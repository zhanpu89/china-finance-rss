# HTTP/SSE 层代码评审（P5b + P7a 合并）

> **评审对象**：`china_finance_rss/server.py`（v1.1 落码）、`china_finance_rss/stream.py`（v1.1 落码）、
> `tests/test_server_http.py`（新增）、`tests/test_stream.py`（4 条既有同步 + 新增多组）
> **契约基线**：`doc/detailed/server.md` v1.1 · `doc/detailed/stream.md` v1.1 · `doc/arch/SAD.md` v1.3 · `doc/prd/perf-stability-optimization.md` v0.4（30 AC）· `doc/arch/tech-stack.json` · `doc/detailed/_PROGRESS.md`
> **评审者**：code-reviewer ｜ **模式**：`>>MODE: review+drift`（评审维度 Dim 0–6 + P7a 漂移节同文档）
> **日期**：2026-09-16

---

## 0. 总评与结论

**本次改造的主干方向正确、落实度高**：`_guard` 全路由防护、`_JSON_SHAPES` 14 + 双断言、feed 双检（双检点与 `ttl` 求值点均与详设一致）、plate 三档 stagger 未被压平、hotplate 全分区失败顶层补 `error`、longhu 走 `fetch_json(encoding='gbk')` 且两 URL 并发、healthz 有界准入 + `_HealthBatch` 五路销账（P1-1 修得干净：`_HealthBatch` 在任何 `submit` 之前建账、回调幂等、`sid is None` 无泄漏路径）、`_frame_bytes_lock` 是纯粹的叶子锁（临界区仅 dict/整数算术 + 锁外发布 metrics）、`_reserve_for` 的 `skip` 排除集与 `_premium` 组账不低估（P2-6）、"销毁 vs 注册"复检（P2-7）、分片轮转 C1/C2 与 `_` 前缀跳过均**逐条可验证**。

**但存在 4 条 P1**，其中 2 条是**新引入机制自身的不变式不成立**（帧计费的"入队后计费"窗口、字节预算的容量前提），另 2 条使 AC-E2 / 输入校验在并发与对抗负载下不成立。

**结论：⚠️ 有条件通过**（P0×0 / P1×4 / P2×12；漂移项 6 + 无害偏差 4）。
→ 开发版可继续迭代；**生产放行前须闭环 P1-1 ~ P1-4**（均可小改）。

**Top3 风险（按最坏后果排序）**
1. **P1-1 帧计费漂移（单调、不可自愈）**：`put_nowait` 与 `_frame_acquire` 之间存在真实并发窗口，命中即让 `refs/_queue_bytes/_group_bytes/_live_frames` 永久多计一个幽灵帧 ⇒ 预算选靶被污染，最终**无谓驱逐其他组的真实帧**，并让 3 个对外指标失真。违反 stream.md §4.2 明文承诺的"`refs == 该帧被多少连接队列持有`（可白盒断言）"。
2. **P2-4 字节预算与配置上限不自洽**：`STREAM_QUEUE_BYTES_BUDGET=128MB` 只按"单组 8 深窗口"推导（128/14MB≈9 帧），而合法配置是 100 条 SSE 连接（≤100 个活跃组）× 单帧上界 14MB ≈ 1.4GB ⇒ 最坏配置下**每 tick 必然丢弃 ≈91% 组的帧**（AC-E5「丢弃 ≤1 帧」不成立，客户端静默收不到帧）。
3. **P1-2 共享扇出池的无界等待**：`_fetch_concurrent` 只保证"在飞 ≤3"，未保证"排空有界"；`max_workers=3` + 无界 `work_queue` + `fut.result()` 无超时 ⇒ 20 个主池 worker 同时打 plate/hotplate/longhu 时队尾等待可达 ≈190s（设计声称 ≤10s，AC-E2 ≤15s）。

---

## 0.1 受影响面清单（无 `>>SIDE-EFFECT:` 入参 ⇒ 由 diff 推断，供编排器映射 `>>SCOPE:` 定向回归）

| # | 受影响点（行为变化） | 归属模块 | 逆向假设（会破坏谁） | 结论 |
|---|---|---|---|---|
| 1 | `_guard` 成为 14 JSON + 5 RSS + `/healthz` 的唯一异常收口 | server | 依赖"handler 异常冒泡到调用方"的调用点/测试 | 不成立（无此类调用点；SRV-T2/T3 覆盖） |
| 2 | `/cls/hotplate`·`/cls/plate`·`/ths/longhu` 由**串行**改 **≤3 并发**，共享 `_fanout_executor` | server → cache.fetch_json | ①上游并发压力由 1 变 3（限流/封禁风险）；②跨端点队头阻塞（见 P1-2） | ①成立且已登记（SAD §4.1）；②**成立 → P1-2** |
| 3 | plate/hotplate 三档 TTL（12/15/18 盘 · 120/150/180 非盘） | server → cache | 依赖"三段同 TTL"的缓存击穿假设 | 不成立（错峰只降不升） |
| 4 | longhu 改走统一 `fetch_json(encoding='gbk')` + L4 TTL | server → cache | cache 层新增 2 个 URL 缓存键/负缓存键 | 不成立（cache 按 URL 键，容量有界） |
| 5 | `_cache_age` 接 policy：`/stock/announcement` **300→30/180**、`/market/margin` **300→600** | server → 外部客户端/爬虫 | 依赖旧 max-age 的下游代理行为 | **成立但为预期修正**（§5.8 已登记；需 API.md 同步，见漂移 D2-6） |
| 6 | `codes→frozenset` / `fields→tuple`；`do_GET /stream/subscriptions/<sid>` 输出不变（list→JSON array） | stream | 对 `g.codes` 原地 `add/discard` 的代码 | 不成立（grep 无；STREAM-T1 覆盖） |
| 7 | 队列元素 `str → _Frame` | stream | 直接读 `conn.q.queue` 取字符串的代码/夹具 | 不成立（`_serve_sse` 双型兼容；旧夹具已同步） |
| 8 | 流端口 `max_inflight` 40 → **110**（显式） | stream → server 服务类 | 依赖"流端口在飞 ≤40"的容量假设 | **成立**（2C2G 上 100 连接为既定预算，属已批准的恢复行为） |
| 9 | `POST /stream/subscriptions` 新增 400 失败模式（`MAX_GROUPS`） | stream → 外部 API | 客户端错误处理分支 | 成立（已在 stream.md §2.1/§10#9 登记；需 API.md + 变更日志） |
| 10 | `/healthz` 只增 4 键 + `feeds[].status` **3 处取值变更** + 首页 CDP 列 | server → 外部 API/监控 | 按旧 `status` 取值的告警规则 | **成立**（§2.9.1 已登记；需 API.md 同步，见漂移 D2-6） |
| 11 | `_send_error(write_body=False)`：HEAD 的 400 不再写体 | server | 依赖 HEAD 400 带体的客户端 | 不成立（符合 HTTP 语义） |

