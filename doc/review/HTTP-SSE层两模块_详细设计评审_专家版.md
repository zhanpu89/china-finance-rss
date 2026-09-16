# HTTP/SSE 层两模块 详细设计评审报告（专家版）

> 报告编号 **REV-DES-20260915-002** · 评审对象 `doc/detailed/server.md` v1.0（1224 行）+ `doc/detailed/stream.md` v1.0（1151 行）
> 参考基线：SAD v1.3 / `config.md` v1.1 / `cache.md` v1.1 / `metrics.md` v1.1 / `stock_api.md` v1.0 / `market_api.md` v1.0 / `cdp_engine.md` v1.0 / `_PROGRESS.md` / PRD v0.3（30 AC）/ 现存代码 `server.py`·`stream.py`（只读核对）
> 评审模式：详细设计（纯后端） · 评审者 review-expert · 日期 2026-09-15
> 就绪检查 ✅：两份文档 >500 行、头部含版本/状态/日期/作者、无占位符、核心内容完整、§3 为 yaml。（不触发空转熔断）

## 一、评审概要

- **结论：⚠️ 阻断**（无 P0；**P1×4**，超阈值 2）→ **不建议直接进入 code-developer**，须先闭合 P1-1~P1-4（或由编排层对已登记项做显式裁决并回写文档）。
- 问题分布：**P0×0 / P1×4 / P2×10**。
- **可编码性总评：整体已达"无需再问"水平。** 签名/数据结构/伪代码/边界值/锁序/错误语义基本齐全，偏差登记纪律良好（server §10 共 14 项、stream §10 共 16 项），跨模块接口抽查 6 点全部精确一致。扣分集中在两处**机制级缺口**：healthz 有界准入的真实性（P1-1）与外部上游串行调用未收敛至 AC-E2（P1-2）。
- **正向确认**：server 侧 8 项钉死项 6 ✅ / 2 ⚠️（§四）；stream 侧 7 项钉死项**全部 ✅**；两模块锁序自洽、`_frame_bytes_lock` 无锁序风险；"销毁 vs 入队"竞态已真闭合。
## 二、问题清单

### P1（阻断，必须修正或由编排层显式裁决）

