# cache.py 详细设计

> **版本** v1.13 · **状态** 增量设计（★ v1.13 实现事实对齐：`_feed_degraded_warned`/`_warn_feed_degraded_once` 写入 BR-CACHE-36（**按原因**去重）+ §10#30 由「登记不修」更正为「已防御」（三处 `isinstance` 守卫）+ `_sweep_expired` 跳过非映射条目 + 溯源 SAD v1.11 / PRD v0.9；P3a · `feed_cache_get_entry`；P3a-r1 评审定向修：扩 **T-CACHE-32** 负例 + 头部溯源修正；P7b 漂移回填：T-CACHE-32 标注已实现；**P8 F1/F5：feed 条目 `fingerprint`/`last_modified` + `feed_cache_put` 返回写入条目**；**P8 F8：feed 取数锁表引用计数收敛原语**；**P2-1 fail-safe：legacy 条目缺 `last_modified` ⇒ 读 `None`（禁用 IMS，不抛 `KeyError`）+ 溯源 PRD v0.8**；**读侧 fail-safe 口径补全（缺 `xml` ⇒ 视同 miss；`time`/`expires_at` 以 `.get` 读取）+ `feed_fetch_acquire` 实现约束（先 `get` 判空、未命中才建 `Lock`）**；**最后一轮契约收口：`''` 边界写死 + 残缺降级可观测（`log.warning` 去重）+ 边界登记（§10#29/#30）**）· **日期** 2026-09-18 · **作者/产出** task-decomposer
> **v1.13 变更（实现事实对齐 + 溯源更正 · 只改文档，不改代码）**：① **【新符号写进契约】** `cache.py` 新增两个符号，写入 **BR-CACHE-36 的实现注**，使契约与代码一一对应：**`_feed_degraded_warned`**（`set`，**按「原因」去重**的集合，非按"原因 + 键"）+ **`_warn_feed_degraded_once(reason, key)`**（`if reason not in _feed_degraded_warned: add(reason); log.warning('[cache] feed entry degraded to miss (%s): key=%r', reason, key)`；**总函数、绝不抛**）。消息含 `key`，措辞是**「缓存条目形态残缺 ⇒ 视同 miss」的自愈信号，不是 upstream error**（不含 "upstream" 字样）；日志用**既有**模块级 `log = logging.getLogger('cache')`（`cache.py:26` 已存在，**未新增 logger**）。② **【BR-CACHE-36 去重口径更正】** 去重维度由文中的「原因 + 键」更正为代码事实的**「原因」**：feed 缓存键内嵌**外部选定的 Host**（F2/F8）⇒ **按键去重会被客户端枚举键刷屏日志**，故每种残缺形态**每进程至多告警一次**（`_feed_degraded_warned` **故意无锁、容忍竞态**，与 `metrics._warned` 同风格）。消息格式钉死为 **`[cache] feed entry degraded to miss (<reason>): key=<key!r>`**（v1.12 契约文中示例 `[feed_cache] malformed entry key=… reason=missing_xml` **作废**）；实际原因取值 = `'entry is not a mapping'` / `'xml is None'`。③ **【§10#30 状态更正：登记不修 → 已防御】** 真值非映射条目现由 **`isinstance(..., dict)` 守卫**防御，落点**三处**：① `feed_cache_get_entry`（非映射 ⇒ 告警 + 视同 miss，**不抛 `AttributeError`**）；② `feed_cache_put` 的继承分支（`prev is not None` → `isinstance(prev, dict)`；非映射 `prev` ⇒ **不继承**、`last_modified` 走 `now`）；③ **共享的 `_sweep_expired`**（URL 缓存与 feed 缓存**两个**缓存共用；原 `entry.get('expires_at', 0)` 会在非映射条目上抛 `AttributeError`）。**为什么 ③ 是必要的最小改动而非越界**（实测证据）：**只去掉 ③ 的守卫**，`feed_cache_put` 在**触发①定时全扫**分支仍 `AttributeError` ⇒ put 的防御**不成立**；③ 是**共享助手**，其行为变化同时覆盖 URL 缓存路径（**合法路径行为逐字不变**，仅畸形条目不抛）。④ **【契约补全】** `_sweep_expired` 契约由"保留 `None` 条目"扩展为**"保留假值条目、且跳过真值非映射条目"**（判定式 `entry and isinstance(entry, dict)`；判定键仍 `expires_at`、返回删除条数不变）——落点 §2.5 兼容表行 / §4.3 BR-CACHE-13 / §5.2·§5.3 伪代码。⑤ **【测试实现标注】** `T-CACHE-36` ④ `xml=''` 命中 + ⑤ **非映射守卫（读侧 + `feed_cache_put`/`_sweep_expired` 写侧）** 已落地于 `tests/test_cache.py::FeedEntryAccessorTests`；**告警可观测/去重**由**独立方法** `test_t_cache_36_degraded_miss_warns_once` 覆盖（**同一原因**的两把不同键 ⇒ 仅 1 条记录；`xml=''` 不产生 warning；消息含键且**不含 "upstream"**）。⑥ **【溯源更正】** 头部上游 **SAD v1.9 → v1.11**、**PRD v0.8 → v0.9**（`config.md` v1.5 已先行更正；权威以各文档头部为准）——**最后一处溯源滞后闭环**。**除 ③ 的「登记不修 → 已防御」属实现状态更正外，其余均为实现事实对齐 / 溯源更正，无 BR 语义变更**；`feed_cache_get` / `feed_cache_get_entry` / `feed_cache_put` / `feed_fetch_acquire` / `feed_fetch_release` 签名与成功路径语义、锁序、TTL/清扫/上限、**BR-CACHE-32..35 正文主体全部不变**。**未改代码 / SAD / PRD / API.md / README.md / `.opencode`；`server.md` → v1.14、`metrics.md` → v1.6、`_PROGRESS.md` 同步。**
> **v1.12 变更（最后一轮契约收口：`''` 边界写死 + 残缺降级可观测 + 边界登记 · 只改文档，不改代码）**：① **【`''` 边界写死】** `feed_cache_get_entry` 的 miss 判据**恰好**是 `entry.get('xml') is None`（缺键或显式 `None`）；**`xml == ''` 属「合法但空」的表示 ⇒ 照常命中、照常服务**（返回 dict；`feed_cache_get` 返回 `''`）；**显式禁令**：**禁止**把判据化简为 `not xml` / `if not entry.get('xml')` —— 那会把 `''` 判为 miss 并形成 **读 miss → 回源 → 写 `''` → 再 miss 的永久回源环**（读侧无法区分"合法空表示"与"截断体"）。② **【残缺降级可观测 · 新增 `BR-CACHE-36`】** 因 `xml` 缺失而"视同 miss"的分支**必须**打一条 `log.warning`（含**键**与**原因**）并**按「原因/键」去重**（防热路径日志刷屏）；**语义澄清**：这是**「缓存条目形态残缺」的自愈路径**（miss ⇒ 回源一次 ⇒ `feed_cache_put` 修复同键 ⇒ 下次命中），**不是"上游故障"**；`feed_cache_put` 恒写 `xml`，故**生产中不可达**（命中即异常信号）；"空条目 / 正常过期"两个 `return None` 分支属正常控制流、**不打 warning**。③ **【边界登记】** §10 续号 **#29**（`expires_at` 缺省 `0` 依赖 `time.time() >= 0`；仅在时钟被打桩为负值时才可能反转为命中，届时直接下标 `entry['expires_at']` 才可能 `KeyError`——**当前不可达**）/ **#30**（真值非映射条目 `entry.get(...)` 抛 `AttributeError` 经 `_guard` 变降级体；生产不可达；**实现未加 `isinstance(entry, dict)` 守卫 ⇒ 登记不修**）。④ **【测试】** `T-CACHE-36` 增 **④ `xml=''` 命中断言**（`feed_cache_get_entry` 返回 dict 且 `feed_cache_get == ''`）+ **⑤ 残缺告警可观测/去重断言**。**`feed_cache_get`/`feed_cache_get_entry`/`feed_cache_put`/`feed_fetch_acquire`/`feed_fetch_release` 签名与成功路径语义、锁序、TTL/清扫/上限、BR-CACHE-32..35 正文主体全部不变**；**未改代码 / SAD / PRD / API.md / README.md / `.opencode`；`server.md` → v1.13、`_PROGRESS.md` 同步。**
> **v1.11 变更（读侧 fail-safe 口径补全 + `acquire` 实现约束 · 只改文档，不改代码）**：① **【P2-4 补全】`feed_cache_get_entry` 的读侧对「形态不完整」必须 fail-safe**（**与 v1.10 的 `last_modified` 口径明确区分，不得写成同一件事**）：**条目有 `xml`、缺 `last_modified`/`fingerprint`** ⇒ 仍**照常服务**，只是不发 `Last-Modified`、禁用 IMS（v1.10 已定，不变）；**条目缺 `xml`（或 `xml is None`）⇒ 视同 miss（返回 `None`）**，**绝不返回残缺体、绝不抛 `KeyError`**（抛异常经 `_guard` 会被误报为"上游失败"降级体）。`time` 以 `.get('time')`（缺省 `None`）读取；`expires_at` 沿用既有 `entry.get('expires_at', 0)`（缺省 `0` ⇒ `now >= 0` 恒成立 ⇒ 自然判为过期 ⇒ 亦视同 miss）；`last_access` 是访问器**自己刚写入**的字段、恒存在，**不需 `.get`**（避免过度防御）。`feed_cache_get` 经同一 `feed_cache_get_entry` 短路径 ⇒ 缺 `xml` 时同样返回 `None`。**一句话原则**：缓存的读侧对「形态不完整」必须 **fail-safe 到「当成没有」或「降级为无该头」**，而不是 **fail-loud 到「抛异常 → 被 `_guard` 误报为上游故障」**。② **【微优化 · 实现约束】`feed_fetch_acquire` 不得为未命中路径构造被丢弃的对象**：**必须先 `get(key)` 判空、仅在 `None` 时创建 `threading.Lock()`**（命中已有锁的路径**零分配**）；`setdefault(key, threading.Lock())` 会**每次调用**（含命中）都先构造一个 `Lock` 再被丢弃。**语义不变**（返回同一把锁、计数先于返回、临界区仅在 `_feed_fetch_locks_lock` 内）。③ 新增测试 **`T-CACHE-36`**（缺 `xml` ⇒ 视同 miss；缺 `expires_at` ⇒ 视同过期；四字段 legacy（**有 `xml`**）⇒ 仍返回 dict 且 `last_modified is None`——**①②③ 行为对比例子是关键**）。**`feed_cache_get`/`feed_cache_get_entry`/`feed_cache_put` 签名与成功路径语义、锁序、TTL/清扫/上限、BR-CACHE-34/35 语义全部不变；`last_modified` 的 v1.10 口径不变。** **未改代码 / SAD / PRD / API.md / README.md / `.opencode`；`server.md` → v1.12、`config.md` → v1.5、`_PROGRESS.md` 同步。**
> **v1.10 变更（P2-1 fail-safe 收口 + 溯源更正 · 只改文档，不改代码）**：**`feed_cache_get_entry` / `feed_cache_put` 对「非六字段条目」（legacy / 注入条目）的 `last_modified` 读取改为 `.get(..., None)` 口径**——① `feed_cache_get_entry` 用 `entry.get('last_modified')`；② `feed_cache_put` 的指纹继承分支用 `prev.get('last_modified')`；③ 完整性核对：`fingerprint` 的两处读取**本就是** `entry.get('fingerprint')` / `prev.get('fingerprint')`，**无需改**。**语义（写死）**：legacy 条目缺 `last_modified` 字段 ⇒ 读为 `None` ⇒ 该表示**不发 `Last-Modified` 头、禁用 IMS**（`If-Modified-Since` 不可评估；`If-None-Match` 仍按 ETag 正常评估），**而非抛 `KeyError` 经 `_guard` 变成降级体**（降级体是"上游失败"语义，缺字段只是"该条目无变更时刻"，二者不得混淆）。继承分支同理：`prev` 缺字段且指纹匹配 ⇒ 新条目 `last_modified=None`（退化为不发头，不抛异常、**不前进为写入时刻**）。**`feed_cache_get`/`feed_cache_get_entry`/`feed_cache_put` 签名语义、锁序、TTL/清扫/上限不变**；**BR-CACHE-32/33 仅追加/收口 `.get(..., None)` 读取口径说明**（BR-CACHE-34/35 正文不变）——**均为读写口径收口、无 BR 语义变更**（正常路径该字段恒存在）。头部溯源 **PRD v0.6 → v0.8**（SAD v1.9 已在上版确认）。**未改代码 / SAD / PRD / API.md / README.md / `.opencode`；`server.md` → v1.11、`_PROGRESS.md` 同步。**
> **v1.9 变更（P8 F8 契约化 · feed 取数锁表有界收敛 · 只改文档，不改代码）**：新增一对锁表原语 **`feed_fetch_acquire(key) -> threading.Lock`** / **`feed_fetch_release(key)`**（BR-CACHE-35 / `server.md` BR-SRV-50）——**两者都必须持 `_feed_fetch_locks_lock`**；`acquire` 在返回锁之前把该键引用计数 +1（必要时创建 `Lock`），`release` 递减、**归零即 `pop` 该键及其计数**（两表同删，避免计数表本身成为新的无界表）。**为什么不能简单重加 `pop`**：归零前 `pop` 会让"已取出锁但尚未进入 `with`"的线程与后来者拿到**两把不同的锁** ⇒ 同一键双抓（`doc/review/系统_代码评审报告_001.md` TS-4 原始事故）；引用计数的不变式是**只要还有线程持有或即将获取该键的锁，计数就 ≥1，该键不可能被 `pop`**。**有界性结论**：锁表规模收敛于"**并发在飞的键数**"，而非"累计见过的键数"；`PUBLIC_BASE_URL` 已设时键恒为 5 条 path。新增 `_feed_fetch_refs: dict[cache_key -> int]`（同受 `_feed_fetch_locks_lock`）。**`feed_cache_get`/`feed_cache_get_entry`/`feed_cache_put` 签名语义、锁序、TTL/清扫/上限、BR-CACHE-32/33/34 正文全部不变。** 新增 **T-CACHE-35**（原语收敛 / 不双抓 / 异常路径不泄漏计数）；§2.4 双检措辞由 `feed_cache_get` 更正为 **`feed_cache_get_entry`**（与 `server.md` §2.5 / `SRV-T70` 一致）；头部溯源 **SAD v1.7 → v1.9**（★ **PRD 仍记 v0.6，实际 v0.8，未在本轮写范围——见报告**）。**未改代码 / SAD / PRD / API.md / README.md / `.opencode`；`server.md` → v1.10、`metrics.md` → v1.5、`_PROGRESS.md` 同步。**
> **v1.8 变更（P8 对抗性盲审 F1/F5 契约化 · 编排层裁定 · 只改文档，不改代码）**：① **【F1 / P1-1 根治】feed 缓存条目新增 `fingerprint`（规范化摘要，与 ETag 同源，由 server 侧 `_feed_fingerprint(xml)` 提供）与 `last_modified`（表示最后一次变更的时刻）**：`feed_cache_put(path, xml, ttl, fingerprint=None)` 写入时与**同一键上的上一条目**比较指纹——★ **即使该条目已过期也参与比较**（**必须显式写明**，否则实现者只在"新鲜条目"上比较而废掉本修复）；相同 ⇒ **继承**上一 `last_modified`，不同 ⇒ 取本次写入时刻；**无上一条目（首次 / 已被 LRU 淘汰 / 已被 sweep）⇒ 本次写入时刻**（可接受降级）。**不变式：`ETag` 变 ⟺ `Last-Modified` 前进**。**`time` 语义不变**（写入时刻，供 `fetch_json` 的 `refresh_epoch` 新鲜度下限 / BR-CACHE-31）。② **【F5 / P2-5】`feed_cache_put` 返回写入条目的浅拷贝**（六字段 `xml/time/last_modified/fingerprint/last_access/expires_at`，**非 `None`**），供 `server._get_or_fetch_feed` 直接消费、消除其 put 后第二次 `feed_cache_get_entry`（BR-CACHE-34 / `server.md` BR-SRV-48）。③ `feed_cache_get_entry` 返回形态扩为**同样六字段**（BR-CACHE-32 改写）。**新增 `BR-CACHE-33`（指纹继承）/ `BR-CACHE-34`（返回值）**；`feed_cache_get` 签名/语义**逐字不变**（薄包装）；**无新增锁、无 TTL/清扫/上限变更**。**未改代码 / SAD / PRD / API.md / README.md / `.opencode`；`server.md` → v1.9、`metrics.md` → v1.4、`_PROGRESS.md` 同步。**
> **v1.7 变更（P7b 漂移回填 D-3 · 仅文档标注，无实现/契约变更）**：**T-CACHE-32 的「浅拷贝隔离负例」已在 P6c 实现**——落点 `tests/test_cache.py::FeedEntryAccessorTests::test_t_cache_32_shallow_copy_isolates_the_container`（同类的契约用例为 `test_srv_t60_feed_cache_get_entry_contract`，二者同属 `FeedEntryAccessorTests`），断言"改写 `feed_cache_get_entry` 返回值不污染容器条目"，即 BR-CACHE-32 的「浅拷贝充分性 / 调用方只读」。本版在 **§8 用例**与 **§9 映射**标注**✅ 已实现**并核对方法名（评审 CR-RSS-20260918-001 D-3 闭环）。**`feed_cache_get_entry`/`feed_cache_get`/`feed_cache_put` 签名与语义、锁、容器字段、TTL/清扫/上限、BR-CACHE-32 正文全部不变。**
> **v1.6 变更（P3a-r1 评审定向修 · 对照 `REV-DES-20260918-001`）**：**仅测试与溯源，无实现/契约变更**——① 【**C7#14**】`§8 T-CACHE-32` 扩**浅拷贝隔离负例**：改写 `feed_cache_get_entry` 返回值**不改变**容器条目的 `last_access`/`expires_at`（断言 `feed_cache` 内条目字段未被污染，与 BR-CACHE-32 的"调用方只读"约束一致）；② 【**C8③**】头部溯源修正为实际版本 **SAD v1.7 / PRD v0.6**（原误记 v1.2 / v0.3）。**`feed_cache_get_entry`/`feed_cache_get`/`feed_cache_put` 签名与语义、锁、容器字段、TTL/清扫/上限全部不变**（BR-CACHE-32 正文未改）。
> **v1.5 变更（P3a · RSS 条件请求支撑）**：新增公开访问器 **`feed_cache_get_entry(path) -> dict | None`**（§2.4 / §5.3 / BR-CACHE-32）——返回**新鲜条目的浅拷贝** `{'xml','time','last_access','expires_at'}`，供 `server._serve_feed` 的 **Last-Modified** 取 `entry['time']`；内部与 `feed_cache_get` **完全同源**（同一 `_feed_cache_lock`、`now < expires_at` 判定、`move_to_end` + `last_access = now`），**`feed_cache_get(path) -> str | None` 签名与语义逐字不变**（改为 `feed_cache_get_entry` 的薄包装）。**无新增锁、无新容器字段、无 TTL/清扫行为变更**；`feed_cache_put` 签名与写入的 `time` 语义不变（`time` 即 Last-Modified 权威时间源）。（★ **v1.8 / F1 起 Last-Modified 改取 `entry['last_modified']`，本句为历史记录**）其余 v1.4 口径（连接池 / DNS / `refresh_epoch` / `_PROBE_BUDGET_CAP`）全部保持。
> **v1.4 变更（P7b 传输层契约同步 · 以代码为准）**：① 新增 **HTTP 连接复用池** `_ConnectionPool`（按 `(scheme,host,port)` 分桶、每 host 有界 `HTTP_POOL_MAX_PER_HOST`、空闲 `HTTP_POOL_IDLE_TTL` 懒淘汰、**失效连接丢弃并重试一次**、`_lock` 只护桶记账、连接/关闭/IO 全在锁外）与 **进程内 DNS TTL 缓存** `_DNSResolver`（TTL=`HTTP_DNS_CACHE_TTL`、失败不缓存、命中 IP 连不上时 `force` 重解析、异常回退 `socket.create_connection`）；② **`cache.urlopen(req, timeout=None)`** 为模块级可打桩缝，返回可 `read()` 的上下文管理器，4xx/5xx 抛 `HTTPError`、传输失败抛 `URLError`（跟随 ≤5 次重定向）——`urllib.request.urlopen` 已不再是取数出口；③ 新增公开函数 **`warm_transport(hosts=None, count=None, timeout=None)`**（走池、**仅握手不发业务请求**、总函数绝不抛）；④ `fetch_json` 新增**第 6 位关键字形参 `refresh_epoch`**（刷新轮起点；`_cache_fresh` 判定 `entry['time'] >= epoch`，`None` 时逐字不变；写入仍用完整域 TTL）；⑤ §1.3 import 面更正：**`json` 已删除**（v1.3 已登记），实际新增 `http.client` 与 `urllib.parse`。**其余 v1.3 口径（`_PROBE_BUDGET_CAP=5.0` / follower 余量 / metrics 锁外发布 / leader `try/finally`）保持不变。**
> **v1.3 变更（AC-S3 裁决 · 收尾契约同步）**：⑦ **半开探测阶梯封顶 = `_PROBE_BUDGET_CAP = 5.0`（新增模块级机制常量）**，序列 `2→4→5`（**不再是** `2→4→8→REQUEST_TIMEOUT(10)`）；`REQUEST_TIMEOUT` 仅用于"无失败历史 / 已老化（≥`_HISTORY_AGE=600s`）"两支的**一次性全预算探测**（§1.1#1 / §4.2 BR-CACHE-22 / §5.1 / §8 T-CACHE-4·4c·4d·21 / §10#11·#18 / §2.5）。**推导**：持续黑洞稳态 ≈ `5s 探测 + 5s NEG_TTL = 10s` 周期、慢请求占比 ≈50% ⇒ **P95 ≈ 5s**；单请求上界 `≤15s` 恒成立。
> 本版修订（P7b 契约同步，**只改文档、不改代码**）：① `fetch_json` 新增第 5 位形参 `deadline`，且**超期闸门位于正缓存命中之后**；② `_probe_budget` 按 `fail_count` **递增阶梯**（v1.3 更正：`2→4→5`，`_PROBE_BUDGET_CAP` 封顶）；③ follower 等待窗口 = `_fetch_budget + _FOLLOWER_WAIT_MARGIN(1.0s)`，`event.wait` 后复查 `_fetch_inflight`（leader 存活 ⇒ `upstream_timeout`）；④ metrics **一律在业务锁释放后**发布（`_publish_url_stats`），命中路径（段①/③双检/④）统一计 hit；⑤ leader 令牌获取纳入 `try/finally`；⑥ `import json` 已删（§10#6 收口）。
> 沿用 v1.1：REV-DES-01（plate stagger 表口径）/02（`cache_hit_ratio`）/03（`logging`）/04（依赖图）/09（段 3 try 范围）+ 逆向建议 1（失败历史老化）+ 逆向建议 2（删常量前置）+ 编排层裁决 #2/#3/#5 + 偏差 D-1/D-2/D-3/D-7 登记
> 模块路径 `china_finance_rss/cache.py` · 归属 **基础层（Layer 0，纯缓存/契约层）**
> 上游 SAD `doc/arch/SAD.md` **v1.11**（★ v1.6 溯源修正：原误记 v1.2；★ v1.9 溯源更新：v1.7 → v1.9；★ **v1.13 溯源更新：v1.9 → v1.11**——权威以 SAD 头部为准）（§2.1 / §2.2 R-3 / §2.3 D-1 D-2 D-5 / §2.4 / ADR-002/003/008/009/014）
> 上游 PRD `doc/prd/perf-stability-optimization.md` **v0.9**（★ v1.6 溯源修正：原误记 v0.3；★ v1.10 溯源更新：v0.6 → v0.8；★ **v1.13 溯源更新：v0.8 → v0.9**——权威以 PRD 头部为准）（AC-S3/S6/A4/A9/A10/E6/E9/A10）
> 端锁定 🟠 STABLE（对外仅**新增**保留键；`fetch_json` 签名**纯新增可选参数**）

## 1. 模块职责与边界

### 1.1 职责

1. **唯一上游取数入口** `fetch_json(url, headers, ttl, encoding, deadline, refresh_epoch)`：URL 缓存 + leader/follower 防击穿 + **负缓存（失败状态层）** + **四段式语义**。超时预算三分：**冷预算 / 老化全预算 = `REQUEST_TIMEOUT(10s)`**，**递增半开探测阶梯 = `2→4→_PROBE_BUDGET_CAP(5s)`**（★ v1.3 / AC-S3 裁决，§4.2 BR-CACHE-22）。
1. **HTTP 传输子层（v1.4 新增，唯一出口）** `urlopen(req, timeout=None)`：per-`(scheme,host,port)` keep-alive 连接池 + 进程内 DNS TTL 缓存 + 重定向跟随；`warm_transport()` 在进程启动期预热 DNS/连接（**不发业务请求**）。`fetch_json` 只经此出口触网（§2.7 / §4.5 BR-CACHE-26..30）。
2. **URL 缓存** `cache`：真 LRU（`OrderedDict`）+ 双触发过期清扫 + 上限 2000。
3. **feed 缓存** `feed_cache`：真 LRU + 双触发清扫 + 上限由 `cache_policy('feed')['cache_max']` 派生。
4. **批量响应组装（纯函数）** `build_batch_response(requested, results, errors, dropped)`：下划线保留键契约的唯一组装点。
5. **失败状态数据结构** `FetchError(kind)`（枚举 `upstream_timeout` / `upstream_error` / `cdp_unavailable`）。
6. `_fill_missing(result, data, expected_keys)`（既有，保留）。

