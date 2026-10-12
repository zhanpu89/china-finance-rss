# 代码评审报告 — market_sentiment 独立接口 + P8 5×P2 修复

**CR-20261010-002 | 模式: P5b review+drift（P5b 评审 + P7a 漂移检测）| 日期: 2026-10-10**
**评审基准**: `doc/detailed/market_sentiment_独立接口.md` v1.0.1（R1–R10 / RG1–RG7 / MS-T1..T16）· 关联契约 `doc/detailed/server.md` v1.19 · `doc/detailed/config.md` v1.14
**变更文件**: `china_finance_rss/server.py`(+124) · `china_finance_rss/config.py`(+11) · `tests/test_server_http.py`(+442) · `tests/stress_all.py`(-1)
> `opencode.json` 系用户自行改动，按编排指令排除；`API.md`/`README.md`/`doc/detailed/*`/`_PROGRESS.md` 契约文档属 P7b 范围，本评审只在漂移节核验其状态、不改文档。本次为静态评审（会话无 shell），单测执行由门禁 `check-changed.sh` / tester 承接。

---

## 一、评审概要

**总评：代码侧质量高——剥离两动作齐备且被 MS-T8（端到端）+ MS-T9（`_fill_missing` 语义级）双层锁死；新 handler 与 `handle_finance_timeline` 逐行同型（R3/R5/R18 全中）；7 注册点 RG1–RG7 一个不漏，19/5/20 三组计数断言与注释全仓零裂缝；B-01..B-05 全部按详设 §5.5 伪代码落地且各有可证伪用例。6+2 条 SIDE-EFFECT 逆向核对未发现被改坏的既有调用方。无 P0/P1/P2 代码问题；残余风险全在文档面（4 条已申报 DOC_SYNC 待 P7b + 1 条本评审新发现）。**

| 项目 | 结果 |
|------|------|
| **评审结论** | ✅ 通过（APPROVE）：P0=0 · P1=0 · P2=0；漂移 5 条文档级待同步（4 已申报 + 1 新申报），代码级 0 |
| P0（阻断） | **0** |
| P1（建议修复/生产阻断） | **0** |
| P2（记录不阻断） | **0** |
| 进入测试 | ✅ 允许（tester 按 MS-T1..T16 + 受影响回归面执行） |

## 二、编排器指定评审重点核对（8/8）

