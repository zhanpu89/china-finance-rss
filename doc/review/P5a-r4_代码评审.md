# 代码评审 — P5b-r3（P5a-r3 复查 P2 收尾轮 r4）

> **编号** CR-P5AR4-20261013-001 · **模式** P5b 常规评审 + P7a 漂移合并 · **日期** 2026-10-13
> **评审对象**：收尾轮 r4 改动（`git diff --stat`：`china_finance_rss/server.py` +39 · `tests/test_server_http.py` +155）。`opencode.json` +9 为用户 model 配置，**非本流水线，未评**。
> **需求来源**：`doc/review/P5a-r3复查_对抗性盲审报告.md` §二 P2-1（形状告警限频）/ P2-2（304 恒真断言）；P2-3/P2-4 本轮用户裁定**仅允许注释澄清、禁止改运行时行为**。
> **>>SIDE-EFFECT 推断**（入参未携带，从 diff 摘要推断，供 tester `>>SCOPE:`）：SE-a 形状分支 `log.warning` 直写 → `_warn_pool_fetch_failed`（server，日志语义）；SE-b 形状路径开始写 `_pool_fetch_warned_at`（server，`test_empty_list…` 因此加隔离）；SE-c 删除 3 处 304 `body==b''` 恒真断言、新增裸 socket 304 用例（tests，覆盖转移）；SE-d `server.py:466-472`/`:1613-1626` 注释改写（server，声明收窄）。

## 〇、总评（一句话）

P2-1 实现真限频且保住了「消息变化即时再告警」，P2-2 新用例 hermetic 且可证伪（自行推演双路红/绿），P2-3/P2-4 对照 r3 基线逐行核实**确为纯注释**；**无 P0/P1**，3 条 P2（残留恒真断言口径不一致等）与 10 项契约行号/登记漂移记录不阻断。

## 一、逐条评审

### P2-1 形状漂移告警纳入限频（server.py:525-543）

| 检查项 | 结论 | 证据 |
| --- | --- | --- |
| 真限频 | ✅ | `:541-542` 改调 `_warn_pool_fetch_failed`；该函数 `:487-491` 读 `_pool_fetch_warned_at`，同 pool 同消息 & `now-prev < 30s` ⇒ 静默。形状判定对每请求重跑（plate TTL 只限回源），限频后日志量与 RPS 解耦 |
| 消息变化即时再告警 | ✅ | 消息含 `type(data).__name__`（`dict`/`NoneType`/…）⇒ 换形状即换消息 ⇒ `:489` 判不等 ⇒ 立即告警。新用例 `test_shape_drift_warning_is_rate_limited` ③段（`:570-576`）钉住 |
| 无行为回归 | ✅ | 返回体逐字不变：`{'error': f'upstream data shape unexpected: {shape}'}`（`:543`，与原 `:527` 同）；状态码路径不经此处（`_send_json_shape` 恒 200）。日志格式变为 `cls pool %s fetch failed: unexpected upstream data shape %s`——全仓无 scraper/测试匹配旧形状消息格式（grep 仅命中契约伪代码），MS-T13 匹配的 except 路径格式逐字未动 |
| 不结束 episode | ✅ | 形状分支 `:543` return 早于成功路径 pop（`:549`），形状失败**不** pop——与 P2-3 裁定的「episode 仅全成功结束」一致 |
| 交替失效模式的量 bound | ✅（观察，非缺陷） | 推演：transport-fail 与 shape-fail 交替时每次切换都是新消息、都会告警——但 shape 响应被 plate TTL(12s) 缓存（同体重放 ⇒ 同消息 ⇒ 窗口内静默），transport 失败受 NEG_TTL(5s) 约束 ⇒ 实际上界 ≈ 1/12s/池，与 r3 盲审 SE-6 已接受的「per-episode 上界」同量级，**非 RPS 线性** |
| docstring | ✅ | `:481-484` 补第二调用方说明，`str(exc)` 耦合点写明（形参名仍叫 `exc` 而形状路径传 str——`str(str)` 恒等，行为正确，命名瑕疵记观察不立条） |