### 1.2 明确不做（**P2-N6 硬约束**）

- **帧计费（`_Frame` / `refs` / `stream_queue_bytes`）不得落在此模块**——属 stream 层（ADR-013）。cache.py 只做纯缓存/契约。
- 不 import `server` / `stream` / `stock_api` / `market_api`（`layerIsolation` 原文）。
- 不实现码级冷却 `_fail_ledger`（属 `stock_api`，ADR-014）——本模块只做 **URL 级负缓存**。
- 不做 HTTP 响应形状的最终拼装（`_truncated` 的 `dropped` 由 `server._handle_stock_batch` 计算后传入）。
- 不依赖交易时段以外的业务概念；`cache_policy` 来自 config，本模块不自行推导 TTL。

### 1.3 layerIsolation 约束（tech-stack.json 原文）

```
pattern: china_finance_rss/cache.py
forbiddenImports: server, stream, stock_api, market_api
reason: cache.py 必须保持纯缓存/契约层，反向依赖上层模块会形成环
```

**允许 import**：标准库 `collections`(OrderedDict) / `http.client` / `logging` / `random` / `socket` / `threading` / `time` / `urllib.error` / `urllib.parse`(urljoin, urlsplit) / `urllib.request`(Request)；包内 `config`、`metrics`。
> `logging` 为 **REV-DES-03 补列**：本模块 §2.3/§5.4/§6 使用 `log.warning(...)`，须在模块顶部 `log = logging.getLogger('cache')`（§5.1 初始化段）。`socket` 为 D-3 新增（供 `_classify` 判定超时），已在 tech-stack allowlist。
> ★ **v1.4 import 面更正（以代码为准）**：`json` **已删除**（v1.3 §10#6 登记，本模块从未使用）；**新增 `http.client`**（`_STALE_CONNECTION_ERRORS` 的 `RemoteDisconnected`/`BadStatusLine`/… + `responses` 表）与 **`urllib.parse`**（`_pool_request` 的 `urlsplit`、`urlopen` 的 `urljoin`）。原 `urllib.request.urlopen` 改为 `Request` + 本模块 `urlopen`（§2.7）。

**依赖方向**（**REV-DES-04 澄清**：`←` 表「分层顺序」，**非 import 关系**）：本模块 `import config` + `import metrics`（二者互不依赖，均为 Layer 0 叶子）→ 上承 `stock_api`/`market_api`/`stream` → `server`。`metrics` 零业务依赖、**不 import config**，图中与 config 并列而非其上：`config` ‖ `metrics` ← **`cache`** ← `stock_api`/`market_api`/`stream` ← `server`。

---

## 2. 接口契约

### 2.1 `fetch_json(url, headers=None, ttl=None, encoding='utf-8', deadline=None, refresh_epoch=None) -> str`

```python
def fetch_json(url: str, headers: dict | None = None, ttl: int | None = None,
               encoding: str = 'utf-8', deadline: float | None = None,
               refresh_epoch: float | None = None) -> str:
```

| 参数 | 类型 | 默认 | 语义 |
|------|------|------|------|
| `url` | `str` | — | 缓存键。**编码不是键的一部分**（§7.3#7 假设：同一 URL 不会以两种编码出现） |
| `headers` | `dict \| None` | `None` | 透传 `Request` 头 |
| `ttl` | `int \| None` | `None` | 秒。`None` → 取 `cache_policy('news_url')['ttl']`（L3）。**调用方应传 `cache_policy(d)['ttl']`** |
| `encoding` | `str` | `'utf-8'` | `resp.read().decode(encoding, errors='replace')`。**新增形参**（D-5）；GBK 上游显式传 `'gbk'` |
| `deadline` | `float \| None` | `None` | **P7b 新增第 5 位形参**：绝对 epoch 秒的端到端期限。`None` ⇒ 不设期限（仅用 `_fetch_budget` 兜底）。非 `None` 时 leader 网络超时 = `min(_fetch_budget(url), max(0.05, deadline-now))`，follower 等待窗口同样被该时刻截断。**位置参数追加，既有 18 处调用点零改动** |
| `refresh_epoch` | `float \| None` | `None` | **v1.4 新增第 6 位关键字形参**：计划刷新轮的起点 epoch 秒。非 `None` 时正缓存命中额外要求 `entry['time'] >= refresh_epoch`（§4.5 BR-CACHE-31 / `_cache_fresh`），以消除"TTL==tick 相位耦合"（名义 4s 实际 8s 刷新）。**段①/③/④ 三处判定一致**；`None`（全部 REST/prefetch 调用方）语义逐字不变；**写入仍用完整域 TTL** |

**返回**：`str`（已解码正文）。
**抛出**：`FetchError`（**唯一失败类型**，见 2.2）。成功路径不再返回 `None`。
**线程安全**：是。网络 IO **永不持锁**。

**四段式语义（SAD §2.3 D-1 精确化，P7b 以代码为准）**

```
段 1  正缓存命中              → 返回 str（move_to_end + last_access 更新 + 计 hit）
                               ★ 命中即返回：**不读负缓存、不看 deadline、零网络**
段 1b deadline 已耗尽（非 None 且 remaining <= 0，且段 1 未命中）
                              → 立即 raise FetchError('upstream_timeout')，不触网、**不写负缓存**
段 2  负缓存未过期            → 立即 raise FetchError(kind)，不触网（<1ms）
段 3  leader 选举，只尝试一次 → 超时预算 _effective_timeout(url, deadline)：
                                 基础 _fetch_budget(url)：无条目 → REQUEST_TIMEOUT(10s)
                                                          已老化(≥_HISTORY_AGE) → REQUEST_TIMEOUT(10s)
                                                          否则 → _probe_budget(fail_count) 递增阶梯
                                                                 2s → 4s → _PROBE_BUDGET_CAP(5s) 封顶（v1.3）
                                 再与剩余 deadline 取 min（超期为 None ⇒ 本地超时，不触网、不写负缓存）
                               成功 → 写正缓存 + 清除负缓存 + 返回 str
                               失败 → 写负缓存(until=now+NEG_TTL, fail_count+=1) + raise
                               ★ finally 必定 pop _fetch_inflight + event.set()（令牌不泄漏）
段 4  follower 等待 leader 结束 → 等待窗口 = _follower_wait_budget(url, deadline)
                                        = min(_fetch_budget(url) + _FOLLOWER_WAIT_MARGIN(1.0s), remaining)
                               读正缓存命中 → 计 hit 并返回；
                               否则读负缓存（**忽略过期**：gap 分支必须确定性）→ raise FetchError(kind)；
                               否则复查 _fetch_inflight：
                                 leader 仍存活 ⇒ raise FetchError('upstream_timeout')
                                                 （本地等待预算，**不写负缓存、不计失败**）
                                 无正缓存 ∧ 无负缓存 ∧ 无 leader ⇒ raise FetchError('upstream_error')
                               **不再重入选举**（删除 fall-through 三段路径）
```

> ★ **v1.4 · `refresh_epoch` 新鲜度下限（以代码为准）**：段 ①/③/④ 的正缓存判定一律调 `_cache_fresh(entry, refresh_epoch)`（§5.1），即 `now < expires_at` **且**（`refresh_epoch is None or entry['time'] >= refresh_epoch`）。计划刷新路径（`stream`）把**本轮起点**作为该域 `refresh_epoch` 传入，使上一轮 δ 秒后写入的条目在本轮不再算命中——否则 TTL 恰等于 tick 时每两轮才真回源一次（4s 名义刷新退化为 8s）。**写路径不感知 `refresh_epoch`**：`_cache_put` 仍写完整域 TTL，故 REST/预取在窗口内仍被正缓存保护。

**行为变更登记（相对现状）**

| 变化 | 现状 | 目标 | 依据 |
|------|------|------|------|
| 失败类型 | `leader` 失败 → follower 重入选举；最终 `RuntimeError` | `FetchError(kind)`；follower 不触网 | R9 / ADR-003 |
| fall-through 三段路径 | `sleep(0~0.5)` + `Semaphore(2)` + `acquire(timeout=3)`（最坏 ~13.5s） | **删除**（含 `_fallthrough_sem`） | R9 的 13.5s 来源 |
| 失败记忆 | 无 | 负缓存 `_negative`（URL 级，`NEG_TTL=5s`） | RC-2 |
| 失败分类 | 无 | `upstream_timeout` / `upstream_error` | AC-A10 枚举 |
| 缓存淘汰 | 按插入 `time`（FIFO） | `OrderedDict` + `move_to_end`（真 LRU） | R3/R11 / ADR-008 |
| 默认 ttl | `CACHE_TTL=300` | `cache_policy('news_url')['ttl']`（30/180） | D4 / Q3 |
| 编码 | 硬编码 utf-8 | `encoding` 形参（默认不变） | P1-4 / D-5 |
| **超期闸门位置** | 无 `deadline` 形参 | 第 5 位形参 `deadline`；闸门**在段 1 命中之后**（P7b） | 命中零网络、零延迟，调用方预算耗尽不得拒掉已在缓存的数据 |
| **半开探测预算** | 有失败历史即 `PROBE_TIMEOUT(2s)`（未老化） | `_probe_budget(fail_count)` **递增阶梯** `2→4→5`，封顶 **`_PROBE_BUDGET_CAP=5.0`**（★ v1.3 更正：**非** `REQUEST_TIMEOUT`；§4.2 BR-CACHE-22） | 慢而 >2s 的上游可在数个周期内自愈，而非苦等 `_HISTORY_AGE`；同时把持续黑洞的 P95 钉在 ≈5s（≤15s 上界不破） |
| **follower 等待窗口** | `event.wait(_fetch_budget(url))` | `+ _FOLLOWER_WAIT_MARGIN(1.0s)`，并按 deadline 截断（P7b，§4.2 BR-CACHE-23） | leader 取数后的发布（微秒级）不得与等待窗口竞态而把 follower 推入 gap 分支 |
| **metrics 发布点** | 持锁内发布（残留） | **一律锁外**：`_publish_url_stats` / `_record_failure` / `_clear_negative` / `feed_cache_put`（P7b，§4.2 BR-CACHE-24） | `/healthz` 快照不得阻塞取数热路径 |
| **leader 令牌** | 预算/选举异常可泄漏 `_fetch_inflight` 条目 | 选举后的全部逻辑置于 `try/finally`，`finally` 内 `pop` + `event.set()`（P7b，§4.2 BR-CACHE-25） | 泄漏会使该 URL 此后每次请求都沦为超时 follower |
| **触网出口**（v1.4） | `urllib.request.urlopen(req, timeout=...)`（每请求新建 TCP+TLS **并重解析 DNS**） | 本模块 `urlopen(req, timeout=None)`：keep-alive 池 + DNS TTL 缓存（§2.7 / §4.5） | 2C2G 实测单请求 ~340ms（DNS ~176ms + 握手 ~78ms）→ 复用后 ~48ms；50 码冷扇出 ~4.2s（超 0.8×tick 预算） |
| **正缓存新鲜度**（v1.4） | 仅 `now < expires_at` | 追加可选 `refresh_epoch` 下限：`entry['time'] >= epoch`（`None` ⇒ 逐字不变） | TTL==tick 时相位耦合使名义 4s 刷新实际 8s（每两轮回源一次） |
### 2.2 `FetchError(kind, *, url=None, cause=None)`

```python
class FetchError(Exception):
    KINDS = frozenset({'upstream_timeout', 'upstream_error', 'cdp_unavailable'})

    def __init__(self, kind: str, *, url: str | None = None,
                 cause: BaseException | None = None) -> None: ...
    # 属性：self.kind, self.url, self.cause
    # __str__: f'{kind}: {url}'  (url 为 None 时仅 kind)
```

| kind | 产生者 | 触发条件 |
|------|--------|---------|
| `upstream_timeout` | `fetch_json` | `socket.timeout`/`TimeoutError`，或 `URLError.reason` 为二者之一 |
| `upstream_error` | `fetch_json` | 其余所有异常（`URLError`/`HTTPError`/`OSError`/`ConnectionError`…）；**及 gap 分支兜底**（§5 段 4） |
| `cdp_unavailable` | `stock_api.fetch_cls_f10`（**不在本模块产生**） | CDP 不可用 / 页面无数据（SAD §2.3 D-4 A′） |

- 非法 kind → `ValueError`（构造期拒绝，防止自由文本进入 `_errors`，AC-S6「不允许自由文本」）。
- `raise FetchError(kind, url=url) from exc`：保留原始异常链（`__cause__`），便于日志定位。
- **`FetchError` 取代原 `RuntimeError`**：调用方现有 `except Exception` 全部覆盖；全仓无 `except RuntimeError` 捕获此路径（编码前需 grep 复核，见 §8 T-CACHE-0）。

### 2.3 `build_batch_response(requested, results, errors=None, dropped=0) -> dict`

```python
def build_batch_response(requested, results, errors=None, dropped=0) -> dict:
```

| 参数 | 类型 | 语义 |
|------|------|------|
| `requested` | `Sequence[str]` | 请求码序（**保序**）；控制输出键序与键集合 |
| `results` | `Mapping[str, Any]` | 码 → 数据客体 / `None` |
| `errors` | `Mapping[str, str] \| None` | 码 → 枚举错误码；`None` 等价 `{}` |
| `dropped` | `int` | 被截断码数（HTTP 层计算，>0 时挂保留键） |

**返回**：扁平映射（`dict`，插入序 = 请求序），可能附保留键。**纯函数**：无锁、无全局读写、无 IO、不 import 业务模块。

**组装规则（BR-CACHE-7..10）**
1. 仅输出 `requested` 中的码，每个至多一次（重复码去重）；值 = `results.get(code)`（缺失 → `None`）。**`results` 中不在 `requested` 的键被忽略**（防止内部键泄漏）。
2. `requested` 中以下划线 `_` 开头的码**跳过**（防御：代码键恒不含前导下划线，避免与保留键同命名空间冲突）。
3. `_errors` **仅在至少一个码满足「值为 `None` 且 `errors[code]` 非空」时**挂载；键序 = 请求序；值为枚举串。
   - `errors[code]` 非空但 `results[code]` 非 `None` → `log.warning` 且**不收录**（保证值域三分自洽：`code ∈ _errors ⇒ 值 null`）。
   - 未知 kind → 归一为 `'upstream_error'` 并 `log.warning`（枚举封闭，不产生自由文本）。
4. `_truncated` / `_dropped_count` **仅当 `dropped > 0` 时同现**：`_truncated=True`、`_dropped_count=int(dropped)`。`dropped <= 0` 时两键**均不存在**（不得为 `false`/`0`，AC-A9 单一口径）。
5. 返回体**永不**含顶层 `error` 键（批量与单体形态严格互斥，AC-A5）。

### 2.4 feed 缓存访问器（**feed LRU/清扫的唯一实现点**）

```python
def feed_cache_get(path: str) -> str | None      # 命中并刷新 LRU；未命中/过期 → None（★ v1.5：薄包装 feed_cache_get_entry）
def feed_cache_get_entry(path: str) -> dict | None   # ★ v1.5：命中返回新鲜条目浅拷贝；未命中/过期 → None
def feed_cache_put(path: str, xml: str, ttl: int, fingerprint: str | None = None) -> dict
                                                 # ★ v1.8 / F1+F5：返回写入条目浅拷贝（六字段，非 None）
```

- **`feed_cache_get_entry` 返回契约（★ v1.5 / BR-CACHE-32；★ v1.8 / F1 扩字段；★ v1.10 / P2-1 fail-safe）**：命中（`now < expires_at`）⇒ 返回**浅拷贝** `{'xml': str, 'time': float | None, 'last_modified': float | None, 'fingerprint': str | None, 'last_access': float, 'expires_at': float}`，并在锁内完成 `move_to_end(path)` + `entry['last_access'] = now`（与 `feed_cache_get` 同一 LRU 副作用，**恰好一次**）；未命中/过期 ⇒ `None`。**浅拷贝**保证调用方（server）无法在锁外改写容器内条目的键值。★ **v1.8 / F1**：`last_modified` 是 **Last-Modified 权威来源**（表示最后一次变更的时刻）；`entry['time']` 仍是 `feed_cache_put` 的**写入时刻**（供 `refresh_epoch` 新鲜度下限，BR-CACHE-31）。★ **v1.10 / P2-1**：`last_modified` **必须**以 `entry.get('last_modified')`（缺省 `None`）读取——legacy / 注入条目（非六字段）缺该字段时 ⇒ 返回的 `last_modified=None` ⇒ server **不发 `Last-Modified` 头、禁用 IMS**，**绝不抛 `KeyError`**（抛异常会被 `_guard` 吞成降级体，把"该条目无变更时刻"误报为"上游失败"）。`fingerprint` 由 `entry.get('fingerprint')` 读取，口径一致。★ **v1.11 / 读侧 fail-safe 补全（P2-4）**：**`xml` 缺字段（或 `None`）⇒ 视同 miss（返回 `None`）**——绝不返回残缺体、绝不抛 `KeyError`（抛异常会被 `_guard` 吞成降级体，把"条目残缺"误报为"上游失败"）；`time` 以 **`entry.get('time')`** 读取（缺省 `None`）；`expires_at` **沿用既有 `entry.get('expires_at', 0)`**（缺省 `0` ⇒ `now >= 0` **恒成立** ⇒ 自然判为过期 ⇒ 亦视同 miss）；`last_access` 是访问器**自己刚写入**的字段、**恒存在，不需 `.get`**（避免过度防御）。★ **此口径与"有 `xml` 但缺 `last_modified` ⇒ 仍照常服务、只是不发头"是两件事，不得混为一谈。** **一句话原则**：读侧对「形态不完整」必须 **fail-safe 到「当成没有」或「降级为无该头」**，而**不得 fail-loud 到「抛异常 → 被 `_guard` 误报为上游故障」**。★ **v1.12 / `''` 边界 + 可观测（BR-CACHE-32 / BR-CACHE-36）**：miss 判据**恒为 `entry.get('xml') is None`**；**`xml == ''` 属「合法但空」的表示 ⇒ 照常命中、照常服务**（`feed_cache_get` 返回 `''`），**禁止**真值化简（`not xml` / `if not entry.get('xml')`）——否则 `''` 判 miss ⇒ **读 miss → 回源 → 写 `''` → 再 miss 的永久回源环**（缓存自我击穿）。因 `xml` 缺失而"视同 miss"的分支**必须**经 **`_warn_feed_degraded_once(reason, key)`** 打一条 `log.warning`（消息含键与原因，用既有 `log`；`reason='xml is None'`）并**按「原因」去重**（集合 `_feed_degraded_warned`；**不按"原因 + 键"**——键含外部选定 Host，按键去重会被枚举刷屏）；**语义**：这是**「缓存条目形态残缺」的自愈路径**，**不是"上游故障"**；`feed_cache_put` 恒写 `xml` ⇒ 生产中不可达（命中即异常信号）。**"空条目（`not entry`）/ 正常过期"两个 `return None` 分支属正常控制流，不打 warning。**
- **`feed_cache_put` 返回契约（★ v1.8 / F5 / BR-CACHE-34）**：写入后返回**写入条目的浅拷贝**（与 `feed_cache_get_entry` 同形态六字段，**恒为 dict、不是 `None`**）——在 `_feed_cache_lock` **内**构造并返回，故不受随后淘汰竞态影响；`server._get_or_fetch_feed` **直接消费该返回值**、不再 put 后二次查询。`fingerprint` 为**可选**（默认 `None`，既有调用点零改动）；`fingerprint is None` ⇒ 不做继承、`last_modified = 本次写入时刻`。
- **指纹继承（★ v1.8 / F1 / BR-CACHE-33；★ v1.10 / P2-1 fail-safe）**：`feed_cache_put` 在写入前取**同一键的上一条目**（★ **即使该条目已过期也参与比较**——这是"跨 TTL 重生成仍 304"的机制），当且仅当 `fingerprint is not None and prev.get('fingerprint') == fingerprint` ⇒ **继承** `prev.get('last_modified')`；否则 `last_modified = now`。**无上一条目**（首次 / LRU 淘汰 / 已 sweep）⇒ `last_modified = now`。★ **v1.10 / P2-1**：继承用 `prev.get('last_modified')`（缺省 `None`）——若上一条目（legacy / 注入）指纹匹配但**缺 `last_modified` 字段** ⇒ 新条目 `last_modified=None`（该表示不发 `Last-Modified`、禁用 IMS），**不抛 `KeyError`、也不前进为写入时刻**（前进会发出错误的"已变更"信号，违反"表示最后一次变更"语义）。`fingerprint` 比较用 `prev.get('fingerprint')`（缺字段 ⇒ `None`，因 `fingerprint is not None` 前置条件恒不匹配 ⇒ 走 `now` 分支），口径一致。**注意**：`prev` 必须在触发①定时全扫 / 触发②容量清扫**之前**捕获（否则被 sweep 删除后丢失继承机会）。
- 命中：`move_to_end(path)` + `last_access = now` → 返回 `entry['xml']`（★ v1.5：`feed_cache_get` 现为 `feed_cache_get_entry` 的薄包装，`return entry['xml'] if entry else None`，**对外签名/语义逐字不变**。★ **v1.11**：`feed_cache_get_entry` 已保证缺 `xml`（或 `None`）时返回 `None`，故此处 `entry['xml']` **安全**——缺 `xml` 的条目在上一行即视同 miss）。
- 写入：触发①定时全扫（`_last_feed_sweep`，60s）→ 触发②容量清扫（cap = `cache_policy('feed')['cache_max']`）→ 插入并 `move_to_end`。
- **落点说明**：SAD 把 feed TTL/LRU 的**行为落点**记为 `server._get_or_fetch_feed`；本设计把**缓存机制**（LRU/清扫/淘汰）实现在 cache 层（符合 1.3 layerIsolation 与"缓存机制归缓存层"），`_get_or_fetch_feed` 保留其 `_feed_fetch_locks` 防击穿职责并改为调用这两个函数。**server 详设必须按此对齐**。编排层已裁决 ✅ 落 cache.py（待确认 #3，SAD §2.2 R-3/§3 server 行将回改）。
- **双检语义（server 侧硬约束，裁决 #3 必要条件；★ v1.8 / F2 键口径；★ v1.9 / F8 加锁原语 + 措辞更正）**：`feed_cache_get_entry(cache_key)` miss 后，`server._get_or_fetch_feed` **必须**按序：① `feed_fetch_acquire(cache_key)` 取 **per-键** 锁 → ② **再次 `feed_cache_get_entry(cache_key)`（双检）** → ③ 仍 miss 才 fetch → ④ `feed_cache_put(cache_key, xml, ttl, fingerprint=…)`；**并全程 `try ... finally: feed_fetch_release(cache_key)`**（BR-CACHE-35）。★ **v1.9 措辞更正**：本文旧版写 `再次 feed_cache_get(path)`，与 `server.md` §2.5 / `SRV-T70`（**`feed_cache_get_entry` 恰好调用 2 次**）不一致——`feed_cache_get` 只是 `feed_cache_get_entry` 的薄包装，**读取入口统一为 `feed_cache_get_entry`**。**缺 ② 则并发请求在「miss→取锁」窗口内全部穿透，防击穿退化**。cache 层只保证 `get`/`put` 各自原子（同 `_feed_cache_lock` 内完成），双检在 server 侧；`feed_cache_get_entry` 不得返回过期值（`now >= expires_at` → `None`）。★ **v1.8 / F2**：`cache_key` 是**不透明缓存键**（`PUBLIC_BASE_URL` 未设时 = `path + '\x00' + base_url`）；cache 层不引入 Host/`PUBLIC_BASE_URL` 概念，键的作用域由 server 侧 `_feed_cache_key` 组合（`server.md` BR-SRV-45）。
- **取数锁表收敛原语（★ v1.9 / F8 / BR-CACHE-35 / `server.md` BR-SRV-50）**：`feed_fetch_acquire(key) -> threading.Lock` / `feed_fetch_release(key)` 是 `_feed_fetch_locks` 的**唯一读写入口**（`server._get_or_fetch_feed` 消费；server 不再直接 `import _feed_fetch_locks`）。两者**均持 `_feed_fetch_locks_lock`**：`acquire` 先取锁（v1.9 原文示例为 `lock = _feed_fetch_locks.setdefault(key, threading.Lock())`；★ **v1.11 实现约束改为先 `get` 判空、仅未命中才建 `Lock`**，见本段末）、`_feed_fetch_refs[key] = _feed_fetch_refs.get(key, 0) + 1`，**然后才 `return lock`**（计数先于返回，覆盖"已取出锁但尚未进入 `with`"的窗口）；`release` 令 `n = _feed_fetch_refs.get(key, 1) - 1`，`n <= 0` ⇒ **同时 `pop` `_feed_fetch_locks[key]` 与 `_feed_fetch_refs[key]`**，否则写回 `n`。**不变式**：只要还有线程持有或即将获取该键的锁，计数 ≥1 ⇒ 该键**不可能**被 `pop`；**禁止**在任何"计数 > 0"的情形下 `pop`（归零前 `pop` 即 `TS-4` 的双抓事故）。**正确性论证（评审会核对）**：`pop` 只发生在计数归零时，此时无任何持有者/等待者；随后到达的线程创建新锁，其双检仍命中前一个持有者已写入的缓存条目 ⇒ **不产生重复取数**（第二次真取数只可能因为条目确实已过期）。**调用纪律**：`acquire` / `try ... finally: feed_fetch_release(key)`——异常路径也必须释放，否则计数泄漏 ⇒ 锁表退化为**只增不减**。**有界性结论**：锁表规模收敛于"**并发在飞的键数**"，而非"累计见过的键数"；`PUBLIC_BASE_URL` 已设时键恒为 5 条 path。★ **v1.11 / 实现约束（微优化，语义不变）**：`acquire` **必须先 `lock = _feed_fetch_locks.get(key)` 判空、仅当 `lock is None` 才 `threading.Lock()` 并写入**——`setdefault(key, threading.Lock())` 会在**每次调用**（含命中已有锁）都先构造一个 `Lock` 再被丢弃；改先 `get` 后 **命中路径零分配**。锁对象身份、计数先于返回、临界区语义**逐字不变**。
- 容器仍为公开名 `feed_cache`；`_feed_cache_lock` 仍导出（server 现状 import 兼容）。
- **★ v1.5（条件请求支撑）**：`server._get_or_fetch_feed` 的**读取入口**由 `feed_cache_get` 改为 `feed_cache_get_entry`（一次查询同时得到 `xml` + 时间）；`feed_cache_get` **保留**（向后兼容，`tests/test_cache.py` 全绿）。**禁止**在 server 侧"先 `feed_cache_get` 再单独查条目"——两次查询会拾取降级态下的陈旧条目，把旧时间冒充当前表示的 `Last-Modified`（`server.md` BR-SRV-38）。★ **v1.8 / F1**：`Last-Modified` 改取 `last_modified`（表示变更时刻），**不是** `time`。

