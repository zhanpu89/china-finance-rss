# 集成验证报告

**时间:** 2026-09-18T06:42:28Z
**项目:** python
**端点来源:** _MEMORY_CACHE.md
**待验端点:** 7 个
- /healthz
- /opml.xml
- /cls/telegraph
- /eastmoney/kuaixun
- /ths/kuaixun
- /jin10/flash
- /wallstreetcn/live

## 逐端点结果

### GET /healthz
- **状态码:** 200
- **响应体:**
```
{
  "status": "ok",
  "cache_ttl": 30,
  "request_timeout": 10,
  "feeds": [
    {
      "name": "CLS Telegraph (财联社电报)",
      "path": "/cls/telegraph",
      "url": "http://127.0.0.1:8053/cls/telegraph",
      "status": "configured"
    },
    {
      "name": "Eastmoney News (东方财富快讯)",
      "path": "/eastmoney/kuaixun",
      "url": "http://127.0.0.1:8053/eastmoney/kuaixun",
      "status": "configured"
    },
    {
      "name": "THS News (同花顺快讯)",
      "path": "/ths/kuaixun",
      "url": "http://127.0.0.1:8053/ths/kuaixun",
      "status": "configured"
    },
    {
      "name": "Jin10 Flash (金十快讯)",
      "path": "/jin10/flash",
      "url": "http://127.0.0.1:8053/jin10/flash",
      "status": "configured"
    },
    {
      "name": "Wallstreetcn Live (华尔街见闻快讯)",
      "path": "/wallstreetcn/live",
      "url": "http://127.0.0.1:8053/wallstreetcn/live",
      "status": "configured"
    },
    {
      "name": "CLS Finance Market (财联社看盘)",
      "path": "/finance/market",
      "url": "http://127.0.0.1:8053/finance/market",
      "status": "requires_chrome_cdp"
    },
    {
      "name": "CLS Quotation Market (财联社行情)",
      "path": "/quotation/market",
      "url": "http://127.0.0.1:8053/quotation/market",
      "status": "requires_chrome_cdp"
    },
    {
      "name": "CLS Stock Detail (财联社个股详情)",
      "path": "/stock/data",
... (截断)
```

### GET /opml.xml
- **状态码:** 200
- **响应体:**
```
<?xml version="1.0" encoding="UTF-8"?>
<opml version="2.0">
<head>
<title>China Finance RSS Bridge feeds</title>
</head>
<body>
<outline text="China Finance RSS Bridge" title="China Finance RSS Bridge">
<outline text="CLS Telegraph (财联社电报)" title="CLS Telegraph (财联社电报)" type="rss" xmlUrl="http://127.0.0.1:8053/cls/telegraph"/>
<outline text="Eastmoney News (东方财富快讯)" title="Eastmoney News (东方财富快讯)" type="rss" xmlUrl="http://127.0.0.1:8053/eastmoney/kuaixun"/>
<outline text="THS News (同花顺快讯)" title="THS News (同花顺快讯)" type="rss" xmlUrl="http://127.0.0.1:8053/ths/kuaixun"/>
<outline text="Jin10 Flash (金十快讯)" title="Jin10 Flash (金十快讯)" type="rss" xmlUrl="http://127.0.0.1:8053/jin10/flash"/>
<outline text="Wallstreetcn Live (华尔街见闻快讯)" title="Wallstreetcn Live (华尔街见闻快讯)" type="rss" xmlUrl="http://127.0.0.1:8053/wallstreetcn/live"/>
</outline>
</body>
</opml>
```

