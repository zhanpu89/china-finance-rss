# 财联社 4 池独立接口 · 测试报告 r1

- **阶段**：P6c 测试执行（阶段二）｜强度 🟢 标准｜`>>SCOPE: modules=server,config`
- **日期**：2026-10-10
- **被测增量**：`china_finance_rss/server.py`（`handle_cls_pool` + 4 注册表 + 分发分支 + feeds 索引）、`china_finance_rss/config.py`（`_UP_DOWN_ANALYSIS_URL/HEADERS`）
- **契约依据**：`doc/detailed/cls_pools.md` §4 BR-POOL-1..13、§8 POOL-T1..T14
- **前序**：code-developer 已实现并自带测试；P5b 代码评审 **APPROVE**（P0=0 / P1=0，P2 仅 1 条 main() 日志非阻断）
- **测试策略**：上游 `x-quote.cls.cn` 按约定打桩（`patch.object(srv, 'fetch_json', ...)` 全限定），**零外部网络 / 零 CDP**

---

## 1. 结论

✅ **PASS-WITH-NOTES**

全量 544 用例通过（0 失败 / 0 错误 / 0 跳过），详设 POOL-T1..T14 **14/14 全部落地**（T4 静态半句由本轮补测闭环），变更相关 21 条全绿，**无 P0/P1/P2 缺陷**。

带一条非阻断备注：详设 **BR-POOL-6 / POOL-T8 的「`data` 非 list ⇒ `{'stocks': []}`」已被 P5b 评审 P1-02 改判为 fail-loud error**，实现与测试按评审裁决落地，但 `doc/detailed/cls_pools.md` 尚未回填（本轮禁止改详设）→ 见 §6 待回填项。

---

## 2. 执行摘要

| 指标 | 值 |
|------|-----|
| 执行命令 | `python -m unittest discover -s tests -v` |
| 范围判定 | T1 定向（scope=server,config）；本仓单次全量 ≈5s、无定向代价 ⇒ **按任务书跑全量**（同时覆盖 server/config 与全仓回归） |
| 总用例数 | **544** |
| 失败 / 错误 / 跳过 | **0 / 0 / 0** |
| 耗时 | 5.09s（补测后复跑；首跑 5.13s） |
| 变更相关用例 | **20 条主相关 + 1 条次要 = 21** |
| Flaky | **0**（无需重试，无重试 >1 的用例） |
| 缺陷（P0/P1/P2） | **0 / 0 / 0** |
| 本轮新增用例 | 1 条（`ClsPoolTests.test_pool_handler_has_no_bare_ttl_literal`） |
| 静态检查 | `py_compile` 通过；`git diff --check` 干净 |

**变更相关用例分布**：`ClsPoolTests` 11 条（原 10 + 补 1）、`HttpSemanticsTests` 池相关 4 条、`ShapeTableTests` 3 条、`HealthPayloadTests` feeds 计数 2 条、`CacheAgeTests.test_registered_paths_follow_policy`（遍历全注册表，间接覆盖 4 池路径）1 条。

---

## 3. POOL-T1..T14 ↔ 落地用例映射

