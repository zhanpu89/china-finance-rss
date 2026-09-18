# RSS 条件请求（ETag / Last-Modified / 304）· 代码评审报告

> **报告编号** CR-RSS-20260918-001 · **模式** `review+drift`（P5b 评审 + P7a 漂移检测合并）· **日期** 2026-09-18 · **评审人** code-reviewer
> **变更文件** `china_finance_rss/{server,cache,utils}.py`、`tests/test_server_http.py`（244+/43-）
> **设计权威** `doc/detailed/server.md` v1.7（§4.7 BR-SRV-36..44）· `cache.md` v1.6（BR-CACHE-32）· 需求 `_MEMORY_CACHE.md`
> **测试基线** `python -m unittest discover -s tests` ⇒ 467 OK（迁移后，未新增用例）
> **scope 外** `.opencode/scripts/*`（编排层工具另提交）· `doc/**`（P7b 处理，本报告仅判有无漂移）

## 总评

**核心专项 R1 的修复是成立的**：`_feed_etag` 的 canonical 投影确实把三类派生元数据的内容剔出了哈希区，三处"当前时间回落"出口全部被 `<pubDate>` 全量替换覆盖；反向（内容变 ⇒ ETag 变）除已登记的 `pubDate`-only 权衡外无新误 304。304 组成、条件头优先级、降级路径、cache 层兼容、`<ttl>` 生成、范围纪律**全部与 v1.7 设计逐项吻合**，未发现 P0/P1。最需要关注的三点是：① **本 change-set 对 R1 零测试覆盖**（T46–T62 属 P6c），C1 修复目前只有静态推理证据；② 详设 §10.1 漏列第 5 条测试迁移项（已被 code-developer 机械迁移，需回填）；③ `Last-Modified = 缓存写入时刻` 使 IMS-only 客户端在每个 TTL 边界仍收 200 全量（设计已取舍，建议 API.md 注明）。

## 评审结论

**⚠️ 有条件通过（无 P0 / 无 P1；P2×4 + 漂移 3 项）**

代码本身可放行；放行条件均为 **P6c 测试** 与 **P7b 文档回填**，不要求本轮改代码（见文末「放行条件」）。

## 问题清单（按最坏后果排序）

### P0（崩溃 / 数据丢失 / 资金 / 安全）—— 0 条

无。

### P1（功能缺陷 / 单点 / 性能退化）—— 0 条

无。R1 关键路径（ETag 抗抖动 / 不误 304）、304 组成、条件头优先级、降级路径、cache 层兼容均经证据链逐条确认成立（见 Dim 0–5）。

### P2（可维护性 / 规范 / 可选加固）—— 4 条，均不阻断

**P2-1** `china_finance_rss/server.py:1329/1333`：`_feed_etag(xml)` 与 `_not_modified(...)` 位于 `_guard` **之外**（`_guard` 只包 `_get_or_fetch_feed`）。逆向假设：当 `xml` 为非 `str`（handler 契约被未来改动破坏、或 stub 返回 `None`）时，`_LASTBUILDDATE_RE.sub(..., None)` 抛 `TypeError`，该异常**穿透 `do_GET`/`do_HEAD` 的 `except OSError`**（只捕 OSError/TimeoutError），连接中断而非 200 降级——而 `_guard` 的"任何 handler 异常都不得穿透"（BR-SRV-3/6.2#2）本应覆盖此场景。现状 5 个 handler 恒返回 `generate_rss` 的 `str`，故**非现实缺陷**，属纵深防御缺口。
→ 建议：`_serve_feed` 内对 `xml = str(xml)` 做一次归一，或把 ETag 计算放进 `_guard` 的成功分支；至少加一条注释说明"xml 恒为 str"的前提。`_send_text` 的 `body.encode` 同类（既有），可一并考虑。

**P2-2** `china_finance_rss/server.py:1297-1320`（BR-SRV-38 / `cache.py:922`）：`Last-Modified = entry['time']` 即 `feed_cache_put` 的**写入时刻**。证据链：TTL 到期 → `feed_cache_get_entry` miss → 回源 → 新条目 time=T1 > T0；仅带 `If-Modified-Since: T0` 的客户端得 `int(T1) <= int(T0)` 为假 ⇒ **200 全量**，即便内容逐字节未变。即"内容未变 ⇒ 304 零 body"对 **ETag-capable 客户端完全成立**，但对 IMS-only 客户端只在同一 TTL 窗口内成立（跨 TTL 边界必重取）。
→ 属设计显式取舍（`entry['time']` 是唯一可用时间源），**不要求改**；建议 P7b 在 `API.md` 注明"推荐用 ETag 条件请求；IMS-only 客户端在每个 TTL 边界会完整重取"（与 `_PROGRESS.md` 待办 ⑥ 同批）。

