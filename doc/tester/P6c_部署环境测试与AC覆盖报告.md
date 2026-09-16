# P6c 部署环境测试与 AC 覆盖报告

- **模块：** 全系统（server / cache / stream / stock_api / market_api / config / metrics / cdp_engine）
- **阶段：** P6c 阶段二（基于已部署容器的实测 + AC 覆盖矩阵）
- **被测环境：** 运行中的容器 `china-finance-rss`（镜像 `china-finance-rss-rss:latest`，端口 8053 主 / 8054 流，容器内 Chromium 152 + CDP 可用）
- **日期：** 2026-09-16 10:35–11:00 CST（**交易时段内**，L1 = 8s / L2 = 12s / L3 = 30s / L4 = 300s）
- **依据：** PRD `doc/prd/perf-stability-optimization.md` v0.4（30 条 AC）；详设 `doc/detailed/*.md`（8 份）；前序 `doc/tester/部署级验证报告_r2.md`
- **约束遵守：** 未修改任何业务代码/配置；未执行 `docker stop`；测试后已 DELETE 全部订阅组、终止全部后台客户端。

---

## ① 执行摘要

**AC 覆盖统计（30 条，逐条见 ②）：**

| 覆盖程度 | 条数 | AC |
|---------|------|----|
| 完整（单测断言 AC 核心语义） | **13** | E6, E7, E8, A3, A4, A6, A7, A9, A10, S1, S5, S6, S10 |
| 部分（机制/参数已测，端到端或分位数未断言；本轮部署实测补足部分） | **14** | E1, E2, E5, E9, A1, A2, A5, A8, S2, S3, S4, S7, S8, S11 |
| 无（单测缺失且部署不可测） | **3** | E3, E4, S9 |

**部署环境实测关键数据：**

- **AC-E1**：缓存命中**服务端 handler 延迟极优** —— 顺序 200 次 P95 2.8–5.9ms、P99 3.2–6.5ms；20 并发 1000 次 P95 19ms，但 **P99 ≈ 1.03s**（分离测量证实 **全部慢样本为 TCP connect ≈1.006s（SYN 重传），handler 本身 ≤0.32s**）。
- **AC-E2**：回源单次最大 **1.367s**（`/cls/hotplate`），16 个冷请求 P95 ≈ 1.35s，**全部 ≤15s** ✅（1.2s 建议值略超，属"待校准"）。
- **AC-E8/S5**：100 并发 → **80×503 `{"error":"server busy"}` + 20×200**，inflight 上限刚性生效、无积压；撤压 5s 后全部恢复 200 ✅。
- **AC-S8**：10×`/healthz?check=1` 并发时业务 P50 由 13.6ms → 14.5ms（**劣化 6.6%** ≤50%），健康检查每次 ≤1.07s（≤10s）✅。
- **AC-A9/A10**：60 码 → `_truncated=true` / `_dropped_count=10` / 50 数据键；50 码 → 两键均不存在；失败码 `null ∧ _errors[code]=cdp_unavailable`，非法码 `null` 且不入 `_errors` ✅。
- **AC-A1/E5（关键）**：50 码×3 字段组 20 连接**同帧**到达（spread ≤0.29s，入队侧 ≤1s ✅），逐码 3 字段齐全（有上游数据的码 35/35），ts 跨 tick 严格递增 ✅；**但节拍随组规模劣化**：1–10 码 ≈8s（正常），50 码 ≈16.6–17.3s，200 码 23.8–48s（`stream_tick_duration_ms` 同步 6.8–28.7s）→ BUG-P6C-01；200 码单帧仅 88–123/200（分片轮转 lag=4）→ BUG-P6C-02。
- **AC-A5**：400 矩阵 10/10、404 4/4、margin 枚举 400 全部符合契约 ✅。
- **缺陷：** 新增 **4 条**（1×P1 + 3×P2，见 ⑤）。**未实测项：** 6 类（S3 / S4-A类 / E4-5min / S9-24h / S7-SSE写阻塞 / A2-部署级）。

**结论：⚠️ 有条件通过** —— 错误语义、批量契约、有界拒绝与恢复、健康检查隔离、缓存命中 handler 延迟、帧完整性/入队、可观测性均达标；**缺陷 4 条（1×P1 + 3×P2）**，其中 **BUG-P6C-01（大组推送节拍 16.6–48s vs 标称 8s，P1）** 与 **BUG-P6C-02（AC-E5 200 码单 tick 全覆盖不可达，P2）** 属**设计/参数标定问题**（非本轮可现场修复），需编排层裁决；**未实测 6 类**（S3 / S4-A类 / E4-5min / S9-24h / S7-SSE写阻塞 / A2-部署级，见 ④）。

---

## ② AC 覆盖矩阵（30 条逐条）

> 「覆盖程度」= 现有 206 单测对该 AC **核心断言**的覆盖；「说明」标注缺口与本轮部署实测补足情况。

