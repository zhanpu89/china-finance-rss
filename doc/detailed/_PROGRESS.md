# task-decomposer 进度（P6c 优化专项 · 详设分解 + P7b 契约同步）

> 会话范围：SAD v1.2 → 模块详设。本文件是**跨 dispatch 断点续传**状态（由 task-decomposer 读写）。
> 编排器上下文见 `_MEMORY_CACHE.md`（本 agent 只读）。

## 当前状态

- ★ **未决项单点入口**：仍开放的未决项（A/B/C/D 四类）已集中登记于下方「**★ 未决项（后续处理 · 单点入口）**」——该节是"仍开放项"的**唯一入口**，各详设 §10 / SAD / PRD 内的登记仅为该条详细上下文，**两者冲突时以该节"状态"为准**。
- 批次 1：**基础层三模块**（config / cache / metrics）→ ✅ 完成（均 v1.1）
- 批次 2：**数据层三模块**（stock_api / market_api / cdp_engine）→ ✅ 完成（均 **v1.1**，已按评审修订）
- 批次 3：**上层两模块**（server / stream）→ ✅ 评审闭环（v1.1）→ ✅ P7b 契约同步（v1.2）→ ✅ v1.3 收尾（`server.md` N1 回退）
- **本次（r5 容量/冷启动契约同步）**：把多轮实现的真实行为**以代码为准**回写 `stream.md`（→ **v1.3**）/ `stock_api.md`（→ **v1.3**）/ `server.md`（→ **v1.4**）（+ 本文件）——**未改代码、未改 SAD/PRD/其他详设**
- **本次（最终收口）**：把「规则文档 ⏳ 待生成」改为 **N/A（项目声明）**（编码规范/项目规则**不在 `doc/detailed/`**，权威落 `.opencode/rules/*.md` + 根 `AGENTS.md`，由 `.opencode/project/manifest.json → doc_profile.detailed.rule_docs = []` 声明；门禁 `check-detailed.sh` 打印显式 N/A 提示、不计问题）；并把历次登记的**编排层跨模块同步项**（`API.md` / `README.md` / SAD / PRD 回填）标记为 **✅ 已由编排层完成**——**只改本文件**；详见顶部「★ 最终收口」。
- **本次（过时措辞更正 + 事实对齐）**：清掉 `doc/detailed/` 中**已过时**的「待编排层批准/同步」措辞（`server.md` → **v1.15** / `stream.md` → **v1.4**），并按**本轮核实结果**把本台账收口（`feeds[].status`、stream 建组 400、margin 400、4 面板 `max-age`、`_fail_ledger`/本地预算；REV-DES-10/11/20/21）——**未改代码、未改 SAD/PRD/API.md/README.md/`.opencode`**；详见「★ 最终收口」§3。
- **本次（事实性数值更正 + 溯源更正 · 2026-09-18）**：`server.md` → **v1.16**（4 面板 `max-age` 旧值 **`8/120` → 现行 `4/120`**（`quote` 于 v1.4 升 L0）；**全文件扫描后共 8 处同类更正** = **`8/120` 字面 6 处** + `L1` 档位误标 1 处 + 面板旧兜底值 `300` 1 处）+ 上游 **SAD v1.11 → v1.12**；`stream.md` → **v1.5**（头部溯源更正：SAD v1.12 / PRD v0.9 / config v1.5 / metrics v1.7）；`metrics.md` → **v1.7**（§3.2 owner 列补 `market_api` · **REV-DES-20 闭环**）；`market_api.md` → **v1.5**（`:411`「同步权归编排层」→ ✅ 已同步——**注**：该文件实际已是 **v1.4**（传输层批次，本台账原记 v1.3 未同步），故本轮顺延为 v1.5）。**只改文档；未改代码 / SAD / PRD / API.md / README.md / `.opencode`。** 详见下方「★ 本轮事实性数值更正 + 溯源更正」。
- **本次（最终溯源 / 台账收口 · 2026-09-18）**：`market_api.md` → **v1.6**（头部溯源 SAD **v1.3 → v1.12** / PRD **v0.3 → v0.10**；接口权威栏 config **v1.1 → v1.5** / cache **v1.1 → v1.13** / metrics **v1.1 → v1.7**）、`metrics.md` → **v1.8** / `config.md` → **v1.6** / `cache.md` → **v1.14**（三份头部上游 **SAD v1.11 → v1.12 / PRD v0.9 → v0.10**）——**均「溯源更正，无内容 / BR / 契约变更」**。**只改文档；未改代码 / `doc/arch/` / `doc/prd/` / `API.md` / `README.md` / `.opencode`。** 详见下方「★ 最终溯源收口」。
- 版本（**历史行 · 2026-09-18 早批快照；现行权威见顶部「★ 全量溯源收口 + 引用时点约定」§4；本行所列 `config v1.5 / cache v1.13 / metrics v1.7 / market_api v1.5 / cdp_engine v1.2` 均已过时，其中 `cdp_engine v1.2` 系笔误**）：`config.md` = **v1.5**（★ 溯源已更正为 **SAD v1.11 / PRD v0.9** — **✅ 待办闭环**）· `cache.md` = **v1.13**（★ P3a → P3a-r1 → P7b 回填 D-3 → **P8 F1/F5** → **P8 F8** → **P2-1 fail-safe 收口 + 溯源 PRD v0.8** → **读侧 fail-safe 补全（缺 `xml` ⇒ miss）+ `acquire` 先判空实现约束 + T-CACHE-36** → **最后一轮契约收口（`''` 边界写死 + 残缺降级 `log.warning` 去重 BR-CACHE-36 + §10#29/#30 边界登记）** → **实现事实对齐（`_feed_degraded_warned`/`_warn_feed_degraded_once` 写入 BR-CACHE-36、按原因去重；§10#30 改「已防御」三处 `isinstance` 守卫；溯源 SAD v1.11/PRD v0.9）**）· `server.md` = **v1.16**（★ v1.16 事实性数值更正 + 溯源更正：4 面板 `max-age` 旧值 `8/120` → 现行 4/120（`quote` 于 v1.4 升 L0；全文件扫描 6 处 `8/120` + 2 处同类共 **8 处**）；上游 SAD v1.11 → v1.12；接口权威 `metrics.md` → v1.7 / `market_api.md` → v1.5——**无 BR 语义变更**；★ v1.15 过时措辞更正 + 事实对齐：`feeds[].status` 同步落点 `API.md:499-511`，L24/§2.9.1/BR-SRV-22/§9/§10#7 收口——**无 BR/契约变更**；★ P3a → P3a-r1 → P3a-r2 → P7b 回填 D-1/D-2 → **P8 F1–F7** → **P8 F8** → **P2-1 措辞收口 + 溯源 SAD v1.9/PRD v0.8** → **F8 并发变体 `SRV-T73` + `acquire` 实现约束** → **最后一轮契约收口（`SRV-T73` 证伪面收窄 + 超时余量/线程结束断言）** → **实现事实对齐（`SRV-T73` 15s 余量 + `is_alive` 落地；溯源 SAD v1.11/PRD v0.9）**）· `stream.md` = **v1.5**（★ v1.5 头部溯源更正：SAD v1.12 / PRD v0.9 / config v1.5 / metrics v1.7；★ v1.4 建组 400 面同步落点 `API.md:541`/`:529` 措辞更正）· `stock_api.md` = **v1.3** · `market_api.md` = **v1.5**（★ v1.5 REV-DES-20 owner 收口；原记 v1.3 系 v1.4 传输层批次未登记，本轮据文件实际 v1.4 顺延） · `metrics.md` = **v1.7**（★ v1.7 §3.2 owner 列补 `market_api`（REV-DES-20 闭环）；★ P8 F3 + **F8 自检/溯源修正** + **v1.6 溯源 SAD v1.11/PRD v0.9**）· `cdp_engine.md` = **v1.2**
- ★ **本批后版本（2026-09-18 · ★ 已被顶部「★ 全量溯源收口 + 引用时点约定」§1/§4 取代，现行以该节为准）**：`config.md` = **v1.6** · `cache.md` = **v1.14** · `metrics.md` = **v1.8** · `market_api.md` = **v1.6**；未动者 `server.md` = v1.16 · `stream.md` = v1.5 · `stock_api.md` = v1.3 · `cdp_engine.md` = **v1.3**（★ 台账上文原记 v1.2 系**笔误**，实测头部为 **v1.3**——见「★ 最终溯源收口」冲突 ①）。溯源：授权范围内已统一为 **SAD v1.12 / PRD v0.10**；`stock_api.md` / `cdp_engine.md` 头部仍为 **SAD v1.3 / PRD v0.3**（**未授权、仍滞后**，见同节「范围外残留」）；`server.md` / `stream.md` 上游 `SAD v1.12` 已对、但 **PRD 仍写 v0.9**（未授权，见同节冲突 ④）。
- 路径：纯后端（无前端/小程序 → Step 4 跳过）
- 门禁：每份含 9 节（职责/契约/数据结构/业务规则/伪代码/错误处理/并发安全/测试要点/AC 追溯）+ 偏差标注 + 自检；§3 为 yaml 代码块
- **本次（全量溯源收口 + 引用时点约定 · 2026-09-18 · 最后一批）**：把 `doc/detailed/` **全部跨文档版本引用**一次性收口——`stock_api.md` → **v1.4**（上游 **SAD v1.3 → v1.12 / PRD v0.3 → v0.10**；基础层接口权威 **config v1.1 → v1.6 / cache v1.1 → v1.14 / metrics v1.1 → v1.8**）、`cdp_engine.md` → **v1.4**（上游 **SAD v1.3 → v1.12 / PRD v0.3 → v0.10**；接口权威 **config v1.1 → v1.6 / metrics v1.1 → v1.8**）、`market_api.md` → **v1.7**（接口权威 config v1.5 → v1.6 / cache v1.13 → v1.14 / metrics v1.7 → v1.8）、`stream.md` → **v1.6**（上游 **PRD v0.9 → v0.10**；接口权威 config v1.5 → v1.6 / metrics v1.7 → v1.8）、`server.md` → **v1.17**（上游 **PRD v0.9 → v0.10**；接口权威 config v1.6 / cache v1.14 / metrics v1.8 / stock_api v1.3 / market_api v1.6 / **cdp_engine v1.3**）、`config.md` → **v1.7** / `cache.md` → **v1.15** / `metrics.md` → **v1.9**（上游 SAD v1.12 / PRD v0.10 复核确认）。**新增「引用时点约定」**（含接口权威栏的文件头部 + 本文件 §2）：接口权威栏 = **本文最后同步时点快照**、**落后一版不属漂移**，内容以被引文档头部为准、该栏仅用于定位。**均「溯源收口 + 引用时点约定」，无 BR 语义变更、无对外契约变更**；**未改代码 / `doc/arch/` / `doc/prd/` / `API.md` / `README.md` / `.opencode`。** 详见下方「★ 全量溯源收口 + 引用时点约定」。
- **本次（台账收口：`REV-DES-21` 裁定关闭 · 2026-09-18）**：`stock_api.md` → **v1.5**（§10#10 加裁定注 + §12 变更行）；本文件同步。**用户裁定：`/stock/f10` 极少/几乎无调用 ⇒ `REV-DES-21` 缓解项「✅ 已裁定：不实现」——不再设「仅单码 / 少量码」上限，不再是待办**（「当前未强制」**保留为事实陈述 = 知情接受，非遗漏**）。**只改文档；未改代码 / `doc/arch/` / `doc/prd/` / `API.md` / `README.md` / `.opencode`。** 详见下方「★ 台账收口：REV-DES-21 裁定关闭」。
- **本次（归因纠偏 + PRF-MEM-02 arena 治理实测 · 2026-09-20 · 只改文档）**：`config.md` → **v1.11** / `stock_api.md` → **v1.9**（+ 本文件）。**纠偏**：上一轮「共享 URL 缓存存解析后 Python 对象、体积数倍于原始 JSON、是 1GB 大头」**已被证伪**——实测缓存存的是**解码后的原始响应文本（`str`）**（`cache.py:851-852` `resp.read().decode(...)` → `cache.py:862` `_cache_put(cache, url, data)`；`json.loads` 在调用方命中后解析），按条数与体积估算总量仅**几十 MB**、**非内存大头**。**真因 + A/B 实测**（run **20260920-113125**，基线 **20260920-110805**）：`MALLOC_ARENA_MAX=2` ⇒ python VmRSS **1,057,324kB(1.008GiB) → 809,328kB(0.772GiB)**、RssAnon **1,042,748kB → 794,776kB**、VmSize **8.96GB → 1.15GB**、匿名 rw-p **300 → 166**、容器 **1.41GiB(93.98%) → 1.259GiB(83.95%)**；机制 = 33 线程 × 默认最多 `8×ncores` 个 64MB glibc arena ⇒ 碎片/不归还（`VmLib`/`RssFile` 仅 14.5MB、`RssAnon` 占 98%）。**累计链路**：python RSS **1.095GiB（收缩前）→ 1.012GiB（3 域缓存收缩 −83MiB）→ 0.772GiB（+arena −248MiB）**；容器 **1.449 → 1.41 → 1.259GiB**；仍未达 ~0.65GiB 级，剩余 = 终端缓存解析对象（~200MB）+ 运行时/分配器残余。tier1000 `timeline` `ok_rate` 89.6% → **100%** 为**单次观测、可能含上游波动，勿写成结论**。落点：`config.md` 头部/§3.2 注/§10#24/§10.1（重写）/§11；`stock_api.md` 头部/§4.3(BR-SA-13)/§10#27/§11/§12；本文件。**只改 `doc/detailed/`；未改代码 / 测试 / `doc/arch/` / `doc/prd/` / `API.md` / `README.md` / `.opencode`。** 详见下方「★ 归因纠偏 + PRF-MEM-02 arena 治理实测」。
- **本次（内存调优 PRF-MEM-01 **实测回填与结论更正** · 2026-09-20 · 只改文档）**：`config.md` → **v1.10** / `stock_api.md` → **v1.8**（+ 本文件）。背景：PRF-MEM-01 已**重建部署 + 五档压测实测**（run **20260920-110805**），**证伪**此前乐观预测——收缩前容器稳态 **1.449GiB/1.5GiB（96.57%）**、python RSS **1.095GiB**；收缩后容器 **1.41GiB/1.5GiB（93.98%）**、python RSS **1.012GiB** ⇒ **净收益仅 ~83MiB，本次收缩未达成内存目标**。**归因更正**：实测反推（`timeline` 1350→500 省 ~82MB + `quote`/`fundflow` 各 −1000 条省 ~10MB ≈ 92MB，与 −83MiB 吻合）⇒ **终端缓存只是小头**；**真正大头 = 未收缩的共享 URL 缓存**（`cache.py:35 MAX_CACHE_SIZE=2000`；实测 `cache_entries.url=2000` 顶满；条目 `{'data': 解析后 Python 对象}` 体积数倍于原始 JSON），其次为线程池 glibc arena 碎片。**旁证**：3 域缓存精确生效（healthz `/healthz?check=0`：`quote`/`fundflow` `pool_max`/`cache_max` = 1000/1000、`timeline` = 500/500、`depth` = 500）；`cache_hit_ratio` **0.1585 → 0.1796**；tier1000 `timeline` `ok_rate` 100% → **89.6%**、`upstream_timeout` 123 → **317**（⚠️ **待复测归因，尚非结论**，不写成结论）。**后续方向**：调优**共享 URL 缓存**（`cache.MAX_CACHE_SIZE` / 条目表示），而非继续收缩终端缓存。落点：`config.md` 头部/§3.2 注/§10#24 + 新增 **§10.1「实测结论」**/§11；`stock_api.md` 头部/§4.3(BR-SA-13)/§10#27/§11/§12；本文件。**只改 `doc/detailed/`；未改代码 / 测试 / `doc/arch/` / `doc/prd/` / `API.md` / `README.md` / `.opencode`。** 详见下方「★ PRF-MEM-01 实测回填与结论更正」。
- **本次（内存调优 PRF-MEM-01 · **修复轮**契约同步 · 2026-09-20 · 只改文档）**：`config.md` → **v1.9** / `stock_api.md` → **v1.7**（+ 本文件）。修复首轮 3 个问题（代码已落地、**517 用例全绿**）：**CR-02（关键）**——3 域 `pool_max` 由矩阵字面量 `'fixed:1000'`/`'fixed:1000'`/`'fixed:500'` 改为 **env 可调**：新增 spec 形 **`'env:<NAME>'`**（`_resolve_pool_max` 经白名单 `_POOL_MAX_ENVS = frozenset({'MAX_QUOTE_POOL','MAX_FUNDFLOW_POOL','MAX_TIMELINE_POOL'})` 在**调用期**解析为模块常量；未知 `NAME` ⇒ `ValueError('bad pool_max env name: ...')`）+ 新增 3 个 env 注册常量 **`MAX_QUOTE_POOL=1000` / `MAX_FUNDFLOW_POOL=1000` / `MAX_TIMELINE_POOL=500`**（`config.py` 顶层，紧邻 `MAX_DEDUP_CODES` 区域；**默认值 = 收缩值 ⇒ 行为不变、部署可免改码调参**）；矩阵三行改 `'env:MAX_QUOTE_POOL'`/`'env:MAX_FUNDFLOW_POOL'`/`'env:MAX_TIMELINE_POOL'`；**`cache_max`（1000/1000/500）仍为矩阵内整数字面量**（内存硬界，与其余 9 域一致）；`depth` 保持 `'dedup'`/500。**CR-03**——新增 `test_prf_mem_01_pool_cache_contract`（CFG-T19）+ `test_prf_mem_01_pool_cap_follows_env`（CR-02，热替换 `MAX_TIMELINE_POOL=400`）；**CR-04**——新增 `test_prf_mem_01_cache_degrade_is_lru_bounded`（锁 `cache_max` < 活跃码上界 2000 的**优雅 LRU 有界降级**）⇒ 用例总数 **514 → 517**。**CR-05**——更正 prefetch 间隔事实（= `pool_refresh` = `ttl × refresh_factor`：quote/depth 盘中 **4s**、fundflow/timeline **8s**、非盘 **120s**；原"120s 轮询"为误）+ `~0.65GiB` 标注**估算待实测**。**CR-06**——`depth` 池保持 `'dedup'` 的理由写入文档（**无 prefetch 循环**、池仅 `code→ts` 账本、`cache_max` 才是内存界）。落点：`config.md` 头部/§1.1#5/§2.4/§2.7/§3.1/§3.2/§3.3/§5/§6/§8(CFG-T19)/§10#24/§11；`stock_api.md` 头部/§3.3/§3.5/§4.3(BR-SA-13)/§9/§10#27/§11/§12；本文件。**只改文档；未改代码 / `doc/arch/`（SAD 已由 system-architect 于 **v1.15** 承接本修复轮）/ `doc/prd/` / `API.md` / `README.md` / `.opencode`。** 详见下方「★ PRF-MEM-01 修复轮契约同步」。
- **本次（内存调优 PRF-MEM-01 **首轮**契约同步 · 2026-09-20 · 只改文档）**：`config.md` → **v1.8** / `stock_api.md` → **v1.6**（+ 本文件）。`DOMAIN_MATRIX` **3 域** 的 `pool_max`/`cache_max` **同源收缩**——`quote` `'dedup',2000 → 'fixed:1000',1000`、`fundflow` `'dedup',2000 → 'fixed:1000',1000`、`timeline` `'dedup',2000 → 'fixed:500',500`（`depth`/`announcement`/`f10` 仍 `'dedup'`=`MAX_DEDUP_CODES`=2000；`plate`/`feed`/`margin`/`sector` 不变）。**背景（PRF-MEM-01）**：压测显示容器内存 **96.57%** 高水位；归因 = 终端缓存被灌满至 `cache_max` + `timeline` 单条 ~96KB（内存大户）+ prefetch（`pool_refresh` 120s 轮询）保活使 LRU 不淘汰 ⇒ **同源收缩**使保活范围收敛，预期 python 稳态 **RSS ~1.1GiB→~0.65GiB**。落点：`config.md` §3.1/§3.2/§2.4/§8(CFG-T19)/§9/§10#24；`stock_api.md` §3.3/§3.5/BR-SA-13/§9/§10#27/§12；**顺带更正 `stock_api.md §3.5` 的 `quote.ttl` 遗留值 `8|120`→`4|120`**（`quote` 于 v1.4 升 L0）。**只改文档；未改代码 / `doc/arch/`（SAD §2.1/§4.3/AR-8 数值由 system-architect 回填）/ `doc/prd/` / `API.md` / `README.md` / `.opencode`。** 详见下方「★ 内存调优 PRF-MEM-01 契约同步」。

- **本次（P8-r1 P1/P2 收尾 · 2026-09-20 · 只改文档）**：`config.md` → **v1.12** / `stock_api.md` → **v1.10**（+ 本文件）。**`'env:<NAME>'` 语义由"调用期 `globals()`（可热替换）"更正为导入期冻结的注册映射 `_POOL_MAX_ENVS`**（**键=唯一合法 NAME、值=冻结池上限、名单与取值同源**）；`cache_policy` **不读可变模块全局**（BR-CFG-10），运行期重绑定 `config.MAX_*_POOL` 不再改变 `['pool_max']`；未注册/未定义 NAME **一律 `ValueError`**（不再 `KeyError`）。**测试 hermetic 化 + 重复用例去重（代码/测试已落地、518 用例全绿）**：`test_prf_mem_01_pool_cache_contract` 改字面量锁定 + 结构性 spec 断言、删热替换用例，新增 `_pool_caps_are_frozen_at_import`（BR-CFG-10）/ `_bad_env_spec_fails_fast`（P2-1）；`tests/test_data_layer.py` 删除与 `test_cache_true_lru_eviction` 重复的用例、新增 `test_prf_mem_01_evicted_code_reads_as_miss_not_stale`（被 LRU 淘汰码**读为 miss 并回源**）⇒ 用例 **517 → 518**。**pool 与 cache 独立上限（P1-2）**：不设 `pool_max ≤ cache_max` 护栏（`depth`/`f10`/`announcement` 现状即 2000 > 500，只造成回源轮转浪费、非正确性问题）。落点：`config.md` 头部/§1.1#5/§2.3/§2.7/§3.1/§3.2/§3.3/§5/§6/BR-CFG-4/§8(CFG-T9/CFG-T19)/§10#24/§10.1/§11；`stock_api.md` 头部/§3.3/§4.3(BR-SA-13)/§10#27/§11/§12；本文件。**只改 `doc/detailed/`；未改代码 / 测试（修复已落地）/ `doc/arch/` / `doc/prd/` / `API.md` / `README.md` / `.opencode`。** 详见下方「★ P8-r1 P1/P2 收尾」。

- **本次（P8-r2 收尾（注册表不可变 + int 归一 + 措辞如实） · 2026-09-20 · 只改文档）**：`config.md` → **v1.13**（+ 本文件；`stock_api.md` 仅 §10#27 补一行、**版本保持 v1.10**）。**① 注册表不可变（P1-1）**——`_POOL_MAX_ENVS` 由普通可变 `dict` 改为 **`MappingProxyType({...})`**（`from types import MappingProxyType`）⇒ **改键 / 改值 / 新增键一律 `TypeError`**（v1.12 的"导入期冻结"此前只冻结值，映射本身仍可被就地改）。**② `int()` 归一恢复（P1-3）**——`_resolve_pool_max` 的 `'env:'` 分支恢复 `return int(_POOL_MAX_ENVS[name])`（防注册值类型漂移；当前合法 int 输出逐字不变）。**③ 措辞如实收窄（P1-4）**——删去"`cache_policy` 完全不依赖可变模块全局"的**过宽**断言（`'dedup'` 分支**仍取**导入期常量 `MAX_DEDUP_CODES`）与"避免被 `_prefetch_loop` 的 `except` 静默吞掉"这一**不成立**陈述（`_prefetch_loop` **不调用** `_resolve_pool_max`）；**真实收益 = 与 `cache_policy` 的 `KeyError(domain)` 契约解耦**。**④ 测试（518 → 519 · 代码/测试已落地）**——`test_env_defaults`（CFG-T9）补 3 个 `MAX_*_POOL` 默认值；新增 `test_prf_mem_01_env_registry_is_immutable`（CFG-T19，改写值 / 新增键均 `TypeError`）；`test_prf_mem_01_evicted_code_reads_as_miss_not_stale` 改从**真实** `config.cache_policy('quote')` 派生并断言 `policy['cache_max'] < config.MAX_DEDUP_CODES`（**回退 `cache_max` 即红**）。**⑤ 保留不改（已登记为设计取舍）**——**不设** `pool_max ≤ cache_max` 护栏；**不在 unittest 中断言进程 RSS**（内存属实测/运维口径）。落点：`config.md` 头部/§1.1#5/§2.3/§2.7/§3.1/§3.3/§5/§6/BR-CFG-4/§8(CFG-T9/CFG-T19；**518 → 519**)/§10#24/§10.1(新增第 8 节)/§11；`stock_api.md` §10#27 补记一行（**版本保持 v1.10**）；本文件。**只改 `doc/detailed/`；未改代码 / 测试（修复已落地）/ `doc/arch/` / `doc/prd/` / `API.md` / `README.md` / `.opencode`。**

- **本次（PRF-LAT-02 margin 终端缓存契约同步 · 2026-09-20 · 只改文档）**：`config.md` → **v1.14** / `market_api.md` → **v1.8** / `metrics.md` → **v1.10**（+ 本文件）。**代码已落地、525 用例全绿**。① `config.py`：`DOMAIN_MATRIX['margin']` 的 `cache_max` 由 `'n/a'` → **`8`**（margin 自本轮起有**终端缓存**，上限 8 = 4 market × 2 余量；`pool_max` 仍 `'fixed:16'`、margin **不用池**）；矩阵上方「仅经共享 URL 缓存取数、`cache_max='n/a'`」清单由 `plate / news_url / longhu / margin` **收窄为 `plate / news_url / longhu`**（margin 移出）。② `market_api.py`：新增模块内终端缓存 `_margin_cache`(OrderedDict)/`_margin_cache_ts`/`_margin_cache_lock`；`fetch_margin(market)` 新流程 = 参数校验 + `deadline` 入口闸 → **终端缓存命中直接返回**（LRU `move_to_end`，不解析、不计数）→ 未命中才 `metrics.incr('upstream_fetch_total', key='margin')` + `fetch_json`/`json.loads`/`_transform_margin` → **仅当 `latest is not None`** 才写缓存并按 `cache_max`(8) LRU 淘汰（同步删 ts）；失败/空数据不写。③ `upstream_fetch_total{margin}` 语义由"每次 handler 调用 +1" → **"仅终端缓存 miss 时 +1"**（与 stock 域对齐）。④ 测试 **519 → 525**（margin 命中不取数 / TTL 过期重取 / LRU 有界 / 失败不缓存 / 空数据不缓存 / 计数仅 miss）。落点：`config.md` 头部/§2.4/§3.1/§3.2/BR-CFG-5/CFG-T13/§9/§10#15+新增 **§10#25**/§11；`market_api.md` 头部/§1.1–1.4/§2.1/§3.3+新增 **§3.4**/BR-MKT-9 改写+新增 **BR-MKT-13..16**/§5/§6/§7/§8（MKT-T7/T13 更正 + **MKT-T14..T19**）/§9/§10#4·#10·#11/§11/§12/接口权威栏；`metrics.md` 头部/§3.2+表后注/§10#15/§11。**只改 `doc/detailed/`；未改代码 / 测试 / SAD / PRD / API.md / README.md / `.opencode`。** 详见下方「★ PRF-LAT-02 margin 终端缓存契约同步」。

- **本次（PRF-LAT-02 P2 收尾（CR-02）· 2026-09-20 · 只改文档）**：`market_api.md` → **v1.9** / `metrics.md` → **v1.11**（+ 本文件）。**代码 / 测试已落地、526 用例全绿**。① `market_api.py`：margin 终端缓存 `_margin_cache` 的**命中路径与写入/淘汰路径**均新增**锁外**发布 `metrics.set_gauge('cache_entries', len(_margin_cache), key='margin')`（`entries` 锁内取、发布锁外；对齐 `stock_api._cache_store` BR-SA-16/26 与 `cache._publish_url_stats` BR-CACHE-24 的「锁内取标量、锁外发布」纪律）；模块 docstring 把过时的 "fetching goes through ``cache.fetch_json`` only" 改为如实表述（`fetch_json` 仍是**唯一 HTTP 出口**，但 TTL 新鲜的终端缓存命中不再调用它）。② 测试：新增 `tests/test_data_layer.py::test_terminal_cache_publishes_cache_entries_gauge`（写后 `cache_entries{margin} == 1`、命中后仍 == 1、LRU 淘汰后 == `cache_max`）⇒ 用例 **525 → 526**。落点：`market_api.md` 头部 + **v1.9 变更块** + §1.4/§2.1 注/§3.4 + **新增 BR-MKT-17**（+ BR-MKT-13/15 交叉引用）+ §5/§7/§8（MKT-T13/T14 补 + **MKT-T20**）/§9/§10#12/§11/§12/接口权威栏；`metrics.md` 头部 + **v1.11 变更块** + §3.2（`cache_entries` 标签枚举**补 `margin`**）+ §10#16 + §11。**只改 `doc/detailed/`；未改代码 / 测试 / SAD / PRD / API.md / README.md / `.opencode`。**

## ★ 未决项（后续处理 · 单点入口）

> **本清单是"仍开放项"的唯一入口**；各详设 §10 / SAD / PRD 内的登记为该条的**详细上下文**，两者冲突时**以本清单的"状态"为准**。
> 登记日期 2026-09-18（集中登记轮）· **只改本文件**：未改代码 / 其他详设 / `doc/arch/` / `doc/prd/` / `API.md` / `README.md` / `.opencode/`；只增不删、不改历史变更块。
> **追加登记（2026-09-20 · 内存 / 延迟 / 权限专项遗留轮）**：本轮新增 **A-8**、**B-5–B-9**、**C-4 / C-5**，并把 **A-2** 标 **✅ 已闭环**（AC-E4 吞吐 5/5 PASS）——同样**只改本文件**（未改代码 / 测试 / 其他详设 / `doc/arch/` / `doc/prd/` / `API.md` / `README.md` / `.opencode/`）；只增不删、不改历史变更块。
> 状态图例：⬜ 开放 · ✅ 已闭环 / 已裁定 / 已防御。

### A 类 · 需实测或交易时段（清理动作对它们无效）

