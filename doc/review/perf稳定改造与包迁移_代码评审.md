# perf 稳定改造 + 裁决落地 + 包迁移 — 代码评审（focused review）

- **评审对象**: `cbc472a`（perf 8 模块改造，368 测试）+ `d6c8f12`（降级恒 200 + 探测预算 5s 封顶）+ `d5062eb`（扁平包迁移，含 Dockerfile CMD）
- **评审模式**: focused review（非盲审，无 drifts 标记 → 无 P7 漂移节）
- **评审基线**: HEAD `e32904d`（fast-forward 链全量合入；读当前文件即为合并后状态）
- **CR 编号**: CR-2026-0916-01
- **评审日期**: 2026-09-16

---

## 评审概要

三连提交对前序 43851ee 等 8 个修复的核心防线**完整保留、未弱化**：僵尸组 sweep/TOCTOU、full_chrome_restart 锁内节流、广播有界队列丢旧保新、CDP 目标账本硬上限、探测预算阶梯——逐一在 HEAD 文件上找到对应行级实现，且均有配套测试。

d6c8f12 两项裁决落地精确：`_send_json` 去除 status 形参恒 200 与 `_probe_budget` 2→4→5s 封顶均按契约实现，API.md 已同步（630 行）。metrics 模块锁设计正确（深克隆在锁外），包迁移干净（根目录零 .py，Dockerfile CMD 正确）。

**总评：3 个 P2，无 P0/P1，可合并。** 最重要的 2 条改进建议：① TOCTOU 重连竞态分支缺专项测试（E 维度覆盖缺口）；② Dockerfile `EXPOSE` 缺 8054（D 维度文档性遗漏）。

---

## 维度 A — 既有修复回归（8 项全部 ✅）

| 修复点 | 状态 | 证据 |
|---|---|---|
| `_active_deduped_codes_unlocked` | ✅ | stream.py:195-205，仅含活动组 codes；`_active_targets`(235-246) 在**单次锁**内读取 codes+fields（BUG-P6C-06 原子性保留） |
| `_sweep_idle_groups` + TOCTOU 重查 | ✅ | stream.py:729-752；收集后**锁内**重查 `if g.conns: continue`（742-748），锁序 groups→conns 无环 |
| `_GROUP_IDLE_TTL` / STREAM_GROUP_IDLE_TTL | ✅ | config.py:46 `float(os.getenv('STREAM_GROUP_IDLE_TTL', '300'))`；stream.py:725 消费 config 常量（单一数据源） |
| `full_chrome_restart` 锁内节流 | ✅ | cdp_engine.py:381-385：`with _chrome_restart_lock:` 内 `if now - _last_chrome_restart < _CHROME_RESTART_THROTTLE * 2` 精确保留；`_CHROME_RESTART_THROTTLE` 由 config.py:182 注册（不再直读 env） |
| 广播满队列丢旧保新 | ✅ | stream.py:704-719：`_frame_acquire` → `put_nowait` → `except Full` → `_pop_oldest_frame`(get_nowait) → `_frame_release` → 重 `put_nowait`；`_SSEConn.q = queue.Queue(maxsize=8)`(535) |
| 缓存 maxsize / URL 缓存 2000 / 池上限 | ✅ | cache.py:29 `MAX_CACHE_SIZE = 2000`；DOMAIN_MATRIX `cache_max` 逐域保留（quote/fundflow/timeline=2000，f10/announcement=500，feed=100）；stock_api `_cache_store`(290) 消费 `cache_max` |
| config.py 既有配置迁移 | ✅ | STREAM_PORT/MAX_STREAM_CONNS/MAX_CODES_PER_SUB/MAX_DEDUP_CODES/MAX_GROUPS/LISTEN_BACKLOG/MAX_INFLIGHT/CDP_RESTART_THROTTLE/STREAM_GROUP_IDLE_TTL/STREAM_QUEUE_BYTES_BUDGET 等全部在 config.py:14-48 注册 |
| 信号-交易下游契约 | ✅ | `_rekey_batch_response`(server.py:636-663) 保留（canonical→requested 回键）；`build_batch_response`(cache.py:425) 仍是保留键唯一组装点 |

