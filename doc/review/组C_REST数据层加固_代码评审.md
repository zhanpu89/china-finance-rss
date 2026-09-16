# 组C REST数据层加固 代码评审

- **评审对象**：feature/stream-push 分支 REST 数据层加固（commit 979ecc3）
  - `stock_api.py`（+158 行）：批次分片 `_handle_cached_batch`/`_process_chunk`、prefetch existing_ts 竞态修复、per-page fetch 锁、prefetch 轮转游标
  - `cache.py`（+46 行）：fall-through 限流 `_fallthrough_sem`、随机退避、两次 re-check、超时 raise
  - `market_api.py`：margin `n = min(len(dates), len(items))`
  - 配合：`server.py` batch 截断日志（`_handle_stock_batch`）
- **评审模式**：常规代码评审（P5b 修复轮）；diff 摘要由编排器预取
- **CR 编号**：CR-2026-0915-组C
- **评审日期**：2026-09-15

---

## 0. 评审概要（总评）

**组C 加固方向正确、实现质量高，无 P0。** 批次分片解除了 stream 全量推送（≤2000 codes）下超出 `_MAX_BATCH_SIZE` 的静默丢弃（P1-6 已有回归测试 `test_stream.py:220` 兜底）；prefetch `existing_ts` 检查经语义推导在时序上正确消除了"主请求新数据被后台预取覆盖"的竞态（4 处同构，逻辑自洽）；fall-through 三段式（随机退避 0~0.5s → 第一次 re-check → sem 有界等待 → 第二次 re-check → 直连）经严格时序推导确认**不会打破单飞**——follower 的 fall-through 直连必然晚于 leader 的 urlopen 失败时刻（urlopen timeout=REQUEST_TIMEOUT 有界），且全部 15 个 `fetch_json` 调用方兜底验证齐全。

**2 条 P1 建议修复**：① CDP 双锁系统并存（`_page_fetch_locks` vs `page._navigate_lock`），`evaluate_fetch` 与 `navigate_stock` 在同一 page 上仍可并发；② prefetch 失败代码不计入游标推进，上游整体故障时 pool 尾部轮不到刷新。**4 条 P2 记录不阻塞。**

---

## 1. 问题清单

### P0

无。

### P1

**【P1-1】stock_api.py:253-260 + cdp_engine.py:590-616/1096-1173：CDP 双锁系统并存，`evaluate_fetch` 与 `navigate_stock` 在同一 page 上仍可并发**
- **证据链**：`_evaluate_fetch_any` 用模块级 `_page_fetch_locks[name]` 串行化 `page.evaluate_fetch`（stock_api.py:253-257）；`fetch_cls_f10` 用 `page._navigate_lock`（RLock）串行化 `navigate_stock`+`get_data`（stock_api.py:502-511）。两个锁系统互不获取对方。当 f10 主请求持有 `_navigate_lock` 正在导航时，fundflow/timeline/announcement 的 CDP fallback（`fetch_cls_*` 或 prefetch `_*_direct_fetch`）可在**同一 page** 上执行 `evaluate_fetch`（`Runtime.evaluate` + `awaitPromise`，cdp_engine.py:603-613）。页面跳转销毁 JS 执行上下文 → evaluate_fetch 抛异常/超时 → 返回 None → CDP 路径静默退化 REST（`evaluate_fetch` 的 fetch 结果也不进 `get_data` 读取的缓存，故无脏数据，是**并发下 CDP 数据获取成功率下降**）。`_navigate_lock` 只解决了 f10-vs-f10（同锁），未解决 evaluate_fetch-vs-navigate_stock（跨锁）。
- **修复建议**：`_evaluate_fetch_any` 中对 `name in _stock_nav_pages()` 的页面改取 `page._navigate_lock`（RLock 可重入，`navigate_stock` 内部 re-acquire 安全），或使 `evaluate_fetch` 统一走 page 级单一锁。

