# stream.py 详细设计

> **版本** v1.3 · **状态** 已同步实现（P7b 契约同步 · **r5 容量重标定 + 冷启动去重/唤醒** · 以代码为准）· **日期** 2026-09-17 · **作者/产出** task-decomposer
> **v1.3 变更（契约级同步 · 以代码为准）**：① **节拍 = 最短订阅域 tier**：`tick_interval(fields=None)` 返回活跃订阅字段域的最短 TTL（quote/depth = L0 盘中 **4s**；无订阅回落 L1），**一轮只算一次并下传**（`push_loop` → `_push_once(t0, tick=)` → `_refresh_pool(..., tick=)`）② **容量模型重标定（r5）**：`_PER_FETCH_EST = config.STREAM_PER_FETCH_EST`（默认 **0.3**）、`BATCH_MAX_WORKERS = 20`、`_FIELD_FETCH_CALLS['quote'] = 2`（basic + depth）⇒ `coverage` = tick4 **213** / tick8 **426** / tick120 **6400**；`coverage_codes` tick4 = quote-only **106** / 3 域 **53**；C1 门限 = `_fetches_per_code(fields) × n ≤ coverage` ③ **`refresh_epoch` 新鲜度下限**：设定 tick 的域（`cache_policy(d)['ttl'] ≤ tick`）传**本轮起点** ⇒ 每拍真回源；慢域（fundflow/timeline）传 `None` 仍交错（`_domain_refresh_epoch` + `_call_refresh_handler`）④ **帧发送层去重**：`_frame_signature`（排除 `ts` 的 blake2b 摘要）+ 组级 `last_sig` ⇒ 内容未变不发；连接级 `_SSEConn.sent_any` ⇒ 未首发连接**强制补发**；`last_push_ts` **仅真正发送时刷新** ⑤ **空闲唤醒**：`_wake_event`/`_idle_sleeping`/`_wake_pending`/`_last_round_idle`；`create_group` 成功 / `_serve_sse` 连接登记后调 `_wake_push_loop()`；**仅空闲等待可被打断**，活跃轮仍硬 `time.sleep`（无连发）⑥ **冷首轮豁免**：进程首个真正刷新轮超预算不计 `degraded`/`slip`（仅一轮，`_first_refresh_done`）⑦ **不变量订正（重要）**：`_tick_sleep_seconds` 的真实不变量是「**轮起点→轮起点 ≥ 1 tick**」，**不是**「帧到达间隔 ≥ 1 tick」；相邻**已发送**帧到达间隔 = `tick − dur_k + dur_{k+1}`，冷→温（`dur_k > dur_{k+1}`）可短于 tick（未变帧现由去重丢弃）⑧ **SSE 帧契约只增**：`items[code].quote` 现可含 **`depth`**（五档盘口，21 字段）
> **v1.2 变更（契约级同步）**：① **对外帧格式扩元数据**（`codes_total`/`fields`/`missing`/`missing_count`/`errors`/`stale`/`stale_count`，items **覆盖全部订阅码**，可 `null`）② `_build_frame` **仅 `codes` 为空**时返回 `None` ③ **last-known 结转**（`_carry_forward`/`_last_known`，未刷新码带旧值并标 `_stale`）④ `_refresh_pool` 新签名 `(codes, now=None, fields=None, tick=None, deadline=None)`，按**订阅字段并集**刷新 + `deadline` 超预算跳过并标 `tick_budget_exceeded` ⑤ **容量模型重标定**：`_PER_FETCH_EST=2.2`、`_FIELD_FETCH_CALLS['quote']=1`、`coverage=23`、`coverage_codes`=1/2/3 域 → 23/11/7；C1 门限 `_fetches_per_code(fields)×n ≤ coverage` ⑥ **节拍整 tick 网格滑移**（`_tick_sleep_seconds`）+ 异常退避 1/2/4…封顶 8 tick；`_TICK_MIN_SLEEP_FRACTION` 已删 ⑦ lag gauge 空池/C1 发布 **0** ⑧ **准入 cap** `projected + largest ≤ budget`（单帧余量；满配组容量 **9→8**）⑨ `_valid_fields` **fail-closed**（显式非法字段 → 400）⑩ 码归一统一走 `config.canonical_code` ⑪ POST/PATCH **非 list → 400、非 object body → 400**；201/200 响应新增容量元数据 ⑫ `_serve_sse` `Connection: close` + `close_connection=True` + 抑制超时日志 ⑬ `_broadcast` 先滤 `closed`；`payload_bytes()` 已删 ⑭ `_MGMT_WORKER_RESERVE=10` 具名
> **v1.1 变更**：P1-4 流端口 `max_inflight=110` · P2-6 `_reserve_for` 用本轮排除集 · P2-7 补"销毁 vs 注册"复检 · P2-8 测试清单降级 1 条 · P2-9 `stream_refresh_lag_ticks` owner 对齐 · P2-10 `cached_batch(_FIELD_DOMAINS[field], …)` 统一
> 模块路径 `china_finance_rss/stream.py` · 归属 **Layer 2（SSE 推送 / 订阅管理）**
> 上游 SAD `doc/arch/SAD.md` **v1.3**（§2.2 R-2/R-6 · §2.5 C-1/C-2/C-3 · §4.2 帧共享与字节计费 · §4.3 资源上界 · §3 stream.py 行 · ADR-004/008/013）
> 上游 PRD `doc/prd/perf-stability-optimization.md` v0.3（AC-A1/A2/A7、AC-E5/E7、AC-S2/S7/S9/S10/S11；R5/R6/R7/R8）
> 基础层/数据层接口权威：`config.md` **v1.3** · `metrics.md` v1.2 · `stock_api.md` **v1.3**（`cache.md` 与本模块**无接口**）
> 跨模块约定（已锁定）：`doc/detailed/_PROGRESS.md` §A（分片轮转 / `_` 前缀 / 游标键 `'stream_refresh'`）
> 端锁定 🟠 STABLE（路由与 SSE 帧格式不变；`POST /stream/subscriptions` **新增 400 失败模式**〔`MAX_GROUPS` 超限，须编排层记变更日志〕）

## 1. 模块职责与边界

### 1.1 职责（8 条）

1. **推送主循环 `push_loop`**：每 tick 一次「清扫僵尸组 → 取活跃码集 → 分片轮转刷新 → 快照广播」；**tick = 活跃订阅字段域的最短 tier**（`tick_interval(_subscribed_fields())`：quote/depth = L0 盘中 4s；仅 fundflow/timeline = L1 8s；无订阅 = L1 基线；非盘中 120s），**一轮只算一次并下传** `_push_once(t0, tick=tick) → _refresh_pool(..., tick=tick)`；**tick 预算基准 = 本轮开始时刻**（修 R8 的静默滑动），耗时/滑动/degraded 入 metrics；**空闲等待可被 `_wake_push_loop()` 打断**（仅"本轮无活跃需求"的等待），活跃轮保持硬 `time.sleep`。
2. **分片轮转刷新 `_refresh_pool(codes, now=None, fields=None, tick=None, deadline=None)`（R-6 / AR-1 / INV-1b）**：按**订阅字段并集**刷新（`_subscribed_fields`/`_active_targets`/`_resolve_refresh_fields`）；**设定 tick 的域（`cache_policy(d)['ttl'] ≤ tick`）以本轮起点为 `refresh_epoch` 新鲜度下限 ⇒ 每拍真回源**（`_domain_refresh_epoch`/`_call_refresh_handler`），慢域传 `None` 仍走 TTL 交错；条件 `C1: _fetches_per_code(fields) × N_active ≤ coverage` 成立 ⇒ 整池一周期（**lag=0**）；否则每 tick 只刷 `|slice| ≤ coverage_codes`（**盘中 quote-only tick=4 → 106**；**3 域 tick=4 → 53**；tick=8 时 quote-only 213 / 3 域 106），其余码从**终点缓存**读取（`stock_api.cached_batch`），并记录 `stream_refresh_lag_ticks = ceil(n/|slice|)`。
3. **不可变组状态（C-1 / R5 / AC-S2）**：`codes → frozenset`、`fields → tuple`；`_build_frame(snapshot, codes, fields)` 接收**不可变快照**，帧构建移出锁区；帧 items **覆盖全部订阅码**（缺数据字段置 `null`），并携带 `codes_total`/`fields`/`missing`/`missing_count`（+ 可选 `errors`/`stale`/`stale_count`）元数据。
4. **distinct 帧引用计数计费（P0-1 / P1-N2 / ADR-013）**：`_Frame{payload,size,sid,refs}` + `_frame_bytes_lock` 保护全部 refs 读改写与 `stream_queue_bytes`/`_group_bytes` 增减；`_frame_acquire`/`_frame_release` 对称原语。
5. **队列字节预算 + 确定性丢弃**：`STREAM_QUEUE_BYTES_BUDGET`（128MB）；从"保留字节最大的组的最满连接"丢最旧帧；**绝不丢最新**（先腾位后入队）。
6. **生命周期收口**：`_drain_conn_queue` 在 `_serve_sse` finally / `destroy_group` / `_release_conn` 三处排空并逐帧归还；`None` 哨兵**不计费**。
7. **管理端点 + IO 预算**：`_read_json_body` 施加 `MGMT_BODY_TIMEOUT=5s` 读预算（读完恢复）；`MAX_GROUPS` 校验（超限 400）；`MAX_STREAM_CONNS` 连接硬界（超限 503）。
8. **可观测（AC-S10）**：9 个 stream 指标（§3.5）全部落在 `metrics._KNOWN` 冻结注册表内。

### 1.2 明确不做

- **不实现缓存/取数逻辑**：只调 `stock_api.handle_cls_*`（组装体）与 `stock_api.cached_batch`（只读）；不 import `cache`。
- **不实现帧计费之外任何内存机制**；不做增量 diff 帧（W 级，PRD §6）；不做鉴权/多租户。
- **SSE 信封不变**（`event: quote` / `id:` / `data: {…}`）、**不改断线重连语义**（AC-S11：`_register_conn` + 下一 tick 全量快照 + `STREAM_GROUP_IDLE_TTL=300s` 全部保留）。⚠️ `data` 体的**字段集已扩展**（v1.2 §2.4）：`{ts, codes_total, fields, items[全码], missing, missing_count, errors?, stale?, stale_count?}`——属**只增字段/只增语义**（原 `data.items` 仍是 `{code: {field: data}}`，新增 `null` 占位与元数据），端锁定仍 🟠 STABLE。
- **字段校验 fail-closed**：显式传入未知字段 ⇒ `_valid_fields` 抛 `ValueError` ⇒ 400（**不**静默回退全字段）。
- **不在本模块计算 `coverage` 的物理参数**：`BATCH_MAX_WORKERS` 由 `stock_api` 公开；本模块只做调度。
- **不新增后台线程**（仍 1 条 `push_loop` + 1 条 stream server 线程）；不新增模块级可变单例之外的存储。

### 1.3 layerIsolation 约束

`tech-stack.json` **未对 `stream.py` 单列 `layerIsolation` 条目**；须遵守分层方向与 allowlist（`http`/`urllib`/`json`/`queue`/`threading`/`time`/`uuid`/`logging`/`concurrent`/`os`）。

```
允许 import：
  标准库：hashlib（★ v1.3：`_frame_signature` 的 blake2b）/ json / logging / queue / socket /
          threading / time / uuid / concurrent.futures.ThreadPoolExecutor / http.server / urllib.parse
  包内  ：config（STREAM_PORT, MAX_STREAM_CONNS, MAX_CODES_PER_SUB, MAX_DEDUP_CODES, MAX_GROUPS,
                  MGMT_BODY_TIMEOUT, STREAM_PING_INTERVAL, STREAM_QUEUE_BYTES_BUDGET,
                  stream_frame_bytes, _trading_tiers, cache_policy）
          metrics
          stock_api（handle_cls_basic_infos, handle_cls_fundflow, handle_cls_timeline,
                     cached_batch, _prefetch_slice, _prefetch_advance, BATCH_MAX_WORKERS）
  延迟  ：from .server import BoundedThreadPoolServer   ← make_stream_server() 内（打破 server ↔ stream 环，现状保留）
禁止 import：cache（无接口需求）/ market_api / cdp_engine / utils；新增第三方库
```

> **`_prefetch_slice` / `_prefetch_advance` 是 `stock_api.md` §2.7 明文提供的跨模块轮转原语**（`_PROGRESS.md` §A.2 锁定"可调 `_prefetch_advance('stream_refresh', ...)`，该函数按 key 通用"）——读私有名有据，非越界。

### 1.4 依赖方向（`←` 表分层顺序，**非 import 关系**）

```
Layer 0: config（无依赖） ‖ metrics（零业务依赖叶子）
Layer 1: cache ← {config, metrics}
Layer 2: stock_api / market_api / stream ← {config, metrics}（stream 另依赖 stock_api 的 handler 与轮转原语）
Layer 3: server ← {stock_api, market_api, stream（延迟 import）, cache, config, metrics, utils}
```

> **同层依赖声明**：`stream → stock_api`（Layer 2 内部）是**既有事实**（现状 `stream.py:40-42` 已 import 3 个 handler）；本设计把该依赖**扩展**到 `cached_batch` + `BATCH_MAX_WORKERS` + 两个轮转原语，**方向不变、无环**。反向（`stock_api → stream`）禁止。

### 1.5 与 `stock_api` 的跨模块契约（`_PROGRESS.md` §A 锁定，不得偏离）

| stock_api 提供 | stream 用法（精确） |
|---------------|-------------------|
| `handle_cls_basic_infos / handle_cls_fundflow / handle_cls_timeline(codes, deadline=None, dropped=0, refresh_epoch=None) -> dict` | `_FIELD_HANDLERS = {'quote': handle_cls_basic_infos, 'fundflow': handle_cls_fundflow, 'timeline': handle_cls_timeline}`（**不变**）；经 `_call_refresh_handler` 调用 `handler(list(sl), deadline=deadline, refresh_epoch=epoch)`（★ 贯通 tick 预算 + 新鲜度下限；**不传 `dropped`** —— 2000 码内部已分块，截断只属 HTTP 层） |
| 组装体可能含保留键 `_errors`（非空失败码时） | `_` 前缀键**不作为股票进 `items`**（AR-7）；但 `_errors` 被**保留**为 `snapshot['_errors']`，最终出现在帧的 `errors` 字段（上游失败 vs "无缓存"可区分） |
| `cached_batch(domain, codes, now=None) -> dict`（无网络） | `snapshot = fresh(slice) ∪ cached(active − slice)`；`domain` 由 `_FIELD_DOMAINS[field]` 显式给出（见 §3.6）；调用 `cached_batch(_FIELD_DOMAINS[field], rest, now=now)` |
| `BATCH_MAX_WORKERS = 20`（公开名，= `config.BATCH_MAX_WORKERS`） | `coverage` 计算（§3.3） |
| `_prefetch_slice(pool, lock, key, size) -> (slice, next_cursor)`（不修改游标） | 游标键固定 `'stream_refresh'`；`pool` 传**临时轮转视图** `{code: 0.0 for code in sorted(active)}`（非成员账） |
| `_prefetch_advance(key, processed, total)` | 切片后 `_prefetch_advance('stream_refresh', len(sl), len(active))` 推进游标 |
| 帧完整性口径（AR-1 / P2-N2 / P1-4） | **warm 码不降级**（`cached_batch` 命中即入帧）；未刷新码经 **last-known 结转**带旧值并标 `stale`；**冷码无任何历史**时才进 `missing`；冷码在 ≤ lag tick 内进入 |

---

## 2. 接口契约

### 2.1 HTTP 端点（OpenAPI 风格，**唯一权威**；端口 `STREAM_PORT`=8054；路径与方法是既有契约不变）

```yaml
openapi: 3.0.3
info: {title: china-finance-rss stream port (8054), version: '1.4'}
paths:
  /stream/subscriptions:
    post:
      requestBody: {required: true, content: {application/json: {schema: {type: object,
        properties: {codes: {type: array, items: {type: string}, example: [sh600519, sz000001]},
                     fields: {type: array, items: {type: string, enum: [quote, fundflow, timeline]}}}}}}}
      responses:
        '201': {description: 建组成功, content: {application/json: {example: {sid: ab12cd34ef56, codes: [sh600519], fields: [quote],
                 refresh_capacity_codes: 106, refresh_lag_ticks: 1, capacity_warning: '...'}}}}
                 # ★ v1.2：新增 refresh_capacity_codes / refresh_lag_ticks（n>cap 时）/ capacity_warning（n>cap 时）
                 # ★ v1.3：refresh_capacity_codes 随 tick 与字段集变（tick=4 quote-only = 106 / 3 域 = 53）
        '400': {description: "invalid JSON body | JSON body must be an object | codes must be a list |
                              codes required | invalid stock code: X | unknown field: X |
                              too many codes (max 200) | pool would exceed 2000 codes |
                              subscription frames would exceed the <budget>-byte stream frame budget |
                              ☆ too many groups (max 200)   ← MAX_GROUPS 新增失败模式"}
        '404': {description: '{error: not found}（路径不匹配时）'}
  /stream/subscriptions/{sid}:
    get:
      responses:
        '200': {description: "组状态", content: {application/json: {example: {sid: .., fields: [quote],
                 codes: [sh600519], conns: 1, last_push_ts: 1760000000.0, created_ts: 1760000000.0}}}}
        '404': {description: '{error: not found}（组不存在或路径错）'}
    patch:
      requestBody: {required: true, content: {application/json: {schema: {type: object,
        properties: {add: {type: array, items: {type: string}}, remove: {type: array, items: {type: string}}}}}}}
      responses:
        '200': {description: '{sid, codes: [...], refresh_capacity_codes, [refresh_lag_ticks], [capacity_warning]}'}
        '400': {description: "invalid JSON body | JSON body must be an object | add must be a list | remove must be a list |
                              invalid stock code: X | too many codes (max 200) |
                              pool would exceed 2000 codes |
                              subscription frames would exceed the <budget>-byte stream frame budget"}
        '404': {description: '{error: subscription not found}（组不存在，或 PATCH 与 destroy 竞态时 get_group 返回 None）'}
    delete:
      responses: {'200': {description: '{deleted: true|false}'}, '404': {description: '{error: not found}'}}
  /stream/quote/{sid}:
    get:
      responses:
        '200': {description: 'SSE 流（text/event-stream；Cache-Control: no-cache；Connection: close；
                              每 L1 tick 一帧 event: quote，data 体见 §2.4；空闲 20s 发 event: ping）'}
        '404': {description: '{error: subscription not found}（组不存在，或"销毁 vs 注册"竞态收口）'}
        '503': {description: '{error: too many stream connections}（≥MAX_STREAM_CONNS=100；计入 http_503_total）'}
  # 其余路径 → 404 {'error': 'not found'}
```

**HTTP 语义矩阵（本次唯一变更 = 第 1 行末项）**

| 情形 | 状态 | 体 |
|------|------|----|
| 请求体非法 JSON / Content-Length 非法 / 读超时 | 400 | `{"error":"invalid JSON body"}` |
| 请求体非 object（如 `[..]`/`123`） | 400 | `{"error":"JSON body must be an object"}` ★ v1.2 |
| `codes`/`add`/`remove` 非 list（如 `123`/`true`/`"x"`） | 400 | `{"error":"codes/add/remove must be a list"}` ★ v1.2 |
| `codes` 缺失/空 | 400 | `{"error":"codes required"}` |
| 非法码（`config.canonical_code` → None） | 400 | `{"error":"invalid stock code: X"}` ★ 归一化权威 |
| 显式未知字段（`fields=['nonsense']`） | 400 | `{"error":"unknown field: nonsense"}` ★ v1.2 fail-closed |
| 单组码数 > `MAX_CODES_PER_SUB`(200) | 400 | `{"error":"too many codes (max 200)"}` |
| 去重池投影 > `MAX_DEDUP_CODES`(2000) | 400 | `{"error":"pool would exceed 2000 codes"}` |
| 跨组帧工作集 + 单帧余量 > `STREAM_QUEUE_BYTES_BUDGET` | 400 | `{"error":"subscription frames would exceed the <budget>-byte stream frame budget"}` ★ v1.2（P1-4 准入 cap） |
| **组数 ≥ `MAX_GROUPS`(200)** | **400** | `{"error":"too many groups (max 200)"}` ← ★ **新增对外失败模式**（SAD §7.1 P2-N7，须编排层记变更日志 + 同步流端口 API 文档） |
| 组不存在 | 404 | `{"error":"subscription not found"}`（PATCH）/ `{"error":"not found"}`（GET/DELETE）；**PATCH 与 destroy 竞态** ⇒ 404（`get_group` 返回 `None`） |
| 连接数 ≥ `MAX_STREAM_CONNS`(100) | 503 | `{"error":"too many stream connections"}`（计 `http_503_total`） |
| 路径未注册 | 404 | `{"error":"not found"}` |

> **码归一（P1-6）**：`create_group`/`patch_group` 一律走 `config.canonical_code`（`600519.SH` / `SH600519` → `sh600519`）；**404 语义不变**，非法码值仍为 400（不再有本地 `_normalize_code`/`VALID_STOCK_CODE` 引用）。

### 2.2 函数签名清单（本模块对外/跨模块可见面）

