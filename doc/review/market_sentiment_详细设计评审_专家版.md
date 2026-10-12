# market_sentiment 独立接口（P3b 详设增量）详细设计评审报告（专家版）

> **文档编号** REV-DES-20261010-002 · **日期** 2026-10-10 · **产出** review-expert
> **评审对象**：`doc/detailed/market_sentiment_独立接口.md` **v1.0.0**（🟡 草稿 · P3a 详设增量）+ `doc/detailed/server.md` **v1.18**（同主题增量登记）
> **评审模式**：详细设计评审（增量） · **项目阶段**：**生产版**（2C2G 在线服务）
> **需求基线**：任务书原文「market_sentiment 拆独立接口 + 一并修复 P8 盲审 5 条 P2（B-01..B-05）」；上游 SAD/PRD 无专属 AC（详设 §10#3 已登记）
> **就绪检查（check-common）**：✅ 文档存在、头部版本/状态/日期/作者齐备；426 行（>500 字阈值）；无 `{例:`/TODO/待补充占位；§2/§4/§5/§8 均为实值（OpenAPI + R1–R10 + RG1–RG7 + 伪代码 + MS-T1..T16 齐备）⇒ 进入正式评审。checklist 懒加载：`check-detailed`。
> **独立性声明**：仅读被评文件 + 其引用的 `server.py` / `config.py` / `cache.py` / `cdp_engine.py` / `tests/test_server_http.py` / `tests/stress_all.py` / `API.md` / `README.md` / `doc/detailed/{server,cdp_engine,SAD}.md` 定位；不依赖 task-decomposer 的创作上下文。

## 一、评审概要

| 项 | 值 |
|----|----|
| 评审结论 | ⚠️ **有条件通过**（P0×0 / P1×1 / P2×5；闭环 P1-01 后放行进入编码） |
| P0 | **0**（无崩溃 / 数据丢失 / 资金 / 安全类） |
| P1 | **1**：§2.3 剥离语义表 + MS-T9(a) 断言方向错误（`_fill_missing` extra 分支语义误解，击中本设计核心陷阱 R2） |
| P2 | **5**：stress_all.py 漂移漏登 / server.md v1.18 漏 10 处现行计数 / cdp_engine.md 未入 DOC_SYNC / SAD 登记不完整 / MS-T15 表述不完整 |
| **注册点 RG1–RG7** | ✅ **逐条实核全部命中**（行号精确，见 §三.1）；测试计数 :48/:669/:680 三处实核存在 |
| **R18/R3 降级同型** | ✅ 与 `handle_finance_timeline`（`server.py:321`）逐行同型，三降级路径 + N1 恒 200 口径一致 |
| **`_CACHE_AGE_DOMAINS` 域裁决** | ✅ `'quote'` 合理（与 4 面板同族；`KEY_TTL_OVERRIDES=60` 为页面刷新节奏，与 HTTP max-age 无关的论证成立；无更优选择） |
| **B-01 skip 风格** | ✅ 合理（env 门控 + 默认跳过 + 不写死外网 URL 断言，与项目测试纪律一致） |
| 是否允许进入编码 | ⚠️ 须先闭环 **P1-01**（§2.3 表格 + MS-T9(a) 一行级修正）；P2 可并行 |
| 端锁定（🟠 STABLE） | ✅ 只增 1 端点 + 从既有端点去 1 键（昨日新增、未冻结，属回退）；`>>DOC_SYNC` 外抛 API.md/README.md 正确 |
| 范围纪律 | ✅ 未改代码 / 未新增第三方依赖 / 未新增 metrics / CDP 层零改动声明属实（API_KEY_MAP / INTERCEPTOR_JS / KEY_TTL_OVERRIDES 实核就绪） |

## 二、问题清单

### P1（生产版阻断，须闭环后放行）

**【P1-01】§2.3 剥离语义表 + MS-T9(a) 断言方向错误：`_fill_missing` extra 分支语义误解**（证据锚点：`market_sentiment_独立接口.md:101-109`（§2.3 表格 + 注）、`:348`（MS-T9）；对照 `cache.py:1155-1161` 实核）

