# 项目画像 Project Profile

> 由 project-init 流程生成（手工校准版），是编排器与各 subagent 认识本项目的唯一权威画像。
> "项目特色/约束/踩坑"由 agent 在编码/评审中持续补充（回写走 `>>PROJECT:` 标记由编排器收集）。

## 技术与栈
- 主语言: **Python 3（标准库 only，零第三方依赖）**
- 前端框架: none | 小程序: none
- 构建命令: `python -m py_compile china_finance_rss/*.py tests/*.py`
- 测试命令: `python -m unittest discover -s tests -v`
- 运行命令: `python -m china_finance_rss.server`
- 部署: Dockerfile（`COPY china_finance_rss/` + `CMD python -m china_finance_rss.server`）+ docker-compose.yml

## 目录结构（扁平包布局，非 src/ 布局）
- 业务包: `china_finance_rss/`（全部业务代码，模块间用**相对导入** `from .config import ...`）
  - `server.py` — RSS/JSON HTTP 入口 + `BoundedThreadPoolServer` + 路由表 ROUTES + main()
  - `stream.py` — SSE 订阅推送服务（/stream/*，独立端口 STREAM_PORT）
  - `config.py` — 配置项 + 环境变量读取 + 缓存/CDP 开关
  - `market_api.py` / `stock_api.py` — 上游行情数据聚合
  - `cache.py` / `utils.py` — 缓存与工具
  - `cdp_engine.py` — Chrome CDP 采集引擎
- 测试: `tests/`（unittest，包含 loadtest.py 与压测脚本）
- 文档: `doc/review/`、`doc/tester/`；契约: `API.md`、`README.md`

## 分层约定（从存量代码提取）
- HTTP 层: `RSSHandler(BaseHTTPRequestHandler)` 的 do_GET/do_HEAD → `_handle_request` 按 path 路由
- 业务层: `handle_*` 纯函数（如 `handle_cls_plate(code)`），返回 dict 而非抛异常
- 数据层: `fetch_json(url, headers, ttl=...)` 统一入口（cache.py + market_api/stock_api 聚合）
- 签名层: `cls_sign_params(params)` — CLS 系接口共用签名机制

## 项目特色 / 约束 / 踩坑（agent 持续追加）
- 少量 `server.py` 模块级副作用：`main()` 内延迟 import（`from . import config`），避免 import 期启动 CDP
- 配置走 `config.py` + 环境变量（PORT/STREAM_PORT/HOST 等），不硬编码
- 源站数据用 TTL 缓存 + 防击穿（feed_cache + 按 path 锁），TTL 随交易时段动态分层（`_trading_tiers()`）
- **不要臆想"标准分层"**：本项目是零依赖手写 HTTP 服务，不引入框架模式
- 测试必须真实起服务/走 HTTP 路径（tests 用 `patch('china_finance_rss.stream.*')`，新增模块测试引用 `china_finance_rss.*` 全限定名）

## 需要人工确认的点
- （探测校准完成：src/ 探测脚本对扁平包布局不适用，手工改为 china_finance_rss/；无前端/小程序）

## 编排调度提示（给 orchestor 的定向记忆）
- **结构提醒**：扁平包布局，业务代码全在 `china_finance_rss/`（无 src/）。编码/修复任务 dispatch 时明确"包内用相对导入"，测试引用 `china_finance_rss.*` 全限定。
- **权限边界**：code-developer 只可改 `china_finance_rss/**`+`tests/**`；契约文档（API.md/README.md）只有编排层能调度同步（doc-agent 路径），code-developer 只标 `>>DOC_SYNC:`。
- **强度建议**：纯 Python 标准库 + unittest，单仓小项目——绝大多数任务走 🟡增量/🟢标准即可；只有跨模块（server+stream+数据层联调）或安全相关才上 🔴全量。
- **已知踩坑**：① 源站接口带复杂签名（cls_sign_params），改参数必须保持签名一致，否则 401/数据为空；② CDP 依赖 Chrome，宿主无 Chrome 时 CDP 端点属预期失败，不要当 bug 修；③ 端口冲突（docker 占 8053/8054）时验证用 PORT/STREAM_PORT 环境变量换端口，别改 docker-compose 里已确认的配置；④ 压测/盲审报告落盘 doc/review、doc/tester，不落根目录。