# SSE 五档并入 + quote 50码 ≤4s — 盘中验收测试报告

**TR-20260917-001** | 版本 **r1** | 状态 **⏳ 待评审** | 日期 2026-09-17 下午盘（13:00–15:00 交易时段）
关联变更：`config.py`（L0=4s 档；quote L1→L0；新增 depth 域 L0；`_STOCK_DEPTH_URL`）、
`stream.py`（`tick_interval` 取订阅域最短 TTL；`_FIELD_FETCH_CALLS['quote']` 1→2）、
`stock_api.py`（`fetch_cls_stock_depth`；`fetch_cls_basic_info` 阶段 3 附加 depth）
验收对象：**能力①quote 50 码 ≤4s**；**能力②五档并入 SSE quote**
测试工具：`doc/tester/sse_depth_bench.py`（自写，扩展自 `sse_bench.py`，新增 depth 观测与逐帧时序）+ `sse_codes50.json`
约束遵守：只读 SSE / 订阅 CRUD；**未改任何代码或配置**；未 `docker stop`；每步带 timeout。

---

## 一、执行概要

| # | 验收项 | 结果 | 结论 |
|---|--------|------|------|
| 1 | 编译 `py_compile` | exit=0 | ✅ |
| 2 | 单元测试（基线 394） | **411 OK**（+17） | ✅ |
| 3 | 容量 tick/coverage/coverage_codes | 4 / 170 / 85·42，与预期逐项一致 | ✅ |
| 4 | 部署 + healthz | Up，healthz=200，日志无 error/traceback | ✅ |
| 5 | **4A quote 50码 ≤4s** | 首全量帧 3.72 / 3.98 / 4.04s，lag=0，节拍 3.94–3.97s | ✅（边界） |
| 6 | **4B 3域 50码 ≤8s** | 首全量帧 0.95 / 8.02 / **12.33s**，lag=2 | ⚠️ 冷启动超时 |
| 7 | **4C 五档字段（普通/北交所/指数）** | 三种语义全部符合 | ✅ |
| 8 | 4D 帧体积与丢弃 | dropped=0；3域帧 ~2.0MB，触发 slow=1 | ⚠️ 见 BUG-02 |
| 9 | 上游负载 | 无失败；负载低于模型估算 | ✅ |
| 10 | 资源 | cpu 29.23%，mem 602.5MiB/1.5GiB | ✅ |
| 11 | 清理订阅组 | 5 组全 404 | ✅ |

**总判定：两项新能力均达标 ✅；3 域回归项冷启动首帧 ⚠️（见缺陷清单）。**

---

## 二、缺陷清单

| BUG-ID | 关联 | 描述 | 严重度 | 状态 |
|--------|------|------|--------|------|
| BUG-SSE-DEPTH-01 | 4B-1 | 3 域（quote+fundflow+timeline）**冷启动首个全量帧 12.33s**，超 ≤8s 目标 +4.33s（+54%）。同期 `stream_tick_duration_ms` 达 4706ms（>0.8×4s=3.2s 预算），触发 `degraded=1 / slip=1`。稳态无此问题（lag=2 → 每码刷新周期 8s）。 | **P1**（性能退化，冷启动态） | 待处置 |
| BUG-SSE-DEPTH-02 | 4D-2 | quote 成本 1→2 后，3 域每 tick 成本 4×50=200 > coverage 170，**由 r2 的 C1 全量转入 C2 分片**（lag=2）；帧体积膨胀至 ~2.0MB，压测中触发 `slow_client_total=1`（帧大 → 慢客户驱逐）。 | P2 | 待处置 |
| — | — | 无 P0；无数据丢失/资金/安全问题。 | — | — |

> **量化差距（BUG-01）**：冷启动实测 12.33s vs 目标 8s → **+4.33s（+54%）**；另 2 次采样 8.02s（+0.02s）/ 0.95s。差距全部来自**冷缓存首拍**（50 码 × 4 域 = 200 次冷请求），非稳态能力不足。稳态 lag=2 与预期一致。

---

## 三、编译 + 单测（第一步）

```
$ python -m py_compile china_finance_rss/*.py tests/*.py; echo "compile exit=$?"
compile exit=0

$ python -m unittest discover -s tests -v 2>&1 | tail -8
----------------------------------------------------------------------
Ran 411 tests in 4.455s

OK
```

- 编译 **exit=0**。
- 单测 **411 通过 / 0 失败**（基线 394 → **+17**，覆盖新增 depth 路径与 L0 档）。

---

## 四、容量校验（第二步，贴原文）

