# PRF-MEM-01 修复轮 · 对抗性盲审报告

> **模式**：P8 对抗性盲审（`>>MODE: blind`）
> **盲审纪律**：入参仅 = 需求原文（触发本轮修复的评审报告 `doc/review/prf-mem-01-blind-review.md`）+ 改动文件清单 + `>>DIFF:` 客观摘要。**未接触**中间修复轮的设计理由、评审结论、测试结论。按需求方明确许可读契约文档（`doc/detailed/config.md`、`doc/arch/SAD.md`）**仅用于核对文档-代码一致性**。
> **入参范围**：需求原文 1 份；改动文件 3 个（`china_finance_rss/config.py`、`tests/test_config.py`、`tests/test_data_layer.py`）；变更范围 `modules=config`。
> **日期**：2026-09-20

## 评审结论

**⚠️ 不阻断（P0 = 0；P1 = 4；P2 = 3）** —— 无崩溃/数据丢失/资金/安全类 P0（纯数值与配置来源变更，运行期最坏后果是命中率下降与门禁空转，不破坏对外契约）。但存在 4 条应修：① 修复方式与同批文档自订的「运行期只读」不变式（BR-CFG-10 / `config.md §7`）正面冲突；② `pool_max` env 可调而 `cache_max` 写死形成新不对称，且无 `pool_max ≤ cache_max` 护栏；③ 新增契约测试对 `pool_max` 侧是自引用断言（改默认值 CI 全绿），且对环境变量敏感、非 hermetic；④ 内存目标仍无任何护栏，`~0.65GiB` 只是写进代码注释的未验证预测。

## 总评

本轮修的是「池上限没有 env 入口」（首轮 CR-02）。实现方式是把矩阵 spec 从字面量改成 `'env:MAX_*_POOL'`，并在 `_resolve_pool_max` 里用 `globals()[name]` **在每次 `cache_policy()` 调用期**取模块常量。这个选择解决了「无 env 入口」，但顺手把两条既有约束弄坏了，且三条新测试里有一条在自我证明：

- **env 值本身仍在导入期冻结**（`int(os.getenv(...))`，`config.py:330-332`），部署调参依然要重启容器 —— 这与 `MAX_DEDUP_CODES` 的地位完全相同。`globals()` 的调用期读取**对生产没有任何新增能力**；它唯一能被观测到的场景，是运行期直接给 `config.MAX_*_POOL` 赋值 —— 而这正是 BR-CFG-10 / `config.md §7` 明令禁止的。新测试 `test_prf_mem_01_pool_cap_follows_env` 恰恰把这个被禁止的动作**固化成受支持的契约**。
- `pool_max` 变成三个域都可以 env 调，`cache_max`（真正的内存硬界）却仍是写死字面量。于是一个「想覆盖 2000 码」的运维会去调 `MAX_FUNDFLOW_POOL`/`MAX_TIMELINE_POOL`，把池放大到超过 `cache_max` —— prefetch 轮转写入的不同码数超过 LRU 容量，条目在被再次调度前就被淘汰，恰好把首轮 CR-04 担心的命中率退化**从另一条路径重新引入**，且没有任何校验、测试或文档警示。
- 新增的 `test_prf_mem_01_pool_cache_contract` 用 `config.MAX_QUOTE_POOL` 去断言 `quote.pool_max` —— 断言两侧同源。它锁住了 `cache_max` 的 1000/1000/500/500 字面量，却**完全没有锁住 pool 侧的收缩默认值**（首轮 CR-03 要求「逐域断言 6 个值」）。默认值改回 2000，或 CI 环境里恰好有 `MAX_QUOTE_POOL=2000`，测试照样全绿。

以下逐条给出触发条件与后果。

## 问题清单

### 【P1】`config.py:330-333` + `config.py:467-471` vs `config.md:383/581-582`：调用期 `globals()` 读取使 `cache_policy` 依赖可变模块全局，与本 change-set 同批文档自订的「env 常量运行期只读 / cache_policy 纯函数」正面冲突

