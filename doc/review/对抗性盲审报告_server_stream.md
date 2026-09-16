# 对抗性盲审报告 — server.py / stream.py

- **模式**：`>>MODE: blind`（对抗性盲审，假设代码一定还有 Bug，不验证"正确性"）
- **需求原文**：「当前系统是提供短线交易系统使用，所以对于这样的场景业务系统来说，系统处理与响应来说必要高效准确且稳定。所以请对当前系统进行全面检查尽量往这些指标靠近。」
- **入参范围**：需求原文 + 改动范围（8 模块「高效/准确/稳定」改造的 server.py / stream.py 两模块）+ 项目约束（stdlib 零依赖 / SSE 长连接 / 主端口 8053 / 流端口 8054）。未接触任何设计理由、评审结论、测试结果；`doc/review/**`、`doc/tester/**` 未读。
- **实测对象**：`china_finance_rss/server.py`（1359 行）、`china_finance_rss/stream.py`（1115 行）；为建立证据链仅读取被调片段：`cache.py`、`stock_api.py`（`_handle_cached_batch` / `cached_batch` / `_run_batch` / `_prefetch_*`）、`config.py`、`cdp_engine.page_data/get_data`、`metrics.py`。
- **评审结论**：❌ **阻断** — 1×P0 + 6×P1 + 4×P2。最担心：静默的**金融数据错配**（P0-1）。

---

## 问题清单

【P0】server.py:212-218: `/ths/longhu` 的营业部买卖席位用**位置** `stock_idx = broker_idx // 2` 对齐股票，但 `if not entries: continue`（212-213）跳过时不自增 `broker_idx`；只要某张「买入/卖出金额最大的前5名营业部」表解析出 0 条（`len(bro_cells) < 4`、名称列空、或数据行用 `<th>` 而非 `<td>` → 见 199-205），后续全部股票的 buy/sell 奇偶配对整体错位一位；`stocks` 来自 lhbtable、表格来自另一页 HTML，两者顺序/覆盖一旦不一致（分页、缺行）同样错位。| 依据：位置映射存在但**从未与该表的股票代码/名称做任何校验**（`cells[1]` 的代码只用于构建 `stocks`，未参与绑定，172-182）| 影响：把 A 股票的营业部席位静默挂到 B 股票上，HTTP 200 + 结构正常、无任何错误信号；短线用户据此决策 → **资金损失** | 建议：以股票代码/名称绑定表格而不是位置；最小修复：label 匹配后**无条件** `broker_idx += 1`（含 entries 为空分支），`stock_idx >= len(stocks)` 时显式告警而非静默丢弃。

【P1】stream.py:363-364（被调：stock_api.py:928/939/963 与 :56）: `_refresh_pool` 调 `handler(list(sl))` **不传 `deadline`**，各字段 handler 退回默认 `_BATCH_BUDGET_REST=15s`；3 个字段串行 → 单个 tick 最坏阻塞 **45s**，期间 push 线程无法进入 `_broadcast`，全部 SSE 连接在该窗口内收不到任何 `event: quote`（只有 20s 一次的 ping）。| 依据：`handle_cls_basic_infos(codes, deadline=None, ...)` → `budget = time() + _BATCH_BUDGET_REST`；`_handle_cached_batch` 逐 chunk `min(budget, ...)`；`_refresh_pool` 全程无 deadline 传播，而这三个 handler 都**已支持** `deadline` 形参 | 影响：上游最慢的时刻（开盘/异动，正是短线最需要推送时）出现 45-53s 全通道行情黑屏；且帧内 `ts` 是 build 时刻（392-441），客户端无法识别数据已陈旧 | 建议：`handler(list(sl), deadline=now + _TICK_BUDGET_FRACTION * tick)`；某字段超预算即跳过剩余字段并按 `_errors` 标记降级。

【P1】stream.py:970 / 1012（被调：776-778 / 831-843）: POST/PATCH 体里 `codes` / `add` / `remove` 只要不是可迭代容器（`{"codes": 123}`、`{"add": true}`），`create_group` 的 `len(codes)`（778）或 `patch_group` 的 `for c in add`（834-838）抛 `TypeError`；该行**在 try 之外**（`_valid_fields` 的 `TypeError` 才被 780-783 包住），异常冒泡出 `BaseHTTPRequestHandler`，客户端得到连接重置/空响应，而不是契约中的 400。| 依据：`_read_json_body` 只校验 JSON 可解析与 Content-Length；tests/test_stream.py:253-273 只覆盖 list 形态 body | 影响：客户端拿到 ECONNRESET 而非 `{"error":...}`，重试与告警语义破裂（127.0.0.1 绑定降低暴露面，但错误契约被违反）| 建议：`_read_json_body` 之后统一做「非 list → 400」，或在 `create_group`/`patch_group` 入口 `isinstance` 校验。

