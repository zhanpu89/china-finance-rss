# RSS 条件请求 F8 修复（锁表有界化）+ 配套 P2 修正 定向复审

- **CR 编号**：CR-RSS-20260918-004
- **状态**：定向复审完成 · ✅ 通过（无 P0 / 无 P1；上一轮 P1-1 **已闭合**）
- **评审模式**：P5b 定向复审（增量）+ 反假绿抽查 + 契约漂移核对
- **日期**：2026-09-18
- **复审范围**：仅本轮增量（F8 + P2-1..P2-4）。**已通过的 F1–F7 不重评**（沿用 CR-RSS-20260918-003 结论）。
- **关联文档**：`doc/detailed/server.md`（头部**实际 v1.10**，见 P2-1）· `doc/detailed/cache.md` v1.10 · `doc/detailed/metrics.md` v1.5 · `doc/detailed/_PROGRESS.md`
- **入参**：未携带 `>>SIDE-EFFECT:` 标记；受影响点由变更面推断（见 §三 末）。
- **取证限制**：本环境无 shell，**未能实跑** `python -m unittest`。下文"能否翻红"均为**静态推演**并逐条标注；建议编排器安排一次实跑把判定升级为实证。

## 一、评审概要

**F8（`feed_fetch_acquire`/`feed_fetch_release` 引用计数惰性回收）落地正确，引用计数不变式在实现层成立；P2-1..P2-4 四项配套修正均已真正消化。** 未引入新竞态，未发现新 P0/P1。

| 等级 | 数量 | 处理 |
|------|------|------|
| P0 | 0 | — |
| P1 | 0 | — |
| P2 | 6 | 记录，不阻断（1 项文档漂移 + 1 项覆盖缺口 + 4 项低风险备注） |

**是否阻断：不阻断。** 结论：✅ **允许进入测试/合入**。上一轮判定的**部署级阻断（P1-1 `_feed_fetch_locks` 无界增长）已闭合**；默认配置下不再存在"外部合法 Host 可无界撑爆锁表"的内存缺陷。

## 二、评审范围

- `china_finance_rss/cache.py`：`_feed_fetch_locks`/`_feed_fetch_refs`(901-907)、`feed_cache_get_entry`(911-932)、`feed_cache_put`(945-982)、`feed_fetch_acquire`(994-1005)、`feed_fetch_release`(1008-1021)
- `china_finance_rss/server.py`：`_get_or_fetch_feed`(1329-1364)、`_serve_feed`(1366-1385)、`_send_not_modified`(1460-1491)、`_send_text`(1416-1458)、`_guard`(624-649)、`_not_modified`(895-903)
- `tests/test_server_http.py`：`RssConditionalGetTests.setUp`(1088-1094)、`test_t55`(1376-1421)、`test_t69`(1697-1724)、`test_t71`(1763-1784)、`test_t72`(1786-1844)
- `tests/test_cache.py`：`_TRACKED_GLOBALS`(17-20)、`_CacheTestCase.setUp`(41-57)、`test_t_cache_33`(310-335)、`FeedFetchLockTests`(358-444)
- 契约核对：`doc/detailed/cache.md` v1.10（BR-CACHE-35 / P2-1 fail-safe）· `doc/detailed/server.md`（BR-SRV-50 / BR-SRV-45 补正 / BR-SRV-46 P2-5 备注）· `doc/detailed/metrics.md` v1.5

只读核对，未改动任何代码或文档（本报告除外）。

## 三、问题清单