**P2-3** `china_finance_rss/server.py:1393-1410` 与 `~1431-1437`：`Cache-Control`（scope + `max-age=_cache_age()`）与 `Vary` 的构造逻辑在 `_send_text` 与 `_send_not_modified` 各写一份（约 4 行同源）。BR-SRV-41 硬要求"304 与同请求 200 同值"，两份实现存在未来单侧改动的漂移面（设计已用 SRV-T62 交叉 diff 网兜底）。
→ 记录不阻断；可选优化：抽 `_cache_headers(varies_on_host) -> (cc, vary)` 唯一来源，两处共用。是否重构由编排层决定。

**P2-4** `china_finance_rss/server.py:101-103`：eastmoney 的"无匹配 ⇒ 空 feed"提前返回是**第 6 个** `generate_rss(..., ttl=_feed_ttl_minutes())` 调用点，而详设 §1.1#13 / §5.4 / §10#33 均按每 handler 一处表述为"5 处"。
→ 见「漂移检测 D-2」；建议 P7b 回填（该选择本身**正确**，见下「SIDE-EFFECT #4 裁定」）。

## 评审维度详情

### Dim 0 — 契约一致性（最高优先级）

以 `doc/detailed/server.md` v1.7 §2.1 / §5.8 / §4.7 为唯一来源，逐项核对：

| # | 契约项（详设） | 实现证据 | 判定 |
|---|--------------|---------|------|
| 0.1 | 200 RSS **恒发 ETag**（`W/"<sha256>"`），有缓存条目时发 `Last-Modified` | `server.py:1388-1392`（`etag`/`last_modified` 非 None 才发）；`_serve_feed` 恒传 `etag`，`last_modified` 来自 `_get_or_fetch_feed` | ✅ |
| 0.2 | 条件命中 ⇒ **304**：无 body / 无 `Content-Encoding` / 无 `Content-Length` / 无 `Content-Type`；**带** `ETag`+`Cache-Control`+`Vary` | `_send_not_modified` server.py:1415-1439 仅 `send_response(304)` + ETag/Last-Modified/Cache-Control/Vary + `end_headers()`，**无** `wfile.write`、无 `Content-*` | ✅ |
| 0.3 | 条件头：`If-None-Match` **优先**，支持 `*` / 多值 / `W/` 弱比较；`If-Modified-Since` 秒级、非法忽略 | `_not_modified` 863-871（INM 存在即只看 INM）；`_if_none_match_matches` 819-837；`_if_modified_since_not_modified` 840-860 | ✅ |
| 0.4 | `_guard(shape='rss')` 成功与异常**同形状 2-tuple** | server.py:639-647（异常 `(generate_error_rss(...), None)`）；成功由 `_get_or_fetch_feed` 1297-1320 返回 2-tuple | ✅ |
| 0.5 | `feed_cache_get(path) -> str\|None` 签名/语义**不变**；新增 `feed_cache_get_entry` | `cache.py:927-934` 薄包装；`cache.py:906-924` 新访问器 | ✅ |
| 0.6 | `generate_rss(..., ttl=None)` 纯新增可选形参，`None` ⇒ 不输出 `<ttl>` | `utils.py:145-178`；`if ttl is not None and int(ttl) > 0:` 之前逐字为旧实现 | ✅ |
| 0.7 | BR-SRV-44 出范围项**不实现** | `RSSHandler` 无 `protocol_version`（全仓仅 `stream.py:1359`）；`/`、`/opml.xml`、JSON 分支无 ETag/条件判定 | ✅ |
| 0.8 | 5 RSS 路由经 `_serve_feed` 统一支持 GET/HEAD 条件请求 | `server.py:1232-1234`（`path in ROUTES` ⇒ `_serve_feed`）；`do_HEAD` 1149 与 `do_GET` 共用 `_handle_request` | ✅ |

**Dim 0 结论：契约一致，无偏差。** 全栈模式下的前端/小程序一致性（Dim 0.B/0.C/0.D）不适用（本变更无前端、无小程序）。