| ID | 文件:章节 | 描述 | 修正建议 | 关联 AC |
|----|----------|------|---------|---------|
| **P1-1** | server.md §2.6 / §5.6 / BR-SRV-19 | **healthz 准入位在"提交的任务"完成前即释放**。`_run_health_checks` 在 `elapsed ≥ _HEALTH_SOURCE_BUDGET(3s)` 时 `break`，未完成的 future **继续运行**；`build_health_payload` 的 `finally` 随即 `_health_sem.release()`。故信号量只约束"本轮调用"，不约束"在飞任务"。按 **AC-S8 自身的场景**（上游慢 5s、并发 10 个 check）持续请求时：每轮被准入的请求各自 `submit` 5 个任务，而准入位在 ~3s 就归还 ⇒ 专用执行器（`max_workers=5`、**工作队列无界**）任务持续累积，重演 SAD P1-3 要消除的"`submit()` 无界队列堆积 / 放大器"。§2.6 的断言"在飞数同时钉死执行器内部队列长度 ⇒ 无界队列从不堆积"在实现层面**不成立**（文档声称与伪代码相矛盾）。 | 让准入位覆盖任务**实际在飞**：① `finally` 内 `wait(pending, timeout=…)` 等本轮 5 个 future 全部结束再 `release`；或② 按 future `done_callback` 计数释放；或③ 增设"任务级"信号量 `_health_task_sem`（`submit` 前 acquire、done-callback 释放）。同时修正 §2.6 表述与 SRV-T20/T22 的断言口径（补"持续慢 check 下执行器队列不增长"的断言）。 | **S8**（主）/ S9 / S10 |
| **P1-2** | server.md §5.5 / §6.2#6 / §10#10 | **外部上游串行调用未收敛到 AC-E2「任何单请求 ≤15s」**。① `/cls/hotplate` 仍为 3 次**串行** `fetch_json`（最坏 ≈30s）——而 **SAD §4.1 明令本轮"改为 ≤3 并发，P95 = max 而非 sum（本次顺带修）"**，本文未落实、§10 也未登记；② `/cls/plate` 同为 3 次串行（≈30s，SAD 未点名但 AC-E2 同样适用）；③ `/ths/longhu` 2 次串行（≈20s），§10#10 将其**误登记为 AC-S7 的边界**——S7 是"分层线程 ≤11s 释放"，"单请求 ≤15s"属 **AC-E2**。§6.2#6 的"单请求上界"清单亦遗漏 hotplate/plate。 | ① 按 SAD §4.1 把 hotplate 三分区改并发（`ThreadPoolExecutor(max_workers=3)` / `concurrent.futures` 收集），使 P95 = max；② plate 同理（AC-E2 一致性）；③ longhu 两 URL 并行化，或显式定"单请求预算"并在 §10 登记；④ 更正 §10#10 的 AC 归属为 E2，并在 §6.2#6 补齐 hotplate/plate 上界。 | **E2**（主）/ S7 |
| **P1-3** | server.md §2.8 / §5.5 / §6.1 / SRV-T14 | **`/cls/hotplate` 全分区失败未补顶层 `error`**。SAD §2.3 D-4 与 §2.4（v1.1 修 P2-3②）把"分区 error 客体（分区可独立降级）**＋ 全部分区失败时顶层补 `error`**"钉为**唯一口径**；本文 §5.5 仅在分区内落 `{'error':…}`，SRV-T14 进一步明文断言"三分区全失败 ⇒ 三块均为 error 客体（顶层**不加** error——现状口径）"，与 SAD 直接矛盾，且 §10 **未登记**该偏离。照此编码将产出不符合 SAD v1.3 的行为，且 AC-A5 的单体/面板 error 客体口径失守。 | 在 `handle_cls_hotplate` 三分区全失败时补顶层 `error`（值可取三块 error 摘要），并同步修改 SRV-T14 断言；如坚持现状口径，则须在 §10 新增偏离登记，并由编排层显式回退 SAD §2.3 D-4 的钉死口径。 | **A5**（主）/ S4 |
| **P1-4** | server.md §2.7 / §10#11 · stream.md §10#13 | **流端口 inflight=40（原 220）把 SSE 连接上限从 100 压到 ≈40**。`_max_inflight = MAX_INFLIGHT(=`MAX_WORKERS*2`=40)` 与 `max_workers` 解耦后，`make_stream_server(max_workers=110)` 仍只准入 40 个在飞 ⇒ 第 41 个 `GET /stream/quote/<sid>` 在 `process_request` 阶段即被 503，`MAX_STREAM_CONNS=100` 与 `_register_conn` 的 100 阈值**沦为死代码**。**AC-E5「100 个 SSE 连接同一 200 码×3 字段组」与 AC-E7「100 连接含 1 慢客户端」不可复现**。该变更已登记（§10#11 / §10#13）但**未解决**。 | 给 `BoundedThreadPoolServer.__init__` 增 `max_inflight=None` 形参：主端口默认 `MAX_INFLIGHT`；`make_stream_server` 显式传 `MAX_STREAM_CONNS + 10`（=110，恢复现状语义）。由编排层确认后落两文档。 | **E5 / E7**（主）/ E8 |
### P2（不阻断，建议修正）

