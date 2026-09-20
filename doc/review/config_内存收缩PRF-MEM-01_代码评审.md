# config `DOMAIN_MATRIX` 内存收缩（PRF-MEM-01）代码评审

> 模式：P5b 代码质量门禁 + P7a 契约漂移检测（`>>MODE: review+drift`）
> 变更范围：`modules=config`；文件 `china_finance_rss/config.py`、`tests/test_config.py`
> 评审依据：预取 diff + `SIDE-EFFECT` 声明 + `doc/detailed/config.md` / `doc/detailed/stock_api.md` / `doc/arch/SAD.md` / `doc/prd/perf-stability-optimization.md` + 存量代码 `config.py` / `stock_api.py` / `stream.py`
> 报告日期：2026-09-20

## 评审结论

**✅ 通过（P0 = 0 / P1 = 0 / P2 = 4）**。改动是纯配置数值收缩，`_resolve_pool_max` 的 `'fixed:<n>'` 解析正确，对外端点响应零变化；主要问题是**测试断言未随新值补齐**、**池淘汰的 O(n log n) 持锁路径被首次激活**，以及契约文档的大面积数值漂移（预期内，由 P7b 同步）。

### P0 / P1 清单

- 无 P0。
- 无 P1。

### P2 清单

| # | 等级 | 位置 | 摘要 |
|---|------|------|------|
| CR-MEM-01 | P2 | `tests/test_config.py:65-72` | 新值仅 `quote.cache_max` 被钉死，另 5 个变更值无断言 |
| CR-MEM-02 | P2 | `china_finance_rss/config.py:344-345` + `stock_api.py:511-517` | `pool_max < MAX_DEDUP_CODES` 首次激活“持锁 O(n log n) 池淘汰”分支 |
| CR-MEM-03 | P2 | `china_finance_rss/config.py:342/344/345` | terminal cache 收缩可能降低 stream 分片 `cached_batch` 命中（逆向项，`_last_known` 兜底，不破坏功能） |
| CR-MEM-04 | P2 | `china_finance_rss/config.py:340` | 超长单行内嵌注释且 `PRF-MEM-01` 未在任何契约/需求文档登记 |

---

## 变更范围与受影响点（供编排器映射 tester `>>SCOPE:`）

入参携带 `>>SIDE-EFFECT: DOMAIN_MATRIX 数值变化 → cache_policy('quote'/'fundflow'/'timeline') 的 pool_max/cache_max 降低 → stock_api 终端缓存容量与 prefetch 保活范围随之收缩`。逐点逆向核对如下：

| # | 受影响点（文件:行） | 所属模块 | 行为变化 | 逆向假设与结论 |
|---|---------------------|----------|----------|----------------|
| 1 | `config.py:342` quote | config | `pool_max 2000→1000`，`cache_max 2000→1000` | quote **无 prefetch loop**（见 SAD §1 链路 C：4 条 loop = fundflow/timeline/f10/announcement），故 pool 收缩只减一个 `code→ts` dict 的成员数，无保活语义变化。**不成立**（无功能影响） |
| 2 | `config.py:344` fundflow | config | `pool_max 2000→1000`，`cache_max 2000→1000` | fundflow 有 prefetch loop。当活跃 distinct 码 > 1000 时，prefetch 轮转面收敛到 1000，超出部分失去保活 → 首次访问回源（非错误）。**成立但仅影响时延，不影响正确性** |
| 3 | `config.py:345` timeline | config | `pool_max 2000→500`，`cache_max 2000→500` | 同 #2；且 `cache_max=500` 使 stream `cached_batch('timeline', …)`（`stock_api.py:341`）对未刷新片的命中面收窄。**成立，见 CR-MEM-02/03** |
| 4 | `stock_api.py:511-517` 池淘汰 | stock_api（消费方） | 条件 `len(pool) > pool_max` 由“恒假”转为“可频繁为真” | **成立，见 CR-MEM-02** |
| 5 | `stream.py` 分片补帧（`cached_batch` 消费方） | stream | 未刷新片 stale 来源减少 | **成立，见 CR-MEM-03**（`_last_known` 结转兜底） |

> 结论：无任何**对外**端点行为/响应的意外改变。所有行为变化均限于进程内缓存容量与后台预热面。

