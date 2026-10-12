# 对抗性盲审报告 — 财联社 4 池独立接口（P8）

| 项 | 值 |
|---|---|
| CR 编号 | CR-20261010-P8-BLIND-001 |
| 版本 / 状态 | v1.0 / 已完成 |
| 评审模式 | P8 对抗性盲审（零上下文，`>>MODE: blind`）· 强度 🟢 |
| 日期 | 2026-10-10 |
| 输入 | 需求原文（编排器内联提供）+ `>>DIFF` 客观摘要 + 变更文件 3 个 |

## 〇、盲审纪律声明（零上下文核对）

- **需求原文**：编排器**内联**提供（未给文件路径），作为唯一需求输入。
- **变更文件（3）**：`china_finance_rss/config.py`、`china_finance_rss/server.py`、`tests/test_server_http.py`。
- **禁读范围** `doc/detailed/**`、`doc/review/**`、`doc/tester/**`、`API.md`、`README.md`：**一个都没有打开**。
- **污染披露（诚实记录）**：为定位变更符号执行过一次全仓 `grep`，其返回片段中混入了 `doc/detailed/server.md`、`doc/detailed/cls_pools.md`、`doc/detailed/_PROGRESS.md`、`API.md`、`README.md` 的行内容。发现后未打开上述任何文件，也未将其中信息（注册点编号、BR 依据、文档同步状态、需求覆盖率）用作本报告任何判定；全部结论仅来自 3 个变更文件 + 参照系代码 + 内联需求原文。若编排器要求严格双盲，请以限目录 grep 重发入参复跑。
- **既往评审文件**：`doc/review/` 下多个报告（含既有 `对抗性盲审报告.md`、`cls_pools_代码评审.md`）仅经 glob 得到**文件名**，未读内容。为避免为写报告而被迫 Read 禁读文件，本次新建 `cls_pools_对抗性盲审报告.md`（文件名含"对抗性盲审"，`check-review.sh --name 对抗性盲审` 按 mtime 可命中）。
- 变更文件自身的 BR-POOL-* / POOL-T* 注释与测试 docstring 属"读变更文件"的正常范围，未据此回溯任何文档。

## 一、评审概要

| 项 | 结论 |
|---|---|
| 评审结论 | ✅ 通过（0 P0 / 0 P1 / 5 P2；2 项非代码条件见 `>>DECISION`） |
| P0 / P1 / P2 | 0 / 0 / 5 |
| 阻断项 | 无 |
| 是否允许进入测试 | 允许 |
| 盲审入参范围 | 需求原文（内联）+ 变更文件 3 个 |

**总评**：实现是对的——4 端点全部走表驱动、TTL 单一取自 `cache_policy('plate')`、total function 降级语义完整、8 处注册点逐一落位且计数断言自洽，既有端点路由未被触碰，**无 P0 / 无 P1**。最该先看的 3 件：① 14 个池用例**全部 mock 掉 `fetch_json`，上游真实契约（`type` 枚举 / `way` / `data` 形状）零实测**（P2-1，本次最大残余风险）；② fetch/解码失败路径**无服务端日志**，与形状漂移路径不对称（P2-2）；③ "无裸 TTL 字面量"的静态守卫正则可被 `ttl=300` 绕过（P2-4）。

## 二、评审范围与验证手段

**读过的（允许范围）**：3 个变更文件；参照系 `server._guard` / `_cache_age` / `_serve_index` / `_base_feed_entries` / `build_health_payload` / `_run_health_checks` / `_send_text`、`cache.fetch_json`、`utils.cls_sign_params`、`tests/test_server.py`（既有 feeds 断言）、`.opencode/scripts/check-review.sh`、本 skill 的 checklist 与模板。**未读**：禁读清单内任何文件。

**验证手段执行情况（如实标注）**：⚠️ 本会话**无 shell/执行类工具**，`python -m py_compile china_finance_rss/*.py tests/*.py` 与 `python -m unittest discover -s tests -v` **未由评审者执行**（任务原文为"若执行请直接用"，属可选）。替代手段：

