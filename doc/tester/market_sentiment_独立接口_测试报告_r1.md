# 财联社 market_sentiment 独立接口 · 测试报告 r1

- **阶段**：P6c 测试执行（阶段二）｜强度 🟢 标准｜`>>SCOPE: modules=server,config,tests`
- **日期**：2026-10-10
- **被测增量**：`china_finance_rss/server.py`（`handle_finance_market_sentiment` + 7 注册点 + `/finance/market` 剥离 + 5×P2 修复）、`china_finance_rss/config.py`（`_FINANCE_EXPECTED_KEYS` 删键 + plate 注释）、`tests/test_server_http.py`、`tests/stress_all.py`
- **契约依据**：`doc/detailed/market_sentiment_独立接口.md` v1.0.1 §8 MS-T1..T16；`doc/detailed/server.md` §8 SRV-T74
- **前序**：code-reviewer 代码评审通过（B-01..B-05 五条 P2 修复）
- **测试策略**：零外网 / 零 CDP（`patch.object(srv, 'cdp_engine'|'page_data'|'fetch_json')` 打桩）；**本轮额外做变异（mutation）验证，逐条核对新用例可证伪性**

---

## 1. 结论

✅ **PASS-WITH-NOTES**

- 详设 **MS-T1..T16 全部 16 条落地**（15 条断言有效 + 1 条半句架空 → 本轮补测闭合）；全量 **562 用例 0 失败 / 0 错误 / 4 跳过**（跳过 = B-01 集成门控，无外网预期行为），无 P0/P1。
- 变异验证 **21 次注入**：**16 次被具名用例抓住、2 次被 import 期结构守卫抓住、2 次未被抓住**（1 条为本轮新增用例 MS-T11 的断言缺陷 → 已补 `MS-T11b` 闭合；1 条为 `stress_all.py` 脚本不在 unittest 发现范围，存量性质）。
- 记 **1 条 P2（测试自身缺陷）**，已在本轮用补测闭合，不阻断；业务代码 **0 缺陷**。

---

## 2. 执行摘要

| 指标 | 值 |
|------|-----|
| 静态检查 | `python -m py_compile china_finance_rss/*.py tests/*.py` 通过；`git diff --check` 干净 |
| T1 定向 ① | `python -m unittest tests.test_server_http -v` → **Ran 144, OK (skipped=4)**，2.73s |
| T1 定向 ② | `python -m unittest tests.test_server tests.test_config tests.test_data_layer -v` → **Ran 173, OK**，0.82s |
| T2 全量 | `python -m unittest discover -s tests -v` → **Ran 562, OK (skipped=4)**，5.33s |
| 失败 / 错误 / Flaky | **0 / 0 / 0**（无失败即未触发 Step 3.7 重试） |
| 变更相关用例 | **19 条绿 + 4 条 skip = 23**（见 §3） |
| 本轮新增用例 | **1 条**：`HttpSemanticsTests.test_head_body_never_reaches_the_wire`（MS-T11b，见 §5） |
| 缺陷（P0/P1/P2） | **0 / 0 / 1**（P2 属测试自身，已闭合） |
| 变异注入 | 21 次（方法见 §4） |

> 跳过明细：`ClsPoolIntegrationTests` 4 条（MS-T12 / B-01，`CLS_INTEGRATION=1` 门控）——**无外网环境下跳过即预期行为，不计失败**。

## 3. MS-T1..T16 ↔ 落地用例映射（16/16）

