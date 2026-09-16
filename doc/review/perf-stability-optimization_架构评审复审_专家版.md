# 架构建档（SAD）复审报告（专家版）— v1.1

- **报告编号** REV-ARCH-20260915-002（复审）
- **日期** 2026-09-15 · **评审模式** 架构复审（P0-1 + P1-1~P1-7 闭环核验 + Q1/Q2/Q3 + §8 + 新缺陷扫描）
- **被评物** `doc/arch/SAD.md`（v1.1 / 903 行 / 9 节）+ `doc/arch/tech-stack.json`（v1.1）
- **前次报告** `doc/review/perf-stability-optimization_架构评审_专家版.md`（REV-ARCH-20260915-001：❌ P0×1 + P1×7 + P2×8）
- **对标基线** `doc/prd/perf-stability-optimization.md`（v0.3；30 AC；R1-R20；M7）
- **阶段口径** 优化专项（生产版：P1 即阻断门槛，与前次报告一致）
- **只读核对依据** `china_finance_rss/{server,stream,cache,config,stock_api}.py`、`tests/test_server.py`（未运行测试，仅静态核对）
- **结论** **❌ 仍阻断**（P0×0 / P1×2）——上轮 8 项阻断的**机制**均已修好，但两项中央修复（P0-1 帧计费、P1-1 覆盖模型）各残留 1 处"必须补齐才可实现/照做即违约"的缺口。最小放行集 = 2 项本地修正（约 10 行文档改动，无需重写机制）。

---

## 一、上轮阻断项逐项核验