| AC | 覆盖 | 测试引用（tests/::方法） | 说明 |
|----|------|--------------------------|------|
| **E1** 本地缓存命中延迟 | 部分 | test_cache.py::test_hit_path_skips_network；test_server_http.py::test_double_check_single_fetch_single_thread/concurrent | 单测只证"命中不触网"，无分位数断言。部署实测：顺序 200 次 P95 2.8–5.9ms / P99 3.2–6.5ms ✅；20 并发 P99≈1.03s ❌（根因=TCP connect SYN 重传，见 BUG-P6C-03） |
| **E2** 回源延迟上界 | 部分 | test_server_http.py::test_hotplate/plate/longhu_latency_is_max_not_sum；test_busy_pool_degrades_within_budget | 单测证"扇出预算 ≤ REQUEST_TIMEOUT"机制。部署实测：16 个冷请求 max **1.367s**（≤15s ✅），P95≈1.35s 略超 1.2s 建议值 |
| **E3** CDP 路径延迟 | 无 | （无单测） | 无可注入 CDP 延迟的测试桩。部署实测"页面数据就绪"命中：P95 1.7–7.6ms ✅ 0 非 200；冷导航分位数未测 |
| **E4** 混合读吞吐 5min | 无 | tests/loadtest.py（非 unittest，未纳入 206） | 需 ≥100 req/s × 5min + 前后 P99 对比 → 时长受限。本轮短采样 20 并发≈390 req/s |
| **E5** 广播吞吐 | 部分 | test_stream.py::test_c1_whole_pool_no_sharding / test_c2_shards_and_fills_from_cache / test_budget_covers_single_group_8_deep_window / test_frame_model_is_the_single_source | 算法级已测；"单 tick 构建+入队 ≤1s"部署实测：**入队部分达标**（20 连接 spread ≤0.29s），**刷新部分严重超标**（见 BUG-P6C-01/02） |
| **E6** URL 缓存有界 | 完整 | test_cache.py::test_url_cap_enforced / test_true_lru_eviction_on_hit / test_timed_sweep_trigger | 2500 URL 场景由单测直接构造；部署未跑 |
| **E7** 连接与队列有界 | 完整 | test_stream.py::test_broadcast_on_full_queue_drops_oldest_keeps_newest / test_distinct_frame_billed_once_for_many_conns / test_drain_releases_back_to_zero / test_none_sentinel_is_not_billed / test_admission_cap_bounds_cross_group_working_set / test_patch_group_honours_frame_budget / test_retained_frames_are_still_billed | 队列 8 帧、丢旧保新、按帧计费、准入上限、无 ghost frame 均有断言 |
| **E8** 线程池有界拒绝 | 完整 | test_server_http.py::test_bounded_admission_stale_path / test_main_port_default_inflight / test_stream_port_explicit_inflight / test_stream_factory_passes_explicit_inflight | 单测 + 部署双证（③-9）：100 并发 → 80×503 + 20×200，无积压 |
| **E9** 龙虎榜缓存有界 | 部分 | test_server_http.py::test_longhu_latency_is_max_not_sum；test_config.py::test_longhu_encoding | 无 L4 命中计数断言。部署实测首请求 1.241s → 后续 10 次 19–22ms（③-8）；url 缓存 +2（上游 2 个 URL） |
| **A1** 帧完整性 | 部分 | test_stream.py::test_build_frame_maps_only_group_fields / test_build_frame_skips_codes_missing_from_snapshot / test_sse_stream_receives_quote_frame | 单测覆盖帧构建语义；"200 连续帧/每帧 50 码×3 字段/ts 非递减"端到端未断言。部署实测（③-5）：字段齐全、ts 跨 tick 严格递增 ✅，但周期 16.6s≠8s |
| **A2** 顺序性与丢旧保新 | 完整（单测） | test_stream.py::test_broadcast_on_full_queue_drops_oldest_keeps_newest | 部署级未复现：帧 885KB + 节拍 16.6s，预算内无法填满 8 帧队列（④） |
| **A3** 分层新鲜度对齐 | 完整 | test_config.py::test_ttl_convergence / test_realtime_domains_le_l1 / test_policy_shape_and_invariants；test_data_layer.py::test_endpoint_ttl_matches_policy | 白盒"单一来源派生 + 实时域 ≤L1"已断言；60×10s 双路采样未跑 |
| **A4** 无过期脏数据 | 完整 | test_cache.py::test_negative_gate_short_circuits / test_probe_success_clears_history / test_fetch_budget_progression；test_server_http.py::test_double_check_single_fetch_concurrent | "过期=拒读+回源一次"与单飞已在单测断言 |
| **A5** 错误语义表 | 部分 | test_server_http.py::test_object_and_text_degrade / test_batch_degrade_all_null_plus_errors / test_invalid_market_is_400_without_reaching_the_handler / test_market_enum_passes_through_to_handler；test_server.py::test_handle_margin_invalid_market_degrades_without_network；test_stream.py::test_sse_stream_unknown_group_returns_404 | 400/404/过载/margin `_error` 已覆盖；**"上游失败"（REST 全端点）与"CDP 不可用-A 类面板"未覆盖**。部署实测：400 矩阵 10/10、404 4/4 ✅，CDP-A′ 达标（③-3），REST 上游失败不可注入（④） |
| **A6** 批量一对一映射 | 完整 | test_data_layer.py::test_boundary_matrix / test_reserved_keys_matrix / test_serial_batch_preserves_order；test_cache.py::test_total_function | 部署实测：乱序 8 码（含 3 非法）顺序保持、非法→null、无跨码污染（③-4）✅ |
| **A7** 去重与池上限 | 完整 | test_stream.py::test_create_group_enforces_per_group_limit / test_create_group_enforces_deduped_pool_limit / test_max_groups_returns_error / test_60_codes_all_fetched_and_returned_beyond_max_batch；test_data_layer.py::test_shards_all_codes_without_truncation | 单组 200/全局 2000/组数上限 + 超限 400 拒绝均有断言 |
| **A8** RSS 不丢不重 | 部分 | test_server.py::test_generate_rss_includes_atom_self_link_when_feed_url_given / test_parse_cls_items_maps_roll_data / test_parse_jin10_items_maps_nested_flash_data | 无 guid 唯一性专项断言。部署实测 3 源 50/50/21 条、guid 全唯一、0 重复（③-7）✅ |
| **A9** 批量截断可感知 | 完整 | test_cache.py::test_reserved_key_matrix / test_zero_or_negative_dropped_omits_keys / test_data_plus_error_conflict_not_recorded | 部署实测：60 码→`_truncated=true`+`_dropped_count=10`+50 数据键；50 码→两键均不存在；51→dropped=1（③-6）✅ |
| **A10** 失败与 null 可区分 | 完整 | test_cache.py::test_value_domain_three_way / test_errors_nonempty_only / test_never_contains_top_level_error；test_data_layer.py::test_three_value_domains / test_none_result_is_no_data_not_failure / test_handler_degrades_to_null_plus_errors | 部署实测：`/stock/f10` 混合 → 非法码 null 且不入 `_errors`；失败码 null ∧ `_errors[code]='cdp_unavailable'`（③-6）✅ |
| **S1** 全端点异常兜底 | 完整 | test_server_http.py::test_object_and_text_degrade / test_batch_degrade_all_null_plus_errors / test_rss_degrade_is_valid_feed / test_invalid_shape_raises / test_keyboard_interrupt_passes_through；test_cache.py::test_never_contains_top_level_error | `_guard` 四形状（batch/object/rss/text）降级 + BaseException 透传均已断言 |
| **S2** 并发修改不中断推送 | 部分 | test_stream.py::test_patch_replaces_codes_object / test_codes_frozenset_fields_tuple / test_consumer_in_put_window_leaves_no_ghost_frame | 单测证"帧构建用不可变快照"；"500 次 PATCH 无 tick 中断 + 劣化 ≤20%"未端到端断言。部署实测 100 并发 PATCH 全 200（0.17s）、无异常日志 ✅（③-10） |
| **S3** 上游全挂有界响应 | 部分 | test_cache.py::test_leader_failure_no_stampede / test_negative_gate_short_circuits / test_probe_success_clears_history；test_server_http.py::test_busy_pool_degrades_within_budget | 负缓存/单飞/降级机制已断言；**故障注入（秒拒/黑洞两模式）无法在部署环境构造**（④） |
| **S4** CDP 降级路径 | 部分 | test_data_layer.py::test_engine_none_raises_cdp_unavailable / test_navigated_but_dateless_raises / test_no_nav_pages_raises / test_spent_budget_raises / test_handler_degrades_to_null_plus_errors；test_stream.py::test_errors_key_never_in_frame | A′ 批量路径（逐码 null + `_errors=cdp_unavailable`）单测+部署双证；**A 类 4 面板的 error 客体路径未覆盖/未实测**（需停 Chrome，④） |
| **S5** 503 恒定与恢复 | 完整 | test_server_http.py::test_bounded_admission_stale_path | 单测 + 部署实测（③-9）：撤压 5s 内全部恢复 200 ✅ |
| **S6** 单码故障不扩散 | 完整 | test_data_layer.py::test_cooldown_after_three_failures_blocks_network / test_success_clears_consecutive_failures / test_none_result_is_no_data_not_failure / test_three_value_domains | 部署侧旁证：`code_cooldown_list` 42 条、`upstream_fail_total` 枚举封闭（③-11）✅ |
| **S7** 超时兜底矩阵 | 部分 | test_stream.py::test_read_budget_set_and_restored / test_read_timeout_returns_none_and_restores / test_invalid_cl_does_not_touch_connection；test_data_layer.py::test_deadline_entry_does_not_touch_network / test_spent_budget_raises / test_exhausted_budget_is_bounded_and_counted | 流端口体读 5s、REST 期限传播已断言；**SSE 写阻塞 41s（连接级）与 CDP 9s 兜底未实测**（④） |
| **S8** 健康检查不是放大器 | 部分 | test_server_http.py::test_schema_check0_zero_upstream；test_server.py::test_healthz_payload_includes_hotplate_endpoint | 无"check=1 并发 vs 业务延迟劣化"断言。部署实测劣化 **6.6%**（≤50%）✅、单次 ≤1.07s（③-8） |
| **S9** 24h 资源总账 | 无 | （无） | 需连续 24h 采样（④） |
| **S10** 关键指标可观测 | 完整 | test_metrics.py 全部 17 项（MET-T1..T12）；test_server_http.py::test_schema_check0_zero_upstream | 部署实测 10 个观测项中 8 项存在；`stream_frame_dropped_total`/`negative_cache_size` 为 0 时不出现（③-11，见缺陷 P6C-04） |
| **S11** 断线重连并续帧 | 部分 | test_stream.py::test_subscription_crud_over_http / test_sweep_idle_groups_reaps_zombie / test_sweep_keeps_live_or_recent_group / test_destroy_between_register_and_attach | 建组/回收已测；"≤1 tick 内收帧"部署仅弱证据（③-5，受节拍劣化限制） |
## ③ 实测数据（命令 + 原始输出摘要 + 结论）

