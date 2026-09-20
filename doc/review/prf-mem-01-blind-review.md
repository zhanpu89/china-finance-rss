# PRF-MEM-01 对抗性盲审报告

> **模式**：P8 对抗性盲审（`>>MODE: blind`）
> **盲审纪律**：入参仅 = 需求原文（内存高水位 96.57% / 参数裁定）+ 改动文件清单 + DIFF 摘要。**未接触**设计决策理由、既往评审结论、测试报告。按需求方明确许可读取契约文档（`config.md` / `SAD.md` / `stock_api.md`）**仅用于核对文档-代码一致性**。
> **入参范围**：需求原文 1 份；改动文件 2 个（`china_finance_rss/config.py`、`tests/test_config.py`）；变更范围 `modules=config`。
> **日期**：2026-09-20

## 评审结论

**❌ 阻断（P0 = 0；P1 = 4；P2 = 2）** — 无数值解析/崩溃/数据丢失型 P0。但存在 4 条应修（P1）：内存缩减目标与工程自证账目不自洽且无护栏；3 域资源上限退化为不可运维覆盖的代码字面量；核心契约（`timeline`）无测试锁定；`cache_max` 跌破活跃码总上界。建议 P1 修复后再放行。

## 总评

这不是一次"看起来只是改数字"的改动。真正的风险不在新数字本身，而在**新数字把三条既有系统不变式悄悄打断了**：① `pool_max`/`cache_max` 与 `MAX_DEDUP_CODES` 的同源关系；② "所有资源上限经 env 注册"（`config.md` §1.1#5 / BR-CFG-16）；③ `cache_max` 覆盖活跃码全集。改动的注释还把 in-session 的 prefetch 频率写成 120s（实为 4/8s），会误导后续容量判断。内存目标（RSS 1.1GiB→0.65GiB）按项目自身账目最多只能由缓存上限拿回约 150MB 原始体积，**缺口 300MB+ 未归因、且无任何护栏**。以下逐条给出触发条件与后果。

## 问题清单

### 【P1】`config.py:340`（注释）+ `SAD.md §4.3`：内存缩减目标与项目自证账目不自洽，且无任何护栏 —— `cache_max` 收缩在数学上无法支撑 `~1.1GiB→~0.65GiB` 的归因

- **证据链**：注释断言 `预期 python 稳态 RSS ~1.1GiB→~0.65GiB`（Δ≈445MB）。但以项目自报单条实测体积核算：变更前 `quote 2000×9.4KB≈18.8MB + fundflow 2000×0.576KB≈1.2MB + timeline 2000×96KB≈192MB ≈ 212MB`；变更后 `1000×9.4KB + 1000×0.576KB + 500×96KB ≈ 58MB` ⇒ **端点缓存原始体积净减 ≈154MB**。要得到 445MB 的 RSS 降幅，需要"原始→展开"膨胀系数 ≈2.9×，而该系数**既未测量也未在任何测试/监控中锁定**。更关键：`SAD.md §4.3` 自身给出**整进程内存上界 ≈278MB**（含 128MB SSE 队列），而压测实测 python RSS = **1.095GiB（≈1121MB）** —— 存在 **≈843MB 未归因残差**，本次改动完全未触及。
- **触发条件**：重建容器部署后实测 RSS。
- **后果**：若残差真实存在（URL 缓存 2000 条、`_last_known` ≤2000 码×3 字段、`_fail_ledger` ≤10000 条、线程栈/帧缓冲等未被本次收缩），RSS 仍可达 ~0.9GiB，容器 96.57% 高水位复现；而**没有 AC/测试/告警**能发现"目标未达成"，改动会被默认记为已解决。`cache_hit_ratio=0.1585`、`upstream_timeout=123` 这两项变更前实测症状，也并非仅靠调小缓存上限即可解释。
- **修复方向**：为目标补一条可执行护栏（如 `tests/` 的内存断言或 `/healthz` 的 RSS 上限断言），并在归因中显式列出残差项与处置；不要只把预测写进注释。