| # | 修订方声称 | 核验证据（SAD 行号 / 代码） | 判定 |
|---|-----------|---------------------------|------|
| **P0-1** | 计费改「distinct 帧对象字节 × 深度」引用计数（`_Frame{payload,refs}`，入队 0→1 加 / 出队 1→0 减）；F_max≈14MB、单组 8 深 ≤112MB、B=128MB、可保留满尺寸帧≈9；MAX_GROUPS=CPU 护栏 / 字节预算=内存护栏职责分离 | §2.2 L219「不是每次入队累加 `len(frame)`」；§4.2 L576-600 完整推导式；ADR-013 L730-735。**推导自洽**：F_max = 200 码 × 3 字段 × 23KB ≈ 200×70KB = 14MB（与代码 `stream.py:73 payload_bytes = len(codes)*70*1024` 同源）；8×F_max = 112MB ≤ B = 128MB ✓；B ≤ 256MB（AC-E7 占位）✓；floor(128/14) = 9 ✓。代码侧确认「每组每 tick 只构建一个 frame 传给该组全部连接」（`stream.py:191-198` 同一 `frame` 引用 `put_nowait` 进所有 conn），故 distinct 计费才是正确模型，「每入队累加」确为错误模型。**§2.2 与 §4.2 的互斥已消除**（全文无残留「每次入队累加」表述，§4.3 内存表同步为「SSE 队列 ≤128MB」） | ✅ **闭环**（附 P1-N2 残留） |
| **P1-1** | 池上限改 `MAX_DEDUP_CODES=2000`、池成员账与终点缓存解耦、INV 拆 1a/1b（条件 C1: N_active≤213）、AR-1 改约束 `_active_codes()` 分片轮转 | §2.1 三层缓存表 L191「池淘汰不再 `cache.pop`（解耦）」+ INV-1a/1b L173-185；§4.3 L628-636 自洽推导；§2.2 R-6 L234-239；§7.2 AR-1 L793。代码侧确认根因属实：`stock_api.py:146-151` 池超限即 `cache.pop` + `cache_ts.pop`（正是 P1-1 的"抖空"）；`stream.py:104-120 _active_codes()` 仅含**有活连接的组**的并集，上界确为 `MAX_DEDUP_CODES`、**不受池上限约束**（AR-1 原缓解对准错误对象属实）。`pool_max = MAX_DEDUP_CODES = 2000` 与单组上限 200 的关系写清（L220「200 组 × 200 码 > 2000，码上限才是主导约束」） | ✅ **机制闭环**（附 P1-N1 数值残留） |
| **P1-2** | 新增半开探测 `PROBE_TIMEOUT=2s`（仅有失败历史的 URL）+ `NEG_TTL=5s` → 模式 B P95 ≤2s | §2.3 D-1 L254-256、L262-266（四段式）；推导 L269-275；ADR-003 L663-664；§4.1 L550；§7.1 Q6。**复算通过**：稳态周期 = 探测 2s + 负缓存 5s = 7s，慢请求占比 = 2/7 ≈ 28.6% < 5% 分位阈值 ⇒ P95 = 2s ≤ 3s ✓；单请求阻塞 ≤ max(10s 首次, 2s 探测) ≤ 15s ✓；并明确"仅对**有失败历史**的 URL 生效"以免误伤慢而成功的回源（AC-E2 不受影响）。原错误（`NEG_TTL 5s < REQUEST_TIMEOUT 10s` ⇒ 慢占比 10/15 ≈ 67% ⇒ P95≈10s）已被显式点出并订正 | ✅ **闭环** |
| **P1-3** | healthz 改 `BoundedSemaphore(5)` 有界准入 + stale 可达 + 新指标 | §2.6 L479-489（准入伪码 + `MAX_HEALTH_INFLIGHT=5` = 执行器 worker 数）；ADR-006 L686；§4.3 L623-624。明确点出 `ThreadPoolExecutor.submit()` 队列无界永不拒绝 ⇒ 原"执行器忙→stale"是**死代码**，并给出可触发的替代判据与测试钩子（注入 >5 并发慢 check） | ✅ **闭环** |
| **P1-4** | `fetch_json` 加 `encoding` 形参、longhu 显式 gbk、DOMAIN_MATRIX 补 longhu 域(L4/300s) | §2.3 D-5 L310-322；§2.1 L157 矩阵行 + L164 `cache_policy('longhu')` + L170 说明；ADR-001 L651。代码侧确认：`cache.py:95/137` 确为硬编码 `.decode('utf-8')`（两处）；`server.py:151/178` longhu 两处 URL 确为 `.decode('gbk', errors='replace')`；`DOMAIN_MATRIX` 原无 longhu 域属实。AC-E9 计数口径已澄清为"每 URL 各回源 1 次，共 2 次"（L322）。默认 `utf-8` 向后兼容，既有调用点零改动（codegraph 实测 `fetch_json` 有 **18 个调用者**，与 SAD 声称的 18 一致） | ✅ **闭环** |
| **P1-5** | 新增模块级 `_fail_ledger`（码级 120s 冷却）批量与 prefetch 共用 | §2.3 D-6 L324-347（归属/判定位置/计数口径/与 URL 负缓存叠加关系全给）；ADR-014 L737-742；§2.6 L472 `code_cooldown_list` 改为**可枚举清单**；§4.3 L620。代码侧确认现状：`stock_api.py:57 _FAIL_COOLDOWN=120` + 4 处局部 `fail_blacklist`（L310/402/531/735，即 4 个 prefetch 循环），而 `_process_chunk`（L122-179）**无任何冷却判断** ⇒ 批量路径确无落点，SAD 根因描述属实且修复对准 | ✅ **闭环** |
| **P1-6** | 端点计数 13→14，五处统一并逐一列名 | 代码侧逐一枚举 `server.py:553-603` JSON 分支 = 面板 4（`/finance/market` `/finance/timeline` `/quotation/market` `/market/timeline`）+ stock 6（`data/fundflow/timeline/f10/basic_info/announcement`）+ `/cls/hotplate` `/cls/plate` `/ths/longhu` `/market/margin` = **14** ✓。SAD 已在 §1.1 L41-43、§1.2 R1 L83、§2.4 L394（逐一列名 + 建议由路由表派生 shape）、§3 L515、ADR-007 L692 五处统一为 14（全文 grep 无残留"13 分支"） | ✅ **闭环** |
| **P1-7** | §3 显式登记改写 `test_..._does_not_stampede`（err=8 / max_active=1） | §3 tests 行 L521 显式写「**改写**存量：`test_fetch_json_leader_failure_does_not_stampede`（新语义：leader 失败 → follower 读负缓存、不触网、不重入选举；断言改为 `err=n`、`max_active=1`、冷却窗口内 <1ms 失败）」；AR-10 L802 声明"51 条基线中 1 条按新语义更新并通过，其余 50 条全绿"并标注 PRD §9 表述待编排层同步。代码侧确认被改用例存在（`tests/test_server.py:298-363`，现断言 `err==1 / ok==7 / max_active==1`），改造后语义必然反向 ⇒ 登记属实。**残留（P2）**：§3 写 `err=n` 与 AR-10 写 `err=8` 表述不一 | ✅ **闭环** |

