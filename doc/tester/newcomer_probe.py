#!/usr/bin/env python3
"""3C probe (BUG-冷启动-01): a NEW connection must get a frame within 1 tick
even when the content is unchanged (`_SSEConn.sent_any` force-send).

A connects to a live quote group and takes its first frame; B then joins the
same sid a moment later, mid-gap.  The next 4s round is content-unchanged
(TTL==tick aliasing) so the group-wide dedup would skip it — B must still be
fed.  Evidence: B's first frame arrives <= ~1 tick after connecting AND its
content signature equals the frame the group already held.

Read-only: SSE + subscription CRUD.
"""
import sys
import time

sys.path.insert(0, 'doc/tester')
from dedup_probe import SSEClient, api, create  # noqa: E402


def main():
    _, st, resp = create(['quote'])
    sid = resp['sid']
    print('sid', sid, st)
    A = SSEClient(sid, 22, 'A')
    A.start()
    A.ready.wait(5)

    def a_quotes():
        return [f for f in A.frames if f.get('event') == 'quote']

    for _ in range(200):                     # wait for A's first frame
        if a_quotes():
            break
        time.sleep(0.05)
    first = a_quotes()[0]
    print('A first frame rel_conn=%.3f sig=%s' % (first['rel_conn'], first['sig']))

    time.sleep(0.5)                          # mid-gap, after the send
    B = SSEClient(sid, 16, 'B')
    B.start()
    B.join(25)

    bq = [f for f in B.frames if f.get('event') == 'quote']
    print('B errors', B.errors, 'n_quote', len(bq))
    if bq:
        print('B first frame rel_conn=%.3f sig=%s' % (bq[0]['rel_conn'], bq[0]['sig']))
        print('B first rel_conn <= 4.5s ?', bq[0]['rel_conn'] <= 4.5)
        print('B first content == A first content (unchanged, force-fed) ?',
              bq[0]['sig'] == first['sig'])
        print('B intervals', [round(b['rel_conn'] - a['rel_conn'], 2)
                              for a, b in zip(bq, bq[1:])])
    st2, d = api('DELETE', f'/stream/subscriptions/{sid}')
    print('DELETE', st2, d)


if __name__ == '__main__':
    main()
