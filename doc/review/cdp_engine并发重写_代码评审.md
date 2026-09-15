# cdp_engine.py CDP 引擎并发重写 _代码评审

- **CR 编号：** CR-20260915-003
- **评审模式：** 组B 并发重写评审（feature/stream-push，对比 main +481 行）
- **日期：** 2026-09-15
- **评审范围：** `cdp_engine.py`（全文 1294 行）
- **关联文档：** `doc/review/cdp_engine_代码评审.md`（r1）、`doc/review/缓存协同修复r1复审_代码评审.md`（r1-r2）、`doc/review/对抗性盲审报告.md`（P8）

---

## 一、评审概要

**总评：** 锁体系设计正确（全局锁序无环、`_ws_lock` 用 RLock 覆盖重入、`_reconnect_lock` 串行化重连）、台账/预算机制（`_created_targets` + `_HARD_CAP` + `close_budget`）有效打断 OOM 正反馈、P8 盲审的 `_close_failures` 死条目泄漏已修复。**但存在 1 个 P1 新回归**：`_maybe_reconnect` 把 `full_chrome_restart`（最坏 ~17s）+ `_reconnect`（最坏 ~80s）放进**类级全局锁** `_restart_counter_lock` 内，触发页持锁期间**所有页面**的 `navigate_stock` 被整体卡死（每 30 次导航触发一次，2C2G 并发负载下可每几分钟一次全局导航停顿 4-24s、崩溃恢复期 60s+），比历史 P1-01（单页阻塞）更严重。

| 等级 | 数量 | 处理 |
|------|------|------|
| P0 | 0 | — |
| P1 | 1 | 应修复（生产版阻断） |
| P2 | 9 | 记录，不阻断 |

---

## 二、受影响的调用方（供编排器映射 tester `>>SCOPE:`）

入参无 `>>SIDE-EFFECT:` 标记，从 diff 推断：

| 受影响点 | 行为变化 | 所属模块 |
|---------|---------|---------|
| `CDPPage._maybe_reconnect` 计数+重启 | 30 次导航触发 `full_chrome_restart`（杀全部 Chrome）→ 所有页 WS 断 → 心跳页经 `_reconnect`、导航页经 `_ensure_ws` 恢复；计数为**类级跨实例共享** | cdp_engine（调用方：`navigate_stock` → `stock_api._navigate_f10`/`fetch_cls_f10`） |
| `CDPPage._connect/_close_target` 台账 | 每个 tab id 记入 `_created_targets`，失败 close 节流重试，`_HARD_CAP`≈40/页硬封顶 | cdp_engine（调用方：`_reconnect`/`_ensure_ws`/`close`/`_heartbeat` sweep） |
| `CDPPage._ensure_ws` 重连语义 | WS 失效时 35s budget + 45s retry window 内重建，Chrome 崩溃自动 restart | cdp_engine（调用方：`navigate_stock`/`evaluate_fetch` ← `stock_api._evaluate_fetch_any`） |
| `navigate_stock` 快路径 | `_last_data.basic_info.secu_code` 匹配即跳过导航（≤10min 旧数据可被当作新鲜） | cdp_engine（调用方：`stock_api.fetch_cls_f10`） |
| `full_chrome_restart` 全局重启 | watchdog（server.py `_cdp_memory_watchdog`）与 `_maybe_reconnect` 双源，`_chrome_restart_lock` 串行 | cdp_engine + server.py |

---

## 三、问题清单

### P0 — 无

### P1（应修复，生产版阻断）

**【P1-01】cdp_engine.py:1064-1074 — `_maybe_reconnect` 将 `full_chrome_restart` + `_reconnect` 置于类级全局锁内，触发时全局导航停顿 4-24s（崩溃恢复期 60s+）**

反模式：**锁作用域过大（全局锁内执行长阻塞 IO）/ 线程池资源耗尽无超时**

