# 代码评审报告 — 财联社 4 池独立接口（cls_pools）

**CR-20261010-001 | 模式: P5b review+drift（含 P7a 漂移检测）| 日期: 2026-10-10**
**评审基准: `doc/detailed/cls_pools.md` v1.0.0（含 P3b 评审条件 P1-01 str 守卫 / P1-02 fail-loud on 非 list data）**
**变更文件: `china_finance_rss/server.py`(+89) · `china_finance_rss/config.py`(+7) · `tests/test_server_http.py`(+200)**
> `opencode.json` 变更系上一会话用户改动，不在本流水线评审范围，已排除。

---

## 一、评审概要

**总评：实现质量高，详设 §5 伪代码逐段落地且两处 P3b P1 条件（str 守卫 / fail-loud）均已实现并被可证伪测试覆盖；13 个注册点 R1–R13 一个不漏，4 条 SIDE-EFFECT 逆向核对未发现隐藏消费者被改坏。无 P0 / P1。**

| 项目 | 结果 |
|------|------|
| **结论** | ✅ APPROVE（P0=0，P1=0，P2=1；漂移 4 条已申报待同步 + 1 条未申报非阻断） |
| P0 (阻断) | **0** |
| P1 (建议修复/生产阻断) | **0** |
| P2 (记录不阻断) | **1** |
| 进入测试 | ✅ 允许 |

## 二、评审范围与方法

| 端点 | `GET /cls/up_pool` · `/cls/continuous_up_pool` · `/cls/up_open_pool` · `/cls/down_pool`（均 shape=object，恒 200 + N1） |
|------|------|
| 重点 | `handle_cls_pool`（server.py:434-475）、`_POOL_HANDLERS`/`_POOL_TYPES`（:560-566）、注册表/断言（:527-593）、分发分支（:1299-1304）、feeds（:981-1022）、首页（:1598-1618）、config（:227-232）、测试（ClsPoolTests :240-387 / HttpSemanticsTests :716-865 / HealthPayloadTests :659,670） |
| Dim 0 | 无前端/小程序端 → 0.B/0.C 跳过；后端契约以详设 §2.1 OpenAPI + §2.4 上游契约为唯一权威逐字段核对 |

## 三、SIDE-EFFECT 逆向核对（4/4 通过）

| # | 受影响点（模块） | 逆向假设 | 结论 |
|---|----------------|---------|------|
| 1 | server:`_base_feed_entries` feeds 15→19（healthz） | 谁还在数 feeds？→ 全仓 grep：仅 `HealthPayloadTests:659`（`len(payload['feeds'])==19`）与 `:670`（`len(entries)==19`）两处硬断言，均已改 19；`build_health_payload` 无内联计数；API.md feeds 字段为 schema 描述不含条数 | ✅ R12/R13 覆盖，无第三处遗漏 |
| 2 | server:`_serve_index` JSON 表 14→18 行（首页） | 谁消费首页行数？→ 仅 `/` 静态页；无行数断言；新增 `test_index_page_lists_all_four_pools` 断言 4 路径在 HTML 中；OPML 只用 `ROUTES`（池为 JSON 非 RSS，不入 OPML 是正确边界） | ✅ 无隐藏消费者 |
| 3 | server:`_handle_request` 在 hotplate 前插池分支 | 会遮蔽谁？→ `_POOL_HANDLERS` 为精确 key 字典，`/cls/hotplate`、`/cls/plate` 为 `==` 比较，路径互斥；`/cls/up_open` 形近路径仍落 404（`test_unregistered_pool_like_path_is_404` 实测）；BR-SRV-1 分发顺序（/→opml→healthz→panels→batch→其余 JSON→RSS→404）未破坏 | ✅ 既有端点路由不变 |
| 4 | server:`assert len(_JSON_SHAPES)` 14→18（导入期护栏） | 护栏与消费方是否同步？→ `_JSON_DISPATCHED_PATHS |= set(_POOL_HANDLERS)` 使 :575 断言自洽；`ShapeTableTests:47` 已改 18；batch 子集断言（:547）不受影响（池为 object） | ✅ 护栏一致，无导入期/测试期裂缝 |

## 四、维度评审详情

### D0 契约一致性 — ✅ 通过