| ID | 文件:章节 | 描述 | 建议 |
|----|----------|------|------|
| P2-1 | server.md §5.4 vs §7.4 | §5.4 在首个 `feed_cache_get` **之前**求值 `ttl = cache_policy('feed')['ttl']`，与 §7.4 明文"实现要求：`ttl` 必须在 miss 之后求值"自相矛盾（命中路径白算 policy）。 | 把 `ttl` 求值移到二次 get 仍 miss 之后；或删 §7.4 的要求，二者取一并保持唯一表述。 |
| P2-2 | server.md §2.6.1 / §5.6 | `while pending: if elapsed >= _HEALTH_TOTAL_BUDGET(10) or elapsed >= _HEALTH_SOURCE_BUDGET(3): break` —— 3s 条件**全局**生效，10s 整体预算成死代码；"单源 3s"退化为"全部源 3s"。SRV-T21 的"5 源全慢 5s ⇒ 总耗时 ≤10.3s"永不触发（实为 ~3.2s）。 | 按每个 future 的提交时刻跟踪**单源**预算，整体预算独立；或明确接受"统一 3s"并删除 10s 常量与相应断言（同时见 P1-1）。 |
| P2-3 | server.md §3.1 | `feeds[].status` 注释称 `check=1 → ok/error/timeout（覆盖前两者）`，但 `_run_health_checks` 只覆盖 5 个 RSS；10 个 JSON/CDP 条目在 check=1 下仍为 `configured`/`requires_chrome_cdp`。 | 注释限定为"仅 5 个 RSS 源"，避免下游误判 schema 语义。 |
| P2-4 | server.md §2.2 | 分组视图写 `object（8）` 并把 `/healthz` 计入，但 `/healthz` **不在** `_JSON_SHAPES`（表内 object 实为 7）；`assert len(_JSON_SHAPES)==14` 正依赖此。 | 明确标"object 7（`/healthz` 复用同 shape 但不入表）"，防编码者把它加入表而触发导入期 assert 失败。 |
| P2-5 | server.md §2.10 | import 清单名为"逐行精确"却**混入未变更行、遗漏变更行**：① 未列"删除 `from urllib.request import Request, urlopen`"（longhu 改走 `fetch_json` 后二者成为未用 import）；② 未列 `main()` 仍需要的 `stock_api` 4 个 prefetch loop、`market_api`、`utils` import。若按字面整体替换将破坏 `main()`。 | 改为"完整 import 块"，或显式标注"仅列变更行、其余保留"；补 `Request/urlopen` 删除行。 |
| P2-6 | stream.md §5.2 / §7.4 | `_reserve_for` 在"选中靶连接的队首为 `None` 哨兵 / 队列瞬时为空"时**整条** `_group_bytes.pop(sid)`，而该组仍有 `refs>0` 的帧 ⇒ `_group_bytes` 系统性低估，"从保留字节最大组丢最旧"的确定性受损（`_queue_bytes` 仍准确，内存上界不破）。 | 改为只移除该组的**本轮候选资格**（临时排除集），而非逐出其全部字节；或按需重算该组保留字节。 |
| P2-7 | stream.md §7.4 | "销毁 vs 入队"已真闭合（put 后复检 `closed` + `destroy_group` 锁外排空，两种时序均覆盖 ✅）；但相邻的**"销毁 vs 注册"未覆盖**：`_serve_sse` 取得 `g` 后 `destroy_group` 已 `pop+clear`，随后 `g.conns.add(conn)` 把连接挂进已销毁组 ⇒ 永不被唤醒（`closed` 恒 False），handler 阻塞至客户端断开，`_conn_count` 长期占用。属既有竞态，非本次引入。 | `g.conns.add(conn)` 后在 `_groups_lock` 下复检 `get_group(sid) is g`；否则立即 `conn.closed=True` 并走 `_release_conn` 收口。 |
| P2-8 | stream.md §11.1 | `test_broadcast_serves_live_group_only` 被列为"必改"，但 patch 返回 bytes 在新 `_broadcast` 下**仍可通过**（`_Frame.size=len(bytes)`，无 `.encode`），非破坏性。真正必改为 **4 条**（已全部登记，见 §五）。 | 降级为"可选清理（改回 str 以符 `_Frame.payload` 契约）"，避免误导 tester 做无谓改动。 |
| P2-9 | stream.md §3.5 | `stream_refresh_lag_ticks` owner 记为 `_refresh_pool`，而 `metrics.md` §3.2 记为 `stream.push_loop`（均属 stream 内，不影响冻结注册表）。 | 与 `metrics.md` 对齐为同一 owner 表述。 |
| P2-10 | stream.md §2.3 vs §5.3 | §2.3 伪代码写 `cached_batch(field, rest)`（隐含"字段名==域名"），§5.3 用 `cached_batch(_FIELD_DOMAINS[field], rest)`；§3.6 才显式化该等价关系。 | 全篇统一用 `_FIELD_DOMAINS[field]`，防未来字段名/域解耦时静默取空缓存。 |
## 三、设计的缺陷详情