### 2.5 保留并调整的内部接口（**兼容清单**）

| 名称 | 现状签名 | 目标签名 | 兼容性 |
|------|---------|---------|--------|
| `cache` | `dict` | `collections.OrderedDict` | `OrderedDict` 是 `dict` 子类；`cache.get/[k]=/in/len/del` 全部不变 |
| `feed_cache` | `dict` | `collections.OrderedDict` | 同上 |
| `_cache_lock` | `Lock` | 不变 | utils.py 用于 jin10 header 槽，保留 |
| `_feed_cache_lock` | `Lock` | 不变 | server import 保留 |
| `feed_cache_get_entry(path)` | — | **新增（★ v1.5；★ v1.8 / F1 扩字段；★ v1.13 非映射守卫）**：命中返回新鲜条目**浅拷贝**（六字段 `xml/time/last_modified/fingerprint/last_access/expires_at`），否则 `None`；★ v1.13：真值**非映射**条目 ⇒ `_warn_feed_degraded_once('entry is not a mapping', path)` + 视同 `None`（**不抛 `AttributeError`**） | 公开名；`feed_cache_get` 实现于其上（BR-CACHE-32 / BR-CACHE-36） |
| `feed_cache_put(path, xml, ttl)` | `-> None` | **`-> dict`（★ v1.8 / F5）+ 第 4 位 `fingerprint=None`（★ v1.8 / F1）**：返回写入条目浅拷贝；指纹相同（即使上一条目已过期）⇒ 继承 `last_modified`；★ v1.13：非映射 `prev` ⇒ **不继承**（`isinstance(prev, dict)` 守卫，否则 `.get` 抛） | 公开名；`server._get_or_fetch_feed` 直接消费返回值（BR-CACHE-33/34 / `server.md` BR-SRV-48） |
| `feed_fetch_acquire(key)` | — | **新增（★ v1.9 / F8 / BR-CACHE-35）**：持 `_feed_fetch_locks_lock` 建锁（必要时）+ 引用计数 +1，返回 `Lock` | 公开名（新）；`server._get_or_fetch_feed` 消费（`server.md` BR-SRV-50） |
| `feed_fetch_release(key)` | — | **新增（★ v1.9 / F8 / BR-CACHE-35）**：持同一锁递减计数；**归零即 `pop` 锁与计数（两表同删）** | 公开名（新）；必须与 `acquire` 成对（异常路径也在 `finally` 释放） |
| `_feed_fetch_locks` / `_feed_fetch_refs` | `_feed_fetch_locks: dict` | **内部**：锁表 + 引用计数表，**同受 `_feed_fetch_locks_lock`**；仅经上面两原语读写 | 既有名保留（测试可白盒断言）；server 不再直接 import |
| `_fetch_inflight` | `dict` | 不变（测试 patch 依赖此名） | 测试 `test_server.py:306,342` 直接 patch |
| `MAX_CACHE_SIZE` | `2000` | 不变（URL 缓存上限 + 负缓存上限） | — |
| `CACHE_JITTER` | `0.2` | 不变 | server.py:47 import 保留 |
| `_CACHE_SWEEP_INTERVAL` | `60.0` | 不变（**清扫间隔，非域 TTL**，不受"禁裸 TTL 字面量"约束） | — |
| `_sweep_expired(d)` | `(d) -> int` | **返回/签名不变**；★ v1.13 判定式补 `isinstance(entry, dict)`（**保留假值条目、跳过真值非映射条目**） | `test_server.py:251-265` 断言依赖；BR-CACHE-13 / §10#30 |
| `_cache_put(d, key, value, ttl=None)` | 4 参 | `(d, key, value, ttl=None, metric_key='url')` | 纯新增可选参数；utils 仅 import 未调用 |
| `_expires_at(ttl=None)` | 默认 `CACHE_TTL` | 默认 `cache_policy('news_url')['ttl']` | 内部 |
| `_fill_missing` | 不变 | 不变 | server/stock_api import |
| `_fallthrough_sem` | `Semaphore(2)` | **删除** | 与 fall-through 路径同时删；无外部引用 |
| `MAX_FEED_CACHE_SIZE` | `100` | **删除** | server.py:47,663 必须同批迁到 `cache_policy('feed')['cache_max']` |
| `_HISTORY_AGE` | — | **新增** `600.0`（失败历史老化窗口，**缓存机制常量**，非域 TTL；BR-CACHE-20） | 新增内部名；无外部引用 |
| `_has_failure_history(url)` | 内部 | **替换**为 `_fetch_budget(url) -> int`（融合老化判定 + 递增阶梯入口） | **新增内部函数名**；无外部引用（T-CACHE-1/5 白盒断言随 §8 更新） |
| `_probe_budget(fail_count)` | — | **新增**（P7b）：`PROBE_TIMEOUT(2s)` 起步、每级 ×2、**`_PROBE_BUDGET_CAP(5.0)` 封顶**（★ v1.3 更正，**非** `REQUEST_TIMEOUT`）；`fail_count < 1` 视同 1 | 新增内部名；`_fetch_budget` 的唯一预算计算器 |
| `_PROBE_BUDGET_CAP` | — | **新增**（v1.3 / AC-S3 裁决）`5.0`（秒，**缓存机制常量**，**不注册为 env**） | 新增内部名；`_probe_budget` 的封顶；无外部引用 |
| `_effective_timeout(url, deadline=None)` | — | **新增**（P7b）：`min(_fetch_budget(url), max(0.05, deadline-now))`；`deadline` 已过 ⇒ 返回 `None` | leader 网络超时唯一计算点 |
| `_follower_wait_budget(url, deadline=None)` | — | **新增**（P7b）：`_fetch_budget(url) + _FOLLOWER_WAIT_MARGIN`，按 deadline 截断（下限 0.0） | follower 等待窗口唯一计算点 |
| `_FOLLOWER_WAIT_MARGIN` | — | **新增** `1.0`（秒，缓存机制常量） | 吸收 leader 取数后发布的调度抖动 |
| `_record_hit_locked()` | — | **新增**（P7b）：持 `_cache_lock` 时自增 `_cache_stats['hit']`，返回 `(hit, miss, entries)` 三元组 | 段①/③双检/④ 三处命中统一计数 |
| `_publish_url_stats(hit, miss, entries, metric_key='url')` | — | **新增**（P7b）：**锁外**发布 `cache_entries` + `cache_hit_ratio` | metrics 发布的唯一入口（S1-4 落点） |
| `import json` | 未使用 | **已删除**（§10#6 收口） | 清洁化；不涉契约 |
| `_cache_fresh(entry, refresh_epoch=None)` | — | **新增**（v1.4）：`now < expires_at` 且（`refresh_epoch is None or entry['time'] >= refresh_epoch`）；段①/③/④ 唯一新鲜度判定 | 新增内部名；`None` ⇒ 与旧行为逐字一致 |
| `urlopen(req, timeout=None)` | 直用 `urllib.request.urlopen` | **新增**（v1.4）：**模块级**池化 drop-in，测试打桩的唯一网络缝（签名 `(req, timeout=None)`） | 公开名；§2.7 / BR-CACHE-26..30 |
| `warm_transport(hosts=None, count=None, timeout=None) -> int` | — | **新增**（v1.4）：走池预热 DNS+连接，**仅握手不发业务请求**，总函数（绝不抛） | 公开名；`server.main` 启动守护线程调用（§2.7 / BR-CACHE-30） |
| `_ConnectionPool(max_per_host, idle_ttl)` / `_pool` | — | **新增**（v1.4）：per-key keep-alive 池；`_pool` 为模块级单例（`HTTP_POOL_MAX_PER_HOST` / `HTTP_POOL_IDLE_TTL`） | 新增内部名 |
| `_DNSResolver(ttl)` / `_resolver` | — | **新增**（v1.4）：`getaddrinfo` TTL 缓存；`_resolver` 单例（`HTTP_DNS_CACHE_TTL`） | 新增内部名 |
| `_pool_request(method, url, headers, timeout)` / `_send(conn, method, path, headers)` / `_open_connection(key, timeout)` / `_PooledResponse` / `_PooledHTTP(S)Connection` / `_CachedDNSConnection` / `_close_quietly` | — | **新增**（v1.4）：池化请求实现（§2.7） | 新增内部名；无外部引用 |
| `_MAX_REDIRECTS(5)` / `_REDIRECT_CODES` / `_STALE_CONNECTION_ERRORS` | — | **新增**（v1.4）：重定向与失效连接判定（机制常量） | 新增内部名 |

### 2.6 `fetch_json` 全部调用点兼容策略（**18 处，逐一列名**）

**编码维度**：新增 `encoding` 为**第 4 位可选参数**，18 处均为 `url`/`headers` 位置传参 + `ttl=` 关键字传参 → **编码改动零调用点改动**（SAD §2.3 D-5 "保持既有 18 个调用点零改动"，已核对属实）。

**TTL 维度**（D1-D4 收敛，须同批改）：

| # | 位置 | 域 | 现状 ttl 来源 | 目标 ttl 来源 | encoding |
|---|------|----|--------------|--------------|----------|
| 1 | `server.py:81` `handle_cls_telegraph` | news_url | `_trading_tiers()['L3']` | `cache_policy('news_url')['ttl']` | utf-8 |
| 2 | `server.py:90` `handle_eastmoney_kuaixun` | news_url | 同上 | 同上 | utf-8 |
| 3 | `server.py:122` `handle_ths_kuaixun` | news_url | 同上 | 同上 | utf-8 |
| 4 | `server.py:217` jin10 flash | news_url | 同上 | 同上 | utf-8 |
| 5 | `server.py:230` wallstreetcn | news_url | 同上 | 同上 | utf-8 |
| 6 | `server.py:311` `handle_cls_hotplate`（循环 industry/concept/area 三档） | plate | `_BASE_TTL(=tiers['L2']) + _TTL_OFFSETS[ptype]`（= `+0` / `+_STAGGER` / `+_STAGGER*2`） | `cache_policy('plate')['ttl']` **+ handler 派生 stagger**（offset = `_STAGGER × 分区序`，`_STAGGER = max(3, ttl//4)`） | utf-8 |
| 7 | `server.py:353` plate info | plate | `_BASE_TTL(=tiers['L2']) + 0`（分区序 0） | `cache_policy('plate')['ttl']`（分区序 0，无 offset） | utf-8 |
| 8 | `server.py:365` plate stocks | plate | `_BASE_TTL(=tiers['L2']) + _STAGGER`（分区序 1） | `cache_policy('plate')['ttl']` **+ handler 派生 stagger**（分区序 1 ⇒ ×1.25） | utf-8 |
| 9 | `server.py:377` plate industry | plate | `_BASE_TTL(=tiers['L2']) + _STAGGER*2`（分区序 2） | `cache_policy('plate')['ttl']` **+ handler 派生 stagger**（分区序 2 ⇒ ×1.5） | utf-8 |
| 10 | `stock_api.py:268` `fetch_cls_fundflow` | fundflow | `tiers['L1']` | `cache_policy('fundflow')['ttl']` | utf-8 |
| 11 | `stock_api.py:360` `fetch_cls_timeline` | timeline | `tiers['L1']` | `cache_policy('timeline')['ttl']` | utf-8 |
| 12 | `stock_api.py:641` basic_info phase1 | quote | `_MAX_CACHE_AGE` | `cache_policy('quote')['ttl']` | utf-8 |
| 13 | `stock_api.py:651` basic_info detail | quote | `_MAX_CACHE_AGE` | `cache_policy('quote')['ttl']` | utf-8 |
| 14 | `stock_api.py:693` `fetch_cls_announcement` | announcement | 裸 `ttl=15` | `cache_policy('announcement')['ttl']`（Q5） | utf-8 |
| 15 | `stock_api.py:779` `handle_cls_stock` | quote | `_MAX_CACHE_AGE` | `cache_policy('quote')['ttl']` | utf-8 |
| 16 | `market_api.py:30` `fetch_margin` | margin | `_MARGIN_CACHE_TTL`(600) | `cache_policy('margin')['ttl']`(=600) | utf-8 |
| 17 | `utils.py:108` jin10 homepage | news_url | 默认 `None`(→300) | 默认 `None`(→ policy news_url) | utf-8 |
| 18 | `utils.py:121` jin10 bundle | news_url | 默认 `None`(→300) | 默认 `None`(→ policy news_url) | utf-8 |
| **+19/20** | `server.handle_ths_longhu`（**新增**走统一入口，R15） | longhu | 现状**直连 urlopen 绕过缓存** | `cache_policy('longhu')['ttl']`(=300) | **`encoding='gbk'`** |

> ⚠️ **stagger 承接脚注（REV-DES-01 / D-7 / SAD §2.1 原文）**：本表 #6–#9 的「目标 ttl 来源」**仅列基值** `cache_policy('plate')['ttl']`（L2 ⇒ 盘中 12 / 非盘中 120）。SAD §2.1 **明令保留**的**三档分区 stagger 不是 policy 的第四维**，而由 **handler 从 policy 基值派生**：
> - `_STAGGER = max(3, ttl // 4)`（`ttl` = `cache_policy('plate')['ttl']`）；
> - `offset = _STAGGER × 分区序`；分区序：`industry`/`info` = 0、`concept`/`stocks` = 1、`area`/`industry` = 2；
> - 等价 `ttl × (1, 1.25, 1.5)`（L2=12 ⇒ 12/15/18；L2=120 ⇒ 120/150/180）；属 policy 派生、非裸字面量。
>
> **编码者不得按本表字面把四者替换为同一个 `cache_policy('plate')['ttl']`** —— 那会**静默丢弃三档错峰**（plate 三块同 TTL，行为回归，SAD 明确禁止）。**派生公式的精确落点由 `server.md` 承接**（本表不重复实现细节）。

> 兼容性结论：**签名向后兼容（编码零改动）**；**行为按 D1-D4 变更**（TTL 来源统一、失败类型变 `FetchError`、LRU 取代 FIFO、新增负缓存）。所有调用点的 `except Exception` 继续覆盖；`utils.warm_jin10_headers` 已 `except Exception: pass` ✓。
> `/ths/longhu` 计数口径：两个不同 URL 各回源 1 次、共 2 次；连续 10 次请求其余 9 次命中（AC-E9）。

### 2.7 HTTP 传输子层（v1.4 新增，**唯一触网出口**）

> `fetch_json` 是项目唯一的 HTTP egress；自 v1.4 起它经本模块的 `urlopen` 触网，而**不再**直用 `urllib.request.urlopen`。动机（`config.py` 实测注）：2C2G 节点上单请求 ~340ms，其中 DNS ~176ms、TCP+TLS 握手 ~78ms；keep-alive + DNS 缓存后复用请求 ~48ms。50 码 quote 冷扇出实测 ~4.2s（超 0.8×tick 预算），故新增进程启动预热。

```python
def urlopen(req, timeout=None) -> _PooledResponse:
    """池化 drop-in（http/https）；测试打桩的唯一网络缝。

    入参为 fetch_json 构造的 Request（也接受 URL 字符串）；返回带 read() 的
    上下文管理器，status/headers 可用。跟随 ≤ _MAX_REDIRECTS(5) 次重定向
    （301/302/303/307/308 + Location）；status >= 400 抛 urllib.error.HTTPError；
    传输失败抛 urllib.error.URLError —— 与 stdlib 契约一致（_classify 与全部调用方依赖它）。
    """

def warm_transport(hosts=None, count=None, timeout=None) -> int:
    """进程启动预热 DNS + 池化连接（总函数，绝不抛，不发业务请求）。

    hosts 缺省取 config.warm_hosts()；count 缺省 HTTP_WARM_CONNECTIONS，
    timeout 缺省 HTTP_WARM_TIMEOUT。逐 host 拨号，失败静默换下一个 host；
    返回本次新置入池中的连接数。由 server.main 的启动守护线程调用。
    """
```

**池化语义（`_ConnectionPool`，键 = `(scheme, host, port)`）**

| 行为 | 规则 |
|------|------|
| **获取** | 有空闲 ⇒ LIFO 取出一条（`reuse`）；`conn.sock.settimeout(timeout)` 失败（checkout 与复用之间已死）⇒ 释放槽位并改走新建 |
| **有界** | 每 key 至多 `HTTP_POOL_MAX_PER_HOST` 条**池内**连接；达到上限且无空闲 ⇒ 开一条短命 **ephemeral** 连接、请求后即关（**不排队**——排队会把池本要保留的并发重新串行化；ephemeral 从不回池） |
| **淘汰** | 空闲超过 `HTTP_POOL_IDLE_TTL` 的连接在下一次 checkout 时**懒关闭**（无 reaper 线程）；`release` 时 `len(bucket) > max_per_host` 亦溢出关闭 |
| **愈合** | 请求抛 `_STALE_CONNECTION_ERRORS`（`RemoteDisconnected`/`BadStatusLine`/`CannotSendRequest`/`CannotSendHeader`/`ConnectionResetError`/`BrokenPipeError`）⇒ 丢弃该连接；**仅当本次是复用（reused）且首次尝试**才在新连接上**重试一次**（真失败的上游不会被翻倍预算） |
| **锁纪律** | `_pool._lock` **只护桶记账**（`_idle`/`_live`/`stats`）；`connect`/`close`/请求 IO **一律在锁外** |
| **统计** | `_pool.stats = {reuse, new, stale, evicted, ephemeral}`（仅供观测，非 metrics 注册名） |

**DNS 语义（`_DNSResolver`）**

- 以 `socket.getaddrinfo(host, port, type=SOCK_STREAM)` 填充缓存，键 `(host, port)`，TTL = `HTTP_DNS_CACHE_TTL`；上限 `_MAX_ENTRIES=256`（超限先清过期、再按插入序淘汰）。
- **失败不缓存**；`ttl <= 0` 完全关闭缓存。
- 连接仍按**主机名**拨号（TLS 的 SNI 与证书主机名校验不变）——只缓存 name→address。
- 缓存地址连不上时，`connect` 以 `force=True` **重解析一次**再试；解析器异常/空结果 ⇒ 回退 `socket.create_connection`（由 stdlib 抛 gaierror）。

**预热语义（`warm_transport`）**

- 逐 host、逐 count 次 `_pool.acquire` → 立即 `_pool.release`（**只握手，不发业务请求**）；某 host 拨号失败 ⇒ `break` 换下一 host；已复用到既有热身连接或池满（ephemeral）⇒ `break`（该 host 无需再加）。
- **总函数**：`warm_hosts()` 取值异常亦被吞（返回 0）；调用方（启动守护线程）不等待结果、不 gate 启动或 `/healthz`。

---


## 3. 数据结构

### 3.1 URL 缓存条目 / feed 缓存条目 / 负缓存条目（yaml）

```yaml
cache: # OrderedDict[url -> Entry]，上限 MAX_CACHE_SIZE=2000，真 LRU
  "<url>":
    data: <str>            # 解码后正文
    time: <float>          # 写入时刻（保留：测试夹具与旧字段兼容）
    last_access: <float>   # 最近命中/写入时刻（真 LRU 证据，命中即更新）
    expires_at: <float>    # time + ttl*(1 ± CACHE_JITTER)，CACHE_JITTER=0.2

feed_cache: # OrderedDict[path -> Entry]，上限 = cache_policy('feed')['cache_max'](=100)
  "<path>":            # ★ v1.8 / F2：path 为不透明缓存键（PUBLIC_BASE_URL 未设时含 base_url）
    xml: <str>             # ★ v1.12：`''` 属「合法但空」⇒ 读侧照常命中（miss 判据恒为 `is None`，禁真值化简）
    time: <float>          # 写入时刻；供 refresh_epoch 新鲜度下限（BR-CACHE-31）；★ v1.8：不再作 Last-Modified
    last_modified: <float|null> # ★ v1.8 / F1：表示最后一次变更的时刻 ⇒ server 的 Last-Modified 权威来源（BR-SRV-38）；
                                #   ★ v1.10 / P2-1：legacy/注入条目缺字段 ⇒ null（不发 Last-Modified、禁用 IMS），绝不抛 KeyError
    fingerprint: <str|null># ★ v1.8 / F1：规范化摘要（与 ETag 同源）；相同 ⇒ 跨 TTL 继承 last_modified
    last_access: <float>
    expires_at: <float>

_negative: # dict[url -> NegEntry]，上限 MAX_CACHE_SIZE=2000
  "<url>":
    until: <float>                       # 门禁到期时刻 = 失败时刻 + NEG_TTL(5)
    kind: upstream_timeout|upstream_error # 枚举，写入时已分类
    fail_count: <int>                    # 连续失败次数（成功即整条清除）
    first_at: <float>                    # 当前"连续失败段"起点（BR-CACHE-20 老化口径；
                                         #   不由后续失败刷新，成功/满额淘汰即随条目消失）
# 语义：now < until ⇒ 段 2 立即 raise；now >= until ⇒ 门禁失效，但
#       条目保留作"失败历史" ⇒ 段 3 半开探测：
#         已老化（now - first_at >= _HISTORY_AGE）→ REQUEST_TIMEOUT(10s) 全预算一次
#         未老化 → _probe_budget(fail_count) 递增阶梯（P7b；★ v1.3 更正封顶）：
#                  fail_count 1→2s、2→4s、≥3→_PROBE_BUDGET_CAP(5s) 封顶
#         （老化窗口 600s，消除"慢而 >2s 上游永久停在 2s 探测"的死锁，见 BR-CACHE-20；
#           递增阶梯消除"同一死锁在老化窗口内的长滞留"，见 BR-CACHE-22；
#           封顶 5s ⇒ 持续黑洞稳态周期 ≈ 5s 探测 + 5s NEG_TTL = 10s，P95 ≈ 5s）
```

### 3.2 `FetchError.KINDS` 与错误码值域（yaml）

```yaml
FetchError:
  KINDS: [upstream_timeout, upstream_error, cdp_unavailable]
  attrs: {kind: str, url: str|null, cause: BaseException|null}
  invalid_kind: raise ValueError   # 禁止自由文本进入 _errors
```

### 3.3 `build_batch_response` 输入输出（yaml）

```yaml
input:
  requested: [sh600519, sz000001, badcode]      # 保序
  results:   {sh600519: {price: 1.2}, sz000001: null}
  errors:    {sz000001: upstream_timeout}       # 可为 null/缺省
  dropped:   20                                 # 0 ⇒ 不挂截断键

output:            # 扁平映射，插入序 = requested 序
  sh600519: {price: 1.2}
  sz000001: null
  badcode: null
  _errors: {sz000001: upstream_timeout}         # 仅非空时出现
  _truncated: true                              # 仅 dropped>0
  _dropped_count: 20                            # 与 _truncated 同现
```

