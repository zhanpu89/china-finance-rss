# market_api.py 详细设计

> **版本** v1.9 · **状态** 已契约同步（★ v1.9：**PRF-LAT-02 P2 收尾（CR-02）**——margin 终端缓存的**命中路径与写入/淘汰路径**均新增**锁外**发布 `metrics.set_gauge('cache_entries', len(_margin_cache), key='margin')`（**锁内只取长度**，对齐 `stock_api._cache_store` 的「锁内取标量、锁外发布」纪律 / BR-SA-16·BR-SA-26）；模块 docstring 把过时的 "fetching goes through ``cache.fetch_json`` only" 改为如实表述——`fetch_json` 仍为**唯一 HTTP 出口**，但 TTL 新鲜的**终端缓存命中不再调用它**；新增用例 `test_terminal_cache_publishes_cache_entries_gauge`（写后 ==1 / 命中后仍 ==1 / LRU 淘汰后 == `cache_max`）⇒ 用例 **525 → 526**；`metrics.md` → **v1.11**（§3.2 `cache_entries` 标签枚举补 `margin`）；★ v1.8：**PRF-LAT-02 margin 终端缓存**——新增模块内**终端缓存** `_margin_cache`(OrderedDict) / `_margin_cache_ts` / `_margin_cache_lock`；`fetch_margin` 新流程 = 参数校验 + `deadline` 入口闸 → **终端缓存命中直接返回**（LRU `move_to_end`，**不解析、不计数**）→ 未命中才 `metrics.incr('upstream_fetch_total', key='margin')` + `fetch_json`/`json.loads`/`_transform_margin` → **仅当 `latest is not None`** 才写缓存并按 `cache_max`(8) LRU 淘汰（同步删 ts）；**失败 / 空数据不写缓存**；§3.3 `margin.cache_max` 由 `null` → **`8`**（`config.md` v1.14 同批）；`upstream_fetch_total{margin}` 语义由"每次 handler 调用 +1"→"**仅终端缓存 miss 时 +1**"（与 stock 域「终端 miss 才调 fetcher → 计数」对齐）；★ v1.7：**溯源收口 + 引用时点约定**——上游 SAD v1.12 / PRD v0.10（已对），基础层接口权威 **config v1.6 / cache v1.14 / metrics v1.8**；**无内容变更**；★ v1.6：溯源更正——上游 SAD v1.12 / PRD v0.10；★ v1.5：REV-DES-20 收口——`metrics.md` §3.2 owner 列已补 `market_api`；P7b 传输层批次：以 `china_finance_rss/market_api.py` 实现为准）· **日期** 2026-09-18 · **作者/产出** task-decomposer
> **v1.9 变更（PRF-LAT-02 P2 收尾（CR-02）· 只改文档，不改代码）**：① **终端缓存可观测（新增）**——`cache_entries{margin}` 的发布此前**缺失**（v1.8 只做了终端缓存的读写与 miss 计数，**未把 `len(_margin_cache)` 发布到 metrics**）；本轮在 `fetch_margin` 的**命中路径与写入/淘汰路径**各补一处 **锁外** `metrics.set_gauge('cache_entries', entries, key='margin')`（`entries = len(_margin_cache)` 在 `_margin_cache_lock` **内**取、发布在**锁外**），对齐 `stock_api._cache_store`（BR-SA-16/26）与 `cache._publish_url_stats`（BR-CACHE-24）的「锁内取标量、锁外发布」纪律（**BR-MKT-17**）。② **模块 docstring 如实化**：原文 "fetching goes through ``cache.fetch_json`` only" 会被读成"每次取数都经 `fetch_json`"，而 TTL 新鲜的**终端缓存命中已不调用它**——改为「`cache.fetch_json` remains the sole HTTP egress, but a TTL-fresh terminal-cache hit serves the stored payload without calling it」（**不改变任何契约**）。③ **测试**：新增 `tests/test_data_layer.py::test_terminal_cache_publishes_cache_entries_gauge`（写后 `cache_entries{margin} == 1`、命中后**仍 == 1**、LRU 淘汰后 **== `cache_max`**）⇒ 用例 **525 → 526**。④ **同步**：`metrics.md` → **v1.11**（§3.2 `cache_entries` 标签枚举**补 `margin`**）。**本模块其余契约 / BR-MKT-1..16 / 响应字段集合 / 对外签名零变更**；**本轮只改文档**——代码 / 测试已落地（**526 用例全绿**）；**未改代码 / 测试 / SAD / PRD / API.md / README.md / `.opencode`；`metrics.md` → v1.11、`_PROGRESS.md` 同步。**
> **v1.8 变更（PRF-LAT-02 margin 终端缓存 · 以 `market_api.py` 实现为准 · 只改文档，不改代码）**：① **新增模块内终端缓存三元组**（§1.1#4 / §3.3·§3.4）：`_margin_cache = OrderedDict()`（`market -> transformed payload`）、`_margin_cache_ts = {}`（`market -> write instant`，TTL 基准）、`_margin_cache_lock = threading.Lock()`。**关键（`market` 为键）**：共享 URL 缓存（`cache.py`）存的是**解码文本**，每次命中仍要付 `json.loads` + `_transform_margin`（热路径 P50 ≈8-9ms）；终端缓存直接缓存**变换后的 payload**，命中零解析。② **`fetch_margin` 新流程**（§2.1 / §5）：参数校验（`market ∈ VALID_MARKETS`，拼 URL 前）→ `deadline` 入口闸 → **终端缓存查找**（`now - ts < ttl` ⇒ `move_to_end` 后**直接返回**，**不解析、不计数**）→ 未命中才 `metrics.incr('upstream_fetch_total', key='margin')` + `fetch_json`/`json.loads`/`_transform_margin` → **仅当 `payload['latest'] is not None`** 才写缓存、`_margin_cache_ts[market]=now`、`move_to_end`，并按 `cache_max` **LRU 淘汰**（`while len > cache_max: popitem(last=False)`，**同步删对应 ts**）。③ **`upstream_fetch_total{margin}` 语义更正**：由 v1.7 的"每次 handler 调用 +1"→ **"仅终端缓存 miss 时 +1"**（BR-MKT-9）；与 stock 域（终端 miss 才调 fetcher → 计数，`stock_api.md` BR-SA-28）**对齐**，消除"URL 缓存命中亦计数"的旧上界口径。④ **§3.3 `margin.cache_max` 由 `null` → `8`**（`config.md` v1.14 同批：`DOMAIN_MATRIX['margin']` 的 `cache_max` 由 `'n/a'` → `8`；margin 由 URL-cache-only 域**移出**）。⑤ **失败 / 空数据不缓存**（BR-MKT-14）：`FetchError`（含 `upstream_timeout`/`upstream_error`）与 `{'latest': None, 'recent': []}` **一律不写** ⇒ **降级体永不被缓存**。⑥ **命中返回共享 payload 对象**（BR-MKT-16）：`_margin_cache` 内是同一对象 ⇒ 调用方（`handle_margin`/`server`）**不得就地修改**（`server` 只序列化写出）。**本模块其余契约 / BR-MKT-1..12 / 响应字段集合 / 对外签名零变更**；**本轮只改文档**——代码 / 测试已落地（**525 用例全绿**：margin 命中不取数 / TTL 过期重取 / LRU 有界 / 失败不缓存 / 空数据不缓存 / 计数仅 miss）；**未改代码 / 测试 / SAD / PRD / API.md / README.md / `.opencode`；`config.md` → v1.14、`metrics.md` → v1.10、`_PROGRESS.md` 同步。**
> **v1.7 变更（溯源收口 + 引用时点约定 · 只改文档，不改代码）**：① **【溯源收口】** 头部上游 **SAD v1.12 / PRD v0.10**（v1.6 已对，本版复核无变化）；「基础层接口权威」栏由 **config v1.5 / cache v1.13 / metrics v1.7** 更新为**现行版本 config v1.6 / cache v1.14 / metrics v1.8**。② **【引用时点约定（新增）】**「接口权威」栏所列版本 = **本文最后一次同步时点的快照**；被引文档的**权威版本以其自身头部为准**——故该栏**落后一版不属漂移、无需每次追平**；**内容以被引文档为准，此栏仅用于定位**。**本模块的代码 / 契约形态 / BR / 测试编号 / 偏差零变更**（v1.6 正文逐字保留）；**未改代码 / SAD / PRD / API.md / README.md / `.opencode`；`_PROGRESS.md` 同步。**
> **v1.6 变更（溯源更正 · 只改文档，不改代码）**：仅更正头部**溯源**——上游 **SAD v1.3 → v1.12**（依据 `doc/arch/SAD.md` 头部 `**版本** v1.12`，AC 总数 36）、**PRD v0.3 → v0.10**（依据 `doc/prd/perf-stability-optimization.md` 头部 **v0.10**）；基础层接口权威栏 **config v1.1 → v1.5 / cache v1.1 → v1.13 / metrics v1.1 → v1.7**。**溯源更正，无内容变更**——本模块代码 / 契约形态 / BR / 测试编号 / 偏差**零变更**（v1.5 正文逐字保留）；**未改代码 / SAD / PRD / API.md / README.md / `.opencode`；`_PROGRESS.md` 同步。**
> **v1.5 变更（REV-DES-20 owner 收口 · 只改文档，不改代码）**：`metrics.md` §3.2 的 `upstream_fail_total` owner 列**已补 `market_api`**（本轮补登；事实依据见 `metrics.md` v1.7——`market_api.py:72/78/145` 为本模块自行判定的语义失败写入点）⇒ 本模块 §10#5 / §11 登记的「由编排层同步」待办 **✅ 闭环**；v1.1 变更记录行「`metrics.md` 同步权归编排层」**原文保留并加 v1.5 更正注**。**本模块代码 / 契约形态零变更**（`market_api.py` 未改）。**未改代码 / SAD / PRD / API.md / README.md / `.opencode`；`metrics.md` → v1.7、`_PROGRESS.md` 同步。**
> **v1.4 变更（以代码为准）**：① **§3.3 `margin.cache_max` 由 `16` 更正为 `null`**——`config.DOMAIN_MATRIX` 的 `margin` 行为 `[L4, 2.0, 2.0, 'fixed:16', 'n/a']`，`cache_policy('margin')['cache_max']` 归一化为 `None`（margin 仅走共享 URL 缓存，`cache.MAX_CACHE_SIZE=2000` 全局约束；per-domain 上限是运维无法生效的死设置，`config.md` §3.1/§10#15 已钉死）。★ **这是本模块本轮唯一的"描述与代码不符"项**。**★ v1.8 已更正：该结论已被 PRF-LAT-02 推翻——margin 现持有终端缓存，`cache_max` 改 `8` 且被消费（见 §3.3 / §10#10·#11）。**
> **本轮逐项核对结论（清单 vs 代码）**：`fetch_margin` 透传 `deadline`（BR-MKT-11）✅ 已在 v1.3 记载；`zb` 归一为 float ✅；`_to_float` 逐字段容错 ✅；`_DEGRADED_LATEST` 全 `0.0` ✅。**四项均与代码一致，无需改动**（`market_api.py` 代码零变更）。
> **v1.3 变更（AC-S3 裁决 · 收尾契约同步）**：⑤ **BR-MKT-11 的"预算封顶"更正**——`fetch_json` 的 `deadline` 透传使 `urlopen` 超时 = `cache._effective_timeout` = `min(_fetch_budget(url), max(0.05, 剩余 deadline))`；其中 `_fetch_budget` 的**阶梯封顶是 `cache._PROBE_BUDGET_CAP=5.0`**（**不是** `REQUEST_TIMEOUT(10s)`）。`REQUEST_TIMEOUT` 仅在"无失败历史 / 已老化"两支作冷/全预算探测 ⇒ **margin 在故障期的单次回源上界实际 ≤5s**（旧表述"可跑满固定 `REQUEST_TIMEOUT`"仅在冷预算期成立）。
> 本版修订（P7b 契约同步，**只改文档、不改代码**）：① `fetch_margin` 把 `deadline` **透传给 `fetch_json`**（`urlopen` 超时随预算收缩）；② `zb` **归一为 float**、`_transform_margin` **逐字段容错**（新增 `_to_float`）；③ **`_DEGRADED_LATEST` 为 `0.0`**（float）；④ 新增 **`VALID_MARKETS` 枚举闸**（URL 拼装前拒绝非法 `market`）。
> 沿用 v1.1：REV-DES-20260915-002（REV-DES-11 裁决回执 + REV-DES-20 owner 引据更正）
> 模块路径 `china_finance_rss/market_api.py` · 归属 **Layer 2（业务/数据获取层）**
> 上游 SAD `doc/arch/SAD.md` **v1.12**（★ v1.6 溯源更正：原误记 v1.3；权威以 SAD 头部为准）（§2.1 `cache_policy` / §2.3 D-1 `FetchError` / §3 `market_api.py` 行 / ADR-001/005/008）
> 上游 PRD `doc/prd/perf-stability-optimization.md` **v0.10**（★ v1.6 溯源更正：原误记 v0.3；权威以 PRD 头部为准）（AC-S1 / AC-S10 / AC-A5；R16）
> 基础层接口权威 `doc/detailed/config.md` **v1.14** · `cache.md` **v1.14** · `metrics.md` **v1.11**（★ v1.9 同步：metrics v1.10 → **v1.11**（§3.2 `cache_entries` 标签枚举补 `margin`）；★ v1.8 同步：config v1.6 → **v1.14**（margin 终端缓存上限 8）、metrics v1.8 → **v1.10**（`upstream_fetch_total` 语义明确）；`cache.md` v1.14 不变；权威以各文档头部为准）
> ★ **引用时点约定**：上列「接口权威」版本 = **本文最后一次同步时点的快照**；被引文档的**权威版本以其自身头部为准**——故该栏**落后一版不属漂移、无需每次追平**；**内容以被引文档为准，此栏仅用于定位**。
> 端锁定 🟠 STABLE（响应字段集合不变；仅 `_error` 取值由自由文本收敛为**枚举错误码**）