### GET /cls/telegraph
- **状态码:** 200
- **响应体:**
```
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
<channel>
<title>财联社电报</title>
<link>https://www.cls.cn/telegraph</link>
<description>财联社实时快讯</description>
<lastBuildDate>Fri, 18 Sep 2026 06:42:29 GMT</lastBuildDate>
<ttl>1</ttl>
<atom:link href="http://127.0.0.1:8053/cls/telegraph" rel="self" type="application/rss+xml"/>
<item>
<title>财联社9月18日电，日本央行行长植田和男表示，将密切关注中东影响、日元波动及人工智能需求。</title>
<link>https://www.cls.cn/detail/2487091</link>
<description>财联社9月18日电，日本央行行长植田和男表示，将密切关注中东影响、日元波动及人工智能需求。</description>
<pubDate>Fri, 18 Sep 2026 06:40:11 GMT</pubDate>
<guid isPermaLink="false">cls_2487091</guid>
</item>
<item>
<title>财联社9月18日电，欧洲央行副行长Vujcic称经济可能在秋季放缓。</title>
<link>https://www.cls.cn/detail/2487089</link>
<description>财联社9月18日电，欧洲央行副行长Vujcic称经济可能在秋季放缓。</description>
<pubDate>Fri, 18 Sep 2026 06:38:57 GMT</pubDate>
<guid isPermaLink="false">cls_2487089</guid>
</item>
<item>
<title>财联社9月18日电，欧洲央行管委卡扎克斯称，能源价格冲击更具持续性，2.5%可能是中性区间的上限，很可能需要采取限制性政策。</title>
<link>https://www.cls.cn/detail/2487088</link>
<description>财联社9月18日电，欧洲央行管委卡扎克斯称，能源价格冲击更具持续性，2.5%可能是中性区间的上限，很可能需要采取限制性政策。</description>
<pubDate>Fri, 18 Sep 2026 06:38:15 GMT</pubDate>
<guid isPermaLink="false">cls_2487088</guid>
</item>
<item>
<title>财联社9月18日电，日本央行行长植田和男表示，将继续根据经济和价格情况加息。</title>
<link>https://www.cls.cn/detail/2487087</link>
<description>财联社9月18日电，日本央行行长植田和男表示，将继续根据经济和价格情况加息。</description>
<pubDate>Fri, 18 Sep 2026 06:37:56 GMT</pubDate>
<guid isPermaLink="false">cls_2487087</guid>
</item>
<item>
<title>财联社9月18日电，日本央行行长植田和男表示，日本经济正在温和复苏，潜在价格趋势接近2%。</title>
<link>https://www.cls.cn/detail/2487086</link>
<description>财联社9月18日电，日本央行行长植田和男表示，日本经济正在温和复苏，潜在价格趋势接近2%。</description>
<pubDate>Fri, 18 Sep 2026 06:36:47 GMT</pubDate>
<guid isPermaLink="false">cls_2487086</guid>
</item>
<item>
<title>【日韩股市集体收涨 SK海力士涨超6%】财联社9月18日电，日经225指数收涨1.38%，报65018.95点。韩国KOSPI指数收涨2.66%，报6894.23点。其中，SK海力士上涨6.42%，三星电子上涨3.37%。</title>
<link>https://www.cls.cn/detail/2487085</link>
<description>【日韩股市集体收涨 SK海力士涨超6%】财联社9月18日电，日经225指数收涨1.38%，报65018.95点。韩国KOSPI指数收涨2.66%，报6894.23点。其中，SK海力士上涨6.42%，三星电子上涨3.37%。</description>
<pubDate>Fri, 18 Sep 2026 06:32:42 GMT</pubDate>
<guid isPermaLink="false">cls_2487085</guid>
... (截断)
```

