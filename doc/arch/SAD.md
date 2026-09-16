# 短线交易财经数据服务 — 高效/准确/稳定优化专项架构建档（SAD）

> **文档编号** SAD-2026-P6C-01 · **版本** v1.5 · **状态** 待复审
> **日期** 2026-09-16 · **产出** system-architect
> **上游输入** PRD `doc/prd/perf-stability-optimization.md`（v0.4，30 AC / R1-R20）
> **修订依据**（v1.1）review-expert `doc/review/perf-stability-optimization_架构评审_专家版.md`（REV-ARCH-20260915-001，❌ 阻断：P0×1 + P1×7 + P2×8；Q1/Q2/Q3 裁决）；（v1.2）复审「❌ 仍阻断」但机制层（P0×1 + P1×7）已全部合格、Q1/Q2/Q3 逐字落地——仅收口 **P1-N1（coverage 单位）** ＋ **P1-N2（`_Frame.refs` 收口）** 与 7 项 P2。逐项落地见 §9；（v1.3）基础层三模块详设评审 review-expert `doc/review/基础层三模块_详细设计评审_专家版.md`（REV-DES-20260915-001，✅ 通过 P0×0/P1×1/P2×8）——落地 P3b 评审的 SAD 侧动作：3 项内部矛盾更正 + 6 项裁决 + D-1~D-7 偏差回填 + 2 项 SAD↔代码不一致更正，逐项见 §9.3；（v1.4）**P7b 契约同步**——以**代码为准**回写实现的最新行为（帧契约、订阅字段容量模型、单帧余量准入、探预算阶梯、deadline 贯通、`canonical_code` 归一化权威、CDP/观测口径），并登记 1 项与 PRD AC-A5 冲突的**待裁决**漂移，逐项见 **§9.4**；（v1.5）**裁决落地收尾同步**——编排层对 3 处契约冲突的裁决已同步 PRD（`perf-stability-optimization.md` v0.5），本轮以**代码为准**把 SAD 侧结论回写：① **N1 关闭**（业务端点降级维持 **200 + error 客体**，`server._json_payload_has_data` 已删除、`_send_json_shape` 恒 200，`http_503_total` 计数点 4→3）；② **AC-S3 模式 B 探测预算阶梯封顶 5s**（`2→4→5`，`cache._PROBE_BUDGET_CAP=5.0`；P95 口径重标为**高密度 ≤5s / 低密度 ≤10s**）；③ **`_LOCAL_BUDGET` 不入冷却账本**的 v1.4 反转**正式确认**（反转 REV-DES-15 裁决②）。逐项见 **§9.5**
> **硬约束** Python 3 标准库零依赖 · 无前端 · 无外部存储 · 不改技术栈
> **定位** 优化专项架构（非新建系统）：只做**架构级改造与契约收口**，不新增业务功能、不改路由与 API 签名
> **端锁定** 🟠 STABLE（仅**新增**下划线保留键与观测字段；`feeds[].status` 属**改既有字段取值**，须编排层批准，见 §7.1 Q2）。**v1.4 新增两项边界（须编排层登记）**：① SSE 帧**只增**元数据（`codes_total`/`fields`/`missing`/`missing_count`/`errors`/`stale`/`stale_count`）属 🟠 STABLE 的"只增"；② **JSON 单体/面板/工具端点业务降级维持 200**（v1.5 N1 裁决关闭）——这不是"状态码变更"，而是**保持旧版本契约**，与 PRD AC-A5 逐格一致；真实 503 仅**连接准入拒绝**（主/流端口）与 **`/healthz` degraded**（健康端点自身语义，**不构成"业务端点可 503"的先例**）（§2.4 / §7.1 N1）

## 0. 阅读指引

| 节 | 内容 | 读者 |
|----|------|------|
| §1 | 现状链路 + R1-R20 根因归类（架构级 vs 实现级） | 全体 / task-decomposer |
| §2 | 目标架构（6 个设计轴） | task-decomposer |
| §3 | 模块变更矩阵（含"明确不改"） | code-developer |
| §4 | 非功能预算（延迟/吞吐/资源上界） | tester / 容量评估 |
| §5 | ADR-001~ADR-017 | 评审 |
| §6 | tech-stack.json | code-developer / check-arch-compliance.sh |
| §7 | 待决策、风险与假设 | 编排层 |

**本次架构设计的三条主线**（先给结论，细节在后）：

1. **把"新鲜度"从散落常量收成单一权威**（R16→R12，并发现 PRD 未列的**第 4 处断崖**：feed 层 300s vs L3 30s）。
2. **把"故障"变成一等状态**（负缓存 + 期限贯通 + 枚举错误码），让失败不再是"更慢的成功"（R9/R13/R14）。
3. **给资源建总账**（线程/队列/缓存/内存/连接各自有界且互相可推导），让"有界拒绝"取代"无限排队"（R2/R7/R11 + EFF-3）。

---

## 1. 现状架构与瓶颈根因分析

> ⚠️ **本节记录的是优化前的基线（pre-P6c）**，用于固化 R1-R20 的根因，**不是**当前实现的描述。当前实现的准确口径见 §2/§3/§4（v1.4 已按代码同步），逐项差异见 **§9.4**。读本节时请勿把"现状"当作今日行为。

### 1.1 现状处理链路（逐模块）

**链路 A — REST 请求（主端口 8053）**

```
client
  → RSSHandler._handle_request()                    [server.py:532]
      路由判定（14 个 JSON 分支 + ROUTES 5 个 RSS + / + /opml.xml + /healthz）
      · 14 = 面板 4（/finance/market,/finance/timeline,/quotation/market,/market/timeline）
            + stock 6（/stock/data,/fundflow,/timeline,/f10,/basic_info,/announcement）
            + /cls/hotplate + /cls/plate + /ths/longhu + /market/margin（逐一列名见 §2.4）
  → 单体/面板：handler() → 直接取 CDP 页面或 fetch_json
  → 批量：_handle_stock_batch()                     [server.py:610]
      · 缺 ?code= → 400；>50 码 → **静默截断**（仅 log.warning）
  → stock_api.handle_cls_* (codes)                   [stock_api.py]
      → _handle_cached_batch：按 50 分块，**逐块串行**
          → _process_chunk：去重 → 校验 → 池 LRU 触碰 → **按码缓存**(cache/cache_ts)
              → 未命中 → _run_batch（≤8 并发）→ _fetch_one
                  → fetcher(code[, deadline])        ← REST 系忽略 deadline（R13）
          → 未命中取数 → cache.fetch_json(url, ttl)  [cache.py:62]
              → 全局 URL 缓存 cache{}（2000 条，按**插入时间**淘汰）
              → leader/follower 选举 → urlopen(10s) → 失败**无负缓存**（R9）
  → RSS 分支：_get_or_fetch_feed()                    [server.py:640]
      → feed_cache{}（100 条，按**插入时间**淘汰，TTL=CACHE_TTL=300s）
  → _send_text / _send_json（Cache-Control max-age 由 _cache_age() 按 tier 计算）
```

**链路 B — SSE 推送（流端口 8054）**

```
push_loop()                                          [stream.py:246]  每 L1 tick
  → _active_codes()（持 _groups_lock 求并集，仅含有活连接的组）
  → _refresh_pool(codes)                              [stream.py:129]
      → 对 quote/fundflow/timeline 各调一次批量 handler（分块串行）
  → _broadcast(snapshot)                              [stream.py:179]
      → 持 _groups_lock 取组列表 → 持 conns_lock 取连接列表
      → _build_frame(snapshot, g)：**不持锁**遍历 g.codes（R5 契约缺口）
      → conn.q.put_nowait(frame)；满 → 丢最旧（有界队列 8）
  → _serve_sse(sid)：q.get → wfile.write；socket 超时 = PING×2 = 40s
管理端点（POST/PATCH/DELETE）：_read_json_body 最多 64KB，**仅靠 30s socket 超时**（R6）
```

**链路 C — 后台线程（7 条）**：`warm_jin10_headers`、`init_cdp`、`_cdp_memory_watchdog`（7200s 强制重启 Chrome）、4 条 prefetch loop（fundflow/timeline/f10/announcement）、`push_loop`、stream server 线程。

### 1.2 R1-R20 根因归类

分类口径：**架构级** = 缺陷根源在"跨模块的机制/契约/资源分配"缺失，修一处不够，必须新增统一机制，且改动会波及 ≥2 个模块；**实现级** = 局部代码缺陷或文档缺失，可在单模块内闭合，不改机制。

| # | 现状现象（代码确认） | 根因 | 层级 | AC |
|---|--------------------|------|------|-----|
| R1 | 14 个 JSON 路由分支（面板 4 + stock 6 + hotplate/plate/longhu/margin 4）中，批量与 `/ths/longhu`、面板系**无 try 边界**；异常穿透 `do_GET`（只捕 BrokenPipe/ConnectionReset）→ 无响应体、连接被关 | **handler 边界无统一异常契约**（`_serve_feed` 有、JSON 路径没有） | **架构级** | S1 |
| R2 | `build_health_payload(check=1)` 在请求线程内**串行**调 5 个 handler，每个 `fetch_json` 10s → 最坏 50s，占用主池 worker | **健康检查与业务共用资源且无预算/隔离** | **架构级** | S8/S10 |
| R3 | `feed_cache` 淘汰 `min(feed_cache, key=time)`，`time` 只在写入时更新 → 实为 **FIFO**；命中不触碰 | 淘汰策略**未建模"最近访问"**（与注释"LRU"不符） | 实现级（依赖缓存机制，见 R11） | E6/A8 |
| R4 | `_handle_stock_batch` >50 码仅 `log.warning` 后截断，响应无标记 | **响应契约缺元信息承载位** | 架构级（契约） | A9 |
| R5 | `_build_frame` 遍历 `g.codes` 不持锁。**实测：`patch_group` 为整体赋值 `g.codes = ...` 而非原地 `add/discard`，故当前不产生 `RuntimeError`**——属**潜在**竞态：任何后续改成原地变更即立刻复现 | **不可变/锁纪律未显式化为契约** | 架构级（契约） | S2/A1 |
| R6 | `_read_json_body` 用 30s socket 超时 + 单次 `rfile.read(64KB)`，慢客户端可占管理线程至 30s | **IO 预算未分层**（管理请求共用长连接超时） | 架构级（预算） | S7 |
| R7 | `payload_bytes = len(codes)×70KB` 仅作估算未参与调度；无组数上限（`MAX_DEDUP_CODES` 只界码不界组）→ 队列内存无总账 | **内存预算缺失** | 架构级 | E7/E5/S9 |
| R8 | `nxt` 在刷新**之前**算定；刷新耗时吞掉间隔 → tick 静默滑动，无指标 | **tick 预算与可观测性缺失** | 架构级（机制+观测） | S10/E5 |
| R9 | `fetch_json` 选举失败后 follower **重入选举成为新 leader**，逐次重试至 deadline(10s)；再走 fall-through：sleep(0~0.5)+`Semaphore(2)` 3s → 单线程可达 ~13.5s。全程**无失败状态记忆** | **无失败状态层（负缓存）** | **架构级** | S3 |
| R10 | `_expires_at` 抖动 ±20% 无文档；「过期=拒读+回源一次」未成文 | 语义未文档化 | 实现级 | A4 |
| R11 | `_cache_put` 每 60s 才清扫一次；淘汰按插入 `time`；命中不更新访问时间 | 缓存淘汰策略**未建模访问序**（同 R3） | 架构级（缓存机制） | E6 |
| R12 | 同一码三条时间尺度：**按码缓存 120s**（`_MAX_CACHE_AGE`）× **URL 缓存 L1=8s** × **池刷新**（basic_info **无 prefetch loop**，`_BASIC_INFO_POOL_REFRESH` 为死常量）→ 走批路径可返回 120s 旧值 | **TTL 权威源缺失导致的多层新鲜度断崖** | **架构级** | A3/A4 |
| R13 | `_fetch_one` 以 `fetcher(code, deadline=...)` 调用，REST 系签名不收 `deadline` → `TypeError` 回退 `fetcher(code)`，**期限静默丢失**；分块串行叠加以致整体无界 | **期限（deadline）未贯通数据获取层** | **架构级** | E2/S7 |
| R14 | 取数失败 / 格式非法 / 上游无数据 → 全部 `None`，消费方不可区分 | **错误语义未编码进响应** | 架构级（契约） | S6/A10 |
| R15 | `/ths/longhu` 每次请求**直连 urlopen 两次**，绕过 `fetch_json` 聚合入口与缓存 | 违反"取数统一走 fetch_json"约定 | 架构级（约定） | E9 |
| R16 | `_trading_tiers()` 存在但消费方常量独立：`_MAX_CACHE_AGE=120`、`CACHE_TTL=300`、`_MARGIN_CACHE_TTL=600`、5 个 `*_POOL_REFRESH`、`_cache_age()`、`_CACHE_SWEEP_INTERVAL=60` | **TTL 无单一权威来源**（R12 根因） | **架构级** | A3 |
| R17 | `STREAM_PING_INTERVAL=20`、socket 30s、部分窗口写死在代码 | 关键 IO 参数未 env 化 | 实现级 | S7 |
| R18 | CDP 页面取数无防御访问：`_fill_missing(r, data, ...)` 假定 `data` 为 dict；`handle_finance_timeline` 返回 `.get('timeline')` 可为 `None`（非 error 客体） | **外部数据边界无防御契约**（与 R1 同源） | 架构级（契约） | S1/S4 |
| R19 | `_cdp_memory_watchdog` 每 7200s **无条件**重启 Chrome（含交易时段）→ 15s 节流 + 45s 启动窗口内 CDP 端点全空，且外部不可观测 | **降级窗口无策略、无可见性** | 架构级（策略+观测） | S10/S4 |
| R20 | `CDP_STOCK_PAGES` 默认 3 + 2 常驻页，每页 150MB+ | 参数化已具备，缺内存总账联动 | 实现级 | S9 |

**归类小结**：架构级 15 项（R1/R2/R4/R5/R6/R7/R8/R9/R11/R12/R13/R14/R15/R16/R18/R19 中除 R3/R10/R17/R20 外）、实现级 4 项（R3/R10/R17/R20）。**M7 必做项全部落在架构级**——这决定了 task-decomposer 的拆分方式：先落 §2 的 6 个机制，再落逐 handler 的适配。

### 1.3 四个架构级根因（深挖，设计 §2 直接针对）

**RC-1 「时间语义散落」——新鲜度不是被设计出来的，是碰巧一致的（R16→R12）**

系统的"新鲜度"由 **7 类互不引用的常量**共同决定：`_trading_tiers()`（唯一"正确"来源）、`_MAX_CACHE_AGE=120`、`CACHE_TTL=300`、`_MARGIN_CACHE_TTL=600`、5 个 `*_POOL_REFRESH`、`_cache_age()` 的端点前缀映射、`fetch_cls_announcement` 里的裸 `ttl=15`。它们的"正确值"依赖维护者手工保持一致，因此**任何一处改动都会制造断崖**，当前至少 4 处：

| 断崖 | 层级 | 现状 | PRD 口径 | 后果 |
|------|------|------|---------|------|
| D1（R12 主断崖） | 按码缓存 | 120s | ≤ L1(8s) | REST/SSE 批路径返回最多 120s 旧价 |
| D2（R12） | 池刷新 | basic_info **无 prefetch loop**（`_BASIC_INFO_POOL_REFRESH=120` 为**死常量**，被误当作实际池刷新源） | ≤ L1 | 死常量须删除；basic_info 新鲜度实际由按码缓存 120s 决定（与 D1 同） |
| D3（R16） | URL 缓存 vs 按码缓存 | 8s vs 120s | 同一权威 | 同一码两条路径可差 112s |
| **D4（PRD 未列，本次新增发现）** | **feed 缓存** | **`CACHE_TTL=300s`，与交易时段无关** | **L3=30s（SCN-2）** | **RSS 快讯盘中最多旧 300s；且 `_cache_age()` 已向客户端声明 `max-age=30`——服务端承诺与行为矛盾** |

> D4 的证据链：`server.py:668` 写入 `expires_at = time.time() + CACHE_TTL×jitter`（CACHE_TTL 不随交易时段变化）；`server.py:701` `_cache_age()` 对 RSS 端点返回 `tiers['L3']`。即 **客户端被承诺 30s 新鲜度，服务端实际可给 300s 旧数据**。这不是 R12 的子集，而是同一根因在**第 4 个缓存**上的复现，必须一并纳入 §2.1。

**RC-2 「故障被当成慢成功」——没有失败状态层（R9/R13/R14）**

`fetch_json` 的契约是"成功返回 str，失败抛异常"，但**失败不留痕**：下一次请求从零开始重新选举、重新 urlopen。于是上游故障期间，每个请求都要重走完整失败路径（最坏 13.5s/线程），延迟与上游压力**随请求数线性放大**——这就是"放大器"的本质。同时失败到达 handler 时已被压成 `None`，与"无数据"合并（R14）。三者是同一件事的三个面：**失败没有独立的数据结构**。

**RC-3 「边界不存在」——异常与响应契约只在个别路径成立（R1/R4/R18）**

`_serve_feed` 有 try/except（降级 error-RSS），JSON 路径没有；`handle_*` 约定"返回 dict 不抛"，但**没有被强制执行的位置**（无装饰器/无统一 wrapper），所以 R1（handler 抛异常 → 裸断连）与 R18（CDP 页面数据为 None → 上游数据边界未防御）必然发生。同理，批量响应的"元信息"（截断、失败）**在契约上没有承载位**，所以 R4（静默截断）与 R14（失败≡null）只能靠"加字段"临时解决——这需要先定命名空间，否则会与股票代码键冲突。

**RC-4 「资源各自有界，合起来无界」——缺总账（R2/R7/R11 + EFF-3）**

各组件都有局部上限：主池 20 worker、inflight 40、SSE 连接 100、单连接队列 8、URL 缓存 2000、feed 100、去重码 2000。但缺三样：
① **跨组件的量纲换算**——码数 × 组数 × 帧体积 × 队列深度 = 队列内存，无任何一处计算它，且**组数无上限**（码 ≤2000 可拆成 2000 个组）；
② **池容量与刷新能力的耦合**——L1 域池上限 500，但 prefetch 串行、间隔 `max(25, L1)`；500 码在同一周期需 **按订阅字段数 × 500 次取数**（基线按每码 3 次 = 1500 次估），以 0.3s/次、8 并发算需 ≈56s，在 8s 内**物理上刷不完**，于是"配置的上限"制造了**沉默的新鲜度违约**（与 RC-1 叠加）；
③ **健康检查与业务的资源隔离**——healthz 与业务抢同一批 worker，且串行。

由此得出量化的容量结论（详见 §4.2）：以 AC 的 **P95** 值（W_miss=1.2s、W_hit=5ms）代入 Little's Law 得到的平均并发 **24.4 只是"均值取 P95"的保守上界**（真实均值 ≤ P95，通常明显更低），因此它**不构成"AC-E4 ≥80% 不可达"的证明**；在上界口径下 80% 处于临界、≥90% 有余量。按 Q1 裁决：**不改 PRD 指标、不改 `MAX_WORKERS`**，改为把"命中率 ≥90%"降格为 **SAD 内部设计目标 + `/healthz` 观测项**；AC-E4 的可断言口径仍为「错误率 0 + P99 劣化 ≤20%」。这是本次架构设计对 PRD 指标的**零修改**（Q1）。

---

## 2. 目标架构设计

### 2.1 缓存分层统一（R12/R16/D1-D4）

**设计决策：把"新鲜度"变成 config.py 的一个纯函数。**

新增 `config.cache_policy(domain, now=None) -> dict`，作为**全系统唯一**的 TTL/刷新/容量权威来源。所有缓存、池、刷新间隔、`Cache-Control` 一律由它派生；**禁止任何模块出现裸 TTL 数字字面量**（唯一例外见下面的 `override`）。

```
DOMAIN_MATRIX = {   # domain → (tier, ttl_factor, pool_refresh_factor, pool_max, cache_max)
  'quote':        ('L1', 1.0, 1.0, 'dedup', 2000),   # basic_info / stock_detail / data（实时价）
  'fundflow':     ('L1', 1.0, 1.0, 'dedup', 2000),
  'timeline':     ('L1', 1.0, 1.0, 'dedup', 2000),
  'plate':        ('L2', 1.0, 1.0, 'fixed:200',  'n/a'),  # 3 分区 stagger 由 handler 从 L2 派生（见下）；URL 缓存独占 ⇒ cache_max n/a
  'news_url':     ('L3', 1.0, 1.0, 'n/a',        'n/a'),  # 5 源 RSS URL 缓存（共享 cache{}，2000）
  'feed':         ('L3', 1.0, 1.0, 'fixed:100',  100),    # ★ 修 D4：feed 缓存改由 L3 派生
  'announcement': ('L3', 1.0, 1.0, 'dedup',      500),
  'longhu':       ('L4', 1.0, 1.0, 'n/a',        'n/a'),  # ★ 新增：龙虎榜（GBK 上游，日更；补 P1-4）
  'margin':       ('L4', 2.0, 2.0, 'fixed:16',   'n/a'),  # URL 缓存独占 ⇒ cache_max n/a
  'f10':          ('L4', 1.0, 1.0, 'dedup',      500),
  'sector':       ('L4', 'override:604800', 'n/a', 'fixed:2000', 2000),  # 行业名，7d
}
cache_policy('quote')  → {'tier':'L1','ttl':8,  'pool_refresh':8,  'pool_max':2000,'cache_max':2000}
cache_policy('feed')   → {'tier':'L3','ttl':30 (盘中) / 180 (非盘中),'pool_refresh':30/180,'cache_max':100}
cache_policy('longhu') → {'tier':'L4','ttl':300,'encoding':'gbk','cache_max':null}
cache_policy('plate')  → {'tier':'L2','ttl':12,'pool_refresh':12,'pool_max':200,'cache_max':null}
```

> ⚠️ **v1.4 更正（`cache_max` 口径，2 格）**：`plate` 与 `margin` 的 `cache_max` 是 `'n/a'`（运行时 `None`），**不是** 200 / 16。理由（实现 P2-9）：`cache_max` 约束的是**域自己的终点缓存**（`stock_api._cache_store` 的 `_*_cache`）或 **feed 缓存**（`cache.feed_cache_put`）；`plate`/`margin` 只经**共享 URL 缓存**（`cache.fetch_json`，`cache{}`）服务，其条目由全局 `cache.MAX_CACHE_SIZE=2000` 约束 ⇒ 给它们一个 per-domain int 是**操作者无法执行的死配置**。故"URL 缓存独占域"（`plate` / `news_url` / `longhu` / `margin`）一律 `'n/a'`；`pool_max` 不受影响（`plate`/`margin` 的 `fixed:200`/`fixed:16` 保留，它们约束的是去重池而非缓存）。SAD 上一版这两格与实现不符，此处以**代码为准**更正。

要点补充（消除 P2-5 的两处悬置）：
- **`plate` 的 3 分区 stagger**：`/cls/hotplate`、`/cls/plate` 现有 `_STAGGER = max(3, L2//4)` 的三档错峰（industry/concept/area 或 info/stocks/industry）不是 policy 的第四维，而是**分区 offset = `_STAGGER × 分区序` 由 handler 从 `cache_policy('plate')['ttl']` 派生**（等价于 `ttl × (1, 1.25, 1.5)`），仍属 policy 派生、非裸字面量。**该项目为明令保留的行为（D-7）**——TTL 收敛（R16）时**不得**把三块压成同一 TTL；详设迁移表若只列基值即为口径失真，须由 `server.md` 显式承接 stagger 派生。
- **`'n/a'` 归一化（裁决 #1）**：`DOMAIN_MATRIX` 单元格**保留 `'n/a'` 字面量**（便于与 SAD 逐格对照），`cache_policy` **返回值一律归一化为 `None`**（供 `is not None` 判空、避免 int/str 混型使 `pool_refresh >= ttl` 不变式失效；示例见上 `longhu` 的 `cache_max`）。
- **新增内部名 `_DOMAIN_ENCODING`（D-5）**：`DOMAIN_MATRIX` 为**公开名**（运行期 Python `dict`，§3 yaml 仅为表达），`_DOMAIN_ENCODING = {'longhu': 'gbk'}` 为 config 新增内部名，`cache_policy` 据此挂 `encoding` 键（非 utf-8 域才出现，§2.3 D-5）。
- **`announcement` 域 tier 定案 L3**（Q5）：交易 30s / 非交易 180s；现 `fetch_cls_announcement` 的裸 `ttl=15`、`_ANNOUNCEMENT_POOL_REFRESH=60` 一并删除改由 policy 派生（列入 §3 stock_api 行）。
- **`longhu` 域补入**（修 P1-4）：AC-E9 要求 L4 TTL ≥300s，`cache_policy('longhu')['ttl'] = L4 = 300s`（盘中）/ 300s（非盘中）为权威来源；上游为 **GBK** HTML，需 `fetch_json(..., encoding='gbk')`（见 §2.3 D-5）。


**不变式（INV-1，可白盒断言，服务 AC-A3）**

> **INV-1a（可证）**：对任意 domain：`ttl_url(d) == ttl_terminal(d) == cache_policy(d)['ttl']`，且 `pool_refresh(d) >= ttl(d)`；实时域（quote/fundflow/timeline）满足 `ttl(d) <= L1`。
> 池刷新间隔 = ttl ⇒ 池内数据在被判定过期**之前**恰好被替换，不存在"配置上过期、实际无人刷新"的沉默窗口。
>
> **INV-1b（条件成立，修 P1-1 / P1-N1；**v1.4 按实现重标定**）**：「一个 L1 周期内覆盖整池」**不是**由池上限单独保证的，它取决于**活跃码数 N_active、订阅字段并集与单周期取数能力 coverage 的关系**。`_refresh_pool` 对**存活组订阅字段并集**（`_subscribed_fields()`，`stream.py:214`）按 `_FIELD_HANDLERS` 顺序**串行**各调一次批量 handler，`_handle_cached_batch` 内再按 50 分块串行——故 coverage 的**单位是「取数次数/周期」，不是「码」**，且**每码成本 = `_fetches_per_code(fields)`**（v1.4：**按订阅字段计**，不再是历史的无条件 3）：
> ```
> _PER_FETCH_EST        = 2.2   # 单次取数占一个 batch worker 的串行等效秒数（r3 部署实测冷路径 ≈2.2s）
> _FIELD_FETCH_CALLS    = {'quote': 1, 'fundflow': 1, 'timeline': 1}
>   # ★ v1.4：quote（handle_cls_basic_infos）实为两相（basic_info + stock detail/sector），
>   #   但第 2 相命中 7d `sector` 缓存后稳态成本 = 1（旧值 2 把冷路径价摊到每个 tick）。
>   #   fundflow / timeline 恒为 1。未知（测试注入）字段回退 _DEFAULT_FETCH_CALLS = 1。
> _fetches_per_code(fields) = Σ _FIELD_FETCH_CALLS[f] for f in fields     # 1 / 2 / 3
> coverage       = max(1, floor(_TICK_BUDGET_FRACTION × tick × BATCH_MAX_WORKERS / _PER_FETCH_EST))
>                = floor(0.8 × 8 × 8 / 2.2) = 23 取数次数/周期   （盘中 tick=8；非盘中 tick=120 ⇒ 349）
> coverage_codes = max(1, coverage // _fetches_per_code(fields))
>                = 盘中 1 域 → 23 码/周期 · 2 域 → 11 · 3 域 → 7
> 条件 C1: _fetches_per_code(fields) × N_active ≤ coverage
>           ⇔ N_active ≤ coverage_codes      ⇒ 一个 L1 周期覆盖整池（lag = 0）
> 条件 C2: _fetches_per_code(fields) × N_active >  coverage
>           ⇒ 单周期物理刷不完 ⇒ 降级为「分片轮转刷新」（见 §2.2 R-6 / AR-1），
>             池内陈旧度 ≤ ceil(N_active / coverage_codes) × L1
> ```
> **两处口径变更（v1.4，原 SAD 失准）**：① 旧 `_PER_FETCH_EST=0.3` 属标定偏乐观（实测冷路径 ≈2.2s/worker-call；旧值下 51 取数实测 ≈14s > 6.4s 预算）⇒ `coverage 170 → 23`；② 旧公式把每码成本固定为 `len(_FIELD_HANDLERS)=3`，而实现**按订阅字段并集**计价 ⇒ `coverage_codes` 由 `≈56` 变为 **23 / 11 / 7**（1 / 2 / 3 域）。
> **不建议**把 3 字段 handler 改并发以抬高 coverage：单 handler 内已用满 `_BATCH_MAX_WORKERS=8`，字段级并发会把在飞取数抬到 24，违反 AC-E8 资源口径（见 §2.2「不选其他」）。
> **AC-A3「绝对陈旧度 ≤ L1×(1+抖动)」的成立前提是 C1**；C1 不成立的**典型输入即"1-2 个不重叠活跃组 × ≤200 码"**（200 码 × 3 域 ⇒ 600 取数 > 23；即使 quote-only 也 200 > 23）——即**默认场景即降级**，必须接受降级并在 metrics 标记（不再是"必然覆盖"的假承诺）。池上限本身**不得**写死为 `MAX_CODES_PER_SUB=200`：池是**跨组共享**的单一 dict，用单组上限界全池会造成 `_process_chunk` 反复抖空端点缓存（P1-1 根因）。
> **切片与容量的单一派生点**：`refresh_capacity(tick, fields)` 同时产出 `(coverage, coverage_codes)`，C1 门限与 C2 切片尺寸**同源**，二者不可能互相矛盾（也不可能与真实每码上游成本矛盾）。

**三层缓存的一致性设计**

| 层 | 现状 | 目标 |
|----|------|------|
| ① 去重池 `_*_pool`（码 → 最后访问 ts） | LRU 触碰已有（`_process_chunk` 写 pool[code]=now），**上限 500 与"跨组活跃码 ≤2000"不匹配**；且池淘汰会 `cache.pop` 连带清除终点缓存 | ① 池是**跨组共享的成员账（membership ledger）**，上限 = `cache_policy(d)['pool_max']`（L1 域 = `MAX_DEDUP_CODES=2000`，与去重码硬上界同源）；② **池淘汰不再 `cache.pop`**（解耦），避免多活跃组时反复抖空终点缓存（修 P1-1） |
| ② URL 缓存 `cache{}` | TTL 由调用方各自传；淘汰按插入时间 | TTL 统一由 `cache_policy` 派生；淘汰改按 `last_access`（见 §2.2）；命中时更新 `last_access` |
| ③ 终点缓存 `_*_cache/_*_cache_ts` | `_MAX_CACHE_AGE=120` 硬编码，与 ② 无关；大小被动受池上限约束 | `_process_chunk` 增加 `ttl` 形参，由 handler 从 `cache_policy(d)` 注入 ⇒ `ttl_terminal == ttl_url`；**独立上限** `cache_policy(d)['cache_max']`，按 LRU + TTL 自管（内存护栏从"池"移到"缓存"） |