> 统一环境：容器 `china-finance-rss`（8053/8054），宿主 `python3` + `requests`/`urllib`/裸 socket；交易时段内（L1=8s）。所有命令为一次性 stdin 脚本，不落盘、不改代码。

### ③-1 AC-E1 本地缓存命中延迟（热点端点 200 次 + 20 并发 1000 次）
命令（摘要）：`requests.Session` 顺序 200 次；`ThreadPoolExecutor(20)` 并发 1000 次，分别对 `/healthz?check=0`、`/stock/data?code=sh600519`、`/finance/market`、`/cls/hotplate`。

原始输出（顺序 200 次，含 localhost RTT）：
```
E1-healthz          p50 2.065  p95 2.758  p99 3.180  max 6.469  status{200:200}
E1-stock-data-quote p50 2.666  p95 3.375  p99 3.897  max 3.928  status{200:200}
E1-finance-market   p50 6.311  p95 7.628  p99 8.649  max 8.841  status{200:200}
E1-hotplate         p50 4.666  p95 5.858  p99 6.538  max 6.820  status{200:200}
```
原始输出（20 并发 ×1000 次，连接模式 keep-alive/close 两轮一致）：
```
E1-stock-data-20x1000  p50 12.16  p95 18.95  p99 1032.11  max 1433.33  over_1s=21  status{200:997,503:3}
E1-healthz-20x1000     p50 17.42  p95 30.35  p99   39.66  max 1039.60  over_1s=7   status{200:1000}
```
**连接/请求耗时分离（决定性）**——裸 socket，400 次 @20 并发，容器**内**执行：
```
slow CONNECT (>0.5s): 12   sample [(1.0062,0.0035),(1.0078,0.0038),(1.0064,0.0041),(1.0130,0.0033)]
request-time >0.5s: 0     max connect 1.0298   max req 0.3189
```
**结论：** ✅ **handler 命中延迟达标**（P95 ≤5ms，P99 ≤15ms，0 非 200；`/finance/market` 163KB 载荷 P95 7.6ms 略超 5ms，属序列化+体积）。❌ **含 TCP connect 的 20 并发 P99≈1.03s**，且慢样本 100% 是 connect（≈1.006s，SYN 重传），handler 本身最大 0.319s。→ BUG-P6C-03。
### ③-2 AC-E2 回源延迟上界 + AC-E9 龙虎榜 L4
命令：16 个冷缓存端点各单次请求；`/ths/longhu` 首请求 + 10 次连续。
```
/stock/data?code=sh600000 0.337 | sh600036 0.323 | sz000002 0.318 | sh601398 0.312 | sh601288 0.383
/stock/basic_info?code=sh600030 0.617 | sh600887 0.699
/stock/fundflow 0.326 | /stock/timeline 0.338 | /stock/announcement 0.317
/cls/plate?code=cls80484 0.352 | cls80146 0.760 | /cls/telegraph 0.624
/cls/hotplate 1.367 | /market/margin?market=99 1.345 | /ths/longhu 1.241
max single cold: 1.367s     全部 < 15s
longhu first 0.019s(*已热) → next10: [0.019,0.021,0.020,0.020,0.020,0.018,0.019,0.022,0.019,0.021]
```
**结论：** ✅ E2「任何单请求 ≤15s」达标（max 1.367s）；⚠️ P95≈1.35s 略超 1.2s 建议值（2 个扇出端点 hotplate/margin）→ 建议以实测校准。✅ E9「首请求回源、后续 9 次命中」达标（1.241s → 19–22ms）；⚠️ 命中延迟 19–22ms > 5ms 建议值（128KB 响应序列化），且上游为 **2 个 URL**（url 缓存 9→11）而非 1。