**【P1-2】stock_api.py:329-343（timeline/f10/announcement 同构 396-437/524-567/729-770）：prefetch 失败代码不计入游标推进，上游整体故障时 pool 尾部数小时轮不到刷新**
- **证据链**：`data is None` → else 分支只更新 `fail_blacklist`，`processed`/`skipped` 均不增 → `_prefetch_advance(key, processed+skipped, len(codes))` 推进 0 → 下一 pass 从断点重试**同一批**。连续 3 次失败才进 120s 冷却（冷却期靠 `skipped` 推进）。pool=500（fundflow）且 pass 预算 60s 时，每轮仅触碰前 ~100 个；上游全挂场景下尾部 codes 需 3 轮失败 + 2 轮冷却才能推进一批，2000 codes 级 pool 尾部刷新延迟达小时级。`fail_blacklist` 防坏源意图正确，但与 round-robin 游标交互产生公平性缺陷。
- **修复建议**：else 分支也计入 `processed`（失败即消费游标），或按"实际访问的最大 index+1"推进而非 processed+skipped；黑名单冷却可保留（冷却期内用 skipped 推进）。

### P2

**【P2-1】cache.py:121-125 + 59-68：fall-through 契约（None→raise）未同步 docstring，且无测试覆盖该路径**
- fetch_json docstring（59-68 行）仍只描述 leader election/re-election，未提 fall-through 的 `RuntimeError`；`test_server.py:385-407` 单飞测试仅覆盖"leader 失败→重新选举"（deadline 未耗尽即恢复），不触发 fall-through。调用方兜底已验证齐全（见第 2 节），注释声称成立。修复：更新 docstring 契约说明；补测试（mock urlopen 挂起 + 占满 2 slots → 断言 RuntimeError 及 `_serve_feed` 降级 error-RSS）。

**【P2-2】stock_api.py:196-201：`_handle_cached_batch` 无全局 dedupe，重复 code 跨 chunk 边界被重复处理**
- chunk 内 dedupe（130-131）只覆盖本 chunk；`codes=[A,...,A]` 跨 chunk 分布时 A 被处理两次（第二次命中缓存，无上游压力）。与 `handle_cls_stock_batch`（789-790 全局 dedupe）不一致。修复：`_handle_cached_batch` 开头做一次全局 dedupe。

**【P2-3】stock_api.py:553-558：f10 prefetch 在 `_f10_cache_lock` 内调用 `_populate_sector_from_f10`（→ `_sector_cache_put` 可能 sweep/min 扫 2000 条目），持锁偏长**
- 对比 `_process_chunk` 中 after 回调在锁外调用（173-177）的不一致。低频（每 interval 一次）可接受，但应把 `_populate_sector_from_f10` 移到 `with` 块外，与主请求路径一致。锁序无死锁（`_sector_cache_lock` 内不取 `_f10_cache_lock`）。

**【P2-4】观察：cache.py:88-98/22：`_fallthrough_sem` 不约束 leader 直连，总上游并发 = leader 数 + 2**
- RSS 9 个端点同时过期时 9 个 leader 并发直连（per-URL 单飞的固有设计，跨 URL 并发本就是所需），fall-through 另占 2 slots。2C2G 可接受，记录不阻塞。

**【P2-5】观察：prefetch existing_ts 竞态修复（4 处）无直接测试覆盖**（仅有 round-robin 测试 test_server.py:409-434）。语义验证正确：`now_ts` 取 fetch 前，主请求在 prefetch fetch 期间写入的 ts > now_ts → 不覆盖 ✅；主请求完成早于 prefetch 开始时被覆盖 ✅（实时性正确）。

---

## 2. 重点审查方向逐项结论