> **① / ③ 解耦的理由（P1-1）**：同一码可能被多个组订阅，池是全局单例。若仍用池上限驱动 `cache.pop`，当活跃码 > 池上限时每处理一块就轮换整池并清缓存 → 每 tick 大量回源、L1 新鲜度反而变差。解耦后：池（廉价 `code→ts`）上限 = 活跃码硬上界 2000，不触发清理；数据内存由 ③ 的 `cache_max` 独立 LRU 守住。这同时消除 R11 的"过期条目滞留"与 P1-1 的"抖空"两种失效。

**消除断崖的具体动作**（逐条对应 D1-D4 + 新增 D5）
- D1/D3：`stock_api` 全部 `_MAX_CACHE_AGE` 引用 → `cache_policy('quote'|'fundflow'|'timeline'|'f10')['ttl']`；`fetch_cls_*` 传给 `fetch_json` 的 `ttl` 用同一个值（**同一变量、同一次调用**，不是"两个相等的常量"）。
- D2：`_BASIC_INFO_POOL_REFRESH/_FUNDFLOW_POOL_REFRESH/_TIMELINE_POOL_REFRESH/_F10_POOL_REFRESH/_ANNOUNCEMENT_POOL_REFRESH` 全部删除，改用 `cache_policy(d)['pool_refresh']`；prefetch 循环 `sleep(interval)` 的 `max(refresh, L1)` 改为 `refresh`（`refresh` 已 ≥ L1）。其中 **`_BASIC_INFO_POOL_REFRESH` 为死常量**——全仓无 import/引用，且**不存在 basic_info prefetch loop**（4 条 loop = fundflow/timeline/f10/announcement），删除**无迁移**。
- D4：`_get_or_fetch_feed` 的 `expires_at` 由 `cache_policy('feed')['ttl']` 派生（交易时段 = L3=30s，**非交易时段 = L3=180s**），与 `_cache_age()` 的 RSS 分支**读同一个 policy**，保证"承诺 = 行为"。
  > ⚠️ 行为变更提示（Q3，本次必做）：① 交易时段 300s → **30s**、非交易时段 300s → **180s**，两段都在变更范围；② `CACHE_TTL` 消费者核定为 **`cache.py` 默认 ttl + `server._get_or_fetch_feed`**；**`utils.py:12` 是未使用 import**（随常量删除；`warm_jin10` 经 `fetch_json` 默认值，迁移后 = `cache_policy('news_url')['ttl']`）——删常量前逐点迁移到 policy；③ feed 缓存**机制落点 = `cache.feed_cache_get`/`feed_cache_put`**（LRU/双触发清扫/淘汰归缓存层，守 `layerIsolation`），`server._get_or_fetch_feed` 只保留 `_feed_fetch_locks` per-path 防击穿并调用二者（miss → per-path lock → **二次 `feed_cache_get` 双检** → fetch → `feed_cache_put`；§3 已同步）；④ AC-A8"间隔 2×TTL 后仍含全部条目"的 TTL 口径同步；⑤ 上游请求量 ×10（AR-6，加每域 fetch 计数）。
- D5（新增长度，修 P1-4）：`fetch_json` 增加 `encoding='utf-8'` 形参（默认不变、向后兼容），`/ths/longhu` 的两个上游 URL 一律 `encoding='gbk'`（详见 §2.3 D-5 与 ADR-001）。

**不选其他**：不引入"全局统一 TTL 单值"——行情/板块/新闻/日更的时效需求天然分层（2.3 场景特征约束），压成单值会让日更数据被高频重取或让行情变钝。分层 + 单一**派生函数**才是正解。

**权衡**：`cache_policy` 引入一次函数调用（dict 查表，纳秒级），相对 5ms 的本地命中预算可忽略；收益是"改一处、全系统对齐"。

### 2.2 资源有界模型（R2/R3/R6/R7/R11 + EFF-3）

**R-1 线程与请求并发（主端口）**
- 保持 `MAX_WORKERS=20`，`inflight = max_workers × 2 = 40`（20 运行 + 20 排队封顶）——**现实现已满足 AC-E8 的目标口径**，本次只做两件事：
  ① 把 `max_workers*2` 提为显式配置 `MAX_INFLIGHT`（默认 40，env 可调），使"40"不再是隐式推导；
  ② 达上限**立即 503 不排队**（现状已如此，补指标计数）。
- 关键结论：40 是**突发吸收**而非**吞吐扩容**——排队请求仍要等 worker。持续吞吐的上限由 §4.2 的并发公式决定。

**R-2 SSE 连接与队列（流端口）**
- 连接硬界 `MAX_STREAM_CONNS=100`（现状保留）；超限 503。
- 单连接队列 `maxsize=8`，满则**丢最旧保最新**（现状正确保留）。
- **新增全局队列字节预算** `STREAM_QUEUE_BYTES_BUDGET`（默认 **128MB**）：计费口径为「**distinct 帧对象字节 × 深度**」，**不是**"每次入队累加 `len(frame)`"（后者会把同一帧按连接数重复计费 → 1 组 100 连接 × 14MB = 计 1.4GB，预算按构造必超，修 P0-1）。计费与推导见 §4.2「帧共享与字节计费」。
- **新增组数上限** `MAX_GROUPS`（默认 200，env 可调）：`create_group` 超限返回 400。**注意：`MAX_GROUPS` 是 CPU/帧构建数护栏（每 tick 帧构建次数 ≤ 组数），不是内存护栏**——跨组帧内存的护栏是上面的字节预算（修 P0-1 的"MAX_GROUPS 界不住内存"）。`MAX_DEDUP_CODES=2000` 仍为码总上界（200 组 × 200 码 > 2000，故码上限才是主导约束）。
- **新增单帧余量准入（v1.4，修 S2-2/P1-4）**：`create_group`/`patch_group` 不仅要求**稳态跨组 distinct 帧工作集** `projected = Σ_g F_g` 落入预算，还要求 **`projected + largest ≤ STREAM_QUEUE_BYTES_BUDGET`**（`largest = max(其余组的最大单帧, 本次新增组的帧)`；`patch_group` 用 `exclude_sid` 重新计价被替换的组）。**理由**：只卡 `projected ≤ B` 时，一个恰好填满预算的合法集合（满配 9 组）会让**每一次 `_broadcast` 都必须驱逐一个真实帧**才能为新帧腾位——预算从"内存护栏"退化为"每 tick 丢帧机"，AC-E5「任一连接丢弃 ≤1 帧」的稳态前提被破坏。加上**一份最大帧的余量**后，满配组容量由 `floor(B/F_max) ≈ 9` 收敛为 **8**（见 §4.2）；写入 `_FRAME_BUDGET_ERR`（400）的理由串与 `STREAM_QUEUE_BYTES_BUDGET` 一致。
- **帧尺寸模型单一来源**：`config.stream_frame_bytes(num_codes, num_fields) = codes × fields × STREAM_FRAME_BYTES_PER_FIELD(23KB)`。**准入判据、队列预算推导、测试断言必须一律调它**，不得在 stream/server 内重新展开常量（否则"准入"与"计费"会各用一套尺寸模型）。

**R-3 缓存容量与淘汰（修 R3/R11：FIFO 伪装成 LRU）**
- URL 缓存：容器改 `collections.OrderedDict`；命中路径（`fetch_json` 早返回处）`move_to_end(url)`；淘汰改 `popitem(last=False)`（O(1) 真 LRU，见 ADR-008）；清扫**双触发**——① 每 `_CACHE_SWEEP_INTERVAL`（保留 60s）全量全扫过期；② 写入时若 `len(d) >= MAX_CACHE_SIZE` 先做**局部清扫**再淘汰。上限 2000 保留。
- feed 缓存：同样改 `OrderedDict` + 命中 `move_to_end` + `popitem(last=False)`（修 R3）；上限 100 → **收敛为 policy 派生**（`feed.cache_max=100`；feed 已改 30s/180s TTL，条目自然更替，100 条 × ~300KB = 30MB 占总预算可接受，见 §4.3）。**机制落点 = `cache.feed_cache_get` / `cache.feed_cache_put`**（LRU / 双触发清扫 / 淘汰均实现在缓存层，符合"缓存机制归缓存层"且不破 `layerIsolation`；裁决 #3）；`server._get_or_fetch_feed` **只保留** `_feed_fetch_locks` per-path 防击穿职责并改为调用这两个函数——miss 流程 = `feed_cache_get` miss → per-path lock → **二次 `feed_cache_get`（双检）** → `fetch_func` → `feed_cache_put`（`server.md` 必须按此对齐，否则防击穿退化为串行穿透）。
- 端点缓存（`_*_cache`）：**与去重池解耦**（修 P1-1）——`_process_chunk` 的池淘汰**不再** `cache.pop`；端点缓存改由自身 `cache_policy(d)['cache_max']` 做 LRU + TTL 淘汰；新增 `ttl` 注入后，`_process_chunk` 的过期判定与 URL 缓存同源。

**R-4 内存总账**（新增 `metrics` 可观测，见 §2.6）
将下述量显式建模并在 `/healthz` 暴露（条目数 + 估算字节），任一超阈告警日志：
`URL 缓存条目/字节` · `各端点缓存条目/字节` · `feed 条目` · `SSE 队列字节（distinct 帧去重计费）` · `distinct 帧数/帧平均/峰值字节` · `活跃组数/连接数`。**不引入任何存储**，纯内存计数。

**R-5 管理请求 IO 预算（R6）**
`_read_json_body` 前置 `self.connection.settimeout(MGMT_BODY_TIMEOUT=5)`，读完恢复为 30s（长连接/SSE 不受影响）；保留 64KB 体长上限。预算来源：`MGMT_BODY_TIMEOUT` 走 config + env（R17）。

**R-6 分片轮转刷新（AR-1 的正确缓解对象，修 P1-1 / P1-N1；v1.4 按实现重标定）**
tick 的刷新集是 `_active_codes()`（**可达 `MAX_DEDUP_CODES=2000`，不受池上限约束**），字段集是**存活组订阅字段并集**（`_subscribed_fields()`）；单周期取数能力 `coverage = 23 取数次数/周期 ⇒ coverage_codes = 23 / 11 / 7 码/周期`（1 / 2 / 3 域，见 §2.1 INV-1b）。当 `_fetches_per_code(fields) × N_active > coverage`（条件 C2）时：

- `push_loop` 每 tick 只对 `_active_codes()` 的一个**切片** `slice`（按码计量）发起网络刷新，切片须满足取数次数上界：`_fetches_per_code(fields) × |slice| ≤ coverage`（`coverage` 已内含 0.8×tick 预算）⇒ `|slice| ≤ coverage_codes`。切片按轮转游标推进（**复用 `_prefetch_slice` / `_prefetch_advance`**，游标键 `'stream_refresh'`，与 prefetch 池的 round-robin 语义同一实现）。
- **`codes` 与 `fields` 必须在同一次加锁中读出**（`_active_targets()`）：两次独立读会与"组关闭"交错，得到一个**字段集已不再被订阅**的码池（P1-6）。
- 未进入本切片的码，其数据从**终点缓存读取**后并入快照（`snapshot = fresh(slice) ∪ cached(active−slice)`，`cached_batch(domain, rest)` **无网络**）。
- **未刷新码的 last-known 结转（v1.4 新增）**：仅靠 `cached(active−slice)` 会让"终点缓存已过期但本 tick 又未进切片"的码以纯 `null` 出现，与"该码根本没有数据"不可区分（AC-A1/值域三分的降级版）。故 `_carry_forward(snapshot, codes, fields)` 维护 `_last_known[code][field]`（**每 tick 按存活码池剪枝** ⇒ 上界 `MAX_DEDUP_CODES`），把上一 tick 的非空值补进本帧；被补过的码进帧内 `stale` 列表（`stale_count`）。**一个码不会同时进 `stale` 与 `missing`**（只有真的存在过旧值才会 stale）。
- **tick 与 deadline 单次计算、向下传递（v1.4）**：`_push_once` 计算 `tick = tick_interval()` 一次并传给 `_refresh_pool`，**C1/C2 门限与调度节拍因此不可能在 tier 翻转点（09:30/11:30/13:00）互相矛盾**（旧实现两处各自求值，曾出现 8s vs 120s 的分歧）；`_refresh_pool` 内所有字段相**共享同一 `deadline = t0 + 0.8×tick`**，某字段相启动时已过 `deadline` 则**跳过**并把该切片码标 `_errors[code]='tick_budget_exceeded'`，绝不阻塞 push 线程（旧实现每相各自回退到 `_BATCH_BUDGET_REST=15s`，三相串行最坏 45s ⇒ 最忙时所有 SSE 连接收不到帧）。
- **帧完整性口径（修 P2-N2，v1.4 补 last-known 后收敛）**：**warm（有终点缓存/有 last-known）码的帧完整性不降级**；**冷码（既无缓存也无历史）在进入首个切片前以 `null` 出现于 `missing`**（不再"缺席"），在 ≤ lag 个 tick 内首次取得数据。故 AC-A1 的"每帧覆盖全部码"以 **warm 稳态 + 200 帧窗口**为前提，首帧即全覆盖**不是**本降级路径的保证。
- 记录 `stream_refresh_lag_ticks`（= `ceil(N_active / |slice|)`，C1 时**发布 0**）与 `stream_tick_degraded_total`；`_fetches_per_code(fields) × N_active ≤ coverage` 时退化为原"整池一周期刷新"，lag=0。**空池时该 gauge 由 `_push_once` 置 0**（不能在 `_refresh_pool` 里重置——空池路径根本到不了那里，否则最后一个订阅消失后 gauge 永久停在最后一个 C2 值）。
- **切片上限随 tick 动态**：`coverage` 与 `tick` 成正比，非盘中 `tick=120` ⇒ `coverage=349 ⇒ 3 域 coverage_codes=116`。**不得**把盘中值 7/23 硬编码为断言（SAD 只给盘中实值口径）。
> 说明：AR-1 原缓解"池上限=200/域"对准的是 prefetch 池，而 tick 刷新集是 `_active_codes()`——缓解对象错误（P1-1 附带项）。R-6 直接约束 `_active_codes()`。

**不选其他**：不为 SSE 改异步/多路复用（违反"标准库 + SSE 全量帧"约束与 W 级范围）；不为缓存引入 TTL 调度器线程（净增线程无收益，双触发清扫已够）；不靠"调大 `_BATCH_MAX_WORKERS`"兜 coverage（会放大上游压力且违反 AC-E8 资源口径）；**不把 `_FIELD_HANDLERS` 的 3 个字段 handler 改并发执行以抬高 coverage**——单 handler 内已用满 `_BATCH_MAX_WORKERS=8`，字段级并发会把在飞取数抬到 24，违反 AC-E8 资源口径（修 P1-N1 的备选方案评审结论）；**也不靠"把每码成本一律记 3"来保守**——那会把 quote-only 组的刷新能力**低估 3 倍**（`coverage_codes 23→7`），制造一个不存在的容量不足（v1.4）。

**权衡**：全局队列字节预算的计费在**帧构建/入队/出队**三处各一次 O(1) 引用计数（见 §4.2），成本可忽略；换来的是唯一能兜住"组×码×帧"组合爆炸的机制。

### 2.3 降级与超时矩阵（R9/R13/R14 + AC-S3/S7）

**D-1 失败状态层：负缓存 + 半开探测（修 P1-2）**

在 `cache.py` 新增与 `cache{}` 平行的结构：

```
_negative: dict[url] = {'until': ts, 'kind': 'upstream_timeout'|'upstream_error'|'cdp_unavailable',
                        'fail_count': int, 'first_at': ts}     # ★ v1.4 补 first_at（失败历史窗口起点）
NEG_TTL      = min(5, cache_policy('quote')['ttl'])   # 交易/非交易均 = 5s（守 PRD §5 #4 ≤5s 恢复延迟）
PROBE_TIMEOUT = 2                                      # ★ 半开探测**阶梯起点**（有失败历史时）
_PROBE_BUDGET_CAP = 5.0                                # ★ v1.5 阶梯**封顶**（AC-S3 裁决；不再升到 REQUEST_TIMEOUT）
_HISTORY_AGE  = 600.0                                  # ★ 失败历史老化窗口（缓存机制常量，非域 TTL）
_FOLLOWER_WAIT_MARGIN = 1.0                            # ★ follower 等待窗口的调度抖动余量
_negative 上限 = MAX_CACHE_SIZE (2000)；满额淘汰最旧 'until'
```

**探测预算：阶梯递增、5s 封顶（v1.4 更正"恒定 2s"；v1.5 按 AC-S3 裁决设封顶）**

```
_probe_budget(fail_count) = PROBE_TIMEOUT 起步、每级 ×2、_PROBE_BUDGET_CAP 封顶
                          = 2 → 4 → 5(s)；fail_count < 1 视同 1
                          # ★ v1.5：封顶 = 5.0，非 REQUEST_TIMEOUT(10s)（AC-S3 裁决）
_fetch_budget(url)        = 无条目             → REQUEST_TIMEOUT (10s)   # 首次冷请求
                            有条目且已老化      → REQUEST_TIMEOUT (10s)   # 全预算探测一次（**不经过阶梯上限**）
                            有条目且未老化      → _probe_budget(fail_count)
```

**为什么封顶在 5s（而不是 10s）**：持续黑洞下稳态周期 = `5s 探测 + 5s NEG_TTL` = **10s**，其间约一半请求落在探测窗口（耗时 ≈5s）、另一半命中未过期负缓存（≈0，不计入慢尾）⇒ **高请求密度 P95 ≈ 5s**；低请求密度下多数请求落在负缓存内，P95 退化为**周期上界 ≈10s**；**任何单请求 ≤15s**。封顶 10s 会把慢请求占比推到 10/15≈67% ⇒ P95≈10s（v1.3 的错误论证）。**注意"阶梯上限"与"老化全预算"是两条不同路径**：老化触发的那次用 `REQUEST_TIMEOUT=10s` 且不经过 `_PROBE_BUDGET_CAP`。

**失败历史老化（`first_at` + `_HISTORY_AGE=600s`）**：`first_at` 记录**当前连续失败段**的起点且**不被后续失败刷新**（仅"老化触发后的那次失败"重置为 `now`，开启新窗口）。判定预算时 `now − first_at ≥ 600s` ⇒ **视同无失败历史**，本次用 `REQUEST_TIMEOUT(10s)` 全预算探测一次。**为什么必须有**：若预算恒定钉在 2s，一个"慢而 >2s 才成功"的上游会**永远**失败（`fail_count` 只增不减 ⇒ 永远 2s），且成功才清历史 ⇒ 与 AC-E2 长期互斥（"永久 2s 陷阱"）。老化 + 阶梯让此类上游在数个周期内自愈，而不是苦等 10 分钟。**AC-S3 影响量化（v1.5 重标）**：封顶后**不存在"阶梯爬到 10s"的常驻档**（顶端 = 5s）；老化窗口（`_HISTORY_AGE=600s`）每窗至多放行 **1 次** 10s 全预算探测 ⇒ 属稀有事件、不改变分档 P95。**P95 口径（与 PRD v0.5 AC-S3 一致）**：高请求密度 ≤5s / 低请求密度 ≤10s（周期上界）/ 单请求 ≤15s。**任一分量（`_PROBE_BUDGET_CAP` / `NEG_TTL`）变动必须连带重标 AC-S3 分档**；若运维调小 `_HISTORY_AGE`（< ~120s）**必须重跑 AC-S3 模式 B 校准**（§9.5 登记）。

`fetch_json` 语义收敛为**五段式**（这是 §2.3 最重要的行为变更；**v1.4** 在原"四段式"的段 1 与段 2 之间插入**端到端 deadline 闸门**）：

1. 命中正缓存 → 返回 str。
2. **（v1.4 插入）端到端 deadline 闸门——位于正缓存之后**：`fetch_json(url, headers=None, ttl=None, encoding='utf-8', deadline=None)` 新增**第 5 位形参** `deadline`（绝对 epoch 秒，纯新增 ⇒ 既有 18 个调用点零改动）。若 `deadline` 已过且无正缓存 ⇒ 立即 `raise FetchError('upstream_timeout')`，**不触网、不写负缓存**（这是"我们自己的预算"，不是上游故障，与 §2.3 D-6 的 `_LOCAL_BUDGET` 同一条纪律）。**闸门必须在正缓存之后**：一次正缓存命中零网络零延迟，调用方耗尽的批预算**不得**否掉手里已有的数据——否则缓存永远救不了它本该吸收的那个慢批。
3. 命中负缓存（未过期）→ **立即 raise `FetchError(kind)`**，不触网（<1ms）。
4. 否则走一次 leader 选举；leader **只尝试一次**，超时预算为 `_fetch_budget(url)`（上表：首次 10s / 未老化阶梯 / 老化后 10s），且再被 `min(budget, max(0.05, deadline−now))` 夹紧。失败即写入负缓存（`until = now + NEG_TTL`，`fail_count += 1`，`aged` 时重置 `first_at`；`kind` 按异常分类：`socket.timeout`/`TimeoutError`/`URLError(reason=timeout)`→`upstream_timeout`，其余→`upstream_error`）后 raise；**成功则删除负缓存条目（清除失败历史）**。
5. follower 等待 leader 结束：`event.wait(timeout=_fetch_budget(url) + _FOLLOWER_WAIT_MARGIN)`（再被 deadline 夹紧），随后**读状态**，**不再重入选举**。删除 fall-through 的 `Semaphore(2) + sleep(0~0.5) + 3s acquire` 组合路径（13.5s 来源）。
   - **`_FOLLOWER_WAIT_MARGIN=1.0` 的作用**：leader 的预算只覆盖网络；"取到数据 → 写正缓存/清负缓存"是若干微秒的收尾。follower 只等 `budget` 会**系统性输给**这个收尾竞态，被推进 gap 分支。+1.0s 只吸收调度抖动，**不是**第二个网络预算。
   - **gap 分支兜底（D-1 补记）**：正常时序下 leader 在 `finally` 置位 `event` **之前**必已写正缓存或负缓存，故 follower 必命中其一。若两者**均未命中**：① `url` 仍在 `_fetch_inflight` ⇒ leader 仍在飞（超出我们的等待窗）⇒ raise `FetchError('upstream_timeout')`（**我们自己的等待预算，不写负缓存**）；② 否则 fail-closed `raise FetchError('upstream_error')`（不触网，不引入放大器）。
   - `cache.py` 允许 import 新增 **`socket`**（供 `_classify` 判定 `socket.timeout`/`TimeoutError` 与其余异常；`socket` 已在 `tech-stack.json` allowlist 内，不破零依赖）。

> **AC-S3 模式 B（黑洞）延迟推导（修 P1-2；v1.5 按 5s 封顶重标）**——按 URL 的时间线：
> - **首次冷请求**（无失败历史）：阻塞 `REQUEST_TIMEOUT=10s` → 落负缓存。**每个 URL 只发生一次**。
> - **其后每轮**：探测阻塞 `_probe_budget`（2s → 4s → **5s 封顶**）→ 落负缓存 `5s` → 再探测。稳态周期 = `5s 探测 + 5s NEG_TTL` = **10s**，其中**唯一 >1ms 的请求是那次探测**。
> - ⇒ **分档达标口径（PRD v0.5 AC-S3）**：① **高请求密度**（到达间隔 ≪ 10s 周期，必然采样到探测窗口）⇒ 慢请求占比 ≈50% ⇒ **P95 ≈ 5s ✓**；② **低请求密度**（间隔 > 1 个周期，多数请求落在未过期负缓存内）⇒ P95 退化为**周期上界 ≈ 10s ✓**；③ **任何单请求 ≤15s ✓**（探测 ≤5s、首次冷请求 ≤10s、follower 等待 ≤ `5s + 1s`）。
> - **`_HISTORY_AGE=600s` 的角色（v1.5 收窄）**：它不再用于"把 10s 档停留封顶在 600s"（顶端已是 5s），而是提供一条**周期性全预算探测**通道——老化触发的那次用 `REQUEST_TIMEOUT=10s`（**不经过阶梯上限**）并重置 `first_at`，让"慢而未死"上游最终仍有一次拿满预算的机会。
> - **⚠️ 权衡登记（v1.5 新增，替代原"稳态 P95≤2s"论证）**：一个**需要 6–10s 才返回的"慢而未死"上游**，在失败累积后**无法再靠阶梯自愈**（顶端钉在 5s < 它所需），只能等 `_HISTORY_AGE=600s` 老化后拿一次 10s 全预算 ⇒ **该类上游的恢复延迟最多约 600s**。**快速黑洞 / 连接秒拒类不受影响**（其失败与恢复完全由 5s 档覆盖）。**若该恢复延迟不可接受，收敛路径是调大 `_PROBE_BUDGET_CAP`（连带重标 AC-S3 分档）而非改 `_HISTORY_AGE`**（见 AR-13 ④）。
> - **⚠️ 待 P6c 实测校准（Q6 延续）**：① "慢而未死"上游的出现频度与 600s 老化窗口的相对占比需实测；② 高/低密度两档 P95 需按 AC-S3 **分两轮**采集（不得合并，合并会被高密度样本覆盖）。**登记为 AR-9/AR-13。**
> - **模式 A（连接秒拒）**：`urlopen` 对 RST/ECONNREFUSED 立即抛错，负缓存后全部 <1ms，P95 ≤ 1s ✓。
> - 两种模式路径不同、可分别断言，符合 PRD P2-3「不得合并注入」。
>
> **不误伤慢而成功的 leader**：短探测**仅对"有失败历史且未老化"的 URL 生效**；全新的正常慢回源仍用 10s 预算，AC-E2（P95 1.2s / P99 3s）不受影响。

**D-2 期限贯通（R13；v1.4 补实现口径）**

- 统一所有取数器签名 `fetcher(code, deadline=None, ttl=None)`（`ttl` 为第 3 形参，供 INV-1a 的"同源同变量"）；REST 系取数器把剩余预算传给 `fetch_json(..., deadline=...)`（**v1.4**：`fetch_json` 自身新增 `deadline` 形参，见 D-1），由其在**正缓存之后**判超期并夹紧 `urlopen` 超时——调用方**不得**在 `fetch_json` 之前自设 deadline 闸门（会让批预算耗尽时把**已在 URL 缓存里**的数据也判成 `null`）。
- 取数器调用点的**参数绑定容错**限定为"**调用帧** `TypeError`"：`_call_fetcher` 依次尝试 `{deadline,ttl} → {deadline} → {ttl} → {}`，仅当 `TypeError.__traceback__` 无下一帧（即参数绑定失败）才降级；**fetcher 体内的 `TypeError` 一律原样抛出**（重试会执行两次取数）。
- `_handle_cached_batch` 增加 `budget`（默认 = handler 的端到端预算）；每进入一个 chunk 前重算 `chunk_deadline = min(budget, now + chunk_budget)`，`chunk_budget = ceil(len(chunk)/BATCH_MAX_WORKERS) × per_call_timeout`。**预算耗尽即停止取数，未完成码返回 `None` 且写 `_errors[code]='upstream_timeout'`**（对外形状）——有界降级，绝不无界等待。
- **本地预算耗尽的标记与语义（`_LOCAL_BUDGET`，P1-1）**：`_fetch_one`/`_run_batch` 在 `deadline` 已过时**不创建任何线程**，逐码产出内部标记 `_LOCAL_BUDGET = '__local_budget__'`（**故意不是** `FetchError.KINDS` 成员）；`_process_chunk` 把它**翻译**为对外的 `'upstream_timeout'`，但**绝不写码级冷却账本**（见 D-6）。理由：把"我们自己的预算耗尽"记成"上游连续失败 3 次"，会让**一个慢批把整条码池尾巴推进 120s 冷却**——自我施加的正反馈，越快越糟。
- `_run_batch` 返回结构从 `{code: data}` 改为 `(results, errors)`（**管道层内部结构**，供 §2.4 组装保留键）。

**D-3 超时矩阵（对齐 AC-S7，含"31s→5s"）**

| 层 | 参数 | 现状 | 目标 | 依据 |
|----|------|------|------|------|
| REST 回源 | `REQUEST_TIMEOUT` | 10s | 10s（不变），P95 目标 1.2s | AC-E2/S7 ≤11s |
| **负缓存半开探测** | `_probe_budget(fail_count)` | 无 | **2s → 4s → 5s 阶梯（`_PROBE_BUDGET_CAP=5.0` 封顶）**（仅有失败历史的未老化 URL）；老化（≥`_HISTORY_AGE=600s`）后本次用 10s 全预算（**不经过阶梯上限**） | **AC-S3 模式 B / P1-2 / v1.5** |
| **follower 等待窗口** | `_fetch_budget + _FOLLOWER_WAIT_MARGIN(1.0)`，deadline 夹紧 | 无 | 同上 +1s 抖动余量；窗口后复查 `_fetch_inflight` | AC-S3 / S1-1 |
| **端到端 budget 耗尽** | `fetch_json(deadline=)` / `_LOCAL_BUDGET` | 无（`TypeError` 静默丢期限） | 正缓存后判超期 → `FetchError('upstream_timeout')`，**不触网、不记冷却** | AC-E2 / S7 / P1-1 |
| CDP 页面求值 | `evaluate_fetch` / `navigate_stock` | 8s / deadline | 8s / 由调用方 deadline 约束，上限 8s | AC-S7 ≤9s |
| SSE 写阻塞 | `connection.settimeout` | PING×2 = 40s | 40s（不变） | AC-S7 ≤41s |
| **流端口管理体读取** | socket `timeout` | **30s（管理请求共用）** | **5s（`MGMT_BODY_TIMEOUT`）** | **AC-S7「31s→5s」** |
| 主端口请求 | `RSSHandler.timeout` | 30s | 30s | 兜底 |
| healthz 整体 | 无 | 最坏 50s | 单源 ≤3s、整体 ≤10s | AC-S8 |
| SSE tick 刷新 | 无 | 可超过 tick | ≤ `0.8 × tick`，超时打 degraded 标记 | AC-E5/S10 |

**D-4 CDP 降级路径（三分清单落地，AC-S4）**

决策：**降级形态由"端点形状"决定，不由"依赖度"决定**——因为消费方的解析方式由形状决定（扁平 vs 客体）。

| 类 | 端点 | 无 CDP 时 | 实现落点 |
|----|------|----------|---------|
| A（4 单体/面板） | `/finance/market` `/finance/timeline` `/quotation/market` `/market/timeline` | HTTP 200 + `{"error": ...}` 客体 | `handle_*` 首行 CDP 能力门（现状已有），**补** `timeline` 缺失时不再返回裸 `null` 而是 error 客体（修 R18 旁支） |
| A′（1 批量） | `/stock/f10` | HTTP 200 + `{"<code>": null}` + `_errors[code]="cdp_unavailable"` | `fetch_cls_f10` 在 CDP 不可用/取数失败时 `raise FetchError('cdp_unavailable')`，由 §2.4 组装 |
| B（14 REST 替代） | `/stock/data` `/stock/fundflow` `/stock/timeline` `/stock/announcement` `/cls/hotplate` `/cls/plate` `/ths/longhu` `/market/margin` `/stock/basic_info` + 5 RSS | 完整数据、0 error 客体 | 保持 REST 优先（现状已满足）；`/cls/hotplate` **保持"分区 error 客体"语义**（`plate_<type>` = `{'error':...}`，现状即如此）并计入 metrics；**仅当全部分区失败时**顶层补 `error` 字段以满足 AC-A5 的单体口径（见 §2.4，修 P2-3②） |