### ③-3 AC-A5 错误语义矩阵（部署实测）
命令：`requests.request` 逐项探测，记录 HTTP/Content-Type/Body。
```
参数缺失：/cls/plate 400 {"error":"Missing ?code= parameter..."}；/cls/plate?code= 400；/stock/{data,fundflow,timeline,f10,basic_info,announcement} 无参 400；?code=,,, 400 {"error":"No valid stock codes provided."}   → 10/10 ✅
未知路径：/nope 404 text/html；/stock/xxx 404；/stock/datax 404；/stream/quote 404（主端口）  → 4/4 ✅
枚举：/market/margin?market=bad 400 {"error":"Invalid ?market= parameter. Allowed: 99,1,2,3"}；?market=999 400；?market=1 200；?market=（空）200 默认 99  ✅
```
CDP 不可用（不停止 Chrome，用上游无数据的码触发 CDP 失败路径）：
```
GET /stock/f10?code=sh600519,NOTACODE,sh999999 → 200
keys = [sh600519, NOTACODE, sh999999, _errors]   _errors = {"sh999999":"cdp_unavailable"}
```
**结论：** ✅ 400 矩阵、404、枚举边界全部符合契约；✅ CDP-A′ 批量降级形状符合（逐码 null ∧ `_errors`，**非** error 客体）。⚠️ 「上游失败」REST 情形与「CDP 不可用-A 类 4 面板 error 客体」未实测（④）。⚠️ 观测：`?market=`（空值）回落默认 99，非 400——与 PRD 参数缺失行（仅列 `/cls/plate` 与 `/stock/*`）不冲突，记录备查。
### ③-4 AC-A6 批量一对一映射
命令：`/stock/data?code=sh601398,abc123,sz000001,sh60,sh600519,12345,sz000002,sh600036`（乱序含 3 非法）。
```
returned keys order == requested order : True   n=8
invalid values: {"abc123":null,"sh60":null,"12345":null}
交叉校验 primary_industry：sh600519→食品饮料行业(白酒) | sz000001→银行 | sh601398→银行 | sh600036→银行
```
**结论：** ✅ 顺序保持、非法码 null、每码数据与代码匹配、无跨码污染。