| 用例 | 落地测试（tests/test_server_http.py） | 结果 | 备注 |
|------|--------------------------------------|------|------|
| **POOL-T1** shape 表计数 14→18 + batch 子集 | `ShapeTableTests.test_json_shapes_complete_and_consistent` | ✅ | 断言 `len(_JSON_SHAPES)==18` 与 batch≡`_STOCK_BATCH_HANDLERS` |
| **POOL-T2** dispatched 一致 | `ShapeTableTests.test_every_shape_path_has_a_routed_branch` + `ClsPoolTests.test_pool_paths_registered_in_the_shape_tables` | ✅ | 集合全等 + 4 池路径逐个 ∈ 表 |
| **POOL-T3** 成功取数 + URL 契约 | `ClsPoolTests.test_success_passes_data_through_and_signs_the_url` | ✅ | `stocks` 透传 ∧ `type/way/rever/app` ∧ `sign` 非空（按 `cls_sign_params` 精确比对）∧ headers == `config._UP_DOWN_ANALYSIS_HEADERS` |
| **POOL-T4** TTL 同源（动态） | 同上（捕获 `ttl == cache_policy('plate')['ttl']`） | ✅ | BR-POOL-3 动态半句 |
| **POOL-T4** TTL 同源（静态：无裸 `ttl=12/120`） | `ClsPoolTests.test_pool_handler_has_no_bare_ttl_literal` | ✅ | **本轮补充**（原未落地），见 §5 |
| **POOL-T5** `way` 恒 last_px + 签名稳定 | `ClsPoolTests.test_sign_covers_exactly_the_specified_params_and_is_stable` + T3 的 `assertNotIn('change_px')` | ✅ | 两次调用 URL 逐字节相同；sign 只覆盖 `{app,os,sv,type,way,rever}` |
| **POOL-T6** 上游业务失败 | `ClsPoolTests.test_upstream_business_failure_is_an_error_body` | ✅ | `code=9000` ⇒ `{'error':'param error'}`；空 msg ⇒ `upstream_error` |
| **POOL-T7** 取数异常不抛 | `ClsPoolTests.test_fetch_or_decode_failure_degrades_without_raising` | ✅ | `FetchError` / 非 JSON / 非 dict 信封 三分支均 `{'error':…}` 且不抛 |
| **POOL-T8** 无数据 / 非 list | `ClsPoolTests.test_empty_list_is_success_but_non_list_data_fails_loud` | ✅ | `data:[]` ⇒ `{'stocks':[]}` 无 error；**非 list/缺 data ⇒ error（语义偏差，见 §6）** |
| **POOL-T9** 枚举闸 | `ClsPoolTests.test_enum_gate_rejects_bad_and_unhashable_types_without_fetching` | ✅ | `bogus/''/None/list/dict/set` 六值 → error 且 `fetch_json` 未被调用（P1-01） |
| **POOL-T10** 4 路径 HTTP 分发 | `HttpSemanticsTests.test_all_four_pool_paths_dispatch_to_200_with_stocks` | ✅ | 4 路径各 200 + `stocks` |
| **POOL-T11** 4 路径降级恒 200 | `HttpSemanticsTests.test_pool_upstream_failure_is_200_with_error_body` | ✅ | 4 路径各 200 + `error`，`http_503_total` 不变（N1） |
| **POOL-T12** cache-age 域 | `ClsPoolTests.test_cache_age_resolves_the_plate_domain`（+ `CacheAgeTests.test_registered_paths_follow_policy` 间接） | ✅ | 4 路径 `_cache_age() == cache_policy('plate')['ttl']` |
| **POOL-T13** feeds 索引 15→19 | `ClsPoolTests.test_healthz_feeds_list_all_four_pools_as_configured` + `HealthPayloadTests.test_feed_status_corrections` + `test_schema_check0_zero_upstream` | ✅ | 4 路径 `status='configured'` 且 URL 拼接正确；总数 19（两处硬断言均已改） |
| **POOL-T14** 分发表值域 | `ClsPoolTests.test_pool_paths_registered_in_the_shape_tables` | ✅ | path 集合与 type 值域均精确等于 4 项 |

**覆盖结论：14/14 落地，无「未落地」用例；仅 T4 静态半句原缺 → 本轮补测。**

补充落地（详设未列但已覆盖的逆向面）：`HttpSemanticsTests.test_unregistered_pool_like_path_is_404`（近似路径 404）、`test_pool_guard_captures_a_raising_handler`（`_guard` 兜底，handler 抛出仍 200+error）、`ClsPoolTests.test_index_page_lists_all_four_pools`（首页端点表可发现性）。

---

## 4. 需求追溯矩阵（4 端点 × 成功 / 失败 / 边界）

| 端点 | 上游 `type` | 成功 | 失败 | 边界 |
|------|------------|------|------|------|
| `GET /cls/up_pool` | `up_pool` | T10 ✅ / T3 ✅（单元直调） | T6 ✅、T7 ✅、T11 ✅、P2-07 guard ✅ | T8 空池 ✅、T8 非 list ✅、T9 枚举闸 ✅、未注册近似路径 404 ✅ |
| `GET /cls/continuous_up_pool` | `continuous_up_pool` | T10 ✅ | T11 ✅ | T14 值域 ✅、T12 plate 域 ✅、T13 feeds ✅ |
| `GET /cls/up_open_pool` | `up_open_pool` | T10 ✅ | T11 ✅ | T14 ✅、T12 ✅、T13 ✅；`/cls/up_open` 近似路径 404 ✅ |
| `GET /cls/down_pool` | `down_pool` | T10 ✅；T5 签名单测以 `down_pool` 采样 ✅ | T11 ✅ | T14 ✅、T12 ✅、T13 ✅ |

