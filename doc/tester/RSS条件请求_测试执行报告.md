# RSS 条件请求（ETag / Last-Modified / 304）测试执行报告

- **日期**：2026-09-18 · **阶段**：P6c 测试代码实现与执行
- **依据**：`doc/detailed/server.md` v1.7 §8（`SRV-T46`–`SRV-T62` ＋ `SRV-T52b`/`SRV-T56b`，19 条）；`doc/detailed/cache.md` v1.6 §8（`T-CACHE-32`，1 条）
- **实现行为参考**：`server.py` `_feed_etag`/`_not_modified`/`_if_none_match_matches`/`_if_modified_since_not_modified`/`_send_not_modified`/`_send_text`/`_get_or_fetch_feed`；`cache.py` `feed_cache_get_entry`；`utils.py` `generate_rss`
- **测试框架**：unittest · **入口**：`python -m unittest discover -s tests -v`

---

## 1. 全量结果

```
$ python -m py_compile china_finance_rss/*.py tests/*.py   # 无输出（通过）
$ python -m unittest discover -s tests
...
Ran 491 tests in 5.031s

OK
```

| 项 | 数值 |
|----|------|
| 基线（改动前实测） | **467** OK |
| 本轮新增用例 | **24**（22 in `test_server_http.py` ＋ 2 in `test_cache.py`） |
| 全量 | **491** OK · 失败 **0** · 错误 **0** |
| 结论 | ✅ **PASS 100%**（无 P0/P1/P2，无测试暴露的真实缺陷） |

---

## 2. 新增用例 ↔ 文档编号映射

| 文档编号 | 测试方法（文件） |
|---------|-----------------|
| `SRV-T46` | `RssConditionalGetTests.test_t46_first_200_has_etag_and_last_modified` |
| `SRV-T47` | `...test_t47_same_etag_replay_304_and_idempotent` |
| `SRV-T48` | `...test_t48_inm_star_304_and_nonmatching_200` |
| `SRV-T49` | `...test_t49_multi_value_list_and_nonmatching_list_200` |
| `SRV-T50` | `...test_t50_weak_strong_and_lowercase_w` |
| `SRV-T51` | `...test_t51_ims_future_past_and_equal_boundary` |
| `SRV-T52` | `...test_t52_channel_content_unchanged_across_ttl_same_etag` |
| `SRV-T52b` | `...test_t52b_pure_function_only_pubdate_differs_same_etag` / `...test_t52b_handler_eastmoney_missing_showtime_clocked` / `...test_t52b_handler_ths_invalid_ctime_clocked` / `...test_t52b_handler_jin10_missing_time_clocked` / `...test_t52b_end_to_end_cross_ttl_304`（5 方法） |
| `SRV-T53` | `...test_t53_content_change_changes_etag_and_200` |
| `SRV-T54` | `...test_t54_head_304_and_head_200` |
| `SRV-T55` | `...test_t55_public_base_url_unset_304_private_vary_host` |
| `SRV-T56` | `...test_t56_invalid_date_header_is_200_and_priority` |
| `SRV-T56b` | `...test_t56b_inm_miss_with_matching_ims_is_200` |
| `SRV-T57` | `...test_t57_gzip_304_no_content_encoding_and_etag_independent` |
| `SRV-T58` | `...test_t58_ttl_output_position_boundaries_and_guard` |
| `SRV-T59` | `...test_t59_degraded_feed_no_false_304_and_ims_disabled` |
| `SRV-T60` | `tests.test_cache.FeedEntryAccessorTests.test_srv_t60_feed_cache_get_entry_contract` |
| `SRV-T61` | `RssConditionalGetTests.test_t61_scope_negative_static_and_json_never_304` |
| `SRV-T62` | `...test_t62_200_and_304_headers_diff_verbatim` |
| `T-CACHE-32` | `tests.test_cache.FeedEntryAccessorTests.test_t_cache_32_shallow_copy_isolates_the_container` |

> `test_server_http.py` 类名前缀统一为 `RssConditionalGetTests.`。19 个 `SRV` 编号 ＋ 1 个 `T-CACHE` 编号 → **24 个测试方法**（`SRV-T52b` 按详设拆为 5 条：纯函数 1 ＋ handler 三 feed 3 ＋ 端到端 1）。

---

## 3. `SRV-T52b` 的红/绿方向证据（P5b 硬要求 ①）

### 3.1 如何 patch 受控时钟

`_StepClock`（`test_server_http.py` 模块级）每次「回落取值」前进 1 秒，显式 `timeval` 原样格式化（不消耗计数）：

- **eastmoney**（`server.py:111` 回落）：`patch.object(srv, 'formatdate', clock.formatdate)`
- **ths**（`server.py:138` 回落）：`patch.object(srv, 'time', clock)`（`clock.time()` 逐次 `t`/`t+1`）
- **jin10**（`utils.py` `parse_jin10_items` 回落）：`patch.object(utils_mod, 'formatdate', clock.formatdate)`

三次 handler 调用均让上游时间字段缺失/非法（eastmoney `showtime` 缺失、ths `ctime='not-a-number'`、jin10 `time` 缺失），使回落真实发生。

### 3.2 红/绿方向声明与实测

测试内两处断言共同构成**双向**证据：
1. `assertNotEqual(p1, p2)` —— 回落的 `<pubDate>` 确实不同（证明时钟跨秒、回落真实发生）；
2. `assertEqual(_feed_etag(x1), _feed_etag(x2))` —— 绿方向：剔除 `pubDate` 后 ETag 必须相同；
3. 同一测试内 `patch.object(srv, '_PUBDATE_RE', re.compile(r'(?!)'))`（等价于「把 `<pubDate>` 替换去掉/裸 body 哈希」）后 `assertNotEqual(...)` —— **红方向**：此时 ETag 必然不同。

