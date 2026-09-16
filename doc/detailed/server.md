# server.py 详细设计

> **版本** v1.3 · **状态** 已同步实现（P7b + **N1 回退** 契约同步 · 以代码为准）· **日期** 2026-09-16 · **作者/产出** task-decomposer
> **v1.3 变更（N1 回退 · 编排层裁决）**：Ⓝ① **业务端点降级恢复 `200 + error 体`**——`_send_json_shape` **恒 `_send_json(payload)`（200）**，不再按 payload 内容判 503；**`_json_payload_has_data` 已删除**（`_guard` 仍产出 `{'error': …}` / `_error` 客体，只是状态码不再随之变化）。Ⓝ② **`_send_json` 去掉 `status` 形参**（签名回落为 `_send_json(data, write_body=True, cache=True)`）。Ⓝ③ **`http_503_total` 计数点 4→3**：仅剩**连接准入拒绝**（`_reject_503`）、**流端口准入拒绝**（`stream._serve_sse` 超 `MAX_STREAM_CONNS`）、**`/healthz`**（其 503 是端点自身语义，**不构成业务端点先例**）。Ⓝ④ **降级体重新可缓存**：`_send_json_shape` 以 `cache=cache` 传参 ⇒ 降级 JSON 按域 TTL 拿 `Cache-Control: public, max-age=<domain ttl>`（v1.2 的"503 ⇒ 不缓存"消失）。
> **v1.2 变更（契约级同步 · 对照表见 §11.1；① 已于 v1.3 回退）**：① ~~**纯 error 包装的 JSON payload ⇒ 503**~~（**已回退，见上**；`_json_payload_has_data` 已删除）② `/healthz` payload 缺 `status` 或含 `error` ⇒ **503**（不只 `status=='degraded'`；**v1.3 保留**）③ `_HealthBatch` 增 **`settle()`**；`build_health_payload` 先建账再调用 + `except BaseException: settle(); raise`；`_run_health_checks(base_url, batch=None)` ④ `_fanout_executor` 的等待受 **`_FANOUT_WAIT_BUDGET=REQUEST_TIMEOUT`** 约束（超期 `cancel()` + `FetchError('upstream_timeout')`）⑤ `_base_url()`：`PUBLIC_BASE_URL` 优先，否则 **Host 格式校验** + `Vary` + `Cache-Control: private`（`_send_text(varies_on_host=…)`）⑥ `_cache_age()` 改用 `urlparse(self.path).path` ⑦ **4 面板的 cache-age 域改 `quote`**（L1，非 `f10` 的 300）⑧ **`/stock/*` 码归一**：`_parse_stock_codes`（canonical 折叠去重）+ `_rekey_batch_response`（响应键回用户原拼写）；截断按归一后码数；非法码值 ⇒ 逐码 `null`（非 400）⑨ **`/market/margin` 非法 `market` ⇒ 400**（`VALID_MARKETS` 前置校验）⑩ `_PANEL_HANDLERS` + `_JSON_DISPATCHED_PATHS` 导入期断言 ⑪ `do_GET`/`do_HEAD` 断连捕获扩为 **`OSError`** ⑫ `BoundedThreadPoolServer.request_queue_size = LISTEN_BACKLOG` ⑬ `handle_ths_longhu` 席位配对 `broker_idx` **无条件自增** + 错位告警；encoding 取自 `cache_policy('longhu')['encoding']` ⑭ import 块更正（`page_data`/`FetchError`/`LISTEN_BACKLOG`；删 `handle_cls_stock`/`fetch_cls_*`/`strip_html`/`escape_xml`）
> **v1.1 变更**：P1-1 healthz 准入位覆盖在飞任务（`_HealthBatch`）· P1-2 `/cls/hotplate`·`/cls/plate`·`/ths/longhu` ≤3 并发（AC-E2）· P1-3 hotplate 全分区失败补顶层 `error` · P1-4 `max_inflight` 形参（流端口显式 110）· P2-1/2/3/4/5 表述收口
> 模块路径 `china_finance_rss/server.py` · 归属 **Layer 3（HTTP 入口 / 编排层）**
> 上游 SAD `doc/arch/SAD.md` **v1.3**（§2.1 D4 + plate stagger · §2.3 D-3/D-5 · §2.4 统一调用顺序 · §2.6 healthz · §3 server.py 行 · ADR-002/006/007/011/012）
> 上游 PRD `doc/prd/perf-stability-optimization.md` v0.3（AC-S1/A5/A8/A9/S5/S7/S8/S10；R1/R2/R4/R15/R17/R19）
> 基础层/数据层接口权威：`config.md` v1.1 · `cache.md` v1.1 · `metrics.md` v1.1 · `stock_api.md` v1.0 · `market_api.md` v1.0 · `cdp_engine.md` v1.0
> 跨模块约定（已锁定）：`doc/detailed/_PROGRESS.md` §B
> 端锁定 🟠 STABLE（**不改路由、不改 API 签名**；仅 `/healthz` 只增字段 + `feeds[].status` 取值修正〔待编排层批准/同步〕）

## 1. 模块职责与边界

### 1.1 职责（8 条）

1. **路由分发（唯一入口）**：`RSSHandler._handle_request` 分派 `14 个 JSON 分支 + 5 个 RSS + / + /opml.xml + /healthz`；**shape 由 `_JSON_SHAPES` 路由表派生**（SAD §2.4「由路由表派生 shape、不写死数字」）。
2. **统一异常边界 `_guard(fn, *, shape, ...)`**：任何 handler 异常**不冒泡**（R1），按 `shape ∈ {batch, object, rss, text}` 产出结构化降级体。
3. **feed 缓存防击穿 + 双检**：`_get_or_fetch_feed` 只保留 `_feed_fetch_locks` per-path 锁；LRU / TTL / 清扫**全部委托** `cache.feed_cache_get/feed_cache_put`（缓存机制归缓存层，裁决 #3）。
4. **plate 三档 stagger 派生**（SAD §2.1 D-7 **明令保留**）：`_plate_ttls()` 从 `cache_policy('plate')['ttl']` 派生 `_STAGGER = max(3, ttl // 4)` 与三档 offset，**不得**把三块压成同一 TTL。
5. **批量截断注入（AC-A9）**：`_handle_stock_batch` 计算 `dropped` 并**作为参数**传给 handler（组装点唯一，server **不重复组装**）。
6. **龙虎榜走统一取数入口（R15 / AC-E9）**：`/ths/longhu` 的两个上游 URL 改走 `fetch_json(..., encoding='gbk')` + `cache_policy('longhu')['ttl']`，删除直连 `urlopen`。
7. **healthz 改造（AC-S8 / R2 / R19）**：`check=0` 零上游快路径；`check=1` 专用执行器 + `BoundedSemaphore(MAX_HEALTH_INFLIGHT)` **有界准入**（stale 可达可测），且**准入位覆盖该批任务的真实在飞**（`_HealthBatch`，修 P1-1；`settle()` 覆盖异常路径 P1-5）；payload 保留既有 4 键 + 新增 `stale`/`metrics`/`policy`/`cdp`。**HTTP 503 判定**：`payload` 缺 `status` 或含 `error` ⇒ 503（guard 失败体不再像健康）**或** `status=='degraded'` ⇒ 503（计入 `http_503_total`）。
7′. **外部上游并发扇出（AC-E2 / SAD §4.1）**：`/cls/hotplate`（3 分区）、`/cls/plate`（3 段）、`/ths/longhu`（2 URL）一律经 `_get_fanout_executor()` **≤3 并发**取数（`max_workers=3`），使单端点耗时 = `max` 而非 `sum`（≤ `REQUEST_TIMEOUT`=10s ≤ AC-E2 的 15s）；等待受 `_FANOUT_WAIT_BUDGET=REQUEST_TIMEOUT` 界，超期 `cancel()` + `FetchError('upstream_timeout')`。
8. **过载有界拒绝（AC-E8 / S5）+ CDP 守护委派（ADR-012）**：`MAX_INFLIGHT` 显式化，达上限**立即 503 不排队**并计 `http_503_total`；`_cdp_memory_watchdog` 改调 `cdp_engine.watchdog_restart_skip_reason()`（盘中避让判断集中化）。
9. **JSON 端点降级 = `200 + error 体`（★ v1.3 / N1 回退）**：`object`/`batch`/`text` shape 的 payload **不因内容改变状态码**——上游/CDP 整体不可用时 `_guard` 产出的 `{'error': …}` / `_error` 客体仍以 **HTTP 200** 返回（与旧版本及既有业务系统消费的契约一致）。**真实 503 仅三条路径**：连接准入拒绝（`BoundedThreadPoolServer._reject_503`）、流端口准入拒绝（`stream._serve_sse` 超 `MAX_STREAM_CONNS`）、`/healthz`（端点自身语义，**不是业务端点先例**）。`_send_json_shape` 只做"从表读 shape + 调 handler + 发 200 JSON"。~~v1.2 的 `_json_payload_has_data` / error-only ⇒ 503 已删除~~。
10. **码身份归一（P1-6）**：`/stock/*` 入口经 `_parse_stock_codes` 折叠（`config.canonical_code`）去重后再计 `_MAX_BATCH_SIZE`；响应经 `_rekey_batch_response` 回请求原拼写，值与键集**不因归一而变**。

### 1.2 明确不做

- **不实现缓存机制**（LRU / 清扫 / 淘汰 / 负缓存）→ `cache.py`；本模块只调 `feed_cache_get/put`。
- **不实现帧计费与 SSE**（`_Frame`/`refs`/`stream_queue_bytes`/`_drain_conn_queue`）→ `stream.py`（SAD P2-N6）。
- **不组装批量保留键**（`_errors`/`_truncated`/`_dropped_count`）→ `cache.build_batch_response`；本模块只透传 `dropped`。
- **不实现码级冷却 / 期限贯通 / 分块预算** → `stock_api.py`。
- **不改技术栈、不增删路由、不改 HTTP 方法、不改 handler 业务语义**。
- **不做鉴权 / 多租户 / 前端**（PRD §6）。

### 1.3 layerIsolation 约束

`tech-stack.json` **未对 `server.py` 单列 `layerIsolation` 条目**；须遵守分层方向与 `importRestrictions.allowlist`（`china_finance_rss/*.py` 白名单含 `http`/`urllib`/`json`/`concurrent`/`socket`/`threading`/`time`/`email`/`atexit`/`signal`/`sys`/`os`/`re`/`logging`）。

```
允许 import：
  标准库：atexit / json / logging / os / re / signal / sys / threading / time /
          concurrent.futures.ThreadPoolExecutor,wait,FIRST_COMPLETED /
          email.utils.formatdate / http.server / urllib.parse / urllib.request
  包内  ：config / cache / utils / stock_api / market_api / cdp_engine / metrics
  延迟  ：from .stream import push_loop, run_stream_server   ← 仅 main() 内（打破 server ↔ stream 环，现状保留）
禁止 import：新增第三方库；`china_finance_rss/` 之外的第二个代码根
```

> **新增依赖仅 2 个**：`from . import metrics`（SAD §2.6 计分板的 owner 之一）+ `from .cdp_engine import restart_window_snapshot, watchdog_restart_skip_reason`（ADR-012 / §2.6）。二者均在既有允许面内（`metrics` 为包内模块、`cdp_engine` 为 Layer 内既有依赖）。

### 1.4 依赖方向（`←` 表分层顺序，**非 import 关系**）

```
Layer 0: config（无依赖） ‖ metrics（零业务依赖叶子，与 config 并列、互不依赖）
Layer 1: cache ← {config, metrics}
Layer 2: stock_api / market_api / stream ← {config, cache, metrics}
Layer 3: server ← {stock_api, market_api, stream（延迟 import）, cache, config, metrics, utils}
cdp_engine: 仅依赖 config/metrics；server 调用其函数（config.cdp_engine 全局槽由 server.init_cdp() 写入——config.md §1.4 登记的唯一历史例外）
```

### 1.5 与基础层 / 数据层接口对齐（不得偏离）

| 依赖接口 | 本模块用法（精确） |
|---------|------------------|
| `config.cache_policy(domain, now=None) -> dict` | `cache_policy('feed')['ttl']`（feed 写入 TTL + healthz `cache_ttl`）；`cache_policy('plate')['ttl']`（stagger 基值）；`cache_policy('longhu')['ttl']`（longhu 两 URL）；`cache_policy(d)['ttl']`（`_cache_age`）；`{d: cache_policy(d) for d in sorted(DOMAIN_MATRIX)}`（healthz `policy`） |
| `config.DOMAIN_MATRIX`（公开名） | healthz `policy` 的**域枚举来源**（不写死域清单） |
| `config.MAX_INFLIGHT` | `BoundedThreadPoolServer._max_inflight` 的**默认值**（显式，取代 `max_workers * 2`）；流端口经 `max_inflight` 形参显式覆盖为 `MAX_STREAM_CONNS+10=110`（修 P1-4，见 §2.7/§10#11） |
| `config.MAX_STREAM_CONNS` | **不 import**（属 `stream.py`）；server 只提供 `max_inflight` 形参，取值由 `stream.make_stream_server` 传入 |
| `config.MAX_HEALTH_INFLIGHT` | `_health_sem = threading.BoundedSemaphore(...)` |
| `cache.feed_cache_get(path) -> str \| None` / `cache.feed_cache_put(path, xml, ttl)` | `_get_or_fetch_feed`：miss → per-path 锁 → **二次 get（双检）** → fetch → put |
| `cache.build_batch_response(requested, results, errors=None, dropped=0) -> dict` | `_guard` 的 `batch` 降级体构造（全码 `null` + `_errors[code]='upstream_error'` + `dropped`） |
| `cache.fetch_json(url, headers=None, ttl=None, encoding='utf-8') -> str` | `/ths/longhu` 两 URL（`encoding='gbk'`）；5 个 RSS handler（既有 18 调用点**签名零改动**，仅 `ttl` 来源改 `cache_policy('news_url')['ttl']`，见 §5.11） |
| `cache.FetchError` | 不单点 catch（由 `_guard` 兜底）：RSS → `rss` shape；其它 → 各自 shape |
| `stock_api.handle_cls_*(codes, deadline=None, dropped=0) -> dict` | `_handle_stock_batch` 传 `dropped`（**不重复组装**，`_PROGRESS.md` §B 锁定） |
| `market_api.handle_margin(market='99') -> dict` | 签名不变（调用点零改动） |
| `cdp_engine.page_data(page) -> dict \| None` | 4 面板 handler 防御取数（A 类）；`timeline` 键缺失 → error 客体（**禁止裸 `null`**，R18 旁支） |
| `cdp_engine.restart_window_snapshot() -> dict` | healthz `cdp` 字段 |
| `cdp_engine.watchdog_restart_skip_reason(now=None) -> str \| None` | `_cdp_memory_watchdog` 的**唯一**决策；仅返回 `None` 时调 `full_chrome_restart()` |
| `metrics.incr(name, n=1, key=None)` / `metrics.set_gauge` / `metrics.snapshot()` | `http_503_total` / `healthz_stale_total` / `healthz_inflight` / healthz `metrics` 字段 |

---

## 2. 接口契约

### 2.1 路由总表（OpenAPI 风格，**唯一权威**；路径与 HTTP 方法本次**不变**）

```yaml
openapi: 3.0.3
info: {title: china-finance-rss main port (8053), version: '1.3'}
paths:
  '/':                                {get: {responses: {'200': {content: {text/html: {}}}}}}          # _serve_index（静态，无 IO）
  '/opml.xml':                        {get: {responses: {'200': {content: {'text/x-opml': {}}}}}}      # generate_opml（静态，无 IO）
  '/healthz':                         # shape=object（见 §2.6）
    get:
      parameters:
        - {name: check, in: query, schema: {type: string}, description: "'1'/'true'/'yes' → 真检查；其余/缺省 → 零上游快路径"}
      responses:
        '200': {description: 健康（可能含 stale:true 的降级快照）}
        '503': {description: "body 缺 status / 含 error / status=='degraded'（★ v1.2：不再仅判 degraded；均计 http_503_total）"}
  '/finance/market':                  {get: {responses: {'200': {description: 'object（含真实数据）或降级体 {"error": "Chrome CDP not available…"}（★ v1.3 / N1：降级体亦 200）'}}}}   # shape=object · CDP A 类
  '/finance/timeline':                {get: {responses: {'200': {description: 'object（timeline 缺失 → {"error":...}，仍 200）'}}}}  # shape=object · CDP A 类
  '/quotation/market':                {get: {responses: {'200': {description: object}}}}   # shape=object · CDP A 类
  '/market/timeline':                 {get: {responses: {'200': {description: object}}}}   # shape=object · CDP A 类
  '/cls/hotplate':                    {get: {responses: {'200': {description: 'object（分区 error 客体；三分区全失败 → 顶层补 error，**仍 200**）'}}}}  # shape=object
  '/cls/plate':                       # shape=object；缺 ?code= → 400（在 guard 之前判定）
    get:
      parameters: [{name: code, in: query, required: true, schema: {type: string}, example: cls80484}]
      responses:
        '200': {description: 'object（`info` 分区可独立降级为 error 客体；顶层无 `error` 键，`code` 恒为非空兄弟键）'}
        '400': {description: '{"error": "Missing ?code= parameter. …"}'}
  '/ths/longhu':                      # shape=text（JSON 体、Cache-Control 关闭）；2 个 GBK 上游
    get: {responses: {'200': {description: '{data:[…],total:n} 或 {"error": …}（text shape）'}}}
  '/market/margin':                   # shape=object
    get:
      parameters: [{name: market, in: query, schema: {type: string, default: '99', enum: ['99', '1', '2', '3']}}]
      responses:
        '200': {description: 'margin 成功体，或降级体 {latest, recent, _error}（★ v1.3 / N1：降级体亦 200）'}
        '400': {description: '★ v1.2：market ∉ VALID_MARKETS ⇒ {"error": "Invalid ?market= parameter. Allowed: 99,1,2,3"}'}
  '/stock/data':          {get: {description: 'batch · handler=handle_cls_stock_batch',   responses: {'200': {description: '扁平映射 + 保留键（键 = 请求原拼写）'}, '400': {description: '缺/空 code（非法码值 → 逐码 null，非 400）'}}}}
  '/stock/fundflow':      {get: {description: 'batch · handler=handle_cls_fundflow',      responses: {'200': {}, '400': {}}}}
  '/stock/timeline':      {get: {description: 'batch · handler=handle_cls_timeline',      responses: {'200': {}, '400': {}}}}
  '/stock/f10':           {get: {description: 'batch · handler=handle_cls_f10（CDP A′）', responses: {'200': {}, '400': {}}}}
  '/stock/basic_info':    {get: {description: 'batch · handler=handle_cls_basic_infos',   responses: {'200': {}, '400': {}}}}
  '/stock/announcement':  {get: {description: 'batch · handler=handle_cls_announcement',  responses: {'200': {}, '400': {}}}}
  '/cls/telegraph':       {get: {description: 'rss', responses: {'200': {content: {application/rss+xml: {}}}}}}
  '/eastmoney/kuaixun':   {get: {description: 'rss', responses: {'200': {content: {application/rss+xml: {}}}}}}
  '/ths/kuaixun':         {get: {description: 'rss', responses: {'200': {content: {application/rss+xml: {}}}}}}
  '/jin10/flash':         {get: {description: 'rss', responses: {'200': {content: {application/rss+xml: {}}}}}}
  '/wallstreetcn/live':   {get: {description: 'rss', responses: {'200': {content: {application/rss+xml: {}}}}}}
# 未注册路径 → 404 文本（send_error(404, 'Not Found. Visit / for available feeds.')）
```

**HTTP 状态语义（AC-A5 五类，唯一口径）**

| 情形 | 状态 / 体 |
|------|----------|
| 参数缺失（`/stock/*` 缺/空 `?code=`；`/cls/plate` 缺 `?code=`） | `400` + `{"error": "<说明>"}`（**非**逐码 null） |
| `/market/margin` 参数非法（`market ∉ VALID_MARKETS`） | `400` + `{"error": "Invalid ?market= parameter. Allowed: 99,1,2,3"}` ★ v1.2（guard 之前判定） |
| 非法码**值**（`/stock/*?code=<乱码>`） | `200`；该码逐码 `null`（**非** 400）★ v1.2（400 仅缺/空 `?code=`） |
| 未知路径 | `404` + 文本说明 |
| 过载（主端口 inflight 达上限） | `503` + `{"error":"server busy"}`，**立即、不排队**（**真实 503 之一**） |
| 流端口连接数 ≥ `MAX_STREAM_CONNS`(100) | `503` + `{"error":"too many stream connections"}`（`stream._serve_sse`；**真实 503 之二**） |
| **业务端点降级**（4 面板 `{'error':…}` / `/cls/hotplate` 全分区失败 / `/market/margin` `_error` / guard 捕获异常后的 `{'error':…}` / `/cls/plate` 分区降级 / batch 逐码 `null`） | **`200` + 结构化降级体** ★ v1.3（**N1 回退**：状态码**不由 payload 内容决定**；`_send_json_shape` 恒 200，降级体**可缓存**——按域 TTL 拿 `Cache-Control: public, max-age=<domain ttl>`） |
| `/healthz` body 缺 `status` / 含 `error` / `status=='degraded'` | `503` ★ v1.2（计 `http_503_total`）。**该 503 属 healthz 端点自身语义，不构成业务端点先例**（v1.3） |
| 上游**部分**失败（批量） | `200`；批量 → 逐码 `null` ∧ `_errors[code]`；单体 → error 客体；RSS → 降级 feed |
| CDP 不可用（面板 4） | `200` + `{"error":"…"}`（★ v1.3：降级体亦 200）；`/stock/f10` → `200` 逐码 `null` ∧ `_errors[code]='cdp_unavailable'`（**非** error 客体） |
| handler 抛异常（guard 捕获） | `200`；`object`/`text` → `{'error': str(exc)}`（`/healthz` 例外 → 503） |

### 2.2 `_JSON_SHAPES`（shape 派生表，**唯一权威**）

