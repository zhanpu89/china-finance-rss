# 核查报告：`/stock/basic_info` 的 `avg_volume_5d` / `business_amount_avg_5d` 为何取不到

| 项 | 内容 |
|---|---|
| 核查类型 | **只读核查**（未修改任何代码/配置/文档，除本报告外） |
| 触发原因 | 下游反馈：架构变更后 `/stock/basic_info` 取不到 `avg_volume_5d` 与 `business_amount_avg_5d` |
| 被核查对象 | `GET /stock/basic_info`（`china_finance_rss/stock_api.py:fetch_cls_basic_info`）及其上游 `https://x-quote.cls.cn/quote/stock/basic` |
| 基线分支 | `feature/stream-push`（核查时工作区干净） |
| 疑似相关变更 | 包结构迁移（`server.py` → `china_finance_rss/`）、`fetch_json` 重写（负缓存/连接池/deadline）、`refresh_epoch`、空壳防御（`_basic_info_is_valid`）、`upstream_secu_code`（北交所双格式） |
| 核查日期 | 2026-09-17 |

---

## 0. 结论

> ### 判定：**这两个字段从未由本服务返回过**，与架构变更无关。
>
> 更进一步：**它们很可能也不属于上游 `/quote/stock/basic` 端点的字段集**。该端点 `fields=all`（权威全集）返回 **41 键**，其中不含这两者；网络上 `fields=avg_volume_5d` 之所以返回 `{...: null}`，是因为该端点的 `fields=` 参数对**任何未知名**都回显 `null`（含明显虚构名与兄弟端点的真实字段名），因此该 `null` **不构成字段存在的证据**。
>
> 需注意：本服务的**取数失败形态是"整节点 null + `_errors`"**，绝无"部分丢字段"形态。故若下游看到的是整节点 null，那是**另一条独立故障线**（北交所拼写 / 冷却账本 / deadline / 负缓存 / 空壳防御），与字段名问题无关 —— 详见 §5。
>
> 下游若确需该数据，**已实测可用的替代口径**见 §6：`kline?type=d1` 取末 5 根日 K 算术平均，单位与 `basic` **逐值一致**。

**四路证据一览：**

| # | 证据 | 结论 | 出处 |
|---|---|---|---|
| A | 全历史 `git log -S'avg_volume_5d'` / `-S'_5d'` 均为空；工作区 grep 为空；`API.md` 字段表无 | 字段名从未进入本仓库任何产物 | §1 |
| B | `basic` 取数 URL 全历史恒为 `?secu_code=`，从未带 `fields=` | 我们从未索取过这两个字段；不存在"不再传"的变更 | §2 |
| C | 上游默认体 = `fields=all` = **41 键**（不含两键）；`fields=` 对任意未知名一律回显 `null` | 上游该端点不认识这两个字段名 | §3 |
| D | 代码无字段裁剪（返回 `data` 逐键等于上游默认体）；失败为整节点 null；`_rekey_batch_response` 仅顶层改名；gzip/连接池/`refresh_epoch` 不改 body | 我们的任何变更都不可能造成字段级丢失 | §4 |

**被排除的两个备选判定：**

- **排除「曾返回、因上游变更消失」**：即使假设上游曾经支持该字段，也解释不了本现象 —— 我们**从未索取过**（无 `fields=`），且默认体从来不含它们，**我们侧不存在任何时间点会返回它们**。
- **排除「曾返回、因我们的变更消失」**：要"返回过"必须满足①URL 带 `fields=` 或②上游默认体含该键；①全历史不成立（§2），②实测不成立（§3）。所列四项近期变更均只影响"整条成败与新鲜度"，**不影响字段集合**（§4）。

---

## 1. 证据 A：仓库考古 —— 这两个字段是否曾存在于本仓库

### 1.1 工作区与 API.md

```
$ grep -rn "avg_volume_5d\|business_amount_avg_5d" . | grep -v "^./.git/"
(工作区无)
```

`API.md` 的 `/stock/basic_info` 契约字段表（`API.md` L242-263）逐项列出 `data` 内的 41 个字段（`secu_code`/`secu_name`/`last_px`/`change`/`business_amount`/`business_balance`/`qrr`/`mc`/`cmc`/…），**不含** `avg_volume_5d` / `business_amount_avg_5d`。

