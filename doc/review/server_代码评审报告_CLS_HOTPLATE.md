# 代码评审报告 — CLS Hotplate 功能新增

**CR-20260706-002 | 版本: HEAD (CLS hotplate changes) | 状态: ⚠️ 有条件通过**
**评审模式: 纯后端 | 日期: 2026-07-06 | 关联文档: AGENTS.md, CLAUDE.md, 上一轮 CR-20260701-001**

---

## 一、评审概要

| 项目 | 结果 |
|------|------|
| **结论** | ⚠️ 有条件通过（无 P0，P1=2，P2=3） |
| P0 (阻断性) | **0** |
| P1 (高优先级) | **2** |
| P2 (建议改进) | **3** |
| 是否允许进入测试 | ⚠️ 建议修复 P1 问题后再进入测试 |

## 二、评审范围

| 类型 | 文件 | 说明 |
|------|------|------|
| 后端 | `cdp_engine.py` (840 行) | CDP 引擎，`API_KEY_MAP` 新增 3 个 plate 映射 + `_re_fetch_api` |
| 后端 | `server.py` (1072 行) | HTTP 服务，新增 `handle_cls_hotplate`、路由、seed 逻辑 |
| 测试 | `tests/test_server.py` (172 行) | 3 个新测试 + 1 个 OPML 断言更新 |

> **说明：** 本仓库无 `doc/detailed/` 详设文档和 `src/`/`frontend/` 标准目录结构。评审按纯后端模式执行 **维度 1~5**，跳过维度 0（全栈端一致性）和维度 6（前端审查）。

## 三、问题清单

| ID | 等级 | 文件 | 行号 | 问题描述 | 维度 |
|----|------|------|------|----------|------|
| #H1 | P1 | `server.py` | 1024-1032 | `init_cdp()` 中 `time.sleep(3)` 脆弱的时序依赖 + 硬编码 seed URL 可能不正确 | 业务逻辑 |
| #H2 | P1 | `server.py` | 1024-1032 | Seed 逻辑所有异常被 `except Exception: pass` 吞没，失败无告警 | 可维护性 |
| #H3 | P2 | `server.py:1024` | — | 外部模块调用 `hotplate._re_fetch_api()` 私有方法，违反封装 | 可维护性 |
| #H4 | P2 | `cdp_engine.py` | 290-300 | `plate_industry`/`plate_concept`/`plate_area` 未在 `KEY_TTL_OVERRIDES` 中注册 | 编码规范 |
| #H5 | P2 | `tests/test_server.py` | 131-147 | 缺少 `_fill_missing` 与 `_HOTPLATE_EXPECTED_KEYS` 的联合测试 | 测试覆盖 |

---

## 四、问题详情

### 维度 2：业务逻辑

---

#### 🔴 #H1 [P1] `init_cdp()` 中 Seed 逻辑存在脆弱的时序依赖且 URL 正确性不确定

**位置：** `server.py:1023-1032`

```python
hotplate = cdp_engine.add_page('cls_hotplate', 'https://www.cls.cn/hotplate')
if hotplate:
    # Seed concept and area plate data (page defaults to industry tab)
    time.sleep(3)
    for _ptype in ('concept', 'area'):
        _url = f'/web_quote/plate/plate_list?type={_ptype}&way=change&page=1&rever=1'
        try:
            hotplate._re_fetch_api(_url)
        except Exception:
            pass
```

**问题 a)：`time.sleep(3)` 时序脆弱**

`add_page()` 返回后，页面虽然已完成加载（`_connect()` 等待了 `Page.loadEventFired`），但：
- 页面可能还在执行异步 JS 初始化（React hydration、延迟加载的脚本）
- CLS 服务端 session/cookie 可能尚未就绪
- 网络延迟或页面资源阻塞可能导致 `fetch()` 调用失败

若 3 秒不够，`_re_fetch_api` 发送的 `fetch()` 可能失败或被浏览器丢弃（`.catch(() => {})` 静默吞异常）。此时概念/地域板块的 seed 数据永久丢失，因为：
1. 数据不会进入 `__cdp_refetch` → 不会被 heartbeat 收集
2. `_api_urls` 中无记录 → 后续的主动 re-fetch 机制永远不会触发
3. 页面本身只默认加载 industry 标签，不会自动请求 concept/area

