# RSS 条件请求（ETag / Last-Modified / 304）· 对抗性盲审报告

- **模式**：`>>MODE: blind`（P8 对抗性盲审，编排器终点前门禁）
- **需求原文**：用户原话「做B方案」；B 的不可妥协项 = 5 个 RSS feed 加 `ETag`/`Last-Modified` + `304`（内容未变 ⇒ 304、零 body）、加 RSS `<ttl>`、对外契约只增不改、功能必须真正生效（不得退化成永远 200）。
- **契约依据**：`doc/detailed/server.md` §4.7（BR-SRV-36..44）/ §2.9 / §2.10 / §5.4 / §5.8；`doc/detailed/cache.md` BR-CACHE-32。
- **改动范围**：`modules: server, utils, cache | endpoints: /cls/telegraph, /eastmoney/kuaixun, /ths/kuaixun, /jin10/flash, /wallstreetcn/live（经 _serve_feed）`。
- **入参纯净性说明（如实披露）**：本轮一条跨仓库 `grep`（pattern `If-Modified-Since|IMS|Last-Modified`）把命中行打印到了 `doc/review/**`、`doc/tester/**`、`_PROGRESS.md`、`API.md` 上。这是**非预期的内容曝光**，不属允许的入参。本报告**不引用**上述文件作为证据；下述每条发现均可由源码本身独立复现。若编排层要求严格零污染，请以本披露为准，必要时重跑一次「只读源码」的盲审。

---

## 总评

条件请求的**核心安全网是成立的**：`_feed_etag` 的 canonical 投影（剔 `lastBuildDate`/`ttl`/全量 `pubDate`）确实把三类"每次重生成即变"的派生元数据移出了哈希区，且反向（真内容变 ⇒ ETag 变）无新误 304 —— 我逐条核对了 5 个 handler 的 body 来源，未发现设计者遗漏的时钟/随机源。**但我找到 2 个 P1 与 5 个 P2**：最要紧的是「**IMS-only 客户端在每个缓存 TTL 边界必然拿 200**」使"内容未变 ⇒ 304"只在 ETag 通道成立；以及「**源站 feed 缓存只按 path 键，而 body/ETag 却依赖请求 Host**」使 `Vary` 给出的是**虚假的**跨 Host 隔离承诺，一次伪造 Host 即可在 TTL 内改写所有客户端的订阅链接。**未发现 P0。**

---

## 问题清单

### P1-1 `Last-Modified = 缓存写入时刻` ⇒ IMS-only 客户端跨 TTL 边界永远 200，不可妥协项 #1 只在 ETag 通道成立
`china_finance_rss/cache.py:950` · `china_finance_rss/server.py:1307-1320` · `server.py:1390-1392` · `server.py:858`

**证据链**：`feed_cache_put` 在**每次** miss/刷新时都写 `'time': now`（cache.py:950），**即使本次回源重生成的字节与上一条目逐字相同**；`_get_or_fetch_feed` 把该 `time` 作为 `last_modified` 返回（server.py:1307/1309/1315/1320）；`_serve_feed` 把它原样发成 `Last-Modified`（server.py:1390-1392）；`_if_modified_since_not_modified` 的判定是 `int(last_modified) <= int(ims_epoch)`（server.py:858）。

**触发条件（可复现）**：
1. `GET /cls/telegraph` → 200，响应头 `Last-Modified: T0`（feed TTL = 30s 盘中 / 180s 非盘）。
2. 等待 > TTL（或 `cache_mod.feed_cache.clear()` 模拟 TTL 到期）。
3. `GET /cls/telegraph` + **仅** `If-Modified-Since: T0`（无 `If-None-Match`）。
4. 即使上游内容逐字节未变 → 缓存 miss → 回源重生成 → `feed_cache_put` 写 `time = T1 > T0` → `int(T1) <= int(T0)` 为假 → **200 全量**。

**后果**：RSS 阅读器中相当一部分只回显 `If-Modified-Since`（不实现 `If-None-Match`）；而 `<ttl>1</ttl>`（=60s）**恰好 ≥ 盘中 TTL(30s)**，它们按推荐节奏轮询时**每次都在 TTL 之后**，于是每次都拿 200 完整体 —— 带宽目标对这类客户端几乎为零收益。这就是需求原文点名的"等于没做"，只是发生在 IMS 通道而非 ETag 通道。

**测试盲区**：`tests/test_server_http.py:1188-1205` 的 IMS 用例（未来/过去/等值）全部是**同一缓存条目内**的背靠背请求，**从不跨 TTL 边界**；唯一跨 TTL 的用例 `test_t52b_end_to_end_cross_ttl_304`（:1279）用的是 `If-None-Match`。故该缺陷对现有 64 条用例**结构性不可见**。

