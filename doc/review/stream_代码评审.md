# stream 代码评审报告

- **CR 编号**：CR-20260915-001
- **版本**：feature/stream-push（SSE 流推送子系统，组A）
- **状态**：⚠️ 有条件合并（无 P0；4×P1 需生产前修复）
- **评审模式**：code-reviewer 常规评审（P5b）
- **日期**：2026-09-15
- **关联文档**：doc/tester/stream_测试报告_r1.md（无 doc/detailed/ 详设）

## 一、评审概要

SSE 流推送子系统整体架构正确：独立端口 + 独立线程池隔离长连接、_groups_lock(RLock) 嵌套获取安全、SSE 帧格式/ping/keep-alive 协议合规、CRUD 校验完备、空闲零成本。**风险集中在三处**：
1. **慢客户端内存无界增长**（P1-1，最危险）：队列无界 + `queue.Full` 是死代码 + SSE 写无 socket 超时，2C2G 上可被少数停滞客户端拖至 OOM；
2. **大码池每 tick 全量回源放大**（P1-2）：设计宣称"zero extra upstream load"只在码池 ≪ 缓存池容量（300-500）时成立，全量订阅 2000 码时约 1000 req/s 出站，且挤占 REST 路径共享缓存；
3. **未鉴权 + 绑 0.0.0.0**（P1-4）与 P1-2 相乘 = 任意网络可达者可驱动上游封禁（DoS-by-subscription）。

结论：**可以合并进 main，但生产部署前必须修复 P1-1 ~ P1-4**；P2 全部记录不阻断。

### 受影响点与逆向假设（入参无 >>SIDE-EFFECT: 标记，由 diff 推断）

| 受影响点 | 模块 | 逆向假设 | 结论 |
|---|---|---|---|
| server.py main() 新增 2 线程 | 主服务启动 | run_stream_server 端口 8054 被占 → OSError 未捕获 → daemon 线程静默死亡 | **成立**（P2-9）；push_loop 空闲零负载，不成立 |
| config.py 新增 4 项 | 配置 | env 覆盖 + 默认值，向后兼容 | 不成立，无破坏 |
| stock_api 三 handler 的 pool/cache | 数据层 | 2000 码每 tick touch + 驱逐 → REST 路径缓存命中率下降 | **成立**（并入 P1-2） |
| BoundedThreadPoolServer 复用 | 通用 | stream 池 110 worker，100 SSE 长期占用 → 管理端点突发 503 | 有界成立，属设计内负载保护，记录不阻塞 |

## 二、评审范围

- stream.py（新增 430 行）
- server.py 集成段（main() 920-982、BoundedThreadPoolServer 801-861，只读未改）
- config.py STREAM 配置项（9/17-20）
- tests/test_stream.py（新增 267 行）
- 关联只读：stock_api.py（_handle_cached_batch/_process_chunk/fetch_*/handle_cls_basic_infos）、cache.py（fetch_json）

## 三、问题清单

