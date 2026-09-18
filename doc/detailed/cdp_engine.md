# cdp_engine.py 详细设计

> **版本** v1.4 · **状态** 已契约同步（★ v1.4：**溯源收口 + 引用时点约定**——上游 **SAD v1.12 / PRD v0.10**、基础层接口权威 **config v1.6 / metrics v1.8**；**无 BR 语义变更、无对外契约变更**；P7b 传输层批次：以 `china_finance_rss/cdp_engine.py` 实现为准回写）· **日期** 2026-09-18 · **作者/产出** task-decomposer
> **v1.4 变更（溯源收口 + 引用时点约定 · 只改文档，不改代码）**：① **【溯源收口】** 头部上游 **SAD v1.3 → v1.12 / PRD v0.3 → v0.10**；「基础层接口权威」栏 **config v1.1 → v1.6 / metrics v1.1 → v1.8**（均指向**现行版本**；`cache.md` 与本模块无接口、不列版本）。② **【引用时点约定（新增）】**「接口权威」栏所列版本 = **本文最后一次同步时点的快照**；被引文档的**权威版本以其自身头部为准**——故该栏**落后一版不属漂移、无需每次追平**；**内容以被引文档为准，此栏仅用于定位**。**本模块的代码 / 契约形态 / BR / 测试编号 / 偏差零变更**（v1.3 正文逐字保留）；**未改代码 / SAD / PRD / API.md / README.md / `.opencode`；`_PROGRESS.md` 同步。**
> **v1.3 变更（以代码为准）**：① `/proc/{pid}/cmdline` 读取改为 `with open(...)`（**修复每次探测泄漏一个 fd**）——`_chrome_pids_by_flag` 逐 PID 读 cmdline，旧写法在 OOM 循环/高频 watch 下会耗尽进程 fd；② 补记 `_chrome_pids_by_flag`/`_kill_chrome_on_port` 的防御面（`/proc` 不可读、PID 竞态消失、`pkill` 兜底）。**§2/§3/§4 的 P7b 口径（窗口终态保证 / `_last_data_ts` 老化 / 对称淘汰 / 限时导航锁 / `CDP_RESTART_THROTTLE` 源自 config）不变。**
> 本版（v1.2 P7b 契约同步，**只改文档、不改代码**）：① `get_data` 以 `_last_data_ts` 老化（**时钟缺失 = 陈旧**）；`_reconnect` 同时清 `_last_data`/`_last_data_ts`；② `navigate_stock` 快路径与锁后兜底改用带 max-age 的 `_fresh_secu_code_locked`，导航锁 `acquire(timeout)` 限时；③ 新增 `_evict_stalest_last_data_locked`（硬上限淘汰**同步清** `_last_data_ts`/`_key_last_seen`/`_api_urls`）；④ 重启窗口**异常兜底**（`ensure_chrome`/`full_chrome_restart` 必然收口终态）；⑤ `CDP_RESTART_THROTTLE` 改由 config 注册；⑥ **§2.1 A′ 收口**：`fetch_cls_f10` 五出口全部 `cdp_unavailable`（含"有数据但不匹配"），修正 v1.1 `REV-DES-18` 的 `None` 例外。
> 沿用 v1.1：REV-DES-20260915-002（REV-DES-18 / REV-DES-19）
> 模块路径 `china_finance_rss/cdp_engine.py` · 归属 **基础设施（CDP 客户端）· 仅依赖 config/metrics**
> 上游 SAD `doc/arch/SAD.md` **v1.12**（★ v1.4 溯源更正：原误记 v1.3；权威以 SAD 头部为准）（§2.3 D-4 CDP 降级 / §2.4 R18 防御取数 / §2.6 `cdp_restart_window` / §3 cdp_engine 行 / ADR-005/012）
> 上游 PRD `doc/prd/perf-stability-optimization.md` **v0.10**（★ v1.4 溯源更正：原误记 v0.3；权威以 PRD 头部为准）（AC-S1 / AC-S4 / AC-S9 / AC-S10；R18/R19/R20）
> 基础层接口权威 `doc/detailed/config.md` **v1.6** · `metrics.md` **v1.8**（★ v1.4 溯源更正：原误记 config/metrics 均 v1.1；均指向**现行版本**；`cache.md` 与本模块无接口）
> ★ **引用时点约定**：上列「接口权威」版本 = **本文最后一次同步时点的快照**；被引文档的**权威版本以其自身头部为准**——故该栏**落后一版不属漂移、无需每次追平**；**内容以被引文档为准，此栏仅用于定位**。
> 端锁定 🟠 STABLE（纯新增函数与观测字段；`CDPPage`/`CDPEngine` 既有公开方法签名不变）

## 1. 模块职责与边界

### 1.1 职责

1. **防御取数 `page_data(page)`（R18）**：对"页面数据可能为 `None`/非 dict/空"的边界提供**唯一**安全访问点，调用方据此产出 error 客体或 `cdp_unavailable`——**不再有"假定数据为 dict"的 `.pop/.get` 链**。
2. **Chrome 重启窗口状态机（AR-12 / R19）**：`idle / restarting / unavailable` 三态 + 窗口起止，作为唯一权威状态（供 `/healthz` `cdp` 字段与 metrics）。
3. **守护重启策略判断集中化（ADR-012）**：`watchdog_restart_skip_reason()` 把"盘中避让 + 节流 + 已在重启 + CDP 未就绪"四项判断收口在 engine，`server._cdp_memory_watchdog` 只调它 + `full_chrome_restart()`。
4. **交易时段判定单一来源**：`CDPPage._heartbeat_interval()` 删除本地时段复本，改调 `config._is_trading_hours()`。
5. **metrics 集成**：每次窗口状态迁移发布 `metrics.set_gauge('cdp_restart_window', {...})`。
6. **页面服务缓存的老化与对称淘汰（P7b）**：`CDPPage._last_data` 由 `_last_data_ts` 作为**唯一**年龄时钟（`_last_data_max_age=600s`），**时钟缺失一律视为陈旧**；`_evict_stalest_last_data_locked()` 在硬上限淘汰时**对称清理** `_last_data_ts` / `_key_last_seen` / `_api_urls`，避免旁表无界漂移。
7. **重启窗口必然收口（P7b）**：`ensure_chrome()` 与 `full_chrome_restart()` 的所有异常路径都落到 `idle` 或 `unavailable` 终态——**不存在"卡在 `restarting`"**。

### 1.2 明确不做

- **不承载守护线程本体**：`_cdp_memory_watchdog`（含 7200s 周期）**位于 `server.py`**（SAD §3 修 P2-2 已钉死）；本模块只提供**判断原语 + 状态机**。
- **不改变 `full_chrome_restart` 的杀/启机制**：仍 `_kill_chrome_on_port → ensure_chrome`，节流窗口 `_CHROME_RESTART_THROTTLE*2` 保留。
- **不做"CDP 不可用时返回缓存旧值"**：与 R10「过期=拒读」冲突（SAD §2.3 不选其他）；`page_data` 只做空值防御，**不兜旧值**。
- **不新增页面数参数**：页面数仍由 `config.stock_nav_page_names()`（`CDP_STOCK_PAGES`，默认 3）+2 常驻决定，本模块不改（R20 由 SAD §4.3 内存总账 + `server` 承接）。
- **不改 `websocket` 延迟导入策略**（tech-stack `optionalRuntimeDependencies`）。

### 1.3 layerIsolation 约束（tech-stack.json 原文）

```
pattern: china_finance_rss/cdp_engine.py
forbiddenImports: server, stream, stock_api
reason: cdp_engine 只允许依赖 config/metrics，禁止反向依赖调用方
```

**允许 import**：标准库 `gc / json / logging / os / signal / subprocess / threading / time / urllib.request / urllib.parse` + `websocket`（**仅函数内延迟导入**） + 包内 **`config`**、**`metrics`**。
**新增 import（本设计）**：`from . import config`、`from . import metrics`（均在 allowlist 且不构成环：`config`/`metrics` 不 import 任何业务模块）。
> **P7b allowlist 修正**：实现**不使用** `atexit` 与 `datetime`（v1.1 清单曾误列）；实际标准库面即上述 10 个模块。
> **env 注册中心（P7b）**：`CDP_URL` → `config.CDP_URL`；`_CHROME_RESTART_THROTTLE` → `config.CDP_RESTART_THROTTLE`。本模块**不自行 `os.getenv`**（`config.md` BR-CFG-16）。

### 1.4 依赖方向与调用关系（`←` 表分层顺序，非 import 关系）

```
config（无依赖） ‖ metrics（零业务依赖叶子）
        ↑
    cdp_engine  ──(单向写 metrics)──▶ metrics
        ↑
    server（调用面：full_chrome_restart / ensure_chrome / _is_trading_hours 的守护判断）
    server / stock_api（消费面：page_data / CDPEngine.get_page）
```

> 说明：`config.cdp_engine` 全局槽由 `server.init_cdp()` 写入（既有机制，`config.md` §1.4 登记的唯一历史例外）。本模块**读取** `config.cdp_engine` 仅用于 `cdp_ready()` 判断，**不写**该槽。

