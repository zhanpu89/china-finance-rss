# PRF-MEM-01 · P1-1/P1-3/P2-1/P2-2 遗留修复轮 代码评审

> **模式**：P5b-r4（`>>MODE: review+drift`，评审 + 漂移合并）
> **变更范围**：`modules=config` | `china_finance_rss/config.py`、`tests/test_config.py`、`tests/test_data_layer.py`
> **入参**：已预取 diff（`git diff --stat` + `>>SIDE-EFFECT:` 4 条）；未自行全库搜索
> **日期**：2026-09-20

## 评审结论

**✅ 通过（P0 = 0 / P1 = 0 / P2 = 4）** —— P8-r1 的四项修复目标（P1-1 / P1-3 / P2-1 / P2-2）全部达成，无新增功能缺陷、无对外契约变化、无安全/并发回归。剩余 4 条均为 P2（测试覆盖 / 注释精度 / 断言脆弱性），不阻断。

**总评**：把 `_resolve_pool_max` 的调用期 `globals()[name]` 收敛为导入期冻结的 `_POOL_MAX_ENVS` 映射，方向正确且落地干净——`try` 块内只有一次 dict 查表，不存在被误吞的第二个 `KeyError` 源；`raise ... from None` 恰当。测试侧从「断言两侧同源」改为字面量锁定，并补了能**真正证伪**「依赖可变全局」的 frozen 用例。唯一实质遗留：删除重复用例时连带丢失了 `cache_ts` 同步淘汰的显式断言，而 `>>SIDE-EFFECT:` #3 声称「该路径仍被既有用例覆盖」——经核对**不成立**（CR-01）。

## 评审概要

| 修复目标 | 结论 | 依据 |
| --- | --- | --- |
| **P1-1** 消除 `cache_policy` 对可变模块全局的依赖 | ✅ 达成 | `config.py:338-342` 导入期冻结映射；全仓 `grep globals()` 仅剩文档/旧测试引用，代码零残留 |
| **P1-3** 测试 hermetic + 默认值字面量锁定 | ✅ 达成 | `test_config.py:76-78/83-86` 全为字面断言；frozen 用例可证伪旧实现 |
| **P2-1** env 名单与取值同源 + 未知名统一 `ValueError` | ✅ 达成 | dict 键即唯一合法 NAME；`KeyError → ValueError` 边界干净 |
| **P2-2** 删重复用例、锁定 PRF-MEM-01 真实读路径降级面 | ⚠️ 部分 | 新用例有效锁定「淘汰后读为 miss」；但 `cache_ts` 同步淘汰失去覆盖 → **CR-01** |
| P0 | 无 | — |

---

## Dim 0 — 契约一致性

**全栈模式不适用**：变更面为纯后端配置层 + 单测，无前端/小程序、无 OpenAPI 端点。以 `doc/detailed/config.md`（v1.11）与 `doc/arch/SAD.md`（v1.15）为契约源逐条核对：

- **0.A 后端覆盖率**：`cache_policy` / `DOMAIN_MATRIX` / `_resolve_pool_max` 均为既有接口，无新增端点。✅
- **0.B 默认值一致性**：`quote/fundflow/timeline` 的 `pool_max` 默认 1000/1000/500（`config.py:339-341`）与 `config.md §3.2`（`:326/328/329`）、`SAD.md:175-178` 逐值一致。✅
- **0.C 行为一致性**：**不成立（属预期漂移）**——契约仍写「**调用期**经 `globals()[NAME]` 解析、热替换常量即生效」（`config.md:247/292/349/379/535/574`、`SAD.md:200/258`），而代码已改为**导入期冻结、运行期重绑定不再生效**。本轮为 P1-1 修复的必要语义变更，按评审重点 #6 **不判代码错误**，登记于 `## 漂移检测`。

## Dim 1 — 数据与正确性

- `_POOL_MAX_ENVS` 的键（=合法 NAME）与值（=冻结上限）同源，**消除了原「白名单内但模块全局不存在 ⇒ `KeyError`」这一失效模式**（它已不可能构造）。✅
- `_resolve_pool_max` 的 `try/except KeyError` 边界干净：`try` 块内**唯一**会抛 `KeyError` 的表达式是 `_POOL_MAX_ENVS[name]`；`name` 恒为 `str`（`spec` 已过 `isinstance(str)` 且 `split(':',1)[1]`），可哈希 ⇒ 不存在「非未知名场景被误吞」。`from None` 正确抑制了 `KeyError` 的隐式 context，使对外异常面统一为 `ValueError`。✅
- 去掉了旧实现的 `int(...)` 包裹：映射值在导入期即为 `int(os.getenv(...))`，类型不变。**注**：这使映射值一旦被上游改为非 int 将不再被强制转换——当前无此风险，仅记录。✅
- 魔法值：`'env:'` 前缀、`'dedup'` / `'fixed:'` / `'n/a'` 均沿用既有 spec 语法，无新增字面量。✅

