# 对抗性盲审报告 — P6c「高效/准确/稳定」改造

- **模式**: P8 对抗性盲审（`>>MODE: blind`，零上下文）
- **需求原文**: 用户诉求——「当前系统是提供短线交易系统使用……系统处理与响应来说必要高效准确且稳定。所以请对当前系统进行全面检查尽量往这些指标靠近。」
- **改动范围**: 全系统 8 模块（config / cache / metrics(新增) / stock_api / market_api / cdp_engine / server / stream）+ tests/
- **执行**: 两组独立 code-reviewer 并行（基础层+数据层 / HTTP+SSE 层），禁带任何前序评审或测试结论
- **结论**: **P0 = 0（无阻断）**；P1 × 11、P2 × 15

---

## 一、P1 问题（11 项）

### 基础层 + 数据层（6 项）

| # | 位置 | 问题 |
|---|------|------|
| S1-1 | `cache.py:228` + `236-241` | **单飞 follower 的等待预算与 leader 网络预算相同** ⇒ leader 的"网络返回→状态发布"耗时超过 follower 等待窗口时，follower 落入 gap 分支，被误判为 `upstream_error`（真因是发布延迟）；该 kind 还会被写入 120s 冷却账本 ⇒ 健康码被静默冻结；`239` 注释"Unreachable" 错误，测试零覆盖该分支 |
| S1-2 | `stock_api.py:1014` | **prefetch 游标欠推进**：`_prefetch_advance(name, processed + skipped, len(codes))` 中"已处理数"≠"已消耗数"（取数成功但数据为空、冷却跳过均可能不计数）⇒ 头部被反复重取、池尾永久得不到 prefetch；极端下 `processed+skipped==0` 时游标**永不移动** |
| S1-3 | `stock_api.py:139-153/179/188` + `metrics.py:99-107` | **失败账本每次写入做 O(n) 全量快照并持全局锁**（账本上限 10000）⇒ 故障规模越大失败路径越贵（二次增长），CPU 尖峰恰好发生在最需要响应时（降级自放大） |
| S1-4 | `cache.py:105/110-111`、`151-152` + `metrics.py:131-137` | **metrics 写入位于 `_cache_lock`/`_neg_lock` 临界区内**，而 `snapshot()` 持同一把锁深拷贝全注册表 ⇒ `/healthz` 轮询可阻塞整条取数热路径（`metrics.py` 声明的"never blocks business code"不成立） |
| S1-5 | `stock_api.py:3-6/220-239` + `cache.py:162` | **R13 deadline 未穿透到 `fetch_json`/`urlopen`**（`fetch_json` 无 deadline 形参）⇒ 通过时间门的调用仍可再跑 10s，`_BATCH_BUDGET_REST=15` 的 AC-E2 最坏可到 ~25s；CDP 路径已钳制，仅 REST 有洞 |
| S1-6 | `cache.py:114-123` + `136-147` | **慢（非死）上游被钉在 2s 探测预算上最长 600s**（`first_at` 起算）⇒ 一次 5s 抖动被放大为 10 分钟的"负缓存门 + 2s 超时"循环，客户端看到"上游挂了" |

### HTTP + SSE 层（5 项）

| # | 位置 | 问题 |
|---|------|------|
| S2-1 | `stream.py:347-362`（+`329-341`,`526-528`） | **帧静默缺码，"full-snapshot" 契约不成立**：C2 分片下每帧可能只剩 ~7/200 个新刷标的，其余已订阅标的被静默省略且无任何标记；`_errors`/`_dropped_count` 被 `_` 过滤丢弃；客户端无法区分"无行情/上游挂了/被丢弃"；测试用永不失效的假 cache 掩盖了该路径 |
| S2-2 | `stream.py:701-704`/`736-740`（+`488`） | **帧字节预算准入 cap 无单帧余量**：128MiB 恰好容纳 9 个满配组（余量 7.0MB < 单帧 14.13MB）⇒ 边界合法配置下每 tick 9 次淘汰（`stream_frame_dropped_total` 1/tick/group），AC-E5"不迫使每 tick 淘汰其他组真实帧"在该边界不成立 |
| S2-3 | `server.py:992-997`（+`1005-1014`,`849-851`） | **信任 Host/X-Forwarded-Host 生成 URL 却声明 public 可缓存**（且未发 `Vary: Host`，`PUBLIC_BASE_URL` 默认空）⇒ 缓存投毒/链接劫持：伪造 Host 可得到指向攻击者域名的 feed，中间缓存可回灌其他订阅者 |
| S2-4 | `stream.py:140-148` | **`_valid_fields` 失败开放**：未知字段被静默放大为全部 3 域（`fields=["nonsense"]` → 3 域）⇒ 帧字节与上游成本放大 3×，客户端拿到的结构与请求不一致且无错误信号；字段错误无法经 PATCH 纠正 |
| S2-5 | `server.py:853-863` | **`/healthz` 自身计算失败时仍返回 HTTP 200**（`_guard` 返回 `{'error':...}` 无 `status` 键 ⇒ 状态码取 200）⇒ 探活把"健康检查已坏掉"判为健康 |

