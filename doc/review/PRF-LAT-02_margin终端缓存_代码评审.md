# PRF-LAT-02 · margin 终端缓存 — 代码评审报告

- **CR 编号**：CR-20260920-001
- **评审模式**：`review+drift`（P5b 代码评审 + P7a 漂移检测合并）
- **日期**：2026-09-20
- **变更范围**：`china_finance_rss/config.py`（`DOMAIN_MATRIX['margin']` cache_max `'n/a'`→`8` + 注释）、`china_finance_rss/market_api.py`（新增模块内终端缓存）、`tests/test_config.py`、`tests/test_data_layer.py`（+6 用例，519→525）
- **关联契约**：`doc/detailed/config.md` / `doc/detailed/market_api.md` / `doc/detailed/metrics.md` / `doc/arch/SAD.md`
- **说明**：纯后端小改。`market_api` 不得 import `stock_api`，无前端/小程序变更 ⇒ Dim 0 前端/小程序节、Dim 6 不适用。

## 评审结论

**✅ 无 P0、无 P1；6 项 P2。允许进入测试（P2 不阻断）。**

总评：终端缓存与 `stock_api` 既有终端缓存模式**逐点对齐**（OrderedDict + ts 字典 + 独立 Lock + 同锁 `while len>cap: popitem(last=False)` + 同步 `ts.pop(victim)`），两条关键不变量成立——**只缓存可用 `latest`**、**读写淘汰同锁**；层隔离通过。最值得处理的两条：**命中路径返回缓存内可变对象引用**（潜在污染，当前无触发者，CR-01）与**新增终端缓存未发布 `cache_entries{margin}`**（与 stock 终端缓存约定不一致，关联 AC-S10/E6 观测，CR-02）。

## 一、评审概要

| 项 | 值 |
|---|---|
| 结论 | ✅（无 P0 且 P1 ≤ 2） |
| P0 / P1 / P2 | **0 / 0 / 6** |
| 是否允许进入测试 | 允许 |
| 层隔离（market_api 不 import stock_api） | ✅ 通过 |
| 锁一致性（`_margin_cache`↔`_margin_cache_ts`） | ✅ 通过 |
| 新鲜度风险（终端 vs URL 缓存） | 无（终端不会晚于 URL 过期） |
| 契约漂移 | 有，属 P7b-r6 并行同步范围，详见末尾 |

## 二、评审范围

后端：`china_finance_rss/config.py`、`china_finance_rss/market_api.py`、`tests/test_config.py`、`tests/test_data_layer.py`。
前端 / 小程序：无。对外接口签名 / 返回键 / URL / 枚举取值 / `server.py` 路由 **零变更**。

## 三、问题清单

| ID | 等级 | 位置 | 问题 | 阻断 |
|---|---|---|---|---|
| CR-01 | P2 | `market_api.py:90` | 命中返回缓存内同一可变对象引用（潜在污染） | 否 |
| CR-02 | P2 | `market_api.py:110-116` | 写终端缓存未发布 `cache_entries{margin}` | 否 |
| CR-03 | P2 | `market_api.py:85,112` | TTL 基准取 fetch 前时刻（与 stock 写入时刻不一致） | 否 |
| CR-04 | P2 | `market_api.py:5-7` | 模块 docstring "goes through fetch_json only" 已过时 | 否 |
| CR-05 | P2 | `market_api.py:92` | 计数语义变更使 AC-E4 验收探针前提失效 | 否 |
| CR-06 | P2 | `market_api.py:84-116` | 终端缓存原语第 3 处复制，未上收（技术债） | 否 |

## 四、问题详情

### Dim 0 — 契约一致性（全栈最高优先）

本 change-set **无对外契约变更**：`fetch_margin(market='99', deadline=None)` / `handle_margin(market='99')` 签名、返回键 `{latest, recent}`（含 `_error` 降级形态）、URL `{_MARGIN_URL}/{market}/`、`VALID_MARKETS` 枚举取值、`server.py` 路由与 400 边界均不变。Dim 0.A/B/C/D 不适用（无前端/小程序）。
**内部契约偏差**（代码 vs 详设）逐条列入末尾 `## 漂移检测`，按指示不判为代码错误。