### ③-5 AC-A1 / E5 / S11 SSE（裸 socket 客户端，20 连接）
**50 码 × 3 字段（AC-A1 形状）+ 20 连接：**
```
tick=1789526793701 clients=20 items={20} spread=0.086s
tick=1789526810347 clients=20 items={50} spread=0.292s  gap=16.63s
tick=1789526827694 clients=20 items={50} spread=0.243s  gap=17.33s
逐码字段集：(quote,fundflow,timeline) 35 码全齐；(quote,timeline) 15 码
  → 该 15 码经 REST 交叉核验为上游 `upstream_error`（退市/停牌，如 sz000003/000005…），非帧构建丢失
ts 跨 tick 严格递增 ✅
```
**200 码 × 1 字段（AC-E5 形状）+ 20 连接：**
```
tick=1789526722361 clients=20 items={123} spread=0.016s
tick=1789526746125 clients=20 items={88}  spread=0.012s  gap=23.76s
metrics stream_tick_duration_ms: 22987→28742→23763   stream_tick_slip_total 4→6
```
**稳态小样本（本次补充观测，1/10 码 × 1 字段 × 1 连接）：**
```
A-1code  : frame_arrivals=[4.61,11.29,20.57,27.29]  gaps=[6.68,9.27,6.73]      items=[1,1,1,1]
           tick_duration_ms samples=[0.02,1316.42,0.38,1271.79,0.24]
B-10codes: frame_arrivals=[15.14,15.94,25.06,32.15,41.43] gaps=[0.80,9.11,7.09,9.28] items=[10,10,10,10,10]
           tick_duration_ms samples=[1283.94,797.98,1913.13,1004.31,2284.71]
```
**结论：** ✅ 帧内字段齐全（有上游数据的码 100% 覆盖订阅字段）、20 连接同一帧到达 spread ≤0.29s（**入队 ≤1s 达标**）、ts 跨 tick 严格递增、丢旧保新语义由单测覆盖。❌ **节拍与覆盖**：1–10 码稳态 ≈8s ✅；**50 码×3 字段 16.6/17.3s、200 码 23.8–28.7s（≥2–3.6× 标称 8s）**；200 码单帧 items 88–123/200（分片轮转，lag=4）→ BUG-P6C-01/02。
### ③-6 AC-A9 / A10 截断与值域
命令：`/stock/data?code=` 传 60 / 51 / 50 码；混合码探测。
```
60 codes: n_data_keys=50  _truncated=true  _dropped_count=10  has_errors=false   ✅
50 codes: n_data_keys=50  _truncated_in=false  _dropped_count_in=false           ✅
51 codes: _truncated=true  _dropped_count=1                                       ✅
A10 /stock/f10 混合: keys=[sh600519, NOTACODE, sh999999, _errors]
                     _errors={"sh999999":"cdp_unavailable"}  非法码 NOTACODE 不在 _errors ✅
```
**结论：** ✅ 截断口径钉死生效（≤50 两键均不存在；>50 同现且 count=请求数−50）；✅ 失败(null ∧ ∈`_errors`) 与 无数据/非法码(null ∧ ∉`_errors`) 可区分。⚠️ 「上游持续失败的码」未构造成功（见 ④）。

### ③-7 AC-A8 RSS 不丢不重
```
/cls/telegraph     items=50 guids=50 unique=50 dup=0
/eastmoney/kuaixun items=50 guids=50 unique=50 dup=0
/jin10/flash       items=21 guids=21 unique=21 dup=0
```
**结论：** ✅ 条目数与 guid 唯一性达标（2×TTL 复测未做，单测覆盖缓存不丢条目）。

### ③-8 AC-S8 healthz 隔离 + AC-S10 可观测
```
baseline(无健康检查)        : p50 13.6ms  p95 1017.7ms  status{200:200}
with 10x /healthz?check=1   : p50 14.5ms  p95 1023.8ms  status{200:200}
healthz check=1 单次耗时: [(200,0.01)x5,(200,0.69)x3,(200,0.04)x3,(200,1.06)x3,(200,0.70)x2,(200,1.07)x2,(200,0.05)x2]
观测字段: stream_tick_duration_ms ✅ http_503_total ✅ cache_entries ✅ code_cooldown_list(42条) ✅
         cdp_restart_window ✅ upstream_fail_total ✅ stream_queue_bytes ✅ stream_frame_peak_bytes(902365) ✅
         stream_frame_dropped_total ❌(0 时不出现)  negative_cache_size ❌(0 时不出现)
```
**结论：** ✅ 业务 P50 劣化 6.6%（≤50%）；健康检查单次 ≤1.07s（≤10s）；✅ 观测项 8/10 可见（2 项 0 值时不发布 → P6C-04）。
### ③-9 AC-E8 / S5 有界拒绝与恢复（100 并发冲主端口）
命令：100 并发、**各自唯一冷码** `/stock/data?code=sh6030xx`（保证线程被真实占用）。
```
status {"503":80,"200":20}   503_bodies {"{\"error\":\"server busy\"}":80}
http_503_total 135 → 215 (+80)
撤压 5s 后: /stock/data 200, /healthz 200   ✅ 无残留拒绝
```
**结论：** ✅ inflight 上限（MAX_INFLIGHT=40 = 20 运行 + 20 排队）刚性生效，超出即 503 且不积压；503 语义正确；恢复 ≤5s ✅。

### ③-10 AC-S2 并发 PATCH（推送运行中）
命令：41 码组 + 2 个常连客户端，运行中 100 次并发 PATCH（add/remove 交替）。
```
100 concurrent PATCH in 0.17s   {'ok':100,'bad':0}   客户端持续收帧(41 items)
日志扫描: 无 push_loop error / 无迭代中断类异常 ✅
```
**结论：** ✅ 并发增删码无中断、无异常、全部 200。⚠️ 「tick 劣化 ≤20%」未量化（基线节拍本身已在 ③-5 中劣化，无清洁基线）。

