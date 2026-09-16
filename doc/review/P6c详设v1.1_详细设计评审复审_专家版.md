# P6c 详设 v1.1 修订 详细设计复审报告（专家版）

> **报告编号** REV-DES-20260916-003 · **类型** 详细设计**复审**（只核验修订项，不全文重审）
> **被评物** `doc/detailed/server.md` v1.1 · `stream.md` v1.1 · `stock_api.md` v1.1 · `market_api.md` v1.1 · `cdp_engine.md` v1.1
> **对应首评** `doc/review/HTTP-SSE层两模块_详细设计评审_专家版.md`（REV-DES-20260915-002，P1×4）· `doc/review/数据层三模块_详细设计评审_专家版.md`（REV-DES-20260915-002，P1×2）
> **复审基线** SAD v1.3 · PRD **v0.4** · `config.md`/`cache.md`/`metrics.md` v1.1 · `_PROGRESS.md` · **源码只读核对**（`server.py:782-843`、`stream.py:506-521`、`config.py:15-22`、`tests/test_server.py:145-170`、`tests/test_stream.py:131`）
> **结论** ✅ **通过**（无 P0；**P1×0**；新增 P2×4 全部不阻断）→ **8 份详设 v1.1 可交付 code-developer**

## 一、结论摘要

| 项 | 结果 |
|----|------|
| 结论 | ✅ **通过**（可进入 P5a 编码） |
| P0 | 0 |
| P1 | **0**（首评 6 项 P1 全部闭环；A 组 4 项 + B 组 2 项，逐项见 §二/§三） |
| 新增 P2 | 4（文档自洽 1 + 资源账残余 2 + 版本引据时效 1；均不阻断） |
| 回归 | stream 侧 SAD v1.3 **7 项钉死项保持全 ✅**；既有测试真正破坏面仍为 **4 条**（未新增） |
| 声明 | **8 份详设 v1.1（config/cache/metrics/stock_api/market_api/cdp_engine/server/stream）可交付 code-developer** |

**复审性质说明**：本轮不重开体系性审查。首评已确认"结构完整性 / 契约精确度 / 锁序正确性 / 跨模块对齐"达高水准，阻断性质为**局部机制缺口**；本报告只验证这 6 个机制缺口是否真闭合、闭合方式是否引入新矛盾。

---

## 二、A 组逐项核验（server / stream 的 P1×4）