---

## 2. 接口契约

### 2.1 `page_data(page) -> dict | None`

```python
def page_data(page) -> dict | None:
```

| 参数 | 类型 | 语义 |
|------|------|------|
| `page` | `CDPPage \| None` | 任意页对象；`None` 合法（页面未初始化） |

**返回**：**非空 dict**（`page.get_data()` 的原样返回）或 `None`。**绝不抛异常**。

| 输入状态 | 返回 |
|---------|------|
| `page is None` | `None` |
| `page.get_data()` 抛异常 | `None`（+ `log.warning`） |
| `page.get_data()` 返回非 dict | `None` |
| `page.get_data()` 返回 `{}`（空 dict） | `None`（Chrome 重启窗口内 `_reconnect` 清空缓存后即此态） |
| 其它 | 原样 dict（调用方仍须对**具体键**做空判定，见 2.2） |

**调用契约（写入 `server.md` / `stock_api.md`）**

- **A 类（单体/面板）**：`data = page_data(page); if data is None: return {'error': 'Chrome CDP not available.'}`
- **A 类 timeline 旁支（修 R18）**：`tl = data.get('timeline'); if tl is None: return {'error': 'timeline unavailable'}`——**禁止**返回裸 `null`。
- **A′ 类（`/stock/f10`）**：`fetch_cls_f10` 对**导航成功但 `page_data(page) is None`**（数据被清）的页面 `continue`；**五条失败出口全部** `raise FetchError('cdp_unavailable')`：① engine 未就绪；② 无导航页；③ 预算已耗尽；④ 全部导航失败**或全部已导航页 `page_data=None`**；⑤ **取到 dict 数据但不属于该码**。由 `build_batch_response` 组装为逐码 `null` + `_errors`。
  > ★ **P7b 收口（修正 v1.1 REV-DES-18）**：v1.1 曾规定"仅**有 dict 数据但不匹配**才返回 `None`（无数据）"。实现已把该出口也并入 `cdp_unavailable`——"取到但属于别的股票"在语义上仍是**本轮未取到该码的数据**，静默 `None` 会让 batch 每个 tick 白付整轮导航且无任何错误信号。**`cdp_engine.md` 与 `stock_api.md §5.9/§10#15` 逐字同步**（BR-CDP-18）。
- **允许的链式访问**：拿到 dict 后可安全使用 `dict.pop(key, None)` / `dict.get(key)`；**禁止**对 `page.get_data()` 的返回值**未经 `page_data` 判定**直接 `.pop/.get`。

### 2.2 `restart_window_snapshot() -> dict`

```python
def restart_window_snapshot() -> dict:
```

**返回**（每次新建 dict，供 `/healthz` 的 `cdp` 字段与 metrics 直接使用）：

```python
{'state': 'idle' | 'restarting' | 'unavailable',
 'window_start': float | None,      # epoch 秒；离开 idle 的时刻
 'window_end':   float | None}      # epoch 秒；回到 idle / 判定 unavailable 的时刻；窗口进行中为 None
```

**线程安全**：在 `_restart_window_lock` 内快照拷贝。

### 2.3 `watchdog_restart_skip_reason(now=None) -> str | None`

```python
def watchdog_restart_skip_reason(now: float | None = None) -> str | None:
```

**返回**：`None` = **允许**本轮守护重启；非 `None` = **跳过**，值为原因枚举（供日志）：

| 返回 | 条件（按序短路判定） | 依据 |
|------|--------------------|------|
| `'not_ready'` | `config.cdp_engine` 为 `None` 或 `.ready` 为 False | 现状 watchdog 前置判断上收 |
| `'already_restarting'` | `_restart_window['state'] == 'restarting'` | 防重入（AR-12） |
| `'trading_hours'` | `config._is_trading_hours(now)` 为 True | **ADR-012 盘中避让（本次必做）** |
| `'recent_restart'` | `now - _last_chrome_restart < _CHROME_RESTART_THROTTLE * 2`（= 30s） | 防 back-to-back 杀新 Chrome（现状 `server.py:896` 上收） |
| `None` | 以上均不成立 | 允许重启 |

**消费者（`server._cdp_memory_watchdog` 的目标形态）**

```python
while True:
    time.sleep(CDP_RESTART_INTERVAL)
    reason = watchdog_restart_skip_reason()
    if reason is not None:
        log.info('  [CDP] watchdog: restart skipped (%s)', reason)
        continue
    log.info('  [CDP] watchdog: restarting Chrome to reclaim renderer memory')
    full_chrome_restart()
```

> **顺手延后语义**：`continue` 表示本轮跳过、**顺延到下一周期**（`CDP_RESTART_INTERVAL` 后），**不累积**、不补偿（ADR-012 原文）。

### 2.4 `cdp_ready() -> bool`

```python
def cdp_ready() -> bool:
    """config.cdp_engine 已初始化且 ready（供 watchdog 与降级判定复用）。"""
```

### 2.5 保留不变的既有公开面（兼容清单）

| 名称 | 签名 | 变更 |
|------|------|------|
| `full_chrome_restart(cdp_url=CDP_URL) -> bool` | 不变 | **新增窗口状态迁移 + metrics 发布**；返回值语义不变 |
| `ensure_chrome(cdp_url=CDP_URL) -> bool` | 不变 | **新增成功→idle / 真失败→unavailable 的状态迁移**；节流返回 False 时**不改状态** |
| `CDPEngine.start() / add_page() / get_page() / shutdown()` | 不变 | `start()` 失败时置 `unavailable` |
| `CDPEngine.ready`（property） | 不变 | **语义不变**（是否可达）；重启窗口不覆盖它 |
| `CDPPage.get_data()` | 不变 | 返回 always-dict（既有语义）——防御收敛在 `page_data` |
| `CDPPage._heartbeat_interval()` | 不变 | **改调 `config._is_trading_hours()`**，删除本地时段复本 |
| `_CHROME_RESTART_THROTTLE` | 不变（值） | **P7b 来源变更**：`= config.CDP_RESTART_THROTTLE`（config 注册，本模块不再 `os.getenv`）；`_last_chrome_restart` / `_chrome_restart_lock` 语义不变 |
| `remap_keys` / `find_tab` / `execute_js` / `API_KEY_MAP` / `INTERCEPTOR_JS` | 不变 | — |
| `_same_code(a, b) -> bool` | — | **P7b 新增**：用 `config.canonical_code` 归一后比较（无效码永不匹配） |
| `CDPPage._fresh_secu_code_locked(now)` | — | **P7b 新增**：持 `self._lock` 时返回"未过 `_last_data_max_age` 的 `_last_data['basic_info'].data.secu_code`"，否则 `None`（**时钟缺失 = 陈旧**） |
| `CDPPage._acquire_navigate_lock(timeout) -> bool` | — | **P7b 新增**：`_navigate_lock` 的**限时**获取；超时/t≤0 ⇒ `False`（降级而非无限 park） |
| `CDPPage._evict_stalest_last_data_locked()` | — | **P7b 新增**：按 `_key_last_seen` 淘汰最旧的 `_last_data` 条目，并对称清理 `_last_data_ts`（键已不在 `self.cache` 时再清 `_key_last_seen`/`_api_urls`）；调用方须持 `self._lock` |
| `CDPPage._ingest_payload(api_map, ws_data, now, run_refetch=True)` | — | **P7b 记录**：heartbeat 与 `refresh()` 共用的合并/新鲜度维护实现（含 TTL 清扫、`_last_data` 老化、主动 `re_fetch`）；两者行为因共用而**天然一致** |

### 2.6 `CDPPage.navigate_stock(stock_code, timeout=15, tabs=('fund_flow','f10')) -> bool`（P7b 收紧）

```python
def navigate_stock(self, stock_code, timeout=15, tabs=('fund_flow', 'f10')) -> bool:
```

| 步骤 | 行为 |
|------|------|
| ① 代码归一 | `stock_code = config.canonical_code(stock_code) or stock_code` —— 两种 ingress 拼写（`600519.SH`/`sh600519`）此后都能对上游 `SecuCode` 比较相等 |
| ② **快路径** | 持 `self._lock` 取 `cached = self._fresh_secu_code_locked(time.time())`；`_same_code(cached, stock_code)` ⇒ **直接返回 True**（不导航）。★ 必须带 **max-age**：否则过期快照会永远命中、页面再也不重新导航（P1-3） |
| ③ **限时取锁** | `wait_start = time()` → `self._acquire_navigate_lock(timeout)`；失败 ⇒ `return False`（**公平排队 + 有界等待**，不无限 park 调用方与准入位） |
| ④ 剩余预算复查 | `remaining = timeout - (now - wait_start)`；`remaining < 2` ⇒ 持锁再取一次 `_fresh_secu_code_locked`，返回 `_same_code(...)`（**锁后兜底**同样带 max-age） |
| ⑤ 导航 | `_maybe_reconnect()`（导航阈值内存自愈）→ `_ensure_ws()` → 清 `__cdp_api/__cdp_refetch` → `Page.navigate`（超时 `min(10, remaining)`）；异常时 `_ensure_ws()` 重试一次 |
| ⑥ 等待稳定 | 轮询 `refresh()` + `get_data()`，`_same_code(bi.secu_code, stock_code)` 即命中；错码需**持续 ≥3 次且距导航开始 >6s** 才提前中断（并发导航下共享页会合法地短暂显示**上一个**码） |
| ⑦ tabs | 命中后按 `tabs` 点击 `fund_flow`/`f10` 分页（北交所 `bj*` 码无这两页，**跳过**） |
| ⑧ 收口 | 循环结束再 `refresh()` + 校验一次；`return _same_code(...)`；`finally: self._navigate_lock.release()` |

