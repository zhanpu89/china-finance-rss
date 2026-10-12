# 对抗性盲审报告 — market_sentiment 独立接口

> **编号** BLIND-REV-20261010-001 · **模式** P8 对抗性盲审（`>>MODE: blind`）· **日期** 2026-10-10
> **入参范围（零上下文）**：需求原文 `doc/detailed/market_sentiment_独立接口.md`（R1–R10 / RG1–RG7 / MS-T1..T16 / B-01..B-05）；改动文件 `china_finance_rss/server.py`、`china_finance_rss/config.py`、`tests/test_server_http.py`、`tests/stress_all.py`；`>>DIFF` 客观摘要；契约文档**略读**核对（`doc/detailed/server.md`、`doc/arch/SAD.md`、`API.md`、`README.md`、`cdp_engine.md`、`config.md`）。变更面：新增 `GET /finance/market_sentiment`；`GET /finance/market` 成功体/降级体剥离 `market_sentiment` 键。
> **纪律声明**：未打开任何 `doc/review/**` 评审报告、`doc/tester/**` 测试报告正文。*（全仓 grep 定位关键词时，这些文件的匹配行首被动返回，仅用于排除、未采信；下列全部结论均出自需求原文与源码/测试实读。）*
> **审查基线**：需求即契约；"代码没有的逻辑就是没有实现"。

## 一、对抗性假设 → 实核结论（B2）

| # | 预设"必有问题"的假设 | 实核证据 | 结论 |
|---|---|---|---|
| H1 | 剥离只做一半 ⇒ `/finance/market` 残留该键 | 两动作齐备：`server.py:283` `data.pop('market_sentiment', None)` + `config.py:204-207`（5 键、无该键）；`cache.py:1155-1161` 双循环语义逐行实核（只删 expected ⇒ 回填**原值** / 只 pop ⇒ 补 **None** / 齐做 ⇒ 键不在） | 证伪 |
| H2 | 降级路径返回裸 null 或 5xx | 三条降级体字面量与 R3 逐字一致（`server.py:341`/`:345`/`:348`）；分发经 `_send_json_shape`（`:1412-1425`）恒 200，`http_503_total` 仅准入与 healthz（`:1304`/`:1703`） | 证伪 |
| H3 | 注册点遗漏 / 计数断言有裂缝 | RG1–RG7 逐条实核 + 手工点数：`_JSON_SHAPES`=**19**（`:544-555`）、`_PANEL_HANDLERS`=**5**（`:570-576`）、`_JSON_DISPATCHED_PATHS` 集合等式成立（`:589-594`）、`_CACHE_AGE_DOMAINS`→`quote`（`:601`）、feeds=**20**（`:1002-1046`）、首页 `:1625`、`main()` `:1841`、计数注释 `:540`/`:568`/`:1310` | 证伪 |
| H4 | 对共享缓存 dict 就地修改 ⇒ 跨请求污染 | `CDPPage.get_data`（`cdp_engine.py:1160-1168`）锁内**每次新建 `merged`**，pop 只作用于副本；`_ingest_payload`（`:815`）以 `cache.update` **替换**值而非原地改写 | 当前证伪，**但该不变式零测试锁定**（→ P2-4） |
| H5 | `handle_cls_pool` 改动吞异常 / 类型错 / 噪声 | `isinstance(raw, dict)` 门在 `raw.get` 之前（`:482`→`:484`）；`str()` 仅包 error 值、返回契约与改动前逐字一致；`log.warning` 不改控制流 | 功能面证伪；**日志放大成立**（→ P2-5） |
| H6 | 测试断言不可证伪 | MS-T9 三态与 `cache.py` 语义逐行对齐（任一单动作回归必红）；MS-T11b 裸 socket **先自证读法**再断言 | 大体证伪（1 条恒真断言除外 → P2-6） |
| H7 | 代码与契约文档不一致 | `server.md` / `SAD.md` / `API.md` 各命中一处 | **成立**（→ P2-1..3） |