- **证据链**：`_resolve_pool_max` 的 `'env:'` 分支在**每次调用**执行 `int(globals()[name])`（`config.py:471`）。`config.md §2.7`（`:245`）把这写成**特性**：「热替换模块常量即可生效（`config.MAX_TIMELINE_POOL = 400 ⇒ cache_policy('timeline')['pool_max'] == 400`）」。但同一份文档的 §7（`:581-582`）写：「`cache_policy` … 均为**纯函数，不读不写共享可变状态**（`os.getenv` 结果在导入期冻结）」「模块级**可读常量**：任何模块**不得**原地修改」；BR-CFG-10（`:383`）同义。`tests/test_config.py:85-92` 正是靠 `config.MAX_TIMELINE_POOL = 400` 通过 —— 即**测试通过的前提是违反被勾选的 BR-CFG-10**。
- **触发条件**：任何运行期对 `config.MAX_*_POOL` 的赋值（测试已示范，生产代码可照抄）。此时并发的 prefetch 线程（`stock_api._prefetch_loop`，`stock_api.py:1333/1337` 各调一次 `cache_policy`）与请求线程（`stock_api.handle_cls_*`、`stream._refresh_pool`）可能在**同一 tick 内**读到不同的 `pool_max`：`_prefetch_loop` 在 `:1337` 取到的 policy 与 `:1333` 取到的不是同一份。
- **后果**：`cache_policy` 不再是「参数的函数」，纯函数/线程安全契约失效且**无法回滚**（无锁保护）；`globals()` 解析出的池上限可在同一轮内不同，池淘汰规模随之抖动。更现实的问题是**能力被夸大**：env 值导入期冻结，热改 env 对运行中进程无效，「免改码调参」与「热替换常量」被混为一谈，后续工程师可能据此在生产里改模块属性。
- **修复方向**：二选一，不能两头都要 ——（a）保持「纯函数 + 导入期冻结」：在导入期为 3 个 spec 解析出**值**（例如 `_POOL_MAX = {'MAX_QUOTE_POOL': MAX_QUOTE_POOL, ...}` 快照，或让矩阵直接引用常量值），删除 `:471` 的调用期 `globals()`；同时把 `test_prf_mem_01_pool_cap_follows_env` 改为**子进程/模块重载**验证 env 生效，而不是原地改全局。（b）若确实要保留热替换，须同步修订 BR-CFG-10 / §7，明确「`MAX_*_POOL` 是**可变**配置项、`cache_policy` 非纯函数、并发热替换无同步保证」，并删除 §7 的纯函数表述。

### 【P1】`config.py:330-333/357-360`：`pool_max` 可 env 调而 `cache_max` 写死，且无 `pool_max ≤ cache_max` 护栏 —— 调大池即让 prefetch 写入集超过 LRU 容量，重演 CR-04 的命中率退化

- **证据链**：`quote/fundflow/timeline` 的 `pool_max` 现由 env 支配（`config.py:357/359/360`），`cache_max` 仍是矩阵内 int 字面量（同一行，无 env、无校验）。prefetch 循环的**工作集 = 该域池**（`_prefetch_rotate` 返回整个池，`stock_api.py:1406-1414`；`_prefetch_loop` 逐个 `_cache_store(..., policy['cache_max'], ...)`，`:1364-1365`）。默认 `pool==cache`（1000/1000、500/500）时刚好自洽；但 env 入口只暴露了池这一半。
- **触发条件**：运维按首轮 CR-04 的结论（活跃码上界 `MAX_DEDUP_CODES=2000` > `cache_max`）把 `MAX_FUNDFLOW_POOL=2000` 或 `MAX_TIMELINE_POOL=2000`（一个完全合法、文档鼓励的「调大 prefetch 覆盖」动作）。此时 `pool_max(2000) > cache_max(1000/500)`。
- **后果**：`_prefetch_loop` 一轮轮转 2000 码（受 `_PREFETCH_PASS_BUDGET` 限流，多轮完成），而 LRU 只留 1000/500 —— 某码被 prefetch 写入后，在其被**下一次调度到之前**就可能已被挤出；prefetch 的「保活」语义被架空，且 `cache_max` 侧无法同步调大（无 env），运维无法在不改码的情况下把这一对调回自洽。终端缓存命中率（变更前已仅 `cache_hit_ratio=0.1585`）进一步下降 ⇒ `cached_batch` miss 上升、`stream._refresh_pool` 的 `rest` 分支（`stream.py:483`）更多落到 `_last_known`、上游取数上升。无校验、无测试、无文档警示会拦下这个配置。
- **修复方向**：给这对参数加最小护栏 ——（a）在 `_resolve_pool_max` 或 `_materialize` 加 `assert pool_max <= cache_max`（或归一 `min(pool_max, cache_max)`），并在 `config.md §6/§10#24` 登记；或（b）把 `cache_max` 也 env 化并在启动期校验 `pool_max <= cache_max`，使两个数字必须成对调整；至少（c）在 `config.md` 明确「env 调大 pool 超过 cache_max 会使 prefetch 失效」，并加一条断言该关系的配置测试。