### Dim 1 — 数据与正确性（R1 核心，逐条证据链）

**1.1 canonical 投影是否真剔除三项派生元数据的内容** —— `_feed_etag`（server.py:799-816）：

- `<lastBuildDate>`：`_LASTBUILDDATE_RE = r'<lastBuildDate>[^<]*</lastBuildDate>'`，`count=1`（554 + 812）。`generate_rss` 唯一 channel 级元素 ⇒ 命中并置为 `<lastBuildDate/>`。✅
- `<ttl>`：`_RSS_TTL_RE`，`count=1`（555 + 813）。channel 级唯一（位置固定在 `</lastBuildDate>` 与 `<atom:link>` 之间）⇒ 命中。✅
- `<pubDate>`：`_PUBDATE_RE`，**不传 count（=0 全量）**（556 + 814）。item 多条 ⇒ 全量替换为 `<pubDate/>`。✅ 与设计「前二者 count=1、pubDate 全量」**完全一致**。

**1.2 三处"当前时间回落"出口重新定位（当前代码行号）** —— 三处回落值**全部**最终进入 `'pubDate'`，故全量剔除 `<pubDate>` 足以移出哈希区：

| # | 源 | 当前行号 | 证据 |
|---|----|---------|------|
| ① eastmoney `showtime` 失败 | `server.py:108-111` | `try: pubdate = parse_china_datetime_to_rfc822(showtime)` / `except Exception: pubdate = formatdate(timeval=None, ...)`（**回落行 = 111**）→ `'pubDate': pubdate`（117） |
| ② ths `ctime` 失败 | `server.py:135-138` | `try: ctime = int(item.get('ctime', 0))` / `except (ValueError, TypeError): ctime = int(time.time())`（**回落行 = 138**）→ `'pubDate': timestamp_to_rfc822(ctime)`（144） |
| ③ jin10 `time` 失败 | `utils.py:247-250` | `try: pubdate = parse_china_datetime_to_rfc822(item.get('time',''))` / `except Exception: pubdate = formatdate(timeval=None,...)`（**回落行 = 250**）→ `'pubDate': pubdate`（256） |

设计原文引用的 `server.py:107/133`、`utils.py:241` 是 v1.5/v1.6 写作时点的旧行号；当前实际为 **111 / 138 / 250**，语义一致、无遗漏。全仓再核：XML 相关的其余时钟源只有 `utils.py:160`（channel `lastBuildDate`，已剔除）、`utils.py:188` 与 `250`（`pubDate`，已剔除）；`parse_cls_items`/`parse_wallstreetcn_items` 用 `ctime`/`pub_ts or 0`（确定性，无当前时间回落）。**无第四个出口。** ✅

**1.3 反向：内容变 ⇒ ETag 变** —— 未剔除项（channel `title`/`link`/`description`、`<atom:link href=feed_url>`、item `guid`/`title`/`link`/`description`）全部在哈希区。逆向检查"同一 guid 下 title/link/description 变了却 ETag 不变"：三者均经 `escape_xml` 注入哈希串，且 `escape_xml` 是**单射**（`&`→`&amp;`、`<`→`&lt;` …，无碰撞映射）⇒ 任一字节变化 ⇒ 规范化串变化 ⇒ sha256 变化 ⇒ 200。**无新误 304。** 唯一"内容变而 ETag 不变"= 仅 `pubDate` 变化，属 BR-SRV-37 显式登记的**可接受权衡**。✅

**1.4 正则误命中** —— `escape_xml` 把 item content 的 `<` 转义为 `&lt;`，故 description/title/guid 含字面 `<pubDate>…</pubDate>` 时在最终 XML 中为 `&lt;pubDate&gt;…&lt;/pubDate&gt;`，正则不匹配。`[^<]*` 是 negated char class，**可匹配换行**，故含换行的值也不会破匹配/跨元素。`<ttl>` 同理。✅

**1.5 弱 ETag 比较** —— `_ETAG_PREFIX = 'W/'`（557）。`_if_none_match_matches` 对服务端标签与客户端候选**两侧都剥 `W/`** 再比 opaque tag（826/833-834）⇒ 弱比较。大小写敏感：候选 `w/"x"` 不 startswith `'W/'`，退化为 opaque tag 字面比较 ⇒ **不匹配 ⇒ 200**（与 BR-SRV-39 修正措辞一致）。`*`（831）与多值（827 `split(',')`）+ `strip()` 均正确。✅

