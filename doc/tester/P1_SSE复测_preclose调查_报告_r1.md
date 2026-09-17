# P1 盘中复测报告 — 容量重标定 (W=20/pool=24) + preclose_px 调查

- 日期：2026-09-17 13:5x（**交易时段**）
- 被测改动：`BATCH_MAX_WORKERS` 16→**20**、`HTTP_POOL_MAX_PER_HOST` 16→**24**
- 复测工具：`doc/tester/sse_recheck_p1_round.py`（本轮新增，只读；SSE + 订阅 CRUD）＋ `doc/tester/sse_codes50.json`（50 码）
- 预期口径：`tick=4` ⇒ `coverage=213`、`coverage_codes` = **106（quote）/ 53（3 域）**
- 结论：**容量重标定完全生效；4B（50×3域 ≤8s）达标 ✅；4A 稳态达标但"进程冷启动首帧 9.87s"未达 ≤4s ❌（量化差距见 §4）；preclose_px 非我方缺陷**

---

## 1. 编译 + 单测（基线 411）

| 项 | 命令 | 结果 |
|---|---|---|
| 编译 | `python -m py_compile china_finance_rss/*.py tests/*.py` | **exit=0** ✅ |
| 全量单测 | `python -m unittest discover -s tests -v` | **Ran 412 tests, OK** ✅ |

- 无失败/error；基线 411 → 本轮 **412**（+1，非本轮改动引入的失败）。

## 2. 容量校验输出原文

```
W= 20 pool= 24
['quote'] tick= 4 coverage= 213 coverage_codes= 106 C1_OK
['quote', 'fundflow', 'timeline'] tick= 4 coverage= 213 coverage_codes= 53 C1_OK
```

- **两行均 C1_OK 且 cc≥50** ✅，与预期 **213 / 106 / 53** 逐位一致。
- 模型自洽：`quote` 成本 2（basic+depth）、3 域成本 4；`int(0.8×4×20/0.3)=213`，`213//2=106`、`213//4=53`。

## 3. 部署状态 + 日志

```
docker compose up -d --build → Image Built → Container Recreated → Started
china-finance-rss | Up 14 seconds
logs (error|traceback): no errors
healthz=200
```

- 重建成功，`healthz=200` ✅。
- 压测全程日志过滤 `error|traceback|warn|capacity|degrad|slip|timeout` → **仅 1 条正常启动行**（`Cache TTL: 30s | Timeout: 10s`），**无 error/warn** ✅。

## 4. 4A 验收：50 码 × quote（quote-only）

| 指标 | 实测 | 判定 |
|---|---|---|
| `refresh_capacity_codes` | **106** | ✅ |
| 模型分支 | C1（2×50=100 ≤ 213） | ✅ |
| `refresh_lag_ticks` | 采样 max **0** | ✅ 无 shard |
| **冷启动首帧**（进程冷，重建后首个订阅） | **9.87s** | ❌ **>4s** |
| 冷启动首帧（复测1，idle 10s 后） | 3.40s | ✅ |
| 冷启动首帧（复测2） | 4.31s | ⚠️ 超 4s 仅 7.7% |
| 稳态帧间隔 | run1 `[3.82,4.32,3.68,4.32,3.68,4.36,3.64]` avg **3.97s**（min3.64/max4.36） | ✅ ~4s |
| 帧内容 | `missing=0, stale=0, items=50, nonnull=50` × 全帧 | ✅ 严格全量 |
| `stream_tick_duration_ms` | max **4179.81ms**（进程冷首 tick） / 复测 1591.6 / 403.3 | ⚠️ 冷首 tick 超 tick |
| 指标增量 | degraded **1** / slip **1**（均来自冷首 tick）；dropped/slow/503 = **0** | ⚠️/✅ |
| 单帧字节 | 58,925 B | ✅ |
| 上游吞吐 | quote 7.33 + depth 5.95 call/s | — |

**4A 判定：稳态节拍 ✅（avg 3.97s）、冷启动首帧 ❌（9.87s）。**
差距分解（量化）：`冷首帧 9.87s = 等待空闲网格 ≈5.69s + 冷启动首刷 4.18s`。
- 空闲期无活跃订阅 ⇒ `push_loop` 跑在 **L1=8s** 网格（`tick_interval([])=8`），首个订阅要等下一次网格点（本次 ≈5.69s）；
- 进程首个真实 refresh 为冷路径（无池/无 DNS 缓存），50 码 × 2 域 = 100 call 耗时 **4.18s > 4s tick** ⇒ degraded+1、slip+1。
- 池温后复测冷启动首帧 3.40s / 4.31s（不再触发 degraded/slip）。