```python
_SHAPES = frozenset({'batch', 'object', 'rss', 'text'})

# 14 个 JSON 分支 → shape。新增端点必须在此登记，否则 _handle_request 走 404。
_JSON_SHAPES = {
    '/finance/market': 'object', '/finance/timeline': 'object',
    '/quotation/market': 'object', '/market/timeline': 'object',
    '/stock/data': 'batch', '/stock/fundflow': 'batch', '/stock/timeline': 'batch',
    '/stock/f10': 'batch', '/stock/basic_info': 'batch', '/stock/announcement': 'batch',
    '/cls/hotplate': 'object', '/cls/plate': 'object',
    '/ths/longhu': 'text', '/market/margin': 'object',
}
assert len(_JSON_SHAPES) == 14      # 结构护栏：再次漏数即导入期失败（修 P1-6 的复发）

# ★ v1.2：路由由表驱动，shape 一律从 _JSON_SHAPES 读（不再写死字面量）
_PANEL_HANDLERS = {'/finance/market': handle_finance_market,
                   '/finance/timeline': handle_finance_timeline,
                   '/quotation/market': handle_cls_quotation,
                   '/market/timeline': handle_market_timeline}
_STOCK_BATCH_HANDLERS = {'/stock/data': handle_cls_stock_batch, ... }   # 6 项
assert set(_STOCK_BATCH_HANDLERS) == {p for p, s in _JSON_SHAPES.items() if s == 'batch'}
# _JSON_SHAPES 必须真被消费：新增表项而无分支（或有分支而无 shape）⇒ 导入期失败
_JSON_DISPATCHED_PATHS = (frozenset(_PANEL_HANDLERS) | set(_STOCK_BATCH_HANDLERS)
                          | {'/cls/hotplate', '/cls/plate', '/ths/longhu', '/market/margin'})
assert _JSON_DISPATCHED_PATHS == frozenset(_JSON_SHAPES)
```

- **`_send_json_shape(path, fn, ...)`（v1.2；★ v1.3 / N1 简化）**：`payload = _guard(fn, shape=_JSON_SHAPES[path])` → `_send_json(payload, write_body=..., cache=cache)`（**恒 200**，状态码**不**按 payload 内容判定）；**路由不再自行发明 shape 字面量**。v1.2 的 `_json_payload_has_data` 分支与 `503` 判定**已删除**（降级体恢复可缓存）。
- **分组视图**（供代码阅读，不参与运行；**表内合计必须 == 14**）：
  - `object`（**7，表内**）：4 面板 + `/cls/hotplate` + `/cls/plate` + `/market/margin`
  - `batch`（6）：`/stock/*`
  - `text`（1）：`/ths/longhu`
  - **`/healthz` 复用 `object` shape 但 `≠` 在 `_JSON_SHAPES` 内**（见 §2.6；把它加进表 ⇒ `assert len(_JSON_SHAPES) == 14` 导入期失败）
  - `rss`（5）：`ROUTES` 的 5 个路径（不在 `_JSON_SHAPES` 中，由 `_serve_feed` 使用）
- `_handle_stock_batch` **断言** `_JSON_SHAPES[path] == 'batch'`（`assert`，导入/调用期暴露误配）。

### 2.3 `_guard(fn, *, shape, requested=None, dropped=0, rss_info=None, feed_url=None)`

```python
def _guard(fn, *, shape, requested=None, dropped=0, rss_info=None, feed_url=None):
    """执行 fn()；任何 Exception → 按 shape 产出结构化降级体（**绝不冒泡**）。"""
```

| 参数 | 类型 | 默认 | 语义 |
|------|------|------|------|
| `fn` | `Callable[[], Any]` | — | 无参可调用（handler 或 `lambda`）；**返回值形状由 shape 决定** |
| `shape` | `str` | — | ∈ `_SHAPES`；非法 → `ValueError`（编程错误，不静默） |
| `requested` | `Sequence[str] \| None` | `None` | **仅 `shape='batch'`** 用：降级时全码置 `null` 的码序 |
| `dropped` | `int` | `0` | **仅 `shape='batch'`** 用：透传 `build_batch_response(..., dropped=)` |
| `rss_info` | `dict \| None` | `None` | **仅 `shape='rss'`** 用：`ROUTES[path]` 的 `title`/`link`/`description` |
| `feed_url` | `str \| None` | `None` | **仅 `shape='rss'`** 用：`base_url + path` |

**分派表（唯一降级形态来源）**

| shape | 成功返回 | 异常时返回（HTTP 200） |
|-------|---------|---------------------|
| `batch` | `fn()` 的 dict（handler 组装体） | `cache.build_batch_response(requested, {}, {c: 'upstream_error' for c in requested}, dropped=dropped)` → 全码 `null` + `_errors` + 截断键；**不抛、不断连** |
| `object` | dict（或 handler 自带 `{'error':…}`） | `{'error': str(exc)}` |
| `text` | dict（`/ths/longhu` 的 `{data,total}`） | `{'error': str(exc)}`（调用方仍以 `application/json` 序列化） |
| `rss` | XML 字符串 | `generate_error_rss(info['title'], info['link'], info['description'], exc, feed_url=feed_url)`（现状行为固化） |

- `shape` 非法 → `raise ValueError(f'unknown guard shape: {shape!r}')`。
- 捕获类型 = `Exception`（**不捕** `BaseException`：`KeyboardInterrupt`/`SystemExit` 直通）。
- 异常落日志：`log.exception('[guard:%s] handler raised', shape)`（保留 traceback，AC-S1「无未捕获异常日志冒泡」指**不冒泡到 `do_GET`**，日志仍必须留痕）。
- **客户端断开不在此层**：`send_*` 阶段的 `BrokenPipeError`/`ConnectionResetError`（均 ⊂ `OSError`）由 `do_GET`/`do_HEAD` 的 `except OSError` 吞掉（v1.2 由 `BrokenPipe/ConnectionReset` 两元组扩为 `OSError`，含 `TimeoutError`；写入发生在 `_guard` 之后）。

### 2.4 `_handle_stock_batch(self, parsed, handler, write_body=True, path=None)`

```python
def _handle_stock_batch(self, parsed, handler, write_body=True, path=None) -> None
```

| 步骤 | 行为 |
|------|------|
| 1 | `params = parse_qs(parsed.query)`；缺 `code` → `_send_error(...400...)` |
| 2 | **`stock_codes, requested = _parse_stock_codes(params['code'][0])`**（★ v1.2：逐码 `config.canonical_code` 折叠后去重，`requested` 与 `stock_codes` 位置对齐并保留用户原拼写）；空 → `_send_error('No valid stock codes provided.')` |
| 3 | `dropped = 0`；若 `len(stock_codes) > _MAX_BATCH_SIZE` → `dropped = len(stock_codes) - _MAX_BATCH_SIZE`、`log.warning(...)`、`stock_codes = stock_codes[:50]` 且 `requested = requested[:50]`（**保持对齐**）。截断按**归一后**码数计 |
| 4 | `data = _guard(lambda: handler(stock_codes, dropped=dropped), shape=_JSON_SHAPES.get(path, 'batch'), requested=requested, dropped=dropped)`（shape 从表派生） |
| 5 | `data = _rekey_batch_response(data, stock_codes, requested)`（★ v1.2：响应键回请求原拼写，值不变；无需改写时原样返回） |
| 6 | `self._send_text(200, 'application/json; charset=utf-8', json.dumps(data, ensure_ascii=False, indent=2), cache=True, write_body=write_body)` |

- **严禁**在此处调用 `build_batch_response` 或手工挂 `_truncated`（组装点唯一 = handler 内部；本处只注入 `dropped`）。`_rekey_batch_response` 是**纯改名**，不改键集（`_` 前缀保留键仍由 `build_batch_response` 唯一组装）。
- **非法码值是逐码 `null`，不是 400**（`_parse_stock_codes` 对 `canonical_code → None` 的码以原拼写为身份交 handler，由 handler 报 `null`）；**400 仅缺/空 `?code=`**。
- **重复拼写不占第二个槽**（折叠后去重）⇒ `600519.SH,SH600519,sh600519` 只计 1 个 `_MAX_BATCH_SIZE` 额度。
- `deadline` **不传**（沿用 handler 默认预算：REST 域 15s / f10 CDP 60s）——与 `_PROGRESS.md` §B 锁定契约一致；f10 多码 >15s 的既有风险见 `stock_api.md` §10#10（本模块不兜）。

### 2.5 `_get_or_fetch_feed(self, path, fetch_func) -> str`（防击穿 + **双检**）

```python
def _get_or_fetch_feed(self, path, fetch_func) -> str
```

| 参数 | 类型 | 语义 |
|------|------|------|
| `path` | `str` | feed 路径（缓存键），来自 `ROUTES` |
| `fetch_func` | `Callable[[], str]` | 回源（`lambda: handler(feed_url=feed_url)`）；**失败抛异常**（由 `rss` shape 兜底） |

**必须按序执行（缺 ② 则防击穿退化，`cache.md` §2.4 硬约束）**

```
① xml = cache.feed_cache_get(path)          # miss → None（命中已内部 move_to_end + last_access）
   命中 → return xml
② with _feed_fetch_locks_lock: lock = _feed_fetch_locks.setdefault(path, threading.Lock())
③ with lock:
     xml = cache.feed_cache_get(path)       # ★ 二次 get（双检）：并发窗口内他人已回源
     命中 → return xml
     xml = fetch_func()                     # 仅 miss 才回源
     cache.feed_cache_put(path, xml, cache_policy('feed')['ttl'])
④ return xml
```

- **锁序（硬约束）**：取 `_feed_fetch_locks_lock` 后**立即释放**再进 per-path 锁；**持有 per-path 锁时绝不持有** `_feed_cache_lock`/`_feed_fetch_locks_lock`（`feed_cache_get/put` 内部自行加/放，二者不嵌套）。
- **TTL 同源**：`ttl = cache_policy('feed')['ttl']`（盘中 30 / 非盘中 180），与 `_cache_age()` 的 RSS 分支读**同一个 policy** ⇒ "承诺 = 行为"（SAD D4）。
- **`ttl` 求值点（修 P2-1）**：`ttl` **必须**在 ③ 的二次 `feed_cache_get` **仍 miss 之后**求值（即紧邻 `fetch_func()`/`feed_cache_put`）；**禁止**在 ① 首个 `feed_cache_get` 之前求值——否则命中路径白算 policy，且与 §7.4 的实现要求自相矛盾。§5.4 伪代码按此顺序。
- 回源失败**不写缓存**（异常穿透到 `_serve_feed` 的 `rss` 降级）；**不缓存错误 RSS**（下次请求重试，现状语义保持）。

### 2.6 `build_health_payload(base_url, check_sources=False) -> dict`

```python
def build_health_payload(base_url, check_sources=False) -> dict     # ★ 签名与位置不变（测试直接 import 调用）
```

**流程（三分支）**

| 分支 | 行为 |
|------|------|
| `check_sources=False`（零上游快路径） | 仅构造 `feeds[]` 基础条目 + `cache_ttl` + `request_timeout` + `metrics.snapshot()` + `policy` + `cdp`；**不触网**（毫秒级，AC-S8）。随后 `_remember_health_snapshot(payload)` |
| `check_sources=True` 且**准入成功** | `_health_sem.acquire(blocking=False)` 成功 → `_set_health_inflight(+1)` → **先建 `batch = _HealthBatch(len(ROUTES))`**（★ v1.2 / P1-5：账在风险调用**之前**建好）→ `try: _run_health_checks(base_url, batch)` / `except BaseException: batch.settle(); raise`（异常路径也恰好销账一次，防准入位永久泄漏）→ 把结果写回 `feeds[].status/items/error` → `status='degraded'` 若任一非 `ok` → 组装 payload → `_remember_health_snapshot(payload)`。**准入位不在本函数 `finally` 释放**（修 P1-1）：由 `_HealthBatch` 在**该批 5 个 future 全部结束**（`task_done` 归零）或**异常路径 `settle()`** 时释放（异步；响应不等任务排空，故 `?check=1` 仍 ≤ ~3s） |
| `check_sources=True` 且**准入失败**（≥`MAX_HEALTH_INFLIGHT` 在飞） | `metrics.incr('healthz_stale_total')` → 返回 **上次快照 + `{'stale': True}`**；若从无快照（进程启动后首个 check 即被拒）→ 返回**本次零上游体**（`status='degraded'`、`feeds` 为 configured 基线）+ `stale:true`；**不触网、不阻塞** |

**准入原语（修 P1-3：替换不可达的"执行器忙 → stale"死代码）**

```python
_health_sem = threading.BoundedSemaphore(MAX_HEALTH_INFLIGHT)   # = 5（config）
_health_executor = None                                          # 懒创建
_health_executor_lock = threading.Lock()
_health_inflight = 0                                             # gauge（在飞准入批次数）
_health_inflight_lock = threading.Lock()
_health_last_snapshot = None                                     # 上次成功 payload（深拷贝）
_health_last_lock = threading.Lock()
```

- **准入原语（修 P1-1：准入位必须覆盖任务真实在飞）**：`_health_sem` 钉死的是**准入批次数**（≤5），而每个准入批次的准入位**由该批 5 个 future 的完成回调释放**（`_HealthBatch.task_done`）。因此：
  - 在飞任务数 ≤ `MAX_HEALTH_INFLIGHT × len(ROUTES)` = **25**（确定性上界）；
  - 专用执行器（`max_workers=5`）的**工作队列长度 ≤ 20**（= 25 − 5 worker）⇒ SAD §2.6「执行器内部队列从不堆积」**成立**；
  - 持续慢 check（上游 5s）+ 高频 `?check=1` 下，新批次无法准入（5 个准入位被未排空的批次占满）⇒ **队列有界、不单调增长**（可测，见 SRV-T34）。
  - ⚠️ **禁止**在 `_run_health_checks` 返回时立即 `release`（旧 v1.0 口径）：轮询在 3s 即 `break`，未完成 future 仍跑，准入位早归还 ⇒ 队列可无界累积（重演 SAD P1-3 要消除的放大器）。
- **释放路径唯一收口**：`_health_sem.release()` 只在 `_release_health_slot()` 内出现，且被 `_HealthBatch` 的 `_done` 标志保证**每个准入批次恰好调用一次**（执行器创建失败/提交失败/异常返回/超时/正常完成**五路都销账**，`BoundedSemaphore` 超放会抛 `ValueError` ⇒ 由类型再次兜底）。

#### 2.6.1 `_run_health_checks(base_url, batch=None) -> dict[path, {'status','items','error'}]`

```python
_HEALTH_TOTAL_BUDGET  = 10.0   # 秒，整体预算（AC-S8「每个健康检查请求 ≤10s」；多源排队时的总闸）
_HEALTH_SOURCE_BUDGET = 3.0    # 秒，**每源独立**预算（SAD §2.2 R-2「单源 ≤3s」；按各自 submitted_at 判定）
_HEALTH_POLL          = 0.25   # 秒，wait() 轮询粒度
```

```
executor = _get_health_executor()                       # ThreadPoolExecutor(max_workers=MAX_HEALTH_INFLIGHT, thread_name_prefix='healthz')
# batch 由 build_health_payload 传入（★ v1.2 / P1-5：账在风险调用之前建，异常时可 settle）
started  = time.monotonic(); out = {}; pending = {}     # pending: fut -> (path, submitted_at)
for path, info in ROUTES.items():                       # 5 源
    try:
        fut = executor.submit(_check_one_feed, path, base_url, info)
    except Exception as exc:                            # 提交失败也须销账（否则准入位泄漏）
        out[path] = {'status': 'error', 'items': None, 'error': str(exc)}
        batch.task_done(); continue
    fut.add_done_callback(batch.task_done)              # ★ 完成即销账（准入位覆盖真实在飞）
    pending[fut] = (path, time.monotonic())             # ★ 记录该源各自的提交时刻

while pending:
    now = time.monotonic()
    for fut in [f for f, (_p, t) in pending.items() if now - t >= _HEALTH_SOURCE_BUDGET]:
        out[pending.pop(fut)[0]] = {'status': 'timeout', 'items': None, 'error': 'timeout'}   # ★ 每源独立 3s
    if not pending:
        break
    elapsed = now - started
    if elapsed >= _HEALTH_TOTAL_BUDGET:                 # ★ 整体 10s 闸（多源排队时才生效，不再死代码）
        break
    next_due = min(t for _p, t in pending.values()) + _HEALTH_SOURCE_BUDGET
    timeout = min(_HEALTH_POLL, max(0.0, next_due - now), max(0.0, _HEALTH_TOTAL_BUDGET - elapsed))
    done, _ = wait(set(pending), timeout=timeout, return_when=FIRST_COMPLETED)
    for fut in done:
        path = pending.pop(fut)[0]
        try:
            out[path] = fut.result()                     # _check_one_feed 是总函数，正常不抛
        except Exception as exc:                         # ★ v1.2 / P1-5：等待中途也不上抛
            out[path] = {'status': 'error', 'items': None, 'error': str(exc)}
for fut, (path, _t) in pending.items():                  # 整体预算耗尽：余下判 timeout
    out[path] = {'status': 'timeout', 'items': None, 'error': 'timeout'}
return out
```

- **`_HealthBatch`（修 P1-1 / v1.2 补 `settle()`）**：`__init__(n)` 置 `_remaining=n`、`_done=False`；`task_done()` 在锁内 `_remaining -= 1`，归零且未释放过 ⇒ 调 `_release_health_slot()`（`_set_health_inflight(-1)` + `_health_sem.release()`）**恰好一次**；**`settle()`（v1.2 / P1-5）**：不看 `_remaining`，仅凭同一 `_done` 闩锁立即释放一次——用于"异常路径已无可依赖的 future 回调"时销账。两条路径共享 `_done` ⇒ 谁先谁赢，**绝不双放**（超放会抛 `ValueError`）。`add_done_callback` 在 future 已结束时**同步**回调，故 `_remaining` 必须在任何 `submit` **之前**初始化为 `len(ROUTES)`。
- **两级预算（修 P2-2）**：**单源**预算按各 future 的 `submitted_at` 独立判定（`now - t >= 3s`）；**整体**预算 `10s` 是"多源排队/worker 被占满"时的总闸。旧口径的"全局 3s 条件"使 10s 常量成为死代码，已删除。
- `_check_one_feed(feed_path, base_url, info)`：**总函数**——`info['handler'](feed_url=base_url+feed_path)` → `{'status':'ok','items':count_rss_items(xml),'error':None}`；任意异常 → `{'status':'error','items':None,'error':str(exc)}`。
- **超时语义**：单源超过 `_HEALTH_SOURCE_BUDGET` 即判 `timeout`（**不取消** worker —— 线程不可杀；其上界由 `cache.REQUEST_TIMEOUT=10s` 钉死（★ v1.3：该 10s 是**冷/老化预算**；故障期探测预算 ≤ `cache._PROBE_BUDGET_CAP=5s`，见 `cache.md` §4.2 BR-CACHE-22），且其准入位由 `_HealthBatch` 在真正结束时归还，AC-S7/S8 可断言"线程有界释放 + 队列有界"）。
- **degraded 判定**：任一 `status != 'ok'` ⇒ `status='degraded'`（含 `timeout`/`error`）；HTTP 状态码由 `_handle_request` 决定：★ v1.2 起 `缺 status` / `含 error` / `status=='degraded'` **三者皆 503**（并计 `http_503_total`）。★ v1.3：**该 503 仅属 `/healthz` 端点自身语义**——业务端点不采用（见 §4.1 BR-SRV-5b）。

### 2.7 `BoundedThreadPoolServer`（过载有界拒绝）

```python
class BoundedThreadPoolServer(ThreadingHTTPServer):
    request_queue_size = LISTEN_BACKLOG            # ★ v1.2：BUG-P6C-03（socketserver 默认 5 ⇒ 突发连接 SYN 重传）
                                                   #   一个值同时配置主端口（≤MAX_INFLIGHT）与流端口（≤MAX_STREAM_CONNS）
    def __init__(self, *args, max_workers=MAX_WORKERS, max_inflight=None, **kwargs):
        ...
        self._max_inflight = MAX_INFLIGHT if max_inflight is None else max_inflight
        #                    ↑ 主端口默认 MAX_INFLIGHT(40)；流端口显式传 110（修 P1-4）
    def _reject_503(self, request):                # + metrics.incr('http_503_total')
    def process_request(self, request, client_address): ...   # 现状逻辑不变：达限即 503，不排队
    def _release_inflight(self, fut): ...
```

- **`max_inflight` 形参（修 P1-4，编排层已批准）**：`max_workers` 形参**不参与** inflight 计算；
  - 主端口：`max_inflight=None` ⇒ `_max_inflight = MAX_INFLIGHT = MAX_WORKERS*2 = 40`；
  - 流端口：`make_stream_server` 显式传 `max_inflight = MAX_STREAM_CONNS + 10 = 110`（**≥** `MAX_STREAM_CONNS=100`）⇒ `MAX_STREAM_CONNS=100` 与 `_register_conn` 的 100 阈值不再被 40 掩盖，AC-E5/E7 的 100 连接可复现。
  - **行为变更登记见 §10#11**（流端口 inflight 由"塌缩为 40"改为"显式 110"）。
- `_reject_503` 在 `finally` 关闭 socket，并 `metrics.incr('http_503_total')`（★ v1.3：`http_503_total` 全系统共 **3** 个计数点——**主端口连接准入拒绝**（本处）、**流端口准入拒绝**（`stream._serve_sse`）、**`/healthz` degraded/异常**；本处是主端口准入路径的唯一计数点。`metrics` 调用放在 `finally` 的 try 内，失败不得影响拒绝路径）。

### 2.8 handler 清单（本模块提供的 handler + 其 shape）