### GET /eastmoney/kuaixun
- **状态码:** 200
- **响应体:**
```
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
<channel>
<title>东方财富快讯</title>
<link>https://kuaixun.eastmoney.com/</link>
<description>东方财富7x24快讯</description>
<lastBuildDate>Fri, 18 Sep 2026 06:42:29 GMT</lastBuildDate>
<ttl>1</ttl>
<atom:link href="http://127.0.0.1:8053/eastmoney/kuaixun" rel="self" type="application/rss+xml"/>
<item>
<title>30年未见之大变局？日本加息提速背后 牵动着5万亿美元的投资去向</title>
<link>http://finance.eastmoney.com/a/202609183878541371.html</link>
<description>【30年未见之大变局？日本加息提速背后 牵动着5万亿美元的投资去向】日本央行周五将基准利率上调至了三十年来的最高点，并释放出未来将继续加息的明确信号。这一重磅的加息提速信号，预计将在日本本土之外激起广泛的全球连锁反应。目前，日本投资者持有的海外资产规高达约5万亿美元，其中的“半壁江山”投资于美国——日本投资者持有约2.5万亿美元的美国股票、债券及其他金融资产。</description>
<pubDate>Fri, 18 Sep 2026 06:39:12 GMT</pubDate>
<guid isPermaLink="false">eastmoney_202609183878541371</guid>
</item>
<item>
<title>道达尔能源与GIP就非洲能源基础设施签署协议</title>
<link>http://finance.eastmoney.com/a/202609183878547645.html</link>
<description>【道达尔能源与GIP就非洲能源基础设施签署协议】9月18日，一份声明显示，道达尔能源已与全球基础设施合伙公司（GIP）就非洲部分石油和天然气基础设施资产达成合作协议。作为对GIP出资18亿美元的交换，道达尔能源将在最长15年的期限内向GIP支付按吞吐量计算的费用。</description>
<pubDate>Fri, 18 Sep 2026 06:34:43 GMT</pubDate>
<guid isPermaLink="false">eastmoney_202609183878547645</guid>
</item>
<item>
<title>日韩股市集体收涨</title>
<link>http://finance.eastmoney.com/a/202609183878547133.html</link>
<description>【日韩股市集体收涨】日经225指数收涨1.38%，报65018.95点；韩国KOSPI指数收涨2.68%，报6895.55点。</description>
<pubDate>Fri, 18 Sep 2026 06:32:47 GMT</pubDate>
<guid isPermaLink="false">eastmoney_202609183878547133</guid>
</item>
<item>
<title>工信部公开征求《有色金属行业科技成果评价规范》等10项行业标准报批意见</title>
<link>http://finance.eastmoney.com/a/202609183878546663.html</link>
<description>【工信部公开征求《有色金属行业科技成果评价规范》等10项行业标准报批意见】据工信部消息，根据行业标准制修订计划，相关标准化技术组织已完成《有色金属行业科技成果评价规范》1项有色金属行业标准、《液体香皂》等6项轻工行业标准、《压剪试验机》等2项机械行业标准、《纺织行业科技成果评价规范》1项纺织行业标准的编制工作。为进一步听取社会各界意见，现予以公示。公示时间为2026年9月19日—2026年10月18日。</description>
<pubDate>Fri, 18 Sep 2026 06:32:43 GMT</pubDate>
<guid isPermaLink="false">eastmoney_202609183878546663</guid>
</item>
<item>
<title>捷成股份等在北京成立智算科技公司 注册资本1亿</title>
<link>http://finance.eastmoney.com/a/202609183878546210.html</link>
<description>【捷成股份等在北京成立智算科技公司 注册资本1亿】天眼查App显示，近日，北京捷成世纪智算科技有限公司成立，法定代表人为黎奕杰，注册资本1亿人民币，经营范围含互联网数据服务、数据处理和存储支持服务、人工智能应用软件开发等。股东信息显示，该公司由北京捷成世纪科技股份有限公司、海南炜辰科技服务合伙企业（有限合伙）共同持股。</description>
<pubDate>Fri, 18 Sep 2026 06:30:43 GMT</pubDate>
<guid isPermaLink="false">eastmoney_202609183878546210</guid>
</item>
<item>
<title>9月18日全国农产品批发市场猪肉平均价格为16.62元/公斤 比昨天上升1.0%</title>
<link>http://finance.eastmoney.com/a/202609183878546020.html</link>
<description>【9月18日全国农产品批发市场猪肉平均价格为16.62元/公斤 比昨天上升1.0%】据农业农村部监测，9月18日“农产品批发价格200指数”为116.97，比昨天下降0.12个点，“菜篮子”产品批发价格指数为117.70，比昨天下降0.17个点。</description>
<pubDate>Fri, 18 Sep 2026 06:30:34 GMT</pubDate>
<guid isPermaLink="false">eastmoney_202609183878546020</guid>
... (截断)
```