| ID | 等级 | 文件:行 | 问题 | 建议 |
|----|------|---------|------|------|
| P2-1 | P2 | `cache.md:4` / `server.md:3` / `_PROGRESS.md:451,456,132` | 文档版本漂移：`cache.md` v1.10 声明"`server.md` → v1.11"，但 `server.md` 头部**仍是 v1.10**、全库无 v1.11；`_PROGRESS.md` 仍记 cache.md v1.9、server.md v1.10，且 F8 行仍写"**代码待 code-developer 落地**"（已落地）。本报告入参所称"server.md v1.11"亦不存在 | 编排层二选一：把 server.md 升 v1.11（若 P2 轮确有服务端契约变更）**或**改 `cache.md:4` 的同步目标为 v1.10（无变更）；并刷新 `_PROGRESS.md` |
| P2-2 | P2 | `tests/test_server_http.py:1763-1784` | 契约 `SRV-T71` 明确列出的"**并发不同 Host 变体**：在飞 K 键时 `len <= K`"未实现；现有仅串行 N=50 断言 `== 0`。原语级 `T-CACHE-35④` 以"同时持有 5 键"近似，但 server 级并发收敛无直接断言 | 补一个并发变体（K 个不同 Host 同时发起，进入后采样 `len(_feed_fetch_locks) <= K`，全部返回后 `== 0`），或由编排层裁定降级该子项并同步契约 |
| P2-3 | P2 | `cache.py:1003` / `server.py:1352-1363` | F8 只闭合了 P1-1 的**内存无界增长**侧面；P1-1 登记的第二后果——`PUBLIC_BASE_URL` 未设时每来一个新合法 Host 必 miss ⇒ 一次 `generate_rss` + `sha256` + LRU 抖动（本地 CPU 放大）——**按选定方案 1 未受约束**（BR-SRV-45 补正 / BR-SRV-50 已登记为"可选运营缓解"） | 非阻断。部署侧强制设 `PUBLIC_BASE_URL`（键退化为 5 条 path），或加 Host 白名单 / 未知 Host 归一到单键 |
| P2-4 | P2 | `cache.py:928-932` | P2-1 fail-safe **不完整**：仅 `last_modified`/`fingerprint` 改 `.get`；`time`/`last_access`/`expires_at` 仍直接下标。非六字段条目若含 `expires_at` 但缺 `last_access`/`time`，仍 `KeyError` → 经 `_guard` 变降级体。v1.10 契约只承诺 `last_modified`，故**非违约** | 可选：三字段一并 `.get` 或对非六字段条目统一按"过期/不可用"处理；至少保证访问器对畸形注入恒不抛 |
| P2-5 | P2 | `cache.py:1003` | `setdefault(key, threading.Lock())` 每次 feed miss 都**先构造一个被丢弃的 Lock**（Python 参数先求值）。仅 miss 路径，影响可忽略 | 可选微优化：`lock = _feed_fetch_locks.get(key)`，缺才建 |
| P2-6 | P2 | `tests/test_server_http.py:1088-1094` / `tests/test_cache.py:320-323` | 测试健壮性备注：① `RssConditionalGetTests.setUp/cleanup` **清空真实锁表**，使"跨用例累计泄漏"永不被观测（T71 的**逐次**断言仍覆盖 F8 主行为，故不掩盖本次缺陷；但若 T71 断言被弱化，风险复现）；② `T-CACHE-33` 继承向断言依赖真实时钟两次取值不同，同值碰撞会伪绿（概率极低） | ① 可加一条"不清空、跨 10 次请求后再断言归零"的独立用例；② 可选改用受控时钟 |

### 受影响点推断（供 tester 定向回归；入参无 `>>SIDE-EFFECT:`）

| 受影响点 | 模块 | 行为变化 / 回归关注 |
|----------|------|---------------------|
| `_get_or_fetch_feed` 加锁改 `acquire`/`finally release` | server/cache | 所有 5 条 feed 路由的 miss 路径；成功/双检命中/异常三条释放路径 |
| 新增 `feed_fetch_acquire`/`feed_fetch_release` + `_feed_fetch_refs` | cache | 新公开面；`server` 不再 import `_feed_fetch_locks(_lock)`（`server.py:52` 仅 import 两原语） |
| `last_modified` 读取改 `.get(...,None)` | cache/server | legacy/非六字段条目 ⇒ 200/304 **均不发 `Last-Modified`、IMS 不可评估**；正常条目不受影响 |
| feed 锁表生命周期 | cache | 键存在 ⟺ 引用计数 ≥1；归零两表同删 |
| 测试隔离新增清空锁表 | tests | `RssConditionalGetTests` 全类 |

