# P5a-r4 复查 · 对抗性盲审报告（收尾回路末轮）

> **模式**：`>>MODE: blind`（零上下文）· **日期**：2026-10-13 · **产出**：本文件
> **入参范围**：需求原文 = 已登记 P2-1（`handle_cls_pool` 形状漂移分支纳入 `_warn_pool_fetch_failed` 限频，保留「消息变化即时再告警」，不改返回体/状态码/缓存语义）+ P2-2（新增裸 socket 304 可证伪用例并处置旧恒真断言）+ 用户决策（**只修 P2-1+P2-2**；P2-3 episode pop 边界 / P2-4 `_reject_503` HEAD 体·注释 overclaim **仅允许注释/契约措辞澄清，禁止改行为**）。改动文件：`china_finance_rss/server.py`、`tests/test_server_http.py`；只读契约核对：`doc/detailed/cls_pools.md`(v1.0.5)、`market_sentiment_独立接口.md`(v1.0.5)、`server.md`(v1.22)；`>>DIFF` 客观摘要。
> **零上下文纪律**：未参照任何修复设计理由、P5b/P6c 评审结论与测试报告；所有判断仅以**当前源码、测试、契约原文**为证据（探索中命中的同名历史文件内容一律不作依据）。
> **执行限制（如实披露）**：本会话无 shell 工具 ⇒ 无法执行 `git diff` / 测试套件；「全量 570 tests OK (skip=4)」**未获执行级自核**，本报告以逐行静态实核替代（见 §5 遗留核验项）。

## 一、修复副作用逆向表（`>>SIDE-EFFECT` 未携带，按 `>>DIFF` 推断；含模块标注，供 tester `>>SCOPE:`）

| # | 受影响点 | 模块 | 逆向假设（会破坏谁？） | 实核结论 |
|---|---|---|---|---|
| SE-a | 形状分支 `log.warning` → `_warn_pool_fetch_failed(pool_type, f'unexpected…{shape}')`（server.py:541-542） | server/handler | ① 消息文本变化 → 是否有断言/抓取器锁旧格式？② 限频后首条告警是否仍必发？ | ① 形状测试只匹配 `'shape'`/`'dict'` 子串（tests:566），返回体断言（tests:540-543、577-581）逐字未变；except 路径格式由 MS-T13 锁定（tests:381-382）不受影响 → **证伪**。② 表被 clear（tests:559）⇒ `prev is None` 短路不成立 ⇒ 首条必发（server.py:489-493）→ **证伪**。 |
| SE-b | 形状路径开始写 `_pool_fetch_warned_at`（server.py:492） | server/state | ① 兄弟用例未隔离被污染 → 伪红？② 与 except 路径共用 pool_type 键 → 互相覆盖/误抑制？③ 与 episode pop 交互？ | ① 全文件排查触碰该表的 8 处（tests:347/371/393/444/481/527/558/1351）均 save/clear/finally；其余触碰 pool 的用例只走 list 成功（pop，无害）或已隔离异常路径 → **证伪**。② 抑制条件 = 同 pool **同消息**（server.py:489），异消息必告警 ⇒ 不存在「互相吞信号」的少告警路径；反向最坏 = 跨消息交替时每次翻转告警一次（上界 = 翻转频率，见 H1）→ **误抑制证伪 / 交替上界登记**。③ 形状 `return`（:543）在 `pop`（:549）**之前** → **成立（正确）**。 |
| SE-c | 删 3 处恒真 `body==b''`（tests:2028-2030/2097-2098/2137-2139 原地注释）+ 新增 `test_304_body_never_reaches_the_wire` | tests/coverage | 覆盖真空：其余 304 `body==b''` 是否仍恒真？处置是否完整？ | **成立 → P2-01**（实测 10 处残留 + 契约登记计数不符）。 |
| SE-d | `server.py:466-472`（episode 注释）/ `:1613-1626`（O1 注释收窄） | server/docs | P2-3/P2-4 是否夹带行为改动？ | **证伪（确为纯注释）**：成功路径才 `pop`（:549，`code != 200` :531 与形状 :543 均在其前 return）；`_reject_503` 仍无条件写体（:1766-1770）；`_send_text` 守卫行（:1627）未动；与 `>>DIFF`「仅注释」声明一致。 |

