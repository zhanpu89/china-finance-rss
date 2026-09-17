# task-decomposer 进度（P6c 优化专项 · 详设分解 + P7b 契约同步）

> 会话范围：SAD v1.2 → 模块详设。本文件是**跨 dispatch 断点续传**状态（由 task-decomposer 读写）。
> 编排器上下文见 `_MEMORY_CACHE.md`（本 agent 只读）。

## 当前状态

- 批次 1：**基础层三模块**（config / cache / metrics）→ ✅ 完成（均 v1.1）
- 批次 2：**数据层三模块**（stock_api / market_api / cdp_engine）→ ✅ 完成（均 **v1.1**，已按评审修订）
- 批次 3：**上层两模块**（server / stream）→ ✅ 评审闭环（v1.1）→ ✅ P7b 契约同步（v1.2）→ ✅ v1.3 收尾（`server.md` N1 回退）
- **本次（r5 容量/冷启动契约同步）**：把多轮实现的真实行为**以代码为准**回写 `stream.md`（→ **v1.3**）/ `stock_api.md`（→ **v1.3**）/ `server.md`（→ **v1.4**）（+ 本文件）——**未改代码、未改 SAD/PRD/其他详设**
- 版本（**以各文档头部为准，已核对**）：`config.md` = **v1.4**（前轮）· `cache.md` = **v1.4**（前轮）· `server.md` = **v1.4** · `stream.md` = **v1.3** · `stock_api.md` = **v1.3** · `market_api.md` = **v1.3** · `metrics.md` / `cdp_engine.md` = **v1.2**
- 路径：纯后端（无前端/小程序 → Step 4 跳过）
- 门禁：每份含 9 节（职责/契约/数据结构/业务规则/伪代码/错误处理/并发安全/测试要点/AC 追溯）+ 偏差标注 + 自检；§3 为 yaml 代码块

## ★ r5 契约同步（`stream.md` v1.3 / `stock_api.md` v1.3 / `server.md` v1.4 · 以代码为准）

> 范围：**只改** `doc/detailed/{stream,stock_api,server}.md` + 本文件。**未改代码、未改其他文档。**
> 触发：r5 容量重标定（连接池后重测）+ 冷启动去重/唤醒 + `depth` 域落地后，三份文档仍为旧口径。

### 1. `stream.md` → **v1.3**（8 组同步项 → §11.4；偏差 28→**33**；测试 43→**48**）

| 主题 | 代码实况（`stream.py`） | 同步结论 |
|------|----------------------|---------|
| `tick_interval(fields=None)` | `L584-616`：无域 ⇒ `_trading_tiers()['L1']`；否则 `min(tiers[cache_policy(d)['tier']] for d in domains)` | 节拍 = **最短订阅域 tier**（quote/depth=L0 盘中 **4s**）；`push_loop` 一轮算一次下传 `_push_once(t0, tick=)` → `_refresh_pool(..., tick=)` |
| `_PER_FETCH_EST` | `= config.STREAM_PER_FETCH_EST`（默认 **0.3**） | v1.2 的 2.2 作废 |
| `BATCH_MAX_WORKERS` | `= config.BATCH_MAX_WORKERS` = **20** | v1.2 的 8 作废 |
| `_FIELD_FETCH_CALLS` | `{'quote': 2, 'fundflow': 1, 'timeline': 1}` | quote = basic + depth |
| 容量实值 | `coverage = int(0.8×tick×20/0.3)` | tick4 **213** / tick8 **426** / tick120 **6400**；`coverage_codes` tick4 quote **106** / 3 域 **53** |
| `refresh_epoch` | `_domain_refresh_epoch`（`ttl ≤ tick` ⇒ 本轮起点）+ `_call_refresh_handler`（纯增量 kwarg；仅调用帧 TypeError 降级） | 设定 tick 的域每拍真回源；慢域 `None` 交错 |
| 帧去重 | `_frame_signature`（blake2b 排 `ts`）+ 组级 `last_sig` + 连接级 `sent_any`；`last_push_ts` 仅真发送刷新 | 内容未变不发；未首发连接强制补发 |
| 空闲唤醒 / 冷首轮 | `_wake_event`/`_idle_sleeping`/`_wake_pending`/`_last_round_idle` + `_first_refresh_done`；`create_group`/`_serve_sse` 调 `_wake_push_loop()` | 仅空轮等待可打断；冷首轮不计 degraded/slip |
| 不变量订正 | `_tick_sleep_seconds` 注释（`L1000-1009`） | 真实不变量 = **轮起点→轮起点 ≥ 1 tick**（非帧到达间隔）；帧到达间隔 = `tick−dur_k+dur_{k+1}` |
| 帧契约只增 | `fetch_cls_basic_info` 附带 `result['depth']` | `items[code].quote` 可含 **`depth`（21 字段，L0 同拍）** |
| **⚠️ 发现的口径不符** | §4.2 **BR-STR-9** 原写"**先 `put_nowait` 成功、再 `_frame_acquire`**"，与代码（**先 `_frame_acquire` 后 `put_nowait`**，二次 Full ⇒ `_frame_release` 回滚）及本文件 §2.5/§5.4/§6.3#2/§7.5#4 **自相矛盾** | 已按代码更正 BR-STR-9；`sent_any`/`last_sig`/`depth`/`hashlib`/`cache_policy` 补入数据结构与 import 面 |

### 2. `stock_api.md` → **v1.3**（6 组同步项 → §10#21..26；偏差 20→**26**；测试 29→**39**）

| 主题 | 代码实况（`stock_api.py`） | 同步结论 |
|------|--------------------------|---------|
| `fetch_cls_stock_depth` | `L1053-1102`：`_STOCK_DEPTH_URL?secu_code=…&field=five`；**空 dict / 20 档全 0 ⇒ `None`**；失败非致命（不 raise） | 新增 `depth` 域取数器 + `_depth_store` + `_DEPTH_VALUE_FIELDS` + `_DOMAIN_STORES['depth']` + `_basic_depth_*` |
| `fetch_cls_basic_info` 三阶段 | `L958-1040`：阶段1 basic（致命）/ 阶段2 sector（非致命）/ **阶段3 depth**（非致命，只增 `result['depth']`） | 三阶段；阶段 1/3 传 epoch，阶段 2 留 TTL |
| 空壳防御 | `_basic_info_is_valid` + `_BASIC_INFO_KEY_FIELDS=('secu_name','last_px')` | `code:200` 但全空 / `data:{}` ⇒ **`upstream_error`**（不写缓存、不进阶段 2/3） |
| `upstream_secu_code` | **9 处**调用点（`_announcement_url` / fundflow / timeline / detail / basic p1 / basic p2 / depth / fundflow direct / timeline direct） | URL 构造全量应用；**北交所点号形 `430047.BJ`**；池/缓存/账本键仍 canonical |
| `BATCH_MAX_WORKERS` | `= config.BATCH_MAX_WORKERS` = **20** | v1.2 的 8 作废 |
| `refresh_epoch` | `_call_fetcher`/`_fetch_one`/`_run_batch`/`_process_chunk`/`_handle_cached_batch` + 3 handler 全贯通；终点缓存命中追加 `written >= refresh_epoch` | 全链路；`None` 逐字不变 |
| **⚠️ 发现的口径不符** | ① §5.1 import 块仍含 `socket` / `Request,urlopen` / `VALID_STOCK_CODE`，且 URL 仍写 `secu_code={stock_code}`；代码已迁移 | 已按代码更正 import 面与全部 URL；② 任务清单称"**10 处** x-quote URL"，实为 **9 处** `upstream_secu_code(` 调用点（announcement 签名 URL 被 REST + direct 两处复用） |

### 3. `server.md` → **v1.4**（4 组同步项 → §11.4；偏差 29→**31**；测试 43→**45**）