**1.6 IMS 解析与异常面** —— `_if_modified_since_not_modified`（840-860）：`last_modified is None` ⇒ False；解析 → `dt is None` 检查 → naive 补 `timezone.utc` → `int(last_modified) <= int(dt.timestamp())` **全部在同一 `try`**，`except (TypeError, ValueError, OverflowError, OSError)`。`timestamp()` 的越界（OverflowError/OSError）不会穿透 `do_GET` 的 `except OSError` 之外 ⇒ 恒 200。✅

**1.7 INM 不匹配 ∧ IMS 本会命中 ⇒ 必须 200** —— `_not_modified` 在 `inm is not None` 时直接 `return _if_none_match_matches(...)`，**不读 IMS**（866-867）。故 `If-None-Match: "nope"` + `If-Modified-Since: <未来>` ⇒ False ⇒ `_serve_feed` 走 `_send_text(200, …, xml)` 发**完整 RSS 体**（而非 304/空体）。✅

**1.8 `<ttl>` 生成** —— `_feed_ttl_minutes`（789-796）= `max(1, (ttl+59)//60)`：30→1、180→3；边界 0/负/59/60/61/180/181 ⇒ 1/1/1/1/2/3/4 与设计一致。`generate_rss` 的 `ttl<=0` 守卫（`if ttl is not None and int(ttl) > 0`）杜绝 `<ttl>0</ttl>`。`generate_error_rss`（191）不传 ttl ⇒ 降级 feed 无 `<ttl>`。位置：`</lastBuildDate>` 之后、`<atom:link>` 之前（162-166）。✅

### Dim 2 — 并发

- **条件请求零新锁成立**（详设 §7.2#2）：`_feed_etag`/`_if_none_match_matches`/`_if_modified_since_not_modified`/`_not_modified` 均为纯函数或只读 `self.headers`；`feed_cache_get_entry` 复用既有 `_feed_cache_lock`。✅
- **LRU 副作用恰好一次**：`feed_cache_get_entry`（cache.py:916-924）在锁内 `move_to_end` + `last_access` 各一次；`feed_cache_get` 只调它一次（933），不产生第二次副作用；`_get_or_fetch_feed` 的 miss/fetch 路径调用三次（①②③ miss 无副作用、put 后命中一次）。**无"薄包装导致两次 move_to_end"**。✅
- **`_get_or_fetch_feed` 锁序未变**：`_feed_fetch_locks_lock` 取到即放（1310-1311）→ per-path 锁 → 锁内不持有 `_feed_cache_lock`（`feed_cache_get_entry/put` 自锁）。✅
- **同一 path 无并发写者**：`feed_cache_put` 仅由 `_get_or_fetch_feed` 在 per-path 锁内调用 ⇒ put 后二次 `feed_cache_get_entry` 拿到的必是刚写入的条目（1.5 节 ④）。✅
- 未同步共享可变状态 / 非原子读改写 / 集合并发修改：无新增。✅

### Dim 3 — 资源与性能

- ETag 成本：每次 RSS 请求一次 sha256(≈40KB) + 3 次 regex ≈ 0.1–0.2ms（详设 §5.4 已登记），远小于 `Cache-Control: max-age` 覆盖下的网络收益；缓存命中路径同样计算，属可接受固定开销。✅
- 304 路径：零 body、零 gzip、零 `feed_cache_put`（1415-1439 无写）⇒ 带宽与上游回源均不因 304 恶化（回源仍由 TTL 决定）。✅
- 无 N+1、无资源泄漏、无无界增长（`feed_cache` 上限由 policy 管）。✅

### Dim 4 — 安全

- **防缓存投毒未回归**：304 与 200 使用**同一** `varies_on_host=not PUBLIC_BASE_URL` 判定（`_serve_feed` 1332/1335/1339），`PUBLIC_BASE_URL` 未设时 `Cache-Control: private` + `Vary: Host, X-Forwarded-Host, X-Forwarded-Proto, Accept-Encoding`；ETag 依赖 `feed_url`（Host 派生）⇒ 不同 Host 得到不同 ETag，`Vary` 保证共享缓存不串号。✅
- Host 注入：`_base_url` 经 `_valid_host_header` 校验（非法 ⇒ localhost），ETag 输出为 hex，无注入/泄露面。✅
- 条件头解析为纯布尔，非法/超长/越界日期头恒 200，不抛、不 400/500 ⇒ 无 header-DoS 面。✅
- 无鉴权面/无敏感信息新增。✅

