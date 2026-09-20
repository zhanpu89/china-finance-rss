# config.py 详细设计

> **版本** v1.10 · **状态** 已契约同步（★ v1.10：**PRF-MEM-01 实测回填 + 归因更正**——重建部署 + 五档压测实测（run **20260920-110805**）**证伪**此前乐观预测：python 稳态 RSS 实测 **1.095GiB → 1.012GiB（净收益仅 ~83MiB）**、容器 **1.449GiB/1.5GiB（96.57%）→ 1.41GiB/1.5GiB（93.98%）** ⇒ **本次收缩未达成内存目标**；**归因更正**：终端缓存只是小头，真正大头 = **未收缩的共享 URL 缓存**（`cache.py:35 MAX_CACHE_SIZE=2000`，实测 `cache_entries.url=2000` 顶满）+ 分配器碎片；**接口 / 常量 / 行为零变更**；★ v1.9：**PRF-MEM-01 修复轮**——3 域 `pool_max` 由矩阵字面量改为 **env 可调**（spec 形 `'env:MAX_*_POOL'`，经 `_POOL_MAX_ENVS` 白名单在**调用期**解析为 env 注册常量；新增 3 个 env 常量，默认值即收缩值），`cache_max` 1000/1000/500 **仍为矩阵内整数字面量**（内存硬界，与其余 9 域一致）；**接口 / 返回键集合 / 其余域 / 行为零变更**；★ v1.8：**内存调优 PRF-MEM-01**——`quote`/`fundflow`/`timeline` 的 `pool_max`/`cache_max` **同源收缩**（`config.py` 已落地；余域不变），**接口 / 键集合 / env 零变更**；★ v1.7：**溯源收口 + 引用时点约定**——上游 **SAD v1.12 / PRD v0.10** 复核无变化，本文件为**基础层权威文档**，**无接口/常量/行为变更**；P7b 传输层 + L0/depth + env 注册表补全：以 `china_finance_rss/config.py` 实现为准；★ **v1.6：溯源更正**——上游 SAD/PRD 由 **v1.11/v0.9** 更新为实际 **v1.12/v0.10**，**无接口/常量/行为变更**；★ **v1.5：溯源更正**——上游 SAD/PRD 版本由 v1.2/v0.3 更新为 **v1.11/v0.9**，**无接口/常量/行为变更**）· **日期** 2026-09-20 · **作者/产出** task-decomposer
> **v1.10 变更（PRF-MEM-01 实测回填与归因更正 · 只改文档，不改代码）**：① **实测证伪乐观预测**——重建部署 + 五档压测（run **20260920-110805**）实测：收缩前容器稳态 **1.449GiB / 1.5GiB（96.57%）**、python RSS **1.095GiB**；收缩后容器 **1.41GiB / 1.5GiB（93.98%）**、python RSS **1.012GiB** ⇒ **净收益仅 ~83MiB，本次收缩未达成内存目标**。② **归因更正**——实测反推（`timeline` 1350→500 省 ~82MB + `quote`/`fundflow` 各 −1000 条省 ~10MB ≈ 92MB）与 −83MiB 吻合 ⇒ **终端缓存只是小头**；真正大头 = **未收缩的共享 URL 缓存**（`cache.py:35 MAX_CACHE_SIZE=2000`；实测 `cache_entries.url=2000` 顶满；条目 `{'data': 解析后 Python 对象}` 体积数倍于原始 JSON），其次为线程池 glibc arena 碎片。③ **3 域缓存精确生效（旁证）**——healthz `/healthz?check=0` 实测：`quote`/`fundflow` `pool_max`/`cache_max` = **1000/1000**、`timeline` = **500/500**、`depth` = **500**，与 §3.1/§3.2 契约逐值一致。④ **观测（待复测归因，尚非结论）**——`cache_hit_ratio` **0.1585 → 0.1796**；tier1000 `timeline` `ok_rate` **100% → 89.6%**、`upstream_timeout` **123 → 317**（⚠️ **待复测归因，尚非结论**，不得写成结论）。⑤ **后续方向**——调优**共享 URL 缓存**（`cache.MAX_CACHE_SIZE` 或条目表示），而非继续收缩终端缓存。**本模块接口签名 / 常量 / `cache_policy` 返回值 / env / 行为零变更**（§3/§5 正文逐字不变）；**未改代码 / 测试 / SAD / PRD / API.md / README.md / `.opencode`；`stock_api.md` → v1.8、`_PROGRESS.md` 同步。**
> **v1.9 变更（PRF-MEM-01 修复轮 · 以 `config.py` 实现为准 · 只改文档，不改代码）**：① **CR-02（关键）**——`quote`/`fundflow`/`timeline` 的 `pool_max` 由**矩阵内字面量** `'fixed:1000'`/`'fixed:1000'`/`'fixed:500'` 改为 **`'env:MAX_QUOTE_POOL'`/`'env:MAX_FUNDFLOW_POOL'`/`'env:MAX_TIMELINE_POOL'`**（§3.1/§3.2/§10#24）。**新增 spec 形式 `'env:<NAME>'`**：`_resolve_pool_max` 经白名单 `_POOL_MAX_ENVS = frozenset({'MAX_QUOTE_POOL','MAX_FUNDFLOW_POOL','MAX_TIMELINE_POOL'})` 在**调用期**解析为模块常量（未知 `NAME` ⇒ `ValueError('bad pool_max env name: ...')`，**不静默兜底**）。② **新增 3 个 env 注册常量**（§2.7）：`MAX_QUOTE_POOL=1000` / `MAX_FUNDFLOW_POOL=1000` / `MAX_TIMELINE_POOL=500`——**默认值即 PRF-MEM-01 收缩值** ⇒ 默认行为与 v1.8 逐字等价，而部署可**免改码调参**。③ **`cache_max`（1000/1000/500）仍为矩阵内整数字面量**——它是该域**真实内存硬界**，与其余 9 域一致，不 env 化；`depth` 保持 `'dedup'`(=2000) 是**正确的**（§10#24：`depth` **无 prefetch 循环**，其池仅作 `code→ts` 账本 ~200KB 量级，`cache_max=500` 才是内存界——故"与 `quote` 不对称"仅是表面观感）。④ **BR-CFG-4 扩充** `'env:<NAME>'` 语义；§6 增「未知 env 名 ⇒ `ValueError`」行；§5 伪代码 `_resolve_pool_max` 与 env 清单同步（**编码者唯一依据**）。⑤ **§8 CFG-T19 由"声明"改为"已落地"**：列出实际用例名（CR-02 / CR-03 / CR-04）。**接口签名 / 返回键集合 / 其余 9 域 / 行为零变更**；**未改代码 / SAD / PRD / API.md / README.md / `.opencode`；`stock_api.md` → v1.7、`_PROGRESS.md` 同步。**
> **v1.8 变更（内存调优 PRF-MEM-01 · 以 `config.py` 实现为准 · 只改文档，不改代码）**：`DOMAIN_MATRIX` **3 个域**的 `pool_max`/`cache_max` **同源收缩**——`quote` `'dedup',2000 → 'fixed:1000',1000`、`fundflow` `'dedup',2000 → 'fixed:1000',1000`、`timeline` `'dedup',2000 → 'fixed:500',500`（§3.1/§3.2）；`depth`(`'dedup'`,500)、`announcement`/`f10`(`'dedup'`,500)、`plate`(200)、`feed`(100)、`margin`(16)、`sector`(2000) **不变**。**登记 `PRF-MEM-01`（2026-09-20）见 §10#24**；本模块的 `cache_policy` 签名 / 返回键集合 / env 注册表 / 其余域**零变更**（§5 伪代码逐字不变）。**未改代码 / SAD / PRD / API.md / README.md / `.opencode`；`stock_api.md` → v1.6、`_PROGRESS.md` 同步。**
> **v1.7 变更（溯源收口 + 引用时点约定 · 只改文档，不改代码）**：① **【溯源收口】** 头部上游 **SAD v1.12 / PRD v0.10** 复核确认（v1.6 已对，无变化）。② **【引用时点约定（新增）】** 本文为**基础层权威文档**——本文件版本**以本文件头部为准**；引用本文的各详设（`stock_api` / `cdp_engine` / `market_api` / `stream` / `server`）其「接口权威」栏所列本文版本 = **其最后一次同步时点的快照**，被引文档（含本文）的**权威版本以各自头部为准**——故该栏**落后一版不属漂移、无需每次追平**；**内容以本文件为准，该栏仅用于定位**。**本模块的接口签名 / `DOMAIN_MATRIX` / `cache_policy` 返回值 / env 注册表 / 任何行为零变更**（v1.6 正文逐字保留）；**未改代码 / SAD / PRD / API.md / README.md / `.opencode`；`_PROGRESS.md` 同步。**
> **v1.6 变更（溯源更正 · 只改文档，不改代码）**：仅更正头部**溯源**——上游 **SAD v1.11 → v1.12**（依据 `doc/arch/SAD.md` 头部 `**版本** v1.12`，AC 总数 36）、**PRD v0.9 → v0.10**（依据 `doc/prd/perf-stability-optimization.md` 头部 **v0.10**）。**溯源更正，无内容变更**——本模块的接口签名 / `DOMAIN_MATRIX` / `cache_policy` 返回值 / env 注册表 / 任何行为**均不变**（v1.5 正文逐字保留）；**未改代码 / SAD / PRD / API.md / README.md / `.opencode`；`_PROGRESS.md` 同步。**
> **v1.5 变更（溯源更正 · 只改文档，不改代码）**：头部上游溯源由 **SAD v1.2 / PRD v0.3** 更正为实际版本 **SAD v1.11 / PRD v0.9**——依据 `doc/arch/SAD.md` 头部 `**版本** v1.11` 与 `doc/prd/perf-stability-optimization.md` 头部 **v0.9**（AC 总数 36）。这是 `_PROGRESS.md` 登记的本轮**最后一处**溯源滞后，现已闭环。**本模块的接口签名 / `DOMAIN_MATRIX` / `cache_policy` 返回值 / env 注册表 / 任何行为均不变**（v1.4 正文逐字保留）。**未改代码 / SAD / PRD / API.md / README.md / `.opencode`；`cache.md` → v1.11、`server.md` → v1.12、`_PROGRESS.md` 同步。**
> **v1.4 变更（以代码为准）**：① **新增 L0 档**：`_trading_tiers()` 盘中 `{'L0':4,'L1':8,'L2':12,'L3':30,'L4':300}`，非盘中 `L0=120`；② **`quote` 由 L1 → L0**；**新增 `depth` 域**（L0、`pool_max='dedup'`、`cache_max=500`，与 quote 同拍）；③ **新增 `upstream_secu_code(code)`**（**单一权威**）：内部 canonical → 上游 wire 形（沪/深 = 前缀形 `sh600519`；北交所 = 点号大写形 `430047.BJ`）；`canonical_code` 的内部身份语义不变；④ **env 注册表补全**（§2.3 新增 7 项 + §2.7 全量表）；⑤ 新增 `_STOCK_DEPTH_URL`/`_STOCK_DEPTH_HEADERS`、`_SSE_HOT_PATH_URLS`、`warm_hosts()`；⑥ `DOMAIN_MATRIX` 现 **12 域**（原 11）。
> **v1.3 变更（AC-S3 裁决 · 收尾契约同步）**：① `PROBE_TIMEOUT` 脚注更正——**阶梯封顶不再是 `REQUEST_TIMEOUT`**：`cache._probe_budget` 以 `cache._PROBE_BUDGET_CAP=5.0` 封顶（序列 `2→4→5`），`REQUEST_TIMEOUT(10s)` 仅用于"无失败历史 / 已老化"两支的全预算探测（§2.3 注 + §10#18）。**`PROBE_TIMEOUT` 默认值 2 不变**（仍是阶梯首级）。
> 本版修订（P7b 契约同步，**只改文档、不改代码**）：① 新增 §2.6 **`canonical_code(code)`（冻结接口）**——股票代码归一的唯一权威（`strip + lower + 点号形映射`）；② `_is_trading_hours` 支持**休市日**（env `TRADING_HOLIDAYS`，默认空）；③ 新增 env `LISTEN_BACKLOG(128)` / `TRADING_HOLIDAYS('')` / `CDP_RESTART_THROTTLE(15)`；④ `DOMAIN_MATRIX.cache_max` 语义钉死为**终态/feed 缓存上限**，URL-cache-only 域（`plate`/`margin`/`news_url`/`longhu`）一律 `'n/a'`→`None`；⑤ §2.4 删除清单**已全部落地**（实现态），`VALID_STOCK_CODE` 保留但仅由 `canonical_code` 内部消费（`utils.py` 死 import 已删）。
> 沿用 v1.1：REV-DES-04/06/07/08 + 逆向建议 2（删常量前置条件）+ 编排层裁决 #1/#2/#6 + 偏差 D-4/D-5 登记
> 模块路径 `china_finance_rss/config.py` · 归属 **基础层（Layer 0）**
> 上游 SAD `doc/arch/SAD.md` **v1.12**（★ v1.5 溯源更正：原误记 v1.2；★ **v1.6 溯源更正：v1.11 → v1.12**——权威以 SAD 头部为准）（§2.1 / §2.3 D-1 D-5 / §2.6 / §3 config.py 行 / ADR-001）
> 上游 PRD `doc/prd/perf-stability-optimization.md` **v0.10**（★ v1.5 溯源更正：原误记 v0.3；★ **v1.6 溯源更正：v0.9 → v0.10**——权威以 PRD 头部为准）（AC-A3/A4/E6/E9/S3/S7）
> 端锁定 🟠 STABLE（仅**新增**函数与 env；内部常量删除属 🟡 FLEXIBLE）

