# AC-E4 吞吐验证报告（≥100 req/s × 5min · 错误率 0 · P99 劣化 ≤20%）

- **AC**：AC-E4【server.py】混合读吞吐（PRD `doc/prd/perf-stability-optimization.md:81`）
- **被测系统**：china-finance-rss，容器 `china-finance-rss`，`http://127.0.0.1:8053`（主端口）
- **部署配置**（`docker compose config` 实测）：`HTTP_POOL_MAX_PER_HOST=48`、`MALLOC_ARENA_MAX=2`、`MAX_WORKERS=20`、`MAX_INFLIGHT=40`、`mem_limit=1.5GiB`
- **时段**：2026-09-20 非交易时段 → TTL 全部钉基线（quote/fundflow/timeline=120s、feed/announcement=180s、margin=600s、f10/sector/longhu=按 policy）
- **执行**：tester 阶段二；**只读生产**，未改 `china_finance_rss/**`，新增 tests-only 压测脚本
- **结论**：**FAIL（不稳定）** — 吞吐与错误率判据稳健通过，P99 劣化判据不可稳定复现

## 0. 判定速览

| 判据 | 要求 | 实测 | 结果 |
|------|------|------|------|
| 吞吐 | ≥ 100 req/s × 300s | **200.0 req/s**（4 次正式跑，均为 60000 req / 300s） | ✅ |
| 错误率 | == 0 | **0 / 240000**（200 req/s 4 次合计；另 120 req/s 36000 亦 0） | ✅ |
| P99 劣化 | P99(120–300s) ≤ 1.2 × P99(0–120s) | 主跑 **1.438×**；复跑 0.811 / 1.021 / 1.095 | ❌ |

> 同负载（200 req/s）4 次运行劣化比 = **1.438 / 0.811 / 1.021 / 1.095**（3 通过 / 1 失败）⇒ 判据**不可稳定复现**，故 AC-E4 判 **FAIL**。
> 在 AC 名义负载 **120 req/s** 下另 1 次运行：劣化比 **1.000**、P99≈15.2ms、错误 0 ⇒ 该负载下判定 PASS。

## 1. 测试口径与设施

### 1.1 可断言口径（SAD Q1 裁决，`doc/arch/SAD.md:1244`）
命中率 ≥90% **不是 AC**，降为设计目标 + `/healthz` 观测项；对外可断言口径仅：**错误率 0 + 后3min P99 劣化 ≤20%**。本报告据此判定，命中率仅作观测。

### 1.2 负载形态（SCN-1 + SCN-4 缓存命中为主混合读）
复用 `tests/loadtest.py` 的请求语义（`urllib` + `User-Agent`，不带 `Accept-Encoding`/gzip），在 `tests/` 下新增两个**最小 tests-only 脚本**：

- `tests/ac_e4_verify.py` — 主验证器：预热 → 并发探测 → 正式 300s →（可选）无 RSS 对照；逐秒 req/s+错误序列；**两窗口 P50/P95/P99**；`/healthz?check=0` 前后快照；`docker stats` 起点/中点/终点快照。
- `tests/ac_e4_diag.py` — 诊断器（复用 `ac_e4_verify` 的 helper）：分离 **TCP 连接耗时 / 服务端响应耗时**；30s 分桶尾延迟；**按端点**尾延迟；`/proc/net/sockstat` TIME_WAIT 采样。

> 为何新增而非扩展 `loadtest.py`：其 `test_sustained_load` 为固定 ~10 req/s 批节奏，且无逐秒序列、无两窗口 P99、无快照能力，无法满足本 AC 的采集要求；`loadtest.py` 保持原样未改。

**加权端点池（每请求 `random.choice`）**：`/stock/data`×code(6) `/stock/basic_info`×code(4) `/stock/timeline`×code(5) `/stock/fundflow`×code(5)（10 个码）× `/cls/hotplate`(15) `/market/margin`(6) `/healthz?check=0`(10) `/cls/telegraph`(10) `/eastmoney/kuaixun`(10)。共 251 权重 / 44 个唯一 URL。**已按要求排除 `/stock/f10`**（CDP 慢尾）。RSS 取 5 源中的 2 个等权。

### 1.3 客户端模型与限速（重要）
服务端为 **HTTP/1.0 无 keep-alive**（`curl -D-` 实测：无 `Connection: keep-alive`），每请求新建 TCP 连接。为避免 5min 内 client 侧临时端口/TIME_WAIT 耗尽污染结果，正式跑对**发送速率设上限 `--max-rate 200 req/s`**（仍 ≥2× 判据下限），并发 10（< `MAX_INFLIGHT=40`，规避 AC-E8 的 503）。并发探测阶段不设限速以测容量。

