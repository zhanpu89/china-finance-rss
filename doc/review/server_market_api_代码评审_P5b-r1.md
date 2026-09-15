# 代码评审报告（P5b 修复轮 r1）

| 项目 | 值 |
|------|-----|
| CR 编号 | CR-20260914-001 |
| 版本 | r1 |
| 状态 | 完成 |
| 评审模式 | P5b 修复轮评审 + P7a 漂移检测（`>>MODE: review+drift`） |
| 日期 | 2026-09-14 |
| 评审范围 | server.py (+8/-1), market_api.py (+1/-1) |
| 关联文档 | 无详设（doc/detailed/ 为空），Dim 0 跳过 |

---

## 一、评审概要

**结论：✅ 通过 — 3 项修复均正确落地，未引入新缺陷。**

3 个修复均为健壮性改善（try/except、log.warning、min 防越界），改动精准，未改变响应格式或状态码，不影响端契约。建议进入测试。

| 等级 | 数量 | 说明 |
|------|------|------|
| P0 | 0 | — |
| P1 | 0 | — |
| P2 | 1 | 观察项（不阻塞） |

---

## 二、评审范围

**后端文件：**
- `server.py` — handle_ths_kuaixun (L125-128) + _handle_stock_batch (L636-640)
- `market_api.py` — _transform_margin (L71)

**前端文件：** 无

---

## 三、问题清单

| ID | 等级 | 文件:行号 | 问题描述 | 阻断 |
|----|------|-----------|----------|------|
| F-1 | P2 | market_api.py:71 | `_transform_margin` 长度不一致时无日志，静默丢弃多余数据 | 否 |

---

## 四、问题详情

### Dim 1 — 数据与正确性

#### P1-1 修复验证：THS ctime try/except fallback

**位置：** `server.py:125-128`

```python
try:
    ctime = int(item.get('ctime', 0))
except (ValueError, TypeError):
    ctime = int(time.time())
```

**评估：✅ 正确**

- **异常类型精确**：`(ValueError, TypeError)` 覆盖了 `int()` 的两种失败模式——`ValueError`（非数字字符串如 `"abc"`、`""`）和 `TypeError`（`None`、列表等非标量类型）。`item.get('ctime', 0)` 在 key 存在但 value 为 `None` 时返回 `None`（不是默认值 `0`），`int(None)` 抛 `TypeError` → 被捕获。✅
- **Fallback 安全**：`int(time.time())` 产生合法 Unix 时间戳，`timestamp_to_rfc822()` 底层调用 `formatdate(timeval=ts)` 正确处理。✅
- **与 eastmoney handler 风格一致**：`handle_eastmoney_kuaixun` (L99-102) 对 `showtime` 用 `parse_china_datetime_to_rfc822` + `except Exception` + `formatdate` fallback。THS 用更精确的异常类型 `(ValueError, TypeError)` + `timestamp_to_rfc822` fallback。两者策略相同（解析失败→当前时间），THS 的异常捕获更窄更精准。✅
- **逆向假设验证**：当 `ctime` 为合法字符串数字（如 `"1726329600"`）→ `int()` 成功，不进 except。当 `ctime` 为 `"0"` → `int("0") = 0`，`timestamp_to_rfc822(0)` 返回 1970-01-01（虽然异常但不崩溃，属于上游数据问题）。✅

**无遗漏调用点：** `handle_ths_kuaixun` 中唯一需要 `int()` 转换的字段是 `ctime`。`seq` 仅用于 GUID 字符串拼接，`title`/`digest`/`url` 均为字符串直传。

#### P1-2 修复验证：批次截断 log.warning

**位置：** `server.py:636-640`

```python
if len(stock_codes) > _MAX_BATCH_SIZE:
    dropped = stock_codes[_MAX_BATCH_SIZE:]
    log.warning(f'Batch truncated: {len(dropped)} codes dropped, '
                f'samples={dropped[:3]}')
    stock_codes = stock_codes[:_MAX_BATCH_SIZE]
```

**评估：✅ 正确**

- **日志仅在截断分支执行**：`log.warning` 在 `if len > _MAX_BATCH_SIZE` 内部，正常路径（≤50 codes）不触发。✅
- **响应格式不变**：截断后 `stock_codes` 传入 `handler(stock_codes)`，返回 JSON 结构与之前一致（只是 codes 数量从 >50 变为 50）。状态码仍为 200。✅
- **`dropped[:3]` 安全**：即使 `dropped` 为空也不会报错（空列表切片返回空列表）。✅
- **与 stock_api.py 防御重叠无害**：`stock_api.py:129-130` 也有 `_MAX_BATCH_SIZE` 截断作为防御。server 层截断在前，stock_api 层截断是 defense-in-depth，不会触发但也无副作用。✅

#### P2-14 修复验证：margin dates/items min 长度

**位置：** `market_api.py:71`

```python
n = min(len(dates), len(items))
return {
    'latest': fmt(n - 1) if n > 0 else None,
    'recent': [fmt(i) for i in range(max(0, n - 30), n)],
}
```

**评估：✅ 正确**