### ③-11 其他旁证
```
code_cooldown_list: 42 条（fundflow 域退市码），冷却 120s 生效 ✅ (AC-S6)
upstream_fail_total: {"cdp_unavailable":3,"upstream_error":524} 枚举封闭(无自由文本) ✅
stream_frame_peak_bytes: 902365 (50 码×3 字段帧 ≈ 885KB) < 128MB 预算 ✅
sse 未知 sid → 404 ✅   healthz → 200  容器 Up、restarts=0
```
## ④ 不可验证项与替代验证建议

| # | 不可验证 AC | 受限类型 | 原因（如实） | 替代验证建议 |
|---|------------|---------|-------------|-------------|
| 1 | **AC-S3** 上游全挂有界响应（模式 A 秒拒 / 模式 B 黑洞，各 5min） | 环境 | 容器网络由 Docker 管理，无 iptables 写权；上游为公网域名，无法在**不改代码/不改配置**前提下把全部上游钉死为"秒拒"或"黑洞"；PRD 又明令两模式**分别单跑、分别断言**，不能合并 | ①由编排层在测试环境提供 fault-injection hook（本地 refuse/黑洞桩 + `HTTP_PROXY` 或 hosts+iptables DROP）；②以 `test_cache.py::test_leader_failure_no_stampede` + `test_negative_gate_short_circuits` + `test_server_http.py::test_busy_pool_degrades_within_budget` 作**机制级**替代证据（已具备）；③模式 A"快速失败 ≤1s"可用**指向已关闭端口**的 URL 单测覆盖 `FetchError` 立即抛出路径 |
| 2 | **AC-S4** A 类 4 面板端点（`/finance/market`、`/finance/timeline`、`/quotation/market`、`/market/timeline`）CDP 不可用 | 环境（破坏性） | 需停止容器内 Chromium；引擎自动恢复依赖后续导航量（约 30 次），停 Chrome 可能产生**长时间不可恢复**窗口，越界"不影响容器正常运行"约束 | ①在**可丢弃的一次性容器**中停 Chromium 后逐端点断言 error 客体（非逐码 null）；②或令 `CDP_URL` 指向不存在端口启动一次性容器验证降级形状；③A′ 批量路径本轮**已实测**（③-3），可作同源机制旁证 |
| 3 | **AC-E4** 混合读 ≥100 req/s 持续 5min + 后 3min P99 劣化 ≤20% | 时长 | 5min 稳态 + 前后窗口对比超出单步 ≤60s 预算；长压还影响容器正常服务 | ①拆成 5 段各 60s 连续采样拼接 P99（本轮短采样：20 并发≈**390 req/s**）；②劣化趋势改用 `stream_tick_duration_ms`/`http_503_total` 做趋势断言 |
| 4 | **AC-S9** 24h 资源总账（内存 ≤基线×1.5、线程 ≤基线+20、FD ≤512） | 时长 | 24h 连续混跑完全越界 | ①短时（5–10min）采样 `RSS/线程数/FD` + `docker stats` 验证**无单调增长**；②一次性容器中调小 `CDP_RESTART_INTERVAL` 验证守护回收逻辑（不改生产配置） |
| 5 | **AC-S7** SSE 写阻塞 ≤41s、CDP 页面求值 ≤9s | 环境 | 需"客户端不读 socket 且持续 >40s"的慢客户端 + CDP 侧永久不返回；无注入点 | ①流端口 5s 体读预算已由 `test_stream.py::test_read_budget_set_and_restored` 覆盖（**达标**）；②写阻塞改用 `SO_RCVBUF=4KB` 裸 socket + 一次性容器调小 `STREAM_PING_INTERVAL` 加速；③CDP 9s 由 `test_data_layer.py::test_spent_budget_raises` 机制级覆盖 |
| 6 | **AC-A2** 丢旧保新（部署级） | 环境 | 队列上限 8 帧，但 50 码×3 字段帧 ≈885KB，慢客户端 socket 缓冲先阻塞**写**路径、且实际节拍 16.6s → 填满 8 帧需 >2min，超预算 | ①单测 `test_broadcast_on_full_queue_drops_oldest_keeps_newest` 已覆盖语义（**完整**）；②部署级改用小帧（3 码×1 字段 ≈4KB）+ `SO_RCVBUF` 极小 + 一次性容器缩短 tick 加速填队列 |

**其他未做实测的次要项（低优先）：** AC-E3 冷 CDP 导航分位数（r2 已有单次冷取 3.04s 旁证）；AC-A3 的 60×10s 双路值比对（白盒同源断言已由单测覆盖）；AC-E6 的 2500-URL 场景（单测构造）；AC-A8 的 2×TTL 复测。
## ⑤ 发现缺陷

> 等级口径与全系统一致：P0 崩溃/数据丢失/资金/安全；P1 功能缺陷/单点/性能退化；P2 可维护性/规范/测试自身问题。**仅报告，未修改任何代码/配置。**

### BUG-P6C-01（**P1**）SSE 大组推送节拍劣化：50 码 ≈17s、200 码 24–48s（标称 L1 = 8s）

- **现象：** 订阅组规模增大后，帧交付周期从 8s 退化到 16.6–48s（≥2–6× 标称节拍）；`/healthz` 的 `stream_tick_duration_ms` 同步飙到 6.8–28.7s，`stream_tick_slip_total` 持续累加。**与码数强相关、与连接数弱相关**：1–10 码正常（≈8s），50 码×3 字段 ≈17s，200 码 ≈24–48s；20 个连接下同一帧到达 spread 仅 ≤0.29s（入队本身不慢）。
- **复现步骤：**
  1. `POST http://localhost:8054/stream/subscriptions  {"codes":[…50 个真实码…],"fields":["quote","fundflow","timeline"]}`
  2. 裸 socket `GET /stream/quote/<sid>`（或 `curl -N`）持续接收，记录每帧到达时刻与 `ts`。
  3. 同时每 3s 读 `http://localhost:8053/healthz?check=0` 的 `metrics.stream_tick_duration_ms` / `stream_tick_slip_total`。
  4. 对照组：1 码 / 10 码重复同样步骤。