> **`_navigate_lock` 是 `RLock`**：`fetch_cls_f10`/`_navigate_f10` 的外层限时获取与本函数内部获取可**同线程重入**，不会自死锁。

### 2.7 Chrome 进程探测 `_chrome_pids_by_flag(flag)` / `_kill_chrome_on_port(port)`（v1.3）

```python
def _chrome_pids_by_flag(flag) -> list[int]:
    """返回 cmdline 含 flag 的 PID；/proc 不可读/单条读失败 ⇒ 静默跳过。"""

def _kill_chrome_on_port(port) -> None:
    """SIGKILL 绑定该调试端口的 Chrome，并以 pkill -f 兜底，最后 sleep(0.5)。"""
```

- **fd 泄漏修复（v1.3）**：`/proc/{pid}/cmdline` 一律经 `with open(path, 'rb') as f:` 读取——**保证即使解码/判断抛错也立刻关闭 fd**。旧的无 `with` 写法在每次 `ensure_chrome`/`full_chrome_restart`/watchdog 都会为每个存活 PID 泄漏一个 fd；OOM 崩溃循环下探测频繁，fd 会单调累积。
- **防御面**：`os.listdir('/proc/')` 整体包 `try/except Exception`；非数字条目跳过；**单条 `open` 的 `OSError`/`IOError`（PID 在枚举与打开之间消失）静默跳过**（内核侧竞态，不是错误）。
- **杀进程兜底**：`os.kill(pid, SIGKILL)` 的 `OSError` 被吞；随后 `subprocess.run(['pkill','-f', flag], timeout=5)` 作为 `/proc` 不可见进程的兜底；整体包 `try/except Exception`。
- **不新增线程/定时器**（BR-CDP-12 不变）。
---

## 3. 数据结构

### 3.1 重启窗口（模块级，yaml）

```yaml
_restart_window:                 # 受 _restart_window_lock（新增 Lock，叶级）
  state:        idle | restarting | unavailable   # 枚举封闭
  window_start: <float|null>     # 离开 idle 的时刻（epoch 秒）
  window_end:   <float|null>     # 回到 idle / 判定 unavailable 的时刻；窗口进行中 = null

_restart_window_lock: threading.Lock   # 新增；只保护上面 3 个字段（无 IO、无嵌套）

_last_chrome_restart: <float>    # 既有，无锁读（GIL 下 float 读原子）；full_chrome_restart 在
                                 # _chrome_restart_lock 内写 —— 语义不变
```

### 3.2 状态机（转换表，唯一权威）

| 当前 | 目标 | 触发（函数） | 前置条件 | 副作用 |
|------|------|-------------|---------|--------|
| `idle` | `restarting` | `full_chrome_restart()` 进入临界区 | 节流窗口已过（现逻辑） | `window_start=now`；`window_end=None`；发布 metric |
| `restarting` | `idle` | `ensure_chrome()` 成功 | Chrome `/json` 可达 | `window_end=now`；发布 metric |
| `restarting` | `unavailable` | `ensure_chrome()` 真失败（无 chrome 二进制 / 15 次重试耗尽） | — | `window_end=now`；发布 metric；`log.error` |
| `unavailable` | `restarting` | 下一次 `full_chrome_restart()` | 节流窗口已过 | 同 `idle→restarting` |
| `unavailable` | `idle` | `ensure_chrome()` 成功（任意调用方） | — | `window_end=now`；发布 metric |
| `idle` | `unavailable` | `CDPEngine.start()` 失败 / `ensure_chrome()` 真失败 | — | `window_start=now`；`window_end=now`；发布 metric |
| `restarting` | `restarting` | `_mark_restarting()` 幂等重入 | — | **不更新 `window_start`**（窗口连续） |
| `idle` | `idle` | `_mark_idle()` 幂等 | — | 不更新字段（避免正常轮询污染窗口） |
| `restarting` | `unavailable` | **`ensure_chrome()` 内任何未捕获异常**（`which`/`Popen` 在 fork 压力下抛错） | — | `except Exception` ⇒ `log.exception` + `_mark_unavailable()`（**绝不让窗口敞着**） |
| `restarting` | `unavailable` | **`full_chrome_restart()` 的 `finally` 兜底** | `restart_window_snapshot()['state'] == 'restarting'` 仍成立 | `_mark_unavailable()` ⇒ **不存在"卡在 `restarting`"** |

> **节流受限的 `ensure_chrome() returns False` 属"未尝试"而非"失败"** → **不改状态**（否则一次合法节流会把状态误置 `unavailable`）。
>
> ★ **P7b 终态保证（BR-CDP-19）**：`restarting` 是**瞬态**，必然在有限步内到达 `idle`（成功）或 `unavailable`（失败）。这条保证有三个落点：① `ensure_chrome` 的 `try/except Exception → _mark_unavailable()`；② `full_chrome_restart` 的 `finally` 兜底；③ 节流分支"未尝试"不改状态。**若丢失该保证**，一个逃逸异常会把 `watchdog_restart_skip_reason()` 永久钉在 `'already_restarting'`（守护重启永久失效），且 `/healthz` 误报。

### 3.3 metrics 负载（yaml）

```yaml
cdp_restart_window:            # gauge(dict)，owner = cdp_engine（metrics.md §3.2 冻结名）
  state:        idle | restarting | unavailable
  window_start: <float|null>
  window_end:   <float|null>
```

### 3.4 页数据边界（yaml，`page_data` 的判定输入）

```yaml
CDPPage.get_data():
  {}                                  # 未就绪 / 重启窗口内（_reconnect 清空）→ page_data → null
  {'basic_info': null}                # 非空 dict（仍为合法返回值）→ page_data 返回该 dict；
                                      #   「具体键为 null」由调用方判定（A 类 timeline 旁支）
  {'basic_info': {...}, '__ws__': [...]}   # 正常合并结果
```

### 3.5 页面服务缓存的老化时钟（yaml，P7b）

```yaml
CDPPage.cache:          dict   # 合并后的服务缓存（对外经 get_data 可见）
CDPPage._last_data:     dict   # 服务缓存（供外部调用方；reconnect 清空）
CDPPage._last_data_ts:  dict   # ★ key -> 写入 _last_data 的时刻（**唯一年龄时钟**）
CDPPage._last_data_max_age: 600            # 秒
CDPPage._key_last_seen: dict   # key -> 最近刷新时刻（与 self.cache 的 TTL 清扫共用）
CDPPage._api_urls:      dict   # key -> 原始 URL（主动 re-fetch 注册表）

# 老化判定（get_data / _fresh_secu_code_locked 共用口径）：
#   ts = _last_data_ts.get(key)
#   ts is None or now - ts >= 600  ⇒ **陈旧**（跳过 / 视为无缓存）
#   ★ "时钟缺失 = 陈旧"：_reconnect 会清空 _last_data_ts，若把缺失当"新鲜"，重启前的
#     快照会被无限期当作有效数据、并随下一次取数刷新时间戳（P1-3）。
# 硬上限淘汰（_evict_stalest_last_data_locked，P7b）：
#   按 _key_last_seen 找最旧 key → del _last_data[key] → pop _last_data_ts[key]
#   → 若该 key 已不在 self.cache，再 pop _key_last_seen[key] / _api_urls[key]
#   （对称清理，避免旁表随淘汰次数无界增多）
```

---

## 4. 业务规则