**核验小结**：8 项阻断的**机制层**全部修复，无一遗留原缺陷表述（全文无"每次入队累加 `len(frame)`""13 个 JSON 分支""不改既有 `feeds[]` 字段与含义""池上限=200 必然覆盖"等旧文本）。P1-N1 / P1-N2 均为**本次修订新引入或未收口**的缺口（见 §三、§四），不是上轮问题的复发。

---

## 二、上轮已 ✅ 项的快速回归（确认未被改坏）

| 项 | 上轮判定 | 本轮核对 | 结论 |
|----|---------|---------|------|
| **R1**（`_guard` 统一异常边界） | ✅ | §2.4 L385-396 `shape ∈ {batch,object,rss,text}` 覆盖 **14** 分支；§3 L515；ADR-007 L688-693。计数由 13 修正为 14（本轮改好） | ✅ 保持 |
| **R5**（并发修改不中断推送） | ✅ | §2.5 C-1 L420-428 `codes→frozenset`、`fields→tuple`、`conns` 保留 set+锁；C-2 L430-443 锁序 groups→conns、帧构建与入队在锁外。ADR-004 L667-672 | ✅ 保持 |
| **R12**（三层新鲜度断崖） | ✅ | §2.1 L198 D1/D3「同一变量、同一次调用」；`_process_chunk` 增加 `ttl` 形参注入 ⇒ `ttl_terminal == ttl_url`（INV-1a L175） | ✅ 保持 |
| **R14**（失败≡null 可区分） | ✅ | §2.4 L357-378 保留键契约 + 值域三分 + 单一组装点 `cache.build_batch_response`；`_errors` 仅非空时挂 | ✅ 保持 |
| **R18**（CDP 页面裸崩） | ✅ | §2.4 L410-412 `cdp_engine.page_data(page)` 防御取数，命名已统一（P2-4/5 修好：全文不再出现 `cdp_page_data`） | ✅ 保持 |

> 回归未发现功能回退：本轮改动集中在 `_errors` 计数口径、`longhu` 域、`feed` TTL、frame 计费与 healthz 准入，均未触碰上述五项的机制表述。

---

## 三、自洽性抽查（新引入的数值 / 机制之间）

### ✅ 抽查通过项

1. **B=128MB 与 AC-E7 的 256MB 占位**：`B=128MB ≤ 256MB` 且 `B ≥ 8×F_max=112MB`，两条件同时成立，§4.2 L592-593 表述与 PRD AC-E7 的"临时上限占位"一致。✓
2. **Tier 数值与代码一致**：`config.py:153-155` `_trading_tiers()` 盘中 `{L1:8,L2:12,L3:30,L4:300}` / 非盘 `{L1:120,L2:120,L3:180,L4:300}` ⇒ 与 SAD 的 feed L3=**30/180**、longhu L4=**300/300**、announcement L3=30/180、`NEG_TTL=min(5,L1)=5` 全部吻合。✓
3. **INV-1a `pool_refresh ≥ ttl`**：各域 factor 组合（quote/fundflow/timeline=1.0×L1、margin=2.0×L4=600 对齐现存 `_MARGIN_CACHE_TTL=600`、sector=override 604800）均成立。✓
4. **`MAX_GROUPS` 与 `MAX_DEDUP_CODES` 的主从关系**：200×200 > 2000，故码上限主导（L220）——与 `stream.py:275-288 create_group` 的双重校验（单组 ≤200 / 全局 ≤2000）口径一致。✓
5. **引用计数与「丢最旧保最新」语义**：§4.2 L598「因 B ≥ F_max，任一单帧必可入队 ⇒ 不丢最新帧」逻辑成立（B > F_max）。✓

