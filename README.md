# China Finance RSS Bridge

Tiny RSS bridge + JSON APIs for Chinese financial data: CLS (财联社),
Eastmoney (东方财富), THS (同花顺), Jin10 (金十数据), Wallstreetcn (华尔街见闻).

## Start

```bash
python -m china_finance_rss.server
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

RSS responses carry a weak `ETag` and support conditional requests: send
`If-None-Match` and an unchanged feed returns **`304 Not Modified` with no body**
(no `Content-Encoding` either). Poll with `If-None-Match` at ≥30s — each feed also
carries `<ttl>` (minutes), which is an **advisory cache hint, not a freshness
promise**; for fresher-than-a-minute news use the SSE stream on port 8054 (4s).
304 saves the response body, not the upstream fetch. See `API.md` §1 and §6.3.

## JSON Stock APIs

All require `?code=` with stock symbols (e.g. `?code=sh600519` or `?code=sh600519,sz000001`).

| Endpoint | Description | CDP |
| --- | --- | --- |
| `/stock/data` | Stock detail: labels, sectors, event/up-reason (REST) | No |
| `/stock/fundflow` | Capital flow (主力/超大/大/中/小单净流入) | No |
| `/stock/timeline` | Intraday price timeline | No |
| `/stock/f10` | Company fundamentals & financials | Yes |
| `/stock/basic_info` | Real-time quote + **order book (五档, `depth`)** + sector name (申万一级行业) | No |
| `/stock/announcement` | Company announcements | No |

Codes accept `sh`/`sz`/**`bj`** (北交所) equally; dotted forms (`600519.SH`, `430047.BJ`) are normalized at ingress.

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

## Health Check

```text
http://localhost:8053/healthz?check=1
```

## Environment Variables

| Variable | Default | Description |
| --- | --- | --- |
| `PORT` | `8053` | Server port |
| `REQUEST_TIMEOUT` | `10` | Upstream request timeout |
| `PUBLIC_BASE_URL` | auto | Public URL for RSS self-links & OPML |
| `CDP_URL` | `http://localhost:9222` | Chrome DevTools URL |
| `MAX_WORKERS` | `20` | Max concurrent request threads |
| `BATCH_MAX_WORKERS` | `20` | Per-batch upstream fan-out (keep ≤ `HTTP_POOL_MAX_PER_HOST`) |
| `STREAM_PER_FETCH_EST` | `0.3` | Per-fetch seconds used by the SSE refresh-capacity model |
| `HTTP_POOL_MAX_PER_HOST` | `24` | Keep-alive connections kept per upstream host |
| `HTTP_POOL_IDLE_TTL` | `60` | Idle keep-alive connection eviction (s) |
| `HTTP_DNS_CACHE_TTL` | `300` | In-process DNS cache TTL (s); `0` disables |
| `HTTP_WARM_CONNECTIONS` | `1` | Connections pre-warmed per upstream host at startup |
| `HTTP_WARM_TIMEOUT` | `2.0` | Warm-up dial timeout (s); failures are silent |
| `LISTEN_BACKLOG` | `128` | TCP accept backlog; keep ≥ `MAX_INFLIGHT` and ≥ `MAX_STREAM_CONNS` |
| `STREAM_HOST` | `127.0.0.1` | SSE listen addr; set `0.0.0.0` for cross-host/container access (no-auth mgmt surface) |
| `CDP_RESTART_THROTTLE` | `15` | Full Chrome restart throttle (s); guards the `full_chrome_restart` lock (×2 = no re-restart within 30s) |
| `STREAM_GROUP_IDLE_TTL` | `300` | Idle zombie subscription-group reaper (s); a group with no live connection is destroyed after this — clients must re-POST `/stream/subscriptions` after a long disconnect |

> Cache TTL is **per data-domain and trading-hours aware** (`config.cache_policy`, single source of truth) — it is no longer a single env var. Examples: `quote`/`depth` **4s** (trading) / 120s (off-hours), RSS/`news_url` 30s / 180s, `fundflow`/`timeline` 8s / 120s, `plate` 12s / 120s, `f10`/`longhu` 300s, `margin` 600s, `sector` 7d. Upstream failures are rate-limited by a negative cache (5s) plus an escalating probe budget (2→4→5s). Upstream HTTP is pooled with keep-alive + in-process DNS caching.

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
- **Navigation pages** (`CDP_STOCK_PAGES` stock pages, default 3 / 2C2G profile 4, plus 1 F10 page): on-demand navigation to stock codes, serialized via per-page fair locks.

The interceptor JS hooks `fetch`, `XHR`, and `WebSocket` to capture JSON API responses into `window.__cdp_api`.

REST-based endpoints (`fundflow`, `timeline`, `announcement`) use direct HTTP first, with CDP `evaluate_fetch` as fallback for anti-bot bypass.

## Docker

```bash
docker build -t china-finance-rss .
docker run -d -p 8053:8053 -p 8054:8054 \
  -e STREAM_HOST=0.0.0.0 --name china-finance-rss china-finance-rss
```

Memory recommendations:

```bash
# 2GB — heavy stock query load
docker run -d --memory=2g --memory-swap=2g --memory-reservation=1g \
  -p 8053:8053 -p 8054:8054 --name china-finance-rss china-finance-rss

# 1GB — RSS feeds + market overview only
docker run -d --memory=1g --memory-swap=1g --memory-reservation=768m \
  -p 8053:8053 -p 8054:8054 --name china-finance-rss china-finance-rss
```

Behind a reverse proxy:

```bash
docker run -d -p 8053:8053 -p 8054:8054 \
  -e PUBLIC_BASE_URL=https://rss.example.com \
  -e STREAM_HOST=0.0.0.0 \
  --name china-finance-rss china-finance-rss
```

## Scheduled Restart (workaround for stale cache)

On low-spec hosts (e.g. 2C2G) the in-memory cache may stop being reclaimed
after running for days, so consumers keep receiving old data until the stack
is restarted. A daily recycle of the stack clears it without changing the app.

`scripts/restart-stack.sh` performs a clean `docker compose down && docker compose up -d`
and logs to `logs/restart.log`. Install it on the **host** crontab to run daily at 02:00:

```bash
# From the project root on the host server:
( crontab -l 2>/dev/null; echo "0 2 * * * $(pwd)/scripts/restart-stack.sh" ) | crontab -
crontab -l   # verify
```

The schedule follows the host's local timezone — set the host timezone to
`Asia/Shanghai` if you want 02:00 to mean Beijing time. The container itself is
already configured to `Asia/Shanghai` (see `TZ` in the `Dockerfile`), which fixes
the 8-hour offset seen in container timestamps/logs.

## Notes

- All RSS sources use public web endpoints; no login required.
- If an upstream source fails, the feed stays valid with a diagnostic item.
- Use `/healthz?check=1` to identify faulty sources.
- See `API.md` for detailed request/response field documentation.

## License

MIT
