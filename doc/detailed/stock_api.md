# stock_api.py 详细设计

> **版本** v1.10 · **状态** 已契约同步（★ v1.10：**P8-r1 P1/P2 收尾**——`config.md` v1.12 把 `'env:<NAME>'` 语义由"调用期 `globals()`（可热替换）"更正为**导入期冻结的注册映射** `_POOL_MAX_ENVS`（键=唯一合法 NAME、值=冻结池上限、**名单与取值同源**）；`cache_policy` **不读可变模块全局**（BR-CFG-10），运行期重绑定 `config.MAX_*_POOL` 不再改变 `['pool_max']`；未注册/未定义 NAME **一律 `ValueError`**（不再 `KeyError`）。**本模块只消费 `policy['pool_max']`/`policy['cache_max']`——代码零变更、对外契约零变更**；并补 **pool 与 cache 是独立上限（P1-2）** 的设计取舍（不设 `pool_max ≤ cache_max` 护栏）；★ v1.9：**归因纠偏 + PRF-MEM-02 arena 治理实测**——**更正 v1.8 的 URL 缓存归因（该归因已被证伪）**：共享 URL 缓存存的是**解码后的原始响应文本（`str`）**（`cache.py:851-852` `resp.read().decode(...)` → `_cache_put(cache, url, data)`；`json.loads` 在调用方命中后解析），**非**解析对象，总量仅**几十 MB**、**非内存大头**；**真因 = glibc arena**（33 线程 × 默认最多 `8×ncores` 个 64MB arena，`RssAnon` 占 98%、`VmLib`/`RssFile` 仅 14.5MB）——A/B 实测（run **20260920-113125**，基线 **20260920-110805**）`MALLOC_ARENA_MAX=2` ⇒ python VmRSS **1.008GiB → 0.772GiB**、VmSize **8.96GB → 1.15GB**、匿名 rw-p **300 → 166**、容器 **1.41GiB(93.98%) → 1.259GiB(83.95%)**；**无行为 / 对外契约变更**；★ v1.8：**PRF-MEM-01 实测回填**——五档压测实测（run **20260920-110805**）证伪此前预测：python RSS **1.095GiB → 1.012GiB（净收益仅 ~83MiB）**、容器 **1.449GiB(96.57%) → 1.41GiB(93.98%)**，**本次收缩未达成内存目标**；**归因更正**：终端缓存只是小头，真正大头 = 未收缩的共享 URL 缓存（`cache.MAX_CACHE_SIZE=2000`）+ 分配器碎片；**无行为 / 对外契约变更**；★ v1.7：**PRF-MEM-01 修复轮同步**——3 域 `pool_max` 改经 **`'env:MAX_*_POOL'`** 派生（默认 1000/1000/500，**可免改码调参**；`cache_max` 仍为 `config` 矩阵整数字面量 = 内存硬界）；**BR-SA-13 补 CR-04 降级说明 + `depth` 保持 `'dedup'` 的理由**；**仅消费 `policy['pool_max']`，本模块代码零变更、对外契约零变更**；★ v1.6：**PRF-MEM-01 内存调优同步**——`config.md` v1.8 将 `quote`/`fundflow`/`timeline` 的 `pool_max`/`cache_max` **同源收缩**（1000/1000、1000/1000、500/500），本模块 §3.3/§3.5/BR-SA-13 同步；**无接口 / 对外契约变更**；★ v1.5：**台账收口——`REV-DES-21` 裁定关闭**：用户裁定 `/stock/f10` 极少/几乎无调用 ⇒ **不实现**「仅单码 / 少量码」上限；§10#10 加裁定注并**保留「当前未强制」事实陈述**（= 知情接受，非遗漏）；**无实现变更、无对外契约变更、无 BR / 测试编号变更**；★ v1.4：**溯源收口 + 引用时点约定**——上游 **SAD v1.12 / PRD v0.10**、基础层接口权威 **config v1.6 / cache v1.14 / metrics v1.8**；**无 BR 语义变更、无对外契约变更**；P7b：以 `china_finance_rss/stock_api.py` 实现为准回写 · **depth 域 + 三阶段 basic_info + refresh_epoch 贯通**）· **日期** 2026-09-20 · **作者/产出** task-decomposer
> **v1.10 变更（P8-r1 P1/P2 收尾 · 只改文档，不改代码）**：① **`'env:<NAME>'` 语义更正**——`config.md` **v1.12** 把 3 域 `pool_max` 的来源由"调用期 `globals()` 解析（v1.9 措辞，声称可热替换模块常量）"更正为**导入期冻结的注册映射** `_POOL_MAX_ENVS`（`{'MAX_QUOTE_POOL': MAX_QUOTE_POOL, 'MAX_FUNDFLOW_POOL': MAX_FUNDFLOW_POOL, 'MAX_TIMELINE_POOL': MAX_TIMELINE_POOL}`，**键=唯一合法 NAME、值=冻结池上限、名单与取值同源**）；`_resolve_pool_max` 改为 `try: return _POOL_MAX_ENVS[name] except KeyError: raise ValueError(...) from None`（**不再 `globals()`**）⇒ `cache_policy` 的运行期结果**不依赖可变模块全局**（BR-CFG-10）。**默认值不变（1000/1000/500）⇒ 本模块行为逐字不变**。② **错误类型收口**——未注册/未定义 NAME **一律 `ValueError('bad pool_max env name: ...')`**（v1.9 对白名单内未定义名可能抛 `KeyError`）。③ **pool 与 cache 是独立上限（P1-2 澄清）**——`pool_max`（prefetch 轮转覆盖）与 `cache_max`（终端缓存内存界）**不设 `pool_max ≤ cache_max` 护栏**；依据：`depth`/`f10`/`announcement` 现状即 `pool_max`(=`'dedup'`=2000) > `cache_max`(500)（`depth` 无 prefetch 循环、`f10`/`announcement` 有大 TTL），`pool_max > cache_max` 只造成**回源轮转浪费**、**非正确性问题**（读路径对 LRU 淘汰码正常回源，绝不返回陈旧值）；3 个收缩域当前 `pool_max == cache_max`（1000/1000、1000/1000、500/500）**是取值巧合、非不变式**。④ **测试侧（`config` / 数据层）**：`test_prf_mem_01_pool_cache_contract` 改**字面量锁定 + 结构性 spec 断言**、删热替换用例，新增 `_pool_caps_are_frozen_at_import`（BR-CFG-10）/ `_bad_env_spec_fails_fast`（P2-1）；`tests/test_data_layer.py` 删除重复用例、新增 `test_prf_mem_01_evicted_code_reads_as_miss_not_stale`（被 LRU 淘汰码**读为 miss 并回源**）⇒ 用例总数 **517 → 518**。**本模块代码零变更 / 无行为·接口·对外契约·BR 编号·测试编号变更**；**本轮只改文档**；**未改 SAD / PRD / API.md / README.md / `.opencode`；`config.md` → v1.12、`_PROGRESS.md` 同步。**
> **v1.9 变更（归因纠偏 + PRF-MEM-02 arena 治理实测 · 只改文档，不改代码）**：本版**更正 v1.8 的错误归因**（v1.8 的「共享 URL 缓存存解析后 Python 对象、体积数倍于原始 JSON、是内存大头」表述**已被证伪**）并回填 arena A/B 实测。① **纠偏**——共享 URL 缓存存的是**解码后的原始响应文本（`str`）**：`cache.py:851-852` `data = resp.read().decode(encoding, errors='replace')`、`cache.py:862` `_cache_put(cache, url, data, ttl=ttl)`；**`json.loads` 在调用方命中后解析**，缓存内**没有**解析对象；按条数与体积估算总量仅**几十 MB** ⇒ **不是内存大头**。② **真因 = glibc arena**——33 线程 × 默认最多 `8×ncores` 个 **64MB arena**，分配后不归还；`RssAnon` 占 98%（`VmLib`/`RssFile` 仅 **14.5MB**）。③ **A/B 实测（run 20260920-113125，基线 run 20260920-110805）**：`MALLOC_ARENA_MAX=2` ⇒ python VmRSS **1,057,324kB(1.008GiB) → 809,328kB(0.772GiB)**、`RssAnon` **1,042,748kB → 794,776kB**、VmSize **8.96GB → 1.15GB**、匿名 rw-p **300 → 166**、容器稳态 **1.41GiB(93.98%) → 1.259GiB(83.95%)**。④ **累计链路**——python RSS **1.095GiB（收缩前）→ 1.012GiB（3 域缓存收缩 −83MiB）→ 0.772GiB（+`MALLOC_ARENA_MAX=2` −248MiB）**；容器 **1.449 → 1.41 → 1.259GiB**；仍未达 ~0.65GiB 级，剩余 = 终端缓存解析对象（~200MB）+ 运行时/分配器残余。⑤ **观测（⚠️ 单次观测，勿写成结论）**——tier1000 `timeline` `ok_rate` **89.6% → 100%**（**单次观测，可能含上游波动，勿写成结论**）。**本模块代码零变更 / 无行为·接口·对外契约·BR 编号·测试编号变更**；**未改代码 / 测试 / SAD / PRD / API.md / README.md / `.opencode`；`config.md` → v1.11、`_PROGRESS.md` 同步。**
> **v1.8 变更（PRF-MEM-01 实测回填 · 只改文档，不改代码）**：① **BR-SA-13 / §10#27** 的「预期 python 稳态 **RSS ~1.1GiB→~0.65GiB（估算值，待重建部署后实测复核）**」按实测更正为：python RSS **1.095GiB → 1.012GiB（净收益仅 ~83MiB）**、容器 **1.449GiB(96.57%) → 1.41GiB(93.98%)** ⇒ **本次收缩未达成内存目标**。② **补「终端缓存非内存大头」的更正**——实测反推（`timeline` 1350→500 省 ~82MB + `quote`/`fundflow` 各 −1000 条省 ~10MB ≈ 92MB）与 −83MiB 吻合 ⇒ 终端缓存只是小头；真正大头 = **未收缩的共享 URL 缓存**（`cache.py:35 MAX_CACHE_SIZE=2000`；实测 `cache_entries.url=2000` 顶满；条目 `{'data': 解析后 Python 对象}` 体积数倍于原始 JSON），其次为线程池 glibc arena 碎片。③ **旁证**：3 域缓存精确生效（healthz `/healthz?check=0`：`quote`/`fundflow` `pool_max`/`cache_max` = 1000/1000、`timeline` = 500/500、`depth` = 500）；`cache_hit_ratio` **0.1585 → 0.1796**；tier1000 `timeline` `ok_rate` 100% → **89.6%**、`upstream_timeout` 123 → **317**（⚠️ **待复测归因，尚非结论**，不写成结论）。**本模块代码零变更 / 无行为·接口·对外契约·BR 编号·测试编号变更**；**未改代码 / 测试 / SAD / PRD / API.md / README.md / `.opencode`；`config.md` → v1.10、`_PROGRESS.md` 同步。**
> **v1.7 变更（PRF-MEM-01 修复轮同步 · 以 `config.py` 实现为准 · 只改文档，不改代码）**：① **§3.3 / §3.5 pool 口径**改为「经 **`'env:MAX_QUOTE_POOL'` / `'env:MAX_FUNDFLOW_POOL'` / `'env:MAX_TIMELINE_POOL'`** 派生（默认 **1000/1000/500**，部署可**免改码调参**）」——**数值不变，来源**由 `config` 矩阵字面量改为 env 注册常量（`config.md` v1.9 §2.7/§3.1/BR-CFG-4；白名单 `_POOL_MAX_ENVS`，**调用期**解析）。**`cache_max`（1000/1000/500）仍为矩阵整数字面量 = 内存硬界**，本模块仍只消费 `policy['cache_max']`。② **BR-SA-13 扩充**：补 **CR-04 优雅降级说明**——`cache_max`（1000/500）**首次小于活跃码上界 `MAX_DEDUP_CODES`(2000)**，「终端缓存覆盖活跃全集」不再成立；降级路径 = 本模块 `_cache_store` **严格 LRU 淘汰（最旧条目与 `cache_ts` 同步淘汰）** + 消费方 `stream._refresh_pool` 对未刷新片的 miss 码退化为 `stream._last_known` **结转**（进帧 `stale`），**功能不破坏**（`_process_chunk` 对未命中码正常回源）；代价 = `cached_batch` 命中率下降、上游取数上升（由 `cache_hit_ratio` / `upstream_fetch_total{domain}` 可观测）。并补 **`depth` 池保持 `'dedup'`(=2000) 的理由**：`depth` **无 prefetch 循环**（经 `fetch_cls_basic_info` 阶段 3 → `_depth_store` 写入），其池仅作 `code→ts` 账本（~200KB 量级），`cache_max=500` 才是内存界 ⇒ 与 `quote` 的"不对称"是**有意的、正确的**。③ **§9 / §10#27 / §12 补修复轮登记**。**本模块代码零变更**（`_process_chunk`/`_cache_store`/`_depth_store` 逐字不变，仅 `policy` 取值自动跟随）；**无接口 / 对外契约 / BR 编号 / 测试编号变更**；**未改代码 / SAD / PRD / API.md / README.md / `.opencode`；`config.md` → v1.9、`_PROGRESS.md` 同步。**
> **v1.6 变更（内存调优 PRF-MEM-01 契约同步 · 只改文档，不改代码）**：① **§3.5 每域策略实值表**——`quote`/`fundflow`/`timeline` 的 `pool_max`/`cache_max` 同步为 **1000/1000、1000/1000、500/500**（权威：`config.md` v1.8 §3.1/§3.2 · §10#24）；② **§3.3 池/缓存上限注释**同步（`quote`/`fundflow`=1000、`timeline`=500；`depth`/`f10`/`announcement` 仍 `'dedup'`=2000）；③ **BR-SA-13 改写**——池上限不再"与 `MAX_DEDUP_CODES` 同源"，改为**按域独立配置**（`'fixed:N'` 与 `'dedup'` 并存），并补收缩理由与内存影响；④ **§3.5 顺带更正遗留数值漂移**：`quote.ttl` 旧记 `8|120` → 现行 **`4|120`**（`quote` 于 v1.4 升 L0，`config.md` §3.2 早已是 `4|120`）；⑤ `_FAIL_LEDGER_MAX`（`5 × MAX_DEDUP_CODES = 10000`；`MAX_DEDUP_CODES` 未变）**不受影响**。**BR-SA-13 为语义同步；无接口 / 对外契约变更**；**未改代码 / SAD / PRD / API.md / README.md / `.opencode`；`_PROGRESS.md` 同步。**
> **v1.5 变更（台账收口：`REV-DES-21` 裁定关闭 · 只改文档，不改代码）**：**用户裁定（2026-09-18）**——`/stock/f10` **极少调用甚至基本上不会有请求调用** ⇒ **不设「仅单码 / 少量码」上限，不构成问题**；故 **`REV-DES-21` 缓解项自本版起关闭为「✅ 已裁定：不实现」**（**不再是待办**）。**§10#10 加裁定注**，且**保留「当前未强制」这一事实陈述**（现状的"未强制"= **知情接受，不是遗漏**，实际暴露面 ≈ 零）；**残留风险与触发条件**一并写明：**若将来该端点被大量调用**，须按「参数错误 ⇒ 400 + PRD AC + 详设 + 测试」**整链**补上限（届时另立 change-set）。**无实现变更 / 无对外契约变更 / 无接口变更**；测试编号仍 **SA-T1..T39**、偏差仍 **§10#1..26**（仅 §10#10 增注，不新增编号）。**未改代码 / `doc/arch/` / `doc/prd/` / `API.md` / `README.md` / `.opencode`；`_PROGRESS.md` 同步。**
> **v1.4 变更（溯源收口 + 引用时点约定 · 只改文档，不改代码）**：① **【溯源收口】** 头部上游 **SAD v1.3 → v1.12 / PRD v0.3 → v0.10**；「基础层接口权威」栏 **config v1.1 → v1.6 / cache v1.1 → v1.14 / metrics v1.1 → v1.8**（均指向**现行版本**）；§11 自检中残留的「按基础层 v1.1 契约使用」改为按**现行**契约（版本见头部）。② **【引用时点约定（新增）】**「接口权威」栏所列版本 = **本文最后一次同步时点的快照**；被引文档的**权威版本以其自身头部为准**——故该栏**落后一版不属漂移、无需每次追平**；**内容以被引文档为准，此栏仅用于定位**。**本模块的代码 / 契约形态 / BR / 测试编号 / 偏差零变更**（v1.3 正文逐字保留）；**未改代码 / SAD / PRD / API.md / README.md / `.opencode`；`_PROGRESS.md` 同步。**
> 本版修订（v1.3 契约同步，**只改文档、不改代码**）：① **新增码级取数器 `fetch_cls_stock_depth(stock_code, deadline=None, ttl=None, refresh_epoch=None)`**（五档盘口，`depth` 域；URL `_STOCK_DEPTH_URL?secu_code=…&field=five`；**空 dict / 20 档全 0 ⇒ 返回 `None`**；失败非致命）+ `_depth_store`（自持 depth 池 / 终点缓存，使 `DOMAIN_MATRIX['depth']` 的 pool_max/cache_max 成为活设置）；② **`fetch_cls_basic_info` 扩为三阶段**：阶段1 basic（致命）/ 阶段2 sector（非致命，7d sector 缓存）/ **阶段3 depth（非致命，只增字段 `result['depth']`）**；③ **空壳防御**：`code:200` 但 `secu_name`/`last_px` 全空、或 `data:{}` ⇒ 视为 **`upstream_error`**（不写缓存、不进阶段 2/3）；④ **`upstream_secu_code()` 全量应用**于 x-quote URL 构造（北交所点号形 `430047.BJ`；SH/SZ 前缀形）；⑤ **`BATCH_MAX_WORKERS` 8 → 20**（来源 `config.BATCH_MAX_WORKERS`）；⑥ **`refresh_epoch` 贯通**：`_fetch_rest_json` → `_rest_fetch` → `_call_fetcher`/`_fetch_one`/`_run_batch`/`_process_chunk`/`_handle_cached_batch` → 各 fetcher/handler；**终点缓存命中追加 `written >= refresh_epoch`**（仅刷新路径，`None` 逐字不变）；⑦ `_DOMAIN_STORES` 增 `depth` 行；`cached_batch` 域枚举扩 `depth`。
> 本版修订（P7b 契约同步，**只改文档、不改代码**）：① `_prefetch_advance(name, visited, len(codes))`——**访问即推进**（含无数据/冷却跳过）；② 新增 `_LOCAL_BUDGET` 哨兵：**本地预算耗尽不计入 `_fail_ledger`**（客户端仍见 `upstream_timeout`）——**取代 v1.1 的 REV-DES-15 裁决②**；③ `_fail_ledger` 满额 O(1) 淘汰（插入序）+ 冷却发布 1 次/5s 限速 + 老化扫描限频；④ `_direct_fetch` REST 腿改经 `fetch_json`（缓存/负缓存/单飞），单次逻辑取数只计一次 `upstream_fetch_total`，删除 `_classify_exc`/`_urlopen_timeout`；⑤ `_fetch_one` 回退仅**调用帧** TypeError 降级（`_call_fetcher`），保留 deadline/ttl；⑥ `_fetch_rest_json` 向 `fetch_json` 传 `deadline`、删除前置闸门；⑦ 池/终端缓存/账本键一律 `canonical_code`，响应按请求原拼写回填；⑧ `fetch_cls_f10` "有数据但不匹配" ⇒ 计 `cdp_unavailable`；导航锁限时 `_acquire_nav_lock`；⑨ 新增 `_basic_sector_*`（detail 派生行业名缓存，BUG-P6C-01）。
> 沿用 v1.1：REV-DES-20260915-002（REV-DES-10/12/13/14/16/17/18/21 + 登记项①-⑦）
> 模块路径 `china_finance_rss/stock_api.py` · 归属 **Layer 2（业务/数据获取层）**
> 上游 SAD `doc/arch/SAD.md` **v1.12**（★ v1.4 溯源更正：原误记 v1.3；权威以 SAD 头部为准）（§2.1 缓存分层 INV-1a/INV-1b / §2.2 R-3 R-6 / §2.3 D-2 D-4 D-6 / §2.4 / §2.6 / §3 stock_api 行 / ADR-001/005/008/009/014）
> 上游 PRD `doc/prd/perf-stability-optimization.md` **v0.10**（★ v1.4 溯源更正：原误记 v0.3；权威以 PRD 头部为准）（AC-A3/A6/A7/A9/A10、AC-E2/E6/E9、AC-S1/S6/S7/S10；R12/R13/R14/R16）
> 基础层接口权威 `doc/detailed/config.md` **v1.6** · `cache.md` **v1.14** · `metrics.md` **v1.8**（★ v1.4 溯源更正：原误记 config/cache/metrics 均 v1.1；均指向**现行版本**）
> ★ **引用时点约定**：上列「接口权威」版本 = **本文最后一次同步时点的快照**；被引文档的**权威版本以其自身头部为准**——故该栏**落后一版不属漂移、无需每次追平**；**内容以被引文档为准，此栏仅用于定位**。
> 端锁定 🟠 STABLE（6 个 `/stock/*` 批量 handler 的**响应字段集合**不变；仅新增 `_errors`/截断保留键，由 `cache.build_batch_response` 统一挂载）

## 1. 模块职责与边界

### 1.1 职责

1. **6 个 `/stock/*` 批量端点的数据获取与组装**：`/stock/data`、`/stock/fundflow`、`/stock/timeline`、`/stock/f10`、`/stock/basic_info`、`/stock/announcement`。
2. **期限贯通（R13 / ADR-009）+ 新鲜度下限（P7b）**：全部码级取数器签名统一为 `fetch_*(code, deadline=None, ttl=None, refresh_epoch=None)`，从 handler → `_handle_cached_batch` → `_process_chunk` → `_run_batch` → `_fetch_one` → `_call_fetcher` → fetcher → `cache.fetch_json` / `evaluate_fetch` **一路传递**（REST 经 `fetch_json` 唯一出口，本模块不再自算超时）；`refresh_epoch` **仅**由 SSE 计划刷新路径设置（无默认值），消除"`TypeError` 回退 ⇒ 期限/下限静默丢弃"。
3. **TTL 同源（INV-1a 落点 2）**：`_MAX_CACHE_AGE` 删除；终点缓存 TTL 与传给 `fetch_json(ttl=)` 的 TTL **来自同一次 `cache_policy(domain)` 调用的同一个变量**。
4. **共享失败状态层 `_fail_ledger`（ADR-014）**：`(domain, code)` 码级 120s 冷却，**批量路径与 4 个 prefetch 循环共用同一账本**；删除 4 处局部 `fail_blacklist`。
5. **批量返回结构 `(results, errors)`（SAD §2.3 D-2）**：`_run_batch` / `_process_chunk` / `_handle_cached_batch` 返回二元组；handler 交 `cache.build_batch_response` 组装。
6. **池与终点缓存解耦（P1-1）**：池淘汰**不再** `cache.pop`；终点缓存由 `cache_max` 独立 LRU 自管。
7. **可观测（AC-S10）**：`code_cooldown_list` / `cache_entries{domain}` / `upstream_fetch_total{domain}` / `upstream_fail_total{kind}`。
8. **分片轮转的**游标原语与只读缓存视图：`_prefetch_rotate`/`_prefetch_advance`（轮转语义）、`cached_batch(domain, codes)`（供 `stream._refresh_pool` 的 `cached(active−slice)` 部分）。
9. **代码归一（P7b / P1-6）**：池键 / 终点缓存键 / `_fail_ledger` 键**一律 canonical**（`config.canonical_code`）；响应按**请求原拼写**回填（`_process_chunk` 的 `alias` 映射），使 `600519.SH` 与 `sh600519` 命中同一份缓存。
10. **detail 派生行业名缓存（P7b / BUG-P6C-01）**：`_basic_sector_cache` + `_basic_sector_get/put`——`fetch_cls_basic_info` 阶段 2 的行业名二次 REST 调用被 7 天 `sector` 策略缓存吸收。
11. **五档盘口 `depth` 域（v1.3 / BUG-SSE-DEPTH-01）**：`fetch_cls_stock_depth` 取五档盘口（20 档 + `preclose_px`）并**挂在 `fetch_cls_basic_info` 的同一 `quote` 终点缓存条目上**（`result['depth']`），使 `quote` 刷新每码 2 次上游调用（basic + depth）；`_depth_store` 以 `cache_policy('depth')` 自持 depth 池/终点缓存。**空壳（`data:{}` / 20 档全 0）⇒ `None`**，绝不伪造全 0 盘口。
12. **计划刷新下限（v1.3）**：`refresh_epoch` 使"设定 tick 的域"的终点缓存命中额外要求 `written >= refresh_epoch`（§4.8 BR-SA-38），消除 TTL==tick 时的隔拍旧值。

### 1.2 明确不做

