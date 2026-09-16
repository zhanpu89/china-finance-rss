# 优化专项架构建档（SAD）评审报告（专家版）

> **编号** REV-ARCH-20260915-001 · **日期** 2026-09-15 · **评审模式** 架构评审
> **被评物** `doc/arch/SAD.md`（v1.0 / 649 行 / 8 节）+ `doc/arch/tech-stack.json`
> **对标基线** `doc/prd/perf-stability-optimization.md`（v0.3；30 AC；R1-R20，M7=R1/R2/R5/R12/R14/R16/R18）
> **阶段口径** 优化专项（生产版：P1 即阻断门槛）
> **核对方式** 只读文档 + 只读核对 `china_finance_rss/` 与 `tests/`，验证设计可行性

---

## 一、评审概要

| 项 | 值 |
|----|----|
| 结论 | ❌ **阻断** |
| P0 | 1 |
| P1 | 7 |
| P2 | 8 |

**放行部分（先说好话）**：SAD 是一份"读懂了代码"的架构文档。根因归类（架构级 15 / 实现级 4）、`cache_policy` 单一权威 + INV-1、负缓存三段式、`_guard(shape)`、值域三分 + 下划线保留键、不可变组状态 + 锁外帧构建、metrics 计分板，均可由标准库实现，**零第三方依赖成立**。对现状的核对多处准确且可复核：R5「`patch_group` 整体赋值而非原地变更」（stream.py:318 属实）、R9 fall-through 13.5s（cache.py:111-141 属实）、R2 串行 5 源（server.py:438-454 属实）、R12 三层常量（config.py:28/120-126 属实）、R18 `.get('timeline')` 可为 None（server.py:279/290 属实）。

**阻断原因**：§2.2 的资源有界模型与 §4.2 的帧共享模型**自相矛盾**（P0-1），使本次新增的"全局队列字节预算"——唯一能兜住"组×码×帧"内存爆炸的机制——按构造必然失效；另有 7 项 P1 使 AC-S3 / AC-S6 / AC-S8 / AC-S9 / AC-E9 / AC-A3 或"必然过不了"，或"论证不成立"。

### M7 必做风险逐项解决情况

| R | 现象 | SAD 设计落点 | 判定 | 残留 |
|---|------|-------------|------|------|
| R1 裸崩 | 13/14 个 JSON 分支无 try | §2.4 `_guard(shape)` + ADR-007 | ✅ 解决 | 端点计数错（P1-6） |
| R2 healthz 放大器 | check=1 串行 5 源、最坏 50s、抢主池 | §2.6 专用执行器 + 10s 预算 + check=0 零上游 | ⚠️ 部分 | 降级路径不可达（P1-3） |
| R5 stream codes 竞态 | 无锁遍历 `g.codes` | §2.5 `frozenset` + 快照广播 + ADR-004 | ✅ 解决 | — |
| R12 三层新鲜度断崖 | 120s × 8s × 120s | §2.1 `cache_policy` + `ttl_terminal == ttl_url` | ✅ 解决 | 池容量不自洽（P1-1） |
| R14 失败≡null | 失败压成 None | §2.4 `_errors` + 值域三分 + 单一组装点 | ✅ 解决 | — |
| R16 TTL 无单一来源 | 7 类独立常量 | §2.1 `cache_policy` + 禁裸字面量 | ⚠️ 部分 | 缺 `longhu` 域（P1-4）；announcement 口径悬置（Q5） |
| R18 CDP 页面裸崩 | `_fill_missing` 假定 dict | §2.4 `cdp_page_data` 防御取数 + A 类补 error 客体 | ✅ 解决 | 命名不一致（P2-5） |

> 备注：R12/R16 的**机制**是对的（单一权威 + 可断言不变式），残留问题不在"是否解决了根因"，而在"新引入的资源模型与既有容量参数不自洽"，故不计入 ❌。

---