| # | 重点 | 核对结果 | 证据位置 |
|---|------|---------|---------|
| 1 | **剥离两动作同时存在** + MS-T8/T9 可证伪 | ✅ 动作① `data.pop('market_sentiment', None)` 在 `handle_finance_market` 内与 `timeline` 剥离同处；动作② `_FINANCE_EXPECTED_KEYS` 现为 5 键（无 market_sentiment）。MS-T8 `assertNotIn` 端到端；MS-T9 (a) `assertIn`+原值 / (b) `assertIn`+`None` / (c) `assertNotIn` 三态与 `cache.py:1155-1161` 双循环语义逐行实核一致（a 走 extra 分支填原值、b 走 expected 分支补 `None`、c 两循环均不含）——对任一单动作回归**必红** | server.py:283 / config.py:204-207 / test_server_http.py:504-539 / cache.py:1155-1161 |
| 2 | **新 handler 与 handle_finance_timeline 同型性** | ✅ 逐行比对：CDP ready 门（None/ready=False 双态）→ `get_page('cls_finance')` → `page_data(page)` → `data is None` 降级 → `ms is None` ⇒ `{'error': 'market_sentiment unavailable'}`（R18 非裸 null）→ 成功原样 `return ms`（R5 逐字节透传）。仅注释措辞差异 | server.py:337-349 vs :322-334 |
| 3 | **计数断言一致性、全仓无残留** | ✅ `_JSON_SHAPES` 注释 `19 JSON branches`(:540)、`assert == 19`(:555)、`_PANEL_HANDLERS` 5 项(:568 注释)、feeds docstring `20 healthz feed entries (5 RSS + 15 JSON/CDP)`(:1002)、分发注释 `5 panels`(:1310)；测试 `len==19`(:49/:465)、`len==5`(:466)、feeds `20`(:865/:876)。全仓 grep（`china_finance_rss/**` + `tests/**`）无残留 `18 JSON`/`== 18`/`4 panels`/`面板 4` 旧断言或注释 | server.py:540/555/568/1002/1310 · test_server_http.py:49/465/466/865/876 |
| 4 | **B-01..B-05 修复正确性** | ✅ B-01 `@unittest.skipUnless(os.getenv('CLS_INTEGRATION'))` 类级门控（默认跳过，setUpClass 不执行），断言仅 status/no-error/stocks-is-list、不写死外网数值；B-02 `log.warning` 在 `except` 内**先记后返**(:476-478)；B-03 `str(raw.get('msg') or 'upstream_error')`(:485)；B-04 正则 `r'ttl=\s*\d+'` 对真源 `ttl=cache_policy('plate')['ttl']`（`=` 后字母 `c`）不命中、对合成 `ttl=30/60/300` 必命中且旧正则 `r'ttl=\s*12\d*'` 必漏；B-05 config.py:387 注释含 `4 cls pools` | test_server_http.py:542-591 / server.py:476-478,485 / :295-312 / config.py:387 |
| 5 | **安全** | ✅ 新端点无参 handler、无用户输入消费（path 为分发表键，query 语义与既有面板同型）；**无新增 urlopen/HTTP 调用**（HTTP 出口仍仅 `fetch_json`/CDP 既有）；无 URL 拼接、无注入面、无敏感信息；响应为 `application/json` 原样透传；零新增第三方依赖（R10） | server.py:337-349 / 全仓无新增网络 API |
| 6 | **并发/资源** | ✅ handler 纯局部变量、无共享可变状态、无锁；**关键逆向：`CDPPage.get_data` 每次在锁内新建 `merged` dict**（cdp_engine.py:1160-1168）⇒ `/finance/market` 的 `pop` 只作用于局部副本，**不可能把键从页面缓存剥掉而误杀新端点**（若返回活引用则两端点互斥，实核不成立）；新端点 0 上游调用、无 N+1、无新缓存容器 | cdp_engine.py:103-119,1150-1168 / server.py:281-285 |
| 7 | **测试可证伪性** | ✅ 逐条核对 MS-T1..T16（见第五节）：对正确实现全绿、对各自回归场景必红；MS-T15 双向（真源不命中 + 合成命中 + 旧正则漏检）表述与实现一致 | 见第五节 |
| 8 | **契约一致性（漂移维度）** | ✅ server.py vs `server.md` v1.19 路由表/形状/handler 清单/feeds 状态值/cache-age/计数**逐项一致**；config.py vs `config.md`：`_FINANCE_EXPECTED_KEYS` 未被 config.md 登记（无旧内容可漂移），但 **§3.1 plate 行注释镜像缺「4 cls pools」→ 漂移（新申报）**；API/README/cdp_engine/SAD 漂移均已申报待 P7b | 见第八节漂移检测 |

## 三、SIDE-EFFECT 逆向核对（code-developer 申报 6 条 + 评审推断 2 条，8/8 通过）