### 1.2 全历史 `git log -S`

```
$ git log --all --oneline -S'avg_volume_5d'
（空，无任何提交）
$ git log --all --oneline -S'business_amount_avg_5d'
（空，无任何提交）
$ git log --all --oneline -S'_5d'
（空）
$ git log --all --oneline -S'amount_avg'
(无 amount_avg)
$ git log --all --oneline -S'avg_vol'
(无 avg_vol)
```

> **决定性补刀：全历史 `-S'_5d'` 为空** —— 本仓库**全部历史**（所有分支、所有标签）中从未出现过任何含 `_5d` 的字符串。字段名从未被写入过代码、测试、文档或注释。

### 1.3 `git log -S'fields='` 的命中是假阳性

```
$ git log --all --oneline -S'fields='
40ef1b2 docs: P7b 契约同步 — 详设/SAD/PRD 对齐多轮实现
066ab6b fix: 北交所行情数据为空 — 上游 secu_code 双格式映射 + 空壳防御
1a36a55 fix(sse): 每拍真刷新 — refresh_epoch 解耦 tick 与缓存 TTL
01bb862 perf(sse): 按域分拍 4s + 五档盘口 + 冷启动修复
d181854 perf: SSE 50 码达标 8 秒 — 上游连接复用池 + DNS 修复 + 容量模型重标定
6d5bf8d docs: P7b 契约同步 — 详设/架构/PRD 对齐实现，并固化三项裁决
cbc472a perf: 高效/准确/稳定全面改造 — 8 模块 + 新增 metrics + 368 测试
c7e5702 feat: SSE 订阅推送服务 — 短线交易实时行情通道
```

逐个展开后，**全部是 SSE 订阅契约**里的 `group.fields` / `_subscribed_fields()` / `fields=["quote"]`，**与上游查询参数无关**：

```
066ab6b:329:+**3B SSE（组 ["bj430047","bj832000","sh600519"], fields=`["quote"]`）— 真实帧原文**
1a36a55:550:@@ def _refresh_pool(codes, now=None, fields=None, tick=None, deadline=None):
01bb862:741:              f'fields={group.fields}')
cbc472a:5267:+def _fetches_per_code(fields=None):
cbc472a:10164:+  """S2-4: fields=["nonsense"] is a 400, not a silent 3-domain widening."""
```

---

## 2. 证据 B：`basic` 取数 URL 的构造变更史 —— 是否曾传 `fields=`？

### 2.1 当前构造

```
china_finance_rss/stock_api.py:990:
  url = f'{_BASIC_INFO_BASE_URL}?secu_code={upstream_secu_code(stock_code)}'

china_finance_rss/config.py:239:
  _BASIC_INFO_BASE_URL = 'https://x-quote.cls.cn/quote/stock/basic'
```

**只有一个查询参数 `secu_code`，无 `fields=`。**

### 2.2 全历史逐提交扫描（含迁移前的根目录 `server.py` 时代）

```
--- 9c416d8 fix: Chrome memory leak + API format alignment + sector_name cache ---  ← 最早引入 REST 取数
513:    url = f'{_BASIC_INFO_BASE_URL}?secu_code={stock_code}'
--- dfffeb9 fix: concurrent CDP navigation with 15-page pool, ... ---
543:    url = f'{_BASIC_INFO_BASE_URL}?secu_code={stock_code}'
--- cbc472a perf: 高效/准确/稳定全面改造 — 8 模块 + 新增 metrics + 368 测试 ---
4575:   url = f'{_BASIC_INFO_BASE_URL}?secu_code={stock_code}'
--- 1a36a55 fix(sse): 每拍真刷新 — refresh_epoch 解耦 tick 与缓存 TTL ---
421:    url = f'{_BASIC_INFO_BASE_URL}?secu_code={stock_code}'
--- 066ab6b fix: 北交所行情数据为空 — 上游 secu_code 双格式映射 + 空壳防御 ---
-    url = f'{_BASIC_INFO_BASE_URL}?secu_code={stock_code}'
+    url = f'{_BASIC_INFO_BASE_URL}?secu_code={upstream_secu_code(stock_code)}'
--- 40ef1b2 docs: P7b 契约同步 — 详设/SAD/PRD 对齐多轮实现 ---
2689:-    url = f'{_BASIC_INFO_BASE_URL}?secu_code={stock_code}'
2690:+    url = f'{_BASIC_INFO_BASE_URL}?secu_code={upstream_secu_code(stock_code)}'
```

