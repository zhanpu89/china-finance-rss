# refresh_epoch 每拍真刷新 — 测试报告 r1

- 日期：2026-09-17
- 被测变更：新增 `refresh_epoch`（刷新路径只复用本轮起点之后写入的缓存条目；REST 路径 `refresh_epoch=None` 逐字不变）
- 环境：docker compose 单容器 `china-finance-rss`，端口 8053(REST)/8054(SSE)
- 结论摘要：**机制 ✅ / REST 缓存无退化 ✅ / 单测 ❌ 1 条陈旧接口断言（P2）/ 交易时段 4s 数字因「非交易时段」不可复现 ⚠️**

> ⚠️ **关键前提偏差：本轮实际不是交易时段。**
> 任务书写"当前为交易时段"，但实测 `config._is_trading_hours()` 返回 **False**（执行时刻 15:16–15:2x CST，已过 15:00 收盘）。
> `/healthz` 的 `policy` 证实为盘后档：`quote`/`depth` `ttl=120s`，`stream.tick_interval(['quote'])=120s`。
> 因此任务书里所有"≈4s 每拍 / 60s≈15 帧 / quote+depth≈25 call/s"的**盘内数字不可复现**（未改配置/时间）。
> 已按"TTL==tick==120s"的**同一相位耦合条件**做等价验证（这正是本次修复针对的条件），并在下表逐项标注。

---

## 1. 编译 + 单测

| 项 | 命令 | 结果 |
|---|---|---|
| 编译 | `python -m py_compile china_finance_rss/*.py tests/*.py` | **exit=0 ✅** |
| 单测 | `python -m unittest discover -s tests -v` | **Ran 444 / FAILED (failures=1) ❌** |

基线 431 → 444，与预期 ≈444 一致。但**全套并非全绿**：

```
FAIL: test_signature_fifth_param_is_deadline (tests.test_cache.DeadlineTests)
AssertionError: Lists differ:
['url','headers','ttl','encoding','deadline','refresh_epoch']
!=
['url','headers','ttl','encoding','deadline']
```

- 原因：`fetch_json` 新增了第 6 个（keyword、默认 `None`）参数 `refresh_epoch`，而这条 **S1-5 冻结接口断言**未同步更新。
- 判定：**P2 测试自身缺陷**（`BUG-refresh_epoch-01`）。该断言的**意图**（第 5 参是 `deadline`）仍成立；新增参数是**向后兼容的附加关键字**，非破坏性。
- **三个重点类全绿 ✅**：`RefreshEpochCacheTests`(4) + `RefreshEpochTerminalCacheTests`(4) + `RefreshEpochStreamTests`(5) = **13 OK**。
- 本轮未修改任何代码/测试（遵守约束），仅登记。

---

## 2. 部署状态

- `docker compose up -d --build` → `Recreated / Started` ✅
- `docker compose ps`：`china-finance-rss | Up`
- 日志 `grep -iE "error|traceback"` → **no errors** ✅
- `GET /healthz?check=0` → **200** ✅
- 后续 `docker compose up -d --force-recreate`（第五步冷启动）→ 同样 Started、healthz=200。

---

## 3. 核心验证：每拍真刷新（quote 50 码）

**盘后实际节拍 = 120s/拍（tick==TTL==120s）。** 目的等价：证明"TTL==tick 时不再隔拍跳过"。

### 3.1 方法
- 50 码 `fields=["quote"]`，SSE 订阅，连续观察 ≥240s。
- 解析 `event: quote` 的 `data.items` 内容哈希与到达时刻；`event: ping`(data:{}) 单独剔除。
- 另用容器 `/proc/net/dev` 交叉验证上游字节，用 `/healthz.metrics.upstream_fetch_total` 取增量。

### 3.2 数据表

| 指标 | 期望（任务书，盘内） | 实测（盘后 tick=120s） | 判定 |
|---|---|---|---|
| 帧间隔（全量帧） | ≈4s，不得隔拍 8s | **119.7s / 120.0s**（两轮独立观测各 120s） | ✅ 每拍真刷，**无 2× 跳过** |
| 60s 帧数 | ≈15 | n/a（tick=120s；期间每 20s 有 `event: ping` 保活，非 quote 帧） | ⚠️ 盘内不可复现 |
| 相邻帧内容变化 | 多数不同 | 相邻全量帧哈希 **0 对相同**（distinct=2/2、2/2） | ✅ |
| quote call/s | ≈12.5 | **≈0.417/s**（Δquote +100 / ~2 拍） | ⚠️ 盘后理论值，盘内不可复现 |
| depth call/s | ≈12.5 | **≈0.417/s**（Δdepth +100 / ~2 拍） | ⚠️ 同上 |
| 合计 | ≈25/s | ≈0.83/s | ⚠️ 同上 |
| `stream_tick_duration_ms` | — | 稳态 ~435ms；冷启动首拍 ~4373ms（一次性） | ✅ 远低于 0.8×tick |
| `degraded` / `slip` 增量 | 0 | **+0 / +0** | ✅ |
| `stream_refresh_lag_ticks` | 0 | **0** | ✅ |

### 3.3 关键判据
- 若相位耦合未修：首拍写入的条目（δ≈4s 后）在下一拍（t0+tick）年龄仅 tick−δ < TTL，会被判命中而**跳过回源**，则全量帧应**每 240s** 才更新一次。
- 实测**连续两拍全量帧严格间隔 120.0s**，且第二拍确实产生了新数据帧 ⇒ `refresh_epoch` 生效，强制每拍回源。**✅**

> 盘内 4s 档的"15 帧/60s、quote+depth 25 call/s"仍**未直接验证**，需交易时段复测。