```python
# ── 组 CRUD（HTTP handler 与测试共用）──────────────────────────────
def create_group(codes, fields) -> tuple[str | None, str | None]      # (sid, error)；码经 config.canonical_code 归一
def get_group(sid) -> SubscriptionGroup | None
def patch_group(sid, add, remove) -> tuple[bool, str | None]          # (ok, error)；锁内复读组存活（S2-4d）
def destroy_group(sid) -> bool
def _valid_fields(fields) -> list[str]                                # ★ fail-closed：显式未知字段 raise ValueError
def _new_sid() -> str
def _deduped_codes_unlocked() -> set          # 调用方须持 _groups_lock
def _active_deduped_codes_unlocked() -> set   # 同上（仅含 conns 非空的组）
def _deduped_codes() -> set                   # 持锁包装
def _active_codes() -> set                    # 持锁包装
def _active_targets() -> tuple[set, list]     # ★ 一次持锁同时读 (codes, fields)（BUG-P6C-06）
def _subscribed_fields_unlocked() / _subscribed_fields() -> list[str]   # ★ 活跃组字段并集（_FIELD_HANDLERS 序）
def _projected_frame_bytes_unlocked() -> int  # ★ Σ_g stream_frame_bytes(|codes_g|,|fields_g|)（P1-4 准入 cap）
def _max_group_frame_bytes_unlocked(exclude_sid=None) -> int   # ★ 最大单组帧字节（单帧余量）

# ── 刷新 / 广播 / 帧 ────────────────────────────────────────────
def tick_interval(fields=None) -> int                             # ★ v1.3：最短订阅域 tier TTL（quote/depth=L0 盘中 4s）；无订阅 → L1
def _fetches_per_code(fields=None) -> int                         # ★ Σ _FIELD_FETCH_CALLS（quote=2, fundflow=1, timeline=1）
def refresh_capacity(tick, fields=None) -> tuple[int, int]        # ★ (coverage, coverage_codes)
def _domain_refresh_epoch(domain, tick, now) -> float | None      # ★ v1.3：ttl ≤ tick ⇒ now（每拍真回源）；慢域 ⇒ None
def _call_refresh_handler(handler, codes, deadline, refresh_epoch) -> dict   # ★ v1.3：仅调用帧 TypeError 降级
def _resolve_refresh_fields(fields) -> list[str]                  # ★ 显式 → 活跃订阅并集 → 全字段
def _refresh_pool(codes, now=None, fields=None, tick=None, deadline=None) -> dict   # ★ 新签名
def _carry_forward(snapshot, codes, fields) -> tuple[dict, set]   # ★ last-known 结转，返回 (merged, stale)
def _clear_last_known() -> None                                   # ★ 空池清账
def _frame_signature(frame) -> bytes                              # ★ v1.3：排除 ts 的 blake2b(16B) 摘要（去重基）
def _build_frame(snapshot, codes, fields) -> str | None           # ★ 仅 codes 为空时返回 None；帧含元数据
def _broadcast(snapshot) -> None                                  # ★ v1.3：先过滤 closed + 组级内容去重
def _tick_sleep_seconds(t0, tick, now) -> float                   # ★ 整 tick 网格
def _push_once(t0=None, tick=None) -> float                       # ★ v1.3：tick 由 push_loop 一次算好下传
def _wake_push_loop() -> None                                     # ★ v1.3：打断空闲等待（叶子锁，任意线程可调）
def push_loop() -> None                                           # 异常退避 1/2/4…封顶 8 tick；空闲等待可打断

# ── 帧计费（P1-N2 收口）─────────────────────────────────────────
def _frame_acquire(f) -> None                                     # ★ 先计费后入队（P1-1 防 ghost frame）
def _frame_release(f) -> None
def _reserve_for(incoming_len) -> int                             # 返回丢弃帧数
def _drain_conn_queue(conn) -> int                                # 返回归还帧数
def _pop_oldest_frame(conn) -> "_Frame | None"

# ── HTTP 层 ─────────────────────────────────────────────────────
def _require_code_list(value) -> tuple[bool, list | None]          # ★ codes/add/remove 必须为数组
def _capacity_meta(codes, fields) -> dict                          # ★ refresh_capacity_codes / refresh_lag_ticks / capacity_warning

# ── 连接 ────────────────────────────────────────────────────────
def _register_conn(conn) -> bool
def _release_conn(conn=None) -> None                              # ★ 增可选 conn（先排空再减计数）
def _sweep_idle_groups(now=None) -> None                          # 不变
def make_stream_server(max_workers=None) -> BoundedThreadPoolServer    # max_workers=max_inflight=MAX_STREAM_CONNS+_MGMT_WORKER_RESERVE
def run_stream_server() -> None                                   # 不变
```

### 2.3 `_refresh_pool(codes, now=None, fields=None, tick=None, deadline=None) -> dict`

| 参数 | 类型 | 默认 | 语义 |
|------|------|------|------|
| `codes` | `Iterable[str]` | — | 活跃码集（来自 `_active_targets()`，可达 `MAX_DEDUP_CODES=2000`）；也接受 list（测试） |
| `now` | `float \| None` | `None` | epoch 秒（注入点）；`None` → `time()`。**同时转发给 `cached_batch(..., now=now)`**（测试可驱动 C2 真过期路径），并作为 `epoch_base`（`refresh_epoch` 新鲜度下限基准，★ v1.3） |
| `fields` | `Iterable[str] \| None` | `None` | 本 tick 要刷新的字段集；`None` → `_subscribed_fields() or list(_FIELD_HANDLERS)`（`_resolve_refresh_fields`） |
| `tick` | `int \| None` | `None` | 调度器一次算好传回（`push_loop` 算 `tick_interval(_subscribed_fields())` → `_push_once(..., tick=)`），避免 tier 翻转时 C1/C2 门限与派发节拍不一致；直调者省略则 `tick_interval(fields)` 自算 |
| `deadline` | `float \| None` | `None` | 整 tick 的字段阶段共享预算；`None` → `time.time() + 0.8×tick` |

**返回**：`snapshot = {code: {field: data}}`（仅含**有数据**的码/字段）；若 handler 报错或超预算，额外带保留键 `snapshot['_errors'] = {code: kind}`（**不作股票项**，仅供帧元数据）。

**执行契约（字段并集 + 成本加权 C1 + 单 tick 预算）**

```
active = sorted(codes)                       # ★ 稳定序（轮转切片必须确定）
n = len(active)
if n == 0: return {}                         # 仅直调快路径；调度器由 _push_once 判空并自行发布 lag=0
fields = _resolve_refresh_fields(fields)     # 显式 → 活跃订阅并集 → 全字段（_FIELD_HANDLERS 序）
if tick is None: tick = tick_interval(fields)  # ★ v1.3：最短订阅域 tier（quote-only 盘中 4 / 非盘 120）
if deadline is None: deadline = time.time() + _TICK_BUDGET_FRACTION * tick
epoch_base = time.time() if now is None else now               # ★ v1.3：本轮起点（新鲜度下限基准）

coverage, coverage_codes = refresh_capacity(tick, fields)      # ★ coverage / coverage_codes
fetches_per_code = _fetches_per_code(fields)                   # Σ _FIELD_FETCH_CALLS[f]

if fetches_per_code * n <= coverage:                          # ★ 条件 C1（成本加权）
    sl, rest, lag = active, [], 0                             # 整池 ⇒ 无 lag（发布 0）
else:                                                          # C2 ⇒ 分片轮转
    view = {c: 0.0 for c in active}                            # 临时轮转视图（非成员账）
    sl, _ = _prefetch_slice(view, _slice_view_lock, 'stream_refresh', coverage_codes)
    _prefetch_advance('stream_refresh', len(sl), n)
    rest = [c for c in active if c not in set(sl)]
    lag  = -(-n // max(1, len(sl)))                            # ceil(n / |slice|)

for field in fields:                                           # fresh（≤ coverage 取数次数）
    handler = _FIELD_HANDLERS.get(field)
    if handler is None: continue                              # 防御（仅 _FIELD_HANDLERS 被 patch 时触发）
    if time.time() >= deadline:                               # ★ 超预算 ⇒ 跳过剩余字段并标记
        for code in sl: errors.setdefault(code, 'tick_budget_exceeded')
        break
    epoch = _domain_refresh_epoch(_FIELD_DOMAINS.get(field), tick, epoch_base)   # ★ v1.3
    fetched = _call_refresh_handler(handler, list(sl), deadline, epoch)          # ★ 贯通 deadline + epoch；不传 dropped
    if not fetched: continue
    for code, data in fetched.items():
        if not isinstance(code, str) or code.startswith('_'):
            if code == '_errors' and isinstance(data, dict): errors.update(data)   # ★ S2-1 保留
            continue                                          # ★ AR-7 跳过保留键（不作股票项）
        if data is not None: snapshot.setdefault(code, {})[field] = data

if rest:                                                      # cached（无网络）
    for field in fields:
        domain = _FIELD_DOMAINS.get(field)
        if domain is None: continue                           # 防御
        for code, data in cached_batch(domain, rest, now=now).items():
            if not isinstance(code, str) or code.startswith('_'): continue   # AR-7 同侧防御
            if data is not None: snapshot.setdefault(code, {})[field] = data

metrics.set_gauge('stream_refresh_lag_ticks', lag)             # BR-STR-21（C1 ⇒ 0）
if errors: snapshot['_errors'] = errors                        # ★ S2-1：帧元数据（绝不作股票项）
return snapshot
```

- **刷新即"订阅字段并集"**：quote-only 组不再替 fundflow/timeline 付费（BUG-P6C-06）——同样 tick 预算可覆盖约 3× 的码数。
- **`_` 前缀过滤是硬要求**（AR-7；`test` 必测）；但 `_errors` 被**保留**为 `snapshot['_errors']`（可区分"上游失败"与"无缓存"）。
- **`sl` 为空**（活跃集空）时 `_refresh_pool` 不会被调度器调用（`_push_once` 判 `if codes:`）；直调时 `n == 0` 直接返回（**不发布 lag gauge**——空池 lag=0 由 `_push_once` 发布）。

### 2.4 `_build_frame(snapshot, codes, fields) -> str | None`（帧 schema）

**返回体（SSE `data:` 部分，JSON）**

```yaml
ts:             <int>            # 毫秒整数
codes_total:    <int>            # 本组订阅码数 len(codes)
fields:         [<str>, ...]     # 本组订阅字段集（list of fields）
items:                           # ★ 覆盖全部订阅码（sorted(codes)，确定性字节序）
  <code>: {<field>: <data|null>, ...}   # 每个订阅字段都有键；无数据 ⇒ null
missing:        [<code>, ...]    # 所有订阅字段均为 null 的码（sorted）
missing_count:  <int>
errors:         {<code>: <kind>, ...}   # 可选；仅非空时出现（code 必须 ∈ items）
stale:          [<code>, ...]    # 可选；仅非空时出现（last-known 结转的码）
stale_count:    <int>            # 仅随 stale 出现
```

```python
def _build_frame(snapshot, codes, fields):
    """全量快照帧。codes: frozenset；fields: tuple（皆不可变 ⇒ 无锁遍历）。"""
    if not codes:
        return None                                 # ★ 仅当无订阅码时返回 None
    errors = snapshot.get('_errors') if isinstance(snapshot, dict) else None
    stale  = snapshot.get('_stale')  if isinstance(snapshot, dict) else None
    items, missing = {}, []
    for code in sorted(codes):                      # ★ 确定性帧字节
        entry = snapshot.get(code) or {}
        row = {f: entry.get(f) for f in fields}
        if all(v is None for v in row.values()):
            missing.append(code)
        items[code] = row
    payload = {'ts': int(time.time() * 1000), 'codes_total': len(codes),
               'fields': list(fields), 'items': items,
               'missing': missing, 'missing_count': len(missing)}
    if errors:
        err = {c: errors[c] for c in sorted(errors) if c in items}
        if err: payload['errors'] = err
    if stale:
        st = sorted(c for c in stale if c in items)
        if st: payload['stale'] = st; payload['stale_count'] = len(st)
    return json.dumps(payload, ensure_ascii=False, separators=(',', ':'))
```

- **`items[code].quote` 可含 `depth`（v1.3）**：`quote` 字段的数据客体由 `stock_api.fetch_cls_basic_info` 阶段 3 附带**五档盘口**（`fetch_cls_stock_depth`，20 档 `b_px_*/b_amount_*/s_px_*/s_amount_*` + `preclose_px`，共 **21 字段**），故 `quote` 值不是扁平 basic_info 而是含 `depth` 子键的客体。属**只增字段**（端锁定 🟠 STABLE）；`depth` 与 `quote` 同为 L0 域（盘中 TTL 4s）。
- **语义变更（v1.2）**：帧是**真正的全量快照**——`items` 覆盖**每个订阅码**，缺数据字段显式 `null`；此前"无数据的码被静默省略"，C2 分片 tick 可能只给 200 码中的 ~7 个而**无任何标记**，客户端无法区分"无行情"/"上游挂了"/"本 tick 未覆盖"。现以 `missing`/`stale`/`errors` 三类元数据区分。
- **`None` 仅当 `codes` 为空**：由于 items 恒覆盖全码，只要组有码就必产帧 ⇒ `last_push_ts` 每 tick 刷新（**不再有"全码无数据 ⇒ 不发帧 ⇒ 僵尸组被误回收"的路径**；僵尸组仍由 `conns` 为空在 `_broadcast` 前置跳过）。
- 返回 `str`（非 bytes）；`codes`/`fields` 不可变 ⇒ 锁外构建安全（BR-STR-2）。
- `stale` 与 `missing` **互斥**：带结转旧值的码有数据 ⇒ 不进 `missing`（`_carry_forward` 保证）。

### 2.5 `_broadcast(snapshot) -> None`（锁序 + 计费 + 确定性丢弃）

```
① with _groups_lock: groups = list(_groups.values())          # 快照即释放
② for g in groups:
     codes, fields = g.codes, g.fields                        # ★ 无锁读（frozenset/tuple）
     with g.conns_lock: conns = list(g.conns)                 # 快照即释放
     if not conns: continue                                   # 僵尸组：不构建帧
     live = [c for c in conns if not c.closed]                # ★ v1.2：先滤 closed，再腾位
     if not live: continue                                    # 为"入队给零个人"的帧腾位会误逐出他组真帧
     payload = _build_frame(snapshot, codes, fields)           # ★ 锁外（CPU 重）
     if payload is None: continue                             # 仅 codes 为空时
     sig = _frame_signature(payload)                          # ★ v1.3：排除 ts 的 blake2b 摘要
     newcomers = [c for c in live if not c.sent_any]          # ★ v1.3：从未收到过帧的连接
     if sig == g.last_sig and not newcomers:
         continue                                             # 内容未变且所有连接已收到 ⇒ 不发（last_push_ts 不刷）
     targets = live if sig != g.last_sig else newcomers       # ★ 变 ⇒ 全员；未变 ⇒ 只补未首发
     frame = _Frame(payload, g.sid)
     _reserve_for(frame.size)                                 # ★ 先腾位（≤ 预算）
     sent = False
     for conn in targets:
         if conn.closed: continue
         _frame_acquire(frame)                                # ★ v1.2：先计费后入队（防 ghost frame）
         try: conn.q.put_nowait(frame)
         except queue.Full:
             old = _pop_oldest_frame(conn)                     # 丢最旧
             if isinstance(old, _Frame):
                 _frame_release(old); metrics.incr('stream_frame_dropped_total')
             try: conn.q.put_nowait(frame)
             except queue.Full:
                 _frame_release(frame)                         # ★ 二次仍失败 ⇒ 未入队，撤销计费
                 continue
         conn.sent_any = True; sent = True                    # ★ v1.3
         if conn.closed: _drain_conn_queue(conn)               # ★ 关闭/入队竞态兜底（见 §7.4）
     if sent:
         g.last_sig = sig; g.last_push_ts = now                # ★ v1.3：仅真正发送时刷新
```

- **帧发送层去重（v1.3 / BUG-冷启动-01）**：同一组本 tick 的快照若与**上一次已发送帧**内容逐字节相同（`_frame_signature` 排除 `ts` ⇒ 只比 `codes_total`/`fields`/`items`/`missing`/`missing_count`/`errors`/`stale`/`stale_count`），则**不再重发**——消除"冷轮 3.5s + 温轮 0.1s ⇒ 两帧相隔 0.6s 且第二帧无新数据"的伪影。它对已收到帧的连接**只减发、不延迟**（有变化的快照仍在本 tick 发出）；**未首发连接**（`sent_any=False`，如新建/重连）由 `newcomers` **强制补发**当前帧，不必等下一 tick。`g.last_sig` 与 `g.last_push_ts` **只在 `sent=True` 时刷新**（被去重跳过的 tick 不得冒充一次推送）。
- **入队（IO 轻）也不在 `_groups_lock` 下** ⇒ PATCH（需 `_groups_lock`）与广播互不阻塞 ⇒ AC-S2 的 `tick 劣化 ≤20%` 由结构保证。
- **先计费后入队（v1.2 修订 BR-STR-9）**：`queue.put_nowait` 会唤醒阻塞在 `q.get()` 的 handler，其 `_frame_release` 可能在另一核上先跑；若"先入队后计费"，那次 release 会看到 `refs==0` 而短路（幂等 no-op），随后 acquire 便**遗留 ghost frame**（`_queue_bytes`/`_group_bytes`/`_live_frames` 永久漂移）。先 acquire 使 `refs≥1` 在帧可达前成立 ⇒ 消费者 release 必减到一个已计费帧。唯一发散窗口是"已计费未入队"这一条有界、自纠正的 in-flight（二次 `Full` 时 `_frame_release` 回滚）。
- `_reserve_for` 在**扇出前**执行一次（每 distinct 帧一次），保证**新帧必可入队**（B ≥ `F_max`）。
- `queue.Full` 分支丢弃的是**该连接最旧的**元素；`None` 哨兵不计费（`_pop_oldest_frame` 只对 `_Frame` 计数）。

### 2.6 管理端点与 SSE 端点（handler 行为契约）

| 方法 | 路径 | 行为 |
|------|------|------|
| `do_POST` | `/stream/subscriptions` | 路径不匹配 → 404；`_read_json_body()`（`None` → 400 `invalid JSON body`）→ 非 `dict` → 400 `JSON body must be an object` → `_require_code_list(body.get('codes'))`（非 list → 400 `codes must be a list`）→ `create_group(codes, body.get('fields'))` → `err` → 400；成功 → 201 `{sid, codes: sorted(...), fields: [...]}` + `_capacity_meta` |
| `do_GET` | `/stream/quote/<sid>` | `_serve_sse(sid)`（长连接；`Connection: close`） |
| `do_GET` | `/stream/subscriptions/<sid>` | 组状态 200（`fields` 为 tuple，`json.dumps` 自动转数组；`codes` 用 `sorted()`） |
| `do_PATCH` | `/stream/subscriptions/<sid>` | 路径不匹配 → 404；`_read_json_body()` → 非 `dict` → 400；`add`/`remove` 非 list → 400；`patch_group` → 404/400；成功 200 `{sid, codes}` + `_capacity_meta`；`get_group` 返回 `None`（与 destroy 竞态）→ 404 |
| `do_DELETE` | `/stream/subscriptions/<sid>` | `destroy_group` → 200 `{deleted: bool}`（未知 sid 仍 200 `{deleted:false}`） |
| 其它 | — | 404 `{"error":"not found"}` |

- **`_require_code_list(value) -> (ok, list)`（v1.2）**：`None`/缺省 → `(True, [])`；`list` → `(True, value)`；其它 → `(False, None)`。拦截 `{"codes":123}` / `{"add":true}` 这类非容器值——旧实现会让 `len()`/`for` 抛 `TypeError` **逃出 handler**（断开连接）而非契约 400。
- **`_capacity_meta(codes, fields)`（v1.2；★ v1.3 数值）**：`refresh_capacity(tick_interval(fields), fields)` → `refresh_capacity_codes`（按该组字段集的最短域；tick=4 quote-only = **106**、3 域 = **53**）；`n > cap` 时追加 `refresh_lag_ticks = ceil(n/cap)` 与 `capacity_warning`（键为**增量**，既有 `sid`/`codes`/`fields` 契约不变）。
- **冷启动唤醒（v1.3 / SSE 冷启动延迟）**：`create_group` 成功后、`_serve_sse` 连接登记（含 `_wake_push_loop` 前的存活复检）后各调一次 `_wake_push_loop()`（在 `_groups_lock` **之外**，`_wake_lock` 为叶锁）⇒ 空闲推送循环被立即打断并进入活跃轮，首个订阅者/新连接不必等整个 L1 基线 tick。**仅"上一轮无活跃需求"的等待可被打断**（`_last_round_idle`）；活跃轮仍是硬 `time.sleep`（无连发保证）。
- **`StreamHandler.log_error` 抑制** `'Request timed out: %r'`（拆除中的连接常发，非运维错误；与 `RSSHandler` 对齐）。

- `_read_json_body(self) -> dict | None`：`Content-Length` 非法/负/`>65536` → `None`（**不读体**）；否则 `settimeout(MGMT_BODY_TIMEOUT=5)` → `rfile.read(length)` → `finally` 恢复原 timeout；读超时/OSError → `None`；JSON 解析失败 → `None`。
- `StreamHandler.timeout = 30` 保留（类属性）；`_serve_sse` 内重设 `STREAM_PING_INTERVAL * 2 = 40s`（AC-S7）。

---

## 3. 数据结构（yaml）

### 3.1 组 / 连接 / 帧