### 3.4 值域三分（唯一判别式，消费方据此写代码）

```yaml
success:  值 = 数据客体
no_data:  值 = null 且 code ∉ _errors      # 无数据 / 无效码（既有语义不变）
failure:  值 = null 且 code ∈ _errors      # 取数失败（本次新增可辨识）
```

### 3.5 模块级状态

```yaml
cache: OrderedDict            # 受 _cache_lock
feed_cache: OrderedDict       # 受 _feed_cache_lock
_negative: dict               # 受 _neg_lock
_fetch_inflight: dict[url -> threading.Event]   # 受 _cache_lock
_feed_fetch_locks: dict[cache_key -> Lock]      # 受 _feed_fetch_locks_lock；★ v1.9 / F8：仅经 feed_fetch_acquire/release 读写
_feed_fetch_refs: dict[cache_key -> int]        # ★ v1.9 / F8：引用计数（同受 _feed_fetch_locks_lock）；归零与锁一同 pop
_cache_stats: {hit: int, miss: int}             # 受 _cache_lock（Q1 观测项，非 AC）
_last_cache_sweep/_last_feed_sweep: float       # 各自受对应容器锁
_HISTORY_AGE: 600.0                             # 失败历史老化窗口（机制常量）
_PROBE_BUDGET_CAP: 5.0                          # ★ v1.3：半开探测阶梯封顶（机制常量，AC-S3 裁决；非 env）
_FOLLOWER_WAIT_MARGIN: 1.0                      # follower 等待余量（机制常量，P7b）
MAX_CACHE_SIZE: 2000 / CACHE_JITTER: 0.2 / _CACHE_SWEEP_INTERVAL: 60.0
_PROBE_BUDGET_CAP / _FOLLOWER_WAIT_MARGIN / _HISTORY_AGE 见上（机制常量，非 env）
```

### 3.6 HTTP 传输状态（v1.4，yaml）

```yaml
_pool: _ConnectionPool(HTTP_POOL_MAX_PER_HOST=24, HTTP_POOL_IDLE_TTL=60.0)
  _lock:    threading.Lock          # 只护桶记账；connect/close/IO 全在锁外（BR-CACHE-27）
  _idle:    dict[key -> [(conn, idle_since), ...]]   # key = (scheme, host, port)；LIFO
  _live:    dict[key -> int]        # 该 key 的池内连接数（≤ max_per_host）
  stats:    {reuse, new, stale, evicted, ephemeral}  # 观测用，非 metrics 注册名

_resolver: _DNSResolver(HTTP_DNS_CACHE_TTL=300.0)
  _ttl:     float                   # <=0 ⇒ 禁用缓存
  _lock:    threading.Lock          # 只护 _cache 读写
  _cache:   dict[(host, port) -> (expires_at, infos_tuple)]
  _MAX_ENTRIES: 256                 # 超限先清过期，再按插入序淘汰

# 传输常量（机制常量，非域 TTL，非 env）
_MAX_REDIRECTS: 5
_REDIRECT_CODES: {301, 302, 303, 307, 308}
_STALE_CONNECTION_ERRORS: (RemoteDisconnected, BadStatusLine, CannotSendRequest,
                           CannotSendHeader, ConnectionResetError, BrokenPipeError)
```

---

## 4. 业务规则（编号供伪代码与测试引用）

### 4.1 TTL 派生与新鲜度

| 编号 | 规则 |
|------|------|
| **BR-CACHE-1** | 正缓存有效性 = `now < expires_at`；`expires_at = 写入时刻 + ttl × (1 ± jitter)`，`jitter = random.uniform(-0.2, 0.2)`。**语义（R10 文档化）：过期 = 拒读旧值 + 必触发一次回源尝试**，绝不返回过期值（AC-A4）。±0.5s 时钟容差由测试侧处理。 |
| **BR-CACHE-2** | `ttl=None` ⇒ `ttl = cache_policy('news_url')['ttl']`。**禁止在 cache.py 出现域 TTL 数字字面量**；`_CACHE_SWEEP_INTERVAL=60`/`CACHE_JITTER=0.2`/`MAX_CACHE_SIZE=2000`/`_HISTORY_AGE=600` 属**缓存机制常量**，非域 TTL。 |
| **BR-CACHE-3** | `NEG_TTL`/`PROBE_TIMEOUT` 只从 `config` 读；负缓存**不加抖动**（确定性，便于 AC-S3 断言）。`_HISTORY_AGE` 为本模块机制常量（0 抖动）。 |

### 4.2 负缓存与半开探测（RC-2 / ADR-003）

| 编号 | 规则 |
|------|------|
| **BR-CACHE-4** | 段 2 判定：`_negative.get(url)` 存在且 `now < until` → 立即 `raise FetchError(kind)`，**不触网**（目标 <1ms）。 |
| **BR-CACHE-5** | 段 3 超时预算由 `_effective_timeout(url, deadline)` 决定：基础值 `_fetch_budget(url)` = 无条目 → `REQUEST_TIMEOUT=10s`；有条目且**已老化**（`now - first_at >= _HISTORY_AGE`）→ `REQUEST_TIMEOUT=10s`（BR-CACHE-20）；有条目且**未老化** → `_probe_budget(fail_count)` **递增阶梯**（BR-CACHE-22）。若给了 `deadline`，最终值 = `min(基础值, max(0.05, deadline-now))`；`deadline` 已过 ⇒ 返回 `None` ⇒ 本地超时（不触网、不写负缓存）。半开探测**仅**对失败历史 URL 生效 ⇒ 首次冷请求与正常慢回源仍用 10s（AC-E2 不误伤）。 |
| **BR-CACHE-6** | 失败写入：`until = now + NEG_TTL`，`kind = _classify(exc)`，`fail_count += 1`（沿用既有条目则累加），`first_at` 按 BR-CACHE-20 维护（未老化则保留、老化/新建则置 `now`）；同步 `metrics.incr('upstream_fail_total', key=kind)`、`metrics.set_gauge('negative_cache_size', len(_negative))`。 |
| **BR-CACHE-7** | 成功即 `_negative.pop(url)`（**清除失败历史**），使下一次失败重新以 10s 冷预算开始（避免永久 2s 探测掩盖"刚恢复又慢"）。 |
| **BR-CACHE-8** | **"失败历史"必须跨 NEG_TTL 窗口保留**（否则半开探测无法生效）：过期条目不删除，仅在①成功 ②`len(_negative) >= MAX_CACHE_SIZE` 时淘汰最早 `until` 的一条。**若改为"过期即删"**，则门禁无法跨窗生效、每次请求都会重新触网 ⇒ 故障期上游请求量随请求数线性放大（RC-2 复发）。<br>⚠️ **P7b 口径更正 + v1.3 封顶更正**：v1.1 此处曾据"每轮 `2s(探测)+5s(负缓存)`"推出"稳态 P95 ≤ 2s"。自 `_probe_budget` **递增阶梯**（BR-CACHE-22）落地后，该推导**仅对"失败次数少"的早期轮次成立**；而自 **v1.3 的 `_PROBE_BUDGET_CAP=5s` 封顶**后，持续黑洞的上游收敛到 **5s 探测**（**不是** `REQUEST_TIMEOUT(10s)`）⇒ 稳态周期 ≈ `5s(探测) + 5s(门禁) = 10s`。**AC-S3 模式 B 的量化口径见 §10#11（v1.3 重写）**。 |
| **BR-CACHE-9** | follower **绝不重入选举**：等待 leader 结束后只读状态。follower 等待时长 = `_follower_wait_budget(url, deadline)` = `_fetch_budget(url) + _FOLLOWER_WAIT_MARGIN(1.0s)`，并按剩余 `deadline` 截断（BR-CACHE-23）。`event.wait` 后按序：正缓存命中 → 返回（计 hit）；负缓存（**忽略过期**）→ `raise FetchError(kind)`；`url in _fetch_inflight`（leader 仍存活）→ `raise FetchError('upstream_timeout')`（**不写负缓存、不计失败**）；三者皆无 → `raise FetchError('upstream_error')`（fail-closed 兜底，BR-CACHE-21）。 |
| **BR-CACHE-20** | **失败历史老化（逆向审查 1）**：`NegEntry.first_at` 记录当前**连续失败段**起点，**不由后续失败刷新**。判定预算时 `now - first_at >= _HISTORY_AGE(600s)` ⇒ **视同无失败历史**，本次用 `REQUEST_TIMEOUT`(10s) **全预算探测一次**；`_record_failure` 在 `aged` 时把 `first_at` 重置为 `now`（开启新窗口）。**效果**：慢而 >2s 的上游**至多每 600s 获得一次全预算机会**，一旦成功即按 BR-CACHE-7 清除历史 → 不再永久停在 2s 探测、与 AC-E2 长期互斥。**与 BR-CACHE-22 的分工**：老化窗口管"上限机会"（600s 一次全预算），递增阶梯管"渐进预算"（同一失败段内逐级加码）。**AC-S3 影响量化见 §10#11（P7b 重写）**。 |
| **BR-CACHE-21** | **deadline 形参与闸门位置（P7b）**：`deadline` 是**第 5 位可选位置参数**（绝对 epoch 秒），既有调用点零改动。闸门有**两处**且**都在段 1 正缓存命中之后**：① 段 1 未命中且 `deadline - now <= 0` ⇒ 立即 `raise FetchError('upstream_timeout')`；② 段 3 选举后 `_effective_timeout` 返回 `None` ⇒ 同一异常。两处均**不触网、不写负缓存**（这是"调用方自己的预算"，不是上游失败）。**理由**：命中缓存零网络、零延迟，调用方耗尽的批量预算不得拒掉已持有的数据——否则缓存永远救不了它本该吸收的慢批次。 |
| **BR-CACHE-22** | **递增半开探测阶梯（P7b；★ v1.3 按 AC-S3 裁决更正封顶）**：`_probe_budget(fail_count)` = 从 `PROBE_TIMEOUT(2s)` 起步、每级 ×2、**以 `_PROBE_BUDGET_CAP(5.0s)` 封顶**（模块级机制常量，**不注册 env**；**不是** `REQUEST_TIMEOUT`）；`fail_count < 1` 视同 1。序列：`1→2s`、`2→4s`、`3→5s`、`≥4→5s`。**`REQUEST_TIMEOUT(10s)` 的独立角色**：仅用于"无失败历史"（段 3 冷预算）与"失败段已老化 ≥`_HISTORY_AGE`"（BR-CACHE-20 一次性全预算探测）两支，**不参与阶梯**。**效果**：① 慢而"仍活着"（如需 ~5s）的上游可在**数个失败周期内**把历史清掉，而不必苦等 `_HISTORY_AGE=600s`；② **持续黑洞的稳态预算被钉在 5s** ⇒ 周期 ≈ `5s 探测 + 5s NEG_TTL = 10s`、慢请求占比 ≈50% ⇒ **P95 ≈ 5s**、单请求 ≤15s（AC-E2）；`fail_count` 由 BR-CACHE-6 每次失败递增，成功即整条清除（BR-CACHE-7）。 |
| **BR-CACHE-23** | **follower 等待窗口与 `leader_alive` 三态（P7b）**：① 等待窗口 = `_fetch_budget(url) + _FOLLOWER_WAIT_MARGIN(1.0s)`（再按 deadline 截断）——余量只吸收 leader 取数后发布的调度抖动，**不是网络预算**；② `event.wait` 返回后**必须复查 `url in _fetch_inflight`**：leader 仍在飞 ⇒ `raise FetchError('upstream_timeout')`（**不写负缓存、不计 `upstream_fail_total`**，与 cache.md S1-1 同源规则）；③ 仅"无正缓存 ∧ 无负缓存 ∧ 无活 leader"才是 `upstream_error`（fail-closed，不触网）。 |
| **BR-CACHE-24** | **metrics 一律锁外发布（P7b / S1-4）**：`_publish_url_stats(hit, miss, entries, metric_key)` / `_record_failure` 的 `incr`+`set_gauge` / `_clear_negative` 的 `set_gauge` / `feed_cache_put` 的 `set_gauge` 均在**释放对应业务锁之后**调用。锁内只做"读取需要一致的少量标量"（如 `_cache_stats` 的 hit/miss、`len(cache)`）。**命中路径（段①/段③双检/段④）统一经 `_record_hit_locked()` 计 hit**——只计段①会按"并发/慢上游流量"的比例把 `cache_hit_ratio` 系统性压低，而该 gauge 存在的意义正是观测这部分流量。 |
| **BR-CACHE-25** | **leader 令牌不泄漏（P7b）**：选举成功后的**全部**逻辑（`_effective_timeout` 求值、网络 IO、cache 写回）置于 `try/finally`；`finally` 内先 `with _cache_lock: _fetch_inflight.pop(url, None)`，再 `event.set()`（释锁后 set，避免唤醒的 follower 立即争锁）。⇒ 任何异常（含预算计算与 `Request` 构造）都不会让该 URL 的选举令牌永久残留；否则此后每次请求都会沦为"等待一个已死的 leader"并超时。 |

### 4.5 HTTP 传输（v1.4 新增，BR-CACHE-26..31）

| 编号 | 规则 |
|------|------|
| **BR-CACHE-26** | **触网唯一出口 = `cache.urlopen(req, timeout=None)`**：`http`/`https` 之外 scheme 或缺失 host ⇒ `URLError`；返回对象须可 `read()` 且支持 `with`；**status ≥ 400 抛 `HTTPError`**（带 `resp_headers`）；传输异常统一包成 `URLError`（保持 `_classify` 与既有调用方的 stdlib 契约）。跟随即 `_REDIRECT_CODES`（301/302/303/307/308）且 `Location` 非空，≤ `_MAX_REDIRECTS(5)`（超限抛 `HTTPError`）。 |
| **BR-CACHE-27** | **池化连接**：按 `(scheme, host, port)` 分桶；空闲复用 LIFO；每桶**池内**连接 ≤ `HTTP_POOL_MAX_PER_HOST`（达上限且无空闲 ⇒ ephemeral，用完即关、**不排队**）；空闲 > `HTTP_POOL_IDLE_TTL` 懒淘汰；`release` 溢出（`len(bucket) > cap`）关闭。 |
| **BR-CACHE-28** | **失效连接丢弃并重试一次**：请求抛 `_STALE_CONNECTION_ERRORS` ⇒ `note_stale` + `discard`；**仅当 `reused and attempt == 0`** 才在新连接上重试一次（`for attempt in (0, 1)`），否则 `URLError`。超时（`socket.timeout`/`TimeoutError`）与 `URLError`/`OSError`/`HTTPException` 一律不重试（直接丢弃并上抛）。 |
| **BR-CACHE-29** | **DNS TTL 缓存**：仅缓存 `getaddrinfo` 结果（键 `(host, port)`，TTL `HTTP_DNS_CACHE_TTL`，上限 `_MAX_ENTRIES=256`）；**失败不缓存**；`ttl <= 0` 禁用；仍按主机名拨号（SNI/证书校验不变）；缓存地址连接失败 ⇒ `force=True` 重解析一次；解析异常/空结果 ⇒ 回退 `socket.create_connection`。 |
| **BR-CACHE-30** | **`warm_transport` 为总函数**：**仅拨号不发业务请求**；`hosts`/`count`/`timeout` 分别缺省 `warm_hosts()` / `HTTP_WARM_CONNECTIONS` / `HTTP_WARM_TIMEOUT`；单 host 失败静默换下一个；已热身/池满即 `break`；返回新入池连接数；**绝不抛**。 |
| **BR-CACHE-31** | **`refresh_epoch` 新鲜度下限（v1.4）**：正缓存命中判定统一为 `_cache_fresh(entry, refresh_epoch)`：`now < expires_at` **且**（`refresh_epoch is None or entry['time'] >= refresh_epoch`）。段①/③/④ 一律传同一 `refresh_epoch`；`None` ⇒ 与 v1.3 行为逐字一致。**写路径不感知该参数**（`_cache_put` 仍写完整域 TTL）⇒ REST/预取在窗口内仍受正缓存保护。目的：消除"TTL == tick"时条目跨轮复用造成的相位耦合（名义 4s 刷新实际 8s）。 |

### 4.3 LRU 与双触发清扫（R3/R11 / ADR-008）

| 编号 | 规则 |
|------|------|
| **BR-CACHE-10** | 容器为 `collections.OrderedDict`；**命中路径** `move_to_end(key)` 且 `last_access = now`；**淘汰** `popitem(last=False)`（O(1)，最久未访问）。 |
| **BR-CACHE-11** | **触发①（定时全扫）**：写入时若 `now - _last_{cache,feed}_sweep >= _CACHE_SWEEP_INTERVAL(60)` → 对该容器全量 `_sweep_expired` 并更新该容器的时间戳。两容器**各自独立**计时。 |
| **BR-CACHE-12** | **触发②（写入时局部清扫）**：写入时若 `len(d) >= cap` → 先 `_sweep_expired(d)`，再 `while len(d) >= cap: d.popitem(last=False)`。`cap`：URL 缓存 `MAX_CACHE_SIZE=2000`；feed 缓存 `cache_policy('feed')['cache_max']`。 |
| **BR-CACHE-13** | `_sweep_expired(d)` 契约：返回删除条数；**保留假值条目**（`None` 等，读取路径自行处理）、**并跳过真值非映射条目**（★ v1.13 / P2-6 已防御）——判定式 `entry and isinstance(entry, dict) and now >= entry.get('expires_at', 0)`；非映射真值**无 `expires_at` 可比**，在此跳过（原 `entry.get` 会抛 `AttributeError`）；判定键仍 `expires_at`。**共享助手**：URL 缓存与 feed 缓存两条路径共用，**合法条目行为逐字不变**（仅畸形条目不抛）。 |
| **BR-CACHE-14** | 淘汰保证"被淘汰 URL 的下一次请求必然回源"（不得命中旧数据，AC-E6）。 |
| **BR-CACHE-32** | **feed 条目访问器 `feed_cache_get_entry(path) -> dict \| None`（★ v1.5；★ v1.8 / F1 扩字段）**：与 `feed_cache_get` **同源**——同一 `_feed_cache_lock`；`now < expires_at` 才命中；命中时 `move_to_end` + `last_access = now`（LRU 副作用**恰好一次**）；返回**浅拷贝** `{'xml','time','last_modified','fingerprint','last_access','expires_at'}`（调用方只读，不得原地改）。`feed_cache_get` 保留原签名，实现改为 `entry['xml'] if entry else None`（**语义逐字不变**）。用途：`server._serve_feed` 一次查询同时取 `xml` 与 **`last_modified`**（Last-Modified 时间源）；**禁止**用两次独立查询拼装（陈旧条目竞态）。**`path` 对 cache 层是不透明键**（★ v1.8 / F2）。**无新增锁、无 TTL/清扫/上限变更**（★ v1.8：条目新增 2 字段）。★ **v1.10 / P2-1**：`last_modified` 以 `entry.get('last_modified')`（缺省 `None`）读取——legacy / 非六字段条目缺该字段 ⇒ 返回 `None`（server 按"无 Last-Modified 时刻"降级、禁用 IMS），**不抛 `KeyError`**；`fingerprint` 同为 `entry.get('fingerprint')`。★ **v1.11 / 读侧 fail-safe 补全（P2-4）**：**`xml` 缺字段（或 `None`）⇒ 视同 miss（返回 `None`）**——绝不返回残缺体、绝不抛 `KeyError`；`time` 以 `entry.get('time')`（缺省 `None`）读取；`expires_at` 沿用 `entry.get('expires_at', 0)`（缺省 `0` ⇒ `now >= 0` 恒成立 ⇒ 自然判为过期 ⇒ 亦视同 miss）；`last_access` 由访问器自写、恒存在**不需 `.get`**。**与上文"有 `xml` 缺 `last_modified` ⇒ 仍照常服务、只是不发头"是两件事**。**原则**：读侧对形态不完整 **fail-safe 到「当成没有」/「降级为无该头」**，**不得 fail-loud 到「抛异常 → 被 `_guard` 误报为上游故障」** ★ **v1.12 / `''` 边界写死（读侧口径，防未来"化简"成永久回源环）**：miss 判据**恰好**是 `entry.get('xml') is None`（缺键或显式 `None`）；**`xml == ''` 属「合法但空」的表示 ⇒ 照常命中、照常服务**（返回 dict；`feed_cache_get` 返回 `''`），**不得**因"空"判为 miss——读侧**无法**区分"合法空表示"与"截断体"，若把 `''` 判 miss 会形成 **读 miss → 回源 → 写 `''` → 再 miss 的永久回源环**（缓存自我击穿），把"内容问题"放大为"上游负载问题"。**显式禁令**：**禁止**把判据写成 `not xml` / `if not entry.get('xml')` 之类**真值化简**（会把 `''` 与 `None` 等同）；重构/优化须保持 `is None` 字面语义 |
| **BR-CACHE-33**（★ v1.8 / F1 新增） | **feed 指纹继承 ⇒ `last_modified` = 表示最后一次变更的时刻**：`feed_cache_put` 写入前取**同一键的上一条目**（★ **即使该条目已过期也参与比较**——这正是「跨 TTL 重生成仍 304」的机制），当且仅当 `fingerprint is not None and prev.get('fingerprint') == fingerprint` ⇒ `last_modified = prev.get('last_modified')`（**继承**；★ v1.10 / P2-1：缺省 `None`——legacy / 非六字段条目指纹匹配但缺字段 ⇒ 新条目 `last_modified=None`，**不发 `Last-Modified`、禁用 IMS**，**不抛 `KeyError` 也不前进为写入时刻**）；否则 `last_modified = now`（**本次写入时刻**）。**无上一条目**（首次 / LRU 淘汰 / 已 sweep）⇒ `last_modified = now`（**退化为一次性 200 后恢复 304，属可接受降级**）。**`prev` 必须在触发①定时全扫 / 触发②容量清扫之前捕获**（否则被 sweep 删除后丢失继承机会）。**不变式（可断言）：在「同一键存在上一条目」的路径上，`ETag` 变 ⟺ `Last-Modified` 前进**（二者同源于 `fingerprint`）；**唯一例外** = 无上一条目（首次 / LRU 淘汰 / 已 sweep）时 `ETag` 可不变而 `last_modified` 前进（本次写入时刻，**已登记的可接受降级**）。`fingerprint is None`（既有调用点 / 未传）⇒ 不继承、`last_modified = now`。**`time` 语义不变**（写入时刻，BR-CACHE-31 用） |
| **BR-CACHE-34**（★ v1.8 / F5 新增） | **`feed_cache_put(path, xml, ttl, fingerprint=None) -> dict` 返回写入条目**：返回**写入条目的浅拷贝**（与 `feed_cache_get_entry` 同形态六字段，**恒为 dict、不是 `None`**）——在 `_feed_cache_lock` **内**构造并返回，不受随后淘汰竞态影响。`server._get_or_fetch_feed` **直接消费该返回值**（`return xml, entry['last_modified']`），**删除 put 之后的第二次 `feed_cache_get_entry` 查询** ⇒ 消除「200 带 `ETag` 却不带 `Last-Modified`」窗口 + 省一次加锁往返。**新形参 `fingerprint` 为可选**（默认 `None`，既有 `feed_cache_put(path, xml, ttl)` 调用点零改动）；**返回类型由 `None` 改 `dict` 属"只增"**（旧调用方忽略返回值即可） |
| **BR-CACHE-35**（★ v1.9 / F8 新增） | **feed 取数锁表必须与键空间同界收敛（引用计数 / 惰性回收）**：`_feed_fetch_locks`（`cache_key → Lock`）与 `_feed_fetch_refs`（`cache_key → int`）**同受 `_feed_fetch_locks_lock`**；唯一读写入口是 **`feed_fetch_acquire(key) -> Lock`** / **`feed_fetch_release(key)`**。`acquire`：取锁（v1.9 原文示例 `lock = _feed_fetch_locks.setdefault(key, threading.Lock())`；★ **v1.11 实现约束：先 `get` 判空、仅 `None` 时建 `Lock`**——命中路径零分配） → `_feed_fetch_refs[key] += 1` → **返回 `lock`**（计数先于返回，使"已取出锁但尚未进入 `with`"也被计数覆盖）。`release`：`n = _feed_fetch_refs.get(key, 1) - 1`；`n <= 0` ⇒ **`pop` `_feed_fetch_locks[key]` 且 `pop` `_feed_fetch_refs[key]`**（**两表同删**）；否则写回 `n`。**不变式**：只要还有线程**持有或即将获取**该键锁，计数 ≥1 ⇒ 该键**不可能**被 `pop`。**为什么不能简单重加 `pop`**：归零前 `pop`（`系统_代码评审报告_001.md` TS-4 的旧做法）会让"已取出锁但尚未进入 `with`"的线程与后来者各拿一把**不同的锁** ⇒ 同一键双抓；引用计数正是为覆盖"取出到 `with` 之间"这段窗口，故 TS-4 的原始事故不会重演。**正确性论证（评审会核对）**：`pop` 只发生在计数归零时，此时无任何持有者/等待者；随后到达的线程创建新锁，其双检仍命中前一个持有者已写入的缓存条目 ⇒ **不产生重复取数**（第二次真取数只可能因为条目确实已过期）。**有界性结论**：锁表规模收敛于"**并发在飞的键数**"，而非"累计见过的键数"；`PUBLIC_BASE_URL` 已设时键恒为 5 条 path。**调用纪律**：`acquire` / `try ... finally: feed_fetch_release(key)`——异常路径也必须释放，否则计数泄漏 ⇒ 锁表退化为**只增不减**（回到 F8 所指缺陷）。**可选运营缓解（备注）**：部署侧强制设 `PUBLIC_BASE_URL` ⇒ 键恒为 5 条 path，即便暂不部署本修复也无 Host 派生的键空间。★ **v1.11 / 实现约束（微优化，观察行为不变）**：`acquire` **必须先 `_feed_fetch_locks.get(key)` 判空、仅在 `None` 时创建 `threading.Lock()`**——`setdefault(key, threading.Lock())` 会为**每次调用（含命中已有锁）**先构造一个被丢弃的 `Lock`；改先 `get` 后**命中路径零分配**。返回同一把锁的身份 / 计数先于返回 / `_feed_fetch_locks_lock` 临界区语义**全部不变** |
| **BR-CACHE-36**（★ v1.12 新增；★ v1.13 补实现注 · 可观测性） | **读侧「形态残缺 ⇒ 视同 miss」必须可观测**：`feed_cache_get_entry` 中返回 `None` 的**残缺分支**（判据：① 真值**非映射**；② `xml` 缺失，即 `entry.get('xml') is None`）**必须**产生一条 `log.warning`，并**按「原因」去重**。**实现注（以 `cache.py` 为准，v1.13）**：符号 **`_feed_degraded_warned`**（`set`，去重集合）+ **`_warn_feed_degraded_once(reason, key)`**（`reason not in _feed_degraded_warned ⇒ add(reason) + log.warning(...)`；**总函数、绝不抛**）；消息格式 **`[cache] feed entry degraded to miss (<reason>): key=<key!r>`**，`reason ∈ {'entry is not a mapping', 'xml is None'}`；`log` 为**既有**模块级 `logging.getLogger('cache')`（`cache.py:26`，**未新增 logger**）。**去重维度 = 原因**（**非"原因 + 键"**）：feed 缓存键内嵌**外部选定 Host**（F2/F8），按键去重会被客户端枚举键刷屏 ⇒ **每进程每种形态至多一条**（该集合**故意无锁、容忍竞态**，与 `metrics._warned` 同风格）；措辞是**「缓存条目形态残缺」的自愈信号，不是 "upstream error"**。**语义澄清（必须写死，勿误标"上游故障"）**：这两个分支是**自愈路径**——miss ⇒ 回源一次 ⇒ `feed_cache_put` 写回同键 ⇒ 下次即命中；**不是**上游取数失败。`feed_cache_put` 以**位置参数恒写 `xml`**、且只写 `dict`，故**生产中不可达**（来源只能是注入 / legacy / 未来重构）。**不得**对"空条目（`not entry`）/ 正常过期 / 缺 `expires_at`（§10#29，自然过期）"三个 `return None` 分支打 warning（属正常控制流，打日志即噪音）。 |