## Dim 2 — 并发

- 新实现：`cache_policy` 对 `_POOL_MAX_ENVS` 仅做**无锁只读 dict 查表**元组语义单调，无读改写、无竞态。✅
- 与 P8-r1 P1-1 的根因对照：旧实现「同一 tick 内两次 `cache_policy` 调用可能因并发赋值读到不同 `pool_max`」的风险已**消除**——输出现在是 `(domain, now)` 的确定函数（就池上限而言），不再随运行期重绑定抖动。✅
- 新测试 `test_prf_mem_01_pool_caps_are_frozen_at_import`（`test_config.py:92-99`）**在用例内原地改全局**并 `finally` 还原——这是**故意模拟被禁止动作以证伪**，属合法测试手法；unittest 默认串行执行，无跨用例污染（`finally` 保证还原）。方式上更贴合项目惯例的写法是 `mock.patch.object(config, 'MAX_TIMELINE_POOL', 400)`（`config.md §7` 明示该惯例），但当前写法等价、不构成缺陷。✅（提示，不计问题）

## Dim 3 — 资源与性能

- `_POOL_MAX_ENVS` 为 3 项 dict，导入期一次性构建，运行期一次 O(1) 查表——相对旧 `globals()` 查表，成本同量级或更低。✅
- 无 N+1 / 大事务 / 资源泄漏引入。✅
- ⚠️ **范围外遗留（P8-r1 P1-2 仍未关闭）**：`pool_max` 仍可经 env 在启动期调大，而 `cache_max` 为写死字面量且**无 `pool_max ≤ cache_max` 护栏**。本轮未处理，仅在 `## 漂移检测` 外单独提示（见「本轮范围外」）。**非本轮 diff 引入**，不计入本轮 P 级。

## Dim 4 — 安全

- 无输入注入、无越权面、无敏感信息。env 名拼接进异常消息 `f'bad pool_max env name: {name!r}'` 使用 `!r` 转义，无日志注入风险。✅
- 未放松任何校验：未知名仍 fail-fast（`ValueError`），与 `config.md §6`（`:574`）一致。✅

## Dim 5 — 结构与可维护性

- 命名/分层与既有模式一致（私有映射紧邻 env 常量，注释解释冻结语义）。✅
- 注释声明「**新增 env 只改这里一处**」（`config.py:333`）**略有夸大**：新增一个池 env 仍需 (a) 新增 `MAX_X_POOL = int(os.getenv(...))` 行 + (b) 在映射加一行，是**相邻两处**而非一处。其核心主张（键=NAME、值=上限，不再有第二份「名字白名单」）成立，故仅为 P2 注释精度 → **CR-02** 一并覆盖。
- `test_config.py:88-90` 的 `DOMAIN_MATRIX[i][3]` 位置索引断言**脆弱**（行结构变化即静默错位）→ **CR-03**。

**Dim 6 — 前端**：不适用（无前端变更）。

---

## 问题清单（本轮）

### 【P2】CR-01 `tests/test_data_layer.py`：删重复用例后，`cache_ts` 同步淘汰失去任何显式覆盖（`>>SIDE-EFFECT:` #3 陈述不准确）

- **证据链**：被删用例 `test_prf_mem_01_cache_degrade_is_lru_bounded` 曾断言「最旧条目及其 `cache_ts` 同步淘汰」。现存覆盖：
  - `test_cache_true_lru_eviction`（`test_data_layer.py:385-394`）只断言 `list(cache)` 与 `metrics['cache_entries']`，**不断言 `cache_ts`**；
  - `test_pool_eviction_leaves_cache_untouched`（`:368-383`）以 `cache_max=10` 运行，**不触发缓存淘汰**；
  - 新用例 `test_prf_mem_01_evicted_code_reads_as_miss_not_stale`（`:396-424`）同样**不断言 `cache_ts`**。
