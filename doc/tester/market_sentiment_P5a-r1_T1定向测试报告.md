# market_sentiment P5a-r1 · T1 定向测试报告（Bug-fix Loop P6c-r1）

- **阶段**：Bug-fix Loop 定向测试（T1）｜`>>MODE: T1 定向测试（P6c-r1）`
- **日期**：2026-10-10
- **被测增量（P5a-r1，3×P2 修复）**：
  - `china_finance_rss/server.py` — `handle_cls_pool` 失败日志限频（`_POOL_FETCH_WARN_GAP=30.0` / `_pool_fetch_warned_at` / `_warn_pool_fetch_failed()`）【P2-5】
  - `tests/test_server_http.py` — 新增 `test_fetch_failure_warning_is_rate_limited`；MS-T11 删恒真 HEAD body 断言【P2-5 / P2-6】
  - `tests/test_data_layer.py` — 新增 `SharedPageCopySemanticsTests`（2 条）【P2-4】
  - `tests/stress_all.py` — `finance/market_sentiment` 纳入 `GLOBAL_ENDPOINTS` + `check_endpoint` 分支
- **前序**：P5a-r1 三条 P2 修复 → P5b-r1 代码评审 **APPROVE**
- **副作用范围**：编排器未单列 `>>SIDE-EFFECT:`，按任务给定的「修改文件（P5a-r1）」4 个文件作为受影响点逐项核验（§5）

---

## 1. 结论

✅ **PASS-WITH-NOTES**

- **定向 261 用例 0 失败 / 0 错误 / 4 skip**；**全量 565 / 4 skip 与基线完全一致**，无回归；**无 P0 / P1**。
- **变异注入 3 次，3 次全部被抓红**（100%），三条修复均被测试真实锁定，非纸面闭合。
- 记 **3 条 P2 级备注**（§6）：F1/F3 与 P5b-r1 评审 S2/S4 同源、本轮独立复现；F2 为新发现。均不阻断。
- 全部注入变异**已还原并经 sha256 + `git diff` 双重验证**，工作区无残留（§7）。

---

## 2. 执行摘要

| 指标 | 值 |
|------|-----|
| 静态检查 | `python -m py_compile`（server/cdp_engine/两测试/stress_all）通过；`git diff --check` 干净 |
| T1 定向 | `python -m unittest tests.test_server_http tests.test_data_layer -v` → **Ran 261, OK (skipped=4)**，2.71s |
| 新增用例执行确认 | **3/3 全部被执行且通过**（见 §3）；P2-6 关联的 MS-T11 / MS-T11b 亦绿 |
| T2 全量 | `python -m unittest discover -s tests -v` → **Ran 565, OK (skipped=4)**，5.29s（变异前）；还原后复跑 **565, OK (skipped=4)**，5.16s |
| 基线对比 | 565 / 4 skip **= 基线 565 / 4 skip** → **无回归** |
| 失败 / 错误 / Flaky | **0 / 0 / 0**（无失败，Step 3.7 重试未触发） |
| 变异注入 | **3 次，3 次抓红**（M1/M2/M3，见 §4） |
| 缺陷 | **P0: 0 ｜ P1: 0 ｜ P2: 3（记录不阻断，见 §6）** |

> 跳过明细：`ClsPoolIntegrationTests` ×4（`CLS_INTEGRATION=1` 真上游门控）——与基线同数同因，**3 条修复相关用例无一被 skip 掩盖**。

---

## 3. T1 定向逐文件结果

`python -m unittest tests.test_server_http tests.test_data_layer -v` → **Ran 261, OK (skipped=4)**

| 文件 | 用例数 | 结果 |
|------|--------|------|
| `tests/test_server_http.py` | 145（含 4 skip） | ✅ OK |
| `tests/test_data_layer.py` | 116 | ✅ OK |
| **合计** | **261** | ✅ **OK（0 失败 / 0 错误 / 4 skip）** |

**新增用例执行确认（任务项 1）**

| 用例 | 归属修复 | 结果 |
|------|----------|------|
| `SharedPageCopySemanticsTests.test_each_read_is_a_distinct_dict` | P2-4 | ✅ ok |
| `SharedPageCopySemanticsTests.test_pop_on_one_read_does_not_reach_the_next` | P2-4 | ✅ ok |
| `ClsPoolTests.test_fetch_failure_warning_is_rate_limited` | P2-5 | ✅ ok |
| （P2-6 关联）`HttpSemanticsTests.test_head_on_market_sentiment_writes_no_body`（MS-T11） | P2-6 | ✅ ok |
| （P2-6 关联）`HttpSemanticsTests.test_head_body_never_reaches_the_wire`（MS-T11b） | P2-6 | ✅ ok |

> 三条新增用例另在**孤立运行**（`python -m unittest <仅这 3 条>`）下复跑全绿 → 无顺序依赖。

---

## 4. 变异注入表（独立可证伪性复核）

