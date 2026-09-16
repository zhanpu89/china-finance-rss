# config.py 详细设计

> **版本** v1.3 · **状态** 已契约同步（P7b + AC-S3 裁决回写：以 `china_finance_rss/config.py` / `cache.py` 实现为准）· **日期** 2026-09-16 · **作者/产出** task-decomposer
> **v1.3 变更（AC-S3 裁决 · 收尾契约同步）**：① `PROBE_TIMEOUT` 脚注更正——**阶梯封顶不再是 `REQUEST_TIMEOUT`**：`cache._probe_budget` 以 `cache._PROBE_BUDGET_CAP=5.0` 封顶（序列 `2→4→5`），`REQUEST_TIMEOUT(10s)` 仅用于"无失败历史 / 已老化"两支的全预算探测（§2.3 注 + §10#18）。**`PROBE_TIMEOUT` 默认值 2 不变**（仍是阶梯首级）。
> 本版修订（P7b 契约同步，**只改文档、不改代码**）：① 新增 §2.6 **`canonical_code(code)`（冻结接口）**——股票代码归一的唯一权威（`strip + lower + 点号形映射`）；② `_is_trading_hours` 支持**休市日**（env `TRADING_HOLIDAYS`，默认空）；③ 新增 env `LISTEN_BACKLOG(128)` / `TRADING_HOLIDAYS('')` / `CDP_RESTART_THROTTLE(15)`；④ `DOMAIN_MATRIX.cache_max` 语义钉死为**终态/feed 缓存上限**，URL-cache-only 域（`plate`/`margin`/`news_url`/`longhu`）一律 `'n/a'`→`None`；⑤ §2.4 删除清单**已全部落地**（实现态），`VALID_STOCK_CODE` 保留但仅由 `canonical_code` 内部消费（`utils.py` 死 import 已删）。
> 沿用 v1.1：REV-DES-04/06/07/08 + 逆向建议 2（删常量前置条件）+ 编排层裁决 #1/#2/#6 + 偏差 D-4/D-5 登记
> 模块路径 `china_finance_rss/config.py` · 归属 **基础层（Layer 0）**
> 上游 SAD `doc/arch/SAD.md` v1.2（§2.1 / §2.3 D-1 D-5 / §2.6 / §3 config.py 行 / ADR-001）
> 上游 PRD `doc/prd/perf-stability-optimization.md` v0.3（AC-A3/A4/E6/E9/S3/S7）
> 端锁定 🟠 STABLE（仅**新增**函数与 env；内部常量删除属 🟡 FLEXIBLE）

## 1. 模块职责与边界

### 1.1 职责（唯一权威）

1. **全系统 TTL / 池刷新间隔 / 池上限 / 端点缓存上限 / 上游编码的单一权威来源** → `cache_policy(domain, now=None)`。
2. **交易时段时间源** → `_is_trading_hours(now=None)` / `_trading_tiers(now=None)`（保留为唯一时间源）；支持**休市日**（env `TRADING_HOLIDAYS`）。
3. **股票代码归一的唯一权威** → `canonical_code(code) -> str | None`（§2.6，**冻结接口**）：把 `sh600519` / `600519.SH` 两种可接受拼写折叠成同一 canonical 形，使同一只股票不会铸出两个池键 / 缓存键 / 上游 URL。
4. **env 注册中心** → 所有 IO 预算 / 资源上限经 `os.getenv` 注册，默认值不变（兼容）。

### 1.2 明确不做

- 不做缓存读写（不持有 `cache` / `feed_cache`）。
- 不发起任何网络请求；不创建线程 / 锁 / 执行器。
- 不依赖任何 `china_finance_rss` 内模块（含 cache/server/stream/stock_api/market_api/cdp_engine）。

### 1.3 layerIsolation 约束（tech-stack.json 原文）

```
pattern: china_finance_rss/config.py
forbiddenImports: cache, server, stream, stock_api, market_api, cdp_engine
reason: config 是 TTL/配置单一权威来源，禁止依赖任何业务模块
```

→ 本模块允许 import 仅：`os`、`re`、`datetime`（`datetime` 的 `timezone`/`timedelta`）。

### 1.4 依赖方向

> **图例（REV-DES-04 澄清）：`←` 表「分层顺序 / 构建顺序」（Layer 0 在左），不是 import 关系。**
> `metrics` 是**独立叶子**（零业务依赖，**不 import config**，仅 `threading`/`logging`），与 `config` 并列同属 Layer 0，并非 config 的上层；`cache` **同时** import `config` 与 `metrics`。

```
分层顺序（← 表先后，非 import 关系）：
  Layer 0:  config（无依赖）   ‖   metrics（零业务依赖叶子，与 config 并列，互不依赖）
  Layer 1:  cache ← {config, metrics}
  Layer 2:  stock_api / market_api / stream ← {config, cache, metrics}
  Layer 3:  server ← stock_api / market_api / stream / cache
  cdp_engine: 仅依赖 config（并单向写 metrics 观测）
```

本模块位于最底层。**唯一历史例外**：`cdp_engine` / `jin10_public_headers` 两个全局槽由 `server.py` 初始化时写入（§3.4），本次保持原状，不新增同类槽。

---

## 2. 接口契约

### 2.1 `cache_policy(domain, now=None) -> dict`

```python
def cache_policy(domain: str, now: float | None = None) -> dict:
```

| 参数 | 类型 | 必填 | 默认 | 语义 |
|------|------|------|------|------|
| `domain` | `str` | 是 | — | `DOMAIN_MATRIX` 的键（§3.1 全表，共 11 个域） |
| `now` | `float \| None` | 否 | `None` | epoch 秒；交易时段判定注入点。`None` → 使用当前时钟（`time.time()` 语义） |

**返回**：每次调用**新建**的 dict（不得返回共享对象，调用方不得原地修改）。键集合固定（不得增删），`encoding` 条件出现：

| 键 | 类型 | 说明 |
|----|------|------|
| `tier` | `str` | `'L1' \| 'L2' \| 'L3' \| 'L4'` |
| `ttl` | `int` | 秒，正数。该域缓存有效期的**权威值** |
| `pool_refresh` | `int \| None` | 秒，恒 `>= ttl`；`None` 表示该域无去重池 |
| `pool_max` | `int \| None` | 去重池成员上限；`None` 表示无池 |
| `cache_max` | `int \| None` | **终态（端点）缓存**或 **feed 缓存**的独立上限；`None` 表示该域**没有自己的终态缓存**（仅经共享 URL 缓存 `cache.fetch_json` 取数，其条目由 `cache.MAX_CACHE_SIZE=2000` 全局约束）。**P7b 钉死语义**：`plate`/`news_url`/`longhu`/`margin` 四域为 URL-cache-only ⇒ `'n/a'`→`None`（此处给 `int` 会是运维无法生效的死设置） |
| `encoding` | `str` | **仅**当域声明非 utf-8 上游编码时存在（当前仅 `longhu` → `'gbk'`） |

**异常**：`KeyError(domain)`，消息含合法域名清单（`sorted(DOMAIN_MATRIX)`）。
**无默认域兜底**——禁止对未知 domain 静默返回 L4/300s，否则拼写错误会静默复现 TTL 断崖（R16 的失效模式）。
**线程安全**：纯函数，无共享可变状态；任意线程任意时刻可调用。

**返回值中 `None` 的语义（SAD 表述归一化，重要）**

SAD §2.1 矩阵单元格用字面量 `'n/a'` 表示"不适用"。本设计：
- **矩阵单元格保留 `'n/a'` 字面量**（便于与 SAD 逐格对照，零解读成本）；
- **`cache_policy` 返回值一律归一化为 `None`**。

