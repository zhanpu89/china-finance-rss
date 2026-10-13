# market_sentiment P5a-r3 代码评审报告（P5b-r2 + P7a 合并）

**CR-20261013-001** · 版本 r1 · 状态 已完成 · 评审模式 `>>MODE: review+drift` · 日期 2026-10-13
**评审对象**：P5a-r3（修 P8/评审残留 3 条非阻断 P2/备注）
**改动文件**：`china_finance_rss/server.py`（+26/-1）、`tests/test_server_http.py`（+112）
**契约参照**：`doc/detailed/market_sentiment_独立接口.md` v1.0.3 · `doc/detailed/cls_pools.md` v1.0.3 · `doc/detailed/server.md` v1.20

---

## 一、评审概要

**P0 = 0 · P1 = 0 · P2 = 0（代码/测试问题）；契约漂移 3 文档共 13 项（必改 9 + 顺带 4，见 §六）→ 交 P7b。**

**总评（最重要三件事）**：
1. 三条修复全部正确闭合——`time.monotonic()` 钟源替换、成功路径 pop 关闭故障 episode、`_send_text` 内在 HEAD 守卫（O1），逐条逆向核实均未引入新行为缺陷（SE-1..SE-4 全部证伪为"不成立/可接受"）。
2. 三条新用例（MS-T18/T19/T20）+ MS-T17 播种修正均 hermetic 且可证伪——从代码推演：任一修复被回滚，对应用例必红，且 MS-T18/MS-T19 各带双保险断言。
3. **全部残留风险在文档侧**：§5.5 伪代码仍写 `now = time.time()`、§7.1 未登记 episode/单调钟语义、§8 缺 MS-T18/19/20、`server.md` §2.10 HEAD 守卫未同步——本报告 §六给出 P7b 精确同步清单，**不阻断进入测试**。

**结论：✅ 通过，允许进入测试。**

## 二、评审范围

- 后端：`china_finance_rss/server.py`——限频表设计注释+钟源（:457-483）、成功路径 pop（:528-534）、`_send_text` HEAD 守卫（:1597-1605）。
- 测试：`tests/test_server_http.py`——MS-T17 播种改单调钟（:414-419）；新增 MS-T18（:429-466）、MS-T19（:468-505）、MS-T20（:1234-1260）。
- 分级：小 diff（<200 行）→ 仅加载 review-checklist；纯后端，Dim 0 以 `doc/detailed/` 详设为契约源（无前端/小程序端，Dim 6 跳过）。

---

## 三、受影响点推断（`>>SIDE-EFFECT` 逆向核对；模块列供编排器映射 tester `>>SCOPE:`）

| # | 申报受影响点 | 模块（SCOPE） | 逆向假设 → 结论 |
|---|---|---|---|
| SE-1 | `server.py:478` 表时间戳 epoch→monotonic | server / cls-pool 日志限频(B-02) | ① 是否有其它读者把 `last_ts` 当墙钟解读？全仓 grep `_pool_fetch_warned_at`：仅 `_warn_pool_fetch_failed` 写、成功路径 pop、测试 save/restore——**无任何墙钟解读方** → 不成立；② 同表是否遗漏其它墙钟取时点？限频函数仅 :478 一处取时 → 不成立；该表不被 admin/metrics 暴露，进程重启即弃，无持久化解读 |
| SE-2 | `server.py:533` 成功 pop：旧"同消息 30s 内一律静默"→"成功后同消息立即再告警" | server / handle_cls_pool 成功路径 | ① 既有调用方依赖旧宽松语义？全仓仅限频函数+测试触碰该表，无业务方读它 → 不成立；② 与并发冲突？`dict.pop` 单键原子（CPython），与并发 warn 写交错最坏=窗口内多/少告警一次——与该表既有"lock-free/容忍竞态"口径一致 → 可接受；③ 与有界性冲突？pop 只减键、写入仍在枚举闸（:497）之后 → 键恒 ⊆ `_POOL_TYPES`、≤4 → 不成立；④ 语义放宽（见 §四观察）：上游成功/失败交替抖动时告警上界由 1/30s/pool 放宽为 ≈1/(NEG_TTL+plate TTL)/pool，由负缓存+URL 缓存 TTL 自限、非 RPS 级 → 记录不阻断 |
| SE-3 | `server.py:1604` `_send_text` 写体条件收紧 | server / HTTP 发送层 | ① 影响非 HEAD 路径？GET 等 `command != 'HEAD'` 恒真 → 条件与旧 `write_body` 等价 → 不成立；② 现存调用点零变化？`do_HEAD`(:1305) 全链 `write_body=False`、`do_GET`(:1311)=True，守卫对存量只是恒真/恒假叠加 → 不成立；③ 动了 Content-Length/头？守卫位于 `end_headers()`(:1596) **之后**，头（CL/Content-Encoding/ETag…）逐字不变、仅体被抑制，恰合 RFC 9112 §9.3.2 → 不成立；④ `command` 缺省（getattr→None）→ 照旧写体 = 向后兼容回退；⑤ `_send_not_modified` 独立路径不经 `_send_text`，304 语义零牵连 → 不成立 |
| SE-4 | `tests:418` 播种基准墙钟→单调 | tests / MS-T17 | 实现与测试钟源必须同源：实现已 monotonic，若播种仍用 epoch → `now-prev` 为负、窗口永不过期、MS-T17 的 expired 分支假红；两者已同步 → 一致（diff 推断补报的受影响点） |