**无回归。** 8 项修复在 cbc472a 改造后未出现被覆盖、删除或弱化的迹象；env 默认值（300s TTL、15s throttle×2、2000 缓存、128 backlog）与迁移前一致。

---

## 维度 B — d6c8f12 裁决落地（2 项 ✅）

### B1 业务降级恒 200 ✅

- server.py:1136-1139 `_send_json(data, write_body, cache)` — **无 status 形参**，恒 200
- server.py:1141-1154 `_send_json_shape`：`_guard` 产出的降级体（`{'error': ...}` object / `_errors` batch）一律走 `_send_json` → 200
- `_handle_stock_batch`(1128)、`_serve_feed`(1184)、`/ths/longhu`(1075)、`/market/margin`(1086) 全部经 guard → 200
- **真实 503 仅两条路径**（与 N1 裁决一致）：`BoundedThreadPoolServer._reject_503`(1328，准入拒绝) 与 `/healthz` degraded(1037)。stream 端口 503（连接上限 stream.py:1209）属准入语义，不在裁决范围——正确。
- 既有 signal-trading 下游依赖 `200 + _error` 字段：`handle_margin` 降级返回 `{'latest':..., 'recent':[], '_error': kind}`(market_api.py:36) → 200 + `_error` 保留 ✓；API.md:630 已同步此语义
- 状态码不由 payload 内容决定（healthz 的 `'error' in payload → 503` 是 /healthz 自身语义，数据端点不共享，server.py:1031-1037 注释明确说明）

### B2 探测预算封顶 5s ✅

- cache.py:84 `_PROBE_BUDGET_CAP = 5.0`；:154-174 `_probe_budget`：PROBE_TIMEOUT(2) → `budget*2` → `min(budget*2, cap)` → 2→4→5
- **恢复延迟验证**：稳态黑洞 = 5s 探测 + 5s NEG_TTL = 10s 周期，P95≈5s ✓；aged-history 路径（`_HISTORY_AGE` 600s 后）`_fetch_budget` 返回 REQUEST_TIMEOUT=10s 一次性全预算探测，leader ≤10s、follower wait ≤11s（10s+1s margin）→ 单请求恒 <15s ✓
- **busy-loop 风险**：无后台探测线程；leader 在请求线程内阻塞 `urlopen`；follower 用 `event.wait(timeout=...)`(stream/cache 均无自旋)；`_reconnect`/`push_loop` 回退均含 `time.sleep(2)` 或网格对齐 sleep ✓
- 测试：test_cache.py:343 `test_probe_budget_escalates_then_caps`（断言 cap < REQUEST_TIMEOUT）✓

---

## 维度 C — metrics 模块架构质量（✅，锁设计正确）

1. **锁开销**：`snapshot()` 的 `_lock` 临界区仅做**浅拷贝**（metrics.py:162-168，dict `.copy()` + `list(v)`），深克隆 `_clone` 在**锁外**（:169）。~17 个注册名的浅拷贝在 µs 量级，/healthz 轮询不会阻塞业务写 ✓；`incr`/`set_gauge` 的 `_lock` 是 leaf lock，不被任何其他模块锁嵌套持有 ✓
2. **线程安全**：浅拷贝在锁内完成（P2-12 防护），锁外克隆迭代的是拷贝而非活对象 → 无 `list changed size during iteration`/torn values；`_warned` 无锁仅告警去重，竞态可容忍 ✓
3. **/healthz 集成**：server.py:970 payload 含 `'metrics': metrics.snapshot()`；`_KNOWN` 冻结名 + `_DEFAULTS` 零值发布（BUG-P6C-04 保留）；`_LABELED_GAUGES` 形状守卫（P2-13）
4. **度量发布纪律**（S1-4）：cache.py `_record_failure`/`_cache_put`/`_publish_url_stats` 均在释放锁后调用 metrics；stream.py `_frame_acquire`/`_frame_release` 同模式 ✓

