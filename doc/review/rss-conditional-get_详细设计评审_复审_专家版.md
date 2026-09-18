# RSS 条件请求（ETag / Last-Modified / 304）详细设计评审 · **复审（专家版）**

> **文档编号** REV-DES-20260918-002 · **结论** ✅ **通过**（P0×0 / P1×0 / P2×6） · **日期** 2026-09-18 · **产出** review-expert
> **复审对象**：`doc/detailed/server.md` **v1.6** · `doc/detailed/cache.md` **v1.6** · `doc/detailed/_PROGRESS.md`（P3a-r1 段）
> **复审依据**：`doc/review/rss-conditional-get_详细设计评审_专家版.md`（REV-DES-20260918-001，⚠️ 有条件通过；P0×0 / P1×3 / P2×10 + 漂移 8 + 缺失用例 14）的 **C1–C8 放行条件**
> **复审模式**：定向复审（核 C1–C8 闭合 + 防新引入），**不重做全量评审** · **项目阶段**：生产版
> **就绪检查（check-common）**：✅ 三文档存在、v1.6 头部齐备、无占位符、核心节为实值 ⇒ 进入复审。

## 一、复审概要

| 项 | 值 |
|----|----|
| 结论 | ✅ **通过**（无 P0 / 无 P1；P2×6，均不阻断） |
| C1–C8 | **8/8 闭合**（C1 设计侧闭合，附 1 项测试规格 P2） |
| 修歪 | 未发现——canonical 投影为 **全量**替换（`count` 省略 = 0），非 `count=1` |
| 新引入缺陷 | 未发现功能级新缺陷；6 项 P2（其中 2 项影响验收网的**捕获力 / 可施工性**） |
| 越界改动 | **未发现**：`china_finance_rss/**` grep 新符号 **0 命中**；`SAD`/`PRD`/`API.md`/`README.md` 无本特性新增契约语句（仍为编排层待办） |
| 实证面 | `server.py:80-149`、`utils.py:14-33/145-182/212-269`、`tests/test_server_http.py:309-360/400-458`；`server.md` §2.3/§2.5/§2.9/§4.7/§5.1/§5.4/§5.8/§6.2#8/§8/§10#32-37/§10.1/§11；`cache.md` §2.4/§4.3/§8 |

## 二、C1–C8 逐条结论

| 条件 | 结论 | 证据（file:line / 节） | 说明 |
|------|------|----------------------|------|
| **C1**（P1-01 · ETag canonical 投影覆盖 item 级 `<pubDate>`；**本专项成败点**） | ✅ **已闭合** | `server.md:483-488`·`:539`·`:1042-1046`；BR-SRV-37 `:822`；§6.2#8③ `:1783`；§10#32 `:2000`；§5.4 注 `:1116`；`SRV-T52b` `:1909` | 见 §三 深度核验。**残留 P2-a** |
| **C2**（§10.1 第 4 条 `h.headers = {}` + §11 计数 4） | ✅ **已闭合** | `server.md:2110`（补登第 4 条）、`:2114`（4 条口径）、`:2019`（§11「4 条」） | 实证 `tests/test_server_http.py:441`/`:451` 两方法 `RSSHandler.__new__` **未设 `headers`** ⇒ 必须补 ✓。**残留 P2-c / P2-d** |
| **C3**（`<ttl>` 契约语句写死 BR-SRV-43） | ✅ **已闭合** | BR-SRV-43 `server.md:828`；§10#33 `:2001`；护栏 `:1143-1144`；`_PROGRESS.md:57` | 含「聚合器缓存提示 / 非时效保证」+「最小 1 分钟」+「推荐轮询 = ETag 优先、≥30s」+「<60s 用 SSE(4s)」✓；`<ttl>0</ttl>` 已排除 ✓ |
| **C4**（`dt.timestamp()` 移入 `try`；`except` 覆盖 stdlib 异常含 `OSError`） | ✅ **已闭合** | `server.md:1074-1082`；BR-SRV-40 `:825`；§6.2#8⑤ `:1783` | 解析 / 补时区 / `int(dt.timestamp())` **全在同一 `try`**；`except (TypeError, ValueError, OverflowError, OSError)` ✓；无同类裸操作遗留 |
| **C5**（BR-SRV-39 措辞与实现一致：大小写敏感、只认字面 `W/`） | ✅ **已闭合** | BR-SRV-39 `server.md:824`；`SRV-T50` `:1906` | 与实现 `:1058-1059`（`candidate.startswith('W/')`）一致；小写 `w/"…"` ⇒ 200 ✓ |
| **C6**（§10#36 补 RFC 9110 §8.6 + HTTP/1.0/EOF） | ✅ **已闭合** | `server.md:2004` | 含「304 带 `Content-Length` 必须等于 200 体长 ⇒ 写 `0` **违规**」+「未设 `protocol_version` ⇒ HTTP/1.0 ⇒ EOF 收尾」+「§6.3 头后空行终止」✓ |
| **C7**（14 条缺失用例逐条归属；★3 到位） | ✅ **已闭合** | 新增 `SRV-T52b:1909` / `T56b:1914` / `T61:1919` / `T62:1920`；扩 `T47:1903`·`T48:1904`·`T49:1905`·`T50:1906`·`T51:1907`·`T54:1911`·`T57:1915`·`T58:1916`·`T59:1917`；`cache.md:1034`（T-CACHE-32 扩容器态负例） | 14/14 有落点 ✓；★3（T56b / T52b / T61）到位 ✓；60→**64** 与 §10.1「新增 19 条」（`:2112`）一致 ✓。**残留 P2-a** |
| **C8**（漂移 8 项登记完整 + 未越界改 SAD/PRD/API/README/代码） | ✅ **已闭合** | `_PROGRESS.md:61-78`（待办 ①–⑧）、`:10-12`（版本核对）；`SAD.md:1009`（仍无落点）；`API.md`/`README.md`/`doc/prd/*` 无新增语句；`china_finance_rss/**` grep **0 命中** | 待办覆盖 D-1/D-2/D-4/D-5/D-6/D-7 + 残余风险；D-3/D-8 无需动作（原判 ✅）。**残留 P2-e** |