```yaml
SubscriptionGroup:                    # _groups: dict[sid -> SubscriptionGroup]
  sid: <str>                          # uuid4().hex[:12]
  fields: <tuple[str, ...]>           # ★ 不可变（原 list）；['quote','fundflow','timeline'] 的子集，非空
  codes: <frozenset[str]>             # ★ 不可变（原 set）；创建/增删码一律「整体替换」
  conns: set[_SSEConn]                # 保留可变（生命周期事件驱动，频次低）→ 受 conns_lock
  conns_lock: threading.Lock
  last_push_ts: <float>               # 最近一次**真正发送**时刻（僵尸组清扫依据；★ v1.3：去重跳过的 tick 不刷新）
  last_sig: <bytes|None>              # ★ v1.3：上一次真正发送帧的 `_frame_signature`（None = 尚未发送过）
  created_ts: <float>
  # ★ v1.2：payload_bytes() 已删除（无引用面）。帧字节的真实口径由 _Frame.size 承担；
  #   跨组工作集由 config.stream_frame_bytes(|codes|,|fields|) 估算（准入 cap，§3.4）。登记 §10#14

_SSEConn:
  q: queue.Queue(maxsize=8)           # 元素 = _Frame（数据帧）| None（唤醒哨兵，不计费）
  closed: bool                        # 摘除/销毁标记（_broadcast 入队前检查）
  sent_any: bool                      # ★ v1.3：是否已收到过帧；False ⇒ 内容未变也强制补发（仅推送线程写）

_Frame:                               # distinct 帧持有者（同一组同 tick 的所有连接共享同一实例）
  __slots__ = ('payload', 'size', 'sid', 'refs')
  payload: <str>                      # SSE data 体（json 字符串）
  size: <int>                         # len(payload)（避免重复 len 调用）
  sid: <str>                          # 所属组（用于 _group_bytes 归集）
  refs: <int>                         # 当前被多少连接队列持有（受 _frame_bytes_lock）
```

### 3.2 模块级状态与计费账

```yaml
_groups: dict[sid -> SubscriptionGroup]
_groups_lock: threading.RLock          # 既有（CRUD 嵌套获取）
_conn_count: <int>                     # 既有（受 _conn_count_lock）
_conn_count_lock: threading.Lock
_frame_bytes_lock: threading.Lock      # ★ 新增：保护 refs / _queue_bytes / _group_bytes / _live_frames（叶锁）
_queue_bytes: <int>                    # = stream_queue_bytes = Σ_{refs>0} frame.size（distinct 计费一次）
_group_bytes: dict[sid -> int]         # 每组「保留中」distinct 帧字节和（丢弃选靶依据；refs 0→1 加、1→0 减）
_live_frames: <int>                    # refs>0 的 distinct 帧数 = stream_frame_distinct
_frame_peak_bytes: <int>               # 历史最大单帧字节 = stream_frame_peak_bytes
_slice_view_lock: threading.Lock       # ★ 新增：传给 _prefetch_slice 的轮转视图锁（叶锁，仅护 dict 读）
_last_known: dict[code -> {field: value}]        # ★ v1.2：last-known 结转账（受 _last_known_lock）
_last_known_lock: threading.Lock                 #  每次 _carry_forward 裁剪到活跃码集 ⇒ 有界于 MAX_DEDUP_CODES
_wake_lock: threading.Lock             # ★ v1.3：叶锁，仅护下面 3 个变量（任意线程可调 _wake_push_loop）
_wake_event: threading.Event           # ★ v1.3：打断空闲等待
_idle_sleeping: <bool>                 # ★ v1.3：push_loop 正处于"可唤醒的空闲等待"
_wake_pending: <bool>                  # ★ v1.3：尚不可唤醒时记下的请求（闭合 read-targets↔mark-idle 的丢失唤醒窗口）
_last_round_idle: <bool>               # ★ v1.3：上一轮是否无活跃需求（决定本轮 sleep 是否可打断）
_first_refresh_done: <bool>            # ★ v1.3：进程首个真刷新轮是否已过（冷首轮 degraded/slip 豁免，仅一次）
_TS_FIELD_PREFIX: b'{"ts":'            # ★ v1.3：_frame_signature 的 ts 前缀（紧凑序列化恒 ts 在前）
_last_group_sweep: <float>             # 既有
_GROUP_IDLE_TTL: config.STREAM_GROUP_IDLE_TTL   # = 300s（不改动，AC-S11 依据）
```

### 3.3 分片轮转参数与预算常量

```yaml
_FIELD_HANDLERS:                       # 既有，不变（字段名 == 域名的唯一来源见 §3.6）
  quote: handle_cls_basic_infos
  fundflow: handle_cls_fundflow
  timeline: handle_cls_timeline
_FIELD_DOMAINS: {quote: quote, fundflow: fundflow, timeline: timeline}   # ★ 新增显式映射
_TICK_BUDGET_FRACTION: 0.8             # tick 预算（AC-E5/S10）
_PER_FETCH_EST: config.STREAM_PER_FETCH_EST   # ★ v1.3 r5 重标定：串行等效秒/worker-call（默认 0.3；env 可调）
_FIELD_FETCH_CALLS: {quote: 2, fundflow: 1, timeline: 1}   # ★ 每码每域上游 REST 调用数（单一权威）
                                       #   quote=2：basic_info + 五档 `depth`（fetch_cls_stock_depth）
_DEFAULT_FETCH_CALLS: 1                # 未知（测试注入）字段的默认
_PUSH_ERROR_BACKOFF_CAP_TICKS: 8       # ★ 异常退避封顶 8 tick
_MGMT_WORKER_RESERVE: 10               # ★ 流端口在 MAX_STREAM_CONNS 之上预留的管理 worker
BATCH_MAX_WORKERS: 20                  # ← stock_api 公开名（= config.BATCH_MAX_WORKERS，import，不重定义）
_STREAM_REFRESH_KEY: 'stream_refresh'  # ← 轮转游标键（stock_api._prefetch_cursor 内）
# 节拍 = 活跃订阅字段域的最短 tier TTL（tick_interval(fields)）：
#   quote / depth = L0 → 盘中 4s（非盘中 120s）；fundflow / timeline = L1 → 8s；无订阅 → L1 基线
coverage        = max(1, int(0.8 × tick × BATCH_MAX_WORKERS / _PER_FETCH_EST))   # 取数次数/tick
fetches_per_code = Σ _FIELD_FETCH_CALLS[f] for f in fields
coverage_codes  = max(1, coverage // fetches_per_code)                  # 每 tick 可"整码全刷"的码数
# 派生（运行时实值；★ coverage 随 tick 线性增长，非恒值）：
#   tick=4    → int(0.8*4*20/0.3)   = 213 取数次数/tick
#   tick=8    → int(0.8*8*20/0.3)   = 426
#   tick=120  → int(0.8*120*20/0.3) = 6400
#   coverage_codes（随 tick 与订阅字段集变；tick=4）：
#     quote-only → 213 // 2 = 106        3 域（quote+fundflow+timeline）→ 213 // 4 = 53
#   C1: _fetches_per_code(fields) × n <= coverage  ⇔  n <= coverage_codes
#   （tick=8：quote-only 213 / 3 域 106）
```

> **与 SAD 的口径差**：SAD §2.1 INV-1b 的 `coverage≈170 ⇔ coverage_codes≈56` 是**旧标定**（`_PER_FETCH_EST=0.3`、quote 记 2 次调用，但按 8 worker + 固定 tick）。★ **v1.3（r5）实测重标定**：`_PER_FETCH_EST=0.3`（连接池 + DNS 缓存后单次 worker-call ≈0.14s，留 ≈2.2× 余量）、`BATCH_MAX_WORKERS=20`、`_FIELD_FETCH_CALLS['quote']=2` ⇒ `coverage` = tick4 **213** / tick8 **426** / tick120 **6400**，`coverage_codes` tick4 = quote-only **106** / 3 域 **53**。SAD 的 170/56 与 `stream.md` v1.2 的 23/23·11·7 均**已作废**（登记 §10#15/#21）。切片上限**随 `tick_interval(fields)` 与订阅字段动态计算**，不写死任何数字。

### 3.4 `STREAM_QUEUE_BYTES_BUDGET` 与丢弃候选

```yaml
STREAM_QUEUE_BYTES_BUDGET: 134217728   # ← config（128MB，env 可调，整数字节）
stream_frame_bytes(codes, fields):     # ← config 单一权威：codes × fields × 23KB
F_max: stream_frame_bytes(200, 3) ≈ 14MB   # 单帧上界（MAX_CODES_PER_SUB × 3 字段）
推导: B(128MB) ≥ 8 × F_max(≈112MB) ⇒ 单个满尺寸组的 8 深窗口不被强制驱逐（保 AC-E5「丢弃 ≤1 帧」）
准入 cap（create_group / patch_group，P1-4；含单帧余量）:
  projected = Σ_g stream_frame_bytes(|codes_g|, |fields_g|)      # 全组稳态 distinct 帧工作集
  largest   = max(max_{g≠sid} frame_bytes_g, incoming)            # 最大单组帧（patch 时排除自身重定价）
  条件：projected + largest ≤ STREAM_QUEUE_BYTES_BUDGET            # ★ 额外留"一帧"余量
  含义：满配组容量 **9 → 8**（9×14.1MB + 14.1MB = 141MB > 128MB 被拒；8×14.1+14.1 ≈ 126.9MB 通过）
  超限 ⇒ 400 `_FRAME_BUDGET_ERR`（不触网、不改组）
候选选择（_reserve_for 每次入队前）:
  ① 取 _group_bytes 中值最大且 >0、且**不在本轮排除集 `skip`** 的组 sid（无则返回）
  ② 该组内按 qsize() 降序的快照；逐个连接尝试取队首（None 哨兵会被消费掉，继续下一个连接）
  ③ 命中 _Frame → _frame_release + stream_frame_dropped_total++；均无 _Frame ⇒ **仅把该 sid 加入 `skip`**
     （★ P2-6：**不** `pop(_group_bytes[sid])`——该组仍有 refs>0 的帧，逐出全部字节会系统性低估
     `_group_bytes`，破坏"从保留字节最大组丢最旧"的确定性）
  ④ 循环直至 _queue_bytes + incoming_len ≤ STREAM_QUEUE_BYTES_BUDGET（`skip` 单调增长 ⇒ 必然终止）
保证: 新帧**必可入队**（最坏清空其余）；**绝不因预算拒绝最新帧**；`_queue_bytes` 上界仍不破（真实字节仍被计入）
```

### 3.5 metrics 口径（9 名，全部 ∈ `metrics._KNOWN` 冻结注册表）

```yaml
stream_frame_dropped_total: counter   # owner=_broadcast（+_reserve_for）：每丢弃一个 _Frame +1（含队列满丢最旧、预算驱逐）
stream_queue_bytes:         gauge     # owner=_broadcast：Σ_{refs>0} frame.size（_frame_acquire/release 内发布）
stream_frame_distinct:      gauge     # owner=_broadcast：refs>0 的 distinct 帧数（_live_frames）
stream_frame_peak_bytes:    gauge     # owner=_broadcast：历史最大**单帧**字节（§10#8）
stream_tick_duration_ms:    gauge     # owner=push_loop：round(( t_end - t0 ) * 1000, 2)
stream_tick_slip_total:     counter   # owner=push_loop：duration >= tick（本轮超出整 tick ⇒ sleep=0 连跑）
stream_tick_degraded_total: counter   # owner=push_loop：duration > 0.8 * tick（AC-E5/S10 预算超支）
stream_refresh_lag_ticks:   gauge     # owner=stream.push_loop（发布点 _push_once 空池分支 / _refresh_pool）
                                      # ★ v1.2：空池 ⇒ 0（_push_once else 分支）；C1 ⇒ 0；C2 ⇒ ceil(N_active / |slice|)
stream_slow_client_total:   counter   # owner=_serve_sse 摘除路径（§10#4 判据收紧）
http_503_total:             counter   # ← server 侧同名计数；stream._serve_sse 连接超限时亦 incr（S10 口径跨两端口）
```

### 3.6 字段名与域的等价关系（显式表，防未来解耦）

```yaml
# _FIELD_HANDLERS 的键（字段名）与 cached_batch/handler 的域参数一一相同：
fields: [quote, fundflow, timeline]
domains: {quote: quote, fundflow: fundflow, timeline: timeline}   # _FIELD_DOMAINS
# 理由：quote 字段由 handle_cls_basic_infos 提供，其域 = cache_policy('quote')（stock_api.md §2.4）
# 一旦未来字段名与域解耦，必须同时更新 _FIELD_HANDLERS 与 _FIELD_DOMAINS（两表同 change-set）
```

---

## 4. 业务规则（编号供伪代码与测试引用）

### 4.1 组状态不可变与锁序（C-1 / C-2）

| 编号 | 规则 | 依据 |
|------|------|------|
| **BR-STR-1** | `SubscriptionGroup.codes` 恒为 `frozenset`、`fields` 恒为 `tuple`；**禁止原地 `add`/`discard`/`append`**——增删码一律 `g.codes = (g.codes \| frozenset(add)) - frozenset(remove)`（整体替换，在 `_groups_lock` 下） | ADR-004 / R5 |
| **BR-STR-2** | 广播路径的锁序固定 `_groups_lock → g.conns_lock`，**各自"取快照即释放"**；`_build_frame` 与 `put_nowait` **不在任何组锁内** | ADR-004 / AC-S2 |
| **BR-STR-3** | 僵尸组（`conns` 为空）**不构建帧**、不刷新 `last_push_ts`（保证 `_sweep_idle_groups` 可回收） | 现状保留 |
| **BR-STR-4** | 类型即承诺：`frozenset`/`tuple` 可被任意线程无锁遍历；任何"想原地改"的后续改动**必须**在评审/测试期暴露（`test` 断言类型） | ADR-004 |

### 4.2 帧计费与预算（P0-1 / P1-N2 / ADR-013）

| 编号 | 规则 | 依据 |
|------|------|------|
| **BR-STR-5** | 计费对象是 **distinct 帧对象**：`_broadcast` 每组建 **1 个** `_Frame`，所有连接共享同一引用；`stream_queue_bytes = Σ_{refs>0} frame.size`（每个 distinct 帧**只计一次**）。**禁止**按连接数重复计费 | ADR-013 / P0-1 |
| **BR-STR-6** | `refs` 语义 = 「该帧当前被多少连接队列持有」；`_frame_acquire(f)`：`refs += 1`，`0→1` 时 `_queue_bytes += f.size` 且 `_group_bytes[f.sid] += f.size`、`_live_frames += 1`；`_frame_release(f)` 为逆运算（`1→0` 时减回、`_live_frames -= 1`） | SAD §4.2 |
| **BR-STR-7** | **所有** `refs` 读改写与 `_queue_bytes`/`_group_bytes`/`_live_frames`/`_frame_peak_bytes` 增减**必须在 `_frame_bytes_lock` 内**（CPython `+=` 非原子；`queue.Queue` 自带锁不覆盖"计费+入队"复合操作） | P1-N2① |
| **BR-STR-8** | `_frame_bytes_lock` 临界区**仅整数/dict 算术 + `metrics`（叶子锁）**：无 IO、无嵌套加锁、**不触碰** `_groups_lock`/`conns_lock`/`_conn_count_lock` | P1-N2① / §7 |
| **BR-STR-9** | 入队顺序（★ v1.2 修订，**以代码为准**）：**先 `_frame_acquire(f)`（使 `refs≥1`）再 `put_nowait`**；`queue.Full` 且二次入队仍失败 ⇒ `_frame_release(f)` **回滚**（未入队不得计费）。**禁止**"先 put 后 acquire"：`put` 会唤醒阻塞在 `q.get()` 的 handler，其 `_frame_release` 可能在另一核先跑、看到 `refs==0` 而短路，随后 acquire 便遗留 **ghost frame**（`_queue_bytes`/`_group_bytes`/`_live_frames` 永久漂移） | P1-1 / 计费自洽 |
| **BR-STR-10** | 队列满 ⇒ 丢**该连接队首最旧**元素（`_Frame` 归还 + `stream_frame_dropped_total++`；`None` 哨兵跳过）⇒ 客户端恢复后读到**最新**帧（AC-A2 丢旧保新） | AC-A2 / AC-E7 |
| **BR-STR-11** | 全局预算：入队前 `_reserve_for(frame.size)` 从「`_group_bytes` 最大组的最满连接」反复丢最旧，直至可容纳；每次丢弃 `stream_frame_dropped_total++`；**B ≥ F_max ⇒ 新帧必可入队，绝不丢最新** | ADR-013 / AC-A2 |
| **BR-STR-12** | **`None` 哨兵不计费**：不包 `_Frame`、不参与 `refs`/字节数；`_drain_conn_queue`/`_pop_oldest_frame` 遇到 `None` 直接跳过（仅用于唤醒 handler 退出） | P1-N2③ |
| **BR-STR-13** | **生命周期收口**：`_drain_conn_queue(conn)` 必须在该连接**所有**终止路径执行——`_serve_sse` 的 `finally`（经 `_release_conn(conn)`）、`destroy_group`（`g.conns.clear()` 之后、锁外）、入队后复检 `conn.closed` 的兜底；否则残留帧字节**永久占用预算**（单调泄漏）⇒ 后续 tick 无条件丢帧 | P1-N2② / P0-1 后果 |
| **BR-STR-14** | 出队消费即归还：`_serve_sse` 取到 `_Frame` 后，在**写完该帧的 `finally`** 中 `_frame_release(f)`（写阻塞 ≤40s 的窗口内该帧仍计费，更保守；异常路径不泄漏） | SAD §4.2（细化见 §10#10） |
| **BR-STR-15** | `_reserve_for` 必须有**进展保证**：无可丢 `_Frame` 的组只加入**本轮排除集 `skip`**（`skip` 单调增长 ⇒ 循环必然终止），**禁止**死循环；**禁止**用 `pop(_group_bytes[sid])` 把仍有 `refs>0` 帧的组整组逐出（P2-6：会系统性低估组保留字节、破坏丢弃选靶确定性） | 实现安全 / 修 P2-6 |
| **BR-STR-36** | **帧发送层去重（v1.3 / BUG-冷启动-01）**：`_broadcast` 以 `sig = _frame_signature(payload)`（`payload` 去掉 `ts` 后的 blake2b(16) 摘要）与组级 `g.last_sig` 比较。**相同且无未首发连接** ⇒ **整组跳过**（不建 `_Frame`、不入队、**不刷 `last_push_ts`**）。**有变化** ⇒ 发全员；**无变化但有 `newcomers = [c for c in live if not c.sent_any]`** ⇒ **只补发这些连接**（新连/重连 1 tick 内拿到当前帧，不必等数据变化）。`g.last_sig`/`g.last_push_ts` 仅在本次**确有连接入队成功**（`sent=True`）时刷新。保证：任一连接不会连续收到两帧内容相同的数据帧（`_reserve_for`/`queue.Full` 对已落后客户端的丢弃是既有例外） | BUG-冷启动-01 / AC-A1 |

### 4.3 分片轮转刷新（R-6 / AR-1 / INV-1b）

| 编号 | 规则 | 依据 |
|------|------|------|
| **BR-STR-16** | `coverage` 单位 = **取数次数/周期**（不是码数）：`coverage = max(1, int(0.8 × tick × BATCH_MAX_WORKERS / _PER_FETCH_EST))`（`_PER_FETCH_EST=config.STREAM_PER_FETCH_EST`=0.3、`BATCH_MAX_WORKERS=20` ⇒ tick4 **213** / tick8 **426** / tick120 **6400**）；`coverage_codes = max(1, coverage // _fetches_per_code(fields))` ⇒ tick=4 quote-only **106** / 3 域 **53**。`_FIELD_FETCH_CALLS`（**quote=2**：basic + depth）是该成本模型的**单一权威**（`refresh_capacity`/`_fetches_per_code` 共用） | SAD §2.1 INV-1b（BUG-P6C-06 重标定；★ v1.3 r5 复标定） |
| **BR-STR-16b** | 刷新字段集 = `_resolve_refresh_fields(fields)`：显式 `fields` → **活跃组字段并集**（`_subscribed_fields`）→ 全字段兜底；顺序恒按 `_FIELD_HANDLERS`。**禁止**无条件扫全 3 域（quote-only 组会被强制付 3 域成本，BUG-P6C-06） | BUG-P6C-06 |
| **BR-STR-17** | 条件 `C1: _fetches_per_code(fields) × n ≤ coverage` 成立 ⇒ **整池一周期刷新**（`sl = 全部活跃码`、`rest = []`、**`lag = 0`**） | SAD §2.2 R-6 |
| **BR-STR-18** | C1 不成立 ⇒ `|slice| ≤ coverage_codes`；切片由 `stock_api._prefetch_slice`（键 `'stream_refresh'`）按 round-robin 产出，切片后 `_prefetch_advance('stream_refresh', len(sl), n)` 推进游标；**不得**按"理论上界"切片（旧口径 71 码 ≈213 取数 ≈1.0×tick） | SAD §2.2 R-6 |
| **BR-STR-19** | 未进切片的码从**终点缓存**读（`stock_api.cached_batch(_FIELD_DOMAINS[field], rest, now=now)`，**无网络**）后并入快照：`snapshot = fresh(sl) ∪ cached(active − sl)` | SAD §2.2 R-6 |
| **BR-STR-20** | **warm 码帧完整性不降级**（`cached_batch` 命中即入帧）；未刷新但**有最后一帧历史值**的码经 `_carry_forward` 带旧值入帧并标 `stale`；**冷码**（无缓存且无历史）才进 `missing`，并在进入首个切片（≤ lag tick）后转 fresh。AC-A1 的"每帧覆盖全部码"以 **warm 稳态 + 200 帧窗口**为前提（P2-N2） | P2-N2 / AR-1 / P1-4 |
| **BR-STR-20b** | `_carry_forward(snapshot, codes, fields)`：`_last_known` 每 tick 裁剪到 `codes`（有界 ⇒ 池缩即回收内存）；fresh 值更新 `_last_known`；仅当"本 tick 既未刷新也未命中缓存且存在历史非 null"时结转并加入 `stale`；**同一码不兼具 `stale` 与 `missing`**；无活跃需求时 `_clear_last_known()` | P1-4 |
| **BR-STR-21** | `lag = 0`（C1）或 `ceil(n / len(sl))`（C2）；每次刷新后 `metrics.set_gauge('stream_refresh_lag_ticks', lag)`；**空池由 `_push_once` 发布 0**（不可放在 `_refresh_pool`——空池下该函数不可达，会产生"最后一次 C2 值被永久滞留"的 BUG-P6C-08） | SAD §2.2 R-6 / AC-S10 / BUG-P6C-08 |
| **BR-STR-22** | **`_` 前缀键不作股票项**：`_refresh_pool` 遍历时 `if code.startswith('_'): continue`（fresh 与 cached 两侧同防）；**但 `_errors` 特殊处理**——保留为 `snapshot['_errors']` 供帧 `errors` 字段（AR-7 唯一陷阱点，必测） | ADR-002 / AR-7 / S2-1 |
| **BR-STR-23** | 切片顺序必须**确定**：`active = sorted(codes)` 后再构造轮转视图（set 迭代序不保证跨 tick 稳定 ⇒ 否则游标语义失真） | 轮转正确性 |
| **BR-STR-24** | `_refresh_pool` 的 handler 调用传 `deadline=deadline`（贯通单 tick 预算）、**不传 `dropped`**（截断只属 HTTP 层；2000 码由 handler 内部分块保证不丢码）；字段阶段开始时刻 `time.time() >= deadline` ⇒ 跳过剩余字段并对 `sl` 全码标 `tick_budget_exceeded`，**绝不阻塞 push 线程** | SAD §2.4 / P1-1 |
| **BR-STR-24b** | **`refresh_epoch` 新鲜度下限（v1.3 / BUG-冷启动-01）**：`epoch_base = now if now is not None else time()`（**本轮起点**）。对每个字段 `epoch = _domain_refresh_epoch(_FIELD_DOMAINS.get(field), tick, epoch_base)`——**仅当 `cache_policy(domain)['ttl'] <= tick`**（该域"设定"了本 tick）返回 `epoch_base`，否则 `None`；`epoch is None` 的字段（含测试注入字段）行为与旧版**逐字一致**。`_call_refresh_handler(handler, list(sl), deadline, epoch)` 把 epoch 作为**纯增量 kwarg** 下传：仅当 TypeError 抛自**调用帧**（`tb_next is None`）才退回 `handler(codes, deadline=deadline)`；**函数体内的 TypeError 原样上抛**（避免重复执行）。⇒ 设定 tick 的域**每一拍都真回源**（quote-only 时 quote/depth，TTL==tick），消除"`tick − δ` 相位命中"导致的隔拍旧值；慢域（fundflow/timeline，TTL 8 > tick 4）保持 TTL 交错（按域分拍） | BUG-冷启动-01 / BUG-P6C-06 |
| **BR-STR-24c** | **节拍 = 最短订阅域（v1.3 / BUG-SSE-DEPTH-01）**：`tick_interval(fields)` = `min(_trading_tiers()[cache_policy(d)['tier']] for d in {_FIELD_DOMAINS[f] for f in fields 且已知})`；`fields` 为空/未知域 ⇒ `_trading_tiers()['L1']`（历史基线，空闲调度与既有调用者行为不变）。**一轮只算一次**（`push_loop` 计算后传入 `_push_once(t0, tick=)` 再传 `_refresh_pool`），避免 tier 翻转时 C1/C2 门限、per-tick deadline 与 slip 口径互相打架 | BUG-SSE-DEPTH-01 |