- **原始证据：**
```
# 1 码 × 1 字段（1 连接，36s 窗口）
frame_arrivals=[4.61,11.29,20.57,27.29]  gaps=[6.68,9.27,6.73]  items=[1,1,1,1]
tick_duration_ms=[0.02,1316.42,0.38,1271.79,0.24]
# 10 码 × 1 字段（1 连接，45s 窗口）
frame_arrivals=[15.14,15.94,25.06,32.15,41.43] gaps=[0.80,9.11,7.09,9.28] items=[10,10,10,10,10]
tick_duration_ms=[1283.94,797.98,1913.13,1004.31,2284.71]
# 50 码 × 3 字段（20 连接）
tick=…793701 items={20} spread=0.086s ; tick=…810347 items={50} spread=0.292s gap=16.63s
tick=…827694 items={50} spread=0.243s gap=17.33s
# 200 码 × 1 字段（20 连接）
tick=…722361 items={123} ; tick=…746125 items={88} gap=23.76s
stream_tick_duration_ms: 22987 → 28742 → 23763 ; stream_tick_slip_total 4→6
```
- **影响：** AC-E5（单 tick 广播预算）、AC-A1（帧交付节拍）、AC-S11（≤1 tick 重连）在 50/200 码组下不可达；P2 量化终端若按 8s 节拍消费，实际看到的是 2–6 个 tick 才一帧，盘中时效性低于 PRD 目标。
- **根因初判（高置信，代码+实测双侧证）：** 慢在 **tick 内 `_refresh_pool` 的刷新耗时**（上游 IO），**不是**调度/睡眠问题——慢样本的 `stream_tick_duration_ms` ≈ 观测到的帧间隔（16–29s），说明循环真在 `_refresh_pool` 里等上游。具体三点：
  1. `stream.py:200` `_refresh_pool` **无条件遍历全部 3 个 `_FIELD_HANDLERS`**（quote/fundflow/timeline），与订阅 `fields` 无关；`quote` 的处理器是 `handle_cls_basic_infos`，其底层 `fetch_cls_basic_info` 每码发 **2 次** REST（行情 + 行业详情）→ 实际 ≈4 次上游调用/码/tick。
  2. 容量常数 `_PER_FETCH_EST=0.3` 仅按"3 字段 = 3 次取数/码"估算：`coverage = int(0.8×8×8/0.3) = 170` 次取数 ⇒ C1 条件 `3n ≤ 170` 令 **n ≤ 56 走全量刷新**。而实测每码 3 字段成本 ≈ **0.5s**（冷取 20 码：basic_info 4.61s + fundflow 0.69s + timeline 5.21s = 10.5s），56 码≈**29s**，远超 8s。
  3. 次级放大：tick 一旦超时，`delay = max(0, t0+tick-time.time()) = 0` ⇒ 下一 tick **不睡眠立即开始**，形成"长间隔后连发"的突发模式（实测 0.80s / 0.315s 连发），节拍抖动加剧。
- **是否与本次改造相关（对比结论）：** **无回归证据，且改造前同规模更差。** 依据：`HEAD` 版 `stream.py` 的 `_refresh_pool(codes)` **无 coverage/分片**，每 tick 对**整个去重池**做 3 字段全量刷新（`git show HEAD:china_finance_rss/stream.py`），200 码即 800 次调用 → 更慢；本次改造新增 `_TICK_BUDGET_FRACTION`/`_PER_FETCH_EST`/C1-C2 分片，**压低了单 tick 工作量**（200 码降至 56 码/片），但系数标定偏乐观，故仍未达 8s。基线说明：`部署级验证报告_r2.md` 与本次 Trial A 均为**1 码**场景（tick 0.29ms / 0.02–0.38ms，节拍 6–9s）→ **小组无劣化**；大组在改造前**没有部署基线**（r2 只测 1 码），故只能由 HEAD 源码对比判定"非本次引入"。
### BUG-P6C-02（**P2**）AC-E5「200 码单 tick 全量帧」与设计分片冲突，不可达

- **现象：** 200 码组单帧 `items` 仅 **88–123/200**（非全量）；`stream_refresh_lag_ticks=4`。
- **复现：** `POST /stream/subscriptions {"codes":[200 个真实码],"fields":["quote"]}` → 20 连接收帧，统计每帧 `len(items)`。
- **原始证据：** `items={123}` / `items={88}`；`stream_refresh_lag_ticks=4`；源码 `coverage=170 → coverage_codes=170//3=56`，C2 分支 `sl=56 码`、`lag=ceil(200/56)=4`（stream.py:186–198）。
- **影响：** AC-E5 断言"100 连接 × 200 码 × 3 字段组，单 tick 快照构建+入队 ≤1s 且帧完整"；按实现，全量覆盖需 **4 个 tick**（≈1–3min），AC 与实现口径不一致，需编排层裁决（改 AC 或改实现）。
- **根因初判：** 设计取舍——单 tick 取数容量（`coverage`）无法覆盖 200 码 × 3 字段，故引入 C2 分片轮转；这是**有意的降级**（避免 tick 无限膨胀），但 AC-E5 仍按"单 tick 全量"描述。**非代码缺陷，属契约/设计口径张力。**