## 二、问题清单（每条：一行结论 + 证据链 + 影响 + 修复方向）

【P2】doc/detailed/server.md:720: `feeds` 条目数仍写「19 条」，而实现与本文档自身其它落点均已是 20 —— 详设内部自相矛盾。
- **证据**：`:720`「feeds: # 既有；19 条，字段集合不变」、`:1522`「feeds = _base_feed_entries(base_url) # 19 条（§2.9.1 修正后 status）」；对照 `server.py:1002` docstring「20 healthz feed entries (5 RSS + 15 JSON/CDP)」、`server.md:467`「20 个基础条目」、`:597`「feeds 19→20」、`tests/test_server_http.py:866`/`:877` 断言 20。R7/RG5 要求 feeds 19→20，同步只改了 §2.9 与 §2.9.1，漏了 §3.3 schema 与 §5 伪代码两处。
- **影响**：下游或校验脚本若以 `:720`/`:1522` 为准核对 `/healthz` `feeds[]` 长度会误判为回归；同一文档两套数字削弱详设作为唯一权威的可信度。无运行时影响。
- **修复**：`:720`、`:1522` 两处 19 → 20；`server.md:2090`（偏差登记表「保持现状 19 条」）建议补注「后经本增量 19→20」。

【P2】doc/arch/SAD.md:562: `_guard` 覆盖声明「全部 15 个 JSON 分支（面板 5 + stock 6 + 其余 4）」漏计 4 个 CLS 池，实际为 19；`:806` 声称代码「含 `assert len == 15`」与代码不符。
- **证据**：`SAD.md:562` 枚举 5+6+4=15，缺 `/cls/up_pool`·`/cls/continuous_up_pool`·`/cls/up_open_pool`·`/cls/down_pool`；`SAD.md:806`「`assert len == 15`」vs `server.py:555` 实为 `assert len(_JSON_SHAPES) == 19`（手工点数 19 复核）；对照 `doc/detailed/server.md:1877`「19 个 JSON 分支」与代码一致 —— SAD 是唯一的错方。本批 P7b 契约同步恰改写了这两行（14→15），只追平了本增量、未追平 4 池批次欠账。
- **影响**：架构契约把"结构护栏"的数值写错，阅读者会以为护栏钉在 15；与 server.md/代码三方不一致。不影响运行（导入期 assert 在代码侧正确）。
- **修复**：`:562`/`:806` 15 → 19 并在枚举中补列 4 池。

【P2】API.md:679: §6.1 缓存域表把 `/finance/market` 归入 `plate` 域（盘中 12s），与同节 `:704` 及代码矛盾；新端点在该表无任何行。
- **证据**：`:679`「`plate`（L2）| `/cls/hotplate` `/finance/market` | **12s** / 120s」；`:704`（本批已改写、含 `/finance/market_sentiment`）声明 5 面板 `max-age` 跟随 `quote`（盘中 **4s**）；`server.py:600-601` 两路径均注册 `'quote'`，`_cache_age()`（`:1503-1512`）只认该表。§6.1 自称是"接入方视角的新鲜度边界"承诺面，表与注在同一屏互相矛盾。
- **影响**：接入方只读表格会认为 `/finance/market` 盘中 12s（实际 4s，按表缓存会多估 3×TTL 的新鲜度），且新端点的 `max-age` 无表可查；`:701` 的实测样例在非盘中（两者同为 120s）恰好掩盖了该矛盾。表格行 `plate` 的"数据特征=板块轮动"也与 `/finance/market` 内容不符，属陈旧行。
- **修复**：`:679` 行移除 `/finance/market`；在 `quote` 行（`:675`）补 5 个面板（或单列「5 面板 | quote | 4s / 120s」行）。

