# PRF-LAT-02 · margin 终端缓存 P2 收尾小改 — 代码评审报告（复审）

- **CR 编号**：CR-20260920-002
- **评审模式**：`review+drift`（P5b 复审 + P7a 漂移检测合并）
- **日期**：2026-09-20
- **变更范围**（仅 3 处，不重评上一轮主变更）：
  1. `china_finance_rss/market_api.py` — 命中路径（:92-96）与写入/淘汰路径（:124-127）各新增一次**锁外** `metrics.set_gauge('cache_entries', <锁内读长度>, key='margin')`
  2. 同文件模块 docstring（:5-8）——过时表述更正（`fetch_json` 仍是唯一 HTTP 出口，但 TTL 新鲜的终端缓存命中不再调用它）
  3. `tests/test_data_layer.py:1491` 新增 `test_terminal_cache_publishes_cache_entries_gauge`（写后 ==1 / 命中后 ==1 / LRU 淘汰后 == `cache_max`），计数 525 → 526
- **关联契约**：`doc/detailed/market_api.md` / `doc/detailed/metrics.md`
- **前置**：上一轮 CR-20260920-001（PRF-LAT-02 主变更）结论 ✅（0 P0 / 0 P1 / 6 P2）；本轮针对其收尾修复 CR-02（写路径未发布 `cache_entries{margin}`）、CR-04（docstring 过时）复审。

## 评审结论

**✅ 无 P0、无 P1；2 项 P2（1 项测试强度、1 项并发瞬态口径）。允许合并。**

总评：三处改动方向正确、实现干净——两条 `set_gauge` 均严格落在 `_margin_cache_lock` 的 `with` 之外（与 `stock_api._cache_store` / `cache._publish_url_stats` 的 S1-4 纪律逐点对齐），labelled 写法与 `_LABELED_GAUGES` 白名单完全一致，docstring 更正准确。**唯一需要动手的是新用例的命中分支不可证伪**（删掉命中路径那条 `set_gauge` 测试仍绿），属测试强度问题、不阻断。

## 一、评审概要

| 项 | 值 |
|---|---|
| 结论 | ✅（无 P0 且 P1 = 0） |
| P0 / P1 / P2 | **0 / 0 / 2** |
| 是否允许合并 | 允许 |
| 锁纪律（两条 `set_gauge` 均在锁外） | ✅ 通过 |
| gauge 语义（`key=` 形式 + `_LABELED_GAUGES` 白名单） | ✅ 通过 |
| 测试可证伪性 | ⚠️ 命中分支不可证伪（P2-01） |
| 并发 gauge 失真 | 瞬态、自愈、可接受（P2-02） |
| 契约漂移 | 有，属 P7b-r7 并行同步范围，详见 `## 漂移检测` |

## 二、评审范围

后端：`china_finance_rss/market_api.py`、`tests/test_data_layer.py`。
前端 / 小程序：无。
上一轮主变更（终端缓存本体、`config.cache_max`、其余 5 用例）**不在本轮范围**，沿用 CR-20260920-001 结论。

## 三、问题清单

| ID | 等级 | 位置 | 问题 | 阻断 |
|---|---|---|---|---|
| CR-07 | P2 | `tests/test_data_layer.py:1501-1502` | 命中分支断言不可证伪：删 `market_api.py:96` 仍绿 | 否 |
| CR-08 | P2 | `market_api.py:92-96` / `:124-127` | 锁内读长度 / 锁外发布：并发写淘汰交错可使 gauge 终态短暂陈旧（自愈） | 否 |

## 四、问题详情

### Dim 2 — 并发 / 锁纪律（评审重点 1）

**结论：✅ 通过。** 两条 `set_gauge` 的调用点均在锁外：
- 命中路径：`with _margin_cache_lock:` 块在 `market_api.py:92` 结束（`entries = len(_margin_cache)` 为块内最后一句），`:96` 的 `set_gauge` 在块外。
- 写入/淘汰路径：`with` 块为 `:117-124`，`:127` 的 `set_gauge` 在块外。
与 `stock_api._cache_store`（`stock_api.py:330-338`：`size = len(cache)` 在锁内、`set_gauge` 在锁外）及 `cache._publish_url_stats`（`cache.py:66-71`，docstring 明确 "call *outside* `_cache_lock` — S1-4"）**逐点一致**；`metrics._lock` 为叶子锁（`metrics.py:16` 注释）、永不反调业务模块 ⇒ 无锁序环。命中分支仅持锁做 `get`/`move_to_end`（`:87-92`），未在持锁时调用 `metrics`/`fetch_json`。