## 二、问题清单

### P0（必须修，架构级缺陷）

**【P0-1】§2.2 R-2 vs §4.2：SSE 队列字节预算的计费模型与"帧共享"模型互斥**
- **位置**：§2.2 R-2「每次入队前累加 `len(frame)`」× §4.2「帧对象**同组共享同一 str 引用**，不产生 100 份拷贝——这是内存与耗时同时达标的关键」。
- **问题**：两处对同一机制的建模互相否证。若帧按引用共享（§4.2），则"每次入队累加 `len(frame)`"会把同一帧按连接数重复计费：100 连接 × 1 帧 × 14MB = 计 1.4GB（实际占用 14MB）→ **预算按构造必然超限、每 tick 无条件丢帧**，`stream_queue_bytes` 指标失真，AC-E5「任一连接队列丢弃 ≤1 帧」与 AC-A2 直接落空。反之若真按"每连接一份拷贝"计费，则 §4.2 的内存结论（"这是内存与耗时同时达标的关键"）与 §4.3 的"SSE 队列 ≤64MB"全部作废。**两种口径不能同时成立，必须二选一**。
- **放大效应**：`MAX_GROUPS=200` 只挡碎片化组，**不界内存**——不同组的帧是不同对象，理论上限为 Σ组(帧字节)×队列深度，200 组 × 8 深 × 帧字节可达 GB 级。因此该预算是这套内存模型里**唯一**的护栏，护栏算错 = 无护栏。
- **修正建议**：把计费口径钉死为"**distinct 帧对象字节 × 深度**"（每组每 tick 记一次 `len(frame)`，队列字节 = 各组 `frame_size × 当前深度` 求和；`conn.q` 只存引用、不重复计入），并给出预算与"组数×帧字节×深度"的**推导式**及触发丢弃时的确定性行为（丢哪一组的哪一帧、是否保最新）。同时明确"单帧字节上界"（200 码 × 3 字段）与 64MB 预算的对应关系。
- **关联**：R7；AC-E5 / AC-E7 / AC-A2；ADR-004 继承风险。

### P1（应修，生产版阻断）

**【P1-1】§4.3：L1 域池上限 500→200 与 `MAX_DEDUP_CODES=2000` 不自洽，INV-1 的"必然覆盖"不成立**
- **位置**：§4.3「令池上限 = `MAX_CODES_PER_SUB = 200`，则'一个 L1 周期内 prefetch 必然覆盖整个池'成立」。
- **问题**：池是**跨组共享**的（`_fundflow_pool` / `_basic_info_pool` / `_timeline_pool` 为模块级单一 dict，被所有组共用），而 `MAX_CODES_PER_SUB=200` 是**单组**上限；`MAX_DEDUP_CODES=2000` 允许**活跃码总数达 2000**。只要有 ≥2 个不重叠的活跃组（如 2×200=400 码），活跃码数 > 200 池上限：`_process_chunk` 每处理一块就把整池轮换一遍并 `cache.pop`，端点缓存被反复抖空 → 每 tick 大量回源（**L1 新鲜度反而更差**），INV-1 与 AC-A3 的"陈旧度 ≤ L1×1.2"前提被破坏。SAD 把该 200 的推导建立在"单组"假设上，却未在 §7.3 假设清单里声明该假设。
- **附带**：AR-1（"2000 码全量刷新超 tick 预算"，等级=高）的缓解被写为"池上限=200/域"，但 tick 的刷新集是 `_active_codes()`（可达 2000），**不受池上限约束**——该缓解对 AR-1 无效。
- **修正建议**：池上限改由"**活跃码总上界**"推导（或与 `MAX_DEDUP_CODES` 联动给出容量公式：`pool_max ≥ ceil(concurrency × pool_refresh / per_fetch)` 且 `≥ 活跃码数`），若坚持 200 则必须把"同一时刻活跃码 ≤200（单活跃组）"写成显式假设并给出违约时的行为；AR-1 的缓解改为直接约束 `_active_codes()`（分片刷新 / tick 内只刷子集 + 轮转）。
- **关联**：R12 / R7；AC-A3 / AC-A7 / AC-E5 / AC-S9；AR-1。

