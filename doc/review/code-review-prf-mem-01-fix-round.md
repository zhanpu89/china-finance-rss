# PRF-MEM-01 修复轮（P5b-r1）代码评审

> **模式**：`>>MODE: review+drift`（P5b 代码门禁 + P7a 漂移检测合并）
> **变更范围**：`modules=config`；文件 `china_finance_rss/config.py`、`tests/test_config.py`、`tests/test_data_layer.py`
> **修复目标**：CR-02（3 域 `pool_max` 恢复 env 可调）/ CR-03（CFG-T19 落测）/ CR-04（`cache_max` 有界降级锁定）/ CR-05（注释事实更正）
> **评审依据**：预取 diff + `>>SIDE-EFFECT:` + `.opencode/project/conventions.md` + `doc/detailed/config.md` / `stock_api.md` / `doc/arch/SAD.md` + 存量 `config.py` / `stock_api.py` / `stream.py`
> **日期**：2026-09-20
> **说明**：本环境无 shell，未执行测试；结论基于静态核对（含消费方调用路径逐点核对）。

## 评审结论

**✅ 通过（P0 = 0 / P1 = 0 / P2 = 7）**。四项修复目标均达成：`pool_max` 经 `'env:<NAME>'` 恢复为部署可调、CFG-T19 落测、CR-04 有界降级有单元锁定、CR-05 的 4s/8s/120s 事实已更正（独立核对 `_prefetch_loop` 与 `_trading_tiers` 属实）。无功能缺陷、无数值解析错误、无对外端点变化。剩余问题集中在**测试锁定的严密性**（默认值未被钉死、fail-fast 分支未测）、**白名单可维护性**、**调用期 `globals()` 引发的测试层越界**，以及**契约文档表示法漂移**（预期内，P7b-r1 并行）。

> **未在本轮范围**：CR-01（内存目标无护栏）、CR-06（`depth` 池未收缩）未列入修复目标，仍为开放项，本报告不重复评判。

## 问题清单（P0/P1/P2 逐条）

### P0 清单

- 无 P0。

### P1 清单

- 无 P1。

### P2 清单

- 【P2】`china_finance_rss/config.py:333,469-470`：`_POOL_MAX_ENVS` 用字面量**重复** 3 个常量名，且无导入期自校验。若后续新增域写成 `'env:MAX_X_POOL'` 而漏登记白名单，`ValueError` 只在**首次 `cache_policy(该域)` 调用时**抛出（`cache_policy` 不在导入期调用），与 `config.md §6`「矩阵 spec 非法 ⇒ **启动期**即暴露」不符——检测被推迟到运行期首个请求，且可能因域冷门而长期潜伏。建议把白名单改为 `{'MAX_QUOTE_POOL': MAX_QUOTE_POOL, ...}` 映射（键即唯一合法名单，杜绝名单/常量双份），或在导入期遍历 `DOMAIN_MATRIX` 校验全部 `pool_max` spec。

- 【P2】`tests/test_config.py:80-82`：CFG-T19 的 3 个 `pool_max` 期望值引用 `config.MAX_QUOTE_POOL / MAX_FUNDFLOW_POOL / MAX_TIMELINE_POOL`，对默认字面量是**同义反复**——把 `MAX_QUOTE_POOL` 默认从 `'1000'` 改成 `'800'`，测试仍全绿，而 `config.md`/SAD 契约仍写 1000。`cache_max` 3 值（1000/1000/500）已钉死，`pool_max` 3 值**未钉死**。CR-03 的「六值」应真正落 6 个字面量：建议在 `test_env_defaults`（`:150`）补 `assertEqual(config.MAX_QUOTE_POOL, 1000)` 等 3 条。
  - 备注（为何判 P2 而非 P1）：CR-03 的核心风险是「spec 回滚（如 timeline 写回 `'dedup'`）CI 全绿」——该风险**已被覆盖**（spec 回滚会使 `pool_max != config.MAX_TIMELINE_POOL` 而失败）；残留的仅是「默认字面量被改」这一类较窄回归，故降为 P2。

- 【P2】`china_finance_rss/config.py:469-470`：新增的**唯一错误分支** `bad pool_max env name` 无任何测试覆盖（`tests/` 全文无 `_resolve_pool_max` / `'env:` / `bad pool_max` 命中）。`'env:NOPE'`、`'env:'` 应 `ValueError` fail-fast 属新契约，建议补 `assertRaises(ValueError)`（可直测 `config._resolve_pool_max('env:NOPE')`）。