## 1. 模块职责与边界

### 1.1 职责

1. **融资融券（margin）单体端点**的取数与格式化：`fetch_margin`（上游取数 + 变换）/ `handle_margin`（对外 handler 形态）。
2. **TTL 来源收敛（R16）**：`_MARGIN_CACHE_TTL(600)` 删除，改读 `config.cache_policy('margin')['ttl']`（值不变 = 600，见 `config.md` §3.2）。
3. **失败分类参与观测（SAD §3 market_api 行）**：把"上游语义失败"（`status_code != 0`）编码为 `FetchError('upstream_error')` 并计入 `metrics`。
4. **margin 终端缓存（★ v1.8 / PRF-LAT-02）**：模块内 `_margin_cache`（`market -> 变换后 payload`）+ `_margin_cache_ts` + `_margin_cache_lock`——命中即返回**变换后**结果，省去每次 `json.loads` + `_transform_margin`（热路径 P50 ≈8-9ms）；TTL/上限只经 `cache_policy('margin')`（`ttl`/`cache_max`），**不引入第二来源**。

### 1.2 明确不做

- **不实现 `handle_margin` 之外的任何端点**（本模块仅 margin；`/ths/longhu` 属 `server.py`，`/cls/hotplate` 属 `server.py`）。
- **★ v1.8 更正（原「不新增缓存容器」已不成立）**：margin **现持有**终端缓存三元组（`_margin_cache`/`_margin_cache_ts`/`_margin_cache_lock`，§1.1#4 / §3.3·§3.4）；**但**仍**不持有**任何 metrics 私有状态、不自行读 env、不发起 `urlopen` 直连——取数**只**经 `cache.fetch_json`。
- **不做降级重试 / 熔断**：失败即降级体，重试抑制由 `cache.fetch_json` 负缓存（`NEG_TTL=5s`）承担（ADR-003）。
- **不改 `_transform_margin` 的输出字段与数值口径**（单位换算 1e8、`recent` 取末 30 条等）——纯保留。

### 1.3 layerIsolation 约束

`tech-stack.json` 的 `layerIsolation` **未对 `market_api.py` 单列条目**（其 `forbiddenImports` 仅约束 cache/config/cdp_engine/metrics）。本模块仍须遵守项目分层方向：

```
允许 import：
  标准库：json / logging / time / threading / collections（OrderedDict）   # ★ v1.8：终端缓存锁与有序表
  包内  ：config（cache_policy）、cache（fetch_json, FetchError）、metrics
禁止 import：server / stream / cdp_engine / stock_api
  （理由：market_api 与 stock_api 同层、互不依赖；server/stream 是上游消费者）
```

**依赖方向**（`←` 表分层顺序，非 import 关系）：

```
Layer 0: config（无依赖）  ‖  metrics（零业务依赖叶子）
Layer 1: cache ← {config, metrics}
Layer 2: market_api / stock_api / stream ← {config, cache, metrics}
Layer 3: server ← {market_api, stock_api, stream}
```

### 1.4 与基础层接口的对齐（不得偏离）

| 基础层接口 | 本模块用法 |
|-----------|-----------|
| `config.cache_policy('margin') -> dict` | 取 `['ttl']`（=600）**与 `['cache_max']`（=8，★ v1.8 终端缓存上限）**。**禁止**出现裸 TTL / 裸缓存上限字面量（BR-CFG-12 / BR-MKT-13） |
| `config.VALID_MARKETS`（本模块定义、`server` 导入） | ★ **P7b**：`('99','1','2','3')` 枚举；URL 拼装**之前**的边界校验点（§2.1） |
| `cache.fetch_json(url, headers, ttl=..., deadline=...) -> str` | 唯一取数入口；失败**恒** `raise FetchError(kind)`（四段式，含负缓存）；★ **P7b**：`deadline` 透传 ⇒ `urlopen` 超时 = `min(cache._fetch_budget(url), 剩余预算)` |
| `cache.FetchError(kind).kind` | ∈ `{upstream_timeout, upstream_error, cdp_unavailable}`；本模块只会收到前两者 |
| `metrics.incr(name, n=1, key=None)` | `upstream_fetch_total{domain='margin'}`、`upstream_fail_total{kind}` |
| `metrics.set_gauge(name, value, key=None)` | ★ **v1.9**：`cache_entries{key='margin'}` = `len(_margin_cache)`——**命中路径与写入/淘汰路径均锁外发布**（锁内只取长度）；`cache_entries ∈ metrics._LABELED_GAUGES`（BR-MKT-17） |

---

## 2. 接口契约

### 2.1 `fetch_margin(market='99', deadline=None) -> dict`

```python
def fetch_margin(market: str = '99', deadline: float | None = None) -> dict:
```

| 参数 | 类型 | 默认 | 语义 |
|------|------|------|------|
| `market` | `str` | `'99'` | `'99'`=合计 / `'1'`=沪 / `'2'`=深 / `'3'`=京（拼进 URL 路径段）。**必须 ∈ `VALID_MARKETS`**，否则**在拼 URL 之前**即 `raise FetchError('upstream_error')`、**不触网**（§4 BR-MKT-10） |
| `deadline` | `float \| None` | `None` | epoch 秒（绝对期限）。`None` → 不做入口期限判定（由 `fetch_json` 的预算兜底）。**非 `None` 时透传给 `fetch_json(deadline=)`**，使 `urlopen` 超时随剩余预算收缩（BR-MKT-11），而非永远允许固定 `REQUEST_TIMEOUT` |

