# 对抗性盲审报告 — P5a-r3 复查（钟源 monotonic / episode pop / `_send_text` HEAD 守卫）

> **编号** BLIND-REV-20261010-003（P5a-r3 复查）· **模式** P8 对抗性盲审（`>>MODE: blind`）· **日期** 2026-10-10
> **入参范围（零上下文）**：需求原文 = `doc/review/P5a-r1复查_对抗性盲审报告.md` §二「问题清单」**仅 P2 条目**（HEAD-400 覆盖 / 契约登记 / 墙钟 / episode 盲区 / 用例硬编码消息；其结论与评审批注已忽略）；改动文件 `china_finance_rss/server.py`、`tests/test_server_http.py`（**2 个**）；`>>DIFF` 客观摘要；契约文档**只读核对**。
> **纪律声明（污染披露）**：B1 双盲——先读需求原文、后读源码与测试。入参本身未混入中间产物；但本人为定位符号执行的仓库级 grep **会话性回显**了 `doc/review/`、`doc/tester/` 下前几轮报告的行片段（工具副作用，非入参污染）。下列全部发现均可回溯到 `server.py` / `tests/test_server_http.py` / `cache.py` / `config.py` 与 CPython 3.12 `Lib/http/client.py` 的**实读行号**，未以任何前轮评审结论或测试结果作证据；如编排器判定该副作用不可接受，可要求换检索方式重跑。
> **审查基线**：假设本轮 3 处修复（钟源 / episode / HEAD 守卫）必有副作用与盲区；逐条逆向，站不住的假设如实记「证伪」，不为凑数造问题。

## 〇、修复副作用逆向检查（入参无 `>>SIDE-EFFECT:`，从 `>>DIFF` 推断；按模块标注供 tester `>>SCOPE:` 定向回归）

| # | 受影响点 | 模块 | 行为变化 | 逆向假设 → 实核结论 |
|---|---|---|---|---|
| SE-1 | `server.py:478` 限频表钟源 `time.time()` → `time.monotonic()` | server | 表内存单调读数，窗口成纯间隔 | ① 有无其它读者把 `last_ts` 当墙钟解读？全仓触点仅 `:467/:477/:478/:482/:533` + 测试播种，无 metrics/admin/持久化解读 → **证伪**；② 同表有无遗漏的墙钟取时点？该表唯一取时即 `:478` → **证伪**；③ 同文件其它**区间**墙钟是否遗漏？`server.py` 余下 `time.time()` 仅 `:139`（RSS `pubDate` 绝对时刻）与 `:1298`（访问日志日期），改单调反而错 → **证伪**；④ 跨模块同型墙钟**区间**限频仍在（`cdp_engine.py:1257` chrome 重启节流）→ **成立（观察，他模块他契约，登记不阻断）** |
| SE-2 | `server.py:533` 成功路径新增 `_pool_fetch_warned_at.pop(pool_type, None)` | server | 一次全成功清掉该池告警条目 | ① 破坏哪个既有调用方？表仅 `_warn_pool_fetch_failed` 一个读者、无其它消费者 → **证伪**；② 相邻分支仍自洽？`code!=200`(`:520-521`) 与形状错误(`:523-527`) 是**传输成功**却不 pop、也不告警 → **成立（→ P2-3）**；③ pop 异常面？`dict.pop(k, None)` 无抛出路径、键恒为 enum gate(`:497`) 后的 str → **证伪**；④ 有界性？pop 只减不增，键 ⊆ `_POOL_TYPES` → **证伪（仍 ≤4 键）** |
| SE-3 | `server.py:1604` 写体条件 `if write_body:` → `if write_body and getattr(self,'command',None) != 'HEAD':` | server（HTTP 出口） | HEAD + `write_body=True` 不再上体 | ① 破坏存量调用方？`do_HEAD`(`:1303-1305`) 全链已传 False、`do_GET`(`:1309-1311`) 为 True ⇒ 存量只是恒真/恒假叠加 → **证伪**；② 头部/CL 是否仍自洽？守卫位于 `end_headers()`(`:1596`) **之后**、唯一动作是抑制 `wfile.write`(`:1605`) → **证伪**；③ 依赖「无 `command` 也写体」旧行为的调用方？`GzipResponseTests._fake_handler`(`:1552-1563`) 用 `RSSHandler.__new__` 且从不设 `command`，默认 `None != 'HEAD'` ⇒ 照旧写体 → **证伪（向后兼容）**；④ HEAD 无体规则是否真的全覆盖？`_reject_503`(`:1740-1747`) 不经 `_send_text` → **成立（→ P2-4）** |
| SE-4 | 测试 MS-T17 播种 `time.time()-GAP-1` → `time.monotonic()-GAP-1`（`tests/test_server_http.py:418-419`） | tests | 过期种子改单调基准 | ① 引入跨钟比较？播种与实现同钟 → **证伪**；② 是否丢覆盖？实现若回退 `time.time()`，单调种子对 epoch 钟是「远古」⇒ 仍判过期 ⇒ **MS-T17 过期段不再区分钟源**，该维度移交 MS-T18(`:463` 存值==1040.0) → **部分成立（覆盖转移，非缺陷，见 H7a）** |
| SE-5 | 新增 MS-T18(`:429`) / MS-T19(`:468`) / MS-T20(`:1234`) 三条用例 | tests | +3 用例、类级 patch + 裸 socket | 逐条 hermetic/可证伪实核见 H7；三条均自带 save/clear/finally 恢复 → **证伪（无线程/顺序污染）** |
| SE-6 | 常量注释块新增 8 行（`server.py:450-465`） | server | 注释声明单调钟 + episode 语义 | 与实现逐句互证（`:478`/`:533`）；但 `:452-453` 仍写无条件的「one warning per `_POOL_FETCH_WARN_GAP` per pool_type」——pop 后真实上界是「每 episode」，周期可被 plate TTL(12s, `config.py:387/:473`) 压到 GAP 之下 → 并入 **P2-3 影响面**，不单列 |