理由：`None` 可直接用于 `is not None` 判空，不引入 `int`/`str` 混合类型；字面量 `'n/a'` 一旦被下游误参与比较或算术会静默出错（且 `pool_refresh >= ttl` 不变式无法在混合类型上成立）。
**若编排层要求返回值保留 `'n/a'` 字面量，唯一改动点 = `_materialize()` 的归一化分支（一处）。**
### 2.2 `_is_trading_hours(now=None)` / `_trading_tiers(now=None)`

```python
def _is_trading_hours(now: float | None = None) -> bool
def _trading_tiers(now: float | None = None) -> dict   # {'L1':int,'L2':int,'L3':int,'L4':int}
```

- `now` 为**新增可选参数**，`now=None` 行为与现状逐字一致 → 存量调用 `_is_trading_hours()` / `_trading_tiers()` **零改动**。
- 语义（P7b 更新）：`now`（epoch 秒）→ CST（UTC+8）→ **① 若该日期 ∈ `TRADING_HOLIDAYS` ⇒ False（休市日优先于星期判定）**；② 交易日（周一至周五）且 09:30–11:30 或 13:00–15:00。
- **盘中**：`{'L1': 8, 'L2': 12, 'L3': 30, 'L4': 300}`；**非盘中**：`{'L1': 120, 'L2': 120, 'L3': 180, 'L4': 300}`（现状保留，不改）。
- 边界保持现状口径：`09:30` 含、`11:30` 含、`15:00` **不含**（`in_afternoon = 13 <= h <= 14`）、周末（weekday ≥ 5）不含。
- **休市日（P7b 新增）**：`TRADING_HOLIDAYS`（env `TRADING_HOLIDAYS`，逗号分隔 `YYYY-MM-DD`，**默认空 frozenset**）列出的日期视为**非交易时段** ⇒ 系统不在休市日按盘中节奏轮询，且 CDP 守护**可以**重启 Chrome（`watchdog_restart_skip_reason` 的 `'trading_hours'` 分支不再命中）。默认空 ⇒ 行为与 v1.1 逐字等价。
- `cache_policy` 内部**只调用一次** `_trading_tiers(now)` 并把结果传给 TTL 与 pool_refresh 两处派生 → 一次调用内 tier 一致（跨时段边界不撕裂）。

### 2.3 新增 env 项（本模块注册，消费者在其它模块）

| env | 默认值 | 类型 | 常量名 | 消费者（落点） | AC |
|-----|--------|------|--------|---------------|----|
| `MAX_INFLIGHT` | `MAX_WORKERS * 2` = **40** | int | `MAX_INFLIGHT` | `server.BoundedThreadPoolServer`（503 准入） | E8/S5/S10 |
| `MAX_GROUPS` | **200** | int | `MAX_GROUPS` | `stream.create_group`（超限 400） | E7/S9 |
| `MGMT_BODY_TIMEOUT` | **5** | int（秒） | `MGMT_BODY_TIMEOUT` | `stream._read_json_body` | S7 |
| `STREAM_QUEUE_BYTES_BUDGET` | **134217728**（128MB，整数字节） | int | `STREAM_QUEUE_BYTES_BUDGET` | `stream._broadcast`（§4.2 distinct 帧计费） | E5/E7/A2 |
| `NEG_TTL` | **5** | int（秒） | `NEG_TTL` | `cache._record_failure` / 负缓存判定 | S3 |
| `PROBE_TIMEOUT` | **2** | int（秒） | `PROBE_TIMEOUT` | `cache.fetch_json` 半开探测（`_probe_budget` 阶梯**首级**；**封顶**是 `cache._PROBE_BUDGET_CAP=5.0`，**非** `REQUEST_TIMEOUT`） | S3/S7 |
| `MAX_HEALTH_INFLIGHT` | **5** | int | `MAX_HEALTH_INFLIGHT` | `server.build_health_payload` 信号量准入 | S8/S10 |
| `STREAM_PING_INTERVAL` | **20** | int（秒） | `STREAM_PING_INTERVAL` | `stream._serve_sse`（socket 超时 = PING×2 = 40s） | S7/R17 |
| `LISTEN_BACKLOG` | **128** | int | `LISTEN_BACKLOG` | `server.BoundedThreadPoolServer.request_queue_size`（`listen(2)` backlog） | E1 |
| `TRADING_HOLIDAYS` | **`''`（空 frozenset）** | 逗号分隔 `YYYY-MM-DD` → `frozenset[date]` | `TRADING_HOLIDAYS` | `_is_trading_hours`（休市日）/ `cdp_engine.watchdog_restart_skip_reason` | A3/S4 |
| `CDP_RESTART_THROTTLE` | **15** | int（秒） | `CDP_RESTART_THROTTLE` | `cdp_engine.ensure_chrome` / `full_chrome_restart` / `_maybe_reconnect`（`×2` = back-to-back 护栏） | R19 |

实现要点（逐条，避免编码者发明）：
- `MAX_INFLIGHT` 默认必须**由 `MAX_WORKERS` 派生**（`str(MAX_WORKERS * 2)`），而非写死 `'40'`——使 `MAX_WORKERS` env 改动时默认联动（SAD §2.2 R-1①："把 `max_workers*2` 提为显式配置，使 '40' 不再是隐式推导"）。
- `STREAM_QUEUE_BYTES_BUDGET` env 只接受**整数字节**，不做 `'128MB'` 后缀解析（不引入解析器；SAD 只定默认值 128MB）。
- `NEG_TTL` 默认 `5`：SAD 的派生式 `min(5, cache_policy('quote')['ttl'])` 在盘中（L1=8）与非盘中（L1=120）均等于 5，故默认值和派生式等价；env 是**唯一的显式覆盖入口**（AR-3 要求 `NEG_TTL`/`PROBE_TIMEOUT` 可调）。
  - ⚠️ **REV-DES-08 · AC-S3 口径前提**：SAD §2.3 D-1 与 `cache.md` T-CACHE-4 的稳态推导「`2s(半开探测) + 5s(负缓存) = 7s` 周期、P95 ≤ 3s」**以 `NEG_TTL = 5` 且探测预算恒为 `PROBE_TIMEOUT` 为前提**。env 覆盖 `NEG_TTL` 属**运维变更**：周期变为 `探测预算 + NEG_TTL`，`P95 ≤ 3s` 仅在 `NEG_TTL` 保持同量级时成立 ⇒ **覆盖即须重跑 AC-S3 模式 B 校准**。CI 断言一律按默认值 5 执行（不得注入覆盖）。
  - ⚠️ **P7b 追加前提（★ v1.3 已被下条更正）**：`cache._probe_budget` 的**递增阶梯**（BR-CACHE-22）使"探测预算恒为 2s"不再成立 ⇒ v1.2 曾据此把 **`P95 ≤ 3s` 的成立条件退化为"请求密度相关"**（高峰密度下仍成立；低密度下 P95 ≈ 阶梯当轮预算）。完整量化与三个备选处置见 `cache.md` §10#11。
  - ✅ **AC-S3 裁决（v1.3 更正）**：阶梯**封顶 = `cache._PROBE_BUDGET_CAP = 5.0`**（模块级机制常量，**不注册为 env**），序列为 `2→4→5`；**`REQUEST_TIMEOUT(10s)` 不再是阶梯上限**——它只在"无失败历史"与"失败段已老化（≥`_HISTORY_AGE=600s`）"两支作**一次性全预算探测**（BR-CACHE-5/20/22）。⇒ 持续黑洞稳态 ≈ `5s 探测 + 5s NEG_TTL = 10s` 周期、慢请求占比 ≈50% ⇒ **P95 ≈ 5s**；单请求上界 `≤15s` 仍恒成立。`PROBE_TIMEOUT` 在本表**仍作为阶梯首级（下限）**，**不是**上限。