> **命名规则说明（tech-stack `namingRules.fetch`）**：`fetch_margin(market=...)` 是**非码取数器**（形参是市场代号而非股票代码），与 `fetch_cls_telegraph(feed_url=None)` 同类，**不受** `fetch_*(code, deadline=None)` 约束；此处仍新增可选 `deadline` 以统一"期限可传入"能力，**向后兼容**。
> **`VALID_MARKETS` 单一权威（P7b）**：代码注释钉明"`server.py` 导入它做边界检查"，故路由层与 URL 构造层的枚举**不会漂移**。非法 `market` 会被插值进路径段，未校验时可注入同主机路径/查询并每个伪造值铸一个缓存键 ⇒ 必须在**拼 URL 前**拒绝。

**返回**：成功 → margin 数据客体（§3.1）；**无数据**（上游 200 但 `date`/`item` 均空）→ `{'latest': None, 'recent': []}`。
**抛出**：`FetchError`（**唯一失败类型**）；`handle_margin` 负责把它转成降级体，**本函数不降级**（分层职责：取数层抛、接口层降级）。

> **★ v1.8 终端缓存语义（PRF-LAT-02）**：`fetch_margin` 是**终端缓存**的读写点——
> - **命中**（`_margin_cache[market]` 存在且 `now - _margin_cache_ts[market] < ttl`）⇒ `move_to_end(market)` 后**直接返回已变换 payload**：**不 `json.loads`、不 `_transform_margin`、不计 `upstream_fetch_total`**（BR-MKT-13）。
> - **未命中** ⇒ 计一次 `upstream_fetch_total{margin}`（**仅此一处**，BR-MKT-9）→ 走 `fetch_json` 原路径。
> - **写缓存**：**仅** `payload['latest'] is not None` 时写（BR-MKT-14）；失败体与无数据体**不写** ⇒ 降级体永不被缓存。
> - **有界**：写入后按 `cache_max`（= `cache_policy('margin')['cache_max']` = **8**）LRU 淘汰（超限 `popitem(last=False)` 并同步删 ts，BR-MKT-15）。
> - **共享对象**：命中返回的是缓存内**同一对象**，调用方不得就地修改（BR-MKT-16）。
> - **★ v1.9 可观测**：**命中**与**写入/淘汰**两条路径均在**释放 `_margin_cache_lock` 之后**发布 `metrics.set_gauge('cache_entries', len(_margin_cache), key='margin')`（锁内只取 `len`）——故 `cache_entries{margin}` 恒等于终端缓存**当前长度**（命中不改变长度 ⇒ 值不变）；`cache_entries ∈ metrics._LABELED_GAUGES`（BR-MKT-17）。

### 2.2 `handle_margin(market='99') -> dict`

```python
def handle_margin(market: str = '99') -> dict:
```

- **总函数**：任意输入/任意上游状态都返回 `dict`，**绝不抛**（项目约定 `handle_* 返回 dict 不抛`）。
- 成功 → 数据客体；失败 → 降级体（§3.2），HTTP 200。
- 消费者：`server.py:602` `handle_margin(market)` → `_send_json`。**签名不变**（server 零改动，🟠 STABLE）。

### 2.3 `_transform_margin(data) -> dict`

```python
def _transform_margin(data: dict) -> dict:
```

- **签名与数值语义不变**：`data` 缺 `date`/`item` → `{'latest': None, 'recent': []}`；否则 `latest` = 末条、`recent` = 末 30 条；金额 `to_100m(v) = round(_to_float(v)/1e8, 4)`；**`zb` 经 `_to_float` 归一为 float**（P7b，不再原样透传上游字符串/哨兵）。
- **防御**：`data` 非 dict → 视为无数据返回 `{'latest': None, 'recent': []}`（`isinstance(data, dict)` 前置判定）；`items[i]` 非 dict → 该行按空 dict 处理（逐行容错）。
- **逐字段容错（P7b / P2-8）**：每个数值单元格独立经 `_to_float`（§2.5）⇒ `'--'`/`None`/`''`/不可解析 junk **只把自己降为 `0.0`**，**不会让整份响应退化为零**（旧版 `float(val)` 抛异常会被 `handle_margin` 兜底成整份降级体，一行脏数据抹掉全部有效行）。

### 2.4 `_degraded(kind) -> dict`（内部函数）

```python
def _degraded(kind: str) -> dict:
```

唯一降级体构造点，避免多处重复字面量（§3.2）。`kind` 必须 ∈ `FetchError.KINDS`，否则归一 `'upstream_error'`。

### 2.5 `_to_float(val) -> float`（P7b 新增）

```python
def _to_float(val) -> float:
```

| 输入 | 返回 |
|------|------|
| `None` / `'--'` / `''`（缺失哨兵） | `0.0` |
| `int` / `float` / 可解析数字串 | `float(val)` |
| 其它不可解析 junk（`TypeError`/`ValueError`） | `0.0` |

单一数值单元格的 best-effort 归一；**绝不抛**（返回 `0.0`），是 §2.3 逐字段容错的唯一实现点。

---

## 3. 数据结构

### 3.1 成功响应体（yaml，字段集合不变）

```yaml
margin_success:
  latest:                       # dict | null（无数据时 null）
    date: <str>                 # 例 '2026-09-12'
    rzye: <float>               # 融资余额(亿)  = round(raw/1e8,4)
    rqye: <float>               # 融券余额(亿)
    rzmre: <float>              # 融资买入额(亿)
    rzjmr: <float>              # 融资净买入(亿)
    rqjmc: <float>              # 融券净卖出(亿)
    lr:   <float>               # 两融余额(亿)
    zb:   <float>               # ★ P7b：占比(小数，不做 1e8 换算) —— 经 _to_float 归一为 float
  recent: [ <latest 同形状>, ... ]   # 至多 30 条（末 30 个交易日）
```

### 3.2 降级响应体（yaml，字段集合不变，仅 `_error` 取值收敛）

```yaml
margin_degraded:
  latest:
    rzye: 0.0, rqye: 0.0, rzmre: 0.0, rzjmr: 0.0, rqjmc: 0.0, lr: 0.0, zb: 0.0   # ★ P7b：全为 float
  recent: []
  _error: upstream_timeout | upstream_error   # ★ 由自由文本 str(e) 收敛为枚举错误码
```

> **值域收敛说明**：现状 `_error: str(e)`（自由文本）。目标 `_error: <FetchError.kind>`（枚举二值）。
> 依据：AC-S6/AC-A10 的"枚举错误码、不允许自由文本"口径；PRD §7.1 端锁定要求"字段集合不变"，`_error` **字段名与类型（str）不变**，仅**取值集合**收敛 → 属 🟠 STABLE 内的行为改进（登记见 §10#3）。

### 3.3 margin 域缓存策略（唯一权威 = `cache_policy`，本模块只读）

```yaml
cache_policy('margin'):
  tier: L4
  ttl: 600                 # 盘中/非盘中均 600（= L4 300 × factor 2.0）→ 与旧 _MARGIN_CACHE_TTL 数值等价
  pool_refresh: 1200       # 本模块不使用（无去重池）
  pool_max: 16             # 本模块不使用（无去重池）
  cache_max: 8             # ★ v1.8 更正（v1.4 曾记 null）：margin 有终端缓存 ⇒ 上限 8（4 market × 2 余量）；config.md v1.14 同批
```

> 本模块**不消费** `pool_refresh`/`pool_max`（margin 是单键端点、无按码去重池）。**★ v1.8 起消费 `cache_max`（=8）** 作终端缓存上限（此前 v1.4–v1.7 记录"不消费"）。margin 数据可有**两级缓存**：URL 级（`cache.fetch_json` 的 `cache{}`，存**解码文本**）与**终端级**（`_margin_cache`，存**变换后 payload**，命中零解析）。

### 3.4 终端缓存内部状态（★ v1.8 / PRF-LAT-02，yaml）

```yaml
_margin_cache:      OrderedDict()          # market(str) -> transformed payload(dict)；插入序 = LRU 序
_margin_cache_ts:   {}                     # market(str) -> write instant(float, epoch 秒；TTL 基准)
_margin_cache_lock: threading.Lock()       # 保护上面两者的全部读写（含 move_to_end / popitem）

# 键值域：market ∈ VALID_MARKETS('99','1','2','3') ⇒ 实际条目 ≤ 4，cache_max=8 仅作结构性上界
# 生命周期：写入 = 仅 latest is not None；淘汰 = 超 cache_max 时 popitem(last=False) 并同步删 ts
# 读命中判据：_margin_cache.get(market) is not None 且 (now - _margin_cache_ts[market]) < ttl
```

> **为什么是 `OrderedDict` 而非普通 dict**：需要**真 LRU**（命中/写入均 `move_to_end`，淘汰取最旧 `popitem(last=False)`）——与 `stock_api._cache_store` 的 LRU 语义一致（`config.md` §3.2 注 / `stock_api.md` BR-SA-13）。
>
> **★ v1.9 发布纪律（BR-MKT-17）**：`len(_margin_cache)` 在 `_margin_cache_lock` **内**取（与 `get`/`move_to_end`/`popitem` 同一临界区，读到自洽长度），`metrics.set_gauge('cache_entries', entries, key='margin')` 在**锁外**调用——**命中路径与写入/淘汰路径各一处**（`market_api.py` 于两条路径分别发布）。对齐 `stock_api._cache_store`（BR-SA-16/26）与 `cache._publish_url_stats`（BR-CACHE-24）的「锁内取标量、锁外发布」纪律，避免"持域锁 → 取 metrics 叶子锁"的长临界区；`entries` 为**普通 int**、`cache_entries ∈ metrics._LABELED_GAUGES`。

---

## 4. 业务规则