### 4.4 批量组装（§2.3 规则的编号化）

| 编号 | 规则 |
|------|------|
| **BR-CACHE-15** | 输出键 = `requested` 去重后保序；值 = `results.get(code)`。 |
| **BR-CACHE-16** | `_errors` 仅收录「值为 `None` ∧ `errors[code]` 非空」的码；未知 kind 归一为 `upstream_error`；**仅非空时挂载**。 |
| **BR-CACHE-17** | `_truncated`/`_dropped_count` 仅 `dropped > 0` 时**同现**；`dropped <= 0` 两键**都不存在**。 |
| **BR-CACHE-18** | 输出体不含顶层 `error`；仅 `requested` 中的非 `_` 前缀码成为数据键。 |
| **BR-CACHE-19** | `stream._refresh_pool` 消费批量结果时**必须跳过 `_` 前缀键**（唯一陷阱点，AR-7；属 stream 层实现，本模块保证保留键为 `_` 前缀）。 |
---

## 5. 伪代码

### 5.1 `fetch_json` 四段式（核心，P7b 与实现逐行对齐）

```python
from collections import OrderedDict
import http.client, logging, random, socket, threading, time, urllib.error
from urllib.parse import urljoin, urlsplit
from urllib.request import Request                             # urlopen 由本模块定义（§5.5）
from .config import (HTTP_DNS_CACHE_TTL, HTTP_POOL_IDLE_TTL,
                     HTTP_POOL_MAX_PER_HOST, HTTP_WARM_CONNECTIONS,
                     HTTP_WARM_TIMEOUT, NEG_TTL, PROBE_TIMEOUT,
                     REQUEST_TIMEOUT, cache_policy, warm_hosts)
from . import metrics

log = logging.getLogger('cache')                     # REV-DES-03：§2.3/§5.4/§6 使用 log.warning

cache = OrderedDict()
_negative = {}
_neg_lock = threading.Lock()
_fetch_inflight = {}                                 # url -> threading.Event（受 _cache_lock）
_cache_stats = {'hit': 0, 'miss': 0}                 # 本地命中计数（Q1 观测项，非 AC）
MAX_CACHE_SIZE = 2000
CACHE_JITTER = 0.2
_CACHE_SWEEP_INTERVAL = 60.0

_HISTORY_AGE = 600.0                                 # 失败历史老化窗口（机制常量，BR-CACHE-20）
_PROBE_BUDGET_CAP = 5.0                              # ★ v1.3：半开探测阶梯封顶（AC-S3 裁决；非 env、非 REQUEST_TIMEOUT）
_FOLLOWER_WAIT_MARGIN = 1.0                          # follower 等待余量（机制常量，BR-CACHE-23）


def _record_hit_locked():
    """计一次正缓存命中；调用方须持 _cache_lock（BR-CACHE-24）。

    段①/段③双检/段④ 三处非网络命中全部经此入账，返回 (hit, miss, entries)
    三元组供**锁外**发布（_publish_url_stats）。
    """
    _cache_stats['hit'] += 1
    return _cache_stats['hit'], _cache_stats['miss'], len(cache)


def _publish_url_stats(hit, miss, entries, metric_key='url'):
    """发布 URL 缓存 gauge（**必须在 _cache_lock 之外** — BR-CACHE-24）。"""
    total = hit + miss
    metrics.set_gauge('cache_entries', entries, key=metric_key)
    metrics.set_gauge('cache_hit_ratio', round(hit / total, 4) if total else 0.0)


def _expires_at(ttl=None):
    """expires_at = now + ttl ×(1 ± jitter)；ttl None ⇒ news_url 域 TTL（BR-CACHE-2）。"""
    base = ttl if ttl is not None else cache_policy('news_url')['ttl']
    return time.time() + base * (1 + random.uniform(-CACHE_JITTER, CACHE_JITTER))


def _cache_fresh(entry, refresh_epoch=None):
    """BR-CACHE-1/31：TTL 内，且（计划刷新时）写入不早于本轮起点。"""
    if not entry or time.time() >= entry.get('expires_at', 0):
        return False
    return refresh_epoch is None or entry.get('time', 0) >= refresh_epoch


def _probe_budget(fail_count):
    """BR-CACHE-22：递增半开探测预算 2s→4s→_PROBE_BUDGET_CAP(5s) 封顶。

    fail_count < 1 视同 1。★ v1.3（AC-S3 裁决）：封顶是 5s 而非 REQUEST_TIMEOUT(10s)；
    REQUEST_TIMEOUT 仅由 _fetch_budget 在"无历史/已老化"两支直接返回（不经本函数）。
    """
    budget = PROBE_TIMEOUT
    steps = max(int(fail_count), 1) - 1
    while steps > 0 and budget < _PROBE_BUDGET_CAP:
        budget = min(budget * 2, _PROBE_BUDGET_CAP)
        steps -= 1
    return budget


def _fetch_budget(url):
    """BR-CACHE-5/20/22：无条目 → 10s；已老化 → 10s（全预算一次）；
    否则 → 当前连续失败段的递增阶梯。"""
    with _neg_lock:
        neg = _negative.get(url)
        if neg is None:
            return REQUEST_TIMEOUT
        if time.time() - neg['first_at'] >= _HISTORY_AGE:
            return REQUEST_TIMEOUT                  # 老化：视同无失败历史
        return _probe_budget(neg.get('fail_count', 1))


def _effective_timeout(url, deadline=None):
    """leader 网络超时 = min(基础预算, 剩余 deadline)（BR-CACHE-21）。

    deadline 已过 ⇒ 返回 None ⇒ 调用方本地超时（不触网、不写负缓存）。
    """
    budget = _fetch_budget(url)
    if deadline is None:
        return budget
    remaining = deadline - time.time()
    if remaining <= 0:
        return None
    return min(budget, max(0.05, remaining))


def _follower_wait_budget(url, deadline=None):
    """follower 等待窗口 = leader 预算 + 余量（BR-CACHE-23），按 deadline 截断。"""
    budget = _fetch_budget(url) + _FOLLOWER_WAIT_MARGIN
    if deadline is None:
        return budget
    remaining = deadline - time.time()
    return max(0.0, min(budget, remaining))


def _classify(exc):
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return 'upstream_timeout'
    if isinstance(exc, urllib.error.URLError) and isinstance(
            getattr(exc, 'reason', None), (socket.timeout, TimeoutError)):
        return 'upstream_timeout'
    return 'upstream_error'


def _record_failure(url, kind):
    with _neg_lock:
        now = time.time()
        prev = _negative.get(url)
        aged = prev is not None and (now - prev['first_at']) >= _HISTORY_AGE   # BR-CACHE-20
        _negative[url] = {
            'until': now + NEG_TTL,                                      # BR-CACHE-6
            'kind': kind,
            'fail_count': (prev['fail_count'] if prev else 0) + 1,       # → _probe_budget 输入
            'first_at': now if (prev is None or aged) else prev['first_at'],
        }
        if len(_negative) >= MAX_CACHE_SIZE:                             # BR-CACHE-8
            victim = min(_negative, key=lambda k: _negative[k]['until'])
            del _negative[victim]
        size = len(_negative)
    metrics.incr('upstream_fail_total', key=kind)                        # ★ 锁外（BR-CACHE-24）
    metrics.set_gauge('negative_cache_size', size)


def _clear_negative(url):
    with _neg_lock:
        removed = _negative.pop(url, None)                               # BR-CACHE-7
        size = len(_negative)
    if removed is not None:
        metrics.set_gauge('negative_cache_size', size)                   # ★ 锁外（BR-CACHE-24）


def fetch_json(url, headers=None, ttl=None, encoding='utf-8', deadline=None,
               refresh_epoch=None):                                      # ★ v1.4 第 6 位（关键字）
    # ── 段 1：正缓存（命中即返回：不读负缓存、不看 deadline、零网络）────
    hit_stats = None
    with _cache_lock:
        entry = cache.get(url)
        if _cache_fresh(entry, refresh_epoch):                           # BR-CACHE-1/31
            cache.move_to_end(url)                                       # BR-CACHE-10
            entry['last_access'] = time.time()
            hit_stats = _record_hit_locked()                             # BR-CACHE-24
            cached_data = entry['data']
        else:
            _cache_stats['miss'] += 1
            cached_data = None
    if hit_stats is not None:
        _publish_url_stats(*hit_stats)                                   # ★ 锁外
        return cached_data

    # ── 段 1b：deadline 闸门（在段 1 之后；BR-CACHE-21）────────────────
    if deadline is not None and deadline - time.time() <= 0:
        raise FetchError('upstream_timeout', url=url)                    # 不触网、不写负缓存

    # ── 段 2：负缓存（不触网）───────────────────────────────────────
    with _neg_lock:
        neg = _negative.get(url)
    if neg is not None and time.time() < neg['until']:                   # BR-CACHE-4
        raise FetchError(neg['kind'], url=url)

    # ── 段 3：leader 选举，只尝试一次 ───────────────────────────────
    hit_stats = None
    with _cache_lock:
        entry = cache.get(url)                                           # 双检
        if _cache_fresh(entry, refresh_epoch):
            cache.move_to_end(url)
            entry['last_access'] = time.time()
            hit_stats = _record_hit_locked()                             # BR-CACHE-24
            cached_data = entry['data']
        elif url in _fetch_inflight:
            event = _fetch_inflight[url]
            is_leader = False
        else:
            event = threading.Event()
            _fetch_inflight[url] = event
            is_leader = True
    if hit_stats is not None:
        _publish_url_stats(*hit_stats)                                   # ★ 锁外
        return cached_data

    if is_leader:
        try:                                                             # ★ BR-CACHE-25：令牌不泄漏
            timeout = _effective_timeout(url, deadline)                  # BR-CACHE-5/20/21/22
            if timeout is None:
                raise FetchError('upstream_timeout', url=url)            # 本地超时，不写负缓存
            try:
                req = Request(url, headers=headers or {})
                with urlopen(req, timeout=timeout) as resp:               # ★ 网络 IO 不持锁
                    data = resp.read().decode(encoding, errors='replace')
            except Exception as exc:
                kind = _classify(exc)
                _record_failure(url, kind)                                # BR-CACHE-6
                raise FetchError(kind, url=url) from exc

            # ── REV-DES-09：cache 写入移出"网络 fetch"的 try ─────────────
            #    编程错误不得被 _classify 误判为 upstream_error 而落负缓存
            try:
                _cache_put(cache, url, data, ttl=ttl)                      # BR-CACHE-11/12
                _clear_negative(url)                                       # BR-CACHE-7
            except Exception:
                log.exception('[fetch_json] post-fetch cache write failed: %s', url)
            return data
        finally:
            with _cache_lock:
                _fetch_inflight.pop(url, None)
            event.set()                                   # 释锁后再 set（§7.2#3）

    # ── 段 4：follower 等待，绝不重入选举 ───────────────────────────
    event.wait(timeout=_follower_wait_budget(url, deadline))             # BR-CACHE-23
    hit_stats = None
    with _cache_lock:
        entry = cache.get(url)
        if _cache_fresh(entry, refresh_epoch):
            cache.move_to_end(url)
            entry['last_access'] = time.time()
            hit_stats = _record_hit_locked()                             # BR-CACHE-24
            cached_data = entry['data']
        else:
            leader_alive = url in _fetch_inflight                        # ★ P7b 复查
    if hit_stats is not None:
        _publish_url_stats(*hit_stats)                                   # ★ 锁外
        return cached_data
    with _neg_lock:
        neg = _negative.get(url)          # 忽略过期：gap 分支必须确定性（BR-CACHE-9）
    if neg is not None:
        raise FetchError(neg['kind'], url=url)
    if leader_alive:
        # leader 仍在取数/发布，超出本 follower 的等待窗口 ⇒ 本地等待预算，
        # 不是上游失败 ⇒ 报超时且**永不落负缓存/不计数**（BR-CACHE-23）
        raise FetchError('upstream_timeout', url=url)
    raise FetchError('upstream_error', url=url)   # 三态皆无：fail-closed，不触网
```

**段 4 的 gap 分支说明（P7b 更新）**：leader 在 `finally` 中 `event.set()` **之前**必然已写入正缓存或负缓存，故正常时序下段 4 必命中其一。三态判定按序：① 正缓存命中 → 返回；② 负缓存存在（**忽略过期**）→ raise 其 `kind`；③ `url in _fetch_inflight` → `upstream_timeout`（**不写负缓存、不计失败**）；④ 三者皆无 → `upstream_error` 兜底（两类极小竞态：负缓存条目在 set 与读之间被淘汰/清除；或 REV-DES-09 下 `_cache_put` 因编程错误被吞并而两处状态均未写入）。全部**失败关闭（不触网）** ⇒ 不引入放大器；情形④有 `log.exception` 显式暴露，便于定位。

> **REV-DES-09 关键约束**：`_cache_put` / `_clear_negative` **必须在网络 fetch 的 `except Exception` 之外**。否则二者抛出的编程错误会被 `_classify` 归为 `upstream_error` **并写入负缓存**（缓存污染 + 掩盖真实缺陷）。同时保证顺序：**cache 写入先于 `event.set()`**，否则 follower 被唤醒时既无正缓存也无负缓存 → 误入 gap 分支。

### 5.2 `_cache_put`（双触发清扫 + 真 LRU）

```python
def _sweep_expired(d):
    """BR-CACHE-13：调用方须持该容器锁；返回删除条数。

    ★ v1.13（P2-6 已防御）：**保留假值条目**（`None` 等，读侧自行处理）、**跳过真值非映射条目**
    （`str`/`list`/… 无 `expires_at` 可比，在此跳过而不是抛 `AttributeError`）。判定键仍 `expires_at`。
    URL 缓存与 feed 缓存**共用**本助手 ⇒ 两条路径的合法条目行为逐字不变。
    """
    now = time.time()
    expired = [k for k, entry in d.items()
               if entry and isinstance(entry, dict) and now >= entry.get('expires_at', 0)]
    for k in expired:
        del d[k]
    return len(expired)


def _cache_put(d, key, value, ttl=None, metric_key='url'):
    with _cache_lock:
        now = time.time()
        global _last_cache_sweep
        if now - _last_cache_sweep >= _CACHE_SWEEP_INTERVAL:              # 触发①
            _sweep_expired(d); _last_cache_sweep = now
        if len(d) >= MAX_CACHE_SIZE:                                      # 触发②
            _sweep_expired(d)
            while len(d) >= MAX_CACHE_SIZE:
                d.popitem(last=False)                                     # BR-CACHE-10
        d[key] = {'data': value, 'time': now, 'last_access': now,
                  'expires_at': _expires_at(ttl)}     # ttl=None ⇒ _expires_at 内回退 news_url（BR-CACHE-2）
        if hasattr(d, 'move_to_end'):
            d.move_to_end(key)
        entries = len(d)
        # cache_hit_ratio：_cache_stats 受 _cache_lock 保护（此处已持锁）⇒ 一致读
        hit, miss = _cache_stats['hit'], _cache_stats['miss']
    _publish_url_stats(hit, miss, entries, metric_key)                    # ★ 锁外唯一发布点（BR-CACHE-24）
```

### 5.3 `feed_cache_get` / `feed_cache_put` / **`feed_fetch_acquire` / `feed_fetch_release`（★ v1.9 / F8）**

```python
_last_feed_sweep = 0.0
_feed_degraded_warned = set()                    # ★ v1.13：按「原因」去重（无锁、容忍竞态，与 metrics._warned 同风格）

def _warn_feed_degraded_once(reason, key):       # ★ v1.13（BR-CACHE-36 实现注；复用既有模块级 log）
    """一条 WARNING = 一次「feed 条目形态残缺 ⇒ 视同 miss」的自愈信号，**非上游故障**；总函数、绝不抛。

    按「原因」去重（**不按 key**）：feed 缓存键内嵌外部选定 Host（F2/F8），按键去重会被枚举刷屏 ⇒ 每进程每种形态至多一条。
    """
    if reason not in _feed_degraded_warned:
        _feed_degraded_warned.add(reason)
        log.warning('[cache] feed entry degraded to miss (%s): key=%r', reason, key)

def feed_cache_get_entry(path):                                  # ★ v1.5（BR-CACHE-32）；★ v1.8 扩字段；★ v1.11 读侧 fail-safe
    """命中返回新鲜条目浅拷贝（含 time/last_modified/fingerprint），否则 None；与 feed_cache_get 同源。"""
    with _feed_cache_lock:
        entry = feed_cache.get(path)
        if not entry:
            return None                                          # 空条目 ⇒ miss（正常控制流，不打 warning）
        if not isinstance(entry, dict):                          # ★ v1.13（BR-CACHE-36 实现注 / §10#30 已防御）：真值非映射 ⇒ 视同 miss
            _warn_feed_degraded_once('entry is not a mapping', path)
            return None                                          # 不抛 AttributeError（否则经 _guard 被误报为"上游故障"降级体）
        if time.time() >= entry.get('expires_at', 0):
            return None                                          # 缺 expires_at（.get 缺省 0 ⇒ now>=0 恒过期）/ 已过期 ⇒ miss（不打 warning）
        now = time.time()
        if entry.get('xml') is None:                             # ★ v1.11：缺 xml（或 None）⇒ 视同 miss（判据恒为 `is None`，★ v1.12 禁 `not xml` 真值化简）
            _warn_feed_degraded_once('xml is None', path)        # ★ v1.13（BR-CACHE-36）：log.warning + 按「原因」去重（自愈信号，非"上游故障"，生产不可达）
            return None                                          # ★ v1.12：`xml=''` 属「合法但空」⇒ 不在此列 ⇒ 照常命中（不判 miss）
        feed_cache.move_to_end(path)
        entry['last_access'] = now
        return {'xml': entry['xml'],
                'time': entry.get('time'),                       # ★ v1.11：缺字段 ⇒ None（读取方按"无写入时刻"降级；不抛）
                'last_modified': entry.get('last_modified'),     # ★ v1.8 / F1；★ v1.10 / P2-1：缺字段 ⇒ None（不发头/禁用 IMS，不抛）
                'fingerprint': entry.get('fingerprint'),         # ★ v1.8 / F1
                'last_access': entry['last_access'],             # 上一行刚写入 ⇒ 恒存在（★ v1.11：不需 .get）
                'expires_at': entry['expires_at']}               # 能通过上述过期判定 ⇒ 该键必存在

def feed_cache_get(path):                                        # ★ v1.5：薄包装，签名/语义不变
    entry = feed_cache_get_entry(path)
    return entry['xml'] if entry is not None else None

def feed_cache_put(path, xml, ttl, fingerprint=None):            # ★ v1.8 / F1+F5（签名 + 返回值）
    """BR-CACHE-33/34：写入并返回条目浅拷贝；指纹相同（即使上一条目已过期）⇒ 继承 last_modified。

    `prev` 必须在触发①/②清扫**之前**捕获，否则已过期条目被 sweep 删除后丢失继承机会
    ——那会让「跨 TTL 重生成仍 304」退化为「每次回源都前进」。
    """
    with _feed_cache_lock:
        now = time.time()
        global _last_feed_sweep
        prev = feed_cache.get(path)                               # ★ F1：先捕获（含过期条目）
        if now - _last_feed_sweep >= _CACHE_SWEEP_INTERVAL:        # 触发①（独立计时）
            _sweep_expired(feed_cache); _last_feed_sweep = now
        cap = cache_policy('feed')['cache_max']                    # BR-CACHE-12
        if len(feed_cache) >= cap:
            _sweep_expired(feed_cache)
            while len(feed_cache) >= cap:
                feed_cache.popitem(last=False)
        if (fingerprint is not None and isinstance(prev, dict)
                and prev.get('fingerprint') == fingerprint):      # ★ v1.13：非映射 prev ⇒ 不继承（原 `prev is not None` 会在 .get 上抛 AttributeError）
            last_modified = prev.get('last_modified')              # ★ F1：继承（表示未变）；★ v1.10 / P2-1：缺字段 ⇒ None
        else:
            last_modified = now                                    # 指纹变 / 无上一条目（可接受降级）
        feed_cache[path] = {'xml': xml, 'time': now,
                            'last_modified': last_modified,        # ★ F1
                            'fingerprint': fingerprint,            # ★ F1
                            'last_access': now, 'expires_at': _expires_at(ttl)}
        feed_cache.move_to_end(path)
        entries = len(feed_cache)
        written = dict(feed_cache[path])                           # ★ F5：锁内浅拷贝后返回
    metrics.set_gauge('cache_entries', entries, key='feed')        # ★ 锁外（BR-CACHE-24）
    return written                                                 # ★ F5：恒为 dict，非 None


# ── ★ v1.9 / F8：feed 取数锁表原语（BR-CACHE-35）───────────────────────
# _feed_fetch_locks: dict[cache_key -> Lock]   受 _feed_fetch_locks_lock
# _feed_fetch_refs:  dict[cache_key -> int]    受 _feed_fetch_locks_lock（与锁同生共死）

def feed_fetch_acquire(key):
    """BR-CACHE-35：持 _feed_fetch_locks_lock 取锁（命中不新建）+ 计数 +1，返回 Lock。"""
    with _feed_fetch_locks_lock:
        lock = _feed_fetch_locks.get(key)                          # ★ v1.11：先判空（命中路径零分配；不用 setdefault）
        if lock is None:
            lock = threading.Lock()
            _feed_fetch_locks[key] = lock
        _feed_fetch_refs[key] = _feed_fetch_refs.get(key, 0) + 1
        return lock                                    # 计数先于返回（覆盖「已取出未 with」窗口）


def feed_fetch_release(key):
    """BR-CACHE-35：持 _feed_fetch_locks_lock 递减计数；归零即 pop 锁与计数（两表同删）。"""
    with _feed_fetch_locks_lock:
        n = _feed_fetch_refs.get(key, 1) - 1
        if n <= 0:
            _feed_fetch_locks.pop(key, None)           # 归零 ⇒ 无持有者/等待者 ⇒ 安全 pop（TS-4 不变式）
            _feed_fetch_refs.pop(key, None)            # 计数表不得成为新的无界表
        else:
            _feed_fetch_refs[key] = n
```