**【P1-2】§2.3 D-1：AC-S3 模式 B 的"P95 ≤3s"论证不成立（NEG_TTL 5s < REQUEST_TIMEOUT 10s）**
- **位置**：§2.3「模式 B（黑洞）——首请求耗尽 10s 超时并落负缓存，其后 5s 窗口内全部 <1ms 失败，5min 窗口 P95 ≤3s」。
- **问题**：该结论只在"偶发单请求"下成立。AC-S3 明确要求"**持续**请求全部 REST 端点 5min"。稳定负载下每个 URL 的周期是 **10s 阻塞 + 5s 快失败 = 15s**：负缓存写入前，leader 阻塞 10s，且按 §2.3 第 3 步"follower 等待 leader 结束"——窗口 [0,10s) 内到达的**所有**请求（含所有 follower）都阻塞约 10s；仅 [10s,15s) 的请求快速失败。慢请求占比 ≈ 10/15 ≈ **67%** ⇒ P95 ≈ 10s，**远超 3s**。这不是实现问题，是 `NEG_TTL < REQUEST_TIMEOUT` 导致的数学必然。
- **修正建议**：三选一并写明推导（给出"慢请求占比 = T_slow / (T_slow + NEG_TTL)"的证明）：
  ① `NEG_TTL ≥ REQUEST_TIMEOUT + ε`（如 12s），使快失败窗口占主导（慢占比 ≈ 10/22 ≈ 45%，仍不达 95%）→ 需更长冷却；
  ② follower 采用**短有界等待**（如 `min(remaining, 1s)`）后即以 `upstream_timeout` 落负缓存失败（牺牲"同批请求全成功"，换 P95），并论证不会误伤慢而成功的 leader；
  ③ 负缓存改为**粘性延长**（每次失败刷新 `until`），使稳定故障期只剩首请求慢。
  无论选哪种，必须同步复算 AC-S3 模式 B 的 P95 与"单请求 ≤15s"。
- **关联**：R9；AC-S3 / AC-S6；ADR-003。

**【P1-3】§2.6：healthz 专用执行器的"降级为 stale"路径**不可达**，洪峰下队列无界**
- **位置**：§2.6「执行器忙（无法提交）→ 直接返回上次快照 + `"stale": true`，**绝不阻塞请求线程超过 ~50ms**」。
- **问题**：`concurrent.futures.ThreadPoolExecutor.submit()` 的工作队列**无界**，`submit()` 除已 shutdown 外**永不失败**——"无法提交"这一分支是死代码，`stale` 永远不会返回；`max_workers=5` 下，healthz 洪峰（10 并发 × 5 源 = 50 任务）会持续堆积任务（每个任务最长占 10s），队列与内存无界增长。SAD 的"物理隔离 = 有界"结论因此不成立：隔离只保证了**主池**不被抢，**没保证**健康检查自身的资源有界。
- **修正建议**：引入显式饱和判据（`MAX_HEALTH_INFLIGHT` 信号量或 `_health_inflight` 计数 ≥ 阈值即返回上次快照 + `stale:true`），或使用固定容量队列 + 拒绝策略；并要求该路径**可被测试触发**（否则 AC-S8/S10 的"隔离"无法断言）。
- **关联**：R2；AC-S8 / AC-S10；ADR-006。

