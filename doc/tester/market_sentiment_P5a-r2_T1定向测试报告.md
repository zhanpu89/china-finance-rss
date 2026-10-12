# market_sentiment P5a-r2 · T1 定向测试报告（Bug-fix Loop P6c-r2，独立验证）

- **阶段**：Bug-fix Loop 定向测试（T1）｜`>>MODE: T1 定向测试（P6c-r2）`
- **日期**：2026-10-10
- **被测增量（P5a-r2，3×测试侧修复，无生产代码变更）**：
  1. 【P1】MS-T13 `test_fetch_failure_logs_a_warning_before_degrading` 及同源 `test_fetch_or_decode_failure_degrades_without_raising`、`test_pool_upstream_failure_is_200_with_error_body` 增加 `server._pool_fetch_warned_at` save/clear/finally-restore 隔离，消除顺序耦合（r1 报告 F1 的修复）
  2. 【P2】SRV-T33 `test_head_writes_no_body` 删除恒真 HEAD body 断言（只留状态码路由）；MS-T11b 裸 socket 循环新增 HEAD-400 路径 `/market/margin?market=bogus`（r1 报告 F3 的修复）
  3. 【P2】`test_fetch_failure_warning_is_rate_limited` 断言消息改派生自注入异常对象（`str(exc)`），去 `'upstream_timeout'` 硬编码字面量
- **前序**：P5a-r1 测试侧 3×P2 修复（r1 报告结论 PASS-WITH-NOTES）→ 本轮独立验证
- **独立性声明**：本报告全部结论来自本人自建探针/变异实验（§4/§5/§6），未引用 developer 的验证结论；探针脚本全部位于 `/tmp/opencode/`（仓库外），仓库内唯一新增文件为本报告

---

## 1. 执行概要

✅ **PASS**

| 指标 | 值 |
|------|-----|
| T2 全量 | `python -m unittest discover -s tests -v` → **Ran 565, OK (skipped=4)**，5.198s |
| 基线对比 | **565 / 4 skip = 基线 565 / 4 skip → 无回归** |
| 契约断言确认 | **19 shapes / 5 panels / 20 feeds 相关 4 条断言全绿**（§3.2） |
| 失败 / 错误 / Flaky | **0 / 0 / 0**（两被测类 34 用例 × 3 连跑全绿；Step 3.7 重试未触发） |
| 顺序独立性实验 | **探针有效（毒物能伪红无隔离复刻）+ MS-T13 hermetic 实证**（§4） |
| HEAD-400 变异 | **变异体被 MS-T11b 400 分支抓红；还原后逐字节一致**（§5） |
| 附加韧性实验 | 限速派生断言在 `FetchError.__str__` 格式漂移下保持绿（§6） |
| 缺陷 | **P0: 0 ｜ P1: 0 ｜ P2: 0 新增**（2 条观察性备注 O1/O2，不阻断，§7） |
| 残留 | **零**：`server.py` / `test_server_http.py` 实验前后 md5 逐字节一致（§8） |

> 跳过明细：4 skip 全部为 `ClsPoolIntegrationTests`（`CLS_INTEGRATION=1` 真上游门控），与基线**同数同因**；3 条修复相关用例**无一被 skip 掩盖**。

---

## 2. 缺陷清单

| ID | 等级 | 位置 | 描述 | 处置 |
|----|------|------|------|------|
| （无） | — | — | P0/P1/P2 **均 0 条**；3 条修复本身未发现缺陷 | — |
| O1 | 备注 | `china_finance_rss/server.py:1429` `_send_error` | 自定义 400 发送路径无 CPython `send_error` 自带的 HEAD 守卫（`if self.command != 'HEAD'`），400 分支「HEAD 无 body」完全依赖 `write_body` 管道正确传递（§7-O1） | 观察记录，不阻断 |
| O2 | 备注 | 同类隔离扫描 | 13 条触碰 pool 路径的用例无 `_pool_fetch_warned_at` 隔离，逐条核验均不读写该表（§7-O2） | 观察记录，不阻断 |

---

## 3. 全量回归（任务项 1）

### 3.1 结果

`python -m unittest discover -s tests -v` → **Ran 565 tests in 5.198s — OK (skipped=4)**

与基线（565 / 4 skip）**完全一致**，无新增失败、无新增 skip、无错误。

4 skip 明细（同数同因）：

| 用例 | 原因 |
|------|------|
| `ClsPoolIntegrationTests.test_up_pool_against_real_upstream` | `set CLS_INTEGRATION=1 to smoke the pools vs the real upstream` |
| `ClsPoolIntegrationTests.test_continuous_up_pool_against_real_upstream` | 同上 |
| `ClsPoolIntegrationTests.test_up_open_pool_against_real_upstream` | 同上 |
| `ClsPoolIntegrationTests.test_down_pool_against_real_upstream` | 同上 |