### 4.4 tick 预算与观测（R8）

| 编号 | 规则 | 依据 |
|------|------|------|
| **BR-STR-25** | `t0 = time()` 在**本轮开始**取；`duration = time() - t0`；`metrics.set_gauge('stream_tick_duration_ms', round(duration*1000, 2))` | SAD §2.6 |
| **BR-STR-26** | `duration > 0.8 × tick` ⇒ `stream_tick_degraded_total++`；`duration >= tick` ⇒ `stream_tick_slip_total++`（本轮已超出整 tick） | SAD §2.6 / AC-E5 |
| **BR-STR-27** | **整 tick 网格滑移**（`_tick_sleep_seconds(t0, tick, now)`）：`k = int((now − t0)//tick) + 1`（≥1，时钟回拨兜底 `k=1`），`delay = max(t0 + k×tick − now, 0.0)`。**基准仍 = 本轮开始时刻**（消除静默滑动），sleep 恒到 `now` 之后的下一个网格点。★ **v1.3 不变量订正（以代码为准）**：该规则保证的是「**轮起点 → 轮起点 ≥ 1 tick**」，**不是**「相邻帧到达间隔 ≥ 1 tick」——帧在轮的**末端**（`_broadcast`）发出，两帧到达间隔 = `tick − dur_k + dur_{k+1}`，当 `dur_k > dur_{k+1}`（冷→温）时可**短于 tick**（4s tick 下实测约 0.6s）。此类"未变帧"已由 `_frame_signature` 去重丢弃（BR-STR-36），故亚 tick 间隔只可能出现在**确有新数据**的两轮之间。**旧 `_TICK_MIN_SLEEP_FRACTION=0.25` 已删除**；`delay > 0` 才 `sleep` | SAD §2.6（修 R8）+ BUG-P6C-06 + BUG-冷启动-01 |
| **BR-STR-28** | `_sweep_idle_groups` 每 60s 触发一次（`now - _last_group_sweep >= 60`）；单轮逻辑抽为 **`_push_once(t0=None, tick=None) -> delay`**（含 `if codes:` 守卫、空池 lag=0 分支与 `_last_round_idle` 发布，可被测试直驱而不进无界循环；`tick` 由 `push_loop` 下传，直调者省略则自算）；`push_loop` 内 `try/except Exception` 兜底：连续失败 `consecutive += 1`，`spans = min(2^(consecutive-1), _PUSH_ERROR_BACKOFF_CAP_TICKS=8)`，`delay = max(spans×tick − elapsed, _tick_sleep_seconds(...))` ⇒ **退避 1/2/4/…封顶 8 tick**，绝不退化成 ~1s 自旋 | 现状保留 + P2 退避 |
| **BR-STR-37** | **冷首轮豁免（v1.3 / BUG-冷启动-01）**：`_first_refresh_done` 为 `False` 且本轮 `codes` 非空 ⇒ 该轮为"冷首轮"，**不**计 `stream_tick_degraded_total`/`stream_tick_slip_total`（空连接池 / 空 DNS / 冷 sector 的一次性启动成本，非劣化）；空轮不消费该豁免；此后**每个**超预算轮照常计数（真实劣化不被掩盖）。仅豁免**一轮**（进程生命周期内一次） | BUG-冷启动-01 |
| **BR-STR-38** | **空闲唤醒（v1.3 / SSE 冷启动延迟）**：`_wake_push_loop()`（叶锁 `_wake_lock`，任意线程可调、不阻塞 IO/非叶锁）置 `_wake_pending=True`，若 `_idle_sleeping` 则 `_wake_event.set()`；`push_loop` 在**无活跃需求**的轮末进入 `_wake_event.wait(delay)`（可打断），**活跃轮**保持硬 `time.sleep(delay)`。每轮顶部清 `_wake_event`/`_wake_pending`；进入空闲等待前在锁内复查 `_wake_pending`（闭合"读完 targets → 标记 idle"之间的丢失唤醒窗口）。**不变量**：唤醒只能缩短一次**空轮**的等待，绝不使两个**轮起点**间距 < 1 tick（空轮不发帧，故也不会连发帧） | BUG-冷启动-01 |

### 4.5 生命周期与有界（组/连接/管理请求）

| 编号 | 规则 | 依据 |
|------|------|------|
| **BR-STR-29** | 组总数上限 `MAX_GROUPS`（=200）：`create_group` 在 `_groups_lock` 内先判 `len(_groups) >= MAX_GROUPS` ⇒ 返回 `(None, 'too many groups (max 200)')` ⇒ HTTP 400 | SAD §2.2 R-2 / P2-N7 |
| **BR-STR-29b** | **帧预算准入 cap（P1-4）**：`create_group`/`patch_group` 在 `_groups_lock` 内校验 `_projected_frame_bytes_unlocked() + largest ≤ STREAM_QUEUE_BYTES_BUDGET`（`largest = max(_max_group_frame_bytes_unlocked([exclude_sid]), incoming)`），超限 ⇒ 返回 `_FRAME_BUDGET_ERR` ⇒ 400。无此 cap 时一组"合法"订阅（如 9 个满配组）会迫使每 tick 逐出他组真帧（违反 AC-E5） | P1-4 / S2-2 |
| **BR-STR-29c** | **字段 fail-closed（S2-4）**：`_valid_fields(fields)` 对**显式**未知字段抛 `ValueError('unknown field: X')`；仅"未提供字段"才回退全字段默认。`create_group` catch `(ValueError, TypeError)` → `(None, str(exc))` ⇒ 400。旧 `out or list(_FIELD_HANDLERS)` 会把 `fields=['nonsense']` 变成全 3 域（帧字节与上游成本 ×3，且客户端拿到未请求的结构、无错误信号） | S2-4 |
| **BR-STR-29d** | **请求体形状严格（P1-2）**：`_require_code_list` 要求 `codes`/`add`/`remove` 为 JSON 数组（`None`/缺省 ⇒ `[]`）；非容器值 ⇒ 400 `... must be a list`。非 object 体 ⇒ 400 `JSON body must be an object`。**禁止**把 `TypeError` 泄出 handler（旧行为会重置连接而非返回契约 400） | P1-2 |
| **BR-STR-29e** | **码归一单一权威（P1-6 / S2-4b）**：`create_group`/`patch_group` 一律 `config.canonical_code`（`600519.SH`/`SH600519` → `sh600519`），**归一去重**在折叠之后；无效码 ⇒ 400 `invalid stock code`。**禁止**本地正则（会为同一股票铸出第二个池/缓存/账本键） | P1-6 / S2-4b |
| **BR-STR-30** | 连接硬界 `MAX_STREAM_CONNS`（=100）：`_register_conn` 超限返回 `False` ⇒ `_serve_sse` 返回 503；`_release_conn` 减计数（下限 0） | AC-E7 / §4.3 |
| **BR-STR-31** | SSE socket 超时 = `STREAM_PING_INTERVAL × 2`（env 化后默认 20 ⇒ 40s）；空闲 `STREAM_PING_INTERVAL` 发 `event: ping` | AC-S7 / R17 |
| **BR-STR-32** | `_read_json_body` 读预算 = `MGMT_BODY_TIMEOUT`（5s，env）：仅**读体**期间生效（读完/异常后 `finally` 恢复原 timeout）；体长上限 64KB；非法 `Content-Length` **不读体**直接 `None` | AC-S7（31s→5s）/ R6 / ADR-011 |
| **BR-STR-33** | 僵尸组回收 `_GROUP_IDLE_TTL = 300s`：`not g.conns and now - max(last_push_ts, created_ts) > TTL` ⇒ 删除（含 TOCTOU 双检，锁序 groups→conns）——**本规则不改动** | AC-S11 / SAD §3.1 |
| **BR-STR-34** | 断线重连语义**不改动**：`_register_conn` + 下一 tick 全量快照 + 组空闲 TTL=300s ⇒ 同 sid 在 1 tick 内重连即收完整快照帧 | AC-S11（§3.1「不改动」） |
| **BR-STR-35** | 慢客户端计量：`_serve_sse` 因**写路径异常退出**（`BrokenPipe/ConnectionReset/OSError`）且退出时队列**非满** ⇒ `stream_slow_client_total++`（正常主动断开亦走异常分支，属**上界估计**；判据细化见 §10#4） | SAD §2.5 C-3 |

---

## 5. 伪代码

### 5.1 模块头部与数据结构

```python
import hashlib                                             # ★ v1.3：_frame_signature
import json
import logging
import queue
import socket
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

from . import config, metrics
from .config import (STREAM_PORT, MAX_STREAM_CONNS, MAX_CODES_PER_SUB,
                     MAX_DEDUP_CODES, MAX_GROUPS, MGMT_BODY_TIMEOUT, STREAM_PING_INTERVAL,
                     STREAM_QUEUE_BYTES_BUDGET, stream_frame_bytes, _trading_tiers,
                     cache_policy)                         # ★ v1.3：_domain_refresh_epoch / tick_interval
# ★ v1.2：VALID_STOCK_CODE 不再引用（码校验走 config.canonical_code）；stream_frame_bytes 新增
from .stock_api import (BATCH_MAX_WORKERS, _prefetch_advance, _prefetch_slice, cached_batch,
                        handle_cls_basic_infos, handle_cls_fundflow, handle_cls_timeline)

log = logging.getLogger('stream')

_FIELD_HANDLERS = {'quote': handle_cls_basic_infos,
                   'fundflow': handle_cls_fundflow,
                   'timeline': handle_cls_timeline}
_FIELD_DOMAINS = {'quote': 'quote', 'fundflow': 'fundflow', 'timeline': 'timeline'}
_STREAM_REFRESH_KEY = 'stream_refresh'
_TICK_BUDGET_FRACTION = 0.8
_PER_FETCH_EST = config.STREAM_PER_FETCH_EST           # ★ v1.3 r5 重标定（默认 0.3）
_FIELD_FETCH_CALLS = {'quote': 2, 'fundflow': 1, 'timeline': 1}   # ★ v1.3：quote = basic + depth
_DEFAULT_FETCH_CALLS = 1
_PUSH_ERROR_BACKOFF_CAP_TICKS = 8
_MGMT_WORKER_RESERVE = 10
_FRAME_BUDGET_ERR = ('subscription frames would exceed the '
                     f'{STREAM_QUEUE_BYTES_BUDGET}-byte stream frame budget')

_groups = {}
_groups_lock = threading.RLock()
_conn_count = 0
_conn_count_lock = threading.Lock()

_frame_bytes_lock = threading.Lock()        # ★ BR-STR-7
_queue_bytes = 0
_group_bytes = {}                           # sid -> 保留中字节
_live_frames = 0
_frame_peak_bytes = 0
_slice_view_lock = threading.Lock()
_last_known = {}                            # ★ v1.2 last-known 结转（受 _last_known_lock）
_last_known_lock = threading.Lock()
_last_group_sweep = 0.0


class SubscriptionGroup:
    def __init__(self, sid, codes, fields):          # BR-STR-1
        self.sid = sid
        self.fields = tuple(fields)
        self.codes = frozenset(codes)
        self.conns = set()
        self.conns_lock = threading.Lock()
        self.last_push_ts = 0.0
        self.created_ts = time.time()

    # ★ v1.2：payload_bytes() 已删除（无引用；帧字节口径 = _Frame.size，跨组估算 = stream_frame_bytes）


class _SSEConn:
    def __init__(self):
        self.q = queue.Queue(maxsize=8)
        self.closed = False


class _Frame:
    __slots__ = ('payload', 'size', 'sid', 'refs')
    def __init__(self, payload, sid):
        self.payload = payload
        self.size = len(payload)
        self.sid = sid
        self.refs = 0
```

### 5.2 帧计费原语 + 预算驱逐（P1-N2 收口）

```python
def _frame_acquire(f):
    """BR-STR-6/7：入队成功 ⇒ refs+1；0→1 时计入队列字节与组字节。"""
    global _queue_bytes, _live_frames, _frame_peak_bytes
    with _frame_bytes_lock:
        f.refs += 1
        if f.refs == 1:
            _queue_bytes += f.size
            _group_bytes[f.sid] = _group_bytes.get(f.sid, 0) + f.size
            _live_frames += 1
            if f.size > _frame_peak_bytes:
                _frame_peak_bytes = f.size
        qb, live, peak = _queue_bytes, _live_frames, _frame_peak_bytes
    metrics.set_gauge('stream_queue_bytes', qb)        # 锁外发布（metrics 叶子锁）
    metrics.set_gauge('stream_frame_distinct', live)
    metrics.set_gauge('stream_frame_peak_bytes', peak)


def _frame_release(f):
    """BR-STR-6/7：逆运算；refs<=0 不动作（幂等，防重复归还）。"""
    global _queue_bytes, _live_frames
    with _frame_bytes_lock:
        if f.refs <= 0:
            return
        f.refs -= 1
        if f.refs == 0:
            _queue_bytes -= f.size
            left = _group_bytes.get(f.sid, 0) - f.size
            if left > 0:
                _group_bytes[f.sid] = left
            else:
                _group_bytes.pop(f.sid, None)
            _live_frames -= 1
        qb, live = _queue_bytes, _live_frames
    metrics.set_gauge('stream_queue_bytes', qb)
    metrics.set_gauge('stream_frame_distinct', live)


def _pop_oldest_frame(conn):
    """BR-STR-10/12：取队首；跳过 None 哨兵（消费掉）；非 _Frame 亦返回（调用方判型）。"""
    while True:
        try:
            f = conn.q.get_nowait()
        except queue.Empty:
            return None
        if isinstance(f, _Frame):
            return f
        if f is None:
            return None            # 哨兵：已消费（连接必为 closed ⇒ handler 经 closed 标志退出）
        return None                # 非 _Frame 旧夹具：不计费、不归还


def _drain_conn_queue(conn):
    """BR-STR-13：排空并逐帧归还；None 哨兵跳过（不计费）。返回归还帧数。"""
    released = 0
    while True:
        try:
            f = conn.q.get_nowait()
        except queue.Empty:
            break
        if isinstance(f, _Frame):
            _frame_release(f)
            released += 1
    return released


def _reserve_for(incoming_len):
    """BR-STR-11/15（修 P2-6）：腾出 incoming_len 字节；从『保留字节最大组的最满连接』丢最旧。
    无可丢 _Frame 的组只加入**本轮排除集 skip**（不逐出其全部字节）。返回丢弃数。"""
    dropped = 0
    skip = set()                                                 # 本轮已确认无可丢 _Frame 的组
    while True:
        with _frame_bytes_lock:
            if _queue_bytes + incoming_len <= STREAM_QUEUE_BYTES_BUDGET:
                return dropped
            sid = max((s for s in _group_bytes if s not in skip),
                      key=_group_bytes.get, default=None)         # ★ P2-6：排除集过滤
        if sid is None:
            return dropped                                       # 本轮无可丢候选（不应发生：B ≥ F_max）
        g = get_group(sid)
        if g is None:
            skip.add(sid)                                        # 组已消失：跳过（**不** pop，防低估）
            continue
        with g.conns_lock:
            conns = sorted(g.conns, key=lambda c: c.q.qsize(), reverse=True)   # 『队列最满的连接』优先
        old = None
        for conn in conns:                                       # 逐连接尝试（哨兵被消费后继续下一个）
            old = _pop_oldest_frame(conn)
            if old is not None:
                break
        if old is None:
            skip.add(sid)                                        # 该组本轮无 _Frame 可丢 ⇒ 仅排除，不逐出字节
            continue
        _frame_release(old)
        metrics.incr('stream_frame_dropped_total')
        dropped += 1
```

> **P2-6 说明**：旧实现 `_group_bytes.pop(sid)` 会把该组**所有**仍有 `refs>0` 的帧字节从组账中抹掉（`_queue_bytes` 仍准确），使后续丢弃选靶**系统性低估**该组保留量、破坏"从保留字节最大组丢最旧"的确定性。改用 `skip` 后组账始终如实反映"该组当前保留的 distinct 帧字节和"。
> **进展保证**：`skip` 每轮至少新增 1 个 sid 且不变量为 `skip ⊆ _group_bytes`；`sid is None` 时返回 ⇒ 循环必然终止（BR-STR-15）。

### 5.3 `_refresh_pool`（分片轮转 + `_` 前缀过滤 + lag）