## 一、对抗性假设 → 实核结论（B2；逐项给证据，站不住的照记「证伪」）

| # | 预设「必有问题」的假设 | 实核证据（源码实读） | 结论 |
|---|---|---|---|
| H1 | 单调钟替换遗漏其它墙钟调用方 / 造成跨时钟比较 | `_pool_fetch_warned_at` 全仓触点 = `server.py:467`(定义)/`:477`(读)/`:478`(唯一取时)/`:482`(写)/`:533`(pop) + 测试播种/断言；无任何第二写入方，无消费方把 `last_ts` 当 epoch 解读（不进 metrics、不落盘、不跨进程）⇒ 不存在「monotonic 减 epoch」的混钟算式 | **证伪** |
| H2 | 与 `stock_api` 既有墙钟限频风格不再一致 = 缺陷 | 两表分属不同模块、不同键、无共享读写点（全仓 grep 无交叉），风格差异不产生任何行为后果；且本模块 `_fetch_concurrent`(`:1187/:1197/:1200`) **早已用 `time.monotonic()` 测区间** ⇒ 新改法与 `server.py` 自身既有区间风格一致。「不一致」只跨文件存在，属可读性债。真正同型的墙钟**区间**残留是 `cdp_engine.py:1257`（他模块、他契约、不在本 diff） | **证伪为缺陷**（记可维护性备注，见 SE-1④） |
| H3 | 成功 pop 与并发 / 有界性 / 其它池语义冲突 | 键恒 ∈ `_POOL_TYPES`（enum gate `:497` 先于一切网络动作）⇒ 有界 ≤4 不变；4 池各键独立、pop 只清本池；GIL 下 `dict.pop/get/setitem` 原子，最坏竞态 = 失败线程在 `:482` 的写**晚于**成功线程的 pop ⇒ 成功后残留旧 `(ts,msg)`，30s 内同 msg 失败被静默（漏 1 条日志），与 `:454` 既登的 `lock-free (tolerated race)` 同口径 | **证伪为新缺陷**（残留竞态=已登记容忍项） |
| H4 | 遗漏其它成功返回分支（`data == []`、非 except 业务失败/形状错误） | `data == []` 与其它成功共用 `:534` 同一 return（`raw.get('data')` 是 `[]` 时 `:523` 通过 ⇒ 照样 `:533` pop，MS-T19 恰以 `data:[]` 驱动）⇒ **已覆盖**；enum-gate 错误(`:498`) 不触网、不该 pop ⇒ 正确；`code!=200`(`:520-521`) 与形状错误(`:523-527`) 是 `try` 之外的**传输成功**却既不 pop 也不告警 ⇒ 这两条正是 episode 语义的边界盲区 | **部分成立 → P2-3**；`data==[]` 子项证伪 |
| H5 | HEAD 守卫影响非 HEAD 路径 / Content-Length / gzip / 304 | 逐项：① GET 等 `command != 'HEAD'` 恒真 ⇒ 条件与旧 `write_body` 等价；② 头部（CL/`Content-Encoding`/ETag/Last-Modified/Vary/Cache-Control）全部在 `end_headers()`(`:1596`) 之前发出 ⇒ 逐字不变，HEAD 按 RFC 9112 §9.3.2 保留 GET 形头部（Content-Length>0）；③ gzip 在守卫**之前**(`:1564-1567`) 仍压缩 ⇒ HEAD+gzip 白压一次，但旧路径 `write_body=False` 同样如此 ⇒ **非本轮引入的既有开销**（登记：可在压缩前对 HEAD 早退，省 CPU）；④ 304 走独立 `_send_not_modified`(`:1607-1638`)，不经 `_send_text` ⇒ 零牵连，但该路径**无守卫也无有效测试** ⇒ 残留并入 P2-2 | **整体证伪**（①②④ 逐项有据；③ 记观察） |
| H6 | `getattr(self,'command',None)` 默认值语义有坑 | 默认 `None` ⇒ 照旧写体 = 向后兼容；生产侧 `handle_one_request → parse_request` 必先解析出 `self.command` 才进 `do_HEAD/do_GET`，且本服务 HTTP/1.0 无 keep-alive（一连接一请求）⇒ 无「上一请求残留 command」；反向推演：默认若改成「缺失即抑制」或直接属性访问 `self.command != 'HEAD'`，`GzipResponseTests`(`:1552-1563`，`__new__` 无 `command`) 中 8 条断言体存在的用例（`:1594/:1605/:1644…`）将全红 ⇒ **现默认值被既有用例保护**。残留备注：守卫是 **fail-open**（缺 `command` 就写体），其安全性依赖「生产必有 `command`」这一前提，目前仅由 MS-T20 端到端（真实 server，`command` 已置）覆盖，无单元级用例钉住默认分支 | **证伪**（fail-open 备注记结构观察，不入清单） |
| H7 | 三条新用例不 hermetic 或不可证伪 | 见下方 H7a/H7b/H7c 三行逐条 | 见各行 |
| H8 | 同文件还有其它恒真断言 / 全局态顺序耦合 | ① 304 的 `body == b''` 五处（`:1833/:1922/:1989/:2029/:2341`）经 CPython 原文证实恒真 → **成立（P2-2）**；② `_pool_fetch_warned_at` 写入方共 6 处模板（`:346/:370/:392/:443/:480/:1305`）全部 save/clear/finally 恢复，类内字母序下所有会走 except 路径的用例都在隔离之列，`:522` 形状断言走**直写** `log.warning`（不经限频表），`test_empty_list…`(`:526-528`) 的成功分支虽 pop 但该用例不断言表 → **证伪（无残留顺序耦合）**；③ `test_head_request_content_length_matches_compressed`(`:1624-1634`) 的 `getvalue()==b''` 断的是 `write_body=False` 参数路径且**可证伪**（改 True 即红），非恒真 → **证伪** | ①**成立**；②③证伪 |