### 3.1 并发（stream 核心，结论：**设计正确、锁序自洽**）

- **锁清单与锁序自洽** ✅：`_frame_bytes_lock` 被正确设为**叶锁**——`_frame_acquire/release` 临界区仅整数/dict 算术，`metrics.set_gauge` 发布于锁外；`_reserve_for` 分两次独立加锁（`_frame_bytes_lock` 选靶 → 释放 → `get_group`/`conns_lock` 取快照 → 释放 → `_frame_release`），**全程无嵌套**。BR-STR-8 的"持 `_frame_bytes_lock` 时不得取 `_groups_lock`/`conns_lock`/`_conn_count_lock`"未被违反。`metrics._lock` 保持叶子（`metrics.md` §7.2）方向一致。
- **`_broadcast` 的帧构建/入队均在组锁外** ✅：`codes`/`fields` 为 `frozenset`/`tuple`（C-1），可无锁遍历；`put_nowait` 用队列自带锁。AC-S2 的"tick 劣化 ≤20%"由结构而非调优保证。
- **"销毁 vs 入队"竞态真闭合** ✅：put 早于 `destroy_group` 排空 ⇒ destroy 的清空回收；put 晚于排空 ⇒ `_broadcast` 入队后复检 `conn.closed` 触发 `_drain_conn_queue`。`_frame_release` 幂等（`refs<=0` 直接返回）+ `_drain_conn_queue` 幂等，重复排空不产生负值。计费顺序"先 `put_nowait` 成功、再 `_frame_acquire`"自洽（未入队不计费）。**唯一残留**是相邻的"销毁 vs 注册"（P2-7）。
- **不变式可白盒断言** ✅：`stream_queue_bytes == Σ_{refs>0} size`、`refs == 持有该帧的连接数`、`_queue_bytes ≤ BUDGET`（先腾位后入队 ⇒ 新帧必可入队，绝不丢最新）。`None` 哨兵不计费已在 `_drain_conn_queue`/`_pop_oldest_frame` 落实。
- **healthz 并发是唯一真实缺陷**（P1-1）：准入位早释放致无界队列可堆积，与 SAD ADR-006 的"队列从不堆积"目标相悖。

### 3.2 异常与错误语义（结论：**分派表精确，一处 SAD 口径失守**）

- `_guard` 四 shape 降级体逐一钉死，捕获 `Exception`（不捕 `BaseException`），异常落日志不冒泡，`BrokenPipe/ConnectionReset` 归 `do_GET/do_HEAD`（写入期）——与 SAD §2.4 / ADR-007 一致 ✅。
- 值域边界"批量无顶层 `error`、单体无逐码值域"（BR-SRV-5）与 AC-A5 一致 ✅；400/404/503/200-error/200-值域五类矩阵齐备 ✅。
- **缺陷**：`/cls/hotplate` 全分区失败缺顶层 `error`（P1-3），且 SRV-T14 反向固化了该行为。

### 3.3 契约与可编码性（结论：**达标，个别表述需收口**）

- `_JSON_SHAPES`（14 项 + `assert`）、`_STOCK_BATCH_HANDLERS` 同集合断言、`_CACHE_AGE_DOMAINS`、`_plate_ttls()`、`_Frame`/计费原语、healthz 精确 schema——均可直接落地。
- `dropped` **单组装点**符合 `_PROGRESS.md` §B 锁定契约：server 只注入 `dropped` 参数，`build_batch_response` 仅在 handler 内（及 `_guard` 异常兜底）调用 ✅。
- 待收口：§5.4/§7.4 的 ttl 求值点矛盾（P2-1）、§3.1 的 status 注释（P2-3）、§2.2 的 object 计数（P2-4）、§2.10 import 清单不完整（P2-5）、§2.6.1 两级预算（P2-2）。
## 四、SAD v1.3 钉死项逐项落实表

### server.md

