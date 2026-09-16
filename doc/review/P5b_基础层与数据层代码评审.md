# P5b 基础层与数据层 代码评审 + P7a 漂移检测报告

> 评审模式：`P5b 代码质量评审` + `P7a 漂移检测`（合并执行） · 日期 2026-09-16 · 评审者 code-reviewer
> 评审对象：`config.py` / `cache.py` / `metrics.py`(新) / `stock_api.py` / `market_api.py` / `cdp_engine.py` + `tests/{test_config,test_cache,test_metrics,test_data_layer}.py`
> 契约基准：`doc/detailed/{config,cache,metrics,stock_api,market_api,cdp_engine}.md`(v1.1) · `doc/arch/SAD.md`(v1.3) · `doc/arch/tech-stack.json`(v1.3) · `doc/detailed/_PROGRESS.md`

## 评审结论

**⚠️ 有条件通过（无 P0；P1 × 2 建议本批修复）**

实现整体质量高：6 个模块的接口签名、锁清单/锁序、常量取值（`DOMAIN_MATRIX` 逐格）、错误枚举、资源上限**与详设逐条对齐**，未发现死锁、网络 IO 持锁、契约字段漂移或 `layerIsolation` 违例。2 项 P1 分别落在**输入边界**（`market` 未校验直达 URL 路径段）与**状态机异常兜底**（Chrome 重启窗口可在异常路径永久卡在 `restarting`）。二者都不阻断进入测试阶段，但建议在 P6c 前修掉（修复面小、回归点明确）。

| 维度 | 结论 |
|------|------|
| Dim 0 契约一致性（含三端） | ✅ 纯后端；6 模块接口/键集合/枚举与详设一致（见「漂移检测」） |
| Dim 1 数据与正确性 | ✅ 值域三分、TTL 同源、失败计数防重复，均与详设一致 |
| Dim 2 并发 | ✅ 无死锁/无锁内 IO/无锁序倒置；`_sector_cache_lock` RLock 使用**恰当**（P2-7 建议） |
| Dim 3 资源与性能 | ✅ 全部容器有上限且淘汰正确；P2-4 有 O(n)/失败 的放大点 |
| Dim 4 安全 | ⚠️ P1-1（URL 路径段注入，host 固定故非 SSRF）；无硬编码密钥、无 eval/exec、subprocess 全部 list 形式无 shell |
| Dim 5 结构与可维护性 | ⚠️ P2-1/P2-2/P2-3（遗留别名、env 注册中心绕过、未用 import） |
| Dim 6 前端 | N/A（无前端目录，纯后端） |

**受影响点与模块映射（入参无 `>>SIDE-EFFECT:` 标记，按下述变更面推断，供编排器映射 tester `>>SCOPE:`）**

| # | 受影响点（变更 → 行为变化） | 所属模块（定向回归必含） |
|---|---------------------------|------------------------|
| 1 | `config.cache_policy` 新增 + 12 常量删除 → `ImportError` 风险面 | config / server / stream / utils |
| 2 | `cache.fetch_json` 失败由「返回 None / RuntimeError」→ `raise FetchError(kind)` → 所有 RSS/JSON 调用点的异常路径改变 | cache / server / utils / stock_api / market_api |
| 3 | `cache` 由 FIFO → 真 LRU + feed SSoT `feed_cache_get/put` → `/feed/*` 双检路径 | cache / server（`_get_or_fetch_feed`） |
| 4 | `stock_api` 内部管道 → `(results, errors)`、handler 返回**组装 dict**（可能含 `_errors`）→ `stream._refresh_pool` 必须跳过 `_` 前缀键 | stock_api / server / stream |
| 5 | `stock_api._fail_ledger` 跨端点共享（`/stock/data` 与 `/stock/basic_info` 共账） | stock_api / stream（分片刷新） |
| 6 | `market_api._error` 由自由文本 → 枚举 kind；`deadline` 入口判定 | market_api / server(`/market/margin`) |
| 7 | `cdp_engine.page_data` + 重启窗口 + `watchdog_restart_skip_reason` → A/A′ 降级形态 + 守护重启决策 | cdp_engine / server / stock_api |
| 8 | 池上限 500/300 → 2000（4×）+ `quote.cache_max=2000` → 内存总账（AC-S9/AR-8） | stock_api / config |

