# market_sentiment 独立接口详细设计

> **版本** v1.0.4 · **状态** 🟢 评审闭环（P3b 评审 `REV-DES-20261010-002` P1-01 + P2×5 已修复）· **日期** 2026-10-10 · **作者/产出** task-decomposer
> 模块路径 `china_finance_rss/server.py`（**增量**：新增 1 个 CDP handler + 1 条路由登记 + `/finance/market` 剥离两动作）+ `china_finance_rss/config.py`（`_FINANCE_EXPECTED_KEYS` 删 1 键）· 归属 **Layer 3（HTTP 入口 / 编排层）**
> 需求来源：本任务书「market_sentiment 独立接口」——`/finance/market` 的 `market_sentiment` 字段由昨日 commit 拼装进去，现改为单独端点 `GET /finance/market_sentiment`
> 先例（**命名 / 分层 / 异常风格必须与之一致**）：`server.py:321 handle_finance_timeline`（`/finance/timeline` 已从 `/finance/market` 拆分同型）；`server.py:272 handle_finance_market`（剥离 `data.pop('timeline', None)` 同处）
> 数据源（**已就绪，CDP 层零改动**）：`cdp_engine.API_KEY_MAP` 已映射 `'dingpan': 'market_sentiment'` 与 `'emotion': 'market_sentiment'`（commit 71ec4e0）；`INTERCEPTOR_JS._shouldCapture` 已拦截 `emotion`/`dingpan` URL；`cls_finance` 页面 `KEY_TTL_OVERRIDES['market_sentiment']=60`（`cdp_engine.py:481`）
> 关联详设：`doc/detailed/server.md`（路由 / `_PANEL_HANDLERS` / `_send_json_shape` / `_cache_age` 权威）· `cdp_engine.md`（`page_data` / `API_KEY_MAP`）· `config.md`（`_FINANCE_EXPECTED_KEYS` / `cache_policy`）· `cache.md`（`_fill_missing`）——**各文档版本以其自身头部为准**
> 端锁定 🟠 STABLE（**只增 1 端点**；`/finance/market` 移除 1 个字段——该字段为**昨日新增、尚未对外冻结**，属回退而非破坏；详见 §10#5）

## 1. 模块职责与边界

### 1.1 职责（5 条）

1. **新增 1 个独立 REST 端点** `GET /finance/market_sentiment`（财联社看盘·市场情绪）：从 `cls_finance` CDP 页面取 `market_sentiment` 键，**原样透传**上游包裹对象。
2. **单函数 `handle_finance_market_sentiment() -> dict`**：CDP ready 门 → `get_page('cls_finance')` → `page_data(page)` 防御取数（A 类唯一入口）→ `data.get('market_sentiment')` → `None` 则 `{'error': 'market_sentiment unavailable'}`（**R18：never return bare null**）；与 `handle_finance_timeline` 逐行同型。
3. **从 `/finance/market` 剥离**（R2，**两动作必须同时**）：`handle_finance_market` 内 `data.pop('market_sentiment', None)` **且** `config._FINANCE_EXPECTED_KEYS` 删除该键；只做一个 ⇒ `/finance/market` 仍会出现该键——**只 `pop`（不删 expected）⇒ 值 = `None`；只删 expected（不 `pop`）⇒ 值 = 原值**（`_fill_missing` 双循环语义，见 §2.3 / R2）。
4. **注册面收口**（RG1–RG7，见 §2.5）：`_JSON_SHAPES` + `_PANEL_HANDLERS` + `_CACHE_AGE_DOMAINS` + `_JSON_DISPATCHED_PATHS`（自动）+ `feeds[]` + 首页 `json_apis` + `main()` 启动日志；计数断言 18→19 / 19→20 同步。
5. **一并承接 P8 盲审 5 条 P2 修复**（B-01..B-05，见 §5.5 / §8）：上游契约实测缺口、失败日志、`msg` 类型归一、TTL 静态守卫正则、`config` 注释过期。

### 1.2 明确不做

- **不改 CDP 层**：`API_KEY_MAP` / `INTERCEPTOR_JS` / `KEY_TTL_OVERRIDES` / 页面清单**零改动**——数据源已就绪（§2.4）。
- **不新增 CDP 页面 / 不新增拦截 URL / 不新增批取**：与 `/finance/market` **共享** `cls_finance` 页面的同一份 `page_data`。
- **不新增缓存容器 / 不新增 metrics**：端点无终端缓存；`max-age` 复用 `cache_policy('quote')`（URL 级统计由 cache 承担）。
- **不改既有 19 个 JSON 端点 / 5 个 RSS / `/healthz` 的既有契约**（仅 `_JSON_SHAPES` +1、`feeds[]` +1、`/finance/market` 去 1 键）。
- **不做鉴权 / 多租户 / 前端 / 小程序**（纯后端只读端点）。

### 1.3 layerIsolation 约束

`tech-stack.json` 未对 `server.py` 单列 `layerIsolation` 条目；本增量遵守既有分层方向与 allowlist：**允许 import = 无新增**（仅复用既有 `cdp_engine.page_data` / `config` / `json` / `logging`）；**禁止**新增第三方库 / 第二代码根。依赖方向（`←` 表分层顺序）：`Layer 0: config · Layer 1: cache · Layer 3: server ← {config, cache, cdp_engine, utils}`。

> 本增量**不新增跨模块边**：`server → cdp_engine` / `config` / `cache` 均既有方向、**无环**。

### 1.4 与基础层 / 数据层接口对齐（不得偏离）

| 接口 | 本增量用法 |
|------|-----------|
| `cdp_engine.get_page('cls_finance')` | 取持久页面（与 `/finance/market`、`/finance/timeline` 同一页） |
| `cdp_engine.page_data(page) -> dict \| None` | **A 类唯一防御取数入口**（总函数，绝不抛；`None` ⇒ 端点降级） |
| `config._FINANCE_EXPECTED_KEYS` | 剥离动作 ②：**删** `'market_sentiment'`（`config.py:204-207`） |
| `config.cache_policy('quote')['ttl']` | `max-age` **唯一来源**（经 `_CACHE_AGE_DOMAINS`；**禁止**裸 TTL 字面量，BR-CFG-12） |
| `server._send_json_shape(path, fn)` | 分发 + `_guard` 降级（`object` shape ⇒ 恒 200 + error body，N1） |

---

## 2. 接口契约

### 2.1 路由总表（OpenAPI 风格，**唯一权威**）

```yaml
openapi: 3.0.3
info: {title: china-finance-rss market_sentiment, version: '1.0'}
paths:
  '/finance/market_sentiment':   # shape=object · CDP A 类
    get: {responses: {'200': {description: '{"code":<int>,"msg":<str>,"data":{...}}（上游原样）；降级 {"error":"..."}（均 200）'}}}
  '/finance/market':             # ★ 变更：成功体/降级体均不再含 market_sentiment 键
    get: {responses: {'200': {description: 'object（去掉 market_sentiment）或降级体 {"error":"..."}（均 200）'}}}
# 无 query 参数 / 无请求体 / 无鉴权；方法仅 GET（HEAD 由基类处理）；未注册路径 → 404
```

