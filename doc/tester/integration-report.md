# RSS 条件请求 真实部署路径集成验证报告（v1 → v2）

> ⚠️ **本文件 v1 部分（下至文末「v2 重验」节之前）已被 v2 取代。**
> v1 的**决定性证据**（§2：跨 TTL 重生成时 `Last-Modified` 由 `03:12:46` **前进**到 `03:13:42` 而 `ETag` 不变）描述的是 **F1 修复前**的语义；F1 落地后该行为被**有意反转**：内容未变时跨 TTL 重生成，`Last-Modified` **必须不再前进**，且**仅带 `If-Modified-Since`** 的客户端也拿到 `304`（v1 时为 `200`，见 v1 §5）。历史原文予以保留，仅逐节加注，**不再作为现状证据**；请以文末 **v2 重验** 节为准。

# 【v1 · 历史，已被 v2 取代】

- **日期**：2026-09-18 · **阶段**：P6d 集成验证（真实部署路径）
- **环境**：`docker compose up -d --build` 重建容器 `china-finance-rss`，端口 **8053**；盘中时段 ⇒ feed TTL **30s**
- **方法**：在部署容器上以 `curl` 完成 RSS 条件请求端到端验证（编排层执行，本报告据实落盘）
- **依据**：`doc/detailed/server.md` v1.7 §8（条件请求 / `ETag` / `<ttl>`）；`doc/review/rss-conditional-get_代码评审_专家版.md` P2-2 / BR-SRV-38
- **结论**：✅ **P6d 通过（11/11）**

---

## 1. 验证矩阵（11 项全通过） — ⚠️ 已被 v2 取代（第 5、11 项方向反转）

| # | 验证项 | 请求 | 实际响应 | 判定 |
|---|--------|------|----------|------|
| 1 | 首次 200 带校验器 | `GET /cls/telegraph` | `200` + `ETag: W/"80fbcb292f95ab7d861ba954113cc3ed7b9b7a9c892eca36e556e9ef9a53e000"` + `Last-Modified: Fri, 18 Sep 2026 03:12:46 GMT` + `Cache-Control: private, max-age=30` + `Vary: Host, X-Forwarded-Host, X-Forwarded-Proto, Accept-Encoding` + `Content-Length: 45003` | ✅ |
| 2 | 第二个 feed | `GET /jin10/flash` | `200` + `ETag: W/"e1f471f518e5138b154aaa86497e430f532b62773eea441ebac6c7419bb7e0f0"` + `Last-Modified: Fri, 18 Sep 2026 03:12:45 GMT` + 同款 `Cache-Control`/`Vary` + `Content-Length: 12901` | ✅ |
| 3 | body 含 `<ttl>` 且位置正确 | 落盘 body 前 9 行 | 第 7 行 `<lastBuildDate>Fri, 18 Sep 2026 03:12:46 GMT</lastBuildDate>`，**第 8 行 `<ttl>1</ttl>`**，第 9 行 `<atom:link href="http://localhost:8053/cls/telegraph" rel="self" type="application/rss+xml"/>` | ✅ |
| 4 | `If-None-Match` 命中 ⇒ 304 | `-H 'If-None-Match: W/"80fbcb…e000"'` | `304 Not Modified`；头含 `ETag` + `Last-Modified` + `Cache-Control` + `Vary`；**无 `Content-Type` / `Content-Length` / `Content-Encoding`**、无 body | ✅ |
| 5 | `If-Modified-Since` 等值 ⇒ 304 | `-H 'If-Modified-Since: Fri, 18 Sep 2026 03:12:46 GMT'` | `304 Not Modified` | ✅ |
| 6 | **INM 不匹配 ∧ IMS 本会命中 ⇒ 完整 200**（优先级负向） | `-H 'If-None-Match: W/"deadbeef"' -H 'If-Modified-Since: …03:12:46…'` | **`200` + `Content-Length: 45003`**（完整体，未误 304） | ✅ |
| 7 | `HEAD` ⇒ 304 | `curl -I -H 'If-None-Match: W/"80fbcb…e000"'` | `304 Not Modified`，头与 GET 304 一致 | ✅ |
| 8 | **范围负向**：`/opml.xml` 带条件头 ⇒ 200 | `-H 'If-None-Match: W/"deadbeef"'` on `/opml.xml` | `200` + `Content-Type: text/x-opml; charset=utf-8` + `Cache-Control: private, max-age=300`，**无 `ETag`** | ✅ |
| 9 | gzip + INM ⇒ 304 无 `Content-Encoding` | `-H 'Accept-Encoding: gzip' -H 'If-None-Match: …'` | `304 Not Modified`，**无 `Content-Encoding`**、无 body | ✅ |
| 10 | 小写 `w/` ⇒ 200（只认字面大写） | `-H 'If-None-Match: w/"80fbcb…e000"'` | **`200` + `Content-Length: 45003`** | ✅ |
| 11 | **跨 TTL 重生成 ⇒ ETag 不变 ⇒ 304**（本专项 R1） | 容器内等 28s 越过 30s TTL 后重新 GET，再以**旧 ETag** 重放 | 见 §2 明细；旧 ETag 重放得 `304` | ✅ |