## 5. 4B 验收：50 码 × 3 域（quote+fundflow+timeline）· 两次独立建组冷启动

> 每次均新建组→立即连 SSE→测完 DELETE（避免复用 sid 掩盖）。

| 指标 | B1（冷启动①） | B2（冷启动②） | 判定 |
|---|---|---|---|
| `refresh_capacity_codes` | **53** | **53** | ✅ ≥50 |
| 模型分支 | C1（4×50=200 ≤ 213） | C1 | ✅ 无 2-tick shard |
| `refresh_lag_ticks` | max **0** | max **0** | ✅ |
| **冷启动首帧（≠ 上一轮 12.33s）** | **2.53s** | **0.97s** | ✅ **≤8s** |
| 首个严格全量帧 | 2.53s（首帧即全量） | 0.97s（首帧即全量） | ✅ |
| 全量帧数 / 挂接帧数 | 10/10 | 10/10 | ✅ |
| 帧间隔 | `[2.32,4.32,3.73,5.07,3.59,3.69,3.69,5.12,3.52]` avg **3.89s** | `[4.89,3.12,4.07,4.10,4.84,2.67,4.57,4.21,4.22]` avg **4.08s** | ✅ ~4s |
| `missing` / `stale` | `[0]*10` / `[0]*10` | `[0]*10` / `[0]*10` | ✅ 三域全员每帧 |
| `items` / `nonnull_codes` | `[50]*10` / `[50]*10` | `[50]*10` / `[50]*10` | ✅ |
| `stream_tick_duration_ms` | max 1710.98 / avg 583.6 | max 1427.38 / avg 718.4 | ✅ ≪4s |
| degraded / slip / dropped / 503 | 0/0/0/0 | 0/0/0/0 | ✅ |
| slow_client 增量 | 0 | **+2** | ⚠️ 见 §7 |
| 单帧字节（max） | **2,256,914 B（~2.15 MiB）** | **2,267,829 B（~2.16 MiB）** | 见 §7 |
| 上游吞吐 | quote 7.58 + depth 7.29 + ff 7.12 + tl 7.14 call/s | quote 6.40 + depth 6.16 + ff 6.92 + tl 7.00 call/s | — |

**4B 判定：✅ 达标**（两次独立冷启动首帧 2.53s / 0.97s，远优于 8s；上一轮 12.33s 的 2-tick shard 已消除，lag=0）。
- 说明：B1/B2 的"冷"是**订阅组侧冷**（新组无帧缓存）＋上游缓存已过 TTL；**进程冷**的最坏样本是 §4 的 4A 首脑（9.87s），B 若在进程冷时首发，理论上同量级。

## 6. 4C 五档三态确认（sh600519 普通股 / bj430047 北交所 / sh000001 指数）

| 码 | 类型 | `depth` 键 | 五档值 | 判定 |
|---|---|---|---|---|
| sh600519 | 沪市普通股 | **有**（4/4 帧） | 非 0：`b_px_1 1262.0 … s_px_5 1262.2`，`preclose_px 1258.0` | ✅ |
| bj430047 | 北交所 | **无**（0/4） | keys=`code,data,msg`（无 `depth`） | ✅ |
| sh000001 | 指数 | **无**（0/4） | keys=`code,data,msg` | ✅ |

- 全 0 假档（`zero_only`）= **[]** ✅（解析层对 index 全 0 载荷返回 `None`，不落 `depth` 键）。
- 结论：五档三态行为与设计一致 **✅**。

## 7. 4D 帧体积与丢弃

| 项 | 实测 | 判定 |
|---|---|---|
| 3 域 50 码单帧（max） | **2,256,914 B / 2,267,829 B（~2.15–2.16 MiB）** | 接近预估 ~2MB |
| 帧峰值 gauge `stream_frame_peak_bytes` | 2,267,165 B | — |
| 单客户端带宽（B2） | 2.25 MB / 4.08s ≈ **552 KB/s** | — |
| `stream_frame_dropped_total` 增量 | **0** | ✅ 无丢弃 |
| `stream_slow_client_total` 增量 | B1 **0**、B2 **+2** | ⚠️ 慢客户端被触发 2 次（未丢帧） |
| `http_503_total` 增量 | 0 | ✅ |
| `stream_queue_bytes` | 0 | ✅ |