**【P1-4】§3 + §2.1：「`/ths/longhu` 改走 `fetch_json`（L4）」不可实现，且 `longhu` 域缺失**
- **位置**：§3 server.py 行「`/ths/longhu` 改走 `fetch_json`（L4）」；§2.1 `DOMAIN_MATRIX`（无 `longhu` 域）。
- **问题（两处，都会让 AC-E9 无法落地）**：
  ① `fetch_json` 内**硬编码** `resp.read().decode('utf-8')`（cache.py:95/137），而 `handle_ths_longhu` 的上游是 **GBK** 页面，现用 `.decode('gbk', errors='replace')`（server.py:151/178）。按 SAD 直接改走 `fetch_json` 会解码失败或乱码（`longhu` 含中文券商名/股票名，必现）。
  ② AC-E9 要求"已配置 L4 TTL 缓存（交易时段 TTL ≥300s）"，而 §2.1 明文规定"**禁止任何模块出现裸 TTL 数字字面量**"、一切经 `cache_policy(domain)` 派生——但 `DOMAIN_MATRIX` 里**没有** `longhu` 域。设计自我封闭的规则下，E9 的 TTL 无权威来源可取。
- **修正建议**：给 `fetch_json` 增加 `encoding='utf-8'` 参数（默认值不变，向后兼容）或改为"缓存解析后的结构"；在 `DOMAIN_MATRIX` 增加 `longhu: ('L4', ...)` 行并说明 `max_entries`；AC-E9 的"上游请求计数 = 1"需澄清：该端点每次请求打 **2 个** 上游 URL（lhbtable + longhu 页），计数口径应写成"每 URL 各 1 次"。
- **关联**：R15；AC-E9；ADR-001。

**【P1-5】§2.4 / §2.6：AC-S6 的"同码连续失败 3 次 → 120s 冷却期"在批量请求路径无设计落点**
- **位置**：§2.6 指标表「`code_cooldown_count` | prefetch 循环的 fail 冷却表」；§8 追溯矩阵「保留键契约… | S6」。
- **问题**：AC-S6 的断言发生在**批量请求路径**（"批量请求 50 码…同码连续失败 3 次后进入冷却期（120s），冷却期内该码不回源（按上游请求计数验证）"）。但代码中 `_FAIL_COOLDOWN=120` **只存在于 4 个 prefetch 循环**（stock_api.py:342/434/564/767），`_process_chunk` → `_run_batch` → `_fetch_one` 的请求路径**没有任何冷却判断**；SAD 新增的负缓存 `NEG_TTL=5s ≠ 120s`，且其指标来源被明写为"prefetch 循环的 fail 冷却表"，等于承认覆盖不到批量路径。→ **AC-S6 按本设计过不了**。
- **修正建议**：明确冷却层归属（URL 级 vs 码级）、判定位置（`_process_chunk` 命中前 / `fetch_json` 入口）与计数口径，并说明与 5s 负缓存的关系（120s 码级冷却 vs 5s URL 级冷却是否叠加）；`code_cooldown_count` 改为可导出清单（AC-S10 原文是"冷却**清单**"）。
- **关联**：R14 / R9；AC-S6 / AC-A10 / AC-S10。

**【P1-6】§1.1 / §2.4 / §3：`_guard` 的端点计数为 13，实际为 14 个 JSON 分支**
- **位置**：§1.1「13 个 JSON 分支」；§2.4「用 4 种形状覆盖全部 13 分支」；§3「覆盖全部 13 个 JSON 路由分支」。
- **问题**：逐一核对 `_handle_request`（server.py:553-603），JSON 分支为 **14** 个：4 面板（/finance/market、/finance/timeline、/quotation/market、/market/timeline）+ 6 stock（data/fundflow/timeline/f10/basic_info/announcement）+ /cls/hotplate + /cls/plate + /ths/longhu + /market/margin。三处一致写 13，说明是**同一个漏数**被复制了三遍。AC-S1 的验收口径是"**逐个端点**注入异常"，少了哪一个取决于实现者怎么枚举——这正是"看着覆盖了、其实漏一个"的典型。
- **修正建议**：改为 14 并**逐一列名**（或改为"由路由表派生，不写死数字"），同步修正 §1.1/§2.4/§3 三处。
- **关联**：R1；AC-S1 / AC-S4 / AC-A5。