---

## 2. 第 11 项明细（R1 决定性证据） — ⚠️ 已被 v2 取代（v2 实测 LM **不变**、IMS-only ⇒ 304）

| 字段 | 第一次 03:12:46 | 第二次 03:13:42 | 含义 |
|------|-----------------|-----------------|------|
| body `<lastBuildDate>` | `Fri, 18 Sep 2026 03:12:46 GMT` | `Fri, 18 Sep 2026 03:13:42 GMT` | **原始 XML 字节已变**（条目过 TTL、重新回源重生成） |
| 头 `Last-Modified` | `…03:12:46 GMT` | `…03:13:42 GMT` | 缓存条目**已重生成** |
| `ETag` | `W/"80fbcb29…e000"` | `W/"80fbcb29…e000"` | **逐字节不变** |
| `Content-Length` | 45003 | 45003 | 内容一致 |
| 旧 ETag 重放 | — | `304 Not Modified` | 客户端零 body 复用 |

---

## 3. R1 的意义：canonical 投影是功能成立的前提

若 `ETag` 由**裸 body 哈希**派生，则每次跨 TTL 重生成时 `<lastBuildDate>` 变化都会使 `ETag` 改变 ⇒ 客户端重放旧校验器**永远得到 200** ⇒ 条件请求功能**静默失效**（表面 200，实则 304 永远不命中，带宽/回源开销无从节省）。

实测第 11 项证明：本实现的 `ETag` 由 **canonical 投影**（剔除 `lastBuildDate` / `ttl` / `pubDate` 三项派生元数据）计算。在 30s TTL 到期、条目重新回源、原始 XML 字节已变（`<lastBuildDate>` 从 `03:12:46` 变为 `03:13:42`）之后，`ETag` 仍**逐字节不变**，旧 ETag 重放稳定得 `304`。

> 结论：**R1 验证的是"ETag 语义正确性"，而非"缓存能否命中"**——这是条件请求在动态 feed 上真正可用的分水岭。

---

## 4. 边界与未覆盖项（如实登记）

| 项 | 说明 |
|----|------|
| 其余 3 个 feed 未逐个手测 | `/eastmoney/kuaixun`、`/ths/kuaixun`、`/wallstreetcn/live` 与已测两源共用 `_serve_feed` 路径；其 handler 层的 `<ttl>` / `ETag` 由 **P6c 单测覆盖**（`SRV-T52b` 三 feed + `SRV-T58`）。 |
| 「上游内容真变化 ⇒ ETag 变化 ⇒ 200」未在部署路径刻意构造 | 上游内容不可控，难以在部署路径稳定复现；由单测 **`SRV-T53`**（`test_t53_content_change_changes_etag_and_200`）覆盖。 |
| 小写 `w/` 只认字面大写 | 已在部署路径实测（第 10 项）——小写 `w/` 视为不匹配 ⇒ 200，与 `SRV-T50` 单测一致。 |

---

## 5. 已知语义取舍（评审 P2-2 / BR-SRV-38，设计已接受） — ⚠️ 已被 v2 取代（F1 后取舍不再成立：表示未变则 LM 不前进，IMS-only 亦 304）