【P1】stream.py:1033-1092（+914 +1064）: `_serve_sse` 任何退出路径都**不置 `self.close_connection = True`**，且把 socket 超时抬到 `STREAM_PING_INTERVAL * 2 = 40s`；响应头又是 `Connection: keep-alive`，于是 `handle()` 的 `while not self.close_connection` 会再进 `handle_one_request` → 在 `rfile.readline()` 上阻塞最多 40s。| 依据：stream.py 全文无 `close_connection` 赋值；`_inflight` 仅在 executor future 完成时释放（server.py:1226-1231），因此名额也被一起占住 40s；`StreamHandler` 未像 `RSSHandler`（867-870）那样抑制 "Request timed out" 日志 | 影响：客户端重连/静默断开的连接会持续占用 pool worker 与准入名额，`max_inflight=110` 的余量（=10）被「死连接」吃掉 → 新连接与 PATCH/DELETE 等管理请求被 503；每例还产生一行超时日志噪音 | 建议：`finally` 内 `self.close_connection = True`；`StreamHandler.log_error` 同步抑制超时消息。

【P1】stream.py:770-814 + 279-292（vs config.py:40-44）: 准入只校验 `MAX_CODES_PER_SUB=200`，而 `refresh_capacity(8, fields)` 在交易时段给出 `coverage_codes = 23`（1 字段）/ **7**（3 字段）；一个合法的 200 码 × 3 字段订阅，每 tick 只覆盖 7 码，`lag = ceil(200/7) = 29` tick ≈ **232s**，而 POST 返回 201 时对客户端**没有任何容量信号**。| 依据：`coverage = max(1, int(0.8*8*8/2.2)) = 23`（290-292）；C2 用 `coverage_codes` 切 `_prefetch_slice`（352-354）；`lag` 只进 gauge（386），不进帧、不进 201 响应 | 影响：短线用户按上限建自选后，单帧 96%+ 为 `null`（`missing`），任一代码行情约 4 分钟才刷新；`_build_frame` 用 `null` 覆盖而非携带上一次已知值，"准确/高效"在这一档订阅上不成立 | 建议：把「可全量刷新的最大码数」放进 201 响应/告警（或据此收紧 `MAX_CODES_PER_SUB`）；C2 帧携带 last-known 值，只对真正无缓存的码给 `null`。

【P1】server.py:817-857（关键区间 823-836）: `/healthz?check=1` 在 `_health_sem.acquire()` + `_set_health_inflight(+1)` 之后到 `_HealthBatch` 的异步回调之间**没有 try/finally**；`_run_health_checks` 或 payload 组装一旦抛异常（`fut.result()` 会重抛 worker 的 BaseException；807 与 849-856 的调用链无兜底），admission 名额与 `healthz_inflight` gauge **永久泄漏**，累计 5 次后所有 `check=1` 恒返回 stale 快照（服务"看起来"永远降级）。| 依据：`_release_health_slot()` 只被 `_HealthBatch.task_done`（731-740）与 executor 构造失败分支（770-774）调用 | 影响：唯一的端到端探针自锁死 → 短线运维不可观测，且 stale 分支还可能带 `status: ok` 返回 200（829-834）| 建议：acquire 成功后 try/except 包裹，异常路径显式 `_release_health_slot()`；`fut.result()` 单独兜底。

【P1】stream.py:344-348 vs 709: `_push_once` 与 `_refresh_pool` **各自独立调用 `tick_interval()`**；在 09:30 / 11:30 / 13:00 的档位翻转瞬间，一个算到 8s、另一个算到 120s，`coverage` 相差 15 倍 → 边界那个 tick 可能对整池发起 C1 全量刷新（200 码 × 3 字段 = 600 fetch），而上游恰在开盘/收盘最忙。| 依据：`refresh_capacity(tick)` 使用函数内重算的 tick（344-345），与本次 round 的调度 tick 无关联 | 影响：会话边界的上游突发 + tick 严重超预算（仅被 `stream_tick_slip_total` 计数、不阻止），易触发上游限流/负缓存级联 | 建议：tick 在 `_push_once` 算出一次后显式传入 `_refresh_pool(codes, now, fields, tick)`。

【P2】server.py:1072-1076 vs 892: `_cache_age()` 用裸 `self.path.split('?')[0]` 查域，路由却用 `urlparse(self.path).path`；对 absolute-form 请求行（`GET http://host/stock/data?code=x HTTP/1.1`）路由命中 `/stock/data`，域查表却落空 → 退回 `_DEFAULT_AGE_DOMAIN='f10'`（509）的 **300s**，实时行情被标成 `Cache-Control: public, max-age=300`（正常 quote=8s）。| 依据：`urlparse` 会拆出 netloc+path，`split('?')` 不会 | 影响：共享缓存可把 8s 时效的实时行情缓存 5 分钟，短线客户端读到过期价（仅 absolute-form 触发：健康探针、代理、部分 curl 习惯）| 建议：`_cache_age` 改用 `urlparse(self.path).path`，或复用 `_handle_request` 已解析的 path。

