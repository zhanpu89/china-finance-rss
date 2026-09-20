# PRF-MEM-01 内存调优 — 测试报告

- **日期**：2026-09-20
- **变更**：`china_finance_rss/config.py` `DOMAIN_MATRIX` 数值收缩（纯配置，无逻辑变更）；`tests/test_config.py` L72 断言同步
- **被测文件**：`china_finance_rss/config.py`、`tests/test_config.py`
- **测试框架**：`unittest`（Python 标准库）
- **探测脚本**：`doc/tester/prf_mem_01_verify.py`（只读，未改生产/测试代码）

## 一、变更范围（git diff 核对）

仅 3 行配置数值 + 1 行测试断言 + 1 行注释，`depth` 行保持原样：

| 域 | before | after |
|----|--------|-------|
| `quote` | `('L0',1.0,1.0,'dedup',2000)` | `('L0',1.0,1.0,'fixed:1000',1000)` |
| `fundflow` | `('L1',1.0,1.0,'dedup',2000)` | `('L1',1.0,1.0,'fixed:1000',1000)` |
| `timeline` | `('L1',1.0,1.0,'dedup',2000)` | `('L1',1.0,1.0,'fixed:500',500)` |
| `depth` | `('L0',1.0,1.0,'dedup',500)` | 不变 |

`git diff --check` → 无空白错误。

## 二、执行命令与原始结果

### 1) 编译检查 — 通过
```
$ python -m py_compile china_finance_rss/*.py tests/*.py
（无输出 ⇒ 全部编译通过）
```

### 2) 全量单元测试 — 通过
```
$ python -m unittest discover -s tests -v
...
----------------------------------------------------------------------
Ran 514 tests in 5.149s

OK
```

- **Ran 514 tests**，**OK**（0 failures / 0 errors / 0 skips）
- 期望「514 全绿」✅ 一致
- 输出中的 `Traceback`/`[guard:*] handler raised` 为测试**故意注入**的降级路径造错日志（断言其被正确捕获），非失败。
- Flaky 复核：无失败用例，无重试需求。

### 3) 实值核对 — 通过（详见 §三）
```
$ python doc/tester/prf_mem_01_verify.py
{"verdict": "PASS", "fail": []}
```

## 三、实值核对表（`config.cache_policy(d)` 实际返回值）

### 3.1 本次变更域（4/4 命中）

| 域 | pool_max 实测 | cache_max 实测 | 期望 | 判定 |
|----|--------------|----------------|------|------|
| `quote` | **1000** | **1000** | {1000, 1000} | ✅ |
| `fundflow` | **1000** | **1000** | {1000, 1000} | ✅ |
| `timeline` | **500** | **500** | {500, 500} | ✅ |
| `depth` | **2000** | **500** | {2000, 500} | ✅ |

> `depth` 的 `pool_max=2000` 来自 `'dedup'` → `MAX_DEDUP_CODES`（实测常量 = 2000），即 `dedup` 语义未被改动。

### 3.2 未变更域回归（6/6 未误改）

| 域 | pool_max 实测 | cache_max 实测 | 期望 | 判定 |
|----|--------------|----------------|------|------|
| `plate` | 200 | None | {200, None} | ✅ |
| `feed` | 100 | 100 | {100, 100} | ✅ |
| `announcement` | 2000 | 500 | {2000, 500} | ✅ |
| `f10` | 2000 | 500 | {2000, 500} | ✅ |
| `margin` | 16 | None | {16, None} | ✅ |
| `sector` | 2000 | 2000 | {2000, 2000} | ✅ |

### 3.3 全域矩阵快照（12 域，原始 spec 1:1 对照）

| 域 | tier | ttl | pool_refresh | pool_spec → pool_max | cache_spec → cache_max |
|----|------|-----|--------------|----------------------|------------------------|
| quote | L0 | 4 / 120 | 4 / 120 | `fixed:1000` → 1000 | 1000 |
| depth | L0 | 4 / 120 | 4 / 120 | `dedup` → 2000 | 500 |
| fundflow | L1 | 8 / 120 | 8 / 120 | `fixed:1000` → 1000 | 1000 |
| timeline | L1 | 8 / 120 | 8 / 120 | `fixed:500` → 500 | 500 |
| plate | L2 | 12 / 120 | 12 / 120 | `fixed:200` → 200 | n/a |
| news_url | L3 | 30 / 180 | 30 / 180 | `n/a` → None | n/a |
| feed | L3 | 30 / 180 | 30 / 180 | `fixed:100` → 100 | 100 |
| announcement | L3 | 30 / 180 | 30 / 180 | `dedup` → 2000 | 500 |
| longhu | L4 | 300 | 300 | `n/a` → None | n/a |
| margin | L4 | 600 | 1200 | `fixed:16` → 16 | n/a |
| f10 | L4 | 300 | 300 | `dedup` → 2000 | 500 |
| sector | L4 | 604800 | None | `fixed:2000` → 2000 | 2000 |

> ttl 列「盘中 / 盘后」（`_trading_tiers`）；非交易时段 L0/L1/L2 收敛到 120。仅 `pool_max`/`cache_max` 与本次变更相关，ttl/tier 未受影响。

## 四、数值安全性分析（逆向核对）

`pool_max` 消费点 `stock_api.py:487/515`：仅在 `pool is not None` 时参与 `len(pool) > pool_max` 比较。

- `'dedup'` 与 `'fixed:1000'` 都解析为**非 None int**，故本次变更**不引入** `None` 参与比较的缺陷（`quote/fundflow/timeline` 变更前后均非 `n/a`）。
- 逆向：若把 `quote` 改成 `'n/a'`，`pool_max` 会变 `None` → `stock_api.py:515` 抛 `TypeError`。本次变更**未走该路径**，实测 `pool_max=1000` ✅。
- 逆向：若 cache_max 被误写 `'n/a'`，`stock_api._cache_store` 的 `len(cache) > cache_max` 会崩。实测四域 cache_max 均为 int ✅。
- `_resolve_pool_max` 对未知 spec 抛 `ValueError`；探测脚本已成功物化全部 12 域，佐证 spec 拼写合法。

## 五、缺陷清单

**无。** 本次未产生任何 BUG（P0/P1/P2 均 0）。

## 六、观察项（非阻断，仅记录）

| # | 观察 | 影响 | 等级 |
|---|------|------|------|
| O1 | `quote/fundflow/timeline` 的 pool_max 从 `'dedup'` 改为 `'fixed:N'` 后，**不再响应** `MAX_DEDUP_CODES` 环境变量 | 运维若曾靠该环境变量调大 quote 刷新池，此路径失效；属部署可观测性（行为语义已由 `fixed:` 显式固定，符合变更意图） | P2 |
| O2 | `cache.py` 共享 cache `MAX_CACHE_SIZE=2000`（L35）与各域 `cache_max` 是**两套独立上限**，本次未改动 | 共享 cache 内存上限不受本次收缩影响；如需进一步降内存需另行评估 | P2 |

> O1/O2 均为知情记录，不阻断本轮；如需处理请编排层决策。

## 七、结论

**✅ 通过（PASS）**

- 编译：通过
- 全量测试：`Ran 514 tests` / `OK`（0 失败 / 0 错误）
- 实值核对：变更域 4/4 命中，未变更域 6/6 未误改，全 12 域矩阵快照与设计一致
- 失败清单：无