## 1. 模块职责与边界

### 1.1 职责（唯一权威）

1. **全系统 TTL / 池刷新间隔 / 池上限 / 端点缓存上限 / 上游编码的单一权威来源** → `cache_policy(domain, now=None)`。
2. **交易时段时间源** → `_is_trading_hours(now=None)` / `_trading_tiers(now=None)`（保留为唯一时间源）；支持**休市日**（env `TRADING_HOLIDAYS`）。
3. **股票代码归一的唯一权威** → `canonical_code(code) -> str | None`（§2.6，**冻结接口**）：把 `sh600519` / `600519.SH` 两种可接受拼写折叠成同一 canonical 形，使同一只股票不会铸出两个池键 / 缓存键 / 上游 URL。
4. **上游 wire 形拼写的唯一权威（P7b）** → `upstream_secu_code(code) -> str`（§2.8）：把内部 canonical 身份转成 x-quote 实际接受的 `secu_code`（沪/深 = `sh600519`；北交所 = `430047.BJ`）。**身份固定、只有 URL 构造转换**。
5. **env 注册中心** → 所有 IO 预算 / 资源上限经 `os.getenv` 注册，默认值不变（兼容）。**★ v1.9**：3 个域池上限**亦经 env 注册**——`MAX_QUOTE_POOL` / `MAX_FUNDFLOW_POOL` / `MAX_TIMELINE_POOL`（默认 **1000/1000/500** = PRF-MEM-01 收缩值，§2.7），由矩阵 spec `'env:<NAME>'` 在**调用期**绑定（§3.1/BR-CFG-4）；`cache_max` 仍为矩阵整数字面量（内存硬界）。
6. **SSE 热路径主机派生** → `warm_hosts()`（§2.9）：从 URL 常量派生 `(scheme, host, port)` 供 `cache.warm_transport` 预热，移动上游不会使预热清单过期。

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
| `domain` | `str` | 是 | — | `DOMAIN_MATRIX` 的键（§3.1 全表，共 **12** 个域） |
| `now` | `float \| None` | 否 | `None` | epoch 秒；交易时段判定注入点。`None` → 使用当前时钟（`time.time()` 语义） |

**返回**：每次调用**新建**的 dict（不得返回共享对象，调用方不得原地修改）。键集合固定（不得增删），`encoding` 条件出现：