| 编号 | 规则 | 依据 |
|------|------|------|
| **BR-CDP-1** | `page_data(page)` 是页面数据读取的**唯一合法入口**；返回 `None` ⇔ `page` 为 None / `get_data` 抛异常 / 返回非 dict / 返回空 dict | SAD §2.4 R18 |
| **BR-CDP-2** | `page_data` **绝不抛**（内部 `try/except Exception` + warning）；它是总函数 | AC-S1 |
| **BR-CDP-3** | `page_data` **不做键级兜底**（不补 `None`、不返回旧值）——键级缺失由调用方按端点形状产出 error 客体 | D-4 / R10 |
| **BR-CDP-4** | 重启窗口 `state` 的写操作**只有** `_mark_restarting/_mark_idle/_mark_unavailable` 三个原语；状态判断只读 `restart_window_snapshot()` | AR-12 |
| **BR-CDP-5** | 状态迁移**必须**发布 `metrics.set_gauge('cdp_restart_window', snapshot)`（幂等迁移不重复发布）；**且模块加载时发布一次初始 `idle` 快照**（模块级 `_publish_window()`）⇒ 进程生命周期内即便无任何迁移，`metrics.snapshot()` 也恒含 `cdp_restart_window`（**REV-DES-19**） | AC-S10 / MET-T10 |
| **BR-CDP-6** | 守护重启的**唯一**决策函数是 `watchdog_restart_skip_reason()`；盘中（`config._is_trading_hours()`）恒返回 `'trading_hours'` ⇒ **交易时段不重启 Chrome** | ADR-012 / R19 |
| **BR-CDP-7** | `_last_chrome_restart` 的节流判定（30s）与 back-to-back 保护**语义不变**，仅判定位置由 `server.py` 上收到本模块 | 现状保留 |
| **BR-CDP-8** | `CDPPage._heartbeat_interval()` 的交易时段判定**必须**调 `config._is_trading_hours()`；**禁止**本模块再出现时段字面量（`9/11/13/15` 等） | 状态判断集中（R17 同源） |
| **BR-CDP-9** | 重启窗口内 `CDPPage._reconnect()` 清空 `cache`/`_key_last_seen`/`_api_urls` **以及 `_last_data`/`_last_data_ts`**（P7b 补全）⇒ `get_data()` 退化为空 ⇒ `page_data → None` ⇒ A/A′ 端点走降级。**不额外加"重启期短路"分支**（避免改变 `ready` 语义） | AR-12 状态处理 |
| **BR-CDP-10** | `CDPEngine.ready` 语义**不变**（= 启动时 `/json` 可达）：不随重启窗口翻转 | 兼容性（`stock_api`/`server` 多处依赖 `config.cdp_engine.ready`） |
| **BR-CDP-11** | 导航阈值重启（`CDPPage._maybe_reconnect`，每 30 次导航）**不施加盘中避让**——它是内存自愈路径；但其内部 `full_chrome_restart()` 会经状态机（可观测） | ADR-012 决策 B 边界 |
| **BR-CDP-12** | 本模块**不新增线程**、不新增定时器；状态机为纯内存 | AC-S9 |
| **BR-CDP-13** | **`get_data()` 的老化口径（P7b / P1-3）**：合并时**只**接受 `_last_data_ts[key]` 存在且 `now - ts < _last_data_max_age(600s)` 的条目；**时钟缺失一律视为陈旧**（不是"新鲜"）。`self.cache` 的条目仍无条件覆盖（它有自己的 TTL 清扫）。⇒ 重启前的快照不会在时钟被清后仍以"新时间戳"重复发出。**同一口径**用于 `_fresh_secu_code_locked`。 | P1-3 / R10（拒读旧值） |
| **BR-CDP-14** | **`_reconnect()` 同时清两表（P7b）**：`self.cache` / `_key_last_seen` / `_api_urls` / **`_last_data` / `_last_data_ts`** 在同一 `with self._lock` 内清空。只清时钟表会让旧快照"永久新鲜"（BR-CDP-13 的失效面）。 | P1-3 |
| **BR-CDP-15** | **硬上限淘汰对称清理（P7b / P2-⑤）**：`_last_data` 超 `_LAST_DATA_MAX_KEYS(50)` ⇒ `_evict_stalest_last_data_locked()`：按 `_key_last_seen` 选最旧 key ⇒ 删 `_last_data[key]`，并 **`_last_data_ts.pop(key)`**；**仅当该 key 已不在 `self.cache`** 时才 `_key_last_seen.pop` / `_api_urls.pop`（否则会打断 `self.cache` 自身的 TTL 清扫，把泄漏搬到那张表）。 | P2-⑤ |
| **BR-CDP-16** | **`navigate_stock` 的快路径与兜底都必须带 max-age**（P7b / P1-3）：命中判定一律经 `_fresh_secu_code_locked(now)`；过期快照不得短路导航。锁内 `remaining < 2` 时**持锁复查**同一函数后再返回。 | P1-3 |
| **BR-CDP-17** | **导航锁限时（P7b / P1-2）**：只经 `_acquire_navigate_lock(timeout)` 获取 `_navigate_lock`；`timeout ≤ 0` 或等待超预算 ⇒ `False`（调用方降级，不 park 线程与准入位）。`fetch_cls_f10` / `_navigate_f10` 与 `navigate_stock` 的获取可**同线程重入**（RLock）。 | P1-2 / AC-S1 |
| **BR-CDP-18** | **`fetch_cls_f10` 的 A′ 语义（P7b 最终态）**：五条失败出口（engine 未就绪 / 无导航页 / 预算耗尽 / 全失败或全 `page_data=None` / **有数据但不匹配**）**全部** `cdp_unavailable`——**没有静默 `None` 的失败路径**。`stock_api.md §5.9/§10#15` 与本节逐字一致。 | AC-S4 A′ / P1-6 |
| **BR-CDP-19** | **重启窗口终态保证（P7b）**：`restarting` 必然收敛到 `idle` 或 `unavailable`（`ensure_chrome` 的 `except Exception` + `full_chrome_restart` 的 `finally` + 节流分支"不改状态"三者共同保证）。⇒ `watchdog_restart_skip_reason()` 不会被永久钉在 `'already_restarting'`。 | AR-12 / R19 |
| **BR-CDP-20** | **进程探测的 fd 与竞态纪律（v1.3）**：`/proc/{pid}/cmdline` **必须**经 `with open(...)` 读取（正常/异常路径都关 fd）；`/proc` 枚举失败、单条 `open` 因 PID 消失而 `OSError`/`IOError` 一律静默跳过；`kill` 的 `OSError` 吞掉并以 `pkill -f` 兜底。**禁止**裸 `open` 不关闭。 | AC-S9（24h fd/资源总账不单调增长）/ 2c2g OOM 恢复 |

---

## 5. 伪代码

### 5.1 状态机 + `page_data`

```python
import logging
import threading
import time

from . import config
from . import metrics

log = logging.getLogger('cdp')

_RESTART_STATES = frozenset({'idle', 'restarting', 'unavailable'})
_restart_window = {'state': 'idle', 'window_start': None, 'window_end': None}
_restart_window_lock = threading.Lock()


def restart_window_snapshot():
    with _restart_window_lock:                                # BR-CDP-4
        return dict(_restart_window)


def _publish_window():
    metrics.set_gauge('cdp_restart_window', restart_window_snapshot())   # BR-CDP-5


# ★ REV-DES-19：模块加载即发布初始 idle 快照
#   ⇒ metrics.snapshot() 恒含 cdp_restart_window（此后 _mark_idle 幂等不重复发布）
_publish_window()


def _mark_restarting():
    changed = False
    with _restart_window_lock:
        if _restart_window['state'] != 'restarting':          # 幂等：不刷新 window_start
            _restart_window['state'] = 'restarting'
            _restart_window['window_start'] = time.time()
            _restart_window['window_end'] = None
            changed = True
    if changed:
        _publish_window()


def _mark_idle():
    changed = False
    with _restart_window_lock:
        if _restart_window['state'] != 'idle':
            _restart_window['state'] = 'idle'
            _restart_window['window_end'] = time.time()
            changed = True
    if changed:
        _publish_window()


def _mark_unavailable():
    changed = False
    now = time.time()
    with _restart_window_lock:
        if _restart_window['state'] != 'unavailable':
            if _restart_window['state'] == 'idle':
                _restart_window['window_start'] = now       # 直接不可用：开窗即关窗
            _restart_window['state'] = 'unavailable'
            _restart_window['window_end'] = now
            changed = True
    if changed:
        _publish_window()
        log.error('[CDP] restart window → unavailable')


def page_data(page):
    """BR-CDP-1/2/3：页面数据唯一防御入口；总函数，绝不抛。"""
    if page is None:
        return None
    try:
        data = page.get_data()
    except Exception as exc:
        log.warning('[CDP] page_data: get_data failed: %s', exc)
        return None
    if not isinstance(data, dict) or not data:
        return None
    return data


def cdp_ready():
    eng = config.cdp_engine
    return bool(eng and eng.ready)


def watchdog_restart_skip_reason(now=None):
    """BR-CDP-6/7：守护重启唯一决策函数（按序短路）。"""
    now = time.time() if now is None else now
    if not cdp_ready():
        return 'not_ready'
    if restart_window_snapshot()['state'] == 'restarting':
        return 'already_restarting'
    if config._is_trading_hours(now):                         # ★ ADR-012 盘中避让
        return 'trading_hours'
    if now - _last_chrome_restart < _CHROME_RESTART_THROTTLE * 2:
        return 'recent_restart'
    return None
```

### 5.2 `ensure_chrome` / `full_chrome_restart` 的状态接线（只列改动点）