## 三、C1 深度核验（成败点，**实际验证而非读文字**）

### 1. canonical 投影是否**全量**空白化 `<pubDate>`
- 规则（`server.md:539`）：`_PUBDATE_RE = re.compile(r'<pubDate>[^<]*</pubDate>')`；应用（`:1044`）：`_PUBDATE_RE.sub('<pubDate/>', normalized)`——**第三个参数 `count` 省略 ⇒ 默认 `0` = 全部替换** ✓（非 `count=1`）。`_LASTBUILDDATE_RE`/`_RSS_TTL_RE` 仍 `count=1`（channel 首个，正确）。
- **三处回落值实际核验**（读代码，非读文档）：
  - `server.py:104-107` eastmoney：`parse_china_datetime_to_rfc822(showtime)` 异常 ⇒ `formatdate(timeval=None, localtime=False, usegmt=True)` ⇒ 产出 `<pubDate>…</pubDate>` **元素内容** ⇒ **落在被全量替换区** ✓
  - `server.py:130-133` ths：`int(item.get('ctime', 0))` 异常 ⇒ `int(time.time())` ⇒ 经 `timestamp_to_rfc822(ctime)` 产出 `<pubDate>` ⇒ **被替换** ✓
  - `utils.py:238-241` jin10：`parse_china_datetime_to_rfc822(item.get('time',''))` 异常 ⇒ `formatdate(timeval=None,…)` ⇒ **被替换** ✓
  - 结论：**三个回落值确实全部落在哈希区之外**——与首评 P1-01 的实证锚点一一对应，修复方向正确。
- `generate_rss` 仅 `pubDate` 为**未转义**原始字段（`utils.py:164`），其余（title/link/description/guid）均 `escape_xml`；而 `pubDate` 取值恒由 `formatdate`/`timestamp_to_rfc822` 产出（RFC822，**不含 `<`**）⇒ **无裸上游文本注入** ✓

### 2. 反向核：剔除 `<pubDate>` 后「内容变 ⇒ ETag 变」是否仍成立
- 仍入哈希：channel `title/link/description`（+被空白化的 `lastBuildDate`/`ttl` 占位）、`<atom:link href>`（含请求派生 Host）、item `title/link/description/guid`（`server.md:822`、`:1032-1046`）⇒ **任一变化照旧改 ETag** ✓
- **新的误 304 路径（存在，已被设计裁定为可接受）**：两条 item **仅 `<pubDate>` 不同、其余（guid/title/link/description）全同** ⇒ 被判同一表示 ⇒ 304。**判定：可接受**——item 身份由 `<guid>` 承载、`pubDate` 为上游元数据，且 3/5 feed 上它是"解析失败的当前时间回落"；纳入哈希会使条件请求**必然失效**（与首目标直接对立）。该取舍已在 `BR-SRV-37`（`:822`"可接受权衡"）与 §5.4 注（`:1116`）明确登记。
- 其它"内容变"通道（新增/删除 item、顺序变、guid/title 变、Host 变）仍 100% 改 ETag ✓（`SRV-T53` `:1910` 覆盖）。

