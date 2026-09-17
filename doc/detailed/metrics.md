# metrics.py 详细设计（新增模块）

> **版本** v1.3 · **状态** 已契约同步（P7b 传输层批次：以 `china_finance_rss/metrics.py` + `stream.py` 计数点实现为准）· **日期** 2026-09-17 · **作者/产出** task-decomposer
> **v1.3 变更（以代码为准）**：① `upstream_fetch_total{domain}` 的 domain 集合**新增 `depth`**（`config.DOMAIN_MATRIX` 现 12 域，§3.2）；② 补记 **`stream_tick_degraded_total` / `stream_tick_slip_total` 的"进程首个真正刷新轮豁免"**（实现落点在 `stream._push_once`；仅一轮、次轮起照常计数、**空池轮不消耗豁免**，§3.2/§4 BR-MET-13/§8 MET-T17）。**`metrics.py` 本身零代码变更**（注册表 19 名与 `_DEFAULTS` 不变）。
> **v1.2 变更（P7b 契约同步，**只改文档、不改代码**）**：① `snapshot()` 改为**锁内浅拷贝 + 锁外深拷贝**（dict `v.copy()`、list `list(v)`）；② **零值恒定发布**（`_DEFAULTS` 兜底，19 键在 `snapshot()` 中恒出现）；③ `set_gauge` 新增 **`_LABELED_GAUGES` 形状守卫**（与 `incr` 对称）。
> 沿用 v1.1：REV-DES-02（`cache_hit_ratio` 公式/命名）/04（依赖图）/05（`_warned` 锁口径）/07（元数据）+ 逆向建议 3（MET-T8 注册表子集断言）+ 编排层裁决 #4/#5 + 偏差 D-6 登记
> 模块路径 `china_finance_rss/metrics.py` · 归属 **基础层（Layer 0 叶子，零业务依赖）**
> 上游 SAD `doc/arch/SAD.md` v1.2（§2.6 / §2.2 R-4 / §4.2 / ADR-010）
> 上游 PRD v0.3（AC-S10 主；承载 E5/E7/S3/S4/S5/S6/S8/S9 的观测项）
> 端锁定 🟠 STABLE（纯新增模块；`/healthz` 仅**新增** `metrics` 字段）

## 1. 模块职责与边界

### 1.1 职责

1. 进程内**计数/仪表**的中心化登记与快照：`incr` / `set_gauge` / `snapshot`。
2. 为 `/healthz` 提供 `metrics` 字段（`build_health_payload` 调 `snapshot()`）。
3. 让"资源总账"（SAD R-4）与"tick 耗时/丢弃帧/上游失败/冷却清单/CDP 重启窗口"可查询（AC-S10），**仅用标准库**。

### 1.2 明确不做

- **零业务依赖**：不 import 任何 `china_finance_rss` 模块；不读缓存、不发网络、不读文件。
- 不做聚合 / 告警 / 持久化（无外部存储）；不做 Prometheus 文本导出（不引 `prometheus_client`）。
- 不做采样 / 定时（无后台线程）——所有写入由业务点主动调用。
- 不持有业务锁，也不被业务锁的语义依赖。

### 1.3 layerIsolation 约束（tech-stack.json 原文）

```
pattern: china_finance_rss/metrics.py
forbiddenImports: cache, server, stream, stock_api, market_api, cdp_engine
reason: metrics 必须是零业务依赖的叶子模块
```

**允许 import**：标准库仅 `threading`、`logging`。
**依赖方向**（**REV-DES-04 澄清**：图中 `←` 表「分层顺序」，**非 import 关系**）：`metrics` 是**独立叶子**——**不 import config**，也不 import 任何 `china_finance_rss` 模块；`cache`/`stream`/`server`/`stock_api`/`market_api`/`cdp_engine` 单向 `from . import metrics`（观测写入），反向**禁止**（layerIsolation 已 deny）。`config` 与 `metrics` 均为 Layer 0 叶子、**互不依赖**（原图 `config ← metrics` 的箭头仅表分层先后，不表 metrics 依赖 config）。

---

## 2. 接口契约

```python
def incr(name: str, n: int = 1, key: str | None = None) -> None
def set_gauge(name: str, value, key: str | None = None) -> None
def snapshot() -> dict
def reset() -> None          # 测试辅助
```

| 函数 | 参数 | 语义 | 返回 |
|------|------|------|------|
| `incr` | `name` 指标名；`n` 增量（int）；`key` 可选标签 | 计数器累加：`_counters[name] += n`；`key` 非空 → 标签化累加 `_counters[name][key] += n` | `None` |
| `set_gauge` | `name`；`value` 任意 JSON 值；`key` 可选标签 | 仪表赋值：无 `key` → 整体覆盖 `_gauges[name] = value`；有 `key` → 写入字典型仪表的单个标签（其余标签保留）。**P7b：两侧都有形状守卫**（§4 BR-MET-12） | `None` |
| `snapshot` | — | 返回**深拷贝**的 `{name: value}`（counter 与 gauge 合并）；**P7b：锁内只做浅拷贝，深拷贝在锁外**，且**每个注册名都出现**（`_DEFAULTS` 兜底零值） | `dict` |
| `reset` | — | 清空全部计数器与仪表（**仅供测试**） | `None` |