```python
def ensure_chrome(cdp_url=CDP_URL):
    port = urlparse(cdp_url).port or 9222
    host = urlparse(cdp_url).hostname or 'localhost'

    try:
        urllib.request.urlopen(f"http://{host}:{port}/json", timeout=2)
        _mark_idle()                                          # ← 新增：可达即 idle
        return True
    except Exception:
        pass

    global _last_chrome_restart
    now = time.time()
    with _chrome_restart_lock:
        if now - _last_chrome_restart < _CHROME_RESTART_THROTTLE:
            log.warning('[CDP] Chrome restart throttled (last restart: %.0f, now: %.0f)',
                        _last_chrome_restart, now)
            return False                                      # ★ 节流 = 未尝试 ⇒ 不改状态
        try:
            urllib.request.urlopen(f"http://{host}:{port}/json", timeout=2)
            _mark_idle()
            return True
        except Exception:
            pass

        _kill_chrome_on_port(port)
        _last_chrome_restart = time.time()
        chrome = <既有 which 探测>
        if not chrome:
            _mark_unavailable()                               # ← 真失败
            return False
        <既有 Popen>
        for _ in range(15):
            try:
                urllib.request.urlopen(f"http://{host}:{port}/json", timeout=2)
                _mark_idle()                                  # ← 启动成功
                return True
            except Exception:
                time.sleep(1)
        _mark_unavailable()                                   # ← 15 次重试耗尽
        return False


def full_chrome_restart(cdp_url=CDP_URL):
    global _last_chrome_restart
    ...
    with _chrome_restart_lock:
        now = time.time()
        if now - _last_chrome_restart < _CHROME_RESTART_THROTTLE * 2:
            log.warning('[CDP] full_chrome_restart: skipped back-to-back restart')
            return False                                      # 未尝试 ⇒ 不改状态
        _mark_restarting()                                    # ← 新增：进入窗口
        _kill_chrome_on_port(port)
        _last_chrome_restart = 0
        gc.collect()
        ok = ensure_chrome(cdp_url)                           # 内部会 _mark_idle/_mark_unavailable
        if ok:
            _last_chrome_restart = time.time()
        log.info('[CDP] full_chrome_restart: %s', 'OK' if ok else 'FAILED')
        return ok
```

### 5.3 交易时段单一来源（`CDPPage`）

```python
def _heartbeat_interval(self):
    """BR-CDP-8：时段判定统一走 config；盘中 10s / 非盘中 60s。"""
    return 10 if config._is_trading_hours() else 60
```

### 5.4 `CDPEngine.start()` 状态接线

```python
def start(self):
    port = urlparse(CDP_URL).port or 9222
    host = urlparse(CDP_URL).hostname or 'localhost'
    try:
        urllib.request.urlopen(f"http://{host}:{port}/json", timeout=2)
        self._ready = True
        _mark_idle()                                      # 初始已为 idle（模块加载已发布）⇒ 幂等不重复发布
        return True
    except Exception:
        _mark_unavailable()
        return False
```

### 5.5 重启窗口的异常兜底接线（P7b / BR-CDP-19）

```python
# module level：节流常量来自 config（env 注册中心）
_CHROME_RESTART_THROTTLE = config.CDP_RESTART_THROTTLE

# ensure_chrome()：真正的启动分支整体包在 try/except 中
def ensure_chrome(cdp_url=CDP_URL):
    ...
    with _chrome_restart_lock:
        if now - _last_chrome_restart < _CHROME_RESTART_THROTTLE:
            return False                                      # 节流 = 未尝试 ⇒ 不改状态
        try:
            ...
            if not chrome:
                _mark_unavailable()                           # 真失败
                return False
            <Popen>
            for _ in range(15):
                try:
                    <poll /json>; _mark_idle(); return True
                except Exception:
                    time.sleep(1)
            _mark_unavailable()                               # 15 次重试耗尽
            return False
        except Exception as exc:                              # ★ 逃逸异常（which/Popen 在
            log.exception(f'[CDP] ensure_chrome: unexpected error ({exc})')
            _mark_unavailable()                               #   fork 压力下抛错）
            return False                                      # ⇒ 绝不把窗口敞在 restarting


def full_chrome_restart(cdp_url=CDP_URL):
    ...
    with _chrome_restart_lock:
        if now - _last_chrome_restart < _CHROME_RESTART_THROTTLE * 2:
            return False                                      # 未尝试 ⇒ 不改状态
        _mark_restarting()
        try:
            _kill_chrome_on_port(port); _last_chrome_restart = 0; gc.collect()
            ok = ensure_chrome(cdp_url)                       # 内部自行 _mark_idle/_mark_unavailable
            if ok:
                _last_chrome_restart = time.time()
            return ok
        except Exception as exc:
            log.exception(f'[CDP] full_chrome_restart: unexpected error ({exc})')
            return False
        finally:
            # ★ BR-CDP-19：restarting 必须到达终态 —— 否则一次逃逸异常会让守护重启永久失效
            if restart_window_snapshot()['state'] == 'restarting':
                _mark_unavailable()
```

### 5.6 `get_data()` 老化 + 对称淘汰（P7b / BR-CDP-13/14/15）

```python
def get_data(self):
    """合并返回：以 live cache 为准，缺口由 _last_data 兜底（**带老化**）。

    `_last_data` 中超过 `_last_data_max_age` 的条目一律跳过；年龄时钟 = `_last_data_ts`
    （与值同写、reconnect 同清），**时钟缺失视为陈旧**（不是新鲜）—— 否则一次重连清掉
    时钟后，重启前的旧快照会被无限期重复发出（P1-3）。
    """
    with self._lock:
        now = time.time()
        merged = {}
        for key, val in self._last_data.items():
            ts = self._last_data_ts.get(key)
            if ts is not None and now - ts < self._last_data_max_age:     # ★ 缺失 = 陈旧
                merged[key] = val
        merged.update(self.cache)
        return merged


def _evict_stalest_last_data_locked(self):
    """硬上限淘汰 `_last_data` 最旧条目，旁表**对称清理**（P2-⑤）。调用方须持 self._lock。

    旧实现只删 `_last_data` ⇒ 每次淘汰泄漏一条 `_last_data_ts`（对称表漂移、无界增长）。
    `_key_last_seen` 是与 `self.cache` 的 TTL 清扫共用的新鲜度时钟，故**仅当该 key 已不在
    self.cache** 时才删它（否则 self.cache 的清扫会永远跳过该 key，把泄漏换个表继续）。
    """
    oldest = min(self._last_data, key=lambda k: self._key_last_seen.get(k, 0))
    del self._last_data[oldest]
    self._last_data_ts.pop(oldest, None)
    if oldest not in self.cache:
        self._key_last_seen.pop(oldest, None)
        self._api_urls.pop(oldest, None)


def _fresh_secu_code_locked(self, now):
    """未过 `_last_data_max_age` 的 `_last_data['basic_info'].data.secu_code`，否则 None。

    调用方须持 self._lock。年龄时钟 = `_last_data_ts`；**缺失即陈旧**（P1-3）——
    否则重连后旧快照会"永久匹配"同一个码。
    """
    bi = (self._last_data.get('basic_info') or {}).get('data') or {}
    ts = self._last_data_ts.get('basic_info')
    if ts is None or now - ts >= self._last_data_max_age:
        return None
    return bi.get('secu_code') if isinstance(bi, dict) else None


def _reconnect(self):
    ...
    with self._lock:
        self.cache.clear()
        self._key_last_seen.clear()
        self._api_urls.clear()
        self._last_data.clear()          # ★ P7b：服务缓存也是会话数据，两表同清
        self._last_data_ts.clear()
    ...
```

> **`_ingest_payload` 的两条老化路径**：① `self.cache` 按 `KEY_TTL`/`KEY_TTL_OVERRIDES` 清扫（`_key_last_seen` 为时钟）；② `_last_data` 按 `_last_data_max_age` 老化（`_last_data_ts` 为时钟）——两条**各自独立**，不可互借时钟。超 `_LAST_DATA_MAX_KEYS(50)` 或 `len(self.cache) > 50` 时都触发淘汰。

### 5.7 `navigate_stock` 的限时与 max-age（P7b / BR-CDP-16/17）

```python
def _acquire_navigate_lock(self, timeout):
    """限时获取 _navigate_lock（P1-2）。超时或 t≤0 ⇒ False（降级而非无限 park）。"""
    wait = max(0.0, timeout)
    if wait <= 0.0:
        return False
    try:
        return self._navigate_lock.acquire(timeout=wait)
    except Exception:
        return False


def navigate_stock(self, stock_code, timeout=15, tabs=('fund_flow', 'f10')):
    stock_code = config.canonical_code(stock_code) or stock_code   # ★ 单一拼写
    url = f'https://www.cls.cn/stock?code={stock_code}'
    # ① 快路径：仅当缓存快照对该码**新鲜**（带 max-age）时才跳过导航（P1-3）
    with self._lock:
        cached = self._fresh_secu_code_locked(time.time())
    if _same_code(cached, stock_code):
        return True
    # ② 限时取锁（公平排队，被预算兜住）
    wait_start = time.time()
    if not self._acquire_navigate_lock(timeout):
        return False
    try:
        remaining = timeout - (time.time() - wait_start)
        if remaining < 2:
            # ③ 锁后兜底同样带 max-age
            with self._lock:
                cached = self._fresh_secu_code_locked(time.time())
            return _same_code(cached, stock_code)
        self._maybe_reconnect()
        if not self._ensure_ws():
            return False
        <既有：清缓冲 → Page.navigate → 等 loadEventFired → 轮询 refresh/get_data 直到匹配>
        #   命中后按 tabs 点击 fund_flow / f10（bj* 北交所码跳过）
        #   「错码」需持续 ≥3 次且距 nav_started >6s 才提前中断
        return _same_code(bi.get('secu_code'), stock_code)
    finally:
        self._navigate_lock.release()
```