【P2】tests/stress_all.py:43: 新端点未纳入任何压测/新鲜度清单，且 MS-T* 全部把 `page_data` 打桩 ⇒「共享页 `pop` 不污染兄弟端点」这一关键不变式**零测试覆盖**。
- **证据**：`GLOBAL_ENDPOINTS`（`stress_all.py:43-49`）、`freshness_test.py:49`、`loadtest.py:54`、`stress_test.py:32` 均无 `/finance/market_sentiment`；`MarketSentimentTests` 与 MS-T6 全部 `patch.object(srv, 'page_data', ...)`（`test_server_http.py:456-457`/`511-512`/`1017-1019`/`1023-1024`）；全仓无任何用例驱动真实 `CDPPage.get_data` 的合并语义（`test_data_layer.py` 只测 `page_data` 的 None 防御与 `_last_data` 淘汰）。
- **证据链（成立的逆向假设）**：若日后把 `cdp_engine.py:1160-1168` 的 `get_data` 改为 `return self.cache`（省一次 dict 拷贝的常见"优化"）→ `server.py:283` 的 `pop` 将作用于**共享页面缓存** → `/finance/market` 任一次请求之后，`GET /finance/market_sentiment` 恒返回 `{"error":"market_sentiment unavailable"}`（直到心跳重新 ingest，`KEY_TTL_OVERRIDES['market_sentiment']=60`）→ **HTTP 200、无告警、无指标**，且当前单测（打桩）与压测脚本（不请求该端点）**全绿**，只能靠人肉发现。
- **影响**：本变更唯一新增的对外可用性，其正确性悬在一条未被测试锁定的实现细节上；`stress_all` 模块头声明的 "No data cross-contamination" 对新端点形同虚设。**属防护缺口、非现存缺陷**（当前 `get_data` 每次新建 `merged`，已实核正确）。
- **修复**：① `stress_all.GLOBAL_ENDPOINTS` + `check_endpoint` 增该端点（断言 200 且体含 `code`/`data`）；② 参照 `test_data_layer.py:1760-1768` 的 `CDPPage.__new__` 注入模式补一条不变式用例：连续两次 `get_data()`、就地 `pop` 第一次结果、断言第二次键仍在。

【P2】china_finance_rss/server.py:477: B-02 新增的 `log.warning` 在"负缓存按请求抛错"的语义下，日志量随**请求速率**而非**故障次数**放大。
- **证据**：`cache.py:817-820` 负缓存命中对**每个请求**都 `raise FetchError(...)`（不摊销、不计数）→ 上游持续故障期间，每个 `/cls/{up,continuous_up,up_open,down}_pool` 请求都走进 `handle_cls_pool` 的 except 各打 1 条 WARNING；4 池 × RPS ⇒ 4×RPS 行/秒、随故障时长线性累积。对照同为失败路径的 `handle_cls_hotplate`（`:379-384`）仍只把 error 写进响应体、不打日志 —— 同一故障两套可观测性口径。
- **影响**：日志/磁盘管道压力与告警噪声，可能淹没同级信号。**不吞异常、不改响应契约**（返回值与改动前逐字一致），负缓存已阻断上游、无功能与安全影响。该行为是详设 B-02 明确要求且被 MS-T13 锁定，故这是修复本身的**副作用**而非实现走样。
- **修复建议**：保留信号、加去重/限速（按 `(pool_type, kind)` 每 30s 一条 + 累计计数），不建议删除日志或回退 B-02。

【P2】tests/test_server_http.py:1035: `test_head_on_market_sentiment_writes_no_body` 的 `body == b''` 断言在 `http.client` 下恒真，不可证伪。
- **证据**：`http.client` 对 HEAD 把读取长度归零（服务器真把 body 写上线也返回 `b''`）→ `:1035` 该维度无判别力，仅 `:1034` 的 status=200 有效；同文件 `:1037-1085` 的 `_raw_exchange` + `test_head_body_never_reaches_the_wire` 正是为补此盲区而加（其 docstring 自陈"该断言被架空"），说明作者已知 `:1035` 是空断言却仍保留在套件中。
- **影响**：一条"永远绿"的 body 断言给出虚假覆盖信号——若 MS-T11b 被误删或被 skip，HEAD body 回归无人拦截。
- **修复**：删除 `:1035`，或改为只断 status 并在 docstring 注明 body 维度由 `test_head_body_never_reaches_the_wire` 覆盖。