| 主题 | 代码实况（`server.py`） | 同步结论 |
|------|----------------------|---------|
| `main()` 预热线程 | `L1509`：`threading.Thread(target=warm_transport, daemon=True).start()`（`cache.warm_transport`；主机 `config.warm_hosts()`） | 新增 daemon 线程；**不阻塞启动/`/healthz`，失败静默**（总函数） |
| gzip 协商 | `_accepts_gzip`（`L541-568`，RFC 9110：`gzip;q=0` 拒绝、`GZIP`/`*` 接受）；`_send_text`（`L1249-1283`）gzip + `Vary` | `Vary: Accept-Encoding` 在 **`gzipped or cache`** 时无条件发（含 `cache=False` 的 gzip）；`GZIP_MIN_BYTES=1024`/`GZIP_COMPRESSLEVEL=1` |
| 已核对**无漂移** | 状态码（业务恒 200；`http_503_total` 计数点 3）、`_send_json` 无 `status`、`_json_payload_has_data` 已删、`_cache_age` 用 `urlparse`、`_parse_stock_codes`/`_rekey_batch_response`、4 面板 `quote` 域、longhu `broker_idx` 无条件自增、`request_queue_size=LISTEN_BACKLOG`、`BoundedThreadPoolServer(..., max_inflight=None)` | 与 v1.3 已同步口径一致，仅补 v1.4 两项 + 线程账 +9 |

**本轮销账**：v1.2 遗留的 `stream.md` 容量/去重类偏差、`stock_api.md` 的 import/URL/depth 类偏差、`server.md` 的 warm/gzip 类偏差**全部落笔**。**仍待编排层（不在本 agent 范围）**见下方「跨模块契约同步项」。

## ★ v1.3 收尾契约同步（N1 回退 + AC-S3 裁决 + `_LOCAL_BUDGET` 裁决 · 以代码为准）

> 范围：**只改** `doc/detailed/{server,cache,config,market_api}.md` + 本文件。**未改代码、未改 SAD/PRD/其他详设。**
> 触发：编排层裁决落地后的"消除新一轮漂移"（代码已改，文档是旧口径）。

### 1. N1 回退：业务端点降级恢复 `200 + error 体` → `server.md` **v1.3**（7 组同步项 → §11.3 对照表；偏差 28→**29**；测试仍 43 条，`SRV-T36` 语义反转）

| 主题 | 代码实况（`server.py`） | 同步结论 |
|------|------------------------|---------|
| `_send_json_shape` | `L1141-1154`：`payload = _guard(fn, shape=_JSON_SHAPES[path])` → `self._send_json(payload, write_body=…, cache=cache)`——**无 200/503 判定** | 恒 **200 + 原样 error 体**；v1.2 的"error-only ⇒ 503"**作废** |
| `_json_payload_has_data` | **全仓 0 命中**（已删） | §2.9 内部辅助改为删除标注；§10#24 同步 |
| `_send_json` | `L1136`：`def _send_json(self, data, write_body=True, cache=True)`——**无 `status`** | 签名回落，恒调 `_send_text(200, …)` |
| `http_503_total` 计数点 | **3 处**：`server._reject_503`（L1340）、`/healthz`（L1039）、`stream._serve_sse`（stream.py L1011） | 同步为 **4→3**；`/healthz` 明确为**端点自身语义** |
| 降级体缓存 | `cache=cache`（不再 `and status == 200`） | 降级 JSON **可缓存**（按 `_CACHE_AGE_DOMAINS` 域 TTL） |
| 受影响落点 | — | §1.1#9 / §2.1（yaml + 状态表）/ §2.2 / §2.4 表 / §2.9 / §2.10 / §4.1 BR-SRV-5b / §4.5 BR-SRV-21 / §5.2 / §5.8（伪代码 + 表）/ §6.1 / §8 T24·T36 / §9 / §10#18·#24·#29 / §11.1·§11.3 |

### 2. AC-S3 裁决：探测预算封顶 5s → `cache.md` **v1.3** / `config.md` **v1.3** / `market_api.md` **v1.3**

| 文档 | 代码实况 | 同步条数 / 落点 |
|------|---------|----------------|
| `cache.py` | `L84` `_PROBE_BUDGET_CAP = 5.0`；`L154-174` `_probe_budget`：`budget=PROBE_TIMEOUT`，`while steps>0 and budget < _PROBE_BUDGET_CAP: budget = min(budget*2, _PROBE_BUDGET_CAP)`；`L177-187` `_fetch_budget`：无条目 / 已老化 ⇒ **`REQUEST_TIMEOUT`**（不经阶梯） | **6 处**：§1 头部+§1.1#1 / §2.1 四段式+行为表 / §2.5 兼容清单（新增 `_PROBE_BUDGET_CAP` 行 + 更正 `_probe_budget` 行）/ §3.1+§3.5 / §4.2 BR-CACHE-8·22 / §5.1 伪代码 / §8 T-CACHE-4·4c·4d·21 / §9 / §10#11 重写 + **#18 新增** / §11 |
| `config.py` | `L38` `PROBE_TIMEOUT = int(os.getenv('PROBE_TIMEOUT', '2'))`（**不变**）；封顶常量在 `cache` 侧，**未注册 env** | **2 处**：§2.3 `PROBE_TIMEOUT` 行脚注 + §10#18 新增 + §11（`PROBE_TIMEOUT` 默认值/env 面**零变更**） |
| `market_api.py` | 无改动；影响仅经 `cache._effective_timeout` 传导 | **1 处**：BR-MKT-11 封顶更正为 `_PROBE_BUDGET_CAP`（故障期 margin 单次回源 ≤5s；冷期/老化期 10s）+ §10#9 新增 + §12 变更记录 |

**推导（已写入 `cache.md` §10#11）**：持续黑洞稳态 ≈ `5s 探测 + 5s NEG_TTL = 10s` 周期，慢请求占比 ≈50% ⇒ **P95 ≈ 5s**（**与请求密度无关**，v1.2 的"低密度 ⇒ P95≈10s"退化消失）；单请求 ≤15s（AC-E2）恒成立。

### 3. `_LOCAL_BUDGET` 裁决（正式反转 REV-DES-15 裁决②）→ **本 agent 范围内无待改项**

- **代码实况**：`stock_api.py:81` `_LOCAL_BUDGET = '__local_budget__'`；`_process_chunk` 命中哨兵 ⇒ **不调 `_fail_ledger_record_failure`**（`L490`/`L500` 的分支互斥）。
- **文档实况**：`stock_api.md` **已在 v1.2（P7b）同步**——头部修订②、§1.1、§2.3 脚注、§3.1b、§4.2 BR-SA-34、§8 SA-T25/SA-T30、§10#14 均已是"**不入冷却账**"新口径。
- ⇒ **`stock_api.md` 无待同步项**（本项闭环）。**在范围内的四份文档不含该口径的旧表述**（`server.md` 只透传 `dropped`；`cache.md` BR-CACHE-23 的"本地等待预算 ≠ 上游失败"与新口径同源一致）。
- ⚠️ **仍需编排层承接（非本 agent 范围）**：SAD §2.3 D-6 的 `_fail_ledger` 条目 + PRD 侧"预算耗尽计入冷却账"的表述回改（`stock_api.md` §10#14 已登记）。


## P7b 契约同步摘要（`server.md` → v1.2（★ 后由 v1.3 / N1 修订两处）/ `stream.md` → v1.2 · 以代码为准）

> ★ **历史快照（v1.2 时点）**：下表"error-only ⇒ 503 / `_send_json(..., status=200)`"两条**已由 v1.3 / N1 回退**（见「v1.3 收尾契约同步」§1）；**"容量模型 `2.2` / `coverage=23` / `coverage_codes` 23·11·7"已由 r5 复标定为 `0.3` / 213·426·6400 / tick4 **106·53**，且节拍改为最短订阅域 tier**（见上「r5 契约同步」§1 / `stream.md` §11.4）；其余条目仍有效。

> 依据：各批次落地 `>>DOC_SYNC` 标记。**仅改 `doc/detailed/{server,stream}.md` + 本文件**；未改代码、未改其他文档。

### stream.md（22 组同步项 → §11.3 对照表；偏差 17→28；测试 34→43）