### 2.3 判定

> **从最早实现（`9c416d8`）到今天，`basic` 取数 URL 恒为 `?secu_code=<code>`，只有一个查询参数。**
>
> **我们从未传入过 `fields=`（或任何类似参数）去索取这两个字段；现在也没有"不再传"的变更 —— 因为历史上从未传过。**
>
> **唯一一次实质变更是 `066ab6b`**：`stock_code` → `upstream_secu_code(stock_code)`，**只改 `secu_code` 的拼写**（北交所双格式映射），**不动参数集合**。

另注：`field=`（单数）在历史中仅出现于五档盘口取数 `.../quote/stock/volume?secu_code=<code>&field=five`，与 `basic` 无关。

---

## 3. 证据 C：上游实测 —— 现在是否还能拿到这两个字段

> 全部探针在**容器内真实链路**执行：`docker compose exec -T rss python - <<'PY'`（只读网络请求，容器内未落文件）。

### 3.1 默认体与 `fields=` 系列探针

```
无 fields: code= 200 keys= 41
probe: avg_volume_5d,business_amount_avg_5d -> code= 200 keys= 2
    相关键: ['avg_volume_5d', 'business_amount_avg_5d']
probe: all -> code= 200 keys= 41
    相关键: ['business_amount']
probe: * -> code= 200 keys= 1
    相关键: []

无 fields 全部键: ['NetAssetPS', 'NonRestrictedShares', 'TotalShares', 'amp', 'av_px',
 'business_amount', 'business_balance', 'change', 'change_1y', 'change_3', 'change_5',
 'change_px', 'cmc', 'down_price', 'dynamic_pe', 'entrust_rate', 'eoeId', 'financing',
 'high_px', 'last_px', 'low_px', 'market_enum', 'mc', 'note', 'open_px', 'ori_code',
 'pb', 'pe', 'preclose_px', 'purchases', 'qrr', 'sales', 'secu_code', 'secu_name',
 'secu_type', 'tr', 'trade_status', 'trade_time', 'ttm_pe', 'unlisted', 'up_price']
```

⚠️ **不能就此下"字段存在"的结论** —— `fields=avg_volume_5d,...` 返回的 `null` 需要一个控制实验才能解释。见 3.2。

### 3.2 关键：`fields=` 的真实语义是「投影 + 未知名回显 `null`」

```
=== 1) 无 fields 默认体：含这两键？ ===
   contains avg_volume_5d = False | business_amount_avg_5d = False | 键数 41
=== 2) fields=这两个：实际值与键全集 ===
   键全集: ['avg_volume_5d', 'business_amount_avg_5d']
   值: {"avg_volume_5d": null, "business_amount_avg_5d": null}
=== 3) fields=all：是否含这两键 ===
   含 F1= False 含 F2= False | 键数 41
   与默认体键集合完全相同? True                      ← 权威全集 = 41 键
=== 4) fields=* ===        {"code": 200, "msg": "", "data": {"*": null}}
=== 5) fields= 空 ===      键数 41
=== 6) 任意混合（白名单语义验证）===
   {"secu_name": "贵州茅台", "last_px": 1266.98, "avg_volume_5d": null}
=== 7) 大小写/别名探测 ===
   fields=avg_volume_5        -> {"avg_volume_5": null}
   fields=avg_volume_10d      -> {"avg_volume_10d": null}
   fields=business_amount_avg_5 -> {"business_amount_avg_5": null}
   fields=volume_avg_5d       -> {"volume_avg_5d": null}
   fields=avg_amount_5d       -> {"avg_amount_5d": null}
```

**控制实验（决定性）：**