- **不实现 HTTP 层截断**：`_truncated`/`_dropped_count` 的 `dropped` 由 `server._handle_stock_batch` 计算并**作为参数传入** handler（本模块不做 `>50` 判定）。
- **不实现 SSE 分片调度**：`stream._refresh_pool` 的切片大小/`stream_refresh_lag_ticks`/`tick degraded` 属 `stream.py`（本模块只提供游标原语 + `cached_batch` 只读访问器 + `BATCH_MAX_WORKERS` 公开常量，见 §10#9）。
- **不产生 `upstream_timeout`/`upstream_error` 的重复计数**：网络层失败已由 `cache._record_failure` 计入 `upstream_fail_total`（`cache.md` BR-CACHE-6）；本模块只计**自建** kind（`cdp_unavailable`、`code != 200`、**JSON 解码失败/上游非 dict**），且全部在 `_fetch_rest_json`/取数器内**就地计一次**（REV-DES-12/13/14）。
- **不把"自己的预算耗尽"当成上游失败（P7b）**：本地 `deadline` 已过 ⇒ `_LOCAL_BUDGET` 哨兵 ⇒ 对客户端呈现 `upstream_timeout` 形态，但**不写 `_fail_ledger`**（见 §2.3 / BR-SA-34）。
- **不改 `_announcement_url` 签名逻辑**（CLS sign）；不改 CDP 页面选择顺序与 anti-ban 策略（CDP 优先/回退顺序保留）。
- **不新增第三方依赖**；**不新增后台线程**（仍为 4 条 prefetch loop）。

### 1.3 layerIsolation 约束

`tech-stack.json` 未对 `stock_api.py` 单列 `layerIsolation` 条目，但须遵守分层方向与项目约定（§1.4 依赖图）。

```
允许 import：
  标准库：json / logging / threading / time(from time import sleep,time) /
          collections.OrderedDict / concurrent.futures.ThreadPoolExecutor,as_completed /
          urllib.parse.urlencode
  包内  ：config（cache_policy, canonical_code, upstream_secu_code, BATCH_MAX_WORKERS, REQUEST_TIMEOUT,
                  MAX_DEDUP_CODES, _MAX_BATCH_SIZE, *_URL/_HEADERS（含 _STOCK_DEPTH_URL/_HEADERS）,
                  _F10_EXPECTED_KEYS, stock_nav_page_names, cdp_engine 槽）
          cache（fetch_json, _fill_missing, build_batch_response, FetchError）
          cdp_engine（page_data）          # ★ REV-DES-10：R18 防御取数的唯一来源
          metrics
          utils（cls_sign_params）
禁止 import：server / stream / market_api（反向依赖消费者或同层模块）
  —— cdp_engine 仅允许其模块级函数 page_data；其 CDPEngine/CDPPage 等其它名禁止 import
     （页面/引擎对象一律经 config.cdp_engine 槽获取）
```

> ★ **P7b 允许清单收紧**：`socket` / `urllib.request.Request,urlopen` / `VALID_STOCK_CODE` **已不再被本模块 import**（随 `_classify_exc` / `_urlopen_timeout` 删除与代码归一迁移，P1-6）。当前 REST 取数**只**经 `cache.fetch_json`（`_direct_fetch` 的 REST 腿亦同，P2-①）。

**依赖方向**（`←` 表分层顺序，非 import 关系）：

```
config（无依赖） ‖ metrics（零业务依赖叶子）
      ↑                              ↑
   cache ← {config, metrics}   cdp_engine ← {config, metrics}
      ↑                              ↑
 stock_api ← {config, cache, metrics, utils, cdp_engine}
      ↑
   server / stream
```

> ★ **REV-DES-10 同层依赖**：`stock_api → cdp_engine`（Layer 2 → 基础设施，单向）。**无环**：`cdp_engine` 的 `forbiddenImports` 仅 `server / stream / stock_api`，且其不 import 任何业务模块。该依赖由编排层在 `SAD §3` 与 `tech-stack.json` 同步登记（本 agent 不改 SAD/tech-stack）。

### 1.4 与基础层接口的对齐（逐项，不得偏离）

| 基础层接口 | 本模块用法 |
|-----------|-----------|
| `config.cache_policy(domain, now=None) -> dict` | 每个 handler **调用一次**取 `{tier, ttl, pool_refresh, pool_max, cache_max}`；`policy` 对象向下传递（`ttl` 同源同变量） |
| `config.REQUEST_TIMEOUT`（=10） | REST 单次预算上界；`fetch_json` 的 `timeout` 由 `cache._effective_timeout(url, deadline)` 取 `min(基础预算, 剩余 deadline)`（P7b：本模块不再自算 `_urlopen_timeout`） |
| `config.canonical_code(code) -> str \| None` | ★ **P7b / P1-6**：池键 / 终点缓存键 / `_fail_ledger` 键 / CDP 比较的**唯一归一入口**；`None` ⇒ 无效码（HTTP 入口 400 / 本模块 `results[code]=None`） |
| `config.upstream_secu_code(code) -> str` | ★ **v1.3**：x-quote URL 的 `secu_code` **wire 拼写**唯一权威（SH/SZ = 前缀形；BSE = 点号形 `430047.BJ`）；仅 URL 构造调用，身份键不变 |
| `config.BATCH_MAX_WORKERS`（=20） | ★ **v1.3**：`stock_api.BATCH_MAX_WORKERS` / `_BATCH_MAX_WORKERS` 的来源；`_run_batch` 与 `stream.refresh_capacity` 共用 |
| `cache.fetch_json(url, headers=None, ttl=None, encoding='utf-8', deadline=None) -> str` | 唯一 REST 取数入口（**含 `_direct_fetch` 的 REST 腿**）；**失败恒 `raise FetchError(kind)`**（四段式 + 负缓存）；`deadline` 透传（P7b） |
| `cache.FetchError(kind).kind` / `.KINDS` | kind ∈ `{upstream_timeout, upstream_error, cdp_unavailable}`；本模块自建 `cdp_unavailable` 与语义 `upstream_error` |
| `cache.build_batch_response(requested, results, errors=None, dropped=0) -> dict` | 6 个 handler 的**唯一组装点**；保留键语义由该纯函数保证 |
| `cache._fill_missing(result, data, expected_keys)` | f10 组装（`data` 已由 `cdp_engine.page_data` 保证为 dict） |
| `cdp_engine.page_data(page) -> dict \| None` | ★ **REV-DES-10**：`fetch_cls_f10` 的**唯一**页面数据读取入口（R18）；返回 `None` ⇒ 该页无数据。本模块**禁止**直接调 `page.get_data()` |
| `metrics.incr(name, n=1, key=None)` / `metrics.set_gauge(name, value, key=None)` | 4 个指标（§4.6），名 ∈ `metrics._KNOWN`（冻结注册表） |

---

## 2. 接口契约

> **命名与签名总约定（v1.3）**：码级取数器一律 `fetch_*(code, deadline=None, ttl=None[, refresh_epoch=None])`；`ttl=None` ⇒ fetcher 内部回退 `cache_policy(domain)['ttl']`（保证直接调用亦同源）；`refresh_epoch=None`（REST / prefetch 全部调用方）⇒ 与旧行为逐字一致（纯增量提示）。非码取数器不在此列。

### 2.1 上游取数器全清单（R13 期限贯通 + 新鲜度下限）

| # | 签名 | 域 | 上游路径 | `deadline` 用法 | `ttl` / `refresh_epoch` |
|---|------|----|---------|----------------|-----------|
| 1 | `fetch_cls_fundflow(stock_code, deadline=None, ttl=None, refresh_epoch=None) -> Any \| None` | `fundflow` | REST `_FUNDFLOW_BASE_URL` → CDP `evaluate_fetch` 回退 | 入口判定 + `_evaluate_fetch_any(deadline=)` | `_rest_fetch(..., refresh_epoch)`（epoch 只到 REST 腿 URL 缓存；CDP 腿无缓存） |
| 2 | `fetch_cls_timeline(stock_code, deadline=None, ttl=None, refresh_epoch=None) -> Any \| None` | `timeline` | REST `_TIMELINE_BASE_URL` → CDP 回退 | 同上 | 同上 |
| 3 | `fetch_cls_f10(stock_code, deadline=None, ttl=None) -> dict \| None` | `f10` | **CDP 导航**（`_navigate_f10` + `cdp_engine.page_data`） | 导航/求值预算 `d = deadline or time()+_CDP_CALL_TIMEOUT` | `ttl` 参数保留、**不使用**（无 URL 缓存）；**不收 `refresh_epoch`** |
| 4 | `fetch_cls_basic_info(stock_code, deadline=None, ttl=None, refresh_epoch=None) -> dict \| None` | `quote` | **三阶段**：`_BASIC_INFO_BASE_URL`（阶段1）→ `_STOCK_DETAIL_BASE_URL`（阶段2 行业）→ `_STOCK_DEPTH_URL`（阶段3 depth） | 入口判定 + 各阶段 `_fetch_rest_json(deadline=)` | 阶段 1/3 传 `refresh_epoch`（稳态 2 次调用均真回源）；**阶段 2 留 TTL**（7d sector 缓存吸收） |
| 5 | `fetch_cls_announcement(stock_code, deadline=None, ttl=None) -> Any \| None` | `announcement` | REST sign URL → CDP 回退 | 同 #1 | `ttl`；**不收 `refresh_epoch`**（非热路径） |
| 6 | `fetch_cls_stock_detail(stock_code, deadline=None, ttl=None) -> Any \| None` | `quote` | REST `_STOCK_DETAIL_BASE_URL` | 入口判定 + `_fetch_rest_json(deadline=)` | `ttl`；**不收 `refresh_epoch`**（`/stock/data` 非热路径） |
| 7 | `fetch_cls_stock_depth(stock_code, deadline=None, ttl=None, refresh_epoch=None) -> dict \| None` | `depth` | REST `_STOCK_DEPTH_URL?secu_code=…&field=five`（无 sign / 无 CDP） | `_fetch_rest_json(deadline=)`（**失败非致命**：返回 `None`，不 raise） | 阶段 3 由 `fetch_cls_basic_info` 传入（含 epoch）；直接调用回退 `cache_policy('depth')['ttl']` |

**prefetch 专用取数器**（CDP 浏览器上下文 anti-ban 优先，REST 腿**经 `fetch_json`**，P7b）：

| # | 签名 | 域 | 说明 |
|---|------|----|------|
| 8 | `_fundflow_direct_fetch(stock_code, deadline=None) -> Any \| None` | `fundflow` | CDP `evaluate_fetch` 优先 → **`_fetch_rest_json`（即 `fetch_json`）回退**；失败 `raise FetchError`；`upstream_fetch_total` **单次逻辑取数只计 1 次** |
| 9 | `_timeline_direct_fetch(stock_code, deadline=None) -> Any \| None` | `timeline` | 同 #8 |
| 10 | `_announcement_direct_fetch(stock_code, deadline=None) -> Any \| None` | `announcement` | 同 #8 |

> ★ **P7b（P2-①）**：REST 腿**不再**是裸 `urlopen` 第二条 HTTP 入口，而是统一走 `cache.fetch_json` ⇒ 获得 URL 正缓存 + 负缓存 + leader/follower 单飞；`_classify_exc` / `_urlopen_timeout` **已删除**（其职责分别归 `cache._classify` 与 `cache._effective_timeout`）。

**CDP 求值辅助**：`_evaluate_fetch_any(url, deadline=None) -> dict | None`（页面顺序与 per-page 预算不变；`deadline` 收缩总窗口）。

**返回/异常语义（全部取数器一致）**

| 结果 | 语义 | 下游 |
|------|------|------|
| 数据客体（非 `None`） | **成功** | 写缓存 + `_fail_ledger` 清账 |
| `None` | **无数据 / 无效码**（上游 200 但无内容、CDP 导航成功但无匹配） | 值 `null` ∧ **不在** `_errors`；不计失败、不清账（BR-SA-6） |
| `raise FetchError(kind)` | **取数失败**（超时/异常/`cdp_unavailable`/语义失败） | `_errors[code]=kind`；计失败、可能触发冷却 |

### 2.2 批量内部管道

```python
def _run_batch(fetcher, codes, deadline=None, ttl=None, concurrent=True, refresh_epoch=None) -> tuple[dict, dict]:
def _process_chunk(codes, domain, policy, fetcher,
                   pool=None, cache=None, cache_ts=None, lock=None,
                   deadline=None, after=None, concurrent=True, refresh_epoch=None) -> tuple[dict, dict]:
def _handle_cached_batch(codes, domain, policy, fetcher,
                         pool=None, cache=None, cache_ts=None, lock=None,
                         budget=None, per_call_timeout=REQUEST_TIMEOUT,
                         after=None, concurrent=True, refresh_epoch=None) -> tuple[dict, dict]:
```

- **返回**：`(results, errors)` —— `results` 覆盖请求码序全部码（无效码 → `None`）；`errors` 仅含失败码 → 枚举 kind。
- `concurrent=False`：串行（CDP `navigate_stock` 会变更共享导航页，必须串行）；`True`：`ThreadPoolExecutor(max_workers=min(BATCH_MAX_WORKERS, len(codes)))`。
- `pool is None` ⇒ 不使用去重池；`cache is None` ⇒ 不使用终点缓存（仅 `fetch_json` URL 缓存兜底，用于 `/stock/data`）。
- `budget`：端到端绝对期限（epoch 秒）；`None` ⇒ 无整体预算（仅单次调用超时兜底）。
- **`refresh_epoch`（v1.3，计划刷新下限）**：刷新轮起点（epoch 秒），**仅 SSE 路径**经 `handle_cls_basic_infos`/`handle_cls_fundflow`/`handle_cls_timeline` 传入；`None`（REST handler + 全部 prefetch）⇒ 逐字旧行为。三层贯通：① `_process_chunk` 的终点缓存命中额外要求 `written >= refresh_epoch`（与 TTL 判定**并列**，§5.6）；② 经 `_run_batch → _fetch_one → _call_fetcher` 下传 fetcher；③ fetcher 经 `_rest_fetch` 把 epoch 传给 `cache.fetch_json(refresh_epoch=)`（URL 正缓存同样只认本轮写入）。**写路径不感知它**（`_cache_store`/`fetch_json` 写仍用完整域 TTL）。

### 2.3 `_call_fetcher` / `_fetch_one`（期限/失败分类的**唯一**收口）

```python
def _call_fetcher(fetcher, code, deadline, ttl, refresh_epoch=None) -> Any
def _fetch_one(fetcher, code, deadline=None, ttl=None, refresh_epoch=None) -> tuple[Any | None, str | None]:
```

| 分支 | 返回 |
|------|------|
| `deadline is not None and time() > deadline` | `(None, _LOCAL_BUDGET)` —— **不触网**（`_LOCAL_BUDGET` 是**内部哨兵**，见下） |
| fetcher 返回数据 | `(data, None)` |
| fetcher 返回 `None` | `(None, None)`（无数据） |
| fetcher `raise FetchError(kind)` | `(None, kind)` |
| fetcher 抛其它异常 | `(None, 'upstream_error')` |

**`_call_fetcher` 的降级规则（P7b / P2-④；★ v1.3 增 `refresh_epoch` 档）**：按关键字形式依次尝试——`refresh_epoch is not None` 时**先**试 `{deadline, ttl, refresh_epoch}`，随后 `{deadline, ttl}` → `{deadline}` → `{ttl}` → `{}`（`None` 时跳过第一档，即原 4 档）；**仅在"调用帧" TypeError**（参数绑定失败，即签名不匹配的测试替身）时才降级到下一档；若 TypeError 的 traceback 有 `tb_next`（说明异常抛自 fetcher **函数体内**）则**原样上抛**——在体内 TypeError 上重试会**把取数执行两次**。每档降级都保留 callable 能接受的 `deadline`/`ttl`，**预算与新鲜度下限永不被静默丢弃**。全部被拒 ⇒ `raise TypeError(f'{fetcher!r} does not accept (code, deadline, ttl)')`。

> **`_LOCAL_BUDGET` 哨兵（P7b / P1-1，取代 REV-DES-15 裁决②）**：值 `'__local_budget__'`，**故意不是 `FetchError.KINDS` 成员**。语义 = "**我们自己的**预算已耗尽，未做任何网络尝试"。`_fetch_one` 与 `_run_batch`（预算耗尽时不建线程）都返回该哨兵；`_process_chunk` 把它**翻译**为 `'upstream_timeout'` 交给客户端，但**绝不写入 120s 冷却账本**——与 `cache.md` BR-CACHE-23 的同源规则一致（"本地等待预算，不是上游失败，永不记录"）。若记账，一次慢 batch 就会冷却整条池尾，形成自伤正反馈。
>
> **口径变更说明**：v1.1 的 REV-DES-15（"预算耗尽的 `upstream_timeout` 照常计入冷却账"）**已被实现取代**；§4.2 BR-SA-34 与 §10#14 已按新口径重写，SA-T25 同步改写。

### 2.4 公共批量 handler（对 `server` / `stream` 的契约）

```python
def handle_cls_fundflow(codes, deadline=None, dropped=0, refresh_epoch=None) -> dict
def handle_cls_timeline(codes, deadline=None, dropped=0, refresh_epoch=None) -> dict
def handle_cls_f10(codes, deadline=None, dropped=0) -> dict
def handle_cls_basic_infos(codes, deadline=None, dropped=0, refresh_epoch=None) -> dict
def handle_cls_announcement(codes, deadline=None, dropped=0) -> dict
def handle_cls_stock_batch(codes, deadline=None, dropped=0) -> dict
```

| 参数 | 类型 | 默认 | 语义 |
|------|------|------|------|
| `codes` | `Sequence[str]` | — | 请求码序（**保序**，可含重复/无效码） |
| `deadline` | `float \| None` | `None` | 端到端绝对期限；`None` ⇒ handler 自取默认预算（§4.5） |
| `dropped` | `int` | `0` | **HTTP 层**截断码数（`server._handle_stock_batch` 计算后传入） |

**返回**：`cache.build_batch_response(codes, results, errors, dropped=dropped)` 的结果（扁平映射 + 可选保留键）。
**约定**：`handle_*` **返回 dict 不抛**（tech-stack `namingRules.handlers`）；`build_batch_response` 为总函数，异常不会外溢。

| 路由 → handler | 域 | `pool` | `cache` | `concurrent` | `per_call_timeout` | `after` | 默认预算 |
|----------------|----|--------|---------|--------------|--------------------|---------|---------|
| `/stock/fundflow` → `handle_cls_fundflow` | `fundflow` | `_fundflow_pool` | `_fundflow_cache` | `True` | `REQUEST_TIMEOUT` | — | `_BATCH_BUDGET_REST` |
| `/stock/timeline` → `handle_cls_timeline` | `timeline` | `_timeline_pool` | `_timeline_cache` | `True` | `REQUEST_TIMEOUT` | — | `_BATCH_BUDGET_REST` |
| `/stock/f10` → `handle_cls_f10` | `f10` | `_f10_pool` | `_f10_cache` | **`False`** | `_CDP_CALL_TIMEOUT` | `_populate_sector_from_f10` | `_BATCH_BUDGET_CDP` |
| `/stock/basic_info` → `handle_cls_basic_infos` | `quote` | `_basic_info_pool` | `_basic_info_cache` | `True` | `REQUEST_TIMEOUT` | — | `_BATCH_BUDGET_REST` |
| `/stock/announcement` → `handle_cls_announcement` | `announcement` | `_announcement_pool` | `_announcement_cache` | `True` | `REQUEST_TIMEOUT` | — | `_BATCH_BUDGET_REST` |
| `/stock/data` → `handle_cls_stock_batch` | `quote` | **`None`** | **`None`** | `True` | `REQUEST_TIMEOUT` | — | `_BATCH_BUDGET_REST` |

> `/stock/data` 无去重池、无终点缓存（仅 `fetch_json` URL 缓存）——登记见 §10#4；仍走同一冷却/错误管道（AC-S6/A10 覆盖 6 端点）。
>
> ★ **v1.3**：`handle_cls_basic_infos` / `handle_cls_fundflow` / `handle_cls_timeline` 增第 4 参 **`refresh_epoch=None`**（SSE 计划刷新下限，§2.2）；`handle_cls_f10` / `handle_cls_announcement` / `handle_cls_stock_batch` **签名不变**（非热路径，不收 epoch）。`handle_cls_basic_infos` 的 `quote` 客体现可含 `depth` 子键（阶段 3）。

### 2.5 共享失败状态层 `_fail_ledger`（ADR-014）

```python
def _fail_ledger_prune_locked(now) -> int           # 调用方须持 _fail_ledger_lock（P7b 新增）
def _fail_ledger_get(domain, code, now=None) -> list | None
def _fail_ledger_record_failure(domain, code, kind, now=None) -> None
def _fail_ledger_clear(domain, code) -> None
def _cooldown_snapshot_locked(now) -> list[list]    # 调用方须持锁
def code_cooldown_list(now=None) -> list[list]      # [[domain, code, cooldown_until], ...]
```

- `_fail_ledger_get` 自带**老化判定**（BR-SA-8）：条目已老化 ⇒ 删除并返回 `None`；返回 `list(entry)` **副本**（调用方不得原地改账）。
- `code_cooldown_list()` 只返回 `cooldown_until > now` 的条目（**可枚举清单**，AC-S10/S6）。
- **P7b 记账节流（S1-3 / P1-4）**：`_fail_ledger_prune_locked(now)` 把 O(n) 老化扫描限频到 `_FAIL_LEDGER_PRUNE_INTERVAL(5.0s)`；硬上限淘汰改为 **O(1)**（`dict` 保插入序 ⇒ `pop(next(iter(...)))` 丢最早注册的键，取代原全表 `sorted`）；`code_cooldown_list` 的发布限频到 `_COOLDOWN_PUBLISH_INTERVAL(5.0s)`（**包含冷却开启**那一次，不再让 inactive→active 跳过节流）。⇒ n 次失败风暴由 O(n²) 降为 O(n)。
- **发布位置**：`metrics.set_gauge('code_cooldown_list', snapshot)` 在**释放 `_fail_ledger_lock` 之后**调用（锁内只取快照）。

### 2.6 只读缓存视图（供 `stream._refresh_pool`）

```python
def cached_batch(domain: str, codes, now=None) -> dict:
```

- **无网络**：读取 `domain` 终点缓存中 **TTL 未过期** 的条目，返回 `{code: data}`；命中即 `move_to_end`（LRU touch）。
- `domain` ∈ `{quote, depth, fundflow, timeline, f10, announcement}`（★ v1.3 增 `depth`）；未知 domain → `{}` + `log.warning`（不抛）。
- **P7b 代码归一**：查询键先过 `config.canonical_code(code)`（`None` ⇒ 跳过该码）；**返回结果仍以请求原拼写为键** ⇒ 传 `600519.SH` 的调用方与传 `sh600519` 的调用方读到**同一份**条目、各自拿到自己请求的键名。
- 用途：`stream._refresh_pool` 组装 `snapshot = fresh(slice) ∪ cached(active − slice)`（SAD §2.2 R-6）。

### 2.7 游标原语（保留 + 复用）

```python
def _prefetch_rotate(pool, lock, key) -> list     # 保留（既有测试依赖）
def _prefetch_advance(key, visited, total) -> None # ★ P7b 形参名 processed → visited
def _prefetch_slice(pool, lock, key, size) -> tuple[list, int]:
    """本轮切片（≤size）+ 切片后游标（供 prefetch/stream 共用轮转语义）。"""
```

- `_prefetch_rotate` **签名与语义逐字保留**；`_prefetch_advance` 的**第二形参语义已改**：`visited` = 本轮**已访问**（消费掉）的码数，**含无数据与冷却跳过** —— 见 §2.8 与 BR-SA-35。
- `_prefetch_slice` 为**新增纯函数**：`rotate` 后取头部 `size` 个，返回 `(slice_codes, next_cursor_value)`；**不修改**游标（由调用方 `_prefetch_advance` 推进），使"取切片"与"推进游标"解耦，便于 stream 记录 `stream_refresh_lag_ticks`。

### 2.7b detail 派生行业名缓存（P7b / BUG-P6C-01）

```python
def _sweep_basic_sector_locked(now) -> None        # 调用方须持 _basic_sector_lock
def _basic_sector_get(code, now=None) -> str | None
def _basic_sector_put(code, sector, now=None) -> None
```

- `_basic_sector_cache`：`code -> {'sector': str, 'ts': float}`，**独立于 `_sector_cache`**（后者存 F10 `IndustryName` 前缀，字段语义不同，不得串用）。
- TTL / 上限一律取 `cache_policy('sector')`（7d / 2000）；空 `sector` **不缓存**（下次重试）。
- **无专属 gauge**：指标名与标签已冻结（`metrics.md` §3.2）⇒ `cache_entries{sector}` 仍归 `_sector_cache_put`。

### 2.8 4 个 prefetch 循环（保留名，共用 §2.5 账本）