### 【P1】`tests/test_config.py:80-83`：`test_prf_mem_01_pool_cache_contract` 对 `pool_max` 是自引用断言 —— 收缩默认值未被锁定，且测试对本机 env 敏感、非 hermetic

- **证据链**：`self.assertEqual((q['pool_max'], q['cache_max']), (config.MAX_QUOTE_POOL, 1000))` —— `q['pool_max']` 本来就由 `config.MAX_QUOTE_POOL` 解析而来（`config.py:471`），断言两侧同源、恒真；`fundflow`/`timeline` 同理，`depth` 侧又拿 `config.MAX_DEDUP_CODES` 自比。全文件**没有任何一处**断言 `quote.pool_max == 1000` / `fundflow.pool_max == 1000` / `timeline.pool_max == 500` 的字面值（首轮 CR-03 的 CFG-T19 要求的正是这 6 个字面值）。`test_env_defaults`（`:150-168`）也**未纳入**这 3 个新 env 常量。
- **触发条件**：① 有人把 `MAX_QUOTE_POOL` 默认值改回 `'2000'`（`config.py:330`）；或 ② CI/开发机上存在 `MAX_QUOTE_POOL=2000` 之类的环境变量（`config.py:330` 在导入期读 env）。
- **后果**：情形 ① 下 CI **全绿**，pool 侧收缩被静默回滚（`timeline` 池回到 2000 正是首轮 CR-03 点名的「内存收益被抹掉」路径）；情形 ② 下测试**在不同机器上断言不同内容**，契约测试失去可复现性（这是本轮新引入的 env 敏感性 —— `depth` 那处旧断言早已如此，但新用例不该复制这个缺陷）。「CFG-T19 已落地」的门禁声明因此名不副实。
- **修复方向**：pool 侧改为**字面值**断言（`(1000, 1000)` / `(1000, 1000)` / `(500, 500)`），env 覆盖行为另用独立用例验证；`test_env_defaults` 补入 3 个新常量的默认值断言；如需环境无关，用 `mock.patch.dict(os.environ, {}, clear=True)` + 子进程重载 `config` 验证 env 派生。

### 【P1】`config.py:350-355` + `state`（无护栏）：内存目标仍以「写在代码注释里的未验证预测」形式存在，缺任何可执行门禁 —— 目标未达成无法被发现

- **证据链**：注释断言 `预期 python 稳态 RSS ≈0.65GiB（估算值，待重建部署后实测复核）`（`config.py:355`），SAD v1.15 §4.3/AR-8 同步为「≈0.65GiB 估算，待复核」。但本 change-set 的 3 条新测试（`tests/test_config.py:74-92`、`tests/test_data_layer.py:396-414`）**没有一条**涉及内存/`cache_entries` 总量上限；全仓无「RSS 超阈值告警」或「`cache_entries` 总上界」断言。首轮 CR-01 要求的护栏（内存断言 / `/healthz` RSS 上限）未落地。
- **触发条件**：重建容器部署后实测（该注释本身要求「待实测复核」）。若首轮 CR-01 指出的 `≈843MB` 未归因残差（URL 缓存 2000 条、`_last_known` ≤2000 码、`_fail_ledger` ≤10000 条、线程栈/帧缓冲）真实存在，RSS 仍可停在 ~0.9GiB。
- **后果**：容器 `96.57%` 高水位复现，但**没有任何测试或指标**能发现「本次修复的目标未达成」；改动会被默认记为已解决，下一次压测前无人知晓。注释里的数字还会随实测过期，成为误导性事实（首轮 CR-05 已指出同类问题，只移走了 prefetch 频率、没移走 RSS 预测）。
- **修复方向**：把预测性数字移出代码注释（放 `doc/` 并标注「待复核」）；补一条可执行门禁 —— 例如 `tests/` 内对「`Σ cache_max` 上界」的静态断言，或 `/healthz` 暴露 `rss_bytes` 并在部署侧配阈值告警，使「目标未达成」在部署后可见。