```
=== 控制实验：明显不存在的字段名 ===
   fields=zzz_not_a_field   -> {"zzz_not_a_field": null}
   fields=totally_bogus_xyz -> {"totally_bogus_xyz": null}

=== 已知真实字段当控制 ===
   {"secu_name": "贵州茅台", "trade_status": "ENDTR", "last_px": 1266.98}

=== 兄弟端点真实字段名，拿到 basic 上请求 ===
   fields=ma5              -> {"ma5": null}            ← ma5 在 kline 端点真实值 1288.47
   fields=ma10             -> {"ma10": null}           ← kline 真实值 1299.46
   fields=main_fund_5      -> {"main_fund_5": null}    ← fundflow 真实字段
   fields=business_balance -> {"business_balance": 2217338283}   ← basic 自己的字段 → 回真值
   fields=last_px          -> {"last_px": 1266.98}               ← basic 自己的字段 → 回真值
```

> **论证：** `fields=` 只在名字属于**该端点自身字段集**时回真值；否则无条件回显 `null`（虚构名、拼写近似名、兄弟端点真实名一视同仁）。`avg_volume_5d` 得到 `null` ⇒ 与 `zzz_not_a_field` / `ma5` **同类** ⇒ **上游 `/quote/stock/basic` 不认识该字段名**。
>
> 独立旁证：`fields=all` 与默认体**键集合完全相同**（41 键），**不含**这两键 —— 若它们是该端点字段，全集里应当出现。

### 3.3 北交所形态同样返回 `null`

```
430047.BJ -> {"avg_volume_5d": null, "business_amount_avg_5d": null}
832000.BJ -> {"avg_volume_5d": null, "business_amount_avg_5d": null}
```

### 3.4 兄弟端点扫描（是否存在同义字段）

```
=== 兄弟端点键扫描（找 avg/volume/amount 相关）===
   fundflow: code=200 keys=18 相关=[]
   tline:    code=200 keys=2  相关=[]
   detail:   code=200 keys=8  相关=[]
   f10:      code=200 keys=4  相关=[]
   company_info: code=9004 data_type=NoneType keys=N/A
   volume5:  code=200 keys=21 相关=['b_amount_1'..'b_amount_5','s_amount_1'..'s_amount_5']
```

`fundflow` 键全集：`date, large_fund_diff, latest_up_date, little_fund_diff, main_fund_10, main_fund_20, main_fund_3, main_fund_5, main_fund_diff, main_fund_in, main_fund_out, medium_fund_diff, min_time, super_fund_diff, year_avr_close_change, year_avr_open_change, year_up_num, year_up_ratio`
—— 有 `main_fund_5`（**5 日主力资金**，非 5 日均量/均额），**无**均量/均额字段。

> **没有任何已探端点直接提供 `avg_volume_5d` / `business_amount_avg_5d`。**

---

## 4. 证据 D：我们代码是否可能"删字段"

### 4.1 `fetch_cls_basic_info` 是否做字段裁剪/白名单过滤？ —— **否，原样透传**

```python
# stock_api.py:990-1002
url = f'{_BASIC_INFO_BASE_URL}?secu_code={upstream_secu_code(stock_code)}'
raw = _rest_fetch(url, _BASIC_INFO_HEADERS, ttl, deadline, refresh_epoch)
if raw.get('code') == 200 and _basic_info_is_valid(raw):
    result = raw                      # ★ 整个上游包裹原样持有（含 code/msg/data）
```

后续只在**顶层**新增 `sector_name`（`stock_api.py:1025`）与 `depth`（`stock_api.py:1035`），**从不触碰 `data` 内部的键集合**。全仓搜索无白名单/投影逻辑：

```
=== 是否存在白名单/投影式裁剪（stream.py / stock_api.py）===
（仅命中 cache LRU 清理的 `for k in aged/expired`，非字段过滤）
```

历史上唯一一次"字段表"相关实现 `70e3daf`（`_fill_missing`）已在 `8bf51aa` 删除，且它**只补齐缺失键为 `null`，从不移除**：

```
70e3daf fix: always return consistent key schema
+def _fill_missing(result, data, expected_keys):
+    """Fill expected keys not in data as null, preserving extra keys."""    ← 保留额外键
8bf51aa remove stock_plate and articles from /stock/data; drop _STOCK_EXPECTED_KEYS
```

**端到端实测（本服务实时响应）确认无裁剪：**

```
$ curl -s "http://localhost:8053/stock/basic_info?code=sh600519"
HTTP 200
顶层键: ['sh600519']
节点键: ['code', 'data', 'depth', 'msg', 'sector_name']
含 avg_volume_5d ? False
data 键数: 41
含 avg_volume_5d ? False | 含 business_amount_avg_5d ? False
```