**【P1-7】§3 tests + PRD §9 不变量：负缓存改造必然打破存量用例 `test_fetch_json_leader_failure_does_not_stampede`**
- **位置**：§3 tests 行（只列"新增"用例）；PRD §9「不变量：51 个存量单元用例保持全绿」；ADR-003「删除 fall-through…所有调用点需确认覆盖」。
- **问题**：`tests/test_server.py:298-367` 显式断言"leader 失败后 follower **重入选举**、恰好 1 个 err、7 个 ok、上游并发恒为 1"——这正是 SAD 要删除的语义与 `fetch_json` docstring 所记载的契约（cache.py:65-70）。按 §2.3 三段式，leader 失败后 follower **读负缓存并 raise**，该用例必然变成 `ok=0, err=8`。SAD 只在 AR-4 提到 `_run_batch` 签名的调用点，**未登记任何需改写的存量用例**，与 PRD 的硬不变量直接冲突。
- **修正建议**：在 §3 tests 行显式登记"**改写**存量用例"清单（至少该条），并把新不变量写成可断言形式（"失败后 follower 不触网，单飞期间上游请求数 ≤1/URL，且冷却窗口内请求 <1ms 失败"）；PRD §9 的"51 全绿"应改为"51 中 N 条语义变更并通过，其余全绿"。
- **关联**：R9；AC-S3 / AC-S1。

### P2（建议）