| 标识 | 类型 | 为什么还没做（阻塞原因） | 触发 / 前置条件 | 承接地 | 建议承接方 |
|------|------|------------------------|------------------|--------|-----------|
| **A-1** ⬜ | 验收实测（AC-S3 模式 B 分档 P95） | 绝对分位数只能在**真实故障注入**下采集；解析式仅证明"高密度 ≤5s / 低密度 ≤10s"稳态可达 | 探测阶梯封顶 5s + `NEG_TTL=5s` 不变；**高/低密度分两轮采集、不得合并**（合并会被高密度样本覆盖） | PRD AC-S3 / SAD §2.3 D-1·§4.1·AR-9·AR-13·Q6 / `cache.md` BR-CACHE-22·§10#11 | tester（故障注入）+ 编排层校准 |
| **A-2** ✅ | 验收压测（AC-E4 吞吐） | **✅ 已闭环（2026-09-20 实测，5/5 PASS）**——原口径（PRD `doc/prd/perf-stability-optimization.md:81`，**未改文本**）：≥100 req/s × 5min、错误率 0、后 3min P99 相对前 2min 基线劣化 ≤20%；实测吞吐 **200.0 req/s**、错误 **0 / 300000**、劣化比 **0.253 / 0.863 / 1.089 / 0.507 / 0.413**（最大 1.089 ≤ 1.2）；`cache_hit_ratio` 0.976–0.994、`http_503_total`=0、容器 RSS 528–558MiB。报告：`doc/tester/AC-E4_吞吐验证报告.md`（首轮）+ `doc/tester/AC-E4_尖峰因果与判据稳定性.md`（本轮）；harness：`tests/ac_e4_verify.py`、`tests/ac_e4_sweep_causality.py`、`tests/ac_e4_diag.py` | 压测环境；同期采集 `cache_hit_ratio` 观测项 | PRD AC-E4 / SAD §4.2·§8 E4·Q1 | tester（压测）+ 编排层 |
| **A-3** ⬜ | 设计目标实测（**非 AC**） | `cache_hit_ratio ≥90%` 是 SAD 内部设计目标 / `/healthz` 观测项，待 P6c 实测 | 实测；**仅当 <84%** 才走 PRD 修订（不得以解析式越权改 PRD） | SAD §4.2·§2.6·AR-2·Q1 / `metrics.md` §10#2 | tester + 编排层 |
| **A-4** ⬜ | 实测校准 | "慢而未死（需 6–10s）"上游频度 ↔ `_HISTORY_AGE=600s` 老化窗口相对占比未知；该窗口决定此类上游恢复延迟上界（≈600s） | 真实上游样本 / P6c 校准；`_PROBE_BUDGET_CAP`/`_HISTORY_AGE` 变动须连带重标 AC-S3 | SAD §2.3 D-1·§4.1·AR-9·AR-13 / PRD AC-S3 | tester + 编排层 |
| **A-5** ⬜ | 运维变更动作 | 默认值下 CI 已覆盖；**一旦 env 覆盖即属运维变更、须重跑校准**（非当前待办） | 运维覆盖 `NEG_TTL` / `PROBE_TIMEOUT>5` / `_HISTORY_AGE`（<~120s）任一项时 | `config.md` §2.3 / `cache.md` §10#11·#18 / SAD AR-13 | 运维 + tester（重跑） |
| **A-6** ⬜ | 验收实测（盘内终验） | PRD v0.6 已标"需在下一个交易时段补采"：AC-E10「盘中 4s 档端到端刷新周期」仅盘后 120s 等价条件直采；AC-A11/A12「交易时段连续多拍」仅单次/单窗口采样 | 下一个交易时段 | PRD §9.1 v0.6「追加待终验」·AC-E10 / AC-A11 / AC-A12 / SAD §8 | tester（盘中补采） |
| **A-7** ⬜ | 运维决策 | 部署侧是否**强制设 `PUBLIC_BASE_URL`**（可选运营缓解：设后 feed 键恒为 5 条 path，消除 Host 派生键空间与本地生成放大）——README / 详设已给建议，未决策 | 部署决策；与 F8 引用计数修复不互斥（缓解非契约） | `server.md` BR-SRV-50 备注 / `README.md` §6.1·环境变量表 / SAD §2.7·§9.10 | 运维 + 编排层 |
| **A-8** ⬜ | 验收实测（残余尖峰归因 · 3 个 60s 周期候选） | 本轮已**否证** `cache._CACHE_SWEEP_INTERVAL` / `_sweep_expired`（周期跟随实验 + 直接计时 p99=0.424ms + 放大上界 ≤0.167% + 阳性对照）；残余候选：① `HTTP_POOL_IDLE_TTL=60`（连接回收导致重连尾延迟）② `cdp_engine._heartbeat_interval()` 非交易时段=60s（15 个 CDP 页心跳）③ `stream.py` 分组清扫 60s（本轮 AC 未激活） | 需可注入 / 可观测的探针（**注意：编排层无通用执行权限，须由 tester 执行**） | `cache.md` §10 / `cdp_engine.md` / `stream.md` §10 | tester（注入计时）+ 编排层 |

### B 类 · 已登记为 §10 的改进建议（非漂移、非缺陷；做不做取决于价值判断）

| 标识 | 类型 | 为什么还没做（阻塞原因） | 触发 / 前置条件 | 承接地 | 建议承接方 |
|------|------|------------------------|------------------|--------|-----------|
| **B-1** ⬜ | 改进建议（归属上收） | longhu 的 URL/headers 现为 `server.py` 模块级常量；上收 `config` 须与 `config.md` 同 change-set，否则跨文档返工 | 决定上收时 | `server.md` §10#1 / `config.md` §2.4 | system-architect + task-decomposer |
| **B-2** ⬜ | 契约面扩大（需单独决策） | `/healthz` 的 `feeds[]` 共 15 条，**未含** `/finance/timeline`、`/market/timeline`、`/ths/longhu`、`/stock/announcement`；补入属"只增"但会扩大 `feeds[]` 契约面（不做则该 4 端点在 `/healthz` 不可见） | 决定是否扩大契约面时 | `server.md` §10#6 / SAD §7.1 Q2·§2.6 | 编排层决策 + system-architect |
| **B-3** ✅ | ~~改进建议~~ **已闭环** | SAD 侧已回填，**非仍开放** | — | SAD §2.6 计分板**已列** `upstream_fetch_total{domain}`（"D-6 补列"；SAD §9.3 记录该动作；`tech-stack.json` `architectureRules.metrics` 同步含该名） | 无（无需再处理；`metrics.md §10#5` 的"建议"文字为该条登记时点快照） |
| **B-4** ⬜ | 判据细分建议 | `stream_slow_client_total` 现为「写路径异常退出 ∧ 队列非满」的上界估计（正常断开也走异常分支）；是否进一步区分 `BrokenPipe` 与 `socket.timeout` 待确认 | 决定是否细化指标时 | `stream.md` §10#4 / BR-STR-35 / SAD §2.5 C-3 | 编排层确认 + task-decomposer |
| **B-5** ⬜ | 改进建议（标签枚举漂移） | `metrics.md` §3.2 `cache_entries` 标签枚举**缺 `depth`**（`stock_api._cache_store` 实际以 `key='depth'` 发布）；**疑似多列 `longhu`**（全仓代码未见 `key='longhu'` 写入，且 `longhu` 属 URL-cache-only 域） | 复核后补 `depth`、裁定 `longhu` 去留 | `metrics.md` §3.2 / `stock_api.md` | task-decomposer |
| **B-6** ⬜ | 评审 P2 收尾（PRF-LAT-02） | **CR-07**：`tests/test_data_layer.py::test_terminal_cache_publishes_cache_entries_gauge` 的**命中分支断言不可证伪**（删掉命中路径的 `set_gauge` 后仍绿），建议在写入与命中之间注入 / 置脏长度使其必红；**CR-01**：margin 终端缓存命中返回**共享可变 payload 对象**（潜在污染；当前唯生产链只 `json.dumps`，无触发者，与 `stock_api` 同先例）；**CR-06**：终端缓存原语第 3 处重复（`stock_api` 多域 + `market_api` margin），**当前不宜上收 `cache.py`**（层隔离），登记为技术债 | 决定收尾时（CR-06 仅登记、不实施） | `market_api.md` §10 / `tests/` | code-developer + code-reviewer |
| **B-7** ⬜ | 已知容量边界（AC-E2 合成高并发尾延迟） | `/stock/timeline` 在合成 tier1000（20 并发 × 50 码）实测 avg **12.1s** / max **24.6s**，超 AC-E2「单请求 ≤15s」。归因：**上游 / CPU 绑定**（单码 ~96KB JSON 解析），**非连接池**（`HTTP_POOL_MAX_PER_HOST` 24→48 无改善）。候选：① 降 `_MAX_BATCH_SIZE` 换取更短单请求 ② 为 timeline 设并发上限 ③ 登记为**已知容量边界**（合成极端负载） | 编排层决策后（选 ①② 需改码） | `stock_api.md` §10 / PRD AC-E2 / SAD §4.2 | 编排层决策 + code-developer（若选 ①②） |
| **B-8** ⬜ | 判据定义澄清（PRD 级，**未改文本**） | AC-E4 判据窗口：5 次实测中 **4/5 次 A(前 2min) > B(后 3min)**，A 窗口波动 3.8×（6.60–25.15ms vs B 6.32–8.66ms）——A 覆盖冷启动瞬态，判据实际在度量「瞬态有多重」，**瞬态越轻越易 FAIL**（首轮唯一 FAIL 即 A「异常干净」）。建议：基线后移至 `[60,180]`、或 ≥3 次取中位数、或改用 5s 分桶 P99 中位数；**不建议降阈值** | 需 PRD 修订（**编排层不得代改**） | PRD §7 / §9 + `doc/prd/perf-stability-optimization.md:81` | **prd-writer + review-expert** |
| **B-9** ⬜ | 权限治理待办（**需用户执行**） | `doc/deploy/permission-proposals.md` 的 **PROPOSAL-02**（把 `.opencode/scripts/*.sh` 两条通配收窄为 22 条逐文件白名单，堵「写脚本 + 通配执行」逃逸面）状态 `open`，待用户应用；同批可选：删除 `bash .opencode/project/scripts/*.sh *`（惰性通配，该目录当前不存在）；`self-evolve` 白名单含同类通配（需另行提案） | 用户在 `opencode.json` 应用（**仅用户可改**） | `doc/deploy/permission-proposals.md` / `opencode.json` | 用户 |

### C 类 · 已裁定不做 / 已知边界（**留痕：后续审计勿再作为未闭环上报**）

| 标识 | 类型 | 结论 / 依据 | 说明（**勿再作为未闭环上报**） | 承接地 |
|------|------|------------|------------------------------|--------|
| **C-1** | **已裁定：不实现** | 用户裁定 2026-09-18：`/stock/f10` 极少/几乎无调用 ⇒ 不设「仅单码/少量码」上限、不构成问题 | ✅ **已裁定不做**。`stock_api.md §10#10` 保留「当前未强制」为**事实陈述**（知情接受，非遗漏）；触发条件（若将来被大量调用）见该条裁定注 | `stock_api.md` §10#10 / 本文件「★ 台账收口：`REV-DES-21` 裁定关闭」 |
| **C-2** | **已知边界（当前不可达）** | `cache.md` §10#29：`expires_at` 缺省 `0` 依赖非负时钟（`time.time() >= 0` 恒真） | ✅ **已知边界**。仅测试把时钟打桩为**负值**时才可能反转为命中并触发 `KeyError`；全仓测试时钟起点均为正 ⇒ 当前不可达 | `cache.md` §10#29 |
| **C-3** | **已防御** | `cache.md` §10#30：真值非映射条目的读侧行为已由 `isinstance(..., dict)` 守卫防御（三处落点：`feed_cache_get_entry` / `feed_cache_put` 继承分支 / 共享 `_sweep_expired`） | ✅ **已防御**（v1.13 状态更正；原"登记不修"口径作废） | `cache.md` §10#30 / BR-CACHE-13 |
| **C-4** ✅ | **已裁定：不实现** | 用户裁定 2026-09-20：**内存不再削缓存换空间**——不削 `timeline` 终端缓存（500）与共享 URL 缓存（`MAX_CACHE_SIZE=2000`）容量；**已知可再降空间**（终端缓存解析对象 ~200MB，timeline 单条对象数倍于原始 ~96KB）**保留不动**（换取命中率）。依据：内存已从 python **1.095GiB → 0.772GiB**、容器 **96.57% → 83.95%**；分配器层三次 A/B 确认地板（`MALLOC_ARENA_MAX=1` 仅 −22MiB 且有噪声；`PYTHONMALLOC=malloc` 零收益 + ok_rate 76.1% 已证伪） | ✅ **已裁定不做**。留痕：**勿再作为未闭环上报** | `config.md` §10#24 / `stock_api.md` §10#27 / `cache.md`（`MAX_CACHE_SIZE`） |
| **C-5** ✅ | **已裁定：设计取舍** | P8-r1 遗留 **P1-2 / P1-4** 判为设计取舍：① 不设 `pool_max ≤ cache_max` 强制护栏（依据：`depth` / `f10` / `announcement` 现状即 2000 > 500，超出仅致 prefetch 回转浪费、非正确性问题）② 不在 unittest 中断言进程 RSS（内存护栏由压测脚本 + SAD AR-18 承担） | ✅ **已裁定不做**。留痕：**勿再作为未闭环上报** | `config.md` §10.1 / SAD AR-18 |

### D 类 · 本轮核实新发现的仍开放项（任务书未列，补入以便统一收口）

| 标识 | 类型 | 为什么还没做（阻塞原因） | 触发 / 前置条件 | 承接地 | 建议承接方 |
|------|------|------------------------|------------------|--------|-----------|
| **D-1** ⬜ | 契约同步（**两份台账冲突**） | SAD §9.12 二-1 / §7.1 N4 判：`API.md` 对 RSS 条件请求的**三项**（`http_304_total` 观测名 / feed 条目**四→六字段形态变更** / HTTP/1.0 304 EOF 说明）**无显式落点 = 部分未闭环**；而本文件「★ 最终收口」§2 记 `http_304_total` 已由 `API.md:507` 的"snapshot 恒定发布全部注册名"覆盖 ⇒ **口径冲突** | 以 `API.md` 实际内容复核后裁决 | SAD §9.12 二-1·§7.1 N4 / 本文件「★ 最终收口」§2 / `API.md` | 编排层 |
| **D-2** ⬜ | 测试落地（SAD §8 ⚠️） | SAD §8 覆盖声明把 **A3**（条件 C1 不成立时降级）与 **A8**（TTL 口径同步，Q3）列为 ⚠️「待落地」；而本文件 §B 曾记 AC-A3/A8"详设侧以注入 `now`/打桩的确定性用例覆盖（非待实测登记项）" ⇒ **口径待统一** | 确认确定性用例是否已构成闭环；若否补测试 | SAD §8（A3/A8）·§2.1 INV-1b / PRD AC-A3·§9.1 v0.6 | 编排层 + tester |
| **D-3** ⬜ | 契约同步（变更日志登记） | SAD §9.12 二-6 / §9.13 三-1：Q2 契约同步、S4 状态、AC 落号对齐、SAD 溯源收口 + 引用时点约定等**变更日志登记**未完成 | 编排层登记变更日志时 | SAD §9.12 二-6 · §9.13 三-1 | 编排层 |
| **D-4** ⬜ | 待裁决（PRD 既有漂移） | PRD §7.2 三条 CDP 标注漂移（`/stock/data`、`/stock/basic_info`、`/stock/f10`）标"待编排层裁决"。**注**：**疑已闭环**——SAD §7.1 Q2 已裁决（B/B/A′）并同步 `API.md:499-511`，请复核后关闭 | 复核 §7.2 后关闭 | PRD §7.2 / SAD §7.1 Q2 / `API.md:499-511` | 编排层复核 |
| **D-5** ⬜ | 待用户裁决 | PRD §5 待确认项 #5（**盘中是否跳过 CDP 守护重启**）标"待编排层决策"，未见闭环记录 | 编排层/用户决定时 | PRD §5 #5 / §9.1 v0.6「未处理项」 | 编排层 + 用户 |

## ★ 台账收口：`REV-DES-21` 裁定关闭（2026-09-18 · 只改文档）

> 范围：**只改** `doc/detailed/{_PROGRESS,stock_api}.md`。**未改代码 / `doc/arch/` / `doc/prd/` / `API.md` / `README.md` / `.opencode`**；**只增不删编号**；**未回改任何历史变更块**。

### 1. 裁定（用户 · 2026-09-18）

- **结论：`REV-DES-21` 缓解项 = ✅ 已裁定：不实现。**
- **裁定原意**：`/stock/f10` **极少调用甚至基本上不会有请求调用** ⇒ **不设「仅单码 / 少量码」上限**，**不构成问题**。
- **理由（暴露面）**：该端点实际调用面 ≈ 零 ⇒ "未强制上限"**无实际风险敞口**；为其新增 400 语义 + AC + 详设 + 测试属**过度设计**。
- **不再是待办**：本项自本日关闭。后续审计**不得**再以「`REV-DES-21` 未闭环 / 待用户决策 / 仍开放」上报或翻出。
- **历史登记行保留（不回改）**：下方「v1.1 修订摘要（REV-DES-20260915-002）」表中 `REV-DES-21` 行、及「本批 v1.1 引出的『编排层同步项』」第 6 条，均为**该时点历史记录**（原文保留、不改）；其状态**已由本节取代**——即 `REV-DES-21` = **✅ 不实现、不再待办**。

### 2. 残留风险与触发条件（**知情接受，非遗漏**）

> **现状的"未强制"是知情接受，不是遗漏。** `stock_api.md §10#10` 的「**当前未强制**」为**事实陈述、原样保留**。

- **触发条件**：**若将来 `/stock/f10` 被大量调用**（拒绝服务面被实际打开）⇒ 须按「**参数错误 ⇒ 400 + PRD AC + 详设 + 测试**」**整链**补上限（`stock_api` 多码可达 60s 的既有登记仍真实存在，届时**另立 change-set**）。
- **未触发时的口径**：不新增 400、不新增 AC、不改详设、不改测试——**保持现状**。

### 3. 逐处落点（`旧 → 新`）

| 文件 | 位置 | 旧 | 新 |
|------|------|----|----|
| `_PROGRESS.md` | 本节 + 5 处活动台账行（`:111` / `:143` / `:200` / `:221` / `:259`） | `⏳ 待用户决策` / `仍开放` | **✅ 已裁定：不实现（用户裁定 2026-09-18）** + 残留风险/触发条件 |
| `stock_api.md` | 头部版本 · §10#10 · §12 | v1.4；§10#10 仅「当前未强制」+ 建议强制 | **v1.5**；§10#10 加裁定注（**保留「当前未强制」事实陈述**）；§12 加变更行 |
| `server.md` | —（**未改**） | — | §10#6 实为**另一件事**（`feeds[]` 端点覆盖缺口），**不属 `REV-DES-21`** ⇒ **不误改、不 +版本**（详见 §4） |

### 4. ⚠️ `server.md` 未改（如实报告）

- **核对结论**：`server.md §10#6` = 「**`feeds[]` 的端点覆盖**」（现状 15 条**未含** `/finance/timeline`、`/market/timeline`、`/ths/longhu`、`/stock/announcement`，标「已知缺口、建议编排层单独决策」）——**与 `REV-DES-21`（`/stock/f10` 仅单码 / 少量码）是两件事**。
- `server.md` **全文无 `REV-DES-21` 编号登记**；仅 `:269` 有**一句交叉引用**（"f10 多码 >15s 的既有风险见 `stock_api.md` §10#10（本模块不兜）"）——属**引用**而非独立登记，**不构成同一项的登记位置**，故**不加注、不改、不 +版本**（保持 **v1.17**）。
- ⇒ **本次唯一版本变更 = `stock_api.md` v1.4 → v1.5**；`_PROGRESS.md` 无版本号。

## ★ 全量溯源收口 + 引用时点约定（最后一批 · 2026-09-18 · 只改文档）

> 范围：**只改** `doc/detailed/*.md`（8 份详设 + 本文件）。依据：`doc/arch/SAD.md` 头部 **v1.12** / `doc/prd/perf-stability-optimization.md` 头部 **v0.10**，以及各详设**头部真值**（逐份核实）。**未改代码 / `doc/arch/` / `doc/prd/` / `API.md` / `README.md` / `.opencode`**；**只增不删编号**；各详设**版本各 +1**。

### 1. 逐份「旧 → 新」（版本 + 头部上游 + 接口权威栏 + 文末「共同构成」）

| 文件 | 版本 旧 → 新 | 头部上游 旧 → 新 | 接口权威栏 旧 → 新 | 内容 |
|------|-------------|------------------|---------------------|------|
| `stock_api.md` | v1.3 → **v1.4** | SAD v1.3 → **v1.12**；PRD v0.3 → **v0.10** | config v1.1 → **v1.6**；cache v1.1 → **v1.14**；metrics v1.1 → **v1.8** | 无（溯源/约定；§11 自检「按基础层 v1.1 契约使用」→ 不绑版本号） |
| `cdp_engine.md` | v1.3 → **v1.4** | SAD v1.3 → **v1.12**；PRD v0.3 → **v0.10** | config v1.1 → **v1.6**；metrics v1.1 → **v1.8** | 无（溯源/约定） |
| `market_api.md` | v1.6 → **v1.7** | 已 v1.12 / v0.10（复核不变） | config v1.5 → **v1.6**；cache v1.13 → **v1.14**；metrics v1.7 → **v1.8** | 无（溯源/约定） |
| `stream.md` | v1.5 → **v1.6** | SAD v1.12（已对）；PRD **v0.9 → v0.10** | config v1.5 → **v1.6**；metrics v1.7 → **v1.8**；stock_api v1.3（不变）；文末 server v1.16 | 无（溯源/约定） |
| `server.md` | v1.16 → **v1.17** | SAD v1.12（已对）；PRD **v0.9 → v0.10** | config v1.5 → **v1.6**；cache v1.13 → **v1.14**；metrics v1.7 → **v1.8**；stock_api v1.3（不变）；**market_api v1.5 → v1.6**；**cdp_engine v1.2 → v1.3** | 无（溯源/约定） |
| `config.md` | v1.6 → **v1.7** | SAD v1.12 / PRD v0.10（复核不变） | —（无该栏，基础层权威文档） | 无（溯源/约定） |
| `cache.md` | v1.14 → **v1.15** | SAD v1.12 / PRD v0.10（复核不变） | —（无该栏，基础层权威文档） | 无（溯源/约定） |
| `metrics.md` | v1.8 → **v1.9** | SAD v1.12 / PRD v0.10（复核不变） | —（无该栏，基础层权威文档） | 无（溯源/约定） |

- **接口权威栏目标值说明**：按任务书「填成**上表现行值**」——即本轮**开始时**各详设头部真值（config v1.6 / cache v1.14 / metrics v1.8 / stock_api v1.3 / market_api v1.6 / cdp_engine v1.3 / stream v1.5 / server v1.16）。因各详设本批**各 +1**，该栏批次结束后**落后被引文档一版**——按任务 2 的「引用时点约定」，**这不是漂移、不计待办**。
- **未回改任何历史快照行**（各文件 vX.Y 变更块、§10 偏差行内嵌的旧版本号逐字保留）。

### 2. 引用时点约定（**终结「版本滞后」类反复上报**）

> **约定正文（已写入各含「接口权威」栏的详设头部，及本文件此处）**：
> 「接口权威」栏所列版本 = **本文最后一次同步时点的快照**；被引文档的**权威版本以其自身头部为准**。故该栏**落后一版不属漂移、无需每次追平**。**内容以被引文档为准；此栏仅用于定位。**

- 适用范围：`stock_api.md` / `cdp_engine.md` / `market_api.md` / `stream.md` / `server.md` 的「基础层(·数据层)接口权威」栏，以及 `stream.md` / `server.md` 文末「共同构成」清单。`config.md` / `cache.md` / `metrics.md` 为**基础层权威文档**，版本以各自头部为准，其变更块已声明同约定。
- **上游 SAD / PRD 不适用本约定**：其版本号仍**按实际头部填成现行值**（本轮统一为 **SAD v1.12 / PRD v0.10**）。
- **可核验性**：每条引用均保留**可定位信息**（`file:line` / 章节号 / 符号名）——快照语义**只免除版本号追平，不免除内容引用**；一旦被引内容变更，引用方仍须按各自 change-set 同步。

### 3. 溯源滞后类待办：**本轮全部关闭**

- ✅ **关闭 `stock_api.md` 头部溯源严重滞后**（原 SAD v1.3 / PRD v0.3 / config·cache·metrics v1.1）——本批更正为 SAD v1.12 / PRD v0.10 + config v1.6 / cache v1.14 / metrics v1.8。**此即上批「范围外残留」所记项。**
- ✅ **关闭 `cdp_engine.md` 头部溯源严重滞后**（原 SAD v1.3 / PRD v0.3 / config·metrics v1.1）——同上（另核实台账原记 v1.2 系笔误、头部实为 v1.3）。
- ✅ **关闭 `server.md` / `stream.md` 上游 PRD 仍写 v0.9**（→ v0.10），及其接口权威栏滞后一版的登记。
- ✅ **关闭 `market_api.md` 接口权威栏滞后**（v1.5/v1.13/v1.7 → v1.6/v1.14/v1.8）。
- ⇒ **`doc/detailed/` 全仓「溯源滞后」类待办 = 0**（含上批「范围外残留」的 `stock_api` / `cdp_engine`）。
- ⇒ **按 §2「引用时点约定」，「接口权威栏版本落后一版」自此不再计为待办**——后续审计**不得**再以该栏与头部差异上报。

### 4. 台账版本行核对（**逐份，以头部真值**）

| 文件 | 台账旧记 | **头部真值（本批开始前）** | 本批后 |
|------|---------|--------------------------|--------|
| `config.md` | v1.5（上文行）/ v1.6（「本批后版本」行） | **v1.6** | **v1.7** |
| `cache.md` | v1.13 / v1.14 | **v1.14** | **v1.15** |
| `metrics.md` | v1.7 / v1.8 | **v1.8** | **v1.9** |
| `server.md` | v1.16 | **v1.16** | **v1.17** |
| `stream.md` | v1.5 | **v1.5** | **v1.6** |
| `stock_api.md` | v1.3 | **v1.3** | **v1.4** |
| `market_api.md` | v1.5 / v1.6 | **v1.6** | **v1.7** |
| `cdp_engine.md` | **v1.2（笔误）**；后行已更正 v1.3 | **v1.3** | **v1.4** |

- ★ **台账更正**：上文「版本（以各文档头部为准，已核对）」行（2026-09-18 早批）所列 `config v1.5 / cache v1.13 / metrics v1.7 / market_api v1.5 / cdp_engine v1.2` 均为**该行时点快照**，已被「本批后版本」行与本表取代；其中 `cdp_engine` 的 **v1.2 系笔误**（头部实为 v1.3）。**历史行原文保留、不回改**；**现行权威以本表右列为准**。

### 5. 未闭环（如实保留，**不标完成**）

- 见下方「★ 最终溯源收口」§3：~~**`REV-DES-21` 缓解项**（待用户决策）~~ → **✅ 已裁定：不实现（用户裁定 2026-09-18；见顶部「★ 台账收口：`REV-DES-21` 裁定关闭」）**／**AC-S3 模式 B P95、AC-E4 吞吐、`cache_hit_ratio ≥90%`、`_HISTORY_AGE` 相对占比、env 覆盖后重跑 AC-S3**（需实测 / 交易时段）。**`REV-DES-21` 已关闭、不再是待办；其余项本批未改其状态。**

## ★ 最终溯源收口（`market_api.md` v1.6 / `metrics.md` v1.8 / `config.md` v1.6 / `cache.md` v1.14 · 2026-09-18 · 只改文档）

> 范围：**只改** `doc/detailed/{market_api,metrics,config,cache,_PROGRESS}.md`。依据：`doc/arch/SAD.md` 头部（**v1.12**，AC 总数 36）与 `doc/prd/perf-stability-optimization.md` 头部（**v0.10**）——**权威以各文档头部为准**。**未改代码 / `doc/arch/` / `doc/prd/` / `API.md` / `README.md` / `.opencode`**；**只增不删编号**。

### 1. 逐份「旧 → 新」

| 文件 | 版本 旧 → 新 | 溯源 旧 → 新 | 内容变更 |
|------|-------------|-------------|---------|
| `market_api.md` | v1.5 → **v1.6** | 上游 `SAD v1.3 → v1.12` / `PRD v0.3 → v0.10`；接口权威 `config v1.1 → v1.5` / `cache v1.1 → v1.13` / `metrics v1.1 → v1.7` | **无**（「溯源更正，无内容变更」；代码 / 契约形态 / BR / 测试编号 / 偏差零变更） |
| `metrics.md` | v1.7 → **v1.8** | 上游 `SAD v1.11 → v1.12` / `PRD v0.9 → v0.10` | **无**（注册名集合 20 / 签名 / 锁 / 快照口径 / `http_304_total` 计数点零变更） |
| `config.md` | v1.5 → **v1.6** | 上游 `SAD v1.11 → v1.12` / `PRD v0.9 → v0.10` | **无**（接口 / `DOMAIN_MATRIX` / `cache_policy` / env 注册表 / 行为零变更） |
| `cache.md` | v1.13 → **v1.14** | 上游 `SAD v1.11 → v1.12` / `PRD v0.9 → v0.10` | **无**（BR-CACHE-32..36 / 签名语义 / 锁序 / TTL·清扫·上限零变更） |

- 变更记录用词：`market_api.md` = 「**溯源更正，无内容变更**」；`metrics.md` / `config.md` / `cache.md` = 「**溯源更正（SAD v1.12 / PRD v0.10），无 BR 语义变更、无对外契约变更**」。
- **未回改任何历史快照行**（`market_api.md` 的 v1.1 行保留原文 + ★ 更正注；`cache.md` v1.5–v1.13 历史变更块逐字保留）。

### 2. 「溯源滞后」类待办：**授权范围内全部关闭**

- ✅ 关闭 **`market_api.md` 头部溯源严重滞后**（原 `:10-12` 写 SAD v1.3 / PRD v0.3 / config·cache·metrics v1.1）——本批更正为 SAD v1.12 / PRD v0.10 + config v1.5 / cache v1.13 / metrics v1.7。
- ✅ 关闭 **`metrics.md` / `config.md` / `cache.md` 头部上游仍写 `SAD v1.11` / `PRD v0.9`**——本批更正为 **v1.12 / v0.10**。
- ⇒ **`doc/detailed/` 授权范围内，溯源滞后类待办 = 0**。
- ⚠️ **范围外残留（只报告，未授权修改）**：
  - `stock_api.md`（`:8-10`）头部仍为 `SAD v1.3` / `PRD v0.3` / 接口权威 `config v1.1 · cache v1.1 · metrics v1.1`。
  - `cdp_engine.md`（`:8-10`）头部仍为 `SAD v1.3` / `PRD v0.3` / 接口权威 `config v1.1 · metrics v1.1`。
  - 二者**同属「溯源滞后」**，因本任务书**只授权 5 个文件**而未改；须**另批授权**方可收口（届时 `stock_api.md` 至少升至 SAD v1.12 / PRD v0.10 + config v1.5 / cache v1.13 / metrics v1.7；`cdp_engine.md` 同理）。**故"全仓无溯源滞后"尚不成立**——如实登记。

### 3. 未闭环（如实保留，**不标完成**）

**A. 待用户决策（行为 / 契约决策，本批不实现）**

- ✅ **`REV-DES-21` 缓解项——已裁定：不实现（用户裁定 2026-09-18；本项不再是待办）**——`server.md` 落实「`/stock/f10` 仅单码 / 少量码」约束**不再实施**：用户裁定该端点**极少调用甚至基本上不会有请求调用** ⇒ **不设上限、不构成问题**（实际暴露面 ≈ 零）。现状 `stock_api.md §10#10` **仍如实记「当前未强制」**（= **知情接受，非遗漏**），并已加裁定注 + 残留风险/触发条件（**若将来被大量调用**，须按「参数错误 ⇒ 400 + PRD AC + 详设 + 测试」整链补上限）。详见顶部「★ 台账收口：`REV-DES-21` 裁定关闭」。

**B. 需实测 / 交易时段（或用户裁决）**