| ID | 声称的修正 | 文档证据 | 只读核对（代码/语义可行性） | 判定 |
|----|-----------|---------|--------------------------|------|
| **P1-1** healthz 准入位释放时机 | 新增 `_HealthBatch`：准入位由**该批 5 个 future 的完成回调**释放；在飞 ≤25、执行器队列 ≤20；五路销账；`_done` 保证恰好一次 | §2.6 三分支表 + §2.6.1 伪代码（`batch = _HealthBatch(len(ROUTES))` **先设账再提交**；`fut.add_done_callback(batch.task_done)`；提交失败 `batch.task_done()`；执行器创建失败 → `_release_health_slot()`）· §4.5 BR-SRV-19/20 · §5.6 `_HealthBatch`（`__slots__`+锁内 `_remaining-=1`+`_done`，`with` 块**外**调 `_release_health_slot()`）· §6.2#4 · §7.1/7.2#3 · §8 SRV-T20/T22/T34 · §10#16 | ✅ 可行性成立：① 计数上界自洽——`BoundedSemaphore(5)` 限 5 个准入批次 × 5 源 = **≤25** 在飞任务，`max_workers=5` ⇒ `_work_queue.qsize() ≤ 20`（SRV-T22/T34 断言值正确）；② 销账完备——每个 future 的回调恰好触发 1 次，提交失败路径显式 `task_done()`，故 `_remaining` 归零 ⇔ 该批 5 源全部销账（**不会提前释放**）；③ 无泄漏——`_get_health_executor()` 抛错时在 `_HealthBatch` 创建**之前**直接 `_release_health_slot()` 返回，不存在双路径；④ 无锁序风险——`_release_health_slot()` 在 `_HealthBatch._lock` 释放之后调用，`_health_inflight_lock`/`metrics._lock` 为叶锁；⑤ `_done` + `BoundedSemaphore` 超放 `ValueError` 构成双重兜底。**§2.6"队列从不堆积"的断言与伪代码现已一致**（首评指出的"文档声称与伪代码矛盾"已消除） | ✅ **闭环** |
| **P1-2** 外部上游串行 | 新增 `_fanout_executor(_FANOUT_MAX_WORKERS=3)` + `_fetch_concurrent`；hotplate/plate/longhu 统一 ≤3 并发；引据改 AC-E2 | §1.1-7′ · §2.8 handlers 表 · §4.6 **BR-SRV-30** · §5.5 `_get_fanout_executor`/`_fetch_concurrent`/`handle_cls_hotplate`/`handle_cls_plate`/`handle_ths_longhu` · §6.2#6 · §8 SRV-T13/T35 · §9（E2 主承载）· §10#10（归属更正是 E2，非 S7）/#15（新执行器登记） | ✅ 三条端点已全部改为 `_fetch_concurrent`：hotplate 3 分区（闭包用**默认参数捕获** `url`/`ttl`，无循环变量晚绑定缺陷）、plate 3 段、longhu 2 URL（并消除直连 `urlopen`，与 R15/BR-SRV-9 合并）。`_fetch_concurrent` 提交后按 specs 序 `fut.result()` 收敛，`Exception` 转值不抛（`text` shape 仍由 `raise` 交 `_guard`）⇒ 单端点 = `max` 而非 `sum`。引据四处同步改为 **AC-E2**（PRD v0.4 AC-E2 原文"任何单请求 ≤15s"） | ✅ **闭环**（残余见 §六-②） |
| **P1-3** hotplate 全分区失败补顶层 `error` | 三分区全失败 ⇒ 顶层补 `error`（值 = 三块摘要），SRV-T14 断言同步 | §2.8 handlers 表 · §4.6 **BR-SRV-31** · §5.5 `if len(errors) == len(specs): result['error'] = '; '.join(errors)` · §6.1（新增"全分区"行 + "部分分区无顶层 error"行，两行互斥）· §8 SRV-T14 · §9 | ✅ 与 SAD §2.3 D-4 / §2.4 唯一口径一致。补充核对：全失败时 `hot_plates` 不会被写入（仅成功分区可能产出），故结果体只含 3 个分区 error 客体 + 顶层 `error`，**不与"批量无顶层 error"不变式冲突**（hotplate 属 `object` shape） | ✅ **闭环** |
| **P1-4** 流端口 inflight | `BoundedThreadPoolServer.__init__` 增 `max_inflight=None`；`make_stream_server` 显式传 `MAX_STREAM_CONNS+10=110` | server §2.7（`__init__(*args, max_workers=MAX_WORKERS, max_inflight=None, **kwargs)`；`_max_inflight = MAX_INFLIGHT if max_inflight is None else max_inflight`）· §3.4 状态注释 · §5.7 伪代码 · §10#11 · stream §2.2（签名清单标注"构造时显式传"）· §10#13 · §11.2 | ✅ 与现状代码兼容：现签名 `__init__(self, *args, max_workers=MAX_WORKERS, **kwargs)`（`server.py:793`）为**纯新增可选 kwarg**，主端口调用点 `BoundedThreadPoolServer(('0.0.0.0', PORT), RSSHandler)`（`server.py:963`）零改动；`stream.make_stream_server` 现为 `max_workers or (MAX_STREAM_CONNS+10)`（`stream.py:509`）。`110 ≥ MAX_STREAM_CONNS(100)` ⇒ `_register_conn` 的 100 阈值与 AC-E5/E7 恢复可达 | ✅ **闭环**（残余见 §六-①③） |

> **A 组小结**：4/4 闭环。首评 §四"server 侧 8 项钉死项 6 ✅/2 ⚠️"的两处 ⚠️（healthz 有界准入、`MAX_INFLIGHT` 显式）**均已转为 ✅**。

---

## 三、B 组逐项核验（数据层的 P1×2）

