# SSE 流推送加固_代码评审

- **评审对象**：commit `6133e25`（相对 `fd4e009`），工作树 `/root/project/china-finance-rss`
- **涉及文件**：`stream.py` / `cdp_engine.py` / `server.py` / `config.py` / `cache.py` / `docker-compose.yml`（纯后端，无前端/小程序改动）
- **评审模式**：review（聚焦提交审查，非盲审）
- **评审日期**：2026-09-15
- **CR 编号**：CR-SSE-20260915-01
- **资源核对**：本项目无 `resources/review-checklist.md` / `doc/detailed/`（无 OpenAPI 详设），按技能内置 Dim 0-6 维度执行；`doc/review/stream传播修复复审_代码评审.md` 为上一轮针对同批修复的评审，本报告为提交落地后的**逐项落实验证 + 残留窗口审查**。

---

## 评审概要（总评）

**⚠️ 可合并 —— 上一轮评审要求的 3 处核心修复（有界队列、重启 throttle 守卫、STREAM_HOST 配置化）均已正确落地，未引入 P0；但 throttle 守卫存在一处"检查在锁外、执行在锁内不重查"的 TOCTOU 残留窗口（P1，低危概率、自愈、3 行可修），建议合并前修复。其余 5 条 P2 记录不阻塞。**

按系统优先级逐项对照：接口稳定 ✅（API 签名/URL/事件格式零变化）；数据新鲜 🔶（P1 残留窗口 + P2 丢帧方向）；线程安全 ✅（锁序无环，见 A1-A3）；资源回收 ✅（有界队列上限生效，退出延迟有界）；缓存合理 🔶（容量数字与 `MAX_DEDUP_CODES` 预算不匹配，P2-2）。

**受影响点与模块映射（入参无 `>>SIDE-EFFECT:` 标记，按变更面推断，供编排器映射 `>>SCOPE:` 定向回归）：**
| 变更 | 受影响点 | 模块 |
|------|---------|------|
| cache.py `MAX_CACHE_SIZE` 200→2000 | 所有 `fetch_json` 调用方（RSS 源 / stock_api 全 fetch / stream `_refresh_pool` / market_api） | 缓存 |
| 池上限 300→500（timeline/basic_info） | `_timeline/_basic_info_prefetch_loop` 全覆盖面、`handle_cls_timeline/basic_infos` | stock_api |
| stream 队列有界 maxsize=8 | SSE 连接生命周期（慢客户端丢帧、destroy 退出延迟） | stream |
| `STREAM_HOST` 绑定参数化 | stream 服务绑定地址、docker-compose 8054 对外暴露面 | stream/部署 |
| `_maybe_reconnect` 计数器锁分离 + throttle | 全部 CDP 页（finance/quotation/3 个 stock nav 页）的导航/心跳/重连路径 | cdp_engine |

---

## Dim 0 — 契约一致性

`doc/detailed/` 下无对应模块详设（本项目仅 README 承载接口契约），按规则跳过 OpenAPI 逐字段核对，输出说明。

- **0.A 后端接口面**：stream 端点路径/方法/事件格式（`event: quote` / `id` / `data` / `event: ping`）零变化；`_read_json_body` 新增的非数字/负/超长 Content-Length → 400，为防御性收紧，与既有错误语义兼容（原行为是 `int()` 抛 ValueError 挂连接）。
- **0.B 对外访问边界（契约级变更）**：`docker-compose.yml` 新增 `8054:8054` 映射 + `STREAM_HOST=0.0.0.0`（此前 stream 绑 127.0.0.1 且无映射 → 容器外不可达；现为**有意扩容**，不破坏既有访问方式）。非 compose 部署保持 loopback 默认，与上一轮 P1-4 修复方向一致。⚠ 见 P2-3/P2-4：新配置项与暴露面变化未同步 README。
- 端间一致性：无前端/小程序，跳过。

## Dim 1 — 数据与正确性

**P2-1　stream.py:151,169-172 + 258-260　有界队列"丢新不丢旧"，与注释语义相反**