证据链：
- `_restart_counter_lock` 是**类级**锁（L1052），所有 CDPPage 实例共享。
- L1064-1074：`with CDPPage._restart_counter_lock:` 块内除了计数 `+=1`/比较/归零，还包含了 `full_chrome_restart()`（L1070，内部 kill+pkill+SIGKILL+`ensure_chrome` 15×1s 轮询，正常 2-17s）和 `self._reconnect()`（L1072，phase1 3 attempts×5s + 失败后 45s retry window）。
- 当 page A 满足 `count >= 30` 触发重启时，持有 `_restart_counter_lock` 最长 ~80s。此时 **page B/C 的 `navigate_stock`（L1102 调 `_maybe_reconnect`）在 L1064 等同一把全局锁**——而 B/C 在 L1096 已持有各自的 `_navigate_lock` → B/C 页的导航请求队列整体挂起。
- 触发频率：3 个 stock 导航页共享类级计数（`config.stock_nav_page_names()` 默认 3 页），30 次**任意页**导航即触发一次；`fetch_cls_f10` 并发 12 的历史负载下 30 次导航几十秒到几分钟累积 → **正常负载下每几分钟一次全局导航停顿 4-24s**；若触发时恰逢 Chrome OOM 崩溃恢复，`_reconnect` 的 45s retry window 使停顿达 60s+。
- 上游 `_navigate_f10`（stock_api.py:457）的 `remaining < 2` 门在 `_maybe_reconnect` 阻塞期间**无法生效**（阻塞发生在 `navigate_stock` 锁内、deadline 检查之后），请求线程在锁等待中不可中断，最终晚于上游 deadline 返回 False —— 超时请求仍占满线程池，2C2G 上放大资源压力。
- 对比：历史 CR-20260914-001 的 P1-01 是"单页 `_navigate_lock` 内阻塞 45s"；本分支把同样的阻塞动作移进了**跨页全局锁**，波及面从 1 页放大到全部导航页。

修复建议（最小改动，锁内只做计数，动作移出锁外）：
```python
with CDPPage._restart_counter_lock:
    CDPPage._nav_restart_counter += 1
    if CDPPage._nav_restart_counter >= self._MAX_PAGE_NAV_BEFORE_RECONNECT:
        CDPPage._nav_restart_counter = 0
        restart = True
    else:
        restart = False
if restart:
    full_chrome_restart(f"http://{self.cdp_host}:{self.cdp_port}")
    self._reconnect()
    return True
return False
```
`full_chrome_restart` 内部已有 `_chrome_restart_lock` 保证"双页同时触发也只有一人重启"；B 页在 A 重启期间拿到计数锁时 count=1 不进 if，随后走 `_ensure_ws` 在**新 Chrome** 上重连（`_ensure_ws` phase2 的 `ensure_chrome` 会被 `_last_chrome_restart` throttle 挡住 ≤15s，但那是每页 `_reconnect_lock` 上的有界等待，不占全局锁）。若需彻底消除导航路径的重启阻塞，可将重启动作拆到独立线程（触发后本页本次导航走一次 `_ensure_ws` 兜底）。

---

### P2（记录，不阻断）

**【P2-01】cdp_engine.py:632-696 — 隐式锁序 `_lock` → `_ws_lock` 靠"恰好无反向嵌套"维持，未文档化**

证据链：`refresh()`（L999）`with self._lock:` 内调 `_ingest_payload` → L696 `_re_fetch_api` → L578 `with self._ws_lock:`。反向序（持 `_ws_lock` 再取 `_lock`）经全文件逐一核对**不存在** → 当前无死锁。但该顺序无注释声明，未来维护者在 `_evaluate`/`re_fetch_api` 的 `_ws_lock` 块内加入数据读取（`get_data` 类）即引入反向嵌套 → 与心跳 ingest 路径构成 ABBA 死锁。
修复建议：在 `_lock` 与 `_ws_lock` 声明处加注释固化锁序（`_chrome_restart_lock → _reconnect_lock → _ws_lock → _lock`，`_lock → _ws_lock` 仅限 ingest→refetch 单链），评审清单加一条锁序检查。

**【P2-02】cdp_engine.py:705-710, 559-566 — `_evaluate` 把 CDP error 响应折成 None，心跳把"瞬时 JS 求值错误"误判为"interceptor 丢失" → 无谓全页重连 + `cache.clear()`**