---

## Dim 0 — 契约一致性

单模块改动，无 OpenAPI 面（无可对照的详设 §3 OpenAPI）。契约核对见文末 **## 漂移检测**。

## Dim 1 — 数据与正确性

**复核项：`_resolve_pool_max` 的 `'fixed:<n>'` 解析**

- `config.py:443-451`：`'n/a'→None`、`'dedup'→MAX_DEDUP_CODES`、`'fixed:<n>'→int(n)`。`'fixed:1000'` / `'fixed:1000'` / `'fixed:500'` 分别解析为 `1000/1000/500`，与矩阵第 5 列 `cache_max` 一致。
- `'dedup'` 分支只作用于**未改动**的 `depth`（343）/`announcement`（349）/`f10`（352），返回值仍为 `MAX_DEDUP_CODES=2000`。`tests/test_config.py:61-69` 对 depth/f10 的断言继续成立。
- `'n/a'` 分支只作用于 `news_url`（347）/`longhu`（350），未受影响。

**✅ 无问题。** 原 Bug 风险（`'fixed:'` 解析错值）不存在。

## Dim 2 — 并发

`_process_chunk` 的池淘汰（`stock_api.py:511-517`）在 `with lock` 内执行 `sorted(pool, key=pool.get)`。本次改动把该分支从“设计上不可达”变为“>cap 负载下每 chunk 可达”——属并发持锁时长问题，归入 CR-MEM-02（Dim 3）。

## Dim 3 — 资源与性能

**【P2】CR-MEM-02** `china_finance_rss/config.py:344-345`（`fundflow`/`timeline` 的 pool_max 降到 1000/500）+ `stock_api.py:511-517`：
当活跃 distinct 码数超过 `pool_max`（timeline=500，理论上限 `MAX_DEDUP_CODES=2000`）时，`_process_chunk` 的**每一个 chunk** 都会命中 `len(pool) > pool_max`，在**持域锁**状态下对约 500–1050 条 `code→ts` 执行 `sorted(pool, key=pool.get)` 并逐条删除。改动前 `pool_max == MAX_DEDUP_CODES == 活跃码硬上界`，该条件**恒为假**（`stock_api.md:1584` 与 SAD §2.2 均以“仅在 `len(pool) > pool_max` 时触发（2000 条量级、低频）”为前提）。
后果：域锁临界区从“几乎不触发”变为“高频触发”，增大域锁争用与单 chunk 尾部时延；**不改变结果正确性**（池淘汰与 terminal cache 已解耦，`stock_api.py` P1-1）。
修复方向（择一）：① 将淘汰改为无排序的 O(n)（如循环 `min(pool, key=pool.get)` 删除 `len-cap` 次，或复用 `OrderedDict` 真 LRU）；② 若确认 `pool_max` 应与活跃码硬上界解耦，则在契约中显式改写“池上限 = MAX_DEDUP_CODES”的旧论证与“低频”假设。

**【P2】CR-MEM-03** `china_finance_rss/config.py:342/344/345`（terminal `cache_max` 收缩）：
`stock_api.cached_batch(domain, codes)`（`stock_api.py:341-371`）只从 terminal cache 读取，被 stream 用于填充“本 tick 未刷新片”。当活跃 distinct 码数 > `cache_max`（timeline 500 / quote 1000）时，未刷新片的 cache 命中面收窄，`stale`（历史值）来源更多依赖 `stream._last_known` 结转（BUG-P6C-08）。
证据链：`cached_batch` 命中要求条目未过期且在 cache 内；LRU 淘汰后即 miss。逆向假设“cache_max < 活跃码集会增大 stale/missing 抖动”——**在 >cap 负载下成立**；若 PRF-MEM-01 的容量模型未覆盖该场景，建议在契约同步时补一条“`cache_max` 与预期活跃码集”的容量约束，并由 tester 在 >cap 场景做定向回归（`>>SCOPE:` stream 分片补帧 / `stale` 覆盖）。功能不破坏，故 P2。

## Dim 4 — 安全

无安全面变更（纯数值收缩，无输入/鉴权/越权路径）。✅

## Dim 5 — 结构与可维护性

