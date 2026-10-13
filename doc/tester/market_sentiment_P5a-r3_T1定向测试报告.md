# market_sentiment P5a-r3 · T1 定向测试报告（独立验证）

> **轮次** P6c-r3 · T1 · **被测增量** P5a-r3（A 单调钟 / B HEAD 内在守卫 / C episode 清除）
> **改动面** `china_finance_rss/server.py`（+26/-1）· `tests/test_server_http.py`（+112/-1）
> **基线** HEAD `bd95e17`（经 `git archive` 导出独立目录实测，非照抄任务书数字）
> **日期** 2026-10-13 · **产出** tester（独立验证，未采信开发者自报结论）

## 1. 执行概要

| 项 | 结果 |
|---|---|
| **结论** | ✅ **PASS** |
| 全量回归（工作区，2 次独立跑） | **Ran 568 · OK · skipped=4**（5.14s / 5.21s），0 fail 0 error |
| 基线（HEAD archive 独立跑） | Ran 565 · OK · skipped=4 → **+3 = MS-T18/T19/T20，与任务书吻合** |
| 3 修复独立验证 | **A/B/C 全部成立**（行为正证 + 区分性实验 + 变异必红 + 还原恢复，四段闭环） |
| 顺序 / Flaky | ClsPoolTests ×5、HttpSemanticsTests ×5、双向组合 —— **全绿，无顺序敏感** |
| **缺陷** | **P0=0 · P1=0 · P2=0** |

## 2. 缺陷清单

无。三条修复的实现、新用例的断言与 hermetic 均通过独立探针实证，未发现缺陷。

## 3. 全量回归

| 跑法 | Ran | 结果 |
|---|---|---|
| 工作区全量 `discover -s tests`（第 1 次，-v） | 568 | OK (skipped=4) |
| 工作区全量（第 2 次，复跑确认稳定） | 568 | OK (skipped=4) |
| 基线 `git archive HEAD` → /tmp 独立全量 | 565 | OK (skipped=4) |
| `test_server_http.py` 单模块 | 148 | OK (skipped=4) |
| `test_stream.py` 单模块 ×3 | 137×3 | 全 OK（噪音见 §5） |

- 4 个 skip 全部是 `ClsPoolIntegrationTests`（需 `CLS_INTEGRATION=1` 打真上游的冒烟），与本增量无关、与基线一致，**无新增 skip 掩盖**。
- 差值 568−565=3，与新增用例 MS-T18（:429）/ MS-T19（:468）/ MS-T20（:1234）一一对应，无其它增减。

## 4. 逐条独立验证

探针全部位于 `/tmp/opencode/p5ar3/`（仓库外），变异一律为**进程内等价注入**（源码字符串替换 + exec 重建 / 函数替换），每个变异实验均含「变异→红 / 还原→恢复绿」闭环。

### 4.1 修复 A — 单调钟（MS-T18）✅ 成立

探针 `probe_a_monotonic.py`：

- **A1 行为正证**：受控注入 `time.monotonic` = 1000.0 → 首次 warn 且表内时间戳 == 1000.0；推进到 `1000+GAP-0.5`（窗口内边界-ε）→ 静默；`1000+GAP+0.5`（边界+ε）→ 再 warn 且表内 == 该读数。窗口边界判定精确落在 GAP 上。**通过**。
- **A2 区分性实验（墙钟跳变）**：真实 `time.time` 前跳 1 小时（模拟 NTP forward step）而 monotonic 仅 +10s ⇒ 现实现保持静默；**同一场景**等价注入修复前的 `time.time` 版 `_warn_pool_fetch_failed` ⇒ 立即 re-warn（窗口被跳变打穿）。证明窗口判定**只认 monotonic 读数**，墙钟免疫成立。**通过**。
- **A3 变异必红**：进程内把 `_warn_pool_fetch_failed` 换成逐行等价的 `time.time` 版 → 跑仓库真实 MS-T18：**PASS → FAIL（1 failure，注入钟到不了墙钟实现 + 存的是 epoch 非 1040.0，双断言均可证伪）** → 还原 → 恢复 PASS。**通过**。
- **附：MS-T17 判别力备案** — MS-T17 在变异 A 下仍 PASS（其过期播种在两种实现下都会过期，**不判别时钟源**）；反向实验证明 MS-T17 的播种必须随实现切换（新实现 + 旧 `time.time` 口径播种 ⇒ monotonic−epoch 为大负数 < GAP ⇒ 永不过期 ⇒ 必红），故 :414-419 的播种修改是**必要配套**而非顺手改。判别力分工：MS-T17 测过期分支语义、MS-T18 锁时钟源，合理。

### 4.2 修复 B — HEAD 内在守卫（MS-T20）✅ 成立

探针 `probe_b_head_guard.py`（真实 `BoundedThreadPoolServer` + 裸 socket 读线上字节）：

- **B1 漏传 write_body 的调用点**：把 `_handle_request` 换成一个「忘记 plumbing、恒走默认 `write_body=True`」的 leaky 分支（`_send_json(...)` 不传 write_body）→ 裸 socket：GET 有完整 body（自证读法有效）且 Content-Length == body 字节长；**HEAD body == b''，Content-Length = 29 > 0 且与 GET 同值**（GET 口径头保留，RFC 9112 §9.3.2）。**通过**。
- **B2 变异必红**：`inspect` 取 `_send_text` 源码、把守卫条件替换回裸 `if write_body:`、exec 重建（磁盘未动）→ 同一 leaky 线上 **HEAD body 出现 29 字节 JSON ⇒ B1 断言必红**；还原 → body 恢复 b''。**通过**。
- **B3 守卫默认值**：无 `command` 属性的对象 + `write_body=True` ⇒ 正常写体不崩（`getattr` 默认 None 分支安全）；`command='HEAD'` + `write_body=False` ⇒ 不写；`command='HEAD'` + 默认 True ⇒ **不写**（内在守卫生效，即"漏传"场景的兜底）；GET 路径写体不受影响。**通过**。