| SAD v1.3 钉死项 | 落实 | 证据 / 缺口 |
|-----------------|------|------------|
| `_guard` 覆盖 **14 JSON + 5 RSS + healthz** | ✅ | §2.2 `_JSON_SHAPES`(14)+`assert`、§2.3 分派表、§5.1/§5.2；`/`、`/opml.xml` 显式排除（§6.3/§10#4，有据） |
| feed **双检防击穿**（miss→lock→二次 get→fetch→put） | ✅ | §2.5/§5.4 按序 ①②③④；锁序"取锁表即释放再进 per-path 锁"（§7.2#1）与 `cache.md` §2.4 硬约束一致 |
| plate **stagger 保留**（不得压成同一 TTL） | ✅ | §4.3 BR-SRV-10~13、§5.5 `_plate_ttls()=max(3, base//4)`、offset=分区序；SRV-T13 断言三档互不相等（12/15/18 · 120/150/180） |
| `dropped` 注入 `build_batch_response` | ✅ | §2.4/§5.3 只注入 `dropped` 参数、不重复组装；`_guard` 异常兜底再传 `dropped`（§5.1） |
| longhu GBK 走 `fetch_json` | ✅ | §4.2 BR-SRV-9、§5.5 `fetch_json(..., ttl=cache_policy('longhu')['ttl'], encoding='gbk')` ×2；AC-E9 计数口径已澄清为"每 URL 1 次、共 2" |
| healthz `BoundedSemaphore(5)` 有界准入（stale 可达可测） | ⚠️ | 原语存在、stale 路径可达（§2.6/§5.6）；**但准入位在任务完成前释放 → 执行器无界队列可堆积**（P1-1），§2.6"从不堆积"断言不成立 |
| `MAX_INFLIGHT` 显式 + 503 | ⚠️ | 显式化与"立即 503 + `http_503_total`"✅（§2.7/§5.7）；**但流端口共用 40 → SSE 100 连接上限失效**（P1-4） |
| CDP 标注 **3 处修正** | ✅ | §2.9.1：`/stock/data`→configured、`/stock/basic_info`→configured、`/stock/f10`→requires_chrome_cdp；首页 CDP 列同步（SRV-T25/T26） |
| **SAD §2.3 D-4 / §2.4：hotplate 全分区失败补顶层 `error`** | ❌ | §5.5 未补；SRV-T14 明文反向固化；§10 未登记（**P1-3**） |
| **SAD §4.1：`/cls/hotplate` 3 次串行 → ≤3 并发（本次顺带修）** | ❌ | §5.5 仍串行；§10 未登记（**P1-2**） |

### stream.md

| SAD v1.3 钉死项 | 落实 | 证据 |
|-----------------|------|------|
| `codes→frozenset` / `fields→tuple` 不可变 + 帧构建移出锁区 | ✅ | §5.1 构造、§5.4 `_build_frame(snapshot, codes, fields)` 锁外调用（ADR-004） |
| `_Frame{payload,refs}` + `_frame_bytes_lock` + `_frame_acquire/release` + `_drain_conn_queue` 三处 + `None` 哨兵不计费 | ✅ | §5.2 原语；三处 = `_serve_sse` finally（经 `_release_conn`）/`destroy_group` 锁外/入队后复检 `closed`；哨兵在 §5.2 `_pop_oldest_frame`·`_drain_conn_queue` 跳过（BR-STR-12/13） |
| 队列字节预算 + 确定性丢弃（**绝不丢最新**） | ✅ | §3.4/§5.2 `_reserve_for` 先腾位（B=128MB ≥ F_max）；候选=最大 `_group_bytes` 组 × 最满连接 × 队首（P2-6 为精度瑕疵，不改内存界） |
| 分片轮转 `|slice| ≤ 56` 码 | ✅ | §3.3 派生（盘中 coverage=170→coverage_codes=56；非盘 853）、§5.3 C1/C2 分支 + `_prefetch_slice/_prefetch_advance('stream_refresh')`；`_prefetch_slice` 语义与 `stock_api.md` §5.12 一致（游标共享、稳定序 `sorted(active)`） |
| 跳过 `_` 前缀键（AR-7） | ✅ | §5.3 `if not isinstance(code,str) or code.startswith('_'): continue`（BR-STR-22，STREAM-T16 必测） |
| `_read_json_body` 5s 预算 | ✅ | §5.7 `settimeout(MGMT_BODY_TIMEOUT)`→read→`finally` 恢复；非法 CL 不读体、不触碰 connection（BR-STR-32） |
| `MAX_GROUPS` 400 | ✅ | §5.6 `create_group` 在 `_groups_lock` 内判 `>= MAX_GROUPS`；§2.1/§6.1 登记新增失败模式；§10#9 声明端锁定显式例外 |
## 五、行为变更与测试影响核对