### 5.4 `build_batch_response` 组装

```python
def build_batch_response(requested, results, errors=None, dropped=0):
    errors = errors or {}
    out, seen = {}, set()
    for code in requested:                                                # BR-CACHE-15
        if not isinstance(code, str) or code.startswith('_') or code in seen:
            continue
        seen.add(code)
        out[code] = results.get(code)                                     # 缺失 → None

    err_out = {}
    for code in requested:                                                # BR-CACHE-16（保序）
        if code not in seen or code in err_out:
            continue
        if out.get(code) is not None:          # 有数据 ⇒ 不算失败（值域三分自洽）
            if errors.get(code):
                log.warning('[build_batch_response] %s has data but error kind %r; dropped',
                            code, errors[code])
            continue
        kind = errors.get(code)
        if not kind:
            continue
        if kind not in FetchError.KINDS:
            log.warning('[build_batch_response] unknown kind %r for %s → upstream_error',
                        kind, code)
            kind = 'upstream_error'
        err_out[code] = kind
    if err_out:
        out['_errors'] = err_out
    if dropped > 0:                                                       # BR-CACHE-17
        out['_truncated'] = True
        out['_dropped_count'] = int(dropped)
    return out
```

### 5.5 HTTP 传输（`urlopen` / `_pool_request` / `warm_transport`，v1.4）

```python
def urlopen(req, timeout=None):
    """池化 drop-in（BR-CACHE-26）：单一网络缝（测试 patch cache.urlopen）。"""
    if isinstance(req, Request):
        url, headers, method = req.full_url, dict(req.header_items()), req.get_method()
    else:
        url, headers, method = str(req), {}, 'GET'
    current, redirects = url, 0
    while True:
        status, resp_headers, body = _pool_request(method, current, headers, timeout)
        if status in _REDIRECT_CODES and resp_headers is not None:
            location = resp_headers.get('location')
            if location:
                redirects += 1
                if redirects > _MAX_REDIRECTS:
                    raise urllib.error.HTTPError(current, status, 'too many redirects',
                                                 resp_headers, None)
                current = urljoin(current, location)
                continue
        if status >= 400:
            raise urllib.error.HTTPError(current, status,
                                         http.client.responses.get(status, ''),
                                         resp_headers, None)
        return _PooledResponse(body, status, resp_headers)      # read()able + 上下文管理器


def _pool_request(method, url, headers, timeout):
    """BR-CACHE-27/28：一次池化请求，失效复用连接重试一次。"""
    parsed = urlsplit(url)
    scheme = (parsed.scheme or '').lower()
    if scheme not in ('http', 'https'):
        raise urllib.error.URLError(f'unsupported URL scheme {scheme!r} in {url!r}')
    host = parsed.hostname
    if not host:
        raise urllib.error.URLError(f'missing host in URL {url!r}')
    key = (scheme, host, parsed.port or (443 if scheme == 'https' else 80))
    path = (parsed.path or '/') + (f'?{parsed.query}' if parsed.query else '')
    for attempt in (0, 1):
        conn, reused, ephemeral = _pool.acquire(key, timeout)    # ★ 仅记账在锁内
        try:
            status, resp_headers, body, will_close = _send(conn, method, path, headers)
        except _STALE_CONNECTION_ERRORS as exc:
            _pool.note_stale(); _pool.discard(key, conn, ephemeral=ephemeral)
            if reused and attempt == 0:
                continue                                        # 失效 keep-alive ⇒ 新连接重试一次
            raise urllib.error.URLError(exc) from exc
        except (socket.timeout, TimeoutError):
            _pool.discard(key, conn, ephemeral=ephemeral); raise
        except urllib.error.URLError:
            _pool.discard(key, conn, ephemeral=ephemeral); raise
        except OSError as exc:
            _pool.discard(key, conn, ephemeral=ephemeral)
            raise urllib.error.URLError(exc) from exc
        except http.client.HTTPException as exc:
            _pool.discard(key, conn, ephemeral=ephemeral)
            raise urllib.error.URLError(exc) from exc
        (_pool.discard if will_close else _pool.release)(key, conn, ephemeral=ephemeral)
        return status, resp_headers, body
    raise urllib.error.URLError('stale connection retry exhausted')


class _ConnectionPool:
    """BR-CACHE-27：per-key keep-alive 桶；_lock 只护 _idle/_live/stats。"""

    def acquire(self, key, timeout):
        """⇒ (conn, reused, ephemeral)。空闲 LIFO；达上限 ⇒ ephemeral（不排队）。"""
        # ① 锁内：摘空闲（过期懒淘汰计数）、或预留槽位、或标 ephemeral
        # ② 锁外：死连接关闭；reused 时 settimeout（失败 ⇒ 释放槽位并新建）
        # ③ 锁外：_open_connection(key, timeout)；失败回滚预留槽位后上抛

    def release(self, key, conn, ephemeral=False):
        """ephemeral ⇒ 直接关；否则入桶（溢出部分关闭）。"""
    def discard(self, key, conn, ephemeral=False):
        """不回池：ephemeral ⇒ 关；否则减 _live 并关。"""


class _DNSResolver:
    """BR-CACHE-29：getaddrinfo TTL 缓存；TLS 仍按主机名拨号。"""

    def resolve(self, host, port, force=False):
        """缓存命中（且未过期、非 force）⇒ 返回；否则 getaddrinfo 并（ttl>0）写缓存。"""
    def connect(self, address, timeout, source_address):
        """先 resolve 后遍历 infos 连接；失败 force 重解析一次；异常/空 ⇒ stdlib 回退。"""


def warm_transport(hosts=None, count=None, timeout=None):
    """BR-CACHE-30：总函数，仅握手不发业务请求。"""
    try:
        hosts = tuple(hosts) if hosts else warm_hosts()          # 取值异常 ⇒ return 0
    except Exception:
        return 0
    count = HTTP_WARM_CONNECTIONS if count is None else max(0, int(count))
    timeout = HTTP_WARM_TIMEOUT if timeout is None else timeout
    warmed = 0
    for key in hosts:
        for _ in range(count):
            try:
                conn, reused, ephemeral = _pool.acquire(key, timeout)
            except Exception:
                break                                            # 该 host 静默失败 ⇒ 下一个
            _pool.release(key, conn, ephemeral=ephemeral)
            if reused or ephemeral:
                break                                            # 已热身 / 池满 ⇒ 无需再加
            warmed += 1
    return warmed
```
---

## 6. 错误处理

| 情形 | 行为 | 下游降级 |
|------|------|---------|
| 上游超时（socket/URL 超时） | `FetchError('upstream_timeout')` + 落负缓存 | 批量 → `_errors[code]='upstream_timeout'`；单体 → `{'error':...}`；RSS → error-RSS |
| 上游其它异常（DNS/RST/HTTP 5xx/解析） | `FetchError('upstream_error')` + 落负缓存 | 同上，kind=`upstream_error` |
| 负缓存命中 | `FetchError(kind)`（沿用首次分类），**不触网** | 同上；AC-S3 模式 A P95 ≤1s |
| CDP 不可用 | **本模块不产生**；`stock_api.fetch_cls_f10` raise `FetchError('cdp_unavailable')` | 批量 → `_errors[code]='cdp_unavailable'`（A′ 形状） |
| 正文编码非 utf-8 | `decode(encoding, errors='replace')` → 不抛（替换非法字节） | 由域传 `encoding='gbk'`（longhu） |
| `build_batch_response` 收到未知 kind | 归一 `'upstream_error'` + warning（不抛） | 枚举封闭 |
| `build_batch_response` 收到 data + error 冲突 | 数据优先、不收录 `_errors` + warning（不抛） | 值域三分自洽 |
| `FetchError(kind)` 非法 kind | 构造期 `ValueError` | 编程错误，暴露于测试 |
| **4xx/5xx（池化 `urlopen`）** | `urllib.error.HTTPError`（含 status/headers）→ `_classify` ⇒ `FetchError('upstream_error')` + 落负缓存 | 同"上游其它异常" |
| **失效 keep-alive 连接**（`_STALE_CONNECTION_ERRORS`） | **仅复用且首次尝试** ⇒ 丢弃 + 新连接**重试一次**；否则 `URLError` ⇒ `FetchError('upstream_error')` | 复用抖动不放大为上游失败（BR-CACHE-28） |
| **DNS 解析失败/缓存地址不可连** | `force` 重解析一次；仍失败 ⇒ `URLError`/`gaierror` ⇒ `FetchError('upstream_error')`；解析器本身异常 ⇒ 回退 `socket.create_connection` | 失败**不缓存**（BR-CACHE-29） |
| **`warm_transport` 任一 host 拨号失败** | 静默 `break` 该 host，继续下一个；整体**绝不抛**（返回已热身数） | 启动预热不 gate 启动/`/healthz`（BR-CACHE-30） |
| **scheme 非 http/https / URL 缺 host** | `_pool_request` 抛 `URLError` | `FetchError('upstream_error')` |

**契约要点**
- `fetch_json` 的失败**永远**是 `FetchError`（不再有 `RuntimeError` / 返回 `None`）；**失败不留 Traceback 断连**（由 `_guard` 兜底）。
- `build_batch_response` 是**总函数**：对任意输入都返回 dict，绝不抛（AC-S1 的组装层保证）。
- 失败即落负缓存 ⇒ 故障期上游请求量**不随请求数线性放大**（RC-2 消除）。

## 7. 并发安全

### 7.1 锁清单与粒度

| 锁 | 保护对象 | 备注 |
|----|---------|------|
| `_cache_lock` | `cache`、`_fetch_inflight`、`_last_cache_sweep`、`_cache_stats` | 既有，保留 |
| `_neg_lock` | `_negative` | **新增**（独立锁，避免与 `_cache_lock` 嵌套） |
| `_feed_cache_lock` | `feed_cache`、`_last_feed_sweep` | 既有，保留 |
| `_feed_fetch_locks_lock` | `_feed_fetch_locks` + `_feed_fetch_refs`（锁表 + 引用计数） | 既有，保留（★ v1.9 / F8：仅经 `feed_fetch_acquire/release` 读写；`release` 归零两表同删） |
| `_pool._lock` | `_pool` 的 `_idle`/`_live`/`stats`（**桶记账**） | **v1.4 新增**：`connect`/`close`/请求 IO **一律在锁外** |
| `_resolver._lock` | `_DNSResolver._cache` | **v1.4 新增**：仅护 dict 读写，`getaddrinfo` 在锁外 |

### 7.2 锁序纪律（硬约束）

1. **`_cache_lock` / `_neg_lock` / `_feed_cache_lock` / `_feed_fetch_locks_lock` / `_pool._lock` / `_resolver._lock` 互不嵌套**：任何时刻最多持有一把。需要组合状态时**顺序获取、立即释放**（如段 3 先 `_cache_lock` 出块，再由 `_fetch_budget` 取 `_neg_lock`）。`_pool.acquire` 内可能同时触及 `_pool._lock` 与（锁外的）`_resolver.resolve`（其内部再取 `_resolver._lock`）⇒ **`_pool._lock` 释放后才 connect**，两把锁不重叠。
2. **网络 IO（`urlopen`/`read`/`decode`）永不持锁** ⇒ 慢上游不阻塞缓存读者（AC-E1/A4）。`_pool`/`_resolver` 同样遵守：锁内只做记账/dict 读写。
3. `event.set()` 在释放 `_cache_lock` 之后调用（先 pop inflight，再 set），避免唤醒的 follower 立即争锁。
4. 与 `_feed_fetch_locks`（per-键 Lock，server 持有）**无锁序关系**：cache 层不在持有自身锁时获取 feed fetch lock，反之亦然（`_get_or_fetch_feed` 先释放 `_feed_cache_lock` 再取 per-键 lock —— server 侧纪律，详见 server 详设）。★ **v1.9 / F8**：`feed_fetch_acquire`/`feed_fetch_release` 的临界区仅在 `_feed_fetch_locks_lock` 内做 dict 读写（无 IO、不嵌套）；**返回锁之后**才由调用方 `with lock:` ⇒ 建表锁与 per-键 锁不同时持有（`server.md` §7.2#1）。
5. **不引入全局大锁**（项目约定：分锁不用全局大锁）。

### 7.3 热点路径锁开销（AC-E1 P95 ≤5ms 相关）

- **正缓存命中**：只取 `_cache_lock` 一次（段 1 即返回）→ 命中路径**不触碰** `_neg_lock`，且**不读 `deadline`**（BR-CACHE-21：命中零网络、零延迟）。
- 未命中的首步多取一次 `_neg_lock`（段 2），仍为纳秒级临界区（dict get）。
- metrics 写入**不在请求热路径的临界区内**：命中/未命中由本地 `_cache_stats{hit,miss}` 在已持 `_cache_lock` 的临界区内自增（**零额外加锁**；**该计数不注册为 metrics 指标名**，全仓**不存在** `cache_hit_total`/`cache_miss_total`），随后 `_publish_url_stats` 在**锁外**发布 `cache_hit_ratio`（= `round(hit/(hit+miss), 4)`，分母 0 → `0.0`）与 `cache_entries`（BR-CACHE-24）。发布点：段①命中、段③双检命中、段④ follower 命中、以及每次 `_cache_put`（写路径）。
- 负缓存读（段 2）在故障期承担全部命中的快速失败路径（<1ms）；`_negative` 无并发写热点（仅失败时写）。

### 7.4 容量竞态

`_sweep_expired` 与 `popitem` 均在对应容器锁内执行；`feed_cache_put` 的 cap 从 `cache_policy` 每次读取（env 不可变，无竞态）。★ **v1.8 / F5**：`feed_cache_put` 在**同一锁内**构造并返回写入条目的浅拷贝 ⇒ 返回值不受随后淘汰竞态影响；`prev` 亦在清扫**之前**捕获（BR-CACHE-33）。

## 8. 测试要点（映射 AC）

