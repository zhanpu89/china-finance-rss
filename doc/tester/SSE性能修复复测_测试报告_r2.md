# SSE 容量重标定复测 · 测试报告 r2

- 日期：2026-09-17
- 被测版本：第二轮修复 — `STREAM_PER_FETCH_EST` 2.2→**0.3**、`BATCH_MAX_WORKERS` 8→**16**（均 env 可覆盖）；承接前轮 DNS 国内优先 + 连接池
- 复测目标：验证容量重标定，复测 **SSE 50 码 ≤8s 硬指标**
- 压测工具：`doc/tester/sse_bench.py` + `doc/tester/sse_codes50.json`（未改动），A/B 各 60s
- 结论：**✅ 50 码 ≤8s 达标**

---

## 1. 编译 + 单测（基线 394）

| 项 | 命令 | 结果 |
|---|---|---|
| 编译 | `python -m py_compile china_finance_rss/*.py tests/*.py` | **exit=0** ✅ |
| 全量单测 | `python -m unittest discover -s tests -v` | **Ran 394 tests, OK** ✅ |

- 无失败、无 error；`tests/test_stream.py` 11 处容量断言与新常量同步，全部通过。
- 基线 394 保持不变（无新增/删除用例）。

## 2. 容量校验输出原文（第 2 步）

```
STREAM_PER_FETCH_EST= 0.3 BATCH_MAX_WORKERS= 16
['quote'] coverage= 341 coverage_codes= 341 OK
['quote', 'fundflow', 'timeline'] coverage= 341 coverage_codes= 113 OK
```

- **两行均 OK** ✅，与预期 **341（1域）/ 113（3域）** 完全一致。
- 容器内复核（`docker compose exec -T rss python -c ...`）：`STREAM_PER_FETCH_EST=0.3 BATCH_MAX_WORKERS=16` → **镜像内已生效** ✅
- 模型：`coverage = int(0.8 × 8 × 16 / 0.3) = 341`；50 码落入 **C1 全量分支**（A：1×50 ≤ 341；B：3×50=150 ≤ 341）。

## 3. 部署状态 + 日志

```
docker compose up -d --build → Image Built → Container Recreated → Started
china-finance-rss | Up 18 seconds
logs (error|traceback): no errors
healthz=200
```

- 重建成功；`curl healthz=200` ✅
- 压测全程日志过滤 `error|traceback|exception|warn|capacity|degrad` → **无命中** ✅（末 60 行 + 全量 125 行）
- 健康态收尾：`stream_tick_duration_ms=0.05`、`stream_refresh_lag_ticks=0`、`stream_queue_bytes=0`

## 4. A 档验收：50 码 × 1 字段（quote）· 60s

| 指标 | 实测 | 判定 |
|---|---|---|
| `refresh_capacity_codes` | **341** | ✅ ≥50 |
| 模型分支 | C1（1×50 ≤ 341） | ✅ |
| `refresh_lag_ticks` | create 响应无该字段；采样 30 点 max **0** | ✅ 无 lag |
| **首个严格全量帧**（missing==0 ∧ stale==0 ∧ items==50） | **4.94s** | ✅ **≤8s** |
| 挂接帧数 / 帧间隔 | 7 帧 `[7.34, 8.19, 7.81, 8.24, 7.76, 8.20]`，avg **7.92s** | ✅ 节拍 ~8s |
| `missing_count` | `[0,0,0,0,0,0,0]` | ✅ |
| `stale_count` | `[0,0,0,0,0,0,0]` | ✅ 稳态无陈旧 |
| `items` / `nonnull_codes` | `[50]×7` / `[50]×7` | ✅ 全员每帧 |
| `stream_tick_duration_ms` | max **661.47ms** | ✅ ≪8s |
| `degraded / slip / dropped / slow_client / 503` 增量 | 0 / 0 / 0 / 0 / 0 | ✅ |
| 上游吞吐 `upstream_fetch_total{quote}` | +256 / 60.28s = **4.25 call/s** | — |
| 单帧字节峰值 | 41,359 B（~40KB） | ✅ |

**A 档结论：✅ 达标。**

## 5. B 档验收：50 码 × 3 字段（quote+fundflow+timeline）· 60s

