# market_api.py 详细设计

> **版本** v1.4 · **状态** 已契约同步（P7b 传输层批次：以 `china_finance_rss/market_api.py` 实现为准）· **日期** 2026-09-17 · **作者/产出** task-decomposer
> **v1.4 变更（以代码为准）**：① **§3.3 `margin.cache_max` 由 `16` 更正为 `null`**——`config.DOMAIN_MATRIX` 的 `margin` 行为 `[L4, 2.0, 2.0, 'fixed:16', 'n/a']`，`cache_policy('margin')['cache_max']` 归一化为 `None`（margin 仅走共享 URL 缓存，`cache.MAX_CACHE_SIZE=2000` 全局约束；per-domain 上限是运维无法生效的死设置，`config.md` §3.1/§10#15 已钉死）。★ **这是本模块本轮唯一的"描述与代码不符"项**。
> **本轮逐项核对结论（清单 vs 代码）**：`fetch_margin` 透传 `deadline`（BR-MKT-11）✅ 已在 v1.3 记载；`zb` 归一为 float ✅；`_to_float` 逐字段容错 ✅；`_DEGRADED_LATEST` 全 `0.0` ✅。**四项均与代码一致，无需改动**（`market_api.py` 代码零变更）。
> **v1.3 变更（AC-S3 裁决 · 收尾契约同步）**：⑤ **BR-MKT-11 的"预算封顶"更正**——`fetch_json` 的 `deadline` 透传使 `urlopen` 超时 = `cache._effective_timeout` = `min(_fetch_budget(url), max(0.05, 剩余 deadline))`；其中 `_fetch_budget` 的**阶梯封顶是 `cache._PROBE_BUDGET_CAP=5.0`**（**不是** `REQUEST_TIMEOUT(10s)`）。`REQUEST_TIMEOUT` 仅在"无失败历史 / 已老化"两支作冷/全预算探测 ⇒ **margin 在故障期的单次回源上界实际 ≤5s**（旧表述"可跑满固定 `REQUEST_TIMEOUT`"仅在冷预算期成立）。
> 本版修订（P7b 契约同步，**只改文档、不改代码**）：① `fetch_margin` 把 `deadline` **透传给 `fetch_json`**（`urlopen` 超时随预算收缩）；② `zb` **归一为 float**、`_transform_margin` **逐字段容错**（新增 `_to_float`）；③ **`_DEGRADED_LATEST` 为 `0.0`**（float）；④ 新增 **`VALID_MARKETS` 枚举闸**（URL 拼装前拒绝非法 `market`）。
> 沿用 v1.1：REV-DES-20260915-002（REV-DES-11 裁决回执 + REV-DES-20 owner 引据更正）
> 模块路径 `china_finance_rss/market_api.py` · 归属 **Layer 2（业务/数据获取层）**
> 上游 SAD `doc/arch/SAD.md` **v1.3**（§2.1 `cache_policy` / §2.3 D-1 `FetchError` / §3 `market_api.py` 行 / ADR-001/005/008）
> 上游 PRD `doc/prd/perf-stability-optimization.md` v0.3（AC-S1 / AC-S10 / AC-A5；R16）
> 基础层接口权威 `doc/detailed/config.md` v1.1 · `cache.md` v1.1 · `metrics.md` v1.1
> 端锁定 🟠 STABLE（响应字段集合不变；仅 `_error` 取值由自由文本收敛为**枚举错误码**）

## 1. 模块职责与边界

### 1.1 职责

1. **融资融券（margin）单体端点**的取数与格式化：`fetch_margin`（上游取数 + 变换）/ `handle_margin`（对外 handler 形态）。
2. **TTL 来源收敛（R16）**：`_MARGIN_CACHE_TTL(600)` 删除，改读 `config.cache_policy('margin')['ttl']`（值不变 = 600，见 `config.md` §3.2）。
3. **失败分类参与观测（SAD §3 market_api 行）**：把"上游语义失败"（`status_code != 0`）编码为 `FetchError('upstream_error')` 并计入 `metrics`。

### 1.2 明确不做