### 3.2 契约断言确认（19 shapes / 5 panels / 20 feeds）

| 断言 | 用例（`tests/test_server_http.py`） | 结果 |
|------|--------------------------------------|------|
| 19 shapes | `ShapeTableTests.test_json_shapes_complete_and_consistent`（`:50` `len(srv._JSON_SHAPES)==19`） | ✅ ok |
| 19 shapes + 5 panels | `MarketSentimentTests.test_registered_in_the_shape_and_dispatch_tables`（`:520-521` `19` / `len(_PANEL_HANDLERS)==5`） | ✅ ok |
| 20 feeds | `HealthPayloadTests.test_schema_check0_zero_upstream`（`:920` `len(payload['feeds'])==20`） | ✅ ok |
| 20 feeds | `HealthPayloadTests.test_feed_status_corrections`（`:931` `len(entries)==20`） | ✅ ok |

另有 `ShapeTableTests.test_every_shape_path_has_a_routed_branch`、`ClsPoolTests.test_pool_paths_registered_in_the_shape_tables` 同轮全绿。

### 3.3 修复相关用例逐条确认（均实际执行、均绿）

| 用例 | 修复归属 | 全量结果 |
|------|----------|----------|
| `ClsPoolTests.test_fetch_failure_logs_a_warning_before_degrading`（MS-T13） | 修复#1 | ✅ ok |
| `ClsPoolTests.test_fetch_or_decode_failure_degrades_without_raising`（POOL-T7） | 修复#1 | ✅ ok |
| `HttpSemanticsTests.test_pool_upstream_failure_is_200_with_error_body`（POOL-T11） | 修复#1 | ✅ ok |
| `ClsPoolTests.test_fetch_failure_warning_is_rate_limited` | 修复#1/#3 | ✅ ok |
| `HttpSemanticsTests.test_head_writes_no_body`（SRV-T33） | 修复#2 | ✅ ok |
| `HttpSemanticsTests.test_head_body_never_reaches_the_wire`（MS-T11b，含 400 分支） | 修复#2 | ✅ ok |

### 3.4 Flaky 排查

`ClsPoolTests + HttpSemanticsTests`（34 用例）独立定向 **3 连跑：3/3 OK**（0.53s/轮）→ 无顺序敏感、无 Flaky；Step 3.7 重试机制未触发。

---

## 4. 顺序独立性独立验证（任务项 2）——自建污染实验

**目标**：证明 MS-T13（及同源 3 条）对 `_pool_fetch_warned_at` 顺序污染 hermetic，且探针毒物本身致命（否则「测了但测不出」）。

**探针**：`/tmp/opencode/probe_ms_t13_isolation.py`（仓库外，跑完即弃）。

**毒物设计**（自推导，非照抄）：向 `srv._pool_fetch_warned_at['up_pool']` 预写 `(time.time(), 'upstream_timeout')` —— 消息与 MS-T13 注入的 `FetchError('upstream_timeout')` 之 `str()` 逐字相同、时间戳在 `_POOL_FETCH_WARN_GAP=30.0` 窗口内 ⇒ 命中 `_warn_pool_fetch_failed`（`server.py:470-472`）的「同消息 & 窗口内 ⇒ 静默」短路。

**三段实验**：

| 段 | 内容 | 预期 | 实测 | 判定 |
|----|------|------|------|------|
| **A 致命性对照** | 毒物预置后跑「无隔离的 MS-T13 原文复刻」（测试体逐字保留，仅去掉 save/clear/finally 三行） | **FAIL**（证明毒物能伪红修复前的测试） | **FAIL**：`AssertionError: no logs of level WARNING or higher triggered on server`（WARNING 被限速短路吞掉，`assertLogs` 落空） | ✅ 探针有效 |
| **B 修复验证** | 同毒物预置后跑**真实 MS-T13**（含 save/clear/finally） | **PASS** | **PASS**；且 `finally` 把毒物**原样恢复**（`after == before == {'up_pool': (fresh_ts, 'upstream_timeout')}`）——隔离双向正确：既不吃外层污染，也不篡改外层状态、不泄漏自身写入 | ✅ hermetic 实证 |
| **C 同源覆盖** | 同毒物下逐条跑 POOL-T7 / 限速率用例 / POOL-T11（HTTP 层） | 全 **PASS** | **3/3 PASS** | ✅ 隔离覆盖完整 |

**结论**：A 段的伪红（`no logs of level WARNING...`）与 r1 报告 F1 记录的症状指纹一致 —— 修复前该毒物确实能伪红 MS-T13；修复后 B/C 段全绿。**MS-T13 及同源用例已 hermetic，修复#1 独立验证成立。**