## 四、复审要点逐条判定

### 要点 1 — P1-1 是否真正闭合（不变式 / 窗口 / 释放路径 / 计数泄漏）

**判定：已闭合。**

- **不变式 `计数 ≥1 ⇒ 键不可回收` 成立**：`feed_fetch_acquire`(`cache.py:1002-1005`) 先 `setdefault` 建锁、**再把 `_feed_fetch_refs[key] += 1`、最后才 `return lock`**——计数先于返回，故"调用方已持有锁对象但尚未进入 `with`"的窗口被计数覆盖。`feed_fetch_release`(`:1015-1021`) 仅当 `n <= 0` 才 `pop` 两表。`pop` 时的 `n==0` 意味着没有其它未释放的 acquire（含等待者——等待者必已计数），故无持有者/等待者，`pop` 安全。
- **"已取锁未进 `with`"窗口不可被绕过**：`acquire` 与 `release` **都持同一把 `_feed_fetch_locks_lock`**(`:1002`/`:1015`)。后来者在 `setdefault` 时必然看到前者的计数 ≥1（同锁互斥 + happens-before），拿到的是**同一把锁对象**，不会另建。
- **`release` 所有路径都执行**：`server.py:1352-1363` 为 `lock = acquire(k)` → `try: with lock: … finally: release(k)`。命中双检 `return`(`:1357`) 在 `with` 内，退出 `with` 后 `finally` 仍执行；成功路径 `return xml, entry[...]`(`:1364`) 在 `try` 之后、`finally` 已执行；`fetch_func()`/`feed_cache_put` 抛异常、以及 `KeyboardInterrupt`/`SystemExit` 等 **BaseException** 均由 `finally` 兜住。`acquire` 与 `try` 之间无任何语句，无"取锁成功却未进 try"的缝隙。
- **计数泄漏不可达**：唯一 acquire 消费点即 `_get_or_fetch_feed`，且与 release 一一配对；`feed_fetch_acquire` 内部在 `return` 前无抛点。全仓仅此一处调用（`grep` 确认）。
- **理论边角（不构成缺陷）**：若线程在 `__enter__` 阻塞期间收到 `KeyboardInterrupt`，CPython 的 `Lock.acquire()` 默认不可被信号中断，异常在 `__enter__` 返回后于 `with` 体区域抛出，异常表会调用 `__exit__` 释放实际锁；即便退一步未释放，`finally` 也已把计数归零并 `pop`（锁对象随之不可达），不影响后续。**无实际缺口**。

### 要点 2 — 是否引入新竞态（归零回收后的双抓 / 两表同步）

**判定：未引入新竞态，两表恒同步。**

- **归零回收后不会漏掉前一持有者的写入**：设 A 持锁写完 `feed_cache` 后 `release`（计数归零、`pop`），B 的 ① `feed_cache_get_entry` 若在 A 写前已 miss，则 B 的 `acquire` 与 A 的 `release` 通过**同一把 `_feed_fetch_locks_lock`** 形成 happens-before：B 取得该锁时，A 在 release 之前的一切写（含释放 `_feed_cache_lock` 的 put）对 B 可见 ⇒ B 的双检必然命中 A 的条目。若 B 的 ① 晚于 A 的 put，则 ① 直接命中、根本不进入 `acquire`。任一方向都**不会产生同键双抓**。
- **真正的并发重叠**（B 在 A 持锁期间 acquire）⇒ 计数 ≥2 ⇒ 不 `pop` ⇒ 同一把锁 ⇒ B 阻塞至 A 释放，之后双检命中。**双检 + per-key 锁 + `_feed_cache_lock` 三层语义均未被 F8 改变。**
- **两表同步**：`acquire` 在同一临界区内 `setdefault`（锁表）+ 计数（计数表）；`release` 归零时 **`pop` 两表**(`:1018-1019`)，非归零只写计数。不存在"删了一个没删另一个"的路径 ⇒ `_feed_fetch_refs` 不会成为新的无界表。
- **残留风险**：仅当调用方**双次 release** 时，`.get(key, 1)` 的缺省 `1` 会让多余的一次递减把仍被他人持有的键 `pop`（进而可能双抓）。当前代码无此调用；这是原语层"防御性缺省"而非实现缺陷，但契约要求成对调用，值得保留在纪律条款中。