| 主题 | 同步结论（代码实况） |
|------|--------------------|
| 帧格式（对外契约） | `{ts, codes_total, fields, items(全码, 可 null), missing, missing_count, errors?, stale?, stale_count?}`；`_build_frame` **仅 `codes` 为空**返回 `None` |
| last-known | `_carry_forward`/`_last_known`/`_clear_last_known`：未刷新码带旧值并标 `_stale`；池缩即裁剪 |
| `_refresh_pool` | 新签名 `(codes, now=None, fields=None, tick=None, deadline=None)`；按**订阅字段并集**刷新（`_subscribed_fields`/`_active_targets`/`_resolve_refresh_fields`）；超预算跳过剩余字段并标 `tick_budget_exceeded` |
| **容量模型（关键数值）** | ~~`_PER_FETCH_EST=2.2`、`_FIELD_FETCH_CALLS['quote']=1` ⇒ coverage=23；coverage_codes 1/2/3 域 → 23/11/7~~ **（v1.2 历史；r5 复标定见上「r5 契约同步」§1：`0.3` / quote=2 / 213·426·6400 / tick4 106·53）**；C1 门限 = `_fetches_per_code(fields)×n ≤ coverage` |
| 节拍 | 整 tick 网格滑移 `k=int((now−t0)//tick)+1`；异常退避 1/2/4…封顶 8 tick；**`_TICK_MIN_SLEEP_FRACTION` 已删** |
| lag gauge | 空池发布 0（`_push_once` 空池分支）；C1 ⇒ 0；C2 ⇒ `ceil(n/|slice|)` |
| 准入 | `projected + largest ≤ budget`（单帧余量 ⇒ 满配组容量 **9→8**）；超限 400 `_FRAME_BUDGET_ERR`；`MAX_GROUPS=200` 超限 400 |
| 字段/码校验 | `_valid_fields` **fail-closed**（显式非法字段 → 400）；码归一走 `config.canonical_code`（本地 `VALID_STOCK_CODE` 引用已删） |
| HTTP | POST/PATCH 非 list → 400、非 object body → 400；201/PATCH 200 增 `refresh_capacity_codes`/`refresh_lag_ticks`/`capacity_warning`；`patch_group` 锁内复读组存活；`do_PATCH` 容忍 `None` → 404 |
| SSE/收口 | `Connection: close` + `close_connection=True`；`log_error` 抑制超时日志；`_broadcast` 先滤 `closed`；`_frame_acquire` **先于** `put_nowait`；`SubscriptionGroup.payload_bytes()` **已删** |
| 端口 | `make_stream_server` 具名 `_MGMT_WORKER_RESERVE=10`（`max_workers = max_inflight = MAX_STREAM_CONNS+10`）；`_serve_sse` 超限计 `http_503_total` |

### server.md（16 组同步项 → §11.1 对照表；偏差 17→28；测试 35→43）

| 主题 | 同步结论（代码实况） |
|------|--------------------|
| **error-only ⇒ 503** ⚠️ **已于 v1.3 / N1 回退** | ~~新增 `_json_payload_has_data`；触发面 = 4 CDP 面板 / hotplate 全分区失败 / margin `_error` / guard 捕获体 ⇒ **503**（原 200）并计 `http_503_total`~~。**现口径（v1.3，以代码为准）**：`_json_payload_has_data` **已删除**；`_send_json_shape` **恒 200 + 原样 error 体**（降级体 `cache=cache` ⇒ 按域 TTL 可缓存）；`_send_json` **无 `status` 形参**；`http_503_total` 计数点 **4→3**（`_reject_503` / `stream._serve_sse` / `/healthz`）；`/healthz` 的 503 属**端点自身语义**，不构成业务端点先例。`_send_json_shape(path, fn)` 表驱动派发不变。**`/cls/plate` 恒 200**（同前） |
| `/healthz` | `BoundedSemaphore(MAX_HEALTH_INFLIGHT)` + `_HealthBatch`（`task_done` + **`settle()`**）；先建账再调用 + `except BaseException: settle(); raise`；`_run_health_checks(base_url, batch=None)`；payload 缺 `status` 或含 `error` ⇒ **503**（计入 `http_503_total`） |
| 扇出 | `_fanout_executor(_FANOUT_MAX_WORKERS=3)` + `_fetch_concurrent` 等待受 **`_FANOUT_WAIT_BUDGET=REQUEST_TIMEOUT`** 界（超期 cancel + `FetchError('upstream_timeout')`） |
| `_guard` 全路由 | 14 JSON（表驱动）+ 5 RSS + `/healthz`；`_JSON_SHAPES` + `_PANEL_HANDLERS` + `_JSON_DISPATCHED_PATHS` 导入期断言 |
| feed/plate | feed 双检保留（`ttl` 在二次 get 仍 miss 后求值）；plate stagger 保留（`_plate_ttls`） |
| `_base_url`/`_cache_age` | `PUBLIC_BASE_URL` 优先；否则 Host 格式校验 + `Vary` + `Cache-Control: private`；`_cache_age` 用 `urlparse(self.path).path` |
| **面板 cache-age（新发现漂移）** | 4 面板已注册到 `_CACHE_AGE_DOMAINS` 的 **`quote`** 域（8/120），**非** `_DEFAULT_AGE_DOMAIN('f10')` 的 300 —— v1.1 文档口径已更正 |
| **码归一（新发现漂移）** | `/stock/*` 走 `_parse_stock_codes`（canonical 折叠去重）+ `_rekey_batch_response`（响应键回原拼写）；截断按归一后码数；非法码值 ⇒ 逐码 `null`（**非** 400），400 仅缺/空 `?code=` |
| **margin 400（新发现漂移）** | `/market/margin` 非法 `market` ⇒ **400**（`VALID_MARKETS` 前置校验，guard 之前） |
| 其他 | ~~`_send_json(..., status=200)`~~（**v1.3 / N1 撤销**：无 `status`，恒 200）；`do_GET`/`do_HEAD` 断连捕获扩为 `OSError`；`request_queue_size = LISTEN_BACKLOG`；longhu `broker_idx` **无条件自增** + 错位告警、encoding 取自 `cache_policy('longhu')['encoding']`；import 面更正 |

### 销账（v1.1 遗留「编排层同步项」）

1. ✅ **`CACHE_TTL` 同批删除**：`config.py` 已无 `CACHE_TTL`；`server.py` 的 healthz `cache_ttl` / feed expires / 启动日志全部改读 `cache_policy('feed')['ttl']`（grep 0 命中）。
2. ✅ **`canonical_code` 落地**：`config.canonical_code` 已是唯一码归一权威；`stream.py` 删除本地 `VALID_STOCK_CODE` 引用，`server.py` 新增 `_parse_stock_codes`/`_rekey_batch_response`。
3. ⏳ 仍待编排层（**不在本 agent 范围**）：`feeds[].status` 3 处取值 + 首页 CDP 列的 API.md/变更日志同步；`POST /stream/subscriptions` 的 `MAX_GROUPS=200` 超限 400 与 **v1.2 新增的「帧预算 cap 400 / 面板 max-age 8·120 / margin 400」**（★ v1.3：**剔除 error-only 503——已 N1 回退，业务端点恒 200，无需外部同步**）的对外文档与变更日志同步；SAD 措辞回改（`handle_cls_*` 返回组装 dict；★ 另可选：`_PROBE_BUDGET_CAP=5s` 与 P95 ≈ 5s 口径）。

## 批次 2 交付摘要（数据层三模块，v1.0）

