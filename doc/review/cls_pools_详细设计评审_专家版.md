# 财联社 4 池独立接口（cls_pools）详细设计评审报告（专家版）

> **文档编号** REV-DES-20261010-001 · **结论** ⚠️ **有条件通过**（P0×0 / P1×2 / P2×7） · **日期** 2026-10-10 · **产出** review-expert
> **评审对象**：`doc/detailed/cls_pools.md` **v1.0.0**（🟡 草稿 · P3a 详设增量）
> **评审模式**：详细设计评审（增量） · **项目阶段**：**生产版**（2C2G 在线服务，已有部署级验证报告）
> **需求基线**：任务书原文「财联社 4 池独立接口」；上游 SAD/PRD 无专属 AC（本文档 §10#1 已登记）
> **就绪检查（check-common）**：✅ 文档存在、头部版本/状态/日期/作者齐备；无 `{例:`/TODO/待补充占位；§2/§4/§5/§8 均为实值（OpenAPI + BR-POOL-1..13 + 伪代码 + POOL-T1..T14 齐备）⇒ 进入正式评审。checklist 懒加载：`check-detailed`。
> **独立性声明**：仅读被评文件 + 其引用的 `server.py` / `config.py` / `utils.py` / `tests/test_server_http.py` / `tests/test_server.py` 定位；不依赖 task-decomposer 的创作上下文。

## 一、评审概要

| 项 | 值 |
|----|----|
| 结论 | ⚠️ **有条件通过**（无 P0；**P1×2 → 生产版按阻断处理**，闭环 P1-01/P1-02 后放行） |
| P0 | **0**（无崩溃 / 数据丢失 / 资金 / 安全类） |
| P1 | **2**：非 hashable `pool_type` 违反"总函数绝不抛"契约 · 上游契约零夹具佐证 + 错 shape 静默空成功 |
| P2 | **7**：引用错号 / 注释漂移漏列 / 签名类比失真 / 用例机制不可执行 / OpenAPI 不可机读等 |
| **注册点 R1–R13** | ✅ **逐条实核全部命中**（见 §三.1）——含任务书漏列、本详设补列的 R12/R13 |
| 是否允许进入编码 | ⚠️ 需先闭环 **P1-01**（一行类型防御）+ **P1-02**（P5a 前补 1 条真实抓包夹具测试） |
| 端锁定（🟠 STABLE） | ✅ 只增 4 端点；既有 14 JSON / 5 RSS / `/healthz` 契约与响应字段集合不变 |
| 范围纪律 | ✅ 未改既有路由/签名；未新增第三方依赖；未新增 metrics；`>>DOC_SYNC` 正确外抛 `API.md`/`README.md` |

## 二、问题清单

### P1（生产版阻断，须闭环后放行）

**【P1-01】`handle_cls_pool` 的"总函数绝不抛"契约不成立：非 hashable `pool_type` 会抛 `TypeError`**（证据锚点：`cls_pools.md:101`、`:254`、`:289`、`:428`；`server.py:505` `_PANEL_HANDLERS` 表驱动先例）
　问题：§2.2（`:101`）与 BR-POOL-8（`:254`）承诺「任意输入 / 任意上游状态都返回 `dict`，**绝不抛**」，且这是项目硬约定（`handle_*() -> dict` 不抛）。但 §5 伪代码（`:289`）把枚举闸写成 `if pool_type not in _POOL_TYPES:`，而 `_POOL_TYPES` 是 `frozenset`（`:116`/`:333`）——`x in frozenset` 对 **list/dict/set 等非 hashable 入参**会抛 `TypeError: unhashable type`，且该闸**位于 `try` 之外**，`_guard` 兜底也接不住（`handle_cls_pool` 直接被路由 lambda 调用，见 `server.py:1314-1327` 的 `_send_json_shape`）。POOL-T9（`:428`）只测了 `'bogus'`/`''`/`None` 三个 **hashable** 值 ⇒ 该边界**测试结构上无法检出**。
　影响：经路由不可达（`_POOL_HANDLERS[path]` 恒为 `str`），故**生产暴露面≈0**；但文档给出的绝对契约与项目约定被违反，且任一直接调用方（含未来复用）传入 list 即崩——属"看似覆盖实则没写条件"的典型。
　建议（一行修复）：`if not isinstance(pool_type, str) or pool_type not in _POOL_TYPES:`（或把闸包进 `try`）；并把 POOL-T9 扩一条 `handle_cls_pool(['up_pool'])`/`handle_cls_pool({'x':1})` 断言返回 `{'error': ...}` 且不抛。