**D-4 补充（修 P2-3② 自相矛盾）**：`/cls/hotplate` 的失败形态**唯一口径** = 分区 error 客体（分区降级）+ 全分区失败时顶层 error。ADR-007 中"可按需精细化（逐板块 error）"与本表一致，不再存在"改为单体 error 客体"的第二种表述。

**D-4 补充 2：CDP 降级语义（v1.4 按实现回写）**

| # | 语义 | 实现口径 |
|---|------|---------|
| ① | **防御取数唯一入口** | `cdp_engine.page_data(page)`：**总函数、永不抛**。`page is None` / `get_data()` 抛异常 / 返回非 dict / 返回空 dict（重启窗口内缓存被清）⇒ 一律返回 `None`；**不做键级回退**，由调用方按端点形状决定承载（面板 → error 客体；批量 A′ → `cdp_unavailable`）。禁止对页面数据的一切"假定为 dict"的直接 `.pop/.get` 链 |
| ② | **重启窗口必达终态** | `_mark_restarting/_mark_idle/_mark_unavailable` 是窗口状态的**唯一写者**，读只经 `restart_window_snapshot()`（拷贝）。`full_chrome_restart` 在 `finally` 中**兜底**：若返回时状态仍是 `restarting` ⇒ 置 `unavailable`。`ensure_chrome` 的"which/Popen 在 fork 压力下抛异常"路径同样 fail-closed 置 `unavailable`。**不存在"卡在 restarting"的转换**——否则 `watchdog_restart_skip_reason()` 会永久返回 `already_restarting`（守护重启彻底失效）且 `/healthz` 误报 |
| ③ | **`_last_data` 老化：时钟缺失 = 陈旧** | `get_data()` 合并"活缓存 + `_last_data` 补洞"，但只接受 `_last_data_ts[k]` 存在**且** `now − ts < _last_data_max_age(600s)` 的条目。**时钟缺失（`None`）算陈旧、不算新鲜**——`_reconnect()` 会同时清 `self.cache` 与 `_last_data/_last_data_ts`，若把缺失时钟当新鲜，重连后的空时钟会把**重启前快照**无限重发（P1-3）。`_ingest_payload` 写入值与时钟并在同一临界区，`_evict_stalest_last_data_locked` 保持 `_last_data/_last_data_ts/_key_last_seen/_api_urls` 四表同步 |
| ④ | **导航锁限时（不无限排队）** | `navigate_stock(code, timeout)` 经 `_acquire_navigate_lock(timeout)` **有界等待**：`timeout ≤ 0` 或锁在整个预算内被占 ⇒ 返回 `False`（降级），**不 park 调用方**。CDP 页池极小，"无界等待锁"曾把所有准入槽位占满 ⇒ 全站 503。获得锁后按剩余预算重算：`remaining < 2s` 直接复查缓存返回、`Page.navigate` ≤ `min(10, remaining)`、`loadEventFired` 等待 ≤ `min(15, remaining)`。代码先经 `config.canonical_code` 折叠，再与页面 `SecuCode` 比较（两处都归一 ⇒ 两种入参拼写都能匹配） |
| ⑤ | **降级计数** | `upstream_fail_total{cdp_unavailable}` 由 `stock_api._raise_cdp_unavailable()` **单一出口**计数（4 处出口收口，避免少计/重计） |


**D-5 取数编码参数（新增，修 P1-4）**

`fetch_json(url, headers=None, ttl=None, encoding='utf-8')`：`resp.read().decode(encoding, errors='replace')`。默认 `utf-8` 保持既有 18 个调用点零改动；`/ths/longhu` 的两个 GBK 上游 URL 显式传 `encoding='gbk'`。

```
# server.handle_ths_longhu（改走统一入口，修 R15）
ttl = cache_policy('longhu')['ttl']            # L4 = 300s（AC-E9 要求 ≥300s）
stock_html = fetch_json(LHBTABLE_URL, LH_HEADERS, ttl=ttl, encoding='gbk')
page_html  = fetch_json(LONGHU_PAGE_URL, PAGE_HEADERS, ttl=ttl, encoding='gbk')
```

- 缓存键 = `url`（编码是域的确定属性，同 URL 不会以两种编码出现；列入 §7.3 假设）。
- **AC-E9 计数口径澄清**：`/ths/longhu` 每次请求打 **2 个**不同上游 URL（lhbtable + longhu 页）→ "上游请求计数 = 1"应写成 **"每个 URL 各回源 1 次，共 2 次"**；连续 10 次请求其余 9 次均命中缓存。

**D-6 共享失败状态层：负缓存（URL 级）+ 码级冷却（修 P1-5）**

AC-S6 的"同码连续失败 3 次 → 120s 冷却、冷却期内不回源"断言发生在**批量请求路径**，但现状 `_FAIL_COOLDOWN=120` 只存在于 4 个 prefetch 循环的局部 `fail_blacklist`，`_process_chunk→_run_batch→_fetch_one` **没有任何冷却判断**。设计：

```
# stock_api.py — 模块级、批量路径与 prefetch 路径共用（单一失败状态层）
_fail_ledger: dict[(domain, code)] -> [fail_count:int, cooldown_until:float, kind:str, last_fail_ts:float]
                                       # ★ v1.4：由二元组更正为 4 元（[3] = 最近一次真实失败时刻，用于老化）
_fail_ledger_lock = threading.Lock()
FAIL_THRESHOLD = 3
FAIL_COOLDOWN  = 120          # 秒，与现状一致
_FAIL_DOMAINS  = ('quote', 'fundflow', 'timeline', 'f10', 'announcement')
_FAIL_LEDGER_MAX = len(_FAIL_DOMAINS) × MAX_DEDUP_CODES = 10000

判定位置：_process_chunk 取数前（命中终点缓存之后、_run_batch 之前）
  entry = _fail_ledger_get(domain, code, now)
  if entry and now < entry[1]:
      result[code] = None; errors[code] = entry[2] or 'upstream_error'   # 不触网
      continue
计数口径：仅"取数失败（异常/超时）"计入——即 _run_batch 返回的 errors[code] 非空时
          fail_count += 1（同一失败段内累加，`now − entry[3] > FAIL_COOLDOWN` 则重新从 1 起算）；
          成功 → 删除条目；result 为 None 但无 error（上游无数据）→ **不计**；
          **`_LOCAL_BUDGET`（本地预算耗尽）→ 翻译为 `upstream_timeout` 对外，但绝不入账**（v1.4 实现；**v1.5 编排层正式反转 REV-DES-15 裁决②并确认**，见 D-2 / ADR-014）
触发：fail_count ≥ FAIL_THRESHOLD ⇒ cooldown_until = now + FAIL_COOLDOWN
```

- **归属**：码级（`(domain, code)`），非 URL 级。URL 级负缓存（`NEG_TTL=5s`）与码级冷却（`FAIL_COOLDOWN=120s`）**叠加不冲突**：URL 负缓存管"网络层 5s 不回源"，码级冷却管"该码 120s 内整体降级"。
- **与 prefetch 统一**：4 个 prefetch 循环的局部 `fail_blacklist` 删除，改读写 `_fail_ledger`（同一把锁、同一计数），使批量与后台对"失败码"的认知一致。
- **`_LOCAL_BUDGET` 不入账是刻意反转（v1.4 实现；v1.5 编排层正式裁决确认，取代 REV-DES-15 的"建议②"）**：v1.4 前的设计曾决定"预算耗尽也计入冷却账"，实现与实测否掉了它——一次慢批会把**整条池尾巴**（那些根本没被网络碰过、只是排在预算之后的码）记成"连续失败 3 次"，下一批它们全部进 120s 冷却，冷却又让批次更快耗预算 ⇒ 自激正反馈。现口径与 `cache.py` 的 S1-1 逐字一致：**"我们自己的预算"从不写成"上游故障"**。（登记：AC-S6 的"同码连续失败 3 次"口径据此限定为**真实上游失败**；PRD v0.5 §9.1③ 已同步固化，反转不再是"实现单方面偏离评审"。）
- **`code_cooldown_list` 的发布节流**：该 gauge 是**可枚举清单**（`[[domain, code, cooldown_until], ...]`），重建是 O(n)，**至多每 `_COOLDOWN_PUBLISH_INTERVAL=5s` 发布一次**（含 cooldown 开启的那次转换——早期实现让"开启"绕过节流，冷启动故障时会在锁内每次写入都重建全表 ⇒ O(n²)）；`_fail_ledger_prune_locked` 的老化扫描同样限流 `_FAIL_LEDGER_PRUNE_INTERVAL=5s`，硬上界淘汰用 `dict` 插入序前端弹出（O(1)）。≤5s 的发布滞后对 120s 冷却无影响。导出/断言用 `stock_api.code_cooldown_list()`（直接读账，不受节流影响）。
- **导出**：`code_cooldown_list()` 返回 `[[domain, code, cooldown_until], ...]` 供 AC-S10。

**不选其他**：不为 CDP 端点做"CDP 不可用时返回缓存旧值"（与 R10「过期=拒读」冲突，且短线场景旧价 > 无价是错误取舍）。

**权衡**：负缓存引入最长 5s 的"故障恢复感知延迟"（上游已恢复但仍在冷却）——PRD §5 #4 已明确接受；若该延迟不可接受，唯一替代是有界回退，会回到 13.5s 放大器，**不选**。

### 2.4 错误语义与响应契约（R4/R14/R1/R18 + AC-A5/A9/A10/S6）

**设计决策：不采用 envelope，采用「下划线保留键 + 全系统单一组装点」。**（PRD §7.1 已裁；此处给出实现机制，ADR-002 记权衡。）

**保留键契约（全局冻结，本次仅这三个）**

| 保留键 | 类型 | 出现条件 | 语义 |
|--------|------|---------|------|
| `_errors` | `{"<code>": "<enum>"}` | **仅当存在失败码**时出现 | 枚举 = `FetchError.KINDS`：`upstream_timeout` / `upstream_error` / `cdp_unavailable`；键必为合法代码。**（SSE 帧侧的对应键 `errors` 值域额外含调度层的 `tick_budget_exceeded`，见 §2.5 C-5；该值属调度层而非上游故障，不入 `upstream_fail_total`）** |
| `_truncated` | `true` | **仅当请求码数 > 50** | 键不存在 ≠ false；≤50 时**两键均不存在** |
| `_dropped_count` | int | 与 `_truncated` **同现** | `= 请求码数 − 50` |

**值域三分（唯一判别式，消费方据此写代码）**

```
值 = 数据客体                          ⇒ 成功
值 = null  ∧  code ∉ _errors           ⇒ 无数据 / 无效码（既有语义不变）
值 = null  ∧  code ∈ _errors           ⇒ 取数失败（本次新增可辨识）
```

**单一组装点：`cache.build_batch_response(requested, results, errors, dropped=0)`**

- **入参**：请求码序（保序）、`{code: data}`、`{code: kind}`、被截断码数。
- **出参**：扁平映射，按上述契约挂保留键。**`_errors` 仅在非空时挂；`_truncated`/`_dropped_count` 仅在 `dropped>0` 时同现。** 总函数：永不出错、永不抛。
- **职责边界（v1.4 措辞更正）**：**管道层**（`_run_batch`/`_process_chunk`/`_handle_cached_batch`）返回二元组 `(results, errors)`；**批量 handler（`handle_cls_*`）本身**把它交给 `build_batch_response` 组装为 **dict 并返回该 dict**（`handle_cls_*(codes, deadline=None, dropped=0) -> dict`）；`server._handle_stock_batch` 只负责计算 `dropped` 并**作为参数**传给 handler（`dropped` 与端点形状无关），**不再二次组装**。截断发生在 HTTP 层、**不在 handler 内**（`_handle_cached_batch` 分块已保证不丢 2000 码，保留该性质）。SAD v1.3 写作"handler 返回 `(results, errors)`"与实现不符，此处以**代码为准**更正。
- `stream._refresh_pool` 消费时**必须跳过 `_` 前缀键**（一处遗漏即会把 `_errors` 当成一只股票塞进帧——这是本设计唯一的"陷阱点"，列为详设必测项）；**但 `_errors` 的值本身要保留**：`_refresh_pool` 把 handler 返回的 `_errors` 收进 `snapshot['_errors']`（**帧元数据位**，由 §2.4/§2.5 的帧契约以 `errors` 键对外），丢弃它会让帧无法区分"上游失败"与"暂无数据"（v1.4）。
- **组装防御规则（D-2 补记，内置于 `build_batch_response`）**：① `requested` 中以 `_` 开头的码**跳过**（代码键恒不含前导下划线 ⇒ 结构性避免与保留键同命名空间冲突）；② `errors[code]` 非空但 `results[code]` 非 `None`（**data+error 冲突**）→ `log.warning` 且**不收录** `_errors`（保证值域三分自洽：`code ∈ _errors ⇒ 值 null`）；③ **未知 `kind`**（∉ `FetchError.KINDS`）→ 归一为 `'upstream_error'` 并 `log.warning`（枚举封闭，不产生自由文本）。

**错误客体（单体 / 面板 / 工具端点，与批量严格互斥）**

- 单体与面板：`{"error": "<说明>"}`（或 `/market/margin` 的既有 `_error` 降级键），**响应体形状与 HTTP 状态码同为 200**。**同一响应内不得出现逐码值域**；反之批量响应**不得出现顶层 `error`**。
- HTTP 状态语义（AC-A5 五类情形，v1.5 裁决固化）：参数缺失 → 400 `{"error": ...}`；未知路径 → 404 文本；过载 → 503（主端口 `{"error":"server busy"}` 立即，流端口 503）；上游失败 → **200** + error 客体（批量端点：逐码 `null` + `_errors`）；CDP 不可用 → **200** + error 客体（`/stock/f10` 为逐码 `null` + `_errors`）。
- **降级状态码（v1.5 N1 裁决关闭：业务降级恒 200）**：**JSON 单体/面板/工具端点在"整体降级"时一律返回 HTTP 200 + 结构化 error 客体**，状态码**不由 payload 内容决定**。v1.4 曾按 `server._json_payload_has_data(payload)` 把"整体只是 error 标记"的 payload 降为 503——该函数**已删除**；`_send_json_shape`（`server.py`）现恒走 `self._send_json(payload, ...)` ⇒ **200**。落地面（与 PRD AC-A5 逐格一致，**无 ⚠️**）：
  | 端点类 | 实现状态码 | PRD AC-A5 |
  |--------|-----------|-----------|
  | 6 个批量 `/stock/*`（`shape=batch`，走 `_handle_stock_batch` → `_send_text`） | **200** + 逐码 `null` ∧ `_errors[code]` | 200 ✓ |
  | 4 个面板 `/finance/*` `/quotation/*` `/market/timeline` | **200** + `{"error":…}` | 200 ✓ |
  | `/cls/hotplate`（三分区全失败）/ `/cls/plate` | **200** + `{"error":…}`（hotplate 另含分区 error 客体） | 200 ✓ |
  | `/market/margin`（`_error` 降级） | **200** + `{latest:{…}, recent:[], _error:…}` | 200 ✓ |
  | `/ths/longhu`（`shape=text`，走 `_send_text`） | **200** + `{"error":…}` | 200 ✓ |
  | 5 个 RSS | **200** + 降级 feed | 200 ✓ |
  **裁决依据（N1，编排层）**：「原来旧版本怎么返回就怎么返回，因为已经有业务系统在使用旧版本接口」——把"业务失败 ⇒ 5xx"当作直觉会断裂按状态码分流的既有消费方（PRD §5 误解 #6）。**真实 503 仅保留两条路径**：① **连接准入拒绝**（`BoundedThreadPoolServer._reject_503`：主端口 `MAX_INFLIGHT`；`stream._serve_sse`：`MAX_STREAM_CONNS`）；② **`/healthz` degraded**（或 guard 失败体）。**`/healthz` 的 503 是健康端点自身的语义，不构成"业务端点可 503"的先例**。可见性由 `metrics`（`upstream_fail_total{kind}` / `negative_cache_size` / `healthz_stale_total`）与 `/healthz` 的 `status='degraded'` 承载，**不再由业务端点的状态码承载**。

**统一异常边界（修 R1/R18）**

在 `server.py` 增加单一装饰器/包装 `_guard(fn, *, shape)`，`shape ∈ {'batch','object','rss','text'}`：

- `batch`：异常 → 全码 `null` + `_errors[code]='upstream_error'`（**不抛、不断连**）；
- `object`：异常 → `{"error": str(exc)}`；
- `rss`：异常 → `generate_error_rss`（现状行为固化）；
- `text`：`/ths/longhu` → `{"error": ...}`。

**`_guard` 覆盖范围 = 全部 14 个 JSON 分支**（面板 4：`/finance/market` `/finance/timeline` `/quotation/market` `/market/timeline`；stock 6：`/stock/data` `/fundflow` `/timeline` `/f10` `/basic_info` `/announcement`；其余 4：`/cls/hotplate` `/cls/plate` `/ths/longhu` `/market/margin`）。修 P1-6：原三处写"13"为漏数，现统一为 14 并逐一列名；实现建议**由路由表派生 shape、不写死数字**，避免再次漏端点。

**`/cls/hotplate` 的 shape 例外（`object` 的聚合子类）**：它是单端点聚合三块（industry/concept/area），失败以**分区 error 客体**承载（`plate_<type>` = `{'error':...}`，分区可独立降级）；**仅当三块全失败**时顶层补 `error` 字段以满足 AC-A5 的单体口径。故 `_guard` 对其只需保证"任意异常不冒泡"，分区语义由 handler 内部维持（与 §2.3 D-4 一致）。

**统一调用顺序（修 P2-4 职责边界；v1.4 按实现回写为由路由表驱动）**
```
_handle_request
  → shape 由 _JSON_SHAPES 表派生（14 项，含 assert len == 14；_PANEL_HANDLERS /
    _STOCK_BATCH_HANDLERS / 其余 4 分支必须与表的路径集合逐一相等，import 期断言）
      batch  → _handle_stock_batch → _parse_stock_codes（归一化）→ 截断（算 dropped）
                   → _guard(handler(stock_codes, dropped=dropped), shape='batch',
                            requested=requested, dropped=dropped)   # 异常 → 全码 null + _errors
                   → _rekey_batch_response（canonical 键 → 客户端原拼写；纯改名）
                   → _send_text(200, …)                            # 批量恒 200
      object → _send_json_shape(path, fn)：_guard(shape='object')
                   → _send_json(payload) ⇒ 200 恒成立（v1.5 N1：不再按 payload 内容翻 503）
      text   → _guard(handle_ths_longhu, shape='text') → _send_text(200, …)   # 恒 200
      rss    → _serve_feed → _guard(shape='rss', rss_info, feed_url) → _send_text(200, …)
  → 业务降级（上游失败 / CDP 不可用）的可辨识性由 payload 内容承载
    （batch: _errors；object: error 客体），**状态码恒 200**（§2.4 N1）；
    503 只出现在准入拒绝（_reject_503 / 流端口）与 /healthz degraded
```
- 职责边界（v1.4 更正）：**管道层产出 `(results, errors)` → 批量 handler 用它调 `build_batch_response` 并返回组装好的 dict → `server._handle_stock_batch` 只做"入参归一化 + 截断 + `dropped` 注入 + 键回写 + 序列化/状态码"**（不重复组装）。
- 命名统一（修 P2-4）：防御取数统一为 `cdp_engine.page_data(page)`（§3 不再写 `cdp_page_data`）。
- **入参归一化（v1.4）**：`_parse_stock_codes` 把 `?code=` 的每个拼写经 `config.canonical_code` 折叠（`600519.SH` / `SH600519` / `sh600519` → `sh600519`）**在 `_MAX_BATCH_SIZE` 计数之前**去重（重拼写不能烧掉第二个名额），并**并行保留 `requested` 原拼写序列**；响应按 `requested` 键回写（§7.3#8）。非法码值**不是 400**，仍是该码的逐码 `null`（400 只给"缺 `?code=`"）。

**R18 防御访问**：新增 `cdp_engine.page_data(page)` 防御取数——`None`/非 dict/空 → 由调用方按 shape 产出 error 客体或 `cdp_unavailable`；删除对页面数据的一切"假定为 dict"的直接 `.pop/.get` 链。

**权衡**：`_errors` 会随响应体增大（最坏 50 码全失败 ≈ +1KB），对 RSS/JSON 客户端无影响；相比 envelope 的收益是**既有消费方零改动**（PRD 🟠 STABLE 只增不改的硬要求）。

### 2.5 并发模型（R5/R6 + AC-S2/A1/A2）

**C-1 组状态不可变化（把 R5 从"碰巧安全"变成"设计安全"）**

`SubscriptionGroup` 状态改造：

| 字段 | 现状 | 目标 | 理由 |
|------|------|------|------|
| `codes` | `set`（当前整体赋值，非原地变更） | `frozenset` | 类型即承诺：**不可变对象可被任意线程无锁遍历**；任何"想原地改"的后续改动会在代码评审/测试期暴露，而非生产期偶发 `RuntimeError` |
| `fields` | `list` | `tuple` | 同上（`_build_frame` 每帧遍历） |
| `conns` | `set` | 保留 `set` + `conns_lock`（连接是**可变性必要的**） | 生命周期事件驱动，频次低 |

`patch_group`/`create_group` 继续在 `_groups_lock` 下**整体替换** `g.codes`。

**C-2 锁层级与广播路径（锁序固定 groups → conns，无反向路径）**

```
_broadcast(snapshot):
  with _groups_lock: groups = list(_groups.values())        # 快照组列表，随即释放
  for g in groups:
      codes = g.codes                                        # frozenset，无锁读（C-1 保证）
      with g.conns_lock: conns = list(g.conns)               # 快照连接列表，随即释放
      if not conns: continue                                 # 僵尸组：不构建帧
      frame = _build_frame(snapshot, codes, g.fields)        # ★ 无锁路径：只读不可变对象
      for conn in conns: conn.q.put_nowait(frame)            # 队列自带锁，互不阻塞
```

要点：**帧构建（CPU 重）与入队（IO 轻）都不在 `_groups_lock` 下**，因此 PATCH（需 `_groups_lock`）与广播互不阻塞，`tick 间隔劣化 ≤20%`（AC-S2）由结构保证而非调优。
`sweep_idle_groups` 的 TOCTOU 双检（现状已有）保留，锁序仍为 groups → conns。

**C-2 补充（v1.4 按实现回写的三处收口）**
- **"先滤 `closed`，再腾位"**：`_broadcast` 取到连接的快照后**先过滤** `conn.closed`，只对**真实目标**做 `_reserve_for(frame.size)`。若先腾位再发现"没人收"，就会**白驱逐别组的真实帧**为一张无用帧腾位置（P2）。
- **`put` / `closed` 竞态双时序收口**：入队成功后**复检** `conn.closed`，若已关闭则立即 `_drain_conn_queue(conn)` 归还该帧字节；`_frame_acquire` **在 `put_nowait` 之前**执行（`refs ≥ 1` 先于帧可达），且"两次 `put` 都 `Full`"时 `_frame_release(frame)` 回滚 ⇒ 不变式恒为"未入队即不计费"。
- **SSE 响应头与连接生命周期**：`_serve_sse` 发 `Connection: close`（`finally` 里必关连接，不能对外承诺 keep-alive）+ `close_connection = True`（否则 `handle()` 会再次 `handle_one_request` 并在 `rfile.readline()` 上阻塞到 40s socket 超时，钉住 worker **与** `_inflight` 槽位，重连抖动下饿死管理请求）；`ConnectionResetError`/`BrokenPipeError`/`OSError` 与 `socket.timeout`（⊂ `OSError`）统一走 stalled 路径并计 `stream_slow_client_total`（**仅当队列非满**——满队列说明是"读得慢"而非"写阻塞"）。

**C-3 慢客户端隔离（AC-E7/A2）**
- 单连接队列 8 + 丢最旧保最新（现状保留）+ 全局字节预算（§2.2 R-2）。
- `wfile.write` 受 40s socket 超时约束；断连/超时 → `finally` 摘除连接并 `_release_conn()`（现状保留）。
- **摘除/销毁必排空队列并逐帧 `refs−=1`**（`_drain_conn_queue`，见 §4.2「生命周期收口」）——否则残留帧字节永久占用预算、后续 tick 无条件丢帧（P1-N2②）；`None` 唤醒哨兵不计费（P1-N2③）。
- 新增：连接被摘除时若其队列非满（说明是"写阻塞超时"而非"读取慢"），计入 `stream_slow_client_total` 指标，供 S10 观测。

**C-4 管理请求 IO（R6）**：见 §2.2 R-5。

**C-5 SSE 帧契约（v1.4 新增章节；对外契约，🟠 STABLE「只增」）**

`_build_frame(snapshot, codes, fields) -> str | None`（**仅 `codes` 为空时返回 `None`**；`codes` 为 `frozenset`、`fields` 为 `tuple` ⇒ **无锁构建**）：

```jsonc
{ "ts": <epoch_ms>,
  "codes_total": <int>,          // ★ 该组订阅码总数（= len(codes)）
  "fields": ["quote","fundflow","timeline"],   // ★ 订阅字段集（请求的形状）
  "items": { "<code>": { "<field>": <data|null> } },   // ★ 覆盖**全部订阅码**，缺数据为 null
  "missing": ["<code>", ...],    // ★ 所有请求字段均为 null 的码（已排序）
  "missing_count": <int>,
  "errors": { "<code>": "<kind>" },   // 仅非空时出现（kind ∈ KINDS ∪ {'tick_budget_exceeded'}）
  "stale": ["<code>", ...],      // 仅非空时出现（P1-4：本 tick 未刷未命中缓存，值来自上一 tick）
  "stale_count": <int>           // 与 stale 同现
}
```

**三条可判别的语义（消费方据此写代码）**：
1. `code ∈ items` **恒成立**（对全部订阅码），故"缺席"不再是信号——**"有没有数据"看 `missing`，"是不是旧值"看 `stale`，"是不是上游失败"看 `errors`**。
2. **`missing` 与 `stale` 互斥**（一个码只有当**确实存在过非空旧值**时才可能进 `stale`；进了 `stale` 就说明它有数据 ⇒ 不可能同时 `missing`）。
3. **`errors` 与 `missing` 不正交**：一个码可以"有数据但某字段失败"（warm 码之一相失败）⇒ 同时出现在 `items`（有值）与 `errors`（有失败字段），但不进 `missing`。`errors` 的 kind 值域 = `FetchError.KINDS` ∪ `{'tick_budget_exceeded'}`（后者是**调度层**错误——该切片本轮没轮到/已过 tick 预算，**不是**上游故障，故不入 `upstream_fail_total`）。

**收缩行为**：`payload['errors']` / `payload['stale']` 只保留 `code in items` 的条目（防御性过滤，防止 `_` 前缀或已移除码泄漏进帧）；`items` 的键序为 `sorted(codes)`、字段序为 `fields` 顺序 ⇒ **帧字节确定**（便于测试断言与 `stream_frame_bytes` 估算）。

**C-5 不选其他**：不用"缺席即无数据"的隐式契约（C2 分片下 200 码组每帧只 7 码有值，客户端无法区分"未轮到/无数据/上游故障"三个完全不同的处置——这是 P1-4 的根因）；不用增量 diff 帧（PRD §6 W 级不做）；不把 `stale` 做成布尔（客户端需要**具体哪些码**是旧值，才能对旧值降级展示）。

**§2.5 不选其他**：不引入 `queue.Queue` 之外的自定义无锁环形缓冲——标准库队列已满足"有界 + 并发安全 + 丢弃策略"，自研只会引入新的锁序风险。

### 2.6 可观测性（R2/R8/R19 + AC-S8/S10）

**决策：新增 `china_finance_rss/metrics.py`（纯标准库、单锁叶子模块），而不是把计数器散落到各模块的全局变量。**（设计期估约 60 行；**v1.4 实测 185 行**——多出的是零值注册表、形状守卫、锁外深克隆与告警去重，仍不引任何依赖。）

- 形态：`incr(name, n=1, key=None)` / `set_gauge(name, value, key=None)` / `snapshot() -> dict` / `reset()`（**测试辅助**）；`key` 是 `cache_entries{url,feed,…}` 与 `upstream_fail_total{kind}` **标签记法的唯一落地载体**（**逐标签写入**，避免多模块写点以整体 dict 覆盖互相清空；裁决 #4）；内部单 `threading.Lock`（写频低：#tick≈1/8s、#503 与 #丢弃帧为事件级，无热点竞争）。
- **`snapshot()` 语义（v1.4 补实现口径）**：① **零值恒定发布**——`_KNOWN` 注册表与 `_DEFAULTS` 表在 import 期以 `assert set(_DEFAULTS) == _KNOWN` 互锁，"从未发生"与"从未插桩"因此可区分（`stream_frame_dropped_total` 读 0 而不是缺键）；`_DEFAULTS` 是**只读回落元数据**，绝不写进 `_counters`/`_gauges`，故某指标的首次 `incr` 仍固定其形状（int vs 标签 dict）。② **锁内浅拷贝 + 锁外深拷贝**——`_lock` 只覆盖注册表浅拷贝（dict `.copy()`、list `list(v)`），**大容器/大列表的深克隆在锁外**，使 `/healthz` 轮询不会阻塞业务写入一个完整克隆的时长；`_clone` 用标准库实现（不 import `copy`，守 allowlist）。③ **形状守卫**——标签计数器/仪表不可被无标签整写覆盖，无标签仪表不可长出标签 dict（`_LABELED_GAUGES` 显式登记，因为 gauge 的 dict 值本身合法，如 `cdp_restart_window`）；不匹配 ⇒ `_warn_once` + **忽略**（观测永不破坏业务）。
- **`cdp_restart_window` 恒在**：`cdp_engine` **模块加载即** `_publish_window()` 发布初始 `idle` 快照，故 `metrics.snapshot()` 在首次重启前也含该键（否则消费方要处理"键缺失"与"值 idle"两种同义状态）。
- 计分板（对齐 AC-S10 逐项）：