| ID | 等级 | 位置 | 问题 | 阻断 |
|----|------|------|------|------|
| P1-1 | P1 | stream.py:148,166-169,393-406 | 无界队列 + `queue.Full` 死代码 + SSE 写无超时 → 慢客户端内存无界增长 | 生产阻断 |
| P1-2 | P1 | stream.py:105-120,179-182；config.py:126-127；cache.py:15 | 大码池每 tick 全量回源放大 + 缓存踩踏 + 死线丢码 | 生产阻断 |
| P1-3 | P1 | stream.py:290-298 | Content-Length 负数/非数字 → 读阻塞悬挂 worker / 未捕获异常 | 生产阻断 |
| P1-4 | P1 | stream.py:420 | 绑 0.0.0.0 + 无鉴权 → DoS-by-subscription（与 P1-2 相乘） | 生产阻断 |
| P2-1 | P2 | stream.py:376-413 | SSE 握手期 destroy 竞态 → 孤儿连接挂起占名额 | 记录 |
| P2-2 | P2 | stream.py:363-364 | PATCH 后 get_group 竞态 → AttributeError 500 | 记录 |
| P2-3 | P2 | stream.py:238 | 组上限未对 add 去重 → 重复码被误拒 | 记录 |
| P2-4 | P2 | stream.py:80-88 | fields 全非法 → 静默订阅全部字段（成本放大） | 记录 |
| P2-5 | P2 | stream.py:173-188 | push_loop 逾期无收拢策略 → 帧陈旧/连续压测 | 记录 |
| P2-6 | P2 | stream.py:67-69 | payload_bytes 死代码，估算值失实 | 记录 |
| P2-7 | P2 | stream.py:155-170 | 空连接组每 tick 仍 json.dumps 建帧 | 记录 |
| P2-8 | P2 | tests/test_stream.py | 慢客户端/断开回收/畸形 Content-Length/destroy 竞态无测试；:261-263 死代码 | 记录 |
| P2-9 | P2 | stream.py:424-430 | 端口冲突 OSError 未捕获 → 线程静默死亡无恢复 | 记录 |

## 四、问题详情

### Dim 0 — 契约一致性

`doc/detailed/` 下无 stream 模块详设 → **跳过**（无契约基准，接口仅以 stream.py 模块 docstring 自证——模块注释声称 "zero extra upstream load"，与实现不符，见 P1-2）。无 DOC_SYNC 输出。

### Dim 1 — 数据与正确性

- **P1-3（命中：宽泛/缺失输入校验）** 当 {Content-Length 为负数或非数字} 时，会 {worker 线程悬挂在 `rfile.read(-N)` 读至 EOF，或无捕获的 `ValueError` 使连接异常关闭}，因为 `stream.py:291` 的 `int(...)` 未捕获、`:294` 的 `read(length)` 未校验负数，且 StreamHandler 未设 socket 超时（ThreadingHTTPServer 默认 timeout=None）。单请求即可永久占用一个 worker，110 池可被 110 个此类请求耗尽（管理端点 503）。**修复**：`try/except (ValueError, TypeError)`，`length < 0 or length > 65536 → 400`，并在 `__init__`/`_serve_sse` 设 `self.connection.settimeout(...)`。
- **P2-3（命中：边界计算错误）** `patch_group` 的 `len(g.codes) + len(add) - len(set(remove))` 未对 add 去重/排除已存在码：当 {add 含重复码或组内已有码} 时，会 {误报 400 too many codes}，因为 :238 用原始 `len(add)`。**修复**：`len((g.codes | set(add)) - set(remove))`。
- **P2-4（命中：隐式状态转换）** `_valid_fields` 对"请求字段全非法"回退为订阅全部 → 当 {客户端传 `fields:["bogus"]`} 时，会 {静默订阅全 3 字段，放大每 tick 负载与带宽}。**修复**：全非法返回 400；`fields` 缺省才默认全量。
- **P2-2（命中：不检查空值/可选）** `do_PATCH` 在 `patch_group` 成功后重新 `get_group`，当 {并发 destroy 恰在此窗口} 时，`g` 为 None → `g.codes` AttributeError 500。**修复**：None → 404。
- **P2-6（命中：死代码）** `payload_bytes()` 全代码库无调用方；估算 70KB/码 与真实帧偏差大（quote 0.5-2KB/码、timeline 全序列可达 5-20KB/码）。**修复**：删除或接入日志/监控。

### Dim 2 — 并发