| # | 位置 | 问题 | 修正建议 | 关联 |
|---|------|------|---------|------|
| P2-1 | §4.3 资源上界表 | 线程总账写"后台线程 ≈9…**不变**"，但 §2.6 新增 `_health_executor(max_workers=5)`，表内未计 5 条线程 → 总账不自洽 | 表内补 `health executor 5`，并注明懒创建、计入 AC-S9 的"基线+20" | AC-S9、R2 |
| P2-2 | §3 cdp_engine.py 行 | "守护重启交易时段避让"归属错误：`_cdp_memory_watchdog` 在 **server.py:881**（非 cdp_engine.py），`_is_trading_hours` 在 config.py → code-developer 会找错文件 | 模块归属改为 server.py；cdp_engine.py 只保留窗口状态机与页面数联动 | R19、AC-S4 |
| P2-3 | §2.6 vs §7.1 Q2；§2.3 D-4 vs ADR-007 | 两处自相矛盾：① §2.6「**不改**既有 `feeds[]` 字段与含义」vs Q2「同步 health 负载 CDP 标注」；② §2.3 D-4「`/cls/hotplate` 改为**单体 error 客体**」vs ADR-007「可按需精细化（**逐板块 error**）」 | 二者均需二选一并删除另一表述；health 标注修正需明确"改既有字段**取值**"并走编排层批准 | AC-S4、AC-A5、R19 |
| P2-4 | §2.4 / §3 | 可执行性缺口：`cdp_page_data`（§2.4）与 `page_data`（§3）命名不一；`build_batch_response`"单一组装点"与"`server._handle_stock_batch` 计算 `dropped` 并透传"的**职责边界**未定（handler 返回 results+errors 还是已组装结构？）；`_guard` 声明"路由分发处统一套用"与批量路径经 `_handle_stock_batch` 的实际结构不吻合 | 给出 `handler → _guard → build_batch_response → server 注入 dropped` 的**调用顺序图**与各函数签名 | R4/R14；AC-A9/A10 |
| P2-5 | §2.1 DOMAIN_MATRIX | `plate` 域为单值 `ttl`，无法表达现有 `/cls/hotplate`·`/cls/plate` 的 **3 分 stagger**（`_STAGGER=max(3, L2//4)`，server.py:300-302/338-339）；`announcement` 域 tier 悬置（Q5），且 `fetch_cls_announcement` 的裸 `ttl=15` 未进入变更矩阵 | 矩阵增加 `stagger` 维度或明确"offset 由 handler 内部派生、仍属 policy 派生"；Q5 定案后回填；把裸 `ttl=15` 列入 §3 stock_api 行 | AC-E9/E6；Q5 |
| P2-6 | §2.6 healthz 字段 | 新增字段只写"`policy`（摘要）""`cdp`（窗口状态）"，**无字段名/类型/嵌套结构** → task-decomposer 无法转契约；AC-S10 要求的是"冷却**清单**"，而 `code_cooldown_count` 只是一个计数 | 给出 `metrics`/`policy`/`cdp` 的精确 JSON schema；冷却改为可枚举清单（或声明 AC 口径降级并回报编排层） | AC-S8/S10 |
| P2-7 | tech-stack.json | 合规自洽性：`importRestrictions.allowlist` **未列 `websocket`**，而 cdp_engine 有函数内 `import websocket` → 与 §6"可选依赖、不得提升为硬依赖"冲突，合规脚本会误报；`fileStructure.forbidden` 含 `src/` 字样但代码根是 `china_finance_rss/`；`namingRules.fetch` 的 `fetch_*(code, deadline=None)` 无法涵盖 `fetch_cls_telegraph(feed_url=None)` 等非码取数器 | allowlist 增 `websocket` 并加"仅函数内、可选"注释，或让脚本忽略函数级导入；修正 `src/` 表述；naming rule 改为"`fetch_*`，码取数器签名 `(code, deadline=None)`" | 零依赖硬约束、§6 |
| P2-8 | §7.2 / §2.2 / §2.3 D-2 | ① `MAX_GROUPS=200` 引入 PRD 未定义的**新 400 失败模式**（对外可观测），未作为契约新增登记；② 无"回滚/止血预案"节（check-arch 部署项）；③ `chunk_budget = ceil(len(chunk)/BATCH_MAX_WORKERS)×PER_CALL_TIMEOUT` 对 `concurrent=False` 的 F10（串行）**低估预算**，会过早中止 f10 批；④ `/cls/plate?code=` 无输入校验（code 直入签名 URL） | ① 登记为端锁定新增项；② 补"回滚 = 回滚镜像，无持久状态迁移"一节；③ 串行路径用 1 作分母；④ 补 `VALID_STOCK_CODE/PLATE_CODE` 校验（可列为 out-of-scope 但需登记） | AC-A7/E9/S5 |

---

## 三、待裁决项裁决建议（Q1 / Q2 / Q3）

### Q1 —— AC-E4 指标反向修正：**依据不充分；不改 PRD 指标、不改 MAX_WORKERS，改 SAD 的论证方式**
- **裁决**：**不改 PRD 的"≥80%"，也不把命中率写成新 AC**；保留 `MAX_WORKERS=20`（守 AC-E8/EFF-3）；把"命中率 ≥90%"降格为 **SAD 内部设计目标 + `/healthz` 观测项**（即现有 AR-2 的定位）。
- **理由**：
  1. **数学依据不成立**。Little's Law 的 `W_avg` 是**均值**服务时间，SAD 代入的 `W_miss=1.2s` 是 AC-E2 的 **P95**、`W_hit=5ms` 也是 P95；均值必然 ≤P95 且通常明显更低。故 `C=24.4` 是"以 P95 为均值的**保守上界**"，不等于真实平均并发，**"≥80% 不可达"未被证明**（按 SAD 自己的临界点 0.84 反推，只要真实均值低于 P95 约 2%，80% 即可达）。
  2. **AC-E4 的可断言部分与命中率无硬绑定**：原文是"错误率 = 0，且后 3min P99 不劣化 >20%"；PRD 头部与 §9 明写"全部延迟/吞吐目标为**建议值，待 P6c 实测校准**"。用解析式覆盖"待校准"的实测口径，属越权。
  3. **若真要改，也应在实测之后走 PRD 流程**：P6c 实测命中率 <84% 时再修订 PRD，且修订依据是实测分位数而非保守上界。