- `STREAM_PING_INTERVAL` 由硬编码常量改为 env（R17/S7），**默认 20 不变**（AC-S7 的 40s = PING×2 口径不变）。编排层已裁决 ✅ env 化（待确认 #6），SAD §3 config 行将回填（本文登记见 §10#8 / D-4）。
- **`LISTEN_BACKLOG` 默认 128（P7b / BUG-P6C-03，§10#11）**：`socketserver` 默认 backlog = 5，突发连接时内核丢 SYN、客户端 ~1s（RTO）后重传，表现为 AC-E1 的 ~1.006s 长尾。必须 **≥ 它前置的两道准入闸**：主端口 `MAX_INFLIGHT`(=40) 与流端口 `MAX_STREAM_CONNS`(=100) ⇒ 128 同时留出余量。可由 env 覆盖。
- **`TRADING_HOLIDAYS` 默认空（P7b，§10#12）**：见 §2.2；解析在**导入期**完成，非法日期（非 `YYYY-MM-DD`）⇒ `datetime.strptime` 抛 `ValueError` 冒泡（与其他 env 一致的 fail-fast）；空串/全空白 token 被跳过。
- **`CDP_RESTART_THROTTLE` 默认 15（P7b，§10#13）**：注册在本模块，使 `cdp_engine` **不再自行读 env**（env 注册中心单一权威，`code-discipline §6`）；语义为"两次 `ensure_chrome` 启动之间的最小间隔"，并被 `full_chrome_restart` / `watchdog_restart_skip_reason` / `CDPPage._maybe_reconnect` 以 `×2` 用作 back-to-back 护栏。
- 全部 int 转换在**模块导入期**完成；非法值 → `ValueError` 冒泡（fail-fast，见 §6）。

### 2.4 已删除的常量清单 + 消费者迁移表（**实现态：已全部落地**）

> **P7b 状态更新**：下表所有常量**已在实现中删除**，全部消费者已迁移到 `cache_policy(...)`（`grep` 全仓无残留引用）。本节保留为**迁移口径的权威记录**（"唯一迁移目标"仍约束后续维护：不得引入第二来源）。

> ⚠️ **REV-DES-逆向-2 · 删除前置条件（已满足，记录备查）**
> 常量被删除而消费者未同步 ⇒ `ImportError` ⇒ **整进程不可用**（非局部降级）。因此删除与迁移**必须落在同一 change-set**。当前 `server.md` / `stock_api.md` / `stream.md` / `market_api.md` / `cdp_engine.md` 详设齐备，常量删除与消费者迁移已同批完成 ⇒ **前置条件已解除**；后续任何"删常量"改动仍须遵守同一纪律（先迁消费者、后删常量，同 change-set）。

| 删除常量 | 现值 | 定义处 | 消费者（file:line，现状） | 迁移目标 |
|----------|------|--------|--------------------------|---------|
| `CACHE_TTL` | 300 | config.py:12 | `cache.py:9,29`（默认 ttl）；`server.py:37,497`（healthz `cache_ttl`）；`server.py:668`（feed expires）；`server.py:936`（启动日志）；`utils.py:12`（**未使用 import**） | `cache_policy('news_url')['ttl']`（fetch_json 默认）；`cache_policy('feed')['ttl']`（healthz/feed/日志）；utils 删 import |
| `_MAX_CACHE_AGE` | 120 | config.py:28 | `stock_api.py:18,159,641,651,779` | `cache_policy('quote'\|'fundflow'\|'timeline'\|'f10')['ttl']` |
| `_MARGIN_CACHE_TTL` | 600 | config.py:90 | `market_api.py:9,30` | `cache_policy('margin')['ttl']`（值不变 = 600） |
| `_FUNDFLOW_POOL_REFRESH` | 25 | config.py:117 | `stock_api.py:26,314` | `cache_policy('fundflow')['pool_refresh']` |
| `_FUNDFLOW_MAX_POOL` | 500 | config.py:118 | `stock_api.py:26,299` | `cache_policy('fundflow')['pool_max']` |
| `_TIMELINE_POOL_REFRESH` | 30 | config.py:119 | `stock_api.py:27,406` | `cache_policy('timeline')['pool_refresh']` |
| `_TIMELINE_MAX_POOL` | 500 | config.py:120 | `stock_api.py:27,391` | `cache_policy('timeline')['pool_max']` |
| `_F10_POOL_REFRESH` | 60 | config.py:121 | `stock_api.py:28,535` | `cache_policy('f10')['pool_refresh']` |
| `_F10_MAX_POOL` | 300 | config.py:122 | `stock_api.py:28,518` | `cache_policy('f10')['pool_max']` |
| `_BASIC_INFO_POOL_REFRESH` | 120 | config.py:123 | **无消费者**（死常量，AR-6 已登记） | 直接删 |
| `_BASIC_INFO_MAX_POOL` | 500 | config.py:124 | `stock_api.py:29,676` | `cache_policy('quote')['pool_max']` ★**行为变更 500→2000**（见下表脚注） |
| `_ANNOUNCEMENT_POOL_REFRESH` | 60 | config.py:125 | `stock_api.py:30,739` | `cache_policy('announcement')['pool_refresh']` |
| `_ANNOUNCEMENT_MAX_POOL` | 300 | config.py:126 | `stock_api.py:30,724` | `cache_policy('announcement')['pool_max']` |
| `MAX_FEED_CACHE_SIZE`（cache.py） | 100 | cache.py:149 | `server.py:47,663` | `cache_policy('feed')['cache_max']` |
| `_SECTOR_CACHE_TTL`（stock_api.py） | 604800 | stock_api.py:583 | `stock_api.py:591` | `cache_policy('sector')['ttl']` |

**保留（不动）**：`PORT` `STREAM_PORT` `STREAM_HOST` `CDP_URL` `REQUEST_TIMEOUT` `PUBLIC_BASE_URL` `MAX_WORKERS` `MAX_STREAM_CONNS` `MAX_CODES_PER_SUB` `MAX_DEDUP_CODES` `STREAM_GROUP_IDLE_TTL` `CDP_RESTART_INTERVAL` `_MAX_BATCH_SIZE`(50) `_*_EXPECTED_KEYS` `_*_BASE_URL` `_*_HEADERS` `VALID_STOCK_CODE` `stock_nav_page_names()` `cdp_engine` `jin10_public_headers`。

> ★ **`VALID_STOCK_CODE` 的 P7b 现状（§10#14）**：该正则**保留**，但**已不再被 `stream.py` 消费**（流端口现经 `config.canonical_code` 校验，`test_stream.py` 直接断言源码中不出现 `VALID_STOCK_CODE`）；当前唯一消费者是 `canonical_code` 自身（§2.6）。**建议**（未落地、不强制）：把 `$` 改为 `\Z` 锚定——Python 的 `$` 会匹配**末尾换行之前**，理论上 `'sh600519\n'` 可穿过校验；`canonical_code` 已先 `strip()`，故生产路径无实际逃逸面。`utils.py` 的 `CACHE_TTL` **死 import 已删除**（§10#1）。

> ★ **行为变更登记（REV-DES-06；联动 S9 / AR-8）**：`_BASIC_INFO_MAX_POOL` **500 → `cache_policy('quote')['pool_max'] = 2000`**（4× 池上限放大）。依据 SAD §2.1——basic_info 与 `/stock/data` 同属 `quote` 域、共享同一去重池，故取**域口径** `'dedup' = MAX_DEDUP_CODES = 2000` 而非旧常量 500。**内存护栏改由端点缓存独立 LRU 承担**（`quote.cache_max = 2000`，见 §3.1），并非静默等价替换：该行计入 **AC-S9 进程内存总账（AR-8）**，编码/评审须核对总账而非按旧值估算。
> ★ **`_BASIC_INFO_POOL_REFRESH`（死常量）**：全仓无引用（AR-6 已登记），**直接删、无迁移**；`quote.pool_refresh` 仍按域定义（= `quote.ttl`），以备 basic_info 走池。

### 2.5 INV-1a 的实现落点