　**问题**：§2.3 表格第一行称「只删 expected / 只 pop（**二者可观测结果相同**）⇒ `result['market_sentiment']` = **`None`**」，表下注称「只删 expected 与只 pop 的**可观测结果相同**（都得到 `None`）」；MS-T9(a) 称「仅删 expected 不 pop（直接调 `_fill_missing({}, data, expected_without_key)`）⇒ 键**不在**」。

　**事实**（`cache.py:1155-1161` 逐行实核）：
```python
def _fill_missing(result, data, expected_keys):
    for key in expected_keys:
        result[key] = data.get(key)          # ① expected 键缺失 ⇒ 补 None
    for k, v in data.items():
        if k not in expected_keys:
            result[k] = v                    # ② 非 expected 键 ⇒ 以 extra 键填回
```
- **只删 expected 不 pop**：`data` 仍含 `market_sentiment`、expected 不含 ⇒ 走 ② extra 分支 ⇒ **键在，值 = 原值**（不是 None，更不是"键不在"）；
- **只 pop 不删 expected**：`data` 不含、expected 含 ⇒ 走 ① ⇒ **键在，值 = None**；
- 两动作齐做：键既不在 data 也不在 expected ⇒ **键不在**（此结论正确）。

　即：两种单动作失败**键均在**（均未真剥离——表格结论"❌ 键仍在"正确），但**可观测值不同**（原值 vs None）。表格"可观测结果相同（都得到 None）"与 MS-T9(a)"键不在"**均与实际语义相反**。

　**影响**：① MS-T9(a) 照抄施工 ⇒ 对**正确行为伪红**（开发者将怀疑自己的正确实现，或更糟——"修"正确的 `_fill_missing` / handler 去迎合错误断言）；② §2.3 语义表错误会误导后续维护者；③ 文档**内部自相矛盾**——§1.1 职责 3（`:17`）的表述「只做一个 ⇒ 仍会出现该键（**null 或原值**）」是**正确**的，与 §2.3 表格冲突，读者无从判断哪个是权威。

　**修复方向**（一行级，must-fix）：
- §2.3 表格第一行拆正：

  | 组合 | 结果 | 正确？ |
  |------|------|-------|
  | 只删 expected（不 pop） | 键经 **extra 分支填回** ⇒ 值 = **原值** | ❌ 键仍在 |
  | 只 pop（不删 expected） | 键仍为 expected ⇒ 值 = **`None`** | ❌ 键仍在 |
  | 两动作齐做 | 键既不在 data、也不在 expected ⇒ 不出现在 result | ✅ 真剥离 |
  | 两动作都不做 | 键在 data、是 expected ⇒ 原值透传（= 现状） | ❌ 未剥离 |

  注改为：「只删 expected 与只 pop 的**键均在**（均未真剥离），但**可观测值不同**（原值 vs None）——MS-T9 (a)/(b) 分别锁定」。
- MS-T9(a) 改为：仅删 expected 不 pop ⇒ `assertIn('market_sentiment', result)` ∧ `assertEqual(result['market_sentiment'], 原值)`（**键在**）；(b)(c) 不变。

### P2（不阻断，建议同批或紧随修复）

**【P2-01】`tests/stress_all.py:117` 漂移未登记**：该脚本对 `/finance/market` 响应检查含 `market_sentiment` 键（`:116-119`）。剥离后该检查必报 `missing key`。该脚本不在 unittest discovery（文件名不匹配 `test*.py`）⇒ **不红**，但属真实漂移。详设 §2.5「非阻断漂移」只登记了 `server.py:523`/`:982`，漏登此处。建议 §2.5 补登：`stress_all.py:117` 同批从键列表中移除 `market_sentiment`。

**【P2-02】`server.md` v1.18 增量登记漏 10 处现行「面板 4 / 18 JSON」表述**：v1.18 自检清单（`server.md:2161`）列了 §1.1/§2.1/§2.2/§2.8/§2.9/§2.9.1/§3.3/§5.8/§8/§9/§10#46/§11，但以下**现行口径**表述仍是旧值（实核）：

