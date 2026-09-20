# PRF-MEM-01 · P8-r2 对抗性盲审报告

> **模式**：P8 对抗性盲审（`>>MODE: blind`）— 假定代码一定有 Bug，找出来。
> **入参范围**：需求原文 1 份（`doc/review/prf-mem-01-blind-review.md`，首轮盲审）+ 用户指令「收尾 P8-r1 的 P1/P2」+ 改动文件清单（`china_finance_rss/config.py`、`tests/test_config.py`、`tests/test_data_layer.py`）+ DIFF 摘要。变更范围 `modules=config`（消费方 `stock_api` 只读 `policy['pool_max']`）。
> **未接触**：本轮修复轮的评审结论、测试是否通过、设计决策理由。仅按需求方许可读取实现代码与既有契约文档（`doc/detailed/config.md` 等）用于文档-代码一致性核对。
> **日期**：2026-09-20
> **★ 盲审纪律污染披露**：为定位 `MAX_*_POOL` 消费方，执行了一次**全仓** grep（模式 `MALLOC_ARENA_MAX|MAX_QUOTE_POOL|...`），意外命中并短暂显示了后续轮次的既有评审产物 `doc/review/prf-mem-01-修复轮_对抗性盲审.md` 与 `doc/review/code-review-prf-mem-01-fix-round.md` 的片段。**这些片段不作为本报告任何结论的依据**；下方每条发现均由「需求原文 + 当前代码」独立重建证据链。若编排器要求 100% 零上下文，建议重发纯净入参并限定搜索路径。**同时，本报告文件名与既有的 `prf-mem-01-修复轮_对抗性盲审.md` 区分，未覆盖任何历史产物。**

## 评审结论

**❌ 阻断（P0 = 0；P1 = 3；P2 = 4）** — 无崩溃/数据丢失/安全类 P0。但本轮宣称修复的核心契约（BR-CFG-10「运行期只读 / 导入期冻结」）**并未被实现层或测试层真正建立**（P1-1）；新增的 env 调节能力与 `cache_max` 硬界之间**无任何不变式或校验**，单条 env 即可让 prefetch 覆盖超出缓存容量并静默回归命中率（P1-2）；首轮 P1「内存目标需可执行护栏」本轮只以注释回填实测数字收尾，**护栏未落地**（P1-3）。建议修 P1 后再放行。

## 总评

这轮 diff 的意图是「把 `'env:<NAME>'` 从调用期 `globals()` 解析改为导入期冻结的注册映射，并让错误类型收口为 `ValueError`」。代码确实换成了 dict 查找，但**冻结的只是「重绑定常量」这一条错误向量**：真正的可变全局是 `_POOL_MAX_ENVS` 这个**普通 dict 本身**，而它在**每次调用**被读取，测试却刻意只做常量重绑定、不碰这个 dict——于是「冻结」停留在注释与测试名里，没有被任何机制或断言兜住（CR-01）。同时，新引入的 env 覆盖只覆盖了 `pool_max`、没有覆盖 `cache_max`，两者之间不存在任何 `pool_max ≤ cache_max` 的校验、断言或文档护栏，运维按注释「免改码调参」把池调大即可在**不改一行代码**的情况下重演首轮担心的命中率退化（CR-02）。此外，首轮 P1 要的「可执行内存护栏」在改动文件里找不到——`config.py:359-369` 是长篇实测叙述，不是断言（CR-03）。以下逐条给出触发条件与后果。

## 问题清单

### 【P1】`config.py:338-342` + `config.py:481-486`：所谓「导入期冻结」并未成立 —— `_POOL_MAX_ENVS` 是**可变普通 dict**，`cache_policy` 在**每次调用**读它，且 `'dedup'` 路径仍直读可变全局

