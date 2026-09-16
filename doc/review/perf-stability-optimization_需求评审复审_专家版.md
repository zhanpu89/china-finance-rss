# PRD 复审报告 — 高效/准确/稳定 三指标体检优化（v0.2）

- **报告编号**：REV-REQ-20260915-002（复审）
- **被评文档**：`doc/prd/perf-stability-optimization.md`（PRD-2026-P6C-01，v0.2 待复审）
- **前次报告**：`doc/review/perf-stability-optimization_需求评审_专家版.md`（v0.1：4 P1 + 8 P2）
- **评审模式**：需求复审（P1 闭环核验 + 新缺陷扫描）
- **只读核对依据**：server.py（路由表/health/index）、stock_api.py、stream.py、config.py
- **结论**：**❌ 仍阻断**（P1-3 未完全闭环：AC-S4 期望与响应形态/实现矛盾）

---

## 一、P1 逐项核验

### P1-1 R14 无 AC + §7 值域变更 → ✅ 闭环
- **AC-A10 可测**：同一请求混入「失败码 / 格式非法码 / 无数据码」，断言三类值均 `null`，仅失败码 ∈ `errors` 且为枚举字符串（`upstream_timeout`/`upstream_error`/`cdp_unavailable`）。判别式「null ∧ ∈errors = 失败；null ∧ ∉errors = 无数据」可机械断言。✅
- **§7 只增不改**：改为「新增独立字段 `errors`、保留 null 原语义」，未收窄既有值域；端锁定 🟠 STABLE 符合 endpoint-lock 对「对外 API 新增 / 需评估后向兼容」的分级。✅
- **残留（P2，不阻断）**：批量端点响应体是**扁平 code→data 映射**（`stock_api._handle_cached_batch` 返回 `{code: data|None}`，`server._handle_stock_batch` 直接 `json.dumps`）。`errors`/`truncated`/`dropped_count` 作为**顶层兄弟键**与股票代码同处一个命名空间，PRD 未定义响应包裹（envelope）。存在与代码键命名冲突、并可能破坏「遍历所有 key」型消费方的风险，与 AC-A10「不破坏既有消费方」有张力。

### P1-2 AC-A3 不可测 → ✅ 闭环
- **同源论证与代码相符**（逐项核实）：REST `/stock/basic_info` → `server.py:578` `handle_cls_basic_infos`；SSE `quote` → `stream.py:48` `_FIELD_HANDLERS['quote'] = handle_cls_basic_infos`；同一 `_basic_info_pool`、同一 `_basic_info_cache`、同一 `fetch_cls_basic_info`（`stock_api.py:672-678`）。白盒断言「同 handler / 池 / fetcher」成立且可验证。✅
- 值比对（60 次 ×10s，diff 率 = 0）在同源下必然成立，可执行。✅
- **残留（P2）**：阈值「≤ 分层周期和 = 16s」在同源（diff 恒 0）后属**空约束 / 冗余表述**；且未采纳前次「注明 60×10s 与 8s tick 相位关系」建议（LCM=40s，实际不共振，影响轻微）。

### P1-3 CDP 端点清单 → ❌ 未闭环
- 三分清单条数与路由表一致（只读核对 `server.py:553-606` + `ROUTES`）：A 类 5 条、B 类 13 条（8 JSON + 5 RSS）、C 类 1 条。✅
- `/finance/timeline`（finance 页）与 `/market/timeline`（quotation 页）已分别列出、未合并。✅
- **缺陷①（P1）**：A 类把 `/stock/f10` 与 4 个面板端点并列，期望「返回既定 error 客体、HTTP 200」。但 `/stock/f10` 是**批量端点**（`server.py:574-575` → `_handle_stock_batch` → `handle_cls_f10` → `_handle_cached_batch` 返回 `{code: data|None}`）；Chrome 停止时 `fetch_cls_f10` 返回 None，响应实为 `{"sh600519": null}`，**不是 error 客体**。该期望同时与 AC-A10/AC-S6 的「失败 = null + errors」方案自相矛盾（本案应断言 `{code:null}` + `errors[code]=cdp_unavailable`）。
- **缺陷②（P1）**：C 类断言 `/stock/basic_info` 「sector_name 依赖 CDP、无 CDP 时缺失(null)」。但实现两阶段均 REST（`stock_api.py:628-669`；模块头注 line 4「basic_info now sources sector from REST only」），Chrome 停止时 sector_name 仍返回 → C 类 Then 与实现矛盾。§7.2 已登记该漂移并自述「实现已可纯 REST」，却仍把 AC 按 C 类写死——**既登记漂移又按契约写死 Then，测试口径自相矛盾**，tester 无所适从。

### P1-4 §9 失实 + R6/S7 矛盾 → ✅ 闭环
- R4→AC-A9（70 码 → `truncated` + `dropped_count=20`，与 `server.py:620-624` 截断逻辑一致）、R15→AC-E9（10 次 ×5s < L4 300s，上游计数=1）、R6→AC-S7「现状 31s = `stream.py:364 timeout=30` +1s → 目标 5s」。均可断言。✅
- §9 已删「S 项全覆盖」表述，改为逐项核对，与 §3 实际映射一致。✅
- **残留（P2）**：AC-E9「上游请求计数 = 1」与 R15 自述「/ths/longhu 每次请求打上游两次」（`server.py:141-211` 两次 `urlopen`）口径不一致——按 HTTP 调用计应为 2，需注明「1」指逻辑请求周期。