| 模块 | 核心接口变更 | 关键约束落实 |
|------|-------------|-------------|
| `stock_api.py` | 6 码级 `fetch_*(code, deadline=None, ttl=None)`（+3 直连）；`_run_batch/_process_chunk/_handle_cached_batch` → `(results, errors)`；`handle_cls_*(codes, deadline=None, dropped=0) -> dict`（内部 `build_batch_response`）；`_fail_ledger`（码级 120s 冷却，批量+prefetch 共用）；`cached_batch/_prefetch_slice` 新增 | deadline 贯通（R13）、TTL 同源同变量（INV-1a 落点 2）、池淘汰不再 `cache.pop`（P1-1）、删裸 `ttl=15`（Q5）、sector 接 policy |
| `market_api.py` | `fetch_margin(market='99', deadline=None)`；`_MARGIN_CACHE_TTL` → `cache_policy('margin')['ttl']`；`_error` 由自由文本收敛为枚举 kind | R16、`FetchError` 分类 + 防重复计数（BR-MKT-8） |
| `cdp_engine.py` | `page_data(page)`（R18 防御取数，总函数）；重启窗口状态机 `idle/restarting/unavailable` + `restart_window_snapshot()`；`watchdog_restart_skip_reason()`（盘中避让 ADR-012 集中判断）；`cdp_ready()`；`_heartbeat_interval` 改调 `config._is_trading_hours` | R18/R19/R20、AR-12、`cdp_restart_window` metrics |

## 批次 3 交付摘要（上层两模块，v1.0）

| 模块 | 核心接口变更 | 关键约束落实 |
|------|-------------|-------------|
| `server.md` | `_guard(fn, *, shape, requested, dropped, rss_info, feed_url)`（4 shape）；`_JSON_SHAPES`（14 项 + `assert`）；`_handle_stock_batch(parsed, handler, write_body)` 透传 `dropped`；`_get_or_fetch_feed` 双检；`build_health_payload(base_url, check_sources)`（签名不变）；`BoundedThreadPoolServer._max_inflight = MAX_INFLIGHT`；`_cache_age` 接 policy；`_plate_ttls()`；`_send_error(msg, write_body)` | `_guard`×14 JSON + 5 RSS + healthz；feed 双检（miss→per-path lock→**二次 get**→fetch→put）；healthz `BoundedSemaphore(MAX_HEALTH_INFLIGHT=5)` 有界准入（stale 可达）+ check=0 零上游 + 精确 schema（既有 4 键 + `stale`/`metrics`/`policy`/`cdp`）；plate `_STAGGER=max(3, ttl//4)` 三档保留；longhu 走 `fetch_json(encoding='gbk')`×2 URL（L4=300）；dropped 单组装点；503 计数 |
| `stream.md` | `codes→frozenset`、`fields→tuple`；`_build_frame(snapshot, codes, fields)`（**签名变更**）；`_Frame{payload,size,sid,refs}` + `_frame_bytes_lock` + `_frame_acquire/release` + `_reserve_for` + `_drain_conn_queue` + `_pop_oldest_frame`；`_refresh_pool(codes, now=None)` 分片轮转；`_release_conn(conn=None)`；`create_group` 校验 `MAX_GROUPS`；`_read_json_body` 5s | distinct 帧计费（`stream_queue_bytes` = Σ refs>0 帧字节，只计一次）；关闭/入队竞态双时序收口（put 后复检 `closed`）；确定性丢弃（`_group_bytes` 最大组 × 最满连接 × 队首）+ 先腾位后入队（不丢最新）；分片 `|slice| ≤ coverage_codes`（★ v1.0 历史：盘中 56 / 非盘 853；**r5 后为随 tick/字段动态值**，见上「r5 契约同步」§1）游标键 `stream_refresh` + `cached_batch` 并帧 + lag 指标；**跳过 `_` 前缀键（AR-7）**；`MAX_GROUPS` 400 |

## v1.1 修订摘要（数据层三模块，REV-DES-20260915-002）

> 依据 `doc/review/数据层三模块_详细设计评审_专家版.md`（结论 ✅ 通过，P0×0 / P1×2 / P2×10）。**仅改 `stock_api.md` / `market_api.md` / `cdp_engine.md`（+ 本文件）——未动 SAD / PRD / 代码。**

| 项 | 模块 · 位置 | 处理 |
|----|-------------|------|
| **P1 REV-DES-10** | `stock_api.md` §1.3/§1.4/§2.1#3/§5.9 | §1.3 允许列表补 `cdp_engine（page_data）`、禁令移除 `cdp_engine`（限 `page_data`）；§1.3 依赖图补 `stock_api → cdp_engine`；§1.4 补 `cdp_engine.page_data(page) -> dict\|None` 行；§5.1 补 `from .cdp_engine import page_data`；§2.1#3/§5.9 口径统一 ⇒ **编码不再违反自带 layerIsolation** |
| **P1 REV-DES-11** | `market_api.md` §10#1 | **设计不变**（保 `{latest, recent, _error}`）；§10#1 改为裁决回执：「编排层已裁决：设计保持，PRD AC-A5 margin 表述将回改」 |
| REV-DES-12 | `stock_api.md` §5.9 | 抽 `_raise_cdp_unavailable()`（计数 + 抛出），4 处出口收口 ⇒ `upstream_fail_total{cdp_unavailable}` 不再少计 |
| REV-DES-13 | `stock_api.md` §5.2 | `_fetch_rest_json` 捕获**非 FetchError** 时就地计 `upstream_error`（cache 抛出的不重复计） |
| REV-DES-14 | `stock_api.md` §5.2 | `_fetch_rest_json` 前置 `isinstance(raw, dict)`，非 dict ⇒ 计一次 + `FetchError('upstream_error')`（与 market_api 对齐） |
| REV-DES-15 | `stock_api.md` §2.3/§4.2/§10#14、§8 SA-T25 | **采用评审建议②**：保留"预算耗尽计入冷却账"现口径 + 补用例 SA-T25 + §10#14 登记影响（AC-S6 张力）；**不引入内部哨兵**（避免动 SAD 钉死的 `_run_batch (results,errors)`） |
| REV-DES-16 | `stock_api.md` §2.8/§5.11 | `_prefetch_loop` 新增 `per_call_budget`（默认 `REQUEST_TIMEOUT`）；单次调用传 `deadline=min(pass_deadline, now+per_call_budget)`；`_f10_prefetch_loop` 传 `per_call_budget=_PREFETCH_CDP_CALL_TIMEOUT`（lambda 移除，直传 `fetch_cls_f10`） |
| REV-DES-17 | `stock_api.md` §3.4/§4.5/§6.2/§9 | ≤15s 引据由 **AC-S7 → AC-E2**（REST 回源上界）；`_CDP_CALL_TIMEOUT` 引据保留 AC-S7 超时矩阵 |
| REV-DES-18 | `stock_api.md` §5.9/§10#15 × `cdp_engine.md` §2.1/§8/§10#9 | **统一钉死**：全部已导航页 `page_data=None` ⇒ `cdp_unavailable`；仅"有 dict 数据但不匹配"⇒ 返回 `None`。两文档同步 + CDP-T13/SA-T28 |
| REV-DES-19 | `cdp_engine.md` §4/§5.1/§5.4/§8/§10#10 | 模块加载即 `_publish_window()` 发布初始 idle 快照 ⇒ `metrics.snapshot()` 恒含 `cdp_restart_window`（CDP-T9 扩断言） |
| REV-DES-20 | `market_api.md` §4 BR-MKT-8 / §10#5 | owner 引据改为"本模块与 cache 的防重复计数约定"；`metrics.md` §3.2 owner 列补 `market_api` **由编排层同步**（本 agent 不改基础层文档） |
| REV-DES-21 | `stock_api.md` §3.4/§4.5/§10#10 | **编排层裁决：接受现状 + 风险登记**（f10 非热路径）；引据更正为 AC-E2；遗留风险 = `/stock/f10` 多码可达 60s，建议 `server.md` 强制"仅单码/少量码" |

**7 项登记项裁决回执（①-⑦，全部批准/接受）**：① handler 返回组装 dict（批准）→ `stock_api §10#1`；② 4 元 ledger（批准）→ §10#2；③ 第 3 参数 `ttl`（批准）→ §10#3；④ `/stock/data` 与 basic_info 共冷却账（接受）→ §10#4/4b；⑤ 池上限 2000（批准）→ §10#5；⑥ f10 60s（接受 + 登记）→ §10#10；⑦ 分片轮转属 stream（批准）→ §10#9。