- **触发条件**：未来误删/改坏 `stock_api._cache_store` 的 `cache_ts.pop(victim, None)`（`stock_api.py:336`）。
- **后果**：**全部测试仍绿**，但被淘汰码的 `cache_ts` 条目永久残留 → 随运行时长单调增长（小而真实的**内存泄漏**）。鉴于本轮主题正是「内存收缩」，这条防线的静默丢失与目标背道而驰；且该用例是 P8-r1 P2-2 要求「改为锁定真实读路径」时新增的，读者会以为降级面已全锁。
- **修复方向**：在新用例加一行 `self.assertNotIn('sh600001', cache_ts)`（或对 `set(cache_ts) == set(cache)` 断言），一行即可闭合；同时更正 `>>SIDE-EFFECT:` #3 的「仍被既有用例覆盖」表述。

### 【P2】CR-02 `china_finance_rss/config.py:333-337`：注释「运行期结果不依赖可变模块全局」过宽，与实现不符

- **证据链**：`cache_policy` **仍读其他可变模块全局**：`_trading_tiers → _is_trading_hours` 读 `TRADING_HOLIDAYS`（`config.py:435`，且 `test_config.py:286-291` **正是靠 `mock.patch.object(config, 'TRADING_HOLIDAYS', ...)` 才通过**）、`_materialize` 读 `DOMAIN_MATRIX` / `_DOMAIN_ENCODING` / `MAX_DEDUP_CODES`。
- **触发条件**：后续维护者据该注释认定 `cache_policy` 已完全冻结，进而删除 `config.md §7` 明确许可的 `TRADING_HOLIDAYS` 注入，或据此推断「改 `DOMAIN_MATRIX` 也不影响运行期」。
- **后果**：契约/注释精度问题，无功能缺陷（这些全局按 `config.md §7`/BR-CFG-10 是「运行期只读」的**约定**，读取本身合法）。P1-1 的**实质**（3 个 env 池常量不再经调用期 `globals()` 读取）已达成，仅措辞外延过大。
- **修复方向**：把注释收窄为「**这 3 个池上限**在导入期冻结，`cache_policy` 不再经 `globals()` 调用期读取 env 常量」，不要泛化为「不依赖任何可变模块全局」。

### 【P2】CR-03 `tests/test_config.py:88-90`：`DOMAIN_MATRIX[i][3]` 位置索引断言脆弱

- **证据链**：`self.assertEqual(config.DOMAIN_MATRIX['quote'][3], 'env:MAX_QUOTE_POOL')` 依赖矩阵行恰为 5 元组且 `pool_max` 在第 4 位。若未来在行内插入新字段（如把 env 名单独成列）或重排元组顺序，`[3]` 将**静默断言另一个单元格**；若行变短则抛 `IndexError`（红但误导）。
- **触发条件**：`DOMAIN_MATRIX` 行结构演进（契约当前冻结为 5 元组，概率低）。
- **后果**：结构性断言在结构演进时产生误报或假绿；同时它并未校验「`'env:X'` 的 X 确实在 `_POOL_MAX_ENVS` 中」（P8-r1 P2-1 建议的那条遍历断言）。当前 `env:` 名与映射键一致，无实际漏洞。
- **修复方向**：可保持现状（记录）；若要收紧，改为遍历 `DOMAIN_MATRIX` 断言「每个 `'env:X'` spec 的 X ∈ `_POOL_MAX_ENVS`」，比对固定下标更抗结构漂移。

### 【P2】CR-04 `_resolve_pool_max` 的**正向路径与非法 spec** 未直接覆盖

- **证据链**：`test_prf_mem_01_bad_env_spec_fails_fast`（`:101-105`）只覆盖 3 个**负例**（`env:NOT_REGISTERED` / `env:` / `env:MAX_NOT_DEFINED`）。**已核对** `'env:'`（空名）确会走到 `_POOL_MAX_ENVS['']` 的 `KeyError` 分支并转 `ValueError`（`split(':',1)[1] == ''`），该断言有效。正向 `_resolve_pool_max('env:MAX_QUOTE_POOL') == 1000` 仅**间接**经 `cache_policy` 覆盖。
- **触发条件**：`_resolve_pool_max` 被重构（如误把 `'env:'` 分支提到 `'fixed:'` 之前、或改动 split 逻辑），负例仍绿但正例坏掉。
- **后果**：正向契约缺少最直接的一道像素级断言；风险低（`cache_policy` 用例已间接锁定 1000/1000/500）。`'fixed:x'`/未知 spec 的 `ValueError` 亦无直接用例。
- **修复方向**：补 1 行 `self.assertEqual(config._resolve_pool_max('env:MAX_QUOTE_POOL'), 1000)` 及一个 `assertRaises(ValueError)` 覆盖 `'fixed:x'` / 未知 spec。

