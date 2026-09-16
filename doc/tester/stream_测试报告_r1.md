# stream/批量分片 修复轮 r1 测试报告

**TR-20260914-001** / v1.0 / ✅ 完成 / 日期：2026-09-14 / 关联用例：P5b 评审必补回归用例（60 codes 分片全量覆盖）

## 一、执行概要

| 项 | 值 |
|----|----|
| 总计 | 46 |
| 通过 | 46 |
| 失败 | 0 |
| 阻塞 | 0 |
| 跳过 | 0 |

**结论：✅ PASS（100%）**

本轮为 P6c 修复轮验证：code-developer 修复了 P8 盲审 + P5b 复审指出的并发/健壮性问题（P1-1~P1-10、P2-11~P2-14），tester 补 1 条 P5b 强制回归用例后执行定向回归 + 全量收尾。

## 二、缺陷清单

无（本轮未发现缺陷，0 BUG）。

## 三、测试详情

| 模块 | 类型 | 总数 | 通过 | 失败 | 说明 |
|------|------|------|------|------|------|
| tests.test_stream | UNIT/INTG | 19 | 19 | 0 | 新增 `BatchShardingTests`（1 条，P1-6 分片回归） |
| tests.test_server | UNIT | 27 | 27 | 0 | 含 P1-7 单飞雪崩相关 `test_fetch_json_leader_failure_does_not_stampede` |
| **合计** | | **46** | **46** | **0** | |

### 本轮新增用例

| 用例 | 位置 | 验证点 |
|------|------|--------|
| `test_60_codes_all_fetched_and_returned_beyond_max_batch` | `tests/test_stream.py::BatchShardingTests` | P1-6 分片修复：真实 `handle_cls_basic_infos`（stream `_FIELD_HANDLERS['quote']` 绑定的真实处理器）传 60 codes（> `_MAX_BATCH_SIZE=50`）——(a) 返回值含全部 60 个 code key；(b) mock fetcher 假数据下每个 code 都有数据；附加断言 fetcher 实际收到全部 60 个 code（分片证据，非仅合并侥幸） |

**变异校验（测试有效性）：** 用 r1 首次截断式修复（入口 `codes[:_MAX_BATCH_SIZE]`）做变异验证，变异后返回 50/60 codes，`set(result)==set(codes)` 断言失败——证明本用例能捕获"静默截断"回归。

## 四、P0 阻断分析

无。

## 五、结论

**✅ PASS（46/46 = 100% ≥ 90%）**

### 判定记录（测试适配 vs 真回归）

修复后行为变化点逐一核查，**全部无需测试适配、无真回归**：

1. **P1-6 batch 分片**（stock_api `_handle_cached_batch` → `_process_chunk` × N）：旧测试未覆盖 >50 批量路径，不受影响；新增回归用例验证分片全量覆盖 ✓
2. **P1-7 fetch_json fall-through 退避**（cache.py：随机 0-0.5s 退避 + 信号量(2) + 二次缓存复查）：现有 `test_fetch_json_leader_failure_does_not_stampede` 仍通过——该测试场景（leader 快速失败后 followers 在 `REQUEST_TIMEOUT=10s` deadline 内重选）不触达 fall-through 路径（仅在 deadline 耗尽后才执行退避），断言语义（err=1/ok=7/max_active=1）与修复后行为一致，**无需适配**
3. **P2-14 margin 长度对齐**（`n = min(len(dates), len(items))`）：现有 margin 3 条用例的 fixture 均为 dates/items 等长，解析结果不变，**无需适配**
4. **P1-1 THS ctime 容错、P1-2 截断日志、P1-3 缓存双写守卫、P1-4 预取游标黑名单、P1-5 after 异常日志、P1-8~P1-10/P2-11~P2-13 CDP 锁**：不改变现有测试断言输入/输出形态，现有用例全绿

### Flaky 说明

无失败用例，未触发重试判定。

### 执行命令

- T1 定向：`python3 -m unittest tests.test_stream tests.test_server -v` → 46/46 OK（本次修复范围 stream/server 受影响模块）
- T2 全量：`python3 -m unittest discover -s tests` → 46/46 OK
- 收尾自检：`python3 -m py_compile server.py tests/test_server.py tests/test_stream.py` ✓、`git diff --check` ✓