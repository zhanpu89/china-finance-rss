# Stream 传播修复复审（P5b）评审报告

- **CR 编号**：CR-2026-0915-stream-push-r1
- **评审对象**：feature/stream-push 分支修复轮（FIX-01 ~ FIX-05，相对分支 HEAD 的未提交改动）
- **评审模式**：修复轮复审（P5b）+ SIDE-EFFECT 逆向审计
- **评审人**：code-reviewer
- **日期**：2026-09-15

---

## 评审概要（总评）

**5 项修复全部可合并。** 核心修复方向正确且证据链成立：FIX-01（有界队列 + socket timeout + None 哨兵闭环）与 FIX-02（锁分离）经逐路径推演无 P0 级回归；FIX-03/04/05 无新问题。**1 条 P1**（FIX-02 引入背靠背双重启窗口，概率性、自愈，3 行可修）、**5 条 P2**（其中 3 条为申报描述不完整/既有问题记录，不阻塞）。未发现 P0。

> 评审方法说明：环境无 bash，无法执行 `git diff`。已按任务提供的 diff 摘要 → 直接读取工作区当前代码（即修复后代码）逐行核验，等价于对 diff 结果做评审。所有行号均指当前工作区文件。

---

## 一、5 项修复逐项验证

### FIX-01 — SSE 队列有界化 + socket timeout（stream.py）✅ 成立

**修复内容核对**（stream.py:151、:402-423）：

```python
self.q = queue.Queue(maxsize=8)                          # :151
self.connection.settimeout(STREAM_PING_INTERVAL * 2)     # :402 (40s)
while not conn.closed:                                   # :403
    frame = conn.q.get(timeout=STREAM_PING_INTERVAL)     # :405 (20s)
    if frame is None: break
    ...
except (BrokenPipeError, ConnectionResetError, OSError): # :417
```

**关键断言验证：**

1. **destroy 的 None 哨兵满队列丢失 → 退出延迟 ≤ ping 间隔**：✅ 成立。destroy（stream.py:254-261）置 `conn.closed = True` 后 `put_nowait(None)` 抛 `queue.Full` 被吞。但 handler 正阻塞在 `get(timeout=20)` 时，get 最多 20s 后超时 → 写 ping → `while not conn.closed` 循环头条件为 False → 退出。**退出延迟 = get 剩余超时 ≤ 20s = ping 间隔**。
2. **`settimeout(40)` 与 `get(timeout=20)` 无互相干扰**：✅。`q.get` 是线程级等待不走 socket；`settimeout` 只作用于 wfile 写调用。正常连接每 20s 写一次 ping，永触不到 40s 写超时。
3. **socket.timeout 被 :417 捕获**：✅。Python 3.3+ 中 `socket.timeout` 是 `OSError` 子类（3.10+ 即 `TimeoutError`），`except (BrokenPipeError, ConnectionResetError, OSError)` 完整覆盖。
4. **`except queue.Full` 从死代码变活代码**：✅。maxsize=8 下慢客户端 64s（8×8s tick/帧）未消费即满，`_broadcast` 的 `put_nowait` 真实抛满（stream.py:169-172）。

**⚠ 申报描述不完整（P2-1）**：destroy 遇上**写阻塞的慢客户端**时，退出延迟 = get 剩余（≤20s）+ write 阻塞（≤40s socket timeout）= **≤60s**，非申报的"≤ ping 间隔"。行为本身有界可接受（修复前为无界），但注释/申报应修正。

### FIX-02 — 锁分离（cdp_engine.py `_maybe_reconnect`）⚠ 1 条 P1

**修复内容核对**（cdp_engine.py:1054-1078）：

```python
with CDPPage._restart_counter_lock:          # 锁内：只计数+归零
    CDPPage._nav_restart_counter += 1
    if CDPPage._nav_restart_counter >= self._MAX_PAGE_NAV_BEFORE_RECONNECT:
        CDPPage._nav_restart_counter = 0
    else:
        return False
log.info(...)
full_chrome_restart(...)                     # 锁外
self._reconnect()                            # 锁外
return True
```

**复审重点 1 逐项裁决：**

