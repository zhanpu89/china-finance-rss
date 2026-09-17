# SSE 接口极限压测基线报告

- **任务**：SSE 极限压测基线（只测 SSE，不测其他接口）
- **时间**：2026-09-17 10:42–10:52 CST（**交易时段**，`_trading_tiers().L1 = 8s`）
- **对象**：`GET /stream/quote/<sid>`（SSE，端口 8054），订阅组经 `POST /stream/subscriptions` 创建
- **方法论**：裸 socket SSE 客户端 + 2s 间隔 `/healthz` 采样；每档建组 50 码，观测 60s
- **产出**：本报告 + `doc/tester/sse_bench.py`（压测脚本）+ `doc/tester/sse_codes50.json`（码表）

## 0. 一句话结论

**两档均未达标，且差距显著。** A 档（50 码 × quote）每码刷新周期 **≈14.8–24s**（要求 ≤8s）；B 档（50 码 × 3 域）**60s 内从未出现过一帧覆盖全部 50 码**，全量周期 **≈27–86s**。当前 `BATCH_MAX_WORKERS=8` 的容量为 **23 码/tick（单域）** 与 **7 码/tick（三域）**，后者是硬瓶颈。

---

## 1. 部署状态

**镜像重建 + 容器重建成功，服务健康，无异常日志。**

| 项 | 值 |
|---|---|
| 镜像 | `china-finance-rss-rss` 重建成功（`#13 DONE 0.0s`），容器 `Recreated` → `Started` |
| 容器 | `china-finance-rss | Up`（压测全程未重启、未崩溃） |
| 日志 | `no errors`（grep error/traceback 无命中） |
| healthz | `200`（压测前后均为 200，全程 **0 次 503**） |
| `MAX_WORKERS` | `20` |
| `MAX_INFLIGHT` | `40` |
| `CDP_STOCK_PAGES` | `4` |
| `GZIP_MIN_BYTES` | `1024` |
| `BATCH_MAX_WORKERS`（代码常量，`stock_api.py:51`） | **`8`** ← 本次压测的容量决定项 |
| L1 tick（交易时段） | `8s`（`config.py:302`，已确认压测时刻为交易时段） |

`coverage = int(0.8 × tick × BATCH_MAX_WORKERS / _PER_FETCH_EST)` = `int(0.8 × 8 × 8 / 2.2)` = **23 fetch-calls/tick**（与建组响应一致）。

---

## 2. 使用的 50 个真实码

**全部为真实标的，无需补充码。** 来源：`/quotation/market` → `stock_ranking.data.{change,main_fund_diff,tr}[].secu_code`（27 个去重真实码，已是 `sh/sz` 规范形态）+ `/ths/longhu`（73 条，去重 + 裸 6 位按 `6→sh / 0,3→sz / 4,8→bj` 换算）。合并去重共 **78 个**真实码，取前 50。

```
sh601091 sh688137 sz301390 sz300434 sh688296 sh688356 sz300553 sh688079 sz300741
sz300461 sh688802 sz000725 sz000981 sh600487 sz002080 sz300394 sh688795 sh603773
sh600522 sz002584 sh688837 sz301520 sh603082 sh600127 sz003001 sz002137 sz300243
sz000592 sz000759 sz000823 sz000868 sz000978 sz000993 sz001216 sz002161 sz002212
sz002281 sz002396 sz002491 sz002579 sz002585 sz002631 sz002790 sz002846 sz002856
sz002912 sz003026 sz300464 sz300656 sz301251
```

> 已剔除 `111024`（债券，非股票）；`longhu` 原始重复项（如 `000823`×2、`301251`×2）已去重。建组响应回显 50 码全部接受（HTTP 201），无 400。

---

## 3. A 档：50 码 × 1 域（quote）

建组响应：`refresh_capacity_codes=23`, `refresh_lag_ticks=3`
`capacity_warning`: *"subscription has 50 codes but only 23 refresh per tick; frames are sharded and each code lags ~3 ticks"*

### 3.1 帧到达间隔序列（观测 71.03s，共 7 帧）

| 指标 | 值 |
|---|---|
| 帧数 | **7** |
| 间隔序列（s） | `[9.08, 11.03, 7.10, 9.70, 6.60, 4.47]` |
| min / avg / max | `4.47` / **`8.00`** / `11.03` |
| ping 帧 | 0（20s 心跳未触发，说明帧从未断流 20s） |
| 连接错误 | 0 |

### 3.2 每帧 missing / stale / codes_total / items