| H7a | **MS-T18** `test_rate_limit_window_uses_monotonic_clock`(`:429-466`) 不 hermetic / 不可证伪 | *hermetic*：`saved/clear/finally恢复`(`:443/:465-466`)，`patch.object(srv.time,'monotonic')` 用 `with` 自动还原。*可证伪*（自行推演双路）：实现若仍读 `time.time()` ⇒ 注入钟(`1000/1010/1040`)永不可达 ⇒ 第三段 `assertLogs`(`:460`) 找不到记录 **红**，且 `:463` 存值为 epoch ≠ `1040.0` **红**；实现若改读 `perf_counter()` 同理红。*残留*：`patch.object(srv.time,'monotonic')` 打的是 **stdlib 模块级属性、进程全局生效**——实核当前隔离：`ClsPoolTests` 自身无服务器 fixture，类按 `dir()` 字母序排在 `HttpSemanticsTests`/`RssConditionalGetTests` 之前，后者的 `setUpClass` 服务器在各自 `tearDownClass` 关闭，注入窗口内无其它存活线程调用 `time.monotonic()` ⇒ **今天安全**（结构性备注：日后若引入常驻后台线程，冻结/回跳的注入钟会污染其区间计算） | **证伪**（全局 patch 记结构备注） |
| H7b | **MS-T19** `test_success_clears_the_warn_episode`(`:468-505`) 不可证伪 | 序列 = fail 告警(`:489-490`) → 同 fail 静默(`:491-492`，依赖真实 monotonic 30s 窗口，毫秒级执行安全) → 成功 stub `{'code':200,'data':[]}`(`:494-497`) → `assertNotIn('up_pool', …)`(`:498`) → 再 fail 必告警(`:499-501`)。**删掉 `server.py:533` 的 pop** ⇒ 表里仍留 `(t, 同 msg)` 且在 30s 内 ⇒ 末段 `assertLogs`(`:500`) 无记录 ⇒ **红**；只删 `:498` 断言则前三段仍能抓住 ⇒ 断言非装饰。hermetic 同 H7a 模板 | **证伪（真可证伪 + hermetic）** |
| H7c | **MS-T20** `test_head_guard_is_intrinsic_to_send_text`(`:1234-1260`) 不可证伪 / 不 hermetic | `leaky`(`:1250-1251`) 忽略 `do_HEAD` 传入的 `write_body=False` 并强制 `True`，正是「未来忘传参的调用点」的等价模拟；裸 socket `_raw_exchange`(`:1181-1206`) 先 GET 自证读法非空(`:1254-1255`) 再断 HEAD `body==b''`(`:1258`) 且 `Content-Length>0`(`:1259-1260`)。**删掉 `:1604` 的 `!= 'HEAD'`** ⇒ 体上线 ⇒ `:1258` 红；反之若把读法改成 `http.client` 就退回恒真（GET 自证正是防这个）。patch 作用域在 `with` 内、连接逐次关闭 ⇒ hermetic。唯一结构备注：`patch.object(RSSHandler,'_handle_request')` 是**类级** patch，套件改为并发跑测试时会波及同进程其它请求——现行串行 `unittest discover` 下不成立 | **证伪（可证伪 + hermetic）** |
| H9 | 非 except 的业务失败 / 形状错误路径「本轮该动而没动」 | 需求原文（r1 §二 P2-4）只要求「恢复后再失败须再告警」；实现把恢复点定义在**全成功 return**。`code!=200` / 形状错误这两条同样是传输恢复信号，却不 pop（且这两条路径自身既不告警也无退避）⇒ **成立，落 P2-1 / P2-3** | **部分成立** |
| H10 | 契约文档与本轮代码漂移（Dim 0 只读核对） | `market_sentiment_独立接口.md` §5.5(`:281-297`) 已同步 `now = time.monotonic()` 与 `pop(pool_type, None)`，标注行号 `:466-483` / `:513-514` / `:533` 与代码逐点相符；§5.4 分发行 `:1353` 命中 `if path in _PANEL_HANDLERS:`（`server.py:1353`）；§8 已登 MS-T18/T19/T20（`:382` 含 `tests/test_server_http.py:1234` 行号）；`cls_pools.md` §5(`:308/:324`)/§7.1(`:415` 含单调钟与 episode)/§8(POOL-T16/T17) 同步；`server.md` v1.21 §5.8/§2.10/§8 SRV-T33 已含守卫条件与 MS-T20 行号 ⇒ **无契约-代码偏差** | **证伪（需求 P2-2「契约漏登」已由文档同步闭合）** |