- 【P2】`tests/test_data_layer.py:396-414`：CR-04 的降级测试只验证 `_cache_store` 在独立 `OrderedDict` 上「有界 + 淘汰最旧 + 最新值保留」，与既有 `test_cache_true_lru_eviction`（`:385-394`）高度重叠，且**未触及 CR-04 的真实后果面**：`stream._refresh_pool`（`stream.py:478-487`）C2 分片把「非本拍切片码」交给 `stock_api.cached_batch(domain, rest)`（`stock_api.py:341-371`，仅读终态缓存、不发网络）；当活跃码 > `cache_max`（quote 1000 / timeline 500）时这些码持续 miss ⇒ 帧字段缺失、退化为 `_last_known` 结转。该路径无定向回归锁定，亦无 `cache_hit_ratio` 护栏（CR-04 修复方向原要求）。降级本身是**有界、非崩溃**的（`snapshot.setdefault`，见 `stream.py:486`），故不构成功能缺陷；但「锁定 LRU 有界降级」的断言强度低于目标。建议补 stream 级 >cap 用例（活跃码 > `cache_max` 时帧不崩、miss 码降级为结转/回源）。

- 【P2】`china_finance_rss/config.py:467-471` + `tests/test_config.py:85-92`：`cache_policy` 现经 `globals()[name]` **调用期**读模块常量，使其可被运行期重绑定观测（新测试正是靠 `config.MAX_TIMELINE_POOL = 400` 证明联动）。这与 BR-CFG-10「env 常量运行期只读（禁止原地修改）」在测试层形成张力——测试把「可热替换」固化为契约。风险低（CPython 全局读为原子操作、无撕裂；生产路径不改），但建议按项目约定改用 `mock.patch.object(config, 'MAX_TIMELINE_POOL', 400)`（`conventions.md` 测试约定 / `config.md §7` 明确推荐），避免手工赋值/还原。
  - **合规判定（评审重点 2）**：**不违反 BR-CFG-16** —— 全仓无 `config.py` 之外的 `os.getenv`；env 值仍在导入期求值冻结，`_resolve_pool_max` 读的是**常量**而非 env，只是「查询时点」在调用期。也不违反 §2.7「仅 `CDP_STOCK_PAGES` 调用期读取」的字面（该条限制的是 env 读取，非常量绑定查找）。**结论：合规**。
  - **安全性（评审重点 1）**：`globals()` 白名单**足以阻断任意全局读取/注入** —— `name` 先经 `_POOL_MAX_ENVS` 先验约束（仅 3 个 int 常量名），`__builtins__`/任意全局均不可达；未知名直接 `ValueError`。**无安全面**。

- 【P2】`china_finance_rss/config.py:328-329,357-360`：本轮把 `pool_max` 恢复为 env 可调，但 `cache_max`（1000/1000/500，本轮目标的**真实内存硬界**）仍是矩阵整数字面量、**无 env 入口**。`config.md §1.1#5`「所有 IO 预算 / 资源上限经 `os.getenv` 注册」因此只被**部分**满足。此为 PRF-MEM-01 之前就存在的既有模式（所有域 `cache_max` 均为字面量，非本轮引入）；是否扩展 env 覆盖由编排层/架构决定，本报告不阻断，登记为漂移配套项。

- 【P2】`china_finance_rss/config.py:351-355`：CR-05 事实更正**正确**（独立核对：`_prefetch_loop` 间隔确为 `sleep(cache_policy(domain)['pool_refresh'])`，`stock_api.py:1333`；`pool_refresh = int(round(ttl × factor))`，`config.py:484`；盘中 L0=4 / L1=8、非盘 L0/L1=120，`_trading_tiers` ⇒ quote/depth 4s、fundflow/timeline 8s、非盘 120s 均属实）。余两点：① **quote/depth 没有 `_prefetch_loop`**（仅 fundflow/timeline/f10/announcement，`server.py:1720-1723`），其保活来自 SSE 计划刷新；把 quote/depth 括注于「prefetch」之下不精确，建议改述为「prefetch / SSE 计划刷新」。② 原 CR-05 还要求把未验证的 RSS 预测移出代码，现仍保留（已标注「估算值，待重建部署后实测复核」，可接受）。

## SIDE-EFFECT 逆向核查（修复副作用）

> 修复轮最危险的是「修好一个引入另一个」。入参 `>>SIDE-EFFECT:` 4 条逐条逆向核对结论：