### GET /ths/kuaixun
- **状态码:** 200
- **响应体:**
```
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
<channel>
<title>同花顺快讯</title>
<link>https://news.10jqka.com.cn/</link>
<description>同花顺7x24快讯</description>
<lastBuildDate>Fri, 18 Sep 2026 06:42:30 GMT</lastBuildDate>
<ttl>1</ttl>
<atom:link href="http://127.0.0.1:8053/ths/kuaixun" rel="self" type="application/rss+xml"/>
<item>
<title>南非卫生部警告猴痘病例激增</title>
<link>https://news.10jqka.com.cn/20260918/c680054961.shtml</link>
<description>南非卫生部警告称，近期南非全国猴痘病例出现快速增加，呼吁公众提高警惕。根据卫生部门的最新通报，8月14日至9月17日，南非已经记录18例实验室确诊病例，以及1例疑似病例。据悉，目前病例主要集中在西开普省，患者年龄介于23岁至50岁之间。（央视新闻）</description>
<pubDate>Fri, 18 Sep 2026 06:41:30 GMT</pubDate>
<guid isPermaLink="false">ths_680054961</guid>
</item>
<item>
<title>日本央行行长植田和男：将根据经济和物价情况继续加息</title>
<link>https://news.10jqka.com.cn/20260918/c680054939.shtml</link>
<description>日本央行行长植田和男表示，将根据经济和物价情况继续加息。中东、AI需求和汇率是影响利率路径的因素。</description>
<pubDate>Fri, 18 Sep 2026 06:40:10 GMT</pubDate>
<guid isPermaLink="false">ths_680054939</guid>
</item>
<item>
<title>布伦特原油失守98美元/桶</title>
<link>https://news.10jqka.com.cn/20260918/c680054899.shtml</link>
<description>布伦特原油失守98美元/桶，日内跌1.96%。</description>
<pubDate>Fri, 18 Sep 2026 06:38:27 GMT</pubDate>
<guid isPermaLink="false">ths_680054899</guid>
</item>
<item>
<title>日本央行行长植田和男：日本经济正在温和复苏，潜在价格趋势接近2%</title>
<link>https://news.10jqka.com.cn/20260918/c680054882.shtml</link>
<description>日本央行行长植田和男表示，日本经济正在温和复苏，潜在价格趋势接近2%。</description>
<pubDate>Fri, 18 Sep 2026 06:37:13 GMT</pubDate>
<guid isPermaLink="false">ths_680054882</guid>
</item>
<item>
<title>光大期货：保供政策推出，焦煤近月合约跌停</title>
<link>https://news.10jqka.com.cn/20260918/c680054837.shtml</link>
<description>短期焦煤的下跌是“情绪降温+政策转向预期+需求负反馈”三重压力的集中释放。中期来看，焦煤的核心矛盾并未根本解决——山西复产进度偏慢、蒙煤通关恢复缺乏明确时间表，四季度供需缺口预期仍存。但短期内，保供政策信号的发酵、钢厂减产的推进以及竞拍流拍对现货定价的拖拽，可能使焦煤延续偏弱调整。真正的企稳信号，或需要等待钢厂利润修复的实质性进展，以及竞拍市场重新出现有效成交。（光大期货）</description>
<pubDate>Fri, 18 Sep 2026 06:33:42 GMT</pubDate>
<guid isPermaLink="false">ths_680054837</guid>
</item>
<item>
<title>日韩股市集体收涨，日经225指数收涨1.38%</title>
<link>https://news.10jqka.com.cn/20260918/c680054826.shtml</link>
<description>日经225指数收涨1.38%，报65018.95点。韩国综指收涨2.68%，报6895.55点。</description>
<pubDate>Fri, 18 Sep 2026 06:32:40 GMT</pubDate>
<guid isPermaLink="false">ths_680054826</guid>
... (截断)
```

### GET /jin10/flash
- **状态码:** 200
- **响应体:**
```
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
<channel>
<title>金十快讯</title>
<link>https://www.jin10.com/</link>
<description>金十数据7x24快讯</description>
<lastBuildDate>Fri, 18 Sep 2026 06:42:30 GMT</lastBuildDate>
<ttl>1</ttl>
<atom:link href="http://127.0.0.1:8053/jin10/flash" rel="self" type="application/rss+xml"/>
<item>
<title>【沙特从拉斯坦努拉港售出约6000万桶原油 全球油价降温】金十数据9月18日讯，贸易消息人士周五称，沙特本月和已从霍尔木兹海峡内的拉斯坦努拉港售出约6000万桶原油，用于在阿曼苏哈尔港通过船对船转运装</title>
<link>https://flash.jin10.com/detail/20260918144127374800</link>
<description>【沙特从拉斯坦努拉港售出约6000万桶原油 全球油价降温】金十数据9月18日讯，贸易消息人士周五称，沙特本月和已从霍尔木兹海峡内的拉斯坦努拉港售出约6000万桶原油，用于在阿曼苏哈尔港通过船对船转运装货。沙特从海湾内部出口的石油回升，冷却了全球油价，因为这可能弥补其红海延布港损失的部分供应量。在东西向输油管道遭也门胡塞武装袭击后，延布港出口已经放缓。消息人士说，韩国炼油商是这些现货供应的主要买家，部分原油将运往印度和日本。</description>
<pubDate>Fri, 18 Sep 2026 06:41:27 GMT</pubDate>
<guid isPermaLink="false">jin10_20260918144127374800</guid>
</item>
<item>
<title>日本央行行长植田和男：近期油价上涨。</title>
<link>https://flash.jin10.com/detail/20260918144117383800</link>
<description>日本央行行长植田和男：近期油价上涨。</description>
<pubDate>Fri, 18 Sep 2026 06:41:17 GMT</pubDate>
<guid isPermaLink="false">jin10_20260918144117383800</guid>
</item>
<item>
<title>欧洲央行管委卡扎克斯：如有必要，我们将把存款利率提高到2.5%以上。</title>
<link>https://flash.jin10.com/detail/20260918144109294800</link>
<description>欧洲央行管委卡扎克斯：如有必要，我们将把存款利率提高到2.5%以上。</description>
<pubDate>Fri, 18 Sep 2026 06:41:09 GMT</pubDate>
<guid isPermaLink="false">jin10_20260918144109294800</guid>
</item>
<item>
<title>日本央行行长植田和男：必须警惕通胀上行风险，包括中东局势带来的风险。</title>
<link>https://flash.jin10.com/detail/20260918144058384800</link>
<description>日本央行行长植田和男：必须警惕通胀上行风险，包括中东局势带来的风险。</description>
<pubDate>Fri, 18 Sep 2026 06:40:58 GMT</pubDate>
<guid isPermaLink="false">jin10_20260918144058384800</guid>
</item>
<item>
<title>日本央行行长植田和男：需要避免价格偏离目标，以免损害经济。</title>
<link>https://flash.jin10.com/detail/20260918144044661800</link>
<description>日本央行行长植田和男：需要避免价格偏离目标，以免损害经济。</description>
<pubDate>Fri, 18 Sep 2026 06:40:44 GMT</pubDate>
<guid isPermaLink="false">jin10_20260918144044661800</guid>
</item>
<item>
<title>【午后，暴拉超297%！沈鼓变“神鼓”，什么情况？】金十数据9月18日讯，9月18日午后，沈鼓集团（C沈鼓）突然暴力拉升，盘中涨幅一度涨超297%，股价最高触及82.59元/股，日内换手率超过80%，</title>
<link>https://mp.weixin.qq.com/s?__biz=MzA3NjM5MjIwOQ==&amp;mid=2652280870&amp;idx=1&amp;sn=49ec88eda222b572894473b591f7377f&amp;chksm=8505bcb254fd146f17da578ca37f70f2421a08d32d03c3b8c4bbf6ba4d6929ec6a397198248b&amp;scene=0&amp;xtrack=1#rd</link>
<description>【午后，暴拉超297%！沈鼓变“神鼓”，什么情况？】金十数据9月18日讯，9月18日午后，沈鼓集团（C沈鼓）突然暴力拉升，盘中涨幅一度涨超297%，股价最高触及82.59元/股，日内换手率超过80%，成交额逼近40亿元。盘中，沈鼓集团二次触发临停。有市场分析人士指出，沈鼓集团上市后股价被“爆炒”，是极低发行价、极小流通盘、稀缺题材共振以及市场资金风格切换多重因素叠加的结果。</description>
<pubDate>Fri, 18 Sep 2026 06:40:43 GMT</pubDate>
<guid isPermaLink="false">jin10_20260918144043396800</guid>
... (截断)
```