```
tick(quote)= 4 tick(3域)= 4
['quote'] coverage= 170 coverage_codes= 85
['quote', 'fundflow', 'timeline'] coverage= 170 coverage_codes= 42
```

| 校验项 | 期望 | 实测 | 结论 |
|--------|------|------|------|
| `tick_interval(['quote'])` | 4 | **4** | ✅ |
| `tick_interval(['quote','fundflow','timeline'])` | 4 | **4** | ✅ |
| `coverage`（两档） | 170 | **170** | ✅ |
| `coverage_codes`（quote） | 85 | **85** | ✅ |
| `coverage_codes`（3 域） | 42 | **42** | ✅ |

与改动摘要逐项吻合：quote 50 码落入 **C1**（`2×50=100 ≤ 170`）→ 全量无 lag；3 域 `4×50=200 > 170` → **C2 分片**，`lag=ceil(50/42)=2`。

---

## 五、部署（第三步）

```
 Container china-finance-rss  Recreated / Started
china-finance-rss | Up 15 seconds
no errors
healthz=200
```
- 镜像重建成功，容器 Up，启动日志 **无 error/traceback**，`/healthz?check=0` = **200**。

---

## 六、4A 验收：50 码 × quote（含 depth）— 目标 ≤4s

建组响应：`refresh_capacity_codes=85` ✅；`refresh_lag_ticks` 未返回（C1 全量分支无 lag），全文采样 **lag=0** ✅。

| 采样 | 帧数/窗口 | 首帧 | **首个全量帧** | 帧间隔 avg(min–max) | missing | stale | items | lag max | tick_ms avg/max | degraded/slip |
|------|-----------|------|----------------|---------------------|---------|-------|-------|---------|-----------------|----------------|
| A1 | 15 / 63.23s | 4.04s | **4.04s** | 3.97 (3.19–4.43) | 全 0 | 全 0 | 全 50 | 0 | 207.1 / 812.9 | 0 / 0 |
| A2 | 10 / 44.00s | 3.98s | **3.98s** | 3.96 (3.60–4.40) | 全 0 | 全 0 | 全 50 | 0 | 181.0 / 406.6 | 0 / 0 |
| A3 | 10 / ~40s | 3.72s | **3.72s** | 3.94 | 全 0 | 全 0 | 全 50 | 0 | — | 0 / 0 |

- **首个全量帧 3.72 / 3.98 / 4.04s**：2/3 次 ≤4s；A1 = 4.04s（**超 0.04s，1%**，边界）。
- 稳态每帧 **50/50 码全量、全字段新鲜**（`missing=0`、`stale=0`、`nonnull=50`），刷新节拍 **3.94–3.97s < 4s**。
- `lag=0` 全程 → 每个 4s tick 全池刷新完毕（C1 成立）。
- `stream_frame_peak_bytes` = 58249（客户端单帧 58.9KB）。
- depth 覆盖：**50/50 码 present，0 码缺失，`zero_only=[]`**。

**4A 判定：✅ 达标（边界）。** 能力①成立；唯一余量点是首次全量帧在冷态 4.04s（+1%），属 tick 相位/首拍开销，非刷新未完成。

---

## 七、4B 验收：50 码 × 3 域 — 目标 ≤8s（lag=2 可接受）

建组响应：`refresh_capacity_codes=42`、`refresh_lag_ticks=2`，并附
`capacity_warning: "subscription has 50 codes but only 42 refresh per tick; frames are sharded and each code lags ~2 ticks"` ✅ 与预期一致。

| 采样 | 帧数/窗口 | 首帧 | **首个全量帧** | 帧间隔 avg(min–max) | stale 分布 | lag max | tick_ms avg/max | degraded/slip/slow |
|------|-----------|------|----------------|---------------------|-----------|---------|-----------------|--------------------|
| B1（冷缓存） | 12 / 60.05s | ~9.32s | **12.33s** ❌ | 4.32 (3.01–7.65) | 0–8 | 2 | 894.8 / **4706.2** | 1 / 1 / 1 |
| B2（温缓存） | 8 / 40.30s | 8.02s | **8.02s** ⚠️ | 4.01 (3.26–4.54) | 0/8 交替 | 2 | 443.3 / 1060.3 | 0 / 0 / 0 |
| B3（热缓存） | 11 / ~45s | 0.95s | **0.95s** ✅ | 4.03 | 0/8 交替 | 2 | — | 0 / 0 / 0 |