证据链：`_send_recv_on` 匹配到带 `error` 的响应（L542-543 只查 `id` 不查 `error`）→ L566 `result.get('result', {})...` 得 None → 心跳 L706 `alive = self._evaluate(...)` 为 None → `if not alive:`（L707）真 → `_reconnect()`。触发场景：`navigate_stock` 的 `Page.navigate`（L1110）整页加载期间 ExecutionContext 销毁/重建，心跳（10s 周期）撞上 1-3s 导航窗口的概率约 10-30% → 每次导航有可观概率触发一次全页重连（35s budget + `cache.clear()` L932）。`_last_data` 兜底保证数据不丢，但 L1 级数据（TTL 8s）在重连窗口内可从 `_last_data` 拿到 ≤600s 旧值。
修复建议：`_evaluate` 区分"error 响应"与"正常空值"，error 时返回哨兵或抛异常；心跳 alive 检查改为 `_send_recv` 显式判 `error`。最低成本：心跳对 None 结果不立即 `_reconnect`，连续 2 次 None 才触发（复用 empty_count 机制）。

**【P2-03】cdp_engine.py:791-800/843/470 — `_close_failures` 读写脱离 `_ws_lock`/`_reconnect_lock`，并发 close 窗口内 fail_count 可能双计**

证据链（P8 盲审已报，本分支未改）：L470/L824/L843 写、L793-794 读均在锁外；`close()`（L1239）不持 `_reconnect_lock` 与会话期心跳/重连并发执行 `_close_target` → 双线程从同一 `(ts, 2)` 各 +1 → 都写 3 → 提前 drop（tab 残留 Chrome）。GIL 保 dict 原子、watchdog 兜底收敛，影响限于 drop 时机偏差。修复方向：`_close_failures` 的读写归入 `_ws_lock` 临界区（与 `_created_targets` 同锁）。

**【P2-04】cdp_engine.py:1239-1248 — `close()` 不持 `_reconnect_lock`（历史 P2-01 延续，本轮未修）**

证据链：`close()` 置 `_running=False` 后直接 `_ws.close()` + `_close_target()`，与 `_reconnect`/`_ensure_ws`（持 `_reconnect_lock`）并发 → close 的 `_close_target` 可能换走一个 `_connect` 刚写入的新 tid → 重连线程对已关 tab 建 WS 失败 → 多一次重试。仅终止路径可达（L937 `_running` 门已让重试收敛，白跑 ≤15s）。
修复建议：`close()` 先 `with self._reconnect_lock:` 再置 `_running=False` + 关 WS + `_close_target`。

**【P2-05】cdp_engine.py:941-947 / 1029-1036 — `_reconnect`/`_ensure_ws` phase-1 的 for-attempt 循环无 `_running` 门**

证据链：`close()` 后 `_running=False`，但 phase-1 的 `for attempt in range(3)`（L941、L1029）仍完整跑 3 次（每次 `_connect` ≤5s + 2s sleep ≈ 15s 白跑，期间 phase-2 的 `while self._running and ...` 才退出）。历史 P2-03 已部分修复（phase-2 加了 `_running`），phase-1 未加。
修复建议：`for` 循环体顶部 `if not self._running: return/break`。

**【P2-06】cdp_engine.py:1090-1093 — `navigate_stock` 快路径只比对 `basic_info.secu_code`，Chrome 崩溃后 10 分钟内可返回"已就绪"而实际页面已死**

证据链：`cached == stock_code` 时直接 `return True`（L1093），不验证 WS/页面存活。若 Chrome 在导航成功后崩溃，`_last_data` 仍保留 secu_code + `stock_company_info`（`_last_data_max_age=600`）→ 后续同 code 请求快路径命中 → 上游 `fetch_cls_f10` 从 `get_data()` 取到 ≤10min 旧数据且 `_company_info_matches` 通过。F10 为日更数据，RSS 场景影响低。
修复建议：快路径命中时对命中 code 校验 `self._ws` 存活（一次 `_evaluate('1', timeout=1)`），连接断开则走慢路径。

**【P2-07】cdp_engine.py:1050-1052 — 类级 `_nav_restart_counter` 隐含"单 Chrome 端口"部署假设**

证据链：计数为类级共享，而 `full_chrome_restart` 只重启 `self.cdp_host/port`（L1070）。若同一进程创建指向不同端口的 CDPPage（当前部署单端口不会），A 端口页面计数被 B 端口导航消耗、B 到阈值触发时重启的是 B 端口 → A 端计次丢失或重启错目标。仅为当前部署形态下的隐式约束。
修复建议：类注释声明"计数器跨实例共享的前提是单 Chrome 实例"；或改实例级计数 + i 类级重启节流。