## 二、对抗性假设与实核（逐条给证据，不采信自报）

| # | 对抗性假设（/任务书指定逆向点） | 实核证据（文件:行） | 结论 |
|---|---|---|---|
| H1 | 形状↔异常交替抖动 → 消息频繁翻转 ⇒ 每次翻转即时告警，日志量是否重新随 RPS 放大？ | 翻转由回源节奏决定：成功响应缓存于 plate TTL（server.py:521 `cache_policy('plate')`）、失败负缓存 `NEG_TTL=5s`（cache.py:818-820 同 kind 复读）；同形同消息仍受 30s 窗口抑制（:489-491） | **部分成立（已知上界，非缺陷）**：单池告警 ≤ min(RPS, 回源/翻转频率)，与 RPS 解耦，满足 P2-1 核心要求；「同 episode 内跨消息交替可突破 1 条/30s」如实登记为上界（H4 补充） |
| H2 | 消息内嵌 shape 名是否**真**保留「变化即告警」？ | `shape = type(data).__name__`（:534）→ JSON 可解析值域使 shape ∈ {dict, NoneType, str, int, float, bool}，与消息一一映射；f-string 先行插值（:542）再走 `%s` 参数化（:493），无格式符风险 | **成立**；同**类型**不同结构的漂移共用一条消息（30s 内静默）——契约口径为「按 type」（cls_pools.md:409 `<type>`），非缺陷 |
| H3 | 形状分支是否真在 **pop 之前 return**？ | :543 `return {'error': …}` → :549 `_pool_fetch_warned_at.pop` 仅在成功分支（:550 return 之前） | **成立（正确）**；与 P2-3 注释（:466-472）自洽 |
| H4 | 形状与 except **共用同一表/键**是否产生误抑制或互相覆盖？ | 抑制 = `prev[1] == msg ∧ Δt<30s`（:489-490）；写入无条件覆盖（:492）。except 消息 `str(exc)`（:523→486），形状消息恒以 `unexpected upstream data shape` 起始（:542）——两族消息不可能相等 | **误抑制证伪**（异族消息必告警；同族同消息本就该抑制）；**覆盖只影响窗口归属**：形状写入会截断 except 同消息的剩余窗口，令下一次 except 更早告警（多告警方向，无少告警）→ 记录不阻断 |
| H5 | episode pop 交互：形状/code≠200 是否错误结束 episode 或漏重新武装？ | 仅 :549 pop；形状 :543、code≠200 :531、malformed :529、except :524 均不 pop | **成立**；MS/POOL 系用例（tests:469-506、548-584）逐段锁定「失败不 pop / 成功 pop / 新 episode 必告警」 |
| H6 | 限频表键是否可能越出 `_POOL_TYPES` ⇒ 无界增长？ | 枚举闸 :507-508 位于一切触网与写表之前；两调用点 :523/:541 均在其后 | **证伪（有界 ≤4 键）** |
| H7 | 新 304 用例是否 hermetic（Host 分键 / ETag 跨表示 / 顺序污染）？ | 两次裸交换同 `Host: 127.0.0.1`（tests:1842）；ETag 从**裸响应**取并 `strip()` 掉 CR（:1940-1944）；`setUp`/`addCleanup` 清 `feed_cache`、`_feed_fetch_locks`、`_feed_fetch_refs`（:1797-1803）；handler 经 `patch.dict` 出域还原（:1816-1817）；HTTP/1.0 close-delimited 读至 EOF 确定（:1839、:1848-1855），断言 `HTTP/1.0 304`（:1945）同时钉死协议 | **证伪（真 hermetic）**；ETag 取法显式规避了「裸 Host 无端口 vs `http.client` 带端口 ⇒ base_url/atom:link 不同 ⇒ 合法 200 冒充」的假绿路径（:1935-1939 注释属实） |
| H8 | 新 304 用例是否**真可证伪**？ | GET 自证读法非恒真（:1932-1934 断 200 + 非空体）；304 线上体断言（:1946）+ 无 `Content-Length`（:1947）；全仓唯一 304 出口 = `_send_not_modified`（server.py:1535 调用 / :1647 `send_response(304)` / :1661 无 wfile 写） | **证伪（真可证伪）**：向该出口补一次 `wfile.write` 或补 `Content-Length` 即红；单出口论证成立（GET 覆盖可外推 HEAD-304，因 `_serve_feed` :1534-1537 与方法无关） |
| H9 | 删 3 处是否造成覆盖真空（**全文件排查其余 304 恒真断言**）？ | 全文件 `assertEqual(<body*>, b'')` 穷举：:1910/:1956/:1971/:2003/:2008/:2247/:2287/:2321/:2350/:2452 共 **10 处**均紧邻 `status == 304` 断言且全部经 `http.client`（`_req` :1819-1828 / 直连 conn :2441-2447），CPython `HTTPResponse.begin` 对 304 归零读长 ⇒ 恒真；另 :2147（HEAD 200）同型恒真（P2-6 家族） | **成立 → P2-01**；其中 3 处（:2028/:2097/:2137）已删+注释，10 处无任何注释/登记处置 |
| H10 | P2-3 / P2-4 是否**确为纯注释**（有行为改动即报）？ | 见 SE-d：pop 位置、`_reject_503` 无条件写体、O1 守卫行均与「仅注释」一致；O1 新注释两条旁路逐条核真——CPython `send_error` 自带 `if self.command != 'HEAD'`，`_reject_503` 由 `process_request` 在读请求行前触发（:1783-1799，方法未知） | **成立（纯注释，且新注释无 overclaim）** |
| H11 | 契约文档与代码是否漂移？ | 行号类全部核对一致：`server.py:477-493`（限频器）/:541-542（形状调用）/:549（pop）/:523（except 调用）/:530-531（B-03）/:496-550（下游提示）；tests `:548`（形状限频）/:1920-1947（304 裸用例）/:1280（MS-T20）。**漂移 3 处** → P2-01附注（server.md 残留计数）、P2-04、P2-05 | **部分成立** |
| H12 | 是否另有**同型未发现缺口**（fail-loud 可观测性）？ | `not isinstance(raw, dict)`（:528-529）与 `code != 200`（:530-531）返回 error 体但**零日志、零限频表写入**；对照本轮刚被点亮的形状分支（:541）与 except 分支（:523） | **成立 → P2-02** |
| H13 | 测试顺序/全局态污染（形状写表是否波及其他断言）？ | 见 SE-b①；`assertNoLogs` 段内仅 handler 自身可达（fetch 已 patch，:568-569） | **证伪** |