| 用例 | 步骤 / 断言 | 覆盖 AC |
|------|------------|---------|
| **T-CACHE-0** 调用点覆盖核查 | grep 全仓 `fetch_json(`，确认 18 处生产调用点 + 2 处新增 longhu；确认无 `except RuntimeError` 捕获此路径 | 兼容性 |
| **T-CACHE-1** 四段式白盒 | mock `urlopen` 计数：段 2 命中时 `urlopen.calls == 0`；段 3 无历史 → `timeout == 10`；有历史且 `fail_count=1` → `== 2`（阶梯首级） | S3/S7 |
| **T-CACHE-2** 存量用例改写（AR-10） | `test_fetch_json_leader_failure_does_not_stampede` 新语义：8 并发、leader 失败 → **`err=8`**（leader 落负缓存，7 follower 读负缓存直接 raise）、`max_active=1`、窗口内失败 <1ms | S3 |
| **T-CACHE-3** 模式 A「连接秒拒」 | mock urlopen 即时 raise `URLError`；P95 ≤ 1s；`_negative` 有条目；`upstream_fail_total{upstream_error} ≥ 1` | S3 模式 A |
| **T-CACHE-4** 模式 B「黑洞超时」 | 首次：单请求阻塞 ≤10s（冷预算）⇒ 落负缓存；其后每轮预算**逐级抬高**（`_probe_budget`：`2→4→5s`，`_PROBE_BUDGET_CAP` 封顶），门禁期 5s 内 <1ms 快速失败。**断言**：① 每轮单请求耗时 ≤ 当轮预算 + ε；② 稳态单请求 ≤15s（AC-E2）；③ **持续黑洞稳态**：预算稳定在 `_PROBE_BUDGET_CAP=5s`，周期 ≈ `5s(探测)+5s(门禁)=10s` ⇒ 慢请求占比 ≈50% ⇒ **P95 ≈ 5s**（§10#11，AC-S3 裁决后不再"密度相关退化为 10s"） | S3 模式 B / S7 / §10#11 |
| **T-CACHE-4b** 失败历史老化（BR-CACHE-20） | 构造 `first_at` 距今 ≥ `_HISTORY_AGE` 的 `_negative` 条目 ⇒ `_fetch_budget` 返回 `REQUEST_TIMEOUT`(10s)；该次失败后 `first_at` **重置为 now**（下一次回到阶梯首级 2s）；该次成功则条目清除 | BR-CACHE-20 / S3 |
| **T-CACHE-4c** 阶梯 + 老化预算矩阵（P7b；★ v1.3 更正期望值） | `_probe_budget` 数值断言 **`(1,2,3,4,9) → (2,4,5,5,5)`**（`_PROBE_BUDGET_CAP=5.0` 封顶）、`(0→2)`；**且断言封顶 ≠ `REQUEST_TIMEOUT`**（`_probe_budget(99) == 5.0 < REQUEST_TIMEOUT`）；`fail_count` 累加（间隔 < `FAIL_COOLDOWN`）后 `_fetch_budget` 逐级放大至 **5s** 封顶；`first_at` 老化后回到 **10s** 全预算且重置窗口 | BR-CACHE-20/22 |
| **T-CACHE-4d** 模式 B 稳态量化（P7b；★ v1.3 按 AC-S3 裁决重写） | 稳态黑洞：预算固定 `_PROBE_BUDGET_CAP=5s` + 门禁 `NEG_TTL=5s` ⇒ ① **单请求 ≤15s**（AC-E2，恒成立）；② **P95 ≈ 5s**（慢请求占比 ≈50%，与请求密度**无关**——阶梯上限已被封顶，不再出现"低密度下 P95 ≈ 10s"的旧退化）；③ 请求密度只影响"每秒触网上游次数"，不影响单请求延迟分布 | S3 / AC-E2 交互（§10#11） |
| **T-CACHE-5** 半开探测恢复 | 失败后负缓存窗口内不触网；上游恢复后首个探测（≤2s）成功 → `_negative` **被清除**、正缓存写入、后续命中 <1ms | S3 / A4 |
| **T-CACHE-6** 失败历史保留 | 负缓存过期后 `url in _negative` 仍为 True（BR-CACHE-8）；再次失败 `until` 顺延、`fail_count` 递增 | S3 |
| **T-CACHE-6b** `first_at` 不被刷新 | 连续多次失败（间隔 < `_HISTORY_AGE`）后 `first_at` **保持不变**；仅老化触发后的失败才重置（BR-CACHE-20） | 逆向审查 1 |
| **T-CACHE-7** 真 LRU | 写入 A,B,C（cap=3）→ 命中 A → 写 D ⇒ 淘汰 B（非 A）；命中刷新 `last_access` | E6 |
| **T-CACHE-8** 双触发清扫 | 触发①：时钟推进 >60s 后一次写入 ⇒ 过期条目被清且返回删除数；触发②：填满 cap 后写入 ⇒ 先清过期再 `popitem(last=False)` | E6 |
| **T-CACHE-9** URL 上限 | >2500 不同 URL ⇒ `len(cache) <= 2000`；被淘汰 URL 下次必回源（mock 计数） | E6 |
| **T-CACHE-10** feed LRU | `feed_cache_put` 至 cap → 最久未访问被淘汰；命中 `move_to_end`；TTL 用 `cache_policy('feed')['ttl']` | E6/A8 |
| **T-CACHE-11** 保留键矩阵 | `build_batch_response` 四组合：①无错误无截断 → 无 `_` 键；②只有错误 → 仅 `_errors`；③只有截断 → `_truncated`+`_dropped_count`；④两者 → 三键；≤50 ⇒ 两截断键**不存在**（非 false/0） | A9/A10 |
| **T-CACHE-12** 值域三分 | 混入 3 类码（失败/非法/无数据）→ 值均 `null`；**仅失败码**在 `_errors`；`_errors` 值 ∈ KINDS | A10/S6 |
| **T-CACHE-13** 组装总函数性 | 非法输入（未知 kind、data+error 冲突、非 str 码、`_` 前缀码、重复码）⇒ 不抛异常、无自由文本 | S1/A10 |
| **T-CACHE-14** `_errors` 非空才出现 | 全成功 ⇒ `'_errors' not in out`（键不存在，不是 `{}`） | A10 |
| **T-CACHE-15** 编码形参 | longhu 两 URL `encoding='gbk'` 正确解码 GBK 页面；既有 18 点默认 utf-8 行为不变 | E9 |
| **T-CACHE-16** `FetchError` 枚举 | 非法 kind → `ValueError`；`upstream_timeout`/`upstream_error`/`cdp_unavailable` 三值可构造 | S6/R14 |
| **T-CACHE-17** `_sweep_expired` 兼容 | 既有用例 `test_sweep_expired_removes_stale_entries` 原样通过（返回 1、保留 `None` 条目） | 回归 |
| **T-CACHE-18** `_` 前缀隔离 | `build_batch_response` 输出中 `requested` 的 `_x` 码不成为数据键（BR-CACHE-18） | A9/AR-7 |
| **T-CACHE-19** 命中率发布（REV-DES-02） | `_cache_put` 后有 `snapshot()['cache_hit_ratio'] == round(hit/(hit+miss),4)`；`hit=miss=0` ⇒ `0.0`；快照键名恒为 `cache_hit_ratio`，**不存在** `cache_hit_total`/`cache_miss_total` | Q1 观测项 |
| **T-CACHE-20** 段 3 try 范围（REV-DES-09） | mock `_cache_put` 抛异常 ⇒ ① 请求仍 `return data`（或按设计暴露）；② `_negative` **不新增**该 url；③ `upstream_fail_total` **不增**；④ 有 `log.exception` | 异常处理 / 缓存污染防护 |
| **T-CACHE-21** 递增探测阶梯（BR-CACHE-22，P7b；★ v1.3 更正） | `_probe_budget(1/2/3/4/9) == (2,4,5,5,5)`；`_probe_budget(0)` 视同 1 → 2；**`_probe_budget(任何 ≥3) == _PROBE_BUDGET_CAP(5.0)`，恒 < `REQUEST_TIMEOUT`**；`fail_count` 累加后 `_fetch_budget` 逐级放大至 **5s** 封顶 | S3 |
| **T-CACHE-22** deadline 闸门在命中之后（BR-CACHE-21，P7b） | ① 正缓存有效 + `deadline = time()-1` ⇒ **返回缓存数据**且 `urlopen.calls == 0`（**不 raise**）；② 无缓存 + `deadline = time()-1` ⇒ `FetchError('upstream_timeout')`、`urlopen.calls == 0`、`_negative` **无**该 URL | AC-E2/S3 |
| **T-CACHE-23** follower 窗口与 `leader_alive`（BR-CACHE-23，P7b） | 构造"leader 慢于 follower 窗口"：`event.wait` 超时后 leader 仍在 `_fetch_inflight` ⇒ `FetchError('upstream_timeout')` 且 `_negative` **无**该 URL、`upstream_fail_total` **不增**；三态皆无（清空负缓存 + 删 inflight）⇒ `FetchError('upstream_error')` | S3/S1 |
| **T-CACHE-24** metrics 锁外发布（BR-CACHE-24，P7b） | 复用 `_lock_held_during`：`_cache_put` / `_record_failure` / `_clear_negative` / `feed_cache_put` 执行期间**均未持有**对应业务锁；段①/③/④ 三种命中路径均使 `cache_hit_ratio` 分子 +1（`_record_hit_locked` 三处调用） | S10（Q1） |
| **T-CACHE-25** leader 令牌不泄漏（BR-CACHE-25，P7b） | mock `_effective_timeout` 抛异常 ⇒ `url not in _fetch_inflight`（`finally` 已 pop）、`event.is_set()` 为真；随后同一 URL 的新请求可正常成为 leader（不再沦为 follower） | S1 |
| **T-CACHE-26** 池化复用与有界（v1.4 / BR-CACHE-27） | 同一 `(scheme,host,port)` 连发两次 ⇒ 第二次 `_pool.stats['reuse'] == 1`（打桩 `_open_connection`）；并发 > `HTTP_POOL_MAX_PER_HOST` ⇒ 多余走 ephemeral（`stats['ephemeral'] > 0`）且**不阻塞**；空闲超 `HTTP_POOL_IDLE_TTL` 后 checkout ⇒ `stats['evicted'] += 1` 且关闭 | E1 传输 |
| **T-CACHE-27** 失效连接重试一次（v1.4 / BR-CACHE-28） | 打桩 `_send` 首次（`reused=True`）抛 `http.client.RemoteDisconnected`、第二次成功 ⇒ 请求成功、`stats['stale']==1`、`_open_connection` 被调 2 次；若 `reused=False` 抛同错 ⇒ `URLError` 且**不重试**；`socket.timeout` 抛 ⇒ 原样上抛、不重试 | 传输健壮性 |
| **T-CACHE-28** `urlopen` stdlib 契约（v1.4 / BR-CACHE-26） | 打桩池返回 200 ⇒ `resp.read()` 得 body、`resp.status==200`、可 `with`；404/500 ⇒ `HTTPError`；连接异常 ⇒ `URLError`；302+Location ⇒ 跟随，>5 次 ⇒ `HTTPError('too many redirects')`；非 http scheme ⇒ `URLError` | `_classify` 依赖 |
| **T-CACHE-29** DNS TTL 缓存（v1.4 / BR-CACHE-29） | 两次 `resolve` 同 host ⇒ `getaddrinfo` 仅调 1 次；`ttl=0` ⇒ 每次调；解析失败**不写缓存**；缓存地址 connect 失败 ⇒ `force` 重解析一次；`getaddrinfo` 抛 ⇒ `connect` 回退 `socket.create_connection` | E1 传输 |
| **T-CACHE-30** `warm_transport` 总函数（v1.4 / BR-CACHE-30） | `warm_transport(hosts=[key], count=1)` ⇒ `_pool` 有该 key 且返回 1；同一 key 再调 ⇒ 返回 0（已热身 `break`）；`_open_connection` 抛 ⇒ 返回 0 **不抛**；`warm_hosts()` 抛 ⇒ 返回 0 | 启动预热 |
| **T-CACHE-31** `refresh_epoch` 新鲜度下限（v1.4 / BR-CACHE-31） | 写入 `time=t0`、`ttl=60`，以 `refresh_epoch=t0+tick` 读 ⇒ **不命中**（`urlopen` 被调 1 次、`upstream_fetch_total` 增），以 `refresh_epoch=None` 读 ⇒ 命中（`urlopen` 0 次）；`refresh_epoch` 不改变写入 TTL（写后 `expires_at-time ≈ ttl`） | SSE 每拍真刷新 |
| **T-CACHE-32** feed 条目访问器（★ v1.5 / BR-CACHE-32；★ v1.6 / C7#14 扩容器态负例；**★ v1.7 / D-3 ✅ 已实现**；**★ v1.8 / F1 扩字段**） | 冷 cache ⇒ `feed_cache_get_entry('/p') is None`；`feed_cache_put('/p','<x/>',30)` 后 ⇒ dict 且 `entry == {'xml':'<x/>','time':float,'last_modified':float,'fingerprint':None,'last_access':float,'expires_at':float}`（★ v1.8：**六字段**，`fingerprint=None` 时 `last_modified == time`）；过期（`ttl=0` 或注入时钟）⇒ `None`；**浅拷贝（返回值侧）**（改返回值不改变后续查询结果）；命中时 `feed_cache` 内条目被 `move_to_end` 且 `last_access` 刷新；`feed_cache_get('/p') == '<x/>'`（**既有 T-CACHE-10 全绿，签名/语义不变**）。★ **v1.6 扩容器态负例（浅拷贝隔离）**：取 `e = feed_cache_get_entry('/p')` 后改写 `e['xml']='z'` / `e['last_access']=0` / `e['expires_at']=0` / `e['time']=0` / `e['last_modified']=0` / `e['fingerprint']=None` ⇒ 容器条目 `feed_cache['/p']` 的对应六字段**逐一不变**，且随后 `feed_cache_get_entry('/p')` 仍返回**未被改写**的值（**因值不可变，浅拷贝足以隔离容器**；禁止 deepcopy）。**✅ 已实现（P6c）**：`tests/test_cache.py::FeedEntryAccessorTests::test_t_cache_32_shallow_copy_isolates_the_container`（容器态负例）+ `test_srv_t60_feed_cache_get_entry_contract`（契约）；★ **v1.8 / F1**：两方法须同步扩为**六字段**断言。★ **v1.10 / P2-1**：`test_srv_t60_feed_cache_get_entry_contract` 追加 **legacy / 注入条目负例**——仅含 `xml/time/last_access/expires_at` 的四字段条目 ⇒ `feed_cache_get_entry` 返回的 `last_modified` **与** `fingerprint` 均为 `None`，且**不抛 `KeyError`**（fail-safe 负例；`tests/test_cache.py::FeedEntryAccessorTests::test_srv_t60_feed_cache_get_entry_contract`） | A8（Last-Modified 时间源）/ 兼容 / **BR-CACHE-32 浅拷贝充分性（P2-04 负例）** |
| **T-CACHE-33** ★ **指纹继承 / 变更两向（F1 决定性）**（★ v1.8 / F1 / BR-CACHE-33） | ① 写 `put('/p', x1, 30, fingerprint='A')` ⇒ 记 `lm1`；推进受控时钟越过 `expires_at` 后再写 `put('/p', x1, 30, fingerprint='A')`（**上一条目已过期**）⇒ **`last_modified == lm1`（继承、不前进）**——**证伪方向**：若实现只在"新鲜条目"上比较或先 sweep 再取 `prev` ⇒ `last_modified` 前进 ⇒ 用例红。② 改指纹 `put('/p', x2, 30, fingerprint='B')` ⇒ `last_modified` **前进**（`> lm1`）。③ **无上一条目**（`feed_cache.clear()` 后首次写）⇒ `last_modified == time`（本次写入时刻，可接受降级）。④ `fingerprint=None` ⇒ 不继承、`last_modified == time`。⑤ **LRU 淘汰 / 已 sweep** ⇒ 视同无上一条目（本次写入时刻）。**不变式断言**：`ETag` 变 ⟺ `last_modified` 前进。⑥ **★ v1.10 / P2-1**：上一条目**指纹匹配但缺 `last_modified` 字段**（legacy / 注入）⇒ 写入条目 `last_modified=None`、**不抛 `KeyError`**（亦**不前进**为写入时刻）；⑦ **★ v1.10 / P2-4**：第二次 `put` 前置 `_last_feed_sweep=0.0` **强制触发①清扫**，断言 `_last_feed_sweep > 0`（清扫确已发生）**且**继承仍成立——覆盖"`prev` 必须先于 sweep 捕获"的顺序要求。落点 `tests/test_cache.py::FeedEntryAccessorTests::test_t_cache_33_fingerprint_inherits_across_expiry` | A8 / **BR-CACHE-33** / `server.md` BR-SRV-38 |
| **T-CACHE-34** ★ **`feed_cache_put` 返回写入条目**（★ v1.8 / F5 / BR-CACHE-34） | 冷/热路径 `r = feed_cache_put('/p', x, 30, fingerprint='A')` ⇒ `r` **是 dict（非 None）** 且恰含 `{xml,time,last_modified,fingerprint,last_access,expires_at}`；`r == feed_cache_get_entry('/p')`（同形态）；**浅拷贝隔离**：改写 `r` 不改容器；`feed_cache_put('/p', x, 30)`（不传 fingerprint）**向后兼容**、旧调用点零改动 | A8 / 兼容 / **BR-CACHE-34** |
| **T-CACHE-35** ★ **feed 取数锁表引用计数收敛**（★ v1.9 / F8 / BR-CACHE-35） | ① **计数成对 + 同锁**：`la = feed_fetch_acquire('/k')`、`lb = feed_fetch_acquire('/k')` ⇒ `_feed_fetch_refs['/k'] == 2` 且 `la is lb`；`feed_fetch_release('/k')` 一次 ⇒ `'/k'` **仍在** `_feed_fetch_locks`；再 `release` ⇒ `'/k' not in _feed_fetch_locks` **且** `'/k' not in _feed_fetch_refs`（**两表同删**）。② **不双抓（TS-4 回归网）**：线程 A `lock = feed_fetch_acquire('/k')` 后**挂起在 `with` 之前**，线程 B `feed_fetch_acquire('/k')` ⇒ **拿到同一把锁**、阻塞至 A 释放；断言 A 挂起期间 `'/k' in _feed_fetch_locks`（**禁止** `pop`）、B 未与 A 并发进入临界区。③ **异常路径不泄漏**：调用方 `try: ... finally: feed_fetch_release('/k')` 中抛异常 ⇒ `_feed_fetch_refs` 归零且键被 `pop`（锁表不单调增长）。④ **不随 N 增长（收敛性）**：**串行** 50 个不同 key 各 acquire/release 一轮（无在飞）⇒ `len(_feed_fetch_locks) == 0`；**并发**在飞 ≤ K 个不同 key ⇒ `len(_feed_fetch_locks) <= K`——断言形式为"**不随累计 key 数 N 增长**"，收敛于**并发在飞的键数** | **BR-CACHE-35** / AC-S9（资源总账不单调增长） / `server.md` **SRV-T71·T72·T73** |
| **T-CACHE-36** ★ **feed 条目读侧 fail-safe（形态不完整 ⇒ 视同 miss / 无该头）**（★ v1.11 / BR-CACHE-32 / BR-CACHE-33；★ v1.13 补 ⑤ 非映射守卫 + 告警去重方法） | ① **缺 `xml` ⇒ 视同 miss（决定性对比例子）**：向 `feed_cache` 注入**缺 `xml` 键**（或 `xml=None`）、但 `expires_at` 未过期的条目 ⇒ `feed_cache_get_entry(path) is None` **且** `feed_cache_get(path) is None`（**不抛 `KeyError`**）。② **缺 `expires_at` ⇒ 视同过期**：注入有 `xml`、`expires_at` 缺字段的条目 ⇒ `feed_cache_get_entry(path) is None`（`entry.get('expires_at', 0)` 缺省 `0`、`now >= 0` **恒成立** ⇒ 自然判为过期）。③ **四字段 legacy（**有 `xml`**）⇒ 仍服务、只是不发头**：注入仅含 `xml/time/last_access/expires_at` 的条目 ⇒ `feed_cache_get_entry` **返回 dict**（**非 `None`**）且 `last_modified is None`、`fingerprint is None`——**与 ① 行为不同**（① 视同 miss、③ 照常服务）。**证伪方向**：若读侧直接下标 `entry['xml']` / `entry['time']` ⇒ ① 抛 `KeyError`（用例红，且线上经 `_guard` 会变"上游失败"降级体）；若缺 `xml` 仍返回残缺 dict ⇒ 断言 `is None` 红。落点建议 `tests/test_cache.py::FeedEntryAccessorTests`。**★ v1.12 新增**：④ **`xml=''` ⇒ 命中（`''` 边界决定性命中例）**：注入 `xml=''`（键存在、值为空串）、其余字段齐全且未过期 ⇒ `feed_cache_get_entry(path)` **返回 dict（非 `None`）** 且 `feed_cache_get(path) == ''`——**证伪方向**：若实现把判据化简为 `not xml`（真值判断）⇒ 该条返回 `None` ⇒ **红**（这是 `is None` 与 `not xml` 的**唯一分叉边界**）。⑤ **非映射守卫（★ v1.13 / P2-6 已防御，三处落点）**：注入真值非映射条目（`['not','a','dict']` / `'not-a-mapping'`）⇒ `feed_cache_get_entry` / `feed_cache_get` 均返回 `None`（**不抛 `AttributeError`**）；**写侧**同形态亦不抛——强制触发①定时全扫（`_last_feed_sweep=0.0`）后 `feed_cache_put('/bad-prev', '<ok/>', 30, fingerprint='FP')` 正常返回、容器被改写为 dict、且**不继承**（`last_modified` 非 `None`，无幻影继承）。**证伪方向**：去掉任一 `isinstance(..., dict)` 守卫（读侧 / `feed_cache_put` 继承分支 / **共享 `_sweep_expired`**）⇒ `AttributeError` ⇒ 红。**告警可观测/去重（独立方法 `test_t_cache_36_degraded_miss_warns_once`）**：缺 `xml` / `xml=None` 两次读（**同一原因的两把不同键**）⇒ 仅 **1** 条 `log.warning`（**按原因去重**，非按键）、消息含键与 `xml is None`、且**不含 "upstream"**；`xml=''` 照常服务、**不产生** warning。**✅ 已实现**：`tests/test_cache.py::FeedEntryAccessorTests::test_t_cache_36_read_side_fail_safe`（①–⑤）+ `test_t_cache_36_degraded_miss_warns_once` | **BR-CACHE-32**（读侧 fail-safe）/ **BR-CACHE-36**（可观测/去重）/ §10#30（已防御）/ 与 v1.10 `last_modified` 口径的**行为对比** / `server.md` 条件请求（不误报 `_guard` 降级） |

## 9. AC 追溯矩阵

| 本模块设计点 | 覆盖 AC |
|-------------|---------|
| 四段式 + 负缓存 + 半开 2s 探测（BR-CACHE-4..9） | **AC-S3**（模式 A/B） |
| 失败历史老化（BR-CACHE-20）消除"永久 2s 陷阱" | **AC-S3**（模式 B P95 不劣化）/ **AC-E2** 交互 |
| `FetchError(kind)` 枚举 + 失败与 null 可区分（BR-CACHE-16） | **AC-S6 / AC-A10** |
| `build_batch_response` 保留键 + 单一组装点（BR-CACHE-15..18） | **AC-A9 / AC-A10 / AC-S6** |
| 真 LRU + 双触发清扫 + 上限 2000（BR-CACHE-10..14） | **AC-E6** |
| feed LRU + `cache_policy('feed')` 派生上限/TTL | **AC-E6 / AC-A8** |
| `encoding` 形参 + longhu GBK（BR-CACHE-2 语义 + §2.6#19/20） | **AC-E9** |
| 过期=拒读+回源一次（BR-CACHE-1） | **AC-A4**（±0.5s 容差） |
| 全路径有界失败（不重入选举、不触网、gap 兜底） | **AC-S1 / AC-S7**（≤15s 单请求） |
| `build_batch_response` 纯函数 | **AC-A6**（1:1 映射 + 保序） |
| `cache_hit_ratio`/`cache_entries` 观测发布（Q1，非 AC） | AC-S10（观测项） |
| `deadline` 形参 + 闸门在命中之后（BR-CACHE-21） | **AC-E2**（REST 回源有界）/ **AC-S7**（超时兜底）/ **AC-A4**（命中不被预算拒绝） |
| `_probe_budget` 递增阶梯 + **`_PROBE_BUDGET_CAP=5s` 封顶**（BR-CACHE-22） | **AC-S3**（模式 B：自愈加速 + 稳态 **P95 ≈ 5s**）/ **AC-E2**（单请求 ≤15s） |
| follower 等待窗口 + `leader_alive`（BR-CACHE-23） | **AC-S1**（不升级本地预算为上游失败）/ **AC-S3** |
| metrics 锁外发布（BR-CACHE-24） | **AC-E1**（`/healthz` 快照不阻塞取数）/ AC-S10 |
| leader 令牌 `try/finally`（BR-CACHE-25） | **AC-S1**（异常不全站退化为超时） |
| **HTTP 连接复用池 + DNS TTL 缓存（v1.4 / BR-CACHE-26..29）** | **AC-E1**（单请求延迟：2C2G 实测 340ms→~48ms）/ **AC-E2**（50 码冷扇出 ~4.2s → 单 tick 内） |
| **`warm_transport` 启动预热（v1.4 / BR-CACHE-30）** | **AC-E2**（冷进程首轮不付全量握手/解析）/ AC-E1 |
| **`refresh_epoch` 新鲜度下限（v1.4 / BR-CACHE-31）** | SSE 每拍真刷新（消除 TTL==tick 相位耦合，名义 4s 不再退化为 8s） |
| **`feed_cache_get_entry` 访问器（★ v1.5 / BR-CACHE-32）** | **AC-A8**（feed 缓存同源）/ 本专项 R1（RSS `Last-Modified` 时间源）/ 兼容（`feed_cache_get` 签名不变）★ v1.7 / D-3：T-CACHE-32（含浅拷贝隔离负例）**已实现**——`tests/test_cache.py::FeedEntryAccessorTests::test_t_cache_32_shallow_copy_isolates_the_container` |
| **★ v1.8 / F1：feed 指纹继承 ⇒ `last_modified` = 表示变更时刻（BR-CACHE-33 / §2.4 / §5.3 / T-CACHE-33）** | **AC-A8** / 本专项 R1（跨 TTL 仍 304，IMS-only 客户端带宽收益）/ `server.md` BR-SRV-38 |
| **★ v1.8 / F5：`feed_cache_put` 返回写入条目（BR-CACHE-34 / §2.4 / §5.3 / T-CACHE-34）** | **AC-A8** / 兼容（新增可选 `fingerprint`、返回类型"只增"）/ `server.md` BR-SRV-48 |
| **★ v1.9 / F8：feed 取数锁表引用计数收敛（BR-CACHE-35 / §2.4 / §5.3 / T-CACHE-35）** | **AC-S9**（24h 资源总账：锁表不得随累计 Host 单调增长）/ **AC-S1**（并发不双抓的既有前提）/ `server.md` BR-SRV-50 |
| **★ v1.11：读侧 fail-safe（缺 `xml` ⇒ 视同 miss；`time`/`expires_at` 以 `.get` 读取）+ `feed_fetch_acquire` 先判空（BR-CACHE-32 / BR-CACHE-35 / §2.4 / §5.3 / T-CACHE-36）** | **AC-A8**（feed 缓存同源）/ 兼容（成功路径语义不变）/ `server.md` 条件请求（缺 `xml` 不得被 `_guard` 误报为"上游失败"降级体） |
| **★ v1.12：读侧 `''` 边界写死（合法但空 ⇒ 照常命中）+ 残缺降级可观测（`log.warning` 去重）（BR-CACHE-32 补 / BR-CACHE-36 新增 / §2.4 / §3.1 / §5.3 / §8 T-CACHE-36 ④⑤ / §10#29·#30）** | **AC-A8**（feed 缓存同源；`''` 合法但空照常服务）/ 兼容（成功路径语义不变）/ `server.md` 条件请求（缺 `xml` 不得被 `_guard` 误报为"上游失败"降级体；残缺事件可观测，与"上游故障"可区分） |
| **★ v1.13：`_feed_degraded_warned`/`_warn_feed_degraded_once` 实现注（按**原因**去重）+ §10#30 三处 `isinstance` 守卫（已防御）+ `_sweep_expired` 跳过非映射（BR-CACHE-36 补 / BR-CACHE-13 补 / §2.4 / §2.5 / §5.2·§5.3 / §8 T-CACHE-36 ⑤ / §10#30）** | **AC-A8** / **AC-S1**（读侧永不 fail-loud，不误报 `_guard` 降级）/ **AC-S9**（共享清扫不因畸形注入抛异常）/ 兼容（合法路径逐字不变） |

## 10. 与 SAD / 现有代码的偏差与歧义标注（不擅自改 SAD）

