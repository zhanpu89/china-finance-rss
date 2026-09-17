# SSE 性能修复复测 · 测试报告 r1

- 日期：2026-09-17
- 被测版本：DNS 国内优先（三份 compose）+ `cache.py` keep-alive 连接池 & 进程内 DNS TTL 缓存 + `config.py` 新增 `HTTP_POOL_MAX_PER_HOST/HTTP_POOL_IDLE_TTL/HTTP_DNS_CACHE_TTL`
- 复测目标：验证性能修复并复测 **SSE 50 码 8 秒硬指标**
- 结论：**❌ 50 码 ≤8s 未达标**（延迟侧修复有效；8s 硬指标受"刷新容量模型"静态参数限制，非延迟限制）

---

## 1. 编译 + 单测

| 项 | 命令 | 结果 |
|----|------|------|
| 编译 | `python -m py_compile china_finance_rss/*.py tests/*.py` | exit=0 ✅ |
| cache 单测 | `python -m unittest tests.test_cache -v` | **Ran 60, OK** ✅ |
| 全量单测 | `python -m unittest discover -s tests -v` | **Ran 394, OK** ✅（基线 382 → 预期 394，符合） |

无失败、无 error。

## 2. 部署状态

```
china-finance-rss | rss | Up | 0.0.0.0:8053-8054->8053-8054/tcp
healthz=200
日志 error/traceback: no errors
```

- 容器 `/etc/resolv.conf`：`nameserver 127.0.0.11`（Docker 内嵌 DNS，转发到 compose 配置的 dns 列表，属正常）。
- 三份 compose 的 `dns` 配置均已确认为 `[223.5.5.5, 223.6.6.6, 8.8.8.8]`：
  - `docker-compose.yml`（部署用）✅
  - `doc/deploy/docker-compose.ucloud-2c8g.yml` ✅
  - `doc/deploy/docker-compose.aliyun-2c2g.yml` ✅
- 新增配置在容器内实测生效：`HTTP_POOL_MAX_PER_HOST=16`、`HTTP_POOL_IDLE_TTL=60.0`、`HTTP_DNS_CACHE_TTL=300.0`。

## 3. DNS 解析耗时 + 单请求延迟（关键对照）

**DNS（容器内 `socket.getaddrinfo` ×10）**

| host | mean | p95 | 对照修复前 |
|------|------|-----|-----------|
| x-quote.cls.cn | **15.8ms** | 21.6ms | ~170ms ✅ 改善 ~11× |
| www.cls.cn | **14.7ms** | 18.0ms | ~170ms ✅ |
| data.10jqka.com.cn | 440.5ms | **4038.9ms** | 4s 重试**仍存在** ⚠️ |

- `x-quote.cls.cn`（SSE quote/fundflow/timeline 唯一上游）DNS 已降至 ~15ms，**4s 尾巴消失**。
- `data.10jqka.com.cn`（仅 margin/news 使用，**不在 SSE 链路**）仍见 4s 重试 —— 223.5.5.5/223.6.6.6 对该域解析不佳，回退 8.8.8.8。应用内 DNS TTL 缓存（300s）可缓解进程内重复解析，但首个解析仍慢。**建议编排层评估是否将该域指向可达的国内解析器或前置缓存。**

**单请求延迟（裸 urllib ×10，`x-quote.cls.cn/quote/stock/basic`）**

```
n=10 mean=139.2ms p50=138.9ms max=167.1ms
all: 124.8 132.2 132.7 134.5 135.2 138.9 140.0 142.0 144.5 167.1
```

- 对照修复前 **340ms**（DNS 176ms + 5.5% 概率 ~4s 重试）→ 现 **139ms，max 167ms，无 4s 尾巴** ✅
- 注：这是裸 urllib，无池化；池化路径经应用逻辑（见第 4 步吞吐）。

## 4. SSE 50 码复测

压测工具：`doc/tester/sse_bench.py` + `doc/tester/sse_codes50.json`，每档观察 65s（窗口 ~71s / ~68s），代码与配置未改动。

容器内静态核算（对照实测）：

```
tick_interval            = 8s
refresh_capacity(quote)  = (coverage=23, coverage_codes=23)
refresh_capacity(3field) = (coverage=23, coverage_codes=7)
BATCH_MAX_WORKERS        = 8,  _PER_FETCH_EST = 2.2,  _TICK_BUDGET_FRACTION = 0.8
```