| # | 位置 | 现状 → 目标 |
|---|------|------------|
| 1 | `server.md:102`（§1.5 接口对齐表） | 「4 面板 handler 防御取数」→ 5 面板 |
| 2 | `server.md:177`（§2.1 状态语义表） | 「业务端点降级（**4 面板** `{'error':…}`…）」→ 5 面板 |
| 3 | `server.md:181`（§2.1 状态语义表） | 「CDP 不可用（**面板 4**）」→ 面板 5 |
| 4 | `server.md:803`（BR-SRV-1 分发顺序） | 「object 分支（**4 面板** + 4 CLS 池…）」→ 5 面板 |
| 5 | `server.md:857`（BR-SRV-27） | 「**4 面板** handler（A 类）只经 `page_data` 取数」→ 5 面板 |
| 6 | `server.md:953`（§5 伪代码注释） | 「── **4 面板**（object）— …」→ 5 面板 |
| 7 | `server.md:1286`（分发代码注释） | 「── **4 panels** (object) — …」→ 5 panels |
| 8 | `server.md:1835`（§6 错误表） | 「业务端点降级体（**4 面板** / hotplate 全失败…）」→ 5 面板 |
| 9 | `server.md:1843`（§6 错误表） | 「CDP 不可用（**面板 4**）」→ 面板 5 |
| 10 | `server.md:1877`（§10 自检清单） | 「**18 个 JSON 分支**」→ 19 个 |

> 注：历史变更块（v1.2/v1.16 等）中的「4 面板」为历史快照，**不改**（正确）；§8 `SRV-T28`/`SRV-T43` 的「4 端点/4 面板」为**测试作用域**表述（新端点由 `SRV-T74` 覆盖），不改可接受。

**【P2-03】`doc/detailed/cdp_engine.md` 未登记 DOC_SYNC**：CDP 层零改动（正确），但 `cdp_engine.md:751`「AC-S4（CDP 降级路径 **A 4** / A′ 1）」、`:752`「AC-S4（**A 类 4 端点**逐条验证）」为现行 AC 追溯计数，+1 端点后应为「A 5 / A′ 1」「A 类 5 端点」。详设 §12 DOC_SYNC 未含 `cdp_engine.md`（SAD 标了「可选」，`cdp_engine.md` 连可选都未标）。建议补：`>>DOC_SYNC: doc/detailed/cdp_engine.md → :751/:752「A 类 4 端点」→ 5（可选，纯计数同步）`。

**【P2-04】SAD.md 的 DOC_SYNC 登记不完整**：详设 §12 对 SAD 只标「§2.4 `_guard` 覆盖清单（14→含新端点）/ §3 server 行 JSON 分支计数」。实核 `SAD.md` 现行计数/清单至少 3 处：`:71-72`（「**14 个 JSON 分支**…14 = 面板 4」）、`:441`（「A（**4 单体/面板**）」端点清单）、`:560`（「`_guard` 覆盖范围 = 全部 **14 个** JSON 分支」）。建议 DOC_SYNC 的 SAD 行补全为「路由计数（`:71-72`）+ A 类清单（`:441`）+ `_guard` 覆盖（`:560`）」。

**【P2-05】MS-T15 断言双向表述不完整**（`:354`）：「新正则 `re.search(r'ttl=\s*\d+', source)` 命中裸字面量」——`source` 若指 `handle_cls_pool` 真实源码，新正则**不命中**（无裸字面量；`ttl=cache_policy('plate')` 中 `=` 后是字母 `c`，正则 `ttl=\s*\d+` **正确放行** policy 调用——这是期望行为，非规避）。现有 `:299` 的 `assertIsNone(re.search(旧正则, source))` 模式应保留并显式化双向：① 真实源码对新正则**必不命中**；② 合成串 `ttl=30`/`ttl=60`/`ttl=300` 对新正则**必命中**、对旧正则 `r'ttl=\s*12\d*'` **必不命中**（证旧守卫假阴性）。负向断言设计本身正确，仅表述需补全，避免开发者误写成对真实源码 `assertIsNotNone` 的伪红。

## 三、设计核对详情

### 1. 注册点 RG1–RG7 逐条实核（**全部命中 ✅**，行号精确）