**HTTP 状态语义（唯一口径）**

| 情形 | 状态 / 体 |
|------|----------|
| 上游成功（页面含 `market_sentiment`） | `200` + 上游原样对象 `{code, msg, data}` |
| CDP 未就绪（`cdp_engine` 为 None 或 `ready=False`） | `200` + `{"error":"Chrome CDP not available. See README."}` |
| `page_data(page)` 返回 `None` | `200` + `{"error":"Finance page not initialized."}` |
| 页面数据**缺 `market_sentiment` 键** | `200` + `{"error":"market_sentiment unavailable"}`（**R18：禁止裸 `null`**） |
| handler 意外抛异常（`_guard` 兜底） | `200` + `{"error":"<str>"}`（**N1：状态码不由 payload 内容决定**） |
| 未知路径 | `404`（既有 `send_error`） |

### 2.2 `handle_finance_market_sentiment() -> dict`

```python
def handle_finance_market_sentiment():
```

- **无参数**（与 `handle_finance_timeline` / `handle_market_timeline` 同类；不需要 `feed_url` 回链）。
- **总函数**：任意 CDP / 页面状态都返回 `dict`，**绝不抛**（项目约定 `handle_*` 返回 dict 不抛）。
- 成功 → 上游 `market_sentiment` 值**原样透传**（`dict`，含 `code`/`msg`/`data`）；失败 → `{'error': <str>}`。
- 消费者：`_handle_request` 的 `_PANEL_HANDLERS` 表驱动分支 → `_send_json_shape(path, handle_finance_market_sentiment, write_body=...)`。
- **返回类型边界**：若页面里 `market_sentiment` 值本身是 `dict`（预期），原样返回；**不裁剪 / 不重命名 / 不补默认值**（R5）。

### 2.3 `/finance/market` 剥离改动（R2，**两动作必须同时**）

```python
# server.py handle_finance_market（现状 282 行附近）
    ws_raw = data.pop('__ws__', None)
    data.pop('timeline', None)
    data.pop('market_sentiment', None)          # ★ 动作 ①（新增，与 timeline 剥离同处）
    result = {}
    _fill_missing(result, data, _FINANCE_EXPECTED_KEYS)

# config.py:204-207
_FINANCE_EXPECTED_KEYS = frozenset({
    'articles', 'advance_decline', 'live_refresh', 'anchor', 'basic_info',   # ★ 动作 ②：删 'market_sentiment'
})
```

**为什么必须两动作同时**（`cache.py:1155-1161 _fill_missing` 语义，**逐行实核**）：`_fill_missing` 先对 **expected 键**取 `data.get(key)`（**expected 键缺失 ⇒ 补 `None`**），再把 **`data` 中的非 expected 键**以 extra key 填回（第二循环 `if k not in expected_keys: result[k] = v`）。故**两个单动作的可观测结果不同**：

| 组合 | 走的分支 | 结果 | 正确？ |
|------|---------|------|-------|
| 只删 expected（不 `pop`） | `data` 仍含该键、expected 不含 ⇒ 走 **extra 分支**填回 | `result['market_sentiment']` = **原值** | ❌ 键仍在（原值） |
| 只 `pop`（不删 expected） | `data` 不含、expected 含 ⇒ 走 **expected 分支**补 `None` | `result['market_sentiment']` = **`None`** | ❌ 键仍在（`None`） |
| **两动作齐做** | 键既不在 `data`、也不在 expected | **不出现在 result** | ✅ 真剥离 |
| 两动作都不做 | 键在 `data`、是 expected | 原值透传（= 现状） | ❌ 未剥离 |

> **注**：只删 expected 与只 `pop` 的**键均在**（均未真剥离），但**可观测值不同**——只删 expected ⇒ **原值**（下游可能误判为"实时数据"）、只 `pop` ⇒ **`None`**（下游可能误判为"情绪数据为空"）。**两动作齐做**才消除该键。回归用例 MS-T9 用 (a)/(b)/(c) 三条子断言**分别锁定这两个单动作的不同值**与真剥离。

### 2.4 上游契约 / 数据源（**CDP 层已就绪，禁止改动**）

```yaml
data_source:
  cdp_page: cls_finance                    # 与 /finance/market、/finance/timeline 同一持久页
  key: market_sentiment
  url_patterns: ['emotion', 'dingpan']     # API_KEY_MAP（cdp_engine.py:151-178）；dingpan=/v2/quote/a/web/dingpan（改版）
  interceptor: _shouldCapture 已含两模式（cdp_engine.py:198）
  page_key_ttl: 60                         # KEY_TTL_OVERRIDES['market_sentiment']（页面自刷新）
  value_envelope: {code: <int>, msg: <str>, data: {market_degree: <num>, ...}}
```

> **本增量 CDP 层零改动**：`API_KEY_MAP` / `INTERCEPTOR_JS` / `KEY_TTL_OVERRIDES` / 页面注册均不变——只新增一个 server 层读取端点。

### 2.5 注册点清单（**一个不漏**；`文件:行` 以当前工作区为准）

> **编号说明**：本详设**业务规则**用 `R1..R10`（§4）、**注册点**用 `RG1..RG7`（本表）——两套编号不冲突。

| # | 文件:行 | 现状 → 目标 | 不做的后果 |
|---|---------|-------------|-----------|
| **RG1** | `server.py:527-536` `_JSON_SHAPES` | **18 → 19** 条（+ `'/finance/market_sentiment': 'object'`）；`assert len == 18`（`:537`）→ **19** | 新路径落 404（BR-SRV-2）/ import 期 `AssertionError` |
| **RG2** | `server.py:552-557` `_PANEL_HANDLERS` | **4 → 5** 项（+ `'/finance/market_sentiment': handle_finance_market_sentiment`） | 新路径 404（无分支） |
| **RG3** | `server.py:579-593` `_CACHE_AGE_DOMAINS` | + `'/finance/market_sentiment': 'quote'`（**裁决见 §10#1**） | `max-age` 落 `_DEFAULT_AGE_DOMAIN`（f10=300s） |
| **RG4** | `server.py:570-575` `_JSON_DISPATCHED_PATHS` | **无需手改**：`frozenset(_PANEL_HANDLERS)` 自动含新键；`assert == frozenset(_JSON_SHAPES)` 自动成立（**须确认**） | —（确认项） |
| **RG5** | `server.py:981-1022` `_base_feed_entries` | +1 条（`name` 英文+中文、`path`、`url`、`status='requires_chrome_cdp'`）；docstring `19` → **20** | `/healthz` 不可见；测试计数断言红 |
| **RG6** | `server.py:1598-1618` `_serve_index` `json_apis` | +1 项（`('/finance/market_sentiment', '...', '/finance/market_sentiment', True)`） | 首页不可见 |
| **RG7** | `server.py:1812-1829` `main()` Utilities 日志 | +1 条 `log.info`（与 4 面板同风格，`needs Chrome CDP`） | 启动日志缺项（非阻断） |