**【P1-02】上游契约零夹具佐证 + 错 shape 静默降级为"空成功"**（证据锚点：`cls_pools.md:148`、`:207`、`:313-314`、`:392`；对照 `server.py:424`）
　问题：本增量**全部正确性**押在"上游 `data` 是**裸 list**"这一未在仓库内留任何夹具/样例的断言上（`:148`/`:207`）。伪代码（`:313-314`）`data = raw.get('data'); return {'stocks': data if isinstance(data, list) else []}`，§6（`:392`）明确「上游 200 但 `data` 非 list / 缺 `data` ⇒ `{'stocks': []}`（**无数据 ≠ 失败**）」。**同族 `/cls/plate` 的 `data` 恰是 dict**（`server.py:424` `raw.get('data', {}).get('stocks', [])`）——若本端点 `data` 实为 dict（或上游改版），handler 会返回 **HTTP 200 + `{'stocks': []}`**：**无 error、无日志、无 5xx**，下游把"空池"当正常结果消费，故障完全静默。POOL-T3（`:422`）与 POOL-T8（`:427`）的 mock 由作者按**文档假设的形状**手写 ⇒ **循环自证**，无法发现契约错误。
　影响：任务书明示「契约错 ⇒ P5a/P5b 白做」；此处是**唯一的单点故障**，且失败模式是"静默空"而非"报错"，正是评审要阻断的"虚假安全感"。
　建议（放行条件）：① P5a 前用一次真实抓包把 **4 个 type 各 1 条响应**固化为 `tests/fixtures/` 夹具，补一条夹具解析测试（断言 `stocks` 非空且元素含 `secu_code`），**取代/补强 POOL-T3 的手写 mock**；② 或（叠加）把 `data` 为 **非空 dict** 的情况记为 `{'error': 'malformed upstream response'}` 并 `log.warning`（fail-loud），而非静默 `[]`——避免契约漂移被吞。

### P2（不阻断，建议同批或紧随修复）

**【P2-01】§6 错误表引用错号**（`cls_pools.md:392`）：行「上游 200 但 `data` 非 list / 缺 `data`」标注依据 **BR-POOL-7**，但该语义属 **BR-POOL-6**（`:252`）；BR-POOL-7 是 `code != 200`。引用错号会让 code-developer 追错规则。建议改为 BR-POOL-6。

**【P2-02】注释/文档漂移清单漏列 `server.py:1230`**：§2.5「非阻断漂移」只登记了 `:478`（"14 JSON branches"→18）与 `:923`（docstring 15→19），**漏登记** `server.py:1230` 注释「remaining **4** JSON branches」→ 8；且 `:923` docstring 的括号 `(5 RSS + 10 JSON/CDP)` 中的 **10** 亦需 → 14。不改不红，但属文档一致性缺口。

**【P2-03】§2.2 签名类比失真**（`cls_pools.md:104`）：称 `handle_cls_pool` "与 `handle_cls_hotplate(feed_url=None)` 同类（无 `feed_url` 形参）"。但 `handle_cls_hotplate` **确带** `feed_url=None`（`server.py:337`）；真正同形（位置参数平铺、无 `feed_url`）的先例是 `handle_cls_plate(code)`（`server.py:383`）。建议改引 `handle_cls_plate`，以免下游照抄错模板。

**【P2-04】R2 行号不精确**（`cls_pools.md:171`）：写 `server.py:40-45` import 块，实际 `from .config import (...)` 为 `server.py:40-50`。非阻断，建议校正。

**【P2-05】POOL-T4 的"无裸字面量"断言不可执行**（`cls_pools.md:423`）：断言「`server.py` 本增量**无** `ttl=12`/`ttl=120` 裸字面量」——未给判定机制（扫描源码？哪几行？`12`/`120` 在 `config._trading_tiers` 里本就存在）。若照抄进 unittest 会变成**伪断言/易漏**。建议：或改为**行为断言**（捕获 `ttl` 等于 `cache_policy('plate')['ttl']`，POOL-T3/T4 已覆盖，可删该句），或明确"对本增量新增代码区间做源码正则"的落点。