- `Last-Modified` = **缓存写入时刻**（非上游发布时间）。
- 因此**仅携带 `If-Modified-Since`** 的客户端，跨 TTL 边界（写入时刻前进）时**仍会得到 200**；携带 `If-None-Match` 的客户端**不受影响**（以 canonical `ETag` 判定，见 §3）。
- 该取舍为设计已接受项，需在 `API.md` 注明（由编排层执行，本报告不改 `API.md`）。

---

## 6. 工具缺口登记

`.opencode/scripts/check-integration.sh` 为**模板级通用脚本**：按 `/health`、端口 `8000` 探测，且会自行另起服务——与本项目（**扁平包** / 端口 **8053** / 健康端点 **`/healthz`** / **服务已运行**）不符，**未采用**。

本报告的验证为**等价的、覆盖面更强的人工端到端验证**（11 项含 3 条负向/边界：第 6、8、10 项），并以容器内等 28s 跨 TTL 复现 R1（第 11 项），覆盖面超出该模板脚本能力。

---

## 7. 落盘后抽查复核（本报告撰写时）

撰写本报告时在**同一运行中容器**上抽查复核 3 条（未改任何业务代码/配置）：

| 复核项 | 命令 | 结果 | 与原始证据一致 |
|--------|------|------|----------------|
| 首次 200 校验器（第 1 项） | `GET /cls/telegraph` | `200` + 同款 `ETag W/"80fbcb…e000"` + `Cache-Control: private, max-age=30` + `Vary`（`Last-Modified` 随缓存重写变为 `03:14:50`） | ✅ |
| INM 命中 ⇒ 304（第 4 项） | `-H 'If-None-Match: W/"80fbcb…e000"'` | `304 Not Modified`，含 `ETag`/`Last-Modified`/`Cache-Control`/`Vary`，**无 `Content-Type`/`Content-Length`**、无 body | ✅ |
| INM 不匹配 ∧ IMS 命中 ⇒ 200（第 6 项） | `-H 'If-None-Match: W/"deadbeef"' -H 'If-Modified-Since: …'` | `200` + `Content-Length: 45003` | ✅ |
| 小写 `w/` ⇒ 200（第 10 项） | `-H 'If-None-Match: w/"80fbcb…e000"'` | `200` + `Content-Length: 45003` | ✅ |

---

## 8. 结论（v1）— ⚠️ 已被 v2 取代

**✅ P6d 通过（11/11，仅限 F1 修复前的语义）**

- 11 项端到端验证全部通过；其中 3 条为负向/边界（第 6、8、10 项），第 11 项为跨 TTL 的 R1 决定性证据。
- 部署路径已证明：首次 200 携带弱 `ETag`/`Last-Modified`；`ETag` 命中 ⇒ 304（无 body / 无 `Content-Encoding`）；`INM` 不匹配优先级正确；`<ttl>` 落位正确；静态 `/opml.xml` 恒 200 且无 `ETag`；**canonical 投影使 ETag 跨 TTL 重生成不变**。
- 无 P0/P1/P2 缺陷；未覆盖项（其余 feed、上游内容变化场景）已如实登记，均由对应 P6c 单测闭合。

---

- **本报告仅写入 `doc/tester/**`**，未改动业务代码、`doc/detailed/**`、`doc/arch/**`、`doc/prd/**`、`API.md`、`README.md`、`.opencode/**`、`opencode.json`、`_MEMORY_CACHE.md`。

---
---

# v2 重验：P8 修复（F1–F8）后的真实部署条件请求证据

- **日期/时间**：2026-09-18 `04:35:12–04:45:02 UTC`（北京时间 `12:35–12:45`，**午间休市**）
- **镜像**：`china-finance-rss-rss:latest` · IMAGE ID **`0389aae5023d`**（`docker compose up -d --build` 重建；`COPY china_finance_rss/`，构建上下文含工作区**未提交**的 F1–F8 改动）
- **代码版本**：`git HEAD ad2a27f`（分支 `feature/stream-push`）+ 工作区未提交改动 `china_finance_rss/{server,cache,metrics}.py`
- **容器**：`china-finance-rss`（compose service `rss`），端口 **8053**(HTTP) / **8054**(SSE)
- **实测策略（关键）**：`GET /healthz?check=0` → `policy.feed = {tier:"L3", ttl:180, pool_refresh:180, pool_max:100, cache_max:100}`。当前为**非交易时段**，故实测 TTL=**180s**（非 v1 的盘中 30s）；据此等待 **195.4s** 跨过一次完整 TTL。**以实际 policy 为准**，F1 机制不依赖 TTL 数值。
- **可复跑工具**：`doc/tester/verify_conditional_get_v2.py`（纯标准库）；本次输出 `checks` 全绿、`failures: []`。突变复现：`doc/tester/mutate_p8_conditional_get.py`。