**契约要点**
- **绝不抛异常**（度量不得中断业务）：非法 `n`、标签用法不一致、未注册名 → `log.warning` + fail-safe（§6）。
- `name` 必须 `str`；`key` 必须 `str | None`。非 `str` name → warning + 忽略。
- `snapshot()` 为**总函数**且 **`json.dumps` 可序列化**（AC-S10 经 `/healthz` 输出）；**键集合 ⊇ `_KNOWN`**（19 名恒出现，P7b）。
- 线程安全：内部单锁；`snapshot()` **锁内仅浅拷贝**（P7b），深拷贝在锁外执行。
---

## 3. 数据结构

### 3.1 内部状态（yaml）

```yaml
_counters: # dict[str -> int | dict[str,int]]
  http_503_total: 12                                             # 无标签计数器 → int
  upstream_fail_total: {upstream_timeout: 3, upstream_error: 7}  # 标签化 → dict
_gauges:   # dict[str -> Any(JSON-serializable)]
  stream_queue_bytes: 1048576                                    # 标量仪表
  cache_entries: {url: 812, feed: 40}                            # 字典型仪表（key= 逐标签写入）
  code_cooldown_list: [[quote, sh600519, 1760000000.0]]          # 数组仪表
_lock: threading.Lock                                            # 单锁保护二者
_warned: set[str]                                                # 告警去重（未注册名/label 混用）

_KNOWN: frozenset[str]                     # §3.2 冻结注册表（19 名），仅供告警
_DEFAULTS: dict[str, Any]                  # ★ P7b：每个注册名的零/空值兜底（19 键）
                                           #   assert set(_DEFAULTS) == _KNOWN（导入期自检）
_LABELED_GAUGES: frozenset[str]            # ★ P7b：值为 label→number 映射的 gauge 白名单
                                           #   当前 = {'cache_entries'}；assert ⊆ _KNOWN
                                           #   理由：gauge 值本身可以是 dict（cdp_restart_window），
                                           #   故不能用运行时类型测试判断"是否标签化"，须显式登记
```

### 3.2 指标名称注册表（**冻结，唯一合法名集合**）

| 指标名 | 类型 | 标签(`key=`) | 写入者（owner） | 对应 |
|--------|------|-------------|----------------|------|
| `http_503_total` | counter | — | `server.BoundedThreadPoolServer._reject_503` | S10/S5 |
| `stream_frame_dropped_total` | counter | — | `stream._broadcast` | S10/E7 |
| `stream_queue_bytes` | gauge | — | `stream._broadcast`（distinct 帧计费） | S10/E7 |
| `stream_frame_distinct` | gauge | — | `stream._broadcast` | S10/E7 |
| `stream_frame_peak_bytes` | gauge | — | `stream._broadcast` | S10/E7 |
| `stream_tick_duration_ms` | gauge | — | `stream.push_loop` | S10/E5 |
| `stream_tick_slip_total` | counter | — | `stream.push_loop`（`_push_once`） | S10/R8 |
| `stream_refresh_lag_ticks` | gauge | — | `stream.push_loop`（分片轮转） | S10/AR-1 |
| `stream_tick_degraded_total` | counter | — | `stream.push_loop`（`_push_once`） | S10/AR-1 |
| `stream_slow_client_total` | counter | — | `stream._serve_sse` 摘除路径 | S10/C-3 |
| `cache_entries` | gauge(dict) | `url`/`feed`/`quote`/`fundflow`/`timeline`/`f10`/`announcement`/`longhu`/`sector` | 各缓存写入点 | S10/E6 |
| `cache_hit_ratio` | gauge(float) | — | `cache._cache_put`（由本地 `_cache_stats` 派生） | Q1 观测项（**非 AC**） |
| `negative_cache_size` | gauge(int) | — | `cache._record_failure`/`_clear_negative` | S10/S3 |
| `upstream_fail_total` | counter | `upstream_timeout`/`upstream_error`/`cdp_unavailable` | `cache.fetch_json` / `stock_api` | S10/S3 |
| `upstream_fetch_total` | counter | 域名（`quote`/`depth`/`fundflow`/`timeline`/`plate`/`feed`/`announcement`/`longhu`/`margin`/`f10`/`sector`/`news_url`） | 各域取数点 | AR-6/Q3⑤ |
| `code_cooldown_list` | gauge(list) | — | `stock_api`（共享失败状态层导出） | S10/S6 |
| `cdp_restart_window` | gauge(dict) | — | `cdp_engine`：`{state, window_start, window_end}` | S10/S4 |
| `healthz_stale_total` | counter | — | `server.build_health_payload`（准入失败） | S8/S10 |
| `healthz_inflight` | gauge(int) | — | `server.build_health_payload` | S8/S10 |