## 二、问题清单（每条：一行结论 + 证据链 + 影响 + 修复方向）

【P2】`china_finance_rss/server.py:525:` 形状漂移告警绕过限频，日志量随 RPS 线性放大——与本需求所治缺陷同型的**同类缺口**，本轮 episode/限频改造仍未触及该路径。

- **证据链**：**当**上游持续返回 `code==200` 但 `data` 非 list（信封/形态契约漂移）→ `:523` 判定失败 → `:525-526` 每次调用无条件 `log.warning(...)`；该行**不经过** `_warn_pool_fetch_failed`、不读 `_pool_fetch_warned_at`、无任何去重 → 因为 `handle_cls_pool` 是每个 HTTP 请求各调一次，而 `fetch_json` 正缓存命中只回放文本（`cache.py:796-808`），`json.loads` + 形状判定对每个请求重跑 ⇒ **告警速率 = 该端点 RPS**；`plate` TTL（`config.py:387`，`L2` 档 = 盘中 12s / 非盘 120s，`:473-474`）只限制**回源**、不限制**日志**。
- **影响**：与 P2-5 所治「日志量随 RPS 线性放大」完全同型；纯可观测性/日志量面，无功能与安全影响。**非本轮引入**（diff 未触 `:518-527`），但同一 handler 内已有一条限频路径、留下第二条，读者会误以为「池失败告警已全部限频」。
- **修复**：`:525` 改调 `_warn_pool_fetch_failed(pool_type, RuntimeError(shape))`（消息含 shape 名 ⇒ 保留「消息变化即时再告警」），或至少在 `:450-465` 注释块补一句「仅 except 路径限频；形状路径未限频（plate TTL 自限回源、不限日志）」。