| 行为变更 | 是否登记 | 核对结论 |
|---------|---------|---------|
| 流端口 inflight 40（原 220） | ✅ 已登记（server §10#11 · stream §10#13） | 登记属实，**但未解决**：与 `MAX_STREAM_CONNS=100` 冲突，AC-E5/E7 不可复现 → **P1-4** |
| announcement TTL L4(300) → L3(30/180) | ✅ 已登记（server §5.8 表 · config/stock_api 同批） | 与 SAD Q5 / `cache.md` 一致；`_cache_age` 与 handler TTL 同源 ✅ |
| `_cache_age` margin 300→600、面板/healthz/`/`/opml 走 `_DEFAULT_AGE_DOMAIN='f10'`(300) | ✅ 已登记（server §5.8 · §10#2） | 逐 path 值与 `cache_policy` 对齐（SRV-T16 可断言）✅ |
| `/healthz` `cache_ttl` 取值改 `cache_policy('feed')['ttl']` | ✅ 已登记（§3.1/BR-SRV-23） | 字段名不变、含义跟随 policy ✅ |
| `feeds[].status` 3 处取值修正 + 首页 CDP 列 3 处 | ✅ 已登记（§2.9.1/§10#7） | 属"改既有字段取值"，同步权归编排层；文档已标 🟠 STABLE 例外 ✅ |
| `POST /stream/subscriptions` 新增 `MAX_GROUPS` 400 | ✅ 已登记（stream §2.1/§6.1/§10#9） | 新失败模式，端锁定显式例外 ✅ |
| **既有测试必改** | ✅ 已登记（stream §11.1 · server §10.1 交叉引用） | **真正破坏性 = 4 条**，全部在 stream：`test_create_group_valid_codes_and_fields`（`fields` list→tuple）、`test_build_frame_maps_only_group_fields`（2 参→3 参）、`test_build_frame_skips_codes_missing_from_snapshot`（2 参→3 参）、`test_broadcast_on_full_queue_drops_oldest_keeps_newest`（字符串夹具→`_Frame` + `.startswith` 会 `AttributeError`）。server 侧 2 条为跨模块交叉引用（`test_fetch_json_leader_failure_does_not_stampede`→cache、`test_sector_cache_bounded`→stock_api）。**§11.1 多列了 1 条非破坏性用例（P2-8）** |
| 既有"无需改"用例核对 | — | 已只读核对：`HttpIntegrationTests.test_sse_stream_receives_quote_frame`（`_FIELD_HANDLERS` 1 字段 × 1 码 ⇒ C1 分支，不触 `cached_batch`/`_prefetch_slice`）✅；`ZombieGroupTests`（僵尸组不建帧、`_build_frame` patch 可兼容）✅；`ReadJsonBodyGuardTests`（非法 CL 在触碰 `connection` 前返回，`getattr(self,'connection',None)` 向后兼容）✅；`BatchShardingTests`（`handle_cls_basic_infos` 全成功 ⇒ 无 `_errors`）✅ |
| 新增测试量 | — | server SRV-T1~T33（33 条）、stream STREAM-T1~T32（32 条），映射到 AC ✅ |

## 六、AC 覆盖缺口清单