> INV-1a（SAD §2.1）：对任意 domain，`ttl_url(d) == ttl_terminal(d) == cache_policy(d)['ttl']`，且 `pool_refresh(d) >= ttl(d)`；实时域（quote/fundflow/timeline）满足 `ttl(d) <= L1`。

三条落点（缺一即不变式不成立）：
1. **来源保证（本模块）**：`pool_refresh = int(round(ttl * pool_refresh_factor))`，`pool_refresh_factor ∈ {1.0, 2.0}` 恒 `>= 1.0` ⇒ `pool_refresh >= ttl` 由构造保证。
2. **同源取用（消费者）**：`stock_api._process_chunk` 的 TTL 与传给 `fetch_json(ttl=...)` 的 TTL 必须来自**同一次 `cache_policy(d)` 调用的同一个变量**（SAD §2.1 D1/D3："同一变量、同一次调用，不是两个相等的常量"）。
3. **可白盒断言（测试）**：`DOMAIN_MATRIX` 为**公开名**，测试直接 `for d in config.DOMAIN_MATRIX:` 迭代断言（§8 用例 CFG-T1）。

### 2.6 `canonical_code(code) -> str | None`（**冻结接口**，P7b 新增）

```python
def canonical_code(code: str) -> str | None:
```

**职责**：股票代码归一的**唯一权威**。把两种可接受的拼写折叠为同一 canonical 形，使同一只股票不会铸出两个池键 / 缓存键 / 上游 URL；同时让 CDP 侧（混用精确比较与 `.upper()`）对两种拼写都能匹配上。

| 输入（大小写不敏感、`strip()` 去首尾空白） | 返回 |
|------------------------------------------|------|
| `sh600519` / `SH600519` / `sz000001` / `bj430047` | 小写交易所前缀形（原样小写） |
| `600519.SH` / `000001.SZ` / `430047.BJ`（点号形，交换前后缀大小写均可） | `sh600519` / `sz000001` / `bj430047` |
| 非 `str` / 空 / 空白 / 长度错 / 未知交易所 | **`None`** |

- **canonical 形 = 小写交易所前缀拼写**（`sh600519`/`sz000001`/`bj430047`），即上游 `secu_code` 参数的形态。
- **调用方自行决定 `None` 的语义**：HTTP/流端口入口 ⇒ 拒绝（400）；CDP 不匹配 ⇒ 计 `cdp_unavailable`。本函数**不**决定拒绝策略。
- **唯一性约束**：**每一个 ingress、每一个缓存/池/账本键都必须过此函数**（`server._handle_stock_batch` 截断前折叠、`stock_api._process_chunk` 池/缓存/账本键、`stock_api.cached_batch` 查询键、`cdp_engine.navigate_stock`/`_same_code`）。
- **响应按请求原拼写回填**：归一只用于内部定位，`build_batch_response` 仍以**请求拼写**为键（`stock_api._process_chunk` 的 `alias` 映射）。
- **幂等**：`canonical_code(canonical_code(x)) == canonical_code(x)`（测试 CFG-T11）。
- **线程安全**：纯函数，无共享可变状态。
- **冻结接口**：`server.py` / `stream.py` 按此名消费；改名属 🔴 FROZEN 变更。
---

## 3. 数据结构

### 3.1 `DOMAIN_MATRIX` 全表（公开名，yaml）

```yaml
# domain -> (tier, ttl_factor, pool_refresh_factor, pool_max, cache_max)
# ttl_factor: float | 'override:<秒>'
# pool_refresh_factor: float | 'n/a'
# pool_max: 'dedup'(=MAX_DEDUP_CODES) | 'fixed:<n>' | 'n/a'
# cache_max: int | 'n/a'      # 终态缓存 / feed 缓存上限；URL-cache-only 域 = 'n/a'（P7b）
DOMAIN_MATRIX:
  quote:        [L1, 1.0,              1.0, 'dedup',       2000]   # stock/data, basic_info, 实时价
  fundflow:     [L1, 1.0,              1.0, 'dedup',       2000]
  timeline:     [L1, 1.0,              1.0, 'dedup',       2000]
  plate:        [L2, 1.0,              1.0, 'fixed:200',  'n/a']   # cls/hotplate, cls/plate（URL 缓存，P7b）
  news_url:     [L3, 1.0,              1.0, 'n/a',        'n/a']   # 5 源 RSS URL（共享 cache{}，2000）
  feed:         [L3, 1.0,              1.0, 'fixed:100',    100]   # ★ 修 D4：feed 缓存改由 L3 派生
  announcement: [L3, 1.0,              1.0, 'dedup',        500]   # Q5 定案 L3
  longhu:       [L4, 1.0,              1.0, 'n/a',        'n/a']   # ★ 新增：GBK 上游，日更（URL 缓存）
  margin:       [L4, 2.0,              2.0, 'fixed:16',   'n/a']   # = 600s / 1200s（URL 缓存，P7b）
  f10:          [L4, 1.0,              1.0, 'dedup',        500]
  sector:       [L4, 'override:604800', n/a, 'fixed:2000',  2000]  # 7d 行业名
```

> **P7b `cache_max` 语义（§10#15）**：`cache_max` 约束该域的**终态缓存**（`stock_api._cache_store`）或 **feed 缓存**（`cache.feed_cache_put`）。**仅经共享 URL 缓存**取数的域（`plate` / `news_url` / `longhu` / `margin`）声明 `'n/a'` —— 其条目由全局 `cache.MAX_CACHE_SIZE=2000` 约束，在此给 `int` 会是运维无法生效的死设置。`'n/a'` 字面量在矩阵中保留（便于与 SAD 逐格对照），`cache_policy` 归一化为 `None`（BR-CFG-11）。

补充常量：

```yaml
_DOMAIN_ENCODING: {longhu: 'gbk'}   # 仅声明非 utf-8 的域；cache_policy 据此挂 encoding 键
```

### 3.2 `cache_policy` 返回值（yaml，逐域实值）

```yaml
L1:  {trading: 8,   off: 120}
L2:  {trading: 12,  off: 120}
L3:  {trading: 30,  off: 180}
L4:  {trading: 300, off: 300}
# 以下为 trading / off 两组实值（pool_refresh = ttl × factor；'n/a'→null；'dedup'→2000；'fixed:N'→N）
quote:        {tier: L1, ttl: [8,120],     pool_refresh: [8,120],     pool_max: 2000, cache_max: 2000}
fundflow:     {tier: L1, ttl: [8,120],     pool_refresh: [8,120],     pool_max: 2000, cache_max: 2000}
timeline:     {tier: L1, ttl: [8,120],     pool_refresh: [8,120],     pool_max: 2000, cache_max: 2000}
plate:        {tier: L2, ttl: [12,120],    pool_refresh: [12,120],    pool_max: 200,  cache_max: null}
news_url:     {tier: L3, ttl: [30,180],    pool_refresh: [30,180],    pool_max: null, cache_max: null}
feed:         {tier: L3, ttl: [30,180],    pool_refresh: [30,180],    pool_max: 100,  cache_max: 100}
announcement: {tier: L3, ttl: [30,180],    pool_refresh: [30,180],    pool_max: 2000, cache_max: 500}
longhu:       {tier: L4, ttl: [300,300],   pool_refresh: [300,300],   pool_max: null, cache_max: null,
               encoding: gbk}
margin:       {tier: L4, ttl: [600,600],   pool_refresh: [1200,1200], pool_max: 16,   cache_max: null}
f10:          {tier: L4, ttl: [300,300],   pool_refresh: [300,300],   pool_max: 2000, cache_max: 500}
sector:       {tier: L4, ttl: [604800,604800], pool_refresh: null,   pool_max: 2000, cache_max: 2000}
```