| # | 受影响点（模块） | 逆向假设（谁会因此被改坏？） | 结论 |
|---|----------------|---------|------|
| 1 | server:`handle_finance_market` 成功体/降级体去 market_sentiment 键（唯一对外契约变化，🟠 STABLE 字段回退） | 谁还期望读到该键？→ 全仓：单测仅 MS-T8 断言**不在**；`stress_all.py` 键清单已移除；`freshness_test/loadtest/stress_test/ac_e4` 均不断言该键；降级体是 `{'error':…}` 字面量、天然无键；对外面 API.md:328/:332 与 README:58 仍写旧契约 → 属已申报 DOC_SYNC（P7b 承接，见漂移节 D2） | ✅ 无代码调用方被改坏 |
| 2 | config:`_FINANCE_EXPECTED_KEYS` 6→5（读该 frozenset 处不再见 market_sentiment） | 谁读它？→ 全仓唯一消费方 `server.py:285`（`_fill_missing`）；与动作①配对后结果=键消失；若单删此处置回 6 键 ⇒ MS-T8/:523 立即红 | ✅ 单消费方、双动作成对 |
| 3 | server:`handle_cls_pool` 失败路径 +WARNING 日志；code≠200 时 error 归一 `str` | 谁消费 error 类型/日志频率？→ 对外 error 契约恒为 str（§3.2/BR-POOL-8），POOL-T6 断言文案不变（已是 str）；MS-T14 锁 int→str；日志与既有 shape 告警(:489)同风格同频率（每失败 1 条），无刷屏放大 | ✅ 类型收紧、日志仅增量 |
| 4 | server:`/finance/market` max-age 不变(quote)；新端点 max-age 走 quote(4/120) | 谁依赖 max-age？→ `_CACHE_AGE_DOMAINS['/finance/market']` 未被触碰；`CacheAgeTests:751` **遍历整表**断言 `_cache_age()==cache_policy(domain)['ttl']`，任何域漂移必红；未注册路径仍落 f10 兜底逻辑未变 | ✅ 头部契约零变化 |
| 5 | server:`/healthz` feeds 19→20；首页 +1；启动日志 +1 | 谁数 feeds？→ 仅 `HealthPayloadTests:865/:876`（已改 20）；`test_server.py:170/:248` 用 `assertIn` 子集断言、不数数；`_run_health_checks` **只遍历 ROUTES（5 RSS）**（server.py:1147）⇒ feeds+1 **不增加** `?check=1` 网络开销；首页/日志无行数断言 | ✅ 无第三处计数消费者 |
| 6 | tests:stress_all 键清单少 1 键 | 该清单是"必备键"探测器（missing key），不是"必须没有"探测器 ⇒ 移除后剥离结果不再被误报；副作用=脚本不再发现键**意外重现**——该回归已由 MS-T8 单测兜住 | ✅ 覆盖职责移交正确 |
| 7（推断） | server:`assert len(_JSON_SHAPES)==18→19` + `_JSON_DISPATCHED_PATHS` 并集断言（导入期护栏） | 护栏与消费方是否同步？→ `_JSON_DISPATCHED_PATHS=frozenset(_PANEL_HANDLERS)∪…` 自动含新键(:589-594)；`ShapeTableTests:49/:60` 已 19 且断言 dispatched==shapes；batch 子集断言(:565)不受影响（新条目为 object） | ✅ 导入期/测试期零裂缝 |
| 8（推断） | server:首页 `json_apis` +1 / `main()` 日志 +1 / 三处注释计数同步 | 有无断言或下游依赖行数/措辞？→ 首页仅 `assertIn(path)`（MS-T11:496-502）；日志无断言；注释为文档性，已同批更新 | ✅ 无隐藏消费者 |

## 四、维度评审详情（D0–D5；Dim 6 无前端变更，跳过）

### D0 契约一致性 — ✅ 通过

以详设 §2.1 OpenAPI（v1.0.1）为唯一来源，逐项核对实现：

| 契约点 | 详设依据 | 实现核对 |
|--------|---------|---------|
| `GET /finance/market_sentiment` shape=object、仅 GET、无 query/请求体/鉴权、未注册 404 | §2.1 / R1 | `_JSON_SHAPES:546` 'object'；经 `_PANEL_HANDLERS:573` → `_send_json_shape`（shape 从表读，无字面量）✓ |
| 状态语义表 5 行（成功原样 / CDP 未就绪 / page_data None / 键缺失 / _guard 兜底，恒 200） | §2.1 表 | :341/:345/:348 三降级文案逐字一致；`_guard` object shape 恒 200（N1）由 MS-T6 断言 ✓ |
| 成功体 = 页面 `market_sentiment` 值原样（不裁剪/不改名/不补默认） | §3.1 / R5 | :349 `return ms` 直通；MS-T2 `assertIs`（连拷贝都会红）✓ |
| `/finance/market` 成功体/降级体均无该键 | §2.1★ / R9 | :283 剥离 + config 5 键；降级体为 `{'error':…}` 字面量 ✓ |
| 缓存域 `quote`（盘中 4/非盘 120，禁裸 TTL） | §3.3 / R6 | `_CACHE_AGE_DOMAINS:601`；`CacheAgeTests:755-762` 5 面板全断言 ✓ |
| feeds +1、`status='requires_chrome_cdp'` | RG5 / R7 | :1014-1017 ✓；MS-T10(:881) ✓ |
| 前端/小程序一致性 0.B/0.C/0.D | — | **跳过**：详设 §1.2 明确不做前端/小程序，纯后端增量 |