## 三、问题清单（6 条，均附证据链 / 影响 / 修复方向）

【P2】`tests/test_server_http.py:1910,1956,1971,2003,2008,2247,2287,2321,2350,2452`: P2-2 的旧恒真断言**处置不完整**——全文件仍有 10 处对 304 响应断言 `body == b''`，全部经 `http.client`（CPython `HTTPResponse.begin` 对 `NOT_MODIFIED` 归零读长 ⇒ `resp.read()` 恒 `b''`），**服务器真写体它们也绿**；本轮只删了 3 处（:2026/:2093/:2130 区域，注释 :2028-2030/:2097-2098/:2137-2139 指向新裸 socket 用例），其余 10 处既未删也未加恒真注释。
- 证据链：当 `_send_not_modified`（或未来第二个 304 出口）写入 body 时 → 这 10 处断言全部保持绿色、读者误以为「该场景已有无体保障」，因为断言读的是 client 归零后的长度而非线上字节（tests:1819-1828 `_req` = `http.client`；:2441-2447 同）。
- 附带：`:2147`（`b_none`，HEAD 200）同型恒真，属 P2-6 家族，一并登记。
- 影响：伪绿残留 + 新用例 docstring（:1923「本文件里所有对 304 断言 `body==b''` 的用例都是恒真」）与「只处置 3 处」的实际动作不一致；**可证伪覆盖本身已由 SRV-T75 承担（单出口论证成立，见 H8），故不构成覆盖真空，仅是处置与登记未收口**。
- 修复方向：对 10 处逐一按 T52/T52b/T54 已用模式处置——删除断言 + 原地一行注释指向 `test_304_body_never_reaches_the_wire`；或保留但改为头部断言并标注「body 恒真、无区分度」。**兜底**：若编排层裁定「头部断言已兜底、保留现状」，则必须在 `server.md` §8 对应行逐行补恒真提示。