```python
def _fetches_per_code(fields=None):                                # BR-STR-16 成本模型
    fields = _FIELD_HANDLERS if not fields else fields
    return sum(_FIELD_FETCH_CALLS.get(f, _DEFAULT_FETCH_CALLS) for f in fields)


def refresh_capacity(tick, fields=None):                           # -> (coverage, coverage_codes)
    coverage = max(1, int(_TICK_BUDGET_FRACTION * tick * BATCH_MAX_WORKERS / _PER_FETCH_EST))
    return coverage, max(1, coverage // _fetches_per_code(fields))


def _domain_refresh_epoch(domain, tick, now):                      # ★ v1.3 BR-STR-24b
    """设定 tick 的域（ttl <= tick）⇒ 本轮起点（每拍真回源）；慢域/未知域 ⇒ None（TTL 交错）。"""
    if domain is None:
        return None
    if cache_policy(domain)['ttl'] <= tick:
        return now
    return None


def _call_refresh_handler(handler, codes, deadline, refresh_epoch):   # ★ v1.3 BR-STR-24b
    """epoch 是纯增量 kwarg；仅**调用帧** TypeError 退回 3 参（体内 TypeError 原样上抛）。"""
    if refresh_epoch is not None:
        try:
            return handler(codes, deadline=deadline, refresh_epoch=refresh_epoch)
        except TypeError as exc:
            tb = exc.__traceback__
            if tb is None or tb.tb_next is not None:
                raise                                   # 抛自函数体 ⇒ 真实失败
    return handler(codes, deadline=deadline)


def _resolve_refresh_fields(fields):                               # BR-STR-16b
    if fields is not None:
        wanted = set(fields)
        return [f for f in _FIELD_HANDLERS if f in wanted]
    return _subscribed_fields() or list(_FIELD_HANDLERS)


def _refresh_pool(codes, now=None, fields=None, tick=None, deadline=None):
    """BR-STR-16..24：fresh(slice) ∪ cached(active − slice)；按订阅字段并集刷新。"""
    snapshot = {}
    errors = {}
    active = sorted(codes)                                        # BR-STR-23：稳定序
    n = len(active)
    if n == 0:
        return snapshot                                           # 直调快路径；lag=0 由 _push_once 发布
    fields = _resolve_refresh_fields(fields)                       # BR-STR-16b
    if tick is None:
        tick = tick_interval(fields)                               # ★ v1.3 BR-STR-24c
    if deadline is None:                                           # BR-STR-24：单 tick 共享预算
        deadline = time.time() + _TICK_BUDGET_FRACTION * tick
    epoch_base = time.time() if now is None else now               # ★ v1.3 BR-STR-24b：本轮起点
    coverage, coverage_codes = refresh_capacity(tick, fields)
    fetches_per_code = _fetches_per_code(fields)

    if fetches_per_code * n <= coverage:                           # BR-STR-17：C1（成本加权）
        sl, rest, lag = active, [], 0
    else:                                                          # BR-STR-18：C2 分片轮转
        view = {c: 0.0 for c in active}                            # 临时轮转视图（非成员账）
        sl, _next = _prefetch_slice(view, _slice_view_lock, _STREAM_REFRESH_KEY, coverage_codes)
        _prefetch_advance(_STREAM_REFRESH_KEY, len(sl), n)
        sl_set = set(sl)
        rest = [c for c in active if c not in sl_set]
        lag = -(-n // max(1, len(sl)))                             # ceil(n / |slice|)

    for field in fields:                                           # fresh（≤ coverage 取数次数）
        handler = _FIELD_HANDLERS.get(field)
        if handler is None:
            continue
        if time.time() >= deadline:                                # ★ 超预算 ⇒ 跳过剩余字段
            for code in sl:
                errors.setdefault(code, 'tick_budget_exceeded')
            break
        epoch = _domain_refresh_epoch(_FIELD_DOMAINS.get(field), tick, epoch_base)  # ★ v1.3
        fetched = _call_refresh_handler(handler, list(sl), deadline, epoch)         # BR-STR-24：不传 dropped
        if not fetched:
            continue
        for code, data in fetched.items():
            if not isinstance(code, str) or code.startswith('_'):
                if code == '_errors' and isinstance(data, dict):
                    errors.update(data)                            # ★ S2-1 保留（不作股票项）
                continue                                           # ★ BR-STR-22 / AR-7
            if data is not None:
                snapshot.setdefault(code, {})[field] = data

    if rest:                                                       # cached（无网络）
        for field in fields:
            domain = _FIELD_DOMAINS.get(field)
            if domain is None:
                continue
            for code, data in cached_batch(domain, rest, now=now).items():
                if not isinstance(code, str) or code.startswith('_'):
                    continue                                       # AR-7 同侧防御
                if data is not None:
                    snapshot.setdefault(code, {})[field] = data

    metrics.set_gauge('stream_refresh_lag_ticks', lag)             # BR-STR-21（C1 ⇒ 0）
    if errors:
        snapshot['_errors'] = errors                                # ★ S2-1
    return snapshot


def _carry_forward(snapshot, codes, fields):                       # BR-STR-20b
    """返回 (merged, stale)：把 last-known 旧值补进本 tick 快照；未覆盖的码标 stale。"""
    global _last_known
    stale = set()
    merged = dict(snapshot)
    with _last_known_lock:
        _last_known = {c: _last_known[c] for c in codes if c in _last_known}   # 裁剪到活跃池
        for code in codes:
            row, known = merged.get(code), _last_known.get(code)
            if known is None:
                if row is not None:
                    _last_known[code] = {f: v for f, v in row.items() if v is not None}
                continue
            new_row = dict(row) if row is not None else {}
            carried = False
            for f in fields:
                if new_row.get(f) is None and known.get(f) is not None:
                    new_row[f] = known[f]; carried = True
            if row is None or carried:
                merged[code] = new_row; stale.add(code)
            store = {f: v for f, v in new_row.items() if v is not None}
            if store:
                _last_known[code] = store
            elif code in _last_known:
                del _last_known[code]
    return merged, stale


def _clear_last_known():                                           # 空池清账
    with _last_known_lock:
        _last_known.clear()
```

### 5.4 `_build_frame` / `_broadcast` / `push_loop`

```python
def _build_frame(snapshot, codes, fields):
    """§2.4：全量快照帧（items 覆盖全码 + 元数据）；仅 codes 为空返回 None。"""
    if not codes:
        return None
    errors = snapshot.get('_errors') if isinstance(snapshot, dict) else None
    stale = snapshot.get('_stale') if isinstance(snapshot, dict) else None
    items, missing = {}, []
    for code in sorted(codes):                                     # 确定性帧字节
        entry = snapshot.get(code) or {}
        row = {f: entry.get(f) for f in fields}
        if all(v is None for v in row.values()):
            missing.append(code)
        items[code] = row
    payload = {'ts': int(time.time() * 1000), 'codes_total': len(codes),
               'fields': list(fields), 'items': items,
               'missing': missing, 'missing_count': len(missing)}
    if errors:
        err = {c: errors[c] for c in sorted(errors) if c in items}
        if err:
            payload['errors'] = err
    if stale:
        st = sorted(c for c in stale if c in items)
        if st:
            payload['stale'] = st
            payload['stale_count'] = len(st)
    return json.dumps(payload, ensure_ascii=False, separators=(',', ':'))


_TS_FIELD_PREFIX = b'{"ts":'                                       # ★ v1.3：_build_frame 恒 ts 在前


def _frame_signature(frame):                                       # ★ v1.3 BR-STR-36 去重基
    """`frame` 去掉 build 时的 `ts` 字段后的 blake2b(16) 摘要（ts 每拍都变，不能参与比较）。"""
    data = frame.encode('utf-8')
    if data[:len(_TS_FIELD_PREFIX)] == _TS_FIELD_PREFIX:
        comma = data.find(b',', len(_TS_FIELD_PREFIX))
        if comma != -1:
            data = data[comma + 1:]
    return hashlib.blake2b(data, digest_size=16).digest()


def _broadcast(snapshot):
    """BR-STR-2/9/10/11/13/36：锁外帧构建 + 组级去重 + distinct 计费 + 确定性丢弃。"""
    now = time.time()
    with _groups_lock:
        groups = list(_groups.values())                            # ① 快照即释放
    for g in groups:
        codes, fields = g.codes, g.fields                          # ★ 无锁读（frozenset/tuple）
        with g.conns_lock:
            conns = list(g.conns)                                  # ② 快照即释放
        if not conns:
            continue                                               # BR-STR-3 僵尸组
        live = [c for c in conns if not c.closed]                  # ★ v1.2：先滤 closed
        if not live:
            continue
        payload = _build_frame(snapshot, codes, fields)             # ★ 锁外（CPU 重）
        if payload is None:                                        # 仅 codes 为空
            continue
        sig = _frame_signature(payload)                            # ★ v1.3 BR-STR-36
        newcomers = [c for c in live if not c.sent_any]
        if sig == g.last_sig and not newcomers:
            continue                                               #   内容未变且全员已收到 ⇒ 不发
        targets = live if sig != g.last_sig else newcomers
        frame = _Frame(payload, g.sid)
        _reserve_for(frame.size)                                   # BR-STR-11 先腾位
        sent = False
        for conn in targets:
            if conn.closed:
                continue
            _frame_acquire(frame)                                  # ★ BR-STR-9：先计费后入队
            try:
                conn.q.put_nowait(frame)
            except queue.Full:
                old = _pop_oldest_frame(conn)                      # BR-STR-10 丢最旧
                if isinstance(old, _Frame):
                    _frame_release(old)
                    metrics.incr('stream_frame_dropped_total')
                try:
                    conn.q.put_nowait(frame)
                except queue.Full:
                    _frame_release(frame)                          # 未入队 ⇒ 撤销计费
                    continue
            conn.sent_any = True
            sent = True
            if conn.closed:                                        # ★ BR-STR-13 竞态兜底
                _drain_conn_queue(conn)                            #   put 后连接已销毁 ⇒ 立即回收本帧
        if sent:                                                   # ★ v1.3：仅真正发送时刷新
            g.last_sig = sig
            g.last_push_ts = now


def _tick_sleep_seconds(t0, tick, now):                            # BR-STR-27 整 tick 网格
    k = int((now - t0) // tick) + 1
    if k < 1:
        k = 1
    return max(t0 + k * tick - now, 0.0)


def _push_once(t0=None, tick=None):                                # ★ v1.3 BR-STR-24c：tick 由 push_loop 下传
    """单轮：清扫 → 取活跃 (codes, fields) → 刷新 → 结转 → 广播 → 计时 → 返回 sleep。"""
    global _last_group_sweep, _last_round_idle, _first_refresh_done
    t0 = time.time() if t0 is None else t0
    now = time.time()
    if now - _last_group_sweep >= 60:
        _sweep_idle_groups(now)
        _last_group_sweep = now
    codes, fields = _active_targets()                              # ★ 一次持锁同读
    _last_round_idle = not codes                                   # ★ v1.3 BR-STR-38（决定本轮 sleep 可否打断）
    cold_first = False
    if tick is None:                                               # 直调者（测试/工具）：自算
        tick = tick_interval(fields)
    if codes:
        cold_first = not _first_refresh_done                       # ★ v1.3 BR-STR-37（仅豁免一轮）
        _first_refresh_done = True
        snapshot = _refresh_pool(codes, now, fields, tick=tick)
        snapshot, stale = _carry_forward(snapshot, codes, fields)  # ★ P1-4 结转
        if stale:
            snapshot['_stale'] = stale
        _broadcast(snapshot)
    else:
        metrics.set_gauge('stream_refresh_lag_ticks', 0)           # ★ 空池 lag=0（唯一生产发布点）
        _clear_last_known()
    duration = time.time() - t0
    metrics.set_gauge('stream_tick_duration_ms', round(duration * 1000, 2))
    if not cold_first and duration > _TICK_BUDGET_FRACTION * tick:  # ★ v1.3：冷首轮豁免 degraded
        metrics.incr('stream_tick_degraded_total')
    if not cold_first and duration >= tick:                        # ★ v1.3：冷首轮豁免 slip
        metrics.incr('stream_tick_slip_total')
    return _tick_sleep_seconds(t0, tick, time.time())


def push_loop():
    """BR-STR-25..28 + BR-STR-38：tick 网格 + 异常指数退避 + 空闲可唤醒等待。"""
    global _idle_sleeping, _wake_pending
    consecutive = 0
    tick = tick_interval()                                         # 冷启动种子（尚无活跃需求 → L1）
    while True:
        with _wake_lock:                                           # 每轮顶部清账（陈旧请求不得唤醒后续活跃 sleep）
            _wake_event.clear()
            _wake_pending = False
        t0 = time.time()
        idle = False
        try:
            tick = tick_interval(_subscribed_fields())             # ★ v1.3 BR-STR-24c：一轮一次
            delay = _push_once(t0, tick=tick)
            idle = _last_round_idle
            consecutive = 0
        except Exception as e:
            consecutive += 1
            log.error(f'[stream] push_loop error (x{consecutive}): {e}')
            spans = min(2 ** (consecutive - 1), _PUSH_ERROR_BACKOFF_CAP_TICKS)
            backoff = spans * tick - (time.time() - t0)
            delay = max(backoff, _tick_sleep_seconds(t0, tick, time.time()))
        if delay <= 0:
            continue
        if not idle:
            time.sleep(delay)                                      # 活跃轮：硬 grid sleep（无连发保证）
            continue
        with _wake_lock:                                           # 空轮：可打断等待
            _idle_sleeping = True
            if _wake_pending:                                      # 闭合"读 targets → 标记 idle"窗口
                _wake_event.set()
        try:
            _wake_event.wait(delay)
        finally:
            with _wake_lock:
                _idle_sleeping = False
```

### 5.5 `_serve_sse` / `_release_conn`（生命周期收口）

```python
def _release_conn(conn=None):
    """BR-STR-13/30：连接摘除的唯一收口——先排空归还字节，再减计数（幂等）。"""
    global _conn_count
    if conn is not None:
        _drain_conn_queue(conn)
    with _conn_count_lock:
        if _conn_count > 0:
            _conn_count -= 1


def _serve_sse(self, sid):
    g = get_group(sid)
    if g is None:
        self._send_json(404, {'error': 'subscription not found'})
        return
    conn = _SSEConn()
    if not _register_conn(conn):                                    # BR-STR-30 → 503
        metrics.incr('http_503_total')                              # ★ v1.2：503 全端口口径
        self._send_json(503, {'error': 'too many stream connections'})
        return
    with g.conns_lock:
        g.conns.add(conn)
    with _groups_lock:                                              # ★ P2-7：销毁 vs 注册 复检
        alive = _groups.get(sid) is g
    if not alive:                                                   # 组已被 destroy_group 摘除 ⇒ 收口
        conn.closed = True
        with g.conns_lock:
            g.conns.discard(conn)
        _release_conn(conn)                                         # 排空（无帧）+ 减计数，避免永久占用
        self._send_json(404, {'error': 'subscription not found'})
        return
    _wake_push_loop()                                               # ★ v1.3：需求刚变活跃 ⇒ 打断空闲等待
    stalled = False
    try:
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('Connection', 'close')                     # ★ v1.2：流结束即关连接
        self.end_headers()
        self.connection.settimeout(STREAM_PING_INTERVAL * 2)        # BR-STR-31：40s
        while not conn.closed:
            try:
                f = conn.q.get(timeout=STREAM_PING_INTERVAL)
            except queue.Empty:
                self.wfile.write(b'event: ping\ndata: {}\n\n')
                self.wfile.flush()
                continue
            if f is None:
                break                                               # 唤醒哨兵（不计费）
            frame = f.payload if isinstance(f, _Frame) else f
            try:
                self.wfile.write(b'event: quote\nid: '
                                 + str(int(time.time() * 1000)).encode()
                                 + b'\ndata: ' + frame.encode('utf-8') + b'\n\n')
                self.wfile.flush()
            finally:
                if isinstance(f, _Frame):
                    _frame_release(f)                               # BR-STR-14：出队消费归还
    except (BrokenPipeError, ConnectionResetError, OSError) as exc:
        stalled = True                                              # 写阻塞/超时或对端断开
    finally:
        conn.closed = True
        with g.conns_lock:
            g.conns.discard(conn)
        if stalled and not conn.q.full():                           # BR-STR-35 / §10#4
            metrics.incr('stream_slow_client_total')
        _release_conn(conn)                                         # ★ 排空 + 减计数
        # ★ v1.2：流已结束，禁止 handle() 再次进入 handle_one_request 阻塞在
        #   rfile.readline()（最长 40s），否则钉住池 worker 与 _inflight 槽
        self.close_connection = True
```

### 5.6 组 CRUD（`MAX_GROUPS` 校验）

```python
def create_group(codes, fields):
    if not codes:
        return None, 'codes required'
    if len(codes) > MAX_CODES_PER_SUB:
        return None, f'too many codes (max {MAX_CODES_PER_SUB})'
    try:
        g_fields = tuple(_valid_fields(fields))                     # ★ BR-STR-29c fail-closed
    except (ValueError, TypeError) as exc:
        return None, str(exc)
    seen, clean = set(), []
    for c in codes:                                                 # ★ BR-STR-29e canonical_code
        code = config.canonical_code(c)
        if code is None:
            return None, f'invalid stock code: {c}'
        if code not in seen:                                        # 归一去重（折叠之后）
            seen.add(code)
            clean.append(code)
    with _groups_lock:
        if len(_groups) >= MAX_GROUPS:                              # ★ BR-STR-29
            return None, f'too many groups (max {MAX_GROUPS})'
        total = len(_deduped_codes_unlocked()) + len(clean)
        if total > MAX_DEDUP_CODES:
            return None, f'pool would exceed {MAX_DEDUP_CODES} codes'
        # ★ BR-STR-29b：跨组帧工作集 + 单帧余量（P1-4 准入 cap）
        incoming = stream_frame_bytes(len(clean), len(g_fields))
        projected = _projected_frame_bytes_unlocked() + incoming
        largest = max(_max_group_frame_bytes_unlocked(), incoming)
        if projected + largest > STREAM_QUEUE_BYTES_BUDGET:
            return None, _FRAME_BUDGET_ERR
        sid = _new_sid()
        group = SubscriptionGroup(sid, clean, g_fields)              # 局部引用（防 KeyError）
        _groups[sid] = group
    _wake_push_loop()                                                # ★ v1.3：新订阅不等基线 tick（锁外）
    return sid, None


def patch_group(sid, add, remove):
    add, remove = add or [], remove or []
    norm_add, norm_remove = [], []
    for c in add:                                                    # ★ BR-STR-29e
        code = config.canonical_code(c)
        if code is None:
            return False, f'invalid stock code: {c}'
        norm_add.append(code)
    for c in remove:
        code = config.canonical_code(c)
        if code is None:
            return False, f'invalid stock code: {c}'
        norm_remove.append(code)
    with _groups_lock:
        g = _groups.get(sid)                                        # ★ S2-4d：锁内复读组存活
        if g is None:
            return False, 'subscription not found'
        others = _deduped_codes_unlocked() - g.codes
        projected = len(others | (g.codes | set(norm_add)) - set(norm_remove))
        if projected > MAX_DEDUP_CODES:
            return False, f'pool would exceed {MAX_DEDUP_CODES} codes'
        if len(g.codes) + len(norm_add) - len(set(norm_remove)) > MAX_CODES_PER_SUB:
            return False, f'too many codes (max {MAX_CODES_PER_SUB})'
        new_codes = (g.codes | frozenset(norm_add)) - frozenset(norm_remove)   # ★ BR-STR-1 整体替换
        # ★ BR-STR-29b：同 cap（排除自身重定价）
        old_f = stream_frame_bytes(len(g.codes), len(g.fields))
        new_f = stream_frame_bytes(len(new_codes), len(g.fields))
        projected_bytes = _projected_frame_bytes_unlocked() - old_f + new_f
        largest = max(_max_group_frame_bytes_unlocked(exclude_sid=sid), new_f)
        if projected_bytes + largest > STREAM_QUEUE_BYTES_BUDGET:
            return False, _FRAME_BUDGET_ERR
        g.codes = new_codes
    return True, None


def _require_code_list(value):                                       # BR-STR-29d
    if value is None:
        return True, []
    if isinstance(value, list):
        return True, value
    return False, None


def _capacity_meta(codes, fields):                                   # v1.2 容量元数据
    _, coverage_codes = refresh_capacity(tick_interval(fields), fields)   # ★ v1.3：按该组字段集的最短域
    n = len(codes)
    if n <= coverage_codes:
        return {'refresh_capacity_codes': coverage_codes}
    lag = -(-n // coverage_codes)
    return {'refresh_capacity_codes': coverage_codes, 'refresh_lag_ticks': lag,
            'capacity_warning': f'subscription has {n} codes but only '
                                f'{coverage_codes} refresh per tick; frames are '
                                f'sharded and each code lags ~{lag} ticks'}


def destroy_group(sid):
    with _groups_lock:
        g = _groups.pop(sid, None)
    if g is None:
        return False
    with g.conns_lock:
        conns = list(g.conns)
        for conn in conns:
            conn.closed = True
            try:
                conn.q.put_nowait(None)                              # 哨兵唤醒（不计费，BR-STR-12）
            except queue.Full:
                pass                                                 # 满 ⇒ handler 靠 closed + get 超时退出
        g.conns.clear()
    for conn in conns:                                               # ★ BR-STR-13：锁外排空
        _drain_conn_queue(conn)
    log.info(f'[stream] group {sid} destroyed')
    return True
```

### 5.7 `_read_json_body`（5s 读预算）

```python
def _read_json_body(self):
    try:
        length = int(self.headers.get('Content-Length') or 0)
    except (ValueError, TypeError):
        return None
    if length < 0 or length > 65536:
        return None                                                  # BR-STR-32：不读体
    conn = getattr(self, 'connection', None)
    prev = None
    if conn is not None:
        try:
            prev = conn.gettimeout()
            conn.settimeout(MGMT_BODY_TIMEOUT)                       # ★ 5s 读预算（AC-S7）
        except OSError:
            conn = None
    try:
        body = self.rfile.read(length) if length else b''
    except (socket.timeout, TimeoutError, OSError):
        return None                                                  # 慢客户端：≤5s 释放线程
    finally:
        if conn is not None:
            try:
                conn.settimeout(prev if prev is not None else self.timeout)
            except OSError:
                pass
    try:
        return json.loads(body.decode('utf-8')) if body else {}
    except Exception:
        return None
```

---

## 6. 错误处理

### 6.1 错误语义矩阵

| 情形 | 触发点 | 响应 / 行为 | 计量 |
|------|--------|------------|------|
| 请求体非 JSON / 读超时 / CL 非法 | `_read_json_body` → `None` | 400 `{"error":"invalid JSON body"}`（或 400 语义等价） | — |
| 请求体非 object | `do_POST` / `do_PATCH` | 400 `{"error":"JSON body must be an object"}` ★ v1.2 | — |
| `codes`/`add`/`remove` 非 list | `_require_code_list` | 400 `{"error":"<key> must be a list"}` ★ v1.2 | — |
| `codes` 缺失/空 | `create_group` | 400 `{"error":"codes required"}` | — |
| 非法码（canonical_code → None） | `create_group` / `patch_group` | 400 `{"error":"invalid stock code: X"}` | — |
| 显式未知字段 | `_valid_fields` → `ValueError` | 400 `{"error":"unknown field: X"}` ★ v1.2 fail-closed | — |
| 单组码数超限 | 同上 | 400 `{"error":"too many codes (max 200)"}` | — |
| 去重池超限 | 同上 | 400 `{"error":"pool would exceed 2000 codes"}` | — |
| 跨组帧工作集超预算（准入 cap） | `create_group` / `patch_group` | 400 `{"error":"subscription frames would exceed …"}` ★ v1.2 | — |
| **组数超限** | `create_group` | **400** `{"error":"too many groups (max 200)"}` ★新增 | — |
| 组不存在 | `patch_group` / `destroy_group` / `get_group` | 404 / `{"deleted": false}` / 404 | — |
| 连接数超限 | `_register_conn` | 503 `{"error":"too many stream connections"}` | — |
| 未注册路径 | `do_*` | 404 `{"error":"not found"}` | — |
| 客户端断开 / 写超时 | `_serve_sse` `except (BrokenPipe, ConnectionReset, OSError)` | 摘除连接、排空队列、计数归还；**线程释放** | `stream_slow_client_total++`（若队列非满） |
| 队列满 | `_broadcast` | 丢该连接最旧帧（保最新）；二次入队失败 ⇒ 本轮跳过该连接 | `stream_frame_dropped_total++`（丢的是 `_Frame` 时） |
| 全局预算超支 | `_reserve_for` | 确定性驱逐最旧帧直至可容纳；**新帧必入队** | `stream_frame_dropped_total++` |
| handler 抛异常 | `_refresh_pool` → handler | **不在本模块兜底**：handler 契约"返回 dict 不抛"（`stock_api` 内部 `build_batch_response` 总函数）；若仍抛 ⇒ `push_loop` 的 `except Exception` 记日志 + `sleep(1)`，**本 tick 无帧**、循环存活 | — |
| `cached_batch` 未知 domain | `stock_api.cached_batch` | 返回 `{}` + warning（不抛） | — |
| `metrics` 调用异常 | metrics fail-safe | 绝不抛，业务不受影响 | — |