### Dim 1 — 数据与正确性

**CR-01 [P2] 命中路径返回缓存内同一可变对象引用**（反模式：返回裸引用/可变对象）
- 路径：`market_api.py:87-90` —— `cached = _margin_cache.get(market)` … `return cached`；写侧 `:111` `_margin_cache[market] = payload`。
- 证据链：当任一调用方对 `fetch_margin`/`handle_margin` 的返回值**就地修改**（如后端给 `latest` 补字段、统一单位、裁剪 `recent`）→ 修改直接写回缓存对象 → 该 TTL（600s）内**所有命中返回被改数据**，因为命中返回的就是缓存条目本身，无拷贝。
- 当前触发者：**无**。唯一生产链 `handle_margin` → `server._send_json_shape`（`server.py:1259`）→ `_send_json` 仅 `json.dumps(data)`（`server.py:1310`，只读）。
- 等级判定：checklist 将"返回裸引用"泛定为 P1，但本处**无当前变异调用者**，且项目既有 `stock_api` 命中同样返回缓存对象（`stock_api.py:529` `by_canon[canon] = data`），属既有约定 ⇒ 按"证据链要求真实后果"降为 **P2**。
- 修复方向（二选一，建议列入契约同步决策）：① 文档化"返回值只读"，并在 `handle_margin` 出口不泄漏引用（如 `dict(payload)`）；② 若要求强隔离，命中返回浅拷贝（注意 `latest`/`recent` 的嵌套仍需深拷贝才有意义，成本需权衡）。

**CR-03 [P2] 终端缓存 TTL 基准取 fetch 前时刻**
- 路径：`market_api.py:85` `now = time.time()`（在回源**之前**取），`:112` `_margin_cache_ts[market] = now`。
- 证据链：当上游取数耗时 Δ（单次预算 ≤ 10s、故障期 ≤ 5s）→ 条目按"调用入口时刻"起算新鲜期，实际可用 ≈ `ttl − Δ`，比标称 TTL 略早过期、多一次回源；**不会返回陈旧数据**（偏差方向安全）。对照 `stock_api._cache_store` 默认 `now=time()`（`stock_api.py:329`，**写入时刻**）。
- 等级：P2（相对 600s 可忽略，无正确性后果）。
- 修复方向：写侧在锁内重取 `_margin_cache_ts[market] = time.time()`；或至少把 `# TTL base` 注释补明"基准 = fetch 前入口时刻"。

**CR-05 [P2] 计数语义变更使既有验收资产失效**
- 路径：`market_api.py:92` `metrics.incr('upstream_fetch_total', key='margin')` 移到终端缓存 miss 之后；受影响资产：`doc/tester/AC-E4_吞吐验证报告.md:218`。
- 证据链：AC-E4 以「handler 无条件进入，margin 无终端缓存 ⇒ 每次请求都到达该计数器」作为 margin 侧吞吐探针的**前提**；PRF-LAT-02 后终端命中不再计数 ⇒ 重跑 E4 时该探针读数与断言的适用范围变化。
- 等级：P2（**非代码错误**，属验证/文档资产失效；AC-E4 报告不在本轮指定同步的四份文档内）。
- 处理：编排层确认 E4 是否重跑或改探针（其余"无终端缓存"端点仍可作探针）。

**逆向审查（Dim 1/3 扫描）**
- ❓ 恶意输入：`market` 枚举闸在 URL 拼装与缓存键之前（`:76`），bogus 值既不进 URL 也不进缓存，无键膨胀。✅
- ❓ 隐式假设：淘汰条件 `len(_margin_cache) > cache_max`（`:114`）假定 `cache_max` 恒为 int；若未来矩阵把 margin 改回 `'n/a'`（→None），该比较将 `TypeError`。当前矩阵固定 8 且运行期只读 ⇒ 非现实风险，列为观察项，不单独立项。
- ❓ 依赖失效：`fetch_json` 抛 `FetchError`、语义失败、`latest is None` 三条路径均**不写缓存**（`:96-116` 条件门），降级体不会被固化 600s。✅
- ❓ 性能悬崖：命中仍需一次 `cache_policy('margin')`（构 dict）+ 一次加锁，但省去 `json.loads` + `_transform_margin`（本 change-set 的目标收益）。✅
- ❓ 测试盲区：无"外部修改返回值 → 缓存被污染"的护栏用例，也未断言命中返回与缓存**同一对象**（正是 CR-01 的暴露面），见第 5 条。