### Dim 5 — 结构与可维护性

- 命名、分层、注释质量良好：新函数集中定义在 `RSS conditional requests` 节（787-871），注释讲"为什么"（裸哈希会静默失效、`pubDate` 回落证据），符合项目规范。✅
- **重复逻辑**：`_send_text` 与 `_send_not_modified` 的 Cache-Control/Vary 各写一份（P2-3）。⚠️ 记录。
- **guarded 边界**：`_serve_feed` 的 ETag/条件判定在 `_guard` 之外（P2-1）。⚠️ 记录。
- 魔法数字：无新增裸 TTL（`_feed_ttl_minutes` 经 policy 派生）；`max(1, …)` 的 1 为 RSS 语义常量，可接受。✅

### Dim 6 — 前端

不适用（本变更无 `frontend/`、无小程序）。

### 逆向审查汇总

| 逆向问题 | 结论 |
|---------|------|
| 恶意/异常输入 | 非法 `If-Modified-Since`（`not-a-date`/`99`/空/越界年）⇒ False ⇒ 200；`If-None-Match` 空串/`"nope"`/小写 `w/` ⇒ 200；恒不 400/500。✅ |
| 竞态 | 条件判定纯函数；`feed_cache` 严格单锁；同 path 序列化。✅ |
| 依赖失效 | 上游失败 ⇒ `(error_xml, None)` ⇒ IMS 不可评估、ETag 与成功体不混淆 ⇒ 200 诊断 feed；缓存新鲜期内仍服务缓存（无降级）。✅ |
| 隐式假设 | 隐含"`xml` 恒为 str"（未在 guard 内断言）——P2-1。 |
| 性能悬崖 | 无随输入规模放大的路径（regex 线性、sha256 线性）。✅ |
| 测试盲区 | **R1 与 304 组成在本 change-set 零覆盖**（T46–T62 属 P6c）——见放行条件 ①。⚠️ |

### SIDE-EFFECT 逆向核对（P5b 强制）

| # | code-developer 自报受影响点 | 逆向假设 | 裁定 |
|---|---------------------------|---------|------|
| 1 | `_get_or_fetch_feed` 返回 2-tuple | 除 `_serve_feed` 外是否有直接调用方按 str 用？ | 全仓仅 `_serve_feed`（1326）与测试；无生产断链。✅ |
| 2 | `_guard(shape='rss')` 两路同 2-tuple | 是否有调用方按裸 str 解包？ | 仅 `_serve_feed`；`GuardTests.test_rss_degrade_is_valid_feed` 已迁移（test_server_http.py:76-82）。✅ 但**详设 §10.1 漏列该迁移**（D-1 漂移）。 |
| 3 | `_serve_feed` 200 恒发 ETag、条件命中 304 | 旧客户端是否因新增响应头受影响？ | 只增头，body/状态码在无条件下逐字不变（BR-SRV-42 / §6.1）。✅ |
| 4 | 5 handler 多出 `<ttl>`（盘 1/非盘 3），eastmoney 空 feed 也带 ttl | 是否造成 ETag/表示不一致？ | `<ttl>` 已从 ETag 剔除；空 feed 两条路径（regex 无匹配 / `LivesList` 空）**均带 ttl**，表示一致。**该选择合理**。唯一问题：详设写"5 处"，实现为 6 个调用点（D-2 漂移，非缺陷）。✅ |
| 5 | `_send_text` 尾部追加 `etag=None, last_modified=None` | 既有调用点是否被位置传参破坏？ | 既有调用点全为关键字传参且不传这两参；grep 无位置传参冲突 ⇒ 其余端点响应头零变化。✅ |
| 6 | `feed_cache_get` 改为薄包装 | 是否与改动前逐字等价？ | 对照：同 `_feed_cache_lock`、`not entry or now >= expires_at`、`move_to_end`、`last_access=now`、返回 `xml`；新实现多一次 `time.time()` 调用（微秒级、无行为差异）。✅ |
| 7 | `generate_rss` 新增 `ttl=None` | 默认输出是否逐字节相同？ | ttl=None ⇒ 新增分支为 False，其余行与旧实现逐字一致。✅ |
| 8 | 测试桩/断言迁移 | 是否削弱断言/假绿？ | FeedDoubleCheck 打桩改为 `feed_cache_get_entry` 且断言 2-tuple、仍断言 `calls['n']==1`；BaseUrlHardening 补 `h.headers={}` 且 `_get_or_fetch_feed` 桩改 2-tuple，`varies_on_host` 断言未放宽；GuardTests 断言 2-tuple + `last_modified is None`（新增强断言）。**无削弱**。✅ 但 `FeedDoubleCheckTests` 打桩条目仅含 `xml/time`（缺 `last_access/expires_at`）——server 只读前两键，可接受。 |