### 【P2】`config.py:333/471`：`_POOL_MAX_ENVS` 与常量清单是两份手工清单；白名单内但未定义的名字会抛 `KeyError`（非文档承诺的 `ValueError`），并与 `KeyError(domain)` 契约撞型，且在 `_prefetch_loop` 里被静默吞掉

- **证据链**：`_POOL_MAX_ENVS = frozenset({...})`（`:333`）与 `MAX_*_POOL` 常量（`:330-332`）是两份必须手工同步的清单；`globals()[name]`（`:471`）对「白名单内但模块全局不存在」的名字抛 `KeyError`。文档承诺的是 `ValueError('bad pool_max env name: ...')`（`config.md:572`）。
- **触发条件**：后续重命名/删除某个 `MAX_*_POOL` 常量却忘了改白名单（或反之）。矩阵 spec 仍在，白名单仍有该名字。
- **后果**：`cache_policy('quote')` 抛 `KeyError('MAX_QUOTE_POOL')` —— 与文档钉死的「未知 domain ⇒ `KeyError(domain)`」撞型，调用方难以区分；而 `stock_api._prefetch_loop` 的 `except Exception as e: log.error(...)`（`:1375-1376`）会**吞掉它并无限空转**，只留错误日志，不会 fail-fast。新增第 4 个受控池需同时改矩阵、常量、白名单三处，任意一处漏改都可能静默或半静默。
- **修复方向**：把两份清单合为一份映射（如 `_POOL_MAX_SPECS = {'MAX_QUOTE_POOL': MAX_QUOTE_POOL, ...}`），`_resolve_pool_max` 只做一次 dict 查找并对缺失键显式抛 `ValueError`（与文档一致）；加一条测试遍历 `DOMAIN_MATRIX` 断言每个 `'env:X'` 的 X 都在该映射中。

### 【P2】`tests/test_data_layer.py:396-414`：新增的「缓存降级」用例是对既有 LRU 用例的重复，未覆盖 CR-04 真正要锁的交互 —— 提供虚假保障

- **证据链**：`test_prf_mem_01_cache_degrade_is_lru_bounded` 与 `test_cache_true_lru_eviction`（`:385-394`）断言的是同一件事：`_cache_store` 在 `cache_max` 处严格 LRU、淘汰最旧、保留最新。二者都直接以手工 `cache_max=3` 调用 `_cache_store`，**没有任何**「活跃码 > `cache_max` 时 `stream._refresh_pool` 的 `rest`/`cached_batch` 行为」或「prefetch 轮转写入集 > `cache_max` 时的驻留时间」的覆盖。而 `config.md` CFG-T19 ③（`:608`）把它登记为「锁 CR-04 降级语义」。
- **触发条件**：未来改动把 `cache_max` 与 `pool_max` 的关系、或 `stream`/prefetch 侧缓存读写搞坏。
- **后果**：测试仍绿，CFG-T19 的「降级语义已锁」是虚假保障；审阅者会据此跳过 CR-04 的真实风险（首轮 `cache_hit_ratio=0.1585` 的进一步退化）。参数化窄（`cache_max=3`、单域 quote、无并发）也意味着它离生产路径很远。
- **修复方向**：把该用例改为驱动真实路径 —— 构造 `活跃码 > cache_max` 的 `_handle_cached_batch` / `cached_batch` 场景，断言「未命中码经 `_last_known` 结转进帧（stale）而非静默 null」以及「`cache_entries` 严格 ≤ `cache_max`」；或与 LRU 用例合并、删除重复。

### 【P2】`config.md:116-135`（§2.3）与 `tests/test_config.py:150-168`（CFG-T9）：3 个新 env 常量未进「新增 env 项」表、未进 env 默认值测试，文档-测试双缺口