【P2】`tests/test_server_http.py:1922`（同型还有 `:1989`、`:2029`；`:1833`/`:2341` 有头部断言部分兜底）: 304 的 `body == b''` 是与本轮所治 HEAD 恒真断言**完全同型**的空断言——`http.client` 对 304 归零读长，服务器真写体它也读 `b''` ⇒ 304 无体保证仍**零可证伪覆盖**，而本轮只把裸 socket 读法用在了 HEAD 上。

- **证据链**：CPython 3.12 `Lib/http/client.py` `HTTPResponse.begin()`：`if (status == NO_CONTENT or status == NOT_MODIFIED or 100 <= status < 200 or self._method == "HEAD"): self.length = 0`；`read()`（无 amt）走 `self._safe_read(self.length)` ⇒ `_safe_read(0)` 返回 `b''`，**与线路上有没有体无关**。因此 `RssConditionalGetTests._req`（`:1773-1782`，`http.client`）对 304 恒得 `b''`。**当**有人给 `_send_not_modified`（`server.py:1607-1638`，唯一 304 写出口；`:1638` 注释自己写着 `no wfile write`）加一次 `wfile.write`（不动头部）→ 线上 304 带体（条件请求/共享缓存的协议级破坏）→ `:1922/:1989/:2029` 的 `body == b''` 仍绿；`_raw_exchange` 循环（`:1222-1225`，200/200/400/404）**不含 304** ⇒ 全套件无一处变红。诚实边界：若回归形态是「改走 `_send_text(304,…)`」，`:1835` 的 `assertNotIn('content-length')` 与 `:2342-2346` 的头部集合断言会红（部分兜底）——**真空的是「裸写体不动头部」这一形态，以及 3 个无头部兜底的站点**。
- **影响**：覆盖缺口（当前实现正确），与本轮建立的口径不一致——同一文件已示范「恒真断言必须换裸 socket」，却只覆盖了 HEAD；若该形态回归上线，304 带体可污染缓存副本判定。
- **修复**：把 `_raw_exchange` 用法扩一条 304 用例（`If-None-Match` 触发，断状态行 `HTTP/1.0 304` + `body==b''` + 无 `Content-Length`）；`:1922/:1989/:2029` 的 `body==b''` 删除或注明「恒真，由裸 socket 用例承担」。

【P2】`china_finance_rss/server.py:533:` episode pop 只挂在**全成功 return** 上——「传输成功但 envelope/形状失败」的两条分支既不 pop 也不告警，「一次成功结束故障 episode」与真实恢复信号不对齐，恢复成降级态时新 episode 首条告警仍被旧窗口吞掉。

