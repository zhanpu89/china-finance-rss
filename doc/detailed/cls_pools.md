# cls_pools（财联社 4 池独立接口）详细设计

> **版本** v1.0.5 · **状态** 🟡 草稿（P3a 详设增量，待评审）· **日期** 2026-10-10 · **作者/产出** task-decomposer
> 模块路径 `china_finance_rss/server.py`（**增量**：新增 1 个 handler + 1 张分发表 + 4 条路由分支；**无新模块文件**）· 归属 **Layer 3（HTTP 入口 / 编排层）**
> 需求来源：本任务书「财联社 4 池独立接口」——从 `https://www.cls.cn/finance` 看盘页把「涨停池 / 连板池 / 炸板池 / 跌停池」4 个 tab 数据分离为 4 个独立 HTTP JSON 接口
> 上游契约（**已实测定案，禁止再探测 / 改参数**）：`https://x-quote.cls.cn/quote/index/up_down_analysis`
> 参考实现（**命名 / 分层 / 异常风格必须与之一致**）：`server.py:337 handle_cls_hotplate` · `server.py:482-535` 三张注册表 + 断言 · `server.py:1218-1261` 分发分支 · `config.py:219-225` CLS 系 URL/Header 常量模式 · `utils.py:80 cls_sign_params`
> 关联详设：`doc/detailed/server.md`（路由 / `_guard` / `_send_json_shape` 权威）· `market_api.md`（`handle_*` 总函数 / 降级体形态参照）· `config.md`（`cache_policy` / `DOMAIN_MATRIX`）· `cache.md`（`fetch_json`）——**各文档版本以其自身头部为准**
> 端锁定 🟠 STABLE（**只增 4 个端点**；不改既有路由 / 签名 / 既有响应字段集合）

## 1. 模块职责与边界

### 1.1 职责（5 条）

1. **4 个独立 REST 端点**的取数与格式化：`/cls/up_pool`（涨停池）/ `/cls/continuous_up_pool`（连板池）/ `/cls/up_open_pool`（炸板池）/ `/cls/down_pool`（跌停池）——**路径镜像上游 `type` 命名**（同 `/cls/hotplate` 族）。
2. **单函数 `handle_cls_pool(pool_type) -> dict`**：拼签名 URL（`cls_sign_params`）→ `fetch_json(url, _UP_DOWN_ANALYSIS_HEADERS, ttl=cache_policy('plate')['ttl'])` → 解析信封 → 成功 `{'stocks': [...]}`、`data` 非 list ⇒ fail-loud `{'error': ...}`（**P1-02**）、失败 `{'error': ...}`。
3. **表驱动分发**：`_POOL_HANDLERS = {路径: type}`（4 项，仿 `_PANEL_HANDLERS` 表驱动分发，`server.py:505`）；路由分支只从该表取值，**不写死 type 字面量**。
4. **走直连 REST**（同 `/cls/hotplate` 模式）：**不走 CDP、不走 batch、不走 `_fetch_concurrent`**（每池 = 单 URL 单次取数）。
5. **注册面收口**（7+ 处，见 §2.5）：config 常量 + `_JSON_SHAPES` + `_JSON_DISPATCHED_PATHS` + `_CACHE_AGE_DOMAINS` + 分发分支 + `feeds[]` + 测试计数。

### 1.2 明确不做

- **不走 CDP**：4 池均为直连 `x-quote.cls.cn` REST，无 Chrome 依赖（与 `/cls/hotplate`、`/cls/plate` 同族）。
- **不走 batch / 不并发扇出**：单 URL 单次 `fetch_json`，无需 `_fetch_concurrent` / `_FANOUT_MAX_WORKERS`。
- **不新增缓存容器**：复用共享 URL 缓存（`cache.fetch_json`），域 = `plate`；**不持有**任何模块级终端缓存。
- **不新增 metrics**：不引入新注册名（复用 cache 的 URL 级统计）。
- **不改既有 18 个 JSON 端点 / 5 个 RSS / `/healthz` 的既有契约**（仅 `_JSON_SHAPES` 只增 4 条 + `feeds[]` 只增 4 条）。
- **不改签名算法**：`cls_sign_params` 原样调用；参数集与 `way=last_px` 已实测定案（见 §2.4）。
- **不做鉴权 / 多租户 / 前端 / 小程序**（纯后端只读端点）。

### 1.3 layerIsolation 约束

`tech-stack.json` 未对 `server.py` 单列 `layerIsolation` 条目；本增量须遵守既有分层方向与 allowlist：

```
允许 import（本增量新增面）：
  包内  ：config（新增 `_UP_DOWN_ANALYSIS_URL` / `_UP_DOWN_ANALYSIS_HEADERS` 两个常量）
  既有  ：utils.cls_sign_params、cache.fetch_json、urllib.parse.urlencode、json
禁止 import：新增第三方库；`china_finance_rss/` 之外的第二个代码根
```

**依赖方向**（`←` 表分层顺序，非 import 关系）：

```
Layer 0: config（常量 + cache_policy）
Layer 1: cache（fetch_json）
Layer 3: server ← {config, cache, utils, ...}
```

> 本增量**不新增跨模块边**：`server → config`（既有）、`server → utils`（既有）、`server → cache`（既有）——均为既有方向，**无环**。

### 1.4 与基础层接口的对齐（不得偏离）

| 接口 | 本增量用法 |
|------|-----------|
| `config._UP_DOWN_ANALYSIS_URL` | 上游 URL 常量（`config.py:219` 附近新增，仿 `_HOTPLATE_BASE_URL`）；**禁止**在 `server.py` 硬编码 URL |
| `config._UP_DOWN_ANALYSIS_HEADERS` | 请求头 `{'User-Agent': 'Mozilla/5.0', 'Referer': 'https://www.cls.cn/finance'}`（仿 `_HOTPLATE_HEADERS`） |
| `config.cache_policy('plate')['ttl']` | TTL **唯一来源**（`plate` = L2 档：**盘中 12s / 非盘 120s**）；**禁止**裸 TTL 字面量（BR-CFG-12） |
| `utils.cls_sign_params(params) -> str` | 签名（内部按 key 排序 ⇒ 调用方传参顺序无关） |
| `cache.fetch_json(url, headers, ttl=) -> str` | **唯一 HTTP 出口**；失败恒 `raise FetchError(kind)`（负缓存 / 分类由 cache 承担） |
| `server._send_json_shape(path, fn)` | 分发 + `_guard` 降级（`object` shape ⇒ 200 + error body，N1） |

---

## 2. 接口契约

### 2.1 路由总表（OpenAPI 风格，**唯一权威**）