> AC-E9 口径核对：`longhu.ttl = 300`（trading 与 off 均 300）满足"L4 TTL ≥ 300s"。
> `announcement` 由裸 `ttl=15`/pool 60s → `30/180` 与 `30/180`（Q5）。
> `feed` 由固定 300s → `30/180`（D4，行为变更，Q3）。

### 3.3 env 常量（模块级不可变）

见 §2.3 表，均为模块导入期求值的 `int`（`TRADING_HOLIDAYS` 为 `frozenset[date]`）。**不得在运行期重读 env**（`stock_nav_page_names()` 是既有唯一例外，保留）。

### 3.4 代码归一的数据结构（P7b）

```yaml
VALID_STOCK_CODE: <re.Pattern>        # r'^(sh|sz|bj)\d{6}$|^\d{6}\.(BJ|SH|SZ)$', re.IGNORECASE
                                      # 保留公开名；当前唯一消费者 = canonical_code（stream 已迁走）
_DOTTED_STOCK_CODE: <re.Pattern>      # r'^(\d{6})\.(SH|SZ|BJ)$', re.IGNORECASE（canonical 专用）
canonical_form: 小写交易所前缀形       # sh600519 / sz000001 / bj430047
invalid_result: None                  # 非 str / 空 / 空白 / 长度错 / 未知交易所

TRADING_HOLIDAYS: frozenset[datetime.date]   # env 解析结果；默认 frozenset()（空）
_parse_holidays(raw):                         # 逗号分隔 YYYY-MM-DD；空白 token 跳过；
                                              # 非法日期 ⇒ datetime.strptime 抛 ValueError（导入期 fail-fast）
```
---

## 4. 业务规则（编号供伪代码与测试引用）

| 编号 | 规则 | 依据 |
|------|------|------|
| **BR-CFG-1** | tier 基值只由 `_trading_tiers(now)` 决定：盘中 `{L1:8,L2:12,L3:30,L4:300}`；非盘中 `{L1:120,L2:120,L3:180,L4:300}`。**盘中判定前置休市日闸**：`now_cst.date() ∈ TRADING_HOLIDAYS` ⇒ 直接返回非交易时段（BR-CFG-14） | SAD §2.1 / PRD §2.3 |
| **BR-CFG-2** | `ttl_factor` 为 `float` → `ttl = int(round(tier_base × factor))`；为 `'override:<n>'` → `ttl = int(n)`，**忽略 tier 基值与时段** | SAD §2.1 sector=7d |
| **BR-CFG-3** | `pool_refresh_factor` 为 `float` → `pool_refresh = int(round(ttl × factor))`，恒 `>= ttl`；为 `'n/a'` → `pool_refresh = None` | INV-1a |
| **BR-CFG-4** | `pool_max == 'dedup'` → `MAX_DEDUP_CODES`（=2000）；`'fixed:<n>'` → `int(n)`；`'n/a'` → `None` | §4.3 池自洽 |
| **BR-CFG-5** | `cache_max` 为 `int` → 原值；`'n/a'` → `None`。**语义（P7b 钉死）**：约束该域**终态缓存**或 **feed 缓存**；URL-cache-only 域（`plate`/`news_url`/`longhu`/`margin`）恒为 `None`（条目由 `cache.MAX_CACHE_SIZE` 全局约束） | ADR-008 / §10#15 |
| **BR-CFG-6** | 实时域（quote/fundflow/timeline）必须满足 `ttl <= L1`；三者 `ttl_factor=1.0` 时 `ttl == L1`（等号成立） | INV-1a / AC-A3 |
| **BR-CFG-7** | `encoding` 键**仅**当 `domain in _DOMAIN_ENCODING` 时出现；值为该域编码（当前仅 `longhu='gbk'`）。缺键 ⇒ 上游按 `utf-8` 解码（`fetch_json` 默认） | SAD §2.3 D-5 / §7.3#7 |
| **BR-CFG-8** | 未知 `domain` → `raise KeyError(domain)`（消息含 `sorted(DOMAIN_MATRIX)`），**不返回默认** | R16 防复发 |
| **BR-CFG-9** | 一次 `cache_policy` 调用内 `_trading_tiers(now)` 只算一次；`ttl` 与 `pool_refresh` 消费同一份 tier 基值 | 跨边界不撕裂 |
| **BR-CFG-10** | 返回值每次新建；`DOMAIN_MATRIX` 与 env 常量在运行期**只读**（禁止原地修改） | 线程安全 |
| **BR-CFG-11** | `'n/a'` 在矩阵中保留字面量，在返回值中归一化为 `None`（见 §2.1） | SAD 归一化 |
| **BR-CFG-12** | 非 config.py 模块禁止出现裸 TTL 数字字面量；一律 `cache_policy(d)['ttl']` | tech-stack namingRules |
| **BR-CFG-13** | **`canonical_code` 是股票代码归一的唯一权威（冻结接口）**：接受"小写/大写交易所前缀形"与"点号形"两种拼写，折叠为**小写前缀形**；非 `str`/空/空白/长度错/未知交易所 ⇒ `None`。**每个 ingress 与每个缓存/池/账本键必须过此函数**；`None` 的拒绝语义由调用方决定（入口 400 / CDP 计 `cdp_unavailable`） | SAD §2.1 / P1-6 / §10#16 |
| **BR-CFG-14** | `TRADING_HOLIDAYS` 中的日期视为**非交易时段**，判定**优先于星期**；默认空 frozenset ⇒ 行为与 v1.1 逐字等价。解析在**导入期**完成，非法日期 ⇒ `ValueError` 冒泡 | S4/A3 / §10#12 |
| **BR-CFG-15** | `LISTEN_BACKLOG` 必须 **≥ 其前置的两道准入闸**（主端口 `MAX_INFLIGHT`、流端口 `MAX_STREAM_CONNS`）；默认 128 | E1 / BUG-P6C-03 |
| **BR-CFG-16** | 所有 env 常量（含 `CDP_RESTART_THROTTLE`）**只在 config.py 读取**；其它模块经 `config.X` 引用，**禁止自行 `os.getenv`** | env 注册中心 / code-discipline §6 |
| **BR-CFG-17** | `VALID_STOCK_CODE` 保留为公开名，但**只由 `canonical_code` 内部消费**（`stream.py` 已迁移）；建议改用 `\Z` 锚定（`$` 会匹配末尾换行前，但 `canonical_code` 先 `strip()` ⇒ 生产无逃逸面） | §10#14 |

## 5. 伪代码