> 建议 `>>SCOPE: modules=config,cache,metrics,stock_api,market_api,cdp_engine,server,stream`（server/stream 是消费方，`config`/`cache` 删除与改语义必须同批回归）。

---

## 问题清单

### P0（阻断）

无。

### P1（建议修复；生产版阻断）

**【P1-1】`market_api.py:45`（+ `server.py:890`）· `market` 参数未校验即拼入 URL 路径段（输入边界注入）**

- 描述：`url = f'{_MARGIN_URL}/{market}/'`，`market` 直接来自 `server.do_GET` 的 `parse_qs(parsed.query).get('market', ['99'])[0]`，**无任何枚举/白名单校验**，全链路无鉴权（PRD §6）。
- 依据：详设 `market_api.md` §2.1 只声明语义为 `'99'|'1'|'2'|'3'`，**未定义校验**（契约缺口）；tech-stack `namingRules.config` 要求参数来源收敛。既有用例 `tests/test_server.py:237 handle_margin('invalid')` 正依赖"未校验→真实回源→降级"的现行为。
- 证据链：当外部请求 `GET /market/margin?market=../../../../other/path` 或 `?market=99%3Fx%3D1` 时 → 实际请求被发往 `https://data.10jqka.com.cn/rzrq/fixdata/type/<market>/`（同 host 任意路径/查询注入），因为 server 未校验且 `fetch_margin` 直接字符串拼接；后果为"任意同 host 路径取数 + 该 10jqka 响应内容经 `data` 字段回传给调用方 + 每次不同 `market` 新增一个 URL 缓存/负缓存键"。**不升 P0**：authority 在拼接前已由 `_MARGIN_URL` 终止，`market` 无法改 host/scheme（非跨站 SSRF），故影响限于同 host 路径遍历与输入纪律。
- 建议：在 `fetch_margin`/`handle_margin` 入口 `market = market if market in {'99','1','2','3'} else '99'`（或对非白名单**直接返回** `_degraded('upstream_error')` 且不触网），并同步 `market_api.md` §2.1 补"入参白名单"。注意 `tests/test_server.py:235` 的期望值需随修复调整（该用例断言 `_error` 存在；白名单归一化后会回源 `99` 成功 → 用例须改为断言"非法值不触网"）。

**【P1-2】`cdp_engine.py:367-380` · Chrome 重启窗口缺少异常兜底，`restarting` 可永久卡死**

- 描述：`full_chrome_restart()` 在 `_chrome_restart_lock` 内先 `_mark_restarting()`（开窗），随后 `_kill_chrome_on_port()` / `gc.collect()` / `ensure_chrome()` **无 try/except/finally**。`ensure_chrome()` 内部的 `subprocess.run(['which', c])`（:326）与 `subprocess.Popen([...])`（:333）未被捕获，在 fork 失败（2C2G OOM 风暴）时会向上抛。
- 依据：详设 `cdp_engine.md` §3.2 状态转换表要求 `restarting` 必达 `idle`（成功）或 `unavailable`（真失败），**不存在"停在 restarting"的转换**；`BR-CDP-5` 要求状态迁移可观测一致。
- 证据链：当 `Popen`/`which` 因 fork ENOMEM 抛 `OSError` 时 → 异常穿透 `full_chrome_restart`，窗口已置 `restarting` 但**永不关闭** → 此后 `watchdog_restart_skip_reason()` 恒命中 `already_restarting` → `server._cdp_memory_watchdog` **永久不再重启 Chrome**（CDP 长期不可用，A/A′ 端点持续降级），且 `/healthz` 的 `cdp.state` 恒为 `restarting`（观测误导）。同一未捕获异常还会从 `_reconnect():1070` 的 `ensure_chrome()` 处抛出，逃出 `_heartbeat` 的 `except` 分支（该分支本身调用 `_reconnect()`）→ **心跳线程终止**（预存量风险，与本次同源）。
- 建议：给 `full_chrome_restart` 的临界区加 `try: ... except Exception: _mark_unavailable(); log.exception(...); return False`（或 `finally: if snapshot()['state']=='restarting': _mark_unavailable()`），保证窗口必闭；同时把 `ensure_chrome` 内 `which`/`Popen` 包进 `try/except Exception → _mark_unavailable(); return False`，使其与"节流=False 不改状态"的既有约定不冲突。