### D1 数据与正确性 — ✅ 通过

- **两动作语义实核**：`_fill_missing` 双循环（cache.py:1155-1161）与详设 §2.3 语义表逐行一致，MS-T9 三子断言方向正确（v1.0.1 评审纠偏后的 a=原值方向已如实落地）。
- **R18 never bare null**：键缺失/显式 null 均走 `ms is None` ⇒ error 客体（server.py:347-348）；MS-T5 同时断言 `result is not None` ∧ 错误文案。
- **无隐式状态转换、无重复数据源**：数据只经 `page_data` 唯一入口（A 类）；`market_sentiment` 权威在 CDP 页 `API_KEY_MAP`（cdp_engine 零改动，符合 R8/§1.2）。
- **B-03 边界**：`msg` 为 falsy（`''`/`0`/`None`）时回退 `'upstream_error'` 属既有 `or` 语义（本轮仅外层加 `str()`），非本次引入；可接受。

### D2 并发 — ✅ 通过

- `handle_finance_market_sentiment` 纯函数（局部变量 + 既有全局只读引用），无锁、无模块级可变状态（详设 §7）。
- **深核共享读**：与 `/finance/market`、`/finance/timeline` 并发读同一 `cls_finance` 页——`get_data` 在 `self._lock` 内构建**全新** `merged` dict（cdp_engine.py:1160-1168），顶层 `pop` 只改调用方副本；嵌套值为共享引用但所有消费方只读（`json.dumps`），写方为整体替换（`merged.update(self.cache)`）⇒ 无集合并发修改、无脏写。
- `_JSON_SHAPES`/`_PANEL_HANDLERS`/`_CACHE_AGE_DOMAINS` 导入期构建、运行期只读；测试 `patch.dict` 恢复机制标准。

### D3 资源与性能 — ✅ 通过

- 新端点 **0 次上游调用**：复用 `/finance/market` 同一 `cls_finance` 页 `page_data`（R8 单一数据源），无新 CDP 页、无新拦截 URL、无新缓存容器/池/终端缓存（§1.2）。
- 无 N+1、无大循环、无资源泄漏面（无打开句柄/无线程/无连接）。
- `/healthz?check=1` 的上游探测仅遍历 `ROUTES`（server.py:1147）——feeds 19→20 **不产生**新增健康检查请求。

### D4 安全 — ✅ 通过

- **无注入面**：handler 无参数、不消费 query/body/path 变量（path 是 `_PANEL_HANDLERS` 的静态键）；无 SQL/命令拼接；无 `eval`。
- **无越权面**：只读公开数据、无鉴权变更（详设 §10 规则六）。
- **无敏感信息泄露**：降级体 `str(exc)` 来自既有 `FetchError`（无凭据 URL）；透传体为上游行情数据。
- **无新增 urlopen**：HTTP 出口仍收敛在 `cache.fetch_json` 与 CDP 既有通道；零新增第三方依赖（R10）。

### D5 结构与可维护性 — ✅ 通过

- 7 注册点全部表驱动/集中登记（RG1–RG7），分发分支零改动零字面量（详设 §5「分发零改动」如实）；`_JSON_DISPATCHED_PATHS` 断言保证"有 shape 必有分支"。
- **同型重复不计复制粘贴反模式**：与 `handle_finance_timeline`/`handle_market_timeline` 的 8 行同构是详设明令（"逐行同型"）且为项目既有面板模式；抽公共函数反而偏离先例。
- 注释与计数同步到批（:540/:568/:1002/:1310 + config:387），命名/docstring/日志风格与兄弟 handler 一致；无上帝对象、无过度工程、圈复杂度无增量。

## 五、测试可证伪性核对（MS-T1..T16 逐条；重点 7）