- B2 出现 slow_client +2：单客户端 2MB/帧消化慢于 tick；当前有 `queue(maxsize=8)` 兜底，未产生 dropped。**fan-out 放大风险点**（与 r2 §7 同源），本轮不阻断。
- 观察：B 档帧间隔最小 2.32s / 2.67s（< tick 4s）。经复核为**客户端 2MB 帧收包/解析节拍压栈**（脚本以 recv 到达时刻打时间戳）而非服务端下发短突发；帧内容逐帧变化，**未出现"2s 背靠背重复帧"**，故非 BR-STR-27 回退。

## 8. preclose_px 调查结论（只读，未改代码）

### 8.1 sh601091 直查（basic vs volume?field=five）

| 字段 | `basic` | `volume?field=five` |
|---|---|---|
| `secu_name` | **N沈鼓**（新股上市首日） | — |
| `last_px` | 13.42 | — |
| `preclose_px` | **4.39** | **4.39** |
| `open_px` / `high_px` / `low_px` | 13.0 / 14.5 / 11.73 | — |
| `change_px` / `change` | 9.03 / **2.0569（+205.7%）** | — |

- 两接口 `preclose_px` **完全一致**；上游自身 `change` 也用 4.39 计算 ⇒ 上游语义自洽。

### 8.2 抽 10 码统计 `|preclose_px - last_px| / last_px`

| 码 | 名称 | last | pre(basic) | pre(vol) | ratio |
|---|---|---|---|---|---|
| sh601091 | **N沈鼓** | 13.40 | 4.39 | 4.39 | **0.6724** ← 唯一异常 |
| sz300434 | 金石亚药 | 12.49 | 10.41 | 10.41 | 0.1665 |
| sz300741 | 华宝股份 | 27.17 | 22.64 | 22.64 | 0.1667 |
| sz301390 | 经纬股份 | 45.00 | 37.50 | 37.50 | 0.1667 |
| sh688137 | 近岸蛋白 | 99.90 | 84.00 | 84.00 | 0.1592 |
| sh688296 | 和达科技 | 27.22 | 24.31 | 24.31 | 0.1069 |
| sh600127 | 金健米业 | 13.02 | 11.84 | 11.84 | 0.0906 |
| sz000725 | 京东方Ａ | 5.74 | 5.45 | 5.45 | 0.0505 |
| sz002080 | 中材科技 | 58.73 | 55.88 | 55.88 | 0.0485 |
| sh603082 | 北自科技 | 51.49 | 52.98 | 52.98 | 0.0289 |

分布：`n=10, min=0.029, p50=0.159, max=0.672`；**9/10 < 0.20**（均在当日涨跌停幅度内，且与 `change` 一致），**1/10 = 0.672（仅 sh601091）**。10 码 `basic.preclose_px == volume.preclose_px`（断言全过）。

### 8.3 原因判定

| 假设 | 结论 |
|---|---|
| ① 当日除权除息 | ❌ 非除权；是 **新股上市首日（N 前缀）** |
| ② 上游 preclose 语义不同 | ✅ **成立**：上市首日 `preclose_px` = **发行价（4.39）**，非"昨收"；上游 `change` 亦按此口径 |
| ③ 上游数据质量 | ❌ 数据自洽（change/changepx/preclose 三者一致） |
| ④ 我们取错字段 | ❌ 我们**原样透传**上游 `data` 整包；basic 与 volume 两接口一致 |

### 8.4 `depth` 是否需要处理 `preclose_px`

- **不需要特殊处理**：`depth` 是纯透传字段，当前代码**不**用它计算涨跌幅/涨跌停（涨跌幅来自 `basic.change`），故异常值不会污染业务语义。
- 若**未来**用 `depth.preclose_px` 自行算涨跌幅 ⇒ 必须对"新股上市首日"特判（或直接采用上游 `change`）。
- 可选优化（低优先）：`depth.preclose_px` 与 `basic.preclose_px` 完全重复，从 `depth` 移除可缩帧（约 20 B/码，50 码仅 ~1 KB，收益微小）。