| 指标 | 来源 | 对应 |
|------|------|------|
| `http_503_total` | **3 个计数点（v1.5；N1 关闭后由 4 收敛为 3）**：① `BoundedThreadPoolServer._reject_503`（主端口准入拒绝，`server.py`）；② `stream._serve_sse` 连接上限 503（流端口准入拒绝，`stream.py`）；③ `/healthz` 的 503（`status=degraded` 或 guard 失败体）。**业务端点降级不产生 503**（§2.4 N1） | AC-S10 / S5 |
| `stream_frame_dropped_total` / `stream_queue_bytes` | `_broadcast`（**distinct 帧去重计费**，§4.2） | AC-S10 / E7 |
| `stream_frame_distinct` / `stream_frame_peak_bytes` | `_broadcast`（`_frame_acquire` 内 0→1 时更新峰值） | AC-S10 / E7 |
| `stream_tick_duration_ms` / `stream_tick_slip_total` | `_push_once`（耗时 > tick ⇒ slip；耗时 > 0.8×tick ⇒ degraded） | AC-S10 / R8 / E5 |
| `stream_refresh_lag_ticks` / `stream_tick_degraded_total` | `_refresh_pool`（分片轮转，§2.2 R-6；**空池时由 `_push_once` 置 0**） | AC-S10 / AR-1 |
| `stream_slow_client_total` | `_serve_sse` 的 stalled 路径（**仅当队列非满**） | AC-S10 / E7 |
| `cache_entries{url,feed,quote,fundflow,timeline,f10,announcement,longhu,sector}` | 各缓存写入点（URL/feed 缓存发布在**业务锁释放后**） | AC-S10 / E6 |
| `cache_hit_ratio`（**设计目标观测项，非 AC**，Q1） | `cache._cache_put` / 各正缓存命中路径（由 cache 本地 `_cache_stats{hit,miss}` 派生发布，**不在请求热路径持有 `_cache_lock` 时发布**；裁决 #5 / S1-4） | Q1 |
| `negative_cache_size` / `upstream_fail_total{kind}` | `cache.fetch_json`（`_record_failure`/`_clear_negative`，**锁释放后**发布）；`upstream_fail_total` 另由 `stock_api._fetch_rest_json`/`_raise_cdp_unavailable`、`market_api.fetch_margin` 补充非网络失败 | AC-S10 / S3 |
| `upstream_fetch_total{domain}`（**每域上游取数计数**，D-6 补列） | 各域取数点（回源 round-trip 计数；**每个逻辑取数恰好 +1**，CDP 回退路径不重复计） | AR-6 / Q3⑤（P6c 核对"上游负载增幅 ≤ 可接受阈值"） |
| `code_cooldown_list`（**可枚举清单**，非计数，修 P1-5/P2-6） | 共享失败状态层（§2.3 D-6）；gauge 发布**至多每 5s 一次**（滞后 ≤5s 对 120s 冷却无影响） | AC-S10 / S6 |
| `cdp_restart_window`（`idle`/`restarting`/`unavailable` + 上次窗口起止） | `cdp_engine`（模块加载即发布初始 `idle`） | AC-S10 / S4 / R19 |
| `healthz_stale_total` / `healthz_inflight` | `build_health_payload`（有界准入，见下） | AC-S8 / S10 |

**healthz 改造（AC-S8，修 P1-3）**
- `/healthz`（`check=0`）：**零上游调用**，只读 policy + metrics + `cdp_restart_window` 快照 → 毫秒级。
- `/healthz?check=1`：提交到**专用执行器** `_health_executor = ThreadPoolExecutor(max_workers=5)`（与主池物理隔离），`as_completed(timeout=10)`；单源超 3s 即判 `timeout`；整体超 10s 返回已收集部分并置 `status='degraded'`。
- **有界准入（替换不可达的"执行器忙"分支）**：`ThreadPoolExecutor.submit()` 的工作队列**无界且永不拒绝**（除 shutdown），故"执行器忙 → stale"是**死代码**。改为显式准入：
  ```
  if not _health_sem.acquire(blocking=False):          # _health_sem = BoundedSemaphore(MAX_HEALTH_INFLIGHT)
      healthz_stale_total += 1
      return 上次快照 + {"stale": true}                  # 可达、可测
  # ★ 准入位的释放由 _HealthBatch 完成（v1.4 更正，见下）——不是 finally 立即释放
  ```
  取 `MAX_HEALTH_INFLIGHT = 5`（= 执行器 worker 数）：并发 check 任务在飞数被信号量钉死，执行器内部队列**从不堆积**（提交前已准入）。`healthz_inflight` gauge 暴露，测试可注入 >5 并发慢 check 触发 stale 路径（AC-S8/S10 可断言）。
- **准入位的生命周期（v1.4 更正：`_HealthBatch`）**：v1.4 前的写法是 `try/finally: release`，**错**——`finally` 在**轮询循环返回时**就释放，而本轮 5 个 future 可能仍在飞。此时 `healthz_inflight` 立刻归 0，但执行器队列里已堆着后续批次的 20 个任务 ⇒ "准入"形同虚设（P1-1）。正确口径：
  - 准入位由 `_HealthBatch(len(ROUTES))` 持有：每个 future 挂 `add_done_callback(batch.task_done)`，**只剩 0 个**时才 `_release_health_slot()`（`_done` 闩锁保证**恰好释放一次**）；
  - 异常路径（执行器创建失败 / `BaseException` 逃出）用 `batch.settle()` **立即释放**同一闩锁（幂等，不会双释放——`BoundedSemaphore` 超放会抛 `ValueError`，由类型兜底）；
  - **可断言上界**：在飞任务 ≤ `MAX_HEALTH_INFLIGHT × len(ROUTES) = 25`，专用执行器工作队列 ≤ 20；
  - 准入失败路径**不刷新** `_health_last_snapshot`（否则 stale 快照会自我覆盖，`stale:true` 变成长期假状态）。
- 响应字段（**只增不改**；原"不改既有 `feeds[]` 字段与含义"**删除**，见 Q2）——**精确 schema**：
  ```jsonc
  {
    // ── 既有字段：必须保留（🟠 STABLE 只增不改；server.py:497-498 现状） ──
    "status": "ok" | "degraded",
    "cache_ttl": <int>,                  // 既有；ADR-001：保留字段名与含义，取值改读 cache_policy('feed')['ttl']（盘中 30 / 非盘中 180）
    "request_timeout": <int>,            // 既有；REQUEST_TIMEOUT
    "feeds": [                           // 既有；name/path/url/status 恒在，?check=1 时附 items / error
      { "name": <str>, "path": <str>, "url": <str>, "status": <str>,
        "items": <int>, "error": <str> } // items / error 仅 check=1 且对应情形出现
    ],
    // ── 本次新增（只增） ──
    "stale":   true,                     // 仅准入失败时出现（只增）
    "metrics": { "<name>": <number|object|array>, ... },   // metrics.snapshot()
    "policy":  { "<domain>": {"tier":"L1","ttl":8,"pool_refresh":8,"pool_max":2000,"cache_max":2000}, ... },
    "cdp":     { "state":"idle|restarting|unavailable", "window_start":<epoch|null>, "window_end":<epoch|null> }
  }
  ```
  > 修 P2-N1：上一版"精确 schema"漏列既有 `feeds[]` / `cache_ttl` / `request_timeout`，与 🟠 STABLE「只增不改」及 ADR-001「`cache_ttl` 保留字段名与含义」冲突。**既有键一个不少**，仅在其上叠加 `stale`/`metrics`/`policy`/`cdp`；`feeds[].status` 的取值变更单独按 Q2 走编排层批准。
- **契约口径（Q2）**：`feeds[].status` 的取值由 `requires_chrome_cdp`/标注漂移改为目标值属「**改既有字段取值**」（≠"只增不改"），须编排层批准并记入变更日志（见 §7.1 Q2）。

**tick 观测与预算（R8；v1.4 按实现回写）**
- `push_loop` 的迭代体抽为 `_push_once(t0)`（**不变量**：空池路径的 `stream_refresh_lag_ticks=0` 必须在 `_push_once` 里，因为 `_refresh_pool` 在空池时根本不被调用——gauge 曾因此永久停在最后一个 C2 值）。
- `push_loop` 用 `t0 = time()` 包裹刷新+广播，`tick = tick_interval()` **只算一次**并下传给 `_refresh_pool`（C1/C2 门限与调度节拍同源）。
- **节拍 = 整 tick 网格（v1.4 更正）**：`delay = t0 + k×tick − now`，`k = floor((now − t0)/tick) + 1 ≥ 1`。即"本轮刚好装进一个 tick"⇒ sleep 到 `t0+tick`；"本轮超了一个 tick" ⇒ **整 tick 滑移到下一个网格点**。**旧规则**（超预算后 `floor` 到 `0.25×tick`）会在一次 >1 tick 的长轮之后紧跟一个 2s 的短间隔帧 ⇒ **帧间隔直方图双峰**（一个 12–17s 停顿 + 一次 2s 连发）。网格化后帧间隔**永短于一个 tick**，不可能出现短促连发。
- **异常退避（v1.4）**：`_push_once` 抛异常时，连续失败数 `consecutive` 决定退避跨度 `min(2^(consecutive−1), 8)` 个 tick，并与网格取 max。**旧行为是固定 `sleep(1)`**——一个反复失败的路由会把循环降级成 ~1s 自旋（每个间隔重跑至多 `tick` 次），在最糟的时刻放大上游压力。
- **degraded 与 slip 只统计"真的跑过的轮"**：耗时 > `0.8×tick` ⇒ `stream_tick_degraded_total += 1`；耗时 ≥ `tick` ⇒ `stream_tick_slip_total += 1`。空池轮耗时 ≈0ms，两个计数都不增长（它们是刷新超预算的属性，不是空转的属性）。

---

## 3. 模块变更矩阵

风险等级：**H** 高（改核心机制，必须白盒+并发测试）/ **M** 中（改行为，需回归）/ **L** 低（新增/文档）。