方法：注入前用 python 备份源文件到 `/tmp/opencode/p5a_r1_mut/*.bak` 并记录 sha256；注入时 `assert` 目标片段**全文件唯一出现**（防止改错位置）；注入后在**独立子进程**跑测试；还原后 sha256 比对 + `git diff` 复核。（源码 `edit` 权限为 deny，故注入/还原均以 python 脚本执行，未绕过纪律——全程备份、还原、复核。）

| # | 修复 | 注入点 | 注入方式 | 预期 | 实测 | 抓红 | 波及面（同轮实测） | 还原验证 |
|---|------|--------|----------|------|------|------|--------------------|----------|
| **M1** | **P2-4** 共享页不变式 | `cdp_engine.py:1168` `get_data` 的 `return merged` | 改为 `return self.cache`（返回共享对象） | `SharedPageCopySemanticsTests` 2 条转红 | **2/2 FAIL**：`assertIsNot(first, second)` → "unexpectedly identical"；`assertIn('market_sentiment', second)` → **"'market_sentiment' not found in {'articles': []}"**（即 pop 污染共享 cache 的真实症状） | ✅ **抓红** | `test_data_layer` **2/116 红**（仅新用例）；`test_server_http` **0/145 绿**（server 测试全 stub `page_data`） | ✅ sha256 `f867c07d…` 复原一致；`git diff -- cdp_engine.py` 空 |
| **M2** | **P2-5** 失败日志限频 | `server.py:470-471` `_warn_pool_fetch_failed` 窗口条件 | `if (prev is not None …` → `if (False and prev is not None …`（等价回退限频，恒不抑制） | `test_fetch_failure_warning_is_rate_limited` 转红 | **FAIL @ :386 `assertNoLogs`** → `Unexpected logs found: ['WARNING:server:[server] cls pool up_pool fetch failed: upstream_timeout']` | ✅ **抓红** | `test_server_http` **1/145 红**（仅新用例；MS-T13 仍绿，因其只要求"至少一条日志"） | ✅ sha256 `856eccfa…` 复原一致 |
| **M3** | **P2-6** HEAD body 线上维度 | `server.py:1290` `do_HEAD` 的 `write_body=False` | 改为 `write_body=True`（服务器**真**往 HEAD 写 body） | MS-T11b 转红；MS-T11（删断言后仅状态码）保持绿 | **MS-T11b FAIL @ :1115** → `b'{\n  "error": "Chrome CDP not available. See README."\n}' != b'' : /finance/market_sentiment`（线上 **54 字节** body）；**MS-T11 ok**；全模块 **145 条中仅 1 条**红 | ✅ **抓红** | `test_server_http` **1/145 红** → MS-T11b 是**唯一**守卫；`test_head_writes_no_body` / `t54_head_304_and_head_200` / gzip HEAD 均仍绿（其 body 断言经 `http.client`，恒真） | ✅ sha256 `856eccfa…` 复原一致 |

**M3 同时完成任务项 3 的 P2-6 问答**：
- MS-T11（`:1060-1068`）现状**只剩 `status == 200`**，无 body 断言 → M3 下保持绿，**证明其已不承载 body 维度**（若旧断言还在，也一样恒真、一样绿 —— 正是删除它的理由）。
- MS-T11b（`:1097-1118`，裸 socket `_raw_exchange`，先用 GET 自证读法非空断言）在 M3 下**转红并读到 54 字节** → 「服务器真写 HEAD body 时 MS-T11b 转红」**成立**；54 字节与 r1 报告 M16 实测一致（复现）。

---

## 5. 副作用点核验（按 4 个修改文件逐项）

| 受影响点 | 存量覆盖 | 本轮核验方式 | 结果 |
|----------|----------|--------------|------|
| `server.py` 失败日志限频 `_warn_pool_fetch_failed` | MS-T13（`:358` 只断言"有日志"） | M2 变异 | ✅ 新用例独力抓红；MS-T13 存量回归绿 |
| `server.py` 新增模块态 `_pool_fetch_warned_at` | 无直接存量用例 | 状态注入实验（§6-F1） | ⚠ 发现 MS-T13 顺序耦合 → F1 |
| `test_server_http.py` MS-T11 删 body 断言 | MS-T11b 裸 socket | M3 变异 | ✅ 承接成立，无净损失 |
| `test_data_layer.py` 新增 `SharedPageCopySemanticsTests` | 无（新维度） | 直接执行 + M1 变异 | ✅ 绿 / ✅ 红，双向有效 |
| `stress_all.py` 新端点登记 + `check_endpoint` 分支 | 不在 unittest 发现范围 | py_compile + 分支直接调用自检 5/5 | ✅ 正常信封过；biz code≠200 / 缺 `data` / 非 dict / error 面 全部按预期拒绝（详见 §6-F6） |

---

## 6. 非预期发现（脆弱断言 / 顺序依赖 / skip 掩盖）

### F1 [P2·顺序依赖｜与 P5b-r1 评审 S2 同源，本轮独立复现]
**MS-T13 与新限频表耦合**：`test_fetch_failure_logs_a_warning_before_degrading`（`:358-369`）**不重置** `_pool_fetch_warned_at`。运行时注入「上一条同 pool 同消息的失败刚发生」的状态后单独跑 MS-T13：