| 问题 | 裁决 | 证据链 |
|------|------|--------|
| 两页同时跨阈值 double-restart？ | ✅ 不会 | A 拿锁后 counter 归零；B 随后拿锁 counter 0→1 → return False。counter 归零保证**单重启者**，与 `_chrome_restart_lock` 无关 |
| `_chrome_restart_lock` 能否保证单重启者？ | ⚠ 部分 | 它只保证并发 restart **串行**（RLock, cdp_engine.py:251），不阻止**背靠背第二**次 restart。见下方 P1 |
| 返回 True 页 `_reconnect()` 与并发 `full_chrome_restart` 冲突？ | ✅ 自愈 | `_reconnect`（:915-968）有 3 次尝试 + 45s retry window + `ensure_chrome()` 兜底；锁序无死锁（`_restart_counter_lock` 已释放 → `_chrome_restart_lock` → 实例 `_reconnect_lock`，无交叉持有） |
| 锁内 else:return False / 锁外 return True 边界漏检？ | ✅ 无 | ≥30 必然归零并走重启路径；<30 只计数。不存在"计数到 30 却未重启即返回 False"的路径 |

**⚠ P1-1（新引入的 SIDE-EFFECT）：restart 窗口内计数继续累积 → 背靠背双重启**

- **触发链**：A 页在锁外执行 `full_chrome_restart`（4-24s，:1075），期间**其他页面每次导航仍会累加 counter**。若窗口内累计 30 次导航（5 个 CDP 页 × 各 6 次导航，loadtest/多用户场景可达），B 页触发第二次。B 阻塞在 `_chrome_restart_lock` 等 A 完成后，**无条件 kill Chrome（cdp_engine.py:252）——把 A 刚启动的 Chrome 杀掉**，再做一次完整重启。期间 CDP 端到端不可用窗口 = A 重启 + B 重启 ≈ 8-48s。
- **对比旧代码**：旧实现 restart 全程持 `_restart_counter_lock`，其他页阻塞在锁上、restart 后各自仅 +1，背靠背概率显著更低。**本修复把 restart 移出锁，等价于放大了该窗口** —— 这是 FIX-02 引入的新 SIDE-EFFECT。
- **自愈性**：✅。第二次 `full_chrome_restart` 内 `_last_chrome_restart = 0`（:253）先于 `ensure_chrome()`，绕过了 15s throttle（:196），最终 Chrome 必然活着。非永久故障，属功能/性能退化级。
- **修复建议（3 行）**：`_maybe_reconnect` 重启前加 throttle 守卫：

  ```python
  # 重启门槛前检查：上一轮重启若在 throttle 窗口内，跳过 full restart 直接重连
  if time.time() - _last_chrome_restart < _CHROME_RESTART_THROTTLE * 2:
      self._ensure_ws()
      return True   # 计数已归零，语义为"本轮已处理"
  full_chrome_restart(...)
  ```
  同守卫同时覆盖 `server.py:910 _cdp_memory_watchdog`（7200s 一次，与 `_maybe_reconnect` 并发同样背靠背）——P2-2 一并消除。

### FIX-03 — stream 服务绑 127.0.0.1（stream.py:430）✅ 成立

`BoundedThreadPoolServer(('127.0.0.1', STREAM_PORT), ...)`。SSE 管理端点（POST/PATCH/DELETE，无鉴权）暴露于 0.0.0.0 是真实安全问题（任何可达主机可建订阅/删组），本修复方向正确。`tests/test_stream.py` 全部经 `127.0.0.1` 连接（:141/:170/:178/:203），不破坏测试。

**⚠ P2-3**：`STREAM_HOST` 未配置化。本项目为单进程单容器形态（`main()` 同进程起 stream server，server.py:943-945），绑 loopback 合理；但若未来 SSE 消费方跨主机（反代分置），需改代码。建议 `STREAM_HOST = os.getenv('STREAM_HOST', '127.0.0.1')` 保留灵活性，不阻塞本次合并。

### FIX-04 — `_read_json_body` 边界加固（stream.py:293-304）✅ 成立

**输入路径全部核查**（调用方 `do_POST`/`do_PATCH` 均只判 `None → 400`）：

| 输入 | 修复后行为 | 调用方结果 |
|------|-----------|-----------|
| CL 缺失 | `or 0` → `{}` → `create_group` 报 'codes required' | 400 ✅ |
| CL=0 | 同上 | 400 ✅ |
| CL 负数 | `None` | 400 ✅ |
| CL 非数字（'abc'/'1.5'） | `ValueError` → `None` | 400 ✅ |
| CL > 65536 | `None` | 400 ✅ |
| body 非 JSON / 非法 UTF-8 | `except Exception` → `None` | 400 ✅ |

`None` 与 `{}` 两条路径最终都到 400，语义等价。无新问题。