### ❌ 抽查发现（→ P1-N1）

**coverage ≈ 213「码/周期」漏掉了 `_refresh_pool` 的 3 字段串行维度，实际能力 ≈ 71 码/周期。**

- SAD 推导（§2.1 L180、§2.2 L235、§4.3 L633）：`coverage ≈ _BATCH_MAX_WORKERS × (pool_refresh / per_fetch) ≈ 8 × (8/0.3) ≈ 213`，单位标为**码/周期**。
- 代码事实：`stream.py:47-51` `_FIELD_HANDLERS` 有 **3** 个字段（quote/fundflow/timeline）；`stream.py:137-138` `_refresh_pool` 对 3 个 handler **串行** `for field, handler in _FIELD_HANDLERS.items(): fetched = handler(list(codes))`；`stock_api.py:196-201 _handle_cached_batch` 再按 50 分块**串行**；`stock_api.py:96` 每块 `ThreadPoolExecutor(min(8, len))`。
- 量纲换算：`8 workers × 8s / 0.3s = 213` 的单位是**取数次数**，而非**码**。每码需 3 次取数（3 字段）⇒ `coverage = 213/3 ≈ 71 码/周期`。
- 后果（三条，均落在本次修订自己的承诺上）：
  1. **§7.3 假设 #6 失实**（L811「典型场景 N_active ≤ 213，即 1-2 组 × ≤200 码」）：单个 200 码组 × 3 字段 = 600 次取数 > 213，**规范场景本身就不满足 C1**。
  2. **§8 AC-A3 的前提被写错**（L857 把 ⚠️ 归因为"C1 不成立时降级"，默认典型场景 C1 成立）：实际典型场景即触发降级 ⇒ 绝对陈旧度 `ceil(600/213)×L1 = 3×L1`，而非 L1。
  3. **R-6 切片过大**（L236「`|slice| ≤ coverage`」）：slice = 213 码 ⇒ 该 tick 发 **639** 次取数 ≈ 639×0.3/8 ≈ **24s**，与 tick=8s 相差 3×，直接违反 SAD 自定的「tick 刷新 ≤ 0.8×tick」与 §2.3 D-3（L296）、AC-E5/S10。即"照 213 实现必然 tick 超预算"。
- **最小修复**（任选其一，二选一即可）：① `coverage` 明确按**取数次数/周期**定义，并把 C1 写成 `len(_FIELD_HANDLERS) × N_active ≤ coverage`；② 或把 `_refresh_pool` 的 3 个字段 handler 改为并发（此时 213 码成立），并同步 §2.1/§2.2/§4.3 与 §7.3#6 三处。

### ⚠️ 抽查发现（→ P1-N2）

**`_Frame{payload,refs}` 的引用计数未定义同步原语与生命周期收口，字节护栏存在漂移/泄漏路径。**

- SAD 只规定三个变更点（§4.2 L585「成功 put_nowait 时 0→1 加、队列丢最旧 / handler 出队消费时 1→0 减」），未规定：
  1. **同步**：`refs` 会被 **push_loop 线程**（入队 +1、丢最旧 −1）与**每个连接各自的 handler 线程**（出队 −1）并发读改写（`_serve_sse` 的 `q.get`）。CPython 的 `refs += 1` 非原子 ⇒ `stream_queue_bytes` 会漂移，而该 gauge 正是丢弃判据的唯一输入。
  2. **连接生命周期**：`_broadcast` 只在 `queue.Full` 时减 refs。连接被摘除/销毁时（§2.5 C-3 的 40s 写阻塞超时、断连、`stream.py:324-340 destroy_group`、`_SSEConn` 的 `None` 哨兵）队列里**残留的帧无人减 refs** ⇒ `refs` 永不归零 ⇒ 字节**单调泄漏**、预算被永久占用 ⇒ 后续 tick 无条件丢帧——**恰是 P0-1 要消除的后果**，被搬到生命周期缝隙里重现。
