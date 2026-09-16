# 语言特化实现指南（Lang-Implement）

> 编码执行时按 LC-001 跳转。这里是"**这个场景在代码里怎么写对**"的实现决策——与 lang-engineering.md（规范禁令）互补，不重复。每节给场景→写法→反例→要点。编码前先过一遍对应语言节。

## 一、Java / Spring Boot

| 场景 | 写法 | 反例 ❌ | 要点 |
|------|------|---------|------|
| 事务 | `@Transactional(rollbackFor = Exception.class)` 或 `@Transactional`（默认运行时异常回滚） | 事务方法被同类 `this.xxx()` 内部调用 | 自调用不走代理；事务方法别做网络 IO；`propagation` 有值再写 |
| 金额计算 | `BigDecimal` + `setScale` + 明确舍入模式 | `double` 累加、`float` 存库 | 入库前校验 scale 与精度；除法必须指定舍入 |
| 日期 | `LocalDateTime`/`Instant` + `DateTimeFormatter` | `new Date()`/`SimpleDateFormat` | 时区统一 UTC；前端传参用 ISO 格式 |
| 并发控制 | 悲观锁 `for update` / 乐观锁 `@Version` / 分布式锁 Redisson | 无锁直接更新、`synchronized` 跨进程 | 更新场景优选乐观锁；锁范围最小化 |
| 集合 | `stream().toList()`（不可变）/ `ConcurrentHashMap` | 遍历中 `remove`、`HashMap` 并发写 | 需要可修改结果用 `collect(Collectors.toList())` |
| 异常 | 自定义业务异常 + 全局 `@RestControllerAdvice` | 每层 `catch` 后又 `throw new RuntimeException` | 异常带错误码与用户文案；禁止吞异常只 log |
| 参数校验 | Bean Validation 注解 `@Valid` + 自定义校验器 | Controller 手写 if 判断 | 校验注解集中在 DTO；复杂规则进 Service |
| 日志 | 占位符 `log.info("order {}, status {}", id, s)` | 字符串拼接 + `printStackTrace` | 关键操作记入参；异常堆栈进 error 级 |

## 二、Python

| 场景 | 写法 | 反例 ❌ | 要点 |
|------|------|---------|------|
| 异步资源 | `async with session:` / `async with aiofiles.open` | `await` 后手动 close 忘调 | 上下文管理器兜底释放；DB 连接池走框架管理 |
| 时间 | `datetime.now(ZoneInfo)` 带时区 | `datetime.now()` 裸本地时间 | 存储 UTC；转换边界明确 |
| 校验 | Pydantic v2 `model_config = ConfigDict(extra="forbid")` + 字段约束 | 手动 if 判断 + `raise ValueError` | 校验集中在 schema；错误转业务异常带 code |
| 并发 | `asyncio.gather` / 锁 `asyncio.Lock` | `asyncio` 里直接 `requests.get`（阻塞） | 阻塞调用用 `run_in_executor` 或 httpx async |
| 金额 | `Decimal(str(x))` + `quantize` | `float` 四则 | 避免 `Decimal(0.1)` 浮点字面量 |
| 异常 | 捕获具体类型 + `logging.exception` | 裸 `except:` / `except Exception: pass` | 自定义异常继承统一基类带 code |
| 配置 | `pydantic-settings` 读 env | `os.getenv` 散落 | 敏感配置只走环境变量 |

## 三、Go

| 场景 | 写法 | 反例 ❌ | 要点 |
|------|------|---------|------|
| 错误 | 检查后处理 + `fmt.Errorf("...: %w", err)` | `_ = f()` / 裸 `errors.New` 丢失链 | 边界层统一转换为响应错误；日志只记一次 |
| 并发 | `errgroup.WithContext` 并行 + `sync.Mutex` 保护共享 | `go func` 无 WaitGroup 泄漏 | 每个 goroutine 有退出路径；channel 关闭只由 sender |
| 切片 | 需要独立时 `copy`/`append` 新底层 | 子切片共享底层数组后续 `append` 覆盖 | 注意 `s[:0]` 复用；`slice = append(slice, x)` 形式 |
| 资源 | `defer file.Close()` / `defer db.Close()` | 手动 close 遗漏 | 打开后立即 defer；defer 内检查错误 |
| 循环取址 | 循环内 `x := x` 或传参副本 | `for _, v := range` 直接 `&v` | Go <1.22 循环变量复用 |
| 时间 | `time.Now().UTC()` + 标准库 | `time.Now()` 本地时间 + 手算时区 | 时间运算用 `time.Time` 方法 |
| 日志 | `slog.Info` / zap 结构化 | `log.Println` | 结构化键值，含请求 id 关联 |

## 四、Node.js / TypeScript

| 场景 | 写法 | 反例 ❌ | 要点 |
|------|------|---------|------|
| 异步 | `await` 完整链路 + 顶层 `try/catch` 边界处理 | 回调地狱、`fire-and-forget` 未 catch | Promise 全部 await；`Promise.allSettled` 处理部分失败 |
| 金额 | `decimal.js`/`big.js` | 原生 `number` 加减 | 金额运算专用库；序列化保持字符串 |
| 校验 | `class-validator` DTO + 管道 | Controller 手写 if 判断 | NestJS 用 ValidationPipe；校验 DTO 集中于 input |
| 时间 | `dayjs`/`date-fns` 显式时区 | 原生 `Date` 加减 + 手算 | 存 ISO/UTC，展示层再转本地 |
| 资源 | `try/finally` 或 `finally` 释放、事务回调 | 忘 close 连接、忘 removeListener | 连接池框架管理；EventEmitter 监听器用后移除 |
| 错误 | 统一异常过滤器 + 业务错误码 | 每层 `throw new Error("xxx")` | 错误响应结构统一；日志含 context |
| 并发 | `p-limit`/信号量控制并发数 | 无上限 `Promise.all` 大列表 | 外部请求限并发；幂等键处理重复 |

## 五、跨语言通用实现要点

- **数据定义唯一**：字段只在 model/entity 定义一次，DTO 通过转换同步，不写第二份
- **依赖注入而非 new**：服务依赖通过构造注入/DI 容器，便于测试 mock
- **边界处理**：每个外部依赖（DB/HTTP/MQ）有超时 + 错误兜底
- **配置外置**：魔法值/阈值走配置文件/环境变量，不硬编码

> 编码时对照本文件 + 项目 `doc/detailed/编码规范.md` + `项目规则.md`。语言陷阱深查见 code-reviewer 的 `lang-ext.md`（评审视角）。