---

## 二、P2 问题（15 项，摘要）

**基础+数据层（6）**：①`stock_api._direct_fetch` 是第二个 HTTP 入口，绕过 `fetch_json` 的 URL 缓存/负缓存/单飞（违反约定"统一走 fetch_json"）；②废弃别名 `CACHE_TTL`（`config.py:291`）仍在且 import 时冻结、`utils.py:12` 仍引用 ⇒ 删除会 ImportError；③per-domain `encoding` 权威无任何生产消费者（硬编码 `'gbk'` 与矩阵可静默漂移）；④`_fetch_one` 的 `except TypeError` 回退吞真实 TypeError、破坏 deadline 传递且可能二次执行取数；⑤`cdp_engine._last_data` 硬上限淘汰未同步清理 `_last_data_ts`/`_key_last_seen` ⇒ 小幅无界增长；⑥`_is_trading_hours` 不看交易日历 ⇒ 休市日按盘中计算（上游请求量 ×15，且看门狗整日拒重启）

**HTTP+SSE 层（9）**：①`push_loop` 异常路径脱离 tick 网格退化为 ~1s 连发（8× 上游压力正反馈）；②`_refresh_pool` 的 `now` 是死参数（测试钩子无效）；③`patch_group` 对 destroy 不原子（可致 200 假成功或 AttributeError）；④股票代码未归一化（`SH600519` vs `sh600519` 双份；正则 `$` 允许末尾换行）；⑤4 个 CDP 面板获得 `max-age=300`（L4），实时面板可被缓存 5 分钟；⑥`_JSON_SHAPES` 不被路由消费（"结构守卫"名不副实）；⑦`RSSHandler` 只捕两种断连异常（`TimeoutError ⊂ OSError` 漏网，与 stream 侧不一致）；⑧准入只约束连接数不约束派生线程数（最坏 ≈20×8 抓取线程 + …，无全局线程预算）；⑨`http_503_total` 不是 503 总数（stream 连接满、healthz degraded 均未计数）；⑩死代码/死导入（`SubscriptionGroup.payload_bytes()`、server 三个未用导入）

---

## 三、测试有效性（独立命中，★ 重点）

盲审发现多处"测试绿但掩盖缺陷"：

| # | 位置 | 问题 |
|---|------|------|
| T1 | `test_server.py:377-402` | 用手工推进值守"游标公平性"，**生产调用方的计数语义零覆盖**（与 S1-2 同源） |
| T2 | `test_data_layer.py:485-505` | patch 掉 `_prefetch_rotate` ⇒ 绕过 `_prefetch_advance` 的真实输入 |
| T3 | `test_data_layer.py:107-122` | 把"零网络的本地预算耗尽"断言为应记账本 ⇒ **固化了"自身超时=上游失败"的耦合**（S1-1/S1-5 误判沿此路径放大） |
| T4 | `test_stream.py:680-683` | 用永不失效的假 cache 断言 `len(snap)==300` ⇒ **掩盖 C2 分片下的静默缺码**（S2-1） |
| T5 | `test_stream.py:1276-1293` | 只断言 working-set ≤ budget，**未断言边界 tick 的丢弃数为 0**（S2-2） |
| T6 | `test_stream.py:964-974` | `PushLoopWiringTests` 只断言 `_push_once` 被调用，异常路径零覆盖 |
| T7 | `test_cache.py` | follower 超时 gap 路径无任何用例（S1-1） |

---

## 四、盲审结论

- **无 P0** ⇒ 按流程不阻断，可继续。
- 但 **P1 × 11** 中多条直接命中需求原文的"准确"与"稳定"：静默缺码（S2-1）、误判污染冷却+数据冻结（S1-1）、降级自放大（S1-3）、监控阻塞热路径（S1-4）、deadline 失效（S1-5）、缓存投毒（S2-3）。
- **测试有效性问题（T1-T7）与 P1 高度同源**：多处"绿测"恰好绕过了缺陷路径，说明"测试全绿"不能作为本轮交付的充分证据。
- 建议：优先闭环 P1（尤其静默类与安全类），并同步修正对应的"假绿"用例。