用户将永久看到 `plate_concept: null, plate_area: null`，但无任何错误日志。

**问题 b)：seed URL 路径 `/web_quote/plate/plate_list` 正确性未经验证**

seed 使用的 URL 路径为 `/web_quote/plate/plate_list?type=concept&way=change&page=1&rever=1`，但 CLS 前端实际调用的板块列表 API 路径可能不同（例如 `/api/plate_list`、`/v1/plate_list` 等）。若路径不正确：
- `fetch()` 返回 404 → `.catch(() => {})` 静默吞异常
- 无任何错误日志、无告警
- `plate_concept`/`plate_area` 永远为 `null`

**影响：** 板块数据（概念/地域）随时序或 URL 不匹配而永久缺失，用户无声感知。

**修复建议：**

方案 A（推荐 — 将 seed 逻辑移入 `CDPPage`，消除时序依赖）：

```python
# 在 CDPPage.__init__ 或 _connect 后添加：
def _seed_plates(self):
    """Auto-fetch concept/area plate data after page load."""
    for ptype in ('concept', 'area'):
        url = f'/web_quote/plate/plate_list?type={ptype}&way=change&page=1&rever=1'
        self._re_fetch_api(url)
```

在 `init_cdp()` 中不用 `time.sleep`：

```python
hotplate = cdp_engine.add_page('cls_hotplate', 'https://www.cls.cn/hotplate')
```

方案 B（最小修复 — 增加重试 + 日志）：

```python
hotplate = cdp_engine.add_page('cls_hotplate', 'https://www.cls.cn/hotplate')
if hotplate:
    for _ptype in ('concept', 'area'):
        _url = f'/web_quote/plate/plate_list?type={_ptype}&way=change&page=1&rever=1'
        for retry in range(3):
            try:
                hotplate._re_fetch_api(_url)
                time.sleep(1)  # gentle spacing between fetches
                break
            except Exception as e:
                if retry == 2:
                    print(f'[CDP] WARNING: Failed to seed {_ptype} plate: {e}')
                time.sleep(1)
```

方案 C（验证 URL — 如果 CLS API 已知有其他路径，修正之）：

实际审查已部署的 CLS hotplate 页面，确认正确的 API URL。若 `/web_quote/plate/plate_list` 不正确，应替换为正确路径。

---

#### 🔴 #H2 [P1] Seed 逻辑异常被完全静默吞没

**位置：** `server.py:1030-1032`

```python
try:
    hotplate._re_fetch_api(_url)
except Exception:
    pass
```

**描述：**
`_re_fetch_api` 内部已包含 `try/except Exception: pass`（cdp_engine.py 第 448 行）。外部 `init_cdp()` 又包了一层同样的静默吞异常。**双重静默**意味着任何失败（CDP 连接断开、浏览器错误、URL 错误）都不会产生任何日志或告警。

**对比：** 同一文件中 `add_page()` 的失败会打印 `✗ Failed to create page`（第 829 行），而 seed 失败完全无声。

**影响：** 运维人员无法得知板块数据为何缺失。

**修复建议：** 至少打印一条警告：

```python
try:
    hotplate._re_fetch_api(_url)
except Exception as e:
    print(f'[CDP] WARNING: Failed to seed plate data ({_ptype}): {e}')
```

---

### 维度 5：可维护性

---

#### ⚠️ #H3 [P2] 外部模块调用私有方法 `_re_fetch_api`

**位置：** `server.py:1030`

```python
hotplate._re_fetch_api(_url)
```

**描述：**
`_re_fetch_api` 是 `CDPPage` 类的一个私有方法（单下划线前缀），设计意图是仅由 `_heartbeat`（第 527 行）等内部调用。`server.py` 的 `init_cdp()` 从外部直接调用它，违反了封装原则。

**影响：** 若 `_re_fetch_api` 的签名或行为在未来重构中改变，`init_cdp()` 将静默失败（双重 `try/except`）。

**修复建议：**

最小方案 — 将 `_re_fetch_api` 更名为 `re_fetch_api`（去掉前缀下划线），表示有意公开的方法：

```python
def re_fetch_api(self, url):
    """Fire-and-forget re-fetch of an API URL (public)."""
    ...
```

或更好：将 seed 逻辑移入 `CDPPage` 的公共方法中（如 `#H1` 方案 A）。

---