## 漂移检测

> P7a 合并模式：对每个变更模块核对实现 ↔ `server.md` v1.7 / `cache.md` v1.6；核对 `_PROGRESS.md` 已知 8 项待办是否遗漏。

### D1 契约核对（实现 vs 详设）

**✅ 无实现侧漂移。** `server.md` v1.7 的 BR-SRV-36..44、§2.1 yaml、§5.1/§5.4/§5.8 伪代码、§6.2#8 不变式、§10#32-#37 与实现**逐项一致**；`cache.md` v1.6 的 BR-CACHE-32（`feed_cache_get_entry` 浅拷贝、同源 LRU、`feed_cache_get` 薄包装）与 `cache.py:906-934` 一致。指定调用点（`server.py:107/133`、`utils.py:241`）为旧行号，当前实际 111/138/250，语义无误（见 Dim 1.2）。

### D2 DOC_SYNC 追溯

本 change-set 的 code-developer 输出未携带 `>>DOC_SYNC:` 标记（评审入参亦未提供）。按 `_PROGRESS.md`「契约影响」节，本次代码引入的对外契约变化为：RSS 200 新增 `ETag`/`Last-Modified`、新增 `304`、feed XML 新增 `<ttl>`、304 无 `Content-Encoding` 约定 —— 对应 `_PROGRESS.md` 契约影响 #1–#5 与 8 项编排层待办，**均在 P7b 待办清单内、未被遗忘**（见 D4）。

### D3 规范合规

新代码遵守项目规则：无裸 TTL 字面量（`_feed_ttl_minutes` 经 `cache_policy('feed')` 派生）、无新增第三方依赖、import 面与详设 §1.3 白名单一致（+`hashlib`/`datetime.timezone`/`parsedate_to_datetime`）、注释解释设计权衡、纯函数无副作用。✅

### D4 `_PROGRESS.md` 已知 8 项待办核对

| # | 待办 | 本轮代码是否触碰/遗漏 | 结论 |
|---|------|---------------------|------|
| ① | SAD 回填 RSS 条件请求（P1 级契约缺口） | 未触碰（属 system-architect） | 仍待办，无新增漂移 |
| ② | PRD 新增 AC | 同上 | 仍待办 |
| ③ | （编号空缺，原文如此） | — | — |
| ④ | "本专项 R1" 与 SAD/PRD R1–R20 同名不同义 | 未触碰 | 仍待办 |
| ⑤ | API.md/README/变更日志补 ETag/Last-Modified/304/`<ttl>` + "`<ttl>` 非时效保证" | 未触碰；代码已具备可文档化行为 | 仍待办（放行前置） |
| ⑥ | "304 只省 body 不省回源" + "降级 feed 不作 304 缓存判断依据" | 代码行为与待办描述**一致**：304 不写缓存、TTL 到期仍回源；降级 feed ETag 稳定可由同一表示 304 | 仍待办（建议 API.md 补 P2-2 的 IMS-only 说明） |
| ⑦ | `_PROGRESS` 契约影响 #6 由"可选"改必做 | 未触碰 | 仍待办 |
| ⑧ | §10#37 / BR-SRV-44 出范围项无反向漂移 | **实现确认未做** keep-alive/`/opml.xml`/JSON 条件请求 | ✅ 无反向漂移 |

**未发现 code-developer 新增的、需 SAD/PRD 承接的漂移。** 8 项待办与本次实现无冲突、无遗漏。

### D5 本次发现的文档缺口（需 P7b 回填，均为"文档滞后于代码"）

