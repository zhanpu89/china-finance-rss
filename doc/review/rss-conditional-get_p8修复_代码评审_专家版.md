# RSS 条件请求 P8 修复（F1–F7）代码评审

- **CR 编号**：CR-RSS-20260918-003
- **状态**：评审完成 · ✅ 通过（附 1 项 P1 必修条件）
- **评审模式**：常规评审 + 反假绿专项 + 契约漂移核对（P5b）
- **日期**：2026-09-18
- **关联文档**：`doc/detailed/server.md` v1.9 · `doc/detailed/cache.md` v1.8 · `doc/detailed/metrics.md` v1.4 · `doc/review/rss-conditional-get_对抗性盲审_专家版.md`
- **入参**：未携带 `>>SIDE-EFFECT:` 标记，受影响点由变更面推断（见 §三 末表）
- **取证限制**：本环境无 shell，**未能实际执行** `python -m unittest`；下文所有"证伪/变异"判断均为**静态推演**并已逐条标注。建议编排器安排一次实跑把静态判定升级为实证。

## 一、评审概要

**F1–F7 七项修复全部落地，且与 v1.9 / v1.8 / v1.4 契约逐条对齐**；核心不变式 `ETag 变 ⟺ Last-Modified 前进` 在实现层成立；反假绿抽查中 `SRV-T63/T64/T65/T66/T67/T70`、`T-CACHE-33` 均具备真实证伪能力（§五）。

| 等级 | 数量 | 处理 |
|------|------|------|
| P0 | 0 | — |
| P1 | 1 | **合入生产前必修**（P1-1：`_feed_fetch_locks` 无界增长） |
| P2 | 6 | 记录，不阻断 |

**是否允许进入测试：允许。** 但 P1-1 在 `PUBLIC_BASE_URL` 未设（即 F2 生效路径、也是默认配置）时，是可被外部合法 Host 触发的资源泄漏 + 本地 XML 生成放大，**必须在对外部署前处置**；未处置时应视为**部署级阻断**。

## 二、评审范围

- `china_finance_rss/server.py`：`_CACHE_AGE_DOMAINS`(520-535)、`_feed_ttl_minutes`(790)、`_feed_fingerprint`(800)、`_feed_etag`(816)、`_feed_cache_key`(835)、`_not_modified`(895)、`_get_or_fetch_feed`(1329)、`_serve_feed`(1358)、`_send_not_modified`(1452)
- `china_finance_rss/cache.py`：`feed_cache_get_entry`(906)、`feed_cache_put`(940)
- `china_finance_rss/metrics.py`：`_KNOWN`(20)、`_DEFAULTS`(34)
- `tests/test_server_http.py`：`FeedDoubleCheckTests`(316)、`CacheAgeTests`(392)、`RssConditionalGetTests`(1062)
- `tests/test_cache.py`：`FeedEntryAccessorTests`(253)
- `tests/test_metrics.py`：`MET-T18`(169)

只读核对、未改动：`doc/detailed/**`、`doc/arch/**`、`doc/prd/**`、`API.md`、`README.md`、`china_finance_rss/**`、`tests/**`。

## 三、问题清单