- **不实现 `handle_margin` 之外的任何端点**（本模块仅 margin；`/ths/longhu` 属 `server.py`，`/cls/hotplate` 属 `server.py`）。
- **不新增缓存容器**：margin 数据只有 URL 级缓存（`cache.fetch_json` 的 `cache{}`），本模块**不持有** `_margin_cache`/锁/metrics 私有状态。
- **不做降级重试 / 熔断**：失败即降级体，重试抑制由 `cache.fetch_json` 负缓存（`NEG_TTL=5s`）承担（ADR-003）。
- **不改 `_transform_margin` 的输出字段与数值口径**（单位换算 1e8、`recent` 取末 30 条等）——纯保留。

### 1.3 layerIsolation 约束

`tech-stack.json` 的 `layerIsolation` **未对 `market_api.py` 单列条目**（其 `forbiddenImports` 仅约束 cache/config/cdp_engine/metrics）。本模块仍须遵守项目分层方向：

```
允许 import：
  标准库：json / logging / time
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
| `config.cache_policy('margin') -> dict` | 取 `['ttl']`（=600）。**禁止**出现裸 TTL 字面量（BR-CFG-12） |
| `config.VALID_MARKETS`（本模块定义、`server` 导入） | ★ **P7b**：`('99','1','2','3')` 枚举；URL 拼装**之前**的边界校验点（§2.1） |
| `cache.fetch_json(url, headers, ttl=..., deadline=...) -> str` | 唯一取数入口；失败**恒** `raise FetchError(kind)`（四段式，含负缓存）；★ **P7b**：`deadline` 透传 ⇒ `urlopen` 超时 = `min(cache._fetch_budget(url), 剩余预算)` |
| `cache.FetchError(kind).kind` | ∈ `{upstream_timeout, upstream_error, cdp_unavailable}`；本模块只会收到前两者 |
| `metrics.incr(name, n=1, key=None)` | `upstream_fetch_total{domain='margin'}`、`upstream_fail_total{kind}` |

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
  cache_max: null          # ★ v1.4 更正（原记 16）：URL-cache-only 域 ⇒ 'n/a'→None（条目由 cache.MAX_CACHE_SIZE 全局约束）
```

> 本模块**不消费** `pool_refresh`/`pool_max`/`cache_max`：margin 是单键端点、无按码去重池、无终点缓存。TTL 由 `fetch_json` 的 URL 缓存生效。

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
| **BR-MKT-9** | `upstream_fetch_total{domain}` 的 `domain` 恒为 `'margin'`；每次**上游取数调用**计数一次（本域经 URL 缓存时可能为命中 → 上界估计口径，见 §10#4） | AR-6 / Q3⑤ |
| **BR-MKT-10** | **`market` 枚举闸（P7b）**：`market ∉ VALID_MARKETS('99','1','2','3')` ⇒ **在拼出 URL 之前** `raise FetchError('upstream_error', url=_MARGIN_URL)`，**不触网**。禁止把任意字符串插值进路径段 | §2.1 / 注入与"每错值一缓存键"防护 |
| **BR-MKT-11** | **`deadline` 透传（P7b；★ v1.3 封顶更正）**：`fetch_json(url, headers, ttl=..., deadline=deadline)` —— 网络超时由 `cache._effective_timeout` 取 `min(_fetch_budget(url), max(0.05, 剩余))`。其中 `_fetch_budget(url)` 三支：**无失败历史 → `REQUEST_TIMEOUT(10s)`**；**失败段已老化（≥`_HISTORY_AGE=600s`）→ `REQUEST_TIMEOUT(10s)`**；**有失败历史且未老化 → `_probe_budget(fail_count)` 阶梯 `2→4→_PROBE_BUDGET_CAP(5s)` 封顶**——⇒ **故障期（负缓存已有条目）的 margin 单次回源上界 = 5s，而非 10s**。入口前置判定（BR-MKT-3）保留为"已过即抛、不触网"的快速路径，**不替代**透传（否则通过入口判定的调用仍可跑满 `_fetch_budget`） | SAD §2.3 D-2 / AC-E2 / `cache.md` §4.2 BR-CACHE-22（**AC-S3 裁决**） |
| **BR-MKT-12** | **逐字段数值容错（P7b / P2-8）**：每个数值单元格独立经 `_to_float`（`None`/`'--'`/`''`/不可解析 ⇒ `0.0`）；`items[i]` 非 dict ⇒ 按空 dict 处理。**禁止**让单个脏字段/脏行使整份响应退化为降级体 | §2.3/§2.5 |

---

## 5. 伪代码

