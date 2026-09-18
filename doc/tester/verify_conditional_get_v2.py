#!/usr/bin/env python3
"""verify_conditional_get_v2.py — deployment E2E re-verification of the RSS
conditional-GET P8 fixes (F1-F8) on a *running* container.

Stdlib only; re-runnable offline:

    python3 doc/tester/verify_conditional_get_v2.py --out /tmp/v2.json

Checks:
  F1  cross-TTL regeneration: <lastBuildDate> advances while ETag and
      Last-Modified stay byte-identical, and If-Modified-Since *alone* -> 304.
  F2  Host-keyed cache: two Hosts get distinct ETags and a correct <atom:link>.
  F3  http_304_total (read from /healthz metrics) moves only on a real 304.
  F6  304 header set: no Content-Length/Type/Encoding; ETag/Last-Modified/
      Cache-Control/Vary present and equal to the 200.
  F8  side evidence: `--hosts` distinct Hosts keep the service responsive.
"""
import argparse
import http.client
import json
import re
import time
from datetime import datetime, timezone

LASTBUILD = re.compile(rb'<lastBuildDate>([^<]*)</lastBuildDate>')
SELF = re.compile(rb'<atom:link[^>]*rel="self"[^>]*>')
FORBIDDEN_304 = ('content-length', 'content-type', 'content-encoding')
REQUIRED_304 = ('etag', 'last-modified', 'cache-control', 'vary')


def iso():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def call(host, port, method, path, headers=None, timeout=30):
    """One fresh HTTP/1.0 request; returns status/reason/headers/body."""
    c = http.client.HTTPConnection(host, port, timeout=timeout)
    try:
        c.request(method, path, headers=headers or {})
        r = c.getresponse()
        hdrs = {}
        for k, v in r.getheaders():
            hdrs.setdefault(k.lower(), v)
        body = r.read()
        status, reason = r.status, r.reason
    finally:
        c.close()
    return {'status': status, 'reason': reason, 'headers': hdrs, 'body': body}


def health(host, port):
    return json.loads(call(host, port, 'GET', '/healthz?check=0')['body'])


