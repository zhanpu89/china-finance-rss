# China Finance RSS Bridge

Tiny RSS bridge + JSON APIs for Chinese financial data: CLS (财联社),
Eastmoney (东方财富), THS (同花顺), Jin10 (金十数据), Wallstreetcn (华尔街见闻).

## Start

```bash
python server.py
```

Open `http://localhost:8053/`.

## RSS Feeds

| Source | RSS URL |
| --- | --- |
| CLS 财联社 | `http://localhost:8053/cls/telegraph` |
| Eastmoney 东方财富 | `http://localhost:8053/eastmoney/kuaixun` |
| THS 同花顺 | `http://localhost:8053/ths/kuaixun` |
| Jin10 金十 | `http://localhost:8053/jin10/flash` |
| Wallstreetcn 华尔街见闻 | `http://localhost:8053/wallstreetcn/live` |

Import all at once with OPML:

```text
http://localhost:8053/opml.xml
```

## JSON Stock APIs

All require `?code=` with stock symbols (e.g. `?code=sh600519` or `?code=sh600519,sz000001`).

| Endpoint | Description | CDP |
| --- | --- | --- |
| `/stock/data` | Stock detail (price, announcements, related sectors, articles) | Yes |
| `/stock/fundflow` | Capital flow (主力/超大/大/中/小单净流入) | No |
| `/stock/timeline` | Intraday price timeline | No |
| `/stock/f10` | Company fundamentals & financials | Yes |
| `/stock/basic_info` | Real-time quote + sector name (申万一级行业) | Yes |
| `/stock/announcement` | Company announcements | No |

## JSON Market APIs

| Endpoint | Description | CDP |
| --- | --- | --- |
| `/finance/market` | Market overview: sentiment, indices, advance/decline | Yes |
| `/finance/timeline` | Finance index timeline | Yes |
| `/quotation/market` | Quotation: sectors, rankings, IPOs, BSE | Yes |
| `/market/timeline` | Index intraday timeline | Yes |
| `/cls/hotplate` | Sector capital flow rankings (行业/概念/地域) | No |
| `/ths/longhu` | THS 龙虎榜 (top buy/sell brokerages) | No |
| `/market/margin` | 融资融券 (margin lending balance) | No |
| `/market/northbound` | 北向资金 snapshot (沪深港通) | No |
| `/market/northbound/history` | 北向资金 history by period | No |

## Health Check

```text
http://localhost:8053/healthz?check=1
```

## Environment Variables

| Variable | Default | Description |
| --- | --- | --- |
| `PORT` | `8053` | Server port |
| `CACHE_TTL` | `300` | Cache TTL (seconds) |
| `REQUEST_TIMEOUT` | `10` | Upstream request timeout |
| `PUBLIC_BASE_URL` | auto | Public URL for RSS self-links & OPML |
| `CDP_URL` | `http://localhost:9222` | Chrome DevTools URL |
| `MAX_WORKERS` | `20` | Max concurrent request threads |

Do not commit `.env` files, cookies, tokens, private keys, Chrome profiles, or HAR captures.

## CDP Setup (Optional)

Some endpoints require Chrome CDP (headless browser). Install the dependency:

```bash
pip install websocket-client
```

Chrome auto-starts on first request. Or attach an existing browser:

```bash
google-chrome --headless --remote-debugging-port=9222 --remote-allow-origins=*
```

Then start the bridge — CDP endpoints activate automatically.

## Architecture

The bridge uses Chrome DevTools Protocol for two page types:

- **Heartbeat pages** (`/finance/market`, `/quotation/market`): persistent tabs with a background thread polling collected data every 10s.
- **Navigation pages** (14 stock pages + 1 F10 page): on-demand navigation to stock codes, serialized via per-page fair locks.

The interceptor JS hooks `fetch`, `XHR`, and `WebSocket` to capture JSON API responses into `window.__cdp_api`.

REST-based endpoints (`fundflow`, `timeline`, `announcement`) use direct HTTP first, with CDP `evaluate_fetch` as fallback for anti-bot bypass.

## Docker

```bash
docker build -t china-finance-rss .
docker run -d -p 8053:8053 --name china-finance-rss china-finance-rss
```

Memory recommendations:

```bash
# 2GB — heavy stock query load
docker run -d --memory=2g --memory-swap=2g --memory-reservation=1g \
  -p 8053:8053 --name china-finance-rss china-finance-rss

# 1GB — RSS feeds + market overview only
docker run -d --memory=1g --memory-swap=1g --memory-reservation=768m \
  -p 8053:8053 --name china-finance-rss china-finance-rss
```

Behind a reverse proxy:

```bash
docker run -d -p 8053:8053 \
  -e PUBLIC_BASE_URL=https://rss.example.com \
  --name china-finance-rss china-finance-rss
```

## Notes

- All RSS sources use public web endpoints; no login required.
- If an upstream source fails, the feed stays valid with a diagnostic item.
- Use `/healthz?check=1` to identify faulty sources.
- See `API.md` for detailed request/response field documentation.

## License

MIT