**本批 v1.1 引出的「编排层同步项」**（**不在本 agent 范围**，须由编排层执行）：
1. **SAD §3 依赖方向 + `tech-stack.json`**：登记同层依赖 `stock_api → cdp_engine`（无环；REV-DES-10）。
2. **PRD AC-A5**：回改 `/market/margin` 表述（保留 `_error` 枚举客体，作为"单体 error 客体"显式子类）并写入验收矩阵（REV-DES-11）。
3. **`metrics.md` §3.2**：`upstream_fail_total` owner 列补 `market_api`（REV-DES-20）。
4. **SAD §2.4**：措辞回改为"管道层返回二元组，handler 交 `build_batch_response` 组装为 dict"（登记项①）。
5. **SAD §2.3 D-6**：`_fail_ledger` 条目同步为 4 元（登记项②）。
6. **`server.md`**：落实"`/stock/f10` 仅单码/少量码"约束（当前未强制；REV-DES-21 缓解项）。

## Step 2.5 链式推导结论（批次 3，7 规则逐条）

| 规则 | 结论 |
|------|------|
| 规则零（需求缺口） | **无新增对外 HTTP 接口**（端锁定 🟠 STABLE）。唯一新增失败模式 = `POST /stream/subscriptions` 的 `MAX_GROUPS` 超限 400（**SAD §7.1 P2-N7 已登记**，同步权归编排层；worker 内部函数新增：`_guard`/`_reserve_for`/`_drain_conn_queue`/`_frame_acquire|release`/`_pop_oldest_frame`/`_run_health_checks`/`_check_one_feed`/`_health_executor` 等）→ **无需用户确认**（无新端点、无新方法与参数） |
| 规则一（读写配对） | 流端口 `PATCH`/`DELETE /stream/subscriptions/<sid>` 均有对应 `GET /stream/subscriptions/<sid>`（组状态）→ 读写配对完整；主端口全为 `GET`/`HEAD` |
| 规则二（状态机） | ①**帧引用计数状态机**：`refs 0→1`（入队成功，计费）→ `refs 1→0`（出队消费 / 丢最旧 / 预算驱逐 / 排空，归还）；幂等（`refs<=0` 直接返回）。②**连接生命周期**：`_register_conn`（≤100）→ **复检组存活**（销毁 vs 注册，修 P2-7）→ 挂组 → `closed` + 哨兵 → `finally` 排空 + `_release_conn`；销毁路径 = `destroy_group`（置 closed→投哨兵→clear→**锁外排空**）。③**组生命周期**：created → live（有连接）→ zombie（无连接，不建帧）→ `_sweep_idle_groups`(>300s) 回收。④**healthz 准入状态**（v1.1 修 P1-1）：acquire 成功 → 批任务在飞（`healthz_inflight` 保持 >0，**准入位不归还**）→ 该批 5 个 future 全部结束 ⇒ `_HealthBatch.task_done` 归零 ⇒ `_release_health_slot()`（恰好一次）；失败 → stale 路径（不 acquire 即不 release）。⑤**CDP 重启窗口**（cdp_engine，本批只消费）。 |
| 规则三（跨模块依赖） | 依赖方向 `config‖metrics ← cache ← stock_api/market_api/stream ← server`；`stream → stock_api`（同层，既有）扩展至 `cached_batch`/`BATCH_MAX_WORKERS`/`_prefetch_slice`/`_prefetch_advance`；`server → stream` 仅 main() 延迟 import（破环）；反向禁止。逐模块 `layerIsolation` 写入详设 §1.3 |
| 规则四（数据生命周期） | ①**feed 条目**：miss→锁→双检→fetch→put（成功才写；失败不缓存）；LRU/清扫/淘汰在 cache 层。②**帧对象**：`_broadcast` 建 → 入队（refs+1）→ 帧构建/入队/出队/丢弃/排空/销毁六路径均收口；`None` 哨兵不计费。③**组/连接**：见规则二。④**healthz 快照**：成功组装才刷新（准入失败路径不刷新，防 stale 自覆盖）。 |
| 规则五（异步流程） | `push_loop` 单后台线程（同步 `sleep(delay)` 无任务状态查询/无死信——无外部存储）；healthz 专用执行器（5 worker，懒创建，`wait(FIRST_COMPLETED)` 轮询 + 两级预算）；4 条 prefetch loop 属 stock_api。**无新增任务队列/存储** |
| 规则六（权限/隔离） | 无鉴权/多租户（PRD §6）；`layerIsolation` 逐模块写入 §1.3；`server`/`stream` 均未在 tech-stack 单列条目，按分层方向 + allowlist 约束 |


## v1.1 修订摘要（REV-DES-20260915-001）

| 项 | 位置 | 处理 |
|----|------|------|
| **P1 REV-DES-01** | `cache.md` §2.6 #6–#9 | 现状列改 `_BASE_TTL(=L2)+offset`；目标列补「+ handler 派生 stagger」；加脚注钉死 `_STAGGER=max(3, ttl//4)`、offset=分区序、等价 ×1/1.25/1.5；落点由 `server.md` 承接 |
| REV-DES-02 | `cache.md` §5.2/§7.3 × `metrics.md` §3.2 | 补 `cache_hit_ratio=round(hit/(hit+miss),4)`（分母 0→0.0）+ `_cache_put` 唯一发布行；统一 `_cache_stats{hit,miss}`，明确**不存在** `cache_hit_total/miss_total`（三处一致） |
| REV-DES-03 | `cache.md` §1.3/§5.1 | 允许 import 补 `logging`；补 `log = logging.getLogger('cache')` |
| REV-DES-04 | 三份依赖图 | 澄清 `←`=分层顺序**非 import**；`config` 与 `metrics` 并列 Layer 0 叶子、互不依赖 |
| REV-DES-05 | `metrics.md` §7.4 | 统一为「`_warn_once` 就地调用（锁内/锁外均可），`_warned` 容忍竞态，不引入第二把锁」 |
| REV-DES-06 | `config.md` §2.4/§10#10 | `_BASIC_INFO_MAX_POOL` 500→2000 **行为变更登记**（联动 S9/AR-8；护栏改由端点 LRU 承担） |
| REV-DES-07 | 三份头部 | 补版本/状态/日期/作者元数据（v1.1） |
| REV-DES-08 | `config.md` §2.3 | 补注：AC-S3 模式 B 的 `2s+5s` 口径**以 NEG_TTL=5 为前提**，env 覆盖须重跑校准 |
| REV-DES-09 | `cache.md` §5.1 | `_cache_put`/`_clear_negative` **移出网络 fetch 的 try**（单独 try/log，不落负缓存），且保证先于 `event.set()` |
| 逆向 1 | `cache.md` §4.2/§3.1/§5.1/§10#11 | 新增**失败历史老化**：`NegEntry.first_at` + `_HISTORY_AGE=600s` → 老化时本次用 `REQUEST_TIMEOUT` 全预算（BR-CACHE-20）；量化保证任一 5min 窗口至多 1 次升级探测（≤1.2% <5%）⇒ AC-S3 P95 仍 2s |
| 逆向 2 | `config.md` §2.4 | 补**删除前置条件**：常量删除须与消费者迁移同 change-set；消费者详设未出前**不得单独提前删** |
| 逆向 3 | `metrics.md` §8/§10#6 | MET-T8 加强为 (a) 单元 + (b) **CI 级断言 `set(snapshot()) ⊆ _KNOWN`**；§10 说明"冻结=文档契约，运行时仅告警" |

> 偏差登记：`config.md` §10 补 D-4 `STREAM_PING_INTERVAL`、D-5 `_DOMAIN_ENCODING`；`cache.md` §10 补 D-1 gap 分支、D-2 防御细化、D-3 socket、D-7 plate stagger、逆向 1、REV-DES-09；`metrics.md` §10 补 D-6 `upstream_fetch_total`、逆向 3、依赖图、`_warned`。SAD 侧由 system-architect 回填（D-1~D-7）。
- 文件：`doc/detailed/config.md`、`cache.md`、`metrics.md`（+ 本文件）——**未动 SAD / 代码**

## Step 2.5 链式推导结论（本批相关）