### Dim 2 — 并发

**通过。** `_margin_cache`（OrderedDict）与 `_margin_cache_ts`（dict）**只在 `_margin_cache_lock` 内成对操作**：命中查 `ts`（`:86-90`）、写 `cache`+`ts`（`:110-113`）、淘汰项同步 `_margin_cache_ts.pop(victim, None)`（`:115-116`）。逐项反证：
- **ts 残留/泄漏**：写与淘汰同锁成对 ⇒ 不存在"cache 有键、ts 无键"或反向；`ts.get(market, 0)` 的默认 0 使异常缺失时判为过期 miss（安全）。
- **过期条目的处理**：过期后条目保留在 `_margin_cache` 中，但读路径要求 `now - ts < ttl` 才命中（`:88`），过期项**不会被服务**且**不做 `move_to_end`** ⇒ 停留在队首附近，容量超限时**优先被淘汰**，自清洁。
- **并发同键 miss**：两个线程同时 miss 会各自进入 `fetch_json`（其内部另有 single-flight 选举），最后写入者胜；各自 `now` 相近，无脏读、无覆盖危害。
- **同锁下的 `move_to_end`**：命中在锁内移动（`:89`），与写侧一致，无 `OrderedDict` 并发修改。

### Dim 3 — 资源与性能

**CR-02 [P2] 写终端缓存未发布 `cache_entries{margin}`**（反模式：复制粘贴代码导致的分化）
- 路径：`market_api.py:110-116`（内联 LRU 写路径）对照 `stock_api.py:338`（`_cache_store` 尾部 `metrics.set_gauge('cache_entries', size, key=domain)`）。
- 证据链：当运维/健康检查读取 `cache_entries` 以核对各域终端缓存的内存界（`cache_max` 的观测口径，AC-S10 / E6）→ margin 恒缺失，因为内联复制的写路径没有 `set_gauge`，而同模式的 stock 有。
- 等级：P2。`metrics.md:108` 的标签枚举当前未含 `margin`，代码未违反**明文**契约；但与本仓"终端缓存写入即发布 `cache_entries{domain}`"（`stock_api` BR-SA-16/26、`cache.py` feed/url、`_sector_cache`）的既有约定不一致。
- 修复方向：`:113` 之后（**锁外**，与 `cache._publish_url_stats`/`_cache_store` 的锁外发布纪律一致）加 `metrics.set_gauge('cache_entries', len(_margin_cache), key='margin')`；`metrics.md` 标签枚举补 `margin`。

### Dim 4 — 安全

**通过。** 无新增输入面：缓存键 = 已校验的 `market` 枚举（`VALID_MARKETS`），URL 仍由枚举成员拼装，注入闸位置未变；无敏感信息进入缓存/日志/响应；无越权面（单体公开只读端点）。

### Dim 5 — 结构与可维护性

**CR-04 [P2] 模块 docstring 过时**（反模式：注释与实现不符）
- 路径：`market_api.py:5-7` "TTL is derived from … only; **fetching goes through `cache.fetch_json` only**"。
- 证据链：命中终端缓存时**不再**经 `fetch_json`，新读者据 docstring 会漏掉 `_margin_cache` 这一层。
- 修复：改为"取数经终端缓存（PRF-LAT-02）→ 未命中再走 `cache.fetch_json`"。

**CR-06 [P2] 终端缓存原语三处重复，未上收 `cache.py`**
- 路径：`market_api.py:84-116` vs `stock_api.py:327-338`（`_cache_store`）vs `cache.py:158-181`（`_cache_put`）。
- **判断：当前不宜强行上收**。理由：① 层隔离硬约束——`market_api` 不得 import `stock_api`，无法复用 `_cache_store`；② 项目规范"不为单次使用做抽象"（code-discipline §2）与 AGENTS"keep this project small"；③ `stock_api._cache_store` 已绑定 pool/domain/metrics 语义，抽到 `cache.py` 会牵动 stock 读路径与 BR-SA-16/26，超出本 change-set 边界。
- 结论：**保留内联可接受**，但 CR-02 正是复制产生的分化（stock 有 gauge、margin 无）——建议在契约同步时登记"终端缓存原语重复 3 处"为已知技术债；未来若出现第 4 处再上收。