### 4A. A 档：50 码 × 1 字段（quote）

| 指标 | 实测 | 判定 |
|------|------|------|
| `refresh_capacity_codes` | **23** | ❌ 远低于 50 |
| `refresh_lag_ticks` | **3**（ceil(50/23)） | ❌ 应为 0/1 |
| capacity_warning | 有 | ❌ |
| 挂接帧数 / 帧间隔 | 8 帧，`[8.03, 7.70, 7.94, 8.05, 7.94, 8.02, 8.03]`，avg **7.96s** | ✅ 节拍稳定 |
| `missing_count` | `[27, 4, 0, 0, 0, 0, 0, 0]` | 第 3 帧起 0 |
| `stale_count` | `[0, 0, 4, 4, 4, 4, 4, 4]` | ❌ 稳态恒为 4 |
| `nonnull_codes` | `[23, 46, 50, 50, 50, 50, 50, 50]` | — |
| **首个全量帧**（missing==0 且 nonnull==50） | **23.46s** | ❌ >8s |
| **首个严格全量帧**（missing==0 且 stale==0） | **从未出现** | ❌ |
| `stream_tick_duration_ms` | max **520ms** | ✅ ≪8s |
| `stream_refresh_lag_ticks` | max 3 | ❌ |
| `degraded/slip/dropped/503` 增量 | 0 / 0 / 0 / 0 | ✅ |
| 上游吞吐 `upstream_fetch_total{quote}` | +264 / 71.45s = **3.69 call/s** | 对照基线 3.38 |

**A 档结论：❌ 不达标。** 50 码每 tick 仅刷新 23 个，整池轮转需 3 tick ≈ 24s > 8s。

### 4B. B 档：50 码 × 3 字段（quote+fundflow+timeline）

| 指标 | 实测 | 判定 |
|------|------|------|
| `refresh_capacity_codes` | **7**（23 // 3 字段） | ❌ 远低于 50 |
| `refresh_lag_ticks` | **8**（ceil(50/7)） | ❌ 应为 0/1 |
| 挂接帧数 / 帧间隔 | 8 帧，`[7.94, 8.05, 8.07, 7.96, 7.95, 8.09, 7.87]`，avg **7.99s** | ✅ |
| `missing_count` | `[0]×8` | ✅ |
| `stale_count` | `[20, 36, 36, 36, 36, 36, 36, 36]` | ❌ 稳态恒为 36 |
| `nonnull_codes` | `[50]×8` | — |
| **首个全量帧**（missing==0 且 nonnull==50） | **4.09s**（但 stale=36） | ⚠️ 名义达成、实质未刷新 |
| **首个严格全量帧**（missing==0 且 stale==0） | **从未出现** | ❌ |
| `stream_tick_duration_ms` | max **366ms** | ✅ ≪8s |
| `stream_refresh_lag_ticks` | max 8 | ❌ |
| `degraded/slip/dropped/503` 增量 | 0 / 0 / 0 / 0 | ✅ |
| 上游吞吐 | quote +66、fundflow +197、timeline +197 → 合计 **6.76 call/s** | 对照基线 3.38 |
| 帧峰值字节 | 1,297,445（~1.24MB，timeline 累积） | ⚠️ 偏大 |
| `stream_slow_client_total` | +1 | ⚠️ 有慢客户端 |

**B 档结论：❌ 不达标。** 每 tick 仅刷新 7 码 × 3 域，整池轮转需 8 tick ≈ 64s ≫ 8s；稳态 36/50 码为陈旧（carry-forward）数据。

### 根因定位（关键）

延迟修复**成功**，但 8s 硬指标由**刷新容量模型**（`stream.py: refresh_capacity`）门控，与延迟无关：

```
coverage       = int(0.8 × tick × BATCH_MAX_WORKERS / _PER_FETCH_EST)
               = int(0.8 × 8 × 8 / 2.2) = 23 fetch-calls/tick
coverage_codes = coverage // fetches_per_code   # quote:23  / 3字段:7
```

`_PER_FETCH_EST = 2.2s`（每 worker-call 串行等价秒数）是**按冷路径旧测量标定的陈旧值**；本次实测暖路径单请求仅 **0.139s**，模型高估约 **16×**，导致覆盖率被严重低估。稳态 `stale` 码为**轮转中的码**（实测不同帧 stale 集合变化），非死码——即瓶颈在分片轮转，不在上游可达性。