| 键 | 类型 | 说明 |
|----|------|------|
| `tier` | `str` | `'L0' \| 'L1' \| 'L2' \| 'L3' \| 'L4'` |
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
def _trading_tiers(now: float | None = None) -> dict   # {'L0':int,'L1':int,'L2':int,'L3':int,'L4':int}
```

- `now` 为**新增可选参数**，`now=None` 行为与现状逐字一致 → 存量调用 `_is_trading_hours()` / `_trading_tiers()` **零改动**。
- 语义（P7b 更新）：`now`（epoch 秒）→ CST（UTC+8）→ **① 若该日期 ∈ `TRADING_HOLIDAYS` ⇒ False（休市日优先于星期判定）**；② 交易日（周一至周五）且 09:30–11:30 或 13:00–15:00。
- **盘中**：`{'L0': 4, 'L1': 8, 'L2': 12, 'L3': 30, 'L4': 300}`；**非盘中**：`{'L0': 120, 'L1': 120, 'L2': 120, 'L3': 180, 'L4': 300}`（P7b 新增 L0；其余档位保持现状口径）。
- **L0 语义（P7b）**：最快档 = 个股五档 + 实时价（`quote`/`depth`）。盘中 4s ≈ 上游实测 3.0s 一跳的 1.3×（4s 轮询仍能看到每次上游变化，同时去掉 8s 的等待浪费）；**非盘中钉在 120s**（与 L1 基线同值），使休市时段不为不动的市场多付请求。
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
| `BATCH_MAX_WORKERS` | **20** | int | `BATCH_MAX_WORKERS` | `stock_api._run_batch` / `stream._refresh_pool`（批相位有界并发） | E2/E5 |
| `STREAM_PER_FETCH_EST` | **0.3** | float（秒） | `STREAM_PER_FETCH_EST` | `stream.refresh_capacity`（BR-STR-16 容量模型） | E2/E5 |
| `HTTP_POOL_MAX_PER_HOST` | **24** | int | `HTTP_POOL_MAX_PER_HOST` | `cache._ConnectionPool`（每 `(scheme,host,port)` 池上限） | E1/E2 |
| `HTTP_POOL_IDLE_TTL` | **60** | float（秒） | `HTTP_POOL_IDLE_TTL` | `cache._ConnectionPool`（空闲连接懒淘汰） | E1 |
| `HTTP_DNS_CACHE_TTL` | **300** | float（秒） | `HTTP_DNS_CACHE_TTL` | `cache._DNSResolver`（`ttl<=0` 关闭缓存） | E1 |
| `HTTP_WARM_CONNECTIONS` | **1** | int | `HTTP_WARM_CONNECTIONS` | `cache.warm_transport`（每 host 预拨号数） | E2 |
| `HTTP_WARM_TIMEOUT` | **2.0** | float（秒） | `HTTP_WARM_TIMEOUT` | `cache.warm_transport`（单次拨号上限） | E2 |

实现要点（逐条，避免编码者发明）：
- `MAX_INFLIGHT` 默认必须**由 `MAX_WORKERS` 派生**（`str(MAX_WORKERS * 2)`），而非写死 `'40'`——使 `MAX_WORKERS` env 改动时默认联动（SAD §2.2 R-1①："把 `max_workers*2` 提为显式配置，使 '40' 不再是隐式推导"）。
- `STREAM_QUEUE_BYTES_BUDGET` env 只接受**整数字节**，不做 `'128MB'` 后缀解析（不引入解析器；SAD 只定默认值 128MB）。
- `NEG_TTL` 默认 `5`：SAD 的派生式 `min(5, cache_policy('quote')['ttl'])` 在**旧 L1 口径**（盘中 8 / 非盘中 120）下恒等于 5；**v1.4 引入 L0（盘中 4）后该派生式盘中会得 4** ⇒ **实现不再采用派生式**，`NEG_TTL` 以 env 默认 **5** 为唯一权威值（与 v1.3 实际行为一致；env 仍是唯一的显式覆盖入口，AR-3）。
  - ⚠️ **REV-DES-08 · AC-S3 口径前提**：SAD §2.3 D-1 与 `cache.md` T-CACHE-4 的稳态推导「`2s(半开探测) + 5s(负缓存) = 7s` 周期、P95 ≤ 3s」**以 `NEG_TTL = 5` 且探测预算恒为 `PROBE_TIMEOUT` 为前提**。env 覆盖 `NEG_TTL` 属**运维变更**：周期变为 `探测预算 + NEG_TTL`，`P95 ≤ 3s` 仅在 `NEG_TTL` 保持同量级时成立 ⇒ **覆盖即须重跑 AC-S3 模式 B 校准**。CI 断言一律按默认值 5 执行（不得注入覆盖）。
  - ⚠️ **P7b 追加前提（★ v1.3 已被下条更正）**：`cache._probe_budget` 的**递增阶梯**（BR-CACHE-22）使"探测预算恒为 2s"不再成立 ⇒ v1.2 曾据此把 **`P95 ≤ 3s` 的成立条件退化为"请求密度相关"**（高峰密度下仍成立；低密度下 P95 ≈ 阶梯当轮预算）。完整量化与三个备选处置见 `cache.md` §10#11。
  - ✅ **AC-S3 裁决（v1.3 更正）**：阶梯**封顶 = `cache._PROBE_BUDGET_CAP = 5.0`**（模块级机制常量，**不注册为 env**），序列为 `2→4→5`；**`REQUEST_TIMEOUT(10s)` 不再是阶梯上限**——它只在"无失败历史"与"失败段已老化（≥`_HISTORY_AGE=600s`）"两支作**一次性全预算探测**（BR-CACHE-5/20/22）。⇒ 持续黑洞稳态 ≈ `5s 探测 + 5s NEG_TTL = 10s` 周期、慢请求占比 ≈50% ⇒ **P95 ≈ 5s**；单请求上界 `≤15s` 仍恒成立。`PROBE_TIMEOUT` 在本表**仍作为阶梯首级（下限）**，**不是**上限。
- `STREAM_PING_INTERVAL` 由硬编码常量改为 env（R17/S7），**默认 20 不变**（AC-S7 的 40s = PING×2 口径不变）。编排层已裁决 ✅ env 化（待确认 #6），SAD §3 config 行将回填（本文登记见 §10#8 / D-4）。
- **`LISTEN_BACKLOG` 默认 128（P7b / BUG-P6C-03，§10#11）**：`socketserver` 默认 backlog = 5，突发连接时内核丢 SYN、客户端 ~1s（RTO）后重传，表现为 AC-E1 的 ~1.006s 长尾。必须 **≥ 它前置的两道准入闸**：主端口 `MAX_INFLIGHT`(=40) 与流端口 `MAX_STREAM_CONNS`(=100) ⇒ 128 同时留出余量。可由 env 覆盖。
- **`TRADING_HOLIDAYS` 默认空（P7b，§10#12）**：见 §2.2；解析在**导入期**完成，非法日期（非 `YYYY-MM-DD`）⇒ `datetime.strptime` 抛 `ValueError` 冒泡（与其他 env 一致的 fail-fast）；空串/全空白 token 被跳过。
- **`CDP_RESTART_THROTTLE` 默认 15（P7b，§10#13）**：注册在本模块，使 `cdp_engine` **不再自行读 env**（env 注册中心单一权威，`code-discipline §6`）；语义为"两次 `ensure_chrome` 启动之间的最小间隔"，并被 `full_chrome_restart` / `watchdog_restart_skip_reason` / `CDPPage._maybe_reconnect` 以 `×2` 用作 back-to-back 护栏。
- **传输 env（P7b 补登，§2.7）**：`BATCH_MAX_WORKERS=20` / `STREAM_PER_FETCH_EST=0.3` 为 SSE 容量模型两个标定输入（`stock_api`/`stream` 在导入期各读一次后保留自己的模块级同名常量）；`HTTP_POOL_MAX_PER_HOST=24` **必须 ≥ `BATCH_MAX_WORKERS`**（否则批扇出会在池上排队，容量模型的 worker 数不可达，BUG-SSE-DEPTH-01）；`HTTP_POOL_IDLE_TTL=60` / `HTTP_DNS_CACHE_TTL=300` / `HTTP_WARM_CONNECTIONS=1` / `HTTP_WARM_TIMEOUT=2.0` 为传输调优项。
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
| `_BASIC_INFO_MAX_POOL` | 500 | config.py:124 | `stock_api.py:29,676` | `cache_policy('quote')['pool_max']` ★**行为变更 500→2000**（★ v1.8 PRF-MEM-01 再收缩 → **1000**；★ v1.9 spec 改经 `'env:MAX_QUOTE_POOL'` 派生、默认 1000；见下表脚注） |
| `_ANNOUNCEMENT_POOL_REFRESH` | 60 | config.py:125 | `stock_api.py:30,739` | `cache_policy('announcement')['pool_refresh']` |
| `_ANNOUNCEMENT_MAX_POOL` | 300 | config.py:126 | `stock_api.py:30,724` | `cache_policy('announcement')['pool_max']` |
| `MAX_FEED_CACHE_SIZE`（cache.py） | 100 | cache.py:149 | `server.py:47,663` | `cache_policy('feed')['cache_max']` |
| `_SECTOR_CACHE_TTL`（stock_api.py） | 604800 | stock_api.py:583 | `stock_api.py:591` | `cache_policy('sector')['ttl']` |

**保留（不动）**：`PORT` `STREAM_PORT` `STREAM_HOST` `CDP_URL` `REQUEST_TIMEOUT` `PUBLIC_BASE_URL` `MAX_WORKERS` `MAX_STREAM_CONNS` `MAX_CODES_PER_SUB` `MAX_DEDUP_CODES` `STREAM_GROUP_IDLE_TTL` `CDP_RESTART_INTERVAL` `_MAX_BATCH_SIZE`(50) `_*_EXPECTED_KEYS` `_*_BASE_URL` `_*_HEADERS` `VALID_STOCK_CODE` `stock_nav_page_names()` `cdp_engine` `jin10_public_headers`。

> ★ **`VALID_STOCK_CODE` 的 P7b 现状（§10#14）**：该正则**保留**，但**已不再被 `stream.py` 消费**（流端口现经 `config.canonical_code` 校验，`test_stream.py` 直接断言源码中不出现 `VALID_STOCK_CODE`）；当前唯一消费者是 `canonical_code` 自身（§2.6）。**建议**（未落地、不强制）：把 `$` 改为 `\Z` 锚定——Python 的 `$` 会匹配**末尾换行之前**，理论上 `'sh600519\n'` 可穿过校验；`canonical_code` 已先 `strip()`，故生产路径无实际逃逸面。`utils.py` 的 `CACHE_TTL` **死 import 已删除**（§10#1）。

> ★ **行为变更登记（REV-DES-06；联动 S9 / AR-8）**：`_BASIC_INFO_MAX_POOL` **500 → `cache_policy('quote')['pool_max']`**（v1.1 取**域口径** `'dedup' = MAX_DEDUP_CODES = 2000` ⇒ 4× 放大；**★ v1.8 PRF-MEM-01 再收缩为 1000**；**★ v1.9 该 spec 由 `'fixed:1000'` 改经 `'env:MAX_QUOTE_POOL'` 派生，默认仍 1000**，见 §10#24）。依据 SAD §2.1——basic_info 与 `/stock/data` 同属 `quote` 域、共享同一去重池。**内存护栏由端点缓存独立 LRU 承担**（`quote.cache_max`：v1.1 = 2000 → **v1.8 = 1000**，见 §3.1），并非静默等价替换：该行计入 **AC-S9 进程内存总账（AR-8）**，编码/评审须核对总账而非按旧值估算。
> ★ **`_BASIC_INFO_POOL_REFRESH`（死常量）**：全仓无引用（AR-6 已登记），**直接删、无迁移**；`quote.pool_refresh` 仍按域定义（= `quote.ttl`），以备 basic_info 走池。

### 2.5 INV-1a 的实现落点

> INV-1a（SAD §2.1）：对任意 domain，`ttl_url(d) == ttl_terminal(d) == cache_policy(d)['ttl']`，且 `pool_refresh(d) >= ttl(d)`；实时域（quote/depth/fundflow/timeline）满足 `ttl(d) <= L1`（v1.4：quote/depth 为 L0=4 ⇒ 严格小于 L1）。

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

- **canonical 形 = 小写交易所前缀拼写**（`sh600519`/`sz000001`/`bj430047`）——它是**内部身份键**（池/缓存/账本键），**不总是上游 `secu_code` 的形态**：x-quote 对沪/深接受前缀形，但北交所只接受点号大写形 `430047.BJ`（见 §2.8 `upstream_secu_code`）。**身份固定、只有 URL 构造转换。**
- **调用方自行决定 `None` 的语义**：HTTP/流端口入口 ⇒ 拒绝（400）；CDP 不匹配 ⇒ 计 `cdp_unavailable`。本函数**不**决定拒绝策略。
- **唯一性约束**：**每一个 ingress、每一个缓存/池/账本键都必须过此函数**（`server._handle_stock_batch` 截断前折叠、`stock_api._process_chunk` 池/缓存/账本键、`stock_api.cached_batch` 查询键、`cdp_engine.navigate_stock`/`_same_code`）。
- **上游 URL 另过 `upstream_secu_code`（§2.8）**：所有 `?secu_code=` 构造点必须经它（`stock_api` 的 basic/detail/fundflow/timeline/depth 共 6+ 处）。
- **响应按请求原拼写回填**：归一只用于内部定位，`build_batch_response` 仍以**请求拼写**为键（`stock_api._process_chunk` 的 `alias` 映射）。
- **幂等**：`canonical_code(canonical_code(x)) == canonical_code(x)`（测试 CFG-T11）。
- **线程安全**：纯函数，无共享可变状态。
- **冻结接口**：`server.py` / `stream.py` 按此名消费；改名属 🔴 FROZEN 变更。

### 2.7 env 注册中心（**全量清单**，P7b 补全）

> 本表是 `config.py` 实际 `os.getenv` 面的**完整**清单（`grep os.getenv china_finance_rss/config.py` 可核对）。§2.3 是"新增/重点项"详表，本节补全此前未列项；**其它模块禁止自行 `os.getenv`**（BR-CFG-16）。

```yaml
# 服务/端口
PORT: 8053 | STREAM_PORT: 8054 | STREAM_HOST: 127.0.0.1 | PUBLIC_BASE_URL: ''
# 上游 CDP
CDP_URL: http://localhost:9222 | CDP_RESTART_INTERVAL: 7200 | CDP_RESTART_THROTTLE: 15
CDP_STOCK_PAGES: 3            # 由 stock_nav_page_names() 在调用期读取（既有唯一例外，非导入期冻结）
# 请求/准入预算
REQUEST_TIMEOUT: 10 | MAX_WORKERS: 20 | MAX_INFLIGHT: MAX_WORKERS*2
MAX_HEALTH_INFLIGHT: 5 | MGMT_BODY_TIMEOUT: 5 | LISTEN_BACKLOG: 128
# 负缓存/半开探测
NEG_TTL: 5 | PROBE_TIMEOUT: 2
# HTTP 传输（cache.fetch_json 唯一出口）
HTTP_POOL_MAX_PER_HOST: 24 | HTTP_POOL_IDLE_TTL: 60.0 | HTTP_DNS_CACHE_TTL: 300.0
HTTP_WARM_CONNECTIONS: 1 | HTTP_WARM_TIMEOUT: 2.0
# SSE 容量模型 / 流端口
BATCH_MAX_WORKERS: 20 | STREAM_PER_FETCH_EST: 0.3
MAX_STREAM_CONNS: 100 | MAX_CODES_PER_SUB: 200 | MAX_DEDUP_CODES: 2000 | MAX_GROUPS: 200
STREAM_PING_INTERVAL: 20 | STREAM_GROUP_IDLE_TTL: 300.0 | STREAM_QUEUE_BYTES_BUDGET: 134217728
# PRF-MEM-01 每域池上限（★ v1.9）—— 由 DOMAIN_MATRIX 的 'env:<NAME>' spec 调用期绑定（白名单 _POOL_MAX_ENVS）
MAX_QUOTE_POOL: 1000 | MAX_FUNDFLOW_POOL: 1000 | MAX_TIMELINE_POOL: 500   # 默认值即 PRF-MEM-01 收缩值
# 压缩
GZIP_MIN_BYTES: 1024 | GZIP_COMPRESSLEVEL: 1
# 交易历
TRADING_HOLIDAYS: ''          # 逗号分隔 YYYY-MM-DD → frozenset[date]
```

> **冻结 vs 调用期读取**：仅 `CDP_STOCK_PAGES` 经 `stock_nav_page_names()` 在**调用期**读取 env（既有唯一例外）；其余全部在**导入期**求值并冻结（BR-CFG-16）。**★ v1.9 细化（`MAX_*_POOL` 三者）**：env 值本身仍在**导入期**冻结；而矩阵 spec `'env:<NAME>'` 的**解析**发生在每次 `cache_policy()` 的**调用期**（`globals()[NAME]`，见 §5 `_resolve_pool_max`）——故热替换模块常量即可生效（`config.MAX_TIMELINE_POOL = 400 ⇒ cache_policy('timeline')['pool_max'] == 400`，CR-02/CR-03）；`NAME` 不在 `_POOL_MAX_ENVS` 白名单 ⇒ `ValueError('bad pool_max env name: ...')`（§6）。

### 2.8 `upstream_secu_code(code) -> str`（**单一权威**，P7b 新增）

```python
def upstream_secu_code(code: str) -> str:
```

**职责**：把内部 canonical 身份转成 x-quote 实际接受的 `secu_code` wire 形（实测 `https://x-quote.cls.cn/quote/stock/{basic,volume,detail}`）：