### 【P1】`config.py:342-345` + `config.py:95/443-451`：`MAX_DEDUP_CODES` env 对 quote/fundflow/timeline 的约束被悄悄切断，且新上限无任何 env 覆盖入口

- **证据链**：改动把 3 域由 `'dedup'`（`_resolve_pool_max` 映射 `MAX_DEDUP_CODES`，`config.py:443-451`）改为硬编码字面量 `'fixed:1000'/'fixed:1000'/'fixed:500'`（`config.py:342/344/345`）。与此同时 **SSE 准入仍以 `MAX_DEDUP_CODES` 为总上界**（`stream.py:1202` `if total > MAX_DEDUP_CODES`；`stream.py:1260` 同）且 `config.py:95` 该 env 未变。于是同一个 env 变量一边管着"最多可订阅 2000 个不同码"，另一边**再也管不到这 3 域的 prefetch 池/缓存上限**。
- **触发条件**：运维按 `config.md` §2.7 把 `MAX_DEDUP_CODES` 调高（如 4000）或调低（如 800）。
- **后果**：调高 → 准入放行 4000 码，但 quote/fundflow/timeline 池仍 1000/1000/500，prefetch 保活范围与准入口径**静默背离**；调低 → 池/缓存仍是 1000/1000/500，代码数下降但内存上限不降，2C2G 节点上运维"降配省内存"的操作**失效**。更严重的是 `'fixed:N'` 是矩阵字面量，**没有任何 env 可覆盖**，这直接违反 `config.py` 自述定位"every env-registered IO/resource budget"与 `config.md` §1.1#5 / BR-CFG-16"所有资源上限经 env 注册"——即 §2.4 当初专门把 `_FUNDFLOW_MAX_POOL` / `_TIMELINE_MAX_POOL` / `_BASIC_INFO_MAX_POOL` 等硬编码常量删除迁入配置系统，本次又把同类硬编码值放回了矩阵。
- **修复方向**：要么为这 3 域引入 env（如 `QUOTE_POOL_MAX` / `CACHE_MAX`），要么给 `'fixed:N'` 增加 env 覆写机制；至少需在 `config.md` 登记"这 3 域不再随 `MAX_DEDUP_CODES` 联动"为 **env 语义变更**，而非现在宣称的"env 零变更"。

### 【P1】`tests/test_config.py:65-72`：新契约未被测试锁定；`config.md §8 CFG-T19` 明列的 6 个断言一个都没落地，内存大户 `timeline` 完全无保护

- **证据链**：DIFF 只把 `test_policy_values` 的第 72 行 `quote.cache_max` 由 2000 改成 1000。全文件扫描（288 行）**无任何对 `quote.pool_max`、`fundflow.*`、`timeline.*` 的断言**：`test_l0_is_the_fastest_tier` 只断言 `depth.pool_max == MAX_DEDUP_CODES`（`tests/test_config.py:62-63`），`test_policy_values` 只断言 `margin/f10/announcement/plate/quote.cache_max`（`:66-72`）。而 `config.md §8` 的 **CFG-T19** 明确要求断言 `quote.pool_max==1000 and quote.cache_max==1000`、`fundflow==1000/1000`、`timeline==500/500`、`depth/announcement/f10.pool_max==2000`。
- **触发条件**：后续任何一次编辑（回滚、重构矩阵、误合并）把 `timeline` 写回 `('L1',1.0,1.0,'dedup',2000)` 或把 `quote.pool_max` 写回 `'dedup'`。
- **后果**：CI **全绿**。按本次归因，`timeline` 单条 ~96KB 是内存首要贡献（500×96KB≈48MB vs 2000×96KB≈192MB），其回滚会把本次修复的主要收益静默抹掉，直至下一次压测才会以 96.57% 高水位形式暴露。设计的测试用例（CFG-T19）存在但未实现，属"契约已声明、门禁未落地"。
- **修复方向**：补 `test_mem_shrink_contract`（或 CFG-T19）逐域断言 6 个值；并额外断言 `cache_max` 与活跃码上界的关系（见 CR-04）。