> `cdp_restart_window.state ∈ {'idle','restarting','unavailable'}`；`code_cooldown_list` 元素形状 `[domain, code, cooldown_until]`（SAD §2.3 D-6）。
> **首个刷新轮豁免（v1.3）**：`stream_tick_degraded_total`（`duration > _TICK_BUDGET_FRACTION × tick`）与 `stream_tick_slip_total`（`duration >= tick`）由 `stream._push_once` 计数；**进程的第一个"真正刷新轮"豁免**（`cold_first = not _first_refresh_done`）——该轮付的是一次性冷路径成本（空连接池 / 空 DNS 缓存 / sector 冷缓存），属启动代价而非退化。**仅一轮**：`_first_refresh_done` 置真后次轮起照常计数（真实退化永不被掩盖）；**空池轮不消耗豁免**（`codes` 为空的分支不进入计数/豁免逻辑，`stream_refresh_lag_ticks` 复位 0）。
> **零值恒定发布（P7b）**：`snapshot()` 对 `_KNOWN` 中**每一个**名字都输出一个值——`_counters`/`_gauges` 里没有的键回落到 `_DEFAULTS`（`0` / `{}` / `0.0` / `[]`）。监控据此区分"从未发生"与"从未埋点"（BUG-P6C-04）。`_DEFAULTS` 是**只读兜底元数据**，**从不写入** `_counters`/`_gauges` ⇒ 某指标的首次 `incr` 仍由自己确定形状（int vs 标签 dict，BR-MET-1）。
> **`cache_hit_ratio` 口径（REV-DES-02）**：`cache_hit_ratio = round(hit / (hit + miss), 4)`，分母 0 → `0.0`；`hit`/`miss` 为 `cache._cache_stats{hit,miss}` **本地计数**（受 `_cache_lock` 保护，段 1 自增），**不作为独立指标名注册**——全仓**不存在** `cache_hit_total`/`cache_miss_total`。唯一发布点 = `cache._cache_put`（写路径），命中路径零额外加锁。
> 注册表**不新增名称**（SAD 契约冻结）；本表之外的写入会被 warning（BR-MET-3）。**冻结的运行时强制**：BR-MET-3 仅告警（不阻断业务），"键 ⊆ 注册表"由 **MET-T8(b) 集成断言**在 CI 层强制（见 §8/§10#6）。

---

## 4. 业务规则

| 编号 | 规则 |
|------|------|
| **BR-MET-1** | 计数器**单调**语义：`incr` 只累加；同 name 首次写入决定其为"无标签 int"或"标签 dict"。 |
| **BR-MET-2** | **标签使用一致性**：同一 `name` 必须始终带 `key` 或始终不带。不一致 → `log.warning` 一次并**忽略本次调用**（fail-safe，不污染快照）。 |
| **BR-MET-3** | **名称注册表冻结**（§3.2）。未注册名：`log.warning`（每 name **至多一次**）后**仍写入**（不阻断业务）。 |
| **BR-MET-4** | `set_gauge` 有 `key` 时，若已有值为非 dict（或不存在）→ 建为该 name 的 dict 再写入；已有其它 key **保留**（支持多模块逐域写 `cache_entries`）。 |
| **BR-MET-5** | `snapshot()` 返回**深拷贝**副本：改返回值不影响内部状态；容器值递归克隆，标量原样。 |
| **BR-MET-6** | `snapshot()` 结果必须 `json.dumps` 可序列化：`tuple`/`set` 归一为 `list`；键恒为 `str`；不含 `None` 键。 |
| **BR-MET-7** | `snapshot()` 为总函数：任意内部状态都返回 dict（空 → `{}`）。counter 与 gauge 同名时 gauge 覆盖（注册表保证不冲突）。 |
| **BR-MET-8** | `n` 必须为 `int`（`bool` 除外）；否则 warning + 忽略。`value` 任意 JSON 值。 |
| **BR-MET-9** | `reset()` 仅测试使用；生产路径不得调用。 |

**并发计数精度依据**：`incr` 的"读-改-写"完全在 `_lock` 内 ⇒ 100 线程 × 1000 次累加结果精确等于 100000（MET-T6 可白盒断言）。