- **证据链**：注释 `config.py:333-334` 声明「本映射在导入期建成后视为**冻结**，`cache_policy` 的运行期结果**不依赖可变模块全局**（BR-CFG-10 运行期只读）」。但实现是 `_POOL_MAX_ENVS = {'MAX_QUOTE_POOL': MAX_QUOTE_POOL, ...}`（`config.py:338-342`）——一个**没有 `MappingProxyType`、没有私有 getter、没有 `__setitem__` 防护的普通可变 dict**；`_resolve_pool_max` 在 `config.py:483-484` 的 `try: return _POOL_MAX_ENVS[name]` 是**每次 `cache_policy()` 调用都执行的实时查找**（`_materialize`←`cache_policy`，`config.py:504/523-524`），不是导入期快照。新增测试 `test_prf_mem_01_pool_caps_are_frozen_at_import`（`tests/test_config.py:92-99`）只执行 `config.MAX_TIMELINE_POOL = 400`，**从未触碰真正的变异向量 `config._POOL_MAX_ENVS['MAX_TIMELINE_POOL'] = 400`**，因此必然通过。
- **触发条件**：任何模块/测试/调试脚本执行 `config._POOL_MAX_ENVS['MAX_QUOTE_POOL'] = 2000`（或 `.clear()` / `.update(...)`）——这是对「模块级 dict」唯一有意义的"运行期重绑定"形态。
- **后果**：`cache_policy('quote')['pool_max']` 在运行期变为 2000，而**CI 全绿**；这正是 BR-CFG-10 / `config.md §7`「均为纯函数，不读不写共享可变状态；任何模块不得原地修改」所禁止的状态，且新测试给出的"已冻结"结论是**假阳性**。附带：`'dedup'` 路径 `return MAX_DEDUP_CODES`（`config.py:477-478`）仍**每次调用直读模块全局**，故 `depth`/`f10`/`announcement` 的 `pool_max` 会随 `config.MAX_DEDUP_CODES` 重绑定而变——注释中「`cache_policy` 的运行期结果不依赖可变模块全局」这句**对所有域都不完全成立**。
- **修复方向**：把注册表建成不可变快照（`types.MappingProxyType({...})` 或 `_pool_max_envs()` 只读访问器）；若要让 `'dedup'` 也满足 BR-CFG-10，需同样在导入期解析其值。测试必须新增"变异 `_POOL_MAX_ENVS` 后 `cache_policy` 输出不变"的断言，否则该测试名与注释就是过度承诺。

### 【P1】`config.py:330-332` + `config.py:371-374`：新增 env 覆盖与 `cache_max` 硬界之间**无任何不变式/校验/测试**，单条 env 即可把 `pool_max` 抬过 `cache_max`，静默重演命中率退化

- **证据链**：本轮的卖点是 `pool_max` 可免改码调参（`config.py:326-329`「在此注册使部署可免改码调参」），而 `cache_max` 为矩阵字面量 `quote=1000 / fundflow=1000 / timeline=500`（`config.py:371-374`）。`_resolve_pool_max`（`config.py:472-487`）、`_materialize`（`config.py:490-510`）、`cache_policy`（`config.py:513-524`）与 `_POOL_MAX_ENVS`（`config.py:338-342`）**没有任何一处校验 `pool_max <= cache_max`**，也没有导入期遍历断言。与此同时 SSE 准入上界仍是 `MAX_DEDUP_CODES=2000`（`stream.py:1202/1260`），prefetch 轮转按 `pool` 全量推进（`stock_api.py:1334` `_prefetch_rotate`），而终端缓存写入按 `cache_max` 严格 LRU 淘汰（`stock_api.py:334-336`）。
- **触发条件**：运维按注释鼓励的动作设置 `MAX_QUOTE_POOL=2000` 或 `MAX_TIMELINE_POOL=2000`。此时 `pool_max(2000) > cache_max(1000/500)`。
- **后果**：prefetch 每轮遍历 2000 个码，但缓存只装得下 1000/500——被遍历到的码在再次轮到之前就已被 LRU 挤出，`cached_batch`（`stock_api.py:341-371`）对超出窗口的码持续 miss，`stream` 分片路径的非切片码取数退化为回源（`stream.py:478-487`）。变更前实测 `cache_hit_ratio` 已仅 0.1585，此路径会使其进一步下降、`upstream_fetch_total` / `upstream_timeout` 上升。由于 env 在导入期读取，`test_prf_mem_01_pool_cache_contract`（`tests/test_config.py:74-90`）只断言默认 1000/1000/500，**在任何设了该 env 的部署里要么失败、要么（若只断言常量）看不出问题**——没有任何门禁能把「调大池导致的命中率退化」与「正常配置」区分开。
- **修复方向**：二选一——(a) 在导入期或 `cache_policy` 中显式拒绝 `pool_max > cache_max`（fail-fast，附一条测试）；(b) 若刻意接受二者独立，须在契约中登记该取舍，并补一条覆盖「工作集 > cache_max 且 pool_max > cache_max」的定向回归（命中率/回源量护栏），不能只在注释里说「非正确性问题」。