**【P2-06】§2.1 OpenAPI 不可机读**（`cls_pools.md:69-79`）：4 端点仅用内联 `description` 描述，**无 request/response schema / 无 `components`**，无法直接被下游生成契约或校验。§3 已给数据结构，建议 OpenAPI 块内 `$ref` 指向 §3 的成功/降级体，或至少注明"结构权威见 §3"。

**【P2-07】缺 `_guard` 兜底路径用例**（`cls_pools.md:394`）：§6 列了"handler 意外抛异常 ⇒ `_guard` 兜底"，但 POOL-T1..T14 无对应用例（POOL-T11 测的是 `fetch_json` 抛，非 handler 抛）。因 `handle_cls_pool` 是总函数该路径实际不可达，属**覆盖nice-to-have**：可补一条 `patch.dict(_POOL_HANDLERS, {p: boom})` 走 HTTP 断言 200 + error 且 `http_503_total` 不变（复用 `test_guard_captured_error_body_is_200` `:662` 模式）。

## 三、设计核对详情

### 1. 注册点 R1–R13 逐条实核（**全部命中 ✅**）

| # | 文档标注 | 实核结果 | 判定 |
|---|---------|---------|------|
| R1 | `config.py:219` 附近 | `:219` 确为 `_HOTPLATE_BASE_URL`（`:220` `_HOTPLATE_HEADERS`） | ✅ |
| R2 | `server.py:40-45` | 实际 import 块 `:40-50`（行号略偏，见 P2-04） | ✅ |
| R3 | `server.py:482` `_JSON_SHAPES` 14→18 | `:482-489` 实为 **14** 条，+4 = 18 | ✅ |
| R4 | `server.py:490` assert ==14→18 | `:490` `assert len(_JSON_SHAPES) == 14` 命中 | ✅ |
| R5 | `server.py:505` 附近新增 `_POOL_HANDLERS` | `:505` `_PANEL_HANDLERS`（表驱动先例）命中 | ✅ |
| R6 | `server.py:514` `_JSON_DISPATCHED_PATHS` | `:514-517` 定义、`:518` 断言命中 | ✅ |
| R7 | `server.py:522` `_CACHE_AGE_DOMAINS` | `:522-534` 命中；`/cls/hotplate`/`/cls/plate`→`plate`（`:529`）同族正确 | ✅ |
| R8 | `server.py:1230` 分发区 | `:1230` 注释「remaining 4 JSON branches」+ `:1231-1261` 分支命中 | ✅ |
| R9 | `server.py:932` `feeds.extend` | `:932-953` 实为 **10** 条（ROUTES 5 + 10 = 15）；+4 = 19 | ✅ |
| R10 | `server.py:923` docstring 15→19 | `:923` 「15 healthz feed entries」命中 | ✅ |
| R11 | `tests/test_server_http.py:47` 14→18 | `:47` `assertEqual(len(srv._JSON_SHAPES), 14)` 命中 | ✅ |
| R12 | `tests/test_server_http.py:510` 15→19 | `:510` `assertEqual(len(payload['feeds']), 15)` 命中 | ✅ |
| R13 | `tests/test_server_http.py:521` 15→19 | `:521` `assertEqual(len(entries), 15)` 命中 | ✅ |

> **补核（任务书外，确认无遗漏）**：全仓再扫，计数型断言**仅** `:47`/`:510`/`:521` 三处；`assert set(_STOCK_BATCH_HANDLERS) == {p for p,s in _JSON_SHAPES.items() if s=='batch'}`（`server.py:500`）不受 +4 object 影响；`CacheAgeTests.test_registered_paths_follow_policy`（`:395-399`）逐项遍历、`test_server.py` 的 healthz 断言全为 `assertIn`（`:171`/`:249`）⇒ **新增 4 路径/4 feeds 均不破**。**R1–R13 完备性成立**，无漏注册点。

### 2. 风格一致性核对（✅ 总体一致）