**测试计数同步（必须，否则红）**：`tests/test_server_http.py:48`（`len(_JSON_SHAPES)==18`→19）· `:669`（`len(payload['feeds'])==19`→20）· `:680`（`len(entries)==19`→20）。
**非阻断漂移（建议同批）**：`server.py:523` 注释「18 JSON branches」→19；`server.py:982` docstring（RG5 已含）；**`server.py:1286` 分发代码注释「── 4 panels (object)」→「── 5 panels (object)」**（评审 P2-02 行 7 的 `:1286` **实为 `server.py:1286`**，非 `server.md:1286`——见 §12 变更记录 v1.0.1 注）；**`tests/stress_all.py:117`（P2-1）** `/finance/market` 响应键检查清单含 `market_sentiment`（`stress_all.py:116-119`）——剥离后**该键必报 `missing key`**；该脚本不在 unittest discovery（文件名不匹配 `test*.py`）⇒ **不红**，但属真实漂移，**同批从键列表移除 `market_sentiment`**（**本 agent 只登记、不落实现**——代码层由 code-developer 在 P5a 处理）。

---

## 3. 数据结构（yaml）

### 3.1 成功响应体

```yaml
market_sentiment_success:            # = 页面 data['market_sentiment'] 原样透传
  code: <int>                        # 上游信封状态码（200 = 成功）
  msg: <str>
  data: {market_degree: <num>, ...}  # 上游 data（字段随上游，本层不裁剪）
```

> **透传不变式**：返回值 **逐字节等于** `page_data(page).get('market_sentiment')`；本层不新增键、不改键名、不补默认值。

### 3.2 降级响应体

```yaml
market_sentiment_degraded:
  error: <str>   # 'Chrome CDP not available. See README.' | 'Finance page not initialized.' | 'market_sentiment unavailable' | str(exc)
```

> 形态与 `_guard` 对 `object` shape 的降级体一致（`server.md` §2.3）。**无 `code`/`msg`/`data` 键**（失败体与成功体键集合互斥）。

### 3.3 `quote` 域缓存策略（唯一权威 = `cache_policy`，本增量只读）

```yaml
cache_policy('quote'): {tier: L0, ttl: 4, pool_refresh: 4, pool_max: 1000, cache_max: 1000}
# ttl 盘中 4s / 非盘 120s；pool_refresh/pool_max/cache_max 本增量不消费（无去重池、无终端缓存）
```

> **域裁决（§10#1）**：新端点 `_CACHE_AGE_DOMAINS` 映射 **`'quote'`**（与 `/finance/timeline`、`/finance/market` 同族）——CDP 面板 = 实时行情面，`max-age` 随盘中/非盘变化（**禁止**落 f10 的 300s 兜底）。注意：CDP 页 `KEY_TTL_OVERRIDES['market_sentiment']=60` 是**页面数据刷新**节奏，与 HTTP `max-age` 无关，**不得**据此另立档位。

### 3.4 本增量新增 / 变更的内部符号

```yaml
handle_finance_market_sentiment: function   # 新 handler（§2.2）
_PANEL_HANDLERS['/finance/market_sentiment']: handle_finance_market_sentiment   # 4 → 5
_JSON_SHAPES['/finance/market_sentiment']: 'object'                             # 18 → 19
_CACHE_AGE_DOMAINS['/finance/market_sentiment']: 'quote'
config._FINANCE_EXPECTED_KEYS: frozenset 去掉 'market_sentiment'                # 6 → 5 键
handle_finance_market: 新增 data.pop('market_sentiment', None)
```

---

## 4. 业务规则

| 编号 | 规则 | 依据 |
|------|------|------|
| **R1** | **新端点路由 / 形状**：`/finance/market_sentiment` shape = `object`；登记 `_JSON_SHAPES`（RG1）+ `_PANEL_HANDLERS`（RG2）；经 `_send_json_shape` 分发，**shape 从表读、不写死字面量** | §2.1 / §2.5 / BR-SRV-2 |
| **R2** | **剥离两动作同时**：`handle_finance_market` 内 `data.pop('market_sentiment', None)` **且** `config._FINANCE_EXPECTED_KEYS` 删该键。**只做一个 ⇒ `/finance/market` 仍含该键**（`_fill_missing` 语义，§2.3） | §2.3 / `cache._fill_missing` |
| **R3** | **CDP 降级语义（R18 never bare null）**：CDP 未就绪 ⇒ `{'error':'Chrome CDP not available. See README.'}`；`page_data=None` ⇒ `{'error':'Finance page not initialized.'}`；键缺失 ⇒ `{'error':'market_sentiment unavailable'}`。**恒 HTTP 200**（N1）；**绝不返回裸 `null`** | `handle_finance_timeline` 同型 / R18 / N1 |
| **R4** | **注册点完整性**：RG1–RG7 全部落地；计数断言同步（`_JSON_SHAPES` 18→19、`feeds[]` 19→20）；`_JSON_DISPATCHED_PATHS` 断言因并集自动成立（RG4 须确认） | §2.5 |
| **R5** | **返回类型 = 上游原样对象**：成功体**逐字节等于**页面 `market_sentiment` 值（`dict`，含 `code`/`msg`/`data`）；不裁剪/不重命名/不补默认值 | §3.1 |
| **R6** | **缓存域 = `quote`**：`_CACHE_AGE_DOMAINS['/finance/market_sentiment']='quote'`；`max-age` 与 `/finance/timeline` 同源（盘中 4 / 非盘 120）；**禁止**裸 TTL 字面量 | §3.3 / BR-SRV-8 / BR-CFG-12 |
| **R7** | **feeds 索引 +1**：`status='requires_chrome_cdp'`（CDP 依赖，与 `/finance/market` 同）；`_base_feed_entries` 计数 19→20 | §2.5 RG5 / BR-SRV-22 |
| **R8** | **单一数据源**：与 `/finance/market`、`/finance/timeline` 共享 `cls_finance` 页面的 `page_data`；**不新增 CDP 页面 / 不新增拦截 URL / 不改 `API_KEY_MAP`** | §2.4 |
| **R9** | **剥离后 `/finance/market` 契约**：成功体与降级体**均不含** `market_sentiment` 键（该字段为昨日新增、尚未对外冻结，属回退） | §2.3 / §10#5 |
| **R10** | **零新增第三方依赖**；handler 参数平铺（无参）；常量/URL 不硬编码（CDP 层既有常量） | 项目约定 |

---

## 5. 伪代码

> 约束标记沿用项目惯例：本增量为**纯同步只读**（无事务 / 无锁 / 无重试 / 无补偿；CDP 页面刷新由 `cdp_engine` 心跳承担）。