## 四·补 — 评审重点逐条回答

**1. 层隔离与模式一致性 / 是否应上收 `cache.py`**
- ✅ `market_api.py` 的 import 仅 stdlib + `.metrics`/`.cache`/`.config`（`:10-18`），**不含 `stock_api`**，同层禁止未违反。
- ✅ 与 `stock_api` 既有模式一致：`OrderedDict` 容器 + 平行 `_*_ts` dict + **独立** `threading.Lock` + `move_to_end` 真 LRU + `while len>cap: popitem(last=False)` + `ts.pop(victim, None)`。
- 上收判断见 **CR-06**：当前不宜上收（层隔离 + 不为单次使用抽象 + 牵连 stock），但应以 CR-02 的 gauge 分化作为"复制成本"的证据登记技术债。

**2. 正确性**
- **共享可变对象**：存在（CR-01），当前无触发者 ⇒ P2。
- **同锁一致性**：✅ 成对读写淘汰，无 ts 残留/泄漏；过期项不服务、优先淘汰，自清洁。
- **deadline 闸排在缓存之前（`:81`）**：符合既有契约 **BR-MKT-3「已过即抛、不触网」**——过期 deadline 即使有缓存也抛 `upstream_timeout`。这是有意的语义差异（对照 `stock_api.cached_batch` 先给缓存、不看 deadline）；且生产入口 `handle_margin(market)`（`server.py:1259`）**不传 deadline**，无实际影响。若期望"缓存命中可豁免 deadline"，那是**契约变更**（需改 BR-MKT-3），不在本评审范围。

**3. TTL 语义（两层 600s）**
- ✅ **不存在终端缓存晚于 URL 缓存过期的风险**：终端 `ts` 取自 fetch **前**的 `now`（`:85`），而 URL 缓存 `_cache_put` 的时间戳在**网络返回后**写入 ⇒ 恒有 `terminal_ts ≤ url_ts` ⇒ `terminal_ts+ttl ≤ url_ts+ttl`，终端只会**不晚于** URL 过期。故不会出现"终端命中但已有比 URL 更陈旧数据"的新鲜度问题（CR-03 是同一事实的另一面：会比标称 TTL 略早过期）。
- ✅ "双 miss 叠加"无危害：两端同时到期最多导致**一次**上游取数（`fetch_json` 内部有 single-flight）；"终端 miss + URL 命中"是一致且预期的（省网络、仍需 parse+transform——这正是终端缓存的价值）。

**4. 可观测性**
- ✅ 语义确与 stock 对齐：stock 为"终端 miss → 调 fetcher → `incr`"（如 `stock_api.py:857`），margin 现在同为"终端 miss → 调 `fetch_json` → `incr`"，比旧版"每请求 +1"更贴近真实取数。
- ✅ 异常路径无多计/漏计：miss 时先 `incr` 一次（`:92`）；`fetch_json` 抛 `FetchError` 时本函数**不重计** fail（`:96-97`，由 fetch_json 内部计）；`json.loads` 异常（`:98-100`）与 `status_code != 0`（`:104-106`）各计 1 次 fetch + 1 次 fail，语义自洽。计数语义变更的下游影响见 **CR-05**。