```python
def _prefetch_loop(name, domain, fetch_one, pool, cache, cache_ts, cache_lock,
                   after=None, per_call_budget=REQUEST_TIMEOUT) -> None
def _fundflow_prefetch_loop() -> None
def _timeline_prefetch_loop() -> None
def _f10_prefetch_loop() -> None
def _announcement_prefetch_loop() -> None
```

- 4 个公开名**保留**（`server.py:57-61` import）；内部统一走 `_prefetch_loop`（DRY）。
- 局部 `fail_blacklist` **删除**，改读写 `_fail_ledger`（同域同账）。
- 间隔 = `cache_policy(domain)['pool_refresh']`（**不再** `max(常量, tier)`；`config.md` §3.2 保证 `pool_refresh >= ttl`）。
- **P7b 游标推进（S1-2）**：循环内 `visited += 1` 紧跟在"取到该码"之后、**冷却判定之前** ⇒ **访问即推进**（含冷却跳过、含无数据）。轮末 `_prefetch_advance(name, visited, len(codes))`。**理由**：只计"已写数据"或"未跳过"会让游标在"取到但无数据"（`None` 是成功但空，永不计数）时冻结 ⇒ 头部被反复重取、池尾永不到达。
- **P7b 单次调用预算（REV-DES-16 保留）**：`call_deadline = min(pass_deadline, now + per_call_budget)`；`_f10_prefetch_loop` 传 `per_call_budget=_PREFETCH_CDP_CALL_TIMEOUT(4)`（单码 ≤4s），其余域默认 `REQUEST_TIMEOUT(10)`。

### 2.9 保留不变的既有公开面

| 名称 | 变更 |
|------|------|
| `handle_cls_stock(stock_code) -> Any \| None` | **保留为兼容薄封装**（`fetch_cls_stock_detail` + 吞 `FetchError` 返回 `None`）；★ v1.3 更正：当前 `server.py` **已不 import 它**（`server.md` v1.2 import 面更正），保留仅为旧调用方兼容，无路由引用 |
| `_announcement_url(stock_code) -> str` | 不变 |
| `_populate_sector_from_f10(data, code)` / `_sector_cache_put` / `_sweep_sector_cache` | 保留；TTL/上限改读 `cache_policy('sector')` |
| `_stock_nav_pages()` / `_iter_nav_pages()` / `_company_info_matches` / `_get_page_fetch_lock` / `_page_fetch_locks` / `_evaluate_fetch_any` | 不变 |
| `_navigate_f10(page, stock_code, deadline)` | **P7b 变更**：锁等待改为**限时** `_acquire_nav_lock(page, remaining)`（剩余 <2s 直接 `False`）；仍持有 `page._navigate_lock`（**RLock**，故与调用方 `fetch_cls_f10` 的外层限时获取可重入嵌套） |
| `_acquire_nav_lock(page, remaining) -> bool` | **P7b 新增**：`page._navigate_lock.acquire(timeout=max(0,remaining))`；`remaining<=0` 或超时 ⇒ `False`（降级，不无限 park 请求线程与准入位） |
| 5 个终点缓存容器名与 5 个 pool 名 | **保留**；容器类型 `dict → collections.OrderedDict`（`dict` 子类，`dict(...)`/`clear`/`update`/`in`/`[]` 全部兼容，`test_stream.py:231-262` 不受影响）。★ v1.3：**新增第 6 组** `_basic_depth_pool`/`_basic_depth_cache`/`_basic_depth_cache_ts`/`_basic_depth_cache_lock`（`depth` 域，`_DEPTH_VALUE_FIELDS` 见 §5.9） |

---

## 3. 数据结构

### 3.1 `_fail_ledger`（共享失败状态层，yaml）

```yaml
_fail_ledger:                 # 键 = (domain, code) 元组（码级，非 URL 级）
  ["fundflow", "sh600519"]:
    - <int>                   # [0] fail_count      连续失败计数（成功即整条清除）
    - <float>                 # [1] cooldown_until  0.0 = 尚未触发冷却；否则 = 触发时刻 + 120
    - <str>                   # [2] kind            最近一次失败的枚举 kind（冷却期 _errors 用它）
    - <float>                 # [3] last_fail_ts     最近一次失败时刻（"连续"判定与账本老化基准）
_fail_ledger_lock: threading.Lock          # 保护整表（新增，独立锁，叶级）
FAIL_THRESHOLD: 3                          # 触发冷却的连续失败次数
FAIL_COOLDOWN: 120                         # 冷却秒数（= 旧 _FAIL_COOLDOWN）
_FAIL_DOMAINS: (quote, fundflow, timeline, f10, announcement)
_FAIL_LEDGER_MAX: len(_FAIL_DOMAINS) * MAX_DEDUP_CODES   # = 5 × 2000 = 10000（硬上限）
_COOLDOWN_PUBLISH_INTERVAL: 5.0            # ★ P7b：code_cooldown_list 发布节流（含冷却开启那一次）
_FAIL_LEDGER_PRUNE_INTERVAL: 5.0           # ★ P7b：O(n) 老化扫描节流
_cooldown_published_at: <float>            # ★ P7b：上次发布时刻（受 _fail_ledger_lock）
_fail_ledger_pruned_at: <float>            # ★ P7b：上次老化扫描时刻（受 _fail_ledger_lock）
```

> **条目为 4 元列表**（SAD §2.3 D-6 写 2 元 `[fail_count, cooldown_until]`）：`kind` 是"冷却期 `_errors` 仍给枚举码"的必要信息（SAD 原文已写 `errors[code] = entry_kind 或 'upstream_error'`）；`last_fail_ts` 实现"**连续**失败"的老化与账本有界（§4.2 BR-SA-8）。登记为细化偏差（§10#2）。

### 3.1b `_LOCAL_BUDGET` 哨兵（P7b）

```yaml
_LOCAL_BUDGET: '__local_budget__'   # 哨兵字符串；**故意不是 FetchError.KINDS 成员**
# 产生：_fetch_one（deadline 已过）/ _run_batch（预算已过，不建线程，逐码填充）
# 消费：_process_chunk 翻译为 'upstream_timeout' 交给客户端，但**不写 _fail_ledger**
# 不变式：任何进入 _fail_ledger 的 kind 必然 ∈ FetchError.KINDS（哨兵永不入账）
```

### 3.2 批量返回 `(results, errors)`

```yaml
results:                      # dict[str, Any|None]；覆盖本次 requested 的全部码（保序无关）
  sh600519: {price: 1.2}      # 成功 → 数据客体
  sz000001: null              # 无数据 / 无效码 / 失败（值域见下）
errors:                       # dict[str, str]；仅"取数失败"码；可为空 {}
  sz000001: upstream_timeout  # ∈ FetchError.KINDS
# 组装后（cache.build_batch_response 的输出，扁平映射）：
  sh600519: {price: 1.2}
  sz000001: null
  _errors: {sz000001: upstream_timeout}   # 仅非空时挂
  _truncated: true                        # 仅 dropped>0
  _dropped_count: 20                      # 与 _truncated 同现
```

**值域三分（唯一判别式）**

```yaml
success:  值 = 数据客体
no_data:  值 = null ∧ code ∉ _errors     # 无数据 / 无效码（既有语义不变）
failure:  值 = null ∧ code ∈ _errors     # 取数失败（本次新增可辨识）
```

### 3.3 域存储与缓存容器（yaml）

```yaml
_DOMAIN_STORES:               # domain -> (pool, cache, cache_ts, lock)
  quote:        (_basic_info_pool,    _basic_info_cache,    _basic_info_cache_ts,    _basic_info_cache_lock)
  depth:        (_basic_depth_pool,   _basic_depth_cache,   _basic_depth_cache_ts,   _basic_depth_cache_lock)   # ★ v1.3（五档盘口）
  fundflow:     (_fundflow_pool,      _fundflow_cache,      _fundflow_cache_ts,      _fundflow_cache_lock)
  timeline:     (_timeline_pool,      _timeline_cache,      _timeline_cache_ts,      _timeline_cache_lock)
  f10:          (_f10_pool,           _f10_cache,           _f10_cache_ts,           _f10_cache_lock)
  announcement: (_announcement_pool,  _announcement_cache,  _announcement_cache_ts,  _announcement_cache_lock)

# 容器类型：cache = collections.OrderedDict[code -> data]（真 LRU 访问序）
#           cache_ts = dict[code -> float]（写入时刻，TTL 基准 —— 注意：命中不刷新它）
#           pool    = dict[code -> float]（最近访问时刻，成员账 LRU）
# /stock/data（stock detail）不登记在此表：无 pool、无终点缓存（§10#4）
# ★ v1.3：depth 行虽在表内，但**不经 `_process_chunk` 写入**——`fetch_cls_stock_depth` 由
#   `fetch_cls_basic_info` 阶段 3 调用，自持 `_depth_store(code, data)` 用 cache_policy('depth')
#   触碰 pool + 写终点缓存（使 DOMAIN_MATRIX['depth'] 的 pool_max/cache_max 成为活设置，P2-9）。

_basic_sector_cache: dict[code -> {sector: str, ts: float}]   # ★ P7b：detail 派生行业名（§2.7b）
                                                              #   TTL/cap 同 cache_policy('sector')；独立锁 _basic_sector_lock
```

**池 vs 终点缓存（解耦，P1-1）**

```yaml
pool:                         # 成员账：code -> 最近触碰时刻
  上限: policy['pool_max']     # 按域独立（★ v1.6 PRF-MEM-01 收缩；★ v1.7 来源改经 env）：quote=env MAX_QUOTE_POOL、fundflow=env MAX_FUNDFLOW_POOL（默认各 1000）、timeline=env MAX_TIMELINE_POOL（默认 500）、depth/f10/announcement=2000 (='dedup'=MAX_DEDUP_CODES)
  淘汰: 超限时删最久未访问者，**仅 del pool[code]** —— 不再 cache.pop / cache_ts.pop
cache:                        # 数据 LRU + TTL
  上限: policy['cache_max']    # quote/fundflow=1000、timeline=500；depth/f10/announcement=500（★ v1.6 PRF-MEM-01；★ v1.7：仍为矩阵整数字面量，**不 env 化** = 内存硬界）
  淘汰: 写入超限时 cache.popitem(last=False) + cache_ts.pop(victim)（O(1)）★ v1.7 CR-04：cache_max 现 < 活跃码上界 2000 ⇒ 「覆盖活跃全集」不再成立，降级 = 本 LRU + 消费方 `stream._last_known` 结转
  TTL : now - cache_ts[code] < policy['ttl']  ⇒ 有效（命中只 move_to_end，**不改 cache_ts**）
```

### 3.4 分片轮转游标状态（yaml）

```yaml
_prefetch_cursor:             # dict[str, int]
  fundflow: 7                 # 各域 prefetch 已处理码数（round-robin 起点）
  timeline: 3
  f10: 0
  announcement: 12
  stream_refresh: 0           # ← stream._refresh_pool 复用的游标键（跨模块约定；值为起始下标，非 coverage_codes）
_prefetch_cursor_lock: threading.Lock        # 既有，保留

_PREFETCH_PASS_BUDGET: 60.0                  # 单轮 prefetch 时间预算（保留）
BATCH_MAX_WORKERS: 20                        # ★ v1.3：公开别名 = config.BATCH_MAX_WORKERS（stream 计算 coverage 用）
_BATCH_MAX_WORKERS: 20                       # 内部别名保留（兼容）
_BATCH_BUDGET_REST: 15                       # REST 批量端到端预算（= AC-E2「REST 回源 ≤15s」；REV-DES-17 引据更正）
_BATCH_BUDGET_CDP: 60                        # CDP 串行批量预算（保留现状；AC-E2 上界仅限 REST；REV-DES-21 风险登记 §10#10）
_CDP_CALL_TIMEOUT: 8                         # CDP 页面求值/导航单次预算（AC-S7 超时矩阵）
_PREFETCH_CDP_CALL_TIMEOUT: 4                # f10 prefetch 单码预算（REV-DES-16：作 per_call_budget 传入）
# prefetch 单次调用预算（REV-DES-16）：REST 域 = REQUEST_TIMEOUT(10)；f10 = _PREFETCH_CDP_CALL_TIMEOUT(4)
```

### 3.5 每域策略实值（`cache_policy(d)`，本模块消费口径）

```yaml
quote:        {ttl: 4|120,   pool_max: 1000, cache_max: 1000}   # basic_info（+ stock/data 仅用 ttl）；★ v1.6：ttl 8→4（v1.4 升 L0，遗留漂移更正）/ 池·缓存 2000→1000（PRF-MEM-01）；★ v1.7：pool_max 经 'env:MAX_QUOTE_POOL' 派生（默认 1000）
depth:        {ttl: 4|120,   pool_max: 2000, cache_max: 500}    # ★ v1.3 五档盘口（L0，与 quote 同拍）；★ v1.7：池保持 'dedup'(2000) 是**有意**——无 prefetch 循环、池仅 code→ts 账本，cache_max=500 才是内存界
fundflow:     {ttl: 8|120,   pool_max: 1000, cache_max: 1000}   # ★ v1.6 PRF-MEM-01：2000→1000；★ v1.7：pool_max 经 'env:MAX_FUNDFLOW_POOL' 派生（默认 1000）
timeline:     {ttl: 8|120,   pool_max: 500,  cache_max: 500}    # ★ v1.6 PRF-MEM-01：2000→500；★ v1.7：pool_max 经 'env:MAX_TIMELINE_POOL' 派生（默认 500）
f10:          {ttl: 300,     pool_max: 2000, cache_max: 500}
announcement: {ttl: 30|180,  pool_max: 2000, cache_max: 500}
sector:       {ttl: 604800,  pool_max: 2000, cache_max: 2000}
# 盘中 | 非盘中；'ttl' 同时用于终点缓存与 fetch_json（同源同变量）
# ★ v1.7：3 域 pool_max 数值不变但**来源改为 env 注册常量**（可免改码调参）；cache_max 仍为 config 矩阵整数字面量（内存硬界）
```

> ★ **行为变更登记（池上限放大）**：`_FUNDFLOW_MAX_POOL 500→2000`、`_TIMELINE_MAX_POOL 500→2000`、`_F10_MAX_POOL 300→2000`、`_ANNOUNCEMENT_MAX_POOL 300→2000`、`_BASIC_INFO_MAX_POOL 500→2000`（后者 `config.md` §2.4 已登记）。池是廉价 `code→ts` 账本，**数据内存改由 `cache_max` 独立 LRU 承担**（f10/announcement = 500），须纳入 AC-S9 内存总账复核（AR-8）。

> ★ **v1.6 更新（PRF-MEM-01 内存收缩 · 只改文档）**：上段的"池上限放大"（v1.1）已由 **PRF-MEM-01（2026-09-20）** 进一步收缩——`quote`/`fundflow`/`timeline` 的 `pool_max`/`cache_max` **同源缩小**为 `2000→1000`、`2000→1000`、`2000→500`（`config.md` v1.8/§10#24）。`depth`/`f10`/`announcement` 仍 `'dedup'=2000`（`f10`/`announcement` 的 `cache_max` 保持 500）。**内存护栏仍由 `cache_max` 独立 LRU 承担，只是上界下调**；后续 **AC-S9（AR-8）内存总账须按新值核对**。
> ★ **v1.7 更新（修复轮：pool 上限 env 化 + 降级面登记）**：上表 3 域 `pool_max` **数值不变**，但 `config.md` v1.9 把其 spec 由 `'fixed:N'` 改为 **`'env:MAX_*_POOL'`**（经**导入期冻结**的注册映射 `_POOL_MAX_ENVS` 取值；★ v1.10 更正：**不再 `globals()`**，运行期重绑定不生效）⇒ **pool 可调、`cache_max` 为硬界**。本模块**仅消费 `policy['pool_max']`/`policy['cache_max']`** ⇒ 代码零改动、行为默认不变。**CR-04 降级面**（新登记）：`cache_max`（1000/500）**首次 < 活跃码上界 `MAX_DEDUP_CODES`(2000)** ⇒ 终态缓存不再可能覆盖全部活跃码；`stream._refresh_pool` 的 C2 分片对"非本拍切片码"调 `cached_batch(domain, rest)`（只读终态缓存、不发网络），miss 码退化为 `stream._last_known` **结转**（进帧 `stale`）——**功能不破坏**（`_process_chunk` 对未命中码正常回源，无异常路径），代价是 `cached_batch` 命中率下降、上游取数上升。详见 BR-SA-13。

---

## 4. 业务规则

### 4.1 TTL 同源与新鲜度（INV-1a 落点 2）

| 编号 | 规则 |
|------|------|
| **BR-SA-1** | handler 每次请求 `policy = cache_policy(domain)` **只调用一次**，把 `policy` 向下传递；`_process_chunk` 的终点 TTL 与 `_run_batch(ttl=policy['ttl'])` 用的是**同一个 `policy['ttl']`**（"同一变量、同一次调用"，非两个相等常量） |
| **BR-SA-2** | 终点缓存有效期 = `now - cache_ts[code] < policy['ttl']`；`cache_ts` 是**写入时刻**，命中**不刷新**（滑动过期会破坏 AC-A4 的 TTL 上界） |
| **BR-SA-3** | 过期 ⇒ **拒读旧值 + 触发一次回源**（`missing` 收集后统一 `_run_batch`），绝不返回过期值（AC-A4） |
| **BR-SA-4** | 全模块禁止裸 TTL 字面量；`sector` 域的 TTL/上限亦经 `cache_policy('sector')`（`_SECTOR_CACHE_TTL/_SECTOR_CACHE_MAX` 删除） |

### 4.2 码级冷却（`_fail_ledger`，ADR-014 / AC-S6）

| 编号 | 规则 |
|------|------|
| **BR-SA-5** | **判定位置**：`_process_chunk` 中"终点缓存命中之后、`_run_batch` 之前"。命中冷却（`entry[1] > now`）⇒ `results[code]=None`、`errors[code]=entry[2]`、**不触网** |
| **BR-SA-6** | **计数口径**：仅"取数失败"（`errors[code]` 非空 = 异常/超时/`cdp_unavailable`）计数；成功 → `_fail_ledger_clear`；`None` 且无 kind（无数据）→ **不计数、不清账** |
| **BR-SA-7** | **触发**：`fail_count >= FAIL_THRESHOLD(3)` ⇒ `cooldown_until = now + FAIL_COOLDOWN(120)`；未达阈值 ⇒ `cooldown_until = 0.0`（仅累计） |
| **BR-SA-8** | **"连续"老化（账本有界的唯一机制）**：读/写时若 `now - last_fail_ts > FAIL_COOLDOWN` ⇒ 视为上一段失败已中断 → `_fail_ledger_get` **删除条目并返回 `None`**；`_fail_ledger_record_failure` 把 `fail_count` **重置为 1**。⇒ 每个"冷却周期"给该码 **最多 3 次**新尝试。**P7b 限频**：全表老化扫描只由 `_fail_ledger_prune_locked` 每 `_FAIL_LEDGER_PRUNE_INTERVAL(5.0s)` 执行一次；窗口内的过期条目仍由 `_fail_ledger_get` 的**逐键**判定即时老化 |
| **BR-SA-9** | **账本上限（P7b 改为 O(1)）**：`len(_fail_ledger) > _FAIL_LEDGER_MAX(10000)` ⇒ `pop(next(iter(_fail_ledger)))` —— `dict` 保插入序 ⇒ 丢**最早注册**的键，**每次淘汰 O(1)**（取代原"全表 `sorted` 取 `last_fail_ts` 最小者"）。原实现一旦到达上限，**每次写入**都要对 10001 个键排序（且失败风暴会刷新每个条目的 `last_fail_ts`，使老化永远腾不出槽位，S1-3 的 O(n²) 退化依旧） |
| **BR-SA-12b** | **发布节流（P7b）**：`code_cooldown_list` 的 O(n) 重建**至多每 `_COOLDOWN_PUBLISH_INTERVAL(5.0s)` 一次**，**包括"冷却开启"那一次转变**。≤5s 的发布延迟对 120s 冷却无实质影响；任何后续写入（失败或清除）都会刷新 gauge |
| **BR-SA-10** | **与 URL 级负缓存协同（不冲突）**：URL 负缓存（`cache`，`NEG_TTL=5s`）管"网络层 5s 不回源"；码级冷却（本层，120s）管"该码 120s 内整体降级"。冷却期内本层已短路 ⇒ 不会进入 `fetch_json`；5s 后 URL 层放开由本层继续拦截 |
| **BR-SA-11** | **批量与 prefetch 共用同一账**：`_process_chunk` 与 4 个 prefetch loop 读写**同一** `_fail_ledger`（同锁、同计数、同清理），使"批量看到的失败码"与"后台看到的失败码"一致 |
| **BR-SA-12** | **可枚举**：任何记账变更后发布 `metrics.set_gauge('code_cooldown_list', code_cooldown_list())`；元素形状 `[domain, code, cooldown_until]` |

> **P7b 口径变更（取代 REV-DES-15）**：BR-SA-6 的"取数失败"口径**不再包含"预算耗尽"**——后者由 `_LOCAL_BUDGET` 哨兵承载，翻译给客户端为 `upstream_timeout` 但**不入账**（BR-SA-34）。⇒ 慢上游 + 大 batch 不会自伤式冷却整条池尾；AC-S6「单码故障不扩散」回到成立。v1.1 的 SA-T25 已据实改写（§8）。

| 编号 | 规则（P7b 新增） |
|------|------|
| **BR-SA-34** | **本地预算耗尽不入账（`_LOCAL_BUDGET`）**：`_fetch_one` 在 `deadline` 已过时返回 `(None, _LOCAL_BUDGET)`；`_run_batch` 在 `time() >= deadline` 时**不创建线程**、逐码填 `_LOCAL_BUDGET`。`_process_chunk` 命中该哨兵 ⇒ `by_canon[canon]=None`、`err_canon[canon]='upstream_timeout'`，**且不调用 `_fail_ledger_record_failure`**（也不清账）。⇒ 客户端形态不变（仍 `_errors[code]='upstream_timeout'`），但账本只记录**真实上游失败**（与 `cache.md` BR-CACHE-23 同源：本地等待预算 ≠ 上游失败）。 |
| **BR-SA-35** | **prefetch 游标"访问即推进"**：`_prefetch_loop` 在取到每个码后**先** `visited += 1`、**再**做冷却判定与取数 ⇒ 冷却跳过与无数据（`None`）都计入 `visited`。轮末 `_prefetch_advance(name, visited, len(codes))`。⇒ 大池轮转不再在"头部取到但无数据"时冻结、池尾可被触达。**参数名** `_prefetch_advance(key, visited, total)`（原 `processed`）——`stream.py` 以 `_prefetch_advance(_STREAM_REFRESH_KEY, len(sl), n)` 复用同一语义。 |
| **BR-SA-36** | **键一律 canonical、响应按请求原拼写回填（P7b / P1-6）**：`_process_chunk` 以 `alias{请求拼写→canonical}` + `canons[]` 去重，池 / 终点缓存 / `_fail_ledger` 全部用 canonical 键；最终按 `alias` 把结果与错误映射回**每一个请求拼写**。`cached_batch` 同规则（查询 canonical、返回请求键）。⇒ `600519.SH` 与 `sh600519` 命中同一份缓存与同一条冷却；`build_batch_response` 仍以请求码为键。 |
| **BR-SA-37** | **`fetch_cls_f10` 的失败全收口（P7b / P1-6）**：5 条失败出口——engine 未就绪 / 无导航页 / 预算已耗尽 / **全部导航失败或全部页 `page_data=None`** / **取到 dict 数据但不属于该码**——**全部**经 `_raise_cdp_unavailable()`（计数一次 + raise），**不再有静默 `None`**。仅"上游返回但无内容"这类真正无数据才 `None`。导航锁等待由 `_acquire_nav_lock(page, remaining)` 限时，超时换页而非无限 park。 |
| **BR-SA-38** | **计划刷新下限 `refresh_epoch`（v1.3 / BUG-SSE-DEPTH-01）**：终点缓存命中判定 = `data is not None and now - written < ttl and (refresh_epoch is None or written >= refresh_epoch)`（**两条件并列**，§5.6 ③）；`_run_batch`/`_fetch_one`/`_call_fetcher` 原样下传；fetcher 经 `_rest_fetch` 把 epoch 传给 `cache.fetch_json(refresh_epoch=)`（URL 正缓存同一约束）。**仅 SSE 路径**传入（`handle_cls_basic_infos`/`handle_cls_fundflow`/`handle_cls_timeline`）；`refresh_epoch is None`（REST handler + 全部 prefetch）⇒ **逐字旧行为**。目的：`ttl == tick` 的域（quote/depth）写入晚于轮起点 δ ⇒ 下一拍命中仅 `tick−δ` 龄的条目、有效节拍减半；下限强制每拍真回源。**写路径不感知 epoch**（`_cache_store`/`fetch_json` 写仍用完整域 TTL） | `cache.md` BR-CACHE-31 |

### 4.3 池成员账与终点缓存解耦（P1-1 / R11）