判定口径：**对正确实现全绿** && **对指定回归场景必红**，两者同时成立才算通过。

| 用例 | 落点 | 对正确实现 | 回归场景 → 红的机制 | 判定 |
|------|------|-----------|---------------------|------|
| MS-T1 路由/形状登记 | MarketSentimentTests:459-468 | 4 断言 + `len==19`/`len(PANEL)==5` 全绿 | 删任一注册 ⇒ 值断言红；多注册 ⇒ 计数红（导入期 `assert:555` 先炸） | ✅ |
| MS-T2 成功透传 | :470-475 | `assertIs(result, ENVELOPE)` 绿 | handler 拷贝/包装/重命名 ⇒ `assertIs` 红（比 assertEqual 更强） | ✅ |
| MS-T3 CDP 未就绪 | :477-483 | None 与 ready=False 双态同文案 | 拆掉能力门 ⇒ 走到 `get_page` Mock → `page_data` 真实调用返回 None ⇒ 文案变 'Finance page not initialized.' → 红 | ✅ |
| MS-T4 page_data None | :485-488 | 精确文案 | 去掉 None 检查 ⇒ `data.get` AttributeError → `_guard` 体或测试抛错 → 红 | ✅ |
| MS-T5 键缺失 never bare null | :490-494 | `assertIsNotNone` + 精确 error | 返回 `None`（裸 null）⇒ `assertIsNotNone` 红；返回 `{}` ⇒ 文案断言红 | ✅ |
| MS-T6 HTTP 分发恒 200 | HttpSemanticsTests:1006-1028 | 真分发表（未 patch handler）下 200+原体 / 200+error，`http_503_total` 不动 | 任一路径非 200 或 503 计数漂移 ⇒ 红 | ✅ |
| MS-T7 cache-age 域 | :467-468 + CacheAgeTests:755-762 | 表值 'quote' + 真 `_cache_age()==policy['ttl']`（5 面板） | 域改 f10 ⇒ 两处红；`CacheAgeTests:751` 遍历整表兜底 | ✅ |
| MS-T8 `/finance/market` 已剥离 | :504-514 | `assertNotIn` + `assertIn('articles')` | **动作①回退** ⇒ extra 分支填回原值 → 红；**动作②回退** ⇒ expected 分支补 `None`（键仍在）→ 红——两个单动作分别可打红 | ✅ |
| MS-T9 剥离双动作三态 | :516-539 | (a) in+原值 (b) in+None (c) not in；:523 `assertNotIn(…, expected_now)` | 语义级锁 `_fill_missing` 三态；动作②回退 ⇒ :523 直接红 | ✅ |
| MS-T10 feeds 索引 | HealthPayloadTests:865/:876/:881 | 20/20 + status 精确 | 删条目 ⇒ 计数红；状态改错 ⇒ 精确断言红 | ✅ |
| MS-T11 HEAD + 首页 | :496-502 + :1030-1034 | 首页含路径；HEAD 200+b'' | 未登记首页/分发 ⇒ 红 | ✅ |
| MS-T12 (B-01) 真上游冒烟 | ClsPoolIntegrationTests:542-591 | **默认 skip**（类级 `skipUnless(CLS_INTEGRATION)`，setUpClass 不执行）；启用时仅断 200/no-error/stocks=list，无外网数值 | 上游 type/way/data 漂移 ⇒ 启用时红（按设计 opt-in） | ✅ |
| MS-T13 (B-02) 失败有日志 | ClsPoolTests:357-368 | `assertLogs('server','WARNING')`（logger 名实核 server.py:75）+ 文案含 'cls pool…fetch failed' | 删 `log.warning` ⇒ `assertLogs` 无记录红 | ✅ |
| MS-T14 (B-03) msg 归一 str | :370-378 | `{'code':9000,'msg':123}` ⇒ `{'error':'123'}` + `isinstance str` | 去掉 `str()` ⇒ error=int ⇒ 双断言红 | ✅ |
| MS-T15 (B-04) TTL 守卫双向 | :295-312 | ① 真源不命中 `r'ttl=\s*\d+'`（`=` 后字母，正确放行 policy 调用）② 合成 `ttl=30/60/300` 必命中 ③ 旧正则对合成串必漏 ④ `assertIn(cache_policy('plate'))` | 守卫回退旧正则 ⇒ ②红；handler 写裸 `ttl=30` ⇒ ①红——双向均封死 | ✅ |
| MS-T16 (B-05) config 注释 | :380-383 | `assertRegex(config源, r"'plate':.*4 cls pools")`（config.py:387 实核同行） | 注释回退 ⇒ 红 | ✅ |
| 计数断言同步（详设 §2.5） | :49/:465/:865/:876 | 19/19/20/20 全绿 | 任何一侧忘改 ⇒ 红（含 `_base_feed_entries` 字典化后 20 条路径唯一性） | ✅ |