**建议（择一，交编排层裁决）**：
- (a) 回源后若 canonical 投影后的 ETag 与前一条目相同，则**沿用前一条目的 `time`** 作 `Last-Modified`（表示"内容未被修改"的语义也比"缓存重写时刻"更准确）；或
- (b) 明确把验收口径收窄为「ETag-capable 客户端」，并在 API 文档写明 IMS-only 客户端跨 TTL 必重取（若采用此路，本条降为 P2，但必须在验收单上显式登记，不能默认"内容未变 ⇒ 304"已对所有客户端成立）。

---

### P1-2 源站 feed 缓存按 `path` 键，body/ETag 却依赖请求 `Host` ⇒ `Vary` 的跨 Host 隔离是虚假的；一次伪造/畸形 Host 可在 TTL 内改写所有客户端的 `<atom:link>`
`server.py:1324` · `server.py:1342-1358` · `server.py:1332` · `server.py:799-816` · `cache.py:906-924` · `cache.py:937-954`

**证据链**：`_serve_feed` 构造 `feed_url = base_url + path`（server.py:1324），`base_url` 在 `PUBLIC_BASE_URL` 未设时来自**请求头**（`X-Forwarded-Host`/`Host`，server.py:1352-1355）；**非法 Host 静默回落**到 `http://localhost:{PORT}`（server.py:1356-1358）。该 `feed_url` 进入 `<atom:link>`（utils.py:164-166）因而进入 ETag（server.py:799-816）。但 `feed_cache` 只按 `path` 键（cache.py:950 / 906-924 / 937-954），`varies_on_host` **只影响响应头**（server.py:1332 → 1402-1403 / 1434-1437），**从不参与缓存键**。

**触发条件（可复现，`PUBLIC_BASE_URL` 未设）**：
```
GET /cls/telegraph   Host: attacker.example        → 200；缓存体开头的 <atom:link href="http://attacker.example/cls/telegraph">
GET /cls/telegraph   Host: legit.example           → TTL 内命中缓存 → 同一体内含 attacker.example 链接（Vary: Host… 仍照发）
GET /cls/telegraph   Host: a@b（格式非法）          → 非法回落到 localhost → 缓存体被改成 http://localhost:PORT/...
```
被污染的 ETag 还会被合法客户端通过 304 **持续"确认"**：持该 ETag 的客户端在 TTL 内每次重验证都得 304，一直复用含攻击者链接的副本。

**后果**：① 订阅链接被改写（link hijack），影响该 feed 的全部下游读者，持续到 TTL 结束；② `Vary: Host, X-Forwarded-Host, X-Forwarded-Proto` 只保护**下游共享缓存**，源站自身仍在跨 Host 串号，头与实际行为不符，给运维/下游错误的安全预期。

**定性说明（不夸大）**：这套「host-blind 缓存 + 请求派生 feed_url」在 v1.2 即存在，不是本 change-set 引入；但本 change-set 把 `_serve_feed` 变成了 ETag/304/Vary 的载体，**新代码建立在这个有缺陷的键之上**，故列入本报告。按"无数据越权、无认证边界、窗口受 TTL 限制"判为 **P1 而非 P0**。

**建议**：`PUBLIC_BASE_URL` 未设时，feed 缓存键改为 `(path, feed_url)`（或 `(path, normalized Host)`）；或让 body 中 `feed_url` 与请求 Host 解耦。若判定为存量问题不本轮修，至少应把 `Vary` 的语义在 API 文档降级说明。

---

### P2-1 `<pubDate>` 全量剔除 ⇒ 仅 pubDate 变化时静默 304；同批 `<ttl>`/`<lastBuildDate>` 也只改头不改体
`server.py:556` · `server.py:814` · `server.py:812-813`

上游更正某条 item 的 `pubDate`（同一 `guid`、title/description 未动）时 ETag 不变 ⇒ 持旧 ETag 的客户端永远 304，直到其它字节变化。同理会话边界 `<ttl>1→3</ttl>`、`<lastBuildDate>` 变化时，304 只更新响应头（`Cache-Control` 用新值），客户端体里仍是旧 `<ttl>`/旧 `lastBuildDate`。**这是设计已登记的取舍**（`guid` 才是身份，剔除是为了防"回落时钟"导致永远 200），本报告不主张推翻，但要求把它作为**显式验收项**登记（"pubDate-only 变更对下游不可见"）。
验证缺口：现有用例只断言期望方向（`t52b` 同 ETag）与 title 变化 ⇒ 200（`t53`），**没有**一条负向用例声明"pubDate-only 变化**不会**触发 200"。

**建议**：在测试中补一条显式的"pubDate-only ⇒ 304（已登记取舍）"断言，防止未来有人把它当 bug 反向修掉；并在 API 文档写明该窗口。