| 规则 | 结论 |
|------|------|
| 规则零（需求缺口） | 无新增对外接口；仅内部函数新增（`cache_policy`/`build_batch_response`/`FetchError`/`feed_cache_get|put`/metrics 四函数） |
| 规则一（读写配对） | 不涉 HTTP 方法；`save/delete` 语义不适用 |
| 规则二（状态机） | 负缓存状态机：`无历史 → 失败(落负缓存) → 门禁期(快速失败) → 半开(未老化 2s / 老化 ≥600s 时 10s 全预算探测) → 成功(清历史)`；3 个 FetchError kind 枚举封闭 |
| 规则三（跨模块依赖） | 已锁定下游契约（见下「必须对齐的跨模块接口」） |
| 规则四（数据生命周期） | 负缓存条目生命周期：成功即清 / 满 2000 淘汰最早 `until` / **不因过期而清**（AC-S3 前提）；`first_at` 老化窗口 600s 触发一次全预算探测（BR-CACHE-20） |
| 规则五（异步流程） | 本层无异步任务；`_fetch_inflight` leader/follower 为同步等待（follower 不重入选举） |
| 规则六（权限/隔离） | `layerIsolation` 已逐模块写入详设 §1.3；无鉴权需求 |

## 必须对齐的跨模块接口（下游批次不得偏离）

- **stock_api**：`_process_chunk(..., ttl=, cache_max=)` 与传给 `fetch_json(ttl=)` **同源同变量**；`_run_batch` → `(results, errors)`；`handle_cls_*` → `cache.build_batch_response(...)`；`_fail_ledger`（码级 120s，ADR-014）；`fetch_cls_f10` raise `FetchError('cdp_unavailable')`；删 `_SECTOR_CACHE_TTL` 改 `cache_policy('sector')['ttl']`。
- **server**：`_handle_stock_batch` 计算 `dropped` 并传 `build_batch_response(..., dropped=)`（不重复组装）；`_get_or_fetch_feed` 改调 `cache.feed_cache_get/put` 并保留 `_feed_fetch_locks` 防击穿（**必须双检**：miss→取锁→**再次 `feed_cache_get`**→fetch→put）；healthz `cache_ttl` 读 `cache_policy('feed')['ttl']`；`/ths/longhu` 走 `fetch_json(..., encoding='gbk')`（2 个新调用点）；**plate 三档 stagger 承接**：`_STAGGER = max(3, cache_policy('plate')['ttl']//4)`，offset = `_STAGGER × 分区序`（REV-DES-01，严禁四调用点同 TTL）。
- **stream**：`_refresh_pool` **必须跳过 `_` 前缀键**（AR-7）；metrics 名按 `metrics.md` §3.2 注册表。
- **market_api**：`_MARGIN_CACHE_TTL` → `cache_policy('margin')['ttl']`。
- **tests**：`test_fetch_json_leader_failure_does_not_stampede` 按 AR-10 改写（`err=8`/`max_active=1`/<1ms）。

## ★ 跨模块接口约定（批次 2 锁定；`stream.md` / `server.md` 不得偏离）

### A. `stream.md` 依赖 stock_api 的 refresh 接口（本批已提供）

1. **批量 handler 返回"已组装 dict"**：`handle_cls_basic_infos / handle_cls_fundflow / handle_cls_timeline(codes, deadline=None, dropped=0) -> dict`。
   - 返回体可能含保留键 `_errors`（失败码非空时）⇒ `_refresh_pool` **必须跳过 `_` 前缀键**（AR-7 陷阱点；否则把 `_errors` 当股票塞进帧）。
   - `_FIELD_HANDLERS = {'quote': handle_cls_basic_infos, 'fundflow': handle_cls_fundflow, 'timeline': handle_cls_timeline}` **不变**。
2. **分片轮转（AR-1 / INV-1b）在 `stream.py` 实现**，stock_api 只提供原语与常量：
   - `stock_api.BATCH_MAX_WORKERS = config.BATCH_MAX_WORKERS = 20`（计算 coverage 用）。
   - ⚠️ **r5 覆盖（以代码为准）**：`coverage = max(1, int(0.8 × tick × BATCH_MAX_WORKERS / _PER_FETCH_EST))`，`_PER_FETCH_EST = config.STREAM_PER_FETCH_EST = 0.3` ⇒ **coverage = tick4 213 / tick8 426 / tick120 6400**（随 tick **线性增长**，非恒值）；`coverage_codes = coverage // _fetches_per_code(fields)`（`_FIELD_FETCH_CALLS['quote']=2`：basic + depth）⇒ **tick4 quote-only 106 / 3 域 53**。旧口径 `≈170/≈56` 与 v1.2 的 `23/23·11·7` **均已作废**（BUG-P6C-06 + BUG-SSE-DEPTH-01；见 `stream.md` §3.3/§10#15·#21）。
   - ★ **节拍 + wire 拼写（v1.3）**：`tick_interval(fields)` = 最短订阅域 tier（quote/depth L0 盘中 **4s**；无订阅 L1）；URL 构造一律 `config.upstream_secu_code`（SH/SZ 前缀形；**BSE 点号形 `430047.BJ`**），池/缓存/账本键仍 canonical。
   - ★ **`refresh_epoch`（v1.3）**：`stream._refresh_pool(..., now=本轮起点)` 对"设定 tick 的域"传入新鲜度下限 ⇒ 每拍真回源；`stock_api` 全链路透传（终点缓存命中追加 `written >= epoch`，`cache.fetch_json` 第 6 位形参）。
   - 条件 `C1: _fetches_per_code(fields) × N_active ≤ coverage ⇔ N_active ≤ coverage_codes` 成立 → 整池一周期刷新（**lag=0**）；否则分片：`|slice| ≤ coverage_codes`。
   - 游标：`stock_api._prefetch_slice(pool=None? ...)` **仅适用于有 pool 的域**；stream 的活跃码集来自 `_active_codes()`（非 pool），故 stream 用 **同一 round-robin 语义**自行维护游标键 `'stream_refresh'`（可复用 `_prefetch_rotate` 的思路；如需公共游标可调 `_prefetch_advance('stream_refresh', ...)`，该函数按 key 通用）。
   - 未进切片的码：`data = stock_api.cached_batch(field_domain, rest_codes)`（无网络读终点缓存）；
     `quote→'quote'`、`fundflow→'fundflow'`、`timeline→'timeline'`；`snapshot = fresh(slice) ∪ cached(active−slice)`。
   - 记录 `stream_refresh_lag_ticks = ceil(N_active / |slice|)` 与 `stream_tick_degraded_total`（metrics 名已冻结）。
3. **warm 码帧完整性不降级**；冷码在 ≤ lag tick 内进入（AC-A1 以 warm 稳态 + 200 帧窗口为前提）。

### B. `server.md` 依赖 stock_api / market_api / cdp_engine

- `server._handle_stock_batch`：截断后把 `dropped` 作为**参数**传给 handler：`data = handler(stock_codes, dropped=dropped)`；**不得**再次调用 `build_batch_response`（组装点唯一）。
- `/market/margin` → `handle_margin(market)`：签名不变。
- A/A′/B 降级形态：A 类（面板 4）用 `cdp_engine.page_data(page)`；`timeline` 为 `None` 时返回 `{'error': ...}`（**禁止**裸 `null`）；A′（`/stock/f10`）由 `fetch_cls_f10` 的 `cdp_unavailable` 经 `_errors` 承载。
- `_cdp_memory_watchdog`（`server.py:881`）：本轮判断改为 `reason = cdp_engine.watchdog_restart_skip_reason(); if reason: continue`（**盘中避让 + 节流判断已集中在 cdp_engine**）。
- `/healthz` 的 `cdp` 字段 = `cdp_engine.restart_window_snapshot()`；`metrics` = `metrics.snapshot()`。
- config 常量删除仍须与 `server.md`/`stream.md` 同 change-set（本批 stock_api/market_api/cdp_engine 已迁移其消费者；**server/stream 的消费者未动，故仍不得单独删常量**）。

### C. `market_api` 落地清单（本批）