- **证据链**：**当** `t0` 发生 `FetchError` ⇒ `_warn_pool_fetch_failed` 写入 `(t0, msg)` 并告警；`t0+ε` 上游传输恢复但返回 `code!=200`（`:520-521`）或 `data` 非 list（`:523-527`）——这两条在 `try` 块**之外**、属于传输成功路径，却不 pop ⇒ 表里仍是 `(t0, msg)`；`t0+13s`（> plate TTL 12s，缓存过期后）再次出现同 kind 同 `str` 的 `FetchError` ⇒ `:479-481` 判「同消息 & 窗口内」⇒ **静默**，新故障 episode 的首条告警被吞。序列可达：TTL(12s) < GAP(30s)。附带效应（SE-6）：pop 使 `:452-453` 宣称的「每池每 30s 一条」不再是无条件上界——成功后的再告警周期下限被 plate TTL(12s) 压低 ⇒ 闪断场景告警频率上界 ≈ 1/12s/池（≈ 设计值 2.5 倍），仍被 NEG_TTL(5s, `config.py:40`) 与 TTL 双重约束、非 RPS 级。
- **影响**：每池每 30s 至多漏 1 条日志（可观测性），不涉返回体/缓存/业务语义；闪断期日志量略超原设计预算（同为日志面）。
- **修复**：把 pop 上移到「传输成功」的判定点（即 `:518` 之前、`json.loads` 成功之后），语义改为「传输恢复即结束 fetch 故障 episode」；或保持现状，但在 `:462-465` 注释与契约 §5.5 显式补「episode 仅由**全成功**结束（有意取舍）」，并把 `:452-453` 的措辞改成「每 episode 每 GAP 一条」。

【P2】`china_finance_rss/server.py:1742:` 本轮声明的「HEAD 无 body 规则内聚于 `_send_text`」不覆盖 `_reject_503`——过载拒绝路径对 HEAD 照样发 23 字节实体体，且无任何用例；注释与文档的 invariant 属 overclaim。

- **证据链**：`process_request`(`:1760-1769`) 在**读请求行之前**判定 `_inflight >= _max_inflight`（或 `executor.submit` 失败）⇒ 直接 `_reject_503` ⇒ 方法未知、完全不经过 `RSSHandler` / `_send_text` ⇒ `:1742-1747` 无条件 `sendall(... Content-Length: 23 ... + body)`。**当**过载时一个 `HEAD /healthz` 到达 ⇒ 线上收到 `HTTP/1.1 503` + 实体体 ⇒ 违反 RFC 9112 §9.3.2；`http.client` 因 HEAD 读长归零忽略之（常用客户端不炸），严格客户端（如 `curl -I`）可能把体误当下一条响应解析。**当**读者据 `:1597-1603` 注释（「the no-body rule for HEAD **lives HERE**，忘传 `write_body=False` 也无法把体写上线」）推断全服务 HEAD 恒无体 ⇒ 会在 `_reject_503` 这类旁路上失判。
- **影响**：既有缺陷、非本轮引入，触发面 = 过载路径（`MAX_INFLIGHT` 达阈 / 提交失败）；后果为协议违规 + 注释/文档 invariant 不成立，无数据/功能影响。
- **修复**：把 `:1597-1603` 注释与 `server.md` §5.8/§2.10 的措辞限定为「`_send_text` 出口的 HEAD 无体**内在守卫**」，并显式列出另外两条出口（CPython `send_error` 自带守卫、`_reject_503` 在读方法之前、无守卫）；若要真正闭环，`_reject_503` 需先 peek 请求行首行取 method 再决定是否附体（成本高，仅文档修正即可达标）。

## 三、定级说明（P0×0 / P1×0）