跨端点共性覆盖：BR-POOL-1（表驱动，T1/T2/T14）、BR-POOL-3/11（TTL + max-age 同源，T4/T12）、BR-POOL-10（18 条 shape + dispatched 断言，T1/T2 + import 期 assert）、BR-POOL-12（feeds 19，T13）、BR-POOL-13（URL/Header 集中在 `config.py`，T3 断言 headers 来自 config）。

**逆向用例（≥2 条，标注 [逆向]）：**
- `TC-cls-R1` [逆向] `test_unregistered_pool_like_path_is_404` — 注册表**没写**的近似路径必须落回 404（反证注册边界收紧，不是前缀放行）。
- `TC-cls-R2` [逆向] `test_enum_gate_rejects_bad_and_unhashable_types_without_fetching` — 不可哈希 `pool_type` 会让 `frozenset` 成员判断抛 `TypeError`（详设没写的分支），必须就地成 error 且**不触网**。
- `TC-cls-R3` [逆向] `test_empty_list_is_success_but_non_list_data_fails_loud` — 上游把 `data` 换成 dict（`/cls/plate` 的形状漂移）时不得静默成空池，必须 fail-loud（P1-02）。
- `TC-cls-R4` [逆向] `test_pool_guard_captures_a_raising_handler` — 假设「总函数永不抛」被打破时，`_guard` 兜底仍 200+error 且不动 `http_503_total`。

---

## 5. 补充测试说明

| # | 新增用例 | 位置 | 补充原因 |
|---|---------|------|---------|
| 1 | `ClsPoolTests.test_pool_handler_has_no_bare_ttl_literal` | `tests/test_server_http.py`（仅改 tests/**） | 详设 **POOL-T4** 含两句断言，code-developer 只落地了动态半句（捕获 `ttl == cache_policy('plate')['ttl']`），静态半句「`server.py` 本增量无 `ttl=12`/`ttl=120` 裸字面量」无对应用例 → 补 `inspect.getsource(handle_cls_pool)` 源码扫描：`re.search(r'ttl=\s*12\d*')` 必须为 `None`，且源码必须含 `cache_policy('plate')`。 |

**可证伪性自检**：正则对 `ttl=120` 命中（True）、对 `ttl=cache_policy(...)` 不命中（False）——用例能抓真回归，不是恒真断言。作用域限定在 `handle_cls_pool` 函数体（而非整文件），避免未来无关功能合法使用其他 TTL 值时误报。

---

## 6. 偏差与待回填（非阻断）

| # | 类型 | 说明 | 处置 |
|---|------|------|------|
| 1 | **详设 ↔ 实现语义偏差** | `BR-POOL-6` / `POOL-T8` 写「`data` 非 list ⇒ `{'stocks': []}`，无 error 键」；P5b 评审 **P1-02** 判定该静默吞掉契约漂移，改为 fail-loud → `{'error': 'upstream data shape unexpected: <type>'}`。实现与测试均按评审裁决落地。 | `>>DOC_SYNC: doc/detailed/cls_pools.md → BR-POOL-6 / POOL-T8 非 list 分支回填为 fail-loud error（依据 P1-02）`（tester 无权改详设，交编排层） |
| 2 | 对外文档 | 详设 §10#4 已标 `API.md`/`README.md` 待补 4 端点（本轮 out of scope） | 沿用详设既有 `>>DOC_SYNC`，无需重复登记 |

---

## 7. 缺陷清单

| BUG-ID | 等级 | 描述 | 状态 |
|--------|------|------|------|
| — | — | **本轮无缺陷**（P0/P1/P2 均为 0） | — |

Flaky 处理：无失败用例，未触发重试；无 Flaky >1 的用例。

---

## 8. 环境与数据策略

- 单元层：`patch.object(srv, 'fetch_json', ...)` fixture 式打桩，进程内隔离，无共享可变数据，可并行。
- HTTP 层：`HttpSemanticsTests` 用 `BoundedThreadPoolServer(('127.0.0.1', 0))` 本机随机端口，无外部依赖。
- 无测试数据库、无外部网络 / CDP / 上游 `x-quote.cls.cn` 访问；测试数据为构造的信封（`code/data/msg`）与合成股票条目，不落盘。

---

>>DECISION: PASS-WITH-NOTES