**CR-08 [P2] 锁内读长度、锁外发布：交错下 gauge 可短暂陈旧（瞬态、自愈、可接受）**
- 证据链：当线程 A（命中 market `99`）在 `:92` 锁内读到 `entries=1`、释放锁后被抢占；线程 B（写 market `1`）持锁将长度改为 2、释放并发布 `2`；A 恢复后在 `:96` 发布 `1` → 若无后续缓存操作，gauge 终态为 `1` 而实际长度为 `2`（陈旧）。
- 量化判断：① **非长期失真**——margin 是高频轮询的单键端点，任何后续命中/写入都会重新发布当前长度（自愈窗口 = 下一次缓存操作，通常一个请求周期内）；② **有界**——误差仅来自并发窗口内「读值 vs 发布」的乱序，纯读负载下长度不变、无失真；③ **非本改引入的新模式**——`stock_api._cache_store` 同构（`:337-338`），是全仓为满足 S1-4（不持业务锁发布指标）而**有意接受**的观测层权衡。
- 等级判定：观测口径的毫秒级瞬态、非业务数据、非资金/安全面 ⇒ **P2**，不阻断。
- 修复方向（可选、不建议本轮改）：若要求强一致，可在锁内同时携带「长度 + 版本号」并在发布时校验，但代价是引入额外共享状态且背离既有约定；**推荐维持现状、对齐 `stock_api` 既定口径**。

### Dim 1 — gauge 语义（评审重点 2）

**结论：✅ 通过。**
- 写法：`metrics.set_gauge('cache_entries', entries, key='margin')` —— 与 `stock_api.py:338`（`key=domain`）和 `cache.py:69`（`key=metric_key`）**完全一致的关键字 `key=` 形式**，非位置参数、非 `{'margin': n}` 整体覆盖。
- 白名单：`cache_entries` 同时在 `metrics._KNOWN`（`metrics.py:24`）与 `metrics._LABELED_GAUGES`（`metrics.py:62`，`frozenset({'cache_entries'})`）中，且 `assert _LABELED_GAUGES <= _KNOWN`（`:63`）通过 ⇒ 走 labelled 分支（`:121-131`），**不触发** `unregistered metric name` / `labeled write to an unlabelled gauge` 的 warning / 失败安全路径。
- 合并安全：`set_gauge` labelled 分支对非 dict 现值会 warning 并忽略，但全仓无对 `cache_entries` 的无 key 写入，且 `cache.py` 的 `url`/`feed` 标签与 `margin` 通过 `cur[key] = value` 合并保留（BR-MET-4）⇒ 不互相清空。
- `key='margin'` 为新增标签；运行时无冲突（标签即键，语义上对应 margin 域），其**文档登记**见 `## 漂移检测`。

### Dim 3 — 测试强度（评审重点 3）

**CR-07 [P2] 命中分支断言不可证伪**
- 位置：`tests/test_data_layer.py:1498-1502`。
- 证据链：用例断言「写后 `_gauge()==1`」（:1500）→「命中后 `_gauge()==1`」（:1502）。命中路径 `market_api.py:96` 发布的也是 `1`（命中不改变长度），而该值在 `:1499` 的写入路径已由 `:127` 发布过 ⇒ **若删除 `market_api.py:96` 的 `set_gauge`，`:1502` 仍读到 1、断言仍过**，命中分支从未被真正覆盖（"still 1" 只能证明"未回归"，不能证明"命中路径确实发布"）。
- 反例构造（建议）：在写入与命中之间**改变真实长度**，令只有命中路径能修正 gauge——例如在 `with market_api._margin_cache_lock:` 内直接注入第二条目（`market_api._margin_cache['1']=payload; market_api._margin_cache_ts['1']=now`），随后调 `fetch_margin('99')` 命中，断言 `_gauge()==2`；或先经 `metrics.set_gauge('cache_entries', 999, key='margin')` 置脏，再命中断言被修正回真实长度。此时删 `:96` 必红。
- 淘汰分支（`:1504-1512`）**可证伪**：断言 `_gauge()==cap`（8）能捕获「在淘汰前取长度（9）」的实现错误，保留。
- 其余强度检查均通过：无跨用例污染（`MarketApiTests.setUp/tearDown` 均 `metrics.reset()` + `_clear_margin_cache()`，`:1319-1333`，且 `patch.object` 自动还原 `VALID_MARKETS`）；淘汰分支通过临时扩展 `VALID_MARKETS = ('0'...'9')`（cap+2）真实触发 eviction（`cache_max=8 > len(合同枚举)=4`，故必须扩展，写法与既有 `test_terminal_cache_lru_is_bounded` 一致）；读 gauge 用 `metrics.snapshot()['cache_entries'].get('margin')`，与 `test_cache.py:226` / `test_data_layer.py:1534` 既有写法一致。
- 降级说明：生产代码正确（命中发布本身有自愈价值，见 CR-08），仅为测试覆盖缺口 ⇒ **P2**，不阻断合并；建议随下次触碰该文件时补齐反例。