---

## 四、问题清单

**F-x 编号：无 —— P0 / P1 / P2 均为 0。** 三条修复的逆向扫描逐项均写不出可复现后果（反模式命中核查：D1 无新增魔法数字——`_POOL_FETCH_WARN_GAP=30.0` 为既有常量；D2 并发见 SE-2②；D3 无资源面——表 ≤4 键、无新增 IO；D4 无安全面——消息走 lazy `%s` 参数化、无注入/越权面变化；D5 结构——新注释均为"why"型设计注释，符合项目注释纪律）。

**❓ 逆向记录（均证伪，不构成问题）**：
- 恶意输入：`_send_text` 守卫仅判 `command` 字面量；pop 只在枚举闸（:497）与成功路径之后可达 → 键值域不可被污染。
- 边界值：`now - prev[0] == 30.0` 恰好不 `< GAP` → 再告警——判定式与旧实现逐字相同，无 off-by-one 变化。
- 测试盲区（**观察 O-1，不计 P2**）：MS-T18 用 `patch.object(srv.time, 'monotonic')` 打桩 stdlib 全局模块属性。代码推演当前套件无受害方：块内无网络/无 socket 读写（`fetch_json` 已整体打桩、直调 handler 不经 HTTP fixture）、logging 记录时间用 `time.time(_ns)` 非 monotonic、unittest 串行执行、`threading.join`/socket 超时不在块内；且 `server.py` 是 `import time`，`srv.time` 本就是唯一可打桩缝。**残余风险**：未来若在该 with 块内引入线程 join 或 socket 超时（依赖 monotonic 的 CPython 内部），需复查——记录备注，不阻断。

**观察 O-2（非本轮引入，登记不阻断）**：`server.py:525` shape 异常路径仍逐次 `log.warning`、不经 `_warn_pool_fetch_failed` 限频——该行 diff 未触碰（前轮评审亦未列）；触发条件为"信封 200 但 data 非 list"的形态漂移，回源频率被 plate TTL 自限，非 RPS 级。仅登记，供后续治理参考。

---

## 五、修复闭合核验

| 修复 | 落点 | 闭合判定 |
|---|---|---|
| 墙钟 → 单调钟（P8-r1 P2「墙钟」） | `server.py:478` + 注释 :457-461 | ✅ 实现取 `time.monotonic()`；全表唯一取时点；MS-T17 播种同步（:418-419）；MS-T18 锁死钟源与**存储值本身**。NTP 回拨（差值变负 → 永 `<GAP` → 抑制窗拉长至无限）与前跳（提前再告警）两分支均消除 |
| episode 盲区（P8-r1 P2「episode」） | `server.py:528-533` + 注释 :462-465 | ✅ 仅**真正成功**（`data` is list）后 pop；信封失败/shape 失败不 pop → episode 延续，语义自洽（这两类失败本就不经限频告警路径）；MS-T19 断言 pop 生效 + 新 episode 再告警 |
| O1：`_send_text` 内在 HEAD 守卫 | `server.py:1597-1605` | ✅ 无 body 规则内聚到发送点（镜像 CPython `send_error` 的 `if self.command != 'HEAD'`），未来调用点忘传 `write_body=False` 也无法把体写上线；MS-T20 正是模拟该"遗忘调用点" |