### 【P1】`config.py:342/345`（`cache_max`=1000/500）vs `stream.py:1202/1260`（准入上界 2000）：`cache_max` 首次跌破活跃码总上界，打断"终点缓存覆盖活跃全集"的定容不变式

- **证据链**：改动前 `quote.cache_max = timeline.cache_max = MAX_DEDUP_CODES = 2000` —— 终点缓存恰好能容纳准入放行的全部活跃码（`_active_codes()` 可达 `MAX_DEDUP_CODES`，见 `stream.py:1202/1260`）。改动后 `quote=1000`、`timeline=500` ≪ 2000。而 C2 分片路径把"非本拍切片码"的取数**唯一依赖终点缓存**：`stream.py:478-487` 的 `rest` 分支只调用 `stock_api.cached_batch(domain, rest, now=now)`（`stock_api.py:341-371`，注释即"no network"）；`_cache_store` 在 `len(cache) > cache_max` 时按 LRU 淘汰（`stock_api.py:334-336`）。SAD 仅论证了**池**上限"仍远大于单组上限 200"，**从未论证缓存上限低于 2000 的影响**。
- **触发条件**：活跃码数 > `cache_max`（quote ≥1001，或 timeline ≥501）。合法可达：10 组 × 200 码 = 2000（`MAX_CODES_PER_SUB=200`、`MAX_DEDUP_CODES=2000`）。
- **后果**：当活跃码 > 缓存上限时，每拍写入/读取都会把 LRU 窗口外的码挤出，`rest` 分支对超出窗口的码持续 miss，只能退化为 `_last_known` 结转/回源（`stream.py:1064`）；变更前实测 `cache_hit_ratio` 已仅 **0.1585**，此改动会使其进一步下降，上游取数量与 `upstream_timeout` 上升，C2 分片容量模型（假设非切片码为缓存命中）被削弱。
- **修复方向**：明确 `cache_max` 的定容依据。若目标是"覆盖活跃全集"，应保持 `cache_max >= MAX_DEDUP_CODES`（或按域把上界显式降到 ≤ `cache_max`）；若接受二者分离，须在 `config.md`/`SAD` 补"`cache_max < MAX_DEDUP_CODES` 时的 hit-ratio 退化与上游增量"论证，并加一条 `cache_hit_ratio` 回归护栏。

### 【P2】`config.py:340`：注释把 prefetch 轮询写成 "120s"，与实现的 in-session 4/8s 矛盾；且把未验证的 RSS 预测固化进代码

- **证据链**：注释称 `prefetch(120s 轮询) 保活范围收敛`。但 `quote.pool_refresh = ttl×1.0`，盘中 L0=4s、`fundflow/timeline` L1=8s（`config.py:342/344/345`），仅**非盘中**才是 120s；`_prefetch_loop` 的间隔正是 `sleep(cache_policy(domain)['pool_refresh'])`（`stock_api.py:1333`）。
- **触发条件**：后续工程师/运维依据该注释判断"池 1000 条、120s 足以覆盖"。
- **后果**：in-session 实际频率被低估 15–30×。以 `_PREFETCH_PASS_BUDGET=60s`（`stock_api.py:73`）核算，盘中每轮实际只能访问约 430 个码（1000 码 × ~140ms ≈ 140s > 60s），"保活范围收敛"的结论只在非盘中成立。`预期 RSS ~0.65GiB` 亦为未验证预测写死在代码里，会随实测过期成为误导性事实。
- **修复方向**：改为"盘中 4/8s、非盘中 120s"；把 RSS 预测移出代码注释（放文档或删除）。

### 【P2】`config.py:343` + `tests/test_config.py:62-63`：`depth` 成为矩阵中最大的池（2000 = quote 的 2×）且仍绑定 `MAX_DEDUP_CODES`，"同源收缩"叙事不自洽