| # | 到达(s) | codes_total | items 实际码数 | missing_count | stale_count | 有数据码数 |
|---|---|---|---|---|---|---|
| 1 | 0.00 | 50 | 50 | **27** | 0 | 23 |
| 2 | 9.08 | 50 | 50 | **4** | 0 | 46 |
| 3 | 20.11 | 50 | 50 | **0** | 4 | 50 |
| 4 | 27.21 | 50 | 50 | **0** | 4 | 50 |
| 5 | 36.91 | 50 | 50 | **0** | 4 | 50 |
| 6 | 43.51 | 50 | 50 | **0** | 4 | 50 |
| 7 | 47.98 | 50 | 50 | **0** | 4 | 50 |

- `items` **始终 50 码**（真快照语义正确），冷启动首帧 23/50 有数据。
- **首个全量帧（`missing_count==0` 且 50/50 有数据）在 31.93s 到达**（第 3 帧，即建组后约 32s）。
- 稳态后每帧 `stale_count=4`（4 码沿用缓存/上轮值），46 码为本轮新鲜数据。
- 帧体积 20,273B → 41,416B（quote-only，单帧 ~41KB）。

### 3.3 tick 时长 / lag 采样

| 指标 | 采样序列 / 值 |
|---|---|
| `stream_tick_duration_ms` | `0.03` → **`8934.38`** → `2017.91` → `5048.20` → `4143.68` → `5848.08` → `4450.81` → `919.20`（同时刻重复值 = 同一 tick 被多次采样） |
| **`stream_tick_duration_ms` 峰值** | **8934.38 ms** ⚠️ **> tick 间隔 8000ms** |
| `stream_refresh_lag_ticks` | `0`（未建组）→ **`3`**（全程稳态）= 与建组响应 `refresh_lag_ticks=3` 一致 |

### 3.4 计数增量 + 上游吞吐

| 计数器 | 增量 |
|---|---|
| `stream_tick_degraded_total` | **+1** |
| `stream_tick_slip_total` | **+1** |
| `stream_frame_dropped_total` | 0 |
| `stream_slow_client_total` | 0 |
| `http_503_total` | 0 |
| `upstream_fail_total` | `{}`（无失败） |
| `upstream_fetch_total{quote}` | **+240** |

**上游吞吐推导**：240 quote 调用 / 71.03s = **3.38 call/s**；quote 为 1 call/码 ⇒ 50 码全量一轮 = **50 / 3.38 = 14.8s**。
（另：`upstream_fetch_total{fundflow/timeline}` 本档 **+0**，证明 quote-only 组确实只付 1 call/码。）

### 3.5 每码刷新周期与达标判定

| 口径 | 50 码全量刷新周期 |
|---|---|
| 设计容量（23 码/tick × lag 3 ticks） | 3 × 8s = **24.0s** |
| 实测上游吞吐（3.38 call/s） | **14.8s** |
| 客户端"存在性间隔"（非新鲜度，仅参考） | 11.25s（avg），max 14.21s |

### 3.6 判定

> **❌ 不达标。** 每码刷新周期实测 **14.8s（吞吐口径）～24.0s（设计口径）**，要求 ≤8s，**超 1.85×～3×**。
> 附加风险：单 tick 时长峰值 **8934ms 已超过 8s tick 间隔**，`slip_total`/`degraded_total` 各 +1 ⇒ tick 已开始"跑不赢自己的节拍"，帧间隔抖动到 4.47–11.03s。

---

## 4. B 档：50 码 × 3 域（quote + fundflow + timeline）

建组响应：`refresh_capacity_codes=7`, `refresh_lag_ticks=8`
`capacity_warning`: *"subscription has 50 codes but only 7 refresh per tick; frames are sharded and each code lags ~8 ticks"*

### 4.1 帧到达间隔序列（观测 60.66s，共 5 帧）

| 指标 | 值 |
|---|---|
| 帧数 | **5** |
| 间隔序列（s） | `[14.69, 8.60, 7.76, 12.10]` |
| min / avg / max | `7.76` / **`10.79`** / `14.69` |
| ping 帧 / 连接错误 | 0 / 0 |

帧间隔均值 **10.79s > 8s** —— 三域下 tick 无法维持 8s 节拍。

### 4.2 每帧 missing / stale / codes_total / items

| # | 到达(s) | codes_total | items 实际码数 | missing_count | stale_count | 有数据码数 |
|---|---|---|---|---|---|---|
| 1 | 0.00 | 50 | 50 | **43** | 0 | 7 |
| 2 | 14.69 | 50 | 50 | **36** | 0 | 14 |
| 3 | 23.29 | 50 | 50 | **29** | 14 | 21 |
| 4 | 31.05 | 50 | 50 | **22** | 14 | 28 |
| 5 | 43.15 | 50 | 50 | **15** | 21 | 35 |