**⚠ P2-4（既有问题记录）**：management 端点 `rfile.read(length)` 无读取超时（`StreamHandler` 未设 `timeout` 属性，settimeout 只在 SSE 分支 :402 设置；`BaseHTTPRequestHandler` 默认 `timeout=None`）。声明 `CL=65536` 只发 1 字节的挂起连接可占住线程池（max_workers = MAX_STREAM_CONNS+10 = 110）——为既有慢速请求 DoS，非本修复引入。建议 `StreamHandler.timeout = 30`（或 settimeout）。不阻塞。

### FIX-05 — 缓存/池容量上调（cache.py / config.py）✅ 成立

**内存评估（2C2G）：**
- URL 缓存 2000 条 × ~10KB ≈ **20MB**（cache.py:15-18 注释自估）。相对 Chrome 渲染器（`--max_old_space_size=512`/renderer，实测 ~1.5GB 常驻）+ Python ~150MB，增加 <2%，**在预算内**。
- pool 500：fundflow/timeline/basic_info=500（config:121-127），f10/announcement=300 未动。各 pool 为 LRU **上限而非预分配**，仅当 500 个不同股票被访问才填满。每 pool 条目量级：fundflow ~5-20KB、timeline ~5-15KB、basic_info ~3-5KB。满额全池粗估 **~25MB**，较 300 档增 ~10MB。合计新增 ~30-35MB，**2C2G 可接受**。

**性能评估：**
- **LRU 淘汰 O(n) 放大 ⚠ P2-5**：cache.py:52-54 `oldest = min(d, key=...)` 在 `_cache_lock` 内做 **O(2000) 全扫描**（修复前 O(200)）。stream tick 每 8s 触碰 600-800 URL（2000 dedup codes × 4 variants 热子集）→ 每轮 tick 约 600 次 `_cache_put`，满期每次淘汰 O(2000) → 每轮额外 **60-120ms 锁内开销**（占 tick 的 ~2%，同时阻塞所有 fetch_json 读路径）。量级可接受，不构成 P1，但建议 `OrderedDict` + `move_to_end` 使淘汰 O(1)，或每 N 次 put 淘汰一次。
- **`_sweep_expired` 扫描**：60s 一次 O(2000) 线性扫描 ≈ 100µs-1ms 锁内，✅ 可忽略。
- **prefetch 覆盖率摊薄 ⚠ P2-6**：`_fundflow_prefetch_loop` 每 pass 受 `_PREFETCH_PASS_BUDGET=60s` 截断 + round-robin cursor（stock_api.py:64-78、:319-343）。pool 500 使单码刷新间隔从 ~125s 摊薄至 ~208s，**超过 `_MAX_CACHE_AGE=120s`**（stock_api.py:159）→ 冷码请求时 miss 补抓（走 fetch_json ttl=L1=8s → 上游）。功能正确，温和权衡，不强制同步调 `_FUNDFLOW_POOL_REFRESH` 等。

**跨文件（复审重点 5）：** 4 个 prefetch loop 的间隔常量无需同步调整——轮转+预算结构自适应容量，摊薄效应已上述量化为温和。✅

---

## 二、SIDE-EFFECT 逆向审计（修复是否引入新破坏）

| 修复 | 受影响点 | 逆向假设 | 裁决 |
|------|---------|---------|------|
| FIX-01 | SSE 连接生命周期 / destroy 退出 | 谁依赖旧无界队列？无（内部仅 `_SSEConn`）。谁依赖旧无超时 write？无（旧行为即缺陷）。`send_response/end_headers` 均在 settimeout 之前完成 ✅ | **无破坏** |
| FIX-02 | `_maybe_reconnect` 调用方 `navigate_stock:1106` | Tensor：True/False 后均走 `_ensure_ws()`，返回语义不变 ✅；并发窗口放大 → **P1-1** | **1 个 SIDE-EFFECT（P1-1）** |
| FIX-03 | stream 监听地址 | 测试全部连 127.0.0.1 ✅；同机消费场景充裕；跨主机 SSE 消费方断联 → **P2-3** | **无破坏（1 条部署假设记录）** |
| FIX-04 | do_POST/do_PATCH | `None` 与 `{}` 均收敛到 400 ✅ | **无破坏** |
| FIX-05 | URL 缓存 / 各 stock pool | 各 handler 不感知容量（`_handle_cached_batch` 只读 pool_max）✅；内存 +30MB 在预算内 ✅ | **无破坏** |

---