### 【P1】改动文件内**没有可执行的内存护栏** —— 首轮 P1「内存目标需护栏」本轮以注释收尾，目标反而被注释自认未达成

- **证据链**：首轮盲审对内存目标的修复方向是「补一条可执行护栏（`tests/` 内存断言或 `/healthz` 的 RSS 上限断言），不要只把预测写进注释」。本轮改动文件仅 `config.py` + 两个测试文件；`config.py:359-369` 新增的是**长篇实测叙述**（run 20260920-110805、RSS 1.095→1.012GiB、`MALLOC_ARENA_MAX=2`、VmSize/匿名映射数字），并自认「仍未到 0.65GiB 级」。全仓 `RSS/VmSize` 相关的断言只出现在手工作业脚本 `tests/stress_all.py:253`、`tests/stress_basic_info.py:237`（读 `VmRSS` 的压测工具），**不是 unittest 门禁**；`tests/` 下无新增任何 RSS/`cache_hit_ratio` 的 unittest 断言。
- **触发条件**：后续任意一次改动重新放大缓存/池，或目标持续未达成。
- **后果**：`~0.65GiB` 这一目标在 CI 中**不可见、不可证伪**；「本次调优已解决内存高水位」会被默认记为完成，直到下一次压测再以 96.57% 高水位暴露。注释里写入的易变实测数字（run 号、GiB、映射数）还会随实测过期成为误导性事实——它描述的是某一刻的观测，不是被守护的不变式。
- **修复方向**：落地一条可执行护栏（定义负载下的 RSS 上限 unittest，或 `/healthz` 暴露并断言 RSS 上界），或把目标从代码注释中移除、在契约里显式登记「目标未达成 + 残差项与后续动作」。两者至少做一项。

### 【P2】`tests/test_config.py:92-105`：删除唯一的 env 生效用例后，3 个新 env 常量**没有任何测试证明 env 能改到 `pool_max`**

- **证据链**：DIFF 摘要显示删除了 `test_prf_mem_01_pool_cap_follows_env`（热替换验证 env/常量联动）。新增的三条测试分别是：`test_prf_mem_01_pool_cache_contract`（只断言**默认值** 1000/1000/500 与 spec 字符串）、`test_prf_mem_01_pool_caps_are_frozen_at_import`（断言重绑定**不**生效）、`test_prf_mem_01_bad_env_spec_fails_fast`（非法名抛 `ValueError`）。**没有一条**通过 `subprocess`/模块重载/`os.environ` 注入设置 `MAX_QUOTE_POOL=1500` 并断言 `cache_policy('quote')['pool_max'] == 1500`。`test_env_defaults`（`tests/test_config.py:163-181`）逐一断言了十余个既有 env 常量，**唯独未纳入这 3 个新常量**（经 grep 确认）。
- **触发条件**：后续重构把 `_POOL_MAX_ENVS` 值写成字面量 `{'MAX_QUOTE_POOL': 1000, ...}`（不再引用常量）、或把 `_resolve_pool_max` 的 env 分支读错名字/读错来源。
- **后果**：本轮引入的**唯一新增能力**（部署可 env 调参）失去测试保护；这类回归 CI 全绿，只在运维真正调参时才发现「调了不生效」——而彼时线上正按旧上限运行，参数与预期背离。删除热替换用例是正确的（热替换语义本身错误），但**替代覆盖没补上**。
- **修复方向**：补一条基于导入期语义的 env 生效测试（子进程或 `importlib.reload`，设置 env 后断言 `pool_max` 跟随）；并把 3 个新常量纳入 `test_env_defaults`。

### 【P2】`config.py:484`：`int()` 强制转换被移除，`'env:'` 分支成为**类型信任边界**；非 int 注册值会在 `_process_chunk` 内抛 `TypeError`