| 编号 | 规则 | 依据 |
|------|------|------|
| **BR-MKT-1** | TTL **只**来自 `cache_policy('margin')['ttl']`；本模块禁止出现 `600`/`_MARGIN_CACHE_TTL` 等裸 TTL 字面量 | R16 / BR-CFG-12 |
| **BR-MKT-2** | 取数**只**经 `cache.fetch_json`；**禁止** `urlopen` 直连（与 R15 同源约定） | §3.1 约定 |
| **BR-MKT-3** | `deadline` 非 `None` 且 `time() >= deadline` → 入口即 `raise FetchError('upstream_timeout')`，**不触网** | SAD §2.3 D-2 || **BR-MKT-4** | 上游 `status_code != 0`（HTTP 200 但业务失败）→ `FetchError('upstream_error')`，并 `metrics.incr('upstream_fail_total', key='upstream_error')`（该失败**不由 cache 计数**，见 BR-MKT-8） | AC-A5 上游失败 |
| **BR-MKT-5** | 上游 200 且 `status_code == 0`，但 `date`/`item` 为空 → **无数据**（`latest=None`），**不是失败**：不抛、不落 `_error`、不计 `upstream_fail_total` | 值域三分 |
| **BR-MKT-6** | `handle_margin` 捕获 `FetchError` → `_degraded(exc.kind)`；捕获其余 `Exception` → `_degraded('upstream_error')` + `log.warning`；**永不抛** | handle_* 约定 / AC-S1 |
| **BR-MKT-7** | `_error` 取值 ⊆ `{upstream_timeout, upstream_error}`（枚举封闭，无自由文本） | AC-S6 口径 |
| **BR-MKT-8** | **`upstream_fail_total{kind}` 计数口径（防重复计数，全系统唯一约定）**：`fetch_json` 的网络失败已由 `cache._record_failure` 计数（BR-CACHE-6）→ 本模块**捕获到的 `FetchError` 一律不再计数**；仅对**本模块自行判定**的语义失败（BR-MKT-4 / BR-MKT-6 的 `Exception` 分支）计数 | 本模块与 `cache` 的防重复计数约定（**REV-DES-20**：`metrics.md` §3.2 owner 列补 `market_api` 由编排层同步；本文不再引已过期的 owner 表述） |
| **BR-MKT-9** | `upstream_fetch_total{domain}` 的 `domain` 恒为 `'margin'`；★ **v1.8 语义更正**：**仅终端缓存 miss 时 +1**（此前 v1.7 口径为"每次 handler 调用 +1 / URL 缓存命中亦计数 = 上界估计"）——与 stock 域（终端 miss 才调 fetcher → 计数，`stock_api.md` BR-SA-28）**对齐**；命中路径**零计数** | AR-6 / Q3⑤ / §10#4 |
| **BR-MKT-10** | **`market` 枚举闸（P7b）**：`market ∉ VALID_MARKETS('99','1','2','3')` ⇒ **在拼出 URL 之前** `raise FetchError('upstream_error', url=_MARGIN_URL)`，**不触网**。禁止把任意字符串插值进路径段 | §2.1 / 注入与"每错值一缓存键"防护 |
| **BR-MKT-11** | **`deadline` 透传（P7b；★ v1.3 封顶更正）**：`fetch_json(url, headers, ttl=..., deadline=deadline)` —— 网络超时由 `cache._effective_timeout` 取 `min(_fetch_budget(url), max(0.05, 剩余))`。其中 `_fetch_budget(url)` 三支：**无失败历史 → `REQUEST_TIMEOUT(10s)`**；**失败段已老化（≥`_HISTORY_AGE=600s`）→ `REQUEST_TIMEOUT(10s)`**；**有失败历史且未老化 → `_probe_budget(fail_count)` 阶梯 `2→4→_PROBE_BUDGET_CAP(5s)` 封顶**——⇒ **故障期（负缓存已有条目）的 margin 单次回源上界 = 5s，而非 10s**。入口前置判定（BR-MKT-3）保留为"已过即抛、不触网"的快速路径，**不替代**透传（否则通过入口判定的调用仍可跑满 `_fetch_budget`） | SAD §2.3 D-2 / AC-E2 / `cache.md` §4.2 BR-CACHE-22（**AC-S3 裁决**） |
| **BR-MKT-12** | **逐字段数值容错（P7b / P2-8）**：每个数值单元格独立经 `_to_float`（`None`/`'--'`/`''`/不可解析 ⇒ `0.0`）；`items[i]` 非 dict ⇒ 按空 dict 处理。**禁止**让单个脏字段/脏行使整份响应退化为降级体 | §2.3/§2.5 |
| **BR-MKT-13** | **★ v1.8 终端缓存（PRF-LAT-02）**：`_margin_cache[market]` 命中判据 = `get(market) is not None` **且** `time() - _margin_cache_ts[market] < cache_policy('margin')['ttl']`（**TTL 唯一来自 `['ttl']`=600**）。命中 ⇒ `move_to_end(market)` 后**直接返回缓存 payload**——**不 `json.loads`、不 `_transform_margin`、不计 `upstream_fetch_total`**。上限 **`= cache_policy('margin')['cache_max']`（=8）**；键 `market ∈ VALID_MARKETS`（实际条目 ≤ 4）。**禁止**在模块内硬编码 600/8（须经 `cache_policy`，BR-CFG-12）；★ **v1.9**：命中路径另**锁外**发布 `cache_entries{margin}`（BR-MKT-17） | PRF-LAT-02 / §3.3·§3.4 / `config.md` v1.14 BR-CFG-5 |
| **BR-MKT-14** | **★ v1.8 只缓存可用数据**：**仅当** `payload['latest'] is not None` 才写 `_margin_cache`（并 `_margin_cache_ts[market] = now`）。**失败**（任何 `FetchError`，含 `upstream_timeout`/`upstream_error`）与**无数据**（`{'latest': None, 'recent': []}`）**一律不写** ⇒ **降级体永不被缓存**、下一次请求必然重试回源 | 值域三分 / AC-A10 |
| **BR-MKT-15** | **★ v1.8 真 LRU 有界**：`_margin_cache` 为 `OrderedDict`；**命中与写入均 `move_to_end(market)`**；写入后 **`while len(_margin_cache) > cache_max: victim,_ = popitem(last=False); _margin_cache_ts.pop(victim, None)`**（**同步删 ts**，防 ts 泄漏 / 幽灵条目）。`cache_max` 取 `cache_policy('margin')['cache_max']`（=8）；★ **v1.9**：写入/淘汰后**锁外**发布 `cache_entries{margin}`（值 = 淘汰后的当前长度，BR-MKT-17） | §3.4 / BUG 防护（ts 与 cache 同步） |
| **BR-MKT-16** | **★ v1.8 命中返回共享对象**：命中路径返回的是 `_margin_cache` 内**同一个 payload 对象**（**有意为之**：省一次深拷贝，且 `cache_max` 有界 ⇒ 退化面小）。⇒ **调用方（`handle_margin` / `server`）不得就地修改返回值**；本模块自身只读返回。若将来出现就地改写需求，须改为返回 `copy.deepcopy`（登记为设计约束） | §2.1 / 并发安全 §7 |
| **BR-MKT-17** | **★ v1.9 终端缓存可观测（写入与命中均锁外发布）**：`fetch_margin` 的**命中路径**与**写入/淘汰路径**各发布一次 `metrics.set_gauge('cache_entries', len(_margin_cache), key='margin')`。**纪律**：`len` 在 `_margin_cache_lock` **内**取（与 `get`/`move_to_end`/`popitem` 同一临界区，读到自洽长度），`set_gauge` 在**释放锁之后**调用——**禁止**持 `_margin_cache_lock` 时调用 metrics（`metrics._lock` 为叶子锁，永远最内层）。命中不改变长度 ⇒ 命中后该值**不增**（仅刷新读数、覆盖同值）；写入/淘汰后该值 == 淘汰后的当前长度。对齐 `stock_api._cache_store`（BR-SA-16/26）与 `cache._publish_url_stats`（BR-CACHE-24）；`cache_entries ∈ metrics._LABELED_GAUGES`（`metrics.md` §3.2 标签值含 `margin`） | PRF-LAT-02 P2 / CR-02 / §3.4 / §7 / `stock_api.md` BR-SA-16·BR-SA-26 / `cache.md` BR-CACHE-24 / `metrics.md` §3.2 |

---

## 5. 伪代码