| 编号 | 规则（P7b 新增） |
|------|------|
| **BR-MET-10** | **`snapshot()` 两段式拷贝**：`_lock` 内只做**浅拷贝**——dict 用 `v.copy()`（**list 用 `list(v)`**），标量原样；深拷贝（`_clone`）在**锁外**执行。⇒ `/healthz` 轮询不会为一次完整深拷贝而长时间阻塞业务写入。**锁内必须同时浅拷贝 list**：否则锁外克隆会迭代一个仍在被业务原地修改的 list（`list changed size during iteration` / 值撕裂）。 |
| **BR-MET-11** | **零值恒定发布**：`snapshot()` 结果包含 `_KNOWN` 全部 19 名；缺失者取 `_DEFAULTS[name]` 的克隆。已写入的值**恒优先**（兜底只补缺，不覆盖）。`assert set(_DEFAULTS) == _KNOWN` 在导入期保证"注册表 ↔ 零值表"永不脱节。 |
| **BR-MET-12** | **`set_gauge` 形状守卫（与 `incr` 对称）**：① 无 `key` 写**标签化 gauge**（∈ `_LABELED_GAUGES`）且当前值已是 dict ⇒ `log.warning` + **忽略**（禁止整体覆盖）；② 有 `key` 写**非标签化 gauge** ⇒ `log.warning` + **忽略**（禁止无标签 gauge 悄悄长出标签 dict）；③ 有 `key` 且已有值为非 dict/不存在 ⇒ 建为该 name 的 dict 再写入（BR-MET-4）。非标签化 gauge 的**值与 dict 合法**（如 `cdp_restart_window`），故不能用运行时类型测试代替白名单。 |
| **BR-MET-13** | **首个真正刷新轮豁免（v1.3，落点 `stream._push_once`）**：`stream_tick_degraded_total` / `stream_tick_slip_total` 对**进程第一个 `codes` 非空轮**不计数（`cold_first`），此后照常；**空池轮（`codes` 为空）既不计数也不消耗豁免**（`_first_refresh_done` 只在非空轮置真）。⇒ 冷启动的一次性成本不被误报为退化，而真实退化（次轮起的超预算/滑 tick）仍被观测。 |
---

## 5. 伪代码

```python
"""Zero-dependency in-process metrics registry (leaf module)."""
import logging
import threading

log = logging.getLogger('metrics')

_counters = {}
_gauges = {}
_lock = threading.Lock()
_warned = set()               # 告警去重；有意不加锁（容忍竞态，REV-DES-05）

# §3.2 注册表（仅供告警，不参与写入判定）
_KNOWN = frozenset({
    'http_503_total', 'stream_frame_dropped_total', 'stream_queue_bytes',
    'stream_frame_distinct', 'stream_frame_peak_bytes', 'stream_tick_duration_ms',
    'stream_tick_slip_total', 'stream_refresh_lag_ticks', 'stream_tick_degraded_total',
    'stream_slow_client_total', 'cache_entries', 'cache_hit_ratio',
    'negative_cache_size', 'upstream_fail_total', 'upstream_fetch_total',
    'code_cooldown_list', 'cdp_restart_window', 'healthz_stale_total', 'healthz_inflight',
})

# ★ P7b BR-MET-11：每个注册名的零/空值兜底（只读元数据，从不写入 _counters/_gauges）
_DEFAULTS = {
    'http_503_total': 0, 'stream_frame_dropped_total': 0, 'stream_queue_bytes': 0,
    'stream_frame_distinct': 0, 'stream_frame_peak_bytes': 0, 'stream_tick_duration_ms': 0,
    'stream_tick_slip_total': 0, 'stream_refresh_lag_ticks': 0,
    'stream_tick_degraded_total': 0, 'stream_slow_client_total': 0,
    'cache_entries': {}, 'cache_hit_ratio': 0.0, 'negative_cache_size': 0,
    'upstream_fail_total': {}, 'upstream_fetch_total': {}, 'code_cooldown_list': [],
    'cdp_restart_window': {}, 'healthz_stale_total': 0, 'healthz_inflight': 0,
}
assert set(_DEFAULTS) == _KNOWN                     # 注册表 ↔ 零值表恒定脱节即启动失败

# ★ P7b BR-MET-12：标签化 gauge 白名单（gauge 值本身可为 dict ⇒ 不能靠运行时类型判断）
_LABELED_GAUGES = frozenset({'cache_entries'})
assert _LABELED_GAUGES <= _KNOWN


def _warn_once(msg):
    if msg not in _warned:
        _warned.add(msg)
        log.warning('[metrics] %s', msg)


def incr(name, n=1, key=None):
    if not isinstance(name, str):                                # BR-MET-8
        _warn_once(f'non-str metric name {name!r} ignored'); return
    if not isinstance(n, int) or isinstance(n, bool):
        _warn_once(f'non-int increment {n!r} for {name} ignored'); return
    if name not in _KNOWN:
        _warn_once(f'unregistered metric name {name!r}')          # BR-MET-3
    with _lock:
        if key is None:
            cur = _counters.get(name)
            if isinstance(cur, dict):                             # BR-MET-2
                _warn_once(f'counter {name}: unlabeled/labeled mismatch'); return
            _counters[name] = (cur or 0) + n
        else:
            cur = _counters.get(name)
            if cur is None:
                _counters[name] = {key: n}
            elif isinstance(cur, dict):
                cur[key] = cur.get(key, 0) + n
            else:                                                 # BR-MET-2
                _warn_once(f'counter {name}: labeled/unlabeled mismatch'); return


def set_gauge(name, value, key=None):
    if not isinstance(name, str):
        _warn_once(f'non-str metric name {name!r} ignored'); return
    if name not in _KNOWN:
        _warn_once(f'unregistered metric name {name!r}')          # BR-MET-3
    with _lock:
        cur = _gauges.get(name)
        if key is None:
            if name in _LABELED_GAUGES and isinstance(cur, dict):  # ★ BR-MET-12①
                _warn_once(f'gauge {name}: unlabeled/labeled mismatch'); return
            _gauges[name] = value
        else:
            if name not in _LABELED_GAUGES:                        # ★ BR-MET-12②
                _warn_once(f'gauge {name}: labeled write to an unlabelled gauge'); return
            if cur is None:
                _gauges[name] = {key: value}
            elif isinstance(cur, dict):
                cur[key] = value
            else:
                _warn_once(f'gauge {name}: labeled/unlabeled mismatch'); return


def _clone(v):                                                    # BR-MET-6（不用 copy 模块）
    if isinstance(v, dict):  return {str(k): _clone(x) for k, x in v.items()}
    if isinstance(v, list):  return [_clone(x) for x in v]
    if isinstance(v, tuple): return [_clone(x) for x in v]
    if isinstance(v, set):   return [_clone(x) for x in v]
    return v


def snapshot():                                                   # BR-MET-5/7/10/11
    # ① 锁内：只做浅拷贝（dict .copy()、list list()），标量原样 —— 临界区最短
    with _lock:
        items = [(k, list(v) if isinstance(v, list)
                  else v.copy() if isinstance(v, dict) else v)
                 for k, v in _counters.items()]
        items += [(k, list(v) if isinstance(v, list)
                   else v.copy() if isinstance(v, dict) else v)
                  for k, v in _gauges.items()]
    # ② 锁外：深拷贝（大 list/dict 的克隆不阻塞业务写入）
    out = {k: _clone(v) for k, v in items}
    # ③ 零值兜底：注册名恒出现，已写入值优先
    for name, default in _DEFAULTS.items():
        if name not in out:
            out[name] = _clone(default)
    return out


def reset():                                                      # BR-MET-9
    with _lock:
        _counters.clear(); _gauges.clear()
    _warned.clear()
```