**任务指定的三项逆向核实**：
1. **单调钟替换是否遗漏其它墙钟调用方**：全仓 grep——`_pool_fetch_warned_at` 仅 4 处触碰（:467 定义/:478 取时/:482 写/:533 pop）+ 测试；`server.py` 其余 `time.time()` 仅 :139（RSS `lastBuildDate`，绝对时刻语义）与 :1298（访问日志日期），与本表无关；cache/cdp/stream 的 wall-clock 属 TTL/预算绝对时间设计、非本表契约且在他模块已登记口径 → **无遗漏**。
2. **成功 pop 是否与并发/有界冲突**：见 SE-2②③——pop 单键原子、只减不增、容忍竞态口径不变 → **无冲突**。
3. **HEAD 守卫是否影响非 HEAD 路径或 Content-Length**：见 SE-3②③——GET 条件等价、头/CL 在守卫之前逐字发出 → **零影响**。

**三条新用例 hermetic + 可证伪（自代码推演，未引用任何测试报告）**：

- **MS-T18** `test_rate_limit_window_uses_monotonic_clock`（:429-466）
  *hermetic*：表快照 save→clear→finally restore（:443/:464-466）；钟打桩 scoped 于 with 块；块内无 monotonic 消费方（见 O-1 推演）。*可证伪*：若实现仍用 `time.time()`——第一次存 epoch T，第三次调用 T'−T≈0 仍 `<GAP` → `assertLogs`（:460）无记录**必红**；即使绕过，存储值断言 `==1040.0`（:463）对 epoch 值也**必红**（双保险）。1000/1010/1040 三档精确覆盖 窗口内静默(10<30) 与 窗口外续报(40≥30) 两分支。
- **MS-T19** `test_success_clears_the_warn_episode`（:468-505）
  *hermetic*：同型隔离（:480/:503-505）；四步调用依赖真实时钟 30s 内完成（相邻语句级，实际不可触发）。*可证伪*：删 `server.py:533` 的 pop → `assertNotIn('up_pool', …)`（:498）**立即红**；即使跳过该断言，旧 `(ts,msg)` 残留使末次同消息失败落在窗口内静默 → `assertLogs`（:500）也**红**（双保险）。成功桩 `_fake_fetch` 返回 `json.dumps(payload)`（:259）→ 走真实成功路径（code=200 → data 为 list → pop），非旁路。
- **MS-T20** `test_head_guard_is_intrinsic_to_send_text`（:1234-1260）
  *hermetic*：`patch.object(RSSHandler, '_handle_request', leaky)` scoped（:1253）；`RSSHandler`/`re` 已在文件头 import（:41/:20）；裸 socket `_raw_exchange` 复用 HttpSemanticsTests 既有 server fixture。*可证伪*：删 `!= 'HEAD'` 守卫 → HEAD 线上写体 → `assertEqual(body, b'')`（:1258）**红**；GET 自证（:1254-1255）排除"读法本身看不到体"的空断言风险；`Content-Length > 0`（:1259-1260）锁定头仍按 GET 口径（RFC 9112 §9.3.2）。`leaky` 对 `do_HEAD` 传入的 `write_body=False` 仍强制 `True`——正是在模拟"忘传参的未来调用点"，设计正确。
- **MS-T17 播种修正**（:414-419）：与实现钟源同源（SE-4）。设计事实（非缺陷）：修正后 MS-T17 **单独不再区分**钟源（epoch 播种在 monotonic 实现下使 `now-prev` 为负 → 窗口恒过期 → expired 分支仍绿），钟源区分力由 MS-T18 独立承担——两用例合取后覆盖完整。

