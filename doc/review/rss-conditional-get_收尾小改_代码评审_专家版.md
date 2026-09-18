# RSS 条件请求「收尾小改」定向复审（读侧 fail-safe / acquire 微优化 / F8 并发变体测试）

- **CR 编号**：CR-RSS-20260918-005
- **状态**：定向复审完成 · ✅ 通过（无 P0 / 无 P1）
- **评审模式**：P5b 定向复审（增量）+ 反假绿抽查 + 契约核对
- **日期**：2026-09-18
- **复审范围**：仅本轮收尾小改（`cache.py` 读侧 fail-safe + `feed_fetch_acquire` 先判空；`tests/test_cache.py` T-CACHE-36；`tests/test_server_http.py` SRV-T73；`cache.md` v1.11 / `server.md` v1.12）。**已通过的 F1–F8 不重评。**
- **关联文档**：`doc/detailed/cache.md` v1.11 · `doc/detailed/server.md` v1.12 · `doc/detailed/_PROGRESS.md`
- **入参**：未携带 `>>SIDE-EFFECT:` 标记；受影响点由变更面推断（见 §六）。
- **取证限制**：本环境无 shell，**未能实跑** `python -m unittest`。下文"能否翻红"均为**静态推演**并逐条标注；建议编排器补一次实跑把判定升级为实证。

## 一、评审概要

**本轮三处收尾改动（读侧 fail-safe 边界、`acquire` 命中路径零分配、F8 并发变体测试）实现与契约一致，未引入新的正确性/并发缺陷。** 七条复审要点中，2 条（`feed_cache_get` 直接下标不变量、`acquire` get-then-create 原子性）逐路径核对**成立**；其余为"边界语义未写死 / 观测缺失 / 契约证伪方向表述过强 / 极端调度下的测试健壮性"，均 P2 记录，不阻断。

| 等级 | 数量 | 处理 |
|------|------|------|
| P0 | 0 | — |
| P1 | 0 | — |
| P2 | 6 | 记录，不阻断 |

**是否阻断：不阻断。** 结论：✅ **允许进入测试/合入**。

## 二、评审范围

- `china_finance_rss/cache.py`：`feed_cache_get_entry`(911-954)、`feed_cache_get`(957-966)、`feed_fetch_acquire`(1018-1037)、`feed_fetch_release`(1040-1053)
- `china_finance_rss/server.py`：`_get_or_fetch_feed`(1329-1364)、import 面(51-54)
- `tests/test_cache.py`：`FeedEntryAccessorTests.test_t_cache_36_read_side_fail_safe`(357-406)、`FeedFetchLockTests`(409-495)
- `tests/test_server_http.py`：`RssConditionalGetTests.setUp`(1088-1094)、`test_t71`(1763-1784)、`test_t72`(1786-1844)、`test_t73`(1846-1909)
- 契约核对：`cache.md` v1.11（§2.4(182) / BR-CACHE-32(484) / BR-CACHE-35(487) / T-CACHE-36(1106) / §10#28(1168)）· `server.md` v1.12（BR-SRV-50(870) / SRV-T73(2004) / §10#45(2110)）· `_PROGRESS.md`

只读核对，未改动任何代码或其它文档（本报告除外）。

## 三、问题清单（P2 记录项）