### 6.2 降级路径

| 层 | 降级形态 |
|----|---------|
| tick 层 | 耗时超 `0.8×tick` ⇒ `degraded` 计数（**不中断**推送）；超整 tick ⇒ `slip` 计数 + `sleep(0)` 立即下一轮 |
| 刷新层（C2） | 单 tick 只刷 `≤ coverage_codes`；其余码读终点缓存 ⇒ **慢而非停**（warm 码不降级；冷码 ≤ lag tick 内进入） |
| 连接层 | 慢客户端：单连接队列 8 + 丢旧保新 + 全局预算驱逐 ⇒ **不拖垮广播**（AC-E7） |
| 组层 | 僵尸组不构建帧、300s 回收；`destroy_group` 幂等（第二次返回 `false`） |
| 请求层 | 管理端点全部返回结构化 `{"error": ...}`（400/404/503），**不裸断连** |

### 6.3 不变式（可白盒断言）

1. `stream_queue_bytes == Σ_{f: f.refs > 0} f.size`（distinct 计费一次；`_frame_acquire`/`_frame_release` 成对）。
2. `f.refs == 该帧当前被多少连接队列持有`（★ v1.2：**先 acquire 后 put** ⇒ refs 领先队列计数至多 1，且仅存在于"已计费未入队"的有界 in-flight 窗口；二次 `Full` 时 `_frame_release` 回滚）。
3. 任一时刻 `_queue_bytes <= STREAM_QUEUE_BYTES_BUDGET`（`_reserve_for` 在入队前完成）。
4. 无泄漏：任意连接终止路径后，该连接队列贡献的字节被归零（`_drain_conn_queue` 三处收口）。
5. `stream_frame_dropped_total` 只统计**真实 `_Frame`** 被丢弃次数（`None` 哨兵/字符串夹具不计）。
6. `_FIELD_HANDLERS` 返回的 `_errors` **绝不**出现在任何帧的 `items` 中（AR-7）；但 **出现在帧的 `errors` 字段**（且其键 ⊆ `items`）。
7. `ACTIVE 码集为空` 时不广播，且 `stream_refresh_lag_ticks == 0`（`_push_once` 判空 + 发布 0）。
8. `_build_frame` 仅当 `codes` 为空返回 `None` ⇒ 组有码时**每 tick 必产帧**；帧 `items` 键集合 == 组订阅码集（sorted）。
9. 同一码**不同时**出现在 `missing` 与 `stale`；`missing ⊆ items`、`stale ⊆ items`、`errors` 键 ⊆ `items`。

---

## 7. 并发安全

### 7.1 锁清单

| 锁 | 保护对象 | 新增/既有 | 临界区内容 |
|----|---------|----------|-----------|
| `_groups_lock`（RLock） | `_groups` 表 | 既有 | dict 增删查 + 池上限投影 + `g.codes` **整体替换** |
| `g.conns_lock` | `g.conns` | 既有 | set add/discard + `list(g.conns)` 快照 |
| `_conn_count_lock` | `_conn_count` | 既有 | 整数读改写 |
| **`_frame_bytes_lock`** | `f.refs` / `_queue_bytes` / `_group_bytes` / `_live_frames` / `_frame_peak_bytes` | **新增** | **仅整数与 dict 算术 + `metrics.set_gauge`（叶子）**；无 IO、不嵌套其它业务锁 |
| `_slice_view_lock` | 轮转视图 dict（`_prefetch_rotate` 内只读） | **新增** | `list(pool.keys())`（叶锁） |
| **`_last_known_lock`** | `_last_known`（last-known 结转账） | **新增（v1.2）** | **仅 dict 重建/读写 + 值拷贝**；无 IO、不嵌套其它业务锁（叶锁） |
| **`_wake_lock`** | `_wake_event` / `_idle_sleeping` / `_wake_pending` | **新增（v1.3）** | **仅布尔/Event 读改写**；无 IO、不嵌套其它业务锁（叶锁）；`_wake_push_loop` 由任意线程调用 |
| `stock_api._prefetch_cursor_lock` | `_prefetch_cursor['stream_refresh']` | 既有（跨模块） | 游标读写（`_prefetch_slice`/`_prefetch_advance` 内部） |
| `metrics._lock` | 计数/仪表 | 既有（叶子） | 见 `metrics.md` §7 |

### 7.2 锁序纪律（硬约束）

```
允许（唯一）：
  _groups_lock → g.conns_lock                      （CRUD 与 sweep 的 TOCTOU 双检）
  _conn_count_lock → metrics._lock                 （_release_conn 不发布 metrics；仅计数）
  _frame_bytes_lock → metrics._lock                （_frame_acquire/release 发布 gauge）
  _last_known_lock → （无其它锁，叶锁）
  _wake_lock → （无其它锁，叶锁；`_wake_event.wait()` 在锁外）
  _groups_lock / g.conns_lock → （无其它锁）
禁止：
  ✗ 持有 _frame_bytes_lock 时获取 _groups_lock / g.conns_lock / _conn_count_lock（BR-STR-8）
  ✗ 持有 _groups_lock 时调用 _build_frame / put_nowait / _drain_conn_queue（帧构建与 IO 必须在锁外）
  ✗ 持有 _last_known_lock 时获取任何其它锁（叶锁；_carry_forward 只做内存拷贝）
  ✗ 反向锁序（conns → groups）
  ✗ metrics._lock → 任何锁（metrics 为叶子）
```

**关键设计（避免 `conns_lock → _frame_bytes_lock` 嵌套）**：
- `_broadcast` 在 `conns_lock` 内**只取快照**；`put_nowait`/`_frame_acquire`/`_drain_conn_queue` 均在锁外。
- `destroy_group` 在 `conns_lock` 内**只**置 `closed`、投哨兵、`clear()`；`_drain_conn_queue` 在**锁外**循环（§5.6）。
- `_reserve_for` 分两次独立加锁（`_frame_bytes_lock` 选靶 → 释放 → `conns_lock` 取连接快照 → 释放 → `_frame_release`），**全程无嵌套**。

### 7.3 与既有锁的关系

- `_groups_lock` 仍为 **RLock**（CRUD 路径嵌套获取，现状保留）。
- `_frame_bytes_lock` **不进** `_groups_lock → g.conns_lock` 链（C-2 锁序面不被扩大）——SAD §4.2 明令。
- `stock_api` 的域锁/`_fail_ledger_lock` 与本模块**无交叉**：`_refresh_pool` 调用 handler 与 `cached_batch` 时**不持任何本模块锁**（`_broadcast` 的锁也已在帧构建前释放）。

### 7.4 竞态分析（put 与 closed 的确定性收口）

| 竞态 | 场景 | 收口 |
|------|------|------|
| **销毁 vs 入队** | `_broadcast` 已通过 `conn.closed` 检查 → `put_nowait` 之后 `destroy_group` 才置 `closed` 并排空 | 入队后**复检 `conn.closed`** ⇒ 命中则 `_drain_conn_queue(conn)`（BR-STR-13）。**两种时序均被覆盖**：put 早于排空 ⇒ 排空清掉；put 晚于排空 ⇒ 复检清掉 |
| **销毁 vs 注册**（P2-7，v1.1 补） | `_serve_sse` 取得 `g` 后、`g.conns.add(conn)` 之前，`destroy_group` 已 `pop+clear` ⇒ 连接被挂进**已销毁组** | `g.conns.add(conn)` 之后在 `_groups_lock` 下**复检 `_groups.get(sid) is g`**；不成立 ⇒ `conn.closed=True` + `discard` + `_release_conn(conn)`（排空 + 减计数）+ 404 收口。**不变量**：连接绝不会停留在已销毁组中（否则 `closed` 恒 False、handler 阻塞至客户端断开、`_conn_count` 长期占用） |
| 队列满 vs handler 出队 | `Full` → `get_nowait` 恰好空 | `queue.Empty` ⇒ `old=None` ⇒ 不 release、不计数，继续二次 put |
| 哨兵 vs 满队列 | `destroy_group` 的 `put_nowait(None)` 遇满 | `except queue.Full: pass`；handler 靠 `closed` 标志 + `q.get(timeout=PING)` 退出（≤20s，有界；SAD P1-N2③ 已接受） |
| 出队 vs 预算驱逐 | handler `q.get` 与 `_pop_oldest_frame` 并发取同一队列 | `queue.Queue` 自带锁 ⇒ 元素不会被两方同时取出；最坏情况是"该帧被驱逐后 handler 取到下一帧"，不产生重复计费（`_frame_release` 幂等：`refs<=0` 直接返回） |
| 重复 `_drain_conn_queue` | `destroy_group` 之后 handler 的 `finally` 再排空 | 幂等（队列已空 ⇒ 立即返回 0） |
| 游标并发 | `_prefetch_slice`/`_prefetch_advance` 只被 `push_loop` 单线程调用 | 无并发；`_prefetch_cursor_lock` 提供跨模块安全 |

### 7.5 并发正确性依据

1. **不可变组状态 ⇒ 无锁遍历安全**（BR-STR-1/4）：`frozenset`/`tuple` 的迭代不会因 PATCH 抛 `RuntimeError: Set changed size during iteration`（AC-S2 的结构保证）。
2. **帧构建/入队不在组锁内 ⇒ PATCH 与广播互不阻塞**（AC-S2 的 tick 劣化 ≤20%）。
3. **`refs` 读改写全在 `_frame_bytes_lock` 内** ⇒ 100 连接 × 200 tick 后 `refs` 精确（可白盒断言 `sum(refs) == Σ连接队列长度`）。
4. **计费+入队的复合操作（v1.2 次序修订）**：**先 `_frame_acquire`（使 `refs≥1`）再 `put_nowait`**，避免 put 唤醒的 handler 在另一核先 `_frame_release` 时看到 `refs==0` 短路而遗留 ghost frame；最坏窗口是"已计费未入队"（二次 `Full` 时回滚），异常不越过该窗口（无 IO）。
5. **无新增线程**：仍为 1 `push_loop` + 1 stream server 线程（AC-S9 线程总账不变）。

---

## 8. 测试要点（映射 PRD AC）

| 用例 | 步骤 / 断言（精确） | 覆盖 AC |
|------|-------------------|---------|
| **STREAM-T1** 不可变组状态 | `create_group([...])` 后 `isinstance(g.codes, frozenset)` 且 `isinstance(g.fields, tuple)`；`patch_group` 后 `g.codes` **是新的 frozenset 对象**（`id` 变化）；对 `g.codes` 调 `.add` 抛 `AttributeError` | **S2 / A1**（R5） |
| **STREAM-T2** 并发 PATCH 不中断推送 | 500 次并发 `patch_group` + 200 次 `_broadcast` ⇒ 无异常、无迭代中断日志；tick 间隔劣化 ≤20%（对比无并发基线） | **S2** |
| **STREAM-T3** 帧构建无锁 | patch `_build_frame` 记录调用时的锁状态（或注入"帧构建期间 PATCH 可完成"断言）⇒ `_groups_lock` **未被持有**；`_broadcast` 期间 PATCH 的延迟 < 1ms | S2 |
| **STREAM-T4** `_build_frame` 字段过滤 | `_build_frame(snap, frozenset({'sh600519'}), ('quote','timeline'))` ⇒ `items['sh600519']` 含 quote/timeline、不含 fundflow；`snap` 无该码 ⇒ `None`；空 items ⇒ `None` | A1 |
| **STREAM-T5** distinct 帧计费 | 1 组 3 连接 + `_broadcast` ⇒ `snapshot()['stream_queue_bytes'] == len(frame.payload)`（**只计一次**，非 ×3）；`stream_frame_distinct == 1`；`Σ f.refs == 3` | **E5 / E7** / P0-1 |
| **STREAM-T6** release 对称 | 3 连接逐个 `_drain_conn_queue` ⇒ 每次 `stream_queue_bytes` 递减，全排空后为 **0**、`stream_frame_distinct == 0` | E7 / P1-N2② |
| **STREAM-T7** 预算确定性丢弃 | 造 `_queue_bytes` 逼近预算（多组多帧）⇒ 建新帧触发 `_reserve_for`：被丢的是**保留字节最大组的最满连接**的**队首**；新帧**成功入队**（`items` 含最新 `ts`）；`stream_frame_dropped_total` 增量 == 丢弃数 | **A2 / E7**（不丢最新） |
| **STREAM-T8** 单连接队列丢旧保新 | maxsize=8 填满 → `_broadcast` ⇒ 队列仍 8；最旧 `_Frame` 被丢、最新在；被丢帧 `_frame_release`（字节不泄漏） | **A2 / E7** |
| **STREAM-T9** 摘除路径归还 Byte | 连接入队 8 帧 → `destroy_group` ⇒ `stream_queue_bytes` 归零；handler 退出后再 `_drain_conn_queue` 幂等（不出现负值/重复减） | E7 / P1-N2② |
| **STREAM-T10** `None` 哨兵不计费 | `destroy_group` 后 `conn.q.queue` 中的 `None` 不增 `stream_queue_bytes`；`_drain_conn_queue` 遇 `None` 跳过；`stream_frame_dropped_total` **不**因哨兵增加 | P1-N2③ |
| **STREAM-T11** 销毁/入队竞态 | 手工构造：先 `put_nowait(frame)` 再置 `conn.closed` ⇒ `_broadcast` 的复检路径触发 `_drain_conn_queue` ⇒ 字节归零 | §7.4（P1-N2 收口） |
| **STREAM-T12** C1 整池刷新 | `tick=4`、**quote-only**、活跃码 106（`2×106=212 ≤ coverage=213`）⇒ `_prefetch_slice` **未被调用**、`cached_batch` **未被调用**、`stream_refresh_lag_ticks == 0`；handler 收到全部 106 码 | **A3 / E5** |
| **STREAM-T13** C2 分片轮转 | `tick=8`、3 域（`_fetches_per_code=4`）、活跃码 200（`4×200=800 > coverage=426`）⇒ handler 只收到 `≤coverage_codes==106` 码（一次 tick）；`cached_batch` 被调 `len(fields)==3` 次（每字段）且收到其余码；`stream_refresh_lag_ticks == ceil(200/106) == 2` | **AR-1 / A3 / E5** |
| **STREAM-T13b** 字段并集刷新（BUG-P6C-06） | 仅 quote 组 ⇒ `_refresh_pool` 只调 `_FIELD_HANDLERS['quote']` **1 次**、不调 fundflow/timeline；`coverage_codes == 106`（tick=4；= `213 // 2`，非 3 域的 53） | AC-E5（成本模型） |
| **STREAM-T14** 游标推进 | 连续 `ceil(n/coverage_codes)` tick（同一 200 码集、3 域、tick=4 ⇒ 4）⇒ 各切片**互不重叠**且合并 == 全集；再一 tick 回到第 1 片（round-robin）；`_prefetch_cursor['stream_refresh']` 按 `coverage_codes`（=53）递增取模 | AR-1 |
| **STREAM-T15** warm 码帧不降级 | 预置终点缓存（`cached_batch` 返回数据）⇒ C2 下未进切片的码**仍出现在帧中**；冷码（无缓存）不在帧中，进入下一片后出现（≤lag tick） | **A1**（warm 稳态口径） |
| **STREAM-T16** `_` 前缀键不作股票项（AR-7） | 组订阅 `{sh600519, sz000001}`；patch handler 返回 `{'sh600519': {...}, '_errors': {'sz000001': 'upstream_timeout'}}` ⇒ 帧 `items` **键集 == {sh600519, sz000001}**（**不含** `_errors` 键）；`frame['errors'] == {'sz000001': 'upstream_timeout'}` 且其键 ⊆ `items` | **AR-7 / A10**（唯一陷阱点） |
| **STREAM-T17** 帧 ts 单调 + 全码覆盖 | 连续 200 帧 ⇒ `payload['ts']` 非递减（AC-A1）；`payload['codes_total'] == len(g.codes)`；`set(payload['items']) == set(g.codes)`；每行键集 == `set(g.fields)`（无数据 ⇒ `null`）；`missing`/`stale` 与 `missing_count`/`stale_count` 自洽 | **A1** |
| **STREAM-T18** tick 预算基准 | patch `time.sleep` 与 `time.time` 序列（刷新耗时 3s、tick 8s）⇒ `delay == 5s`（= `t0+8-now`），**不是** 8s；`duration > 0.8*8` ⇒ `stream_tick_degraded_total == 1` | **S10 / E5**（R8） |
| **STREAM-T19** slip 计数 | 刷新耗时 9s（> tick 8s）⇒ `stream_tick_slip_total == 1`、`sleep` 未调用（delay=0） | S10 / R8 |
| **STREAM-T20** `MAX_GROUPS` 400 | patch `stream.MAX_GROUPS = 2` ⇒ 建第 3 组返回 `(None, 'too many groups (max 2)')`；HTTP POST ⇒ **400** + `{"error":"too many groups (max 2)"}` | **E7 / A7**（新增失败模式） |
| **STREAM-T21** 连接硬界 | patch `MAX_STREAM_CONNS = 2` ⇒ 第 3 个 `_register_conn` 返回 `False`；HTTP `GET /stream/quote/<sid>` ⇒ **503** | **E7** |
| **STREAM-T22** `_read_json_body` 5s 预算 | 构造 `connection` 为 mock：断言 `settimeout(MGMT_BODY_TIMEOUT)` → read → `settimeout(30)`；read 抛 `socket.timeout` ⇒ 返回 `None` 且 timeout 已恢复；非法 CL ⇒ **不读体**（`read.assert_not_called`）+ **不触碰 `connection`** | **S7**（31s→5s） |
| **STREAM-T23** socket 超时 = PING×2 | patch `STREAM_PING_INTERVAL=20` ⇒ `_serve_sse` 内 `settimeout(40)`（AC-S7 ≤41s） | **S7** |
| **STREAM-T24** 慢客户端隔离 | 1 个不读 socket 的连接 + 300s 推送 ⇒ 其队列 ≤8、`stream_queue_bytes ≤ 8 × 单帧`、进程 RSS 不单调增长；其余连接正常收帧 | **E7 / A2** |
| **STREAM-T25** 僵尸组不建帧 | 无连接组 ⇒ `_build_frame` 未被调用（存量用例 `test_broadcast_skips_zombie_group_frame_build` 保持） | 回归 / E5 |
| **STREAM-T26** 组回收 | `last_push_ts`/`created_ts` 距今 >300s 且无连接 ⇒ 被 `_sweep_idle_groups` 回收；有连接或刚创建 ⇒ 保留 | **S11** / 回归 |
| **STREAM-T27** 断线重连续帧 | 建组 → SSE 连接 → 断开 → 1 tick 内同 sid 重连 ⇒ ≤1 tick 内收到完整快照帧；组被回收后 → 重新 POST 建组 ⇒ ≤1 tick 收帧 | **S11** |
| **STREAM-T28** 管理端点 CRUD | POST 201 / GET 200（`codes` 升序）/ PATCH 200 / DELETE 200 `{deleted:true}`；重复 DELETE ⇒ `{deleted:false}`；未知 sid ⇒ 404 | 回归 / A7 |
| **STREAM-T29** metrics 名合法 | 一轮「建组→SSE→广播→销毁」后 `set(metrics.snapshot()) ⊆ metrics._KNOWN` | **S10 / MET-T8b** |
| **STREAM-T30** 无新增线程 | 模块导入 + `push_loop` 一轮前后 `threading.active_count()` 不因本模块增长（除 `make_stream_server` 的 server 线程） | **S9** |
| **STREAM-T31** 存量用例回归（**需同步修改的 4 条见 §11.1**） | `SubscriptionGroupTests`（除 `fields` 断言）/ `FieldAndFrameTests`（`_build_frame` 调用改 3 参）/ `HttpIntegrationTests` / `BatchShardingTests` / `SSEQueueDropTests`（改 `_Frame.payload` 解包）/ `ReadJsonBodyGuardTests` / `ZombieGroupTests` / `MaybeReconnectThrottleTests` 全绿 | PRD §9 存量基线 |
| **STREAM-T32** 无裸预算字面量 | 扫 `stream.py`：`STREAM_QUEUE_BYTES_BUDGET`/`MGMT_BODY_TIMEOUT`/`MAX_GROUPS`/`STREAM_PING_INTERVAL` 均来自 `config`，无重复数字字面量（`0.8`/`0.3`/`60`/`8` 为**机制常量**，非域 TTL，允许） | R16 精神 / config.md §2.3 |
| **STREAM-T33** `_reserve_for` 不低估组账（P2-6） | 组 G1 持有 2 个 distinct 帧（`_group_bytes[G1] == 2×size`）、其连接队首为 `None` 哨兵；组 G2 有可丢 `_Frame`；令 `_queue_bytes` 逼近预算后调 `_reserve_for(incoming)` ⇒ 断言：①`_group_bytes[G1]` **仍为 `2×size`**（未被整组逐出）；②哨兵被消费、循环终止；③丢弃来自 G2；④`_queue_bytes + incoming ≤ STREAM_QUEUE_BYTES_BUDGET`（新帧必可入队） | **A2 / E7**（修 P2-6） |
| **STREAM-T34** 销毁 vs 注册（P2-7） | 构造 `get_group(sid)` 返回 `g` 后、`_serve_sse` 入组前调用 `destroy_group(sid)` ⇒ 断言：①`_serve_sse` **不阻塞**、返回 404；②`g.conns` 为空；③`_conn_count` 回到调用前值（无长期占用）；④`conn.closed is True` | **E7**（修 P2-7） |
| **STREAM-T35** last-known 结转（v1.2） | 第 1 tick 全码 fresh ⇒ `_last_known` 记录；第 2 tick 令该码既不在 slice 也不在缓存 ⇒ 帧 `items[code]` **含上一 tick 值**、`stale` 含该码、`missing` **不含**；`stale_count == len(stale)`；无历史的新码才进 `missing` | **A1 / P1-4** |
| **STREAM-T36** last-known 有界 + 清账（v1.2） | 池从 2000 缩到 10 ⇒ `_carry_forward` 后 `set(_last_known) ⊆ 新池`；空池 tick ⇒ `_last_known == {}` 且 `stream_refresh_lag_ticks == 0` | **E5 / BUG-P6C-08** |
| **STREAM-T37** 单 tick 预算超支标记（v1.2） | patch `_FIELD_HANDLERS` 使首个字段阶段 `time.time()` 越过 `deadline` ⇒ 帧 `errors` 含 `{code: 'tick_budget_exceeded'}`（对 `sl` 全码）；push 线程**未阻塞** | **S10 / P1-1** |
| **STREAM-T38** 非 list / 非 object 体 → 400（v1.2） | `POST {"codes":123}` ⇒ 400 `codes must be a list`；`POST [1,2]` ⇒ 400 `JSON body must be an object`；`PATCH {"add":true}` ⇒ 400 `add must be a list`；**不抛 TypeError、不断连** | **A7 / P1-2** |
| **STREAM-T39** fail-closed 字段（v1.2） | `POST {"codes":["sh600519"],"fields":["nonsense"]}` ⇒ 400 `unknown field: nonsense`（**不**回退全字段）；`fields` 缺省 ⇒ 全 3 域 | **A7 / S2-4** |
| **STREAM-T40** 准入 cap（v1.2） | patch `STREAM_QUEUE_BYTES_BUDGET` 极小使 `projected + largest` 超限 ⇒ `create_group` 返回 `_FRAME_BUDGET_ERR`、HTTP 400、`_groups` 未增 | **E5 / P1-4** |
| **STREAM-T41** 码归一（v1.2） | `POST {"codes":["600519.SH","SH600519","sh600519"]}` ⇒ 组内**仅 1 码** `sh600519`；`PATCH {"remove":["600519.SH"]}` 命中同一码 | **A7 / P1-6** |
| **STREAM-T42** 容量元数据（v1.2 / v1.3 数值） | 106 码 quote-only（tick=4）⇒ 201 含 `refresh_capacity_codes==106`、无 `refresh_lag_ticks`；200 码 3 域（tick=4）⇒ `refresh_capacity_codes==53`、含 `refresh_lag_ticks(4)` 与 `capacity_warning` | **A7 / P1-4** |
| **STREAM-T43** Connection: close（v1.2） | `_serve_sse` 响应头 `Connection: close`；handler 退出后 `close_connection is True`（下一次 `handle_one_request` 不再阻塞） | **E7 / P1-3** |
| **STREAM-T44** 节拍=最短订阅域（v1.3） | patch `_trading_tiers` 为盘中：`tick_interval(['quote']) == 4`；`tick_interval(['fundflow']) == 8`；`tick_interval(['quote','fundflow']) == min(4,8) == 4`；`tick_interval([]) == _trading_tiers()['L1'] == 8`；`push_loop` 一轮内 `tick_interval` **只被调 1 次**（patch 计数） | **A3 / S10** |
| **STREAM-T45** `refresh_epoch` 每拍真回源（v1.3） | patch `_FIELD_HANDLERS['quote']` 捕获 `refresh_epoch`：quote-only tick=4 下**每 tick 均非 None** 且 == 本轮起点（`now`）；3 域 tick=4 时 fundflow/timeline 收到 `None`（TTL 8 > tick 4，保持交错）；注入仅接受 3 参的 handler ⇒ 仍被调用（调用帧 TypeError 降级）；handler **体内** `raise TypeError` ⇒ 原样上抛且**只执行一次** | BUG-冷启动-01 / BR-STR-24b |
| **STREAM-T46** 帧发送层去重（v1.3） | 两轮快照逐字节相同（仅 `ts` 变）⇒ 第二轮 `_frame_acquire`/`put_nowait` **均未调用**、`last_push_ts` **不刷新**、`stream_queue_bytes` 不变；第二轮内容变 ⇒ 全员重发；存在 `sent_any=False` 的连接且内容未变 ⇒ **仍补发一帧**给该连接（其后 `sent_any=True`），其余连接不重发 | BUG-冷启动-01 / **A1** |
| **STREAM-T47** 空闲唤醒（v1.3） | 空池状态下调 `create_group` / `_serve_sse` ⇒ `_wake_push_loop()` 命中、空闲 `_wake_event.wait` 立即返回（<0.1s，而非整个 L1 基线 tick）；**活跃轮**调 `_wake_push_loop()` ⇒ 本轮仍硬 `time.sleep(delay)`（两个**轮起点**间距 ≥ 1 tick）；唤醒在"读 targets 后、标记 idle 前"到达 ⇒ `_wake_pending` 复查命中（不丢失唤醒） | BUG-冷启动-01 / BR-STR-38 |
| **STREAM-T48** 冷首轮豁免（v1.3） | 进程首个 `codes` 非空轮 duration > tick ⇒ `stream_tick_degraded_total`/`stream_tick_slip_total` **均不增**；第二轮的同类超预算 **照常 +1**；空轮不消费豁免 | BUG-冷启动-01 / S10 |