```python
import json
import logging
import threading
import time
from collections import OrderedDict

from . import metrics
from .cache import FetchError, fetch_json
from .config import _MARGIN_HEADERS, _MARGIN_URL, cache_policy

log = logging.getLogger('market')

# market 契约枚举（§2.1）：'99'=合计 / '1'=沪 / '2'=深 / '3'=京。
# 单一权威 —— server.py 导入它做边界检查，故路由层与 URL 构造层的枚举不会漂移。
VALID_MARKETS = ('99', '1', '2', '3')

# 终端缓存（★ v1.8 / PRF-LAT-02，§3.3·§3.4）：market -> 变换后 payload。
# 共享 URL 缓存（cache.py）存的是解码文本，命中仍要付 json.loads + _transform_margin
# （热路径 P50 ≈8-9ms）；终端缓存直接返回变换结果，命中零解析。
# 键 = market（已校验的全枚举）⇒ 实际条目 ≤ 4；cache_max=8 仍作结构性上界。
_margin_cache = OrderedDict()          # market -> transformed payload（插入序 = LRU 序）
_margin_cache_ts = {}                  # market -> write instant（TTL 基准）
_margin_cache_lock = threading.Lock()  # 保护上面两者的全部读写（move_to_end / popitem）

_DEGRADED_LATEST = {'rzye': 0.0, 'rqye': 0.0, 'rzmre': 0.0,
                    'rzjmr': 0.0, 'rqjmc': 0.0, 'lr': 0.0, 'zb': 0.0}   # ★ 全 float


def _degraded(kind):
    if kind not in FetchError.KINDS:          # BR-MKT-7：枚举封闭
        kind = 'upstream_error'
    return {'latest': dict(_DEGRADED_LATEST), 'recent': [], '_error': kind}


def fetch_margin(market='99', deadline=None):
    """BR-MKT-1..5/9..17：唯一取数入口 + 枚举闸 + 期限入口判定与透传 + 终端缓存（含锁外观测）+ 语义失败编码。"""
    if market not in VALID_MARKETS:                        # ★ BR-MKT-10：拼 URL 之前
        raise FetchError('upstream_error', url=_MARGIN_URL)
    url = f'{_MARGIN_URL}/{market}/'
    policy = cache_policy('margin')                        # BR-MKT-1/13：唯一权威
    ttl = policy['ttl']
    if deadline is not None and time.time() >= deadline:   # BR-MKT-3：入口即抛、不触网
        raise FetchError('upstream_timeout', url=url)

    now = time.time()
    with _margin_cache_lock:                               # ★ BR-MKT-13：命中直接返回
        cached = _margin_cache.get(market)
        hit = cached is not None and now - _margin_cache_ts.get(market, 0) < ttl
        if hit:
            _margin_cache.move_to_end(market)              # 真 LRU（不解析、不计数）
        entries = len(_margin_cache)                       # ★ BR-MKT-17：锁内取长度
    if hit:
        metrics.set_gauge('cache_entries', entries, key='margin')   # ★ 锁外发布（命中，BR-MKT-17）
        return cached

    metrics.incr('upstream_fetch_total', key='margin')     # ★ BR-MKT-9：仅 miss 时 +1
    try:
        raw = json.loads(fetch_json(url, _MARGIN_HEADERS,  # BR-MKT-2
                                    ttl=ttl, deadline=deadline))   # ★ BR-MKT-11：期限透传
    except FetchError:
        raise                                              # BR-MKT-8：cache 已计数，不重复（亦不写缓存 BR-MKT-14）
    except Exception as exc:                               # JSON 解码等
        metrics.incr('upstream_fail_total', key='upstream_error')
        raise FetchError('upstream_error', url=url, cause=exc) from exc

    if not isinstance(raw, dict):
        return {'latest': None, 'recent': []}              # BR-MKT-5：无数据（且不写缓存 BR-MKT-14）
    if raw.get('status_code') != 0:                        # BR-MKT-4：语义失败
        metrics.incr('upstream_fail_total', key='upstream_error')
        raise FetchError('upstream_error', url=url)        # BR-MKT-14：不写缓存
    payload = _transform_margin(raw.get('data') or {})     # BR-MKT-5
    if payload['latest'] is not None:                      # ★ BR-MKT-14：仅可用数据才写
        cache_max = policy['cache_max']                    # = 8（BR-MKT-13）
        with _margin_cache_lock:
            _margin_cache[market] = payload
            _margin_cache_ts[market] = now                 # TTL 基准
            _margin_cache.move_to_end(market)              # BR-MKT-15
            while len(_margin_cache) > cache_max:
                victim, _ = _margin_cache.popitem(last=False)   # 真 LRU
                _margin_cache_ts.pop(victim, None)               # 同步删 ts
            entries = len(_margin_cache)                   # ★ BR-MKT-17：锁内取长度
        metrics.set_gauge('cache_entries', entries, key='margin')   # ★ 锁外发布（写入/淘汰，BR-MKT-17）
    return payload


def _to_float(val):
    """单个数值单元格的 best-effort 归一（BR-MKT-12）。

    缺失哨兵（None / '--' / ''）与不可解析 junk 一律降为 0.0 —— **逐字段**降级：
    旧版 float(val) 会抛穿 transform，让 handle_margin 把整份响应变成零，一行脏数据
    抹掉全部有效行。
    """
    if val is None or val == '--' or val == '':
        return 0.0
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0


def _transform_margin(data):
    """非 dict 输入降级；每个数值字段独立归一（BR-MKT-12）。"""
    if not isinstance(data, dict):
        return {'latest': None, 'recent': []}
    dates = data.get('date') or []
    items = data.get('item') or []
    if not dates or not items:
        return {'latest': None, 'recent': []}

    def to_100m(val):
        return round(_to_float(val) / 100_000_000, 4)

    def fmt(i):
        item = items[i] if isinstance(items[i], dict) else {}      # 逐行容错
        return {'date': dates[i],
                'rzye': to_100m(item.get('rzye', 0)),
                'rqye': to_100m(item.get('rqye', 0)),
                'rzmre': to_100m(item.get('rzmre', 0)),
                'rzjmr': to_100m(item.get('rzjmr', 0)),
                'rqjmc': to_100m(item.get('rqjmc', 0)),
                'lr':   to_100m(item.get('lr', 0)),
                'zb':   _to_float(item.get('zb', 0))}              # ★ float，非 1e8 换算

    n = min(len(dates), len(items))
    return {'latest': fmt(n - 1) if n > 0 else None,
            'recent': [fmt(i) for i in range(max(0, n - 30), n)]}


def handle_margin(market='99'):
    """BR-MKT-6：总函数，永不抛。"""
    try:
        return fetch_margin(market)
    except FetchError as exc:                              # 含 BR-MKT-4 的 upstream_error
        return _degraded(exc.kind)
    except Exception as exc:                               # 兜底（防御性）
        log.warning('[margin] unexpected error: %s', exc)
        metrics.incr('upstream_fail_total', key='upstream_error')
        return _degraded('upstream_error')
```

---

## 6. 错误处理

| 情形 | 产生层 | 行为 | 对外形态 |
|------|--------|------|---------|
| `market` 非法（∉ `VALID_MARKETS`） | `fetch_margin`（BR-MKT-10） | `raise FetchError('upstream_error')`，**在拼 URL 之前、不触网** | `_error='upstream_error'` |
| 入口期限已过 | `fetch_margin`（BR-MKT-3） | `raise FetchError('upstream_timeout')`，不触网 | `_error='upstream_timeout'` |
| 上游超时（socket/URL，含透传 `deadline` 截断后超时） | `cache.fetch_json`（`cache._classify`） | cache 落负缓存并 raise | `_error='upstream_timeout'` |
| 上游其它异常（DNS/RST/5xx） | `cache.fetch_json` | 同上 | `_error='upstream_error'` |
| 负缓存命中（<1ms） | `cache.fetch_json` 段 2 | 立即 raise（沿用首次 kind） | 同上（AC-S3 模式 A P95 ≤1s） |
| JSON 解码失败 | `fetch_margin` | 自建 `upstream_error` | `_error='upstream_error'` |
| `status_code != 0` | `fetch_margin` | 自建 `upstream_error` | `_error='upstream_error'` |
| 上游 200 但无数据 | `fetch_margin` | **不抛**，返回 `{'latest': None, 'recent': []}` | 无 `_error`（无数据 ≠ 失败） |
| 单个数值单元格脏（`'--'`/`None`/`''`/junk） | `_transform_margin` / `_to_float`（BR-MKT-12） | **该字段**降为 `0.0`，其余字段与其余行**保持有效值** | HTTP 200 正常体（不降级、不 `_error`） |
| `items[i]` 非 dict | `_transform_margin`（BR-MKT-12） | 该行按空 dict 处理（各数值字段 `0.0`） | 同上 |
| `handle_margin` 其它异常 | `handle_margin` | `log.warning` + 降级 | `_error='upstream_error'` |
| **★ v1.8：终端缓存命中** | `fetch_margin`（BR-MKT-13） | **不触网、不解析（无 `json.loads`/`_transform_margin`）、不计数**，`move_to_end` 后直接返回缓存 payload | HTTP 200 正常体 |
| **★ v1.8：终端缓存 miss** | `fetch_margin`（BR-MKT-9） | `upstream_fetch_total{margin}` **+1**，随后走 `fetch_json`（沿用 cache 的失败分类/负缓存） | 同对应上游情形 |
| **★ v1.8：失败 / 无数据（不写缓存）** | `fetch_margin`（BR-MKT-14） | **不写 `_margin_cache`**（无 `latest` 即不写）⇒ 下次请求**必然重试回源**，降级体永不被缓存 | 失败 ⇒ 降级体；无数据 ⇒ `{'latest': None, 'recent': []}` |
| **★ v1.8：缓存超 `cache_max`** | `fetch_margin`（BR-MKT-15） | LRU 淘汰最旧（`popitem(last=False)`）并**同步删 ts** | 被淘汰键下次读为 miss、正常回源（不返回陈旧值） |

**降级路径**：本模块降级**只降级响应体形态**，不降级为异常外抛（`handle_*` 约定）。上游故障期的请求放大由 `cache` 负缓存（`NEG_TTL=5s`）抑制，本模块无需重试逻辑。

---

## 7. 并发安全

| 项 | 结论 |
|----|------|
| 本模块持有的锁 | **★ v1.8：`_margin_cache_lock`**（`threading.Lock`）——保护 `_margin_cache`/`_margin_cache_ts` 的**全部读写**（含 `move_to_end` / `popitem` / `pop`）。此外无其它模块级可变状态 |
| `cache_policy('margin')` | 纯函数、无锁、纳秒级；可在锁内调用（`config.md` §7）。**★ v1.8：`cache_policy` 调用在锁外**（`policy` 在入口一次取得，命中分支只读 `ttl`） |
| `fetch_json` | 内部自有 `_cache_lock`/`_neg_lock`，网络 IO 不持锁；本模块**不在持有 `_margin_cache_lock` 时调用** `fetch_json` |
| `metrics.incr/set_gauge` | 叶子锁（`metrics._lock` 永远最内层）；本模块调用点均在**锁外**。★ **v1.9**：`set_gauge('cache_entries', …, key='margin')` 的**两处**调用点（命中路径 / 写入淘汰路径）均在**释放 `_margin_cache_lock` 之后**（锁内只取 `len`，BR-MKT-17） |
| 锁序 | `_margin_cache_lock` 为**最外层**且**不嵌套**任何其它锁：命中分支仅持它做 `get`/`move_to_end`；写入分支仅持它做赋值/LRU（均在 `fetch_json` 与 `metrics` 之后）；⇒ 不存在锁序环，也不与 cache 的锁交叉 |
| 命中返回共享对象 | 命中返回缓存内**同一 payload**（BR-MKT-16）⇒ 并发读者之间共享对象；本模块**只读**返回，调用方**不得就地修改**（如需改写须自行拷贝） |