---

## 修复建议（按优先级）

1. **CR-01（建议本轮补）**：`test_data_layer.py` 新用例补 `assertNotIn(victim, cache_ts)`；更正 SIDE-EFFECT #3 表述。
2. **CR-02（建议本轮补）**：收窄 `config.py:333-337` 注释外延。
3. **CR-03 / CR-04（可记录，不阻断）**：结构断言与正向/非法 spec 覆盖为增强项。

---

## SIDE-EFFECT 逆向检查（入参携带 `>>SIDE-EFFECT:` 4 条，逐条逆向验证）

| # | code-developer 声明 | 逆向假设 | 结论 |
| --- | --- | --- | --- |
| 1 | `_resolve_pool_max` 取值由调用期 `globals()` 改为导入期冻结 ⇒ 运行期重绑定 `config.MAX_*_POOL` 不再影响 `cache_policy` | 是否有**生产代码**依赖旧「重绑定生效」行为？⇒ 全仓 `grep MAX_QUOTE_POOL/MAX_FUNDFLOW_POOL/MAX_TIMELINE_POOL`：除 `config.py` 定义处与 `tests/` 外**无任何生产读写**；`stock_api`/`stream` 只消费 `cache_policy(...)['pool_max']`（`stock_api.py:487/515/570`、`stream.py:483`）。⇒ 无调用方被破坏。且新语义正是 BR-CFG-10 要求的方向。 | ✅ 成立 |
| 2 | 未注册/未定义 NAME 异常 `KeyError → ValueError`；`_prefetch_loop` 的 `except Exception` 对二者均吞，循环健壮性不变 | 改异常型是否会**改变既有捕获点行为**？⇒ 已知唯一宽捕获 `stock_api._prefetch_loop` 的 `except Exception`（盲审定位 `stock_api.py:1375-1376`）对 `KeyError`/`ValueError` **均捕获**，健壮性不变；且新实现下「白名单内但未定义」已不可能发生，只会剩下真正的未知名（本就 `ValueError`）。`cache_policy` 的 `KeyError(domain)` 走的是另一分支（`:520-522`），**不复用** `_resolve_pool_max`，不撞型。⇒ 相邻分支自洽。 | ✅ 成立 |
| 3 | 删 `test_prf_mem_01_cache_degrade_is_lru_bounded`（与 `test_cache_true_lru_eviction` 重复），「`cache_ts` 同步淘汰该路径仍被既有用例覆盖」 | 删后该行为是否**仍有覆盖**？⇒ **NO**。`test_cache_true_lru_eviction` 不断言 `cache_ts`；`test_pool_eviction_leaves_cache_untouched` 不触发缓存淘汰；新用例也不断言。声明不准确 → **CR-01（P2）**。非破坏性（无生产代码被改），仅测试门禁出现缺口。 | ⚠️ 声明不成立 |
| 4 | 删热替换用例（其断言与 P1-1 新不变量相反），改由 frozen 用例锁定相反行为 | 删除是否使某**既有契约**失去门禁？⇒ 旧用例断言「热替换生效」正是 P1-1 认定应消除的行为，其断言与新契约**方向相反**，删除正确；新增 `test_prf_mem_01_pool_caps_are_frozen_at_import` 提供了**证伪旧实现**的断言（旧 `globals()` 实现下该用例必红）。 | ✅ 成立 |

**受影响点 → 所属模块（供编排器映射 tester 定向回归 `>>SCOPE:`）**：

| 受影响点 | 所属模块 | 回归重点 |
| --- | --- | --- |
| `pool_max` 来源改为导入期冻结映射 | `config` → `stock_api`(`_process_chunk`/`_prefetch_loop`)/`stream`(`_refresh_pool`) | `cache_policy` 各域 `pool_max` 默认值；重绑定不生效 |
| `ValueError` 统一 | `config` → `stock_api._prefetch_loop` | 未知名 fail-fast，循环不中断 |
| `cache_ts` 淘汰覆盖缺口（CR-01） | `stock_api._cache_store` → `cached_batch`/`_process_chunk` | 缓存淘汰时 `cache_ts` 同步移除 |

---

## 漂移检测

> 本轮为 `review+drift` 合并模式。契约文档同步属 **P7b-r4 并行任务**，以下条目**列为预期漂移，不判代码错误**（评审重点 #6）。

**D1 契约核对 — 发现 1 处语义漂移（预期）：**