| # | 文档标注 | 实核结果 | 判定 |
|---|---------|---------|------|
| RG1 | `server.py:527-536` `_JSON_SHAPES` 18→19；assert `:537` | `:527-536` 实为 **18** 条、`:537` `assert len(_JSON_SHAPES) == 18` 命中 | ✅ |
| RG2 | `server.py:552-557` `_PANEL_HANDLERS` 4→5 | `:552-557` 实为 **4** 项（market/timeline/quotation/market-timeline） | ✅ |
| RG3 | `server.py:579-593` `_CACHE_AGE_DOMAINS` → `quote` | `:579-593` 命中；4 面板 → `'quote'`（`:581-582`）同族正确 | ✅ |
| RG4 | `server.py:570-575` `_JSON_DISPATCHED_PATHS` 自动 | `:570-574` = `frozenset(_PANEL_HANDLERS) | …`、`:575` `assert == frozenset(_JSON_SHAPES)` ⇒ 两表同 +1 自动成立，「须确认」标注正确 | ✅ |
| RG5 | `server.py:981-1022` `_base_feed_entries` 19→20；docstring `:982` | `:981-1022` 命中；`:982`「19 healthz feed entries」 | ✅ |
| RG6 | `server.py:1598-1618` 首页 `json_apis` +1 | `:1598-1618` 实为 **19** 项；新项 4 元组形态（path/name/example/`True`=needs CDP）与既有一致 | ✅ |
| RG7 | `server.py:1812-1829` `main()` Utilities 日志 +1 | `:1812-1829` 命中（4 面板 + 各 JSON 端点 `log.info` 风格） | ✅ |
| 计数 | `tests/test_server_http.py:48`（18→19） | `:48` `assertEqual(len(srv._JSON_SHAPES), 18)` 命中 | ✅ |
| 计数 | `tests/test_server_http.py:669`（19→20） | `:669` `assertEqual(len(payload['feeds']), 19)` 命中 | ✅ |
| 计数 | `tests/test_server_http.py:680`（19→20） | `:680` `assertEqual(len(entries), 19)` 命中 | ✅ |

> **补核（任务书外，确认无遗漏）**：全仓再扫，计数型断言**仅** `:48`/`:669`/`:680` 三处（OPML 测试基于 `ROUTES` 5 RSS，不受影响；`_serve_index` 无计数测试；`_PANEL_HANDLERS` 无计数断言）；`assert set(_STOCK_BATCH_HANDLERS) == {…if s=='batch'}`（`:547`）不受 +1 object 影响；`CacheAgeTests`（`:551`）/`HealthPayloadTests`（`:660`）/`HttpSemanticsTests`（`:722`）/`ClsPoolTests`（`:241`）/`ShapeTableTests`（`:45`）/`test_head_writes_no_body`（`:751`）等引用锚点全部实存。**RG1–RG7 + 三处计数完备，无漏注册点。**

### 2. R2 剥离两动作核对（⚠️ 动作规格正确，语义表/测试方向错误，见 P1-01）

- **两动作本身写死**：§2.3 伪代码（`:87-99`）同时给出 ① `handle_finance_market` 内 `data.pop('market_sentiment', None)`（与 `timeline` 剥离同处 `:282`）与 ② `config._FINANCE_EXPECTED_KEYS` 删键（`config.py:204-207` 实核现含该键，6→5）；R2（`:193`）/§1.1 职责 3（`:17`）/§3.4（`:182`）/§5 伪代码（`:229-239`）四处一致。✅
- **「为什么必须两动作同时」的论证方向正确**（`_fill_missing` 双循环语义），但**表格与 MS-T9(a) 的中间结论写错**（P1-01）。
- **MS-T8 是真实回归兜底**：stub `page_data` 含 `market_sentiment` ⇒ `handle_finance_market()` 结果不含该键——只 pop（键=None）/ 只删 expected（键=原值）/ 不做（键=原值）三种回归**均红**。MS-T8 可证伪 ✅；MS-T9 的 (a) 方向错误使「双动作必要性」的精确锁定失效（P1-01）。

### 3. R18/R3 CDP 降级语义核对（✅ 与 `handle_finance_timeline` 逐行同型）

| 路径 | 新 handler（§5 伪代码） | `handle_finance_timeline`（`server.py:321-333` 实核） | 判定 |
|------|----------------------|--------------------------------------------------|------|
| CDP 未就绪 | `{'error': 'Chrome CDP not available. See README.'}` | 同文（`:325`） | ✅ |
| `page_data` → None | `{'error': 'Finance page not initialized.'}` | 同文（`:329`） | ✅ |
| 键缺失 | `{'error': 'market_sentiment unavailable'}` | `{'error': 'timeline unavailable'}`（`:332`，R18 禁止裸 null） | ✅ 同型 |
| 意外异常 | `_guard` 兜底 `{'error': str(exc)}` | 同（object shape，N1 恒 200） | ✅ |

