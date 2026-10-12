# 代码评审报告（market_sentiment P5a-r1 P2 修复轮）

**CR-20261010-003 | 模式: P5b review+drift（P5b-r1 修复评审 + P7a 漂移检测）| 日期: 2026-10-10**

| 项目 | 值 |
|------|-----|
| 评审对象 | P8 盲审遗留 P2-4 / P2-5 / P2-6 三条修复（P5a-r1，均不改对外契约） |
| 触发源 | `doc/review/market_sentiment_对抗性盲审报告.md`（BLIND-REV-20261010-001） |
| 契约文档 | `doc/detailed/market_sentiment_独立接口.md` v1.0.2、`doc/detailed/cls_pools.md` v1.0.2 |
| 评审方法 | 静态实读（评审容器无 shell、未执行套件）：代码/文档行号级逐行核对 + 变异推演；测试执行由 P6 门禁承担 |

> **总评：** 三条 P2 均为真闭合——限频实现与详设 §5.5 伪代码逐行一致、共享页不变式由 2 条驱动真实 `page_data→get_data` 的用例锁定且变异必红、恒真断言已删且由 MS-T11b 裸 socket 线上字节承接；修复未引入 P0/P1。逆向审查另识别 3 条 P2（同文件同类恒真断言的 400 分支无后备、MS-T13 与限频表的测试顺序耦合、§5.5 历史行号引用过期），均记录不阻断。

## 一、评审概要

**结论：✅ 通过 — 3 条 P2 真闭合，新测试可证伪，契约文档与代码一致，未引入新缺陷。**

| 等级 | 数量 | 说明 |
|------|------|------|
| P0 | 0 | — |
| P1 | 0 | — |
| P2 | 3 | 逆向审查新识别（F-1/F-2/F-3），记录不阻断 |

## 二、评审范围与受影响点推断

入参未附 `>>SIDE-EFFECT:`，以下受影响点由改动自推断并**标注所属模块**（供编排器映射 tester 的 `>>SCOPE:` 定向回归）：

| # | 受影响点 | 模块 | 行为变化 | 逆向假设核验 |
|---|---------|------|---------|--------------|
| S1 | server.py `handle_cls_pool` except（:503-505） | server / CLS 4 池端点 | 逐失败打日志 → 每 (pool_type, msg) 30s 窗口 1 条 | 下游 `_send_json_shape`→`_guard`：返回体 `{'error': str(exc)}` 逐字不变（测试断言 first==repeat==expired）；相邻分支（enum gate :488 / envelope :509-512 / shape :516）零改动 → 自洽 |
| S2 | server.py 新增模块级状态 `_pool_fetch_warned_at`（:457-474） | server / 全局状态 | 新增 ≤4 键 lock-free 表 | 无旧消费者依赖旧行为；新耦合点=测试间模块状态共享 → F-2 |
| S3 | tests/test_server_http.py MS-T11（:1060-1068） | tests / HTTP 语义 | 删恒真 body 断言、保留 200 | 覆盖消费者 MS-T11b（:1097-1118）已线上实测承接 → 无净损失 |
| S4 | tests/test_data_layer.py :1823-1867 | tests / 数据层 | 纯新增 2 用例 | 不触碰既有用例/实现 |
| S5 | tests/stress_all.py :45 / :121-130 | tests / 压测脚本 | 新端点入清单 + 校验分支 | 脚本不在 unittest 发现范围（存量性质） |
| S6 | 两份详设 v1.0.2 回填 | docs / 契约 | §5.5 B-02、§8 MS-T11、cls_pools §7.1 | 同节历史行号未顺带刷新 → F-3 |

## 三、问题清单