---

## 1. P0（0 条）

无。逐项确认过 4 类 P0 判据均未命中：

- **崩溃/不可恢复**：`push_loop` 有 `except Exception` + `sleep(1)` 兜底（`stream.py:458-460`）；`_guard` 覆盖全部 handler 路径（`server.py:504-526`）；`_run_health_checks` 为总函数（执行器创建失败/提交失败/超时/正常完成四路均销账）；`send_error(404)` 由 CPython 自行判 `HEAD` 不写体。
- **数据丢失**：无持久化；feed 回源失败不写缓存（`server.py:953` 注释与实现一致）；`_pop_oldest_frame` / `_broadcast` 的两处丢弃均为"丢最旧保最新"（`stream.py:383-386`），不丢最新。
- **资金**：无交易路径。
- **安全**：见 P1-3（同主机参数注入，非 SQL 注入/越权，故列 P1 而非 P0）；无明文凭据、无路径穿越到本地文件。

---

## 2. P1（4 条，建议修复；生产版阻断）

### 【P1-1】`stream.py:374-396` — "入队后计费"窗口使 `refs` 与字节账永久漂移（幽灵帧）

**描述**：`_broadcast` 按 BR-STR-9 的顺序执行 `put_nowait(frame)` →（`else` 分支）`_frame_acquire(frame)`。两条语句之间没有任何锁/GIL 屏障：`queue.put_nowait` 内部在释放 `not_full` 互斥量前 `notify()`，已阻塞在 `q.get()` 上的 SSE handler 线程被唤醒后**可在另一核上真实并发**执行 `q.get()` → 写帧 → `finally: _frame_release(f)`。此刻 `f.refs == 0`，`_frame_release` 命中幂等短路（`stream.py:273-274`）直接返回、**无任何副作用**；随后广播线程才执行 `_frame_acquire` ⇒ `refs` 变为 1 且 `_queue_bytes += size`、`_group_bytes[sid] += size`、`_live_frames += 1`，而该帧**已不在任何连接队列中**。

**证据链（当…→后果…因为…）**：
当活跃 SSE 客户端在 `q.get()` 上等待（高频常态）且广播线程在 `put_nowait` 返回与 `_frame_acquire` 之间被抢占（GIL 切换间隔默认 5ms，窗口 ≈ 数十字节码）→ 该帧被计费但无人持有，且**永远不会被归还**（`_drain_conn_queue` 只能在队列里找到它；它已不在队列）→ 后果：`_queue_bytes`/`_group_bytes[sid]`/`_live_frames`/`stream_frame_peak_bytes` 单调偏高（`_live_frames` 只增不减）→ 因为 `_reserve_for` 以 `_group_bytes` 最大值为选靶（`stream.py:333-334`）且该组所有连接都无该帧可丢（`old is None` ⇒ `skip.add(sid)`），每轮 `_reserve_for` 都为它白耗一次迭代；当其他组也进 skip 时 `_reserve_for` 提前返回（`stream.py:335-336`），真实预算未满却已停止驱逐；反向地，幽灵账使该组持续被选为受害组直至其真帧被清空 ⇒ **其他组的真实帧被无谓驱逐**（`stream_frame_dropped_total` 虚高、客户端丢帧率上升）。

**依据**：stream.md §4.2 BR-STR-6/9 明文承诺"`refs` 语义 = 该帧当前被多少连接队列持有（可白盒断言）"、§7.5#3"100 连接 × 200 tick 后 `refs` 精确"；实现无法满足该断言。§7.5#4 只分析了"已入队未计费（下一语句即补）"的单侧窗口，**未考虑消费者落在窗口内**这一侧。

**建议**（择一，均不改外部契约）：
1. **计费先于入队**：`_frame_acquire(frame)` → `try: conn.q.put_nowait(frame)` / `except queue.Full:` 走"丢最旧 + 二次入队"分支；若二次入队仍失败则回滚 `_frame_release(frame)`（保持"未入队不计费"）。此时 `refs ≥ 1` 先于帧可见，消费者的 `_frame_release` 不再短路。
2. **把"入队 + 计费"合并进 `_frame_bytes_lock` 临界区**：`with _frame_bytes_lock: q.put_nowait(...); refs+=1; ...`。安全性：`_drain_conn_queue` 的 `q.get_nowait()` 在返回前已释放 queue 内部锁，故 `_frame_bytes_lock → queue.mutex` 与 `queue.mutex → _frame_bytes_lock` **不会同时持有**，无死锁；但会轻微扩大临界区（仅一次无阻塞入队，无 IO）。

**回归防护**：补一条白盒用例——patch `_SSEConn.q`（或注入 `put_nowait` 钩子在返回前触发 `q.get_nowait()` + `_frame_release`）断言 `_queue_bytes == 0`、`_live_frames == 0`（现有 `FrameAccountingTests` 只覆盖正常路径，见 §6）。

### 【P1-2】`server.py:531-568` — 共享扇出池的**等待队列无界**，单端点耗时上界（AC-E2 ≤15s）在并发下不成立

**描述**：`_get_fanout_executor()` 是 `ThreadPoolExecutor(max_workers=3)`，其 `work_queue` 无界；`_fetch_concurrent` 对多段请求**提交全部段后逐个 `fut.result()`（无 timeout）**（`server.py:561-567`）。