- 三降级路径 + N1（恒 200）+ 成功/降级体键集合互斥（§3.2）均与既有 object 端点一致；`http_503_total` 不受影响（MS-T6 断言正确）。✅
- 总函数契约（绝不抛）成立：handler 无 try 外抛路径（CDP 门 + page_data 总函数 + `data.get`），`_guard` 为兜底。✅

### 4. `_CACHE_AGE_DOMAINS` 域裁决核对（✅ 合理，无更优选择）

- 新端点与 `/finance/market`·`/finance/timeline`·`/quotation/market`·`/market/timeline` 共享 `cls_finance` 页面同一份 `page_data`（§2.4 实核属实），同属实时行情面 ⇒ `quote` 域（盘中 4s / 非盘 120s）同族。
- `KEY_TTL_OVERRIDES['market_sentiment']=60`（`cdp_engine.py:480-481` 实核）是**页面数据刷新**节奏；`quote` 域 TTL 由 L0 档位（上游盘中 3s 一跳的物理下限）驱动，与 60s 页面刷新**无关**——详设「不得据此另立档位」的论证成立。
- 备选裁决：`f10`（300s 兜底，否决正确——实时报价标 300s 与 AC-A3「承诺=行为」冲突）；新域（否决正确——无新语义、须改 `config.md`）。**`'quote'` 为最优解。** ✅

### 5. B-01..B-05 修复规格核对（✅ 均可证伪）

| 项 | 落点实核 | 可证伪性 |
|----|---------|---------|
| B-01 | `tests/` 新增 `ClsPoolIntegrationTests`，`@skipUnless(os.getenv('CLS_INTEGRATION'))`；对 4 池各 1 次真 `handle_cls_pool` ⇒ 无 `error` ∧ `stocks` 为 list | ✅ 默认跳过、不写死外网 URL 断言（走 `config._UP_DOWN_ANALYSIS_URL`）；env 门控与 `stress_all.py` 的 `STRESS_URL` 风格一致；项目 unittest 无 skip 先例，详设已裁决并说明（§10#2） |
| B-02 | `server.py:460-461` except 内补 `log.warning('[server] cls pool %s fetch failed: %s', …)`；MS-T13 `assertLogs('server', level='WARNING')`（`server.py:75` 日志器名实核为 `'server'`） | ✅ 删 `log.warning` ⇒ 断言红 |
| B-03 | `server.py:467-468` `{'error': str(raw.get('msg') or 'upstream_error')}`；MS-T14 `{'code':9000,'msg':123}` ⇒ `{'error':'123'}` ∧ isinstance str | ✅ 不加 `str()` ⇒ 值为 int ⇒ 红 |
| B-04 | `tests/test_server_http.py:294-301` 旧正则 `r'ttl=\s*12\d*'` 实核存在；新正则 `r'ttl=\s*\d+'` 负向断言（合成串双向） | ✅ 设计正确（`ttl=cache_policy` 正确放行、`ttl=120` 正确命中）；表述需补全双向（P2-05） |
| B-05 | `config.py:387` plate 行注释实核为「cls/hotplate, cls/plate (URL cache)」；MS-T16 断言注释含 `4 cls pools` | ✅ 注释未补 ⇒ 红 |

### 6. 逆向审查（Step 1.5）

