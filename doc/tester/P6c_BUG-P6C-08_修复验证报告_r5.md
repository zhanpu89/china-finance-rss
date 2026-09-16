# P6c BUG-P6C-08 修复验证报告 r5

- 时间：2026-09-16 11:53–12:03 CST（**午间休市**）
- 变更：①lag 归零上提至 `_push_once` 空池分支 + 删假绿用例 + 新增真实路径用例；②fundflow 预取调查结论 NOT-A-BUG（未改生产代码）
- 约束：不改代码/配置；未 `docker stop`

## 1. 编译 + 全量测试

- `python -m py_compile china_finance_rss/*.py tests/*.py` → **exit=0**
- `python -m unittest discover -s tests` → **Ran 244 tests … OK**（r4 基线 238，**+6**）
- 重点类单独复跑（11 tests OK）：
  - `test_stream.RefreshLagGaugeTests` 4/4 ✅
  - `test_stream.PushLoopWiringTests` 1/1 ✅
  - `test_data_layer.PrefetchLoopTests` 6/6 ✅
- 假绿用例确已移除：`tests/test_stream.py` 中已无 `_refresh_pool([])` 式断言（仅存 docstring 说明）。

## 2. 当前时段判定

| 项 | 值 |
|---|---|
| 时钟 | 2026-09-16T03:53Z / 11:53 CST |
| `_is_trading_hours()` | **False** |
| `tick_interval()` | **120**（非 8） |
| 判定 | 午间休市 11:30–13:00 |
| 下一次可复测 | **今日 13:00 CST（05:00Z）**，下午盘 13:00–15:00 |

## 3. 三档节拍实测 —— ⏸ 未执行（时段不满足）

| 档位 | 结果 |
|---|---|
| 20 码 × 1 字段（核心） | 待复测 |
| 10 码 × 3 字段 | 待复测 |
| 200 码 × 1 字段（安全阀） | 待复测 |

## 4. lag 归零真实路径复测 —— ✅ 闭环（必做项，已执行）

部署级实测（重建后的容器，off-hours tick=120s）。建组 **120 码 × 3 字段** + 挂 SSE 连接（`coverage_codes=116`，120>116 ⇒ 强制 C2 分片，`lag=ceil(120/116)=2`）：

| t | 动作 | `stream_refresh_lag_ticks` | `tick_duration_ms` | slip | degr |
|---|---|---|---|---|---|
| 0.0s | 空池（建组前） | 0 | 0.02 | 0 | 0 |
| 89.4s | 收到 FRAME #1（调度轮产出） | — | — | — | — |
| 90.1s | 调度轮发布（C2 真实 backlog） | **2** | 42661.18 | 0 | 0 |
| 90.1s | DELETE 组（池清空） | 2 | — | — | — |
| 170.1s | 空池轮（+1 tick 内） | **0** | 0.02 | 0 | 0 |
| 290.2s | +2 tick | 0 | 0.03 | 0 | 0 |
| 322s | 清理后 | 0 | 0.03 | 0 | 0 |

**关键结论：非零 lag=2 由调度路径 `_refresh_pool` 的 C2 分片真实发布（非人为注入），池空后 1 个 tick 内归 0 并在 ≥2 tick 后维持 0。旧代码在此处会滞留 2（r4 §5 复现的滞留值）。**

> 附注：该档位（120 码 × 3 字段）离市刷新耗时 42.7s。此为超出 tick 容量的组合（coverage_codes=116），在 120s tick 下仍达标（slip=0）；若在 8s tick 下会整 tick 滑移——属容量模型预期行为，非缺陷。

## 5. 部署状态

- ⚠️ **重建前容器运行的是修复前代码**：容器内 `stream.py` 无 `No live demand` 空池分支，gauge 仅出现在旧位置（行 299/341）；宿主机 `stream.py` mtime=11:50:10（修复落盘），容器建于 ~11:30 → 陈旧。源码经 `COPY` 入镜像、无 bind mount，**必须重建**方可验证 → 已执行 `docker compose up -d --build`。
- 重建后校验：容器内 `stream.py:642-644` 已含空池归零分支 ✅
- `docker compose ps`：running，`RestartCount=0`，started 11:55:05 CST
- 日志：无 `error`/`traceback`/`exception`；仅 1 条 **INFO** 级 `Request timed out: TimeoutError` —— 我保持的空闲 SSE 客户端 socket 超出 `STREAM_PING_INTERVAL*2` 所致，非缺陷
- 清理：无残留订阅组（GET 该 sid → 404；容器生命周期内仅 1 次 created/1 次 destroyed）；无残留 :8053/:8054 客户端 socket

## 6. 结论

| 项 | 结论 |
|---|---|
| BUG-P6C-08 | ✅ **闭环**（部署级真实路径验证：2 → 0，且 ≥2 tick 维持 0） |
| <20 码 8s 节拍目标 | ⏸ **待复测**（时段不满足，tick=120） |
| 回归 | ✅ 无（244/244 OK；lag/slip/degraded/dropped/slow_client 全 0） |

## 7. 待复测项

**8s 口径待复测。** 建议复测时间：**今日 13:00 CST（05:00Z）开盘后**，于 13:10–14:50 之间执行第 3 步三档节拍实测（20 码×1 字段 / 10 码×3 字段 / 200 码×1 字段，每档 ≥60s），验收帧间隔 ≈8s（±20%）、每帧 items=订阅码数、lag=0、无 >12s 停顿。

