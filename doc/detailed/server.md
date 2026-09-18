# server.py 详细设计

> **版本** v1.14 · **状态** 增量设计（★ v1.14 实现事实对齐：`SRV-T73` 超时余量（实测 15s）+ `join` 后 `is_alive` 断言已落地；溯源更正 **SAD v1.11 / PRD v0.9**；**P3a · RSS 条件请求 ETag / Last-Modified / 304**；P3a-r1 评审定向修 · P3a-r2 复审 P2 收口 · P7b 漂移回填 D-1/D-2 · **P8 对抗性盲审 F1–F7 契约化** · **P8 F8 契约化：feed 取数锁表有界收敛** · **P2-1 fail-safe 措辞收口 + 溯源更正** · **F8 并发变体测试契约（`SRV-T73`）+ `feed_fetch_acquire` 实现约束**；**最后一轮契约收口：`SRV-T73` 证伪面收窄 + 超时余量/线程结束断言**，**只增不改**）· **日期** 2026-09-18 · **作者/产出** task-decomposer
> **v1.14 变更（实现事实对齐 + 溯源更正 · 只改文档，不改代码）**：① **【溯源更正】** 头部上游 **SAD v1.9 → v1.11**、**PRD v0.8 → v0.9**（`config.md` v1.5 / `cache.md` v1.13 已就地更正；权威以各文档头部为准）——**最后一处溯源滞后闭环**。② **【`SRV-T73` 实现对齐】** v1.13 契约要求的**超时余量**与**线程结束证据**已落地于 `tests/test_server_http.py::test_t73_concurrent_distinct_hosts_bounded_and_in_sync`：等待放行 / `join` 均用 **15s**（≥ v1.13 建议的 10s），并在 `join` 后逐一 **`assertFalse(t.is_alive())`**；在飞断言 `1 <= len(_feed_fetch_locks) <= K`（K=8）、`len(_feed_fetch_refs) == len(_feed_fetch_locks) == K`，返回后两表均 `0`、`state['calls'] == K`（每键恰一次取数）。③ **【接口权威栏】** `cache.md` v1.12 → **v1.13**、`metrics.md` v1.5 → **v1.6**。**无 BR 语义变更 / 无接口变更 / 测试计数仍 75（`T73` 改写、不新增编号）/ 偏差仍 45 项**；**未改代码 / SAD / PRD / API.md / README.md / `.opencode`；`cache.md` → v1.13、`metrics.md` → v1.6、`_PROGRESS.md` 同步。**
> **v1.13 变更（最后一轮契约收口：`SRV-T73` 证伪面收窄 + 超时余量 · 只改文档，不改代码）**：① **【P2-4 / 证伪面收窄】`SRV-T73` 的取数桩从不抛异常 ⇒ T73 不能证伪"`release` 不在 `finally`"**（成功路径上"`with` 后裸 `release`"与"`finally release`"行为相同）——该证伪**归 `SRV-T72`**（异常路径计数归零）。**T73 的证伪面收窄为**：**「按累计增长 / 两表（`_feed_fetch_locks` 与 `_feed_fetch_refs`）不同步 / 上界 > K」**；T73 **保留「两表相等 + 在飞上界 ≤ K + 全部返回后归零」三条断言不变**。② **【P2-5 / 超时余量】`SRV-T73` 增超时余量要求**：等待放行 / `join` 的超时**不得过短（建议 ≥10s**；原 5s 在极端调度延迟下有**伪红**风险）**，并在 `join` 后断言线程**已结束**（`assertFalse(t.is_alive())`）**，把"到底谁没跑完"变成可见证据。③ **【接口权威栏】** `cache.md` v1.11 → **v1.12**。**未改代码 / SAD / PRD / API.md / README.md / `.opencode`；`cache.md` → v1.12、`_PROGRESS.md` 同步。**
> **v1.12 变更（F8 并发变体测试契约 + `acquire` 实现约束 · 只改文档，不改代码）**：① **【P2-2 / 覆盖缺口】把 F8 契约中承诺的「并发 K 个不同 Host 同时在飞」变体从 `SRV-T71` 的附注提升为独立可测用例 `SRV-T73`**（编号续测试表最大值）——用**阻塞式取数桩 + `threading.Event` 同步**让 K（如 8）个不同 Host 的键**同时在飞**（**不用 `sleep` 撞运气**）：断言 ① **在飞期间** `1 <= len(_feed_fetch_locks) <= K` **且 `len(_feed_fetch_refs) == len(_feed_fetch_locks)`（两表同步）**；② **全部返回后** `len(_feed_fetch_locks) == 0` **且** `len(_feed_fetch_refs) == 0`。**证伪方向**：若 `release` 不在 `finally`、或计数表与锁表不同步（归零只 `pop` 一张表）⇒ 断言（或两表相等断言）**红**。`SRV-T71` 收敛为**纯串行**收敛性用例（并发句子移入 `T73`，不删编号）。② **【微优化 · 实现约束】`feed_fetch_acquire` 不得为未命中路径构造被丢弃的对象**：契约补一句——**必须先 `get(key)` 判空、仅在 `None` 时创建 `threading.Lock()`**（命中路径**零分配**）；`setdefault(key, threading.Lock())` 会**每次调用**（含命中已有锁）都先构造一个 `Lock` 再被丢弃。**语义不变**（返回同一把锁、计数先于返回、临界区仅在 `_feed_fetch_locks_lock` 内），**仅去掉无谓对象构造**（`cache.md` BR-CACHE-35 同步补该实现约束）。③ **【接口权威栏】** `config.md` v1.4 → **v1.5**、`cache.md` v1.10 → **v1.11**。**未改代码 / SAD / PRD / API.md / README.md / `.opencode`；`cache.md` → v1.11、`config.md` → v1.5、`_PROGRESS.md` 同步。**
> **v1.11 变更（P2-1 fail-safe 措辞收口 + 溯源更正 · 只改文档，不改代码）**：① **【消费 `cache.md` v1.10 的 P2-1 fail-safe】** `_get_or_fetch_feed` 的读取入口 `feed_cache_get_entry` 现以 `entry.get('last_modified')` 读取——**legacy / 注入条目（非六字段）缺 `last_modified` ⇒ 该字段为 `None`** ⇒ 与"降级/回源失败"路径同样**不发 `Last-Modified` 头、`If-Modified-Since` 不可评估**（`If-None-Match` 仍按 ETag 正常评估），**绝不因缺字段抛 `KeyError` 经 `_guard` 变降级体**。本版把该语义补进 §2.5 访问器契约注与 BR-SRV-38（原文只把"降级/回源失败"列为 `None` 来源）——**属措辞收口：BR-SRV-38 的 BR 语义（时间源 = `last_modified`、指纹继承规则、`ETag 变 ⟺ Last-Modified 前进` 不变式）不变**；`feed_cache_put` 返回值恒为含该键的 dict（值可为 `None`），故 `return xml, entry['last_modified']` 仍安全。② **【溯源更正】** 头部上游 **SAD v1.7 → v1.9**、**PRD v0.6 → v0.8**（`cache.md` / `metrics.md` 已就地更正；`config.md` 的 SAD v1.2 / PRD v0.3 滞后属既存问题、**不在本版范围**，登记于 `_PROGRESS.md` 待办）；接口权威栏 `cache.md` **v1.9 → v1.10**。**未改代码 / SAD / PRD / API.md / README.md / `.opencode`；`cache.md` → v1.10、`_PROGRESS.md` 同步。**
> **v1.10 变更（P8 F8 契约化 · feed 取数锁表有界收敛 · 只改文档，不改代码）**：把 F2 引入的 **P1 资源缺陷**（`_feed_fetch_locks` 只增不减、键空间随请求派生 Host 无界扩张）按代码评审 `CR-RSS-20260918-003`（`doc/review/rss-conditional-get_p8修复_代码评审_专家版.md`）**推荐方案 1：引用计数 / 惰性回收** 契约化——① **【F8 新增】`_get_or_fetch_feed` 的加锁改走 cache 层新原语 `feed_fetch_acquire(cache_key)` / `feed_fetch_release(cache_key)`**（`cache.md` BR-CACHE-35），**用 `try ... finally` 保证异常路径也释放**（否则计数泄漏 ⇒ 锁表退化回只增不减）；`acquire` 在返回锁前把该键引用计数 +1、`release` 递减、**归零即 pop 该键及其计数**；**不能简单重加 `pop`**（归零前 `pop` 会让"已取出锁但尚未进入 `with`"的线程与后来者拿**两把不同的锁** ⇒ 同一键双抓，即 `系统_代码评审报告_001.md` TS-4 原事故）；**不变式 = 只要还有线程持有或即将获取该键的锁，计数 ≥1，该键不可能被 `pop`**；**正确性 = `pop` 只发生在计数归零（无持有者/等待者）时，随后线程创建新锁、其双检仍命中前一个持有者已写入的缓存条目 ⇒ 不产生重复取数**（第二次真取数只可能因条目确实已过期）；**有界性 = 锁表收敛于"并发在飞的键数"而非"累计见过的键数"**（`PUBLIC_BASE_URL` 已设时键恒为 5 条 path；可选运营缓解：部署侧强制设 `PUBLIC_BASE_URL`）。→ **BR-SRV-50**。② **【BR-SRV-45 补正】** 原"放大风险论证"**只覆盖上游请求、未覆盖锁表内存与本地生成**，本版**保留原论证并加限定**：F2 后键空间 = `path × 请求派生 base_url`，`_valid_host_header`（`server.py:591`）**只校验格式、不校验归属** ⇒ 任意合法主机名可造新键 ⇒ ① 锁表**永久内存增长**（每键 ~300–450 B，外部可无界触发 ⇒ OOM）；② 键数超 `feed_cache` 上限 100 后每个新 Host 必 miss ⇒ 一次 `generate_rss` + sha256、LRU 持续抖动（**只放大本地 CPU，上游仍被 URL 级缓存兜住**）。③ **【F8 测试】** 新增 `SRV-T71`（收敛性：串行 N=50 个不同 Host 后 `len(_feed_fetch_locks) == 0`、断言"不随 N 增长"）/ `SRV-T72`（并发不双抓 + 异常路径计数归零）→ 测试 **72 → 74**。④ **§2.10 import 面**由 `_feed_fetch_locks, _feed_fetch_locks_lock` 改为 **`feed_fetch_acquire, feed_fetch_release`**（server 不再直接触锁表）。**未改代码 / SAD / PRD / API.md / README.md / `.opencode`；`cache.md` → v1.9、`metrics.md` → v1.5、`_PROGRESS.md` 同步。**
> **v1.9 变更（P8 对抗性盲审 F1–F7 契约化 · 编排层裁定 · 只改文档，不改代码）**：把 P8 盲审（P0=0 / 2×P1 + 8×P2）裁定的修复写进契约——① **【F1 / P1-1 根治】`Last-Modified` 语义改为「表示最后一次变更的时刻」**（原 BR-SRV-38「feed 缓存条目写入时刻」表述**本版改写、全部作废**）：feed 条目新增 `fingerprint`（规范化摘要，与 ETag 同源）与 `last_modified`；`feed_cache_put` 与**同一键上一条目**比指纹（★ **即使该条目已过期也参与比较**——这正是「跨 TTL 重生成仍 304」的机制），相同 ⇒ **继承**上一 `last_modified`，不同 ⇒ 取本次写入时刻；**不变式 `ETag 变 ⟺ Last-Modified 前进`**；无上一条目（首次 / LRU 淘汰 / 已 sweep）⇒ 本次写入时刻（一次性 200 后恢复 304，**可接受降级**）；降级体（`_guard` 失败）仍 `last_modified=None`（不发头、IMS 不可评估）。**被否决备选 `Last-Modified = max(items 的 pubDate)`**（免状态，但上游「改描述不改 pubDate」会发**错误 304（陈旧数据）**；对交易数据服务，错误 304 远比多发 200 严重）写入 BR-SRV-38。副作用（`last_modified` 可能**远早于** body 内 `<lastBuildDate>`，语义正确）写入 BR-SRV-38。② **【F2 / P1-2 根治】feed 缓存键覆盖表示的全部变化维度**：`PUBLIC_BASE_URL` 已设 ⇒ 键 = `path`（与现状逐字一致）；未设 ⇒ 键 = `path + '\x00' + base_url`（`_base_url()` 结果；与 `Vary: Host, X-Forwarded-Host, X-Forwarded-Proto` **同语义** ⇒ **头与行为一致**）；键对 cache 层**不透明**（新增 server 侧 `_feed_cache_key(path, base_url)`）；放大风险论证（上游 `fetch_json` 另有 URL 级缓存 ⇒ 键增多**不放大上游请求**；条目受 `cache_max=100` + LRU 约束；非法 Host 经 `_valid_host_header` 塌缩 `localhost:PORT` 单键）写入 BR-SRV-45。③ **【F3 / P2-6】新增 `http_304_total` 指标**：`metrics._KNOWN` + `_DEFAULTS` **同步注册**（`assert` 强制），`_send_not_modified` 内**单点**计数；**只需计数、不需分母**（计数停止增长即「pubDate 抖动 ⇒ 永远 200」回归的报警信号）→ BR-SRV-46 + `metrics.md` v1.4。④ **【F4 / P2-4】feed 的 `max-age` authority 由 `news_url` 改 `feed`**：5 个 feed path 在 `_CACHE_AGE_DOMAINS` 映射改 `'feed'`；今日数值不变（两域同为 L3 / `ttl_factor=1.0` ⇒ 盘中 30 / 非盘 180）⇒ **只换 authority，数值不变、契约不变**；新增不变式 `_feed_ttl_minutes() == ceil(feed 路径的 max-age / 60)` → BR-SRV-47。⑤ **【F5 / P2-5】`feed_cache_put` 返回写入条目的浅拷贝**（六字段，**非 None**）；`_get_or_fetch_feed` 直接使用该返回值、**删除 put 之后第二次 `feed_cache_get_entry` 查询** ⇒ 消除「200 带 ETag 却不带 `Last-Modified`」窗口 + 省一次加锁往返 → BR-SRV-48 + BR-CACHE-34。⑥ **【F6 / P2-7 仅文档化】** HTTP/1.0（`RSSHandler` 未设 `protocol_version`）下 304 无 `Content-Length`、由**连接关闭（EOF）**收尾；RFC 9110 §8.6 明令 304 **不得**发 `Content-Length: 0`（若发须等于 200 体长）；本轮**不**升 `protocol_version`/keep-alive（BR-SRV-44 出范围）→ BR-SRV-49 + §10#36（该权衡与"中间件收尾为理论风险、`http.client` 已实测通过"如实记录）。⑦ **【F7】测试补充**：新增 `SRV-T63..T70`（8 条）+ **改写 `SRV-T55`**（自造陈旧条目、不依赖时序；独立证明 304 头组合）→ §8。**编号策略**：BR-SRV-38 **本版改写**；新增 `BR-SRV-45..49` / `BR-CACHE-33..34` / `BR-MET-14`，既有编号只增不删。**未改代码 / SAD / PRD / API.md / README.md / `.opencode`；`cache.md` → v1.8、`metrics.md` → v1.4、`_PROGRESS.md` 同步。**
> **v1.8 变更（P7b 漂移回填 · 只改文档，不改代码/设计裁定 · 对照 `doc/review/rss-conditional-get_代码评审_专家版.md` CR-RSS-20260918-001 D5）**：① **【D-1】** §10.1 补**第 5 条**测试迁移——`tests/test_server_http.py::GuardTests::test_rss_degrade_is_valid_feed`（:80）直接调 `_guard(shape='rss')` 并把返回值当 XML；§2.3/§5.1 已把 rss 形状钉死为 2-tuple ⇒ 照 v1.7 清单施工**必红**（`ET.fromstring(tuple)` ⇒ `TypeError`，且拿不到 `last_modified` 无从断言 IMS 不可评估）。**实现阶段已按详设裁定机械迁移**（解包 `xml, last_modified = srv._guard(...)` + `assertIsNone(last_modified)`）；本版补登使文档与实现一致。② **【D-1 计数】** §11 迁移计数 **4 → 5**（§10.1 计数口径注 / §11 自检 / v1.7 注同步标注）。③ **【D-2】** eastmoney 的 `<ttl>` 调用点由「5 处」更正为 **6 处调用点 / 5 个 handler**——`handle_eastmoney_kuaixun` 有**两个** `generate_rss` 站点（常规返回 + 「无匹配 ⇒ 空 feed」提前返回），**两处均传** `ttl=_feed_ttl_minutes()`（罕见路径的 feed 表示与常规路径一致；`<ttl>` 已剔除出 ETag，不影响条件请求）；落点 BR-SRV-43 / §2.10 / §5.8 / §11.5。④ **【顺带 · P2-3 如实记录】** `_send_text`（200）与 `_send_not_modified`（304）**各写一份** `Cache-Control`/`Vary`——**实现现状，非设计变更**；`SRV-T62`（200/304 头逐字 diff）即该漂移面的兜底断言（§5.8）。⑤ **【顺带】** §8 注明实现把 `SRV-T52b` 拆为 **5 个 unittest 方法**，**编号计数不变**（总 64）。**未改任何设计裁定（BR 编号 / 算法 / 取值 / 优先级 / 出范围项）、未改代码、未改 SAD/PRD/API.md/README.md/`.opencode`；`cache.md` 同步 v1.6 → v1.7（D-3）。**
> **v1.7 变更（P3a-r2 复审 P2 机械收口 · 只修精确性，不引入新设计 · 对照 `doc/review/rss-conditional-get_详细设计评审_复审_专家版.md` REV-DES-20260918-002）**：① **【P2-a · `SRV-T52b` 用例定义细化（防假绿）】**——`formatdate(timeval=None)` 与 `int(time.time())` 均为**秒级**，同一秒两次回落值相同 ⇒ 不 patch 时**即便无 C1 修复也会绿**；故**明确要求 patch 时钟**（源 `srv.formatdate` / `srv.time.time` / `utils.formatdate`，或等价受控源）使两次回落确定取 **`t` / `t+1`**，并声明**红/绿方向**（若 `pubDate` 仍在哈希区 ⇒ 两次 ETag 必不同 ⇒ 该断言**必须红**；C1 后必绿）；**另补纯函数断言**「仅 `<pubDate>` 值不同、其余逐字节相同的两个 XML ⇒ `_feed_etag` 相同」（不依赖时钟，直接锁死投影规则）；三个 feed（eastmoney `showtime` / ths `ctime` / jin10 `time`）的 handler 层覆盖**保持不变**。② **【P2-b】** BR-SRV-37 双向不变式的**第二子句补限定**为「**除 `pubDate`/`lastBuildDate`/`ttl` 三项外的**任一字节变化 ⇒ ETag 必不同」（§6.2#8③ 同步显式化）。③ **【P2-c】** §10.1 `FeedDoubleCheckTests` 补「返回值断言改 **2-tuple `(xml, time)`**」（否则照清单施工会红）。④ **【P2-d】** §10.1 第 3 条标题 `（:440）` → `（:440 / :450）`。⑤ **【P2-f】** §1.1 标题「职责（11 条）」→「**（13 条）**」（既有遗留）。**未改任何设计裁定（BR 编号 / 算法 / 取值 / 优先级 / 出范围项）、未改契约、未改代码；`cache.md` 无 P2 落点故保持 v1.6。**
> **v1.6 变更（P3a-r1 评审定向修 · 对照 `doc/review/rss-conditional-get_详细设计评审_专家版.md`）**：① **【C1 / P1-01 · 阻断项】ETag canonical 投影扩展至 item 级 `<pubDate>`**——`_feed_etag` 在既有剔除 `<lastBuildDate>`/`<ttl>`（各 `count=1`）之外，**全量**（`count=0`，item 多条）把 `<pubDate>…</pubDate>` 内容空白化为 `<pubDate/>`；修复 3/5 feed 因 item 级"当前时间回落"（`server.py:107` eastmoney `showtime` / `server.py:133` ths `ctime` / `utils.py:241` jin10 `time`）每次 TTL 到期重生成 ETag 变化 ⇒ **永远 200** 的静默失效；BR-SRV-37 不变式改写为**双向**（内容未变 ⇒ ETag 不变【不误 200】∧ 内容变 ⇒ ETag 变【不误 304】），`<pubDate>` 语义取舍明确为**可接受权衡**（BR-SRV-37 / §5.4 注）。② **【C2 / P1-02】§10.1 打桩迁移清单补第 4 条** `h.headers = {}`（`_serve_feed` 自 v1.5 起读 `self.headers`，`RSSHandler.__new__` 实例否则 `AttributeError`）；§11 自检计数"三条"→"**4 条**"。③ **【C3 / P1-03】`<ttl>` 契约语句写死**（BR-SRV-43 / §5.8）：**聚合器缓存提示、非时效保证**；**最小粒度 1 分钟**；**推荐轮询 = ETag 条件请求优先、间隔 ≥30s**；需 <60s 新鲜度请用 SSE（4s）。④ **【C4 / P2-01】**`_if_modified_since_not_modified` 的 `dt.timestamp()` **移入 `try`**、`except` 增 `OSError`；`§6.2#8⑤` 措辞收敛。⑤ **【C5】BR-SRV-39 弱前缀措辞**改为**大小写敏感、只接受字面 `W/`**。⑥ **【C6】§10#36 补依据**（RFC 9110 §8.6：304 不得带等于 200 体长的 `Content-Length`，写 `0` **违规**；HTTP/1.0 + EOF 收尾）。⑦ **【C7】补 14 条缺失用例**（新增 `SRV-T52b`/`SRV-T56b`/`SRV-T61`/`SRV-T62`，扩 T47/T48/T49/T50/T51/T54/T57/T58/T59；测试 60→**64 条**）+ `generate_rss` `ttl>0` 护栏。⑧ **【C8】**契约影响（漂移 8 项）见 `_PROGRESS.md`；头部溯源修正为 **SAD v1.7 / PRD v0.6**。
> **v1.5 变更（契约级同步 · 只增不改）**：为 5 个 RSS feed 增加 **HTTP 条件请求**支持——① **弱 ETag** `W/"<sha256>"`，派生自**规范化后**的 feed XML：**剔除 `<lastBuildDate>` 与 `<ttl>`** 两个"非内容元数据"元素后再哈希（**严禁裸 body 哈希**——`<lastBuildDate>=formatdate(timeval=None)` 每次重生成都变，裸哈希会导致 TTL 到期后内容未变也返回 200，**功能静默失效**，见 BR-SRV-37 / §10#32）；② **Last-Modified** 取 feed 缓存条目 `entry['time']`（新增 `cache.feed_cache_get_entry(path) -> dict|None`，**`feed_cache_get` 签名与语义不变**——BR-SRV-38 / `cache.md` BR-CACHE-32）（★ **v1.9 / F1 起改取 `entry['last_modified']`（表示最后一次变更时刻），`time` 保留给 `refresh_epoch`；本句为历史记录**）；③ **304 响应**由专用方法 `_send_not_modified()` 生成：**无 body / 无 `Content-Encoding` / 无 `Content-Length`**，**必带 `ETag` + `Cache-Control`（与 200 同值）+ `Vary`（Host 三件套 + `Accept-Encoding`）**，**不写缓存**；`HEAD` 同样可得 304（BR-SRV-39/40/41）；④ **条件头优先级**：`If-None-Match` **优先于** `If-Modified-Since`（RFC 9110 §13.1.3），支持 `*` / 逗号列表 / `W/` 弱前缀（弱比较），IMS 用 `email.utils.parsedate_to_datetime` **秒级**比较、**非法日期头忽略 → 200**（绝不 400/500）（BR-SRV-39/40）；⑤ RSS 2.0 `<ttl>`（**分钟**整数）= `max(1, (cache_policy('feed')['ttl']+59)//60)`（盘中 30s→`1`、非盘 180s→`3`），位置在 `</lastBuildDate>` 与 `<atom:link>` 之间，**同样剔除出 ETag**（BR-SRV-43）；⑥ **出范围（仅登记）**：`protocol_version` 升 HTTP/1.1 启用 keep-alive、`/opml.xml` 与 `/` 的条件请求（BR-SRV-44）。**既有 200 语义、`Vary`/`private` 反投毒、业务降级恒 200 口径全部保持。**
> **v1.4 变更（契约级同步 · 以代码为准）**：① **`main()` 新增 daemon 线程 `warm_transport`**（启动即预热上游传输：DNS + 每 SSE 热路径主机 1 条池化连接；**仅握手、不发业务请求**；`threading.Thread(target=warm_transport, daemon=True).start()`，**不阻塞启动/`/healthz`**，失败静默——`cache.warm_transport` 为总函数）；② **gzip 协商**：`_accepts_gzip(header)` 按 RFC 9110 §12.5.3 解析 `Accept-Encoding`（逗号分隔 token + `;q=` 权重、coding 大小写不敏感、`*` 兜底、**`gzip;q=0` = 明确拒绝**、`GZIP`/`*` 接受）；`_send_text` 对 `len(body) >= config.GZIP_MIN_BYTES(1024)` 且被接受的响应 `gzip.compress(level=config.GZIP_COMPRESSLEVEL=1)` 并发 `Content-Encoding: gzip`；**`Vary: Accept-Encoding` 在 `gzipped or cache` 时无条件发出**（= 所有可缓存响应 + 任何 gzip 响应，**含 `cache=False` 的 gzip**，防共享缓存把 gzip 体复用给不支持它的客户端）。
> **v1.3 变更（N1 回退 · 编排层裁决）**：Ⓝ① **业务端点降级恢复 `200 + error 体`**——`_send_json_shape` **恒 `_send_json(payload)`（200）**，不再按 payload 内容判 503；**`_json_payload_has_data` 已删除**（`_guard` 仍产出 `{'error': …}` / `_error` 客体，只是状态码不再随之变化）。Ⓝ② **`_send_json` 去掉 `status` 形参**（签名回落为 `_send_json(data, write_body=True, cache=True)`）。Ⓝ③ **`http_503_total` 计数点 4→3**：仅剩**连接准入拒绝**（`_reject_503`）、**流端口准入拒绝**（`stream._serve_sse` 超 `MAX_STREAM_CONNS`）、**`/healthz`**（其 503 是端点自身语义，**不构成业务端点先例**）。Ⓝ④ **降级体重新可缓存**：`_send_json_shape` 以 `cache=cache` 传参 ⇒ 降级 JSON 按域 TTL 拿 `Cache-Control: public, max-age=<domain ttl>`（v1.2 的"503 ⇒ 不缓存"消失）。
> **v1.2 变更（契约级同步 · 对照表见 §11.1；① 已于 v1.3 回退）**：① ~~**纯 error 包装的 JSON payload ⇒ 503**~~（**已回退，见上**；`_json_payload_has_data` 已删除）② `/healthz` payload 缺 `status` 或含 `error` ⇒ **503**（不只 `status=='degraded'`；**v1.3 保留**）③ `_HealthBatch` 增 **`settle()`**；`build_health_payload` 先建账再调用 + `except BaseException: settle(); raise`；`_run_health_checks(base_url, batch=None)` ④ `_fanout_executor` 的等待受 **`_FANOUT_WAIT_BUDGET=REQUEST_TIMEOUT`** 约束（超期 `cancel()` + `FetchError('upstream_timeout')`）⑤ `_base_url()`：`PUBLIC_BASE_URL` 优先，否则 **Host 格式校验** + `Vary` + `Cache-Control: private`（`_send_text(varies_on_host=…)`）⑥ `_cache_age()` 改用 `urlparse(self.path).path` ⑦ **4 面板的 cache-age 域改 `quote`**（L1，非 `f10` 的 300）⑧ **`/stock/*` 码归一**：`_parse_stock_codes`（canonical 折叠去重）+ `_rekey_batch_response`（响应键回用户原拼写）；截断按归一后码数；非法码值 ⇒ 逐码 `null`（非 400）⑨ **`/market/margin` 非法 `market` ⇒ 400**（`VALID_MARKETS` 前置校验）⑩ `_PANEL_HANDLERS` + `_JSON_DISPATCHED_PATHS` 导入期断言 ⑪ `do_GET`/`do_HEAD` 断连捕获扩为 **`OSError`** ⑫ `BoundedThreadPoolServer.request_queue_size = LISTEN_BACKLOG` ⑬ `handle_ths_longhu` 席位配对 `broker_idx` **无条件自增** + 错位告警；encoding 取自 `cache_policy('longhu')['encoding']` ⑭ import 块更正（`page_data`/`FetchError`/`LISTEN_BACKLOG`；删 `handle_cls_stock`/`fetch_cls_*`/`strip_html`/`escape_xml`）
> **v1.1 变更**：P1-1 healthz 准入位覆盖在飞任务（`_HealthBatch`）· P1-2 `/cls/hotplate`·`/cls/plate`·`/ths/longhu` ≤3 并发（AC-E2）· P1-3 hotplate 全分区失败补顶层 `error` · P1-4 `max_inflight` 形参（流端口显式 110）· P2-1/2/3/4/5 表述收口
> 模块路径 `china_finance_rss/server.py` · 归属 **Layer 3（HTTP 入口 / 编排层）**
> 上游 SAD `doc/arch/SAD.md` **v1.11**（★ v1.6 溯源修正：设计时点快照原误记为 v1.3；★ v1.11 溯源更新：v1.7 → v1.9；★ **v1.14 溯源更新：v1.9 → v1.11**——权威以 SAD 头部为准）（§2.1 D4 + plate stagger · §2.3 D-3/D-5 · §2.4 统一调用顺序 · §2.6 healthz · §3 server.py 行 · ADR-002/006/007/011/012）
> 上游 PRD `doc/prd/perf-stability-optimization.md` **v0.9**（★ v1.6 溯源修正：原误记为 v0.3；★ v1.11 溯源更新：v0.6 → v0.8；★ **v1.14 溯源更新：v0.8 → v0.9**——权威以 PRD 头部为准）（AC-S1/A5/A8/A9/S5/S7/S8/S10；R1/R2/R4/R15/R17/R19）
> ★ **编号命名说明（v1.6 / C8④）**：本文档（及 `cache.md`）中的「**本专项 R1**」指 `_MEMORY_CACHE.md` 工作文件的"内容未变 ⇒ ETag 不变 ⇒ 304"，与 SAD/PRD 已用的 **R1–R20**（根因编号）**同名不同义**；跨文档阅读时请以「本专项 R1」全称辨识。建议编排层统一改称 `US-RSS-1` / `AC-RSS-1`（本 agent 不改 SAD/PRD 编号）。
> 基础层/数据层接口权威：`config.md` **v1.5**（★ v1.5：溯源更正 SAD v1.11 / PRD v0.9；无接口/常量/行为变更） · `cache.md` **v1.13**（v1.5 新增 `feed_cache_get_entry`；v1.6 扩 T-CACHE-32 负例 + 溯源；v1.7 标注 T-CACHE-32 已实现；v1.8 / F1+F5：feed 条目 +`fingerprint`/`last_modified`、`feed_cache_put` 返回写入条目；★ **v1.9 / F8：`feed_fetch_acquire`/`feed_fetch_release` 引用计数原语 + 双检措辞更正为 `feed_cache_get_entry`**；★ **v1.10 / P2-1：`last_modified` 读取 `.get(..., None)` fail-safe（legacy 条目 ⇒ `None` ⇒ 不发 `Last-Modified`、禁用 IMS）+ 溯源 PRD v0.8**；★ **v1.11：读侧 fail-safe 补全（缺 `xml` ⇒ 视同 miss；`time`/`expires_at` 以 `.get` 读取）+ `acquire` 先判空实现约束 + T-CACHE-36**；★ **v1.12：`''` 边界写死（合法但空 ⇒ 照常命中）+ 残缺降级 `log.warning` 去重（BR-CACHE-36）+ §10#29/#30 边界登记**；★ **v1.13：`_feed_degraded_warned`/`_warn_feed_degraded_once` 实现注（按原因去重）+ §10#30 改「已防御」（三处 `isinstance` 守卫）+ `_sweep_expired` 跳过非映射 + 溯源 SAD v1.11/PRD v0.9**）· `metrics.md` **v1.6**（★ v1.4 / F3：注册 `http_304_total` → 20 名；★ v1.5：修正"`metrics.py` 零代码变更"自检句 + 溯源更新；★ v1.6：溯源更正 SAD v1.11 / PRD v0.9）· `stock_api.md` v1.3 · `market_api.md` v1.3 · `cdp_engine.md` v1.2
> 跨模块约定（已锁定）：`doc/detailed/_PROGRESS.md` §B
> 端锁定 🟠 STABLE（**不改路由、不改 API 签名**；仅 `/healthz` 只增字段 + `feeds[].status` 取值修正〔待编排层批准/同步〕）

## 1. 模块职责与边界

### 1.1 职责（13 条）

1. **路由分发（唯一入口）**：`RSSHandler._handle_request` 分派 `14 个 JSON 分支 + 5 个 RSS + / + /opml.xml + /healthz`；**shape 由 `_JSON_SHAPES` 路由表派生**（SAD §2.4「由路由表派生 shape、不写死数字」）。
2. **统一异常边界 `_guard(fn, *, shape, ...)`**：任何 handler 异常**不冒泡**（R1），按 `shape ∈ {batch, object, rss, text}` 产出结构化降级体。
3. **feed 缓存防击穿 + 双检**：`_get_or_fetch_feed` 只保留 **per-键** `_feed_fetch_locks[cache_key]` 锁；LRU / TTL / 清扫**全部委托** `cache.feed_cache_get_entry/feed_cache_put`（缓存机制归缓存层，裁决 #3）。★ **v1.10 / F8**：该锁表**不再直接读写**，改经 cache 层原语 `feed_fetch_acquire(cache_key)` / `feed_fetch_release(cache_key)`（`cache.md` BR-CACHE-35）——**引用计数归零即回收**，锁表规模收敛于**并发在飞的键数**（非累计见过的键数；BR-SRV-50）。
4. **plate 三档 stagger 派生**（SAD §2.1 D-7 **明令保留**）：`_plate_ttls()` 从 `cache_policy('plate')['ttl']` 派生 `_STAGGER = max(3, ttl // 4)` 与三档 offset，**不得**把三块压成同一 TTL。
5. **批量截断注入（AC-A9）**：`_handle_stock_batch` 计算 `dropped` 并**作为参数**传给 handler（组装点唯一，server **不重复组装**）。
6. **龙虎榜走统一取数入口（R15 / AC-E9）**：`/ths/longhu` 的两个上游 URL 改走 `fetch_json(..., encoding='gbk')` + `cache_policy('longhu')['ttl']`，删除直连 `urlopen`。
7. **healthz 改造（AC-S8 / R2 / R19）**：`check=0` 零上游快路径；`check=1` 专用执行器 + `BoundedSemaphore(MAX_HEALTH_INFLIGHT)` **有界准入**（stale 可达可测），且**准入位覆盖该批任务的真实在飞**（`_HealthBatch`，修 P1-1；`settle()` 覆盖异常路径 P1-5）；payload 保留既有 4 键 + 新增 `stale`/`metrics`/`policy`/`cdp`。**HTTP 503 判定**：`payload` 缺 `status` 或含 `error` ⇒ 503（guard 失败体不再像健康）**或** `status=='degraded'` ⇒ 503（计入 `http_503_total`）。
7′. **外部上游并发扇出（AC-E2 / SAD §4.1）**：`/cls/hotplate`（3 分区）、`/cls/plate`（3 段）、`/ths/longhu`（2 URL）一律经 `_get_fanout_executor()` **≤3 并发**取数（`max_workers=3`），使单端点耗时 = `max` 而非 `sum`（≤ `REQUEST_TIMEOUT`=10s ≤ AC-E2 的 15s）；等待受 `_FANOUT_WAIT_BUDGET=REQUEST_TIMEOUT` 界，超期 `cancel()` + `FetchError('upstream_timeout')`。
8. **过载有界拒绝（AC-E8 / S5）+ CDP 守护委派（ADR-012）**：`MAX_INFLIGHT` 显式化，达上限**立即 503 不排队**并计 `http_503_total`；`_cdp_memory_watchdog` 改调 `cdp_engine.watchdog_restart_skip_reason()`（盘中避让判断集中化）。
9. **JSON 端点降级 = `200 + error 体`（★ v1.3 / N1 回退）**：`object`/`batch`/`text` shape 的 payload **不因内容改变状态码**——上游/CDP 整体不可用时 `_guard` 产出的 `{'error': …}` / `_error` 客体仍以 **HTTP 200** 返回（与旧版本及既有业务系统消费的契约一致）。**真实 503 仅三条路径**：连接准入拒绝（`BoundedThreadPoolServer._reject_503`）、流端口准入拒绝（`stream._serve_sse` 超 `MAX_STREAM_CONNS`）、`/healthz`（端点自身语义，**不是业务端点先例**）。`_send_json_shape` 只做"从表读 shape + 调 handler + 发 200 JSON"。~~v1.2 的 `_json_payload_has_data` / error-only ⇒ 503 已删除~~。
10. **码身份归一（P1-6）**：`/stock/*` 入口经 `_parse_stock_codes` 折叠（`config.canonical_code`）去重后再计 `_MAX_BATCH_SIZE`；响应经 `_rekey_batch_response` 回请求原拼写，值与键集**不因归一而变**。
11. **响应压缩协商（v1.4 / AC-E1）**：`_accepts_gzip(header)` 按 RFC 9110 解析 `Accept-Encoding`（`gzip;q=0` 拒绝、大小写不敏感、`*` 兜底）；大响应（≥ `GZIP_MIN_BYTES`）gzip 后发 `Content-Encoding`；`Vary: Accept-Encoding` 在 `gzipped or cache` 时必发。
12. **上游传输预热（v1.4 / 冷启动）**：`main()` 起 `warm_transport` daemon 线程（DNS + 池化连接握手，无业务请求），使进程首个 refresh 不再全冷（冷扇出实测 ≈4.2s > 0.8×tick 预算）；预热不阻塞启动与 `/healthz`。
13. **RSS 条件请求（v1.5 / 下游轮询带宽；★ v1.9 / F1–F5 语义修订）**：5 个 `ROUTES` feed 的 `GET`/`HEAD` 支持 `If-None-Match`（**优先**）/`If-Modified-Since`；内容未变 ⇒ **304（零 body）**，且 304 不压缩、不写缓存；200 带弱 `ETag` 与（有缓存条目时）`Last-Modified`；`<ttl>` 由 `generate_rss` 输出（分钟）指导轮询间隔。**★ v1.9 / F1**：`Last-Modified` = **表示最后一次变更的时刻**（由 feed 条目的 `fingerprint` 跨 TTL 继承判定），非缓存写入时刻；**★ v1.9 / F2**：feed 缓存键在 `PUBLIC_BASE_URL` 未设时含 `base_url`（与 `Vary` 同语义）；**★ v1.9 / F3**：304 计入 `http_304_total`；**★ v1.9 / F4**：RSS `max-age` authority = `feed` 域（原 `news_url`）；**★ v1.9 / F5**：`feed_cache_put` 返回写入条目，miss 路径不再二次查询。**`/opml.xml`、`/` 不在范围**（BR-SRV-44）。

### 1.2 明确不做

- **不实现缓存机制**（LRU / 清扫 / 淘汰 / 负缓存）→ `cache.py`；本模块只调 `feed_cache_get/put`。
- **不实现帧计费与 SSE**（`_Frame`/`refs`/`stream_queue_bytes`/`_drain_conn_queue`）→ `stream.py`（SAD P2-N6）。
- **不组装批量保留键**（`_errors`/`_truncated`/`_dropped_count`）→ `cache.build_batch_response`；本模块只透传 `dropped`。
- **不实现码级冷却 / 期限贯通 / 分块预算** → `stock_api.py`。
- **不改技术栈、不增删路由、不改 HTTP 方法、不改 handler 业务语义**。
- **不做鉴权 / 多租户 / 前端**（PRD §6）。

### 1.3 layerIsolation 约束

`tech-stack.json` **未对 `server.py` 单列 `layerIsolation` 条目**；须遵守分层方向与 `importRestrictions.allowlist`（`china_finance_rss/*.py` 白名单含 `http`/`urllib`/`json`/`concurrent`/`socket`/`threading`/`time`/`email`/`atexit`/`signal`/`sys`/`os`/`re`/`logging`）。

```
允许 import：
  标准库：atexit / gzip（★ v1.4：响应压缩）/ hashlib（★ v1.5：ETag sha256）/ json / logging / os / re / signal / sys / threading / time /
          concurrent.futures.ThreadPoolExecutor,wait,FIRST_COMPLETED /
          datetime.timezone（★ v1.5：IMS naive → UTC）/ email.utils.formatdate（★ v1.5 亦用 parsedate_to_datetime）/ http.server / urllib.parse / urllib.request
  包内  ：config / cache（含 `warm_transport`，★ v1.4）/ utils / stock_api / market_api / cdp_engine / metrics
  延迟  ：from .stream import push_loop, run_stream_server   ← 仅 main() 内（打破 server ↔ stream 环，现状保留）
禁止 import：新增第三方库；`china_finance_rss/` 之外的第二个代码根
```

> **新增依赖仅 2 个**：`from . import metrics`（SAD §2.6 计分板的 owner 之一）+ `from .cdp_engine import restart_window_snapshot, watchdog_restart_skip_reason`（ADR-012 / §2.6）。二者均在既有允许面内（`metrics` 为包内模块、`cdp_engine` 为 Layer 内既有依赖）。

### 1.4 依赖方向（`←` 表分层顺序，**非 import 关系**）

```
Layer 0: config（无依赖） ‖ metrics（零业务依赖叶子，与 config 并列、互不依赖）
Layer 1: cache ← {config, metrics}
Layer 2: stock_api / market_api / stream ← {config, cache, metrics}
Layer 3: server ← {stock_api, market_api, stream（延迟 import）, cache, config, metrics, utils}
cdp_engine: 仅依赖 config/metrics；server 调用其函数（config.cdp_engine 全局槽由 server.init_cdp() 写入——config.md §1.4 登记的唯一历史例外）
```

### 1.5 与基础层 / 数据层接口对齐（不得偏离）

| 依赖接口 | 本模块用法（精确） |
|---------|------------------|
| `config.cache_policy(domain, now=None) -> dict` | `cache_policy('feed')['ttl']`（feed 写入 TTL + healthz `cache_ttl`）；`cache_policy('plate')['ttl']`（stagger 基值）；`cache_policy('longhu')['ttl']`（longhu 两 URL）；`cache_policy(d)['ttl']`（`_cache_age`）；`{d: cache_policy(d) for d in sorted(DOMAIN_MATRIX)}`（healthz `policy`） |
| `config.DOMAIN_MATRIX`（公开名） | healthz `policy` 的**域枚举来源**（不写死域清单） |
| `config.MAX_INFLIGHT` | `BoundedThreadPoolServer._max_inflight` 的**默认值**（显式，取代 `max_workers * 2`）；流端口经 `max_inflight` 形参显式覆盖为 `MAX_STREAM_CONNS+10=110`（修 P1-4，见 §2.7/§10#11） |
| `config.MAX_STREAM_CONNS` | **不 import**（属 `stream.py`）；server 只提供 `max_inflight` 形参，取值由 `stream.make_stream_server` 传入 |
| `config.MAX_HEALTH_INFLIGHT` | `_health_sem = threading.BoundedSemaphore(...)` |
| `cache.feed_cache_get(path) -> str \| None` / **`cache.feed_cache_put(path, xml, ttl, fingerprint=None) -> dict`（★ v1.9 / F5 返回写入条目）** | `_get_or_fetch_feed`：miss → **per-键（`cache_key`）** 锁 → **二次 get（双检）** → fetch → put。`feed_cache_get` 签名/语义**不变**（v1.5 起为 `feed_cache_get_entry` 薄包装）；★ **v1.9 / F5**：`feed_cache_put` 返回写入条目的**浅拷贝**（六字段，**非 None**），`_get_or_fetch_feed` **直接消费返回值、删除 put 之后第二次 `feed_cache_get_entry` 查询**（BR-SRV-48 / BR-CACHE-34）。**★ v1.9 / F1**：`fingerprint` 由 server 侧 `_feed_fingerprint(xml)` 提供（与 ETag 同源），cache 只做等值比较与 `last_modified` 继承 |
| **`cache.feed_cache_get_entry(path) -> dict \| None`（★ v1.5 新增；★ v1.9 / F1 扩字段）** | `_get_or_fetch_feed` 的**唯一读取入口**：命中返回新鲜条目的**浅拷贝** `{'xml','time','last_modified','fingerprint','last_access','expires_at'}`（同时 `move_to_end` + `last_access`），miss/过期返回 `None`。**`entry['last_modified']` = Last-Modified 时间源**（★ v1.9 / F1：表示最后一次变更时刻；BR-SRV-38；`cache.md` BR-CACHE-32/33）。★ **v1.11 / P2-1**：该字段由 cache 层以 `entry.get('last_modified')` 读取——legacy / 非六字段条目缺字段 ⇒ 值为 `None`（**与降级同口径**：不发 `Last-Modified`、IMS 不可评估；`If-None-Match` 仍按 ETag 评估），**不抛 `KeyError`**；返回值恒含该键（值可为 `None`）⇒ `entry['last_modified']` 下标安全。`entry['time']` = `feed_cache_put` **写入时刻**（供 `refresh_epoch` 新鲜度下限 BR-CACHE-31，**不再**作 Last-Modified）。**禁止**以 `feed_cache_get` + 另行查询拼时间（会拿到降级态的陈旧条目） |
| **`cache.feed_fetch_acquire(key) -> threading.Lock` / `cache.feed_fetch_release(key)`（★ v1.10 / F8 新增）** | `_get_or_fetch_feed` 的**唯一加锁入口**：`lock = feed_fetch_acquire(cache_key)` → `try: … finally: feed_fetch_release(cache_key)`；`acquire` 计数 +1 后返回锁，`release` 递减、**归零即回收键与其计数**（BR-SRV-50 / `cache.md` BR-CACHE-35）。**禁止**直接 `import _feed_fetch_locks` / `setdefault` / 手工 `pop` |
| `cache.build_batch_response(requested, results, errors=None, dropped=0) -> dict` | `_guard` 的 `batch` 降级体构造（全码 `null` + `_errors[code]='upstream_error'` + `dropped`） |
| `cache.fetch_json(url, headers=None, ttl=None, encoding='utf-8') -> str` | `/ths/longhu` 两 URL（`encoding='gbk'`）；5 个 RSS handler（既有 18 调用点**签名零改动**，仅 `ttl` 来源改 `cache_policy('news_url')['ttl']`，见 §5.11） |
| `cache.FetchError` | 不单点 catch（由 `_guard` 兜底）：RSS → `rss` shape；其它 → 各自 shape |
| `stock_api.handle_cls_*(codes, deadline=None, dropped=0) -> dict` | `_handle_stock_batch` 传 `dropped`（**不重复组装**，`_PROGRESS.md` §B 锁定） |
| `market_api.handle_margin(market='99') -> dict` | 签名不变（调用点零改动） |
| `cdp_engine.page_data(page) -> dict \| None` | 4 面板 handler 防御取数（A 类）；`timeline` 键缺失 → error 客体（**禁止裸 `null`**，R18 旁支） |
| `cdp_engine.restart_window_snapshot() -> dict` | healthz `cdp` 字段 |
| `cdp_engine.watchdog_restart_skip_reason(now=None) -> str \| None` | `_cdp_memory_watchdog` 的**唯一**决策；仅返回 `None` 时调 `full_chrome_restart()` |
| `metrics.incr(name, n=1, key=None)` / `metrics.set_gauge` / `metrics.snapshot()` | `http_503_total` / `healthz_stale_total` / `healthz_inflight` / healthz `metrics` 字段 |

---

## 2. 接口契约

### 2.1 路由总表（OpenAPI 风格，**唯一权威**；路径与 HTTP 方法本次**不变**）

```yaml
openapi: 3.0.3
info: {title: china-finance-rss main port (8053), version: '1.5'}
paths:
  '/':                                {get: {responses: {'200': {content: {text/html: {}}}}}}          # _serve_index（静态，无 IO）
  '/opml.xml':                        {get: {responses: {'200': {content: {'text/x-opml': {}}}}}}      # generate_opml（静态，无 IO）
  '/healthz':                         # shape=object（见 §2.6）
    get:
      parameters:
        - {name: check, in: query, schema: {type: string}, description: "'1'/'true'/'yes' → 真检查；其余/缺省 → 零上游快路径"}
      responses:
        '200': {description: 健康（可能含 stale:true 的降级快照）}
        '503': {description: "body 缺 status / 含 error / status=='degraded'（★ v1.2：不再仅判 degraded；均计 http_503_total）"}
  '/finance/market':                  {get: {responses: {'200': {description: 'object（含真实数据）或降级体 {"error": "Chrome CDP not available…"}（★ v1.3 / N1：降级体亦 200）'}}}}   # shape=object · CDP A 类
  '/finance/timeline':                {get: {responses: {'200': {description: 'object（timeline 缺失 → {"error":...}，仍 200）'}}}}  # shape=object · CDP A 类
  '/quotation/market':                {get: {responses: {'200': {description: object}}}}   # shape=object · CDP A 类
  '/market/timeline':                 {get: {responses: {'200': {description: object}}}}   # shape=object · CDP A 类
  '/cls/hotplate':                    {get: {responses: {'200': {description: 'object（分区 error 客体；三分区全失败 → 顶层补 error，**仍 200**）'}}}}  # shape=object
  '/cls/plate':                       # shape=object；缺 ?code= → 400（在 guard 之前判定）
    get:
      parameters: [{name: code, in: query, required: true, schema: {type: string}, example: cls80484}]
      responses:
        '200': {description: 'object（`info` 分区可独立降级为 error 客体；顶层无 `error` 键，`code` 恒为非空兄弟键）'}
        '400': {description: '{"error": "Missing ?code= parameter. …"}'}
  '/ths/longhu':                      # shape=text（JSON 体、Cache-Control 关闭）；2 个 GBK 上游
    get: {responses: {'200': {description: '{data:[…],total:n} 或 {"error": …}（text shape）'}}}
  '/market/margin':                   # shape=object
    get:
      parameters: [{name: market, in: query, schema: {type: string, default: '99', enum: ['99', '1', '2', '3']}}]
      responses:
        '200': {description: 'margin 成功体，或降级体 {latest, recent, _error}（★ v1.3 / N1：降级体亦 200）'}
        '400': {description: '★ v1.2：market ∉ VALID_MARKETS ⇒ {"error": "Invalid ?market= parameter. Allowed: 99,1,2,3"}'}
  '/stock/data':          {get: {description: 'batch · handler=handle_cls_stock_batch',   responses: {'200': {description: '扁平映射 + 保留键（键 = 请求原拼写）'}, '400': {description: '缺/空 code（非法码值 → 逐码 null，非 400）'}}}}
  '/stock/fundflow':      {get: {description: 'batch · handler=handle_cls_fundflow',      responses: {'200': {}, '400': {}}}}
  '/stock/timeline':      {get: {description: 'batch · handler=handle_cls_timeline',      responses: {'200': {}, '400': {}}}}
  '/stock/f10':           {get: {description: 'batch · handler=handle_cls_f10（CDP A′）', responses: {'200': {}, '400': {}}}}
  '/stock/basic_info':    {get: {description: 'batch · handler=handle_cls_basic_infos',   responses: {'200': {}, '400': {}}}}
  '/stock/announcement':  {get: {description: 'batch · handler=handle_cls_announcement',  responses: {'200': {}, '400': {}}}}
  # ★ v1.5：5 个 RSS feed 支持 GET/HEAD 条件请求（响应头清单见 §5.8；规则 BR-SRV-36..44）
  #   200 ⇒ 含 ETag（W/"<sha256>"）+ 有缓存条目时的 Last-Modified
  #   条件命中 ⇒ 304（无 body / 无 Content-Encoding / 无 Content-Length）
  #   条件头：If-None-Match（优先，支持 * / 多值 / W/）/ If-Modified-Since；均缺省 ⇒ 200 全量
  #   非法/不可解析日期头 ⇒ 忽略（200），绝不 400/500
  '/cls/telegraph':       {get: {description: 'rss+conditional', responses: {'200': {content: {application/rss+xml: {}}}, '304': {}}}, head: {responses: {'200': {}, '304': {}}}}
  '/eastmoney/kuaixun':   {get: {description: 'rss+conditional', responses: {'200': {content: {application/rss+xml: {}}}, '304': {}}}, head: {responses: {'200': {}, '304': {}}}}
  '/ths/kuaixun':         {get: {description: 'rss+conditional', responses: {'200': {content: {application/rss+xml: {}}}, '304': {}}}, head: {responses: {'200': {}, '304': {}}}}
  '/jin10/flash':         {get: {description: 'rss+conditional', responses: {'200': {content: {application/rss+xml: {}}}, '304': {}}}, head: {responses: {'200': {}, '304': {}}}}
  '/wallstreetcn/live':   {get: {description: 'rss+conditional', responses: {'200': {content: {application/rss+xml: {}}}, '304': {}}}, head: {responses: {'200': {}, '304': {}}}}
  # 条件头：If-None-Match（优先）/ If-Modified-Since；两者均缺省 ⇒ 200 全量（BR-SRV-36）
  # 304 上限：同一 client 的同一 ETag 重放。非法/不可解析日期头 ⇒ 忽略（200），绝不 400/500（BR-SRV-40）
# 未注册路径 → 404 文本（send_error(404, 'Not Found. Visit / for available feeds.')）
```

**HTTP 状态语义（AC-A5 五类，唯一口径）**

| 情形 | 状态 / 体 |
|------|----------|
| 参数缺失（`/stock/*` 缺/空 `?code=`；`/cls/plate` 缺 `?code=`） | `400` + `{"error": "<说明>"}`（**非**逐码 null） |
| `/market/margin` 参数非法（`market ∉ VALID_MARKETS`） | `400` + `{"error": "Invalid ?market= parameter. Allowed: 99,1,2,3"}` ★ v1.2（guard 之前判定） |
| 非法码**值**（`/stock/*?code=<乱码>`） | `200`；该码逐码 `null`（**非** 400）★ v1.2（400 仅缺/空 `?code=`） |
| 未知路径 | `404` + 文本说明 |
| 过载（主端口 inflight 达上限） | `503` + `{"error":"server busy"}`，**立即、不排队**（**真实 503 之一**） |
| 流端口连接数 ≥ `MAX_STREAM_CONNS`(100) | `503` + `{"error":"too many stream connections"}`（`stream._serve_sse`；**真实 503 之二**） |
| **业务端点降级**（4 面板 `{'error':…}` / `/cls/hotplate` 全分区失败 / `/market/margin` `_error` / guard 捕获异常后的 `{'error':…}` / `/cls/plate` 分区降级 / batch 逐码 `null`） | **`200` + 结构化降级体** ★ v1.3（**N1 回退**：状态码**不由 payload 内容决定**；`_send_json_shape` 恒 200，降级体**可缓存**——按域 TTL 拿 `Cache-Control: public, max-age=<domain ttl>`） |
| `/healthz` body 缺 `status` / 含 `error` / `status=='degraded'` | `503` ★ v1.2（计 `http_503_total`）。**该 503 属 healthz 端点自身语义，不构成业务端点先例**（v1.3） |
| 上游**部分**失败（批量） | `200`；批量 → 逐码 `null` ∧ `_errors[code]`；单体 → error 客体；RSS → 降级 feed |
| **RSS 条件请求命中**（`If-None-Match` 弱比较匹配 / `If-Modified-Since ≥ Last-Modified`）★ v1.5 | **`304`**（由 `_send_not_modified` 生成）：**无 body**、**无 `Content-Encoding`**、无 `Content-Length`；**带 `ETag` + `Cache-Control` + `Vary`**；**不写 feed 缓存**；`HEAD` 同（BR-SRV-41） |
| CDP 不可用（面板 4） | `200` + `{"error":"…"}`（★ v1.3：降级体亦 200）；`/stock/f10` → `200` 逐码 `null` ∧ `_errors[code]='cdp_unavailable'`（**非** error 客体） |
| handler 抛异常（guard 捕获） | `200`；`object`/`text` → `{'error': str(exc)}`（`/healthz` 例外 → 503） |

### 2.2 `_JSON_SHAPES`（shape 派生表，**唯一权威**）

```python
_SHAPES = frozenset({'batch', 'object', 'rss', 'text'})

# 14 个 JSON 分支 → shape。新增端点必须在此登记，否则 _handle_request 走 404。
_JSON_SHAPES = {
    '/finance/market': 'object', '/finance/timeline': 'object',
    '/quotation/market': 'object', '/market/timeline': 'object',
    '/stock/data': 'batch', '/stock/fundflow': 'batch', '/stock/timeline': 'batch',
    '/stock/f10': 'batch', '/stock/basic_info': 'batch', '/stock/announcement': 'batch',
    '/cls/hotplate': 'object', '/cls/plate': 'object',
    '/ths/longhu': 'text', '/market/margin': 'object',
}
assert len(_JSON_SHAPES) == 14      # 结构护栏：再次漏数即导入期失败（修 P1-6 的复发）

# ★ v1.2：路由由表驱动，shape 一律从 _JSON_SHAPES 读（不再写死字面量）
_PANEL_HANDLERS = {'/finance/market': handle_finance_market,
                   '/finance/timeline': handle_finance_timeline,
                   '/quotation/market': handle_cls_quotation,
                   '/market/timeline': handle_market_timeline}
_STOCK_BATCH_HANDLERS = {'/stock/data': handle_cls_stock_batch, ... }   # 6 项
assert set(_STOCK_BATCH_HANDLERS) == {p for p, s in _JSON_SHAPES.items() if s == 'batch'}
# _JSON_SHAPES 必须真被消费：新增表项而无分支（或有分支而无 shape）⇒ 导入期失败
_JSON_DISPATCHED_PATHS = (frozenset(_PANEL_HANDLERS) | set(_STOCK_BATCH_HANDLERS)
                          | {'/cls/hotplate', '/cls/plate', '/ths/longhu', '/market/margin'})
assert _JSON_DISPATCHED_PATHS == frozenset(_JSON_SHAPES)
```

- **`_send_json_shape(path, fn, ...)`（v1.2；★ v1.3 / N1 简化）**：`payload = _guard(fn, shape=_JSON_SHAPES[path])` → `_send_json(payload, write_body=..., cache=cache)`（**恒 200**，状态码**不**按 payload 内容判定）；**路由不再自行发明 shape 字面量**。v1.2 的 `_json_payload_has_data` 分支与 `503` 判定**已删除**（降级体恢复可缓存）。
- **分组视图**（供代码阅读，不参与运行；**表内合计必须 == 14**）：
  - `object`（**7，表内**）：4 面板 + `/cls/hotplate` + `/cls/plate` + `/market/margin`
  - `batch`（6）：`/stock/*`
  - `text`（1）：`/ths/longhu`
  - **`/healthz` 复用 `object` shape 但 `≠` 在 `_JSON_SHAPES` 内**（见 §2.6；把它加进表 ⇒ `assert len(_JSON_SHAPES) == 14` 导入期失败）
  - `rss`（5）：`ROUTES` 的 5 个路径（不在 `_JSON_SHAPES` 中，由 `_serve_feed` 使用）
- `_handle_stock_batch` **断言** `_JSON_SHAPES[path] == 'batch'`（`assert`，导入/调用期暴露误配）。

### 2.3 `_guard(fn, *, shape, requested=None, dropped=0, rss_info=None, feed_url=None)`

```python
def _guard(fn, *, shape, requested=None, dropped=0, rss_info=None, feed_url=None):
    """执行 fn()；任何 Exception → 按 shape 产出结构化降级体（**绝不冒泡**）。"""
```

| 参数 | 类型 | 默认 | 语义 |
|------|------|------|------|
| `fn` | `Callable[[], Any]` | — | 无参可调用（handler 或 `lambda`）；**返回值形状由 shape 决定** |
| `shape` | `str` | — | ∈ `_SHAPES`；非法 → `ValueError`（编程错误，不静默） |
| `requested` | `Sequence[str] \| None` | `None` | **仅 `shape='batch'`** 用：降级时全码置 `null` 的码序 |
| `dropped` | `int` | `0` | **仅 `shape='batch'`** 用：透传 `build_batch_response(..., dropped=)` |
| `rss_info` | `dict \| None` | `None` | **仅 `shape='rss'`** 用：`ROUTES[path]` 的 `title`/`link`/`description` |
| `feed_url` | `str \| None` | `None` | **仅 `shape='rss'`** 用：`base_url + path` |

**分派表（唯一降级形态来源）**

| shape | 成功返回 | 异常时返回（HTTP 200） |
|-------|---------|---------------------|
| `batch` | `fn()` 的 dict（handler 组装体） | `cache.build_batch_response(requested, {}, {c: 'upstream_error' for c in requested}, dropped=dropped)` → 全码 `null` + `_errors` + 截断键；**不抛、不断连** |
| `object` | dict（或 handler 自带 `{'error':…}`） | `{'error': str(exc)}` |
| `text` | dict（`/ths/longhu` 的 `{data,total}`） | `{'error': str(exc)}`（调用方仍以 `application/json` 序列化） |
| `rss` | **`(xml: str, last_modified: float \| None)`（★ v1.5：由 `_get_or_fetch_feed` 返回；★ v1.9 / F1：`last_modified` = feed 条目 `last_modified`（表示最后一次变更时刻），非 `time`）** | `(generate_error_rss(info['title'], info['link'], info['description'], exc, feed_url=feed_url), None)`（★ v1.5：降级 feed **无 `Last-Modified`** ⇒ `If-Modified-Since` 不可评估；★ v1.6 / C1：`pubDate` 已从 canonical 投影**剔除** ⇒ **不再**依赖"`pubDate` 每次变化"来避免 304——降级体 ETag 由**错误体内容**派生，与成功体内容不同 ⇒ 二者**不混淆**；同一错误表示重放可得 304（**同一表示**的条件命中，语义正确，BR-SRV-37）） |

- `shape` 非法 → `raise ValueError(f'unknown guard shape: {shape!r}')`。
- 捕获类型 = `Exception`（**不捕** `BaseException`：`KeyboardInterrupt`/`SystemExit` 直通）。
- 异常落日志：`log.exception('[guard:%s] handler raised', shape)`（保留 traceback，AC-S1「无未捕获异常日志冒泡」指**不冒泡到 `do_GET`**，日志仍必须留痕）。
- **客户端断开不在此层**：`send_*` 阶段的 `BrokenPipeError`/`ConnectionResetError`（均 ⊂ `OSError`）由 `do_GET`/`do_HEAD` 的 `except OSError` 吞掉（v1.2 由 `BrokenPipe/ConnectionReset` 两元组扩为 `OSError`，含 `TimeoutError`；写入发生在 `_guard` 之后）。

### 2.4 `_handle_stock_batch(self, parsed, handler, write_body=True, path=None)`

```python
def _handle_stock_batch(self, parsed, handler, write_body=True, path=None) -> None
```

| 步骤 | 行为 |
|------|------|
| 1 | `params = parse_qs(parsed.query)`；缺 `code` → `_send_error(...400...)` |
| 2 | **`stock_codes, requested = _parse_stock_codes(params['code'][0])`**（★ v1.2：逐码 `config.canonical_code` 折叠后去重，`requested` 与 `stock_codes` 位置对齐并保留用户原拼写）；空 → `_send_error('No valid stock codes provided.')` |
| 3 | `dropped = 0`；若 `len(stock_codes) > _MAX_BATCH_SIZE` → `dropped = len(stock_codes) - _MAX_BATCH_SIZE`、`log.warning(...)`、`stock_codes = stock_codes[:50]` 且 `requested = requested[:50]`（**保持对齐**）。截断按**归一后**码数计 |
| 4 | `data = _guard(lambda: handler(stock_codes, dropped=dropped), shape=_JSON_SHAPES.get(path, 'batch'), requested=requested, dropped=dropped)`（shape 从表派生） |
| 5 | `data = _rekey_batch_response(data, stock_codes, requested)`（★ v1.2：响应键回请求原拼写，值不变；无需改写时原样返回） |
| 6 | `self._send_text(200, 'application/json; charset=utf-8', json.dumps(data, ensure_ascii=False, indent=2), cache=True, write_body=write_body)` |

- **严禁**在此处调用 `build_batch_response` 或手工挂 `_truncated`（组装点唯一 = handler 内部；本处只注入 `dropped`）。`_rekey_batch_response` 是**纯改名**，不改键集（`_` 前缀保留键仍由 `build_batch_response` 唯一组装）。
- **非法码值是逐码 `null`，不是 400**（`_parse_stock_codes` 对 `canonical_code → None` 的码以原拼写为身份交 handler，由 handler 报 `null`）；**400 仅缺/空 `?code=`**。
- **重复拼写不占第二个槽**（折叠后去重）⇒ `600519.SH,SH600519,sh600519` 只计 1 个 `_MAX_BATCH_SIZE` 额度。
- `deadline` **不传**（沿用 handler 默认预算：REST 域 15s / f10 CDP 60s）——与 `_PROGRESS.md` §B 锁定契约一致；f10 多码 >15s 的既有风险见 `stock_api.md` §10#10（本模块不兜）。

### 2.5 `_get_or_fetch_feed(self, cache_key, fetch_func) -> tuple[str, float | None]`（防击穿 + **双检**；★ v1.5 返回二元组；★ v1.9 / F1+F2+F5 修订；★ v1.10 / F8 锁表有界）

```python
def _get_or_fetch_feed(self, cache_key, fetch_func) -> tuple[str, float | None]
    """返回 (xml, last_modified)。last_modified = 该 feed 条目的 entry['last_modified']
    （★ v1.9 / F1：表示最后一次变更的时刻，epoch 秒）；无条目 ⇒ None。
    第一个形参是 **不透明缓存键**（★ v1.9 / F2：由 `_feed_cache_key(path, base_url)` 组合）。
    """
```

| 参数 | 类型 | 语义 |
|------|------|------|
| `cache_key` | `str` | ★ **v1.9 / F2**：不透明缓存键（原为 `path`）。`PUBLIC_BASE_URL` 已设 ⇒ `= path`；未设 ⇒ `= path + '\x00' + base_url`。`cache.py` 不解析其结构 |
| `fetch_func` | `Callable[[], str]` | 回源（`lambda: handler(feed_url=feed_url)`）；**失败抛异常**（由 `rss` shape 兜底） |
| **返回** | `tuple[str, float \| None]` | ★ v1.5：`(xml, last_modified)`。**`last_modified` 只来自真实缓存条目**（★ v1.9 / F1：`entry['last_modified']`，**不是** `entry['time']`）——降级/回源失败路径由 `_guard` 产出 `(error_xml, None)` ⇒ **绝不把陈旧条目的时间冒充降级体的 Last-Modified** |

**必须按序执行（缺 ② 则防击穿退化，`cache.md` §2.4 硬约束）**

```
① entry = cache.feed_cache_get_entry(cache_key)   # miss → None（命中已内部 move_to_end + last_access）
   命中 → return (entry['xml'], entry['last_modified'])        # ★ v1.9 / F1
② lock = cache.feed_fetch_acquire(cache_key)   # ★ v1.10 / F8：计数 +1 后返回锁（内部持 _feed_fetch_locks_lock 后立即释放）
③ try:
     with lock:
         entry = cache.feed_cache_get_entry(cache_key)   # ★ 二次 get（双检）：并发窗口内他人已回源
         命中 → return (entry['xml'], entry['last_modified'])      # ★ v1.9 / F1
         ttl = cache_policy('feed')['ttl']          # ★ P2-1：二次 miss 后才求值
         xml = fetch_func()                         # 仅 miss 才回源；失败 ⇒ 异常穿透（不写缓存）
         # ★ v1.9 / F5：put 直接返回写入条目，**删除** put 之后的第二次 feed_cache_get_entry 查询
         entry = cache.feed_cache_put(cache_key, xml, ttl,
                                      fingerprint=_feed_fingerprint(xml))   # ★ v1.9 / F1
   finally:
     cache.feed_fetch_release(cache_key)        # ★ v1.10 / F8：异常路径也必须释放（否则计数泄漏 ⇒ 锁表只增不减）
④ return (xml, entry['last_modified'])        # ★ v1.9 / F5：entry 恒为 dict（非 None）
```

- **锁序（硬约束）**：`feed_fetch_acquire` 内部取 `_feed_fetch_locks_lock` 后**立即释放**才返回锁，调用方再 `with lock:`；**持有 per-键 锁时绝不持有** `_feed_cache_lock`/`_feed_fetch_locks_lock`（`feed_cache_get_entry/put` 内部自行加/放，二者不嵌套）。★ **v1.9 / F2**：`_feed_fetch_locks` 的键必须是**同一 `cache_key`**——若仍按 `path` 建锁，两个 Host 会共享锁且双检会串用对方的表示（BR-SRV-45）。
- **★ v1.10 / F8 锁表有界（BR-SRV-50）**：`feed_fetch_acquire(cache_key)` = 引用计数 +1 后返回锁；`feed_fetch_release(cache_key)` = 递减，**归零即 `pop` 该键及其计数**（`cache.md` BR-CACHE-35）。**必须 `try ... finally`**：`fetch_func()`/`feed_cache_put` 抛异常时，`finally` 仍释放 ⇒ 计数不泄漏。**不变式**：计数 ≥1 时该键不可能被 `pop`（归零前 `pop` 会让"已取出锁未进 `with`"的线程与后来者拿两把不同的锁 ⇒ 双抓 = TS-4 原事故）。**有界性**：锁表收敛于**并发在飞的键数**，非累计键数；`PUBLIC_BASE_URL` 已设时键恒为 5 条 path。
- **`feed_cache_get` 兼容**：本方法**改用** `feed_cache_get_entry`（一次查询同时拿到 `xml` + `last_modified`）；`cache.feed_cache_get` 签名与语义**不变**，仅是内部改为 `feed_cache_get_entry` 的薄包装（`cache.md` BR-CACHE-32）。**禁止**用"`feed_cache_get` + 另行 `feed_cache_get_entry`"两次查询拼装——第二次查询会拾取降级态的陈旧条目（BR-SRV-38）。
- **TTL 同源（★ v1.9 / F4）**：`ttl = cache_policy('feed')['ttl']`（盘中 30 / 非盘中 180），与 `_cache_age()` 的 RSS 分支读**同一个 `feed` 域**（v1.9 起 `_CACHE_AGE_DOMAINS` 的 5 个 feed path 已由 `news_url` 改映射 `feed`）⇒ "承诺 = 行为"（SAD D4）且**单一 authority**（BR-SRV-47）。`<ttl>` 亦由同一 policy 派生（BR-SRV-43）。
- **`ttl` 求值点（修 P2-1，保持）**：`ttl` **必须**在 ③ 的二次 `feed_cache_get_entry` **仍 miss 之后**求值（即紧邻 `fetch_func()`/`feed_cache_put`）；**禁止**在 ① 首次查询之前求值——否则命中路径白算 policy。§5.4 伪代码按此顺序。
- 回源失败**不写缓存**（异常穿透到 `_serve_feed` 的 `rss` 降级）；**不缓存错误 RSS**（下次请求重试，现状语义保持）。
- **§2.5a 新访问器契约（`cache.feed_cache_get_entry`，★ v1.5；★ v1.9 / F1 扩字段）**：`cache_key → 新鲜条目浅拷贝 | None`；命中时与 `feed_cache_get` 完全同源（`now < expires_at`、`move_to_end`、`last_access = now`）；返回**浅拷贝** `{'xml','time','last_modified','fingerprint','last_access','expires_at'}`（调用方只读，不得原地改）；`feed_cache_get` 由它实现，**签名/返回不变**。★ **v1.9 / F1**：`last_modified` = 表示最后一次变更时刻（Last-Modified 权威）；`time` = 写入时刻（`refresh_epoch` 用）。`feed_cache_put` 返回**同形态**浅拷贝（★ v1.9 / F5 / BR-CACHE-34）。详见 `cache.md` §2.4 / BR-CACHE-32/33/34。

### 2.6 `build_health_payload(base_url, check_sources=False) -> dict`

```python
def build_health_payload(base_url, check_sources=False) -> dict     # ★ 签名与位置不变（测试直接 import 调用）
```

**流程（三分支）**

| 分支 | 行为 |
|------|------|
| `check_sources=False`（零上游快路径） | 仅构造 `feeds[]` 基础条目 + `cache_ttl` + `request_timeout` + `metrics.snapshot()` + `policy` + `cdp`；**不触网**（毫秒级，AC-S8）。随后 `_remember_health_snapshot(payload)` |
| `check_sources=True` 且**准入成功** | `_health_sem.acquire(blocking=False)` 成功 → `_set_health_inflight(+1)` → **先建 `batch = _HealthBatch(len(ROUTES))`**（★ v1.2 / P1-5：账在风险调用**之前**建好）→ `try: _run_health_checks(base_url, batch)` / `except BaseException: batch.settle(); raise`（异常路径也恰好销账一次，防准入位永久泄漏）→ 把结果写回 `feeds[].status/items/error` → `status='degraded'` 若任一非 `ok` → 组装 payload → `_remember_health_snapshot(payload)`。**准入位不在本函数 `finally` 释放**（修 P1-1）：由 `_HealthBatch` 在**该批 5 个 future 全部结束**（`task_done` 归零）或**异常路径 `settle()`** 时释放（异步；响应不等任务排空，故 `?check=1` 仍 ≤ ~3s） |
| `check_sources=True` 且**准入失败**（≥`MAX_HEALTH_INFLIGHT` 在飞） | `metrics.incr('healthz_stale_total')` → 返回 **上次快照 + `{'stale': True}`**；若从无快照（进程启动后首个 check 即被拒）→ 返回**本次零上游体**（`status='degraded'`、`feeds` 为 configured 基线）+ `stale:true`；**不触网、不阻塞** |

**准入原语（修 P1-3：替换不可达的"执行器忙 → stale"死代码）**

```python
_health_sem = threading.BoundedSemaphore(MAX_HEALTH_INFLIGHT)   # = 5（config）
_health_executor = None                                          # 懒创建
_health_executor_lock = threading.Lock()
_health_inflight = 0                                             # gauge（在飞准入批次数）
_health_inflight_lock = threading.Lock()
_health_last_snapshot = None                                     # 上次成功 payload（深拷贝）
_health_last_lock = threading.Lock()
```

- **准入原语（修 P1-1：准入位必须覆盖任务真实在飞）**：`_health_sem` 钉死的是**准入批次数**（≤5），而每个准入批次的准入位**由该批 5 个 future 的完成回调释放**（`_HealthBatch.task_done`）。因此：
  - 在飞任务数 ≤ `MAX_HEALTH_INFLIGHT × len(ROUTES)` = **25**（确定性上界）；
  - 专用执行器（`max_workers=5`）的**工作队列长度 ≤ 20**（= 25 − 5 worker）⇒ SAD §2.6「执行器内部队列从不堆积」**成立**；
  - 持续慢 check（上游 5s）+ 高频 `?check=1` 下，新批次无法准入（5 个准入位被未排空的批次占满）⇒ **队列有界、不单调增长**（可测，见 SRV-T34）。
  - ⚠️ **禁止**在 `_run_health_checks` 返回时立即 `release`（旧 v1.0 口径）：轮询在 3s 即 `break`，未完成 future 仍跑，准入位早归还 ⇒ 队列可无界累积（重演 SAD P1-3 要消除的放大器）。
- **释放路径唯一收口**：`_health_sem.release()` 只在 `_release_health_slot()` 内出现，且被 `_HealthBatch` 的 `_done` 标志保证**每个准入批次恰好调用一次**（执行器创建失败/提交失败/异常返回/超时/正常完成**五路都销账**，`BoundedSemaphore` 超放会抛 `ValueError` ⇒ 由类型再次兜底）。

#### 2.6.1 `_run_health_checks(base_url, batch=None) -> dict[path, {'status','items','error'}]`

```python
_HEALTH_TOTAL_BUDGET  = 10.0   # 秒，整体预算（AC-S8「每个健康检查请求 ≤10s」；多源排队时的总闸）
_HEALTH_SOURCE_BUDGET = 3.0    # 秒，**每源独立**预算（SAD §2.2 R-2「单源 ≤3s」；按各自 submitted_at 判定）
_HEALTH_POLL          = 0.25   # 秒，wait() 轮询粒度
```

```
executor = _get_health_executor()                       # ThreadPoolExecutor(max_workers=MAX_HEALTH_INFLIGHT, thread_name_prefix='healthz')
# batch 由 build_health_payload 传入（★ v1.2 / P1-5：账在风险调用之前建，异常时可 settle）
started  = time.monotonic(); out = {}; pending = {}     # pending: fut -> (path, submitted_at)
for path, info in ROUTES.items():                       # 5 源
    try:
        fut = executor.submit(_check_one_feed, path, base_url, info)
    except Exception as exc:                            # 提交失败也须销账（否则准入位泄漏）
        out[path] = {'status': 'error', 'items': None, 'error': str(exc)}
        batch.task_done(); continue
    fut.add_done_callback(batch.task_done)              # ★ 完成即销账（准入位覆盖真实在飞）
    pending[fut] = (path, time.monotonic())             # ★ 记录该源各自的提交时刻

while pending:
    now = time.monotonic()
    for fut in [f for f, (_p, t) in pending.items() if now - t >= _HEALTH_SOURCE_BUDGET]:
        out[pending.pop(fut)[0]] = {'status': 'timeout', 'items': None, 'error': 'timeout'}   # ★ 每源独立 3s
    if not pending:
        break
    elapsed = now - started
    if elapsed >= _HEALTH_TOTAL_BUDGET:                 # ★ 整体 10s 闸（多源排队时才生效，不再死代码）
        break
    next_due = min(t for _p, t in pending.values()) + _HEALTH_SOURCE_BUDGET
    timeout = min(_HEALTH_POLL, max(0.0, next_due - now), max(0.0, _HEALTH_TOTAL_BUDGET - elapsed))
    done, _ = wait(set(pending), timeout=timeout, return_when=FIRST_COMPLETED)
    for fut in done:
        path = pending.pop(fut)[0]
        try:
            out[path] = fut.result()                     # _check_one_feed 是总函数，正常不抛
        except Exception as exc:                         # ★ v1.2 / P1-5：等待中途也不上抛
            out[path] = {'status': 'error', 'items': None, 'error': str(exc)}
for fut, (path, _t) in pending.items():                  # 整体预算耗尽：余下判 timeout
    out[path] = {'status': 'timeout', 'items': None, 'error': 'timeout'}
return out
```

- **`_HealthBatch`（修 P1-1 / v1.2 补 `settle()`）**：`__init__(n)` 置 `_remaining=n`、`_done=False`；`task_done()` 在锁内 `_remaining -= 1`，归零且未释放过 ⇒ 调 `_release_health_slot()`（`_set_health_inflight(-1)` + `_health_sem.release()`）**恰好一次**；**`settle()`（v1.2 / P1-5）**：不看 `_remaining`，仅凭同一 `_done` 闩锁立即释放一次——用于"异常路径已无可依赖的 future 回调"时销账。两条路径共享 `_done` ⇒ 谁先谁赢，**绝不双放**（超放会抛 `ValueError`）。`add_done_callback` 在 future 已结束时**同步**回调，故 `_remaining` 必须在任何 `submit` **之前**初始化为 `len(ROUTES)`。
- **两级预算（修 P2-2）**：**单源**预算按各 future 的 `submitted_at` 独立判定（`now - t >= 3s`）；**整体**预算 `10s` 是"多源排队/worker 被占满"时的总闸。旧口径的"全局 3s 条件"使 10s 常量成为死代码，已删除。
- `_check_one_feed(feed_path, base_url, info)`：**总函数**——`info['handler'](feed_url=base_url+feed_path)` → `{'status':'ok','items':count_rss_items(xml),'error':None}`；任意异常 → `{'status':'error','items':None,'error':str(exc)}`。
- **超时语义**：单源超过 `_HEALTH_SOURCE_BUDGET` 即判 `timeout`（**不取消** worker —— 线程不可杀；其上界由 `cache.REQUEST_TIMEOUT=10s` 钉死（★ v1.3：该 10s 是**冷/老化预算**；故障期探测预算 ≤ `cache._PROBE_BUDGET_CAP=5s`，见 `cache.md` §4.2 BR-CACHE-22），且其准入位由 `_HealthBatch` 在真正结束时归还，AC-S7/S8 可断言"线程有界释放 + 队列有界"）。
- **degraded 判定**：任一 `status != 'ok'` ⇒ `status='degraded'`（含 `timeout`/`error`）；HTTP 状态码由 `_handle_request` 决定：★ v1.2 起 `缺 status` / `含 error` / `status=='degraded'` **三者皆 503**（并计 `http_503_total`）。★ v1.3：**该 503 仅属 `/healthz` 端点自身语义**——业务端点不采用（见 §4.1 BR-SRV-5b）。

### 2.7 `BoundedThreadPoolServer`（过载有界拒绝）

```python
class BoundedThreadPoolServer(ThreadingHTTPServer):
    request_queue_size = LISTEN_BACKLOG            # ★ v1.2：BUG-P6C-03（socketserver 默认 5 ⇒ 突发连接 SYN 重传）
                                                   #   一个值同时配置主端口（≤MAX_INFLIGHT）与流端口（≤MAX_STREAM_CONNS）
    def __init__(self, *args, max_workers=MAX_WORKERS, max_inflight=None, **kwargs):
        ...
        self._max_inflight = MAX_INFLIGHT if max_inflight is None else max_inflight
        #                    ↑ 主端口默认 MAX_INFLIGHT(40)；流端口显式传 110（修 P1-4）
    def _reject_503(self, request):                # + metrics.incr('http_503_total')
    def process_request(self, request, client_address): ...   # 现状逻辑不变：达限即 503，不排队
    def _release_inflight(self, fut): ...
```

- **`max_inflight` 形参（修 P1-4，编排层已批准）**：`max_workers` 形参**不参与** inflight 计算；
  - 主端口：`max_inflight=None` ⇒ `_max_inflight = MAX_INFLIGHT = MAX_WORKERS*2 = 40`；
  - 流端口：`make_stream_server` 显式传 `max_inflight = MAX_STREAM_CONNS + 10 = 110`（**≥** `MAX_STREAM_CONNS=100`）⇒ `MAX_STREAM_CONNS=100` 与 `_register_conn` 的 100 阈值不再被 40 掩盖，AC-E5/E7 的 100 连接可复现。
  - **行为变更登记见 §10#11**（流端口 inflight 由"塌缩为 40"改为"显式 110"）。
- `_reject_503` 在 `finally` 关闭 socket，并 `metrics.incr('http_503_total')`（★ v1.3：`http_503_total` 全系统共 **3** 个计数点——**主端口连接准入拒绝**（本处）、**流端口准入拒绝**（`stream._serve_sse`）、**`/healthz` degraded/异常**；本处是主端口准入路径的唯一计数点。`metrics` 调用放在 `finally` 的 try 内，失败不得影响拒绝路径）。

### 2.8 handler 清单（本模块提供的 handler + 其 shape）

| # | 路径 | handler | shape | 说明 |
|---|------|---------|-------|------|
| 1 | `/finance/market` | `handle_finance_market(feed_url=None)` | object | CDP A；`page_data(page)` 防御取数 |
| 2 | `/finance/timeline` | `handle_finance_timeline()` | object | CDP A；`timeline is None → {'error':'timeline unavailable'}`（**禁止裸 null**） |
| 3 | `/quotation/market` | `handle_cls_quotation(feed_url=None)` | object | CDP A |
| 4 | `/market/timeline` | `handle_market_timeline()` | object | CDP A；同上禁止裸 null |
| 5 | `/stock/data` | `handle_cls_stock_batch`（stock_api） | batch | 无 pool/无终点缓存 |
| 6 | `/stock/fundflow` | `handle_cls_fundflow` | batch | — |
| 7 | `/stock/timeline` | `handle_cls_timeline` | batch | — |
| 8 | `/stock/f10` | `handle_cls_f10` | batch | CDP A′（`_errors='cdp_unavailable'`） |
| 9 | `/stock/basic_info` | `handle_cls_basic_infos` | batch | — |
| 10 | `/stock/announcement` | `handle_cls_announcement` | batch | — |
| 11 | `/cls/hotplate` | `handle_cls_hotplate(feed_url=None)` | object | **≤3 并发**；分区 error 客体 + **全分区失败补顶层 `error`**；3 档 stagger |
| 12 | `/cls/plate` | `handle_cls_plate(code)` | object | **≤3 并发**；3 档 stagger；缺 code 在路由层 400 |
| 13 | `/ths/longhu` | `handle_ths_longhu()` | text | GBK × **2 URL 并发**走 `fetch_json` |
| 14 | `/market/margin` | `handle_margin(market)`（market_api） | object | 签名不变 |
| 15–19 | 5 RSS | `handle_cls_telegraph` / `handle_eastmoney_kuaixun` / `handle_ths_kuaixun` / `handle_jin10_flash` / `handle_wallstreetcn_live`（均 `(feed_url=None)`） | rss | `ROUTES` 表 |

**本模块 handler 的既有签名（仅内部实现变化，签名不变）**

| 签名 | 变化 |
|------|------|
| `handle_finance_market(feed_url=None) -> dict` | 内部：`data = cdp_engine.page_data(page)`；`None → {'error':'Finance page not initialized.'}`；拿到 dict 后 `ws_raw = data.pop('__ws__', None)` / `data.pop('timeline', None)` 合法（已判定 dict） |
| `handle_finance_timeline() -> dict` | 内部：`data = page_data(page)`；`None → {'error': …}`；`tl = data.get('timeline')`；`tl is None → {'error': 'timeline unavailable'}`（**修 R18 旁支**） |
| `handle_market_timeline() -> dict` | 同 `handle_finance_timeline`（页面 = `cls_quotation`） |
| `handle_cls_quotation(feed_url=None) -> dict` | 同 `handle_finance_market`（无 `__ws__`） |
| `handle_cls_hotplate(feed_url=None) -> dict` | `ttl = base + stagger × idx`（§2.9）；3 分区经 `_fetch_concurrent` **≤3 并发**（SAD §4.1）；分区 error 客体 + 全失败补顶层 `error`（BR-SRV-31） |
| `handle_cls_plate(code) -> dict` | 同上 3 档；3 段经 `_fetch_concurrent` **≤3 并发**；`code` 由调用方保证非空 |
| `handle_ths_longhu() -> dict` | 两 URL 经 `_fetch_concurrent` **并发**走 `fetch_json(..., encoding='gbk')`；解析逻辑逐字保留 |

### 2.9 内部辅助（签名精确）

```python
def _plate_ttls() -> tuple[int, int]:
    """返回 (base_ttl, stagger)。base_ttl = cache_policy('plate')['ttl']；stagger = max(3, base_ttl // 4)。"""

def _policy_snapshot() -> dict:
    """{domain: cache_policy(domain)}，domain 枚举自 config.DOMAIN_MATRIX（sorted）。"""

def _base_feed_entries(base_url) -> list[dict]:
    """healthz feeds[] 的 15 个基础条目（5 RSS + 10 JSON/CDP），status 取 §2.9.1 表。"""

def _remember_health_snapshot(payload) -> None:
    """深拷贝（json round-trip，不用 copy 模块）后存入 _health_last_snapshot。"""

def _health_snapshot() -> dict | None:
    """返回 _health_last_snapshot 的浅引用（调用方只做 {**snap, 'stale': True} 后立即序列化，不原地改）。"""

def _set_health_inflight(delta: int) -> None:
    """_health_inflight 增减 + metrics.set_gauge('healthz_inflight', 值)（下限 0）。"""

def _get_health_executor() -> ThreadPoolExecutor:
    """懒创建（双检，_health_executor_lock）：ThreadPoolExecutor(max_workers=MAX_HEALTH_INFLIGHT, thread_name_prefix='healthz')。"""

def _release_health_slot() -> None:
    """BR-SRV-19：释放一次 healthz 准入位（_set_health_inflight(-1) + _health_sem.release()）；仅由 _HealthBatch 调用。"""

class _HealthBatch:
    """一次 ?check=1 的在飞记账（修 P1-1）：__init__(n) / task_done()（幂等，归零即 _release_health_slot()）
    / **settle()（v1.2 / P1-5：异常路径立即释放，共享 _done 闩锁 ⇒ 绝不双放）**。"""

# ★ v1.3 / N1：_json_payload_has_data(payload) -> bool 已删除 —— v1.2 曾用它把
#   "仅 error 包装"的 payload 判为 503；编排层裁决回退为"业务端点恒 200 + error 体"，
#   该函数与 _send_json_shape 的 503 分支一并移除（降级体恢复可缓存）。

def _parse_stock_codes(codes_str) -> tuple[list[str], list[str]]:
    """★ v1.2（P1-6）：一个 `?code=a,b,c` 值 → (canonical 去重码, 请求原拼写)；
    `config.canonical_code` 为唯一权威；无效码以自身拼写为身份（逐码 null，非 400）。"""

def _rekey_batch_response(data, codes, requested) -> dict:
    """★ v1.2（P1-6）：把 handler 的 canonical 键体改回请求原拼写（含 `_errors` 子映射）；
    纯改名（键集不变）；无需改写时原样返回。"""

def _valid_host_header(host) -> bool:
    """★ v1.2（S2-3）：Host 形如 hostname[:port] / [v6][:port]；拒绝空/超长/host-list/注入（@ / 空白 / CRLF）。"""

def _normalize_proto(value) -> str:
    """★ v1.2：X-Forwarded-Proto → 'http'/'https'（其余 ⇒ 'http'）。"""

# ── ★ v1.5：RSS 条件请求（ETag / Last-Modified / 304）────────────────────
def _feed_ttl_minutes() -> int:
    """RSS 2.0 <ttl> 单位为分钟；由 feed 缓存 policy 派生（BR-SRV-43）。
    ttl=30 ⇒ 1；ttl=180 ⇒ 3。★ v1.6：恒 ≥1（边界 0/负/59/60/61/180/181 ⇒ 1/1/1/1/2/3/4）。
    ★ v1.9 / F4 不变式：`_feed_ttl_minutes() == ceil(feed 路径的 max-age / 60)`（两处同读 `feed` 域）。"""

def _feed_fingerprint(xml) -> str:                              # ★ v1.9 / F1 新增
    """规范化摘要 = sha256-hex(normalize(xml))，**与 ETag 同源**（BR-SRV-37 的投影规则）。
    供 `feed_cache_put(fingerprint=...)` 做跨 TTL 表示变更判定（相同 ⇒ 继承 `last_modified`）。
    纯函数（不读时钟、不读缓存）。"""

def _feed_etag(xml) -> str:
    """BR-SRV-37：弱 ETag `W/"<sha256-hex>"`。
    规范化 = 移除 <lastBuildDate>…</lastBuildDate>（count=1）、<ttl>…</ttl>（count=1）
    与 <pubDate>…</pubDate>（★ v1.6 / C1：count=0 全量，item 有多条）的**内容**（保留占位元素），
    再对整串 utf-8 做 sha256。纯函数（不读时钟、不读缓存）。
    ★ pubDate 必须全量剔除：eastmoney/ths/jin10 的三处"解析失败回落到当前时间"落在哈希区。
    ★ v1.9 / F1：实现为 `_ETAG_PREFIX + '"' + _feed_fingerprint(xml) + '"'` ⇒ ETag 与缓存
    `fingerprint` **必为同一摘要**（不变式 `ETag 变 ⟺ Last-Modified 前进` 的基础）。"""

def _feed_cache_key(path, base_url) -> str:                     # ★ v1.9 / F2 新增
    """feed 缓存键（对 cache 层为**不透明字符串**）——覆盖表示的全部变化维度（BR-SRV-45）。
    `PUBLIC_BASE_URL` 已设 ⇒ `path`（表示与 Host 无关，与现状逐字一致）；
    未设 ⇒ `path + '\\x00' + base_url`（`base_url` = `_base_url()` 结果；与
    `Vary: Host, X-Forwarded-Host, X-Forwarded-Proto` **同一语义** ⇒ 头与行为一致）。
    非法 Host 已在 `_base_url()` 内塌缩为 `localhost:PORT` ⇒ 不可能靠畸形 Host 枚举键。"""

def _if_none_match_matches(header, etag) -> bool:
    """BR-SRV-39：If-None-Match 弱比较（RFC 9110 §13.1.2）。
    `*` ⇒ True；逗号列表逐项去空白、剥 `W/` 前缀后与服务端 opaque tag 比较。"""

def _if_modified_since_not_modified(header, last_modified) -> bool:
    """BR-SRV-40：If-Modified-Since 解析（email.utils.parsedate_to_datetime）→ 秒级比较
    last_modified <= ims ⇒ True。非法/不可解析/last_modified is None ⇒ False（忽略头）。
    ★ v1.6 / C4：解析、补时区、dt.timestamp() 全在 try 内，except 含 OSError（P2-01）。"""

def _not_modified(headers, etag, last_modified) -> bool:
    """BR-SRV-39/40：条件判定唯一入口。
    If-None-Match **存在** ⇒ 只看它（匹配⇒304，不匹配⇒200，**忽略 IMS**）；
    否则看 If-Modified-Since；两者皆缺 ⇒ False（200 全量）。"""

def _get_fanout_executor() -> ThreadPoolExecutor:
    """懒创建（双检，_fanout_lock）：ThreadPoolExecutor(max_workers=_FANOUT_MAX_WORKERS=3, thread_name_prefix='fanout')。"""

def _fetch_concurrent(specs) -> dict:
    """specs: list[(key, Callable[[], Any])]；≤3 并发展开，返回 {key: 结果|Exception}（**不抛**）；
    单元素时走当前线程（免池化开销）。顺序 = specs 顺序（确定性）。
    ★ v1.2：`wait(futs, timeout=_FANOUT_WAIT_BUDGET=REQUEST_TIMEOUT)` 有界排空；超期 future `cancel()`
    并降级为 `FetchError('upstream_timeout')`（已在跑的仍受自身 10s 界）；此处不计任何计数（真失败由
    cache.fetch_json 计，防双计）。"""
```

**新增/调整的模块级常量**

```python
_SHAPES = frozenset({'batch', 'object', 'rss', 'text'})
_JSON_SHAPES = {...}                     # §2.2，14 项
_DEFAULT_AGE_DOMAIN = 'f10'              # _cache_age 未登记路径的兜底域（L4、factor 1.0 ⇒ 恒 300，见 §10#2）
_LHBTABLE_URL     = 'https://data.10jqka.com.cn/ifmarket/lhbtable'
_LHBTABLE_HEADERS = {'User-Agent': '…Chrome/120.0.0.0 Safari/537.36',
                     'Referer': 'https://data.10jqka.com.cn/market/longhu/',
                     'X-Requested-With': 'XMLHttpRequest'}
_LONGHU_PAGE_URL     = 'https://data.10jqka.com.cn/market/longhu/'
_LONGHU_PAGE_HEADERS = {'User-Agent': '…Chrome/120.0.0.0 Safari/537.36',
                        'Accept-Language': 'zh-CN,zh;q=0.9'}
_HEALTH_TOTAL_BUDGET = 10.0
_HEALTH_SOURCE_BUDGET = 3.0
_HEALTH_POLL = 0.25
_FANOUT_MAX_WORKERS = 3                  # ★ 外部上游扇出并发上限（SAD §4.1；hotplate/plate/longhu 共享）
_FANOUT_WAIT_BUDGET = REQUEST_TIMEOUT    # ★ v1.2（P1-2）：一轮扇出的排空上界（否则共享池被占时单请求可拖到 ~190s）
_BASE_URL_VARY = 'Host, X-Forwarded-Host, X-Forwarded-Proto'   # ★ v1.2（S2-3）
_HOST_RE / _HOST_IPV6_RE = ...           # ★ v1.2：Host 格式校验正则
# ★ v1.5：ETag 规范化（剔除"非内容"元素的内容）
# ★ v1.6 / C1：+ item 级 <pubDate>（全量替换，count=0；item 多条）
_LASTBUILDDATE_RE = re.compile(r'<lastBuildDate>[^<]*</lastBuildDate>')   # count=1（channel 首个）
_RSS_TTL_RE       = re.compile(r'<ttl>[^<]*</ttl>')                       # count=1（channel 首个）
_PUBDATE_RE       = re.compile(r'<pubDate>[^<]*</pubDate>')               # ★ v1.6：count=0（全量）
_ETAG_PREFIX      = 'W/'                  # 弱校验器（ETag 由规范化体派生 ⇒ 语义上即为弱校验器）
_FEED_KEY_SEP     = '\x00'                # ★ v1.9 / F2：feed 缓存键 path/base_url 的分隔符（不可能出现在合法 base_url 内）
```

> **线程账**：本模块新增线程来源 = healthz 专用执行器（≤5，懒创建）+ 扇出执行器（≤3，懒创建）+ **启动预热线程 `warm_transport`（1，daemon，v1.4；随 `main()` 起一次，不常驻轮询）**；`fanout` 线程仅在首次并发扇出时创建（AC-S9 线程总账 **+9** 上界，见 §10#15/#31）。

> `_LHBTABLE_*` / `_LONGHU_PAGE_*` 是**从现状 `Request(...)` 字面量提取**的模块级常量（现状 `server.py:143-176` 内联）；**本次未上收 `config.py`**（`config.md` v1.1 的常量清单未登记该域）——登记见 §10#1。

#### 2.9.1 `_base_feed_entries` 的 status 取值表（含 3 处 CDP 标注修正）

| path | 现状 status | **目标 status** | 类别（PRD AC-S4） |
|------|------------|----------------|------------------|
| `/cls/telegraph` `/eastmoney/kuaixun` `/ths/kuaixun` `/jin10/flash` `/wallstreetcn/live` | configured | `configured`（不变） | B |
| `/finance/market` | requires_chrome_cdp | `requires_chrome_cdp`（不变） | A |
| `/quotation/market` | requires_chrome_cdp | `requires_chrome_cdp`（不变） | A |
| `/stock/data` | requires_chrome_cdp | **`configured`** ★修正 | B |
| `/stock/fundflow` | configured | `configured`（不变） | B |
| `/cls/hotplate` | configured | `configured`（不变） | B |
| `/cls/plate?code=cls80484` | configured | `configured`（不变） | B |
| `/stock/timeline` | configured | `configured`（不变） | B |
| `/stock/f10` | configured | **`requires_chrome_cdp`** ★修正 | A′ |
| `/stock/basic_info` | requires_chrome_cdp | **`configured`** ★修正 | B |
| `/market/margin` | configured | `configured`（不变） | B |

> ★ 三处为 SAD §7.1 Q2 登记的契约漂移；**同步权归编排层**（本设计只落目标值 + §10#7 登记）。`feeds[].status` 属**改既有字段取值**（≠"只增不改"），须走变更日志 + API.md 同步。

**首页 CDP 列修正（`_serve_index` 的 `json_apis` 表，第 4 元素 `needs_cdp`）**

| path | 现状 `needs_cdp` | **目标** |
|------|-----------------|---------|
| `/stock/data` | `True` | **`False`** |
| `/stock/basic_info` | `True` | **`False`** |
| `/stock/f10` | `False` | **`True`** |
| 其余 11 项 | — | 不变 |

### 2.10 保留不变的公开面（兼容清单）

| 名称 | 变更 |
|------|------|
| `ROUTES`（5 项 dict，含 `handler`/`name`/`title`/`link`/`description`） | **不变**（OPML/healthz/首页均依赖其结构） |
| `RSSHandler.timeout = 30` | 不变（主端口兜底） |
| `_serve_index` / `_serve_feed` | **签名不变**（`_serve_feed(self, path, base_url, write_body=True)`）；★ v1.5 内部新增条件判定 + 200 校验器头 + 304 分支（`varies_on_host=not PUBLIC_BASE_URL` 保持）；★ **v1.9 / F2**：内部改经 `_feed_cache_key(path, base_url)` 组合缓存键并传给 `_get_or_fetch_feed` |
| `_base_url()` / `_send_text` / `_send_json` | **签名扩展（v1.2）**：`_base_url` 加 Host 校验；`_send_text(..., varies_on_host=False, write_body=True)`；`_send_json(data, write_body=True, cache=True)`（★ v1.3：**无 `status` 形参**——恒调 `_send_text(200, …)`）；新增 `_send_json_shape`（★ v1.3：恒 200，无 503 分支）；★ **v1.4**：新增 `_accepts_gzip(header) -> bool`，`_send_text` 内部按 `GZIP_MIN_BYTES`/`GZIP_COMPRESSLEVEL` 决定 gzip 并补发 `Content-Encoding`/`Vary`（**签名不变**）；★ **v1.5**：`_send_text(..., etag=None, last_modified=None)` **纯新增两个可选形参**（200 RSS 路径发 `ETag`/`Last-Modified`；其余调用点零改动）；**新增方法** `_send_not_modified(etag, last_modified, varies_on_host=False)`（304 专用，无 body/无 `Content-Encoding`/无 `Content-Length`） |
| **`cache.feed_cache_get_entry(path) -> dict \| None`（★ v1.5 新增公开访问器；★ v1.9 / F1 扩字段）** | 命中返回新鲜条目**浅拷贝**（★ v1.9：六字段 `xml/time/last_modified/fingerprint/last_access/expires_at`；`last_modified` = 表示变更时刻，`time` = 写入时刻）；`cache.feed_cache_get` **签名与语义不变**（内部薄包装） |
| **`cache.feed_cache_put(path, xml, ttl, fingerprint=None) -> dict`（★ v1.9 / F5）** | 返回**写入条目的浅拷贝**（六字段，**非 None**）；`fingerprint` 由 server 的 `_feed_fingerprint(xml)` 提供（与 ETag 同源），用于跨 TTL 的 `last_modified` 继承（BR-CACHE-33/34） |
| **`cache.feed_fetch_acquire(key) -> threading.Lock` / `cache.feed_fetch_release(key)`（★ v1.10 / F8 新增公开面）** | `_get_or_fetch_feed` 的**唯一加锁入口**（替换原 `_feed_fetch_locks`/`_feed_fetch_locks_lock` import）；`acquire` 计数 +1 后返回锁，`release` 递减、**归零即回收键与计数**；**必须 `try ... finally`**（BR-SRV-50 / `cache.md` BR-CACHE-35） |
| **`utils.generate_rss(title, link, description, items, feed_url=None, ttl=None)`（★ v1.5）** | `ttl` 为 **RSS 2.0 `<ttl>` 的分钟整数**；`None`（默认）⇒ **不输出** `<ttl>`（既有 9 个调用点/测试零改动）；5 个 RSS handler（**6 处 `generate_rss` 调用点**：`handle_eastmoney_kuaixun` 含「无匹配 ⇒ 空 feed」提前返回；★ v1.8 / D-2）传 `ttl=_feed_ttl_minutes()` |
| `BoundedThreadPoolServer.__init__(*args, max_workers=MAX_WORKERS, max_inflight=None, **kwargs)` | **增 `max_inflight` 形参（v1.1）**；★ v1.2 增类属性 `request_queue_size = LISTEN_BACKLOG` |
| `init_cdp()` / `_cdp_memory_watchdog()` / `main()` | 签名不变（watchdog 内部决策改调 cdp_engine） |
| `handle_cls_telegraph` / `handle_eastmoney_kuaixun` / `handle_ths_kuaixun` / `handle_jin10_flash` / `handle_wallstreetcn_live(feed_url=None)` | 签名不变；内部 `ttl` 改 `cache_policy('news_url')['ttl']`；★ v1.5：`generate_rss(..., ttl=_feed_ttl_minutes())`（**6 处调用点 / 5 个 handler**：eastmoney 两个 `generate_rss` 出口均传；★ v1.8 / D-2；`_feed_ttl_minutes()` 只读 `cache_policy('feed')`） |
| `build_health_payload(base_url, check_sources=False)` | **签名不变**（测试直接调用） |

**删除的 import / 常量消费者迁移（与 `config.md` §2.4 **同一 change-set**）**

| 删除项 | 本模块消费点 | 迁移目标 |
|--------|-------------|---------|
| `CACHE_TTL` | `server.py:37`（import）、`:497`（healthz `cache_ttl`）、`:668`（feed expires）、`:936`（启动日志） | `cache_policy('feed')['ttl']` |
| `CACHE_JITTER`、`random` | `server.py:668` 的 `× (1 ± jitter)` | **删除**（jitter 现由 `cache._expires_at(ttl)` 内部提供，`cache.md` §2.5） |
| `feed_cache`、`_feed_cache_lock`、`MAX_FEED_CACHE_SIZE` | `server.py:46-47,663-664`（feed LRU/淘汰） | `cache.feed_cache_get` / `feed_cache_put`（`cache.md` §2.4） |
| `_feed_fetch_locks`、`_feed_fetch_locks_lock` | import 面（旧 `server.py` 直接持锁表建锁） | **`cache.feed_fetch_acquire` / `cache.feed_fetch_release`**（★ v1.10 / F8；`cache.md` BR-CACHE-35）——server 不再直接触锁表 |
| `_trading_tiers` | `server.py:81/90/122/217/230`（news TTL）、`:299`/`:337`（hotplate/plate 的 `tiers['L2']`）、`:693`（`_cache_age`） | `cache_policy('news_url')['ttl']` / `_plate_ttls()`（`cache_policy('plate')['ttl']`）/ `cache_policy(d)['ttl']`；**`_trading_tiers` import 随删**（本模块不再直接读 tier） |

**完整 import 块（修 P2-5：逐行可整体替换，含标准库/包内全部保留项与删除项）**

```python
# ── 标准库 ────────────────────────────────────────────────────────────
import atexit
import gzip                     # ★ v1.4：_send_text 响应压缩
import hashlib                  # ★ v1.5：_feed_etag 的 sha256
import json
import os
import re
import signal
import sys
import threading
import time
import logging
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED   # ★ 新增 wait/FIRST_COMPLETED
from datetime import timezone   # ★ v1.5：IMS naive datetime → UTC
from email.utils import formatdate, parsedate_to_datetime   # ★ v1.5：parsedate_to_datetime
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
from urllib.parse import parse_qs, urlencode
# ★ 删除：import random（唯一使用点 :668 的 jitter 已归 cache._expires_at）
# ★ 删除：from urllib.request import Request, urlopen（longhu 改走 fetch_json 后二者成为未用 import）

# ── 包内 ──────────────────────────────────────────────────────────────
from . import config                                                       # ★ 新增（config.MAX_HEALTH_INFLIGHT / config.canonical_code 以前缀引用）
from . import metrics                                                      # ★ 新增（SAD §2.6 owner）
from .cdp_engine import (ensure_chrome, CDPEngine, full_chrome_restart,
                         restart_window_snapshot, watchdog_restart_skip_reason,
                         page_data)                                        # ★ v1.2：page_data 补入（A 类唯一入口）
from .config import (
    PORT, REQUEST_TIMEOUT, PUBLIC_BASE_URL, MAX_WORKERS, MAX_INFLIGHT,
    LISTEN_BACKLOG, DOMAIN_MATRIX, cache_policy, _MAX_BATCH_SIZE,           # ★ v1.2：LISTEN_BACKLOG 新增
    _FINANCE_EXPECTED_KEYS, _QUOTATION_EXPECTED_KEYS,
    _HOTPLATE_BASE_URL, _HOTPLATE_HEADERS,
    _PLATE_INFO_URL, _PLATE_STOCKS_URL, _PLATE_INDUSTRY_URL, _PLATE_HEADERS,
    CDP_RESTART_INTERVAL, stock_nav_page_names, cdp_engine,
)   # ★ 删除：CACHE_TTL、_trading_tiers；★ v1.2：MAX_HEALTH_INFLIGHT 不再直接 import（改用 config. 前缀）
from .cache import (fetch_json, feed_cache_get_entry, feed_cache_put,
                    feed_fetch_acquire, feed_fetch_release,               # ★ v1.10 / F8：锁表原语（替换 _feed_fetch_locks/_feed_fetch_locks_lock）
                    build_batch_response, _fill_missing, FetchError,
                    warm_transport)                                        # ★ v1.4：warm_transport（main() 预热线程）
from .utils import (                                                       # 不变（handler + main() 均用）
    generate_rss, generate_error_rss, generate_opml, count_rss_items,
    parse_cls_items, parse_jin10_items, parse_wallstreetcn_items,
    cls_sign_params, get_jin10_public_headers,
    timestamp_to_rfc822, parse_china_datetime_to_rfc822,
)   # ★ v1.2：strip_html / escape_xml 已不在使用面（删除）
from .stock_api import (                                                   # 含 main() 的 4 个 prefetch loop
    handle_cls_stock_batch, handle_cls_fundflow,
    handle_cls_timeline, handle_cls_f10, handle_cls_basic_infos,
    handle_cls_announcement,
    _fundflow_prefetch_loop, _timeline_prefetch_loop,
    _f10_prefetch_loop, _announcement_prefetch_loop,
)   # ★ v1.2：handle_cls_stock / fetch_cls_fundflow / fetch_cls_timeline 不在使用面（删除）
from .market_api import (handle_margin, VALID_MARKETS)                     # ★ v1.2：VALID_MARKETS 新增（margin 400 门）
```

> **禁止**把 `main()` 仍需要的 `stock_api` 4 个 prefetch loop / `market_api` / `utils` import 当成"未变更行"省略后整体替换——本块已列全，编码者按此整体替换即可（P2-5）。


---

## 3. 数据结构（yaml）

### 3.1 `/healthz` 响应精确 schema（既有 4 键一个不少 + 新增 4 键）

```yaml
healthz_payload:
  status: "ok" | "degraded"          # 既有；check=1 时任一源非 ok → degraded（timeout/error 均算）
                                     # ★ v1.2 HTTP 503 判定：缺 status / 含 error / status=='degraded'
                                     #   （guard 捕获异常时体为 {'error': …}，无 status ⇒ 503，不再假健康）
  cache_ttl: <int>                   # 既有；★取值改 cache_policy('feed')['ttl']（盘中 30 / 非盘中 180）
  request_timeout: <int>             # 既有；REQUEST_TIMEOUT（10）
  feeds:                             # 既有；15 条，字段集合不变
    - name: <str>                    # 既有
      path: <str>                    # 既有
      url: <str>                     # 既有（base_url + path）
      status: "configured" | "requires_chrome_cdp" | "ok" | "error" | "timeout"
                                     #   check=0 → 前两者（§2.9.1 修正后取值）
                                     #   check=1 → 仅覆盖 5 个 RSS 源的 status 为 ok/error/timeout；
                                     #             其余 10 个 JSON/CDP 条目**仍为** configured / requires_chrome_cdp
                                     #             （`_run_health_checks` 只检查 ROUTES 的 5 个 RSS 源）
      items: <int>                   # 仅 check=1 且 status==ok
      error: <str>                   # 仅 check=1 且 status∈{error, timeout}
  stale: true                        # 仅"准入失败"时出现（值恒 true；不存在 ≠ false）
  metrics: {<name>: <number|object|array>, ...}          # metrics.snapshot()（★ v1.9 / F3：20 名冻结注册表，含 http_304_total）
  policy: {<domain>: {tier,ttl,pool_refresh,pool_max,cache_max[,encoding]}, ...}   # 11 域，枚举自 DOMAIN_MATRIX
  cdp: {state: "idle"|"restarting"|"unavailable", window_start: <float|null>, window_end: <float|null>}
```

### 3.2 healthz 模块级状态

```yaml
_health_executor: ThreadPoolExecutor | null      # 懒创建；max_workers = MAX_HEALTH_INFLIGHT(5)；thread_name_prefix='healthz'
_health_executor_lock: threading.Lock            # 仅保护懒创建（双检）
_health_sem: threading.BoundedSemaphore          # 初值 MAX_HEALTH_INFLIGHT = 5；★ 有界准入（stale 可达）
_HealthBatch: <class>                            # ★ P1-1：一次 check 的在飞记账（_remaining/_lock/_done）
                                                 #   task_done() 归零 ⇒ _release_health_slot()（幂等，恰好一次）
_health_inflight: <int>                          # 在飞**准入批次**数（gauge healthz_inflight；含"已返回响应但任务仍在跑"的批次）
_health_inflight_lock: threading.Lock
_health_last_snapshot: <dict|null>               # 上次 payload 的深拷贝（stale 回退源）
_health_last_lock: threading.Lock
_HEALTH_TOTAL_BUDGET: 10.0                       # 秒（整体闸；多源排队时生效）
_HEALTH_SOURCE_BUDGET: 3.0                       # 秒（★ 每源独立，按各自 submitted_at 判定）
_HEALTH_POLL: 0.25                               # 秒
_fanout_executor: ThreadPoolExecutor | null      # ★ 懒创建；max_workers = _FANOUT_MAX_WORKERS(3)；thread_name_prefix='fanout'
_fanout_lock: threading.Lock                     # 仅保护懒创建（双检）
_FANOUT_MAX_WORKERS: 3                           # ★ hotplate/plate/longhu 共享的外部上游扇出并发上限（SAD §4.1）
```

### 3.3 路由与 shape 结构（运行时视图）

```yaml
ROUTES:                                          # 既有，5 个 RSS
  '/cls/telegraph': {handler: handle_cls_telegraph, name: 'CLS Telegraph (财联社电报)', title: 财联社电报,
                     link: 'https://www.cls.cn/telegraph', description: 财联社实时快讯}
  '/eastmoney/kuaixun': {...}  '/ths/kuaixun': {...}  '/jin10/flash': {...}  '/wallstreetcn/live': {...}
_JSON_SHAPES:                                    # §2.2，14 项（object×8 / batch×6 / text×1）
_SHAPES: [batch, object, rss, text]
_CACHE_AGE_DOMAINS:                              # ★ 新增：_cache_age 的 path → domain 映射（唯一权威）
  '/finance/market': quote    '/finance/timeline': quote        # ★ v1.2：面板 = 实时行情面（L1，**非** 300）
  '/quotation/market': quote  '/market/timeline': quote         # ★ v1.2
  '/stock/data': quote        '/stock/basic_info': quote
  '/stock/fundflow': fundflow '/stock/timeline': timeline
  '/stock/f10': f10           '/stock/announcement': announcement
  '/cls/hotplate': plate      '/cls/plate': plate
  '/ths/longhu': longhu       '/market/margin': margin
  '/cls/telegraph': feed      '/eastmoney/kuaixun': feed      '/ths/kuaixun': feed
  '/jin10/flash': feed        '/wallstreetcn/live': feed      # ★ v1.9 / F4：5 个 feed path 单一 authority = feed（原 news_url）
  # 未登记（/healthz、/、/opml.xml）→ _DEFAULT_AGE_DOMAIN('f10'，L4 恒 300)
_feed_fetch_locks: dict[cache_key -> threading.Lock]  # 既有（cache.py 模块级）；★ v1.9 / F2：键为 `_feed_cache_key`（原 path）；★ v1.10 / F8：本模块**不再直接访问**，仅经 feed_fetch_acquire/release
_feed_fetch_locks_lock: threading.Lock           # 既有（cache.py 模块级）；★ v1.10 / F8：由 acquire/release 内部持有，server 不 import
_feed_fetch_refs: dict[cache_key -> int]         # ★ v1.10 / F8：引用计数（cache.py，同受 _feed_fetch_locks_lock）；归零与锁一同 pop
```

### 3.4 `BoundedThreadPoolServer` 状态

```yaml
executor: ThreadPoolExecutor(max_workers=MAX_WORKERS=20)
_inflight: <int>              # 运行 + 排队（受 _inflight_lock）
_inflight_lock: threading.Lock
_max_inflight: MAX_INFLIGHT if max_inflight is None else max_inflight
                              # 主端口 = MAX_INFLIGHT(40)（config 显式；env MAX_INFLIGHT 可调）
# stream 侧实例：max_workers = MAX_STREAM_CONNS + 10 = 110
#               max_inflight = MAX_STREAM_CONNS + 10 = 110  ⇒ _max_inflight = 110（★ 修 P1-4，见 §10#11）
```

---

## 4. 业务规则（编号供伪代码与测试引用）

### 4.1 路由与异常边界

| 编号 | 规则 | 依据 |
|------|------|------|
| **BR-SRV-1** | 分发顺序（固定）：`/` → `/opml.xml` → `/healthz` → `_JSON_SHAPES` 的 `batch` 六分支 → `object` 分支（4 面板 + hotplate + plate + margin）→ `text`（longhu）→ `ROUTES`（rss）→ `send_error(404)`。**顺序即优先级**，不得重排 | 现状 + §2.2 |
| **BR-SRV-2** | `shape` **只**从 `_JSON_SHAPES` 派生；任何新增 JSON 分支未登记 → 走 404（**不静默当 object**） | SAD §2.4（P1-6 防复发） |
| **BR-SRV-3** | `_guard` 捕获 `Exception`（非 `BaseException`）；`batch` 异常 ⇒ 全码 `null` + `_errors[code]='upstream_error'`；`object`/`text` ⇒ `{'error': str(exc)}`；`rss` ⇒ `generate_error_rss`。**任何 handler 异常都不得穿透 `do_GET`/`do_HEAD`** | R1 / AC-S1 |
| **BR-SRV-4** | `_guard` **不吞**写入阶段断连异常（写入在 guard 之后）；`do_GET`/`do_HEAD` 以 `except OSError` 吞掉（★ v1.2 由 `BrokenPipeError`/`ConnectionResetError` 扩为 `OSError`，含 `TimeoutError`/流端口 parity） | 现状保留（v1.2 扩容） |
| **BR-SRV-5** | 批量响应**永不含顶层 `error`**；单体/面板响应**永不含逐码值域**（跨类别即失配） | AC-A5 |
| **BR-SRV-5b** | **业务端点降级 = `200 + error 体`（★ v1.3 / N1 回退）**：`object`/`text` shape 的 payload 若仅由 error 客体包装（`{'error': …}` / 保留键 `_error`），仍以 **HTTP 200** 返回原样降级体——**状态码不得由 payload 内容决定**（`_json_payload_has_data` 已删）。**真实 503 = 三条**：`_reject_503`（连接准入）、`stream._serve_sse`（流端口准入）、`/healthz`（端点自身语义）。v1.2 的"error-only ⇒ 503 + 计 `http_503_total`"**已作废** | **N1 裁决** / AC-A5 / 既有消费契约 |
| **BR-SRV-5c** | **`/market/margin` 参数门（v1.2）**：`market ∉ VALID_MARKETS` ⇒ **400**（guard 之前，不建缓存键、不发上游请求）；`market` 缺省 `'99'` | A5 |

### 4.2 feed 缓存与 TTL

| 编号 | 规则 | 依据 |
|------|------|------|
| **BR-SRV-6** | `_get_or_fetch_feed` 的 **miss → `feed_fetch_acquire` 取 per-键 锁 → 二次 `feed_cache_get_entry`（双检）→ fetch → `feed_cache_put` → `feed_fetch_release`（`finally`）** 顺序**不可省略双检**；回源失败不写缓存、不写错误 RSS（★ v1.10 / F8：加锁经原语、`release` 在 `finally`） | 裁决 #3 / `cache.md` §2.4 / **BR-SRV-50** |
| **BR-SRV-7** | feed TTL 恒 = `cache_policy('feed')['ttl']`（盘 30 / 非盘 180）；★ **v1.9 / F4**：`_cache_age()` 的 RSS 分支**也读 `feed` 域**（`_CACHE_AGE_DOMAINS` 的 5 个 feed path 已由 `news_url` 改映射 `feed`）⇒ 服务端承诺（`Cache-Control: max-age=30`）= 实际新鲜度 = 单一 authority（**修 D4 + F4**；数值不变，仅换 authority） | SAD §2.1 D4 / Q3 / AC-A8 / **BR-SRV-47** |
| **BR-SRV-8** | `_cache_age()` 用 **`urlparse(self.path).path`**（v1.2：与路由同规则，absolute-form 请求行不再落到兜底域）**只**经 `_CACHE_AGE_DOMAINS` → `cache_policy(domain)['ttl']`；未登记路径（**仅** `/healthz`、`/`、`/opml.xml`）→ `_DEFAULT_AGE_DOMAIN`（`f10`，L4 恒 300）。**禁止裸 TTL 字面量** | ADR-001 / BR-CFG-12 |
| **BR-SRV-8b** | **4 CDP 面板的 `_cache_age` 域 = `quote`（L1，8/120）**（v1.2）：面板是实时行情面，**不得**落 `_DEFAULT_AGE_DOMAIN('f10')` 的 300s（否则实时行情被标 `max-age=300`） | S2-3 / AC-A3 |
| **BR-SRV-9** | `/ths/longhu` 的两个 URL 使用**同一** `cache_policy('longhu')` 的 `ttl`（=300）与 **`encoding`（`policy['encoding']='gbk'`，不再硬编码字面量）**；**消除直连 `urlopen`**（R15）。AC-E9 计数口径：每个 URL 各回源 1 次、共 2 次；连续 10 次请求其余 9 次命中 | SAD §2.3 D-5 / AC-E9 |

### 4.3 plate stagger（D-7 **明令保留**）

| 编号 | 规则 | 依据 |
|------|------|------|
| **BR-SRV-10** | `base_ttl = cache_policy('plate')['ttl']`；`stagger = max(3, base_ttl // 4)`；**offset = stagger × 分区序** | SAD §2.1 / `cache.md` REV-DES-01 脚注 |
| **BR-SRV-11** | `handle_cls_hotplate` 分区序：`industry`=0、`concept`=1、`area`=2 ⇒ TTL = `base + stagger×idx`（盘中 12/15/18；非盘中 120/150/180，等价 ×1/1.25/1.5） | 同上 |
| **BR-SRV-12** | `handle_cls_plate` 分区序：`info`=0、`stocks`=1、`industry`=2 ⇒ TTL = `base + stagger×idx` | 同上 |
| **BR-SRV-13** | **严禁**把三档压成同一个 `cache_policy('plate')['ttl']`（静默丢弃错峰 = 行为回归）；`_STAGGER`/offset **不得**写成裸字面量 | SAD D-7 / `cache.md` §2.6 脚注 |

### 4.4 批量截断

| 编号 | 规则 | 依据 |
|------|------|------|
| **BR-SRV-14** | `> _MAX_BATCH_SIZE(50)` ⇒ `dropped = len(codes) - 50`，**只截断请求码**（不截断 handler 内部 2000 码路径——stream 直调 handler，不经本处） | SAD §2.4 |
| **BR-SRV-15** | `dropped` **只经参数**传入 handler；`_truncated`/`_dropped_count` 由 `build_batch_response` 挂载（`dropped>0` 才同现；`dropped<=0` 两键都不存在） | AC-A9 / `cache.md` BR-CACHE-17 |
| **BR-SRV-16** | 截断必须 `log.warning`（保留现状：含丢弃数 + 前 3 个样本） | 现状保留 |

### 4.5 healthz

| 编号 | 规则 | 依据 |
|------|------|------|
| **BR-SRV-17** | `check=0` **零上游**：不创建执行器、不触网、不占准入位；只读 policy + metrics + cdp 快照 | AC-S8 / SAD §2.6 |
| **BR-SRV-18** | **准入先于提交**：`_health_sem.acquire(blocking=False)` 失败 ⇒ `metrics.incr('healthz_stale_total')` + 返回"上次快照 + `stale:true`"（无快照则用本次零上游体 + `status='degraded'`）；**不触网、不阻塞、不排队** | 修 P1-3（可达可测） |
| **BR-SRV-19** | 准入成功后，准入位**必须在该批 `len(ROUTES)` 个任务真正结束之后**释放：由每个 future 的 `add_done_callback(_HealthBatch.task_done)` 驱动，归零时调 `_release_health_slot()`（`_set_health_inflight(-1)` + `_health_sem.release()`）**恰好一次**；执行器创建失败/提交失败/异常返回/超时/正常完成**五路均销账**。**禁止**在 `_run_health_checks` 返回时立即释放（P1-1：否则准入位只覆盖轮询窗口 ⇒ 执行器无界队列累积） | 并发正确性 / AC-S8（修 P1-1） |
| **BR-SRV-20** | `check=1` 走专用执行器（`max_workers=MAX_HEALTH_INFLIGHT=5`）与主池物理隔离；**单源**独立 ≤3s（按各自 `submitted_at` 判定）、**整体** ≤10s（多源排队时的总闸，**非死代码**）；超时源记 `status='timeout'` + `status='degraded'` | ADR-006 / AC-S8 / SAD §2.2 R-2（修 P2-2） |
| **BR-SRV-21** | healthz **必须总函数**：调用点以 `_guard(..., shape='object')` 兜底 ⇒ 任何异常返回 `{'error': …}` 且 **HTTP 503**（★ v1.2；★ v1.3 明确**这是 healthz 端点自身语义**——`{'error': …}` 在本端点 ⇒ 服务不可用；**业务端点不采用**，见 BR-SRV-5b），**不得**穿透 | AC-S1 / S2-5 |
| **BR-SRV-22** | `feeds[]`/`cache_ttl`/`request_timeout` 键集合与含义**一个不少**；新增仅 `stale`/`metrics`/`policy`/`cdp`（🟠 STABLE 只增）；`feeds[].status` 取值修正按 §2.9.1（**须编排层批准**） | SAD §2.6 P2-N1 / Q2 |
| **BR-SRV-23** | `cache_ttl` = `cache_policy('feed')['ttl']`（字段名与含义不变，取值跟随 policy） | ADR-001 / Q2 |
| **BR-SRV-24** | `_remember_health_snapshot` 仅在**成功组装**（含 `check=1` degraded 结果）后调用；**准入失败路径不刷新快照**（否则 stale 链会自我覆盖） | 设计裁决（§10#5） |

### 4.6 过载与守护

| 编号 | 规则 | 依据 |
|------|------|------|
| **BR-SRV-25** | inflight 达 `MAX_INFLIGHT` ⇒ **立即 503**（`{"error":"server busy"}`）+ `metrics.incr('http_503_total')`；**不排队**、不等待；撤销负载后 5s 内恢复 200（无残留准入） | AC-E8 / S5 |
| **BR-SRV-26** | `_cdp_memory_watchdog`：`time.sleep(CDP_RESTART_INTERVAL)` → `reason = cdp_engine.watchdog_restart_skip_reason()`；`reason is not None` ⇒ `log.info('…skipped (%s)', reason)` + `continue`（**本轮跳过、顺延下一周期、不累积**）；否则 `log.info(...)` + `full_chrome_restart()`；`except Exception` 仅日志 | ADR-012 / R19 |
| **BR-SRV-27** | 4 面板 handler（A 类）**只经** `cdp_engine.page_data(page)` 取数；`None` ⇒ `{'error': …}`；`timeline` 键为 `None` ⇒ `{'error': 'timeline unavailable'}`（**禁止裸 `null`**）；**删除**对 `page.get_data()` 的直接 `.pop/.get` 链 | R18 / AC-S4 |
| **BR-SRV-28** | 5 个 RSS handler 的 `ttl` 一律 `cache_policy('news_url')['ttl']`；`fetch_json` 调用点**签名零改动**（`encoding` 默认 utf-8） | ADR-001 / `cache.md` §2.6#1–#5 |
| **BR-SRV-29** | 启动日志的 `Cache TTL` 读 `cache_policy('feed')['ttl']`（删 `CACHE_TTL` 后不得留断链）；`main()` 中 `_cdp_memory_watchdog` 依赖的 import 与 `config.cdp_engine` 槽语义不变 | 现状 + Q3 |
| **BR-SRV-30** | `/cls/hotplate`（3 分区）、`/cls/plate`（3 段）、`/ths/longhu`（2 URL）的多上游请求**一律**经 `_get_fanout_executor()`（`max_workers=_FANOUT_MAX_WORKERS=3`）**≤3 并发展开**；单端点耗时 = `max(单次取数)` 而非 `sum`，上界 = 一次 `fetch_json` ≤ `REQUEST_TIMEOUT`(10s) ⇒ **单请求 ≤15s（AC-E2）**。**禁止**多上游串行累加（SAD §4.1 明令本轮修） | SAD §4.1 / **AC-E2**（修 P1-2） |
| **BR-SRV-31** | `/cls/hotplate` 失败形态**唯一口径**：分区 error 客体（`plate_<type>` = `{'error':…}`，分区可独立降级）+ **三分区全失败时顶层补 `error`**（值 = 三块 error 摘要）；`hot_plates` 仅在至少一个分区取到 `main_fund_diff` 时出现 | SAD §2.3 D-4 / §2.4 / AC-A5（修 P1-3） |
| **BR-SRV-32** | **longhu 席位配对（v1.2 / P0 修复）**：每匹配到一个"买入/卖出前5名营业部"`<th>` 标签的表 ⇒ `broker_idx` **无条件自增**（即便该表解析出 0 条 `entries`——`len(bro_cells)<4`、空名、`<th>` 数据行）。`stock_idx = broker_idx // 2` 与 `stocks` 位置配对，**跳过自增会静默错配后续所有股票的席位**（HTTP 200 无错误信号）。`stock_idx >= len(stocks)` ⇒ `log.warning` 丢弃该项（不静默）；末尾 `broker_idx != 2×len(stocks)` ⇒ `log.warning` 错位告警 | P0 / 数据正确性 |
| **BR-SRV-33** | **请求派生 base URL 加固（v1.2 / S2-3）**：`PUBLIC_BASE_URL` 非空则恒优先；否则取 `X-Forwarded-Host` → `Host`，格式校验（`hostname[:port]`/`[v6][:port]`，非法 ⇒ `localhost:PORT`），并在响应标 `Cache-Control: private` + `Vary: Host, X-Forwarded-Host, X-Forwarded-Proto`（feed/opml 体嵌入了该 Host ⇒ 防共享缓存串号污染） | S2-3 |
| **BR-SRV-34** | **响应 gzip 协商（v1.4 / AC-E1）**：`_accepts_gzip(header)` 按 RFC 9110 §12.5.3 解析 `Accept-Encoding`（逗号分隔 token + `;q=` 权重、coding 大小写不敏感、显式 `gzip` 覆盖 `*`、**`q=0` 表示拒绝**）；`_send_text` 仅当 `len(body_bytes) >= config.GZIP_MIN_BYTES` **且** 被接受时 `gzip.compress(..., config.GZIP_COMPRESSLEVEL)` 并加 `Content-Encoding: gzip`；**`Vary: Accept-Encoding` 在 `gzipped or cache` 时必发**（表示随编码变，不可缓存响应亦须标） | AC-E1 / S1（旧子串匹配对 `gzip;q=0` 误压缩、漏 `GZIP`） |
| **BR-SRV-35** | **启动传输预热（v1.4 / 冷启动）**：`main()` 起 `threading.Thread(target=warm_transport, daemon=True)`——`cache.warm_transport` 走池**仅握手不发业务请求**（主机由 `config.warm_hosts()` 从 URL 常量派生），**总函数绝不抛**；不阻塞启动、不参与 `/healthz`；失败静默 | BUG-冷启动-01（冷扇出 ≈4.2s > 0.8×tick） |

### 4.7 RSS 条件请求（★ v1.5；`GET`/`HEAD`，仅 5 个 `ROUTES` feed）

| 编号 | 规则 | 依据 |
|------|------|------|
| **BR-SRV-36** | **适用范围**：**仅** `ROUTES` 的 5 个 RSS 路径的 **GET / HEAD**。`/opml.xml`、`/`、`/healthz`、全部 JSON 端点**不支持**条件请求（不改路由、不改方法、不改 status 语义）。无任何条件头 ⇒ 行为与 v1.4 **逐字一致**（200 全量） | 端锁定 🟠 STABLE / BR-SRV-44 |
| **BR-SRV-37** | **ETag 派生（弱校验器）**：`etag = 'W/"' + sha256(normalize(xml)) + '"'`，其中 `normalize` = 用**空占位**替换三类"非内容元数据"的**内容**，再对整串 utf-8 哈希：① `<lastBuildDate>…</lastBuildDate>`（`count=1`）；② `<ttl>…</ttl>`（`count=1`）；③ **`<pubDate>…</pubDate>`（★ v1.6 / C1：`count=0` 全量替换，item 有多条）**。**严禁裸 body 哈希**（`lastBuildDate` 每调用即变 ⇒ TTL 到期重生成后 ETag 必变 ⇒ 永远 200 ⇒ 功能静默失效）。**item 级 pubDate 必须同剔（★ v1.6 / C1）**：eastmoney `showtime`、ths `ctime`、jin10 `time` 解析失败时**回落到当前时间**（`formatdate(timeval=None)` / `int(time.time())`，证据 `server.py:107/133`、`utils.py:241`），该回落落在哈希区 ⇒ 3/5 feed 每次 TTL 到期重生成都换 ETag ⇒ 永远 200。item 的**身份**由 `<guid>` 承载，`pubDate` 属上游元数据且存在**已知非确定性回落** ⇒ 剔除后仍保持"内容变 ⇒ ETag 变"（`guid`/`title`/`link`/`description`/channel 字段/`<atom:link feed_url>` 任一变化照旧改 ETag）。**不变式（双向，★ v1.6 / C1 改写）**：**「内容（除 `pubDate`/`lastBuildDate`/`ttl` 三项外）未变 ⇒ ETag 不变（不误 200，本专项 R1 正向）且除 `pubDate`/`lastBuildDate`/`ttl` 三项外的任一字节变化 ⇒ ETag 必不同（不误 304，反向）」**（★ P3a-r2 / P2-b：第二子句补「除三项外」限定语，消除"内容变 ⇒ ETag 必变"的 overclaim——仅 `pubDate` 字节变化时 ETag **不变**，属已登记的可接受权衡）——v1.5 只保证反向（不误 304），把 R1 的"内容未变 ⇒ ETag 不变"命题漏掉，故**不可妥协项 #2 只闭合了一半**；本版补齐正向。**`<pubDate>` 取舍（可接受权衡）**：上游**真实**更正某条 item 的 `pubDate` 时 ETag **不变** ⇒ 下游持旧副本直到其它字节变化或 TTL 语义外的强制刷新；**权衡理由**：① `pubDate` 在 3/5 feed 上是"解析失败的当前时间回落"，纳入哈希会使条件请求**必然失效**（本专项第一目标的直接对立面）；② 在可解析的 feed 上 `pubDate` 是上游元数据、非下游消费身份（`guid` 才是）；③ 其变化通常伴随 `title`/`description`/新增 item 等**真内容**变化 ⇒ 实际漏报面极小。**成本**：一次 regex + 40KB sha256 ≈ 0.1–0.2ms，远小于同响应的 gzip(level=1)。**碰撞**：sha256 256-bit 抗碰撞；ETag 仅作等值比较，不作安全边界。**弱**：因规范化去除了字节差异，按 RFC 9110 §8.8.3 语义必须标记 `W/`。**编码无关**：ETag 在 gzip 之前由未压缩 XML 派生 ⇒ gzip/identity 两个表示共享同一弱标签（弱校验器允许），304 时各客户端复用自身缓存副本；**故 304 不得携带 `Content-Encoding`** | RFC 9110 §8.8.3 / 本专项 R1（**P1-01 定向修**） |
| **BR-SRV-38**（★ **v1.9 / F1 本版改写**——「feed 缓存条目写入时刻」表述**全部作废**） | **Last-Modified = 「表示最后一次变更的时刻」**：`last_modified = feed_cache_get_entry(cache_key)['last_modified']`（epoch 秒）；发送格式 `formatdate(timeval=last_modified, localtime=False, usegmt=True)`。**时间源 = feed 条目的 `last_modified` 字段**，由 `feed_cache_put` 维护：与**同一键的上一条目**（★ **即使该条目已过期也参与比较**——这正是「跨 TTL 重生成仍是 304」的机制）比较 `fingerprint`（规范化摘要，与 ETag 同源）：相同 ⇒ **继承**上一 `last_modified`；不同 ⇒ 取**本次写入时刻**。**不变式（必须作为可断言契约）：在「同一键存在上一条目」的路径上，`ETag` 变 ⟺ `Last-Modified` 前进**（二者同源于同一 `fingerprint`）；**唯一例外**是下句的"无上一条目"降级（`ETag` 可不变而 `Last-Modified` 前进，属已登记的**可接受降级**）。**无上一条目**（首次 / 已被 LRU 淘汰 / 已被 sweep）⇒ `last_modified = 本次写入时刻`——**退化为一次性 200 后恢复 304，属可接受降级**（写进契约，非缺陷）。**仅在真实缓存条目存在且含该字段时**才有值——① 降级/回源失败路径（`_guard` rss 分支）为 `None`；② ★ **v1.11 / P2-1**：legacy / 非六字段缓存条目缺 `last_modified`（cache 层以 `entry.get('last_modified')` 读取）亦为 `None` ⇒ **不发 `Last-Modified`、`If-Modified-Since` 不可评估**（`If-None-Match` 仍按 ETag 正常评估），**绝不抛 `KeyError`、绝不拿陈旧条目的时间冒充降级体**。**副作用（须写进契约）**：`last_modified` 可能**远早于** body 内 `<lastBuildDate>`（语义正确：前者表示"未变"，后者是生成时刻）。**不得修改 `feed_cache_get` 签名**（5 调用方 + `tests/test_cache.py`）；新访问器/写入器见 BR-CACHE-32/33/34。**被否决的备选（决策记录）**：`Last-Modified = max(items 的 pubDate)` 虽免状态，但上游**改描述不改 pubDate** 时会发出**错误 304（陈旧数据）**；对交易数据服务，**错误 304 远比多发 200 严重**，故否决 | 裁决 #3 / `cache.md` §2.4 / **P8 F1（P1-1）** |
| **BR-SRV-39** | **条件头优先级与 If-None-Match**：`If-None-Match` **优先于** `If-Modified-Since`（RFC 9110 §13.1.3）——只要 INM **存在**，就**只**评估 INM（匹配 ⇒ 304；不匹配 ⇒ 200），**完全忽略** IMS。INM 支持：`*`（任何当前表示 ⇒ 命中）、逗号分隔**多值列表**（任一项命中 ⇒ 304）、`W/` 弱前缀（**弱比较**：`W/"x"` 与 `"x"`/`W/"x"` 视为同一 opaque tag，RFC 9110 §8.8.3.2）。**弱指示符大小写敏感（★ v1.6 / C5 措辞修正）**：**只接受字面 `W/`**；小写 `w/"…"` **不**匹配（按 opaque tag 字面比较）⇒ **200**（RFC 9110 §8.8.3 的弱指示符大小写敏感；v1.5 的"不区分大小写前缀"表述与实现冲突，已更正）；空白容忍 | RFC 9110 §13.1.2/§13.1.3 |
| **BR-SRV-40** | **If-Modified-Since**：仅在 INM 缺失时评估。用 `email.utils.parsedate_to_datetime` 解析（naive ⇒ 视为 UTC），转 epoch 后 **秒级**比较：`int(last_modified) <= int(ims_epoch)` ⇒ 304，否则 200。**非法/不可解析的日期头必须忽略并退回 200**（`except (ValueError, TypeError, OverflowError, OSError)`），**绝不 400/500**；`last_modified is None` ⇒ 忽略。★ **v1.6 / C4（P2-01）**：**解析、补时区、`dt.timestamp()` 全部在同一个 `try` 内**——`dt.timestamp()` 对超大年份/平台 `time_t` 越界可抛 `OverflowError`/`OSError`，若写在 `try` 之外则穿透 `do_GET`/`do_HEAD` 的 `except OSError` 之外 ⇒ 连接中断（非 200）；故 `except` 增 `OSError` 并把 `timestamp()` 纳入受保护区。发送侧 `formatdate` 亦为秒级（截断），保证客户端回显我们发出的 `Last-Modified` 时 `<=` 成立 | RFC 9110 §13.1.3 / §15.4.5 / **P2-01** |
| **BR-SRV-41** | **304 响应组成（RFC 9110 §15.4.5）**：由专用 `_send_not_modified(etag, last_modified, varies_on_host)` 生成——**无 body**、**不得有 `Content-Encoding`**（**不得**对 304 gzip）、**不发 `Content-Length`**、不发 `Content-Type`；**必带** `ETag`（当前弱标签）+ `Cache-Control`（**与 200 同值**：`private`/`public` 由 `varies_on_host` 判定 + `max-age=self._cache_age()`）+ `Vary`（`varies_on_host` 时为 `Host, X-Forwarded-Host, X-Forwarded-Proto, Accept-Encoding`，否则 `Accept-Encoding`）。**304 不调用 `feed_cache_put`、不写任何缓存**（LRU 触碰由读取路径完成）。**`HEAD` 与 `GET` 走同一条件判定** ⇒ HEAD 亦得 304 | RFC 9110 §15.4.5 / §8.6 |
| **BR-SRV-42** | **200 RSS 响应头（仅增）**：`_send_text` 新增可选 `etag`/`last_modified` ⇒ 200 必发 `ETag`，有缓存条目时发 `Last-Modified`；其余头（`Content-Type`/`Content-Length`/`Cache-Control`/`Vary`/`Content-Encoding`）与 v1.4 **逐字不变**。`Cache-Control` 与 304 **同一值来源**（★ v1.9 / F4：`_cache_age()` = **`feed` 域** ⇒ 盘 30 / 非盘 180，原 `news_url` 已改） | 本专项 / BR-SRV-7 / **BR-SRV-47** |
| **BR-SRV-43** | **RSS `<ttl>`**：`generate_rss` 新增可选形参 `ttl=None`（**分钟**整数）；`None` ⇒ 不输出元素（向后兼容）。5 个 RSS handler（**6 处 `generate_rss` 调用点**——`handle_eastmoney_kuaixun` 的**常规返回**与「**无匹配 ⇒ 空 feed**」**提前返回**两处**均**传 `ttl=_feed_ttl_minutes()`，使该罕见路径的 feed 表示与常规路径一致；★ v1.8 / D-2）传 `ttl=_feed_ttl_minutes()`；`_feed_ttl_minutes() = max(1, (cache_policy('feed')['ttl'] + 59) // 60)`（盘 30s→`1`、非盘 180s→`3`）。★ **v1.6 / C7#12（P2-07）值域护栏**：生成侧仅当 **`ttl is not None and int(ttl) > 0`** 时输出 `<ttl>`——RSS 2.0 要求**正**整数；`generate_rss(ttl=0)` / `ttl<0` ⇒ **不输出**（不得出现 `<ttl>0</ttl>`）。**位置**：紧随 `</lastBuildDate>`、在 `<atom:link>` **之前**。**对 ETag 的影响**：`<ttl>` 与 `<lastBuildDate>` 一样在规范化时**被剔除**（二者皆为派生新鲜度元数据，盘中/非盘切换会使其变化）；剔除后 ETag 仅由**内容**决定 ⇒ 日内交易时段边界不产生假 200。<br>★ **【C3 / P1-03 · 契约语句，必须进 `API.md`】「`<ttl>` 是聚合器缓存提示，非时效保证；需要比 1 分钟更快的时效请用 SSE（4s）」。** 语义细则：**① 最小粒度 = 1 分钟**——RSS 2.0 的 `<ttl>` 只能表达整分钟，盘中缓存 TTL 30s 由 `max(1, …)` **向上取整为 `1`**（不得向下取整为 `0`，也**不得**恒输出 `3`——后者会与 `Cache-Control: max-age=30` 直接冲突并丢掉盘中低延迟意图）；**② 推荐轮询策略 = 「`ETag` 条件请求优先，轮询间隔 ≥ 30s」**——下游应按 `If-None-Match` 拿 304（零 body、省带宽），**不得**照抄 `<ttl>1</ttl>` 把轮询放慢到 60s（服务端 `max-age=30` 比它更激进）；**③ `Cache-Control: max-age` 是更强的承诺**（盘 30 / 非盘 180），`<ttl>` 仅为 advisory。**本条是"下游照抄 `<ttl>1</ttl>` 把时效降到 1 分钟"这一误导风险的唯一缓冲**（见契约影响 #4） | RSS 2.0 `<ttl>` / 本专项 R1 / **C3（P1-03）** |
| **BR-SRV-44** | **出范围项（本轮不做，仅登记）**：① `RSSHandler.protocol_version` 升 **HTTP/1.1** 以启用 keep-alive（改变连接复用语义，**波及全部端点与线程池占用**，须独立评估）；② `/opml.xml` 与 `/` 的条件请求（静态内存拼接，无缓存条目时间源）；③ JSON 端点条件请求（不适用；其 `Cache-Control` 已由域 TTL 承担）。**上述三项不得在本轮顺带实现** | 端锁定 / 范围纪律 |
| **BR-SRV-45**（★ v1.9 / F2 新增） | **feed 缓存键必须覆盖表示的全部变化维度**：`cache_key = _feed_cache_key(path, base_url)`——`PUBLIC_BASE_URL` 已设 ⇒ `= path`（与 v1.8 现状**逐字一致**，该模式下表示与 Host 无关）；未设 ⇒ `= path + '\x00' + base_url`（`base_url` = `_base_url()` 结果）。理由：body 内嵌请求 Host 派生的 `<atom:link rel=self>`，而缓存此前**只按 path 建键** ⇒ **一条伪造 Host 的请求就能在一个 TTL 内改写所有读者的订阅链接**，**头（`Vary: Host, X-Forwarded-Host, X-Forwarded-Proto`）与行为不符**。键对 `cache.py` 是**不透明字符串**（cache 层不引入 Host/`PUBLIC_BASE_URL` 概念）；`feed_cache_get`/`feed_cache_get_entry` **签名不变**、接受该键。**放大风险论证（评审会核对；★ v1.10 / F8 补正）**：① 上游 JSON 取数另有 URL 级缓存（handler 内 `fetch_json(..., ttl=cache_policy('news_url')['ttl'])`）⇒ 键增多**不放大上游请求**（同一上游 URL 仍只取一次）；② 条目数受 `cache_policy('feed')['cache_max']=100` + LRU 约束；③ 非法 Host 经 `_valid_host_header` 一律塌缩为 `localhost:PORT` **单键**（不能靠畸形 Host 枚举）。**★ v1.10 / F8 限定（原论证不完整）**：以上 ①–③ **只证明"不放大上游请求"，未覆盖锁表内存与本地生成**——F2 后键空间 = `path × 请求派生 base_url`，而 `_valid_host_header`（`server.py:591`）**只校验格式、不校验归属** ⇒ **任意合法主机名可造新键**，后果：(a) `_feed_fetch_locks` **永久内存增长**（每键约 300–450 B，外部可无界触发直至 OOM）；(b) 键数超过 `feed_cache` 上限 100 后每个新 Host 必 miss ⇒ 一次 `generate_rss` + sha256，LRU 持续抖动（**只放大本地 CPU，上游仍被 URL 级缓存兜住**）。故本 BR 的键语义**必须**与 **BR-SRV-50（锁表同界收敛）** 成对落地。`_feed_fetch_locks` 按 `cache_key` 建锁（防击穿按键隔离），其生命周期由 BR-SRV-50 收敛 | **P8 F2（P1-2）+ F8** / BR-SRV-33 |
| **BR-SRV-46**（★ v1.9 / F3 新增） | **`http_304_total` 指标（304 计数）**：在 `_send_not_modified` 内**单点** `metrics.incr('http_304_total')`（与 `http_503_total` 的"单点"风格一致，保证**任何 304 都被计入、不可能漏记**）；计数在 `end_headers()` 之前发生。`metrics._KNOWN` 与 `_DEFAULTS` **同时注册**（`metrics.md` v1.5 / BR-MET-14）。**为什么只需要计数、不需要分母**：该计数**单调**；若"`pubDate` 抖动 ⇒ 永远 200"的回归发生，该计数**停止增长**本身就是报警信号（一个既不增长、又无分母的计数即足够），无需 200 分母。<br>★ **v1.10 / F8 备注（P2-5 口径）**：计数发生在**构造 304 响应时**（`_send_not_modified` 内、`end_headers()` 之前）⇒ 极少数「**计数已增但响应未送达客户端**」的情形（客户端中途断开 / `send_response` 抛错）**会计入**——这是**有意的语义**：该计数反映"**服务端决定返回 304 的次数**"，**不是**"客户端成功收到 304 的次数" | **P8 F3（P2-6）+ F8（P2-5 口径）** / AC-S10 |
| **BR-SRV-47**（★ v1.9 / F4 新增） | **feed 的 `max-age` authority = `feed` 域**：`_CACHE_AGE_DOMAINS` 的 5 个 feed path 由 `news_url` 改映射 `'feed'`。此前 `<ttl>` 与 feed 缓存 TTL 取自 `feed` 域，而 `max-age` 取自 `news_url` 域 ⇒ 同一件事（"建议多久轮询"）有**两个 authority**、可静默漂移。**今日数值不变**（两域同为 L3、`ttl_factor=1.0` ⇒ 盘中 30 / 非盘 180）——**只换 authority，数值不变、契约不变**。**不变式（可断言）**：`_feed_ttl_minutes() == ceil(feed 路径的 max-age / 60)`。理由：`news_url` 的语义是"上游 URL 取数缓存"，用它决定 **RSS 响应**的 `max-age` 属语义错配（此前被"两域恰好同 L3"掩盖） | **P8 F4（P2-4）** / SAD D4 |
| **BR-SRV-48**（★ v1.9 / F5 新增） | **`feed_cache_put` 返回写入条目**：返回写入条目的**浅拷贝**（与 `feed_cache_get_entry` 同形态六字段，**不是 `None`**）；`_get_or_fetch_feed` miss 路径**直接使用该返回值**并**删除 put 之后的第二次 `feed_cache_get_entry` 查询** ⇒ 消除「200 带 `ETag` 却不带 `Last-Modified`」的窗口（旧路径在 put 与再查询之间若被淘汰 ⇒ `last_modified=None`，而 ETag 仍发出），并省一次加锁往返。此为**新增的可依赖行为**，须写入契约（BR-CACHE-34） | **P8 F5（P2-5）** |
| **BR-SRV-49**（★ v1.9 / F6 新增 · **仅文档化，不改代码**） | **HTTP/1.0 下 304 的收尾契约**：`RSSHandler` **未设** `protocol_version` ⇒ HTTP/1.0 短连接，304 **无 `Content-Length`**，由**连接关闭（EOF）**收尾；RFC 9110 §8.6 明令 304 **不得**发 `Content-Length: 0`（若发则其值**必须等于**该资源 200 的体长——写 `0` 反而违约，本服务 200 体 ~37KB）。本轮**不**升 `protocol_version`/keep-alive（BR-SRV-44 出范围）：该变更波及全部端点连接语义与线程池占用。**权衡如实记录**：中间件（代理/CDN）对"无长度 304 的 EOF 收尾"处理属**理论风险**，`http.client` 已实测通过（`SRV-T47`/`T62` 断言无 `Content-Length`/`Content-Type`/`Content-Encoding` 且无 body） | **P8 F6（P2-7）** / RFC 9110 §8.6 / BR-SRV-44 |
| **BR-SRV-50**（★ v1.10 / F8 新增） | **feed 取数锁表必须与键空间同界收敛**：`_get_or_fetch_feed` **不得**直接读写 `_feed_fetch_locks`，只经 cache 层原语 **`feed_fetch_acquire(cache_key) -> Lock`** / **`feed_fetch_release(cache_key)`**（`cache.md` BR-CACHE-35）。`acquire` 在**返回锁之前**把该键引用计数 +1（必要时创建 `Lock`），`release` 递减、**归零即 `pop` 该键及其计数**（两表同删）；**两者都必须持 `_feed_fetch_locks_lock`**（原语内部完成，server 不 import 该锁）。**必须 `lock = acquire(k)` → `try: … finally: release(k)`**：异常路径（`fetch_func()` 抛 / `feed_cache_put` 抛）也释放，否则**计数泄漏 ⇒ 锁表退化为只增不减**。**为什么不能简单重加 `pop`**：归零前 `pop` 会让"已取出锁但尚未进入 `with`"的线程与后来者各拿一把**不同的锁** ⇒ 同一键双抓（`系统_代码评审报告_001.md` TS-4 原事故）；引用计数的不变式是**只要还有线程持有或即将获取该键的锁，计数就 ≥1，该键不可能被 `pop`**。**正确性论证（评审会核对）**：`pop` 只发生在计数归零时，此时无任何持有者/等待者；随后到达的线程创建新锁，其双检仍命中前一个持有者已写入的缓存条目 ⇒ **不产生重复取数**（第二次真取数只可能因为条目确实已过期）。**有界性结论**：锁表规模收敛于"**并发在飞的键数**"，而非"累计见过的键数"；**`PUBLIC_BASE_URL` 已设时键恒为 5 条 path**。**可选运营缓解（备注，非契约）**：部署侧强制设 `PUBLIC_BASE_URL` ⇒ 即便暂不部署本修复，也无 Host 派生的键空间。**★ v1.12 / 实现约束（微优化，观察行为不变）**：`acquire` **必须先 `_feed_fetch_locks.get(key)` 判空、仅在 `None` 时创建 `threading.Lock()`**（命中路径**零分配**）；`setdefault(key, threading.Lock())` 会为**每次调用（含命中已有锁）**先构造一个被丢弃的 `Lock`。返回同一把锁的身份 / 计数先于返回 / 临界区语义**全部不变**（`cache.md` BR-CACHE-35 同步）。测试见 `SRV-T71`（**纯串行**收敛性）/ `SRV-T72`（并发不双抓 + 异常计数归零）/ **`SRV-T73`（并发在飞 K 键上界 + 两表同步，★ v1.12）** | **P8 F8** / `CR-RSS-20260918-003`（P1-1）/ BR-SRV-45 / AC-S9 |

---

## 5. 伪代码

### 5.1 `_guard`（统一异常边界）

```python
_SHAPES = frozenset({'batch', 'object', 'rss', 'text'})

def _guard(fn, *, shape, requested=None, dropped=0, rss_info=None, feed_url=None):
    """BR-SRV-3：任何 Exception → 按 shape 产出结构化降级体（绝不冒泡）。"""
    if shape not in _SHAPES:                                   # 编程错误：立即暴露
        raise ValueError(f'unknown guard shape: {shape!r}')
    try:
        return fn()
    except Exception as exc:                                    # 不捕 BaseException
        log.exception('[guard:%s] handler raised: %s', shape, exc)
        if shape == 'batch':                                    # 全码 null + _errors
            codes = list(dict.fromkeys(requested or []))
            errors = {c: 'upstream_error' for c in codes}
            return build_batch_response(codes, {}, errors, dropped=dropped)
        if shape == 'rss':
            info = rss_info or {}
            # ★ v1.5：rss shape 返回契约扩展为 (xml, last_modified)；
            #   降级体无真实缓存条目 ⇒ last_modified=None（禁用 IMS 304，BR-SRV-38/40）
            return (generate_error_rss(info.get('title', 'feed'),
                                       info.get('link', ''),
                                       info.get('description', ''),
                                       exc, feed_url=feed_url), None)
        return {'error': str(exc)}                              # object / text
```

> ★ v1.5：`shape='rss'` 的**成功返回**亦为 `(xml, last_modified)`（由 `_get_or_fetch_feed` 返回）⇒ **成功与异常两条路径返回形状一致**（均为 2-tuple），`_serve_feed` 无需 `isinstance` 判别。其余三 shape 契约不变。

### 5.2 `_handle_request`（分发，含 shape 派生）

```python
def _handle_request(self, write_body=True):
    parsed = urlparse(self.path)
    path = parsed.path
    base_url = self._base_url()

    if path == '/':                                             # 静态（无 IO）
        self._serve_index(write_body=write_body); return
    if path == '/opml.xml':                                     # 静态（无 IO）
        # ★ v1.2（S2-3）：OPML 嵌入 base URL ⇒ 请求派生时 private + Vary
        self._send_text(200, 'text/x-opml; charset=utf-8',
                        generate_opml(base_url, ROUTES),
                        varies_on_host=not PUBLIC_BASE_URL, write_body=write_body); return
    if path == '/healthz':                                      # BR-SRV-21：object 兜底
        query = parse_qs(parsed.query)
        check_sources = query.get('check', ['0'])[0] in ('1', 'true', 'yes')
        payload = _guard(lambda: build_health_payload(base_url, check_sources=check_sources),
                         shape='object')
        # ★ v1.2（S2-5）：guard 失败体 {'error': …} 无 status ⇒ 503（不再假健康）
        # ★ v1.3（N1）：该 503 只属 /healthz 自身语义；业务端点降级恒 200（见 _send_json_shape）
        if 'error' in payload or 'status' not in payload:
            status_code = 503
        else:
            status_code = 503 if payload.get('status') == 'degraded' else 200
        if status_code == 503:
            metrics.incr('http_503_total')
        self._send_text(status_code, 'application/json; charset=utf-8',
                        json.dumps(payload, ensure_ascii=False, indent=2),
                        cache=False, write_body=write_body); return

    # ── 4 面板（object）— handler 与 shape 均取自派发表 ────────
    if path in _PANEL_HANDLERS:
        self._send_json_shape(path, _PANEL_HANDLERS[path], write_body=write_body); return

    # ── 6 批量（batch）— shape 由表派生 ────────────────────────
    if path in _STOCK_BATCH_HANDLERS:
        self._handle_stock_batch(parsed, _STOCK_BATCH_HANDLERS[path],
                                 write_body=write_body, path=path); return

    # ── 其余 4 个 JSON 分支 ─────────────────────────────────────
    if path == '/cls/hotplate':
        self._send_json_shape(path, handle_cls_hotplate, write_body=write_body); return
    if path == '/cls/plate':
        code = parse_qs(parsed.query).get('code', [''])[0]
        if not code:                                              # 400 在 guard 之前
            self._send_error('Missing ?code= parameter. Usage: /cls/plate?code=cls80484',
                             write_body=write_body); return
        self._send_json_shape(path, lambda: handle_cls_plate(code),
                              write_body=write_body); return
    if path == '/ths/longhu':                                     # text：JSON 体、cache=False
        data = _guard(handle_ths_longhu, shape=_JSON_SHAPES[path])
        self._send_text(200, 'application/json; charset=utf-8',
                        json.dumps(data, ensure_ascii=False, indent=2),
                        cache=False, write_body=write_body); return
    if path == '/market/margin':
        market = parse_qs(parsed.query).get('market', ['99'])[0]
        if market not in VALID_MARKETS:                            # ★ v1.2：400 在 guard 之前
            self._send_error('Invalid ?market= parameter. Allowed: '
                             + ','.join(VALID_MARKETS), write_body=write_body); return
        self._send_json_shape(path, lambda: handle_margin(market),
                              write_body=write_body); return

    # ── 5 RSS（rss）─────────────────────────────────────────────
    if path in ROUTES:
        self._serve_feed(path, base_url, write_body=write_body); return

    self.send_error(404, 'Not Found. Visit / for available feeds.')          # BR-SRV-1
```

- `_STOCK_BATCH_HANDLERS` 与 `_JSON_SHAPES` 的 `batch` 六项**必须同集合**（`assert ...`，导入期）；`_JSON_DISPATCHED_PATHS == frozenset(_JSON_SHAPES)` 亦为导入期断言（新增表项必须有分支）。
- `_send_json(data, write_body=True, cache=True)`（★ v1.3：**无 `status` 形参**，恒 200）；`_send_json_shape` 是 7 个 object JSON 分支的唯一出口（shape 从表读；**恒 200 + 原样降级体，且 `cache=cache` ⇒ 降级体按域 TTL 可缓存**）；`/ths/longhu` 仍走 `_send_text`（text shape，`cache=False`）。

### 5.3 `_handle_stock_batch`（dropped 注入）

```python
def _handle_stock_batch(self, parsed, handler, write_body=True, path=None):
    params = parse_qs(parsed.query)
    if 'code' not in params:
        self._send_error('Missing ?code= parameter. Usage: /stock/...?code=sh600519 or ...?code=sh600519,sz000001',
                         write_body=write_body); return
    # ★ v1.2（P1-6）：入口折叠 —— stock_codes=canonical 去重码；requested=请求原拼写
    stock_codes, requested = _parse_stock_codes(params['code'][0])
    if not stock_codes:
        self._send_error('No valid stock codes provided.', write_body=write_body); return
    dropped = 0
    if len(stock_codes) > _MAX_BATCH_SIZE:                        # BR-SRV-14（按归一后码数）
        dropped = len(stock_codes) - _MAX_BATCH_SIZE
        log.warning(f'Batch truncated: {dropped} codes dropped, '
                    f'samples={stock_codes[_MAX_BATCH_SIZE:_MAX_BATCH_SIZE+3]}')
        stock_codes = stock_codes[:_MAX_BATCH_SIZE]
        requested = requested[:_MAX_BATCH_SIZE]                   # 保持对齐
    data = _guard(lambda: handler(stock_codes, dropped=dropped),  # BR-SRV-15：只传参，不重复组装
                  shape=_JSON_SHAPES.get(path, 'batch'),
                  requested=requested, dropped=dropped)
    data = _rekey_batch_response(data, stock_codes, requested)    # ★ v1.2：响应键回原拼写
    self._send_text(200, 'application/json; charset=utf-8',
                    json.dumps(data, ensure_ascii=False, indent=2),
                    cache=True, write_body=write_body)


def _parse_stock_codes(codes_str):
    """★ v1.2（P1-6）：(canonical 去重码, 请求原拼写)。无效码 ⇒ 以自身拼写为身份（逐码 null）。"""
    codes, requested, seen = [], [], set()
    for raw in codes_str.split(','):
        raw = raw.strip()
        if not raw:
            continue
        canon = config.canonical_code(raw)
        key = canon if canon is not None else raw
        if key in seen:                                           # 重复拼写不占第二个槽
            continue
        seen.add(key)
        codes.append(key)
        requested.append(raw)
    return codes, requested


def _rekey_batch_response(data, codes, requested):
    """★ v1.2（P1-6）：纯改名（键集不变）；无需改写时原样返回。"""
    if not isinstance(data, dict):
        return data
    rename = dict(zip(codes, requested))
    if not any(canon != raw for canon, raw in rename.items()):
        return data
    out = {}
    for key, value in data.items():
        if key == '_errors' and isinstance(value, dict):
            out[key] = {rename.get(c, c): kind for c, kind in value.items()}
        elif key.startswith('_'):
            out[key] = value
        else:
            out[rename.get(key, key)] = value
    return out
```

### 5.4 `_get_or_fetch_feed`（双检）+ `_serve_feed`（rss shape）+ 条件请求（★ v1.5；★ v1.9 / F1+F2+F5 修订）

```python
def _feed_cache_key(path, base_url):
    """BR-SRV-45（F2）：不透明缓存键，覆盖表示的全部变化维度。"""
    if PUBLIC_BASE_URL:
        return path                                  # 表示与 Host 无关（与 v1.8 逐字一致）
    return path + _FEED_KEY_SEP + base_url            # 与 Vary: Host, X-Forwarded-Host, X-Forwarded-Proto 同语义


def _get_or_fetch_feed(self, cache_key, fetch_func):
    """BR-SRV-6/7/38/48/50：防击穿（per-键 锁 + 引用计数收敛）+ 双检；LRU/TTL/清扫归 cache 层。
    ★ v1.9：返回 (xml, last_modified)；last_modified = 条目 entry['last_modified']（F1），
    不再用 entry['time']；miss 路径直接消费 feed_cache_put 的返回值（F5）。
    ★ v1.10 / F8：加锁走 feed_fetch_acquire/release（引用计数归零即回收，锁表有界）。"""
    entry = feed_cache_get_entry(cache_key)                        # ①（命中路径不读 policy —— P2-1）
    if entry is not None:
        return entry['xml'], entry['last_modified']                # ★ v1.9 / F1
    lock = feed_fetch_acquire(cache_key)                           # ② ★ v1.10 / F8：计数 +1 后返回锁
    try:
        with lock:                                                 # ③
            entry = feed_cache_get_entry(cache_key)                # ★ 双检
            if entry is not None:
                return entry['xml'], entry['last_modified']        # ★ v1.9 / F1
            ttl = cache_policy('feed')['ttl']                      # ★ P2-1：二次 miss 后才求值
            xml = fetch_func()                                     # 仅 miss 才回源；失败 ⇒ 异常穿透
            entry = feed_cache_put(cache_key, xml, ttl,            # ★ v1.9 / F5：直接用返回值
                                   fingerprint=_feed_fingerprint(xml))  # ★ v1.9 / F1（与 ETag 同源）
    finally:
        feed_fetch_release(cache_key)                              # ★ v1.10 / F8：异常路径也必须释放
    return xml, entry['last_modified']                             # entry 恒为 dict（非 None）


# ── ★ v1.5：ETag 规范化与条件判定（纯函数，不读时钟/不读缓存）─────────────
# ★ v1.6 / C1：canonical 投影扩展——三个"非内容"元素的『内容』一律空白化
_LASTBUILDDATE_RE = re.compile(r'<lastBuildDate>[^<]*</lastBuildDate>')   # count=1
_RSS_TTL_RE = re.compile(r'<ttl>[^<]*</ttl>')                            # count=1
_PUBDATE_RE = re.compile(r'<pubDate>[^<]*</pubDate>')                    # ★ v1.6：count=0（全量）


def _feed_fingerprint(xml):
    """BR-SRV-38（F1）：规范化摘要 sha256-hex —— 与 ETag 同源（同一 canonical 投影）。"""
    normalized = _LASTBUILDDATE_RE.sub('<lastBuildDate/>', xml, count=1)
    normalized = _RSS_TTL_RE.sub('<ttl/>', normalized, count=1)
    normalized = _PUBDATE_RE.sub('<pubDate/>', normalized)              # ★ v1.6：count=0 全量
    return hashlib.sha256(normalized.encode('utf-8')).hexdigest()


def _feed_etag(xml):
    """BR-SRV-37：弱 ETag W/"<fingerprint>"；剔除 lastBuildDate / ttl / **pubDate** 的『内容』后再哈希。

    裸 body 哈希是本专项第一风险：lastBuildDate 每次生成都取当前时间
    ⇒ TTL 到期重生成后内容未变 ETag 亦变 ⇒ 永远 200 ⇒ 功能静默失效。

    ★ v1.6 / C1：item 级 pubDate 必须**全量**（count=0）剔除——eastmoney `showtime`、
    ths `ctime`、jin10 `time` 解析失败时回落到当前时间（`formatdate(timeval=None)` /
    `int(time.time())`），落在哈希区 ⇒ 3/5 feed 每次 TTL 到期重生成都换 ETag ⇒ 永远 200。
    item 身份由 <guid> 承载，pubDate 为上游元数据（可接受的权衡，见 BR-SRV-37）。
    ★ v1.9 / F1：实现为 `_ETAG_PREFIX + '"' + _feed_fingerprint(xml) + '"'` ⇒ 与缓存
    `fingerprint` 必为同一摘要（`ETag 变 ⟺ Last-Modified 前进` 的基础）。
    """
    return _ETAG_PREFIX + '"' + _feed_fingerprint(xml) + '"'


def _if_none_match_matches(header, etag):
    """BR-SRV-39：If-None-Match（弱比较）。header 已确认非 None。"""
    current = etag[2:] if etag.startswith('W/') else etag        # 服务端 opaque tag（含引号）
    for raw in header.split(','):
        candidate = raw.strip()
        if not candidate:
            continue
        if candidate == '*':                                     # 任意当前表示
            return True
        if candidate.startswith('W/'):
            candidate = candidate[2:]                            # 弱比较：剥 W/ 后比 opaque tag
        if candidate == current:
            return True
    return False


def _if_modified_since_not_modified(header, last_modified):
    """BR-SRV-40：IMS 秒级比较；非法/None ⇒ False（忽略头，退回 200，绝不 400/500）。

    ★ v1.6 / C4（P2-01）：解析、补时区、`dt.timestamp()` **全部在同一 try 内**。
    `dt.timestamp()` 对超大年份/平台 time_t 越界可抛 OverflowError/OSError；若写在
    try 之外会穿透 do_GET/do_HEAD 的 except OSError ⇒ 连接中断（非 200）。
    """
    if last_modified is None:
        return False
    try:
        dt = parsedate_to_datetime(header)
        if dt is None:
            return False
        if dt.tzinfo is None:                                    # HTTP-date 无时区 ⇒ 视作 GMT
            dt = dt.replace(tzinfo=timezone.utc)
        return int(last_modified) <= int(dt.timestamp())         # ★ v1.6：timestamp 在 try 内
    except (TypeError, ValueError, OverflowError, OSError):      # ★ v1.6：+ OSError
        return False


def _not_modified(headers, etag, last_modified):
    """BR-SRV-39/40：条件判定唯一入口（RFC 9110 §13.1.3 优先级）。"""
    inm = headers.get('If-None-Match')
    if inm is not None:                                          # INM 存在 ⇒ IMS 被完全忽略
        return _if_none_match_matches(inm, etag)
    ims = headers.get('If-Modified-Since')
    if ims is not None:
        return _if_modified_since_not_modified(ims, last_modified)
    return False                                                 # 无条件头 ⇒ 200 全量


def _serve_feed(self, path, base_url, write_body=True):
    """BR-SRV-36..49：rss shape + 条件请求。GET/HEAD 同一路径（write_body 只控 200 体）。"""
    info = ROUTES[path]
    feed_url = base_url + path
    cache_key = _feed_cache_key(path, base_url)                  # ★ v1.9 / F2：键覆盖 Host 维度
    xml, last_modified = _guard(                                 # ★ v1.5：rss shape 返回 2-tuple
        lambda: self._get_or_fetch_feed(cache_key, lambda: info['handler'](feed_url=feed_url)),
        shape='rss', rss_info=info, feed_url=feed_url)            # 异常 → (generate_error_rss, None)
    etag = _feed_etag(xml)
    varies_on_host = not PUBLIC_BASE_URL                         # ★ v1.2（S2-3）不变；与 _feed_cache_key 同判定
    if _not_modified(self.headers, etag, last_modified):         # ★ v1.5：命中 ⇒ 304（零 body）
        self._send_not_modified(etag, last_modified,
                                varies_on_host=varies_on_host)
        return
    self._send_text(200, 'application/rss+xml; charset=utf-8', xml,
                    varies_on_host=varies_on_host, write_body=write_body,
                    etag=etag, last_modified=last_modified)       # ★ v1.5：200 带校验器
```

> **跨 TTL 仍 304 的机制（★ v1.9 / F1 核心）**：feed 条目在 `cache_policy('feed')['ttl']` 内命中 ⇒ 用缓存 xml 算 ETag，零上游；TTL 到期 ⇒ 回源重生成，此时 `_feed_fingerprint(xml)` 与**已过期**的上一条目指纹比较：**相同 ⇒ 继承 `last_modified`**（不前进）⇒ 客户端 `If-None-Match`/`If-Modified-Since` 仍命中 ⇒ **304**。这正是「表示最后一次变更的时刻」的语义（BR-SRV-38），也是 P1-1 的根治点：v1.8 用写入时刻会让 IMS-only 客户端每次跨 TTL 都拿 200。省的是 ~37KB body 而非上游请求（"缓存 TTL 管上游新鲜度、ETag 管客户端带宽"）。
>
> **降级路径与 304（★ v1.6 / C1 修正措辞；★ v1.9 / F1）**：`fetch_func` 抛异常 ⇒ `_guard` 返回 `(error_xml, None)`；`last_modified=None` 使 **IMS 不可评估**（永不因 IMS 得 304）。error feed 的 ETag 由 `error_xml` 规范化后派生——`pubDate` 现已被 canonical 投影剔除，故**同一错误表示**的重复请求会得到**相同 ETag**（客户端带该 ETag 时 ⇒ **304**，属"同一表示的条件命中"，语义正确）。**关键约束**：降级 feed 的 ETag **不得与成功 feed 的 ETag 混淆**（两者内容不同 ⇒ 哈希不同）；**不得**给降级体挂旧条目的 `last_modified`（否则会把陈旧时间冒充当前表示的 `Last-Modified`）。**`error_xml` 的生成仍逐字保留 `formatdate(None)`**（诊断用途，不影响 ETag）。
>
> **微冗余与 2-tuple 契约（★ v1.9 / F1）**：miss 路径 sha256 计算**两次**（`_feed_fingerprint(xml)` 取指纹入缓存 + `_feed_etag(xml)` 取 ETag 送响应）≈**0.15ms/次**，相对 30–180s TTL 与上游取数**可忽略**；`_get_or_fetch_feed` 的 **`(xml, last_modified)` 2-tuple 契约保持不变**（避免涟漪到 `_guard` 与既有测试）。

**`<ttl>` 生成（★ v1.5；`utils.py` 无独立详设，落点在此）**

```python
# server.py（handler 侧，6 处调用点 / 5 个 handler）：ttl 由 feed 缓存口径派生，单位为分钟
def _feed_ttl_minutes():
    ttl = cache_policy('feed')['ttl']            # 盘中 30 / 非盘中 180
    return max(1, (ttl + 59) // 60)              # 30→1，180→3（RSS 2.0 要求整数分钟）


def handle_cls_telegraph(feed_url=None):
    ...
    return generate_rss('财联社电报', 'https://www.cls.cn/telegraph',
                        '财联社实时快讯', parse_cls_items(data),
                        feed_url=feed_url, ttl=_feed_ttl_minutes())   # ★ v1.5

# utils.py（唯一生成点；ttl=None ⇒ 不输出该元素，既有调用点零改动）
def generate_rss(title, link, description, items, feed_url=None, ttl=None):
    xml = (f'<?xml version="1.0" encoding="UTF-8"?>\n'
           f'<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">\n'
           f'<channel>\n'
           f'<title>{escape_xml(title)}</title>\n'
           f'<link>{escape_xml(link)}</link>\n'
           f'<description>{escape_xml(description)}</description>\n'
           f'<lastBuildDate>{formatdate(timeval=None, localtime=False, usegmt=True)}</lastBuildDate>\n')
    # ★ v1.6 / C7#12（P2-07）：RSS 2.0 要求正整数；ttl<=0（如直调 ttl=0）⇒ 不输出
    if ttl is not None and int(ttl) > 0:                   # 位置 = lastBuildDate 之后、atom:link 之前
        xml += f'<ttl>{int(ttl)}</ttl>\n'
    if feed_url:
        xml += (f'<atom:link href="{escape_xml(feed_url)}" rel="self" '
                'type="application/rss+xml"/>\n')
    for item in items:
        ...                                                # 逐字保留
    return xml
```

> `generate_error_rss` **不传** `ttl` ⇒ 降级 feed 无 `<ttl>`（短生命周期、不承诺缓存间隔）。`<ttl>` 从生成到 ETag 规范化的关系见 `_feed_etag`（被剔除）。
>
> **eastmoney 的两个 `<ttl>` 出口（★ v1.8 / D-2）**：`handle_eastmoney_kuaixun` 有**两个** `generate_rss(...)` 站点——① 正则无匹配时的「空 feed」提前返回（`server.py:101-103`）；② 常规返回（`server.py:120-122`）。两处**均**传 `ttl=_feed_ttl_minutes()`，使该罕见路径与常规路径的 feed 表示一致（评审 SIDE-EFFECT #4 已确认该选择**正确**；`<ttl>` 本就被 canonical 投影剔除 ⇒ 不影响 ETag）。故本模块 `<ttl>` 调用点为 **6 处 / 5 个 handler**（v1.5 起的「5 处」口径已更正）。

### 5.5 外部上游扇出（`_fetch_concurrent`）+ plate stagger + longhu GBK

```python
_FANOUT_MAX_WORKERS = 3
_FANOUT_WAIT_BUDGET = REQUEST_TIMEOUT          # ★ v1.2：一轮扇出的排空上界
_fanout_executor = None
_fanout_lock = threading.Lock()


def _get_fanout_executor():
    """BR-SRV-30：hotplate/plate/longhu 共享的 ≤3 并发扇出执行器（懒创建，双检）。"""
    global _fanout_executor
    with _fanout_lock:
        if _fanout_executor is None:
            _fanout_executor = ThreadPoolExecutor(max_workers=_FANOUT_MAX_WORKERS,
                                                  thread_name_prefix='fanout')
        return _fanout_executor


def _fetch_concurrent(specs):
    """specs=[(key, fn)]；≤3 并发展开；返回 {key: 结果 或 Exception}（**不抛**）。顺序 = specs 顺序。"""
    if not specs:
        return {}
    if len(specs) == 1:                                    # 单元素：走当前线程（免池化开销）
        k, fn = specs[0]
        try:
            return {k: fn()}
        except Exception as exc:
            return {k: exc}
    ex = _get_fanout_executor()
    futs = {ex.submit(fn): k for k, fn in specs}
    done, _ = wait(futs, timeout=_FANOUT_WAIT_BUDGET)      # ★ v1.2：有界排空（P1-2）
    out = {}
    for fut, k in futs.items():                            # 固定顺序消费（确定性）
        if fut in done:
            try:
                out[k] = fut.result()
            except Exception as exc:
                out[k] = exc
            continue
        fut.cancel()                                       # 排队中 ⇒ 永不运行；已在跑 ⇒ 自身 10s 界
        out[k] = FetchError('upstream_timeout')
    return out


def _plate_ttls():
    """BR-SRV-10：从 policy 基值派生 stagger（D-7 明令保留三档）。"""
    base = cache_policy('plate')['ttl']
    return base, max(3, base // 4)


def handle_cls_hotplate(feed_url=None):
    """BR-SRV-30/31：3 分区 **≤3 并发**（SAD §4.1）；分区 error 客体 + 全失败补顶层 error。"""
    result = {}
    hot_plates = None
    base, stagger = _plate_ttls()
    offsets = {'industry': 0, 'concept': stagger, 'area': stagger * 2}   # 分区序 0/1/2
    specs = []
    for ptype in ('industry', 'concept', 'area'):
        params = {'app': 'CailianpressWeb', 'os': 'web', 'sv': '8.7.9',
                  'type': ptype, 'way': 'change', 'page': 1, 'rever': 1}
        params['sign'] = cls_sign_params(params)
        url = f'{_HOTPLATE_BASE_URL}?{urlencode(params)}'
        ttl = base + offsets[ptype]                        # ★ 默认参数捕获（闭包不可引用循环变量）
        specs.append((ptype, lambda url=url, ttl=ttl:
                      json.loads(fetch_json(url, _HOTPLATE_HEADERS, ttl=ttl))))
    fetched = _fetch_concurrent(specs)                     # ★ ≤3 并发：P95 = max 而非 sum
    errors = []
    for ptype in ('industry', 'concept', 'area'):          # ★ 固定消费顺序（确定性）
        raw = fetched.get(ptype)
        if isinstance(raw, Exception):
            result[f'plate_{ptype}'] = {'error': str(raw)}  # 分区 error 客体（分区可独立降级）
            errors.append(str(raw))
            continue
        data = raw.get('data') or raw
        result[f'plate_{ptype}'] = data
        if hot_plates is None:
            mfd = data.get('main_fund_diff') or {}
            top = mfd.get('top_main_fund_diff') or []
            last = mfd.get('last_main_fund_diff') or []
            if top or last:
                hot_plates = top + last
    if hot_plates:
        result['hot_plates'] = hot_plates
    if len(errors) == len(specs):                          # ★ BR-SRV-31：全分区失败 ⇒ 顶层补 error
        result['error'] = '; '.join(errors)                #   值 = 三块 error 摘要（SAD §2.3 D-4 唯一口径）
    return result


def handle_cls_plate(code):
    """BR-SRV-12/30：3 段 **≤3 并发**（SAD §4.1）；分区失败语义逐字保留。"""
    result = {'code': code}
    base, stagger = _plate_ttls()                          # info=0 / stocks=1 / industry=2

    def _signed_url(base_url, extra=None):                 # 逐字保留（现状签名逻辑）
        params = {'app': 'CailianpressWeb', 'os': 'web', 'sv': '8.7.9', 'secu_code': code}
        if extra:
            params.update(extra)
        params['sign'] = cls_sign_params(params)
        return f'{base_url}?{urlencode(params)}'

    specs = [
        ('info',     lambda: json.loads(fetch_json(_signed_url(_PLATE_INFO_URL),
                                                  _PLATE_HEADERS, ttl=base))),
        ('stocks',   lambda: json.loads(fetch_json(_signed_url(_PLATE_STOCKS_URL),
                                                  _PLATE_HEADERS, ttl=base + stagger))),
        ('industry', lambda: json.loads(fetch_json(_signed_url(_PLATE_INDUSTRY_URL),
                                                  _PLATE_HEADERS, ttl=base + stagger * 2))),
    ]
    fetched = _fetch_concurrent(specs)                     # ★ ≤3 并发

    raw = fetched.get('info')                              # 1) info：失败 ⇒ error 客体（逐字保留语义）
    if isinstance(raw, Exception):
        result['info'] = {'error': str(raw)}
    elif raw.get('code') == 200:
        result['info'] = raw.get('data', {})
    else:
        result['info'] = {'error': raw.get('msg', 'unknown')}

    raw = fetched.get('stocks')                            # 2) stocks：失败/非 200 ⇒ []（逐字保留）
    result['stocks'] = raw.get('data', {}).get('stocks', []) \
        if (not isinstance(raw, Exception) and raw.get('code') == 200) else []

    raw = fetched.get('industry')                          # 3) industry：失败/非 200 ⇒ []（逐字保留）
    result['industry'] = raw.get('data', []) \
        if (not isinstance(raw, Exception) and raw.get('code') == 200) else []
    return result


def handle_ths_longhu():
    """BR-SRV-9/30/32：走统一取数入口 + policy encoding + **2 URL 并发**（R15 / AC-E2）。"""
    policy = cache_policy('longhu')
    ttl = policy['ttl']                                    # L4 = 300
    encoding = policy.get('encoding', 'utf-8')             # ★ v1.2：encoding 取自 policy（=gbk）
    fetched = _fetch_concurrent([                          # ★ 2 URL 并发：≤ max 而非 sum（≈20s → ≈10s）
        ('table', lambda: fetch_json(_LHBTABLE_URL, _LHBTABLE_HEADERS, ttl=ttl, encoding=encoding)),
        ('page',  lambda: fetch_json(_LONGHU_PAGE_URL, _LONGHU_PAGE_HEADERS, ttl=ttl, encoding=encoding)),
    ])
    stock_html = fetched['table']
    if isinstance(stock_html, Exception):                  # 任一 URL 失败 ⇒ 抛给 _guard('text') 兜底
        raise stock_html
    rows = re.findall(r'<tr[^>]*>(.*?)</tr>', stock_html, re.DOTALL)
    ...                                                    # 解析逻辑逐字保留（cells/营业部）
    page_html = fetched['page']
    if isinstance(page_html, Exception):
        raise page_html
    broker_idx = 0
    for tbl in re.findall(r'<table[^>]*>(.*?)</table>', page_html, re.DOTALL):
        ...                                                # 标签匹配 + entries 解析逐字保留
        stock_idx = broker_idx // 2
        if stock_idx >= len(stocks):
            log.warning('[longhu] broker table #%d (%s) has no matching stock row (stocks=%d): entries dropped',
                        broker_idx, kind, len(stocks))     # ★ v1.2：不静默丢弃
        elif entries:
            stocks[stock_idx][kind] = entries
        broker_idx += 1                                    # ★ v1.2（P0）：无条件自增（即便 entries 为空）
    if broker_idx != 2 * len(stocks):
        log.warning('[longhu] %d broker tables matched but %d stocks expect %d — buy/sell pairing is misaligned',
                    broker_idx, len(stocks), 2 * len(stocks))
    return {'data': stocks, 'total': len(stocks)}
```

> **并发正确性**：`_fetch_concurrent` 提交后**阻塞等待全部 future**（每个 `fn` 自身的上界 = `fetch_json` 的 `REQUEST_TIMEOUT=10s`）⇒ 单端点耗时上界 = `10s + 解析` ≤ 15s（AC-E2）。共享执行器保证**全局**在这些端点上的在飞取数 ≤3（SAD §4.1），满足 AC-E8 的资源口径。

### 5.6 healthz（有界准入 + 预算 + 快照）

```python
_MAX_HEALTH_INFLIGHT = config.MAX_HEALTH_INFLIGHT                    # 5（config.md §2.3）


def _release_health_slot():
    """BR-SRV-19：释放一次准入位（仅由 _HealthBatch 调用；每个准入批次恰好一次）。"""
    _set_health_inflight(-1)
    _health_sem.release()


class _HealthBatch:
    """BR-SRV-19（修 P1-1）：一次 ?check=1 的在飞记账。

    准入位必须覆盖**该批任务的真实在飞**——轮询在 ~3s 即 break，未完成 future 仍会跑；
    若此时就 release，持续慢 check 会把提交量灌进专用执行器（max_workers=5、工作队列无界）
    ⇒ 重演 SAD P1-3 要消除的放大器。故 release 由「本批全部 future 结束」驱动。"""
    __slots__ = ('_remaining', '_lock', '_done')

    def __init__(self, n):
        self._remaining = n
        self._lock = threading.Lock()
        self._done = False

    def task_done(self, _fut=None):
        """future 完成回调；幂等 —— 归零时释放准入位一次。"""
        release = False
        with self._lock:
            self._remaining -= 1
            if self._remaining <= 0 and not self._done:
                self._done = True
                release = True
        if release:
            _release_health_slot()

    def settle(self):
        """★ v1.2（P1-5）：异常路径立即释放（不看 _remaining）；与 task_done 共享 _done ⇒ 绝不双放。"""
        release = False
        with self._lock:
            if not self._done:
                self._done = True
                release = True
        if release:
            _release_health_slot()


def _get_health_executor():
    global _health_executor
    with _health_executor_lock:                                      # 双检懒创建
        if _health_executor is None:
            _health_executor = ThreadPoolExecutor(
                max_workers=_MAX_HEALTH_INFLIGHT, thread_name_prefix='healthz')
        return _health_executor


def _check_one_feed(feed_path, base_url, info):
    """总函数：任何异常 → error 条目（绝不抛）。"""
    try:
        xml = info['handler'](feed_url=base_url + feed_path)
        return {'status': 'ok', 'items': count_rss_items(xml), 'error': None}
    except Exception as exc:
        return {'status': 'error', 'items': None, 'error': str(exc)}


def _run_health_checks(base_url, batch=None):
    """BR-SRV-20：5 源并发；**每源独立 3s**、整体 ≤10s；
    准入位由 `batch` 在**每个 future 真正结束**时销账（修 P1-1）。
    ★ v1.2（P1-5）：调用方可传入自建账本，异常时可 `settle()` 而非泄漏。
    捕获 `Exception`；`BaseException` 上抛由调用方 guard 处理。"""
    out = {}
    try:
        executor = _get_health_executor()
    except Exception as exc:                                         # 执行器创建失败 ⇒ 全 error + 归还准入位
        for path in ROUTES:
            out[path] = {'status': 'error', 'items': None, 'error': str(exc)}
        _release_health_slot()
        return out

    if batch is None:
        batch = _HealthBatch(len(ROUTES))                            # 直调兜底（先设账，再提交）
    started = time.monotonic()
    pending = {}                                                     # fut -> (path, submitted_at)
    for path, info in ROUTES.items():
        try:
            fut = executor.submit(_check_one_feed, path, base_url, info)
        except Exception as exc:                                     # 提交失败也销账，防准入位泄漏
            out[path] = {'status': 'error', 'items': None, 'error': str(exc)}
            batch.task_done()
            continue
        fut.add_done_callback(batch.task_done)                       # ★ P1-1：完成即销账
        pending[fut] = (path, time.monotonic())

    while pending:
        now = time.monotonic()
        for fut in [f for f, (_p, t) in pending.items()
                    if now - t >= _HEALTH_SOURCE_BUDGET]:            # ★ P2-2：每源独立 3s
            out[pending.pop(fut)[0]] = {'status': 'timeout', 'items': None, 'error': 'timeout'}
        if not pending:
            break
        elapsed = now - started
        if elapsed >= _HEALTH_TOTAL_BUDGET:                          # ★ 整体 10s 闸（多源排队时生效）
            break
        next_due = min(t for _p, t in pending.values()) + _HEALTH_SOURCE_BUDGET
        timeout = min(_HEALTH_POLL, max(0.0, next_due - now),
                      max(0.0, _HEALTH_TOTAL_BUDGET - elapsed))
        done, _ = wait(set(pending), timeout=timeout, return_when=FIRST_COMPLETED)
        for fut in done:
            path = pending.pop(fut)[0]
            try:
                out[path] = fut.result()                             # 总函数，正常不抛
            except Exception as exc:                                 # ★ v1.2（P1-5）：等待中途也不上抛
                out[path] = {'status': 'error', 'items': None, 'error': str(exc)}
    for fut, (path, _t) in pending.items():                          # 整体预算耗尽：余下判 timeout
        out[path] = {'status': 'timeout', 'items': None, 'error': 'timeout'}
    return out


def _remember_health_snapshot(payload):
    global _health_last_snapshot
    with _health_last_lock:                                           # 深拷贝（json round-trip，不用 copy 模块）
        _health_last_snapshot = json.loads(json.dumps(payload, ensure_ascii=False))


def build_health_payload(base_url, check_sources=False):
    feeds = _base_feed_entries(base_url)                              # 15 条（§2.9.1 修正后 status）
    status = 'ok'

    if check_sources:
        if not _health_sem.acquire(blocking=False):                   # BR-SRV-18：有界准入
            metrics.incr('healthz_stale_total')
            with _health_last_lock:
                snap = _health_last_snapshot
            if snap is None:                                          # 首个 check 即被拒：给可解析的降级体
                snap = {'status': 'degraded',
                        'cache_ttl': cache_policy('feed')['ttl'],
                        'request_timeout': REQUEST_TIMEOUT,
                        'feeds': feeds, 'metrics': metrics.snapshot(),
                        'policy': _policy_snapshot(),
                        'cdp': restart_window_snapshot()}
            return {**snap, 'stale': True}                            # 不触网、不刷新快照（BR-SRV-24）
        _set_health_inflight(+1)
        # ★ v1.2（P1-5）：账在风险调用之前建好 ⇒ 异常路径也能恰好销账一次
        batch = _HealthBatch(len(ROUTES))
        try:
            results = _run_health_checks(base_url, batch)              # 准入位由 _HealthBatch 释放（P1-1）
        except BaseException:
            batch.settle()
            raise
        for entry in feeds:
            res = results.get(entry['path'])
            if res is None:
                continue
            entry['status'] = res['status']
            if res['items'] is not None:
                entry['items'] = res['items']
            if res['error'] is not None:
                entry['error'] = res['error']
            if res['status'] != 'ok':
                status = 'degraded'

    payload = {'status': status,
               'cache_ttl': cache_policy('feed')['ttl'],              # BR-SRV-23：字段名不变，取值接 policy
               'request_timeout': REQUEST_TIMEOUT,
               'feeds': feeds,
               'metrics': metrics.snapshot(),
               'policy': _policy_snapshot(),
               'cdp': restart_window_snapshot()}
    _remember_health_snapshot(payload)                                # BR-SRV-24
    return payload


def _policy_snapshot():
    return {d: cache_policy(d) for d in sorted(DOMAIN_MATRIX)}
```

### 5.7 服务类 + 守护线程

```python
class BoundedThreadPoolServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True
    request_queue_size = LISTEN_BACKLOG               # ★ v1.2（BUG-P6C-03）

    def __init__(self, *args, max_workers=MAX_WORKERS, max_inflight=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self._inflight = 0
        self._inflight_lock = threading.Lock()
        self._max_inflight = MAX_INFLIGHT if max_inflight is None else max_inflight
        #                    ★ 默认 MAX_INFLIGHT(40)；流端口显式传 110（修 P1-4）

    def _reject_503(self, request):
        try:
            body = b'{"error":"server busy"}'
            request.sendall(b'HTTP/1.1 503 Service Unavailable\r\n'
                            b'Content-Type: application/json\r\n'
                            b'Content-Length: ' + str(len(body)).encode() + b'\r\n'
                            b'Connection: close\r\n\r\n' + body)
        except Exception:
            pass
        finally:
            try:
                metrics.incr('http_503_total')                          # BR-SRV-25（主端口准入拒绝的计数点）
            except Exception:
                pass
            try:
                request.close()
            except Exception:
                pass

    def process_request(self, request, client_address):                # 现状逻辑逐字保留
        with self._inflight_lock:
            if self._inflight >= self._max_inflight: overloaded = True
            else: self._inflight += 1; overloaded = False
        if overloaded:
            self._reject_503(request); return
        try:
            fut = self.executor.submit(self.process_request_thread, request, client_address)
        except Exception:
            with self._inflight_lock:
                self._inflight -= 1
            self._reject_503(request); return
        fut.add_done_callback(self._release_inflight)


def _cdp_memory_watchdog():
    """BR-SRV-26：决策集中在 cdp_engine（ADR-012 盘中避让 + 节流 + 重入）。"""
    while True:
        time.sleep(CDP_RESTART_INTERVAL)
        try:
            reason = watchdog_restart_skip_reason()
            if reason is not None:
                log.info('  [CDP] watchdog: restart skipped (%s)', reason)
                continue                                                # 顺延下一周期，不累积
            log.info('  [CDP] watchdog: restarting Chrome to reclaim renderer memory')
            full_chrome_restart()
        except Exception as e:
            log.error(f'  [CDP] watchdog error: {e}')
```

### 5.8 `_cache_age` / `_send_*`（TTL 接 policy）

```python
def _base_url(self):
    """★ v1.2（S2-3）：PUBLIC_BASE_URL 恒优先；否则校验 Host 格式（非法 ⇒ localhost:PORT）。"""
    if PUBLIC_BASE_URL:
        return PUBLIC_BASE_URL
    proto = _normalize_proto(self.headers.get('X-Forwarded-Proto'))
    raw = self.headers.get('X-Forwarded-Host') or self.headers.get('Host') or ''
    host = raw.split(',')[0].strip()
    if not _valid_host_header(host):
        host = f'localhost:{PORT}'
    return f'{proto}://{host}'.rstrip('/')

def _cache_age(self):
    """BR-SRV-8：path → domain → policy（禁止裸 TTL 字面量）。"""
    path = urlparse(self.path).path               # ★ v1.2：与路由同规则
    domain = _CACHE_AGE_DOMAINS.get(path, _DEFAULT_AGE_DOMAIN)
    return cache_policy(domain)['ttl']

def _accepts_gzip(header):                                               # ★ v1.4（RFC 9110 §12.5.3）
    """coding token 大小写不敏感；`;q=0` 表示拒绝；显式 `gzip` 覆盖 `*`。"""
    best = None
    for part in header.split(','):
        tokens = part.split(';')
        coding = tokens[0].strip().lower()
        if not coding:
            continue
        q = 1.0
        for param in tokens[1:]:
            key, _, val = param.partition('=')
            if key.strip().lower() == 'q':
                try:
                    q = float(val.strip())
                except ValueError:
                    q = 0.0
        if coding == 'gzip':
            best = q                      # 显式 coding 覆盖 '*'
        elif coding == '*' and best is None:
            best = q
    return best is not None and best > 0


def _send_text(self, status_code, content_type, body, cache=True,
               varies_on_host=False, write_body=True,
               etag=None, last_modified=None):                 # ★ v1.2 增 varies_on_host；★ v1.5 增 etag/last_modified
    body_bytes = body.encode('utf-8')
    gzipped = False
    # ★ v1.4：大响应且客户端接受 ⇒ gzip（level=1，CPU 优先；334KB JSON ≈10× 缩减）
    if (len(body_bytes) >= config.GZIP_MIN_BYTES
            and _accepts_gzip(self.headers.get('Accept-Encoding', ''))):
        body_bytes = gzip.compress(body_bytes, config.GZIP_COMPRESSLEVEL)
        gzipped = True
    self.send_response(status_code)
    self.send_header('Content-Type', content_type)
    self.send_header('Content-Length', str(len(body_bytes)))
    if etag is not None:                                        # ★ v1.5：校验器（仅 RSS 200 传）
        self.send_header('ETag', etag)
    if last_modified is not None:                               # ★ v1.5：有缓存条目才发
        self.send_header('Last-Modified',
                         formatdate(last_modified, localtime=False, usegmt=True))
    vary_parts = []
    if gzipped:
        self.send_header('Content-Encoding', 'gzip')
    if cache:
        scope = 'private' if varies_on_host else 'public'                # ★ v1.2：请求派生 Host ⇒ private
        self.send_header('Cache-Control', f'{scope}, max-age={self._cache_age()}')
        if varies_on_host:
            vary_parts.append(_BASE_URL_VARY)
    # ★ v1.4：表示随 Accept-Encoding 变 ⇒ gzipped 或可缓存时都必须 Vary
    if gzipped or cache:
        vary_parts.append('Accept-Encoding')
    if vary_parts:
        self.send_header('Vary', ', '.join(vary_parts))
    self.end_headers()
    if write_body:
        self.wfile.write(body_bytes)


def _send_not_modified(self, etag, last_modified, varies_on_host=False):   # ★ v1.5（BR-SRV-41）；★ v1.9 / F3+F6
    """304：**无 body / 无 Content-Encoding / 无 Content-Length / 无 Content-Type**。

    RFC 9110 §15.4.5：304 由头部结束即终止，不得含内容。**不得复用 `_send_text`**
    ——后者总会计算 gzip 并写 Content-Length/Content-Type，一个分支失误就会给
    304 带上体或 `Content-Encoding`。Cache-Control/Vary 必须与 200 同值，否则
    共享缓存会按 200 的语义缓存 304 的元数据。

    ★ v1.9 / F3：进入本方法即 `metrics.incr('http_304_total')`（单点 ⇒ 不可能漏记）。
    ★ v1.9 / F6：HTTP/1.0 无 `Content-Length`，由连接关闭（EOF）收尾；RFC 9110 §8.6
    禁止写 `Content-Length: 0`（若携带必须等于 200 体长）——故**不发**而非写 0。
    """
    self.send_response(304)
    metrics.incr('http_304_total')                              # ★ v1.9 / F3：单点计数
    self.send_header('ETag', etag)                              # 必发（与 200 同一弱标签）
    if last_modified is not None:                               # 与 200 一致：有则发
        self.send_header('Last-Modified',
                         formatdate(last_modified, localtime=False, usegmt=True))
    scope = 'private' if varies_on_host else 'public'            # 与 200 同值来源
    self.send_header('Cache-Control', f'{scope}, max-age={self._cache_age()}')
    vary_parts = []
    if varies_on_host:
        vary_parts.append(_BASE_URL_VARY)
    vary_parts.append('Accept-Encoding')                         # 200（cache=True）恒含 ⇒ 304 同
    self.send_header('Vary', ', '.join(vary_parts))
    self.end_headers()
    # 不写 wfile、不发 Content-*、不 gzip、不写 feed 缓存（BR-SRV-41）

def _send_json(self, data, write_body=True, cache=True):                 # ★ v1.3：无 status（恒 200）
    self._send_text(200, 'application/json; charset=utf-8',
                    json.dumps(data, ensure_ascii=False, indent=2),
                    cache=cache, write_body=write_body)

def _send_json_shape(self, path, fn, write_body=True, cache=True):       # ★ v1.2；v1.3 简化
    """shape 从 `_JSON_SHAPES[path]` 读 → `_guard` 兜底 → **恒 200** 发送。

    ★ v1.3（N1 裁决）：业务降级体（`{'error': …}` / `_error`）以 **200 + 结构化 error
    体** 返回，**状态码不由 payload 内容决定**（v1.2 的 `_json_payload_has_data` 与
    503 分支已删）。真实 503 仅：连接准入 `_reject_503`、流端口 `_serve_sse` 超限、
    `/healthz`（端点自身语义）。降级体沿 `cache=cache` ⇒ 按域 TTL 可缓存。
    """
    payload = _guard(fn, shape=_JSON_SHAPES[path])
    self._send_json(payload, write_body=write_body, cache=cache)

def _send_error(self, msg, write_body=True):                             # ★ 增 write_body（HEAD 不写体，见 §10#3）
    self._send_text(400, 'application/json; charset=utf-8',
                    json.dumps({'error': msg}, ensure_ascii=False, indent=2),
                    cache=False, write_body=write_body)
```

> ★ **v1.8 / P2-3（如实记录实现现状 · 评审 CR-RSS-20260918-001 P2-3）**：`Cache-Control`（`{private|public}, max-age={_cache_age()}`）与 `Vary` 的构造在 **`_send_text`（200 路径，见上）** 与 **`_send_not_modified`（304 路径，见上）** **各写一份**（约 4 行同源）——此即**实现现状**，**非设计变更**（**不抽公共函数、不改设计**）。BR-SRV-41 硬要求「304 与同请求 200 同值」，两份实现存在「未来单侧改动」的漂移面；§8 **`SRV-T62`** 是该漂移面的**兜底断言**：对**同一请求**先取 200、再带其 `ETag` 取 304，**逐头 diff** 两侧 `ETag`/`Last-Modified`/`Cache-Control`/`Vary` 必须**完全相同**（**不得**两侧各自硬编码期望值 ⇒ 防「两份头构造逻辑同时漂移」）。可选重构（抽 `_cache_headers(varies_on_host) -> (cc, vary)` 唯一来源供两处共用）由编排层决定，本版**不落**。

**RSS 条件请求响应头清单（★ v1.5，实测基线为锚）**

| 响应 | 头部 | 值 / 规则 |
|------|------|----------|
| **200**（5 RSS `GET`/`HEAD`） | `Content-Type` | `application/rss+xml; charset=utf-8`（不变） |
| | `Content-Length` | 实际发送字节数（HEAD 亦发，体不写——不变） |
| | `ETag` | **恒发**（★ v1.5）：`W/"<sha256-hex>"`，见 BR-SRV-37 |
| | `Last-Modified` | **有缓存条目时发**（★ v1.5）：`formatdate(entry['last_modified'], usegmt=True)`（★ v1.9 / F1：表示最后一次变更时刻，**非** 写入时刻）；降级体不发 |
| | `Cache-Control` | `{private\|public}, max-age={_cache_age()}`（★ v1.9 / F4：**`feed` 域**：盘 30 / 非盘 180；原 `news_url` 已改，**值不变**）；`private` ⟺ `PUBLIC_BASE_URL` 未设（不变）★ 实测当前为 `private, max-age=30` |
| | `Vary` | `PUBLIC_BASE_URL` 未设 ⇒ `Host, X-Forwarded-Host, X-Forwarded-Proto, Accept-Encoding`；设了 ⇒ `Accept-Encoding`（不变）★ 实测当前为四元组。★ v1.9 / F2：该 `Vary` 与 `_feed_cache_key` 的 `base_url` 维度**同语义**（头与行为一致） |
| | `Content-Encoding` | `gzip` 当且仅当 `len(body) >= GZIP_MIN_BYTES(1024)` 且 `_accepts_gzip`（不变） |
| **304**（条件命中） | `ETag` | **必发**（与 200 同一弱标签） |
| | *计量* | ★ v1.9 / F3：每次 304 计 `http_304_total`（`metrics.snapshot()` 可见；恒 ≥0） |
| | `Last-Modified` | 有值即发（与 200 一致） |
| | `Cache-Control` | **与 200 同值**（含 `private`/`public` 判定） |
| | `Vary` | **与 200 同值**（Host 三件套 + `Accept-Encoding`） |
| | `Content-Type` / `Content-Length` / `Content-Encoding` | **一律不发**；**无 body**（不 gzip、不写体、不写缓存） |

> **可断言（SRV-T49/T55）**：`PUBLIC_BASE_URL` 未设时，304 仍为 `Cache-Control: private, max-age=30` + `Vary: Host, X-Forwarded-Host, X-Forwarded-Proto, Accept-Encoding`——**不得因"无 body"而省略反投毒头**（否则共享缓存会把按 Host 变的 feed 串号）。

**`_cache_age` 行为变更登记**（值来源由 `_trading_tiers()[tier]` 改 `cache_policy(domain)['ttl']`）

| path | 现状 max-age | 目标 max-age（盘 / 非盘） | 说明 |
|------|-------------|------------------------|------|
| `/stock/data` `/stock/basic_info` `/stock/fundflow` `/stock/timeline` | L1（8 / 120） | 8 / 120（不变） | quote/fundflow/timeline |
| `/stock/f10` | L4（300） | 300 / 300（不变） | f10 域 |
| `/stock/announcement` | L4（300） | **30 / 180**（变更） | 纠正漂移：与 announcement 域 L3 对齐 |
| `/cls/hotplate` `/cls/plate` | L2（12 / 120） | 12 / 120（不变） | plate 基值（stagger 不进 `max-age`，现状亦然） |
| `/market/margin` | L4（300） | **600 / 600**（变更） | 与 margin 域 TTL 对齐 |
| `/ths/longhu` | L4（300） | 300（不变） | longhu 域 |
| 5 RSS | L3（30 / 180） | 30 / 180（不变） | ★ **v1.9 / F4：`feed` 域**（原 `news_url`；数值不变、只换 authority）；★ v1.5：同一 max-age 亦用于 304（与 200 同值），并新增 `ETag`/`Last-Modified` 校验器；★ v1.9 / F1：`Last-Modified` = 表示变更时刻 |
| **面板 4**（`/finance/market` `/finance/timeline` `/quotation/market` `/market/timeline`） | L4（300） | **8 / 120**（★ v1.2 变更） | 注册到 `quote` 域（实时行情面，**不再**落 300s 兜底） |
| `/healthz` / `/` / `/opml.xml` | L4（300） | 300（不变） | `_DEFAULT_AGE_DOMAIN='f10'`（L4 恒 300）；未登记路径现仅此三项 |
| 请求派生 Host（`PUBLIC_BASE_URL` 未设）的 feed/opml | `public` | **`private` + `Vary`**（★ v1.2） | S2-3 防共享缓存串号 |

### 5.9 `main()` 的改动点（4 处）

```python
    # ① 启动日志 TTL 来源（删 CACHE_TTL 后不得留断链）
    log.info(f'Cache TTL: {cache_policy("feed")["ttl"]}s | Timeout: {REQUEST_TIMEOUT}s')
    # ② 后台线程清单：warm_jin10 / ★ warm_transport（v1.4）/ init_cdp /
    #    _cdp_memory_watchdog / 4 prefetch / push_loop / run_stream_server
    threading.Thread(target=warm_transport, daemon=True).start()   # ★ v1.4：预热传输（DNS + 池化握手）
    # ③ 服务类构造不变：BoundedThreadPoolServer(('0.0.0.0', PORT), RSSHandler)
    # ④ warm_transport 是总函数 / daemon：上游宕机时静默，**绝不** gate 启动或 /healthz
```

`_serve_index` 的 `json_apis` 表仅改 3 个 `needs_cdp` 布尔（§2.9.1 表）。

---

## 6. 错误处理

### 6.1 错误语义矩阵（唯一口径）

| 情形 | 触发点 | HTTP | 响应体 | 计量 |
|------|--------|------|--------|------|
| 缺 `?code=`（6 批量） | `_handle_stock_batch` 步骤 1 | 400 | `{"error":"Missing ?code= parameter. …"}` | — |
| 码全为空串（6 批量） | 步骤 2 | 400 | `{"error":"No valid stock codes provided."}` | — |
| 缺 `?code=`（`/cls/plate`） | `_handle_request` | 400 | `{"error":"Missing ?code= parameter. …"}` | — |
| 非法码**值**（`/stock/*`） | `_parse_stock_codes` → handler | 200 | 该码逐码 `null`（★ v1.2：**非** 400） | — |
| `/market/margin` 非法 `market` | `_handle_request` | 400 | `{"error":"Invalid ?market= parameter. Allowed: 99,1,2,3"}` ★ v1.2 | — |
| 未知路径 | 兜底 | 404 | 文本 | — |
| 过载（inflight ≥ `MAX_INFLIGHT`） | `process_request` | 503 | `{"error":"server busy"}` | `http_503_total++`（**真实 503 ①**） |
| 流端口连接数 ≥ `MAX_STREAM_CONNS` | `stream._serve_sse` | 503 | `{"error":"too many stream connections"}` | `http_503_total++`（**真实 503 ②**，见 `stream.md`） |
| **业务端点降级体**（4 面板 / hotplate 全失败 / margin `_error` / guard 捕获体 / plate 分区降级） | `_guard` → `_send_json_shape` | **200** ★ v1.3（N1 回退） | payload 原样（含 `{'error':…}` / `_error` 客体）；`_send_json_shape` 以 `cache=True` 发送 ⇒ **按域 TTL 可缓存** | — |
| `/healthz` body 缺 `status` 或含 `error` | `_handle_request` | **503** ★ v1.2（**healthz 自身语义**） | payload 原样 | `http_503_total++`（**真实 503 ③**） |
| 上游失败（批量） | handler → `_errors` | 200 | 逐码 `null` ∧ `_errors[code] ∈ KINDS` | `upstream_fail_total{kind}`（stock_api/cache） |
| 上游失败（单体/面板/工具） | handler 返回 error 客体 | 200 | `{"error": …}` 或 `_error` 枚举（margin） | 同上 |
| 上游失败（`/cls/hotplate` **全分区**） | handler 三分区全 error | 200 | `{'plate_industry':{'error':…},'plate_concept':{'error':…},'plate_area':{'error':…}, 'error':'<三块摘要>'}`（**顶层补 `error`**，SAD §2.3 D-4 / BR-SRV-31） | 同上 |
| 上游失败（`/cls/hotplate` 部分分区） | handler 仅失败分区 | 200 | 失败分区为 `{'error':…}`，其余正常；**无顶层 `error`**、无 `hot_plates` | 同上 |
| 上游失败（RSS） | `rss` shape | 200 | `generate_error_rss`（合法 feed + 诊断 item） | 同上；★ v1.9 / F1：`last_modified=None` ⇒ 不发 `Last-Modified` |
| **RSS 条件请求命中（5 feed）** ★ v1.5 | `_send_not_modified` | **304** | 无 body / 无 `Content-Encoding`/`Content-Length`/`Content-Type`；带 `ETag`+`Cache-Control`+`Vary` | ★ v1.9 / F3：`http_304_total++`（**每次 304 单点计数**） |
| CDP 不可用（面板 4） | `page_data → None` | **200** ★ v1.3（N1 回退） | `{"error":"…"}` | — |
| CDP 不可用（`/stock/f10`） | `FetchError('cdp_unavailable')` | 200 | 逐码 `null` ∧ `_errors[code]='cdp_unavailable'` | `upstream_fail_total{cdp_unavailable}` |
| healthz 准入失败 | `_health_sem.acquire` | 200 或 503（依 `payload['status']`） | 上次快照 + `stale:true` | `healthz_stale_total++` |
| healthz 单源超时 | `_run_health_checks` | 200/503 | `feeds[].status='timeout'` + `error='timeout'`，`status='degraded'` | — |
| **任意 handler 抛异常** | `_guard` | 200 | 按 shape（§4.1 矩阵） | — |
| 客户端断开（写入期） | `do_GET`/`do_HEAD` 既有 except | — | 无（连接已关） | — |

### 6.2 降级路径（分层，互不混淆）

```
网络层（cache.fetch_json）  → 负缓存 + FetchError(kind)（cache.md 四段式）
   ↓
业务层（stock_api）         → (results, errors) + _fail_ledger 120s 冷却
   ↓
组装层（build_batch_response）→ 保留键（_errors/_truncated/_dropped_count）
   ↓
端点层（server）            → _guard(shape) 兜底 + JSON 序列化 + HTTP 状态
```

**关键不变式（可断言）**

1. **批量响应无顶层 `error`；单体响应无逐码值域**（跨类别即判失配，AC-A5）。
2. **任何 handler 异常都有结构化响应体**（`batch`→全码 null；`object`/`text`→`{'error'}`；`rss`→error feed）——`_guard` 是唯一收口（AC-S1）。
3. **过载即 503、不排队**：`_inflight` 只在 `process_request` 增减，`_release_inflight` 由 future 回调保证成对（AC-E8/S5）。
4. **healthz 准入位恰好释放一次**：`acquire` 成功 → 该批任务全部结束后由 `_HealthBatch` 释放（**不是** `finally` 立即释放，修 P1-1）；失败路径不 acquire、不 release。**在飞任务数 ≤ `MAX_HEALTH_INFLIGHT × len(ROUTES)` = 25，专用执行器工作队列 ≤ 20**（可断言上界；`BoundedSemaphore` 超放会抛 `ValueError` ⇒ 由类型再次兜底）。
5. **feed 双检不可省**：并发 N 请求在 miss 窗口只产生 1 次回源（可用回源计数白盒断言）。
6. **单请求上界（AC-E2 ≤15s）**：REST 批量 ≤15s（stock_api 预算）；`/cls/hotplate`、`/cls/plate` 的 3 段经 `_fetch_concurrent` **≤3 并发** ⇒ 耗时 ≤ `max(单次取数)` ≤ `REQUEST_TIMEOUT=10s`；`/ths/longhu` 的 2 URL **并发** ⇒ ≤10s（修 P1-2，`§10#10` 的 AC 归属已更正为 **E2**）；★ v1.2：整轮扇出受 **`_FANOUT_WAIT_BUDGET=REQUEST_TIMEOUT`** 界定（共享池被占时单请求也不会拖到 ~190s，超期项 `cancel()` + `FetchError('upstream_timeout')`）；面板 CDP ≤8s/次（cdp_engine）。
7. **压缩与缓存协商一致（v1.4）**：`Content-Encoding: gzip` 当且仅当 `len(body_bytes) >= config.GZIP_MIN_BYTES` 且 `_accepts_gzip(Accept-Encoding)` 为真；**`Vary: Accept-Encoding` 在 `gzipped or cache` 时必发**——可断言：`cache=True` 的任意响应、以及 `cache=False` 的 gzip 响应都含该头，`cache=False` 且未 gzip 的响应不含。`gzip;q=0` 的请求**不压缩**（`_accepts_gzip` 返回 False）。
8. **条件请求语义一致（★ v1.5；★ v1.6 / C1 双向化 + C4 措辞收敛；★ v1.9 / F1–F5 扩，可断言）**：① 304 当且仅当 **存在** `If-None-Match`/`If-Modified-Since` **且**条件命中；② 304 **无 body、无 `Content-Encoding`、无 `Content-Length`、无 `Content-Type`**，**必含 `ETag` + `Cache-Control` + `Vary`**（与同请求 200 同值；★ v1.9 / F6：HTTP/1.0 由 EOF 收尾，**不得**写 `Content-Length: 0`）；③ **ETag 由规范化后的内容决定（★ v1.6 / C1）**——`<lastBuildDate>`/`<ttl>`/`<pubDate>` 的**内容**被剔除（前二者 `count=1`、`pubDate` 全量）；同一 feed 内容（除这三项外）在 TTL 到期重生成后 ETag **逐字节相同**（R1 正向：**不误 200**），**除这三项外的任一字节变化则 ETag 必不同**（反向：**不误 304**；★ P3a-r2 / P2-b 限定语显式化）；④ `If-None-Match` **存在时 IMS 被完全忽略**（优先级）；⑤ 非法/不可解析日期头（含 `dt.timestamp()` 越界；异常面 = `TypeError`/`ValueError`/`OverflowError`/`OSError`）⇒ **200**（绝不 400/500）——**已覆盖 stdlib 已知异常面**（★ v1.6 / C4）；⑥ 304 **不触发 `feed_cache_put`**（回源计数不变，可用白盒断言）；⑦ 降级 feed（`fetch_func` 抛异常）⇒ `last_modified=None`（IMS **不可评估**）、其 ETag 与成功体**不混淆**（内容不同 ⇒ 哈希不同）；同一错误表示重放可得 304（属**同一表示**的条件命中，语义正确）；★ **v1.9 / F1**：⑧ `Last-Modified` = **表示最后一次变更的时刻**（`entry['last_modified']`），**在"同一键存在上一条目"的路径上 `ETag` 变 ⟺ `Last-Modified` 前进**（同源于 `fingerprint`）；指纹相同（即使条目已过期）⇒ 继承 ⇒ 跨 TTL 仍 304；无上一条目 ⇒ 本次写入时刻（**唯一例外**：ETag 可不变而时间前进，一次性 200 后可接受降级）；⑨ **★ v1.9 / F2**：feed 缓存键在 `PUBLIC_BASE_URL` 未设时含 `base_url`（`path + '\x00' + base_url`）⇒ 每个 Host 表示各自独立、无法跨 Host 串号；`PUBLIC_BASE_URL` 已设时键恒为 `path`（不随 Host 变）；⑩ **★ v1.9 / F3**：每次 304 使 `http_304_total` +1，每次 200 不增（`snapshot()` 在从未 304 时读到 0）；⑪ **★ v1.9 / F4**：`_feed_ttl_minutes() == ceil(feed 路径的 max-age / 60)`（两处同读 `feed` 域）；⑫ **★ v1.9 / F5**：miss 路径只调用一次 `feed_cache_get_entry`（双检）+ 一次 `feed_cache_put`（消费其返回），**不再有 put 后的第二次查询**；200 在真实条目存在时**必带 `Last-Modified`**（窗口已消除）；⑬ **★ v1.10 / F8**：feed 取数锁表**有界**——`_get_or_fetch_feed` 用 `feed_fetch_acquire`/`try…finally feed_fetch_release` 包裹；**计数 ≥1 时该键不可能被 `pop`**（不双抓），**归零即回收** ⇒ `len(_feed_fetch_locks)` 收敛于**并发在飞的键数**、不随累计 Host 数增长（`SRV-T71`/`T72`/`T73`）。

### 6.3 异常兜底范围声明

| 端点 | 是否受 `_guard` 保护 | 说明 |
|------|--------------------|------|
| 14 个 JSON 分支 | ✅ | `batch`/`object`/`text` 三 shape |
| 5 个 RSS | ✅ | `rss` shape |
| `/healthz` | ✅（额外加固） | `object` shape（SAD 未强制，但 healthz 自身必须总函数） |
| `/`、`/opml.xml` | ❌（**不纳入**） | 纯内存字符串拼接（无 IO、无外部数据），AC-S1 的注入故障（上游超时/非法响应/CDP 无数据）不可达；登记见 §10#4 |

---

## 7. 并发安全

### 7.1 锁清单

| 锁 | 保护对象 | 新增/既有 | 临界区内容 |
|----|---------|----------|-----------|
| `_inflight_lock` | `BoundedThreadPoolServer._inflight` | 既有 | 整数读改写（无 IO） |
| `_feed_fetch_locks_lock`（cache.py） | `_feed_fetch_locks` + `_feed_fetch_refs`（锁表 + 引用计数） | 既有（★ v1.10 / F8：仅经 `feed_fetch_acquire/release` 读写） | dict setdefault + 计数读写（无 IO）；`release` 归零**两表同删** |
| `_feed_fetch_locks[cache_key]`（per-键） | 同一 feed 键的回源串行 | 既有（★ v1.10 / F8：`feed_fetch_acquire` 取、`feed_fetch_release` 归还） | **仅** `feed_cache_get_entry`（内部自锁）+ `fetch_func()` + `feed_cache_put`；网络 IO **在锁内**（这是防击穿的必要代价，per-键 粒度 ⇒ 不同 feed 键互不阻塞） |
| `_health_executor_lock` | 执行器懒创建 | **新增** | 双检创建（无 IO） |
| `_health_inflight_lock` | `_health_inflight` | **新增** | 整数读改写 + `metrics.set_gauge`（metrics 为叶子锁，见 §7.3） |
| `_health_last_lock` | `_health_last_snapshot` | **新增** | json 深拷贝（内存） |
| `_health_sem`（`BoundedSemaphore`） | healthz 在飞窗位 | **新增** | 非阻塞 acquire；release 仅经 `_release_health_slot()`（由 `_HealthBatch` 归零触发） |
| `_HealthBatch._lock` | 该批 `_remaining`/`_done` | **新增** | 纯整数/布尔读改写（无 IO、不嵌套） |
| `_fanout_lock` | `_fanout_executor` 懒创建 | **新增** | 双检创建（无 IO）；**不跨模块调用** |
| `metrics._lock` | 计数/仪表 | 既有（叶子） | 见 `metrics.md` §7 |
| `cache._cache_lock` / `_neg_lock` / `_feed_cache_lock` | 缓存内部 | 既有 | 见 `cache.md` §7.1 |

### 7.2 锁序纪律（硬约束）

1. **`_feed_fetch_locks_lock` → per-键 lock**：`feed_fetch_acquire` 内建表/计数后**立即释放**才返回锁，调用方再 `with lock:`；**禁止**持有 per-键 锁时再取 `_feed_fetch_locks_lock`（server 不再直接取该锁）。★ **v1.10 / F8**：`feed_fetch_release` **必须在 `finally`**（异常路径也释放 ⇒ 计数不泄漏）。
2. **per-键 锁内不持有任何 cache 内部锁**：`feed_cache_get_entry`/`feed_cache_put` 各自在 `_feed_cache_lock` 内完成并**在返回前释放**（`cache.md` §7.2#4）。★ v1.5：条件请求**不引入新锁**——ETag/条件判定为纯函数（`re`+`hashlib`+`email.utils`），`_not_modified` 只读 `self.headers`；`feed_cache_get_entry` 复用既有 `_feed_cache_lock`。★ v1.10 / F8：`feed_fetch_acquire/release` 的 `_feed_fetch_locks_lock` 临界区同样只做 dict 读写，与 `_feed_cache_lock` 不嵌套。
3. **`_coordinator → 无`**：`_health_executor_lock` / `_health_last_lock` / `_health_inflight_lock` / `_fanout_lock` / `_HealthBatch._lock` 各锁**互不嵌套**，且**不在**持有时调用任何其它模块（`metrics` 例外：`metrics._lock` 是全局最内层，允许被持有 → 见 §7.3）。
   - `_HealthBatch.task_done` 的 `_release_health_slot()` 在**释放 `_HealthBatch._lock` 之后**调用（`with` 块外），⇒ 不出现 `_HealthBatch._lock → _health_inflight_lock` 嵌套。
4. **healthz 专用执行器与主池物理隔离**：healthz 的 5 个 worker **绝不**执行任何业务 handler（只执行 `_check_one_feed`），且其 RSS handler 走 `fetch_json`（自带 `_cache_lock`/`_neg_lock`，网络 IO 不持锁）。
5. **扇出执行器（`fanout`，≤3）与主池/healthz 池三方物理隔离**：`_fetch_concurrent` 只提交"单次 `fetch_json`"闭包，**不**在其中再做嵌套扇出（禁止 hotplate→plate 的递归并发）。
6. **不引入全局大锁**（项目约定）。
7. **`_guard` 无锁**：捕获异常与降级体构造均为纯内存操作（`build_batch_response` 为纯函数）。

### 7.3 metrics 锁的嵌套方向（唯一允许的跨界锁）

```
允许：_inflight_lock → metrics._lock            （_reject_503 在 finally 内计数）
允许：_health_inflight_lock → metrics._lock      （_set_health_inflight 计数）
允许：_feed_cache_lock → metrics._lock           （cache._cache_put 发布，cache.md §7.3）
禁止：metrics._lock → 任何其它锁（metrics 为叶子，metrics.md §7.2）
```

> `_set_health_inflight` 的 `metrics.set_gauge` **在释放 `_health_inflight_lock` 之后**调用亦无不可；伪代码为简化在锁内调用——两处均在 `metrics.md` 允许的"叶子锁永远最内层"范围内。**唯一硬约束：不得反向**。

### 7.4 热点路径开销（AC-E1/E4 相关）

- **本地缓存命中**：只多一次 `_cache_age()` 的 `cache_policy(domain)`（dict 查表，纳秒级）+ 一次 `cache_policy('feed')` 的**不调用**（feed 命中路径不读 policy：`_get_or_fetch_feed` 仅在 miss 后读 ttl——**实现要求（P2-1）**：`ttl = cache_policy('feed')['ttl']` 必须在**二次 `feed_cache_get_entry` 仍 miss 之后**求值（§5.4 位置），避免命中路径白算 policy）。★ v1.10 / F8：`feed_fetch_acquire/release` 命中路径**完全不触及**（仅 miss 路径各一次，临界区为 dict 读写）。
- 批量端点：命中路径零 metrics、零网络；`_guard` 在成功路径只有一次 `try` 建立的成本（CPython 无异常时 near-zero）。
- healthz `check=0`：`metrics.snapshot()` 深拷贝 O(19) + `_policy_snapshot()` O(11) + `_base_feed_entries` O(15) ⇒ 毫秒级。

### 7.5 并发正确性依据（可白盒断言）

1. `_inflight` 与 `_release_inflight` 成对：`fut.add_done_callback` 在 future 结束（含异常）时回调 ⇒ 无泄漏（AC-E8/S5）。
2. `_health_sem` 为 `BoundedSemaphore`：多 release 会抛 `ValueError`；`_HealthBatch._done` 保证每个准入批次**恰好 release 一次**（测试可断言"无超放/无漏放"）。
3. healthz 并发 10 请求且上游慢：前 5 个进入检查、后 5 个走 stale（`stale:true` + `healthz_stale_total==5`）——AC-S8 的可测路径。**修 P1-1 追加**：前 5 批的任务未排空前 `_health_sem._value == 0`（准入位不归还），`_health_executor._work_queue.qsize() ≤ 20` 且**不随持续请求单调增长**；任务结束后准入位回升。
4. `_fetch_concurrent` 的 N 段并发 ⇒ 单端点耗时 ≈ `max(单段)` 而非 `sum`：注入 3 段各 `sleep(1s)` 断言总耗时 < 2s（而非 ≈3s），验证 AC-E2（BR-SRV-30）。
5. feed 并发 N：回源调用计数 == 1（双检 + per-键 锁）；★ v1.10 / F8：并发/异常后 `_feed_fetch_refs` 归零、键被回收（`SRV-T72`），锁表规模不随累计 Host 数增长（`SRV-T71`）；★ v1.12：**并发在飞 K 键**时锁表/计数表规模 `<= K` 且两表同步、返回后均归零（`SRV-T73`）。
6. `_cache_age()` 纯函数（`cache_policy` 纯函数）⇒ 任意线程可调。

---

## 8. 测试要点（映射 PRD AC）

| 用例 | 步骤 / 断言（精确） | 覆盖 AC |
|------|-------------------|---------|
| **SRV-T1** `_JSON_SHAPES` 完整且 =14 | `assert len(_JSON_SHAPES) == 14`；`{p for p,s in _JSON_SHAPES.items() if s=='batch'} == set(_STOCK_BATCH_HANDLERS)`；`_SHAPES == {'batch','object','rss','text'}` | S1（防漏数复发） |
| **SRV-T2** guard 全覆盖矩阵 | 对 14 分支 + 5 RSS 逐个 patch handler 抛 `RuntimeError('boom')` ⇒ 断言：batch 分支返回 `{<每个请求码>: None, '_errors': {code:'upstream_error'}, …}`（含 `_truncated/_dropped_count` 若 dropped>0）；object/text 分支 `{'error':'boom'}`；RSS 分支为合法 XML（`ET.fromstring` 可解析）且含诊断 item；**进程存活、无异常冒泡** | **S1 / A5 / S4** |
| **SRV-T3** guard 不吞 KeyboardInterrupt | patch handler 抛 `KeyboardInterrupt` ⇒ 异常**穿透**（`assertRaises`） | S1（边界口径） |
| **SRV-T4** 批量保留键（dropped 注入） | 70 码请求（patch handler 记录 `dropped` 实参）⇒ handler 收到 `codes` 长度 50、`dropped==20`；响应含 `_truncated is True` ∧ `_dropped_count == 20`；**50 码时两键均不存在** | **A9** |
| **SRV-T5** 批量 handler 不被重复组装 | patch `build_batch_response`（计数）⇒ 仅由 handler 调用（server 直调计数 == 0）；`_guard` 仅在**异常**时调用 1 次 | A9 / 职责边界 |
| **SRV-T6** 缺参 400 | `/stock/data`（无 code）、`/stock/data?code=`、`/cls/plate`（无 code）⇒ 400 + `{'error':…}`；**不含逐码值域** | **A5** |
| **SRV-T7** 未知路径 404 | `/stock/xxx`、`/nope` ⇒ 404 文本 | **A5** |
| **SRV-T8** 过载 503 + 恢复 | 上游阻塞桩 + 注入 200 并发 ⇒ inflight ≤ `MAX_INFLIGHT`；超限响应 503 `{"error":"server busy"}`；`snapshot()['http_503_total'] == 503 次数`；撤载 5s 内全部 200；`_inflight` 回到 0 | **E8 / S5 / S10** |
| **SRV-T9** `MAX_INFLIGHT` 显式 | `config.MAX_INFLIGHT == config.MAX_WORKERS*2`（无 env 时）；patch `MAX_WORKERS` env 重启后联动；`server._max_inflight` 读该值（非 `max_workers*2`） | E8 |
| **SRV-T10** feed 双检（防击穿） | 冷路径 + N=8 并发同 path：patch `fetch_func` 计数 ⇒ **1 次**；`feed_cache_put` 1 次；8 个返回值相同 | **A8** / R3 |
| **SRV-T11** feed TTL 接 policy（★ v1.9 / F4 修订） | patch `cache_policy('feed')` 返回 `ttl=30` ⇒ `feed_cache_put` 收到 `ttl==30`；`healthz['cache_ttl']==30`；`_cache_age()` 对 RSS 路径 == `cache_policy('feed')['ttl']`（★ v1.9：原断言 `news_url` 域已作废） | **A8 / A3** |
| **SRV-T12** feed 回源失败不写缓存 | `fetch_func` 抛异常 ⇒ `_serve_feed` 返回 error RSS（200）、`feed_cache_get(path)` 仍 `None`；下次请求再次回源 | S1 / A8 |
| **SRV-T13** plate stagger 三档 + 并发 | 盘中（注入 `_is_trading_hours→True`）patch `fetch_json` 捕获 ttl ⇒ hotplate `[12,15,18]`；plate `[12,15,18]`（info/stocks/industry）；非盘中 `[120,150,180]`；`_STAGGER == max(3, base//4)`；**三档互不相等**；且 hotplate/plate 各只调 `_fetch_concurrent` **1 次**、`len(specs)==3`（≤3 并发） | **A3 / E6 / E2** / D-7 |
| **SRV-T14** plate 分区 error 客体 + 顶层 error | 单分区失败 ⇒ 仅该 `plate_<type>` 为 `{'error':…}`，其余正常、**无顶层 `error`**；三分区**全**失败 ⇒ 三块均为 error 客体 **且顶层含 `error`**（值 = 三块摘要，SAD §2.3 D-4 / BR-SRV-31） | **A5** / S4 |
| **SRV-T15** longhu GBK + 走统一入口 | patch `fetch_json` 捕获 `(url, ttl, encoding)` ⇒ 2 个 URL、`ttl==cache_policy('longhu')['ttl']==300`、`encoding=='gbk'`；连续 10 次请求回源 2 次（每 URL 1 次）；**全仓无 `urlopen` in `handle_ths_longhu`** | **E9 / R15** |
| **SRV-T16** `_cache_age` policy 映射 | 逐 path 断言 max-age == `cache_policy(domain)['ttl']`；`/stock/announcement` == L3（30/180）、`/market/margin` == 600、面板 == 300（`_DEFAULT_AGE_DOMAIN`） | A3 / E6 |
| **SRV-T17** 无裸 TTL 字面量 | 扫 `server.py`：`ttl=` 实参来源均为 `cache_policy(...)`；无 `300`/`600`/`120`/`8` 作为 TTL | R16 / CFG-T10 |
| **SRV-T18** healthz `check=0` 零上游 | patch 5 个 RSS handler + `urlopen` 计数 ⇒ 均 0 调用；payload 含 4 既有键 + `metrics`/`policy`/`cdp`；`stale` 键不存在；毫秒级 | **S8 / S10** |
| **SRV-T19** healthz 精确 schema | 断言键集合 == `{status,cache_ttl,request_timeout,feeds,metrics,policy,cdp}`（无 stale）；`feeds[]` 每条含 `name/path/url/status`；`policy` 键集合 == `set(DOMAIN_MATRIX)`；`cdp` 键 == `{state,window_start,window_end}` | S10 / P2-N1 |
| **SRV-T20** healthz 有界准入（stale 可达） | 5 个并发慢 check（每源 sleep 2s，patch handler）占满信号量 ⇒ 第 6 个请求立即返回（<50ms）含 `stale is True`；`snapshot()['healthz_stale_total'] ≥ 1`；`healthz_inflight ≤ 5`；**且在首批任务的 future 未全部完成前 `_health_sem._value == 0`（准入位不归还，修 P1-1）**；前 5 批完成后信号量归位（后续请求不再 stale） | **S8 / S10**（P1-1 可测性） |
| **SRV-T21** healthz 两级预算（单源独立 + 整体闸） | ①**单源独立 3s**：单源慢 5s、其余快 ⇒ 慢源 `status=='timeout'`、请求总耗时 ≤ ~3.2s；②**整体 10s 闸非死代码**：patch `_HEALTH_TOTAL_BUDGET=1.0` 且 5 源全慢 5s ⇒ 请求总耗时 ≤ ~1.1s（**不是** 3.2s），全部源 `timeout`（修 P2-2） | **S8 / S7** |
| **SRV-T22** healthz 不污染业务池 + 队列有界 | 10 并发 `?check=1`（上游慢 5s）+ 同时业务请求 ⇒ 业务 P95 劣化 ≤50%；`server.executor` 无 healthz 任务；**`_health_executor._work_queue.qsize() ≤ 20`**（= 5 批 × 5 源 − 5 worker） | **S8** |
| **SRV-T23** healthz 准入失败不刷快照 | 先成功一次（快照 A）→ 再并发占满 → stale 返回 A；期间 `_health_last_snapshot` 仍为 A（未被 stale 体覆盖） | S8 / §10#5 |
| **SRV-T24** healthz 总函数 | patch `build_health_payload` 抛异常 ⇒ `/healthz` 返回 **503** `{'error':…}`（★ v1.3 更正：v1.2 起不再假 200；非 500/断连），且**不写回快照**；与 `SRV-T37` 同源 | S1 |
| **SRV-T25** feeds[].status 修正 | `_base_feed_entries`：`/stock/data`→`configured`、`/stock/basic_info`→`configured`、`/stock/f10`→`requires_chrome_cdp`；`/finance/market` 保持 `requires_chrome_cdp`；`/market/margin` `configured`；条目数 == 15 | S4（标注修正）/ Q2 |
| **SRV-T26** 首页 CDP 列 | `_serve_index` HTML 中 `/stock/data` 与 `/stock/basic_info` 行不含 `CDP` 标签；`/stock/f10` 行含 `CDP` 标签 | S4 / Q2 |
| **SRV-T27** watchdog 委派 | patch `watchdog_restart_skip_reason` 返回 `'trading_hours'` ⇒ `full_chrome_restart` **未被调用**且日志含原因；返回 `None` ⇒ 调用 1 次；`full_chrome_restart` 抛异常 ⇒ 线程存活（`except` 兜底） | **S4 / S9 / R19** |
| **SRV-T28** 面板 A 类降级 + timeline 旁支 | `page_data→None` ⇒ `{'error':…}`（4 端点）；`page_data→{'basic_info':{...}}`（无 timeline）⇒ `/finance/timeline`、`/market/timeline` 返回 `{'error':'timeline unavailable'}`（**非** `None`，**非**裸 `null`） | **S4 / S1 / R18** |
| **SRV-T29** f10 A′ 形状 | `config.cdp_engine = None` ⇒ `/stock/f10?code=sh600519` 返回 `{'sh600519': None, '_errors': {'sh600519':'cdp_unavailable'}}`（**非** error 客体） | **S4 A′** |
| **SRV-T30** RSS 不丢不重 | 上游 50 条 ⇒ feed 含 50 item、guid 无重复；间隔 2×TTL 后再次请求仍含全部条目（TTL 用 `cache_policy('feed')['ttl']`） | **A8** |
| **SRV-T31** 存量用例回归 | `test_server.py`：`test_handle_cls_hotplate_returns_three_plate_keys` / `..._includes_hot_plates` / `test_handle_cls_plate_returns_info_stocks_industry` / `test_healthz_payload_includes_hotplate_endpoint` / `test_healthz_includes_market_endpoints` / `test_transform_margin_*` / `test_handle_margin_error_returns_degraded` / `test_generate_opml_*` 全绿 | PRD §9（存量基线） |
| **SRV-T32** import 断链检查 | 全仓 grep `CACHE_TTL` / `MAX_FEED_CACHE_SIZE` / `feed_cache`（在 server.py 内）/ `CACHE_JITTER`（server.py）⇒ **0 命中**；`python -m py_compile china_finance_rss/server.py` 通过 | config.md §2.4 同 change-set |
| **SRV-T33** HEAD 不写体 | `do_HEAD` `/stock/data?code=…` 400 路径 ⇒ 响应无 body（`Content-Length: 0` 或空）；`_send_error(write_body=False)` 被调用 | S1 |
| **SRV-T34** healthz 准入位覆盖在飞任务（执行器队列有界） | patch `_check_one_feed` 为 `sleep(5s)`；**持续 20s 高频**发起 `?check=1`（每 0.1s 一次）⇒ ①任一时刻 `healthz_inflight ≤ MAX_HEALTH_INFLIGHT`；②`_health_executor._work_queue.qsize() ≤ MAX_HEALTH_INFLIGHT × len(ROUTES) − MAX_HEALTH_INFLIGHT == 20` 且**不单调增长**（对比 v1.0 会让队列无界累积）；③每个准入批次**恰好** `release` 一次（`_health_sem._value` 最终回到 `MAX_HEALTH_INFLIGHT`，无 `ValueError`、无泄漏） | **S8 / S7**（修 P1-1 的核心断言） |
| **SRV-T35** AC-E2 单请求上界（并发扇出） | ①hotplate：patch 3 个分区 `fetch_json` 各 `sleep(1s)` ⇒ `/cls/hotplate` 总耗时 < 2s（≈`max`，非 ≈3s）；②plate 同断言；③longhu：patch 2 个 URL 各 `sleep(1s)` ⇒ 总耗时 < 2s（≈`max`，非 ≈2s+）；④`_fetch_concurrent` 返回项中 `Exception` 不抛出（转成 `{'error':…}` / 分区 error 客体）；★ v1.2：⑤patch `_FANOUT_WAIT_BUDGET=0.2` 且各段 `sleep(1s)` ⇒ 总耗时 < 0.5s 且每项为 `FetchError('upstream_timeout')` | **E2**（主，修 P1-2） |
| **SRV-T36** 业务端点降级恒 200（★ v1.3 / N1 反转） | patch `handle_finance_market` 返回 `{'error':'x'}` ⇒ `/finance/market` **200**（体原样 `{'error':'x'}`）且 `http_503_total` **不增**；`{'plate_industry':{'error':'x'},'error':'x'}`（hotplate 全失败）⇒ 200；`handle_margin` 返回 `{'_error': …}` ⇒ 200；guard 抛异常（object/text 分支）⇒ 200 `{'error': str(exc)}`；**并断言响应含 `Cache-Control: public, max-age=<域 TTL>`（降级体可缓存）** | **A5 / N1**（回退 S2-5） |
| **SRV-T37** healthz guard 失败 ⇒ 503（v1.2） | patch `build_health_payload` 抛异常 ⇒ `/healthz` **503**（体 `{'error':…}`），`http_503_total++`；`status=='degraded'` ⇒ 503；`status=='ok'` ⇒ 200 | **S1 / S8** |
| **SRV-T38** `/market/margin` 参数门（v1.2） | `?market=abc` ⇒ **400** `Invalid ?market= parameter. Allowed: 99,1,2,3`，且 patch `handle_margin` **未被调用**、无缓存键；`?market=99`/缺省 ⇒ 200 | **A5** |
| **SRV-T39** 批量码归一 + 键回写（v1.2） | `?code=600519.SH,SH600519,sh600519` ⇒ handler 收到 `['sh600519']`（**1** 个码，`dropped==0`）；响应键 == `'600519.SH'`（首个原拼写）；`?code=sh600519,sz000001` ⇒ 响应键 == 原拼写且体与旧实现**逐字节一致** | **A9 / A6 / P1-6** |
| **SRV-T40** 非法码值 ⇒ 逐码 null（v1.2） | `?code=sh600519,NOTACODE` ⇒ **200**；`NOTACODE` 键为 `null`（或 `_errors` 命中）；**非** 400；`?code=`/无 `code` ⇒ 400 | **A5** |
| **SRV-T41** longhu 席位配对（v1.2） | 构造 N 个股票行 + 其中一张表解析出 0 条 entries ⇒ 断言 `broker_idx` 仍按 2×股票数推进、后续股票席位**不偏移**；`broker_idx != 2×len(stocks)` ⇒ `log.warning` 命中 | P0 回归 |
| **SRV-T42** `_base_url` 加固（v1.2） | 无 `PUBLIC_BASE_URL` 时：`Host: evil/@x` ⇒ 返回 `http://localhost:8053`；合法 `Host: example.com` ⇒ `http://example.com`；`X-Forwarded-Host` 优先；响应含 `Cache-Control: private` + `Vary: Host, …` | S2-3 |
| **SRV-T43** `_cache_age` 面板域（v1.2） | 4 面板路径的 `max-age == cache_policy('quote')['ttl']`（8/120），**非** 300；`_cache_age` 用 `urlparse`：absolute-form 请求行解析出正确 path | S2-3 / A3 |
| **SRV-T44** gzip 协商（v1.4） | ① `Accept-Encoding: gzip` + 大响应（≥1024B）⇒ `Content-Encoding: gzip` 且体可 `gzip.decompress` 还原；② `gzip;q=0` ⇒ **不压缩**（无 `Content-Encoding`）；③ `GZIP` / `*` ⇒ 压缩；④ 小响应（<1024B）⇒ 不压缩；⑤ `cache=True` 响应恒含 `Vary: Accept-Encoding`；⑥ `cache=False` + gzip 响应**亦**含该头，`cache=False` + 未压缩则不含 | E1 / S1 |
| **SRV-T45** `main()` 预热线程（v1.4） | patch `warm_transport` 计数 ⇒ `main()` 启动即调用一次（daemon 线程内）；`warm_transport` 抛异常 / 上游不可达 ⇒ **不影响**启动与 `/healthz`（静默、总函数） | 冷启动 / S9 |
| **SRV-T46** 首次 200 带 ETag/Last-Modified（v1.5） | 冷路径请求 `/cls/telegraph`（patch handler 返回固定 XML）⇒ `200`；响应含 `ETag`（形如 `W/"<64 hex>"`）与 `Last-Modified`（`formatdate` 可被 `parsedate_to_datetime` 解析）；`feed_cache_put` 被调 1 次 | 本专项 R1 / A8 |
| **SRV-T47** 同 ETag 重放 ⇒ 304 零 body/无 Content-Encoding **+ 幂等重放**（v1.5；★ v1.6 / C7#6 扩） | 第二次请求带 `If-None-Match: <上一步 ETag>` ⇒ **304**；断言 **无 body**（`self.wfile` 未写 / socket 读到 0 字节）、**无 `Content-Encoding`**、**无 `Content-Length`**、**无 `Content-Type`**；含 `ETag` + `Cache-Control` + `Vary`；`feed_cache_put` **未被再次调用**。★ **幂等重放**：带**同一 ETag 连发两次** ⇒ **两次均 304**，且 `feed_cache_put` 计数**仍为 1**（首次回源那次）、`Last-Modified` 两次**相同**（304 不写缓存 ⇒ 时间源不被刷新） | 本专项 R1 / 304 语义 |
| **SRV-T48** `If-None-Match: *`（v1.5；★ v1.6 / C7#5 扩负向） | 请求带 `If-None-Match: *` ⇒ **304**（`*` 命中任何当前表示）；`If-None-Match: "nope"` ⇒ **200** 且**体为完整 RSS**（非空、`ET.fromstring` 可解析、item 数 == 上游条数、`ETag` 为新值） | RFC 9110 §13.1.2 |
| **SRV-T49** 多值列表 + 大小写/空白（v1.5；★ v1.6 / C7#5 扩负向） | `If-None-Match: "a", W/"b", <当前 ETag 去 W/>` ⇒ 304（任一项命中）；`If-None-Match: "a","b"` ⇒ **200 且体为完整 RSS**（非空、item 数正确、`ETag` 为新值） | RFC 9110 §13.1.2 |
| **SRV-T50** `W/` 弱标签（v1.5；★ v1.6 / C7#13 扩小写） | 客户端发**强** `"<当前 opaque>"` 与 **弱** `W/"<当前 opaque>"` ⇒ **均 304**（INM 用弱比较）；服务端标签为弱 `W/"…"`；★ **小写 `w/"<当前 opaque>"` ⇒ 200**（弱指示符**大小写敏感**，只认字面 `W/`，与 BR-SRV-39 修正后措辞一致） | RFC 9110 §8.8.3.2 |
| **SRV-T51** `If-Modified-Since` 未来/过去 **+ 等值边界**（v1.5；★ v1.6 / C7#4 扩边界；★ v1.9 / F1：时间源改 `last_modified`） | 仅带 `If-Modified-Since`（无 INM）：① 未来日期（`now+3600`，`formatdate`）⇒ **304**；② 早于 `entry['last_modified']` 的日期（`now-3600`）⇒ **200**（含完整体）；③ **★ 等值边界**：`If-Modified-Since` == 上一步响应发出的 `Last-Modified`（**同一秒**，客户端回显的常见路径）⇒ **304**（`<=` 成立） | RFC 9110 §13.1.3 |
| **SRV-T52** **channel 级内容未变跨 TTL 重生成 ⇒ ETag 不变 ⇒ 304（R1 关键）**（v1.5；★ v1.6 / C1 标注覆盖边界） | 用同一组 items 调 `generate_rss` **两次**（中间跨过 `_feed_cache_lock`，`lastBuildDate` 因 `timeval=None` 不同）⇒ `_feed_etag(x1) == _feed_etag(x2)`；端到端：patch `cache_policy('feed')['ttl']=0` 强制过期 → 第二次带旧 ETag ⇒ 仍 **304**；`<ttl>` 从 1 切到 3 时 ETag **亦不变**（ttl 被剔除）。⚠️ **覆盖边界（C1）**：本用例复用同一 items 直调 `generate_rss`，**结构上检测不到 item 级 `<pubDate>` 的"当前时间回落"** ⇒ 必须由 **`SRV-T52b`** 补齐（handler 层缺失/非法时间字段） | **本专项 R1**（防"裸 body 哈希"回归；channel 级） |
| **SRV-T52b** ★ **item 级 `pubDate` 哨兵回归（handler 层，跨 TTL ⇒ ETag 相同 ⇒ 304）**（★ v1.6 / C1 / C7#2；★ **P3a-r2 / P2-a 用例定义细化（防假绿）**） | **防假绿前置（P2-a 核心）**：`formatdate(timeval=None)` 与 `int(time.time())` **均为秒级** ⇒ 同一秒内两次回落值**相同** ⇒ **不 patch 时钟时，即便不做 C1 修复本用例也会绿**（重演 v1.5 `SRV-T52` 的假绿）。**① 必须 patch 时钟**：受控源（`mock.patch` 目标 = `srv.formatdate` / `srv.time.time` / `utils.formatdate`，或等价）令两次回落**确定**取 **`t`** 与 **`t+1`**（**跨秒**）。**② 红/绿方向声明**：若 `pubDate` 仍在哈希区 ⇒ 两次 `generate_rss` 的 ETag **必不同** ⇒ 断言 `_feed_etag(x1) == _feed_etag(x2)` **必须失败（用例必须红）**；C1 修复后（`pubDate` 被 canonical 投影剔除）⇒ **必绿**——即该用例对 C1 具**真实捕获力**。**③ 纯函数断言（不依赖时钟，直接锁死投影规则）**：手工构造两个**仅 `<pubDate>` 值不同**、其余（channel `title`/`link`/`description`/`lastBuildDate`/`ttl`/`<atom:link>` + item `guid`/`title`/`link`/`description`）**逐字节相同**的 XML `x1`/`x2` ⇒ `_feed_etag(x1) == _feed_etag(x2)`（`count=0` **全量**剔除的直接回归网）。**④ handler 层（三门 feed 覆盖保持不变）**：在 feed handler 层对 3 个 feed 分别 patch 上游响应**缺失/非法时间字段**：eastmoney **`showtime`**、ths **`ctime`**、jin10 **`time`**（参数化一条或各一条），配合 ① 的时钟 ⇒ `generate_rss` 内部回落确定取 `t`/`t+1` ⇒ 断言 `_feed_etag(x1) == _feed_etag(x2)`（**剔除 pubDate 后相同**）⇒ 端到端带旧 ETag ⇒ **304**。**负向**：`pubDate` 变化**伴随**真内容（`guid`/`title`）变化时仍应 200（复用 T53）。**⑤ 验收证据资格**：**未控制时钟时不得作为 C1 的验收证据** | **本专项 R1**（P1-01 回归网；v1.5 的 T52 结构上假绿；P2-a 防"秒级回落同值"假绿） |
| **SRV-T53** 内容变化 ⇒ ETag 变化 ⇒ 200（v1.5） | 新增/修改一条 item（guid 不变、仅 title 变）或 `<atom:link>`（不同 Host）⇒ `_feed_etag` **不同**；端到端带旧 ETag ⇒ **200**（体含新内容）。**证明 ETag 覆盖 channel 字段与 feed_url，不是仅 guid 序列** | 本专项 R1 |
| **SRV-T54** `HEAD` 的 304（v1.5；★ v1.6 / C7#9 扩 IMS） | `do_HEAD` + `If-None-Match: <当前>` ⇒ **304**，头与 GET 304 相同（`ETag`/`Cache-Control`/`Vary`），无 body；无头 `HEAD` ⇒ 200（含 `Content-Length`，不写体）；★ **`HEAD` + 仅 `If-Modified-Since`（未来日期）⇒ 304**（两分支交叉：`write_body` 不参与条件判定，`_send_not_modified` 从不写体） | RFC 9110 §9.3.2 / BR-SRV-41 |
| **SRV-T55** `PUBLIC_BASE_URL` 未设时 304 仍 `private` + `Vary: Host…`（v1.5；**★ v1.9 / F7#8 改写：自造陈旧条目、不依赖时序**） | **前置**：在 `feed_cache` 里**手工注入**一条已过期条目（`expires_at` 早于 `now`；含 `xml/time/last_modified/fingerprint` 六字段）——**不依赖"等到 TTL 过期"的时序**；请求带该表示对应的 `If-None-Match` ⇒ **304**；断言 `Cache-Control: private, max-age=30` 与 `Vary: Host, X-Forwarded-Host, X-Forwarded-Proto, Accept-Encoding`（`PUBLIC_BASE_URL=''`）；设 `PUBLIC_BASE_URL` 时键/表示独立（表示与 Host 无关）、304 为 `public` 且 `Vary: Accept-Encoding`。头集合白名单由 **`SRV-T67` 独立证明**（本用例只锁 `private`/`Vary`）。**★ 旧版缺陷**：原用例在 `PUBLIC_BASE_URL` 切换后仍得 304，只因 **path 键缓存了旧表示**（P1-2）——F2 后该路径不再成立，故必须改写 | S2-3（反投毒不因 304 失效）/ **F2** |
| **SRV-T56** 非法日期头 ⇒ 200（v1.5） | `If-Modified-Since: not-a-date` / `If-Modified-Since: 99` / 空值 ⇒ **200**（绝不 400/500），且无异常日志冒泡；`If-None-Match` 存在 + 非法 IMS ⇒ 只看 INM（优先级），INM 命中 ⇒ 304、不命中 ⇒ 200 | S1 / RFC 9110 |
| **SRV-T56b** ★ **INM 不匹配 ∧ IMS 本会命中 ⇒ 必须 200**（★ v1.6 / C7#1 负向断言） | 构造 `If-None-Match: "nope"`（**不匹配**）**同时** `If-Modified-Since: <未来日期>`（**单独本会命中 ⇒ 304**）⇒ 断言 **200**（体为完整 RSS，非 304、非空）。**证明 INM 的优先性是对 IMS 的完全忽略**（RFC 9110 §13.1.3 最强断言）；T56 只用**非法** IMS 验证优先级，未证明"忽略一个本来有效的 IMS" | RFC 9110 §13.1.3 / **本专项 R1 第 4 项不可妥协语义** |
| **SRV-T57** gzip 请求下 304 无 `Content-Encoding` **+ ETag 编码无关**（v1.5；★ v1.6 / C7#8 扩核心推断） | `Accept-Encoding: gzip` + `If-None-Match: <当前>` ⇒ **304** 且 **无 `Content-Encoding`**、无 body；断言 `_accepts_gzip` 结果为 True（即"客户端能解 gzip"不改变 304 组成）；同请求去掉条件头 ⇒ 200 且（≥1024B 时）`Content-Encoding: gzip` 可解压还原。★ **编码无关**：对同一 feed 分别以 `Accept-Encoding: gzip` 与 `identity` 请求 ⇒ **两次 200 的 `ETag` 逐字相同**（弱标签在 gzip 之前由未压缩 XML 派生）；持 **gzip 时代**拿到的 ETag 重放 ⇒ **304**（各客户端复用自身编码副本） | E1 / BR-SRV-41 / **BR-SRV-37 编码无关核心推断** |
| **SRV-T58** `<ttl>` 输出与位置 **+ 边界 + 值域护栏**（v1.5；★ v1.6 / C7#11·#12 扩） | `generate_rss(..., ttl=1)` ⇒ XML 含 `<ttl>1</ttl>` 且位于 `</lastBuildDate>` 之后、`<atom:link` 之前；`ttl=None` ⇒ **无** `<ttl>` 元素。★ **`_feed_ttl_minutes()` 边界**：patch `cache_policy('feed')['ttl']` = `0/负/59/60/61/180/181` ⇒ `1/1/1/1/2/3/4`。★ **`generate_rss(ttl=0)` / `ttl<0` ⇒ 不得输出 `<ttl>0</ttl>`**（RSS 2.0 要求正整数；`ttl is not None and int(ttl) > 0` 护栏） | RSS 2.0 / BR-SRV-43 / **P2-07** |
| **SRV-T59** 降级不误 304 **+ 仅 IMS + 降级**（v1.5；★ v1.6 / C1 修正 + C7#7 扩） | ① patch `fetch_func` 抛异常、客户端带**刚拿到的成功 ETag** ⇒ **200** error feed（`_errors`/诊断 item），其 ETag 与成功体**不混淆**；② `Last-Modified` **不出现**（`last_modified=None`）；③ **★ 仅带 `If-Modified-Since`（未来日期）+ 降级 ⇒ 200 且响应无 `Last-Modified`**（`last_modified=None` 使 IMS 不可评估，BR-SRV-40）；④ **同一错误表示重放**（成功体旧 ETag 已换成 error feed 当前 ETag 再发）⇒ **304**（同一表示的条件命中，语义正确）。⚠️ **v1.5 的"连续两次失败 ⇒ ETag 因 `pubDate` 变化而不同"在 C1 后不再成立**（pubDate 已被 canonical 投影剔除），已按此改写 | S1 / BR-SRV-38 / **BR-SRV-37** |
| **SRV-T60** `feed_cache_get_entry` 契约（v1.5；★ v1.9 / F1+F5 扩） | 冷 cache ⇒ `None`；`feed_cache_put('/p','<x/>',30)` 后 ⇒ 返回 dict 且 `entry['xml']=='<x/>'`、`entry['time']` 为 float、**含 `last_modified`/`fingerprint`（六字段）**；TTL 过期 ⇒ `None`；**返回浅拷贝**（改返回值不影响后续 `feed_cache_get_entry`）；`feed_cache_get('/p')` 仍返回 `'<x/>'`（向后兼容，`test_cache.py` 全绿）；★ `feed_cache_put` **返回写入条目**（非 None） | `cache.md` BR-CACHE-32/33/34 / 兼容 |
| **SRV-T61** ★ **范围纪律负向断言：`/opml.xml`、`/`、JSON 端点带条件头 ⇒ 恒 200 全量**（★ v1.6 / C7#3） | 分别对 `/opml.xml`、`/`、任一 JSON 端点（如 `/market/margin?market=99`、`/healthz`）带 `If-None-Match: <任意>` / `If-Modified-Since: <未来日期>` ⇒ **恒 200 全量**（**绝不 304**），且这些响应**不含 `ETag`**（BR-SRV-36/44）；`/` 与 `/opml.xml` 亦不得因条件头改变体 | BR-SRV-36 / **BR-SRV-44** / 范围纪律（**v1.5 零覆盖**） |
| **SRV-T62** ★ **200 与 304 的头逐字一致（diff 而非两侧硬编码）**（★ v1.6 / C7#10） | 对**同一请求**先取 200、再带该 `ETag` 取 304 ⇒ 逐头 **diff** 两侧响应：`ETag`/`Last-Modified`/`Cache-Control`/`Vary` **完全相同**；304 独有差异 = **无** `Content-Type`/`Content-Length`/`Content-Encoding` **且** 无 body。**不得**两侧各自硬编码期望值（防两份头构造逻辑同时漂移）；覆盖 `PUBLIC_BASE_URL` 设/未设两种 | BR-SRV-41 / BR-SRV-42（`_send_text` 与 `_send_not_modified` 交叉校验） |
| **SRV-T63** ★ **IMS 跨 TTL 仍 304（F1 决定性证据）**（★ v1.9 / F1） | **受控时钟 + 同一规范化内容跨一次 TTL 重生成**：首次 200（记下 `Last-Modified`）→ 令条目过期（推进受控时钟越过 `expires_at`，或注入 `expires_at<now` 的同表示条目）→ 再次回源得到**同一规范化内容**（`<lastBuildDate>`/`<pubDate>`/`<ttl>` 可变）⇒ 断言 **`Last-Modified` 不前进**（条目 `last_modified` 不变）**且**第二次仅带 `If-Modified-Since: <第一次 Last-Modified>` 回 **304**。**证伪方向**：若指纹未继承（每次写入都取 now）⇒ `Last-Modified` 前进 ⇒ 第二次必 200 ⇒ 用例**必须红** | 本专项 R1 / **F1（P1-1）** |
| **SRV-T64** ★ **指纹继承/变更两向**（★ v1.9 / F1） | ① **真内容变**（改 `title` 或 `guid`，其余逐字节相同）⇒ `_feed_fingerprint`/`ETag` 变 **且** `last_modified` **前进**；带旧 `If-None-Match` ⇒ **200**。② **仅 `<pubDate>` / `<lastBuildDate>` / `<ttl>` 变** ⇒ 指纹与 `ETag` **都不变**、`last_modified` **不前进**、回 **304**（把"仅 pubDate 变 ⇒ 304"这一既定取舍变成**显式正向用例**，与 `SRV-T52b` 的纯函数/时钟断言互补）。**证伪方向**：若指纹含 pubDate ⇒ ② 会 200（红） | 本专项 R1 / **F1** |
| **SRV-T65** ★ **跨 Host 键隔离**（★ v1.9 / F2） | `Host: a.example` 与 `Host: b.example` 两次请求（`PUBLIC_BASE_URL=''`）⇒ **两把键**（`path + '\x00' + base_url`），各自 body 的 `<atom:link rel=self>` 指向自身 base_url；**后者不得看到前者的链接**（`feed_cache` 内两条独立条目，**不 `clear()` 也隔离**）。`PUBLIC_BASE_URL` 已设 ⇒ 键**不随 Host 变**（同键、同一条目）。**证伪方向**：若键仍为 `path` ⇒ 第二次命中第一条目、body 链接错误（红） | **F2（P1-2）** / BR-SRV-45 / S2-3 |
| **SRV-T66** ★ **`http_304_total` 计数**（★ v1.9 / F3） | 一次 200 后带其 `ETag` 回 304 ⇒ `metrics.snapshot()['http_304_total']` 由 `n` 增到 `n+1`；200 **不增**；**`snapshot()` 在从未发生 304 时也读到 `0`**（BUG-P6C-04 风格：零值恒定发布、非键缺失）。可与 `metrics.reset()` 组合保证用例隔离 | **F3（P2-6）** / BR-SRV-46 / S10 |
| **SRV-T67** ★ **`_send_not_modified` 头集合白名单**（★ v1.9 / F6 + F7#5） | 对 304 响应断言**头集合恰为** `{ETag, Last-Modified, Cache-Control, Vary, Server, Date}`（后二者由 `BaseHTTPRequestHandler.send_response` 注入）；**不得**出现 `Content-Length` / `Content-Type` / `Content-Encoding`；**无 body**。该函数在 codegraph 中**当前无覆盖测试** ⇒ 本用例为其首个**直接**覆盖（同时兜底 F6 的 HTTP/1.0/EOF 语义假设） | **F6（P2-7）** / BR-SRV-41 / RFC 9110 §8.6 |
| **SRV-T68** ★ **INM 极端输入恒 200 且不抛**（★ v1.9 / F7#6） | `If-None-Match` 取：**空串**、**超长（>8KB）**、**畸形**（`',,,'`、`W/` 无引号、**小写 `w/"…"`**、含空格）⇒ **恒 200**（体为完整 RSS）、**不抛异常**、连接不中断。要点：小写 `w/` **不**匹配（BR-SRV-39 大小写敏感）；空串/空白项被跳过 | RFC 9110 §13.1.2 / S1 / BR-SRV-39 |
| **SRV-T69** ★ **`_feed_ttl_minutes()` ↔ max-age 一致性断言**（★ v1.9 / F4） | 对 5 个 feed path：`_feed_ttl_minutes() == ceil(_cache_age() / 60)`（两者同读 `feed` 域）；盘中/非盘各断言一次（30→1、180→3）。**证伪方向**：若 `_CACHE_AGE_DOMAINS` 回退 `news_url` 且两域 `ttl_factor` 分叉 ⇒ 断言红 | **F4（P2-4）** / BR-SRV-47 / A3 |
| **SRV-T70** ★ **`feed_cache_put` 返回写入条目 / miss 无二次查询**（★ v1.9 / F5） | 冷路径一次请求：patch/计数 `feed_cache_get_entry` ⇒ `_get_or_fetch_feed` 内调用次数 == **2**（① 首次 + ③ 双检），**put 之后无第三次**；`feed_cache_put` 返回值为 **dict（非 None）** 且含六字段；200 响应**必带 `Last-Modified`**（真实条目存在时）。**证伪方向**：若仍 put 后再查 / 返回 None ⇒ 计数 3 或用例报错（红） | **F5（P2-5）** / BR-SRV-48 / A8 |

| **SRV-T71** ★ **feed 取数锁表收敛性（不随 N 增长 · **纯串行**）**（★ v1.10 / F8；★ v1.12：并发变体移入 `SRV-T73`） | **串行**请求 N=50 个不同 Host 的**同一** feed path（`PUBLIC_BASE_URL=''`，每次请求完成后再发下一个）⇒ 每次请求后断言 `len(_feed_fetch_locks)` **不随累计 N 增长**：稳态（无在飞）时 `== 0`——即第 50 次后与第 1 次后同为 `0`（**不是** `== N`）。**证伪方向**：若锁表只增不减 ⇒ 串行断言在第 2 次后即红（`len == N`）。**并发在飞变体见 `SRV-T73`**（本用例保持纯串行，两用例互为补充） | **F8（P1-1）** / BR-SRV-50 / AC-S9 |
| **SRV-T72** ★ **并发不双抓 + 异常路径计数归零**（★ v1.10 / F8） | ① **不双抓**：同一 `cache_key` 两个并发请求，`fetch_func` 用**计数桩 + `threading.Event` 同步**（先到的桩阻塞，直到确认另一个已进入等待）⇒ 断言 `fetch_func` **只被调用 1 次**、两响应体相同。② **异常路径**：`fetch_func` 抛异常 ⇒ 请求返回降级 RSS（200），且 `_feed_fetch_refs` **归零、键已 `pop`**（`release` 在 `finally` 生效）——**证伪方向**：若 `release` 不在 `finally` ⇒ 计数滞留、后续同类请求锁表只增不减（红）。③ **不双抓回归（TS-4）**：线程 A `acquire` 后**挂起在 `with` 之前**、线程 B `acquire` ⇒ 两线程拿**同一把锁**、B 阻塞至 A 释放 | **F8（P1-1）** / BR-SRV-50 / `cache.md` **T-CACHE-35** / A8 |
| **SRV-T73** ★ **并发在飞 K 键：锁表上界 + 两表同步**（★ v1.12 / F8 并发变体 · 独立可测） | **装置（不用 `sleep` 撞运气）**：对 K（如 **8**）个**不同 Host** 的同一 feed path（`PUBLIC_BASE_URL=''` ⇒ K 个不同 `cache_key`）**同时**发起请求；`fetch_func` 用**阻塞式取数桩 + `threading.Event` 同步**——每个桩进入后置位"已到达"事件并**阻塞等待"放行"事件**，使 **K 个键同时在飞**（主线程等齐 K 个"已到达"后统一放行）。**断言**：① **在飞期间** `1 <= len(_feed_fetch_locks) <= K` **且 `len(_feed_fetch_refs) == len(_feed_fetch_locks)`（两表同步）**；② **全部返回后** `len(_feed_fetch_locks) == 0` **且** `len(_feed_fetch_refs) == 0`。**证伪面（★ v1.13 收窄）**：本用例的取数桩**从不抛异常** ⇒ **不能**证伪"`release` 不在 `finally`"（成功路径上"`with` 后裸 `release`"与"`finally release`"行为相同）——该变异由 **`SRV-T72`**（异常路径计数归零）捕获。**T73 的证伪面 = ① 锁表按累计增长（`> K`）/ ② 两表（`_feed_fetch_locks` 与 `_feed_fetch_refs`）不同步（归零只 `pop` 一张表 ⇒ `len(refs) != len(locks)`）/ ③ 在飞上界 > K**。**超时余量与收尾证据（★ v1.13 / P2-5）**：等待放行 / `join` 的超时**不得过短——建议 ≥10s**（原 5s 在极端重载下 `release.wait(5.0)` 可能先于断言超时，线程越过放行点提前 `release` ⇒ 在飞快照 / 收尾归零断言**伪红**）；并在 `join` 之后断言线程**已结束**（`assertFalse(t.is_alive())`），把"到底谁没跑完"变成可见证据 | **F8（P1-1）** / BR-SRV-50 / AC-S9（资源总账）/ `cache.md` **T-CACHE-35**（原语级） / A8 |

> ★ **v1.12 编号/实现映射核对（P2-2 覆盖缺口）**：本表用例编号计数 **74 → 75**（★ v1.12 新增 `SRV-T73` 共 **1** 条；`SRV-T71` 为**改写**——并发变体句移入 `T73`、**编号不删**）。新增覆盖：`T73` = **并发在飞 K 键**的锁表上界（`1 <= len(_feed_fetch_locks) <= K`）+ **两表同步**（`len(_feed_fetch_refs) == len(_feed_fetch_locks)`）+ 全部返回后两表归零。原语级白盒见 `cache.md` `T-CACHE-35`。
> ★ **v1.13 更正（`SRV-T73` 证伪面收窄 + 超时余量）**：`T73` 的取数桩**从不抛异常** ⇒ **不能**证伪"`release` 不在 `finally`"（该变异归 **`SRV-T72`** 异常路径计数归零）；**`T73` 的证伪面 = 「按累计增长 / 两表不同步 / 上界 > K」**。等待放行 / `join` 超时**建议 ≥10s**（原 5s 在极端调度下有**伪红**风险），并在 `join` 后 `assertFalse(t.is_alive())`（P2-5 伪红防护）。`T73` 的 **「两表相等 + 在飞上界 + 归零」三条断言不变**；测试编号计数仍 **75**（不新增编号，`T73` 为改写）。
> ★ **v1.10 编号/实现映射核对（P8 F8）**：本表用例编号计数 **72 → 74**（★ v1.10 新增 `SRV-T71`/`SRV-T72` 共 **2** 条；`SRV-T55` 为改写、不新增编号）。新增覆盖：`T71` = 锁表收敛性（不随 N 增长；F8）；`T72` = 并发不双抓 + 异常路径计数归零（F8）。原语级白盒见 `cache.md` `T-CACHE-35`。
> ★ **v1.9 编号/实现映射核对（P8 F7）**：本表用例编号计数 **64 → 72**（★ v1.9 新增 `SRV-T63..T70` 共 **8** 条；**`SRV-T55` 为改写、不新增编号**）。新增覆盖：`T63` = IMS 跨 TTL 304（F1 决定性）；`T64` = 指纹继承/变更两向（F1）；`T65` = 跨 Host 键隔离（F2）；`T66` = `http_304_total`（F3）；`T67` = `_send_not_modified` 头集合白名单（F6）；`T68` = INM 极端输入（BR-SRV-39）；`T69` = `_feed_ttl_minutes()` ↔ max-age（F4）；`T70` = `feed_cache_put` 返回值 / 无二次查询（F5）。
> ★ **v1.8 编号/实现映射核对（P7b 顺带）**：`SRV-T52b` 实现拆为 **5 个 unittest 方法**（`test_t52b_pure_function_only_pubdate_differs_same_etag` / `test_t52b_handler_eastmoney_missing_showtime_clocked` / `test_t52b_handler_ths_invalid_ctime_clocked` / `test_t52b_handler_jin10_missing_time_clocked` / `test_t52b_end_to_end_cross_ttl_304`），属**方法粒度**拆分；`SRV-T61` = `test_t61_scope_negative_static_and_json_never_304`，`SRV-T62` = `test_t62_200_and_304_headers_diff_verbatim`。


## 9. AC 追溯矩阵

| 本模块设计点（§） | 覆盖 AC |
|------------------|---------|
| `_guard(shape)` 覆盖 14 JSON + 5 RSS + `/healthz`（§2.3 / §5.1 / §5.2） | **S1**（主承载）/ **A5** / R1 |
| shape 由 `_JSON_SHAPES` 派生 + `assert len==14`（§2.2） | **S1**（防漏数复发）/ A5 |
| `_handle_stock_batch` 计算并透传 `dropped`（§2.4 / §5.3） | **A9** / R4 |
| feed 双检 + per-键 锁 + TTL 接 `cache_policy('feed')`（§2.5 / §5.4） | **A8** / **A3**（承诺=行为）/ R3 / ★ v1.10：锁表有界（BR-SRV-50）/ **AC-S9** |
| `_cache_age()` / healthz `cache_ttl` 接 policy（§5.8 / §5.6） | **A3 / A8** / R16 |
| plate 三档 stagger 派生（§4.3 / §5.5） | **A3 / E6** / D-7 |
| `/ths/longhu` 走 `fetch_json(encoding='gbk')` + L4（§4.2 / §5.5） | **E9** / R15 |
| **`_fetch_concurrent` ≤3 并发展开**（hotplate/plate/longhu）（§4.6 BR-SRV-30 / §5.5） | **E2**（主承载）/ **S7** / E8（资源口径）/ R13 |
| `/cls/hotplate` 分区 error 客体 + **全失败补顶层 `error`**（§4.6 BR-SRV-31 / §5.5） | **A5**（主）/ S4 |
| healthz 零上游快路径 + 专用执行器 + **有界准入**（§2.6 / §5.6） | **S8**（主承载）/ **S10** / R2 |
| healthz 精确 schema（既有 4 键 + 4 新键）（§3.1） | **S10** / P2-N1 |
| `MAX_INFLIGHT` 显式 + 立即 503 + `http_503_total`（§2.7 / §5.7） | **E8 / S5** / **S10** |
| CDP A 类 `page_data` 防御 + timeline 禁止裸 null（§4.6 / BR-SRV-27） | **S4** / S1 / R18 |
| CDP A′ `/stock/f10` 逐码 `cdp_unavailable`（由 stock_api 承载，本模块只传 `dropped`） | **S4 A′** |
| watchdog 委派 `watchdog_restart_skip_reason()`（§5.7） | **S4 / S9 / S10** / R19 |
| `feeds[].status` + 首页 CDP 列修正（§2.9.1） | **S4** / Q2（契约同步待编排层） |
| 错误语义矩阵（400/404/503/200-error/200-值域）（§2.1 / §6.1） | **A5** |
| 单请求上界（REST ≤15s / **hotplate·plate·longhu ≤10s（并发）** / CDP ≤8s）（§6.2） | **E2**（主承载，`§10#10` 归属已更正）/ S7 |
| 无全局锁 / 锁序纪律（§7） | **S2**（不劣化，与 stream 共享）/ S9 |
| 静态端点不纳入 guard 的显式声明（§6.3） | S1（范围声明） |
| 业务端点降级 = **200 + error 体**（BR-SRV-5b / §5.5 `_send_json_shape`；★ v1.3 N1 回退） | **A5**（主）/ S1（降级体仍结构化） |
| healthz guard 失败 / 缺 status / degraded ⇒ 503（§5.2） | **S1 / S8**（**healthz 自身语义**，非业务端点先例） |
| 批量码归一 + 响应键回写（§2.4 / `_parse_stock_codes` / `_rekey_batch_response`） | **A6 / A9 / P1-6** |
| `/market/margin` 参数门 400（BR-SRV-5c） | A5 |
| `_base_url` Host 校验 + `private`/`Vary`（BR-SRV-33） | **S2-3** |
| 面板 cache-age 域 = quote（BR-SRV-8b） | S2-3 / A3 |
| longhu 席位配对无条件自增（BR-SRV-32） | 数据正确性（P0） |
| `request_queue_size = LISTEN_BACKLOG`（§2.7） | E1（突发连接） |
| 响应 gzip 协商 + `Vary: Accept-Encoding`（BR-SRV-34 / §1.1#11 / §5.8） | **E1**（网络时间） / S1 |
| `main()` 预热 `warm_transport`（BR-SRV-35 / §1.1#12 / §5.9） | 冷启动（与 E1/E2 相关；观测项） |
| **RSS 条件请求 ETag/Last-Modified/304（v1.5 / BR-SRV-36..44 / §5.4 / §5.8）** | **本专项 R1**（下游轮询带宽：内容未变 ⇒ 304 零 body）/ **A8**（feed 缓存同源）/ **E1**（响应路径）/ S1（非法头不冒泡） |
| **`_feed_etag` 规范化体弱校验器（BR-SRV-37；★ v1.6 / C1 含 item 级 `<pubDate>` 全量剔除）** | **本专项 R1**（防"裸 body 哈希 ⇒ 永远 200"静默失效；**双向不变式**：不误 200 ∧ 不误 304） |
| **`feed_cache_get_entry` 访问器（BR-CACHE-32 / §2.5a）** | A8（Last-Modified 时间源）/ 兼容（`feed_cache_get` 签名不变） |
| **★ v1.9 / F1：`Last-Modified` = 表示变更时刻（BR-SRV-38 改写 / BR-CACHE-33 / §5.4 / §6.2#8⑧）** | **本专项 R1**（跨 TTL 仍 304；IMS-only 客户端带宽收益）/ A8 |
| **★ v1.9 / F2：feed 缓存键覆盖 `base_url`（BR-SRV-45 / §5.4 / §3.3）** | S2-3（头与行为一致、防跨 Host 订阅链接劫持）/ A8 |
| **★ v1.9 / F3：`http_304_total`（BR-SRV-46 / §5.8 / `metrics.md` BR-MET-14）** | S10（304 可观测）/ 本专项 R1 回归报警 |
| **★ v1.9 / F4：feed `max-age` authority = `feed`（BR-SRV-47 / §3.3 / §5.8）** | A3（承诺=行为）/ A8（单一 authority） |
| **★ v1.9 / F5：`feed_cache_put` 返回写入条目（BR-SRV-48 / BR-CACHE-34 / §2.5 / §5.4）** | A8（200 必带校验器）/ S1（消除窗口） |
| **★ v1.9 / F6：HTTP/1.0 304 EOF 收尾、不发 `Content-Length`（BR-SRV-49 / §10#36）** | E1（响应路径）/ RFC 9110 §8.6 |
| **★ v1.10 / F8：feed 取数锁表引用计数收敛（BR-SRV-50 / `cache.md` BR-CACHE-35 / §2.5 / §5.4 / §7.1·7.2 / §8 T71·T72）** | **AC-S9**（24h 资源总账：锁表不随累计 Host 单调增长）/ **AC-S1**（并发不双抓的既有前提）/ BR-SRV-45（键空间） |
| **★ v1.12：F8 并发变体测试契约（`SRV-T73`）+ `acquire` 先判空实现约束（BR-SRV-50 / `cache.md` BR-CACHE-35 / §8）** | **AC-S9**（并发在飞键数上界 = 锁表规模上界）/ **AC-S1**（两表同步、不双抓）/ BR-SRV-45 |
| **★ v1.13：`SRV-T73` 证伪面收窄（`release` 不在 `finally` 归 `SRV-T72`）+ 超时余量（≥10s）/ `assertFalse(t.is_alive())`（BR-SRV-50 / §8 / §10#45）** | **AC-S9**（并发在飞键数上界）/ **AC-S1**（两表同步、不双抓、异常路径归零由 T72 证伪；T73 只证上界/同步/累计） |

> **AC 覆盖核对**：本模块承载 **S1/A5/A8/A9/E2/E8/E9/S4/S5/S7/S8/S10** 共 12 条（v1.1 新增 **E2**：server 自有的 hotplate/plate/longhu 单请求上界）；`E1/E3/E4` 由基础层/数据层承载（本模块仅提供 `_cache_age` 与序列化路径）；`E6` 由 config/stock_api 承载（本模块提供 plate 侧派生）；`A3` 由 stock_api 承载（本模块提供 feed 侧同源）。

---

## 10. 与 SAD / 现有代码的偏差与歧义标注（不擅自改 SAD）

| # | 项 | SAD / 契约表述 | 本文裁决 | 理由 |
|---|----|---------------|---------|------|
| 1 | **longhu 上游 URL/headers 的归属** | `config.md` v1.1 §2.4「保留（不动）」表登记了 `_*_BASE_URL`/`_*_HEADERS`，但**未含** longhu 两 URL；现状为 `server.py` 内联 `Request(...)` 字面量 | 提取为 **`server.py` 模块级常量** `_LHBTABLE_URL`/`_LHBTABLE_HEADERS`/`_LONGHU_PAGE_URL`/`_LONGHU_PAGE_HEADERS`，**不上收 config** | `config.md` 已评审冻结，新增 config 常量须与 `config.md` 同 change-set（会造成跨文档返工）；本模块内常量可满足"消除 `urlopen` 直连"的 R15 目标。**建议编排层后续把该域常量上收 config 并同批改 `config.md`** |
| 2 | `_cache_age()` 未登记路径的兜底 | SAD §3 server 行只说"`_cache_age()` 改读 policy" | 未登记路径（4 面板 / `/healthz` / `/` / `/opml.xml`）→ `_DEFAULT_AGE_DOMAIN='f10'`（L4、factor 1.0 ⇒ **恒 300**，与现状逐字等价） | `DOMAIN_MATRIX` 无"面板/CDP"域，且新增域须改 `config.md`；用 L4 域承载可保证 **0 行为变更**且无裸 TTL 字面量。**登记：该域选择不表达业务语义，仅为口径连续** |
| 3 | `_send_error` 增 `write_body` 形参 | SAD 未提 | `_send_error(self, msg, write_body=True)`，调用点透传 | 现状 `_send_error` 硬编码 `write_body=True`，**HEAD 请求的 400 会写体**（HTTP 语义瑕疵）；属 R1"边界"范围内的最小修正。非契约变更（内部方法） |
| 4 | `_guard` 覆盖范围 | SAD §2.4：`_guard` 覆盖**全部 14 个 JSON 分支** + `rss` + `text` | **扩展为 14 JSON + 5 RSS + `/healthz`**；`/`、`/opml.xml` **显式排除** | ① healthz 自身必须总函数（AC-S1 的"全端点"口径）；② `/`、`/opml.xml` 为纯内存拼接、无外部数据，AC-S1 的注入故障不可达。属**超集**而非偏离 |
| 5 | 准入失败且**从无快照**时的响应 | SAD §2.6：`return 上次快照 + {"stale": true}`（隐含必有快照） | 若 `_health_last_snapshot is None` → 返回**本次零上游体 + `status='degraded'`** + `stale:true`（HTTP 503） | 进程启动后首个 `?check=1` 即被并发占满时，"上次快照"不存在；返回可解析体优于 `None`/500。**登记：SAD 未定义该边界** |
| 6 | `feeds[]` 的端点覆盖 | SAD §7.1 Q2 只列 3 处 `status` 修正 | 保持现状 15 条（**不新增** `/finance/timeline`、`/market/timeline`、`/ths/longhu`、`/stock/announcement`） | 现状 healthz `feeds[]` 未含这 4 个端点（既有 gap，非本次引入）；新增条目属"只增"但会扩大 `feeds[]` 契约面，**建议编排层单独决策**。**登记为已知缺口**（AC-S4 的端点验证不依赖 healthz 列表） |
| 7 | `feeds[].status` 取值修正（3 处） | SAD §2.6 Q2：属**改既有字段取值**（≠"只增不改"），须编排层批准 | 本文按目标值落地 + 登记；**同步范围 = healthz 负载 + 首页 CDP 列 + API.md** | AC-S4 归类的直接前提（`/stock/data`→B、`/stock/basic_info`→B、`/stock/f10`→A′）；SAD 只输出目标值，契约修改权在编排层 |
| 8 | healthz 执行器的线程名/预算常量 | SAD 只给 `max_workers=5`、整体 10s、单源 3s | 落 `thread_name_prefix='healthz'` + `_HEALTH_TOTAL_BUDGET=10.0`/`_HEALTH_SOURCE_BUDGET=3.0`/`_HEALTH_POLL=0.25` | 实现细化；AC-S9 的线程总账 +5 与 `MAX_HEALTH_INFLIGHT` 一致 |
| 9 | `_run_health_checks` 的 `pending` 判定方式 | SAD 只说 `as_completed(timeout=10)` | 改用 `wait(..., FIRST_COMPLETED)` 轮询（`_HEALTH_POLL=0.25`）以**能实现"单源 3s"**（`as_completed` 只在 future 完成时 yield，无法对未完成源判超时）；**并按各 future 的 `submitted_at` 实现"每源独立 3s"、整体 10s 独立闸**（修 P2-2） | 行为对齐 SAD 的两级预算；时间复杂度 5 源 × 40 轮，可忽略 |
| 10 | `/ths/longhu`、`/cls/hotplate`、`/cls/plate` 的单请求上界 | **AC-E2**（任何单请求 ≤15s）+ **SAD §4.1**（hotplate 3 次串行 → ≤3 并发，"本次顺带修"） | **改并发**：三者的多上游请求统一经 `_fetch_concurrent`（`max_workers=3`）展开 ⇒ 单端点 ≤ `REQUEST_TIMEOUT=10s`（≤15s ✅）。**登记项归属更正为 AC-E2**（v1.0 误记为 AC-S7 的边界） | 现状串行：hotplate ≈30s、plate ≈30s、longhu ≈20s，均**越 AC-E2 的 15s**；P95 由 `sum` 变 `max`（SAD §4.1 明令） |
| 11 | `MAX_INFLIGHT` 对**流端口**实例的语义 | SAD §4.3「流端口 worker = `MAX_STREAM_CONNS+10=110`」+ SAD §4.2 C-3（100 连接） | **采纳评审建议 + 编排层已批准**：`BoundedThreadPoolServer.__init__` 增 `max_inflight=None` 形参；主端口默认 `MAX_INFLIGHT(40)`，`stream.make_stream_server` **显式传 `MAX_STREAM_CONNS+10=110`** ⇒ 流端口 `_max_inflight=110`（**≥** 100 连接上限） | v1.0 的"主/流端口共用 40"把 SSE 连接上限从 100 压到 ≈40 ⇒ `MAX_STREAM_CONNS=100` 与 `_register_conn` 的 100 阈值沦为死代码、**AC-E5/E7 不可复现**。参数化后恢复现状语义（原 `max_workers*2=220` 亦 ≥110）；**行为变更已登记**（本行 + `stream.md` §10#13） |
| 12 | `healthz_inflight` gauge 的写入点 | `metrics.md` §3.2 owner = `server.build_health_payload` | 由 `_set_health_inflight` 统一写入（`build_health_payload` 的唯一子路径） | owner 不变，落点细化 |
| 13 | `_health_last_snapshot` 是否含 `check=1` 的真实结果 | SAD 未定义 | **含**：每次成功组装（`check=0` 或 `check=1`）都刷新 | `stale` 回退给"最近一次真实快照"信息量最大；`check=0` 体也刷新（否则长期无 `check=1` 时 stale 永远无快照） |
| 14 | `build_health_payload` 的 `policy` 字段含 `encoding` | SAD §2.6 schema 示例只列 5 键 | `cache_policy('longhu')` 会**额外带 `encoding:'gbk'`**（`config.md` BR-CFG-7 规定） | 与 `config.md` 契约一致；`policy` 字段本就是 policy 原样透出。**不改 schema 断言**（断言应为"⊇ 5 键 ∪ longhu 的 encoding"） |
| 15 | **外部上游扇出执行器**（新增） | SAD §4.1 只要求 hotplate ≤3 并发；未指定执行器归属 | 新增模块级**共享** `_fanout_executor`（`max_workers=_FANOUT_MAX_WORKERS=3`，懒创建、双检），供 hotplate/plate/longhu 复用；**不新增 config 常量**（`3` 为机制常量，同 `_HEALTH_POLL`） | 每请求新建 `ThreadPoolExecutor` 会引入不可控线程抖动；共享池使**全局**在这些端点上的在飞取数 ≤3（同时满足 AC-E8 资源口径）。线程账 +3（懒创建，AC-S9 上界见 §2.9）；★ v1.4：另有 `main()` 的 `warm_transport` 预热线程 +1（daemon，启动一次性） |
| 16 | **healthz 准入位语义**（修 P1-1，新增） | SAD §2.6：*并发 check 任务在飞数被信号量钉死，执行器内部队列**从不堆积**（提交前已准入）* | 引入 `_HealthBatch`：准入位由**该批全部 future 的完成回调**释放（非 `_run_health_checks` 返回时立即释放）⇒ 在飞任务 ≤25、工作队列 ≤20，SAD 断言**成立** | v1.0 的"3s `break` 后 `finally release`"只约束轮询窗口、不约束在飞任务 ⇒ 持续慢 check 下无界队列累积（重演 SAD P1-3 的放大器）。响应时点不变（仍 ~3s 返回），仅**释放时点**后移 |
| 17 | **handler 返回"组装 dict"（非 `(results, errors)`）** | SAD 对 `handle_cls_*` 的措辞将回改 | 保持现状口径：`handle_cls_*(codes, deadline=None, dropped=0) -> dict`（内部调 `build_batch_response`）；**编排层已批准**，SAD 措辞由 system-architect 回改 | `_PROGRESS.md` §B 锁定契约；server 只注入 `dropped`，组装点唯一 |
| 18 | **error-only payload ⇒ 503**（v1.2；★ **v1.3 已回退**） | SAD §2.1 AC-A5 五类状态语义只定义"上游失败 → 200 + error 客体" | **回退**：业务端点降级体**恒 200**（BR-SRV-5b）；`_json_payload_has_data` 与 `_send_json_shape` 的 503 分支**已删**；`http_503_total` 计数点回到 3 个 | v1.2 曾把"CDP/上游整体不可用"改判 503 以让监控可区分——但那**改动了既有对外状态码契约**，与 AC-A5「上游失败 → 200 + error 客体」冲突，且既有消费方按 200 解析。编排层裁决 **N1：回退**。真正的可用性观测由 `/healthz`（503 语义 + `stale`/`metrics`/`cdp` 字段）承担 |
| 19 | **`/healthz` 503 判定扩为"缺 status / 含 error"**（v1.2） | SAD §2.6：`payload['status']=='degraded'` ⇒ 503 | guard 捕获异常的体 `{'error': …}`（**无** `status`）也判 503，并计 `http_503_total` | v1.1 会把"健康检查自身抛异常"报成 200 ⇒ 假健康（S2-5） |
| 20 | **`/market/margin` 非法 market ⇒ 400**（v1.2） | SAD §2.1 只给 enum，未定义非法值行为 | guard 之前校验 `market ∈ VALID_MARKETS` ⇒ 400（`Invalid ?market= parameter. Allowed: 99,1,2,3`） | 避免非法值进入 URL/缓存键；与 `/cls/plate` 缺参 400 同族 |
| 21 | **批量码归一 + 键回写**（v1.2） | SAD §2.4 未定义码拼写归一 | `_parse_stock_codes`（`config.canonical_code` 折叠去重，截断按归一后计数）+ `_rekey_batch_response`（响应键回请求原拼写，纯改名） | 同一股票不得因拼写不同而铸出多个池/缓存/账本键（P1-6）；响应键契约不变（回原拼写） |
| 22 | **面板 cache-age 域改 `quote`**（v1.2） | SAD §3 server 行只说"`_cache_age()` 改读 policy"；v1.1 用 `_DEFAULT_AGE_DOMAIN='f10'`（恒 300）覆盖面板 | 4 面板注册到 `_CACHE_AGE_DOMAINS` 的 `quote` 域 ⇒ max-age **8/120**；未登记路径现仅 `/healthz`、`/`、`/opml.xml` | 面板是实时行情面，v1.1 的 300s 会把实时报价标成"可缓存 5 分钟"（与 AC-A3「承诺=行为」冲突） |
| 23 | **`_send_text` 增 `varies_on_host`**（v1.2） | SAD 未涉及 Host 头可信性 | `_send_text(..., varies_on_host=False)`；`PUBLIC_BASE_URL` 未设时 feed/opml/（派生 base URL 的响应）标 `private` + `Vary: Host, X-Forwarded-Host, X-Forwarded-Proto`；`_base_url()` 做格式校验（非法 ⇒ localhost） | Host 可被伪造且会嵌入 feed 体 ⇒ 防共享缓存投毒（S2-3） |
| 24 | **`_send_json_shape`**（v1.2；★ v1.3 简化） | SAD §2.4 只要求"shape 由路由表派生" | object JSON 分支统一走 `_send_json_shape(path, fn)`：shape 读 `_JSON_SHAPES[path]`（不再写死字面量）；**恒 `_send_json(payload, cache=cache)` ⇒ 200** | ① 消除"分支写死 shape 字面量"的漂移面；② v1.3 起"503 判定唯一入口"不复存在（回归单一口径：业务端点恒 200） |
| 25 | **`request_queue_size = LISTEN_BACKLOG`**（v1.2） | SAD §4.3 未定义 backlog | 类属性 `request_queue_size = LISTEN_BACKLOG`（config，默认 128） | socketserver 默认 backlog=5，突发连接下 accept 队列溢出 ⇒ 客户端 SYN 重传 ~1s（BUG-P6C-03，AC-E1 尾部尖峰） |
| 26 | **`_FANOUT_WAIT_BUDGET` 界定扇出等待**（v1.2） | SAD §4.1 只要求 ≤3 并发 | `_fetch_concurrent` 用 `wait(futs, timeout=REQUEST_TIMEOUT)`；超期 `cancel()` + `FetchError('upstream_timeout')` | 共享池被占时旧的无界 `fut.result()` 可让单请求拖到 ~190s（远超 AC-E2 的 15s） |
| 27 | **`handle_ths_longhu` 席位配对无条件自增**（v1.2） | SAD 未定义解析细节 | 标签匹配即 `broker_idx += 1`（即便该表 0 条 entries）；`stock_idx >= len(stocks)` 丢弃 + 告警；末尾错位告警 | 旧实现跳过自增会**静默错配**后续所有股票的买卖席位（HTTP 200 无错误信号）——数据正确性 P0 |
| 28 | **import 面更正**（v1.2） | v1.1 §2.10 块含已不在使用面的名字 | 增 `page_data` / `FetchError` / `LISTEN_BACKLOG` / `VALID_MARKETS`；删 `handle_cls_stock` / `fetch_cls_fundflow` / `fetch_cls_timeline` / `strip_html` / `escape_xml`；`MAX_HEALTH_INFLIGHT` 改用 `config.` 前缀 | 文档与实现逐行对齐（编码者可直接整体替换） |
| 29 | **N1 回退：业务端点降级恢复 `200 + error 体`**（v1.3） | AC-A5 只定义"上游失败 → 200 + error 客体"；v1.2 的 error-only ⇒ 503 属**超集变更** | `_send_json_shape` 恒 `_send_json(payload)`（**200**）；**`_json_payload_has_data` 删除**；**`_send_json` 去掉 `status` 形参**；**`http_503_total` 计数点 4→3**（`_reject_503` / `stream._serve_sse` / `/healthz`）；降级体 `cache=cache` ⇒ **按域 TTL 可缓存** | 编排层裁决 N1：v1.2 改判 503 动摇了既有对外状态码契约，既有消费方按 200 解析；`/healthz` 已能承担可用性观测，业务端点无需第二个 503 语义（且 `/healthz` 的 503 属端点自身语义，**不构成业务端点先例**） |
| 30 | **`_accepts_gzip` + 响应 gzip（v1.4）** | SAD §2.6/§4.3 未定义响应压缩 | `_accepts_gzip(header)` 按 RFC 9110 解析；`_send_text` 对 `≥ GZIP_MIN_BYTES(1024)` 且被接受的响应 `gzip.compress(level=GZIP_COMPRESSLEVEL=1)` + `Content-Encoding: gzip`；**`Vary: Accept-Encoding` 在 `gzipped or cache` 时必发** | 旧实现用子串匹配 ⇒ 对 `gzip;q=0`（明确拒绝）仍压缩、且漏掉大写 `GZIP`；共享缓存会把 gzip 体复用给不支持它的客户端。`GZIP_*` 为 `config` env（`config.md` §2.7） |
| 31 | **`main()` 预热 `warm_transport`（v1.4）** | SAD §4.3 未定义进程启动传输预热 | 新增 daemon 线程 `warm_transport`（`HTTP_WARM_CONNECTIONS=1` / `HTTP_WARM_TIMEOUT=2.0`；主机由 `config.warm_hosts()` 从 URL 常量派生） | 冷进程首个 refresh 空连接池/空 DNS ⇒ 50 码 quote 扇出 ≈4.2s（> 0.8×tick 预算）；仅握手不发业务请求，不 gate 启动/`/healthz`（`config.md` §2.7 已登记 env） |
| 32 | **`_feed_etag` 用"规范化体哈希 + 弱标记"（v1.5；★ v1.6 / C1 扩展 canonical 投影）** | SAD/PRD 未定义 ETag 派生；任务书明确**严禁裸 body 哈希** | `sha256` 于 **剔除 `<lastBuildDate>`（count=1）、`<ttl>`（count=1）与 `<pubDate>`（count=0 全量）内容后**的整串 XML，标记 `W/`（弱校验器） | `<lastBuildDate>=formatdate(timeval=None)` 每次重生成即变 ⇒ 裸哈希会使"TTL 到期但内容未变"也返回 200（**功能静默失效**，本专项第一风险）。★ **v1.6 / C1**：v1.5 漏掉 **item 级 `<pubDate>` 的"当前时间回落"**（`server.py:107` eastmoney `showtime` / `server.py:133` ths `ctime` / `utils.py:241` jin10 `time`）⇒ 3/5 feed 每次 TTL 到期重生成都换 ETag ⇒ **永远 200**（R1 只闭合一半）；item 有多条 ⇒ 必须**全量替换**（`count=0`，非 `count=1`）。item 身份由 `<guid>` 承载、`pubDate` 属上游元数据且有已知非确定性回落 ⇒ 剔除；其余任一字节（`guid`/`title`/`link`/`description`/channel 字段/feed_url）都进哈希 ⇒ **双向不变式成立**（不误 200 ∧ 不误 304）。因剔除了字节差异，按 RFC 9110 §8.8.3 该 ETag 语义上为**弱**，故必须带 `W/`。备选"仅由 guid 序列派生"被否：会漏掉 `<atom:link>`（请求派生 Host 写入）与 channel 字段，跨 Host 会误 304。**`<pubDate>` 权衡理由**见 BR-SRV-37 |
| 33 | **ETag 覆盖 `<ttl>` 的取舍：剔除（v1.5；★ v1.6 / C3 补契约语义）** | RSS 2.0 `<ttl>` 未在既有设计中 | `<ttl>` 纳入生成（BR-SRV-43），但**从 ETag 规范化中剔除** | `<ttl>` 由 `cache_policy('feed')['ttl']` 派生，盘中/非盘切换（30↔180）会使其变化；若纳入 ETag，则内容未变也会在每日交易时段边界产生假 200（违反 R1）。★ **C3 契约语义（必须进 `API.md`）**：`<ttl>` 是**聚合器缓存提示、非时效保证**；**最小粒度 1 分钟**（`max(1, …)` 向上取整）；**推荐轮询 = `ETag` 条件请求优先、间隔 ≥30s**；**需 <60s 新鲜度请用 SSE（4s）**——`Cache-Control: max-age`（盘 30 / 非盘 180）是更强承诺。剔除 `<ttl>` 不会造成客户端误判（其语义已由 `Cache-Control` 与 `ETag` 承担） |
| 34 | **`_get_or_fetch_feed` 返回 `(xml, last_modified)`（v1.5，内部签名变更）** | 任务书要求"如何同时拿到 xml + etag + 时间" | 内部方法返回 2-tuple；`_guard(shape='rss')` 成功/异常两路**同形状**（异常 → `(error_rss, None)`） | 单一查询（`feed_cache_get_entry`）同时得到 xml 与 `time`；避免"先 `feed_cache_get` 再另查条目"拾取降级态陈旧时间。**非对外契约**（对外仅 RSS body/头）；`tests/test_server_http.py` 的打桩目标须同步（§10.1） |
| 35 | **`_send_text(..., etag=, last_modified=)` + 独立 `_send_not_modified`（v1.5）** | SAD/PRD 未定义响应头扩展 | 200 路径用 `_send_text` 的**纯新增可选形参**；304 路径用**独立方法** | 不把 304 塞进 `_send_text`：后者无条件计算 gzip/写 `Content-Length`/`Content-Type`，一个分支失误就会给 304 带体或 `Content-Encoding`。独立方法使"无 body / 无编码"成为结构性保证；200 的既有调用点因形参默认 `None` **零改动** |
| 36 | **304 不发 `Content-Length`（v1.5；★ v1.6 / C6 补依据）** | RFC 9110 §15.4.5（304 不得含内容）+ **§8.6**（304 若携带 `Content-Length`，其值**必须等于**该资源 200 体的字节数） | **不发** `Content-Length`（也不发 `Content-Type`）；由 HTTP/1.0 短连接在响应头结束后**由 EOF 终止消息** | **裁决理由（三条实证）**：① **RFC 9110 §8.6 规定 304 若带 `Content-Length` 必须等于 200 体长** ⇒ 显式写 **`Content-Length: 0` 反而违规**（本服务 200 体是 ~37KB XML）；② 本服务 `RSSHandler` **未设 `protocol_version`** ⇒ **HTTP/1.0**（全仓 `protocol_version` 仅 `stream.py:1359` 属流端口既有实现），且 CPython `http.server` **仅在 `protocol_version >= 'HTTP/1.1'` 时才把客户端 `Connection: keep-alive` 视为持久连接** ⇒ **每响应后关连接、EOF 即消息边界**；③ RFC 9110 §6.3 明定 304/HEAD 恒以"头后首个空行"终止，与是否带 `Content-Length` 无关。⇒ **保持现设计**（不发而非写 0）。**登记该取舍**；若编排层为兼容异常客户端要求，可加钝化防御 `if self.request_version == 'HTTP/1.0': self.close_connection = True`（不改契约） |
| 37 | **出范围：HTTP/1.1 keep-alive、`/opml.xml`、`/` 条件请求（v1.5）** | — | **仅登记，不实现**（BR-SRV-44） | `protocol_version` 变更波及全部端点的连接语义与线程池占用（`BoundedThreadPoolServer`/`max_inflight` 假设 HTTP/1.0 短连接），须独立评估；`/opml.xml`、`/` 无缓存条目时间源。**本轮不得顺带实现** |
| 38 | **★ F1：`Last-Modified` = 表示最后一次变更的时刻（v1.9；改写 BR-SRV-38）** | SAD/PRD 未定义 `Last-Modified` 时间源；v1.5–v1.8 取 feed 条目**写入时刻** `entry['time']`（BR-SRV-38 原文） | feed 条目新增 `last_modified`（+ `fingerprint`）；`feed_cache_put` 与**同一键上一条目**（★ **即使已过期**）比指纹：相同 ⇒ 继承，不同 ⇒ 本次写入时刻。**不变式 `ETag 变 ⟺ Last-Modified 前进`** | **P1-1**：写入时刻每次回源刷新 ⇒ IMS-only 客户端跨 TTL 必拿 200；`<ttl>1</ttl>`(60s) ≥ 盘中 TTL(30s) ⇒ 按推荐节奏轮询恰好每次踩在 TTL 之后 ⇒ 该通道带宽收益≈0。备选 `max(items pubDate)` 被否（改描述不改 pubDate ⇒ 错误 304 陈旧数据，比多发 200 严重）。副作用：`last_modified` 可能远早于 `<lastBuildDate>`（语义正确） |
| 39 | **★ F2：feed 缓存键覆盖 `base_url`（v1.9；BR-SRV-45）** | SAD/PRD 未定义 feed 缓存键；v1.5–v1.8 键 = `path` | `PUBLIC_BASE_URL` 已设 ⇒ `path`；未设 ⇒ `path + '\x00' + base_url`（与 `Vary` 同语义）；`_feed_fetch_locks` 按同一 `cache_key` 建锁 | **P1-2**：body 内嵌请求 Host 派生的 `<atom:link rel=self>`，但缓存只按 path 建键 ⇒ 一条伪造 Host 的请求即可在一个 TTL 内改写所有读者的订阅链接（**头与行为不符**）。**放大风险已论证**：上游 JSON 另有 URL 级缓存（不放大上游请求）、条目受 `cache_max=100` + LRU 约束、非法 Host 塌缩 `localhost:PORT` 单键。**★ v1.10 / F8 补正**：上列**只覆盖上游请求**，**未覆盖锁表内存与本地生成**——见 #44（锁表引用计数收敛，BR-SRV-50） |
| 40 | **★ F3：`http_304_total` 指标（v1.9；BR-SRV-46）** | SAD §2.6 计分板（19 名）未列该名 | `_KNOWN` + `_DEFAULTS` 同步注册（20 名）；`_send_not_modified` 单点计数 | `metrics.md` §3.2「注册表不新增名称」属**该文档旧口径**；本版经编排层裁定新增 1 名（**契约变更**，`metrics.md` v1.4 同步）。只需计数、不需分母：计数单调，停止增长即"永远 200"回归的报警 |
| 41 | **★ F4：feed `max-age` authority 改 `feed`（v1.9；BR-SRV-47）** | SAD §2.1 D4 只说"承诺=行为"；v1.2–v1.8 `_CACHE_AGE_DOMAINS` 把 5 feed path 映射 `news_url` | 5 path 改映射 `'feed'`；不变式 `_feed_ttl_minutes() == ceil(max-age/60)` | 同一件事（"建议多久轮询"）此前有**两个 authority**（`<ttl>`/feed TTL 用 `feed`，`max-age` 用 `news_url`），可静默漂移；`news_url` 语义是"上游 URL 取数缓存"，决定 RSS 响应 max-age 属语义错配（被"两域恰好同 L3"掩盖）。**数值不变、契约不变** |
| 42 | **★ F5：`feed_cache_put` 返回写入条目（v1.9；BR-SRV-48 / BR-CACHE-34）** | SAD 未定义；v1.5–v1.8 返回 `None`，miss 路径 put 后再查一次 `feed_cache_get_entry` | 返回写入条目浅拷贝（六字段）；`_get_or_fetch_feed` 直接消费 | 旧路径在 put 与再查询之间条目若被淘汰 ⇒ `last_modified=None` 而 ETag 仍发出 ⇒ 「200 带 ETag 却不带 `Last-Modified`」窗口；且省一次加锁往返。**新增可依赖行为须写进契约** |
| 43 | **★ F6：HTTP/1.0 304 不发 `Content-Length`、EOF 收尾（v1.9；BR-SRV-49）** | RFC 9110 §15.4.5/§8.6 | 保持不发（不写 `Content-Length: 0`）；**本轮不升 `protocol_version`/keep-alive** | §10#36 已给三条依据；本版**如实登记权衡**：中间件对"无长度 304 的 EOF 收尾"处理为**理论风险**，`http.client` 已实测通过（T47/T62）。升 HTTP/1.1 出范围（BR-SRV-44） |
| 44 | **★ F8：feed 取数锁表有界化（v1.10；BR-SRV-50 / `cache.md` BR-CACHE-35）** | SAD/PRD 未定义 feed per-键 锁表生命周期；`系统_代码评审报告_001.md` TS-4 曾因"`pop` 与持锁线程竞态 ⇒ 双抓"**移除 `pop`** ⇒ v1.9 前只增不减 | `_get_or_fetch_feed` 改经 `feed_fetch_acquire/release`（`try…finally` 保证异常也释放）；`release` 归零即**两表同删**；引用计数不变式 + 正确性论证 + 有界性结论入 BR-SRV-50；补 `SRV-T71/T72` + `cache.md` `T-CACHE-35` | **F2 把键空间从 5 条固定 path 变成 `path × 请求派生 base_url`**，`_valid_host_header`（`server.py:591`）**只校验格式、不校验归属** ⇒ 任意合法主机名可造新键：① 锁表**永久内存增长**（每键 ~300–450 B，外部可无界触发 ⇒ OOM）；② 键数超 `feed_cache` 上限 100 后每个新 Host 必 miss ⇒ `generate_rss`+sha256、LRU 抖动（**只放大本地 CPU，上游仍被 URL 级缓存兜住**）。**归零前 `pop` 会重演 TS-4 双抓** ⇒ 必须引用计数 |
| 45 | **★ v1.12：F8 并发变体测试契约（`SRV-T73`）+ `acquire` 先判空实现约束** | SAD/PRD 未定义 feed 锁表并发上界测试；`cache.py::feed_fetch_acquire` 现用 `setdefault(key, threading.Lock())`（每次调用先构造 `Lock` 再丢弃） | ① 新增独立可测用例 **`SRV-T73`**（K 个不同 Host 键**同时在飞**：在飞期间 `1 <= len(_feed_fetch_locks) <= K` **且两表相等**；返回后两表均 `0`）；`SRV-T71` 收敛为**纯串行**（编号不删）。② `acquire` 契约补**实现约束**：**先 `get` 判空、仅 `None` 时建 `Lock`**（命中路径零分配，语义不变；`cache.md` BR-CACHE-35 同步） | **P2-2 / 覆盖缺口**：v1.10 契约承诺了"并发 K 个不同 Host 同时在飞 ⇒ 在飞期间 `len <= K`"，但 `SRV-T71` 仅做**串行** N=50 ⇒ 承诺未实现、无回归网；`setdefault` 的每次构造属**无谓分配**（命中路径本可零分配）。两者均**不改变可观测行为**（前者补测试、后者仅去分配）。**★ v1.13 更正（`SRV-T73` 证伪面收窄 + 超时余量）**：`T73` 的取数桩**从不抛异常** ⇒ **不能**证伪"`release` 不在 `finally`"（成功路径上"`with` 后裸 `release`"与"`finally release`"等价；该变异归 **`SRV-T72`** 异常路径）；**`T73` 的证伪面 = 「按累计增长 / 两表（`_feed_fetch_locks` 与 `_feed_fetch_refs`）不同步 / 上界 > K」**，其 **「两表相等 + 在飞上界 + 归零」三条断言不变**。另：等待放行 / `join` 超时**建议 ≥10s**（原 5s 在极端调度下有**伪红**风险），并在 `join` 后 `assertFalse(t.is_alive())` |

---

## 11. 交付自检

- [x] 无 `{例:` 占位符；`_JSON_SHAPES`/healthz schema/`_cache_age` 映射/plate TTL 均为**实值**
- [x] §3 为 `yaml` 代码块（healthz schema / health 状态 / 路由与 shape / 服务类状态）
- [x] 路由表精确：14 JSON（逐一列名 + shape）+ 5 RSS + `/` + `/opml.xml` + `/healthz`；无增删路径
- [x] `_guard` 四 shape 语义与降级体逐一钉死；异常兜底范围（含显式排除项）声明
- [x] 业务规则编号 BR-SRV-1..**50**，伪代码直接引用编号（BR-SRV-30/31 为 v1.1 新增；v1.2 新增 5b/5c/8b/32/33；v1.4 新增 34/35；v1.5 新增 36–44；**★ v1.9 / F1–F6 新增 45–49 + 改写 38**；**★ v1.10 / F8 新增 50 + 补正 45 的放大风险论证**；★ v1.12 在 **BR-SRV-50 内补 `acquire` 实现约束**（不新增编号））
- [x] 关键流程伪代码齐备：分发 / `_guard` / 批量截断 / feed 双检 / **`_fetch_concurrent` 扇出** / plate stagger / longhu GBK / healthz 准入（`_HealthBatch`） / 过载 503 / watchdog / **★ v1.5 条件请求（`_feed_etag` / `_not_modified` / `_send_not_modified`）**
- [x] 错误处理矩阵（400/404/503/200-error/200-值域/304 + hotplate 全/部分分区）+ 降级分层 + **8 条**可断言不变式（★ v1.5 新增 #8）
- [x] 并发安全：锁清单 + 锁序（`_feed_fetch_locks_lock → per-键 lock`，★ v1.10 / F8 经 `feed_fetch_acquire/release`；metrics 永远最内层）+ 热点开销 + 并发正确性依据；★ v1.5：条件请求**零新锁**；★ v1.10：锁表有界（BR-SRV-50）
- [x] 测试要点 **75 条**映射 PRD AC（v1.1 新增 T34/T35；v1.2 新增 T36–T43；v1.4 新增 T44–T45；v1.5 新增 T46–T60；v1.6 / C7 补 `T52b`/`T56b`/`T61`/`T62` → 64 条；**★ v1.9 / F7 新增 `T63..T70` → 72 条，并改写 `T55`**；**★ v1.10 / F8 新增 `T71`/`T72` → 74 条**；**★ v1.12 新增 `T73`（并发在飞 K 键上界 + 两表同步）→ 75 条，并改写 `T71`（纯串行，编号不删）**）；回归用例逐条列名（含 **2 条**跨模块交叉引用必改 + **★ v1.8 5 条 server_http 打桩迁移** + **★ v1.9 / F1–F5 5 条打桩/契约迁移**，见 §10.1）
- [x] AC 追溯：S1/A5/A8/A9/**E2**/E8/E9/S4/S5/S7/S8/S10 主承载，A3/E6/A6 协同项已注明；**v1.2 增 S2-5/S2-3/P1-6；★ v1.5 增 本专项 R1**
- [x] 与基础层/数据层接口逐项对齐（`cache_policy`/`feed_cache_get|put`/★ **`feed_cache_get_entry`**/`build_batch_response`/`page_data`/`restart_window_snapshot`/`watchdog_restart_skip_reason`/`metrics`）
- [x] 偏差 **45 项**全部登记（**不改 SAD / 不改 PRD / 不改 config.md**；★ v1.5 新增 #32–#37；**★ v1.9 新增 #38–#43**；**★ v1.10 / F8 新增 #44**；**★ v1.12 新增 #45**）
- [x] **v1.4**：gzip 协商 `_accepts_gzip` + `Vary: Accept-Encoding`（BR-SRV-34 / §1.1#11 / §5.8 / §6.2#7 / T44）；`main()` 预热 `warm_transport`（BR-SRV-35 / §1.1#12 / §5.9 / T45）；线程账 +9
- [x] **v1.5（P3a · RSS 条件请求）**：ETag 弱校验器（规范化剔除 `lastBuildDate`/`ttl`，**严禁裸哈希**）· Last-Modified = 缓存条目 `time`（新访问器 `feed_cache_get_entry`）· 304 组成（无 body/无 `Content-Encoding`/无 `Content-Length`，带 `ETag`+`Cache-Control`+`Vary`，不写缓存）· 条件头优先级（INM > IMS，支持 `*`/多值/`W/`，非法日期头忽略）· RSS `<ttl>`（分钟，位置与 ETag 影响）· 出范围项（BR-SRV-36..44 / §5.4 / §5.8 头清单 / §6.2#8 / T46–T60 / §10#32–#37 / §11.5）
- [x] **v1.5（只增不改核对）**：200 既有头与体、`Vary`/`private` 反投毒、业务降级恒 200、路由/方法、`feed_cache_get` 签名**全部未变**；新增仅 2 个可选形参 + 1 个方法 + 1 个访问器 + 1 个 `generate_rss` 可选形参
- [x] **v1.9（P8 对抗性盲审 F1–F7 契约化 · 编排层裁定）**：**F1** `Last-Modified` = 表示最后一次变更时刻（feed 条目 `fingerprint`/`last_modified`；跨 TTL 指纹继承；不变式 `ETag 变 ⟺ Last-Modified 前进`；否决 `max(pubDate)`）→ BR-SRV-38 改写 + BR-CACHE-33；**F2** feed 缓存键含 `base_url`（`_feed_cache_key`；与 `Vary` 同语义；放大风险论证）→ BR-SRV-45；**F3** `http_304_total`（`_send_not_modified` 单点）→ BR-SRV-46 + `metrics.md` v1.4；**F4** feed `max-age` authority = `feed`（数值不变）+ 一致性不变式 → BR-SRV-47；**F5** `feed_cache_put` 返回写入条目 / miss 无二次查询 → BR-SRV-48 + BR-CACHE-34；**F6** HTTP/1.0 304 EOF/不发 `Content-Length`（仅文档化）→ BR-SRV-49 + §10#36；**F7** 新增 `SRV-T63..T70` 8 条 + 改写 `T55`（测试 64→**72**）。**未改代码 / SAD / PRD / API.md / README.md / `.opencode`；`cache.md` → v1.8、`metrics.md` → v1.4、`_PROGRESS.md` 同步**
- [x] **v1.10（P8 F8 契约化 · feed 取数锁表有界收敛）**：**F8** `_get_or_fetch_feed` 改经 `feed_fetch_acquire/release`（`try…finally`）+ 引用计数归零即回收 ⇒ BR-SRV-50（不变式 / 正确性论证 / 有界性 / 运营缓解）；**BR-SRV-45 补正**放大风险论证（原论证只覆盖上游、未覆盖锁表内存与本地生成）；§2.10 import 面替换；§3.3/§5.4/§7.1·7.2/§6.2#8⑬/§9/§10#44 同步；新增 **`SRV-T71`/`SRV-T72`**（测试 **72 → 74**）。**未改代码 / SAD / PRD / API.md / README.md / `.opencode`；`cache.md` → v1.9、`metrics.md` → v1.5、`_PROGRESS.md` 同步**
- [x] **v1.11（P2-1 fail-safe 措辞收口 + 溯源更正）**：消费 `cache.md` v1.10 — `feed_cache_get_entry` 以 `entry.get('last_modified')` 读取 ⇒ legacy / 非六字段条目 `last_modified=None` ⇒ **不发 `Last-Modified`、禁用 IMS**（`If-None-Match` 仍按 ETag），**不抛 `KeyError` 经 `_guard` 变降级体**；落点 §2.5 访问器契约注 + BR-SRV-38（**措辞收口，BR 语义不变**）；头部溯源 **SAD v1.7 → v1.9 / PRD v0.6 → v0.8**；接口权威栏 + 文末 `cache.md` → **v1.10**。**测试计数不变（74 条）**；**未改代码 / SAD / PRD / API.md / README.md / `.opencode`；`cache.md` → v1.10、`_PROGRESS.md` 同步**
- [x] **v1.12（F8 并发变体测试契约 + `acquire` 实现约束）**：**P2-2** 把"并发 K 个不同 Host 同时在飞"从 `SRV-T71` 附注提升为**独立可测用例 `SRV-T73`**（阻塞式取数桩 + `threading.Event` 同步、不用 `sleep`；在飞期间 `1 <= len(_feed_fetch_locks) <= K` **且两表相等**，返回后均 `0`；证伪：`release` 不在 `finally` / 两表不同步 / 按累计增长 ⇒ 红）；`SRV-T71` 收敛为**纯串行**（编号不删）；**微优化实现约束**——`feed_fetch_acquire` **先 `get` 判空、仅未命中建 `Lock`**（命中路径零分配，语义不变）写入 BR-SRV-50（`cache.md` BR-CACHE-35 同步）；§2.5/§8/§9/§10#45 同步；接口权威栏 `config.md` → v1.5、`cache.md` → **v1.11**。**未改代码 / SAD / PRD / API.md / README.md / `.opencode`；`cache.md` → v1.11、`config.md` → v1.5、`_PROGRESS.md` 同步**
- [x] **v1.13（最后一轮契约收口）**：**P2-4** 收窄 `SRV-T73` 证伪面——取数桩**从不抛异常** ⇒ **不能**证伪"`release` 不在 `finally`"（该变异归 **`SRV-T72`** 异常路径计数归零）；`T73` 证伪面 = **「按累计增长 / 两表不同步 / 上界 > K」**，**「两表相等 + 在飞上界 + 归零」三条断言不变**；**P2-5** `SRV-T73` 增**超时余量（建议 ≥10s**，原 5s 伪红风险）与 `join` 后 **`assertFalse(t.is_alive())`** 收尾证据；§8 表后注 + §9 + §10#45 同步；接口权威栏 `cache.md` → **v1.12**。**测试计数不变（75 条）**；**未改代码 / SAD / PRD / API.md / README.md / `.opencode`；`cache.md` → v1.12、`_PROGRESS.md` 同步**
- [x] **v1.14（实现事实对齐 + 溯源更正）**：头部溯源 **SAD v1.9 → v1.11 / PRD v0.8 → v0.9**（**最后一处溯源滞后闭环**，与 `config.md` v1.5 / `cache.md` v1.13 一致）；`SRV-T73` 实现对齐——超时余量实测 **15s**（≥ v1.13 建议 10s）+ `join` 后 `assertFalse(t.is_alive())`、在飞 `1 <= 两表 <= K`（K=8）且两表相等、返回后归零、`calls == K`；接口权威栏 `cache.md` → **v1.13**、`metrics.md` → **v1.6**。**无 BR 语义变更 / 无接口变更；测试仍 75、偏差仍 45**；**未改代码 / SAD / PRD / API.md / README.md / `.opencode`；`cache.md` → v1.13、`metrics.md` → v1.6、`_PROGRESS.md` 同步**
- [x] **v1.6（P3a-r1 评审定向修 · 对照 `REV-DES-20260918-001`）**：**C1** ETag canonical 投影扩展 item 级 `<pubDate>`（全量）+ 双向不变式 + 取舍（BR-SRV-37 / §2.9 / §5.4 / §6.2#8③⑦ / §10#32）；**C2** §10.1 打桩迁移第 4 条 `h.headers = {}` + §11 计数 4；**C3** `<ttl>` 契约语句 + 推荐轮询 ≥30s + SSE（BR-SRV-43 / §5.8）；**C4** `dt.timestamp()` 入 try + `OSError`（BR-SRV-40 / §5.4 / §6.2#8⑤）；**C5** BR-SRV-39 弱前缀大小写敏感措辞；**C6** §10#36 补 RFC 9110 §8.6 + HTTP/1.0/EOF 依据；**C7** 14 条缺失用例（新增 T52b/T56b/T61/T62，测试 60→**64**）+ `generate_rss` `ttl>0` 护栏；**C8** 漂移 8 项入 `_PROGRESS.md` 契约影响。**未改代码 / SAD / PRD / API.md / README.md / `.opencode`**
- [x] **v1.3（N1 回退）**：业务端点降级 = `200 + error 体`（§1.1#9 / §2.1 yaml + 状态表 / §2.2 `_send_json_shape` / §2.9 `_json_payload_has_data` 删除 / §2.10 / §4.1 BR-SRV-5b / §5.2 注 + §5.8 伪代码 / §6.1 / §9 / §10#18·#24·#29 / §11.3）；`_send_json` 无 `status`；`http_503_total` 计数点 3；降级体可缓存
- [x] **v1.3（N1 回退）**：`/healthz` 的 503 明确为**端点自身语义**（BR-SRV-21 / §5.2 / §6.1 / §9 / §10#29），不构成业务端点先例

### 11.1 v1.2 契约同步对照（P7b · 以代码为准）

| # | 同步项 | 落点 | 与 v1.1 的差异 |
|---|--------|------|---------------|
| 1 | ~~error-only payload ⇒ 503~~（**★ v1.3 / N1 已回退**：业务端点降级恒 200；`_json_payload_has_data` 删除。见 §11.3 / §10#29） | §1.1#9 / §2.1 / §2.2 / §4.1 BR-SRV-5b / §5.2·5.8 / §6.1 / T36 | v1.1：一律 200 → v1.2 改 503 → **v1.3 回退为 200** |
| 2 | `/healthz` 缺 `status`/含 `error` ⇒ 503 + `http_503_total` | §1.1#7 / §2.1 / §3.1 / §5.2 / T37 | v1.1：仅 `degraded` ⇒ 503 |
| 3 | `_HealthBatch.settle()` + 先建账再调用 + `except BaseException` | §2.6 / §2.6.1 / §3.2 / §5.6 / §7.1 | v1.1：无 settle（异常路径泄漏准入位） |
| 4 | `_run_health_checks(base_url, batch=None)` + 等待中 `fut.result()` 不上抛 | §2.6.1 / §5.6 | v1.1：无 batch 形参 |
| 5 | `_FANOUT_WAIT_BUDGET=REQUEST_TIMEOUT` 界定扇出 | §1.1#7′ / §2.9 / §5.5 / §6.2#6 / T35 | v1.1：无界 `fut.result()` |
| 6 | `_base_url()` Host 校验 + `private`/`Vary`（`_send_text(varies_on_host=…)`） | §2.10（`_send_text`）/ §4.6 BR-SRV-33 / §5.8 / §5.8 表 / T42 | v1.1：直接取 Host；`public` 缓存 |
| 7 | `_cache_age()` 用 `urlparse(self.path).path` | §4.2 BR-SRV-8 / §5.8 / T43 | v1.1：`split('?')[0]` |
| 8 | 4 面板 cache-age 域 = `quote`（8/120） | §3.3 `_CACHE_AGE_DOMAINS` / §4.2 BR-SRV-8b / §5.8 表 / §10#22 | v1.1：`f10`（300） |
| 9 | 码归一 `_parse_stock_codes` + `_rekey_batch_response` | §1.1#10 / §2.4 / §5.3 / §6.1 / T39·T40 | v1.1：仅 strip/split，原样传 |
| 10 | `/market/margin` 非法 market ⇒ 400（`VALID_MARKETS`） | §2.1 / §4.1 BR-SRV-5c / §5.2 / T38 | v1.1：无校验 |
| 11 | `_PANEL_HANDLERS` + `_JSON_DISPATCHED_PATHS` 导入期断言 | §2.2 / §5.2 | v1.1：无 |
| 12 | ~~`_send_json(data, write_body, cache, status=200)`~~（**★ v1.3 / N1**：去 `status`，恒 200） | §2.10 / §5.8 | v1.1：无 `status` → v1.2 增 → **v1.3 撤销** |
| 13 | `do_GET`/`do_HEAD` 断连捕获扩为 `OSError` | §2.3 / §5 | v1.1：`BrokenPipe/ConnectionReset` |
| 14 | `BoundedThreadPoolServer.request_queue_size = LISTEN_BACKLOG` | §2.7 / §3.4 / §5.7 / §10#25 | v1.1：无 |
| 15 | longhu `broker_idx` 无条件自增 + 错位告警；encoding 取自 policy | §4.6 BR-SRV-32 / §5.5 / §10#27 / T41 | v1.1：解析细节未钉死、encoding 字面量 |
| 16 | import 面更正（+page_data/FetchError/LISTEN_BACKLOG/VALID_MARKETS；−handle_cls_stock/fetch_cls_*/strip_html/escape_xml） | §2.10 / §10#28 | v1.1：清单不完整 |

### 11.2 v1.1 修订对照（闭环 REV-DES-20260915-002）

| 评审项 | 落点 | 处理 |
|--------|------|------|
| **P1-1** healthz 准入位早释放 / 无界队列 | §2.6 / §2.6.1 / §3.2 / §4.5 BR-SRV-19·20 / §5.6 `_HealthBatch` / §6.2#4 / §7.1·7.2·7.5 / §8 T20·T21·T34 / §10#16 | 新增 `_HealthBatch`（future 完成回调驱动释放）⇒ 在飞任务 ≤25、执行器队列 ≤20；§2.6 断言与伪代码一致；补"持续慢 check 下队列不增长"断言 |
| **P1-2** 外部上游串行越 AC-E2 | §1.1 / §2.8·2.9 / §4.6 BR-SRV-30 / §5.5 `_fetch_concurrent` / §6.2#6 / §8 T13·T35 / §9 / §10#10·#15 | hotplate/plate/longhu 改 ≤3 并发（共享 `fanout` 池）；单端点 = `max` 而非 `sum` ⇒ ≤10s ≤15s；登记归属**更正为 AC-E2**；补 E2 落点与测试 |
| **P1-3** hotplate 全失败缺顶层 `error` | §2.8 / §4.6 BR-SRV-31 / §5.5 / §6.1 / §8 T14 / §9 | 三分区全失败 ⇒ **顶层补 `error`**（SAD §2.3 D-4 口径）；T14 断言同步 |
| **P1-4** 流端口 inflight 40 使 100 连接失效 | §1.5 / §2.7 / §3.4 / §5.7 / §10#11 | `__init__` 增 `max_inflight` 形参；流端口显式传 110（≥ `MAX_STREAM_CONNS`+10）⇒ AC-E5/E7 可复现 |
| **P2-1** §5.4 vs §7.4 ttl 求值点矛盾 | §2.5 / §5.4 / §7.4 | `ttl` 移到**二次 get 仍 miss 后**求值；唯一表述 |
| **P2-2** 10s 整体预算成死代码 | §2.6.1 / §3.2 / §4.5 BR-SRV-20 / §5.6 / §8 T21 | 每源按各自 `submitted_at` 独立 3s；整体 10s 独立闸（可测） |
| **P2-3** `feeds[].status` 注释过宽 | §3.1 | 限定为"仅 5 个 RSS 源被覆盖"；10 个 JSON/CDP 条目保持原值 |
| **P2-4** 分组视图 `object（8）` 计数错 | §2.2 | 改为 `object（7，表内）`+ 明示 `/healthz` **不入表**（否则 `assert len==14` 失败） |
| **P2-5** import 清单不完整 | §2.10 | 改为**完整 import 块**（可整体替换）：补删 `Request,urlopen` / `random`；补 `main()` 所需的 `stock_api` 4 prefetch loop、`market_api`、`utils` |
| **编排层裁决** handler 返回组装 dict | §10#17 | 批准；SAD 措辞由 system-architect 回改（不在本 agent 范围） |

### 11.3 v1.3 收尾同步对照（N1 回退 · 以代码为准）

| # | 同步项 | 落点 | 与 v1.2 的差异 |
|---|--------|------|---------------|
| 1 | 业务端点降级体 **恒 200**（`_send_json_shape` 无 503 分支） | §1.1#9 / §2.1（yaml + 状态表）/ §2.2 / §4.1 BR-SRV-5b / §5.8 / §6.1 / §9 / §10#18·#29 | v1.2：error-only ⇒ 503 |
| 2 | **`_json_payload_has_data` 已删除** | §2.9（删除标注）/ §5.8 / §10#24 | v1.2：`_send_json_shape` 的判定入口 |
| 3 | **`_send_json(data, write_body, cache)` 无 `status`** | §2.10 / §5.8 | v1.2：`status=200` 形参 |
| 4 | **`http_503_total` 计数点 4→3**（`_reject_503` / `stream._serve_sse` / `/healthz`） | §1.1#9 / §2.1 状态表 / §6.1 / §10#29 | v1.2：多 `_send_json_shape` 一处 |
| 5 | 降级体**可缓存**：`cache=cache`（按域 TTL；v1.2 的"503 ⇒ 不缓存"消失） | §2.2 / §4.1 BR-SRV-5b / §6.1 / §11.3#1 | v1.2：`cache=cache and status==200` |
| 6 | `/healthz` 503 定位为**端点自身语义**（非业务端点先例） | BR-SRV-21 / §5.2 / §6.1 / §9 / §10#29 | v1.2：未区分端点归属 |
| 7 | 测试 `SRV-T36` 语义反转（error-only ⇒ **200**，`http_503_total` **不增**） | §8 T36 | v1.2：断言 503 |

### 11.4 v1.4 契约同步对照（响应 gzip + 启动预热 · 以代码为准）

| # | 同步项 | 落点 | 与 v1.3 的差异 |
|---|--------|------|---------------|
| 1 | `_accepts_gzip(header)` 按 RFC 9110 §12.5.3 解析 `Accept-Encoding`（`gzip;q=0` 拒绝、`GZIP`/`*` 接受） | §1.1#11 / §4.6 BR-SRV-34 / §5.8 / §6.2#7 / §8 T44 / §10#30 | v1.3：无（响应恒不压缩） |
| 2 | `_send_text` 对 `len(body) >= GZIP_MIN_BYTES(1024)` 且被接受的响应 `gzip.compress(level=1)` + `Content-Encoding: gzip` | §5.8 / §1.3（`import gzip`） | v1.3：无 |
| 3 | **`Vary: Accept-Encoding` 在 `gzipped or cache` 时无条件发**（含 `cache=False` 的 gzip 响应） | §5.8 / §6.2#7 | v1.3：仅 `varies_on_host` 时发 `_BASE_URL_VARY` |
| 4 | `main()` 新增 daemon 线程 `warm_transport`（预热上游传输；不阻塞启动/`/healthz`，失败静默） | §1.1#12 / §4.6 BR-SRV-35 / §5.9 / §2.9 线程账 / §8 T45 / §10#31 / §1.3·§2.10 import | v1.3：main() 3 处改动，无预热线程 |

### 11.5 v1.5 增量设计对照（P3a · RSS 条件请求 · 只增不改）

| # | 增量项 | 落点 | 与 v1.4 的差异 |
|---|--------|------|---------------|
| 1 | **弱 ETag** `W/"<sha256>"`，规范化剔除 `<lastBuildDate>` / `<ttl>` / **`<pubDate>`（★ v1.6 / C1 全量）** 内容（**严禁裸 body 哈希**） | §1.1#13 / §4.7 BR-SRV-37 / §5.4 `_feed_etag` / §2.9 常量 / §8 T46·T52·T52b·T53 / §10#32 | v1.4：RSS 无 `ETag`；★ v1.6：扩 item 级 `pubDate` |
| 2 | **Last-Modified** = feed 条目 `last_modified`（★ v1.9 / F1：表示最后一次变更时刻，由 `fingerprint` 跨 TTL 继承；v1.5–v1.8 的「写入时刻 `time`」已作废）；新访问器 `cache.feed_cache_get_entry(path) -> dict\|None`（**`feed_cache_get` 签名不变**） | §1.5 / §2.5·§2.5a / §4.7 BR-SRV-38 / §2.10 / `cache.md` §2.4·BR-CACHE-32/33 / §8 T46·T60·T63·T64 | v1.4：`_get_or_fetch_feed` 返回 `str`，无时间源 |
| 3 | **304**：专用 `_send_not_modified`（无 body / 无 `Content-Encoding` / 无 `Content-Length`；带 `ETag`+`Cache-Control`+`Vary`；不写缓存；`HEAD` 同） | §2.1 / §2.1 状态表 / §4.7 BR-SRV-41 / §5.8 头清单 / §6.2#8 / §8 T47·T54·T55·T57 / §10#35·#36 | v1.4：无 304 路径 |
| 4 | **条件头**：`If-None-Match` 优先于 `If-Modified-Since`；`*`/多值/`W/` 弱比较；IMS `parsedate_to_datetime` 秒级、非法忽略 | §4.7 BR-SRV-39·40 / §5.4 判定函数 / §8 T48–T51·T56 | v1.4：忽略一切条件头 |
| 5 | **200 加校验器**：`_send_text(..., etag=None, last_modified=None)`（纯新增可选形参；其余调用点零改动） | §2.10 / §4.7 BR-SRV-42 / §5.8 头清单 / §8 T46 | v1.4：无 `ETag`/`Last-Modified` |
| 6 | **RSS `<ttl>`**（分钟）：`generate_rss(..., ttl=None)`；5 个 handler（**6 处调用点**——eastmoney 常规 + 空 feed 两个出口；★ v1.8 / D-2）传 `_feed_ttl_minutes()`（30→1 / 180→3），位置在 `</lastBuildDate>` 与 `<atom:link>` 间，**剔除出 ETag** | §1.1#13 / §2.10 / §4.7 BR-SRV-43 / §8 T58 / §10#33 | v1.4：无 `<ttl>` |
| 7 | **出范围（仅登记）**：HTTP/1.1 keep-alive、`/opml.xml`、`/` 条件请求 | §4.7 BR-SRV-44 / §10#37 | v1.4：未涉及 |
| 8 | import 面：+`hashlib` / `datetime.timezone` / `parsedate_to_datetime`；cache 侧 `feed_cache_get` → `feed_cache_get_entry` | §1.3 / §2.10 import 块 / §10#32·#34 | v1.4：无这些名字 |

### 10.1 既有测试的必改清单（供 code-developer / tester 依此同步）

| 测试 | 现状 | 必改点 | 理由 |
|------|------|-------|------|
| `test_server.py::test_handle_cls_hotplate_*` | 直接调用、依赖网络 | **无需改**（成功路径 keys/`hot_plates` 结构不变）★ 注意：若 CI 断网导致三分区全失败，新口径会**多出顶层 `error`**（BR-SRV-31）——断言若用精确键集合需允许该键 | ① 断网下的 key-set 断言属既有 mock 缺口（现状问题，非本次引入）；② 新增顶层 `error` 是 SAD §2.3 D-4 的**必须**口径 |
| `test_server.py::test_healthz_payload_includes_hotplate_endpoint` / `test_healthz_includes_market_endpoints` | 断言 path 存在 | **无需改**（feeds 条目集合不变） | 只增字段 |
| `test_server.py::test_fetch_json_leader_failure_does_not_stampede` | 断言 `err=1`/`ok=7` | **必改**（AR-10：`err=8`/`max_active=1`/负缓存窗口内 <1ms） | 属 `cache.md` T-CACHE-2（**已在 cache.md 登记**，非 server 范围，此处交叉引用） |
| `test_server.py::test_sector_cache_bounded` | import `_SECTOR_CACHE_MAX` | **必改**（`stock_api.md` §10#4 删该常量，改 `cache_policy('sector')['cache_max']`） | 属 `stock_api.md` 登记范围（交叉引用） |
| **`test_server_http.py::FeedDoubleCheckTests`（2 条；:315 / :331）★ 迁移第 1、2 条** | patch `srv.feed_cache_get` 为返回 xml 的 lambda | ★ v1.5 **必改**：打桩目标改为 **`srv.feed_cache_get_entry`**，返回 `{'xml': ..., 'time': <float>, 'last_access': ..., 'expires_at': ...}` 或 `None`；断言"回源 1 次"不变。★ **v1.7 / P2-c（若不写会红）**：**返回值断言须改 2-tuple**——`_get_or_fetch_feed` 现返回 `(xml, last_modified)` ⇒ 直接调用处 `assertEqual(h._get_or_fetch_feed(...), '<rss/>')`（`tests/test_server_http.py:327-328`）与 `worker()` 内调用（`:346`）须改为元组 `('<rss/>', <stub 条目的 `time`>)` | `_get_or_fetch_feed` 改用 `feed_cache_get_entry` 且返回 2-tuple（§2.5/§2.5a/§10#34）；旧打桩不再被调用 ⇒ 否则"回源 1 次"退化为 2 次而失败；**返回值形状不变则为断言失败（照 v1.5 清单施工会红）** |
| **`test_server_http.py::BaseUrlHardeningTests::test_serve_feed_marks_host_derived_url_non_public`（:440 / :450）★ 迁移第 3 条**（★ v1.7 / P2-d：2-tuple 变更同施于 `:450`，与第 4 条口径一致） | patch `srv.RSSHandler._get_or_fetch_feed` 返回 `'<rss/>'` | ★ v1.5 **必改**：返回值改 **`('<rss/>', None)`**（2-tuple）；`_send_text`/`_send_not_modified` 打桩仍可捕获 kwargs（新增 `etag`/`last_modified`） | `_guard(shape='rss')` 现返回 2-tuple（§5.1/§10#34） |
| **`test_server_http.py::BaseUrlHardeningTests`（:440 / :450）★ 迁移第 4 条（★ v1.6 / C2 / P1-02 补登）** | 两方法用 `RSSHandler.__new__(RSSHandler)` 构建，**未设 `h.headers`** | ★ v1.6 **必改（第 4 条）**：**补 `h.headers = {}`**（或 `patch.object(srv.RSSHandler, '_not_modified', return_value=False)`）；否则即便按第 3 条把 `_get_or_fetch_feed` 改成 2-tuple，`_serve_feed` 仍会读 `self.headers` ⇒ **`AttributeError`（用例报错，非断言失败）** | `_serve_feed` 自 v1.5 起在 `_send_text` **之前**执行 `_not_modified(self.headers, …)`（§5.4 / BR-SRV-36..41）。**这是 v1.5 §10.1 唯一漏项**（v1.5 只写了 2-tuple + kwargs） |
| **`test_server_http.py::GuardTests::test_rss_degrade_is_valid_feed`（:80）★ 迁移第 5 条（★ v1.8 / D-1 补登）** | 直接调用 `srv._guard(self._boom, shape='rss', …)` 并把**返回值当 XML**（旧形状 = 裸 `str`） | ★ **必改（第 5 条）**：按 2-tuple **解包 + 断言降级体无 `Last-Modified`**——`xml, last_modified = srv._guard(self._boom, shape='rss', rss_info=…, feed_url=…)`；`ET.fromstring(xml)`；`self.assertIsNone(last_modified)`。**照 v1.7 清单施工必红**：`ET.fromstring(tuple)` ⇒ `TypeError`；且不解包就拿不到 `last_modified`，无从断言「降级 ⇒ IMS 不可评估」 | `_guard(shape='rss')` 自 v1.5 起**成功/异常两路同 2-tuple**（§2.3 / §5.1 / §10#34）。本用例是**唯一绕过 `_serve_feed` 直接调 `_guard(shape='rss')`** 的存量用例，v1.5/v1.6/v1.7 的迁移清单**均漏列** ⇒ **实现阶段已按详设裁定机械迁移**（解包 + `last_modified is None`），本版补登使文档与实现一致 |
| **`test_server.py` 中任何断言 `generate_rss` 输出的用例** | 无 `<ttl>` | ★ v1.5：**无需改**（`ttl=None` 默认不输出）；仅新增用例传 `ttl=` | 向后兼容（§2.10 / BR-SRV-43） |
| **`test_server_http.py::FeedDoubleCheckTests`（2 方法）★ v1.9 / F1+F5 迁移** | `feed_cache_get_entry` 桩返回 `{'xml', 'time'}`（无 `last_modified`）；`feed_cache_put` 桩签名为 `lambda p, xml, ttl`，返回 `None` | ★ **必改**：① `feed_cache_get_entry` 桩返回**六字段**（补 `last_modified`/`fingerprint`）；② `feed_cache_put` 桩接受 **`fingerprint=`** 关键字并**返回**条目 dict（含 `last_modified`）——否则 `_get_or_fetch_feed` 读 `entry['last_modified']` 时 `TypeError`（`NoneType`/缺键）；③ 返回值断言改 `('<rss/>', <桩条目 last_modified>)` | `_get_or_fetch_feed` 现读 `entry['last_modified']`（F1）并直接消费 `feed_cache_put` 的返回值（F5）（§2.5 / §5.4 / BR-SRV-38/48） |
| **`test_server_http.py::test_t46` / `test_t47` 的 `counting_put`** ★ v1.9 / F5 迁移 | `def counting_put(path, xml, ttl):` | ★ **必改**：签名改 `counting_put(path, xml, ttl, fingerprint=None)` 并原样转交 `real_put(..., fingerprint=fingerprint)`；否则 server 传 `fingerprint=` 时 `TypeError` | `feed_cache_put` 新增第 4 位 `fingerprint`（BR-CACHE-34） |
| **`test_server_http.py::test_t55`** ★ v1.9 / F2+F7#8 迁移 | 依赖 **path 键缓存旧表示** 才在 `PUBLIC_BASE_URL` 切换后仍得 304（P1-2 的伪绿） | ★ **必改**：F2 后该路径失效 ⇒ 按 §8 `SRV-T55` 改写为**自造陈旧条目**（不依赖时序）+ 独立头组合断言（配合 `SRV-T67`） | `_feed_cache_key` 含 `base_url`（BR-SRV-45）；旧断言掩盖 P1-2 |
| **`tests/test_cache.py::FeedEntryAccessorTests`（`test_srv_t60_feed_cache_get_entry_contract` / `test_t_cache_32_shallow_copy_isolates_the_container`）** ★ v1.9 / F1+F5 迁移 | 断言 `entry == {'xml','time','last_access','expires_at'}`（四字段）；`feed_cache_put(path, xml, ttl)` | ★ **必改**：条目断言扩为**六字段**（补 `last_modified`/`fingerprint`）；浅拷贝负例同步四→六字段；`feed_cache_put` 默认 `fingerprint=None` 时 `last_modified == time`（写入时刻），显式传相同 `fingerprint`（即使条目过期）⇒ 继承上一 `last_modified` | BR-CACHE-32/33/34 |
| **`test_server_http.py::CacheAgeTests` 中 RSS 域断言（`SRV-T11` 等）** ★ v1.9 / F4 迁移 | 断言 `_cache_age()` 对 RSS 路径 == `cache_policy('news_url')['ttl']` | ★ **必改**：改断言 == `cache_policy('feed')['ttl']` | `_CACHE_AGE_DOMAINS` 5 feed path 由 `news_url` 改 `feed`（BR-SRV-47） |
| 新增 | — | `SRV-T*` **19 条**（T46–T60 + ★ v1.6：`T52b`/`T56b`/`T61`/`T62`）**+ ★ v1.9 新增 `T63..T70`（8 条）+ ★ v1.10 新增 `T71`/`T72`（2 条）+ ★ v1.12 新增 `T73`（1 条，并发在飞 K 键上界 + 两表同步；`T71` 改写为纯串行、编号不删）** | 本详设 §8 |

> **★ v1.6 / C2 迁移清单计数口径（P1-02 闭环；★ v1.8 / D-1 由 4 → 5）**：`test_server_http.py` 的**打桩迁移共 5 条**，逐条为——**①** `FeedDoubleCheckTests:315` 打桩目标 `feed_cache_get` → `feed_cache_get_entry`；**②** `FeedDoubleCheckTests:331` 同上；**③** `BaseUrlHardeningTests`（2 方法）`_get_or_fetch_feed` 桩返回 2-tuple `('<rss/>', None)`；**④** `BaseUrlHardeningTests`（2 方法）**补 `h.headers = {}`**（或 patch `_not_modified`）；**⑤** `GuardTests::test_rss_degrade_is_valid_feed`（:80）**直接调 `_guard(shape='rss')` 须按 2-tuple 解包 + 断言 `last_modified is None`**（★ v1.8 / D-1 补登——v1.5 §11 自检的"三条"与 v1.6 的"4 条"**均漏列**该唯一绕过 `_serve_feed` 直接调 `_guard` 的存量用例）。综合口径：**本版更正为 5 条**（见 §11）。

> 本文档与 `config.md` **v1.5** / `cache.md` **v1.13** / `metrics.md` **v1.6** / `stock_api.md` v1.3 / `market_api.md` v1.3 / `cdp_engine.md` v1.2 / `stream.md` v1.3 共同构成 P6c 优化专项的模块级详设；**server.py 的编码可与 stream.md 并行**（二者无共享文件的写冲突：server 仅延迟 import stream 的 `push_loop`/`run_stream_server`）。
>
> **v1.13 修订（最后一轮契约收口 · 收窄 `SRV-T73` 证伪面 + 超时余量 · 只改文档，不改代码）**：**P2-4** `T73` 的取数桩从不抛异常 ⇒ **不能**证伪"`release` 不在 `finally`"（归 **`SRV-T72`** 异常路径计数归零）；`T73` 证伪面收窄为 **「按累计增长 / 两表（`_feed_fetch_locks` 与 `_feed_fetch_refs`）不同步 / 上界 > K」**，其 **「两表相等 + 在飞上界 + 归零」三条断言不变**；**P2-5** 等待放行 / `join` 超时**建议 ≥10s**（原 5s 在极端调度下有**伪红**风险）并在 `join` 后 `assertFalse(t.is_alive())`。§8 表后注 / §9 / §10#45 同步；接口权威栏 `cache.md` → **v1.12**；测试计数仍 **75**（`T73` 改写、不新增编号）。**未改代码 / SAD / PRD / API.md / README.md / `.opencode`；`cache.md` → v1.12、`_PROGRESS.md` 同步。**
> **v1.14 修订（实现事实对齐 + 溯源更正 · 只改文档，不改代码）**：头部上游 **SAD v1.9 → v1.11 / PRD v0.8 → v0.9**（**最后一处溯源滞后闭环**，与 `config.md` v1.5 / `cache.md` v1.13 一致）；`SRV-T73` 实现对齐——等待放行 / `join` 超时实测 **15s**（≥ v1.13 建议的 10s）+ `join` 后逐线程 `assertFalse(t.is_alive())`，在飞 `1 <= 两表 <= K`（K=8）且两表相等、返回后两表归零、`calls == K`；接口权威栏 `cache.md` → **v1.13**、`metrics.md` → **v1.6**。**无 BR 语义变更 / 无接口变更；测试仍 75、偏差仍 45**；**未改代码 / SAD / PRD / API.md / README.md / `.opencode`；`cache.md` → v1.13、`metrics.md` → v1.6、`_PROGRESS.md` 同步。**
>
> **v1.12 修订（F8 并发变体测试契约 + `acquire` 实现约束）**：**P2-2** 新增独立可测用例 **`SRV-T73`**（K 个不同 Host 键**同时在飞**，阻塞式取数桩 + `threading.Event` 同步、不用 `sleep`；断言在飞期间 `1 <= len(_feed_fetch_locks) <= K` **且两表相等**，全部返回后两表均 `0`），`SRV-T71` 收敛为**纯串行**（编号不删）；**微优化实现约束**写入 **BR-SRV-50**——`feed_fetch_acquire` **先 `get` 判空、仅未命中建 `Lock`**（命中路径零分配，语义不变；`cache.md` BR-CACHE-35 同步）；接口权威栏 `config.md` → **v1.5**、`cache.md` → **v1.11**；§2.5/§6.2#8⑬/§7/§8/§9/§10#45/§11 同步；测试 **74 → 75 条**，偏差 **44 → 45 项**。**未改代码 / SAD / PRD / API.md / README.md / `.opencode`；`cache.md` → v1.11、`config.md` → v1.5、`_PROGRESS.md` 同步。**
>
> **v1.11 修订（P2-1 fail-safe 措辞收口 + 溯源更正）**：消费 `cache.md` v1.10 的 P2-1 — `feed_cache_get_entry` 以 `entry.get('last_modified')` 读取，legacy / 非六字段条目缺字段 ⇒ `None` ⇒ **不发 `Last-Modified`、IMS 不可评估**（`If-None-Match` 仍按 ETag 评估），**不抛 `KeyError` 经 `_guard` 变降级体**；本版把该 `None` 来源补进 §2.5 访问器契约注 + **BR-SRV-38**（**措辞收口，BR 语义 = 时间源 / 指纹继承 / `ETag 变 ⟺ Last-Modified 前进` 不变式均不变**）。头部溯源更正：**SAD v1.7 → v1.9**、**PRD v0.6 → v0.8**；接口权威栏 `cache.md` → **v1.10**；§11 自检同步。**未改代码 / SAD / PRD / API.md / README.md / `.opencode`；`cache.md` → v1.10、`_PROGRESS.md` 同步。**
>
> **v1.10 修订（P8 F8 契约化 · feed 取数锁表有界收敛）**：**F8** 新增 **BR-SRV-50**（`_get_or_fetch_feed` 经 `feed_fetch_acquire/release` 引用计数回收；不变式 `计数 ≥1 ⇒ 键不可 pop`；正确性论证；有界性 = 并发在飞键数）+ **BR-SRV-45 补正**（原放大风险论证只覆盖上游请求，未覆盖锁表内存与本地生成）；§2.10 import 面由 `_feed_fetch_locks` 改 `feed_fetch_acquire/release`；新增 `SRV-T71`/`SRV-T72`（测试 **72 → 74**）；§10 偏差 **43 → 44 项**（#44）；§6.2#8⑬ / §9 / §11 同步。**未改代码 / SAD / PRD / API.md / README.md / `.opencode`；`cache.md` → v1.9、`metrics.md` → v1.5、`_PROGRESS.md` 同步。**
>
> **v1.9 修订（P8 对抗性盲审 F1–F7 契约化 · 编排层裁定）**：**F1** BR-SRV-38 **改写**（`Last-Modified` = 表示最后一次变更时刻；`fingerprint`/`last_modified`；跨 TTL 指纹继承；不变式 `ETag 变 ⟺ Last-Modified 前进`）+ BR-CACHE-33；**F2** BR-SRV-45（`_feed_cache_key` 含 `base_url`，与 `Vary` 同语义；放大风险论证）；**F3** BR-SRV-46（`http_304_total`，`metrics.md` v1.4 / BR-MET-14）；**F4** BR-SRV-47（feed `max-age` authority 改 `feed`，数值不变）；**F5** BR-SRV-48 + BR-CACHE-34（`feed_cache_put` 返回写入条目、miss 无二次查询）；**F6** BR-SRV-49 + §10#36（HTTP/1.0 304 EOF、不发 `Content-Length`）；**F7** §8 新增 `SRV-T63..T70`（8 条）+ 改写 `T55`（测试 64→**72**）。§10 偏差 **37 → 43 项**（#38–#43）。**未改代码 / SAD / PRD / API.md / README.md / `.opencode`；`cache.md` → v1.8、`metrics.md` → v1.4、`_PROGRESS.md` 同步。**
>
> **v1.8 修订（P7b 漂移回填 D-1/D-2 · 对照 `doc/review/rss-conditional-get_代码评审_专家版.md` CR-RSS-20260918-001 D5）**：**D-1** §10.1 补**第 5 条**迁移（`GuardTests::test_rss_degrade_is_valid_feed`（:80）须按 `_guard(shape='rss')` 的 2-tuple 解包 + 断言 `last_modified is None`）+ **§11 迁移计数 4 → 5**（§10.1 计数口径注 / §11 自检）；**D-2** eastmoney `<ttl>` 口径由「5 处」更正为 **6 处调用点 / 5 个 handler**（`handle_eastmoney_kuaixun` 常规返回 + 「无匹配 ⇒ 空 feed」提前返回两处均传 `ttl=_feed_ttl_minutes()`；BR-SRV-43 / §2.10 / §5.8 / §11.5）；**顺带·P2-3（如实记录）** `_send_text` 与 `_send_not_modified` **各写一份** `Cache-Control`/`Vary`（实现现状，非设计变更）＋ `SRV-T62` 兜底断言关系（§5.8）；**顺带** §8 注明 `SRV-T52b` 实现拆 5 个 unittest 方法、**编号计数不变**。**未改任何设计裁定（BR 编号/算法/取值/优先级/出范围项）、未改代码；`cache.md` 同步 v1.6 → v1.7（D-3）。**
>
> **v1.7 修订（P3a-r2 复审 P2 机械收口 · 对照 `REV-DES-20260918-002`）**：**P2-a** `SRV-T52b` 用例定义细化（必须 patch 时钟 `t`/`t+1` + 红/绿方向声明 + 纯函数「仅 `pubDate` 不同 ⇒ 同 ETag」断言；三门 feed 覆盖不变；未控时钟不得作 C1 验收证据）；**P2-b** BR-SRV-37 第二子句补「除三项外」限定（§6.2#8③ 同步）；**P2-c** §10.1 `FeedDoubleCheckTests` 补返回值断言改 2-tuple；**P2-d** §10.1 第 3 条标题 `:440` → `:440 / :450`；**P2-f** §1.1 标题 11 → **13 条**。**测试计数口径不变**（总 64 / 新增 19 / 迁移 4；★ v1.8 / D-1 更正为 **迁移 5**）。**未改设计裁定/契约/代码；`cache.md` 无 P2 落点，保持 v1.6（★ v1.8 另同步至 v1.7）。**
>
> **v1.6 修订（P3a-r1 评审定向修 · 对照 `REV-DES-20260918-001`）**：**C1** ETag canonical 投影扩展 item 级 `<pubDate>`（全量）+ 双向不变式（BR-SRV-37 / §2.3 / §2.9 / §5.4 / §6.2#8 / §10#32）；**C2** §10.1 迁移第 4 条 `h.headers = {}` + §11 计数 4；**C3** `<ttl>` 契约语句（BR-SRV-43 / §10#33）；**C4** `dt.timestamp()` 入 try（BR-SRV-40 / §5.4）；**C5** BR-SRV-39 弱前缀措辞；**C6** §10#36 依据；**C7** 14 条缺失用例（新增 T52b/T56b/T61/T62）。§10 偏差仍 **37 项**（#32/#33/#36 就地更新，未增号）；测试要点 **60 → 64 条**。**未改代码、未改其他文档（仅本文件 + `cache.md` + `_PROGRESS.md`）**。
>
> **v1.5 增量（P3a · RSS 条件请求）**：见 §11.5 对照表（8 组增量项）；§10 偏差扩至 **37 项**（新增 #32–#37）；测试要点扩至 **60 条**（新增 T46–T60）。**新增仅 2 个可选形参（`_send_text`）+ 1 个方法（`_send_not_modified`）+ 1 个访问器（`feed_cache_get_entry`）+ 1 个 `generate_rss` 可选形参（`ttl`）**；**未改代码、未改其他文档（仅本文件 + `cache.md` + `_PROGRESS.md`）**。
>
> **v1.4 修订**：**P7b 契约同步（响应 gzip + 启动预热 · 以代码为准）**——见 §11.4 对照表（4 组同步项）；§10 偏差扩至 **31 项**（新增 #30/#31）；测试要点扩至 **45 条**（新增 T44/T45）。**未改代码、未改其他文档**。
>
> **v1.3 修订（N1 回退）**：**业务端点降级恢复 `200 + error 体`**——见 §11.3 对照表（7 组同步项）；`_json_payload_has_data` 删除、`_send_json` 去 `status`、`http_503_total` 计数点 3、降级体可缓存；§10 偏差扩至 **29 项**（新增 #29）；测试要点仍 **43 条**（`SRV-T36` 语义反转）。**未改代码、未改其他文档（仅本文件 + `_PROGRESS.md`）**。
>
> **v1.2 修订**：**P7b 契约同步（以代码为准）**——见 §11.1 对照表（16 组同步项；其中 **#1 error-only ⇒ 503 与 #12 `_send_json(status=)` 已由 v1.3 / N1 回退**）；§10 偏差扩至 28 项；测试要点扩至 43 条。**未改代码、未改其他文档**。
>
> **v1.1 修订**：闭环 `doc/review/HTTP-SSE层两模块_详细设计评审_专家版.md`（REV-DES-20260915-002）全部 P1×4 + P2×10；跨模块行为变更（`max_inflight` 形参、handler 返回组装 dict）已按编排层裁决落定。

