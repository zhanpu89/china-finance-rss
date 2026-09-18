# RSS 条件请求（ETag / Last-Modified / 304）详细设计评审报告（专家版）

> **文档编号** REV-DES-20260918-001 · **结论** ⚠️ **有条件通过**（P0×0 / P1×3 / P2×10） · **日期** 2026-09-18 · **产出** review-expert
> **评审对象**：`doc/detailed/server.md` v1.5 增量（§1.1#13 · §1.3 · §1.5 · §2.1 · §2.3 · §2.5/§2.5a · §2.9 · §2.10 · **§4.7 BR-SRV-36..44** · §5.1 · §5.4 · §5.8 · §6.2#8 · §7.2#2 · §8 SRV-T46..T60 · §10#32–37 · §10.1 · §11.5）+ `doc/detailed/cache.md` v1.5（BR-CACHE-32 / §2.4 / §5.3 / T-CACHE-32）+ `doc/detailed/_PROGRESS.md` P3a 段
> **评审模式**：详细设计评审（增量） · **项目阶段**：**生产版**（2C2G 在线服务，P6c 专项已有部署级验证报告）
> **需求基线**：`_MEMORY_CACHE.md`（B 方案 + 3 条不可妥协项 + 6 条设计分叉） · **上游**：SAD v1.7 · PRD v0.6
> **就绪检查（check-common）**：✅ 文档存在、头部版本/状态/日期/作者齐备；无 `{例:`/TODO/待补充占位；核心节均为实值（伪代码、常量、用例编号逐条齐备）⇒ 进入正式评审。checklist 懒加载：`check-detailed`。

## 一、评审概要

| 项 | 值 |
|----|----|
| 结论 | ⚠️ **有条件通过**（无 P0；**P1×3 → 生产版按阻断处理**，闭环 P1 后放行） |
| P0 | **0**（无崩溃 / 数据丢失 / 资金 / 安全类） |
| P1 | **3**：R1 未真正解掉（item 级时钟派生 `pubDate` 未规范化）· 既有用例必挂点未登记（§10.1 清单不完备）· 需求明令的 `<ttl>` 契约语义缺失 |
| P2 | **10**：健壮性 / 一致性 / 溯源 / 测试覆盖，可并行修 |
| 是否允许进入编码 | ⚠️ 需先闭环 **P1-01**（ETag 规范化边界必须由设计裁定——需求明令「禁止 code-developer 自行选型」）+ P1-02/P1-03（两项低成本清单补全） |
| 范围纪律（Q8） | ✅ 出范围三项（HTTP/1.1 keep-alive、`/opml.xml`、`/` 与 JSON 的条件请求）**均未实现**，仅登记于 BR-SRV-44 / §10#37；`server.py` 无 `protocol_version`（全仓仅 `stream.py:1359` 属流端口既有实现） |
| 对外契约 | ✅ 只增：路由/方法/200 头体语义/`feed_cache_get` 签名/`generate_rss` 既有调用点均未变（实证：`cache.py:906-914` 与 `cache.md §5.3` 薄包装逐字等价） |

## 二、问题清单

### P1（生产版阻断，须闭环后放行）

**【P1-01】`server.md` §4.7 BR-SRV-37 / §6.2#8③ / §10#32（证据锚点：`server.py:104-107`、`server.py:130-133`、`utils.py:238-241`）：ETag 规范化只剔除 channel 级 `<lastBuildDate>`/`<ttl>`，**未覆盖 item 级「当前时间回落」`<pubDate>`** ⇒ 3/5 个 feed 仍「永远 200」，**不可妥协项 #2 未真正满足**（本专项第一风险只在 channel 级被解掉）**
　问题：`handle_eastmoney_kuaixun`（`showtime` 缺失/不可解析 ⇒ `pubdate = formatdate(timeval=None)`）、`handle_ths_kuaixun`（`ctime` 非数 ⇒ `ctime = int(time.time())`）、`parse_jin10_items`（`item['time']` 不可解析 ⇒ `formatdate(timeval=None)`）三处回落值**位于哈希区内**，每次 TTL 到期重生成都变 ⇒ ETag 变 ⇒ 200。BR-SRV-37 的不变式（"其余任何字节变化都改变 ETag ⇒ 不会误 304"）**方向写反了**：它保证了"不误 304"，却没保证"不误 200"。且 `SRV-T52` 用**同一组 items**复用调 `generate_rss` 两次，**结构上无法检出**该路径（正是 `_MEMORY_CACHE.md` R1 所注"测试也难发现"）。
　建议（必须由设计裁定其一，不得留给编码者）：① **确定性化回落**：item 缺时间时不回落到 now（省略 `<pubDate>` 或写固定哨兵；`generate_rss` 需容忍缺失键——体改动须编排层批准）；② **ETag 侧投影**：`generate_rss` 产出"canonical 串"（把生成期 now 派生的 pubDate 一并占位化），ETag 只对该串取哈希（零体外变更，推荐）；③ 明确登记"这 3 个 feed 不支持条件请求"并**撤回 R1 承诺**（最不推荐）。无论选哪条，均须补 **端到端用例：缺失 `ctime`/`showtime`/`time` 的 payload 经 handler 两次解析 ⇒ ETag 不变**。