**测量口径注意**：本报告延迟为**客户端端到端**（PRD §3 的服务端 handler 耗时口径不含 RTT）；loopback RTT 可忽略，但含每请求 TCP 建连（HTTP/1.0）。故该延迟是服务端 handler 耗时的**保守超集**。

## 2. 预热与并发确定

```
python3 tests/ac_e4_verify.py --base http://127.0.0.1:8053 \
  --probe-concurrency 4,10 --probe-seconds 30 \
  --formal-seconds 300 --max-rate 200 --cooldown 60 \
  --control-seconds 60 --control-rate 200 \
  --report-json /tmp/opencode/ac_e4_formal.json
```

| 阶段 | 并发 | 时长 | 达成速率 | 错误 | P50(ms) | P95(ms) | P99(ms) |
|------|------|------|---------|------|---------|---------|---------|
| 预热 | 4 | 8s | 452.9 | 0 | 8.09 | 15.53 | 20.16 |
| 探测 | 4 | 30s | 444.1 | 0 | 8.25 | 16.63 | 22.42 |
| 探测 | 10 | 30s | 428.9 | 0 | 22.41 | 37.26 | 45.07 |

结论：**并发 4 即达 ~445 req/s ≫ 100**；服务端混合读容量约 **430–455 req/s**（c=4 与 c=10 已接近饱和，再增并发无吞吐收益、仅抬尾延迟）。正式跑取 c=10 + 限速 200 req/s。

## 3. 正式运行结果

### 3.1 主跑（run1，`/tmp/opencode/ac_e4_formal.json`）—— FAIL

正式：c=10、限速 200 req/s、300s；**60000 请求全部 HTTP 200，错误 0**。

| 窗口 | n | 错误 | P50(ms) | P95(ms) | P99(ms) | Max(ms) |
|------|---|------|---------|---------|---------|---------|
| A 前2min (0–120s) | 24000 | 0 | 2.186 | 7.756 | **13.651** | 323.5 |
| B 后3min (120–300s) | 36000 | 0 | 2.260 | 10.928 | **19.632** | 1454.3 |

**劣化比 = 19.632 / 13.651 = 1.438 > 1.2 ⇒ FAIL**（超限差值 +0.238）。P50 基本不变（+3.4%），劣化集中在尾部（P95 +40.9%、P99 +43.8%）。

**无 RSS 对照**（60s，c=10，cap 200）：12000 req / 0 err；P50 2.783 / P95 14.608 / P99 21.398 / Max 159.5 —— 与含 RSS 的 B 窗口（P99 19.63）同量级 ⇒ **RSS 生成不是尾延迟来源**（RSS 端点自身 p99 22–24ms，与其它端点相当）。

### 3.2 复现运行（同负载不同轮次）

| 运行 | 脚本 | 速率 | 错误 | A P99(ms) | B P99(ms) | 劣化比 | 判定 |
|------|------|------|------|-----------|-----------|--------|------|
| run1 | verify（主跑，含探测+对照） | 200.0 | 0 | 13.651 | 19.632 | **1.438** | ❌ |
| run2 | verify | 200.0 | 0 | 22.310 | 18.086 | 0.811 | ✅ |
| run3 | verify | 200.0 | 0 | 18.854 | 19.259 | 1.021 | ✅ |
| diag200 | diag（http.client） | 200.0 | 0 | 25.519 | 27.936 | 1.095 | ✅ |
| diag120 | diag（**120 req/s**，c=6） | 120.0 | 0 | 15.216 | 15.212 | **1.000** | ✅ |

观察：窗口 A 的 P99 在 **13.6–25.5ms 剧烈波动**，窗口 B 稳定在 18.1–27.9ms；**主跑 FAIL 的唯一原因是其 A 窗口异常"干净"（13.651ms，5 次运行最低）**，随后 B 回落到典型 ~19ms。即判据被 **A 窗口相位**主导。

## 4. 观测项

### 4.1 `/healthz?check=0` 前后快照

| 时点 | cache_hit_ratio | http_503_total | cache_entries.url | upstream_timeout | upstream_error |
|------|-----------------|----------------|-------------------|------------------|----------------|
| 压测前（curl） | 0.2281 | 0 | 65 | 147 | 10 |
| 主跑 pre_formal | 0.3646 | 0 | 63 | 147 | 11 |
| 主跑 mid_formal | 0.4603 | 0 | 60 | 148 | 11 |
| 主跑 post_formal | 0.5301 | 0 | 58 | 149 | 11 |
| 压测后（curl，全局） | 0.7703 | 0 | 53 | 158 | 16 |