| 模块 | 改什么 | 为什么（根因） | AC | 风险 |
|------|--------|---------------|----|------|
| **config.py** | 新增 `cache_policy()` + `DOMAIN_MATRIX`（含 `longhu` 域、`cache_max`、plate stagger 派生；`plate`/`margin` 的 `cache_max` = `'n/a'`）+ **内部名 `_DOMAIN_ENCODING`（D-5）**；删除/改由 policy 承接的 TTL 与 `*_REFRESH` 常量；**`CACHE_TTL` 逐消费者迁移后删除**（cache.py 默认、`server._get_or_fetch_feed`；**`utils.py:12` 为未使用 import**，Q3）；**新增代码归一化唯一权威 `canonical_code(code) -> str\|None`（v1.4）** + `VALID_STOCK_CODE`/`_DOTTED_STOCK_CODE`（规范形 = 小写交易所前缀 `sh600519`；接受 `SH600519`/`600519.SH`；非法 ⇒ `None`）+ **帧尺寸单一来源 `stream_frame_bytes(codes, fields)`**（`STREAM_FIELDS_PER_FRAME=3`/`STREAM_FRAME_BYTES_PER_FIELD=23KB`）；新增 env：`MAX_INFLIGHT`/`MAX_GROUPS`/`MGMT_BODY_TIMEOUT`/`STREAM_QUEUE_BYTES_BUDGET`(默认 128MB)/`NEG_TTL`/`PROBE_TIMEOUT`/`MAX_HEALTH_INFLIGHT`/**`STREAM_PING_INTERVAL`(默认 20，原硬编码，D-4)**/**`LISTEN_BACKLOG`(默认 128，TCP accept backlog，默认 5 会在突发连接下内核丢 SYN ⇒ ~1s RTO 尾巴)**/**`CDP_RESTART_THROTTLE`(默认 15)**/**`STREAM_GROUP_IDLE_TTL`(默认 300)**/**`TRADING_HOLIDAYS`(空，逗号分隔 `YYYY-MM-DD`)**；`_trading_tiers()` 保留为唯一时间源，`_is_trading_hours(now=None)` 增补 `now` 注入点 + 节假日判定（配置的假日按非交易时段处理） | RC-1（R16/R12/D1-D5）、R6/R17、P1-6 | A3/A4/E6/E9/S3/S7 | **H** |
| **cache.py** | `fetch_json` **五段式**（正缓存 → **端到端 deadline 闸门（v1.4，第 5 位形参 `deadline`；闸门在正缓存之后）** → 负缓存门禁 → leader 单次尝试 → follower 读状态）+ **半开探测 `_probe_budget` 阶梯（2→4→5，`_PROBE_BUDGET_CAP=5.0` 封顶，v1.5）** + 负缓存（URL 级，4 键含 `first_at`）+ `FetchError(kind)` + 删除 fall-through 三段路径 + **gap 分支 fail-closed 兜底（D-1）**；新增 `encoding='utf-8'` 形参（修 P1-4）；URL 缓存改 `last_access` 淘汰 + 双触发清扫；**feed 缓存机制落点 = `feed_cache_get`/`feed_cache_put`**（LRU/双触发清扫/淘汰均在此层，裁决 #3）；新增 `build_batch_response()`（纯函数，内置 `_` 前缀跳过 / data+error 冲突 / 未知 kind 归一，D-2；**返回组装好的 dict**）；允许 import 新增 `socket`（D-3）；**metrics 一律在业务锁释放后发布**（`_publish_url_stats`/`_record_failure`/`_clear_negative`），命中路径（段①/③双检/④）**统一计 hit**（只计段①会把 `cache_hit_ratio` 系统性低估）；`import json` 已删。**帧计费（`_Frame`/refs/`stream_queue_bytes`）不得落在此模块**——它属 stream 层，cache.py 只做纯缓存/契约，守 `layerIsolation`（修 P2-N6） | RC-2（R9）、R11/R3、RC-3（R4/R14）、P1-2/P1-4/P1-5 | S3/S6/A9/A10/E6/E9 | **H** |
| **server.py** | 新增 `_guard(shape)` 统一异常边界，覆盖**全部 14 个** JSON 路由分支（**shape 由 `_JSON_SHAPES` 路由表派生**，含 `assert len == 14` 与"分派集合 == 表"的 import 期断言；逐一列名，§2.4）；`_handle_stock_batch` 做**入参归一化（`_parse_stock_codes` → `config.canonical_code`）+ 截断 + `dropped` 注入 + 键回写（`_rekey_batch_response`）**；`build_health_payload` 专用执行器 + **信号量有界准入（替换死代码 stale）+ `_HealthBatch` 准入位生命周期** + 零上游快路径；503 计数接入 metrics（**3 个计数点，v1.5**）；`MAX_INFLIGHT`/`MGMT` 常量接入；`_cache_age()` 改读 policy（未登记路径回落 `_DEFAULT_AGE_DOMAIN='f10'` ⇒ 恒 300，与现状逐字等价）；`/ths/longhu` 改走 `fetch_json`（L4，`encoding='gbk'`，**2 URL 并发 ≤3**）；**feed TTL 派生 + 防击穿调用 `cache.feed_cache_get/put`**（miss → per-path lock → **二次 `feed_cache_get` 双检** → fetch → `feed_cache_put`；`ttl` 在**二次仍 miss 之后**才求值；**机制归 cache 层**，Q3③/裁决 #3）+ `CACHE_TTL` 消费者迁移；`/cls/hotplate` 保持分区 error 客体（**全分区失败时顶层补 `error`**）；**`BoundedThreadPoolServer.__init__(..., max_inflight=None)`（v1.4：流端口显式传 110，否则主端口默认 40 会掩盖 100 连接上限）**；**（v1.5 N1 关闭）`_json_payload_has_data` 已删——`_send_json_shape` 恒 200 + error 客体，业务降级不产生 503（§2.4）**；`request_queue_size = LISTEN_BACKLOG` | RC-3（R1/R4）、RC-4（R2）、D4/D5、R15、P1-3/P1-4/P1-6/P2-3② | S1/S8/S10/A5/A9/A8/E9/E6 | **H** |
| **stream.py** | `codes→frozenset`、`fields→tuple`；`_build_frame(snapshot, codes, fields)` **签名变更 + 帧契约扩元数据**（`codes_total`/`fields`/`missing`/`missing_count`/`errors`/`stale`/`stale_count`，**items 覆盖全部订阅码**，仅空 `codes` 返回 `None`，C-5）；`_broadcast` 锁序与无锁帧构建 + **先滤 `closed` 再腾位** + put/closed 竞态收口；**distinct 帧引用计数 + 队列字节预算 + 丢弃计数**（P0-1）+ **`_frame_bytes_lock` 保护 `refs` 读改写、`_drain_conn_queue` 在摘除/销毁路径逐帧归还字节、`None` 哨兵不计费**（P1-N2）；**`_refresh_pool(codes, now=None, fields=None, tick=None, deadline=None)`** 改「**按订阅字段并集刷新的分片轮转**」（R-6/AR-1；`coverage_codes` 盘中 **1/2/3 域 = 23/11/7**，v1.4；`tick`/`deadline` 单次计算下传 + `tick_budget_exceeded`）；**新增 `_subscribed_fields`/`_active_targets`（codes+fields 同锁读）**、**`_carry_forward`/`_last_known`（last-known 结转 + `stale`）**、**`_valid_fields` fail-closed（显式非法字段 → 400，不再静默放宽为全字段）**、**`config.canonical_code` 归一化（`create_group`/`patch_group`，含非法码 400）**、**`_capacity_meta`（201/200 响应补容量元数据）**、**`_require_code_list`（非 list → 400）**；`_read_json_body` 5s 读预算；**`_tick_sleep_seconds` 整 tick 网格滑移 + `push_loop` 异常退避（1/2/4…≤8 tick）**；`_refresh_pool` 跳过 `_` 前缀键（但**保留** `_errors` 到 `snapshot['_errors']`）；`create_group` 校验 `MAX_GROUPS`（超限 400）+ **单帧余量准入**（v1.4）；`_serve_sse` 发 `Connection: close` + `close_connection=True`；`make_stream_server` 传 `max_inflight=MAX_STREAM_CONNS+10=110` | R5、R6、R7、R8、R14 陷阱点、P0-1/P1-1/P1-N1/P1-N2/P1-4/P1-6 | S2/S7/S10/E5/E7/A1/A2/A3/A7 | **H** |
| **stock_api.py** | 全部取数器签名加 `deadline`/`ttl` 并传递到 `fetch_json`；删除 `_MAX_CACHE_AGE`，按 `cache_policy` 注入 `ttl`/`pool_refresh`/`pool_max`/`cache_max`；**池淘汰不再 `cache.pop`，端点缓存独立 LRU**（P1-1）；`fetch_cls_f10` 失败 `raise FetchError('cdp_unavailable')`；`_run_batch` 返回 `(results, errors)`；**新增共享失败状态层 `_fail_ledger`**（码级 120s 冷却，**4 元条目** `[fail_count, cooldown_until, kind, last_fail_ts]`，批量与 prefetch 共用，P1-5），删除 4 个 prefetch 的局部 `fail_blacklist`；**新增 `_LOCAL_BUDGET` 本地预算标记（对外翻译为 `upstream_timeout`、**绝不入冷却账**，v1.4）** + `_call_fetcher` 的"仅调用帧 `TypeError` 才降级"；`_process_chunk` 全链 **`canonical_code` 归一化 + 结果回写原拼写**；`cached_batch(domain, codes)` 只读终点缓存（供 stream 分片）；`code_cooldown_list` 导出 + 发布节流；`fetch_cls_announcement` 裸 `ttl=15` 删除（Q5）；**依赖新增 `cdp_engine.page_data`（同层，无环）** | RC-1（R12）、RC-2（R13/R14）、RC-4、P1-1/P1-5/P1-6 | A3/A6/A7/A10/E2/E9/S6/S7 | **H** |
| **market_api.py** | TTL 改 policy（`margin` 域）；失败降级体保持既有 `_error` 语义（单体客体，**取值收敛为枚举 kind**），补 `FetchError` 分类参与 metrics + **防重复计数约定**（`fetch_json` 已计的失败不再二次计） | R16、RC-3 | S1/S10 | **M** |
| **cdp_engine.py** | 新增 `page_data(page)` 防御取数（总函数；None/非 dict/空 dict → `None`，**无键级回退**）；`cdp_restart_window` 状态机（`_mark_*` 唯一写者 + 读只经 `restart_window_snapshot()` + **`full_chrome_restart` 的 `finally` 兜底必达终态**）+ 模块加载即发布初始 `idle`；`watchdog_restart_skip_reason()`（盘中避让 + 节流集中判断）；`cdp_ready()`；**`_last_data` 老化口径（时钟缺失 = 陈旧）** + 四表同步淘汰；**`navigate_stock` 有界导航锁（`_acquire_navigate_lock`）+ `canonical_code` 归一化比对**；页面求值超时预算对齐 §2.3 | RC-3（R18）、R19、R20、P1-3 | S1/S4/S9/S10 | **M** |
| **server.py（CDP 守护）** | **`_cdp_memory_watchdog`（含 `_is_trading_hours` 避让判断）在 `server.py:881`，非 cdp_engine.py**（修 P2-2）；守护重启交易时段避让（`_is_trading_hours()` 为真则跳过本轮，顺延到下一周期） | R19/R20 | S4/S9 | **M** |
| **metrics.py（新增）** | 计数/仪表 + `snapshot()`；被 server/stream/cache/stock_api/market_api/cdp_engine 引用。**v1.4 实测口径**：`_KNOWN` 注册表（19 名）+ `_DEFAULTS` 零值表（import 期 `assert` 互锁）、`_LABELED_GAUGES` 形状守卫、`snapshot()` 零值恒定 + 锁内浅拷贝/锁外深拷贝、`reset()`（测试）。**规模已从设计期的 ~60 行增至 185 行**（形状守卫/深克隆/告警去重），仍为零依赖叶子模块 | RC-4（观测）、AC-S10 | S10 | **L** |
| **tests/** | **改写**存量：`test_fetch_json_leader_failure_does_not_stampede`（新语义：leader 失败 → follower 读负缓存、不触网、不重入选举；断言改为 `err=8`（8 个并发 caller 全部失败：leader 落负缓存后，7 个 follower 读负缓存直接 raise、不触网）、`max_active=1`、冷却窗口内 <1ms 失败）。**新增**：policy 一致性白盒、负缓存/两模式故障注入、半开探测恢复、保留键契约矩阵、并发 PATCH 广播、healthz 有界准入（stale 可达）、distinct 帧字节计费、共享失败冷却（批量+prefetch）、longhu GBK 解码 | 上述机制的验证载体 | 全部 | **M** |

**依赖方向（不得成环）**：`config`（无依赖）← `metrics` ← `cache` ← `stock_api`/`market_api`/`stream` ← `server`；`cdp_engine` 仅依赖 config/metrics。`cache` **禁止** import `server`/`stream`/`stock_api`（`build_batch_response` 保持纯函数）。`stream` 继续以函数内 `from .server import BoundedThreadPoolServer` 的**延迟 import** 打破 `server ↔ stream` 环（现状保留）。

**同层依赖登记（v1.4 补，REV-DES-10）**：`stock_api → cdp_engine`（经 `from .cdp_engine import page_data`）是**同层**依赖（两者都在 Layer 1），**无环**：`cdp_engine` 的 `forbiddenImports` 已含 `stock_api`，反向不可能成立。该边也必须写进 `tech-stack.json`，否则 `check-arch-compliance.sh` 的层级图与 §3 不一致。依赖全图（同层边以 ⇢ 标注）：
```
config ‖ metrics                     ← Layer 0 叶子，互不依赖
  ↑
cache                                ← Layer 0.5（纯缓存/契约）
  ↑
stock_api ⇢ cdp_engine               ← Layer 1（stock_api 经 page_data 单向引用 cdp_engine）
market_api                           ← Layer 1
stream → stock_api                   ← Layer 1（cached_batch / BATCH_MAX_WORKERS / _prefetch_slice / _prefetch_advance）
  ↑
server                               ← Layer 2（main() 内延迟 import stream 破环）
```

### 3.1 明确不改（架构边界）

| 不改项 | 理由 |
|--------|------|
| 技术栈：不引入任何第三方库/框架/异步框架 | PRD §6 硬约束 |
| 外部存储：不加 DB/Redis；全部状态在内存 | 同上 |
| 路由表与 API 签名：不增删路径、不改方法（**例外 1（P2-7）**：`POST /stream/subscriptions` 新增 `MAX_GROUPS=200` 上限 → 超限返回 400，属新增失败模式，须编排层登记变更日志，见 §7.1） | 🟠 STABLE 端锁定 |
| **（v1.4 例外 2）`POST`/`PATCH /stream/subscriptions` 入参校验加严**：`codes`/`add`/`remove` **非数组 → 400**；请求体**非 JSON 对象 → 400**；**显式未知字段 → 400**（不再静默放宽为全字段）；**非法股票代码 → 400**（`config.canonical_code → None`，归一化后去重 ⇒ 同一股票的多种拼写只占一个名额、只产生一次上游取数）。均为**新增失败模式**，须编排层登记 | 同上（S2-4 fail-closed / P1-6 归一化） |
| **（v1.4 例外 3）SSE 帧新增元数据键**：`codes_total`/`fields`/`missing`/`missing_count`/`errors`/`stale`/`stale_count`，且 `items` 由"缺数据即缺席"改为"**覆盖全部订阅码、缺数据为 `null`**"（C-5） | 🟠 STABLE「只增」范围内：既有键 `ts`/`items` 的**类型与含义不变**，新增键与"全码在位"是**语义补全**（原缺席语义无法表达"未轮到"）。**但 `items` 由稀疏变稠密会使帧字节增大**，客户端若按"键存在即数据"的旧假设遍历需适配 ⇒ 列入契约同步项 |
| **（v1.4 例外 4 → v1.5 关闭）JSON 单体/面板/工具端点的降级状态码** | **N1 裁决关闭（§7.1 N1 / §9.5）**：业务降级**维持 200 + error 客体**，与旧版本契约及 PRD AC-A5 一致 ⇒ **不构成"改既有状态码"，不再是本节的例外**。真实 503 仅准入拒绝与 `/healthz`（§2.4） |
| 既有字段类型与含义：尤其 `null = 无数据` | 只增不改（**例外**：`feeds[].status` 取值变更，须编排层批准，见 §7.1 Q2；**已在代码落地**，`API.md` 待同步） |
| 断线重连并续帧语义（AC-S11）：同一 sid 在 1 tick 内重连 → 下一 tick 收完整快照帧；组空闲 300s 回收 | **不改动**；依赖既有 `_register_conn` + `push_loop` 全量快照 + `STREAM_GROUP_IDLE_TTL`（断言依据见 §8） |
| SSE 全量快照帧机制、增量 diff 帧（W 级不做） | PRD §6 |
| 前端/UI：无 | PRD §6 |
| 鉴权/多租户：不做 | PRD §6 |
| `handle_* 返回 dict 不抛`、分锁不用全局大锁、取数走 `fetch_json`、配置走 config+env、延迟 import、tests 全限定 patch | 项目既有约定（仅"取数走 fetch_json"由 R15 补全，非改变） |

---

## 4. 非功能性预算（NFR）

### 4.1 延迟预算分解（对齐 AC-E1/E2/E3/S7）

| 路径 | 端到端目标 | 预算分解（服务端 handler） | 备注 |
|------|-----------|--------------------------|------|
| 本地缓存命中 | P95 ≤5ms / P99 ≤15ms | policy 查表 <0.01ms + 逐码 dict 命中 + `json.dumps` 50 码 ≈ 1.5ms + socket 写 | 主要成本是序列化，非查表 |
| 上游命中（REST 回源） | P95 ≤1.2s / P99 ≤3s | 连接+首字节 ≤0.4s + 读 ≤0.8s；硬上限 `REQUEST_TIMEOUT=10s`；**批路径多码并行（≤8）**，故 P95 由单码 RTT 主导而非 50×RTT | 任何单请求 ≤15s（AC-S7）；**仅对无失败历史的 URL** |
| 故障快速路径（负缓存命中） | ≤1ms | 负缓存未过期 → 直接 `raise FetchError`，不触网 | AC-S3 模式 A/B |
| 故障半开探测 | **高密度 P95 ≤5s / 低密度 ≤10s** | `_probe_budget(fail_count)` = 2→4→**5 封顶**（`_PROBE_BUDGET_CAP=5.0`）；持续黑洞稳态 = `5s 探测 + 5s NEG_TTL` = 10s 周期，慢占比 ≈50% ⇒ 高密度 P95 ≈5s、低密度退化为周期上界 ≈10s；**+ `_HISTORY_AGE=600s` 老化**每窗至多放行 1 次 10s 全预算探测（稀有事件，不改分档 P95） | AC-S3 模式 B（v1.5 重标；单请求 ≤15s；**6–10s"慢而未死"上游恢复延迟 ≤600s，见 §2.3 D-1 权衡**；P6c 校准，Q6） |
| 端到端 budget 耗尽（本地） | ≤1ms | `fetch_json(deadline=)` 正缓存后判超期 / `_LOCAL_BUDGET` ⇒ 不触网、不记冷却 | AC-E2 / P1-1 |
| CDP 命中 | P95 ≤3s / P99 ≤5s | `navigate_stock` ≤2-3s（含 `_navigate_lock` 公平排队等待，上限由 deadline 约束）+ `evaluate_fetch` ≤2s | 面板端点走 `get_data()` 为纯内存读，≈本地命中 |
| `/cls/hotplate` | 跟随"上游命中" | **现状 3 次串行 fetch_json（最坏 30s）→ 改为 ≤3 并发**（`_fetch_concurrent` + 共享 `_fanout_executor`，统一 `_FANOUT_WAIT_BUDGET=REQUEST_TIMEOUT` 兜底；超期 spec 被 `cancel()` 并降级 `upstream_timeout`），P95 = max 而非 sum（**v1.4：已落地**） | 本次顺带修（同 R13 家族；AC 归属 = **E2**，非 S7） |
| `/healthz?check=1` | ≤10s | 5 源并发（专用 5 worker），单源 ≤3s | AC-S8 |
| SSE 单 tick | ≤1s（AC-E5） | 200 码 ×3 字段帧构建 ≈10-30ms + 100 次 `put_nowait` ≈ 1ms | 全为缓存命中前提 |

### 4.2 吞吐与连接容量预算（AC-E4/E5/E8）

**并发公式（Little's Law，**用均值**，勿用 P95——修 Q1）**

```
平均并发 C = λ × W_avg = λ × [ h×W_hit_avg + (1−h)×W_miss_avg ]
主端口容量约束：C ≤ MAX_WORKERS = 20（排队不增加并发，只增加等待）
AC-E2 只给了 P95（W_hit=5ms、W_miss=1.2s）；把它们**当均值**代入得到的是**保守上界**：
  h=0.80 → C ≤ 100×(0.004 + 0.24)  = 24.4   （上界，> 20）
  h=0.84 → C ≤ 100×(0.0042 + 0.192) = 19.6   （上界，临界）
  h=0.90 → C ≤ 100×(0.0045 + 0.12)  = 12.5   （上界，有余量）
真实均值 ≤ P95（且命中时间也 ≤ P95），故真实 C ≤ 上界 ⇒ 24.4 不构成"80% 不可达"的证明。
```

**架构结论（Q1 裁决：零修改 PRD 指标、零修改 `MAX_WORKERS`）**
- `MAX_WORKERS=20` 保持（守 AC-E8/EFF-3 硬界）；**不新增"命中率"AC**。
- AC-E4 的可断言口径维持 PRD 原文：**错误率 = 0 + 后 3min P99 劣化 ≤20%**。
- "命中率 ≥90%"**降格为 SAD 内部设计目标 + `/healthz` 观测项**（`cache_hit_ratio`，§2.6）；**待 P6c 实测若 <84% 再走 PRD 修订流程**（不得以解析式越权改 PRD 的"待校准"口径）。
- 支撑手段（不构成 AC）：① prefetch 预热（间隔 = 域 TTL）；② 负缓存把故障态 `W_miss` 从"1.2s 级"压到"<1ms 级"。

**帧共享与字节计费（修 P0-1——把"共享引用"与"预算计费"对齐）**

现状 `_broadcast`：**每组每 tick 只构建一个 `frame` 对象**（`str`），把它 `put_nowait` 进该组所有连接的 `q`——即 100 连接**共享同一引用**。因此：
```
distinct 帧对象数 ≤ 活跃组数 G（每组每 tick 1 个）
单组同时保留的 distinct 帧 ≤ 队列深度 8（队列满后丢最旧，各连接队列同步于最近 8 个 tick）
stream_queue_bytes = Σ_g Σ_{f 被 g 的队列保留} len(f)     ← 每个 distinct 帧只计一次
```

**计费实现（标准库，引用计数）**：`_broadcast` 构建帧后包一层轻量持有者（`_Frame{payload, refs}`）再入队；**成功 `put_nowait` 时 `refs+=1`（0→1 时把 `len(payload)` 加进 `stream_queue_bytes`）**；**队列丢最旧 / handler 出队消费时 `refs-=1`（1→0 时减回）**。于是每个 distinct 帧的字节**恰好计一次**，指标 `stream_queue_bytes` 反映真实占用。（替代原"# 每次入队累加 `len(frame)`"——后者 1 组 100 连接 × 14MB = 计 1.4GB，预算按构造必超。）

**`_Frame.refs` 并发安全与生命周期收口（修 P1-N2——预算判据必须自洽）**

① **并发安全（`refs` 读改写必须原子）**：`refs` 被 `push_loop` 线程（入队 `+1`、队列满丢最旧 `−1`）与各连接 handler 线程（出队 `−1`）并发读改写。CPython 下 `refs += 1` **不是原子操作**（LOAD/ADD/STORE 三步），且 `queue.Queue` 自带锁**不覆盖**"计费累加 + 入队"这一复合操作 ⇒ 计数漂移，而 `stream_queue_bytes` 是丢弃判据的**唯一输入**，漂移直接导致预算误判。收口（纯标准库）：
- 新增模块级 `_frame_bytes_lock = threading.Lock()`；**所有 `refs` 读改写与 `stream_queue_bytes` 增减一律在 `with _frame_bytes_lock:` 内完成**。临界区仅几条整数算术（无 IO、无嵌套加锁、不触碰 `_groups_lock`/`conns_lock`）⇒ 不引入锁序风险，也不与"C-2 锁序 groups → conns"交叉；
- 统一两个对称原语：`_frame_acquire(f)` = `with _frame_bytes_lock: f.refs += 1; if f.refs == 1: stream_queue_bytes += len(f.payload)`；`_frame_release(f)` 为其逆运算（`refs == 0` 时减回）；
- 可白盒断言的不变式：`refs == 该帧当前被多少连接队列持有`，`stream_queue_bytes == Σ_{refs>0} len(payload)`；
- 备选（不选）：改用 `threading.Semaphore`/自造原子整数——标准库无原子整型，`Semaphore` 语义（超发/负值）与"引用计数 + 按 `len` 计费"不匹配。

② **生命周期收口（摘除/销毁必须归还字节）**：连接被摘除（`_serve_sse` 的 `finally`）、`_release_conn`、`destroy_group`、handler 异常退出等**所有**终止路径，必须**排空该连接队列并对每个被移除的帧 `refs−=1`**（`1→0` 时从 `stream_queue_bytes` 减回）。否则残留帧的字节**永久占用预算**（单调泄漏）⇒ 后续 tick 无条件丢帧——正是 P0-1 要消除的后果。落地：
- 新增 `_drain_conn_queue(conn)`：`while True: try: f = conn.q.get_nowait() except queue.Empty: break; if isinstance(f, _Frame): _frame_release(f)  # None 哨兵跳过`；
- 在 `_serve_sse` 的 `finally`（连接摘除）、`destroy_group`（`g.conns.clear()` 之前）、`_release_conn` 三处调用 `_drain_conn_queue`；
- **`None` 哨兵不计费（修 P1-N2③）**：`destroy_group` 用 `q.put_nowait(None)` 唤醒 handler（`stream.py:333`）；`None` **不包 `_Frame`、不参与 `refs`/字节计费**，`_drain_conn_queue` 与 handler 出队逻辑遇到 `None` 直接跳过，仅用于唤醒。

**预算与组数的关系（推导式；v1.4 补单帧余量）**
```
F_max（单帧字节上界）= stream_frame_bytes(MAX_CODES_PER_SUB, 3)
                     = 200 × 3 × 23KB = 13.8MB          （config 单一来源，勿再手算）
F_g（某组单帧）      = stream_frame_bytes(|codes_g|, |fields_g|)
单组 8 深上界        = 8 × F_max ≈ 110MB
预算 B = STREAM_QUEUE_BYTES_BUDGET = 128MB
  ⇒ B ≥ 8 × F_max：单个满尺寸组的完整 8 深窗口不被预算强制驱逐（保 AC-E5「丢弃 ≤1 帧」）
  ⇒ B ≤ 256MB：落在 AC-E7 的临时上限占位内
准入（create_group / patch_group）：Σ_g F_g + max_g F_g ≤ B        ← ★ v1.4 单帧余量
  ⇒ 满配等价组的容量 (N+1) × F_max ≤ B ⇒ N ≤ floor(B/F_max) − 1 = 8
  （只卡 Σ F_g ≤ B 时 N 可达 9，但每一次 _broadcast 都必须先驱逐一个真实帧才能为新帧
    腾位 ⇒ 预算退化成"每 tick 丢帧机"，AC-E5 的稳态前提被破坏）
MAX_GROUPS=200 **不参与**内存护栏（它界的是每 tick 帧构建次数/CPU）；跨组帧内存的唯一护栏是 B；
单帧余量准入让"准入判据"与"广播时必然要腾出一帧"这两件事**口径一致**。
```

**确定性丢弃行为**：构建新帧后若 `stream_queue_bytes + len(frame) > B`，**反复**从"当前保留字节最大的组中队列最满的连接"丢弃其最旧帧，直至可容纳；每次丢弃 `stream_frame_dropped_total += 1`。因 `B ≥ F_max`，任一单帧必可入队（最坏清空其余）⇒ **不丢最新帧**（AC-A2 语义保持）。

**SSE 容量（AC-E5/E7）**：连接 100；单组 ≤200 码 ×3 字段；单 tick 帧构建 + 100 连接入队 ≤1s（**帧对象同组共享同一引用**，不产生 100 份拷贝——耗时与内存同时达标的关键，且与上面的 distinct 计费一致）。流端口 worker = `MAX_STREAM_CONNS + 10 = 110`（每条 SSE 常驻 1 worker）。

### 4.3 资源上界表（AC-E6/E7/E8/E9/S9）

| 资源 | 上界 | 超限行为 | 现状 → 目标 |
|------|------|---------|------------|
| 主端口 worker | 20 | — | 不变 |
| 主端口 inflight | 40（20 运行 + 20 排队） | **立即 503，不排队** | 现状隐式 `20×2` → 显式 `MAX_INFLIGHT` |
| 流端口 worker | 110 | — | 不变 |
| SSE 连接 | 100 | 503 | 不变 |
| 活跃组数 | **200（新增）** | 建组 400 | 无上限 → 有界；**CPU/帧构建护栏，非内存护栏**；**400 属新增对外失败模式，登记见 §7.1（P2-N7）** |
| SSE 单连接队列 | 8 帧 | 丢最旧保最新 | 不变 |
| SSE 全局队列字节 | **128MB（新增，distinct 帧计费）** | 从最满连接丢最旧（确定性，§4.2） | 无界 → 有界 |
| **跨组 distinct 帧工作集（准入 cap）** | **`Σ_g F_g + max_g F_g ≤ 128MB` ⇒ 满配等价组 ≤ 8**（v1.4 单帧余量） | 建组/增码 400 `subscription frames would exceed …` | 新增（S2-2/P1-4）。**这是"准入"侧的界，与"运行期"侧的队列字节预算同源**（都经 `config.stream_frame_bytes`）；`_reserve_for` 的排除集 `skip` 单调增长保证驱逐循环终止 |
| 去重码池（成员账 `_*_pool`） | 2000 全局 / 200 单组 | **拒绝（400）**，不截断 | 池上限与"跨组活跃码 ≤2000"对齐（修 P1-1） |
| 端点缓存（数据 `_*_cache`，L1 域） | **2000/域（独立 LRU）** | 按 `last_access` 淘汰 | 与池解耦、独立 `cache_max` |
| 端点缓存（f10 / announcement 数据） | 500/域 | 同上 | 独立 LRU |
| URL 缓存 | 2000 条（≈20MB） | 按 `last_access` 淘汰 | FIFO → LRU；清扫双触发 |
| feed 缓存 | 100 条（≈30MB） | 按 `last_access` 淘汰 | FIFO → LRU；TTL 30s/180s |
| sector 缓存 | 2000 条 / 7d | 淘汰 + 过期清扫 | 不变 |
| 负缓存（URL 级） | 与 URL 键同域（≤2000），4 键 `until`/`kind`/`fail_count`/`first_at` | **门禁过期失效；条目保留作失败历史**（仅"成功"或"满额淘汰最早 `until`"时清除）；`first_at` **不被后续失败刷新**（连续失败段起点，`≥_HISTORY_AGE=600s` 即老化 ⇒ 本次用全预算探测） | 新增（v1.4 补 `first_at`） |
| 码级冷却账 `_fail_ledger` | `(domain, code)` ≤ `_FAIL_LEDGER_MAX = 5 域 × 2000 = 10000`，条目 **4 元** `[fail_count, cooldown_until, kind, last_fail_ts]`，冷却 120s | 过期即清（**老化扫描限流 `_FAIL_LEDGER_PRUNE_INTERVAL=5s`**）；超硬上界按 `dict` 插入序前端弹出（O(1)，不再全表 `sorted`）；`_COOLDOWN_PUBLISH_INTERVAL=5s` 限流 `code_cooldown_list` 重建 | 新增（P1-5；v1.4 更正条目形状 + 补上界/节流） |
| 流侧 last-known 结转 `_last_known` | `code → {field: 非空值}`，**每 tick 按存活码池剪枝** ⇒ ≤ `MAX_DEDUP_CODES`（2000） | 码离开存活池即回收；全字段为空则删该码条目；无活跃组时整表清空 | 新增（v1.4，P1-4 帧完整性） |
| CDP 页面 | `CDP_STOCK_PAGES`(默认3) + 2 常驻 | 固定，不随流量增长 | 不变 |
| 后台线程 | 4 prefetch + push + stream + watchdog + warm + init ≈ 9（+CDP 心跳 5） | — | 不变 |
| **healthz 专用执行器线程** | **5（懒创建）** | 信号量准入失败 → stale 快照 | 新增，计入 AC-S9「基线+20」 |
| healthz 在飞 check | `MAX_HEALTH_INFLIGHT=5` 批 × <=`len(ROUTES)=5` 源 = **≤25 在飞**；执行器队列 ≤20 | 返回上次快照 + `stale:true`（准入位由 `_HealthBatch` 在该批 future 全部结束后释放，**恰好一次**） | 新增（修 P1-3 / P1-1） |
| 批处理并发 | `_BATCH_MAX_WORKERS = 8`/请求 | — | 不变 |
| 进程内存 | AC-S9：≤ 基线×1.5，2C2G 参考 ≤1.2GB | 指标告警 | 新增总账 |

**池上限与"跨组活跃码"的自洽（修 P1-1 / P1-N1，替换原"500→200"推导）**：
```
去重池是跨组共享的单一 dict（_fundflow_pool/_basic_info_pool/_timeline_pool…），
MAX_CODES_PER_SUB=200 只是**单组**上限，MAX_DEDUP_CODES=2000 才是**活跃码总上界**。
⇒ 池上限 = pool_max = MAX_DEDUP_CODES (2000)，不写死 200（200 只会在 ≥2 个不重叠组时抖空缓存）。
⇒ "一个 L1 周期必然覆盖整池"仅当覆盖条件 C1 成立（`_fetches_per_code(fields) × N_active ≤ coverage = 23 取数次数/周期`，⇔ `N_active ≤ coverage_codes` = **23 / 11 / 7 码/周期**（1 / 2 / 3 域，盘中），见 §2.1 INV-1b）；
   C1 不成立时按 §2.2 R-6 分片轮转，陈旧度 ≤ ceil(N_active/coverage_codes)×L1，并在 metrics 标记；
   例：200 码 × 3 域 ⇒ slice=7 ⇒ lag=29 tick ≈ 232s（盘中 8s tick）——**这是默认场景，不是异常**。
   非盘中 tick=120 ⇒ coverage=349 ⇒ 3 域 coverage_codes=116，同一订阅 lag=2。
⇒ 数据内存不再由池上限承担：改由终点缓存独立 cache_max（上表）守住。
```

**内存分项估算（进程内，2C2G）**：URL 20MB + feed 30MB + L1 端点数据缓存（**3 域** quote/fundflow/timeline × 2000 × ~8KB ≈ 48MB；修 P2-N5，原"4 域≈64MB"失实）+ f10/announcement ≈11MB + sector 0.2MB + **`_last_known` ≤2000 码 × 3 字段（引用同一批 dict/数值对象，≈1MB 保守计，v1.4）** + SSE 队列 ≤128MB + 解释器/栈 ≈30MB ≈ **268MB**；Chrome 独立进程 ≈5 页×150MB ≈ 750MB（见 ADR-012）。合计 ≈1.01GB < 1.2GB 参考线，**余量薄**——故 `STREAM_QUEUE_BYTES_BUDGET=128MB`、**单帧余量准入（⇒ 满配组 ≤8）** 与 `MAX_GROUPS=200` 是必需而非可选。

---

## 5. 架构决策记录（ADR）

> 每条含：背景 → 选项 → 决策 → 理由 → 影响 → 对应 AC。按"可逆性"排序：**低可逆 8 条（001-005 机制/契约 + 013 内存护栏 + 016 帧契约 + 017 代码身份）**，**中可逆 9 条（006-012 + 014 + 015）**。（v1.4 新增 015/016/017；001/003/009/013/014 按实现补正。）

### ADR-001 TTL 单一权威来源（低可逆）
**背景**：R16/R12/D1-D4——7 类互不引用的时间常量，至少 4 处断崖（含新发现的 feed 层 300s vs L3 30s）。
**选项**：A 全局单值 TTL（简单，牺牲分层时效）；B 保留各常量、加注释与测试校验（低改动，仍靠人守）；C `config.cache_policy(domain)` 纯函数派生，所有消费者读它，禁止裸字面量。
**决策**：C。
**理由**：分层是需求（L1/L2/L3/L4 是"准确"的基准口径），不能压成单值；B 无法阻止未来再分叉（本次 4 处断崖就是 B 的产物）。C 用**一条不变式**（`ttl_url == ttl_terminal == policy.ttl`）把"一致性"变成可断言的性质而非纪律。
**影响**：删 8 个常量、改 6 个模块的 TTL 取法、`_cache_age()` 与 `/healthz` 的 `cache_ttl` 改读 policy（后者保留字段名与含义）；**`CACHE_TTL` 消费者核实为 `cache.py` 默认值 + `server._get_or_fetch_feed`**（`utils.py:12` 为未使用 import，随常量删除；`warm_jin10` 经 `fetch_json` 默认值）；**`DOMAIN_MATRIX` 补入 `longhu` 域（L4/300s/GBK）**、`cache_max` 维度、plate stagger 派生；feed 层新鲜度由 300s → **30s（盘中）/ 180s（非盘中）**（行为变更，Q3）；`fetch_json` 新增 `encoding` 形参（D5）。**AC**：A3/A4/E6/E9。

### ADR-002 下划线保留键 vs envelope（低可逆，对外契约）
**背景**：R4/R14 需要往批量响应加元信息，但响应是扁平映射 `{code: data}`（🟠 STABLE，只增不改）。
**选项**：A envelope `{"data":{...},"errors":{...}}`（语义清晰，**改义**：把扁平变嵌套，既有消费方全部失效）；B 直接在顶层加 `errors`/`truncated`（与股票代码键**同命名空间**，未来若出现 `errors` 形态代码即冲突，且污染既有遍历逻辑）；C 下划线前缀保留键 `_errors`/`_truncated`/`_dropped_count`（代码键恒不含前导下划线 → **恒不冲突**）。
**决策**：C（与 PRD §7.1 一致）。
**理由**：A 违反只增不改；B 的冲突是"概率事件"，C 的隔离是"结构性保证"。代价是消费方需跳过 `_` 前缀键——以**一处约定**换**零破坏**，最优。
**影响**：names 冻结为全局保留键集合（本表外不得新增）；`stream._refresh_pool` 必须过滤 `_` 前缀（唯一陷阱点，列为必测）。**AC**：A9/A10/S6。

### ADR-003 负缓存（失败短缓存）策略（低可逆）
**背景**：R9——失败不留痕 ⇒ 每请求重走选举 + 回退，单线程最坏 13.5s，故障期延迟/上游压力线性放大。AC-S3 要求模式 A"秒拒"P95 ≤1s；模式 B"黑洞"P95 **分档**（高请求密度 ≤5s / 低请求密度 ≤10s，v1.5 重标）且单请求 ≤15s。
**选项**：A 不引入负缓存，仅靠有界回退并发（现状形态，延迟 13.5s、上游压力大）；B 负缓存 + 首次失败即记录 + 冷却期快速失败；C 熔断器（连续 N 次失败 → 全局熔断端点，有半开态）。**TTL 取值**：1s / 5s / min(5, L1) / 30s。**探测超时取值**：`REQUEST_TIMEOUT`（10s）/ `PROBE_TIMEOUT`（2s，半开）/ **阶梯递增（2→4→5 封顶）** / 阶梯封顶 + **失败历史老化**（v1.4/v1.5）。
**决策**：B + **半开短探测**；`NEG_TTL = min(5, L1) = 5s`（交易与非交易都取 5）；探测预算 = **`_probe_budget(fail_count)` 阶梯递增 2→4→5（`_PROBE_BUDGET_CAP=5.0` 封顶），并对超过 `_HISTORY_AGE=600s` 的失败历史本次改用全预算（10s，不经过阶梯上限）**（v1.5，取代 v1.4 的"2→4→8→10"）。
**理由**：C 的全局熔断粒度太粗——单码失败会拖垮整端点，与 AC-S6"单码故障不扩散"冲突；A 已被 PRD 明确拒绝；B 的粒度是**URL 级**（≈ 码级），正好匹配故障域。5s 是"恢复感知"与"放大抑制"的平衡点（PRD §5 #4 明确接受 ≤5s 的恢复延迟）。**半开短探测是 AC-S3 模式 B 达标的必要条件（修 P1-2）**：若每次探测都用 10s，则稳定故障期每 `10s+5s` 周期有一次 10s 阻塞，慢请求占比 10/15≈67% ⇒ P95≈10s（原 SAD 错误）；**封顶 5s 后稳态周期 = `5s+5s`，慢占比 ≈50% ⇒ 高密度 P95 ≈5s、低密度 ≈10s（均落在 PRD v0.5 分档内）**。
**v1.4 补（为什么恒定 2s 也不够）**：`fail_count` 只在成功时清零，**恒定 2s 会把"慢而 >2s 才成功"的上游永久钉死**——它每次都超 2s、每次都失败、历史永不清 ⇒ 与 AC-E2 长期互斥（"永久 2s 陷阱"）。解法是**两个正交的松绑**：① **阶梯**（成本随连续失败数上升，给慢上游更多机会）；② **老化**（`first_at` 不被后续失败刷新；`≥600s` 视同无历史，本次用 10s 全预算并重置窗口）。
**v1.5 补（5s 封顶的代价，已登记权衡）**：封顶 5s 使"需要 6–10s 才返回的慢而未死上游"**无法再靠阶梯自愈**（顶端 5s < 其所需），只能等 `_HISTORY_AGE=600s` 老化后拿一次 10s 全预算 ⇒ **该类上游恢复延迟最多约 600s**；**快速黑洞 / 秒拒类不受影响**（其失败与恢复由 5s 档覆盖）。**恢复延迟与分档 P95 的取舍在此定死**：调大 `_PROBE_BUDGET_CAP` 会连带抬高 P95 分档（须重标 AC-S3），故不作为默认缓解（见 AR-13）。
**影响**：`fetch_json` 契约新增 `FetchError(kind)`（**五段式**：正缓存 → deadline 闸门 → 负缓存门禁 → leader 单次 → follower 读状态）；删除 fall-through 三段路径；新增 `PROBE_TIMEOUT`（阶梯起点，仍从 config/env 读）/ **`_PROBE_BUDGET_CAP`（阶梯封顶，机制常量）** / `fail_count` / `first_at` / `_HISTORY_AGE` / `_FOLLOWER_WAIT_MARGIN`；**失败条目跨 `NEG_TTL` 保留**（过期只让门禁失效，条目留作失败历史；仅"成功"或"满额淘汰最早 `until`"才清除）；所有调用点需确认 `except Exception` 覆盖（逐点核对，含 `utils.warm_jin10`）。**AC**：S3/S6/A10；模式 B 需 P6c 校准（Q6）；**调小 `_HISTORY_AGE`（<~120s）或改动 `_PROBE_BUDGET_CAP`/`NEG_TTL` 任一分量必须重跑 AC-S3 模式 B 校准**（AR-13）。

### ADR-004 并发模型：不可变组状态 + 快照广播（低可逆）
**背景**：R5——`_build_frame` 无锁遍历 `g.codes`，与 PATCH 并发。**实测当前安全**（整体替换而非原地变更），但契约未显式化。AC-S2 要求 tick 劣化 ≤20%。
**选项**：A 全路径加 `_groups_lock`（简单，但让 CPU 重的帧构建阻塞 PATCH → 违反 S2 指标）；B 细粒度 `g.codes_lock`（新增锁与锁序风险）；C `codes→frozenset` + 快照式广播，锁只保护"取快照"，帧构建在锁外。
**决策**：C。
**理由**：不可变对象是**编译器/类型层面的保证**，比"记得加锁"强；且把 CPU 移出锁区是 S2 达标的**结构性**前提（A 需要靠调优）。C 无需新锁，锁序保持 groups→conns。
**影响**：`_build_frame` 签名改为接收 `(snapshot, codes, fields)`；`patch_group` 继续整体替换；新增并发 PATCH 渗透测试。**AC**：S2/A1/A2/E5。

### ADR-005 CDP 降级：形状优先 + 枚举错误码（低可逆）
**背景**：R18/R19 + AC-S4——19 条 CDP 相关端点的三分清单（A 4 / A′ 1 / B 14 / C 0）。
**选项**：A 按"依赖度"统一返回 error 客体（A′ 会被判失配——`/stock/f10` 是批量形状）；B 按"有无 REST 替代"决定形态；C 按"端点形状（扁平 vs 客体）"决定降级形态，依赖度只决定走不走替代路径。
**决策**：C。
**理由**：**消费方的解析方式由形状决定**，不由依赖度决定。批量族共用 `_handle_cached_batch` 的扁平输出，硬塞 error 客体等于让消费方对同一端点写两套解析（AC-S4 明确禁止）。C 使"降级形态 = 端点形状的投影"，无需逐端点记忆。
**影响**：A′ 的 `cdp_unavailable` 经 §2.4 组装；A 类补 `timeline` 缺失时的 error 客体（R18 旁支）；B 类保持 REST 优先。**AC**：S4/S1/A10/S6。

### ADR-006 healthz 隔离与预算（低可逆）
**背景**：R2——`?check=1` 在请求线程串行拉 5 源，最坏 50s，与业务抢主池；AC-S8 要求业务 P95 劣化 ≤50%、单次健康检查 ≤10s。
**选项**：A 保留串行 + 减少检查项（不达 10s）；B 专用小执行器（5 worker）+ 整体 10s 预算 + `check=0` 零上游；C 后台线程周期性刷新，`check=1` 只读快照（最隔离，但"检查"失去即时性，且多一条常驻线程）。
**决策**：B；并让 `check=0` 走零上游快路径（现状 `check=0` 已经不拉上游，但 payload 构造遍历 ROUTES，保留即可）。
**理由**：C 的"即时性"缺失会让 `?check=1` 语义退化（AC-S8 要求"每个健康检查请求 ≤10s 完成"，隐含允许发起真实检查）；B 用**物理隔离的执行器**保证不占用主池，同时保留即时性。10 个并发 healthz 只占 5 个专用 worker，主池 20 个 worker 不受影响 → 劣化 ≈0。
**影响**：新增 `_health_executor` + **`BoundedSemaphore(MAX_HEALTH_INFLIGHT=5)` 有界准入**——`submit()` 工作队列无界且永不拒绝，"执行器忙 → stale"是死代码（修 P1-3）；现在准入失败（达到 5 在飞）→ "上次快照 + `stale: true`"，**该路径可达且可测**；`healthz_stale_total`/`healthz_inflight` 入 metrics。**AC**：S8/S10。

### ADR-007 统一 handler 异常边界（中可逆）
**背景**：R1/R18——14 个 JSON 路由分支无 try；`_serve_feed` 有。异常穿透 → 裸断连、无响应体。
**选项**：A 逐个 handler 内部 try/except（改动面大、易遗漏、契约分散）；B `_handle_request` 顶层 try 包住整个路由（一处生效，但**无法区分形状**，批量端点会退化成 error 客体 → 违反 AC-S4）；C 按形状分类的 `_guard(shape)` 包装器，在路由分发处统一套用。
**决策**：C（`shape ∈ {batch, object, rss, text}`）。
**理由**：B 的"一处兜底"看似优雅，但**丢失了形状语义**——正是 AC-A5「错误体 vs 值域」边界口径所禁止的"跨类别即判失配"。C 用 4 种形状覆盖全部 14 分支，且新增极端点时只需选 shape。
**影响**：`shape` 建议由路由表派生（不写死端点数字，避免再次漏数，修 P1-6）；`/cls/hotplate` 维持**分区 error 客体**（唯一口径，见 §2.3 D-4，修 P2-3②）；`_guard` 计入 metrics（异常计数）。**AC**：S1/S4/A5。

### ADR-008 淘汰策略：访问时间 LRU + 双触发清扫（中可逆）
**背景**：R3/R11——淘汰键用写入 `time`，命中不更新 ⇒ 注释写 LRU、实为 FIFO；过期条目最长滞留 60s。
**选项**：A 维持 FIFO，改注释（诚实但牺牲热点源命中率）；B `OrderedDict.move_to_end` 真 LRU（标准库原生，O(1)）；C 显式 `last_access` 字段 + `min()` 扫描（O(n) 淘汰）。
**决策**：B 的结构（`OrderedDict` 保序）+ 命中 `move_to_end`；淘汰 `popitem(last=False)`（O(1)）。清扫仍双触发（定时 + 写入时局部）。
**理由**：C 的 O(n) 在 2000 条目 × 高写入下会成为延迟抖动源（本地命中 P99 ≤15ms）；B 是标准库原生、O(1)、语义即 LRU。feed 缓存同样改造。
**影响**：`cache{}`/`feed_cache{}` 容器类型变更（`dict`→`OrderedDict`）；tests 若有 `dict` 断言需同步。**AC**：E6/E9/A8。

### ADR-009 期限贯通数据获取层（中可逆）
**背景**：R13——REST 取数器不收 `deadline`，`_fetch_one` 的 `TypeError` 回退静默丢弃期限；分块串行叠加 → 整批无界（名义 60s）。
**选项**：A 保持现状（靠 `REQUEST_TIMEOUT` 隐式兜底）；B 只给 REST 取数器加 `*args, **kwargs` 吞掉参数（消除 TypeError，但期限仍不生效）；C 全部取数器显式 `deadline=None` 形参，并在 `urlopen` 与入口都强制使用。
**决策**：C。
**理由**：B 只消除异常、不产生约束（"静默丢弃"变成"静默忽略"）；C 让期限成为**可测试的类型契约**（形参即文档），并支撑 §4.2 的 `W_miss` 收敛。
**影响**：取数器签名变更（`deadline` + `ttl` 两个可选参数，向后兼容）；**`fetch_json` 也新增第 5 位形参 `deadline`（v1.4）**，且**超期闸门位于正缓存命中之后**（先给数据、再谈预算）；`_handle_cached_batch`/`_process_chunk`/`_run_batch` 增加 `budget`/`ttl`，`_run_batch` 返回值变 `(results, errors)`（**管道层内部**结构，handler 侧经 `build_batch_response` 组装为 dict）。**AC**：E2/S7/A10。

### ADR-010 新增 metrics.py（中可逆）
**背景**：R8/R19/S10——tick 耗时、503、丢弃帧、缓存条目、冷却清单、CDP 窗口全不可观测；PRD 要求"仅用标准库日志与现有接口"。
**选项**：A 各模块各加全局计数变量（无中心、跨模块不可聚合、healthz 要 import 一圈）；B 新增 `metrics.py`（约 60 行，单锁，`snapshot()`）；C 用 `logging` 结构化日志替代指标（无当前值可查）。
**决策**：B。
**理由**：A 会让 `server.build_health_payload` 依赖几乎所有模块的私有全局（依赖方向恶化）；C 满足不了"查询健康状态即可观测"的 AC-S10 语义。B 是唯一"中心化 + 零依赖 + 可 `snapshot()`"的形态，60 行也符合项目"保持小"的约束。
**影响**：新增模块（模块数 +1，可接受；**v1.4 实测 185 行**）；`/healthz` 新增 `metrics` 字段（只增）。**AC**：S10/E7/S8/S3。

### ADR-011 流端口管理体读预算 5s（中可逆）
**背景**：R6/S7——管理端点 `_read_json_body` 只有 30s socket 超时兜底，慢客户端长期占用管理线程（名义 31s）。
**选项**：A 全局把 `StreamHandler.timeout` 降到 5s（**会误伤 SSE**：`_serve_sse` 依赖 30s 初值，虽会重设 40s，但顺序脆弱）；B 仅对请求体读取临时 `settimeout(5)`，读完恢复；C 用非阻塞分段读 + 截止时间循环。
**决策**：B。
**理由**：A 的副作用面大于收益（SSE 与管理的超时需求不同，共用一个 class 属性是现状的耦合）；C 在标准库 `BaseHTTPRequestHandler` 上要重写 `rfile` 交互，复杂度不成比例。B 用"最小作用域"（仅 body 读）达到 5s 目标。
**影响**：`MGMT_BODY_TIMEOUT` env 化；SSE 路径不受影响（`_serve_sse` 仍重设 40s）。**AC**：S7/R6。

### ADR-012 CDP 守护重启交易时段避让（中可逆）
**背景**：R19/R20——watchdog 每 7200s 无条件重启 Chrome，窗口 15s 节流 + 45s 启动内 CDP 端点全空，且不可观测；AC-S4 要求降级可验证、AC-S9 要求 24h 内存不单调增长。
**选项**：A 盘中照常重启（45s 无数据窗口无法消除，AC-S4 目标需放宽）；B 交易时段跳过、非交易时段照常（内存回收延后到盘后）；C 盘中不重启、仅靠 nav 阈值触发（`_MAX_PAGE_NAV_BEFORE_RECONNECT=30` 已有自愈路径）。
**决策**：B（PRD §5 #5 倾向项）；同时把窗口状态机（`idle/restarting/unavailable`）暴露到 `/healthz` 并在 metrics 记录窗口时长。
**理由**：C 依赖导航量，低流量下永不触发（这正是 watchdog 存在的理由，见其 docstring）；B 在"内存回收"与"盘中连续性"之间选后者——短线盘中 45s 无数据是不可接受的产品缺陷，而 7200s 周期内延后到收盘后回收，内存前提（AC-S9 ≤基线×1.5）仍成立（盘后 CDP 心跳降至 60s，负载低）。
**影响**：`_cdp_memory_watchdog`（**位于 `server.py:881`，非 cdp_engine.py**，修 P2-2）增加 `_is_trading_hours()` 判断（顺延，不累积）；cdp_engine 只保留窗口状态机与页面数联动；页面数仍由 `CDP_STOCK_PAGES` 控制（默认 3，与内存总账联动）。**AC**：S4/S9/S10/R19/R20。

### ADR-013 SSE 队列字节计费：distinct 帧 × 深度（低可逆，修 P0-1）
**背景**：P0-1——§2.2「每次入队累加 `len(frame)`」与 §4.2「同组共享同一引用」互斥；按前者计费，100 连接 × 14MB = 计 1.4GB，预算按构造必超、每 tick 无条件丢帧，AC-E5/A2 落空；而 `MAX_GROUPS` 界不住跨组帧内存，此预算是唯一护栏。
**选项**：A 每连接持独立帧拷贝并按连接计费（内存 ×连接数，违背帧共享）；B 放弃字节预算，仅靠单连接队列 8 帧（跨组内存无界）；C **引用计数只对 distinct 帧计费一次**（`_Frame` 持有者 + refs，入队 0→1 加、出队/丢最旧 1→0 减），预算 = `Σ len(distinct frame)`。
**决策**：C；`STREAM_QUEUE_BYTES_BUDGET=128MB`（≥ `8×F_max≈110MB`，≤ AC-E7 的 256MB 占位）。**v1.4 补**：准入判据为 **`Σ_g F_g + max_g F_g ≤ B`**（单帧余量），使满配等价组容量由 9 收敛为 **8**——否则一个"恰好填满预算"的合法订阅集会让**每一 tick** 都必须驱逐一个真实帧，预算从内存护栏退化为丢帧机（AC-E5 的稳态前提被破坏）。尺寸一律经 `config.stream_frame_bytes()`。
**理由**：帧共享是内存/耗时达标的前提，不能放弃（排除 A）；单连接有界 ≠ 全局有界（排除 B）。C 让"共享引用"与"预算计费"不再矛盾，且给出可测的不变量 `stream_queue_bytes = Σ distinct len(frame)`。
**影响**：`_broadcast` 增加帧持有者与引用计数；丢弃策略确定性（从保留字节最大组的最满连接丢最旧，绝不丢最新）；组数是 CPU 护栏、预算是内存护栏，二者职责显式分离。**`refs` 读改写须加 `_frame_bytes_lock`，摘除/销毁路径须 `_drain_conn_queue` 逐帧归还、`None` 哨兵不计费**（P1-N2，见 §4.2）；**准入侧须同时落 `create_group` 与 `patch_group`（后者用 `exclude_sid` 重价被替换组）**。**AC**：E5/E7/A2。

### ADR-014 失败状态分层：URL 级负缓存 + 码级冷却共用（中可逆，修 P1-5）
**背景**：P1-5——AC-S6 的"同码连续失败 3 次→120s 冷却"发生在批量请求路径，但 `_FAIL_COOLDOWN` 仅在 4 个 prefetch 循环，批量路径无冷却；且负缓存为 URL 级 5s，二者易被误认为同一机制。
**选项**：A 只保留 URL 级负缓存（冷却 5s，AC-S6 的 120s 无落点）；B 只保留码级冷却（网络层无快速失败）；C **两层协同**——URL 级负缓存（5s，网络层）+ 码级 `_fail_ledger`（120s，业务层），批量与 prefetch 共用同一账。
**决策**：C。
**理由**：两层故障域不同（URL ≈ 端点/码的取数地址；码 = 订阅实体），AC-S6 断言的粒度是**码**、AC-S3 的快速失败是**URL**，缺一不可（排除 A/B）。共用账保证批量与后台对失败码认知一致。
**影响**：`stock_api._fail_ledger`（模块级，条目 **4 元 `[fail_count, cooldown_until, kind, last_fail_ts]`**，v1.4 更正）+ 4 个 prefetch 的局部 `fail_blacklist` 删除；`_process_chunk` 取数前判冷却；仅"取数失败（异常/超时）"计数，成功清零，"无数据"不计，**本地预算耗尽（`_LOCAL_BUDGET`）不计**（v1.4 实现 / **v1.5 正式反转确认**，见下）；`code_cooldown_list` 导出 + 发布节流。**AC**：S6/S10/A10。

> **v1.4 反转登记 → v1.5 正式反转确认（取代 REV-DES-15 的"建议②"）**：批 2 详设评审曾决定"**预算耗尽也计入冷却账**"（理由：保留现口径、避免引入内部哨兵）。实现的最终口径**相反**：`_run_batch` 用内部标记 `_LOCAL_BUDGET` 逐码产出（**不新造 `FetchError.KINDS` 成员**，故并没有破坏 SAD 钉死的 `(results, errors)` 形状），`_process_chunk` 把它翻译成对外的 `'upstream_timeout'` 但**绝不写账**。反转理由：把"我们自己的预算耗尽"记成"上游连续失败 3 次"，会让**一个慢批把整条码池尾巴推进 120s 冷却**，而冷却又让下一批更快耗尽预算——自激正反馈。该口径与 `cache.py` 的 S1-1（本地等待预算不写负缓存）**逐字一致**。**AC-S6 的断言口径据此限定为"真实上游失败"**。**v1.5：编排层正式裁决"`_LOCAL_BUDGET` 不计入冷却账本"（PRD v0.5 §9.1③），本反转不再是"实现单方面偏离评审"，而是已确认口径**（代码位置：`stock_api.py:490-498` `_process_chunk` 命中 `_LOCAL_BUDGET` ⇒ 翻译后 `continue`；`:390-394` `_run_batch` 预算耗尽不建线程）。

### ADR-015 按订阅字段刷新（中可逆，v1.4 新增）
**背景**：`_refresh_pool` 历史上**无条件**对 `_FIELD_HANDLERS` 的全部 3 个域（quote/fundflow/timeline）各刷一次。但组的 `fields` 是**订阅契约**：一个 `fields=["quote"]` 的组每 tick 仍付 3 倍上游成本，且容量模型把每码成本硬编码为 3 ⇒ ① 上游负载与订阅无关（浪费 2/3）；② `coverage_codes` 被低估（quote-only 组明明能覆盖 23 码，模型只给 7）⇒ 制造**不存在的容量不足**，把一个本可整池刷新的订阅降级成分片轮转。另有一个正确性面：`codes` 与 `fields` 若分两次加锁读，会与"组关闭"交错，得到**字段集已不再被订阅**的码池。
**选项**：A 保持无条件 3 域（简单、容量模型与订阅解耦；代价是 3× 上游 + 容量低估）；B 按订阅字段并集刷新（成本与订阅成正比；代价是 `coverage_codes` 随字段数而变、C1 门限不再是常数）；C 按组分别刷新（每个组独立切片；代价是共享池被拆散、去重收益消失、上游成本回升）。
**决策**：B。字段集 = **存活组订阅字段并集**（`_subscribed_fields()`，按 `_FIELD_HANDLERS` 顺序；只算**有连接**的组——僵尸组不得继续为无人消费的域付钱），且 **`codes` 与 `fields` 必须在同一次加锁中读出**（`_active_targets()`）。`_fetches_per_code(fields)` 与 `coverage_codes` 成为**订阅的函数**：盘中 1/2/3 域 ⇒ 23/11/7 码/周期。
**理由**：排除 A——"订阅什么就付出什么"是资源模型的底线，且 A 的容量低估会**错误地**把合法订阅推进降级路径（比多付上游更糟，因为它把可用的新鲜度当成不可用）。排除 C——去重池是跨组共享的单一账本（P1-1），按组拆分会同时破坏去重收益与池上限推导。"同一次加锁读 codes+fields"是把"字段集是订阅的函数"从**约定**升级为**结构保证**（P1-6）。
**影响**：`_refresh_pool` 签名 `(codes, now=None, fields=None, tick=None, deadline=None)`；新增 `_subscribed_fields`/`_active_targets`/`_resolve_refresh_fields`/`_fetches_per_code`/`refresh_capacity`；C1 由 `3×n ≤ 170` 变为 `_fetches_per_code(fields)×n ≤ 23`；`coverage_codes` 出现在 201/200 响应（`refresh_capacity_codes`/`refresh_lag_ticks`/`capacity_warning`）。**AC**：A1/A3/E5/S10；AR-1/AR-6。
**何时改变选择**：若上游成本不再敏感（如引入稳定 CDN 边缘缓存）且**帧布局要求"每帧恒定三域"**（当前不要求：`fields` 是帧元数据、`items` 按订阅字段裁剪），可回到 A 以换取"容量常数化"。

### ADR-016 SSE 帧完整性契约：全码在位 + 显式陈旧/缺失/失败（低可逆，v1.4 新增）
**背景**：分片轮转（R-6）把一个"每帧缺 96% 码"的问题暴露出来：旧 `_build_frame` 把**没有数据的码直接不写进 `items`**。在 C2 下（200 码 × 3 域 ⇒ 每 tick 只刷 7 码），客户端拿到的帧里只有 7 个键，而"缺席"同时可以意味着**未轮到**、**无数据**、**上游故障**——三个处置完全不同的状态共用一个信号（P1-4）。补救"只补终点缓存"不够：终点缓存也可能在本 tick 过期而未进切片。
**选项**：A 保持稀疏 `items`（零成本；语义不可判别）；B 稠密 `items` + 三个显式元数据（`missing` / `stale` / `errors`）；C 改增量 diff 帧（带宽最省；但 PRD §6 明确 W 级不做，且丢帧语义会变）；D 只稠密化、不给元数据（客户端仍需猜）。
**决策**：B + **last-known 结转**（`_carry_forward`/`_last_known`）。帧内：`items` **覆盖全部订阅码**（无数据为 `null`）、`codes_total`/`fields` 声明形状、`missing`+`missing_count` 标"本次确实没有值"、`stale`+`stale_count` 标"值来自上一 tick"、`errors` 标"上游失败 kind"。**三者互斥/正交互补**：`missing ∩ stale = ∅`；`errors` 可与前两者任一共存（某字段失败但整行有值）。收缩规则：`errors`/`stale` 只保留 `code ∈ items` 的条目。
**理由**：B 把"一个含糊的缺席"拆成**三个可行动的状态**（等下一 tick / 显示旧值并弱化 / 报故障），而每个状态各自对应消费方的不同处置——这是 AC-A1 与值域三分在 SSE 侧的落点。排除 A/D（不解决不可判别）；排除 C（越出 W 级范围，且会同时改变丢帧与断线重连语义）。
**影响**：`_build_frame` 输出契约扩展（🟠 STABLE **只增**：既有 `ts`/`items` 类型与含义不变；**但 `items` 由稀疏变稠密会增大帧字节**，`stream_frame_bytes` 的 23KB/码/域估算即按稠密帧标定）；新增 `_last_known`（**每 tick 按存活码池剪枝** ⇒ 上界 `MAX_DEDUP_CODES`）+ `stale` 元数据 + `_errors → snapshot['_errors'] → payload['errors']` 的**保留位（非股票项）**；`errors` 的值域 = `FetchError.KINDS ∪ {'tick_budget_exceeded'}`（后者为调度层错误，不入 `upstream_fail_total`）。**AC**：A1/A2/E5/E7；AR-7（`_` 前缀陷阱）。
**何时改变选择**：若客户端体积成为硬约束（如移动端流量计费），可对 `stale` 码**只发字段级差分**——但那属新一轮的"增量帧"设计（W 级），须先改 PRD §6。

### ADR-017 股票代码归一化单一权威 `config.canonical_code`（低可逆，v1.4 新增）
**背景**：系统历史上**同时接受**交易所前缀式（`sh600519`）与点号式（`600519.SH`）两种拼写，但下游是**按字符串建键**的：去重池、终点缓存、URL 缓存键、`_fail_ledger`、CDP 页面的 `SecuCode` 精确比较。不归一化时同一只股票可以铸出**两个池键 / 两个缓存键 / 两次上游取数**（P1-6）；而 CDP 侧的比较混用"精确相等"与 `.upper()`，两种拼写里**必有一种永远匹配不上**（表现为该拼写恒返回 `null`/`cdp_unavailable`）。
**选项**：A 各处就地写正则（最小改动；代价是 N 份实现漂移，且"响应键用什么拼写"没有统一答案）；B 只在下游（池/缓存）归一、响应仍用原拼写（无 N 份实现，但"哪些键是 canonical"要逐点记忆）；C `config.canonical_code(code) -> str | None` 作为**唯一权威**：规范形 = 小写交易所前缀（`sh600519`/`sz000001`/`bj430047`），接受两种写法，非法 ⇒ `None`；所有入口与所有键位经它折叠，**响应键回写客户端原拼写**。
**决策**：C。**`canonical_code` 是冻结接口名**（`server.py`/`stream.py`/`stock_api.py`/`cdp_engine.py` 按此名消费，`tech-stack.json` 的 `layerIsolation`/`namingRules` 需反映）。
**理由**：排除 A——"同一数据两处定义"违反项目纪律（§编码纪律 #6），且 4 个模块各持一份正则会各自演化；排除 B——它把"哪些是 canonical 键"留成隐性知识，评审无法检查。C 让"一个股票一个身份"成为**可断言的性质**（`canonical_code(canonical_code(x)) == canonical_code(x)`），而不是纪律。
**影响**：`config.py` 新增 `canonical_code` + `VALID_STOCK_CODE` + `_DOTTED_STOCK_CODE`；`server._parse_stock_codes`（入口折叠 + `requested` 原拼写序列 + `_rekey_batch_response` 回写）、`stream.create_group`/`patch_group`（折叠后去重 ⇒ 同一股票多种拼写只占一个名额；非法码 = **400**）、`stock_api._process_chunk`/`cached_batch`（canonical 键位 + 结果回写原拼写）、`cdp_engine._same_code`/`navigate_stock`（两侧都归一后比较）全部接入。**注意两条端锁定边界**：① 非法码值在**批量 HTTP 路径**仍是**逐码 `null`**（400 只给"缺 `?code=`"），只有**流端口建组/改组**把非法码当 400（入参校验，非数据）；② 响应键**保持客户端原拼写**（`_rekey_batch_response` 是纯改名，未发生重拼写时 body 逐字节不变）。**AC**：A6/A7/S4；PRD 🟠 STABLE。

**ADR 汇总**：**17 条**（低可逆 **8**：001-005 + **013** + **016** + **017**；中可逆 **9**：006-012 + **014** + **015**）；高可逆决策（如具体常数值、日志文案、"tick 网格 vs 0.25×tick 下限"这类一个函数即可回滚的节拍规则）不记 ADR（tick 节拍落点见 §2.6）。

---

## 6. 技术栈

**结论：本次优化不改变技术栈。** 全部设计均可由 Python 3 标准库实现——关键能力与标准库落点：

| 能力（本次设计使用） | 标准库落点 | 不选其他 |
|---------------------|-----------|---------|
| HTTP 服务（主/流双端口） | `http.server.ThreadingHTTPServer` + `BaseHTTPRequestHandler` | 不引 Flask/FastAPI（零依赖硬约束） |
| 并发与线程池 | `concurrent.futures.ThreadPoolExecutor`、`threading.Lock/RLock/Event/Semaphore` | 不引 asyncio（SSE 全量帧 + 零依赖约束下收益不成比例） |
| 有界队列与丢弃策略 | `queue.Queue(maxsize=8)` + `Full/Empty` | 不自研无锁环形缓冲（锁序风险） |
| 缓存容器与 LRU | `collections.OrderedDict`（`move_to_end` / `popitem`） | 不引 cachetools |
| 时间与时区 | `time`、`datetime(timezone.utc)` + 8h（CST） | 不引 pytz/zoneinfo 依赖数据 |
| 上游调用 | `urllib.request` + `bytes.decode(encoding)`（`fetch_json` 新增 `encoding` 形参，GBK 上游用 `encoding='gbk'`） | 不引 requests / 不引 chardet（编码由域显式指定，见 §2.3 D-5） |
| CDP 客户端 | 现有 `cdp_engine`（`websocket` 为**可选**运行时依赖，CDP 模式才需要；非 CDP 路径零依赖） | 不引 playwright/selenium |
| 观测 | 新增 `metrics.py`（`threading.Lock` + dict）+ `logging` | 不引 prometheus_client |
| 测试 | `unittest`（`python -m unittest discover -s tests -v`） | 不引 pytest |

> ⚠️ 既有依赖说明：`cdp_engine.execute_js()` 内 `import websocket` 为**函数内延迟导入**，仅 CDP 模式使用；本架构不改该状态，且**不将其提升为硬依赖**。

**tech-stack.json 已更新于 `doc/arch/tech-stack.json`（v1.4）**：含 `architectureRules`——`importRestrictions.denylist` 固化"零第三方库"红线；`allowlist` 补入 `websocket`（仅函数内延迟导入，修 P2-7）；`layerIsolation`/`fileStructure` 与 §2.6/§3 的模块划分一致，供 `code-developer` 自验与 `check-arch-compliance.sh` 校验。**帧计费（`_Frame`/refs/`stream_queue_bytes`）归 stream 层，cache.py 不得承载**——由现有 `layerIsolation`（cache.py 禁 import stream/server/stock_api/market_api）覆盖；**feed 缓存机制归 cache 层、`socket` 已在 allowlist**（D-3）。

**v1.4 对 tech-stack.json 的两处实质变更（审计实测得到，非版本号联动）**：
1. **`allowlist` = 实测 import 闭包**。逐模块扫描 `china_finance_rss/*.py` 的模块级 import 后，`allowlist` 遗漏了 **`hashlib` / `html` / `xml`**（三者均来自 `utils.py`：`cls_sign_params` 的 `hashlib`、HTML 实体反转义的 `html.unescape`、RSS/OPML 生成的 `xml.etree.ElementTree`）。它们是**标准库**，缺失会让 `check-arch-compliance.sh` 对 `utils.py` 报假阳性。同时 `itertools` 在包内**无任何引用**（保留无害，已标注为历史项）。`websocket` 仍是唯一"函数内延迟导入"的特例。
2. **`layerIsolation` 补登同层边 `stock_api → cdp_engine`**（`from .cdp_engine import page_data`）。该边**无环**（cdp_engine 的 `forbiddenImports` 已含 `stock_api`），但必须显式登记——否则层级图与 §3「依赖方向」不一致，且未来有人"顺手"把 `cdp_engine → stock_api` 加回来时无据可拦。新增条目如下（与 §3 依赖全图一致）：
   ```json
   { "pattern": "china_finance_rss/stock_api.py",
     "forbiddenImports": ["china_finance_rss.server", "china_finance_rss.stream"],
     "reason": "stock_api 属 Layer 1；允许同层单向引用 cdp_engine.page_data（无环），禁止反向依赖上层（server/stream）" },
   { "pattern": "china_finance_rss/cdp_engine.py",
     "forbiddenImports": ["china_finance_rss.server", "china_finance_rss.stream", "china_finance_rss.stock_api"],
     "reason": "cdp_engine 只允许依赖 config/metrics，禁止反向依赖调用方（含 stock_api）—— 与 stock_api → cdp_engine 构成单向边" }
   ```
   > 另：`namingRules.fetch` 已覆盖"按码取数器签名为 `fetch_*(code, deadline=None)`"；v1.4 起实现实为 `fetch_*(code, deadline=None, ttl=None)`（`ttl` 为第 3 可选形参），**`namingRules` 的措辞已同步放宽为"至少含 `(code, deadline=None)`"**，不要求穷举后续可选参数。

## 7. 待决策、风险与假设

### 7.1 编排层裁决落地（Q1-Q6 + N1（v1.5 关闭）/N2）

| # | 事项 | 编排层裁决 | SAD 落点 |
|---|------|-----------|---------|
| Q1 | AC-E4：是否改 PRD 指标 / `MAX_WORKERS` | **均不改**；删错误论证（P95 当均值），命中率 ≥90% 降为**设计目标 + `/healthz` 观测项**；保留"错误率 0 + P99 劣化 ≤20%"为可断言口径；P6c 实测 <84% 再走 PRD 流程 | §1.3 / §4.2 / §2.6 / ADR-003 |
| Q2 | 三条 CDP 标注漂移（`/stock/data` `/stock/basic_info` `/stock/f10`） | 分类 **B / B / A′** 与 PRD §7.2 一致，确认；**同步权归编排层**；SAD **删除**"不改既有 `feeds[]` 字段与含义"；`feeds[].status` 属**改既有字段取值**，须批准 | §2.6 / §3 / 下方"契约同步项" |
| Q3 | feed 缓存 TTL 改 L3 | **确认，本次必做**：盘中 30s / 非盘中 180s；5 点副作用见 §2.1 D4 | §2.1 D4 / §3 server.py 行 |
| Q4 | `MAX_GROUPS` / `STREAM_QUEUE_BYTES_BUDGET` 取值 | 落 env：`MAX_GROUPS=200`（CPU 护栏）、`STREAM_QUEUE_BYTES_BUDGET=128MB`（内存护栏） | §2.2 R-2 / §4.3 |
| Q5 | announcement 域 tier | **L3（盘中 30s / 非盘中 180s）**；删除裸 `ttl=15`、pool 60s 两值 | §2.1 / §3 stock_api 行 |
| Q6 | AC-S3 模式 B 的 P95 口径 | **v1.5 重标（PRD v0.5 裁决）**：目标由「≤3s」改为**高请求密度 ≤5s / 低请求密度 ≤10s**（前提：探测阶梯**封顶 5s** + `NEG_TTL=5s`）。由 §2.3 D-1 论证可达：持续黑洞稳态 = 10s 周期、慢占比 ≈50% ⇒ 高密度 P95≈5s、低密度退化为周期上界 ≈10s；**封顶值 / `NEG_TTL` 任一分量变动必须连带重标本 AC**；"6–10s 慢而未死"上游恢复延迟 ≤600s 为**已登记权衡**（§2.3 D-1 / AR-13） | §2.3 D-1 / §4.1 / AR-9 / AR-13 / §9.5 |
| **N1（v1.4 发现 → v1.5 关闭）** | **JSON 单体/面板/工具端点在"整体降级"时的状态码**（原冲突：实现 503 vs PRD AC-A5 的 200） | **已裁决（关闭）：维持 HTTP 200 + error 客体**——「原来旧版本怎么返回就怎么返回，因为已经有业务系统在使用旧版本接口」⇒ 与 PRD AC-A5 一致（PRD v0.5 已固化"503 仅准入拒绝与 `/healthz`"）。**代码落地**：`_json_payload_has_data` 已删、`_send_json_shape` 恒 200；`http_503_total` 计数点 4→3。**§8 A5 由 ⚠️ 改 ✅；AR-12 关闭** | §2.4 / §3.1 关闭登记 / §8 A5 / §9.5 |
| **N2（新，P7b 发现）** | **SSE 帧 `items` 由稀疏变稠密**（缺数据从"缺席"改为 `null` + `missing`），属语义补全但会改变既有客户端的遍历假设 | 归入 🟠 STABLE「只增」的边界情形：**建议按"只增"处理**（既有键类型/含义未变；`missing` 明示"本来就没有值"），但须与 N1 一同记入变更日志，并同步**流端口 API 文档**（`/stream/quote/<sid>` 的帧 schema 目前无正式对外文档） | §2.5 C-5 / §3.1 例外 3 |

**CDP 标注契约同步项（Q2）——⚠️ 状态更正：health 负载 + 首页 CDP 列已在代码落地，仅 `API.md` 待同步**

| 端点 | 原现状（代码位置） | 目标值（分类） | v1.4 实测状态 |
|------|-----------------|---------------|--------------|
| `/stock/data` | health 负载 `requires_chrome_cdp` + 首页 CDP 列 | `configured`（**B**） | ✅ 已落地（`_base_feed_entries` = `configured`；首页 `needs_cdp=False`） |
| `/stock/basic_info` | API.md 与 health 双错 | `configured`（**B**） | ✅ health 负载 + 首页已落地（`configured` / `needs_cdp=False`）；**`API.md` 仍写"⚡ 需要 Chrome CDP" ⇒ 待同步** |
| `/stock/f10` | health `configured` + 首页 `needs_cdp=False` | CDP（**A′**） | ✅ 已落地（health = `requires_chrome_cdp`；首页 `needs_cdp=True`）；API.md 原本即"是" ✓ |

> **结论**：Q2 的**代码侧已闭环**，剩余为 `API.md`（`/stock/basic_info` 的 CDP 标注）与变更日志——属编排层动作，不在本 SAD 范围。

> **新增对外行为变更登记（修 P2-N7）**：`POST /stream/subscriptions`（流端口 **8054**，`stream.py:395`）新增组数上限 `MAX_GROUPS=200`，**超限返回 400** `{"error": ...}`。现状**无组数上限**（该端点永不返回 400），故此变更在 🟠 STABLE 端上**新增一种失败模式**，属对外行为变更——须由编排层记入变更日志并同步流端口 API 文档（SAD 只输出目标行为、不改契约），§3.1「不增删路径、不改方法」由此获得**显式例外**。

### 7.2 架构风险登记（本次设计引入或未完全消除）

| # | 风险 | 等级 | 缓解 |
|---|------|------|------|
| AR-1 | **SSE tick 内 `_active_codes()`（可达 2000）全量刷新超 tick 预算**（40 chunk；按订阅字段串行计可达 6000 次取数） | 高 | **针对 `_active_codes()`**：§2.2 R-6 分片轮转（每 tick 只刷 `\|slice\| ≤ coverage_codes` 的切片 ⇒ ≤23 取数 ≤ `coverage = 23`，其余读终点缓存）；`stream_refresh_lag_ticks` 可观测；tick 预算 0.8×tick + degraded。**v1.4 数字更正**：`coverage` 由 `≈170` 重标定为 **23**（`_PER_FETCH_EST` 0.3→2.2 实测校准），`coverage_codes` 由 `≈56` 变为 **23/11/7**（1/2/3 域，按订阅字段），故 200 码 × 3 域的 lag ≈ 29 tick ≈ 232s（盘中）——**这是容量模型的预期行为，不是缺陷**。**帧完整性口径（修 P2-N2，v1.4 补 last-known）**：warm 码不降级；冷码以 `null` 出现在帧内 `missing` 中（不再"缺席"），≤lag tick 内首次取到数据；AC-A1 以 warm 稳态 + 200 帧窗口为前提。（原"池上限=200"缓解对准 prefetch 池、对 `_active_codes()` 无效；原"≤coverage≈213 切片"单位错误，均已在 P1-1/P1-N1 改） |
| AR-2 | 命中率 ≥90% 仅为 SAD 设计目标，PRD 未列为验收项 | 中 | 纳入 `/healthz` `cache_hit_ratio` 观测项（**非 AC**）；P6c 作为主指标之一；<84% 时走 PRD 修订 |
| AR-3 | 负缓存半开探测的"恢复感知延迟"与探测误判 | 中 | ADR-003 论证：`NEG_TTL=5s`（守 PRD ≤5s）、探测预算 `_probe_budget` **阶梯 2→4→5 封顶**（**v1.5：`_PROBE_BUDGET_CAP=5.0`**；v1.4 起不再是恒定 2s）+ `_HISTORY_AGE=600s` 老化；`negative_cache_size`/`fail_count` 可观测；`NEG_TTL`/`PROBE_TIMEOUT` env 可调（`_HISTORY_AGE` / `_PROBE_BUDGET_CAP` 不可，见 AR-13） |
| AR-4 | `_run_batch` 返回值改 `(results, errors)` 是**内部签名破坏性变更** | 中 | 全仓 grep 调用点 + 存量用例回归；errors 缺失时组装点容忍空 dict。**v1.4 边界澄清**：该二元组只存在于**管道层内部**，对外的 handler 签名与响应形状未变（§2.4 职责边界） |
| AR-5 | Chrome ≈750MB + 进程内 ≈268MB 在 2C2G 上余量薄 | 中 | `MAX_GROUPS`(CPU) / 队列字节预算(内存) / CDP 页面数三者联动；`cache_max` 独立 LRU；AC-S9 24h 采样 |
| AR-6 | **TTL / prefetch 间隔收紧导致上游请求量上升**（修 P2-N3 + P3b 评审校正**幻影数据**）：① feed 300s→30s（盘中）⇒ 5 源请求量 ×10；② prefetch 有效间隔（现状代码 = `max(常量, tier 基值)`）→ 目标（`cache_policy(d)['pool_refresh']`），逐域：**fundflow `max(25, L1=8)=25`→8（×3.1）、timeline `max(30,8)=30`→8（×3.8）、announcement `max(60, L4=300)=300`→30（**×10**，且 tier **L4→L3**）、f10 `max(60, L4=300)=300`→300（**无变化**）**；**`basic_info 120→8（×15）` 为幻影，已删除**——无 basic_info prefetch loop，`_BASIC_INFO_POOL_REFRESH` 是**死常量**（无任何 import/引用，随常量删除） | 中 | 上游为行情/新闻站，量级可承受；URL 缓存同域 L3 限流；负缓存挡故障期；**新增每域 fetch 计数 `upstream_fetch_total{domain}` 入 metrics**（Q3⑤），P6c 以该计数核对"上游负载增幅 ≤ 可接受阈值"。**v1.4 方向的抵消项**：§2.2 R-6 改为**按订阅字段刷新**（ADR-015）后，SSE 侧的上游成本只与"实际被订阅的域"成正比——quote-only 组从 3×降到 1×，故上表的 ×3.1/×3.8 只对**三域全订**的组成立；单域组反而**下降**。P6c 应按 `upstream_fetch_total{domain}` 的**实测**分摊核对，不要用"订阅组数 × 3 域"外推 |
| AR-7 | `stream._refresh_pool` 若漏过滤 `_` 前缀键，会把 `_errors` 当股票塞进帧 | 中 | 列为详设必测项（契约陷阱点）；`_refresh_pool` 加单测断言 |
| AR-8 | 池上限升到 `MAX_DEDUP_CODES=2000` + `cache_max` 独立后，端点数据缓存内存需实测 | 中 | `cache_max` 独立 LRU + `cache_entries` 指标；§4.3 估算 ≈268MB（L1 为 3 域 + `_last_known`）；AC-S9 采样 |
| AR-9 | AC-S3 模式 B 的**分档 P95**（高密度 ≤5s / 低密度 ≤10s）依赖"探测预算封顶 5s + `NEG_TTL=5s` 稳态周期 + 请求密度"，绝对分位数需实测 | 中 | 封顶 5s 后稳态周期 = 10s、慢占比 ≈50% ⇒ 高密度 P95≈5s、低密度≈周期上界 10s（v1.5 重标）；需按 PRD AC-S3 **高/低密度两轮分别采集**（不得合并）；首次冷窗口一次/URL；**P6c 实测校准**（Q6 / 与 AR-13 同批） |
| AR-10 | 负缓存改造使存量用例 `test_fetch_json_leader_failure_does_not_stampede` 语义变更，与 PRD §9「51 用例全绿」冲突 | 中 | §3 tests 行**显式登记改写**；声明"**51 条基线中 1 条按新语义更新并通过，其余 50 条全绿**"（新语义断言：leader 失败后 follower 不触网、`err=8`、`max_active=1`，负缓存窗口内 <1ms 失败）；PRD §9 的"51 全绿"表述**待编排层同步**（P1-7） |
| **AR-11（v1.4 新）** | **单帧余量准入把"满配等价组"容量从 9 收到 8**：一个"9 个 200 码 × 3 域组"的订阅集合现在被 **400 拒绝**（`subscription frames would exceed …`）。而按**码**看，9×200 = 1800 ≤ `MAX_DEDUP_CODES=2000`、每组 200 ≤ `MAX_CODES_PER_SUB=200` ⇒ 客户端会认为"参数都合法却被拒" | 中 | ① 400 理由串**必须**给出 `STREAM_QUEUE_BYTES_BUDGET` 具体值（已如此），便于客户端自证预算；② 这是 `MAX_GROUPS`/码上限之外的**第三条**建组失败轴 ⇒ 与 N1/N2 同批记入变更日志；③ 若运维调大 `STREAM_QUEUE_BYTES_BUDGET`，容量按 `floor(B/F_max) − 1` **自动**重算（无硬编码常数）；④ 该风险**不可通过调 `MAX_GROUPS` 缓解**（`MAX_GROUPS` 是 CPU 护栏） |
| **AR-12（v1.4 新 → v1.5 关闭）** | ~~降级状态码与 PRD AC-A5 冲突未裁决~~（§2.4 / §7.1 N1） | ~~高（裁决阻塞）~~ **已关闭** | **N1 裁决落地**：业务降级维持 **200**（§2.4 逐格一致）、代码回退已落地（`_json_payload_has_data` 删除、`_send_json_shape` 恒 200）、PRD v0.5 已同步、§8 A5 改 ✅ ⇒ **文档-代码静默分叉消除，测试基线不再阻塞**。残留动作（非阻塞）：AC-A5 回归**须含"业务降级不得返回 503"断言**（§9.5 遗留 1） |
| **AR-13（v1.4 新 → v1.5 更新）** | **`_PROBE_BUDGET_CAP=5.0` 与 `_HISTORY_AGE=600s` 同为 AC-S3 分档 P95 的隐含参数**：封顶值决定稳态档位（5s ⇒ 高密度 P95≈5s；调大到 ~10s 会把慢占比推到 67% ⇒ P95≈10s、直接违反分档）；老化窗口决定"慢而未死（需 6–10s）"上游的恢复延迟上界（≈600s）。**任一分量与 `NEG_TTL` 变动必须连带重标 AC-S3 分档** | 中 | ① `_PROBE_BUDGET_CAP`/`_HISTORY_AGE` 均为 **cache.py 的机制常量**（不经 env），改动须走代码变更 + **重跑 AC-S3 模式 B 校准**（与 `NEG_TTL`/`PROBE_TIMEOUT` 的性质不同——后两者 env 可调且 `config.md` 要求覆盖后重跑校准）；② 量化依据见 §2.3 D-1 推导与 §4.1；③ "慢而未死"上游的出现频度与高/低密度两档 P95 **待 P6c 实测**（Q6）；④ **不缓解项**：不靠调小 `_HISTORY_AGE` 来"加速恢复"——那会把 10s 全预算探测变成常驻高频事件，直接违反分档 P95 |

### 7.3 设计假设（变更即需重评架构）

1. **上游库模式不变**：`fetch_json` 仍是唯一取数入口，读多写少、无外部存储（违反 → 缓存分层设计失效）。
2. **部署拓扑不变**：单进程、主/流双端口、单机 2C2G、无多副本（违反 → 内存中 `_groups`/缓存/负缓存无法跨副本共享，需重新设计）。
3. **单进程时钟单调性**：帧时序断言（A1/A2）依赖进程内单调时钟（PRD 已排除时钟回拨）。
4. **SSE 语义不变**：全量快照帧、丢旧保新、不做增量 diff；**同组帧对象共享同一引用**（违反 → §4.2 distinct 帧计费与 §2.5 帧共享失效）。
5. **`MAX_CODES_PER_SUB=200` 为单组上限、`MAX_DEDUP_CODES=2000` 为活跃码总上界**；**去重池跨组共享**（违反 → §4.3 池上限推导失效）。
6. **覆盖条件 C1（修 P1-N1；v1.4 按实现重标定）**：`_refresh_pool` 对**存活组订阅字段并集**（按 `_FIELD_HANDLERS` 顺序）串行取数，单周期取数能力 `coverage = 23 取数次数/周期`（`coverage_codes = 23 / 11 / 7`，1/2/3 域；见 §2.1 INV-1b），**单位是取数次数而非码**，且**每码成本 = `_fetches_per_code(fields)`（不再是常数 3）**。**"典型 1-2 组 × ≤200 码"并不满足 C1**（200 码 × 3 域 ⇒ 600 取数 ≫ 23）⇒ **默认场景即走 §2.2 R-6 分片轮转**，池内陈旧度 ≤ `ceil(N_active/coverage_codes)×L1`（3 域 200 码 ⇒ lag=29 ≈ 232s）。**AC-A3 的 L1×(1+抖动) 口径仅对 C1 成立的码保证**；violation 由 `stream_refresh_lag_ticks` 暴露。**帧完整性**（AC-A1）以 warm 码 + 200 帧窗口为前提，冷码以 `null` 出现在 `missing` 中并在 ≤lag tick 内进入（修 P2-N2；v1.4 补 last-known/stale）。
7. **编码是域的确定属性**：同一 URL 不会以两种编码出现（违反 → `fetch_json` 缓存键需含 `encoding`，见 §2.3 D-5）。
8. **股票代码拼写可归一（v1.4 新，ADR-017）**：任意入口的码都经 `config.canonical_code` 折叠为**小写交易所前缀**（`sh600519`/`sz000001`/`bj430047`），且**响应键回写客户端原拼写**（`_rekey_batch_response`）。下游所有键位（去重池 / 终点缓存 / URL 缓存 / `_fail_ledger` / CDP `SecuCode` 比对）**只认 canonical 形**。违反后果：同一股票铸出多个身份 ⇒ 去重与冷却账失效、上游取数翻倍、CDP 精确比对接不上（P1-6 根因）。**边界**：非法码值在**批量 HTTP 路径**是逐码 `null`（不是 400）；在**流端口建组/改组**是 400（入参校验）。
9. **`_last_known` 的上界依赖"每 tick 按存活码池剪枝"（v1.4 新）**：结转表在 `_push_once` 每轮按 `codes` 重建，无活跃组时整表清空。违反（例如改成"只在码离开时删除"）⇒ 该表无界增长，且会把已不在池中的码的旧值继续喂回帧（对象引用被永久钉住，内存不随订阅收缩回收）。

---

## 8. 追溯矩阵（设计点 → R → AC）

| 设计点（§） | 覆盖 R | 覆盖 AC |
|-----------|--------|---------|
| 2.1 `cache_policy` 单一权威 + INV-1a/1b | R16/R12 | A3/A4/E6/E9 |
| 2.1 四层断崖收敛（D1-D5，含 feed 层、longhu 域、编码） | R12/R16/R15 | A3/A8/E9 |
| 2.1/2.2 池成员与数据缓存解耦 + 覆盖条件 C1 | R11/R12/R7 | A3/A7/E6 |
| 2.2 inflight 显式上界 + 立即 503 | R2 | E8/S5 |
| 2.2 组数上限（CPU）/ 队列字节预算（内存）/ 内存总账 | R7 | E7/E5/S9 |
| 2.2 **distinct 帧引用计数计费（P0-1）+ `refs` 加锁与生命周期排空（P1-N2）** | R7 | E5/E7/A2 |
| 2.2 **分片轮转刷新针对性约束 `_active_codes()`（R-6/AR-1）；切片按取数次数计量 `\|slice\| ≤ coverage_codes`（P1-N1；v1.4 重标定为 23/11/7，按订阅字段）** | R7/R8 | A3/E5/S10 |
| **2.2 单帧余量准入 `Σ F_g + max F_g ≤ B`（v1.4，S2-2/P1-4；`stream_frame_bytes` 单一来源）** | R7 | E5/E7/A2/A7 |
| **2.2 按订阅字段刷新 `_subscribed_fields`/`_active_targets`（v1.4，ADR-015；P1-6 同锁读 codes+fields）** | R12/R7 | A1/A3/E5 |
| 2.2 LRU 真实化 + 双触发清扫 | R3/R11 | E6/E9 |
| 2.2 管理体 5s 预算 | R6/R17 | S7 |
| 2.3 负缓存 + **五段式 fetch_json**（正缓存 → **deadline 闸门** → 负缓存门禁 → leader → follower）+ **探测预算阶梯 2→4→5 封顶 + `_HISTORY_AGE` 老化（P1-2/v1.5）** | R9/R10 | S3 |
| 2.3 期限贯通（取数器 + **`fetch_json(deadline=)`** + 分块预算 + `_LOCAL_BUDGET` 不入冷却账） | R13 | E2/S7 |
| 2.3 超时矩阵（含 31s→5s、阶梯探测、follower 等待余量） | R6/R13/R17 | S7/S8 |
| 2.3 **D-6 共享失败状态层：URL 负缓存 + 码级冷却（P1-5；v1.4 4 元条目 + 本地预算不入账）** | R9/R14 | S6/S10/A10 |
| 2.3 CDP 三分降级（形状优先）+ **D-5 longhu GBK 编码（P1-4）** + **D-4 补充 2（v1.4：`page_data`/窗口终态/`_last_data` 老化/导航锁限时）** | R18/R19/R15 | S4/S1/E9 |
| 2.4 保留键契约 + 值域三分 + 单一组装点 | R4/R14 | A9/A10/S6 |
| 2.4 `_guard(shape)` 统一异常边界（**14 分支，shape 由路由表派生**） | R1/R18 | S1/S4/A5 |
| **2.4 降级状态码：全部业务端点（含单体/面板/工具）降级恒 200 + error 客体；503 仅准入拒绝与 `/healthz`（v1.5 N1 关闭）** | R1/R14 | **A5**/S10 |
| **2.4 入参归一化 `_parse_stock_codes` + 键回写 `_rekey_batch_response`（v1.4，ADR-017）** | R14 | A6/A10 |
| 2.5 不可变组状态 + 快照广播 | R5 | S2/A1/A2/E5 |
| **2.5 C-5 SSE 帧契约（v1.4：全码在位 + `missing`/`stale`/`errors`；🟠 STABLE 只增）** | R14（帧侧） | A1/A2/E5/E7 |
| 2.5 慢客户端隔离（队列 + 字节预算 + 摘除） | R7 | E7/A2 |
| 2.6 metrics.py + healthz 改造（**有界准入 + `_HealthBatch` 生命周期，P1-3/P1-1；`snapshot()` 零值恒定 + 锁内浅拷贝/锁外深拷贝；503 三计数点**） | R2/R8/R19 | S8/S10/S5 |
| 2.6 tick 预算基准修正 + **整 tick 网格滑移 + 异常退避 + tick 单次计算下传（v1.4）** | R8 | S10/E5 |
| **3.x 股票代码归一化单一权威 `config.canonical_code`（v1.4，ADR-017；server/stream/stock_api/cdp_engine 四模块接入）** | R14（身份）/P1-6 | A6/A7/S4 |
| 3.1 断线重连语义**不改动**（断言依据：`_register_conn` + 全量快照 + `STREAM_GROUP_IDLE_TTL`） | — | S11 |
| 3.x 取数统一走 fetch_json（longhu，L4/GBK） | R15 | E9 |
| 3.x CDP 守护盘中避让 + 窗口状态（`server.py:881`） | R19/R20 | S4/S9/S10 |

