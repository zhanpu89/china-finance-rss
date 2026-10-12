# 对抗性盲审报告 — P5a-r1 复查（market_sentiment P2-4/5/6 修复轮）

> **编号** BLIND-REV-20261010-002（P5a-r1 复查）· **模式** P8 对抗性盲审（`>>MODE: blind`）· **日期** 2026-10-10
> **入参范围（零上下文）**：触发报告路径 `doc/review/market_sentiment_对抗性盲审报告.md`（仅取其 P2-4/P2-5/P2-6 作为需求原文）；改动文件 `china_finance_rss/server.py`、`tests/test_data_layer.py`、`tests/test_server_http.py`、`tests/stress_all.py`；`>>DIFF` 客观摘要；契约文档**只读核对**（`doc/detailed/market_sentiment_独立接口.md` v1.0.2、`doc/detailed/cls_pools.md` v1.0.2、`cdp_engine.md` 相关节）。变更面：`handle_cls_pool` 失败日志限频化 + 2 条共享页不变式用例 + 1 条限频用例 + MS-T11 恒真断言删除 + stress_all 纳入新端点。
> **纪律声明**：未打开任何其它评审/测试报告正文；修复的设计理由不在入参内，以下全部结论出自源码、测试与契约文档实读。
> **审查基线**：假设本轮修复一定引入了新问题——重点逆向"修复本身的副作用"。

## 〇、修复副作用逆向检查（>>SIDE-EFFECT 推断，按模块标注供 tester 定向回归）

入参无 `>>SIDE-EFFECT:` 标记，从 diff 推断受影响点：

| 受影响点 | 模块 | 行为变化 | 逆向假设（破坏哪个既有调用方） |
|---|---|---|---|
| `_pool_fetch_warned_at` 模块级新状态 | server | `handle_cls_pool` 失败路径日志由逐次改为限频 | 既有断言"必有日志"的用例（MS-T13）在同进程二次执行/乱序执行时被静默抑制 → **成立（P1-1）** |
| `_warn_pool_fetch_failed` 新函数 | server | except 分支先限频告警再返回 | 返回体/异常捕获语义不变（实核 :503-505 与改动前逐字同构）→ 不成立 |
| MS-T11 删除 `body==b''` | tests | HEAD market_sentiment 只剩 status 断言 | body 维度移交 MS-T11b → 200 分支成立移交；**400 分支未纳入 MS-T11b，且同类恒真断言仍在 SRV-T33 → 成立（P2-1）** |
| stress_all 新端点分支 | tests（工具） | `/finance/market_sentiment` 断言 envelope `code/data` | degrade 体先被通用 `'error' in data` 拦截 → 不成立；断言形状与 handler 透传语义一致 → 不成立 |
| `_page()` 用 `CDPPage.__new__` 注入 | tests | 绕过 `__init__` 构造 | 属性集合与 `get_data()` 实际触点一一比对（`_lock/_last_data/_last_data_ts/_last_data_max_age/cache`）→ 齐备，不成立 |

## 一、对抗性假设 → 实核结论（B2，按审查方向逐项）