### P2（记录，不阻断）

**【P2-1】`config.py:252-256` + `utils.py:12` · `CACHE_TTL` 过渡别名未删、消费者未迁（遗留项）**

- 描述：`config.md` §2.4 要求 `CACHE_TTL` 与其余 11 个常量**同一 change-set 删除**；实现保留了 deprecated 别名 `CACHE_TTL = cache_policy('news_url')['ttl']`，`utils.py:12` 仍在 `from .config import CACHE_TTL, ...`（未使用）。
- 证据链：① 当盘中启动进程时 `CACHE_TTL=30`、非盘中启动时 `=180` → 该"常量"的值**随 import 时刻漂移**，任何未来的新消费者都会拿到时间耦合的过期 TTL，正是 R16 要消除的断崖来源；② 一旦按详设删除该行，`utils.py` 立即 `ImportError` → 整进程不可用（详设逆向-2 明确禁止"先删后迁"）。
- 建议：本轮同批删 `config.py:252-256` + 去掉 `utils.py:12` 的 `CACHE_TTL` import（该名在 utils 内零引用），并在 `_PROGRESS.md` 的"编排层同步项"中销账。

**【P2-2】`cdp_engine.py:33,37` · cdp_engine 自建 env 读取，绕过 config 的 env 注册中心**

- 描述：`CDP_URL = os.getenv('CDP_URL', 'http://localhost:9222')` **与 `config.py:17` 重复定义同一数据源**；`_CHROME_RESTART_THROTTLE = int(os.getenv('CDP_RESTART_THROTTLE', '15'))` 是**未在 config 注册**的新 env 项。
- 依据：`config.md` §1.1「env 注册中心：所有 IO 预算 / 资源上限经 `os.getenv` 注册」+ §2.3 env 表；`tech-stack.json` `namingRules.config`。`cdp_engine.md` §2.5 把二者标注为"不变"⇒ 属**详设滞后**（未登记该偏离）。
- 证据链：当运维只改 `config.CDP_URL` 或新增 `CDP_*` env 时 → cdp_engine 仍读自己的默认值，两侧静默不一致（例如 config 指向 9223、cdp_engine 仍连 9222），因为存在两份独立定义（违反 code-discipline §6「一处数据只改一处」）。
- 建议：`cdp_engine` 改 `from .config import CDP_URL`（或统一走参数注入），`CDP_RESTART_THROTTLE` 提为 `config.py` 的 env 注册项；同步在 `cdp_engine.md` §2.5/§10 登记。**注意**：本项为存量偏离（非本 change-set 引入），如不在本轮范围请在漂移节保留跟踪。

**【P2-3】`cdp_engine.py:15` · `import atexit` 未使用**

- 描述：全模块无 `atexit.` 调用（`server.py:1196` 才用）。`atexit` 在 allowlist 内故不违 `layerIsolation`，但属代码卫生（未用引用）。
- 建议：删除该 import。

**【P2-4】`stock_api.py:144-153,169-180` · `_fail_ledger` 每次失败全表扫描（+可能 sorted(10000)），故障风暴期 CPU 放大**

- 描述：`_fail_ledger_record_failure` 每次失败都调用 `_fail_ledger_prune_locked(now)` → ① 对**整表**做 `now - e[3] > FAIL_COOLDOWN` 的 O(n) 推导；② `len > _FAIL_LEDGER_MAX(10000)` 时 `sorted(..., key=e[3])` O(n log n) —— 而 `_FAIL_LEDGER_MAX` 仅在**超限**时才需要该分支。
- 依据：`BR-SA-9` 只要求"上限 ⇒ 淘汰 last_fail_ts 最小者"，未要求"每写必排序"；`stock_api.md` §7.3 把"池超限淘汰"标为低频，但未评估账本的在写路径成本。
- 证据链：当上游整体故障、全池约 2000 码在 120s 窗口内连续失败时 → 每个失败码都触发一次 n 元表扫描（n 随故障扩散增长到 2000+），使**故障期**（最需要低延迟的时段）出现 O(n²) 量级的总 CPU，2C2G 上放大请求 P95。
- 建议：`prune` 改为"仅当 `len(_fail_ledger) > _FAIL_LEDGER_MAX` 才计算 aged/淘汰"，或对 aged 检查用采样（例如每 N 次写或按 last_prune_ts 节流）；保留硬上限语义不变。