| 指标 | 实测 | 判定 |
|---|---|---|
| `refresh_capacity_codes` | **113** | ✅ ≥50 |
| 模型分支 | C1（3×50=150 ≤ 341） | ✅ |
| `refresh_lag_ticks` | 采样 30 点 max **0** | ✅ 无 lag |
| **首个严格全量帧**（missing==0 ∧ stale==0 ∧ items==50） | **5.21s** | ✅ **≤8s** |
| 挂接帧数 / 帧间隔 | 7 帧 `[6.81, 8.39, 8.27, 7.98, 7.80, 8.38]`，avg **7.94s** | ✅ |
| `missing_count` / `stale_count` | `[0]×7` / `[0]×7` | ✅ |
| `items` / `nonnull_codes` | `[50]×7` / `[50]×7` | ✅ 三域全员每帧 |
| 各域刷新次数（min） | quote/fundflow/timeline 均 **7** | ✅ 无域被饿死 |
| `stream_tick_duration_ms` | max **1,206.43ms** | ✅ ≪8s |
| 指标增量 | degraded/slip/dropped/slow_client/503 全 **0** | ✅ |
| 上游吞吐 | quote 3.46 + fundflow 5.93 + timeline 5.88 = **15.27 call/s** | — |
| 单帧字节峰值 | **1,444,113 B（~1.38MB）** | ⚠️ 偏大（见 §7） |

**B 档结论：✅ 达标。**

## 6. 容器资源

```
china-finance-rss  cpu=20.68%  mem=589.2MiB / 1.5GiB
```

- CPU/内存均无压力，无 OOM/限流迹象；`mem_limit=1.5g` 余量充足。

## 7. 逆向/边界观察（非阻断，记录供下轮）

1. **帧周期抖动**：A 档 `8.19 / 8.24`、B 档 `8.39` 略超 8s（最大超 **4.9%**）。这是 tick 调度抖动，**不是刷新未完成**——每帧数据均为严格全量（missing=0, stale=0）且新鲜。若产品把"帧周期 ≤8s"也当硬约束，需将 tick 目标下调至 ~7.5s。
2. **B 档单帧 1.38MB**：较 r1（1.24MB）增大 ~11%（timeline 累积）。推算单客户端带宽 ~161KB/s；慢客户端风险随 fan-out 线性放大。本轮 `slow_client` 增量 0。
3. **上游吞吐口径**：A 档 quote 4.25 call/s 低于名义 50码×7帧/60s=5.83，metric 可能含批量/去重语义；不影响验收结论，仅记录。

## 8. 结论

**✅ 50 码 ≤8s 硬指标达标。**

| 维度 | r1（修复前） | r2（本轮） |
|---|---|---|
| A `coverage_codes` | 23 ❌ | **341** ✅ |
| B `coverage_codes` | 7 ❌ | **113** ✅ |
| A lag / 稳态 stale | 3 / 4 ❌ | **0 / 0** ✅ |
| B lag / 稳态 stale | 8 / 36 ❌ | **0 / 0** ✅ |
| A 首个严格全量帧 | 从未出现 ❌ | **4.94s** ✅ |
| B 首个严格全量帧 | 从未出现 ❌ | **5.21s** ✅ |
| tick 耗时 max | 520ms / 366ms | 661ms / 1206ms ✅ |
| 指标增量 | 0（slow_client +1） | **全 0** ✅ |

- 容量重标定**生效且与预期 341/113 完全一致**；50 码落入 C1 全量分支，**每帧全员 50 码 × 全字段刷新**，`lag=0`、`stale=0`，分片轮转不再触发。
- 前轮延迟修复（单请求 139ms）+ 本轮容量模型（0.3 / 16）形成闭环，**8s 瓶颈已消除**。
- 未达标项：**无**。唯一量化余量点：帧周期抖动最大 8.39s（+4.9%）、B 档单帧 1.38MB —— 均非 8s 指标项。

### 下一步建议
1. 若"帧周期 ≤8s"为硬约束 → 将 `TICK_INTERVAL` 目标降至 7.5s 或保留当前（抖动仅 +4.9%）。
2. B 档 1.38MB 帧：评估 timeline 累积是否可增量下发/截断，或提高 `STREAM_QUEUE_BYTES` 以抗慢客户端（当前增量 0，暂无风险）。
3. 建议将 50 码 ≤8s 纳入回归门禁（本 bench 可脚本化），防止常量回退导致 coverage 再次跌破 50。

## 9. 清理

- A/B 两档 `DELETE /stream/subscriptions/{sid}` 均返回 **200**（`{"deleted": true}`）。
- 收尾确认：`stream_refresh_lag_ticks=0`、`stream_tick_duration_ms=0.05`、`stream_queue_bytes=0`；无残留订阅组（无 list 端点 → 404，以 DELETE 回执为准）。

---

**验收结论：✅ PASS**