| ID | 声称的修正 | 文档证据 | 只读核对 | 判定 |
|----|-----------|---------|---------|------|
| **REV-DES-10**（stock_api 引用 `cdp_engine.page_data` 的自相矛盾） | §1.3 允许 `cdp_engine（page_data）`；§1.4/§2.1#3/§5.9 口径统一 | §1.3 允许列表第 41 行 `cdp_engine（page_data）` + 禁令第 44-46 行改为"禁止 `server/stream/market_api`；`cdp_engine` **仅**允许模块级函数 `page_data`，`CDPEngine/CDPPage` 禁止 import" · §1.3 依赖图补 `stock_api ← {…, cdp_engine}` + REV-DES-10 同层依赖说明 · §1.4 第 73 行补 `cdp_engine.page_data(page) -> dict \| None`（"唯一页面数据读取入口；禁止直接调 `page.get_data()`"）· §2.1#3 `_navigate_f10 + cdp_engine.page_data` · §5.9 代码 `data = page_data(page)` · §10#16 | ✅ **同一文档内 4 处口径现完全一致**（§1.3 允许 / §1.4 登记 / §2.1 契约 / §5.9 调用）。逐处核对无残留矛盾：禁令已不再出现 `cdp_engine` 平铺禁名；§5.1 import 块含 `from .cdp_engine import page_data`（`_PROGRESS.md` §v1.1 摘要已登记）。方向性核对：`cdp_engine` 的 `forbiddenImports` = server/stream/stock_api，而 `stock_api → cdp_engine` 为 Layer2→基础设施（`cdp_engine` 不 import 任何业务模块）⇒ **无环**。SAD §3 / `tech-stack.json` 的登记归编排层（文档已显式标注不自改） | ✅ **闭环** |
| **REV-DES-11**（market_api `_error` 形态 vs PRD AC-A5） | 设计保持 + 裁决回执 | `market_api.md` §3.2（`_error: upstream_timeout \| upstream_error`）· §10#1 改为**裁决回执**："设计保持：保留 `{latest, recent, _error}`，不改为 `{error}`；**编排层已裁决**，PRD AC-A5 对 margin 的表述将回改" · §11 自检 | ✅ **两端口径已对齐**：`doc/prd/perf-stability-optimization.md` 已升至 **v0.4**，§修订依据明确"AC-A5『上游失败』行 `/market/margin` 错误体口径改为既有数据客体内 `_error` 字段（保持 🟠 STABLE）"，并在变更表单列该条与"同格逐项核对"结论。⇒ tester 现可落笔，原"AC 该格断言与设计不能同时成立"的阻断面已消除。**残留为回执时效**（见 §六-④），非阻断 | ✅ **闭环** |

---

## 四、C 组 P2 抽查（每文档 ≥2 项）