- **安全面（P0 候选）**：三处修复均不新增输入面/反序列化/鉴权；`getattr`/`dict.pop`/`time.monotonic()` 无异常路径；日志仍走 `%s` 参数化（无格式串注入）；HEAD 守卫只做抑制、不放宽任何校验。**无 P0**。
- **崩溃/数据丢失面**：`handle_cls_pool` 仍为总函数（enum gate + try/except + 无裸 raise，`:497/:508-514` 逐段实读）；pop 不可能抛；守卫不改变任何已发出的头部 ⇒ 不产生「头体不一致」的半响应。**无 P0**。
- **功能缺陷面（P1 候选）**：钟源替换后窗口语义、返回体、日志格式逐字不变；HEAD 守卫对存量调用方是恒真/恒假叠加（SE-3①），对 GET 零行为差（H5①），头/CL 在守卫前发出（H5②）；episode pop 不改任何返回值。⇒ 本轮新代码**无功能缺陷**，P1 = 0。四条发现全部落在「既有同类缺口（P2-1/P2-2/P2-4）」与「新语义的边界未对齐（P2-3，最坏后果 = 每池每 30s 漏 1 条日志）」，按最坏后果均到不了 P1 线。
- **排序依据（先想后果再定级）**：P2-1 是**当前就存在**、随上游漂移即按请求速率放大的日志行为；P2-2 是最坏后果最重但需未来回归才触发的**覆盖真空**；P2-3 是本轮新代码的**边界语义缺口**（后果最轻但与需求原文最相关）；P2-4 是**声明过宽 + 边缘路径协议违规**。四条均不阻断，交编排器记入未阻断问题。
- **需求原文闭环复核（r1 §二 5 条 P2）**：HEAD-400 → MS-T11b 循环已含 `('/market/margin?market=bogus',400)`(`:1224`)、`test_head_writes_no_body` 已删体断言(`:1086-1096`) ⇒ 闭合；契约登记 → H10 实核三份详设已同步 ⇒ 闭合；墙钟 → `:478` monotonic ⇒ 闭合（MS-T17 过期段的钟源区分力转移给 MS-T18，见 SE-4）；episode → `:533` pop ⇒ 闭合（边界见 P2-3）；硬编码消息 → `:419` 改 `str(exc)` ⇒ 闭合。**5/5 落地**，本报告 4 条均在需求原文之外。

## 四、评审结论

| 项 | 结论 |
| --- | --- |
| **评审结论** | ✅ **通过（APPROVE）** — 本轮 3 处修复（`time.monotonic()` 钟源 / 成功路径 `pop` episode / `_send_text` 内在 HEAD 守卫）逐条逆向实核：无跨钟比较、无遗漏的同表墙钟取时点、pop 不破坏有界性与并发口径、HEAD 守卫对非 HEAD 路径与全部头部零影响、`getattr` 默认值向后兼容且被既有用例保护；三条新用例 hermetic 且**真可证伪**（MS-T18 双路可红、MS-T19 删 pop 必红、MS-T20 删守卫必红，均自行推演、未引任何测试报告）；需求原文 5 条 P2 **5/5 落地**、契约文档已同步（H10 无漂移）。**无 P0/P1**；4 条 P2 全部为需求原文之外的同类缺口/覆盖真空/声明过宽，记录不阻断 |
| 问题统计 | **P0 = 0 · P1 = 0 · P2 = 4**（P2-1 形状告警未限频 / P2-2 304 体断言恒真 / P2-3 episode pop 边界 / P2-4 `_reject_503` HEAD 体与 overclaim） |
| 最严重项 | `china_finance_rss/server.py:525`（P2-1）：形状漂移时 `log.warning` 逐请求直写、绕过本轮维护的限频表与 episode 语义，日志量按该端点 RPS 线性放大——与本需求所治缺陷同型、至今未被任何限频路径覆盖 |
| 需求原文范围 | `doc/review/P5a-r1复查_对抗性盲审报告.md` §二 **仅 P2 条目（5 条）**，其结论/评审批注未取 |
| 零上下文纪律 | ✅ 入参 = 需求原文（仅 P2）+ 2 个改动文件 + `>>DIFF` 摘要 + 契约文档只读核对；未读取任何设计理由/前轮评审结论/测试报告正文；本人 grep 的 doc/ 回显副作用已在头部如实披露，全部结论均可回溯至源码、测试、CPython 原文行号 |
| 盲审产出下限 | ≥3 独立问题（实得 4，均带「当 {输入} → {后果}，因为 {路径}」证据链）；10+ 对抗性假设逐条给出成立/证伪，不为凑数造问题 |

>>DECISION: APPROVE