#### ⚠️ #H4 [P2] 新增 plate keys 未在 `KEY_TTL_OVERRIDES` 中注册

**位置：** `cdp_engine.py:290-300`

```python
KEY_TTL_OVERRIDES = {
    'market_sentiment': 60,
    ...
    'hot_plate': 60,
    'stock_ranking': 60,
    '__ws__': 30,
}
```

**描述：**
`plate_industry`、`plate_concept`、`plate_area` 三个新增 key 未出现在 `KEY_TTL_OVERRIDES` 字典中，因此它们使用默认的 `KEY_TTL = 120` 秒 TTL。板块数据通常变化频率低于行情数据（15-30 分钟级别），120 秒 TTL 偏短，会导致：
- 不必要的主动 re-fetch 频率（每 25 秒触发一次）
- 缓存空间的浪费

**修复建议：** 添加更长的 TTL：

```python
KEY_TTL_OVERRIDES = {
    ...
    'hot_plate': 60,
    'plate_industry': 300,   # 5 min — plate data changes slowly
    'plate_concept': 300,
    'plate_area': 300,
    'stock_ranking': 60,
    ...
}
```

---

### 维度 1：编码规范

---

#### ⚠️ #H5 [P2] 测试覆盖不足

**位置：** `tests/test_server.py:131-147`

**描述：**
新增的 3 个测试覆盖了：
- `_HOTPLATE_EXPECTED_KEYS` 常量内容（✓）
- 无 CDP 时的错误返回（✓）
- health 端点包含 hotplate（✓）

但缺少以下测试：

1. **`_fill_missing` 与 `_HOTPLATE_EXPECTED_KEYS` 的交互：** 无测试验证当部分数据缺失时，`_fill_missing` 能正确填写 null 并保留额外字段。

2. **`remap_keys` 对 plate URL 模式的匹配：** 无测试验证 `'plate_list?type=concept'` 等模式能否正确地从 sample URL 映射到对应的 key。

**修复建议：** 添加以下测试：

```python
def test_fill_missing_with_hotplate_keys(self):
    """_fill_missing should set null for missing hotplate keys."""
    result = {}
    data = {'plate_industry': [{'name': '金融'}]}
    server._fill_missing(result, data, server._HOTPLATE_EXPECTED_KEYS)
    self.assertEqual(result['plate_industry'], [{'name': '金融'}])
    self.assertIsNone(result['plate_concept'])
    self.assertIsNone(result['plate_area'])

def test_remap_keys_matches_plate_list_patterns(self):
    """plate_list?type=* URL patterns should map to correct keys."""
    from cdp_engine import remap_keys
    data = {
        'https://cls.cn/plate_list?type=industry': 'industry_data',
        'https://cls.cn/plate_list?type=concept': 'concept_data',
        'https://cls.cn/plate_list?type=area': 'area_data',
    }
    mapped = remap_keys(data)
    self.assertEqual(mapped.get('plate_industry'), 'industry_data')
    self.assertEqual(mapped.get('plate_concept'), 'concept_data')
    self.assertEqual(mapped.get('plate_area'), 'area_data')
```

---

## 五、数据流完整性审查

### 数据路径追踪

```
CLS 页面 (https://www.cls.cn/hotplate)
  │
  ├─ 默认加载: fetch("...plate_list?type=industry...")
  │     ↓ INTERCEPTOR_JS 捕获
  │     → window.__cdp_api[url] = JSON.parse(text)
  │     ↓ heartbeat (每10s)
  │     → remap_keys() → key: 'plate_industry'
  │     → cache['plate_industry'] / _last_data['plate_industry']
  │     → _api_urls['plate_industry'] = url
  │     → _key_last_seen['plate_industry'] = now
  │     ↓ re-fetch (25s后)
  │     → _re_fetch_api(_api_urls['plate_industry'])
  │
  ├─ seed fetch (3s延迟): hotplate._re_fetch_api("...plate_list?type=concept...")
  │     → window.__cdp_refetch[url] = d
  │     ↓ heartbeat
  │     → remap_keys() → key: 'plate_concept'  (如果 URL 匹配 "plate_list?type=concept")
  │     → cache['plate_concept'] / _last_data['plate_concept']
  │
  ├─ seed fetch (3s延迟): hotplate._re_fetch_api("...plate_list?type=area...")
  │     → 同上 → key: 'plate_area'
  │
  └─ HTTP handler: handle_cls_hotplate()
        → page.get_data() → _last_data + cache merge
        → _fill_missing(result, data, _HOTPLATE_EXPECTED_KEYS)
        → JSON response
```