1. **导入期断言手工点数复核**：`_JSON_SHAPES` = 4 panels + 6 batch + hotplate + plate + longhu + margin + 4 池 = **18** ✓（`assert len == 18` 成立）；`_JSON_DISPATCHED_PATHS` = 4+6+4+4 = **18** 且与 `_JSON_SHAPES` 同集 ✓；`_STOCK_BATCH_HANDLERS` 6 = shapes 中 batch 6 ✓；`_base_feed_entries` = 5 ROUTES + 扩展列表 **14** 条 = **19** ✓。
2. **计数注释一致性**：`18 JSON branches` / `19 healthz feed entries (5 RSS + 14 JSON/CDP)` / `4 panels` / `6 batch` / `remaining 8` / `5 RSS` 全部自洽（4+6+8=18，5+14=19）✓。
3. **全仓 grep 确认无残留旧计数**：测试目录无 `== 14` / `== 15` 类断言；`tests/test_server.py` 对 feeds 仅用 `assertIn` ✓。
4. **逐条走查 14 个新用例**的断言逻辑、mock 边界与预期值（见 §五）。

> 两条命令需由编排器在有 shell 的门禁中补跑 —— 见 `>>DECISION` 条件 C1。

## 三、SIDE-EFFECT 逆向核对（入参无 `>>SIDE-EFFECT:` → 评审者按 diff 推断）

供编排器映射进 tester 的 `>>SCOPE:` 定向回归（模块列）；同时用于核对编排器是否漏报标记。

| # | 受影响点 | 模块 | 逆向假设（可能被破坏的既有调用方） | 核对结论 |
|---|---|---|---|---|
| S1 | `_JSON_SHAPES` 14→18 | server·路由表 | 某处仍断言 `len(...) == 14` → 导入即炸 | 不成立：全仓无 14/15 残留；server 内计数注释已同步 18 |
| S2 | `_JSON_DISPATCHED_PATHS` 并集 +4 | server·路由表 | 新增路径缺 shape → 断言破裂 | 不成立：手工点数 18 = 18，断言覆盖 |
| S3 | `_CACHE_AGE_DOMAINS` +4 | server·HTTP 缓存 | 池路径漏注册 → 落 `_DEFAULT_AGE_DOMAIN`('f10', 300s)，实时池被打上错误 `max-age` | 不成立：4 条均 `'plate'`，`CacheAgeTests` 遍历断言 + `:272` 精确断言双覆盖 |
| S4 | 分发新增 pool 分支（hotplate 前） | server·`_handle_request` | 插入分支遮蔽 `/cls/hotplate`、`/cls/plate`、batch、longhu、margin、RSS | 不成立：dict 精确匹配，4 新路径与既有路径无交集；逐条核对分支顺序，既有分支一个没动 |
| S5 | `_base_feed_entries` 15→19 | server·`/healthz` | `?check=1` 多打 4 次上游 / JSON 项状态被改写 | 不成立：`_run_health_checks` 只遍历 `ROUTES`（5 RSS）；JSON 项 `results.get()` 为 `None` → `continue`，保持 `configured` |
| S6 | `_serve_index` json_apis +4 | server·首页 | 首页行数断言破裂 | 不成立：无行数断言，仅路径包含断言 |
| S7 | `main()` 启动日志 +4 | server·启动 | 依赖启动日志行数的脚本 | 不成立：grep 确认测试未断言启动日志 |
| S8 | config 新增 2 常量 | config·配置层 | 破坏 layerIsolation（config 不得 import 包内模块） | 不成立：无新增 import，仍仅 stdlib |
| S9 | 测试计数 14→18 / 15→19 | tests·HTTP 层 | 其他测试文件仍断言旧计数 | 不成立：`test_server.py` 仅 `assertIn` |

**9 个逆向假设全部不成立 → 无回归类 P0/P1。**

## 四、问题清单