**【P2-5】`metrics.py:64-79` · `set_gauge` 无对称保护：无 `key` 调用会整体清空已积累的 label dict**

- 描述：`BR-MET-4` 只防"有 key 时非 dict → 重建"，但 `key is None` 分支无条件 `_gauges[name] = value`。若未来某写入点对 `cache_entries`/`upstream_fail_total` 这类字典型仪表误用无 key 调用 → 所有 label 一次清空。
- 证据链：当出现一次 `set_gauge('cache_entries', 5)`（漏传 `key=`）时 → `/healthz` 的 per-domain 观测全部消失且**无任何 warning**，因为该分支不校验既有类型。
- 建议：`key is None` 且 `isinstance(_gauges.get(name), dict)` 时 `_warn_once(...)` 并忽略（与 `incr` 的 BR-MET-2 对称）；或在 `set_gauge` 入口对"注册表中标注为 dict 型仪表"的名字强制要求 `key`。

**【P2-6】`stock_api.py:918` · `sleep(cache_policy(domain)['pool_refresh'])` 在 `pool_refresh is None` 时会退化为无间隔空转**

- 描述：`_prefetch_loop` 的 `sleep` 是 `try` 内第一条语句；若某域 `pool_refresh` 为 `None`，`sleep(None)` 抛 `TypeError` → 被同层 `except Exception` 吞掉并 `log.error` → 循环**立即进入下一轮**，唯一的节流点被绕过。
- 证据链：当（未来）用 `news_url`/`longhu`/`sector`（矩阵中 `pool_refresh='n/a'→None`）误接 `_prefetch_loop` 时 → 该线程以 100% CPU 空转并刷日志，因为异常路径绕过了 `sleep`。当前 4 个接线域（fundflow/timeline/f10/announcement）均非 `None`，**不可达**（故仅 P2）。
- 建议：函数入口 `interval = cache_policy(domain)['pool_refresh'] or REQUEST_TIMEOUT`（或断言非 None），保证任何路径下都有节流。

**【P2-7】`stock_api.py:130,556-582` · `_sector_cache_lock` 用 RLock 恰当，但掩盖锁序错误（建议改结构）**

- 结论（回答评审重点 1）：**RLock 使用正确且必要** —— `_sector_cache_put()` 持锁后调用 `_sweep_sector_cache()`，后者自身 `with _sector_cache_lock`，只有 RLock 不会自锁；`_sweep_sector_cache` 仅被 `_sector_cache_put` 调用（无外部持锁方），无跨模块重入。
- 风险：RLock 允许任意重入 ⇒ 未来若有人在持 `_sector_cache_lock` 时误调其它带锁函数（如 `_cache_store` 的域锁），RLock 不会报错、锁序违例会静默通过。
- 建议：改为 `_sweep_sector_cache_locked(now)`（无锁实现）+ `_sweep_sector_cache(now)` 薄包装，`_sector_cache_put` 调 locked 版 → 降为普通 `Lock`，锁序回归显式。属重构建议，可延后。

**【P2-8】`stock_api.py:937` vs `:381` · prefetch 路径未传 `ttl`，跨时段边界两个"同源值"可能来自两次 policy 读取**