```python
# ── module level（顺序：env → 常量 → 矩阵 → 时间源 → 派生函数）────────────
import os, re
from datetime import datetime, timezone, timedelta

# 1) 既有 env（保持原样）
PORT = int(os.getenv('PORT', '8053'))
...
MAX_WORKERS = int(os.getenv('MAX_WORKERS', '20'))

# 2) 新增 env（§2.3）
MAX_INFLIGHT             = int(os.getenv('MAX_INFLIGHT', str(MAX_WORKERS * 2)))
MAX_GROUPS               = int(os.getenv('MAX_GROUPS', '200'))
MGMT_BODY_TIMEOUT        = int(os.getenv('MGMT_BODY_TIMEOUT', '5'))
STREAM_QUEUE_BYTES_BUDGET = int(os.getenv('STREAM_QUEUE_BYTES_BUDGET', str(128 * 1024 * 1024)))
NEG_TTL                  = int(os.getenv('NEG_TTL', '5'))
PROBE_TIMEOUT            = int(os.getenv('PROBE_TIMEOUT', '2'))
MAX_HEALTH_INFLIGHT      = int(os.getenv('MAX_HEALTH_INFLIGHT', '5'))
STREAM_PING_INTERVAL     = int(os.getenv('STREAM_PING_INTERVAL', '20'))   # 原为硬编码 20
LISTEN_BACKLOG           = int(os.getenv('LISTEN_BACKLOG', '128'))        # P7b：listen(2) backlog
CDP_RESTART_THROTTLE     = int(os.getenv('CDP_RESTART_THROTTLE', '15'))   # P7b：cdp_engine 不再读 env

# 3) DOMAIN_MATRIX（§3.1 字面量）+ 编码表
DOMAIN_MATRIX = {...}
_DOMAIN_ENCODING = {'longhu': 'gbk'}

# 3b) 代码归一（P7b，§2.6）
VALID_STOCK_CODE = re.compile(r'^(sh|sz|bj)\d{6}$|^\d{6}\.(BJ|SH|SZ)$', re.IGNORECASE)
_DOTTED_STOCK_CODE = re.compile(r'^(\d{6})\.(SH|SZ|BJ)$', re.IGNORECASE)


def canonical_code(code):
    """BR-CFG-13：唯一权威代码归一；canonical 形 = 小写交易所前缀形。"""
    if not isinstance(code, str):
        return None
    text = code.strip()
    dotted = _DOTTED_STOCK_CODE.match(text)
    if dotted:
        return f'{dotted.group(2).lower()}{dotted.group(1)}'   # 600519.SH → sh600519
    lowered = text.lower()
    return lowered if VALID_STOCK_CODE.match(lowered) else None


# 3c) 休市日（P7b，§2.2/BR-CFG-14）
def _parse_holidays(raw):
    days = set()
    for token in (raw or '').split(','):
        token = token.strip()
        if token:
            days.add(datetime.strptime(token, '%Y-%m-%d').date())   # 非法 ⇒ ValueError（导入期）
    return frozenset(days)


TRADING_HOLIDAYS = _parse_holidays(os.getenv('TRADING_HOLIDAYS', ''))


def _is_trading_hours(now=None):          # now: epoch 秒 | None
    if now is None:
        now_cst = datetime.now(timezone.utc) + timedelta(hours=8)
    else:
        now_cst = datetime.fromtimestamp(now, timezone.utc) + timedelta(hours=8)
    if now_cst.date() in TRADING_HOLIDAYS:                # BR-CFG-14：休市日优先
        return False
    if now_cst.weekday() >= 5:
        return False
    h, m = now_cst.hour, now_cst.minute
    in_morning   = (h == 9 and m >= 30) or (10 <= h <= 10) or (h == 11 and m <= 30)
    in_afternoon = (13 <= h <= 14)
    return in_morning or in_afternoon

def _trading_tiers(now=None):
    if _is_trading_hours(now):
        return {'L1': 8, 'L2': 12, 'L3': 30, 'L4': 300}
    return {'L1': 120, 'L2': 120, 'L3': 180, 'L4': 300}
```

```python
# ── 派生（BR-CFG-1..11）──────────────────────────────────────────────
def _resolve_int_factor(spec, base):
    """float → round(base*factor); 'override:<n>' → int(n)"""
    if isinstance(spec, str) and spec.startswith('override:'):
        return int(spec.split(':', 1)[1])
    return int(round(base * float(spec)))

def _resolve_pool_max(spec):
    if spec == 'n/a':                return None
    if spec == 'dedup':              return MAX_DEDUP_CODES
    if isinstance(spec, str) and spec.startswith('fixed:'):
        return int(spec.split(':', 1)[1])
    raise ValueError(f'bad pool_max spec: {spec!r}')

def _materialize(domain, matrix_row, tiers):
    tier, ttl_factor, refresh_factor, pool_max_spec, cache_max_spec = matrix_row
    base = tiers[tier]                                        # BR-CFG-1
    ttl = _resolve_int_factor(ttl_factor, base)               # BR-CFG-2
    if refresh_factor == 'n/a':
        pool_refresh = None                                   # BR-CFG-3
    else:
        pool_refresh = int(round(ttl * float(refresh_factor)))
    policy = {
        'tier': tier,
        'ttl': ttl,
        'pool_refresh': pool_refresh,
        'pool_max': _resolve_pool_max(pool_max_spec),         # BR-CFG-4
        'cache_max': None if cache_max_spec == 'n/a' else int(cache_max_spec),  # BR-CFG-5/11
    }
    enc = _DOMAIN_ENCODING.get(domain)                        # BR-CFG-7
    if enc is not None:
        policy['encoding'] = enc
    return policy

def cache_policy(domain, now=None):
    if domain not in DOMAIN_MATRIX:                           # BR-CFG-8
        raise KeyError(
            f'unknown cache domain {domain!r}; known: {sorted(DOMAIN_MATRIX)}')
    tiers = _trading_tiers(now)                               # BR-CFG-9：只算一次
    return _materialize(domain, DOMAIN_MATRIX[domain], tiers) # BR-CFG-10：新建 dict
```
---

## 6. 错误处理

| 情形 | 行为 | 理由 |
|------|------|------|
| 未知 `domain` | `KeyError(domain)`（消息含合法域名清单） | 拼写错误必须立刻暴露；静默兜底会复现 R16 断崖（BR-CFG-8） |
| env 非整数（如 `MAX_GROUPS=abc`） | 模块导入期 `ValueError` 冒泡 → 进程启动失败 | fail-fast；错误配置必须在启动期可见，不得运行期静默降级 |
| 矩阵 spec 非法（如 `pool_max='fixed:x'`） | `ValueError`（`_resolve_pool_max`） | 编程错误，启动期即暴露 |
| 矩阵 spec 为 `'n/a'` | **不是错误**，归一化为 `None` | BR-CFG-11 |
| `TRADING_HOLIDAYS` 含非法日期（如 `2026-13-01`） | 模块导入期 `datetime.strptime` 抛 `ValueError` 冒泡 → 进程启动失败 | fail-fast（与其它 env 一致）；错误的休市日会静默改变全系统轮询节奏 |
| `canonical_code` 收到非法输入（非 str / 空 / 未知交易所） | **不是错误**，返回 `None`；不抛 | BR-CFG-13：`None` 是"无法归一"的正常信号，拒绝策略由调用方决定 |

本模块**没有降级路径**：它是配置源，降级会掩盖缺陷。所有失败都在导入期或调用期立即抛出。

## 7. 并发安全

- **无锁**：`cache_policy` / `_is_trading_hours` / `_trading_tiers` / **`canonical_code`** 均为纯函数，不读不写共享可变状态（`os.getenv` 结果在导入期冻结；`TRADING_HOLIDAYS` 为导入期冻结的 `frozenset`，运行期只读）。
- `DOMAIN_MATRIX` / `_DOMAIN_ENCODING` / `VALID_STOCK_CODE` / `_DOTTED_STOCK_CODE` / `TRADING_HOLIDAYS` 为模块级**可读常量**：任何模块**不得**原地修改（无锁保护，改了就跨线程可见且不可回滚）。测试若需构造变体（如注入休市日），应 `mock.patch.object(config, 'TRADING_HOLIDAYS', ...)` 并在用后还原，不原地改全局 frozenset。
- 与既有 `_feed_cache_lock` / `_feed_fetch_locks_lock`（cache.py）**无任何关系**：本模块不持有锁、不在锁内被调用（`cache_policy` 可在锁内调用——纯函数、纳秒级、无阻塞 ⇒ 不引入锁序风险）。
- 返回值每次新建 ⇒ 调用方互不干扰（`cache_policy` 的返回 dict 可安全地被单个请求线程独占）。

## 8. 测试要点（映射 AC）