```yaml
openapi: 3.0.3
info: {title: china-finance-rss CLS pools, version: '1.0'}
paths:
  '/cls/up_pool':            {get: {responses: {'200': {description: '涨停池 {"stocks":[...]}；降级 {"error":"..."}（均 200）'}}}}          # shape=object · type=up_pool
  '/cls/continuous_up_pool': {get: {responses: {'200': {description: '连板池 {"stocks":[...]}；降级 {"error":"..."}（均 200）'}}}}          # shape=object · type=continuous_up_pool
  '/cls/up_open_pool':       {get: {responses: {'200': {description: '炸板池 {"stocks":[...]}；降级 {"error":"..."}（均 200）'}}}}          # shape=object · type=up_open_pool
  '/cls/down_pool':          {get: {responses: {'200': {description: '跌停池 {"stocks":[...]}；降级 {"error":"..."}（均 200）'}}}}          # shape=object · type=down_pool
# 无 query 参数；无请求体；无鉴权；HTTP 方法仅 GET（HEAD 由基类统一处理）
# 未注册路径 → 404（既有行为不变）
```

**HTTP 状态语义（唯一口径）**

| 情形 | 状态 / 体 |
|------|----------|
| 上游成功（`code==200`） | `200` + `{"stocks":[...]}`（可为空 list） |
| 上游成功（`code==200`）但 `data` 非 list | `200` + `{"error":"upstream data shape unexpected: <type>"}`（**fail-loud**，BR-POOL-6 / **P1-02**；**禁止**静默 `{"stocks": []}`） |
| 上游 `code != 200`（如错 `way` 返回 9000） | `200` + `{"error":"<msg>"}` |
| 取数失败 / JSON 解码失败 / handler 抛异常（`_guard` 兜底） | `200` + `{"error":"<str>"}`（**N1：状态码不由 payload 内容决定**） |
| 非法 `pool_type`（直接调用 handler，非路由） | `200` + `{"error":"..."}`、**不触网** |
| 未知路径 | `404`（既有 `send_error`） |

### 2.2 `handle_cls_pool(pool_type) -> dict`

```python
def handle_cls_pool(pool_type):
```

| 参数 | 类型 | 语义 |
|------|------|------|
| `pool_type` | `str` | ∈ `{'up_pool','continuous_up_pool','up_open_pool','down_pool'}`（= `_POOL_HANDLERS` 值域，**单一权威**）；非法值 ⇒ `{'error': 'unknown pool type: ...'}`、**在拼 URL 之前、不触网** |

- **总函数**：任意输入 / 任意上游状态都返回 `dict`，**绝不抛**（项目约定 `handle_*` 返回 dict 不抛）。
- 成功 → `{'stocks': [...]}`（`stocks` 为上游 `data` 裸 list）；**`data` 非 list ⇒ `{'error': 'upstream data shape unexpected: <type>'}`**（fail-loud，BR-POOL-6 / **P1-02**，`<type>` = `type(data).__name__`）；失败 → `{'error': <str>}`。
- 消费者：`_handle_request` 分发分支 → `_send_json_shape(path, lambda pt=pool_type: handle_cls_pool(pt))`。
- **签名不变式**：与 `handle_cls_hotplate(feed_url=None)` 同类（无 `feed_url` 形参，因不需回链）；**不封装请求对象**（参数平铺）。

### 2.3 `_POOL_HANDLERS`（分发表，**唯一权威**）

```python
# 4 CLS pools → upstream `type`（路径镜像 type；表驱动，仿 _PANEL_HANDLERS）
_POOL_HANDLERS = {
    '/cls/up_pool': 'up_pool',
    '/cls/continuous_up_pool': 'continuous_up_pool',
    '/cls/up_open_pool': 'up_open_pool',
    '/cls/down_pool': 'down_pool',
}
_POOL_TYPES = frozenset(_POOL_HANDLERS.values())   # 值域单一权威（handler 校验用）
```

- **定义位置**：模块级，紧邻 `_PANEL_HANDLERS`（`server.py:505` 附近）——**必须在 `server.py:514` 的 `_JSON_DISPATCHED_PATHS` 断言之前**，否则该断言无法引用它。
- 路由分支：`if path in _POOL_HANDLERS:`（`server.py:1230`「remaining … JSON branches」区新增，见 §5）。
- **禁止**在路由分支写死 `'up_pool'` 等 type 字面量——type 只从 `_POOL_HANDLERS` 取（防漂移）。

### 2.4 上游契约（**已实测定案，禁止再探测 / 改参数**）

```yaml
upstream:
  url: https://x-quote.cls.cn/quote/index/up_down_analysis
  method: GET
  headers:
    User-Agent: Mozilla/5.0
    Referer: https://www.cls.cn/finance
  params:
    app: CailianpressWeb
    os: web
    sv: 8.7.9
    type: up_pool | continuous_up_pool | up_open_pool | down_pool   # ← 由 _POOL_HANDLERS 决定
    way: last_px          # ★ 必须 last_px（way=change_px ⇒ 上游返回 code 9000，已踩坑）
    rever: 1
    sign: <cls_sign_params(params)>   # 覆盖「除 sign 外」的全部参数
  type_to_pool:                        # 括号内为实测返回条数（2026-10-10 定案）
    up_pool: 涨停池 (72)
    continuous_up_pool: 连板池 (12)
    up_open_pool: 炸板池 (13)
    down_pool: 跌停池 (10)
  response_envelope:
    code: 200          # 200 = 成功；非 200（如 9000）= 业务失败
    msg: ''
    data: [ ... ]      # ★ data 是裸 list（非 dict）
  item:                # data 中每条
    secu_code: <str>       # 股票代码
    secu_name: <str>       # 股票名
    change: <float>        # 涨跌幅
    last_px: <float>       # 最新价
    time: <str>            # 时间
    up_reason: <str>       # ★ 炸板池 / 跌停池 为空串 ''
    num_stocks: <int>      # 连板/涨停家数
    plate: <str>           # 所属板块
    is_st: <bool|int>      # 是否 ST
    limit_up_days: <int>   # 连板天数
```

> **签名不变式（踩坑）**：`way` 必须 `last_px`；改用 `change_px` 上游返回 `code=9000`（业务失败）。**该参数已实测定案，禁止改动**。`cls_sign_params` 内部按 key 排序，故 params 传入顺序不影响 `sign`（BR-POOL-11）。

### 2.5 注册点清单（**一个不漏**；`文件:行` 以当前工作区为准）

> **背景**：4 条路由必须同时登记到 5 张表 / 3 处计数，否则**导入期断言**或**测试**直接失败。下表为施工清单（含本 agent 核实新发现的 **R12/R13**，任务书未列，见 §10#2 的 `>>SCOPE:`）。