- **最小修复**：明确"refs 变更在同一把锁下（或仅在 push_loop 与出队路径各自的原子段内）"；在 `_release_conn` / `destroy_group` / handler `finally` 中**排空队列并按帧 refs−=1**；`None` 哨兵不参与计费。

---

## 四、新发现问题清单

| ID | 等级 | 位置 | 描述 | 建议 |
|----|------|------|------|------|
| **P1-N1** | **P1（阻断）** | §2.1 L180 / §2.2 L235 / §4.3 L633 / §7.3#6 L811 / §8 A3 | coverage 把"取数次数/周期"当"码/周期"，漏 `_refresh_pool` 的 3 字段串行 ⇒ 213 实为 **71**；C1 阈值、典型场景假设、R-6 切片尺寸、AC-A3 前提同时失准（详见 §三） | 按 §三「最小修复」二选一，并同步 4 处表述 |
| **P1-N2** | **P1（阻断）** | §4.2 L585 / ADR-013 | `refs` 并发无同步原语；连接摘除 / `destroy_group` / `None` 哨兵路径不归还 refs ⇒ 字节单调泄漏，护栏失效（详见 §三） | 明确锁/原子 + 生命周期排空；哨兵不计费 |
| P2-a | P2 | §2.6 L491-499 | 「**精确 schema**」块只列 `status/stale/metrics/policy/cdp`，**漏既有 `feeds[]` 与 `cache_ttl`**；而 ADR-001 L651 明写"`/healthz` 的 `cache_ttl` 保留字段名与含义"、Q2 L500 明写 `feeds[].status` 改取值（即 `feeds[]` 仍在）。下游照 schema 实现会**删既有字段**，破 🟠 STABLE | schema 标注「仅示新增字段；既有 `feeds[]`/`cache_ttl` 保留」，或补全 schema |
| P2-b | P2 | §2.2 R-6 L237 | 「未入切片的码从终点缓存读取 ⇒ **帧完整性不降级**（AC-A1 仍成立）」在**冷码**下不成立：该码终点缓存为空时 `snapshot` 无该码 ⇒ `stream.py:150-154 _build_frame` 直接 `continue` ⇒ 帧缺码。AC-A1 的 50 码场景因 C1 成立不受影响，但 C2 降级期需写明"冷码首 tick 可能缺" | 补一句边界说明，或降级期对冷码强制入切片 |
| P2-c | P2 | §2.1 D2 L199 / §4.3 / AR-6 | 删 `*_POOL_REFRESH` 改 policy 派生后，prefetch 间隔由现状 `_FUNDFLOW=25 / _TIMELINE=30 / _BASIC_INFO=120 / _F10=60` 变为 **8/8/8/300**（announcement 60→30/180）⇒ 上游取数频次提升 3–15×；AR-6 L798 只登记了 feed ×10 | 同轮登记"prefetch 间隔收紧"的上游负载风险与每源 fetch 计数 |
| P2-d | P2 | §3 L521 vs AR-10 L802 | 同一用例的断言口径写作 `err=n`（§3）与 `err=8`（AR-10），表述不一 | 统一为 `err=8`（= 请求数） |
| P2-e | P2 | §4.3 L638 | 「L1 端点数据缓存（**4 域** × 2000 × ~8KB ≈ 64MB）」，而 `DOMAIN_MATRIX` 的 L1 域仅 **3** 个（quote/fundflow/timeline） | 注明第 4 个域（或改为 3 域 × …） |
| P2-f | P2 | §3 cache.py 行 L513 | 「导出 **distinct 帧计费**所需的引用计数钩子」被列在 **cache.py** 变更行；帧计费属 stream.py（cache 反向依赖 stream 被 layerIsolation 禁止，见 tech-stack.json:93-96） | 该职责移入 §3 stream.py 行 |
| P2-g | P2 | §7.1 契约同步项 | `MAX_GROUPS` 新增的建组 **400** 失败模式（对外可观测，§2.2 L220）未登记进契约同步项（上轮 P2-8① 未闭环） | 补登记为端锁定新增项 |