```python
# ══ server.py 新 handler（紧邻 handle_finance_timeline）══════════════════════
def handle_finance_market_sentiment():
    """CLS Finance Market Sentiment (财联社看盘·市场情绪) — from finance CDP page.

    与 handle_finance_timeline 逐行同型；成功 → 上游 market_sentiment 原样对象，
    失败/缺失 → {'error': ...}，绝不抛（R3 / R18）。
    """
    global cdp_engine
    if not cdp_engine or not cdp_engine.ready:              # ① CDP 能力门
        return {'error': 'Chrome CDP not available. See README.'}
    page = cdp_engine.get_page('cls_finance')               # ② 同一持久页
    data = page_data(page)                                  # ③ A 类唯一防御取数
    if data is None:
        return {'error': 'Finance page not initialized.'}
    ms = data.get('market_sentiment')                       # ④ 取键
    if ms is None:                                          #    R18: never bare null
        return {'error': 'market_sentiment unavailable'}
    return ms                                               # ⑤ 原样透传（R5）

# ══ server.py handle_finance_market 改动（R2 动作 ①）═════════════════════════
    ws_raw = data.pop('__ws__', None)
    data.pop('timeline', None)
    data.pop('market_sentiment', None)      # ★ 新增：与 timeline 剥离同处
    result = {}
    _fill_missing(result, data, _FINANCE_EXPECTED_KEYS)

# ══ config.py 改动（R2 动作 ②）════════════════════════════════════════════════
_FINANCE_EXPECTED_KEYS = frozenset({
    'articles', 'advance_decline', 'live_refresh', 'anchor', 'basic_info',
})   # ★ 删除 'market_sentiment'
```

```python
# ══ server.py 注册表（RG1–RG3）════════════════════════════════════════════════
_JSON_SHAPES['/finance/market_sentiment'] = 'object'          # ★ RG1（字面量 +1 条）
assert len(_JSON_SHAPES) == 19                                # ★ 18 → 19
_PANEL_HANDLERS['/finance/market_sentiment'] = handle_finance_market_sentiment  # ★ RG2（4 → 5）
# RG4：_JSON_DISPATCHED_PATHS 经 frozenset(_PANEL_HANDLERS) 自动含新键，
#      assert == frozenset(_JSON_SHAPES) 自动成立 —— 无需手改，仅须确认。
_CACHE_AGE_DOMAINS['/finance/market_sentiment'] = 'quote'     # ★ RG3（与 /finance/timeline 同族）

# ══ server.py feeds（RG5）+ 首页（RG6）+ main 日志（RG7）═════════════════════
# _base_feed_entries docstring: '19 healthz feed entries' → '20'
feeds.append({'name': 'CLS Finance Market Sentiment (财联社市场情绪)',
              'path': '/finance/market_sentiment',
              'url': base_url + '/finance/market_sentiment', 'status': 'requires_chrome_cdp'})
# _serve_index json_apis 追加：
#   ('/finance/market_sentiment', 'Market Sentiment (市场情绪)', '/finance/market_sentiment', True)
# main() Utilities 追加（同 4 面板风格，needs Chrome CDP）
```

```python
# ══ 分发分支：**零改动**（RG2 已并入 _PANEL_HANDLERS 表，既有分支自动覆盖）══
        if path in _PANEL_HANDLERS:                            # server.py:1353 既有
            self._send_json_shape(path, _PANEL_HANDLERS[path], write_body=write_body)
            return
```

### 5.5 P8 盲审 5 条 P2 修复伪代码（B-01..B-05）

```python
# ── B-02（server.py handle_cls_pool except 内，:513-514）失败路径补日志 ──────
#    P2-5（P7b-r2）：改为**限频**实现——负缓存（NEG_TTL=5s）窗口内同一失败对
#    每个请求重复发生，逐次告警会使日志量随 RPS 线性放大；故同 pool_type 同错误
#    消息 30s 窗口内只告警一次，错误消息变化时即时再告警（新失败模式 = 新信号）。
#    消息格式逐字不变（log scraper / MS-T13 匹配口径不变）。
    except Exception as exc:                  # FetchError / JSON decode / …
        _warn_pool_fetch_failed(pool_type, exc)   # ★ P2-5 限频（原 log.warning 直写）
        return {'error': str(exc)}

# ── B-02 限频实现（server.py:466-483，P2-5）────────────────────────────────
_POOL_FETCH_WARN_GAP = 30.0        # 同 pool_type 同消息的两次告警最小间隔（秒）
_pool_fetch_warned_at = {}         # pool_type -> (last_ts, last_msg)；键 ∈ _POOL_TYPES ⇒ 有界 ≤4 键

def _warn_pool_fetch_failed(pool_type, exc):
    msg = str(exc)
    prev = _pool_fetch_warned_at.get(pool_type)
    now = time.monotonic()         # ★ P8-r1 P2：间隔 ⇒ 单调钟（非墙钟；NTP 步不影响窗口）
    if (prev is not None and prev[1] == msg
            and now - prev[0] < _POOL_FETCH_WARN_GAP):
        return                      # 同失败、仍在窗口内 ⇒ 静默
    _pool_fetch_warned_at[pool_type] = (now, msg)
    log.warning('[server] cls pool %s fetch failed: %s', pool_type, msg)   # 格式逐字不变

# ── B-02 成功路径 episode 结束（server.py:533，P8-r1 P2）────────────────────
    _pool_fetch_warned_at.pop(pool_type, None)   # ★ 一次成功结束该池失败 episode
    return {'stocks': data}                     # 其后同 kind 同消息失败 = 新 episode ⇒ 必再告警

# ── B-03（server.py:520-521）error 值归一为 str ─────────────────────────────
    if raw.get('code') != 200:
        return {'error': str(raw.get('msg') or 'upstream_error')}   # ★ 外层 str()（msg 非字符串时防类型漂移）

# ── B-05（config.py:387）plate 行注释补 4 池 ────────────────────────────────
    'plate': ('L2', 1.0, 1.0, 'fixed:200', 'n/a'),   # cls/hotplate, cls/plate, 4 cls pools (URL cache)
```

```python
# ── B-01（tests/test_server_http.py）默认 skip 的 4 池真实上游冒烟 ───────────
import os
@unittest.skipUnless(os.getenv('CLS_INTEGRATION'), 'set CLS_INTEGRATION=1 to smoke')
class ClsPoolIntegrationTests(unittest.TestCase):
    """B-01: 4 pools vs REAL upstream (catches type/way/data drift); default-skipped."""
    def test_four_pools_return_200_with_list_stocks(self):
        for path, pt in srv._POOL_HANDLERS.items():
            result = srv.handle_cls_pool(pt)                 # 真 fetch_json
            self.assertNotIn('error', result, path)
            self.assertIsInstance(result['stocks'], list, path)

# ── B-04（tests/test_server_http.py:294-301）TTL 守卫正则收窄 ────────────────
        source = inspect.getsource(srv.handle_cls_pool)
        self.assertIsNone(re.search(r'ttl=\s*\d+', source),          # ★ 任意数字裸字面量
                          'bare TTL literal in handle_cls_pool')
        self.assertIn("cache_policy('plate')", source)               # 保留
```