> `handle_margin` 可被主池 20 worker 并发调用；终端缓存由 `_margin_cache_lock` 串行化其元数据读写（纳秒级、无 IO），**网络 IO 与 metrics 写入均在锁外** ⇒ 无阻塞放大。

---

## 8. 测试要点（映射 AC）

| 用例 | 步骤 / 断言（精确） | 覆盖 AC |
|------|-------------------|---------|
| **MKT-T1** TTL 同源 | patch `fetch_json` 捕获 `ttl` 实参 ⇒ `== cache_policy('margin')['ttl'] == 600`；全仓 grep `market_api.py` **无** `600`/`_MARGIN_CACHE_TTL` 字面量 | R16 / A3 |
| **MKT-T2** 成功变换 | 给定 `{'status_code':0,'data':{date:[...],item:[...]}}` ⇒ `latest` = 末条、`recent` 长度 ≤30、金额 = `round(raw/1e8,4)` | 回归 |
| **MKT-T3** 无数据 | `data: {'date': [], 'item': []}` ⇒ `{'latest': None, 'recent': []}`，**无** `_error` | A10（值域） |
| **MKT-T4** 语义失败 | `status_code != 0` ⇒ `fetch_margin` 抛 `FetchError('upstream_error')`；`handle_margin` 返回 `_error='upstream_error'` | A5 |
| **MKT-T5** 网络失败分类 | mock `fetch_json` 抛 `FetchError('upstream_timeout')` ⇒ `handle_margin()['_error'] == 'upstream_timeout'`；`_error` ∈ 枚举（无自由文本） | S6 / A5 |
| **MKT-T6** 总函数性 | mock `fetch_margin` 抛任意异常 ⇒ `handle_margin` **不抛**、返回含 `_error` 的 dict | S1 |
| **MKT-T7** 不重复计数 | mock `fetch_json` 抛 `FetchError('upstream_timeout')`；`metrics.reset()` 后调 `handle_margin()`（**终端缓存为空 ⇒ miss**）⇒ `upstream_fail_total` **无** `upstream_timeout` 增量（cache 主责）；`upstream_fetch_total{margin}` **有**增量（miss 路径） | BR-MKT-8 / S10 |
| **MKT-T8** 期限入口 | `fetch_margin('99', deadline=time()-1)` ⇒ 抛 `upstream_timeout` 且 `fetch_json` **未被调用**（不触网） | S7 |
| **MKT-T9** 字段集合不变 | 成功体与降级体的键集合分别 == §3.1/§3.2（🟠 STABLE） | 端锁定 |
| **MKT-T10** `market` 枚举闸（P7b） | `fetch_margin('1x')` / `fetch_margin('')` / `fetch_margin('99/../admin')` ⇒ 各抛 `FetchError('upstream_error')`、`fetch_json` **未被调用**；合法四值均通过 | §2.1 / 注入防护 |
| **MKT-T11** 期限透传（P7b） | patch `fetch_json` 捕获关键字 ⇒ `deadline` 实参 == 传入值（非 `None`）；`fetch_margin('99', deadline=D)` 在 `D` 未过时**不**抛、调 `fetch_json(deadline=D)` | BR-MKT-11 / AC-E2 |
| **MKT-T12** 逐字段容错（P7b） | 单行含 `rzye='--'`、`rqye='junk'`、`zb='1.23'`、另一行 `items[1]='xxx'`（非 dict） ⇒ **不抛**、`rzye/rqye == 0.0`、`zb == 1.23`（float）、**另一行的有效值保留**、无 `_error`；`_to_float` 对 `None/'--'/''/None→0.0`、`'1.5'→1.5`、`False/{}→0.0` | BR-MKT-12 |
| **MKT-T13** `margin.cache_max`（v1.4 → ★ v1.8 更正） | ★ **`cache_policy('margin')['cache_max'] == 8`**（v1.8 起 margin 有终端缓存；矩阵单元格 = `8`，`config.md` v1.14 / CFG-T13）；`pool_max == 16`、`pool_refresh == 1200`、`ttl == 600` 不变；**矩阵不再把 margin 归入 URL-cache-only**；★ **v1.9**：该 `cache_max` 同时是 `cache_entries{margin}` 的**上界**（LRU 淘汰后 gauge == `cache_max`，见 MKT-T20） | §3.3 / `config.md` CFG-T13 |
| **MKT-T14** 终端缓存命中不取数（★ v1.8） | 先成功取一次（写入 `_margin_cache`）；`metrics.reset()` 后同 `market` 再调 ⇒ `fetch_json` **未被调用**（`json.loads`/`_transform_margin` 亦未跑）、`upstream_fetch_total{margin}` **无增量**、命中返回**同一 payload 对象**；★ **v1.9**：命中路径**另**发布 `cache_entries{margin}`（**锁外**；值 == 当前长度、命中**不增**，见 MKT-T20） | BR-MKT-13 / BR-MKT-16 / BR-MKT-17 |
| **MKT-T15** TTL 过期重取（★ v1.8） | 写入后把 `time.time()` 推进越过 `ttl`（patch）⇒ 再调走 `fetch_json`、`upstream_fetch_total{margin}` **+1** | BR-MKT-13 |
| **MKT-T16** LRU 有界（★ v1.8） | 收紧 `cache_max`（如 patch 到 2）后依次取 3 个不同 `market` ⇒ `len(_margin_cache) <= cache_max`、**最旧键被淘汰**、且 `_margin_cache_ts` 中该键**同步删除**（无幽灵 ts） | BR-MKT-15 |
| **MKT-T17** 失败不缓存（★ v1.8） | mock `fetch_json` 抛 `FetchError` ⇒ `_margin_cache` **不含**该 `market`；再次调用**仍**触发 `fetch_json`（降级体不被复用） | BR-MKT-14 / AC-A10 |
| **MKT-T18** 空数据不缓存（★ v1.8） | 上游返回空 `date`/`item` ⇒ 返回 `{'latest': None, 'recent': []}` 且 `_margin_cache` **不含**该 `market`；再次调用**仍**走 `fetch_json` | BR-MKT-14 / AC-A10 |
| **MKT-T19** 计数仅 miss（★ v1.8） | 连续两次调用（首次成功写缓存）⇒ `upstream_fetch_total{margin}` **仅 +1**（首次 miss）；命中路径 **+0** | BR-MKT-9 |
| **MKT-T20** 终端缓存发布 `cache_entries{margin}`（★ v1.9 / CR-02） | ① **写入**：`metrics.reset()` 后成功取一次 ⇒ `snapshot()['cache_entries']['margin'] == 1`；② **命中**：同 `market` 再调 ⇒ **仍 == 1**（命中不改变长度，仅锁外覆盖同值）；③ **LRU 淘汰**：取满 `cache_max` 后再写第 `cache_max+1` 项 ⇒ `cache_entries{margin} == cache_max` **且** == `len(_margin_cache)`；④ **锁纪律**：两处 `set_gauge` 均在**释放 `_margin_cache_lock` 之后**（复用 `_lock_held_during` 一类断言，或断言发布值 == 真实长度）。落地 = `tests/test_data_layer.py::test_terminal_cache_publishes_cache_entries_gauge` | BR-MKT-17 / AC-S10 / AC-E6 |

---

## 9. AC 追溯矩阵

| 本模块设计点 | 覆盖 AC |
|-------------|---------|
| `cache_policy('margin')['ttl']` 唯一 TTL（BR-MKT-1） | **AC-A3**（TTL 单一权威）/ **AC-E6**（TTL 分层不漂移）/ R16 |
| `handle_margin` 总函数 + `FetchError` 捕获（BR-MKT-6） | **AC-S1**（异常兜底，不裸崩、不抛） |
| `_error` 枚举收敛 + 网络/语义失败分类（BR-MKT-4/7） | **AC-A5**（上游失败 error 客体）/ **AC-S6**（枚举错误码） |
| 无数据 ≠ 失败（BR-MKT-5） | **AC-A10**（值域三分：null/无数据 vs 失败） |
| `upstream_fail_total{kind}` 分类计数（BR-MKT-8） | **AC-S10**（观测） |
| `upstream_fetch_total{margin}`（BR-MKT-9） | AR-6 / Q3⑤（上游负载核算）★ v1.8：**仅终端 miss 计一次**（更准的回源率口径） |
| `deadline` 入口判定（BR-MKT-3） | **AC-S7**（超时兜底）/ **AC-E2**（REST 回源 ≤15s 上界；REV-DES-17 同口径） |
| ★ v1.8：**终端缓存有界（`cache_max=8`）+ 单锁仅护元数据**（§3.4/§7；BR-MKT-13..15） | **AC-S9**（资源总账**有界**不增长）/ **AC-E6**（缓存上限不漂移） |
| ★ v1.8：**命中零解析**（BR-MKT-13，省 `json.loads`+`_transform_margin`，P50 ≈8-9ms） | 延迟改善（PRF-LAT-02）/ **AC-S1**（不裸崩） |
| ★ v1.8：**失败/空数据不写缓存**（BR-MKT-14） | **AC-A10**（值域三分；降级体不被缓存复用） |
| **`VALID_MARKETS` 枚举闸（BR-MKT-10）** | 安全（禁止路径/查询注入与缓存键铸造）/ 端锁定 |
| **`deadline` 透传 `fetch_json`（BR-MKT-11）** | **AC-E2**（REST 回源 ≤15s 上界）/ **AC-S7**（超时兜底） |
| **逐字段数值容错（BR-MKT-12）** | **AC-A5**（上游失败不应把有效数据一起抹掉）/ **AC-S1**（不裸崩） |
| ★ v1.9：**终端缓存可观测**——命中与写入/淘汰均**锁外**发布 `cache_entries{margin}`（BR-MKT-17；值恒 == `len(_margin_cache)`） | **AC-S10**（观测项；`/healthz.metrics` 可查终端缓存条目数）/ **AC-E6**（上限可观测、不漂移） |

