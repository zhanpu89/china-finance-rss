"""RSS/OPML generation, item parsers, and auth/helper utilities."""

import hashlib
import json
import re
from datetime import datetime, timezone, timedelta
from email.utils import formatdate
from html import unescape
from urllib.parse import urlencode
from xml.etree import ElementTree as ET

from config import CACHE_TTL, PUBLIC_BASE_URL, jin10_public_headers
from cache import fetch_json, _cache_lock, _cache_put


def escape_xml(text):
    """Escape special XML characters."""
    return (str(text)
            .replace('&', '&amp;')
            .replace('<', '&lt;')
            .replace('>', '&gt;')
            .replace('"', '&quot;')
            .replace("'", '&apos;'))


def timestamp_to_rfc822(ts):
    """Convert Unix timestamp to RFC 822 date string."""
    return formatdate(timeval=ts, localtime=False, usegmt=True)


def parse_china_datetime_to_rfc822(value):
    """Parse a China-local datetime string into an RFC 822 UTC date."""
    dt = datetime.strptime(value, '%Y-%m-%d %H:%M:%S')
    dt = dt.replace(tzinfo=timezone(timedelta(hours=8)))
    return formatdate(timeval=dt.timestamp(), localtime=False, usegmt=True)


def strip_html(text):
    """Strip simple HTML tags from upstream snippets."""
    text = re.sub(r'<[^>]+>', '', str(text or ''))
    return unescape(re.sub(r'\s+', ' ', text)).strip()


def clean_title(text, max_len=120):
    """Truncate title to first sentence, max max_len chars."""
    text = text.strip()
    if len(text) <= max_len:
        return text
    truncated = text[:max_len]
    for punct in ('。', '！', '？', '；', '\n'):
        idx = truncated.rfind(punct)
        if idx > max_len // 3:
            return text[:idx + 1]
    for punct in ('，', ', '):
        idx = truncated.rfind(punct)
        if idx > max_len // 3:
            return text[:idx]
    return truncated + '…'


def cls_serialize_sign_value(value, key):
    """Serialize a value the same way the CLS frontend signs params."""
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return f'{key}={value}'
    if isinstance(value, list):
        if not value:
            return f'{key}[]'
        return '&'.join(filter(None, (
            cls_serialize_sign_value(item, f'{key}[{index}]')
            for index, item in enumerate(value)
        )))
    if isinstance(value, dict):
        return '&'.join(filter(None, (
            cls_serialize_sign_value(value[item_key], f'{key}[{item_key}]')
            for item_key in sorted(value, key=lambda item: str(item).upper())
        )))
    return None


def cls_sign_params(params):
    """Sign CLS request params using the public web frontend algorithm."""
    serialized = '&'.join(filter(None, (
        cls_serialize_sign_value(params[key], key)
        for key in sorted(params, key=lambda item: str(item).upper())
    )))
    sha1_digest = hashlib.sha1(serialized.encode('utf-8')).hexdigest()
    return hashlib.md5(sha1_digest.encode('utf-8')).hexdigest()


def extract_jin10_public_app_id(bundle_text):
    """Extract Jin10's public frontend app id from its web bundle."""
    match = re.search(r'"x-app-id":"([^"]+)"', bundle_text)
    if not match:
        raise ValueError('Jin10 public app id not found in frontend bundle')
    return match.group(1)


def get_jin10_public_headers():
    """Build Jin10 headers from public frontend assets without hardcoded ids."""
    global jin10_public_headers
    with _cache_lock:
        if jin10_public_headers:
            return dict(jin10_public_headers)

    base_headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://www.jin10.com/'}
    html = fetch_json('https://www.jin10.com/', base_headers)
    script_match = re.search(r'(?:https:)?//www\.jin10\.com/new/js/index\.[^"\']+\.js', html)
    if not script_match:
        script_match = re.search(r'/new/js/index\.[^"\']+\.js', html)
    if not script_match:
        raise ValueError('Jin10 frontend bundle not found')

    script_url = script_match.group(0)
    if script_url.startswith('//'):
        script_url = 'https:' + script_url
    elif script_url.startswith('/'):
        script_url = 'https://www.jin10.com' + script_url

    bundle = fetch_json(script_url, base_headers)
    app_id = extract_jin10_public_app_id(bundle)

    with _cache_lock:
        if jin10_public_headers:
            return dict(jin10_public_headers)
        jin10_public_headers = {
            'User-Agent': 'Mozilla/5.0',
            'Accept': 'application/json,text/plain,*/*',
            'Referer': 'https://www.jin10.com/',
            'Origin': 'https://www.jin10.com',
            'x-app-id': app_id,
            'x-version': '1.0.0',
        }
    return dict(jin10_public_headers)