| # | 文件:行 | 现状 → 目标 | 不做的后果 |
|---|---------|-------------|-----------|
| **R1** | `config.py:219` 附近 | 新增 `_UP_DOWN_ANALYSIS_URL` + `_UP_DOWN_ANALYSIS_HEADERS`（仿 `_HOTPLATE_BASE_URL`/`_HOTPLATE_HEADERS`） | `server` import 期 `ImportError` |
| **R2** | `server.py:40-45` import 块 | `from .config import (...)` 并入 `_UP_DOWN_ANALYSIS_URL, _UP_DOWN_ANALYSIS_HEADERS` | `NameError`（import 期） |
| **R3** | `server.py:482` `_JSON_SHAPES` | **14 → 18** 条（+4 条 `'object'`） | 新路径落到 404（BR-SRV-2） |
| **R4** | `server.py:490` `assert len(_JSON_SHAPES) == 14` | **→ 18** | import 期 `AssertionError` |
| **R5** | `server.py:505` 附近 | 新增 `_POOL_HANDLERS`（+ `_POOL_TYPES`）表 | 分发分支无表可引用 |
| **R6** | `server.py:514` `_JSON_DISPATCHED_PATHS` | 并入 4 路径（`\| set(_POOL_HANDLERS)`，**与 R3 的 4 条一一对应**） | `server.py:518` 断言 import 期挂 |
| **R7** | `server.py:522` `_CACHE_AGE_DOMAINS` | 4 路径 → `'plate'`（与 hotplate 同族） | `max-age` 落到 `_DEFAULT_AGE_DOMAIN`（300s） |
| **R8** | `server.py:1230` 「remaining … JSON branches」区 | 新增 `if path in _POOL_HANDLERS:` 分支（走 `self._send_json_shape(path, lambda pt=…: handle_cls_pool(pt), write_body=write_body)`） | 新路径 404 |
| **R9** | `server.py:932` `feeds.extend` | +4 条（`name` 英文+中文、`path`、`url`、`status='configured'`） | `/healthz` 不可见（B-2 覆盖缺口扩大） |
| **R10** | `server.py:923` `_base_feed_entries` docstring | `15 healthz feed entries` → **`19`** | 文档漂移（非阻断） |
| **R11** | `tests/test_server_http.py:47` | `assertEqual(len(srv._JSON_SHAPES), 14)` → **18** | 测试红 |
| **R12** | `tests/test_server_http.py:510` | `assertEqual(len(payload['feeds']), 15)` → **19** | **测试红（任务书漏列）** |
| **R13** | `tests/test_server_http.py:521` | `assertEqual(len(entries), 15)` → **19** | **测试红（任务书漏列）** |

> **非阻断漂移（建议同步，不改不红）**：`server.py:478` 注释「14 JSON branches」→ 18；`server.py:923` docstring（R10）。

---

## 3. 数据结构（yaml）

### 3.1 成功响应体

```yaml
pool_success:
  stocks:                       # 恒为 list（上游 data 裸 list；非 list ⇒ fail-loud error，BR-POOL-6 / P1-02）
    - secu_code: <str>
      secu_name: <str>
      change: <float>
      last_px: <float>
      time: <str>
      up_reason: <str>          # 炸板池 / 跌停池 为 ''
      num_stocks: <int>
      plate: <str>
      is_st: <bool|int>
      limit_up_days: <int>
```

> 字段集合 = 上游 `data[i]` **原样透传**（本层不裁剪、不重命名、不补默认值）——`{'stocks': data}` 即 `raw.get('data')`。

### 3.2 降级响应体

```yaml
pool_degraded:
  error: <str>                  # 上游 msg / FetchError 文本 / 'unknown pool type: ...' / 'malformed upstream response' / 'upstream data shape unexpected: <type>'
```

> 形态与 `_guard` 对 `object` shape 的降级体一致（`server.md` §2.3：`{'error': str(exc)}`）。**无 `stocks` 键**（失败体与成功体键集合互斥）。

### 3.3 `plate` 域缓存策略（唯一权威 = `cache_policy`，本增量只读）

```yaml
cache_policy('plate'):
  tier: L2
  ttl: 12                    # 盘中（L2 基 12s × factor 1.0）；非盘 = 120
  pool_refresh: 12           # 本增量不使用（无去重池）
  pool_max: 200              # 本增量不使用（无去重池）
  cache_max: null            # URL-cache-only 域（共享 URL 缓存，全局 MAX_CACHE_SIZE 约束）
```

> 4 池与 `/cls/hotplate`、`/cls/plate` **共用 `plate` 域**：`fetch_json` 的 TTL 与 `_cache_age` 的 `max-age` **同源**（BR-POOL-3 / BR-SRV-8）。本增量**不消费** `pool_refresh`/`pool_max`/`cache_max`（无终端缓存、无池）。

### 3.4 本增量新增的内部符号

```yaml
_POOL_HANDLERS: {4 路径 -> type}   # 分发表（§2.3）
_POOL_TYPES: frozenset              # 值域（_POOL_HANDLERS.values()）
handle_cls_pool: function           # 单函数 handler（§2.2）
config._UP_DOWN_ANALYSIS_URL: str
config._UP_DOWN_ANALYSIS_HEADERS: dict
```

---

## 4. 业务规则

| 编号 | 规则 | 依据 |
|------|------|------|
| **BR-POOL-1** | **type ↔ 路径映射唯一权威 = `_POOL_HANDLERS`**（4 项）；路径镜像上游 `type` 命名（`/cls/<type>`）。路由分支只从表取 type，**禁止**写死 type 字面量 | §2.3 / 仿 `_PANEL_HANDLERS` |
| **BR-POOL-2** | **`way` 恒为 `'last_px'`**（硬编码，随 params 一起签名）；`change_px` 会触发上游 `code=9000`（已实测踩坑）——**禁止改动** | §2.4 上游契约 |
| **BR-POOL-3** | TTL **只**来自 `cache_policy('plate')['ttl']`（盘中 12 / 非盘 120）；**禁止**裸 TTL 字面量（如 `12`/`120`） | BR-CFG-12 / §3.3 |
| **BR-POOL-4** | 取数**只**经 `cache.fetch_json(url, _UP_DOWN_ANALYSIS_HEADERS, ttl=…)`；**禁止** `urlopen` 直连；URL = `f'{_UP_DOWN_ANALYSIS_URL}?{urlencode(params)}'` | R15 同源约定 |
| **BR-POOL-5** | `sign` = `cls_sign_params(params)`（覆盖除 `sign` 外全部参数）；params 集恒为 `{app,os,sv,type,way,rever}` + `sign`；**签名算法 / 参数名不得改动** | §2.4 / `utils.cls_sign_params` |
| **BR-POOL-6** | 成功 → `{'stocks': data}`（`data = raw.get('data')`）；**`data` 非 list ⇒ fail-loud**：`{'error': 'upstream data shape unexpected: <type>'}`（`<type>` = `type(data).__name__`）+ `logging.warning`（**禁止**静默 `{'stocks': []}`）；空 list 属合法成功（`{'stocks': []}`），**不是** error | §3.1 / 值域 / **P3b 评审条件 P1-02** |
| **BR-POOL-7** | 上游 `code != 200` → `{'error': raw.get('msg') or 'upstream_error'}`（业务失败，如 9000） | §2.4 信封 |
| **BR-POOL-8** | `handle_cls_pool` 为**总函数**：`fetch_json`/`json.loads` 的任意 `Exception` 就地捕获 → `{'error': str(exc)}`，**绝不抛**；`_send_json_shape` 的 `_guard` 为**兜底**（若 handler 意外抛出仍降级为 `{'error': …}`） | `handle_*` 约定 / `server.md` §2.3 / N1 |
| **BR-POOL-9** | **枚举闸**：`pool_type ∉ _POOL_TYPES` ⇒ `{'error': 'unknown pool type: …'}`，**在拼 URL 之前、不触网**（防任意值注入上游请求 / 铸造缓存键） | 仿 `market_api.VALID_MARKETS` |
| **BR-POOL-10** | **注册点齐全**（R1–R13）：`_JSON_SHAPES` 14→18 **且** `assert len(_JSON_SHAPES) == 18`；`_JSON_DISPATCHED_PATHS` 并入 4 路径（否则 `server.py:518` 断言 import 期挂） | §2.5 / `server.md` §2.2 |
| **BR-POOL-11** | 缓存域 = `plate`：`_CACHE_AGE_DOMAINS` 4 路径 → `'plate'`（与 hotplate 同族）；`max-age` 与 `fetch_json` TTL 同源 | BR-SRV-8 / §3.3 |
| **BR-POOL-12** | `feeds[]` 索引 **+4** 条（`name` 英文+中文、`status='configured'`）；`_base_feed_entries` 计数 15 → 19 | §2.5 R9/R10 |
| **BR-POOL-13** | **零新增第三方依赖**；常量集中在 `config.py`（不在 `server.py` 硬编码 URL/Header）；handler 参数平铺、不封装请求对象 | 项目约定 |