| 文档 | 位置 | 文档仍写 | 代码现状 | 性质 |
| --- | --- | --- | --- | --- |
| `doc/detailed/config.md` | `:247`（§2.7「冻结 vs 调用期读取」）、`:292`（§3.1 spec 注释）、`:349`（§3.3）、`:379`（BR-CFG-4）、`:433`（§5 伪代码 `frozenset`+`globals()`）、`:535`（§5 `_resolve_pool_max`）、`:574`（§6）、`:610`（§8 CFG-T19） | 「**调用期**经 `globals()[NAME]` 解析」「**热替换模块常量即生效**（`MAX_TIMELINE_POOL=400 ⇒ pool_max==400`）」「白名单 `_POOL_MAX_ENVS = frozenset(...)`」 | 导入期冻结的 **dict** `_POOL_MAX_ENVS`；运行期重绑定**不生效**（返回 500） | 语义漂移（P1-1 修复的**预期**结果） |
| `doc/arch/SAD.md` | `:15`（v1.15 修订依据 CR-02）、`:175-178`（矩阵）、`:200`（更正注）、`:258`（去重池表）、`:790`（config.py 行）、`:933`、`:1982-2004` | 同上「调用期解析为模块常量 / 部署可调」 | 同上 | 语义漂移（预期） |
| `doc/detailed/stock_api.md` | `:6`、`:376`、`:422`、`:465`（BR-SA-13）、`:1714`、`:1758` | 「`pool_max` 经 `'env:MAX_*_POOL'` 派生（调用期解析、部署可调）」 | 同上（仅「调用期」措辞需改） | 语义漂移（预期） |
| `doc/detailed/_PROGRESS.md` | `:25`、`:998-1000`、`:1034` | `_POOL_MAX_ENVS` 为 `frozenset`、`int(globals()[NAME])`（调用期）、热替换生效 | dict 冻结映射 | 语义漂移（预期） |

**D2 DOC_SYNC 追溯**：本轮入参**未携带** `>>DOC_SYNC:` 标记（代码 comment 中已说明「P7b-r4 并行同步」）。上述 4 份文档待 P7b-r4 回写，**不阻断本轮代码门禁**。

**D3 测试名同步漂移（应随 P7b-r4 修正）**：`config.md:610`（CFG-T19）仍引用**已删除**的用例名 `test_prf_mem_01_pool_cap_follows_env` 与 `test_prf_mem_01_cache_degrade_is_lru_bounded`，并把前者的「热替换得 400」写成已落地契约；实际用例已更名/改义为 `test_prf_mem_01_pool_caps_are_frozen_at_import`（断言**得 500**）与 `test_prf_mem_01_evicted_code_reads_as_miss_not_stale`。CFG-T19 的「用例总数」与「③ 锁 `cache_ts` 同步淘汰」描述均需更新（后者亦呼应 **CR-01**）。

**D4 规范合规**：新代码遵守 `code-discipline`（手术式修改、无新抽象）与 `config.md §1.3 layerIsolation`（config 未新增任何 `china_finance_rss` import）。✅ 无规范漂移。

> **漂移结论**：存在语义漂移（调用期→导入期冻结），全部属**已知预期**、归 P7b-r4 处理；无「代码违背未变更契约」的实质漂移（BR-CFG-10 本就要求运行期只读，本轮是向契约靠拢）。

---

## 本轮范围外（明确提示，不计入本轮 P 级）

- **P8-r1 P1-2 仍开放**：`pool_max` 可经 env 启动期调大，而 `cache_max` 写死且无 `pool_max ≤ cache_max` 护栏（`config.py:371-374` 无校验）。触发即让 prefetch 写入集超 LRU 容量，重演命中率退化。本轮修复未涉及，建议后续轮次按 P8-r1 建议 (a)/(c) 处置。
- **P8-r1 P1-4 仍开放**：内存目标 `≈0.65GiB` 仍以代码注释形式存在，无任何可执行门禁。
- **P8-r1 P2-7（部分）**：`config.md §2.3`「新增 env 项」表仍未列 3 个池 env；`test_env_defaults` 未纳入（其默认值已由本轮 `test_prf_mem_01_pool_cache_contract` 字面锁定，**测试半边已闭合**，文档半边待 P7b-r4）。

---

## 结论

**✅ 通过（P0 = 0 / P1 = 0 / P2 = 4）**。四项修复目标达成；无 P0。CR-01/CR-02 建议本轮顺手补（各一行级改动），CR-03/CR-04 可记录不阻断。