## V2-0. 结论摘要

| 项 | 结果 |
|---|---|
| 端到端断言 | ✅ **25/25 通过**（脚本 `pass: true`） |
| **F1 决定性证据** | ✅ 跨 TTL 重生成：`<lastBuildDate>` `04:35:12 → 04:38:45`（**前进**）而 `Last-Modified` `04:35:12`、`ETag` `W/"c1f04a…dd8"` **逐字不变**；**仅带 IMS** ⇒ **`304`** |
| F2 跨 Host 键隔离 | ✅ 两 Host 各自 `atom:link` 正确、互不串号，`ETag` 不同，`a.example` 条件请求 ⇒ `304` |
| F3 `http_304_total` | ✅ 200 不变、304 后 +1；末值 = 基线 + 观测 304 数（6+6=12） |
| F6 304 头集合 | ✅ 恰为 `{server,date,etag,last-modified,cache-control,vary}`，无 `Content-Length/Type/Encoding`、无 body |
| F8 旁证 | ✅ 50 个不同 Host 串行均 `200`；内存 `554.6→547.3 MiB`（未增长），PIDS 319 不变 |
| 范围回归 | ✅ `/opml.xml`、`/`、`/stock/data` 带条件头仍 `200` 且行为不变 |
| 全量单测 | ✅ **511/511 OK** |
| 独立突变复现 | ✅ 4/4 按预期翻红（M1 继承/M2 键/M3 finally/M4 incr） |
| 交付判定 | ✅ **通过**；无 P0/P1 缺陷 |

## V2-1. 逐条命令与原始响应

### V2-1.1 部署与策略基线

```console
$ docker compose up -d --build
# … Container china-finance-rss Recreated / Started
$ docker compose ps
china-finance-rss  china-finance-rss-rss  …  Up …  0.0.0.0:8053-8054->8053-8054/tcp
$ docker compose images
china-finance-rss  china-finance-rss-rss  latest  linux/amd64  0389aae5023d  324MB  …
$ curl -s -o /tmp/opencode/healthz_t0.json 'http://127.0.0.1:8053/healthz?check=0'
# 解析：status=ok；policy.feed={tier:L3,ttl:180,…}；metrics.http_304_total=0；http_503_total=0
$ curl -sS -o /dev/null -w 'sse_port_8054=%{http_code}\n' \
    http://127.0.0.1:8054/stream/subscriptions/probe
sse_port_8054=404            # SSE 监听存活（未知 sid 的预期 404），8054 已起
```

### V2-1.2 F1 决定性证据（跨一次完整 TTL，实测 195.4s）

命令（与脚本 `verify_conditional_get_v2.py` 等价）：

```console
# ① 第一次 200（记录 ETag/Last-Modified/body <lastBuildDate>）
$ curl -sS -D - -o /dev/null http://127.0.0.1:8053/cls/telegraph
HTTP/1.0 200 OK
Server: BaseHTTP/0.6 Python/3.12.14
Content-Type: application/rss+xml; charset=utf-8
Content-Length: 39738
ETag: W/"c1f04afa6e21b72cc2f4a0f42d265618ecec2b9daf1eb91f4a881b8fd4a61dd8"
Last-Modified: Fri, 18 Sep 2026 04:35:12 GMT
Cache-Control: private, max-age=180
Vary: Host, X-Forwarded-Host, X-Forwarded-Proto, Accept-Encoding
# body: <lastBuildDate>Fri, 18 Sep 2026 04:35:12 GMT</lastBuildDate>

# ② 等待 > TTL(180s)，实际 195.4s 后无条件重放（证明真的回源重生成）
$ curl -sS -D - -o /dev/null http://127.0.0.1:8053/cls/telegraph
HTTP/1.0 200 OK
Content-Length: 39738                       # 逐字不变
ETag: W/"c1f04afa6e21b72cc2f4a0f42d265618ecec2b9daf1eb91f4a881b8fd4a61dd8"   # ★ 不变
Last-Modified: Fri, 18 Sep 2026 04:35:12 GMT                                  # ★ 不变
Cache-Control: private, max-age=180
Vary: Host, X-Forwarded-Host, X-Forwarded-Proto, Accept-Encoding
# body: <lastBuildDate>Fri, 18 Sep 2026 04:38:45 GMT</lastBuildDate>           # ★ 前进 213s

# ③ 仅带 If-Modified-Since（不带 If-None-Match）⇒ 必须 304（F1 验收点）
$ curl -sS -D - -o /dev/null -H 'If-Modified-Since: Fri, 18 Sep 2026 04:35:12 GMT' \
      http://127.0.0.1:8053/cls/telegraph
HTTP/1.0 304 Not Modified                        # ★ v1 此处为 200
Server: BaseHTTP/0.6 Python/3.12.14
ETag: W/"c1f04afa6e21b72cc2f4a0f42d265618ecec2b9daf1eb91f4a881b8fd4a61dd8"
Last-Modified: Fri, 18 Sep 2026 04:35:12 GMT
Cache-Control: private, max-age=180
Vary: Host, X-Forwarded-Host, X-Forwarded-Proto, Accept-Encoding
```