> **skip 风格裁决（§10#2）**：采用 `@unittest.skipUnless(os.getenv('CLS_INTEGRATION'), ...)`——与项目既有 env 门控脚本（`tests/stress_all.py` 的 `STRESS_URL`）一致；项目 unittest 内**无** `skipUnless` 先例，本详设**确立**该风格（env 名 `CLS_INTEGRATION`）。**默认跳过、不依赖外网跑全量**（项目测试纪律）。

---

## 6. 错误处理

| 情形 | 产生层 | 行为 | 对外形态（恒 200） |
|------|--------|------|-------------------|
| CDP 未就绪（`cdp_engine` None / `ready=False`） | `handle_finance_market_sentiment`（R3） | 直接返回、**不取页** | `{"error": "Chrome CDP not available. See README."}` |
| `get_page('cls_finance')` 返回 None | `page_data(None)` | 返回 None | `{"error": "Finance page not initialized."}` |
| 页面数据为 None / 空 dict / `get_data` 抛 | `cdp_engine.page_data`（内部捕获） | 返回 None | `{"error": "Finance page not initialized."}` |
| 页面数据缺 `market_sentiment` 键 | `handle_finance_market_sentiment`（R3/R18） | `data.get` 返回 None | `{"error": "market_sentiment unavailable"}`（**非**裸 `null`） |
| handler 意外抛异常（未预期） | `_guard`（`_send_json_shape` 内兜底） | `log.exception` + 降级 | `{"error": str(exc)}` |

**降级路径**：本增量降级**只降级响应体形态**，不降级为异常外抛（`handle_*` 约定）。**真实 503 不涉及**（业务端点恒 200，N1）；`http_503_total` 不受影响。**B-02** 补的 `log.warning` 属**兄弟函数**（`handle_cls_pool`）的可观测性修复，与本端点无关。

---

## 7. 并发安全

| 项 | 结论 |
|----|------|
| 本增量持有的锁 | **无**——`handle_finance_market_sentiment` 纯函数式（局部变量 + 既有全局只读引用） |
| `_PANEL_HANDLERS` / `_JSON_SHAPES` / `_CACHE_AGE_DOMAINS` / `cache_policy('quote')` | 导入期构建 / 纯函数，运行期只读；多线程只读安全 |
| `cdp_engine.get_page` / `page_data` | 页面对象由 `cdp_engine` 自管（既有并发协议）；`page_data` 为总函数（绝不抛），本增量不持锁调用 |
| 并发读者 | 与 `/finance/market`、`/finance/timeline` 读**同一份** `page_data`，无共享可变状态 ⇒ 无竞态 |

> **无锁设计**是刻意的：本增量不引入终端缓存 / 池 / 账本，并发安全责任由 `cdp_engine` 既有页面协议承担。

---

## 8. 测试要点（映射 AC；**引用现有面板 / 池测试模式**）

> 落地位置建议：`tests/test_server_http.py`（扩 `ShapeTableTests`·`CacheAgeTests`·`HealthPayloadTests`·`HttpSemanticsTests`·`ClsPoolTests` + 新增 `MarketSentimentTests` / `ClsPoolIntegrationTests`）与 `tests/test_server.py`（handler 单测）。打桩：`patch.object(srv, 'page_data', ...)` / `patch.object(srv, 'cdp_engine', ...)`（参照 `SRV-T28` 面板降级用例）。