| 用例 | 落地测试（`tests/test_server_http.py`） | 结果 |
|------|----------------------------------------|------|
| **MS-T1** 路由/形状登记 | `MarketSentimentTests.test_registered_in_the_shape_and_dispatch_tables` | ✅ |
| **MS-T2** 成功原样透传 | `MarketSentimentTests.test_success_returns_the_upstream_object_verbatim` | ✅ |
| **MS-T3** CDP 未就绪 | `MarketSentimentTests.test_cdp_unavailable_is_an_error_body`（`None` + `ready=False` 两变体） | ✅ |
| **MS-T4** `page_data` None | `MarketSentimentTests.test_page_data_none_degrades` | ✅ |
| **MS-T5** 键缺失非裸 null | `MarketSentimentTests.test_missing_key_never_returns_bare_null` | ✅ |
| **MS-T6** HTTP 分发恒 200 | `HttpSemanticsTests.test_market_sentiment_dispatches_200_in_success_and_degrade`（真实 `_PANEL_HANDLERS`，非 patch handler） | ✅ |
| **MS-T7** cache-age `quote` | `CacheAgeTests.test_realtime_panels_use_quote_domain`（5 面板遍历）+ MS-T1 内 `_CACHE_AGE_DOMAINS` 断言 | ✅ |
| **MS-T8** `/finance/market` 已剥离 | `MarketSentimentTests.test_finance_market_strips_market_sentiment`（`assertNotIn` + `assertIn('articles')`） | ✅ |
| **MS-T9** 剥离双动作三态 | `MarketSentimentTests.test_strip_requires_pop_and_expected_removal_together`（a/b/c 三子断言） | ✅ |
| **MS-T10** feeds 索引 20 | `HealthPayloadTests.test_schema_check0_zero_upstream` + `test_feed_status_corrections` | ✅ |
| **MS-T11** HEAD + 首页 | `HttpSemanticsTests.test_head_on_market_sentiment_writes_no_body`（status 半句 ✅ / **body 半句架空**）+ `MarketSentimentTests.test_index_page_lists_the_endpoint` | ⚠→✅ 补 T11b |
| **MS-T12**（B-01）真上游冒烟 | `ClsPoolIntegrationTests` ×4（`skipUnless(CLS_INTEGRATION)`） | ⏭ skip（预期） |
| **MS-T13**（B-02）失败留日志 | `ClsPoolTests.test_fetch_failure_logs_a_warning_before_degrading` | ✅ |
| **MS-T14**（B-03）msg 归一 str | `ClsPoolTests.test_non_string_upstream_msg_is_normalised_to_str` | ✅ |
| **MS-T15**（B-04）TTL 守卫正则 | `ClsPoolTests.test_pool_handler_has_no_bare_ttl_literal` | ✅（见 §6-2） |
| **MS-T16**（B-05）plate 注释 | `ClsPoolTests.test_plate_domain_comment_lists_the_four_pools` | ✅ |

间接覆盖（同一变更面）：`ShapeTableTests.test_json_shapes_complete_and_consistent`（19 计数）、`test_every_shape_path_has_a_routed_branch`（dispatched 全等）、`CacheAgeTests.test_registered_paths_follow_policy`（全注册表遍历）。

**覆盖结论：16/16 全部落地；唯一缺陷在 MS-T11 的 body 半句（不可证伪），已由 MS-T11b 补测闭合。**

## 4. 可证伪性验证（变异注入 · 逐条核对）

**方法**：把工作区完整复制到 `/tmp/opencode/ms_*`（**不动工作区业务代码**），对每条关键断言注入 1 处最小变异 → 只跑相关用例 → 看是否变红。变异源与断言必须一一对应，否则视为「未命中」。

| # | 注入变异（被测代码） | 期望抓住它的用例 | 实测 |
|---|---------------------|-----------------|------|
| M1 | 删 `handle_finance_market` 的 `data.pop('market_sentiment', None)` | MS-T8 | ✅ 变红 |
| M2 | `config._FINANCE_EXPECTED_KEYS` 放回 `'market_sentiment'` | MS-T8 **+ MS-T9** | ✅ 双红 |
| M3 | 删 `handle_cls_pool` 的 `log.warning`（B-02） | MS-T13 | ✅ 变红 |
| M4 | 去掉 `str(raw.get('msg') …)`（B-03） | MS-T14 | ✅ 变红 |
| M6 | 删 `if ms is None` 分支 | MS-T5 | ✅ 变红 |
| M7 | `return ms` → `return dict(ms)`（破坏 verbatim） | MS-T2 | ✅ 变红 |
| M8 | `ttl=cache_policy('plate')['ttl']` → `ttl=30`（B-04 真回归） | MS-T15 ①半 | ✅ 变红（并连带 POOL-T3 动态断言红） |
| M9 | 删 plate 注释里的 `4 cls pools`（B-05） | MS-T16 | ✅ 变红 |
| M10 | 新端点 `_CACHE_AGE_DOMAINS` 改回默认域 | MS-T1 + `CacheAgeTests` | ✅ 双红 |
| M11 | 删 `if data is None` 分支 | MS-T4 | ✅ 变红 |
| M12 | 摘掉 `handle_finance_market_sentiment` 的 CDP 就绪门 | MS-T3 | ✅ 变红（ERROR） |
| M20 | 改 CDP 门错误串为 `'CDP down'` | MS-T3 | ✅ 变红（FAIL，证明断的是具体串） |
| M13 | `cache._fill_missing` 删掉第二个循环（不保留 extra 键） | MS-T9(a) | ✅ 变红 |
| M14 | `_base_feed_entries` 去掉 market_sentiment 条目 | MS-T10 ×2 | ✅ 双红 |
| M15 | 首页 `json_apis` 去掉该端点 | MS-T11（首页半句） | ✅ 变红 |
| M18 | `_PANEL_HANDLERS` 把该路径指向 `handle_finance_timeline` | MS-T1 + MS-T6 | ✅ 双红 |