### 修复副作用逆向检查（无 `>>SIDE-EFFECT:` 标记，按 diff 推断受影响点）

| 受影响点 | 所属模块 | 逆向假设 | 结论 |
|---|---|---|---|
| `fetch_margin` 命中路径新增 `set_gauge` | `market_api` | 新增调用是否会抛异常破坏命中返回？ | 否——`cache_entries` 已注册、`key` 合法，`set_gauge` 守卫仅 `return`、不抛（`metrics.py:100-131`） |
| `cache_entries` 字典被 margin 写入 | `metrics` / 各域缓存 | 会不会清空或覆盖 `url`/`feed`/`sector` 等既有标签？ | 否——labelled 合并 `cur[key]=value`（BR-MET-4）；无无 key 写入 |
| 命中路径返回值 | 调用方 `handle_margin`→`server._send_json_shape` | 新增指标后返回语义是否变化？ | 否——仍返回同一 `cached` 对象，`server` 只序列化（BR-MKT-16 未受影响） |
| `tests/test_data_layer.py` 计数 | 测试套件 | 新增用例是否影响其他用例断言？ | 否——独立用例，setUp/tearDown 隔离；仅计数 525→526（文档待同步） |

### Dim 0 / Dim 4 / Dim 5 / Dim 6
本 change-set 无对外契约、无安全面、无前端/小程序变更 ⇒ 不适用（沿用上一轮结论；Dim 0 内部契约偏差见 `## 漂移检测`）。

## 五、修复建议（按优先级）

1. **CR-07（建议，P2）**：强化 `test_terminal_cache_publishes_cache_entries_gauge` 命中分支——在写入与命中之间改变真实长度（注入第二条目或置脏 gauge），使删除 `market_api.py:96` 时断言失败。淘汰分支保留。
2. **CR-08（无需动作，P2）**：维持现状，与 `stock_api._cache_store` 口径一致；如需强一致再评估版本号方案。
3. 其余三处改动**无需修改**。

## 漂移检测

> 说明：`doc/detailed/market_api.md`、`doc/detailed/metrics.md` 的本轮同步由 P7b-r7 并行进行；下列为**残留差异**，按指示**不判为代码错误**。

**D1 契约核对**
- ✅ `market_api.md` §7（:391-392）已声明「`metrics.incr/set_gauge` … 调用点均在**锁外**」「`_margin_cache_lock` 为最外层且不嵌套」——与本轮两条锁外 `set_gauge` **一致**，无需更正。
- ⚠️ **差异 1**：`market_api.md` 全文**未记载** `cache_entries{margin}` 的发布（写入路径 `:127` 与命中路径 `:96` 两处，对齐 BR-SA-26 / AC-S10）。建议 P7b-r7 在 §2.1 流程 / §7 并发安全 / §8 用例表中补登（新增 gauge 发布点 + 对应用例）。
- ⚠️ **差异 2**：`metrics.md` §3.2 注册表（:109）`cache_entries` 的标签列 = `url`/`feed`/`quote`/`fundflow`/`timeline`/`f10`/`announcement`/`longhu`/`sector`——**缺 `margin`**。建议补 `margin`。（§2.6 示例 `{url, feed}` 为节选，可选补注。）

**D2 DOC_SYNC 追溯**
- 上一轮 CR-02（写路径未发布 `cache_entries{margin}`）→ 代码已修复（`:127`），本轮新增命中路径发布（`:96`）；对应文档同步尚未见（＝差异 1）。
- 上一轮 CR-04（docstring 过时）→ 代码已更正（`:5-8`）；若 `market_api.md` 无对应引用句则无需同步。

**D3 规范合规**
- ✅ 无裸 TTL/裸上限字面量（新增代码不含 `600`/`8`）；锁外发布符合 S1-4；labelled 写法符合 BR-MET-4 / BR-MET-12；`market_api` 未 import `stock_api`（层隔离）。

**D4 漂移结论**
- ⚠️ **有残留差异 3 项**：
  1. `market_api.md` 缺 `cache_entries{margin}` 发布记载（写 + 命中两处）；
  2. `metrics.md` §3.2 标签列缺 `margin`；
  3. 用例计数 **525 → 526** 未同步（`market_api.md` v1.8 变更行 / §11、`metrics.md` v1.10 变更行均记 525）。
- 无其它漂移。

---

- **本轮结论**：✅ 允许合并（无 P0 / 无 P1；CR-07、CR-08 均为 P2，不阻断）。
- **建议后续**：CR-07 反例补强可随 P7b-r7 之后的收尾一并落地；CR-08 维持现状。