- 命中反模式：注释与实现语义漂移（`_SSEConn` docstring "L1 tick drops frames for a lagging client — next tick overwrites" 宣称**新帧覆盖旧帧**）。
- 证据链：`queue.Queue(maxsize=8)` + `put_nowait(frame)`——队列满时 `except queue.Full: pass` 丢弃的是**新帧**（FIFO 行为），旧帧留在队首。当 {慢客户端 TCP 写缓冲停滞 ≥64s（8 帧×8s tick）} 时 → 恢复后客户端收到**最多 8 帧累计延迟 64s 的旧行情**，而最新帧全部被丢——短线交易场景下"旧价当新价"比"丢帧"危害更大，与系统优先级 #2 数据新鲜直接相悖。健康客户端（每 8s 排空一帧）不受影响。
- 影响维度：数据新鲜（慢客户端路径）。
- 修复方向：Full 时丢最旧保最新——`except queue.Full: self.q.get_nowait()（吞 Empty）; self.q.put_nowait(frame)`，或改用 LIFO 语义并在注释中修正描述。

**P2-1b（同条附注，前轮已接受不再单独计级）**：`destroy_group` 满队列时 `put_nowait(None)` 哨兵被吞（258-260）→ handler 退出延迟 ≤ get 剩余(20s)+写超时(40s) = ≤60s，有界可接受；**但该上限未在代码注释中记录**（前轮评审要求"修正注释/申报描述"，本次仍未落实）。建议在 258 行旁补一行注释。

## Dim 2 — 并发

**P1（低危）　cdp_engine.py:1073-1083 + server.py:915-922　节流守卫 TOCTOU：锁外检查、锁内不重查**

- 命中反模式：check-then-act 竞态（守卫读取 `_last_chrome_restart` 在 `_chrome_restart_lock` **之外**，`full_chrome_restart` 锁内**不重查**节流，且内部刻意 `_last_chrome_restart = 0`（:253）绕过 throttle——该设计对"已经决定的合法重启"正确，但对竞态中的第二个执行者无兜底）。
- 证据链：nav 线程过 :1073 检查（`_last_chrome_restart` 仍显示 >30s 前）→ 阻塞/等待 `_chrome_restart_lock` 期间，watchdog（:915 同样通过检查）先完成 `full_chrome_restart` 并盖上新鲜时间戳 → nav 获得锁后**不再检查节流**，直接 `_kill_chrome_on_port` 杀掉刚启动的 fresh Chrome 再启一次 → 所有 CDP 页二度断连 + 二度 `cache.clear()`。穿越窗口 = 双方检查通过到首次时间戳落定（`ensure_chrome:207`，约 kill 0.5s + /json 探测）的 ~1-2s；nav×nav 变体不成立（单页 `_navigate_lock` 串行 + 30 次导航无法在 ~1s 内累积，计数器锁内清零又保证单启动者），因此仅 **watchdog(2h 周期)×nav 阈值** 交汇，约 0.2%/次、自愈（`_maybe_reconnect` 返回值 False 后 `navigate_stock:1115` 无条件 `_ensure_ws()` 重连新 Chrome，:1074-1077 注释成立——该自愈语义已核实 ✅）。
- 影响维度：线程安全 / 数据新鲜（CDP 不可用窗口翻倍 ~10-30s，无数据丢失，无资金/安全后果）。
- 修复方向（3 行）：`full_chrome_restart` 在 `_chrome_restart_lock` 内、`_kill_chrome_on_port` 之前重查 `if time.time() - _last_chrome_restart < _CHROME_RESTART_THROTTLE * 2: return False`（调用方已表达相同意图：watchdog:915、nav:1073）；若担心显式强制重启场景，可加 `force=False` 参数，`_maybe_reconnect`/watchdog 均传默认值。

**A1 确认（ok）**：计数器+阈值判断全部在 `_restart_counter_lock` 内、无 I/O（:1067-1072）；越阈线程在锁内清零 → **任意时刻只有一个启动者**；其余线程 return False。✅
**A2 确认（ok）**：`_last_chrome_restart=0`（:253）的语义无害——`ensure_chrome:207`（kill 后立即）重盖新时间戳，失败路径也不会滞留 0（stamp 先于 15s 探测），throttle 永不休眠；`full_chrome_restart→ensure_chrome` 为 RLock 重入无死锁。✅
**A3 确认（ok）**：锁序单向——`_reconnect_lock → _chrome_restart_lock`、`_navigate_lock → _restart_counter_lock`，无反向/无环，与既有锁纪律（budget 35s / `_close_budget` 5s / 硬上限 40）无冲突。✅