| # | 声明 | 逆向假设 | 结论 |
|---|------|----------|------|
| 1 | `_resolve_pool_max` 新增 `'env:<NAME>'`；未知 NAME 抛错；既有 spec 不变 | 翻转后相邻分支（`'fixed:'` / `'dedup'` / `'n/a'`）是否仍自洽？ | **成立**：`fixed:` 分支在 `env:` 之前判断，互不干扰；`'n/a'`/`'dedup'` 返回值不变（`depth/announcement/f10/news_url/longhu` 未动）。既有调用方（`_materialize` 唯一调用点）签名不变。 |
| 2 | 3 域 `pool_max` 改 `'env:MAX_*_POOL'`：默认值不变，改为**调用期**读常量（运行期热替换即改变输出） | 哪个既有调用方依赖「池上限恒为导入期常量」？ | **无依赖**：消费方 `stock_api._process_chunk` / `_depth_store` 每次调用 `cache_policy` 取新 dict，从不缓存 policy（`grep cache_policy(` 全为按次调用）。默认值 1000/1000/500 与改前 `'fixed:1000'/'fixed:1000'/'fixed:500'` 逐值相等 ⇒ 行为等价。**唯一新增语义**即「热替换可观测」，见 P2（测试层越界）。 |
| 3 | 矩阵头注释：纯注释，更正 prefetch 间隔 | 是否会误导容量判断？ | **更正正确**（见 P2 第 7 条），唯一不精确为「quote/depth」归类。 |
| 4 | tests：仅新增用例 | 新用例是否污染全局状态？ | **成立**：`test_prf_mem_01_pool_cache_contract` 只读；`test_prf_mem_01_pool_cap_follows_env` 用 `try/finally` 还原；`test_prf_mem_01_cache_degrade_is_lru_bounded` 位于 `BatchPipelineTests`，`setUp/tearDown` 调 `_reset_stock_state()`（含 `metrics.reset()`）与 `config.DOMAIN_MATRIX` 无写。 |

**未发现 code-developer 漏报/失真的 SIDE-EFFECT**；其声明 2 主动披露了调用期读取语义，与本报告独立核对一致。

## 变更范围与受影响点（供编排器映射 tester `>>SCOPE:`）

| # | 受影响点（文件:行） | 所属模块 | 行为变化 | 逆向结论 |
|---|---------------------|----------|----------|----------|
| 1 | `config.py:330-333`（新 env 常量 + 白名单） | config | 新增 3 个 env 注册项 | P2（白名单可维护性 / fail-fast 时点） |
| 2 | `config.py:458-472`（`_resolve_pool_max`） | config | 新增 `'env:<NAME>'` 分支，调用期 `globals()` 读常量 | P2（测试锁定 / mock 约定） |
| 3 | `config.py:357-360`（3 域矩阵行） | config→stock_api→stream | 池上限改为常量绑定；值不变 | 无功能回归（默认等价） |
| 4 | `stock_api._process_chunk` / `_prefetch_loop` / `cached_batch` | stock_api→stream | 池/缓存上限仍按 policy 消费 | P2（CR-04 系统级 >cap 回归未覆盖） |
| 5 | `tests/test_config.py:74-92`、`tests/test_data_layer.py:396-414` | tests | 新增门禁 | P2（默认值未钉死、fail-fast 未测） |

## Dim 0 — 契约一致性

单模块改动，无 OpenAPI 面（`doc/detailed/` 下无本模块接口契约可对照）。数值契约核对：`cache_max` 1000/1000/500 与 `config.md §3.2` / `stock_api.md §3.5` 逐值一致 ✅；`pool_max` 数值默认（1000/1000/500）一致，但**表示法**由 `'fixed:N'` 变为 `'env:<NAME>'` ⇒ 文档漂移（见 `## 漂移检测`，不判代码错误）。

## Dim 1 — 数据与正确性

- `_resolve_pool_max` 四分支解析正确：`'n/a'`→`None`、`'dedup'`→`MAX_DEDUP_CODES`、`'fixed:<n>'`→`int(n)`、`'env:<NAME>'`→白名单常量 `int(globals()[name])`。未见错值/静默兜底；未知 spec 仍 `ValueError`。
- `depth/announcement/f10` 的 `'dedup'` 分支未受影响，`test_l0_is_the_fastest_tier:62-63` 继续成立。
- 魔法值：新 env 默认值以 `os.getenv(..., '1000'/'500')` 注册，符合「配置不硬编码」；`cache_max` 字面量见 P2。

## Dim 2 — 并发

`cache_policy` 现读 `globals()[name]`——CPython 下模块字典取值原子，无撕裂；生产不改常量，等价纯函数。但「运行期热替换即可见」与 BR-CFG-10「运行期只读」在测试层形成张力（P2）。无新增锁，无锁序变化。