> **与 v1 的直接对照**：v1 §2 记录 `Last-Modified` `03:12:46→03:13:42`（前进）、`ETag` 不变、IMS 跨 TTL 得 `200`（v1 §5）；v2 记录 `Last-Modified` **不变**、`<lastBuildDate>` 前进、IMS-only 得 **`304`**。这正是 F1 指纹继承（相同指纹继承 `prev.last_modified`）的目的行为。
>
> **时序透明说明**：②「第一次 200」读取的是本脚本「零等待冒烟」（`--skip-f8 --wait 0`）在 `04:35:12` 写入的同键缓存条目（`Last-Modified=04:35:12`）。因此 ③ 的第二次请求发生在 `04:38:45`，该条目实际年龄 **213s > TTL 180s**，确已跨过一次完整 TTL 并回源重生成；继承比较的 `prev` 即该条目。基线条目由哪一次请求写入不影响结论（决定性证据是 `lastBuildDate` 前进而 LM/ETag 不变 + IMS-only 304）。

**附：真实内容变化时的反向验证（自然实验）**：`04:38:45` 缓存条目于 `04:41:45` 过期后，`04:44:55` 的正常请求返回了**新的** `ETag W/"85462cda…6d1ae4"` 且 `Last-Modified` 前进到 `04:44:55`、`Content-Length 40632`（上游新增条目）。即不变式 **`ETag 变 ⟺ Last-Modified 前进`** 两个方向均在部署路径观测到。

### V2-1.3 304 响应头集合（F6）

```console
$ curl -sS -D - -o /dev/null \
    -H 'If-None-Match: W/"85462cda04771dfaa3dbdeefb94305533ef7c485c814305be889c2b8436d1ae4"' \
    http://127.0.0.1:8053/cls/telegraph
HTTP/1.0 304 Not Modified
Server: BaseHTTP/0.6 Python/3.12.14
Date: Fri, 18 Sep 2026 04:45:01 GMT
ETag: W/"85462cda04771dfaa3dbdeefb94305533ef7c485c814305be889c2b8436d1ae4"
Last-Modified: Fri, 18 Sep 2026 04:44:55 GMT
Cache-Control: private, max-age=180
Vary: Host, X-Forwarded-Host, X-Forwarded-Proto, Accept-Encoding
# 无 Content-Length / Content-Type / Content-Encoding；无 body（EOF 收尾，HTTP/1.0）
```

脚本对 4 类 304（INM、IMS-only、`HEAD`、`gzip+INM`）断言头名集合**恰等于** `{server,date,etag,last-modified,cache-control,vary}`（`missing=[] forbidden=[] body_len=0`），且与 200 的 `ETag/Last-Modified/Cache-Control/Vary` **同值**。`HEAD` 同路径 `-H 'If-None-Match: …'` 亦 `304`。

### V2-1.4 `http_304_total` 可观测（F3，读 `/healthz.metrics`）