**由 import 期结构守卫（而非具名用例）抓住的 2 次**：

| # | 变异 | 抓住者 | 判定 |
|---|------|--------|------|
| M5 / M5b | 从 `_JSON_SHAPES`/`_PANEL_HANDLERS`/`_CACHE_AGE_DOMAINS` 单独或协同摘除新端点 | `assert len(_JSON_SHAPES)==19` / `assert _JSON_DISPATCHED_PATHS == frozenset(_JSON_SHAPES)` | ✅ 导入即失败（合法防线，但**不是用例断言**——MS-T1 自身对这三种变异不会红） |
| M19 | `_PANEL_HANDLERS` 多加一个假条目 | 同上 dispatched 全等断言 | ✅ 导入即失败 |

**未命中的 2 次（本轮核心发现）：**

| # | 变异 | 实测 | 结论 |
|---|------|------|------|
| **M16** | `do_HEAD` 改 `write_body=True`（服务器**真的**往 HEAD 写 body） | **18 条 `HttpSemanticsTests` 全绿**；裸 socket 实测线上 **54 字节 body**（对照 pristine HEAD **0 字节**） | ❌ **MS-T11 的 `assertEqual(body, b'')` 不可证伪**：`http.client` 对 HEAD 把读取长度归零（RFC 9112 §9.3.2），服务器写没写它都返回 `b''`。→ 记 BUG-MS-01(P2)，已补 MS-T11b 闭合 |
| **M17** | `tests/stress_all.py` 的 `/finance/market` 期望键清单回加 `market_sentiment` | 无任何用例红（该脚本不以 `test_*` 命名，不进 discovery） | ⚠ 脚本级改动无自动化护栏，属存量机制（见 §6-3） |

**方法学备注（诚实披露）**：`server.py` 中「CDP 就绪门 + `get_page('cls_finance')` + `page_data(page)`」三行块有 **3 处同型副本**（market / timeline / market_sentiment），按行替换的前两次尝试命中了错的函数、给出假绿——改用「函数签名 + docstring 唯一锚点」后 M12 才有效。**变异锚点必须唯一**，否则「未命中」既可能是用例缺陷也可能是变异打偏。

## 5. 补充测试说明（tester 职权内，仅改 `tests/**`）

| # | 新增用例 | 位置 | 补充原因 |
|---|---------|------|---------|
| 1 | `HttpSemanticsTests.test_head_body_never_reaches_the_wire`（**MS-T11b**，标 `[逆向]`） | `tests/test_server_http.py`（新增 `_raw_exchange` 裸 socket 助手 + `import socket`） | 详设 MS-T11 要求「HEAD ⇒ 200、body `b''`」，落地用例借道 `http.client`，而它对 HEAD **把读取长度归零**，断言恒真（M16 已证：改 `do_HEAD` 写 body，线上 54 字节，18 条用例仍全绿）。改读裸 socket：**先用 GET 自证这条读法确实读得到 body**（否则补的用例自己也是空断言），再断 HEAD 三路径（新端点 / 首页 / 404）线上 0 字节，且头部仍按 GET 口径给出非零 `Content-Length`。 |

**补测可证伪性自检**：在 `do_HEAD → write_body=True` 变异下 `test_head_body_never_reaches_the_wire` **红**（其余 17 条仍绿，差异可归因）；在当前代码下 **绿**。原 MS-T11 的 `status==200` 半句仍有效，予以保留。

**未改业务代码**：全部发现仅报告，`server.py` / `config.py` 零改动（`git diff --check` 干净）。

---

## 6. 未覆盖点与观察项（均不阻断）