> **不使用 `copy` 模块**：`copy` 不在 `tech-stack.json` 的 import allowlist 内；`_clone` 用内建容器推导实现（AC-S9 的"标准库零依赖"红线由 allowlist 强制）。
> **P7b 补充**：`snapshot()` 的浅拷贝-深拷贝两段式是**性能契约**（BR-MET-10）——锁内只做 O(n) 指针拷贝（n ≈ 19），深拷贝在锁外。测试 `test_cache.py::test_*_publishes_after_release` 一类"锁持有期间不得发布 metrics"的断言与本节同向。

---

## 6. 错误处理

| 情形 | 行为 |
|------|------|
| `name` 非 `str` | `log.warning` + 忽略本次调用（不抛） |
| `n` 非 `int` / 为 `bool` | `log.warning` + 忽略本次调用（不抛） |
| 同 name 标签用法不一致（counter） | `log.warning`（每 name 一次）+ 忽略本次调用（不抛） |
| **无 `key` 写标签化 gauge（`cache_entries`）且当前已是 dict** | `log.warning` + **忽略本次调用**（不抛；禁止整体覆盖，BR-MET-12①） |
| **有 `key` 写非标签化 gauge** | `log.warning` + **忽略本次调用**（不抛；禁止无标签 gauge 长出标签 dict，BR-MET-12②） |
| 未注册指标名 | `log.warning`（每 name 一次）+ **仍写入**（不阻断业务） |
| `value` 为不可 JSON 序列化对象 | 仍写入，但快照不保证可序列化；**由 owner 保证**传入 number/str/bool/None/list/dict（SAD schema `<number\|object\|array>`） |
| `snapshot()` | 总函数，绝不抛；registry 全空 ⇒ 仍返回 `_KNOWN` 全 19 名的零值（**不是 `{}`**，BR-MET-11） |

**降级路径**：`metrics` 是**观测旁路**——任何 metrics 故障都不得影响业务。故一律 fail-safe：忽略 + warning，绝不 raise。

---

## 7. 并发安全