→ 我们返回的 `data` **逐键等于上游默认体**（§3.1 与本节两处键列表完全一致）。**既没多、也没少。**

### 4.2 空壳防御 `_basic_info_is_valid` 触发时会发生什么？ —— **整条约失败，不会部分丢字段**

```python
# stock_api.py:942-955
# Validity probe for the upstream `basic` payload (BSE / wrong-spelling shell
# defence).  x-quote answers a wrong `secu_code` spelling with HTTP 200 +
# `code:200` + a 41-key all-null object — not an error code — so a fetcher that
# trusts `code == 200` alone caches and streams a "frame full of nulls".  A real
# quote always names the instrument and/or carries a last price.
_BASIC_INFO_KEY_FIELDS = ('secu_name', 'last_px')


def _basic_info_is_valid(raw):
    """True when ``raw`` carries real instrument data (not the all-null shell)."""
    data = raw.get('data')
    if not isinstance(data, dict) or not data:
        return False
    return any(data.get(f) not in (None, '') for f in _BASIC_INFO_KEY_FIELDS)
```

**判定条件：** `data` 为非空 `dict`，且 `secu_name` / `last_px` **至少一个**非 `None`/`''`。不满足 ⇒ 走 `err = FetchError('upstream_error', url=url)`（`stock_api.py:1001`），**整条 payload 被丢弃**（`result` 保持 `None`），并计 `upstream_fail_total{upstream_error}`。

失败在批处理链上的落点（`_process_chunk` ⑥ 段，`stock_api.py`）：

```python
if kind:
    _fail_ledger_record_failure(domain, canon, kind)     # 进 120s 冷却账本
    by_canon[canon] = None                               # ★ 整节点 null
    err_canon[canon] = kind
...
for original, canon in alias.items():
    results[original] = by_canon.get(canon)              # 请求拼写 → None
    if canon in err_canon:
        errors[original] = err_canon[canon]              # → _errors[code]
```

→ 语义是 **`{"sh600519": null, "_errors": {"sh600519": "upstream_error"}}`**，即**整个 code 节点为 `null`**，**绝不出现"其他 40 键在、惟独这两键没了"的部分丢失形态**。

### 4.3 `_rekey_batch_response` 是否可能丢字段？ —— **否，纯顶层改名**

```python
# server.py:668-695
def _rekey_batch_response(data, codes, requested):
    """... This is a pure rename, not assembly: the key set is exactly the
    handler's ... and a request that needed no re-spelling (the common
    ``sh600519`` case) returns ``data`` untouched, so its body stays
    byte-identical."""
    if not isinstance(data, dict):
        return data
    rename = dict(zip(codes, requested))
    if not any(canon != raw for canon, raw in rename.items()):
        return data                          # ★ 无需改拼写 → 原对象直接返回
    out = {}
    for key, value in data.items():
        if key == '_errors' and isinstance(value, dict):
            out[key] = {rename.get(c, c): kind for c, kind in value.items()}
        elif key.startswith('_'):
            out[key] = value                 # 保留保留键
        else:
            out[rename.get(key, key)] = value  # ★ 只改顶层键名，值引用不变
    return out
```

只对**顶层** code 键与 `_errors` 子键做映射；`value` 是原引用。`sh600519` 这类不需要改拼写的请求**直接返回原对象**（注释明示 byte-identical）。**不可能丢 `data` 内部字段。**

### 4.4 gzip / 连接池 / `refresh_epoch` 是否改动响应体内容？ —— **否**

```python
# cache.py:841-858
req = Request(url, headers=headers or {})
with urlopen(req, timeout=timeout) as resp:              # ★ no lock held
    data = resp.read().decode(encoding, errors='replace')
...
_cache_put(cache, url, data, ttl=ttl)                    # 原样字符串入缓存
return data
```