| # | 预设"必有问题"的假设 | 实核证据 | 结论 |
|---|---|---|---|
| H1 | 限频表引发线程竞态/脏读 | dict `get`/`__setitem__` GIL 原子；值为不可变 tuple 无撕裂；竞态最坏=窗口内多/少一条日志，已由 `server.py:454-456` 注释与 `cls_pools.md:415` 契约显式容忍（同 `metrics._warned` 风格） | 证伪（已登记的容忍竞态） |
| H2 | 表无界增长 | `_warn_pool_fetch_failed` 仅在 `handle_cls_pool:488` 枚举闸**之后**可达 ⇒ 键恒 ∈ `_POOL_TYPES`，≤4 键（`server.py:456` 注释属实） | 证伪 |
| H3 | 错误消息含变量导致去重失效（回到 RPS 级日志） | 三条消息源逐一实核：① FetchError 消息 = `kind[: url]`，pool URL 的 `sign` 由固定参数 `{app,os,sv,type,way,rever}` 派生、**无时间戳**（`utils.py:80-87`，`test_sign_...:315` 锁稳定性）⇒ 同故障同消息；② 负缓存重抛同 URL 同 kind（`cache.py:820`）；③ 200+变体垃圾体路径：坏体被 URL 缓存按 plate TTL 兜住（盘中 12s/非盘 120s），TTL 内重复解码失败消息恒同 ⇒ 最坏 1 条/TTL/池，非 RPS 线性 | 证伪（残留弱点见 P2-3） |
| H4 | 限频实现吞异常/改变失败语义 | `_warn_pool_fetch_failed` 总函数：`str(exc)` 安全、格式串为字面量（`%s` 参数化，消息含 `%` 不炸）、dict/log 无异常路径；调用后 `return {'error': str(exc)}` 与改动前逐字一致（`server.py:503-505`） | 证伪 |
| H5 | 时钟选择错误 | `time.time()` 墙钟（`server.py:469`）：NTP 回拨 ⇒ 抑制窗口被拉长；前跳 ⇒ 提前再告警。后果仅日志量，无业务面；但与项目内同类限频（`stock_api._FAIL_LEDGER_PRUNE_INTERVAL` 亦墙钟）风格一致 | **部分成立（P2-4）** |
| H6 | 新限频用例不可证伪/hermetic | 三段式：首条告警→窗口内 `assertNoLogs`→回拨时间戳→再告警；删限频 ⇒ 第二段红；且自建 clear+finally 恢复（`:377-398`）hermetic。**但暴露姊妹用例 MS-T13 未做同等隔离** | **成立（P1-1，见问题清单）** |
| H7 | MS-T11 删除留下覆盖真空 | HEAD 200 分支：MS-T11b 裸 socket 先 GET 自证读法再断言（`:1097-1118`）——扎实。**HEAD 400 分支：SRV-T33 `test_head_writes_no_body:979-985` 的 `body==b''` 是与被删断言完全相同的 `http.client` 恒真模式，而 MS-T11b 循环只含 200/200/404、无 400 路径** | **成立（P2-1）** |
| H8 | stress_all 新分支断言与实际响应形状不一致 | 成功：handler 逐字透传 upstream envelope `{code,msg,data}`（`server.py:346-349`，MS-T2 契约）⇒ `code/data` 键检查一致；降级：`{'error':...}` 先被 `global_task`/`check_endpoint` 通用 error 分支拦截（`stress_all.py:72-74/173-175`），不会误入 envelope 分支 | 证伪 |
| H9 | 共享页不变式用例打桩不驱动真实路径 | `cdp_engine.page_data(page)` → 真实 `get_data()`（`cdp_engine.py:103-119/1150-1168`），无 stub；注入属性与 `get_data` 触点比对齐备；若 `get_data` 改返回共享 cache ⇒ `first.pop` 删 `page.cache` 键 ⇒ 第二次 `assertIn` 红 —— 真可证伪 | 证伪（P2-4 防护缺口已补且有效） |
| H10 | 契约文档与代码不一致 | v1.0.2 §5.5 伪代码（`:282-293`）与 `server.py:457-474` 逐行一致、行号属实、消息格式逐字不变；§7.1 并发登记（`cls_pools.md:411/415`）与实现一致。**但本轮 3 处新增测试资产在两份详设 §8 均无登记行，v1.0.2 changelog 亦未提及** | **部分成立（P2-2）** |

## 二、问题清单（每条：一行结论 + 证据链 + 影响 + 修复方向）

【P1】tests/test_server_http.py:358: 本轮新增的模块级限频态 `_pool_fetch_warned_at` 使姊妹用例 MS-T13 `test_fetch_failure_logs_a_warning_before_degrading` 退化为**顺序/时钟耦合的脆弱断言**——修复者在新用例里做了 clear+finally 恢复，却未回填到更脆弱的旧用例。
- **证据**：MS-T13（`:358-369`）以 `assertLogs` 断言**必有**告警，但不清 `_pool_fetch_warned_at`；该表是模块全局态（`server.py:458`）。触发链：同进程内 MS-T13 之前的任何一次 `(up_pool, 'upstream_timeout')` 失败调用（如 `python -m unittest` 显式指定 `test_fetch_or_decode_failure_degrades_without_raising` 先于 MS-T13 执行、套件同进程双载重跑、或未来任何字母序在 `test_fetch_failure_logs...` 之前的新增用例复用该失败桩）→ `_warn_pool_fetch_failed:470-472` 在 30s 窗口内静默 → MS-T13 的 `assertLogs` 抛 "no logs" → **伪红，且报错信息指向"日志缺失"、根因却是新限频态**。现行默认 `unittest discover` 字母序恰好 MS-T13 先行（`logs` < `warning` < `or_decode`），故当前全绿——属"靠排序运气成立"。
- **影响**：测试资产的潜在 flaky + 误导性失败信息；不涉生产代码（限频对生产是纯收益）。违反本轮自己确立的口径（新用例 docstring 自陈 "hermetic: independent of run order"，`:378`——同一修复面内两套隔离标准）。
- **修复**：MS-T13 复制新用例的隔离手法——进入前 `saved=dict(...); clear()`、`finally` 恢复；或改用未被污染的 `pool_type`（如 `down_pool`）执行。