| ID | 等级 | 文件:行 | 触发条件 → 后果（证据链） | 建议 |
|----|------|---------|--------------------------|------|
| P2-1 | P2 | `cache.py:944-947`；契约 `cache.md:182,484`；测试 `test_cache.py:357-406` | **缺 `xml` 判据只写死"缺字段/None"，未写死空串 `''`**。当条目（或未来某 producer）持有 `xml=''`，实现按 `is None` **当作命中照常服务**（本审认为正确，见 §四 要点1）；若后人把 `xml is None` "化简"为 `not xml`，`''` 即变 miss，而写侧 `feed_cache_put` 仍会再写 `''` ⇒ **该键每次读都 miss、反复回源**（缓存自我击穿）。同类未写死点：写侧对 `xml=None` 无校验，producer 返回 None 时 `feed_cache_put` 照写 ⇒ 读侧恒 miss ⇒ 同上 | ①§2.4/BR-CACHE-32 明写"`xml=''` 属**合法但空**、读侧**照常命中**"；②`T-CACHE-36` 增 ④ 断言 `xml=''` 返回**非 None**；③可选：写侧对 `None` 体显式判失败，避免"写 None ⇒ 永久 miss" |
| P2-2 | P2 | `cache.py:938-947` | **读侧 fail-safe 静默降级、无可观测信号**。某契约变更/重构令大批条目缺 `xml` 时，"残缺 ⇒ 视同 miss"表现为"每键多一次回源"；feed 链路**无 `upstream_fetch_total` 计数**（该计数只在 stock/market 域），仅间接体现为 `cache_hit_ratio` 下降 ⇒ 运维难辨"上游故障"与"本地条目残缺" | 三个 `return None` 分支加 `log.warning`（`[feed_cache] malformed entry %r`），使二者可区分。**属设计选择的可观测性缺口，非新缺陷**（§四 要点2） |
| P2-3 | P2 | `cache.py:942,954`；`test_server_http.py:1562,1565` | **"缺 `expires_at` ⇒ 恒过期"依赖 `time.time() >= 0`**（缺省 0 ⇒ `now >= 0` 恒真）。同一假设也是 :954 `entry['expires_at']` **直接下标安全**的前提：时钟取负时，缺 `expires_at` 的条目会**反转成命中**并在 :954 抛 `KeyError`（经 `_guard` 变降级体）。生产时钟恒非负、测试 `_FixedClock(time.time())` 起点为正 ⇒ **不可达** | 契约注明隐含前提（`time.time() >= 0`），或 :954 也改 `.get`。**非缺陷**（§四 要点3） |
| P2-4 | P2 | `server.md:4`；`_PROGRESS.md:32` | **契约对 `SRV-T73` 的证伪方向表述过强**：称"若 `release` 不在 `finally` … ⇒ 红"。但 T73 取数桩**从不抛异常**，T73 **无法**区分 `finally` 与 `with` 后裸 `release`——该变异由 T72 异常路径捕获。T73 实际可证伪的是：①按累计增长、②两表不同步回收、③上界 > K | 收窄 `SRV-T73` 证伪描述（"release 不在 finally"归回 `SRV-T72`），避免后人据此放松 T72 |
| P2-5 | P2 | `test_server_http.py:1871,1891,1901-1902` | **T73 固定 5.0s 超时在极端调度延迟下有伪红风险**：`release.wait(5.0)`/`join(5.0)` 在重载 CI 上超时，线程可能越过放行点提前 release，使在飞快照断言（`== K`）或收尾归零断言失败。正常环境因断言紧随事件置位、耗时远小于 5s，**不 flaky** | 可选加固：超时改 10–15s，或收尾断言前断言 `not t.is_alive()` |
| P2-6 | P2 | `cache.py:937-954` | **读侧 fail-safe 作用域仅"映射形态条目"**：只覆盖缺键/None 值；真值**非映射**条目（如注入 `feed_cache[k]=5`）在 `entry.get` 抛 `AttributeError`（非 `KeyError`）→ `_guard` 降级体。`feed_cache_put` 只写 dict、生产不可达 | 可选：访问器首行加 `isinstance(entry, dict)` 守卫，或在契约中显式限定 fail-safe 仅覆盖映射条目 |

## 四、复审要点逐条判定

### 要点 1 — fail-safe 边界：`is None` 判据与空串 `''` 语义

**判定：实现正确且更安全；边界未写死属 P2-1。**

- **判据等价性**：`xml = entry.get('xml'); if xml is None: return None`（`cache.py:944-947`）等价于 `'xml' not in entry or entry['xml'] is None`。与契约 `cache.md:182,484` 的"**缺字段（或 `None`）⇒ 视同 miss**"逐字一致。
- **`''` 应视为命中（served），当前实现正是如此**。理由（证据链）：
  1. `''` 是**结构完整**的条目（键存在、值为字符串）；fail-safe 的目标是"结构残缺"，不是"内容为空"。
  2. 读侧**无法**区分"合法空表示"与"截断体"——两者都是字符串。因此"拒绝残缺体"本质上不可能在读侧实现，只能在写侧/producer 侧校验。
  3. 若把 `''` 判为 miss：读 miss ⇒ 回源 ⇒ producer 仍返回 `''` ⇒ `feed_cache_put` 再写 `''` ⇒ 下次仍 miss，**形成对该键的永久回源环**（缓存自我击穿），把"内容问题"放大成"上游负载问题"。
- **"`''` 与 `None` 等同是否会造成永远 miss"**：**不会**——实现用 `is None`，**没有**把 `''` 与 `None` 等同。该隐患只在"被化简为 `not xml`"时才出现；当前无此写法。
- 残留（P2-1）：契约与注释均未陈述 `''` 语义，`T-CACHE-36` 也只覆盖缺键/`None`，未覆盖 `''`；建议补文档 + 一条 `xml=''` 仍命中的断言把边界钉死。另：写侧对 `xml=None` 无校验（producer 返回 None 会恒 miss），建议写侧补防御。