---

## 10. 与 SAD / 现有代码的偏差与歧义标注（不擅自改 SAD）

| # | 项 | SAD / PRD 表述 | 本文裁决 | 理由 |
|---|----|---------------|---------|------|
| 1 | margin 降级形态（**REV-DES-11**） | PRD AC-A5 把 `/market/margin` 归入"单体端点 → **error 客体**" | **设计保持**：保留 `{latest, recent, _error}`（`_error` 为枚举 kind）形态，**不改为 `{error}`** | **编排层已裁决（REV-DES-20260915-002）：设计保持；PRD AC-A5 对 margin 的表述将回改**（保留 `_error` 枚举客体，作为"单体 error 客体"的显式子类）并写入验收矩阵——由编排层执行。改 `{error}` 会删既有字段，违反 PRD §7.1 🟠 STABLE 与 SAD §3 |
| 2 | `_error` 取值 | 未定义 | 由自由文本 `str(e)` 收敛为枚举 kind | AC-S6/AC-A10 枚举封闭口径；字段名/类型不变 |
| 3 | `deadline` 形参 | SAD §2.3 D-2 只要求**码级**取数器带 `deadline` | `fetch_margin` 为非码取数器，按命名规则不受限；仍新增可选 `deadline=None`（向后兼容） | 与 `fetch_cls_telegraph(feed_url=None)` 同类；新增可选参数不破坏 server 调用 |
| 4 | `upstream_fetch_total` 计数口径 | SAD §2.6/AR-6 仅说"每域上游取数计数" | 定义为"该域**取数调用次数**"：URL 缓存命中亦计数（上界估计）；直连路径为真实回源。**★ v1.8 更正**：`margin` 口径改为**仅终端缓存 miss 时 +1**（BR-MKT-9）——引入终端缓存后，"URL 缓存命中"不再进入计数路径；与 stock 域（终端 miss 才调 fetcher → 计数）**对齐** | 旧口径（无法在调用点区分 cache 命中、故取上界）在终端缓存引入后**不再必要**且会**高估回源率**（详见 `metrics.md` §3.2 注）；新口径与其余域一致 |
| 5 | `upstream_fail_total` 防重复 owner（**REV-DES-20**） | SAD 未定义 owner 边界；`metrics.md` §3.2 注册表 owner 列**仅** `cache.fetch_json / stock_api`，**未列 `market_api`**（本模块实际写入） | BR-MKT-8 明确"网络失败归 cache、语义失败归 API 层"，**同一次失败只计一次**；`upstream_fail_total` owner 列补 `market_api` **由编排层同步 `metrics.md`**（本 agent 不改基础层文档）——**★ v1.5：✅ 已同步（`metrics.md` v1.7 §3.2 owner 列已补 `market_api`，本轮补登）** | 避免同一故障被两层各计一次导致指标虚高；owner 缺登记会使 MET-T8b/§3.2 的注册表"全名断言"遗漏本模块 |
| 6 | **P7b · `market` 枚举闸** | SAD §2.1 未定义 `market` 值域校验 | 新增模块级 `VALID_MARKETS`（**本模块为定义方**，`server` 导入做边界检查）+ 拼 URL 前的拒绝（BR-MKT-10 / §2.1 / §10#…） | `market` 被插值进路径段：未校验可注入同主机路径/查询，且每个伪造值铸一个 URL 缓存键 |
| 7 | **P7b · `deadline` 透传；★ v1.3 封顶更正** | SAD §2.3 D-2 只要求"期限可传入" | 除入口快速判定外，**把 `deadline` 交给 `fetch_json`**（BR-MKT-11） | 否则通过入口判定的调用仍可跑满 `_fetch_budget`（**v1.3 更正**：故障期该值 = `_PROBE_BUDGET_CAP=5s`，冷期/老化期才是 `REQUEST_TIMEOUT=10s`），越过调用方预算 |
| 9 | **v1.3 · `_PROBE_BUDGET_CAP` 对 margin 的影响（AC-S3 裁决）** | SAD §2.3 D-1 未定义探测阶梯上限 | BR-MKT-11 的封顶表述更正为 `cache._PROBE_BUDGET_CAP=5.0`（**非** `REQUEST_TIMEOUT`）⇒ margin 故障期单次回源 ≤5s；**本模块代码零改动**（约束来自 `cache` 侧） | 与 `cache.md` §4.2 BR-CACHE-22 / `config.md` §2.3 注保持单一口径；旧表述会让读者以为故障期 margin 仍可 10s 回源 |
| 8 | **P7b · 逐字段数值容错 + `_to_float`** | SAD 未定义脏字段行为 | 每个数值单元格独立 `_to_float`（`None`/`'--'`/`''`/junk ⇒ `0.0`）；`items[i]` 非 dict ⇒ 空 dict；`zb` 归一 float（BR-MKT-12） | 旧版 `float(val)` 抛出后 `handle_margin` 把**整份**响应降级为零 ⇒ 一行脏数据抹掉全部有效行（`_DEGRADED_LATEST` 由此改为全 `0.0`，类型与正常体一致） |
| 10 | **v1.4 · `margin.cache_max` 更正** | SAD §2.1 矩阵 `margin` 曾给 16；本文 v1.3 §3.3 仍作 `16` | 实现为 `'n/a'`⇒`None`：margin **只走共享 URL 缓存**，per-domain 上限是运维无法生效的死设置（与 `plate`/`news_url`/`longhu` 同口径） | ★ 该轮唯一"描述与代码不符"项（`config.py:350` vs 本文 v1.3 §3.3）。语义澄清，**该轮本模块不消费 `cache_max`**（`config.md` §3.1/§10#15/CFG-T13 已钉死）。**★ v1.8 更正**：此结论**已被 PRF-LAT-02 推翻**——margin 现有**进程内终端缓存**（`_margin_cache`）⇒ `cache_max` 改 **`8`**、本模块**消费**它（见 §10#11 / `config.md` v1.14 §10#25）。本条保留为**历史口径** |
| 11 | **★ v1.8 · PRF-LAT-02 margin 终端缓存** | SAD §2.1/§2.6 未定义 margin 终端缓存；SAD 按"margin 只走共享 URL 缓存"处理 | 新增模块内 `_margin_cache`(OrderedDict)/`_margin_cache_ts`/`_margin_cache_lock`；`fetch_margin` 命中直接返回**变换后 payload**（零解析、零计数），仅 `latest is not None` 写入并按 `cache_max`(8) LRU 淘汰；`upstream_fetch_total{margin}` 改为**仅 miss 计数**（BR-MKT-9/13..16） | 共享 URL 缓存存**解码文本**，每次命中仍需 `json.loads`+`_transform_margin`（P50 ≈8-9ms）⇒ 终端缓存省去热路径重复解析；`cache_max=8` 为有界内存界（`config.md` v1.14 / BR-CFG-5）；**代价**：命中返回**共享对象**（BR-MKT-16，调用方不得就地改） |
| 12 | **★ v1.9 · `cache_entries{margin}` 发布（P2 收尾 / CR-02）** | SAD §2.6 只登记 `cache_entries{…}` 名与"字典型仪表"形态，**未穷举标签值**；SAD 未定义 margin 终端缓存的"当前条目数"如何可观 | 终端缓存**命中**与**写入/淘汰**两条路径均**锁外**发布 `metrics.set_gauge('cache_entries', len(_margin_cache), key='margin')`（锁内只取 `len`，BR-MKT-17）；`cache_entries` 标签值集合**补 `margin`**（`metrics.md` v1.11 §3.2） | v1.8 只做了终端缓存的读写与 miss 计数，**未把条目数发布到 metrics** ⇒ 运行期无法回答"margin 终端缓存当前几项"（`AC-E6` 上限可观测缺口）。发布纪律对齐 `stock_api._cache_store`（BR-SA-16/26）与 `cache._publish_url_stats`（BR-CACHE-24）；`metrics.py` **零代码变更**（标签值不由 `_KNOWN`/`_DEFAULTS` 冻结，只冻结指标名） |

---

## 11. 交付自检