### 5.8 `_chrome_pids_by_flag`（v1.3 / BR-CDP-20）

```python
def _chrome_pids_by_flag(flag):
    """返回 cmdline 含 flag 的 PID；fd 必定关闭、竞态静默。"""
    pids = []
    try:
        for entry in os.listdir('/proc/'):
            if not entry.isdigit():
                continue
            try:
                with open(f'/proc/{entry}/cmdline', 'rb') as f:   # ★ v1.3：with 修复 fd 泄漏
                    cmdline = f.read().decode('utf-8', errors='replace')
                if flag in cmdline:
                    pids.append(int(entry))
            except (OSError, IOError):                            # PID 已消失 / 读失败 ⇒ 跳过
                pass
    except Exception:
        pass
    return pids
```

---

## 6. 错误处理

| 情形 | 行为 | 对外表现 |
|------|------|---------|
| `page` 为 `None`（页面未初始化） | `page_data` → `None` | A 类 → `{'error': ...}`；A′ → `_errors[code]='cdp_unavailable'` |
| `page.get_data()` 抛异常 | `page_data` → `None` + `log.warning` | 同上（绝不冒泡，AC-S1） |
| `get_data()` 返回 `{}`（重启窗口/缓存被清） | `page_data` → `None` | 同上（BR-CDP-9） |
| `get_data()` 返回 dict 但目标键为 `None`（如 `timeline`） | `page_data` 返回该 dict | **调用方**返回 `{'error': 'timeline unavailable'}`（A 类旁支，修 R18）；**不得**裸 `null` |
| Chrome 启动真失败 | `_mark_unavailable()` + `log.error` | `cdp_restart_window.state='unavailable'`（`/healthz` 可见） |
| 节流窗口内的重启请求 | 返回 `False`，**状态不变** | 不产生假 `unavailable` |
| 守护周期落在交易时段 | `watchdog_restart_skip_reason()` = `'trading_hours'` | 本轮不重启，顺延下一周期 |
| `metrics.set_gauge` 异常 | 由 metrics fail-safe（绝不抛）承担 | 不影响状态机（metrics 为叶子锁 + warning） |
| **`_last_data` 条目的时钟缺失**（如 `_reconnect` 刚清空） | `get_data` **跳过**该条（视为陈旧，BR-CDP-13） | 不返回过期快照（R10 拒读旧值） |
| **导航锁被长时占用**（他人 ~60s 导航中） | `_acquire_navigate_lock` 超预算 ⇒ `False`（BR-CDP-17） | `navigate_stock`/`fetch_cls_f10` 降级（换页 / `cdp_unavailable`），**不 park 线程与准入位** |
| **`ensure_chrome` 内逃逸异常** | `except Exception` ⇒ `log.exception` + `_mark_unavailable()`（BR-CDP-19） | 窗口收口 `unavailable`（`/healthz` 可见），守护重启仍可用 |
| **`full_chrome_restart` 内逃逸异常** | `finally` 复查 `state == 'restarting'` ⇒ `_mark_unavailable()` | 同上；**不存在卡在 `restarting`** |
| `fetch_cls_f10` 取到数据但**不匹配** | 由 `stock_api` 侧 `_raise_cdp_unavailable()`（BR-CDP-18） | `_errors[code]='cdp_unavailable'`（**不再**静默 `None`） |
| **`/proc` 枚举失败 / 单条 cmdline 读取失败（v1.3）** | `_chrome_pids_by_flag` 静默跳过（`OSError`/`IOError`）；fd 由 `with open(...)` 保证关闭 | 探测退化为"未找到该 PID"，`pkill -f` 兜底仍执行；**不泄漏 fd**（BR-CDP-20） |

**降级路径总览**：`page_data → None` 是 A/A′ 两类端点降级的**唯一信号源**；形态由端点形状决定（A=error 客体，A′=逐码 null + `_errors`，D-4/ADR-005）。

---

## 7. 并发安全

| 锁 | 保护对象 | 新增/既有 | 纪律 |
|----|---------|----------|------|
| `_restart_window_lock` | `_restart_window`（3 字段） | **新增** Lock | 临界区仅字段读写，**无 IO、无嵌套加锁、不触碰 `_chrome_restart_lock`/`_ws_lock`** |
| `_chrome_restart_lock` | Chrome 杀/启 临界区 + `_last_chrome_restart` | 既有 RLock | 状态迁移 `_mark_*` 在其内部调用**仅做字段写**（纳秒级），不引入新锁序 |
| `page._lock` / `page._ws_lock` / `page._reconnect_lock` / `page._navigate_lock` | 页面内部 | 既有 | `page_data` 只经 `get_data()`（内部持 `page._lock`）；本模块**不嵌套**。`_navigate_lock` 为 **RLock**，经 `_acquire_navigate_lock` **限时**获取（BR-CDP-17） |
| `page._lock`（`_last_data`/`_last_data_ts` 的一致性） | P7b | 既有 | `get_data` / `_fresh_secu_code_locked` / `_evict_stalest_last_data_locked` / `_reconnect` 的清理**均在同一 `_lock` 内** ⇒ 两张表不会读到半更新状态 |

**锁序（硬约束）**：`_chrome_restart_lock → _restart_window_lock → metrics._lock`；**禁止反向**。`_restart_window_lock` **永不**在持有页面锁时获取（`page_data` 不碰状态机；`_mark_*` 不在页面锁内调用）。

**指标发布位置**：`_publish_window()` 在**释放 `_restart_window_lock` 之后**调用（先快照、后发布），避免持状态锁时进入 metrics 锁（进一步压缩锁序面）。

**无新增线程**：状态机为纯内存对象；`CDPEngine`/`CDPPage` 的既有线程模型不变（AC-S9 线程总账不变）。

---

## 8. 测试要点（映射 AC）