### 3. 正则 `count` 语义与 `escape_xml` 误命中
- `count` 语义见 §三.1 ✓。
- **转义串误命中核验**：item `description` 内含字面 `<pubDate>x</pubDate>` 时，经 `escape_xml` 变为 `&lt;pubDate&gt;x&lt;/pubDate&gt;`；`_PUBDATE_RE` 要求字面 `<`，**不匹配** ✓ ⇒ 无误命中。
- `<lastBuildDate>` 与 `<pubDate>` 不互为子串，三条正则互不串扰 ✓。

### 4. `SRV-T52b` 是否真能在 handler 层捕获缺陷
- 覆盖 3 个 feed（eastmoney `showtime` / ths `ctime` / jin10 `time`），与"有 now 回落的 3/5 feed"**精确对应**（`/cls/telegraph` 与 `/wallstreetcn/live` 用 `timestamp_to_rfc822(item.get('ctime', 0))` / `timestamp_to_rfc822(int(pub_ts))`，**无 now 回落**，不需哨兵）✓
- **捕获力核验（关键）**：`formatdate(timeval=None)` 与 `int(time.time())` **均为秒级**。若用例在同一秒内连续调用 handler 两次，两次回落值**相同** ⇒ **即便没有 C1 修复，`_feed_etag(x1) == _feed_etag(x2)` 亦成立 ⇒ 假绿**。文档（`:1909`）写了"取**不同**的 `timeval` 两次"，但**未钉死如何强制不同** ⇒ 属**测试规格缺口（P2-a）**，必须补受控时钟（见 §四）。同一问题亦使 `SRV-T52`（`:1908`）仅在 `lastBuildDate` 跨秒时才对 channel 级失效有捕获力。

## 四、新引入 / 剩余问题清单（P2×6，**均不阻断**）

| # | 等级 | 问题 | 证据 | 修正指令 |
|---|------|------|------|---------|
| **P2-a** | **测试规格（影响 C1 验收证据）** | `SRV-T52b` 未钉死"如何让两次回落 `timeval` 不同"；`formatdate(None)` / `int(time.time())` **秒级**，同一秒两次调用产出相同 `pubDate` ⇒ **无修复也可绿**（正是 v1.5 `SRV-T52` 的假绿模式） | `server.md:1909`（另 `:1908`） | 用例须**控制时钟**：patch `utils.formatdate` / `server.time.time` 依次返回 `t`、`t+1`；并补一条**纯函数**断言「仅 `pubDate` 不同的两个 XML ⇒ `_feed_etag` 相同」（`count=0` 的直接回归网）。未控制时钟时**不得**作为 C1 的验收证据 |
| **P2-b** | 措辞过强（防"虚假安全感"复发） | BR-SRV-37 双向不变式第二子句「内容变 ⇒ ETag 变（不误 304）」缺「**除三项元数据外**」限定；仅 `pubDate` 字节变化时 ETag **不变**（本节后文以"可接受权衡"说明，但首句易被误读） | `server.md:822`、`:1783`③ | 第二子句改写为「**除 `pubDate`/`lastBuildDate`/`ttl` 三项外**的任一字节变化 ⇒ ETag 必不同」 |
| **P2-c** | 迁移清单不完备（照此施工会红） | §10.1 `FeedDoubleCheckTests` 条目只写"打桩目标改 `feed_cache_get_entry`、断言回源 1 次不变"，**未写**直接调用断言的返回值形状由 `'<rss/>'` 变 `('<rss/>', time)` | `server.md:2108`；`tests/test_server_http.py:327-328`、`:346` | 该行补："返回值断言改 2-tuple `(xml, time)`（`time` = stub 条目的 `time`）" |
| **P2-d** | 清单表述不一致 | §10.1 迁移第 3 条标题仅写 `（:440）`，但 2-tuple 变更同施于 `:450`（第 4 条已写 `:440 / :450`） | `server.md:2109-2110` | 标题改 `（:440 / :450）`，与第 4 条一致 |
| **P2-e** | 文档一致性（`_PROGRESS`） | "产出与落点"段仍作 `§8 T46–T60（15 条，总 60）`、`新增测试 SRV-T46..T60（15 条）`、`§10.1（3 条 server_http 打桩迁移）`，与本文件 `:63`（64 条 / C2 已修）**自相矛盾** | `_PROGRESS.md:33`、`:36` | 三处改为：`§8 T46–T62∪T52b/T56b（19 条，总 64）`、`新增测试 …（19 条）`、`§10.1（4 条迁移）` |
| **P2-f** | 文档遗留（**既有，非本轮引入**） | §1.1 标题「职责（11 条）」与实际编号至 **13** 条（另有 `7′`）不符；属 v1.4/v1.5 遗留 | `server.md:20`、`:22-35` | 改为「职责（13 条）」 |