## Dim 3 — 资源与性能

**P2-2　cache.py:15-18 + config.py:20 + stock_api 池 500　缓存容量与 `MAX_DEDUP_CODES=2000` 预算不匹配**

- 命中反模式：容量数字与配置上限脱节（`MAX_CACHE_SIZE` 按 200 码×4 URL 推算，未对齐 dedup 池上限）。
- 证据链：`stream._refresh_pool` 每 L1 tick 将整个 dedup 池（上限 **2000** 码）× 3 字段喂入 handler——每 tick URL 工作集 ≈ 2000×2（basic_info, TTL120s 常驻）+ 2000×1（fundflow, TTL8s）+ 2000×1（timeline, TTL8s）= **8000 条不同 URL**，而 `MAX_CACHE_SIZE=2000`（FIFO 淘汰，`cache.py:53`）。当 dedup 池 >500 码时 URL 缓存命中率跌破合理线（全池 2000 码时约 25%），且 evict 使 8s 后同 URL 立即重取上游 → 每 tick 上游请求放大至 ~6000 条/8s，8 worker 并发，2C2G 上有 CLS 反封禁与 CPU 压力。同理 stock_api 码池（500 上限）在 2000 码 tick 下每 tick 淘汰 1500 码并 `cache.pop` → 命中率 ~25%。提交将 200→2000、300→500 是正确方向，但只够覆盖 ≤500 码池；注释里 "600-800 URL entries/tick" 的推算仅对 200 码成立。TTL 清扫（`_last_cache_sweep` 60s 一次）本身跟得上（dict 恒 ≤2000，sweep O(n)=廉价），瓶颈在容量而非清扫节奏。
- 影响维度：缓存合理 / 接口稳定（上游压力）/ 性能。
- 修复方向：二选一——① 将 `MAX_DEDUP_CODES` 与缓存预算绑定（如 cap 到 500 并注释线性预算表）；② 按 dedup 上限线性扩展 `MAX_CACHE_SIZE`/池上限并在注释中给出预算公式（2000 码 ≈ 60MB URL 缓存 + ~12MB 码池，仍可承受，但需显式声明）。

## Dim 4 — 安全

**P2-3　docker-compose.yml:16+8　`STREAM_HOST=0.0.0.0` + 8054 映射重新对外暴露无鉴权管理面**

- 证据链：stream 管理端点（POST/PATCH/DELETE 建组/改组/删组 + SSE 拉流）**全无鉴权**（`stream.py:317-381`）。上一轮 P1-4 以"默认绑 127.0.0.1"堵住的攻击面，本次 compose 为满足跨机消费者**显式**重新打开——属有意的部署选择，但 {网络可达 8054 的任意主机} 可创建 2000 码订阅组 / 批量 PATCH 触发大规模出站拉取（沿用 P1-4 论证的 DoS-by-subscription 放大器）。码数上限（MAX_CODES_PER_SUB=200 / MAX_DEDUP_CODES=2000）与 body 大小校验仍在，单请求被限，但多请求累积攻击面未恢复。
- 影响维度：安全（越权/资源滥用面，非数据泄露）。
- 修复方向：README 明确"8054 仅限可信内网" + 防火墙白名单说明；或管理端点加共享 token（环境变量）与 SSE 拉流分离鉴权；至少注解 compose 中的暴露意图。

## Dim 5 — 结构与可维护性