- **P1-1（命中：内存无限增长 + 线程阻塞无超时）** `_SSEConn.q = queue.Queue()` 无 maxsize（:148），`put_nowait` 永不抛 Full——`:167-169` 与 `:254-257` 的 `except queue.Full` 为死代码。当 {客户端停滞（TCP 写缓冲满）} 时，handler 线程阻塞在 `wfile.write`（:398-402，无超时）不再排空队列，队列按 tick 积压一帧；大 timeline 组帧可达 MB 级，若干慢客户端 × 数小时 = 2C2G OOM。**修复**：① `queue.Queue(maxsize=8)`，Full 时丢一帧（行情可接受丢帧，需一并处理 destroy 醒哨兵 None 在满队列被丢时的 ≤ping 间隔退出延迟）；② `_serve_sse` 循环前 `self.connection.settimeout(STREAM_PING_INTERVAL * 2)`（socket.timeout 属 OSError，被 :407 捕获）。
- 已确认安全项：`_groups_lock` 用 RLock 且嵌套（`_new_sid`/`_deduped_codes_unlocked`）无死锁；`_broadcast` 组列表在锁内拷贝、组对象本地引用，destroy 后迭代空 conns 集合安全；`conn.closed` 读写无锁但 GIL 下 bool 原子，最坏多投一帧（无害）；`_register_conn`/`_release_conn` 成对加锁；`patch_group` 对 `g.codes` 引用替换（非原地变更），`_build_frame`/`_deduped_codes_unlocked` 并发迭代旧对象安全。
- **P2-1（命中：未同步的共享可变状态窗口）** 当 {destroy_group 恰在 `_serve_sse` 的 `g.conns.add(conn)` 之前完成 pop+clear} 时，conn 挂入已脱离 `_groups` 的孤儿组 → 只收 ping、`_conn_count` 不归还，直到客户端自行断开。**修复**：add 后复查 `sid in _groups`，否则 discard + `_release_conn()` + 关闭连接。

### Dim 3 — 资源与性能

- **P1-2（命中：缓存穿透/击穿视角的周期性全量回源 + N+1 类放大）** `_refresh_pool` 每 tick 将去重池（至 2000 码）整池喂给 3 个 handler（:113-119），而：内存池容量 `_BASIC_INFO_MAX_POOL=300`/fundflow 500/timeline 300（config.py:121-127）逐 tick 驱逐超出部分；URL 级缓存 `MAX_CACHE_SIZE=200`（cache.py:15）在 8000 URL/tick 的冲刷下命中率趋零；fundflow/timeline fetch 的 ttl=L1=8s（stock_api.py:268,360）等于 tick 间隔。当 {订阅满 2000 码} 时 → 每 8s ≈2000 码 × 3 字段（basic 含 basic+detail 两请求）≈ **6000-8000 次出站请求 ≈ 1000 req/s 持续**，触发 cls.cn 反爬封禁风险（本库专门为此建了 CDP fallback）。同时 `handle_cls_basic_infos` 内置 60s 死线（stock_api.py:674）与 8s tick 不匹配：40 个顺序 chunk 超时后尾块返回 None → 帧缺码（静默）。另：2000 码对 3 个 pool 每 tick touch+驱逐，把 REST 扫描路径最近查看的股票挤出缓存 → 主服务上游请求增加。**修复**：① refresh 改预算制——每 tick 只刷旋转子集（复用 `_prefetch_rotate` 的 round-robin + pass-budget 模式），快照=上一轮结果；② 或按码池规模比例放大 pool/URL 缓存容量；③ 至少将 basic_infos 死线与 push 周期对齐（如 deadline=8s，超时用旧缓存）。
- **P2-5** 当 {单轮 refresh+broadcast 超过 tick 间隔} 时，`delay ≤ 0` → 不 sleep 立即下一轮（:183-185），push_loop 变 work-bound 连转，帧持续陈旧且无喘息。修复：逾期时跳过本周期（`nxt = time.time() + tick` 重新对齐）或 `sleep(1)` 降频。
- **P2-7** `_broadcast` 对零连接组仍做 json.dumps 并更新 last_push_ts（:158-170）——每 tick 白耗。修复：`if not g.conns: continue`（锁内快查）。
- 已确认安全项：push_loop 无组时零成本（`if codes:` 短路）；`fetch_json` 有 leader-election 单飞 + `_fallthrough_sem(2)` 兜底，回源不会雪崩式叠加；SSE 线程池 daemon 化，退出不残留。

