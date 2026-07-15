# China Finance RSS Bridge API 文档

Base URL: `http://localhost:8053`

---

## 目录

- [1. RSS 订阅源](#1-rss-订阅源)
- [2. 个股数据 API（JSON）](#2-个股数据-apijson)
- [3. 市场数据 API（JSON）](#3-市场数据-apijson)
- [4. 工具端点](#4-工具端点)

---

# 1. RSS 订阅源

所有 RSS 端点返回 `application/rss+xml`（RSS 2.0）。支持 `HEAD` 和 `GET` 方法。

---

### `GET /cls/telegraph`

**财联社电报** — 实时金融快讯。

- **内容类型**: `application/rss+xml; charset=utf-8`
- **来源**: `https://www.cls.cn/v1/roll/get_roll_list`
- **缓存**: 300s（交易时段 30s）
- **请求参数**: 无
- **响应格式**: RSS 2.0 XML

**响应字段（RSS `<item>` 元素）**:

| 字段 | 类型 | 说明 |
|------|------|------|
| `title` | string | 快讯标题（截取至完整首句，最长 120 字符） |
| `link` | string | 详情页 URL `https://www.cls.cn/detail/{id}` |
| `description` | string | 快讯全文内容 |
| `pubDate` | string | RFC 822 格式发布时间 |
| `guid` | string | 唯一标识 `cls_{id}` |

---

### `GET /eastmoney/kuaixun`

**东方财富快讯** — 7×24 快讯。

- **内容类型**: `application/rss+xml; charset=utf-8`
- **来源**: `https://newsapi.eastmoney.com/kuaixun/v1/getlist_102_ajaxResult_50_1_.html`
- **缓存**: 300s（交易时段 30s）
- **请求参数**: 无
- **响应格式**: RSS 2.0 XML

**响应字段（RSS `<item>` 元素）**:

| 字段 | 类型 | 说明 |
|------|------|------|
| `title` | string | 快讯标题 |
| `link` | string | 原文链接 |
| `description` | string | 快讯摘要（`digest`）或标题 |
| `pubDate` | string | RFC 822 格式发布时间 |
| `guid` | string | 唯一标识 `eastmoney_{newsid}` |

---

### `GET /ths/kuaixun`

**同花顺快讯** — 7×24 快讯。

- **内容类型**: `application/rss+xml; charset=utf-8`
- **来源**: `https://news.10jqka.com.cn/tapp/news/push/stock/?page=1&tag=&track=website&pagesize=50`
- **缓存**: 300s（交易时段 30s）
- **请求参数**: 无
- **响应格式**: RSS 2.0 XML

**响应字段（RSS `<item>` 元素）**:

| 字段 | 类型 | 说明 |
|------|------|------|
| `title` | string | 快讯标题 |
| `link` | string | 原文链接 |
| `description` | string | `digest` 或 `remark` 内容 |
| `pubDate` | string | RFC 822 格式发布时间（Unix 时间戳转换） |
| `guid` | string | 唯一标识 `ths_{seq}` |

---

### `GET /jin10/flash`

**金十快讯** — 7×24 快讯。

- **内容类型**: `application/rss+xml; charset=utf-8`
- **来源**: `https://flash-api.jin10.com/get_flash_list?channel=-8200&limit=50`
- **缓存**: 300s（交易时段 30s）
- **请求参数**: 无
- **响应格式**: RSS 2.0 XML

**响应字段（RSS `<item>` 元素）**:

| 字段 | 类型 | 说明 |
|------|------|------|
| `title` | string | 快讯标题（`data.title`）或 HTML 剥离内容的前 100 字符 |
| `link` | string | 来源链接或 `https://flash.jin10.com/detail/{id}` |
| `description` | string | 去 HTML 标签后的内容 |
| `pubDate` | string | RFC 822 格式发布时间 |
| `guid` | string | 唯一标识 `jin10_{id}` |

---

### `GET /wallstreetcn/live`

**华尔街见闻快讯** — 7×24 快讯。

- **内容类型**: `application/rss+xml; charset=utf-8`
- **来源**: `https://api-one-wscn.awtmt.com/apiv1/content/lives?channel=global-channel&client=pc&limit=50`
- **缓存**: 300s（交易时段 30s）
- **请求参数**: 无
- **响应格式**: RSS 2.0 XML

**响应字段（RSS `<item>` 元素）**:

| 字段 | 类型 | 说明 |
|------|------|------|
| `title` | string | 快讯标题或内容前 100 字符 |
| `link` | string | 原文 URI 或 `https://wallstreetcn.com/livenews/{id}` |
| `description` | string | `content_text` 或 HTML 剥离后的 `content` |
| `pubDate` | string | RFC 822 格式发布时间（`display_time` 或 `created_at`） |
| `guid` | string | 唯一标识 `wallstreetcn_{id}` |

---

# 2. 个股数据 API（JSON）

所有个股端点返回 `application/json; charset=utf-8`。接受 `?code=` 查询参数，支持批量查询（逗号分隔，上限 50 只）。

**通用请求参数**:

| 参数 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `code` | string | 是 | 股票代码，格式 `{市场}{6位数字}`，如 `sh600519`。支持逗号分隔批量查询，如 `sh600519,sz000001` |

**通用响应结构**（批量查询多只时返回 `{"code1": data1, "code2": data2}`；单只查询时直接返回到 `{"code": data}`）：

---

### `GET /stock/data` ⚡ 需要 Chrome CDP

**个股详情聚合** — 整合 REST API + CDP 导航的多种数据。

- **CDP**: 是（依赖 Chrome CDP）
- **响应字段**:

| 字段 | 类型 | 说明 |
|------|------|------|
| `stock_detail` | object/null | 个股详情（REST API，`https://x-quote.cls.cn/quote/stock/detail`） |
| `stock_announcement` | object/null | 个股公告列表（REST API） |
| `stock_plate` | object/null | 所属板块（CDP evaluate_fetch） |
| `articles` | array/null | 相关文章（CDP 页面导航） |

**`stock_detail` 字段**:

| 字段 | 类型 | 说明 |
|------|------|------|
| `secu_code` | string | 证券代码 |
| `secu_name` | string | 证券名称 |
| `latest_price` | number | 最新价 |
| `change` | number | 涨跌额 |
| `change_pct` | number | 涨跌幅（%） |
| `high` | number | 最高价 |
| `low` | number | 最低价 |
| `open` | number | 开盘价 |
| `pre_close` | number | 昨收价 |
| `volume` | number | 成交量 |
| `amount` | number | 成交额 |
| `turnover_rate` | number | 换手率（%） |
| `pe` | number | 市盈率 |
| `pb` | number | 市净率 |
| 其他字段 | — | 上游 API 返回的额外字段也会透传 |

**`stock_announcement` 字段**:

| 字段 | 类型 | 说明 |
|------|------|------|
| `list` | array | 公告列表 |
| `list[].id` | string | 公告 ID |
| `list[].title` | string | 公告标题 |
| `list[].time` | string | 发布时间 |
| `list[].url` | string | 公告链接 |

**`stock_plate` 字段**:

上游 CLS `stock/assoc_plate` API 返回的关联板块数据。

**`articles` 字段**:

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | string | 文章 ID |
| `title` | string | 文章标题 |
| `content` | string | 文章摘要 |
| `ctime` | number | 发布时间戳 |
| `link` | string | 文章链接 |

---

### `GET /stock/fundflow`

**个股资金流向** — 个股主力资金流入流出数据。

- **CDP**: 否（REST API + CDP evaluate_fetch 回退）
- **请求示例**: `?code=sh600519`
- **响应字段**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `code` | number | 状态码（200=成功） |
| `data` | object/null | 资金流向数据 |
| `data.main_inflow` | number | 主力净流入 |
| `data.main_inflow_pct` | number | 主力净占比（%） |
| `data.super_inflow` | number | 超大单净流入 |
| `data.big_inflow` | number | 大单净流入 |
| `data.mid_inflow` | number | 中单净流入 |
| `data.small_inflow` | number | 小单净流入 |
| 其他字段 | — | 上游 API 透传 |

---

### `GET /stock/timeline`

**个股分时图** — 个股当日分时走势数据。

- **CDP**: 否（REST API + CDP evaluate_fetch 回退）
- **请求示例**: `?code=sh600519`
- **响应字段**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `code` | number | 状态码（200=成功） |
| `data` | object | 分时数据 |
| `data.prices` | array | 价格序列 |
| `data.volumes` | array | 成交量序列 |
| `data.avg_price` | number | 均价 |
| `data.pre_close` | number | 昨收价 |
| 其他字段 | — | 上游 API 透传 |

---

### `GET /stock/f10`

**个股 F10 财务概要** — 个股公司基本信息、财务数据（CDP 导航）。

- **CDP**: 是（依赖 Chrome CDP 导航到个股页面并点击 F10 选项卡）
- **请求示例**: `?code=sh600519`
- **响应字段**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `basic_info` | object | 基础信息 |
| `basic_info.SecuCode` | string | 证券代码 |
| `basic_info.SecuAbbr` | string | 证券简称 |
| `basic_info.IndustryName` | string | 行业名称（如 "食品饮料-白酒"） |
| `basic_info.ListingDate` | string | 上市日期 |
| `basic_info.TotalCapital` | number | 总股本 |
| `basic_info.NationalCapital` | number | 流通股本 |
| `basic_info.PrimaryBusiness` | string | 主营业务 |
| `ipo_info` | object/null | IPO 信息 |
| `finance_info` | object/null | 财务信息 |
| `finance_info.perShareEPS` | number | 每股收益 |
| `finance_info.perShareBV` | number | 每股净资产 |
| `finance_info.perShareCF` | number | 每股现金流 |
| `finance_info.roe` | number | 净资产收益率（%） |
| `finance_info.profitRatio` | number | 净利润率（%） |
| 其他字段 | — | 上游 API 透传 |

---

### `GET /stock/basic_info` ⚡ 需要 Chrome CDP

**个股基本信息** — 实时行情 + 行业板块归属。分两阶段：
1. REST API 获取实时行情（<100ms）
2. CDP 导航获取申万一级行业名称

- **CDP**: 是（需要 CDP 获取行业信息）
- **请求示例**: `?code=sh600519`
- **响应字段**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `code` | number | 状态码 |
| `data` | object | 行情数据 |
| `data.secu_code` | string | 证券代码 |
| `data.secu_name` | string | 证券名称 |
| `data.latest_price` | number | 最新价 |
| `data.change` | number | 涨跌额 |
| `data.change_pct` | number | 涨跌幅（%） |
| `data.high` | number | 最高价 |
| `data.low` | number | 最低价 |
| `data.open` | number | 开盘价 |
| `data.pre_close` | number | 昨收价 |
| `data.volume` | number | 成交量 |
| `data.amount` | number | 成交额 |
| `data.total_capital` | number | 总股本 |
| `data.circulated_capital` | number | 流通股本 |
| `data.total_market_value` | number | 总市值 |
| `data.circulated_market_value` | number | 流通市值 |
| `data.turnover_rate` | number | 换手率（%） |
| `data.pe` | number | 市盈率 |
| `data.pb` | number | 市净率 |
| `sector_name` | string/null | 申万一级行业名称（如 "食品饮料"），仅当 CDP 可用时 |

---

### `GET /stock/announcement`

**个股公告** — 个股公告列表（REST API + CLS 签名）。

- **CDP**: 否（REST API + CDP evaluate_fetch 回退）
- **请求示例**: `?code=sh600519`
- **响应字段**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `code` | number | 状态码（200=成功） |
| `data` | object | 公告数据 |
| `data.list` | array | 公告列表 |
| `data.list[].id` | string | 公告 ID |
| `data.list[].title` | string | 公告标题 |
| `data.list[].time` | string | 发布时间 |
| `data.list[].url` | string | 公告详情链接 |

---

# 3. 市场数据 API（JSON）

---

### `GET /finance/market` ⚡ 需要 Chrome CDP

**财联社看盘** — 财联社大盘情绪与数据面板。

- **CDP**: 是（依赖 Chrome CDP 持久页面）
- **请求参数**: 无
- **响应字段**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `market_sentiment` | object/null | 市场情绪指标（emotion） |
| `articles` | array/null | 要闻文章列表 |
| `advance_decline` | object/null | 涨跌家数（up_down） |
| `live_refresh` | object/null | 实时刷新数据 |
| `anchor` | object/null | 锚点/关注数据 |
| `basic_info` | object/null | 基础指数信息 |
| `ws_count` | number | 采集到的 WebSocket 消息总数（仅当 CDP 页面有 WS 数据时） |
| `ws_latest` | array | 最近 5 条 WebSocket 消息（仅当 CDP 页面有 WS 数据时） |

**`market_sentiment` 字段**:

| 字段 | 类型 | 说明 |
|------|------|------|
| `emotion` | string | 市场情绪（如 "积极"/"谨慎"） |
| `score` | number | 情绪评分 |

**`advance_decline` 字段**:

| 字段 | 类型 | 说明 |
|------|------|------|
| `up` | number | 上涨家数 |
| `down` | number | 下跌家数 |
| `flat` | number | 平盘家数 |
| `up_pct` | number | 上涨占比（%） |

**`basic_info` 字段**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `sh_index` | number | 上证指数 |
| `sz_index` | number | 深证成指 |
| `cy_index` | number | 创业板指 |

---

### `GET /finance/timeline` ⚡ 需要 Chrome CDP

**财联社看盘分时图** — 来自 finance CDP 页面的指数分时数据。

- **CDP**: 是
- **请求参数**: 无
- **响应**: 原始分时数据数组（tline 数据），格式由上游 CLS API 决定

---

### `GET /quotation/market` ⚡ 需要 Chrome CDP

**财联社行情** — 市场行情综合数据面板。

- **CDP**: 是
- **请求参数**: 无
- **响应字段**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `hot_plate` | object/null | 热门板块排行 |
| `stock_ranking` | object/null | 个股排名（涨跌幅） |
| `stock_ipo` | object/null | 新股信息 |
| `bj_stock_info` | object/null | 北交所股票信息 |
| `index_home` | object/null | 指数首页数据 |
| `basic_info` | object/null | 基础行情数据 |

---

### `GET /market/timeline` ⚡ 需要 Chrome CDP

**指数分时图** — 来自 quotation CDP 页面的指数分时数据。

- **CDP**: 是
- **请求参数**: 无
- **响应**: 原始分时数据数组（tline 数据）

---

### `GET /cls/hotplate`

**财联社板块** — 板块资金流向排行（行业、概念、地域）。

- **CDP**: 否（REST API，使用 CLS 签名）
- **来源**: `https://x-quote.cls.cn/web_quote/plate/plate_list`
- **请求参数**: 无
- **响应字段**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `plate_industry` | object | 行业板块排行 |
| `plate_industry.list` | array | 行业板块列表 |
| `plate_industry.list[].plate_name` | string | 板块名称 |
| `plate_industry.list[].change_pct` | number | 板块涨跌幅（%） |
| `plate_industry.list[].main_inflow` | number | 主力净流入 |
| `plate_concept` | object | 概念板块排行 |
| `plate_concept.list` | array | 概念板块列表（同上结构） |
| `plate_area` | object | 地域板块排行 |
| `plate_area.list` | array | 地域板块列表（同上结构） |
| `hot_plates` | array | 综合热门板块（合并 `main_fund_diff` 的 top + last） |
| `hot_plates[].plate_name` | string | 板块名称 |
| `hot_plates[].change_pct` | number | 涨跌幅 |
| `hot_plates[].main_fund_diff` | number | 主力资金净差 |

---

### `GET /ths/longhu`

**同花顺龙虎榜** — 龙虎榜数据明细（含买卖营业部 Top5）。

- **CDP**: 否（HTML 页面解析）
- **来源**: `https://data.10jqka.com.cn/ifmarket/lhbtable` + `https://data.10jqka.com.cn/market/longhu/`
- **请求参数**: 无
- **响应字段**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `data` | array | 龙虎榜股票列表 |
| `data[].code` | string | 股票代码 |
| `data[].name` | string | 股票名称 |
| `data[].price` | string | 最新价 |
| `data[].change_pct` | string | 涨跌幅（%） |
| `data[].turnover` | string | 成交额 |
| `data[].net_buy` | string | 净买入额 |
| `data[].buy_top5` | array | 买入金额最大的前 5 名营业部（如 HTML 解析到） |
| `data[].buy_top5[].name` | string | 营业部名称 |
| `data[].buy_top5[].buy` | string | 买入金额（万元） |
| `data[].buy_top5[].sell` | string | 卖出金额（万元） |
| `data[].buy_top5[].net` | string | 净额（万元） |
| `data[].sell_top5` | array | 卖出金额最大的前 5 名营业部（同上结构） |
| `total` | number | 总股票数 |

---

### `GET /market/margin`

**融资融券** — 两市融资融券余额、买入额等数据。

- **CDP**: 否（REST API）
- **来源**: `https://data.10jqka.com.cn/rzrq/fixdata/type/{market}/`
- **请求参数**:

| 参数 | 类型 | 必需 | 默认 | 说明 |
|------|------|------|------|------|
| `market` | string | 否 | `99` | `99`=合计, `1`=沪市, `2`=深市, `3`=京市 |

- **响应字段**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `latest` | object | 最新交易日数据 |
| `latest.date` | string | 日期（YYYY-MM-DD） |
| `latest.rzye` | number | 融资余额（亿元） |
| `latest.rqye` | number | 融券余额（亿元） |
| `latest.rzmre` | number | 融资买入额（亿元） |
| `latest.rzjmr` | number | 融资净买入（亿元） |
| `latest.rqjmc` | number | 融券净卖出（亿元） |
| `latest.lr` | number | 两融余额（亿元） |
| `latest.zb` | number | 占比（小数） |
| `recent` | array | 最近 30 个交易日数据（每项同上结构） |
| `_error` | string | 仅当请求失败时出现 |

---

### `GET /market/northbound`

**北向资金（沪深港通）** — 北向资金实时快照。

- **CDP**: 否（REST API）
- **来源**: `https://data.10jqka.com.cn/hsgt/basedata/type/north/`
- **请求参数**: 无
- **响应字段**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `sh` | object | 沪股通数据 |
| `sh.net_inflow` | number | 资金净流入 |
| `sh.remaining_quota` | number | 剩余额度 |
| `sh.total_quota` | number | 总额度 |
| `sh.buy_turnover` | number | 买入成交额 |
| `sh.sell_turnover` | number | 卖出成交额 |
| `sh.net_turnover` | number | 净成交额 |
| `sh.state` | string | 状态（如 "暂停"/"交易中"） |
| `sh.up_stocks` | number | 上涨股票数 |
| `sh.mid_stocks` | number | 平盘股票数 |
| `sh.down_stocks` | number | 下跌股票数 |
| `sz` | object | 深股通数据（结构同 `sh`） |
| `total_net_inflow` | number | 沪深合计净流入 |
| `total_net_buy` | number | 沪深合计净买入 |
| `update_date` | string | 数据更新日期 |
| `unit` | string | 金额单位（"元"） |
| `_error` | string | 仅当请求失败时出现 |

---

### `GET /market/northbound/history`

**北向资金历史** — 北向资金历史走势数据。

- **CDP**: 否（REST API）
- **来源**: `https://data.10jqka.com.cn/hsgt/history/type/north/date/{period}/`
- **请求参数**:

| 参数 | 类型 | 必需 | 默认 | 说明 |
|------|------|------|------|------|
| `period` | string | 否 | `day` | 周期：`day`（日）, `week`（周）, `month`（月）, `quarter`（季）, `year`（年） |

- **响应字段**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `dates` | array | 日期数组 |
| `data` | array | 数据数组（与 dates 一一对应） |
| `_error` | string | 仅当请求失败时出现 |

每个 `data` 元素包含：

| 字段 | 类型 | 说明 |
|------|------|------|
| `jlr` | number | 净流入 |
| `jmr` | number | 净买入 |
| `sh_zjlr` | number | 沪股通净流入 |
| `sz_zjlr` | number | 深股通净流入 |

---

# 4. 工具端点

---

### `GET /`

**首页** — 返回 HTML 页面，以表格形式列出所有可用端点。

- **内容类型**: `text/html; charset=utf-8`
- **请求参数**: 无
- **响应**: HTML 页面，按类型（RSS / JSON）和 CDP 依赖进行标记

---

### `GET /opml.xml`

**OPML** — 返回 OPML 2.0 格式的订阅列表，可导入 RSS 阅读器。

- **内容类型**: `text/x-opml; charset=utf-8`
- **请求参数**: 无
- **响应**: OPML XML，包含所有 RSS 订阅源

---

### `GET /healthz`

**健康检查** — 返回服务器状态和所有端点的健康信息。

- **内容类型**: `application/json; charset=utf-8`
- **请求参数**:

| 参数 | 类型 | 必需 | 默认 | 说明 |
|------|------|------|------|------|
| `check` | string | 否 | `0` | `1`/`true`/`yes` 时逐一检查每个 RSS 源是否可达 |

- **响应字段**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `status` | string | `"ok"` 或 `"degraded"`（任一源出错时） |
| `cache_ttl` | number | 全局缓存 TTL（秒） |
| `request_timeout` | number | 全局请求超时（秒） |
| `feeds` | array | 各端点状态列表 |
| `feeds[].name` | string | 端点名称 |
| `feeds[].path` | string | 端点路径 |
| `feeds[].url` | string | 完整 URL |
| `feeds[].status` | string | `"configured"`/`"ok"`/`"error"`/`"requires_chrome_cdp"` |
| `feeds[].items` | number | 仅当 `check=1` 时：RSS 源的条目数 |
| `feeds[].error` | string | 仅当 `check=1` 且出错时 |

---

## 通用说明

### 错误响应

所有 JSON 端点在出错时返回 `{"error": "错误描述"}`，HTTP 状态码 400 或 200（取决于端点）。例如 `?code` 参数缺失时：

```json
{
  "error": "Missing ?code= parameter. Usage: /stock/...?code=sh600519 or ...?code=sh600519,sz000001"
}
```

### CDP 依赖端点的错误

当 Chrome CDP 不可用时，CDP 依赖端点返回：

```json
{
  "error": "Chrome CDP not available. See README."
}
```

### 缓存

- RSS 源: 缓存 `CACHE_TTL` 秒（默认 300s），交易时段降为 30s，带 ±20% 抖动防雪崩
- REST JSON API: 使用全局 URL 缓存（`cache.py`），带 stampede protection（Leader Election）

### 并发

- 服务器使用 `BoundedThreadPoolServer`，默认最大 20 个工作线程
- 每个 RSS 源有独立锁防止并发取回
- 个股导航通过 `_navigate_lock` 实现公平排队