---

## 5. 伪代码

> 约束标记沿用项目惯例：本增量为**纯同步只读取数**，无事务 / 无锁 / 无重试 / 无补偿（失败由 `cache` 负缓存承担）。

```python
# ══ config.py（R1，仿 :219-225）════════════════════════════════════════════
_UP_DOWN_ANALYSIS_URL = 'https://x-quote.cls.cn/quote/index/up_down_analysis'
_UP_DOWN_ANALYSIS_HEADERS = {
    'User-Agent': 'Mozilla/5.0',
    'Referer': 'https://www.cls.cn/finance',
}

# ══ server.py import 块（R2）═══════════════════════════════════════════════
from .config import (
    ..., _HOTPLATE_BASE_URL, _HOTPLATE_HEADERS,
    _UP_DOWN_ANALYSIS_URL, _UP_DOWN_ANALYSIS_HEADERS,          # ★ R2
)

# ══ server.py handler（新函数，紧邻 handle_cls_hotplate / handle_cls_plate）══
def handle_cls_pool(pool_type):
    """CLS pool data (财联社 4 池) — direct REST, plate-domain TTL.

    pool_type ∈ _POOL_TYPES（= _POOL_HANDLERS 值域，单一权威）。
    成功 → {'stocks': [...]}；data 非 list → {'error': 'upstream data shape unexpected: <type>'}
    （fail-loud + logging.warning，BR-POOL-6 / P1-02）；失败/非法 → {'error': ...}，绝不抛（BR-POOL-8）。
    """
    # ① 枚举闸（BR-POOL-9）：非法 type ⇒ 不触网、不铸缓存键
    if pool_type not in _POOL_TYPES:
        return {'error': f'unknown pool type: {pool_type!r}'}

    # ② 签名 URL（BR-POOL-2/5）：way 恒 'last_px'
    params = {
        'app': 'CailianpressWeb', 'os': 'web', 'sv': '8.7.9',
        'type': pool_type, 'way': 'last_px', 'rever': 1,
    }
    params['sign'] = cls_sign_params(params)
    url = f'{_UP_DOWN_ANALYSIS_URL}?{urlencode(params)}'

    # ③ 唯一取数入口 + plate 域 TTL（BR-POOL-3/4）
    try:
        raw = json.loads(fetch_json(
            url, _UP_DOWN_ANALYSIS_HEADERS,
            ttl=cache_policy('plate')['ttl']))
    except Exception as exc:                    # FetchError / JSON 解码失败 / …
        _warn_pool_fetch_failed(pool_type, exc) # B-02：限频告警（P2-5，原 log.warning 直写）
        return {'error': str(exc)}              # BR-POOL-8：就地降级（不抛）

    # ④ 信封判定 + fail-loud shape check（BR-POOL-6/7 / P1-02）
    if not isinstance(raw, dict):
        return {'error': 'malformed upstream response'}
    if raw.get('code') != 200:
        return {'error': str(raw.get('msg') or 'upstream_error')}   # B-03：外层 str()
    data = raw.get('data')
    if not isinstance(data, list):
        shape = type(data).__name__
        # P2-1: 形状失败每请求重跑（plate TTL 只限回源、不限日志）⇒ 走同一限频器；
        # 消息含 shape 名 ⇒ 换形状即换消息 ⇒ 即时再告警；同形状 30s 窗口静默。
        _warn_pool_fetch_failed(
            pool_type, f'unexpected upstream data shape {shape}')
        return {'error': f'upstream data shape unexpected: {shape}'}
    # B-02 成功路径：结束该池失败 episode（P8-r1 P2）——一次成功使后续同 kind
    # 同消息失败成为新 episode、必再告警（NEG_TTL=5s ≪ GAP=30s，flapping 场景）。
    # P2-3（P5a-r3-r4，有意取舍）：episode 仅由全成功 return 结束——code != 200
    # 与形状失败（transport 成功但信封/形状未达标）return 前不 pop，故不结束
    # episode、也不重新武装被抑制的告警；限频上界口径为 per-episode，非无条件的
    # per-GAP 天花板。
    _pool_fetch_warned_at.pop(pool_type, None)
    return {'stocks': data}   # data 裸 list（空 list 属合法成功）
```