## 9. 资源 + 上游负载

```
china-finance-rss  cpu=5.70%  mem=620.6MiB / 1.5GiB
```

- CPU/内存均无压力，无 OOM/限流；`mem_limit=1.5g` 余量充足。
- 上游吞吐（压测前后 healthz 增量，窗口 ≈149s）：

| 域 | 增量 | call/s（整体均值） | 各档实测 call/s（A / B1 / B2） |
|---|---|---|---|
| quote | 896 | 6.0 | 7.33 / 7.58 / 6.40 |
| depth | 809 | 5.4 | 5.95 / 7.29 / 6.16 |
| fundflow | 594 | 4.0 | — / 7.12 / 6.92 |
| timeline | 595 | 4.0 | — / 7.14 / 7.00 |
| announcement | 5 | 0.03 | 背景 |
| **fail 总量** | **0** | — | **无失败** ✅ |

- 说明：3 域订阅在 tick=4 下，fundflow/timeline（TTL=8s）命中缓存于隔拍，故其 call/s（~7）低于"每帧 50 码"名义值，**未因 4s tick 翻倍上游负载**（按域分拍生效）。

## 10. 总结论 + 清理

### 结论

| 验收项 | 结果 |
|---|---|
| 编译 + 单测（412） | ✅ |
| 容量 213 / 106 / 53（两行 C1_OK） | ✅ **与预期逐位一致** |
| 4B 50×3域 冷启动首帧 ≤8s（×2 独立建组） | ✅ 2.53s / 0.97s（上轮 12.33s 已修复） |
| 4B lag=0 / stale=0 / 三域不饿死 | ✅ |
| 4A 50×quote 稳态节拍 ≤4s | ✅ avg 3.97s |
| **4A 50×quote 冷启动首帧 ≤4s** | ❌ **9.87s**（进程冷首脑） |
| 4C 五档三态 | ✅ |
| 4D dropped=0 | ✅（slow_client +2，非阻断） |
| 上游 fail | 0 ✅ |

**唯一定量未达标：4A 进程冷启动首帧 9.87s（超 ≤4s 指标 5.87s；超 ≤8s 最坏 1.87s）。**
量化分解：空闲 L1=8s 网格等待 **≈5.69s** + 进程冷首个 refresh **4.18s**（100 call，>4s tick ⇒ degraded+1/slip+1）。

**整改建议（本轮未实施，供决策）：**
1. 从"无活跃订阅"（idle，L1=8s）转为"首个活跃订阅"时，**立即触发一次刷新**而非等下一次网格点 → 消除 ≈5.69s 等待；
2. 进程启动时**预热连接池 / 首 tick 不计 slip**，或对冷首 tick 采用独立预算 → 消除 4.18s 冷刷超 tick；
3. 二者任一即可使"进程冷启动首帧"落入 ≈4s；二者结合可稳定 ≤4s。

### 无损复用 / 逆向观察（记录，不阻断）
- `sh601091` 被标记为 `N沈鼓` 新股首日，其 `depth.preclose_px` 与 `last_px` 合理性差异**非缺陷**（§8）。
- `sz000725` 在 4A 中偶现 `depth` 键时有时无（上游空包/超时 → 以 `None` 省略，未伪造）——建议关注上游对该码 depth 的稳定性，非本轮回归。
- B2 `slow_client+2`：2MB/帧下的慢客户端；queue=8 兜底未丢帧。

### 清理
- 本轮所有订阅组测完即 `DELETE`（4A/B1/B2/复测/4C 全部返回 `200 {"deleted":true}`）。
- 收尾健康态：`stream_tick_duration_ms=0.12`、`stream_refresh_lag_ticks=0`、`stream_frame_distinct=0`、`stream_queue_bytes=0` ⇒ **无残留活跃组** ✅。
- 只测 SSE，未改任何代码/配置，未执行 `docker stop`。

### 产出物
- 报告：`doc/tester/P1_SSE复测_preclose调查_报告_r1.md`（本文件）
- 原始数据：`doc/tester/sse_recheck_p1_out.json`
- 脚本：`doc/tester/sse_recheck_p1_round.py`