| 编号 | 规则 |
|------|------|
| **BR-SA-13** | 池是**跨组共享的成员账**（`code → 最近触碰时刻`）；上限 = `policy['pool_max']`，**按域独立配置**（★ v1.6 PRF-MEM-01：`quote`/`fundflow`=`1000`、`timeline`=`500`；`depth`/`announcement`/`f10` 仍 `'dedup'`⇒`MAX_DEDUP_CODES=2000`）。v1.1 的"池上限与 `MAX_DEDUP_CODES` **同源**"口径**对这 3 域已失效**。**★ v1.7（修复轮 / CR-02 + CR-06）**：这 3 域的**来源**由 `'fixed:N'` 改经 **`'env:MAX_QUOTE_POOL'` / `'env:MAX_FUNDFLOW_POOL'` / `'env:MAX_TIMELINE_POOL'`** 派生（`config.py` 经**导入期冻结**的注册映射 `_POOL_MAX_ENVS` 取值——键=唯一合法 NAME、值=冻结池上限、**名单与取值同源**；★ v1.10 更正：**不再 `globals()`**，运行期重绑定 `config.MAX_*_POOL` 不生效；未注册 NAME ⇒ `ValueError`；**默认值仍是 1000/1000/500**）⇒ 部署可**免改码调参**；`cache_max`（1000/1000/500）**仍是矩阵内整数字面量 = 内存硬界**，**不** env 化。**★ v1.10（P1-2）**：`pool_max` 与 `cache_max` 是**两个独立上限**——前者约束 **prefetch 轮转覆盖**、后者约束**终端缓存内存界**，**不设 `pool_max ≤ cache_max` 护栏**（`depth`/`f10`/`announcement` 现状即 `pool_max`=2000 > `cache_max`=500：`depth` 无 prefetch 循环、`f10`/`announcement` 有大 TTL；`pool_max > cache_max` 只造成**回源轮转浪费**、**非正确性问题**，读路径对 LRU 淘汰码正常回源、绝不返回陈旧值）。**`depth` 池保持 `'dedup'`(=2000) 是正确设计**（**无 prefetch 循环**——`depth` 经 `fetch_cls_basic_info` 阶段 3 → `_depth_store` 写入，池仅作 `code→ts` 账本 ~200KB 量级；真正的内存界是 `cache_max=500`），故"与 `quote` 不对称"仅为表面观感。**收缩理由与内存影响**：PRF-MEM-01 压测内存高水位 **96.57%**，**原归因（v1.6/v1.7 假设 · ★ v1.8 实测已更正）** = 终态缓存被灌满至 `cache_max` + `timeline` 单条 ~96KB（内存大户）+ prefetch 保活使 LRU 不淘汰（★ v1.7 更正：prefetch **间隔 = `pool_refresh` = `ttl × refresh_factor`**——`quote`/`depth` 盘中 4s、`fundflow`/`timeline` 8s、非盘 120s，**不是**"120s 轮询"）；`pool_max` 与 `cache_max` **同源收缩**使保活范围收敛（池成员不再被无限期触碰 ⇒ 终态缓存 LRU 可真正淘汰），**★ v1.8 实测回填（run 20260920-110805，证伪该预期）**：python 稳态 **RSS 1.095GiB → 1.012GiB（净收益仅 ~83MiB）**、容器 **1.449GiB(96.57%) → 1.41GiB(93.98%)** ⇒ **本次收缩未达成内存目标**；**归因 —— 终端缓存非内存大头**：实测反推（`timeline` 1350→500 省 ~82MB + `quote`/`fundflow` 各 −1000 条省 ~10MB）与 −83MiB 吻合。**★ v1.9 归因纠偏（v1.8 的 URL 缓存归因已被证伪）**：共享 URL 缓存存的是**解码后的原始响应文本（`str`）**（`cache.py:851-852` `resp.read().decode(...)` → `_cache_put`；`json.loads` 在调用方命中后解析），**非**解析对象，总量仅**几十 MB**、**非内存大头**；**真因 = glibc arena**（33 线程 × 默认最多 `8×ncores` 个 64MB arena，`RssAnon` 占 98%）——A/B 实测（run 20260920-113125，基线 20260920-110805）`MALLOC_ARENA_MAX=2` ⇒ python VmRSS **1.008GiB → 0.772GiB（−248MiB）**、VmSize **8.96GB → 1.15GB**、容器 **1.41GiB(93.98%) → 1.259GiB(83.95%)**；累计链路 **1.095GiB → 1.012GiB → 0.772GiB**（容器 **1.449 → 1.41 → 1.259GiB**），剩余 = 终端缓存解析对象（~200MB）+ 运行时/分配器残余（`config.md` §10#24 / §10.1 实测结论）。**CR-04 降级面（★ v1.7 新登记）**：`cache_max` 现 **< 活跃码上界 `MAX_DEDUP_CODES`(2000)** ⇒ 原隐含的「终端缓存覆盖活跃全集」**不再成立**；降级路径 = `_cache_store` **严格 LRU 淘汰（最旧条目与其 `cache_ts` 同步淘汰）** + 消费方 `stream._refresh_pool` 对未刷新片 miss 码退化为 `stream._last_known` **结转**（进帧 `stale`）；**功能不破坏**（`_process_chunk` 对未命中码正常回源，无异常路径），代价 = `cached_batch` 命中率下降、`upstream_fetch_total{domain}` 上升（`cache_hit_ratio` 可观测）。**禁止**把池上限写成 `MAX_CODES_PER_SUB(200)`（单组上限；会在 ≥2 个不重叠组时抖空缓存） |
| **BR-SA-14** | 池淘汰**只** `del pool[code]`：**不再** `cache.pop`/`cache_ts.pop`。数据内存由 `cache_max` 独立 LRU 守 |
| **BR-SA-15** | 终点缓存命中/写入均 `move_to_end(code)`（真 LRU 访问序）；淘汰 `popitem(last=False)` |
| **BR-SA-16** | 终点缓存写入后发布 `metrics.set_gauge('cache_entries', len(cache), key=domain)` |
| **BR-SA-17** | **INV-1b（覆盖条件，供 stream 决策）**：**权威口径在 `stream.md` §3.3 / BR-STR-16**（★ v1.3：`coverage = int(0.8 × tick × BATCH_MAX_WORKERS / _PER_FETCH_EST)`，**随 tick 与订阅字段集变**，不再是固定 170/56）；本模块只提供公开常量 `BATCH_MAX_WORKERS`（=20）与轮转原语（`_prefetch_slice`/`_prefetch_advance`/`cached_batch`），**不在此重算 coverage**（避免两处标定漂移） |

### 4.4 deadline 传递（R13 / ADR-009）

| 编号 | 规则 |
|------|------|
| **BR-SA-18** | 每一层都必须**消费**期限，不得"接收后丢弃"：handler→`budget`；`_handle_cached_batch`→`chunk_deadline`；`_run_batch`/`_fetch_one`→前置判定；fetcher→`fetch_json(deadline=)`（REST）/ `_evaluate_fetch_any(deadline=)`（CDP） |
| **BR-SA-19** | **P7b：本模块删除 `_urlopen_timeout`**。REST 单次预算**只**由 `cache._effective_timeout(url, deadline)` 计算（`min(_fetch_budget(url), max(0.05, remaining))`；已过 ⇒ `None` ⇒ `FetchError('upstream_timeout')`）。本模块的职责是**把 `deadline` 透传** `_fetch_rest_json → fetch_json`，不再自行计算超时 |
| **BR-SA-20** | 预算耗尽即停止取数：`_fetch_one` 返回 `(None, _LOCAL_BUDGET)`；`_run_batch` 在 `time() >= deadline` 时**不创建线程**、逐码填 `_LOCAL_BUDGET`（有界降级，绝不无界等待）。**该哨兵不入 `_fail_ledger`**（BR-SA-34） |
| **BR-SA-21** | `_run_batch` **删除** `except TypeError: fetcher(code)` 的**静默丢弃**路径；降级逻辑上收为 `_call_fetcher` 的**4 档关键字尝试**，且**仅当 TypeError 抛自调用帧**（`tb_next is None`）才降级（§2.3 / P2-④）。生产取数器全部接受 `(deadline, ttl)` ⇒ 生产路径无期限丢失 |

### 4.5 分块预算（SAD §2.3 D-2）

| 编号 | 规则 |
|------|------|
| **BR-SA-22** | 每进入一个 chunk 前重算：`workers = BATCH_MAX_WORKERS if concurrent else 1`；`chunk_budget = ceil_div(len(chunk), workers) × per_call_timeout`；`chunk_deadline = min(budget, time() + chunk_budget)`（`budget is None` ⇒ 无整体上限，仅 `chunk_deadline = time() + chunk_budget`） |
| **BR-SA-23** | `ceil_div(a,b) = -(-a // b)`（**禁止** `import math`，不在 allowlist） |
| **BR-SA-24** | 默认预算：REST 域 `_BATCH_BUDGET_REST=15`（**AC-E2**「REST 回源 ≤15s」——**REV-DES-17 引据更正，非 AC-S7**）；CDP 域 `_BATCH_BUDGET_CDP=60`（串行导航无法在 15s 内跑完 50 码；**编排层裁决 REV-DES-21：接受现状 + 风险登记 §10#10**，引据同为 AC-E2） |
| **BR-SA-25** | handler 的 `deadline` 非 `None` ⇒ `budget = deadline`（**覆盖**默认值）；`None` ⇒ `budget = time() + 默认预算` |

### 4.6 metrics 口径（AC-S10）

| 编号 | 指标 | 口径 |
|------|------|------|
| **BR-SA-26** | `cache_entries{domain}` | 每次终点缓存写入/淘汰后 `set_gauge(len(cache), key=domain)`；`domain` ∈ {quote,**depth**,fundflow,timeline,f10,announcement}（`sector` 由 `_sector_cache_put` 另行发布；`depth` 由 `_depth_store` 经 `_cache_store` 发布） |
| **BR-SA-27** | `code_cooldown_list` | 记账变更后发布；元素 `[domain, code, cooldown_until]`；仅 `cooldown_until > now` |
| **BR-SA-28** | `upstream_fetch_total{domain}` | **每次取数调用**计数一次（REST `fetch_json` 调用、CDP `evaluate_fetch`）。口径为"取数调用次数"（URL 缓存命中亦计 ⇒ 上界估计；CDP 路径为真实回源）。`domain` ∈ `DOMAIN_MATRIX` 键。**P7b**：`_direct_fetch` 的**单次逻辑取数只计 1 次**（旧版 CDP 腿 + REST 腿各计一次 ⇒ 双计）；`fetch_cls_*` 的 CDP 回退仍各计一次（确为第二次尝试） |
| **BR-SA-29** | `upstream_fail_total{kind}` | **防重复**：`fetch_json` 的网络失败已由 `cache._record_failure` 计数（BR-CACHE-6）⇒ 本模块**从 `fetch_json` 捕获到的 `FetchError` 不再计数**；**自建** kind 就地计一次：① `cdp_unavailable` —— `fetch_cls_f10` 的**五处出口全部**经 `_raise_cdp_unavailable()` 计数（P7b / BR-SA-37：含"有数据但不匹配"）；② `upstream_error` 语义失败 —— `code != 200`（各取数器）+ **JSON 解码失败 / 上游非 dict**（`_fetch_rest_json` 就地计数，REV-DES-13/14） |
| **BR-SA-30** | 指标名冻结 | 只允许上述 4 个名（+`sector` 的 `cache_entries`）；`metrics._KNOWN` 之外的写入会被 metrics 告警（MET-T8b 红灯） |

### 4.7 `_` 前缀保留键

| 编号 | 规则 |
|------|------|
| **BR-SA-31** | `requested` 中以 `_` 开头的码由 `build_batch_response` **跳过**（不成为数据键）；本模块**不**自行过滤保留键 |
| **BR-SA-32** | 本模块输出的组装体中**永不含顶层 `error`**（批量与单体形态严格互斥，AC-A5） |
| **BR-SA-33** | **消费方契约（跨模块，硬约束）**：`stream._refresh_pool` 遍历本模块返回的扁平映射时**必须跳过 `_` 前缀键**（否则会把 `_errors` 当股票塞进帧——AR-7 唯一陷阱点） |

---

## 5. 伪代码

### 5.1 模块头部与常量

```python
import json
import logging
import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, as_completed
from time import sleep, time
from urllib.parse import urlencode
# ★ v1.3：socket / urllib.request.Request,urlopen 已删（REST 只经 cache.fetch_json，P2-①）

from . import config
from . import metrics
from .cache import FetchError, _fill_missing, build_batch_response, fetch_json
from .cdp_engine import page_data                            # ★ REV-DES-10：R18 防御取数唯一入口
from .config import (
    MAX_DEDUP_CODES, REQUEST_TIMEOUT, _MAX_BATCH_SIZE,       # ★ v1.3：删 VALID_STOCK_CODE（改 canonical_code）
    _ANNOUNCEMENT_BASE_URL, _ANNOUNCEMENT_HEADERS, _BASIC_INFO_BASE_URL,
    _BASIC_INFO_HEADERS, _F10_EXPECTED_KEYS, _FUNDFLOW_BASE_URL, _FUNDFLOW_HEADERS,
    _STOCK_DETAIL_BASE_URL, _STOCK_DETAIL_HEADERS,
    _STOCK_DEPTH_URL, _STOCK_DEPTH_HEADERS,                  # ★ v1.3 五档盘口
    _TIMELINE_BASE_URL, _TIMELINE_HEADERS, cache_policy, canonical_code,
    stock_nav_page_names, upstream_secu_code,                # ★ v1.3 wire 拼写唯一权威
)
from .utils import cls_sign_params

log = logging.getLogger('stock')

BATCH_MAX_WORKERS = config.BATCH_MAX_WORKERS                 # ★ v1.3：20（不再是字面量 8）
_BATCH_MAX_WORKERS = BATCH_MAX_WORKERS
_BATCH_BUDGET_REST = 15
_BATCH_BUDGET_CDP = 60
_CDP_CALL_TIMEOUT = 8
_PREFETCH_CDP_CALL_TIMEOUT = 4
_PREFETCH_PASS_BUDGET = 60.0
FAIL_THRESHOLD = 3
FAIL_COOLDOWN = 120
_FAIL_DOMAINS = ('quote', 'fundflow', 'timeline', 'f10', 'announcement')
_FAIL_LEDGER_MAX = len(_FAIL_DOMAINS) * MAX_DEDUP_CODES        # 10000

_prefetch_cursor = {}
_prefetch_cursor_lock = threading.Lock()
_page_fetch_locks = {}
_page_fetch_locks_lock = threading.Lock()
```

### 5.2 期限/分类辅助（BR-SA-19/21，P7b）

```python
def _call_fetcher(fetcher, code, deadline, ttl, refresh_epoch=None):
    """按关键字档尝试调用；**仅调用帧 TypeError** 才降级（P2-④ / BR-SA-38）。

    函数体内的 TypeError 是真实失败，原样上抛 —— 重试会执行两次取数。
    `refresh_epoch` 是**纯增量档**：仅在非 None 时先试它，其余档与旧版逐字一致。
    """
    combos = []
    if refresh_epoch is not None:                                  # ★ v1.3
        combos.append({'deadline': deadline, 'ttl': ttl,
                       'refresh_epoch': refresh_epoch})
    combos.extend(({'deadline': deadline, 'ttl': ttl},
                   {'deadline': deadline},
                   {'ttl': ttl},
                   {}))
    for kwargs in combos:
        try:
            return fetcher(code, **kwargs)
        except TypeError as exc:
            tb = exc.__traceback__
            if tb is None or tb.tb_next is not None:
                raise                                  # 抛自函数体 ⇒ 不降级
    raise TypeError(f'{fetcher!r} does not accept (code, deadline, ttl)')


def _fetch_rest_json(url, headers, ttl, deadline=None, refresh_epoch=None):
    """唯一 REST 取数收口：**期限 + 新鲜度下限透传** + 失败分类 + 解码/结构防御 + 自建失败计数。

    ★ P7b：**没有前置 deadline 闸门**——`fetch_json` 在段 1 先查正缓存再判期限
    （`cache.md` BR-CACHE-21），所以即使批量预算已耗尽，URL 缓存命中仍可服务。
    先闸门会让慢批次对"已在缓存里"的数据回 `null`。
    ★ v1.3（BR-SA-38）：`refresh_epoch` 仅在非 None 时作为关键字传入 `fetch_json`，
    `None`（REST/prefetch）⇒ 调用形态逐字不变。
    """
    kwargs = {'ttl': ttl, 'deadline': deadline}
    if refresh_epoch is not None:                                  # ★ v1.3
        kwargs['refresh_epoch'] = refresh_epoch
    try:
        raw = json.loads(fetch_json(url, headers, **kwargs))         # 期限 + epoch 透传
    except FetchError:
        raise                                                        # BR-SA-29：cache 已计数，勿重复
    except Exception as exc:                                         # JSON 解码等 → 自建
        metrics.incr('upstream_fail_total', key='upstream_error')    # ★ REV-DES-13
        raise FetchError('upstream_error', url=url, cause=exc) from exc
    if not isinstance(raw, dict):                                    # ★ REV-DES-14
        metrics.incr('upstream_fail_total', key='upstream_error')
        raise FetchError('upstream_error', url=url)
    return raw


def _rest_fetch(url, headers, ttl, deadline, refresh_epoch=None):
    """按需给 REST 漏斗加 epoch 提示（v1.3）；`None` ⇒ 逐字旧调用形态。"""
    if refresh_epoch is None:
        return _fetch_rest_json(url, headers, ttl, deadline)
    return _fetch_rest_json(url, headers, ttl, deadline, refresh_epoch)
```

> **删除项（P7b）**：`_classify_exc`（职责归 `cache._classify`）与 `_urlopen_timeout`（职责归 `cache._effective_timeout`）已**从本模块移除**。

### 5.3 共享失败状态层（BR-SA-5..12）

```python
_fail_ledger = {}
_fail_ledger_lock = threading.Lock()

# S1-3 / P1-4：失败路径的家务节流。账本可达 10000 条 ⇒ 每次失败写都做 O(n) 老化扫描
# + O(n) code_cooldown_list 重建 ⇒ n 次失败风暴 O(n²)，全部串行在 _fail_ledger_lock 上。
_COOLDOWN_PUBLISH_INTERVAL = 5.0
_FAIL_LEDGER_PRUNE_INTERVAL = 5.0
_cooldown_published_at = 0.0
_fail_ledger_pruned_at = 0.0


def _cooldown_snapshot_locked(now):
    """当前仍在冷却的条目；调用方须持锁。"""
    return [[d, c, e[1]] for (d, c), e in _fail_ledger.items() if e[1] > now]


def _fail_ledger_prune_locked(now):
    """BR-SA-8/9：老化清除（限频）+ 硬上限淘汰（O(1)，调用方须持锁）。"""
    global _fail_ledger_pruned_at
    pruned = 0
    if now - _fail_ledger_pruned_at >= _FAIL_LEDGER_PRUNE_INTERVAL:   # ★ 老化扫描限频
        aged = [k for k, e in _fail_ledger.items() if now - e[3] > FAIL_COOLDOWN]
        for k in aged:
            del _fail_ledger[k]
        pruned = len(aged)
        _fail_ledger_pruned_at = now
    while len(_fail_ledger) > _FAIL_LEDGER_MAX:                       # ★ BR-SA-9：O(1) 淘汰
        _fail_ledger.pop(next(iter(_fail_ledger)))                    #   dict 保插入序 ⇒ 丢最旧注册
    return pruned


def _fail_ledger_get(domain, code, now=None):
    now = time() if now is None else now
    with _fail_ledger_lock:
        entry = _fail_ledger.get((domain, code))
        if entry is None:
            return None
        if now - entry[3] > FAIL_COOLDOWN:                            # BR-SA-8：非"连续"
            del _fail_ledger[(domain, code)]
            return None
        return list(entry)                                            # 副本


def _fail_ledger_record_failure(domain, code, kind, now=None):
    global _cooldown_published_at
    now = time() if now is None else now
    snapshot = publish = None
    with _fail_ledger_lock:
        prev = _fail_ledger.get((domain, code))
        fresh = prev is not None and (now - prev[3]) <= FAIL_COOLDOWN  # BR-SA-8
        cnt = (prev[0] + 1) if fresh else 1
        cooldown = (now + FAIL_COOLDOWN) if cnt >= FAIL_THRESHOLD else 0.0   # BR-SA-7
        _fail_ledger[(domain, code)] = [cnt, cooldown, kind, now]
        _fail_ledger_prune_locked(now)
        if now - _cooldown_published_at >= _COOLDOWN_PUBLISH_INTERVAL:  # ★ BR-SA-12b
            snapshot = _cooldown_snapshot_locked(now)
            _cooldown_published_at = now
            publish = True
    if publish:
        metrics.set_gauge('code_cooldown_list', snapshot)              # ★ 锁外（BR-SA-12）


def _fail_ledger_clear(domain, code):
    global _cooldown_published_at
    now = time()
    snapshot = publish = None
    with _fail_ledger_lock:
        entry = _fail_ledger.pop((domain, code), None)
        if entry is None:
            return
        if now - _cooldown_published_at >= _COOLDOWN_PUBLISH_INTERVAL:
            snapshot = _cooldown_snapshot_locked(now)
            _cooldown_published_at = now
            publish = True
    if publish:
        metrics.set_gauge('code_cooldown_list', snapshot)


def code_cooldown_list(now=None):
    now = time() if now is None else now
    with _fail_ledger_lock:
        return _cooldown_snapshot_locked(now)
```

### 5.4 终点缓存（LRU + TTL + cache_max；BR-SA-2/13..16）

```python
def _cache_store(cache, cache_ts, lock, code, data, cache_max, domain, now=None):
    now = time() if now is None else now
    with lock:
        cache[code] = data
        cache_ts[code] = now                                          # 写入时刻（TTL 基准）
        cache.move_to_end(code)                                       # BR-SA-15
        if len(cache) > cache_max:
            victim, _ = cache.popitem(last=False)                     # 真 LRU 淘汰
            cache_ts.pop(victim, None)
        size = len(cache)
    metrics.set_gauge('cache_entries', size, key=domain)              # BR-SA-26


def cached_batch(domain, codes, now=None):
    """§2.6：无网络读取域终点缓存（stream 分片轮转的 cached 部分）。

    ★ P7b / P1-6：查询键 canonical，**结果仍以请求原拼写为键** —— 传
    `600519.SH` 与 `sh600519` 的调用方读到同一份条目、各拿自己请求的键名。
    """
    store = _DOMAIN_STORES.get(domain)
    if store is None:
        log.warning('[cached_batch] unknown domain %r', domain)
        return {}
    _pool, cache, cache_ts, lock = store
    if cache is None:
        return {}
    now = time() if now is None else now
    ttl = cache_policy(domain)['ttl']
    out = {}
    with lock:
        for code in codes:
            canon = canonical_code(code)
            if canon is None:
                continue
            data = cache.get(canon)
            if data is not None and now - cache_ts.get(canon, 0) < ttl:
                cache.move_to_end(canon)
                out[code] = data
    return out
```

### 5.5 `_run_batch` / `_fetch_one`（BR-SA-20/21）

```python
def _fetch_one(fetcher, code, deadline=None, ttl=None, refresh_epoch=None):
    """唯一的期限/失败分类漏斗（总函数，绝不 raise）。

    预算已过 ⇒ `_LOCAL_BUDGET`（我们自己的预算，不是上游失败）⇒ 调用方可呈现
    超时形态而不写入冷却账本（BR-SA-34）。
    """
    if deadline is not None and time() > deadline:                    # BR-SA-20：不触网
        return None, _LOCAL_BUDGET
    try:
        return _call_fetcher(fetcher, code, deadline, ttl, refresh_epoch), None   # §5.2
    except FetchError as exc:                                         # kind 枚举
        return None, exc.kind
    except Exception:
        return None, 'upstream_error'


def _run_batch(fetcher, codes, deadline=None, ttl=None, concurrent=True, refresh_epoch=None):
    """返回 (results, errors)。BR-SA-20/34：预算耗尽 ⇒ 不建线程、逐码 `_LOCAL_BUDGET`。"""
    results, errors = {}, {}
    if not codes:
        return results, errors
    if deadline is not None and time() >= deadline:
        for code in codes:
            results[code] = None
            errors[code] = _LOCAL_BUDGET                                 # ★ 不入账
        return results, errors
    if not concurrent:
        for code in codes:                                            # CDP 导航必须串行
            data, kind = _fetch_one(fetcher, code, deadline, ttl, refresh_epoch)
            results[code] = data
            if kind:
                errors[code] = kind
        return results, errors
    with ThreadPoolExecutor(max_workers=min(BATCH_MAX_WORKERS, len(codes))) as ex:
        futures = {ex.submit(_fetch_one, fetcher, code, deadline, ttl,
                             refresh_epoch): code for code in codes}
        for fut in as_completed(futures):
            code = futures[fut]
            try:
                data, kind = fut.result()
            except Exception:                                         # 不应发生（_fetch_one 总函数）
                data, kind = None, 'upstream_error'
            results[code] = data
            if kind:
                errors[code] = kind
    return results, errors
```