### Dim 4 — 安全

- **P1-4（命中：越权/未鉴权管理面 + 攻击面暴露）** `make_stream_server(('', STREAM_PORT))` 绑所有接口（:420，日志却自称 localhost）；POST/PATCH/DELETE/SSE 全无鉴权。当 {网络可达者} 时 → 可创建 2000 码订阅组，经 P1-2 放大为 ~1000 req/s 出站：上游封禁 + 本机线程/内存耗尽（DoS-by-subscription）。**修复**：默认绑 `127.0.0.1`（与日志自述一致），或管理端点加共享 token 校验（环境变量注入，与主服务鉴权模型对齐后统一）。
- 已确认安全项：sid 仅作 dict 键，`rsplit` 解析无路径穿越；`code` 全部过 VALID_STOCK_CODE；`_read_json_body` 有 65536 上限（正方向）；SSE 输出无敏感字段透出（仅行情数据）。

### Dim 5 — 结构与可维护性

- 正向：模块内聚清晰（连接/广播/CRUD/HTTP 分层），复用 `BoundedThreadPoolServer` 与 `_handle_cached_batch` 既有入口，未重复造轮子——**符合 arch-thinking 第三关**。
- **P2-8** 测试缺口：SSE 断开后 `_conn_count` 归零、慢客户端/队满行为（P1-1 修复后需配套）、畸形 Content-Length、destroy 竞态均无用例；`tests/test_stream.py:261-263` 的 `_json()` 为死代码。已覆盖项质量良好：`BatchShardingTests`（P1-6 分片回归，驱动真实 handler）价值高。
- **P2-9** `run_stream_server` 端口冲突 → OSError 未捕获 → daemon 线程静默死亡，主服务继续运行而 SSE 静默缺失。修复：捕获 OSError 记 ERROR 日志。

### Dim 6 — 前端

不适用（纯后端变更）。

## 五、修复建议

**P1 修复顺序**（全部低侵入、数行级）：
1. P1-1：`queue.Queue(maxsize=8)` + `_serve_sse` 设 settimeout（stream.py:148,393）；同步调整 destroy 醒哨兵满队列降级路径。
2. P1-3：`_read_json_body` 捕获 ValueError + 拒绝 length<0（stream.py:290-294）。
3. P1-4：默认绑 127.0.0.1 或加 token（stream.py:420）。
4. P1-2：refresh 改旋转预算制（stream.py:105-120,179-182），配置化每 tick 刷新上限。

**P2**：修 P2-1~P2-4 每个均 ≤5 行；P2-5/6/7/9 随手清理；P2-8 随 P1-1 修复补测试。

## 六、评审结论

⚠️ **无 P0，但 P1=4（>2）**。可合并进 main（代码整体方向正确、协议合规），**生产版前必须修复 P1-1~P1-4**；其中 P1-1 若该服务将暴露于公网/移动弱网环境，建议按 P0 处理（OOM 崩溃风险）。

### 变更记录

- 2026-09-15：首评（P5b 常规评审，无 P7 漂移合并模式、无 >>SIDE-EFFECT: 入参）。

## 项目约定回写标记

>>PROJECT: 服务边界 → 长连接服务（SSE）独立端口 + 独立 BoundedThreadPoolServer 线程池，与主 HTTP 服务隔离，避免长连接饿死主 worker 池
>>PROJECT: 缓存接入 → 批量 codes 数据读取统一走 stock_api._handle_cached_batch 分片接入（≤_MAX_BATCH_SIZE，分片不截断），模块内禁止绕过缓存层直接 fetch（_handle_cached_batch docstring 与 3 个 handler 佐证）