**可证伪性结论：16/16 通过。** 打桩全部用 `patch.object(srv, 'cdp_engine'/'page_data'/'fetch_json')` 全限定名（无字符串 patch），HTTP 用例走 127.0.0.1 本地 `BoundedThreadPoolServer`，默认无外网/无 Chrome 依赖。

## 六、问题清单

| ID | 等级 | 位置 | 反模式 | 问题 |
|----|------|------|--------|------|
| — | P0 | — | — | **0 条** |
| — | P1 | — | — | **0 条** |
| — | P2 | — | — | **0 条** |

**不凑数说明**：以下逆向假设均已主动探测，全部**不成立或已被既有断言覆盖**，故不计入问题清单（有证据链才算问题）：

| ❓ 逆向探测 | 结果 |
|------------|------|
| `data.pop` 会污染页面缓存、导致 `/finance/market_sentiment` 被兄弟请求"误杀"？ | **不成立**——`get_data` 锁内每次新建 merged dict（cdp_engine.py:1160-1168），pop 仅作用于副本 |
| 单动作剥离回退无人守？ | **不成立**——MS-T8 端到端对①②各自回退分别必红 + MS-T9 语义级三态锁定 |
| feeds/shapes 计数有第三处消费者？ | **不成立**——全仓 grep 仅 HealthPayloadTests/ShapeTableTests 硬断言，均已同步；test_server.py 用子集断言 |
| B-04 新正则会把 `ttl=cache_policy(...)` 误判为违例（伪红）？ | **不成立**——`=` 后为字母不匹配 `\d+`；MS-T15 对真源 `assertIsNone` 正是"期望行为"锚定 |
| feeds +1 增加 `/healthz?check=1` 上游开销？ | **不成立**——`_run_health_checks` 只遍历 ROUTES（server.py:1147） |
| HEAD 执行新 handler 有崩溃面？ | **不成立**——总函数契约 + 测试进程 cdp_engine=None 早退；MS-T11-HEAD 实测 200+b'' |
| stress_all 移除键清单后丢失回归探测？ | 已覆盖——剥离回归由 MS-T8 承担（见 SIDE-EFFECT #6） |

## 七、修复建议

- **代码侧：无必须修复项（P0/P1/P2 = 0）。**
- **文档侧（不阻断代码，随 P7b 批次执行）**：见第八节漂移检测的 5 条待同步项；其中 `config.md` plate 注释为本评审**新发现漏申报项**，已输出 `>>DOC_SYNC:`。

## 八、漂移检测（P7a）

### D1 契约核对（代码实现 vs `doc/detailed/` 契约文档）