- `market_api.py` 删除 `_MARGIN_CACHE_TTL` import，改 `cache_policy('margin')['ttl']`；新增 `metrics`/`FetchError` import；`_error` 值域收敛为枚举 kind。
- 与 `config.md` §2.4 的 `_MARGIN_CACHE_TTL` 删除行**同 change-set**。

## 待确认项 → 编排层裁决（**已闭环，6/6**）

| # | 待确认 | 编排层裁决 | 详设落点 |
|---|--------|-------------|---------|
| 1 | `cache_policy` 返回值中 `'n/a'` 是否保留字面量 | ✅ 批准：归一化为 `None`（矩阵保留 `'n/a'`） | `config.md` §2.1/§10#4 |
| 2 | 负缓存"过期即清" vs 半开探测需失败历史 | ✅ 批准：门禁过期失效、条目保留作失败历史（**AC-S3 模式 B 必要条件**） | `cache.md` §4.2 BR-CACHE-8 / §10#1 |
| 3 | feed LRU 落点 | ✅ 批准：机制落 `cache.feed_cache_get/put`，server 保留防击穿（**须双检**） | `cache.md` §2.4 |
| 4 | metrics 是否允许新增 `key=`/`reset()` | ✅ 批准（向后兼容） | `metrics.md` §2/§10#3 |
| 5 | `cache_hit_ratio` 发布点 | ✅ 批准：`cache._cache_put` 派生发布（**须补实现**） | `cache.md` §5.2/§7.3；`metrics.md` §3.2 |
| 6 | `STREAM_PING_INTERVAL` env 化 | ✅ 批准：env 化，默认 20 不变 | `config.md` §2.3 / §10#8（D-4） |

> SAD 侧待回填（由 system-architect 承接，**不在本 agent 范围**）：§4.3"过期即清"措辞、feed LRU 落点、§2.1 `'n/a'`→`null` 示例、§2.6 补 `upstream_fetch_total`、§3 config 行补 `STREAM_PING_INTERVAL`、Q3②/AR-6 消费者与负载增幅更正。

## 详设清单（全量 8 份）

| # | 文档 | 状态 |
|---|------|------|
| 1 | `doc/detailed/config.md` | ✅ **v1.4（批次 1 → v1.1 → P7b v1.2 → AC-S3 v1.3 → ★ 传输/容量 env v1.4）**（`PROBE_TIMEOUT` 脚注更正：阶梯封顶 = `cache._PROBE_BUDGET_CAP=5.0`；★ v1.4 补登 `BATCH_MAX_WORKERS=20`/`STREAM_PER_FETCH_EST=0.3`/`HTTP_POOL_*`/`HTTP_DNS_CACHE_TTL`/`HTTP_WARM_*`、L0 档 + `quote`→L0 + `depth` 域、`upstream_secu_code`、`warm_hosts()`；§10#19..23）**——**版本以文档头部为准** |
| 2 | `doc/detailed/cache.md` | ✅ **v1.4（批次 1 → v1.1 → P7b v1.2 → AC-S3 v1.3 → ★ 传输层 v1.4）**（`_PROBE_BUDGET_CAP=5.0`；阶梯 `2→4→5`；★ v1.4：`_ConnectionPool` + `_DNSResolver` + `cache.urlopen` 打桩缝 + `warm_transport` + `fetch_json` 第 6 位 `refresh_epoch`（BR-CACHE-31）；§10#21）**——**版本以文档头部为准** |
| 3 | `doc/detailed/metrics.md` | ✅ v1.2（批次 1 → P7b） |
| 4 | `doc/detailed/stock_api.md` | ✅ **v1.3（批次 2 → P7b v1.2 → ★ r5 契约同步 v1.3）**（depth 域 + 三阶段 basic_info + 空壳防御 + `upstream_secu_code` 全量应用 + `BATCH_MAX_WORKERS=20` + `refresh_epoch` 贯通；偏差 26·测试 39） |
| 5 | `doc/detailed/market_api.md` | ✅ **v1.3（批次 2 → v1.1 → P7b v1.2 → AC-S3 裁决 v1.3）**（BR-MKT-11 封顶更正为 `_PROBE_BUDGET_CAP`；§10#9；§12 变更记录） |
| 6 | `doc/detailed/cdp_engine.md` | ✅ v1.2（批次 2 → P7b） |
| 7 | `doc/detailed/server.md` | ✅ **v1.4（批次 3 → P7b v1.2 → N1 回退 v1.3 → ★ r5 契约同步 v1.4）**（`_guard`×14 表驱动 + `_send_json_shape`（**恒 200**）、**`_json_payload_has_data` 已删**、**业务降级 = 200 + error 体**、`_send_json` 无 `status`、`http_503_total` 计数点 3、降级体可缓存、healthz 有界准入 + `_HealthBatch`(+`settle()`)、feed 双检、码归一 `_parse_stock_codes`/`_rekey_batch_response`、margin 400、`_FANOUT_WAIT_BUDGET`、`_base_url` 加固、面板 cache-age=`quote`、longhu 席位配对自增、`request_queue_size=LISTEN_BACKLOG`；★ **v1.4 新增 gzip 协商 `_accepts_gzip`+`Vary` 与 `main()` `warm_transport` 预热线程**；对照表 §11.3·§11.4，偏差 31 项·测试 45） |
| 8 | `doc/detailed/stream.md` | ✅ **v1.3（批次 3 → P7b v1.2 → ★ r5 契约同步 v1.3）**（帧 schema 全码 + `missing`/`stale`/`errors`、last-known 结转、`_refresh_pool` 5 参 + 字段并集 + tick 预算、整 tick 网格 + 异常退避、lag C1/空池=0、准入 cap 单帧余量（9→8）、fail-closed 字段、canonical_code、`Connection: close`；★ **v1.3：节拍=最短订阅域（quote L0 4s）、`coverage` 213/426/6400、`coverage_codes` tick4 **106/53**、`refresh_epoch` 每拍真回源、帧发送层去重（`_frame_signature`/`sent_any`）、空闲唤醒 + 冷首轮豁免、`quote` 可含 `depth`**；偏差 33 项·测试 48） |
| 9 | `doc/detailed/编码规范.md` | ⏳ 待生成 |
| 10 | `doc/detailed/项目规则.md` | ⏳ 待生成 |