无性能悬崖；无锁顺序违规。

---

## 维度 D — 包迁移正确性（✅，1 个 P2）

1. **根目录无顶层 .py** ✅：`ls` 根目录仅 `china_finance_rss/`、`tests/`、docs/scripts/docker 等；旧 server.py/stream.py 等已全部迁入包内
2. **__init__.py** ✅：暴露 `__version__`；真实入口为 `python -m china_finance_rss.server` 的 `main()`
3. **AGENTS.md** ✅：code entry 已更新为 `china_finance_rss/server.py`
4. **Dockerfile** ✅：`COPY china_finance_rss/ china_finance_rss/`（不复制根目录散件）、`CMD ["python", "-m", "china_finance_rss.server"]`
5. **requirements.txt** ✅：`websocket-client`（Xueqiu/CDP fallback 依赖）；无遗漏的新导入（imports 全为 `china_finance_rss.*` 相对导入 + stdlib + websocket）
6. **docker-compose.yml** ✅：`STREAM_HOST=0.0.0.0` 容器内绑定，端口映射 8053/8054 完整
7. **P2-1**：Dockerfile 仅 `EXPOSE 8053`，未声明 8054（见问题清单）

---

## 维度 E — 测试覆盖度（✅，1 个 P2 缺口）

368 测试全部通过（5.028s）。关键场景覆盖矩阵：

| 关键场景 | 测试位置 |
|---|---|
| 僵尸组 sweep（超 TTL 回收 / 活动组保留 / 新建组保留） | test_stream.py `ZombieGroupTests.test_sweep_idle_groups_reaps_zombie`/`test_sweep_keeps_live_or_recent_group`/`test_sweep_skips_recent_connectionless`（641/651/661 行） |
| 活动池收窄（无连接组不入 refresh 池） | test_stream.py `test_active_codes_excludes_connectionless_groups`(607)、`test_broadcast_skips_zombie_group_frame_build`(620) |
| full_chrome_restart 节流（THROTTLE×2 窗口跳过重启） | test_stream.py `MaybeReconnectThrottleTests.test_second_trigger_within_throttle_skips_restart`(571)；test_data_layer.py:1180 `test_throttled_ensure_chrome_keeps_state`、:1225/:1246 restart 窗口状态机 |
| 有界队列丢帧（maxsize=8 满时丢最旧保最新） | test_stream.py `SSEQueueDropTests.test_broadcast_on_full_queue_drops_oldest_keeps_newest`(527)；`FrameAccountingTests`(694) 计费/释放；`ReserveSkipTests`(760) 预算跳过 |
| 探测预算 2→4→5s 封顶 | test_cache.py:343 `test_probe_budget_escalates_then_caps` |
| metrics 快照/零值/形状守卫/healthz_inflight | test_metrics.py（35-228 全 registry）；test_server_http.py:500-514 healthz_inflight 不泄漏 |
| 业务降级恒 200 | test_server_http.py `test_margin_degraded_is_200_with_error_body`(614)、`test_guard_captured_error_body_is_200`(622)、`test_object_and_text_degrade`(61)、`test_batch_degrade_all_null_plus_errors`(66)、`test_guard_degrade_body_is_keyed_by_the_requested_spelling`(785) |
| SSE 帧全量快照/缺失标记/shared 单帧计费 | test_stream.py `FieldAndFrameTests`/`ShardingTests.test_c2_missing_codes_are_marked_not_silently_omitted`(903) |
| 空池 lag 复位（BUG-P6C-08） | test_stream.py `RefreshLagGaugeTests.test_lag_resets_on_the_scheduled_path_after_the_pool_empties`(1167) |