- [x] 无 `{例:` 占位符；TTL/字段/边界/降级体均为实值
- [x] 每条 BR 有 SAD/PRD 来源，且接口签名精确（参数名/类型/默认/返回/异常）
- [x] §3 为 yaml 代码块（数据结构）；§2 含精确返回与异常
- [x] 与基础层接口逐项对齐（`cache_policy`/`FetchError`/`metrics`）
- [x] 无裸 TTL / 缓存上限字面量；★ v1.8：**新增 1 锁 3 容器**（`_margin_cache`/`_margin_cache_ts`/`_margin_cache_lock`）——**均为经登记的终端缓存**（§1.2/§3.4），非"不必要新容器"
- [x] AC 追溯覆盖 S1/S6/S7/A3/A5/A10/S10/E6（★ v1.8 另覆盖 **AC-S9 有界**）
- [x] **v1.1**：§10#1 更新为 **REV-DES-11 裁决回执**（设计保持，PRD AC-A5 表述回改）；§10#5/BR-MKT-8 的 owner 引据改为"本模块与 cache 的防重复计数约定"（**REV-DES-20**，`metrics.md` owner 列由编排层补登）——**★ v1.5：✅ 已闭环（`metrics.md` v1.7 §3.2 已补 `market_api`）**
- [x] **v1.2（P7b）**：`VALID_MARKETS` 枚举闸（§2.1/BR-MKT-10/MKT-T10）；`deadline` 透传 `fetch_json`（§1.4/§2.1/BR-MKT-11/MKT-T11）
- [x] **v1.2（P7b）**：`_to_float` 逐字段容错 + `zb` 归一 float + `_DEGRADED_LATEST` 全 `0.0`（§2.3/§2.5/§3.1/§3.2/BR-MKT-12/MKT-T12）——§5 伪代码与实现逐行一致
- [x] **v1.3（AC-S3 裁决）**：BR-MKT-11 封顶更正为 `cache._PROBE_BUDGET_CAP=5.0`（§2.1 参数表 / §4.1 BR-MKT-11 / §10#7·#9）；故障期 margin 单次回源上界 **5s**（冷期/老化期 10s）；MKT-T11 断言不变但预算期望值更正
- [x] **v1.4**：§3.3 `margin.cache_max` 由 `16` 更正为 `null`（BR 无改动；§10#10/MKT-T13）；逐项核对 `deadline` 透传/`zb` float/`_to_float`/`_DEGRADED_LATEST=0.0` **四项均与代码一致**
- [x] **v1.6（溯源更正）**：头部上游 **SAD v1.3 → v1.12 / PRD v0.3 → v0.10**；基础层接口权威 **config v1.1 → v1.5 / cache v1.1 → v1.13 / metrics v1.1 → v1.7**；**代码 / 契约 / BR / 测试编号 / 偏差零变更**（v1.5 正文逐字保留）；**未改代码 / SAD / PRD / API.md / README.md / `.opencode`**
- [x] **v1.7（溯源收口 + 引用时点约定）**：上游 **SAD v1.12 / PRD v0.10**（复核无变化）；基础层接口权威 **config v1.5 → v1.6 / cache v1.13 → v1.14 / metrics v1.7 → v1.8**（指向现行版本）；新增「引用时点约定」——接口权威栏 = 本文最后同步时点快照、**落后一版不属漂移**，内容以被引文档头部为准。**代码 / 契约 / BR / 测试编号 / 偏差零变更**；**未改代码 / SAD / PRD / API.md / README.md / `.opencode`**
- [x] **v1.8（PRF-LAT-02 margin 终端缓存 · 以 `market_api.py` 实现为准）**：新增终端缓存三元组（§1.1#4/§1.2/§3.4）；`fetch_margin` 新流程（§2.1/§5：命中直接返回、仅 miss 计数、仅可用数据写入、LRU 有界）；**§3.3 `cache_max` `null`→`8`**；**BR-MKT-9 改写**（仅 miss 计数）+ 新增 **BR-MKT-13..16**；§7 并发安全（新增 `_margin_cache_lock`）；§8 **MKT-T7/T13 更正 + MKT-T14..T19**（6 条新用例，**519 → 525**）；§9/§10#4·#10·#11/§11 同步。**其余契约 / 响应字段集合 / 对外签名零变更**；**本轮只改文档**——代码 / 测试已落地（**525 用例全绿**）；**未改代码 / 测试 / SAD / PRD / API.md / README.md / `.opencode`；`config.md` → v1.14、`metrics.md` → v1.10、`_PROGRESS.md` 同步**
- [x] **v1.9（PRF-LAT-02 P2 收尾（CR-02）· 以 `market_api.py` 实现为准）**：终端缓存**命中路径与写入/淘汰路径**均补**锁外** `metrics.set_gauge('cache_entries', len(_margin_cache), key='margin')`（锁内只取 `len`）——新增 **BR-MKT-17**（§3.4/§4/§7/§8 MKT-T20）；§2.1 注/§1.4/§9/§10#12 同步；§5 伪代码与实现逐行一致（`hit` 分支 + `entries` 锁内取、锁外发布）；模块 docstring 如实化（`fetch_json` 仍为唯一 HTTP 出口，TTL 新鲜的终端缓存命中不再调用它）；§8 **MKT-T13/T14 补 + MKT-T20**（用例 **525 → 526**）。**其余契约 / BR-MKT-1..16 / 响应字段集合 / 对外签名零变更**；**本轮只改文档**——代码 / 测试已落地（**526 用例全绿**）；**未改代码 / 测试 / SAD / PRD / API.md / README.md / `.opencode`；`metrics.md` → v1.11、`_PROGRESS.md` 同步**

---

## 12. 变更记录

| 版本 | 日期 | 说明 |
|------|------|------|
| v1.0 | 2026-09-15 | 首版（批次 2 数据层） |
| v1.1 | 2026-09-15 | 按 `doc/review/数据层三模块_详细设计评审_专家版.md`（REV-DES-20260915-002）修订：**P1 REV-DES-11**（§10#1 改裁决回执：设计保持、PRD 回改）；**P2 REV-DES-20**（BR-MKT-8/§10#5 owner 引据更正，`metrics.md` 同步权归编排层 → ★ **v1.5 更正：✅ 已同步（本轮补登 owner，见 `metrics.md` v1.7 §3.2）**）。**代码/契约形态不变** |
| v1.2 | 2026-09-16 | P7b 契约同步（以 `market_api.py` 实现为准）：`deadline` 透传 `fetch_json`（BR-MKT-11）·`VALID_MARKETS` 枚举闸（BR-MKT-10）·`_to_float` 逐字段容错 + `_DEGRADED_LATEST` 全 `0.0`（BR-MKT-12）。**未改代码** |
| v1.3 | 2026-09-16 | **AC-S3 裁决收尾同步**：BR-MKT-11 的"预算封顶"更正为 `cache._PROBE_BUDGET_CAP=5.0`（非 `REQUEST_TIMEOUT`）⇒ 故障期 margin 单次回源 ≤5s（§2.1/§4.1 BR-MKT-11/§10#7·#9/§11）。**未改代码**（约束来自 `cache` 侧） |
| v1.4 | 2026-09-17 | **P7b 传输层批次契约同步（以 `market_api.py` 实现为准）**：§3.3 `margin.cache_max` 由 `16` 更正为 `null`（URL-cache-only 域归一；§10#10/MKT-T13）。逐项核对 `deadline` 透传、`zb` float、`_to_float` 容错、`_DEGRADED_LATEST=0.0` **均与代码一致**。**未改代码**（**★ v1.8 更正：该行 `null` 口径已由 PRF-LAT-02 推翻——margin 现有终端缓存、`cache_max` = `8`**） |
| v1.2 | 2026-09-16 | **P7b 契约同步（以 `market_api.py` 实现为准）**：`VALID_MARKETS` 枚举闸（拼 URL 前拒绝）·`deadline` 透传 `fetch_json`·`_to_float` 逐字段容错 + `zb` 归一 float + `_DEGRADED_LATEST` 全 `0.0`。新增 BR-MKT-10..12、MKT-T10..T12、§10#6..8。**未改代码** |
| v1.5 | 2026-09-18 | **REV-DES-20 owner 收口（只改文档）**：`metrics.md` §3.2 `upstream_fail_total` owner 列已补 `market_api`（`market_api.py:72/78/145` 语义失败写入点）⇒ §10#5 / §11「由编排层同步」待办闭环；v1.1 历史行加更正注。**本模块代码/契约零变更** |
| v1.6 | 2026-09-18 | **溯源更正（只改文档）**：头部上游 **SAD v1.3 → v1.12**（AC 总数 36）/ **PRD v0.3 → v0.10**（权威以各文档头部为准）；基础层接口权威 **config v1.1 → v1.5 / cache v1.1 → v1.13 / metrics v1.1 → v1.7**。**溯源更正，无内容变更**（本模块代码/契约/BR/测试编号/偏差零变更） |
| v1.7 | 2026-09-18 | **溯源收口 + 引用时点约定（只改文档）**：上游 **SAD v1.12 / PRD v0.10**（复核）；基础层接口权威 **config v1.5 → v1.6 / cache v1.13 → v1.14 / metrics v1.7 → v1.8**（指向现行版本）；新增「引用时点约定」——接口权威栏 = 本文最后同步时点快照，**落后一版不属漂移**，内容以被引文档头部为准。**无内容变更 / 无对外契约变更** |
| v1.8 | 2026-09-20 | **PRF-LAT-02 margin 终端缓存（以 `market_api.py` 实现为准 · 只改文档）**：新增终端缓存三元组 `_margin_cache`(OrderedDict)/`_margin_cache_ts`/`_margin_cache_lock`（§1.1#4/§1.2/§3.4）；`fetch_margin` 流程重写（§2.1/§5：命中直接返回、**仅 miss 计数**、仅 `latest is not None` 写入、LRU 有界）；§3.3 `cache_max` `null` → **`8`**；**BR-MKT-9 改写 + 新增 BR-MKT-13..16**；§7 并发安全；§8 **MKT-T7/T13 更正 + MKT-T14..T19**（用例 **519 → 525**）；§9/§10#4·#10·#11/§11/接口权威栏（config v1.14 / metrics v1.10）同步。**其余契约/响应字段集合/对外签名零变更**；**未改代码 / 测试 / SAD / PRD / API.md / README.md / `.opencode`** |
| v1.9 | 2026-09-20 | **PRF-LAT-02 P2 收尾（CR-02 · 以 `market_api.py` 实现为准 · 只改文档）**：margin 终端缓存的**命中路径与写入/淘汰路径**均补**锁外** `metrics.set_gauge('cache_entries', len(_margin_cache), key='margin')`（锁内只取 `len`），对齐 `stock_api._cache_store`（BR-SA-16/26）；模块 docstring 如实化（`fetch_json` 仍为**唯一 HTTP 出口**，TTL 新鲜的终端缓存命中不再调用它）；新增 **BR-MKT-17**（§1.4/§2.1 注/§3.4/§4/§7/§9/§10#12）；§5 伪代码与实现一致；§8 **MKT-T13/T14 补 + MKT-T20**（用例 **525 → 526**）；接口权威栏 metrics → **v1.11**。**其余契约 / BR-MKT-1..16 / 响应字段集合 / 对外签名零变更**；**未改代码 / 测试 / SAD / PRD / API.md / README.md / `.opencode`** |
