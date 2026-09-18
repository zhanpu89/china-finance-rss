# RSS 条件请求 P6d 真实部署路径集成验证报告

- **日期**：2026-09-18 · **阶段**：P6d 集成验证（真实部署路径）
- **环境**：`docker compose up -d --build` 重建容器 `china-finance-rss`，端口 **8053**；盘中时段 ⇒ feed TTL **30s**
- **方法**：在部署容器上以 `curl` 完成 RSS 条件请求端到端验证（编排层执行，本报告据实落盘）
- **依据**：`doc/detailed/server.md` v1.7 §8（条件请求 / `ETag` / `<ttl>`）；`doc/review/rss-conditional-get_代码评审_专家版.md` P2-2 / BR-SRV-38
- **结论**：✅ **P6d 通过（11/11）**

---

## 1. 验证矩阵（11 项全通过）

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

## 2. 第 11 项明细（R1 决定性证据）

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

## 5. 已知语义取舍（评审 P2-2 / BR-SRV-38，设计已接受）

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

## 8. 结论

**✅ P6d 通过（11/11）**

- 11 项端到端验证全部通过；其中 3 条为负向/边界（第 6、8、10 项），第 11 项为跨 TTL 的 R1 决定性证据。
- 部署路径已证明：首次 200 携带弱 `ETag`/`Last-Modified`；`ETag` 命中 ⇒ 304（无 body / 无 `Content-Encoding`）；`INM` 不匹配优先级正确；`<ttl>` 落位正确；静态 `/opml.xml` 恒 200 且无 `ETag`；**canonical 投影使 ETag 跨 TTL 重生成不变**。
- 无 P0/P1/P2 缺陷；未覆盖项（其余 feed、上游内容变化场景）已如实登记，均由对应 P6c 单测闭合。

---

- **本报告仅写入 `doc/tester/**`**，未改动业务代码、`doc/detailed/**`、`doc/arch/**`、`doc/prd/**`、`API.md`、`README.md`、`.opencode/**`、`opencode.json`、`_MEMORY_CACHE.md`。