## 三、定级说明（为何 P0×0 / P1×0）

- **安全面（P0 候选）逐项排查无发现**：新端点只读、无参数拼接、无 SQL/命令/URL 注入面（键名为常量，值为上游 JSON 原样透传且经 `json.dumps` 序列化）、无鉴权/多租户可越权面、无敏感信息泄露面（`str(exc)` 泄露的上游 URL 属既有契约、且本批仅新增日志副本）。
- **崩溃/数据丢失面（P0 候选）无发现**：handler 为总函数（CDP 门 → `page_data` 防御取数 → error 客体），异常由 `_guard` 兜底恒 200；`data.pop` 作用于 `get_data()` 每次新建的 `merged` 副本（`cdp_engine.py:1160-1168` 实核），无共享状态污染、无锁新增。
- **功能缺陷面（P1 候选）无发现**：R1–R10 / RG1–RG7 逐条对齐（见 §一 H1–H3），三条降级体与 R3 逐字一致，剥离两动作齐备且 MS-T8/MS-T9 对任一单动作回归必红，计数断言（19/19/5/20）与手工点数一致、导入期护栏成立。
- **最严重 P2 = P2-4（新端点共享页不变式零测试覆盖）**，不构成 P0/P1 的理由：① 现存实现**正确**——`get_data` 每次新建 `merged`、`_ingest_payload` 以 `update` 替换值，实核无污染，未发生任何功能错误；② 触发需要一次**未来的**重构（把 `get_data` 改成返回共享 dict），是防护缺口而非现存缺陷；③ 失败形态是"新端点返回 error 客体 + 200"的既定降级路径，无数据丢失、无崩溃、无安全面，最坏后果是新端点在 60s 级窗口内持续报"unavailable"——属功能可用性风险但需前提条件才触发，按"必须改/建议改"分界归 **建议修（P2）**。
- 其余 P2（P2-1/2/3 文档漂移、P2-5 日志放大、P2-6 恒真断言）均为规范与可维护性问题，按定义不阻断。

## 四、契约漂移登记（供编排层调度 DOC_SYNC；本 agent 不改契约文档）

| 文档 | 落点 | 现状 → 目标 |
|------|------|------------|
| `doc/detailed/server.md` | `:720`、`:1522`（另 `:2090` 加注） | feeds 条目 `19 条` → `20 条` |
| `doc/arch/SAD.md` | `:562`、`:806` | `_guard` 覆盖 `15` → `19`（枚举补 4 CLS 池；`assert len` 数值同步） |
| `API.md` | `:679`（§6.1 表） | `plate` 行移除 `/finance/market`；`quote` 行（`:675`）补 5 面板含 `/finance/market_sentiment` |

（`README.md`、`cdp_engine.md`、`config.md`、`server.md` 路由/形状/feeds 状态表、`API.md` §3 新端点节与字段表已实核一致，**无漂移**。）

## 五、评审结论

| 项 | 结论 |
| --- | --- |
| **评审结论** | ✅ 通过（APPROVE）— 代码实现与需求 R1–R10 / RG1–RG7 逐条一致，剥离两动作齐备、降级三态无裸 null、7 注册点与计数断言无裂缝、无并发污染；遗留 P0×0 / P1×0 / **P2×6**（3 处契约文档计数/表格漂移 + 1 处测试护栏缺口 + 1 处日志放大副作用 + 1 条恒真断言），均为记录不阻断项 |
| 问题统计 | **P0 = 0 · P1 = 0 · P2 = 6** |
| 最严重项 | `tests/stress_all.py:43`（P2-4）：共享页 `pop` 不变式零测试覆盖 —— 建议修复，不阻断 |
| 零上下文纪律 | ✅ 入参 = 需求原文 + 4 改动文件 + `>>DIFF` + 契约文档略读；未读取评审/测试报告正文 |

>>DECISION: APPROVE