【P2】server.py:927-969 + 245-268: 4 个 CDP 面板与 `/cls/hotplate`、`/market/margin` 在浏览器/CDP **完全不可用**时仍返回 `200 + {"error": ...}`（`_send_json_shape`→`_send_json` 固定 200），而 `/healthz` 已被 S2-5 明确改成 503（913-920）。同一"上游不可用"语义在两层不一致。| 依据：`handle_finance_market` 等直接 `return {'error': ...}`（249/253/268/272/283/290/302/305）| 影响：客户端/监控用状态码探活会看到 200 健康，只有解析 body 才能发现浏览器已死；短线客户端的 liveness 探针会误判 | 建议：`error` 且无有效数据时降级为 503（或统一 `X-Degraded: 1`），与 healthz 对齐。

【P2】stream.py:605-609: `_broadcast` 在 `for conn in conns` **之前**就 `_reserve_for(frame.size)`，但 conn 可能全部在 611-612 的 `if conn.closed: continue` 被跳过（关闭但 handler 尚未 discard 的窗口）→ 本轮会为「一个根本不会被入队的帧」驱逐其他组的真实帧。| 依据：609 先于 610-612；`_frame_acquire` 只在实际入队分支执行（621-636），账目不漂移 | 影响：接近 128MB 预算上限时，活客户端可能无谓丢一帧（下个 tick 自愈）| 建议：先 `live = [c for c in conns if not c.closed]`，为空直接 `continue`，非空再 `_reserve_for`。

【P2】stream.py:1095-1106 + server.py:1179-1187: `max_workers == max_inflight == MAX_STREAM_CONNS + 10`，SSE 长连接与管理端点共用同一池；100 个 SSE 占满后只剩 10 个 worker，管理面（PATCH/DELETE/GET 状态）与数据面争抢，且叠加 P1-4 的 40s 死连接占位后更早打满。| 依据：`make_stream_server` 注释自称"不被 MAIN 默认掩盖"，但仍未给管理端点预留独立预算 | 影响：连接数接近上限时客户端无法 PATCH/DELETE 自救（管理面被数据面挤占）| 建议：SSE 与管理端点分池，或预留 `max(4, 10%)` 的管理专用 worker。

---

## 已核验、未发现问题的点（避免"漏审"误解）

- **锁清单/锁序**：`_groups_lock(RLock) → g.conns_lock` 单向；`_frame_bytes_lock` 是叶子（`_reserve_for` 先释放再取 `_groups_lock`）；`_conn_count_lock` 不与 frame 锁嵌套；`_slice_view_lock → _prefetch_cursor_lock` 单向。未发现环。
- **锁内 IO**：`_broadcast` 的帧构建、`_fetch_concurrent` 的网络等待、`destroy_group` 的 drain 都在锁外；`create_group` 锁内只做整数/字典运算。**未发现锁内网络 IO**。
- **引用计数与字节账**：`_frame_acquire` 先计费再入队 + 双 `put_nowait` 失败回滚 + `conn.closed` 收口（637-638）+ `_pop_oldest_frame` 消费哨兵不计费，逐条推演未发现 ghost frame / 双释放 / 负数帐。
- **C1/C2 与分片覆盖**：`_prefetch_slice` 返回 `ordered[:size]`（rotation 首段）与 `_prefetch_advance(len(sl), n)` 一致；`sl` 非空（size≥1）；`rest` 与 `sl` 互补无重叠。
- **SSE 帧契约**：`json.dumps(separators=(',',':'), ensure_ascii=False)` 不会输出裸换行，`data:` 单行契约成立；`event/id/data/空行` 顺序正确；`None` 哨兵不计费。
- **Host 头**：`_valid_host_header` 正则拒绝 `@ / CR LF` 与超长，IPv6 分支独立；`private + Vary` 在 `PUBLIC_BASE_URL` 为空时覆盖 feed/OPML 两条宿主相关响应。
- **测试有效性**：P0-1（表格空条目错位）与 P1-2（非 list body）两条路径在 `tests/test_stream.py`、`tests/test_server*.py` 中都**没有对应用例**——"测试全绿"掩盖了它们。

## 统计与结论

| 等级 | 数量 | 条目 |
|---|---|---|
| P0 | 1 | 营业部/股票位置错配（静默错数据） |
| P1 | 6 | 无 deadline 的 tick 阻塞 45s；畸形 body 崩溃；SSE 退出不关闭连接占 40s；200 码订阅覆盖率 3.5%；healthz 名额泄漏；tick 档位翻转突发 |
| P2 | 4 | `_cache_age` 域查表落空→300s；CDP 面板 200 vs healthz 503；`_reserve_for` 为幽灵帧驱逐；管理面与数据面共池 |

**评审结论：❌ 阻断（1×P0）。** 最担心 Top1：**P0-1 的静默金融数据错配**——它是唯一"不报错却直接误导交易决策"的缺陷，且修复成本极低（`broker_idx` 无条件自增）；其余 P1 都是短线场景下"黑屏/过期/不可观测"的直接来源，建议一并处理后再进入下一轮门禁。