| ID | 等级 | 文件:行 | 问题 | 建议 |
|----|------|---------|------|------|
| P1-1 | P1 | `cache.py:901` + `server.py:1346-1347` | `_feed_fetch_locks` 按 `cache_key` 建锁且**全仓无任何删除/淘汰**；F2 后 `cache_key` 含攻击者可控 Host ⇒ 可无界增长；键数 >100 后 feed_cache 每请求必 LRU 淘汰 ⇒ 每请求回源生成 XML | 锁表有界化（§六） |
| P2-1 | P2 | `cache.py:924` / `cache.py:965` | `last_modified` 用直接下标；六字段契约之外的条目会抛 `KeyError`（经 `_guard` 转降级体，非崩溃） | 改 `.get('last_modified')` 或统一缺省 |
| P2-2 | P2 | `tests/test_server_http.py:1372-1408` | `test_t55` 注入的"过期条目"因已过期必被回源覆盖，对 304 结果无影响；注释宣称的"自造陈旧条目"未被真正消费 | 断言继承值 `last_modified==1.0`，或删误导注释 |
| P2-3 | P2 | `tests/test_server_http.py:1684-1697` | `test_t69` 行为断言今日恒真（两域同为 L3/1.0）；防回归实际来自字面量映射断言；"ttl_factor 分叉"证伪方向未触发 | 增加受控分叉断言 |
| P2-4 | P2 | `tests/test_cache.py:297-309` | `T-CACHE-33` 未触达契约显式要求的"`prev` 先于 sweep 捕获"（第二次 put 时清扫定时器未到期） | 写前 `_last_feed_sweep=0` 强制触发① |
| P2-5 | P2 | `server.py:1469-1470` | `http_304_total` 在 `send_response` 后计数：客户端中途断开可能"计数已发、响应未达"；`send_response` 抛错则漏记 | 语义可接受，建议在 BR-SRV-46 备注该口径 |
| P2-6 | P2 | `doc/detailed/metrics.md:386` | 文档自检称"`metrics.py` 本身仍零代码变更"，与 BR-MET-14（要求在 `_KNOWN`/`_DEFAULTS` 注册）互斥 | 文档同步（不改代码） |

### 受影响点推断（供 tester 定向回归；入参无 `>>SIDE-EFFECT:`）

| 受影响点 | 模块 | 行为变化 / 回归关注 |
|----------|------|---------------------|
| `feed_cache_put` 返回 `None → dict` | cache/server | 唯一消费方 `server._get_or_fetch_feed`；其余调用点忽略返回值 |
| feed 条目 4 → 6 字段 | cache/server | 所有读取点须用 `xml/time/last_modified/fingerprint/last_access/expires_at` |
| feed 缓存键 `path → path+NUL+base_url`（`PUBLIC_BASE_URL` 未设） | server/cache | 命中域收窄到同 Host；`_feed_fetch_locks` 键同步变化 |
| `_CACHE_AGE_DOMAINS` 5 路径 `news_url → feed` | server | 数值不变（两域 L3/1.0）⇒ `Cache-Control: max-age` 逐字不变 |
| `metrics` 注册表 19 → 20 | metrics | `snapshot()` 多一键；精确键集断言须同步 |

## 四、问题详情

### Dim 0 — 契约一致性（逐条核对 v1.9 / v1.8 / v1.4）

| 修复 | 契约要求 | 实现事实 | 判定 |
|------|----------|----------|------|
| F1 | BR-SRV-38 改写：`Last-Modified = entry['last_modified']`；`feed_cache_put` 与同一键**上一条目（即使已过期）**比指纹，相同继承、不同取写入时刻；降级 `None`；`(xml,last_modified)` 2-tuple | `cache.py:954` 在两次清扫**之前**捕获 `prev`；`:963-967` 相同指纹继承 `prev['last_modified']`；`server.py:1343-1356` 读 `entry['last_modified']`；`_guard` rss 分支 `server.py:645-648` 仍 `(error_rss, None)` | ✅ |
| F2 | BR-SRV-45：`PUBLIC_BASE_URL` 设 ⇒ `path`；未设 ⇒ `path + '\x00' + base_url` | `server.py:835-848`；分隔符 `_FEED_KEY_SEP='\x00'`(`:558`)；`_feed_fetch_locks` 用同一键(`:1347`) | ✅（并发/安全副作用见 P1-1） |
| F3 | BR-SRV-46 + BR-MET-14：`_KNOWN`/`_DEFAULTS` 同步注册；`_send_not_modified` 单点计数 | `metrics.py:21,36`；`server.py:1470`；`metrics.py:56` 的 `assert set(_DEFAULTS)==_KNOWN` 通过 | ✅ |
| F4 | BR-SRV-47：5 feed path `news_url → feed`；不变式 `_feed_ttl_minutes()==ceil(max-age/60)` | `server.py:531-533`（恰 5 条）；`_feed_ttl_minutes`(`:790-797`) 读 `feed`；两域均 L3/1.0（`config.py:346-347`）⇒ 数值不变 | ✅ |
| F5 | BR-SRV-48 / BR-CACHE-34：`put` 返回六字段浅拷贝；miss 路径直接消费、删除二次查询 | `cache.py:975-977`（锁内 `dict(...)`）；`server.py:1354-1356`；`server.py` 全仓仅两处 `feed_cache_get_entry`（① + ③ 双检） | ✅ |
| F6 | BR-SRV-49：HTTP/1.0 304 不发 `Content-Length`、EOF 收尾 | `_send_not_modified`(`:1469-1483`) 不写任何 `Content-*`；未改 `protocol_version` | ✅（仅文档化） |
| F7 | SRV-T63..T70 新增、T55 改写、T-CACHE-32 扩六字段 | 见 §五 | ✅（个别用例见 P2-2/3/4） |