1. **单 `threading.Lock`** 保护 `_counters`/`_gauges`；临界区仅内存读写（无 IO、无阻塞）→ 竞争窗口纳秒级。
2. **叶子锁**：metrics 锁**永远是最内层**；持锁时**不得**调用任何其它模块（禁止回调 / 网络 / 除 logging 外的 IO）。允许的嵌套方向：`_cache_lock` / `_feed_cache_lock` → `metrics._lock`（cache 写路径），反向禁止。
3. `snapshot()` 的**锁内部分只有浅拷贝**（BR-MET-10）：`_lock` 下做 O(19) 指针拷贝（dict `.copy()` / list `list()`），**深拷贝在锁外** ⇒ 指标数 ≈ 19，`/healthz` 毫秒级（AC-S8 的 zero-upstream 路径），且一次完整深拷贝不会长时间阻塞业务写入。
4. **`_warned` 锁口径（REV-DES-05，择一统一）**：`_warn_once` **就地调用，不强制在锁外**——name 类告警（`incr`/`set_gauge` 入口的 `name not in _KNOWN` / 非 str name）在 `_lock` **外**调用；标签一致性告警（`incr` 的 labeled/unlabeled mismatch 分支、`set_gauge` 的两条形状守卫分支，均位于 `with _lock:` 内）在锁内调用。`_warned` 为无锁 `set`，"检查-添加"非原子，**容忍极小竞态**（极端交错下至多多打一条重复 warning，不影响计数/快照正确性）；**不为此引入第二把锁，也不调整临界区**（叶子锁原则优先）。
5. **形状白名单（BR-MET-12）**：`_LABELED_GAUGES` 是**静态** frozenset（`assert ⊆ _KNOWN`），运行期只读 ⇒ 守卫判定无竞态；`cdp_restart_window` 这类"值为 dict 的非标签化 gauge"不会被误判。
6. 无后台线程、无定时器、无存储 ⇒ 不增加 AC-S9 的线程/内存总账（仅 ~19 个键 + `_DEFAULTS`/`_LABELED_GAUGES` 两张静态表，恒定）。

---

## 8. 测试要点（映射 AC）

| 用例 | 步骤 / 断言 | 覆盖 AC |
|------|------------|---------|
| **MET-T1** 计数器累加 | `incr('http_503_total')` ×3 + `incr('c', 5)` → `snapshot()['http_503_total'] == 3`、`['c'] == 5` | S10 |
| **MET-T2** 标签化计数器 | `incr('upstream_fail_total', key='upstream_timeout')` ×2、`key='upstream_error'` ×1 → `{'upstream_timeout':2,'upstream_error':1}` | S3/S10 |
| **MET-T3** 仪表覆盖与逐标签合并 | `set_gauge('cache_entries', 5, key='url')`、`set_gauge('cache_entries', 2, key='feed')` → `{'url':5,'feed':2}`（不互相覆盖） | E6/S10 |
| **MET-T4** 快照为深拷贝 | `s = snapshot()`；`s['cache_entries']['url'] = 999` → 再次 `snapshot()` 仍为原值 | S10 |
| **MET-T5** 快照可 JSON 序列化 | 写入 dict/list/tuple/set 值 → `json.dumps(snapshot())` 不抛；tuple/set 变为 list | S10 |
| **MET-T6** 并发精确性 | 100 线程 × 1000 次 `incr('c')` → `snapshot()['c'] == 100000` | S10/S2 |
| **MET-T7** label 混用 fail-safe | 先 `incr('m')` 再 `incr('m', key='k')` → 均不抛；首次计数保留、第二次被忽略；有 warning | S10 |
| **MET-T8** 未注册名 / 注册表子集（逆向审查 3） | **(a) 单元**：`incr('typo_metric')` → 不抛、被写入、有 warning（仅一次）；**(b) 集成（CI 强制）**：完整跑一轮业务（或全量测试套件）后 `set(snapshot()) ⊆ _KNOWN`（§3.2 注册表）——任何越界键即拼写/漏注册缺陷，测试红灯 | S10 / 逆向审查 3 |
| **MET-T9** 非 int 增量 | `incr('c', 'x')` / `incr('c', True)` → 不抛、忽略、计数不变 | S10 |
| **MET-T10** 注册表齐全 | 完整运行后 `snapshot()` 可含 §3.2 全部名；`/healthz` 的 `metrics` 字段非空 | S10 |
| **MET-T11** reset | `reset()` 后 `snapshot()` **仍含全部 19 名且为零值**（P7b：不再是 `{}`） | 测试隔离 / BR-MET-11 |
| **MET-T12** `cache_hit_ratio` 命名唯一（REV-DES-02） | 全仓 grep 确认**无** `cache_hit_total`/`cache_miss_total`；`set_gauge('cache_hit_ratio', x)` 后快照键为 `cache_hit_ratio` | Q1 观测项 |
| **MET-T13** 零值恒定发布（P7b） | 全新进程未写任何指标 ⇒ `set(snapshot()) == _KNOWN` 且每一值等于 `_DEFAULTS[name]`；写过 `incr('http_503_total', 3)` 后该键为 `3`（**已写值优先**） | BR-MET-11 / S10 |
| **MET-T14** 快照锁内浅拷贝（P7b） | 持 `_lock` 期间 `snapshot()` 返回；另起线程对 `_gauges` 里的 list 值**原地 append** ⇒ 克隆不抛 `changed size during iteration`、结果自洽（浅拷贝快照为"某时刻的成员集"） | BR-MET-10 |
| **MET-T15** gauge 形状守卫（P7b） | ① `set_gauge('cache_entries', 5)`（无 key，`_LABELED_GAUGES` 且已 dict）⇒ 忽略 + warning，已有标签保留；② `set_gauge('code_cooldown_list', 1, key='x')` ⇒ 忽略 + warning，值不变；③ `set_gauge('cdp_restart_window', {...})`（无 key 的 dict 值）**合法**，不被守卫拦 | BR-MET-12 |
| **MET-T16** 静态表自检（P7b） | `set(_DEFAULTS) == _KNOWN`；`_LABELED_GAUGES <= _KNOWN`；导入即断言（脱节 ⇒ 启动失败） | BR-MET-11/12 |
| **MET-T17** `upstream_fetch_total{depth}` 与首轮豁免（v1.3） | ① `stock_api.fetch_cls_stock_depth` 成功 ⇒ `snapshot()['upstream_fetch_total']['depth'] >= 1`；`set(snapshot()) ⊆ _KNOWN` 仍成立（MET-T8b）。② `stream._push_once` 首个 `codes` 非空轮即使 `duration > tick` 也**不**增 `stream_tick_degraded_total`/`stream_tick_slip_total`；**次轮**同样超时则两者各 +1；前置一个空池轮**不消耗**豁免（紧随其后的首个非空轮仍豁免） | AR-6/E2/S10 |