---

## 9. AC 追溯矩阵

| 本模块设计点（§） | 覆盖 AC |
|------------------|---------|
| `codes→frozenset` / `fields→tuple` / 整体替换（BR-STR-1/4，§5.1/§5.6） | **S2**（主承载）/ **A1** / R5 |
| 锁序 groups→conns + 帧构建/入队锁外（BR-STR-2，§5.4） | **S2**（tick 劣化 ≤20% 的结构保证）/ **E5** |
| distinct 帧引用计数计费 + `_frame_bytes_lock`（BR-STR-5..9，§5.2） | **E5 / E7** / **A2** / P0-1 / P1-N2① |
| 队列满丢最旧保最新（BR-STR-10，§5.4） | **A2 / E7** |
| 全局字节预算 + 确定性驱逐 + 不丢最新（BR-STR-11，§5.2） | **E7 / E5 / A2**（ADR-013） |
| `_reserve_for` 排除集：组账不低估（BR-STR-15，§5.2） | **E7 / A2**（修 P2-6） |
| "销毁 vs 注册"复检（§5.5 / §7.4） | **E7**（修 P2-7） |
| `_drain_conn_queue` 三处收口 + `None` 哨兵不计费（BR-STR-12/13，§5.2/§5.5/§5.6） | **E7** / P1-N2②③ |
| 分片轮转 `|slice| ≤ coverage_codes` + `cached(active−slice)`（BR-STR-16..20，§2.3/§5.3） | **AR-1 / A3 / E5 / S10** |
| **跳过 `_` 前缀键**（BR-STR-22，§5.3） | **AR-7 / A10**（唯一陷阱点） |
| `stream_refresh_lag_ticks` / `stream_tick_degraded_total`（BR-STR-21/26） | **S10 / AR-1** |
| tick 耗时/滑动/预算基准修正（BR-STR-25..27） | **S10 / E5** / R8 |
| `_read_json_body` 5s 预算（BR-STR-32，§5.7） | **S7**（31s→5s）/ R6 |
| socket 超时 = `STREAM_PING_INTERVAL×2`（BR-STR-31） | **S7**（≤41s）/ R17 |
| 慢客户端隔离 + 计量（BR-STR-10/35，§5.5） | **E7 / A2 / S10** |
| `MAX_GROUPS` 400（BR-STR-29，§5.6） | **E7 / A7**（新增失败模式，登记 §10#9） |
| `MAX_STREAM_CONNS` 503（BR-STR-30） | **E7** |
| 僵尸组回收 + 断线重连语义不改（BR-STR-33/34，§5.6/`_sweep_idle_groups`） | **S11** |
| 帧完整/有序（`_build_frame` ts 单调、字段过滤）（§2.4） | **A1** |
| 组状态与池上限（`create_group`/`patch_group` 校验不变） | **A7** |
| 无新增线程/无存储（§1.2/§7.5） | **S9** |
| 全量帧 schema + `missing`/`stale`/`errors` 元数据（v1.2 §2.4 / BR-STR-20b） | **A1 / A2**（可区分"未覆盖"/"无数据"/"上游失败"） |
| last-known 结转 + 空池清账（§5.3 `_carry_forward`） | **A1 / E5**（BUG-P6C-08） |
| 字段并集刷新 + 成本加权 C1（BR-STR-16/16b，§3.3/§5.3） | **E5 / S10**（BUG-P6C-06） |
| 单 tick 共享预算 + `tick_budget_exceeded`（BR-STR-24） | **S10 / P1-1** |
| 准入 cap `projected + largest ≤ budget`（BR-STR-29b，§3.4） | **E5 / A7**（修 P1-4） |
| 码归一 `config.canonical_code`（BR-STR-29e） | **A7**（P1-6） |
| 9 个 metrics 名 ∈ 冻结注册表（§3.5） | **S10** |
| 节拍 = 最短订阅域 tier（BR-STR-24c，§2.2/§5.4） | **A3 / S10**（quote-only 组 4s 推送） |
| `refresh_epoch` 新鲜度下限（BR-STR-24b，§5.3） | **A1 / E5**（每拍真回源，无隔拍旧值；BUG-冷启动-01） |
| 帧发送层去重（BR-STR-36，§2.5/§5.4） | **A1 / A2**（内容未变不发；新连强制补发；BUG-冷启动-01） |
| 空闲唤醒 + 冷首轮豁免（BR-STR-37/38，§5.4） | **A1 / E5 / S10**（冷启动延迟；不掩盖真实劣化） |

> **AC 覆盖核对**：本模块承载 **A1/A2/A3(调度侧)/A7/A10(陷阱点)/E5/E7/S2/S7/S9/S10/S11**；`A6`（批量 1:1）与 `S6`（码级冷却）由 `stock_api` 承载；`E4`（吞吐）由 `server` 与基础层共同承载。

---

## 10. 与 SAD / 现有代码的偏差与歧义标注（不擅自改 SAD）

| # | 项 | SAD / 契约表述 | 本文裁决 | 理由 |
|---|----|---------------|---------|------|
| 1 | **`_build_frame` 签名变更的连带影响** | SAD §2.5 C-1 / ADR-004：签名改 `(snapshot, codes, fields)` | 按 SAD 变更；**存量用例 2 条必须同步改**（§11.1） | 类型即承诺（frozenset/tuple 无锁遍历）；存量用例以 2 参调用（`_build_frame(snap, g)`）需改 3 参 |
| 2 | `fields` 由 `list → tuple` | SAD §2.5 C-1 表（`fields: list → tuple`） | 按 SAD 变更；**存量断言 `assertEqual(g.fields, ['quote','fundflow'])` 必改为 tuple**（§11.1） | `tuple != list`，属预期内的测试同步 |
| 3 | `_broadcast` 入队对象 `str → _Frame` | SAD §4.2（`_Frame{payload,refs}`） | 按 SAD 变更；**存量用例 `SSEQueueDropTests` 的字符串夹具必改为 `_Frame`/解包 `.payload`**（§11.1） | 计费需要持有者对象 |
| 4 | **`stream_slow_client_total` 判据** | SAD §2.5 C-3：*连接被摘除时若其队列**非满**（说明是写阻塞超时而非读取慢）* | **收紧**为「写路径异常退出（`BrokenPipe/ConnectionReset/OSError`）**∧** 退出时队列非满」 | 按 SAD 字面（仅"队列非满"），正常主动断开的连接队列几乎总是非满 ⇒ 指标失去区分度；收紧后仍是**上界估计**（正常断开也走异常分支），**建议编排层确认是否需进一步区分 `BrokenPipe` 与 `socket.timeout`** |
| 5 | 入队后复检 `conn.closed` | SAD 未定义 | 新增：`put_nowait` 成功后若 `conn.closed` ⇒ 立即 `_drain_conn_queue(conn)` | 关闭/入队竞态会使残留帧**永久占用预算**（P1-N2② 的后果）；两种时序均被覆盖（§7.4） |
| 6 | `_reserve_for` 的"保留字节最大的组" | SAD §4.2：*从"当前保留字节最大的组中队列最满的连接"丢弃其最旧帧* | 用 `_group_bytes[sid]`（按 `refs 0→1 / 1→0` 维护的**帧字节和**）作为"组保留字节"，**不逐帧扫描**；无可丢 `_Frame` 的组只加入**本轮排除集 `skip`**（**不** `pop(_group_bytes[sid])`，修 P2-6） | 数学等价（帧只属于一个组）+ O(1) 维护；逐帧扫描每 tick 最坏 O(组×连接×8) 不可接受；整组 `pop` 会把仍有 `refs>0` 帧的组账抹掉 ⇒ 系统性低估、破坏丢弃选靶确定性（v1.0 缺陷） |
| 7 | 分片游标落点 | SAD §2.2 R-6：*复用 `_prefetch_rotate/_prefetch_advance` 的 round-robin 语义*；`_PROGRESS.md` §A.2：*可用 `_prefetch_advance('stream_refresh', ...)`* | 使用 `stock_api._prefetch_slice(view, lock, 'stream_refresh', size)` + `_prefetch_advance('stream_refresh', len(sl), n)`；`view` 为 **临时轮转视图**（`{code: 0.0}`），复用 `_prefetch_cursor['stream_refresh']` | stream 的活跃码集**不是池**（`_active_codes()` 非 `pool` 成员账）；`_prefetch_slice` 只依赖 `list(pool.keys())` + 共享游标 ⇒ 语义等价且不复制游标逻辑。**登记：使用了私有名（stock_api.md §2.7 已明文提供）** |
| 8 | `stream_frame_peak_bytes` 语义 | SAD §2.2 R-4 列"distinct 帧数/**帧平均**/峰值字节" | 注册表冻结（`metrics.md` §3.2）只有 `stream_frame_distinct` + `stream_frame_peak_bytes` 两名 ⇒ `peak` = **历史最大单帧字节**；**"帧平均"无注册名，不实现** | 不得新增 metrics 名（注册表冻结，ADR-010/`metrics.md` §3.2）；总量口径由 `stream_queue_bytes` 承载 |
| 9 | `MAX_GROUPS` 400 | SAD §7.1 P2-N7：**新增对外失败模式**，须编排层记变更日志 + 同步流端口 API 文档 | 已实现 + 登记（§2.1 / §6.1）；**同步权归编排层** | 🟠 STABLE 下端锁定要求显式登记；`§3.1「不增删路径/不改方法」由此获得显式例外` |
| 10 | `_Frame` 归还时点 | SAD §4.2：*handler 出队消费时 `refs−=1`* | 在**写完该帧的 `finally`** 中归还（而非出队瞬间） | 更保守：写阻塞（≤40s）期间该帧仍计入预算，不会低估占用；异常路径由 `finally` 保证不泄漏。**语义与 SAD 一致（"消费时"），时点细化** |
| 11 | tick 观测的两个计数名 | SAD §2.6 表只列 `stream_tick_duration_ms` / `stream_tick_slip_total`；另在 §2.2 R-6 列 `stream_tick_degraded_total` | `slip` = `duration >= tick`（超出整 tick）；`degraded` = `duration > 0.8 × tick` | 二者语义不同（预算超支 vs 已滑动），SAD 未给判据，此处钉死 |
| 12 | `_FIELD_DOMAINS` 显式映射 | SAD/`_PROGRESS.md` 隐含"字段名 == 域名" | 显式建表 `{quote: quote, fundflow: fundflow, timeline: timeline}` | 防未来字段名与域解耦时 `cached_batch` 传错域（静默取空缓存） |
| 13 | 流端口 inflight 上限（**修 P1-4**） | SAD §4.3：流端口 worker = `MAX_STREAM_CONNS+10=110`；SAD §4.2 C-3：`MAX_STREAM_CONNS=100` | `make_stream_server` 构造时**显式传 `max_inflight = MAX_STREAM_CONNS + 10 = 110`**（同时 `max_workers=110`）⇒ `_max_inflight = 110 ≥ 100` | v1.0 口径（`_max_inflight` 塌缩为 `MAX_INFLIGHT(40)`）使 `MAX_STREAM_CONNS=100` 与 `_register_conn` 的 100 阈值沦为**死代码**、AC-E5/E7 不可复现。`BoundedThreadPoolServer` 的 `max_inflight` 形参由 `server.md` §2.7/§10#11 提供；**同一行为变更，两侧同登记、编排层已批准** |
| 17 | **销毁 vs 注册**竞态（新增，P2-7） | SAD 未定义（属既有竞态，非本次引入） | `_serve_sse` 在 `g.conns.add(conn)` 后于 `_groups_lock` 下复检 `_groups.get(sid) is g`；不成立即 `closed` + 摘除 + `_release_conn` + 404（§5.5/§7.4） | 否则连接挂进已销毁组 ⇒ 永不被唤醒、`_conn_count` 长期占用；修法与"销毁 vs 入队"（§10#5）同族 |
| 14 | `SubscriptionGroup.payload_bytes()` | SAD R7：*`payload_bytes = len(codes)×70KB` 仅作估算未参与调度* | **v1.2：已删除该方法**（无引用面；跨组工作集改用 `config.stream_frame_bytes(codes, fields)`）；帧字节的真实口径始终由 `_Frame.size` 承担 | v1.1 的"保留以避免破坏引用面"经核已无引用；且 `stream_frame_bytes` 是含 `fields` 维度的唯一权威 |
| 15 | `coverage` 与 tick / 订阅字段的关系 | SAD §2.1 INV-1b 只给盘中口径（170 / 56） | ★ **v1.3（r5）**：`_PER_FETCH_EST=0.3`、`BATCH_MAX_WORKERS=20` ⇒ `coverage = int(0.8×tick×20/0.3)` **随 tick 线性增长**（tick4 **213** / tick8 **426** / tick120 **6400**）；`coverage_codes` 由**订阅字段**（+tick）决定（tick4 quote-only **106** / 3 域 **53**）。v1.2 的"恒 23"与旧"非盘中 2560/853"口径均作废 | SAD 的 170/56 属旧标定（8 worker + `_PER_FETCH_EST=0.3`）；**登记以防评审按 56/23/853 硬断言**（BUG-P6C-06 + BUG-SSE-DEPTH-01） |
| 16 | `_slice_view_lock` 的用途 | SAD 未涉及 | 每次刷新新建 `view` dict（局部变量）并配一把模块级叶锁传给 `_prefetch_slice` | `_prefetch_rotate(pool, lock, key)` 要求 lock 参数；局部 dict 无并发（仅 `push_loop` 单线程）⇒ 锁仅满足接口契约、临界区纳秒级 |
| 18 | **SSE 帧 schema 扩展**（v1.2） | SAD §2.5 C-1 / §4.2：帧为 `{ts, items}`（items 仅含有数据的码） | 帧体扩为 `{ts, codes_total, fields, items(全码,可 null), missing, missing_count, errors?, stale?, stale_count?}` | 端锁定 🟠 STABLE 下"只增字段/只增语义"：`items[code]` 结构不变，但**新增 null 占位**与元数据——消除"静默省略码导致客户端无法区分未覆盖/无数据/上游失败"。**须编排层记流端口 API 文档变更** |
| 19 | **`_build_frame` 返回 `None` 的条件**（v1.2） | v1.1 口径：`items` 为空 ⇒ `None`（本组本 tick 不发帧） | 仅 `codes` 为空 ⇒ `None`；组有码则**必产帧**（全 null 也发） | 旧口径下"全部码无数据"会不发帧 ⇒ `last_push_ts` 不刷新 ⇒ **活跃组被 `_sweep_idle_groups` 误回收**；且与"全量快照"语义矛盾。僵尸组（无连接）仍由 `_broadcast` 前置跳过 |
| 20 | **last-known 结转**（v1.2） | SAD 未定义（属 v1.0 缺陷：C2 分片下 200 码订阅 >95% 为 null） | 新增 `_last_known` + `_carry_forward`：未刷新但有历史的码带旧值并标 `stale`；每 tick 裁剪到活跃码集（有界） | 使客户端可区分"未刷新（stale）"与"无数据（missing）"；池缩即回收内存，上界 `MAX_DEDUP_CODES` |
| 21 | **容量模型重标定（v1.2 → v1.3 r5 复标定）** | SAD §2.1 INV-1b：`coverage≈170`、`coverage_codes≈56` | **v1.3 最终态**：`_PER_FETCH_EST=0.3`（`config.STREAM_PER_FETCH_EST`）、`BATCH_MAX_WORKERS=20`、`_FIELD_FETCH_CALLS['quote']=2` ⇒ `coverage` 随 tick（213/426/6400）、`coverage_codes` tick4 = **106/53** | v1.2 的 `2.2` 按**连接池前冷路径**定价、高估 ≈16×，把覆盖封在 23 取数（50 码 × 3 域 / 8s 目标不达）。r5 池化后单次 ≈0.14s（139ms p50 / 167ms max），0.3 留 ≈2.2× 余量；`HTTP_POOL_MAX_PER_HOST=24 ≥ BATCH_MAX_WORKERS=20` 保证扇出不排队。**登记以防评审按 56/23 硬断言**（BUG-P6C-06 + BUG-SSE-DEPTH-01） |
| 22 | **`_refresh_pool` 签名扩展**（v1.2） | v1.1：`_refresh_pool(codes, now=None)` | `_refresh_pool(codes, now=None, fields=None, tick=None, deadline=None)` | `fields` = 订阅字段并集（BUG-P6C-06）；`tick` 由调度器一次算好（防 tier 翻转时 C1 门限与派发节拍不一致）；`deadline` = 单 tick 共享预算（P1-1，防 3 字段阶段串行 45s 卡死推送） |
| 23 | **节拍：整 tick 网格 + 异常退避**（v1.2） | SAD §2.6：基准 = 本轮开始；v1.1 无超预算后的网格/退避定义 | `_tick_sleep_seconds`：sleep 到 `now` 之后的下一个网格点（`k=floor((now−t0)/tick)+1`），`_TICK_MIN_SLEEP_FRACTION` **删除**；`push_loop` 异常退避 1/2/4…封顶 8 tick | 旧"超预算后 floor 到 0.25×tick"会产生"2s 连发重复帧 + 前 12–17s 停顿"的双峰；旧固定 `sleep(1)` 会让故障轮退化成 ~1s 自旋、成倍放大上游压力 |
| 24 | **准入 cap + fail-closed 字段 + 请求体形状**（v1.2） | SAD §2.2 R-2 只有 `MAX_GROUPS`；未定义帧工作集 cap / 字段校验 / 体形状 | `projected + largest ≤ budget`（400）；`_valid_fields` 显式未知字段 raise ⇒ 400；`_require_code_list` 非 list ⇒ 400、非 object 体 ⇒ 400 | ① 无帧 cap 时"合法"订阅集会迫使每 tick 逐出他组真帧（P1-4）；② 静默回退全字段使帧字节与上游成本 ×3 且无错误信号（S2-4）；③ 非容器值会让 `TypeError` 泄出 handler（P1-2） |
| 25 | **`payload_bytes()` 删除**（v1.2） | SAD R7 提到 `payload_bytes = len(codes)×70KB` 仅作估算 | **删除**该方法；跨组工作集改用 `config.stream_frame_bytes(codes, fields)` | v1.1 声称"保留方法避免破坏引用面"，实际已无引用；`stream_frame_bytes` 为唯一权威（含 `fields` 维度） |
| 26 | **`Connection: close` + 抑制超时日志**（v1.2） | SAD §4.3 未定义流结束后的连接语义 | `_serve_sse` 发 `Connection: close` 并在 `finally` 置 `close_connection=True`；`log_error` 抑制 `'Request timed out: %r'` | 否则 `handle()` 会再次进入 `handle_one_request` 阻塞在 `rfile.readline()` 达 40s，钉住池 worker 与 `_inflight` 槽；拆除中的连接超时日志是噪声 |
| 27 | **码归一单一权威**（v1.2） | SAD 未指定归一落点 | `create_group`/`patch_group` 走 `config.canonical_code`；**删除**本地 `VALID_STOCK_CODE` 引用 | `600519.SH`/`SH600519`/`sh600519` 折叠为同一码，避免同一股票铸出多个池/缓存/账本键与多次上游取数（P1-6 / S2-4b） |
| 28 | **`_serve_sse` 超限计数**（v1.2） | v1.1 未在流端口计 `http_503_total` | `_register_conn` 失败时 `metrics.incr('http_503_total')` | 与主端口 503 计数口径统一（S10 跨两端口） |
| 29 | **帧发送层去重**（v1.3） | SAD §4.2：同组每 tick 构建一帧广播给全部连接 | 新增 `_frame_signature`（排除 `ts` 的 blake2b(16)）+ 组级 `last_sig` + 连接级 `sent_any`：内容未变且全员已收到 ⇒ **不发**；未首发连接**强制补发** | 冷轮→温轮的两帧到达间隔 = `tick − dur_k + dur_{k+1}`，未变帧制造亚 tick"重复帧"伪影。去重**只减发、不延迟**（变化即发），`last_push_ts` 只在真发送时刷新（僵尸组回收不被去重蒙蔽） |
| 30 | **空闲唤醒**（v1.3） | SAD §4.3 未定义冷启动唤醒 | `_wake_event`/`_idle_sleeping`/`_wake_pending`/`_last_round_idle`；`create_group`/`_serve_sse` 调 `_wake_push_loop()`；**仅空轮等待可打断** | 首个订阅者原需等整个 L1 基线 tick（实测占冷首帧 5.69s/9.87s）；唤醒只缩短**空轮**等待，不破坏"轮起点 ≥ 1 tick"（空轮不发帧） |
| 31 | **`refresh_epoch` 每拍真回源**（v1.3） | SAD §2.1 INV-1b / §2.2 R-6 未定义"TTL==tick 的相位命中" | `_domain_refresh_epoch`：`cache_policy(d)['ttl'] <= tick` 的域以**本轮起点**为新鲜度下限；慢域传 `None` | 设定 tick 的域 TTL==tick，缓存写入晚于轮起点 δ ⇒ 下一拍命中仅 `tick−δ` 龄的条目、有效节拍减半（4s 域退化为 8s）；下限强制真回源 |
| 32 | **`_tick_sleep_seconds` 不变量订正**（v1.3） | v1.1/v1.2 表述"间隔永短于一整 tick"（未区分**轮起点**与**帧到达**） | 真实不变量 = **轮起点 → 轮起点 ≥ 1 tick**；相邻**已发送**帧到达间隔 = `tick − dur_k + dur_{k+1}`，冷→温（`dur_k > dur_{k+1}`）可 **< tick** | 帧在轮**末端**（`_broadcast`）发出；旧措辞已被实测证伪（4s tick 下约 0.6s 间隔）。未变帧现由去重（#29）丢弃 |
| 33 | **冷首轮豁免 degraded/slip**（v1.3） | SAD §2.6 未定义冷启动计数边界 | `_first_refresh_done`：**仅进程首个 `codes` 非空轮**不计 `degraded`/`slip`；空轮不消费豁免；此后超预算照计 | 冷连接池 / 冷 DNS / 冷 sector 是一次性启动成本，非劣化；只豁免一轮 ⇒ 真实劣化不被掩盖 |