| 时点 | `metrics.http_304_total` | 说明 |
|---|---|---|
| 基线（重建后，无业务请求） | `0` | — |
| 一次 200 之后 | `0` | **200 不计数** |
| 一次 `If-None-Match` 命中 304 后 | `1` | **+1** |
| 再一次 IMS-only 304 后 | `2` | 单调 +1 |
| 本次会话结束（`HEAD`/`gzip`/`Host-a` 条件 304 + 跨 TTL IMS 304） | `12` | = 基线 `6` + 观测到的 304 总数 `6` |

脚本最终断言 `final == baseline + observed_304s` 通过（`6 + 6 = 12`）⇒ **只在 304 时增长**。

### V2-1.5 跨 Host 键隔离（F2）

> **配置说明**：`docker-compose.yml` 将 `PUBLIC_BASE_URL=` 设为**空串**；`config.py:21` `os.getenv('PUBLIC_BASE_URL','').rstrip('/')` ⇒ `''`，`server.py:846 if PUBLIC_BASE_URL:` 为假 ⇒ **等价于未设置**，F2 的 Host 派生键路径**在现有 compose 下即生效**（无需另起实例）。

```console
$ curl -sS -o /tmp/opencode/host_a.xml -H 'Host: a.example' http://127.0.0.1:8053/cls/telegraph
$ curl -sS -o /tmp/opencode/host_b.xml -H 'Host: b.example' http://127.0.0.1:8053/cls/telegraph
# 两份 body 的 <atom:link rel="self">：
a: <atom:link href="http://a.example/cls/telegraph" rel="self" type="application/rss+xml"/>
b: <atom:link href="http://b.example/cls/telegraph" rel="self" type="application/rss+xml"/>
# b 的 body 内含 "a.example": False    a 的 body 内含 "b.example": False   （互不串号）
```

- **ETag 不同**（脚本）：`a = W/"b3ab629aa5a1bdd309f14371bc972b9d9a77f696b524cea60f531c3ebc2180c0"`，`b = W/"b9d30f1942198495e02d5a29989a927dafc80410b192001e0c799b57aa00cfa7"`（Host 派生 `atom:link` 落在指纹内）。
- 以 `Host: a.example` + `If-None-Match: <etag_a>` ⇒ **`304`**。
- `Cache-Control: private, max-age=180` + `Vary: Host, X-Forwarded-Host, X-Forwarded-Proto, Accept-Encoding`（头与行为一致）。

### V2-1.6 F8 锁表收敛的端到端旁证

```console
$ docker stats --no-stream    # 前：china-finance-rss  MEM 554.6MiB / 1.5GiB  PIDS 319
$ python3 -c "…串行请求 50 个不同 Host 的 /cls/telegraph…"
count=50 distinct=[200] secs=0.12
$ docker stats --no-stream    # 后：china-finance-rss  MEM 547.3MiB / 1.5GiB  PIDS 319
$ curl -s -o /dev/null -w 'healthz=%{http_code} time=%{time_total}s\n' \
    'http://127.0.0.1:8053/healthz?check=0'
healthz=200 time=0.001287s
```

50 个不同 Host 串行请求后服务**仍正常响应**（全 `200`），内存**未增长**（略降，GC），PIDS 不变，健康检查 `200`/1.3ms。白盒收敛断言由 `SRV-T71`/`T-CACHE-35`/`SRV-T72②` 覆盖（见 V2-1.8 突变 M2/M3），本步仅为端到端旁证。

### V2-1.7 范围与回归

| 请求 | 实测 | 判定 |
|---|---|---|
| `/opml.xml` + `If-None-Match`/`If-Modified-Since` | `200`，`Content-Type: text/x-opml; charset=utf-8`，**无 `ETag`** | ✅ 行为不变 |
| `/` | `200` | ✅ |
| `/stock/data?code=sh600519` + 条件头 | `200`（body 9427B） | ✅ 不误 304 |
| `/healthz?check=0` | `200`，`status: ok` | ✅ |
| 小写 `w/` 前缀 | `200`（只认字面大写 `W/`，与 `SRV-T50` 一致） | ✅ |
| `INM` 不匹配 ∧ `IMS` 本会命中 | `200` + 完整体 39738B（优先级正确） | ✅ |

### V2-1.8 全量单测 + 独立突变复现

```console
$ python3 -m unittest discover -s tests
Ran 511 tests in 5.111s
OK
```