```python
# ══ server.py 注册表（R3–R7）═══════════════════════════════════════════════
_JSON_SHAPES = {
    ...                                                        # 既有 14 条
    '/cls/up_pool': 'object', '/cls/continuous_up_pool': 'object',
    '/cls/up_open_pool': 'object', '/cls/down_pool': 'object', # ★ R3
}
assert len(_JSON_SHAPES) == 18                                 # ★ R4（14 → 18）

# 紧邻 _PANEL_HANDLERS（R5）：路径 → 上游 type
_POOL_HANDLERS = {
    '/cls/up_pool': 'up_pool',
    '/cls/continuous_up_pool': 'continuous_up_pool',
    '/cls/up_open_pool': 'up_open_pool',
    '/cls/down_pool': 'down_pool',
}
_POOL_TYPES = frozenset(_POOL_HANDLERS.values())

_JSON_DISPATCHED_PATHS = (frozenset(_PANEL_HANDLERS)
                          | set(_STOCK_BATCH_HANDLERS)
                          | {'/cls/hotplate', '/cls/plate',
                             '/ths/longhu', '/market/margin'}
                          | set(_POOL_HANDLERS))               # ★ R6
assert _JSON_DISPATCHED_PATHS == frozenset(_JSON_SHAPES)      # :518 守卫

_CACHE_AGE_DOMAINS = {
    ...,
    '/cls/hotplate': 'plate', '/cls/plate': 'plate',
    '/cls/up_pool': 'plate', '/cls/continuous_up_pool': 'plate',
    '/cls/up_open_pool': 'plate', '/cls/down_pool': 'plate',   # ★ R7
    ...,
}

# ══ server.py feeds 索引（R9/R10）══════════════════════════════════════════
# _base_feed_entries docstring：'15 healthz feed entries' → '19'
feeds.extend([
    ...,
    {'name': 'CLS Up Pool (财联社涨停池)', 'path': '/cls/up_pool',
     'url': base_url + '/cls/up_pool', 'status': 'configured'},
    {'name': 'CLS Continuous Up Pool (财联社连板池)', 'path': '/cls/continuous_up_pool',
     'url': base_url + '/cls/continuous_up_pool', 'status': 'configured'},
    {'name': 'CLS Up Open Pool (财联社炸板池)', 'path': '/cls/up_open_pool',
     'url': base_url + '/cls/up_open_pool', 'status': 'configured'},
    {'name': 'CLS Down Pool (财联社跌停池)', 'path': '/cls/down_pool',
     'url': base_url + '/cls/down_pool', 'status': 'configured'},
])
```

```python
# ══ server.py 分发分支（R8，_handle_request「remaining … JSON branches」区）══
        # ── 4 CLS pools (object) — table-driven ─────────────────────────
        if path in _POOL_HANDLERS:                              # ★ R8
            pool_type = _POOL_HANDLERS[path]
            self._send_json_shape(
                path, lambda pt=pool_type: handle_cls_pool(pt),
                write_body=write_body)          # 默认参数绑定，无闭包晚绑定
            return
        # （其后为既有 /cls/hotplate、/cls/plate、/ths/longhu、/market/margin 分支）
```

> **闭包安全**：`lambda pt=pool_type:` 用**默认参数**绑定当前 type（非循环变量，无晚绑定风险）；`_send_json_shape` 从 `_JSON_SHAPES[path]` 读 shape（`'object'`），路由**不发明** shape 字面量。

---

## 6. 错误处理

| 情形 | 产生层 | 行为 | 对外形态（恒 200） |
|------|--------|------|-------------------|
| `pool_type` 非法（∉ `_POOL_TYPES`） | `handle_cls_pool`（BR-POOL-9） | 直接返回、**不触网** | `{"error": "unknown pool type: ..."}` |
| 上游超时（socket/URL） | `cache.fetch_json` | cache 落负缓存并 `raise FetchError('upstream_timeout')` → handler 捕获 | `{"error": "..."}` |
| 上游其它异常（DNS/RST/5xx） | `cache.fetch_json` | 同上（`upstream_error`） | `{"error": "..."}` |
| 负缓存命中（<1ms） | `cache.fetch_json` 段 2 | 立即 raise（沿用首次 kind） | `{"error": "..."}` |
| JSON 解码失败 | `handle_cls_pool` | 就地捕获 → `{"error": str(exc)}` | `{"error": "..."}` |
| 上游信封非 dict | `handle_cls_pool`（BR-POOL-7） | 返回 `{"error": "malformed upstream response"}` | `{"error": "..."}` |
| 上游 `code != 200`（如 9000，`way` 错） | `handle_cls_pool`（BR-POOL-7） | 返回 `{"error": msg}` | `{"error": "<msg>"}` |
| 上游 200 但 `data` 非 list / 缺 `data` | `handle_cls_pool`（BR-POOL-6 / **P1-02**） | **fail-loud**：`logging.warning` + 返回 `{"error": "upstream data shape unexpected: <type>"}`（**禁止**静默 `{"stocks": []}`） | `{"error": "upstream data shape unexpected: <type>"}` |
| 上游 200 且 `data` 空 list | `handle_cls_pool` | 返回 `{"stocks": []}` | `{"stocks": []}` |
| handler 意外抛异常（未预期） | `_guard`（`_send_json_shape` 内，BR-POOL-8 兜底） | `log.exception` + 降级 | `{"error": str(exc)}` |

**降级路径**：本增量降级**只降级响应体形态**，不降级为异常外抛（`handle_*` 约定）。上游故障期的请求放大由 `cache` 负缓存（`NEG_TTL=5s`）抑制，本增量无需重试逻辑。**真实 503 不涉及**（业务端点恒 200，N1）。

---

## 7. 并发安全

| 项 | 结论 |
|----|------|
| 本增量持有的锁 | **无**——`handle_cls_pool` 是纯函数式（局部变量 + 既有全局只读表）；**唯一模块级可变状态** = B-02 日志限频表 `_pool_fetch_warned_at`（`pool_type -> (last_ts, last_msg)`，键 ∈ 枚举闸 `_POOL_TYPES` 值域 ⇒ **有界 ≤4 键**，lock-free / 容忍竞态）——用途：负缓存（`NEG_TTL=5s`）窗口内同一失败对每个请求重复发生，逐次告警会使日志量随 RPS 线性放大，故同 `pool_type` 同消息 30s 窗口内只告警一次（`_POOL_FETCH_WARN_GAP=30.0`）、消息变化即时再告警；**纯日志限频，不改变任何缓存 / 业务语义**。★ **P8-r1 P2（墙钟→单调钟）**：`last_ts` 存 **`time.monotonic()` 读数**（非墙钟 `time.time()`）——窗口是两次读数之间的**间隔**，NTP 步（回拨 ⇒ `now - prev[0]` 变负、窗口永久拉伸；前拨 ⇒ 提前再告警）不得影响纯间隔测量（`server.py:477-493`）。★ **P8-r1 P2（episode 语义）**：`handle_cls_pool` **成功路径** pop 该池条目（`server.py:549`）⇒ 一次成功结束该池失败 episode，其后同 kind 同消息失败是**新 episode**、必再告警（NEG_TTL=5s ≪ GAP=30s，flapping 场景：失败→恢复→失败须再次告警）。★ **P2-1（P5a-r3-r4，第二写入方）**：形状失败路径（`data` 非 list）亦走 `_warn_pool_fetch_failed`（`server.py:541-542`），消息格式 `cls pool %s fetch failed: unexpected upstream data shape <type>`——消息含 shape 名 ⇒ 换形状即换消息 ⇒ 即时再告警；同形状 30s 窗口静默。★ **P2-3（P5a-r3-r4，episode 收窄）**：episode 仅由全成功 return 结束——`code != 200` 与形状失败 return 前不 pop，故不结束 episode、也不重新武装被抑制的告警；限频上界口径为 per-episode，非无条件的 per-GAP 天花板 |
| `_POOL_HANDLERS` / `_POOL_TYPES` / `_JSON_SHAPES` / `_CACHE_AGE_DOMAINS` | 导入期构建、**运行期只读**（不修改）；多线程只读安全 |
| `cache_policy('plate')` | 纯函数、无锁、纳秒级；每次调用返回 fresh dict（`config.md` §7） |
| `fetch_json` | 内部自有 `_cache_lock`/`_neg_lock`，网络 IO 不持锁；本增量不持任何锁调用它 |
| 并发读者 | 4 端点可被主池多 worker 并发调用；彼此**无业务共享可变状态** ⇒ 无业务竞态；唯一共享可变状态 = 限频表 `_pool_fetch_warned_at`（lock-free / 容忍竞态：最坏结果仅为窗口内多告警或少告警一次，均不触及业务语义） |