| 文档 | P2 项 | 抽查结果 |
|------|-------|---------|
| **server.md** | P2-2 healthz 每源 3s + 整体 10s | ✅ §2.6.1 代码：`now - t >= _HEALTH_SOURCE_BUDGET` 按**各 future 的 `submitted_at`** 判定；整体闸独立为 `elapsed >= _HEALTH_TOTAL_BUDGET`，且 `timeout = min(_HEALTH_POLL, next_due-now, TOTAL-elapsed)` 让 10s 闸可达（不再死代码）。SRV-T21 补"patch `_HEALTH_TOTAL_BUDGET=1.0` ⇒ ≤1.1s（不是 3.2s）"断言，**可测** |
| | P2-4 `_JSON_SHAPES len==14` | ✅ §2.2 分组视图改为 `object（7，表内）`，并显式写"`/healthz` 复用 `object` shape 但 **≠** 在表中（加入即 `assert len==14` 导入期失败）"；SRV-T1 断言三项（len/tuple/set）齐备。防编码者误加表 |
| | P2-5 import 完整 | ✅ §2.10 改为"**完整 import 块（可整体替换）**"：逐行比对现状 `server.py:18-36` **无遗漏**（atexit/json/os/re/signal/sys/threading/time/logging/ThreadPoolExecutor/**wait,FIRST_COMPLETED**/formatdate/ThreadingHTTPServer,…；`signal`/`sys`/`atexit`/`formatdate` 均在块内）；删除项显式标出（`random`、`Request,urlopen`）；补回 `main()` 所需 `stock_api` 4 个 prefetch loop、`market_api`、`utils`、`_fill_missing` |
| | （附带核到）P2-1 / P2-3 | ✅ §5.4 伪代码 `ttl = cache_policy('feed')['ttl']` 已移到**二次 get 仍 miss 之后**（①命中路径不读 policy）；§3.1 `status` 注释限定为"check=1 仅覆盖 5 个 RSS 源" |
| **stream.md** | P2-6 `_reserve_for` 用 skip 排除集 | ✅ §5.2 代码 `skip=set()` + `max((s for s in _group_bytes if s not in skip), …)`，两处 `skip.add(sid)`（组已消失 / 该组无 `_Frame` 可丢）**均不再 `_group_bytes.pop`**；§4.2 BR-STR-15 明文禁 `pop`；进展保证成立（`skip` 单调增长且 `skip ⊆ _group_bytes`，`sid is None` 即返回）⇒ **无死循环**；§8 新增 STREAM-T33 断言"G1 组账仍为 2×size、丢弃来自 G2" |
| | P2-7 销毁 vs 注册竞态 | ✅ §5.5 `_serve_sse`：`g.conns.add(conn)` 之后 `with _groups_lock: alive = _groups.get(sid) is g`；不存活 ⇒ `conn.closed=True` + `g.conns.discard(conn)` + `_release_conn(conn)`（排空 + 减计数）+ 404。§7.4 竞态表新增该行并给出不变量；STREAM-T34 断言四条（不阻塞/conns 空/`_conn_count` 回位/closed True）。**与 P2-6 同族、收口方式正确** |
| | （附带核到）P2-8/9/10 | ✅ §11.1 把 `test_broadcast_serves_live_group_only` 降级为"可选清理（非破坏性）"并明示真正必改 = **4 条**；§3.5 owner 对齐 `stream.push_loop`；§2.3/§5.3 统一 `cached_batch(_FIELD_DOMAINS[field], rest)` |
| **stock_api.md** | REV-DES-12（计数收口） | ✅ §5.9 抽 `_raise_cdp_unavailable()`（`metrics.incr('upstream_fail_total', key='cdp_unavailable')` + `raise`），**4 处出口全部改为调用它**（engine 未就绪 / 无导航页 / 预算耗尽 / 全导航失败或全页 `page_data=None`）；§4.6 BR-SA-29 同步为"四处出口全部经 `_raise_cdp_unavailable()` 计数" |
| | REV-DES-13 / 14 | ✅ §5.2 `_fetch_rest_json`：`except FetchError: raise`（cache 已计数，**不重复计**）+ `except Exception → incr(upstream_error) + FetchError` + 前置 `if not isinstance(raw, dict): incr + FetchError` ⇒ 与 `market_api` 防御一致 |
| | REV-DES-16（prefetch deadline） | ✅ §2.8 签名 `_prefetch_loop(..., per_call_budget=REQUEST_TIMEOUT)`；§5.11 `call_deadline = min(pass_deadline, now + per_call_budget)` 并 `fetch_one(code, deadline=call_deadline)`；`_f10_prefetch_loop` **移除 lambda** 直传 `fetch_cls_f10` + `per_call_budget=_PREFETCH_CDP_CALL_TIMEOUT(4)`（`fetch_cls_f10(stock_code, deadline=None, ttl=None)` 接受 kwarg）；SA-T29 断言实参上界 |
| **market_api.md** | REV-DES-20（owner） | ✅ §10#5 与 BR-MKT-8 的引据改为"本模块与 cache 的**防重复计数约定**"（网络失败归 cache、语义失败归 API 层，同一次失败只计一次），并明示 `metrics.md §3.2` owner 列补 `market_api` **由编排层同步**（本 agent 不改基础层文档）。MKT-T7 有"无 `upstream_timeout` 增量"断言 ⇒ 口径可测 |
| **cdp_engine.md** | REV-DES-19（初始 idle 发布） | ✅ §5.1 模块级 `_publish_window()`（紧跟定义段）；§4.1 **BR-CDP-5** 明文化"且模块加载时发布一次初始 `idle` 快照"；`CDPEngine.start()` 内 `_mark_idle()` 注"初始已为 idle（模块加载已发布）⇒ 幂等不重复发布"；§8 CDP-T9 扩断言"未发生任何迁移时 `metrics.snapshot()` 已含 `cdp_restart_window` 且 `state=='idle'`"；§10#10 登记 |

> **C 组小结**：抽查 14 项（超出"每文档 ≥2"要求）**全部闭合**，未发现"声称已改但正文未改"的挂空。

---

## 五、D 组回归检查

### 5.1 stream 侧 SAD v1.3 七项钉死项 —— 仍全 ✅