**物理可行性**：50 码 × 3 域 = 150 fetch/tick；预算 0.8×8=6.4s。按实测 0.139s/call、W=8 计，150×0.139/8 ≈ 2.6s < 6.4s —— **上游足以支撑全量刷新**，是模型常量卡住了它。

**达标所需参数（量化）**：需 `coverage_codes ≥ 50`

| 路径 | 条件 |
|------|------|
| A（quote, fpc=1） | 需 coverage ≥ 50 |
| B（3 字段, fpc=3） | 需 coverage ≥ **150** |

| 方案 | A 结果 | B 结果 |
|------|--------|--------|
| 现状 W=8, est=2.2 | 23 ❌ | 7 ❌ |
| W=8, est≤**0.34** | 150 ✅ | 50 ✅（无余量） |
| W=8, est=0.3 | 170 ✅ | 56 ✅ |
| W=16, est=**0.5** | 204 ✅ | 68 ✅（推荐） |
| W=16, est=2.2 | 46 ❌ | 15 ❌ |
| est=2.2 保 W | 需 W≥18(A) / **W≥52(B)** | |

## 5. 资源观测

```
china-finance-rss  cpu=3.16%  mem=578.5MiB / 1.5GiB
```

CPU/内存均无压力；`mem_limit=1.5g` 下余量充足，无 OOM/限流迹象。

## 6. 清理

- 压测 A/B 两档 `DELETE /stream/subscriptions/{sid}` 均返回 **200**。
- 复测探针 A 档 DELETE 200。
- 收尾确认：`stream_refresh_lag_ticks=0`、`stream_tick_duration_ms=0.05`、无残留订阅组。

## 7. 结论

**❌ 50 码 ≤8s 硬指标未达标。**

- ✅ **延迟侧修复有效且显著**：DNS 170ms→15ms，单请求 340ms→139ms（max 167ms），4s 重试尾巴在 SSE 上游 `x-quote.cls.cn` 上消失；tick 耗时 ≤520ms，无 degraded/slip/dropped/503。
- ❌ **8s 硬指标未达成**，瓶颈是**静态容量模型常量 `_PER_FETCH_EST=2.2`**，而非上游延迟/带宽：
  - A 档：覆盖率 23/50，lag=3，稳态 stale=4，首个全量帧 23.46s（超 8s 约 **2.9×**）。
  - B 档：覆盖率 7/50，lag=8，稳态 stale=36，整池轮转 ~64s（超 8s 约 **8×**）。
- ⚠️ 次要项：`data.10jqka.com.cn` 仍有 4s DNS 尾巴（不影响 SSE）；B 档单帧峰值 ~1.24MB 且出现 1 次 slow_client。

**下一步调参建议（供编排层决策，本报告不改参数）：**

1. **首选：重标定 `_PER_FETCH_EST`**（`stream.py`）从 `2.2` → **~0.3–0.5**（实测暖路径 0.139s，留 2–3.6× 余量），使其反映池化后的真实单次耗时；这是"单一权威"常量的正确落点。
2. **配合：`BATCH_MAX_WORKERS` 8 → 16**，同时保持 `HTTP_POOL_MAX_PER_HOST ≥ 16`（当前恰为 16，若 W>16 需同步抬高池上限，否则并发被池截断）。
   - 组合 `W=16 + est=0.5` → coverage=204，A=204、B=68，均满足 ≥50 且有约 36% 余量。
3. 若维持 `est=2.2` 不变，则需 `W≥18`（A）/ `W≥52`（B）——后者远超池上限 16，会退化为池排队，**不推荐**。
4. 建议同轮验证：重标定后复测 A/B 两档，确认 `stale_count→0`、`refresh_lag_ticks ≤1`、首全量帧 ≤8s；并关注 B 档单帧字节（1.24MB）与 slow_client。

> 备注：`refresh_capacity` 的"分片轮转"（BR-STR-17/18）是为大订阅池（如 200 码）设计的降载机制。若产品要求"50 码全员 8s 内刷新"为硬约束，则 50 码必须落入 C1 全量分支（`fetches_per_code × n ≤ coverage`），即上表参数需满足。