| canonical 输入 | 返回（wire 形） | 说明 |
|----------------|-----------------|------|
| `sh600519` / `sz000001` | 原样（前缀小写形） | 沪/深；点号形（`600519.SH`）会返回全 null 空壳 |
| `bj430047` / `bj832000` | `430047.BJ` / `832000.BJ` | 北交所；前缀形 `bj430047` 返回空壳（曾使 BSE 报价全空而沪深正常） |
| 非 canonical（无法归一） | **原样返回** | 入口已校验；本函数不抛 |

- **唯一性**：URL 构造是**唯一**转换点；身份（池/缓存/账本键）保持 canonical 不变 ⇒ 一只股票仍只有一个身份（P1-6）。
- **幂等**：`upstream_secu_code(upstream_secu_code(x))` 对合法 canonical 输入保持不变（`430047.BJ` 经 `canonical_code` 折叠回 `bj430047` 再转回）。
- **消费者**（本模块提供、`stock_api` 消费）：`fetch_cls_basic_info` / detail / fundflow / timeline / `fetch_cls_stock_depth` / `_direct_fetch` 等全部 `?secu_code=` 构造点。

### 2.9 `warm_hosts() -> tuple` + SSE 热路径 URL 常量（P7b 新增）

```python
_SSE_HOT_PATH_URLS = (_BASIC_INFO_BASE_URL, _STOCK_DEPTH_URL,
                      _STOCK_DETAIL_BASE_URL, _FUNDFLOW_BASE_URL, _TIMELINE_BASE_URL)

def warm_hosts() -> tuple[tuple[str, str, int], ...]:
    """去重、稳定序地返回热路径上游的 (scheme, hostname, port)。"""

_STOCK_DEPTH_URL    = 'https://x-quote.cls.cn/quote/stock/volume'   # 五档盘口；field=five 取 21 字段
_STOCK_DEPTH_HEADERS = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://www.cls.cn/stock'}
```

- `warm_hosts()` 从 `_SSE_HOT_PATH_URLS` **派生**（URL 常量 = 单一权威）⇒ 移动上游不会让预热清单过期；`cache.warm_transport` 消费。
- 端口缺省按 scheme 推（https→443 / http→80）；同 host 去重；插入序稳定。
---

## 3. 数据结构

### 3.1 `DOMAIN_MATRIX` 全表（公开名，yaml）

```yaml
# domain -> (tier, ttl_factor, pool_refresh_factor, pool_max, cache_max)
# ttl_factor: float | 'override:<秒>'
# pool_refresh_factor: float | 'n/a'
# pool_max: 'dedup'(=MAX_DEDUP_CODES) | 'fixed:<n>' | 'n/a' | 'env:<NAME>'(env 注册常量，白名单 _POOL_MAX_ENVS，调用期解析)
# cache_max: int | 'n/a'      # 终态缓存 / feed 缓存上限；URL-cache-only 域 = 'n/a'（P7b）
DOMAIN_MATRIX:
  quote:        [L0, 1.0,              1.0, 'env:MAX_QUOTE_POOL',      1000]   # ★ v1.4：stock/data, basic_info, 实时价（L1→L0）；★ v1.8 PRF-MEM-01：'dedup',2000 → 1000/1000；★ v1.9：spec 'fixed:1000' → 'env:MAX_QUOTE_POOL'（默认 1000，可免改码调参）
  depth:        [L0, 1.0,              1.0, 'dedup',        500]   # ★ v1.4 新增：五档盘口（与 quote 同拍，独立池/终态上限）；★ v1.9：池保持 'dedup'(=2000) 是**有意**——depth 无 prefetch 循环、池仅 code→ts 账本（~200KB 量级），cache_max=500 才是内存界
  fundflow:     [L1, 1.0,              1.0, 'env:MAX_FUNDFLOW_POOL',   1000]   # ★ v1.8 PRF-MEM-01：'dedup',2000 → 1000/1000；★ v1.9：spec → 'env:MAX_FUNDFLOW_POOL'（默认 1000）
  timeline:     [L1, 1.0,              1.0, 'env:MAX_TIMELINE_POOL',    500]   # ★ v1.8 PRF-MEM-01：'dedup',2000 → 500/500；★ v1.9：spec → 'env:MAX_TIMELINE_POOL'（默认 500）
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
L0:  {trading: 4,   off: 120}
L1:  {trading: 8,   off: 120}
L2:  {trading: 12,  off: 120}
L3:  {trading: 30,  off: 180}
L4:  {trading: 300, off: 300}
# 以下为 trading / off 两组实值（pool_refresh = ttl × factor；'n/a'→null；'dedup'→2000；'fixed:N'→N；'env:<NAME>'→该 env 注册常量，默认 1000/1000/500）
quote:        {tier: L0, ttl: [4,120],     pool_refresh: [4,120],     pool_max: 1000, cache_max: 1000}
depth:        {tier: L0, ttl: [4,120],     pool_refresh: [4,120],     pool_max: 2000, cache_max: 500}
fundflow:     {tier: L1, ttl: [8,120],     pool_refresh: [8,120],     pool_max: 1000, cache_max: 1000}
timeline:     {tier: L1, ttl: [8,120],     pool_refresh: [8,120],     pool_max: 500,  cache_max: 500}
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
> ★ **PRF-MEM-01（v1.8）**：`quote`/`fundflow`/`timeline` 的 `pool_max`/`cache_max` **同源收缩**为 `1000/1000`、`1000/1000`、`500/500`（原均 `2000/2000`）。`pool_max` 与 `cache_max` 同步缩小 ⇒ prefetch（**间隔 = `pool_refresh` = `ttl × refresh_factor`**：`quote`/`depth` 盘中 **4s**、`fundflow`/`timeline` **8s**、非盘 **120s**——★ v1.9 更正：原"`pool_refresh` 120s 轮询"表述为误）保活范围收敛，终端缓存不再长期顶满 `cache_max`；`depth`/`announcement`/`f10` 仍 `'dedup'`⇒`2000`，`plate`(200)/`feed`(100)/`margin`(16)/`sector`(2000) 不变。**★ v1.10 实测（run 20260920-110805）证伪该预期**：python 稳态 RSS **1.095GiB → 1.012GiB（净收益仅 ~83MiB）**、容器 **1.449GiB(96.57%) → 1.41GiB(93.98%)** ⇒ **本次收缩未达成内存目标**；**归因更正**——终端缓存只是小头（`timeline` 1350→500 省 ~82MB + `quote`/`fundflow` 各 −1000 条省 ~10MB ≈ 92MB，与 −83MiB 吻合），**真正大头 = 未收缩的共享 URL 缓存**（`cache.py:35 MAX_CACHE_SIZE=2000`，实测 `cache_entries.url=2000` 顶满；条目 `{'data': 解析后 Python 对象}` 体积数倍于原始 JSON）+ 分配器碎片。详见 §10#24 / §10.1「实测结论」。
> ★ **v1.9（修复轮）**：上表**数值不变**（`pool_max` 1000/1000/500、`cache_max` 1000/1000/500），但 `quote`/`fundflow`/`timeline` 三行的 `pool_max` **改经 `'env:MAX_*_POOL'` 派生**（默认值即上述收缩值）⇒ 部署可**免改码调参**；`cache_max` **仍为矩阵整数字面量**（该域内存硬界）。`depth` 的 `'dedup'` **不动**（无 prefetch 循环、池仅 `code→ts` 账本，`cache_max=500` 才是内存界）。

### 3.3 env 常量（模块级不可变）

见 §2.3 表（+ ★ v1.9：`MAX_QUOTE_POOL`/`MAX_FUNDFLOW_POOL`/`MAX_TIMELINE_POOL`，§2.7），均为模块导入期求值的 `int`（`TRADING_HOLIDAYS` 为 `frozenset[date]`）。**不得在运行期重读 env**（`stock_nav_page_names()` 是既有唯一例外，保留）。**★ v1.9 边界澄清**：`MAX_*_POOL` 的 **env 值**在导入期求值并冻结；矩阵 `'env:<NAME>'` 的**解析**发生在每次 `cache_policy()` 调用期（`globals()[NAME]`）——读的是已冻结的模块常量，**不是**重读 env 环境变量。

### 3.4 代码归一的数据结构（P7b）

```yaml
VALID_STOCK_CODE: <re.Pattern>        # r'^(sh|sz|bj)\d{6}$|^\d{6}\.(BJ|SH|SZ)$', re.IGNORECASE
                                      # 保留公开名；当前唯一消费者 = canonical_code（stream 已迁走）