**【P1-02】`server.md` §10.1 必改清单 / §11 自检（证据：`tests/test_server_http.py:440-458`）：迁移清单不完备 + 计数自相矛盾 ⇒ 直接威胁不可妥协项 #3（不破坏既有 467 用例）**
　问题：两处 `test_serve_feed_*` 用 `RSSHandler.__new__(RSSHandler)` 构建且**未设 `h.headers`**；v1.5 起 `_serve_feed` 在调 `_send_text` **之前**执行 `_not_modified(self.headers, …)` ⇒ 即便按 §10.1 把 `_get_or_fetch_feed` 桩改成 2-tuple，仍会 **AttributeError**（用例报错，非断言失败）。§10.1 只写了"2-tuple + `_send_text` kwargs 可捕获"，**漏写 `h.headers = {}`（或 patch `_not_modified`）**；且 §11 自检称"**三条** server_http 打桩迁移"，与表格实际列出的 **4 个方法**（FeedDoubleCheckTests ×2 于 `:315/:331`，BaseUrlHardeningTests ×2 于 `:440/:450`）不一致。
　建议：§10.1 该行补 `h.headers = {}`（并注明"`_serve_feed` 自 v1.5 起读 `self.headers`"）；§11 计数改 **4**（"2 条 2-tuple + 2 条 headers/2-tuple"）。

**【P1-03】`server.md` §4.7 BR-SRV-43 / §10#33 / `_PROGRESS.md` 契约影响#4：需求明令的 `<ttl>` 契约语句未落**
　问题：`_MEMORY_CACHE.md` 设计分叉 5 **明令**"须在契约中说明「**聚合器缓存提示，非时效保证，短线请用 SSE**」"；v1.5 仅有 §10#33 的 "advisory" 一词，**该句与其登记项均缺失**。它恰是"`<ttl>1</ttl>` 让下游把轮询从 30s 降到 60s"这一误导风险的唯一缓冲。
　建议：BR-SRV-43 与 §10#33 补该语义；`_PROGRESS` 契约影响#4 + API.md/README 同步项写明"`<ttl>` 为建议轮询间隔、**最小粒度 1 分钟**（盘中 30s 被向上取整到 1）、非时效保证，需 <60s 新鲜度请用 SSE"。

### P2（不阻断，建议同批或紧随修复）

**【P2-01】§5.4（第 1050-1062 行伪代码）/"绝不 400/500"不变式无结构性保证** → `_feed_etag` 与 `_not_modified` 在 `_guard` **之外**执行，`do_GET`/`do_HEAD` 只 `except OSError`。`dt.timestamp()` 写在 `try` **之外**，大年份/平台 time_t range 可抛 `OverflowError`/`OSError`（非已捕获三元组）⇒ 连接被中断而非 200。**建议**：把 `dt.timestamp()` 移入 `try`，或把条件判定整体放进受 guard 保护的闭包；§6.2#8⑤ 的措辞随之收敛为"已覆盖 stdlib 已知异常面"。

**【P2-02】§4.7 BR-SRV-37 / §2.9 `count=1` 的成立前提无护栏** → 已核实当前成立：所有 `<pubDate>` 值均由 `formatdate` 产出（无裸上游文本注入），且 `escape_xml` 使 item 字段不可能含字面 `<lastBuildDate>`/`<ttl>`；channel 级两元素结构上先于 items ⇒ `count=1` 精确命中，**无误命中、无误 304**。但该前提仅存在于 `generate_rss` 的实现顺序中，**无注释/断言**：将来 item 级出现同类元素或 channel 元素重排即静默改语义。**建议**：加注释 + 一条"规范化只作用于 channel 首个元素"的单测；或改由 `generate_rss` 直接产出 canonical 串（与 P1-01 的推荐方案②同路）。

**【P2-03】§5.4 / §2.5：`feed_cache_put` 后**第三次**取 `feed_cache_get_entry`** → 多一次加锁与 LRU 触碰（每次都会再 `move_to_end` + `last_access`）；语义正确且无竞态（持 per-path 锁）。但**当 ttl 极小（如测试用 `ttl=0`）时第三次查询返回 `None`** ⇒ 200 **不发 `Last-Modified`**，与 §4.7 BR-SRV-42"有缓存条目时发"的措辞不符。**建议**：把口径钉死为"仅**新鲜**条目发 `Last-Modified`"（`expires_at` 已过则视为无条目），并说明理由（与 `feed_cache_get_entry` 契约一致）。

**【P2-04】`cache.md` §2.4/BR-CACHE-32、§5.3 与 §7.2#2："浅拷贝 + 调用方只读"缺违约后果说明** → 已核实**浅拷贝充分**（值仅 str/float，不可变；`feed_cache_get_entry` 返回字面量新 dict），且**薄包装与现码 `cache.py:906-914` 逐字等价**（`not entry` 真值判定、`time.time() >= entry.get('expires_at',0)`、`move_to_end`、`last_access = time.time()`、`return entry['xml']` 全部一致）。**建议**：补一句"因值不可变，浅拷贝即可隔离容器；改返回值不影响容器态（T-CACHE-32 已断言）"，避免下游误加 deepcopy。