| 用例 | 步骤 / 断言（精确） | 覆盖 |
|------|-------------------|------|
| **MS-T1** 路由 / 形状登记 | `srv._JSON_SHAPES['/finance/market_sentiment'] == 'object'`；`srv._PANEL_HANDLERS['/finance/market_sentiment'] is srv.handle_finance_market_sentiment`；路径 ∈ `srv._JSON_DISPATCHED_PATHS`；`len(srv._JSON_SHAPES) == 19`（`ShapeTableTests` :48 改写 18→19） | R1 / R4 / RG1·RG2·RG4 |
| **MS-T2** 成功透传 | patch `page_data` → `{'market_sentiment': {'code':200,'msg':'','data':{'market_degree':88}}}`；`handle_finance_market_sentiment()` 返回**同一对象**（`assertEqual` 逐字段） | R5 |
| **MS-T3** CDP 未就绪 | `patch.object(srv, 'cdp_engine', None)` ⇒ `{'error':'Chrome CDP not available. See README.'}`；再 `ready=False` 变体同断言 | R3 |
| **MS-T4** page_data None | `patch.object(srv, 'page_data', return_value=None)` ⇒ `{'error':'Finance page not initialized.'}` | R3 |
| **MS-T5** 键缺失 never bare null | `page_data → {'basic_info':{...}}`（无 market_sentiment）⇒ `{'error':'market_sentiment unavailable'}`；**断言 `result is not None` ∧ `'error' in result`** | R3 / **R18** |
| **MS-T6** HTTP 分发 + 恒 200 | 本地 `BoundedThreadPoolServer`，stub 成功 ⇒ `GET /finance/market_sentiment` **200** + body 对象；stub 降级 ⇒ **200** + `{'error':...}`；`http_503_total` **不变**（N1，参照 `SRV-T36`） | R1 / N1 |
| **MS-T7** cache-age 域 | `srv._CACHE_AGE_DOMAINS['/finance/market_sentiment'] == 'quote'`；`h.path=…; h._cache_age() == cache_policy('quote')['ttl']`（参照 `CacheAgeTests` :560） | R6 / RG3 |
| **MS-T8** `/finance/market` 已剥离 | stub `page_data` 含 `market_sentiment` ⇒ `handle_finance_market()` 结果 `'market_sentiment' not in result`（同时 `'articles'` 等仍在） | R2 / R9 |
| **MS-T9** 剥离双动作（**关键陷阱**） | 三子断言，**分别对正确实现全绿、对任一单动作回归必红**：(a) 仅删 expected 不 pop（`_fill_missing({}, data, expected_without_key)`，`data` 仍含键）⇒ `assertIn('market_sentiment', result)` **∧** `assertEqual(result['market_sentiment'], 原值)`（键**在**、值 = **原值**）；(b) 仅 pop 不删 expected（`_fill_missing({}, data_minus_key, expected_with_key)`）⇒ `assertIn(...)` **∧** `assertEqual(result['market_sentiment'], None)`（键**在**、值 = **`None`**）；(c) 两动作齐做（`_fill_missing({}, data_minus_key, expected_without_key)`）⇒ `assertNotIn('market_sentiment', result)`（键**不在**）。**注意 (a) 断言方向**：仅删 expected ⇒ 经 extra 分支填回**原值**，**非**"键不在"（`cache.py:1155-1161` 实核；原 v1.0.0 方向写反） | R2 |
| **MS-T10** feeds 索引 | `len(_base_feed_entries('http://x')) == 20`；`entries['/finance/market_sentiment']['status'] == 'requires_chrome_cdp'`；`len(build_health_payload('http://x')['feeds']) == 20`（`:669`/`:680` 改写 19→20） | R7 / RG5 |
| **MS-T11** HEAD + 首页登记 | `HEAD /finance/market_sentiment` ⇒ **200**（只锁状态码；**body `== b''` 断言已删**——`http.client` 对 HEAD 把读取长度归零（RFC 9112 §9.3.2），该断言恒真、无区分度；HEAD body 的**线上无 body 保证由 MS-T11b**（裸 socket `_raw_exchange` 实测线上字节）承担）；`_serve_index()` body 含该路径（参照池首页用例） | R1 / RG6 |
| **MS-T12**（**B-01**）上游真实冒烟 | `@skipUnless(os.getenv('CLS_INTEGRATION'))`；对 4 池各 1 次真 `handle_cls_pool` ⇒ `'error' not in result` ∧ `isinstance(result['stocks'], list)`（§5.5） | B-01 |
| **MS-T13**（**B-02**）失败有日志 | patch `fetch_json` 抛 ⇒ `with self.assertLogs('server', level='WARNING')` 命中含 `'cls pool'`；结果仍 `{'error': ...}`（可证伪：删 `log.warning` ⇒ 断言红）。**该用例现自带 `_pool_fetch_warned_at` save/clear/restore 隔离（hermetic）**——执行前保存限频表快照、执行后清空并恢复，其可证伪性不再依赖用例执行顺序（P7b-r3 对抗性复查后补） | B-02 |
| **MS-T14**（**B-03**）msg 归一 str | `{'code':9000,'msg':123}` ⇒ `handle_cls_pool('up_pool') == {'error':'123'}` 且 `isinstance(result['error'], str)`（可证伪：不加 `str()` ⇒ 值为 int ⇒ 红） | B-03 |
| **MS-T15**（**B-04**）TTL 守卫正则 | **双向显式**（负向断言设计不变，仅补全表述）：① **真实源码必不命中**——`source = inspect.getsource(srv.handle_cls_pool)`，新正则 `r'ttl=\s*\d+'` 对其**必不命中**（`assertIsNone`；真实码为 `ttl=cache_policy('plate')`，`=` 后是字母 `c`，正则**正确放行** policy 调用——**期望行为、非规避**）；② **合成串必命中**——`'ttl=30'`/`'ttl=60'`/`'ttl=300'` 对新正则**必命中**（`assertIsNotNone`），且对旧正则 `r'ttl=\s*12\d*'` **必不命中**（证旧守卫假阴性：漏 `30`/`60`/`300`）；保留 `assertIn("cache_policy('plate')", source)`。**避免开发者误写成对真实源码 `assertIsNotNone` 的伪红** | B-04 |
| **MS-T16**（**B-05**）config 注释 | `inspect.getsource(config)` 中 `plate` 行注释含 `4 cls pools`（可证伪：注释未补 ⇒ 红） | B-05 |
| **MS-T17**（**B-02**）失败告警限频 | `test_fetch_failure_warning_is_rate_limited`（`tests/test_server_http.py`）：patch `fetch_json` 抛同一异常 ⇒ 首次告警、30s 窗口内同 pool_type 同错误**静默**（日志计数不变）、错误消息变化**即时再告警**、窗口后**续报**；自带 `_pool_fetch_warned_at` save/clear/restore 隔离（hermetic）。锁定"负缓存下日志限频"行为（同 pool_type 同错误 30s 窗口一条） | B-02 |
| **MS-T18**（**B-02**）单调钟窗口 | `test_rate_limit_window_uses_monotonic_clock`（`tests/test_server_http.py:429`）：patch `srv.time.monotonic` 注入 1000/1010/1040，warn→silent→warn，断言表内时间戳 == 1040.0。可证伪：实现仍读 `time.time()` ⇒ 注入钟不到达 ⇒ 第三次调用仍在墙钟窗口内 ⇒ `assertLogs` 空 ⇒ 红 | B-02 / P8-r1 P2 |
| **MS-T19**（**B-02**）成功结束 episode | `test_success_clears_the_warn_episode`（`tests/test_server_http.py:468`）：fail(warn)→同 fail(silent)→成功→`'up_pool' not in` 表→再 fail(warn)。可证伪：删成功路径 pop ⇒ 旧 `(ts,msg)` 留存 ⇒ 末次 `assertLogs` 空 ⇒ 红 | B-02 / P8-r1 P2 |
| **MS-T20**（**O1**）HEAD 内在守卫 | `test_head_guard_is_intrinsic_to_send_text`（`tests/test_server_http.py:1234`）：`patch.object(RSSHandler,'_handle_request', 误传 write_body=True 调 _send_error)`，裸 socket 先 GET 自证再 HEAD 断言 body==b'' 且 Content-Length>0。可证伪：删 `_send_text` 的 `!= 'HEAD'` 守卫 ⇒ HEAD 线上带 body ⇒ 裸 socket 读到非空 ⇒ 红 | O1 / RFC 9112 §9.3.2 |

> **压测覆盖**：`/finance/market_sentiment` 已纳入 `tests/stress_all.py` 压测清单（`GLOBAL_ENDPOINTS` + `check_endpoint` 分支）。

---

## 9. AC 追溯矩阵

> **本增量无专属 PRD AC**（需求来自任务书原文，非 `doc/prd/perf-stability-optimization.md`）——登记见 §10#3。下表映射到**项目既有约束 / AC**。

| 本增量设计点 | 覆盖 |
|-------------|------|
| `handle_finance_market_sentiment` 总函数 + `_guard` 兜底 / 键缺失 ⇒ error 客体而非裸 `null`（R3） | **AC-S1**（异常兜底）/ **R18 / AC-S4**（面板降级 error 客体，HTTP 200） |
| CDP 不可用 ⇒ error 客体 + 200（R3 / N1） | **AC-S4**（A 类 CDP 端点）/ **A5** |
| `_CACHE_AGE_DOMAINS` → `quote`（R6） | **BR-SRV-8**（max-age 经 policy 域）/ `SRV-T11`·`SRV-T43` 同源口径 |
| `_JSON_SHAPES` 计数 19 + `_JSON_DISPATCHED_PATHS` 断言（R4） | **P1-6 结构护栏**（导入期失败而非静默 404） |
| `feeds[]` +1（R7） / `/finance/market` 去 1 键（R2/R9） | **BR-SRV-22**（healthz 可见性）/ **S4**；端锁定 🟠（字段回退，须 `API.md` 同步） |
| B-01..B-05（§5.5） | 既有盲审 P2 修复（可观测性 / 类型稳健 / 测试守卫 / 契约实测） |

---

## 10. 与 SAD / 现有代码的偏差与歧义标注（不擅自改方案）