| 项 | 依据 | 说明 |
|----|------|------|
| **AC-S3 模式 B 分档 P95**（高密度 ≤5s / 低密度 ≤10s） | `SAD §2.2`（AR-9 / AR-13）/ `cache.md §10#11` / `config.md §2.3`·§10#18 | 需**分两轮采集**（高 / 低密度**不得合并**，合并会被高密度样本覆盖）；需**真实故障 / 交易时段**实测。 |
| 「慢而未死」上游出现频度 ↔ `_HISTORY_AGE=600s` 相对占比 | `SAD §2.2` AR-9 | 需**实测**（决定老化窗口是否合适）。 |
| env 覆盖后**重跑 AC-S3 校准**（`NEG_TTL` / `PROBE_TIMEOUT > 5` / `_HISTORY_AGE`） | `config.md §2.3` / `cache.md §10#11`·#18 | 默认值下 CI 已覆盖；**覆盖即属运维变更、须重跑**。 |
| **AC-E4 吞吐**（可断言口径：错误率 0 + 后 3min P99 劣化 ≤20%） | `SAD §4.2` | **✅ 已压测（2026-09-18 收盘后 / 非交易时段观测）**：真实负载形态全绿（loadtest 混合 10 并发 700/700 OK · avg 60ms / max 219ms · 35 req/s；stress_all 15 并发除 `/stock/f10` 外 p95<0.4s · 内存稳定 620MiB）；极端并发（380 线程）级联饿死已定位为 `f10_batch` 60s CDP 慢尾占满公共 worker 池所致，f10 非热路径（REV-DES-21 已裁定）⇒ 场景不成立、不做工程改造。AC 口径（错误率 0 + P99 劣化）属交易时段 / 持续观测项，保留实测。 |
| `cache_hit_ratio ≥90%`（SAD 内部**设计目标**，**非 AC**） | `SAD §4.2` / Q1 | 待 **P6c 实测**；若 <84% 再走 PRD 修订。 |
| **AC-A3 / AC-A8** | `config.md` CFG-T1/T2/T4/T12 · `server.md` SRV-T11/T16/T30/T43/T69 · `cache.md` T-CACHE-32..36 | 详设侧以**注入 `now` / 打桩的确定性用例**覆盖（**非"待实测"登记项**）；如需**真实盘中**回归观测，则需**交易时段**。 |

**C. 其它（既非「溯源」也非上述两类 · 列出供你判；本轮未取证是否已闭环）**

- `server.md §10#1`（longhu 上游 URL / headers 归属）：标「**建议编排层**后续把该域常量上收 `config` 并同批改 `config.md`」——**功能性建议**（非溯源）。
- `server.md §10#6`（`feeds[]` 端点覆盖）：现状 15 条**未含** `/finance/timeline`、`/market/timeline`、`/ths/longhu`、`/stock/announcement`，标为「**已知缺口**、**建议编排层单独决策**」。
- `metrics.md §10#5`（D-6）：`upstream_fetch_total` 在 SAD §2.6 计分板**未列**，标「**建议编排层**…system-architect 回填」。
- `stream.md §10#4`（`stream_slow_client_total` 判据）：标「**建议编排层确认**是否需进一步区分 `BrokenPipe` 与 `socket.timeout`」。
- ⇒ 以上**均非本批「溯源」范围**，且不属 §3.A（行为 / 契约决策待用户裁决）/ §3.B（需实测）：**本批未改、未取证**——**请裁决是否单独立项**。

### 4. ⚠️ 冲突 / 异常（**只报告**，不自行修改范围外文档）

1. **`cdp_engine.md` 版本口径不一致**：任务书「已核实目标版本」记 **v1.2**，但**文件头部实为 v1.3**（`cdp_engine.md:3`「**版本** v1.3」，P7b 传输层批次）——按「权威以各文档头部为准」**以 v1.3 为准**；台账「版本（以各文档头部为准，已核对）」行记 v1.2 系**笔误**（本批已在「本批后版本」行更正为 v1.3，**不回改该行历史原文**）。
2. **`market_api.md`「接口权威」栏指向本批前的 config / cache / metrics 版本**：按任务书写入 `config v1.5 / cache v1.13 / metrics v1.7`（= 本模块 v1.5 契约同步时点），而**同批**把三者 +1 至 **v1.6 / v1.14 / v1.8** ⇒ 批次结束后该栏**落后一版**（与 `server.md` v1.16 引 `metrics v1.7` / `market_api v1.5`、`stream.md` v1.5 引 `config v1.5` / `metrics v1.7` **同类**——均为"引用时点 = 该文档最后同步时点"）。**是否把该栏同步到批次后版本，请指示**（本批按任务书字面执行，未擅自改写）。
3. **`SAD.md:5` 的「上游输入」仍写 `PRD v0.9`**，而 PRD 实际已 **v0.10**——属 SAD 侧内部引用滞后（`doc/arch/` **不在本批授权范围**，未改）。**建议编排层另批同步**。
4. **`server.md` / `stream.md` 头部在本批后仍未追平**：二者上游 **PRD 均仍写 `v0.9`**（实际 **v0.10**；`server.md:23` / `stream.md:11`），且接口权威栏落后一版（`server.md` 引 `metrics v1.7` / `market_api v1.5`；`stream.md` 引 `config v1.5` / `metrics v1.7`）——二者**不在本批授权范围**，未改；PRD 项与冲突 3 同类、接口项与冲突 2 **同源**。

## ★ 最终收口（规则文档 N/A 声明 + 编排层跨模块同步项闭环 · 只改本文件）

> 范围：**只改** `doc/detailed/_PROGRESS.md`（状态文件，无独立版本号）。依据：本项目约定 + 编排层同步事实（**本轮已逐一核对** `API.md` / `README.md` / `doc/arch/SAD.md` / `doc/prd/perf-stability-optimization.md` 的头部与相关小节）。**未改代码 / 其他详设 / `doc/arch/` / `doc/prd/` / `API.md` / `README.md` / `.opencode/`**；**未改任何详设的正文章节或版本号**。

### 1. 两条规则文档：`⏳ 待生成` → **N/A（项目声明）**

| # | 文档 | 状态 | 权威位置 / 声明落点 |
|---|------|------|--------------------|
| 9 | `doc/detailed/编码规范.md` | **N/A（项目声明）**——不是"待生成"，也不是"缺失" | 权威位置：`.opencode/rules/*.md`（精准定位 / 端锁定 / JSON 写入安全 / 编码纪律 / 文档对齐 / 架构思考 / 项目镜像）+ 根 `AGENTS.md`；声明落点：`.opencode/project/manifest.json → doc_profile.detailed.rule_docs = []` |
| 10 | `doc/detailed/项目规则.md` | **N/A（项目声明）**——同上 | 同 #9（规则与编码规范统一落 `.opencode/rules/` + `AGENTS.md`，**不放进 `doc/detailed/`**） |

- **门禁行为（不静默、也不计问题）**：`.opencode/scripts/check-detailed.sh` 读 `rule_docs`，为空时打印显式提示 `ℹ️ 项目规则/编码规范：项目声明为 N/A（规则位于 .opencode/rules/ + AGENTS.md，不在 doc/detailed/）`（脚本 `:112-115`），且详设收集阶段已排除这两个文件名（`:43`）⇒ **既不当缺失报错，也不计入问题**。
- **后续运行约定**：#9/#10 **不得**再被当作未完成 / 待生成工作。

### 2. 编排层跨模块同步项：**✅ 已由编排层完成**（本文件不再跟踪）

| 同步项 | 承接方 | 现状（已核对） |
|--------|--------|---------------|
| `API.md`：RSS 条件请求 `If-None-Match` / `If-Modified-Since`、弱 `ETag`、`304`（无 body / 无 `Content-Encoding`）、条件头优先级与非法头忽略→200 | 编排层 | ✅（`API.md:23-31`） |
| `API.md` / `README.md`：`<ttl>` advisory（分钟，盘中 1 / 非盘 3）+ 推荐轮询 ≥30s + 「`<ttl>` 非时效保证，需更快用 SSE」 | 编排层 | ✅（`API.md:645-649`、`README.md:30-36`） |
| `API.md`：「304 省 body 不省回源」「降级 feed 不作 304 缓存判据」 | 编排层 | ✅（`API.md:29`） |
| `README.md`：条件请求 / 304 / 轮询 ≥30s / `PUBLIC_BASE_URL` 与 per-host feed 键说明 | 编排层 | ✅（`README.md:30-36`、`:78`） |
| `/healthz.metrics` 新增 `http_304_total`（F3，"只增一个键"） | 编排层 | ✅ 已覆盖：`API.md:507` 声明"`snapshot()` 恒定发布全部注册名，未发生为 0"（无需逐键列举） |
| r5 外部面：SSE `quote.depth`（五档 21 字段）、主端口 gzip（`Accept-Encoding` 协商）、`refresh_capacity_codes`、`feeds[].status` 取值 | 编排层 | ✅（`API.md:249-292` / `:503-511` / `:537` / `:653` / `:667`；`README.md:49`） |
| SAD 回填（D-1 / F1–F8 / r5 容量与 L0·depth 等） | system-architect | ✅ **SAD v1.11**（已核对头部）：v1.8 承接 RSS 条件请求（AC-A13）、v1.9 承接 F1–F7（AC-A14）、v1.10 承接 F8（AC-S12）、v1.11 做 **AC 落号对齐**（F2 → **AC-A14**、F8 → **AC-S12**） |
| PRD 承接（AC-A13 / AC-A14 / AC-S12） | prd-writer | ✅ **PRD v0.9**（已核对头部，AC 总数 36）：AC-A14 落 v0.8、**AC-S12** 落 v0.9 |

- **AC 落号与本详设一致（已核对）**：**AC-A14**（F2，feed 缓存键覆盖表示全部维度）↔ `BR-SRV-45` / `SRV-T65`；**AC-S12**（F8，per-key 资源随并发收敛）↔ `BR-SRV-50` / `BR-CACHE-35` / `SRV-T71`·`T72`·`T-CACHE-35`。
- **本文件各处登记的历史待办**（「待编排层」/「8 项编排层待办」/「契约影响（需编排层…）」/「SAD 侧待回填」/「跨模块契约同步项」）**凡属 `API.md` / `README.md` / SAD / PRD 回填者，均已闭环**；相关段落**仅作历史记录保留**（不回改历史快照行），**本文件不再跟踪**。
- **更早批次（批次 2 等）登记、未列入上表的编排层项**：**本轮已按核实结果收口（见本文件「★ 最终收口」§3）**——已核实**完成**：REV-DES-10（`tech-stack.json` 同层边 `stock_api → cdp_engine`）、SAD §2.4（handler 返回"已组装 dict"）、SAD §2.3 D-6（`_fail_ledger` 4 元）、PRD AC-A5（`/market/margin` 表述回改），以及 `feeds[].status` / stream 建组 400 / margin 400 / 4 面板 `max-age` / `_fail_ledger`·本地预算（§3 逐条含落点）；**仍未闭环（如实保留）**：~~REV-DES-20~~ **✅ 已闭环（本批）**——`metrics.md` v1.7 §3.2 owner 列已补 `market_api`；**REV-DES-21 缓解项（`server.md` 强制 f10 仅单码/少量码）——✅ 已裁定：不实现**（用户裁定 2026-09-18：该端点**极少/几乎无调用** ⇒ **不设上限、不构成问题**）；属**行为/契约决策**，**自此不再是待办**（`stock_api.md §10#10` **保留「当前未强制」事实陈述** + 裁定注；见顶部「★ 台账收口：`REV-DES-21` 裁定关闭」）。**其余本轮未核实者，仍记为「由编排层负责，本文件不再跟踪」（不臆断其状态）。**

### 3. 本轮核实（2026-09-18 · `server.md` v1.15 / `stream.md` v1.4 · 编排层取证 `API.md` + 在跑服务）

> 编排层本轮从 `API.md` 与在跑服务逐一取证，把下方「批次 2 / r5 / P7b」台账中登记为"待编排层"的项按**核实结果**收口。**本节只登记核实结论与落点；未改代码/契约。**

| 待办（原登记） | 核实结果 | 落点（已核对） |
|---|---|---|
| `feeds[].status` 三处取值修正 + 首页 CDP 列（`server.md` §2.9.1 / BR-SRV-22 / §9 / §10#7） | **✅ 已同步** | `API.md:499-505` 列 `feeds[].status` 取值 `configured`/`ok`/`error`/`requires_chrome_cdp`（+ `items`/`error` 仅 `check=1`）；`:511` 逐条写明 `/stock/data`·`/stock/basic_info` = `configured`（纯 REST）、`/stock/f10` = `requires_chrome_cdp`（CDP 导航）——**即 §2.9.1 表的三处目标值** |
| stream 建组 `MAX_GROUPS=200` 400 / 帧预算 cap 400 / 非法 `fields` 400 | **✅ 已同步** | `API.md:541` 含 `too many groups (max 200)` 与 `subscription frames would exceed <B>-byte stream frame budget`；`:529` 含非法 `fields` ⇒ 400 |
| `/market/margin` 非法 `market` ⇒ 400 | **✅ 已同步** | `API.md` §6.5 错误处理速查 `:724`「`market` 不在枚举内」（★ 任务书记为 `:710`，系行号偏差，见下方「冲突」） |
| 4 面板 `max-age` 对外口径（旧值 `8/120` 系 `quote` 升 L0 **之前**） | **✅ 已同步**（**现行 4/120**） | `API.md` §6.1「响应头口径」表 `:619-631` + 实测行：**4 面板跟随 `quote` 域（盘中 4s / 非盘 120s），不是固定 300s**；实测 `/finance/market` → `max-age=120`、`/market/margin` → `600`、`/ths/longhu` → 无 `Cache-Control`。`quote` 于 **v1.4 升 L0**（`config.md` v1.4 / r5） |
| `_fail_ledger` / 本地预算不入冷却账 | **✅ 已闭环** | `SAD §2.3 D-6` + `§8 S6` 已写「**v1.4 实现 / v1.5 正式裁决确认**」；PRD v0.5 已正式反转（`_LOCAL_BUDGET` 不计入冷却账本） |

- **批次 2 / v1.1 评审登记、本轮一并核实（已完成）**：
  - ✅ **REV-DES-10**（SAD §3 + `tech-stack.json` 补登同层边 `stock_api → cdp_engine`）：`doc/arch/tech-stack.json` `stock_api.py` 条目 `reason` 明示"允许同层单向引用 `cdp_engine.page_data`（无环）"。
  - ✅ **SAD §2.4：handler 返回"已组装 dict"**（登记项 ④ / D-4）：`SAD §2.4` 已写"管道层（`_run_batch`/…）返回二元组，批量 handler 交 `build_batch_response` 组装为 **dict 并返回**"；`tech-stack.json:127` `namingRules.handlers` 同步。
  - ✅ **SAD §2.3 D-6：`_fail_ledger` 4 元**（登记项 ⑤）：`SAD §2.3 D-6` `[fail_count, cooldown_until, kind, last_fail_ts]` 已落。
  - ✅ **PRD AC-A5 的 `/market/margin` 表述回改**（REV-DES-11）：PRD 已将其单列为既有数据客体 `{latest, recent, _error}`（`_error` 为枚举 kind），并写入验收矩阵。
- **仍未闭环（如实保留，不臆断）**：
  - ✅ **REV-DES-20（本批闭环）**：`metrics.md` **v1.7** §3.2 的 `upstream_fail_total` owner 列**已补 `market_api`**（写入点 `market_api.py:72/78/145`）；`market_api.md` **v1.5** 同步把 §10#5/§11 待办标 ✅。
  - ✅ **REV-DES-21 缓解项——已裁定：不实现（用户裁定 2026-09-18；**本项不再开放**）**：`server.md` 落实「`/stock/f10` 仅单码/少量码」约束 **不再实施**——用户裁定该端点**极少调用甚至基本上不会有请求调用** ⇒ **不设上限、不构成问题**（实际暴露面 ≈ 零）。`server.md` **本就无该强制**；`stock_api.md §10#10` **仍如实记"当前未强制"**（= 知情接受、**非遗漏**，已加裁定注 + 残留风险/触发条件）。**性质**：属**行为/契约决策**，已由用户裁定关闭。详见顶部「★ 台账收口：`REV-DES-21` 裁定关闭」。
- **★ 冲突（只报告）**：任务书「margin 400 落 `API.md:710`」的**行号偏差**——`API.md:710` 实为 §6.5 的 `503` 行；「`market` 不在枚举内」实际在 **`API.md:724`**（§6.5 错误处理速查 `400` 行）。事实（已同步）成立，仅行号需以 `:724` 为准。

## ★ 本轮事实性数值更正 + 溯源更正（`server.md` v1.16 / `stream.md` v1.5 / `metrics.md` v1.7 / `market_api.md` v1.5 · 只改文档）

> 范围：**只改** `doc/detailed/{server,stream,metrics,market_api,_PROGRESS}.md`。依据：编排层取证（`_CACHE_AGE_DOMAINS` + `config.DOMAIN_MATRIX` + 在跑服务实测）与 REV-DES-20。**未改代码 / `doc/arch/` / `doc/prd/` / `API.md` / `README.md` / `.opencode`**；**只增不删编号**。

### 1. `server.md` v1.15 → **v1.16**：4 面板 `max-age` 旧值更正（全文件扫描 **8 处**）

| # | 位置 | 旧 → 新 |
|---|------|---------|
| 1 | §4.2 `BR-SRV-8b` | `quote`（**L1**，**8/120**）→ `quote`（**L0**，**4/120**） |
| 2 | §5.8 `/stock/*` 行 | 4 路径笼统 `L1（8 / 120）` → **拆两行**：`/stock/data`·`/stock/basic_info`（`quote` 域）= **4/120**；`/stock/fundflow`·`/stock/timeline`（L1）= 8/120 |
| 3 | §5.8 面板行 | **8 / 120** → **4 / 120** |
| 4 | §8 `SRV-T43` | `cache_policy('quote')['ttl']`（8/120）→（现行 **4/120**） |
| 5 | §10#22 | max-age **8/120** → **4/120** |
| 6 | §11#8 | `quote`（8/120）→（★ v1.16 更正：现行 **4/120**） |
| 7 | §3.3 `_CACHE_AGE_DOMAINS` 注释（`L1` 档位误标） | `（L1，**非** 300）` → `（**非** 300）；★ v1.16 更正档位：quote 于 v1.4 升 L0` |
| 8 | §8 `SRV-T16`（面板旧兜底值 `300`） | `面板 == 300（_DEFAULT_AGE_DOMAIN）` → `面板 == cache_policy('quote')['ttl']`（现行 4/120） |
| — | v1.2 变更块 ⑦（历史快照） | 原文**保留**，其后加 `★ v1.16 更正注`（不改历史块） |
| — | 头部 / 接口权威 | 上游 **SAD v1.11 → v1.12**；`metrics.md` → **v1.7**、`market_api.md` → **v1.5**、`stream.md` → **v1.5** |

- **口径**：`quote` 域自 **v1.4 升 L0** ⇒ `cache_policy('quote')['ttl']` = **盘中 4s / 非盘 120s**（实测旁证：非盘 `/finance/market` → `Cache-Control: public, max-age=120`）。其中 **`8/120` 字面 6 处**（#1–#6）+ **`L1` 误标 1 处**（#7）+ **面板旧兜底值 `300` 1 处**（#8）= **8 处**。**无 BR 语义变更**（档位本就是 L0；本次是让文字追上事实）/ **无对外契约变更**；测试仍 **75**、偏差仍 **45**。

### 2. `stream.md` v1.4 → **v1.5**：头部溯源更正

- 上游 **SAD v1.3 → v1.12 / PRD v0.3 → v0.9**；接口权威栏 **`config.md` v1.3 → v1.5 / `metrics.md` v1.2 → v1.7**、`stock_api.md` v1.3（不变）；文末「共同构成」清单同步（config v1.5 / metrics v1.7 / stock_api v1.3 / server v1.16）；`cache.md` 与本模块无接口、不列版本。**无帧契约 / 无 BR / 无测试编号变更。**

### 3. `metrics.md` v1.6 → **v1.7**：§3.2 owner 列补 `market_api`（**REV-DES-20 闭环**）

- `upstream_fail_total` owner：`cache.fetch_json / stock_api` → `cache.fetch_json / stock_api / **market_api**`（写入点 `market_api.py:72/78/145`，语义失败 `upstream_error`）。**注册名集合（20 名）/ 签名 / 锁 / 快照口径 / `http_304_total` 计数点零变更。**

### 4. `market_api.md` v1.4 → **v1.5**：`:411` 过时措辞收口（REV-DES-20）

- v1.1 历史行「`metrics.md` 同步权归编排层」**原文保留**并加 `★ v1.5 更正：✅ 已同步（本轮补登 owner）`；§10#5 / §11 待办标 ✅。**注**：任务书期望 `v1.3 → v1.4`，但文件**实际已是 v1.4**（2026-09-17 传输层批次；本台账原记 v1.3 未同步）⇒ 本轮**顺延为 v1.5**，`v1.4` 行保留不动。**本模块代码 / 契约零变更。**

### 未闭环（如实保留）

- ✅ **`REV-DES-21` 缓解项——已裁定：不实现（用户裁定 2026-09-18；本项不再待办）**（`/stock/f10` 仅单码/少量码约束）：用户裁定该端点**极少/几乎无调用** ⇒ **不设上限、不构成问题**；`stock_api.md §10#10` **保留「当前未强制」事实陈述** + 裁定注（知情接受、非遗漏）。详见顶部「★ 台账收口：`REV-DES-21` 裁定关闭」。

### ⚠️ 发现但未改（超出本任务书明确范围，只报告）

- **`market_api.md` 头部溯源严重滞后**（`:10-12` 仍写 SAD **v1.3** / PRD **v0.3** / config v1.1 / cache v1.1 / metrics v1.1）——与本轮 `stream.md` 同类问题，但任务书未授权；**建议编排层同批更正**。——**✅ 已闭环（最终溯源收口 · 2026-09-18）：`market_api.md` v1.6 头部已更正为 `SAD v1.12 / PRD v0.10` + 接口权威 `config v1.5 / cache v1.13 / metrics v1.7`。**
- **`metrics.md` / `config.md` / `cache.md` 头部上游仍写 SAD v1.11**（SAD 实际 **v1.12**；`server.md` / `stream.md` 本轮已更正）。——**✅ 已闭环（最终溯源收口 · 2026-09-18）：三份已更正为 `SAD v1.12 / PRD v0.10`（`metrics.md` v1.8 / `config.md` v1.6 / `cache.md` v1.14）。**

## ★ 最后一处文档收口（实现事实对齐 + 溯源更正 · `cache.md` v1.13 / `server.md` v1.14 / `metrics.md` v1.6 · 只改文档，不改代码）

> 范围：**只改** `doc/detailed/{cache,server,metrics,_PROGRESS}.md`。依据：code-developer 落地的实现事实（**514 用例全绿、连续 4 次无 flaky**）+ 任务书 `>>DOC_SYNC`。**未改代码 / `doc/arch/` / `doc/prd/` / API.md / README.md / `.opencode`**；**只增不删编号**。

### 1. `cache.md` v1.12 → **v1.13**（新符号写进契约 + §10#30 更正为「已防御」）

| 项 | 内容 | 落点 |
|----|------|------|
| **① 新符号写进契约** | `_feed_degraded_warned`（`set`，**按原因**去重）+ `_warn_feed_degraded_once(reason, key)`（`log.warning('[cache] feed entry degraded to miss (%s): key=%r', reason, key)`；总函数、绝不抛）；复用**既有**模块级 `log = logging.getLogger('cache')`（`cache.py:26`，**未新增 logger**） | BR-CACHE-36 实现注 / §2.4 / §5.3 |
| **② 去重口径更正** | 由「原因 + 键」→ **「原因」**：feed 键内嵌外部选定 Host（F2/F8），按键去重会被枚举刷屏；消息格式钉死为 `[cache] feed entry degraded to miss (<reason>): key=<key!r>`，`reason ∈ {'entry is not a mapping','xml is None'}` | BR-CACHE-36 / §2.4 / §5.3 |
| **③ §10#30 状态更正** | 「登记不修」→ **「已防御」**：三处 `isinstance(..., dict)` 守卫（`feed_cache_get_entry` / `feed_cache_put` 继承分支 / **共享 `_sweep_expired`**）；**③ 为必要的最小改动**——只去掉 ③ 的守卫，`feed_cache_put` 在触发①定时全扫分支仍 `AttributeError` ⇒ put 防御不成立；③ 是**共享助手**，合法路径行为逐字不变（含 URL 缓存路径） | §10#30 / §4.3 BR-CACHE-13 / §2.5 / §5.2·§5.3 |
| **④ 测试标注** | `T-CACHE-36` ④ `xml=''` 命中 + ⑤ **非映射守卫（读侧 + 写侧）**；告警去重由**独立方法** `test_t_cache_36_degraded_miss_warns_once` 覆盖（同一原因两把不同键 ⇒ 1 条、不含 "upstream"） | §8 / §9 |
| **⑤ 溯源** | **SAD v1.9 → v1.11 / PRD v0.8 → v0.9** | 头部 |

### 2. `server.md` v1.13 → **v1.14**（溯源更正 + `SRV-T73` 实现对齐）

- 头部溯源 **SAD v1.9 → v1.11 / PRD v0.8 → v0.9**；接口权威栏 `cache.md` → **v1.13**、`metrics.md` → **v1.6**。
- `SRV-T73` 实现对齐：等待放行 / `join` 实测 **15s**（≥ v1.13 建议 10s）+ `join` 后逐线程 `assertFalse(t.is_alive())`；在飞 `1 <= 两表 <= K`（K=8）且两表相等、返回后两表归零、`calls == K`。**测试计数仍 75、偏差仍 45**。

### 3. `metrics.md` v1.5 → **v1.6**（溯源更正）

- 头部溯源 **SAD v1.9 → v1.11 / PRD v0.8 → v0.9**（**末处滞后闭环**）；**函数签名 / 注册名集合（20 名）/ 锁 / 快照口径 / `http_304_total` 计数点零变更**。

### 4. 实现事实登记（本轮实测）

- **514 用例全绿、连续 4 次无 flaky**；`T-CACHE-36` ④⑤ + **告警去重用例** + `SRV-T73` **超时余量**均已落地。
- ✅ **「详设溯源滞后」待办全部关闭**：`config.md` v1.5（SAD v1.11/PRD v0.9）+ `cache.md` v1.13 + `server.md` v1.14 + `metrics.md` v1.6 **四份口径一致，无剩余溯源滞后**。
- ✅ **原「最后一轮契约收口」冲突 #1 闭环**：`cache.py` 的 `log.warning`/去重与 `isinstance` 守卫**已实现**（BR-CACHE-36 不再"契约先行"；§10#30 由"登记不修"改"已防御"）——见 `cache.md` v1.13。

### 变更记录

- `cache.md` **v1.12 → v1.13**；`server.md` **v1.13 → v1.14**；`metrics.md` **v1.5 → v1.6**。
- **无 BR 语义变更**——除 `cache.md` §10#30 由「登记不修」**更正为「已防御」**（**实现状态更正**）；**无新增编号**（BR / 测试编号均不新增）。

## ★ 最后一轮契约收口（`cache.md` v1.12 / `server.md` v1.13 · 只改文档，不改代码）

> 范围：**只改** `doc/detailed/{cache,server,_PROGRESS}.md`。依据代码评审 **`CR-RSS-20260918-005`**（`doc/review/rss-conditional-get_收尾小改_代码评审_专家版.md`，**P0=0 / P1=0 / 6×P2**）。**未改代码 / `doc/arch/` / `doc/prd/` / API.md / README.md / `.opencode`**；**只增不删编号**。

### 1. `cache.md` v1.11 → **v1.12**（`''` 边界写死 + 残缺降级可观测 + 边界登记）

| 项 | 内容 | 落点 |
|----|------|------|
| **① `''` 边界写死** | `feed_cache_get_entry` 的 miss 判据**恰好**是 `entry.get('xml') is None`（缺键或显式 `None`）；**`xml == ''` 属「合法但空」的表示 ⇒ 照常命中、照常服务**（返回 dict；`feed_cache_get` 返回 `''`）；**显式禁令**：**不得**写成 `not xml` / `if not entry.get('xml')` 真值化简——否则 `''` 判 miss ⇒ **读 miss → 回源 → 写 `''` → 再 miss 的永久回源环**（读侧无法区分"合法空表示"与"截断体"） | §2.4 / §3.1 / §4.3 BR-CACHE-32 / §5.3 |
| **② 残缺降级可观测** | 因 `xml` 缺失而"视同 miss"的分支**必须** `log.warning`（含**键**与**原因**）并**按「原因/键」去重**（防热路径刷屏）；**语义澄清**：这是**「缓存条目形态残缺」的自愈路径**（miss ⇒ 回源 ⇒ `feed_cache_put` 修复同键），**不是"上游故障"**；`feed_cache_put` 恒写 `xml` ⇒ **生产不可达**（命中即异常信号）；"空条目 / 正常过期"两分支**不打 warning** | **新增 `BR-CACHE-36`** / §2.4 / §5.3 |
| **③ 边界登记** | §10 续号 **#29**（`expires_at` 缺省 `0` 依赖 `time.time() >= 0`；负时钟才可能反转、届时直接下标 `entry['expires_at']` 才可能 `KeyError`——**当前不可达**）/ **#30**（真值非映射条目 `entry.get(...)` 抛 `AttributeError` 经 `_guard` 变降级体；生产不可达；**实现未加 `isinstance` 守卫 ⇒ 登记不修**） | `cache.md` §10 |
| **④ 测试** | `T-CACHE-36` 增 **④ `xml=''` 命中断言**（返回 dict 且 `feed_cache_get == ''`）+ **⑤ 告警可观测/去重断言** | `cache.md` §8 |

### 2. `server.md` v1.12 → **v1.13**（`SRV-T73` 证伪面收窄 + 超时余量）

| 项 | 内容 | 落点 |
|----|------|------|
| **③ 证伪面收窄** | `SRV-T73` 的取数桩**从不抛异常** ⇒ **T73 不能证伪"`release` 不在 `finally`"**（成功路径上"`with` 后裸 `release`"与"`finally release`"行为相同）——该证伪**归 `SRV-T72`**（异常路径计数归零）。**T73 证伪面收窄为「按累计增长 / 两表（`_feed_fetch_locks` 与 `_feed_fetch_refs`）不同步 / 上界 > K」**；T73 **保留「两表相等 + 在飞上界 + 归零」三条断言不变** | `SRV-T73` / §8 表后注 / §9 / §10#45 |
| **⑤ 超时余量** | 等待放行 / `join` 超时**不得过短（建议 ≥10s**；原 5s 在极端调度延迟下有**伪红**风险）**，并在 `join` 后断言线程**已结束**（`assertFalse(t.is_alive())`），把"到底谁没跑完"变成可见证据 | `SRV-T73` / §8 表后注 / §10#45 |
| **接口权威栏** | `cache.md` v1.11 → **v1.12** | §1 头部 / 文末 |

### 版本与计数

- `cache.md` **v1.11 → v1.12**：新增 **`BR-CACHE-36`**；`T-CACHE-36` 增 ④⑤（**不新增测试编号**）。
- `server.md` **v1.12 → v1.13**：`SRV-T73` **改写、不新增编号**；测试编号计数仍 **75**。

### ⚠️ 发现的契约冲突（**只报告，不自行修改其它文档**）