**独立突变（在 `/tmp/opencode/mut/<variant>` 复制包注入，绝不改仓库；基线副本 511 OK）**：

| 突变 | 注入点 | 翻红用例（实际） | 预期 | 结果 |
|---|---|---|---|---|
| M1 禁用指纹继承（`and False`） | `cache.py::feed_cache_put` | `T-CACHE-33`、`SRV-T63`、`SRV-T64`、`T55` | 至少 T63/T64/T-CACHE-33 | ✅ 4 红 |
| M2 `_feed_cache_key` 恒返回 `path` | `server.py` | `SRV-T65`、`SRV-T71` | T65/T71 | ✅ 2 红 |
| M3 `release` 移出 `finally`（仅成功路径） | `server.py::_get_or_fetch_feed` | `SRV-T72②`(异常路径回收)、`SRV-T72①`(并发) | T72② | ✅ 2 红 |
| M4 删除 `http_304_total` 计数 | `server.py::_send_not_modified` | `SRV-T66` | T66 | ✅ 1 红 |

四个突变各自只让对方**预期用例**翻红、无附带假绿/假红；证明这些用例具备真实证伪能力，评审 §五/§六 的**静态推演判定被升格为实证**。

## V2-2. 未覆盖 / 受限项（如实登记）

| 项 | 说明 |
|---|---|
| **本次 TTL 为 `180s`（非盘中 `30s`）** | 验证时点为午间休市（北京 12:35–12:45），`/healthz.policy.feed.ttl=180`。已按**实际 policy** 跨越 180s（等待 195.4s）。F1 的继承机制与 TTL 数值无关（`feed_cache_put` 比对指纹而非时长）；盘中 30s 路径由 `SRV-T63`（受控时钟跨 3600s）覆盖。 |
| **未用 `docker exec`** | 本会话 shell 白名单不含 `docker exec`，故未用容器内触发；改用只读端点（`/healthz`、`curl`）与等待实测，未规避权限。 |
| 其余 4 个 feed 未逐个手测 | `/jin10/flash`、`/eastmoney/kuaixun`、`/ths/kuaixun`、`/wallstreetcn/live` 与已测 `/cls/telegraph` 共用 `_serve_feed`/`_get_or_fetch_feed` 路径；其 `<ttl>`/ETag 由 P6c 单测（`SRV-T52b`、`SRV-T58`）覆盖。 |
| F8 锁表条目数无外部端点可观测 | 端到端仅能给出「50 Host 后不失控 + 内存不增长」旁证；精确收敛由白盒 `SRV-T71`/`T-CACHE-35` 覆盖。 |
| `PUBLIC_BASE_URL` 非空的键不随 Host 变 | 现有 compose 为空串（等价未设），故未另起「设了 `PUBLIC_BASE_URL`」的实例；该分支由 `SRV-T65` 第二段（`patch` 设为 `https://feeds.example.com` 后仅 1 个键）覆盖。 |

## V2-3. 最终统计

- **端到端断言：25/25 通过**（`verify_conditional_get_v2.py`，`pass: true`，`failures: []`）。
- **关键证据**：① F1 跨 180s TTL：`<lastBuildDate>` `04:35:12→04:38:45`，`Last-Modified`/`ETag`/`Content-Length` 逐字不变，**IMS-only ⇒ 304**；② 304 头集合无 `Content-*`；③ `http_304_total` 只在 304 时 +1（`6→12`，与观测 304 数一致）；④ F2 两 Host 自链接正确、ETag 不同、互不串号；⑤ F8 50 Host 全 200、内存未增长；⑥ 全量单测 **511/511 OK**；⑦ 4/4 突变按预期翻红。
- **未通过项：0。未能验证项：0**（受限项已列 V2-2，均有对应单测闭合或已说明）。
- **缺陷**：无 P0/P1/P2 缺陷。
- **交付判定**：✅ **通过**。

> 本 v2 节仅写入 `doc/tester/**`（本报告 + `verify_conditional_get_v2.py` + `mutate_p8_conditional_get.py`）；未改动业务代码、`tests/**`、`doc/detailed/**`、`doc/arch/**`、`doc/prd/**`、`API.md`、`README.md`、`.opencode/**`、`opencode.json`。突变仅在 `/tmp/opencode/mut/**` 的副本上进行。