| 钉死项 | 是否被 v1.1 改动触及 | 复核结论 |
|--------|---------------------|---------|
| `codes→frozenset` / `fields→tuple` + 帧构建移出锁区 | 未触及 | ✅ 保持（§5.1/§5.4） |
| `_Frame{payload,refs}` + `_frame_bytes_lock` 叶锁 + `_frame_acquire/release` + 三处 `_drain_conn_queue` + `None` 哨兵不计费 | P2-7 新增一处**排空触发点**（注册失败收口经 `_release_conn → _drain_conn_queue`） | ✅ 属超集：排空仍是同一收口函数、幂等；BR-STR-13 的"三处"未减，新增路径不改变原三处的时序结论 |
| 队列字节预算 + 确定性丢弃（**绝不丢最新**） | P2-6 改变的是"选靶时的错误记账" | ✅ 不变式**更强**：`_group_bytes` 现始终等于"该组 `refs>0` 帧字节和"（旧实现会低估）；`先腾位后入队` 与 `B ≥ F_max` 未变 |
| 分片轮转 `|slice| ≤ 56` 码 | 未触及 | ✅ 保持（§3.3/§5.3，`_prefetch_slice`/`_prefetch_advance` 语义未动） |
| 跳过 `_` 前缀键（AR-7） | 未触及 | ✅ 保持（§5.3） |
| `_read_json_body` 5s 预算 | 未触及 | ✅ 保持（§5.7） |
| `MAX_GROUPS` 400 | 未触及 | ✅ 保持（§5.6/§10#9） |

> 结论：**P1-4 / P2-6 / P2-7 三项改动均落在"钉死项之外或其安全边界内"，无一项破坏 7 项钉死项。**

### 5.2 server 侧是否引入新问题（重点：`_fanout_executor` 资源账、新无界点）

| 核查点 | 结论 |
|--------|------|
| **线程账自洽** | ✅ §2.9 明确"新增线程 = healthz 专用执行器（≤5）+ 扇出执行器（≤3），懒创建，**总账 +8 上界**"，§10#8/#15 分别登记；三者物理隔离（§7.2#5），`_fetch_concurrent` **禁止**嵌套扇出 ⇒ 无递归并发放大 |
| **锁序自洽** | ✅ `_fanout_lock` 仅保护懒创建、无 IO、不跨模块调用；`_fetch_concurrent` 在**不持任何锁**时阻塞等待 future（调用链 `handle_cls_* → _fetch_concurrent` 无锁持有），故与 cache/config/metrics 锁无嵌套、无死锁面 |
| **healthz 执行器队列上界** | ✅ 见 §二 P1-1（≤20，与 SRV-T22/T34 断言值一致），**不再是 v1.0 的无界点** |
| **主池阻塞面** | ⚠️ 见 §六-②（`_fetch_concurrent` 阻塞主池 worker 等待扇出 future；共享 3 worker ⇒ 跨请求排队），**不构成新无界点**（队列深度受主池 `_max_inflight=40` 与每请求 ≤3 specs 双重封顶） |
| **`_HealthBatch` 新锁** | ✅ `_HealthBatch._lock` 为纯整数/布尔、不嵌套（§7.1/§7.2#3），release 在锁外调用（§7.2#3 末句） |

### 5.3 既有测试破坏面

| 项 | 结论 |
|----|------|
| 真正**必改**条数 | ✅ 仍为 **4 条**（全在 stream：`test_build_frame_maps_only_group_fields`、`test_build_frame_skips_codes_missing_from_snapshot`、`test_create_group_valid_codes_and_fields`、`test_broadcast_on_full_queue_drops_oldest_keeps_newest`），与首评一致，**未新增** |
| server 侧 | ✅ 仅 2 条**跨模块交叉引用**（`test_fetch_json_leader_failure_does_not_stampede`→cache、`test_sector_cache_bounded`→stock_api），归他模块 |
| P1-3 是否新破坏 hotplate 存量用例 | ✅ **不破坏**（已读 `tests/test_server.py:145-155`：断言为 `assertIn` 逐键 + `hot_plates` 结构，**非精确键集合**；且新增顶层 `error` 只在三分区全失败时出现）。§10.1 的"CI 断网需允许该键"提示属**既有 mock 缺口**（全失败路径无论是否补 `error`，`hot_plates` 断言在断网下同样失败），非本次引入 |
| P1-4 是否新破坏 `tests/test_stream.py:131` | ✅ **不破坏**（该处直接构造 `BoundedThreadPoolServer(('', 0), StreamHandler, max_workers=4)`，未走 `make_stream_server`、未断言 `_max_inflight`；新签名 `max_inflight=None` ⇒ 向后兼容） |
| `make_stream_server` 调用方 | ✅ 仅 `run_stream_server`（`stream.py:516`） |