| 视角 | 发现 |
|------|------|
| **反证**（假设不成立会怎样） | 假设「只做一个动作就够了」：只 pop ⇒ 键以 **None** 出现（下游可能误判为"情绪数据为空"）；只删 expected ⇒ 键以**原值**出现（下游可能误判为"实时数据"）。两种失败对下游的**误导不同**——MS-T9 的存在意义正是区分二者，但 (a) 写反了（P1-01）。假设「`quote` 域裁决错」：落 `f10` ⇒ 实时情绪报价被标 `max-age=300`，与 4 面板口径分裂（裁决正确，已规避）。 |
| **遗漏** | ① `stress_all.py:117` 键检查（P2-01）；② `server.md` 10 处现行计数（P2-02）；③ `cdp_engine.md` / SAD 计数登记（P2-03/04）；④ MS-T15 双向表述（P2-05）。 |
| **误导**（虚假安全感） | §2.3 表格「可观测结果相同（都得到 None）」——**虚假的精确性**：让读者以为两种单动作失败不可区分（实际可区分：原值 vs None），且 MS-T9(a) 给出与真实语义相反的断言方向（P1-01）。 |
| **不可逆** | 纯只读 GET + 文档增量，无持久化 / 无 DDL / 无删除；回滚成本 = 撤 1 端点 + 恢复 1 键。**回滚安全 ✅**。 |
| **断链**（需求→实现→验证） | 需求（拆独立接口 + 5×P2 修复）→ 实现（1 端点 + 剥离两动作 + 7 注册点）→ 验证（MS-T1..T16）链条闭合；**唯一断点 = MS-T9(a) 方向错误**使「双动作必要性」的精确验证失效（MS-T8 兜底，P1-01）。 |

### 7. 可执行性审查（Step 1.6）

- **正向**：伪代码逐行可落（handler + 两动作 diff + config 删键 + 注册表 edits + 5 条 P2 修复规格）；**全部行号实核命中**（30 余处 `文件:行` 引用逐一对照当前工作区，含 `server.py` 15 处 / `config.py` 2 处 / `cache.py` 1 处 / `cdp_engine.py` 3 处 / `tests` 6 处 / `API.md`·`README.md` 5 处）；下游**无需发明任何接口** ✅。
- **阻断面**：P1-01（§2.3 表格 + MS-T9(a)，一行级修正）须先闭环；P2-05（MS-T15 双向表述）须补全，否则 tester 可能写出伪红断言。

## 四、漂移检测

| # | 漂移项 | 事实 | 判定 / 建议 |
|---|--------|------|------------|
| D-1 | **无专属 PRD AC** | 需求来自任务书，`doc/prd/perf-stability-optimization.md` 无对应 AC；详设 §9 映射既有约束（AC-S1/AC-S4/A5/BR-SRV-8/S4 等） | 详设 §10#3 已如实登记并外抛编排层。**建议编排层确认**（新功能增量，非性能专项 AC 范围）——与 `cls_pools.md` §10#1 同型处理 |
| D-2 | **`stress_all.py` 键检查漂移** | `:117` 检查 `/finance/market` 含 `market_sentiment` | 见 P2-01，建议 §2.5 补登 |
| D-3 | **`server.md` v1.18 内部计数漏改** | 10 处现行「面板 4 / 18 JSON」表述（§三.2 P2-02 表） | 见 P2-02，建议编排层在 v1.18 批内补改或升 v1.19 |
| D-4 | **`cdp_engine.md` / `SAD.md` 计数未入 DOC_SYNC** | `cdp_engine.md:751/:752`「A 类 4 端点」；`SAD.md:71-72`/`:441`/`:560` | 见 P2-03/04，建议补全 DOC_SYNC |
| D-5 | **对外文档（`API.md`/`README.md`）** | `API.md:328`/`:332`（market_sentiment 行）实核存在、`:342`（timeline 节）实核存在；`README.md:54-68` 表、`:58`（market 行含 "sentiment"）实核存在 | 详设 §12 已输出 `>>DOC_SYNC`，**正确外抛**，非本 agent 权限 |

## 五、改进建议（汇总）

1. **P1-01（must-fix）**：§2.3 表格第一行拆正（只删 expected ⇒ 原值 / 只 pop ⇒ None，**键均在**）+ 注改正；MS-T9(a) 改为 `assertIn` + `assertEqual(原值)`。
2. **P2-01**：§2.5 非阻断漂移清单补登 `stress_all.py:117`（同批移除 `market_sentiment` 键检查）。
3. **P2-02**：`server.md` v1.18 批内补改 10 处现行计数（§三.2 表），或升 v1.19 收口。
4. **P2-03/04**：DOC_SYNC 补 `cdp_engine.md`（`:751/:752`）+ SAD 行补全（`:71-72`/`:441`/`:560`）。
5. **P2-05**：MS-T15 显式化双向断言（真实源码必不命中 + 合成串必命中/旧正则必不命中）。
6. **强度认可（无需改）**：① 两动作约束在 §1.1/§2.3/R2/§3.4/§5 五处一致写死，MS-T8 提供真实回归兜底；② RG1–RG7 + 三处测试计数**逐条实核全部命中、行号精确**；③ R18/R3 三降级路径与 `handle_finance_timeline` 逐行同型；④ `quote` 域裁决论证严密（页面刷新节奏 vs HTTP max-age 的区分是关键踩坑，已正确规避）；⑤ B-01 skip 风格裁决有理有据；⑥ 端锁定 🟠 定级准确（昨日新增字段回退）、`>>DOC_SYNC` 外抛规范；⑦ 426 行 / 16 用例对 1 端点 + 5 修复规格的比例适当，无过度设计。