- **证据链**：`MAX_QUOTE_POOL`/`MAX_FUNDFLOW_POOL`/`MAX_TIMELINE_POOL` 只出现在 §2.7 全量清单（`config.md:237-238`）；§2.3「新增 env 项（本模块注册，消费者在其它模块）」表（`:116-135`）**未列**这 3 项，尽管它们的消费者（经 `cache_policy`）在 `stock_api`/`stream`。`test_env_defaults`（`tests/test_config.py:150-168`）也未断言其默认值。
- **触发条件**：后续维护者按 §2.3 作为「env 门禁清单」核对，或依赖 CFG-T9 作为「env 默认不变」护栏。
- **后果**：文档清单不完整、测试护栏有洞（与 P1-3 的环境敏感性叠加），新 env 的默认值没有任何一处被字面锁定。
- **修复方向**：§2.3 补 3 行（默认值/类型/消费者/AC）；`test_env_defaults` 补 `assertEqual(config.MAX_QUOTE_POOL, 1000)` 等 3 条。

## 逆向假设确认（B2 逐项）

- **恶意/越界输入**：`'env:<NAME>'` 的 `NAME` 不在白名单 ⇒ `ValueError`（`:469-470`）✅ 不静默；但白名单内未定义 ⇒ `KeyError`（**P2-5**，非文档承诺的类型）❌。
- **外部依赖最坏时刻失效**：本改动为静态数值 + 模块全局，无新外部依赖 ✅ 不适用。
- **并发/竞态**：`cache_policy` 读 `globals()`（`:471`）⇒ 不再是纯函数；`test` 验证的原地赋值在并发下无同步（**P1-1**）❌。`_cache_store` 的淘汰与 `cached_batch` 读仍走同一把 lock ✅。
- **边界值**：`MAX_*_POOL` env 可被设为 `0`/负数/`> MAX_DEDUP_CODES`/`> cache_max` —— 前两者不会崩（`sorted(...)[:n]` 切片安全），但 `> cache_max` **确认导致 prefetch 写入集超 LRU 容量**（**P1-2**）❌。
- **调用链漏处理层**：`pool_max`/`cache_max` 全链消费一致（`stock_api.py:487/515-517/570`、`stream.py:483`）✅；env → 池的绑定**改为调用期 `globals()`**，绑定机制本身成为新风险面（**P1-1/P2-5**）❌。
- **需求未覆盖分支**：需求「不破坏对外契约」—— OpenAPI/字段/状态码未变 ✅；但「同一 env `MAX_DEDUP_CODES` 管准入、不再管 3 域池」的运维语义已变，文档已登记（SAD v1.15 CR-04）✅；「内存目标未达成可发现」**无分支覆盖**（**P1-4**）❌。

## 变更范围与消费方（供编排器映射定向回归）

| 受影响点 | 所属模块 | 逆向结论 |
| --- | --- | --- |
| `quote/fundflow/timeline` 的 `pool_max` 来源改 `'env:<NAME>'`（调用期 `globals()`） | `config` → `stock_api`（`_process_chunk`/`_prefetch_loop`）→ `stream`（`_refresh_pool`） | P1-1（纯函数契约）、P2-5（白名单/异常型） |
| `pool_max` 可 env 调而 `cache_max` 写死 | `config` → `stock_api`（`_prefetch_loop` 工作集 vs `_cache_store` LRU） | P1-2（命中率退化） |
| 新增 3 个 env 常量默认值 | `config` / 测试 | P1-3（自引用断言 + env 敏感）、P2-7（清单/测试缺口） |
| 内存目标 `≈0.65GiB` | `config` 注释 + SAD §4.3/AR-8 | P1-4（无护栏） |
| 缓存降级用例 | `tests/test_data_layer.py` | P2-6（重复 + 未覆盖交互） |
| `depth` 池维持 `'dedup'`=2000 / `cache_max=500` | `config` → `stock_api._depth_store` | ✅ 文档已登记（SAD v1.15 CR-06：无 prefetch 循环，池仅账本）；无新发现 |

> **P0 结论**：无。全部 7 条问题均为配置来源/契约一致性/测试门禁/文档缺口范畴，不构成崩溃、数据丢失、资金或安全类 P0；对外 API/字段/状态码零变更。
