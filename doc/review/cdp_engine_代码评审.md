# 代码评审报告 — cdp_engine.py 修复轮 r1

**CR-20260914-001** / v1.0 / 状态: 完成
**评审模式:** P5b 修复轮评审 + P7a 漂移检测（review+drift）
**日期:** 2026-09-14
**评审范围:** cdp_engine.py（+96/-73 行，修复 P8 盲审 5 个并发/资源泄漏问题）

---

## 一、评审概要

**总评：** 5 项修复目标全部正确落地，锁设计无环、无自死锁。但 `_maybe_reconnect` 在持有 `_navigate_lock` 时可阻塞 45s+（Chrome 重启路径），以及 `close()` 与 `_connect()` 存在未同步的竞态窗口，需在合入前修复或降级。

| 等级 | 数量 | 说明 |
|------|------|------|
| P0 | 0 | — |
| P1 | 2 | 需修复或显式接受风险 |
| P2 | 3 | 记录，不阻塞 |

**是否允许进入测试：** ⚠️ 条件允许 — 2 个 P1 不影响单元测试，但集成测试需覆盖竞态场景

---

## 二、评审范围

| 文件 | 变更 |
|------|------|
| cdp_engine.py | +96/-73 行 — 5 项并发/资源修复 |

**受影响调用方（供 tester >>SCOPE:）：**
- `server.py` — `handle_finance_market`, `handle_cls_quotation`, `handle_market_timeline`, `handle_finance_timeline`（调用 `page.get_data()`，签名未变，安全）
- `stock_api.py` — `_evaluate_fetch_any`（调用 `page.evaluate_fetch()`），`fetch_cls_f10`（调用 `page._navigate_lock`, `page.get_data()`），`_iter_nav_pages`（调用 `page` 引用）

---

## 三、修复目标验证

| ID | 修复目标 | 实现状态 | 验证结论 |
|----|---------|---------|---------|
| P1-8 | `_reconnect()` 无锁重入 → `_reconnect_lock` 互斥 | ✅ 已修复 | `_reconnect()` 和 `_ensure_ws()` 均在 `_reconnect_lock` 内执行，串行化成功 |
| P1-9 | `_connect()` 失败 tab 孤儿 → `_close_target()` 回收 | ✅ 已修复 | `self._target_id` 提前置位（line 408），失败路径均调用 `_close_target()` |
| P1-10 | `_nav_restart_counter` 类变量用实例锁 → 类级锁 | ✅ 已修复 | `CDPPage._restart_counter_lock`（line 796）保护类变量 |
| P2-11 | `_ensure_ws` 无锁 → `_reconnect_lock` 串行化 | ✅ 已修复 | `_ensure_ws()` 全程持有 `_reconnect_lock` |
| P2-12 | `refresh()` 读不清 → 一次性 JS 读+清 | ✅ 已修复 | JS 表达式原子读取后清空 `__cdp_api/refetch/ws` |

---

## 四、问题详情

### Dim 2 — 并发

**【P1-01】cdp_engine.py:846 — `_maybe_reconnect()` 在持有 `_navigate_lock` 时可阻塞 45s+**

反模式：**线程池资源耗尽 / 阻塞无超时**

证据链：当 `_navigate_lock` 被 acquire 后（line 840），`remaining` 在 line 842 计算。若 remaining > 0，进入 `_maybe_reconnect()`（line 846）。当导航计数达到阈值（每 30 次），`_maybe_reconnect` 调用 `full_chrome_restart()`（~2s）+ `_reconnect()`（3 次重试 × 2s sleep + 45s retry window = 最坏 51s）。在此期间 `_navigate_lock` 被持有，所有其他 `navigate_stock()` 调用者阻塞在 lock acquire。

`navigate_stock` 的 `timeout=15` 保护仅在 line 842-844 生效（lock acquire 后、`_maybe_reconnect` 前），无法约束 `_maybe_reconnect` 内部的阻塞时长。

触发条件：Chrome OOM 崩溃（2c2g 环境常见）+ 导航恰好达到第 30 次阈值。

**修复建议：** 将 `_RECONNECT_RETRY_WINDOW` 或一个 deadline 传入 `_maybe_reconnect`，在 retry loop 内检查超时后 break，返回 False 让 `navigate_stock` 走降级路径。或者更简单：将 `_maybe_reconnect` 的 Chrome 重启+重连逻辑拆到独立线程，不阻塞 `_navigate_lock`。

---

**【P1-02】cdp_engine.py:408+983-990 — `_target_id` 提前置位与 `close()` 未同步**

反模式：**未同步的共享可变状态**

证据链：`_connect()` 在 line 408 设置 `self._target_id = target_id`，随后在 line 410 尝试 `websocket.create_connection`（timeout=30s）。若此时 `close()` 被调用（line 983-990）：`close()` 读取 `self._ws`（无锁，可能是 None），然后调用 `_close_target()` 读取并清空 `self._target_id`，关闭刚创建的 tab。`_connect()` 的 `create_connection` 因 tab 被关闭而抛异常，进入失败路径 `_close_target()`（但 `self._target_id` 已是 None，no-op）。连接失败，重连线程进入重试循环。