| # | 项 | 表述 | 本文裁决 / 偏差 | 理由 |
|---|----|------|----------------|------|
| 1 | **`_CACHE_AGE_DOMAINS` domain 选择** | 任务书留由详设裁决 | **裁决：`'quote'`**（与 `/finance/timeline`·`/finance/market` 同域） | 新端点是 `cls_finance` CDP 面板 = 实时行情面，`max-age` 应随盘中/非盘变化；`KEY_TTL_OVERRIDES['market_sentiment']=60` 是**页面数据刷新**节奏，与 HTTP `max-age` 无关，**不**据此另立档位。沿用 `quote` 与既有 4 面板一致、无新语义 |
| 2 | **B-01 integration skip 风格** | 任务书留由详设裁决 | **裁决：`@unittest.skipUnless(os.getenv('CLS_INTEGRATION'), ...)`** | 项目 unittest **无** skip 先例；既有 env 门控在脚本（`stress_all.py` 的 `STRESS_URL`）——本详设**确立** unittest 内的 env-gated skip 风格，**默认跳过、不依赖外网跑全量**（项目测试纪律） |
| 3 | **无专属 PRD AC** | 需求来自任务书原文，PRD 无对应 AC | 本详设**按任务书原文承接**，AC 追溯见 §9（映射既有约束）；**建议编排层 / system-architect 决定是否回填 SAD/PRD**（本 agent 不改 `doc/arch/` / `doc/prd/`） | 属新功能增量，非既有性能专项 AC 范围 |
| 4 | **独立文档 vs 并入 `server.md`** | 任务书要求「新建独立详设」+「更新 `server.md` 增量登记」 | **裁决：新建 `market_sentiment_独立接口.md`（本文）+ `server.md` 做增量登记**（新端点 + 计数 18→19 / 19→20 写入 §1.1/§2.1/§2.2/§2.8/§2.9.1/§3.3/§5.8 + v1.18 变更块） | 1 端点 + 1 键剥离 + 7 注册点构成自洽增量，独立成文便于评审；`server.md` 含端点规格与注册点清单，故**按任务书做增量登记**（非仅列清单） |
| 5 | **`/finance/market` 去键属契约变更** | 端锁定分级 | **标 🟠 STABLE**（非 🔴） | 被删字段 `market_sentiment` 为**昨日新增、尚未对外冻结**（`API.md:332` 亦为昨日同步），属**回退**而非破坏既有冻结面；仍**必须**同步 `API.md`/`README.md`（DOC_SYNC） |
| 6 | **对外文档同步（out of scope）** | `API.md` / `README.md` 需改 | 本 agent **只写 `doc/detailed/`**，**不碰 `API.md`/`README.md`** ⇒ 输出 `>>DOC_SYNC:`（见 §12 末） | 契约文档修改权在编排层 |
| 7 | **非阻断漂移** | `server.py:523` 注释「18 JSON branches」、`:982` docstring「19」 | 建议同批改为 19 / 20（**不改不红**，仅文档一致性） | 与 RG1/RG5 同源 |

### Step 2.5 链式推导（7 规则）

| 规则 | 结论 |
|------|------|
| 规则零（需求缺口） | 需求 = 「market_sentiment 拆独立接口」——**1 端点已完整覆盖**（键↔端点一一对应）⇒ **无补充接口** |
| 规则一（读写配对） | 全为 `GET`（读）；**无 PUT/DELETE/PATCH**，无写配对需求 |
| 规则二（状态机） | **无状态实体**；仅「成功（原样对象）/ 降级（error 客体）」二值（穷举封闭：CDP 未就绪 / page_data None / 键缺失 / 意外异常 ⇒ 降级） |
| 规则三（跨模块依赖） | `server → cdp_engine`（`get_page`/`page_data`，既有）；`server → config`（`_FINANCE_EXPECTED_KEYS`/`cache_policy('quote')`，既有）；`server → cache`（`_fill_missing`，既有）——**均既有方向、无环** |
| 规则四（数据生命周期） | **无持久化**；数据由 CDP 页面自刷新（`KEY_TTL_OVERRIDES['market_sentiment']=60`）；本增量不写库、不建表、不新增缓存 |
| 规则五（异步流程） | **无异步 / 无任务状态 / 无死信**（纯同步取数） |
| 规则六（权限 / 数据隔离） | **无鉴权 / 无多租户**（只读公开数据）；不改 `layerIsolation`（`cdp_engine`/`config`/`cache` 均在既有 allowlist） |

---

## 11. 交付自检

- [x] §3 为 `yaml` 代码块（成功体 / 降级体 / quote 策略 / 内部符号）
- [x] 业务规则有编号（R1–R10），精确到字段 / 取值，配置来源已标注；注册点用 RG1–RG7（编号不冲突）
- [x] 接口有完整 OpenAPI 定义（新端点请求 / 响应 schema + 错误语义 + 状态码表）
- [x] 注册点 **RG1–RG7 一个不漏**（含 RG4「自动成立须确认」）；计数 18→19 / 19→20 已列
- [x] 核心伪代码含 `handle_finance_market_sentiment` + `handle_finance_market` 剥离 diff + config 剥离 + 注册表 edits
- [x] B-01..B-05 均给**伪代码级修复规格**（§5.5）+ 各 1 条可证伪用例（MS-T12..MS-T16）
- [x] 测试用例引用现有面板 / 池模式（`SRV-T28`/`SRV-T36`/`CacheAgeTests`/`ShapeTableTests`）
- [x] 无 `{例:` / 无 `{...}` 占位符残留；两处不确定项（§10#1/#2）已给**裁决 + 理由**
- [x] **未改任何代码 / 测试 / `API.md` / `README.md`**（仅新增本详设 + `server.md` 增量登记 + `_PROGRESS.md`）

---

## 12. 变更记录