| ID | 等级 | 文件:行号 | 问题描述 | 阻断 |
|----|------|-----------|----------|------|
| F-1 | P2 | tests/test_server_http.py:985 | 同类 HEAD body 恒真断言：400 分支无 MS-T11b 后备，HEAD 400「无 body」无可证伪锁定 | 否 |
| F-2 | P2 | tests/test_server_http.py:358-369 | MS-T13 未做 hermetic 清表，通过性依赖类内字母序（限频引入的测试状态顺序耦合） | 否 |
| F-3 | P2 | doc/detailed/market_sentiment_独立接口.md:295 / :315 | §5.5 B-03/B-04 历史伪代码行号引用过期（既有欠账，本批未顺带修正） | 否 |

## 四、修复闭合核验（P2-4 / P2-5 / P2-6）

### P2-4 共享页不变式零测试锁定 —— ✅ 真闭合

- **处方覆盖**：① `GLOBAL_ENDPOINTS` 增端点（stress_all.py:45）+ `check_endpoint` 校验分支（:121-130：dict 守卫 + `code`/`data` 键 + 信封 `code==200`，HTTP 200 由 global_task :170 前置断言）✓；② 不变式用例超额落地 2 条（盲审处方为「补一条」）✓。
- **可证伪性独立复核（变异 `get_data → return self.cache`）**：`test_each_read_is_a_distinct_dict` 首断言 `assertIsNot(first, second)` 即红（两次皆为同一 `page.cache`；`assertIsNot(first, page.cache)` 同红）；`test_pop_on_one_read_does_not_reach_the_next` 的 pop 直改共享 cache ⇒ 第二次 `assertIn('market_sentiment', second)` 红。**code-developer 变异自检论断成立**（静态推演复核；`page.cache` 非空 ⇒ `page_data` 不落 None 分支，无假绿路径）。
- **真实路径、无打桩**：`cdp_engine.page_data(page)` → `page.get_data()`；`__new__` 注入的 5 属性恰为 `get_data` 全部依赖（`_lock/_last_data/_last_data_ts/_last_data_max_age/cache`，cdp_engine.py:1160-1168 实核），注入模式与 `LastDataEvictionTests._page`（test_data_layer.py:1760-1768）逐属性同构。
- **对齐真实调用方**：用例 pop 的 3 键与 `handle_finance_market`（server.py:281-283：`__ws__`/`timeline`/`market_sentiment`）逐一对应；兄弟端点 `handle_finance_market_sentiment`（server.py:346 `data.get` 只读）依赖键存活——正是盲审 H4 的因果链。
- **范围外残留（登记、不判缺口）**：`freshness_test.py:49`/`loadtest.py:54`/`stress_test.py:32` 仍无该端点——盲审修复处方仅规定 stress_all，按处方口径不构成闭合失败。

### P2-5 失败日志负缓存下放大 —— ✅ 真闭合（6 项专项全过）

| 专项 | 核验结论 |
|------|---------|
| 线程安全 | lock-free `get`/`__setitem__` 在 GIL 下原子、表无遍历 ⇒ 无 `RuntimeError`；先写后志 ⇒ 竞态最坏=窗口内重复一条（有界于 worker 数），不触业务语义。与 `metrics.py:17`「intentionally lock-free (tolerated race)」同款模式，cls_pools §7.1 已登记。**无 P0/P1** |
| 竞态容忍边界 | §7.1 称「最坏多/少告警一次」：实核「少告警」在 get/set 原子性下不可构造（写者必志），文档表述保守无害 |
| 吞异常/失败语义 | `_warn_pool_fetch_failed` 无 try/except；`:505 return {'error': str(exc)}` 原位不变；测试断言 first==repeat==expired 且 `set(first)=={'error'}`；lazy `%s` 渲染与原文案逐字一致（MS-T13 :368 子串断言不受影响） |
| 既有模式复用判断 | **复核成立**：`metrics._warn_once`（metrics.py:66-69）= 进程级永久去重 + `[metrics] ` 前缀 + logger `metrics` → 复用会破坏 MS-T13 的 logger/文案契约且丢「窗口后再告警」；`cache._warn_feed_degraded_once`（cache.py:926-936）= logger `cache`、按 reason 永久一次 → 同不适用；且 §5.5 伪代码已钉死实现形态（偏离即漂移）。项目内无通用窗口型限频 helper（`_last_chrome_restart` 为域内手写）⇒ 手写符合「先找模式」惯例 |
| 键有界 | enum gate（:488）先于 try（:499）⇒ except 路径 `pool_type ⊆ _POOL_TYPES`（4 值 frozenset）⇒ 表 ≤4 键；codegraph 实核唯一调用方 :504 |
| 时间源 | `time.time()` 非单调——实核**不可能抛错**（负差仅延长抑制窗口）；最坏=时钟回拨量级内告警抑制延长，不触达业务；与 §5.5 伪代码 `now = time.time()` 逐字一致、与全仓时间戳惯例及既有评审先例（缓存协同修复r1：「墙钟回拨记录即可，不建议换 monotonic」）一致 ⇒ **判为可接受权衡，不记问题**（若改 monotonic 须同步伪代码） |