**【P2-08】cdp_engine.py:1094-1096 — 注释声称 "fair queuing via blocking lock"，但 `threading.Lock` 无公平性保证**

证据链：CPython `threading.RLock` 的等待者唤醒顺序不保证 FIFO，重负载下个别请求可能被反复插队（饥饿）；上游 deadline 兜底（`_navigate_f10` 的 `remaining < 2`）使饥饿最终以失败终结。RSS 低并发下不可见。修复建议：注释改 "blocking queue（无超时重试）"，不承诺公平；或使用 `threading.Condition` + FIFO 队列（成本高，不建议）。

**【P2-09】cdp_engine.py:254 — `full_chrome_restart` 内 `gc.collect()` 对子进程 Chrome 无内存效果**

证据链：`gc.collect()` 回收的是**本 Python 进程**的对象，Chrome 是 `subprocess.Popen` 子进程，其 V8/renderer 内存不受影响。注释语境（"2c2g OOM recovery"）暗示它回收 Chrome 内存——实际只清理 Python 侧 CDP 对象，Chrome 内存回收靠 `--max_old_space_size=512` + kill 重启。修复建议：删除或改正注释（kill 本身才是内存回收手段），`gc.collect()` 保留无害。

---

## 四、覆盖的检查维度清单

| 维度 | 覆盖内容 | 结论 |
|------|---------|------|
| Dim 0 契约一致性 | `doc/detailed/` 不存在（`doc/` 仅有 review/、tester/）→ 无详设可对照，**N/A（跳过）**。stock_api 侧配合（`_get_page_fetch_lock` per-page 锁、`_navigate_lock` RLock 公开访问、`fetch_cls_f10` 持锁导航+读）与 cdp_engine 实现逐点核对一致 | ✅ 一致 |
| Dim 1 数据与正确性 | 快路径 secu_code 匹配（P2-06）、stable_count 错误码判定（`>=3` 且 `nav_started>6s` 才 fail-fast，与并发过渡期注释自洽）、tab 点击后 refresh、`_ingest_payload` TTL/MAX_KEYS 双上限一致性（cache evict 不破坏 `_last_data` 兜底语义） | ✅ 逻辑自洽（2 条 P2） |
| Dim 2 并发 | 六把锁的获取顺序全链审计：全局 `_restart_counter_lock → _chrome_restart_lock → _reconnect_lock → _ws_lock → _lock` 无环、无反向嵌套；`_ws_lock` RLock 覆盖 `_send_navigate` 内 `_evaluate` 重入；`_heartbeat` sweep 的 `_ws_lock` 短持释放后再取 `_reconnect_lock`（timeout=2）无锁序冲突；`_close_target` 幂等 double-close 安全 | ✅ 无死锁（P1-01 锁作用域问题 + P2-01/03/04 记录） |
| Dim 3 资源与性能 | `--max_old_space_size=512`；`_HARD_CAP≈40/页` 台账硬封顶（软 evict 优先、硬 cap 越权 throttle、drop 放弃追踪均正确）；`close_budget` 贯穿全部 7 个 `_close_target` 调用点；`_connect`/`_create_target` 网络操作 5s 定界；2h watchdog 兜底真实 tab 收敛 | ✅（P1-01 全局停顿 + P2-09 记录） |
| Dim 4 安全 | `navigate_stock` URL 经 `json.dumps` 转义；`evaluate_fetch`/`re_fetch_api` 的 `escaped` 双替换（`\` `"`）封住 JS 字符串注入；`stock_code` 注入面被上游 `VALID_STOCK_CODE` 正则前置校验 | ✅ 无注入/越权面 |
| Dim 5 结构与可维护性 | heartbeat=True/False 分层（心跳页/懒重连导航页）；`_reconnect`/`_ensure_ws` budget 语义一致（35s + 45s window）；docstring 与行为一致（L477-480 的 elif pop 注释已同步修复）；`RE_FETCH_AFTER=25` 魔法数字一处 | ✅（2 条 P2） |
| 逆向审查 | ⚠️ 恶意输入：stock_code 注入面封死（见 Dim 4）✅；竞态：`_connect` 无锁写 `self._ws` 与 `_evaluate` 并发 → 旧 socket 异常被捕获、无损坏 ✅；依赖失效：Chrome 崩溃 → `_close_one_target` 双通道（browser WS + HTTP /json/close）降级 ✅；隐式假设：`tabs[0]['webSocketDebuggerUrl']` 用于 browser 命令（Target domain 经 page WS 路由，Chrome 实测可用）⚠️ 文档化不足；性能悬崖：`_maybe_reconnect` 全局锁（P1-01）、`_ensure_ws` 80s 阻塞导航（有上游 deadline 兜底）⚠️ | 2 项 ⚠️ 已入 P1/P2 |