| 用例 | 步骤 / 断言（精确） | 覆盖 AC |
|------|-------------------|---------|
| **CDP-T1** `page_data` 边界矩阵 | 依次注入：`None` page、`get_data` 抛异常、返回 `None`/`[]`/`{}`/`{'a':1}` ⇒ 前四者返回 `None`、末者原样返回；**全程不抛** | R18 / S1 |
| **CDP-T2** 空 dict 不误判为有数据 | `_reconnect` 清空后 `get_data()=={}` ⇒ `page_data → None`；A 类调用方返回 `{'error': ...}`（非 `{}`） | S1/S4 |
| **CDP-T3** timeline 缺失不返回裸 null | `page_data` 返回 `{'basic_info': {...}}`（无 `timeline`）⇒ server 侧返回 `{'error': ...}` | **R18 旁支 / S4** |
| **CDP-T4** 状态机转换表 | 逐条驱动 §3.2 的 8 条转换，断言 `restart_window_snapshot()` 的 `state/window_start/window_end`；幂等迁移不刷新 `window_start` | AR-12 / S10 |
| **CDP-T5** 盘中避让 | patch `config._is_trading_hours` → True ⇒ `watchdog_restart_skip_reason() == 'trading_hours'`；patch `full_chrome_restart` 计数 ⇒ 守护循环**未**调用它 | **ADR-012 / S4 / R19** |
| **CDP-T6** 节流避让 | `now - _last_chrome_restart < 30` ⇒ `'recent_restart'`；`cdp_ready()` False ⇒ `'not_ready'`；state 为 `restarting` ⇒ `'already_restarting'` | R19 |
| **CDP-T7** 节流不污染状态 | 节流窗口内 `ensure_chrome()` 返回 False ⇒ `state` 保持 `idle`（**非** `unavailable`） | T4 边界 |
| **CDP-T8** 失败置 unavailable | 无 chrome 二进制（patch `which` 返回非 0）⇒ `ensure_chrome()` False 且 `state=='unavailable'` | R19 / S4 |
| **CDP-T9** 窗口可观测（含初始态） | **未发生任何迁移**时 `metrics.snapshot()` 已含 `cdp_restart_window` 且 `state=='idle'`（REV-DES-19）；任一转换后 `metrics.snapshot()['cdp_restart_window']` 与 `restart_window_snapshot()` 一致；键 ∈ `metrics._KNOWN` | **S10 / MET-T8b / MET-T10** |
| **CDP-T10** 时段判定单一来源 | 全仓 grep `cdp_engine.py` **无** `9 and m >= 30`/`13 <= h <= 14` 时段字面量；`_heartbeat_interval()` 随 `config._is_trading_hours` patch 变化 | S7/R17 同源 |
| **CDP-T11** 无新增线程 | 启动+运行前后 `threading.active_count()` 不因本模块增长 | S9 |
| **CDP-T12** 既有回归 | `_maybe_reconnect` 阈值重启用例（test_stream.py:315-335）保持通过（`full_chrome_restart` 被 patch） | 回归 |
| **CDP-T13** `page_data=None` 跨模块语义 | patch `page_data` 恒 `None` + `_navigate_f10` 恒成功 ⇒ `stock_api.fetch_cls_f10` 抛 `cdp_unavailable`（**非**返回 `None`）；`handle_cls_f10` 组装 `_errors[code]='cdp_unavailable'`（REV-DES-18，两文档一致） | **AC-S4 A′** |
| **CDP-T14** `get_data` 老化口径（P7b） | ① `_last_data={'a':1}` + `_last_data_ts={'a': now-601}` ⇒ 结果**不含** `a`；`ts=now-1` ⇒ 含；② **删掉 `_last_data_ts['a']`（时钟缺失）⇒ 结果不含 `a`**（缺失=陈旧）；③ `self.cache` 的键无条件出现在结果中 | BR-CDP-13 / R10 |
| **CDP-T15** `_reconnect` 双表同清（P7b） | `_reconnect` 后 `_last_data == {}` **且** `_last_data_ts == {}`（+ `cache`/`_key_last_seen`/`_api_urls` 清空）；随后 `get_data()` 不含重启前快照 | BR-CDP-9/14 |
| **CDP-T16** 硬上限对称淘汰（P7b） | 灌 > `_LAST_DATA_MAX_KEYS` 个键 ⇒ `len(_last_data) <= 50` **且** `len(_last_data_ts) <= 50`（不泄漏）；被淘汰 key 已不在 `self.cache` 时 `_key_last_seen`/`_api_urls` 同步移除；仍在 `self.cache` 时**保留** `_key_last_seen`（不打断 cache 的 TTL 清扫） | BR-CDP-15 |
| **CDP-T17** `navigate_stock` max-age 与限时锁（P7b） | ① `basic_info.secu_code` 匹配但 `_last_data_ts` 已 >600s（或缺失）⇒ **不**走快路径（`navigate_stock` 仍执行导航）；② `_navigate_lock` 被他线程长持 ⇒ `_acquire_navigate_lock(timeout)` 返回 False、`navigate_stock` 返回 False（**不无限等待**）；③ 锁后 `remaining < 2` 走同一 max-age 兜底 | BR-CDP-16/17 / P1-2/P1-3 |
| **CDP-T18** 窗口终态保证（P7b） | ① patch `Popen` 抛异常 ⇒ `ensure_chrome()` 返回 False 且 `state=='unavailable'`（**非** `restarting`）；② patch `ensure_chrome` 在 `full_chrome_restart` 内抛异常 ⇒ `finally` 后 `state=='unavailable'`；③ 节流分支返回 False ⇒ 状态**不变** | BR-CDP-19 / R19 |
| **CDP-T19** env 注册（P7b） | `cdp_engine._CHROME_RESTART_THROTTLE is config.CDP_RESTART_THROTTLE`；全仓 grep `cdp_engine.py` **无** `os.getenv` | BR-CFG-16 / §10#11 |
| **CDP-T20** 进程探测不泄漏 fd（v1.3 / BR-CDP-20） | ① patch `os.listdir('/proc/')` 返回不可读 PID 条目 ⇒ `_chrome_pids_by_flag` 不抛、返回 `[]`；② 反复调用 N 次后用 `resource`/`len(os.listdir('/proc/self/fd'))` 或计数打桩断言 **fd 数不随调用次数增长**（`with open` 已关闭）；③ `/proc/{pid}/cmdline` 含 flag 的条目被正确返回 | AC-S9（fd 不单调增长）|

---

## 9. AC 追溯矩阵

| 本模块设计点 | 覆盖 AC |
|-------------|---------|
| `page_data` 唯一防御入口 + 总函数（BR-CDP-1/2） | **AC-S1**（全端点异常兜底）/ **R18** |
| A 类 error 客体 / A′ 逐码 `cdp_unavailable` 的信号源（BR-CDP-3） | **AC-S4**（CDP 降级路径 A 4 / A′ 1）/ **AC-A5** |
| `timeline` 缺失不返回裸 null（§6） | **AC-S4**（A 类 4 端点逐条验证）/ R18 旁支 |
| 重启窗口状态机 + 幂等迁移（BR-CDP-4/5） | **AC-S10**（`cdp_restart_window`）/ **R19** |
| 盘中避让（BR-CDP-6） | **AC-S4**（降级可验证）/ **R19** / ADR-012 |
| 节流/back-to-back 保护保留（BR-CDP-7） | R19（不制造额外无数据窗口） |
| `_is_trading_hours` 单一来源（BR-CDP-8） | R17 同源 / S7 |
| 无新增线程/无存储（BR-CDP-12） | **AC-S9**（24h 资源总账） |
| 页面数仍由 `CDP_STOCK_PAGES` 决定（§1.2） | **AC-S9 / R20**（本模块不改，登记由 server 内存总账承接） |
| **`get_data` 老化 / `_reconnect` 双表同清（BR-CDP-13/14）** | **AC-A4 / R10**（拒读过期数据）/ S1 |
| **硬上限对称淘汰（BR-CDP-15）** | **AC-S9**（24h 资源总账：旁表不无界增长） |
| **`navigate_stock` max-age + 限时锁（BR-CDP-16/17）** | **AC-S1**（CDP 慢不拖垮准入）/ **P1-2/P1-3** |
| **A′ 五出口无静默 `None`（BR-CDP-18）** | **AC-S4 A′** / AC-A10（失败可辨识） |
| **窗口终态保证（BR-CDP-19）** | **AC-S4**（降级可验证）/ **AC-S10**（`cdp_restart_window` 不误报） |
| **进程探测 fd 纪律（v1.3 / BR-CDP-20）** | **AC-S9**（24h 资源总账：fd 不因探测单调增长） |

---

## 10. 与 SAD / 现有代码的偏差与歧义标注（不擅自改 SAD）