【P2】tests/test_server_http.py:985: 恒真断言删除**未覆盖同类现场**——SRV-T33 `test_head_writes_no_body` 对 400 分支的 `body == b''` 仍是被删断言的同款 `http.client` 恒真模式，且替代者 MS-T11b 的裸 socket 循环不含 400 路径，HEAD-400 的线上无 body 保证**零可证伪覆盖**。
- **证据**：`:979-985` 对 `('/market/margin?market=bogus', 400)` 断言 `body==b''`——`http.client` 对 HEAD 归零读长（本轮 MS-T11 docstring `:1063-1065` 与 MS-T11b docstring `:1073-1075` 自己论证了该模式不可证伪）；MS-T11b 循环（`:1109-1111`）仅 `('/finance/market_sentiment',200)/('/',200)/('/nope',404)`。服务端代码本身正确（`_send_error:1429-1432` 透传 `write_body`）——纯覆盖缺口。
- **影响**：若未来有人把 `_send_error` 的 `write_body` 误写成 `True`（HEAD 400 会上线 54 字节级 body，恰是 MS-T11b docstring 记载过的事故形态），现有套件全绿、无人拦截。
- **修复**：MS-T11b 循环补 `('/market/margin?market=bogus', 400)`；SRV-T33 的 400 行 `body==b''` 删除或注明"由 MS-T11b 线上覆盖"。

【P2】doc/detailed/market_sentiment_独立接口.md:439: v1.0.2 契约同步**漏登本轮 3 处新增测试资产**——限频用例、共享页不变式用例、stress_all 端点纳入在两份详设 §8 用例表均无行，changelog 只字未提；MS-T13 行（`:371`）的"可证伪：删 log.warning ⇒ 断言红"在限频引入后已**不再无条件成立**（同键先有告警则红）。
- **证据**：`market_sentiment_独立接口.md` §8 表止于 MS-T16（`:359-374`），无 `test_fetch_failure_warning_is_rate_limited`、无 `SharedPageCopySemanticsTests`（落 `test_data_layer.py:1823-1867`）；`cls_pools.md` §8 POOL-T1..T14（`:427-440`）无对应行；v1.0.2 changelog（`:439`）仅覆盖 §5.5 限频伪代码与 MS-T11 删除。对照项目纪律：本轮 P2-4 的需求原文（触发报告）明确要求补不变式用例 + stress_all 纳入——**代码做了，契约没登**。
- **影响**：详设作为测试登记权威出现缺口；后人按 §8 清点用例会漏掉这 3 处；MS-T13 行的可证伪声明带条件而文档未标注。
- **修复**：§8 补 3 行（限频用例标注"清表隔离"；共享页用例标注落点 `test_data_layer.py`；MS-T13 行补注"受 `_pool_fetch_warned_at` 全局态影响，须清表执行"）；changelog 补记。

【P2】china_finance_rss/server.py:469: 限频窗口用墙钟 `time.time()`——NTP 回拨会把 30s 抑制窗拉长（回拨 5 分钟 ⇒ 同故障 5 分钟无日志），前跳则提前再告警；`time.monotonic()` 才是区间测量的正确时钟。
- **证据**：`server.py:469` `now = time.time()`；窗口判定 `now - prev[0] < _POOL_FETCH_WARN_GAP`（`:470-471`）。回拨 ⇒ 差值为负恒 `< 30` ⇒ 静默延长。后果仅日志信号面（不触业务/缓存语义），且与 `stock_api` 既有限频（墙钟）风格一致——降级理由。
- **影响**：时钟阶跃期间同故障告警缺失或重复，量级 = 回拨幅度；无功能/安全影响。
- **修复**：`time.monotonic()` 替换（表语义不变，测试 `:390` 回拨时间戳同步改 monotonic 基准）；若为风格一致性保留墙钟，在 `:454` 注释补"墙钟容忍 NTP 阶跃"声明。