| ID | 等级 | 位置 | 问题 | 修复方向 | 阻断 |
|---|---|---|---|---|---|
| B-01 | P2 | `tests/test_server_http.py:241-397, 837-875` | 14 个池用例全部 mock `fetch_json`，上游真实契约（`type` 枚举 / `way` / `data` 形状）零实测 | 发布前 4 端点各 1 次真实冒烟，或补 1 个默认 skip 的 integration 用例 | 否 |
| B-02 | P2 | `server.py:460-461` | fetch/解码失败路径无日志，与形状漂移的 `log.warning` 不对称 | `except` 内先 `log.warning('[server] cls pool %s fetch failed: %s', pool_type, exc)` 再返回 | 否 |
| B-03 | P2 | `server.py:467-468` | `{'error': raw.get('msg') or ...}` 未归一 `str`，`msg` 非字符串时 error 值类型漂移 | `str(raw.get('msg') or 'upstream_error')` | 否 |
| B-04 | P2 | `tests/test_server_http.py:298-301` | TTL 静态守卫正则 `ttl=\s*12\d*` 拦不住 `ttl=30/60/300`，假阴性 | 改为 `re.search(r'ttl=\s*\d+', source)` 并保留 `cache_policy('plate')` 断言 | 否 |
| B-05 | P2 | `config.py:387` | `DOMAIN_MATRIX['plate']` 行注释未纳入 4 个新消费方（单一权威的说明过期） | 注释补 `, 4 cls pools` | 否 |

## 五、问题详情

### D0 契约一致性

盲审入参不含契约文档（`doc/detailed/**` 按纪律禁读）→ **Dim 0 按"无契约可核"跳过，不记偏差**（盲审读不到契约属正常，不因"读不到契约"报偏差）。

**以需求原文为基准的实现覆盖率**（需求原文是本次唯一输入）：4 端点路径 ✓ / 成功体 `{"stocks":[...]}` ✓（`server.py:475`）/ 失败体 `{"error":...}` 恒 200 ✓（`_send_json_shape` → `_send_json(200)`）/ 零第三方依赖 ✓（仅 stdlib + `fetch_json`）/ `handle_*` 纯函数 ✓ / 路由表驱动 ✓ / `fetch_json` + `cls_sign_params` 签名 ✓ / TTL 走 `cache_policy` ✓ / N1 语义 ✓（`_send_json_shape` docstring + 用例 `:848-875` 断言 503 计数不增）。

**无法核验项（如实标注，均非偏差）**：
- **U1** 上游 `type` 枚举 / `way` / `data` 数组形状未实测（无执行工具 + 测试全 mock）→ 承接 B-01。
- **U2** `raw['code']` 是否恒为 int `200`：若上游给字符串 `'200'` 会被判为 error。该假设与既有 `handle_cls_plate:419` 同型（存量风格），无法实测，**不记偏差**。
- **U3** `py_compile` / `unittest` 未执行（见 §二）。
- **U4** `API.md` / `README.md` 同步性不在判定范围（禁读 + 编排层另批）。

### D1 数据与正确性

- **命中「宽泛异常捕获（可观测性缺口）」→ B-02**。当上游返回 200 + HTML 错误页 → `json.loads` 抛出 → `except Exception` 直接 `return {'error': str(exc)}`（`server.py:460-461`）→ 客户端拿到 error 体，**服务端日志零痕迹**（cache 层只记录网络/传输错误，不记录解码失败）；同函数 ④ 的形状漂移有 `log.warning`（`:472`），而 `_guard` 的 `log.exception`（`:694`）对本函数**不可达**（本函数全捕获、不抛）。后果：上游格式漂移只能靠客户端反馈发现。
- **命中「隐式假设 / 类型漂移」→ B-03**。当上游回 `{'code': 9000, 'msg': 123}` → body `{"error": 123}`，与本函数其余 error 值恒为 str（`f'...'`、`str(exc)`、`'upstream data shape unexpected: ...'`）不一致 → 消费方做字符串操作会 TypeError。与 `handle_cls_plate:422` 同型的存量风格，顺手改不扩散。
- **魔法数字**：`way='last_px'` / `rever=1` / `app,os,sv` 有注释与用例双向锁定（`:447-451`、用例 `:287-289` 断言 `way=last_px` 且 `change_px` 不出现），有 "measured" 依据 → 不记。
- **评审重点 1 — handle_cls_pool 正确性逐条**：
  - str 守卫 ✓ `isinstance(pool_type, str)` **先于** frozenset 成员测试（`server.py:445`），不可哈希输入（list/dict/set）不会 TypeError；用例 `:364-372` 覆盖 6 个非法输入（含 2 个不可哈希）且断言 `fetch.assert_not_called()`。
  - 枚举 ✓ `_POOL_TYPES = frozenset(_POOL_HANDLERS.values())` 单一权威（`:566`），路由只从表取值、handler 再校验一次（双闸）。
  - fail-loud ✓ `data` 非 list → `log.warning` + `{'error': 'upstream data shape unexpected: <type>'}`（`:470-474`）；`data: []` 是合法空池、不带 error（用例 `:352`）；`data` 缺失/None → `NoneType` 走同路径（用例 `:353-362`）。
  - **无裸 TTL 字面量 ✓** 唯一 TTL 源 `cache_policy('plate')['ttl']`（`:459`），无第二处 ttl。