| # | 项 | SAD 表述 | 本文裁决 | 理由 |
|---|----|---------|---------|------|
| 1 | 守护重启避让的**落点** | SAD §3 把 `_cdp_memory_watchdog` + `_is_trading_hours` 避让记在 **`server.py`**；同时要求 cdp_engine"只保留窗口状态机与页面数联动" | **判断原语（`watchdog_restart_skip_reason`/`cdp_ready`）落在 cdp_engine**，`server._cdp_memory_watchdog` 只调它 + `full_chrome_restart()` | 任务要求"状态判断集中在 engine，不散落"；且 `_last_chrome_restart`/节流常量/窗口状态均在本模块，判断放此处可避免跨模块读私有全局。**行为与 SAD 一致，落点细化**——不改 SAD |
| 2 | `CDPEngine.ready` 在重启窗口内的取值 | SAD 未定义 | **保持既有语义不变**（不因 `restarting` 翻转） | `stock_api`/`server` 多处依赖；翻转会使重启后无法自动恢复 ready。降级由 `page_data → None` 自然触发（BR-CDP-9/10） |
| 3 | "重启期间的状态处理" | SAD 未给显式分支 | **不新增短路分支**：`_reconnect` 清空页面缓存 ⇒ `get_data()=={}` ⇒ `page_data → None` ⇒ A/A′ 降级 | 避免发明新降级路径；复用既有机制，行为可测（CDP-T2） |
| 4 | 导航阈值重启是否也避让 | ADR-012 只裁"守护重启" | `_maybe_reconnect`（每 30 导航）**不避让**，但记入状态机 | ADR-012 决策 B 的原文范围；它是内存自愈路径，避让会使低流量长期不回收 |
| 5 | `ensure_chrome` 节流返回 False 的状态语义 | 未定义 | 视为"未尝试"，**不置 unavailable** | 否则一次合法节流即把 CDP 误标为不可用（`/healthz` 误报） |
| 6 | `page_data` 是否补 `None` 键 | SAD 只说"None/非 dict/空 → 调用方产出 error" | **不补键**（BR-CDP-3） | 补键会把"缺数据"伪装成"有数据但值为 null"，破坏 A 类 timeline 旁支的 error 客体语义 |
| 7 | metrics 名 `cdp_restart_window` | SAD §2.6 与 `metrics.md` §3.2 一致 | 完全对齐（`{state, window_start, window_end}`） | 无偏差 |
| 8 | `_heartbeat_interval` 的时段复本 | SAD 未提 | 删除复本，改调 `config._is_trading_hours()` | 状态判断单一来源（任务要求）；行为等价（同一工作日/时段口径） |
| 9 | **`page_data=None` 的 A′ 语义（REV-DES-18 + P7b 收口）** | §2.1 称 `page_data(page) is None` 时 `continue`/最终 `cdp_unavailable` | **P7b 最终态**：五出口（engine 未就绪 / 无页 / 预算耗尽 / 全失败或全 `page_data=None` / **有数据但不匹配**）**全部** `cdp_unavailable`；**不再有"有数据但不匹配 ⇒ `None`"的例外**（BR-CDP-18） | 与 `stock_api.md §5.9/§10#15` 逐字同步；"取到但属于别的股票"仍是该码本轮未取到数据，静默 `None` 让 batch 每 tick 白付导航且无错误信号 |
| 10 | **初始 idle 未发布（REV-DES-19）** | SAD §2.6 要求 `cdp_restart_window` 可观测 | 模块加载时 `_publish_window()` 发布初始 idle 快照 | 否则进程生命周期内无迁移时 `metrics.snapshot()` 缺该键，与 AC-S10 / MET-T10「全名」断言张力；healthz `cdp` 字段本就直读 `restart_window_snapshot()`，不受影响 |
| 11 | **P7b · `_last_data` 老化时钟** | SAD 未定义 CDP 服务缓存的老化 | `_last_data_ts` 为唯一年龄时钟，**缺失=陈旧**；`_reconnect` 双表同清（BR-CDP-13/14） | 缺失当时钟"新鲜"会让重启前快照被无限期（并以新时间戳）重复发出，直接违反 R10「过期=拒读」 |
| 12 | **P7b · 硬上限淘汰对称清理** | SAD 未定义旁表清理 | `_evict_stalest_last_data_locked`：同步 `_last_data_ts`；`_key_last_seen`/`_api_urls` **仅在键已离开 `self.cache` 时**才清（BR-CDP-15） | 只删 `_last_data` 会每次淘汰泄漏一条旁表记录（无界漂移）；无条件清 `_key_last_seen` 会把泄漏搬进 `self.cache`（其 TTL 清扫依赖该表） |
| 13 | **P7b · `navigate_stock` 快路径 max-age + 限时锁** | SAD §2.4 R18 未细化 | 快路径与锁后兜底均经 `_fresh_secu_code_locked`；导航锁 `acquire(timeout)`（BR-CDP-16/17） | 无 max-age ⇒ 过期快照永久命中、页面再不重新导航；无界 `acquire` 会 park 请求线程与准入位（CDP 慢 ⇒ 整站 503） |
| 14 | **P7b · 窗口异常兜底** | SAD 未定义异常路径 | `ensure_chrome` 的 `except Exception → _mark_unavailable()` + `full_chrome_restart` 的 `finally` 兜底（BR-CDP-19） | `which`/`Popen` 在 2c2g OOM 下会抛错，且 `ensure_chrome` 也被 `_reconnect`/`_ensure_ws` 从心跳线程调用 ⇒ 逃逸异常会同时杀死心跳线程并把窗口钉在 `restarting` |
| 15 | **P7b · `CDP_RESTART_THROTTLE` 来源** | SAD §3 cdp_engine 行未列该 env | 改读 `config.CDP_RESTART_THROTTLE`（config 注册，默认 15）（§1.3 / BR-CFG-16） | 避免"同一 env 两处定义、一处生效"；`config.md §10#13` 已同步登记 |
| 16 | **v1.3 · `/proc` 探测 fd 泄漏** | SAD 未定义进程探测实现 | `_chrome_pids_by_flag` 的 cmdline 读取改 `with open(...)`（BR-CDP-20，§2.7/§5.8） | 旧的无 `with` 写法为每个存活 PID 泄漏一个 fd；OOM 崩溃循环/高频探测下 fd 单调累积，最终探测与 CDP 连接一起失败 |

---

## 11. 交付自检

- [x] 无 `{例:` 占位符；`page_data`/状态机/回避原因枚举均为实值
- [x] 接口签名精确（参数/默认/返回键集合/异常=不抛）
- [x] §3 为 yaml 代码块（窗口结构 / 状态转换表 / metrics 负载 / 页数据边界）
- [x] 状态机含**转换表 + 前置条件 + 副作用 + 幂等规则**；无"视情况"
- [x] 与基础层对齐：`config._is_trading_hours(now=None)`、`metrics.set_gauge(name,value,key=None)`
- [x] 锁清单 + 锁序（`_chrome_restart_lock → _restart_window_lock → metrics._lock`）
- [x] 与 `server.py` / `stock_api.py` 的调用契约明确（A/A′ 降级形态）
- [x] AC 追溯覆盖 S1/S4/S9/S10/A5 + R18/R19/R20
- [x] **v1.1**：§2.1 A′ 契约与 `stock_api.md §5.9` 对 `page_data=None` 的口径逐字一致（REV-DES-18）；`metrics.snapshot()` 恒含 `cdp_restart_window`（模块加载发布初始 idle，REV-DES-19）
- [x] **v1.2（P7b）**：§2.1 A′ **收口为五出口全 `cdp_unavailable`**（BR-CDP-18，修正 REV-DES-18 的 `None` 例外；与 `stock_api.md §5.9/§10#15` 逐字同步）
- [x] **v1.2（P7b）**：`get_data` 老化（缺失=陈旧）/ `_reconnect` 双表同清 / `_evict_stalest_last_data_locked` 对称清理（§2.5/§3.5/§4 BR-CDP-13..15/§5.6/§6/CDP-T14..T16）
- [x] **v1.2（P7b）**：`navigate_stock` max-age 快路径 + 锁后兜底 + `_acquire_navigate_lock` 限时（§2.6/§4 BR-CDP-16/17/§5.7/CDP-T17）
- [x] **v1.2（P7b）**：重启窗口终态保证（`ensure_chrome` except + `full_chrome_restart` finally，§3.2/§4 BR-CDP-19/§5.5/CDP-T18）；`CDP_RESTART_THROTTLE` 改由 config 注册（§1.3/CDP-T19）
- [x] **v1.3**：`_chrome_pids_by_flag` 的 `/proc/{pid}/cmdline` 改 `with open(...)`（修复 fd 泄漏；§2.7/BR-CDP-20/§5.8/§6/CDP-T20/§9/§10#16）
- [x] **v1.4（溯源收口 + 引用时点约定）**：头部上游 **SAD v1.3 → v1.12 / PRD v0.3 → v0.10**；基础层接口权威 **config v1.1 → v1.6 / metrics v1.1 → v1.8**（指向现行版本）；新增「引用时点约定」——接口权威栏 = 本文最后同步时点快照、**落后一版不属漂移**，内容以被引文档头部为准。**代码 / 契约 / BR / 测试编号 / 偏差零变更**；**未改代码 / SAD / PRD / API.md / README.md / `.opencode`**

---

## 12. 变更记录

| 版本 | 日期 | 说明 |
|------|------|------|
| v1.0 | 2026-09-15 | 首版（批次 2 数据层） |
| v1.1 | 2026-09-15 | 按 `doc/review/数据层三模块_详细设计评审_专家版.md`（REV-DES-20260915-002）修订：**P2 REV-DES-18**（§2.1 A′ 与 stock_api 统一 `page_data=None`=取数失败）；**P2 REV-DES-19**（模块加载发布初始 idle 快照，BR-CDP-5/§5.1/§5.4/§10#10 同步）。**既有公开签名与状态机不变** |
| v1.2 | 2026-09-16 | **P7b 契约同步（以 `cdp_engine.py` 实现为准）**：`get_data` 以 `_last_data_ts` 老化（缺失=陈旧）·`_reconnect` 双表同清·`_evict_stalest_last_data_locked` 对称清理·`navigate_stock` max-age 快路径/锁后兜底/限时导航锁·`_same_code` 归一·重启窗口异常兜底（终态保证）·`CDP_RESTART_THROTTLE` 改由 config 注册·**A′ 收口为五出口全 `cdp_unavailable`**（修正 REV-DES-18）。新增 BR-CDP-13..19、CDP-T14..T19、§10#11..15。**未改代码** |
| v1.3 | 2026-09-17 | **P7b 传输层批次契约同步（以 `cdp_engine.py` 实现为准）**：`_chrome_pids_by_flag` 的 `/proc/{pid}/cmdline` 改 `with open(...)`（**修复 fd 泄漏**）·补记 `/proc` 不可读/PID 竞态/pkill 兜底防御面。新增 BR-CDP-20、CDP-T20、§2.7、§5.8、§10#16。**未改代码** |
| v1.4 | 2026-09-18 | **溯源收口 + 引用时点约定（只改文档）**：头部上游 **SAD v1.3 → v1.12 / PRD v0.3 → v0.10**；基础层接口权威 **config v1.1 → v1.6 / metrics v1.1 → v1.8**（指向现行版本）；新增「引用时点约定」——接口权威栏 = 本文最后同步时点快照，**落后一版不属漂移**，内容以被引文档头部为准。**无 BR 语义变更 / 无对外契约变更**；**未改代码 / SAD / PRD / API.md / README.md / `.opencode`** |