| AC | 承载模块 | 设计落点 | 结论 |
|----|---------|---------|------|
| **E2**（任何单请求 ≤15s） | 基础层 + **server** | server §6.2#6 只列"REST 批量 ≤15s / CDP ≤8s / longhu 2×10s" | ❌ **缺口**：`/cls/hotplate`（≈30s）、`/cls/plate`（≈30s）、`/ths/longhu`（≈20s）均越界；longhu 被误记为 S7（**P1-2**） |
| **A5**（错误语义表） | server | §2.1/§6.1 矩阵 | ⚠️ `/cls/hotplate` 全分区失败口径与 SAD 不一致（**P1-3**） |
| **S8**（健康检查不放大） | server | §2.6/§5.6 有界准入 | ⚠️ 准入位早释放 ⇒ 慢 check 持续负载下执行器队列可堆积（**P1-1**） |
| **E5 / E7**（100 连接 / 慢客户端有界） | stream（受 server inflight 制约） | stream §5.4/§5.5 队列与计费 | ⚠️ 流端口 inflight=40 ⇒ 100 连接不可复现（**P1-4**） |
| S1 / A3 / A8 / A9 / E8 / S4 / S5 / S7 / S9 / S10 / E9 | server | §9 追溯矩阵逐条有落点 | ✅（E9 计数口径已按 SAD 澄清） |
| S2 / A1 / A2 / A3(调度侧) / A7 / A10(陷阱点) / E5 / E7 / S7 / S9 / S10 / S11 | stream | §9 追溯矩阵逐条有落点 | ✅（A1 的 warm/冷码口径与 SAD P2-N2 一致） |

> 说明：server 未承载的 E1/E3/E4/E6 与 A3/A4/A6 归基础层/数据层，两文档已显式声明归属，无越界；**唯一归属错误**是 longhu 的单请求上界（E2 被写成 S7）。
## 七、跨模块接口对齐抽查（6 点，全部精确一致）

| # | 调用点 | 权威定义 | 结论 |
|---|--------|---------|------|
| 1 | server §5.4 `feed_cache_put(path, xml, ttl)` / `feed_cache_get(path)->str|None` | `cache.md` §2.4 `feed_cache_get(path)`、`feed_cache_put(path, xml, ttl)` | ✅ 一致（LRU/TTL/清扫在 cache 层，双检在 server 侧，与 `cache.md` §2.4 硬约束同序） |
| 2 | server §5.1 `build_batch_response(codes, {}, errors, dropped=dropped)` | `cache.md` §2.5 `build_batch_response(requested, results, errors=None, dropped=0)` | ✅ 一致（纯函数；`_` 前缀跳过 / data+error 冲突 / 未知 kind 归一由 cache 内置） |
| 3 | server §5.5 `fetch_json(url, headers, ttl=…, encoding='gbk')` | `cache.md` §2.1 `fetch_json(url, headers=None, ttl=None, encoding='utf-8')` | ✅ 一致（默认 utf-8 兼容既有 18 调用点） |
| 4 | stream §5.3 `cached_batch(domain, rest)` / `_prefetch_slice(view, lock, 'stream_refresh', size)` / `_prefetch_advance('stream_refresh', len(sl), n)` / `BATCH_MAX_WORKERS` | `stock_api.md` §2.6/§2.7/§5.12/§5.13 | ✅ 一致（`_prefetch_slice` 只依赖 `list(pool.keys())` + 共享游标，`view` 为局部轮转视图；返回 `(slice,next_cursor)` 且不改游标） |
| 5 | server §2.8/§5.6/§5.7 `page_data(page)` / `restart_window_snapshot()` / `watchdog_restart_skip_reason()` | `cdp_engine.md` §2.1/§2.2/§2.3 | ✅ 一致（`page_data` 总函数；watchdog 返回 `None` 才 `full_chrome_restart()`；`page_data` 对空 dict 也返回 `None`，需注意面板空数据由"填充键 dict"变为 error 客体，属 R18 预期，建议 §2.9 补一句） |
| 6 | 两模块全部 metrics 名（`http_503_total`、`healthz_stale_total`、`healthz_inflight`、`stream_frame_*`、`stream_queue_bytes`、`stream_tick_*`、`stream_refresh_lag_ticks`、`stream_slow_client_total`） | `metrics.md` §3.2 `_KNOWN` 冻结注册表 | ✅ 全部 ⊆ `_KNOWN`（20 名内），无越界写入 |