| # | 项 | 契约（文档现状） | 代码实现 | 定性 / 严重度 |
|---|----|----------------|---------|--------------|
| 1 | 路由 + shape + 分发 | server.md v1.19 §2.1:128 / §2.2:192 / assert:199 `==19` | `_JSON_SHAPES:546`、`assert:555==19`、`_PANEL_HANDLERS:573`、dispatched 断言:594 | ✅ 无漂移 |
| 2 | handler 清单与伪代码 | server.md §2.8:428/:450；详设 §5 | server.py:337-349 逐行一致（含 R18 文案） | ✅ 无漂移 |
| 3 | `/finance/market` 剥离（两动作） | server.md:426/:448；详设 §2.3 / R2 / R9 | server.py:283 + config.py:204-207 | ✅ 无漂移 |
| 4 | feeds 表 + 状态值 + docstring | server.md §2.9.1:597（`requires_chrome_cdp`，19→20）、:467（20 条 5RSS+15JSON） | server.py:1002 docstring、:1014-1017 条目 | ✅ 无漂移 |
| 5 | cache-age 表 | server.md §5.8:768 `'/finance/market_sentiment': quote`、§6.1:1801 面板 5 = 4/120 | server.py:601 + CacheAgeTests:755-762 | ✅ 无漂移 |
| 6 | 分发注释/计数注释 | 详设 §2.5 非阻断项 `server.py` 「4 panels→5」「18 JSON→19」、feeds docstring | :1310 `5 panels`、:540 `19 JSON`、:568 `5 CDP panels`、:1002 `20` | ✅ 无漂移（代码层 DOC_SYNC 已完成） |
| 7 | server.md:217 `object(12)=4 面板 + /finance/market_sentiment + …` | 枚举式表述 | 实核 object=12（5 面板+2+4 池+1）、算式含新端点 | ✅ 非漂移（表述核验通过；v1.19「5 面板」口径下该枚举式写法算术自洽） |
| 8 | config.md §3.1 plate 行注释 | config.md:306 `# cls/hotplate, cls/plate（URL 缓存，P7b）`——**缺「4 cls pools」** | config.py:387 已按 B-05 改为 `…, 4 cls pools (URL cache)` | ⚠️ **漂移（修订型）· P2/文档**——B-05 修了代码注释、其文档镜像未同步；**未在详设 §12 DOC_SYNC 清单内** → 新申报（见 D4） |
| 9 | API.md `/finance/market` 字段表 + 新端点节 | API.md:328 顶层键仍列 `market_sentiment`、:332 字段行仍在、**无** `/finance/market_sentiment` 端点节 | 代码已剥离 + 新端点已上线 | ⚠️ 漂移（缺失型+修订型）· **对外契约面 🟠**——**已申报**，待 P7b（编排层明示不属本评审） |
| 10 | README.md JSON 表 | README:58 描述仍含 "sentiment"；:56-68 表无新端点行 | 同上 | ⚠️ 漂移 · **已申报**，待 P7b |
| 11 | cdp_engine.md A 类计数 | :751「A 4 / A′ 1」、:752「A 类 4 端点」 | CDP A 类现为 5（含新端点；CDP 层本身零改动） | ⚠️ 漂移（计数型）· **已申报（P2-3）**，待 P7b |
| 12 | SAD.md 路由/面板计数 | :71-72「14 个 JSON…面板 4」、:114、:441「A（4 单体/面板）」、:560、:804「全部 14 个」 | 现状 19 JSON / 5 面板 | ⚠️ 漂移（计数型）· **已申报（P2-4）**，待 P7b（system-architect 回填；SAD 连同 4 池批次口径一并滞后） |
| 13 | API.md §6.1 面板口径「4 面板」(:686/:679/:824) | 新端点同走 quote 域 | `_CACHE_AGE_DOMAINS` 5 面板均 quote | ⚠️ 漂移（措辞型）· 轻——**已申报为「可补」**（可选项），待 P7b |

**D1 结论：代码 vs server.md/config 的结构性契约（路由/形状/handler/feeds/cache-age/计数/语义）零漂移；全部漂移集中在对外与外围文档（9–13 行），其中 4 项已申报、1 项（#8 config.md）为本评审新发现。**

### D2 `>>DOC_SYNC:` 追溯（详设 §12 登记 7 条，逐条核验 + 评审新发现 1 条）