- **生产有效性（逆向补核，入参清单外）**：负缓存命中重抛 `FetchError(kind, url=url)`（cache.py:820）⇒ 真实 msg = `f'{kind}: {url}'`；`cls_sign_params`（utils.py:80-87）为纯 sha1/md5、**无时间戳** ⇒ 同 pool 每次构建的 URL 稳定 ⇒ msg 稳定 ⇒ 限频在生产真正生效（若签名含时间则 msg 每请求都变、限频形同虚设——实核排除；且签名可变时负缓存按 URL 键本身不会命中，与盲审「每请求重抛」实核自相矛盾，反证成立）。
- **新测试双向可证伪**：删限频 ⇒ `assertNoLogs`（:386）红；永久去重不看窗口 ⇒ expired 段 `assertLogs`（:391）红；改返回体 ⇒ `assertEqual`（:393-394）红。时间推进用写表注入而非 sleep（无时序抖动）；save/clear/restore 全 hermetic（:377-378 / :396-398）。
- **MS-T13 默认序仍绿**：类内字母序首个进入 except 路径的用例即 MS-T13 自身（其前 3 个用例均不进 except）；`CLS_INTEGRATION=1` 时真实 msg 带 `: url` 后缀、与 MS-T13 无 url 的 msg 必不同 ⇒ 不触发抑制。顺序脆弱性另记 F-2。

### P2-6 恒真断言 —— ✅ 真闭合，无覆盖净损失

- 删除的 `assertEqual(body, b'')` 恒真（`http.client` 对 HEAD 归零读取长度；tester M16 实证：`do_HEAD` 改写 body ⇒ 18 条仍绿而线上 54 字节）⇒ 删除 = 去伪覆盖。
- **MS-T11b 真正覆盖「HEAD 无 body」**：先 GET 自证读法（`get_body` 非空，防本用例自空）→ 裸 socket 断 3 路径 `body==b''` + Content-Length>0；若 `do_HEAD` 回归写 body ⇒ 读法已被 GET 自证 ⇒ 必红；位于 `HttpSemanticsTests`（真实 `BoundedThreadPoolServer`，无 skip，:1097-1118）。
- 文档 §8 MS-T11 行同步如实（doc:369 只锁状态码 + MS-T11b 承接 + `_serve_index` 半句，与 test :527 一致）。

## 五、问题详情（按 Dim）

### Dim 0 契约一致性

本批 3 修复均不改对外契约（无 OpenAPI/字段/状态码变化）；详设伪代码-代码一致性逐项核验结论见 §八 漂移检测 D1。

### Dim 1 数据与正确性

#### F-1（P2）HEAD 400 分支的 body 断言恒真且无后备