| # | 项 | SAD 表述 | 本文裁决 | 理由 |
|---|----|---------|---------|------|
| 1 | 负缓存"过期即清"（§4.3）vs 半开探测需失败历史（§2.3） | 两处张力 | **门禁**过期失效；**条目**保留至成功或满额淘汰（BR-CACHE-8） | 过期即删会使每轮退化为 10s+5s、P95≈10s → 直接违反 AC-S3 模式 B；半开探测的实现前提就是历史可见 |
| 2 | feed LRU 落点 | "落点 = `server._get_or_fetch_feed`" | 机制实现在 cache 层（`feed_cache_get/put`），server 保留防击穿并调用之 | 缓存机制归缓存层；避免 server 复制 sweep/LRU；server 详设须对齐 |
| 3 | `NEG_TTL = min(5, cache_policy('quote')['ttl'])` | §2.3 | 等价于常量 5（L1∈{8,120}），config 以 env 默认 5 注册 | 与 SAD 派生式数值等价 |
| 4 | `_cache_put` 签名 | 未涉及 | 加第 5 个可选参数 `metric_key='url'` | utils 仅 import 未调用 ⇒ 无破坏 |
| 5 | 存量用例 `test_fetch_json_leader_failure_does_not_stampede` | AR-10 已登记改写 | 断言改为 `err=8`/`max_active=1`/负缓存窗口内 <1ms | P2-N4 口径 |
| 6 | `json` import | — | **实现已删除** `import json`（v1.2 收口；该 import 从未使用） | 纯清洁化；`_fill_missing`/`build_batch_response` 不使用 `json` |
| 7 | **D-1** follower gap 分支 | §2.3 D-1 第 4 段仅"读负缓存并 raise" | 新增 fail-closed 兜底 `raise FetchError('upstream_error')`（leader 未留任何状态时，含 REV-DES-09 的 cache 写入失败） | 行为等价、**不触网**、不引入放大器 |
| 8 | **D-2** `build_batch_response` 防御细化 | §2.4 未定义 | `_` 前缀码跳过；`errors[code]` 非空但值非 `None` → warning 不收录；未知 kind 归一 `upstream_error` | 防御性细化，保证值域三分自洽 |
| 9 | **D-3** `socket` import | D-5 未提 | 新增 `import socket`（供 `_classify` 判定超时）；`logging` 同批补列（REV-DES-03） | 二者均在 tech-stack allowlist |
| 10 | **D-7 / REV-DES-01** plate stagger | §2.1 明令保留 3 分区 stagger | §2.6 #6–#9 目标列补「`cache_policy('plate')['ttl']` **+ handler 派生 stagger**」+ 脚注钉死派生式；**不得**字面替换为同一 ttl | 否则静默丢弃错峰（行为回归）；落点由 `server.md` 承接 |
| 11 | **逆向审查 1** 永久 2s 陷阱 | SAD 未定义 | 新增 `first_at` + `_HISTORY_AGE=600s` 老化口径（BR-CACHE-20）：老化后本次用全预算探测 | 消除"慢而 >2s 上游永不恢复"；AC-S3 影响量化见下 |
| 12 | **REV-DES-09** 段 3 try 范围 | 未涉及 | `_cache_put`/`_clear_negative` 移出网络 fetch 的 `except Exception`，单独 try/log（不落负缓存） | 编程错误不得被误判 `upstream_error` 并污染负缓存 |
| 13 | **P7b · `deadline` 形参与闸门位置** | SAD §2.3 D-1 无 `deadline`；`cache.md` v1.1 无该形参 | `fetch_json` 追加**第 5 位**可选形参；闸门**在段 1 命中之后**（BR-CACHE-21） | 命中零网络 ⇒ 已持有数据不得被调用方耗尽的预算拒绝；位置参数追加 ⇒ 18 调用点零改动 |
| 14 | **P7b · 递增半开探测阶梯** | SAD 未定义（v1.1 为"未老化恒 `PROBE_TIMEOUT(2s)`"） | `_probe_budget(fail_count)`：`2→4→_PROBE_BUDGET_CAP(5s)` 封顶（BR-CACHE-22） | 消除"慢而上游长时间滞留 2s 探测"；与 BR-CACHE-20 老化窗口互补（老化管"上限机会"，阶梯管"渐进预算"） |
| 18 | **v1.3 · 阶梯封顶 = `_PROBE_BUDGET_CAP(5s)`（AC-S3 裁决）** | SAD §2.3 D-1 未定义阶梯及其上限；v1.2 本文（§4.2/§5.1/§2.5）曾记"`REQUEST_TIMEOUT(10s)` 封顶" | 新增模块级机制常量 **`_PROBE_BUDGET_CAP = 5.0`**（**不注册 env**）；阶梯 `2→4→5`；`REQUEST_TIMEOUT(10s)` **降为**"无历史/已老化"两支的一次性全预算探测，**不再是阶梯上限** | v1.2 的 10s 封顶使持续黑洞 P95 退化到 ≈10s（低密度下甚至 ==10s），与 AC-S3 模式 B 的 P95 目标直接冲突。封顶 5s 后稳态周期 ≈10s、P95 ≈5s，且**单请求 ≤15s（AC-E2）不受影响**。详见下方量化 |
| 15 | **P7b · follower 等待余量与 `leader_alive`** | SAD §2.3 D-1 第 4 段仅"读负缓存并 raise" | 等待窗口 `+ _FOLLOWER_WAIT_MARGIN(1.0s)`；复查 `_fetch_inflight` ⇒ leader 存活报 `upstream_timeout` 且**不落负缓存/不计数**（BR-CACHE-23） | leader 取数后的发布（微秒级）不得因竞态把 follower 推入 gap 分支；本地等待预算≠上游失败 |
| 16 | **P7b · metrics 锁外发布** | SAD §2.4/§2.6 未定义发布时机 | `_publish_url_stats` 为唯一入口，**锁外**调用（BR-CACHE-24）；命中路径段①/③/④统一 `_record_hit_locked()` 计 hit | 否则 `/healthz` 快照可与取数热路径争锁；只计段①会按并发流量比例系统性压低 `cache_hit_ratio` |
| 17 | **P7b · leader 令牌 `try/finally`** | SAD 未定义 | 选举后全部逻辑置于 `try/finally`，`finally` 内 `pop` + `event.set()`（BR-CACHE-25） | 令牌泄漏会使该 URL 此后每次请求都沦为"等待死 leader"并超时 |
| 19 | **v1.4 · HTTP 连接复用池 + DNS TTL 缓存** | SAD §2.3 D-1 未定义传输实现；本文 v1.3 仍以 `urllib.request.urlopen` 为出口 | 新增 `_ConnectionPool`/`_DNSResolver`/`_pool_request`/`urlopen`（§2.7/§4.5 BR-CACHE-26..29） | 每请求新建 TCP+TLS **并重解析 DNS** 是 2C2G 上单请求 ~340ms 的主因（DNS ~176ms + 握手 ~78ms）；复用后 ~48ms。**行为等价 stdlib 契约**（`read()`/`HTTPError`/`URLError`/重定向），仅传输复用 |
| 20 | **v1.4 · `warm_transport` 启动预热** | SAD 未定义 | 新增公开函数（§2.7/BR-CACHE-30）；`server.main` 启动守护线程调用，**仅握手不发业务请求**、总函数 | 冷进程首个 50 码 quote 扇出实测 ~4.2s（超 0.8×tick 预算）：空池 + 空 DNS 缓存的首轮一次性成本 |
| 21 | **v1.4 · `refresh_epoch`（第 6 位关键字形参）** | SAD §2.3 D-1 无该形参；`stream` 的"每拍真刷新"由实现引入 | `_cache_fresh(entry, refresh_epoch)`：命中追加 `entry['time'] >= epoch`；段①/③/④ 一致；`None` 逐字不变；写 TTL 不变（BR-CACHE-31） | TTL 恰等于 tick 时，上一轮 δ 秒后写入的条目在本轮仍新鲜 ⇒ 名义 4s 刷新实际每 8s 才回源一次（相位耦合） |
| 22 | **v1.4 · import 面（`json`→`http.client`/`urllib.parse`）** | SAD/tech-stack allowlist | 本模块实际 import：`http.client`、`urllib.parse` 为新增；`json` 已删（v1.3 #6） | §1.3 一度仍列 `json` 而未列 `http.client`/`urllib.parse`——**与实现不符**，本版据实更正 |
| 23 | **v1.5 · `feed_cache_get_entry` 访问器** | SAD/PRD 未定义"取条目"接口；裁决 #3 只定"机制落 cache 层" | 新增公开访问器（BR-CACHE-32）；`feed_cache_get` 保留并改为其薄包装 | 条件请求需要条目的时间字段作 `Last-Modified`，而 `feed_cache_get` 只回 `xml`；**不得改 `feed_cache_get` 签名**（5 调用方 + `tests/test_cache.py`）。返回浅拷贝避免锁外改写容器条目。★ **v1.8 / F1 修订**：时间字段由 `time`（写入时刻）改 `last_modified`（表示变更时刻），见 #24 |
| 24 | **★ v1.8 · F1：feed 条目 `fingerprint`/`last_modified` + 指纹继承** | SAD/PRD 未定义；`server.md` v1.5–v1.8 取 `entry['time']` 作 Last-Modified | feed 条目新增 `fingerprint`/`last_modified`；`feed_cache_put` 与**同一键上一条目（即使已过期）**比指纹 ⇒ 相同继承、不同取写入时刻（BR-CACHE-33） | **P1-1**：写入时刻每次回源刷新 ⇒ IMS-only 客户端跨 TTL 必拿 200；只有跨 TTL 继承指纹才能让 `Last-Modified` 表示"最后一次变更"（`server.md` BR-SRV-38）。**cache 层不自行规范化 XML**（不 import server、不复制投影规则）⇒ `fingerprint` 由 server 侧 `_feed_fingerprint` 传入，cache 只做等值比较 |
| 25 | **★ v1.8 · F5：`feed_cache_put` 返回写入条目 + 可选 `fingerprint` 形参** | SAD/PRD 未定义；v1.5–v1.8 返回 `None` | 返回写入条目浅拷贝（BR-CACHE-34）；新增第 4 位可选 `fingerprint=None` | `server._get_or_fetch_feed` 需在 miss 路径拿到 `last_modified` 而不必二次查询（消除「200 带 ETag 却不带 `Last-Modified`」窗口 + 省一次加锁）；`fingerprint` 默认 `None` ⇒ 既有调用点零改动 |
| 26 | **★ v1.9 · F8：feed 取数锁表有界化（引用计数原语）** | SAD/PRD 未定义 feed per-键 锁表生命周期；`系统_代码评审报告_001.md` TS-4 曾因"`pop` 与持锁线程竞态 ⇒ 双抓"**主动移除 `pop`** ⇒ 现为只增不减 | 新增 `feed_fetch_acquire`/`feed_fetch_release` + `_feed_fetch_refs`（BR-CACHE-35）：`acquire` 计数 +1 后返回锁；`release` 递减、**归零两表同删** | **F2 把键空间从 5 条固定 path 变成 `path × 请求派生 base_url`**，而 `_valid_host_header` 只校验格式、不校验归属 ⇒ 任意合法主机名可造新键。**两个后果**：① 锁表**永久内存增长**（每键 ~300–450 B，外部可无界触发 ⇒ OOM）；② 键数超 `feed_cache` 上限 100 后每个新 Host 必 miss ⇒ 一次 `generate_rss` + sha256、LRU 持续抖动（**只放大本地 CPU，上游仍被 URL 级缓存兜住**）。**归零前 `pop` 会重演 TS-4 双抓** ⇒ 必须引用计数（`acquire` 计数先于返回） |
| 27 | **★ v1.10 · P2-1：`last_modified` 读取 fail-safe（`.get` 口径）** | 本文 v1.8–v1.9 的 §2.4 / §5.3 / BR-CACHE-33 写 `entry['last_modified']` / `prev['last_modified']`（直接下标）；SAD/PRD 未定义非六字段条目的行为 | `feed_cache_get_entry` 改 `entry.get('last_modified')`；`feed_cache_put` 继承分支改 `prev.get('last_modified')`（缺省 `None`）。`fingerprint` 两处读取**本就是** `.get`，无需改 | **评审 P2-1（`CR-RSS-20260918-003`）**：六字段契约之外的条目（legacy / 注入）用直接下标会抛 `KeyError`，经 `_guard` 被吞成**降级体**（语义错误：把"条目无变更时刻"误报为"上游失败"）。fail-safe 口径下缺字段 ⇒ `last_modified=None` ⇒ **不发 `Last-Modified`、禁用 IMS**（`If-None-Match` 仍按 ETag 正常评估），语义与"降级体"明确区分。**属读写口径收口，非 BR 语义变更**（正常路径字段恒存在） |
| 28 | **★ v1.11 · P2-4 补全：读侧 fail-safe（缺 `xml` ⇒ 视同 miss；`time`/`expires_at` 以 `.get` 读取）+ `feed_fetch_acquire` 先判空** | 本文 v1.5–v1.10 的 §2.4 / §5.3 / BR-CACHE-32 在返回时**直接下标** `entry['xml']` / `entry['time']`（且 `feed_cache_get` 亦 `entry['xml']`）、`feed_cache_put` 继承分支仅对两个字段做 `.get`；SAD/PRD 未定义"形态不完整条目"的读侧行为 | ① 缺 `xml`（或 `None`）⇒ **视同 miss（返回 `None`）**，`feed_cache_get` 同样返回 `None`；② `time` 用 `entry.get('time')`（缺省 `None`）；③ `expires_at` **沿用** `entry.get('expires_at', 0)`（缺省 `0` ⇒ `now >= 0` 恒成立 ⇒ 自然过期 ⇒ 亦视同 miss）；④ `last_access` 由访问器自写、恒存在，**不需 `.get`**（避免过度防御）；⑤ `feed_fetch_acquire` 改**先 `get` 判空、仅未命中才建 `Lock`**（命中路径零分配，语义不变） | **评审 `CR-RSS-20260918-004/005` 的 P2 与遗留清单**：读侧直接下标在"live 条目"与"注入 / 降级 / legacy 条目"之间留了 `KeyError` 窗口——异常经 `_guard` 会变成与缺 `last_modified` 同一类**降级体**，把"条目残缺"误报为"上游失败"。fail-safe 口径让读侧**要么照常服务、要么当作没有**（或降级为无该头），**永不 fail-loud**。**属读侧口径补全，成功路径行为不变**（正常条目六字段恒在）；`acquire` 的 `get`+建锁为**实现约束**，观察行为不变 |
| 29 | **★ v1.12 · `expires_at` 缺省 `0` 的隐含前提（`time.time() >= 0`）** | SAD/PRD 未定义"缺 `expires_at`"与"非负时钟"前提 | 保持现口径：`entry.get('expires_at', 0)` 缺省 `0` ⇒ `now >= 0` 恒真 ⇒ 视同过期（miss）；且 `feed_cache_get_entry` 命中路径的 `entry['expires_at']` **直接下标**亦依赖同一"非负时钟"前提。**当前不可达**：只有"时钟被测试打桩为**负值**"时才可能反转为**命中**，届时该直接下标才可能 `KeyError`（经 `_guard` 变降级体）。全仓测试**只用** `_FixedClock(time.time())`（起点为正）；`_StepClock` 起点 `1_700_000_000` 且只打桩 `srv.time`、不影响 `cache.time` | **已知边界，登记不修**（评审 P2-3）：生产时钟恒非负。若未来允许负时钟打桩，须把命中路径的 `entry['expires_at']` 一并改 `.get`（或显式断言 `now >= 0`）。**只报告、不改 SAD** |
| 30 | **★ v1.12 登记 / ★ v1.13 状态更正：真值非映射条目的读侧行为（`entry.get` 抛 `AttributeError`）** | SAD/PRD 未定义 `feed_cache[key]` 被注入**非映射真值**（如 `str`/`list`）时的行为 | **★ v1.13 更正为「已防御」**：实现已加 **`isinstance(..., dict)` 守卫**，三处落点——① `feed_cache_get_entry`（非映射 ⇒ `_warn_feed_degraded_once('entry is not a mapping', key)` + **视同 miss**，不抛）；② `feed_cache_put` 的继承分支（`prev is not None` → `isinstance(prev, dict)`；非映射 `prev` ⇒ **不继承**、`last_modified` 走 `now`）；③ **共享的 `_sweep_expired`**（判定式 `entry and isinstance(entry, dict) and now >= entry.get('expires_at', 0)`；**URL 缓存与 feed 缓存两个缓存共用**）。 | **状态更正（v1.12 的"已知边界，登记不修"口径作废）**：① 生产**仍不可达**（`feed_cache_put` 只写 `dict`、访问器返回浅拷贝 `dict`，生产写入方恒为 dict）；② **为什么 ③ 是必要的最小改动而非越界**——**实测证据：只去掉 ③ 的守卫，`feed_cache_put` 在触发①定时全扫分支仍 `AttributeError` ⇒ put 的防御不成立**；③ 作为**共享助手**，其行为变化同时覆盖 URL 缓存路径（**合法路径行为逐字不变**，仅畸形条目不抛）。**只报告、不改 SAD**（SAD 未定义该行为，不构成 SAD↔详设矛盾）。 |

> **§10#11 的 AC-S3 影响量化（★ v1.3 按 AC-S3 裁决 / 实现重写——遗留项已闭环）**
>
> v1.1 的量化（"任一 5min 窗口至多 1 次 10s 升级探测 ⇒ 占慢请求 ≤1.2% ⇒ P95 仍为 2s"）随 `_probe_budget` 递增阶梯落地而失效；v1.2 因此把 P95 结论退化为"密度相关（低密度 ≈ 当轮预算 ≤10s）"。**v1.3 的 `_PROBE_BUDGET_CAP=5s` 封顶消除了该退化**：
>
> | 相 | 探测预算 | 说明 |
> |----|---------|------|
> | 首轮（无条目） | 10s | 冷预算（`REQUEST_TIMEOUT`） |
> | 连续失败 1 / 2 / ≥3 次 | 2 / 4 / 5s | `_probe_budget` 阶梯，`_PROBE_BUDGET_CAP=5.0` 封顶；每轮之间夹 `NEG_TTL=5s` 门禁 |
> | 失败段已老化（≥`_HISTORY_AGE=600s`） | 10s | BR-CACHE-20 的一次性全预算探测（不走上限），失败后 `first_at` 重置 |
>
> ⇒ 持续黑洞上游在 **2 次失败（约 20s）内**即收敛到 **5s** 探测，之后每 `5s(探测) + 5s(门禁) = 10s` 一个周期。
>
> **P95 结论（与请求密度无关）**：
> - 稳态每周期恰有 1 次请求真正触网（占比 ≈50% 的请求落在"门禁期快速失败 <1ms"上），另 1 次承担 5s 探测 ⇒ **P95 ≈ 5s**。
> - 请求密度只改变"单位时间触网上游次数"（= `1/周期`），**不改变单请求延迟分布**（v1.2 的"低密度 ⇒ P95≈10s"不再成立）。
> - **单请求上界 `≤15s`（AC-E2）恒成立**（5s 探测 ≪ 15s；单请求最大 = 探测 5s + 余量）。
>
> **结论（AC-S3 裁决已落地）**：① 梯**上限**= `_PROBE_BUDGET_CAP`（**非** `REQUEST_TIMEOUT`，后者仅用于冷预算与老化全预算探测）；② `PROBE_TIMEOUT`（env 可调）**仍为阶梯首级**，默认 2 不变；③ 若运维把 `PROBE_TIMEOUT > 5` 覆盖，则首级即越过封顶（`_probe_budget` 返回首级值）⇒ **env 覆盖须重跑 AC-S3 校准**（同 `config.md` §2.3 的 `NEG_TTL` 前提）。默认值（`PROBE_TIMEOUT=2` / `_PROBE_BUDGET_CAP=5` / `NEG_TTL=5` / `_HISTORY_AGE=600`）下 T-CACHE-4/4c/4d/21 已覆盖。

> **编排层裁决回执（2026-09-15）**：#1 `'n/a'`→`None` ✅（`config.md` §2.1）；#2 负缓存「门禁过期失效、条目保留作失败历史」✅ **且为 AC-S3 模式 B 必要条件**（§4.2 BR-CACHE-8 / §10#1）；#3 feed LRU 落 cache.py ✅（§2.4，并补双检语义）；#4 metrics `key=`/`reset()` ✅；#5 `cache_hit_ratio` 发布点 ✅（§5.2/§7.3）；#6 `STREAM_PING_INTERVAL` env ✅（`config.md` §2.3）。

## 11. 交付自检

- [x] 四段式每段有精确判定与锁边界；网络 IO 不持锁
- [x] `FetchError` kind 枚举封闭；`build_batch_response` 为总函数
- [x] 保留键三键出现/不出现条件逐条钉死；`_errors` 值域枚举
- [x] 18 调用点逐一列名 + 兼容策略（编码零改动 / TTL 同批收敛）；**#6–#9 plate stagger 不丢**（REV-DES-01 脚注）
- [x] LRU 与双触发清扫可白盒断言；`_sweep_expired` 兼容既有用例
- [x] 锁清单 + 锁序纪律 + 与 `_feed_cache_lock`/`_feed_fetch_locks_lock` 关系
- [x] `logging` 在 allowlist 且 `log` 已初始化（REV-DES-03）
- [x] `cache_hit_ratio` 有公式 + 唯一发布点 + 命名统一 `_cache_stats{hit,miss}`（REV-DES-02）
- [x] 段 3 cache 写入移出网络 try，且先于 `event.set()`（REV-DES-09）
- [x] 失败历史老化口径可断言（BR-CACHE-20 / T-CACHE-4b/4c/6b）
- [x] AC 追溯覆盖 S3/S6/A4/A9/A10/A6/E6/E9/S1/S7
- [x] **v1.2（P7b）**：`fetch_json` 的 5 位形参、两处 deadline 闸门位置、`_probe_budget` 阶梯、follower 等待窗口 + `leader_alive` 三态、metrics 锁外发布、leader 令牌 `try/finally` 与实现逐行一致（§2.1/§4.2 BR-CACHE-21..25/§5.1/§7.3/§8 T-CACHE-21..25）
- [x] **v1.2（P7b）**：`import json` 已删（§10#6 收口）；§2.5 兼容清单补 `_probe_budget`/`_effective_timeout`/`_follower_wait_budget`/`_FOLLOWER_WAIT_MARGIN`/`_record_hit_locked`/`_publish_url_stats`
- [x] **v1.3（AC-S3 裁决）**：阶梯封顶更正为 **`_PROBE_BUDGET_CAP=5.0`**（§1 头部 / §2.1 四段式+行为表 / §2.5 / §3.1+§3.5 / §4.2 BR-CACHE-8·22 / §5.1 / §8 T-CACHE-4·4c·4d·21 / §9 / §10#11·#18）；`REQUEST_TIMEOUT` 角色收敛为"冷预算 + 老化全预算探测"；稳态 P95 ≈ 5s、单请求 ≤15s
- [x] **v1.4（P7b 传输层）**：连接复用池 + DNS TTL 缓存 + `urlopen` 单一网络缝 + `warm_transport`（§2.7 / §3.6 / §4.5 BR-CACHE-26..30 / §5.5 / §6 / §7.1·7.2 / §8 T-CACHE-26..30 / §9）
- [x] **v1.4（P7b 传输层）**：`fetch_json` 第 6 位关键字形参 `refresh_epoch` + `_cache_fresh` 下限（§2.1 / §4.5 BR-CACHE-31 / §5.1 / §8 T-CACHE-31 / §10#21）
- [x] **v1.4（import 面更正）**：§1.3 删 `json`、补 `http.client`/`urllib.parse`（§10#22，据实现更正）
- [x] **v1.5（P3a · 条件请求支撑）**：新增 `feed_cache_get_entry`（§2.4 / §2.5 兼容表 / §3.1 `time` 标注 / §4.3 BR-CACHE-32 / §5.3 / §8 T-CACHE-32 / §9 / §10#23）；`feed_cache_get` **签名/语义不变**（薄包装）；**无新增锁/字段/TTL/清扫/上限变更**
- [x] **v1.6（P3a-r1 评审定向修）**：§8 `T-CACHE-32` 扩**浅拷贝隔离容器态负例**（C7#14）；头部溯源修正为 **SAD v1.7 / PRD v0.6**（C8③）；**无实现/契约变更**（BR-CACHE-32 正文未改）
- [x] **v1.7（P7b 漂移回填 D-3）**：§8 `T-CACHE-32`（含 v1.6 浅拷贝隔离负例）标注 **✅ 已实现**——`tests/test_cache.py::FeedEntryAccessorTests::test_t_cache_32_shallow_copy_isolates_the_container`（容器态负例）+ `test_srv_t60_feed_cache_get_entry_contract`（契约）；§9 映射同步标注；**无实现/契约变更**（签名/锁/容器字段/TTL/清扫/上限/BR-CACHE-32 正文均不变）
- [x] **v1.8（P8 F1/F5）**：feed 条目新增 `fingerprint`/`last_modified`（§3.1 / §2.4 / §5.3）；`feed_cache_put(path, xml, ttl, fingerprint=None) -> dict` 指纹继承（**含过期条目**、`prev` 先于 sweep 捕获）+ 返回写入条目（BR-CACHE-33/34）；`feed_cache_get_entry` 六字段（BR-CACHE-32 改写）；`server.md` BR-SRV-38/48 对齐；测试 **T-CACHE-33/34 新增 + T-CACHE-32 扩六字段**；§10#24/#25 登记。**`feed_cache_get` 签名/语义、锁、TTL/清扫/上限不变**；**未改代码 / SAD / PRD / API.md / README.md / `.opencode`**
- [x] **v1.9（P8 F8）**：新增 `feed_fetch_acquire`/`feed_fetch_release` + `_feed_fetch_refs`（BR-CACHE-35；归零两表同删、`pop` 不变式、正确性论证、`acquire`/`finally release` 纪律、有界性结论、可选运营缓解）；§2.4 **双检措辞更正**为 `feed_cache_get_entry`（与 `server.md` §2.5 / `SRV-T70` 一致）；头部溯源 **SAD v1.7 → v1.9**；新增 **T-CACHE-35**；§2.5/§3.5/§5.3/§7.1·7.2/§9/§10#26 同步。**`feed_cache_get`/`feed_cache_get_entry`/`feed_cache_put` 签名语义、锁序、TTL/清扫/上限、BR-CACHE-32/33/34 正文不变**；**未改代码 / SAD / PRD / API.md / README.md / `.opencode`**
- [x] **v1.10（P2-1 fail-safe 收口 + 溯源更正）**：`feed_cache_get_entry` 读 `entry.get('last_modified')`、`feed_cache_put` 继承分支读 `prev.get('last_modified')`（缺省 `None`）；legacy / 非六字段条目 ⇒ `last_modified=None` ⇒ **不发 `Last-Modified`、禁用 IMS**，**不抛 `KeyError` 经 `_guard` 变降级体**；`fingerprint` 读取本为 `.get`（核对通过，无需改）；落点 §2.4（返回契约 + 指纹继承）/ §3.1（`<float|null>`）/ §4.3 BR-CACHE-32/33 / §5.3 伪代码 / §8 T-CACHE-32/33 / §10#27；**BR-CACHE-32/33 为口径收口（补 `.get` 读取说明）、无 BR 语义变更**；头部溯源 **PRD v0.6 → v0.8**（SAD v1.9 保持）。**未改代码 / SAD / PRD / API.md / README.md / `.opencode`；`server.md` → v1.11、`_PROGRESS.md` 同步**
- [x] **v1.11（读侧 fail-safe 口径补全 + `acquire` 实现约束）**：`feed_cache_get_entry` 缺 `xml`（或 `None`）⇒ **视同 miss**（`feed_cache_get` 同）；`time` 以 `entry.get('time')` 读取（缺省 `None`）；`expires_at` 沿用 `entry.get('expires_at', 0)`（缺省 `0` ⇒ `now >= 0` 恒成立 ⇒ 自然过期 ⇒ miss）；`last_access` 恒存在**不需 `.get`**（与 v1.10"有 `xml` 缺 `last_modified` ⇒ 仍服务"**明确区分**）；`feed_fetch_acquire` 改**先 `get` 判空、仅未命中建 `Lock`**（命中路径零分配，语义不变）；新增 **T-CACHE-36**；落点 §2.4（返回契约 + `acquire` 实现约束）/ §4.3 BR-CACHE-32·35 / §5.3 伪代码 / §8 / §9 / §10#28。**成功路径语义 / 锁序 / TTL·清扫·上限 / BR-CACHE-34·35 语义不变**；**未改代码 / SAD / PRD / API.md / README.md / `.opencode`；`server.md` → v1.12、`config.md` → v1.5、`_PROGRESS.md` 同步**
- [x] **v1.12（最后一轮契约收口）**：`feed_cache_get_entry` miss 判据写死为 `entry.get('xml') is None`，**`xml=''` 属「合法但空」⇒ 照常命中**（显式禁止 `not xml` 真值化简，防**永久回源环**）；缺 `xml` 视同 miss 分支**必须** `log.warning`（含键与原因、按「原因/键」去重）+ 语义澄清（**形态残缺自愈路径**，非上游故障、生产不可达、`feed_cache_put` 恒写 `xml`）→ **新增 `BR-CACHE-36`**；§10 续号 **#29**（`expires_at` 缺省 `0` / 非负时钟前提，当前不可达）/ **#30**（非映射条目 `AttributeError`，实现未加 `isinstance` ⇒ **登记不修**）；`T-CACHE-36` 增 **④ `xml=''` 命中** + **⑤ 告警去重**断言；落点 §2.4 / §3.1 / §4.3 BR-CACHE-32·36 / §5.3 / §8 / §9 / §10。**成功路径语义 / 锁序 / TTL·清扫·上限 / BR-CACHE-32..35 主体不变**；**未改代码 / SAD / PRD / API.md / README.md / `.opencode`；`server.md` → v1.13、`_PROGRESS.md` 同步**
- [x] **v1.13（实现事实对齐 + 溯源更正）**：`_feed_degraded_warned`（`set`，**按原因**去重）+ `_warn_feed_degraded_once(reason, key)`（消息含键、措辞=**条目自愈信号非 "upstream error"**、复用**既有**模块级 `log`）写入 **BR-CACHE-36**；**§10#30 由「登记不修」更正为「已防御」**（三处 `isinstance(..., dict)`：`feed_cache_get_entry` / `feed_cache_put` 继承分支 / **共享 `_sweep_expired`**；③ 的必要性有实测证据：去掉后 `feed_cache_put` 在定时全扫分支仍 `AttributeError`）；`_sweep_expired` 契约补"**跳过真值非映射条目**"（BR-CACHE-13 / §2.5 / §5.2·§5.3）；`T-CACHE-36` ⑤ 更正为**非映射守卫**、告警去重由独立方法 `test_t_cache_36_degraded_miss_warns_once` 覆盖（同一原因两把键 ⇒ 1 条）；头部溯源 **SAD v1.9 → v1.11 / PRD v0.8 → v0.9**（**最后一处溯源滞后闭环**）。**除 #30 属实现状态更正外，无 BR 语义变更**；**未改代码 / SAD / PRD / API.md / README.md / `.opencode`；`server.md` → v1.14、`metrics.md` → v1.6、`_PROGRESS.md` 同步**