- **D-1（对应 §10.1 / §11 计数）**：详设 §10.1「既有测试必改清单」列 **4 条** server_http 打桩迁移（FeedDoubleCheck ×2 / BaseUrlHardening 2-tuple / BaseUrlHardening `h.headers={}`），**漏列第 5 条** `GuardTests.test_rss_degrade_is_valid_feed`（实现已按 2-tuple 机械迁移，见 `tests/test_server_http.py:75-82`）。建议：§10.1 补第 5 条，§11 自检计数"迁移 4 条"→"**5 条**"，并在 `_PROGRESS.md` v1.7 计数口径（总 64 / 新增 19 / 迁移 4）同步。
- **D-2（对应 P2-4）**：详设 §1.1#13 / §5.4 / §10#33 表述"5 个 handler 传 `ttl=_feed_ttl_minutes()`"，实现为 **6 个 `generate_rss(..., ttl=...)` 调用点**（`server.py:89/101/120/147/250/264`，eastmoney 含"无匹配空 feed"提前返回 101-103）。建议 §5.4/§10#33 补一句"eastmoney 的两个 `generate_rss` 出口（常规 + 空 feed）均带 `<ttl>`；因 `<ttl>` 已剔除出 ETag，两路径表示一致"。
- **D-3（测试文档 vs 测试代码，属 P6c 承接）**：`cache.md` v1.6 声明 §8 T-CACHE-32 扩"浅拷贝隔离负例"，但 `tests/test_cache.py` **尚无 `feed_cache_get_entry` 引用**（最小复现：grep 0 命中）。本 change-set 明确不新增用例（467 OK），故属 P6c 待补项，**非本轮漂移**，登记以免 P6c 遗漏。

### 漂移检测小结

**✅ 无实现侧漂移；⚠️ 3 项文档滞后（D-1/D-2 建议 P7b 回填；D-3 归 P6c）。** 8 项已知编排层待办未被遗漏，亦无新增需 SAD/PRD 承接的漂移。

## 修复建议（按优先级）

1. **（P2-1，可选）** `server.py:_serve_feed`：`xml = str(xml)` 归一，或把 `_feed_etag`/`_not_modified` 纳入 `_guard` 保护，杜绝非 str xml 穿透 `do_GET`（现状不可达，纵深防御）。
2. **（P2-3，可选）** 抽取 `_cache_headers(varies_on_host)` 供 `_send_text`/`_send_not_modified` 共用，消除 304/200 头漂移面（T62 已在 P6c 设计为交叉网）。
3. **（D-1/D-2，P7b）** 回填 `server.md` §10.1 第 5 条迁移项 + §11 计数 4→5；回填 eastmoney 第 6 个 `<ttl>` 调用点表述。
4. **（P2-2/待办 ⑤⑥，P7b）** `API.md` 补：IMS-only 客户端在每个 TTL 边界会完整重取（推荐 ETag 条件请求）；"304 只省 body、降级 feed 不作 304 缓存判断依据"。

## 放行条件

**代码侧：通过，无需修复即可合入。** 以下条件为进入下一阶段前必须闭合的**非代码**项：

- **①（P6c，必须）** 实现 §8 的 SRV-T46–T62（19 条）。其中 **`SRV-T52b` 必须按 v1.7 / P2-a patch 受控时钟**（`srv.formatdate` / `srv.time.time` / `utils.formatdate` 使两次回落确定取 `t`/`t+1`），并声明红/绿方向 + 补"仅 `<pubDate>` 不同 ⇒ `_feed_etag` 相同"的纯函数断言；否则 C1（`pubDate` 全量剔除）**无有效验收证据**。另补 T61（`/opml.xml`、`/`、JSON 恒 200 且无 ETag）与 T62（200/304 头逐字 diff）以锁死范围纪律与头一致性。
- **②（P6c，必须）** 补 `cache.md` v1.6 §8 T-CACHE-32 的"浅拷贝隔离负例"（D-3），确认 `feed_cache_get_entry` 返回值改动不污染容器条目。
- **③（P7b，必须）** 闭合 D-1/D-2 文档回填 + 待办 ⑤（API.md/README/变更日志的 ETag/Last-Modified/304/`<ttl>` 语义与"`<ttl>` 非时效保证"）——`_PROGRESS.md` 已将其标为放行前置。
- **④（P7b，建议）** 待办 ①②⑦（SAD/PRD 回填）与该专项编号统一（`US-RSS-1`/`AC-RSS-1`）。

> 评审范围声明：本报告未运行测试（入参已提供 467 OK 基线，且 P5b 不新增用例）；Dim 1 的 R1 结论为静态证据链推理——这正是放行条件 ① 存在的原因。