---

## 二、新发现问题（修订引入 / 残留）

| ID | 等级 | 位置 | 描述 |
|----|------|------|------|
| N1 | **P2（偏 P1）** | §8 / §9 | **AC-A7（去重与池上限）未映射任何测试组**。§8「错误语义组」列为 `A5, A6, A8, A9, A10`——v0.1 原有 A7，v0.2 添加 A9/A10 时把 A7 挤丢。§9「30 条均映射至 §8 测试组」因此失实（实为 29/30）。属**修订引入的新断链**，与前次 P1-4 同类（声称覆盖实则漏）。 |
| N2 | P2 | §9.1 | 声称「P2 全部已顺手修订」，但前次 **P2-2**（AC-A5 五类情形×端点适用矩阵）、**P2-3**（AC-S3 故障注入模式：黑名单秒拒 vs 黑洞超时）、**P2-7**（EFF-3 表现状/目标口径）**均未处理**——§9.1 完整性声明再次失实。 |
| N3 | P2 | §7.2 | `/stock/f10` 的 CDP 标注漂移**未登记**：health 负载 `status='configured'`（`server.py:484-487`）、首页 `json_apis` CDP=False（`server.py:758`），而 AC-S4 将其定为真·CDP 依赖（A 类）。§7.2 只登记了 `/stock/data`、`/stock/basic_info`，漏了 f10。 |
| N4 | P2 | §7.1 / AC-A10 | 顶层 `errors`/`truncated`/`dropped_count` 未定义响应包裹，见 P1-1 残留。 |
| N5 | P3 | AC-A9 | 「请求恰好 50 码时**无 truncated 字段（或为 false）**」为二义表述；tester 只能断言「非真值」，口径宜钉死（建议统一为「≤50 码时字段不存在」）。 |
| N6 | P3 | AC-E9 | 上游计数口径（见 P1-4 残留）。 |

**编号/值域冲突核查**：AC-A10 / S11 / E9 与既有编号**无冲突**；A1-A10、S1-S11、E1-E9 连续无缺号；值域枚举（`upstream_timeout`/`upstream_error`/`cdp_unavailable`）在 AC-A10 与 AC-S6 一致。✅（唯一顺序瑕疵：AC-S6 排在 STB-1 的 S1/S2 之后，非阻断。）

---

## 三、剩余 P2（未处理）

- **P2-2** AC-A5 五类情形×全部端点的适用矩阵未定义（参数缺失仅适用带参端点；RSS 端点的 error-RSS 是否算业务 error 客体未判）——**未处理**。
- **P2-3** AC-S3 故障注入模式未钉死（`60s 不可达` 是秒拒还是黑洞，P95≤3s 结果迥异）；§8 仍写「黑名单」而 AC 未声明——**未处理**。
- **P2-7** EFF-3 资源表未标「现状 vs 目标」，tester 可能把目标当现状（`inflight=40` 等）——**未处理**。
- 已核验修复的 5 项 P2：E7 临时上限 ≤256MB ✅、§7/§9 端锁定统一 🟠 STABLE ✅、AC-A1 时钟回拨例外 ✅、新增 AC-S11 断线重连 ✅、/healthz `/stock/data` 漂移登记 ✅。

---

## 四、结论

> **❌ 仍阻断。** 4 项 P1 中 3 项闭环（P1-1 / P1-2 / P1-4）；**P1-3 未完全闭环**：端点清单已补全、两路分时已区分，但 `/stock/f10` 的期望响应形态（error 客体 vs 批量 `{code:null}`）与 `/stock/basic_info` 的 C 类期望（CDP 依赖 vs 实现纯 REST）**均与代码及本文档自身方案矛盾**。另新增 P2×5（AC-A7 漏映射、§9.1 完整性失实等）。

**放行最小修改集**：
1. **AC-S4 A 类拆分**：4 个面板端点保留「error 客体 + HTTP 200」；`/stock/f10` 改断言批量语义 `{code: null}` + `errors[code]=cdp_unavailable`（与 AC-A10/AC-S6 对齐）。
2. **AC-S4 C 类 `/stock/basic_info` 口径二选一**：按实现改判 B 类（REST 全量返回），或明确要求实现改为 CDP 依赖并承担回归——不能既登记漂移又按契约写死 Then。
3. **§8 补 AC-A7 映射**；**§9.1 改为**「P2 已修 5 项、剩 3 项（P2-2 / P2-3 / P2-7）」。
4. 补 §7.1 `errors`/`truncated` 的响应包裹定义（顶层键 vs 元数据对象），消除与股票代码键的命名空间冲突。

- **变更记录**：2026-09-15 复审（v0.2，核验 4 项 P1 闭环 + 新缺陷扫描）。