- **落地**：SAD §4.2 把 24.4 标注为"上界（均值取 P95）"，补一句"命中率为设计目标、不构成 AC 修订"；§1.3 的"AC-E4 边界不可达"改为"在上界口径下临界"。

### Q2 —— 三条 CDP 契约漂移：**分类（B / B / A′）与 PRD §7.2 一致，确认；但 SAD 内部矛盾必须先消除，同步权归编排层**
- **分类裁决**（与 PRD §7.2 一致，逐条核对代码后确认）：
  | 端点 | 错在哪 | 目标值 | 依据 |
  |------|--------|--------|------|
  | `/stock/data` | **health 负载**标 `requires_chrome_cdp`（server.py:465-467）+ 首页 CDP 列；API.md 已对 | health → `configured`（B 类） | API.md §2「CDP: 否」 |
  | `/stock/basic_info` | **API.md 与 health 双错**（server.py:488-491）；实现两阶段均 REST | health → `configured`（B 类）；API.md 同步 | stock_api.py:628-669 头注 + 两阶段 REST |
  | `/stock/f10` | **health/首页双错**（server.py:484-487 `configured`、:758 `needs_cdp=False`）；实现真依赖 CDP | health/首页 → CDP（A′ 类） | `fetch_cls_f10` → `_navigate_f10` |
- **谁在何时做**：按 PRD §7.2「契约修改权在编排层」，由**编排层**在本 SAD 通过后、详设（task-decomposer）启动前统一 dispatch，一次性对齐 API.md + `/healthz` 负载 + 首页三处；SAD 只输出"目标值清单"，**不改契约**，且必须删掉 §2.6「不改既有 `feeds[]` 字段与含义」这句与之冲突的表述。
- **端锁定提示**：`feeds[].status` 的取值由 `requires_chrome_cdp` 改为 `configured` 属"**改既有字段取值**"（≠只增），需编排层在 🟠 STABLE 下显式批准并记入变更日志。

### Q3 —— feed 缓存 300s → L3(30s)：**确认本次变更，必做**
- **裁决**：确认。交易时段 `30s`、非交易时段 `180s`，由 `cache_policy('feed')` 从 L3 派生，与 `_cache_age()` 读同一来源。
- **理由**：PRD SCN-2 明写"L3=30s 新鲜度"，且 `_cache_age()` 已向客户端承诺 `max-age=30`（server.py:700-702）而实际给 300s（server.py:668）——这是**已生效的对外矛盾**，不修则 SCN-2 与 AC-A8 同时不成立。D4 的发现成立（已读代码复核）。
- **必须一并处理的副作用（否则会连带打破其他 AC）**：
  1. `CACHE_TTL` 是**多消费者常量**（cache.py:9/29 默认 ttl、utils.warm_jin10、server.py feed）——删常量前逐点迁移到 policy，否则 jin10 取数丢缓存或报错。SAD §3 config.py 行未列第二阶消费者。
  2. **非交易时段 300 → 180** 也在变，SAD 只写了交易时段口径。
  3. feed 缓存 LRU 改造的落点在 **server.py `_get_or_fetch_feed`**，§3 server.py 行漏列该函数。
  4. AC-A8 的"2×TTL"测试口径同步（SAD 已列，保留）。
  5. 上游请求量 ×10（AR-6 已登记）：建议每源 fetch 计数入 metrics。

---

## 四、AC 覆盖缺口清单