---

## 9. AC 追溯矩阵

| 本模块设计点 | 覆盖 AC |
|-------------|---------|
| `snapshot()` + `/healthz` `metrics` 字段（只增） | **AC-S10** 主承载 |
| `stream_tick_duration_ms` / `stream_tick_slip_total` / `stream_frame_*` | AC-S10 / R8 / **E5/E7** |
| `code_cooldown_list`（可枚举清单） | AC-S10 / **S6** |
| `cdp_restart_window` | AC-S10 / **S4**（R19） |
| `negative_cache_size` / `upstream_fail_total` | AC-S10 / **S3** |
| `http_503_total` | AC-S10 / **S5** |
| `healthz_stale_total` / `healthz_inflight` | AC-S10 / **S8** |
| `cache_entries` | AC-S10 / **E6**（上限可观测） |
| 零依赖叶子 + 无后台线程 + 无存储 | **AC-S9**（24h 资源总账不因观测单调增长） |
| `cache_hit_ratio`（Q1 观测项） | 非 AC（PRD 未列） |
| **零值恒定发布 / 锁内浅拷贝**（BR-MET-10/11） | **AC-S10**（`/healthz` 快照恒含全名、且不被深拷贝阻塞）|
| **gauge 形状守卫**（BR-MET-12） | AC-S10（观测不得破坏业务状态）|
| **`upstream_fetch_total{depth}`（v1.3）** | AR-6 / Q3⑤（上游负载核算覆盖五档盘口域） |
| **首个刷新轮豁免（v1.3 / BR-MET-13）** | AC-S10（冷启动不误报退化；真实退化仍可见）/ **E2** |

---

## 10. 与 SAD 的偏差与歧义标注（不擅自改 SAD）