| 用例 | 断言（精确） | 覆盖 AC |
|------|-------------|---------|
| **CFG-T1** policy 一致性白盒 | `for d in DOMAIN_MATRIX:` 断言 `p['ttl'] == p['pool_refresh']`（`pool_refresh is not None` 时 `>=`）；`ttl > 0`；`tier in {L1..L4}`；键集合 == `{tier,ttl,pool_refresh,pool_max,cache_max}` ∪（longhu 的 `encoding`） | A3 |
| **CFG-T2** 实时域 ≤ L1 | 盘中 `cache_policy(d, now=盘中时刻)['ttl'] <= 8`；非盘中 `<= 120`（对 quote/fundflow/timeline） | A3 |
| **CFG-T3** 断崖收敛 | 盘中/非盘中分别断言 `feed.ttl == L3`（30/180）、`quote.ttl == L1`（8/120）、`announcement.ttl == L3`、`longhu.ttl == 300`、`margin.ttl == 600` | A4/E9/E6 |
| **CFG-T4** `now` 注入与边界 | `now` 取 09:30/11:30/13:00/14:59/15:00/周六 → tier 基值符合 BR-CFG-1；`15:00` 判非盘中 | A3 |
| **CFG-T5** 未知域 | `cache_policy('nope')` → `KeyError` 且消息含全部合法域名 | R16 防复发 |
| **CFG-T6** 返回值隔离 | 两次调用 `p1 is not p2`；改 `p1['ttl']` 不影响 `p2` | 线程安全 |
| **CFG-T7** longhu 编码 | `cache_policy('longhu')['encoding'] == 'gbk'`；其余域无 `encoding` 键 | E9 |
| **CFG-T8** `'n/a'` 归一化 | `news_url.pool_max is None`；`longhu.cache_max is None`；矩阵单元格仍为 `'n/a'` | ADR-008 |
| **CFG-T9** env 默认不变 | 无 env 时 `MAX_INFLIGHT == MAX_WORKERS*2`、`MAX_GROUPS==200`、`MGMT_BODY_TIMEOUT==5`、`STREAM_QUEUE_BYTES_BUDGET==134217728`、`NEG_TTL==5`、`PROBE_TIMEOUT==2`、`MAX_HEALTH_INFLIGHT==5`、`STREAM_PING_INTERVAL==20`、`LISTEN_BACKLOG==128`、`CDP_RESTART_THROTTLE==15`、`TRADING_HOLIDAYS==frozenset()` | S7/S3 |
| **CFG-T10** 无裸 TTL 字面量 | 对 `cache.py/stock_api.py/market_api.py/server.py/stream.py` 扫描 `ttl=` 实参来源为 `cache_policy(...)` | R16 |
| **CFG-T11** `canonical_code` 归一/幂等（P7b） | 两形等价：`{'sh600519','SH600519','600519.SH','600519.sh'}` → `'sh600519'`；`sz000001`/`000001.SZ` → `'sz000001'`；`bj430047`/`430047.BJ` → `'bj430047'`；**幂等** `canonical_code(canonical_code(x)) == canonical_code(x)`；非法集（非 str/`''`/`'  '`/`'60051'`/`'600519.XX'`/`'us600519'`）→ `None`；**不抛** | BR-CFG-13 |
| **CFG-T12** 休市日（P7b） | `patch TRADING_HOLIDAYS` 为某周三 ⇒ `_is_trading_hours(该日 10:00)` 为 False；默认空 ⇒ 同刻为 True；`TRADING_HOLIDAYS == frozenset()` | BR-CFG-14 / A3 |
| **CFG-T13** `cache_max` 语义（P7b） | `plate/margin/news_url/longhu` 的 `cache_max is None`（矩阵单元格仍为 `'n/a'`）；`quote/f10/feed/sector` 等为 int；`feed.cache_max == 100` | §10#15 |
| **CFG-T14** backlog 约束（P7b） | `LISTEN_BACKLOG >= MAX_INFLIGHT` 且 `>= MAX_STREAM_CONNS` | E1 |

## 9. AC 追溯矩阵

| 本模块设计点 | 覆盖 AC |
|-------------|---------|
| `cache_policy` 单一权威 + BR-CFG-1/2/6/9 | **AC-A3**（分层新鲜度对齐的前提：两路同源 TTL） |
| 过期语义「拒读 + 回源一次」所需的 ttl 权威值（BR-CFG-2） | **AC-A4** |
| URL 缓存上限 `quote.cache_max=2000` / `limit` 语义 | **AC-E6** |
| `longhu` 域（L4=300s）+ `encoding='gbk'`（BR-CFG-7） | **AC-E9** |
| `NEG_TTL` / `PROBE_TIMEOUT` env（BR-CFG 之外的 §2.3） | **AC-S3** |
| `MGMT_BODY_TIMEOUT=5` / `STREAM_PING_INTERVAL=20` | **AC-S7** |
| `feed.ttl = L3`（D4 收敛，与 `_cache_age()` 同源） | **AC-A8**（TTL 口径同步）、**AC-A3** |
| `MAX_INFLIGHT` / `MAX_GROUPS` / `STREAM_QUEUE_BYTES_BUDGET` / `MAX_HEALTH_INFLIGHT` | E8/E7/E5/S8（消费者模块主责，本模块提供权威值） |
| **`canonical_code` 唯一权威（BR-CFG-13）** | **AC-A6 / AC-A7**（1:1 映射与去重池同一性）/ P1-6 |
| **`TRADING_HOLIDAYS`（BR-CFG-14）** | **AC-A3**（TTL 分层在休市日不按盘中节奏）/ **AC-S4**（CDP 窗口） |
| **`LISTEN_BACKLOG`（BR-CFG-15）** | **AC-E1**（连接长尾 ≤5ms） |
| **`cache_max` URL-only 域归一（§3.1/§10#15）** | **AC-E6**（域缓存有界口径不误导运维） |

---

## 10. 与 SAD / 现有代码的偏差与歧义标注（不擅自改 SAD）