**证据链**：当 20 个主池 worker（`MAX_WORKERS=20`）同时命中 `/cls/plate`（或 hotplate/longhu 任意混合）→ 每个 handler 提交 3 个任务 ⇒ 最多 60 个任务进入 3-worker 池 → 每个任务自身最坏耗时 = `cache.fetch_json` 的 `REQUEST_TIMEOUT=10s`（`cache.py:202-206`）→ 队尾请求等待 ≈ `(60-3)/3 × 10s ≈ 190s` → 后果：**单请求耗时上界由 10s 退化为 ~190s**，远超 `server.md` §6.2#6 与 AC-E2 的 15s；且池是 **hotplate/plate/longhu 共享**的 ⇒ 一个端点的积压**跨端点传染**（plate 洪水让 longhu/hotplate 一起排队），与"分区可独立降级"的设计意图相悖。

**依据**：BR-SRV-30 与 §10#15 只论证了"全局在飞取数 ≤3（资源口径）"，**未论证排空时间有界**；AC-E2 的推导（§5.5 注）隐含"提交即执行"。

**建议**（择一）：
1. **提交侧准入**：模块级 `threading.BoundedSemaphore(_FANOUT_MAX_WORKERS)`，`_fetch_concurrent` 非阻塞 `acquire` 失败 ⇒ 本轮该段**走快速降级**（返回 `FetchError('upstream_error')` 等价体 / 直接串行本地取缓存），保证端点级上界 = `REQUEST_TIMEOUT + 排队容忍`；
2. **等待侧上界**：`fut.result(timeout=_FANOUT_WAIT_BUDGET)`（≈ 单次 `REQUEST_TIMEOUT`），超时按 `upstream_timeout` 降级并 `fut.cancel()`（已在跑的任务无法取消，但请求不再无限等待）；
3. 或给共享池换**有界队列**（`_work_queue = queue.Queue(maxsize=N)`）并在满时拒绝提交 → 立即降级。

**附带**：`_get_fanout_executor` / `_get_health_executor` 均为懒创建且永不 `shutdown`；进程退出由 `concurrent.futures` 的 atexit join 兜底（空闲 worker 会退出），可接受，但建议在 `main()` 的退出钩子里显式 `shutdown(wait=False)`。

### 【P1-3】`server.py:890-892`（+ `market_api.py:45`）— `market` 参数未校验即拼进上游 URL（同主机路径/查询注入 + 缓存键污染）

**描述**：`_handle_request` 取 `parse_qs(parsed.query).get('market', ['99'])[0]` 后**原样**传给 `handle_margin`；`fetch_margin` 用 f-string 拼路径：`url = f'{_MARGIN_URL}/{market}/'`。`server.md` §2.1 的 OpenAPI 声明 `market` 为 enum `['99','1','2','3']`，实现层**没有任何校验**（对照：`/stock/*` 的码由 `stock_api.py:360` 的 `VALID_STOCK_CODE` 在下游拦住，`market` 没有对应防线）。

**证据链**：当请求 `/market/margin?market=1%3Ffoo%3Dbar` → `market='1?foo=bar'` → 上游 URL 变为 `…/fixdata/type/1?foo=bar/`（query 注入）；`?market=..%2F..%2F..%2Fsome` → 路径穿越到**同主机**其他端点（是否可达取决于上游 nginx 归一化）；且 `fetch_json` 以 URL 为缓存键 ⇒ 每个不同 `market` 值产生一个独立的**正缓存 + 负缓存**条目、一次真实出网请求、一次 `upstream_fetch_total` 计数 ⇒ 攻击者可用一条 URL 参数高速刷：放大出网流量、加速全局缓存 LRU 驱逐（挤掉合法条目）。

**依据**：`server.md` §2.1 enum 声明（契约未实现）；评审重点 #5"URL 参数处理、无注入"；`tech-stack.json` `namingRules.config`"禁止裸…一律经 config 派生"的同类精神（外部输入须在边界校验）。**归属说明**：`market_api.py` 不在本次变更清单内（注入点是既有的），但 `server.py` 的 `margin` 分支正是本次"路由层统一收口"改造覆盖的入口，校验加在这一层是一行改动，故记为本层 P1。

**建议**：`market = query.get('market', ['99'])[0]`，随后 `if market not in ('99','1','2','3'): self._send_error('Invalid ?market= parameter. Allowed: 99,1,2,3', write_body=write_body); return`（与 `/cls/plate` 缺参 400 同族，`server.py:873-879` 已有现成范式）。

### 【P1-4】`stream.py:319-354` + `config.py:34-41` — 128MB 字节预算与"合法配置 × 帧上界"不自洽：最坏配置下每 tick 必然丢弃 ≈9 成群组的帧

**描述**：`_reserve_for` 的容量前提来自 `stream.md` §3.4：`F_max ≈ 14MB`（`MAX_CODES_PER_SUB(200) × 3 字段 × ~23KB`）、`B(128MB) ≥ 8 × F_max` ⇒ 结论"**单个**满尺寸组的 8 深窗口不被强制驱逐（保 AC-E5「丢弃 ≤1 帧」）"。该推导**只覆盖一个组**。而合法上限是 `MAX_STREAM_CONNS=100` 条连接（⇒ 最多 100 个活跃组，`_active_codes()` 只统计有连接的组）× 每组每 tick 至少 1 个 distinct 帧 ⇒ 稳态需要 `100 × 14MB ≈ 1.4GB`，预算只有 128MB ⇒ 最多同时存活 `128/14 ≈ 9` 个满尺寸帧。

**证据链**：当 10+ 个"200 码 × 3 字段"的组同时在线（无需攻击：客户端可自建组，`create_group` 只校验单组 ≤200 码与去重池 ≤2000，10 个组共用 200 个码即合法）→ `_broadcast` 每组入队前调 `_reserve_for(14MB)`（`stream.py:373`）→ `_queue_bytes + incoming > BUDGET` 恒成立 → 从 `_group_bytes` 最大组的最满连接反复丢队首（`stream.py:341-353`）→ 后果：**每 tick 有 90+ 个组的帧在客户端读取前就被驱逐**，这些客户端静默收不到帧（不是"延迟 ≤lag tick"，是丢帧），`stream_frame_dropped_total` 线性增长；AC-E5"丢弃 ≤1 帧"与 AC-A2"丢旧保新"的验收前提（`B ≥ 8×F_max`）在合法配置下不成立。