### BUG-P6C-03（**P2**）主端口 TCP 监听 backlog 过小 → 高并发下 P99≈1.03s 与偶发 503

- **现象：** 20 并发连接/请求模式下，≈2–3% 请求耗时 **恰为 1.006–1.03s**（SYN 重传 RTO），P99 由 15ms 级跳到 ≈1.03s；部分轮次出现零星 503（3/1000；曾观测 111/1000，后者伴随测试客户端残留 keep-alive 会话，判定为**客户端伪影**，置信度低）。
- **复现步骤：**
  1. 裸 socket 容器**内**执行：`connect()` → 计时；`sendall(GET /stock/data?code=sh600519)` → 计时读取。
  2. 20 线程 × 400 次。
- **原始证据：**
```
slow CONNECT (>0.5s): 12  sample [(1.0062,0.0035),(1.0078,0.0038),(1.0064,0.0041),(1.0130,0.0033)]
request-time >0.5s: 0      max connect 1.0298   max req 0.3189
```
- **影响：** AC-E1 若按"端到端（含 connect）"口径判定，P99 ≤15ms 与「0 个 4xx/5xx」不达标；按 PRD §5#1「服务端 handler 处理耗时，不含网络」口径则**达标**（P95 ≤5ms）。另：客户端每请求新建连接（主端口为 HTTP/1.0，无 keep-alive 复用）会放大该效应。
- **根因初判：** `server.py` 的 `BoundedThreadPoolServer` 未设置 `request_queue_size`（`socketserver` 默认 **5**），并发建连速率高时 accept 队列溢出 → SYN 丢弃 → 客户端 1s 后重传；accept 循环与 20 个 worker 争抢 GIL 使溢出概率上升。建议（不由本测试实施）：显式提高 `request_queue_size`（如 128）或引入 keep-alive。

### BUG-P6C-04（**P2**）0 值观测指标不发布，AC-S10 可观测性不完全

- **现象：** `/healthz?check=0` 的 `metrics` 中 `stream_frame_dropped_total` 与 `negative_cache_size` **在值为 0 时缺失**（其余 8 项存在）。
- **复现：** 无丢弃、无负缓存时读 `/healthz?check=0` → 两键 `MISSING`；触发丢弃/负缓存后出现。
- **影响：** AC-S10 要求"可观测到 SSE 队列丢弃帧计数、上游失败码冷却清单"等；0 值缺失使监控无法区分"未发生"与"未埋点"（对告警规则不友好）。
- **根因初判：** `metrics.incr/set_gauge` 仅在写入时注册发布（计数器首次 incr 才出现），非缺陷性 bug，属**可观测性约定**问题；建议健康负载对关键计数器做 0 值兜底发布。
---

## ⑥ 测试清理与合规记录

- **订阅组清理：** 本次共创建 9 个订阅组（3/3/200/200/20/50/41/50/3/1/10 码各轮次），**全部 `DELETE /stream/subscriptions/<sid>` 返回 200**，无残留。
- **后台客户端：** 全部为进程内 daemon 线程，随脚本退出终止；无遗留进程。
- **容器状态：** 未执行 `docker compose stop/restart`；测试末 `docker compose ps` = `Up`、`restarts=0`；`/healthz` 200、`/stream/quote/<未知 sid>` 404。
- **代码/配置：** **零修改**（`git status` 中 `china_finance_rss/*.py` 的改动为**前序阶段既有**未提交改动，非本报告产生）。
- **测试方法：** 全部为 stdin 一次性脚本（未落盘、未入 `tests/`），仅做只读请求与订阅 CRUD；未做破坏性故障注入。

## ⑦ 结论与建议动作

| 观察 | 判定 |
|------|------|
| 错误语义（400/404/过载/降级/值域） | ✅ 达标（③-3/③-6） |
| 批量契约（截断保留键、一对一映射、`_errors`） | ✅ 达标（③-4/③-6） |
| 有界拒绝与恢复（E8/S5） | ✅ 达标（③-9） |
| 健康检查隔离（S8） | ✅ 达标（③-8） |
| 缓存命中 handler 延迟（E1/E3） | ✅ 达标（③-1） |
| 回源上界（E2） | ✅ ≤15s；⚠️ P95 1.35s 略超 1.2s 建议值 |
| SSE 入队/帧完整性/ts 单调 | ✅ 达标（③-5） |
| **SSE 大组节拍与单 tick 全量覆盖** | ❌ **不达标（BUG-P6C-01/02）** |
| TCP 高并发 connect 尾延迟 | ⚠️ P99≈1.03s（BUG-P6C-03） |
| 可观测性 0 值兜底 | ⚠️ 2 项缺失（BUG-P6C-04） |

**建议动作（交编排层 / 后续修复轮，非本轮实施）：**
1. **P1** BUG-P6C-01：重标定 `_PER_FETCH_EST`/`coverage`（计入 quote 的 2 次上游调用；或按"码"而非"字段"计容量），或按组 `fields` 只刷新所需字段；并考虑 tick 超时后的追赶策略（当前 `delay=0` 连发）。
2. **P2** BUG-P6C-02：裁决 AC-E5 口径（"单 tick 全量"vs"分片轮转 lag≤N tick"），同步 PRD 与实现注释。
3. **P2** BUG-P6C-03：显式设置 `request_queue_size`，或在测试口径中明确 E1 的延迟定义（handler-only）。
4. **P2** BUG-P6C-04：健康负载对关键计数器做 0 值兜底发布。

*报告完 · tester（阶段二）· 2026-09-16*