### D2 并发

`handle_cls_pool` 无共享可变状态；`_POOL_HANDLERS` / `_POOL_TYPES` 只读表；分发用 `lambda pt=pool_type: ...` 默认参防晚绑定（`:1302`，该写法同时使 `patch.object(srv, 'handle_cls_pool')` 的用例 `:866-875` 能生效）；同 URL 并发冷启动由 `fetch_json` 的单飞 leader election 防击穿（`cache.py:822-837`）。**无命中**。

### D3 资源与性能

单请求单次 fetch（无 N+1）；TTL 命中零网络；4 端点 = 4 个独立 URL key，`plate` 域 `cache_max='n/a'` 由全局 LRU 上限兜底（不无界增长）；`Cache-Control max-age` 与 fetch TTL 同源于 plate 域；`?check=1` 不因 feeds 15→19 增加上游探测（S5 已核）。**无命中**。

### D4 安全

池 `type` 取自服务端表、**永不来自用户输入**（`:1300`）→ 无注入/越权面；URL 经 `urlencode` 构造；**无新增 urlopen**（HTTP 出口仍只有 `cache.fetch_json`，grep 确认 `server.py` 无 `urlopen`/`Request(`）；响应 `application/json`，内容不含 host 依赖（`varies_on_host=False` + `public` 正确，池数据非 host 相关）；无凭据进响应体（`cls_sign_params` 为公开前端算法的纯参数哈希，无密钥）。**无命中**。

### D5 结构与可维护性

单函数覆盖 4 端点（无复制粘贴）；`_POOL_HANDLERS` 镜像 `_PANEL_HANDLERS` 表驱动模式，与项目存量风格一致；配置集中（URL/headers 在 `config.py`，server 只 import）；命名/分层/异常处理与 `handle_cls_hotplate` 同型。**命中「注释说"是什么"但已过期」→ B-05**：`config.py:387` `# cls/hotplate, cls/plate (URL cache)` 未含 4 池，而 plate 域的 TTL 同时是这 4 个端点的 `max-age` 与 fetch TTL → 调参者按该行注释评估 plate TTL 影响面会漏掉 4 个新端点（单一权威的"权威说明"漂移）。

### ❓ 对抗性六问（B2）

- **恶意输入**：池路径不接受任何业务参数 → 无越权/注入/未校验面；枚举门使非法 `pool_type` 永不触网 ✓。形近路径 `/cls/up_open` → 404（用例 `:861-864`）；`/CLS/up_pool`、`/cls/up_pool/` → 404（与既有端点一致的大小写/尾斜杠敏感）；`/cls/up_pool?x=1` → `urlparse().path` 正常分发、query 被忽略 ✓。
- **依赖失效**：FetchError / 非 JSON / 非 dict 信封 / `code != 200` / `data` 非 list / handler 抛异常 → **6 条路全部 `{"error"}` + 200**，负缓存防打爆上游 ✓，`_guard` 兜底在位 ✓。**唯一残口 = 失败无服务端日志（B-02）**。
- **竞态**：见 D2，无。
- **边界值**：空列表 ✓、`data` 缺失/None ✓、`msg` 空 ✓、不可哈希 pool_type ✓；**`msg` 非字符串 ✗（B-03）**。
- **隐式假设**：上游 `code` 为 int（U2，存量同型）；`data` 为 list（已 fail-loud 覆盖）；**`type` 枚举被上游认账（U1 / B-01，零实测）**。
- **测试盲区**：B-01；另记两处覆盖缺口备注（不单列编号）：① `test_head_writes_no_body` 未覆盖池路径 HEAD（`_send_text(write_body=False)` 已被 `/` 覆盖，风险低）；② `tests/stress_test.py` / `loadtest.py` / `stress_all.py` 端点清单未纳入 4 池（非门禁，现成压测工具暂无法回归新端点性能）。