- 描述：批量路径严格同源同变量（`_process_chunk: ttl=policy['ttl']` → `_run_batch` → `_fetch_one` → fetcher）✅；prefetch 路径 `fetch_one(code, deadline=call_deadline)` **不传 ttl**，由 fetcher 内部再读一次 `cache_policy(domain)['ttl']`（URL 缓存用），而终点缓存的 TTL 由读取方（`cached_batch:272` / `_process_chunk:381`）另行读取。
- 证据链：当写入发生在时段边界前一刻（如 14:59:59，trading `ttl=8`）、读取发生在边界后（15:00:01，off `ttl=120`）→ 同一 `cache_ts` 条目被判为有效 120s 而非 8s（TTL 上界被放宽 ≤112s），因为两次 policy 读取跨越了 tier 切换。属于**设计已接受**的偏差（`stock_api.md` §5.11 与 §1.4 的 `ttl=None ⇒ 内部回退 policy` 同形），影响面为每日 ≤4 个边界秒级窗口。
- 建议：prefetch 侧也把 `policy['ttl']` 透传（`fetch_one(code, deadline=..., ttl=policy['ttl'])`），与批量路径完全同源；或在详设中显式登记该窗口。

**【P2-9】`cache.py:187-199,229-234` · 段 3 双检命中 / 段 4 follower 命中不递增 `hit` ⇒ `cache_hit_ratio` 系统性低估**

- 描述：`_cache_stats['hit']` 只在段 1（:176）自增；段 3 双检命中（:189-192）与段 4 follower 命中（:231-234）都直接 `return` 不计 `hit`，但两者都在段 1 计过 `miss`。
- 证据链：当 N 个并发请求同时未命中同一 URL 时 → 只有 1 个 leader，其余 N-1 个走段 3/段 4 命中却被记为 miss ⇒ 高并发/冷启动场景下 `cache_hit_ratio` 被低估（观测项 Q1，非 AC，且详设 §5.1 伪代码同形）。
- 建议：在两处命中分支补 `_cache_stats['hit'] += 1`（均在 `_cache_lock` 内，零额外加锁），使口径与注释「命中即计」自洽。

**【P2-10】测试缺口（详见末节「覆盖与测试评估」）**

- MET-T8b（`set(snapshot()) ⊆ metrics._KNOWN` 的集成断言）、SA-T8（批量↔prefetch 共用账）、负缓存 2000 / 失败账本 10000 的**上限淘汰**、CDP-T8（无 chrome 二进制 → `unavailable`）、AC-S3 模式 A/B 的时序断言（T-CACHE-3/4/4c）在现有测试套件中缺失。

---

## 漂移检测（P7a）

> D1 契约核对（逐模块接口/字段/BR） · D2 `>>DOC_SYNC:` 追溯 · D3 规范合规 · D4 漂移节（本节的漂移条目即 P7a 产物，编排器据此 dispatch doc agent）

### D2 DOC_SYNC 追溯

全仓 grep `>>DOC_SYNC:` **未发现代码侧待验标记**（仅命中历史评审报告文本）⇒ 本轮无 P5a 遗留标记待核销，**N/A**。
但 `config.py:252` 自带的「DEPRECATED: 随本次 change-set 删除」注释是一条**未销账的自声明待办**，已在 D4 #1 与 P2-1 体现。

### D4 漂移条目