## 三、契约变化确认

- `doc/detailed/` 不存在（仅 doc/review、doc/tester 有产出）→ **Dim 0 契约一致性核对跳过**（🐛/🟢-light 常见情形）。
- **代码面核查**：5 项修复均只改内部常量/内部行为（队列上限、socket timeout、锁粒度、绑定地址、缓存容量），**无对外 API 签名、URL、字段、SSE 事件格式变化**。
- **code-developer 申报"无 DOC_SYNC"属实** ✅。唯一值得商榷的是 FIX-03 绑定地址从 0.0.0.0 收窄到 127.0.0.1 —— 属部署行为变化但无契约文档记载过 0.0.0.0，不构成契约漂移；已在 P2-3 记录供编排层知情。

---

## 四、问题清单

### P0
无。

### P1（1 条 — 建议合入前修复，不阻断）

**【P1-1】cdp_engine.py:1075 — FIX-02 引入背靠背双重启窗口**
- 描述：`_maybe_reconnect` 把 `full_chrome_restart`（4-24s）移出 `_restart_counter_lock` 后，重启窗口内其他页面的导航计数持续累积；若窗口内累计 30 次（多页并发场景），第二个页面在 `_chrome_restart_lock` 上等待 A 完成后**无条件 kill 刚启动的新 Chrome 再重启一次**，CDP 不可用窗口翻倍至 8-48s。`full_chrome_restart` 内部先将 `_last_chrome_restart = 0` 绕过 15s throttle（:253/:196），无 throttle 兜底。
- 概率：低（需窗口内 30 次导航），自愈（最终 Chrome 必然存活），属功能/性能退化级。
- 修复方向：重启前检查 `time.time() - _last_chrome_restart < _CHROME_RESTART_THROTTLE * 2` → 跳过 full restart，仅 `_ensure_ws()` 后返回 True（计数已归零，语义自洽）。同一守卫覆盖 `server.py:910` watchdog 并发场景。

### P2（5 条 — 记录，不阻塞）

**【P2-1】stream.py:402-417 — FIX-01 申报"退出延迟 ≤ ping 间隔"不完整**
- destroy 逢队列满 + 慢客户端写阻塞场景下，退出延迟 = get 剩余（≤20s）+ socket write 超时（≤40s）= **≤60s**。行为有界可接受（修复前无界），修正注释/申报描述。

**【P2-2】server.py:910 — watchdog 与 `_maybe_reconnect` 并发 full_chrome_restart 同源背靠背**
- 与 P1-1 同根因（restart 无 throttle 语义），由 P1-1 的守卫一并消除。

**【P2-3】stream.py:430 — `STREAM_HOST` 未配置化**
- 绑 127.0.0.1 正确且与测试一致，但跨主机 SSE 消费方（若部署拓扑分置）将断联。建议 `STREAM_HOST = os.getenv('STREAM_HOST', '127.0.0.1')`。

**【P2-4】stream.py:293-304 — management 端点无读取超时（既有）**
- 声明大 Content-Length 但挂起的连接可占满线程池（max_workers=110）。建议 `StreamHandler.timeout = 30`。非本修复引入。

**【P2-5】cache.py:52-54 — LRU 淘汰 O(n) 扫描放大 10×**
- `min(d, key=...)` 在 `_cache_lock` 内 O(2000) 全扫描，stream tick 峰值每轮追加 ~60-120ms 锁内开销。建议 `OrderedDict`/`move_to_end` O(1) 化或降低淘汰频率。

**【P2-6】config.py:121-127 / stock_api.py:316-343 — pool 500 摊薄 prefetch 单码刷新间隔（~125s→~208s > `_MAX_CACHE_AGE`=120s）**
- 冷码请求时 miss 补抓，功能正确、上游请求温和上升。记录知情，不强制调整刷新间隔。

---

## 五、结论

**本次 5 项修复可合并（Accept）。**

- 无 P0，修复未引入数据/资金/安全级回归；
- 1 条 P1（背靠背双重启窗口）为**概率性且自愈**的功能退化，提供 3 行修复建议，建议在合入前顺手修掉（低风险），不阻断合并；
- 5 条 P2 全部记录在案，无阻断项；
- 契约无变化：无 DOC_SYNC 申报属实。
- 后续建议：`python -m unittest discover -s tests -v` 回归（test_stream.py 覆盖 SSE 相关路径）；`check-review.sh` 门禁通过后由编排器 dispatch 处理 P1-1 或登记待办。