| # | 项 | SAD 表述 | 本文裁决 | 理由 |
|---|----|---------|---------|------|
| 1 | `cache_entries{url,feed,quote,…}` 的 `{}` 记法 | §2.6 表 | 用 `set_gauge(name, value, key=...)` 实现为**字典型仪表的逐标签写入** | 单 `set_gauge(name,{...})` 整体覆盖会被多模块写点互相清空；逐标签写入是无竞态的最小实现 |
| 2 | `cache_hit_ratio` 来源 | "`_handle_cached_batch` / `fetch_json`" | 由 `cache.py` 本地命中/未命中计数在 `_cache_put` 派生发布（不在请求热路径读回快照） | 命中路径零额外锁；Q1 已定性为观测项非 AC |
| 3 | 接口面 | `incr` / `set_gauge` / `snapshot` | 三者各加可选 `key`（向后兼容）+ `reset()`（测试） | `key` 是偏差 #1 的载体；`reset()` 保证用例隔离 |
| 4 | `copy` 模块 | 未提 | 不用 `copy.deepcopy`，自写 `_clone` | `copy` 不在 tech-stack allowlist ⇒ 会被 `check-arch-compliance.sh` 判违规 |
| 5 | **D-6** `upstream_fetch_total` | §2.6 计分板**未列**该名（仅 §7.2 AR-6 文字提"新增每域 fetch 计数"） | 注册表冻结声明**包含** `upstream_fetch_total{domain}`（`domain` ∈ `DOMAIN_MATRIX` 键） | 建议编排层在 SAD §2.6 补列该名，使"冻结"与注册表一致；SAD 侧由 system-architect 回填 |
| 6 | **逆向审查 3** 注册表冻结的运行时强制 | BR-MET-3"未注册名仍写入 + warning" | 冻结为**文档契约**，运行时**仅告警不阻断**（保业务）；"快照键 ⊆ 注册表"由 **MET-T8(b) 集成断言**在 **CI 层**强制（越界即红灯） | 不阻断业务的前提下闭合"假指标/拼写错误"缺口（AC-S10 要求可观测到**指定**项） |
| 7 | 依赖图箭头语义 | SAD 图 `config ← metrics` | 澄清为**分层顺序非 import**；metrics **不 import config**（§1.3，REV-DES-04） | 消除与"metrics 零业务依赖"的表面矛盾 |
| 8 | `_warned` 锁内外 | SAD 未涉及 | 统一为"`_warn_once` 就地调用，容忍竞态，不引入第二把锁"（§7.4，REV-DES-05） | 描述与 §5 实现一致 |
| 9 | **P7b · `snapshot()` 拷贝分段** | SAD §2.6 只说"返回快照" | 锁内**浅拷贝**（dict `.copy()`、list `list(v)`）、锁外深拷贝（BR-MET-10） | `/healthz` 轮询不得为一次完整深拷贝长阻塞业务写；list 必须同批浅拷贝，否则锁外克隆会迭代活对象 |
| 10 | **P7b · 零值恒定发布** | SAD §2.6 未定义"未发生"与"未埋点"的区分 | `_DEFAULTS` 兜底；`snapshot()` 恒含 19 名；`assert set(_DEFAULTS) == _KNOWN`（BR-MET-11） | 监控需要 `stream_frame_dropped_total == 0` 而非"键缺失"；兜底表**不写入** registry ⇒ 不改变首次 `incr` 定形语义 |
| 11 | **P7b · gauge 形状守卫** | SAD 未定义 gauge 的标签形状规则 | 新增 `_LABELED_GAUGES = {'cache_entries'}` 白名单 + `set_gauge` 两条守卫（BR-MET-12） | gauge 值本身可以是 dict（`cdp_restart_window`）⇒ 不能用运行时类型测试判断"是否标签化"；与 `incr` 的形状守卫对称 |
| 12 | **v1.3 · `upstream_fetch_total{depth}`** | SAD §2.6 记分板按 `DOMAIN_MATRIX` 定域；v1.2 文档 domain 示例未含 `depth` | `depth` 域新增（`config.md` §3.1，v1.4）⇒ 其 `upstream_fetch_total` 标签合法，注册表"全名断言"（MET-T8b）不新增指标名、仅新增标签值 | 注册表**不新增名称**（仍 19 名）；标签值是域名 → 随 `DOMAIN_MATRIX` 演进，不需要新注册 |
| 13 | **v1.3 · 首个刷新轮豁免** | SAD §2.6/§4.2 未定义"冷启动 vs 退化"的区分 | 实现落在 `stream._push_once`（`_first_refresh_done`/`cold_first`），metrics.md 仅登记口径（BR-MET-13） | 冷进程首轮付空池/空 DNS/sector 冷缓存的**一次性**成本；不豁免会把每次冷启动都记成退化，豁免多轮则会掩盖真实退化 ⇒ **仅一轮、空池轮不消耗** |

> **编排层裁决回执（2026-09-15）**：#4 metrics 增 `key=`/`reset()` ✅（向后兼容；`key` 是 `cache_entries{…}`/`upstream_fail_total{kind}` 记法的唯一落地载体，SAD §2.6 将补注）；#5 `cache_hit_ratio` 发布点 ✅（§3.2 已补公式 + 唯一发布点，实现由 `cache.md` §5.2 承接）。

## 11. 交付自检

- [x] 零业务依赖（仅 `threading`/`logging`），符合 `layerIsolation`（依赖图箭头语义已澄清）
- [x] 四函数签名 / 类型 / 默认值 / 返回精确；fail-safe 不抛
- [x] 指标注册表冻结，逐项标注 owner 与 AC；`cache_hit_ratio` 口径与命名统一（REV-DES-02）
- [x] 单锁 + 叶子锁 + 允许嵌套方向明确；`_warned` 锁口径与 §5 实现一致（REV-DES-05）
- [x] `snapshot()` 深拷贝且 JSON 可序列化（不依赖 `copy`）
- [x] 注册表"键 ⊆ `_KNOWN`"有 CI 级断言（MET-T8b，逆向审查 3）
- [x] AC 追溯：S10 主承载，E5/E7/S3/S4/S5/S6/S8/S9 载体齐备
- [x] **v1.2（P7b）**：`snapshot()` 锁内浅拷贝 + 锁外深拷贝（BR-MET-10）、零值恒定发布 19 键（BR-MET-11）、`set_gauge` 的 `_LABELED_GAUGES` 形状守卫（BR-MET-12）——§2/§3.1/§4/§5/§6/§7/§8 MET-T13..T16 全部与实现一致
- [x] **v1.2（P7b）**：`reset()` 后快照**非空**（19 名零值），MET-T11 已据实改写
- [x] **v1.3**：`upstream_fetch_total` domain 补 `depth`（§3.2/T-MET-T17）；首个刷新轮豁免口径（§3.2/BR-MET-13/§8 MET-T17/§9/§10#12·13）；**`metrics.py` 零代码变更**（仍 19 名）