| # | 类型 | 说明 | 处置 |
|---|------|------|------|
| 1 | **存量覆盖缺口** | `/finance/market` **自身**的 CDP 就绪门错误串无具名断言——`test_cdp_unavailable_panel_is_200_with_error_body` 把 handler 整个 patch 掉了。变异证明：摘掉 market 的门（M12-first-occurrence）**26 条相关用例仍全绿**。本轮 MS-T3 只覆盖**新**句柄。 | `>>DOC_SYNC: doc/detailed/server.md → 建议补 SRV 用例锁定 /finance/market CDP 门错误串（存量缺口，非本轮引入）` |
| 2 | 观察项（MS-T15 ②半） | 合成串 `'ttl=30/60/300'` 对新旧正则的「命中/不命中」是**对测试内正则的恒真断言**，不作用于产品代码；详设 P2-05 明确要求此双向表述，且 ①半（真源必不命中）已被 M8 证明可证伪 | 不记缺陷，仅披露语义边界 |
| 3 | 脚本级改动 | `tests/stress_all.py` 键清单移除 `market_sentiment` 无自动化护栏（不在 discovery） | 需部署级/手工跑一次（`AC-E4`/`stress` 通道），本轮 out of scope |
| 4 | RG7 | `main()` 启动日志 +1 行（新端点 URL）无用例 | 纯日志可观测性，建议不补 |
| 5 | MS-T12 / B-01 | 4 条真上游集成用例 **skip**（无外网） | 预期行为；联网环境需 `CLS_INTEGRATION=1` 复跑 |
| 6 | 并发/时序 | `/finance/market` 顶层 `pop` 与 `/finance/market_sentiment` 读同一页数据 | **已核**：`cdp_engine.get_data()` 每次新建顶层 `merged` dict，`_ingest_payload` 用 `dict.update` 整体替换键绑定、不原地改写已返回信封 ⇒ 顶层 `pop` 不污染缓存、无已知「序列化中被改写」竞态；未写并发用例（存量机制、非本轮引入） |

## 7. 缺陷清单

| BUG-ID | 等级 | 类别 | 描述 | 状态 |
|--------|------|------|------|------|
| **BUG-MS-01** | **P2** | 测试自身缺陷（非业务缺陷） | MS-T11 的 `self.assertEqual(body, b'')` 不可证伪：`http.client` 对 HEAD 归零读取长度，服务器即使写了 body 也返回 `b''`（M16 实测：线上 54 字节，18 条用例仍全绿）。**当前业务代码行为正确**（pristine 裸 socket 实测 HEAD 0 字节），故不涉及产品缺陷。 | ✅ 本轮已闭合：补 `MS-T11b`（裸 socket 线上断言 + GET 自证） |

- **P0 = 0，P1 = 0，P2 = 1（测试自身，已闭合）** → 不阻断本轮。
- **业务代码缺陷 = 0**：21 次变异中没有任何一次暴露「实现与详设不符」的红——所有红都指向被正确断言的注入点。
- Flaky 处理：无失败用例，未触发重试；无 Flaky >1 的用例。
- 附带发现（存量、非本轮 scope）：§6-1 `/finance/market` CDP 门错误串未被断言；§6-3 `stress_all.py` 无自动化护栏。二者均只记录、不修。

---

## 8. 环境与数据策略

- **单元层**：`patch.object(srv, 'cdp_engine'|'page_data'|'fetch_json', ...)` 进程内 fixture 式打桩，用例间无共享可变数据，可并行。
- **HTTP 层**：`HttpSemanticsTests` 用 `BoundedThreadPoolServer(('127.0.0.1', 0))` 本机随机端口；新增 MS-T11b 走裸 socket、HTTP/1.0 close-delimited，读到 EOF 为止，确定性无超时抖动。
- **变异验证层**：全部在 `/tmp/opencode/ms_*` 副本中进行，**工作区业务代码零改动**；变异后仅运行目标用例，跑完即弃。
- **无测试数据库、无外网、无 CDP / Chrome**；测试数据为构造信封（`code/msg/data`）与合成股票条目，不落盘。
- 上游 `x-quote.cls.cn` / 财联社看盘页真实可达性 **本轮未验证**（MS-T12 skip），需联网门控复跑。

---

## 9. 下游提示

- `>>DOC_SYNC: doc/detailed/market_sentiment_独立接口.md → MS-T11 增补 body 半句的落地约束（须为裸 socket/线上断言，不得借道 http.client）+ 登记 MS-T11b`
- `>>DOC_SYNC: doc/detailed/server.md → §8 SRV-T74 补「/finance/market 自身 CDP 门错误串」覆盖缺口（存量）`
- 建议 code-developer 无需返工：本轮 0 业务缺陷，实现与详设 16/16 一致。

---

>>DECISION: PASS-WITH-NOTES — 562 全量 0 失败 0 错误（4 skip 为 B-01 门控预期）；MS-T1..T16 全落地；21 次变异注入证伪核对通过，唯一 P2（MS-T11 HEAD body 断言被 http.client 架空）已由 tester 补 MS-T11b 闭合，业务代码 0 缺陷，不阻断合入。