**AC 覆盖核对（逐条状态，修正原「30/30 一刀切」的失实声明）**

| AC | 状态 | 设计落点 / 说明 |
|----|------|----------------|
| E1/E2/E3 | ✅ | §4.1 延迟分解；取数器 deadline 贯通 |
| E4 | ⚠️ | §4.2（Q1）：可断言口径 = 错误率 0 + P99 劣化 ≤20%；命中率 ≥90% **为观测项非 AC**，待 P6c 校准 |
| E5 | ✅ | §4.2 distinct 帧共享 + 入队 ≤1s |
| E6 | ✅ | §2.2 LRU + 双触发清扫 + 上限 |
| E7 | ✅ | §2.2/§4.2 **distinct 帧 × 深度字节预算**（原 P0-1 已修） |
| E8 | ✅ | §2.2 inflight=40 + 立即 503；**流端口显式 `max_inflight=MAX_STREAM_CONNS+10=110`**（v1.4，否则 100 连接上限被主端口默认 40 掩盖） |
| E9 | ✅ | §2.1 `longhu` 域（L4≥300s）+ §2.3 D-5 GBK 编码 + 计数口径（原 P1-4 已修） |
| A1 | ✅ | §2.5 C-5 帧契约（**v1.4：items 覆盖全部订阅码**；warm 码含 last-known 结转不降级；冷码以 `null` 现于 `missing`）+ 帧对象同组共享 + 200 帧窗口前提 |
| A2 | ✅ | §2.2 丢旧保新 + 预算"不丢最新" + 单帧余量准入（v1.4） |
| A3 | ⚠️ | §2.1 INV-1b 明确**条件 C1**（`_fetches_per_code(fields) × N_active ≤ coverage = 23 取数次数/周期` ⇔ `N_active ≤ coverage_codes` = **23/11/7**（1/2/3 域））；**典型 1-2 组 × ≤200 码即不满足 C1**，走 §2.2 R-6 分片轮转（`stream_refresh_lag_ticks` 3 域 200 码 ≈ 29 tick ≈ 232s）（P1-1/P1-N1/v1.4 已修，仍待实测） |
| A4 | ✅ | §2.3 负缓存 + 过期=拒读+回源一次（**v1.4：条目过期只失效门禁、保留作失败历史**；`deadline` 本地耗尽不写负缓存） |
| A5 | ✅ | §2.4 错误客体/值域边界 + `/cls/hotplate` 分区口径（P2-3② 已统一）；**v1.5 N1 关闭：业务降级恒 200 + error 客体，与 AC-A5 逐格一致**（§7.1 N1）；真实 503 仅准入拒绝与 `/healthz` ⇒ 本条**可作为测试基线**，回归须含"业务降级不得返回 503"断言 |
| A6 | ✅ | §2.3 D-2 分块保序 + `_run_batch` 保一对一 + **`_process_chunk` 归一化后按原拼写回写（v1.4，别名不丢、重复拼写不重复回源）** |
| A7 | ✅ | §2.2 组上限 400 + 码池上限；**v1.4 新增第三条失败轴：单帧余量准入（帧预算 400，§4.3 / AR-11）** |
| A8 | ⚠️ | §2.1 D4/Q3：TTL 30s（盘中）/180s（非盘中），测试口径同步；落点 `cache.feed_cache_get/put` + `server._get_or_fetch_feed`（双检） |
| A9 | ✅ | §2.4 `_truncated`/`_dropped_count` |
| A10 | ✅ | §2.4 `_errors` + 值域三分；**v1.4：SSE 帧侧同一语义以 `errors` 承载（C-5），值域加 `tick_budget_exceeded`** |
| S1 | ✅ | §2.4 `_guard` 覆盖 **14** 分支（**shape 由 `_JSON_SHAPES` 表派生 + import 期集合断言**，避免再次漏数） |
| S2 | ✅ | §2.5 不可变组状态 + 锁外帧构建 |
| S3 | ⚠️ | §2.3 D-1 **探测预算阶梯 2→4→5（`_PROBE_BUDGET_CAP=5.0` 封顶）+ `_HISTORY_AGE=600s` 老化**（模式 A/B 分别断言；模式 B 按**高/低密度两轮**采集）；分档 P95（高密度 ≤5s / 低密度 ≤10s）由"稳态 10s 周期、慢占比 ≈50%"论证可达，绝对分位数待 P6c 校准（Q6 / AR-13）；**6–10s"慢而未死"上游恢复延迟 ≤600s 为已登记权衡** |
| S4 | ⚠️ | §2.3 D-4 三分（B/B/A′）+ **D-4 补充 2（v1.4：`page_data`/窗口终态/`_last_data` 老化/导航锁限时）**；**health 负载 + 首页 CDP 列已在代码落地**，仅 `API.md`（`/stock/basic_info`）待同步 |
| S5 | ✅ | §2.2 503 + 撤除后恢复 |
| S6 | ✅ | §2.3 D-6 码级冷却 120s（**4 元条目**），批量与 prefetch 共用（P1-5 已修）；**v1.4：仅"真实上游失败"入账——本地预算耗尽（`_LOCAL_BUDGET`）不计（ADR-014 v1.4 反转）** |
| S7 | ✅ | §2.3 D-3 超时矩阵（31s→5s；**v1.4 补阶梯探测、follower 等待余量、端到端 `deadline`**） |
| S8 | ✅ | §2.6 专用执行器 + **有界准入**（stale 可达可测，P1-3 已修）+ **`_HealthBatch` 准入位恰好释放一次、在飞 ≤25**（v1.4） |
| S9 | ✅ | §4.3 资源上界表 + 进程内存 ≈268MB（L1=3 域 + `_last_known`，修 P2-N5/v1.4） |
| S10 | ✅ | §2.6 计分板（**冷却清单**可枚举、healthz 精确 schema，P2-6 已补）；**v1.4 补：`http_503_total` 计数点、`snapshot()` 零值恒定发布、`code_cooldown_list` 发布节流；v1.5 该计数点由四收敛为三** |
| S11 | ✅ | **不改动 + 断言依据**（§3.1）：`_register_conn` 重连 + `push_loop` 下一 tick 全量快照 + `STREAM_GROUP_IDLE_TTL=300s` |