| # | 路径 | handler | shape | 说明 |
|---|------|---------|-------|------|
| 1 | `/finance/market` | `handle_finance_market(feed_url=None)` | object | CDP A；`page_data(page)` 防御取数 |
| 2 | `/finance/timeline` | `handle_finance_timeline()` | object | CDP A；`timeline is None → {'error':'timeline unavailable'}`（**禁止裸 null**） |
| 3 | `/quotation/market` | `handle_cls_quotation(feed_url=None)` | object | CDP A |
| 4 | `/market/timeline` | `handle_market_timeline()` | object | CDP A；同上禁止裸 null |
| 5 | `/stock/data` | `handle_cls_stock_batch`（stock_api） | batch | 无 pool/无终点缓存 |
| 6 | `/stock/fundflow` | `handle_cls_fundflow` | batch | — |
| 7 | `/stock/timeline` | `handle_cls_timeline` | batch | — |
| 8 | `/stock/f10` | `handle_cls_f10` | batch | CDP A′（`_errors='cdp_unavailable'`） |
| 9 | `/stock/basic_info` | `handle_cls_basic_infos` | batch | — |
| 10 | `/stock/announcement` | `handle_cls_announcement` | batch | — |
| 11 | `/cls/hotplate` | `handle_cls_hotplate(feed_url=None)` | object | **≤3 并发**；分区 error 客体 + **全分区失败补顶层 `error`**；3 档 stagger |
| 12 | `/cls/plate` | `handle_cls_plate(code)` | object | **≤3 并发**；3 档 stagger；缺 code 在路由层 400 |
| 13 | `/ths/longhu` | `handle_ths_longhu()` | text | GBK × **2 URL 并发**走 `fetch_json` |
| 14 | `/market/margin` | `handle_margin(market)`（market_api） | object | 签名不变 |
| 15–19 | 5 RSS | `handle_cls_telegraph` / `handle_eastmoney_kuaixun` / `handle_ths_kuaixun` / `handle_jin10_flash` / `handle_wallstreetcn_live`（均 `(feed_url=None)`） | rss | `ROUTES` 表 |

**本模块 handler 的既有签名（仅内部实现变化，签名不变）**

| 签名 | 变化 |
|------|------|
| `handle_finance_market(feed_url=None) -> dict` | 内部：`data = cdp_engine.page_data(page)`；`None → {'error':'Finance page not initialized.'}`；拿到 dict 后 `ws_raw = data.pop('__ws__', None)` / `data.pop('timeline', None)` 合法（已判定 dict） |
| `handle_finance_timeline() -> dict` | 内部：`data = page_data(page)`；`None → {'error': …}`；`tl = data.get('timeline')`；`tl is None → {'error': 'timeline unavailable'}`（**修 R18 旁支**） |
| `handle_market_timeline() -> dict` | 同 `handle_finance_timeline`（页面 = `cls_quotation`） |
| `handle_cls_quotation(feed_url=None) -> dict` | 同 `handle_finance_market`（无 `__ws__`） |
| `handle_cls_hotplate(feed_url=None) -> dict` | `ttl = base + stagger × idx`（§2.9）；3 分区经 `_fetch_concurrent` **≤3 并发**（SAD §4.1）；分区 error 客体 + 全失败补顶层 `error`（BR-SRV-31） |
| `handle_cls_plate(code) -> dict` | 同上 3 档；3 段经 `_fetch_concurrent` **≤3 并发**；`code` 由调用方保证非空 |
| `handle_ths_longhu() -> dict` | 两 URL 经 `_fetch_concurrent` **并发**走 `fetch_json(..., encoding='gbk')`；解析逻辑逐字保留 |

### 2.9 内部辅助（签名精确）

```python
def _plate_ttls() -> tuple[int, int]:
    """返回 (base_ttl, stagger)。base_ttl = cache_policy('plate')['ttl']；stagger = max(3, base_ttl // 4)。"""

def _policy_snapshot() -> dict:
    """{domain: cache_policy(domain)}，domain 枚举自 config.DOMAIN_MATRIX（sorted）。"""

def _base_feed_entries(base_url) -> list[dict]:
    """healthz feeds[] 的 15 个基础条目（5 RSS + 10 JSON/CDP），status 取 §2.9.1 表。"""

def _remember_health_snapshot(payload) -> None:
    """深拷贝（json round-trip，不用 copy 模块）后存入 _health_last_snapshot。"""

def _health_snapshot() -> dict | None:
    """返回 _health_last_snapshot 的浅引用（调用方只做 {**snap, 'stale': True} 后立即序列化，不原地改）。"""

def _set_health_inflight(delta: int) -> None:
    """_health_inflight 增减 + metrics.set_gauge('healthz_inflight', 值)（下限 0）。"""

def _get_health_executor() -> ThreadPoolExecutor:
    """懒创建（双检，_health_executor_lock）：ThreadPoolExecutor(max_workers=MAX_HEALTH_INFLIGHT, thread_name_prefix='healthz')。"""

def _release_health_slot() -> None:
    """BR-SRV-19：释放一次 healthz 准入位（_set_health_inflight(-1) + _health_sem.release()）；仅由 _HealthBatch 调用。"""

class _HealthBatch:
    """一次 ?check=1 的在飞记账（修 P1-1）：__init__(n) / task_done()（幂等，归零即 _release_health_slot()）
    / **settle()（v1.2 / P1-5：异常路径立即释放，共享 _done 闩锁 ⇒ 绝不双放）**。"""

# ★ v1.3 / N1：_json_payload_has_data(payload) -> bool 已删除 —— v1.2 曾用它把
#   "仅 error 包装"的 payload 判为 503；编排层裁决回退为"业务端点恒 200 + error 体"，
#   该函数与 _send_json_shape 的 503 分支一并移除（降级体恢复可缓存）。

def _parse_stock_codes(codes_str) -> tuple[list[str], list[str]]:
    """★ v1.2（P1-6）：一个 `?code=a,b,c` 值 → (canonical 去重码, 请求原拼写)；
    `config.canonical_code` 为唯一权威；无效码以自身拼写为身份（逐码 null，非 400）。"""

def _rekey_batch_response(data, codes, requested) -> dict:
    """★ v1.2（P1-6）：把 handler 的 canonical 键体改回请求原拼写（含 `_errors` 子映射）；
    纯改名（键集不变）；无需改写时原样返回。"""

def _valid_host_header(host) -> bool:
    """★ v1.2（S2-3）：Host 形如 hostname[:port] / [v6][:port]；拒绝空/超长/host-list/注入（@ / 空白 / CRLF）。"""

def _normalize_proto(value) -> str:
    """★ v1.2：X-Forwarded-Proto → 'http'/'https'（其余 ⇒ 'http'）。"""

def _get_fanout_executor() -> ThreadPoolExecutor:
    """懒创建（双检，_fanout_lock）：ThreadPoolExecutor(max_workers=_FANOUT_MAX_WORKERS=3, thread_name_prefix='fanout')。"""

def _fetch_concurrent(specs) -> dict:
    """specs: list[(key, Callable[[], Any])]；≤3 并发展开，返回 {key: 结果|Exception}（**不抛**）；
    单元素时走当前线程（免池化开销）。顺序 = specs 顺序（确定性）。
    ★ v1.2：`wait(futs, timeout=_FANOUT_WAIT_BUDGET=REQUEST_TIMEOUT)` 有界排空；超期 future `cancel()`
    并降级为 `FetchError('upstream_timeout')`（已在跑的仍受自身 10s 界）；此处不计任何计数（真失败由
    cache.fetch_json 计，防双计）。"""
```

**新增/调整的模块级常量**

```python
_SHAPES = frozenset({'batch', 'object', 'rss', 'text'})
_JSON_SHAPES = {...}                     # §2.2，14 项
_DEFAULT_AGE_DOMAIN = 'f10'              # _cache_age 未登记路径的兜底域（L4、factor 1.0 ⇒ 恒 300，见 §10#2）
_LHBTABLE_URL     = 'https://data.10jqka.com.cn/ifmarket/lhbtable'
_LHBTABLE_HEADERS = {'User-Agent': '…Chrome/120.0.0.0 Safari/537.36',
                     'Referer': 'https://data.10jqka.com.cn/market/longhu/',
                     'X-Requested-With': 'XMLHttpRequest'}
_LONGHU_PAGE_URL     = 'https://data.10jqka.com.cn/market/longhu/'
_LONGHU_PAGE_HEADERS = {'User-Agent': '…Chrome/120.0.0.0 Safari/537.36',
                        'Accept-Language': 'zh-CN,zh;q=0.9'}
_HEALTH_TOTAL_BUDGET = 10.0
_HEALTH_SOURCE_BUDGET = 3.0
_HEALTH_POLL = 0.25
_FANOUT_MAX_WORKERS = 3                  # ★ 外部上游扇出并发上限（SAD §4.1；hotplate/plate/longhu 共享）
_FANOUT_WAIT_BUDGET = REQUEST_TIMEOUT    # ★ v1.2（P1-2）：一轮扇出的排空上界（否则共享池被占时单请求可拖到 ~190s）
_BASE_URL_VARY = 'Host, X-Forwarded-Host, X-Forwarded-Proto'   # ★ v1.2（S2-3）
_HOST_RE / _HOST_IPV6_RE = ...           # ★ v1.2：Host 格式校验正则
```

> **线程账**：本模块新增线程来源 = healthz 专用执行器（≤5，懒创建）+ 扇出执行器（≤3，懒创建）；`fanout` 线程仅在首次并发扇出时创建（AC-S9 线程总账 +8 上界，见 §10#15）。

> `_LHBTABLE_*` / `_LONGHU_PAGE_*` 是**从现状 `Request(...)` 字面量提取**的模块级常量（现状 `server.py:143-176` 内联）；**本次未上收 `config.py`**（`config.md` v1.1 的常量清单未登记该域）——登记见 §10#1。

#### 2.9.1 `_base_feed_entries` 的 status 取值表（含 3 处 CDP 标注修正）

| path | 现状 status | **目标 status** | 类别（PRD AC-S4） |
|------|------------|----------------|------------------|
| `/cls/telegraph` `/eastmoney/kuaixun` `/ths/kuaixun` `/jin10/flash` `/wallstreetcn/live` | configured | `configured`（不变） | B |
| `/finance/market` | requires_chrome_cdp | `requires_chrome_cdp`（不变） | A |
| `/quotation/market` | requires_chrome_cdp | `requires_chrome_cdp`（不变） | A |
| `/stock/data` | requires_chrome_cdp | **`configured`** ★修正 | B |
| `/stock/fundflow` | configured | `configured`（不变） | B |
| `/cls/hotplate` | configured | `configured`（不变） | B |
| `/cls/plate?code=cls80484` | configured | `configured`（不变） | B |
| `/stock/timeline` | configured | `configured`（不变） | B |
| `/stock/f10` | configured | **`requires_chrome_cdp`** ★修正 | A′ |
| `/stock/basic_info` | requires_chrome_cdp | **`configured`** ★修正 | B |
| `/market/margin` | configured | `configured`（不变） | B |

> ★ 三处为 SAD §7.1 Q2 登记的契约漂移；**同步权归编排层**（本设计只落目标值 + §10#7 登记）。`feeds[].status` 属**改既有字段取值**（≠"只增不改"），须走变更日志 + API.md 同步。

**首页 CDP 列修正（`_serve_index` 的 `json_apis` 表，第 4 元素 `needs_cdp`）**

| path | 现状 `needs_cdp` | **目标** |
|------|-----------------|---------|
| `/stock/data` | `True` | **`False`** |
| `/stock/basic_info` | `True` | **`False`** |
| `/stock/f10` | `False` | **`True`** |
| 其余 11 项 | — | 不变 |

### 2.10 保留不变的公开面（兼容清单）

| 名称 | 变更 |
|------|------|
| `ROUTES`（5 项 dict，含 `handler`/`name`/`title`/`link`/`description`） | **不变**（OPML/healthz/首页均依赖其结构） |
| `RSSHandler.timeout = 30` | 不变（主端口兜底） |
| `_serve_index` / `_serve_feed` | 不变（`_serve_feed` 内部改传 `varies_on_host=not PUBLIC_BASE_URL`） |
| `_base_url()` / `_send_text` / `_send_json` | **签名扩展（v1.2）**：`_base_url` 加 Host 校验；`_send_text(..., varies_on_host=False, write_body=True)`；`_send_json(data, write_body=True, cache=True)`（★ v1.3：**无 `status` 形参**——恒调 `_send_text(200, …)`）；新增 `_send_json_shape`（★ v1.3：恒 200，无 503 分支） |
| `BoundedThreadPoolServer.__init__(*args, max_workers=MAX_WORKERS, max_inflight=None, **kwargs)` | **增 `max_inflight` 形参（v1.1）**；★ v1.2 增类属性 `request_queue_size = LISTEN_BACKLOG` |
| `init_cdp()` / `_cdp_memory_watchdog()` / `main()` | 签名不变（watchdog 内部决策改调 cdp_engine） |
| `handle_cls_telegraph` / `handle_eastmoney_kuaixun` / `handle_ths_kuaixun` / `handle_jin10_flash` / `handle_wallstreetcn_live(feed_url=None)` | 签名不变；内部 `ttl` 改 `cache_policy('news_url')['ttl']` |
| `build_health_payload(base_url, check_sources=False)` | **签名不变**（测试直接调用） |

**删除的 import / 常量消费者迁移（与 `config.md` §2.4 **同一 change-set**）**

| 删除项 | 本模块消费点 | 迁移目标 |
|--------|-------------|---------|
| `CACHE_TTL` | `server.py:37`（import）、`:497`（healthz `cache_ttl`）、`:668`（feed expires）、`:936`（启动日志） | `cache_policy('feed')['ttl']` |
| `CACHE_JITTER`、`random` | `server.py:668` 的 `× (1 ± jitter)` | **删除**（jitter 现由 `cache._expires_at(ttl)` 内部提供，`cache.md` §2.5） |
| `feed_cache`、`_feed_cache_lock`、`MAX_FEED_CACHE_SIZE` | `server.py:46-47,663-664`（feed LRU/淘汰） | `cache.feed_cache_get` / `feed_cache_put`（`cache.md` §2.4） |
| `_trading_tiers` | `server.py:81/90/122/217/230`（news TTL）、`:299`/`:337`（hotplate/plate 的 `tiers['L2']`）、`:693`（`_cache_age`） | `cache_policy('news_url')['ttl']` / `_plate_ttls()`（`cache_policy('plate')['ttl']`）/ `cache_policy(d)['ttl']`；**`_trading_tiers` import 随删**（本模块不再直接读 tier） |

**完整 import 块（修 P2-5：逐行可整体替换，含标准库/包内全部保留项与删除项）**

```python
# ── 标准库 ────────────────────────────────────────────────────────────
import atexit
import json
import os
import re
import signal
import sys
import threading
import time
import logging
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED   # ★ 新增 wait/FIRST_COMPLETED
from email.utils import formatdate
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
from urllib.parse import parse_qs, urlencode
# ★ 删除：import random（唯一使用点 :668 的 jitter 已归 cache._expires_at）
# ★ 删除：from urllib.request import Request, urlopen（longhu 改走 fetch_json 后二者成为未用 import）

# ── 包内 ──────────────────────────────────────────────────────────────
from . import config                                                       # ★ 新增（config.MAX_HEALTH_INFLIGHT / config.canonical_code 以前缀引用）
from . import metrics                                                      # ★ 新增（SAD §2.6 owner）
from .cdp_engine import (ensure_chrome, CDPEngine, full_chrome_restart,
                         restart_window_snapshot, watchdog_restart_skip_reason,
                         page_data)                                        # ★ v1.2：page_data 补入（A 类唯一入口）
from .config import (
    PORT, REQUEST_TIMEOUT, PUBLIC_BASE_URL, MAX_WORKERS, MAX_INFLIGHT,
    LISTEN_BACKLOG, DOMAIN_MATRIX, cache_policy, _MAX_BATCH_SIZE,           # ★ v1.2：LISTEN_BACKLOG 新增
    _FINANCE_EXPECTED_KEYS, _QUOTATION_EXPECTED_KEYS,
    _HOTPLATE_BASE_URL, _HOTPLATE_HEADERS,
    _PLATE_INFO_URL, _PLATE_STOCKS_URL, _PLATE_INDUSTRY_URL, _PLATE_HEADERS,
    CDP_RESTART_INTERVAL, stock_nav_page_names, cdp_engine,
)   # ★ 删除：CACHE_TTL、_trading_tiers；★ v1.2：MAX_HEALTH_INFLIGHT 不再直接 import（改用 config. 前缀）
from .cache import (fetch_json, feed_cache_get, feed_cache_put,
                    _feed_fetch_locks, _feed_fetch_locks_lock,
                    build_batch_response, _fill_missing, FetchError)       # ★ v1.2：FetchError 新增
from .utils import (                                                       # 不变（handler + main() 均用）
    generate_rss, generate_error_rss, generate_opml, count_rss_items,
    parse_cls_items, parse_jin10_items, parse_wallstreetcn_items,
    cls_sign_params, get_jin10_public_headers,
    timestamp_to_rfc822, parse_china_datetime_to_rfc822,
)   # ★ v1.2：strip_html / escape_xml 已不在使用面（删除）
from .stock_api import (                                                   # 含 main() 的 4 个 prefetch loop
    handle_cls_stock_batch, handle_cls_fundflow,
    handle_cls_timeline, handle_cls_f10, handle_cls_basic_infos,
    handle_cls_announcement,
    _fundflow_prefetch_loop, _timeline_prefetch_loop,
    _f10_prefetch_loop, _announcement_prefetch_loop,
)   # ★ v1.2：handle_cls_stock / fetch_cls_fundflow / fetch_cls_timeline 不在使用面（删除）
from .market_api import (handle_margin, VALID_MARKETS)                     # ★ v1.2：VALID_MARKETS 新增（margin 400 门）
```

> **禁止**把 `main()` 仍需要的 `stock_api` 4 个 prefetch loop / `market_api` / `utils` import 当成"未变更行"省略后整体替换——本块已列全，编码者按此整体替换即可（P2-5）。


---

## 3. 数据结构（yaml）

### 3.1 `/healthz` 响应精确 schema（既有 4 键一个不少 + 新增 4 键）

```yaml
healthz_payload:
  status: "ok" | "degraded"          # 既有；check=1 时任一源非 ok → degraded（timeout/error 均算）
                                     # ★ v1.2 HTTP 503 判定：缺 status / 含 error / status=='degraded'
                                     #   （guard 捕获异常时体为 {'error': …}，无 status ⇒ 503，不再假健康）
  cache_ttl: <int>                   # 既有；★取值改 cache_policy('feed')['ttl']（盘中 30 / 非盘中 180）
  request_timeout: <int>             # 既有；REQUEST_TIMEOUT（10）
  feeds:                             # 既有；15 条，字段集合不变
    - name: <str>                    # 既有
      path: <str>                    # 既有
      url: <str>                     # 既有（base_url + path）
      status: "configured" | "requires_chrome_cdp" | "ok" | "error" | "timeout"
                                     #   check=0 → 前两者（§2.9.1 修正后取值）
                                     #   check=1 → 仅覆盖 5 个 RSS 源的 status 为 ok/error/timeout；
                                     #             其余 10 个 JSON/CDP 条目**仍为** configured / requires_chrome_cdp
                                     #             （`_run_health_checks` 只检查 ROUTES 的 5 个 RSS 源）
      items: <int>                   # 仅 check=1 且 status==ok
      error: <str>                   # 仅 check=1 且 status∈{error, timeout}
  stale: true                        # 仅"准入失败"时出现（值恒 true；不存在 ≠ false）
  metrics: {<name>: <number|object|array>, ...}          # metrics.snapshot()（19 名冻结注册表）
  policy: {<domain>: {tier,ttl,pool_refresh,pool_max,cache_max[,encoding]}, ...}   # 11 域，枚举自 DOMAIN_MATRIX
  cdp: {state: "idle"|"restarting"|"unavailable", window_start: <float|null>, window_end: <float|null>}
```

### 3.2 healthz 模块级状态

```yaml
_health_executor: ThreadPoolExecutor | null      # 懒创建；max_workers = MAX_HEALTH_INFLIGHT(5)；thread_name_prefix='healthz'
_health_executor_lock: threading.Lock            # 仅保护懒创建（双检）
_health_sem: threading.BoundedSemaphore          # 初值 MAX_HEALTH_INFLIGHT = 5；★ 有界准入（stale 可达）
_HealthBatch: <class>                            # ★ P1-1：一次 check 的在飞记账（_remaining/_lock/_done）
                                                 #   task_done() 归零 ⇒ _release_health_slot()（幂等，恰好一次）
_health_inflight: <int>                          # 在飞**准入批次**数（gauge healthz_inflight；含"已返回响应但任务仍在跑"的批次）
_health_inflight_lock: threading.Lock
_health_last_snapshot: <dict|null>               # 上次 payload 的深拷贝（stale 回退源）
_health_last_lock: threading.Lock
_HEALTH_TOTAL_BUDGET: 10.0                       # 秒（整体闸；多源排队时生效）
_HEALTH_SOURCE_BUDGET: 3.0                       # 秒（★ 每源独立，按各自 submitted_at 判定）
_HEALTH_POLL: 0.25                               # 秒
_fanout_executor: ThreadPoolExecutor | null      # ★ 懒创建；max_workers = _FANOUT_MAX_WORKERS(3)；thread_name_prefix='fanout'
_fanout_lock: threading.Lock                     # 仅保护懒创建（双检）
_FANOUT_MAX_WORKERS: 3                           # ★ hotplate/plate/longhu 共享的外部上游扇出并发上限（SAD §4.1）
```

### 3.3 路由与 shape 结构（运行时视图）

```yaml
ROUTES:                                          # 既有，5 个 RSS
  '/cls/telegraph': {handler: handle_cls_telegraph, name: 'CLS Telegraph (财联社电报)', title: 财联社电报,
                     link: 'https://www.cls.cn/telegraph', description: 财联社实时快讯}
  '/eastmoney/kuaixun': {...}  '/ths/kuaixun': {...}  '/jin10/flash': {...}  '/wallstreetcn/live': {...}
_JSON_SHAPES:                                    # §2.2，14 项（object×8 / batch×6 / text×1）
_SHAPES: [batch, object, rss, text]
_CACHE_AGE_DOMAINS:                              # ★ 新增：_cache_age 的 path → domain 映射（唯一权威）
  '/finance/market': quote    '/finance/timeline': quote        # ★ v1.2：面板 = 实时行情面（L1，**非** 300）
  '/quotation/market': quote  '/market/timeline': quote         # ★ v1.2
  '/stock/data': quote        '/stock/basic_info': quote
  '/stock/fundflow': fundflow '/stock/timeline': timeline
  '/stock/f10': f10           '/stock/announcement': announcement
  '/cls/hotplate': plate      '/cls/plate': plate
  '/ths/longhu': longhu       '/market/margin': margin
  '/cls/telegraph': news_url  '/eastmoney/kuaixun': news_url  '/ths/kuaixun': news_url
  '/jin10/flash': news_url    '/wallstreetcn/live': news_url
  # 未登记（/healthz、/、/opml.xml）→ _DEFAULT_AGE_DOMAIN('f10'，L4 恒 300)
_feed_fetch_locks: dict[path -> threading.Lock]  # 既有（cache.py 模块级），本模块只经 cache 的锁表访问
_feed_fetch_locks_lock: threading.Lock           # 既有（cache.py 模块级）
```