> P2 均不阻断。P2-a/P2-b/P2-f 建议在 **P3a 详设前**顺手改（会直接误导 code-developer），P2-c/d/e/g 可在详设或实测阶段回填。

---

## 五、Q1 / Q2 / Q3 与 §8 覆盖核验

### Q1 — AC-E4 口径：✅ 落地
- 删除了"P95 当均值 ⇒ ≥80% 不可达"的论证：§1.3 L136 改为"24.4 只是**均值取 P95 的保守上界**，不构成不可达证明"，§4.2 L558-567 标题即"**用均值**，勿用 P95—修 Q1"并三档列表（0.80→24.4 上界 / 0.84→19.6 临界 / 0.90→12.5 有余量）。✓
- AC-E4 可断言口径**保留原文**（错误率 0 + 后 3min P99 劣化 ≤20%）：§4.2 L572、§8 L849。✓
- 命中率 ≥90% 降为**设计目标 + 观测项**：§2.6 L470 `cache_hit_ratio`（标注"设计目标观测项，非 AC，Q1"）、AR-2 L794、§8 E4 判 ⚠️。✓
- 零修改 `MAX_WORKERS`（§4.2 L571）。✓

### Q2 — feeds[] 声明与三同步点：✅ 落地
- §3.1 L532 「明确不改」表已改为"只增不改（**例外**：`feeds[].status` 取值变更，须编排层批准）"；§2.6 L490 明写"原『不改既有 `feeds[]` 字段与含义』**删除**"；文档头 L9 端锁定行同步声明。✓
- 三同步点逐一列名（§7.1 L781-787）：`/stock/data`（B，health 负载）、`/stock/basic_info`（B，health 负载 + API.md）、`/stock/f10`（A′，health 负载 + 首页 CDP 列），各带**代码位置**（`server.py:465-467/488-491/484-487/758`）。✓

### Q3 — feed TTL 改 L3 与 5 点连带：✅ 落地
- TTL 定案盘中 30s / 非盘 180s：§2.1 L163（`cache_policy('feed')`）、L200（D4）、ADR-001 L651、§7.1 Q3 L776。✓
- 5 点连带**逐条列全**（§2.1 D4 L201）：① `CACHE_TTL` 多消费者**逐点迁移**（`cache.py:9/29` 默认 ttl、`utils.warm_jin10`、`server._get_or_fetch_feed`——与代码侧 `config.py:12 CACHE_TTL` 的 3 类消费者一致）；② 非盘 300→180 一并列出；③ feed LRU 落点补列 `server._get_or_fetch_feed`（§3 server.py 行 L514 已含）；④ AC-A8 的 2×TTL 口径同步（§8 L862）；⑤ ×10 影响 + 每源 fetch 计数（AR-6 L798）。✓

### §8 AC 覆盖声明：✅ 属实
- 逐条核对 30 条（E1-E9 / A1-A10 / S1-S11）：**全部有条目**，无缺号无重复；⚠️ 恰为 **5** 条（E4/A3/A8/S3/S4），与声明一致。✓
- 上轮 ❌ 的 4 条已翻绿：E7（§2.2/§4.2 distinct 帧预算）、E9（§2.1 longhu 域 L4 + §2.3 D-5 GBK + 计数口径）、S6（§2.3 D-6 码级冷却）、S11（§3.1 L533「不改动 + 断言依据」`_register_conn` + 全量快照 + `STREAM_GROUP_IDLE_TTL=300s`，与 `stream.py:22/343` 一致）。✓
- 「30 条全部有落点」的表述**未失实**（非上轮的"30/30 一刀切"）。✓
- **唯一欠精确**：A3 的 ⚠️ 归因（见 P1-N1）。