---

### P2-2 `<ttl>`/feed 缓存时间源自 `cache_policy('feed')`，`Max-Age` 源自 `cache_policy('news_url')` —— 两套权威，当前同值但可静默漂移
`server.py:795`（`_feed_ttl_minutes` 读 `feed`）· `server.py:1316`（feed 缓存 TTL 读 `feed`）· `server.py:1368` + `server.py:531-533`（`_cache_age` 把 5 个 RSS 路径映射到 `news_url`）

今天 `DOMAIN_MATRIX` 的 `feed` 与 `news_url` 同为 L3（30/180），所以 `<ttl>`、缓存新鲜度、`Max-Age` 三者一致。但三者由**两个域**分别派生：改 `feed` 的 tier 会让"`<ttl>`/缓存 TTL"变而 `Max-Age` 不变；改 `news_url` 反之。契约把 `Cache-Control` 明确定为 `news_url` 域，`<ttl>` 定为 `feed` 域，这是可复现的漂移面。

**建议**：让 `<ttl>` 与 `Max-Age` 共用同一域的 ttl（或在契约里把"两域必须同 tier"写成不变量并加断言）。

---

### P2-3 成功回源也可能返回"有 ETag、无 Last-Modified"的 200
`server.py:1316-1320`

`feed_cache_put` 后第三次 `feed_cache_get_entry(path)` 若因过期（`_expires_at` 有 ±20% 抖动，`CACHE_JITTER=0.2`，cache.py:36/108-111）或被并发**其它 path 的 `feed_cache_put` 触发 cap 淘汰**（cache.py:946-949）而返回 `None`，则 `last_modified=None`（server.py:1320），于是 200 只有 `ETag` 没有 `Last-Modified`。同一表示的相邻响应可能一会儿有一会儿没有，且 IMS-only 客户端拿不到可回显的校验器。影响小，但属"成功路径可产生半套校验器"的非预期态。

**建议**：`feed_cache_put` 返回写入的 `time`（或让 `_get_or_fetch_feed` 直接使用 `put` 时的时间），不再二次查询，消除该窗口。

---

### P2-4 无 304 / 条件命中的可观测性 ⇒ 带宽目标在生产无法验证
`server.py:1415-1439`（304 分支不产生任何计数）· 全文 `grep 304` 无 metrics 调用

需求的可验收结果是"下游省 ~37–45KB/次"。当前 `/healthz` 的 metrics 只有 `http_503_total` 之类，**没有** `http_304_total`（或 conditional-hit/cache-hit 计数），运维无法观测"到底省了多少"、也无法在回归时发现 304 命中率骤降（例如 pubDate 抖动回归 → 全 200，正是本专项最怕的静默失效）。这是"功能真正生效"缺少的观测闭环。

**建议**：在 304 分支加一个计数器（如 `http_304_total` / `rss_not_modified_total`）并在 `/healthz` 暴露。

---

### P2-5 HTTP/1.0 下的 304 无 `Content-Length`：RFC 合规但存在中间件收尾风险
`server.py:1120-1123`（`RSSHandler` 未设 `protocol_version` ⇒ HTTP/1.0）· `server.py:1426-1438`

304 无 body、不发 `Content-Length`、不发 `Content-Encoding`（与 BR-SRV-41 一致，`http.client` 也按 204/304 特例读零长，测试 t47/t62 已验证）。但 HTTP/1.0 下 `Content-Length` 是要靠"连接关闭"兜底的，个别按 `Content-Length` 排队的代理/老旧客户端可能把无长 304 当作截断。属**兼容性风险**而非缺陷；BR-SRV-44 已把 `protocol_version → 1.1` 登记为出范围项。

**建议**：维持现状，但在 API 文档标注"本服务为 HTTP/1.0 响应，304 以连接关闭收尾"；若下游反馈异常再单独立项升级 1.1。

---

### P2-6 测试质量：3 处结构性缺口 / 一处"靠陈旧缓存才能过"的断言
`tests/test_server_http.py:1188-1205` · `:1342-1360` · `:1279-1292` · `:1131-1144`