### 要点 3 — P2-1..P2-4 是否真被消化

**判定：四项均已真正消化。**

- **P2-2（`test_t55`，`test_server_http.py:1376-1421`）**：注入条目 `last_modified=1.0` 且 `fingerprint` 与**重生成体**的 `_feed_fingerprint` 相同（`<lastBuildDate>/<ttl>/<pubDate>` 被规范化剔除，故跨时刻同指纹），`expires_at` 已过期 ⇒ 必 miss 回源 ⇒ `feed_cache_put` 走继承分支。断言 `h_priv.get('last-modified') == inherited_lm`（`formatdate(1.0)`）。**若禁用继承 ⇒ `last_modified=now` ⇒ 头 ≠ 1970 ⇒ 翻红**；若 `put` 返回 `None` ⇒ 访问 `entry['last_modified']` 抛错、304 变降级 200 ⇒ 两条断言同时红。注入值**真被消费**。
- **P2-3（`test_t69`，`:1712-1724`）**：受控分叉桩 `feed→{'ttl':7}` / 其余 `→{'ttl':999}`。若 `_CACHE_AGE_DOMAINS[path]` 回退为 `news_url`，则 `h._cache_age()` 得 999 ≠ 7 ⇒ **翻红**；`_feed_ttl_minutes()` 恒读 `feed` 得 1，配合第一段 `assertEqual(_CACHE_AGE_DOMAINS[path],'feed')` 共同锁定 authority。证伪方向已触发。
- **P2-4（`T-CACHE-33`，`test_cache.py:310-335`）**：写前置 `_last_feed_sweep = 0.0` ⇒ 第二次 `put` 内触发①定时全扫；`assertGreater(_last_feed_sweep, 0.0)` **证明清扫确实发生**；`assertEqual(written['last_modified'], first['last_modified'])` 证明**过期条目仍参与继承**（即 `prev` 先于 sweep 捕获）。若实现"先 sweep 再取 prev"，过期条目被删 ⇒ 无继承 ⇒ `last_modified=now2 ≠ now1` ⇒ **翻红**。顺序要求已被触达。
- **P2-1（`cache.py:929,970`）语义与契约一致**：`entry.get('last_modified')` 缺字段返回 `None`。链路核对：`feed_cache_get_entry` 返回 None 型 `last_modified` → `_serve_feed` 的 `_not_modified`：INM 存在时仍按 ETag 评估（可 304，**合法**），IMS 存在时 `_if_modified_since_not_modified`(`server.py:882-883`) 见 `None` **直接 False ⇒ 200**；`_send_text`(`:1435`) 与 `_send_not_modified`(`:1480`) **都在 `None` 时省略 `Last-Modified`**。故 200 与 304 **同源、同缺省**，**不产生"304 与 200 头不一致"**。正常生产条目恒含该字段（唯一写入方 `feed_cache_put` 恒写六字段），None 仅对注入/legacy 条目生效。

### 要点 4 — 反假绿抽查