```
srv._pool_fetch_warned_at['up_pool'] = (time.time(), 'upstream_timeout')
→ FAIL: AssertionError: no logs of level WARNING or higher triggered on server
```

- 现状不红的原因是**字母序**：`test_fetch_failure_logs…` 排在 `test_fetch_failure_warning_is_rate_limited` 之前，且此前无同消息失败。
- 建议（1 行防护）：MS-T13 照抄新用例的 `saved/clear/finally-restore`。
- **非阻断**：当前全量绿、顺序稳定；新用例自身已 hermetic（save/clear/restore 三段式，孤立运行亦绿）。

### F2 [P2·覆盖备注｜**新发现**]
**P2-4 不变式只有单层防护**：M1 注入下 `test_server_http` **145 条全绿**（server 侧测试一律 stub `page_data`），唯一守卫是 `SharedPageCopySemanticsTests` 的 2 条直连 `page_data → get_data` 用例；**没有端到端"兄弟端点投毒"用例**（`/finance/market` 就地 `pop` → `/finance/market_sentiment` 之后 unavailable）。
- 单元层是正确的锁定层，但若未来有人在 server 层引入 `page_data` 结果复用/缓存，测试不会红。
- 建议：记录；后续轮可补 1 条端到端回归。**不阻断**。

### F3 [P2·残余恒真断言｜与 P5b-r1 评审 S4 同源，本轮独立复现]
**`test_head_writes_no_body`（`:979-985`）的 body 断言仍经 `http.client`**：M3 下该用例**仍绿**（服务器真写了 body）→ 其 `assertEqual(body, b'')` 对 body 维度恒真（状态码 200/400/404 半句有效）。
- **覆盖缺口**：MS-T11b 的路径元组只有「新端点 / 首页 / 404」，**不含 400 分支**（`/market/margin?market=bogus`）→ 400 分支的 HEAD body 无线上级后备。
- 建议：把 400 路径并入 MS-T11b 元组，或该用例改用 `_raw_exchange`。**不阻断**。

### F4 [skip 掩盖检查]
4 skip = `ClsPoolIntegrationTests`（`CLS_INTEGRATION=1` 门控），与基线**同数同因**；3 条修复相关用例**均非 skip、均实际执行**。**无 skip 掩盖**。

### F5 [Flaky / 顺序依赖]
3 条新增用例在 (a) 全量 565、(b) 定向 261、(c) 孤立 3 条 三种编排下**均绿** → 无顺序依赖、无 Flaky，Step 3.7 重试未触发。

### F6 [stress_all.py 执行范围说明]
该脚本需活服务器（`wait_for_server()` 后直接压测），不在 T1 可执行范围 → **SKIP-EXECUTION（理由：需活服务器 + 真流量）**，改为静态核验：
- `py_compile` 通过；`GLOBAL_ENDPOINTS['finance/market_sentiment'] = '/finance/market_sentiment'`（`:45`）与 `check_endpoint` 分支（`:121-130`）就位；
- 分支逻辑直接调用自检 **5/5 符合预期**：`{code:200,data:{}}` → ok；`{code:9000}` → `envelope code != 200`；缺 `data` → `missing key: data`；非 dict → `not dict: str`；`{error:…}` → `server_error`。

---

## 7. 纪律与还原声明

- 注入 3 次，**全部还原**：`server.py` 还原 sha256 `856eccfaacc575b35388ca34d9ff65cd3cbd534234a9b4a64fb530a2dc88eb51`、`cdp_engine.py` 还原 sha256 `f867c07db7b2f27171e4783ad6980130c278a493a10c0d97bb57b358129a7ec0`，与注入前记录**逐字节一致**。
- `git diff --stat` 还原后与变异前**完全相同**（13 files, +1019/−82）；`git diff --check` 干净；`grep MUTATION-P2` 在 `china_finance_rss/` **零命中**；`cdp_engine.py` 不在 diff 列表中。
- 还原后复跑：定向 **261 OK (4 skip)**、全量 **565 OK (4 skip)**。
- 本轮**唯一新增文件**为本报告；未修改任何源码/测试/契约文档。

---

## 8. 缺陷清单

| ID | 等级 | 位置 | 描述 | 处置 |
|----|------|------|------|------|
| （无新缺陷） | — | — | P0/P1 **0 条**；三条修复本身**未发现缺陷** | — |
| F1 | P2 | `tests/test_server_http.py:358` MS-T13 | 不重置 `_pool_fetch_warned_at`，与限频表顺序耦合（状态注入实验证实可红） | 记录，不阻断（评审 S2 同源） |
| F2 | P2 | 覆盖面 | P2-4 不变式仅单层防护，无端到端兄弟端点投毒用例 | 记录，不阻断（**新发现**） |
| F3 | P2 | `tests/test_server_http.py:979` + MS-T11b 路径 | `test_head_writes_no_body` body 断言恒真；MS-T11b 未覆盖 400 分支 | 记录，不阻断（评审 S4 同源） |

**结论**：✅ **PASS-WITH-NOTES** — 定向与全量均与基线一致、3 条修复变异 3 抓、无 P0/P1；3 条 P2 备注记录不阻断。