**Dim 0-5 覆盖小结**：D0 对外契约零变化（响应码/字段/日志格式逐字不变；HEAD 线上行为对现存调用点零变化）→ 无对外漂移；D1-D5 无命中（详见 §四）。P2-5 限频原始目标（日志量随事件而非 RPS）在 O-2 与 SE-2④ 两处的放宽均已量化并判定可接受。

---

## 六、漂移检测（P7a）

**D1 契约核对**（逐文档对照本轮代码）· **D2 `>>DOC_SYNC` 追溯**：P5a-r3 入参未携带 `>>DOC_SYNC` 标记（修复轮，编排层改由本漂移清单派发 P7b）→ 下表即 P7b 派工单。**D3 规范合规**：✅ 通过——手术式修改（diff 仅限两文件目标区域、未"顺手改进"邻近代码）；测试隔离沿用同文件既有 save/clear/restore 模式（先找模式再编码）；无新增依赖/配置项/HTTP 出口（arch-thinking 三关通过）；注释为 why 型。

### 需 P7b 同步的精确清单（13 项 = 必改 9 + 顺带 4，涉 3 文档）

**① `doc/detailed/market_sentiment_独立接口.md`（v1.0.3 → v1.0.4）**

| # | 位置 | 现状 → 需改为 | 类别 |
|---|---|---|---|
| M1 | §5.5 B-02 伪代码 `:288` | `now = time.time()` → `now = time.monotonic()`（+ 一行注：区间测量 ⇒ 单调钟，NTP 阶跃免疫；表存单调读数非墙钟） | 必改 |
| M2 | §5.5 行号 `:281`（实现 `:457-474`）、`:272`（调用点 `:503-504`） | 实现 → **`:466-483`**（设计注释 `:457-465`、常量/表 `:466-467`、函数 `:470-483`）；调用点 → **`:513-514`** | 必改 |
| M3 | §5.5 B-02 块 | 补 episode 伪代码：`handle_cls_pool` 成功路径 `_pool_fetch_warned_at.pop(pool_type, None)`（一次成功结束故障 episode，其后同消息失败立即再告警） | 必改 |
| M4 | §8 用例表（现止于 MS-T17 `:375`） | 新增 3 行：**MS-T18**（注入受控单调钟 1000/1010/1040 ⇒ warn→silent→warn，且表内时间戳==1040.0；可证伪：回滚 time.time ⇒ :460/:463 双红）、**MS-T19**（fail→同 fail 静默→成功 pop→`assertNotIn`→再 fail 告警）、**MS-T20**（`_send_text` 内在 HEAD 守卫；`leaky` 调用点 + 裸 socket GET 自证/HEAD 体空/CL>0） | 必改 |
| M5 | §5.5 `:295` B-03 行号 `server.py:467-468` | → **`:520-521`** | 顺带（P5a-r1 已记、仍未修） |
| M6 | §5.4 `:264` `server.py:1287` | → **`:1353`**（`_PANEL_HANDLERS` 分发分支） | 顺带（本轮 +15 行后偏移至 +66） |
| M7 | §8 MS-T17 行 `:375` 描述含「错误消息变化**即时再告警**」 | 现行用例无该步骤（仅 首告警/窗口静默/窗口过期续报）→ 文档按现状收口，或裁决给用例补步骤 | 顺带（v1.0.3 登记时已偏） |

头部版本 bump + changelog 行；`_PROGRESS.md` 登记按惯例由编排层处理。

**② `doc/detailed/cls_pools.md`（v1.0.3 → v1.0.4）**