- **`SRV-T71` 不随 N 增长**（`:1763-1784`）：串行 50 个不同 Host，**每次请求后**断言 `len(_feed_fetch_locks) == 0`。若 `release` 缺失或未在 `finally`，第 1 次后即为 1 ⇒ 立即红。**不是"碰巧为 0"**——它是"累计 N 次后必须回到 0"的强断言。
- **并发用例有真实同步**：`test_t72_concurrent_same_key_single_fetch`(`:1786-1826`) 用 `entered`/`finish` 两个 `threading.Event` 把首线程**确定性地卡在 `fetch_func` 内**，再启动第二线程，并**有界轮询** `_feed_fetch_refs == 2`（2s 上限）后才断言 `calls['n'] == 1`；若超时，随后的 `assertEqual(refs, 2)` **失败而非误过**（最坏是"假红"而非"假绿"）。`T-CACHE-35②` 同用 `b_acquired` Event + 锁本身；其 `time.sleep(0.1)` 只用于**否定式**断言（B 未进入），只会让判定更严，不会造成假绿。**无靠 sleep 撞运气的正例断言。**
- **并发不同 key 变体缺失**：见 P2-2（覆盖缺口，非假绿）。
- **测试隔离是否掩盖泄漏**：`_CacheTestCase.setUp` **替换** `_feed_fetch_locks`/`_feed_fetch_refs`（`test_cache.py:50-51`），`RssConditionalGetTests.setUp` **清空**两表（`test_server_http.py:1090-1091`）。结论：**不掩盖本次 F8 主行为**——T71 在**同一用例内**逐次累计并断言归零，采样式泄漏无法藏身；T72 在单次请求后立即断言归零。唯一盲区是"跨用例累计"永不被观测（见 P2-6①），属测试卫生取舍，不改变 F8 结论。

### 要点 5 — 残余风险与规模上界

- **规模上界 = 并发在飞键数，且该值 ≤ 工作线程数**：键存在 ⟺ 引用计数 ≥1 ⟺ 有线程已 acquire 未 release（持有者或等待者）。feed 由 `BoundedThreadPoolServer` 的 `ThreadPoolExecutor(max_workers=MAX_WORKERS=20)` 处理（`config.py:22`），每线程同刻只处理一个请求 ⇒ **生产主端口上界 ≤ 20**，与累计 Host 数无关。`PUBLIC_BASE_URL` 已设时键恒为 5 条 path。**上界结论成立。**
- **`PUBLIC_BASE_URL` 未设时的残余外部资源面**：
  1. **本地生成放大（P2-3）**：每来一个新合法 Host ⇒ `feed_cache` 必 miss ⇒ 一次 `generate_rss`（含 `_feed_etag` 的 sha256，且该 sha256 在 200 路径本就每请求执行）+ 102 键 LRU 抖动。上游请求仍被 URL 级缓存兜住，**不放大上游**；这是 F2 的固有代价、F8 未覆盖，已在 BR-SRV-45 补正 / BR-SRV-50 登记。
  2. **表示隔离正确但自我放大**：伪造 Host 只影响**攻击者自己的响应**（键含 base_url），不再跨读者串号——F2 的 P1-2 修复仍成立。
  3. **`/opml.xml` / `/healthz` 同样取 `_base_url()`**（`server.py:1184,1189-1195`），但均为**非 feed 缓存**：OPML 标 `private + Vary`（未设 `PUBLIC_BASE_URL` 时），healthz `cache=False`。不存在 Host 派生的服务端持久容器 ⇒ **无新的无界资源面**。
- **结论**：F8 之后，默认配置下**无界内存增长面已消除**；唯一残留是"每新 Host 一次本地生成"的**有界 CPU 放大**（P2-3），不构成部署级阻断，但建议以运营约束（设 `PUBLIC_BASE_URL`）收口。

## 五、维度详情（Dim 0–5）

### Dim 0 — 契约一致性

