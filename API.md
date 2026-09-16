# China Finance RSS Bridge API 文档

Base URL: `http://localhost:8053`

---

## 目录

- [1. RSS 订阅源](#1-rss-订阅源)
- [2. 个股数据 API（JSON）](#2-个股数据-apijson)
- [3. 市场数据 API（JSON）](#3-市场数据-apijson)
- [4. 工具端点](#4-工具端点)
- [5. SSE 实时推送](#5-sse-实时推送端口-8054)
- [6. 接入指南](#6-接入指南)
- [7. 通用说明](#7-通用说明)

---

# 1. RSS 订阅源

所有 RSS 端点返回 `application/rss+xml`（RSS 2.0）。支持 `HEAD` 和 `GET` 方法。

---

### `GET /cls/telegraph`

**财联社电报** — 实时金融快讯。

- **内容类型**: `application/rss+xml; charset=utf-8`
- **来源**: `https://www.cls.cn/v1/roll/get_roll_list`
- **缓存**: 180s（交易时段 30s）
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
- **缓存**: 180s（交易时段 30s）
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
- **缓存**: 180s（交易时段 30s）
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
- **缓存**: 180s（交易时段 30s）
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
- **缓存**: 180s（交易时段 30s）
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

所有个股端点返回 `application/json; charset=utf-8`。接受 `?code=` 查询参数，支持批量查询（逗号分隔，上限 50 只）。**批量时以 `code` 为顶层键**（`{"sh600519": {...}, "sz000001": {...}}`）；单只查询时同样返回 `{"code": data}` 包裹。

> **数值单位约定（全章适用）**：`change` / `tr` / `amp` / `change_3` / `change_5` / `change_1y` 等带「率/比/幅」语义的字段均为**小数**，不是百分比数值——`change: -0.0116` 表示 **-1.16%**，`tr: 0.0021` 表示 **0.21%**。换算公式：百分比 = 小数值 × 100。

---

### `GET /stock/data`

**个股行情详情** — CLS x-quote 详情（REST 直调，原样透传上游返回）。

- **CDP**: 否
- **顶层键**：`{"<code>": {...}}`；内容为上游 `data` 客体原样透传（含 `label`/`plate`/`plate_rel`/`primary_industry`/`event` 等），**不做字段映射**；`label` 内为多维标签位（`suspend`/`financing`/`tong`/`sh`/`sz`/`index`/`stock`/`kcb` + 对应 `*_desc` 描述文本）。

| 字段 | 类型 | 说明 |
|------|------|------|
| `primary_industry` | object/null | 申万一级行业：`{plate_code, plate_name, change}`（`change` 为小数） |
| `plate` | array | 所属板块列表：`{secu_code, secu_name, change(小数), assoc_desc}` |
| `plate_rel` | array | 相关板块详情：`{plate_code, plate_name, change(小数), is_most_relevant, assoc_desc}` |
| `label` | object | 标签位集合（含 `*_desc` 中文描述，如 `融资融券标的`/`沪股通/深股通`）；`kcb`=科创板等 |
| `event` | object/null | 近期事件：`{content, secu_code, time, type}` |
| `up_reason` / `up_time` | string | 上涨原因 / 触发时间（无则为 `""`） |
| `growth_ms` | string/null | 增长里程碑（如无为 `null`） |

---

### `GET /stock/fundflow`

**个股资金流向** — CLS 口径主力资金流（REST 直调）。

- **CDP**: 否（REST API + CDP evaluate_fetch 回退）
- **顶层键**：`{"<code>": {...}}`

| 字段 | 类型 | 说明 |
|------|------|------|
| `main_fund_in` | number | 主力净流入（**元**） |
| `main_fund_out` | number | 主力净流出（**元**） |
| `main_fund_diff` | number | 主力净额 = 流入 - 流出（**元**） |
| `super_fund_diff` | number | 超大单净额（元） |
| `large_fund_diff` | number | 大单净额（元） |
| `medium_fund_diff` | number | 中单净额（元） |
| `little_fund_diff` | number | 小单净额（元） |
| `main_fund_3` / `_5` / `_10` / `_20` | number | 近 3/5/10/20 日主力净额（元） |
| `date` | number | 数据日期 `YYYYMMDD`（如 `20260916`） |
| `min_time` | number | 数据时点（HHMM，如 `1524` = 15:24） |
| `year_up_ratio` | number | 年度上涨比例（小数，0~1） |
| `year_up_num` | number | 年内上涨天数 |
| `latest_up_date` | string/null | 最近上涨日期 |
| `year_avr_open_change` / `year_avr_close_change` | number/null | 年内开盘/收盘平均涨跌幅（小数） |

---

### `GET /stock/timeline`

**个股分时图** — 当日 241 点分时走势（REST 直调，一次取全）。

- **CDP**: 否（REST API + CDP evaluate_fetch 回退）
- **顶层键**：`{"<code>": {"date": [...], "line": [...]}}`

| 字段 | 类型 | 说明 |
|------|------|------|
| `date` | array | 分时日期（每元素 `YYYYMMDD`） |
| `line` | array | 分时点序列（**241 点**：09:30~11:30 + 13:00~15:00） |
| `line[].minute` | number | 分钟序号（`930` = 09:30，`1130`=11:30，`1300`=13:00…） |
| `line[].last_px` | number | 该分钟最新价 |
| `line[].av_px` | number | 均价 |
| `line[].change` | number | 涨跌幅（**小数**，如 `0.0009` = 0.09%） |
| `line[].change_px` | number | 涨跌额（元） |
| `line[].preclose_px` / `open_px` | number | 昨收 / 今开 |
| `line[].amp` | number | 振幅（**小数**） |
| `line[].change_color` | number | 涨跌色（1=红/涨，2=绿/跌，0=平） |
| `line[].business_amount` | number | 成交量（手） |
| `line[].business_balance` | number | 成交额（元） |
| `line[].purchases` / `sales` | number/null | 委买 / 委卖手数 |

---

### `GET /stock/f10` ⚡ 需要 Chrome CDP

**个股 F10 全景** — 公司资料 / IPO / 经营 / 财务 / 分红 / 股本股东（CDP 导航）。

- **CDP**: 是（依赖 Chrome CDP 导航到个股页面并点击 F10 选项卡）
- **顶层键**：`{"<code>": {...}}`

| 字段 | 类型 | 说明 |
|------|------|------|
| `basic_info` | object | 公司资料：`SecuCode`/`SecuAbbr`/`company_name`/`IndustryName`(食品饮料-白酒Ⅱ-白酒Ⅲ)/`plate_names`/`LegalRepr`/`GeneralManager`/`EstablishmentDate`/`RegCapital`/`BriefIntroText`/`main_business` 等 |
| `ipo_info` | object | IPO：`ListedDate`/`IssueVol`/`IssuePriceCeiling`/`IPOProceeds`/`WeightedPERatio`/`LotRateOnline` |
| `operation_overview` | array | 主营构成：`{revenue_structure, operating_revenue, operating_profit}`（字符串带单位） |
| `financial_analysis` | object | 财务：`eps`/`nav_ps`/`roe`/`debt_ratio`/`net_profit_margin`/`yoy_net_profit`/`yoy_revenue`/`total_revenue`/`net_profit`（**字符串带单位**，如 `'35.57元'`/`'17.72%'`，此处 % 为文本） |
| `dividend` | array | 分红记录：`{data(报告期), plan(每10股派息+登记/除权日)}` |
| `shares_and_holders` | object | 股本股东：`total_shares`/`a_shares_float`/`a_shares_holders_count` |

---

### `GET /stock/basic_info`

**个股基本信息** — 实时行情 + 行业归属（两阶段 REST：行情致命 + 行业非致命，命中 7 天 `sector` 缓存则跳过）。

- **CDP**: 否（纯 REST）
- **顶层键**：`{"<code>": {"code": 200, "msg": "", "data": {...}, "sector_name": "..."}}`

**`data` 内字段**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `secu_code` / `ori_code` | string | 证券代码（`sh600519`）/ 纯数字码（`600519`） |
| `secu_name` / `secu_type` | string | 证券名称 / 类型（`SHARE`） |
| `last_px` | number | 最新价 |
| `change_px` | number | 涨跌额（元） |
| `change` | number | 涨跌幅（**小数**，`-0.0116` = -1.16%） |
| `open_px` / `preclose_px` / `high_px` / `low_px` | number | 今开 / 昨收 / 最高 / 最低 |
| `tr` | number | 换手率（**小数**，`0.0021` = 0.21%） |
| `amp` | number | 振幅（**小数**，`0.0164` = 1.64%） |
| `business_amount` | number | 成交量（手） |
| `business_balance` | number | 成交额（元） |
| `qrr` | number | 量比（如 `1.1283`） |
| `mc` / `cmc` | number | 总市值 / 流通市值（元） |
| `change_3` / `change_5` / `change_1y` | number | 3 日 / 5 日 / 1 年涨跌幅（**小数**） |
| `up_price` / `down_price` | number | 涨停价 / 跌停价 |
| `av_px` | number | 均价 |
| `entrust_rate` | number | 委比（**小数**，`0.55` = 55%） |
| `purchases` / `sales` | number | 委买 / 委卖 |
| `pe` / `ttm_pe` / `dynamic_pe` | number | 市盈率（静态 / TTM / 动态） |
| `pb` | number | 市净率 |
| `TotalShares` / `NonRestrictedShares` | number | 总股本 / 流通股本（股） |
| `NetAssetPS` | number | 每股净资产 |
| `trade_status` | string | 交易状态（`ENDTR` = 收盘等） |
| `unlisted` | boolean | 是否未上市 |
| `trade_time` / `eoeId` / `market_enum` / `note` / `financing` | — | 内部扩展字段（常数/可空，忽略即可） |
| **`sector_name`**（顶层） | string/null | 申万一级行业名（如 `食品饮料行业`）；取数失败时缺省 |

---

### `GET /stock/announcement`

**个股公告列表** — CLS 口径（REST API + CLS 签名）。

- **CDP**: 否（REST API + CDP evaluate_fetch 回退）
- **顶层键**：`{"<code>": [公告数组]}`（**不是** `data.list`——code 直接对数组）

| 字段 | 类型 | 说明 |
|------|------|------|
| `[].id` | string | 公告 ID |
| `[].secu_code` | string | 证券代码 |
| `[].title` | string | 公告标题 |
| `[].time` | string | 发布时间（`YYYY-MM-DD HH:MM:SS`） |
| `[].timestamp` | number | 时间戳（秒） |
| `[].url` | string | 公告 PDF 链接 |

---

# 3. 市场数据 API（JSON）

所有市场端点返回 `application/json; charset=utf-8`。**带「率/比」语义的字段均为小数**（`0.048` = 4.8%），换算 = 小数值 × 100。

---

### `GET /finance/market` ⚡ 需要 Chrome CDP

**财联社看盘** — 大盘情绪与数据面板。

- **CDP**: 是（依赖 Chrome CDP 持久页面）；CDP 不可用时各键为 `null`/缺省
- **请求参数**: 无
- **响应**：顶层键 `live_refresh` / `basic_info` / `anchor` / `advance_decline` / `market_sentiment` / `articles` / `stock_quote`；每键为上游原样包裹 `{code|errno, msg, data}`。

| 字段 | 类型 | 说明 |
|------|------|------|
| `market_sentiment` | object/null | 市场情绪：`{code, msg, data}`，`data` 含情绪评分 |
| `advance_decline` | object/null | 涨跌家数：`{code, msg, data}`，`data` 含 `up`/`down`/`flat` 与占比 |
| `articles` | object/null | 要闻文章列表（上游 `errno` 包裹） |
| `live_refresh` | object/null | 实时刷新：`{code, msg, data}`，`data` 为 **码 → 涨跌幅（小数）** 映射（如 `{"sh000688": 0.0414}` = +4.14%） |
| `anchor` | object/null | 锚点/关注数据 |
| `basic_info` | object/null | 基础指数信息（`data.sh_index`/`sz_index`/`cy_index` 等） |
| `stock_quote` | object/null | 个股速览（上游 `data` 原样） |

---

### `GET /finance/timeline` ⚡ 需要 Chrome CDP

**财联社看盘分时图** — 指数分时数据。

- **CDP**: 是
- **请求参数**: 无
- **响应**：`{code, msg, data: [...]}`，`data` 为分时点数组，元素结构与个股分时 `line[]` 一致（`minute`/`last_px`/`change`(小数)/`change_px`/`amp`/`preclose_px`/`open_px`/`business_amount`/`business_balance`）

---

### `GET /quotation/market` ⚡ 需要 Chrome CDP

**财联社行情** — 综合行情面板。

- **CDP**: 是
- **请求参数**: 无
- **响应**：顶层键 `hot_plate` / `stock_ranking` / `stock_ipo` / `bj_stock_info` / `index_home` / `basic_info`；每键为上游原样包裹 `{code, msg, data}`（CDP 不可用时 `null`/缺省）。

| 字段 | 类型 | 说明 |
|------|------|------|
| `hot_plate` | object/null | 热门板块排行（`data` 内为板块列表） |
| `stock_ranking` | object/null | 个股排名（涨跌幅） |
| `stock_ipo` | object/null | 新股信息 |
| `bj_stock_info` | object/null | 北交所股票信息 |
| `index_home` | object/null | 指数首页数据 |
| `basic_info` | object/null | 基础行情数据 |

---

### `GET /market/timeline` ⚡ 需要 Chrome CDP

**指数分时图** — 上证/深证等指数分时。

- **CDP**: 是
- **请求参数**: 无
- **响应**：`{code, msg, data: {"<index_code>": {"date": YYYYMMDD, "line": [...]}}}`；`line[]` 元素为 `{minute, change(小数), last_px}`（含 241 点）

---

### `GET /cls/hotplate`

**财联社板块** — 板块资金流向排行（行业、概念、地域）。

- **CDP**: 否（REST API，使用 CLS 签名）
- **请求参数**: 无
- **响应**：顶层键 `plate_industry` / `plate_concept` / `plate_area` / `hot_plates`；前三者结构相同（见下）。

| 字段 | 类型 | 说明 |
|------|------|------|
| `plate_industry` / `plate_concept` / `plate_area` | object | 行业/概念/地域板块 |
| `.{is_all}` | number | 是否全量（0/1） |
| `.{plate_data}` | array | 板块列表（**每档 30 条**） |
| `.{plate_data}[].secu_name` | string | 板块名称（如 `半导体`） |
| `.{plate_data}[].secu_code` | string | 板块代码（`cls82245`） |
| `.{plate_data}[].change` | number | 板块涨跌幅（**小数**，`0.048` = 4.8%） |
| `.{plate_data}[].main_fund_diff` | number | 主力净额（元） |
| `.{plate_data}[].limit_up` / `limit_down` | number | 上涨 / 下跌家数 |
| `.{plate_data}[].limit_up_num` / `limit_down_num` | number | 涨停 / 跌停家数 |
| `.{plate_data}[].trade_status` | string | 交易状态（`ENDTR` 等） |
| `.{plate_data}[].first_stock` | object | 领涨股：`{secu_code, secu_name, last_px, change(小数), tr(小数)}` |
| `.{main_fund_diff}` | object | 主力资金榜：`{top_main_fund_diff: [...], last_main_fund_diff: [...]}`（各 3 条） |
| `hot_plates` | array | 综合热门板块（`plate_data` 同构元素，6 条） |

---

### `GET /ths/longhu`

**同花顺龙虎榜** — 龙虎榜明细（含买卖营业部 Top5）。

- **CDP**: 否（HTML 页面解析）
- **请求参数**: 无
- **响应**：`{data: [...], total: N}`。**金额/涨跌幅字段为带单位字符串**（上游原文，不做数值化）。

| 字段 | 类型 | 说明 |
|------|------|------|
| `data` | array | 龙虎榜股票列表 |
| `data[].code` | string | 股票代码（`000592`，无市场前缀） |
| `data[].name` | string | 股票名称 |
| `data[].price` | string | 最新价（如 `"8.71"`） |
| `data[].change_pct` | string | 涨跌幅（**字符串带 `%`**，如 `"9.97%"`） |
| `data[].turnover` | string | 成交额（**字符串带单位**，如 `"8.22亿"`） |
| `data[].net_buy` | string | 净买入额（如 `"4.57亿"`） |
| `data[].buy_top5` | array | 买入前 5 营业部：`{name, buy, sell, net}`（均字符串带单位，如 `"91398.90万"`） |
| `data[].sell_top5` | array | 卖出前 5 营业部（同上结构） |
| `total` | number | 总股票数 |

---

### `GET /market/margin`

**融资融券** — 两市融资融券余额、买入额（同花顺口径）。

- **CDP**: 否（REST API）
- **请求参数**:

| 参数 | 类型 | 必需 | 默认 | 说明 |
|------|------|------|------|------|
| `market` | string | 否 | `99` | `99`=合计, `1`=沪市, `2`=深市, `3`=京市 |

- **响应字段**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `latest` | object | 最新交易日数据 |
| `latest.date` | string | 日期（YYYY-MM-DD） |
| `latest.rzye` | number | 融资余额（**亿元**） |
| `latest.rqye` | number | 融券余额（亿元） |
| `latest.rzmre` | number | 融资买入额（亿元） |
| `latest.rzjmr` | number | 融资净买入（亿元） |
| `latest.rqjmc` | number | 融券净卖出（亿元） |
| `latest.lr` | number | 两融余额（亿元） |
| `latest.zb` | number | 两融占比（**小数**，`0.0279` = 2.79%） |
| `recent` | array | 最近 30 个交易日数据（每项同上结构） |
| `_error` | string | 仅当请求失败时出现 |

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
| `cache_ttl` | number | feed 域缓存 TTL（秒；交易时段 30 / 非交易时段 180） |
| `request_timeout` | number | 全局请求超时（秒） |
| `feeds` | array | 各端点状态列表 |
| `feeds[].name` | string | 端点名称 |
| `feeds[].path` | string | 端点路径 |
| `feeds[].url` | string | 完整 URL |
| `feeds[].status` | string | `"configured"`/`"ok"`/`"error"`/`"requires_chrome_cdp"` |
| `feeds[].items` | number | 仅当 `check=1` 时：RSS 源的条目数 |
| `feeds[].error` | string | 仅当 `check=1` 且出错时 |
| `stale` | boolean | 仅当 `check=1` 但健康检查准入已满时：返回上次快照并标 `true`（不触网） |
| `metrics` | object | 运行指标快照（计数/仪表；`snapshot()` 恒定发布全部注册名，未发生为 0） |
| `policy` | object | 各数据域的 TTL/池策略快照（`cache_policy` 派生，观测用） |
| `cdp` | object | CDP 引擎状态（`state`: `idle`/`restarting`/`unavailable` 等） |

> 说明：`feeds[].status` 取值 `"configured"`/`"ok"`/`"error"`/`"requires_chrome_cdp"`。`/stock/data` 与 `/stock/basic_info` 为 `configured`（纯 REST）；`/stock/f10` 为 `requires_chrome_cdp`（CDP 导航）。

---

# 5. SSE 实时推送（端口 8054）

订阅组管理与推送端点在 **8054**（`STREAM_PORT`），主端口 8053 不提供。

> 管理面**无鉴权**，不应暴露到公网（见 README 的 `STREAM_HOST` 说明）。

---

### `POST /stream/subscriptions`

**建组** — 创建订阅组。

- **请求体**: `{"codes": ["sh600519", ...], "fields": ["quote"]}`
  - `codes`: 必需，字符串数组；经 `canonical_code` 归一（`600519.SH` 与 `sh600519` 视为同一标的并折叠去重），单组上限 200
  - `fields`: 可选；取值 `quote` / `fundflow` / `timeline`，缺省 = 全部；**显式传入非法字段 ⇒ 400**
- **响应 `201`**:

| 字段 | 类型 | 说明 |
|------|------|------|
| `sid` | string | 订阅组 ID |
| `codes` | array | 归一后的代码（排序） |
| `fields` | array | 生效字段集 |
| `refresh_capacity_codes` | number | 单 tick 可全量刷新的码数上限（容量提示，附加键） |
| `refresh_lag_ticks` | number | 仅当码数超容量时：每码刷新周期（tick） |
| `capacity_warning` | string | 仅当超容量时：容量告警文案 |

- **错误 `400`**: `JSON body must be an object` / `codes must be a list` / `codes required` / `invalid stock code: X` / `unknown field: X` / `too many codes (max 200)` / `too many groups (max 200)` / `pool would exceed 2000 codes` / `subscription frames would exceed <B>-byte stream frame budget`

---

### `GET /stream/subscriptions/<sid>`

返回组状态 `{sid, fields, codes, conns, last_push_ts, created_ts}`；不存在 ⇒ `404`。

---

### `PATCH /stream/subscriptions/<sid>`

请求体 `{"add": [...], "remove": [...]}`（均为字符串数组）⇒ `200 {sid, codes, refresh_capacity_codes, ...}`；不存在 ⇒ `404`。

---

### `DELETE /stream/subscriptions/<sid>`

⇒ `200 {"deleted": true|false}`。

---

### `GET /stream/quote/<sid>` （SSE）

长连接，推送 `text/event-stream`：

- `event: quote` — **全量快照帧**，`data:` 为单行 JSON：

| 字段 | 类型 | 说明 |
|------|------|------|
| `ts` | number | 帧构建时间（毫秒） |
| `codes_total` | number | 该组订阅码数 |
| `fields` | array | 该组字段集 |
| `items` | object | **覆盖全部订阅码**；无数据的字段为 `null` |
| `missing` | array | 本 tick 无任何数据的码（排序） |
| `missing_count` | number | `len(missing)` |
| `stale` | array | 沿用上一 tick 值的码；仅非空时出现 |
| `stale_count` | number | `len(stale)`；仅随 `stale` 出现 |
| `errors` | object | 码 → 上游错误枚举（`upstream_timeout`/`upstream_error`/`cdp_unavailable`）；仅非空时出现 |

- `event: ping` — 保活（`STREAM_PING_INTERVAL`，默认 20s）

连接数上限 100 ⇒ 超限 `503`。组在无活动连接超过 `STREAM_GROUP_IDLE_TTL`（默认 300s）后被回收，需重新 `POST /stream/subscriptions`。

---

# 6. 接入指南

本章回答三个问题：**系统为你缓存了什么**、**你是否还需要再缓存一次**、以及 **REST / SSE 两种接入方式各自的最优姿势**。

## 6.1 系统缓存策略（接入方视角）

服务端对所有上游数据做了**分层 TTL 缓存 + 负缓存 + 单飞（single-flight）防击穿 + 半开探测**。接入方不需要感知内部机制，但要知道每个数据域的新鲜度边界：

| 数据域 | 端点示例 | 缓存 TTL（盘中 / 非盘中） | 数据特征 |
|--------|---------|--------------------------|----------|
| `quote`（L1） | `/stock/data` `/stock/basic_info` | **8s** / 120s | 实时行情 |
| `fundflow`（L1） | `/stock/fundflow` | **8s** / 120s | 资金流向 |
| `timeline`（L1） | `/stock/timeline` | **8s** / 120s | 分时 |
| `plate`（L2） | `/cls/hotplate` `/finance/market` | **12s** / 120s | 板块轮动 |
| `news_url` / `feed`（L3） | 5 个 RSS 源 | **30s** / 180s | 快讯 |
| `announcement`（L3） | `/stock/announcement` | **30s** / 180s | 公告 |
| `longhu`（L4） | `/ths/longhu` | 300s（日更） | 龙虎榜 |
| `margin`（L4） | `/market/margin` | 600s | 两融 |
| `f10`（L4） | `/stock/f10` | 300s | 财务概要 |
| `sector`（L4） | `/stock/basic_info` 行业名 | 7 天 | 行业归属 |

**交易时段判定**：A 股连续竞价时段内走「盘中」列；收盘后走「非盘中」列（TTL 放宽，减少对外部源的无效轮询）。

**失败语义**（重要）：上游失败 / CDP 不可用时，服务端做**负缓存**——失败后 5s 内请求**立即快速失败**（不重复打上游），5s 后进入**半开探测**（探测预算 2s→4s→5s 递增）。因此接入方看到 `error` 时**不要再立即重试**：服务端已在探测，你的重试只会追加延迟。建议退避 ≥5s 或用 SSE 自动恢复。

## 6.2 接入方是否需要再次缓存？

**结论：REST 场景不需要在服务端之外再加缓存层。**

理由：

1. 服务端已按 TTL 缓存同一 URL / 同一数据域，**重复缓存只会拿到更旧的数据**，不会更快；
2. 服务端已做单飞（并发请求合并为一次回源），你再加缓存不会减少上游请求；
3. 负缓存 + 半开探测已代为处理失败降频，你的缓存层若按「失败就多缓存一会」反而会固化错误快照。

**唯一的例外**是**跨公网长链路 + 高并发读**的终态聚合场景：若你的下游需要抗瞬间尖峰且能容忍 ≤2s 陈旧，可以在**边缘聚合层**（不是上游专用缓存）做一层极短 TTL（1~2s）的**兜底缓存**，用于吸收网络抖动——但这只是工程冗余，不是数据一致性的必要项。

> ⚠️ 一个反模式：对 `/stock/data` 这种**盘中 TTL 仅 8s** 的域，接入方若自己做 60s 缓存并展示为「实时」，会系统性展示过期行情。要么信任服务端 TTL 直接透传，要么把你的缓存 TTL 设得比服务端更短（如 ≤5s）。

## 6.3 轮询节奏（REST 接入）

**最优轮询周期 = 目标数据域的盘中 TTL**（不必更短，再短也拿不到新数据，只是浪费请求）：

| 目标 | 推荐轮询周期 | 原因 |
|------|-------------|------|
| 个股行情 / 分时 / 资金流 | ≥8s | L1 盘中 TTL=8s |
| 板块 | ≥12s | L2 盘中 TTL=12s |
| 快讯 RSS | ≥30s 或 ETag/Last-Modified 感知 | L3 盘中 TTL=30s |
| 龙虎榜 / 两融 / F10 | ≥300s~600s | L4 日更级 |

**批量查询**：个股端点支持逗号分隔批量（上限 50 码）——**尽可能批量**。50 码一次请求 vs 50 次请求：单飞只对并发同 URL 生效，不同 code 是不同上游 URL，批量是唯一能减少回源次数的手段。

**gzip**：所有 ≥1KB 响应（REST JSON 与 RSS）在客户端携带 `Accept-Encoding: gzip` 时自动压缩（实测大响应带宽节省 ~77%）。**强烈建议开启**，代价可忽略（level=1 压缩，2C2G 压测无超时回归）。

## 6.4 SSE 接入（实时推送，端口 8054）

### 接入三步曲

```
① POST /stream/subscriptions {"codes": [...]}   → 拿 sid（建组）
② GET  /stream/quote/<sid>                       → SSE 长连接（text/event-stream）
③ 消费帧 → 断线重连（sid 幂等）+ 组回收后重建
```

### 帧消费协议

- `event: quote` — **全量快照帧**：`items` 覆盖组内全部订阅码（Tick=2s，L1），无数据字段为 `null`；`missing`/`stale`/`errors` 三个可选键做差异提示（详见 §5）。
- `event: ping` — 保活帧，默认 20s 一次。**客户端 socket 读超时建议 ≥40s（2× ping 间隔）**，避免正常静默被误判断线。

### 三个必须知道的语义（坑）

1. **丢帧是设计，不是 bug**：每个连接的消费队列有界（8 帧）。消费慢于推送时，**旧帧被丢弃**，服务端绝不为慢消费者堆积内存。因此：
   - 客户端必须**及时读走帧**（逐行 `readline`，不要在客户端做重计算）；
   - 需要「一个都不能少」的场景（如落库审计）**不要走 SSE**——用 REST 定时拉全量，SSE 只负责实时展示。
2. **组无连接 300s 回收**：组在无活动连接超过 `STREAM_GROUP_IDLE_TTL`（默认 300s）后被回收。回收后 `GET` 返回 404，需重新 `POST` 建组。**断线重连前先 `GET /stream/subscriptions/<sid>` 探活**，404 就重建。
3. **连接数上限 100**：超出返回 503。客户端要退避重试（≥1s），不要死循环猛连。

### 集群部署的粘性要求

服务端**无跨节点同步**（组状态在单节点内存）。多节点 + nginx 接入时：

- nginx `upstream` 必须 **`ip_hash`**（或 cookie hash），保证**同一客户端的 `POST` 建组与 `GET` 连接落在同一节点**；
- 不能只用 URL hash（sid 是 POST 响应里生成的，建组时还没有 URL 可 hash）；
- 配 `proxy_buffering off` + `proxy_read_timeout 3600s`（SSE 是长连接，nginx 默认缓冲会攒帧、默认超时 60s 会掐断）。

### 鉴权边界

管理面（`POST/PATCH/DELETE /stream/subscriptions`）**无鉴权**。SSE 端口**不要暴露公网**——部署时 `STREAM_HOST=0.0.0.0` 仅在 Docker 桥接网络 / 内网使用，公网入口必须经你自己的鉴权层。

## 6.5 错误处理速查

| 响应特征 | 含义 | 接入方动作 |
|---------|------|-----------|
| `200` + 结构化数据 | 正常 | 消费 |
| `200` + `{"error": "...", "_errors": {...}}` | 业务降级（上游失败/CDP 不可用） | 展示兜底/标记延迟；**勿立刻重试**（服务端负缓存中） |
| `503` | 连接准入拒绝（负载过高） | 指数退避重试（1s/2s/4s…） |
| `400` | 请求参数错误 | 修参，不重试 |
| SSE `404` | 组已回收 | 重新 `POST` 建组 |

> 失败语义总结（§7 通用说明）：业务降级恒为 `200 + error 客体`；`503` 只用于准入拒绝与 `/healthz` 降级——**不要用 HTTP 状态码判断业务成败**。
# 7. 通用说明

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

- RSS 源: 缓存 180s（交易时段降为 30s），带 ±20% 抖动防雪崩
- REST JSON API: 统一走 `cache.fetch_json`（`cache.py`）：按数据域 TTL 缓存（`config.cache_policy` 单一权威，如 `quote` 盘中 8s / 非盘中 120s）+ 负缓存（失败后 5s 内快速失败，探测预算阶梯 2→4→5s）+ 单飞（single-flight，避免并发重复回源）
- 失败语义: 业务降级（上游失败/CDP 不可用）恒以 **HTTP 200 + 结构化 `error` 客体**返回；HTTP 503 仅用于连接准入拒绝与 `/healthz` 降级

### 并发

- 服务器使用 `BoundedThreadPoolServer`，默认最大 20 个工作线程
- 每个 RSS 源有独立锁防止并发取回
- 个股导航通过 `_navigate_lock` 实现公平排队

---