- **60s 观测窗内，`missing_count` 从未归零**（最好 15/50 缺数据，即 **30% 的码在整段压测中一次有效数据都没拿到**）。
- 每帧仅新增 **7 个码**覆盖（7→14→21→28→35），与 `refresh_capacity_codes=7` 精确吻合。
- 按此斜率需 **8 帧 ≈ 8 × 10.79s ≈ 86s** 才能覆盖全部 50 码。
- **帧体积持续膨胀：141,818B → 278,441B → 416,496B → 555,958B → 700,513B**，`stream_frame_peak_bytes` 收于 **838,919B（~820KB/帧）**。三域 50 码的帧已逼近 MB 级，N 个客户端即 N 份拷贝（`STREAM_QUEUE_BYTES_BUDGET=128MB` 下约 160 帧即打满）。

### 4.3 tick 时长 / lag 采样

| 指标 | 采样序列 / 值 |
|---|---|
| `stream_tick_duration_ms` | `0.04` → `1979.42` → **`8672.05`** → `1270.90` → `1034.04` → `5134.44` |
| **峰值** | **8672.05 ms** ⚠️ **> 8000ms** |
| `stream_refresh_lag_ticks` | `0` → **`8`**（稳态）= 与建组响应 `refresh_lag_ticks=8` 一致 |

### 4.4 计数增量 + 上游吞吐

| 计数器 | 增量 |
|---|---|
| `stream_tick_degraded_total` | **+1**（累计 2） |
| `stream_tick_slip_total` | **+1**（累计 2） |
| `stream_frame_dropped_total` / `http_503_total` / `stream_slow_client_total` | 0 / 0 / 0 |
| `upstream_fail_total` | `{}`（无失败） |
| `upstream_fetch_total{quote}` | **+44** |
| `upstream_fetch_total{fundflow}` | **+147** |
| `upstream_fetch_total{timeline}` | **+147** |

**上游吞吐推导**（合计 338 call / 60.66s = **5.57 call/s**）：

| 域 | 速率 | 50 码一轮 |
|---|---|---|
| fundflow | 2.42 call/s | **20.6s** |
| timeline | 2.42 call/s | **20.6s** |
| quote | 0.73 call/s | **68.5s** |
| **三域合成**（150 call 覆盖 50 码） | 5.57 call/s | **26.9s** |

> ⚠️ **口径说明（已如实标注为推断）**：quote 增量仅 +44，明显低于另两域的 147。A 档刚用同一批 50 码刷过 quote，B 档部分 quote 命中服务端缓存而未产生上游调用——这会使"5.57 call/s"**高估**真实三域吞吐，故下表同时给出设计公式口径（52 workers）作为保守值。

### 4.5 每码刷新周期与达标判定

| 口径 | 50 码 × 3 域全量刷新周期 |
|---|---|
| 设计容量（7 码/tick × lag 8 ticks × 10.79s） | **86.3s** |
| 设计容量（7 码/tick × lag 8 ticks × 8s 标称） | **64.0s** |
| 实测上游吞吐（5.57 call/s，偏乐观） | **26.9s** |
| 单域实测（fundflow / timeline） | 20.6s |

### 4.6 判定

> **❌ 严重不达标。** 全量刷新周期 **26.9s（乐观）～86.3s（设计）**，要求 ≤8s，**超 3.4×～10.8×**；更严重的是 **60s 内连"一帧覆盖 50 码"都未达成**，末帧仍有 15 码（30%）无数据。

---

## 5. 容器资源观测（压测期间）

采样：`docker stats --no-stream`，约 2s 一次，共 73 个 `china-finance-rss` 样本（A+B 两档全程）。

| 指标 | 值 |
|---|---|
| CPU 峰值 | **22.70%**（单核口径，远未打满） |
| CPU 均值 | **7.31%** |
| 内存峰值 | **569.2 MiB / 1.5 GiB（≈37%）** |
| 内存常态区间 | 535–560 MiB |

> 结论：**CPU 与内存均不是本轮瓶颈**。当前压测下容器有大量余量（CPU 峰值仅 22.7%），瓶颈在 `BATCH_MAX_WORKERS=8` 的**串行批次并发度与单次调用延迟**，不是机器资源。
> `http_503_total = 0`、无 dropped frame、无容器重启 ⇒ **50 码规模未压垮服务，无需降级到 20 码**。

### 5.1 附带发现：空闲态并非空闲（超出 SSE 压测范围，供后续排查）

删完全部订阅组后，`upstream_fetch_total{fundflow/timeline}` **仍在以约 2 call/s 持续增长**（实测 `1271→1281→1291` 每 5s +10，两域合计约 4 call/s），`quote` 保持不变。

| 时刻 | quote | fundflow | timeline |
|---|---|---|---|
| 删组后 ~1min | 284 | 1239 | 1239 |
| +10s | 284 | 1271 | 1275 |
| +20s | 284 | 1281 | 1281 |
| +30s | 284 | 1291 | 1295 |