一次性探针实测（未改任何业务文件，运行时 monkeypatch）：

```
[handler] fallback pubDate differs        -> True
[handler] real projection, ETag equal     -> True
[handler] projection OFF, ETag equal      -> False
[pure]    real _PUBDATE_RE : ETag(x1)==ETag(x2) -> True
[pure]    projection OFF   : ETag(x1)==ETag(x2) -> False
```

**若把 `_PUBDATE_RE` 的替换去掉，该用例会失败**：`_feed_etag(x1)` 与 `_feed_etag(x2)` 将不等（探针第 3/5 行），绿方向的 `assertEqual` 直接红。

### 3.3 为什么「不控时钟」是假绿（P2-a 核心）

未 patch 时钟时，同一秒内两次回落的 `formatdate(timeval=None)`/`int(time.time())` 取值相同：

```
unclocked fallback pubDates: ['Fri, 18 Sep 2026 03:08:37 GMT'] ['Fri, 18 Sep 2026 03:08:37 GMT']
unclocked pubDate differs  -> False
```

即两次生成的 XML **逐字节相同**，ETag 自然相同 —— 不做 C1 修复也会绿。本用例的 `assertNotEqual(p1, p2)` 会在这种情形下先失败，**拒绝把同秒同值当作验收证据**；只有受控时钟使回落跨秒后，ETag 相等才真正检验「`pubDate` 已被 canonical 投影全量剔除」。

---

## 4. 三条最易漏的范围/负向断言落实

| 要求 | 落实 |
|------|------|
| `If-None-Match` 不匹配 ∧ `If-Modified-Since` 本会命中 ⇒ **必须 200 完整体** | `test_t56b_inm_miss_with_matching_ims_is_200`：先验证「仅 IMS 未来日期」单独得 304，再验证「INM `"nope"` ＋ 同一 IMS」得 200 且体可解析、item 数正确（**负向**，非仅断言"忽略 IMS"） |
| `SRV-T52b`（受控时钟 `t`/`t+1` ＋ 红/绿方向 ＋ 纯函数断言） | 见 §3；纯函数：构造仅 `<pubDate>` 不同、其余逐字节相同的 x1/x2 ⇒ ETag 相同；handler 层三 feed 全覆；端到端跨 TTL ⇒ 304 |
| **范围负向**：`/opml.xml`、`/`、JSON 端点带条件头 ⇒ 恒 200 | `test_t61_scope_negative_static_and_json_never_304`：`/opml.xml`、`/`、`/market/margin?market=99`、`/healthz` 带 `If-None-Match` ＋ 未来 `If-Modified-Since` ⇒ 全部 200、**无 `ETag`**、`/` 与 `/opml.xml` 体不因条件头改变（BR-SRV-36/44，v1.5 零覆盖 → 本轮闭合） |

其余 `SRV-T46`–`T62` 全部实现（见 §2 映射），含：弱 `W/"…"` 首次 200 ＋ `Last-Modified`、同 ETag 重放 304（无 body/无 `Content-Encoding`/无 `Content-Length`/无 `Content-Type`）、304 的 `ETag`+`Cache-Control`+`Vary` 与 200 同值、幂等重放且 `feed_cache_put` 仅首次、`If-None-Match: *`、逗号多值、**只认字面大写 `W/`**（小写 `w/` ⇒ 200）、IMS 未来/过去/**等值边界**、内容变（title / `<atom:link>` 随 Host）⇒ ETag 变 ⇒ 200、`HEAD` 得 304（含仅 IMS 分支）且与 GET 304 头一致、`PUBLIC_BASE_URL` 未设时 304 仍 `private` ＋ `Vary: Host, X-Forwarded-Host, X-Forwarded-Proto, Accept-Encoding`、非法/不可解析日期头 ⇒ 200（绝不 400/500）、gzip 客户端下 304 无 `Content-Encoding` ＋ ETag 编码无关、`<ttl>` 位置与取值（30→1 / 180→3、`ttl=None` 不输出、`ttl<=0` 守卫、`_feed_ttl_minutes` 七档边界）、降级不误 304（失败态 `Last-Modified` 不出现；同一错误表示重放可 304）、200 vs 304 头逐字 **diff**（T62，设/未设 `PUBLIC_BASE_URL` 两种）。

---

## 5. 发现的问题清单

**无。** 本轮 24 条新用例全部一次通过；**未修改任何业务代码**；未削弱或改写既有断言（既有 467 条全绿保持）。测试写法遵循项目约定：`unittest`、全限定名 `patch`、起真实 HTTP 服务并真实解析响应、不依赖外网/CDP（打桩 `fetch_json` 等）。

---

## 6. 改动文件

| 文件 | 改动 |
|------|------|
| `tests/test_server_http.py` | 顶部补 `gzip`/`hashlib`/`re`/`email.utils`/`cache as cache_mod`/`utils as utils_mod` 导入；新增 `_StepClock` 与 `RssConditionalGetTests`（22 方法，覆盖 `SRV-T46`–`T62`） |
| `tests/test_cache.py` | 新增 `FeedEntryAccessorTests`（2 方法：`SRV-T60`、`T-CACHE-32`） |
| `doc/tester/RSS条件请求_测试执行报告.md` | 本报告 |

未触碰 `china_finance_rss/**`、`doc/detailed/**`、`doc/arch/**`、`doc/prd/**`、`API.md`、`README.md`、`.opencode/**`、`opencode.json`。