## Dim 3 — 资源与性能

- `pool_max` 现已 env 可调，运维可**免改码**调参，达成 CR-02 目标。
- **性能悬崖（既有，非本轮新增）**：`pool_max < 活跃码上界` 使 `stock_api.py:515-517` 的「持锁 `sorted(pool, key=pool.get)`」由恒假转为可高频触发（上轮 CR-MEM-02 / 盲审已登记）。本轮未改该路径；`pool_max` 从字面量变常量不改变触发条件。仍建议按 CR-MEM-02 评估无排序淘汰。
- **`cache_max` 跌破活跃上界**：C2 `rest` 分支 `cached_batch` miss 面收窄（CR-04），有界降级、非崩溃；系统级回归未覆盖（P2）。

## Dim 4 — 安全

无安全面变更：无输入/鉴权/越权路径；`globals()` 白名单先验约束 `name`，无任意属性/全局读取面。✅

## Dim 5 — 结构与可维护性

- 命名/位置/注册符合 `conventions.md` 配置管理节（`'env:<NAME>'` + `globals()` 白名单 + 未知名 fail-fast）——**约定已先行记录该模式，代码与镜像一致**。
- 双份名单（3 常量 vs `_POOL_MAX_ENVS`）是可维护性熵源（P2）。
- 测试手工赋值而非 `mock.patch.object`（P2）。

## Dim 6 — 前端

无前端变更，不适用。

## 漂移检测（P7a）

> 本节为 P7b-r1（并行进行）的待同步清单；**按编排层约定不判代码错误**。

### D1 契约核对

**`doc/detailed/config.md`（v1.8，仍写 `'fixed:N'`、声称 env 零变更）**

| 位置 | 文档现值 | 代码现值 | 漂移 |
|------|----------|----------|------|
| §3.1 L290 `quote` | `'fixed:1000', 1000` | `'env:MAX_QUOTE_POOL', 1000` | ⚠️ 是 |
| §3.1 L292 `fundflow` | `'fixed:1000', 1000` | `'env:MAX_FUNDFLOW_POOL', 1000` | ⚠️ 是 |
| §3.1 L293 `timeline` | `'fixed:500', 500` | `'env:MAX_TIMELINE_POOL', 500` | ⚠️ 是 |
| §3.2 L321/L323/L324 实值表 | `pool_max: 1000/1000/500` | 数值同（来源改为 env 常量） | ⚠️ 表示法 |
| 头部 v1.8 L4 | 「**接口 / 键集合 / env 零变更**」 | 新增 3 个 env、新增 `'env:<NAME>'` spec | ⚠️ 是（陈述失真） |
| §2.3 / §2.7 env 注册表 | 无 `MAX_QUOTE_POOL/MAX_FUNDFLOW_POOL/MAX_TIMELINE_POOL` | 已注册（`config.py:330-332`） | ⚠️ 是 |
| §1.1#5 / BR-CFG-16 | env 注册中心完整性 | 3 个新 env 未登记 | ⚠️ 是 |
| §4 BR-CFG-4 | 仅 `'dedup'`/`'fixed:<n>'`/`'n/a'` | 新增 `'env:<NAME>'` | ⚠️ 是 |
| §5 伪代码 L515-520 `_resolve_pool_max` | 无 `env:` 分支 | 有 | ⚠️ 是 |
| §6 错误处理 | 「矩阵 spec 非法 ⇒ **启动期**即暴露」 | `env:` 未知名的 `ValueError` 在**调用期** | ⚠️ 是（措辞，见 P2 第 1 条） |
| §8 CFG-T18 | `grep os.getenv` 名集 == §2.7 清单 | 差 3 项（若该测试落地会失败） | ⚠️ 是 |
| §8 CFG-T19 | `quote.pool_max==1000` 等 6 值 | 数值同；默认字面量未被测试钉死 | ⚠️ 部分 |

**`doc/detailed/stock_api.md`（v1.6）**：§3.3 L373 / §3.5 L405-408 / BR-SA-13（L460）仍写 `'fixed:1000'/'fixed:1000'/'fixed:500` 与「不再等于 `MAX_DEDUP_CODES`」——**行为不受影响**（仅消费 `policy['pool_max']`），属**表示法漂移**。