⇒ 无订阅时 `_resolve_refresh_fields` 回退到全字段，后台池对默认码集持续拉取。**这会污染任何"基线"测量，并让空载态持续占用上游配额**。本次已如实标注其对 B 档口径的影响。

---

## 6. 结论：与"50 码 ≤8s"的差距量化

### 6.1 设计公式口径（`refresh_capacity` 的反解）

`coverage = int(0.8 × 8s × W / 2.2)`，要求 `coverage ≥ 50 × 每码调用数`：

| 场景 | 每码调用数 | 50 码需 fetch-calls/tick | **需要 workers** | 当前 | 缺口倍数 |
|---|---|---|---|---|---|
| **A 档：单域（quote）** | 1 | 50 | **`ceil(50×2.2/6.4) = 18`** | 8 | **2.25×** |
| **B 档：三域** | 3 | 150 | **`ceil(150×2.2/6.4) = 52`** | 8 | **6.50×** |

### 6.2 实测吞吐口径（用本机真实速率反解）

| 场景 | 实测单 worker 速率 | 达 8s 所需速率 | **需要 workers** |
|---|---|---|---|
| A 档 | 3.38 / 8 = **0.42 call/s·worker** | 50/8 = 6.25 call/s | **15** |
| B 档 | 5.57 / 8 = **0.70 call/s·worker**（受 quote 缓存复用高估） | 150/8 = 18.75 call/s | **27**（乐观下限） |

> **两口径收敛结论**：单域需 **~15–18 workers**（当前 8）；三域需 **~27–52 workers**（当前 8）。
> 给出区间而非单点，是因为 B 档 quote 缓存复用使实测速率偏乐观，而 2.2s/call 的标定值在冷路径下偏保守（实测冷路径 ≈ **3.11 s/call**：8934ms × 8 workers ÷ 23 calls）。

### 6.3 关键约束：单靠加 worker 不够

A 档仅 23 call/tick 时，**单 tick 时长峰值已达 8934ms > 8000ms tick 间隔**，`slip_total` 与 `degraded_total` 各 +1。即 tick 已经在"跑不赢自己的节拍"。

⇒ 达标需要**同时**满足：
1. `BATCH_MAX_WORKERS` 提到 15–18（单域）/ 27–52（三域）；**且**
2. 把每 tick 总时长压回 8000ms 以内（降低冷路径单调用延迟，或下调 `_TICK_BUDGET_FRACTION`，或提高 L1 tick）；
3. B 档还需关注 **~820KB/帧** 的帧膨胀（50 码 × 3 域 × N 客户端）。当前 **CPU 峰值仅 22.7%、内存 37%** ⇒ 资源侧仍有充足空间承接更多 worker。

### 6.4 达标判定汇总

| 档 | 50 码全量刷新周期 | 要求 | 判定 |
|---|---|---|---|
| A（50 × quote） | 14.8s（实测）/ 24.0s（设计） | ≤8s | ❌ 超 1.85×～3.0× |
| B（50 × 3 域） | 26.9s（乐观）/ 64–86s（设计）；60s 内未覆盖全量 | ≤8s | ❌ 超 3.4×～10.8× |

---

## 7. 清理

| 项 | 状态 |
|---|---|
| A 组 `07b5bf5c66d4` | `DELETE /stream/subscriptions/07b5bf5c66d4` → **200 `{"deleted": true}`** |
| B 组 `df9d196cfd80` | `DELETE /stream/subscriptions/df9d196cfd80` → **200 `{"deleted": true}`** |
| SSE 连接 | 客户端主动关闭，服务端 `stream_slow_client_total` 仅 1（收尾时写入失败，非泄漏） |
| 未知 sid 探针 | `GET /stream/subscriptions/deadbeef` → **404**（组已确实不存在） |
| 容器 | 未 stop、未改代码/配置；全程 Up，最终 `healthz=200` |

---

## 8. 附录：原始数据与复现

- 压测脚本：`doc/tester/sse_bench.py`（用法：`python3 doc/tester/sse_bench.py 60`）
- 码表：`doc/tester/sse_codes50.json`
- 原始结果 JSON：`/tmp/sse_bench_out.json`（含逐帧明细、逐码出现序列、metrics 前后快照）
- 采集受限项（如实报告）：
  - 逐码"新鲜度"无法从帧内直接判定——`items` 恒为全量 50 码（含缓存值），仅 `missing`/`stale` 标记区分。故每码刷新周期以**设计 lag + 上游 fetch 吞吐**反解，未用"存在性间隔"（后者会低估为 11.25s）。
  - `tick_ms` 由 `/healthz` 2s 轮询采样，同一 tick 会被重复采样（序列中连续相同值即同一 tick），峰值为真实观测值。
  - `docker stats` 采样循环因超时被截断，但已覆盖 A+B 两档全程（73 个有效样本）。