**漂移结论：代码 ↔ 契约 0 项偏差。** 未发现任何需要修改契约的代码行为；唯一不一致在文档内部（P2-6）。`server.md` §10.1 的打桩迁移清单（`FeedDoubleCheckTests` 六字段 + `_put(...,fingerprint=)`、`counting_put` 签名、`CacheAgeTests` feed 域、`test_t55` 改写）**实现侧全部完成**，抽查一致。

### Dim 1 — 数据与正确性

- **不变式 `ETag 变 ⟺ Last-Modified 前进`**：`_feed_etag` 复用 `_feed_fingerprint`（`server.py:816-832`），缓存 `fingerprint` 与 ETag 同源；`last_modified` 的推进条件恰为 `prev.fingerprint != fingerprint`（`cache.py:963-967`）⇒ 二者同步。**唯一例外**（`fingerprint=None` / 无上一条目 / 被 sweep 淘汰）已在 BR-CACHE-33 登记为可接受降级，且生产唯一调用方恒传非 `None` 指纹。✅
- **`last_modified` 可能远早于 body `<lastBuildDate>`**：核对仓内全部消费方——`_if_modified_since_not_modified`(`server.py:872-892`) 只做单调 `<=` 比较，语义正确；无任何代码把它当"生成时刻"。BR-SRV-38 已登记该副作用，**不构成缺陷**。✅
- **单一 authority**：`_feed_ttl_minutes` / `_cache_age`(RSS 分支) / `feed_cache_put` 的 TTL 三处同读 `cache_policy('feed')`，无第二个数据源。✅
- **`(xml,last_modified)` 2-tuple 未被破坏**：`_get_or_fetch_feed` 三处 return 均 2-tuple（`:1343-1356`），`_guard` 成功/失败同形状。✅

### Dim 2 — 并发

- **指纹继承读的"上一条目"在锁内**：`prev = feed_cache.get(path)`（`cache.py:954`）位于 `with _feed_cache_lock` 之内，且捕获在两次清扫之前 ⇒ 与写入同一临界区，读-比-写原子。✅
- **双检路径不会写出不一致的 `last_modified`**：`_get_or_fetch_feed` 的 fetch+put 全程持 per-`cache_key` 锁（`server.py:1348-1355`），同一键的并发请求被串行化；即便存在并发 put，`_feed_cache_lock` 仍保证 `prev` 读取与写入互斥。✅
- **F2 与锁键**：锁按含 `base_url` 的 `cache_key` 建，两个 Host 不共享锁、双检不会串用对方表示（`server.py:1346-1347`）——正是 BR-SRV-45 要求的修复。✅ 但键集合无界 ⇒ P1-1。
- **`metrics.incr` 无重复计数**：`_send_not_modified`(`server.py:1470`) 单点、无嵌套锁；异常口径见 P2-5。✅

### Dim 3 — 资源与性能