> **无锁设计**是刻意的：本增量不引入终端缓存 / 池 / 账本，故不需要 `_margin_cache_lock` 那类原语；所有并发安全责任由 `cache.fetch_json` 的既有四段式协议承担。

---

## 8. 测试要点（映射 AC；**引用现有 hotplate 测试模式**）

> 落地位置建议：`tests/test_server_http.py`（新增 `ClsPoolTests` / 扩 `ShapeTableTests`·`CacheAgeTests`·`HealthPayloadTests`）与 `tests/test_server.py`（handler 单测，参照 `test_handle_cls_hotplate_*`）。打桩一律 `patch.object(srv, 'fetch_json', ...)`（全限定名，参照 `PlateStaggerTests._capture_ttls` :103）。

| 用例 | 步骤 / 断言（精确） | 覆盖 |
|------|-------------------|------|
| **POOL-T1** shape 表计数 | `len(srv._JSON_SHAPES) == 18`；`{p for p,s in _JSON_SHAPES.items() if s=='batch'} == set(_STOCK_BATCH_HANDLERS)`（**既有断言改写 14→18**，参照 `ShapeTableTests` :45） | BR-POOL-10 |
| **POOL-T2** dispatched 一致 | `srv._JSON_DISPATCHED_PATHS == frozenset(srv._JSON_SHAPES)`；4 pool 路径 ∈ 两者（参照 `test_every_shape_path_has_a_routed_branch` :55） | BR-POOL-10 |
| **POOL-T3** 成功取数 + URL 契约 | patch `fetch_json`（捕获 `url/headers/ttl`）返回 `json.dumps({'code':200,'msg':'','data':[{'secu_code':'sh600519'}]})` ⇒ `handle_cls_pool('up_pool') == {'stocks':[{'secu_code':'sh600519'}]}`；`url` 含 `type=up_pool` ∧ `way=last_px` ∧ `rever=1` ∧ `app=CailianpressWeb` ∧ `sign=` 非空；`headers == config._UP_DOWN_ANALYSIS_HEADERS` | BR-POOL-4/5/6 |
| **POOL-T4** TTL 同源 | 捕获 `ttl == cache_policy('plate')['ttl']`（盘中 12 / 非盘 120）；`server.py` 本增量**无** `ttl=12`/`ttl=120` 裸字面量 | BR-POOL-3 |
| **POOL-T5** `way` 恒 last_px | `url` 含 `way=last_px` 且**不含** `change_px`；`cls_sign_params` 对同 params 两次调用结果相同（签名稳定） | BR-POOL-2/5 |
| **POOL-T6** 上游业务失败 | patch 返回 `{'code':9000,'msg':'param error'}` ⇒ `handle_cls_pool('up_pool') == {'error':'param error'}` | BR-POOL-7 |
| **POOL-T7** 取数异常不抛 | patch `fetch_json` 抛 `FetchError('upstream_timeout')` ⇒ `handle_cls_pool('up_pool')` 返回 `{'error': ...}`、**不抛** | BR-POOL-8 |
| **POOL-T8** 空 list vs 非 list（fail-loud） | 返回 `data: []` ⇒ `{'stocks': []}`（合法成功）；`data: {}` / `data: "str"` / 缺 `data` ⇒ `{'error': 'upstream data shape unexpected: <type>'}` + `logging.warning` 命中（**无 `stocks` 键**） | BR-POOL-6 / **P1-02** |
| **POOL-T9** 枚举闸 | `handle_cls_pool('bogus')` / `handle_cls_pool('')` / `handle_cls_pool(None)` ⇒ 各 `{'error': ...}` 且 `fetch_json` **未被调用** | BR-POOL-9 |
| **POOL-T10** 4 路径 HTTP 分发 | `self._req('GET', p)`（patch `fetch_json` 返回信封），`p` 遍历 4 路径 ⇒ 各 `200` + body `{'stocks':...}`（参照 `test_hotplate_all_partitions_failing_is_200_with_error_body` :646） | BR-POOL-1/10 |
| **POOL-T11** 4 路径降级恒 200 | patch `fetch_json` 抛 ⇒ 4 路径各 `200` + body 含 `error`；`http_503_total` **不变**（N1） | BR-POOL-8 |
| **POOL-T12** cache-age 域 | 4 路径 `_CACHE_AGE_DOMAINS[p] == 'plate'`；`RSSHandler.__new__` 设 `h.path=p` ⇒ `h._cache_age() == cache_policy('plate')['ttl']`（参照 `CacheAgeTests` :392） | BR-POOL-11 |
| **POOL-T13** feeds 索引 | `len(_base_feed_entries('http://x')) == 19`；4 pool 路径 `status == 'configured'` 且 `path` 在索引中（参照 `test_feed_status_corrections` :518） | BR-POOL-12 |
| **POOL-T14** 分发表值域 | `set(_POOL_HANDLERS) == {'/cls/up_pool','/cls/continuous_up_pool','/cls/up_open_pool','/cls/down_pool'}`；`set(_POOL_HANDLERS.values()) == _POOL_TYPES == {'up_pool','continuous_up_pool','up_open_pool','down_pool'}` | BR-POOL-1/9 |
| **POOL-T15**（**B-02**）失败告警限频 | `test_fetch_failure_warning_is_rate_limited`（`tests/test_server_http.py`）：patch `fetch_json` 抛同一异常 ⇒ 首次告警、30s 窗口内同 pool_type 同错误**静默**（日志计数不变）、错误消息变化**即时再告警**、窗口后**续报**；自带 `_pool_fetch_warned_at` save/clear/restore 隔离（hermetic）。锁定"负缓存下日志限频"行为（同 pool_type 同错误 30s 窗口一条） | B-02 |
| **POOL-T16**（**B-02**）单调钟窗口 | `test_rate_limit_window_uses_monotonic_clock`（`tests/test_server_http.py:430`）：patch `srv.time.monotonic` 注入 1000/1010/1040，warn→silent→warn，断言表内时间戳 == 1040.0。可证伪：实现仍读 `time.time()` ⇒ 注入钟不到达 ⇒ 第三次调用仍在墙钟窗口内 ⇒ `assertLogs` 空 ⇒ 红 | B-02 / P8-r1 P2 |
| **POOL-T17**（**B-02**）成功结束 episode | `test_success_clears_the_warn_episode`（`tests/test_server_http.py:469`）：fail(warn)→同 fail(silent)→成功→`'up_pool' not in` 表→再 fail(warn)。可证伪：删成功路径 pop ⇒ 旧 `(ts,msg)` 留存 ⇒ 末次 `assertLogs` 空 ⇒ 红 | B-02 / P8-r1 P2 |
| **POOL-T18**（**P2-1**）形状漂移告警限频 | `test_shape_drift_warning_is_rate_limited`（`tests/test_server_http.py:548`）：patch `fetch_json` 返回 `data: {}`（dict 形状）⇒ 首次告警含 `'shape'` 与 `'dict'`；同形状窗口内 `assertNoLogs` 静默；换 `data: None`（NoneType 形状）⇒ 消息变了 ⇒ 立即再告警；同形状两次 error 返回体逐字一致、换形状时 shape 名照常出现在 error 里。可证伪：形状分支改回直写 `log.warning` ⇒ repeat 段 `assertNoLogs` 红。自带 `_pool_fetch_warned_at` save/clear/finally 隔离（hermetic） | P2-1 / B-02 |