### 5.6 `_process_chunk`（批量取数 + 冷却，核心）

```python
def _process_chunk(codes, domain, policy, fetcher, pool=None, cache=None,
                   cache_ts=None, lock=None, deadline=None, after=None,
                   concurrent=True, refresh_epoch=None):
    ttl, pool_max, cache_max = policy['ttl'], policy['pool_max'], policy['cache_max']
    # ① 归一 + 去重 + 校验（P7b / P1-6）。canonical_code 把 'SH600519'/'600519.SH'
    #    折叠为 'sh600519' ⇒ 同一只股票不会铸出两个池/缓存键/上游 URL。
    #    结果在返回前映射回**每一个请求拼写**（build_batch_response 以请求码为键）。
    results, errors = {}, {}
    alias, canons, seen = {}, [], set()                # 请求拼写 → canonical
    for code in codes:
        canon = canonical_code(code)
        if canon is None:
            results[code] = None                                      # 无效码 → null
            continue
        alias[code] = canon
        if canon not in seen:
            seen.add(canon)
            canons.append(canon)
    if not canons:
        return results, errors
    now = time()
    # ② 池成员账 touch + 上限淘汰（BR-SA-13/14：不再 cache.pop）
    if pool is not None:
        with lock:
            for canon in canons:
                pool[canon] = now
            if len(pool) > pool_max:
                for victim in sorted(pool, key=pool.get)[:len(pool) - pool_max]:
                    del pool[victim]                                      # 仅删成员账
    # ③ 终点缓存查（TTL 命中 / move_to_end；BR-SA-2/15）
    by_canon, missing = {}, []
    if cache is not None:
        with lock:
            for canon in canons:
                data = cache.get(canon)
                written = cache_ts.get(canon, 0)
                # ★ v1.3 / BR-SA-38：TTL 有效 **且** 写入不早于本轮起点才命中
                if data is not None and now - written < ttl \
                        and (refresh_epoch is None or written >= refresh_epoch):
                    cache.move_to_end(canon)
                    by_canon[canon] = data
                else:
                    missing.append(canon)        # 过期 / 早于本轮 ⇒ 拒读+回源（BR-SA-3/38）
    else:
        missing = list(canons)
    # ④ 码级冷却门（BR-SA-5：命中 → 不触网）
    err_canon, eligible = {}, []
    for canon in missing:
        entry = _fail_ledger_get(domain, canon, now)
        if entry is not None and entry[1] > now:
            by_canon[canon] = None
            err_canon[canon] = entry[2] or 'upstream_error'           # 枚举 kind
            continue
        eligible.append(canon)
    # ⑤ 取数（期限贯通；返回 (results, errors)）
    if eligible:
        fetched, fetch_errors = _run_batch(fetcher, eligible, deadline=deadline,
                                           ttl=ttl, concurrent=concurrent,
                                           refresh_epoch=refresh_epoch)   # ★ v1.3
        # ⑥ 合并 + 失败记账 + 缓存写（BR-SA-6）
        for canon in eligible:
            data = fetched.get(canon)
            kind = fetch_errors.get(canon)
            if kind == _LOCAL_BUDGET:
                # ★ P7b / BR-SA-34：我们自己的 deadline 先到了，未做网络尝试。
                #   呈现超时形态，但**永不写 120s 冷却账**（cache.md S1-1 同源）。
                by_canon[canon] = None
                err_canon[canon] = 'upstream_timeout'
                continue
            if kind:
                _fail_ledger_record_failure(domain, canon, kind)       # BR-SA-6
                by_canon[canon] = None
                err_canon[canon] = kind
                continue
            if data is not None:
                _fail_ledger_clear(domain, canon)                      # 成功 ⇒ 清账
                if cache is not None:
                    _cache_store(cache, cache_ts, lock, canon, data, cache_max, domain)
                if after is not None:
                    try:
                        after(data, canon)
                    except Exception:
                        log.warning('[after] callback failed for %s', canon)
                by_canon[canon] = data
            else:
                by_canon[canon] = None                                 # 无数据：不计不清（BR-SA-6）
    # ⑦ 把 canonical 结果映射回每一个请求拼写（BR-SA-36）
    for original, canon in alias.items():
        results[original] = by_canon.get(canon)
        if canon in err_canon:
            errors[original] = err_canon[canon]
    return results, errors
```

### 5.7 `_handle_cached_batch`（分块 + chunk 预算；BR-SA-22..25）

```python
def _handle_cached_batch(codes, domain, policy, fetcher, pool=None, cache=None,
                         cache_ts=None, lock=None, budget=None,
                         per_call_timeout=REQUEST_TIMEOUT, after=None,
                         concurrent=True, refresh_epoch=None):
    if not codes:
        return {}, {}
    results, errors = {}, {}
    workers = BATCH_MAX_WORKERS if concurrent else 1
    for i in range(0, len(codes), _MAX_BATCH_SIZE):
        chunk = codes[i:i + _MAX_BATCH_SIZE]
        if budget is not None:
            chunk_budget = (-(-len(chunk) // workers)) * per_call_timeout   # BR-SA-23 ceil_div
            chunk_deadline = min(budget, time() + chunk_budget)
        else:
            chunk_deadline = None
        r, e = _process_chunk(chunk, domain, policy, fetcher, pool=pool, cache=cache,
                              cache_ts=cache_ts, lock=lock, deadline=chunk_deadline,
                              after=after, concurrent=concurrent,
                              refresh_epoch=refresh_epoch)          # ★ v1.3
        results.update(r)
        errors.update(e)
    return results, errors
```

### 5.8 handler（6 个，同一形状；组装点唯一）

```python
_DOMAIN_STORES = {}   # 定义在各缓存之后（见 §5.9 末）：domain -> (pool, cache, cache_ts, lock)


def handle_cls_fundflow(codes, deadline=None, dropped=0, refresh_epoch=None):
    policy = cache_policy('fundflow')                                 # BR-SA-1：只调一次
    budget = deadline if deadline is not None else time() + _BATCH_BUDGET_REST
    pool, cache, cache_ts, lock = _DOMAIN_STORES['fundflow']
    results, errors = _handle_cached_batch(
        codes, 'fundflow', policy, fetch_cls_fundflow,
        pool=pool, cache=cache, cache_ts=cache_ts, lock=lock, budget=budget,
        refresh_epoch=refresh_epoch)                                  # ★ v1.3
    return build_batch_response(codes, results, errors, dropped=dropped)


def handle_cls_timeline(codes, deadline=None, dropped=0, refresh_epoch=None):
    policy = cache_policy('timeline')
    budget = deadline if deadline is not None else time() + _BATCH_BUDGET_REST
    pool, cache, cache_ts, lock = _DOMAIN_STORES['timeline']
    results, errors = _handle_cached_batch(
        codes, 'timeline', policy, fetch_cls_timeline,
        pool=pool, cache=cache, cache_ts=cache_ts, lock=lock, budget=budget,
        refresh_epoch=refresh_epoch)                                  # ★ v1.3
    return build_batch_response(codes, results, errors, dropped=dropped)


def handle_cls_f10(codes, deadline=None, dropped=0):
    policy = cache_policy('f10')
    budget = deadline if deadline is not None else time() + _BATCH_BUDGET_CDP
    pool, cache, cache_ts, lock = _DOMAIN_STORES['f10']
    results, errors = _handle_cached_batch(
        codes, 'f10', policy, fetch_cls_f10, pool=pool, cache=cache,
        cache_ts=cache_ts, lock=lock, budget=budget,
        per_call_timeout=_CDP_CALL_TIMEOUT,
        after=_populate_sector_from_f10, concurrent=False)            # CDP 必须串行
    return build_batch_response(codes, results, errors, dropped=dropped)


def handle_cls_basic_infos(codes, deadline=None, dropped=0, refresh_epoch=None):
    policy = cache_policy('quote')
    budget = deadline if deadline is not None else time() + _BATCH_BUDGET_REST
    pool, cache, cache_ts, lock = _DOMAIN_STORES['quote']
    results, errors = _handle_cached_batch(
        codes, 'quote', policy, fetch_cls_basic_info,
        pool=pool, cache=cache, cache_ts=cache_ts, lock=lock, budget=budget,
        refresh_epoch=refresh_epoch)                                  # ★ v1.3
    return build_batch_response(codes, results, errors, dropped=dropped)


def handle_cls_announcement(codes, deadline=None, dropped=0):
    policy = cache_policy('announcement')
    budget = deadline if deadline is not None else time() + _BATCH_BUDGET_REST
    pool, cache, cache_ts, lock = _DOMAIN_STORES['announcement']
    results, errors = _handle_cached_batch(
        codes, 'announcement', policy, fetch_cls_announcement,
        pool=pool, cache=cache, cache_ts=cache_ts, lock=lock, budget=budget)
    return build_batch_response(codes, results, errors, dropped=dropped)


def handle_cls_stock_batch(codes, deadline=None, dropped=0):
    """§2.4：无 pool、无终点缓存（仅 fetch_json URL 缓存兜底）。"""
    policy = cache_policy('quote')                                    # 仅供 ttl 同源
    budget = deadline if deadline is not None else time() + _BATCH_BUDGET_REST
    results, errors = _handle_cached_batch(
        codes, 'quote', policy, fetch_cls_stock_detail,
        pool=None, cache=None, cache_ts=None, lock=None, budget=budget)
    return build_batch_response(codes, results, errors, dropped=dropped)


def handle_cls_stock(stock_code):
    """保留的薄封装（server import 兼容）：handle_* 不抛。"""
    try:
        return fetch_cls_stock_detail(stock_code)
    except Exception:
        return None
```

### 5.9 取数器（REST/CDP，失败自建 kind）

```python
def _evaluate_fetch_any(url, deadline=None):
    if not config.cdp_engine or not config.cdp_engine.ready:
        return None
    end = time() + _CDP_CALL_TIMEOUT if deadline is None else min(time() + _CDP_CALL_TIMEOUT, deadline)
    for name in _stock_nav_pages()[:3] + ['cls_finance', 'cls_quotation']:
        if time() >= end:
            break
        page = config.cdp_engine.get_page(name)
        if not page:
            continue
        budget = min(end - time(), 2)
        if budget < 0.5:
            break
        with _get_page_fetch_lock(name):
            try:
                result = page.evaluate_fetch(url, timeout=budget)
                if result and isinstance(result, dict):
                    return result
            except Exception:
                pass
    return None


def fetch_cls_fundflow(stock_code, deadline=None, ttl=None, refresh_epoch=None):
    domain = 'fundflow'
    url = f'{_FUNDFLOW_BASE_URL}?secu_code={upstream_secu_code(stock_code)}'   # ★ v1.3 wire 拼写
    ttl = cache_policy(domain)['ttl'] if ttl is None else ttl
    metrics.incr('upstream_fetch_total', key=domain)                  # BR-SA-28
    err = None
    try:
        raw = _rest_fetch(url, _FUNDFLOW_HEADERS, ttl, deadline, refresh_epoch)  # ★ v1.3
        if raw.get('code') == 200:
            return raw.get('data')                                    # 可能 None（无数据）
        err = FetchError('upstream_error', url=url)
        metrics.incr('upstream_fail_total', key='upstream_error')     # BR-SA-29（自建）
    except FetchError as exc:
        err = exc                                                     # cache 已计数，勿重复
    if deadline is not None and time() >= deadline:
        raise err
    metrics.incr('upstream_fetch_total', key=domain)                  # CDP 回退也是一次取数
    result = _evaluate_fetch_any(url, deadline=deadline)
    if result and result.get('code') == 200:
        return result.get('data')
    raise err


def fetch_cls_timeline(stock_code, deadline=None, ttl=None, refresh_epoch=None):
    domain = 'timeline'
    url = f'{_TIMELINE_BASE_URL}?secu_code={upstream_secu_code(stock_code)}'   # ★ v1.3
    ttl = cache_policy(domain)['ttl'] if ttl is None else ttl
    metrics.incr('upstream_fetch_total', key=domain)
    err = None
    try:
        raw = _rest_fetch(url, _TIMELINE_HEADERS, ttl, deadline, refresh_epoch)  # ★ v1.3
        if raw.get('code') == 200:
            return raw.get('data')
        err = FetchError('upstream_error', url=url)
        metrics.incr('upstream_fail_total', key='upstream_error')
    except FetchError as exc:
        err = exc
    if deadline is not None and time() >= deadline:
        raise err
    metrics.incr('upstream_fetch_total', key=domain)
    result = _evaluate_fetch_any(url, deadline=deadline)
    if result and result.get('code') == 200:
        return result.get('data')
    raise err


def fetch_cls_announcement(stock_code, deadline=None, ttl=None):
    domain = 'announcement'
    url = _announcement_url(stock_code)
    ttl = cache_policy(domain)['ttl'] if ttl is None else ttl        # Q5：删裸 ttl=15
    metrics.incr('upstream_fetch_total', key=domain)
    err = None
    try:
        raw = _fetch_rest_json(url, _ANNOUNCEMENT_HEADERS, ttl, deadline)
        if raw.get('code') == 200:
            return raw.get('data')
        err = FetchError('upstream_error', url=url)
        metrics.incr('upstream_fail_total', key='upstream_error')
    except FetchError as exc:
        err = exc
    if deadline is not None and time() >= deadline:
        raise err
    metrics.incr('upstream_fetch_total', key=domain)
    result = _evaluate_fetch_any(url, deadline=deadline)
    if result and result.get('code') == 200:
        return result.get('data')
    raise err


def fetch_cls_stock_detail(stock_code, deadline=None, ttl=None):
    domain = 'quote'
    url = f'{_STOCK_DETAIL_BASE_URL}?secu_code={upstream_secu_code(stock_code)}'  # ★ v1.3
    ttl = cache_policy(domain)['ttl'] if ttl is None else ttl
    metrics.incr('upstream_fetch_total', key=domain)
    raw = _fetch_rest_json(url, _STOCK_DETAIL_HEADERS, ttl, deadline)
    if raw.get('code') == 200:
        return raw.get('data')
    metrics.incr('upstream_fail_total', key='upstream_error')         # 语义失败自建
    raise FetchError('upstream_error', url=url)


# 上游 `basic` 数据有效性探针（★ v1.3）：错误 `secu_code` 拼写（如北交所用前缀形而非点号形）
# 会得到 HTTP 200 + `code:200` + **41 键全 null** 的空壳，而不是错误码。
_BASIC_INFO_KEY_FIELDS = ('secu_name', 'last_px')


def _basic_info_is_valid(raw):
    """True 当 `raw['data']` 是含真实标的字段的 dict（空壳/非 dict/空 dict ⇒ False）。"""
    data = raw.get('data')
    if not isinstance(data, dict) or not data:
        return False
    return any(data.get(f) not in (None, '') for f in _BASIC_INFO_KEY_FIELDS)


def fetch_cls_basic_info(stock_code, deadline=None, ttl=None, refresh_epoch=None):
    """三阶段取 basic info（+ `sector_name` + `depth`）。★ v1.3 / BR-SA-39。

    阶段 1 REST basic（**致命**；错误码或"空壳" ⇒ `upstream_error`，不写缓存、**不进阶段 2/3**）
    阶段 2 REST stock detail 取行业（非致命；7d `sector` 缓存吸收，稳态 0 次）
    阶段 3 REST `volume?field=five` 取五档盘口（非致命、**只增字段**；失败 ⇒ 无 `depth`，不伪造）
    阶段 1/3 传 `refresh_epoch`（稳态 2 次调用均真回源）；阶段 2 留 TTL（避免第三调用/tick）。
    `upstream_secu_code` 为 wire 拼写唯一权威（SH/SZ 前缀形 / BSE 点号形）。
    """
    domain = 'quote'
    ttl = cache_policy(domain)['ttl'] if ttl is None else ttl
    result, err = None, None
    # 阶段 1：行情/身份（致命）
    url = f'{_BASIC_INFO_BASE_URL}?secu_code={upstream_secu_code(stock_code)}'
    metrics.incr('upstream_fetch_total', key=domain)
    try:
        raw = _rest_fetch(url, _BASIC_INFO_HEADERS, ttl, deadline, refresh_epoch)
        if raw.get('code') == 200 and _basic_info_is_valid(raw):
            result = raw
        else:
            # 含真实错误码与"空壳"（错误 wire 拼写）——后者绝不写缓存/进帧
            err = FetchError('upstream_error', url=url)
            metrics.incr('upstream_fail_total', key='upstream_error')
    except FetchError as exc:
        err = exc
    # 阶段 2：行业名（非致命）★ P7b / BUG-P6C-01：先查 7d sector 缓存，命中即省掉
    #   每次 tick 的第二次上游调用；阶段 1 失败则整段跳过（行业名也终将被丢弃）。
    sector = _basic_sector_get(stock_code) if result is not None else None
    if sector is None and result is not None \
            and (deadline is None or time() < deadline):
        detail_url = f'{_STOCK_DETAIL_BASE_URL}?secu_code={upstream_secu_code(stock_code)}'
        metrics.incr('upstream_fetch_total', key=domain)
        try:
            detail_raw = _fetch_rest_json(detail_url, _STOCK_DETAIL_HEADERS, ttl, deadline)
            if detail_raw.get('code') == 200:
                sector = (detail_raw.get('data', {}).get('primary_industry') or {}) \
                    .get('plate_name', '')
                _basic_sector_put(stock_code, sector)                 # 空值不缓存（§2.7b）
        except Exception:                                             # 非致命：忽略
            pass
    if sector and result is not None:
        if not isinstance(result.get('data'), dict):
            result['data'] = {}
        result['sector_name'] = sector
    # 阶段 3：五档盘口（非致命、只增字段）★ v1.3
    if result is not None:
        depth = fetch_cls_stock_depth(stock_code, deadline=deadline, ttl=ttl,
                                      refresh_epoch=refresh_epoch)
        if depth is not None:
            result['depth'] = depth
    if result is not None:
        return result
    if err is not None:
        raise err
    return None


# 五档盘口 20 个值字段（判"真实盘口" vs 指数返回的 20 档全 0 载荷）
_DEPTH_VALUE_FIELDS = tuple(
    f'{side}_{kind}_{level}'
    for side in ('b', 's') for kind in ('px', 'amount') for level in range(1, 6)
)


def fetch_cls_stock_depth(stock_code, deadline=None, ttl=None, refresh_epoch=None):
    """取五档盘口（dict）或 `None`（**绝不 raise**；失败非致命，§2.1#7）。

    源：`GET _STOCK_DEPTH_URL?secu_code=<wire>&field=five`（无 sign / 无 WS / 无 Chrome）。
    空 `data` dict（未知/无效码）或 20 档全 0（指数 `sh000001`/`sz399001`）⇒ `None`；
    否则返回 data（`b_px_1..5`/`b_amount_1..5`/`s_px_1..5`/`s_amount_1..5` + `preclose_px`）。
    `_depth_store` 把结果写入 `depth` 池 + 终点缓存。
    """
    domain = 'depth'
    url = f'{_STOCK_DEPTH_URL}?secu_code={upstream_secu_code(stock_code)}&field=five'
    ttl = cache_policy(domain)['ttl'] if ttl is None else ttl
    metrics.incr('upstream_fetch_total', key=domain)                  # BR-SA-28
    try:
        raw = _rest_fetch(url, _STOCK_DEPTH_HEADERS, ttl, deadline, refresh_epoch)
    except FetchError:
        return None                                                   # 传输/解码失败：非致命（cache 已计数）
    if raw.get('code') != 200:
        metrics.incr('upstream_fail_total', key='upstream_error')     # 语义失败自建
        return None
    data = raw.get('data')
    if not isinstance(data, dict) or not data:
        return None                                                   # 未知码 / 空壳
    if all(not data.get(f) for f in _DEPTH_VALUE_FIELDS):
        return None                                                   # 指数：无盘口
    _depth_store(stock_code, data)
    return data


def _depth_store(code, data, now=None):
    """把盘口写入 `depth` 池 + 终点缓存（自持 depth 策略：pool_max/cache_max 成为活设置，P2-9）。"""
    policy = cache_policy('depth')
    now = time() if now is None else now
    pool_max = policy['pool_max']
    with _basic_depth_cache_lock:
        _basic_depth_pool[code] = now
        if pool_max is not None and len(_basic_depth_pool) > pool_max:
            victims = sorted(_basic_depth_pool, key=_basic_depth_pool.get)
            for victim in victims[:len(_basic_depth_pool) - pool_max]:
                del _basic_depth_pool[victim]
    _cache_store(_basic_depth_cache, _basic_depth_cache_ts,
                 _basic_depth_cache_lock, code, data, policy['cache_max'],
                 'depth', now)


def _raise_cdp_unavailable():
    """`cdp_unavailable` 的**唯一**出口（计数 + 抛出）——**五处**失败出口全部收口。"""
    metrics.incr('upstream_fail_total', key='cdp_unavailable')        # BR-SA-29
    raise FetchError('cdp_unavailable')


def _acquire_nav_lock(page, remaining):
    """限时获取导航锁（P1-2）。一次导航最长可占 ~60s，而未获取到锁的请求会把自己的
    worker + 准入位一起 park ⇒ CDP 变慢时曾把整站（含 /healthz）打成 503。
    最多等剩余请求预算；超时即降级（跳过该页 → 漏斗处 cdp_unavailable）。"""
    if remaining <= 0:
        return False
    try:
        return page._navigate_lock.acquire(timeout=remaining)
    except Exception:
        return False


def _navigate_f10(page, stock_code, deadline):
    """导航（阻塞在忙页上，但被请求期限兜住）。"""
    remaining = deadline - time()
    if remaining < 2:
        return False
    if not _acquire_nav_lock(page, remaining):                        # 限时（RLock ⇒ 可重入）
        return False
    try:
        return page.navigate_stock(stock_code, tabs=('f10',), timeout=remaining)
    except Exception:
        return False
    finally:
        page._navigate_lock.release()


def fetch_cls_f10(stock_code, deadline=None, ttl=None):
    """CDP 导航；A′ 形状：不可用/取数失败/**数据不匹配** → raise FetchError('cdp_unavailable')。

    ★ P7b / BR-SA-37：**任何**未产出匹配数据的页（未导航 / 无数据 / 显示别的股票）都是
    `cdp_unavailable` 取数失败。静默 `None` 会意味着"无数据、不计"，使 batch 每个 tick
    白付一次整轮导航且没有任何错误信号。
    持有页面导航锁跨越 navigate_stock() 与数据读取（共享页不得在两者之间被改码）；
    锁等待由请求期限兜住（P1-2）。
    `ttl` 仅为签名统一而接收，**未使用**（无 URL 缓存）。
    """
    if not (config.cdp_engine and config.cdp_engine.ready):
        _raise_cdp_unavailable()                                      # 出口①：engine 未就绪
    pages = list(_iter_nav_pages())
    if not pages:
        _raise_cdp_unavailable()                                      # 出口②：无导航页
    d = deadline if deadline is not None else time() + _CDP_CALL_TIMEOUT
    if time() >= d:
        _raise_cdp_unavailable()                                      # 出口③：预算已耗尽
    navigated = False
    got_data = False
    for page in pages:
        remaining = d - time()
        if remaining < 1:
            break
        if not _acquire_nav_lock(page, remaining):                    # ★ 限时，超时换页
            continue
        try:
            if _navigate_f10(page, stock_code, d):
                navigated = True
                data = page_data(page)                                # ★ R18（cdp_engine.page_data）
                if data is None:
                    continue                                          # 该页数据被清，换页
                got_data = True
                r = {}
                _fill_missing(r, data, _F10_EXPECTED_KEYS)
                ci = r.get('stock_company_info')
                if _company_info_matches(ci, stock_code):
                    return ci
        finally:
            page._navigate_lock.release()
    # 出口④/⑤：从未导航成功 / 全部页 page_data=None ⇒ 或 ⇒ 页面显示了别的股票。
    # 两者都是 cdp_unavailable，计数并外显 —— 永不静默 None。
    _raise_cdp_unavailable()
```

> ★ **P7b 口径变更**：v1.1 的 REV-DES-18 曾规定"**有 dict 数据但不匹配** ⇒ 返回 `None`（无数据）"。实现已统一为**同样计 `cdp_unavailable`**（BR-SA-37）——因为"取到但属于别的股票"在实际语义上仍是**本轮未取到该码的数据**，静默 `None` 会让 batch 反复重付导航却无错误信号。`cdp_engine.md §2.1` 已同步。

### 5.10 CDP 直连取数器（prefetch 用）