## 六、评审结论

本详设**结构完整、注册点零遗漏、降级语义与既有面板同型、B-01..B-05 修复规格均可证伪**，对 8 项评审重点均有正面回应；**无 P0**。唯一 P1 击中本设计核心陷阱（R2 双动作语义），但为**一行级修正**（语义表 + MS-T9(a) 断言方向），且 MS-T8 已提供 handler 级回归兜底——闭环 P1-01 后**可放行进入编码**。

| 项 | 结论 |
|---|---|
| 评审结论 | ⚠️ 有条件通过（P0×0 / P1×1 / P2×5） |
| 依据 | 无 P0 且 P1 ≤ 2；P1-01 为一行级修正，闭环成本极低 |
| 是否允许进入编码 | 允许（须先闭环 P1-01；P2 可并行） |

> 放行前置条件（must-fix，按序）：
> 1. **P1-01** — §2.3 表格第一行拆正（只删 expected ⇒ 原值 / 只 pop ⇒ None，键均在）+ 注改正；MS-T9(a) 改为「键在（原值）」断言。
>
> P2 可与编码并行修，不阻断。

>>DECISION: APPROVE-WITH-CONDITIONS

- **C1（编码前）**：闭环 P1-01（§2.3 语义表 + MS-T9(a) 断言方向，一行级修正）。
- **C2（同批）**：P2-01..P2-05 随编码批收口（stress_all.py 键检查 / server.md 10 处计数 / cdp_engine.md + SAD DOC_SYNC 补全 / MS-T15 双向表述）。
- 若编排层门禁本就包含文档漂移收口，C2 可按 `APPROVE` 处理。

>>DOC_SYNC:（契约文档遗漏/偏离，由编排层执行）
- `>>DOC_SYNC: doc/detailed/cdp_engine.md → :751/:752「A 类 4 端点」→「A 类 5 端点」（CDP 层零改动，纯计数同步；详设 §12 遗漏，本次补登）`
- `>>DOC_SYNC: doc/arch/SAD.md → 补全计数落点：路由计数（:71-72「14 个 JSON 分支…面板 4」）+ A 类清单（:441「A（4 单体/面板）」）+ _guard 覆盖（:560「全部 14 个 JSON 分支」）；详设 §12 原登记仅含后两处中的部分，本次补全`
- `>>DOC_SYNC: tests/stress_all.py → :117 键列表移除 market_sentiment（非契约文档，测试资产漂移；不在 unittest discovery，不红）`
- （详设 §12 原登记有效项：`API.md`（删 :328/:332 字段行 + 新增端点节仿 :342 + §6.1 面板口径表 :686 可补）/ `README.md`（:54-68 表 +1 行、:58 描述去 "sentiment") / `server.md` v1.18 已增量登记——均确认）`

**check-review.sh 结论行**（`## X、评审结论` 格式 + 表格式结论）：

```
## 六、评审结论

| 评审结论 | ⚠️ 有条件通过（P0×0 / P1×1 / P2×5） |
```

## 变更记录

| 版本 | 日期 | 说明 |
|------|------|------|
| v1.0 | 2026-10-10 | P3b 详细设计评审首版：P0×0 / P1×1（§2.3 语义表 + MS-T9(a) 方向错误）/ P2×5（stress_all.py 漂移 / server.md 10 处计数 / cdp_engine.md + SAD DOC_SYNC 补全 / MS-T15 表述）；⚠️ 有条件通过（APPROVE-WITH-CONDITIONS），闭环 P1-01 后放行 |