1. **`cache.py` 实现尚未落地 ② 的 `log.warning` 与去重**：`cache.py:944-947` 的 `xml is None` 分支当前**静默** `return None` ⇒ `BR-CACHE-36` 属**契约先行**（实现侧对齐为后续 change-set）。同理 §10#30 的 `isinstance(entry, dict)` 守卫**未加**（`cache.py:938-947` 直接 `entry.get`），故登记为"已知边界，登记不修"而非"已防御"。——**✅ 已闭环（本收口轮 2026-09-18）：实现已落地**（`_feed_degraded_warned`/`_warn_feed_degraded_once` + 三处 `isinstance` 守卫：读侧 / `feed_cache_put` 继承分支 / 共享 `_sweep_expired`）**；BR-CACHE-36 不再"契约先行"，§10#30 已改记「已防御」——见上方「最后一处文档收口」/ `cache.md` v1.13。**
2. **`server.md` / `cache.md` / `metrics.md` 头部上游溯源仍为 `SAD v1.9 / PRD v0.8`**，而 SAD 实际已 **v1.11**、PRD 已 **v0.9**（`config.md` v1.5 已更正）——本轮任务书**未授权改溯源**，仅报告，建议编排层下次同批更正。——**✅ 已闭环（本收口轮）：三份头部全部更正为 `SAD v1.11 / PRD v0.9`（`cache.md` v1.13 / `server.md` v1.14 / `metrics.md` v1.6），全仓详设溯源自此一致。**
3. **`SRV-T73` 若测试实现已把"`release` 不在 `finally`"的证伪断言写在其名下**，需按本版口径**机械搬迁/删除该断言至 `SRV-T72`**（属测试迁移，非文档冲突）；`T73` 保留三条断言不变。

## ★ 收尾小改（P2-4 读侧 fail-safe / F8 并发变体测试 / acquire 实现约束 / `config.md` 溯源闭环 · 只改文档）

> 范围：**只改** `doc/detailed/{cache,server,config,_PROGRESS}.md`。依据代码评审 **`CR-RSS-20260918-004/005`** 的 **P2** 与遗留清单。**未改代码 / SAD / PRD / API.md / README.md / `.opencode`**；**只增不删编号**。

### 1. `cache.md` v1.10 → **v1.11**（读侧 fail-safe 补全 + `acquire` 实现约束）

| 项 | 内容 | 落点 |
|----|------|------|
| **P2-4 读侧 fail-safe** | **条目有 `xml`、缺 `last_modified`/`fingerprint`** ⇒ 仍照常服务、只是不发 `Last-Modified`、禁用 IMS（v1.10 口径，**不变**）；**条目缺 `xml`（或 `None`）⇒ 视同 miss（返回 `None`）**，绝不返回残缺体、绝不抛 `KeyError`（抛异常经 `_guard` 会变"上游失败"降级体）；`time` 以 `.get('time')`（缺省 `None`）读取；`expires_at` **沿用** `entry.get('expires_at', 0)`（缺省 `0` ⇒ `now >= 0` 恒成立 ⇒ 自然判为过期 ⇒ 亦视同 miss）；`last_access` 由访问器自写、恒存在，**不需 `.get`**；`feed_cache_get` 经同一短路径 ⇒ 缺 `xml` 同样返回 `None`。**一句话原则**：读侧对「形态不完整」**fail-safe 到「当成没有」/「降级为无该头」**，**不得 fail-loud 到「抛异常 → 被 `_guard` 误报为上游故障」** | §2.4（返回契约 + `feed_cache_get` 注）/ §4.3 BR-CACHE-32 / §5.3 伪代码 / §9 / §10#28 |
| **微优化实现约束** | `feed_fetch_acquire` **必须先 `get(key)` 判空、仅在 `None` 时创建 `threading.Lock()`**——命中已有锁的路径**零分配**；`setdefault(key, threading.Lock())` 每次调用都先构造被丢弃的 `Lock`。**语义不变** | §2.4 / §4.3 BR-CACHE-35 / §5.3 伪代码 |
| **新增测试** | **`T-CACHE-36`**：① 缺 `xml` 的注入条目 ⇒ `feed_cache_get_entry`/`feed_cache_get` 均返回 `None`（视同 miss，不抛）；② 缺 `expires_at` ⇒ 视同过期；③ 四字段 legacy（**有 `xml`**）⇒ 仍返回 dict 且 `last_modified is None`（**与 ① 行为不同——对比例子是关键**） | §8 |

### 2. `server.md` v1.11 → **v1.12**（F8 并发变体测试契约 + `acquire` 实现约束）

| 项 | 内容 | 落点 |
|----|------|------|
| **P2-2 / 覆盖缺口** | 把 F8 契约承诺的"**并发 K 个不同 Host 同时在飞 ⇒ 在飞期间 `len(_feed_fetch_locks) <= K`**"从 `SRV-T71` 附注提升为**独立可测用例 `SRV-T73`**：K（如 8）个不同 Host 的键**同时在飞**（**阻塞式取数桩 + `threading.Event` 同步**，不用 `sleep`）⇒ 断言 ① 在飞期间 `1 <= len(_feed_fetch_locks) <= K` **且 `len(_feed_fetch_refs) == len(_feed_fetch_locks)`（两表同步）**；② 全部返回后两表均 `0`。**证伪方向**：`release` 不在 `finally`、或计数/锁表不同步 ⇒ 红。`SRV-T71` 收敛为**纯串行**（编号不删） | §8（新增 `T73`、改写 `T71`）/ BR-SRV-50 / §9 / §10#45 / §11 |
| **微优化实现约束** | `acquire` **先 `get` 判空、仅未命中建 `Lock`**（语义不变、命中路径零分配）写入 BR-SRV-50（`cache.md` BR-CACHE-35 同步） | BR-SRV-50 / §2.5 |
| **接口权威栏** | `config.md` v1.4 → **v1.5**、`cache.md` v1.10 → **v1.11** | §1 头部 |

### 3. `config.md` v1.4 → **v1.5**（溯源更正，✅ 最后一处溯源滞后闭环）

- 头部上游溯源由 **SAD v1.2 / PRD v0.3** 更正为实际 **SAD v1.11 / PRD v0.9**（依据两文档头部；PRD AC 总数 36）。
- **接口签名 / `DOMAIN_MATRIX` / `cache_policy` 返回值 / env 注册表 / 任何行为零变更**（v1.4 正文逐字保留）。

### 版本与计数

- `cache.md` **v1.10 → v1.11**、`server.md` **v1.11 → v1.12**、`config.md` **v1.4 → v1.5**。
- 编号：`cache.md` 新增 **`T-CACHE-36`**（BR 无新增，BR-CACHE-32/35 内补口径/约束）；`server.md` 新增 **`SRV-T73`**（BR 无新增，BR-SRV-50 内补实现约束）；测试计数 **74 → 75**（server）+ cache 新增 1 条。

### ⚠️ 发现的契约冲突（**只报告，不自行修改其它文档**）

1. **`server.md` v1.12 / `cache.md` v1.11 / `metrics.md` v1.5 头部溯源仍为 `SAD v1.9 / PRD v0.8`**，而 SAD 实际已 **v1.11**、PRD 实际已 **v0.9**（与本次更正的 `config.md` v1.11/v0.9 不一致）。本轮**只按任务书更正 `config.md`**，其余三份属**新暴露的同批滞后**，建议编排层下次调度 task-decomposer 时按同一口径同批更正。——**✅ 已闭环（本收口轮）：`cache.md` v1.13 / `server.md` v1.14 / `metrics.md` v1.6 → `SAD v1.11 / PRD v0.9`。**
2. **`cache.md` BR-CACHE-35 / `server.md` BR-SRV-50 的 `acquire` 历史示例仍保留 `setdefault`**——已在两文档内**就地加注 v1.11/v1.12 实现约束**（先 `get` 判空、仅未命中建 `Lock`），**不再构成矛盾**；实现侧以最新约束为准（观察行为不变）。
3. **`SRV-T71` 改写为纯串行后**，其"并发变体"由 `SRV-T73` 承接——**测试编号无删除**（`T71` 仍存在、语义收窄）；若测试实现已把并发断言写在 `T71` 内，需机械搬迁至 `T73`（属测试迁移，非文档冲突）。



> 范围：**只改** `doc/detailed/{server,cache,_PROGRESS}.md`。**未改代码、未改 SAD/PRD/其他详设/`.opencode`/API.md/README.md。**
> 触发：下游轮询在内容未变时应收 **304（零 body）**。本次仅出**详设增量**（不写业务代码）。

### 5 个设计分叉裁定（结论 + 理由）

| # | 分叉 | 裁定 | 一句理由 |
|---|------|------|---------|
| 1 | ETag 派生 | **弱 ETag `W/"sha256(规范化体)"`**：剔除 `<lastBuildDate>` 与 `<ttl>` 的**内容**后哈希整串 XML（纯函数 `_feed_etag`） | 裸 body 哈希因 `lastBuildDate=formatdate(None)` 每生成即变 ⇒ TTL 到期后内容未变也 200（**静默失效**）；guid-only 方案会漏掉 `<atom:link>`（请求派生 Host）与 channel 字段 ⇒ 跨 Host 误 304 |
| 2 | Last-Modified 时间源 | 新增 `cache.feed_cache_get_entry(path) -> dict\|None`（新鲜条目浅拷贝，含 `time`）；`feed_cache_get` **签名/语义不变**（薄包装）；`_get_or_fetch_feed` 返回 `(xml, last_modified)` | `time` 是现成写入时刻；单次查询同取 xml+time，避免"两次查询拾取降级态陈旧条目" |
| 3 | 304 头与 body | 新增专用 `_send_not_modified(etag, last_modified, varies_on_host)`：**无 body / 无 `Content-Encoding` / 无 `Content-Length`**，**带 `ETag`+`Cache-Control`(与 200 同值)+`Vary`(Host 三件套+`Accept-Encoding`)**，不写缓存；`HEAD` 同 | 304 不塞进 `_send_text`（后者总会 gzip/写 `Content-Length`），用独立方法把"无体无编码"变成结构性保证 |
| 4 | 条件头解析 | `If-None-Match` **优先**（存在即忽略 IMS）；支持 `*`/逗号多值/`W/` 弱比较；IMS 用 `parsedate_to_datetime` 秒级比较，**非法头忽略→200** | RFC 9110 §13.1.3 优先级；非法头不得 400/500 |
| 5 | RSS `<ttl>` | **加**；`generate_rss(..., ttl=None)`（分钟）；5 handler（**6 处调用点**——eastmoney 常规 + 空 feed 两个出口；★ P7b 回填 D-2）传 `_feed_ttl_minutes()=max(1,(feed_ttl+59)//60)`（30→1/180→3）；位置 `</lastBuildDate>` 与 `<atom:link>` 之间；**同样剔除出 ETag** | 盘中/非盘切换会使 ttl 变；若纳入 ETag 会在时段边界产生假 200（违反 R1）；ttl 是 advisory，已由 `Cache-Control` 表达 |

### 产出与落点

- `server.md` **v1.5 → v1.6（★ P3a-r1）**：§1.1#13 / §1.3 import（+hashlib/datetime.timezone/parsedate_to_datetime）/ §1.5（+`feed_cache_get_entry`）/ §2.1（RSS yaml +304 + 状态表 304 行）/ §2.3（`_guard` rss → 2-tuple）/ §2.5（返回 `(xml,last_modified)` + §2.5a 访问器契约）/ §2.9（`_feed_etag`/`_not_modified`/`_if_*` + 正则常量）/ §2.10（import 面 + 兼容清单）/ **§4.7 BR-SRV-36..44** / §5.1（rss 降级 2-tuple）/ §5.4（`_get_or_fetch_feed`+`_serve_feed`+条件函数）/ §5.8（`_send_text` 扩参 + `_send_not_modified` + **条件请求头清单** + cache-age RSS 行）/ §6.2#8 / §7.2#2 / **§8 T46–T62∪T52b/T56b（19 条 = 15 + v1.6 新增 4，总 64）** / §9 / §10#32–#37（总 37）/ §11 自检 / **§11.5** / §10.1（**5 条** server_http 打桩迁移〔v1.6 记 4，v1.8 / D-1 更正〕）
- `cache.md` **v1.5 → v1.6（★ P3a-r1）→ v1.7（★ P7b 回填 D-3）**：头部 / §2.4（+`feed_cache_get_entry` 契约）/ §2.5 兼容表 / §3.1（`time` = Last-Modified 权威）/ **§4.3 BR-CACHE-32** / §5.3（伪代码）/ §8 **T-CACHE-32**（v1.7：标注 ✅ 已实现 = `tests/test_cache.py::FeedEntryAccessorTests::test_t_cache_32_shallow_copy_isolates_the_container`）/ §9 / §10#23 / §11
- **新增 BR**：`BR-SRV-36..44`（9 条）+ `BR-CACHE-32`（1 条）
- **新增测试**：`SRV-T46..T60`（15 条）+ ★ v1.6 / C7 新增 `T52b`/`T56b`/`T61`/`T62`（**4 条**）（**合计 19 条**）+ `T-CACHE-32`（1 条）

### Step 2.5 链式推导（7 规则，本专项）

| 规则 | 结论 |
|------|------|
| 规则零（需求缺口） | **无新端点/新方法/新参数**；仅内部新增（`_feed_etag`/`_not_modified`/`_send_not_modified`/`feed_cache_get_entry` + `generate_rss` 可选 `ttl`）→ **无需用户确认新接口** |
| 规则一（读写配对） | 全为 GET/HEAD（读）；304 为条件读语义，无写配对需求 |
| 规则二（状态机） | 条件判定 = 二值：`INM 命中 ⇒ 304 / 未命中 ⇒ 200`；`INM 缺 → IMS: last_modified<=ims ⇒ 304 else 200`；`无头 ⇒ 200`；**降级（last_modified=None）⇒ 不可能 304**（穷举封闭） |
| 规则三（跨模块依赖） | `server → cache` 新增 `feed_cache_get_entry`（同向、无环）；`server → utils.generate_rss(ttl=)`（既有依赖，纯新增可选形参）；**不改 cache→server 反向** |
| 规则四（数据生命周期） | feed 条目 `time` 现被 `Last-Modified` 消费（读路径，不改写入）；304 **不写缓存**；ETag 纯派生（无存储）；`<ttl>` 纯派生 |
| 规则五（异步流程） | 无异步/无任务状态/无死信（纯同步响应头逻辑） |
| 规则六（权限/隔离） | 无鉴权/多租户；条件请求不改 `layerIsolation`/allowlist（`hashlib`/`datetime` 在 stdlib） |

**✅ 已由编排层完成（2026-09-18；见顶部「★ 最终收口」§2）**（原记「⚠️ 待编排层（不在本 agent 范围）」）：见下方「契约影响」；本轮**未**动 API.md/README.md/`.opencode`/opencode.json。

### 契约影响（需编排层同步 `API.md` / `README.md` / 变更日志）