- 响应体 → 字符串 → 缓存 → 原样返回；`json.loads` 只在 `_fetch_rest_json`（`stock_api.py:298`）做一次解析，**不重建键**。
- `refresh_epoch` 只影响**是否命中缓存**（`_cache_fresh(entry, refresh_epoch)`，`cache.py:790/818/874`），**不影响体内容**。
- 连接池只复用底层连接（`d181854`：上游连接复用池 + DNS 修复），**不改 body**。
- `c26f5df` 的"gzip 协商严谨化 / Vary 补全"针对的是**我们自己的 HTTP 响应头**，与上游取数无关。
- SSE 帧装配同样整对象赋值（`stream.py:478`：`snapshot.setdefault(code, {})[field] = data`），无投影。

> **四者皆不会造成字段级丢失。**

---

## 5. 需下游澄清的歧义：两种现象指向完全不同的根因

本报告的结论**只覆盖"字段集合"问题**。下游所报"取不到"必须先用**现象形态**区分，因为两条线的根因与处置完全不同：

| 下游观察到的现象 | 根因判定 | 处置方向 |
|---|---|---|
| **① `data` 的 41 键都在，惟独缺 `avg_volume_5d` / `business_amount_avg_5d`** | 该两字段**从未存在过**（§1-§4）。下游大概率**记错来源**：可能曾直连 `x-quote` 且自带 `fields=`、或数据来自其他行情商 / 第三方 SDK、或与 `business_amount`（成交量）、`main_fund_5`（5 日主力资金）混淆 | 按"下游契约期望"处理：走 §6 替代口径，或由编排层裁决是否新增聚合域。**注意：即便下游自己带 `fields=avg_volume_5d,...` 直连上游，实测也只会拿到 `null`（§3.2）** |
| **② 整个 code 节点是 `null` / 响应里 `_errors` 有值** | **取数失败线**，与字段名**完全无关**（§4.2）。候选：北交所 `secu_code` 拼写（`upstream_secu_code`）、120s 冷却账本（`_fail_ledger_*`）、`deadline` 预算耗尽、URL 负缓存（`_negative`）、空壳防御（`_basic_info_is_valid`）拦截 | **另开一条线**排查。需下游提供：原始响应报文、发生时间、请求的 code 形态（`sh600519` / `430047` / `430047.BJ`） |

**请下游回传**（用于终结歧义）：

1. 现象形态属于 ① 还是 ②（最好附**原始响应报文**）；
2. 若自称"曾经拿到过"，请提供**当时真实收到该两键的原始报文**（作为对照基准）；
3. 当时是**直接调本服务**，还是**直连 `x-quote`**？若直连，URL 是否带了 `fields=`？

> **不确定项（明确标注）：** 本次核查无法访问上游的**历史**契约，因此**不能 100% 排除**"上游曾经在该端点返回过这两个键、后被下线"这一上游侧事件。但在拿到下游"历史原始报文"之前，该假设缺乏任何证据支撑，且与两条实测事实相悖（`fields=all` 全集不含它们；`fields=` 存在未知名回显机制，会把"不支持"误读为"支持"）。**故在拿到反证前，按"从未返回过"处置。**

---

## 6. 替代方案（**已实测可用**）

上游**无现成的 5 日均量/均额字段**，但有**日 K 线**可用以计算，且单位与 `basic` **逐值一致**。

### 6.1 找到日 K 取值

```
=== 探测 日K线/均量 类端点 ===
  kline        : code=9001 msg=请求错误 data=['type']      ← 端点存在，缺合法 type
  klines       : code=9004 not found
  dayk         : code=9004 not found
  tline&type=5d: code=200 data=['date','line']            ← 分时，非日K

=== kline type 取值探测（节选）===
  type=w   : OK → 200 条（周K）
  type=m   : OK → 200 条（月K）
  type=d1  : OK → 200 条（★ 日K）      type=fd1 : OK → 200 条
  type=day / d / 1 / 1d / 5 / min / week / month / … : code=9001 请求错误
```

### 6.2 记录字段与实测值

```
type=d1 条数: 200 | 字段: ['amp','business_amount','business_balance','change',
  'change_color','close_px','date','high_px','low_px','ma10','ma20','ma5',
  'open_px','preclose_px','secu_code','tr']
最后 6 条日期/量/额:
   20260910  amount=1890022  balance=2428698784
   20260911  amount=3480142  balance=4430841445
   20260914  amount=1657146  balance=2116621850
   20260915  amount=1376172  balance=1756915149
   20260916  amount=2623524  balance=3307926407
   20260917  amount=1755380  balance=2217338283

★ 由最后5根日K算出的 5日均量/均额（下游替代口径）:
   avg_volume_5d          = 2178472.8
   business_amount_avg_5d = 2765928626.8
```