---

## 9. AC 追溯矩阵

> **本增量无专属 PRD AC**（需求来自任务书原文，非 `doc/prd/perf-stability-optimization.md`）——登记见 §10#1。下表映射到**项目既有约束 / AC**。

| 本增量设计点 | 覆盖 |
|-------------|------|
| `handle_cls_pool` 总函数 + `_guard` 兜底（BR-POOL-8） | **AC-S1**（异常兜底，不裸崩、不抛） |
| TTL 只来自 `cache_policy('plate')['ttl']`（BR-POOL-3） | **AC-A3**（TTL 单一权威）/ **AC-E6**（TTL 分层不漂移） |
| `_CACHE_AGE_DOMAINS` 4 路径 → `plate`（BR-POOL-11） | **BR-SRV-8**（max-age 经 policy 域）/ `SRV-T11` 同源口径 |
| `_JSON_SHAPES` 计数 + `_JSON_DISPATCHED_PATHS` 断言（BR-POOL-10） | **P1-6 结构护栏**（anti-regression，导入期失败而非静默 404） |
| 枚举闸 `_POOL_TYPES`（BR-POOL-9） | 安全（禁止任意值注入上游 / 铸造缓存键）；仿 `market_api.VALID_MARKETS` |
| `feeds[]` +4（BR-POOL-12） | **BR-SRV-22**（healthz 端点可见性） |
| 只增 4 端点、不改既有契约 | **端锁定 🟠 STABLE** |

---

## 10. 与 SAD / 现有代码的偏差与歧义标注（不擅自改方案）

| # | 项 | 表述 | 本文裁决 / 偏差 | 理由 |
|---|----|------|----------------|------|
| 1 | **无专属 PRD AC** | 需求来自任务书原文，`doc/prd/perf-stability-optimization.md` 无对应 AC | 本详设**按任务书原文承接**，AC 追溯见 §9（映射既有约束）；**建议编排层 / system-architect 决定是否回填 SAD/PRD**（本 agent 不改 `doc/arch/` / `doc/prd/`） | 属新功能增量，非既有性能专项 AC 范围 |
| 2 | **注册点清单漏列（`>>SCOPE:`）** | 任务书「必须逐一列全的注册点」给 7 项，**未列** `tests/test_server_http.py:510`（`len(payload['feeds']) == 15`）与 `:521`（`len(entries) == 15`） | **本详设补列 R12/R13**（`15 → 19`）；**否则照任务书 7 项施工，feeds 计数断言必红** | 4 条 `feeds[]` 新增使总数 15 → 19；两处硬断言须同批改 |
| 3 | **独立文档 vs 并入 `server.md`** | 任务书允许「并入现有 server.md/market_api.md 亦可」 | **裁决：独立 `cls_pools.md`**——4 端点 + 13 注册点 + 14 用例构成自洽增量，独立文档便于评审与 code-developer 单点消费；`server.md`（2000+ 行）已含大量历史批次，并入会稀释可读性。**未改 `server.md` 正文**（仅其路由表需按 R3–R9 施工，由 code-developer 执行） | 粒度判断：4 功能端点 + 完整契约 + 测试 ⇒ 独立成文 |
| 4 | **对外文档同步（out of scope）** | `API.md` / `README.md` 的端点清单需补 4 条（对外可见面） | 本 agent **只写 `doc/detailed/`**，**不碰 `API.md`/`README.md`** ⇒ 输出 `>>DOC_SYNC: API.md, README.md → 新增 4 个 /cls/* 池端点` 供编排层承接 | 契约文档修改权在编排层 |
| 5 | **非阻断漂移** | `server.py:478` 注释「14 JSON branches」、`server.py:923` docstring「15」 | 建议同批改为 18 / 19（**不改不红**，仅文档一致性） | 与 R4/R10 同源 |

### Step 2.5 链式推导（7 规则）

| 规则 | 结论 |
|------|------|
| 规则零（需求缺口） | 需求 = 「4 tab → 4 独立接口」，**4 端点已完整覆盖**（type↔池一一对应）⇒ **无补充接口** |
| 规则一（读写配对） | 全为 `GET`（读）；**无 PUT/DELETE/PATCH**，无写配对需求 |
| 规则二（状态机） | **无状态实体**；仅「成功 `{'stocks':…}` / 降级 `{'error':…}`」二值（穷举封闭：`code==200` ∧ data list ⇒ 成功；`code==200` ∧ data 非 list ⇒ fail-loud error，**P1-02**；其余 ⇒ 降级） |
| 规则三（跨模块依赖） | `server → config`（`_UP_DOWN_ANALYSIS_URL`/`_UP_DOWN_ANALYSIS_HEADERS` + `cache_policy('plate')`）；`server → utils`（`cls_sign_params`）；`server → cache`（`fetch_json`）——**均既有方向、无环**；**无反向边** |
| 规则四（数据生命周期） | **无持久化**；上游响应经共享 URL 缓存（`plate` 域 TTL，LRU/清扫由 cache 层负责）；本增量不写库、不建表 |
| 规则五（异步流程） | **无异步 / 无任务状态 / 无死信**（纯同步取数） |
| 规则六（权限 / 数据隔离） | **无鉴权 / 无多租户**（只读公开数据）；不改 `layerIsolation`（`config`/`cache`/`utils` 均在既有 allowlist） |