**依据**：ADR-013 / `stream.md` §3.4 的推导只算了单组 8 深窗口，**未与 `MAX_STREAM_CONNS`/`MAX_GROUPS` 联合求解**（`MAX_GROUPS=200` 更极端：200×14MB ≈ 2.8GB）。

**建议**（择一，属容量参数决策，需编排层确认）：
1. 把预算口径改为 `max(8 × F_max, MAX_STREAM_CONNS × F_expected)` 并按 2C2G 内存重新定 `F_max`（例如把单帧上界压到 ~1.3MB：`MAX_CODES_PER_SUB` 或订阅字段数在 SSE 侧再设小上限）——**注意内存现实：2C2G 放不下 1.4GB，故更可能需下调 `MAX_CODES_PER_SUB(stream 侧)` 或引入"每帧最多 K 码"**；
2. 引入**按组配额 + 跨组公平**（每组保留 ≥1 帧的软保证），使超支时只丢"深队列"而不丢"唯一帧"；
3. 无论选哪条，**在 `/healthz` 暴露 `stream_frame_dropped_total` 速率**（已注册名，无需新增）并把它作为容量回归的观测点。

---

## 3. P2（12 条，记录不阻断）

| # | 位置 | 描述（含证据） | 建议 |
|---|------|---------------|------|
| P2-1 | `server.py:20,40,55,58`；`stream.py:30,32` | **未用 import**：`os`、`MAX_HEALTH_INFLIGHT`（因为用的是 `config.MAX_HEALTH_INFLIGHT`）、`escape_xml`、`strip_html`、`handle_cls_stock`；`ThreadPoolExecutor`、`parse_qs`。`server.md` §2.10 的"完整 import 块"注释称"handler + main() 均用"，与实际不符（`os`/`escape_xml`/`strip_html` 在 server.py 内 **0 引用**） | 删除未用 import（或修正 §2.10 注释）；`escape_xml/strip_html` 若保留需注明"仅供测试/兼容" |
| P2-2 | `server.py:752-763` | **契约函数缺失**：`server.md` §2.9 声明 `_health_snapshot() -> dict \| None`（"返回浅引用"），实现把读取内联在 stale 分支（行为等价） | 文档删该行并注明"实现内联于 `build_health_payload` stale 分支" |
| P2-3 | `server.py:902` | **契约断言未实现**：`server.md` §2.2 末条要求 `_handle_stock_batch` 断言 `_JSON_SHAPES[path] == 'batch'`，但该函数**无 `path` 形参**（设计上不可实现）。同等风险已由 `server.py:470-471` 的导入期集合断言覆盖 | 文档改为"由 `_STOCK_BATCH_HANDLERS` 与 `_JSON_SHAPES` 的 batch 集合相等断言覆盖" |
| P2-4 | `stream.py:330-336` | `_reserve_for` 在"无可丢候选"时直接 `return dropped`，**超支仍会被后续 `put_nowait` 接受**（入队无终检）⇒ §3.4 "保证新帧必可入队 / `_queue_bytes` 不破"的措辞与实现有张力（最坏情形下不变式 3 不再成立），且该降级**无可观测信号** | 返回前若 `_queue_bytes > BUDGET` 记 `log.warning`（不改 metrics 冻结注册表）；文档补"无可丢候选时的兜底语义" |
| P2-5 | `stream.py:404-427`、`520-539` | `_sweep_idle_groups` / `destroy_group` 均不清理 `_group_bytes[sid]`；若存在 P1-1 产生的幽灵帧，该组账与 `_live_frames` 永驻（每轮 `_reserve_for` 多一次无效选靶）。修 P1-1 后该状态不可达 | 修 P1-1；另建议在 sweep 后加一次性自检日志（`_group_bytes` 中 sid 不在 `_groups` 且无 refs>0 → warning） |
| P2-6 | `stream.py:626-627,669-670` | `do_POST`/`do_PATCH` 在 `create_group`/`patch_group` 之后**再次** `get_group(sid)` 并直接 `.codes/.fields`，未判 `None`；并发 `destroy_group` 时 `AttributeError`（`created_ts` 保护使实际触发概率低，但 sweep/+DELETE 竞态窗口存在） | 复用前一次取到的 `g` 并判 `None` → 404 |
| P2-7 | `stream.py:614-678` | 流端口**无请求级异常边界**（与主端口 `_guard` 不对称）：任何 handler 异常只得到 socketserver traceback + 直接断连，违背 `stream.md` §6.2"请求层全部返回结构化 `{"error": ...}`，不裸断连" | 在 `do_*` 外层包 `try/except Exception → self._send_json(500, {'error': 'internal error'})`（保持"永不裸断连"） |
| P2-8 | `stream.py:153,447` | `_refresh_pool(codes, now=None)` 的 `now` **从未使用**（`tick_interval()` 走墙钟），`push_loop` 仍传 `now` ⇒ §2.3 宣称的"注入点（便于测试）"无效，易误导后续测试以为能冻结交易时段 | 要么用 `now` 派生 tick（`_is_trading_hours(now)`），要么删形参；二选一后同步 §2.3 |
| P2-9 | `stream.py:190-194` | `cached` 分支**不做** `_` 前缀过滤（fresh 分支做了）。当前安全（`rest ⊆ active` 且 `cached_batch` 只回传入参码），但与 BR-STR-22"唯一陷阱点在遍历处"的防御口径不对称，未来 `cached_batch` 返回面扩大即穿透 | 在 cached 分支同样加 `if code.startswith('_'): continue`（一行，防御对称） |
| P2-10 | `stream.py:713-741`；`server.py:1120-1122,1196-1199` | **退出可能挂住（既有问题，非本次引入）**：`ThreadPoolExecutor` 的 worker 在 3.9+ 为**非 daemon**，`concurrent.futures` 的退出钩子会 join 全部 worker；而 stream 端口每个 SSE 连接占用一个 worker 且循环 `while not conn.closed`，SIGTERM/SIGINT（`main()` 的信号处理器 `sys.exit(0)`）后 `closed` 无人置位 ⇒ 有活跃 SSE 连接时进程可能长时间不退出（每个 worker 需等下一次 `q.get(timeout=20s)`，且醒来后 `closed` 仍为 False） | `main()` 的退出钩子加：遍历 `stream._groups` 置 `conn.closed=True` + 投 `None` 哨兵 + `srv.shutdown()`（本次新增的 `_drain_conn_queue`/`destroy_group` 已是现成原语） |
| P2-11 | `server.py:838`、`752-763` | 准入失败返回 `{**snap,'stale':True}`，若上次快照 `status=='ok'` 则 HTTP **200**；监控若只看状态码会漏判"检查被拒"。`stream.md`/`server.md` BR-SRV-18 明确"依 `payload['status']`"，**非漂移** | 监控/告警口径改用 `stale` 字段（文档侧登记即可，无需改码） |
| P2-12 | `stream.py:743-754` | `make_stream_server(max_workers=N)` 与 `max_inflight` **不联动**：传 `max_workers≠110` 时 `_max_inflight` 仍为 110 ⇒ 最多 110 个请求可灌进 N-worker 池，管理端点可能被长连接饿死（测试中的 `max_workers=4` 即此类） | `max_inflight = max_workers if max_workers else MAX_STREAM_CONNS + 10`，或断言 `max_workers >= max_inflight` |