### 3.4 `BoundedThreadPoolServer` 状态

```yaml
executor: ThreadPoolExecutor(max_workers=MAX_WORKERS=20)
_inflight: <int>              # 运行 + 排队（受 _inflight_lock）
_inflight_lock: threading.Lock
_max_inflight: MAX_INFLIGHT if max_inflight is None else max_inflight
                              # 主端口 = MAX_INFLIGHT(40)（config 显式；env MAX_INFLIGHT 可调）
# stream 侧实例：max_workers = MAX_STREAM_CONNS + 10 = 110
#               max_inflight = MAX_STREAM_CONNS + 10 = 110  ⇒ _max_inflight = 110（★ 修 P1-4，见 §10#11）
```

---

## 4. 业务规则（编号供伪代码与测试引用）

### 4.1 路由与异常边界

| 编号 | 规则 | 依据 |
|------|------|------|
| **BR-SRV-1** | 分发顺序（固定）：`/` → `/opml.xml` → `/healthz` → `_JSON_SHAPES` 的 `batch` 六分支 → `object` 分支（4 面板 + hotplate + plate + margin）→ `text`（longhu）→ `ROUTES`（rss）→ `send_error(404)`。**顺序即优先级**，不得重排 | 现状 + §2.2 |
| **BR-SRV-2** | `shape` **只**从 `_JSON_SHAPES` 派生；任何新增 JSON 分支未登记 → 走 404（**不静默当 object**） | SAD §2.4（P1-6 防复发） |
| **BR-SRV-3** | `_guard` 捕获 `Exception`（非 `BaseException`）；`batch` 异常 ⇒ 全码 `null` + `_errors[code]='upstream_error'`；`object`/`text` ⇒ `{'error': str(exc)}`；`rss` ⇒ `generate_error_rss`。**任何 handler 异常都不得穿透 `do_GET`/`do_HEAD`** | R1 / AC-S1 |
| **BR-SRV-4** | `_guard` **不吞**写入阶段断连异常（写入在 guard 之后）；`do_GET`/`do_HEAD` 以 `except OSError` 吞掉（★ v1.2 由 `BrokenPipeError`/`ConnectionResetError` 扩为 `OSError`，含 `TimeoutError`/流端口 parity） | 现状保留（v1.2 扩容） |
| **BR-SRV-5** | 批量响应**永不含顶层 `error`**；单体/面板响应**永不含逐码值域**（跨类别即失配） | AC-A5 |
| **BR-SRV-5b** | **业务端点降级 = `200 + error 体`（★ v1.3 / N1 回退）**：`object`/`text` shape 的 payload 若仅由 error 客体包装（`{'error': …}` / 保留键 `_error`），仍以 **HTTP 200** 返回原样降级体——**状态码不得由 payload 内容决定**（`_json_payload_has_data` 已删）。**真实 503 = 三条**：`_reject_503`（连接准入）、`stream._serve_sse`（流端口准入）、`/healthz`（端点自身语义）。v1.2 的"error-only ⇒ 503 + 计 `http_503_total`"**已作废** | **N1 裁决** / AC-A5 / 既有消费契约 |
| **BR-SRV-5c** | **`/market/margin` 参数门（v1.2）**：`market ∉ VALID_MARKETS` ⇒ **400**（guard 之前，不建缓存键、不发上游请求）；`market` 缺省 `'99'` | A5 |

### 4.2 feed 缓存与 TTL

| 编号 | 规则 | 依据 |
|------|------|------|
| **BR-SRV-6** | `_get_or_fetch_feed` 的 **miss → 取 per-path 锁 → 二次 `feed_cache_get`（双检）→ fetch → `feed_cache_put`** 顺序**不可省略双检**；回源失败不写缓存、不写错误 RSS | 裁决 #3 / `cache.md` §2.4 |
| **BR-SRV-7** | feed TTL 恒 = `cache_policy('feed')['ttl']`（盘 30 / 非盘 180）；`_cache_age()` 的 RSS 分支（`news_url` 域）与 `feed` 域同一 L3 基值 ⇒ 服务端承诺（`Cache-Control: max-age=30`）= 实际新鲜度（**修 D4**） | SAD §2.1 D4 / Q3 / AC-A8 |
| **BR-SRV-8** | `_cache_age()` 用 **`urlparse(self.path).path`**（v1.2：与路由同规则，absolute-form 请求行不再落到兜底域）**只**经 `_CACHE_AGE_DOMAINS` → `cache_policy(domain)['ttl']`；未登记路径（**仅** `/healthz`、`/`、`/opml.xml`）→ `_DEFAULT_AGE_DOMAIN`（`f10`，L4 恒 300）。**禁止裸 TTL 字面量** | ADR-001 / BR-CFG-12 |
| **BR-SRV-8b** | **4 CDP 面板的 `_cache_age` 域 = `quote`（L1，8/120）**（v1.2）：面板是实时行情面，**不得**落 `_DEFAULT_AGE_DOMAIN('f10')` 的 300s（否则实时行情被标 `max-age=300`） | S2-3 / AC-A3 |
| **BR-SRV-9** | `/ths/longhu` 的两个 URL 使用**同一** `cache_policy('longhu')` 的 `ttl`（=300）与 **`encoding`（`policy['encoding']='gbk'`，不再硬编码字面量）**；**消除直连 `urlopen`**（R15）。AC-E9 计数口径：每个 URL 各回源 1 次、共 2 次；连续 10 次请求其余 9 次命中 | SAD §2.3 D-5 / AC-E9 |

### 4.3 plate stagger（D-7 **明令保留**）

| 编号 | 规则 | 依据 |
|------|------|------|
| **BR-SRV-10** | `base_ttl = cache_policy('plate')['ttl']`；`stagger = max(3, base_ttl // 4)`；**offset = stagger × 分区序** | SAD §2.1 / `cache.md` REV-DES-01 脚注 |
| **BR-SRV-11** | `handle_cls_hotplate` 分区序：`industry`=0、`concept`=1、`area`=2 ⇒ TTL = `base + stagger×idx`（盘中 12/15/18；非盘中 120/150/180，等价 ×1/1.25/1.5） | 同上 |
| **BR-SRV-12** | `handle_cls_plate` 分区序：`info`=0、`stocks`=1、`industry`=2 ⇒ TTL = `base + stagger×idx` | 同上 |
| **BR-SRV-13** | **严禁**把三档压成同一个 `cache_policy('plate')['ttl']`（静默丢弃错峰 = 行为回归）；`_STAGGER`/offset **不得**写成裸字面量 | SAD D-7 / `cache.md` §2.6 脚注 |

### 4.4 批量截断

| 编号 | 规则 | 依据 |
|------|------|------|
| **BR-SRV-14** | `> _MAX_BATCH_SIZE(50)` ⇒ `dropped = len(codes) - 50`，**只截断请求码**（不截断 handler 内部 2000 码路径——stream 直调 handler，不经本处） | SAD §2.4 |
| **BR-SRV-15** | `dropped` **只经参数**传入 handler；`_truncated`/`_dropped_count` 由 `build_batch_response` 挂载（`dropped>0` 才同现；`dropped<=0` 两键都不存在） | AC-A9 / `cache.md` BR-CACHE-17 |
| **BR-SRV-16** | 截断必须 `log.warning`（保留现状：含丢弃数 + 前 3 个样本） | 现状保留 |

### 4.5 healthz

| 编号 | 规则 | 依据 |
|------|------|------|
| **BR-SRV-17** | `check=0` **零上游**：不创建执行器、不触网、不占准入位；只读 policy + metrics + cdp 快照 | AC-S8 / SAD §2.6 |
| **BR-SRV-18** | **准入先于提交**：`_health_sem.acquire(blocking=False)` 失败 ⇒ `metrics.incr('healthz_stale_total')` + 返回"上次快照 + `stale:true`"（无快照则用本次零上游体 + `status='degraded'`）；**不触网、不阻塞、不排队** | 修 P1-3（可达可测） |
| **BR-SRV-19** | 准入成功后，准入位**必须在该批 `len(ROUTES)` 个任务真正结束之后**释放：由每个 future 的 `add_done_callback(_HealthBatch.task_done)` 驱动，归零时调 `_release_health_slot()`（`_set_health_inflight(-1)` + `_health_sem.release()`）**恰好一次**；执行器创建失败/提交失败/异常返回/超时/正常完成**五路均销账**。**禁止**在 `_run_health_checks` 返回时立即释放（P1-1：否则准入位只覆盖轮询窗口 ⇒ 执行器无界队列累积） | 并发正确性 / AC-S8（修 P1-1） |
| **BR-SRV-20** | `check=1` 走专用执行器（`max_workers=MAX_HEALTH_INFLIGHT=5`）与主池物理隔离；**单源**独立 ≤3s（按各自 `submitted_at` 判定）、**整体** ≤10s（多源排队时的总闸，**非死代码**）；超时源记 `status='timeout'` + `status='degraded'` | ADR-006 / AC-S8 / SAD §2.2 R-2（修 P2-2） |
| **BR-SRV-21** | healthz **必须总函数**：调用点以 `_guard(..., shape='object')` 兜底 ⇒ 任何异常返回 `{'error': …}` 且 **HTTP 503**（★ v1.2；★ v1.3 明确**这是 healthz 端点自身语义**——`{'error': …}` 在本端点 ⇒ 服务不可用；**业务端点不采用**，见 BR-SRV-5b），**不得**穿透 | AC-S1 / S2-5 |
| **BR-SRV-22** | `feeds[]`/`cache_ttl`/`request_timeout` 键集合与含义**一个不少**；新增仅 `stale`/`metrics`/`policy`/`cdp`（🟠 STABLE 只增）；`feeds[].status` 取值修正按 §2.9.1（**须编排层批准**） | SAD §2.6 P2-N1 / Q2 |
| **BR-SRV-23** | `cache_ttl` = `cache_policy('feed')['ttl']`（字段名与含义不变，取值跟随 policy） | ADR-001 / Q2 |
| **BR-SRV-24** | `_remember_health_snapshot` 仅在**成功组装**（含 `check=1` degraded 结果）后调用；**准入失败路径不刷新快照**（否则 stale 链会自我覆盖） | 设计裁决（§10#5） |

### 4.6 过载与守护

| 编号 | 规则 | 依据 |
|------|------|------|
| **BR-SRV-25** | inflight 达 `MAX_INFLIGHT` ⇒ **立即 503**（`{"error":"server busy"}`）+ `metrics.incr('http_503_total')`；**不排队**、不等待；撤销负载后 5s 内恢复 200（无残留准入） | AC-E8 / S5 |
| **BR-SRV-26** | `_cdp_memory_watchdog`：`time.sleep(CDP_RESTART_INTERVAL)` → `reason = cdp_engine.watchdog_restart_skip_reason()`；`reason is not None` ⇒ `log.info('…skipped (%s)', reason)` + `continue`（**本轮跳过、顺延下一周期、不累积**）；否则 `log.info(...)` + `full_chrome_restart()`；`except Exception` 仅日志 | ADR-012 / R19 |
| **BR-SRV-27** | 4 面板 handler（A 类）**只经** `cdp_engine.page_data(page)` 取数；`None` ⇒ `{'error': …}`；`timeline` 键为 `None` ⇒ `{'error': 'timeline unavailable'}`（**禁止裸 `null`**）；**删除**对 `page.get_data()` 的直接 `.pop/.get` 链 | R18 / AC-S4 |
| **BR-SRV-28** | 5 个 RSS handler 的 `ttl` 一律 `cache_policy('news_url')['ttl']`；`fetch_json` 调用点**签名零改动**（`encoding` 默认 utf-8） | ADR-001 / `cache.md` §2.6#1–#5 |
| **BR-SRV-29** | 启动日志的 `Cache TTL` 读 `cache_policy('feed')['ttl']`（删 `CACHE_TTL` 后不得留断链）；`main()` 中 `_cdp_memory_watchdog` 依赖的 import 与 `config.cdp_engine` 槽语义不变 | 现状 + Q3 |
| **BR-SRV-30** | `/cls/hotplate`（3 分区）、`/cls/plate`（3 段）、`/ths/longhu`（2 URL）的多上游请求**一律**经 `_get_fanout_executor()`（`max_workers=_FANOUT_MAX_WORKERS=3`）**≤3 并发展开**；单端点耗时 = `max(单次取数)` 而非 `sum`，上界 = 一次 `fetch_json` ≤ `REQUEST_TIMEOUT`(10s) ⇒ **单请求 ≤15s（AC-E2）**。**禁止**多上游串行累加（SAD §4.1 明令本轮修） | SAD §4.1 / **AC-E2**（修 P1-2） |
| **BR-SRV-31** | `/cls/hotplate` 失败形态**唯一口径**：分区 error 客体（`plate_<type>` = `{'error':…}`，分区可独立降级）+ **三分区全失败时顶层补 `error`**（值 = 三块 error 摘要）；`hot_plates` 仅在至少一个分区取到 `main_fund_diff` 时出现 | SAD §2.3 D-4 / §2.4 / AC-A5（修 P1-3） |
| **BR-SRV-32** | **longhu 席位配对（v1.2 / P0 修复）**：每匹配到一个"买入/卖出前5名营业部"`<th>` 标签的表 ⇒ `broker_idx` **无条件自增**（即便该表解析出 0 条 `entries`——`len(bro_cells)<4`、空名、`<th>` 数据行）。`stock_idx = broker_idx // 2` 与 `stocks` 位置配对，**跳过自增会静默错配后续所有股票的席位**（HTTP 200 无错误信号）。`stock_idx >= len(stocks)` ⇒ `log.warning` 丢弃该项（不静默）；末尾 `broker_idx != 2×len(stocks)` ⇒ `log.warning` 错位告警 | P0 / 数据正确性 |
| **BR-SRV-33** | **请求派生 base URL 加固（v1.2 / S2-3）**：`PUBLIC_BASE_URL` 非空则恒优先；否则取 `X-Forwarded-Host` → `Host`，格式校验（`hostname[:port]`/`[v6][:port]`，非法 ⇒ `localhost:PORT`），并在响应标 `Cache-Control: private` + `Vary: Host, X-Forwarded-Host, X-Forwarded-Proto`（feed/opml 体嵌入了该 Host ⇒ 防共享缓存串号污染） | S2-3 |

---

## 5. 伪代码

### 5.1 `_guard`（统一异常边界）

```python
_SHAPES = frozenset({'batch', 'object', 'rss', 'text'})

def _guard(fn, *, shape, requested=None, dropped=0, rss_info=None, feed_url=None):
    """BR-SRV-3：任何 Exception → 按 shape 产出结构化降级体（绝不冒泡）。"""
    if shape not in _SHAPES:                                   # 编程错误：立即暴露
        raise ValueError(f'unknown guard shape: {shape!r}')
    try:
        return fn()
    except Exception as exc:                                    # 不捕 BaseException
        log.exception('[guard:%s] handler raised: %s', shape, exc)
        if shape == 'batch':                                    # 全码 null + _errors
            codes = list(dict.fromkeys(requested or []))
            errors = {c: 'upstream_error' for c in codes}
            return build_batch_response(codes, {}, errors, dropped=dropped)
        if shape == 'rss':
            info = rss_info or {}
            return generate_error_rss(info.get('title', 'feed'),
                                      info.get('link', ''),
                                      info.get('description', ''),
                                      exc, feed_url=feed_url)
        return {'error': str(exc)}                              # object / text
```

### 5.2 `_handle_request`（分发，含 shape 派生）

```python
def _handle_request(self, write_body=True):
    parsed = urlparse(self.path)
    path = parsed.path
    base_url = self._base_url()

    if path == '/':                                             # 静态（无 IO）
        self._serve_index(write_body=write_body); return
    if path == '/opml.xml':                                     # 静态（无 IO）
        # ★ v1.2（S2-3）：OPML 嵌入 base URL ⇒ 请求派生时 private + Vary
        self._send_text(200, 'text/x-opml; charset=utf-8',
                        generate_opml(base_url, ROUTES),
                        varies_on_host=not PUBLIC_BASE_URL, write_body=write_body); return
    if path == '/healthz':                                      # BR-SRV-21：object 兜底
        query = parse_qs(parsed.query)
        check_sources = query.get('check', ['0'])[0] in ('1', 'true', 'yes')
        payload = _guard(lambda: build_health_payload(base_url, check_sources=check_sources),
                         shape='object')
        # ★ v1.2（S2-5）：guard 失败体 {'error': …} 无 status ⇒ 503（不再假健康）
        # ★ v1.3（N1）：该 503 只属 /healthz 自身语义；业务端点降级恒 200（见 _send_json_shape）
        if 'error' in payload or 'status' not in payload:
            status_code = 503
        else:
            status_code = 503 if payload.get('status') == 'degraded' else 200
        if status_code == 503:
            metrics.incr('http_503_total')
        self._send_text(status_code, 'application/json; charset=utf-8',
                        json.dumps(payload, ensure_ascii=False, indent=2),
                        cache=False, write_body=write_body); return

    # ── 4 面板（object）— handler 与 shape 均取自派发表 ────────
    if path in _PANEL_HANDLERS:
        self._send_json_shape(path, _PANEL_HANDLERS[path], write_body=write_body); return

    # ── 6 批量（batch）— shape 由表派生 ────────────────────────
    if path in _STOCK_BATCH_HANDLERS:
        self._handle_stock_batch(parsed, _STOCK_BATCH_HANDLERS[path],
                                 write_body=write_body, path=path); return

    # ── 其余 4 个 JSON 分支 ─────────────────────────────────────
    if path == '/cls/hotplate':
        self._send_json_shape(path, handle_cls_hotplate, write_body=write_body); return
    if path == '/cls/plate':
        code = parse_qs(parsed.query).get('code', [''])[0]
        if not code:                                              # 400 在 guard 之前
            self._send_error('Missing ?code= parameter. Usage: /cls/plate?code=cls80484',
                             write_body=write_body); return
        self._send_json_shape(path, lambda: handle_cls_plate(code),
                              write_body=write_body); return
    if path == '/ths/longhu':                                     # text：JSON 体、cache=False
        data = _guard(handle_ths_longhu, shape=_JSON_SHAPES[path])
        self._send_text(200, 'application/json; charset=utf-8',
                        json.dumps(data, ensure_ascii=False, indent=2),
                        cache=False, write_body=write_body); return
    if path == '/market/margin':
        market = parse_qs(parsed.query).get('market', ['99'])[0]
        if market not in VALID_MARKETS:                            # ★ v1.2：400 在 guard 之前
            self._send_error('Invalid ?market= parameter. Allowed: '
                             + ','.join(VALID_MARKETS), write_body=write_body); return
        self._send_json_shape(path, lambda: handle_margin(market),
                              write_body=write_body); return

    # ── 5 RSS（rss）─────────────────────────────────────────────
    if path in ROUTES:
        self._serve_feed(path, base_url, write_body=write_body); return

    self.send_error(404, 'Not Found. Visit / for available feeds.')          # BR-SRV-1
```

- `_STOCK_BATCH_HANDLERS` 与 `_JSON_SHAPES` 的 `batch` 六项**必须同集合**（`assert ...`，导入期）；`_JSON_DISPATCHED_PATHS == frozenset(_JSON_SHAPES)` 亦为导入期断言（新增表项必须有分支）。
- `_send_json(data, write_body=True, cache=True)`（★ v1.3：**无 `status` 形参**，恒 200）；`_send_json_shape` 是 7 个 object JSON 分支的唯一出口（shape 从表读；**恒 200 + 原样降级体，且 `cache=cache` ⇒ 降级体按域 TTL 可缓存**）；`/ths/longhu` 仍走 `_send_text`（text shape，`cache=False`）。

### 5.3 `_handle_stock_batch`（dropped 注入）

```python
def _handle_stock_batch(self, parsed, handler, write_body=True, path=None):
    params = parse_qs(parsed.query)
    if 'code' not in params:
        self._send_error('Missing ?code= parameter. Usage: /stock/...?code=sh600519 or ...?code=sh600519,sz000001',
                         write_body=write_body); return
    # ★ v1.2（P1-6）：入口折叠 —— stock_codes=canonical 去重码；requested=请求原拼写
    stock_codes, requested = _parse_stock_codes(params['code'][0])
    if not stock_codes:
        self._send_error('No valid stock codes provided.', write_body=write_body); return
    dropped = 0
    if len(stock_codes) > _MAX_BATCH_SIZE:                        # BR-SRV-14（按归一后码数）
        dropped = len(stock_codes) - _MAX_BATCH_SIZE
        log.warning(f'Batch truncated: {dropped} codes dropped, '
                    f'samples={stock_codes[_MAX_BATCH_SIZE:_MAX_BATCH_SIZE+3]}')
        stock_codes = stock_codes[:_MAX_BATCH_SIZE]
        requested = requested[:_MAX_BATCH_SIZE]                   # 保持对齐
    data = _guard(lambda: handler(stock_codes, dropped=dropped),  # BR-SRV-15：只传参，不重复组装
                  shape=_JSON_SHAPES.get(path, 'batch'),
                  requested=requested, dropped=dropped)
    data = _rekey_batch_response(data, stock_codes, requested)    # ★ v1.2：响应键回原拼写
    self._send_text(200, 'application/json; charset=utf-8',
                    json.dumps(data, ensure_ascii=False, indent=2),
                    cache=True, write_body=write_body)


def _parse_stock_codes(codes_str):
    """★ v1.2（P1-6）：(canonical 去重码, 请求原拼写)。无效码 ⇒ 以自身拼写为身份（逐码 null）。"""
    codes, requested, seen = [], [], set()
    for raw in codes_str.split(','):
        raw = raw.strip()
        if not raw:
            continue
        canon = config.canonical_code(raw)
        key = canon if canon is not None else raw
        if key in seen:                                           # 重复拼写不占第二个槽
            continue
        seen.add(key)
        codes.append(key)
        requested.append(raw)
    return codes, requested


def _rekey_batch_response(data, codes, requested):
    """★ v1.2（P1-6）：纯改名（键集不变）；无需改写时原样返回。"""
    if not isinstance(data, dict):
        return data
    rename = dict(zip(codes, requested))
    if not any(canon != raw for canon, raw in rename.items()):
        return data
    out = {}
    for key, value in data.items():
        if key == '_errors' and isinstance(value, dict):
            out[key] = {rename.get(c, c): kind for c, kind in value.items()}
        elif key.startswith('_'):
            out[key] = value
        else:
            out[rename.get(key, key)] = value
    return out
```