| 契约点 | 详设依据 | 实现核对 |
|--------|---------|---------|
| 4 路径 + shape=object | §2.1 | `_JSON_SHAPES` :533-534 四条 'object' ✓ |
| 上游 URL / Headers | §2.4 / R1 | `config.py:228-232` 与详设逐字一致（UA + Referer cls.cn/finance）✓ |
| params 集 {app,os,sv,type,way,rever}+sign | §2.4 / BR-POOL-5 | server.py:449-453 ✓；`cls_sign_params` 内部按 key 排序（utils.py:84），传参顺序无关 ✓ |
| `way='last_px'` 恒定（踩坑项） | BR-POOL-2 | :451 硬编码 + 测试断言 URL 含 `way=last_px` 且不含 `change_px` ✓ |
| TTL 唯一来源 `cache_policy('plate')['ttl']` | BR-POOL-3 | :459 ✓；全仓无 `ttl=12/120` 裸字面量；`_CACHE_AGE_DOMAINS` 4 路径→'plate'（:587-588）max-age 与 TTL 同源 ✓ |
| 成功/失败体互斥键集 | §3.1/§3.2 | 成功 `{'stocks':…}` 无 error 键；失败 `{'error':…}` 无 stocks 键 ✓（测试断言 `set(result)=={'error'}`） |
| N1 恒 200 | §2.1 | 分发走 `_send_json_shape` → `_guard` object shape → `_send_json` 恒 200 ✓；`test_pool_upstream_failure_is_200_with_error_body` 断言 `http_503_total` 不变 ✓ |
| **P1-02 fail-loud**（详设叠加的评审条件） | P3b 条件 | :470-474 非 list data → `log.warning` + `{'error': 'upstream data shape unexpected: <type>'}` ✓（覆盖 dict / None 两形态）。**注意：此语义覆盖详设 §5 伪代码/BR-POOL-6 的「非 list ⇒ []」旧口径**——实现服从评审条件，详设本体待同步（见漂移节 D2-3） |
| **P1-01 str 守卫** | P3b 条件 | :445 `isinstance(pool_type, str)` 先于 frozenset 成员测试 → list/dict/set 入参不再触发 TypeError，总函数契约成立 ✓ |

### D1 数据与正确性 — ✅ 通过

- 枚举闸在拼 URL 之前（BR-POOL-9）：非法值不触网、不铸缓存键；`fetch.assert_not_called()` 真实断言 ✓。
- 信封三级判定完整：非 dict → `malformed upstream response`；`code!=200` → `msg or 'upstream_error'`（9000 场景覆盖）；data 非 list → fail-loud。无隐式状态转换、无重复数据源。
- `except Exception as exc: {'error': str(exc)}` 为 BR-POOL-8 显式总函数约定（与 `_guard` 同口径），非宽泛吞异常反模式——错误对外可见且 `log.exception` 由 `_guard` 兜底层补充。

### D2 并发 — ✅ 通过

`handle_cls_pool` 纯局部变量；`_POOL_HANDLERS`/`_POOL_TYPES`/`_JSON_SHAPES`/`_CACHE_AGE_DOMAINS` 导入期构建、运行期只读；无新模块级可变状态、无新锁。缓存并发责任全在既有 `cache.fetch_json` 四段式协议。

### D3 资源与性能 — ✅ 通过

单 URL 单次 `fetch_json`（plate 域共享 URL 缓存 + 负缓存抑制故障放大）；无 N+1、无新 HTTP 客户端、无资源泄漏面。4 端点与 hotplate/plate 共享 plate 域缓存键空间（URL 不同、域策略同源）。

### D4 安全 — ✅ 通过

- 无注入面：无 query 参数消费；`pool_type` 经枚举闸白名单；URL 经 `urlencode`；headers/URL 常量集中 config。
- 枚举闸防「任意值注入上游请求 / 铸造缓存键」（BR-POOL-9）——这是本增量唯一新增的外部输入面，已封闭。
- 零第三方依赖；无敏感信息泄露；错误体 `str(exc)` 不含凭据（URL 无 token）。

### D5 结构与可维护性 — ✅ 通过（1 条 P2 见问题清单）

表驱动分发（路由分支零 type 字面量，BR-POOL-1）、常量入 config（R1/R2）、包内相对导入、命名/docstring/日志风格与 `handle_cls_hotplate` 族一致；`_POOL_HANDLERS` 紧邻 `_PANEL_HANDLERS` 且位于 `_JSON_DISPATCHED_PATHS` 断言之前（R5 定位约束满足）。无上帝对象/过度工程/复制粘贴。

### 测试质量（可证伪性）— ✅ 通过

| 检查点 | 结论 |
|--------|------|
| mock 全限定名 | 全部 `patch.object(srv, 'fetch_json' / 'handle_cls_pool' / …)`，无字符串 patch；stub 签名 `(url, headers=None, ttl=None, encoding=None)` 与 `cache.fetch_json` 兼容；无外部网络/CDP 依赖（HTTP 用例走 127.0.0.1 本地 `BoundedThreadPoolServer`） |
| 断言非自证循环 | T3 断言 URL 契约/headers/TTL 真实捕获值 vs `cache_policy` 独立计算；T5 sign 等式用 `utils_mod.cls_sign_params` 独立重算——若 handler 漏/多传参，等式即破（算法本身正确性属 utils 自有测试域，边界划分正确）；枚举闸断言 fetch **未被调用**；P1-02 断言精确错误文案 + `assertLogs` WARNING |
| 详设 14 用例覆盖 | POOL-T1..T14 全部落地：T10/T11/T-guard/404 在 `HttpSemanticsTests`（:827-865），T12/T13/T14 在 `ClsPoolTests`（:259-376），R11/R12/R13 三处计数断言均更新。T8 按 P1-02 语义实现（偏离详设旧口径，已申报 DOC_SYNC） |
| 注册点断言 | `test_pool_paths_registered_in_the_shape_tables` 一次覆盖 _POOL_HANDLERS 全表/_POOL_TYPES/4×shape/4×dispatched/4×cache-age 域——新增第 5 池路径漏注册即红 |

