# 项目约定 Project Conventions

> 从存量代码实际模式提取（非臆想）。新增代码必须符合以下约定；评审以此为据。

## 命名规范
- 模块/文件: snake_case（config.py、market_api.py、cdp_engine.py）
- 常量: UPPER_SNAKE（`MAX_CODES_PER_SUB`、`STREAM_PING_INTERVAL`、路由表 `ROUTES`）
- 私有函数/锁: 下划线前缀（`_handle_request`、`_feed_cache_lock`、`_send_json`）
- HTTP handler 类: XxxHandler（`RSSHandler`、`StreamHandler`）；服务类: XxxServer

## 分层与职责
- 包内模块间**相对导入**（`from .config import ...`）；外部（tests/）用 `from china_finance_rss.* import ...` 全限定
- 业务函数形态: `handle_*(...) -> dict`，参数平铺（code、feed_url 等），不封装请求对象
- 路由: 集中式 dict（`ROUTES`）或 `_handle_request` 内显式 path 分支；不搞装饰器路由
- 数据获取统一走 `fetch_json(url, headers, ttl=...)` 聚合入口，禁止模块内 new HTTP 客户端
- 延迟依赖的导入放函数内（如 `def main(): from . import config`），避免 import 期副作用

## 异常与错误处理
- 业务异常**不外抛**：handler 内部 try/except，错误写入结果 dict（`{'error': str(e)}`）或子字段
- HTTP 错误语义: 参数缺失/非法 → 400 + `{'error': msg}`；未知路径 → 404；降级/过载 → 503
- 网络断开类异常（BrokenPipeError/ConnectionResetError/OSError）在 handler 外层静默捕获
- 日志: `log.info/warning`（logging），`[模块]` 前缀（`[stream]`、`[cdn]`）

## 事务与并发
- 共享状态用 threading.Lock 显式保护，锁名独立区分（`_feed_cache_lock`/`_feed_fetch_locks_lock`/`_groups_lock`/`_conn_count_lock`），不用全局大锁
- 连接有上限: `MAX_STREAM_CONNS` 计数 + 超限 503；socket timeout（`STREAM_PING_INTERVAL*2`）防停滞客户端占线程
- 缓存防击穿: 双重检查 + 按 path 独立锁 + TTL 分层（`_trading_tiers()`：盘中/盘后不同 TTL）

## 配置管理
- 需要部署可调的每域资源上限统一以 env 注册常量（config 模块顶层）承载，矩阵以 'env:<NAME>' spec 引用，_resolve_pool_max 调用期经 globals() 白名单解析；新增 spec 分支必须对未知名 fail-fast ValueError
- 配置项统一在 `config.py`（读取环境变量 + 默认值），代码不硬编码端口/主机/TTL
- 敏感信息（cookie/token）走环境变量，**绝不入库/入 git**（.env、HAR、Chrome profile 均不提交）
- 运行时开关（如 CDP 可用否）在 config/engine 状态判断，不散落判断逻辑

## 测试约定
- 框架: unittest（`python -m unittest discover -s tests -v`）+ loadtest 压测脚本
- mock: `unittest.mock.patch('china_finance_rss.<module>.<symbol>')` **全限定名**
- 测试要覆盖真实路径：起真实 HTTP 服务、真实解析响应；SSE 测试验证事件帧格式
- 不依赖外部网络/CDP（打桩），本地可跑

## 文档同步
- 契约文档（API.md/README.md）与实现不符时，code-developer 只输出 `>>DOC_SYNC:` 标记，由编排层调度同步，code-developer 不直接改契约