- **`handle_cls_pool(pool_type)` 形态**：与 `handle_cls_plate(code)`（`server.py:383`）同为"位置参数平铺 + 内部拼签名 URL + 走 `fetch_json` + 返回 dict"；URL 拼装 `f'{_URL}?{urlencode(params)}'`、`params['sign']=cls_sign_params(params)` 与 hotplate/plate **逐字同构**（`:355-356`、`:402-403`）。✅
- **表驱动**：`_POOL_HANDLERS`（路径→type）与 `_PANEL_HANDLERS`/`_STOCK_BATCH_HANDLERS` 同为模块级集中 dict，路由只从表取值、不写死字面量（BR-POOL-1）——符合项目"集中式 dict 路由"约定。✅（形态差异：panels 表是"路径→handler"，pool 表是"路径→type"，路由再经 `lambda pt=...` 构造；§5 注已说明闭包安全，可接受。）
- **零第三方依赖 / 配置全在 `config.py` / `fetch_json` 聚合 / 业务异常不外抛**：均满足（BR-POOL-4/13）。✅
- **`rever: 1` 的 int 形态**：与 `handle_cls_hotplate` 的 `'rever': 1`（`server.py:353`）一致；`cls_sign_params`（`utils.py:80-87`）对 int 序列化为 `rever=1`、`urlencode` 亦然 ⇒ 签名与 wire 一致。✅
- **`_POOL_TYPES` 运行期解析**：`handle_cls_pool` 在 `~:431` 定义、`_POOL_TYPES` 在 `~:507` 定义——**函数体在调用期解析全局名**，导入期不 `NameError`，位置合法。✅

### 3. 错误语义核对（✅ 与 `_guard`/`_send_json_shape` 吻合）

- 成功 `{'stocks':[...]}` / 失败 `{'error':...}` 与 `object` shape 的 `_guard` 降级体（`server.py:649`）**键集合互斥**、形态一致（N1：恒 200 + error body）。✅
- **400 分支确认不需要**：本端点**无 query 参数**，路由分支直接 `_send_json_shape`，与 `/cls/hotplate`（`server.py:1231`）同构；非法 `pool_type` 只在直接调用 handler 时经枚举闸返回 error、**不触网**（§2.1/§6 一致）。✅ 无 400 正确。
- 上游 `code != 200`（如 9000）⇒ `{'error': msg or 'upstream_error'}`；`data` 非 list ⇒ `{'stocks': []}`（成功语义）。逻辑自洽（唯一风险见 P1-02）。✅

### 4. 测试设计核对（POOL-T1..T14）

- **覆盖**：注册点计数（T1/T2/T13）、handler 打桩（T3–T9）、HTTP 分发 + 全失败降级（T10/T11）、cache-age 域（T12）、分发表值域（T14）——对 5 项评审重点**覆盖齐**。✅
- **mock 全限定名**：`patch.object(srv, 'fetch_json', ...)`（参照 `PlateStaggerTests._capture_ttls` `:110`）——`handle_cls_pool` 解析 `server` 命名空间的 `fetch_json`（`server.py:51` 导入），打桩点正确；**不依赖外部网络**。✅
- **缺口**：① T9 未覆盖非 hashable 入参（P1-01）；② T4 机制不可执行（P2-05）；③ 无 `_guard` 兜底用例（P2-07）；④ 无真实夹具（P1-02）。

### 5. 逆向审查（Step 1.5）

| 视角 | 发现 |
|------|------|
| **反证**（假设不成立会怎样） | 假设"`data` 是裸 list"。若为 dict（同族 `/cls/plate` 即 dict），`isinstance(data, list)` 为假 ⇒ **静默返回 `{'stocks': []}`**（200、无 error）⇒ 假设失效**不报错、只静默空**（P1-02）。假设"`way=last_px` 定案"若错 ⇒ 上游 9000 ⇒ 全池降级为 `{'error':...}`：**有 error 信号但功能全废**（可观测，风险次之）。 |
| **遗漏** | ① 上游契约夹具（P1-02）；② 非 hashable 入参（P1-01）；③ 注释漂移 `:1230`（P2-02）；④ 降级体（`{'error'}`）在 `_send_json_shape` 下 `cache=True` ⇒ 会被 `Cache-Control: public, max-age=12` 标为可缓存（**既有 object 端点同病**，非本增量引入，仅提示）。 |
| **误导**（虚假安全感） | §6「无数据 ≠ 失败」+ `data` 非 list ⇒ `[]` 的写法，让读者以为"防御完备"，实则把**契约错/改版**吞成正常空结果——**失败不可观测**（P1-02）。§2.2「任意输入…绝不抛」给读者总函数已闭合的错觉（P1-01）。 |
| **不可逆** | 纯只读 GET、无持久化、无 DDL、无删除 ⇒ 回滚成本 = 撤 4 条路由 + 4 张表项。**回滚安全 ✅**。 |
| **断链**（需求→实现→验证） | 需求（4 tab）→ 实现（4 端点）→ 验证（T1–T14）链条闭合，但**验证终点止于作者自写 mock**，**无一条对着真实上游** ⇒ 契约层无外部证据（P1-02）。 |