**`doc/arch/SAD.md`（v1.14）**：§2.1 L161/163/164 `'fixed:1000'/'fixed:1000'/'fixed:500'`；§2.2 L238/L927「`pool_max` 按域声明（`'dedup'`/`'fixed:N'`）」；§9.14 变更表 L1891-1893/1902 同；env 清单未含 3 新 env。数值口径（1000/1000/500、内存总账 ≈58MB、RSS ≈0.65GiB）**不变**，仅 spec 表示法与 env 清单需补。

**`.opencode/project/conventions.md`**：配置管理节（L30）已记录「`'env:<NAME>'` spec + `_resolve_pool_max` 调用期经 `globals()` 白名单解析 + 未知名 fail-fast」——**与代码一致，无漂移**（镜像先行，详设落后）。

### D2 DOC_SYNC 追溯

- 本轮入参**未携带** `>>DOC_SYNC:` 标记（仅 `>>SIDE-EFFECT:`），无可追溯声明；`PRF-MEM-01` 现已在 `config.md §10#24` / `SAD.md v1.14` 登记，CR-01 的「需求锚点缺失」已由上一轮文档同步闭环。
- 待 P7b-r1 同步目标：`config.md`（§1.1#5 / §2.3 / §2.7 / §3.1 / §3.2 / §4 BR-CFG-4 / §5 / §6 / §8 CFG-T18·T19 / §10）、`stock_api.md`（§3.3 / §3.5 / BR-SA-13）、`SAD.md`（§2.1 / §2.2 / §9.14 + env 清单）、`_PROGRESS.md`。

### D3 规范合规

- 代码符合 `code-discipline.md`（手术式修改）与 `conventions.md` 配置管理；无越界改文档。
- 测试偏离 `conventions.md` 测试约定（应 `mock.patch('china_finance_rss.<module>.<symbol>')`）——P2 第 5 条。

### D4 漂移节结论

**⚠️ 有漂移（预期内）**：3 份文档、约 14 处表示法/env 清单待同步。**数值契约（1000/1000/500）零漂移**，`cache_policy` 签名 / 键集合 / 其余 9 域零变更；漂移集中在 `pool_max` 的 spec 表示法、3 个新 env 的注册表补登、以及 v1.8「env 零变更」陈述订正。

## 修复建议（按优先级）

| 等级 | 建议 | 负责方 |
|------|------|--------|
| P2 | `tests/` 补 fail-fast 用例：`config._resolve_pool_max('env:NOPE')` / `'env:'` ⇒ `ValueError`（config.py:469-470） | code-developer |
| P2 | `test_env_defaults` 补钉死 3 个默认字面量 `MAX_QUOTE_POOL==1000`、`MAX_FUNDFLOW_POOL==1000`、`MAX_TIMELINE_POOL==500`（test_config.py:80-82/150） | code-developer |
| P2 | `_POOL_MAX_ENVS` 与 3 常量改单份来源（映射字典或导入期遍历 `DOMAIN_MATRIX` 校验），消除双份名单并恢复「启动期即暴露」（config.py:333） | code-developer |
| P2 | 新增测试改用 `mock.patch.object(config, 'MAX_TIMELINE_POOL', 400)` 以符合测试约定（test_config.py:85-92） | code-developer |
| P2 | CR-04 补 stream 级 >cap 回归：活跃码 > `cache_max` 时 C2 `rest` 的 miss 降级（帧不崩、结转/回源），并评估 `cache_hit_ratio` 护栏（stream.py:478-487） | tester / code-developer |
| P2 | 注释「quote/depth」并入 prefetch 的措辞改述为「prefetch / SSE 计划刷新」（config.py:352） | code-developer |
| P2 | 评估 `cache_max` 是否也需 env 入口（§1.1#5 完整性），由编排层/架构裁决 | 编排层 / system-architect |
| P2 | 按 D1 表同步 3 份文档（表示法 + env 清单 + v1.8 陈述订正） | task-decomposer（P7b-r1） |
| 既有 | 评估 `stock_api.py:515-517` 持锁 `sorted` 淘汰为 >cap 负载做无排序改造（CR-MEM-02，上轮登记） | code-developer / 编排层 |

## 结论摘要

- **P0：无。**
- **P1：无。**
- **P2：7 条**（白名单可维护性 / 默认值未钉死 / fail-fast 未测 / CR-04 系统级 >cap 未覆盖 / `globals()` 调用期与 BR-CFG-10 测试层张力 / `cache_max` env 缺口 / 注释 quote-depth 归类）。
- 四项修复目标全部达成，**建议放行**；P2 可按上表择机在文档同步轮或下轮修复并入。
- `## 漂移检测`：⚠️ 有漂移（3 份文档、约 14 处），数值契约零漂移，交 P7b-r1。