**5. 测试强度**
- ✅ 6 条用例**可证伪**。打桩用 `patch.object(market_api, 'fetch_json', ...)`（`fetch_margin` 调用模块全局）——**全限定名正确**。
- ✅ TTL 用例回拨 `_margin_cache_ts['99'] = time.time() - ttl - 1`（`:1471`）有效：`time.time()`（更晚）− ts > ttl ⇒ 必然 miss。
- ✅ LRU 有界用例通过 `patch.object(market_api, 'VALID_MARKETS', markets)` 临时扩展为 10 个合成成员（`:1481`），断言容量=8、淘汰最旧 2 键、`_margin_cache` 与 `_margin_cache_ts` 长度一致；`patch.object` 退出即还原，且 `setUp/tearDown` **双向**清缓存 ⇒ **无跨用例污染 / 无顺序依赖**。
- ✅ 失败不缓存 / 空数据不缓存 / 仅 miss 计数 三条直击写路径条件门。
- ⚠️ **唯一缺口**：未断言命中返回与缓存**同一对象**（`assertIs`），也无"外部修改返回值 → 缓存被污染"的护栏用例（CR-01 的暴露面）。建议补 `assertIs(first, second)` 明示共享语义，或补变异防护测试锁死"只读"约定。

**6. 契约漂移**：见下方 `## 漂移检测`（按指示只列，不判代码错误）。

## 五、修复建议

**建议本轮顺手处理（低成本、无契约风险）**
1. **CR-02**：`market_api.py:113` 之后（锁外）加 `metrics.set_gauge('cache_entries', len(_margin_cache), key='margin')`，对齐 `stock_api._cache_store`。
2. **CR-04**：修 `market_api.py:5-7` docstring，写明"终端缓存 → `fetch_json`"两层。
3. **CR-03**：写侧改用锁内 `time.time()` 作 ts，或在注释登记"基准 = fetch 前"。

**需编排层决策**
4. **CR-01**：命中返回值是否拷贝 / 仅文档化只读 —— 涉及 `handle_margin` 对外返回语义，宜与契约同步一并裁定。
5. **CR-05**：AC-E4 是否重跑或更换探针（其前提已被本轮推翻）。
6. **CR-06**：是否登记"终端缓存原语重复 3 处"为技术债（不阻断）。

**改进优先级**：CR-02 > CR-04 > CR-05 > CR-01 > CR-03 > CR-06。

## 六、评审结论

**✅ 通过**——无 P0、无 P1（P1=0 ≤ 2），6 项 P2 记录不阻断，允许进入测试。
关键不变量（只缓存可用 `latest`、读写淘汰同锁、键=合法枚举、失败/空数据不写缓存）均已由代码与用例双重保证。

---

## 七、修复副作用逆向检查（P5b）

本轮入参**未携带 `>>SIDE-EFFECT:` 标记**，以下从变更范围推断受影响点，并标注所属模块（供编排器映射 `>>SCOPE:` 定向回归）：

| 受影响点 | 模块 | 行为变化 | 逆向假设与结论 |
|---|---|---|---|
| `fetch_margin` 返回值来源 | `market_api`（margin 域） | 可能来自终端缓存（同一对象） | 假设有调用方就地修改 → 污染缓存（CR-01）。已核对唯一生产链 `handle_margin`→`_send_json` 只 `json.dumps` ⇒ **当前不成立**；加护栏测试可证伪 |
| `cache_policy('margin')['cache_max']` | `config` / `market_api` / healthz 策略转储 | `None` → `8` | 假设有消费者按 `None` 分支处理 margin → 已检索：只有 `market_api` 消费且按 int 使用；无 `is None` 分支 ⇒ **不成立** |
| `upstream_fetch_total{margin}` 计数点 | `metrics` / 健康检查 | 由"每请求"→"终端 miss" | 假设下游按请求速率解读 → AC-E4 探针前提失效（CR-05）⇒ **成立**，非代码错误，转验证侧 |
| `DOMAIN_MATRIX['margin'].cache_max` | `config`（唯一权威） | `'n/a'` → `8` | 假设其他模块重复定义了 margin 上限（违反"一处数据只改一处"）→ 已检索 `cache_max` 全仓无第二处 margin 定义 ⇒ **不成立** |
| margin 域内存占用 | `market_api` 缓存 | 最多 +8 个解析对象的常驻 | 假设触发内存护栏/AR-8 总账 → 量级相对 ~200MB 终端缓存总账可忽略 ⇒ **不成立** |

**结论**：未发现"修好一个引入另一个"的副作用；唯一真实行为外溢是计数语义（CR-05）与对外可观测的 `cache_entries` 缺口（CR-02），均非正确性回归。

---

## 漂移检测（P7a · 与 P5b 合并执行）