**【P2-05】§5.8 `_send_not_modified`：`Vary` 中 `Accept-Encoding` 无条件追加** → 与 200 一致**仅因**所有复用方都是 `cache=True`（RSS 恒定如此）；若将来复用到 `cache=False` 表示，会出现"200 无 `Vary: Accept-Encoding` / 304 有"的头漂移。**建议**：形参化（`cache=True`/`accept_encoding=True`）或加注释"仅用于可缓存表示，勿复用到 `cache=False` 路径"。

**【P2-06】§10#36 / §4.7 BR-SRV-41：304 不发 `Content-Length` 的兼容性判定 —— ✅ 结论正确，但依据未写全（见 §三.2）** → 三处实证：① `RSSHandler` 未设 `protocol_version` ⇒ HTTP/1.0（全仓 `protocol_version` 仅 `stream.py:1359`，属流端口既有实现）；② CPython `http.server` **仅在 `protocol_version >= 'HTTP/1.1'` 时才把 `Connection: keep-alive` 视为持久连接**，故主端口每响应后必然关连接、由 **EOF** 收尾；③ RFC 9110 §15.4.5 / §8.6 规定 304 **不得**携带等于 200 体长度的 `Content-Length` ⇒ **显式 `Content-Length: 0` 反而不合规**。**建议**：把上述②③写入 §10#36（回答"为何不必"）；可选加一条钝化防御 `if self.request_version == 'HTTP/1.0': self.close_connection = True`（对不合规客户端更稳，无契约影响）。

**【P2-07】§4.7 BR-SRV-43 / §5.4 `generate_rss(ttl=0)` 会输出 `<ttl>0</ttl>`** → `if ttl is not None` 无值域防护，而 RSS 2.0 要求**正**整数。`_feed_ttl_minutes` 已由 `max(1, …)` 保护，但公开可选形参无防护。**建议**：改 `if ttl is not None and int(ttl) > 0`（或 `max(1, int(ttl))`），并补边界用例（见"缺失测试用例"#12）。

**【P2-08】§2.3 / §5.1：`shape='rss'` 的 2-tuple 无类型护栏** → 成功/异常**同形状**已正确达成（降级 → `(error_rss, None)`）；但无 `isinstance` 断言时，若某路径返回 str（**正是既有测试桩的现状**），`xml, last_modified = …` 会按字符静默解包（长 XML 才抛 `ValueError`）。**建议**：解包处加 `assert`，或改用 `NamedTuple` 提升可诊断性。

**【P2-09】溯源版本漂移（文档头部）** → `server.md` 头部仍写"上游 SAD **v1.3** / 上游 PRD **v0.3**"（实际 SAD **v1.7**、PRD **v0.6**）；`cache.md` 头部写 SAD **v1.2**。**建议**：更新为实际版本，或统一注明"上游版本为设计时点快照，权威以对方头部为准"。

**【P2-10】文档一致性（两处）** → ① §10 条目物理顺序为 `1..14, 18, 15, 16, 17, 19..37`（v1.3 插入 #18 所致），编号无冲突但阅读顺序断裂——建议重排或标注"#18（v1.3 增补）"；② `_MEMORY_CACHE.md` 称"既有 **467** 用例"，PRD v0.6 称"**461** 个单元用例"，§10.1 未注明受影响用例总数基线来源——建议在 §10.1 写明基线口径（否则外部无法判定"不破坏既有用例"是否达成）。

## 三、设计的缺陷详情

### 1. R1 复核：误 304 与误 200 的两个方向

| 方向 | 结论 | 依据 |
|------|------|------|
| **误 304（内容变、ETag 不变）** | ✅ 未发现可达路径 | 规范化仅剔除 `<lastBuildDate>`/`<ttl>` 的**内容**（各 `count=1`）；其余全部字节（channel title/link/description、`<atom:link href>`（含请求派生 Host）、item guid/title/link/description/pubDate、元素顺序、XML 声明、空白）均进哈希。**转义分析**：`escape_xml` 把 `<`→`&lt;`，item/description/title/link/feed_url 内不可能出现字面 `<lastBuildDate>`；**唯一未转义的 item 字段 `pubDate`** 取值全部由 `formatdate(...)` 产出（`server.py:107/139`、`utils.py:26/33/241/266`），无裸上游文本注入 ⇒ 无法伪造出被正则命中的元素。加之两元素在 `generate_rss` 中结构上**先于** items，`count=1` 精确命中 channel 首个 ⇒ 无误命中。 |
| **误 200（内容未变、ETag 变）** | ❌ **存在，且命中 3/5 个 feed** | 见 **P1-01**：item 级 `pubDate` 的"当前时间回落"是第二个时钟派生字段，未被规范化覆盖 ⇒ 每次 TTL 到期重生成都改 ETag。`SRV-T52` 复用同一 items 调 `generate_rss` 两次，**无法覆盖**该路径（假绿）。 |