### P2-2 304 无体保证改为裸 socket 可证伪（tests/test_server_http.py）

| 检查项 | 结论 | 证据 |
| --- | --- | --- |
| 新用例真 hermetic | ✅ | `test_304_body_never_reaches_the_wire`（`:1920-1947`）：类级 server fixture + `_patch_handler` 上下文内完成两次交换（`setUp` 每测清 feed_cache）；裸 socket 逐次关闭；无线程/顺序污染 |
| 可证伪（自行推演） | ✅ | 若 `_send_not_modified` 加一次 `wfile.write`（不动头部）⇒ 线上 304 带体 ⇒ 裸读法 read-until-EOF 读到非空 ⇒ `:1946` `assertEqual(body, b'')` **红**；若改发 `Content-Length` ⇒ `:1947` `assertIsNone(re.search(content-length))` **红**。反向：实现正确时首个裸 GET 自证读法非恒真（`:1933-1934` 断 200 + 非空体）⇒ 用例自身不是空断言。恒真陷阱已注释钉在 helper docstring（`:1834-1838`） |
| ETag 取法正确 | ✅ | `:1935-1944` 注释明确：裸 reader 发 `Host: 127.0.0.1`（无端口）、`http.client` 发带端口 Host ⇒ base_url/atom:link 不同 ⇒ ETag 不同 ⇒ **从裸响应取 validator**再重放，避免「合法 200 冒充 304 测不到」的假绿。该细节是本用例正确性的关键，已写对 |
| 删除的恒真断言确由新用例承担 | ✅ | 删除 3 处（旧 `:1922/:1989/:2029` → 现 t52 `:2028-2030` / t52b_end `:2097-2098` / t54 `:2137-2139` 原地注释指向 `test_304_body_never_reaches_the_wire`）。304 写体出口全仓唯一 = `_send_not_modified`（`:1630-1661`，`:1661` 注释「no wfile write」；调用点仅 `_serve_feed` 一处）⇒ 新用例钉住唯一出口即钉住全部 304 形态 |
| 循环改造损失覆盖 | ✅ | `test_empty_list_is_success_but_non_list_data_fails_loud`（`:523-546`）因 P2-1 形状路径开始写限频表而加 save/clear/finally 隔离——这是**正确**的 hermetic 适配而非删减：`data: []` 成功分支、dict/None 双形状 assertLogs 分支全保留；None 形状消息不同 ⇒ 仍即时告警，红/绿方向不变 |
| 新增 `test_shape_drift_warning_is_rate_limited` | ✅ | `:548-584`：四段断言（首告警含 shape 名 / 同形状窗口内 `assertNoLogs` / 换形状再告警 / error 体逐字一致）。可证伪：形状分支改回直写 `log.warning` ⇒ repeat 段 `assertNoLogs` **红**。`assertNoLogs` 需 Py3.10+，项目 3.12 ✓ |

### P2-3 / P2-4 注释澄清是否纯注释（对照 r3 基线逐行核实）

- **P2-3（`server.py:466-472`）**：✅ 纯注释。新增 7 行注释显式声明「episode 仅由全成功 return 结束（有意取舍）」+ 把 `:452-453` 的无条件「per GAP」措辞在 `:471-472` 收窄为「per-episode, not an unconditional per-GAP ceiling」。运行时逐点比对 r3 基线：`code != 200`（`:530`）与形状分支（`:533-543`）仍在 pop（`:549`）之前 return、不 pop——**与 r3 行为逐字一致**，未动任何可执行语句。
- **P2-4（`server.py:1613-1626`）**：✅ 纯注释。r3 盲审指认的 overclaim（旧 `:1597-1603`「no-body rule lives HERE」）改写为「Deliberately NOT a service-wide invariant」+ 列明另两条出口（CPython `send_error` 自带守卫；`_reject_503` `:1763-1770` 在读请求行之前、方法未知无守卫）。守卫行 `:1627` `if write_body and getattr(self, 'command', None) != 'HEAD':` 与 r3 基线（r3 `:1604`）**逐字相同**——本轮未触碰。`_reject_503` 本体（`:1763-1781`）亦未改。
- 结论：**未发现任何借注释澄清夹带的行为改动，P1 = 0 成立**。