> 实验方法对照说明：任务建议「探针用例在 MS-T13 之前运行并预写状态」。本实验用「进程内预置 + 无隔离复刻对照」达到同等证明力且更严格——A 段同时证明了（a）毒物真实致命、（b）致命机理正是限速短路，而非无关因素。

---

## 5. HEAD-400 变异验证（任务项 3）

**方法说明**：容器纪律禁止直接 edit `china_finance_rss/server.py`（仅 `doc/tester/**`、`tests/**` 可写），故采用任务明确允许的「**等价注入**」——进程内 class-level monkey-patch `RSSHandler._send_error`，把 `write_body` 硬编码为 `True`（忽略 HEAD 传入的 `False`）。变异体逐行对应真实 bug 形态（服务器对 HEAD 的 400 真写 body），且**构造上零文件残留**。变异/还原后均以 md5 + `git status` + `git diff --stat` 三重核验（§8）。

**探针**：`/tmp/opencode/mutate_head400.py`。

| # | 场景 | 用例 | 预期 | 实测 | 判定 |
|---|------|------|------|------|------|
| 0 | 基线（无变异） | MS-T11b / SRV-T33 | 双绿 | **双 PASS** | — |
| 1 | **变异下** | MS-T11b（裸 socket） | **转红（400 分支抓到非空 body）** | **FAIL**：`AssertionError: b'{\n  "error": "Invalid ?market= parameter. Allowed: 99,1,2,3"\n}' != b'' : /market/margin?market=bogus` —— 线上确有 400 error body，**红点正是 P5a-r2 新增的 400 路径条目** | ✅ **抓红** |
| 2 | **变异下** | SRV-T33（`http.client`） | 仍绿（证明 http.client 对 HEAD 读不到 body，r1-F3 的「恒真断言」判断成立，P2-6 删除有据） | **PASS**（服务器真写了 body，client 仍读到 `b''`） | ✅ 盲区被实证 |
| 3 | 还原后 | MS-T11b | 回绿 | **PASS**；`RSSHandler._send_error is ORIG`（对象同一性校验） | ✅ 还原干净 |

**关键推论（P2-1 修复的变异证明力）**：本变异体**只**影响 `_send_error`（400 路径）。若停留在 r1 状态（MS-T11b 元组仅含 200 sentiment / 200 `/` / 404，无 400 条目），该变异体将**存活**（无用例能红）。P5a-r2 把 `/market/margin?market=bogus` 并入裸 socket 循环后，变异体在 400 分支被精确抓红 —— **r1-F3 指出的覆盖缺口经本轮变异测试证明已被真正关闭，非纸面闭合。**

**404 分支旁注**：CPython `BaseHTTPRequestHandler.send_error` 自带 `if self.command != 'HEAD' and body` 守卫，404 走该路径天然无 body；400 走自定义 `_send_error` 无此守卫 —— 这正是 400 分支必须靠 `write_body` 管道 + MS-T11b 裸 socket 双重保障的结构性原因（见 §7-O1）。

---

## 6. 附加韧性实验（修复#3 本质验证）

**目标**：修复#3 的断言改为派生自异常对象（`str(exc)`）后，对 `FetchError.__str__` 格式漂移是否 lock-step（硬编码字面量的旧断言在此漂移下会伪红/漏保）。

**方法**：进程内把 `cache.FetchError.__str__` 改为完全不含 kind 的 `'NETWORK-DRIFT'`（模拟格式演化），跑限速用例 + MS-T13，随后还原。探针：`/tmp/opencode/drift_rate_limit_msg.py`。

| 场景 | 用例 | 实测 |
|------|------|------|
| 基线 | `test_fetch_failure_warning_is_rate_limited` | PASS |
| `__str__` 漂移下 | `test_fetch_failure_warning_is_rate_limited` | **PASS**（断言 `str(exc) in line` 与 handler 侧 `msg = str(exc)` 同源漂移；过期播种 `str(exc)` 亦步亦趋，限速窗口路径仍被真实行使） |
| `__str__` 漂移下 | MS-T13 | **PASS**（其断言只锚 `'cls pool'`+`'fetch failed'`，与 kind 无关） |
| 还原后 | 限速用例 | PASS；`FetchError.__str__ is ORIG` |

**结论**：派生断言在格式漂移下保持绿且限速语义仍被完整验证 —— **修复#3 独立验证成立**（若仍硬编码 `'upstream_timeout'`，首轮断言即伪红）。

---

## 7. 非预期发现（任务项 4）