```python
import json
import logging
import time

from . import metrics
from .cache import FetchError, fetch_json
from .config import _MARGIN_HEADERS, _MARGIN_URL, cache_policy

log = logging.getLogger('market')

# market 契约枚举（§2.1）：'99'=合计 / '1'=沪 / '2'=深 / '3'=京。
# 单一权威 —— server.py 导入它做边界检查，故路由层与 URL 构造层的枚举不会漂移。
VALID_MARKETS = ('99', '1', '2', '3')

_DEGRADED_LATEST = {'rzye': 0.0, 'rqye': 0.0, 'rzmre': 0.0,
                    'rzjmr': 0.0, 'rqjmc': 0.0, 'lr': 0.0, 'zb': 0.0}   # ★ 全 float


def _degraded(kind):
    if kind not in FetchError.KINDS:          # BR-MKT-7：枚举封闭
        kind = 'upstream_error'
    return {'latest': dict(_DEGRADED_LATEST), 'recent': [], '_error': kind}


def fetch_margin(market='99', deadline=None):
    """BR-MKT-1..5/10/11：唯一取数入口 + 枚举闸 + 期限入口判定与透传 + 语义失败编码。"""
    if market not in VALID_MARKETS:                        # ★ BR-MKT-10：拼 URL 之前
        raise FetchError('upstream_error', url=_MARGIN_URL)
    url = f'{_MARGIN_URL}/{market}/'
    ttl = cache_policy('margin')['ttl']                    # BR-MKT-1：唯一权威
    if deadline is not None and time.time() >= deadline:   # BR-MKT-3：入口即抛、不触网
        raise FetchError('upstream_timeout', url=url)

    metrics.incr('upstream_fetch_total', key='margin')     # BR-MKT-9
    try:
        raw = json.loads(fetch_json(url, _MARGIN_HEADERS,  # BR-MKT-2
                                    ttl=ttl, deadline=deadline))   # ★ BR-MKT-11：期限透传
    except FetchError:
        raise                                              # BR-MKT-8：cache 已计数，不重复
    except Exception as exc:                               # JSON 解码等
        metrics.incr('upstream_fail_total', key='upstream_error')
        raise FetchError('upstream_error', url=url, cause=exc) from exc

    if not isinstance(raw, dict):
        return {'latest': None, 'recent': []}              # BR-MKT-5：无数据
    if raw.get('status_code') != 0:                        # BR-MKT-4：语义失败
        metrics.incr('upstream_fail_total', key='upstream_error')
        raise FetchError('upstream_error', url=url)
    return _transform_margin(raw.get('data') or {})        # BR-MKT-5


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

**降级路径**：本模块降级**只降级响应体形态**，不降级为异常外抛（`handle_*` 约定）。上游故障期的请求放大由 `cache` 负缓存（`NEG_TTL=5s`）抑制，本模块无需重试逻辑。

---

## 7. 并发安全

| 项 | 结论 |
|----|------|
| 本模块持有的锁 | **无**（无模块级可变状态：无缓存容器、无计数器） |
| `cache_policy('margin')` | 纯函数、无锁、纳秒级；可在锁内调用（`config.md` §7） |
| `fetch_json` | 内部自有 `_cache_lock`/`_neg_lock`，网络 IO 不持锁；本模块不与其并发结构交互 |
| `metrics.incr/set_gauge` | 叶子锁（`metrics._lock` 永远最内层）；本模块调用点均在锁外 |
| 锁序 | 本模块**不引入**任何锁序；不存在嵌套加锁 |

> `handle_margin` 可被主池 20 worker 并发调用；因无共享可变状态，天然线程安全。

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
| **MKT-T7** 不重复计数 | mock `fetch_json` 抛 `FetchError('upstream_timeout')`；`metrics.reset()` 后调 `handle_margin()` ⇒ `upstream_fail_total` **无** `upstream_timeout` 增量（cache 主责）；`upstream_fetch_total{margin}` 有增量 | BR-MKT-8 / S10 |
| **MKT-T8** 期限入口 | `fetch_margin('99', deadline=time()-1)` ⇒ 抛 `upstream_timeout` 且 `fetch_json` **未被调用**（不触网） | S7 |
| **MKT-T9** 字段集合不变 | 成功体与降级体的键集合分别 == §3.1/§3.2（🟠 STABLE） | 端锁定 |
| **MKT-T10** `market` 枚举闸（P7b） | `fetch_margin('1x')` / `fetch_margin('')` / `fetch_margin('99/../admin')` ⇒ 各抛 `FetchError('upstream_error')`、`fetch_json` **未被调用**；合法四值均通过 | §2.1 / 注入防护 |
| **MKT-T11** 期限透传（P7b） | patch `fetch_json` 捕获关键字 ⇒ `deadline` 实参 == 传入值（非 `None`）；`fetch_margin('99', deadline=D)` 在 `D` 未过时**不**抛、调 `fetch_json(deadline=D)` | BR-MKT-11 / AC-E2 |
| **MKT-T12** 逐字段容错（P7b） | 单行含 `rzye='--'`、`rqye='junk'`、`zb='1.23'`、另一行 `items[1]='xxx'`（非 dict） ⇒ **不抛**、`rzye/rqye == 0.0`、`zb == 1.23`（float）、**另一行的有效值保留**、无 `_error`；`_to_float` 对 `None/'--'/''/None→0.0`、`'1.5'→1.5`、`False/{}→0.0` | BR-MKT-12 |
| **MKT-T13** `margin.cache_max` 归一（v1.4） | `cache_policy('margin')['cache_max'] is None`（矩阵单元格仍为 `'n/a'`）；`pool_max == 16`、`pool_refresh == 1200`、`ttl == 600` 不变 | §3.3 / `config.md` CFG-T13 |

---

## 9. AC 追溯矩阵

| 本模块设计点 | 覆盖 AC |
|-------------|---------|
| `cache_policy('margin')['ttl']` 唯一 TTL（BR-MKT-1） | **AC-A3**（TTL 单一权威）/ **AC-E6**（TTL 分层不漂移）/ R16 |
| `handle_margin` 总函数 + `FetchError` 捕获（BR-MKT-6） | **AC-S1**（异常兜底，不裸崩、不抛） |
| `_error` 枚举收敛 + 网络/语义失败分类（BR-MKT-4/7） | **AC-A5**（上游失败 error 客体）/ **AC-S6**（枚举错误码） |
| 无数据 ≠ 失败（BR-MKT-5） | **AC-A10**（值域三分：null/无数据 vs 失败） |
| `upstream_fail_total{kind}` 分类计数（BR-MKT-8） | **AC-S10**（观测） |
| `upstream_fetch_total{margin}`（BR-MKT-9） | AR-6 / Q3⑤（上游负载核算） |
| `deadline` 入口判定（BR-MKT-3） | **AC-S7**（超时兜底）/ **AC-E2**（REST 回源 ≤15s 上界；REV-DES-17 同口径） |
| 无共享可变状态、无锁（§7） | **AC-S9**（资源总账不增长） |
| **`VALID_MARKETS` 枚举闸（BR-MKT-10）** | 安全（禁止路径/查询注入与缓存键铸造）/ 端锁定 |
| **`deadline` 透传 `fetch_json`（BR-MKT-11）** | **AC-E2**（REST 回源 ≤15s 上界）/ **AC-S7**（超时兜底） |
| **逐字段数值容错（BR-MKT-12）** | **AC-A5**（上游失败不应把有效数据一起抹掉）/ **AC-S1**（不裸崩） |

---

## 10. 与 SAD / 现有代码的偏差与歧义标注（不擅自改 SAD）

| # | 项 | SAD / PRD 表述 | 本文裁决 | 理由 |
|---|----|---------------|---------|------|
| 1 | margin 降级形态（**REV-DES-11**） | PRD AC-A5 把 `/market/margin` 归入"单体端点 → **error 客体**" | **设计保持**：保留 `{latest, recent, _error}`（`_error` 为枚举 kind）形态，**不改为 `{error}`** | **编排层已裁决（REV-DES-20260915-002）：设计保持；PRD AC-A5 对 margin 的表述将回改**（保留 `_error` 枚举客体，作为"单体 error 客体"的显式子类）并写入验收矩阵——由编排层执行。改 `{error}` 会删既有字段，违反 PRD §7.1 🟠 STABLE 与 SAD §3 |
| 2 | `_error` 取值 | 未定义 | 由自由文本 `str(e)` 收敛为枚举 kind | AC-S6/AC-A10 枚举封闭口径；字段名/类型不变 |
| 3 | `deadline` 形参 | SAD §2.3 D-2 只要求**码级**取数器带 `deadline` | `fetch_margin` 为非码取数器，按命名规则不受限；仍新增可选 `deadline=None`（向后兼容） | 与 `fetch_cls_telegraph(feed_url=None)` 同类；新增可选参数不破坏 server 调用 |
| 4 | `upstream_fetch_total` 计数口径 | SAD §2.6/AR-6 仅说"每域上游取数计数" | 定义为"该域**取数调用次数**"：URL 缓存命中亦计数（上界估计）；直连路径为真实回源 | 无法在调用点区分 cache 命中；AR-6 目标是核对**负载增幅量级**，上界口径足够（登记为口径细化） |
| 5 | `upstream_fail_total` 防重复 owner（**REV-DES-20**） | SAD 未定义 owner 边界；`metrics.md` §3.2 注册表 owner 列**仅** `cache.fetch_json / stock_api`，**未列 `market_api`**（本模块实际写入） | BR-MKT-8 明确"网络失败归 cache、语义失败归 API 层"，**同一次失败只计一次**；`upstream_fail_total` owner 列补 `market_api` **由编排层同步 `metrics.md`**（本 agent 不改基础层文档） | 避免同一故障被两层各计一次导致指标虚高；owner 缺登记会使 MET-T8b/§3.2 的注册表"全名断言"遗漏本模块 |
| 6 | **P7b · `market` 枚举闸** | SAD §2.1 未定义 `market` 值域校验 | 新增模块级 `VALID_MARKETS`（**本模块为定义方**，`server` 导入做边界检查）+ 拼 URL 前的拒绝（BR-MKT-10 / §2.1 / §10#…） | `market` 被插值进路径段：未校验可注入同主机路径/查询，且每个伪造值铸一个 URL 缓存键 |
| 7 | **P7b · `deadline` 透传；★ v1.3 封顶更正** | SAD §2.3 D-2 只要求"期限可传入" | 除入口快速判定外，**把 `deadline` 交给 `fetch_json`**（BR-MKT-11） | 否则通过入口判定的调用仍可跑满 `_fetch_budget`（**v1.3 更正**：故障期该值 = `_PROBE_BUDGET_CAP=5s`，冷期/老化期才是 `REQUEST_TIMEOUT=10s`），越过调用方预算 |
| 9 | **v1.3 · `_PROBE_BUDGET_CAP` 对 margin 的影响（AC-S3 裁决）** | SAD §2.3 D-1 未定义探测阶梯上限 | BR-MKT-11 的封顶表述更正为 `cache._PROBE_BUDGET_CAP=5.0`（**非** `REQUEST_TIMEOUT`）⇒ margin 故障期单次回源 ≤5s；**本模块代码零改动**（约束来自 `cache` 侧） | 与 `cache.md` §4.2 BR-CACHE-22 / `config.md` §2.3 注保持单一口径；旧表述会让读者以为故障期 margin 仍可 10s 回源 |
| 8 | **P7b · 逐字段数值容错 + `_to_float`** | SAD 未定义脏字段行为 | 每个数值单元格独立 `_to_float`（`None`/`'--'`/`''`/junk ⇒ `0.0`）；`items[i]` 非 dict ⇒ 空 dict；`zb` 归一 float（BR-MKT-12） | 旧版 `float(val)` 抛出后 `handle_margin` 把**整份**响应降级为零 ⇒ 一行脏数据抹掉全部有效行（`_DEGRADED_LATEST` 由此改为全 `0.0`，类型与正常体一致） |
| 10 | **v1.4 · `margin.cache_max` 更正** | SAD §2.1 矩阵 `margin` 曾给 16；本文 v1.3 §3.3 仍作 `16` | 实现为 `'n/a'`⇒`None`：margin **只走共享 URL 缓存**，per-domain 上限是运维无法生效的死设置（与 `plate`/`news_url`/`longhu` 同口径） | ★ 本轮唯一"描述与代码不符"项（`config.py:350` vs 本文 v1.3 §3.3）。语义澄清，**本模块不消费 `cache_max`** ⇒ 无行为回归（`config.md` §3.1/§10#15/CFG-T13 已钉死） |

---

## 11. 交付自检

- [x] 无 `{例:` 占位符；TTL/字段/边界/降级体均为实值
- [x] 每条 BR 有 SAD/PRD 来源，且接口签名精确（参数名/类型/默认/返回/异常）
- [x] §3 为 yaml 代码块（数据结构）；§2 含精确返回与异常
- [x] 与基础层接口逐项对齐（`cache_policy`/`FetchError`/`metrics`）
- [x] 无裸 TTL 字面量；无新增锁；无不必要新容器
- [x] AC 追溯覆盖 S1/S6/S7/A3/A5/A10/S10/E6
- [x] **v1.1**：§10#1 更新为 **REV-DES-11 裁决回执**（设计保持，PRD AC-A5 表述回改）；§10#5/BR-MKT-8 的 owner 引据改为"本模块与 cache 的防重复计数约定"（**REV-DES-20**，`metrics.md` owner 列由编排层补登）
- [x] **v1.2（P7b）**：`VALID_MARKETS` 枚举闸（§2.1/BR-MKT-10/MKT-T10）；`deadline` 透传 `fetch_json`（§1.4/§2.1/BR-MKT-11/MKT-T11）
- [x] **v1.2（P7b）**：`_to_float` 逐字段容错 + `zb` 归一 float + `_DEGRADED_LATEST` 全 `0.0`（§2.3/§2.5/§3.1/§3.2/BR-MKT-12/MKT-T12）——§5 伪代码与实现逐行一致
- [x] **v1.3（AC-S3 裁决）**：BR-MKT-11 封顶更正为 `cache._PROBE_BUDGET_CAP=5.0`（§2.1 参数表 / §4.1 BR-MKT-11 / §10#7·#9）；故障期 margin 单次回源上界 **5s**（冷期/老化期 10s）；MKT-T11 断言不变但预算期望值更正
- [x] **v1.4**：§3.3 `margin.cache_max` 由 `16` 更正为 `null`（BR 无改动；§10#10/MKT-T13）；逐项核对 `deadline` 透传/`zb` float/`_to_float`/`_DEGRADED_LATEST=0.0` **四项均与代码一致**

---

## 12. 变更记录

| 版本 | 日期 | 说明 |
|------|------|------|
| v1.0 | 2026-09-15 | 首版（批次 2 数据层） |
| v1.1 | 2026-09-15 | 按 `doc/review/数据层三模块_详细设计评审_专家版.md`（REV-DES-20260915-002）修订：**P1 REV-DES-11**（§10#1 改裁决回执：设计保持、PRD 回改）；**P2 REV-DES-20**（BR-MKT-8/§10#5 owner 引据更正，`metrics.md` 同步权归编排层）。**代码/契约形态不变** |
| v1.2 | 2026-09-16 | P7b 契约同步（以 `market_api.py` 实现为准）：`deadline` 透传 `fetch_json`（BR-MKT-11）·`VALID_MARKETS` 枚举闸（BR-MKT-10）·`_to_float` 逐字段容错 + `_DEGRADED_LATEST` 全 `0.0`（BR-MKT-12）。**未改代码** |
| v1.3 | 2026-09-16 | **AC-S3 裁决收尾同步**：BR-MKT-11 的"预算封顶"更正为 `cache._PROBE_BUDGET_CAP=5.0`（非 `REQUEST_TIMEOUT`）⇒ 故障期 margin 单次回源 ≤5s（§2.1/§4.1 BR-MKT-11/§10#7·#9/§11）。**未改代码**（约束来自 `cache` 侧） |
| v1.4 | 2026-09-17 | **P7b 传输层批次契约同步（以 `market_api.py` 实现为准）**：§3.3 `margin.cache_max` 由 `16` 更正为 `null`（URL-cache-only 域归一；§10#10/MKT-T13）。逐项核对 `deadline` 透传、`zb` float、`_to_float` 容错、`_DEGRADED_LATEST=0.0` **均与代码一致**。**未改代码** |
| v1.2 | 2026-09-16 | **P7b 契约同步（以 `market_api.py` 实现为准）**：`VALID_MARKETS` 枚举闸（拼 URL 前拒绝）·`deadline` 透传 `fetch_json`·`_to_float` 逐字段容错 + `zb` 归一 float + `_DEGRADED_LATEST` 全 `0.0`。新增 BR-MKT-10..12、MKT-T10..T12、§10#6..8。**未改代码** |