| # | 模块 · 位置 | 漂移项 | 方向判定 | 处置 |
|---|------------|--------|---------|------|
| 1 | `config.py:252-256` × `utils.py:12` | `CACHE_TTL` 未按 §2.4 删除；`utils` 未迁（未使用 import） | **实现偏离详设**（按逆向-2 的"同 change-set"要求属未完成） | P2-1；删除前须先改 `utils.py` |
| 2 | `cdp_engine.py:367-380` | 重启窗口无异常兜底，`restarting` 可达"永久态" | **实现偏离详设**（§3.2 转换表无此终态） | P1-2 |
| 3 | `market_api.py:45` × `server.py:890` | `market` 无枚举校验即入 URL 路径段 | **契约缺口（详设滞后）**：§2.1 未定义校验 → 编码亦未做；实现与详设字面一致 | P1-1；建议详设补"入参白名单" |
| 4 | `cdp_engine.py:33,37` | 自建 `CDP_URL`（与 `config.py:17` 重复）+ 未注册 env `CDP_RESTART_THROTTLE` | **详设滞后**（§2.5 标"不变/既有"未登记）+ 实现偏离 `config.md` §1.1 env 注册中心 | P2-2；须登记 `cdp_engine.md` §10 |
| 5 | `cdp_engine.py:15` | `import atexit` 未使用 | 实现偏离"手术式修改"（未用引用未清） | P2-3 |
| 6 | `metrics.md` §8 MET-T8b | CI 级 `set(snapshot()) ⊆ _KNOWN` 断言未落地（仅有反向的子集断言） | **详设要求未实现**（含逆向审查 3 的加强项） | P2-10 |
| 7 | `stock_api.py:937` | prefetch 未透传 `ttl`（与 §1.4「同源」措辞的严格解读不一致） | **合理偏差**（§5.11 伪代码同形，实为详设口径允许） | P2-8；建议透传后与批量同源 |
| 8 | `cache.py:189-192,231-234` | 非段 1 命中不计 `hit` | **合理偏差**（§5.1 伪代码同形，Q1 非 AC 观测项） | P2-9 |
| 9 | `stock_api.py:144-153` | 每次失败全表 prune（详设 §5.3 同形） | **合理偏差**（实现=详设），但成本未被详设评估 | P2-4；建议详设补在写路径成本口径 |
| 10 | `stock_api.py:918` | `sleep(None)` 空转路径（详设 §5.11 同形） | **合理偏差**（当前不可达） | P2-6 |
| 11 | `metrics.py:71-79` | `set_gauge` 无 key 时无对称保护（详设 §5 同形） | **合理偏差**（详设同形），属契约缺口 | P2-5 |

### 已核对「无漂移」项（逐条，供编排器销账）

| 契约点 | 核对结果 |
|--------|---------|
| `DOMAIN_MATRIX` 11 域 × 5 列逐格对照 `config.md` §3.1 | ✅ 完全一致（含 `plate fixed:200/200`、`feed fixed:100/100`、`margin 2.0/fixed:16`、`sector override:604800/n/a/fixed:2000`） |
| `cache_policy` 返回键集合（固定 5 键 + longhu `encoding`）、`'n/a'→None`、`KeyError` 消息含 sorted 域名、每次新建 dict | ✅ 与 §2.1/BR-CFG-8/10/11 一致（`test_config.py` CFG-T1/T5/T6/T8 覆盖） |
| 8 个新 env 名称/默认值/派生（`MAX_INFLIGHT = MAX_WORKERS*2`、整数字节 `STREAM_QUEUE_BYTES_BUDGET`） | ✅ 与 §2.3 一致；`delete` 清单 12 个常量中 11 个已删（仅 `CACHE_TTL` 见 D4 #1） |
| `fetch_json` 四段式 / `_fetch_budget` 老化（`_HISTORY_AGE=600`）/ `first_at` 不被刷新 / 失败条目跨 `NEG_TTL` 保留 / cap 2000 | ✅ 与 `cache.md` §4.2/§5.1 逐行一致（含 REV-DES-09 的"cache 写入移出网络 try"） |
| `FetchError.KINDS` 三值 + 非法 kind `ValueError`；`build_batch_response` 保留键三条件/保序去重/未知 kind 归一/无顶层 `error` | ✅ 与 §2.2/§2.3/BR-CACHE-15..18 一致 |
| 锁清单与锁序（`_cache_lock`/`_neg_lock`/`_feed_cache_lock` 互不嵌套；`_fail_ledger_lock` ⊥ 域锁；`metrics._lock` 恒最内层；`_chrome_restart_lock → _restart_window_lock → metrics._lock`） | ✅ 全部成立；网络 IO 与 `urlopen/read/decode` 均在锁外 |
| `_fail_ledger` 4 元结构、阈值 3/冷却 120s、老化删条、硬上限 `5×MAX_DEDUP_CODES` | ✅ 与 §3.1/BR-SA-7..9 一致（含"预算耗尽照常计账"的 REV-DES-15 现口径） |
| 池/终点缓存解耦（池淘汰只 `del pool[code]`）、真 LRU `move_to_end`/`popitem(last=False)`、`cache_max` 独立 LRU | ✅ 与 BR-SA-14/15 一致（SA-T9/T10 覆盖） |
| `deadline` 贯通链 + chunk 预算 `ceil_div` + 预算耗尽不建线程 + §2.3 TypeError 兼容回退 | ✅ 与 BR-SA-18..25 一致；生产取数器 6+3 个签名全带 `(code, deadline=None, ttl=None)`，无 `math` 依赖 |
| f10 四处出口统一 `_raise_cdp_unavailable()`；`page_data=None`（全部已导航页）⇒ `cdp_unavailable`，仅"有数据不匹配"⇒ `None` | ✅ 与 REV-DES-12/18（两文档统一口径）一致（SA-T26/T28 覆盖） |
| `market_api._degraded` 枚举封闭 + 防重复计数（cache 抛出的 `FetchError` 不计数） | ✅ 与 BR-MKT-6/7/8 一致（MKT-T7 覆盖） |
| 重启窗口状态机 8 条转换 + 幂等不刷 `window_start` + 节流=False 不改状态 + 模块加载发布初始 idle | ✅ 与 §3.2/BR-CDP-5（REV-DES-19）一致（`test_data_layer` 覆盖） |
| `layerIsolation` / import allowlist | ✅ config 不依赖业务；cache 不依赖上层；metrics 零业务依赖；stock_api 仅 `cdp_engine.page_data`（REV-DES-10 授权）；cdp_engine 未 import server/stream/stock_api |
| 规范：命名（`handle_*`/`fetch_*`/`cache_policy`）、相对导入、`websocket` 延迟导入、无裸 TTL 字面量 | ✅ 一致（`test_config.py` CFG-T10 扫描 5 个模块，无违规；`stock_api.py:654` 注释已剥离） |