### 4.3 修复 C — episode 清除（MS-T19）✅ 成立

探针 `probe_c_episode.py`：

- **C1 行为正证**：fail(warn) → 同 fail 窗口内(silent) → success ⇒ 表中 `up_pool` 条目消失、**他池 `down_pool` 预置条目保留**（pop 是单 key，不误伤）→ 同消息再 fail ⇒ **再 warn（新 episode）**。**通过**。
- **C2 变异必红**：进程内等价变异（源码删除 `_pool_fetch_warned_at.pop(pool_type, None)` 行 + exec 重建）→ 跑仓库真实 MS-T19：**PASS → FAIL**（末次 `assertLogs` 找不到记录）→ 还原 → 恢复 PASS。**通过**。
- **C3 逆向边界（详设没写的分支）**：只有**成功**才 pop —— 业务失败（`code!=200`）不 pop、形状错误（`data` 非 list）不 pop、枚举门 early-return 完全不碰表；malformed JSON 触发「变更消息即时再告警」并刷新条目（P2-5 既有设计语义），episode 同样未结束。**通过**。
- **C4 hermetic / 顺序独立性**：先向 `_pool_fetch_warned_at` 污染 `up_pool`+`down_pool` 脏条目，再按**正序与倒序**分别跑 MS-T17→T18→T19：每条用例全绿，且**每条用例结束后表内容与污染快照逐字相等**（save/clear/restore 是真隔离，非"碰巧没被查"）。**通过**。

## 5. 顺序 / Flaky 排查

| 项 | 结果 |
|---|---|
| `ClsPoolTests` 独立定向 ×5 | 每次 17 tests 全绿 |
| `HttpSemanticsTests` 独立定向 ×5 | 每次 20 tests 全绿 |
| 组合 ClsPool→HttpSemantics | 37 OK |
| 组合 HttpSemantics→ClsPool（倒序） | 37 OK |

**ConnectionResetError 归因**：单跑 `test_stream.py` ×3，**每次稳定复现 2 次**该异常打印，但 rc=0、137 tests 全 OK；基线（HEAD archive）全量跑中同样出现；第二次工作区全量跑则完全未出现。来源是 stream 集成测试里客户端提前断连、`socketserver` 工作线程 `recv` 时对端 RST 的**服务器侧打印噪音**（`process_request_thread` → `readline`），与 P5a-r3 无关（本增量未触 stream 路径）。**判定：既有偶发噪音，非 flaky 用例，不计缺陷。**

## 6. 非预期发现

1. **doc/detailed 三文件在我测试期间被并行修改**（`server.md` → v1.21、`cls_pools.md` → v1.0.4、`market_sentiment_独立接口.md`）—— 内容是 P7b-r4 契约同步，与本批 3 修复对齐（O1 守卫伪代码、monotonic/episode 语义登记、MS-T18/19/20 测试登记）。**非我改动**（我的写入全部在 /tmp + 本报告；`server.py`/`test_server_http.py` md5 开工与收尾一致）。内容与代码无矛盾，但提醒编排层：这 3 份 doc 与代码构成同一未提交变更集，提交时须一并 review。
2. `opencode.json` 存在开工前已有的未提交改动（各 subagent `model` 字段），与本增量无关。
3. **MS-T17 不判别时钟源**（见 §4.1 备案）—— 判别力集中在 MS-T18，属用例分工而非缺陷；已实证 MS-T17 的播种修改是新实现下的必要配套。
4. 命名双轨观察（不计缺陷）：doc 侧登记用 POOL-T16/T17、代码注释用 MS-T18/T19，双侧互相交叉引用可追溯，且延续了既有模式（POOL-T15 ↔ 限频用例），不影响执行与判定。

## 7. 纪律与还原声明

- **md5 核验（开工 vs 收尾）**：`china_finance_rss/server.py` = `0875a73c37f83a320f02cd553c98299c`、`tests/test_server_http.py` = `479d37770146a9932701adfae1ec4b7c` —— **两时点一致，全程未修改**。
- 所有变异均为**进程内等价注入**（A：替换 `_warn_pool_fetch_failed` 函数；B：源码字符串替换守卫条件 + exec 重建 `_send_text`；C：源码删除 pop 行 + exec 重建 `handle_cls_pool`），运行结束即还原，且每项均做「还原后再跑恢复 PASS」闭环验证，无残留。
- 探针文件位于 `/tmp/opencode/p5ar3/`（probe_a / probe_b / probe_c + baseline HEAD archive），**均在仓库外**。
- **仓库内唯一新增文件为本报告**。git status 中 `doc/detailed/*` 三文件为并行 doc-sync 产物（§6.1），非本轮测试改动。

## 8. 结论

✅ **PASS**。三条修复（A 单调钟 / B HEAD 内在守卫 / C episode 清除）经独立探针**全部成立**：行为正证、区分性实验、变异必红、还原恢复四段闭环齐全；新用例 hermetic 与顺序独立性经污染实验实证；全量 568 OK（skip=4）与基线 565+3 吻合；无顺序敏感、无 flaky 用例、无 P0/P1/P2。可以放行进入下一轮。