**P2-2 覆盖缺口**：TOCTOU 重查分支（收集后→销毁前客户端重连 → 组存活，stream.py:746-748 `if g.conns: continue`）无专项测试。现测试覆盖了三侧（可扫/有连接不扫/新组不扫），但缺"扫描集合阶段与销毁阶段之间注入重连"的竞态定向用例。

---

## 问题清单

### P0（阻断）
无。

### P1（建议修复）
无。

### P2（记录，不阻断）

**【P2-1】Dockerfile:24 — `EXPOSE 8053` 未声明 stream 端口 8054（影响维度 D）**
`EXPOSE` 虽仅文档性（docker-compose.yml 的 `ports: "8054:8054"` 实际映射正常），但直接 `docker run` 的使用者不会获得 8054 提示，SSE 服务对容器外不可达且无指引。
修复方向：改为 `EXPOSE 8053 8054`。

**【P2-2】tests/test_stream.py — TOCTOU 重连竞态分支无专项测试（影响维度 E）**
`_sweep_idle_groups` 的锁内 `if g.conns: continue`（stream.py:746-748）是本轮 P8 修复的关键防线（收集无连接→销毁前重连），但 368 测试中该分支仅被行为近似覆盖，无"sweep 执行中注入重连"的定向用例。
修复方向：测试中 mock `_sweep_idle_groups` 的收集与销毁之间（或直接在锁内重查前）向 `g.conns` 添加连接，断言组未被销毁——锁定该分支不被未来重构破坏。

**【P2-3】cdp_engine.py:268 — `open(f'/proc/{entry}/cmdline', 'rb')` 未用 `with`/显式 close（影响维度：资源回收）**
`_chrome_pids_by_flag` 对每个 /proc 进程号打开文件后仅 `.read()`，无 close。CPython 引用计数下即时回收，但 PyPy 等实现会延迟；进程多时 OS 层 FD 短暂累积。调用频率低（仅 Chrome 重启/杀进程路径），无实际泄漏后果。
修复方向：`with open(...) as f: cmdline = f.read().decode(...)`。

---

## 评审结论

✅ **可合并**

368/368 测试通过；维度 A 8 项既有修复全部保留、维度 B 两项裁决精确落地、维度 C 锁设计正确、维度 D 迁移完整、维度 E 覆盖充分（含 1 个 P2 缺口）。3 个 P2 均为记录级，不阻塞合入；建议后续迭代补 TOCTOU 定向用例（P2-2）。

---

## DOC_SYNC 检查

| 文档 | 状态 | 说明 |
|---|---|---|
| API.md | ✅ 一致 | 630 行明确"业务降级恒 HTTP 200 + 结构化 error 客体；503 仅准入拒绝与 /healthz degraded"（d6c8f12）；SSE 部分（§5）含 400 错误枚举、连接上限 503、STREAM_GROUP_IDLE_TTL 300s、帧结构 missing/stale/errors 字段 |
| README.md | ✅ 一致 | `python -m china_finance_rss.server` 启动方式（包迁移）；env 表含 STREAM_HOST/CDP_RESTART_THROTTLE/STREAM_GROUP_IDLE_TTL；缓存 TTL 说明含"negative cache 5s + escalating probe 2→4→5s" |
| docker-compose.yml | ✅ 一致 | STREAM_HOST=0.0.0.0（容器内绑定）、端口 8053/8054 映射 |
| Dockerfile | ⚠️ P2 | CMD 正确；EXPOSE 缺 8054（见 P2-1） |
| AGENTS.md | ✅ 一致 | code entry 已指向 `china_finance_rss/server.py` |
| doc/detailed/ 各模块详设 | ✅ 一致 | cache.md 探测预算阶梯 §2.1（AC-S3 封顶）、metrics.md v1.1 注册/快照设计均与实现对应 |

**无契约-代码漂移。** 未输出 `>>DOC_SYNC:` / `>>PROJECT:` 标记（无新契约变更；无 ≥2 例同构的新稳定约定待回写）。