### 要点 2 — "`xml` 缺失 ⇒ miss"是否掩盖真实故障

**判定：属设计选择，非新缺陷；观测缺口记 P2-2。**

- **生产不可达**：`feed_cache` 的唯一写入方 `feed_cache_put(path, xml, ttl, …)`（`cache.py:969-1006`）把 `xml` 作位置参**恒写入**，故"生产条目缺 `xml`"只能来自注入/legacy/未来重构——**正是 fail-safe 要覆盖的畸形输入**。
- **有界，不会量级放大上游**：命中该分支 → 回源一次 → `_get_or_fetch_feed` 用 `feed_cache_put` 的返回值（`server.py:1360-1361`）**立刻修复同键条目**；下次读即命中。故每个"残缺事件"至多多一次回源，不构成持续风暴（除非写侧反复写残缺体，见 P2-1 的 `None` 情形）。
- **语义优于旧行为**：改动前访问器直接 `entry['xml']`，缺失即 `KeyError` → 被 `_guard` 吞成"上游失败"降级 RSS（不区分"条目残缺"与"上游故障"）。改动后降级为一次正常回源，**更准确**。
- **可观测性缺口（P2-2）**：该分支无 `log.warning`；feed 链路无 `upstream_fetch_total`（该计数仅在 `stock_api`/`market_api` 域）。若未来大面积条目残缺，唯一症状是回源次数上升，运维难以定位。建议加 warning（metric 名需契约变更，暂不建议）。

### 要点 3 — `expires_at` 缺省 0 的推理链

**判定：推理链成立，当前不可反转；隐含假设记 P2-3。**

- `now = time.time()`；`entry.get('expires_at', 0)` 缺省得 `0`；判定 `now >= 0`。对任何**真实时钟**，epoch 秒恒 `>= 0` ⇒ 恒真 ⇒ 自然判为过期（miss）。✅ 实现与注释（`cache.py:941`）一致。
- **反转条件只有一个：时钟被打桩为负值**。检索全测试：`cache_mod.time.time` 仅被 `test_server_http.py:1565` 以 `_FixedClock(time.time())` 打桩，**起点为正**；`_StepClock` 起点 `1_700_000_000` 且只打桩 `srv.time`，不影响 `cache.time`。故**无任何边角使其反转为命中**。
- 需注意：同一"非负时钟"假设也是 `entry['expires_at']` 直接下标（`:954`）安全的前提——越过 gating 的条目其 `expires_at` 必存在。契约未明写该前提，建议补注（P2-3）；若想彻底去耦，可把 :954 也改 `.get`。

### 要点 4 — `feed_cache_get` 直接下标不变量是否真被访问器保证

**判定：不变量成立，无 P0/P1。**

逐返回路径枚举 `feed_cache_get_entry`（`cache.py:937-954`）：

| 路径 | 条件 | 返回 | 是否含非 None `xml` |
|------|------|------|----------------------|
| ① 空条目 | `not entry`（`None`/空 dict） | `None` | — |
| ② 过期 | `time.time() >= entry.get('expires_at', 0)` | `None` | — |
| ③ 缺体 | `entry.get('xml') is None` | `None` | — |
| ④ 命中 | 其余 | dict | **是**（③ 已排除 None；`''` 亦非 None） |

`feed_cache_get`（`:957-966`）只把 ④ 的 dict 作 `entry['xml']`，**不可能**取到 None 或 `KeyError`。访问器是 `feed_cache_get` 的唯一数据来源，故注释所依赖的"命中必有 `xml`"不变量**成立**。✅

> 交叉核对：唯一能绕过该不变量的方式是外部直接注入 dict 到 `feed_cache`（测试这么做），但仍经同一访问器。`server._get_or_fetch_feed` 也只经访问器读。无旁路。

### 要点 5 — `acquire` 的 get-then-create 是否原子、命中路径是否零分配

**判定：原子；命中路径零分配达成。**

```python
with _feed_fetch_locks_lock:          # cache.py:1031
    lock = _feed_fetch_locks.get(key) # :1032 判空
    if lock is None:                  # :1033
        lock = threading.Lock()       # :1034 仅未命中构造
        _feed_fetch_locks[key] = lock # :1035
    _feed_fetch_refs[key] = _feed_fetch_refs.get(key, 0) + 1  # :1036
    return lock                       # :1037
```