| 修复 | 契约要求（cache.md v1.10 / server.md BR-SRV-50） | 实现事实 | 判定 |
|------|---------------------------------------------------|----------|------|
| F8 | `_get_or_fetch_feed` 只经 `feed_fetch_acquire/release`；server 不 import 锁表；`acquire` 计数先于返回；`release` 归零两表同删；`try…finally` | `server.py:52` 仅 import 两原语；`:1352-1363` 严格 `acquire → try/with → finally release`；`cache.py:994-1021` 逐条符合 | ✅ |
| F8 有界性 | 收敛于并发在飞键数；`PUBLIC_BASE_URL` 已设时 5 键 | 见 §四 要点 5；`SRV-T71` 串行 50 键后归零 | ✅ |
| P2-1 | `.get('last_modified')` 缺省 `None` ⇒ 不发头、禁用 IMS、不抛 `KeyError` | `cache.py:929,970`；`server.py:882-883,1435,1480` 行为一致 | ✅ |
| P2-5 口径 | BR-SRV-46 备注"计数 = 服务端决定返回 304 的次数" | `server.md:864` 已含该备注（落在 **v1.10** 块，非入参所称 v1.11）；`_send_not_modified:1478` 在 `end_headers` 前计数 | ✅ |
| 测试 | `SRV-T71`/`T72`/`T-CACHE-35` 落点 | 均存在（`test_server_http.py:1763-1844`；`test_cache.py:358-444`） | ✅（T71 并发变体缺，P2-2） |

**漂移结论**：代码 ↔ 契约 **0 项行为偏差**；唯一不一致在**文档版本元数据**（P2-1）。

### Dim 1 — 数据与正确性

- 六字段访问器契约在 P2-1 后仍成立：返回 dict 恒含六键（`last_modified`/`fingerprint` 值可为 None）。`test_srv_t60`(`test_cache.py:266-272`) 的精确键集断言保证。✅
- `feed_fetch_release` 的非归零分支只写计数、不触碰锁表；归零分支两表同删。无中间态泄漏。✅
- `ttl` 求值仍在二次 miss 之后（`server.py:1358`），命中路径不读 policy，P2-1(旧轮) 约束保持。✅

### Dim 2 — 并发

- 见 §四 要点 1/2。三层语义（引用计数 → per-key 锁 → `_feed_cache_lock`）职责清晰，无锁序反转：`_feed_fetch_locks_lock` 只在 `acquire`/`release` 内部短暂持有；持有 per-key 锁时只进入 `feed_cache_get_entry/put`（其内部取 `_feed_cache_lock`，单向），不存在反向获取 ⇒ **无环、无死锁**。✅
- `T-CACHE-35②` 以"线程 A 挂起在 `with` 之前、B 拿同锁并阻塞"直接回归 TS-4 原事故面。✅

### Dim 3 — 资源与性能

- **P1-1 内存面闭合**：锁表 ≤ 在飞键数 ≤ 20（见 §四 要点 5）。✅
- **残余 CPU 放大（P2-3）**：未受 F8 约束，已登记。记录，不阻断。
- 新增两次 `_feed_fetch_locks_lock` 获取（acquire/release），仅 miss 路径；命中路径零新增。可忽略。✅

### Dim 4 — 安全

- 无新增注入/越权/敏感面：键为不透明字符串，cache 层不解析 Host；`_FEED_KEY_SEP` 不可能出现在 path/合法 base_url 中 ⇒ 无键碰撞。✅
- F8 消除了"合法 Host 枚举 ⇒ 锁表无界增长直至 OOM"的慢速 DoS 面（原 P1-1）。残余的生成放大为有界成本（P2-3）。✅

### Dim 5 — 结构与可维护性

- 原语封装得当：`server` 不再直接触锁表，生命周期归 cache 层，符合分层与"缓存机制归缓存层"的既有裁决。✅
- `_feed_fetch_refs` 与 `_feed_fetch_locks` 由同一把锁保护，注释明确写出不变式与 TS-4 渊源，可维护性好。✅
- P2-4/P2-5 为可选一致性/微优化建议，非阻塞。

## 六、修复建议

**本轮无 P0/P1，不强制修复。** 建议按优先级：