- **证据链**：`depth` 保持 `('L0',1.0,1.0,'dedup',500)`（`config.py:343`）⇒ `pool_max = MAX_DEDUP_CODES = 2000`、`cache_max=500`（4:1）。而"同拍"的 `quote` 池已降到 1000。`tests/test_config.py:62-63` 还**显式把 depth 池锁死在 `MAX_DEDUP_CODES`** —— 即唯一仍与那个被 3 域抛弃的 env 绑定的 L0 域。
- **触发条件**：运维调整 `MAX_DEDUP_CODES`，或复核"同源收缩"是否彻底。
- **后果**：矩阵中最大的 prefetch 工作集落在声明"自有池/缓存"的 depth 上，与本次"收敛保活范围"的目标不一致；且测试把该不对称**固化为契约**，后续想统一收缩会先撞测试。需求仅裁定 "depth 保持 500"（指 cache），未裁定其 `pool_max` 保持 2000。
- **修复方向**：确认 depth 池 2000 是否刻意豁免；若是，在 `config.md`/`SAD` 显式登记"depth 池不参与本次收缩"及理由；若否，改为 `'fixed:<n>'`。

## 逆向假设确认（B2 逐项）

- **恶意/越界输入**：`'fixed:x'` → `_resolve_pool_max` 抛 `ValueError`（`config.py:451`），启动期 fail-fast ✅；`'fixed:0'`/负值可解析但本改动未引入 ❌ 不适用。
- **外部依赖最坏时刻失效**：本次为静态数值，无新外部依赖 ✅ 不适用。
- **并发/竞态**：`cache_policy` 纯函数、返回值新建（`config.py:487-488`）未改动 ✅；`cache_max` 变小后 `_cache_store` 的淘汰与 `cached_batch` 读并发仍走同一把 `lock` ✅。
- **边界值**：活跃码 2000 vs `cache_max` 1000/500 —— **确认成立**（CR-04）。
- **调用链漏处理层**：`pool_max`/`cache_max` 全链消费一致（`stock_api.py:487/515-517/334`、`stream.py:483`）✅；但 env 到池的绑定断裂 **确认成立**（CR-02）。
- **需求未覆盖分支**：需求裁定"RSS TTL 保持 180s 不动" —— 核对 `feed` 非盘中 ttl=180 未被改动 ✅；**容量模型假设"非切片码为缓存命中"在该改动下不再普遍成立**（CR-04）。

## 变更范围与消费方（供编排器映射定向回归）

| 受影响点 | 所属模块 | 逆向结论 |
| --- | --- | --- |
| `quote/fundflow/timeline` 的 `pool_max`/`cache_max` 收缩 | `config` → `stock_api`（`_process_chunk`/`_cache_store`/`_prefetch_loop`）→ `stream`（`_refresh_pool`/`cached_batch`） | P1（CR-04）、P2（CR-05） |
| `MAX_DEDUP_CODES` 与 3 域池解绑 | `config` ↔ `stream`（准入）/`stock_api`（`_FAIL_LEDGER_MAX` 仍=10000，未受影响 ✅） | P1（CR-02） |
| `depth` 池未收缩 | `config` → `stock_api`（`_basic_depth_pool`） | P2（CR-06） |
| 内存目标归因 | `config` 注释 + `SAD`/AR-8 | P1（CR-01） |
| 测试断言 | `tests/test_config.py` | P1（CR-03） |

> **P0 结论**：无。全部 6 条问题均为数值上限/运维可调性/测试门禁/注释一致性范畴，不构成崩溃、数据丢失、资金或安全类 P0；但 P1 需修复后方建议放行。
>
> **下一步（交编排器）**：P1 → 回退 `code-developer` 修复；CR-03 的 CFG-T19 补测可并入同批。CR-01/CR-04 建议由 `tester` 做 RSS/`cache_hit_ratio` 定向回归（`>>SCOPE:` 见上表）。