- **无检查-创建竞态**：`get`、`Lock()`、写表、计数 +1、`return` **全部在 `_feed_fetch_locks_lock` 临界区内**，与 `feed_fetch_release`（`:1047` 同锁）互斥。两个并发首次调用串行化：后到者 `get` 命中先到者刚写入的锁，得**同一把**锁对象。
- **命中路径零分配**：命中时 `:1034` 的 `threading.Lock()` **不被求值**（`if lock is None` 为假），无残留 `setdefault`（原 `setdefault(key, threading.Lock())` 会在每次调用先构造丢弃的锁）。计数使用小整数（CPython 小整数缓存），无可感分配。
- **语义不变**：计数先于返回（覆盖"已取锁未进 `with`"窗口）、锁身份、临界区范围与 v1.10 逐字一致。✅

### 要点 6 — `SRV-T73` 是否真能证伪且不 flaky

**判定：真能证伪（3 类变异），但契约宣称的第 4 类证伪不成立（P2-4）；固定超时属轻微健壮性备注（P2-5）。**

- **"K 个键确实同时在飞"成立**：每个 worker 的时序为 `feed_cache_get_entry` miss → `feed_fetch_acquire(key)`（建锁 + 计数 +1）→ `with lock` → 二次 miss → `fetch()`。K 个 worker 在 `fetch()` 内 park（`release.wait(5.0)`），而**放行事件 `release` 只在主线程断言之后才置位**（`test_server_http.py:1899-1900`）⇒ 采样瞬间 K 个键的锁/计数**必然全部在位**，不存在"先到的先做完"。K 个 Host 经 `_feed_cache_key` 映射为 K 个互异键（`:1879` 断言）。
- **断言非空转、上界有证伪力**：`1 <= len(locks) <= K`（`:1894-1895`）单独看上界偏松，但**紧随其后的 `len(refs) == len(locks)`（`:1896-1897`）与 `len(refs) == K`（`:1898`）**把上界钉死为 K；三者联合既排除"按累计增长"（> K），又排除"两表不同步"（len 不等），还排除"双抓导致键数 < K"（refs 键数不足 K）。
- **收尾归零断言强**：`release.set()` 后 join 全部线程，断言两表**均**为 0（`:1908-1909`）⇒ 若 `release` 未在**任何**路径执行、或归零只 `pop` 一张表，必红。✅
- **证伪边界（P2-4）**：T73 的取数桩**从不抛异常**，因此它**无法**证伪"`release` 不在 `finally`"——成功路径上"`with` 后裸 `release`"与"`finally release`"行为相同。该变异由 **T72 的异常路径**（`test_t72_exception_path_reclaims_key`，`:1828-1844`）捕获。`server.md:4` / `_PROGRESS.md:32` 把该证伪力记在 T73 名下，**表述过强**，建议收窄（否则后人可能以为 T72 冗余）。
- **flaky 评估（P2-5）**：主流程 `entered.wait(5.0)` 后立即采样，耗时远小于 5s，正常不 flaky。极端重载下若 `release.wait(5.0)` 超时先于断言，线程会提前 release，导致在飞/收尾断言伪红。可选把超时抬到 10–15s。

### 要点 7 — `T-CACHE-36` 的对比性（①/③ 行为差异是否真被断言区分）

**判定：对比性成立，合并实现必红；缺 `''` 分支记 P2-1。**

- ① 缺 `xml`（`:365-373`，含 `'xml'` 缺键与 `xml=None` 两种形态）断言 `feed_cache_get_entry` **与** `feed_cache_get` 均 `is None`。
- ③ 四字段 legacy、**有 `xml`**（`:388-397`）断言 `feed_cache_get_entry` **非 None**、`xml=='<l/>'`、`last_modified is None`、`fingerprint is None`，且 `feed_cache_get=='<l/>'`。
- **合并即红**：若实现把 ③ 也当 miss（合并到 ①），`assertIsNotNone(legacy)` 红；若把 ① 当"服务但降级"（返回 dict），`assertIsNone` 红。二者行为被**分别**钉死，对比性有效。✅
- 另覆盖 ② 缺 `expires_at` ⇒ miss（`:377-381`）与"缺 `time` 仍可服务"（`:400-406`），均为有效负例/正例。
- 缺口（P2-1）：未覆盖 `xml=''`——这正是 `is None` 与 `not xml` 两种实现会分叉的唯一边界。

## 五、维度详情（Dim 0–5）

### Dim 0 — 契约一致性

