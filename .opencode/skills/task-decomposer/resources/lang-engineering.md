# 语言工程规则

仅列项目特有禁令。标准语言工程规范 AI 已知。

## Java

- 禁止：`new Date()`/`SimpleDateFormat`/`System.out.println`/`e.printStackTrace()`/`double`/`float` 存金额/MD5/SHA1 存密码/`SELECT *`/N+1
- 必须：`LocalDateTime`/`log.info`/`BigDecimal`/`BCryptPasswordEncoder`/参数化查询
- 方法≤80行，嵌套≤4层

## Python

- 禁止：`print()`/`except: pass`/裸 `except:`/`for i in range(len(...))`/密码硬编码/`SELECT *`
- 必须：logging 替代 print/`async with` 管理资源/参数化查询
- 方法≤60行

## Go

- 禁止：`log.Println` 替代 logging/忽略 `err`/同步 `time.Sleep` 重试/`interface{}` 滥用
- 必须：`slog`/`zap` 结构化日志/error 链式处理/`errgroup` 并发控制
- 方法≤60行

## Node.js

- 禁止：`console.log`/`try...catch` 吞异常/sync 文件操作/回调地狱/RAM 缓存替代 Redis
- 必须：`winston`/`pino` 结构化日志/`async/await`/`class-validator` 校验
- 方法≤60行

## 通用

- 参数化查询防注入，缓存 TTL 有上限，外部调用有超时+熔断