| # | 项 | SAD 表述 | 实际代码 / 本文裁决 | 处置 |
|---|----|---------|-------------------|------|
| 1 | `CACHE_TTL` 消费者 | Q3② 列为「cache.py 默认 ttl、`utils.warm_jin10`、`server._get_or_fetch_feed`」 | `utils.py` 的 `CACHE_TTL` **死 import 已删除**（P7b 实况）；`warm_jin10` 的真实依赖是 `fetch_json(ttl=None)` 默认值 | 已按实际落点补全迁移表（§2.4）；SAD 表述差异登记，不改 SAD |
| 2 | `NEG_TTL = min(5, cache_policy('quote')['ttl'])` | SAD §2.3 | L1 ∈ {8,120} ⇒ 派生值恒为 5，与 env 默认 5 等价 | 采用 env 默认 5 + 派生式注释（§2.3） |
| 3 | 负缓存「过期即清」（§4.3）vs 半开探测需"失败历史"（§2.3） | 两处张力 | 裁决：**门禁**过期即失效（不阻塞）；**条目**保留失败历史直至成功或被上限淘汰（细节见 `cache.md` §4） | 标注，不改 SAD；`cache.md` 给出可断言口径 |
| 4 | `cache_policy` 返回值 `'n/a'` | 示例字面量 | 返回 `None`，矩阵保留 `'n/a'`（§2.1/BR-CFG-11） | 标注，唯一改动点在 `_materialize` |
| 5 | `feed` 返回示例未列 `pool_max` | §2.1 示例 | 键集合固定 5 键恒在（§2.1） | 已统一 |
| 6 | `_BASIC_INFO_POOL_REFRESH` | AR-6 称"现为未用常量" | 验证属实（无引用）；`quote.pool_refresh` 仍定义以备 basic_info 走池 | 直接删，无迁移 |
| 7 | `_MARGIN_CACHE_TTL=600` | 矩阵 `margin` factor 2.0 | `L4(300)×2.0 = 600`，**值不变**，仅为来源收敛 | 已对齐 |
| 8 | **D-4** `STREAM_PING_INTERVAL` env 化 | SAD §3 config 行**未列**该 env（R17 仅记"`STREAM_PING_INTERVAL=20` 写死"） | 提为 env，默认 20 不变（§2.3），消费者 `stream._serve_sse` | 补登本表；编排层已裁决 ✅（待确认 #6），SAD §3 将回填 |
| 9 | **D-5** `_DOMAIN_ENCODING` 新增内部名 | SAD §2.3 D-5 仅提 `encoding` **形参** | 新增模块级名 `_DOMAIN_ENCODING = {'longhu': 'gbk'}`；`DOMAIN_MATRIX` 为**公开名**（供 INV-1a 白盒迭代），运行期为 Python dict（§3 以 YAML 表达） | 实现细化，登记不改 SAD |
| 10 | `_BASIC_INFO_MAX_POOL` 500→2000 | SAD §2.1 `quote` 域 `pool_max='dedup'` | 4× 池上限放大，**行为变更**（§2.4 脚注） | ✓ 已登记，联动 S9/AR-8 |
| 11 | **P7b · `LISTEN_BACKLOG`** | SAD §2.2 R-1 只列 `MAX_INFLIGHT`/`MAX_HEALTH_INFLIGHT`，未列 `listen(2)` backlog | 新增 env，默认 **128**（`socketserver` 默认 5 会在突发连接时丢 SYN ⇒ ~1.006s 长尾，BUG-P6C-03）；消费者 `server.BoundedThreadPoolServer.request_queue_size` | 新增配置项已注册（BR-CFG-15/16）；SAD §3 由 system-architect 回填 |
| 12 | **P7b · `TRADING_HOLIDAYS`** | SAD §2.1/§2.6 未定义休市日概念 | 新增 env（逗号分隔 `YYYY-MM-DD`，默认空），`_is_trading_hours` 中**优先于星期**判定（BR-CFG-14） | 同时惠及 `cdp_engine.watchdog_restart_skip_reason`（休市日允许重启 Chrome）；默认空 ⇒ 行为等价，**非破坏性** |
| 13 | **P7b · `CDP_RESTART_THROTTLE` 注册** | SAD §3 cdp_engine 行未提该 env；`cdp_engine` 旧版自行读 env | 在 config 注册（默认 15），`cdp_engine` 改读 `config.CDP_RESTART_THROTTLE`（BR-CFG-16） | env 注册中心单一权威；避免"同一 env 两处定义、一处生效" |
| 14 | **P7b · `VALID_STOCK_CODE` 消费者与锚定** | SAD §2.1 将其列为代码校验权威 | 保留公开名，但**已不再被 `stream.py` 消费**（流端口经 `canonical_code`）；当前唯一消费者是 `canonical_code`。**建议**（未落地）改 `\Z` 锚定 | `$` 匹配末尾换行前属正则语义细节；`canonical_code` 先 `strip()` ⇒ 生产无逃逸面。属技术债登记，不涉契约 |
| 15 | **P7b · `cache_max` 语义收紧** | SAD §2.1 矩阵对 `plate` 给 200、对 `margin` 给 16 | 实现把二者改为 `'n/a'`⇒`None`：这两域**只走共享 URL 缓存**，per-domain 上限是运维无法生效的死设置 | 语义澄清（BR-CFG-5/§3.1）；`quote`/`f10`/`announcement`/`sector` 等仍给 int。**消费者 `stock_api` 只对 `quote/f10/announcement` 读 `cache_max`**，故无行为回归 |
| 16 | **P7b · `canonical_code` 新增（冻结接口）** | SAD 未定义代码归一函数（仅在 §2.4/§3 隐含"代码校验"） | 新增模块级函数（§2.6）作为**唯一权威**；`server`/`stream`/`stock_api`/`cdp_engine` 均按此名消费 | 消除"同一股票多个身份"（池/缓存/URL 分裂 + CDP 精确比较只匹配一种拼写，P1-6）；属**新增**接口（🟠 STABLE 内），无破坏 |
| 17 | **P7b · `_parse_holidays` 内部名** | 未提 | 新增模块级私有函数（导入期解析，非法日期 `ValueError`） | 实现细化，登记不改 SAD |
| 18 | **v1.3 · 阶梯封顶归属（AC-S3 裁决）** | SAD §2.3 D-1 只说"半开探测用 `PROBE_TIMEOUT`"，未定义阶梯与其上限 | `cache._probe_budget` 的封顶是 **`cache._PROBE_BUDGET_CAP=5.0`（本模块机制常量，不注册 env）**；`REQUEST_TIMEOUT` 只用于无历史/老化两支的全预算探测（§2.3 注） | v1.2 曾记"`REQUEST_TIMEOUT` 为阶梯封顶"——**与实现不符**（`cache.py:84/171`）。⇒ `PROBE_TIMEOUT` 语义不变（仍为 env 可调首级），新增的是 cache 侧机制常量；**config 侧无行为变更、无新增 env** |

> **编排层裁决回执（2026-09-15，6 项）**：#1 `'n/a'`→`None` ✅（本文已按此写）；#2 负缓存「门禁过期失效、条目保留作失败历史」✅（且为 AC-S3 模式 B 必要条件，见 `cache.md` §4.2/§10#1）；#3 feed LRU 落 `cache.py` ✅（`cache.md` §2.4 保持并补双检语义）；#4 metrics 增 `key=`/`reset()` ✅；#5 `cache_hit_ratio` 发布点 ✅（`cache.md` §5.2 补齐实现）；#6 `STREAM_PING_INTERVAL` env 化 ✅（本文 §2.3/§10#8，SAD 将补列）。

> **P7b 契约同步回执（2026-09-16）**：本版 §2.2/§2.3/§2.4/§2.6/§3.1/§3.2/§3.4/§4/§5/§8/§9 已与 `china_finance_rss/config.py` 逐项对齐。**遗留项（不在本 agent 范围，交编排层）**：① 若需 SAD 补齐 `LISTEN_BACKLOG` / `TRADING_HOLIDAYS` / `CDP_RESTART_THROTTLE` 三行 env（§10#11/#12/#13）与 `canonical_code`（§10#16），由 system-architect 回填；② `VALID_STOCK_CODE` 的 `\Z` 锚定属可选技术债（§10#14），当前无实际逃逸面。

## 11. 交付自检

- [x] 无 `{例:` 占位符；所有常量/结构/边界为实值
- [x] 每条 BR 有 SAD 来源（R16/INV-1a/D4/D5/Q3/Q5/AR-6）
- [x] 接口签名精确（参数名/类型/默认/返回键集合/异常）
- [x] 删除常量有唯一迁移目标（file:line）+ **删除前置条件**（同 change-set / 不得单独提前删）
- [x] 行为变更登记：`_BASIC_INFO_MAX_POOL` 500→2000（§2.4 脚注，联动 S9/AR-8）
- [x] AC-S3 口径前提注记（`NEG_TTL` env 覆盖须重跑校准，§2.3）
- [x] 依赖图 `←` 语义澄清（分层顺序 ≠ import，§1.4）
- [x] AC 追溯矩阵覆盖 A3/A4/E6/E9/S3/S7（+A8/E5/E7/E8/S8 的权威值供给）
- [x] §10 偏差登记与详设最新内容一致（含 D-4 `STREAM_PING_INTERVAL`、D-5 `_DOMAIN_ENCODING`）
- [x] **v1.2（P7b）**：`canonical_code` 冻结接口（§2.6/§3.4/BR-CFG-13/CFG-T11）；`TRADING_HOLIDAYS` 休市日（§2.2/§3.4/BR-CFG-14/CFG-T12）；`LISTEN_BACKLOG`(128)/`CDP_RESTART_THROTTLE`(15) 入 §2.3 env 表
- [x] **v1.2（P7b）**：§3.1/§3.2 `plate`/`margin` 的 `cache_max` 已改 `'n/a'`→`null`（BR-CFG-5/§10#15）；§2.4 删除清单标注为**已落地实现态**（前置条件已解除）
- [x] **v1.3（AC-S3 裁决）**：`PROBE_TIMEOUT` 脚注更正为"阶梯首级；封顶 = `cache._PROBE_BUDGET_CAP=5.0`"（§2.3 注 / §10#18）；默认值与 env 面**零变更**