### 注册点完备性核对表（评审重点 2）

| 注册点 | 位置 | 结论 |
|---|---|---|
| `_JSON_SHAPES` ×4 = object | `server.py:533-534` | ✓ |
| `_POOL_HANDLERS` + `_POOL_TYPES` | `:560-566` | ✓ |
| `_JSON_DISPATCHED_PATHS` 并集 | `:574` | ✓ |
| `_CACHE_AGE_DOMAINS` ×4 = plate | `:587-588` | ✓ |
| 分发分支（hotplate 之前） | `:1299-1304` | ✓ |
| `feeds[]` +4（`configured`） | `:1012-1020` | ✓ |
| 首页 `json_apis` +4 | `:1605-1609` | ✓ |
| `main()` 启动日志 +4 | `:1826-1829` | ✓ |
| config URL / headers + server 导入 | `config.py:227-232`、`server.py:48` | ✓ |
| 计数断言 14→18 | `server.py:537` / `tests:48` | ✓ 同步无裂缝 |
| 计数断言 15→19 | `server.py:982` 注释 / `tests:669,680` | ✓ 同步无裂缝 |

注：`_JSON_DISPATCHED_PATHS` 断言只比对**表**、不比对**代码**，"表在分支被删"的风险由 HTTP 用例 `:837-846` 真实分发兜底（分支若缺失 → 404 → 断言失败）✓。

### 测试可证伪性核对（评审重点 5）

成功 ✓ / 降级 5 型 ✓ / 非 list 形状 ✓ / 类型守卫 ✓ / 注册点（表 + cache-age + healthz feeds + 首页）✓ / 404 边界 ✓ / N1 不动 503 计数 ✓ / **签名稳定性 ✓**（`:303-318` 断言两次调用 URL **完全相同**——这是 URL 缓存能命中的前提；已核 `utils.cls_sign_params` 为纯参数哈希、无时间戳/随机量）。**外部网络依赖：无**（全部 patch `fetch_json`；HTTP 用例走本地 `BoundedThreadPoolServer(('127.0.0.1', 0))`）。缺口：TTL 守卫正则弱（B-04）、上游契约零实测（B-01）。

## 六、评审结论

| 项 | 结论 |
|---|---|
| 评审结论 | ✅ 通过 |
| 依据 | 无 P0、无 P1；P2 × 5 全部记录不阻断，符合"无 P0 且 P1 ≤ 2"判据 |
| 是否允许进入测试 | 允许（建议同时满足 `>>DECISION` 条件 C1 / C2） |

**`>>DECISION: APPROVE-WITH-CONDITIONS`**

- **C1（流程）**：编排器在有 shell 的门禁补跑 `python -m py_compile china_finance_rss/*.py tests/*.py` 与 `python -m unittest discover -s tests -v`（本会话无执行工具，评审者无法运行，替代核验见 §二）。
- **C2（发布前）**：对 4 个池端点各做 1 次**上游真实冒烟**（或补 1 个默认 skip 的 integration 用例），闭合 B-01 / U1——全部测试 mock 掉了 `fetch_json`，上游 `type` / `way` / `data` 契约漂移不会被任何现有门禁捕获。
- 两项均为**流程条件，非代码缺陷，无需回退修复轮**；若编排器门禁本就包含编译 + 测试 + 冒烟，条件自动满足，可按 `APPROVE` 处理。
- P2 × 5（B-01…B-05）记入【P8 未阻塞问题】。

**check-review.sh 结论行**（`## X、评审结论` 格式 + 表格式结论）：

```
## 六、评审结论
| 评审结论 | ✅ 通过 |
```

**变更记录**

| 版本 | 日期 | 说明 |
|---|---|---|
| v1.0 | 2026-10-10 | P8 对抗性盲审首版（零上下文，3 个变更文件） |