**数据流评估：**

| 环节 | 状态 | 风险 |
|------|------|------|
| `_shouldCapture` 拦截 | ✅ `plate_list` 包含在拦截条件中 | — |
| `API_KEY_MAP` → `remap_keys` | ⚠️ 依赖 query 参数顺序 | 若 `type` 不是第一个 query 参数则模式不匹配 |
| Interceptor → `__cdp_api` / `__cdp_refetch` | ✅ 双缓冲设计 | — |
| heartbeat 收集 | ✅ 双缓冲都读取并清理 | — |
| `KEY_TTL` 过期 | ⚠️ 120s 默认 TTL 偏短 | 见 #H4 |
| 主动 re-fetch (25s) | ⚠️ plate 数据不在 `_PAGE_REFRESHED_KEYS` 中 | 会主动 re-fetch（合理） |
| Cache → `get_data()` | ✅ `_last_data` + `cache` 合并 | — |
| `_fill_missing` → response | ✅ null 填充正确 | 见 #H5 |
| `/cls/hotplate` route | ✅ 200 + JSON + Cache-Control | — |

### 竞态条件分析

| 场景 | 影响 | 概率 |
|------|------|------|
| Seed 时 WS 被 heartbeat 重建 | 种子数据丢失，且无法自动恢复 | 低（需在 3s 内触发 reconnect） |
| Seed fetch 先于页面 cookie 就绪 | fetch 失败（401/403），种子丢失 | 中（取决于 CLS 认证速度） |
| heartbeat 和 `_re_fetch_api` 同时发 CDP 命令 | WS 消息交错，但 `_next_id()` 保证响应匹配 | 低（安全设计） |
| 多个 `/cls/hotplate` 请求同时到达 | `ThreadingHTTPServer` + thread pool，读取只读缓存 | 无（缓存为只读路径） |

---

## 六、修复建议优先级

| 优先级 | 问题 ID | 修复难度 | 影响范围 |
|--------|---------|----------|----------|
| **P0** | 无 | — | — |
| **最高** | **#H1** | ~15 行 | **板块概念/地域数据可能永久缺失** |
| **高** | **#H2** | ~5 行 | **Seed 失败静默无告警** |
| 中 | #H3 | ~5 行（改名） | 可维护性 |
| 低 | #H4 | ~3 行（添加 TTL） | 性能 / 缓存效率 |
| 低 | #H5 | ~20 行 | 可测试性 |

---

## 七、评审结论

```
╔═══════════════════════════════════════════╗
║  ⚠️  有条件通过                           ║
║                                           ║
║  P0: 0  |  P1: 2  |  P2: 3               ║
║                                           ║
║  建议修复 P1 问题后进入测试阶段。          ║
║  重点关注 #H1（seed 时序 + URL 正确性）   ║
║  和 #H2（失败静默问题）。                  ║
╚═══════════════════════════════════════════╝
```

**总体评价：**

新增的 CLS hotplate 功能整体设计合理，复用了已有的 CDP 引擎架构（interceptor → API_KEY_MAP → cache → handler），数据流清晰。

**亮点：**
- 代码风格与现有代码一致，遵循了已建立的处理模式（`handle_*` 函数签名、`_fill_missing` 模式、CDP 页面管理）
- 双缓冲设计（`__cdp_api` + `__cdp_refetch`）确保数据不丢失
- 测试覆盖了基本的常量验证、无 CDP 时的错误处理和 health 端点

**主要风险：**
1. **seed 逻辑脆弱**（#H1）：`time.sleep(3)` + 硬编码 URL 是当前最紧要的风险。在慢网络或页面变化时，概念/地域板块数据永久缺失。
2. **静默吞异常**（#H2）：双重 `try/except Exception: pass` 让运维完全无感知。
3. **私有方法外部调用**（#H3）：违反封装，增加重构风险。

**建议修复顺序：** #H1 → #H2 → #H3 → #H4 → #H5

---

## 变更记录

| 版本 | 日期 | 变更内容 |
|------|------|----------|
| v1.0 | 2026-07-06 | CLS Hotplate 功能新增评审 |