- **P1-1（本轮唯一真正的新增风险，P1）**：`_feed_fetch_locks`（`cache.py:901`）以 `cache_key` 为键 `setdefault` 建 `Lock`（`server.py:1347`），**全仓无任何 `pop`/淘汰**（`grep` 仅命中定义 + setdefault）。历史评审 `系统_代码评审报告_001.md` TS-4 曾因"`pop` 与持锁线程竞态 ⇒ 双抓"**主动移除** pop（`doc/review/系统_代码评审报告_001.md:44,155`），因此当前"只增不减"是既有取舍。**但 F2 把键空间从 5 条固定 path 变成"path × 请求派生 base_url"**：`_valid_host_header`（`server.py:591-598`）只校验**格式**、不校验归属，任意合法主机名（≤253 字符）都能生成新键。后果：
  1. **永久内存增长**：每键约 300–450 B（Lock + 键串 + 字典槽），外部可无界增长，直至 OOM（2C2G 节点尤甚）；
  2. **本地生成放大**：键数一旦超过 `feed_cache` 上限 100，每来一个新 Host 必 miss，触发一次 `generate_rss` + sha256，LRU 持续抖动。
  BR-SRV-45 的"放大风险论证"只覆盖了**上游请求**（确被 URL 级缓存兜住），**未覆盖锁表内存与本地 XML 生成**；其"不能靠畸形 Host 枚举"只对**非法** Host 成立，**合法 Host 仍可枚举**（`a1.example`、`a2.example` …）。
- **`cache_entries`(label `feed`)** 取 `len(feed_cache)`，受 `cache_max=100` 约束，**指标不失真**，但无法反映键空间真实规模（键数可远超 100）。这属观测盲区，非失真。
- `feed_cache_put` 锁内 `dict(feed_cache[path])` 为 O(1) 浅拷贝（值均不可变：str/float/None），无性能回退；`_serve_feed` 每请求对 xml 做一次 sha256（~37KB 级），与 v1.8 相同，无新增量级。✅

### Dim 4 — 安全

- F2 **修复了**原 P1-2（一条伪造 Host 改写全体读者 `<atom:link>` / 头与行为不符）。✅
- 残余：**合法 Host 枚举 ⇒ 锁表无界增长 + 每请求 XML 生成**（慢速 DoS，P1-1）；`_valid_host_header` 的长度上限只限制了单键长度，未限制键数量。
- 无新增注入/越权/敏感信息面：键是不透明字符串，cache 层不解释 Host（BR-SRV-45）；`_FEED_KEY_SEP` 不可能出现在 path（路由为固定 5 值）或合法 base_url（校验禁 NUL/CR/LF）中，**无键碰撞**。✅

### Dim 5 — 结构与可维护性

- `_feed_etag` 复用 `_feed_fingerprint`，**消除了"两份规范化投影可能漂移"的结构风险**（ETag 与缓存指纹恒同源）。✅
- `_send_text` 与 `_send_not_modified` 各写一份 `Cache-Control`/`Vary`：`server.md` §10#36 已如实登记为"实现现状"，`SRV-T62` 为兜底断言。**非本轮引入**，维持 P2 记录，不新增。
- 六字段字面量在 `cache.py` 出现 3 处（get_entry / put / put 返回值），字段少且邻近，未抽公共构造器可接受。

## 五、反假绿审查（本轮重点）

> 无 shell，未实跑。判断方式：逐行推演"删掉/回退被测代码后，该断言是否变红"。文末给出建议的变异矩阵供实证复跑。