---

## 11. 交付自检

- [x] 无 `{例:` 占位符；`_Frame`/预算/coverage/丢弃候选/指标口径均为**实值**
- [x] §3 为 `yaml` 代码块（组/连接/帧 · 模块状态与计费账 · 分片参数 · 预算与丢弃候选 · metrics 口径 · 字段-域映射）
- [x] HTTP 端点清单精确（方法/路径/请求体/201/400×6/404/503）；**新增 400 失败模式已登记**
- [x] 函数签名清单含 `_build_frame(snapshot, codes, fields)` / `_broadcast(snapshot)` / `_refresh_pool(codes, now=None)` / `_release_conn(conn=None)` 等全部变更点
- [x] 业务规则编号 BR-STR-1..35，伪代码直接引用编号
- [x] 关键流程伪代码齐备：计费原语 / `_reserve_for` / `_refresh_pool` 分片 / `_build_frame` / `_broadcast` / `push_loop` / `_serve_sse` / `destroy_group` / `_read_json_body`
- [x] 错误处理矩阵 + 降级路径 + 7 条可白盒断言不变式
- [x] 并发安全：锁清单 + 锁序（`_frame_bytes_lock` 叶锁、不嵌套）+ 竞态分析（put vs closed 双时序 **+ 销毁 vs 注册**）+ 依据
- [x] 测试要点 **48 条**映射 PRD AC（含 AR-7 陷阱点、预算驱逐、竞态、lag、`MAX_GROUPS` 400；v1.1 新增 T33/T34；v1.2 新增 T13b/T35–T43；**v1.3 新增 T44–T48**）
- [x] AC 追溯：A1/A2/A3/A7/A10/E5/E7/S2/S7/S9/S10/S11 主承载
- [x] 与 `stock_api` 跨模块契约逐项对齐（`_PROGRESS.md` §A）：handler 组装体（+`deadline` +**`refresh_epoch`**）/ `cached_batch(domain, rest, now)` / `BATCH_MAX_WORKERS`（=20）/ 轮转原语 / `_` 前缀；`fetch_cls_basic_info` 的 `quote` 客体可含 `depth`
- [x] 偏差 **33 项**全部登记（**不改 SAD / 不改 PRD / 不改 config.md / 不改 stock_api.md**）

### 11.3 v1.2 契约同步对照（P7b · 以代码为准）

| # | 同步项 | 落点 | 与 v1.1 的差异 |
|---|--------|------|---------------|
| 1 | 帧 schema 扩元数据 + items 全码 null 占位 | §2.4 / §1.2 / §6.3 / §9 / T17 | v1.1：`{ts, items}`、仅含有数据的码 |
| 2 | `_build_frame` 仅 `codes` 空 ⇒ `None` | §2.4 / §5.4 / §10#19 | v1.1：`items` 空 ⇒ `None` |
| 3 | last-known 结转 + `stale`/`stale_count` | §2.4 / §3.2 / §4.3 BR-STR-20b / §5.3 / T35·T36 | v1.1：无结转（未覆盖即 null） |
| 4 | `_refresh_pool` 新签名（fields/tick/deadline） | §2.2 / §2.3 / §5.3 / §10#22 | v1.1：`(codes, now=None)` |
| 5 | 字段并集刷新（不再无条件 3 域） | §1.1 / §4.3 BR-STR-16b / §5.3 / T13b | v1.1：固定遍历 `_FIELD_HANDLERS` |
| 6 | 容量重标定 `_PER_FETCH_EST=2.2`、`coverage=23`、`coverage_codes` 23/11/7 | §3.3 / §4.3 BR-STR-16 / §10#21 | v1.1：0.3 / 170 / 56 |
| 7 | C1 门限改 `_fetches_per_code(fields)×n` | §2.3 / §4.3 BR-STR-17 / §5.3 | v1.1：`len(_FIELD_HANDLERS)×n` |
| 8 | lag：C1/空池 ⇒ **0** | §3.5 / §4.3 BR-STR-21 / §5.4 `_push_once` | v1.1：C1 ⇒ 1 |
| 9 | 单 tick 共享 deadline + `tick_budget_exceeded` | §2.3 / §4.3 BR-STR-24 / §6.1 / T37 | v1.1：无 deadline |
| 10 | `_errors` 保留进帧 `errors` | §2.3 / §4.3 BR-STR-22 / T16 | v1.1：`_` 前缀一律丢弃 |
| 11 | 准入 cap `projected + largest ≤ budget`（满配 9→8） | §3.4 / §4.5 BR-STR-29b / §5.6 / T40 | v1.1：无帧预算 cap |
| 12 | `_valid_fields` fail-closed | §1.2 / §4.5 BR-STR-29c / T39 | v1.1：静默 intersect |
| 13 | `_require_code_list` + 非 object 体 → 400 | §2.1 / §2.6 / §4.5 BR-STR-29d / T38 | v1.1：未定义 |
| 14 | 码归一 `config.canonical_code` | §2.1 / §4.5 BR-STR-29e / §5.6 / T41 | v1.1：本地 `VALID_STOCK_CODE` |
| 15 | 201/PATCH 200 增容量元数据 | §2.1 / §2.6 / §5.6 / T42 | v1.1：仅 `{sid, codes, fields}` |
| 16 | `_serve_sse` `Connection: close` + `close_connection=True` + 抑制超时日志 | §2.1 / §2.6 / §5.5 / T43 / §10#26 | v1.1：`keep-alive` |
| 17 | `_broadcast` 先滤 `closed`；`_frame_acquire` **先于** `put_nowait` | §2.5 / §4.2 BR-STR-9 / §5.4 / §6.3#2 / §7.5#4 | v1.1：`put` 后 acquire |
| 18 | `payload_bytes()` 删除 | §3.1 / §5.1 / §10#25 | v1.1：保留 |
| 19 | `_MGMT_WORKER_RESERVE=10` 具名 | §3.3 / §2.2 | v1.1：字面量 10 |
| 20 | `_PUSH_ERROR_BACKOFF_CAP_TICKS=8` + 整 tick 网格 | §3.3 / §4.4 BR-STR-28 / §5.4 | v1.1：`sleep(1)` |
| 21 | `http_503_total` 在 `_serve_sse` 计数 | §3.5 / §5.5 / §10#28 | v1.1：未计 |
| 22 | `_push_once` / `_tick_sleep_seconds` / `_carry_forward` / `_clear_last_known` / `_active_targets` / `_subscribed_fields` / `_projected_frame_bytes_unlocked` / `_max_group_frame_bytes_unlocked` / `_capacity_meta` / `_require_code_list` 新增 | §2.2 / §5 | v1.1：无 |

### 11.4 v1.3 契约同步对照（r5 容量重标定 + 冷启动去重/唤醒 · 以代码为准）

| # | 同步项 | 落点 | 与 v1.2 的差异 |
|---|--------|------|---------------|
| 1 | 节拍 = 最短订阅域 tier：`tick_interval(fields=None)`（quote/depth=L0 盘中 4s；无订阅回落 L1）；`push_loop` 一轮算一次并下传 `_push_once(t0, tick=)` | §1.1#1 / §2.2 / §4.3 BR-STR-24c / §5.4 / §8 T44 | v1.2：`push_loop` 用 `tick_interval()`（恒 L1），`_push_once(t0=None)` |
| 2 | 容量重标定：`_PER_FETCH_EST=0.3`（`config.STREAM_PER_FETCH_EST`）、`BATCH_MAX_WORKERS=20`、`_FIELD_FETCH_CALLS['quote']=2`；coverage 213/426/6400；coverage_codes tick4 quote **106** / 3 域 **53** | §1.1#2 / §3.3 / §4.3 BR-STR-16 / §5.3 / §8 T12·T13·T13b·T14·T42 / §10#15·#21 | v1.2：2.2 / 8 / quote=1 ⇒ 恒 coverage=23、coverage_codes 23/11/7 |
| 3 | `refresh_epoch` 新鲜度下限：`_domain_refresh_epoch` + `_call_refresh_handler`（纯增量 kwarg；仅调用帧 TypeError 降级） | §1.1#2 / §2.2 / §2.3 / §4.3 BR-STR-24b / §5.3 / §8 T45 / §10#31 | v1.2：无 epoch（设定 tick 的域隔拍旧值） |
| 4 | 帧发送层去重：`_frame_signature` + 组级 `last_sig` + 连接级 `sent_any`；`last_push_ts` 仅真发送刷新 | §2.5 / §3.1 / §4.2 BR-STR-36 / §5.4 / §8 T46 / §10#29 | v1.2：每 tick 无条件重发（未变帧也发） |
| 5 | 空闲唤醒：`_wake_event`/`_idle_sleeping`/`_wake_pending`/`_last_round_idle` + `_wake_lock`；`create_group`/`_serve_sse` 调 `_wake_push_loop()` | §1.1#1 / §2.6 / §3.2 / §4.4 BR-STR-38 / §5.4·5.5·5.6 / §7.1·7.2 / §8 T47 / §10#30 | v1.2：仅硬 `time.sleep`（冷首帧等整个基线 tick） |
| 6 | 冷首轮豁免：`_first_refresh_done`（仅一轮不计 degraded/slip） | §3.2 / §4.4 BR-STR-37 / §5.4 / §8 T48 / §10#33 | v1.2：冷首轮照计 degraded/slip |
| 7 | `_tick_sleep_seconds` 不变量订正：轮起点→轮起点 ≥ 1 tick（非帧到达间隔） | §4.4 BR-STR-27 / §5.4 / §10#32 | v1.2：措辞隐含"帧到达间隔 ≥ 1 tick"（已被实测证伪） |
| 8 | 帧契约只增：`items[code].quote` 可含 `depth`（21 字段，L0 同拍） | §2.4 / §1.1#3 / §3.3 | v1.2：quote 值为扁平 basic_info |

### 11.2 v1.1 修订对照（闭环 REV-DES-20260915-002）

| 评审项 | 落点 | 处理 |
|--------|------|------|
| **P1-4**（联动 server） | §2.2 / §10#13 | `make_stream_server` 构造时显式传 `max_inflight=MAX_STREAM_CONNS+10=110` ⇒ `MAX_STREAM_CONNS=100` 与 `_register_conn` 阈值不再是死代码，AC-E5/E7 可复现（行为变更同 `server.md` §10#11，编排层已批准） |
| **P2-6** `_group_bytes` 低估 | §3.4 / §4.2 BR-STR-15 / §5.2 `_reserve_for` / §8 T33 / §9 / §10#6 | 无可丢 `_Frame` 的组只加入**本轮排除集 `skip`**，不再 `pop(_group_bytes[sid])`；`skip` 单调增长 ⇒ 无死循环；组账始终如实 |
| **P2-7** 销毁 vs 注册竞态 | §5.5 `_serve_sse` / §7.4 / §8 T34 / §10#17 | `g.conns.add(conn)` 后在 `_groups_lock` 下复检 `_groups.get(sid) is g`；不成立 ⇒ `closed` + 摘除 + `_release_conn` + 404 |
| **P2-8** 测试清单多列 1 条 | §11.1 | `ZombieGroupTests::test_broadcast_serves_live_group_only` 降级为**可选清理**（非破坏性）；明确真正必改 = **4 条**（§11.1 前 4 行）；`STREAM-T31` 措辞同步为"4 条" |
| **P2-9** `stream_refresh_lag_ticks` owner | §3.5 | owner 对齐 `metrics.md` §3.2：`stream.push_loop`（发布点 `_refresh_pool`） |
| **P2-10** `cached_batch` 域名 | §2.3 | 统一用 `_FIELD_DOMAINS[field]`（消除"字段名==域名"的隐式假设） |

### 11.1 既有测试的必改清单（`tests/test_stream.py`，供 code-developer / tester 依此同步）

| 测试 | 现状 | 必改点 | 理由 |
|------|------|-------|------|
| `FieldAndFrameTests::test_build_frame_maps_only_group_fields` | `_build_frame(snapshot, _groups[g])`（2 参） | 改 `_build_frame(snapshot, g.codes, g.fields)`（3 参） | §10#1 签名变更 |
| `FieldAndFrameTests::test_build_frame_skips_codes_missing_from_snapshot` | `_build_frame({'sz000001': …}, g)`（2 参） | 改 3 参 | 同上 |
| `SubscriptionGroupTests::test_create_group_valid_codes_and_fields` | `assertEqual(g.fields, ['quote','fundflow'])` | 改 `assertEqual(g.fields, ('quote','fundflow'))`（或 `list(g.fields)`） | §10#2 `tuple` |
| `SSEQueueDropTests::test_broadcast_on_full_queue_drops_oldest_keeps_newest` | 队列填 `'frame-{i}'` 字符串；断言 `items` 中含字符串 | 夹具改 `_Frame` 或改断言为 `[f.payload for f in items if isinstance(f, _Frame)]`；`assertNotIn('frame-0', payloads)`；`assertIn('frame-7', payloads)` | §10#3 `_Frame` 包装 |
| `ZombieGroupTests::test_broadcast_serves_live_group_only` | patch `_build_frame` 返回 **bytes** | **可选清理**（改回 `str` 以符 `_Frame.payload` 契约）；**非破坏性**——新 `_broadcast` 下 patch 返回 bytes **仍可通过**（`_Frame.size = len(bytes)`，帧路径不做 `.encode`） | v1.0 误列为"必改"；真正必改的仅 **4 条**（上表前 4 行） |
| `HttpIntegrationTests::test_sse_stream_receives_quote_frame` | 用真实 `_refresh_pool` + patched `_FIELD_HANDLERS` | **无需改**（C1 分支：`len(_FIELD_HANDLERS)=1`、1 码 ⇒ 整池刷新、无 `cached_batch`） | 行为等价 |
| `ReadJsonBodyGuardTests` | `StreamHandler.__new__` + mock `rfile`，仅测非法 CL | **无需改**（非法 CL 分支在触碰 `connection` **之前**返回；且新代码用 `getattr(self,'connection',None)`） | 向后兼容 |
| `MaybeReconnectThrottleTests` | cdp_engine 用例 | **无需改**（`cdp_engine.md` 保证 `_maybe_reconnect` 语义不变） | 交叉引用 |
| `BatchShardingTests` | 60 码走真实 `handle_cls_basic_infos` | **无需改**（`stock_api.md` SA-T23 保证） | 交叉引用 |
| 新增 | — | `STREAM-T*` **48 条** | 本详设 §8 |

> 本文档与 `config.md` v1.1 / `metrics.md` v1.1 / `stock_api.md` v1.0 / `server.md` **v1.2** 共同构成 P6c 优化专项的模块级详设；**stream.py 的编码依赖 `stock_api` 的 `cached_batch`/`_prefetch_slice`/`_prefetch_advance`/`BATCH_MAX_WORKERS` 已就位**（批次 2 已产出），与 `server.py` 无共享文件写冲突（仅 `make_stream_server` 延迟 import `server`）。
>
> **v1.3 修订**：**P7b 契约同步（r5 容量重标定 + 冷启动去重/唤醒 · 以代码为准）**——见 §11.4 对照表（8 组同步项）；§10 偏差扩至 **33 项**；测试要点扩至 **48 条**。**未改代码、未改其他文档**。
>
> **v1.2 修订**：**P7b 契约同步（以代码为准）**——见 §11.3 对照表（22 组同步项）；§10 偏差扩至 **28 项**；测试要点扩至 **43 条**。**未改代码、未改其他文档**。
>
> **v1.1 修订**：闭环 `doc/review/HTTP-SSE层两模块_详细设计评审_专家版.md`（REV-DES-20260915-002）之 P1-4 + P2-6/7/8/9/10；**SAD v1.3 的 7 项钉死项保持全 ✅ 未改动**。