### 非问题（登记，供放行后吸收）

1. **降级 feed 的 ETag 由"每次变"改为"稳定"（行为变更，已登记）**：`pubDate` 被剔除后，同一错误表示的重复请求会命中 **304**（`server.md:230`、`:1116`、`SRV-T59④` `:1917`）。语义正确（同一表示的条件命中），且 `_PROGRESS.md:74` 已要求 `API.md` 注明"降级 feed 不应作为 304 缓存的判断依据"。
2. **`_feed_etag` 在 `_guard` 之外执行**（`server.md:1103`）：`xml.encode('utf-8')` 在 lone-surrogate 数据下可抛 `UnicodeEncodeError`（⊄ `OSError`，不被 `do_GET` 捕获）。**非本轮新引入**（`_send_text` `:1606` 的 `body.encode('utf-8')` 属同类既有风险），仅登记为残余。

## 五、额外自查结论

- **C1 与 `SRV-T52` 的不变式自洽**：✅ `SRV-T52` 已明确标注为 **channel 级** 并把覆盖边界指向 `SRV-T52b`（`:1908`）；§6.2#8③ 已改双向（`:1783`）；`BR-SRV-37` 双向 + 取舍（`:822`）。自洽（措辞限定见 P2-b）。
- **用例编号 / 列表一致性**：✅ `SRV-T52b`/`T56b`/`T61`/`T62` 无冲突（原止于 T60）；`T46..T60`(15) + 4 新增 = 19，与 §10.1 `:2112` 一致；`45 + 19 = 64` 与 §11 `:2019` 一致；`BR-SRV-36..44` 与 `§10#32-37` 连续无冲突。唯一不一致在 `_PROGRESS`（P2-e）。
- **对外契约"只增不改"**：✅ `_send_text` 新增两可选形参默认 `None`（`:1603-1605`）、`generate_rss(ttl=None)` 默认不输出（`:583`/`:1143`）、`feed_cache_get` 签名/语义不变（`:582`）、路由/方法/200 头体语义不变；`generate_error_rss` 不传 `ttl` ⇒ 降级体无 `<ttl>`（`:1153`）。
- **出范围项未偷偷实现（BR-SRV-44）**：✅ `BR-SRV-44`（`:829`）仅登记 keep-alive / `/opml.xml` / `/` 条件请求；`SAD.md` 仍只有第 1009 行的假设句、无 keep-alive/304 承诺；全仓 **0 命中** `protocol_version`（除 `stream.py` 既有流端口）。

## 六、评审结论

**✅ 通过** —— **P0×0 / P1×0 / P2×6**。首评三项 P1 全部闭环：**C1（P1-01）设计侧已闭合且未修歪**（canonical 投影为全量空白化，三处 now 回落值实证出哈希区）、C2（P1-02）✅、C3（P1-03）✅；C4–C8 一并闭环。**未发现功能性新引入，未发现越界改动**（代码 / SAD / PRD / API.md / README.md 均未被改动）。

**放行前建议同批吸收（低成本，不阻断）**：
1. **P2-a 必落**（否则 C1 的验收网不成立）：`SRV-T52b` 用**受控时钟**；补一条"仅 `pubDate` 不同的两 XML ⇒ 同 ETag"的纯函数断言。
2. **P2-c 必落**（否则 §10.1 的 4 条迁移照此施工不能全绿）：补 `FeedDoubleCheckTests` 返回值断言改 2-tuple。
3. P2-b / P2-d / P2-e / P2-f：文本收口（同批或随后）。

> 上述均为 P2 级文本 / 测试规格修订，**无需退回重做详设**；由 task-decomposer 落 P2-a/P2-b/P2-c 后即可交 `tester` / `code-developer`。

## 变更记录

| 版本 | 日期 | 内容 |
|------|------|------|
| REV-DES-20260918-002 | 2026-09-18 | 复审（定向核 C1–C8 + 防新引入）。对象 `server.md` v1.6 / `cache.md` v1.6 / `_PROGRESS.md`（P3a-r1）。结论 ✅ 通过（P0×0 / P1×0 / P2×6）。实证复核 `server.py:80-149`、`utils.py:14-33/145-182/212-269`、`tests/test_server_http.py:309-360/400-458`、`SAD.md:1009`、`API.md:631`、`README.md`；确认代码未改（grep 新符号 0 命中）。 |

> 本报告仅依据文档交付物与参考契约文件的客观内容；不含对作者/创作意图的任何推断。评审不修改任何被评审文档。