### O1 [备注·结构性观察] `_send_error` 无 HEAD 守卫，400 无 body 纯赖管道
CPython `send_error`（404 路径）自带 `if self.command != 'HEAD' and body` 守卫；自定义 `_send_error`（`server.py:1429-1432`，400 路径）**没有**等价守卫，HEAD 无 body 完全依赖调用方逐一正确传递 `write_body=False`（已核：`_handle_request` 的 market/plate/batch 三个 400 调用点均正确传参）。当前管道正确 + MS-T11b 裸 socket 400 分支锁定 ⇒ 无现行缺陷；但新增 400 调用点时若漏传 `write_body`，单元层（http.client）不可见，仅 MS-T11b 能红。**不阻断**，记录为结构脆弱点。

### O2 [备注·同类隔离遗漏扫描] 13 条无隔离用例逐条核验，无真实遗漏
静态扫描 `tests/test_server_http.py`：13 条触碰 pool 路径但无 `_pool_fetch_warned_at` save/clear 的用例。逐条分类核验：

- **不触发 warn 路径**（成功路径 / `code!=200` 业务失败路径 / enum gate / 表注册断言 / index 页）：9 条 —— `_warn_pool_fetch_failed` 仅在 `handle_cls_pool` 的 `except` 分支被调（`server.py:504`），这些用例的 `fetch_json` stub 不抛异常或走 `code!=200` 早返回，**不读不写**该表；
- **hotplate / guard 类**：3 条 —— `handle_cls_hotplate` / `_guard` 路径不触碰该表；
- **`ClsPoolIntegrationTests`（env-gated）**：真上游失败时会写表，但该场景下这些用例自身先红（`assertNotIn('error')`），且默认 skip 不入全量。

**结论**：修复#1 的隔离集合（4 条读写该表的用例）完整，无同类遗漏。

### O3 [skip 掩盖检查] 无掩盖
4 skip = CLS 真上游门控，与基线同数同因；3 条修复用例 + 2 条 HEAD 用例**均非 skip、均实际执行**（§3.3）。

### O4 [Flaky / 顺序依赖] 无
两被测类 34 用例 3 连跑全绿（§3.4）；污染实验 B 段证明 MS-T13 在**对抗性状态**下亦稳定绿。

---

## 8. 纪律与还原声明

- **全轮零文件写入生产/测试代码**：HEAD-400 变异与 `__str__` 漂移均为**进程内 monkey-patch**（等价注入），进程退出自动消失；无任何针对 `china_finance_rss/**`、`tests/**` 的磁盘修改。
- **md5 逐字节核验**（实验前后各测一次，两次一致）：
  - `china_finance_rss/server.py` = `f16256e498b42adfe6a222b85702b835`
  - `tests/test_server_http.py` = `42b08a9475dfc4ecb2c238827ed10c84`
- **git 三重核验**：`git status --short` 对两文件仅显示开发者 P5a-r2 修复本身造成的既有 ` M`（本轮前后无变化）；`git diff --stat HEAD` 两文件 151/569 行增量与本轮实验前**完全相同**（均为 P5a-r2 修复内容，非本人改动）。
- **探针残留**：全部位于 `/tmp/opencode/`（`probe_ms_t13_isolation.py` / `mutate_head400.py` / `drift_rate_limit_msg.py`），仓库外，不入版本库；探针进程内状态（`_pool_fetch_warned_at`、`FetchError.__str__`、`_send_error`）均在 `finally`/进程退出时还原并经对象同一性校验。
- **本轮唯一新增仓库文件**：本报告 `doc/tester/market_sentiment_P5a-r2_T1定向测试报告.md`。
- 还原后复跑全量：**565 OK (4 skip)**（§3 即还原态结果）。

---

## 9. 结论

✅ **PASS**

- 全量 **565 / 4 skip 与基线完全一致**，无回归、无 P0/P1/P2 新增缺陷。
- **3 条修复全部经独立实验证实有效，非纸面闭合**：
  1. 测试隔离：探针毒物（a）能伪红无隔离复刻（FAIL 指纹 = `no logs of level WARNING...`）、（b）对真实 MS-T13 及同源 3 条用例无害（全 PASS）⇒ **hermetic 成立**；
  2. HEAD-400 裸 socket 路径：`_send_error` 强写 body 变异被 MS-T11b **精确抓红于 400 分支**（同时实证 SRV-T33 的 http.client 断言确为盲区）⇒ **r1-F3 缺口经变异证明已关闭**；
  3. 派生断言：`FetchError.__str__` 格式漂移下限速用例保持绿 ⇒ **lock-step 成立**。
- 2 条观察性备注（O1 结构脆弱点 / O2 扫描阴性记录）均不阻断。
- 工作区**零残留**（md5 逐字节一致 + git 三重核验）。