| 用例 | 能否证伪 | 理由（红/绿方向） |
|------|----------|-------------------|
| `SRV-T63` IMS 跨 TTL 仍 304（`:1542`） | **能（决定性）** | 受控时钟 `_FixedClock` 固定 `cache_mod.time.time`；手工 `expires_at=clock.now-1` 使条目必 miss；`clock.now += 3600` 跨整 TTL；第二次**仅带 IMS**。若禁用指纹继承 ⇒ `last_modified=clock.now=lm1+3600` ⇒ `int(lm_new)>int(IMS)` ⇒ **200**，`assertEqual(st2,304)` 必红。`assertLess(lm1, clock.now)` 另证时钟确实前进，排除"同秒伪绿"。 |
| `SRV-T64` 指纹继承/变更两向（`:1568`） | **能** | 继承向：同指纹跨过期写 ⇒ `e2.lm==e1.lm`（`sleep(0.01)` 保证"未继承时必不等"⇒ 红）；变更向：`e3.lm>e1.lm` 且 ETag 必变 + 端到端旧 INM ⇒ 200 且体含 `CHANGED`。方向齐备。 |
| `SRV-T65` 跨 Host 键隔离（`:1611`） | **能** | 键退回 `path` 时 `assertNotEqual(key_a,key_b)` 先红；即使只回退 `_feed_cache_key` 而请求两 Host，第二请求将命中第一条目、`assertNotIn(b'a.example', body_b)` 红。`assertIn(key_a/key_b, feed_cache)` 验证"不 clear 也隔离"。 |
| `SRV-T66` `http_304_total`（`:1637`） | **能** | 断言 200 后为 0（200 不计数）、304 后为 1；去掉 `incr` ⇒ `0 != 1` 红；`reset()` 保证隔离。 |
| `SRV-T67` 304 头集合白名单（`:1651`） | **能（部分）** | 头集合**恰等于** `{etag,last-modified,cache-control,vary,server,date}`，任何多/少一头即红 → 对 `_send_not_modified` 的首个直接覆盖。**"无 body"断言无牙齿**：`http.client` 对 304 一律不读 body，`body==b''` 恒真；真正兜底 F6 的是"无 `Content-Length`"这一断言。 |
| `SRV-T69` `_feed_ttl_minutes()` ↔ max-age（`:1684`） | **能（弱）** | 防回归实际来自 `assertEqual(_CACHE_AGE_DOMAINS[path],'feed')` 这一**字面量**断言；`_cache_age()==real_ttl` 今日恒真（两域同为 L3/1.0），标称的"两域 ttl_factor 分叉"方向未触发（第二段把 `cache_policy` 整体打桩）。 |
| `SRV-T70` `put` 返回值 / 无二次查询（`:1699`） | **能** | `get_calls==2`；put 后若仍查一次 ⇒ 3 ⇒ 红；若 `feed_cache_put` 返回 `None` ⇒ 六字段断言 / `entry['last_modified']` 报错 ⇒ 红。 |
| `T-CACHE-33` 指纹跨过期继承（`test_cache.py:297`） | **能** | "只在新鲜条目上比较"的实现 ⇒ 第二次 put 不继承 ⇒ `written.lm != first.lm`（真实时钟前进）⇒ 红。**但**契约显式要求的"`prev` 先于 sweep 捕获"**未被触达**（第二次 put 时 `now-_last_feed_sweep<60` 且容量未满，清扫不触发）⇒ 覆盖缺口 P2-4。 |
| `test_t55`（`:1372`） | **部分伪绿** | 注入条目 `expires_at=now-1` ⇒ 必 miss 并回源重生成；注入对 304 结果无影响，`last_modified=1.0` 的继承也未被断言。头契约断言（private/public + Vary）仍真实有效 ⇒ 记录为 P2-2。 |
| `SRV-T46/T47` `counting_put` | **通过** | 已按 §10.1 迁移：签名含 `fingerprint=None` 并原样转交（`:1134-1136`、`:1153-1155`），否则 `TypeError`。 |
| `FeedDoubleCheckTests` 桩 | **通过** | 桩条目六字段、`_put` 接受并返回条目（`:328-338`），无 4 字段残留 → `_get_or_fetch_feed` 读 `entry['last_modified']` 不报错。 |

**开发者自称变异的抽查（静态判定）**：`禁用继承 ⇒ 200 != 304`（T63/T64 命中）、`键退回 path ⇒ Host 串号`（T65 命中）、`去掉 incr ⇒ 0 != 1`（T66 命中）——三条断言的逻辑**确能翻红**，抽查**通过**；但**未经实际执行**，以上为静态判定而非实证。

## 六、修复建议