后果：`close()` 的语义是"关闭并停止"，但在竞态窗口内，它只关闭了 tab 而未阻止后续重连尝试。重连线程在 `_running=False` 后仍会重试（`_reconnect` 不检查 `_running`），白白消耗 45s。

触发条件：应用 shutdown 恰在 `_connect()` 的 `create_connection` 调用期间。

**修复建议：** `close()` 应先设置 `self._running = False`，再获取 `_reconnect_lock` 后关闭 WS 和 target，确保与 `_connect`/`_reconnect` 互斥。或者在 `_reconnect` 和 `_ensure_ws` 的 retry loop 中检查 `self._running`。

---

### Dim 3 — 资源与性能

**【P2-03】cdp_engine.py:691-713, 781-791 — `_reconnect` 和 `_ensure_ws` retry loop 不检查 `self._running`**

反模式：**线程池资源耗尽（阻塞无超时）**

证据链：`_reconnect()` 的 3+retry 循环（line 691-713）和 `_ensure_ws()` 的 3+retry 循环（line 773-791）在 shutdown 期间（`self._running=False`）仍持续重试，最长 45s。虽然 `close()` 会关闭 WS，但重连线程会在 `_connect()` 的 `create_connection` 处反复失败，每次失败后 sleep 2s 再重试。

触发条件：应用 shutdown 时恰好有重连进行中。

**修复建议：** 在每个 retry loop 的 `time.sleep(2)` 前加 `if not self._running: return`。低风险改动。

---

### Dim 5 — 结构与可维护性

**【P2-04】cdp_engine.py:764-768 — `_ensure_ws` 中 `self._ws.close()` 在 `_ws=None` 时触发 AttributeError**

证据链：当 `self._ws` 为 None 时（line 758 `if self._ws:` 分支跳过），执行到 line 767 `self._ws.close()` 抛 `AttributeError`，被 `except Exception: pass` 吞掉。功能正确但不优雅。

**修复建议：** 改为 `if self._ws: self._ws.close()` 或直接删除 line 767-768（因为 `self._ws` 在 line 770 被置为 None）。

---

**【P2-05】cdp_engine.py:648-669 — `_close_target` 非线程安全的 read-and-clear**

证据链：`_close_target()` 读取 `self._target_id` 赋给局部变量 `tid`，然后 `self._target_id = None`。若两个线程同时调用（`close()` + `_reconnect()`），两者都读到同一个 `tid` 值，都尝试关闭同一个 tab。第二次关闭被 Chrome 拒绝（"target not found"），异常被 `except: pass` 吞掉。功能正确但产生无谓的网络往返。

**修复建议：** 用 `self._target_id` 的原子 swap：`tid = self._target_id; self._target_id = None` 在 CPython 中由于 GIL 实际上是原子的，但可以用 `threading.Lock` 或简单的 flag 改进。优先级低，不阻塞。

---

## 五、修复建议优先级

| 优先级 | ID | 动作 |
|--------|-----|------|
| 应修复 | P1-01 | `_maybe_reconnect` 增加 deadline 检查或异步化 |
| 应修复 | P1-02 | `close()` 获取 `_reconnect_lock` 或 `_reconnect`/`_ensure_ws` 检查 `_running` |
| 可选 | P2-03 | retry loop 加 `_running` 检查（与 P1-02 共同修复） |
| 可选 | P2-04 | `_ensure_ws` 删除无效 `.close()` 调用 |
| 可选 | P2-05 | `_close_target` 文档化 double-close 安全性 |

---

## 六、评审结论

**⚠️ 无 P0，2 个 P1 需评估后决定修复或接受风险**

P1-01（45s 阻塞）和 P1-02（close 竞态）均为极端边界场景（Chrome OOM + 阈值命中 / shutdown 竞态），但代码路径真实存在。建议至少修复 P1-02（在 retry loop 加 `_running` 检查，改动 <5 行），P1-01 可记录为已知限制。

---

## 漂移检测

### D1 契约核对
`doc/detailed/` 目录为空，无详设文档可供对照。**N/A — 无契约可漂移。**

### D2 DOC_SYNC 追溯
无 `>>DOC_SYNC:` 标记（纯代码修复轮，未变更公开 API 签名）。**N/A。**

### D3 规范合规
- 项目规则 `code-discipline.md` 要求"手术式修改"：本次变更聚焦于并发锁和错误路径，未"顺手改进"无关代码。✅
- 项目规则 `arch-thinking.md` 要求"一处数据只改一处"：`_restart_counter_lock` 作为类级锁保护类变量 `_nav_restart_counter`，符合模式。✅
- 项目约定无 `conventions.md`（`.opencode/project/` 未生成）。**N/A。**

### D4 漂移结论
✅ 无漂移。本次修复未变更公开 API 签名（`get_data()`, `refresh()`, `evaluate_fetch()`, `navigate_stock()`, `close()` 签名均未变），未新增/删除字段，未改变返回值语义。调用方 `server.py` 和 `stock_api.py` 无需同步修改。