| 版本 | 日期 | 变更类型 | 变更内容 | 变更人 |
|------|------|---------|---------|--------|
| v1.0.0 | 2026-10-10 | 🆕 新建 | market_sentiment 独立接口详设：`/finance/market_sentiment`（CDP A 类）+ `handle_finance_market_sentiment` + `/finance/market` 剥离两动作（`data.pop` + `_FINANCE_EXPECTED_KEYS` 删键）+ **7 注册点 RG1–RG7** + 16 用例（含 B-01..B-05 修复规格）；同步 `server.md` 增量登记（v1.18） | task-decomposer |
| v1.0.1 | 2026-10-10 | 🔧 评审闭环（P1-01 + P2×5） | 闭环 `doc/review/market_sentiment_详细设计评审_专家版.md`（REV-DES-20261010-002，⚠️ 有条件通过 P0×0 / P1×1 / P2×5）：**P1-01** §2.3 语义表按 `cache.py:1155-1161` 实际语义重写（只删 expected ⇒ **原值**、只 pop ⇒ **`None`**、两动作齐做 ⇒ 键不在）+ §1.1 职责 3 值方向显式化 + **MS-T9(a) 断言方向纠正**（由"键不在"改为 `assertIn` + `assertEqual(原值)`）；**P2-1** §2.5 补登 `stress_all.py:117` 键清单移除 `market_sentiment`；**P2-2** 同步 `server.md` → v1.19（**8 处「4 面板/面板 4」→「5 面板」+ 3 处「18 JSON」→「19 JSON」**——评审清单 9 处 + 验证额外发现 §9 `:2034` / §10#4 `:2088`；**评审行 7 的 `:1286` 实为 `server.py:1286`**，登记为代码注释漂移）；**P2-3** DOC_SYNC 补 `cdp_engine.md` `:751/:752`「A 类 4 端点」→5；**P2-4** DOC_SYNC 补全 SAD 计数落点（`:71-72`/`:114`/`:441`/`:560`/`:804`）；**P2-5** MS-T15 双向表述补全。**只改文档**；未改代码 / 测试 / `API.md` / `README.md` / `SAD` / `cdp_engine.md` | task-decomposer |
| v1.0.2 | 2026-10-10 | 🔧 契约同步（P7b-r2 Bug-fix Loop） | code-developer 完成 3 条 P2 代码修复（不改对外契约）后的文档回填：**§5.5 B-02** 失败日志改为**限频**实现——`_warn_pool_fetch_failed(pool_type, exc)` + 窗口常量 `_POOL_FETCH_WARN_GAP=30.0`（同 pool_type 同错误 30s 窗口内只告警一次、错误消息变化即时再告警、消息格式逐字不变；负缓存窗口内日志不再随 RPS 放大）；**§8 MS-T11** 删除 HEAD body `== b''` 断言描述（`http.client` 下恒真、用例已删），HEAD body 线上校验由 MS-T11b（裸 socket `_raw_exchange`）承担。**只改文档**；未改代码 / 测试 / `API.md` / `README.md` / `SAD` | 编排层（P7b 契约同步） |
| v1.0.3 | 2026-10-10 | 🔧 契约同步（P7b-r3 对抗性复查） | 对抗性复查（P8-r1）指出的测试登记漂移补齐：**§8** 新增 **MS-T17**（`test_fetch_failure_warning_is_rate_limited`，B-02 失败告警限频：同 pool_type 同错误 30s 窗口一条、错误变化即时告警、窗口内静默、窗口后续报，自带 `_pool_fetch_warned_at` save/clear/restore 隔离）；**MS-T13** 补注该用例现自带限频表隔离（hermetic），可证伪性不再依赖执行顺序；**§8** 补注 `/finance/market_sentiment` 已纳入 `tests/stress_all.py` 压测清单。**只改文档**；未改代码 / 测试 / `API.md` / `README.md` / `SAD` | 编排层（P7b 契约同步） |
| v1.0.4 | 2026-10-10 | 🔧 契约同步（P7b-r4 契约同步） | P5a-r3 修复 3 条小问题后的文档回填：**§5.5** B-02 限频实现 `now = time.time()` → `now = time.monotonic()`（P8-r1 P2 墙钟→单调钟）；**§5.5** 补成功路径 `_pool_fetch_warned_at.pop(pool_type, None)` episode 语义（P8-r1 P2）；**§5.5** 行号刷新（实现 `:457-474`→`:466-483`、调用点 `:503-504`→`:513-514`、B-03 `:467-468`→`:520-521`）；**§5.4** 分发行号 `:1287`→`:1353`；**§8** 新增 **MS-T18**（单调钟窗口）/ **MS-T19**（成功结束 episode）/ **MS-T20**（HEAD 内在守卫）三行。**只改文档**；未改代码 / 测试 / `API.md` / `README.md` / `SAD` | 编排层（P7b 契约同步） |

> **下游提示（code-developer）**：严格按 §2.5 注册点 RG1–RG7 施工；**先读 `server.py:321 handle_finance_timeline` 与 `server.py:272 handle_finance_market` 再动手**，命名 / 分层 / 异常风格与之一致；**剥离两动作必须同时**（只做一个 ⇒ `/finance/market` 仍含该键，MS-T9 锁定）；`_CACHE_AGE_DOMAINS` 用 `'quote'`。
> **DOC_SYNC（受影响契约文档，由编排层执行）**：
> `>>DOC_SYNC: API.md → 删 `/finance/market` 字段表 `market_sentiment` 行（`:328`/`:332`）+ 新增 `/finance/market_sentiment` 端点节（仿 `:342` `/finance/timeline`）；§6.1 面板口径表（`:686`）四面板措辞可补该端点`
> `>>DOC_SYNC: README.md → JSON Market APIs 表（`:54-68`）新增 `/finance/market_sentiment`（CDP=Yes）；`:58` `/finance/market` 描述去掉 "sentiment"`
> `>>DOC_SYNC: doc/detailed/server.md → v1.18 增量登记 + v1.19 计数收口：§1.1 计数 18→19、§2.1 路由表、§2.2 `_JSON_SHAPES`+assert、§2.8 handler 清单、§2.9.1 feeds 表、§3.3 结构、§5.8 cache-age 表；**v1.19 补 8 处「4 面板/面板 4」→「5 面板」**（`:102`/`:177`/`:181`/`:803`/`:857`/`:953`/`:1835`/`:1843`）+ **3 处「18 JSON」→「19 JSON」**（§6.3 `:1877`；§9 `:2034` / §10#4 `:2088` 验证额外发现）`
> `>>DOC_SYNC: doc/detailed/cdp_engine.md → `:751`「AC-S4（CDP 降级路径 A 4 / A′ 1）」→「A 5 / A′ 1」+ `:752`「AC-S4（A 类 4 端点逐条验证）」→「A 类 5 端点」（**P2-3**；CDP 层零改动，纯计数同步）`
> `>>DOC_SYNC: doc/arch/SAD.md → 计数落点补全（**P2-4**）：① 路由计数 `:71-72`（「14 个 JSON 分支…14 = 面板 4」→ 15 = 面板 5）+ `:114`（R1「14 个 JSON 路由分支」→15）；② A 类清单 `:441`（「A（4 单体/面板）」→「A（5 单体/面板）」）；③ `_guard` 覆盖 `:560`（「全部 14 个 JSON 分支」→15）+ `:804`（server.py 行「全部 14 个」→15）；**本 agent 不改 SAD**（§10#3）`
> `>>DOC_SYNC: tests/stress_all.py → `:117` 键列表移除 `market_sentiment`（**P2-1**；非契约文档/测试资产漂移，不在 unittest discovery ⇒ 不红；**本 agent 只登记、不落实现**，代码层由 code-developer 在 P5a 处理）`
> `>>DOC_SYNC: china_finance_rss/server.py → `:1286` 分发注释「── 4 panels (object)」→「── 5 panels (object)」（**P2-2 行 7 所指实为 `server.py:1286`**，非 `server.md:1286`；与 `:523`「18 JSON branches」→19 同批；**代码层由 code-developer 在 P5a 处理**）`