> 代码与以下契约文档不一致；**本轮 P7b-r6 并行同步中，不判为代码错误**。

**D1 契约核对**
- 代码：`config.py:385` `margin = ('L4', 2.0, 2.0, 'fixed:16', 8)`；代码注释 `config.py:354-361` 已自洽（明确 margin 离开 URL-cache-only 组、`market_api._margin_cache`）。
- 对外接口/返回键/URL/枚举/路由 **零变更**；`cache_policy` 键集合与其余 11 域零变更。

**D2 待同步文档清单（逐条）**

1. **`doc/detailed/config.md`（v1.13，用例 519）**
   - 头部版本 + 用例数 **519 → 525**，追加 PRF-LAT-02 变更段。
   - §3.1 实值表（`:342`）`margin … cache_max: null` → **8**；矩阵源（`:310`）`'n/a'` → **8**。
   - §3.1 语义表（`:88`）+ P7b 注（`:315`）：URL-cache-only 域清单 `plate/news_url/longhu/margin` → **移除 margin**。
   - **BR-CFG-5**（`:387`）：URL-cache-only 枚举措辞去 margin。
   - **CFG-T13**（`:619`）：`margin` 的 `cache_max is None` 断言 → `== 8`，并登记 margin 终端缓存新用例；**CFG-T19**（`:625`）总数 519 → 525。
   - **§10#15**（`:668`）：P7b 的"margin cache_max=None"结论被 PRF-LAT-02 取代，需追记 superseding 条目。
   - CFG-T3（`:609`）不变（margin ttl 仍 600）。
2. **`doc/detailed/market_api.md`（v1.4）**
   - `:30`「不新增缓存容器 … 本模块**不持有** `_margin_cache`/锁/metrics 私有状态」→ **已不成立**，改写为"持有 8 条终端缓存（PRF-LAT-02）"。
   - `:169` `cache_max: null` → **8**；`:172`「本模块**不消费** … `cache_max`」→ **消费**（LRU 淘汰）。
   - **BR-MKT-9**（`:187`）「每次上游取数调用计数」→ 收窄为"每次**终端缓存 miss**（即 `fetch_json` 调用）计数"，与 stock 域对齐。
   - §2.1 伪代码（`:221` 起）插入终端缓存命中短路 + 写回/淘汰步骤；§10 追加 PRF-LAT-02 条目与新 MKT-T* 用例编号。
3. **`doc/detailed/metrics.md`**
   - `:108` `cache_entries` 标签枚举：若采纳 CR-02，补 `margin`；`:112` `upstream_fetch_total` margin 语义注记"终端 miss 口径"。
4. **`doc/arch/SAD.md`**
   - §2.1 矩阵（`:186`）`margin … 'n/a'` → **8**（注释"URL 缓存独占"作废）；更正说明（`:208`）"URL 缓存独占域（`plate`/`margin`/`news_url`/`longhu`）"→ 去 margin。
   - `:796`、`:1520 D-2` 两处"`plate`/`margin` 的 `cache_max='n/a'`"→ margin=8。
   - §7.2/AR-8 内存总账：margin +≤8 条解析对象，量级可忽略，~200MB 终端缓存总账口径不变。

**D3 DOC_SYNC 追溯**：本轮入参未携带 `>>DOC_SYNC:` 标记；上述四份由 P7b-r6 并行同步，完成后本漂移节可关闭。

**D4 域外同源风险（非四文档）**
- `doc/tester/AC-E4_吞吐验证报告.md:218`：以"margin 无终端缓存"为探针前提，已被本轮推翻 ⇒ 需编排层决策重跑/改探针（对应 **CR-05**）。
- `doc/detailed/_PROGRESS.md`：按惯例同步本次 change-set。

**D5 结论**：**有漂移**（预期内，P7b-r6 并行处理中）。已列出四份指定文档 + 1 份 tester 报告，**无未被登记的漂移**。

## 变更记录

| 版本 | 日期 | 说明 |
|---|---|---|
| r1 | 2026-09-20 | 首轮评审（`review+drift`）；P0=0 / P1=0 / P2=6；漂移 4 文档 + 1 tester 报告 |




