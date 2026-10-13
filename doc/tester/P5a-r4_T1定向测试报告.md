# P6c-r4 · T1 定向测试报告（P5a-r4 收尾轮）

> **编号** T1-P5AR4-20261013-001 · **执行** 2026-10-13 · **角色** tester 阶段二（T1 定向 + 独立验证，只验证不新增实现）
> **被测改动**：`china_finance_rss/server.py` +39（P2-1 形状漂移告警纳入 `_warn_pool_fetch_failed` 限频；P2-3/P2-4 注释澄清）；`tests/test_server_http.py` +155（P2-1/P2-2 新用例、删 3 处恒真 `body==b''`、`test_empty_list…` 隔离化）。
> **需求来源**：`doc/review/P5a-r4_代码评审.md`（APPROVE，自报 570 OK skip=4、变异 4/4、P0/P1=0、P2=3）。
> **实验规约**：区分性变异一律在临时副本上做，实验后从备份整体还原；`git diff --stat` 实验前后完全一致（`server.py 39 / tests 155 / opencode.json 9`），无残留 MUTATION 标记。

## 一、测试执行结果

| 轮次 | 命令 | Ran | OK | skip | 结果 |
| --- | --- | --- | --- | --- | --- |
| Run-1（基线） | `python -m unittest discover -s tests -v` | 570 | 570 | 4 | ✅ OK（5.236s） |
| Run-2（基线复跑） | 同上 | 570 | 570 | 4 | ✅ OK（5.164s） |
| Run-3（M1 还原后） | 同上 | 570 | 570 | 4 | ✅ OK（5.229s） |
| Run-4（M2 还原后·收尾） | 同上 | 570 | 570 | 4 | ✅ OK（5.149s） |

- **2 次一致性：4/4 次结果指纹完全一致（570 / OK / skip=4）**，skip 均为 `ClsPoolIntegrationTests` 的 4 条 `CLS_INTEGRATION=1` 真上游冒烟（预期跳过），无 flaky、无重跑。
- 与 P5a-r4 自报（570 OK skip=4）**一致**。
- 辅助门禁：`python -m py_compile china_finance_rss/server.py tests/test_server_http.py` 通过；`git diff --check` 无输出。

## 二、逐条独立验证

### V1 · P2-1 `test_shape_drift_warning_is_rate_limited`（真 hermetic + 可证伪）

| 段 | 实验 | 结果 |
| --- | --- | --- |
| 正证 | 单跑该用例 | ✅ Ran 1, OK |
| 正证（顺序面） | `ClsPoolTests` 全类 18 条：字母序 / **逆序** / **随机洗牌**（seed=20261013）各跑一遍 | ✅ 18 OK × 3，无顺序耦合 |
| hermetic | 预先污染 `_pool_fetch_warned_at = {'up_pool':(-100s,'stale-seed'), 'down_pool':(-5s,'other-seed')}`，再跑该用例 + `test_empty_list…` | ✅ 2 OK；**跑后状态与污染前逐键相等**（save/clear/finally 真还原） |
| 区分性实验 M1 | 把形状分支改回 HEAD 原文直写 `log.warning('[server] cls pool %s: unexpected upstream data shape %s', pool_type, shape)`（不动其它任何行） | ❌ **必红**：`AssertionError: Unexpected logs found: ['WARNING:server:[server] cls pool up_pool: unexpected upstream data shape dict']`（`:568 assertNoLogs` 段） |
| 变异必红（稳定性） | M1 下连续 2 个独立进程各跑一次 | ❌ 红 2/2（非 flaky） |
| 变异全量面 | M1 下跑全量 | ❌ `Ran 570 … FAILED (failures=1, skipped=4)` — **仅目标用例红，零连带** |
| 还原复绿 | 从备份还原 → 单跑 + 全量 | ✅ 目标用例 OK；Run-3 全量 570 OK；diff 统计与实验前一致 |