- **`http_503_total` 全程 0** —— 无限流拒绝、无 AC-E8 触发、`MAX_INFLIGHT` 未打满。
- `upstream_timeout` 147→158（+11，跨全部轮次含非压测背景）、`upstream_error` 10→16（+6）：**未随压测放量**，属正常背景。
- `cache_hit_ratio` 观测 0.23→0.77（累计口径，含历史流量）。**远低于 ≥90% 设计目标**，但按 SAD Q1 **非 AC**，仅登记为设计目标偏离（与 AR-2 一致）。
- `cache_entries.url` 稳定 53–65（仅触达 44 个唯一 URL，无 LRU 抖动；`fundflow/quote=1000`、`timeline/depth=500` 打满属预期）。

### 4.2 容器资源（`docker stats --no-stream`）

| 时点 | CPU% | Mem / Limit | Mem% | PIDs |
|------|------|-------------|------|------|
| 压测前 | 0.88 | 1.25GiB / 1.5GiB | 83.3 | 341 |
| 主跑 mid | 78.5 | 1.219GiB / 1.5GiB | 81.3 | 341 |
| 主跑 post | 6.9 | 1.23GiB / 1.5GiB | 82.0 | 341 |
| diag200 mid | 69.4 | 1.24GiB / 1.5GiB | 82.7 | 341 |
| 压测后 | 1.71 | 1.251GiB / 1.5GiB | 83.4 | 341 |

- **内存全程稳定 1.22–1.25GiB（81–84%），无增长、无 OOM、无重启**（PIDS 恒 341）。
- 残余风险：**headroom 仅 ~250MiB**，与 SAD AR-18「缺口 ≈750MB / 已定位缓解」残余一致；本 AC 下未劣化。
- CPU 峰值 ~78%（中点瞬时采样）。

### 4.3 TIME_WAIT 与客户端建连（诊断）

| 指标 | A(0–120s) | B(120–300s) | B/A |
|------|-----------|-------------|-----|
| connect P99 | 0.699ms | 0.704ms | **1.007** |
| 服务端响应 P99 | 25.150ms | 27.709ms | 1.102 |
| 总 P99 | 25.519ms | 27.936ms | 1.095 |

`/proc/net/sockstat` TIME_WAIT：5458 → **10814**（mid）→ 10000（post）；主机 `tcp_tw_reuse=2`、`tcp_timestamps=1`。**尽管 TIME_WAIT 上万，connect P99 恒定 0.7ms** ⇒ **客户端建连未随压测劣化，客户端侧伪影可排除**。

## 5. 根因分析

### 5.1 客户端限制 —— 排除
吞吐 200 req/s（判据下限 2×）、错误 0、connect P99 恒定；未达容量瓶颈（容量 ~450 req/s）。**不属"客户端压不动"**。

### 5.2 服务端尾延迟来源（第 1 条归因已于 §9 更正）
1. **`/market/margin` 无终端缓存 ⇒ 每次请求都要对 URL 缓存命中的文本做 `json.loads` + `_transform_margin`（CPU 成本），而非"每请求回源网络"** — `margin.cache_max='n/a'`（`DOMAIN_MATRIX`，`config.py:382`；`/healthz` 实测 `cache_max=null`）指**无终端缓存**（`stock_api._cache_store` 式 LRU），**不等于无 URL 缓存**：margin 取数经 `market_api.py:61` `ttl = cache_policy('margin')['ttl']`（=600s）与 `:68` `fetch_json(url, _MARGIN_HEADERS, ttl=ttl, deadline=...)`，仍受共享 URL 缓存（`cache.fetch_json` 的 TTL/LRU）保护。故每次请求的固定成本是**命中 URL 缓存后的 `json.loads`（`market_api.py:67`）+ `_transform_margin`（`:80`）**，这解释其 P50 ≈9.1ms（缓存端点仅 0.8–4.5ms；diag200 中 margin P50 12.7ms / P99 41.2ms，为全场最慢路径）——而非网络往返。它占请求 ~2.4%，但**每次都在高位**，主导聚合 P99。
   > ⚠ **本节原结论"`/market/margin` 每请求回源、无 URL 缓存"已被推翻**（代码复核 + 本轮 HTTP 探针，见 §9）。原"连发 20 次 → `upstream_fetch_total.margin` 精确 +20"的观测**予以保留**，但其含义更正为"计数器按 fetcher 调用自增"，**不能证明每次回源**。