## 五、问题清单

| ID | 等级 | 文件:行号 | 反模式 | 问题 |
|----|------|----------|--------|------|
| #CP1 | P2 | `china_finance_rss/server.py:1813-1825` | 注册面不完整（低危） | `main()` 启动日志「Utilities」清单列出 hotplate/plate/stock/*/margin 等 JSON 端点，但未补 4 个池端点——运维从启动日志发现不了新端点（首页/healthz/API 契约均已覆盖，仅日志可发现性缺口） |

## 六、修复建议

- **#CP1（P2，不阻断）**：`main()` 的 Utilities 日志块追加 4 行（仿 :1817 hotplate 行格式，标注 "JSON, no CDP needed"）。可与 P7b 文档同步批次顺带处理，无需单独修复轮。

## 七、漂移检测（P7a）

### D1 契约核对（实现 vs `doc/detailed/cls_pools.md`）

| # | 项 | 详设 | 实现 | 定性 |
|---|----|------|------|------|
| 1 | 注册点 R1–R13 | §2.5 | 13/13 落实（含详设补列的 R12/R13 feeds 计数）；§10#5 两处非阻断漂移（`_JSON_SHAPES` 注释 14→18、feeds docstring 15→19）亦已同批修复 | ✅ 无漂移 |
| 2 | 伪代码/分发表/闭包绑定 | §5 | 逐段一致（`lambda pt=pool_type:` 默认参数绑定、shape 从表读、无 type 字面量） | ✅ 无漂移 |
| 3 | 非 list data 语义 | BR-POOL-6 / §5 伪代码 / §6 表 / POOL-T8：「非 list ⇒ `{'stocks': []}`」 | 实现为 fail-loud `{'error': …}`——**服从 P3b 评审条件 P1-02（评审基准确认该条件叠加于详设之上）**，详设本体未回写 | ⚠️ 漂移，已申报 DOC_SYNC #3，需同步 |
| 4 | 测试落地位置 | §8「建议」handler 单测入 test_server.py | 全部 consolidated 于 test_server_http.py（ClsPoolTests/HttpSemanticsTests），覆盖无损 | ✅ 建议性条款，非漂移 |

### D2 `>>DOC_SYNC:` 追溯（code-developer 申报 4 条，逐条裁定）

| # | 申报 | 现状核验 | 裁定 |
|---|------|---------|------|
| 1 | `API.md` → 新增 4 池端点 | API.md 端点章节（§38 起）无 `/cls/up_pool` 等条目 | ✅ **真实需要**，待同步（对外契约可见面） |
| 2 | `README.md` → 端点表补 4 条 | README:62 端点表仅有 `/cls/hotplate`，无池条目 | ✅ **真实需要**，待同步 |
| 3 | `cls_pools.md` P1-02 语义回写 | BR-POOL-6/§5/§6/POOL-T8 仍为「非 list ⇒ []」旧口径，与实现及 P1-02 条件矛盾 | ✅ **真实需要且优先级最高**——不回写则后续读者/维护者可能按详设把 fail-loud 「修回」静默空池 |
| 4 | `server.md` 计数 | 仍存「14 个 JSON 分支」（:35/:188/:556/:757/:1869/:2025/:2128）、`assert len == 14`（:197/:217/:1937）、feeds「15 条」（:461/:713/:1514/:1961）、BR-SRV-1 分支枚举未含池 | ✅ **真实需要**（结构性计数漂移，多处） |

### D3 规范合规 — ✅ 通过

零第三方依赖；包内相对导入；`fetch_json` 唯一 HTTP 出口（全仓无新增 urlopen）；配置集中 config.py；业务函数不抛；路由集中 dict；测试全限定名 + 无外部网络。layerIsolation 无新增跨模块边。

### D4 漂移结论

**4 条申报 DOC_SYNC 全部核实为真实需要，均处于待同步状态（编排层 P7b 待 dispatch doc agent）；未申报漂移 0 条代码级；#CP1（main() 启动日志）为注册面完整性 P2，可选顺带同步。**

---

## 八、评审结论

实现与详设契约高度一致，两项 P3b P1 修复条件均落地且有可证伪测试锚定；13 注册点齐全，SIDE-EFFECT 逆向核对未发现回归。代码无阻断问题；4 条文档同步按既定 DOC_SYNC 机制由编排层承接（其中 #3 详设 P1-02 语义回写建议优先）。

**>>DECISION: APPROVE**