**两维语义独立复现（不依赖该用例，自建 harness 直驱 `handle_cls_pool` + logging handler）：**

- ① **同 shape 30s 窗口静默**：`dict` 形状连打 3 次 → 告警计数 **1 / 0 / 0**，首条消息 `[server] cls pool up_pool fetch failed: unexpected upstream data shape dict`。
- ② **换 shape 名即时再告警**：`dict → NoneType` → 新告警 **1** 条（含 `NoneType`），随后同形状再打 **0** 条。
- 契约不因限频改变：同 shape 两次 error 体逐字相同 `{'error': 'upstream data shape unexpected: dict'}`，换形状后 error 体照常携带新 shape 名。

### V2 · P2-2 `test_304_body_never_reaches_the_wire`（真 hermetic + 可证伪）

| 段 | 实验 | 结果 |
| --- | --- | --- |
| 正证 | 单跑 / `RssConditionalGetTests` 类内 / 两次全量 | ✅ 全绿 |
| hermetic | 仅 loopback `127.0.0.1` 临时端口，每次交换独立 socket 并在 `finally` 关闭；两次交换都在 `_patch_handler` 上下文内；不写任何模块级全局（feed cache 由 `setUp` 每测清） | ✅ 无外部依赖、无跨用例状态 |
| 用例自身非空断言 | 首个裸 GET 自证读法能读到 body（`assertTrue(raw_body)` + 200），再取**裸响应**的 ETag 重放 | ✅ 该自证在基线与 M2 下都通过 ⇒ 用例不是"永远绿"的空断言 |
| 区分性实验 M2 | 给 `_send_not_modified` 在 `end_headers()` 之后注入 `self.wfile.write(b'X')`（**头部一字未动**） | ❌ **必红**：`AssertionError: b'X' != b''`（`:1946`） |
| 变异必红（稳定性） | M2 下连续 2 个独立进程各跑一次 | ❌ 红 2/2（非 flaky） |
| 变异全量面（覆盖归属证明） | M2 下跑全量 | ❌ `Ran 570 … FAILED (failures=1, skipped=4)` — **仅目标用例红**；被删 3 处断言所在的 `t52 / t52b / t54` **全部仍绿**，其余残留 `body==b''` 用例（t47/t48/t49/t51/t57/t63/t67）**也全部仍绿** ⇒ 反证它们恒真、**覆盖确由新裸 socket 用例承担** |
| 还原复绿 | 从备份还原 → 目标用例 + 304 相关 8 条 | ✅ OK；Run-4 全量 570 OK；`MUTATION` 标记 0 |

## 三、覆盖 / 回归结论

1. **删 3 处恒真断言无覆盖损失**：M2 全量面显示这 3 处（`t52:2027` / `t52b` / `t54`）在"线上真写体"时依然绿 ⇒ 删掉它们不丢任何区分度；同时它们保留的状态码/头部断言（`st == 304`、`etag`/`cache-control`/`vary`）仍全绿，基线与变异下均通过。**"304 无体"这一不变量现由唯一裸 socket 用例承担，且在唯一 304 出口 `_send_not_modified` 上被证伪过一次。**
2. **两次变异全量面各只有 1 红（各自目标用例）** ⇒ P2-1/P2-2 的改动既无"改A红B"的连带，也不存在靠隐性顺序/共享状态凑绿的用例。
3. **`test_empty_list…` 隔离化后无顺序残留**：`ClsPoolTests` 字母序 / 逆序 / 随机洗牌三种顺序各 18/18 绿；该用例单跑绿；预置污染态下跑完状态被完整还原（见 V1 hermetic 行）。类内字母序（`test_empty_list…` 紧随 `test_cache_age…`、`test_enum_gate…` 之前）不再构成隐性前置。
4. **无 flaky**：所有基线轮 0 失败；两次变异各复跑 2 次，红向稳定 2/2（Step 3.7 无需重试判定）。