### 5.4 `_get_or_fetch_feed`（双检）+ `_serve_feed`（rss shape）

```python
def _get_or_fetch_feed(self, path, fetch_func):
    """BR-SRV-6/7：防击穿（per-path 锁）+ 双检；LRU/TTL/清扫归 cache 层。"""
    xml = feed_cache_get(path)                                     # ①（命中路径不读 policy —— P2-1）
    if xml is not None:
        return xml
    with _feed_fetch_locks_lock:                                   # ②（立即释放）
        lock = _feed_fetch_locks.setdefault(path, threading.Lock())
    with lock:                                                     # ③
        xml = feed_cache_get(path)                                 # ★ 双检
        if xml is not None:
            return xml
        ttl = cache_policy('feed')['ttl']                           # ★ P2-1：二次 get 仍 miss 后才求值
        xml = fetch_func()                                         # 仅 miss 才回源
        feed_cache_put(path, xml, ttl)
    return xml


def _serve_feed(self, path, base_url, write_body=True):
    info = ROUTES[path]
    feed_url = base_url + path
    xml = _guard(lambda: self._get_or_fetch_feed(path, lambda: info['handler'](feed_url=feed_url)),
                 shape='rss', rss_info=info, feed_url=feed_url)     # 异常 → generate_error_rss
    # ★ v1.2（S2-3）：feed 体嵌入 feed_url（请求派生 Host 时）⇒ private + Vary
    self._send_text(200, 'application/rss+xml; charset=utf-8', xml,
                    varies_on_host=not PUBLIC_BASE_URL, write_body=write_body)
```

### 5.5 外部上游扇出（`_fetch_concurrent`）+ plate stagger + longhu GBK

```python
_FANOUT_MAX_WORKERS = 3
_FANOUT_WAIT_BUDGET = REQUEST_TIMEOUT          # ★ v1.2：一轮扇出的排空上界
_fanout_executor = None
_fanout_lock = threading.Lock()


def _get_fanout_executor():
    """BR-SRV-30：hotplate/plate/longhu 共享的 ≤3 并发扇出执行器（懒创建，双检）。"""
    global _fanout_executor
    with _fanout_lock:
        if _fanout_executor is None:
            _fanout_executor = ThreadPoolExecutor(max_workers=_FANOUT_MAX_WORKERS,
                                                  thread_name_prefix='fanout')
        return _fanout_executor


def _fetch_concurrent(specs):
    """specs=[(key, fn)]；≤3 并发展开；返回 {key: 结果 或 Exception}（**不抛**）。顺序 = specs 顺序。"""
    if not specs:
        return {}
    if len(specs) == 1:                                    # 单元素：走当前线程（免池化开销）
        k, fn = specs[0]
        try:
            return {k: fn()}
        except Exception as exc:
            return {k: exc}
    ex = _get_fanout_executor()
    futs = {ex.submit(fn): k for k, fn in specs}
    done, _ = wait(futs, timeout=_FANOUT_WAIT_BUDGET)      # ★ v1.2：有界排空（P1-2）
    out = {}
    for fut, k in futs.items():                            # 固定顺序消费（确定性）
        if fut in done:
            try:
                out[k] = fut.result()
            except Exception as exc:
                out[k] = exc
            continue
        fut.cancel()                                       # 排队中 ⇒ 永不运行；已在跑 ⇒ 自身 10s 界
        out[k] = FetchError('upstream_timeout')
    return out


def _plate_ttls():
    """BR-SRV-10：从 policy 基值派生 stagger（D-7 明令保留三档）。"""
    base = cache_policy('plate')['ttl']
    return base, max(3, base // 4)


def handle_cls_hotplate(feed_url=None):
    """BR-SRV-30/31：3 分区 **≤3 并发**（SAD §4.1）；分区 error 客体 + 全失败补顶层 error。"""
    result = {}
    hot_plates = None
    base, stagger = _plate_ttls()
    offsets = {'industry': 0, 'concept': stagger, 'area': stagger * 2}   # 分区序 0/1/2
    specs = []
    for ptype in ('industry', 'concept', 'area'):
        params = {'app': 'CailianpressWeb', 'os': 'web', 'sv': '8.7.9',
                  'type': ptype, 'way': 'change', 'page': 1, 'rever': 1}
        params['sign'] = cls_sign_params(params)
        url = f'{_HOTPLATE_BASE_URL}?{urlencode(params)}'
        ttl = base + offsets[ptype]                        # ★ 默认参数捕获（闭包不可引用循环变量）
        specs.append((ptype, lambda url=url, ttl=ttl:
                      json.loads(fetch_json(url, _HOTPLATE_HEADERS, ttl=ttl))))
    fetched = _fetch_concurrent(specs)                     # ★ ≤3 并发：P95 = max 而非 sum
    errors = []
    for ptype in ('industry', 'concept', 'area'):          # ★ 固定消费顺序（确定性）
        raw = fetched.get(ptype)
        if isinstance(raw, Exception):
            result[f'plate_{ptype}'] = {'error': str(raw)}  # 分区 error 客体（分区可独立降级）
            errors.append(str(raw))
            continue
        data = raw.get('data') or raw
        result[f'plate_{ptype}'] = data
        if hot_plates is None:
            mfd = data.get('main_fund_diff') or {}
            top = mfd.get('top_main_fund_diff') or []
            last = mfd.get('last_main_fund_diff') or []
            if top or last:
                hot_plates = top + last
    if hot_plates:
        result['hot_plates'] = hot_plates
    if len(errors) == len(specs):                          # ★ BR-SRV-31：全分区失败 ⇒ 顶层补 error
        result['error'] = '; '.join(errors)                #   值 = 三块 error 摘要（SAD §2.3 D-4 唯一口径）
    return result


def handle_cls_plate(code):
    """BR-SRV-12/30：3 段 **≤3 并发**（SAD §4.1）；分区失败语义逐字保留。"""
    result = {'code': code}
    base, stagger = _plate_ttls()                          # info=0 / stocks=1 / industry=2

    def _signed_url(base_url, extra=None):                 # 逐字保留（现状签名逻辑）
        params = {'app': 'CailianpressWeb', 'os': 'web', 'sv': '8.7.9', 'secu_code': code}
        if extra:
            params.update(extra)
        params['sign'] = cls_sign_params(params)
        return f'{base_url}?{urlencode(params)}'

    specs = [
        ('info',     lambda: json.loads(fetch_json(_signed_url(_PLATE_INFO_URL),
                                                  _PLATE_HEADERS, ttl=base))),
        ('stocks',   lambda: json.loads(fetch_json(_signed_url(_PLATE_STOCKS_URL),
                                                  _PLATE_HEADERS, ttl=base + stagger))),
        ('industry', lambda: json.loads(fetch_json(_signed_url(_PLATE_INDUSTRY_URL),
                                                  _PLATE_HEADERS, ttl=base + stagger * 2))),
    ]
    fetched = _fetch_concurrent(specs)                     # ★ ≤3 并发

    raw = fetched.get('info')                              # 1) info：失败 ⇒ error 客体（逐字保留语义）
    if isinstance(raw, Exception):
        result['info'] = {'error': str(raw)}
    elif raw.get('code') == 200:
        result['info'] = raw.get('data', {})
    else:
        result['info'] = {'error': raw.get('msg', 'unknown')}

    raw = fetched.get('stocks')                            # 2) stocks：失败/非 200 ⇒ []（逐字保留）
    result['stocks'] = raw.get('data', {}).get('stocks', []) \
        if (not isinstance(raw, Exception) and raw.get('code') == 200) else []

    raw = fetched.get('industry')                          # 3) industry：失败/非 200 ⇒ []（逐字保留）
    result['industry'] = raw.get('data', []) \
        if (not isinstance(raw, Exception) and raw.get('code') == 200) else []
    return result


def handle_ths_longhu():
    """BR-SRV-9/30/32：走统一取数入口 + policy encoding + **2 URL 并发**（R15 / AC-E2）。"""
    policy = cache_policy('longhu')
    ttl = policy['ttl']                                    # L4 = 300
    encoding = policy.get('encoding', 'utf-8')             # ★ v1.2：encoding 取自 policy（=gbk）
    fetched = _fetch_concurrent([                          # ★ 2 URL 并发：≤ max 而非 sum（≈20s → ≈10s）
        ('table', lambda: fetch_json(_LHBTABLE_URL, _LHBTABLE_HEADERS, ttl=ttl, encoding=encoding)),
        ('page',  lambda: fetch_json(_LONGHU_PAGE_URL, _LONGHU_PAGE_HEADERS, ttl=ttl, encoding=encoding)),
    ])
    stock_html = fetched['table']
    if isinstance(stock_html, Exception):                  # 任一 URL 失败 ⇒ 抛给 _guard('text') 兜底
        raise stock_html
    rows = re.findall(r'<tr[^>]*>(.*?)</tr>', stock_html, re.DOTALL)
    ...                                                    # 解析逻辑逐字保留（cells/营业部）
    page_html = fetched['page']
    if isinstance(page_html, Exception):
        raise page_html
    broker_idx = 0
    for tbl in re.findall(r'<table[^>]*>(.*?)</table>', page_html, re.DOTALL):
        ...                                                # 标签匹配 + entries 解析逐字保留
        stock_idx = broker_idx // 2
        if stock_idx >= len(stocks):
            log.warning('[longhu] broker table #%d (%s) has no matching stock row (stocks=%d): entries dropped',
                        broker_idx, kind, len(stocks))     # ★ v1.2：不静默丢弃
        elif entries:
            stocks[stock_idx][kind] = entries
        broker_idx += 1                                    # ★ v1.2（P0）：无条件自增（即便 entries 为空）
    if broker_idx != 2 * len(stocks):
        log.warning('[longhu] %d broker tables matched but %d stocks expect %d — buy/sell pairing is misaligned',
                    broker_idx, len(stocks), 2 * len(stocks))
    return {'data': stocks, 'total': len(stocks)}
```

> **并发正确性**：`_fetch_concurrent` 提交后**阻塞等待全部 future**（每个 `fn` 自身的上界 = `fetch_json` 的 `REQUEST_TIMEOUT=10s`）⇒ 单端点耗时上界 = `10s + 解析` ≤ 15s（AC-E2）。共享执行器保证**全局**在这些端点上的在飞取数 ≤3（SAD §4.1），满足 AC-E8 的资源口径。

### 5.6 healthz（有界准入 + 预算 + 快照）

```python
_MAX_HEALTH_INFLIGHT = config.MAX_HEALTH_INFLIGHT                    # 5（config.md §2.3）


def _release_health_slot():
    """BR-SRV-19：释放一次准入位（仅由 _HealthBatch 调用；每个准入批次恰好一次）。"""
    _set_health_inflight(-1)
    _health_sem.release()


class _HealthBatch:
    """BR-SRV-19（修 P1-1）：一次 ?check=1 的在飞记账。

    准入位必须覆盖**该批任务的真实在飞**——轮询在 ~3s 即 break，未完成 future 仍会跑；
    若此时就 release，持续慢 check 会把提交量灌进专用执行器（max_workers=5、工作队列无界）
    ⇒ 重演 SAD P1-3 要消除的放大器。故 release 由「本批全部 future 结束」驱动。"""
    __slots__ = ('_remaining', '_lock', '_done')

    def __init__(self, n):
        self._remaining = n
        self._lock = threading.Lock()
        self._done = False

    def task_done(self, _fut=None):
        """future 完成回调；幂等 —— 归零时释放准入位一次。"""
        release = False
        with self._lock:
            self._remaining -= 1
            if self._remaining <= 0 and not self._done:
                self._done = True
                release = True
        if release:
            _release_health_slot()

    def settle(self):
        """★ v1.2（P1-5）：异常路径立即释放（不看 _remaining）；与 task_done 共享 _done ⇒ 绝不双放。"""
        release = False
        with self._lock:
            if not self._done:
                self._done = True
                release = True
        if release:
            _release_health_slot()


def _get_health_executor():
    global _health_executor
    with _health_executor_lock:                                      # 双检懒创建
        if _health_executor is None:
            _health_executor = ThreadPoolExecutor(
                max_workers=_MAX_HEALTH_INFLIGHT, thread_name_prefix='healthz')
        return _health_executor


def _check_one_feed(feed_path, base_url, info):
    """总函数：任何异常 → error 条目（绝不抛）。"""
    try:
        xml = info['handler'](feed_url=base_url + feed_path)
        return {'status': 'ok', 'items': count_rss_items(xml), 'error': None}
    except Exception as exc:
        return {'status': 'error', 'items': None, 'error': str(exc)}


def _run_health_checks(base_url, batch=None):
    """BR-SRV-20：5 源并发；**每源独立 3s**、整体 ≤10s；
    准入位由 `batch` 在**每个 future 真正结束**时销账（修 P1-1）。
    ★ v1.2（P1-5）：调用方可传入自建账本，异常时可 `settle()` 而非泄漏。
    捕获 `Exception`；`BaseException` 上抛由调用方 guard 处理。"""
    out = {}
    try:
        executor = _get_health_executor()
    except Exception as exc:                                         # 执行器创建失败 ⇒ 全 error + 归还准入位
        for path in ROUTES:
            out[path] = {'status': 'error', 'items': None, 'error': str(exc)}
        _release_health_slot()
        return out

    if batch is None:
        batch = _HealthBatch(len(ROUTES))                            # 直调兜底（先设账，再提交）
    started = time.monotonic()
    pending = {}                                                     # fut -> (path, submitted_at)
    for path, info in ROUTES.items():
        try:
            fut = executor.submit(_check_one_feed, path, base_url, info)
        except Exception as exc:                                     # 提交失败也销账，防准入位泄漏
            out[path] = {'status': 'error', 'items': None, 'error': str(exc)}
            batch.task_done()
            continue
        fut.add_done_callback(batch.task_done)                       # ★ P1-1：完成即销账
        pending[fut] = (path, time.monotonic())

    while pending:
        now = time.monotonic()
        for fut in [f for f, (_p, t) in pending.items()
                    if now - t >= _HEALTH_SOURCE_BUDGET]:            # ★ P2-2：每源独立 3s
            out[pending.pop(fut)[0]] = {'status': 'timeout', 'items': None, 'error': 'timeout'}
        if not pending:
            break
        elapsed = now - started
        if elapsed >= _HEALTH_TOTAL_BUDGET:                          # ★ 整体 10s 闸（多源排队时生效）
            break
        next_due = min(t for _p, t in pending.values()) + _HEALTH_SOURCE_BUDGET
        timeout = min(_HEALTH_POLL, max(0.0, next_due - now),
                      max(0.0, _HEALTH_TOTAL_BUDGET - elapsed))
        done, _ = wait(set(pending), timeout=timeout, return_when=FIRST_COMPLETED)
        for fut in done:
            path = pending.pop(fut)[0]
            try:
                out[path] = fut.result()                             # 总函数，正常不抛
            except Exception as exc:                                 # ★ v1.2（P1-5）：等待中途也不上抛
                out[path] = {'status': 'error', 'items': None, 'error': str(exc)}
    for fut, (path, _t) in pending.items():                          # 整体预算耗尽：余下判 timeout
        out[path] = {'status': 'timeout', 'items': None, 'error': 'timeout'}
    return out


def _remember_health_snapshot(payload):
    global _health_last_snapshot
    with _health_last_lock:                                           # 深拷贝（json round-trip，不用 copy 模块）
        _health_last_snapshot = json.loads(json.dumps(payload, ensure_ascii=False))


def build_health_payload(base_url, check_sources=False):
    feeds = _base_feed_entries(base_url)                              # 15 条（§2.9.1 修正后 status）
    status = 'ok'

    if check_sources:
        if not _health_sem.acquire(blocking=False):                   # BR-SRV-18：有界准入
            metrics.incr('healthz_stale_total')
            with _health_last_lock:
                snap = _health_last_snapshot
            if snap is None:                                          # 首个 check 即被拒：给可解析的降级体
                snap = {'status': 'degraded',
                        'cache_ttl': cache_policy('feed')['ttl'],
                        'request_timeout': REQUEST_TIMEOUT,
                        'feeds': feeds, 'metrics': metrics.snapshot(),
                        'policy': _policy_snapshot(),
                        'cdp': restart_window_snapshot()}
            return {**snap, 'stale': True}                            # 不触网、不刷新快照（BR-SRV-24）
        _set_health_inflight(+1)
        # ★ v1.2（P1-5）：账在风险调用之前建好 ⇒ 异常路径也能恰好销账一次
        batch = _HealthBatch(len(ROUTES))
        try:
            results = _run_health_checks(base_url, batch)              # 准入位由 _HealthBatch 释放（P1-1）
        except BaseException:
            batch.settle()
            raise
        for entry in feeds:
            res = results.get(entry['path'])
            if res is None:
                continue
            entry['status'] = res['status']
            if res['items'] is not None:
                entry['items'] = res['items']
            if res['error'] is not None:
                entry['error'] = res['error']
            if res['status'] != 'ok':
                status = 'degraded'

    payload = {'status': status,
               'cache_ttl': cache_policy('feed')['ttl'],              # BR-SRV-23：字段名不变，取值接 policy
               'request_timeout': REQUEST_TIMEOUT,
               'feeds': feeds,
               'metrics': metrics.snapshot(),
               'policy': _policy_snapshot(),
               'cdp': restart_window_snapshot()}
    _remember_health_snapshot(payload)                                # BR-SRV-24
    return payload


def _policy_snapshot():
    return {d: cache_policy(d) for d in sorted(DOMAIN_MATRIX)}
```

### 5.7 服务类 + 守护线程

```python
class BoundedThreadPoolServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True
    request_queue_size = LISTEN_BACKLOG               # ★ v1.2（BUG-P6C-03）

    def __init__(self, *args, max_workers=MAX_WORKERS, max_inflight=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self._inflight = 0
        self._inflight_lock = threading.Lock()
        self._max_inflight = MAX_INFLIGHT if max_inflight is None else max_inflight
        #                    ★ 默认 MAX_INFLIGHT(40)；流端口显式传 110（修 P1-4）

    def _reject_503(self, request):
        try:
            body = b'{"error":"server busy"}'
            request.sendall(b'HTTP/1.1 503 Service Unavailable\r\n'
                            b'Content-Type: application/json\r\n'
                            b'Content-Length: ' + str(len(body)).encode() + b'\r\n'
                            b'Connection: close\r\n\r\n' + body)
        except Exception:
            pass
        finally:
            try:
                metrics.incr('http_503_total')                          # BR-SRV-25（主端口准入拒绝的计数点）
            except Exception:
                pass
            try:
                request.close()
            except Exception:
                pass

    def process_request(self, request, client_address):                # 现状逻辑逐字保留
        with self._inflight_lock:
            if self._inflight >= self._max_inflight: overloaded = True
            else: self._inflight += 1; overloaded = False
        if overloaded:
            self._reject_503(request); return
        try:
            fut = self.executor.submit(self.process_request_thread, request, client_address)
        except Exception:
            with self._inflight_lock:
                self._inflight -= 1
            self._reject_503(request); return
        fut.add_done_callback(self._release_inflight)


def _cdp_memory_watchdog():
    """BR-SRV-26：决策集中在 cdp_engine（ADR-012 盘中避让 + 节流 + 重入）。"""
    while True:
        time.sleep(CDP_RESTART_INTERVAL)
        try:
            reason = watchdog_restart_skip_reason()
            if reason is not None:
                log.info('  [CDP] watchdog: restart skipped (%s)', reason)
                continue                                                # 顺延下一周期，不累积
            log.info('  [CDP] watchdog: restarting Chrome to reclaim renderer memory')
            full_chrome_restart()
        except Exception as e:
            log.error(f'  [CDP] watchdog error: {e}')
```

### 5.8 `_cache_age` / `_send_*`（TTL 接 policy）

```python
def _base_url(self):
    """★ v1.2（S2-3）：PUBLIC_BASE_URL 恒优先；否则校验 Host 格式（非法 ⇒ localhost:PORT）。"""
    if PUBLIC_BASE_URL:
        return PUBLIC_BASE_URL
    proto = _normalize_proto(self.headers.get('X-Forwarded-Proto'))
    raw = self.headers.get('X-Forwarded-Host') or self.headers.get('Host') or ''
    host = raw.split(',')[0].strip()
    if not _valid_host_header(host):
        host = f'localhost:{PORT}'
    return f'{proto}://{host}'.rstrip('/')

def _cache_age(self):
    """BR-SRV-8：path → domain → policy（禁止裸 TTL 字面量）。"""
    path = urlparse(self.path).path               # ★ v1.2：与路由同规则
    domain = _CACHE_AGE_DOMAINS.get(path, _DEFAULT_AGE_DOMAIN)
    return cache_policy(domain)['ttl']

def _send_text(self, status_code, content_type, body, cache=True,
               varies_on_host=False, write_body=True):                   # ★ v1.2 增 varies_on_host
    body_bytes = body.encode('utf-8')
    self.send_response(status_code)
    self.send_header('Content-Type', content_type)
    self.send_header('Content-Length', str(len(body_bytes)))
    if cache:
        scope = 'private' if varies_on_host else 'public'                # ★ v1.2：请求派生 Host ⇒ private
        self.send_header('Cache-Control', f'{scope}, max-age={self._cache_age()}')
        if varies_on_host:
            self.send_header('Vary', _BASE_URL_VARY)
    self.end_headers()
    if write_body:
        self.wfile.write(body_bytes)

def _send_json(self, data, write_body=True, cache=True):                 # ★ v1.3：无 status（恒 200）
    self._send_text(200, 'application/json; charset=utf-8',
                    json.dumps(data, ensure_ascii=False, indent=2),
                    cache=cache, write_body=write_body)

def _send_json_shape(self, path, fn, write_body=True, cache=True):       # ★ v1.2；v1.3 简化
    """shape 从 `_JSON_SHAPES[path]` 读 → `_guard` 兜底 → **恒 200** 发送。

    ★ v1.3（N1 裁决）：业务降级体（`{'error': …}` / `_error`）以 **200 + 结构化 error
    体** 返回，**状态码不由 payload 内容决定**（v1.2 的 `_json_payload_has_data` 与
    503 分支已删）。真实 503 仅：连接准入 `_reject_503`、流端口 `_serve_sse` 超限、
    `/healthz`（端点自身语义）。降级体沿 `cache=cache` ⇒ 按域 TTL 可缓存。
    """
    payload = _guard(fn, shape=_JSON_SHAPES[path])
    self._send_json(payload, write_body=write_body, cache=cache)

def _send_error(self, msg, write_body=True):                             # ★ 增 write_body（HEAD 不写体，见 §10#3）
    self._send_text(400, 'application/json; charset=utf-8',
                    json.dumps({'error': msg}, ensure_ascii=False, indent=2),
                    cache=False, write_body=write_body)
```