- **命中反模式**：恒真断言（不可证伪覆盖）——与 P2-6 同类、同文件的存量残留。
- **证据链**：`test_head_writes_no_body`（test_server_http.py:979-985）对 `/`、`/market/margin?market=bogus`、`/nope` 经 `http.client` 断 `body==b''` ⇒ 恒真（tester M16 已实证该类断言不可证伪）；MS-T11b 路径表（:1109-1111）仅 `(/finance/market_sentiment 200)`、`(/ 200)`、`(/nope 404)`。**当** HEAD 的 400 分支回归写 body（`_send_error`→`_send_text` 丢失 `write_body=False`）**⇒** :985 恒真绿、MS-T11b 不测 400 路径 **⇒** 无用例变红，线上 HEAD 400 带 body 无人拦截。
- **影响**：防护缺口（当前实现正确，`write_body=False` 实核无误），非现存缺陷；400 为参数校验分支、触发面真实存在。定级 P2（记录不阻断）。
- **修复**：MS-T11b 循环补 `('/market/margin?market=bogus', 400)`；:985 处 docstring 注明 200/404 已由 MS-T11b 线上覆盖（或删除该 body 断言）。

### Dim 2 并发

限频表专项核验通过（见 §四 P2-5 六项表：lock-free 原子读写、竞态容忍边界、有界键），**无发现**。

### Dim 3 资源与性能

**无发现**：表 ≤4 键、O(1) 读写、无新增分配热点；日志量由放大降为每窗口 1 条（本批收益）。

### Dim 4 安全

**无发现**：日志仅含既有契约已透出的 `str(exc)`（含签名 URL，盲审已核为既有契约），限频反而降低日志量；无注入/越权/敏感面变化。

### Dim 5 结构与可维护性

#### F-2（P2）MS-T13 与限频表的测试顺序耦合

- **命中反模式**：隐式共享状态（测试间模块级可变状态，未做 hermetic 隔离）。
- **证据链**：**当**新增一个类内字母序早于 `test_fetch_failure_logs_a_warning_before_degrading`、且以 `FetchError('upstream_timeout')`（无 url）触发 except 的用例 **⇒** `_pool_fetch_warned_at['up_pool']` 被预写且 30s 内 **⇒** MS-T13 `assertLogs` 无记录、假红。当前套件实核**不触发**（类内字母序首触者即 MS-T13 自身；全仓无其他 `handle_cls_pool` 调用方；integration 模式真实 msg 带 `: url` 后缀必不同）。
- **影响**：测试维护陷阱（未来新增用例时的偶发假红），非现存失败、无运行时影响。定级 P2。
- **修复**：MS-T13（:358-369）补与新测试同款 save/clear/restore 三行（样板：:377-378 / :396-398）。

#### F-3（P2）§5.5 历史伪代码行号引用过期

- **命中反模式**：文档-代码双重权威漂移（行号互指失效）。
- **证据链**：doc:295「B-03（server.py:467-468）」⇒ 实际 B-03 内容在 server.py:511-512（当前 467-468 是 `_warn_pool_fetch_failed` 函数体）；doc:315「B-04（tests/test_server_http.py:294-301）」⇒ 实际在 :296-313（内容 :306-309）。**当**读者按行号定位 **⇒** 落到无关代码 **⇒** 误判文档失效、浪费排查时间。非本批引入（盲审 H5 引用 :482/:484 可证修复前已偏），但 v1.0.2 更新同节 B-02 行号时未顺带修正同节历史引用。
- **影响**：可维护性/文档可信度，无运行时影响。定级 P2。
- **修复**：B-03 → `server.py:511-512`；B-04 → `test_server_http.py:296-313`（随下次文档同步）。

## 六、修复建议

1. **F-1 / F-2（测试加固，可合并一次小改）**：MS-T11b 补 400 路径 + MS-T13 补 hermetic 清表，各 1-2 行、样板均在同文件内。
2. **F-3（文档）**：编排层按漂移表派发 doc agent 随下次同步修正 §5.5 两个行号引用。
3. 无 P0/P1，无需回退或重构。

## 七、评审结论