## 四、越界检查（P2-3 / P2-4 是否纯注释）

方法：把 `git show HEAD:china_finance_rss/server.py` 与现工作区版本做 **tokenize 级 diff（剔除 COMMENT / NL / 缩进 / 空白）**，只看"可执行 token"差异。

- diff **仅剩 2 处**：
  1. 形状分支 `log.warning(...)` → `_warn_pool_fetch_failed(pool_type, f'unexpected upstream data shape {shape}')` —— 即本轮**获批的 P2-1** 行为改动；
  2. `_warn_pool_fetch_failed` 的 **docstring 字符串**（P2-1 双调用方说明）——docstring 非执行逻辑，全文件 `__doc__` 引用数 = 0。
- **P2-3（`:466-472`）与 P2-4（`:1610-1626`）两个 hunk 在剔除注释后完全消失** ⇒ 确为纯注释；守卫行 `:1627 if write_body and getattr(self, 'command', None) != 'HEAD':`、成功路径 pop `:549`、`code != 200`/`非 list` 的提前 return 位置与 HEAD 逐 token 相同。
- 结论：**未发现借注释夹带的行为改动，P1 = 0 成立**（与评审报告结论互证，且为独立方法得出）。

## 五、非预期发现

- **【P2·已知项独立复现】** 恒真 304 断言清理不彻底：r4 删 3 处，`tests/test_server_http.py` 仍余 **7 处** 304 `assertEqual(b*, b'')`（`:1910` t47、`:1956` t48、`:1971` t49、`:2003`/`:2008` t51、`:2247` t57、`:2350` t63、`:2452` t67）——M2 注入真实写体后**这 7 处全部仍绿**，实证恒真。无覆盖损失（不变量由新裸 socket 用例承担），但"删 3 留 7"口径不一致，后续读者易误判其有区分度。评审报告已记为 P2，本轮以区分性实验独立确认（评审所列行号 `:2287` 与实际 `:2350` 有偏差，以本报告为准）。
- **【范围外·不计缺陷】** 工作区 `opencode.json` +9（各 subagent 的 `model` 路由）不在本轮被测改动清单内；评审报告已声明排除，与业务/测试无关。
- 其余：未发现新缺陷；未发现测试作弊（无 `try/except pass`、无恒真兜底掩盖失败——两次变异均真实转红即为证）。

## 六、结论表

| 项 | 结论 |
| --- | --- |
| 全量执行 | ✅ **Ran 570 · OK 570 · skipped 4**，连续 4 次结果完全一致（含 2 次基线一致性复跑） |
| P2-1（形状告警限频） | ✅ PASS — 正证绿 + M1 变异必红（2/2，全量仅 1 红）+ 还原复绿；两维语义（同 shape 窗口静默 1/0/0、换 shape 即时再告警）经独立 harness 复现 |
| P2-2（304 无体可证伪） | ✅ PASS — 正证绿 + M2 变异必红（2/2，全量仅 1 红）+ 还原复绿；删 3 处断言经实证无覆盖损失、覆盖确由新用例承担 |
| 回归面 / 顺序耦合 | ✅ PASS — 三种顺序 18/18 绿、单跑绿、污染态下状态完整还原 |
| 越界（P2-3/P2-4 纯注释） | ✅ PASS — token 级 diff 仅剩 P2-1 行为改动与 docstring，无夹带行为改动 |
| **评审结论** | ✅ **PASS**（可进入下一轮 / 收口） |
| **P0 / P1 / P2 计数** | **P0 = 0 · P1 = 0 · P2 = 1**（残留 7 处恒真 304 断言，口径不一致，不阻断） |

> 实验还原声明：全部变异均已从备份还原，`git diff --stat` 与实验前一致（`server.py 39 / tests 155 / opencode.json 9`，173 insertions / 30 deletions），`MUTATION` 标记残留 0，最终全量 570 OK（Run-4）。