【P2】`china_finance_rss/server.py:528-531`: 同型（fail-loud 可观测性）缺口——`raw` 非 dict（`:529`）与 `code != 200`（`:531`）两条失败分支返回 `{'error': …}` 但**零日志、零限频表写入**，与本轮刚纳入限频的形状分支（`:541-542`）、except 分支（`:523`）形成「四条失败路径、两条有声、两条全静默」的不对称。
- 证据链：当上游持续返回 `{"code":9000,"msg":"param error"}`（如 `way` 参数被上游废弃）→ 每个请求走 :531 返回 error 体、响应 200 → **服务端无任何 WARNING/限频表痕迹**（全路径无 `log.*`），日志侧告警完全失明，只能靠下游读 error 字段发现；`malformed upstream response` 分支（:528-529）同理。
- 影响：上游契约漂移的可观测性盲区（业务码漂移恰是本仓库历史上真实踩过的形态）；契约侧 `cls_pools.md:407-408` 目前也只要求 error 体、未要求日志 ⇒ **代码符合契约、属契约级缺口**。
- 修复方向：**超出本轮批准范围（属行为改动）**——建议登记为下轮需求：`code != 200` / 非 dict 信封同样调用 `_warn_pool_fetch_failed(pool_type, …)`（消息分别含业务码/信封类型），纳入同一限频；本轮仅登记不改码。
- **兜底**：若维持静默，契约应显式写「这两条分支有意不打日志（error 体即信号）」，避免后人再按 P2-1 口径误判为缺陷。

【P2】`tests/test_server_http.py:1227-1252` 与 `:1830-1859`: 两份 `_raw_exchange` 裸 socket 读法**复制并存**且签名不一致（前者 `(method, path)`，后者多 `headers`），新 docstring（:1833）宣称「Same reader as `HttpSemanticsTests._raw_exchange`」但二者是独立拷贝而非共享实现；同时 `:1257-1262` 的 docstring 仍称「MS-T11 / SRV-T33 用 `http.client` 断言 `body == b''`」——**与现实矛盾**（MS-T11 :1218-1225、SRV-T33 :1132-1142 均已无 body 断言，见 :1133/:1220 自注）。
- 证据链：当未来协议升级（如 `protocol_version='HTTP/1.1'` keep-alive）或读法需修正时 → 只改一份，另一份静默失效（read-until-EOF 将挂满 5s 超时后靠 `socket.timeout` 兜底截断，:1851-1853），因为两处是逐行拷贝、无共同调用点；陈旧 docstring 则误导维护者以为这两处仍有 body 断言。
- 影响：D5 复制粘贴 + 注释与实现漂移（可维护性/误导性）。
- 修复方向：提升为模块级共享 helper（如 `raw_exchange(port, method, path, headers=None)`），两处类方法转调；同时把 :1257-1262 首句改为过去式并指向现行断言状态。**兜底**：至少删改陈旧首句，保留双拷贝。