```python
def _direct_fetch(url, headers, domain, deadline=None, ttl=None):
    """CDP evaluate_fetch 优先（anti-ban），REST 腿**经 `fetch_json`**；失败 raise FetchError。

    仅 prefetch 使用；失败**绝不返回 None**。

    ★ P7b（P2-①）：REST 腿走共享 `fetch_json` 漏斗（URL 正缓存 + 负缓存 + 单飞），
    不再是绕过聚合的第二条裸 urlopen HTTP 入口。**一次逻辑取数只计一次**
    `upstream_fetch_total`（旧版 CDP/REST 两腿各计一次 ⇒ 双计，BR-SA-28）。
    """
    ttl = cache_policy(domain)['ttl'] if ttl is None else ttl
    metrics.incr('upstream_fetch_total', key=domain)                  # 唯一一次
    result = _evaluate_fetch_any(url, deadline=deadline)              # CDP 腿
    if result and result.get('code') == 200:
        return result.get('data')
    raw = _fetch_rest_json(url, headers, ttl, deadline)               # REST 腿（走 fetch_json）
    if raw.get('code') == 200:
        return raw.get('data')
    metrics.incr('upstream_fail_total', key='upstream_error')         # 语义失败自建
    raise FetchError('upstream_error', url=url)


def _fundflow_direct_fetch(stock_code, deadline=None):
    return _direct_fetch(f'{_FUNDFLOW_BASE_URL}?secu_code={upstream_secu_code(stock_code)}',   # ★ v1.3
                         _FUNDFLOW_HEADERS, 'fundflow', deadline)


def _timeline_direct_fetch(stock_code, deadline=None):
    return _direct_fetch(f'{_TIMELINE_BASE_URL}?secu_code={upstream_secu_code(stock_code)}',   # ★ v1.3
                         _TIMELINE_HEADERS, 'timeline', deadline)


def _announcement_direct_fetch(stock_code, deadline=None):
    return _direct_fetch(_announcement_url(stock_code),
                         _ANNOUNCEMENT_HEADERS, 'announcement', deadline)
```

### 5.11 prefetch 循环（4 域共用账本与实现）

```python
def _prefetch_loop(name, domain, fetch_one, pool, cache, cache_ts, cache_lock,
                   after=None, per_call_budget=REQUEST_TIMEOUT):
    while True:
        try:
            sleep(cache_policy(domain)['pool_refresh'])               # BR-SA：间隔 = pool_refresh（无 max）
            codes = _prefetch_rotate(pool, cache_lock, name)
            if not codes:
                continue
            policy = cache_policy(domain)
            pass_deadline = time() + _PREFETCH_PASS_BUDGET
            visited = 0
            for code in codes:
                if time() >= pass_deadline:
                    break
                # ★ P7b / BR-SA-35：**visited**（从轮转头部消费掉的）推进游标，而不是
                #   "processed（写了数据）"或"skipped（冷却）"。只计后者会在"取到但无数据"
                #   （None 是成功但空，永不计数）时冻结游标 ⇒ 头部每轮重取、池尾永不到达。
                visited += 1
                now = time()
                entry = _fail_ledger_get(domain, code, now)           # 与批量共用账本（BR-SA-11）
                if entry is not None and entry[1] > now:
                    continue
                kind = None
                # REV-DES-16：一次调用也消费有界预算。
                call_deadline = min(pass_deadline, now + per_call_budget)
                try:
                    data = fetch_one(code, deadline=call_deadline)
                except FetchError as exc:
                    data, kind = None, exc.kind
                except Exception:
                    data, kind = None, 'upstream_error'
                if data:
                    _cache_store(cache, cache_ts, cache_lock, code, data,
                                 policy['cache_max'], domain)             # 终点缓存独立 LRU
                    _fail_ledger_clear(domain, code)
                    if after is not None:
                        try:
                            after(data, code)
                        except Exception:
                            log.warning('[prefetch:%s] after failed for %s', name, code)
                elif kind:
                    _fail_ledger_record_failure(domain, code, kind)   # 无数据不计（BR-SA-6）
            _prefetch_advance(name, visited, len(codes))              # ★ 访问即推进
        except Exception as e:
            log.error(f'[{name}] prefetch error: {e}')


def _fundflow_prefetch_loop():
    _prefetch_loop('fundflow', 'fundflow', _fundflow_direct_fetch,
                   _fundflow_pool, _fundflow_cache, _fundflow_cache_ts, _fundflow_cache_lock)


def _timeline_prefetch_loop():
    _prefetch_loop('timeline', 'timeline', _timeline_direct_fetch,
                   _timeline_pool, _timeline_cache, _timeline_cache_ts, _timeline_cache_lock)


def _f10_prefetch_loop():
    _prefetch_loop('f10', 'f10', fetch_cls_f10,                       # ★ 直接传（接受 deadline kwarg）
                   _f10_pool, _f10_cache, _f10_cache_ts, _f10_cache_lock,
                   after=_populate_sector_from_f10,
                   per_call_budget=_PREFETCH_CDP_CALL_TIMEOUT)        # REV-DES-16：单码 ≤4s


def _announcement_prefetch_loop():
    _prefetch_loop('announcement', 'announcement', _announcement_direct_fetch,
                   _announcement_pool, _announcement_cache, _announcement_cache_ts,
                   _announcement_cache_lock)
```

### 5.12 轮转原语（保留 + 新增纯函数）

```python
def _prefetch_rotate(pool, lock, key):        # ★ 逐字保留（测试依赖）
    with lock:
        keys = list(pool.keys())
    if not keys:
        return []
    with _prefetch_cursor_lock:
        start = _prefetch_cursor.get(key, 0) % len(keys)
    return keys[start:] + keys[:start]


def _prefetch_advance(key, visited, total):    # ★ P7b：形参 processed → visited（语义同：本轮消费数）
    with _prefetch_cursor_lock:
        _prefetch_cursor[key] = (_prefetch_cursor.get(key, 0) + visited) % max(total, 1)


def _prefetch_slice(pool, lock, key, size):
    """§2.7：返回 (本轮切片, 下一游标值)；**不修改**游标（由调用方 advance）。"""
    ordered = _prefetch_rotate(pool, lock, key)
    if not ordered:
        return [], 0
    size = max(1, min(int(size), len(ordered)))
    with _prefetch_cursor_lock:
        start = _prefetch_cursor.get(key, 0) % len(ordered)
    return ordered[:size], (start + size) % len(ordered)
```

### 5.13 域存储表（必须置于 5 个缓存容器定义之后）

```python
_DOMAIN_STORES = {
    'quote':        (_basic_info_pool,   _basic_info_cache,   _basic_info_cache_ts,   _basic_info_cache_lock),
    'depth':        (_basic_depth_pool,  _basic_depth_cache,  _basic_depth_cache_ts,  _basic_depth_cache_lock),   # ★ v1.3
    'fundflow':     (_fundflow_pool,     _fundflow_cache,     _fundflow_cache_ts,     _fundflow_cache_lock),
    'timeline':     (_timeline_pool,     _timeline_cache,     _timeline_cache_ts,     _timeline_cache_lock),
    'f10':          (_f10_pool,          _f10_cache,          _f10_cache_ts,          _f10_cache_lock),
    'announcement': (_announcement_pool, _announcement_cache, _announcement_cache_ts, _announcement_cache_lock),
}
```

### 5.14 sector 缓存（TTL/上限接 policy）

```python
def _sweep_sector_cache(now=None):
    now = time() if now is None else now
    ttl = cache_policy('sector')['ttl']                               # BR-SA-4
    with _sector_cache_lock:
        expired = [k for k, v in _sector_cache.items()
                   if isinstance(v, dict) and now - v.get('ts', 0) > ttl]
        for k in expired:
            del _sector_cache[k]
    if expired:
        log.info(f'[sector] expired {len(expired)} entries from sector cache')


def _sector_cache_put(code, sector, now=None):
    now = time() if now is None else now
    cap = cache_policy('sector')['cache_max']                         # BR-SA-4（=2000）
    with _sector_cache_lock:
        _sweep_sector_cache(now)
        if len(_sector_cache) >= cap:
            oldest = min(_sector_cache, key=lambda k: _sector_cache[k].get('ts', 0))
            del _sector_cache[oldest]
        _sector_cache[code] = {'sector': sector, 'ts': now}
    metrics.set_gauge('cache_entries', len(_sector_cache), key='sector')
```

### 5.15 detail 派生行业名缓存（§2.7b，P7b）

```python
_basic_sector_cache = {}                     # code -> {'sector': str, 'ts': float}
_basic_sector_lock = threading.Lock()        # 叶锁：绝不跨 IO 持有


def _sweep_basic_sector_locked(now):
    ttl = cache_policy('sector')['ttl']
    expired = [k for k, v in _basic_sector_cache.items()
               if now - v.get('ts', 0) > ttl]
    for k in expired:
        del _basic_sector_cache[k]


def _basic_sector_get(code, now=None):
    """已缓存且未过期的 `sector_name`；否则 None。"""
    now = time() if now is None else now
    with _basic_sector_lock:
        v = _basic_sector_cache.get(code)
        if v is None:
            return None
        if now - v.get('ts', 0) > cache_policy('sector')['ttl']:
            del _basic_sector_cache[code]
            return None
        return v.get('sector')


def _basic_sector_put(code, sector, now=None):
    """写入 `sector`（sector 策略 TTL + 上限；先清扫后淘汰）。空值不缓存。"""
    if not sector:
        return                               # 空 ⇒ 永不缓存（下次重试）
    now = time() if now is None else now
    cap = cache_policy('sector')['cache_max']
    with _basic_sector_lock:
        _sweep_basic_sector_locked(now)
        if code not in _basic_sector_cache and len(_basic_sector_cache) >= cap:
            oldest = min(_basic_sector_cache,
                         key=lambda k: _basic_sector_cache[k].get('ts', 0))
            del _basic_sector_cache[oldest]
        _basic_sector_cache[code] = {'sector': sector, 'ts': now}
```

---

## 6. 错误处理

### 6.1 `FetchError.kind` 映射

| kind | 产生点 | 触发条件 | 对外 |
|------|--------|---------|------|
| `upstream_timeout` | `cache.fetch_json`（`cache._classify`）/ **`_process_chunk` 对 `_LOCAL_BUDGET` 的翻译** | `socket.timeout`/`TimeoutError`；或 `deadline` 已过（**不触网、不入冷却账**，BR-SA-34） | `_errors[code]='upstream_timeout'` |
| `upstream_error` | `cache.fetch_json` / 本层语义失败（`code != 200`、JSON 解码失败、**上游非 dict**） | 其余异常 / 业务 API 返回错误码 / 解码或结构异常 | `_errors[code]='upstream_error'`（自建分支就地计数，REV-DES-13/14） |
| `cdp_unavailable` | `fetch_cls_f10` 的 `_raise_cdp_unavailable()`（**唯一出口，5 处调用**：P7b / BR-SA-37） | CDP 未就绪 / 无导航页 / 预算已耗尽 / 全部导航失败**或全部页 `page_data=None`** / **取到 dict 数据但不属于该码** | `_errors[code]='cdp_unavailable'`（A′） |
| `_LOCAL_BUDGET`（哨兵，**非 kind**） | `_fetch_one`（`deadline` 已过）/ `_run_batch`（预算已过、不建线程） | 我们自己的预算耗尽，未做网络尝试 | **不出现在 `_errors`**（被翻译为 `upstream_timeout`）；**不写 `_fail_ledger`** |

### 6.2 降级路径（分层，互不混淆）

| 层 | 失败 → 行为 | 结果形态 |
|----|-----------|---------|
| 网络层（cache） | 首次失败落 `NEG_TTL=5s` 负缓存；门禁期内 <1ms 快速失败 | `FetchError(kind)` 无延迟放大 |
| 码级（本模块） | 连续 3 次失败 → 120s 冷却；期内**不触网**、直接给枚举 kind | `_errors[code]` 仍非空（值域三分保持） |
| 预算层（本模块） | `deadline` 耗尽 → 未完成码 `upstream_timeout`（经 `_LOCAL_BUDGET` 翻译），**不无界等待**、**不入冷却账** | 有界降级（**AC-E2**：REST 回源 ≤15s；REV-DES-17 引据更正）+ AC-S6 不被自伤式扩散 |
| 端点层（cache/server） | 组装 `_errors`（批量）或 error 客体（单体） | 批量永不顶层 `error`；单体永不含逐码值域 |

**关键不变式**

- 单码故障**不阻塞**其余码（`_run_batch` 并发 + 每码独立 try）；AC-S6 断言 49 码正常。
- `None`（无数据）与 `FetchError`（失败）**永不合并**：前者不入 `_errors`、不冷却；后者入 `_errors`、计冷却。
- **"本地预算耗尽"既不算"无数据"也不算"上游失败"**：对客户端呈现 `upstream_timeout`，但账本零痕迹（BR-SA-34）。
- 失败**不抛到** handler 之外：`_fetch_one` 总函数 → `_run_batch` → `results/errors`；`build_batch_response` 总函数。

---

## 7. 并发安全

### 7.1 锁清单

| 锁 | 保护对象 | 新增/既有 | 备注 |
|----|---------|----------|------|
| `_fundflow_cache_lock` / `_timeline_cache_lock` / `_f10_cache_lock` / `_basic_info_cache_lock` / `_announcement_cache_lock` | 各域 `pool` + `cache` + `cache_ts` | 既有（**复用同一把**，不新增第二把） | 池与终点缓存同域共享一把锁 —— 与现状一致，避免锁序 |
| `_fail_ledger_lock` | `_fail_ledger` | **新增** | 独立叶锁；`_fail_ledger_*` 内**不调用**任何域锁 |
| `_prefetch_cursor_lock` | `_prefetch_cursor` | 既有 | 保留 |
| `_page_fetch_locks_lock` / `_page_fetch_locks[name]` | CDP 页面求值串行 | 既有 | 保留（P2-13） |
| `_sector_cache_lock` | `_sector_cache`（F10 行业名前缀） | 既有 | 保留 |
| `_basic_sector_lock` | `_basic_sector_cache`（detail 派生行业名，P7b） | **新增** | 叶锁；**绝不跨 IO 持有**（`_basic_sector_get/put` 内无网络） |
| `page._navigate_lock`（RLock） | f10 导航串行 | 既有（cdp_engine） | 由 `fetch_cls_f10` **限时**获取（`_acquire_nav_lock`），并跨越 `navigate_stock()` 与数据读取；`_navigate_f10` 内部再次限时获取——**RLock ⇒ 同线程可重入** |

### 7.2 锁序纪律（硬约束）

1. **`_fail_ledger_lock` 与域缓存锁互不嵌套**：`_process_chunk` 先出域锁（池/缓存查）→ 再 `_fail_ledger_get`（取 `_fail_ledger_lock`）；记账（`_fail_ledger_*`）与 `_cache_store` 顺序调用、各自独立锁。
2. **`metrics._lock` 永远最内层**：`_cache_store`/`_fail_ledger_*` **在释放自身锁后**调用 `metrics.set_gauge`（§5.4/§5.3 伪代码已按此写）⇒ 不存在"持域锁 → 取 metrics 锁"的长临界区。
3. **网络 IO 永不持锁**：`_run_batch`/`_fetch_one`/fetcher 全程不持任何本模块锁；`_cache_store` 只在写回时短暂持锁。
4. **`full_chrome_restart`（CDP）与本模块无锁交互**（cdp_engine 既有锁序不变）。
5. **不引入全局大锁**（项目约定）。

### 7.3 热点路径开销

- 命中路径（`cache` TTL 有效）：每码一次 `cache.get` + `move_to_end`（O(1)），无 metrics、无网络；`_fail_ledger_get` 仅在**未命中**时调用 ⇒ 高命中率下冷却账零开销。
- 池 touch 为 `dict` 写（O(1)）；超限淘汰为 `sorted` O(n log n)，仅在 **len(pool) > pool_max** 时触发（2000 条量级、低频）。
- `cached_batch` 只读 + `move_to_end`，供 SSE tick 使用（每 tick ≤ N_active 次）；归一步骤为一次 regex match（P7b）。
- **失败风暴路径（P7b）**：`_fail_ledger_record_failure` 的临界区只做 O(1) 字典写 + O(1) 满额淘汰；O(n) 老化扫描与 O(n) `code_cooldown_list` 重建均**限频 5s** ⇒ n 次失败由 O(n²) 降为 O(n)，且 metrics 发布在锁外。

### 7.4 并发正确性依据

- `_fail_ledger` 的"读-改-写"（计数+1、置 cooldown）**完全在** `_fail_ledger_lock` 内 ⇒ 并发失败计数不丢（可白盒断言：N 线程各失败 1 次 → `fail_count == N`）。
- 终点缓存"查-写"之间可能有并发取数（双检缺失），但**不产生错误数据**：同一码的最坏情形是多取一次、后写覆盖先写（幂等数据）；`cache_ts` 取后写者的时刻（更近）⇒ 不会延长陈旧窗口。
- `cache` 由 `dict → OrderedDict` 后，`move_to_end`/`popitem` 均在同域锁内 ⇒ 无结构竞态。

---

## 8. 测试要点（映射 PRD AC）

| 用例 | 步骤 / 断言（精确） | 覆盖 AC |
|------|-------------------|---------|
| **SA-T1** TTL 同源同变量 | patch `fetch_json` 捕获 `ttl`；调 `handle_cls_fundflow(['sh600519'])` ⇒ 捕获值 `== cache_policy('fundflow')['ttl']`；且终点缓存 `cache_ts` 判定阈值 == 同一值 | **AC-A3** / INV-1a |
| **SA-T2** deadline 贯通 | fetcher stub 记录 `deadline` 实参 ⇒ 与 `_handle_cached_batch` 传入的 `chunk_deadline` 一致；`deadline` 已过 ⇒ `_fetch_one` 不调 fetcher（触网计数 0） | **R13 / AC-E2/S7** |
| **SA-T3** 预算耗尽有界 | `budget = time()-1`、codes=50 ⇒ 全部 `_errors[code]=='upstream_timeout'`、`urlopen` 调用次数 0、耗时 < 0.1s（不建线程） | **AC-S7** |
| **SA-T4** 冷却触发 | 同一码连续失败 3 次（stub 抛 `FetchError('upstream_error')`）⇒ `code_cooldown_list()` 含 `['fundflow','sh600519', ts]`；第 4 次请求 fetcher **未被调用**、`_errors[code]=='upstream_error'` | **AC-S6** |
| **SA-T5** 冷却成功清零 | 失败 2 次 → 成功 1 次 → 再失败 1 次 ⇒ `fail_count == 1`（未触冷却） | **AC-S6** |
| **SA-T6** 无数据不计不清 | stub 返回 `None`（无 kind）⇒ `_fail_ledger` **无**该码条目；`_errors` 不含该码；值 `null` | **AC-A10** |
| **SA-T7** 冷却老化 | 构造 `last_fail_ts = now-121` 的条目 ⇒ `_fail_ledger_get` 返回 `None` 且条目被删；`record_failure` 后 `fail_count == 1` | SS6 / BR-SA-8 |
| **SA-T8** 批量与 prefetch 共用账 | 批量路径把码置冷却 ⇒ prefetch loop 对该码 `skipped`（不调 fetch）；反之亦然 | **AC-S6 / ADR-014** |
| **SA-T9** 池/缓存解耦 | 池超 `pool_max` ⇒ 仅 `pool` 减少；`cache`/`cache_ts` **不变**（旧实现会 pop） | **P1-1 / AC-E6** |
| **SA-T10** 终点缓存独立 LRU | `cache_max=2`：写 A、B → 命中 A → 写 C ⇒ 淘汰 B（非 A）；`cache_entries{domain}` == 2 | **AC-E6** |
| **SA-T11** TTL 过期拒读回源 | `cache_ts[code] = now - ttl - 1` ⇒ 命中判定失败、fetcher 被调 1 次、新值写回 | **AC-A4** |
| **SA-T12** 保留键矩阵 | 无失败无截断 ⇒ 无 `_` 键；有失败 ⇒ 仅 `_errors`；`dropped=20` ⇒ `_truncated=true` ∧ `_dropped_count=20`；`dropped=0` ⇒ 两键都不存在 | **AC-A9 / A10** |
| **SA-T13** 三类码值域 | 1 失败码 + 1 非法码 + 1 无数据码 ⇒ 三者值皆 `null`；仅失败码 ∈ `_errors`，值 ∈ KINDS | **AC-A10** |
| **SA-T14** 批量 1:1 映射/分片 | 60 码（>50）⇒ 结果键集合 == 码集合（60），无丢码；fetcher 实际收到全部 60 码（跨 2 chunk） | **AC-A6**（含 `test_stream.BatchShardingTests` 回归） |
| **SA-T15** f10 A′ 降级 | `config.cdp_engine = None` ⇒ `fetch_cls_f10` 抛 `cdp_unavailable`；`handle_cls_f10(['sh600519'])` ⇒ `{'sh600519': None, '_errors': {'sh600519': 'cdp_unavailable'}}`（**非** error 客体） | **AC-S4 A′** |
| **SA-T16** `_run_batch` 结构 | 返回值解包为 `(dict, dict)`；errors 仅含失败码；`concurrent=False` 时按码序串行（stub 记录调用序） | SAD D-2 / AR-4 |
| **SA-T17** 预取间隔接 policy | `_prefetch_loop` 首轮 `sleep` 实参 == `cache_policy(domain)['pool_refresh']`（fundflow 盘中 8，非盘中 120） | **AR-6 / R12** |
| **SA-T18** 轮转回归 | `_prefetch_rotate`/`_prefetch_advance` 既有用例原样通过；`_prefetch_slice` 不改游标 | 回归 |
| **SA-T19** sector 接 policy | `_sector_cache_put` 上限 == `cache_policy('sector')['cache_max']`；`_sweep_sector_cache` 阈值 == `['ttl']` | R16 |
| **SA-T20** metrics 名合法 | 一轮批量后 `set(metrics.snapshot()) ⊆ metrics._KNOWN` | **AC-S10 / MET-T8b** |
| **SA-T21** 防重复计数 | stub 抛 `FetchError('upstream_timeout')`（模拟 cache 已计数）⇒ 本模块**不**新增 `upstream_fail_total['upstream_timeout']` | BR-SA-29 |
| **SA-T22** `cached_batch` 无网络 | 预热缓存后 `cached_batch('quote', codes)` ⇒ 不产生任何 `fetch_json` 调用；仅返回 TTL 未过期的码 | **AR-1 / AC-E5** |
| **SA-T23** 60 码既有回归 | `test_stream.BatchShardingTests` 原样通过（`handle_cls_basic_infos` 返回组装 dict、60 码全覆盖） | PRD §9「存量用例」 |
| **SA-T24** 测试隔离 | 涉及冷却的用例须在 `setUp`/`tearDown` 清空 `_fail_ledger`（持 `_fail_ledger_lock`）并 `metrics.reset()`；否则跨用例残留的冷却条目会使 `set(result) == set(codes)` 类断言因 `_errors` 误红 | 用例可靠性 |
| **SA-T25** 预算耗尽**不**计冷却账（P7b 改写） | `budget = time()-1`、单码 ⇒ `_errors[code]=='upstream_timeout'`（客户端形态不变）**且** `_fail_ledger` 该码**无条目**、`code_cooldown_list()` 不含它（`_LOCAL_BUDGET` 翻译但**不入账**，BR-SA-34）；与 SA-T6「无数据不计」互补 | AC-S6 |
| **SA-T30** `_LOCAL_BUDGET` 全链路（P7b） | ① `deadline=time()-1` 单码 ⇒ fetcher **未被调用**、`_errors[code]=='upstream_timeout'`、`_fail_ledger` 空；② `_run_batch` 预算已过 ⇒ 不建线程（`ThreadPoolExecutor` 未构造）；③ 任意进入账本的 kind ∈ `FetchError.KINDS`（哨兵永不入账） | BR-SA-34 / S7 |
| **SA-T31** `_call_fetcher` 仅调用帧降级（P7b） | ① 单参 stub `_fake_fetch(code)` ⇒ 成功降级到 `{}` 档并返回数据（**不抛**）；② fetcher **函数体内** `raise TypeError` ⇒ **原样上抛**、`_fetch_one` 归类 `upstream_error` 且**只执行一次**（调用计数 == 1）；③ 接受 `{deadline}` 但不接受 `ttl` 的 stub ⇒ 收到 `deadline`（预算不丢） | P2-④ / R13 |
| **SA-T32** 账本 O(1) 淘汰与 5s 限速（P7b） | ① 灌满 `_FAIL_LEDGER_MAX+1` 条 ⇒ 淘汰的是**最早注册**的键，单次写入耗时不随 n 增长（无 `sorted`）；② 连续 n 次失败在 5s 内**只发布 1 次** `code_cooldown_list`；③ 冷却开启那一次也走节流（不额外多一次发布） | S1-3 / AC-S10 |
| **SA-T33** 归一与回填（P7b） | 同一码以 `sh600519` / `600519.SH` 两次请求 ⇒ **同一**池条目 / 终点缓存条目 / 账本条目（各 1 条）；响应分别以 `sh600519`、`600519.SH` 为键；`cached_batch('quote', ['600519.SH'])` 能读到 `sh600519` 预热的数据 | P1-6 / AC-A6 |
| **SA-T34** f10 五出口 + `_basic_sector` 缓存（P7b） | ① 五出口（engine=None / 无页 / `deadline=time()-1` / 全页 `page_data=None` / **有数据但不匹配**）各使 `upstream_fail_total['cdp_unavailable']` +1 且抛 `FetchError`（**均不返回 `None`**）；② 导航锁被他人长持 ⇒ `_acquire_nav_lock` 超时返回 False、换页降级（不 park）；③ `_basic_sector_put` 后 `fetch_cls_basic_info` 阶段 2 **不再**发第二次 REST（`upstream_fetch_total` 少 1） | AC-S4 A′ / BUG-P6C-01 |
| **SA-T26** `cdp_unavailable` 全出口计数 | 分别构造 engine=None / 无导航页 / `deadline=time()-1` / 导航全失败 ⇒ 四次调用各使 `upstream_fail_total['cdp_unavailable']` 增 1（**旧版仅出口④计数**，REV-DES-12） | AC-S10 / BR-SA-29 |
| **SA-T27** 自建 `upstream_error` 计数 | patch `fetch_json` 返回非 JSON 文本 ⇒ `_fetch_rest_json` 抛 `upstream_error` 且 `upstream_fail_total['upstream_error']` +1；返回合法 JSON 数组/标量 ⇒ 同样 +1 且抛错（REV-DES-13/14） | AC-S10 |
| **SA-T28** f10 `page_data=None` → `cdp_unavailable` | patch `page_data` 恒返回 `None` + `_navigate_f10` 恒成功 ⇒ `fetch_cls_f10` 抛 `cdp_unavailable`（**非**返回 `None`）；`_navigate_f10` 全失败亦然（REV-DES-18） | AC-S4 A′ |
| **SA-T29** prefetch 期限贯通 | `_prefetch_loop` 内 stub `fetch_one(code, deadline=...)` 捕获实参 ⇒ `deadline` 非 None 且 `<= min(pass_deadline, now + per_call_budget)`；`_f10_prefetch_loop` 的 `per_call_budget == _PREFETCH_CDP_CALL_TIMEOUT`（REV-DES-16） | R13 / AC-E2 |
| **SA-T35** `depth` 域取数 + 空壳语义（v1.3） | ① `fetch_cls_stock_depth` 对 `data:{}` / **20 档全 0**（指数）⇒ `None`；② 正常载荷 ⇒ 返回 dict 且 `_basic_depth_pool`/`_basic_depth_cache` 各增 1（`cache_entries{depth}` 发布）；③ `code != 200` ⇒ `None` + `upstream_fail_total['upstream_error']` +1；④ patch `_fetch_rest_json` 抛 `FetchError` ⇒ `None`（**不抛**）；⑤ URL 含 `&field=five` 且 `secu_code` 为 `upstream_secu_code` 拼写 | BUG-SSE-DEPTH-01 |
| **SA-T36** `fetch_cls_basic_info` 三阶段（v1.3） | 阶段 1 成功 ⇒ 调阶段 3 且 `result['depth']` 存在；阶段 1 **空壳**（`secu_name`/`last_px` 全空）⇒ 抛 `upstream_error`、**阶段 2/3 均不被调用**、不写缓存；阶段 3 失败 ⇒ quote 仍返回（**无** `depth` 键）；阶段 2 命中 `_basic_sector_cache` ⇒ 不发第二次 REST（`upstream_fetch_total` 少 1） | BUG-SSE-DEPTH-01 / BUG-P6C-01 |
| **SA-T37** `upstream_secu_code` 全量应用（v1.3） | patch `cache.fetch_json` 捕获 URL：`sh600519` ⇒ `secu_code=sh600519`；`bj430047` ⇒ `secu_code=430047.BJ`（**点号形**）；覆盖 fundflow/timeline/basic/detail/depth/announcement（签名 URL）与两个 prefetch 直连；全仓 grep `secu_code={stock_code}` ⇒ 0 命中 | BUG-北交所 |
| **SA-T38** `refresh_epoch` 贯通（v1.3） | ① `handle_cls_basic_infos(codes, refresh_epoch=t)` ⇒ fetcher stub 收到 `refresh_epoch==t`；② 终点缓存 `written = t-1`（TTL 未过）⇒ 以 `refresh_epoch=t` 读**不命中**（fetcher 被调 1 次）、以 `refresh_epoch=None` 读**命中**（fetcher 0 次）；③ `handle_cls_f10`/`handle_cls_announcement`/`handle_cls_stock_batch` **签名不收**该参数；④ 仅接受 3 参的 fetcher stub ⇒ 仍被调用（调用帧 TypeError 降级） | BUG-SSE-DEPTH-01 / `cache.md` BR-CACHE-31 |
| **SA-T39** `BATCH_MAX_WORKERS` 公开别名（v1.3） | `stock_api.BATCH_MAX_WORKERS == config.BATCH_MAX_WORKERS == 20`（无 env）；`_BATCH_MAX_WORKERS` 同值；`stream.refresh_capacity(4, ['quote'])` ⇒ `coverage == 213`、`coverage_codes == 106` | E5 / BUG-SSE-DEPTH-01 |