| AC | 状态 | 缺口 | 对应问题 |
|----|------|------|---------|
| AC-E4 | ⚠️ | 指标反向修正依据不充分（以 P95 当均值） | Q1 |
| AC-E7 | ❌ | 队列字节预算计费模型与帧共享模型互斥 | P0-1 |
| AC-E9 | ❌ | `fetch_json` 硬编码 utf-8（longhu 为 GBK）+ `DOMAIN_MATRIX` 无 `longhu` 域 | P1-4 |
| AC-A3 | ⚠️ | L1 域池 200 < 跨组活跃码上限 2000，INV-1"必然覆盖"不成立 | P1-1 |
| AC-S4 | ⚠️ | CDP 标注漂移未定案，且与 §2.6「不改 feeds[]」矛盾 | Q2 / P2-3 |
| AC-S6 | ❌ | "3 次失败→120s 冷却"在批量请求路径无设计落点 | P1-5 |
| AC-S8 | ⚠️ | 专用执行器无饱和判据，stale 降级不可达 | P1-3 |
| AC-S10 | ⚠️ | "冷却清单"降格为计数；`/healthz` 新字段无精确 schema | P2-6 |
| AC-S11 | ❌ | §8 声称 "S1-S11 = 30/30"，但全文**无任何 S11 设计点**（断线重连并续帧）；实际依赖既有行为，需显式写成"不改动 + 断言依据"，否则属覆盖声明失实 | §8 |
| 其余 21 条 | ✅ | E1/E2/E3/E5/E6/E8；A1/A2/A4/A5/A6/A7/A8/A9/A10；S1/S2/S3/S5/S7/S9 均可追溯到设计点 | — |

**覆盖声明失实**：§8「30 条 AC…本 SAD 直接设计覆盖 30/30」与上表不符（E9/S6/S11 无有效设计点，E4/E7/A3/S4/S8/S10 部分）。建议改为逐条状态表，避免给编排层/测试方虚假安全感。

---

## 五、评审结论

**❌ 阻断**。SAD 的机制设计（单一权威、失败状态层、资源总账、形状化异常边界）方向正确且零依赖成立，具备进入下一轮的价值；但存在 1 项 P0 与 7 项 P1，其中 P0 使新增内存护栏按构造失效，P1 使 AC-S3 / AC-S6 / AC-E9 / AC-A3 无法通过、AC-S1 可能漏端点、PRD 的"51 用例全绿"不变量被破坏。

**阻断解锁条件（必须全部修正后方可复审放行）**：

1. **P0-1** 重写 SSE 队列字节计费口径（distinct 帧 × 深度），给出推导式与确定性的丢弃行为。
2. **P1-1** 池上限与"活跃码总上界"自洽（或把单活跃组写成显式假设），并让 AR-1 的缓解对准 `_active_codes()`。
3. **P1-2** 复算 AC-S3 模式 B 的 P95，并选定"负缓存窗口 / follower 短等待 / 粘性冷却"三者之一的时序方案。
4. **P1-3** 为 healthz 执行器定义**可触发的**饱和判据（有界在飞计数或定容队列），并给测试留钩子。
5. **P1-4** `fetch_json` 增加 `encoding` 参数（或缓存解析结果）+ `DOMAIN_MATRIX` 补 `longhu` 域 + 澄清 AC-E9 计数口径。
6. **P1-5** 明确 AC-S6 冷却层的归属、判定位置与计数口径。
7. **P1-6** 端点计数 13→14 并逐一列名（或改为由路由表派生）。
8. **P1-7** 登记需改写的存量用例，修正 PRD §9 的"51 全绿"不变量表述。

**复审方式**：仅复审上述 8 项 + Q1/Q2/Q3 三项裁决的落地文本；P2 项不阻断，但建议同轮一并修（尤其 P2-3 的两处自相矛盾会直接误导 code-developer）。

---

## 变更记录

| 版本 | 日期 | 说明 |
|------|------|------|
| v1.0 | 2026-09-15 | 首轮架构评审（REV-ARCH-20260915-001）：❌ 阻断；P0×1 / P1×7 / P2×8；Q1/Q2/Q3 裁决；AC 覆盖缺口 9 条 |