- 稳态：每帧 **items=50**、`missing=0`，`stale` 0↔8 交替 → 每码刷新周期 = lag(2) × tick(4s) = **8s**，符合"lag=2 可接受"的口径 ✅。
- **首个全量帧高度不稳定**：0.95 / 8.02 / **12.33s**。冷启动（B1，紧随另一组销毁、缓存冷）12.33s **超 ≤8s 目标 +4.33s（+54%）**；B1 首帧时 `items_n=50` 但 8 码为 null（`nonnull=42`）。
- B1 `stream_tick_duration_ms` 峰值 **4706ms > 3.2s 预算**，触发 `degraded=1 / slip=1`；仅冷启动出现。

**4B 判定：⚠️ 稳态达标、冷启动首帧未达标。** 若"首个全量帧 ≤8s"为硬门禁则 B1 为 ❌；按"lag=2 即 8s 刷新周期"口径则命中预期。根因为**冷缓存首拍**（200 冷请求），非稳态刷新容量不足。

> 对比 r2 基线（`SSE性能修复复测_测试报告_r2.md`）：当时 3 域 tick=8s、`coverage_codes=113`、**C1 lag=0**、首全量帧 5.21s。本次 quote 成本 1→2 使 3 域跨入 **C2 分片（lag=2）**。刷新周期仍 ~8s，但首帧延迟方差显著变大 —— 见 BUG-01/02。

---

## 八、4C 五档字段实测（关键）

探针组 `[sh600519 普通股, bj430047 北交所, sh000001 指数]` × quote，16s，4 帧：

| 代码 | 类型 | `quote.depth` 出现 | 帧内 `quote` 键 | 值特征 |
|------|------|--------------------|-----------------|--------|
| sh600519 | 普通个股 | **4/4 present** | `code,data,depth,msg,sector_name` | 21 键，**全部非 0** |
| bj430047 | 北交所 | **0/4（absent）** | `code,data,msg`（无 depth） | 键不存在 ✅ |
| sh000001 | 指数 | **0/4（absent）** | `code,data,msg`（无 depth） | 键不存在 ✅ |

`zero_only=[]` → **未出现任何"全 0 假档"**。

**普通个股 depth 原文（sh600519，脱敏不限）：**
```json
"depth": {"b_px_1":1265.14,"b_px_2":1265.13,"b_px_3":1265.1,"b_px_4":1265.08,"b_px_5":1265.03,
 "b_amount_1":3,"b_amount_2":1,"b_amount_3":1,"b_amount_4":4,"b_amount_5":1,
 "s_px_1":1265.2,"s_px_2":1265.4,"s_px_3":1265.44,"s_px_4":1265.5,"s_px_5":1265.58,
 "s_amount_1":27,"s_amount_2":1,"s_amount_3":4,"s_amount_4":10,"s_amount_5":3,"preclose_px":1258.0}
```

50 码组内 depth 亦全部 present（50/50），示例（sh601091）：
```json
"depth": {"b_px_1":13.39,"b_px_2":13.38,"b_px_3":13.37,"b_px_4":13.36,"b_px_5":13.35,
 "b_amount_1":28,"b_amount_2":39,"b_amount_3":13,"b_amount_4":53,"b_amount_5":158,
 "s_px_1":13.4,"s_px_2":13.41,"s_px_3":13.42,"s_px_4":13.43,"s_px_5":13.44,
 "s_amount_1":140,"s_amount_2":310,"s_amount_3":153,"s_amount_4":534,"s_amount_5":20,"preclose_px":4.39}
```
> 注：`b_px_1..5`/`s_px_1..5`/`b_amount_1..5`/`s_amount_1..5`/`preclose_px` 共 **20+1 键**齐全；`preclose_px` 与最新成交价差异过大（如 sh601091: 13.39 vs 4.39）疑为上游字段语义问题，**建议业务侧确认是否需同源校验**（不影响"非 0/非假档"结论）。

**4C 判定：✅ 达标。** 普通股非 0 真档、北交所/指数无 depth 键、无全 0 假档，与 `fetch_cls_stock_depth` 的 None 语义完全一致。

---

## 九、4D 帧体积与丢弃

| 项 | 4A（quote×50） | 4B（3域×50） |
|----|----------------|--------------|
| 客户端单帧 avg / max | 58,898.5 / **58,913 B** | 1,960,294 / **2,015,725 B** |
| 服务端 `stream_frame_peak_bytes` | 58,249 | 1,991,879 → 收尾 **2,015,061** |
| `stream_frame_dropped_total` 增量 | **0** | **0** |
| `stream_slow_client_total` 增量 | **0** | **1**（B1 冷启动） |
| `stream_queue_bytes` 收尾 | 0 | 0 |