---

## 五、总体结论

**⚠️ 条件放行（1 个 P1 需修复后合入生产）。**

- P1-01（`_maybe_reconnect` 类级全局锁内长阻塞）是本次并发重写的**新回归**：修复成本 <10 行（计数与动作分离），不修则 2C2G 并发负载下每几分钟出现一次 4-24s（崩溃恢复期 60s+）的全导航面停顿，直接违背"接口稳定/风暴收敛"的变更目标，**合入生产前必须修复**。
- 其余 9 条 P2 均不阻断：锁序固化（P2-01）与 `_evaluate` 错误区分（P2-02）建议紧随 P1-01 一并处理，其余记入待办。
- 无 P0：无崩溃/资金/数据丢失路径（`_last_data` 兜底 + 台账双上限 + watchdog 硬兜底构成三层防护）。

---

## 六、漂移检测

- **D1 契约核对：** `doc/detailed/` 不存在，无详设契约可供对照；公开 API 签名（`get_data`/`refresh`/`evaluate_fetch`/`navigate_stock`/`close`）与 stock_api.py 调用方逐点核对一致，无漂移。**N/A。**
- **D2 DOC_SYNC 追溯：** 本轮无 P5a `>>DOC_SYNC:` 标记待验证。**N/A。**
- **D3 规范合规：** 常量走 config/env（`CDP_RESTART_THROTTLE`/`_MAX_PAGE_NAV_BEFORE_RECONNECT` 类常量）；锁复用既有体系、无新增第三方依赖；`code-discipline.md` 手术式修改原则遵守（未发现无关改动）。✅
- **D4 漂移结论：** ✅ **无漂移。**（策略性备注：若编排器计划在后续详设中回注 CDP 锁序与 tab 台账语义，属文档增强，非漂移修复，可选执行。）

---

## 七、修复建议优先级

| 优先级 | ID | 动作 | 工作量 |
|--------|-----|------|--------|
| 应修复（本轮） | P1-01 | 计数与 `full_chrome_restart`+`_reconnect` 动作分离出 `_restart_counter_lock` | <10 行 |
| 建议（随本轮） | P2-01 | `_ws_lock`/`_lock` 声明处固化锁序注释 | 3 行注释 |
| 建议（随本轮） | P2-02 | `_evaluate` 区分 error 响应，心跳对 None 不立即重连（连续 2 次才触发） | ~15 行 |
| 待办 | P2-03/04/05 | `_close_failures` 入锁、`close()` 持 `_reconnect_lock`、phase-1 加 `_running` 门 | 各 ≤5 行 |
| 待办 | P2-06 | 快路径加 WS 存活校验 | ~5 行 |
| 记录 | P2-07/08/09 | 文档/注释修正 | — |

---

## 八、稳定项目约定回写

```
>>PROJECT: 锁体系与锁序 → CDP 全局锁序固定为 _chrome_restart_lock(RLock,模块级) → _reconnect_lock(实例) → _ws_lock(RLock,实例) → _lock(数据,实例)；唯一反向嵌套是 _ingest_payload→_re_fetch_api 的 _lock→_ws_lock 链（仅此一处）；新代码禁止引入 _ws_lock→_lock 嵌套
>>PROJECT: CDP 有界重试 → 所有 CDP 网络操作 settimeout 有界（2-5s/操作），重连路径用绝对 budget（time.time()+N）跨 attempt 共享，_close_target 一律 close_budget=time.time()+5；新代码遵循同一 "budget + settimeout" 模式
```

---

## 变更记录

| 版本 | 日期 | 变更 |
|------|------|------|
| v1.0 | 2026-09-15 | 首轮评审（feature/stream-push 组B：CDP 引擎并发重写），结论 ⚠️ 条件放行 |