- **缺跨 TTL 的 IMS 用例**（见 P1-1）：现有 IMS 用例全在同一条目内，无法捕获 P1-1。
- **`test_t55`（:1342-1360）依赖"陈旧缓存"成立**：它先用真实 `PUBLIC_BASE_URL` 取 200（缓存体里的 `feed_url` 与随后 patch 的配置**不一致**），再 patch `PUBLIC_BASE_URL=''` / `='https://feeds.example.com'` 用同一 ETag 请求并断言 304。若在初始 200 后清一次 `feed_cache`，因 `feed_url` 参与哈希，ETag 必变、断言转红。也就是说该用例**并没有独立证明** 304 的 `private`/`Vary` 组合，只是复用了旧条目（生产不会运行时切换 `PUBLIC_BASE_URL`，所以不算产品缺陷，但作为门禁证据偏弱）。
- **无「`If-None-Match` 为空 / 纯空白」用例**：`_if_none_match_matches`（:827-830）对空 token 直接跳过返回 False；实现正确，但没被锁死；同理无 `If-None-Match` 超长列表的健壮性用例。
- **无跨 Host 体正确性用例**（见 P1-2）：`test_t53`（:1310-1311）只断言"不同 Host ⇒ ETag 不同"，没有断言"Host B 不该拿到 Host A 的 `atom:link`"。

**建议**：补 4 条用例 —— ① IMS-only 跨 TTL（预期 **200**，把 P1-1 变成可跟踪的显式行为）；② 空/空白 `If-None-Match` ⇒ 200；③ 不同 Host 的 body 中 `atom:link` 正确性（或明确断言当前 host-blind 行为并存档）；④ `feed_cache_put` 恰好写入的 `time` 被用作 `Last-Modified`（覆盖 P2-3）。

---

## 逆向审查（❓ 逐项）

- ❓ **逆向：恶意输入** —— `If-None-Match`/`If-Modified-Since` 的解析面（server.py:819-860）对 `*`、逗号多值、`w/`、空值、乱码日期都只返回布尔，不抛、不回显，无注入。**未发现 500**。唯一反射面是服务端自定义的 `W/"<hex>"`，不受客户端影响。
- ❓ **逆向：竞态** —— `_get_or_fetch_feed` 的响应是 `(xml, time)` 同源快照（server.py:1307-1320），不存在"旧 ETag 配新 body"。per-path 锁 + 双检逻辑正确（cache 侧 LRU/过期判定在 `_feed_cache_lock` 内，cache.py:916-924）。
- ❓ **逆向：依赖失效** —— 回源失败 ⇒ `_guard` 返回 `(error_xml, None)`（server.py:639-647），IMS 不可评估、降级 ETag 与成功体不同，不会互相混淆。**正确**。
- ❓ **逆向：隐式假设** —— 唯一站不住的隐式假设是"请求 Host 不影响缓存内容"（P1-2）。
- ❓ **逆向：性能悬崖** —— 每次 RSS 请求都 `sha256(≈40KB)`（server.py:815），量级 0.1–0.2ms，非悬崖。
- ❓ **逆向：测试盲区** —— 见 P2-6。

---

## 实际读过的文件 / 行号范围（零上下文取证）

- `china_finance_rss/server.py`：全量 1–1709（重点 51-60、554-557、789-871、1120-1148、1297-1439、1503-1504）
- `china_finance_rss/cache.py`：全量 1–1006（重点 906-954、108-111）
- `china_finance_rss/utils.py`：全量 1–325（重点 145-191）
- `china_finance_rss/config.py`：1–487（重点 300-359、389-487）
- `doc/detailed/server.md`：1-260、455-574、1000-1179、1590-1729（§2.9/§2.10/§4.7/§5.4/§5.8）
- `doc/detailed/cache.md`：6、177-183、324、468（BR-CACHE-32）
- `tests/test_server_http.py`：1–1494（重点 316-380、1007-1490）
- `tests/test_cache.py`：229–348
- `tests/test_server.py`：1–70
- 跨仓库 `grep`：`feed_cache_get|feed_cache_put|generate_rss|_send_text|_feed_etag|_not_modified|…`、`If-None-Match|If-Modified-Since|…`、`protocol_version|Connection`、`PUBLIC_BASE_URL`、`304`
- **未主动打开**：`doc/review/**`、`doc/tester/**`（内容因上述 grep 命中行被动曝光，已在文首披露）

---

## 评审结论

**⚠️ 有条件通过（不阻断本轮发布，但 2 个 P1 需编排层裁决优先级）**。

**是否存在 P0：无。** 未发现崩溃 / 数据错误 / 越权 / 会返回陈旧 body 的误 304。核心 R1（内容未变 ⇒ ETag 不变、内容变 ⇒ ETag 变）经源码逐条核对成立，canonical 投影覆盖了全部三处"当前时间回落"；304 组成与条件头优先级符合 BR-SRV-36..44。需要编排层拍板的是：**P1-1（IMS-only 客户端跨 TTL 永远 200 —— 要么修时间源，要么把验收口径收窄并登记）** 与 **P1-2（源站 feed 缓存 host-blind 与 `Vary` 承诺不符 —— 要么改缓存键，要么把该风险显式登记）**；其余 5 条 P2 建议随下一轮修复批次一并收口（P2-4 的可观测性尤其建议优先，因为它决定本专项"省带宽"能否被生产验证）。