def warm_jin10_headers():
    try:
        get_jin10_public_headers()
    except Exception:
        pass


# ── RSS / OPML generation ──────────────────────────────────────────────────

def generate_rss(title, link, description, items, feed_url=None):
    """Generate standard RSS 2.0 XML."""
    xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
<channel>
<title>{escape_xml(title)}</title>
<link>{escape_xml(link)}</link>
<description>{escape_xml(description)}</description>
<lastBuildDate>{formatdate(timeval=None, localtime=False, usegmt=True)}</lastBuildDate>
'''
    if feed_url:
        xml += (f'<atom:link href="{escape_xml(feed_url)}" rel="self" '
                'type="application/rss+xml"/>\n')

    for item in items:
        xml += '<item>\n'
        xml += f'<title>{escape_xml(item["title"])}</title>\n'
        xml += f'<link>{escape_xml(item["link"])}</link>\n'
        xml += f'<description>{escape_xml(item["description"])}</description>\n'
        xml += f'<pubDate>{item["pubDate"]}</pubDate>\n'
        xml += f'<guid isPermaLink="false">{escape_xml(item["guid"])}</guid>\n'
        xml += '</item>\n'

    xml += '</channel>\n</rss>'
    return xml


def generate_error_rss(title, link, description, error, feed_url=None):
    """Generate a valid RSS feed that explains an upstream failure."""
    error_text = str(error) or error.__class__.__name__
    items = [{
        'title': f'{title} temporarily unavailable',
        'link': link,
        'description': f'Upstream fetch failed: {error_text}',
        'pubDate': formatdate(timeval=None, localtime=False, usegmt=True),
        'guid': f'error_{title}'
    }]
    return generate_rss(title, link, description, items, feed_url=feed_url)


def generate_opml(base_url, routes):
    """Generate an OPML subscription list for all built-in feeds."""
    base_url = (base_url or '').rstrip('/')
    xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<opml version="2.0">
<head>
<title>China Finance RSS Bridge feeds</title>
</head>
<body>
<outline text="China Finance RSS Bridge" title="China Finance RSS Bridge">
'''
    for path, info in routes.items():
        xml += (f'<outline text="{escape_xml(info["name"])}" title="{escape_xml(info["name"])}" '
                f'type="rss" xmlUrl="{escape_xml(base_url + path)}"/>\n')

    xml += '</outline>\n</body>\n</opml>'
    return xml


def count_rss_items(xml):
    """Return the number of RSS items in a generated feed."""
    root = ET.fromstring(xml)
    return len(root.findall('./channel/item'))


# ── Item parsers ────────────────────────────────────────────────────────────

def parse_cls_items(payload):
    """Convert CLS roll_data payload into RSS item dictionaries."""
    items = []
    for item in payload.get('data', {}).get('roll_data', []):
        item_id = item.get('id', '')
        content = item.get('content', '')
        title = clean_title(item.get('brief') or content, max_len=120)
        items.append({
            'title': title,
            'link': f'https://www.cls.cn/detail/{item_id}',
            'description': content,
            'pubDate': timestamp_to_rfc822(item.get('ctime', 0)),
            'guid': f'cls_{item_id}',
        })
    return items


def parse_jin10_items(payload):
    """Convert Jin10 flash API payload into RSS item dictionaries."""
    items = []
    for item in payload.get('data', []):
        item_id = item.get('id', '')
        data = item.get('data') or {}
        title = data.get('title') or strip_html(data.get('content', ''))[:100]
        content = strip_html(data.get('content') or title)
        link = data.get('source_link') or f'https://flash.jin10.com/detail/{item_id}'
        try:
            pubdate = parse_china_datetime_to_rfc822(item.get('time', ''))
        except Exception:
            pubdate = formatdate(timeval=None, localtime=False, usegmt=True)

        items.append({
            'title': title,
            'link': link,
            'description': content,
            'pubDate': pubdate,
            'guid': f'jin10_{item_id}',
        })
    return items


def parse_wallstreetcn_items(payload):
    """Convert Wallstreetcn live API payload into RSS item dictionaries."""
    items = []
    for item in payload.get('data', {}).get('items', []):
        item_id = item.get('id', '')
        description = item.get('content_text') or strip_html(item.get('content', ''))
        title = item.get('title') or description[:100]
        pub_ts = item.get('display_time') or item.get('created_at') or 0

        items.append({
            'title': title,
            'link': item.get('uri') or f'https://wallstreetcn.com/livenews/{item_id}',
            'description': description,
            'pubDate': timestamp_to_rfc822(int(pub_ts)),
            'guid': f'wallstreetcn_{item_id}',
        })
    return items