【P2】china_finance_rss/server.py:470: 限频去重键 = `(pool_type, 完整消息)`，**同种故障的新一轮 episode 在 30s 内不可见**——上游闪断恢复后再次同 kind 失败，若距上次告警 <30s 则被当作"仍在持续"静默；契约文档（`market_sentiment_独立接口.md:273-275`）只声明"消息变化即时再告警"，未登记该盲区。
- **证据**：负缓存 5s 过期后重试失败（`cache.py:814-820`），新 exception 对象但 `str` 相同（同 kind 同 URL）⇒ `prev[1] == msg` 且窗口内 ⇒ 抑制。闪断-恢复-再失败循环可发生在秒级（NEG_TTL=5s ≪ GAP=30s）。备选方案（结合 `_clear_negative` 的成功回调重置表）未被采用也未论证。
- **影响**：仅可观测性（故障转折点少一条日志）；量级 30s/池上限。不阻断。
- **修复**：在 `:454` 注释与契约文档补一句"同 kind 同消息的新 episode 30s 内不重复告警（有意取舍）"；或 fetch 成功路径调 `cache` 侧回调清对应池键（改动面更大，非必要）。

【P2】tests/test_server_http.py:389: 限频用例"窗口过期"段**硬编码消息字面量** `'upstream_timeout'` 与桩的真实 `str(exc)` 人工对齐——若 `FetchError` 的 `str` 格式演化（如补 url 后缀），注入的 `prev[1]` 与真实消息失配 ⇒ 第三次调用走"消息变化即时再告警"分支而非"窗口过期"分支，**该段断言静默失去对 GAP 判定的捕获力**（用例仍绿、覆盖已空）。
- **证据**：`:389-390` 手写 `(time.time() - srv._POOL_FETCH_WARN_GAP - 1, 'upstream_timeout')`；真实消息来自 `FetchError('upstream_timeout')` 的 `__init__`（`cache.py:98-105`，无 url 时 `str==kind`）。两处独立硬编码，无编译期/断言期耦合。第一、二段不受影响（同一对象演化的消息自洽）。
- **影响**：未来格式漂移时"窗口过期必再告警"维度假绿；当前实现下用例有效。
- **修复**：注入消息改为 `str(FetchError('upstream_timeout'))` 派生，消除双处硬编码。

## 三、定级说明（为何 P0×0）

- **安全面（P0 值得）**：新代码只做日志限频与测试，无输入拼接/反序列化/鉴权面；日志消息经 `%s` 参数化（非格式串拼接），上游内容无法注入格式指令；限频表键经枚举闸，外部不可控键。无发现。
- **崩溃/数据丢失面**：`_warn_pool_fetch_failed` 总函数无异常路径（实核 H4）；`get_data` 每次新建 `merged` 的不变式由本轮新用例锁死（H9），共享页污染场景从"零覆盖"变"必红"。无发现。
- **功能缺陷面**：返回体与失败语义逐字不变（`:503-505`）；对外契约零变更（入参声明属实）；stress_all 断言与透传形状一致（H8）。唯一 P1 落在**测试资产自身**（MS-T13 顺序耦合），生产代码无功能缺陷——按"最坏后果"定级：伪红可误导排查但不放走生产 bug，故 P1 而非 P0。
- **P2-4 防护缺口复查结论**：触发报告的 P2-4（共享页不变式零覆盖）**已被有效修复**——新用例驱动真实 `page_data→get_data`、对"返回共享 dict"变异必红（H9），非打桩空转；stress_all 亦已纳入新端点。该项闭环。

## 四、评审结论

| 项 | 结论 |
| --- | --- |
| **评审结论** | ⚠️ 有条件通过（APPROVE，附条件）——3 条 P2 修复目标中 P2-5（限频）、P2-4（不变式用例+压测纳入）、P2-6（恒真断言删除）**均已落地且实现方向正确**；限频实现线程安全/有界/不吞异常/消息源稳定逐项实核通过。但本轮新引入的模块级限频态**副作用未闭环**：MS-T13 退化为顺序耦合脆弱断言（P1-1，3 行可修），建议**并入本批修复**；其余 P2（HEAD-400 覆盖真空、契约漏登 3 处测试资产、墙钟、episode 盲区、用例硬编码）记录不阻断，由编排层裁决 |
| 问题统计 | **P0 = 0 · P1 = 1 · P2 = 4** |
| 最严重项 | `tests/test_server_http.py:358`（P1-1）：MS-T13 未隔离 `_pool_fetch_warned_at` 全局态——修复本身引入的副作用，同批内新用例已示范正确手法、旧用例漏改 |
| 零上下文纪律 | ✅ 入参 = 触发报告（仅取 P2-4/5/6 条目）+ 4 改动文件 + `>>DIFF` + 契约文档只读核对；未读取其它评审/测试报告正文 |

>>DECISION: APPROVE