1. **批次分片** ✅ — `_handle_cached_batch` 拆 chunk 全量处理；`server.py:636-640` HTTP 层截断（len>50 + dropped 日志）与内层 chunk 全量语义一致且注释说明清晰（191-192）；chunk 内 pool 注册/缓存合并正确；`batch_deadline`（f10/basic_info 60s）在 chunk 串行下与旧行为等价（concurrent=False 本就顺序消费，先到先得语义不变）。
2. **fall-through 限流** ⚠️ — 时序推导：follower fall-through 的 urlopen 开始时间 ≥ 自身 deadline（进入+REQUEST_TIMEOUT）≥ leader 失败时刻（leader 进入+REQUEST_TIMEOUT），故与 leader 无并发窗口，**单飞保持**；两次 re-check 时序正确。sem(2) 3s 超时 raise 的调用方兜底验证：server.py `_serve_feed`(692-696，error-RSS)、stock_api 全部 7 个 fetch 函数（try/except → CDP fallback/None）、market_api 3 个（降级零值 dict）、utils `warm_jin10_headers`(141-142)、`get_jin10_public_headers` 经 `_serve_feed` 兜底、stream `push_loop`(186-188)——**全部有兜底，注释声称成立**。顾虑见 P2-1。
3. **prefetch 竞态** ⚠️ — `existing_ts <= now_ts` 检查 4 处同构一致，**正确消除主请求/后台预取覆盖竞态**；游标公平性缺陷见 P1-2。
4. **per-page fetch 锁** ⚠️ — `_page_fetch_locks` 有界（name 集合 ≤ 3 stock 页 + 2 固定 = 5，`stock_nav_page_names` 默认 3），**无泄漏风险**；与 `_navigate_lock` 的跨锁并发见 P1-1。
5. **margin 修复** ✅ — `n = min(len(dates), len(items))` 正确防越界：`latest=fmt(n-1)`、`recent` 取交集区间，均需 `n>0` 前置保护（已具备 50-51 行空数组短路）。修复正确。

---

## 3. 覆盖的检查维度

| 维度 | 覆盖情况 |
|------|----------|
| Dim 0 契约一致性 | ⏭️ 跳过：`doc/detailed/` 不存在（修复型变更，无详设文档）。REST 数据层无 URL/字段对外变更，端间命名无漂移风险 |
| Dim 1 数据与正确性 | ✅ margin 越界修复、_MAX_CACHE_AGE 缓存命中判定、_process_chunk 缓存写入/merging |
| Dim 2 并发 | ✅ 重点：prefetch existing_ts 竞态、fall-through 单飞保持性、per-page lock 有界性、_page_fetch_locks vs _navigate_lock 双锁系统、_prefetch_cursor 线程安全、锁序检查（_f10_cache_lock→_sector_cache_lock 无反向） |
| Dim 3 资源与性能 | ✅ sem(2) 并发上限、pass 预算 60s、pool LRU evict per chunk、_page_fetch_locks 内存有界、sweep 间隔 60s |
| Dim 4 安全 | ✅ 本变更无外部输入新面（codes 经 VALID_STOCK_CODE 校验、无注入点新增） |
| Dim 5 结构与可维护性 | ✅ 4 处 prefetch loop 同构一致性、docstring 契约同步性（P2-1）、重复代码模式 |
| Dim 6 前端 | ⏭️ 无前端变更 |

## 4. 总体结论

**结论：⚠️ 有条件通过（修复 2 条 P1 后合入）**

- 无 P0，无数据丢失/安全/资金风险。
- P1-1（CDP 双锁并发）与 P1-2（prefetch 游标停滞）为建议修复项，生产版合入前应处理；均附修复方向，改动面小（各约 5 行）。
- P2 共 4 条（+2 观察）记录不阻塞，建议随 P1 一并处理 P2-1/P2-2/P2-3。
- 回归测试已存在：P1-6 分片测试（test_stream.py:220）、单飞测试（test_server.py:385）、round-robin 测试（test_server.py:409）均与本变更兼容通过；建议补充 P2-1 的 fall-through 契约测试。

## 5. DOC_SYNC 标记

```
>>DOC_SYNC: cache.py:59-68 → fetch_json docstring 需补充 fall-through 契约：选举 deadline 超时后走有界并发（Semaphore(2)）直连兜底，acquire 3s 超时 raise RuntimeError（不再返回 None）；调用方统一 try/except 降级
```

## 6. PROJECT 标记

```
>>PROJECT: 并发模式 → 后台 prefetch 写共享缓存前统一检查 existing_ts <= fetch 起始时间戳，防止覆盖主请求刚写入的新数据（fundflow/timeline/f10/announcement 4 处同构实例）
>>PROJECT: 异常与错误处理 → fetch_json 契约"成功 return str，失败 raise"，所有调用方 try/except 降级（error-RSS/None/空对象），不在缓存层返回 None（≥6 处同类实现证实）
>>PROJECT: 并发模式 → 新增 CDP 页面共享操作须纳入既有 page 级锁体系（_navigate_lock / per-page lock），禁止引入第二套独立锁（P1-1 教训，修复后回写）
```