### GET /wallstreetcn/live
- **状态码:** 200
- **响应体:**
```
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
<channel>
<title>华尔街见闻快讯</title>
<link>https://wallstreetcn.com/live</link>
<description>华尔街见闻7x24快讯</description>
<lastBuildDate>Fri, 18 Sep 2026 06:42:30 GMT</lastBuildDate>
<ttl>1</ttl>
<atom:link href="http://127.0.0.1:8053/wallstreetcn/live" rel="self" type="application/rss+xml"/>
<item>
<title>日本央行行长植田和男：将根据经济和物价情况继续加息。

中东、AI需求和汇率是影响利率路径的因素。

受人工智能、原油及日元走弱影响，生产者价格处于高位。

将物价趋势稳定在2%左右非常重要。

需要</title>
<link>https://wallstreetcn.com/livenews/3167196</link>
<description>日本央行行长植田和男：将根据经济和物价情况继续加息。

中东、AI需求和汇率是影响利率路径的因素。

受人工智能、原油及日元走弱影响，生产者价格处于高位。

将物价趋势稳定在2%左右非常重要。

需要避免物价偏离目标、损害经济。

近期油价正在上涨。

原油驱动的物价上涨可能正在广泛蔓延。</description>
<pubDate>Fri, 18 Sep 2026 06:39:09 GMT</pubDate>
<guid isPermaLink="false">wallstreetcn_3167196</guid>
</item>
<item>
<title>欧洲央行管委Kazaks：能源价格冲击更为持久。

所有会议都是实时会议。

如有必要，我们将把存款利率提高到2.5%以上。</title>
<link>https://wallstreetcn.com/livenews/3167195</link>
<description>欧洲央行管委Kazaks：能源价格冲击更为持久。

所有会议都是实时会议。

如有必要，我们将把存款利率提高到2.5%以上。</description>
<pubDate>Fri, 18 Sep 2026 06:33:57 GMT</pubDate>
<guid isPermaLink="false">wallstreetcn_3167195</guid>
... (截断)
```


---

## 汇总

| 指标 | 值 |
|------|-----|
| ✅ 通过 | 7 |
| ❌ 失败 | 0 |
| ⏭️  跳过 | 0 |

**结论:** ✅ 集成验证通过