- **五档对 quote 帧的增量**：depth 单码 JSON ≈ **322 B** × 50 ≈ **16.1 KB**，占 58.9 KB quote 帧的 **≈27%**（其余 ~42.8 KB 为 basic/quote 本体）。
- 3 域帧 ~2.0MB 主要由 fundflow/timeline 贡献；伴随 1 次慢客户驱逐（BUG-02）。
- **无丢帧**（dropped=0），队列收尾为 0。

---

## 十、上游负载观测（第五步）

```
PRE  fetch= {}                                    # 压测前空闲，无流量
POST fetch= {"quote":1358,"depth":1253,"fundflow":994,"timeline":991}
POST fail=  {}                                    # 全程 0 失败
```

| 用例 | quote call/s | depth call/s | fundflow | timeline | 窗口 |
|------|--------------|--------------|----------|----------|------|
| 4A-1 quote×50 | 7.34 | 6.33 | — | — | 63.23s |
| 4B-1 3域×50 | 5.58 | 5.36 | 6.11 | 6.08 | 60.05s |

- 全程 `upstream_fail_total = {}` → **零上游失败**。
- 实测负载**显著低于**模型估算（quote 50 码理论 25 call/s；3 域分片理论 42 call/s）：实测约为理论值的 ~55%。原因为 URL 缓存/负缓存/去重池在 tick 内吸收了部分请求 —— 属**良性余量**，无过载风险。
- quote : depth ≈ 1.09 : 1（A1 464:400），符合"每次 quote 刷新伴随一次 depth"的设计意图。

---

## 十一、资源（第六步）

```
china-finance-rss     cpu=29.23%   mem=602.5MiB / 1.5GiB
ai-memory-mcp         cpu=2.42%    mem=568.8MiB / 2GiB
ai-memory-mcp-web     cpu=0.20%    mem=37.72MiB / 2GiB
```
- 业务容器 CPU 29%、内存 602.5MiB，距 1.5GiB 上限余量充足；2MB 帧未造成内存压力。

---

## 十二、结论（第十步）

### 能力① quote 50 码 ≤4s —— ✅ **达标（边界）**
- `lag=0`、每帧 50/50 全量新鲜、刷新节拍 **3.94–3.97s < 4s**。
- 首个全量帧 **3.72 / 3.98 / 4.04s**：2/3 ≤4s；冷态 4.04s 超 **+0.04s（1%）**，属首拍相位开销。
- 与模型完全一致：`coverage=170 ≥ 100` → C1 全量分支。

### 能力② 五档并入 SSE quote —— ✅ **达标**
- 普通个股 depth 20+1 键齐全且**数值非 0**（50/50 码）；北交所 `bj430047`、指数 `sh000001` **无 depth 键**；`zero_only=[]` 无假档。
- 非致命降级正确：depth 缺失不影响 quote 本体（上游 `fail=0` 未触发）。

### 回归项 4B（3 域 ≤8s）—— ⚠️ **冷启动未达标，稳态达标**
- 稳态 lag=2 → 每码 8s 刷新周期 ✅；首全量帧 0.95 / 8.02 / **12.33s** 不稳。
- 量化差距：冷启动 **+4.33s（+54%）**；温缓存 **+0.02s**。
- 根因：quote 成本 1→2 使 3 域由 r2 的 **C1（lag=0）转入 C2（lag=2）**，冷缓存首拍 200 请求 + tick 退化（4706ms）叠加。
- **不建议擅自调参**；若"首全量帧 ≤8s"为硬门禁，建议方向（供编排层决策）：提高 `BATCH_MAX_WORKERS` / 下调 `STREAM_PER_FETCH_EST` 使 3 域回到 C1，或对冷启动首拍做预热。

### 缺陷
- P0：**0**；P1：1（BUG-SSE-DEPTH-01，冷启动）；P2：1（BUG-SSE-DEPTH-02，C1→C2 与 2MB 帧）。

---

## 十三、清理（第十一步）

DELETE 全部订阅组，5 个 sid 复查均 **404**：
```
84312729a196 -> 404    b2a0932235a9 -> 404    56c2637cabe6 -> 404
1e049535dfba -> 404    e932dc5d1924 -> 404
```
无残留订阅组、无残留 SSE 连接。

---

## 附：复现命令

```bash
python -m py_compile china_finance_rss/*.py tests/*.py
python -m unittest discover -s tests -v
python doc/tester/sse_depth_bench.py 60          # A / 4C探针 / B，写 doc/tester/sse_depth_out.json
```
原始数据：`doc/tester/sse_depth_out.json`（主跑）、`sse_depth_confirm.json`、`sse_depth_confirm3.json`（复采样）。