def hdrs_only(d):
    return {k: d['headers'][k] for k in sorted(d['headers'])}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--host', default='127.0.0.1')
    ap.add_argument('--port', type=int, default=8053)
    ap.add_argument('--path', default='/cls/telegraph')
    ap.add_argument('--wait', type=float, default=None,
                    help='seconds to cross one TTL (default: live ttl + 15)')
    ap.add_argument('--hosts', type=int, default=50)
    ap.add_argument('--out', default=None)
    ap.add_argument('--skip-f8', action='store_true')
    a = ap.parse_args()

    ev = {'generated_at': iso(), 'target': f'http://{a.host}:{a.port}',
          'feed': a.path, 'checks': {}, 'steps': []}
    fails = []

    def rec(name, **kw):
        kw['_ts'] = iso()
        ev['steps'].append({'step': name, **kw})
        return kw

    def check(name, ok, detail=''):
        ev['checks'][name] = {'pass': bool(ok), 'detail': detail}
        if not ok:
            fails.append(name)
        return ok

    def check_304_set(name, d):
        h = d['headers']
        missing = [k for k in REQUIRED_304 if k not in h]
        present_forbidden = [k for k in FORBIDDEN_304 if k in h]
        ok = (d['status'] == 304 and not missing and not present_forbidden
              and d['body'] == b'')
        return check(name, ok,
                     f'status={d["status"]} missing={missing} '
                     f'forbidden={present_forbidden} body_len={len(d["body"])}')

    h0 = health(a.host, a.port)
    ttl = h0['policy']['feed']['ttl']
    wait = a.wait if a.wait is not None else ttl + 15
    c0 = h0['metrics']['http_304_total']
    rec('health_baseline', http_304_total=c0, feed_ttl=ttl,
        status=h0.get('status'), tier=h0['policy']['feed']['tier'])

    # ---- first 200 + record validators --------------------------------
    r1 = call(a.host, a.port, 'GET', a.path)
    t1 = time.time()
    h1 = r1['headers']
    et1, lm1 = h1.get('etag'), h1.get('last-modified')
    m = LASTBUILD.search(r1['body'])
    lb1 = m.group(1).decode() if m else None
    rec('first_200', status=r1['status'], etag=et1, last_modified=lm1,
        last_build_date=lb1, content_length=h1.get('content-length'),
        cache_control=h1.get('cache-control'), vary=h1.get('vary'),
        headers=hdrs_only(r1))
    check('first_200', r1['status'] == 200 and et1 and lm1 and lb1,
          f'status={r1["status"]} etag={et1} lm={lm1} lbd={lb1}')

    # ---- F3: a 200 must not move the counter --------------------------
    ha = health(a.host, a.port)
    rec('health_after_200', http_304_total=ha['metrics']['http_304_total'])
    check('F3_200_not_counted', ha['metrics']['http_304_total'] == c0,
          f'before={c0} after200={ha["metrics"]["http_304_total"]}')

    # ---- INM match -> 304 ---------------------------------------------
    d_inm = call(a.host, a.port, 'GET', a.path, {'If-None-Match': et1})
    hb = health(a.host, a.port)
    rec('if_none_match_304', status=d_inm['status'], headers=hdrs_only(d_inm),
        http_304_total=hb['metrics']['http_304_total'])
    check('INM_match_304', d_inm['status'] == 304, f'status={d_inm["status"]}')
    check_304_set('F6_304_header_set_INM', d_inm)
    check('F3_304_counted', hb['metrics']['http_304_total'] == c0 + 1,
          f'before={c0} after1x304={hb["metrics"]["http_304_total"]}')

    # ---- IMS-only -> 304 (same TTL window) ----------------------------
    d_ims = call(a.host, a.port, 'GET', a.path, {'If-Modified-Since': lm1})
    hc = health(a.host, a.port)
    rec('if_modified_since_only_304_same_ttl', status=d_ims['status'],
        headers=hdrs_only(d_ims),
        http_304_total=hc['metrics']['http_304_total'])
    check('IMS_only_304_same_ttl', d_ims['status'] == 304,
          f'status={d_ims["status"]}')
    check('F3_monotonic', hc['metrics']['http_304_total'] == c0 + 2,
          f'expected={c0 + 2} got={hc["metrics"]["http_304_total"]}')

    # ---- priority: INM mismatch wins over IMS match -> 200 ------------
    d_prio = call(a.host, a.port, 'GET', a.path,
                  {'If-None-Match': 'W/"deadbeef"', 'If-Modified-Since': lm1})
    rec('inm_mismatch_ims_match_200', status=d_prio['status'],
        content_length=d_prio['headers'].get('content-length'),
        body_len=len(d_prio['body']))
    check('INM_mismatch_IMS_match_200',
          d_prio['status'] == 200 and len(d_prio['body']) > 1000,
          f'status={d_prio["status"]} body_len={len(d_prio["body"])}')

    # ---- HEAD -> 304 --------------------------------------------------
    d_head = call(a.host, a.port, 'HEAD', a.path, {'If-None-Match': et1})
    rec('head_304', status=d_head['status'], headers=hdrs_only(d_head))
    check_304_set('F6_304_header_set_HEAD', d_head)

    # ---- gzip + INM -> 304, no Content-Encoding -----------------------
    d_gz = call(a.host, a.port, 'GET', a.path,
                {'Accept-Encoding': 'gzip', 'If-None-Match': et1})
    rec('gzip_inm_304', status=d_gz['status'], headers=hdrs_only(d_gz))
    check('gzip_304_no_encoding',
          d_gz['status'] == 304 and 'content-encoding' not in d_gz['headers'],
          f'status={d_gz["status"]} ce={d_gz["headers"].get("content-encoding")}')

    # ---- lower-case w/ is not a weak tag -> 200 -----------------------
    d_low = call(a.host, a.port, 'GET', a.path,
                 {'If-None-Match': 'w/' + et1[2:]})
    rec('lowercase_w_200', status=d_low['status'], body_len=len(d_low['body']))
    check('lowercase_w_200', d_low['status'] == 200,
          f'status={d_low["status"]}')

    seen_304 = sum(1 for d in (d_inm, d_ims, d_head, d_gz)
                   if d['status'] == 304)

    # ---- range regression: non-feed paths ignore conditional headers ---
    d_opml = call(a.host, a.port, 'GET', '/opml.xml', {'If-None-Match': et1})
    d_idx = call(a.host, a.port, 'GET', '/')
    d_json = call(a.host, a.port, 'GET', '/stock/data?code=sh600519',
                  {'If-None-Match': 'W/"deadbeef"',
                   'If-Modified-Since': lm1})
    rec('range_regression', opml={'status': d_opml['status'],
                                  'etag': d_opml['headers'].get('etag'),
                                  'content_type': d_opml['headers'].get('content-type')},
        index_status=d_idx['status'],
        stock_data={'status': d_json['status'],
                    'body_len': len(d_json['body'])})
    check('opml_conditional_200_no_etag',
          d_opml['status'] == 200 and 'etag' not in d_opml['headers'],
          f'status={d_opml["status"]} etag={d_opml["headers"].get("etag")}')
    check('index_200', d_idx['status'] == 200, f'status={d_idx["status"]}')
    check('json_conditional_200', d_json['status'] == 200,
          f'status={d_json["status"]}')

    # ---- F2: cross-Host key isolation ---------------------------------
    a_res = call(a.host, a.port, 'GET', a.path, {'Host': 'a.example'})
    b_res = call(a.host, a.port, 'GET', a.path, {'Host': 'b.example'})
    self_a = SELF.search(a_res['body'])
    self_b = SELF.search(b_res['body'])
    a_self = self_a.group(0).decode() if self_a else None
    b_self = self_b.group(0).decode() if self_b else None
    et_a = a_res['headers'].get('etag')
    et_b = b_res['headers'].get('etag')
    rec('F2_host_isolation', host_a_status=a_res['status'], etag_a=et_a,
        atom_self_a=a_self, host_b_status=b_res['status'], etag_b=et_b,
        atom_self_b=b_self,
        a_example_in_b=('a.example' in b_res['body'].decode('utf-8', 'replace')))
    check('F2_self_link_a', bool(a_self) and 'a.example' in a_self,
          f'self_a={a_self}')
    check('F2_self_link_b', bool(b_self) and 'b.example' in b_self,
          f'self_b={b_self}')
    check('F2_no_cross_host_body', b'a.example' not in b_res['body'],
          'b.example body must not embed a.example')
    check('F2_distinct_etag', et_a != et_b, f'a={et_a} b={et_b}')
    a_cond = call(a.host, a.port, 'GET', a.path,
                  {'Host': 'a.example', 'If-None-Match': et_a})
    rec('F2_host_a_conditional', status=a_cond['status'])
    check('F2_host_a_conditional_304', a_cond['status'] == 304,
          f'status={a_cond["status"]}')
    if a_cond['status'] == 304:
        seen_304 += 1

    # ---- F8: many Hosts must not destabilise the service --------------
    if not a.skip_f8:
        t_f8 = time.time()
        statuses = [call(a.host, a.port, 'GET', a.path,
                         {'Host': f'h{i:02d}.verify.example'})['status']
                    for i in range(a.hosts)]
        rec('F8_many_hosts', count=len(statuses), seconds=round(time.time() - t_f8, 2),
            distinct=sorted(set(statuses)), all_200=all(s == 200 for s in statuses))
        check('F8_many_hosts_responsive', all(s == 200 for s in statuses),
              f'distinct={sorted(set(statuses))}')

    # ---- F1: cross one full TTL ---------------------------------------
    remaining = (t1 + wait) - time.time()
    if remaining > 0:
        time.sleep(remaining)
    r2 = call(a.host, a.port, 'GET', a.path)          # unconditional: prove refetch
    m2 = LASTBUILD.search(r2['body'])
    lb2 = m2.group(1).decode() if m2 else None
    et2 = r2['headers'].get('etag')
    lm2 = r2['headers'].get('last-modified')
    rec('cross_ttl_regenerated', waited=round(time.time() - t1, 1),
        status=r2['status'], last_build_date=lb2, etag=et2, last_modified=lm2,
        content_length=r2['headers'].get('content-length'))
    check('F1_regen_advanced_lastbuilddate', lb2 != lb1,
          f'before={lb1} after={lb2}')
    if et2 == et1:
        check('F1_etag_unchanged_on_regen', True, f'etag={et2}')
        check('F1_lm_unchanged_on_regen', lm2 == lm1,
              f'before={lm1} after={lm2}')
        d_ims2 = call(a.host, a.port, 'GET', a.path,
                      {'If-Modified-Since': lm1})       # IMS ONLY (F1 acceptance)
        rec('cross_ttl_ims_only', status=d_ims2['status'],
            headers=hdrs_only(d_ims2))
        check('F1_IMS_only_cross_ttl_304', d_ims2['status'] == 304,
              f'IMS-only after cross-TTL status={d_ims2["status"]}')
        if d_ims2['status'] == 304:
            seen_304 += 1
    else:
        check('F1_etag_unchanged_on_regen', False,
              f'upstream content changed in window: etag {et1} -> {et2}')
        check('F1_lm_advanced_with_etag', lm2 != lm1,
              f'etag changed; lm {lm1} -> {lm2} (invariant)')

    # ---- F3 final: counter moved exactly with observed 304s -----------
    hf = health(a.host, a.port)
    rec('health_final', http_304_total=hf['metrics']['http_304_total'],
        observed_304=seen_304, baseline=c0)
    check('F3_count_matches_observed_304s',
          hf['metrics']['http_304_total'] == c0 + seen_304,
          f'baseline={c0} observed304={seen_304} '
          f'final={hf["metrics"]["http_304_total"]}')

    ev['pass'] = not fails
    ev['failures'] = fails
    text = json.dumps(ev, ensure_ascii=False, indent=2)
    if a.out:
        with open(a.out, 'w', encoding='utf-8') as fh:
            fh.write(text)
    print(text)


if __name__ == '__main__':
    main()