### 6. 可执行性审查（Step 1.6）

- **正向**：伪代码逐行可落（config 常量、import、handler、4 张表、feeds、分发分支齐全）；`_POOL_HANDLERS` 定义位置先于 `:514` 断言，编码者不会踩 `NameError`；下游**无需发明任何接口** ✅。
- **阻断面**：P1-01（一行防御，否则契约与实现不符）与 P1-02（P5a 前须补真实夹具，否则契约错无法在编码前暴露）须先闭环；P2-01（错号）与 P2-05（伪断言）会误导 code-developer/tester 的具体施工。

## 四、漂移检测

| # | 漂移项 | 事实 | 判定 / 建议 |
|---|--------|------|------------|
| D-1 | **无专属 PRD AC** | 需求来自任务书，`doc/prd/perf-stability-optimization.md` 无对应 AC；本文档 §9 映射既有约束 | 文档 §10#1 已如实登记并外抛编排层/system-architect 决定是否回填 SAD/PRD。**建议编排层确认**（新功能增量，非性能专项 AC 范围） |
| D-2 | **`server.md` 路由表未同步** | 4 端点只在 `cls_pools.md` 立契，`server.md` 路由总表未列 | 文档 §10#3 裁定"独立成文"，路由表由 code-developer 按 R3–R9 施工。**可接受**，但建议 P5b 后由编排层在 `server.md` 增一行指针 |
| D-3 | **对外文档（`API.md`/`README.md`）缺 4 端点** | 对外可见面未登记 | 文档 §10#4 已输出 `>>DOC_SYNC: API.md, README.md`，**正确外抛**，非本 agent 权限 |
| D-4 | **注释计数漂移未登记全** | `server.py:1230`「remaining 4 JSON branches」、`:923` docstring 括号内「10」 | 见 P2-02，建议补登记 |

## 五、改进建议（汇总）

1. **P1-01**：枚举闸加 `isinstance(pool_type, str)` 短路（一行）；POOL-T9 扩非 hashable 用例。
2. **P1-02**：P5a 前把 4 个 type 的真实响应各存 1 条为 `tests/fixtures/`，补夹具解析测试；对"`data` 为非空 dict"改为 fail-loud（error + `log.warning`）而非静默 `[]`。
3. **P2**：改 §6 错号（BR-POOL-7→6）；补登记 `:1230`/`:923` 注释漂移；§2.2 类比改引 `handle_cls_plate`；校正 R2 行号；POOL-T4 改行为断言或明确机制；§2.1 OpenAPI 指向 §3；可选补 `_guard` 兜底用例。
4. **强度认可（无需改）**：① 正确区分了本端点 `data` 为**裸 list** 与同族 `/cls/plate` 的 `data` 为 **dict**（关键踩坑，未混用）；② 主动核出并补列任务书**漏列**的 R12/R13（否则 feeds 计数断言必红）；③ 明确"无 query ⇒ 无 400 分支"与 N1（恒 200）语义，与 `_send_json_shape` 机制吻合；④ 只增不删、端锁定、依赖无环、零新依赖。

## 六、结论

本详设**结构完整、注册点零遗漏、风格与既有 `handle_cls_plate`/hotplate 同族一致**，对 5 项评审重点均有正面回应；**无 P0**。两处 P1 均为**低成本可闭环**项：P1-01 是一行类型防御，P1-02 是补一条真实夹具测试（防"契约错 ⇒ 下游白做"的静默风险）。闭环 P1-01/P1-02 后**可放行进入 P5a**。

**结论：⚠️ 有条件通过（APPROVE-WITH-CONDITIONS）**

> 放行前置条件（must-fix，按序）：
> 1. **P1-01** — 枚举闸补 `isinstance(pool_type, str)` 防御 + 扩展 POOL-T9。
> 2. **P1-02** — P5a 前提交 4 条真实上游夹具 + 夹具解析测试（或对 dict 型 `data` fail-loud）。
>
> P2 可与 P5a 并行修，不阻断。

>>DECISION: APPROVE-WITH-CONDITIONS