**❓ 逆向发现（额外）**
- **❓逆向: `server.py:338-345`（hotplate）/ `388-399`（plate）** — `fetch_json` 成功但上游返回**非 dict 的合法 JSON**（如顶层数组）时，`raw.get('data')` 抛 `AttributeError` ⇒ 整个端点降级为 `{'error': '...'}`，**丢失其余正常分区的数据**，"分区可独立降级"失效。详设伪代码同形，故非漂移，但属设计空白。建议 `if not isinstance(raw, dict): result[f'plate_{ptype}'] = {'error': 'bad_payload'}; continue`。
- **❓逆向: `stream.py:166-178`** — `coverage` 用"取数次数/周期"估算（`0.8×tick×8/0.3`），而实际并发是 3 个 handler **顺序执行**、每个内部 8 宽（`BATCH_MAX_WORKERS`）⇒ 单 tick 实际并发取数 = 3×8 = 24，与 SAD §4.1 的"全局上游并发"口径需在容量评审时一并核对（本次未发现越界，仅登记口径差）。
- **❓逆向: `stream.py:97`/`payload_bytes()`** — 保留但声明"不参与调度"；`_reserve_for` 只信 `_Frame.size`，一致 ✅。若未来有人重新引入 `payload_bytes` 做决策，会与真实帧账口径冲突（已在 §10#14 登记）。

---

## 4. 漂移检测（P7a · 随 P5b 合并执行）

> **D1 契约核对**（以 `server.md` v1.1 / `stream.md` v1.1 为唯一来源；逐模块比对接口签名/字段/BR 落实）

### 4.1 无漂移（✅ 逐条核对通过）

**server.py（Layer 3）**

| 契约点 | 落点 | 结论 |
|---|---|---|
| `_JSON_SHAPES` 14 项 + `_SHAPES` 4 值 + batch 集合相等 + `/healthz` 不入表 | `server.py:446-471` | ✅ 断言齐备（含 `assert len==14`） |
| `_guard(fn,*,shape,requested,dropped,rss_info,feed_url)` 四 shape 降级体、非法 shape `ValueError`、不捕 `BaseException` | `server.py:504-526` | ✅ 与 §2.3 分派表逐格一致 |
| `_handle_stock_batch` 步骤 1-5（缺参 400 / 空码 400 / 截断 + `log.warning` 前 3 样本 / 只透传 `dropped` / 不重复组装） | `server.py:902-924` | ✅ BR-SRV-14..16 |
| `_get_or_fetch_feed`：miss → 建锁（立即释放）→ 二次 get → **仍 miss 才**取 `ttl = cache_policy('feed')['ttl']` → fetch → put | `server.py:936-954`（`ttl` 在 `949` 求值） | ✅ BR-SRV-6/7 + P2-1 求值点正确 |
| `_serve_feed` = `_guard(..., shape='rss', rss_info, feed_url)` | `server.py:956-963` | ✅ |
| `_plate_ttls()` → `base, max(3, base//4)`；hotplate offset 0/1/2；plate offset 0/1/2 | `server.py:571-574,318,377-381` | ✅ BR-SRV-10..13（三档未压平，亲测非同一值） |
| `_fetch_concurrent`：空 `{}`、单元素走当前线程、≤3 并发、**不抛**、顺序 = specs 顺序 | `server.py:546-568` | ✅ |
| longhu 2 URL 走 `fetch_json(..., encoding='gbk')` + 同一 `cache_policy('longhu')['ttl']`；解析逐字保留 | `server.py:144-215,489-499` | ✅ BR-SRV-9/30（无 `urlopen` 直连） |
| hotplate 分区 error 客体 + **全分区失败顶层 `error`**；部分失败无顶层 `error` | `server.py:331-350` | ✅ BR-SRV-31 |
| healthz：`check=0` 零上游；准入 `BoundedSemaphore(5)` 非阻塞；`_HealthBatch` 建账**先于**提交；五路销账；stale 路径不刷新快照 | `server.py:646-786` | ✅ BR-SRV-17..24（P1-1 核心） |
| `_run_health_checks`：每源按自身 `submitted_at` 3s、整体 10s 独立闸 | `server.py:718-737` | ✅ BR-SRV-20（10s 非死代码） |
| `_base_feed_entries` 15 条 + §2.9.1 三处 status 修正 | `server.py:593-625` | ✅ `/stock/data`→configured、`/stock/basic_info`→configured、`/stock/f10`→requires_chrome_cdp |
| `_serve_index` 三处 `needs_cdp` 修正 | `server.py:1028,1032,1031` | ✅ |
| `_cache_age` 只经 `_CACHE_AGE_DOMAINS → cache_policy(domain)['ttl']`，未登记 → `_DEFAULT_AGE_DOMAIN='f10'` | `server.py:475-485,972-976` | ✅ BR-SRV-8（无裸 TTL 字面量） |
| `BoundedThreadPoolServer(max_inflight=None)` 主端口 40 / 流端口 110 | `server.py:1066-1074`；`stream.py:743-754` | ✅ §2.7 / §10#11（P1-4 落地） |
| watchdog 委派 `watchdog_restart_skip_reason()`：非 None ⇒ 跳过并**顺延**；异常仅日志 | `server.py:1173-1183` | ✅ BR-SRV-26 |
| `_send_error(msg, write_body=)`、`_send_json(data, write_body=, cache=)`、`_send_text` | `server.py:926-934,978-987` | ✅ §10#3 |
| 4 面板 `page_data` 防御取数 + `timeline` 缺失 → `{'error': 'timeline unavailable'}`（禁裸 null） | `server.py:241-302` | ✅ BR-SRV-27 |