【P2】`doc/detailed/cls_pools.md:291`（§5 伪代码）: 枚举闸写作 `if pool_type not in _POOL_TYPES:`，**缺代码实有的 `isinstance(pool_type, str)` 前置**（`server.py:507`）。
- 证据链：当按伪代码施工/核对者传入不可哈希 `pool_type`（如 `['up_pool']`、`{'x':1}`）→ frozenset 成员测试直接 `TypeError: unhashable type`，破坏「总函数绝不抛」（BR-POOL-8）与 POOL-T9 的实测口径（tests:586-594 断言 list/dict/set 均返回 error 且不触网）；现实现靠 :504-506 的 isinstance 闸避免。
- 影响：契约伪代码与实现、与既有测试三方不一致（v1.0.5 本轮同步 §5 时未一并收口）；BR-POOL-9 行（cls_pools.md:402）与 POOL-T9 行（:445）也只列了 str 类/None，未登记不可哈希用例。
- 修复方向：§5 该行改为 `if not isinstance(pool_type, str) or pool_type not in _POOL_TYPES:`（与 :507 逐字对齐），BR-POOL-9/POOL-T9 补「不可哈希」枚举。**兜底**：在 §5 加一行「伪代码省略 isinstance 闸，以 `server.py:507` 为准」。

【P2】`doc/detailed/server.md:1994`（§8 SRV-T33 行）: 描述为「`do_HEAD` `/stock/data?code=…` 400 路径 ⇒ 响应无 body（`Content-Length: 0` 或空）」，与映射测试 `test_head_writes_no_body`（tests:1132-1142，类 docstring :1104 明示 SRV-T33）不符——实际覆盖 `/`、`/market/margin?market=bogus`、`/nope` 三条路径，且按 P2-6 **只锁状态码、无 body 断言**（:1133-1137）。
- 证据链：当读者按 SRV-T33 行去找 `/stock/data` HEAD 用例或以为存在「无 body 断言」→ 找不到/误判覆盖面；线上无 body 保证实际由 MS-T11b 同源裸用例（:1254-1278，含 `/market/margin?market=bogus`）与 MS-T20 内在守卫承担。
- 影响：契约-测试映射漂移（pre-existing，本轮 server.md v1.22 更新 §8 时未顺带收口）。
- 修复方向：SRV-T33 行改为实际三路径 + 注明「body 断言已删（P2-6 恒真），线上保证由 MS-T11b/MS-T20 承担」。**兜底**：仅在行尾加一句现状注。

【P2】`china_finance_rss/server.py:477,480-484`: `_warn_pool_fetch_failed(pool_type, exc)` 形参名为 `exc`，第二调用方（:541-542）实传 **plain str**；docstring 首句「The message format is unchanged (`… fetch failed: <exc>`), so log scrapers and MS-T13 keep matching」只对 except 路径严格成立——形状路径的行文是本轮**新路由进来的**（不再是旧的直写格式），「unchanged」的适用范围未限定到调用方。
- 证据链：当后续维护者按 `exc` 语义加 `exc.args`/`type(exc).__name__` 之外的 Exception 专有访问 → 对 str 实参 `AttributeError`，而该函数位于「总函数绝不抛」（BR-POOL-8）路径上，一次 `AttributeError` 即击穿降级契约；「unchanged」表述则可能让抓取器变更评审误以为形状告警行文从未变过。
- 影响：可维护性/注释精确性（当前实现只用 `str(exc)`，**今日无实际缺陷**）。
- 修复方向：形参改名 `reason`（或 `msg_or_exc`），docstring 首句限定「except 调用方的消息格式不变；形状调用方为本轮新入（cls_pools.md §5 登记）」。**兜底**：仅在 docstring 补限定从句。

## 四、定级说明