**`_cache_age` 行为变更登记**（值来源由 `_trading_tiers()[tier]` 改 `cache_policy(domain)['ttl']`）

| path | 现状 max-age | 目标 max-age（盘 / 非盘） | 说明 |
|------|-------------|------------------------|------|
| `/stock/data` `/stock/basic_info` `/stock/fundflow` `/stock/timeline` | L1（8 / 120） | 8 / 120（不变） | quote/fundflow/timeline |
| `/stock/f10` | L4（300） | 300 / 300（不变） | f10 域 |
| `/stock/announcement` | L4（300） | **30 / 180**（变更） | 纠正漂移：与 announcement 域 L3 对齐 |
| `/cls/hotplate` `/cls/plate` | L2（12 / 120） | 12 / 120（不变） | plate 基值（stagger 不进 `max-age`，现状亦然） |
| `/market/margin` | L4（300） | **600 / 600**（变更） | 与 margin 域 TTL 对齐 |
| `/ths/longhu` | L4（300） | 300（不变） | longhu 域 |
| 5 RSS | L3（30 / 180） | 30 / 180（不变） | news_url 域 |
| **面板 4**（`/finance/market` `/finance/timeline` `/quotation/market` `/market/timeline`） | L4（300） | **8 / 120**（★ v1.2 变更） | 注册到 `quote` 域（实时行情面，**不再**落 300s 兜底） |
| `/healthz` / `/` / `/opml.xml` | L4（300） | 300（不变） | `_DEFAULT_AGE_DOMAIN='f10'`（L4 恒 300）；未登记路径现仅此三项 |
| 请求派生 Host（`PUBLIC_BASE_URL` 未设）的 feed/opml | `public` | **`private` + `Vary`**（★ v1.2） | S2-3 防共享缓存串号 |

### 5.9 `main()` 的改动点（仅 3 处）

```python
    # ① 启动日志 TTL 来源（删 CACHE_TTL 后不得留断链）
    log.info(f'Cache TTL: {cache_policy("feed")["ttl"]}s | Timeout: {REQUEST_TIMEOUT}s')
    # ② 后台线程清单不变（warm_jin10 / init_cdp / _cdp_memory_watchdog / 4 prefetch / push_loop / run_stream_server）
    # ③ 服务类构造不变：BoundedThreadPoolServer(('0.0.0.0', PORT), RSSHandler)
```

`_serve_index` 的 `json_apis` 表仅改 3 个 `needs_cdp` 布尔（§2.9.1 表）。

---

## 6. 错误处理

### 6.1 错误语义矩阵（唯一口径）

| 情形 | 触发点 | HTTP | 响应体 | 计量 |
|------|--------|------|--------|------|
| 缺 `?code=`（6 批量） | `_handle_stock_batch` 步骤 1 | 400 | `{"error":"Missing ?code= parameter. …"}` | — |
| 码全为空串（6 批量） | 步骤 2 | 400 | `{"error":"No valid stock codes provided."}` | — |
| 缺 `?code=`（`/cls/plate`） | `_handle_request` | 400 | `{"error":"Missing ?code= parameter. …"}` | — |
| 非法码**值**（`/stock/*`） | `_parse_stock_codes` → handler | 200 | 该码逐码 `null`（★ v1.2：**非** 400） | — |
| `/market/margin` 非法 `market` | `_handle_request` | 400 | `{"error":"Invalid ?market= parameter. Allowed: 99,1,2,3"}` ★ v1.2 | — |
| 未知路径 | 兜底 | 404 | 文本 | — |
| 过载（inflight ≥ `MAX_INFLIGHT`） | `process_request` | 503 | `{"error":"server busy"}` | `http_503_total++`（**真实 503 ①**） |
| 流端口连接数 ≥ `MAX_STREAM_CONNS` | `stream._serve_sse` | 503 | `{"error":"too many stream connections"}` | `http_503_total++`（**真实 503 ②**，见 `stream.md`） |
| **业务端点降级体**（4 面板 / hotplate 全失败 / margin `_error` / guard 捕获体 / plate 分区降级） | `_guard` → `_send_json_shape` | **200** ★ v1.3（N1 回退） | payload 原样（含 `{'error':…}` / `_error` 客体）；`_send_json_shape` 以 `cache=True` 发送 ⇒ **按域 TTL 可缓存** | — |
| `/healthz` body 缺 `status` 或含 `error` | `_handle_request` | **503** ★ v1.2（**healthz 自身语义**） | payload 原样 | `http_503_total++`（**真实 503 ③**） |
| 上游失败（批量） | handler → `_errors` | 200 | 逐码 `null` ∧ `_errors[code] ∈ KINDS` | `upstream_fail_total{kind}`（stock_api/cache） |
| 上游失败（单体/面板/工具） | handler 返回 error 客体 | 200 | `{"error": …}` 或 `_error` 枚举（margin） | 同上 |
| 上游失败（`/cls/hotplate` **全分区**） | handler 三分区全 error | 200 | `{'plate_industry':{'error':…},'plate_concept':{'error':…},'plate_area':{'error':…}, 'error':'<三块摘要>'}`（**顶层补 `error`**，SAD §2.3 D-4 / BR-SRV-31） | 同上 |
| 上游失败（`/cls/hotplate` 部分分区） | handler 仅失败分区 | 200 | 失败分区为 `{'error':…}`，其余正常；**无顶层 `error`**、无 `hot_plates` | 同上 |
| 上游失败（RSS） | `rss` shape | 200 | `generate_error_rss`（合法 feed + 诊断 item） | 同上 |
| CDP 不可用（面板 4） | `page_data → None` | **200** ★ v1.3（N1 回退） | `{"error":"…"}` | — |
| CDP 不可用（`/stock/f10`） | `FetchError('cdp_unavailable')` | 200 | 逐码 `null` ∧ `_errors[code]='cdp_unavailable'` | `upstream_fail_total{cdp_unavailable}` |
| healthz 准入失败 | `_health_sem.acquire` | 200 或 503（依 `payload['status']`） | 上次快照 + `stale:true` | `healthz_stale_total++` |
| healthz 单源超时 | `_run_health_checks` | 200/503 | `feeds[].status='timeout'` + `error='timeout'`，`status='degraded'` | — |
| **任意 handler 抛异常** | `_guard` | 200 | 按 shape（§4.1 矩阵） | — |
| 客户端断开（写入期） | `do_GET`/`do_HEAD` 既有 except | — | 无（连接已关） | — |

### 6.2 降级路径（分层，互不混淆）

```
网络层（cache.fetch_json）  → 负缓存 + FetchError(kind)（cache.md 四段式）
   ↓
业务层（stock_api）         → (results, errors) + _fail_ledger 120s 冷却
   ↓
组装层（build_batch_response）→ 保留键（_errors/_truncated/_dropped_count）
   ↓
端点层（server）            → _guard(shape) 兜底 + JSON 序列化 + HTTP 状态
```

**关键不变式（可断言）**

1. **批量响应无顶层 `error`；单体响应无逐码值域**（跨类别即判失配，AC-A5）。
2. **任何 handler 异常都有结构化响应体**（`batch`→全码 null；`object`/`text`→`{'error'}`；`rss`→error feed）——`_guard` 是唯一收口（AC-S1）。
3. **过载即 503、不排队**：`_inflight` 只在 `process_request` 增减，`_release_inflight` 由 future 回调保证成对（AC-E8/S5）。
4. **healthz 准入位恰好释放一次**：`acquire` 成功 → 该批任务全部结束后由 `_HealthBatch` 释放（**不是** `finally` 立即释放，修 P1-1）；失败路径不 acquire、不 release。**在飞任务数 ≤ `MAX_HEALTH_INFLIGHT × len(ROUTES)` = 25，专用执行器工作队列 ≤ 20**（可断言上界；`BoundedSemaphore` 超放会抛 `ValueError` ⇒ 由类型再次兜底）。
5. **feed 双检不可省**：并发 N 请求在 miss 窗口只产生 1 次回源（可用回源计数白盒断言）。
6. **单请求上界（AC-E2 ≤15s）**：REST 批量 ≤15s（stock_api 预算）；`/cls/hotplate`、`/cls/plate` 的 3 段经 `_fetch_concurrent` **≤3 并发** ⇒ 耗时 ≤ `max(单次取数)` ≤ `REQUEST_TIMEOUT=10s`；`/ths/longhu` 的 2 URL **并发** ⇒ ≤10s（修 P1-2，`§10#10` 的 AC 归属已更正为 **E2**）；★ v1.2：整轮扇出受 **`_FANOUT_WAIT_BUDGET=REQUEST_TIMEOUT`** 界定（共享池被占时单请求也不会拖到 ~190s，超期项 `cancel()` + `FetchError('upstream_timeout')`）；面板 CDP ≤8s/次（cdp_engine）。

### 6.3 异常兜底范围声明

| 端点 | 是否受 `_guard` 保护 | 说明 |
|------|--------------------|------|
| 14 个 JSON 分支 | ✅ | `batch`/`object`/`text` 三 shape |
| 5 个 RSS | ✅ | `rss` shape |
| `/healthz` | ✅（额外加固） | `object` shape（SAD 未强制，但 healthz 自身必须总函数） |
| `/`、`/opml.xml` | ❌（**不纳入**） | 纯内存字符串拼接（无 IO、无外部数据），AC-S1 的注入故障（上游超时/非法响应/CDP 无数据）不可达；登记见 §10#4 |

---

## 7. 并发安全

### 7.1 锁清单

| 锁 | 保护对象 | 新增/既有 | 临界区内容 |
|----|---------|----------|-----------|
| `_inflight_lock` | `BoundedThreadPoolServer._inflight` | 既有 | 整数读改写（无 IO） |
| `_feed_fetch_locks_lock`（cache.py） | `_feed_fetch_locks` 建锁表 | 既有 | dict setdefault |
| `_feed_fetch_locks[path]`（per-path） | 同一 feed 路径的回源串行 | 既有 | **仅** `feed_cache_get`（内部自锁）+ `fetch_func()` + `feed_cache_put`；网络 IO **在锁内**（这是防击穿的必要代价，per-path 粒度 ⇒ 不同 feed 互不阻塞） |
| `_health_executor_lock` | 执行器懒创建 | **新增** | 双检创建（无 IO） |
| `_health_inflight_lock` | `_health_inflight` | **新增** | 整数读改写 + `metrics.set_gauge`（metrics 为叶子锁，见 §7.3） |
| `_health_last_lock` | `_health_last_snapshot` | **新增** | json 深拷贝（内存） |
| `_health_sem`（`BoundedSemaphore`） | healthz 在飞窗位 | **新增** | 非阻塞 acquire；release 仅经 `_release_health_slot()`（由 `_HealthBatch` 归零触发） |
| `_HealthBatch._lock` | 该批 `_remaining`/`_done` | **新增** | 纯整数/布尔读改写（无 IO、不嵌套） |
| `_fanout_lock` | `_fanout_executor` 懒创建 | **新增** | 双检创建（无 IO）；**不跨模块调用** |
| `metrics._lock` | 计数/仪表 | 既有（叶子） | 见 `metrics.md` §7 |
| `cache._cache_lock` / `_neg_lock` / `_feed_cache_lock` | 缓存内部 | 既有 | 见 `cache.md` §7.1 |

### 7.2 锁序纪律（硬约束）

1. **`_feed_fetch_locks_lock` → per-path lock**：建锁表后**立即释放**才进 per-path 锁；**禁止**持有 per-path 锁时再取 `_feed_fetch_locks_lock`。
2. **per-path 锁内不持有任何 cache 内部锁**：`feed_cache_get`/`feed_cache_put` 各自在 `_feed_cache_lock` 内完成并**在返回前释放**（`cache.md` §7.2#4）。
3. **`_coordinator → 无`**：`_health_executor_lock` / `_health_last_lock` / `_health_inflight_lock` / `_fanout_lock` / `_HealthBatch._lock` 各锁**互不嵌套**，且**不在**持有时调用任何其它模块（`metrics` 例外：`metrics._lock` 是全局最内层，允许被持有 → 见 §7.3）。
   - `_HealthBatch.task_done` 的 `_release_health_slot()` 在**释放 `_HealthBatch._lock` 之后**调用（`with` 块外），⇒ 不出现 `_HealthBatch._lock → _health_inflight_lock` 嵌套。
4. **healthz 专用执行器与主池物理隔离**：healthz 的 5 个 worker **绝不**执行任何业务 handler（只执行 `_check_one_feed`），且其 RSS handler 走 `fetch_json`（自带 `_cache_lock`/`_neg_lock`，网络 IO 不持锁）。
5. **扇出执行器（`fanout`，≤3）与主池/healthz 池三方物理隔离**：`_fetch_concurrent` 只提交"单次 `fetch_json`"闭包，**不**在其中再做嵌套扇出（禁止 hotplate→plate 的递归并发）。
6. **不引入全局大锁**（项目约定）。
7. **`_guard` 无锁**：捕获异常与降级体构造均为纯内存操作（`build_batch_response` 为纯函数）。

### 7.3 metrics 锁的嵌套方向（唯一允许的跨界锁）

```
允许：_inflight_lock → metrics._lock            （_reject_503 在 finally 内计数）
允许：_health_inflight_lock → metrics._lock      （_set_health_inflight 计数）
允许：_feed_cache_lock → metrics._lock           （cache._cache_put 发布，cache.md §7.3）
禁止：metrics._lock → 任何其它锁（metrics 为叶子，metrics.md §7.2）
```

> `_set_health_inflight` 的 `metrics.set_gauge` **在释放 `_health_inflight_lock` 之后**调用亦无不可；伪代码为简化在锁内调用——两处均在 `metrics.md` 允许的"叶子锁永远最内层"范围内。**唯一硬约束：不得反向**。

### 7.4 热点路径开销（AC-E1/E4 相关）

- **本地缓存命中**：只多一次 `_cache_age()` 的 `cache_policy(domain)`（dict 查表，纳秒级）+ 一次 `cache_policy('feed')` 的**不调用**（feed 命中路径不读 policy：`_get_or_fetch_feed` 仅在 miss 后读 ttl——**实现要求（P2-1）**：`ttl = cache_policy('feed')['ttl']` 必须在**二次 `feed_cache_get` 仍 miss 之后**求值（§5.4 位置），避免命中路径白算 policy）。
- 批量端点：命中路径零 metrics、零网络；`_guard` 在成功路径只有一次 `try` 建立的成本（CPython 无异常时 near-zero）。
- healthz `check=0`：`metrics.snapshot()` 深拷贝 O(19) + `_policy_snapshot()` O(11) + `_base_feed_entries` O(15) ⇒ 毫秒级。

### 7.5 并发正确性依据（可白盒断言）

1. `_inflight` 与 `_release_inflight` 成对：`fut.add_done_callback` 在 future 结束（含异常）时回调 ⇒ 无泄漏（AC-E8/S5）。
2. `_health_sem` 为 `BoundedSemaphore`：多 release 会抛 `ValueError`；`_HealthBatch._done` 保证每个准入批次**恰好 release 一次**（测试可断言"无超放/无漏放"）。
3. healthz 并发 10 请求且上游慢：前 5 个进入检查、后 5 个走 stale（`stale:true` + `healthz_stale_total==5`）——AC-S8 的可测路径。**修 P1-1 追加**：前 5 批的任务未排空前 `_health_sem._value == 0`（准入位不归还），`_health_executor._work_queue.qsize() ≤ 20` 且**不随持续请求单调增长**；任务结束后准入位回升。
4. `_fetch_concurrent` 的 N 段并发 ⇒ 单端点耗时 ≈ `max(单段)` 而非 `sum`：注入 3 段各 `sleep(1s)` 断言总耗时 < 2s（而非 ≈3s），验证 AC-E2（BR-SRV-30）。
5. feed 并发 N：回源调用计数 == 1（双检 + per-path 锁）。
6. `_cache_age()` 纯函数（`cache_policy` 纯函数）⇒ 任意线程可调。

---

## 8. 测试要点（映射 PRD AC）