**stream.py（Layer 2）**

| 契约点 | 落点 | 结论 |
|---|---|---|
| `codes → frozenset` / `fields → tuple`；增删码**整体替换**（`_groups_lock` 内） | `stream.py:83-86,514` | ✅ BR-STR-1/4 |
| 广播锁序 `_groups_lock → g.conns_lock`，"取快照即释放"；`_build_frame`/`put_nowait` 在组锁外 | `stream.py:356-397` | ✅ BR-STR-2（`_build_frame` 在 `369`） |
| 僵尸组不建帧、不刷 `last_push_ts` | `stream.py:365-368` | ✅ BR-STR-3 |
| `_Frame{payload,size,sid,refs}`；`_frame_bytes_lock` 仅整数/dict 算术，metrics **锁外**发布；`_frame_release` 幂等 | `stream.py:236-286` | ✅ BR-STR-6..8（临界区无 IO、无嵌套——满足） |
| `_drain_conn_queue` 三处收口（`_serve_sse` finally 经 `_release_conn`、`destroy_group` 锁外、`_broadcast` put 后复检 `closed`）+ `None` 哨兵不计费 | `stream.py:303-316,536-537,395-396,740` | ✅ BR-STR-12/13 |
| 队列满 ⇒ 丢最旧保最新（二次入队失败 ⇒ 不 acquire）；`_reserve_for` 先腾位后入队 | `stream.py:374-394,373` | ✅ BR-STR-9/10/11 |
| `_reserve_for`：`skip` 排除集、**不** `pop(_group_bytes)`、`skip` 单调 ⇒ 终止 | `stream.py:319-354` | ✅ BR-STR-15（P2-6 修得正确） |
| C1/C2 判定、`active=sorted`、`view` 临时轮转视图、`_prefetch_advance('stream_refresh', len(sl), n)`、`lag=ceil(n/\|sl\|)` | `stream.py:161-197` | ✅ BR-STR-16..21/23 |
| **跳过 `_` 前缀键** | `stream.py:185-186` | ✅ BR-STR-22 / AR-7（fresh 分支；cached 分支见 P2-9） |
| handler 调用**不传 `dropped`** | `stream.py:181` | ✅ BR-STR-24 |
| `_FIELD_DOMAINS` 显式映射 + `cached_batch(域, rest)` | `stream.py:55,192` | ✅ P2-10 |
| `_read_json_body`：CL 非法/负/>65536 **不读体**；5s 预算且 `finally` 恢复 | `stream.py:575-604` | ✅ BR-STR-32 |
| `_serve_sse`：socket 超时 = `PING×2`；空闲 ping；`_frame_release` 在写完的 `finally`；慢客户端判据（写异常 ∧ 队列非满） | `stream.py:702-740` | ✅ BR-STR-31/14/35 |
| `MAX_GROUPS` 400 / `MAX_STREAM_CONNS` 503 / 连接注销幂等 | `stream.py:479-481,542-558,688-690` | ✅ BR-STR-29/30 |
| 僵尸组 300s 回收（TOCTOU 双检，锁序 groups→conns） | `stream.py:404-427` | ✅ BR-STR-33（`_group_bytes` 清理见 P2-5） |
| 9 个 stream metrics 名全部 ∈ `metrics._KNOWN` | `metrics.py:21-26` | ✅ AC-S10 |
| `MAX_GROUPS` 新增 400 失败模式 | `stream.py:480-481` / `doc/detailed/stream.md §2.1` | ✅ 设计已登记；**对外同步（API.md + 变更日志）仍待编排层执行** |

### 4.2 漂移项（D2/D3/D4，需编排层分派同步）

| # | 类型 | 漂移项 | 证据 | 处置建议 |
|---|------|--------|------|---------|
| DR-1 | **文档缺项（契约有、代码无）** | `server.md` §2.9 声明 `_health_snapshot() -> dict \| None`，实现未定义 | `server.py:752-763` 内联读取 | 文档删行 + 注明"内联于 stale 分支"（等同 P2-2） |
| DR-2 | **文档错项（契约不可实现）** | `server.md` §2.2 末条要求 `_handle_stock_batch` 断言 `_JSON_SHAPES[path]=='batch'`，该函数无 `path` 形参 | `server.py:902` | 文档改为"由 `_STOCK_BATCH_HANDLERS` 集合相等断言覆盖" |
| DR-3 | **契约未实现（安全）** | `server.md` §2.1 声明 `market` enum `['99','1','2','3']`，`server.py` 无校验 | `server.py:890-892` | 实现侧补 enum 校验（P1-3）；文档可保留 enum |
| DR-4 | **文档自相矛盾** | `stream.md` §2.3 表格称 `now` 是注入点（"`None` → `time()`"），正文/伪代码从未使用；`server.md`/`stream.md` 均如此（`server.md` 无此问题） | `stream.py:153,166`（`tick_interval()` 不接 `now`） | 文档二选一：删形参或改为"`now` 仅透传，tick 由墙钟决定"（等同 P2-8） |
| DR-5 | **文档错项（docstring 与代码相反）** | `stream.md` §5.2 `_pop_oldest_frame` 文档串"非 `_Frame` 亦返回（调用方判型）"，其代码 `return None` | `stream.py:289-300` | 文档对齐代码（`None` = 不计费、不归还） |
| DR-6 | **对外契约变更登记未闭环（4 项，均需编排层执行）** | ① `_cache_age` 行为变更：`/stock/announcement` 300→30/180、`/market/margin` 300→600（`server.md` §5.8 已登记）；② `/healthz` 新增 4 键 + `feeds[].status` **3 处取值变更**（§2.9.1）；③ 首页 CDP 列 3 处；④ `POST /stream/subscriptions` 新 400（`MAX_GROUPS`） | `server.py:475-485`、`593-625`、`1028-1032`；`stream.py:479-481` | 同步 `API.md` + 变更日志（`_PROGRESS.md` §A.2/§B 已列为"编排层同步项"） |
| DR-7 | **无害偏差** | `_broadcast` 未接收 `_reserve_for` 的返回值（详设 §2.5 写 `dropped = _reserve_for(...)`，变量未使用）；`_MAX_HEALTH_INFLIGHT` 同时以 `config.` 前缀与 `from .config import` 两种形式存在（后者未用） | `stream.py:373`；`server.py:40,579` | 登记即可（行为等价），顺手清理未用名 |