_DOTTED_STOCK_CODE: <re.Pattern>      # r'^(\d{6})\.(SH|SZ|BJ)$', re.IGNORECASE（canonical 专用）
canonical_form: 小写交易所前缀形       # sh600519 / sz000001 / bj430047（内部身份键）
upstream_wire_form:                   # ★ v1.4：x-quote 的 secu_code 形（仅 URL 构造用）
  sh|sz: 同 canonical（前缀小写形）
  bj:    '<6位>.BJ'（点号大写形）      # 由 upstream_secu_code() 派生
invalid_result: None                  # 非 str / 空 / 空白 / 长度错 / 未知交易所

TRADING_HOLIDAYS: frozenset[datetime.date]   # env 解析结果；默认 frozenset()（空）
_parse_holidays(raw):                         # 逗号分隔 YYYY-MM-DD；空白 token 跳过；
                                              # 非法日期 ⇒ datetime.strptime 抛 ValueError（导入期 fail-fast）

_SSE_HOT_PATH_URLS: tuple[str, ...]           # ★ v1.4：热路径上游 URL 常量（单一权威）
warm_hosts():                                 # ★ v1.4：去重 (scheme, hostname, port) 元组，插入序稳定
```
---

## 4. 业务规则（编号供伪代码与测试引用）

| 编号 | 规则 | 依据 |
|------|------|------|
| **BR-CFG-1** | tier 基值只由 `_trading_tiers(now)` 决定：盘中 `{L1:8,L2:12,L3:30,L4:300}`；非盘中 `{L1:120,L2:120,L3:180,L4:300}`。**盘中判定前置休市日闸**：`now_cst.date() ∈ TRADING_HOLIDAYS` ⇒ 直接返回非交易时段（BR-CFG-14） | SAD §2.1 / PRD §2.3 |
| **BR-CFG-2** | `ttl_factor` 为 `float` → `ttl = int(round(tier_base × factor))`；为 `'override:<n>'` → `ttl = int(n)`，**忽略 tier 基值与时段** | SAD §2.1 sector=7d |
| **BR-CFG-3** | `pool_refresh_factor` 为 `float` → `pool_refresh = int(round(ttl × factor))`，恒 `>= ttl`；为 `'n/a'` → `pool_refresh = None` | INV-1a |
| **BR-CFG-4** | `pool_max == 'dedup'` → `MAX_DEDUP_CODES`（=2000）；`'fixed:<n>'` → `int(n)`；`'n/a'` → `None`；**★ v1.9 `'env:<NAME>'` → 该 env 注册常量**（`NAME` 必须 ∈ `_POOL_MAX_ENVS = frozenset({'MAX_QUOTE_POOL','MAX_FUNDFLOW_POOL','MAX_TIMELINE_POOL'})` 白名单，在**调用期**经 `globals()[NAME]` 取模块常量；不在白名单 ⇒ `ValueError('bad pool_max env name: ...')`，**无静默兜底**） | §4.3 池自洽 / PRF-MEM-01 修复轮（§10#24） |
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
| **BR-CFG-18** | **L0 档（P7b）**：`_trading_tiers()` 盘中 `{'L0':4,...}`、非盘中 `{'L0':120,...}`；L0 = 最快档（`quote`/`depth`，个股五档+实时价），盘中 4s ≈ 上游实测 3.0s 一跳的 1.3×。**L0 是 tier 基值，不改变 `pool_refresh >= ttl` 不变式** | SAD §2.1 分层 / PRD 实时价 |
| **BR-CFG-19** | **`depth` 域（P7b）**：`('L0', 1.0, 1.0, 'dedup', 500)` —— 与 `quote` **同拍（同 tier）**但**自有池与终态缓存上限**（`pool_max=2000` 去重池、`cache_max=500` 终态）；`quote` 同步由 L1 升为 L0 | 五档盘口并入实时价刷新 / SAD §2.1 |
| **BR-CFG-20** | **`upstream_secu_code` 是上游 wire 形的唯一权威（P7b）**：沪/深 = 前缀形（= canonical）；北交所 = `<6位>.BJ`；非 canonical 输入原样返回。**所有 `?secu_code=` 构造点必须经它**；内部身份仍用 `canonical_code`（两者职责分离，禁止混用） | P1-6 / BSE 空壳修复 |
| **BR-CFG-21** | **`warm_hosts()` 从 URL 常量派生（P7b）**：`_SSE_HOT_PATH_URLS` 是单一权威，`warm_hosts()` 去重并稳定排序返回 `(scheme, hostname, port)`；端口缺省按 scheme 推。移动上游不得留下手工主机字面量 | 预热清单不腐烂 / BUG-SSE-DEPTH-01 |

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
# v1.4 补登（传输 + 容量模型，§2.7 全量）
HTTP_POOL_MAX_PER_HOST   = int(os.getenv('HTTP_POOL_MAX_PER_HOST', '24'))
HTTP_POOL_IDLE_TTL       = float(os.getenv('HTTP_POOL_IDLE_TTL', '60'))
HTTP_DNS_CACHE_TTL       = float(os.getenv('HTTP_DNS_CACHE_TTL', '300'))
HTTP_WARM_CONNECTIONS    = int(os.getenv('HTTP_WARM_CONNECTIONS', '1'))
HTTP_WARM_TIMEOUT        = float(os.getenv('HTTP_WARM_TIMEOUT', '2.0'))
BATCH_MAX_WORKERS        = int(os.getenv('BATCH_MAX_WORKERS', '20'))
STREAM_PER_FETCH_EST     = float(os.getenv('STREAM_PER_FETCH_EST', '0.3'))
# v1.9 补登（PRF-MEM-01 池上限，§2.7；由矩阵 'env:<NAME>' spec 调用期绑定）
MAX_QUOTE_POOL           = int(os.getenv('MAX_QUOTE_POOL', '1000'))
MAX_FUNDFLOW_POOL        = int(os.getenv('MAX_FUNDFLOW_POOL', '1000'))
MAX_TIMELINE_POOL        = int(os.getenv('MAX_TIMELINE_POOL', '500'))
_POOL_MAX_ENVS = frozenset({'MAX_QUOTE_POOL', 'MAX_FUNDFLOW_POOL', 'MAX_TIMELINE_POOL'})

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


def upstream_secu_code(code):
    """BR-CFG-20：唯一权威上游 wire 形（沪/深前缀形；北交所点号大写形）。"""
    canon = canonical_code(code)
    if canon is None:
        return code                       # 入口已校验；不抛
    if canon.startswith('bj'):
        return f'{canon[2:]}.BJ'          # bj430047 → 430047.BJ
    return canon                          # sh600519 / sz000001


# 3d) SSE 热路径主机（v1.4，§2.9/BR-CFG-21）
_STOCK_DEPTH_URL = 'https://x-quote.cls.cn/quote/stock/volume'
_SSE_HOT_PATH_URLS = (_BASIC_INFO_BASE_URL, _STOCK_DEPTH_URL, _STOCK_DETAIL_BASE_URL,
                      _FUNDFLOW_BASE_URL, _TIMELINE_BASE_URL)


def warm_hosts():
    """从 _SSE_HOT_PATH_URLS 派生 (scheme, hostname, port)，去重、稳定序。"""
    seen, out = set(), []
    for url in _SSE_HOT_PATH_URLS:
        parsed = urlsplit(url)
        key = (parsed.scheme, parsed.hostname,
               parsed.port or (443 if parsed.scheme == 'https' else 80))
        if key not in seen:
            seen.add(key)
            out.append(key)
    return tuple(out)


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
        return {'L0': 4, 'L1': 8, 'L2': 12, 'L3': 30, 'L4': 300}   # ★ v1.4：新增 L0
    return {'L0': 120, 'L1': 120, 'L2': 120, 'L3': 180, 'L4': 300}
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
    if isinstance(spec, str) and spec.startswith('env:'):     # ★ v1.9 / BR-CFG-4
        name = spec.split(':', 1)[1]
        if name not in _POOL_MAX_ENVS:                        # 白名单：未知 env 名立即失败
            raise ValueError(f'bad pool_max env name: {name!r}')
        return int(globals()[name])                           # 调用期解析 ⇒ 热替换常量即生效
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
| 矩阵 spec 非法（如 `pool_max='fixed:x'`） | `ValueError`（`_resolve_pool_max`，**首次 `cache_policy` 调用期**即暴露） | 编程错误，越早暴露越好 |
| **矩阵 spec `'env:<NAME>'` 的 `NAME` 不在白名单**（★ v1.9） | `ValueError('bad pool_max env name: ...')`（`_resolve_pool_max`，**调用期**） | 拼错的 env 名**绝不静默**回落某个池上限（与 BR-CFG-4「无兜底」一致）；`_POOL_MAX_ENVS` 是唯一合法集合 |
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
| **CFG-T1** policy 一致性白盒 | `for d in DOMAIN_MATRIX:` 断言 `p['ttl'] == p['pool_refresh']`（`pool_refresh is not None` 时 `>=`）；`ttl > 0`；`tier in {L0..L4}`；键集合 == `{tier,ttl,pool_refresh,pool_max,cache_max}` ∪（longhu 的 `encoding`） | A3 |
| **CFG-T2** 实时域 ≤ L0/L1 | 盘中 `cache_policy('quote'/'depth', now=盘中)['ttl'] == 4`（L0）；`fundflow/timeline <= 8`（L1）；非盘中三者 `<= 120` | A3 |
| **CFG-T3** 断崖收敛 | 盘中/非盘中分别断言 `feed.ttl == L3`（30/180）、`quote.ttl == L0`（4/120）、`depth.ttl == L0`、`announcement.ttl == L3`、`longhu.ttl == 300`、`margin.ttl == 600` | A4/E9/E6 |
| **CFG-T4** `now` 注入与边界 | `now` 取 09:30/11:30/13:00/14:59/15:00/周六 → tier 基值符合 BR-CFG-1；`15:00` 判非盘中 | A3 |
| **CFG-T5** 未知域 | `cache_policy('nope')` → `KeyError` 且消息含全部合法域名 | R16 防复发 |
| **CFG-T6** 返回值隔离 | 两次调用 `p1 is not p2`；改 `p1['ttl']` 不影响 `p2` | 线程安全 |
| **CFG-T7** longhu 编码 | `cache_policy('longhu')['encoding'] == 'gbk'`；其余域无 `encoding` 键 | E9 |
| **CFG-T8** `'n/a'` 归一化 | `news_url.pool_max is None`；`longhu.cache_max is None`；矩阵单元格仍为 `'n/a'` | ADR-008 |
| **CFG-T9** env 默认不变 | 无 env 时 `MAX_INFLIGHT == MAX_WORKERS*2`、`MAX_GROUPS==200`、`MGMT_BODY_TIMEOUT==5`、`STREAM_QUEUE_BYTES_BUDGET==134217728`、`NEG_TTL==5`、`PROBE_TIMEOUT==2`、`MAX_HEALTH_INFLIGHT==5`、`STREAM_PING_INTERVAL==20`、`LISTEN_BACKLOG==128`、`CDP_RESTART_THROTTLE==15`、`TRADING_HOLIDAYS==frozenset()`、`HTTP_POOL_MAX_PER_HOST==24`、`HTTP_POOL_IDLE_TTL==60.0`、`HTTP_DNS_CACHE_TTL==300.0`、`HTTP_WARM_CONNECTIONS==1`、`HTTP_WARM_TIMEOUT==2.0`、`BATCH_MAX_WORKERS==20`、`STREAM_PER_FETCH_EST==0.3` | S7/S3/E1/E2 |
| **CFG-T10** 无裸 TTL 字面量 | 对 `cache.py/stock_api.py/market_api.py/server.py/stream.py` 扫描 `ttl=` 实参来源为 `cache_policy(...)` | R16 |
| **CFG-T11** `canonical_code` 归一/幂等（P7b） | 两形等价：`{'sh600519','SH600519','600519.SH','600519.sh'}` → `'sh600519'`；`sz000001`/`000001.SZ` → `'sz000001'`；`bj430047`/`430047.BJ` → `'bj430047'`；**幂等** `canonical_code(canonical_code(x)) == canonical_code(x)`；非法集（非 str/`''`/`'  '`/`'60051'`/`'600519.XX'`/`'us600519'`）→ `None`；**不抛** | BR-CFG-13 |
| **CFG-T12** 休市日（P7b） | `patch TRADING_HOLIDAYS` 为某周三 ⇒ `_is_trading_hours(该日 10:00)` 为 False；默认空 ⇒ 同刻为 True；`TRADING_HOLIDAYS == frozenset()` | BR-CFG-14 / A3 |
| **CFG-T13** `cache_max` 语义（P7b） | `plate/margin/news_url/longhu` 的 `cache_max is None`（矩阵单元格仍为 `'n/a'`）；`quote/f10/feed/sector` 等为 int；`feed.cache_max == 100` | §10#15 |
| **CFG-T14** backlog 约束（P7b） | `LISTEN_BACKLOG >= MAX_INFLIGHT` 且 `>= MAX_STREAM_CONNS` | E1 |
| **CFG-T15** L0 档与 depth 域（v1.4） | `_trading_tiers(盘中) == {'L0':4,'L1':8,'L2':12,'L3':30,'L4':300}`、非盘中 `L0==120`；`quote.tier=='L0'` 且 `depth.tier=='L0'`；`depth.ttl==4/120`、`depth.cache_max==500`、`depth.pool_max==2000`；`DOMAIN_MATRIX` 含 12 个域 | SAD 分层 / E6 |
| **CFG-T16** `upstream_secu_code`（v1.4） | `upstream_secu_code('bj430047')=='430047.BJ'`、`('bj832000')=='832000.BJ'`；`('sh600519')=='sh600519'`、`('sz000001')=='sz000001'`；`('430047.BJ')=='430047.BJ'`（幂等经 canonical）、`('600519.SH')=='sh600519'`；非法输入原样返回且**不抛** | BR-CFG-20 / BSE |
| **CFG-T17** `warm_hosts()`（v1.4） | 返回值 == `(('https','x-quote.cls.cn',443),)`（当前 5 个热路径 URL 同主机 ⇒ 去重为 1 项）；`_SSE_HOT_PATH_URLS` 变更 ⇒ 结果随之变化（从常量派生，无手工字面量） | BR-CFG-21 |
| **CFG-T18** env 全量注册（v1.4） | `grep os.getenv china_finance_rss/config.py` 的 env 名集合 == §2.7 清单；除 `stock_nav_page_names()` 外无调用期读取 | BR-CFG-16 |
| **CFG-T19** PRF-MEM-01 内存收缩（v1.8 **声明** → ★ v1.9 **已落地**；用例总数 514 → **517**） | **已落地用例（3 条）**：① `test_prf_mem_01_pool_cache_contract`（= CFG-T19）——`quote == (config.MAX_QUOTE_POOL, 1000)`、`fundflow == (config.MAX_FUNDFLOW_POOL, 1000)`、`timeline == (config.MAX_TIMELINE_POOL, 500)`、`depth == (config.MAX_DEDUP_CODES, 500)`；且 `plate.pool_max==200`、`feed==100`、`margin==16`、`sector==2000` **不变**（`announcement`/`f10` 仍 `'dedup'`）。② `test_prf_mem_01_pool_cap_follows_env`（**CR-02**）——热替换 `config.MAX_TIMELINE_POOL = 400` ⇒ `cache_policy('timeline')['pool_max'] == 400`（证 `pool_max` **由 env 注册常量经 `'env:<NAME>'` 派生**，非矩阵字面量；用后还原）。③ `test_prf_mem_01_cache_degrade_is_lru_bounded`（**CR-04**，落 `tests/test_data_layer.py`）——锁 `cache_max < 活跃码上界(2000)` 时的**优雅降级**：终端缓存**严格 LRU 有界于 `cache_max`**、最旧条目及其 `cache_ts` **同步淘汰**、最新值**逐字节不变**、写路径**不抛异常**。被引文档 `stock_api.md §3.5` 与之一致 | §10#24 / AC-S9(AR-8) |

## 9. AC 追溯矩阵

| 本模块设计点 | 覆盖 AC |
|-------------|---------|
| `cache_policy` 单一权威 + BR-CFG-1/2/6/9 | **AC-A3**（分层新鲜度对齐的前提：两路同源 TTL） |
| 过期语义「拒读 + 回源一次」所需的 ttl 权威值（BR-CFG-2） | **AC-A4** |
| 端点缓存上限 `quote.cache_max=1000`（★ v1.8 PRF-MEM-01：原 2000）/ `limit` 语义 | **AC-E6** |
| `longhu` 域（L4=300s）+ `encoding='gbk'`（BR-CFG-7） | **AC-E9** |
| `NEG_TTL` / `PROBE_TIMEOUT` env（BR-CFG 之外的 §2.3） | **AC-S3** |
| `MGMT_BODY_TIMEOUT=5` / `STREAM_PING_INTERVAL=20` | **AC-S7** |
| `feed.ttl = L3`（D4 收敛，与 `_cache_age()` 同源） | **AC-A8**（TTL 口径同步）、**AC-A3** |
| `MAX_INFLIGHT` / `MAX_GROUPS` / `STREAM_QUEUE_BYTES_BUDGET` / `MAX_HEALTH_INFLIGHT` | E8/E7/E5/S8（消费者模块主责，本模块提供权威值） |
| **`canonical_code` 唯一权威（BR-CFG-13）** | **AC-A6 / AC-A7**（1:1 映射与去重池同一性）/ P1-6 |
| **`TRADING_HOLIDAYS`（BR-CFG-14）** | **AC-A3**（TTL 分层在休市日不按盘中节奏）/ **AC-S4**（CDP 窗口） |
| **`LISTEN_BACKLOG`（BR-CFG-15）** | **AC-E1**（连接长尾 ≤5ms） |
| **`cache_max` URL-only 域归一（§3.1/§10#15）** | **AC-E6**（域缓存有界口径不误导运维） |
| **L0 档 + `depth` 域（v1.4 / BR-CFG-18/19）** | 实时价/五档同拍刷新（SSE L0 tick=4s）/ **AC-E6**（`depth.cache_max=500`） |
| **`upstream_secu_code`（v1.4 / BR-CFG-20）** | 北交所报价/五档不再空壳（BSE wire 形）/ P1-6 |
| **`warm_hosts()`（v1.4 / BR-CFG-21）** | **AC-E2**（`cache.warm_transport` 冷进程预热清单不腐烂） |
| **传输 env（v1.4 / §2.3·§2.7）** | **AC-E1/E2**（池/空闲 TTL/DNS TTL/预热参数为 `cache` 侧的权威值供给） |

---

## 10. 与 SAD / 现有代码的偏差与歧义标注（不擅自改 SAD）

| # | 项 | SAD 表述 | 实际代码 / 本文裁决 | 处置 |
|---|----|---------|-------------------|------|
| 1 | `CACHE_TTL` 消费者 | Q3② 列为「cache.py 默认 ttl、`utils.warm_jin10`、`server._get_or_fetch_feed`」 | `utils.py` 的 `CACHE_TTL` **死 import 已删除**（P7b 实况）；`warm_jin10` 的真实依赖是 `fetch_json(ttl=None)` 默认值 | 已按实际落点补全迁移表（§2.4）；SAD 表述差异登记，不改 SAD |
| 2 | `NEG_TTL = min(5, cache_policy('quote')['ttl'])` | SAD §2.3 | 旧 L1 口径下派生值恒为 5；**v1.4 `quote` 升 L0（盘中 4）后派生式会得 4** ⇒ 实现以 env 默认 **5** 为唯一权威（不再采用派生式） | 采用 env 默认 5 + 本注（§2.3） |
| 3 | 负缓存「过期即清」（§4.3）vs 半开探测需"失败历史"（§2.3） | 两处张力 | 裁决：**门禁**过期即失效（不阻塞）；**条目**保留失败历史直至成功或被上限淘汰（细节见 `cache.md` §4） | 标注，不改 SAD；`cache.md` 给出可断言口径 |
| 4 | `cache_policy` 返回值 `'n/a'` | 示例字面量 | 返回 `None`，矩阵保留 `'n/a'`（§2.1/BR-CFG-11） | 标注，唯一改动点在 `_materialize` |
| 5 | `feed` 返回示例未列 `pool_max` | §2.1 示例 | 键集合固定 5 键恒在（§2.1） | 已统一 |
| 6 | `_BASIC_INFO_POOL_REFRESH` | AR-6 称"现为未用常量" | 验证属实（无引用）；`quote.pool_refresh` 仍定义以备 basic_info 走池 | 直接删，无迁移 |
| 7 | `_MARGIN_CACHE_TTL=600` | 矩阵 `margin` factor 2.0 | `L4(300)×2.0 = 600`，**值不变**，仅为来源收敛 | 已对齐 |
| 8 | **D-4** `STREAM_PING_INTERVAL` env 化 | SAD §3 config 行**未列**该 env（R17 仅记"`STREAM_PING_INTERVAL=20` 写死"） | 提为 env，默认 20 不变（§2.3），消费者 `stream._serve_sse` | 补登本表；编排层已裁决 ✅（待确认 #6），SAD §3 将回填 |
| 9 | **D-5** `_DOMAIN_ENCODING` 新增内部名 | SAD §2.3 D-5 仅提 `encoding` **形参** | 新增模块级名 `_DOMAIN_ENCODING = {'longhu': 'gbk'}`；`DOMAIN_MATRIX` 为**公开名**（供 INV-1a 白盒迭代），运行期为 Python dict（§3 以 YAML 表达） | 实现细化，登记不改 SAD |
| 10 | `_BASIC_INFO_MAX_POOL` 500→2000 | SAD §2.1 `quote` 域 `pool_max='dedup'` | 4× 池上限放大，**行为变更**（§2.4 脚注） | ✓ 已登记，联动 S9/AR-8（★ v1.8：该口径已由 **§10#24 PRF-MEM-01** 更新——`quote` 池/缓存再收缩为 **1000/1000**） |
| 11 | **P7b · `LISTEN_BACKLOG`** | SAD §2.2 R-1 只列 `MAX_INFLIGHT`/`MAX_HEALTH_INFLIGHT`，未列 `listen(2)` backlog | 新增 env，默认 **128**（`socketserver` 默认 5 会在突发连接时丢 SYN ⇒ ~1.006s 长尾，BUG-P6C-03）；消费者 `server.BoundedThreadPoolServer.request_queue_size` | 新增配置项已注册（BR-CFG-15/16）；SAD §3 由 system-architect 回填 |
| 12 | **P7b · `TRADING_HOLIDAYS`** | SAD §2.1/§2.6 未定义休市日概念 | 新增 env（逗号分隔 `YYYY-MM-DD`，默认空），`_is_trading_hours` 中**优先于星期**判定（BR-CFG-14） | 同时惠及 `cdp_engine.watchdog_restart_skip_reason`（休市日允许重启 Chrome）；默认空 ⇒ 行为等价，**非破坏性** |
| 13 | **P7b · `CDP_RESTART_THROTTLE` 注册** | SAD §3 cdp_engine 行未提该 env；`cdp_engine` 旧版自行读 env | 在 config 注册（默认 15），`cdp_engine` 改读 `config.CDP_RESTART_THROTTLE`（BR-CFG-16） | env 注册中心单一权威；避免"同一 env 两处定义、一处生效" |
| 14 | **P7b · `VALID_STOCK_CODE` 消费者与锚定** | SAD §2.1 将其列为代码校验权威 | 保留公开名，但**已不再被 `stream.py` 消费**（流端口经 `canonical_code`）；当前唯一消费者是 `canonical_code`。**建议**（未落地）改 `\Z` 锚定 | `$` 匹配末尾换行前属正则语义细节；`canonical_code` 先 `strip()` ⇒ 生产无逃逸面。属技术债登记，不涉契约 |
| 15 | **P7b · `cache_max` 语义收紧** | SAD §2.1 矩阵对 `plate` 给 200、对 `margin` 给 16 | 实现把二者改为 `'n/a'`⇒`None`：这两域**只走共享 URL 缓存**，per-domain 上限是运维无法生效的死设置 | 语义澄清（BR-CFG-5/§3.1）；`quote`/`f10`/`announcement`/`sector` 等仍给 int。**消费者 `stock_api` 只对 `quote/f10/announcement` 读 `cache_max`**，故无行为回归 |
| 16 | **P7b · `canonical_code` 新增（冻结接口）** | SAD 未定义代码归一函数（仅在 §2.4/§3 隐含"代码校验"） | 新增模块级函数（§2.6）作为**唯一权威**；`server`/`stream`/`stock_api`/`cdp_engine` 均按此名消费 | 消除"同一股票多个身份"（池/缓存/URL 分裂 + CDP 精确比较只匹配一种拼写，P1-6）；属**新增**接口（🟠 STABLE 内），无破坏 |
| 17 | **P7b · `_parse_holidays` 内部名** | 未提 | 新增模块级私有函数（导入期解析，非法日期 `ValueError`） | 实现细化，登记不改 SAD |
| 18 | **v1.3 · 阶梯封顶归属（AC-S3 裁决）** | SAD §2.3 D-1 只说"半开探测用 `PROBE_TIMEOUT`"，未定义阶梯与其上限 | `cache._probe_budget` 的封顶是 **`cache._PROBE_BUDGET_CAP=5.0`（本模块机制常量，不注册 env）**；`REQUEST_TIMEOUT` 只用于无历史/老化两支的全预算探测（§2.3 注） | v1.2 曾记"`REQUEST_TIMEOUT` 为阶梯封顶"——**与实现不符**（`cache.py:84/171`）。⇒ `PROBE_TIMEOUT` 语义不变（仍为 env 可调首级），新增的是 cache 侧机制常量；**config 侧无行为变更、无新增 env** |
| 19 | **v1.4 · L0 档** | SAD §2.1 分层为 L1..L4（无 L0） | 新增 `L0`（盘中 4 / 非盘中 120），`quote` 由 L1 升 L0（BR-CFG-18） | 上游实测 3.0s 一跳；L0 使实时价同拍刷新，非盘中钉 120s 不多付请求 |
| 20 | **v1.4 · `depth` 域** | SAD §2.1 矩阵无 `depth`（五档盘口在实现中并入 quote 拍） | 新增 `depth` 行 `('L0',1.0,1.0,'dedup',500)`：与 quote 同 tier、**自有池与终态上限**（BR-CFG-19） | 五档与实时价同拍但生命周期/容量不同 ⇒ 独立域；`stock_api._basic_depth_pool/_basic_depth_cache` 消费其 `pool_max`/`cache_max`（不再是死设置，P2-9） |
| 21 | **v1.4 · `upstream_secu_code`（单一权威）** | SAD §2.1 只说 `canonical_code` 归一；未区分"内部身份"与"上游 wire 形" | 新增函数（§2.8/BR-CFG-20）：沪/深=前缀形；**北交所=点号大写形 `430047.BJ`**；非 canonical 原样返回 | 北交所前缀形返回全 null 空壳（BSE 报价全空而沪深正常）；身份固定、只 URL 构造转换 ⇒ 不破坏"一股票一身份" |
| 22 | **v1.4 · 传输/容量 env 补登** | SAD §3 config 行未列 `BATCH_MAX_WORKERS`/`STREAM_PER_FETCH_EST`/`HTTP_POOL_*`/`HTTP_DNS_CACHE_TTL`/`HTTP_WARM_*` | 已在实现中注册（§2.3 + §2.7 全量清单/BR-CFG-16） | env 注册中心完整可核对；SAD §3 由 system-architect 回填 |
| 23 | **v1.4 · `_SSE_HOT_PATH_URLS`/`warm_hosts()`/`_STOCK_DEPTH_URL`** | SAD 未定义传输预热清单 | 新增（§2.9/BR-CFG-21）：从 URL 常量派生主机键，供 `cache.warm_transport` | 手工主机字面量会与上游常量脱钩 ⇒ 预热失效（冷启动 ~4.2s 扇出） |
| 24 | **v1.8 · PRF-MEM-01 内存调优（3 域 pool/cache 同源收缩）**；**★ v1.9 · 修复轮：池上限 env 化** | SAD §2.1 矩阵与 §4.3/AR-8 内存总账对 `quote`/`fundflow`/`timeline` 按 `'dedup'=2000`、`cache_max=2000` 估算 | **v1.8**：3 域收缩为 `pool_max`/`cache_max` = **1000/1000、1000/1000、500/500**（§3.1/§3.2）；`depth`/`announcement`/`f10` 仍 `'dedup'⇒MAX_DEDUP_CODES=2000`，`plate`/`feed`/`margin`/`sector` **不变**。**★ v1.9（修复轮）**：3 域 `pool_max` 的 spec 由 `'fixed:N'` 改为 **`'env:MAX_*_POOL'`**（`_resolve_pool_max` 经 `_POOL_MAX_ENVS` 白名单在**调用期**解析，未知名 ⇒ `ValueError`）——即 **pool 可调（env）、`cache_max` 为硬界（矩阵字面量）**：`MAX_QUOTE_POOL=1000` / `MAX_FUNDFLOW_POOL=1000` / `MAX_TIMELINE_POOL=500`（默认值 = 上述收缩值 ⇒ **默认行为不变**，部署可免改码调参）。**`depth` 池保持 `'dedup'` 是正确设计**（**无 prefetch 循环** ⇒ 池不被轮转无限触碰，仅作 `code→ts` 账本 ~200KB 量级；`cache_max=500` 才是内存界）——消除"与 `quote` 不对称"的表面观感 | **PRF-MEM-01（2026-09-20）**：压测显示容器内存 **96.57%** 高水位；**原归因（v1.8/v1.9 假设 · ★ v1.10 实测已更正）** = 终态缓存被灌满至 `cache_max` + `timeline` 单条 ~96KB（内存大户）+ prefetch（**间隔 = `pool_refresh` = `ttl × refresh_factor`**：`quote`/`depth` 盘中 **4s**、`fundflow`/`timeline` **8s**、非盘 **120s**——★ v1.9 更正原"`pool_refresh` 120s 轮询"误述）保活使 LRU 不淘汰；处置 = 3 域 `pool_max`/`cache_max` **同源收缩**使保活范围收敛。**★ v1.10 实测回填（run 20260920-110805）**：python 稳态 RSS **1.095GiB → 1.012GiB（净收益仅 ~83MiB）**、容器 **1.449GiB(96.57%) → 1.41GiB(93.98%)** ⇒ **本次收缩未达成内存目标**；**归因更正**：终端缓存只是小头，真正大头 = **未收缩的共享 URL 缓存**（`cache.MAX_CACHE_SIZE=2000`）+ 分配器碎片（详见下「实测结论」）。**SAD 侧 §2.1/§4.3/AR-8 数值由 system-architect 回填**（本 agent 不改 SAD） |

### 10.1 ★ PRF-MEM-01 实测结论（v1.10 回填 · run 20260920-110805）

> 背景：PRF-MEM-01 修复轮（v1.9）后容器已**重建部署**并做**五档压测实测**。本节回填实测值，**更正此前文档中的乐观预测**（原文「预期 python 稳态 RSS ~1.1GiB → ~0.65GiB」为**估算值，已被实测证伪**）。

**1. 实测事实（权威）**

| 指标 | 收缩前 | 收缩后（实测） | 净变化 |
|------|--------|----------------|--------|
| 容器稳态 | **1.449GiB / 1.5GiB（96.57%）** | **1.41GiB / 1.5GiB（93.98%）** | −~39MiB |
| python 稳态 RSS | **1.095GiB** | **1.012GiB** | **−~83MiB** |
| `cache_hit_ratio` | 0.1585 | **0.1796** | +0.0211 |

- **结论：本次收缩未达成内存目标**（原预期降至 ~0.65GiB，实测仅 −83MiB）。
- **3 域缓存精确生效（旁证）**——healthz `/healthz?check=0` 实测：`quote`/`fundflow` `pool_max`/`cache_max` = **1000/1000**、`timeline` = **500/500**、`depth` = **500**，与 §3.1/§3.2 契约逐值一致。

**2. 归因更正（实测反推）**

- 实测反推：`timeline` 1350→500 省 **~82MB** + `quote`/`fundflow` 各 −1000 条省 **~10MB** ≈ **92MB**，与实测 −83MiB **吻合** ⇒ **终端缓存只是小头**。
- **真正大头 = 未收缩的共享 URL 缓存**：`cache.py:35 MAX_CACHE_SIZE = 2000`；实测 `cache_entries.url = 2000` **顶满**；其条目形如 `{'data': 解析后的 Python 对象}`，**体积数倍于原始 JSON** ⇒ 是内存主体。
- 其次为**线程池 glibc arena 碎片**（分配器不归还）。

**3. 观测（⚠️ 待复测归因，尚非结论）**

- tier1000 压测中 `timeline` `ok_rate` **100% → 89.6%**、`upstream_timeout` **123 → 317**。
- **待复测归因，尚非结论**——不得据此断言为收缩导致的退化；需复测 + 归因后再定论。

**4. 后续方向**

- **调优共享 URL 缓存**（`cache.MAX_CACHE_SIZE` 或缓存条目表示方式），而非继续收缩终端缓存；`cache.md` 侧改动须另立 change-set（**本轮不改代码**）。

> **编排层裁决回执（2026-09-15，6 项）**：#1 `'n/a'`→`None` ✅（本文已按此写）；#2 负缓存「门禁过期失效、条目保留作失败历史」✅（且为 AC-S3 模式 B 必要条件，见 `cache.md` §4.2/§10#1）；#3 feed LRU 落 `cache.py` ✅（`cache.md` §2.4 保持并补双检语义）；#4 metrics 增 `key=`/`reset()` ✅；#5 `cache_hit_ratio` 发布点 ✅（`cache.md` §5.2 补齐实现）；#6 `STREAM_PING_INTERVAL` env 化 ✅（本文 §2.3/§10#8，SAD 将补列）。

> **P7b 契约同步回执（2026-09-16）**：本版 §2.2/§2.3/§2.4/§2.6/§3.1/§3.2/§3.4/§4/§5/§8/§9 已与 `china_finance_rss/config.py` 逐项对齐。**遗留项（不在本 agent 范围，交编排层）**：① 若需 SAD 补齐 `LISTEN_BACKLOG` / `TRADING_HOLIDAYS` / `CDP_RESTART_THROTTLE` 三行 env（§10#11/#12/#13）与 `canonical_code`（§10#16），由 system-architect 回填；② `VALID_STOCK_CODE` 的 `\Z` 锚定属可选技术债（§10#14），当前无实际逃逸面。

> **v1.4 契约同步回执（2026-09-17，以 `config.py` 为准）**：§2.2（L0）/§2.6（身份 vs wire）/§2.7（env 全量）/§2.8（`upstream_secu_code`）/§2.9（`warm_hosts`）/§3.1·§3.2（`quote`→L0 + `depth`）/§3.4/§4 BR-CFG-18..21/§5/§8 CFG-T15..T18/§9/§10#19..23 已对齐。**遗留项（交编排层/system-architect）**：SAD §2.1 补 L0 档与 `depth` 域、§2.8 `upstream_secu_code`、§3 config 行补传输/容量 env（§10#19..22）。

## 11. 交付自检

- [x] 无 `{例:` 占位符；所有常量/结构/边界为实值
- [x] 每条 BR 有 SAD 来源（R16/INV-1a/D4/D5/Q3/Q5/AR-6）
- [x] 接口签名精确（参数名/类型/默认/返回键集合/异常）
- [x] 删除常量有唯一迁移目标（file:line）+ **删除前置条件**（同 change-set / 不得单独提前删）
- [x] 行为变更登记：`_BASIC_INFO_MAX_POOL` 500→2000（★ v1.8 PRF-MEM-01 再收缩 → **1000**；§2.4 脚注，联动 S9/AR-8）
- [x] AC-S3 口径前提注记（`NEG_TTL` env 覆盖须重跑校准，§2.3）
- [x] 依赖图 `←` 语义澄清（分层顺序 ≠ import，§1.4）
- [x] AC 追溯矩阵覆盖 A3/A4/E6/E9/S3/S7（+A8/E5/E7/E8/S8 的权威值供给）
- [x] §10 偏差登记与详设最新内容一致（含 D-4 `STREAM_PING_INTERVAL`、D-5 `_DOMAIN_ENCODING`）
- [x] **v1.2（P7b）**：`canonical_code` 冻结接口（§2.6/§3.4/BR-CFG-13/CFG-T11）；`TRADING_HOLIDAYS` 休市日（§2.2/§3.4/BR-CFG-14/CFG-T12）；`LISTEN_BACKLOG`(128)/`CDP_RESTART_THROTTLE`(15) 入 §2.3 env 表
- [x] **v1.2（P7b）**：§3.1/§3.2 `plate`/`margin` 的 `cache_max` 已改 `'n/a'`→`null`（BR-CFG-5/§10#15）；§2.4 删除清单标注为**已落地实现态**（前置条件已解除）
- [x] **v1.3（AC-S3 裁决）**：`PROBE_TIMEOUT` 脚注更正为"阶梯首级；封顶 = `cache._PROBE_BUDGET_CAP=5.0`"（§2.3 注 / §10#18）；默认值与 env 面**零变更**
- [x] **v1.4**：L0 档 + `quote`→L0 + `depth` 域（§2.2/§3.1/§3.2/BR-CFG-18/19/§10#19·20；CFG-T15）
- [x] **v1.4**：`upstream_secu_code` 单一权威（§2.8/§3.4/BR-CFG-20/CFG-T16；§2.6 身份 vs wire 措辞更正）
- [x] **v1.4**：env 注册表补全（§2.3 补 7 项 + §2.7 全量清单/BR-CFG-16/CFG-T18）与 `_SSE_HOT_PATH_URLS`/`warm_hosts()`/`_STOCK_DEPTH_URL`（§2.9/BR-CFG-21/CFG-T17）
- [x] **v1.5（溯源更正）**：头部上游版本由 **SAD v1.2 / PRD v0.3** 更正为 **SAD v1.11 / PRD v0.9**（`_PROGRESS.md` 登记的最后一处溯源滞后，闭环）；**接口 / `DOMAIN_MATRIX` / `cache_policy` 返回值 / env 注册表 / 任何行为零变更**（v1.4 正文逐字保留）
- [x] **v1.6（溯源更正）**：头部上游版本由 **SAD v1.11 / PRD v0.9** 更新为实际 **SAD v1.12 / PRD v0.10**（AC 总数 36）；**溯源更正，无内容变更**——**接口 / `DOMAIN_MATRIX` / `cache_policy` 返回值 / env 注册表 / 任何行为零变更**（v1.5 正文逐字保留）；**未改代码 / SAD / PRD / API.md / README.md / `.opencode`**
- [x] **v1.7（溯源收口 + 引用时点约定）**：上游 **SAD v1.12 / PRD v0.10** 复核无变化；本文为**基础层权威文档**（版本以本文件头部为准），新增「引用时点约定」——引用本文的详设其接口权威栏 = 其最后同步时点快照、**落后一版不属漂移**，内容以本文件为准。**接口 / 常量 / 行为零变更**；**未改代码 / SAD / PRD / API.md / README.md / `.opencode`**
- [x] **v1.8（PRF-MEM-01 内存调优）**：§3.1/§3.2 `quote`/`fundflow`/`timeline` 的 `pool_max`/`cache_max` 收缩为 **1000/1000、1000/1000、500/500**（余域不变）；§2.4 脚注 / §9 / §10#24 / CFG-T19 登记；**接口签名 / 返回键集合 / env 零变更**（§5 伪代码逐字不变）；**未改代码 / SAD / PRD / API.md / README.md / `.opencode`**
- [x] **v1.9（PRF-MEM-01 修复轮 · CR-02）**：3 域 `pool_max` spec 改 `'env:MAX_*_POOL'`（§3.1/§3.2/§10#24）；新增 §2.7 env 3 行（默认 1000/1000/500）+ §1.1#5 补注；**BR-CFG-4 扩充** `'env:<NAME>'`（白名单 + 调用期解析 + 未知名 `ValueError`）；**§6 增"未知 env 名"行**；**§5 伪代码 `_resolve_pool_max` 与 env 清单同步**（这是编码者唯一依据）；**CFG-T19 由"声明"改为"已落地"**（列出 3 个真实用例名，总数 514 → **517**）；**`cache_max` 仍矩阵字面量**（内存硬界）、**`depth` 保持 `'dedup'` 的理由已写明**（无 prefetch 循环、池仅账本）；★ 顺带更正 §3.2/§10#24 的 **prefetch 间隔误述**（= `pool_refresh` = `ttl × refresh_factor`）与 **`~0.65GiB` 标注为估算待实测**。**接口签名 / 返回键集合 / 其余 9 域 / 行为零变更**；**未改代码 / SAD / PRD / API.md / README.md / `.opencode`**
- [x] **v1.10（PRF-MEM-01 实测回填与归因更正）**：§3.2 注 / §10#24（+ 新增 **§10.1「实测结论」**）回填五档压测实测（run **20260920-110805**）——python RSS **1.095GiB → 1.012GiB（−83MiB）**、容器 **1.449GiB(96.57%) → 1.41GiB(93.98%)**，**明确「本次收缩未达成内存目标」**；**归因更正**为「终端缓存只是小头，真正大头 = 共享 URL 缓存 `cache.MAX_CACHE_SIZE=2000` + 分配器碎片」；旁证 3 域缓存精确生效（healthz `?check=0`）；tier1000 `timeline` 退化**标注"待复测归因，尚非结论"**。**接口 / 常量 / 行为零变更**；**未改代码 / 测试 / SAD / PRD / API.md / README.md / `.opencode`；`stock_api.md` → v1.8、`_PROGRESS.md` 同步。**