1. **P2-1（文档，交编排层）**：`cache.md:4` 的"`server.md` → v1.11"与实际 `server.md` v1.10 对齐（升版或改引用），并刷新 `_PROGRESS.md`（cache.md v1.9→v1.10、F8"待落地"→已落地）。这是入参契约基线与实际头部不一致的**可追溯性缺口**，建议闭环。
2. **P2-2（测试）**：补 `SRV-T71` 并发不同 Host 变体，或由编排层裁定该子项降级并在 `server.md §8` 注明。
3. **P2-3（运营/设计）**：部署强制 `PUBLIC_BASE_URL`，或对未知 Host 归一化，收口本地生成放大。
4. P2-4/P2-5/P2-6：可选加固/微优化/测试健壮性，不阻塞。

## 七、评审结论

- **F8 逐条：通过。** 引用计数不变式成立、无新竞态、释放全路径、无计数泄漏、两表恒同步、规模收敛于在飞键数（≤ `MAX_WORKERS`）。
- **P2-1..P2-4：全部真被消化**（P2-2 注入值被消费、P2-3 分叉断言可翻红、P2-4 触达 sweep 顺序、P2-1 语义与契约一致且无头不一致）。
- **P0 = 0；P1 = 0；P2 = 6（全部不阻断）。**
- **结论：✅ 通过，不阻断。** 默认配置下**无界内存增长面已消除**，上一轮"部署级阻断"解除。

### 上一轮 P1-1 闭环判定

| 项 | 判定 |
|----|------|
| **P1-1 闭环** | ✅ **已闭合**（就"`_feed_fetch_locks` 无界增长"这一主缺陷而言） |
| 理由 | ① 不变式 `计数≥1 ⇒ 不可 pop` 由"计数先于返回"保证；② `release` 经 `try/finally` 覆盖成功/双检命中/异常/BaseException 全路径；③ 两表归零同删、无泄漏；④ 归零回收不产生同键双抓（同锁 happens-before + 双检）；⑤ 规模 = 并发在飞键数 ≤ `MAX_WORKERS=20`；⑥ `SRV-T71`/`T72` + `T-CACHE-35` 具备真实证伪能力 |
| 附带说明 | P1-1 当初登记的**第二后果（本地生成放大）**按选定"方案 1"属**未覆盖项**，并非本轮回归——已作为 **P2-3** 单列，建议以运营约束收口 |

### 建议 tester 复跑的变异矩阵（把静态判定升级为实证）

| 变异 | 期望翻红的用例 |
|------|----------------|
| 去掉 `finally` 中的 `feed_fetch_release` | `SRV-T71`（第 1 次后 `len==1`）、`SRV-T72②`、`T-CACHE-35③` |
| `release` 改为"非零也 `pop`"（还原 TS-4） | `T-CACHE-35②`、`SRV-T72①`（`calls` 或 `refs`） |
| `acquire` 把计数 +1 移到 `return lock` 之后（或去掉） | `T-CACHE-35①`/②、`SRV-T72①` |
| `release` 只 `pop` 锁表、不 `pop` 计数表 | `SRV-T71`、`T-CACHE-35①④`（`_feed_fetch_refs` 残留） |
| `cache.py` 回退 `.get('last_modified')` 为直接下标 | `T-CACHE-33`（legacy 分支抛 `KeyError`） |
| `feed_cache_put` 禁用指纹继承 | `test_t55`（`last-modified` ≠ 1970）、`T-CACHE-33`、`SRV-T63/64` |
| `_CACHE_AGE_DOMAINS[path]` 回退 `news_url` | `test_t69`（`_cache_age()==999≠7`）、`SRV-T69`、`CacheAgeTests` |

## 变更记录

| 日期 | 版本 | 说明 |
|------|------|------|
| 2026-09-18 | r1 | 首轮定向复审：F8（锁表引用计数惰性回收）+ P2-1..P2-4。判定 P1-1 **已闭合**、无新增 P0/P1、P2=6。未改动任何代码或其它文档；未实跑测试（环境无 shell），变异结论为静态推演。 |