- **证据链**：原实现是 `return int(globals()[name])`（强制归一为 int），新实现是 `return _POOL_MAX_ENVS[name]`（`config.py:484`）——**不再做任何类型收敛**。对照：同一函数的 `'fixed:<n>'` 仍是 `int(spec.split(':',1)[1])`（`config.py:479-480`），`'dedup'` 返回 int（`config.py:477-478`）。而注释明说「新增 env 只改这里一处」（`config.py:333`），鼓励在注册表中扩充项。消费侧 `_process_chunk` 用 `if len(pool) > pool_max:`（`stock_api.py:515`）——若注册值为 `str`，该表达式抛 `TypeError`；`_prefetch_slice` 虽用 `max(1, min(int(size), len(ordered)))`（`stock_api.py:1432`）容忍，但 `stock_api.py:515` 不容忍。
- **触发条件**：后续把某项注册为 `MAX_X_POOL = os.getenv('MAX_X_POOL', '1000')`（漏 `int()`）或 `float(...)`，或被运行期改写成非 int。
- **后果**：`len(pool) > '1000'` 抛 `TypeError`，沿批次处理路径向外冒泡为请求 500（`_process_chunk` 无此异常兜底）；float 则静默改变语义。改动前 `int()` 曾挡住这一类类型漂移，本轮把它删掉了。
- **修复方向**：保留归一 `return int(_POOL_MAX_ENVS[name])`（成本可忽略），或在导入期对注册表值做类型/正值校验。

### 【P2】`tests/test_data_layer.py:396-424`：新用例与本次改动**无因果**，无法证伪 PRF-MEM-01 回归（换回 2000 也全绿）

- **证据链**：该用例自建合成策略 `policy = {'ttl': 100, 'pool_max': 5, 'cache_max': 2}`（`:408`），再调用 `_process_chunk`（`:419-421`）。但 `_process_chunk` / `_cache_store` 在本次 diff 中**逐字未改**（改动文件仅 config + 测试）；它断言的行为——「缓存里没有 → 查视为 miss → 回源 → `results` 为 `None`，绝不返回陈旧值」——对**任意** `cache_max` 都成立，包括变更前的 2000。用例全程**不读 `config.cache_policy(...)`**，不使用真实的 1000/500，也不构造「工作集 > 2000」的真实形态。
- **触发条件**：把 `config.DOMAIN_MATRIX['quote']` 的 `cache_max` 从 1000 改回 2000，或把 `MAX_QUOTE_POOL`/`MAX_TIMELINE_POOL` 改回 2000。
- **后果**：该用例仍然通过，docstring 声称的「locks the *read* consequence of the smaller `cache_max`」是**过度声明**——它对本次收缩零保护。同时 DIFF 摘要称被删的 `test_prf_mem_01_cache_degrade_is_lru_bounded` 与 `test_cache_true_lru_eviction` 重复，但被删用例体已不在工作树，无法独立核验其删除是否真的被接管。数据层对 PRF-MEM-01 的净覆盖因此**没有增加**。
- **修复方向**：让用例从 `config.cache_policy(domain)` 取真实策略（或断言一条跨层不变式：工作集 > 真实 `cache_max` 时被淘汰码必然回源），使 config 回退能使其失败；并在删除用例时留存其原断言以便核验去重不丢失覆盖。

### 【P2】`config.py:335-337`：注释对 `ValueError` 收益的诊断**不成立**；且坏 spec 并不在导入期暴露

- **证据链**：注释称旧 `KeyError` 的问题之一是「在 `_prefetch_loop` 的 `except Exception` 中被静默吞掉」。但 `_prefetch_loop` 的 `try` 体（`stock_api.py:1331-1376`）包含 `cache_policy(domain)`（`:1333` 与 `:1337`），其兜底是 `except Exception as e: log.error(...)`（`:1375-1376`）——`ValueError` **同样是 `Exception` 子类**，因此新的 `ValueError('bad pool_max env name: ...')` 在 prefetch 路径上**照样被静默吞掉并无尽空转**，收益仅为「与 `KeyError(domain)` 契约不再撞型」（这一条成立）。另外，`_resolve_pool_max` 仅经 `_materialize`←`cache_policy` 调用（`config.py:504/523-524`），**没有任何导入期校验**；`cache_policy` 在每个请求/每轮 prefetch 才被调用，故「fail-fast」实为「首次用到该域时才失败」，与测试名 `..._fails_fast`（`tests/test_config.py:101`）给人的印象不符。
- **触发条件**：开发者在某矩阵行写入 `'env:MAX_SECTOR_POOL'`（或任何拼写错误的名字）却未登记注册表。
- **后果**：错误要到**首次调用该域**才暴露；若该域冷门则长期潜伏，若首次调用发生在 prefetch 路径则被日志吞掉、循环空转。注释中的技术论证会误导后续维护者以为「换成 `ValueError` 就解决了静默吞掉」。
- **修复方向**：修正注释（只声明类型收口收益，删掉"避免被吞"的表述）；在导入期遍历 `DOMAIN_MATRIX` 校验所有 `'env:<NAME>'` 均可解析，才是真正的 fail-fast。