1. **5 个 RSS feed 的 200 响应新增 `ETag`（弱 `W/"…"`）与（有缓存条目时）`Last-Modified`** —— `API.md` 的 RSS 端点响应头说明需补；`README.md` 若描述轮询方式建议说明可带 `If-None-Match`。
2. **RSS feed 新增 `304 Not Modified` 响应** —— 无 body / 无 `Content-Encoding`；属**对外新增状态码**（🟠 STABLE 的"只增"），须写 API 文档 + 变更日志。
3. **`Accept-Encoding: gzip` 客户端下 304 不返回 `Content-Encoding`** —— 客户端库行为约定（应复用自身缓存的编码副本），建议 API.md 附注。
4. **RSS feed XML 新增 channel 级 `<ttl>`（分钟；盘中 1 / 非盘 3）** —— 这是**响应体内容变化**（XML schema 只增元素），须在 API.md / README 的 feed 样例或说明中登记；`generate_rss` 的 `ttl=None` 默认保证既有调用点不变。★ **【C3 / P1-03 · 必须写进 `API.md` 的契约语句】「`<ttl>` 是聚合器缓存提示，非时效保证；需要比 1 分钟更快的时效请用 SSE（4s）」。** 细则：**最小粒度 1 分钟**（盘中缓存 TTL 30s 向上取整为 `1`；不得向下取整为 0、不得恒为 3）；**推荐轮询 = `ETag` 条件请求优先、轮询间隔 ≥ 30s**（`Cache-Control: max-age` 是更强承诺：盘 30 / 非盘 180）。**此项是防止下游照抄 `<ttl>1</ttl>` 把时效降到 1 分钟的唯一缓冲**（BR-SRV-43 / `server.md` §5.8）。
5. **条件请求为可选**：不带条件头的客户端行为与现状逐字一致（200 全量 + 既有头），**无需迁移**；此点应在变更日志中明确，避免消费方误判为破坏性变更。
6. **SAD 回填（system-architect，★ P3a-r1 由"可选"改判为**必做**）**：RSS 条件请求的 ETag 派生口径（弱校验器、剔除 `lastBuildDate`/`ttl`/**`pubDate`**）与 `<ttl>` 轮询上限若需进 SAD §2/§4，由编排层调度；`server.md` §4.7 / `cache.md` BR-CACHE-32 已按实现钉死。**依据：评审 D-1（SAD 全文无 304/ETag/`Last-Modified`/`<ttl>` 契约落点，P1 级契约缺口）**。

### ★ P3a-r1 评审定向修（C1–C8）· 编排层待办（★ C8 / 评审 `## 漂移检测` 8 项）

> 依据 `doc/review/rss-conditional-get_详细设计评审_专家版.md`（REV-DES-20260918-001，结论 ⚠️ 有条件通过，P0×0 / P1×3 / P2×10 + 漂移 8 项 + 缺失用例 14 条）。本轮**已就地修**：`server.md` **v1.5→v1.6**（C1 canonical 投影 + item 级 `<pubDate>` 全量剔除 · BR-SRV-37 双向不变式；C2 §10.1 迁移第 4 条 `h.headers={}` + §11 计数 4；C3 `<ttl>` 契约语句 + 推荐轮询 ≥30s；C4 `dt.timestamp()` 入 `try` + `OSError`；C5 BR-SRV-39 弱前缀措辞；C6 §10#36 依据；C7 14 条缺失用例 → 测试 **64 条**）+ `cache.md` **v1.5→v1.6**（C7#14 T-CACHE-32 容器态负例。**无实现/契约变更**）。

**↓ 以下 8 项为编排层（P7b）待办——本 agent 不改 SAD / PRD / API.md / README.md：**（**✅ ①②⑤⑥（SAD / PRD / API.md / README / 变更日志）已由编排层完成；③⑦ 已就地闭环；④⑧ 本文件不再跟踪——见顶部「★ 最终收口」§2**）

| # | 漂移项（评审编号） | 编排层待办 | 承接方 |
|---|------------------|-----------|--------|
| ① | **SAD 未承接 RSS 条件请求（D-1，P1 级契约缺口）** | SAD 回填：§2.4（或 server 行）增"RSS 响应缓存校验器与 304 语义"「弱 ETag 派生口径（**剔除 `lastBuildDate`/`ttl`/`pubDate` 的内容**）」「`<ttl>` 为 advisory、**最小 1 分钟**」；并显式声明**仍为拉模型**、未启用 keep-alive。**由"可选"改判为必做** | system-architect |
| ② | **PRD 无对应 AC（D-2）** | PRD v0.7 增 AC（如「AC-A13 RSS 条件请求：内容未变 ⇒ 304 零 body；`<ttl>` advisory、最小 1 分钟」）或由 SAD 正式承接 ①；**当前唯一追溯目标是工作文件 `_MEMORY_CACHE.md`，一旦覆写即失去需求锚点** | prd-writer |
| ③ | **详设头部溯源版本（D-5 / P2-09）** | **✅ 本轮已就地修正**：`server.md` / `cache.md` 头部由 `SAD v1.3`/`v1.2` + `PRD v0.3` → **实际 SAD v1.7 / PRD v0.6**。⚠️ **剩余（不在本轮写范围）**：`config.md` 头部仍写 SAD v1.2、`metrics.md` 头部仍写 SAD v1.2 / PRD v0.3 ⇒ 建议编排层下次调度 task-decomposer 时同批修正（口径同上） | ✅ task-decomposer（★ 2026-09-18：`server.md` v1.12 / `cache.md` v1.11 / `metrics.md` v1.5 已完成至 **SAD v1.9 / PRD v0.8**；★ **收尾小改：`config.md` v1.5 已更正为实际 `SAD v1.11 / PRD v0.9`——本项登记（含 config）✅ 闭环**；⚠️ 新暴露：`server.md`/`cache.md`/`metrics.md` 头部仍为 v1.9/v0.8，实际已 v1.11/v0.9，见「收尾小改」冲突 #1）——**★ 本收口轮（2026-09-18）：`cache.md` v1.13 / `server.md` v1.14 / `metrics.md` v1.6 头部已更正为实际 `SAD v1.11 / PRD v0.9` ⇒ 全仓溯源滞后 ✅ 全部闭环（无剩余）。** |
| ④ | **「本专项 R1」与 SAD/PRD R1–R20 同名不同义（D-4）** | 统一改称 **`US-RSS-1` / `AC-RSS-1`**（或每次出现写全「本专项 R1（`_MEMORY_CACHE.md`）」）；避免跨文档把"内容未变⇒304"误读为 SAD 根因 R1。本轮已在 `server.md` 头部加命名说明并保留限定语 | 编排层统一（SAD/PRD 编号权）+ 各详设 |
| ⑤ | **对外文档同步面缺分叉 5 契约语句（D-6 → 并入 P1-03）** | `API.md` / `README.md` / 变更日志须补：`ETag`/`Last-Modified`/`304`/`<ttl>` 语义 + **「`<ttl>` 非时效保证，短线请用 SSE」** + RSS 样例体现 `<ttl>` 元素（**放行前置**）；★ 见上方契约影响 #1–#5 与本文件 #4 | 编排层（API.md/README/变更日志） |
| ⑥ | **"304 只省 body、不省回源"（评审五残余风险）** | `API.md` 写明：TTL 到期仍回源重生成；若上游窗口内静默改内容，客户端最长滞后一个 TTL。另注明"**降级 feed 不应作为 304 缓存的判断依据**"（同一错误表示会 304，监控勿误读） | 编排层（API.md） |
| ⑦ | **`_PROGRESS` 契约影响 #6 "可选"口径（D-1 关联）** | 已在本文件改判为**必做**（见契约影响 #6）；SAD 回填由 system-architect 承接 | ✅ 本文件 + system-architect |
| ⑧ | **§10#37 / BR-SRV-44 出范围项（D-7，无反向漂移）** | 确认 SAD/PRD 均无 keep-alive / `/opml.xml` / JSON 条件请求的既有承诺 ⇒ **无需回填**；若后续要启用须独立评估（波及全部端点连接语义与线程池） | 编排层（评估立项） |

> **评审放行条件对照**：C1（P1-01）✅ · C2（P1-02）✅ · C3（P1-03）✅ · C4（P2-01/P2-07 低成本）✅ · C5（缺失用例 #1/#2/#4 + #3）✅ · C6（编排层登记：SAD 回填 D-1 + PRD 承接 D-2 + 对外文档三件）→ **上表 ①②⑤为本表交付，编排层回执后即可进 `code-developer`**。


### ★ P3a-r2 复审 P2 收口（机械修正 · 只修精确性，不引入新设计）

> 依据 `doc/review/rss-conditional-get_详细设计评审_复审_专家版.md`（REV-DES-20260918-002，结论 ✅ 通过，P0×0 / P1×0 / **P2×6**）。本轮**已就地修**：`server.md` **v1.6→v1.7**——**P2-a** `SRV-T52b` 用例定义细化（必须 patch 时钟 `t`/`t+1` + 红/绿方向声明 + 纯函数「仅 `pubDate` 不同 ⇒ 同 ETag」断言；三门 feed 覆盖不变；未控时钟不得作 C1 验收证据）；**P2-b** BR-SRV-37 第二子句补「除三项外」限定（§6.2#8③ 同步）；**P2-c** §10.1 `FeedDoubleCheckTests` 补返回值断言改 2-tuple；**P2-d** §10.1 第 3 条标题 `:440` → `:440 / :450`；**P2-f** §1.1 标题 11 → 13 条。**本文件**：计数口径统一为**测试总 64 / 新增 19（其中 v1.6 新增 4）/ 迁移 4**（消除 `:33`/`:36` 与 `:63` 的两套口径）。`cache.md` 无 P2 落点，保持 **v1.6**。**未改设计裁定 / 契约 / 代码 / SAD / PRD / API.md / README.md / `.opencode`。**


## ★ P7b 漂移回填（`server.md` v1.8 / `cache.md` v1.7 · 只改文档，不改代码/设计裁定）

> 依据 `doc/review/rss-conditional-get_代码评审_专家版.md`（CR-RSS-20260918-001，结论 ⚠️ 有条件通过；D5 三项文档滞后 D-1/D-2/D-3）。**本轮只改** `doc/detailed/{server,cache,_PROGRESS}.md`；**未改代码 / SAD / PRD / API.md / README.md / `.opencode`**；**不改任何设计裁定**（BR 编号 / 算法 / 取值 / 优先级 / 出范围项）。

| # | 回填项 | 落点 | 结论 |
|---|--------|------|------|
| **D-1** | §10.1 迁移清单**漏列第 5 条**：`test_server_http.py::GuardTests::test_rss_degrade_is_valid_feed`（:80）直接调 `_guard(shape='rss')` 并把返回值当 XML；rss 形状自 v1.5 起钉死为 2-tuple ⇒ 照 v1.7 清单施工**必红**（实现阶段已机械迁移：解包 + `last_modified is None`） | `server.md` §10.1 表格补第 5 条 + §10.1 计数口径注 + §11 自检 | ✅ 迁移计数 **4 → 5** |
| **D-2** | eastmoney 的 `<ttl>` 调用点为 **6 处 / 5 个 handler**（`handle_eastmoney_kuaixun` 常规返回 + 「无匹配 ⇒ 空 feed」提前返回，两处均传 `ttl=_feed_ttl_minutes()`；评审 SIDE-EFFECT #4 确认该选择正确） | `server.md` BR-SRV-43 / §2.10 / §5.8（新增出口说明）/ §11.5 | ✅ 「5 处」→「6 处调用点 / 5 个 handler」 |
| **D-3** | `cache.md` T-CACHE-32「浅拷贝隔离负例」**已在 P6c 实现**，但文档未标注 | `cache.md` §8 用例 + §9 映射 + §11 自检 | ✅ 标注 **已实现** = `tests/test_cache.py::FeedEntryAccessorTests::test_t_cache_32_shallow_copy_isolates_the_container` |
| **顺带·P2-3** | `_send_text`（200）与 `_send_not_modified`（304）**各写一份** `Cache-Control`/`Vary`——**实现现状，非设计变更**；`SRV-T62` 为兜底断言 | `server.md` §5.8（如实记录） | ✅ 记录现状与 T62 关系（不抽公共函数 / 不改设计） |
| **顺带·§8 映射** | 实现把 `SRV-T52b` 拆为 **5 个 unittest 方法** | `server.md` §8 表后注 | ✅ 编号计数不变（总 64） |


## ★ P8 对抗性盲审 F1–F7 契约化（`server.md` v1.9 / `cache.md` v1.8 / `metrics.md` v1.4 · 只改文档，不改代码）

> 依据：P8 对抗性盲审（**P0=0 / 2×P1 + 8×P2**）+ 编排层裁定。**本轮只改** `doc/detailed/{server,cache,metrics,_PROGRESS}.md`；**未改代码 / SAD / PRD / API.md / README.md / `.opencode`**。

| # | 修复 | 落点 | 契约产出 |
|---|------|------|---------|
| **F1** | **P1-1 根治**：`Last-Modified` = 表示最后一次变更的时刻 | feed 条目新增 `fingerprint`/`last_modified`；`feed_cache_put` 与**同一键上一条目（★ 即使已过期）**比指纹 ⇒ 相同继承、不同取写入时刻；不变式 `ETag 变 ⟺ Last-Modified 前进` | **BR-SRV-38 改写** + **BR-CACHE-33** |
| **F2** | **P1-2 根治**：feed 缓存键覆盖表示全部变化维度 | `PUBLIC_BASE_URL` 已设 ⇒ `path`；未设 ⇒ `path + '\x00' + base_url`；键对 cache 不透明；`_feed_fetch_locks` 按同一键建锁；放大风险已论证 | **BR-SRV-45** |
| **F3** | **P2-6**：新增 `http_304_total` | `metrics._KNOWN` + `_DEFAULTS` 同步注册（19 → **20**）；`_send_not_modified` **单点**计数；只需计数不需分母 | **BR-SRV-46** + **BR-MET-14** |
| **F4** | **P2-4**：feed `max-age` authority 由 `news_url` 改 `feed` | `_CACHE_AGE_DOMAINS` 5 path 改 `'feed'`；**数值不变、契约不变**；不变式 `_feed_ttl_minutes() == ceil(max-age/60)` | **BR-SRV-47** |
| **F5** | **P2-5**：`feed_cache_put` 返回写入条目 | 返回六字段浅拷贝（非 None）；`_get_or_fetch_feed` 直接消费、**删除 put 后第二次查询**（消除「200 带 ETag 却不带 `Last-Modified`」窗口） | **BR-SRV-48** + **BR-CACHE-34** |
| **F6** | **P2-7 仅文档化**：HTTP/1.0 304 EOF 收尾 | 304 无 `Content-Length`；RFC 9110 §8.6 禁写 `Content-Length: 0`；本轮不升 `protocol_version`/keep-alive | **BR-SRV-49** + §10#36 |
| **F7** | 测试补充 | 新增 `SRV-T63..T70`（8 条）+ 改写 `SRV-T55`（自造陈旧条目、不依赖时序）；`T-CACHE-33/34` 新增、`T-CACHE-32` 扩六字段；`MET-T18` 新增 | 测试 **64 → 72**（server）+ cache/metrics 用例 |
| **F8** ★ 后补 | **P1-1 根治**（`CR-RSS-20260918-003`，评审推荐方案 1）：feed 取数锁表与键空间同界收敛 | cache 新增 `feed_fetch_acquire/release` + `_feed_fetch_refs`（`acquire` 返回锁前计数 +1、`release` 归零两表同删）；`_get_or_fetch_feed` 改 `acquire` / `try…finally release`；BR-SRV-45 **补正**（原放大论证只覆盖上游请求，未覆盖锁表内存与本地生成） | **BR-SRV-50** + **BR-CACHE-35** + `SRV-T71/T72` + `T-CACHE-35` |

### 编号清单（只增不删；改写用原号并注明）

- **改写**：`BR-SRV-38`（`Last-Modified` 时间源）、`BR-SRV-7`/`BR-SRV-42`（RSS `max-age` 域 → `feed`）、`BR-CACHE-32`（条目六字段 + `last_modified` 为 Last-Modified 源）。
- **新增**：`BR-SRV-45`（F2）/ `BR-SRV-46`（F3）/ `BR-SRV-47`（F4）/ `BR-SRV-48`（F5）/ `BR-SRV-49`（F6）；`BR-CACHE-33`（F1 指纹继承）/ `BR-CACHE-34`（F5 返回值）；`BR-MET-14`（F3）。
- **新增测试**：`SRV-T63..T70`（8 条）+ `T-CACHE-33`/`T-CACHE-34`（2 条）+ `MET-T18`（1 条）；**改写** `SRV-T55`、`T-CACHE-32`、`SRV-T11`、`SRV-T46/T47`/`FeedDoubleCheckTests` 打桩。

### 契约影响（需编排层 / 其它文档同步 · 本 agent 不改）—— ✅ 已由编排层完成（见顶部「★ 最终收口」§2；以下为历史登记）

1. **`API.md` / `README.md` / 变更日志**：F3 新增 `http_304_total`（`/healthz.metrics` 只增一个键，属"只增"）；F1 的 `Last-Modified` 语义澄清（"表示最后一次变更"）；F4 无对外数值变化（**无需**外部文档改动，仅 authority 内部收敛）；F2 无对外接口变化。
2. **SAD 回填（system-architect）**：§2.6 计分板注册表 19 → 20（F3）；§2.1 D4 / §2.4 可补"RSS `max-age` authority = `feed`"（F4）；`feed` 缓存键含 `base_url` 的说明（F2）。
3. **`config.md`**：`DOMAIN_MATRIX` 无改动，无需同步。

### ⚠️ 发现的契约冲突（**只报告，不自行修改其它文档**）

1. **`metrics.md` v1.3 的"注册表不新增名称（SAD 契约冻结）" vs F3**：F3 要求新增 `http_304_total`。本版在 `metrics.md` v1.4 内已按编排层裁定改口径（并留痕），但**SAD §2.6 计分板仍记 19 名** ⇒ 存在 SAD↔详设注册表不一致，需 system-architect 回填（见上"契约影响 #2"）。
2. **SAD §2.1 D4 的"承诺=行为"推导以 `news_url`/`feed` 同 L3 为前提**：F4 改 authority 后推导不再依赖"两域恰好同 L3"，属**强化**；SAD 若原样保留旧措辞不构成矛盾，但建议补一句"RSS max-age 取 `feed` 域"。
3. **`test_t55` 旧断言实际上是 P1-2 的伪绿**：该用例此前"通过"依赖 path 键缓存旧表示，**与 F2 的键语义直接冲突**——已在 `server.md` §8/§10.1 标注改写（**属测试迁移，不改其它文档**）。
4. **`cache.md` BR-CACHE-32（v1.5–v1.7）** 与 `server.md` BR-SRV-38 旧文均称 `entry['time']` 为 Last-Modified 权威：本版已在**两份文档内**同步改写为 `entry['last_modified']`，`time` 保留给 `refresh_epoch`（BR-CACHE-31）——无跨文档冲突残留。
5. **【★ v1.10 / F8 更正】`server.py`/`cache.py` 的 F1–F6 代码已实现**（本文件旧版"仍未实现"条目**作废**）：F1–F6 已落地，通过 §8 的 **72 条**用例（含 **`SRV-T66` 304 计数**等 **504 用例场景**），并已过代码评审 **`CR-RSS-20260918-003`**（`doc/review/rss-conditional-get_p8修复_代码评审_专家版.md`，结论 ✅ 通过；但判 **P1-1（`_feed_fetch_locks` 无界增长）对外部署前必修**）。本轮 **F8** 即按该评审"**方案 1：引用计数 / 惰性回收**"契约化（`server.md` BR-SRV-50 / `cache.md` BR-CACHE-35）：**★ 2026-09-18 状态更新（F8 已实现）**——`server.py::_get_or_fetch_feed` 已走 `feed_fetch_acquire` / `try…finally feed_fetch_release`，`cache.py` 两原语 + `_feed_fetch_refs` 就位（`server.md` §10.1 / `cache.md` §8 的 `SRV-T71/T72`、`T-CACHE-35` 已落地）；同轮 **P2-1..P2-4** 全部修复（详见下方「P2-1..P2-4 修复 + 溯源收口」）；**全量测试 511 用例全绿**。


## ★ P8 F8 契约化（`server.md` v1.10 / `cache.md` v1.9 / `metrics.md` v1.5 · 只改文档，不改代码）

> 依据：代码评审 `CR-RSS-20260918-003`（`doc/review/rss-conditional-get_p8修复_代码评审_专家版.md`，判 **P1-1 = F2 引入、对外部署前必修**）+ 编排层裁定（采纳推荐**方案 1：引用计数 / 惰性回收**）。**本轮只改** `doc/detailed/{server,cache,metrics,_PROGRESS}.md`；**未改代码 / SAD / PRD / API.md / README.md / `.opencode`**；**只增不删 BR 编号**。

### F8 契约（锁表与键空间同界收敛）

| 项 | 内容 | 落点 |
|----|------|------|
| **根因（F2 引入）** | `_feed_fetch_locks`（`cache.py:901`）+ `_feed_fetch_locks_lock`（`:902`）以 `cache_key` 为键 `setdefault` 建 `threading.Lock`（消费点 `server._get_or_fetch_feed` `:1346-1347`），**全仓无任何删除/淘汰**。历史 `系统_代码评审报告_001.md` TS-4 曾因"`pop` 与持锁线程竞态 ⇒ 同一键双抓"**主动移除 `pop`** ⇒ "只增不减"是既有取舍。**F2 把键空间从 5 条固定 path 变成 "path × 请求派生 base_url"**，而 `_valid_host_header`（`server.py:591`）**只校验格式、不校验归属** ⇒ 任意合法主机名都能造新键 | BR-SRV-45 补正 |
| **后果 1** | **永久内存增长**（每键约 300–450 B，外部可无界触发，直至 OOM） | BR-SRV-45 补正 / BR-SRV-50 |
| **后果 2** | **本地生成放大**：键数超过 `feed_cache` 上限 100 后每个新 Host 必 miss ⇒ 一次 `generate_rss` + sha256、LRU 持续抖动（**上游请求仍被 URL 级缓存兜住 ⇒ 只放大本地 CPU，不放大上游**） | BR-SRV-45 补正 |
| **方案（评审推荐 1）** | **引用计数 / 惰性回收**：新增 cache 层原语 **`feed_fetch_acquire(key) -> Lock`** / **`feed_fetch_release(key)`**，**两者都持 `_feed_fetch_locks_lock`**；`acquire` 返回锁**之前**计数 +1（必要时建 `Lock`）；`release` 递减、**归零即 `pop` 键及其计数**（**两表同删**，避免计数表成为新的无界表）。新增 `_feed_fetch_refs: dict[cache_key -> int]` | BR-CACHE-35 / BR-SRV-50 |
| **为什么不能简单重加 `pop`** | 归零前 `pop` 会让"已取出锁但尚未进入 `with`"的线程与后来者拿到**两把不同的锁** ⇒ 同一键双抓（TS-4 原事故）。**不变式**：只要还有线程持有或即将获取该键的锁，计数 ≥1，该键不可能被 `pop` | BR-CACHE-35 / BR-SRV-50 |
| **正确性论证** | `pop` 只发生在计数归零时（无持有者/等待者）；随后到达的线程创建新锁，其双检仍命中前一个持有者已写入的缓存条目 ⇒ **不产生重复取数**（第二次真取数只可能因条目确实已过期） | BR-CACHE-35 / BR-SRV-50 |
| **调用纪律** | `acquire` / **`try ... finally: release`**（异常路径也必须释放，否则计数泄漏 ⇒ 锁表退化为只增不减） | BR-SRV-50 / `server.md` §5.4 |
| **有界性结论** | 锁表规模收敛于"**并发在飞的键数**"，而非"累计见过的键数"；`PUBLIC_BASE_URL` 已设时键恒为 5 条 path。**可选运营缓解（备注）**：部署侧强制设 `PUBLIC_BASE_URL` | BR-SRV-50 / BR-CACHE-35 |

### 新增编号 / 测试

- **新增 BR**：**`BR-SRV-50`**（F8，`server.md` §4.7）/ **`BR-CACHE-35`**（F8，`cache.md` §4.3）。**改写（补正）**：`BR-SRV-45` 的"放大风险论证"**保留原论证并加限定**（原论证只覆盖上游请求，未覆盖锁表内存与本地生成）。
- **新增测试**：`server.md` **`SRV-T71`**（收敛性：串行 N=50 个不同 Host 后 `len(_feed_fetch_locks) == 0`，断言"不随 N 增长"）/ **`SRV-T72`**（并发不双抓：`fetch_func` 仅 1 次；异常路径计数归零）→ 测试 **72 → 74**；`cache.md` **`T-CACHE-35`**（原语级：计数成对 / 同锁 / 不双抓 / 异常不泄漏 / 不随 N 增长）。
- **`metrics.md` v1.5（顺带 3 处文档修正之 1 + 溯源）**：更正 v1.4 自检句「`metrics.py` 零代码变更」（与 BR-MET-14 互斥）；溯源 `SAD v1.2`/`PRD v0.3` → **`SAD v1.9`/`PRD v0.8`**。
- **`cache.md` v1.9（顺带 3 处文档修正之 2）**：§2.4 双检步骤 ② 由 `再次 feed_cache_get(path)` 更正为 **`再次 feed_cache_get_entry(cache_key)`**（与 `server.md` §2.5 / `SRV-T70` 的"`feed_cache_get_entry` 恰好 2 次"一致）；头部溯源 `SAD v1.7` → **`SAD v1.9`**。
- **`server.md` v1.10（顺带 3 处文档修正之 3）**：`BR-SRV-46` 加 **P2-5 口径备注**——`http_304_total` 在**构造 304 响应时**计数，故极少数"计数已增但响应未送达客户端"（客户端中途断开 / `send_response` 抛错）的情况**会计入**，这是**有意语义**（"服务端决定返回 304 的次数"，非"客户端成功收到的次数"）。

### Step 2.5 链式推导（7 规则，F8）

| 规则 | 结论 |
|------|------|
| 规则零（需求缺口） | **无新对外端点/新 HTTP 参数**；新增 2 个 cache 层内部公开原语（`feed_fetch_acquire/release`）→ **无需用户确认新接口** |
| 规则一（读写配对） | `acquire`/`release` **必须成对**（`try/finally`）——新增的读写配对约束本身即本契约核心 |
| 规则二（状态机） | 锁表键状态机：`不存在 --acquire--> count=1 --acquire--> count=n --release--> count=n-1 --release to 0--> pop（不存在）`；**禁止** `count>0` 时 `pop`（穷举封闭） |
| 规则三（跨模块依赖） | `server → cache` 新增 `feed_fetch_acquire/release`（同向、无环）；替换原 `_feed_fetch_locks`/`_feed_fetch_locks_lock` 直接 import；**不改 cache→server 反向** |
| 规则四（数据生命周期） | 锁表条目生命周期 = "首次 acquire 创建 → 每次 acquire/release 增减计数 → 计数归零删除"；**有界 = 并发在飞键数** |
| 规则五（异步流程） | 无异步/无任务状态/无死信（纯同步锁原语） |
| 规则六（权限/隔离） | 无鉴权/多租户；不改 `layerIsolation`（`threading` 已在 allowlist） |

### 契约影响（需编排层 / 其它文档同步 · 本 agent 不改）—— ✅ 已由编排层完成（见顶部「★ 最终收口」§2；以下为历史登记）

1. **`API.md` / `README.md` / 变更日志**：F8 **无对外接口变化**（内部锁表生命周期）⇒ **无需**外部文档改动；仅 `PUBLIC_BASE_URL` 作为可选运营缓解值得在部署文档说明。
2. **SAD 回填（system-architect）**：SAD/PRD 未定义 feed per-键 锁表生命周期；若需入 SAD §2.2/§4，可补"feed 取数锁表按并发键数有界、引用计数归零回收"（`server.md` BR-SRV-50 / `cache.md` BR-CACHE-35 已按实现钉死）。

### ⚠️ 发现的契约冲突（**只报告**）

1. **✅ 已闭环（2026-09-18）**：`server.md` v1.11 头部已更正为 **SAD v1.9 / PRD v0.8**；`cache.md` v1.10 头部 PRD 已更正 **v0.6 → v0.8**（SAD v1.9 于 v1.9 版已更正）；`metrics.md` v1.5 已更正 SAD v1.9 / PRD v0.8。**除下条 `config.md` 外无剩余滞后。**
2. **✅ 已闭环（2026-09-18 收尾小改）**：`config.md` **v1.5** 头部已更正为实际 **SAD v1.11 / PRD v0.9**——本项登记（含 §③ 与本章）**闭环**。⚠️ **新暴露（同批）**：`server.md` v1.12 / `cache.md` v1.11 / `metrics.md` v1.5 头部仍为 **SAD v1.9 / PRD v0.8**，实际 SAD 已 **v1.11**、PRD 已 **v0.9**；本轮按任务书只更正 `config.md`，其余建议编排层下次同批更正（见「收尾小改 → ⚠️ 契约冲突 #1」）。——**✅ 已闭环（本收口轮）：`cache.md` v1.13 / `server.md` v1.14 / `metrics.md` v1.6 已更正为 `SAD v1.11 / PRD v0.9`。**


## ★ P2-1..P2-4 修复 + 溯源收口（`server.md` v1.11 / `cache.md` v1.10 · 只改文档，不改代码）

> 依据：代码评审 `doc/review/rss-conditional-get_p8修复_代码评审_专家版.md`（`CR-RSS-20260918-003`，P1-1 必修 + P2-1..P2-4）的**实现落地事实** + code-developer 的 `>>DOC_SYNC` 标记（P2-1）。**本轮只改** `doc/detailed/{server,cache,_PROGRESS}.md`；**未改代码 / SAD / PRD / API.md / README.md / `.opencode`**；**无 BR 语义变更**。

### 实现事实（以代码为准）

| 项 | 实现事实（代码） | 文档收口 |
|----|----------------|---------|
| **F8 已实现** | `cache.py`：`feed_fetch_acquire`（计数 +1 后返回锁）/ `feed_fetch_release`（归零两表同删）+ `_feed_fetch_refs`；`server.py::_get_or_fetch_feed` 经 `acquire` / `try…finally release` | `server.md` BR-SRV-50 / `cache.md` BR-CACHE-35（契约 v1.9 / v1.10 已钉死，**实现对齐**） |
| **P2-1 修复** | `cache.py::feed_cache_get_entry` 读 `entry.get('last_modified')`；`feed_cache_put` 继承分支读 `prev.get('last_modified')`（缺省 `None`）；`fingerprint` 两处本为 `.get` | `cache.md` v1.10：§2.4 / §3.1 / BR-CACHE-32/33 / §5.3 / §8 T-CACHE-32/33 / §10#27；`server.md` v1.11：§2.5 访问器契约注 + BR-SRV-38（**措辞收口**） |
| **P2-2 修复** | `tests/test_server_http.py::test_t55`：自造陈旧条目 + 断言继承值（`last_modified` 继承） | 测试用例侧（文档 §8 `SRV-T55` 已记改写口径，无需再改） |
| **P2-3 修复** | `tests/test_server_http.py::test_t69`：增加两域分叉受控断言 | 测试用例侧（文档 §8 `SRV-T69` 口径不变） |
| **P2-4 修复** | `tests/test_cache.py::test_t_cache_33_fingerprint_inherits_across_expiry`：第二次 `put` 前置 `_last_feed_sweep=0.0` 强制触发①，断言清扫确已发生 + 继承仍成立 | `cache.md` v1.10 §8 `T-CACHE-33`（补 ⑥⑦） |
| **测试** | **全量 511 用例全绿**（`server.md` §8 当轮 74 条含 `SRV-T71/T72`；`cache.md` T-CACHE-32..35 含 legacy fail-safe 负例）——★ 收尾小改后 `server.md` 契约 **75 条**（+`SRV-T73`）、`cache.md` **+`T-CACHE-36`** | 本文件登记 |

### P2-1 语义（fail-safe，写死）

- **非六字段条目（legacy / 注入）缺 `last_modified`** ⇒ 读为 **`None`** ⇒ **不发 `Last-Modified` 头、禁用 IMS**（`If-None-Match` 仍按 ETag 正常评估），**而非抛 `KeyError` 经 `_guard` 变降级体**（降级体是"上游失败"语义；缺字段只是"该条目无变更时刻"，二者必须区分）。
- **继承分支**：`prev` 指纹匹配但缺 `last_modified` ⇒ 新条目 `last_modified=None`（**不前进为写入时刻**——前进会误发"已变更"信号）。
- **`fingerprint` 核对通过**：`entry.get('fingerprint')` / `prev.get('fingerprint')` **本就是 `.get`**，无需改。

### 溯源更正

- `server.md`：**SAD v1.7 → v1.9**、**PRD v0.6 → v0.8**；接口权威栏 `cache.md` v1.9 → **v1.10**。
- `cache.md`：**PRD v0.6 → v0.8**（SAD v1.9 已在上版更正）。
- **`config.md`（SAD v1.2 / PRD v0.3）已由「收尾小改」更正为 SAD v1.11 / PRD v0.9（v1.5 = ✅ 闭环）**（见上「P8 F8 契约化 → ⚠️ 冲突 #2」与「收尾小改」§3）。

### 版本

- `server.md` **v1.10 → v1.11**、`cache.md` **v1.9 → v1.10**（变更记录已写：**措辞收口 + 溯源更正，无 BR 语义变更**）。
- `config.md` / `metrics.md` / `stream.md` / `stock_api.md` / `market_api.md` / `cdp_engine.md` **本轮未改**。

### ⚠️ 发现的冲突（只报告）

1. **`config.md` v1.4 头部溯源滞后已闭环**：v1.5 已由「收尾小改」更正为实际 **SAD v1.11 / PRD v0.9**（原写 v1.2 / v0.3）。⚠️ **同批新暴露**：`server.md` v1.12 / `cache.md` v1.11 / `metrics.md` v1.5 仍为 SAD v1.9 / PRD v0.8（实际 v1.11 / v0.9），见「收尾小改 → ⚠️ 契约冲突 #1」。——**✅ 已闭环（本收口轮）：`cache.md` v1.13 / `server.md` v1.14 / `metrics.md` v1.6 → `SAD v1.11 / PRD v0.9`。**
2. **`metrics.md` v1.5 变更块（历史行）** 仍写 "`server.md` → v1.10、`cache.md` → v1.9"——属该版**历史快照**（现行：`server.md` v1.11 / `cache.md` v1.10），**不回改**，跨文档阅读以各文档头部为准。
3. **`cache.md` 历史变更行（v1.5–v1.9）** 仍含 `entry['last_modified']` / `prev['last_modified']` 直接下标表述——属**历史记录**；正文（§2.4 / §3.1 / §4.3 / §5.3）已全部收口为 `.get(..., None)`，**不回改历史行**（与"只增不删"惯例一致）。


## ★ r5 契约同步（`stream.md` v1.3 / `stock_api.md` v1.3 / `server.md` v1.4 · 以代码为准）

> 范围：**只改** `doc/detailed/{stream,stock_api,server}.md` + 本文件。**未改代码、未改其他文档。**
> 触发：r5 容量重标定（连接池后重测）+ 冷启动去重/唤醒 + `depth` 域落地后，三份文档仍为旧口径。

### 1. `stream.md` → **v1.3**（8 组同步项 → §11.4；偏差 28→**33**；测试 43→**48**）

| 主题 | 代码实况（`stream.py`） | 同步结论 |
|------|----------------------|---------|
| `tick_interval(fields=None)` | `L584-616`：无域 ⇒ `_trading_tiers()['L1']`；否则 `min(tiers[cache_policy(d)['tier']] for d in domains)` | 节拍 = **最短订阅域 tier**（quote/depth=L0 盘中 **4s**）；`push_loop` 一轮算一次下传 `_push_once(t0, tick=)` → `_refresh_pool(..., tick=)` |
| `_PER_FETCH_EST` | `= config.STREAM_PER_FETCH_EST`（默认 **0.3**） | v1.2 的 2.2 作废 |
| `BATCH_MAX_WORKERS` | `= config.BATCH_MAX_WORKERS` = **20** | v1.2 的 8 作废 |
| `_FIELD_FETCH_CALLS` | `{'quote': 2, 'fundflow': 1, 'timeline': 1}` | quote = basic + depth |
| 容量实值 | `coverage = int(0.8×tick×20/0.3)` | tick4 **213** / tick8 **426** / tick120 **6400**；`coverage_codes` tick4 quote **106** / 3 域 **53** |
| `refresh_epoch` | `_domain_refresh_epoch`（`ttl ≤ tick` ⇒ 本轮起点）+ `_call_refresh_handler`（纯增量 kwarg；仅调用帧 TypeError 降级） | 设定 tick 的域每拍真回源；慢域 `None` 交错 |
| 帧去重 | `_frame_signature`（blake2b 排 `ts`）+ 组级 `last_sig` + 连接级 `sent_any`；`last_push_ts` 仅真发送刷新 | 内容未变不发；未首发连接强制补发 |
| 空闲唤醒 / 冷首轮 | `_wake_event`/`_idle_sleeping`/`_wake_pending`/`_last_round_idle` + `_first_refresh_done`；`create_group`/`_serve_sse` 调 `_wake_push_loop()` | 仅空轮等待可打断；冷首轮不计 degraded/slip |
| 不变量订正 | `_tick_sleep_seconds` 注释（`L1000-1009`） | 真实不变量 = **轮起点→轮起点 ≥ 1 tick**（非帧到达间隔）；帧到达间隔 = `tick−dur_k+dur_{k+1}` |
| 帧契约只增 | `fetch_cls_basic_info` 附带 `result['depth']` | `items[code].quote` 可含 **`depth`（21 字段，L0 同拍）** |
| **⚠️ 发现的口径不符** | §4.2 **BR-STR-9** 原写"**先 `put_nowait` 成功、再 `_frame_acquire`**"，与代码（**先 `_frame_acquire` 后 `put_nowait`**，二次 Full ⇒ `_frame_release` 回滚）及本文件 §2.5/§5.4/§6.3#2/§7.5#4 **自相矛盾** | 已按代码更正 BR-STR-9；`sent_any`/`last_sig`/`depth`/`hashlib`/`cache_policy` 补入数据结构与 import 面 |

### 2. `stock_api.md` → **v1.3**（6 组同步项 → §10#21..26；偏差 20→**26**；测试 29→**39**）

| 主题 | 代码实况（`stock_api.py`） | 同步结论 |
|------|--------------------------|---------|
| `fetch_cls_stock_depth` | `L1053-1102`：`_STOCK_DEPTH_URL?secu_code=…&field=five`；**空 dict / 20 档全 0 ⇒ `None`**；失败非致命（不 raise） | 新增 `depth` 域取数器 + `_depth_store` + `_DEPTH_VALUE_FIELDS` + `_DOMAIN_STORES['depth']` + `_basic_depth_*` |
| `fetch_cls_basic_info` 三阶段 | `L958-1040`：阶段1 basic（致命）/ 阶段2 sector（非致命）/ **阶段3 depth**（非致命，只增 `result['depth']`） | 三阶段；阶段 1/3 传 epoch，阶段 2 留 TTL |
| 空壳防御 | `_basic_info_is_valid` + `_BASIC_INFO_KEY_FIELDS=('secu_name','last_px')` | `code:200` 但全空 / `data:{}` ⇒ **`upstream_error`**（不写缓存、不进阶段 2/3） |
| `upstream_secu_code` | **9 处**调用点（`_announcement_url` / fundflow / timeline / detail / basic p1 / basic p2 / depth / fundflow direct / timeline direct） | URL 构造全量应用；**北交所点号形 `430047.BJ`**；池/缓存/账本键仍 canonical |
| `BATCH_MAX_WORKERS` | `= config.BATCH_MAX_WORKERS` = **20** | v1.2 的 8 作废 |
| `refresh_epoch` | `_call_fetcher`/`_fetch_one`/`_run_batch`/`_process_chunk`/`_handle_cached_batch` + 3 handler 全贯通；终点缓存命中追加 `written >= refresh_epoch` | 全链路；`None` 逐字不变 |
| **⚠️ 发现的口径不符** | ① §5.1 import 块仍含 `socket` / `Request,urlopen` / `VALID_STOCK_CODE`，且 URL 仍写 `secu_code={stock_code}`；代码已迁移 | 已按代码更正 import 面与全部 URL；② 任务清单称"**10 处** x-quote URL"，实为 **9 处** `upstream_secu_code(` 调用点（announcement 签名 URL 被 REST + direct 两处复用） |

### 3. `server.md` → **v1.4**（4 组同步项 → §11.4；偏差 29→**31**；测试 43→**45**）

| 主题 | 代码实况（`server.py`） | 同步结论 |
|------|----------------------|---------|
| `main()` 预热线程 | `L1509`：`threading.Thread(target=warm_transport, daemon=True).start()`（`cache.warm_transport`；主机 `config.warm_hosts()`） | 新增 daemon 线程；**不阻塞启动/`/healthz`，失败静默**（总函数） |
| gzip 协商 | `_accepts_gzip`（`L541-568`，RFC 9110：`gzip;q=0` 拒绝、`GZIP`/`*` 接受）；`_send_text`（`L1249-1283`）gzip + `Vary` | `Vary: Accept-Encoding` 在 **`gzipped or cache`** 时无条件发（含 `cache=False` 的 gzip）；`GZIP_MIN_BYTES=1024`/`GZIP_COMPRESSLEVEL=1` |
| 已核对**无漂移** | 状态码（业务恒 200；`http_503_total` 计数点 3）、`_send_json` 无 `status`、`_json_payload_has_data` 已删、`_cache_age` 用 `urlparse`、`_parse_stock_codes`/`_rekey_batch_response`、4 面板 `quote` 域、longhu `broker_idx` 无条件自增、`request_queue_size=LISTEN_BACKLOG`、`BoundedThreadPoolServer(..., max_inflight=None)` | 与 v1.3 已同步口径一致，仅补 v1.4 两项 + 线程账 +9 |

**本轮销账**：v1.2 遗留的 `stream.md` 容量/去重类偏差、`stock_api.md` 的 import/URL/depth 类偏差、`server.md` 的 warm/gzip 类偏差**全部落笔**。**仍待编排层（不在本 agent 范围）**见下方「跨模块契约同步项」——**✅ 已由编排层完成（见顶部「★ 最终收口」§2）**。

## ★ v1.3 收尾契约同步（N1 回退 + AC-S3 裁决 + `_LOCAL_BUDGET` 裁决 · 以代码为准）

> 范围：**只改** `doc/detailed/{server,cache,config,market_api}.md` + 本文件。**未改代码、未改 SAD/PRD/其他详设。**
> 触发：编排层裁决落地后的"消除新一轮漂移"（代码已改，文档是旧口径）。

### 1. N1 回退：业务端点降级恢复 `200 + error 体` → `server.md` **v1.3**（7 组同步项 → §11.3 对照表；偏差 28→**29**；测试仍 43 条，`SRV-T36` 语义反转）

| 主题 | 代码实况（`server.py`） | 同步结论 |
|------|------------------------|---------|
| `_send_json_shape` | `L1141-1154`：`payload = _guard(fn, shape=_JSON_SHAPES[path])` → `self._send_json(payload, write_body=…, cache=cache)`——**无 200/503 判定** | 恒 **200 + 原样 error 体**；v1.2 的"error-only ⇒ 503"**作废** |
| `_json_payload_has_data` | **全仓 0 命中**（已删） | §2.9 内部辅助改为删除标注；§10#24 同步 |
| `_send_json` | `L1136`：`def _send_json(self, data, write_body=True, cache=True)`——**无 `status`** | 签名回落，恒调 `_send_text(200, …)` |
| `http_503_total` 计数点 | **3 处**：`server._reject_503`（L1340）、`/healthz`（L1039）、`stream._serve_sse`（stream.py L1011） | 同步为 **4→3**；`/healthz` 明确为**端点自身语义** |
| 降级体缓存 | `cache=cache`（不再 `and status == 200`） | 降级 JSON **可缓存**（按 `_CACHE_AGE_DOMAINS` 域 TTL） |
| 受影响落点 | — | §1.1#9 / §2.1（yaml + 状态表）/ §2.2 / §2.4 表 / §2.9 / §2.10 / §4.1 BR-SRV-5b / §4.5 BR-SRV-21 / §5.2 / §5.8（伪代码 + 表）/ §6.1 / §8 T24·T36 / §9 / §10#18·#24·#29 / §11.1·§11.3 |

### 2. AC-S3 裁决：探测预算封顶 5s → `cache.md` **v1.3** / `config.md` **v1.3** / `market_api.md` **v1.3**

| 文档 | 代码实况 | 同步条数 / 落点 |
|------|---------|----------------|
| `cache.py` | `L84` `_PROBE_BUDGET_CAP = 5.0`；`L154-174` `_probe_budget`：`budget=PROBE_TIMEOUT`，`while steps>0 and budget < _PROBE_BUDGET_CAP: budget = min(budget*2, _PROBE_BUDGET_CAP)`；`L177-187` `_fetch_budget`：无条目 / 已老化 ⇒ **`REQUEST_TIMEOUT`**（不经阶梯） | **6 处**：§1 头部+§1.1#1 / §2.1 四段式+行为表 / §2.5 兼容清单（新增 `_PROBE_BUDGET_CAP` 行 + 更正 `_probe_budget` 行）/ §3.1+§3.5 / §4.2 BR-CACHE-8·22 / §5.1 伪代码 / §8 T-CACHE-4·4c·4d·21 / §9 / §10#11 重写 + **#18 新增** / §11 |
| `config.py` | `L38` `PROBE_TIMEOUT = int(os.getenv('PROBE_TIMEOUT', '2'))`（**不变**）；封顶常量在 `cache` 侧，**未注册 env** | **2 处**：§2.3 `PROBE_TIMEOUT` 行脚注 + §10#18 新增 + §11（`PROBE_TIMEOUT` 默认值/env 面**零变更**） |
| `market_api.py` | 无改动；影响仅经 `cache._effective_timeout` 传导 | **1 处**：BR-MKT-11 封顶更正为 `_PROBE_BUDGET_CAP`（故障期 margin 单次回源 ≤5s；冷期/老化期 10s）+ §10#9 新增 + §12 变更记录 |

**推导（已写入 `cache.md` §10#11）**：持续黑洞稳态 ≈ `5s 探测 + 5s NEG_TTL = 10s` 周期，慢请求占比 ≈50% ⇒ **P95 ≈ 5s**（**与请求密度无关**，v1.2 的"低密度 ⇒ P95≈10s"退化消失）；单请求 ≤15s（AC-E2）恒成立。

### 3. `_LOCAL_BUDGET` 裁决（正式反转 REV-DES-15 裁决②）→ **本 agent 范围内无待改项**

- **代码实况**：`stock_api.py:81` `_LOCAL_BUDGET = '__local_budget__'`；`_process_chunk` 命中哨兵 ⇒ **不调 `_fail_ledger_record_failure`**（`L490`/`L500` 的分支互斥）。
- **文档实况**：`stock_api.md` **已在 v1.2（P7b）同步**——头部修订②、§1.1、§2.3 脚注、§3.1b、§4.2 BR-SA-34、§8 SA-T25/SA-T30、§10#14 均已是"**不入冷却账**"新口径。
- ⇒ **`stock_api.md` 无待同步项**（本项闭环）。**在范围内的四份文档不含该口径的旧表述**（`server.md` 只透传 `dropped`；`cache.md` BR-CACHE-23 的"本地等待预算 ≠ 上游失败"与新口径同源一致）。
- ⚠️ **仍需编排层承接（非本 agent 范围）**：SAD §2.3 D-6 的 `_fail_ledger` 条目 + PRD 侧"预算耗尽计入冷却账"的表述回改（`stock_api.md` §10#14 已登记）——**由编排层负责，本文件不再跟踪**（历史登记；其中"预算耗尽计入冷却账"已由 PRD v0.5 正式反转为"冷却只记真实上游失败"）。


## P7b 契约同步摘要（`server.md` → v1.2（★ 后由 v1.3 / N1 修订两处）/ `stream.md` → v1.2 · 以代码为准）

> ★ **历史快照（v1.2 时点）**：下表"error-only ⇒ 503 / `_send_json(..., status=200)`"两条**已由 v1.3 / N1 回退**（见「v1.3 收尾契约同步」§1）；**"容量模型 `2.2` / `coverage=23` / `coverage_codes` 23·11·7"已由 r5 复标定为 `0.3` / 213·426·6400 / tick4 **106·53**，且节拍改为最短订阅域 tier**（见上「r5 契约同步」§1 / `stream.md` §11.4）；其余条目仍有效。

> 依据：各批次落地 `>>DOC_SYNC` 标记。**仅改 `doc/detailed/{server,stream}.md` + 本文件**；未改代码、未改其他文档。

### stream.md（22 组同步项 → §11.3 对照表；偏差 17→28；测试 34→43）

| 主题 | 同步结论（代码实况） |
|------|--------------------|
| 帧格式（对外契约） | `{ts, codes_total, fields, items(全码, 可 null), missing, missing_count, errors?, stale?, stale_count?}`；`_build_frame` **仅 `codes` 为空**返回 `None` |
| last-known | `_carry_forward`/`_last_known`/`_clear_last_known`：未刷新码带旧值并标 `_stale`；池缩即裁剪 |
| `_refresh_pool` | 新签名 `(codes, now=None, fields=None, tick=None, deadline=None)`；按**订阅字段并集**刷新（`_subscribed_fields`/`_active_targets`/`_resolve_refresh_fields`）；超预算跳过剩余字段并标 `tick_budget_exceeded` |
| **容量模型（关键数值）** | ~~`_PER_FETCH_EST=2.2`、`_FIELD_FETCH_CALLS['quote']=1` ⇒ coverage=23；coverage_codes 1/2/3 域 → 23/11/7~~ **（v1.2 历史；r5 复标定见上「r5 契约同步」§1：`0.3` / quote=2 / 213·426·6400 / tick4 106·53）**；C1 门限 = `_fetches_per_code(fields)×n ≤ coverage` |
| 节拍 | 整 tick 网格滑移 `k=int((now−t0)//tick)+1`；异常退避 1/2/4…封顶 8 tick；**`_TICK_MIN_SLEEP_FRACTION` 已删** |
| lag gauge | 空池发布 0（`_push_once` 空池分支）；C1 ⇒ 0；C2 ⇒ `ceil(n/|slice|)` |
| 准入 | `projected + largest ≤ budget`（单帧余量 ⇒ 满配组容量 **9→8**）；超限 400 `_FRAME_BUDGET_ERR`；`MAX_GROUPS=200` 超限 400 |
| 字段/码校验 | `_valid_fields` **fail-closed**（显式非法字段 → 400）；码归一走 `config.canonical_code`（本地 `VALID_STOCK_CODE` 引用已删） |
| HTTP | POST/PATCH 非 list → 400、非 object body → 400；201/PATCH 200 增 `refresh_capacity_codes`/`refresh_lag_ticks`/`capacity_warning`；`patch_group` 锁内复读组存活；`do_PATCH` 容忍 `None` → 404 |
| SSE/收口 | `Connection: close` + `close_connection=True`；`log_error` 抑制超时日志；`_broadcast` 先滤 `closed`；`_frame_acquire` **先于** `put_nowait`；`SubscriptionGroup.payload_bytes()` **已删** |
| 端口 | `make_stream_server` 具名 `_MGMT_WORKER_RESERVE=10`（`max_workers = max_inflight = MAX_STREAM_CONNS+10`）；`_serve_sse` 超限计 `http_503_total` |

### server.md（16 组同步项 → §11.1 对照表；偏差 17→28；测试 35→43）

| 主题 | 同步结论（代码实况） |
|------|--------------------|
| **error-only ⇒ 503** ⚠️ **已于 v1.3 / N1 回退** | ~~新增 `_json_payload_has_data`；触发面 = 4 CDP 面板 / hotplate 全分区失败 / margin `_error` / guard 捕获体 ⇒ **503**（原 200）并计 `http_503_total`~~。**现口径（v1.3，以代码为准）**：`_json_payload_has_data` **已删除**；`_send_json_shape` **恒 200 + 原样 error 体**（降级体 `cache=cache` ⇒ 按域 TTL 可缓存）；`_send_json` **无 `status` 形参**；`http_503_total` 计数点 **4→3**（`_reject_503` / `stream._serve_sse` / `/healthz`）；`/healthz` 的 503 属**端点自身语义**，不构成业务端点先例。`_send_json_shape(path, fn)` 表驱动派发不变。**`/cls/plate` 恒 200**（同前） |
| `/healthz` | `BoundedSemaphore(MAX_HEALTH_INFLIGHT)` + `_HealthBatch`（`task_done` + **`settle()`**）；先建账再调用 + `except BaseException: settle(); raise`；`_run_health_checks(base_url, batch=None)`；payload 缺 `status` 或含 `error` ⇒ **503**（计入 `http_503_total`） |
| 扇出 | `_fanout_executor(_FANOUT_MAX_WORKERS=3)` + `_fetch_concurrent` 等待受 **`_FANOUT_WAIT_BUDGET=REQUEST_TIMEOUT`** 界（超期 cancel + `FetchError('upstream_timeout')`） |
| `_guard` 全路由 | 14 JSON（表驱动）+ 5 RSS + `/healthz`；`_JSON_SHAPES` + `_PANEL_HANDLERS` + `_JSON_DISPATCHED_PATHS` 导入期断言 |
| feed/plate | feed 双检保留（`ttl` 在二次 get 仍 miss 后求值）；plate stagger 保留（`_plate_ttls`） |
| `_base_url`/`_cache_age` | `PUBLIC_BASE_URL` 优先；否则 Host 格式校验 + `Vary` + `Cache-Control: private`；`_cache_age` 用 `urlparse(self.path).path` |
| **面板 cache-age（新发现漂移）** | 4 面板已注册到 `_CACHE_AGE_DOMAINS` 的 **`quote`** 域（~~8/120~~ **★ v1.16 更正：现行 4/120**，`quote` 于 v1.4 升 L0），**非** `_DEFAULT_AGE_DOMAIN('f10')` 的 300 —— v1.1 文档口径已更正 |
| **码归一（新发现漂移）** | `/stock/*` 走 `_parse_stock_codes`（canonical 折叠去重）+ `_rekey_batch_response`（响应键回原拼写）；截断按归一后码数；非法码值 ⇒ 逐码 `null`（**非** 400），400 仅缺/空 `?code=` |
| **margin 400（新发现漂移）** | `/market/margin` 非法 `market` ⇒ **400**（`VALID_MARKETS` 前置校验，guard 之前） |
| 其他 | ~~`_send_json(..., status=200)`~~（**v1.3 / N1 撤销**：无 `status`，恒 200）；`do_GET`/`do_HEAD` 断连捕获扩为 `OSError`；`request_queue_size = LISTEN_BACKLOG`；longhu `broker_idx` **无条件自增** + 错位告警、encoding 取自 `cache_policy('longhu')['encoding']`；import 面更正 |

### 销账（v1.1 遗留「编排层同步项」）

1. ✅ **`CACHE_TTL` 同批删除**：`config.py` 已无 `CACHE_TTL`；`server.py` 的 healthz `cache_ttl` / feed expires / 启动日志全部改读 `cache_policy('feed')['ttl']`（grep 0 命中）。
2. ✅ **`canonical_code` 落地**：`config.canonical_code` 已是唯一码归一权威；`stream.py` 删除本地 `VALID_STOCK_CODE` 引用，`server.py` 新增 `_parse_stock_codes`/`_rekey_batch_response`。
3. **✅ 已由编排层完成（本轮核实 · 2026-09-18；原记：⏳ 仍待编排层，不在本 agent 范围）**：`feeds[].status` 3 处取值 + 首页 CDP 列 → `API.md:499-511`；`POST /stream/subscriptions` 的 `MAX_GROUPS=200` 超限 400 与 **v1.2 新增的「帧预算 cap 400 / 面板 max-age ~~8·120~~ **4/120（`quote` 于 v1.4 升 L0；现行口径见 `API.md`:619-631）** / margin 400」** → `API.md:541` / `:529` / `:724`（★ v1.3：**已剔除 error-only 503——N1 回退，业务端点恒 200，无需外部同步**）；SAD 措辞回改（`handle_cls_*` 返回组装 dict）→ SAD §2.4；★ 另可选（`_PROBE_BUDGET_CAP=5s` 与 P95 ≈ 5s 口径）→ SAD §2.3 / §9.5 已回填（v1.5）。

## 批次 2 交付摘要（数据层三模块，v1.0）

| 模块 | 核心接口变更 | 关键约束落实 |
|------|-------------|-------------|
| `stock_api.py` | 6 码级 `fetch_*(code, deadline=None, ttl=None)`（+3 直连）；`_run_batch/_process_chunk/_handle_cached_batch` → `(results, errors)`；`handle_cls_*(codes, deadline=None, dropped=0) -> dict`（内部 `build_batch_response`）；`_fail_ledger`（码级 120s 冷却，批量+prefetch 共用）；`cached_batch/_prefetch_slice` 新增 | deadline 贯通（R13）、TTL 同源同变量（INV-1a 落点 2）、池淘汰不再 `cache.pop`（P1-1）、删裸 `ttl=15`（Q5）、sector 接 policy |
| `market_api.py` | `fetch_margin(market='99', deadline=None)`；`_MARGIN_CACHE_TTL` → `cache_policy('margin')['ttl']`；`_error` 由自由文本收敛为枚举 kind | R16、`FetchError` 分类 + 防重复计数（BR-MKT-8） |
| `cdp_engine.py` | `page_data(page)`（R18 防御取数，总函数）；重启窗口状态机 `idle/restarting/unavailable` + `restart_window_snapshot()`；`watchdog_restart_skip_reason()`（盘中避让 ADR-012 集中判断）；`cdp_ready()`；`_heartbeat_interval` 改调 `config._is_trading_hours` | R18/R19/R20、AR-12、`cdp_restart_window` metrics |

## 批次 3 交付摘要（上层两模块，v1.0）

| 模块 | 核心接口变更 | 关键约束落实 |
|------|-------------|-------------|
| `server.md` | `_guard(fn, *, shape, requested, dropped, rss_info, feed_url)`（4 shape）；`_JSON_SHAPES`（14 项 + `assert`）；`_handle_stock_batch(parsed, handler, write_body)` 透传 `dropped`；`_get_or_fetch_feed` 双检；`build_health_payload(base_url, check_sources)`（签名不变）；`BoundedThreadPoolServer._max_inflight = MAX_INFLIGHT`；`_cache_age` 接 policy；`_plate_ttls()`；`_send_error(msg, write_body)` | `_guard`×14 JSON + 5 RSS + healthz；feed 双检（miss→per-path lock→**二次 get**→fetch→put）；healthz `BoundedSemaphore(MAX_HEALTH_INFLIGHT=5)` 有界准入（stale 可达）+ check=0 零上游 + 精确 schema（既有 4 键 + `stale`/`metrics`/`policy`/`cdp`）；plate `_STAGGER=max(3, ttl//4)` 三档保留；longhu 走 `fetch_json(encoding='gbk')`×2 URL（L4=300）；dropped 单组装点；503 计数 |
| `stream.md` | `codes→frozenset`、`fields→tuple`；`_build_frame(snapshot, codes, fields)`（**签名变更**）；`_Frame{payload,size,sid,refs}` + `_frame_bytes_lock` + `_frame_acquire/release` + `_reserve_for` + `_drain_conn_queue` + `_pop_oldest_frame`；`_refresh_pool(codes, now=None)` 分片轮转；`_release_conn(conn=None)`；`create_group` 校验 `MAX_GROUPS`；`_read_json_body` 5s | distinct 帧计费（`stream_queue_bytes` = Σ refs>0 帧字节，只计一次）；关闭/入队竞态双时序收口（put 后复检 `closed`）；确定性丢弃（`_group_bytes` 最大组 × 最满连接 × 队首）+ 先腾位后入队（不丢最新）；分片 `|slice| ≤ coverage_codes`（★ v1.0 历史：盘中 56 / 非盘 853；**r5 后为随 tick/字段动态值**，见上「r5 契约同步」§1）游标键 `stream_refresh` + `cached_batch` 并帧 + lag 指标；**跳过 `_` 前缀键（AR-7）**；`MAX_GROUPS` 400 |

## v1.1 修订摘要（数据层三模块，REV-DES-20260915-002）

> 依据 `doc/review/数据层三模块_详细设计评审_专家版.md`（结论 ✅ 通过，P0×0 / P1×2 / P2×10）。**仅改 `stock_api.md` / `market_api.md` / `cdp_engine.md`（+ 本文件）——未动 SAD / PRD / 代码。**

| 项 | 模块 · 位置 | 处理 |
|----|-------------|------|
| **P1 REV-DES-10** | `stock_api.md` §1.3/§1.4/§2.1#3/§5.9 | §1.3 允许列表补 `cdp_engine（page_data）`、禁令移除 `cdp_engine`（限 `page_data`）；§1.3 依赖图补 `stock_api → cdp_engine`；§1.4 补 `cdp_engine.page_data(page) -> dict\|None` 行；§5.1 补 `from .cdp_engine import page_data`；§2.1#3/§5.9 口径统一 ⇒ **编码不再违反自带 layerIsolation** |
| **P1 REV-DES-11** | `market_api.md` §10#1 | **设计不变**（保 `{latest, recent, _error}`）；§10#1 改为裁决回执：「编排层已裁决：设计保持，PRD AC-A5 margin 表述将回改」 |
| REV-DES-12 | `stock_api.md` §5.9 | 抽 `_raise_cdp_unavailable()`（计数 + 抛出），4 处出口收口 ⇒ `upstream_fail_total{cdp_unavailable}` 不再少计 |
| REV-DES-13 | `stock_api.md` §5.2 | `_fetch_rest_json` 捕获**非 FetchError** 时就地计 `upstream_error`（cache 抛出的不重复计） |
| REV-DES-14 | `stock_api.md` §5.2 | `_fetch_rest_json` 前置 `isinstance(raw, dict)`，非 dict ⇒ 计一次 + `FetchError('upstream_error')`（与 market_api 对齐） |
| REV-DES-15 | `stock_api.md` §2.3/§4.2/§10#14、§8 SA-T25 | **采用评审建议②**：保留"预算耗尽计入冷却账"现口径 + 补用例 SA-T25 + §10#14 登记影响（AC-S6 张力）；**不引入内部哨兵**（避免动 SAD 钉死的 `_run_batch (results,errors)`） |
| REV-DES-16 | `stock_api.md` §2.8/§5.11 | `_prefetch_loop` 新增 `per_call_budget`（默认 `REQUEST_TIMEOUT`）；单次调用传 `deadline=min(pass_deadline, now+per_call_budget)`；`_f10_prefetch_loop` 传 `per_call_budget=_PREFETCH_CDP_CALL_TIMEOUT`（lambda 移除，直传 `fetch_cls_f10`） |
| REV-DES-17 | `stock_api.md` §3.4/§4.5/§6.2/§9 | ≤15s 引据由 **AC-S7 → AC-E2**（REST 回源上界）；`_CDP_CALL_TIMEOUT` 引据保留 AC-S7 超时矩阵 |
| REV-DES-18 | `stock_api.md` §5.9/§10#15 × `cdp_engine.md` §2.1/§8/§10#9 | **统一钉死**：全部已导航页 `page_data=None` ⇒ `cdp_unavailable`；仅"有 dict 数据但不匹配"⇒ 返回 `None`。两文档同步 + CDP-T13/SA-T28 |
| REV-DES-19 | `cdp_engine.md` §4/§5.1/§5.4/§8/§10#10 | 模块加载即 `_publish_window()` 发布初始 idle 快照 ⇒ `metrics.snapshot()` 恒含 `cdp_restart_window`（CDP-T9 扩断言） |
| REV-DES-20 | `market_api.md` §4 BR-MKT-8 / §10#5 | owner 引据改为"本模块与 cache 的防重复计数约定"；`metrics.md` §3.2 owner 列补 `market_api` **由编排层同步**（本 agent 不改基础层文档） |
| REV-DES-21 | `stock_api.md` §3.4/§4.5/§10#10 | **编排层裁决：接受现状 + 风险登记**（f10 非热路径）；引据更正为 AC-E2；遗留风险 = `/stock/f10` 多码可达 60s，建议 `server.md` 强制"仅单码/少量码" |

**7 项登记项裁决回执（①-⑦，全部批准/接受）**：① handler 返回组装 dict（批准）→ `stock_api §10#1`；② 4 元 ledger（批准）→ §10#2；③ 第 3 参数 `ttl`（批准）→ §10#3；④ `/stock/data` 与 basic_info 共冷却账（接受）→ §10#4/4b；⑤ 池上限 2000（批准）→ §10#5；⑥ f10 60s（接受 + 登记）→ §10#10；⑦ 分片轮转属 stream（批准）→ §10#9。

**本批 v1.1 引出的「编排层同步项」**（**不在本 agent 范围**，须由编排层执行）——**由编排层负责，本文件不再跟踪**（SAD/PRD 相关回填已随 **SAD v1.11 / PRD v0.9** 收口，见顶部「★ 最终收口」§2；其余项按各自承接方处理）：
1. **SAD §3 依赖方向 + `tech-stack.json`**：登记同层依赖 `stock_api → cdp_engine`（无环；REV-DES-10）。
2. **PRD AC-A5**：回改 `/market/margin` 表述（保留 `_error` 枚举客体，作为"单体 error 客体"显式子类）并写入验收矩阵（REV-DES-11）。
3. **`metrics.md` §3.2**：`upstream_fail_total` owner 列补 `market_api`（REV-DES-20）。
4. **SAD §2.4**：措辞回改为"管道层返回二元组，handler 交 `build_batch_response` 组装为 dict"（登记项①）。
5. **SAD §2.3 D-6**：`_fail_ledger` 条目同步为 4 元（登记项②）。
6. **`server.md`**：落实"`/stock/f10` 仅单码/少量码"约束（当前未强制；REV-DES-21 缓解项）。

## Step 2.5 链式推导结论（批次 3，7 规则逐条）

| 规则 | 结论 |
|------|------|
| 规则零（需求缺口） | **无新增对外 HTTP 接口**（端锁定 🟠 STABLE）。唯一新增失败模式 = `POST /stream/subscriptions` 的 `MAX_GROUPS` 超限 400（**SAD §7.1 P2-N7 已登记**，✅ 已由编排层同步（`API.md:541`）；worker 内部函数新增：`_guard`/`_reserve_for`/`_drain_conn_queue`/`_frame_acquire|release`/`_pop_oldest_frame`/`_run_health_checks`/`_check_one_feed`/`_health_executor` 等）→ **无需用户确认**（无新端点、无新方法与参数） |
| 规则一（读写配对） | 流端口 `PATCH`/`DELETE /stream/subscriptions/<sid>` 均有对应 `GET /stream/subscriptions/<sid>`（组状态）→ 读写配对完整；主端口全为 `GET`/`HEAD` |
| 规则二（状态机） | ①**帧引用计数状态机**：`refs 0→1`（入队成功，计费）→ `refs 1→0`（出队消费 / 丢最旧 / 预算驱逐 / 排空，归还）；幂等（`refs<=0` 直接返回）。②**连接生命周期**：`_register_conn`（≤100）→ **复检组存活**（销毁 vs 注册，修 P2-7）→ 挂组 → `closed` + 哨兵 → `finally` 排空 + `_release_conn`；销毁路径 = `destroy_group`（置 closed→投哨兵→clear→**锁外排空**）。③**组生命周期**：created → live（有连接）→ zombie（无连接，不建帧）→ `_sweep_idle_groups`(>300s) 回收。④**healthz 准入状态**（v1.1 修 P1-1）：acquire 成功 → 批任务在飞（`healthz_inflight` 保持 >0，**准入位不归还**）→ 该批 5 个 future 全部结束 ⇒ `_HealthBatch.task_done` 归零 ⇒ `_release_health_slot()`（恰好一次）；失败 → stale 路径（不 acquire 即不 release）。⑤**CDP 重启窗口**（cdp_engine，本批只消费）。 |
| 规则三（跨模块依赖） | 依赖方向 `config‖metrics ← cache ← stock_api/market_api/stream ← server`；`stream → stock_api`（同层，既有）扩展至 `cached_batch`/`BATCH_MAX_WORKERS`/`_prefetch_slice`/`_prefetch_advance`；`server → stream` 仅 main() 延迟 import（破环）；反向禁止。逐模块 `layerIsolation` 写入详设 §1.3 |
| 规则四（数据生命周期） | ①**feed 条目**：miss→锁→双检→fetch→put（成功才写；失败不缓存）；LRU/清扫/淘汰在 cache 层。②**帧对象**：`_broadcast` 建 → 入队（refs+1）→ 帧构建/入队/出队/丢弃/排空/销毁六路径均收口；`None` 哨兵不计费。③**组/连接**：见规则二。④**healthz 快照**：成功组装才刷新（准入失败路径不刷新，防 stale 自覆盖）。 |
| 规则五（异步流程） | `push_loop` 单后台线程（同步 `sleep(delay)` 无任务状态查询/无死信——无外部存储）；healthz 专用执行器（5 worker，懒创建，`wait(FIRST_COMPLETED)` 轮询 + 两级预算）；4 条 prefetch loop 属 stock_api。**无新增任务队列/存储** |
| 规则六（权限/隔离） | 无鉴权/多租户（PRD §6）；`layerIsolation` 逐模块写入 §1.3；`server`/`stream` 均未在 tech-stack 单列条目，按分层方向 + allowlist 约束 |


## v1.1 修订摘要（REV-DES-20260915-001）

| 项 | 位置 | 处理 |
|----|------|------|
| **P1 REV-DES-01** | `cache.md` §2.6 #6–#9 | 现状列改 `_BASE_TTL(=L2)+offset`；目标列补「+ handler 派生 stagger」；加脚注钉死 `_STAGGER=max(3, ttl//4)`、offset=分区序、等价 ×1/1.25/1.5；落点由 `server.md` 承接 |
| REV-DES-02 | `cache.md` §5.2/§7.3 × `metrics.md` §3.2 | 补 `cache_hit_ratio=round(hit/(hit+miss),4)`（分母 0→0.0）+ `_cache_put` 唯一发布行；统一 `_cache_stats{hit,miss}`，明确**不存在** `cache_hit_total/miss_total`（三处一致） |
| REV-DES-03 | `cache.md` §1.3/§5.1 | 允许 import 补 `logging`；补 `log = logging.getLogger('cache')` |
| REV-DES-04 | 三份依赖图 | 澄清 `←`=分层顺序**非 import**；`config` 与 `metrics` 并列 Layer 0 叶子、互不依赖 |
| REV-DES-05 | `metrics.md` §7.4 | 统一为「`_warn_once` 就地调用（锁内/锁外均可），`_warned` 容忍竞态，不引入第二把锁」 |
| REV-DES-06 | `config.md` §2.4/§10#10 | `_BASIC_INFO_MAX_POOL` 500→2000 **行为变更登记**（联动 S9/AR-8；护栏改由端点 LRU 承担） |
| REV-DES-07 | 三份头部 | 补版本/状态/日期/作者元数据（v1.1） |
| REV-DES-08 | `config.md` §2.3 | 补注：AC-S3 模式 B 的 `2s+5s` 口径**以 NEG_TTL=5 为前提**，env 覆盖须重跑校准 |
| REV-DES-09 | `cache.md` §5.1 | `_cache_put`/`_clear_negative` **移出网络 fetch 的 try**（单独 try/log，不落负缓存），且保证先于 `event.set()` |
| 逆向 1 | `cache.md` §4.2/§3.1/§5.1/§10#11 | 新增**失败历史老化**：`NegEntry.first_at` + `_HISTORY_AGE=600s` → 老化时本次用 `REQUEST_TIMEOUT` 全预算（BR-CACHE-20）；量化保证任一 5min 窗口至多 1 次升级探测（≤1.2% <5%）⇒ AC-S3 P95 仍 2s |
| 逆向 2 | `config.md` §2.4 | 补**删除前置条件**：常量删除须与消费者迁移同 change-set；消费者详设未出前**不得单独提前删** |
| 逆向 3 | `metrics.md` §8/§10#6 | MET-T8 加强为 (a) 单元 + (b) **CI 级断言 `set(snapshot()) ⊆ _KNOWN`**；§10 说明"冻结=文档契约，运行时仅告警" |

> 偏差登记：`config.md` §10 补 D-4 `STREAM_PING_INTERVAL`、D-5 `_DOMAIN_ENCODING`；`cache.md` §10 补 D-1 gap 分支、D-2 防御细化、D-3 socket、D-7 plate stagger、逆向 1、REV-DES-09；`metrics.md` §10 补 D-6 `upstream_fetch_total`、逆向 3、依赖图、`_warned`。SAD 侧由 system-architect 回填（D-1~D-7）。
- 文件：`doc/detailed/config.md`、`cache.md`、`metrics.md`（+ 本文件）——**未动 SAD / 代码**

## Step 2.5 链式推导结论（本批相关）

| 规则 | 结论 |
|------|------|
| 规则零（需求缺口） | 无新增对外接口；仅内部函数新增（`cache_policy`/`build_batch_response`/`FetchError`/`feed_cache_get|put`/metrics 四函数） |
| 规则一（读写配对） | 不涉 HTTP 方法；`save/delete` 语义不适用 |
| 规则二（状态机） | 负缓存状态机：`无历史 → 失败(落负缓存) → 门禁期(快速失败) → 半开(未老化 2s / 老化 ≥600s 时 10s 全预算探测) → 成功(清历史)`；3 个 FetchError kind 枚举封闭 |
| 规则三（跨模块依赖） | 已锁定下游契约（见下「必须对齐的跨模块接口」） |
| 规则四（数据生命周期） | 负缓存条目生命周期：成功即清 / 满 2000 淘汰最早 `until` / **不因过期而清**（AC-S3 前提）；`first_at` 老化窗口 600s 触发一次全预算探测（BR-CACHE-20） |
| 规则五（异步流程） | 本层无异步任务；`_fetch_inflight` leader/follower 为同步等待（follower 不重入选举） |
| 规则六（权限/隔离） | `layerIsolation` 已逐模块写入详设 §1.3；无鉴权需求 |

## 必须对齐的跨模块接口（下游批次不得偏离）

- **stock_api**：`_process_chunk(..., ttl=, cache_max=)` 与传给 `fetch_json(ttl=)` **同源同变量**；`_run_batch` → `(results, errors)`；`handle_cls_*` → `cache.build_batch_response(...)`；`_fail_ledger`（码级 120s，ADR-014）；`fetch_cls_f10` raise `FetchError('cdp_unavailable')`；删 `_SECTOR_CACHE_TTL` 改 `cache_policy('sector')['ttl']`。
- **server**：`_handle_stock_batch` 计算 `dropped` 并传 `build_batch_response(..., dropped=)`（不重复组装）；`_get_or_fetch_feed` 改调 `cache.feed_cache_get/put` 并保留 `_feed_fetch_locks` 防击穿（**必须双检**：miss→取锁→**再次 `feed_cache_get`**→fetch→put）；healthz `cache_ttl` 读 `cache_policy('feed')['ttl']`；`/ths/longhu` 走 `fetch_json(..., encoding='gbk')`（2 个新调用点）；**plate 三档 stagger 承接**：`_STAGGER = max(3, cache_policy('plate')['ttl']//4)`，offset = `_STAGGER × 分区序`（REV-DES-01，严禁四调用点同 TTL）。
- **stream**：`_refresh_pool` **必须跳过 `_` 前缀键**（AR-7）；metrics 名按 `metrics.md` §3.2 注册表。
- **market_api**：`_MARGIN_CACHE_TTL` → `cache_policy('margin')['ttl']`。
- **tests**：`test_fetch_json_leader_failure_does_not_stampede` 按 AR-10 改写（`err=8`/`max_active=1`/<1ms）。

## ★ 跨模块接口约定（批次 2 锁定；`stream.md` / `server.md` 不得偏离）

### A. `stream.md` 依赖 stock_api 的 refresh 接口（本批已提供）

1. **批量 handler 返回"已组装 dict"**：`handle_cls_basic_infos / handle_cls_fundflow / handle_cls_timeline(codes, deadline=None, dropped=0) -> dict`。
   - 返回体可能含保留键 `_errors`（失败码非空时）⇒ `_refresh_pool` **必须跳过 `_` 前缀键**（AR-7 陷阱点；否则把 `_errors` 当股票塞进帧）。
   - `_FIELD_HANDLERS = {'quote': handle_cls_basic_infos, 'fundflow': handle_cls_fundflow, 'timeline': handle_cls_timeline}` **不变**。
2. **分片轮转（AR-1 / INV-1b）在 `stream.py` 实现**，stock_api 只提供原语与常量：
   - `stock_api.BATCH_MAX_WORKERS = config.BATCH_MAX_WORKERS = 20`（计算 coverage 用）。
   - ⚠️ **r5 覆盖（以代码为准）**：`coverage = max(1, int(0.8 × tick × BATCH_MAX_WORKERS / _PER_FETCH_EST))`，`_PER_FETCH_EST = config.STREAM_PER_FETCH_EST = 0.3` ⇒ **coverage = tick4 213 / tick8 426 / tick120 6400**（随 tick **线性增长**，非恒值）；`coverage_codes = coverage // _fetches_per_code(fields)`（`_FIELD_FETCH_CALLS['quote']=2`：basic + depth）⇒ **tick4 quote-only 106 / 3 域 53**。旧口径 `≈170/≈56` 与 v1.2 的 `23/23·11·7` **均已作废**（BUG-P6C-06 + BUG-SSE-DEPTH-01；见 `stream.md` §3.3/§10#15·#21）。
   - ★ **节拍 + wire 拼写（v1.3）**：`tick_interval(fields)` = 最短订阅域 tier（quote/depth L0 盘中 **4s**；无订阅 L1）；URL 构造一律 `config.upstream_secu_code`（SH/SZ 前缀形；**BSE 点号形 `430047.BJ`**），池/缓存/账本键仍 canonical。
   - ★ **`refresh_epoch`（v1.3）**：`stream._refresh_pool(..., now=本轮起点)` 对"设定 tick 的域"传入新鲜度下限 ⇒ 每拍真回源；`stock_api` 全链路透传（终点缓存命中追加 `written >= epoch`，`cache.fetch_json` 第 6 位形参）。
   - 条件 `C1: _fetches_per_code(fields) × N_active ≤ coverage ⇔ N_active ≤ coverage_codes` 成立 → 整池一周期刷新（**lag=0**）；否则分片：`|slice| ≤ coverage_codes`。
   - 游标：`stock_api._prefetch_slice(pool=None? ...)` **仅适用于有 pool 的域**；stream 的活跃码集来自 `_active_codes()`（非 pool），故 stream 用 **同一 round-robin 语义**自行维护游标键 `'stream_refresh'`（可复用 `_prefetch_rotate` 的思路；如需公共游标可调 `_prefetch_advance('stream_refresh', ...)`，该函数按 key 通用）。
   - 未进切片的码：`data = stock_api.cached_batch(field_domain, rest_codes)`（无网络读终点缓存）；
     `quote→'quote'`、`fundflow→'fundflow'`、`timeline→'timeline'`；`snapshot = fresh(slice) ∪ cached(active−slice)`。
   - 记录 `stream_refresh_lag_ticks = ceil(N_active / |slice|)` 与 `stream_tick_degraded_total`（metrics 名已冻结）。
3. **warm 码帧完整性不降级**；冷码在 ≤ lag tick 内进入（AC-A1 以 warm 稳态 + 200 帧窗口为前提）。

### B. `server.md` 依赖 stock_api / market_api / cdp_engine

- `server._handle_stock_batch`：截断后把 `dropped` 作为**参数**传给 handler：`data = handler(stock_codes, dropped=dropped)`；**不得**再次调用 `build_batch_response`（组装点唯一）。
- `/market/margin` → `handle_margin(market)`：签名不变。
- A/A′/B 降级形态：A 类（面板 4）用 `cdp_engine.page_data(page)`；`timeline` 为 `None` 时返回 `{'error': ...}`（**禁止**裸 `null`）；A′（`/stock/f10`）由 `fetch_cls_f10` 的 `cdp_unavailable` 经 `_errors` 承载。
- `_cdp_memory_watchdog`（`server.py:881`）：本轮判断改为 `reason = cdp_engine.watchdog_restart_skip_reason(); if reason: continue`（**盘中避让 + 节流判断已集中在 cdp_engine**）。
- `/healthz` 的 `cdp` 字段 = `cdp_engine.restart_window_snapshot()`；`metrics` = `metrics.snapshot()`。
- config 常量删除仍须与 `server.md`/`stream.md` 同 change-set（本批 stock_api/market_api/cdp_engine 已迁移其消费者；**server/stream 的消费者未动，故仍不得单独删常量**）。

### C. `market_api` 落地清单（本批）

- `market_api.py` 删除 `_MARGIN_CACHE_TTL` import，改 `cache_policy('margin')['ttl']`；新增 `metrics`/`FetchError` import；`_error` 值域收敛为枚举 kind。
- 与 `config.md` §2.4 的 `_MARGIN_CACHE_TTL` 删除行**同 change-set**。

## 待确认项 → 编排层裁决（**已闭环，6/6**）

| # | 待确认 | 编排层裁决 | 详设落点 |
|---|--------|-------------|---------|
| 1 | `cache_policy` 返回值中 `'n/a'` 是否保留字面量 | ✅ 批准：归一化为 `None`（矩阵保留 `'n/a'`） | `config.md` §2.1/§10#4 |
| 2 | 负缓存"过期即清" vs 半开探测需失败历史 | ✅ 批准：门禁过期失效、条目保留作失败历史（**AC-S3 模式 B 必要条件**） | `cache.md` §4.2 BR-CACHE-8 / §10#1 |
| 3 | feed LRU 落点 | ✅ 批准：机制落 `cache.feed_cache_get/put`，server 保留防击穿（**须双检**） | `cache.md` §2.4 |
| 4 | metrics 是否允许新增 `key=`/`reset()` | ✅ 批准（向后兼容） | `metrics.md` §2/§10#3 |
| 5 | `cache_hit_ratio` 发布点 | ✅ 批准：`cache._cache_put` 派生发布（**须补实现**） | `cache.md` §5.2/§7.3；`metrics.md` §3.2 |
| 6 | `STREAM_PING_INTERVAL` env 化 | ✅ 批准：env 化，默认 20 不变 | `config.md` §2.3 / §10#8（D-4） |

> SAD 侧待回填（由 system-architect 承接，**不在本 agent 范围**）——**✅ 已由编排层/system-architect 完成（SAD v1.11；见顶部「★ 最终收口」§2）**：§4.3"过期即清"措辞、feed LRU 落点、§2.1 `'n/a'`→`null` 示例、§2.6 补 `upstream_fetch_total`、§3 config 行补 `STREAM_PING_INTERVAL`、Q3②/AR-6 消费者与负载增幅更正。

## 详设清单（模块详设 8 份 + 规则文档 2 项 = N/A）

| # | 文档 | 状态 |
|---|------|------|
| 1 | `doc/detailed/config.md` | ✅ **v1.5（批次 1 → v1.1 → P7b v1.2 → AC-S3 v1.3 → ★ 传输/容量 env v1.4 → ★ 溯源更正 v1.5）**（`PROBE_TIMEOUT` 脚注更正：阶梯封顶 = `cache._PROBE_BUDGET_CAP=5.0`；★ v1.4 补登 `BATCH_MAX_WORKERS=20`/`STREAM_PER_FETCH_EST=0.3`/`HTTP_POOL_*`/`HTTP_DNS_CACHE_TTL`/`HTTP_WARM_*`、L0 档 + `quote`→L0 + `depth` 域、`upstream_secu_code`、`warm_hosts()`；§10#19..23；★ **v1.5：头部溯源由 SAD v1.2 / PRD v0.3 更正为实际 `SAD v1.11 / PRD v0.9`（最后一处溯源滞后闭环；接口/常量/env/行为零变更）**）**——**版本以文档头部为准** |
| 2 | `doc/detailed/cache.md` | ✅ **v1.13（批次 1 → v1.1 → P7b v1.2 → AC-S3 v1.3 → ★ 传输层 v1.4 → ★ P3a v1.5 → ★ P3a-r1 v1.6 → ★ P7b 回填 D-3 v1.7 → ★ P8 F1/F5 v1.8 → ★ P8 F8 v1.9 → ★ P2-1 fail-safe + 溯源 v1.10 → ★ 读侧 fail-safe 补全 + acquire 实现约束 v1.11）**（v1.4：`_ConnectionPool` + `_DNSResolver` + `cache.urlopen` 打桩缝 + `warm_transport` + `fetch_json` 第 6 位 `refresh_epoch`（BR-CACHE-31）；v1.5：`feed_cache_get_entry` 访问器（BR-CACHE-32）供 RSS Last-Modified；`feed_cache_get` 签名/语义不变；★ **v1.6（P3a-r1）：T-CACHE-32 扩浅拷贝隔离负例 + 头部溯源 SAD v1.7/PRD v0.6**；★ **v1.7（P7b 回填 D-3）：T-CACHE-32 标注 ✅ 已实现 = `tests/test_cache.py::FeedEntryAccessorTests::test_t_cache_32_shallow_copy_isolates_the_container`；无实现/契约变更**；★ **v1.8（P8 F1/F5）：feed 条目 `fingerprint`/`last_modified` + `feed_cache_put` 返回写入条目（BR-CACHE-33/34）**；★ **v1.9（P8 F8）：`feed_fetch_acquire`/`feed_fetch_release` + `_feed_fetch_refs` 引用计数原语（BR-CACHE-35）、§2.4 双检措辞更正为 `feed_cache_get_entry`、头部溯源 SAD v1.9**；★ **v1.10（P2-1 fail-safe + 溯源）：`last_modified` 读 `entry.get`/`prev.get(..., None)`（legacy / 非六字段条目 ⇒ `None` ⇒ 不发 `Last-Modified`、禁用 IMS，不抛 `KeyError` 经 `_guard` 变降级体）、BR-CACHE-33 口径收口（无 BR 语义变更）、§8 T-CACHE-32/33 补负例、§10#27、头部 PRD v0.6 → v0.8**；★ **v1.11（读侧 fail-safe 补全 + acquire 实现约束）：缺 `xml`（或 `None`）⇒ 视同 miss（`feed_cache_get` 同）；`time` 以 `.get` 读取（缺省 `None`）；`expires_at` 沿用 `.get(..., 0)`（缺省 0 ⇒ 恒过期 ⇒ miss）；`last_access` 恒存在**不需 `.get`**（与 v1.10 口径明确区分）；`feed_fetch_acquire` 先 `get` 判空、仅未命中建 `Lock`（命中零分配、语义不变）；新增 `T-CACHE-36`（缺 `xml` vs 四字段 legacy 行为对比）、§10#28**；★ **v1.12（最后一轮契约收口）：`''` 边界写死（合法但空 ⇒ 照常命中，禁 `not xml` 真值化简，防永久回源环）、残缺降级 `log.warning` 去重（新增 `BR-CACHE-36`）、§10#29/#30 边界登记；`T-CACHE-36` 增 ④⑤**）**——**版本以文档头部为准** |
| 3 | `doc/detailed/metrics.md` | ✅ **v1.6（批次 1 → P7b v1.2 → ★ v1.3 depth 域 + 首轮豁免 → ★ P8 F3 v1.4 注册 `http_304_total`（20 名）→ ★ v1.5 F8 顺带修正自检句"`metrics.py` 零代码变更" + 溯源 SAD v1.9/PRD v0.8）**（v1.4：`_KNOWN`/`_DEFAULTS` 19→20、`server._send_not_modified` 单点计数、BR-MET-14/MET-T18；★ v1.5：**本版确实改了 `metrics.py`**——注册表各新增 1 名，与 BR-MET-14 一致） |
| 4 | `doc/detailed/stock_api.md` | ✅ **v1.3（批次 2 → P7b v1.2 → ★ r5 契约同步 v1.3）**（depth 域 + 三阶段 basic_info + 空壳防御 + `upstream_secu_code` 全量应用 + `BATCH_MAX_WORKERS=20` + `refresh_epoch` 贯通；偏差 26·测试 39） |
| 5 | `doc/detailed/market_api.md` | ✅ **v1.3（批次 2 → v1.1 → P7b v1.2 → AC-S3 裁决 v1.3）**（BR-MKT-11 封顶更正为 `_PROBE_BUDGET_CAP`；§10#9；§12 变更记录） |
| 6 | `doc/detailed/cdp_engine.md` | ✅ v1.2（批次 2 → P7b） |
| 7 | `doc/detailed/server.md` | ✅ **v1.15（★ v1.15 过时措辞更正 + 事实对齐：`feeds[].status` 同步落点 `API.md:499-511`，L24 / §2.9.1 表尾注 / BR-SRV-22 / §9 / §10#7 收口——无 BR/契约变更 · 批次 3 → P7b v1.2 → N1 回退 v1.3 → ★ r5 v1.4 → ★ P3a v1.5 → ★ P3a-r1 v1.6 → ★ P3a-r2 v1.7 → ★ P7b 回填 D-1/D-2 v1.8 → ★ P8 F1–F7 v1.9 → ★ P8 F8 v1.10 → ★ P2-1 措辞收口 + 溯源 v1.11 → ★ F8 并发变体 SRV-T73 + acquire 实现约束 v1.12 → ★ 最后一轮契约收口（SRV-T73 证伪面收窄 + 超时余量）v1.13）**（v1.4：gzip 协商 `_accepts_gzip`+`Vary`、`main()` `warm_transport`；v1.5：RSS 条件请求 `ETag`(弱)/`Last-Modified`/`304`——`_feed_etag`、`_send_not_modified`（无 body/无 `Content-Encoding`）、INM>IMS 优先级、RSS `<ttl>`（分钟）、`_get_or_fetch_feed` 返回 `(xml,last_modified)`；★ **v1.6（P3a-r1）：`_feed_etag` canonical 投影扩展 item 级 `<pubDate>` 全量剔除 + 双向不变式（C1）；§10.1 迁移第 4 条 `h.headers={}`（C2）；`<ttl>` 契约语句（C3）；`dt.timestamp()` 入 try（C4）；BR-SRV-39 措辞（C5）；§10#36 依据（C6）；14 条缺失用例（C7）**；★ **v1.7（P3a-r2）：P2-a `SRV-T52b` 细化、P2-b BR-SRV-37 限定、P2-c §10.1 2-tuple 断言、P2-d `:440/:450`、P2-f §1.1 13 条**；★ **v1.8（P7b 回填 D-1/D-2）：§10.1 第 5 条迁移 + 计数 4→5、eastmoney `<ttl>` 6 处调用点/5 handler**；★ **v1.9（P8 F1–F7）：`Last-Modified`=表示变更时刻（BR-SRV-38 改写 + BR-CACHE-33）、feed 键含 `base_url`（BR-SRV-45）、`http_304_total`（BR-SRV-46）、`max-age` authority=`feed`（BR-SRV-47）、`feed_cache_put` 返回条目（BR-SRV-48）、HTTP/1.0 304 EOF（BR-SRV-49）、`SRV-T63..T70`（测试 64→72）**；★ **v1.10（P8 F8）：`_get_or_fetch_feed` 经 `feed_fetch_acquire/release` 引用计数回收（BR-SRV-50）+ BR-SRV-45 放大风险论证补正 + `SRV-T71/T72`（测试 72→74）+ BR-SRV-46 加 P2-5 口径备注**；★ **v1.11（P2-1 措辞收口 + 溯源）：§2.5 访问器契约注 + BR-SRV-38 补 legacy 条目 \`None\` 来源（**措辞收口、无 BR 语义变更**）、头部 **SAD v1.7→v1.9 / PRD v0.6→v0.8**、接口权威 \`cache.md\` → v1.10**；★ **v1.12（F8 并发变体 + acquire 实现约束）：`SRV-T73` 独立可测（K 个不同 Host 键同时在飞：`1 <= len(_feed_fetch_locks) <= K` 且两表相等、返回后两表归零；阻塞桩 + `threading.Event`、不用 sleep）、`SRV-T71` 改写为纯串行（编号不删）、`feed_fetch_acquire` 先 `get` 判空（命中零分配）写入 BR-SRV-50、接口权威 config.md → v1.5 / cache.md → v1.11**；偏差 **45 项**·测试 **75 条**；★ **v1.13（最后一轮契约收口）：`SRV-T73` 证伪面收窄（"`release` 不在 `finally`"归 `SRV-T72` 异常路径；T73 = 按累计增长 / 两表不同步 / 上界 > K）+ 超时余量 ≥10s / `join` 后 `assertFalse(t.is_alive())`（测试仍 75、偏差仍 45）；接口权威 `cache.md` → v1.12**） |
| 8 | `doc/detailed/stream.md` | ✅ **v1.4（★ v1.4 过时措辞更正：建组 400 面同步落点 `API.md:541`/`:529`；§10#9 / §10#18 收口 · 批次 3 → P7b v1.2 → ★ r5 契约同步 v1.3）**（帧 schema 全码 + `missing`/`stale`/`errors`、last-known 结转、`_refresh_pool` 5 参 + 字段并集 + tick 预算、整 tick 网格 + 异常退避、lag C1/空池=0、准入 cap 单帧余量（9→8）、fail-closed 字段、canonical_code、`Connection: close`；★ **v1.3：节拍=最短订阅域（quote L0 4s）、`coverage` 213/426/6400、`coverage_codes` tick4 **106/53**、`refresh_epoch` 每拍真回源、帧发送层去重（`_frame_signature`/`sent_any`）、空闲唤醒 + 冷首轮豁免、`quote` 可含 `depth`**；偏差 33 项·测试 48） |
| 9 | `doc/detailed/编码规范.md` | **N/A（项目声明）**——不是"待生成"，也不是"缺失"。权威位置：`.opencode/rules/*.md`（精准定位 / 端锁定 / JSON 写入安全 / 编码纪律 / 文档对齐 / 架构思考 / 项目镜像）+ 根 `AGENTS.md`；声明落点：`.opencode/project/manifest.json → doc_profile.detailed.rule_docs = []`；门禁 `check-detailed.sh` 打印显式 N/A 提示（不静默跳过、不计问题） |
| 10 | `doc/detailed/项目规则.md` | **N/A（项目声明）**——同 #9（规则与编码规范统一落 `.opencode/rules/` + `AGENTS.md`，**不放进 `doc/detailed/`**） |

> 状态标记：**批次 1（3 份）已评审通过并修订至 v1.1**（`REV-DES-20260915-001`）；**批次 2（3 份）已按评审修订至 v1.1**（`REV-DES-20260915-002`，各文档头部为准）；**批次 3（server/stream 2 份）已完成评审闭环（v1.1）+ P7b 契约同步（v1.2）**；★ **v1.3 收尾契约同步**已回写 `server.md`（N1 回退）/ `cache.md`·`config.md`·`market_api.md`（AC-S3 裁决）——**版本以各文档头部为准**（见上表）→ **模块详设全量 8 份可交付 code-developer**（规则文档 2 项 = **N/A**，不在 `doc/detailed/`，见上表 #9/#10 与顶部「★ 最终收口」§1）。
> 
> **P7b 说明**：`config.md` 亦已在同轮 P7b 同步中回写实现态（其头部 §2.6/§10#14 等），本文件与 `config.md` 的旧口径注释（`VALID_STOCK_CODE` 保留说明）以 `config.md` 头部为准。
>
> ✅ **交付/编码前置提醒（P7b 更新）**：`config.md` §2.4 的 `CACHE_TTL`/`CACHE_JITTER`/`feed_cache`/`MAX_FEED_CACHE_SIZE`/`_trading_tiers` 常量删除**已随代码落地**（`config.py` 已无 `CACHE_TTL`；`server.py` 消费点全部改读 `cache_policy`）——本项**销账**。
>
> ⚠️ **跨模块契约同步项（编排层执行；★ v1.3 更新）——✅ 已由编排层完成（`API.md`/`README.md` 含 `depth`/gzip/`refresh_capacity_codes`/`feeds[].status`；见顶部「★ 最终收口」§2）**：① `feeds[].status` 三处取值修正（`/stock/data`→`configured`、`/stock/basic_info`→`configured`、`/stock/f10`→`requires_chrome_cdp`）需同步 healthz 负载 + 首页 CDP 列 + `API.md`；② `POST /stream/subscriptions` 的 `MAX_GROUPS=200` 超限 **400** + v1.2 新增 **`_FRAME_BUDGET_ERR` 400**（流端口 API 文档 + 变更日志）；③ `BoundedThreadPoolServer` 的 `max_inflight` 形参、**流端口显式 110**（`server.md` §10#11 · `stream.md` §10#13，编排层已批准）；④ **v1.2 新增对外行为**（★ v1.3 已剔除 error-only ⇒ 503）：~~error-only payload ⇒ 503~~ **（N1 回退：业务端点恒 200 + error 体，**无需外部同步**）**、`/healthz` 缺 `status`/含 `error` ⇒ 503、4 面板 `max-age` ~~8/120~~ **4/120（`quote` 于 v1.4 升 L0）**、`/market/margin` 非法参数 ⇒ **400**、SSE 帧新增 `missing`/`stale`/`errors` 元数据与 null 占位 —— 均须 API 文档 + 变更日志同步（**✅ 已完成，见上表 §3 落点**）；⑤ **SAD 措辞回改**：`handle_cls_*` 返回"组装 dict"（非 `(results, errors)`）+ INV-1b 覆盖数值（170/56 → ~~23/23·11·7~~ **213/426/6400；coverage_codes tick4 106/53**，见上「r5 契约同步」）—— 由 system-architect 承接；★ ⑥ **v1.3 新增（AC-S3 裁决）**：`cache._PROBE_BUDGET_CAP=5.0`（阶梯封顶，**机制常量非 env**）与"P95 ≈ 5s / 单请求 ≤15s"的量化口径若需写入 SAD §2.3 D-1，由 system-architect 回填（`cache.md` §10#11·#18 / `config.md` §2.3·§10#18 已按实现钉死）。
>
> ★ **v1.4 新增（r5 契约同步 · 编排层执行）——✅ 已由编排层完成（`API.md`:537/653/667、`README.md`:49/81-83；见顶部「★ 最终收口」§2）**：⑦ **`API.md` / README / 变更日志同步**：① SSE 帧 `items[code].quote` 新增 **`depth`**（五档盘口 21 字段）＋ 既有 `missing`/`stale`/`errors` 元数据与 null 占位；② 主端口 JSON/HTML 响应新增 **gzip**（`Content-Encoding: gzip` + `Vary: Accept-Encoding`，`Accept-Encoding` 协商；`gzip;q=0` 不压缩）；③ 建组 400（`MAX_GROUPS` / `_FRAME_BUDGET_ERR`）与 `refresh_capacity_codes`（tick4 quote 106 / 3 域 53）容量元数据；④ `feeds[].status` 三处取值修正（`/stock/data`→`configured`、`/stock/basic_info`→`configured`、`/stock/f10`→`requires_chrome_cdp`）。⑧ **SAD 回填（system-architect）**：§2.1 INV-1b / §2.2 R-6 覆盖数值改为 `coverage = int(0.8×tick×BATCH_MAX_WORKERS/_PER_FETCH_EST)`（r5：**213/426/6400**；`coverage_codes` tick4 **106/53**）、补 **L0 档**（quote/depth 盘中 4s）、`depth` 域、`upstream_secu_code`（wire 拼写）、`_refresh_pool` 的 `refresh_epoch` 与帧发送层去重；`config.md`/`cache.md`/`stream.md`/`stock_api.md`/`server.md` **已按实现钉死**。

## v1.1 修订摘要（批次 3 · REV-DES-20260915-002）

> 评审报告：`doc/review/HTTP-SSE层两模块_详细设计评审_专家版.md`（结论 ⚠️ 阻断，P0×0 / P1×4 / P2×10）。
> 范围：仅 `server.md` / `stream.md`（+ 本文件）——**未动 SAD / PRD / config.md / 代码**。

| 项 | 位置 | 处理 |
|----|------|------|
| **P1-1** healthz 准入位早释放 → 无界队列 | `server.md` §2.6/§2.6.1/§3.2/§4.5/§5.6/§6.2/§7/§8/§10#16 | 新增 `_HealthBatch`：准入位由该批 **5 个 future 的完成回调**释放 ⇒ 在飞任务 ≤25、执行器队列 ≤20；§2.6 断言与伪代码一致；新增 `SRV-T34`（持续慢 check 下队列有界、恰好 release 一次） |
| **P1-2** 外部上游串行越 AC-E2 | `server.md` §1.1/§2.8/§2.9/§4.6 BR-SRV-30/§5.5/§6.2/§8/§9/§10#10·#15 | hotplate/plate/longhu 改 **≤3 并发**（共享 `_fanout_executor`）⇒ 单端点 = `max` 而非 `sum`（≤10s ≤15s）；登记归属更正为 **AC-E2**；新增 `SRV-T35`、`SRV-T13` 补并发断言 |
| **P1-3** hotplate 全失败缺顶层 `error` | `server.md` §2.8/§4.6 BR-SRV-31/§5.5/§6.1/§8·T14/§9 | 三分区全失败 ⇒ **顶层补 `error`**（SAD §2.3 D-4 唯一口径）；部分失败仍无顶层 `error` |
| **P1-4** 流端口 inflight 40 使 100 连接失效 | `server.md` §1.5/§2.7/§3.4/§5.7/§10#11 · `stream.md` §2.2/§10#13 | `BoundedThreadPoolServer.__init__` 增 `max_inflight=None`；流端口显式传 **110**（≥ `MAX_STREAM_CONNS`+10）⇒ AC-E5/E7 可复现（**编排层已批准**） |
| **P2-1** ttl 求值点矛盾 | `server.md` §2.5/§5.4/§7.4 | `ttl` 移到**二次 `feed_cache_get` 仍 miss 之后**求值；唯一表述 |
| **P2-2** healthz 10s 预算死代码 | `server.md` §2.6.1/§3.2/§4.5 BR-SRV-20/§5.6/§8·T21 | 每源按各自 `submitted_at` 独立 3s；整体 10s 为独立闸（新增可测断言） |
| **P2-3** `feeds[].status` 注释过宽 | `server.md` §3.1 | 限定"仅 5 个 RSS 源被覆盖"；10 个 JSON/CDP 条目保持原值 |
| **P2-4** 分组视图 `object（8）` 计数错 | `server.md` §2.2 | 改 `object（7，表内）`+ 明示 `/healthz` 不入表（否则 `assert len==14` 失败） |
| **P2-5** import 清单不完整 | `server.md` §2.10 | 改为**完整 import 块**（可整体替换）：补删 `Request,urlopen`/`random`；补 `main()` 所需 `stock_api` 4 prefetch loop、`market_api`、`utils` |
| **P2-6** `_group_bytes` 系统性低估 | `stream.md` §3.4/§4.2 BR-STR-15/§5.2/§8·T33/§9/§10#6 | `_reserve_for` 改用**本轮排除集 `skip`**（不再 `pop(_group_bytes[sid])`）⇒ 组账如实、丢弃选靶确定性恢复；`skip` 单调增长保证终止 |
| **P2-7** 销毁 vs 注册残留竞态 | `stream.md` §5.5/§7.4/§8·T34/§10#17 | `g.conns.add(conn)` 后在 `_groups_lock` 下复检 `_groups.get(sid) is g`；不成立 ⇒ `closed`+摘除+`_release_conn`+404 |
| **P2-8** 测试清单多列 1 条 | `stream.md` §11.1/§8·T31 | `test_broadcast_serves_live_group_only` 降级为**可选清理**（非破坏性）；明示真正必改 = **4 条** |
| **P2-9** `stream_refresh_lag_ticks` owner | `stream.md` §3.5 | owner 对齐 `metrics.md` §3.2 = `stream.push_loop` |
| **P2-10** `cached_batch` 域名隐式化 | `stream.md` §2.3 | 统一 `cached_batch(_FIELD_DOMAINS[field], rest)`（消除"字段名==域名"假设） |
| **裁决①** handler 返回组装 dict | `server.md` §10#17 | 批准；SAD 措辞由 system-architect 回改 |
| **裁决②** 流端口 `max_inflight=110` | `server.md` §10#11 · `stream.md` §10#13 | 批准 |

**保持不动**：全部 SAD v1.3 钉死项（stream 侧 **7 项全 ✅**、server 侧 8 项中 6 ✅ 已转为 ✅，见 server §4 与 `SRV-T14` 更新）；既有测试真正破坏面仍为 **4 条**（全在 stream，未新增）。



## ★ 压测观测记录（2026-09-18 · 非交易时段 / 收盘后）

> 范围：**只记录观测，未改代码 / 未改契约 / 未改其他文档**。方法：`tests/{stress_test,stress_all,loadtest}.py` 对 8053 端口全套压测（容器已由用户重建并验证代码 == 工作区 HEAD）。

### 观测结论

1. **真实负载形态（健康）**：
   - `loadtest.py` 混合 10 并发（含 `/`、`/healthz`、`/opml.xml`、`/cls/hotplate`、`/stock/fundflow`）：700 请求 700 OK · 35 req/s · avg 60ms · max 219ms。
   - `stress_all.py` 15 并发 660 请求：628 OK / 32 Fail——**32 Fail 全部为 `/stock/f10`**（已知 REV-DES-21 非热路径），其余 11 个端点（RSS 5 + 面板 4 + fundflow/timeline/announcement/basic_info/data）p95 < 0.4s；内存 621→620MiB **稳定**（预算 1.5GiB）。
   - `/stock/f10` 单只验证：`sh600519` 缓存命中 1.8ms 完整数据；`sh600030` CDP 导航 3.3s 完整数据；批量 5 码 26.4s（60s budget 内）200，3 码完整 + 2 码按既有 `cdp_unavailable` 降级语义返回（`_errors` 结构，契约不变）。
2. **极端并发（不代表真实业务）**：`stress_test.py`（20 并发 × 20 端点 = 380 线程）第 2 轮出现全量客户端失败（status=-1 @0.0s）。定位：`/stock/f10_batch` 60s CDP 串行导航慢尾（`_BATCH_BUDGET_CDP=60`）占满 20-worker 公共池 → `BoundedThreadPoolServer._reject_503` 负载丢弃（裸 503 不经 `log_message`，访问日志不可见）。**触发条件需 20 并发 `f10_batch` 同时命中**——f10 非热路径（REV-DES-21 已裁定：极少调用、不构成问题）⇒ **该场景真实业务不成立，不做工程改造**（不设 CDP 并发闸门、不改 `MAX_WORKERS`/`MAX_INFLIGHT`）。
3. **回归**：`python -m unittest discover -s tests` = **514 全绿（5.4s）**；`py_compile` 通过。服务代码零改动，仅新增压测辅助脚本 `.opencode/scripts/{run-stress.sh,inspect-logs.sh}`（含 `--since` 修复与 503 隐形问题的说明）。

## ★ 内存调优 PRF-MEM-01 契约同步（2026-09-20 · 只改文档）

> 范围：**只改** `doc/detailed/{config,stock_api,_PROGRESS}.md`。**未改代码 / `doc/arch/` / `doc/prd/` / `API.md` / `README.md` / `.opencode/`**；**只增不删编号**；未回改任何历史变更块。

### 1. 变更（权威新值 · 代码已落地并过 514 用例 + 代码评审）

| 域 | `pool_max` 旧 → 新 | `cache_max` 旧 → 新 | pool spec |
|----|-------------------|--------------------|-----------|
| `quote` | 2000 → **1000** | 2000 → **1000** | `'dedup'` → `'fixed:1000'` |
| `fundflow` | 2000 → **1000** | 2000 → **1000** | `'dedup'` → `'fixed:1000'` |
| `timeline` | 2000 → **500** | 2000 → **500** | `'dedup'` → `'fixed:500'` |

- **不变**：`depth`(dedup,500)、`announcement`/`f10`(dedup,500)、`plate`(200)、`feed`(100)、`margin`(16)、`sector`(2000/2000)。`MAX_DEDUP_CODES`（=2000）未变 ⇒ `stock_api._FAIL_LEDGER_MAX`（5×2000=10000）不受影响。

### 2. 归因与预期（登记原文）

- **现象**：压测显示容器内存 **96.57%** 高水位。
- **归因**：终端缓存被灌满至 `cache_max`；`timeline` 单条 ~96KB 为内存大户；prefetch（`pool_refresh` 120s 轮询）保活使 LRU 不淘汰。
- **处置**：3 域 `pool_max`/`cache_max` **同源收缩**（保活范围收敛）。
- **预期**：python 稳态 **RSS ~1.1GiB → ~0.65GiB**。

### 3. 逐处落点（`旧 → 新`）

| 文件 | 位置 | 旧 → 新 |
|------|------|---------|
| `config.md` | 头部 / §3.1 / §3.2 / §2.4 / §8(CFG-T19) / §9 / §10#24 / §11 | v1.7 → **v1.8**；3 域矩阵与实值 `2000` → `1000/1000/500`；新增 PRF-MEM-01 登记与断言 |
| `stock_api.md` | 头部 / §3.3 / §3.5 / §4.3(BR-SA-13) / §9 / §10#5·#27 / §11 / §12 | v1.5 → **v1.6**；3 域实值同步；BR-SA-13 改写为"池上限按域独立配置"；**另更正 §3.5 `quote.ttl` `8\|120`→`4\|120`**（遗留漂移，v1.4 升 L0） |
| `_PROGRESS.md` | 「当前状态」+ 本节 | 新增登记 |

### 4. ⚠️ 评审未列出的额外漂移（本轮一并修正）

- **`stock_api.md §3.5` `quote.ttl` 旧记 `8|120`**（其余域按 L 档正确）：`quote` 于 **v1.4 升 L0**（盘中 4s），`config.md` §3.2 早已为 `4|120` ⇒ 本次顺带更正为 **`4|120`**（与 `quote` 同拍语义一致）。此为评审清单未列项，已在本轮修正并在两文件变更说明中标注。

### 5. 交编排层 / system-architect（不在本 agent 范围）

- **SAD 回填**：`doc/arch/SAD.md` §2.1 矩阵 / §4.3 内存估算 / §7.2 AR-8（端点缓存 ≈268MB 等）按 3 域新值重算（`quote`/`fundflow`/`timeline` 池与 `cache_max` 收缩）；`config.md §10#24` / `stock_api.md §10#27` 已登记为权威上下文。

## ★ PRF-MEM-01 修复轮契约同步（2026-09-20 · 只改文档）

> 范围：**只改** `doc/detailed/{config,stock_api,_PROGRESS}.md`。修复**首轮** P8 发现的 3 个问题（代码已落地、**517 用例全绿**），以 `china_finance_rss/config.py` + `tests/` 实现与用例为准回写。**未改代码 / `doc/arch/`（SAD 已由 system-architect 于 v1.15 承接本修复轮）/ `doc/prd/` / `API.md` / `README.md` / `.opencode/`**；**只增不删编号**；**未回改任何历史变更块**。

### 1. 代码事实（本轮依据，逐条已核对）

| # | 事实（`file:line`） | 内容 |
|---|--------------------|------|
| CR-02 | `config.py:330-333` | 新增 3 env 注册常量 + 白名单：`MAX_QUOTE_POOL`(1000) / `MAX_FUNDFLOW_POOL`(1000) / `MAX_TIMELINE_POOL`(500)；`_POOL_MAX_ENVS = frozenset({...})` |
| CR-02 | `config.py:458-472` | `_resolve_pool_max` 新增 `'env:<NAME>'` 分支：`NAME ∉ _POOL_MAX_ENVS ⇒ ValueError('bad pool_max env name: ...')`；否则 `int(globals()[NAME])`（**调用期**解析） |
| CR-02 | `config.py:357/359/360` | 矩阵三行 spec = `'env:MAX_QUOTE_POOL'` / `'env:MAX_FUNDFLOW_POOL'` / `'env:MAX_TIMELINE_POOL'`；`cache_max` 仍为整数字面量 1000/1000/500；`depth` 仍 `'dedup'`/500 |
| CR-03 | `tests/test_config.py:74-92` | `test_prf_mem_01_pool_cache_contract`（CFG-T19）+ `test_prf_mem_01_pool_cap_follows_env`（热替换常量 ⇒ 值跟随） |
| CR-04 | `tests/test_data_layer.py:396-414` | `test_prf_mem_01_cache_degrade_is_lru_bounded`（`_cache_store` 严格 LRU 有界 + `cache_ts` 同步淘汰 + 最新值不变 + 不抛） |
| CR-05 | `config.py:350-355` | 矩阵头注释更正：prefetch 间隔 = `pool_refresh` = `ttl × refresh_factor`（盘中 quote/depth 4s、fundflow/timeline 8s、非盘 120s）；`≈0.65GiB` 明标**估算值，待实测复核** |
| CR-06 | `config.py:326-329/358` | `depth` 池保持 `'dedup'` 的理由（无 prefetch 循环 ⇒ 池仅账本；`cache_max=500` 为内存界） |

### 2. 逐处落点（`旧 → 新`）

| 文件 | 位置 | 旧 → 新 |
|------|------|---------|
| `config.md` | 头部 / 版本 / 日期 | v1.8 → **v1.9**；新增 **v1.9 变更块**（修复轮）；日期 → **2026-09-20** |
| `config.md` | §1.1#5 | 补：3 域池上限亦经 env 注册（`MAX_*_POOL`，默认 1000/1000/500），由 `'env:<NAME>'` **调用期**绑定 |
| `config.md` | §2.4（表行 + 脚注） | `_BASIC_INFO_MAX_POOL` 目标值注明 ★ v1.9 经 `'env:MAX_QUOTE_POOL'` 派生 |
| `config.md` | §2.7（env 全量清单） | `+3` 行：`MAX_QUOTE_POOL: 1000 \| MAX_FUNDFLOW_POOL: 1000 \| MAX_TIMELINE_POOL: 500`（默认值即收缩值）；补「冻结 vs 调用期读取」细化段 |
| `config.md` | §3.1（矩阵 + spec 注释） | 三行 `'fixed:1000'/'fixed:1000'/'fixed:500'` → **`'env:MAX_QUOTE_POOL'/'env:MAX_FUNDFLOW_POOL'/'env:MAX_TIMELINE_POOL'`**；spec 注释补 `'env:<NAME>'`；`depth` 行补"保持 dedup 是有意" |
| `config.md` | §3.2（实值表 + 注） | **数值不变**；注释补 `'env:<NAME>'` 语义；新增 v1.9 注（来源 env / `cache_max` 硬界）；**更正 prefetch 间隔误述**；`~0.65GiB` 标"估算待实测" |
| `config.md` | §3.3 | 边界澄清：env 值导入期冻结、`'env:<NAME>'` 解析在调用期（≠ 重读 env） |
| `config.md` | §5（伪代码） | 新增 3 env 常量 + `_POOL_MAX_ENVS`；`_resolve_pool_max` 增 `'env:'` 分支（白名单 + `ValueError`） |
| `config.md` | §6（错误处理） | 新增行：`'env:<NAME>'` 未知名 ⇒ `ValueError`；原 spec 非法行注明"首次 `cache_policy` 调用期" |
| `config.md` | §8（CFG-T19） | **"声明" → "已落地"**：列出 3 个真实用例名（CFG-T19 / CR-02 / CR-04）；用例总数 **514 → 517** |
| `config.md` | §10#24 | 补 v1.9 env 语义（**pool 可调 / `cache_max` 硬界**）+ `depth` 理由 + prefetch 更正 + GiB 估算标注 |
| `config.md` | §11 | 新增 v1.9 自检行 |
| `stock_api.md` | 头部 / 版本 | v1.6 → **v1.7**；新增 **v1.7 变更块**（修复轮） |
| `stock_api.md` | §3.3（池/缓存注释） | pool 上限 → "经 `'env:MAX_*_POOL'` 派生（默认 1000/1000/500，可免改码调参）"；`cache` 行补 CR-04 降级说明 |
| `stock_api.md` | §3.5（实值表 + 注） | 3 行 `pool_max` 注明经 env 派生（**数值不变**）；`depth` 行补"保持 dedup 有意"；新增 v1.7 注（来源变更 + CR-04 降级面） |
| `stock_api.md` | §4.3 **BR-SA-13** | 补 `'env:<NAME>'`（白名单/调用期/默认值不变）；补 **CR-04 降级说明**（`cache_max` < 活跃码上界 2000 ⇒ LRU + `stream._last_known` 结转，功能不破坏）；补 **`depth` 保持 `'dedup'` 的理由**；更正 prefetch 间隔；GiB 标估算 |
| `stock_api.md` | §9（AC 矩阵） | 池上限行补"★ v1.7 经 `'env:MAX_*_POOL'` 派生、可免改码调参" |
| `stock_api.md` | §10#27 | 补修复轮登记（v1.9 env 化 / CR-04 / CR-06；SAD v1.15 已承接） |
| `stock_api.md` | §11 / §12 | 新增 v1.7 自检行 + 变更记录行 |
| `_PROGRESS.md` | 「当前状态」+ 本节 | 新增登记 |

### 3. 语义边界（钉死，避免下游脑补）

- **`pool_max` = 可调（env）**；**`cache_max` = 硬界（矩阵字面量，不 env 化）** —— 两者**不再是同一来源**，但**默认值仍是同一组数**（1000/1000/500）。
- **`'env:<NAME>'` 解析在调用期**：读的是**导入期已冻结的模块常量**（`globals()[NAME]`），**不是**重读 `os.getenv` ⇒ 不违反 BR-CFG-16「禁止运行期重读 env」；热替换模块常量即生效（CR-02 / CR-03）。
- **未知 `NAME` 无兜底**：`ValueError('bad pool_max env name: ...')`，与 BR-CFG-8「未知 domain 不返回默认」同精神。
- **CR-04 降级是"有界非崩溃"**：`cache_max`（1000/500）< 活跃码上界 2000 ⇒ 终态缓存**不再覆盖活跃全集**；本模块 `_process_chunk` 对未命中码**正常回源**，消费方 `stream` 以 `_last_known` 结转保帧完整。**代价 = 命中率/取数量**，非功能缺陷。
- **CR-06 `depth` 保持 `'dedup'` 是正确设计**：`depth` **无 prefetch 循环**（经 `fetch_cls_basic_info` 阶段 3 → `_depth_store` 写入），池仅 `code→ts` 账本（~200KB 量级），真正的内存界是 `cache_max=500` ⇒ "与 quote 不对称"仅为表面观感。

### 4. 交编排层 / 其他 agent（不在本 agent 范围）

- **SAD**：已由 **system-architect** 于 **v1.15** 承接本修复轮（§2.1 三行 spec + 示例输出、§2.2 不变式更正、§2.4/§2.6/§3/§4.3/§6/§7.2 AR-8/§8 S9/§9.15）；本轮**未改** `doc/arch/`。
- **`tech-stack.json`**：同上批已 `version 1.14 → 1.15`。
- **`cache_hit_ratio` 定向护栏（CR-04 修复方向原要求）**：`stream.md` / `metrics.md` 侧未新增——**如需请另批授权**（本轮范围仅 `config` / `stock_api` / 本文件）。
- **历史快照行**：本文件「★ 内存调优 PRF-MEM-01 契约同步」§1 表格、`stock_api.md §10#5` 仍记首轮 `'fixed:...'` 值——**按"不回改历史变更块"约定原样保留**（其状态由本节取代）。

## ★ PRF-MEM-01 实测回填与结论更正（2026-09-20 · 只改文档）

> 范围：**只改** `doc/detailed/{config,stock_api,_PROGRESS}.md`。**未改代码 / 测试 / `doc/arch/`（SAD）/ `doc/prd/` / `API.md` / `README.md` / `.opencode/`**；**只增不删编号**；未回改任何历史变更块。

### 1. 实测事实（权威 · run 20260920-110805）

| 指标 | 收缩前 | 收缩后（实测） | 净变化 |
|------|--------|----------------|--------|
| 容器稳态 | **1.449GiB / 1.5GiB（96.57%）** | **1.41GiB / 1.5GiB（93.98%）** | −~39MiB |
| python 稳态 RSS | **1.095GiB** | **1.012GiB** | **−~83MiB** |
| `cache_hit_ratio` | 0.1585 | **0.1796** | +0.0211 |

- **3 域缓存精确生效（旁证）**——healthz `/healthz?check=0`：`quote`/`fundflow` `pool_max`/`cache_max` = **1000/1000**、`timeline` = **500/500**、`depth` = **500**（与契约逐值一致）。
- **结论：本次收缩未达成内存目标**（原预期 python RSS ~1.1GiB → ~0.65GiB 已被实测**证伪**，实测仅 −83MiB）。

### 2. 归因更正

- **终端缓存只是小头**：实测反推 = `timeline` 1350→500 省 **~82MB** + `quote`/`fundflow` 各 −1000 条省 **~10MB** ≈ **92MB**，与 −83MiB **吻合**。
- **真正大头 = 未收缩的共享 URL 缓存**：`cache.py:35 MAX_CACHE_SIZE = 2000`；实测 `cache_entries.url = 2000` **顶满**；条目形如 `{'data': 解析后的 Python 对象}`，**体积数倍于原始 JSON**。
- 其次为**线程池 glibc arena 碎片**（分配器不归还）。

### 3. 观测（⚠️ 待复测归因，尚非结论）

- tier1000 压测：`timeline` `ok_rate` **100% → 89.6%**、`upstream_timeout` **123 → 317**。
- **不得写成结论**——需复测 + 归因；`config.md §10.1` / `stock_api.md BR-SA-13` 与本节均已标注「待复测归因，尚非结论」。

### 4. 逐处落点（`旧 → 新`）

| 文件 | 位置 | 旧 → 新 |
|------|------|---------|
| `config.md` | 头部 / 版本 | v1.9 → **v1.10**；新增 **v1.10 变更块**（实测回填 + 归因更正） |
| `config.md` | §3.2 注 | 「预期 ~1.1GiB → ~0.65GiB（估算待实测）」→ **实测 1.095GiB → 1.012GiB（−83MiB）/ 容器 1.449GiB→1.41GiB；未达成目标；归因更正** |
| `config.md` | §10#24 | 行内「预期…~0.65GiB」→ 实测回填；**新增 §10.1「实测结论」小节**（目标未达成 + 证据 + 后续方向） |
| `config.md` | §11 | 新增 v1.10 自检行 |
| `stock_api.md` | 头部 / 版本 | v1.7 → **v1.8**；新增 **v1.8 变更块**（实测回填） |
| `stock_api.md` | §4.3 **BR-SA-13** | 「预期 RSS ~1.1GiB→~0.65GiB」→ 实测口径 + **终端缓存非内存大头**更正 |
| `stock_api.md` | §10#27 | 同上更正 |
| `stock_api.md` | §11 / §12 | 新增 v1.8 自检行 + 变更记录行 |
| `_PROGRESS.md` | 「当前状态」+ 本节 | 新增登记 |

### 5. 交编排层 / 其他 agent（不在本 agent 范围）

- **共享 URL 缓存调优**（`cache.MAX_CACHE_SIZE` / 条目表示）：属 `cache.py` 改动，须**另立 change-set**（本轮不改代码）；`cache.md` 契约同步届时由 task-decomposer 执行。
- **tier1000 `timeline` 退化**：⚠️ **待复测归因，尚非结论**——复测后再定是否立修复项。
- **残留 `~0.65GiB` 表述**：仅存于**历史变更块**（`config.md §11 v1.9 自检行`、`stock_api.md §11 v1.7 / §12 v1.6·v1.7`、本文件「★ 内存调优 PRF-MEM-01 契约同步」§2 与「★ PRF-MEM-01 修复轮契约同步」§CR-05）——按「不回改历史变更块」约定**原样保留**，其状态由本节取代。

## ★ 归因纠偏 + PRF-MEM-02 arena 治理实测（2026-09-20 · 只改文档）

> 范围：**只改** `doc/detailed/{config,stock_api,_PROGRESS}.md`。**未改代码 / 测试 / `doc/arch/`（SAD）/ `doc/prd/` / `API.md` / `README.md` / `.opencode/`**；**只增不删编号**；未回改任何历史变更块（旧归因以「已被证伪」标注，保留原文）。
> 承接：上一轮「★ PRF-MEM-01 实测回填与结论更正」的**归因部分被本轮证伪**；本节为**现行有效**口径。

### 1. 纠偏（上一轮归因已被证伪）

- ❌ **旧归因（作废）**：共享 URL 缓存条目为 `{'data': 解析后 Python 对象}`，体积数倍于原始 JSON，是 1GB 级内存大头。
- ✅ **实际**：共享 URL 缓存存的是**解码后的原始响应文本（`str`）**——`cache.py:851-852` `data = resp.read().decode(encoding, errors='replace')`、`cache.py:862` `_cache_put(cache, url, data, ttl=ttl)`；**`json.loads` 由调用方在命中后解析**，缓存内**没有**解析对象。
- ⇒ 按条数（`MAX_CACHE_SIZE=2000`）与体积估算，URL 缓存总量仅**几十 MB**，**不是内存大头**。
- 终端缓存（解析对象）绝对量级仅约 **~200MB**（见 §3 剩余项），亦非 GiB 级主体。

### 2. 真因 + A/B 实测（run 20260920-113125，基线 run 20260920-110805）

| 指标 | 基线（默认 arena） | `MALLOC_ARENA_MAX=2` |
|------|--------------------|----------------------|
| python VmRSS | 1,057,324 kB (1.008GiB) | **809,328 kB (0.772GiB)** |
| RssAnon | 1,042,748 kB | 794,776 kB |
| VmSize | 8.96 GB | **1.15 GB** |
| 匿名 rw-p 映射 | 300 | **166** |
| 容器稳态 | 1.41GiB (93.98%) | **1.259GiB (83.95%)** |
| tier1000 `timeline` `ok_rate` | 89.6% | **100%**（⚠️ **单次观测，可能含上游波动，勿写成结论**） |

- **机制**：33 线程 × 默认最多 `8×ncores` 个 **64MB glibc arena** → 碎片 / 分配后不归还（`VmLib`/`RssFile` 仅 **14.5MB**，`RssAnon` 占 **98%**）。
- **结论**：`MALLOC_ARENA_MAX=2` 是当前最有效的单项治理（python VmRSS −248MiB）；属**部署侧 env 注入**，非代码改动。

### 3. 累计链路

| 阶段 | python RSS | 容器稳态 |
|------|-----------|---------|
| 收缩前 | 1.095GiB | 1.449GiB |
| 3 域缓存收缩（PRF-MEM-01） | 1.012GiB（−83MiB） | 1.41GiB |
| + `MALLOC_ARENA_MAX=2`（PRF-MEM-02） | **0.772GiB**（−248MiB） | **1.259GiB** |

- **仍未达 ~0.65GiB 级**：剩余 = 终端缓存解析对象（**~200MB**）+ 运行时/分配器残余。

### 4. 逐处落点（`旧 → 新`）

| 文件 | 位置 | 旧 → 新 |
|------|------|---------|
| `config.md` | 头部 / 版本 | v1.10 → **v1.11**；新增 **v1.11 变更块**（归因纠偏 + PRF-MEM-02） |
| `config.md` | §3.2 注 | 「真正大头 = 共享 URL 缓存（解析后 Python 对象）」→ **URL 缓存存文本、仅几十 MB、非大头；真因 = arena + A/B 数据** |
| `config.md` | §10#24 | 同上更正 + 编号列补 **★ v1.11** |
| `config.md` | §10.1 | 标题扩为 **PRF-MEM-01 / PRF-MEM-02**；**归因段重写为「纠偏」**；新增 **A/B 表 + 累计链路表 + 剩余项**；单次观测标注 |
| `config.md` | §11 | 新增 v1.11 自检行 |
| `stock_api.md` | 头部 / 版本 | v1.8 → **v1.9**；新增 **v1.9 变更块**（归因纠偏 + PRF-MEM-02） |
| `stock_api.md` | §4.3 **BR-SA-13** | 「真正大头 = 共享 URL 缓存（解析后 Python 对象）」→ 纠偏 + arena A/B |
| `stock_api.md` | §10#27 | 同上更正 + 编号列补 **★ v1.9** |
| `stock_api.md` | §11 / §12 | 新增 v1.9 自检行 + 变更记录行 |
| `_PROGRESS.md` | 「当前状态」+ 本节 | 新增登记 |

### 5. 交编排层 / 其他 agent（不在本 agent 范围）

- **部署侧 `MALLOC_ARENA_MAX=2`**（env 注入）：属部署配置，非代码改动；如需写入 `README.md` / 部署脚本，**由编排层另批**。
- **终端缓存解析对象治理（~200MB）**：属 `stock_api`/`cache` 代码改动，须**另立 change-set**。
- **残留旧归因表述**：仅存于**历史变更块**（`config.md` v1.10 块与头部 ★ v1.10 片段、`stock_api.md` v1.8 块与头部 ★ v1.8 片段、本文件「★ PRF-MEM-01 实测回填与结论更正」）——按「不回改历史变更块」约定**原样保留**，其状态由本节取代（各处已由本节/新块显式标注「已被证伪」）。

## ★ P8-r1 P1/P2 收尾（导入期冻结 + 测试 hermetic 化 + 重复用例去重 · 2026-09-20 · 只改文档）

> 范围：**只改** `doc/detailed/{config,stock_api,_PROGRESS}.md`。背景：P8-r1 修复已落地（**518 用例全绿**），本轮把**契约文档**与实现对齐。**未改代码 / 测试（修复已落地）/ `doc/arch/`（SAD）/ `doc/prd/` / `API.md` / `README.md` / `.opencode/`**；**只增不删编号**；未回改任何历史变更块（旧措辞以「已更正」标注，保留原文）。

### 1. 变更事实（代码，已落地）

- **`'env:<NAME>'` 语义由"调用期解析"改为"导入期冻结的注册映射"**：`_POOL_MAX_ENVS` 由 `frozenset({'MAX_QUOTE_POOL','MAX_FUNDFLOW_POOL','MAX_TIMELINE_POOL'})` 改为**映射** `{'MAX_QUOTE_POOL': MAX_QUOTE_POOL, 'MAX_FUNDFLOW_POOL': MAX_FUNDFLOW_POOL, 'MAX_TIMELINE_POOL': MAX_TIMELINE_POOL}`（**键=唯一合法 NAME、值=导入期冻结的池上限；名单与取值同源，新增 env 只改一处**）。
- **`_resolve_pool_max`** 的 `'env:'` 分支改为 `try: return _POOL_MAX_ENVS[name] except KeyError: raise ValueError(...) from None`（**不再 `globals()`**）。
- **后果**：运行期重绑定 `config.MAX_*_POOL` **不再影响** `cache_policy(...)['pool_max']`（此前会生效）⇒ `cache_policy` 的运行期结果**不依赖可变模块全局**（符合 **BR-CFG-10**「运行期只读」）。
- **错误类型**：未注册/未定义 NAME **一律 `ValueError('bad pool_max env name: ...')`**（此前可能 `KeyError`）。

### 2. 测试侧（代码，已落地）

- `tests/test_config.py::test_prf_mem_01_pool_cache_contract` 改为**字面量锁定**默认值（1000/1000/500）+ 断言 `DOMAIN_MATRIX[i][3] == 'env:MAX_*_POOL'`；**删除热替换用例** `test_prf_mem_01_pool_cap_follows_env`；新增 `test_prf_mem_01_pool_caps_are_frozen_at_import`（BR-CFG-10）与 `test_prf_mem_01_bad_env_spec_fails_fast`（P2-1）。
- `tests/test_data_layer.py`：删除与 `test_cache_true_lru_eviction` 重复的用例；新增 `test_prf_mem_01_evicted_code_reads_as_miss_not_stale`（锁 `cache_max < 工作集` 时被 LRU 淘汰的码**读路径为 miss 并回源、绝不返回陈旧值**）。
- **用例总数 517 → 518**。

### 3. 逐处落点（`旧 → 新`）

| 文件 | 位置 | 旧 → 新 |
|------|------|---------|
| `config.md` | 头部 / 版本 | v1.11 → **v1.12**；新增 **v1.12 变更块**（P8-r1 P1/P2 收尾） |
| `config.md` | §1.1#5 / §2.7 yaml 注释 / §3.1 注释 | "在**调用期**绑定 / 白名单 _POOL_MAX_ENVS / 调用期解析" → **导入期冻结的注册映射取值（键=NAME、值=冻结值、名单与取值同源）** |
| `config.md` | §2.3 env 表 | 补 `MAX_QUOTE_POOL`(1000) / `MAX_FUNDFLOW_POOL`(1000) / `MAX_TIMELINE_POOL`(500) 三行（**默认值 = PRF-MEM-01 收缩值**）+ 实现要点补注 |
| `config.md` | §2.7 注 | "调用期 `globals()[NAME]`、热替换常量即生效" → **导入期建成并冻结、不读可变模块全局、运行期重绑定不生效** |
| `config.md` | §3.3 边界澄清 | 同上更正（v1.12 更正 v1.9） |
| `config.md` | **BR-CFG-4** | 改写为"`'env:<NAME>'` → **导入期冻结的注册映射**取值；未注册/未定义 NAME ⇒ `ValueError`"；删去"调用期 `globals()` / 可热替换" |
| `config.md` | §5 伪代码 | `_POOL_MAX_ENVS` 映射（键=NAME、值=冻结值）+ `_resolve_pool_max` 改 `try/except KeyError` |
| `config.md` | §6 错误处理 | "NAME 不在白名单（调用期）" → "**未注册/未定义 ⇒ `ValueError`（读导入期冻结映射未命中）**" |
| `config.md` | §3.2 | 新增 **pool 与 cache 是两个独立上限（P1-2）** 设计取舍（不设 `pool_max ≤ cache_max` 护栏） |
| `config.md` | §8 | **CFG-T9** 补 3 个 `MAX_*_POOL` 默认值断言；**CFG-T19** 更新为 **4 个落地用例**（含读路径 miss 锁）**517 → 518** |
| `config.md` | §10#24 / §10.1 / §11 | 补 **P8-r1 P1/P2 收尾** 登记（导入期冻结、名单同源、`ValueError`、测试 hermetic 化） |
| `stock_api.md` | 头部 / 版本 | v1.9 → **v1.10**；新增 **v1.10 变更块**（P8-r1 P1/P2 收尾） |
| `stock_api.md` | §4.3 **BR-SA-13** | "调用期解析" → **导入期冻结映射 + 名单同源 + `ValueError`**；补 **pool/cache 独立上限（P1-2）** 设计取舍 |
| `stock_api.md` | §3.3（v1.7 注） | "（白名单 `_POOL_MAX_ENVS`，调用期解析）" → "（经**导入期冻结**的注册映射取值）" |
| `stock_api.md` | §10#27 | "白名单 `_POOL_MAX_ENVS` + **调用期**解析" → **导入期冻结映射取值**；编号列补 **★ v1.10** |
| `stock_api.md` | §11 / §12 | 新增 v1.10 自检行 + 变更记录行 |
| `_PROGRESS.md` | 「当前状态」+ 本节 | 新增登记 |

### 4. 残留（**历史变更块，不回改**）

- **现行有效正文**已无"调用期解析 / 可热替换"表述（见本轮 grep 自查：`config.md` 仅剩**历史 ★ v1.9 片段/块/自检行**，`stock_api.md` 仅剩**历史 v1.7/v1.8/v1.9 块与 §12 历史行**）。
- 本文件下方「★ PRF-MEM-01 修复轮契约同步」§1/§2 及 `CR-02`/`CR-03` 行仍记旧措辞（`int(globals()[NAME])`、"热替换常量 ⇒ 值跟随"）——**为该轮历史快照，按约定原样保留**，其状态由本节取代。

## ★ PRF-LAT-02 margin 终端缓存契约同步（`config.md` v1.14 / `market_api.md` v1.8 / `metrics.md` v1.10 · 2026-09-20 · 只改文档）

> 范围：**只改** `doc/detailed/{config,market_api,metrics,_PROGRESS}.md`。依据：**已落地的代码**（`china_finance_rss/config.py` / `market_api.py`，**525 用例全绿**）。**未改代码 / 测试 / `doc/arch/`（SAD）/ `doc/prd/`（PRD）/ `API.md` / `README.md` / `.opencode/`**；**只增不删编号**；未回改任何历史变更块（旧口径以「已更正 / 已被推翻」标注，保留原文）。

### 1. 变更事实（代码，已落地）

| # | 模块 | 旧 → 新 |
|---|------|---------|
| 1 | `config.py` `DOMAIN_MATRIX['margin']` | `('L4', 2.0, 2.0, 'fixed:16', 'n/a')` → **`('L4', 2.0, 2.0, 'fixed:16', 8)`**（`cache_max`：`'n/a'` → `8`） |
| 2 | `config.py` 矩阵上方注释 | 「仅经共享 URL 缓存取数、`cache_max='n/a'`」清单 `plate / news_url / longhu / margin` → **`plate / news_url / longhu`**（margin 移出） |
| 3 | `market_api.py` 模块级 | **新增**终端缓存三元组：`_margin_cache`(OrderedDict) / `_margin_cache_ts` / `_margin_cache_lock` |
| 4 | `market_api.fetch_margin` | 新流程：参数校验 + `deadline` 入口闸 → **终端缓存命中直接返回**（`move_to_end`，不解析、不计数）→ 未命中才 `metrics.incr('upstream_fetch_total', key='margin')` + `fetch_json`/`json.loads`/`_transform_margin` → **仅 `latest is not None`** 才写缓存并按 `cache_max`(8) LRU 淘汰（**同步删 ts**）；失败/空数据不写 |
| 5 | `upstream_fetch_total{margin}` 语义 | "每次 handler 调用 +1" → **"仅终端缓存 miss 时 +1"**（与 stock 域「终端 miss 才调 fetcher → 计数」对齐） |
| 6 | 测试 | **519 → 525**（6 条：margin 命中不取数 / TTL 过期重取 / LRU 有界 / 失败不缓存 / 空数据不缓存 / 计数仅 miss） |

### 2. 逐处落点（`旧 → 新`）

| 文件 | 位置 | 旧 → 新 |
|------|------|---------|
| `config.md` | 头部 / 版本 | v1.13 → **v1.14**；新增 **v1.14 变更块** |
| `config.md` | §3.1 matrix `margin` 行 | `'n/a'` → **`8`**（注释补「终端缓存上限 8（4 market × 2 余量），margin 不用池」） |
| `config.md` | §3.1 spec 注释 / P7b 语义段 | URL-cache-only 域 `plate/news_url/longhu/margin` → **`plate/news_url/longhu`**（注明 margin 自 v1.14 有终端缓存、上限 8） |
| `config.md` | §3.2 逐域实值表 | `margin … cache_max: null` → **`cache_max: 8`** |
| `config.md` | **BR-CFG-5** | URL-cache-only 域列举**移除 `margin`**；补「margin 自 v1.14 声明 `cache_max=8`」 |
| `config.md` | §8 **CFG-T13** | `plate/margin/news_url/longhu` 的 `cache_max is None` → **`plate/news_url/longhu` is None；`margin.cache_max == 8`** |
| `config.md` | §2.4 迁移行 / §9 / §10#15 / **§10#25（新增）** / §11 | `_MARGIN_CACHE_TTL` 行补注（另消费 `['cache_max']`=8）；补 AC 行；#15 加更正注；新增 #25 登记；新增 v1.14 自检行 |
| `market_api.md` | 头部 / 版本 / 接口权威栏 | v1.7 → **v1.8**；新增 **v1.8 变更块**；接口权威 `config v1.6 → v1.14`、`metrics v1.8 → v1.10`（`cache.md` v1.14 不变） |
| `market_api.md` | §1.1 / §1.2 / §1.3 / §1.4 | 职责新增 #4 终端缓存；**§1.2「不新增缓存容器」更正**为「持有终端缓存三元组」；import 补 `threading`/`collections`；对齐表补 `['cache_max']` |
| `market_api.md` | §2.1 | 补终端缓存语义（命中不解析/不计数、失败/空数据不写、LRU 有界、共享对象） |
| `market_api.md` | §3.3 / **§3.4（新增）** | `cache_max: null` → **`8`**；新增终端缓存三元组 yaml + LRU 说明 |
| `market_api.md` | §4 **BR** | **BR-MKT-9 改写**（仅 miss 计数）；**新增 BR-MKT-13..16**（命中/上限、只缓存可用数据、真 LRU 有界、命中返回共享对象） |
| `market_api.md` | §5 伪代码 | `fetch_margin` 流程重写（终端缓存查找/写回/LRU）+ imports + 模块级三元组 |
| `market_api.md` | §6 / §7 | 错误处理补 3 行（命中/miss/不写/超限）；并发安全由「无锁」改为 **`_margin_cache_lock`**（锁序/共享对象） |
| `market_api.md` | §8 测试 | **MKT-T7 更正**（miss 路径）+ **MKT-T13 更正**（`cache_max == 8`）+ **新增 MKT-T14..T19** |
| `market_api.md` | §9 / §10#4·#10·#11 / §11 / §12 | AC 补行（S9 有界 + 命中零解析 + 不写缓存）；#4 口径更正、#10 加推翻注、新增 #11；自检补 v1.8 行；变更记录补 v1.8 行 |
| `metrics.md` | 头部 / 版本 | v1.9 → **v1.10**；新增 **v1.10 变更块** |
| `metrics.md` | §3.2 表 + 表后注 | `upstream_fetch_total` owner 列 + 注：**语义 = 该域 fetch 路径被调用次数（终端 miss 计一次）**；补 margin 修复前后差异 |
| `metrics.md` | §10#15（新增） / §11 | 登记语义明确；新增 v1.10 自检行 |
| `_PROGRESS.md` | 「当前状态」+ 本节 | 新增登记 |

### 3. 口径边界（**注明，不扩大到范围外文档**）

- **SAD §2.1 / §2.6 矩阵与计分板**：SAD 对 `margin` 的 `cache_max` 与"终端缓存 miss 计数"口径**未定义 / 仍按 URL-cache-only 处理** ⇒ 需 **system-architect 回填**（属 `doc/arch/`，本轮**未改**）。
- **`API.md` / `README.md`**：margin 端点对外契约未变（响应字段集合/HTTP 语义不变）⇒ **无需同步**；若 `API.md` 有 `margin.cache_max` 之类描述则另判（本轮未授权、未查改）。
- **`config.py` 侧"仅经共享 URL 缓存"注释清单**已随代码同步（代码已落地），文档侧本轮对齐。

### 4. grep 自查（**现行有效表述**）

- ✅ `config.md`：**现行有效正文**已无「margin 属 URL-cache-only」或「`margin.cache_max` 为 `null`」——仅剩**历史 v1.2/P7b 行**（已加 ★ v1.14 更正注）与 **§10#15 历史裁决**（已加"★ v1.14 更正"）。
- ✅ `market_api.md`：**现行有效正文**已无「margin 不消费 `cache_max`」——§3.3/§10#10 的旧口径均标注「★ v1.8 更正 / 已被 PRF-LAT-02 推翻」。
- ✅ `metrics.md`：`upstream_fetch_total` 无「URL 缓存命中亦计数（上界）」**现行有效**表述——已由 v1.10 明确为「终端缓存 miss 计一次」，旧口径仅存于 v1.2–v1.9 历史块。
- ⇒ 三份详设的**现行有效正文**口径一致，**无残留矛盾**。
