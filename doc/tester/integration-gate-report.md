# 集成验证报告

**时间:** 2026-09-20T03:44:44Z
**项目:** python
**端点来源:** 默认（健康检查兜底）
**待验端点:** 1 个
- GET /healthz?check=0

## 逐端点结果

### GET /healthz?check=0
- **状态码:** 200
- **响应体:**
```
{
  "status": "ok",
  "cache_ttl": 180,
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


---

## 汇总

| 指标 | 值 |
|------|-----|
| ✅ 通过 | 1 |
| ❌ 失败 | 0 |
| ⏭️  跳过 | 0 |

**结论:** ✅ 集成验证通过