> 依赖方向：server ← {stock_api, market_api, stream（**仅 main() 延迟 import**）, cache, config, metrics, utils}；stream → stock_api（同层既有，扩展至 `cached_batch`/`BATCH_MAX_WORKERS`/两轮转原语，方向不变、无环）。**零第三方依赖 / layerIsolation：未发现违规 import**（`stream` 未 import cache/market_api/cdp_engine/utils；`server` 未新增第三方模块）。

## 八、逆向审查记录（Step 1.5）

- ⚠️ 逆向审查（反证）：若"准入位 == 在飞任务"的假设不成立会怎样？→ 已验证：确实不成立（P1-1），慢上游 + 持续 `?check=1` 会让无界执行器队列累积，重回被修复的放大器。
- ⚠️ 逆向审查（遗漏）：AC-E2 的"任何单请求 ≤15s"在 server 侧无界落点（hotplate/plate/longhu 串行）——文档把 E2 整体推给基础层，掩盖了 server 自有的 3 个端点（P1-2）。
- ⚠️ 逆向审查（误导）：§2.6 声称"执行器内部队列从不堆积"给出**虚假安全感**——伪代码实现与之相反（P1-1）；SRV-T14 把"顶层不加 error"写成"现状口径"，误导编码者产出与 SAD 相悖的行为（P1-3）。
- ⚠️ 逆向审查（断链）：SAD §4.1 的 hotplate 并发改造在详设层**整条丢失**（需求→架构→详设断链），且 §10 未登记（P1-2）。
- ✅ 逆向审查（不可逆）：本设计不涉及资金/数据落库/不可逆写；进程内存为纯内存态，重启即恢复；`destroy_group`/`_drain_conn_queue` 的归还路径已覆盖主要终止路径（P2-7 为残留窗口）。
- ✅ 逆向审查（误导，正向）：§10 偏差表把 `_DEFAULT_AGE_DOMAIN='f10'` 的"无语义选择"、`longhu` 常量未上收、`/`·`/opml` 不纳入 guard 等逐条显式登记，透明度良好。

## 九、评审建议

1. **必须先闭合 P1-1~P1-4**（或由编排层对 P1-2/P1-3/P1-4 这三个"涉及 SAD/端锁定"的项做显式裁决并回写两文档 + SAD 侧登记）。建议优先级：P1-4（参数化 `max_inflight`，改动最小、恢复 AC-E5/E7）→ P1-3（补顶层 error，改动最小）→ P1-2（hotplate/plate 并发 + longhu 并行化）→ P1-1（healthz 准入位语义重写，需同步改断言）。
2. P2 项建议在**同一轮修订**内收口（多为表述级，成本低），尤其 P2-5（import 清单）与 P2-1（ttl 求值点）会直接影响编码正确性。
3. 建议 tester 侧新增断言：healthz "持续慢 check 下执行器队列不增长"（补 AC-S8 缺口）、hotplate 单请求耗时上界（AC-E2）。
4. 修订后按本报告 §四/§六 逐项复核即可放行；stream.md 除 P2-6/7/8/9/10 外**无需返工**。

## 十、评审结论

**⚠️ 阻断**——无 P0，但 P1×4（生产版 P1 阻断）。两文档在**结构完整性、契约精确度、锁序正确性、跨模块对齐**上均达高水准，可编码性整体合格；阻断性质为**局部机制缺口**而非体系性问题：healthz 准入位语义（P1-1）、外部上游串行未收敛 AC-E2 且漏落实 SAD §4.1（P1-2）、hotplate 全失败口径与 SAD 相悖（P1-3）、流端口 inflight 致 SSE 上限塌缩（P1-4）。**闭合（或由编排层显式裁决）上述 4 项后即可放行 code-developer。**

## 变更记录

| 版本 | 日期 | 说明 |
|------|------|------|
| 1.0 | 2026-09-15 | 首轮详设评审（server.md v1.0 + stream.md v1.0）；P0×0 / P1×4 / P2×10；结论 ⚠️ 阻断 |