**覆盖声明**：30 条 AC 全部有设计落点（E7/E9/S6/S11 的原缺口已补齐，见上表）；其中 **5 条标注 ⚠️**：E4（命中率降为观测项，Q1）、A3（条件 C1 不成立时降级，P1-1）、A8（TTL 口径同步，Q3）、S3（模式 B 分档 P95 待 P6c 校准，Q6）、S4（CDP 契约同步：代码已落地、`API.md` 待同步，Q2）。**v1.5：A5 由 ⚠️ 改 ✅**（N1 裁决关闭——业务降级恒 200，与 AC-A5 逐格一致；§7.1 N1）。**测试方法与阈值**由 task-decomposer→tester 阶段落实，本 SAD 保证"机制存在且可断言"。**v1.4 的"A5 裁决未落地前不得进入基线"前置约束已随 N1 关闭解除**；AC-A5 回归**须含"业务降级不得返回 503"断言**（§9.5 遗留 1）。

---

## 9. 修订摘要

> ⚠️ **§9.1-§9.3 是历史修订记录**（分别落地 REV-ARCH / 二轮复审 / P3b 详设评审的 SAD 侧动作），其中若干**数字口径已被后续实测或裁决推翻**（最典型：`coverage≈170` / `coverage_codes≈56` / "恒定 2s 探测" / "探测阶梯升到 10s" / "降级 503" / "`_LOCAL_BUDGET` 反转未确认"）。**§9.4（v1.4，P7b 契约同步）与 §9.5（v1.5，裁决落地收尾同步）是最新且唯一的现行口径**；两者冲突时以 **§9.5 为准**（§9.5 覆盖 §9.4 的三处表述：§2.4 降级状态码、§2.3 探测阶梯封顶、ADR-014 反转的"已确认"状态）。

### 9.1 v1.1（依据 REV-ARCH-20260915-001）

| 项 | 问题 | 修订落点 |
|----|------|---------|
| **P0-1** | 队列字节计费（每次入队累加）与帧共享互斥 → 预算按构造必超、每 tick 丢帧 | §2.2 R-2 / §4.2「帧共享与字节计费」/ ADR-013：改 **distinct 帧 × 深度**（引用计数计一次），给出推导式（B=128MB ≥ 8×F_max）、确定性丢弃、组数=CPU 护栏 vs 预算=内存护栏 |
| **P1-1** | L1 池 500→200 与 `MAX_DEDUP_CODES=2000` 不自洽；AR-1 缓解对准错误对象 | §2.1 INV-1b（条件 C1）/ §2.1 三层缓存表（池/缓存解耦）/ §4.3 推导 / §2.2 R-6（分片轮转约束 `_active_codes()`） |
| **P1-2** | 模式 B P95≤3s 不成立（NEG_TTL 5s < REQUEST_TIMEOUT 10s） | §2.3 D-1（**半开探测 `PROBE_TIMEOUT=2s`** + 慢占比推导）/ ADR-003 / §4.1 / Q6 |
| **P1-3** | healthz `submit()` 永不失败 → stale 死代码、队列无界 | §2.6（`BoundedSemaphore(MAX_HEALTH_INFLIGHT=5)` 有界准入）+ ADR-006 / §3 server.py 行 |
| **P1-4** | `fetch_json` 硬编码 utf-8（longhu GBK 不可实现）+ 缺 `longhu` 域 | §2.3 D-5（`encoding` 形参）+ §2.1 `DOMAIN_MATRIX.add('longhu')` + ADR-001 |
| **P1-5** | `_FAIL_COOLDOWN` 仅在 prefetch 循环，批量路径无冷却 → AC-S6 过不了 | §2.3 D-6（共享 `_fail_ledger`，批量+prefetch 共用，码级 120s）+ ADR-014 + §3 stock_api 行 |
| **P1-6** | 端点计数 13 实为 14（三处） | §1.1 / §1.2 R1 / §2.4 / §3 / ADR-007：统一 **14** 并逐一列名 |
| **P1-7** | 负缓存改造使存量用例失败未登记 | §3 tests 行**显式登记改写** + AR-10；新不变量可断言 |
| **Q1** | AC-E4 改为均值口径、命中率降为观测项 | §1.3 / §4.2 / §2.6 / §7.1 |
| **Q2** | 删「不改 feeds[]」；声明 `feeds[].status` 属改取值；列 3 同步点 | §2.6 / §7.1「契约同步项」/ §3.1 |
| **Q3** | feed TTL 改 L3（30s/180s）必做 + 5 点副作用 | §2.1 D4 / §3 config+server 行 / AR-6 |
| **P2-3** | 两处自相矛盾（feeds[] / hotplate 形态） | §2.6 删除 + §2.3 D-4 唯一口径 + ADR-007 |
| AC 缺口 | E7/E9/S6/S11 无落点；E4/A3/S4/S8/S10 部分 | §8 逐条状态表（S11 = 不改动+断言依据；其余均有落点） |
| 同轮 P2 | P2-1 线程总账、P2-2 watchdog 归属、P2-4 调用顺序、P2-5 stagger/Q5、P2-6 schema、P2-7 tech-stack | §4.3 / §3 / §2.4 / §2.1 / §2.6 / tech-stack.json |

### 9.2 v1.2（依据第二轮复审：机制层 P0×1 + P1×7 已全部合格，仅收口 2 项 P1 + 7 项 P2）

> 复审结论「❌ 仍阻断」但**机制层无返工**，Q1/Q2/Q3 逐字落地、§8 属实。本轮为**收口轮**：只改本文件（+ tech-stack.json 版本号），不改代码/PRD，不重写任何机制。

| 项 | 问题 | 修订落点（本轮） |
|----|------|-----------------|
| **P1-N1** | coverage 漏掉 `_refresh_pool`（`stream.py:137-138`）对 `_FIELD_HANDLERS` **3 字段串行**维度：`8×8/0.3=213` 的单位是**取数次数**而非**码**，实为 ≈71 码/周期；导致 §7.3#6 「1-2 组×≤200 码 满足 C1」失实、§8 A3 前提失准（典型即降级）、R-6 切片=213 码 ⇒ 639 取数≈24s 违反 `tick ≤0.8×tick` | **coverage 单位明确为「取数次数/周期」**，并按 AC-E5/S10 的 0.8×tick 收紧为 `≈170 取数次数/周期 ⇔ ≈56 码/周期`（213/71 保留为**绝对理论上界**，因占满整 tick 不作调度依据）；**C1 改写为 `len(_FIELD_HANDLERS) × N_active ≤ coverage`**。五处同步：**§2.1 INV-1b**（含公式块）/ **§2.2 R-6**（切片 `\|slice\| ≤ 56`，标注 71/213 两种错法均违约）/ **§4.3**（池自洽推导）/ **§7.3#6**（典型场景即降级，陈旧度 ≈4×L1）/ **§8 A3**；另同步 §7.2 AR-1、§2.2「不选其他」（评估并否决"3 字段并发"备选：在飞取数 24 违反 AC-E8） |
| **P1-N2** | `_Frame{payload,refs}` ① `refs` 被 push_loop 与各 handler 线程并发读改写、无同步原语（CPython `refs+=1` 非原子）⇒ `stream_queue_bytes` 漂移而它是丢弃判据**唯一输入**；② 连接摘除/`destroy_group`/`None` 哨兵路径**不归还**残留帧 refs ⇒ 字节单调泄漏、预算永久占用 ⇒ 后续 tick 无条件丢帧（P0-1 的后果） | §4.2 新增「`_Frame.refs` 并发安全与生命周期收口」：① 新增 `_frame_bytes_lock`，**所有 `refs` 读改写与 `stream_queue_bytes` 增减在锁内**（临界区仅整数算术，不触碰 `_groups_lock`/`conns_lock` ⇒ 无锁序风险），给出 `_frame_acquire`/`_frame_release` 对称原语与可白断言不变式；② 新增 `_drain_conn_queue`，在 `_serve_sse` `finally` / `destroy_group` / `_release_conn` 三处**排空队列并逐帧 `refs−=1`**；③ **`None` 哨兵不计费**（不包 `_Frame`）。同步 **§2.5 C-3**（摘除必排空）/ **§3 stream.py 行** |
| **P2-N1** | healthz「精确 schema」漏既有 `feeds[]`/`cache_ttl`/`request_timeout`（与 🟠 STABLE + ADR-001 冲突） | §2.6 schema 补全：既有 4 键（`status`/`cache_ttl`/`request_timeout`/`feeds[]`，含 `?check=1` 的 `items`/`error`）一个不少，仅叠加 `stale`/`metrics`/`policy`/`cdp` |
| **P2-N2** | R-6 "帧完整性不降级"对**冷码**不成立 | §2.2 R-6 + §7.2 AR-1 + §7.3#6：改为 **warm 码不降级、冷码在 ≤lag tick 内进入**，AC-A1 以 warm 稳态 + 200 帧窗口为前提 |
| **P2-N3** | prefetch 间隔 25/30/120/60→8/8/8/300 的上游负载未登记 | §7.2 AR-6：逐域 before→after 登记（fundflow 25→8 ×3.1、timeline 30→8 ×3.8、basic_info 120→8 ×15、announcement 60→30 ×2、f10 60→300 ×0.2 下降），并指定 `upstream_fetch_total{domain}` 为 P6c 核对口径。**⚠️ v1.3 校正：`basic_info 120→8（×15）` 为幻影、`announcement` 实为 ×10、`f10` 无变化，见 §9.3** |
| **P2-N4** | `err=n` 与 `err=8` 表述不一致 | §3 tests 行统一为 **`err=8`**（leader 落负缓存后 7 个 follower 读负缓存直接 raise、不触网；`max_active=1`），与 AR-10 一致 |
| **P2-N5** | §4.3「4 域」实为 3 域（L1 = quote/fundflow/timeline） | §4.3：`4 域×2000×8KB≈64MB` → **`3 域×2000×8KB≈48MB`**；进程内 ≈283MB → **≈267MB**、合计 ≈1.03GB → **≈1.01GB**；同步 §7.2 AR-5/AR-8、§8 S9 |
| **P2-N6** | 帧计费钩子误挂 `cache.py`（违反 layerIsolation） | §3 cache.py 行删除"导出引用计数钩子"，改为**显式声明帧计费属 stream 层、cache.py 只做纯缓存/契约**；计费实现落点已归 §3 stream.py + §4.2（`_frame_bytes_lock`/`_drain_conn_queue`） |
| **P2-N7** | `MAX_GROUPS` 新增 400 契约变更未登记（🟠 STABLE 下须显式记录） | §7.1 新增「对外行为变更登记」：`POST /stream/subscriptions`（8054）新增 `MAX_GROUPS=200` → 超限 400，属**新增失败模式**，须编排层记变更日志 + 同步流端口 API 文档；§3.1「不增删路径/不改方法」标注**显式例外** |

**本轮版本**：SAD v1.1 → **v1.2**；`doc/arch/tech-stack.json` 同步 `version: 1.2`（内容不变——P2-N6 的层级归属本就由现有 `layerIsolation` 约束覆盖）。**约束保持**：Python 3 标准库零依赖、`layerIsolation`（cache.py 禁 import stream/server/stock_api/market_api）、文件结构（扁平包 + 唯一新增 `metrics.py`）均未放宽。

### 9.3 v1.3（依据 P3b 基础层三模块详设评审 REV-DES-20260915-001）

> 评审结论 **✅ 通过**（P0×0 / P1×1 / P2×8）。本轮为**详设回改轮**：只改本文件（+ `tech-stack.json` 版本号），不改详设/代码/PRD，不重写任何机制；落地 P3b 评审提出的 SAD 侧动作。

**一、SAD 内部矛盾更正（3 项）**