---

## 六、新增 P2（均不阻断，建议随编码收口）

| # | 项 | 位置 | 描述 | 建议 |
|---|----|------|------|------|
| **N-1** | `__init__` 签名在"保留不变的公开面"表内**自相矛盾** | `server.md` §2.10 第 468 行 vs §2.7/§5.7/§10#11 | §2.10 表格写 `BoundedThreadPoolServer.__init__(*args, max_workers=MAX_WORKERS, **kwargs)` = **"不变（仅内部 `_max_inflight` 来源变）"**，但 P1-4 已把 **`max_inflight=None` 加进签名**（§2.7/§5.7 一致写明）。这是 P1-4 修订在同一文档内留下的**新旧表述并存**（首评"§2.6 断言与伪代码矛盾"的同类问题，程度轻得多） | 将该行改为 `__init__(*args, max_workers=MAX_WORKERS, max_inflight=None, **kwargs)`（**纯新增可选 kwarg，向后兼容；主端口调用点不改**），并注明"签名新增可选形参，非'不变'" |
| **N-2** | 共享扇出池的**跨请求排队**未被登记 | `server.md` §5.5 并发正确性注 / §6.2#6 / BR-SRV-30 / §10#15 | 文档断言"单端点耗时上界 = 10s + 解析 ≤ 15s"。该上界仅在**扇出池未被其它请求占用**时成立：池为**全局共享 3 worker**，同一时刻 N 个 hotplate 请求各提交 3 个 spec（N ≤ 主池 `_max_inflight=40`）⇒ 一个请求可能排在他人 task 之后，最坏单请求耗时 > 15s。**注意这不算 AC-E2 违反**——AC-E2 原文限定"**且上游正常**"，而上游正常时排队立即排空；但文档给出的"≤15s"是无条件的结构断言，属**条件性安全感的表述**（首评 §八"误导"同类） | 二选一：① 在 §5.5/BR-SRV-30 的表述中补条件"（上游正常、扇出池无跨请求排队时）"；② 若需硬上界，给 `_fetch_concurrent` 加"提交前对 spec 数取 `min` 于剩余预算"或"单请求预算耗尽即降级"的兜底，并登记为 AC-E2 的显式口径。**推荐 ①**（成本最低，且不改变已批准的资源口径） |
| **N-3** | `make_stream_server` 未给出代码，且 `max_workers` 覆盖时的语义未钉死 | `stream.md` §2.2 第 166 行 / §10#13 | v1.1 明确"构造时**显式传** `max_inflight = MAX_STREAM_CONNS + 10 = 110`（同时 `max_workers=110`）"，但**全篇无该函数的伪代码**（仅签名清单注释 + 偏差表 + 修订对照三处文字）。值虽已三处一致、可编码，但若测试/调用方显式传 `max_workers`（如 `max_workers=4`），`max_inflight` 应取 110 还是随 workers 缩放**未定义** | 在 §5 补 3 行伪代码（成本极低），并建议 `max_inflight = max_workers`（默认即 110；覆盖时保持"inflight ≥ worker"语义），消除歧义 |
| **N-4** | 跨文档**版本引据时效** | `market_api.md` 头部（PRD v0.3）与 §10#1（"将回改"）· `stream.md` §末（`stock_api.md` **v1.0**）· `server.md` §末（`stock_api/market_api/cdp_engine` **v1.0**） | REV-DES-11 依赖的 PRD 已实际升至 **v0.4 并完成回改**，但 market_api 仍写 v0.3 / "将回改"；两模块尾部仍引"数据层三模块 v1.0"（现均 v1.1）。不影响编码，但会让下游误判"契约尚未回改" | 随本轮统一为 PRD v0.4 / 数据层三模块 v1.1，并把 §10#1 措辞由"将回改"改为"**已回改（PRD v0.4）**" |

---

## 七、逆向审查（复审视角，Step 1.5）