> ⚠️ **逆向审查**：文档 §4.7 BR-SRV-37 的措辞"其余任何字节变化…都改变 ETag ⇒ **不会误 304**"给读者**虚假的安全感**——它只证明了单向（不误 304），却让读者认为 R1 已闭合；`_MEMORY_CACHE.md` 把 R1 定义为**"内容未变 ⇒ ETag 不变 ⇒ 304"**，此处被替换为"变更 ⇒ ETag 变"，**命题不等价**。

### 2. 304 组成与 HTTP/1.0 收尾（RFC 9110 §15.4.5）

- **组成合规 ✅**：无 body、无 `Content-Encoding`、无 `Content-Length`、无 `Content-Type`；带 `ETag` + `Vary`（`_BASE_URL_VARY` + `Accept-Encoding`，与 200 同值）+ `Cache-Control`（与 200 同值来源 `_cache_age()`）；`Date` 由 `BaseHTTPRequestHandler.send_response` 自动补（满足 RFC 的"MUST 生成 200 会有的 Date/ETag/Vary"）。独立 `_send_not_modified` 而非复用 `_send_text`，把"无体无编码"变成**结构性保证**（§10#35）——这是本增量最正确的一个设计取舍。
- **`HEAD` 同路径 ✅**：`do_HEAD` → `_serve_feed(write_body=False)`，条件判定与 304 生成不依赖 `write_body`（`_send_not_modified` 从不写体）⇒ HEAD 可得 304。
- **"无 `Content-Length` 的 304 在 HTTP/1.0 下能否正确收尾"——判定：能，且不应改为 `Content-Length: 0`**。① `protocol_version` 未设置 ⇒ HTTP/1.0，且 CPython `http.server` 只在 `protocol_version >= 'HTTP/1.1'` 时才把客户端 `Connection: keep-alive` 当作持久连接 ⇒ **每响应后关连接，EOF 即消息边界**；② RFC 7230 §3.3.3-1 / 9110 §6.3 明定 1xx/204/**304** 与 HEAD 响应恒以"头后首个空行"终止，与是否带 `Content-Length` 无关；③ RFC 9110 §8.6 要求 304 若带 `Content-Length` 必须**等于 200 体的字节数**，写 `0` 属**违规**。⇒ **保持现设计**，仅需在 §10#36 补依据（P2-06）。
- **待补一处措辞**：§5.4 注中"降级 feed 每次错误体 `pubDate` 变化 ⇒ **不会误 304**"略微夸大——同一秒内两次错误体的 ETag 相同、会返回 304，但那是**同一表示**的条件命中，语义正确；应表述为"不会与**成功**体的 ETag 混淆"。

### 3. 条件头解析正确性（RFC 9110 §13.1.2 / §13.1.3）

- **INM 优先于 IMS ✅严谨**：`_not_modified` 用 `inm = headers.get('If-None-Match'); if inm is not None:` 分支 ⇒ INM **存在**（含空串等非法值）即完全忽略 IMS，与 §13.1.3 一致。
- **`*` / 多值 / `W/` / 空白 ✅**：`*` 短路 True；逗号逐项 `strip` + 剥 `W/` 后与服务端 opaque tag（已剥 `W/`）比较 ⇒ 弱比较（§8.8.3.2）实现正确；服务端标 `W/` 且用弱比较，语义自洽。
- **`w/` 大小写**：BR-SRV-39 的"不区分大小写前缀只接受字面 `W/`"表述**自相矛盾**，实际实现只认字面 `W/`（小写 `w/"x"` ⇒ 不匹配 ⇒ 200）。这符合 RFC（弱指示符大小写敏感），但须把该句改写为可测口径并补用例（见缺失用例#13）——属 **P2**（措辞歧义）。
- **IMS 秒级 + naive→UTC ✅**：`parsedate_to_datetime` → naive 补 `timezone.utc` → `int(last_modified) <= int(ims_epoch)`；发送侧 `formatdate` 亦截断到秒 ⇒ 客户端回显自身 `Last-Modified` 时 `<=` 必成立（**边界正确**）。非法头 `except (TypeError, ValueError, OverflowError)` → 200，方向正确（残留健壮性见 P2-01）。
- **`last_modified is None` ⇒ 禁用 IMS ✅**：降级路径正确不评估 IMS，且 `_send_text(last_modified=None)` 不发头（`formatdate(None)` 陷阱被规避）。

### 4. 访问器契约、降级路径与并发（Q4）

- `feed_cache_get_entry` **浅拷贝足够 ✅**（值不可变；实证 `cache.py:906-914` 与 `cache.md §5.3` 薄包装**逐字等价**，R4 风险已规避）。
- "**命中恰好一次** `move_to_end` + `last_access`" ✅ 成立；miss 路径的第二次（双检）与第三次（put 后取 time）各自也只在命中时触碰一次，无重复触碰同一逻辑命中。
- **降级路径同形状 ✅**：`_guard(shape='rss')` 成功/异常均 2-tuple；异常路 `(generate_error_rss(...), None)`；`_serve_feed` 无 `isinstance` 分支 ⇒ 可执行性良好（残留：无类型护栏，P2-08）。
- **锁序**：per-path 锁内调用 `feed_cache_get_entry/put`（内部各取一次 `_feed_cache_lock`）构成 **per-path → `_feed_cache_lock`** 的嵌套方向；cache 层从不反向取 per-path 锁 ⇒ 无死锁。但 `server.md §7.2#2`（"per-path 锁内不持有任何 cache 内部锁"）与 `cache.md §7.2#4`（"两把锁无锁序关系"）的**表述与实际嵌套方向不符**（v1.5 未新增锁，属既有措辞遗留；建议改为"允许 `per-path → _feed_cache_lock` 单向嵌套，禁止反向"）。**P2**（归入一致性）。

### 5. `<ttl>` 决策评估（Q5）

- **取值映射符合要求**：`max(1,(ttl+59)//60)` ⇒ 30→1 / 180→3；与 `cache_policy('feed')['ttl']` 同源；且 `feed` 域与 `_cache_age()` 用的 `news_url` 域**同为 L3、ttl `[30,180]`**（实证 `config.md:291-292/322-323`）⇒ 200/304 的 `Cache-Control` 与 `<ttl>` 不自相矛盾 ✅。
- **位置与兼容性 ✅**：紧随 `</lastBuildDate>`、在 `<atom:link>` 之前；`generate_rss(ttl=None)` 默认不输出 ⇒ 既有 9 个调用点零改动（实证 `utils.py:145` 现签名无 `ttl`）；`generate_error_rss` 不传 ⇒ 降级 feed 无 `<ttl>`（合理）✅。
- **剔除出 ETag 的理由成立 ✅**：`<ttl>` 由 policy 派生，盘中/非盘切换（30↔180）会变；纳入则每日时段边界产生假 200。但**理由成立 ≠ 风险已闭环**：`<ttl>` 是 **ETag 之外**的新可变量，不构成第二时钟源（正确），却也**不能**用它来解释 P1-01 的假 200。
- **`<ttl>1</ttl>` 对短线场景是否误导 —— 判定：确有误导面，但不应改取值，应补语义（即 P1-03）**。RSS 2.0 的 `<ttl>` 只能表达整分钟，30s 无法表达；向下取整（0）非法、向上取整（1）会让"只认 `<ttl>`"的聚合器把轮询**放慢**到 60s（比现状 30s 更慢、且大于服务端 `max-age=30`）。**不建议**改成"只在非盘输出 3"或恒输出 3（会与 `Cache-Control` 直接冲突，并丢掉盘中低延迟意图）。**正确做法 = 保留 1/3 取值 + 落 P1-03 的"advisory、最小 1 分钟、非时效保证、需 <60s 用 SSE"契约语句**，使下游不会把它当时效承诺。

### 6. 逆向审查（Step 1.5）

| 视角 | 发现 |
|------|------|
| **反证**（假设不成立会怎样） | 文档假设"剔除 `lastBuildDate`/`ttl` 即得到内容指纹"。该假设对 channel 级成立、对 **item 级 now 回落不成立** ⇒ 假设失效的后果不是报错而是**静默退化为永远 200**（P1-01），且现有用例全绿（假绿）。 |
| **遗漏**（边界/错误路径/降级） | ① item 级时钟字段（P1-01）；② `ttl=0`/负值（P2-07）；③ "ttl 极小 ⇒ 无 Last-Modified"（P2-03）；④ 条件判定异常面（P2-01）；⑤ **范围纪律的负向断言缺失**（`/opml.xml`、`/`、JSON 带条件头必须 200——无任何用例）。 |
| **误导**（虚假安全感） | ① BR-SRV-37"不会误 304"被当作 R1 已闭合（§三.1）；② §6.2#8⑤"绝不 400/500"缺结构性保证（P2-01）；③ BR-SRV-42"有缓存条目时发 Last-Modified"与 `expires_at` 语义不符（P2-03）；④ BR-SRV-39 "不区分大小写前缀"自相矛盾（§三.3）。 |
| **不可逆** | 无新增持久化/无 DDL/无删除路径 ⇒ 回滚成本 = 撤 `_serve_feed` 分支与两个可选形参；ETag 无存储。**回滚安全 ✅**。唯一"半不可逆"是 `<ttl>` 已发布给下游聚合器（下游可能据此调轮询）⇒ 这正是 P1-03 必须补契约语义的原因。 |
| **断链**（需求→实现→验证） | 需求（`_MEMORY_CACHE.md` 分叉 1/5）→ 实现（BR-SRV-37/43）→ 验证（T52/T58）**两处断链**：① T52 结构与真实重生成路径不同（P1-01 之所以假绿）；② 分叉 5 的契约语句无实现落点（P1-03）。 |

### 7. 可执行性审查（Step 1.6）

- **正向**：伪代码逐行可替换（含常量、正则、`_send_not_modified` 全量头序）；接口签名精确（`_send_text` 两可选形参、`_serve_feed` 不变、`feed_cache_get_entry` 契约与浅拷贝字段清单齐备）；`cache.md` 侧伪代码可直接落 `feed_cache_get` 薄包装。**编码者无需"发明"任何接口 ✅**。
- **阻断面**：① **P1-01 是唯一的"必须由设计裁定"项**——需求明令"禁止 code-developer 自行选型"，若带着现设计进编码，编码者只能二选一（要么照样静默失效，要么擅自改生成逻辑），故必须在 P3b 闭环；② **P1-02** 不修则编码者按 §10.1 施工后会遇到 2 个红用例并可能误改生产代码；③ `_feed_etag` 若按 P1-01 方案②（canonical 投影）落地，需在 `utils.md`（无独立详设）与 `server.md §5.4` 明确 canonical 串的唯一产点，否则会出现"两份哈希输入口径"。

## 漂移检测（P7a）

> 比对对象：`doc/arch/SAD.md` **v1.7**、`doc/prd/perf-stability-optimization.md` **v0.6**、`doc/detailed/{server,cache,_PROGRESS}.md`、`_MEMORY_CACHE.md`。

| # | 漂移项 | 事实 | 判定 / 建议 |
|---|--------|------|------------|
| D-1 | **SAD 未承接 RSS 条件请求** | `SAD.md` 全文仅 1 处提及条件请求（第 1009 行的假设句"若上游提供按版本/时间戳的条件请求…"），**无** 304/ETag/`Last-Modified`/`<ttl>` 的任何契约落点 | **新漂移（需回填，P1 级契约缺口）**。建议 SAD 回填：§2.4（或 server 行）增"RSS 响应缓存校验器与 304 语义""弱 ETag 派生口径（剔除 `lastBuildDate`/`ttl` 的**内容**）""`<ttl>` 为 advisory、最小 1 分钟"；并显式声明**仍为拉模型**、未启用 keep-alive。回填责任在 system-architect（`_PROGRESS` 契约影响#6 已登记为"可选"，建议改判为**必做**） |
| D-2 | **PRD 无对应 AC** | `grep` PRD 全文：`ETag`/`304`/`Last-Modified`/`<ttl>` **0 命中**；该特性唯一追溯目标是 `_MEMORY_CACHE.md`（编排层工作文件，非契约文档） | **新漂移（建议承接）**。§9 追溯矩阵把本增量挂到"**本专项 R1**"，而 R1 仅存在于工作文件 ⇒ 一旦 `_MEMORY_CACHE.md` 被覆写（该文件历史上即被复用覆写，见其 D3），交付物将失去需求锚点。建议 PRD v0.7 增 AC（如"AC-A13 RSS 条件请求：内容未变 ⇒ 304 零 body；`<ttl>` advisory"）或由 SAD 正式承接 D-1 |
| D-3 | **编号与既有体系** | `BR-SRV-36..44`（接 35 ✅）、`BR-CACHE-32`（接 31 ✅）、`SRV-T46..T60`（接 T45 ✅）、`T-CACHE-32`（接 31 ✅）、`§10#32–37`（接 31 ✅）；`_PROGRESS` 计数（偏差 37 / 测试 60）与两文档一致 | ✅ **连续、无冲突、可引用**（`_PROGRESS` 自检口径与正文一致） |
| D-4 | **标识符同名不同义** | 设计通篇用「**本专项 R1**」表示"内容未变⇒304"，而 SAD/PRD 已用 **R1–R20** 表示根因编号（另有 R-1/R-2/R-3 等架构风险号） | **命名冲突风险（P2）**。跨文档阅读易误读（"R1 未解" / "R1 已修"）。建议改称 `US-RSS-1` / `AC-RSS-1`，或每次出现都写全「本专项 R1（`_MEMORY_CACHE.md`）」 |
| D-5 | **文档溯源版本** | `server.md` 头部：SAD **v1.3** / PRD **v0.3**（实际 v1.7 / v0.6）；`cache.md` 头部：SAD **v1.2** | **既有漂移（P2-09）**，v1.5 未修；影响"哪版上游被评审过"的可追溯性 |
| D-6 | **对外文档同步面** | `_PROGRESS` 契约影响 #1–#5 覆盖 ETag/304/gzip-304/`<ttl>`/可选性 ✅，但**缺**分叉 5 明令的"非时效保证，短线请用 SSE"；且未登记"`<ttl>` 会改变 RSS 体（元素只增）需在 API.md 样例体现"的**验收点** | **漂移（并入 P1-03）**：补齐该语句 + 明确 API.md/README/变更日志为放行前置 |
| D-7 | **出范围项反向漂移** | SAD/PRD 均无 keep-alive / `/opml.xml` / JSON 条件请求的既有承诺 ⇒ 不存在"文档说做、设计没做"的反向漂移 | ✅ 无反向漂移 |
| D-8 | **变更范围自述一致性** | `_PROGRESS` P3a 称"未改代码、未改 SAD/PRD/其他详设"；变更规模（3 个 `doc/detailed/*.md`）与之吻合；`server.md §11.5` 8 组增量项与正文落点可逐条对齐 | ✅ 一致 |

## 缺失测试用例

> 现有 `SRV-T46..T60`（15 条）+ `T-CACHE-32` 覆盖面总体良好（`*`、多值、`W/`、非法头、304 头组成、TTL 重生成、`<ttl>` 位置、降级不误 304、访问器契约均有）。以下为**经复核确认缺失**的用例（★ = 会掩盖真实缺陷，优先级最高）。

| # | 缺失用例 | 为什么必须有 | 建议落点 |
|---|---------|-------------|---------|
| 1 ★ | **INM 不匹配 ∧ IMS 本会命中 ⇒ 必须 200** | T56 只用**非法** IMS 验证优先级，未证明"会**忽略一个本来有效的 IMS**"——这是 RFC 9110 §13.1.3 的最强断言，也是本增量第 4 项不可妥协语义 | 新增 SRV-T56b（或强化 T56） |
| 2 ★ | **item 级 now 回落 ⇒ 跨 TTL 重生成 ETag 不变** | P1-01 的回归网：以缺失 `showtime`（eastmoney）/`ctime`（ths）/`time`（jin10）的 payload 调 **handler** 两次（而非复用 items 调 `generate_rss`）⇒ 断言 `_feed_etag` 相同 | 新增 SRV-T52b（**修 P1-01 后应转绿**） |
| 3 ★ | **范围纪律负向断言**：`/opml.xml`、`/`、任一 JSON 端点带 `If-None-Match`/`If-Modified-Since` ⇒ **恒 200 全量**（绝不 304） | BR-SRV-36/44 的范围边界**零覆盖**；一旦有人把 `etag=`/条件判定误接到公共路径，无网可拦 | 新增 SRV-T61 |
| 4 | **IMS 边界等值**：`If-Modified-Since ==` 发出的 `Last-Modified`（同秒）⇒ 304 | `<=` 的边界值未测（T51 只测未来/过去），而"客户端回显"正是最常见路径 | 扩 SRV-T51 |
| 5 | **INM 不匹配 ⇒ 200 且 body 为完整 RSS**（非空、item 数正确、`ETag` 为新值） | T48/T49 只断言状态码；"不匹配却回空体/304"是典型实现缺陷 | 扩 SRV-T48/T49 |
| 6 | **304 幂等重放**：带同一 ETag 连发两次 ⇒ 两次均 304，且 `feed_cache_put` 计数仍为 1、`Last-Modified` 不变 | T52 只做"改 TTL 后一次"；幂等与"不写缓存"的联合断言缺失 | 扩 SRV-T47 |
| 7 | **仅 IMS + 降级（`last_modified=None`）⇒ 200 且响应无 `Last-Modified`** | T59 只覆盖 INM；`last_modified=None` 时的 IMS 路径（BR-SRV-40）无用例 | 扩 SRV-T59 |
| 8 | **ETag 与内容编码无关**：`Accept-Encoding: gzip` 与 identity 两次 200 的 `ETag` **相同**；持 gzip 时代 ETag 重放 ⇒ 304 | T57 只断言"304 无 `Content-Encoding`"，未验证 BR-SRV-37"编码无关"的**核心推断**（gzip/identity 共享弱标签） | 扩 SRV-T57 |
| 9 | **HEAD + IMS**（不止 INM） | T54 只测 HEAD+INM；HEAD 与 IMS 组合是"两分支交叉"的空白格 | 扩 SRV-T54 |
| 10 | **200 与 304 的头逐字一致**（对同一请求做两次响应做 diff，而非两侧各自硬编码期望值） | T55 是"各自断言"，无法发现两侧同时漂移；`_send_not_modified` 与 `_send_text` 是**两份头构造逻辑**，需要交叉校验 | 新增 SRV-T62 |
| 11 | **`_feed_ttl_minutes` 边界**：ttl = 0/负数/59/60/61/180/181 ⇒ 1/1/1/1/2/3/4 | T58 只测 30/180；`max(1,…)` 与取整边界未锁定（配合 P2-07） | 扩 SRV-T58 |
| 12 | **`generate_rss(ttl=0)` 不得输出 `<ttl>0</ttl>`** | RSS 2.0 要求正整数；现伪代码会输出（P2-07） | 扩 SRV-T58 |
| 13 | **`W/` 前缀大小写口径**：`w/"…"` ⇒ 200（若采纳"仅字面 `W/`"），与 BR-SRV-39 改写后的措辞一致 | 当前文档表述自相矛盾，须由用例钉死 | 扩 SRV-T50 |
| 14 | **cache 侧**：`feed_cache_get_entry` 返回值的改写**不改变**容器条目的 `last_access`/`expires_at`（浅拷贝隔离的负例） | T-CACHE-32 已断言"改返回值不影响后续查询"，但未断言容器态字段未被污染 | 扩 T-CACHE-32 |

## 四、评审建议

### 4.1 已核实**无需修改**的项（正向结论，供编码者免检）

1. **弱 ETag 语义使用正确**：`W/"<sha256>"` 与"因规范化剔除了字节差异"这一理由是自洽的（RFC 9110 §8.8.3）；INM 用弱比较（§13.1.2）、服务端恒标 `W/`——无"强标签配弱比较"的混用。
2. **304 头组成与 `HEAD` 路径合规**；**独立 `_send_not_modified` 而非复用 `_send_text`** 是正确的结构性选择（§10#35）。
3. **HTTP/1.0 无 `Content-Length` 的 304 收尾安全**，且**不应**改发 `Content-Length: 0`（会违反 RFC 9110 §8.6）——只需补登记依据（P2-06）。
4. **INM 优先于 IMS 的实现严格**（`inm is not None` 短路）；`*`/多值/`W/`/空白/非法头→200 均正确。
5. **`feed_cache_get` 逐字不变**已实证（对照 `cache.py:906-914`）；**浅拷贝充分**；`feed_cache_get_entry` 无新增锁、无新容器字段。
6. **降级路径 2-tuple 同形状**，`last_modified=None` 正确禁用 IMS 且不发 `Last-Modified`；错误 feed 不会与成功 feed 的 ETag 混淆。
7. **范围纪律评分满**：未实现 keep-alive / `/opml.xml` / `/` / JSON 条件请求；未改路由、方法、200 头体语义、`generate_rss` 既有调用点。
8. **编号体系连续无冲突**；`<ttl>` 取值/位置/默认值/与 `Cache-Control` 同源均正确。

### 4.2 修复顺序建议

1. **先闭环 P1-01**（设计裁定：推荐"ETag 侧 canonical 投影"方案②，零体外变更、无需编排层批准体改动），并**同批**补 `SRV-T52b`；
2. **P1-02 / P1-03**（各一处文本修正）与 **P2-01/P2-07**（各一行代码级约束）同批落；
3. **D-1/D-2 漂移**交给编排层调度 system-architect/prd-writer（本次详设**不得**擅自改 SAD/PRD）；
4. 缺失用例 **#1/#2/#3/#4** 必须进 `tester` 的用例集；其余可随后补。

## 五、评审结论

**⚠️ 有条件通过**——**P0 阻断项为 0**；P1×3（生产版按阻断处理）×P2×10。

### P0 阻断项

**无。** 未发现崩溃、数据丢失、资金、安全类问题。

### 放行条件（按序闭环后即可进入 `code-developer`）

| # | 条件 | 验收方式 |
|---|------|---------|
| C1 | **P1-01 闭环**：ETag 规范化必须覆盖 item 级 now 派生 `pubDate`（② canonical 投影 ／ ① 确定性回落 二选一，由本设计裁定并写明理由），并在 §4.7 BR-SRV-37 把不变式改写为**双向**："内容未变 ⇒ ETag 不变（不误 200）**且** 内容变 ⇒ ETag 变（不误 304）" | 设计评审复审（diff 可验）；新用例 `SRV-T52b` 转绿 |
| C2 | **P1-02 闭环**：§10.1 补 `h.headers = {}`（或 patch `_not_modified`）；§11 自检计数改 **4**；注明 `_serve_feed` 自 v1.5 读 `self.headers` | 清单可逐条施工；`test_server_http.py` 4 条迁移后全绿 |
| C3 | **P1-03 闭环**：BR-SRV-43 / §10#33 / `_PROGRESS` 契约影响补"`<ttl>` 为聚合器缓存提示、最小 1 分钟、非时效保证，短线请用 SSE"，并列为 API.md/README/变更日志同步项 | 文本存在且被 §9 追溯 |
| C4 | **P2-01/P2-07 闭环**（低成本、防回归）：`dt.timestamp()` 移入 `try`；`generate_rss(ttl<=0)` 不输出 | 伪代码可验 |
| C5 | **缺失用例 #1/#2/#4 进入 tester 用例集**，`#3`（范围纪律负向断言）同批 | 用例 ID 存在、可复现 |
| C6 | **编排层登记**：SAD 回填（D-1）+ PRD/SAD 承接 AC 或明确以 API.md 承担（D-2）；对外文档三件（API.md/README/变更日志）列入放行前置 | 编排层回执 |

### 放行后仍存在的**已知残余风险**（登记，不阻断）

- **304 只省 body，不省回源**：TTL 到期仍回源重生成（§5.4 注已自陈）。若上游在窗口内静默改内容，客户端最长滞后一个 TTL 才看到——与"缓存 TTL 管上游新鲜度、ETag 管客户端带宽"的分工一致，但**应在 API.md 写明**，避免下游误以为 304 连上游压力也一并降低。
- **同一秒内两次错误 feed 的 ETag 相同** ⇒ 会命中 304（语义正确，但监控侧可能把"降级仍在持续"误读为"没变"）——建议 API.md 注明"降级 feed 不应作为 304 缓存的判断依据"。

## 变更记录

| 版本 | 日期 | 内容 |
|------|------|------|
| REV-DES-20260918-001 | 2026-09-18 | 首评。对象 `server.md` v1.5 / `cache.md` v1.5 / `_PROGRESS.md` P3a；结论 ⚠️ 有条件通过（P0×0 / P1×3 / P2×10）；含漂移检测 8 项、缺失用例 14 条；实证复核 `server.py:88-157/1188-1218/1249-1283/1335-1354`、`utils.py:145-169/210-269`、`cache.py:898-934`、`tests/test_server_http.py:309-360/400-458`、`config.md:291-292/322-323`、`SAD.md`（v1.7）、`prd`（v0.6）。 |

> 本报告仅依据文档交付物与参考契约文件的客观内容；不含对作者/创作意图的任何推断。评审不修改任何被评审文档。