---

## 六、结论

> **❌ 仍阻断**（P0×0 / P1×2）。

上轮 **P0×1 + P1×7 的机制层全部修复**，Q1/Q2/Q3 三项裁决逐字落地，§8 覆盖声明属实且由 ❌→✅ 的 4 条（E7/E9/S6/S11）证据充分，上轮已 ✅ 的 R1/R5/R12/R14/R18 无回退。修订质量高、自我订正诚实（如 P1-2 主动写出原错误推导、P0-1 主动写出错误计费的后果）。

**但仍不能放行**，因为两项中央修复各残留 1 处"必须补齐才可实现"的缺口，且二者都落在**新引入机制的正确性**上（非格式问题）：

1. **P1-N1（覆盖模型漏字段维度）**：`coverage=213` 应按 3 字段串行折算为 ≈**71 码/周期**。照 213 实现，R-6 切片将发 639 次/tick 取数 ≈24s，**直接违反 SAD 自定的 tick ≤0.8×tick**；同时 §7.3#6 的"典型场景满足 C1"与 AC-A3 的前提失准。
2. **P1-N2（帧引用计数未收口）**：`refs` 无同步原语 + 连接摘除路径不归还 ⇒ `stream_queue_bytes` 漂移/单调泄漏，**P0-1 的字节护栏在生命周期缝隙里失效**。

**最小放行集（2 项，均为本地修正，不改任何机制）**

| # | 修正 | 落点 |
|---|------|------|
| 1 | coverage 明确为**取数次数/周期**（或 3 字段改并发），C1 写成 `len(_FIELD_HANDLERS) × N_active ≤ coverage`；同步 §2.1 INV-1b、§2.2 R-6、§4.3、§7.3#6、§8 A3 | §2.1 L178-185、§2.2 L235-238、§4.3 L633、§7.3#6、§8 L857 |
| 2 | `refs` 变更给定同步原语；`_release_conn`/`destroy_group`/handler `finally` 排空队列并逐帧 refs−=1；`None` 哨兵不计费 | §4.2 L585、ADR-013、§3 stream.py 行 |

修正后**无需重审全文**——仅需复核上述 2 处的文本（及可顺带 P2-a/P2-b/P2-f）。

**待编排层后续项（SAD 已声明，非本次阻断）**

| 项 | 内容 | SAD 落点 |
|----|------|---------|
| Q2 契约同步 | 由编排层一次性 dispatch：`/healthz` 负载（`/stock/data`→configured、`/stock/basic_info`→configured、`/stock/f10`→CDP）+ API.md（basic_info）+ 首页 CDP 列（f10）；`feeds[].status` 取值变更需在 🟠 STABLE 下显式批准并记入变更日志 | §7.1 L781-787 |
| PRD §9 表述 | "51 个存量单元用例保持全绿"改为"51 中 1 条按新语义更新并通过，其余 50 条全绿" | AR-10 L802（P1-7） |
| P6c 校准 | AC-S3 模式 B 的 P95 绝对分位数与首次冷窗口占比；AC-A3 的 C1 覆盖实测；`cache_hit_ratio` <84% 时走 PRD 修订；AC-E7 256MB 占位替换 | §7.1 Q6、AR-9/AR-2、§4.2 |

---

## 变更记录

| 版本 | 日期 | 说明 |
|------|------|------|
| v1.0 | 2026-09-15 | 首轮架构评审（REV-ARCH-20260915-001）：❌ 阻断；P0×1 / P1×7 / P2×8；Q1/Q2/Q3 裁决 |
| v1.1 | 2026-09-15 | 复审（REV-ARCH-20260915-002）：8 项阻断 + Q1/Q2/Q3 + §8 逐项核验通过；**❌ 仍阻断（P0×0 / P1×2）**——coverage 漏字段维度（P1-N1）、帧引用计数未收口（P1-N2）；新增 P2×7 |