| 变更 | 契约要求 | 实现事实 | 判定 |
|------|----------|----------|------|
| 读侧缺 `xml` ⇒ miss | `cache.md` v1.11 §2.4/BR-CACHE-32：缺字段或 `None` ⇒ 返回 `None`，不抛 | `cache.py:944-947` | ✅（`''` 未定义，P2-1） |
| `time` 以 `.get` 读 | 缺省 `None` | `cache.py:950` | ✅ |
| `expires_at` 沿用 `.get(...,0)` | 缺省 0 ⇒ 自然过期 | `cache.py:942` | ✅ |
| `last_access` 直接下标 | 访问器自写、恒存在 | `cache.py:949,953` | ✅（要点4 已证） |
| `feed_cache_get` 直接 `entry['xml']` | 不变量：命中必有非 None `xml` | `cache.py:966` | ✅ |
| `acquire` 先 `get` 判空 | `cache.md` BR-CACHE-35 / `server.md` BR-SRV-50 v1.11/v1.12 实现约束 | `cache.py:1031-1037` | ✅ |
| T-CACHE-36 / SRV-T73 落点 | 见 `cache.md:1106` / `server.md:2004` | `test_cache.py:357-406` / `test_server_http.py:1846-1909` | ✅（T73 证伪描述过强，P2-4） |

**漂移结论**：代码 ↔ 契约 **0 项行为偏差**；不一致仅在契约的证伪描述措辞（P2-4）。

### Dim 1 — 数据与正确性

- 命中/未命中三态（`''` 命中、`None` miss、缺键 miss）与契约字面一致；无隐式状态转换。✅ 反模式命中：无。
- 读数 `.get`/直接下标混用有明确不变式支撑（要点1/3/4），非"随手不一致"。✅

### Dim 2 — 并发

- `acquire`/`release` 全在 `_feed_fetch_locks_lock` 内，无检查-创建竞态、无"非原子读改写"（要点5）。✅
- `_feed_fetch_refs` 与 `_feed_fetch_locks` 同锁、成对增删，两表恒同步。✅
- T73 为并发在飞场景提供回归网。✅ 反模式命中：无。

### Dim 3 — 资源与性能

- 命中路径零 `Lock` 分配，消除每次 feed 读取的无谓对象构造（要点5）。✅ 正面改进。
- 读侧 fail-safe 至多多一次回源/键，无"缓存击穿"复发；唯 `xml=None` 写入（不可达）理论上有永久 miss 风险（P2-1）。✅

### Dim 4 — 安全

- 无新增外部输入面；本次不触碰 Host 解析/键构造。无注入/越权/敏感信息。✅

### Dim 5 — 结构与可维护性

- fail-safe 注释含"为什么"（区分 `_guard` 降级语义），符合本仓风格。✅
- 唯一可维护性风险：边界语义（`''`）靠注释隐含，易被后人"化简"（P2-1）。

## 六、受影响点推断（供 tester 定向回归；入参无 `>>SIDE-EFFECT:`）

| 受影响点 | 模块 | 行为变化 / 回归关注 |
|----------|------|---------------------|
| `feed_cache_get_entry` 缺 `xml`/`expires_at` | cache | 所有经该访问器的读（feed 路由 5 条 + `/healthz` 探活）；畸形条目由"抛错降级"变"回源修复" |
| `feed_cache_get` 直接下标 | cache | 依赖第 ④ 路径不变量；任何新增返回路径必须保持 `xml` 非 None |
| `feed_fetch_acquire` get-then-create | cache | 所有 feed miss 的加锁；仅分配行为变化，身份/计数/锁序不变 |
| T73 新增并发变体 | tests | 锁表两表同步、按在飞键数有界、归零 |
| T-CACHE-36 新增负例 | tests | 畸形条目读侧 fail-safe |

## 七、评审结论

- **P0：0；P1：0；P2：6。**
- **是否阻断：不阻断。** ✅ 允许进入测试/合入。
- 建议编排器：① 安排一次 `python -m unittest discover -s tests` 实跑，把 T-CACHE-36 / SRV-T73 的"能否翻红"从静态推演升级为实证；② 把 P2-1（补 `''` 边界文档+用例）、P2-2（fail-safe 加 `log.warning`）、P2-4（收窄 T73 证伪描述）列入下一轮小改；③ 落地 `>>DOC_SYNC:`（若采纳 P2-1/P2-3/P2-4 的契约措辞调整）。

## 变更记录

| 版本 | 日期 | 说明 |
|------|------|------|
| v1.0 | 2026-09-18 | 首次定向复审：读侧 fail-safe / acquire 微优化 / F8 并发变体测试 + T-CACHE-36；结论 ✅ 通过（0 P0 / 0 P1 / 6 P2） |