> 状态标记：**批次 1（3 份）已评审通过并修订至 v1.1**（`REV-DES-20260915-001`）；**批次 2（3 份）已按评审修订至 v1.1**（`REV-DES-20260915-002`，各文档头部为准）；**批次 3（server/stream 2 份）已完成评审闭环（v1.1）+ P7b 契约同步（v1.2）**；★ **v1.3 收尾契约同步**已回写 `server.md`（N1 回退）/ `cache.md`·`config.md`·`market_api.md`（AC-S3 裁决）——**版本以各文档头部为准**（见上表）→ **全量 8 份详设可交付 code-developer**。
> 
> **P7b 说明**：`config.md` 亦已在同轮 P7b 同步中回写实现态（其头部 §2.6/§10#14 等），本文件与 `config.md` 的旧口径注释（`VALID_STOCK_CODE` 保留说明）以 `config.md` 头部为准。
>
> ✅ **交付/编码前置提醒（P7b 更新）**：`config.md` §2.4 的 `CACHE_TTL`/`CACHE_JITTER`/`feed_cache`/`MAX_FEED_CACHE_SIZE`/`_trading_tiers` 常量删除**已随代码落地**（`config.py` 已无 `CACHE_TTL`；`server.py` 消费点全部改读 `cache_policy`）——本项**销账**。
>
> ⚠️ **跨模块契约同步项（编排层执行；★ v1.3 更新）**：① `feeds[].status` 三处取值修正（`/stock/data`→`configured`、`/stock/basic_info`→`configured`、`/stock/f10`→`requires_chrome_cdp`）需同步 healthz 负载 + 首页 CDP 列 + `API.md`；② `POST /stream/subscriptions` 的 `MAX_GROUPS=200` 超限 **400** + v1.2 新增 **`_FRAME_BUDGET_ERR` 400**（流端口 API 文档 + 变更日志）；③ `BoundedThreadPoolServer` 的 `max_inflight` 形参、**流端口显式 110**（`server.md` §10#11 · `stream.md` §10#13，编排层已批准）；④ **v1.2 新增对外行为**（★ v1.3 已剔除 error-only ⇒ 503）：~~error-only payload ⇒ 503~~ **（N1 回退：业务端点恒 200 + error 体，**无需外部同步**）**、`/healthz` 缺 `status`/含 `error` ⇒ 503、4 面板 `max-age` 8/120、`/market/margin` 非法参数 ⇒ **400**、SSE 帧新增 `missing`/`stale`/`errors` 元数据与 null 占位 —— 仍须 API 文档 + 变更日志同步；⑤ **SAD 措辞回改**：`handle_cls_*` 返回"组装 dict"（非 `(results, errors)`）+ INV-1b 覆盖数值（170/56 → ~~23/23·11·7~~ **213/426/6400；coverage_codes tick4 106/53**，见上「r5 契约同步」）—— 由 system-architect 承接；★ ⑥ **v1.3 新增（AC-S3 裁决）**：`cache._PROBE_BUDGET_CAP=5.0`（阶梯封顶，**机制常量非 env**）与"P95 ≈ 5s / 单请求 ≤15s"的量化口径若需写入 SAD §2.3 D-1，由 system-architect 回填（`cache.md` §10#11·#18 / `config.md` §2.3·§10#18 已按实现钉死）。
>
> ★ **v1.4 新增（r5 契约同步 · 编排层执行）**：⑦ **`API.md` / README / 变更日志同步**：① SSE 帧 `items[code].quote` 新增 **`depth`**（五档盘口 21 字段）＋ 既有 `missing`/`stale`/`errors` 元数据与 null 占位；② 主端口 JSON/HTML 响应新增 **gzip**（`Content-Encoding: gzip` + `Vary: Accept-Encoding`，`Accept-Encoding` 协商；`gzip;q=0` 不压缩）；③ 建组 400（`MAX_GROUPS` / `_FRAME_BUDGET_ERR`）与 `refresh_capacity_codes`（tick4 quote 106 / 3 域 53）容量元数据；④ `feeds[].status` 三处取值修正（`/stock/data`→`configured`、`/stock/basic_info`→`configured`、`/stock/f10`→`requires_chrome_cdp`）。⑧ **SAD 回填（system-architect）**：§2.1 INV-1b / §2.2 R-6 覆盖数值改为 `coverage = int(0.8×tick×BATCH_MAX_WORKERS/_PER_FETCH_EST)`（r5：**213/426/6400**；`coverage_codes` tick4 **106/53**）、补 **L0 档**（quote/depth 盘中 4s）、`depth` 域、`upstream_secu_code`（wire 拼写）、`_refresh_pool` 的 `refresh_epoch` 与帧发送层去重；`config.md`/`cache.md`/`stream.md`/`stock_api.md`/`server.md` **已按实现钉死**。

## v1.1 修订摘要（批次 3 · REV-DES-20260915-002）

> 评审报告：`doc/review/HTTP-SSE层两模块_详细设计评审_专家版.md`（结论 ⚠️ 阻断，P0×0 / P1×4 / P2×10）。
> 范围：仅 `server.md` / `stream.md`（+ 本文件）——**未动 SAD / PRD / config.md / 代码**。

| 项 | 位置 | 处理 |
|----|------|------|
| **P1-1** healthz 准入位早释放 → 无界队列 | `server.md` §2.6/§2.6.1/§3.2/§4.5/§5.6/§6.2/§7/§8/§10#16 | 新增 `_HealthBatch`：准入位由该批 **5 个 future 的完成回调**释放 ⇒ 在飞任务 ≤25、执行器队列 ≤20；§2.6 断言与伪代码一致；新增 `SRV-T34`（持续慢 check 下队列有界、恰好 release 一次） |
| **P1-2** 外部上游串行越 AC-E2 | `server.md` §1.1/§2.8/§2.9/§4.6 BR-SRV-30/§5.5/§6.2/§8/§9/§10#10·#15 | hotplate/plate/longhu 改 **≤3 并发**（共享 `_fanout_executor`）⇒ 单端点 = `max` 而非 `sum`（≤10s ≤15s）；登记归属更正为 **AC-E2**；新增 `SRV-T35`、`SRV-T13` 补并发断言 |
| **P1-3** hotplate 全失败缺顶层 `error` | `server.md` §2.8/§4.6 BR-SRV-31/§5.5/§6.1/§8·T14/§9 | 三分区全失败 ⇒ **顶层补 `error`**（SAD §2.3 D-4 唯一口径）；部分失败仍无顶层 `error` |
| **P1-4** 流端口 inflight 40 使 100 连接失效 | `server.md` §1.5/§2.7/§3.4/§5.7/§10#11 · `stream.md` §2.2/§10#13 | `BoundedThreadPoolServer.__init__` 增 `max_inflight=None`；流端口显式传 **110**（≥ `MAX_STREAM_CONNS`+10）⇒ AC-E5/E7 可复现（**编排层已批准**） |
| **P2-1** ttl 求值点矛盾 | `server.md` §2.5/§5.4/§7.4 | `ttl` 移到**二次 `feed_cache_get` 仍 miss 之后**求值；唯一表述 |
| **P2-2** healthz 10s 预算死代码 | `server.md` §2.6.1/§3.2/§4.5 BR-SRV-20/§5.6/§8·T21 | 每源按各自 `submitted_at` 独立 3s；整体 10s 为独立闸（新增可测断言） |
| **P2-3** `feeds[].status` 注释过宽 | `server.md` §3.1 | 限定"仅 5 个 RSS 源被覆盖"；10 个 JSON/CDP 条目保持原值 |
| **P2-4** 分组视图 `object（8）` 计数错 | `server.md` §2.2 | 改 `object（7，表内）`+ 明示 `/healthz` 不入表（否则 `assert len==14` 失败） |
| **P2-5** import 清单不完整 | `server.md` §2.10 | 改为**完整 import 块**（可整体替换）：补删 `Request,urlopen`/`random`；补 `main()` 所需 `stock_api` 4 prefetch loop、`market_api`、`utils` |
| **P2-6** `_group_bytes` 系统性低估 | `stream.md` §3.4/§4.2 BR-STR-15/§5.2/§8·T33/§9/§10#6 | `_reserve_for` 改用**本轮排除集 `skip`**（不再 `pop(_group_bytes[sid])`）⇒ 组账如实、丢弃选靶确定性恢复；`skip` 单调增长保证终止 |
| **P2-7** 销毁 vs 注册残留竞态 | `stream.md` §5.5/§7.4/§8·T34/§10#17 | `g.conns.add(conn)` 后在 `_groups_lock` 下复检 `_groups.get(sid) is g`；不成立 ⇒ `closed`+摘除+`_release_conn`+404 |
| **P2-8** 测试清单多列 1 条 | `stream.md` §11.1/§8·T31 | `test_broadcast_serves_live_group_only` 降级为**可选清理**（非破坏性）；明示真正必改 = **4 条** |
| **P2-9** `stream_refresh_lag_ticks` owner | `stream.md` §3.5 | owner 对齐 `metrics.md` §3.2 = `stream.push_loop` |
| **P2-10** `cached_batch` 域名隐式化 | `stream.md` §2.3 | 统一 `cached_batch(_FIELD_DOMAINS[field], rest)`（消除"字段名==域名"假设） |
| **裁决①** handler 返回组装 dict | `server.md` §10#17 | 批准；SAD 措辞由 system-architect 回改 |
| **裁决②** 流端口 `max_inflight=110` | `server.md` §10#11 · `stream.md` §10#13 | 批准 |

**保持不动**：全部 SAD v1.3 钉死项（stream 侧 **7 项全 ✅**、server 侧 8 项中 6 ✅ 已转为 ✅，见 server §4 与 `SRV-T14` 更新）；既有测试真正破坏面仍为 **4 条**（全在 stream，未新增）。