**D2 DOC_SYNC 追溯**：本 change-set 未见 `>>DOC_SYNC:` 标记输出（入参未携带）；上表 DR-1~DR-6 即为本层产出的"待同步清单"，与 `_PROGRESS.md` 的"编排层同步项 4 条"部分重叠，**未发现文档已被提前改动**（`server.md`/`stream.md` 仍为 v1.1 未变）。

**D3 规范合规（✅）**：全部相对导入（`.config`/`.cache`/`.utils`/`.stock_api`/`.market_api`/`.cdp_engine`）；命名 `handle_*`/`fetch_*` 合规；TTL 无裸字面量（`server.py` 的 `ttl=` 全部来自 `cache_policy`/`_plate_ttls`，`stream.py` 的 `0.8/0.3/60/8` 属 `STREAM-T32` 明示允许的机制常量）；`layerIsolation`：`stream.py` 未 import `cache`/`market_api`/`cdp_engine`/`utils`，`server→stream` 仅 `main()` 内延迟 import（`server.py:1209`）；`tech-stack.json` allowlist 全满足（`socket`/`concurrent`/`queue` 均在名单）；无新增第三方依赖。

**D4**：除上表 7 项外，**其余契约点无漂移**。

---

## 5. 覆盖与测试评估

### 5.1 已覆盖（✅ 关键断言到位）

**`tests/test_server_http.py`（新增 24 例，10 个 TestCase）**

| 关键断言 | 用例 | 评价 |
|---|---|---|
| `_SHAPES` / `_JSON_SHAPES==14` / batch 集合相等 / `/healthz` 不入表 | `ShapeTableTests` | ✅ 正是 P1-6 防复发护栏 |
| `_guard` object/text/batch/rss 四形态降级 + 非法 shape + `KeyboardInterrupt` 穿透 | `GuardTests` | ✅ 覆盖 §6.3 边界口径；rss 用 `ET.fromstring` 验证是合法 feed |
| plate 三档 TTL **互不相等** + `stagger==max(3,base//4)` + `_fetch_concurrent` 仅 1 次 3 段 | `PlateStaggerTests` | ✅ D-7 防压平的硬断言；`lambda url=url, ttl=ttl` 默认参数捕获陷阱被真实触发 |
| hotplate 全失败顶层 `error` / 部分失败无顶层 `error` | `HotplateFailureShapeTests` | ✅ BR-SRV-31 双向都测（比只测失败更有价值） |
| longhu 2 URL、`encoding=='gbk'`、同一 L4 TTL | `LonghuTests` | ✅ |
| feed 双检：单线程 + **8 线程并发**均只回源 1 次 | `FeedDoubleCheckTests` | ✅ 防击穿是最难测的点，并发版测法正确 |
| `_cache_age` 逐 path 走 policy + 未登记路径 + query 剥离 | `CacheAgeTests` | ✅ |
| healthz check=0 精确 schema（7 键、无 `stale`、15 条 feeds、无 `items`）+ 三处 status 修正 + **准入耗尽 → 立即 stale 且不触网** | `HealthPayloadTests` | ✅ 有界准入的"可达性"被真正验证 |
| `_max_inflight` 默认 = `MAX_INFLIGHT` / 显式 110 | `BoundedServerTests` | ✅（但见 5.2-G） |

**`tests/test_stream.py`（新增 11 组 + 4 条既有同步）**

| 关键断言 | 用例 | 评价 |
|---|---|---|
| frozenset/tuple + `.add` 抛 `AttributeError` + PATCH 后 `codes` **换新对象** | `FrozenGroupStateTests` | ✅ BR-STR-1/4（"类型即承诺"被测试钉住） |
| distinct 帧**只计一次**（3 连接 ⇒ `_queue_bytes == frame.size`、`refs==3`、`_live_frames==1`）+ drain 归零 + 幂等 | `FrameAccountingTests` | ✅ BR-STR-5/6/13 正面路径 |
| `None` 哨兵不计费（drain/`_pop_oldest_frame` 两入口） | `FrameAccountingTests` | ✅ BR-STR-12 |
| 队列满 ⇒ 丢 `frame-0`、保 `frame-7` + **新帧在且内容为最新** | `SSEQueueDropTests` | ✅ AC-A2"丢旧保新"精确断言 |
| `_reserve_for`：哨兵组**组账不被逐出**、只丢另一组、新帧可入队 | `ReserveSkipTests` | ✅ P2-6 的针对性回归（连"哨兵被消费后队首变真帧"都断言了） |
| C1 不切片/不读缓存；C2 切片 ≤56、每字段 1 次 `cached_batch`、warm 码不降级、`lag==ceil(300/56)` | `ShardingTests` | ✅ BR-STR-16..21 主路径 |
| `_errors` 不进帧（fresh 路径 + `_build_frame` 双层） | `UnderscoreKeyTests` | ✅ AR-7 唯一陷阱点 |
| `MAX_GROUPS` 400 文案 | `MaxGroupsTests` | ✅ 新增失败模式 |
| 销毁 vs 注册：404 + `conns` 空 + `_conn_count` 归零 + 不阻塞 | `DestroyVsRegisterTests` | ✅ P2-7 |
| `_read_json_body` 5s 预算/恢复/超时 → None/非法 CL 不触 socket | `ReadJsonBodyBudgetTests` + `ReadJsonBodyGuardTests` | ✅ BR-STR-32（`conn.settimeout.assert_any_call` 双向验证） |
| 僵尸组不建帧 / 不贡献活跃池 / 回收与保留边界 | `ZombieGroupTests` | ✅ BR-STR-3/33 |
| SSE 端到端收到 `event: quote` + `id` + 数据体 | `HttpIntegrationTests` | ✅ 真实 HTTP + 真实 `_refresh_pool`（C1 路径） |