- **空集合安全**：`dates=[]` 或 `items=[]` → `n=0` → `latest=None, recent=[]`。✅
- **None 值安全**：`data.get('date') or []` 和 `data.get('item') or []` 在 L48-49 处理了 `None`/缺失情况。✅
- **长度不一致**：`dates` 有 5 个、`items` 有 3 个 → `n=3` → 只处理前 3 个。多余的 dates 被丢弃（合理，因为无对应数据）。反向情况同理。✅
- **`n-1` 安全**：`if n > 0` 保护了 `n=0` 时 `fmt(-1)` 的越界风险。✅

---

### 逆向审查（P5b 强制）

**SIDE-EFFECT 1 逆向：THS ctime fallback 时间戳**

| 逆向假设 | 结论 |
|----------|------|
| fallback 时间戳会破坏 RSS 订阅者排序？ | **不成立** — RSS 订阅者通常按 pubDate 排序，单条 item 出现当前时间仅在 ctime 数据损坏时发生，属于异常数据的合理降级。其他正常 item 的排序不受影响。 |
| 修复会掩盖上游数据质量问题？ | **不成立** — 修复前是整 feed 500 崩溃，修复后是单条 item 带 fallback 时间 + 其余正常。降级优于崩溃，且 log 可观测。 |

**SIDE-EFFECT 2 逆向：截断 log.warning**

| 逆向假设 | 结论 |
|----------|------|
| log.warning 是否影响响应格式/状态码？ | **不成立** — `log.warning` 是副作用（写日志），不影响控制流或返回值。响应体仍是 handler 返回的 JSON，状态码 200。 |
| 日志是否误伤正常路径？ | **不成立** — 仅在 `len > _MAX_BATCH_SIZE` 分支内执行。 |

**SIDE-EFFECT 3 逆向：margin min(len) 静默丢弃**

| 逆向假设 | 结论 |
|----------|------|
| 静默丢弃多余数据是否破坏下游消费者？ | **不成立** — 下游（前端/小程序）按 `recent` 列表遍历，长度缩短不影响结构。原来 IndexError 导致整批降级为 `{_error}` 更糟。 |
| `items` 为 `None` 时 `min(len)` 是否安全？ | **不成立** — L49 `data.get('item') or []` 保证 `items` 永远是 list。 |
| `dates` 为 `None` 时 `min(len)` 是否安全？ | **不成立** — L48 `data.get('date') or []` 同理。 |

---

### Dim 2-5 — 其他维度

- **Dim 2（并发）：** 无新增并发问题。改动不涉及共享状态。
- **Dim 3（资源与性能）：** 无新增资源泄漏或性能问题。`log.warning` 在错误路径执行一次，开销可忽略。
- **Dim 4（安全）：** 无注入/越权风险。日志仅输出 dropped codes 的前 3 个 sample（公开股票代码，非敏感信息）。
- **Dim 5（结构与可维护性）：** 无新增上帝对象/过度工程。

---

### F-1 观察项（P2，不阻塞）

**位置：** `market_api.py:71`

**描述：** `_transform_margin` 在 `len(dates) != len(items)` 时静默截断到 min 长度，无日志输出。与 `server.py:_handle_stock_batch` 的 `log.warning` 风格不一致——后者在截断时记录了 warning。

**影响：** 不影响功能正确性，但数据长度不一致属于异常上游响应，无日志会增加运维排查难度。

**建议（不阻塞）：** 可在 `_transform_margin` 中加 `log.warning` 记录长度不一致情况，与 server.py 的 P1-2 修复风格对齐。非阻塞，可后续优化。

---

## 五、修复建议

**P0：** 无

**P1：** 无

**P2（观察项）：**
- F-1：`_transform_margin` 长度不一致时建议加 `log.warning`，提升可观测性。

---

## 六、评审结论

**✅ 通过 — 3 项修复均正确落地，未引入新缺陷，未破坏端契约。1 个 P2 观察项不阻塞。**

---

## 漂移检测

### D1 契约核对

- **doc/detailed/ 为空**，无详设 OpenAPI 契约可供核对。本次修复均为内部健壮性改善，未改变接口路径、方法、字段名或类型。✅ 无漂移。

### D2 DOC_SYNC 追溯

- 本次修复轮无 `>>DOC_SYNC:` 声明（修复目标明确为"响应格式不变，避免破坏端契约"）。
- 复核确认：三处修复均未改变 HTTP 响应体结构或状态码：
  - P1-1：pubDate 字段在 ctime 异常时从崩溃变为 fallback 时间戳（格式仍为 RFC 822 string）。
  - P1-2：响应体 JSON 结构不变，仅 codes 数量从 >50 变为 50。
  - P2-14：响应体 `recent` 列表结构不变，仅长度可能缩短。
- ✅ 无需文档同步。

### D3 规范合规

- 新代码遵循项目约定：`log.warning` 使用项目统一的 `logging.getLogger('server')` 实例；异常处理使用 Python 标准 `try/except` 模式；函数命名与现有模式一致。
- ✅ 合规。

### D4 漂移结论

✅ 无漂移。三处修复均为防御性编码改善，未引入契约偏差或规范违规。