2. **~60s 周期性尾尖峰（时间上吻合，因果待验证）** — diag200 的 30s 分桶 P99 在 t=60s（48.2ms）、t=120s（60.5ms）陡升，其余桶 13–22ms；与 `china_finance_rss/cache.py:39` 的 `_CACHE_SWEEP_INTERVAL = 60.0`（缓存清扫/后台刷新节拍）**在时间上吻合**。120 req/s 下尖峰被抹平（分桶 P99 12.5–17.6ms）。**注意：这是相关性观测、非已证因果**——本轮无直接证据（如清扫临界区计时 / 锁等待打点）证明尖峰由 sweep 引起，GC / 上游波动等其它周期源未被排除。
3. **A/B 窗口相位敏感** — 上述周期尖峰使 2min/3min 窗口 P99 随相位漂移，劣化比在 0.81–1.44 间跳动。

### 5.3 非来源
- **RSS 生成**：无 RSS 对照 P99 21.4ms ≈ 含 RSS 的 B 窗口 19.6ms ⇒ 非来源。
- 线程池/限流：`http_503_total=0`、容量 450 req/s 未达、`MAX_INFLIGHT=40` 未打满。

## 6. 缺陷清单

| ID | 严重度 | 描述 | 证据 | 处置建议 |
|----|--------|------|------|---------|
| BUG-AC-E4-01 | **P1** | **P99 劣化判据不可稳定复现**：同负载 4 次运行劣化比 1.438/0.811/1.021/1.095，1 次违反 ≤1.2。观测到的 ~60s 尾尖峰与 `_CACHE_SWEEP_INTERVAL=60.0` **时间吻合，因果待验证** | §3.1/§3.2/§5.2.2 | 修尾尖峰或修订判据（§7） |
| BUG-AC-E4-02 | **P1（可观测性）** | **`upstream_fetch_total{margin}` 语义与其它域不一致**：stock 域在**终端缓存 miss** 后才调用 fetcher 自增；margin 无终端缓存且计数器置于 `fetch_json` 调用**之前**（`market_api.py:65` vs `:68`）⇒ **每次 handler 调用都自增**，与 URL 缓存命中/回源无关，会误导运维判断回源率。**原"`/market/margin` 无 URL 缓存、每请求回源"结论已证伪**（见 §9） | §5.2.1/§9 | 统一指标语义（如新增 `upstream_net_total` 仅在实际网络 IO 后自增，或文档化各域口径）；margin 的 P99 贡献改归因为 URL 缓存命中后的 `json.loads`+transform **CPU 成本** |
| OBS-AC-E4-03 | 观测 | `cache_hit_ratio` 0.23–0.77 ≪ 90% 设计目标（**非 AC**，SAD Q1） | §4.1 | 按 AR-2 在 P6c 稳态窗口复核 |
| OBS-AC-E4-04 | 观测 | 内存 headroom 仅 ~250MiB（83%）；本 AC 下稳定无增长 | §4.2 | 与 AR-18 残余一并跟踪 |