**P1-1（必修，对外部署前）—— `_feed_fetch_locks` 有界化。** 注意：**不能简单重加 `pop`**（TS-4 已证其与持锁线程竞态、会导致同一键双抓）。三选一：
1. **引用计数 / 惰性回收（推荐）**：`_get_or_fetch_feed` 在锁内递增键引用、`finally` 递减，归零即 `pop`，使锁表随并发收敛，不引入新上限常量；
2. **容量上限 + LRU**：仿 `feed_cache` 给锁表设 `cache_max` 与淘汰（淘汰前确保无等待者）；
3. **退路**：不修则**强制部署侧设置 `PUBLIC_BASE_URL`**（此时键 = `path`，锁表退化为有界 5 键），并在 README / 启动日志显式告警该前提。
修复后补一条：并发 N 个不同 Host 后断言 `len(_feed_fetch_locks)` 收敛（或 ≤ 上限）。

**P2-1**：`cache.py:924` / `:965` 改 `.get('last_modified')`（缺省 `None` / `now`），使访问器与非六字段条目 fail-safe（当前经 `_guard` 产降级体，非崩溃）。
**P2-2 / P2-3 / P2-4**：按问题清单补强用例——`t55` 断言继承值、`t69` 增加两域分叉的受控断言、`T-CACHE-33` 在第二次 put 前把 `_last_feed_sweep=0` 强制触发①清扫（覆盖契约显式顺序要求）。
**P2-5**：把"进入 `_send_not_modified` 即计数（含极少数未能送达的 304）"写入 BR-SRV-46 备注。
**P2-6**：`metrics.md:386` 自检句与 BR-MET-14 矛盾，交编排层文档同步（代码无须改）。

**改进优先级**：P1-1 → P2-4（契约显式要求的覆盖缺口）→ P2-2/P2-3 → 其余。

### 建议 tester 复跑的变异矩阵（把静态判定升级为实证）

| 变异 | 期望翻红的用例 |
|------|----------------|
| `feed_cache_put` 恒 `last_modified=now`（禁用继承） | `SRV-T63`→200、`SRV-T64`、`T-CACHE-33`、`SRV-T52b_end_to_end` 亦可能变红 |
| `_feed_cache_key` 恒返回 `path` | `SRV-T65`、`SRV-T55` |
| 删除 `feed_cache_put` 返回值 / 恢复 put 后二次查询 | `SRV-T70`、`SRV-T60`、`FeedDoubleCheckTests` |
| 删除 `_send_not_modified` 的 `incr` | `SRV-T66`、`MET-T18`（部分） |
| `_CACHE_AGE_DOMAINS` 5 条回退 `news_url` | `CacheAgeTests::test_rss_paths_use_feed_domain`、`SRV-T69`、`SRV-T11` |

## 七、评审结论

- **F1–F7 逐项：全部通过**（契约一致、实现正确、核心不变式成立、测试具备证伪能力）。
- **P0 = 0；P1 = 1；P2 = 6。**
- **结论：✅ 通过，不阻断本轮 F1–F7 的验收。** 但 **P1-1（`_feed_fetch_locks` 无界增长）是 F2 新引入、可被外部合法 Host 触发的资源泄漏 + 本地生成放大面**，在 `PUBLIC_BASE_URL` 未设（默认配置）时构成**部署级阻断**；须在对外部署前按 §六 处置或明确以"强制设 `PUBLIC_BASE_URL`"作运营约束。
- 允许进入测试阶段；建议 tester 按 §三 受影响点做定向回归，并按 §六 变异矩阵复跑，补上 P2-4 的清扫顺序覆盖。

## 变更记录

| 日期 | 版本 | 说明 |
|------|------|------|
| 2026-09-18 | r1 | 首轮：P8 修复 F1–F7 常规评审 + 反假绿专项 + 契约核对。未改动 `china_finance_rss/`、`tests/`、`doc/detailed/`、`doc/arch/`、`doc/prd/`、`API.md`、`README.md` 或任何契约文档。未实跑测试（环境无 shell），变异结论为静态推演。 |