| # | 矛盾 | 更正落点 |
|---|------|---------|
| ① | feed LRU 机制落点原记 `server._get_or_fetch_feed`（与详设 §2.4 冲突） | §2.2 R-3 / §2.1 D4③ / §3 cache.py 行 + server.py 行：机制落 **`cache.feed_cache_get`/`feed_cache_put`**（LRU/双触发清扫/淘汰，守 `layerIsolation`）；server 只保留 `_feed_fetch_locks` per-path 防击穿并调用（miss → per-path lock → **二次 `feed_cache_get` 双检** → fetch → `feed_cache_put`） |
| ② | §4.3 负缓存"过期即清"与 §2.3 半开探测需失败历史冲突；"过期即清"⇒ 每轮 `10s+5s` ⇒ P95≈10s，**直接违反 AC-S3 模式 B** | §4.3 资源上界表：改「**门禁过期失效；条目保留作失败历史**」（仅"成功"或"满额淘汰最早 `until`"时清除） |
| ③ | §7.2 AR-6 负载增幅登记含**幻影数据** | §7.2 AR-6：改用**有效间隔** `max(常量, tier 基值)` 逐域登记（见下） |

AR-6 校正后（供 P6c 校准）：`fundflow max(25,8)=25→8（×3.1）` · `timeline max(30,8)=30→8（×3.8）` · `announcement max(60,300)=300→30（**×10**，tier **L4→L3**）` · `f10 max(60,300)=300→300（**无变化**）`；**删除 `basic_info 120→8（×15）`**——无 basic_info prefetch loop，`_BASIC_INFO_POOL_REFRESH` 为死常量。

**二、6 项详设裁决的 SAD 侧落地**

| # | 裁决 | 落地 |
|---|------|------|
| 1 | `cache_policy` 返回值 `'n/a'` → `None` | §2.1 示例 `cache_policy('longhu')` 的 `'cache_max'` 改 `null`；补注"矩阵单元格保留 `'n/a'`、返回值归一化 `None`" |
| 2 | 负缓存语义（门禁过期失效、条目保留作失败历史） | 同 ①-②（§4.3） |
| 3 | feed LRU 落点 | 同 ①（§2.2 R-3 / §2.1 D4③ / §3） |
| 4 | metrics 增 `key=` / `reset()` | §2.6 接口面：`incr(name, n=1, key=None)` / `set_gauge(name, value, key=None)` / `snapshot()` / `reset()`（测试辅助）；`key` 为标签记法唯一载体 |
| 5 | `cache_hit_ratio` 发布点 | §2.6 计分板：来源改 `cache._cache_put`（由本地 `_cache_stats{hit,miss}` 派生，不在请求热路径） |
| 6 | `STREAM_PING_INTERVAL` env 化 | §3 config.py 行 env 列表补 `STREAM_PING_INTERVAL`(默认 20) |

**三、SAD↔详设偏差回填（D-1~D-7，D-7 由详设修）**

| # | 偏差 | SAD 落点 |
|---|------|---------|
| D-1 | gap 分支兜底 `raise FetchError('upstream_error')` | §2.3 D-1 第 4 段补「follower 正/负缓存均未命中 → fail-closed（不触网）」 |
| D-2 | `_` 前缀码跳过 / data+error 冲突 / 未知 kind 归一 | §2.4 组装防御规则补 3 条 |
| D-3 | cache.py 允许 import 新增 `socket` | §2.3 D-1 补注（已在 allowlist，不破零依赖） |
| D-4 | `STREAM_PING_INTERVAL` env 化 | 同 二-6 / §3 config.py 行 |
| D-5 | 新增内部名 `_DOMAIN_ENCODING`；`DOMAIN_MATRIX` 运行期为 Python dict | §2.1 要点补充 / §3 config.py 行 |
| D-6 | metrics 注册表含 `upstream_fetch_total` | §2.6 计分板补列 `upstream_fetch_total{domain}` |
| D-7 | plate stagger（由详设修） | §2.1 plate stagger 表述明确"**明令保留，不得在 TTL 收敛时丢弃**"，由 `server.md` 承接派生 |

**四、SAD↔代码不一致更正（2 项）**

| # | 项 | 更正落点 |
|---|----|---------|
| 1 | `utils.py:12` `CACHE_TTL` 为**未使用 import**（原 SAD Q3②/§3/ADR-001 称其为消费者） | §2.1 D4② / §3 config.py 行 / ADR-001：改「消费者 = `cache.py` 默认 + `server._get_or_fetch_feed`；`utils.py:12` 未使用 import（随常量删）；`warm_jin10` 经 `fetch_json` 默认值」 |
| 2 | `_BASIC_INFO_POOL_REFRESH` 为**死常量**（全仓无引用 + 无 basic_info prefetch loop） | §1.2 R12 / §2.1 D2 / §7.2 AR-6：明确死常量 + 无 loop，删除无迁移 |

**本轮版本**：SAD v1.2 → **v1.3**；`doc/arch/tech-stack.json` 同步 `version: 1.3`（内容不变——D-3 的 `socket` 本就在 allowlist、feed 机制归属本就由 `layerIsolation` 约束覆盖）。**约束保持**：Python 3 标准库零依赖、`layerIsolation`（cache.py 禁 import stream/server/stock_api/market_api）、文件结构（扁平包 + 唯一新增 `metrics.py`）均未放宽。

---

### 9.4 v1.4（P7b 契约同步：以**代码为准**回写实现的最新行为）

> **性质**：本轮**不是设计轮**——机制全部已由前序轮次钉死并已实现。本轮只做一件事：**把实现跑出来的最新行为回写到 SAD，使文档与代码一致**。范围严格限定为 `doc/arch/SAD.md` + `doc/arch/tech-stack.json` 版本号与规则条目；**未改代码、未改详设、未改 PRD**。每一条都先读代码确认再改；**发现"任务描述与代码不符"的地方，一律以代码为准并在下表标注**（见"⚠️ 描述-代码不符"列）。
>
> 复核基线：`stream.py`(1301 行) / `config.py`(352) / `cache.py`(462) / `stock_api.py`(1212) / `cdp_engine.py`(1529) / `server.py`(1521) / `metrics.py`(185)。

**一、11 项必须同步的已知漂移（逐项：代码证据 → SAD 落点）**

| # | 项 | 代码证据（v1.4 实测） | SAD 落点 | ⚠️ 描述-代码不符 |
|---|----|---------------------|---------|-----------------|
| 1 | **SSE 刷新容量模型** | `_PER_FETCH_EST = 2.2`（`stream.py:74`）；`_FIELD_FETCH_CALLS={'quote':1,'fundflow':1,'timeline':1}`（`:83`，quote 第 2 相命中 7d `sector` 缓存 ⇒ 稳态 1）；`coverage = max(1,int(0.8×tick×8/2.2)) = 23`；`_fetches_per_code` ⇒ `coverage_codes` = **23/11/7**（1/2/3 域）；C1 = `_fetches_per_code(fields)×n ≤ coverage`（`:410`） | §2.1 INV-1b（公式块整体重写）/ §2.2 R-6 / §4.3 推导 / §7.3#6 / §8 AR-1·A3 / ADR-015 | 无（与描述一致）。**原 SAD `coverage≈170`/`coverage_codes≈56` 确为失准**：`_PER_FETCH_EST` 0.3→2.2 是 r3 部署实测校准，且每码成本由常数 3 改为按订阅字段 |
| 2 | **按订阅字段刷新** | `_subscribed_fields()`/`_active_targets()`（`:214`/`:235`，codes+fields **同一次加锁读**）；`_resolve_refresh_fields`（`:284`）；`_refresh_pool(fields=...)` | §2.2 R-6（新增 bullet）/ §2.1 INV-1b / §4.3 / §7.2 AR-6 / §8 / **ADR-015（新）** | 无。**原 SAD 的"无条件 3 域"确为旧行为**（`len(_FIELD_HANDLERS)=3` 被当常数计价） |
| 3 | **帧字节预算：单帧余量准入** | `create_group`：`projected + largest > B ⇒ 400`（`stream.py:903-907`）；`patch_group` 同（`:957-962`，`largest` 用 `exclude_sid` 重价）；`config.stream_frame_bytes()` 为尺寸单一来源（`config.py:62`） | §2.2 R-2（新 bullet）/ §4.2 推导式 / §4.3（新行"跨组 distinct 帧工作集"）/ ADR-013（补） | 无。**满配组容量 9→8 成立**：`F_max = 200×3×23KB = 13.8MB`，`(N+1)×F_max ≤ 128MB ⇒ N ≤ 8` |
| 4 | **帧契约变更** | `_build_frame`（`stream.py:458-518`）：`codes_total`/`fields`/`items`（**全码在位**）/`missing`/`missing_count` + 条件 `errors` + 条件 `stale`/`stale_count`；仅空 `codes` 返回 `None` | **§2.5 新增 C-5（帧契约专节）** / §2.6 计分板 / §8 / §3.1 例外 3 / §7.1 N2 / ADR-016（新） | 无 |
| 5 | **negative cache 语义：探测预算阶梯 + 老化** | `_probe_budget(fail_count)` 2→4→8→10（`cache.py:147-162`）；`_fetch_budget` 融合老化判定（`:165-175`，`_HISTORY_AGE=600`，`first_at`）；`_FOLLOWER_WAIT_MARGIN=1.0`（`:77`） | §2.3 D-1（整体重写 + 延迟推导重算）/ §2.3 D-3 矩阵 / §4.1 / §4.3 / ADR-003（补正）/ §7.1 Q6 / **AR-13（新）** | 无。**原"恒定 2s 探测"确为旧口径**；**且原 SAD 的"稳态 P95≤2s"在恒定 2s 下也不成立**（阶梯爬到顶即进 10s+5s 周期）——v1.4 用"老化把 10s 档停留封顶 600s"重新论证 |
| 6 | **`fetch_json` 新增 `deadline` 形参** | `fetch_json(url, headers=None, ttl=None, encoding='utf-8', deadline=None)`（`cache.py:242`）；超期闸门在**正缓存之后**（`:278`）；leader 内 `_effective_timeout` 再夹紧（`:312`）；`_fetch_rest_json` 明确**不**自设闸门（`stock_api.py:266-269`） | §2.3 D-1（段 2 新增）/ §2.3 D-2 / §2.3 D-3 矩阵 / ADR-009（补） | 无。**"闸门位于正缓存之后"与描述一致**（P1-5） |
| 7 | **新增 `config.canonical_code`** | `config.py:84-109`（+ `VALID_STOCK_CODE`/`_DOTTED_STOCK_CODE`）；消费方 4 处：`server._parse_stock_codes`、`stream.create_group/patch_group`、`stock_api._process_chunk`/`cached_batch`、`cdp_engine._same_code`/`navigate_stock` | §3 config/stream/stock_api/cdp_engine 行 / §3 依赖全图 / §2.4 统一调用顺序 / §4.3 / §6（tech-stack.json）/ §7.3#8 / §8 / **ADR-017（新）** | **是（描述不完整）**：任务只提到"模块变更矩阵与 layerIsolation 需反映"。实测它还**改变了响应契约的实现路径**（`_rekey_batch_response` 把 canonical 键回写为客户端原拼写；流端口非法码 = **400**，批量 HTTP 路径非法码仍是逐码 `null`）——两条边界都已写入 SAD |
| 8 | **CDP 降级语义（4 项）** | ① `page_data(page)` 总函数（`cdp_engine.py:103-119`）；② `full_chrome_restart` 的 `finally` 兜底终态（`:399-406`）+ `ensure_chrome` fail-closed（`:361-364`）；③ `get_data()` "时钟缺失=陈旧"（`:1147-1165`）+ `_fresh_secu_code_locked`（`:1269-1281`）；④ `_acquire_navigate_lock` 有界（`:1283-1296`） | §2.3 **D-4 补充 2（新表）** / §3 cdp_engine 行 / §8 S4 / ADR-005·012 引证 | 无。**"重启窗口异常兜底必达终态"与描述一致**（含 `ensure_chrome` 的 fork 压力路径） |
| 9 | **可观测性** | `snapshot()` 零值恒定（`_DEFAULTS`/`_KNOWN` + `assert`，`metrics.py:34-62`/`:170-172`）；锁内浅拷贝 + 锁外深拷贝（`:162-169`）；`http_503_total` **4 个计数点**（`server.py:1063`(healthz)/`:1175`(降级)/`:1363`(_reject_503)，`stream.py:1208`(连接上限)） | §2.6（形态 + 计分板整表重写）/ §8 S10 | 无。任务说"计数点补齐"——实测为 **4 点**（SAD 原只列 `_reject_503` 1 点） |
| 10 | **`_LOCAL_BUDGET` 不入 code 级冷却账本** | `_LOCAL_BUDGET='__local_budget__'`（`stock_api.py:81`，**非** `FetchError.KINDS` 成员）；`_process_chunk` 翻译为 `upstream_timeout` 且 `continue`（`:490-498`）；`_run_batch` 预算耗尽不建线程（`:390-394`） | §2.3 D-6（新增 bullet）/ §2.3 D-2 / ADR-014（**v1.4 反转登记**）/ §8 S6 | **是（描述与设计相反）**：任务只说"不计入冷却账本"，而**批 2 详设评审（REV-DES-15 建议②）曾正式决定"预算耗尽计入冷却账"**。二者冲突 ⇒ 这是**实现反转了评审裁决**。v1.4 显式登记反转理由（自激正反馈）与 AC-S6 口径限定（"真实上游失败"）。**若编排层认为应回到评审口径，需改代码而非改 SAD** |
| 11 | **tick 节拍：整 tick 网格 + 异常退避 + 单次计算** | `_tick_sleep_seconds`（`stream.py:755-775`，`k = floor(elapsed/tick)+1`）；`push_loop` 指数退避 `min(2^(n−1), 8)` tick（`:836-852`）；`_push_once` 算一次 `tick` 并传给 `_refresh_pool`（`:792`/`:801`）；空池在 `_push_once` 重置 lag gauge（`:809`） | §2.6 tick 观测与预算（整段重写）/ §8 / §3 stream 行 | 无。**"tick 单次计算后传递"与描述一致**（修 tier 翻转点的 8s vs 120s 分歧） |

**二、本轮额外发现（不在 11 项清单内，但属 SAD↔代码不一致）**

| # | 项 | 代码证据 | 严重度 | SAD 落点 |
|---|----|---------|-------|---------|
| **D-1** | **JSON 单体/面板/工具端点在"整体降级"时返回 503，与 PRD AC-A5 的"HTTP 200"逐字冲突** | `_json_payload_has_data(payload)`（`server.py:597-620`）+ `_send_json_shape` `status = 200 if _json_payload_has_data(payload) else 503`（`:1173`）；单测 `test_server_http.py:590-628` 已锁死 503；受影响 = 4 面板 + `/cls/hotplate` + `/cls/plate` + `/market/margin` | **高（裁决阻塞）** | §2.4 降级状态码表 / §3.1 例外 4 / **§7.1 N1（待裁决）** / §8 A5 标 ⚠️ / **AR-12（新）** |
| **D-2** | `DOMAIN_MATRIX` 中 `plate`/`margin` 的 `cache_max` 为 `'n/a'`（非 200/16） | `config.py:222`/`:227`；`test_config.py:107-112`（P2-9：URL 缓存独占域不设 per-domain cache_max） | 中 | §2.1 矩阵 + 更正说明 |
| **D-3** | `_fail_ledger` 条目为 **4 元** `[cnt, cooldown, kind, last_ts]`（原 SAD 写 2 元） | `stock_api.py:216`；老化判定用 `entry[3]`（`:183`/`:200`） | 中 | §2.3 D-6 / ADR-014 / §4.3 |
| **D-4** | **handler 返回的是"已组装 dict"**，不是 `(results, errors)`（后者仅存在于管道层） | `handle_cls_*(codes, deadline=None, dropped=0) -> dict` 内部调 `build_batch_response`（`stock_api.py:1020-1088`）；`server._handle_stock_batch` 只注入 `dropped`（`server.py:1145-1147`） | 中 | §2.4 职责边界 / §3 stock_api 行 / ADR-009 影响 |
| **D-5** | `BoundedThreadPoolServer` 新增 `max_inflight` 形参，**流端口显式 110** | `server.py:1341-1349`；`stream.make_stream_server` 传 `MAX_STREAM_CONNS+10`（`stream.py:1289-1292`） | 中 | §3 server 行 / §8 E8 |
| **D-6** | `healthz` 准入位由 **`_HealthBatch`** 在该批 future 全部结束后释放（**不是 `finally` 立即释放**） | `server.py:828-866`/`:974-979`；在飞上界 ≤25 | 中 | §2.6 / §4.3 / §8 S8 |
| **D-7** | **`feeds[].status` 三处修正 + 首页 CDP 列已在代码落地**（原 SAD 标"待编排层执行"） | `server.py:790-803`（`/stock/data`→`configured`、`/stock/basic_info`→`configured`、`/stock/f10`→`requires_chrome_cdp`）+ `:1289-1303`（首页 `needs_cdp`） | 低 | §7.1 CDP 标注同步项表（状态更正：仅 `API.md` 待同步） |
| **D-8** | `tech-stack.json` 的 `allowlist` **遗漏 `hashlib`/`html`/`xml`**（均来自 `utils.py`），`itertools` 无引用 | `utils.py:3`/`:7`/`:8`；全包 grep 无 `itertools` | 中（会造成 `check-arch-compliance.sh` 假阳性） | §6（v1.4 变更 1）+ **tech-stack.json 本体已补** |
| **D-9** | `upstream_fail_total{cdp_unavailable}` 由 `_raise_cdp_unavailable()` **单出口**计数（4 出口收口）；`market_api` 亦为 owner | `stock_api.py:986-989`；`market_api.py:65` | 低 | §2.6 计分板 / §3 行 |
| **D-10** | `/cls/hotplate`、`/cls/plate`、`/ths/longhu` 走**共享 `_fanout_executor`（≤3 并发）**，统一 `_FANOUT_WAIT_BUDGET=REQUEST_TIMEOUT` 兜底 | `server.py:695-750` | 低 | §4.1（状态更新为"已落地"、AC 归属更正为 E2） |

**三、ADR 动作**

| 动作 | ADR | 说明 |
|------|-----|------|
| **新增** | **ADR-015 按订阅字段刷新（中可逆）** | 3 选项（无条件 3 域 / 按订阅并集 / 按组分别刷）→ 选"按订阅并集 + codes/fields 同锁读"；核心理由是**避免容量模型被低估而错误降级**（比多付上游更糟） |
| **新增** | **ADR-016 SSE 帧完整性契约（低可逆）** | 4 选项（稀疏 items / 稠密 + 三元数据 / 增量 diff / 只稠密化）→ 选"稠密 + `missing`/`stale`/`errors` + last-known 结转"；把"一个含糊的缺席"拆成三个可行动状态 |
| **新增** | **ADR-017 `config.canonical_code` 单一权威（低可逆）** | 3 选项（各处就地正则 / 只归一化下游 / 单一权威函数 + 响应回写原拼写）→ 选 C；把"一个股票一个身份"变成 `canonical_code(canonical_code(x))==canonical_code(x)` 的可断言性质 |
| **补正** | ADR-001 / 003 / 009 / 013 / 014 | 001 补 `plate`/`margin` 的 `cache_max='n/a'`；003 决策改"阶梯 + 老化"并加长推导；009 补 `fetch_json(deadline=)` 与"闸门在正缓存后"；013 补单帧余量准入与容量 9→8；014 补 4 元条目 + **`_LOCAL_BUDGET` 不入账的反转登记** |
| **不新增** | tick 节拍（整 tick 网格 + 退避） | 按可逆性原则：改回 `_tick_sleep_seconds` 只需数行 ⇒ **高可逆 ⇒ 不记 ADR**，落 §2.6 叙述（已在 ADR 汇总行显式说明该判定） |

**四、tech-stack.json 动作**：`version: 1.3 → 1.4`；**`allowlist` 补 `hashlib`/`html`/`xml`**（D-8）；**`layerIsolation` 补登 `stock_api → cdp_engine` 单向同层边**（并强化 cdp_engine 条目的 reason）；`namingRules.fetch` 措辞放宽为"至少含 `(code, deadline=None)`"（实现已增至 3 个可选形参）；`namingRules.config` 补"代码归一化一律经 `config.canonical_code`，禁止本地正则"。`fileStructure` 不变（仍是扁平 9 模块）。

**五、本轮遗留（交编排层/后续轮次）**

> ⚠️ **v1.5 状态更新**：下表第 1 项（N1 裁决）**已关闭**（业务降级维持 200，见 §9.5）；第 5 项（AR-9/AR-13）的分档口径已按 5s 封顶重标（见 §9.5）。其余项状态不变。

| # | 事项 | 性质 |
|---|------|------|
| 1 | **§7.1 N1**：降级状态码 503 vs AC-A5 的 200 —— **二选一裁决** | **阻塞**（AR-12）：裁决前 A5 相关测试不得入基线 |
| 2 | **§7.1 N2**：SSE 帧 `items` 由稀疏变稠密 —— 建议按"只增"处理，**须记变更日志 + 补流端口帧 schema 文档** | 登记 |
| 3 | **`API.md`**：`/stock/basic_info` 仍写"⚡ 需要 Chrome CDP"（代码已为 `configured`） | 契约同步（编码/文档层） |
| 4 | **AR-6 的上游负载复核**：按订阅字段刷新后需用 `upstream_fetch_total{domain}` **实测分摊**，不得用"组数 × 3 域"外推 | P6c 校准 |
| 5 | **AR-9/AR-13**：探测阶梯顶端档位与 `_HISTORY_AGE` 窗口相对占比需实测，以确认 AC-S3 模式 B 的稳态 P95=2s | P6c 校准 |
| 6 | **AR-11**：单帧余量准入产生的"第三条建组失败轴"（帧预算 400）须与其他新增失败模式同批记入变更日志 | 登记 |

**本轮版本**：SAD v1.3 → **v1.4**；`doc/arch/tech-stack.json` 同步 `version: 1.4`（**内容有实质变更**：allowlist 补 3 个标准库 + layerIsolation 补 1 条同层边 + namingRules 2 处措辞）。**约束保持**：Python 3 标准库零依赖、`layerIsolation`（cache.py 禁 import stream/server/stock_api/market_api；cdp_engine 禁反向依赖调用方）、文件结构（扁平包 + 唯一新增 `metrics.py`）均未放宽。**未改代码、未改详设、未改 PRD。**

---

### 9.5 v1.5（裁决落地收尾同步：以**代码为准**回写 3 项裁决结论）

> **性质**：本轮**不是设计轮**。编排层已对 3 处契约冲突作出裁决并同步 PRD（`doc/prd/perf-stability-optimization.md` **v0.5**）；本轮把裁决的 **SAD 侧结论**回写，使 SAD 与**代码现状**及 **PRD v0.5** 三方一致。范围严格限定为 `doc/arch/SAD.md` + `doc/arch/tech-stack.json` 版本号与规则条目；**未改代码、未改详设、未改 PRD**。每条均先读代码确认（`server.py` / `cache.py` / `stock_api.py` / `stream.py` / `metrics.py`）。

**一、N1：业务端点降级 = 200 + error 客体（裁决关闭）**

| 项 | 内容 |
|---|------|
| **用户裁决** | 「原来旧版本怎么返回就怎么返回，因为已经有业务系统在使用旧版本接口」⇒ 与 PRD AC-A5（业务降级 = 200）逐字一致 |
| **代码证据（本轮实测）** | `server.py::_send_json_shape` 恒 `self._send_json(payload, ...)` ⇒ **200 + error 体**（`server.py:1141-1154`）；`_json_payload_has_data` **全仓无引用/已删除**（旧判定函数）；`http_503_total` **3 个计数点**：`server.py:1039`（`/healthz`）、`server.py:1340`（`_reject_503` 主端口准入）、`stream.py:1208`（流端口连接上限）——**由 4 收敛为 3** |
| **SAD 落点** | §2.3 D-1 相关（不变）/ **§2.4 降级状态码表整体重写（恒 200）** / **§2.6 计分板 `http_503_total` 4→3 计数点** / §3 server.py 行 / **§3.1 例外 4 关闭登记** / **§7.1 N1 关闭** / **§8 A5 ⚠️ → ✅、覆盖声明 6→5 条 ⚠️** / **AR-12 关闭** |
| **要点** | ① 503 仅用于**连接准入拒绝**与 **`/healthz` degraded**；**`/healthz` 的 503 是健康端点自身语义，不构成"业务端点可 503"的先例**；② 业务降级体**重新可被缓存**（`_send_json(..., cache=True)` 路径恢复语义一致，状态码不再随 payload 内容翻转）；③ 可见性改由 `metrics`（`upstream_fail_total{kind}`/`negative_cache_size`/`healthz_stale_total`）与 `/healthz` 的 `status='degraded'` 承载 |

**二、AC-S3：探测预算阶梯封顶 5s**

| 项 | 内容 |
|---|------|
| **代码证据（本轮实测）** | `cache.py::_probe_budget` 阶梯 **2→4→5（封顶）**（`cache.py:154-174`）；新增常量 **`_PROBE_BUDGET_CAP=5.0`**（`cache.py:79-84`）；`REQUEST_TIMEOUT` **不再是阶梯封顶**（仅保留给"首次冷请求"与"老化后的一次全预算探测"）；`PROBE_TIMEOUT=2` 仍为起点（`config.py:38`） |
| **推导** | 持续黑洞稳态 ≈ `5s 探测 + 5s NEG_TTL` = **10s 周期**，慢占比 ≈50% ⇒ **P95 ≈ 5s**（高请求密度）；低密度退化为**周期上界 ≈10s**；**任何单请求 ≤15s** |
| **SAD 落点** | §2.3 D-1（code block / 探测预算块 / 老化分析 / 延迟推导整体重标）/ **§2.3 D-3 矩阵** / **§4.1 延迟预算行** / §2.6（无变）/ §3 cache.py 行 / **ADR-003（决策 + 理由 + 新增 v1.5 补）** / §7.1 Q6 / **AR-3 / AR-9 / AR-13** / §8 S3 |
| **⚠️ 权衡登记（新增）** | 需要 **6–10s 才返回的"慢而未死"上游**，失败累积后**无法再靠阶梯升到 10s 自愈**（顶端钉在 5s），只能等 `_HISTORY_AGE=600s` 老化后拿一次全预算 ⇒ **该类上游恢复延迟最多约 600s**（**快速黑洞 / 连接秒拒类不受影响**）。**收敛路径**：调大 `_PROBE_BUDGET_CAP`（连带重标 AC-S3 分档），**不是**调小 `_HISTORY_AGE`（见 AR-13 ④） |

**三、`_LOCAL_BUDGET` 裁决：本地预算耗尽不计入冷却账本（正式反转确认）**

| 项 | 内容 |
|---|------|
| **裁决** | 编排层**正式反转** REV-DES-15 裁决②：本地预算耗尽**不计入**码级冷却账本（PRD v0.5 §9.1③ 固化"冷却只记真实上游失败"） |
| **代码证据（本轮实测）** | `stock_api.py:490-498`：`kind == _LOCAL_BUDGET` ⇒ 翻译为对外 `'upstream_timeout'` 后 `continue`，**不调 `_fail_ledger_record_failure`**；`stock_api.py:390-394`：预算耗尽时 `_run_batch` **不创建线程**、逐码产出 `_LOCAL_BUDGET`；`_LOCAL_BUDGET = '__local_budget__'`（`:81`，**非** `FetchError.KINDS` 成员） |
| **SAD 落点** | §2.3 **D-6**（计数口径行 + bullet 措辞改"v1.4 实现 / **v1.5 正式裁决确认**"）/ **ADR-014**（影响行 + 反转登记段 → "已确认口径"）/ §8 S6（无变，已含）/ §7.3（无变） |
| **性质** | 本轮**未改机制**——v1.4 已按实现回写；本轮仅把"实现单方面反转评审"升级为"编排层已确认裁决"，消除"评审口径 vs 实现口径"的悬空状态 |

**四、ADR 动作（本轮）**

| 动作 | ADR | 说明 |
|------|-----|------|
| **更新（关闭冲突）** | ADR-003 | 决策由"2→4→8→REQUEST_TIMEOUT"改为 **"2→4→5 封顶"**；理由段重算 P95；新增 **v1.5 补**（封顶代价 = 慢而未死上游恢复延迟 ≤600s）；影响段补 `_PROBE_BUDGET_CAP` 与"任一分量变动须重标" |
| **更新（状态升级）** | ADR-014 | `_LOCAL_BUDGET` 不入账由"v1.4 反转登记"升级为 **"v1.5 正式反转确认"**（含代码位置与 PRD v0.5 依据）；机制不变 |
| **无 ADR 变更** | ADR-001/002/004~013/015/016/017 | 本轮无涉及（N1 属契约状态码口径、按可逆性原则已由 §2.4 叙述 + AR-12 追踪，**不新增 ADR**——回改只需删一个函数，若未来再翻则是**高可逆**决策，无需 ADR 层） |

**五、tech-stack.json 动作**：`version: 1.4 → 1.5`；**`architectureRules.metrics` 条目更新**——`http_503_total` 计数点 **4 → 3**（`_reject_503` 主端口准入 / `/healthz` / 流端口连接上限），并注明"业务端点降级恒 200、不计数（v1.5 N1）"。`allowlist`/`layerIsolation`/`fileStructure`/`namingRules` 均不变。

**六、本轮遗留（交编排层/后续轮次）**

| # | 事项 | 性质 |
|---|------|------|
| 1 | **AC-A5 回归断言**：新增"业务降级（上游失败 / CDP 不可用）**不得返回 503**"用例 | 测试落地（随 §8 A5 解除阻塞） |
| 2 | **AC-S3 模式 B 重采**：按**高/低密度两轮**分别采集 P95（≤5s / ≤10s），不得合并 | P6c 校准（AR-9 / Q6） |
| 3 | **"慢而未死"上游恢复延迟**（≤600s）需实测确认可接受；若不可接受，须重议 `_PROBE_BUDGET_CAP` 并连带重标 AC-S3 | P6c 校准（§2.3 D-1 权衡 / AR-13） |
| 4 | **§7.1 N2**（SSE 帧 `items` 稠密化）：建议按"只增"处理，须记变更日志 + 补流端口帧 schema 文档 | 登记（v1.4 遗留，未变） |
| 5 | **`API.md`**：`/stock/basic_info` 仍写"需要 Chrome CDP"（代码已为 `configured`） | 契约同步（v1.4 遗留，未变） |

**本轮版本**：SAD v1.4 → **v1.5**；`doc/arch/tech-stack.json` 同步 `version: 1.5`（**内容有一处实质变更**：`metrics` 规则的 503 计数点口径）。**约束保持**：Python 3 标准库零依赖、`layerIsolation`、文件结构（扁平包 + 唯一新增 `metrics.py`）均未放宽。**未改代码、未改详设、未改 PRD。**

---

*SAD v1.5 完 · 供 review-expert 复审（复核 §9.5 裁决落地收尾同步的准确性，尤以 §2.4 降级状态码恒 200、§2.3 D-1 探测阶梯封顶 5s 与 AR-12 关闭为重点）与 task-decomposer 承接（`stream.md` / `server.md` / `cache.md` 的 P7b 侧已各自同步；`API.md` 待同步 `/stock/basic_info` CDP 标注）*