> 分级口径与全系统一致：P1 = 功能缺陷/单点/**性能退化**（生产版阻断，MVP 记入报告）；本次属**性能退化类**，不阻断但需处置。

## 7. 判定与建议

### 7.1 判定
- **吞吐 ≥100 req/s：✅ PASS**（200 req/s × 300s，4/4 运行；容量 ~450 req/s）。
- **错误率 = 0：✅ PASS**（200 req/s 4 次共 240000 请求 0 错误；120 req/s 36000 请求 0 错误）。
- **P99 劣化 ≤20%：❌ FAIL**（主跑 1.438×；4 次同负载运行 1 次违反）。
- **AC-E4 总判：FAIL（不稳定）**。在 AC 名义负载 **120 req/s** 下判定 PASS（1.000×）。

### 7.2 建议（需编排层裁决，二选一）
1. **修订判据稳健性（建议先做）**：将"前2min vs 后3min 单次 P99"改为抗周期尖峰口径，例如
   - 用**起跑 60s 之后的稳态区间**比较；或
   - 用**滑窗 P99 中位数比**（每 30s 一个 P99，比较前后半段中位数）；或
   - 要求 **≥3 次重复取中位劣化比 ≤1.2**。
   依据：本 AC 的 A 窗口 P99 单次波动达 13.6–25.5ms，单次比值噪声 ±30%。
2. **消除尾尖峰**：核查 `_CACHE_SWEEP_INTERVAL=60` 清扫/后台刷新是否造成同步停顿（如为锁竞争，考虑分片/异步化）——**该尖峰与 60s 节拍仅为时间吻合，须先做临界区/锁等待探针确认因果**。附带修正 BUG-AC-E4-02（**可观测性**：统一 `upstream_fetch_total` 各域语义；margin **已有** URL 缓存 ttl=600s，**无需再加缓存**，其 P99 成本为命中后的 `json.loads`+transform CPU 成本）。

> 未修改任何生产代码与契约文档（符合测试纪律）。

## 8. 附录

### 8.1 命令
```
# 主跑（含探测 + 无RSS对照）
python3 tests/ac_e4_verify.py --base http://127.0.0.1:8053 \
  --probe-concurrency 4,10 --probe-seconds 30 --formal-seconds 300 \
  --max-rate 200 --cooldown 60 --control-seconds 60 --control-rate 200 \
  --report-json /tmp/opencode/ac_e4_formal.json
# 复跑（run2 / run3）
python3 tests/ac_e4_verify.py --base http://127.0.0.1:8053 \
  --probe-concurrency 10 --probe-seconds 5 --formal-seconds 300 \
  --max-rate 200 --cooldown 20 --control-seconds 0 \
  --report-json /tmp/opencode/ac_e4_run2.json
# 诊断（连接/响应分离 + 分桶 + 按端点 + TIME_WAIT）
python3 tests/ac_e4_diag.py --formal-seconds 300 --concurrency 10 \
  --max-rate 200 --cooldown 20 --bucket 30 --report-json /tmp/opencode/ac_e4_diag200.json
python3 tests/ac_e4_diag.py --formal-seconds 300 --concurrency 6 \
  --max-rate 120 --cooldown 20 --bucket 30 --report-json /tmp/opencode/ac_e4_diag120.json
# 观测
curl -s 'http://127.0.0.1:8053/healthz?check=0'
docker stats --no-stream china-finance-rss
# §9.2 计数器归因探针（同键 20 次 + 冷键 miss/hit 延迟签名）
curl -s -o /dev/null -w '%{http_code}\n' 'http://127.0.0.1:8053/market/margin?market=99'   # ×20（同 URL）
curl -s -o /dev/null -w '%{time_total}\n' 'http://127.0.0.1:8053/market/margin?market=1'   # ×6（首慢后快）
```

### 8.2 原始产物
- `/tmp/opencode/ac_e4_formal.json`（主跑，含逐秒 req/s+错误序列）
- `/tmp/opencode/ac_e4_run2.json`、`/tmp/opencode/ac_e4_run3.json`
- `/tmp/opencode/ac_e4_diag200.json`、`/tmp/opencode/ac_e4_diag120.json`（含分桶 / 按端点 / connect-resp 分离）
- 复用脚本：`tests/loadtest.py`（未改）；新增 tests-only：`tests/ac_e4_verify.py`、`tests/ac_e4_diag.py`
- §9.2 归因探针原始读数（`curl` + `/healthz?check=0`，非文件产物）：空闲 `8404→8404`；同键 20 次 `8404→8424`；冷键 `?market=1` 6 次 `8424→8450` 且 `time_total` 首 1.329s、后 5 次 0.0075–0.0100s

### 8.3 环境
- 主机：`ip_local_port_range=32768-60999`、`tcp_tw_reuse=2`、`tcp_timestamps=1`、`tcp_max_tw_buckets=65536`、`somaxconn=4096`
- 服务端：`Server: BaseHTTP/0.6 Python/3.12.14`，HTTP/1.0，无 keep-alive

## 9. 更正记录（事后代码复核 + HTTP 探针，2026-09-20）

> 本节记录对 §5.2.1 / **BUG-AC-E4-02** 的**归因更正**：原"`/market/margin` 每请求回源"的**事实断言不成立**，已被代码复核与本轮探针推翻。**§0 判定结论（吞吐 ✅ / 错误率 ✅ / P99 劣化判据 ❌）不变**。原观测数据全部保留，仅更正其含义。

### 9.1 代码证据（推翻"每请求回源 / 无 URL 缓存"）

| 证据 | 位置 | 含义 |
|------|------|------|
| 计数器位于取数**之前** | `market_api.py:65` `metrics.incr('upstream_fetch_total', key='margin')`，`:68` 才 `fetch_json(...)` | 每次 `fetch_margin` 调用都自增，**与 URL 缓存命中/未命中无关** |
| handler 无条件进入 | `handle_margin`（`market_api.py:137-140`）→ `fetch_margin(market)`，无短路 | margin 无终端缓存 ⇒ 每次请求都到达该计数器 |
| margin **有** URL 缓存 | `market_api.py:61` `ttl = cache_policy('margin')['ttl']`（`/healthz` 实测 `ttl=600`）；`:68` `fetch_json(url, _MARGIN_HEADERS, ttl=ttl, deadline=...)` | margin 取数仍受共享 URL 缓存（`cache.fetch_json` 的 TTL/LRU）保护 |
| `cache_max='n/a'` 的真实语义 | `config.py:354-358`、`:382` | 指**无终端缓存**（`stock_api._cache_store` 式）；注释明确 margin 属"仅经共享 URL 缓存服务"的域 |
| stock 域对照（口径不一致的根源） | `stock_api.py:518-548`：先查终端缓存，命中直接返回，仅 `missing/eligible` 才走 fetcher（自增在 fetcher 内） | stock 的 `upstream_fetch_total` 在**终端缓存 miss** 后才自增 ⇒ 与 margin 口径不同 |

**结论**：`upstream_fetch_total{margin}` 度量的是 **"fetcher 被调用次数"**，不是"网络取数次数"；原"连发 20 次 → 精确 +20"只能证明计数器按调用自增。

### 9.2 本轮 HTTP 探针（如实记录）

环境：`http://127.0.0.1:8053`（同一容器），非交易时段，经 `/healthz?check=0` 读 `metrics`。

- **空闲漂移基线**：间隔 20s 无任何 margin 请求，读两次计数 ⇒ `8404 → 8404`，**idle_delta=0**（排除背景刷新干扰）。
- **同键连发 20 次**（`?market=99`，全部 HTTP 200）：计数 `8404 → 8424`，**精确 +20**；`upstream_error`/`upstream_timeout` 不变（17/159）。
- **冷键 vs 热键**（`?market=1`，连续 6 次，`curl -w '%{time_total}'`）：

  | 次序 | 1 | 2 | 3 | 4 | 5 | 6 |
  |------|---|---|---|---|---|---|
  | `time_total`(s) | **1.329** | 0.0082 | 0.0086 | 0.0100 | 0.0081 | 0.0075 |

  该 6 次计数共 **+6**（`8424 → 8450`）——即 URL 缓存**命中的后 5 次也各 +1**。

**探针能证明什么**：
1. 计数器**按 fetcher 调用自增**，与命中/回源无关（缓存命中的 5 次仍各 +1）；
2. `?market=1` **首请求 1.329s、后续 ~8ms** = 明确的 **URL 缓存 miss(网络) → hit(缓存)** 延迟签名 ⇒ **证明 margin 确实受 URL 缓存保护**，"每请求回源 / 无 URL 缓存"不成立；
3. 热路径稳定的 ~8ms = **命中 URL 后仍要做 `json.loads` + `_transform_margin` 的 CPU 成本**，而非网络往返——与原报告 margin P50 9.1ms 吻合。

**探针不能证明什么（诚实标注）**：
- 计数器本身**无法区分**命中/回源（它不做区分）；本报告对命中/回源的判定**靠"冷键首请求 1.329s vs 后者 ~8ms"的延迟签名**，是行为证据而非计数器证据；
- 未做"本地监听端口替换 `_MARGIN_URL`"或"缓存命中打点"这类直接探针（需改 `china_finance_rss/**`，超出本轮只读约束）；
- `?market=1` 首请求偏慢**单次观测**，也可能是该键恰在 TTL 边缘或上游瞬时抖动，未重复；结论以**代码证据（9.1）**为主、探针为辅。

### 9.3 复查 BUG-AC-E4-01（保留）

- **未被推翻的部分**：同负载 4 次劣化比 1.438/0.811/1.021/1.095（1 次违反）、A 窗口 P99 13.6–25.5ms 抖动、diag200 在 t=60s/t=120s 的 30s 分桶尾尖峰——**观测数据全部保留**。
- **措辞更正**：分桶尖峰与 `_CACHE_SWEEP_INTERVAL=60.0` **仅为时间吻合的相关性观测**；本轮**无**直接证据（清扫临界区计时 / 锁等待打点 / 关闭 sweep 的对照）证明因果，故 §5.2.2 与 §6 均标注"**时间上吻合、因果待验证**"。判据不稳定（❌）的结论不变。