### 常规质量面

- **安全**：无新输入面/反序列化/鉴权变化；形状名取自 `type(data).__name__`（受控于 Python 类型名，无注入面）；日志仍 `%s` 参数化。✅
- **性能**：形状失败路径每请求多一次 dict 查找 + `time.monotonic()`，可忽略；限频本身**降低**日志 I/O。✅
- **规范**：命名/分层/异常风格与既有 P2-5 实现一致（存量模式复用，未造第二套限频）；测试隔离遵循本文件既定 save/clear/finally 模板。✅
- **项目约定**：`AGENTS.md` 手术式修改——本次 diff 未越出 P2-1/P2-2/P2-3/P2-4 范围。✅

## 二、问题清单

【P2】`tests/test_server_http.py:1910/:1956/:1971/:2003/:2008/:2287/:2452:` 同型 304 `body == b''` 恒真断言残留 7 处，本轮删 3 留 7、口径不一致——维护者无法分辨哪些断言是承重的。

- **证据链**：这 7 处均经 `http.client` 读 304 体（CPython 对 NOT_MODIFIED 归零读长 ⇒ 恒 `b''`）。**当**未来有人逐点审这些断言以为它们有区分度 ⇒ 误判覆盖状态。缓解事实：304 写体出口全仓唯一（`_send_not_modified`），新裸 socket 用例（`:1920`）已钉住该出口 ⇒ **覆盖真空已闭合**，残留断言只是不可证伪噪音；且 t47/t67 另有头部断言部分兜底。
- **影响**：可维护性；无功能/安全影响。
- **修复方向**：与被删 3 处同法——逐处加一行注释「恒真，由 `test_304_body_never_reaches_the_wire` 承担」，或删除。不阻断。

【P2】`tests/test_server_http.py:548:` 新增 `test_shape_drift_warning_is_rate_limited` 未登记进 `cls_pools.md` §8 用例表（POOL-T 系列断档）。

- **证据链**：本文件既定口径是「新增用例即登记契约 §8」（POOL-T15/T16/T17 先例）；**当**后续按契约回归时，该用例不在清单内 ⇒ 漏跑风险。
- **影响**：契约-测试追溯缺口；用例本身 hermetic 且可证伪（见 §一），质量无虞。
- **修复方向**：派 task-decomposer 在 `cls_pools.md` §8 补 POOL-T18 行（含可证伪说明：形状分支改回直写 ⇒ `assertNoLogs` 段红）。已列入下方 drift 清单。

【P2】`china_finance_rss/server.py:477:` `_warn_pool_fetch_failed(pool_type, exc)` 形参名 `exc`，形状路径（`:541`）实际传入 plain str——签名语义与实参类型轻微错位。

- **证据链**：`str(exc)` 对 str 恒等（`:486`）⇒ 行为零影响；docstring（`:481-484`）已写明双调用方约定。**当**读者按形参名推断「只接受异常」⇒ 轻微误导。
- **影响**：可读性；无行为影响。
- **修复方向**：改名 `detail`（或重载为 `Union[Exception, str]` 注释），或维持现状。 Cosmetic，不阻断。

## 三、契约 drift 清单（行号级，供编排层派 task-decomposer，勿原地改文档）