| 项 | 结论 |
| --- | --- |
| 评审结论 | ✅ 通过（APPROVE）— P2-4/5/6 三条均真闭合：共享页不变式由 2 条真实路径用例锁定且变异必红（独立复核成立）、限频实现与 §5.5 伪代码逐行一致且 6 项专项（线程安全/竞态/吞异常/复用判断/键有界/时间源）全过、MS-T11 恒真断言删除后由 MS-T11b 线上字节承接无净损失；契约文档 v1.0.2 与代码一致；新识别 3 条 P2 均记录不阻断 |
| 问题统计 | **P0 = 0 · P1 = 0 · P2 = 3**（F-1 / F-2 / F-3，均记录不阻断） |
| 是否允许进入测试 | 允许（P6 常规执行；本评审为静态实读，未在评审容器内执行套件） |

>>DECISION: APPROVE

## 漂移检测（P7a）

**D1 契约核对（本批 3 个同步点，逐项）：**

| 同步点 | 文档落点 | 代码实位 | 结论 |
|--------|---------|---------|------|
| 限频常量 / 函数名 / 窗口语义 | market_sentiment §5.5 B-02（doc:282-293）：`_POOL_FETCH_WARN_GAP = 30.0`、`_warn_pool_fetch_failed(pool_type, exc)`、同 pool 同 msg 30s 窗口内一条、msg 变化即时再告警、lazy `%s` 消息格式逐字不变；调用点声称 :503-504、实现声称 :457-474 | server.py:457-474（实现）+ :503-505（调用点）——行号精确命中，逻辑逐行一致 | ✅ 一致 |
| MS-T11 表述 | §8 doc:369：「只锁状态码；body `== b''` 断言已删（http.client 恒真）；MS-T11b 裸 socket `_raw_exchange` 承接线上字节；`_serve_index()` body 含该路径」 | test_server_http.py:1060-1068（只断 200）+ :1097-1118（MS-T11b）+ :527（index 半句） | ✅ 一致 |
| cls_pools §7.1 模块级可变状态登记 | cls_pools doc:411/:415：`_pool_fetch_warned_at` = `pool_type -> (last_ts, last_msg)`、键 ∈ `_POOL_TYPES` ⇒ ≤4 键、lock-free/容忍竞态、30s 窗口、`NEG_TTL=5s`、纯日志限频不改业务语义 | server.py:457-474 注释与实现；config.py:40 `NEG_TTL=5` | ✅ 一致 |
| 版本头 / changelog | 两文档头部 v1.0.2 + 回填行（market_sentiment doc:439 / cls_pools doc:504，声明「只改文档」） | — | ✅ 一致 |

**D2 DOC_SYNC 追溯：** 入参摘要声明本批同步 = §5.5 B-02 + §8 MS-T11 + cls_pools §7.1，三处均已实核存在且与代码一致 ✅（入参未附 P5a 原始 `>>DOC_SYNC:` 标记清单——若另有标记，请编排器比对补验）。

**D3 规范合规：** 手术式修改（3 修复各守其位、未动无关代码）✅；lock-free 模块状态与 `metrics._warned` 既有模式及项目「容忍竞态」注释风格一致 ✅；新测试沿用 `CDPPage.__new__` 注入、`assertLogs`、save/restore 既有样板 ✅；无新增配置项/外部依赖 ✅。

**D4 漂移结论：**

- 本批同步点：**✅ 无漂移**。
- 登记 1 条**既有**漂移（非本批引入，随附 F-3，可选派发）：`market_sentiment_独立接口.md` §5.5 B-03/B-04 行号引用过期 —— doc:295 → 实为 `server.py:511-512`；doc:315 → 实为 `test_server_http.py:296-313`（内容 :306-309）。

**变更记录**

| 版本 | 日期 | 变更 | 作者 |
|------|------|------|------|
| r1 | 2026-10-10 | 首版：P5b-r1 修复闭合核验（P2-4/5/6 + 6 项专项 + 变异推演）+ 逆向新识别 F-1/F-2/F-3 + P7a 漂移检测 | code-reviewer |
