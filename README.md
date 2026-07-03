# China Finance RSS Bridge

Tiny RSS feeds for Chinese financial news: CLS, Eastmoney, THS, Jin10,
Wallstreetcn, and optional Xueqiu.

## Start

```bash
python server.py
```

Open `http://localhost:8053/`.

## Feeds

| Source | RSS URL | Notes |
| --- | --- | --- |
| CLS 财联社 | `http://localhost:8053/cls/telegraph` | Real-time flashes |
| Eastmoney 东方财富 | `http://localhost:8053/eastmoney/kuaixun` | 7x24 news |
| THS 同花顺 | `http://localhost:8053/ths/kuaixun` | 7x24 news |
| Jin10 金十 | `http://localhost:8053/jin10/flash` | 7x24 news |
| Wallstreetcn 华尔街见闻 | `http://localhost:8053/wallstreetcn/live` | 7x24 news |
| Xueqiu 雪球 | `http://localhost:8053/xueqiu/user/{uid}` | Requires Chrome CDP |

Import all built-in feeds with OPML:

```text
http://localhost:8053/opml.xml
```

## JSON Data Endpoints (Chrome CDP required)

These endpoints collect real-time market data via a headless Chrome tab
(DevTools Protocol). Start the bridge normally — Chrome auto-starts.

| Endpoint | Description |
| --- | --- |
| `/finance/market` | CLS market overview: heat, index, stock pools, live feed |
| `/quotation/market` | CLS quotation: sectors, rankings, NEEQ/BSE, 涨停 data |
| `/stock/data?code=sz300139` | Single-stock detail (price, timeline, news, fundamentals) |

The stock endpoint requires `?code=` with any CLS stock symbol
(e.g. `/stock/data?code=sh600519`). Data is collected from a single
persistent tab that navigates on demand — no per-request tab overhead.

Check upstream source status:

```text
http://localhost:8053/healthz?check=1
```

## Configure Only If Needed

| Variable | Default | Use |
| --- | --- | --- |
| `PORT` | `8053` | Change the server port |
| `CACHE_TTL` | `300` | Cache upstream responses |
| `REQUEST_TIMEOUT` | `10` | Timeout for upstream requests |
| `PUBLIC_BASE_URL` | auto | Public URL for OPML and RSS self links |
| `CDP_URL` | `http://localhost:9222` | Chrome DevTools URL for CDP pages |
| `MAX_WORKERS` | `10` | Max concurrent request threads (lower for low-memory servers) |


Configuration names are public. Do not commit `.env` files, cookies, tokens,
private keys, Chrome profiles, or HAR captures.

## Xueqiu Optional Setup

Xueqiu blocks direct API requests. This bridge can fetch through a logged-in
Chrome tab via Chrome DevTools Protocol.

1. Install the optional dependency:
   ```bash
   pip install websocket-client
   ```
2. Start Chrome with remote debugging:
   ```bash
   /Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --remote-debugging-port=9222 --remote-allow-origins=*
   ```
3. Open Xueqiu in Chrome and log in.
4. Run the bridge:
   ```bash
   CDP_URL=http://localhost:9222 python server.py
   ```

Keep the CDP port local or on a trusted private network.

## Docker

```bash
docker build -t china-finance-rss .
docker run -d -p 8053:8053 --name china-finance-rss china-finance-rss
```

For 2C2G servers (2 core, 2GB RAM), limit memory and **disable swap**
(Chrome under swap causes CDP heartbeat timeouts). 2GB is recommended
when using stock detail queries at 10+ concurrency; 1GB suffices for RSS
feeds + market overview only:

```bash
# 2GB (heavy stock query load)
docker run -d --memory=2g --memory-swap=2g --memory-reservation=1g \
  -p 8053:8053 --name china-finance-rss china-finance-rss

# 1GB (RSS feeds + market overview only)
docker run -d --memory=1g --memory-swap=1g --memory-reservation=768m \
  -p 8053:8053 --name china-finance-rss china-finance-rss
```

Stress test results (2GB 2C, concurrency=10, 30 stock detail queries):
**100% success** — 0 failures, 0 data mismatches, 0 zombie tabs,
peak memory 630MiB, p95 latency 6.6s. The single persistent tab
approach ensures memory is reclaimed after each test cycle.

Behind a reverse proxy:

```bash
docker run -d -p 8053:8053 \
  -e PUBLIC_BASE_URL=https://rss.example.com \
  --name china-finance-rss china-finance-rss
```

## Notes

- CLS, Eastmoney, THS, Jin10, and Wallstreetcn use public web endpoints.
- Xueqiu uses your local browser session but does not store or print cookies.
- If an upstream source breaks, the feed stays valid and includes a diagnostic
  item. Use `/healthz?check=1` to see which source failed.
- Run `python tests/freshness_test.py --duration 300` to monitor CDP data
  update frequency during market hours.
- Run `python tests/stress_stock.py --concurrency 5 --total 20` to stress-test
  the stock detail endpoint with multiple real stock codes.

## CDP Architecture

The bridge uses headless Chrome DevTools Protocol for two kinds of pages:

- **Heartbeat pages** (`/finance/market`, `/quotation/market`): a persistent
  tab with a background thread that polls collected data every 10s, supports
  TTL expiry and proactive API re-fetch. Data is served from an in-memory
  cache — zero-latency for callers.
- **On-demand page** (`/stock/data`): a single persistent tab that navigates
  to the requested stock code on each query. No heartbeat, no background
  polling. A re-entrant lock serializes concurrent requests. Chrome crash
  self-heals via `ensure_chrome()`.

The interceptor JS (`cdp_engine.py:INTERCEPTOR_JS`) hooks `fetch` and
`XMLHttpRequest` to capture JSON API responses into `window.__cdp_api`,
which is read by `Runtime.evaluate` on each refresh cycle.

## 中文简版

启动：

```bash
python server.py
```

打开 `http://localhost:8053/`，把页面里的 RSS 地址加到阅读器。内置源包括
财联社、东方财富、同花顺、金十、华尔街见闻和可选雪球。阅读器支持 OPML
的话，直接导入 `http://localhost:8053/opml.xml`。

如果订阅为空或不更新，打开 `http://localhost:8053/healthz?check=1` 看是哪
个上游源失败。

通过 CDP 自动采集的实时行情数据：
- `/finance/market` — 盘面热度、指数、股票池、盘口
- `/quotation/market` — 板块、排名、北交所、涨停数据
- `/stock/data?code=sz300139` — 个股详情（股价、分时图、新闻、基本面）

雪球需要 Chrome CDP 和已登录的本地浏览器标签页；不要把 CDP 端口暴露到公网，
也不要提交 cookies、tokens、`.env`、Chrome profile 或 HAR 文件。

## License

MIT