---

## 11. 交付自检

- [x] §3 为 `yaml` 代码块（成功体 / 降级体 / plate 策略 / 内部符号）
- [x] 业务规则有编号（BR-POOL-1..13），精确到字段 / 取值，配置来源已标注
- [x] 接口有完整 OpenAPI 定义（4 端点请求 / 响应 schema + 错误语义 + 状态码表）
- [x] 上游契约（URL / Headers / params / `way=last_px` / type↔池 / 信封 / 条目字段）照任务书**逐字保留**
- [x] 注册点 **R1–R13 一个不漏**（含本 agent 核实新发现的 R12/R13，`>>SCOPE:` 见 §10#2）
- [x] 核心伪代码含 `handle_cls_pool` + 4 张注册表 + 分发分支（闭包安全）
- [x] 测试用例引用现有 hotplate 模式（`PlateStaggerTests._capture_ttls` / `CacheAgeTests` / `ShapeTableTests` / HTTP 分发用例）
- [x] 无 `{例:` / 无 `{...}` 占位符残留；无 `>>SCOPE` 以外的方案改动
- [x] **未改任何代码 / 测试 / `API.md` / `README.md`**（仅新增本详设 + `_PROGRESS.md` 登记）

---

## 12. 变更记录

| 版本 | 日期 | 变更类型 | 变更内容 | 变更人 |
|------|------|---------|---------|--------|
| v1.0.0 | 2026-10-10 | 🆕 新建 | 财联社 4 池独立接口详设：4 端点（`/cls/up_pool`·`/cls/continuous_up_pool`·`/cls/up_open_pool`·`/cls/down_pool`）+ `handle_cls_pool` + `_POOL_HANDLERS` 表驱动 + 13 注册点 + 14 用例 | task-decomposer |
| v1.0.1 | 2026-10-10 | 🔧 语义回写 | **P1-02 fail-loud 回写**（一致遵 **P3b 评审条件 P1-02**）：BR-POOL-6 / §2.1 HTTP 状态语义表 / §2.2 / §3.1 / §3.2 / §5 伪代码 / §6 错误处理表 / POOL-T8 / Step 2.5 规则二统一改为「上游 `data` 非 list ⇒ `{'error': 'upstream data shape unexpected: <type>'}`（200 + N1 error body）+ `logging.warning`；**禁止**静默 `{'stocks': []}`」；空 list 仍按成功 `{'stocks': []}` 不变（P5b 已确认实现服从评审条件，叠加于详设之上，本次把详设本体回写以防后续按旧口径「修回」实现） | 编排层（P7b 契约同步） |
| v1.0.2 | 2026-10-10 | 🔧 契约同步（P7b-r2 Bug-fix Loop） | **§7.1 并发安全**登记 P2-5 新增的模块级限频状态 `_pool_fetch_warned_at`（`server.py` 内，`pool_type -> (时间戳, 消息)`，键 ∈ `_POOL_TYPES` ⇒ ≤4 键、lock-free / 容忍竞态；用途：负缓存窗口内日志不随 RPS 放大；不改变任何缓存 / 业务语义）；同时收口头部版本漂移（v1.0.1「P1-02 语义回写」行已存在但头部未同步，本次一并 bump 至 v1.0.2）。**只改文档**；未改代码 / 测试 / `API.md` / `README.md` / `SAD` | 编排层（P7b 契约同步） |
| v1.0.3 | 2026-10-10 | 🔧 契约同步（P7b-r3 对抗性复查） | 对抗性复查（P8-r1）指出的测试登记漂移补齐：**§8** 新增 **POOL-T15**（`test_fetch_failure_warning_is_rate_limited`，B-02 失败告警限频：同 pool_type 同错误 30s 窗口一条、错误变化即时告警、窗口内静默、窗口后续报，自带 `_pool_fetch_warned_at` save/clear/restore 隔离；锁定"负缓存下日志限频"行为）。**只改文档**；未改代码 / 测试 / `API.md` / `README.md` / `SAD` | 编排层（P7b 契约同步） |
| v1.0.4 | 2026-10-10 | 🔧 契约同步（P7b-r4 契约同步） | P5a-r3 修复 3 条小问题后的文档回填：**§5** 伪代码 except 分支补 `_warn_pool_fetch_failed(pool_type, exc)` 调用（P7b-r2 遗留）+ 成功 return 前补 `_pool_fetch_warned_at.pop(pool_type, None)`（episode 语义）；**§5** B-03 补外层 `str()`；**§7.1** 限频表登记补「时间戳为 `time.monotonic()` 读数（非墙钟）」+「成功路径 pop ⇒ episode 结束语义」+ 行号刷新（`server.py:466-483` / `:533`）；**§8** POOL-T15 描述收口（补"日志计数不变"）+ 新增 **POOL-T16**（单调钟窗口，对应 MS-T18）/ **POOL-T17**（成功结束 episode，对应 MS-T19）。**只改文档**；未改代码 / 测试 / `API.md` / `README.md` / `SAD` | 编排层（P7b 契约同步） |
| v1.0.5 | 2026-10-13 | 🔧 契约同步（P7b-r5 契约同步） | P5a-r4 代码评审 drift 清单（D1–D5）同步：**§5** 伪代码形状分支由直写 `log.warning` 改为 `_warn_pool_fetch_failed(pool_type, f'unexpected upstream data shape {shape}')`（P2-1，消息含 shape 名 ⇒ 换形状即时再告警；同形状 30s 窗口静默）；**§5** episode 注释补 P2-3（episode 仅由全成功 return 结束，`code != 200` 与形状失败不 pop）；**§7.1** 行号刷新（`server.py:477-493` / `:549`）+ 补 P2-1 第二写入方与 P2-3 episode 收窄；**§8** POOL-T16/T17 行号刷新（`:429`→`:430` / `:468`→`:469`）+ 新增 **POOL-T18**（`test_shape_drift_warning_is_rate_limited`，P2-1 形状漂移告警限频）；**§2.5** 下游提示行号刷新（`server.py:496-550`）。**只改文档**；未改代码 / 测试 / `API.md` / `README.md` / `SAD` | 编排层（P7b 契约同步） |

> **下游提示（code-developer）**：严格按 §2.5 注册点 R1–R13 施工；`way` 必须 `last_px`；TTL 取 `cache_policy('plate')['ttl']`；**先读 `server.py:337 handle_cls_hotplate` 与 `server.py:496-550` 再动手**，命名 / 分层 / 异常风格与之一致。**P1-02 fail-loud**：上游 `data` 非 list ⇒ `{'error': 'upstream data shape unexpected: <type>'}` + `_warn_pool_fetch_failed`（限频告警，禁止静默空池）。