**【P2】CR-MEM-04** `china_finance_rss/config.py:340`：单行内嵌超长中文注释（含 RSS/百分比/字节量级度量），与相邻注释块风格不一致；且标识 `PRF-MEM-01` 在 `doc/prd/`、`doc/arch/SAD.md`、`doc/detailed/*` 全文 **0 命中**，属未登记的需求锚点（见漂移节 D2）。建议删除或改写为简短说明，并把改动依据落到契约层。

## 逆向审查小结

- **恶意输入**：`_resolve_pool_max` 对非 `fixed:` 前缀字符串抛 `ValueError`（启动期暴露），矩阵为静态字面量，无外部输入。✅
- **边界值**：`cache_max` 最小 500 远大于单批 `_MAX_BATCH_SIZE=50`，单请求写入不会被自身淘汰；`pool_refresh >= ttl` 不变式不受影响（`_trading_tiers` 未动）。✅
- **性能悬崖**：见 CR-MEM-02（持锁排序）——唯一被本次改动“从休眠转为活跃”的路径。
- **测试盲区**：见 CR-MEM-01。
- **依赖失效/隐式假设**：SAD §2.2 / `stock_api.md:457` BR-SA-13 的隐式假设“`pool_max` 与 `MAX_DEDUP_CODES` 同源即可不触发清理”已被本次改动推翻，属契约层待同步项（漂移节）。

---

## 修复建议（按优先级）

| 等级 | 建议 | 负责方 |
|------|------|--------|
| P2 | `tests/test_config.py` 补断言：`quote.pool_max==1000`、`fundflow.pool_max==1000`、`fundflow.cache_max==1000`、`timeline.pool_max==500`、`timeline.cache_max==500`（`depth` 断言保持不动，正确） | code-developer |
| P2 | 评估 `stock_api.py:511-517` 池淘汰是否为 >cap 负载做无排序改造；或在契约中改写旧“低频”论证 | code-developer / 编排层 |
| P2 | 契约同步（见漂移节 D4） | task-decomposer（P7b） |
| P2 | 清理 `config.py:340` 超长注释，将依据落到契约层 | code-developer |

> `depth` 断言（`test_config.py:61-63`）**保持不动是正确的**：`depth` 仍为 `'dedup'`，`pool_max == MAX_DEDUP_CODES` 成立。

---

## 漂移检测

### D1 契约核对（以代码为基准，逐格）

**`doc/detailed/config.md`**

| 位置 | 文档现值 | 代码现值 | 漂移 |
|------|----------|----------|------|
| §3.1 DOMAIN_MATRIX L289 `quote` | `['L0',1.0,1.0,'dedup',2000]` | `['L0',1.0,1.0,'fixed:1000',1000]` | ⚠️ 是 |
| §3.1 L291 `fundflow` | `['L1',1.0,1.0,'dedup',2000]` | `['L1',1.0,1.0,'fixed:1000',1000]` | ⚠️ 是 |
| §3.1 L292 `timeline` | `['L1',1.0,1.0,'dedup',2000]` | `['L1',1.0,1.0,'fixed:500',500]` | ⚠️ 是 |
| §3.2 实值表 L320 `quote` | `pool_max 2000, cache_max 2000` | `1000 / 1000` | ⚠️ 是 |
| §3.2 实值表 L322 `fundflow` | `pool_max 2000, cache_max 2000` | `1000 / 1000` | ⚠️ 是 |
| §3.2 实值表 L323 `timeline` | `pool_max 2000, cache_max 2000` | `500 / 500` | ⚠️ 是 |
| §2.4 L168/L178 `_BASIC_INFO_MAX_POOL` | `cache_policy('quote')['pool_max'] = 2000`（含“4× 行为变更”登记） | `1000` | ⚠️ 是（登记需重写） |
| §10 L598 | `URL 缓存上限 quote.cache_max=2000` | `quote.cache_max=1000` | ⚠️ 是（且该行把 terminal cache 误称 URL cache，建议一并订正） |
| BR-CFG-4（L371）/ BR-CFG-19 / CFG-T13 / CFG-T15 | `'dedup'→2000` 规则、depth/sector 数值 | 未变 | ✅ 无漂移 |

**`doc/detailed/stock_api.md`**