---

## 覆盖与测试评估

### 新增测试质量（**非空转，断言具体**）

| 文件 | 用例数 | 评价 |
|------|--------|------|
| `test_config.py` | 12 | ✅ 逐条对应 CFG-T1..T10：`DOMAIN_MATRIX` 迭代断言键集合/不变式、`now` 注入边界（09:30/11:30/12:00/13:00/14:59/15:00/周六）、`sector` override 忽略时段、未知域消息含全部域名、返回值隔离、`'n/a'` 归一、8 env 默认值、**无裸 TTL 字面量扫描**（真读文件逐行，非 mock）。质量高。 |
| `test_cache.py` | 24 | ✅ 覆盖 T-CACHE-1..20 中的 16 条，含**并发真断言**（`test_leader_failure_no_stampede`：8 线程 → `max_active==1`、`calls==1`、`errs==8`）与**patch `_cache_put` 抛异常**验证 REV-DES-09 不污染负缓存（T-CACHE-20）。真 LRU 用 `list(cache)` 断言顺序（非仅长度）。 |
| `test_metrics.py` | 15 | ✅ MET-T1..T12 基本齐备，含 100 线程 × 1000 次并发精确断言 = 100000（真并发非模拟）、深拷贝、JSON 可序列化（tuple/set→list）、fail-safe 不抛、reset 隔离。 |
| `test_data_layer.py` | 26 | ✅ 最强的一组：ledger 三态（失败/成功清账/无数据不清）、老化删条、3 次触发冷却后**不触网**、预算耗尽 50 码 0 次网络 + `fail_count==1`（SA-T25）、60 码跨 chunk 无丢码、池淘汰不动数据缓存、真 LRU + `cache_entries{quote}` gauge、`page_data` 6 态边界矩阵、状态机幂等 + 4 个 skip reason 短路顺序、**4 个 `cdp_unavailable` 出口各计数 1**（SA-T26）。断言了 `_errors` 的 kind ∈ `FetchError.KINDS`（枚举封闭），非"存在即可"。 |

时序边界处理规范：`_reset_stock_state()` 持 `_fail_ledger_lock` 清账 + `metrics.reset()`（符合 SA-T24 的用例隔离要求），`_StopLoop(BaseException)` 用于逃出 `except Exception` 抓取 sleep 间隔——设计得当。

### 关键路径未覆盖（P2-10 明细）