| # | 登记的 DOC_SYNC | 现状核验 | 裁定 |
|---|----------------|---------|------|
| 1 | `API.md` → 删 `/finance/market` 字段行 + 新增端点节 + §6.1 可补 | :328/:332 仍旧、无新端点节 | ⏳ **真实需要，待 P7b** |
| 2 | `README.md` → 表补新行 + :58 去 sentiment | :58 仍旧、表无行 | ⏳ **真实需要，待 P7b** |
| 3 | `server.md` → v1.18 增量登记 + v1.19 计数收口 | **已到 v1.19**（路由/assert/feeds/cache-age/8 处 5 面板 + 3 处 19 JSON 均在） | ✅ **已完成**（P3 阶段落地） |
| 4 | `cdp_engine.md` → :751/:752 A 类 4→5 | 仍为 4 | ⏳ **真实需要，待 P7b** |
| 5 | `SAD.md` → :71-72/:114/:441/:560/:804 计数 | 5 处均仍为 14/面板 4 | ⏳ **真实需要，待 P7b** |
| 6 | `tests/stress_all.py` → 键清单移除 market_sentiment | :117 清单现为 `advance_decline/articles/anchor/live_refresh`，无该键 | ✅ **已完成**（P5a 代码层落实） |
| 7 | `china_finance_rss/server.py` → :1286 分发注释 4→5 panels | :1310 已为 `5 panels` | ✅ **已完成**（P5a 代码层落实） |
| **8（新）** | `doc/detailed/config.md` → §3.1:306 plate 行注释补 `4 cls pools` | 仍为 `cls/hotplate, cls/plate（URL 缓存，P7b）` | ⚠️ **本评审新发现漏申报项**，输出见 D4 |

### D3 规范合规 — ✅ 通过

零第三方依赖（R10）；包内相对导入；无新增 `urlopen`（HTTP 出口仍收敛 `fetch_json`/CDP）；常量/域注册集中 config（缓存域经 `_CACHE_AGE_DOMAINS` → `cache_policy`，无裸 TTL 字面量，BR-CFG-12）；`handle_*` 总函数不抛约定遵守；路由/形状/缓存域全部表驱动；测试全限定名 patch、无外网默认依赖。项目规则符合：先找模式再编码（与 `handle_finance_timeline` 同型）、一处数据只改一处（`market_sentiment` 权威在 CDP 层、本层只读）、手术式修改（未触碰无关代码）。layerIsolation 无新增跨模块边、无新增 import。

### D4 漂移结论

**代码级漂移 0 条；文档级漂移 5 条待同步**——4 条为详设 §12 已登记（API.md / README.md / cdp_engine.md / SAD.md，均经本评审复核为"真实需要、尚未执行"），1 条（config.md plate 注释）为本评审新发现、**未在登记清单内**。已完成的登记项 3 条（server.md / stress_all.py / server.py 注释）已核验落地。触发 P7b：按下列漂移表 dispatch doc agent；config.md 条目建议并入同批（同为注释镜像级、30 秒可改，不值得单开轮次）。

```
>>DOC_SYNC: doc/detailed/config.md → §3.1 `plate` 行注释（:306）补「4 cls pools」（B-05 已将 config.py:387 注释改为
  `cls/hotplate, cls/plate, 4 cls pools (URL cache)`，config.md 镜像未同步；该条未在 market_sentiment_独立接口.md
  §12 DOC_SYNC 清单内，系本次代码评审漂移检测新发现；纯注释镜像、无语义变更，建议随 P7b 批次顺带执行）
```

## 九、评审结论

实现与详设 v1.0.1 契约高度一致：剥离两动作齐备并被双层测试锁死、新 handler 与 timeline 同型、7 注册点与 19/5/20 计数零裂缝、B-01..B-05 五项修复全部按伪代码落地且可证伪、安全/并发/资源维度无新增风险面；8 条 SIDE-EFFECT（6 申报 + 2 推断）逆向核对无一例既有调用方被改坏。代码无阻断问题；残余 5 条文档级漂移全部走既定 DOC_SYNC 机制由编排层 P7b 承接（4 已申报 + 1 本评审新申报）。

| 评审结论 | ✅ 通过 | P0=0 · P1=0 · P2=0；代码级漂移 0；文档级漂移 5 条待 P7b（含 1 条新申报 config.md）；测试可证伪性 16/16 通过 |
|----------|---------|----------------------------------|

**>>DECISION: APPROVE**

**门禁预期**：`check-review.sh --name 代码评审` → 命中本报告（`market_sentiment_独立接口_代码评审.md`）→ 结论行提取上表 → **✅ 通过（exit 0）**。