| 位置 | 文档现值 | 代码现值 | 漂移 |
|------|----------|----------|------|
| §5.x L372 | `上限: policy['pool_max']  # quote/fundflow/timeline/f10/announcement = 2000 (= MAX_DEDUP_CODES)` | quote/fundflow=1000, timeline=500, f10/announcement=2000 | ⚠️ 是 |
| §3.5 L404 `quote` | `pool_max 2000, cache_max 2000` | `1000 / 1000` | ⚠️ 是 |
| §3.5 L406 `fundflow` | `pool_max 2000, cache_max 2000` | `1000 / 1000` | ⚠️ 是 |
| §3.5 L407 `timeline` | `pool_max 2000, cache_max 2000` | `500 / 500` | ⚠️ 是 |
| BR-SA-13（L457） | “上限 = `policy['pool_max']`（L1/L3 域 = `MAX_DEDUP_CODES=2000`），与 `MAX_DEDUP_CODES` 同源” | 实时域已与 `MAX_DEDUP_CODES` **解耦** | ⚠️ 是（设计论证需改写） |

**`doc/arch/SAD.md`**

| 位置 | 文档现值 | 代码现值 | 漂移 |
|------|----------|----------|------|
| §2.1 示例（L173-175） | `quote pool_max:2000 cache_max:2000`；`fundflow/timeline` 同 | 1000/1000；500/500 | ⚠️ 是 |
| §2.6 计分板示例（L678） | `"pool_max":2000,"cache_max":2000` | 同上 | ⚠️ 是 |
| §2.2（L235） | “池上限 = `cache_policy(d)['pool_max']`（实时域 L0/L1 = `MAX_DEDUP_CODES=2000`，与去重码硬上界**同源**）” | 实时域已解耦，同源论证失效 | ⚠️ 是（**设计不变量级**漂移） |
| §4.3 内存分项（L932） | “L1 端点数据缓存（**3 域** quote/fundflow/timeline × **2000** × ~8KB ≈ **48MB**）” | 实际容量 1000+1000+500 | ⚠️ 是（内存总账须重算；与 PRF-MEM-01 目标 RSS 1.1GiB→0.65GiB 联动） |

**`doc/prd/perf-stability-optimization.md`**：无逐值锚点。AC-E6 约束的是 `cache.MAX_CACHE_SIZE=2000`（URL 缓存），**不受本次 terminal cache 收缩影响**；AC-S9 只给内存上界，本次为收紧方向。✅ 无字面漂移。（但 PRF-MEM-01 本身未在 PRD/SAD 落号，见 D2。）

### D2 DOC_SYNC 追溯

- 本轮入参**未携带** `>>DOC_SYNC:` 标记（仅 `>>SIDE-EFFECT:`），无可追溯的同步声明。
- `PRF-MEM-01` 在 `doc/prd/`、`doc/arch/SAD.md`、`doc/detailed/*` 中 **0 命中**——改动依据目前只存在于 `config.py:340` 代码注释，**需求/架构锚点缺失**。建议 P7b 同步时补登记（PRD 资源条目或 SAD 内存总账联动 AC-S9），否则本改动无契约可追溯。

### D3 规范合规

- `config.py:340` 注释超长且内嵌度量数字（CR-MEM-04）。
- 测试断言未随值更新（CR-MEM-01）。
- 其余符合 `code-discipline.md`（手术式修改，仅动目标数值）。

### D4 漂移节结论

**⚠️ 有漂移**（预期内，本报告不判代码错误）。共 **3 份详设/架构文档、14 处数值/论证** 待 P7b（task-decomposer）按上表同步：

1. `config.md` §3.1 / §3.2 / §2.4 / §10 —— 6 处数值 + 1 处登记重写 + 1 处“URL cache”误称订正；
2. `stock_api.md` §3.5 / §5.x / BR-SA-13 —— 3 处数值 + 1 处池上限论证改写；
3. `SAD.md` §2.1 / §2.6 / §2.2 / §4.3 —— 2 处示例 + 1 处设计不变量 + 1 处内存分项重算。

> 编排器若判定本改动属“行为变更”，还须按流程登记到 PRD/SAD 并触发 AC-S9 内存总账重标（当前 `.env`/部署侧无相关变更）。