### 5.2 未覆盖 / 覆盖不足（建议补测，按优先级）

| # | 缺口 | 对应详设用例 | 影响 |
|---|------|-------------|------|
| A | **`_HealthBatch` 在飞记账**：无一条用例断言"5 个 future 未结束前 `_health_sem._value == 0`"、"`_health_executor._work_queue.qsize() ≤ 20` 且不单调增长"、"恰好 release 一次（最终归位 5）"。现有 `test_bounded_admission_stale_path` 是**手工预占信号量**，验证的是"拒绝路径"，**未验证 P1-1 的修复本体** | `SRV-T34`（P1-1 核心） | 本次最重要的并发修复缺回归护栏；后续若有人把 release 挪回 `finally` 不会被测试拦住 |
| B | **帧计费竞态（P1-1 本评审发现）**：无用例覆盖"消费者落在 put/acquire 窗口内" | 新增 | 见 P1-1；建议按 5.2-A 同批补 |
| C | **`_broadcast` 的 put→closed 复检兜底**：无"先 `put_nowait` 再置 `closed` ⇒ 字节归零"的用例；`destroy_group` 后 `stream_queue_bytes` 归零（`STREAM-T9`）也未直接断言（现仅手工 `_drain_conn_queue`） | `STREAM-T9/T11` | BR-STR-13 三处收口只测了 1 处 |
| D | **游标轮转语义**：`ShardingTests.test_c2...` 把 `_prefetch_advance` patch 掉了，且 `fake_slice` 永远返回前 N 个 ⇒ **"连续 tick 切片不重叠、合并==全集、第 5 tick 回绕"完全未验证**（真 `_prefetch_slice`/`_prefetch_advance` 的集成未被任何用例驱动） | `STREAM-T14` | 分片轮转是本模块最易错的调度逻辑，"跳码/只刷前 56 码"这类 bug 不会被发现 |
| E | **AC-E2 并发上界**：无用例断言 hotplate/plate/longhu 的"3 段各 sleep(1s) ⇒ 总耗时 <2s（≈max）"；`PlateStaggerTests` 只断言"调用次数"，不断言**时间** | `SRV-T35` | P1-2 的核心指标（是否真并发、排队多久）无观测 |
| F | **HEAD 不写体**：无用例经真实 HTTP 断言 HEAD 的 200/400/404 分支 body 为空 | `SRV-T33` | 本次新增的 `write_body` 透传链（8 个调用点）无回归护栏 |
| G | **流端口 110 的传递**：`BoundedServerTests` 直接给 `BoundedThreadPoolServer(..., max_inflight=110)`，**未断言 `stream.make_stream_server()` 真的传了 110** | `stream.md §2.2 P1-4` | P1-4 的关键闭环（工厂函数）未被测试钉住，回归时静默失效 |
| H | `metrics` 名合法性哨兵：无"一轮 建组→广播→丢弃→销毁 后 `set(snapshot()) ⊆ _KNOWN`" | `STREAM-T29 / MET-T8b` | 低风险（名已 grep 核对 ✅），建议补 CI 断言 |
| I | 测试卫生：`HealthPayloadTests` 读到全局 `healthz_stale_total` 且依赖用例执行顺序；`test_bounded_admission_stale_path` 预占信号量后 `finally` 释放在测试失败时若线程异常可能残留（当前安全）；`_reset_frame_accounting` 直接改模块级私有量（可接受，但应注明"仅测试"） | — | 低风险；建议在 `setUp` 里快照/恢复 `_health_sem` 与 metrics 计数器 |

### 5.3 结论

新增测试**质量高于数量要求**：plate 三档互不相等、distinct 计费只计一次、`skip` 组账不低估、销毁 vs 注册、非法 CL 不触 socket —— 这些都是"能挡住真实回归"的断言。缺口集中在**本次修复的并发本体（P1-1 的 `_HealthBatch`、P1-1' 的计费窗口）与"时间维度"（AC-E2 并发耗时）**，以及**分片轮转的真实游标集成**。建议在修 P1-1/P1-2 时同批补 A/B/D/E 四条（成本低、收益最高）。

---

## 6. 放行建议

| 门禁 | 结论 |
|---|---|
| **P0 阻断** | 无（0 条） |
| **P1（生产版阻断）** | 4 条，建议按序修：P1-1（计费竞态，1 处小改 + 1 条测试）→ P1-2（扇出等待上界）→ P1-3（`market` enum 校验，1 行）→ P1-4（预算与配置联合求解，需容量决策） |
| **P2** | 12 条，可随 P1 修复批次一并处理（P2-6/7/10 建议同批，均为 10 行内改动） |
| **漂移（P7a）** | 无阻塞性漂移；DR-1~DR-5 为文档侧修正，DR-6 为对外契约同步（4 项，需编排层执行 `API.md` + 变更日志） |
| **端锁定** | 无违反：未改路由/方法/SSE 帧格式；新增 400（`MAX_GROUPS`）与 `feeds[].status` 取值变更均已在详设登记、同步权归编排层 |
| **layerIsolation / tech-stack** | ✅ 合规 |

**下一跳建议**：`>>P7b` 仅需按 DR-1~DR-6 分派文档同步（无代码契约漂移需要回改设计）；代码侧由 bug-fixer/code-developer 闭环 P1-1~P1-3 后，**只需一轮定向复审**（P1-4 若涉及容量参数调整，须回到 `task-decomposer` 同步 `stream.md §3.4` + `config.md` 预算常量）。

> `>>PROJECT: 并发/锁序 → 计时/字节类模块级账簿状态一律由单一叶子锁保护、临界区仅整数/dict 算术，metrics 发布放在锁外（≥2 处：_frame_bytes_lock、_conn_count_lock，且 stream.md §7.2 明文约束）`