### 6.3 单位一致性校验（关键，避免口径错配）

```
basic : trade_time=None  business_amount=1755380  business_balance=2217338283
kline : date=20260917    business_amount=1755380  business_balance=2217338283
单位一致性(当日量/额需相等): True True
```

> **`basic.data.business_amount` / `business_balance` 与 `kline(type=d1)` 末根日 K 的对应值逐值相等** ⇒ 由日 K 算出的 5 日均值与 `basic` 同量纲，可直接对接。

### 6.4 北交所点号形态（三个码全部实测）

```
430047.BJ: code=200 len=200   末5根均值: avg_volume_5d=3079575.0  business_amount_avg_5d=44581268.8
832000.BJ: code=200 len=200   末5根均值: avg_volume_5d=362471.2   business_amount_avg_5d=4931380.2
920819.BJ: code=200 len=200   末5根均值: avg_volume_5d=8045879.4  business_amount_avg_5d=25413111.8
```

（`secu_code` 用 `config.upstream_secu_code` 的点号形；`430047.BJ` 单独验证 `type=w` 亦为 200 条。）

### 6.5 推荐口径

```
GET https://x-quote.cls.cn/quote/stock/kline?secu_code=<code>&type=d1
→ data: 200 根日K（升序），取末 5 根算术平均：
   avg_volume_5d          = mean(last5[*].business_amount)
   business_amount_avg_5d = mean(last5[*].business_balance)
```

**注意事项：**

- 属性为**日频（非实时）**，与 `basic` 的盘中 4s TTL 域**不同频**；建议给独立的**长 TTL 缓存域**（对齐 `sector` 量级，而非 `quote` 的 4s），避免每拍打上游。
- 数据量较大（200 条/码），批量场景需评估上游负载。
- 若确需**服务端直接返回**这两个字段，需由**编排层裁决**是否新增聚合域（例如 `GET /stock/avg5?code=`）。**本次为只读核查，未做任何实现。**
- 日 K 的更新时点/停牌日处理未在本次核查范围内，下游计算口径需自行确认。

---

## 7. 只读性声明

- 本次核查**未修改任何代码、配置、文档**（除本报告文件的**新增**外）；核查阶段未触发任何写操作，未执行 `git commit` / `git checkout` / 任何写命令。
- 核查阶段唯一写入：`/tmp/opencode/bi.json`（仓库外临时目录，`curl` 输出）。
- `docker compose exec` 仅执行**只读网络探测**（`urllib` GET），容器内未落文件。
- 核查结束时工作区状态：

```
$ git status --porcelain
（空）
```

---

## 附录：关键复现命令

```bash
# A. 仓库考古
grep -rn "avg_volume_5d\|business_amount_avg_5d" . | grep -v "^./.git/"
git log --all --oneline -S'avg_volume_5d'
git log --all --oneline -S'_5d'

# B. URL 构造全历史
grep -n "secu_code=\|fields=" china_finance_rss/stock_api.py
for c in $(git log --all --format=%H); do
  git show "$c" | grep -n "quote/stock/basic\|BASIC_INFO_BASE_URL}?" | head -4
done

# C. 上游实测（容器内真实链路）
docker compose exec -T rss python - <<'PY'
import json, urllib.request
H={'User-Agent':'Mozilla/5.0','Referer':'https://www.cls.cn/stock'}
def get(u):
    r=urllib.request.urlopen(urllib.request.Request(u,headers=H),timeout=8)
    return json.loads(r.read().decode('utf-8','replace'))
B='https://x-quote.cls.cn/quote/stock/basic?secu_code=sh600519'
print(get(B)['data'].keys())                    # 默认 41 键
print(get(B+'&fields=zzz_not_a_field')['data']) # 控制：未知名 → null
print(get(B+'&fields=all')['data'].keys())      # 权威全集 41 键
PY

# D. 本服务实时响应
curl -s "http://localhost:8053/stock/basic_info?code=sh600519" | python3 -m json.tool
```

**报告结束。**

