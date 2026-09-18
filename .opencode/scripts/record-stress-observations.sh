#!/usr/bin/env bash
# Record stress-test observations into doc/detailed/_PROGRESS.md (2026-09-18).
# Orchestrator-led doc update (subagent channel unavailable in free tier).
# Idempotent: skips if the marker section already exists.
set -euo pipefail

DOC="doc/detailed/_PROGRESS.md"

python3 - "$DOC" <<'PYEOF'
import io, sys

path = sys.argv[1]
with io.open(path, encoding='utf-8') as f:
    text = f.read()

old_row = (
    '| **AC-E4 吞吐**（可断言口径：错误率 0 + 后 3min P99 劣化 ≤20%） | `SAD §4.2` | '
    '需**压测 / 观测**。 |'
)
new_row = (
    '| **AC-E4 吞吐**（可断言口径：错误率 0 + 后 3min P99 劣化 ≤20%） | `SAD §4.2` | '
    '**✅ 已压测（2026-09-18 收盘后 / 非交易时段观测）**：真实负载形态全绿（loadtest 混合 '
    '10 并发 700/700 OK · avg 60ms / max 219ms · 35 req/s；stress_all 15 并发除 '
    '`/stock/f10` 外 p95<0.4s · 内存稳定 620MiB）；极端并发（380 线程）级联饿死已定位为 '
    '`f10_batch` 60s CDP 慢尾占满公共 worker 池所致，f10 非热路径（REV-DES-21 已裁定）'
    '⇒ 场景不成立、不做工程改造。AC 口径（错误率 0 + P99 劣化）属交易时段 / 持续观测项，保留实测。 |'
)

marker = '## ★ 压测观测记录（2026-09-18 · 非交易时段 / 收盘后）'
if marker in text:
    print('already recorded; nothing to do')
    sys.exit(0)

if old_row not in text:
    raise SystemExit('AC-E4 row not found: ' + old_row[:60])
text = text.replace(old_row, new_row, 1)

section = '''

## ★ 压测观测记录（2026-09-18 · 非交易时段 / 收盘后）

> 范围：**只记录观测，未改代码 / 未改契约 / 未改其他文档**。方法：`tests/{stress_test,stress_all,loadtest}.py` 对 8053 端口全套压测（容器已由用户重建并验证代码 == 工作区 HEAD）。

### 观测结论

1. **真实负载形态（健康）**：
   - `loadtest.py` 混合 10 并发（含 `/`、`/healthz`、`/opml.xml`、`/cls/hotplate`、`/stock/fundflow`）：700 请求 700 OK · 35 req/s · avg 60ms · max 219ms。
   - `stress_all.py` 15 并发 660 请求：628 OK / 32 Fail——**32 Fail 全部为 `/stock/f10`**（已知 REV-DES-21 非热路径），其余 11 个端点（RSS 5 + 面板 4 + fundflow/timeline/announcement/basic_info/data）p95 < 0.4s；内存 621→620MiB **稳定**（预算 1.5GiB）。
   - `/stock/f10` 单只验证：`sh600519` 缓存命中 1.8ms 完整数据；`sh600030` CDP 导航 3.3s 完整数据；批量 5 码 26.4s（60s budget 内）200，3 码完整 + 2 码按既有 `cdp_unavailable` 降级语义返回（`_errors` 结构，契约不变）。
2. **极端并发（不代表真实业务）**：`stress_test.py`（20 并发 × 20 端点 = 380 线程）第 2 轮出现全量客户端失败（status=-1 @0.0s）。定位：`/stock/f10_batch` 60s CDP 串行导航慢尾（`_BATCH_BUDGET_CDP=60`）占满 20-worker 公共池 → `BoundedThreadPoolServer._reject_503` 负载丢弃（裸 503 不经 `log_message`，访问日志不可见）。**触发条件需 20 并发 `f10_batch` 同时命中**——f10 非热路径（REV-DES-21 已裁定：极少调用、不构成问题）⇒ **该场景真实业务不成立，不做工程改造**（不设 CDP 并发闸门、不改 `MAX_WORKERS`/`MAX_INFLIGHT`）。
3. **回归**：`python -m unittest discover -s tests` = **514 全绿（5.4s）**；`py_compile` 通过。服务代码零改动，仅新增压测辅助脚本 `.opencode/scripts/{run-stress.sh,inspect-logs.sh}`（含 `--since` 修复与 503 隐形问题的说明）。
'''

if not text.endswith('\n'):
    text += '\n'
text += section

with io.open(path, 'w', encoding='utf-8') as f:
    f.write(text)
print('recorded OK')
PYEOF