## 逆向假设确认（B2 逐项，不验证正确性）

- **恶意/越界输入**：`'env:MAX_NOT_DEFINED'` / `'env:'` → `ValueError`（`config.py:485-486`）✅；但**非 int 的注册值**未做类型归一（见 P2-⑤）→ `_process_chunk` 内 `TypeError` 可冒泡为 500 ❌ 成立。
- **外部依赖最坏时刻失效**：本次为静态数值，无新外部依赖 ✅ 不适用。
- **并发/竞态**：`cache_policy` 返回值每次新建（`config.py:490-510`）、`_POOL_MAX_ENVS` 只读使用未新增锁。但「冻结」若被理解为可安全并发读的不可变对象，则**该前提不成立**（dict 可被任意线程原地改写，`config.py:338-342`）❌ 成立（并入 P1-①）。
- **边界值**：`pool_max > cache_max` 当前可由单条 env 合法构造（`MAX_QUOTE_POOL=2000` vs `cache_max=1000`）❌ 成立（P1-②）；`pool_max=0/负数` 亦可（无正值校验）→ `_process_chunk` 每次清空池、prefetch 退化为空转，属同一根因（无校验）。
- **调用链漏处理层**：`policy['pool_max']` 消费方 `_process_chunk`（`stock_api.py:511-517`）一致 ✅；注册表→矩阵→policy 的绑定在**默认值**下一致 ✅；但 env 覆写与 `cache_max` 的联动缺失 ❌ 成立（P1-②）；坏 spec 在 `_prefetch_loop` 内被吞 ❌ 成立（P2-⑦）。
- **需求未覆盖分支**：需求裁定「env 注册使部署可免改码调参」——该分支**无生效测试**（P2-④）；需求 P1「内存目标需护栏」的分支**未实现**（P1-③）。

## 变更范围与消费方（供编排器映射定向回归）

| 受影响点 | 所属模块 | 逆向结论 |
| --- | --- | --- |
| `_POOL_MAX_ENVS` 可变 dict / 调用期读取 | `config`（`cache_policy` 全调用方） | P1（CR-01） |
| `'dedup'` 仍直读可变全局 `MAX_DEDUP_CODES` | `config` → `depth`/`f10`/`announcement` 消费方 | P1（CR-01，注释过度承诺） |
| env `pool_max` 可超过 `cache_max`，无护栏 | `config` → `stock_api`（`_process_chunk`/`_cache_store`/`_prefetch_loop`）→ `stream`（`cached_batch`/分片回源） | P1（CR-02） |
| 内存目标护栏 | `config` 注释 + `tests/`（缺 unittest 断言） | P1（CR-03） |
| 新 env 生效性未测 | `tests/test_config.py` | P2（CR-04） |
| `int()` 归一被删 | `config` → `stock_api._process_chunk` | P2（CR-05） |
| 数据层新用例与改动无因果 | `tests/test_data_layer.py` | P2（CR-06） |
| 注释诊断（`except Exception` 同吞 `ValueError`） | `config` 注释 + `stock_api._prefetch_loop` | P2（CR-07） |

> **P0 结论**：**无**。全部 7 条问题集中在「冻结不变式未落地 / env 与 cache_max 无护栏 / 内存护栏缺失 / 测试覆盖与类型归一 / 注释准确性」，默认配置下不产生崩溃、数据丢失、资金或安全后果；P1 → 建议回退 `code-developer` 修复，P2 记录不阻断。
>
> **零上下文核验点（交编排器）**：本报告仅以「需求原文 + 当前改动文件 + DIFF 摘要」为依据；污染披露见文首。若需 100% 盲审纯净度，请重发入参并禁止全仓 grep（避免再次命中历史评审产物）。