| 用例 | 步骤 / 断言（精确） | 覆盖 AC |
|------|-------------------|---------|
| **SRV-T1** `_JSON_SHAPES` 完整且 =14 | `assert len(_JSON_SHAPES) == 14`；`{p for p,s in _JSON_SHAPES.items() if s=='batch'} == set(_STOCK_BATCH_HANDLERS)`；`_SHAPES == {'batch','object','rss','text'}` | S1（防漏数复发） |
| **SRV-T2** guard 全覆盖矩阵 | 对 14 分支 + 5 RSS 逐个 patch handler 抛 `RuntimeError('boom')` ⇒ 断言：batch 分支返回 `{<每个请求码>: None, '_errors': {code:'upstream_error'}, …}`（含 `_truncated/_dropped_count` 若 dropped>0）；object/text 分支 `{'error':'boom'}`；RSS 分支为合法 XML（`ET.fromstring` 可解析）且含诊断 item；**进程存活、无异常冒泡** | **S1 / A5 / S4** |
| **SRV-T3** guard 不吞 KeyboardInterrupt | patch handler 抛 `KeyboardInterrupt` ⇒ 异常**穿透**（`assertRaises`） | S1（边界口径） |
| **SRV-T4** 批量保留键（dropped 注入） | 70 码请求（patch handler 记录 `dropped` 实参）⇒ handler 收到 `codes` 长度 50、`dropped==20`；响应含 `_truncated is True` ∧ `_dropped_count == 20`；**50 码时两键均不存在** | **A9** |
| **SRV-T5** 批量 handler 不被重复组装 | patch `build_batch_response`（计数）⇒ 仅由 handler 调用（server 直调计数 == 0）；`_guard` 仅在**异常**时调用 1 次 | A9 / 职责边界 |
| **SRV-T6** 缺参 400 | `/stock/data`（无 code）、`/stock/data?code=`、`/cls/plate`（无 code）⇒ 400 + `{'error':…}`；**不含逐码值域** | **A5** |
| **SRV-T7** 未知路径 404 | `/stock/xxx`、`/nope` ⇒ 404 文本 | **A5** |
| **SRV-T8** 过载 503 + 恢复 | 上游阻塞桩 + 注入 200 并发 ⇒ inflight ≤ `MAX_INFLIGHT`；超限响应 503 `{"error":"server busy"}`；`snapshot()['http_503_total'] == 503 次数`；撤载 5s 内全部 200；`_inflight` 回到 0 | **E8 / S5 / S10** |
| **SRV-T9** `MAX_INFLIGHT` 显式 | `config.MAX_INFLIGHT == config.MAX_WORKERS*2`（无 env 时）；patch `MAX_WORKERS` env 重启后联动；`server._max_inflight` 读该值（非 `max_workers*2`） | E8 |
| **SRV-T10** feed 双检（防击穿） | 冷路径 + N=8 并发同 path：patch `fetch_func` 计数 ⇒ **1 次**；`feed_cache_put` 1 次；8 个返回值相同 | **A8** / R3 |
| **SRV-T11** feed TTL 接 policy | patch `cache_policy('feed')` 返回 `ttl=30` ⇒ `feed_cache_put` 收到 `ttl==30`；`healthz['cache_ttl']==30`；`_cache_age()` 对 RSS 路径 == `cache_policy('news_url')['ttl']` | **A8 / A3** |
| **SRV-T12** feed 回源失败不写缓存 | `fetch_func` 抛异常 ⇒ `_serve_feed` 返回 error RSS（200）、`feed_cache_get(path)` 仍 `None`；下次请求再次回源 | S1 / A8 |
| **SRV-T13** plate stagger 三档 + 并发 | 盘中（注入 `_is_trading_hours→True`）patch `fetch_json` 捕获 ttl ⇒ hotplate `[12,15,18]`；plate `[12,15,18]`（info/stocks/industry）；非盘中 `[120,150,180]`；`_STAGGER == max(3, base//4)`；**三档互不相等**；且 hotplate/plate 各只调 `_fetch_concurrent` **1 次**、`len(specs)==3`（≤3 并发） | **A3 / E6 / E2** / D-7 |
| **SRV-T14** plate 分区 error 客体 + 顶层 error | 单分区失败 ⇒ 仅该 `plate_<type>` 为 `{'error':…}`，其余正常、**无顶层 `error`**；三分区**全**失败 ⇒ 三块均为 error 客体 **且顶层含 `error`**（值 = 三块摘要，SAD §2.3 D-4 / BR-SRV-31） | **A5** / S4 |
| **SRV-T15** longhu GBK + 走统一入口 | patch `fetch_json` 捕获 `(url, ttl, encoding)` ⇒ 2 个 URL、`ttl==cache_policy('longhu')['ttl']==300`、`encoding=='gbk'`；连续 10 次请求回源 2 次（每 URL 1 次）；**全仓无 `urlopen` in `handle_ths_longhu`** | **E9 / R15** |
| **SRV-T16** `_cache_age` policy 映射 | 逐 path 断言 max-age == `cache_policy(domain)['ttl']`；`/stock/announcement` == L3（30/180）、`/market/margin` == 600、面板 == 300（`_DEFAULT_AGE_DOMAIN`） | A3 / E6 |
| **SRV-T17** 无裸 TTL 字面量 | 扫 `server.py`：`ttl=` 实参来源均为 `cache_policy(...)`；无 `300`/`600`/`120`/`8` 作为 TTL | R16 / CFG-T10 |
| **SRV-T18** healthz `check=0` 零上游 | patch 5 个 RSS handler + `urlopen` 计数 ⇒ 均 0 调用；payload 含 4 既有键 + `metrics`/`policy`/`cdp`；`stale` 键不存在；毫秒级 | **S8 / S10** |
| **SRV-T19** healthz 精确 schema | 断言键集合 == `{status,cache_ttl,request_timeout,feeds,metrics,policy,cdp}`（无 stale）；`feeds[]` 每条含 `name/path/url/status`；`policy` 键集合 == `set(DOMAIN_MATRIX)`；`cdp` 键 == `{state,window_start,window_end}` | S10 / P2-N1 |
| **SRV-T20** healthz 有界准入（stale 可达） | 5 个并发慢 check（每源 sleep 2s，patch handler）占满信号量 ⇒ 第 6 个请求立即返回（<50ms）含 `stale is True`；`snapshot()['healthz_stale_total'] ≥ 1`；`healthz_inflight ≤ 5`；**且在首批任务的 future 未全部完成前 `_health_sem._value == 0`（准入位不归还，修 P1-1）**；前 5 批完成后信号量归位（后续请求不再 stale） | **S8 / S10**（P1-1 可测性） |
| **SRV-T21** healthz 两级预算（单源独立 + 整体闸） | ①**单源独立 3s**：单源慢 5s、其余快 ⇒ 慢源 `status=='timeout'`、请求总耗时 ≤ ~3.2s；②**整体 10s 闸非死代码**：patch `_HEALTH_TOTAL_BUDGET=1.0` 且 5 源全慢 5s ⇒ 请求总耗时 ≤ ~1.1s（**不是** 3.2s），全部源 `timeout`（修 P2-2） | **S8 / S7** |
| **SRV-T22** healthz 不污染业务池 + 队列有界 | 10 并发 `?check=1`（上游慢 5s）+ 同时业务请求 ⇒ 业务 P95 劣化 ≤50%；`server.executor` 无 healthz 任务；**`_health_executor._work_queue.qsize() ≤ 20`**（= 5 批 × 5 源 − 5 worker） | **S8** |
| **SRV-T23** healthz 准入失败不刷快照 | 先成功一次（快照 A）→ 再并发占满 → stale 返回 A；期间 `_health_last_snapshot` 仍为 A（未被 stale 体覆盖） | S8 / §10#5 |
| **SRV-T24** healthz 总函数 | patch `build_health_payload` 抛异常 ⇒ `/healthz` 返回 **503** `{'error':…}`（★ v1.3 更正：v1.2 起不再假 200；非 500/断连），且**不写回快照**；与 `SRV-T37` 同源 | S1 |
| **SRV-T25** feeds[].status 修正 | `_base_feed_entries`：`/stock/data`→`configured`、`/stock/basic_info`→`configured`、`/stock/f10`→`requires_chrome_cdp`；`/finance/market` 保持 `requires_chrome_cdp`；`/market/margin` `configured`；条目数 == 15 | S4（标注修正）/ Q2 |
| **SRV-T26** 首页 CDP 列 | `_serve_index` HTML 中 `/stock/data` 与 `/stock/basic_info` 行不含 `CDP` 标签；`/stock/f10` 行含 `CDP` 标签 | S4 / Q2 |
| **SRV-T27** watchdog 委派 | patch `watchdog_restart_skip_reason` 返回 `'trading_hours'` ⇒ `full_chrome_restart` **未被调用**且日志含原因；返回 `None` ⇒ 调用 1 次；`full_chrome_restart` 抛异常 ⇒ 线程存活（`except` 兜底） | **S4 / S9 / R19** |
| **SRV-T28** 面板 A 类降级 + timeline 旁支 | `page_data→None` ⇒ `{'error':…}`（4 端点）；`page_data→{'basic_info':{...}}`（无 timeline）⇒ `/finance/timeline`、`/market/timeline` 返回 `{'error':'timeline unavailable'}`（**非** `None`，**非**裸 `null`） | **S4 / S1 / R18** |
| **SRV-T29** f10 A′ 形状 | `config.cdp_engine = None` ⇒ `/stock/f10?code=sh600519` 返回 `{'sh600519': None, '_errors': {'sh600519':'cdp_unavailable'}}`（**非** error 客体） | **S4 A′** |
| **SRV-T30** RSS 不丢不重 | 上游 50 条 ⇒ feed 含 50 item、guid 无重复；间隔 2×TTL 后再次请求仍含全部条目（TTL 用 `cache_policy('feed')['ttl']`） | **A8** |
| **SRV-T31** 存量用例回归 | `test_server.py`：`test_handle_cls_hotplate_returns_three_plate_keys` / `..._includes_hot_plates` / `test_handle_cls_plate_returns_info_stocks_industry` / `test_healthz_payload_includes_hotplate_endpoint` / `test_healthz_includes_market_endpoints` / `test_transform_margin_*` / `test_handle_margin_error_returns_degraded` / `test_generate_opml_*` 全绿 | PRD §9（存量基线） |
| **SRV-T32** import 断链检查 | 全仓 grep `CACHE_TTL` / `MAX_FEED_CACHE_SIZE` / `feed_cache`（在 server.py 内）/ `CACHE_JITTER`（server.py）⇒ **0 命中**；`python -m py_compile china_finance_rss/server.py` 通过 | config.md §2.4 同 change-set |
| **SRV-T33** HEAD 不写体 | `do_HEAD` `/stock/data?code=…` 400 路径 ⇒ 响应无 body（`Content-Length: 0` 或空）；`_send_error(write_body=False)` 被调用 | S1 |
| **SRV-T34** healthz 准入位覆盖在飞任务（执行器队列有界） | patch `_check_one_feed` 为 `sleep(5s)`；**持续 20s 高频**发起 `?check=1`（每 0.1s 一次）⇒ ①任一时刻 `healthz_inflight ≤ MAX_HEALTH_INFLIGHT`；②`_health_executor._work_queue.qsize() ≤ MAX_HEALTH_INFLIGHT × len(ROUTES) − MAX_HEALTH_INFLIGHT == 20` 且**不单调增长**（对比 v1.0 会让队列无界累积）；③每个准入批次**恰好** `release` 一次（`_health_sem._value` 最终回到 `MAX_HEALTH_INFLIGHT`，无 `ValueError`、无泄漏） | **S8 / S7**（修 P1-1 的核心断言） |
| **SRV-T35** AC-E2 单请求上界（并发扇出） | ①hotplate：patch 3 个分区 `fetch_json` 各 `sleep(1s)` ⇒ `/cls/hotplate` 总耗时 < 2s（≈`max`，非 ≈3s）；②plate 同断言；③longhu：patch 2 个 URL 各 `sleep(1s)` ⇒ 总耗时 < 2s（≈`max`，非 ≈2s+）；④`_fetch_concurrent` 返回项中 `Exception` 不抛出（转成 `{'error':…}` / 分区 error 客体）；★ v1.2：⑤patch `_FANOUT_WAIT_BUDGET=0.2` 且各段 `sleep(1s)` ⇒ 总耗时 < 0.5s 且每项为 `FetchError('upstream_timeout')` | **E2**（主，修 P1-2） |
| **SRV-T36** 业务端点降级恒 200（★ v1.3 / N1 反转） | patch `handle_finance_market` 返回 `{'error':'x'}` ⇒ `/finance/market` **200**（体原样 `{'error':'x'}`）且 `http_503_total` **不增**；`{'plate_industry':{'error':'x'},'error':'x'}`（hotplate 全失败）⇒ 200；`handle_margin` 返回 `{'_error': …}` ⇒ 200；guard 抛异常（object/text 分支）⇒ 200 `{'error': str(exc)}`；**并断言响应含 `Cache-Control: public, max-age=<域 TTL>`（降级体可缓存）** | **A5 / N1**（回退 S2-5） |
| **SRV-T37** healthz guard 失败 ⇒ 503（v1.2） | patch `build_health_payload` 抛异常 ⇒ `/healthz` **503**（体 `{'error':…}`），`http_503_total++`；`status=='degraded'` ⇒ 503；`status=='ok'` ⇒ 200 | **S1 / S8** |
| **SRV-T38** `/market/margin` 参数门（v1.2） | `?market=abc` ⇒ **400** `Invalid ?market= parameter. Allowed: 99,1,2,3`，且 patch `handle_margin` **未被调用**、无缓存键；`?market=99`/缺省 ⇒ 200 | **A5** |
| **SRV-T39** 批量码归一 + 键回写（v1.2） | `?code=600519.SH,SH600519,sh600519` ⇒ handler 收到 `['sh600519']`（**1** 个码，`dropped==0`）；响应键 == `'600519.SH'`（首个原拼写）；`?code=sh600519,sz000001` ⇒ 响应键 == 原拼写且体与旧实现**逐字节一致** | **A9 / A6 / P1-6** |
| **SRV-T40** 非法码值 ⇒ 逐码 null（v1.2） | `?code=sh600519,NOTACODE` ⇒ **200**；`NOTACODE` 键为 `null`（或 `_errors` 命中）；**非** 400；`?code=`/无 `code` ⇒ 400 | **A5** |
| **SRV-T41** longhu 席位配对（v1.2） | 构造 N 个股票行 + 其中一张表解析出 0 条 entries ⇒ 断言 `broker_idx` 仍按 2×股票数推进、后续股票席位**不偏移**；`broker_idx != 2×len(stocks)` ⇒ `log.warning` 命中 | P0 回归 |
| **SRV-T42** `_base_url` 加固（v1.2） | 无 `PUBLIC_BASE_URL` 时：`Host: evil/@x` ⇒ 返回 `http://localhost:8053`；合法 `Host: example.com` ⇒ `http://example.com`；`X-Forwarded-Host` 优先；响应含 `Cache-Control: private` + `Vary: Host, …` | S2-3 |
| **SRV-T43** `_cache_age` 面板域（v1.2） | 4 面板路径的 `max-age == cache_policy('quote')['ttl']`（8/120），**非** 300；`_cache_age` 用 `urlparse`：absolute-form 请求行解析出正确 path | S2-3 / A3 |

## 9. AC 追溯矩阵

| 本模块设计点（§） | 覆盖 AC |
|------------------|---------|
| `_guard(shape)` 覆盖 14 JSON + 5 RSS + `/healthz`（§2.3 / §5.1 / §5.2） | **S1**（主承载）/ **A5** / R1 |
| shape 由 `_JSON_SHAPES` 派生 + `assert len==14`（§2.2） | **S1**（防漏数复发）/ A5 |
| `_handle_stock_batch` 计算并透传 `dropped`（§2.4 / §5.3） | **A9** / R4 |
| feed 双检 + per-path 锁 + TTL 接 `cache_policy('feed')`（§2.5 / §5.4） | **A8** / **A3**（承诺=行为）/ R3 |
| `_cache_age()` / healthz `cache_ttl` 接 policy（§5.8 / §5.6） | **A3 / A8** / R16 |
| plate 三档 stagger 派生（§4.3 / §5.5） | **A3 / E6** / D-7 |
| `/ths/longhu` 走 `fetch_json(encoding='gbk')` + L4（§4.2 / §5.5） | **E9** / R15 |
| **`_fetch_concurrent` ≤3 并发展开**（hotplate/plate/longhu）（§4.6 BR-SRV-30 / §5.5） | **E2**（主承载）/ **S7** / E8（资源口径）/ R13 |
| `/cls/hotplate` 分区 error 客体 + **全失败补顶层 `error`**（§4.6 BR-SRV-31 / §5.5） | **A5**（主）/ S4 |
| healthz 零上游快路径 + 专用执行器 + **有界准入**（§2.6 / §5.6） | **S8**（主承载）/ **S10** / R2 |
| healthz 精确 schema（既有 4 键 + 4 新键）（§3.1） | **S10** / P2-N1 |
| `MAX_INFLIGHT` 显式 + 立即 503 + `http_503_total`（§2.7 / §5.7） | **E8 / S5** / **S10** |
| CDP A 类 `page_data` 防御 + timeline 禁止裸 null（§4.6 / BR-SRV-27） | **S4** / S1 / R18 |
| CDP A′ `/stock/f10` 逐码 `cdp_unavailable`（由 stock_api 承载，本模块只传 `dropped`） | **S4 A′** |
| watchdog 委派 `watchdog_restart_skip_reason()`（§5.7） | **S4 / S9 / S10** / R19 |
| `feeds[].status` + 首页 CDP 列修正（§2.9.1） | **S4** / Q2（契约同步待编排层） |
| 错误语义矩阵（400/404/503/200-error/200-值域）（§2.1 / §6.1） | **A5** |
| 单请求上界（REST ≤15s / **hotplate·plate·longhu ≤10s（并发）** / CDP ≤8s）（§6.2） | **E2**（主承载，`§10#10` 归属已更正）/ S7 |
| 无全局锁 / 锁序纪律（§7） | **S2**（不劣化，与 stream 共享）/ S9 |
| 静态端点不纳入 guard 的显式声明（§6.3） | S1（范围声明） |
| 业务端点降级 = **200 + error 体**（BR-SRV-5b / §5.5 `_send_json_shape`；★ v1.3 N1 回退） | **A5**（主）/ S1（降级体仍结构化） |
| healthz guard 失败 / 缺 status / degraded ⇒ 503（§5.2） | **S1 / S8**（**healthz 自身语义**，非业务端点先例） |
| 批量码归一 + 响应键回写（§2.4 / `_parse_stock_codes` / `_rekey_batch_response`） | **A6 / A9 / P1-6** |
| `/market/margin` 参数门 400（BR-SRV-5c） | A5 |
| `_base_url` Host 校验 + `private`/`Vary`（BR-SRV-33） | **S2-3** |
| 面板 cache-age 域 = quote（BR-SRV-8b） | S2-3 / A3 |
| longhu 席位配对无条件自增（BR-SRV-32） | 数据正确性（P0） |
| `request_queue_size = LISTEN_BACKLOG`（§2.7） | E1（突发连接） |

> **AC 覆盖核对**：本模块承载 **S1/A5/A8/A9/E2/E8/E9/S4/S5/S7/S8/S10** 共 12 条（v1.1 新增 **E2**：server 自有的 hotplate/plate/longhu 单请求上界）；`E1/E3/E4` 由基础层/数据层承载（本模块仅提供 `_cache_age` 与序列化路径）；`E6` 由 config/stock_api 承载（本模块提供 plate 侧派生）；`A3` 由 stock_api 承载（本模块提供 feed 侧同源）。

---

## 10. 与 SAD / 现有代码的偏差与歧义标注（不擅自改 SAD）