- **P0 = 0**：无崩溃 / 数据丢失 / 资金 / 安全面。形状分支返回体逐字未变（:543 vs 契约 `cls_pools.md:409`）、except/成功返回体未动（:524/:550）、状态码与缓存语义未动；新用例不触网、不写共享态（除只读）。
- **P1 = 0**：无功能缺陷/单点/性能退化。
  - 限频**真生效**：形状判定每请求重跑但告警经 :489-491 同消息窗口抑制，日志量与 RPS 解耦（H1 上界 = 回源/翻转频率，非 RPS 线性）；键有界（H6）；pop 前 return（H3）；无误抑制（H4）。
  - 新 304 用例**真 hermetic、真可证伪**（H7/H8），且单出口论证成立 ⇒ 残留恒真断言**不构成覆盖转移失败**，仅是处置/登记未收口。
  - P2-3/P2-4 **确为纯注释**（H10），未越权改行为。
  - 静默分支（P2-02）符合现行契约（`cls_pools.md:407-408` 只要求 error 体），且修复需行为改动、超出本轮批准范围 ⇒ 按「登记不阻断、交编排层决策」处理。
- **P2 = 6**：均为可维护性 / 契约-代码-测试一致性 / 观测性登记类——测试恒真断言残留（1）、同型观测缺口登记（1）、复制 helper + 陈旧注释（1）、伪代码漂移（1）、SRV-T33 行漂移（1）、形参/注释措辞（1）。

## 五、评审结论表

| 维度 | 结论 | 关键证据 |
|---|---|---|
| P2-1 形状告警纳入限频 | ✅ 通过 | `server.py:541-542` 改调限频器；`:489-493` 同池同消息 30s 抑制、异消息即时；`:543` pop 前 return；消息含 `type(data).__name__`（:534）；测试 `tests:548-584` 四段可证伪（改回直写 `log.warning` ⇒ repeat 段 `assertNoLogs` 红） |
| P2-1 返回体/状态码/缓存语义不变 | ✅ 通过 | :543 错误串与 `cls_pools.md:409` 逐字一致；除 :541-542 外无其它行为面改动（按 `>>DIFF` + 当前码核验） |
| 共键/episode/键值域逆向 | ✅ 证伪缺陷 | H3/H4/H5/H6 |
| 交替抖动上界 | ⚠️ 已知上界（非缺陷） | H1：上界 = 翻转频率（plate TTL / NEG_TTL=5s），非 RPS |
| P2-2 新 304 用例 | ✅ 通过（hermetic + 可证伪） | H7/H8；`server.py:1535/:1647/:1661` 单出口实核 |
| P2-2 旧恒真断言处置 | ⚠️ 不完整 → **P2-01** | H9：10 处残留（+1 HEAD），仅处置 3 处 |
| P2-3 / P2-4 纯注释纪律 | ✅ 通过 | H10；O1 新注释两条旁路核真、无 overclaim |
| 契约文档一致性 | ⚠️ 3 处漂移 → P2-01附注 / P2-04 / P2-05 | H11（行号类全部一致） |
| 测试全绿自核 | ⚠️ **未获执行级证实** | 本会话无 shell 工具，无法运行 570 用例；静态层面新/改用例逻辑、隔离（save/clear/finally）、确定性逐条核过，未发现伪红/伪绿路径 |

**遗留核验项（不阻断，交编排层/tester）**：① 实际执行 `python -m unittest discover -s tests -v`（或 `bash .opencode/scripts/check-changed.sh`）复证「570 tests OK (skip=4)」；② P2-01 的 10 处断言处置与 `server.md` §8 登记计数（现写「残留 7 处」，实测 10 处）一并收口；③ P2-02 是否升级为下轮行为改动需求，由编排层裁定。

**问题计数：P0=0 / P1=0 / P2=6；最严重项** = 10 处仍恒真的 304 `body == b''` 断言（P2-2 仅处置 3/13，且 `server.md` v1.22 登记的「残留 7 处」与实测 10 处不符——处置与登记双未收口）。

>>DECISION: APPROVE