| # | 文件:行号 | 漂移内容 | 代码事实（现值） |
| --- | --- | --- | --- |
| D1 | `doc/detailed/cls_pools.md:319-320` | §5 伪代码形状分支仍直写 `log.warning('[server] cls pool %s: unexpected upstream data shape %s', …)` | `server.py:541-542` 已改调 `_warn_pool_fetch_failed(pool_type, f'unexpected upstream data shape {shape}')`；消息格式亦变为 `cls pool %s fetch failed: …`（P2-1） |
| D2 | `doc/detailed/cls_pools.md:415` | §7.1 行号引用 stale：`server.py:466-483` / `:533`；且未提形状路径是限频器第二调用方 | 限频函数现 `:477-493`、pop 现 `:549`；双调用方见 `server.py:481-484` |
| D3 | `doc/detailed/cls_pools.md:446-447` | POOL-T16/T17 行号 stale：`tests/test_server_http.py:429` / `:468` | 实际 `:430` / `:469` |
| D4 | `doc/detailed/cls_pools.md:515` | 下游提示引用 `server.py:482-535` stale | `handle_cls_pool` 现 `:496-550` |
| D5 | `doc/detailed/cls_pools.md` §8 | 新用例 `test_shape_drift_warning_is_rate_limited`（`tests/test_server_http.py:548`）未登记 | 建议补 POOL-T18（同问题清单 P2-2） |
| D6 | `doc/detailed/market_sentiment_独立接口.md:272/:281/:295/:299` | §5.5 行号 stale：`:513-514` / `:466-483` / `:533` / `:520-521`；§5.5 伪代码未反映形状路径走限频器 | 实际 `:523` / `:477-493` / `:549` / `:530-531`；形状路径 `server.py:541-542` |
| D7 | `doc/detailed/market_sentiment_独立接口.md` §8（`:380-382`） | MS-T18/T19/T20 行号 stale：`:429` / `:468` / `:1234`；两条新用例（`:548` 形状限频、`:1920` 304 裸 socket）未登记 | 实际 `:430` / `:469` / `:1280`（`test_head_guard_is_intrinsic_to_send_text` 因前置 +46 行下移） |
| D8 | `doc/detailed/server.md:1714-1718`（§5.8 伪代码注释） | 仍载 r3 overclaim「the no-body rule for HEAD **lives HERE**…」；r4 已在代码侧收窄（P2-4） | `server.py:1613-1626` 现为「Deliberately NOT a service-wide invariant」+ 另两出口（`send_error` 自带守卫 / `_reject_503` 读方法前无守卫） |
| D9 | `doc/detailed/server.md:1986`（SRV-T33） | MS-T20 行号 stale：`tests/test_server_http.py:1234` | 实际 `:1280` |
| D10 | `doc/detailed/server.md` §8 / 头部 | 新用例 `test_304_body_never_reaches_the_wire`（`tests/test_server_http.py:1920`）未登记（可挂 SRV-T47 增补行或新编号）；版本头仍 v1.21、「测试计数 76」未随 +2 用例刷新 | 现文件 2697 行、新增 2 用例 |

**drift 项数 = 10**（D1/D6/D8 为语义级——伪代码或声明与代码行为不符；其余为行号 stale + 登记缺失）。均为文档侧待同步，代码侧无越权改动。

## 四、评审结论

| 项 | 结论 |
| --- | --- |
| **评审结论** | ✅ **通过（APPROVE）** — P2-1 真限频（同形状窗口静默、换形状即时告警、返回体/状态码/episode 语义零回归，交替失效模式量 bound ≈ 1/12s/池非 RPS 线性）；P2-2 新裸 socket 用例 hermetic 且双路可证伪（写体 ⇒ 红、发 CL ⇒ 红），删 3 处恒真断言确由唯一 304 出口覆盖承担，循环改造为正确 hermetic 适配未损覆盖；P2-3/P2-4 对照 r3 基线逐行核实**确为纯注释**（守卫行 `:1627` 与 r3 `:1604` 逐字同、pop 位置未动、`_reject_503` 未触碰）。安全/性能/规范无新缺陷。**P0=0 / P1=0**；3 条 P2（残留恒真断言口径、新用例契约登记、形参命名）记录不阻断；契约 drift 10 项交编排层派单同步 |
| 问题统计 | **P0 = 0 · P1 = 0 · P2 = 3** |
| drift 项数 | **10**（语义级 3 + 行号/登记级 7） |
| 最严重项 | 无 P0/P1；最重为契约 drift D1/D6/D8（`cls_pools.md:319` 伪代码仍写形状分支直写 `log.warning`、`server.md:1714` 仍载已被 r4 收窄的 HEAD overclaim——照旧契约施工会把 P2-1/P2-4 的修正「修回去」） |
| 范围声明 | `opencode.json` 改动（用户 model 配置）已按编排器指令排除，未评审 |

>>DECISION: APPROVE