| # | 项 | SAD / 契约表述 | 本文裁决 | 理由 |
|---|----|---------------|---------|------|
| 1 | **longhu 上游 URL/headers 的归属** | `config.md` v1.1 §2.4「保留（不动）」表登记了 `_*_BASE_URL`/`_*_HEADERS`，但**未含** longhu 两 URL；现状为 `server.py` 内联 `Request(...)` 字面量 | 提取为 **`server.py` 模块级常量** `_LHBTABLE_URL`/`_LHBTABLE_HEADERS`/`_LONGHU_PAGE_URL`/`_LONGHU_PAGE_HEADERS`，**不上收 config** | `config.md` 已评审冻结，新增 config 常量须与 `config.md` 同 change-set（会造成跨文档返工）；本模块内常量可满足"消除 `urlopen` 直连"的 R15 目标。**建议编排层后续把该域常量上收 config 并同批改 `config.md`** |
| 2 | `_cache_age()` 未登记路径的兜底 | SAD §3 server 行只说"`_cache_age()` 改读 policy" | 未登记路径（4 面板 / `/healthz` / `/` / `/opml.xml`）→ `_DEFAULT_AGE_DOMAIN='f10'`（L4、factor 1.0 ⇒ **恒 300**，与现状逐字等价） | `DOMAIN_MATRIX` 无"面板/CDP"域，且新增域须改 `config.md`；用 L4 域承载可保证 **0 行为变更**且无裸 TTL 字面量。**登记：该域选择不表达业务语义，仅为口径连续** |
| 3 | `_send_error` 增 `write_body` 形参 | SAD 未提 | `_send_error(self, msg, write_body=True)`，调用点透传 | 现状 `_send_error` 硬编码 `write_body=True`，**HEAD 请求的 400 会写体**（HTTP 语义瑕疵）；属 R1"边界"范围内的最小修正。非契约变更（内部方法） |
| 4 | `_guard` 覆盖范围 | SAD §2.4：`_guard` 覆盖**全部 14 个 JSON 分支** + `rss` + `text` | **扩展为 14 JSON + 5 RSS + `/healthz`**；`/`、`/opml.xml` **显式排除** | ① healthz 自身必须总函数（AC-S1 的"全端点"口径）；② `/`、`/opml.xml` 为纯内存拼接、无外部数据，AC-S1 的注入故障不可达。属**超集**而非偏离 |
| 5 | 准入失败且**从无快照**时的响应 | SAD §2.6：`return 上次快照 + {"stale": true}`（隐含必有快照） | 若 `_health_last_snapshot is None` → 返回**本次零上游体 + `status='degraded'`** + `stale:true`（HTTP 503） | 进程启动后首个 `?check=1` 即被并发占满时，"上次快照"不存在；返回可解析体优于 `None`/500。**登记：SAD 未定义该边界** |
| 6 | `feeds[]` 的端点覆盖 | SAD §7.1 Q2 只列 3 处 `status` 修正 | 保持现状 15 条（**不新增** `/finance/timeline`、`/market/timeline`、`/ths/longhu`、`/stock/announcement`） | 现状 healthz `feeds[]` 未含这 4 个端点（既有 gap，非本次引入）；新增条目属"只增"但会扩大 `feeds[]` 契约面，**建议编排层单独决策**。**登记为已知缺口**（AC-S4 的端点验证不依赖 healthz 列表） |
| 7 | `feeds[].status` 取值修正（3 处） | SAD §2.6 Q2：属**改既有字段取值**（≠"只增不改"），须编排层批准 | 本文按目标值落地 + 登记；**同步范围 = healthz 负载 + 首页 CDP 列 + API.md** | AC-S4 归类的直接前提（`/stock/data`→B、`/stock/basic_info`→B、`/stock/f10`→A′）；SAD 只输出目标值，契约修改权在编排层 |
| 8 | healthz 执行器的线程名/预算常量 | SAD 只给 `max_workers=5`、整体 10s、单源 3s | 落 `thread_name_prefix='healthz'` + `_HEALTH_TOTAL_BUDGET=10.0`/`_HEALTH_SOURCE_BUDGET=3.0`/`_HEALTH_POLL=0.25` | 实现细化；AC-S9 的线程总账 +5 与 `MAX_HEALTH_INFLIGHT` 一致 |
| 9 | `_run_health_checks` 的 `pending` 判定方式 | SAD 只说 `as_completed(timeout=10)` | 改用 `wait(..., FIRST_COMPLETED)` 轮询（`_HEALTH_POLL=0.25`）以**能实现"单源 3s"**（`as_completed` 只在 future 完成时 yield，无法对未完成源判超时）；**并按各 future 的 `submitted_at` 实现"每源独立 3s"、整体 10s 独立闸**（修 P2-2） | 行为对齐 SAD 的两级预算；时间复杂度 5 源 × 40 轮，可忽略 |
| 10 | `/ths/longhu`、`/cls/hotplate`、`/cls/plate` 的单请求上界 | **AC-E2**（任何单请求 ≤15s）+ **SAD §4.1**（hotplate 3 次串行 → ≤3 并发，"本次顺带修"） | **改并发**：三者的多上游请求统一经 `_fetch_concurrent`（`max_workers=3`）展开 ⇒ 单端点 ≤ `REQUEST_TIMEOUT=10s`（≤15s ✅）。**登记项归属更正为 AC-E2**（v1.0 误记为 AC-S7 的边界） | 现状串行：hotplate ≈30s、plate ≈30s、longhu ≈20s，均**越 AC-E2 的 15s**；P95 由 `sum` 变 `max`（SAD §4.1 明令） |
| 11 | `MAX_INFLIGHT` 对**流端口**实例的语义 | SAD §4.3「流端口 worker = `MAX_STREAM_CONNS+10=110`」+ SAD §4.2 C-3（100 连接） | **采纳评审建议 + 编排层已批准**：`BoundedThreadPoolServer.__init__` 增 `max_inflight=None` 形参；主端口默认 `MAX_INFLIGHT(40)`，`stream.make_stream_server` **显式传 `MAX_STREAM_CONNS+10=110`** ⇒ 流端口 `_max_inflight=110`（**≥** 100 连接上限） | v1.0 的"主/流端口共用 40"把 SSE 连接上限从 100 压到 ≈40 ⇒ `MAX_STREAM_CONNS=100` 与 `_register_conn` 的 100 阈值沦为死代码、**AC-E5/E7 不可复现**。参数化后恢复现状语义（原 `max_workers*2=220` 亦 ≥110）；**行为变更已登记**（本行 + `stream.md` §10#13） |
| 12 | `healthz_inflight` gauge 的写入点 | `metrics.md` §3.2 owner = `server.build_health_payload` | 由 `_set_health_inflight` 统一写入（`build_health_payload` 的唯一子路径） | owner 不变，落点细化 |
| 13 | `_health_last_snapshot` 是否含 `check=1` 的真实结果 | SAD 未定义 | **含**：每次成功组装（`check=0` 或 `check=1`）都刷新 | `stale` 回退给"最近一次真实快照"信息量最大；`check=0` 体也刷新（否则长期无 `check=1` 时 stale 永远无快照） |
| 14 | `build_health_payload` 的 `policy` 字段含 `encoding` | SAD §2.6 schema 示例只列 5 键 | `cache_policy('longhu')` 会**额外带 `encoding:'gbk'`**（`config.md` BR-CFG-7 规定） | 与 `config.md` 契约一致；`policy` 字段本就是 policy 原样透出。**不改 schema 断言**（断言应为"⊇ 5 键 ∪ longhu 的 encoding"） |
| 15 | **外部上游扇出执行器**（新增） | SAD §4.1 只要求 hotplate ≤3 并发；未指定执行器归属 | 新增模块级**共享** `_fanout_executor`（`max_workers=_FANOUT_MAX_WORKERS=3`，懒创建、双检），供 hotplate/plate/longhu 复用；**不新增 config 常量**（`3` 为机制常量，同 `_HEALTH_POLL`） | 每请求新建 `ThreadPoolExecutor` 会引入不可控线程抖动；共享池使**全局**在这些端点上的在飞取数 ≤3（同时满足 AC-E8 资源口径）。线程账 +3（懒创建，AC-S9 上界见 §2.9） |
| 16 | **healthz 准入位语义**（修 P1-1，新增） | SAD §2.6：*并发 check 任务在飞数被信号量钉死，执行器内部队列**从不堆积**（提交前已准入）* | 引入 `_HealthBatch`：准入位由**该批全部 future 的完成回调**释放（非 `_run_health_checks` 返回时立即释放）⇒ 在飞任务 ≤25、工作队列 ≤20，SAD 断言**成立** | v1.0 的"3s `break` 后 `finally release`"只约束轮询窗口、不约束在飞任务 ⇒ 持续慢 check 下无界队列累积（重演 SAD P1-3 的放大器）。响应时点不变（仍 ~3s 返回），仅**释放时点**后移 |
| 17 | **handler 返回"组装 dict"（非 `(results, errors)`）** | SAD 对 `handle_cls_*` 的措辞将回改 | 保持现状口径：`handle_cls_*(codes, deadline=None, dropped=0) -> dict`（内部调 `build_batch_response`）；**编排层已批准**，SAD 措辞由 system-architect 回改 | `_PROGRESS.md` §B 锁定契约；server 只注入 `dropped`，组装点唯一 |
| 18 | **error-only payload ⇒ 503**（v1.2；★ **v1.3 已回退**） | SAD §2.1 AC-A5 五类状态语义只定义"上游失败 → 200 + error 客体" | **回退**：业务端点降级体**恒 200**（BR-SRV-5b）；`_json_payload_has_data` 与 `_send_json_shape` 的 503 分支**已删**；`http_503_total` 计数点回到 3 个 | v1.2 曾把"CDP/上游整体不可用"改判 503 以让监控可区分——但那**改动了既有对外状态码契约**，与 AC-A5「上游失败 → 200 + error 客体」冲突，且既有消费方按 200 解析。编排层裁决 **N1：回退**。真正的可用性观测由 `/healthz`（503 语义 + `stale`/`metrics`/`cdp` 字段）承担 |
| 19 | **`/healthz` 503 判定扩为"缺 status / 含 error"**（v1.2） | SAD §2.6：`payload['status']=='degraded'` ⇒ 503 | guard 捕获异常的体 `{'error': …}`（**无** `status`）也判 503，并计 `http_503_total` | v1.1 会把"健康检查自身抛异常"报成 200 ⇒ 假健康（S2-5） |
| 20 | **`/market/margin` 非法 market ⇒ 400**（v1.2） | SAD §2.1 只给 enum，未定义非法值行为 | guard 之前校验 `market ∈ VALID_MARKETS` ⇒ 400（`Invalid ?market= parameter. Allowed: 99,1,2,3`） | 避免非法值进入 URL/缓存键；与 `/cls/plate` 缺参 400 同族 |
| 21 | **批量码归一 + 键回写**（v1.2） | SAD §2.4 未定义码拼写归一 | `_parse_stock_codes`（`config.canonical_code` 折叠去重，截断按归一后计数）+ `_rekey_batch_response`（响应键回请求原拼写，纯改名） | 同一股票不得因拼写不同而铸出多个池/缓存/账本键（P1-6）；响应键契约不变（回原拼写） |
| 22 | **面板 cache-age 域改 `quote`**（v1.2） | SAD §3 server 行只说"`_cache_age()` 改读 policy"；v1.1 用 `_DEFAULT_AGE_DOMAIN='f10'`（恒 300）覆盖面板 | 4 面板注册到 `_CACHE_AGE_DOMAINS` 的 `quote` 域 ⇒ max-age **8/120**；未登记路径现仅 `/healthz`、`/`、`/opml.xml` | 面板是实时行情面，v1.1 的 300s 会把实时报价标成"可缓存 5 分钟"（与 AC-A3「承诺=行为」冲突） |
| 23 | **`_send_text` 增 `varies_on_host`**（v1.2） | SAD 未涉及 Host 头可信性 | `_send_text(..., varies_on_host=False)`；`PUBLIC_BASE_URL` 未设时 feed/opml/（派生 base URL 的响应）标 `private` + `Vary: Host, X-Forwarded-Host, X-Forwarded-Proto`；`_base_url()` 做格式校验（非法 ⇒ localhost） | Host 可被伪造且会嵌入 feed 体 ⇒ 防共享缓存投毒（S2-3） |
| 24 | **`_send_json_shape`**（v1.2；★ v1.3 简化） | SAD §2.4 只要求"shape 由路由表派生" | object JSON 分支统一走 `_send_json_shape(path, fn)`：shape 读 `_JSON_SHAPES[path]`（不再写死字面量）；**恒 `_send_json(payload, cache=cache)` ⇒ 200** | ① 消除"分支写死 shape 字面量"的漂移面；② v1.3 起"503 判定唯一入口"不复存在（回归单一口径：业务端点恒 200） |
| 25 | **`request_queue_size = LISTEN_BACKLOG`**（v1.2） | SAD §4.3 未定义 backlog | 类属性 `request_queue_size = LISTEN_BACKLOG`（config，默认 128） | socketserver 默认 backlog=5，突发连接下 accept 队列溢出 ⇒ 客户端 SYN 重传 ~1s（BUG-P6C-03，AC-E1 尾部尖峰） |
| 26 | **`_FANOUT_WAIT_BUDGET` 界定扇出等待**（v1.2） | SAD §4.1 只要求 ≤3 并发 | `_fetch_concurrent` 用 `wait(futs, timeout=REQUEST_TIMEOUT)`；超期 `cancel()` + `FetchError('upstream_timeout')` | 共享池被占时旧的无界 `fut.result()` 可让单请求拖到 ~190s（远超 AC-E2 的 15s） |
| 27 | **`handle_ths_longhu` 席位配对无条件自增**（v1.2） | SAD 未定义解析细节 | 标签匹配即 `broker_idx += 1`（即便该表 0 条 entries）；`stock_idx >= len(stocks)` 丢弃 + 告警；末尾错位告警 | 旧实现跳过自增会**静默错配**后续所有股票的买卖席位（HTTP 200 无错误信号）——数据正确性 P0 |
| 28 | **import 面更正**（v1.2） | v1.1 §2.10 块含已不在使用面的名字 | 增 `page_data` / `FetchError` / `LISTEN_BACKLOG` / `VALID_MARKETS`；删 `handle_cls_stock` / `fetch_cls_fundflow` / `fetch_cls_timeline` / `strip_html` / `escape_xml`；`MAX_HEALTH_INFLIGHT` 改用 `config.` 前缀 | 文档与实现逐行对齐（编码者可直接整体替换） |
| 29 | **N1 回退：业务端点降级恢复 `200 + error 体`**（v1.3） | AC-A5 只定义"上游失败 → 200 + error 客体"；v1.2 的 error-only ⇒ 503 属**超集变更** | `_send_json_shape` 恒 `_send_json(payload)`（**200**）；**`_json_payload_has_data` 删除**；**`_send_json` 去掉 `status` 形参**；**`http_503_total` 计数点 4→3**（`_reject_503` / `stream._serve_sse` / `/healthz`）；降级体 `cache=cache` ⇒ **按域 TTL 可缓存** | 编排层裁决 N1：v1.2 改判 503 动摇了既有对外状态码契约，既有消费方按 200 解析；`/healthz` 已能承担可用性观测，业务端点无需第二个 503 语义（且 `/healthz` 的 503 属端点自身语义，**不构成业务端点先例**） |

---

## 11. 交付自检

- [x] 无 `{例:` 占位符；`_JSON_SHAPES`/healthz schema/`_cache_age` 映射/plate TTL 均为**实值**
- [x] §3 为 `yaml` 代码块（healthz schema / health 状态 / 路由与 shape / 服务类状态）
- [x] 路由表精确：14 JSON（逐一列名 + shape）+ 5 RSS + `/` + `/opml.xml` + `/healthz`；无增删路径
- [x] `_guard` 四 shape 语义与降级体逐一钉死；异常兜底范围（含显式排除项）声明
- [x] 业务规则编号 BR-SRV-1..33，伪代码直接引用编号（BR-SRV-30/31 为 v1.1 新增；**v1.2 新增 5b/5c/8b/32/33**）
- [x] 关键流程伪代码齐备：分发 / `_guard` / 批量截断 / feed 双检 / **`_fetch_concurrent` 扇出** / plate stagger / longhu GBK / healthz 准入（`_HealthBatch`） / 过载 503 / watchdog
- [x] 错误处理矩阵（400/404/503/200-error/200-值域 + hotplate 全/部分分区）+ 降级分层 + 6 条可断言不变式
- [x] 并发安全：锁清单 + 锁序（`_feed_fetch_locks_lock → per-path`；metrics 永远最内层）+ 热点开销 + 并发正确性依据
- [x] 测试要点 **43 条**映射 PRD AC（v1.1 新增 T34/T35；**v1.2 新增 T36–T43**）；回归用例逐条列名（含 **2 条**跨模块交叉引用必改：见 §10.1）
- [x] AC 追溯：S1/A5/A8/A9/**E2**/E8/E9/S4/S5/S7/S8/S10 主承载，A3/E6/A6 协同项已注明；**v1.2 增 S2-5/S2-3/P1-6**
- [x] 与基础层/数据层接口逐项对齐（`cache_policy`/`feed_cache_get|put`/`build_batch_response`/`page_data`/`restart_window_snapshot`/`watchdog_restart_skip_reason`/`metrics`）
- [x] 偏差 **29 项**全部登记（**不改 SAD / 不改 PRD / 不改 config.md**）
- [x] **v1.3（N1 回退）**：业务端点降级 = `200 + error 体`（§1.1#9 / §2.1 yaml + 状态表 / §2.2 `_send_json_shape` / §2.9 `_json_payload_has_data` 删除 / §2.10 / §4.1 BR-SRV-5b / §5.2 注 + §5.8 伪代码 / §6.1 / §9 / §10#18·#24·#29 / §11.3）；`_send_json` 无 `status`；`http_503_total` 计数点 3；降级体可缓存
- [x] **v1.3（N1 回退）**：`/healthz` 的 503 明确为**端点自身语义**（BR-SRV-21 / §5.2 / §6.1 / §9 / §10#29），不构成业务端点先例

### 11.1 v1.2 契约同步对照（P7b · 以代码为准）

| # | 同步项 | 落点 | 与 v1.1 的差异 |
|---|--------|------|---------------|
| 1 | ~~error-only payload ⇒ 503~~（**★ v1.3 / N1 已回退**：业务端点降级恒 200；`_json_payload_has_data` 删除。见 §11.3 / §10#29） | §1.1#9 / §2.1 / §2.2 / §4.1 BR-SRV-5b / §5.2·5.8 / §6.1 / T36 | v1.1：一律 200 → v1.2 改 503 → **v1.3 回退为 200** |
| 2 | `/healthz` 缺 `status`/含 `error` ⇒ 503 + `http_503_total` | §1.1#7 / §2.1 / §3.1 / §5.2 / T37 | v1.1：仅 `degraded` ⇒ 503 |
| 3 | `_HealthBatch.settle()` + 先建账再调用 + `except BaseException` | §2.6 / §2.6.1 / §3.2 / §5.6 / §7.1 | v1.1：无 settle（异常路径泄漏准入位） |
| 4 | `_run_health_checks(base_url, batch=None)` + 等待中 `fut.result()` 不上抛 | §2.6.1 / §5.6 | v1.1：无 batch 形参 |
| 5 | `_FANOUT_WAIT_BUDGET=REQUEST_TIMEOUT` 界定扇出 | §1.1#7′ / §2.9 / §5.5 / §6.2#6 / T35 | v1.1：无界 `fut.result()` |
| 6 | `_base_url()` Host 校验 + `private`/`Vary`（`_send_text(varies_on_host=…)`） | §2.10（`_send_text`）/ §4.6 BR-SRV-33 / §5.8 / §5.8 表 / T42 | v1.1：直接取 Host；`public` 缓存 |
| 7 | `_cache_age()` 用 `urlparse(self.path).path` | §4.2 BR-SRV-8 / §5.8 / T43 | v1.1：`split('?')[0]` |
| 8 | 4 面板 cache-age 域 = `quote`（8/120） | §3.3 `_CACHE_AGE_DOMAINS` / §4.2 BR-SRV-8b / §5.8 表 / §10#22 | v1.1：`f10`（300） |
| 9 | 码归一 `_parse_stock_codes` + `_rekey_batch_response` | §1.1#10 / §2.4 / §5.3 / §6.1 / T39·T40 | v1.1：仅 strip/split，原样传 |
| 10 | `/market/margin` 非法 market ⇒ 400（`VALID_MARKETS`） | §2.1 / §4.1 BR-SRV-5c / §5.2 / T38 | v1.1：无校验 |
| 11 | `_PANEL_HANDLERS` + `_JSON_DISPATCHED_PATHS` 导入期断言 | §2.2 / §5.2 | v1.1：无 |
| 12 | ~~`_send_json(data, write_body, cache, status=200)`~~（**★ v1.3 / N1**：去 `status`，恒 200） | §2.10 / §5.8 | v1.1：无 `status` → v1.2 增 → **v1.3 撤销** |
| 13 | `do_GET`/`do_HEAD` 断连捕获扩为 `OSError` | §2.3 / §5 | v1.1：`BrokenPipe/ConnectionReset` |
| 14 | `BoundedThreadPoolServer.request_queue_size = LISTEN_BACKLOG` | §2.7 / §3.4 / §5.7 / §10#25 | v1.1：无 |
| 15 | longhu `broker_idx` 无条件自增 + 错位告警；encoding 取自 policy | §4.6 BR-SRV-32 / §5.5 / §10#27 / T41 | v1.1：解析细节未钉死、encoding 字面量 |
| 16 | import 面更正（+page_data/FetchError/LISTEN_BACKLOG/VALID_MARKETS；−handle_cls_stock/fetch_cls_*/strip_html/escape_xml） | §2.10 / §10#28 | v1.1：清单不完整 |

### 11.2 v1.1 修订对照（闭环 REV-DES-20260915-002）

| 评审项 | 落点 | 处理 |
|--------|------|------|
| **P1-1** healthz 准入位早释放 / 无界队列 | §2.6 / §2.6.1 / §3.2 / §4.5 BR-SRV-19·20 / §5.6 `_HealthBatch` / §6.2#4 / §7.1·7.2·7.5 / §8 T20·T21·T34 / §10#16 | 新增 `_HealthBatch`（future 完成回调驱动释放）⇒ 在飞任务 ≤25、执行器队列 ≤20；§2.6 断言与伪代码一致；补"持续慢 check 下队列不增长"断言 |
| **P1-2** 外部上游串行越 AC-E2 | §1.1 / §2.8·2.9 / §4.6 BR-SRV-30 / §5.5 `_fetch_concurrent` / §6.2#6 / §8 T13·T35 / §9 / §10#10·#15 | hotplate/plate/longhu 改 ≤3 并发（共享 `fanout` 池）；单端点 = `max` 而非 `sum` ⇒ ≤10s ≤15s；登记归属**更正为 AC-E2**；补 E2 落点与测试 |
| **P1-3** hotplate 全失败缺顶层 `error` | §2.8 / §4.6 BR-SRV-31 / §5.5 / §6.1 / §8 T14 / §9 | 三分区全失败 ⇒ **顶层补 `error`**（SAD §2.3 D-4 口径）；T14 断言同步 |
| **P1-4** 流端口 inflight 40 使 100 连接失效 | §1.5 / §2.7 / §3.4 / §5.7 / §10#11 | `__init__` 增 `max_inflight` 形参；流端口显式传 110（≥ `MAX_STREAM_CONNS`+10）⇒ AC-E5/E7 可复现 |
| **P2-1** §5.4 vs §7.4 ttl 求值点矛盾 | §2.5 / §5.4 / §7.4 | `ttl` 移到**二次 get 仍 miss 后**求值；唯一表述 |
| **P2-2** 10s 整体预算成死代码 | §2.6.1 / §3.2 / §4.5 BR-SRV-20 / §5.6 / §8 T21 | 每源按各自 `submitted_at` 独立 3s；整体 10s 独立闸（可测） |
| **P2-3** `feeds[].status` 注释过宽 | §3.1 | 限定为"仅 5 个 RSS 源被覆盖"；10 个 JSON/CDP 条目保持原值 |
| **P2-4** 分组视图 `object（8）` 计数错 | §2.2 | 改为 `object（7，表内）`+ 明示 `/healthz` **不入表**（否则 `assert len==14` 失败） |
| **P2-5** import 清单不完整 | §2.10 | 改为**完整 import 块**（可整体替换）：补删 `Request,urlopen` / `random`；补 `main()` 所需的 `stock_api` 4 prefetch loop、`market_api`、`utils` |
| **编排层裁决** handler 返回组装 dict | §10#17 | 批准；SAD 措辞由 system-architect 回改（不在本 agent 范围） |

### 11.3 v1.3 收尾同步对照（N1 回退 · 以代码为准）

| # | 同步项 | 落点 | 与 v1.2 的差异 |
|---|--------|------|---------------|
| 1 | 业务端点降级体 **恒 200**（`_send_json_shape` 无 503 分支） | §1.1#9 / §2.1（yaml + 状态表）/ §2.2 / §4.1 BR-SRV-5b / §5.8 / §6.1 / §9 / §10#18·#29 | v1.2：error-only ⇒ 503 |
| 2 | **`_json_payload_has_data` 已删除** | §2.9（删除标注）/ §5.8 / §10#24 | v1.2：`_send_json_shape` 的判定入口 |
| 3 | **`_send_json(data, write_body, cache)` 无 `status`** | §2.10 / §5.8 | v1.2：`status=200` 形参 |
| 4 | **`http_503_total` 计数点 4→3**（`_reject_503` / `stream._serve_sse` / `/healthz`） | §1.1#9 / §2.1 状态表 / §6.1 / §10#29 | v1.2：多 `_send_json_shape` 一处 |
| 5 | 降级体**可缓存**：`cache=cache`（按域 TTL；v1.2 的"503 ⇒ 不缓存"消失） | §2.2 / §4.1 BR-SRV-5b / §6.1 / §11.3#1 | v1.2：`cache=cache and status==200` |
| 6 | `/healthz` 503 定位为**端点自身语义**（非业务端点先例） | BR-SRV-21 / §5.2 / §6.1 / §9 / §10#29 | v1.2：未区分端点归属 |
| 7 | 测试 `SRV-T36` 语义反转（error-only ⇒ **200**，`http_503_total` **不增**） | §8 T36 | v1.2：断言 503 |

### 10.1 既有测试的必改清单（供 code-developer / tester 依此同步）

| 测试 | 现状 | 必改点 | 理由 |
|------|------|-------|------|
| `test_server.py::test_handle_cls_hotplate_*` | 直接调用、依赖网络 | **无需改**（成功路径 keys/`hot_plates` 结构不变）★ 注意：若 CI 断网导致三分区全失败，新口径会**多出顶层 `error`**（BR-SRV-31）——断言若用精确键集合需允许该键 | ① 断网下的 key-set 断言属既有 mock 缺口（现状问题，非本次引入）；② 新增顶层 `error` 是 SAD §2.3 D-4 的**必须**口径 |
| `test_server.py::test_healthz_payload_includes_hotplate_endpoint` / `test_healthz_includes_market_endpoints` | 断言 path 存在 | **无需改**（feeds 条目集合不变） | 只增字段 |
| `test_server.py::test_fetch_json_leader_failure_does_not_stampede` | 断言 `err=1`/`ok=7` | **必改**（AR-10：`err=8`/`max_active=1`/负缓存窗口内 <1ms） | 属 `cache.md` T-CACHE-2（**已在 cache.md 登记**，非 server 范围，此处交叉引用） |
| `test_server.py::test_sector_cache_bounded` | import `_SECTOR_CACHE_MAX` | **必改**（`stock_api.md` §10#4 删该常量，改 `cache_policy('sector')['cache_max']`） | 属 `stock_api.md` 登记范围（交叉引用） |
| 新增 | — | `SRV-T*` **35 条** | 本详设 §8 |

> 本文档与 `config.md` **v1.3** / `cache.md` **v1.3** / `metrics.md` v1.1 / `stock_api.md` **v1.2** / `market_api.md` **v1.3** / `cdp_engine.md` v1.1 / `stream.md` **v1.2** 共同构成 P6c 优化专项的模块级详设；**server.py 的编码可与 stream.md 并行**（二者无共享文件的写冲突：server 仅延迟 import stream 的 `push_loop`/`run_stream_server`）。
>
> **v1.3 修订（N1 回退）**：**业务端点降级恢复 `200 + error 体`**——见 §11.3 对照表（7 组同步项）；`_json_payload_has_data` 删除、`_send_json` 去 `status`、`http_503_total` 计数点 3、降级体可缓存；§10 偏差扩至 **29 项**（新增 #29）；测试要点仍 **43 条**（`SRV-T36` 语义反转）。**未改代码、未改其他文档（仅本文件 + `_PROGRESS.md`）**。
>
> **v1.2 修订**：**P7b 契约同步（以代码为准）**——见 §11.1 对照表（16 组同步项；其中 **#1 error-only ⇒ 503 与 #12 `_send_json(status=)` 已由 v1.3 / N1 回退**）；§10 偏差扩至 28 项；测试要点扩至 43 条。**未改代码、未改其他文档**。
>
> **v1.1 修订**：闭环 `doc/review/HTTP-SSE层两模块_详细设计评审_专家版.md`（REV-DES-20260915-002）全部 P1×4 + P2×10；跨模块行为变更（`max_inflight` 形参、handler 返回组装 dict）已按编排层裁决落定。