| 缺口 | 依据 | 风险 |
|------|------|------|
| MET-T8b 集成断言（业务跑一轮后 `set(snapshot()) ⊆ _KNOWN`）缺失；仅有 `PUBLISHED_NAMES <= _KNOWN`（反向） | `metrics.md` §8 + 逆向审查 3（"CI 级强制"） | 指标名拼写错误/漏注册不会被任何测试发现（运行时仅 warning） |
| SA-T8（批量置冷却 ⇒ prefetch 对该码 `skipped`，反之亦然）缺失 | `stock_api.md` §8 SA-T8 | 共享账本的核心价值（ADR-014）无回归；`_prefetch_loop` 的 ledger gate 分支未被单测执行 |
| 负缓存 2000 / `_fail_ledger` 10000 的**上限淘汰路径**无覆盖（`test_url_cap_enforced` 只覆盖 URL 正缓存） | BR-CACHE-8 / BR-SA-9 | 淘汰算法写错（如误删最新项）不会被发现；内存护栏无回归 |
| CDP-T8（无 chrome 二进制 ⇒ `ensure_chrome()==False` 且 `state=='unavailable'`）缺失 | `cdp_engine.md` §8 CDP-T8 | 与 P1-2 同一函数族，异常/失败路径缺护栏回归 |
| CDP-T11（无新增线程）缺失 | BR-CDP-12 / AC-S9 | 线程总账无自动化守护 |
| AC-S3 模式 A/B 的时序断言（T-CACHE-3 秒拒 P95≤1s、T-CACHE-4 黑洞 2s+5s、T-CACHE-4c 老化下 P95 不劣化） | `cache.md` §8 | 本 change-set 的核心 AC 之一（负缓存/半开探测）只做了**白盒分支**验证（`_fetch_budget` 返回值），无**端到端时延**验证；若 P6c 无对应性能用例，AC-S3 实际未被机器验证 |
| `test_server.py:235` 的期望值与 P1-1 修复目标耦合（断言"非法 market → `_error`"依赖未校验行为） | P1-1 | 修 P1-1 必须同步改该用例，否则回归红灯（编排器需把 `market_api`+`server` 一并纳入 `>>SCOPE:`） |

### 残余风险（接受，不阻断）

1. `/stock/f10` 多码端到端可达 `_BATCH_BUDGET_CDP=60s`（REV-DES-21 已裁决接受 + 风险登记）；缓解项"server 强制仅单码/少量码"仍未落地（`_PROGRESS.md` 编排层同步项 #6）。
2. 池上限 4× 放大（500/300→2000）后内存改由 `cache_max` LRU 承担，须在 AC-S9 的 24h 资源总账中复核（AR-8）——本轮为静态核对，未做实测。
3. 段 4 gap 分支（`raise FetchError('upstream_error')`）在"leader 超出 follower 预算"的窄竞态下可达，会把一次性超时升格为码级失败计数（3 次后 120s 冷却）；详设 §5.1 已显式接受（fail-closed、不放大），故仅记录。

---

## 修复优先级建议（供编排器）

| 顺序 | 项 | 文件 | 回归点 |
|------|----|------|--------|
| 1 | P1-2 重启窗口异常兜底 | `cdp_engine.py` | CDP-T4/T7/T8 + `test_data_layer.RestartWindowTests` |
| 2 | P1-1 `market` 白名单 | `market_api.py`(+`server.py` 可选) | `test_server.py:235` 需改期望；`test_data_layer.MarketApiTests` |
| 3 | P2-1 删 `CACHE_TTL` + 迁 `utils.py` | `config.py`/`utils.py` | `test_server.py`(cache maintenance) + 全量 import 冒烟 |
| 4 | P2-4 / P2-5 / P2-6 防御性收口 | `stock_api.py`/`metrics.py` | 新增 3 条单测即可 |
| 5 | P2-10 补测试（MET-T8b / SA-T8 / 上限淘汰 / CDP-T8） | `tests/` | — |
| 6 | P2-2 / P2-3 / P2-7 / P2-8 / P2-9 | 各模块 | 视编排器容量，可延后至下一轮 |

**评审结论（复核行）：⚠️ 有条件通过 —— P0=0，P1=2（建议本批修），P2=10，漂移项=11（其中 2 项为实现偏离详设：`CACHE_TTL` 未删、重启窗口终态缺失）。**