| # | 位置 | 现状 → 需改为 | 类别 |
|---|---|---|---|
| C1 | §7.1 `:411` 限频表行 | 语义更新三点：`last_ts` 为 **`time.monotonic()` 单调读数**（非 epoch 墙钟）；「同 pool_type 同消息 30s 窗口只告警一次」补 **「成功取数即 pop 清键、episode 重开——其后同消息失败立即再告警」**；行号落点补 `:466-483`（限频实现）/ `:533`（pop） | 必改 |
| C2 | §7.1 `:415` 并发读者行 | 「最坏结果仅为窗口内多告警或少告警一次」→ 可顺带补入 pop 单键原子、与并发 warn 交错同属容忍竞态 | 必改（可并入 C1 句） |
| C3 | §5 伪代码 `:321` | `return {'stocks': data}` 前补 `_pool_fetch_warned_at.pop(pool_type, None)`（+ 一句 episode 注） | 必改 |
| C4 | §5 伪代码 `:307-038`、`:314` | except 分支补 `_warn_pool_fetch_failed(pool_type, exc)` 调用；`:314` 补外层 `str()`（B-03） | 顺带（**P7b-r2 漏同步**，非本轮引入） |
| C5 | §8 POOL-T15 行 `:441` | 同 M7 描述收口；并按 T15↔MS-T17 双登记惯例新增 **POOL-T16/T17** 行登记 `test_rate_limit_window_uses_monotonic_clock` / `test_success_clears_the_warn_episode`（或裁决改为单侧登记 + 交叉引用） | 必改（描述部分顺带） |

头部版本 bump + changelog 行。

**③ `doc/detailed/server.md`（v1.20 → v1.21）**

| # | 位置 | 现状 → 需改为 | 类别 |
|---|---|---|---|
| S1 | §2.10 `_send_text` 伪代码 `:1713` | `if write_body:` → `if write_body and getattr(self, 'command', None) != 'HEAD':` + O1 注释要点（HEAD 无体内聚于此、镜像 CPython `send_error`、头/Content-Length 不受影响 RFC 9112 §9.3.2、守卫在 `end_headers()` 之后） | 必改 |
| S2 | §8 用例表 | 新增行登记 **MS-T20** `test_head_guard_is_intrinsic_to_send_text`（建议 SRV-T 编号 + 交叉引用 MS-T20，沿 SRV-T33「HEAD 不写体」相邻登记）；SRV-T33 `:1978` 补注「HEAD 无体自 v1.21 起为 `_send_text` 内在保证（O1），`write_body=False` 仍为既有调用约定」 | 必改（后半可选） |
| S3 | 头部版本 + changelog | v1.20 → v1.21，登记 O1 为实现事实对齐（**非契约变更**） | 必改 |

**无需同步**：`API.md` / `README.md` / `doc/arch/SAD.md`——对外契约零变化（响应码/字段/日志格式逐字不变；HEAD 对现存调用点线上行为零变化；无新端点/签名/配置）。`metrics/cache/config` 等无交集文档不动。

**D4 漂移节结论**：⚠️ **有漂移（13 项，见上表）**，全部为文档落后于代码，**代码侧无需回改**；P7b 按上表派发 doc agent 同步 3 文档，同步后建议复核 M2/M6 行号以实际文件为准。

---

## 七、评审结论

| 门禁项 | 结果 |
|---|---|
| P0（崩溃/数据丢失/资金/安全） | **0** ✅ |
| P1（功能缺陷/单点/性能退化） | **0** ✅ |
| P2（可维护性/规范） | **0** ✅（观察 O-1/O-2 登记不阻断） |
| 修复闭合（3/3：钟源 / episode / HEAD 守卫） | ✅ 全部闭合，注释与实现互证 |
| 副作用逆向核验（SE-1..SE-4，含 SE-4 补报） | ✅ 4/4 不成立或可接受；SE-2④ 语义放宽已量化记录 |
| 新用例 hermetic（MS-T18/19/20 + MS-T17 播种） | ✅ 4/4 隔离完整 |
| 新用例可证伪（自代码推演） | ✅ 4/4 回滚任一修复必红；T18/T19 各双保险 |
| Dim 0 对外契约一致性 | ✅ 零变化（无 API/README/SAD 同步义务） |
| P7a 漂移（D1-D4） | ⚠️ 13 项（必改 9 + 顺带 4，3 文档）→ **P7b 同步**，不阻断测试 |
| **是否允许进入测试** | **✅ 允许**（P0=0 且 P1=0；漂移清单并行派发 P7b，终审/收口前完成即可） |

> P5b-r2 与 P7a 两道门禁：**代码门禁 ✅ 通过；文档门禁 ⚠️ 待 P7b**（清单见 §六）。

>>DECISION: APPROVE