---

## 9. AC 追溯矩阵

| 本模块设计点 | 覆盖 AC |
|-------------|---------|
| `cache_policy` 单次取值贯穿终点 TTL 与 `fetch_json(ttl=)`（BR-SA-1/2）= INV-1a 落点 2 | **AC-A3**（同层同源、无 120s 断崖）/ **AC-A4** / R12/R16 |
| 分块 ≤50 不丢码 + `build_batch_response` 保序去重（§5.7/5.8） | **AC-A6**（1:1 映射、50/60 码无丢） |
| 池上限**按域独立**（`quote`/`fundflow`=1000、`timeline`=500；`depth`/`announcement`/`f10`=`MAX_DEDUP_CODES`=2000；★ v1.7：前 3 者经 `'env:MAX_*_POOL'` 派生、可免改码调参）、池/缓存解耦（BR-SA-13/14） | **AC-A7**（去重池 ≤2000）/ **AC-E6** / `config.md` §10#24（PRF-MEM-01） |
| `dropped` 透传组装点（§2.4） | **AC-A9**（`_truncated`/`_dropped_count`） |
| `(results, errors)` + fetcher 失败 raise / 无数据 None（§2.1/2.3） | **AC-A10**（失败 ≠ null）/ **AC-S6** |
| `_fail_ledger` 120s 冷却 + 批量/prefetch 共用（BR-SA-5..12） | **AC-S6**（同码 3 次失败 → 冷却期不回源） |
| `deadline` 贯通 + chunk 预算 + 预算耗尽早退（BR-SA-18..25） | **AC-E2**（REST 回源 ≤15s 有界；REV-DES-17）/ **AC-S7**（超时兜底）/ **R13** |
| `FetchError` 分类 + 端点层组装（§6） | **AC-S1**（异常兜底）/ **AC-A5**（error 客体 vs 值域） |
| f10 `cdp_unavailable`（§5.9） | **AC-S4 A′**（`_errors[code]=cdp_unavailable`） |
| `announcement` 删裸 `ttl=15`，接 L3（§5.9） | **AC-A3 / Q5**（TTL 单一权威） |
| `cache_max` 独立 LRU（BR-SA-15） | **AC-E6**（URL/缓存有界）/ AR-8 |
| `code_cooldown_list` / `cache_entries` / `upstream_fetch_total` / `upstream_fail_total` | **AC-S10** / AR-6 |
| `BATCH_MAX_WORKERS` + `_prefetch_slice` + `cached_batch`（跨模块供 stream） | **AR-1 / INV-1b / AC-E5**（调度在 `stream.md`） |
| 既有 `test_stream.BatchShardingTests` / `test_server` 轮转用例保持通过 | PRD §9 存量用例全绿 |
| **`_LOCAL_BUDGET` 不入账（BR-SA-34）** | **AC-S6**（单码故障不扩散；慢批次不自伤冷却） |
| **`_call_fetcher` 仅调用帧降级（BR-SA-21）** | **R13**（生产路径无期限丢失）/ AC-E2 |
| **`_direct_fetch` REST 腿经 `fetch_json`（BR-SA-28）** | **AC-E6**（URL 缓存/负缓存/单飞对 prefetch 同样生效）/ 观察口径不双计 |
| **归一与按请求拼写回填（BR-SA-36）** | **AC-A6**（1:1 映射）/ **AC-A7**（去重池同一性） |
| **f10 五出口 + 限时导航锁（BR-SA-37）** | **AC-S4 A′** / **AC-S1**（CDP 慢不拖垮准入） |
| **账本 5s 限速 + O(1) 淘汰（BR-SA-8/9/12b）** | S1-3（失败风暴不退化）/ AC-S10 |
| **`_basic_sector` 缓存（§2.7b）** | 上游负载核算（BUG-P6C-01；非 AC，观测项） |
| **prefetch 访问即推进（BR-SA-35）** | **AC-E5 / AR-1**（大池轮转公平、池尾可触达） |
| **`depth` 域取数 + 空壳语义（§2.1#7 / §5.9 / SA-T35·T36）** | **AC-A1 / E5**（五档盘口随 quote 同拍；索引/无效码不伪造数据；BUG-SSE-DEPTH-01） |
| **`upstream_secu_code` wire 拼写全量应用（§2.1 / §5.9 / SA-T37）** | 北交所行情正确性（BUG-北交所；观测项） |
| **`refresh_epoch` 计划刷新下限（BR-SA-38 / SA-T38）** | **AC-E5**（每拍真回源，消除 `ttl==tick` 隔拍旧值） |
| **`BATCH_MAX_WORKERS=20`（§3.4 / SA-T39）** | **E5 / AC-E5**（SSE 覆盖模型标定输入；协同 `stream.md`） |

---

## 10. 与 SAD / 现有代码的偏差与歧义标注（不擅自改 SAD）

| # | 项 | SAD 表述 | 本文裁决 | 理由 |
|---|----|---------|---------|------|
| 1 | **handler 返回结构** | §2.4 统一调用顺序写 `_guard(handler, shape='batch')  # handler 返回 (results, errors)`；同节又写"所有批量 handler 统一返回该结构（组装体）"+ server 注入 `dropped` | `handle_cls_*(codes, deadline=None, dropped=0) -> dict`（**内部**交 `build_batch_response`，`dropped` 由 server 传参） | ① tech-stack `namingRules.handlers` 要求 `handle_* 返回 dict 不抛`；② `stream._refresh_pool` 消费的是**组装后**扁平映射，SAD 自身要求其"跳过 `_` 前缀键"（AR-7）⇒ 只有组装体才含 `_errors`；③ `dropped` 经同一组装点入参，满足"server 只注入、不重复组装"。**登记项①：编排层已批准**（SAD §2.4 措辞由 system-architect 回改为"管道层返回二元组，handler 交 `build_batch_response` 组装为 dict"）|
| 2 | `_fail_ledger` 条目 | §2.3 D-6 写 `[fail_count:int, cooldown_until:float]` | 扩为 `[fail_count, cooldown_until, kind, last_fail_ts]` | `kind`：SAD 伪代码自身引用 `entry_kind`（冷却期 `_errors` 需枚举码）；`last_fail_ts`：实现"**连续**失败"老化与账本有界（§4.3 SAD 要求"≤ 活跃码数"）。**登记项②：编排层已批准**（SAD D-6 同步为 4 元）|
| 3 | 取数器签名 | §2.3 D-2 只新增 `deadline` | 新增 `ttl` 第二可选参数 | 为满足 INV-1a 落点 2"同源同变量"（评审 §四 提醒 `stock_api.md` 必须落实）。`ttl=None` 回退 policy ⇒ 直接调用亦同源。**登记项③：编排层已批准** |
| 4 | `/stock/data` 缓存结构 | §3 stock_api 行未细分 | `/stock/data` **无**去重池、**无**终点缓存（`cache=None`），仅 `fetch_json` URL 缓存；与 `basic_info` 共用 `quote` 域 policy 但**不共用缓存** | 两会话数据形状不同，共用终点缓存会串数据；URL 缓存（ttl=8s）已满足新鲜度，再加一层终点缓存冗余。仍走同一冷却/错误管道 |
| 4b | `/stock/data` 的**冷却账域键** | SAD §2.3 D-6：ledger 键 `(domain, code)` | 沿用 `domain='quote'` ⇒ 与 `/stock/basic_info` **共享**同一 `(quote, code)` 冷却条目 | 二者确实共用同一上游地址族（`basic_info` 阶段 2 的行业查询与 `/stock/data` 同用 `_STOCK_DETAIL_BASE_URL?secu_code=`）⇒ 失败域天然重叠，共账语义成立；**代价**：`/stock/data` 连失 3 次会同时冷却该码的 `basic_info`（保守方向，不产生错误数据，仅可能多一次降级）。**登记项④：编排层已接受**（跨端点耦合登记）|
| 5 | 池上限放大 | §2.1/§4.3 给出 `pool_max='dedup'=2000` | fundflow/timeline 500→2000、f10/announcement 300→2000（basic_info 已在 `config.md` 登记） | 域口径 `dedup`；数据内存改由 `cache_max` 独立 LRU 承担，须纳入 AC-S9/AR-8 总账。**登记项⑤：编排层已批准**（★ v1.6：该口径已由 **§10#27 PRF-MEM-01** 更新——`quote`/`fundflow`/`timeline` 进一步 **同源收缩**为 `'fixed:1000'`/`'fixed:1000'`/`'fixed:500'`） |
| 6 | `announcement` 域 TTL | Q5：删裸 `ttl=15`/pool 60s → L3 | 已落实（`cache_policy('announcement')['ttl']` + `pool_refresh`） | 无偏差 |
| 7 | `_evaluate_fetch_any` 的 per-page 预算 | SAD 未细化 | 保留 `min(remaining, 2)`，总窗口收缩为 `min(time()+8, deadline)` | 期限贯通到 CDP 回退路径 |
| 8 | `_fetch_one` 兼容回退（**P7b 更新**） | ADR-009 决策 C 要求删除 `TypeError` 回退 | **保留**降级，但**上收为 `_call_fetcher`**：4 档关键字尝试，且**仅当 TypeError 抛自调用帧**（`tb_next is None`）才降级；函数体内的 TypeError 原样上抛（避免重复执行取数） | 存量用例以单参 `_fake_fetch` patch 取数器；生产取数器全部接受新参数 ⇒ 生产路径无期限丢失。**旧版"except TypeError 后重调 fetcher(code)"会把体内的类型错误也吞掉并重执行**（P2-④） |
| 9 | 分片轮转刷新（`_refresh_pool` / `stream_refresh_lag_ticks`） | §2.2 R-6 / §3 stream 行 | **本体属 `stream.py`**；本模块只提供 `BATCH_MAX_WORKERS`、`_prefetch_rotate/_prefetch_advance/_prefetch_slice`、`cached_batch`、以及 handler 契约 | `layerIsolation` 方向为 `stream → stock_api`；把 `_refresh_pool` 放本模块会反向依赖 stream。**登记项⑦：编排层已批准**；跨模块约定已写入 `_PROGRESS.md` |
| 10 | CDP 批量预算（**REV-DES-21**） | SAD 未钉数值；**AC-E2 的 ≤15s 仅限 REST 回源**，AC-S7 超时矩阵未含批量整体上限 | `_BATCH_BUDGET_CDP=60`（保留现状） | **编排层已裁决：接受现状 + 登记风险**（f10 非热路径，无 AC 硬违反）。**引据更正为 AC-E2**（REV-DES-17）；**遗留风险**：`/stock/f10` 多码请求端到端可达 60s；缓解 = 建议 `server.md` 强制"f10 仅单码/少量码"（**当前未强制**，编排层同步）+ stream 分片。**登记项⑥**。★ **v1.5 裁定注（台账收口 · 用户裁定 2026-09-18）**：**已知情接受**——用户裁定 `/stock/f10` **极少调用甚至基本上不会有请求调用** ⇒ **不实现**「仅单码 / 少量码」上限，**不构成问题**；上句「**当前未强制**」**为事实陈述、原样保留**（= 知情接受，**不是遗漏**；实际暴露面 ≈ 零）。**残留风险 / 触发条件**：若将来该端点**被大量调用**，须按「参数错误 ⇒ **400** + PRD AC + 详设 + 测试」**整链**补上限。**本项不再是待办。** |
| 11 | `handle_cls_stock` | SAD 未提 | 保留（`server.py:55` import 兼容），改为薄封装吞异常返回 `None` | 避免 import 破坏；单码非路由，行为与现状等价（现状亦返回 `None`） |
| 12 | `_FAIL_DOMAINS` 5 域 | SAD §4.3 称账本"≤ 活跃码数" | 硬上限 `5 × MAX_DEDUP_CODES = 10000` | 5 个消费域各可能达 2000 活跃码；列表条目极小，10000 条内存可忽略 |
| 13 | `BATCH_MAX_WORKERS` 公开别名 | 无 | 新增公开名（内部 `_BATCH_MAX_WORKERS` 保留） | `stream.md` 计算 `coverage` 需读线程上限；避免读私有名 |
| 14 | **预算耗尽的记账（P7b 改写，取代 REV-DES-15）** | SAD/AC 未定义 | **新口径**：预算耗尽 ⇒ `_LOCAL_BUDGET` 哨兵 ⇒ 客户端见 `upstream_timeout`，但**不写 `_fail_ledger`**（BR-SA-34） | v1.1 的 REV-DES-15 裁决②（"照常计入冷却账"）**已实现取代**：计入会使一次慢 batch 冷却整条池尾，形成自伤正反馈，与 AC-S6「单码故障不扩散」直接冲突。与 `cache.md` BR-CACHE-23（本地等待预算不落负缓存/不计数）**同源一致**。SA-T25 已改写 |
| 15 | **f10 `page_data=None` 语义（REV-DES-18 + P7b 收口）** | `cdp_engine.md` §2.1 曾称"仅**有 dict 数据但不匹配**才返回 `None`" | **统一钉死（P7b 最终态）**：**五条失败出口全部** `cdp_unavailable` —— engine 未就绪 / 无导航页 / 预算耗尽 / 全部导航失败**或全部页 `page_data=None`** / **取到数据但不匹配**（BR-SA-37）。不再有任何"静默 `None`"的失败路径 | "取到但属于别的股票"≠"该码无数据"：静默 `None` 会让 batch 每 tick 白付整轮导航且无错误信号。`cdp_engine.md §2.1` 已同步（两文档一致） |
| 16 | **`cdp_engine` 依赖（REV-DES-10）** | tech-stack 未列 `stock_api.py` 的 `layerIsolation` | 允许 `from .cdp_engine import page_data`（R18 唯一入口）；同层依赖 `stock_api → cdp_engine` 由**编排层在 SAD §3 + `tech-stack.json`** 登记 | 无环（`cdp_engine` 不 import 业务模块）；不放行则该依赖无法编码（旧版 §1.3 禁 import 与 §5.9 调用 `page_data` 自相矛盾） |
| 17 | **P7b · `config.canonical_code` 归一（P1-6）** | SAD 未定义代码归一 | 池/终点缓存/账本键**一律 canonical**；响应按**请求原拼写**回填（BR-SA-36） | 消除"同一股票多身份"：否则 `600519.SH` 与 `sh600519` 各铸一份池/缓存/冷却，CDP 精确比较也只可能匹配一种拼写 |
| 18 | **P7b · `_direct_fetch` REST 腿经 `fetch_json`** | SAD §2.2 R-6/§7.2 未定义 prefetch 的 HTTP 入口 | 统一走 `cache.fetch_json`（正缓存 + 负缓存 + 单飞）；单次逻辑取数只计 1 次 `upstream_fetch_total`（BR-SA-28） | 裸 `urlopen` 是绕过聚合的第二条 HTTP 入口，prefetch 看不到缓存/负缓存，且每次必回源；双计使 `upstream_fetch_total` 虚高 |
| 19 | **P7b · `_fail_ledger` 限频与 O(1) 淘汰** | SAD §4.3 称账本"≤ 活跃码数" | 老化扫描限频 5s、上限淘汰 O(1)（插入序）、冷却发布限频 5s（BR-SA-8/9/12b） | 原实现每次失败写都做 O(n) 扫描 + O(n) 重建 + 满额时 O(n log n) 排序 ⇒ n 次失败风暴 O(n²)，恰在系统已故障时自我放大 |
| 20 | **P7b · `_basic_sector_cache`** | SAD 未提 | 新增 detail 派生行业名缓存（7d `sector` 策略；空值不缓存；无专属 gauge） | BUG-P6C-01 根因 2：quote 域每次 tick 的第二次 REST（行业名）被缓存吸收 ⇒ 该笔调用归零；**★ v1.3 补充**：稳态 quote 成本实为 **2 调用/码**（basic + depth），行业名**不含在内** |
| 21 | **v1.3 · `depth` 域 + `fetch_cls_stock_depth`** | `DOMAIN_MATRIX` 未列 `depth`（`config.md` §3.2 已登记）；SAD §2.2 未定义五档 | 新增 `fetch_cls_stock_depth`（`_STOCK_DEPTH_URL?field=five`）+ `_depth_store` + `_DEPTH_VALUE_FIELDS`；**空 dict / 20 档全 0 ⇒ `None`**；随 `fetch_cls_basic_info` 阶段 3 附加（`_DOMAIN_STORES['depth']`） | BUG-SSE-DEPTH-01：`quote` 帧需含五档盘口；指数/无效码无盘口 ⇒ **绝不伪造全 0 载荷**（`depth` 域 TTL=L0，与 quote 同拍） |
| 22 | **v1.3 · 空壳防御 `_basic_info_is_valid`** | SAD 未定义 | `code:200` 但 `data` 非 dict / 空 / `secu_name`&`last_px` 全空 ⇒ 视 **`upstream_error`**（不写缓存、**不进阶段 2/3**） | 错误 `secu_code` 拼写（尤北交所前缀形）返回 **HTTP 200 + 41 键全 null**；信任 `code==200` 会把空壳缓存并流进帧 |
| 23 | **v1.3 · `upstream_secu_code` 全量应用** | `config.upstream_secu_code` 已存在；SAD §2.1 未定义"身份 vs wire 拼写" | 池/缓存/账本键仍 canonical；**URL 构造**一律 `upstream_secu_code`（SH/SZ 前缀形、BSE 点号形 `430047.BJ`） | 拼写混用曾致北交所行情全空（前缀形返回空壳）；身份唯一、wire 只在 URL 边界转换（`config.md` §2.8） |
| 24 | **v1.3 · `refresh_epoch` 贯通** | SAD §2.3 D-1 无该形参（`cache.md` v1.4 已登记 BR-CACHE-31） | 终点缓存命中 = TTL 有效 **且** `written >= refresh_epoch`；经 `_run_batch`/`_fetch_one`/`_call_fetcher` + `_rest_fetch` 下传；`None` ⇒ 逐字不变 | `ttl==tick` 相位耦合使名义 4s 刷新实际 8s（BUG-SSE-DEPTH-01）；写路径不感知（仍写完整 TTL） |
| 25 | **v1.3 · `BATCH_MAX_WORKERS` 8→20** | SAD §3 config 行已登记 env | `BATCH_MAX_WORKERS = config.BATCH_MAX_WORKERS`（=20；公开别名保留） | `stream.refresh_capacity` 的标定输入；`HTTP_POOL_MAX_PER_HOST=24 ≥ 20` 保证批扇出不在池上排队（BUG-SSE-DEPTH-01） |
| 26 | **v1.3 · `fetch_cls_basic_info` 三阶段** | SAD §2.2 R-6 未定义 quote 组成 | 阶段 3 depth（非致命、只增字段）；阶段 1/3 传 epoch、**阶段 2 留 TTL** | quote 刷新 = basic + depth 两次调用；行业名由 7d 缓存吸收，不每拍付费 |
| 27 | **v1.6 · PRF-MEM-01 内存收缩（3 域 pool/cache 同源缩小）**；**★ v1.7 · 修复轮：pool 上限 env 化 + CR-04 降级面 + CR-06**；**★ v1.9 · 归因纠偏 + PRF-MEM-02 arena 治理实测**；**★ v1.10 · P8-r1 P1/P2 收尾（`'env:<NAME>'` 导入期冻结 + 名单同源 + `ValueError` + 测试 hermetic 化）** | SAD §2.1 矩阵与 §4.3/AR-8 内存总账对 `quote`/`fundflow`/`timeline` 按 `'dedup'`=2000、`cache_max=2000` 估算（★ SAD 已于 **v1.15** 承接本修复轮：三行 spec 改 env、新增"终端缓存上界不变式更正"、`depth` 理由与 prefetch 事实更正） | **v1.6**：`config.md` v1.8 把这 3 域改为 `'fixed:1000'`/`'fixed:1000'`/`'fixed:500'`（`cache_max` 同步 1000/1000/500），本模块 §3.3/§3.5/BR-SA-13 同步（**仅消费 `policy`，行为自动跟随**）。**★ v1.7（修复轮）**：`config.md` **v1.9** 把三行 spec 改为 **`'env:MAX_QUOTE_POOL'`/`'env:MAX_FUNDFLOW_POOL'`/`'env:MAX_TIMELINE_POOL'`**（默认值不变 **1000/1000/500**，经**导入期冻结**的注册映射 `_POOL_MAX_ENVS` 取值（键=NAME、值=冻结值、名单与取值同源；★ v1.10 更正：**不再 `globals()`**）；`cache_max` 仍为字面量 = 内存硬界）；本模块 §3.3/§3.5/BR-SA-13 同步"来源变更"（代码零改动）；**CR-04**：`cache_max`（1000/500）**首次 < 活跃码上界 2000** ⇒ 「终端缓存覆盖活跃全集」**不再成立**，降级 = 严格 LRU 淘汰 + 消费方 `stream._last_known` 结转（**功能不破坏**，仅命中率下降/上游取数上升）；**CR-06**：`depth` 池保持 `'dedup'` 的理由（**无 prefetch 循环**、池仅 `code→ts` 账本、`cache_max=500` 才是内存界） | **PRF-MEM-01（2026-09-20）**：压测内存高水位 **96.57%**；**原归因（v1.6/v1.7 假设 · ★ v1.8 实测已更正）** = 终态缓存顶满 `cache_max` + `timeline` 单条 ~96KB + prefetch（**间隔 = `pool_refresh` = `ttl × refresh_factor`**：quote/depth 盘中 **4s**、fundflow/timeline **8s**、非盘 **120s**——★ v1.7 更正原"120s 轮询"误述）保活使 LRU 不淘汰；**同源收缩**使保活范围收敛 ⇒ **★ v1.8 实测（run 20260920-110805，证伪乐观预期）**：python RSS **1.095GiB → 1.012GiB（净收益仅 ~83MiB）**、容器 **1.449GiB(96.57%) → 1.41GiB(93.98%)** ⇒ **本次收缩未达成内存目标**；终端缓存只是小头。**★ v1.9 归因纠偏（v1.8 的 URL 缓存归因已被证伪）**：共享 URL 缓存存的是**解码后的原始响应文本（`str`）**（`cache.py:851-852` `resp.read().decode(...)` → `_cache_put`；`json.loads` 在调用方命中后解析），**非**解析对象，总量仅**几十 MB**、**非内存大头**；**真因 = glibc arena**（33 线程 × 默认最多 `8×ncores` 个 64MB arena，`RssAnon` 占 98%）——A/B 实测（run 20260920-113125）`MALLOC_ARENA_MAX=2` ⇒ python VmRSS **1.008GiB → 0.772GiB**、VmSize **8.96GB → 1.15GB**、容器 **1.41GiB(93.98%) → 1.259GiB(83.95%)**；累计链路 **1.095GiB → 1.012GiB → 0.772GiB**（容器 **1.449 → 1.41 → 1.259GiB**），剩余 = 终端缓存解析对象（~200MB）+ 运行时/分配器残余。基线 tier1000 `timeline` `ok_rate` 100%→89.6% / `upstream_timeout` 123→317 **待复测归因，尚非结论**；arena A/B 下回升至 **100%**（**单次观测，可能含上游波动，勿写成结论**）。**无接口 / 对外契约变更**；本模块 `_FAIL_LEDGER_MAX`（`5×MAX_DEDUP_CODES`=10000）不受影响（`MAX_DEDUP_CODES` 未变）。权威登记见 `config.md` §10#24 |