- `_read_json_body` 长度防护（297-307）：非数字/负数/超长 → 400，正确；缺失/`0` → 空 body `{}`，语义自洽。✅
- `timeout=30`（287-289）与 `_serve_sse` 内 `settimeout(40)`（405）交叉：管理请求读 `rfile` 全程受 setup() 施加的 30s 约束，SSE 写路径 40s 覆盖仅发生于 SSE 循环内；SSE 结束后 keep-alive 连接若被客户端空挂 >40s 会被断开（原 30s 同类行为），无新风险。✅
- 配置化：`STREAM_HOST` 走 env + compose，符合 arch-thinking 配置注册纪律；`_CHROME_RESTART_THROTTLE` env 化。✅
- 死代码/过度工程：未新增；`_broadcast` 在队列满时仍更新 `g.last_push_ts`（状态端点可能虚报最新推送时间）——既有问题，记录不阻塞。

## Dim 6 — 前端

无前端变更，跳过。

## 逆向审查（问题清单汇总）

| # | 等级 | 位置 | 问题 | 影响维度 |
|---|------|------|------|---------|
| 1 | P1 | cdp_engine.py:1073-1083 + server.py:915-922 | 节流守卫 TOCTOU（锁外检查/锁内不重查）→ watchdog×nav 并发窗口内背靠背 kill fresh Chrome | 线程安全/数据新鲜 |
| 2 | P2 | stream.py:151,169-172 | 有界队列丢新不丢旧，与 "next tick overwrites" 注释相反；慢客户端恢复后收 ≤64s 旧帧 | 数据新鲜 |
| 3 | P2 | stream.py:258-260 | destroy 哨兵满队列被吞 → 退出延迟 ≤60s，有界但未注释（前轮已接受） | 资源回收 |
| 4 | P2 | cache.py:18 + config.py:20 | 缓存容量 2000 / 池 500 vs MAX_DEDUP_CODES=2000 → 全池 tick 命中率 ~25%、上游放大 | 缓存合理/接口稳定 |
| 5 | P2 | docker-compose.yml:8,16 | 0.0.0.0 + 8054 重开无鉴权管理面（有意为之，需文档/白名单声明） | 安全 |
| 6 | P2 | README.md:63-72 | STREAM_HOST 新配置、8054 映射、loopback 默认未入文档 | 接口稳定/部署 |
| 7 | P2 | tests/test_stream.py | 丢帧方向、满队列哨兵、长度防护、节流跳过路径无新测试（46/46 为存量） | 规范/可维护 |

**未发现**：P0（无崩溃/数据丢失/资金/安全直通）、SQL/命令注入、明文凭据、越权直读。

## 漂移检测

- **对外 API 契约**：stream 端点签名/字段/事件格式零漂移；`_read_json_body` 收紧为 400 属协议兼容行为。❌ 无漂移。
- **配置契约**：新增 `STREAM_HOST`（默认 127.0.0.1）与 `CDP_RESTART_THROTTLE`（默认 15）两个 env 配置项；compose 新增 8054 映射。当前 README 环境变量表（:63-72）与 Docker 示例（:103-128）**未同步**。
- **`__DOC_SYNC__` 需求**：
  - `README.md` → 环境变量表补 `STREAM_HOST`（默认 127.0.0.1，注明"默认仅本机，跨机消费者需设 0.0.0.0 + 防火墙白名单"）；Docker 节补 `-p 8054:8054` 示例与 8054 安全说明。
  - `docker-compose.yml` 已含 `STREAM_HOST=0.0.0.0`，无需二次同步（建议注释暴露意图）。

## 修复建议（按优先级）

1. **【P1·合并前 3 行修复】** `full_chrome_restart` 在 `_chrome_restart_lock` 内、kill 前重查节流（见 Dim 2 修复方向）。
2. **【P2·顺手】** stream 队列 Full 时丢最旧保最新 + 修正注释（P2-1）。
3. **【P2·排期】** 缓存/池容量与 `MAX_DEDUP_CODES` 预算绑定或显式线性扩展（P2-2）；README env/8054 文档同步（P2-3）；compose 暴露面安全说明（P2-5）；补队列/长度防护/节流测试（P2-7）。

## 评审结论

**⚠️ 可合并（1 条低危 P1 建议先修）**：上一轮 3 处核心修复全部正确落地、锁纪律无冲突、无 P0；残留的节流 TOCTOU 概率极低且自愈，3 行可修，其余为 P2 记录项。