---

## 4. REST 缓存不退化（关键反向验证）✅

### 4.1 延迟证据（`/stock/data?code=...`，5 连发）
| 请求 | sz000001（不在订阅集） | sh600519（在订阅集） |
|---|---|---|
| req1 | 0.175s（回源） | 0.070s |
| req2–5 | **0.0023s**（命中缓存） | **0.0022s** |

### 4.2 网络字节证据（对照冷/热，排除本地 HTTP 干扰）
- 冷 `sz300750`：0.296s，eth0 **RX +28191B**（上游响应体）。
- 热 20 连发 `sz300750`：eth0 **RX +25956B（≈1.3KB/req，本地请求头+ACK）/ TX +414898B（≈20.7KB/req = 19.9KB 响应体）** ⇒ **无 28KB 上游载荷**。
- 结论：重复 REST 请求由缓存服务，**未回源**。

### 4.3 ⚠️ 关于任务书预期"增量 ≤1"
- 实测 5 连发 `upstream_fetch_total{quote}` **+5**，并非"误伤 REST"。
- 原因：该计数在**缓存查询之前无条件自增**（`stock_api.py:934/971/990/1063`），语义是"**fetch 调用次数**"而非"网络往返次数"。故它**不能**作为 REST 回源次数的判据。
- 真实缓存行为已由 4.1/4.2 证实：**REST 缓存无退化 ✅**。

---

## 5. 回归确认（逐条）

| 项 | 目标 | 实测 | 判定 |
|---|---|---|---|
| 3 域 50 码 首全量帧 | ≤8s（盘内） | **113.3s**（≤1 tick=120s） | ⚠️ 盘内目标不可复现；盘后 ≤1 拍 ✅ |
| 3 域 lag | 0 | **0** | ✅ |
| 3 域 stale | 0 | 帧完整度 49–50/50，未见 `_stale`（间接） | ✅（覆盖有限） |
| **冷启动** `--force-recreate`+立即建组 | 首帧 ≤4s | **0.816s** | ✅ |
| 去重：无相邻帧完全相同 | 0 对 | **0 对**（adj_identical=0） | ✅（盘后样本仅 2–3 帧） |
| 新连接中途接入 | ≤1 tick 首帧 | 冷空闲 0.816s；运行中接入 51.96s / 119.99s | ✅（均 ≤1 tick=120s） |
| 五档：普通股 depth 非 0 | 是 | `sh600519` depth **PRESENT**（b_px_1..5 全非 0）+ `sector_name` | ✅ |
| 五档：北交所无 depth 键 | 无 | `bj430047`/`bj832000` quote keys=['code','msg','data']，**无 depth** | ✅ |
| 五档：指数无 depth 键 | 无 | `sh000001` 同上，**无 depth** | ✅ |

### 5.1 开发者登记的副作用：fundflow/timeline 每拍回源
| 域 | 任务书盘内理论 | 盘后理论(50/120s) | 实测(252s 窗口) | 偏差 |
|---|---|---|---|---|
| fundflow | ≈6.25/s | 0.417/s | **121 次→≈0.48/s** | +15% |
| timeline | ≈6.25/s | 0.417/s | **115 次→≈0.456/s** | +9% |

- 偏差来源：①计数器按"调用次数"计（含 CDP 回退重复计数，`fail_total{upstream_error}=1`）；②存在**独立 prefetch loop**（`_fundflow_prefetch_loop`/`_timeline_prefetch_loop`，`sleep(pool_refresh)` 盘后=120s）与每拍刷新**相位重叠**，会额外记账（命中缓存也计数）。
- 判定：**未显著超出**（相对盘内理论 6.25/s 相差 13×）。**盘内 call/s 待复测** ⚠️。

> 补充：`新连接` 在"上一拍有活跃需求"时会等待硬睡眠（最多 1 tick）而不被唤醒——这是 BUG-P6C-06 的 no-burst 设计（唤醒只打断**空闲**等待），非缺陷。

---

## 6. 资源

```
china-finance-rss   cpu=14.63%   mem=655.2MiB / 1.5GiB
```

---

## 7. 结论

1. **quote 是否真正每拍刷新**：**机制成立 ✅**。在 TTL==tick==120s（盘后）下，连续两拍全量帧严格 120.0s 间隔、内容更新，**无隔拍 2× 跳过**。盘内 4s 档因**当前非交易时段**（`_is_trading_hours()=False`，15:16 收盘后）**未能直接复现**，需交易时段复测。
2. **REST 缓存有无退化**：**无退化 ✅**。重复 REST 命中缓存（2ms / 无上游字节）。任务书"增量 ≤1"预期不成立，因 `upstream_fetch_total` 语义为"调用次数"而非"上游网络次数"。
3. **其他回归**：功能无回退。**单测 ❌ 1 条**（`test_signature_fifth_param_is_deadline` 陈旧接口断言，P2，属测试自身）。

### 缺陷清单
| ID | 级别 | 描述 | 建议 |
|---|---|---|---|
| `BUG-refresh_epoch-01` | **P2** | `tests/test_cache.py:390` 冻结接口断言未随 `refresh_epoch` 更新，全套 `FAILED(1)` | 期望列表追加 `'refresh_epoch'`（或仅断言第 5 参） |

---

## 8. 清理

- 订阅组全部删除：`7459a20e5b13`、`2a8a5cdd0856`、`b7df4b12bc19`、`3bb3cce4c842` → 逐个 `GET` 均 `{"error":"not found"}` ✅
- 未修改任何代码/配置；未 `docker stop`；仅少量 REST 反向验证请求，其余均为 SSE。