> ★ **P8-r2 补记（§10#27 · `config.md` v1.13 · 只改文档，不改代码）**：`_POOL_MAX_ENVS` 由普通可变 `dict` 改为 **`MappingProxyType`（不可变映射）**——运行期**改键 / 改值 / 新增键一律 `TypeError`**；`_resolve_pool_max` 的 `'env:'` 分支恢复 **`int(_POOL_MAX_ENVS[name])` 类型归一**（当前合法值不变）。**本模块只消费 `policy['pool_max']` / `policy['cache_max']`（默认 1000/1000/500 不变）⇒ 消费侧逐字不变、代码零改动。** **版本保持 v1.10**（本轮 `stock_api.py` 代码零变更、仅交叉引用补记，不触发版本号变动）。

---

## 11. 交付自检

- [x] 无 `{例:` 占位符；签名/默认值/返回结构/错误码/边界值均为实值
- [x] `fetch_*(code, deadline=None, ttl=None)` **全清单**（6 码级 + 3 直连）逐一列出，含域与 `deadline`/`ttl` 用法
- [x] `(results, errors)`、`_fail_ledger`（4 元）、分片游标、域存储表均在 §3 以 yaml 给出
- [x] 业务规则编号 BR-SA-1..33，伪代码直接引用编号
- [x] 冷却判定:位置/计数口径/触发/老化/上限/协同 逐条钉死；池轮转与池-缓存解耦逐条钉死
- [x] deadline 传递链逐层可验证（handler→budget→chunk_deadline→`_fetch_one`→fetcher→`urlopen`）
- [x] 锁清单 + 锁序（域锁 ⊥ `_fail_ledger_lock`；metrics 永远最内层）+ 热点开销
- [x] 错误处理含 kind 映射与降级路径；防重复计数口径明确
- [x] 测试要点 **39 条**（SA-T1..T39；v1.1 新增 T25..T29；★ v1.3 新增 T35..T39）映射 PRD AC；AC 追溯矩阵覆盖 A3/A4/A6/A7/A9/A10/E2/E5/E6/S1/S4/S6/S7/S10
- [x] 与基础层对齐：`cache_policy`/`FetchError`/`build_batch_response`/`metrics.incr,set_gauge` 全部按**现行**基础层契约使用（逐项见 §1.4；版本见头部「基础层接口权威」——★ v1.4：原写「基础层 v1.1」，按「引用时点约定」改为不绑版本号，内容以被引文档头部为准）
- [x] **v1.1**：§1.3/§1.4/§2.1#3/§5.9 对 `cdp_engine.page_data` 的口径一致（REV-DES-10 无矛盾）
- [x] **v1.1**：`cdp_unavailable` 4 处出口统一计数（REV-DES-12）；`_fetch_rest_json` 解码失败/非 dict 就地计数（REV-DES-13/14）
- [x] **v1.1**：BR-SA-24/§6.2/§9 的 ≤15s 引据改为 **AC-E2**（REV-DES-17）；`_BATCH_BUDGET_CDP` 裁决回执入 §10#10（REV-DES-21）
- [x] **v1.1**：§10 新增 #14（预算耗尽早冷却账，登记）、#15（f10 `page_data=None` = `cdp_unavailable`）、#16（`cdp_engine` 依赖）；登记项①-⑦ 裁决回执齐备
- [x] **v1.2（P7b）**：`_LOCAL_BUDGET` 哨兵（§2.3/§3.1b/BR-SA-34/SA-T25/SA-T30）取代 REV-DES-15 现口径；`_call_fetcher` 仅调用帧降级（§2.3/BR-SA-21/SA-T31）
- [x] **v1.2（P7b）**：`_prefetch_advance(name, visited, …)` 访问即推进（§2.7/§2.8/BR-SA-35）；账本 5s 限频 + O(1) 淘汰（§2.5/§3.1/BR-SA-8/9/12b/SA-T32）
- [x] **v1.2（P7b）**：`_direct_fetch` REST 腿经 `fetch_json`、单次只计一次（§2.1#7-9/§5.10/BR-SA-28）；`_classify_exc`/`_urlopen_timeout` 已删（§1.3/§5.2/§6.1）
- [x] **v1.2（P7b）**：归一与按请求拼写回填（§2.6/§5.4/§5.6/BR-SA-36/SA-T33）；f10 五出口 + 限时导航锁（§2.9/§5.9/BR-SA-37/SA-T34）；`_basic_sector_*`（§2.7b/§5.15）；`_fetch_rest_json` 期限透传、无前置闸门（§5.2）
- [x] **v1.3**：`depth` 域 `fetch_cls_stock_depth`/`_depth_store`（§2.1#7/§3.3/§3.5/§5.9/BR-SA-26/SA-T35）；`fetch_cls_basic_info` 三阶段 + 空壳防御（§2.1#4/§5.9/SA-T36）；`upstream_secu_code` 全量应用（§1.3/§2.1/§5.9/§5.10/SA-T37）；`refresh_epoch` 贯通（§2.2/§2.3/§4.2 BR-SA-38/§5.2/§5.5/§5.6/§5.7/§5.8/SA-T38）；`BATCH_MAX_WORKERS=20`（§3.4/§5.1/SA-T39）
- [x] **v1.4（溯源收口 + 引用时点约定）**：头部上游 **SAD v1.3 → v1.12 / PRD v0.3 → v0.10**；基础层接口权威 **config v1.1 → v1.6 / cache v1.1 → v1.14 / metrics v1.1 → v1.8**（指向现行版本）；「按基础层 v1.1 契约使用」改为不绑版本号（依「引用时点约定」，接口权威栏为快照、**落后一版不属漂移**，内容以被引文档头部为准）。**代码 / 契约 / BR / 测试编号 / 偏差零变更**；**未改代码 / SAD / PRD / API.md / README.md / `.opencode`**
- [x] **v1.6（PRF-MEM-01 内存收缩同步）**：§3.3/§3.5 `quote`/`fundflow`/`timeline` 的 `pool_max`/`cache_max` 同步 `config.md` v1.8（**1000/1000、1000/1000、500/500**）；**BR-SA-13 改写**为"池上限按域独立配置"（`'dedup'` 与 `'fixed:N'` 并存）并补收缩理由/内存影响；**顺带更正 §3.5 `quote.ttl` 遗留值 `8|120`→`4|120`**（v1.4 升 L0）；§10#27 登记；`_FAIL_LEDGER_MAX`（5×`MAX_DEDUP_CODES`=10000）不受影响；**无接口 / 对外契约变更**；**未改代码 / SAD / PRD / API.md / README.md / `.opencode`**
- [x] **v1.7（PRF-MEM-01 修复轮同步 · CR-02 / CR-04 / CR-06）**：§3.3/§3.5 pool 口径改为「经 **`'env:MAX_QUOTE_POOL'`/`'env:MAX_FUNDFLOW_POOL'`/`'env:MAX_TIMELINE_POOL'`** 派生（默认 **1000/1000/500**，可免改码调参）」，`cache_max` 仍为 `config` 矩阵整数字面量（**内存硬界**）；**BR-SA-13 扩充**——**CR-04 降级说明**（`cache_max` 首次 < 活跃码上界 2000 ⇒ 本模块严格 LRU 淘汰 + 消费方 `stream._last_known` 结转，**功能不破坏**、仅命中率下降）+ **`depth` 保持 `'dedup'` 的理由**（**无 prefetch 循环**、池仅 `code→ts` 账本、`cache_max=500` 才是内存界）+ **prefetch 间隔事实更正**（= `pool_refresh` = `ttl × refresh_factor`）+ `~0.65GiB` 标注**估算待实测**；§9/§10#27/§12 补登记；**本模块代码零改动 / 无接口·对外契约·BR 编号·测试编号变更**；**未改代码 / SAD / PRD / API.md / README.md / `.opencode`**
- [x] **v1.8（PRF-MEM-01 实测回填）**：**BR-SA-13** / **§10#27** 的乐观预测按五档压测实测（run **20260920-110805**）更正——python RSS **1.095GiB → 1.012GiB（−83MiB）**、容器 **1.449GiB(96.57%) → 1.41GiB(93.98%)** ⇒ **本次收缩未达成内存目标**；补「**终端缓存非内存大头**」更正（真正大头 = 共享 URL 缓存 `MAX_CACHE_SIZE=2000` + 分配器碎片）；旁证 3 域缓存精确生效 + `cache_hit_ratio` 0.1585→0.1796；tier1000 `timeline` 退化**标注"待复测归因，尚非结论"**。**本模块代码零改动 / 无行为·接口·对外契约·BR 编号·测试编号变更**；**未改代码 / 测试 / SAD / PRD / API.md / README.md / `.opencode`**
- [x] **v1.9（归因纠偏 + PRF-MEM-02 arena 治理实测）**：**BR-SA-13** / **§10#27** 的 URL 缓存归因按实测更正——共享 URL 缓存存**解码后原始响应文本（`str`）**（`cache.py:851-852` → `_cache_put`；`json.loads` 在调用方命中后解析），总量仅**几十 MB**、**非大头**（v1.8 的"解析后 Python 对象/真大头"表述**已被证伪**）；**真因 = glibc arena**（33 线程 × 默认最多 `8×ncores` 个 64MB arena，`RssAnon` 占 98%、`VmLib`/`RssFile` 仅 14.5MB）。A/B 实测（run 20260920-113125，基线 20260920-110805）`MALLOC_ARENA_MAX=2` ⇒ python VmRSS 1.008GiB → 0.772GiB、VmSize 8.96GB → 1.15GB、容器 1.41GiB(93.98%) → 1.259GiB(83.95%)；累计链路 1.095GiB → 1.012GiB → 0.772GiB（容器 1.449 → 1.41 → 1.259GiB），剩余 = 终端缓存解析对象（~200MB）+ 运行时/分配器残余；tier1000 `ok_rate` 回升**标注单次观测、勿写成结论**。**本模块代码零改动 / 无行为·接口·对外契约·BR 编号·测试编号变更**；**未改代码 / 测试 / SAD / PRD / API.md / README.md / `.opencode`；`config.md` → v1.11、`_PROGRESS.md` 同步**
- [x] **v1.10（P8-r1 P1/P2 收尾）**：**BR-SA-13** / **§3.3** 的 `'env:<NAME>'` 措辞更正——由"调用期 `globals()`（可热替换）"改为**导入期冻结的注册映射** `_POOL_MAX_ENVS`（键=唯一合法 NAME、值=冻结池上限、**名单与取值同源**；`config.md` v1.12 §2.7/§3.1/§3.3/BR-CFG-4）；`cache_policy` **不读可变模块全局**（BR-CFG-10），运行期重绑定 `config.MAX_*_POOL` 不再生效；未注册/未定义 NAME **一律 `ValueError`**（不再 `KeyError`）。**补 pool/cache 独立上限（P1-2）设计取舍**：`pool_max`（prefetch 轮转覆盖）≠ `cache_max`（内存界），**不设 `pool_max ≤ cache_max` 护栏**（`depth`/`f10`/`announcement` 现状即 2000 > 500，只造成回源轮转浪费、非正确性问题）。**本模块代码零改动 / 无行为·接口·对外契约·BR 编号·测试编号变更**（仅消费 `policy['pool_max']`/`policy['cache_max']`）；**本轮只改文档**；**未改 SAD / PRD / API.md / README.md / `.opencode`；`config.md` → v1.12、`_PROGRESS.md` 同步**

---

## 12. 变更记录

| 版本 | 日期 | 说明 |
|------|------|------|
| v1.0 | 2026-09-15 | 首版（批次 2 数据层） |
| v1.1 | 2026-09-15 | 按 `doc/review/数据层三模块_详细设计评审_专家版.md`（REV-DES-20260915-002）修订：**P1 REV-DES-10**（§1.3 允许 `cdp_engine(page_data)` + §1.4 补登记 + §1.3 依赖图）；**P2** REV-DES-12/13/14/15/16/17/18/21；登记项①-⑦ 裁决回执；引据恒 AC-E2 |
| v1.2 | 2026-09-16 | **P7b 契约同步（以 `stock_api.py` 实现为准）**：`_LOCAL_BUDGET` 哨兵（取代 REV-DES-15 裁决②）·`_call_fetcher` 仅调用帧降级·`_prefetch_advance(name, visited, …)` 访问即推进·账本 5s 限频 + O(1) 淘汰·`_direct_fetch` REST 腿经 `fetch_json`（单计一次）并删 `_classify_exc`/`_urlopen_timeout`·`_fetch_rest_json` 期限透传无前置闸门·归一键与请求拼写回填·f10 五出口 + 限时导航锁·`_basic_sector_*` 新增。新增 BR-SA-34..37、SA-T30..T34、§10#17..20。**未改代码** |
| v1.3 | 2026-09-17 | **P7b 契约同步（以 `stock_api.py` 实现为准 · depth 域 + 三阶段 basic_info + refresh_epoch）**：`fetch_cls_stock_depth`/`_depth_store`/`_DEPTH_VALUE_FIELDS`/`_DOMAIN_STORES['depth']`·`fetch_cls_basic_info` 扩三阶段 + `_basic_info_is_valid` 空壳防御·`upstream_secu_code` 全量应用于 x-quote URL·`BATCH_MAX_WORKERS` 8→20·`refresh_epoch` 全链路贯通 + 终点缓存 `written >= epoch`·`cached_batch` 域枚举扩 `depth`。新增 BR-SA-38·SA-T35..T39·§10#21..26·§12 本行。**未改代码** |
| v1.4 | 2026-09-18 | **溯源收口 + 引用时点约定（只改文档）**：头部上游 **SAD v1.3 → v1.12 / PRD v0.3 → v0.10**；基础层接口权威 **config v1.1 → v1.6 / cache v1.1 → v1.14 / metrics v1.1 → v1.8**（指向现行版本）；新增「引用时点约定」——接口权威栏 = 本文最后同步时点快照，**落后一版不属漂移**，内容以被引文档头部为准。**无 BR 语义变更 / 无对外契约变更**；**未改代码 / SAD / PRD / API.md / README.md / `.opencode`** |
| v1.5 | 2026-09-18 | **台账收口：`REV-DES-21` 裁定关闭（无实现变更、无契约变更）**：用户裁定 `/stock/f10` **极少/几乎无调用** ⇒ **不实现**「仅单码 / 少量码」上限（**不构成问题**）；**§10#10 加裁定注并保留「当前未强制」事实陈述**（知情接受、**非遗漏**）+ 残留风险/触发条件（如将来被大量调用 ⇒ 按「参数错误 ⇒ 400 + PRD AC + 详设 + 测试」整链补）。**无 BR 语义变更 / 无对外契约变更 / 无接口变更 / 无编号新增**；**未改代码 / SAD / PRD / API.md / README.md / `.opencode`** |
| v1.6 | 2026-09-20 | **内存调优 PRF-MEM-01 契约同步（以 `config.py` 实现为准 · 只改文档）**：`config.md` v1.8 将 `quote`/`fundflow`/`timeline` 的 `pool_max`/`cache_max` **同源收缩**（`'dedup',2000 → 'fixed:1000',1000` / `'fixed:1000',1000` / `'fixed:500',500`）。本模块 §3.3/§3.5/§11 同步；**BR-SA-13 改写**为"池上限按域独立配置"（`depth`/`announcement`/`f10` 仍 `'dedup'`=2000）并补收缩理由（内存高水位 96.57% ⇒ 预期 RSS ~1.1GiB→~0.65GiB）；顺带更正 §3.5 `quote.ttl` 遗留值 `8|120`→`4|120`；§10#27 登记。**无接口 / 对外契约变更**；**未改代码 / SAD / PRD / API.md / README.md / `.opencode`** |
| v1.7 | 2026-09-20 | **PRF-MEM-01 修复轮同步（以 `config.py` 实现为准 · 只改文档）**：`config.md` **v1.9** 把 3 域 `pool_max` 的 spec 由 `'fixed:N'` 改为 **`'env:MAX_QUOTE_POOL'` / `'env:MAX_FUNDFLOW_POOL'` / `'env:MAX_TIMELINE_POOL'`**（默认值不变 **1000/1000/500**；白名单 `_POOL_MAX_ENVS` + **调用期**解析；`cache_max` 仍为矩阵字面量 = 内存硬界）。本模块 §3.3/§3.5 pool 口径改为"经 `'env:MAX_*_POOL'` 派生"；**BR-SA-13 扩充**——**CR-04**（`cache_max` 首次 < 活跃码上界 2000 ⇒ 「终端缓存覆盖活跃全集」不再成立；降级 = `_cache_store` 严格 LRU 淘汰 + 消费方 `stream._last_known` 结转，**功能不破坏**）+ **CR-06**（`depth` 池保持 `'dedup'` 的理由：**无 prefetch 循环**、池仅 `code→ts` 账本、`cache_max=500` 才是内存界）+ **prefetch 间隔事实更正**（= `pool_refresh` = `ttl × refresh_factor`；原"120s 轮询"为误述）+ `~0.65GiB` 标注**估算待实测复核**；§9/§10#27/§11 同步。**本模块代码零改动 / 无接口·对外契约·BR 编号·测试编号变更**；**未改代码 / SAD / PRD / API.md / README.md / `.opencode`** |
| v1.8 | 2026-09-20 | **PRF-MEM-01 实测回填（只改文档）**：重建部署 + 五档压测实测（run **20260920-110805**）**证伪**此前乐观预测——python RSS **1.095GiB → 1.012GiB（净收益仅 ~83MiB）**、容器 **1.449GiB(96.57%) → 1.41GiB(93.98%)** ⇒ **本次收缩未达成内存目标**。**BR-SA-13 / §10#27** 按实测更正，并补「**终端缓存非内存大头**」（真正大头 = 未收缩的共享 URL 缓存 `cache.MAX_CACHE_SIZE=2000` + 分配器碎片）；旁证 3 域缓存精确生效（healthz `?check=0`：1000/1000、500/500、depth 500）+ `cache_hit_ratio` 0.1585→0.1796；tier1000 `timeline` `ok_rate` 100%→89.6% / `upstream_timeout` 123→317 **待复测归因，尚非结论**。**本模块代码零改动 / 无行为·接口·对外契约·BR 编号·测试编号变更**；**未改代码 / 测试 / SAD / PRD / API.md / README.md / `.opencode`** |
| v1.9 | 2026-09-20 | **归因纠偏 + PRF-MEM-02 arena 治理实测（只改文档）**：**更正 v1.8 的 URL 缓存归因（该归因已被证伪）**——共享 URL 缓存存的是**解码后的原始响应文本（`str`）**（`cache.py:851-852` `resp.read().decode(...)` → `_cache_put`；`json.loads` 在调用方命中后解析），**非**解析对象，总量仅**几十 MB**、**非内存大头**；**真因 = glibc arena**（33 线程 × 默认最多 `8×ncores` 个 64MB arena，`RssAnon` 占 98%、`VmLib`/`RssFile` 仅 14.5MB）。**A/B 实测（run 20260920-113125，基线 20260920-110805）**：`MALLOC_ARENA_MAX=2` ⇒ python VmRSS 1,057,324kB(1.008GiB) → 809,328kB(0.772GiB)、`RssAnon` 1,042,748kB → 794,776kB、VmSize 8.96GB → 1.15GB、匿名 rw-p 300 → 166、容器 1.41GiB(93.98%) → 1.259GiB(83.95%)。**累计链路**：python RSS 1.095GiB → 1.012GiB(−83MiB) → 0.772GiB(−248MiB)；容器 1.449 → 1.41 → 1.259GiB；剩余 = 终端缓存解析对象（~200MB）+ 运行时/分配器残余。**BR-SA-13 / §10#27 / §11** 同步更正；tier1000 `ok_rate` 回升**标注单次观测、勿写成结论**。**本模块代码零改动 / 无行为·接口·对外契约·BR 编号·测试编号变更**；**未改代码 / 测试 / SAD / PRD / API.md / README.md / `.opencode`；`config.md` → v1.11、`_PROGRESS.md` 同步** |
| v1.10 | 2026-09-20 | **P8-r1 P1/P2 收尾（只改文档）**：`'env:<NAME>'` 语义更正——由"调用期 `globals()` 解析（v1.9 措辞，声称可热替换）"改为**导入期冻结的注册映射** `_POOL_MAX_ENVS`（键=唯一合法 NAME、值=冻结池上限、**名单与取值同源**；`config.md` **v1.12** §2.7/§3.1/§3.3/BR-CFG-4）；`cache_policy` **不读可变模块全局**（BR-CFG-10），运行期重绑定 `config.MAX_*_POOL` 不再生效；未注册/未定义 NAME **一律 `ValueError`**（不再 `KeyError`）。**补 pool/cache 独立上限（P1-2）设计取舍**——`pool_max`（prefetch 轮转覆盖）与 `cache_max`（终端缓存内存界）是两个独立上限，**不设 `pool_max ≤ cache_max` 护栏**（`depth`/`f10`/`announcement` 现状即 2000 > 500，只造成回源轮转浪费、非正确性问题；3 个收缩域当前相等是取值巧合）。**BR-SA-13 / §3.3 / §10#27 / §11** 同步；**本模块代码零改动 / 无行为·接口·对外契约·BR 编号·测试编号变更**（`config`/数据层测试 hermetic 化、用例 **517 → 518**）；**未改代码 / 测试 / SAD / PRD / API.md / README.md / `.opencode`；`config.md` → v1.12、`_PROGRESS.md` 同步** |