- ⚠️ 逆向审查（误导）：N-2 —— "单请求 ≤15s"在共享池下**给出条件性安全感**；首评同类问题的**新变体**（P1-1 的"队列从不堆积"已修，此处是 P1-2 修法的副产物）。等级 P2：AC-E2 自身限定"上游正常"，且新设计较 v1.0（无条件 30s/20s 串行）**严格更优**。
- ⚠️ 逆向审查（断链）：N-1/N-3 —— 局部修订在**同一文档内**留下旧表述（§2.10 vs §2.7）与"只说不写"（`make_stream_server`）。复核确认**不构成不可编码**：取值与机制均取自权威节（§2.7/§10#11/§10#13），code-developer 不会发明。
- ✅ 逆向审查（反证）：若"准入位 == 任务真实在飞"仍不成立会怎样？→ 复核 `_HealthBatch` 计数路径（先设账、五路销账、`_done` 单次、回调幂等）**确认成立**，P1-1 的核心断言不再虚假。
- ✅ 逆向审查（遗漏）：P1-2 的补救是否遗漏端点？→ 逐端点核对 hotplate/plate/longhu **均已改并发**，且 §2.8/§6.2#6/§9/§10#10 四处引据同步为 AC-E2，**无遗漏端点**。
- ✅ 逆向审查（不可逆）：本轮改动均为进程内内存态 + 可选形参（`max_inflight=None` 向后兼容），**无不可逆操作**；`_fanout_executor` 懒创建、无 shutdown 钩子（进程退出由 daemon 语义覆盖）不成风险。
- ✅ 逆向审查（断链，正向）：SAD §4.1「hotplate 3 次串行 → ≤3 并发」在 v1.0 详设层**整条丢失**（首评 P1-2 的断链项），现已在 §4.6 BR-SRV-30 + §5.5 伪代码落地并登记 **§10#10/#15** ⇒ 需求→架构→详设链**已接回**。

---

## 八、复审结论

**✅ 通过**（P0×0 / **P1×0** / 新增 P2×4）。

- **A 组 4/4 闭环**：healthz 准入位改为"批任务完成回调释放"（在飞 ≤25、队列 ≤20、五路销账、恰好一次）、三端点统一 ≤3 并发（引据改 AC-E2）、hotplate 全失败补顶层 `error`（SAD D-4 唯一口径）、`max_inflight` 形参 + 流端口 110（AC-E5/E7 恢复可达）。四项均经**源码只读核对**确认可行（现存 `__init__` 签名为纯新增 kwarg 兼容；`BoundedSemaphore`/`ThreadPoolExecutor` 语义支撑文档给出的上界）。
- **B 组 2/2 闭环**：`stock_api` 的 `cdp_engine.page_data` 自相矛盾在 4 处口径上消除（且无环）；`market_api` 的 AC-A5 冲突已由**编排层裁决 + PRD v0.4 回改**闭合，设计形态（🟠 STABLE）保持。
- **C 组抽查 14 项全过**（远超"每文档 ≥2"）。
- **D 组回归**：stream 7 项钉死项保持全 ✅；server 新机制的资源账（线程 +8、队列 ≤20、锁序、无嵌套扇出）自洽、**无新无界点**；既有测试真正破坏面仍为 **4 条**（未新增）。
- 新增 4 项 P2 均为**表述/时效/可执行性**瑕疵，不影响 P5a 编码正确性，建议随编码同 change-set 收口（其中 N-1 建议优先，属文档内部矛盾）。

> **放行声明**：**8 份详设 v1.1（`config.md`/`cache.md`/`metrics.md`/`stock_api.md`/`market_api.md`/`cdp_engine.md`/`server.md`/`stream.md`）可交付 code-developer 进入 P5a 编码。**
> 编码期仍受 `_PROGRESS.md` 已登记的 4 项**编排层跨模块同步项**约束（`feeds[].status` 三处取值、`MAX_GROUPS` 400、`max_inflight` 形参、SAD `handle_cls_*` 措辞回改），**不在 code-developer 权限内**。

---

## 变更记录

| 版本 | 日期 | 说明 |
|------|------|------|
| v1.0 | 2026-09-16 | 详设 v1.1 修订**复审**（仅核验 6 项 P1 + 14 项 P2 抽查 + 回归）；结论 ✅ 通过（P0×0 / P1×0 / 新增 P2×4）；8 份详设 v1.1 可交付 code-developer |

