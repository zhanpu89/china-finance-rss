# 语言特化检查项

按 LC-001 跳转。仅列项目特有约定，标准框架规范 AI 已知。

## Java

`@RestController` / `@Service` / `@Repository` 分层。`@Valid` + `@Transactional`。MyBatis `${}` 用 `#{}` 替代。异常用 `@ControllerAdvice` 全局处理。

## Python

FastAPI `Depends()` 依赖注入。`async def` 路由。Pydantic v2 校验。SQLAlchemy async session 管理。

## Go

Gin `c.ShouldBindJSON` / `c.ShouldBindQuery`。`zap`/`logrus` 替代 `fmt.Println`。error 链式处理。

## Node.js

NestJS `@Controller`/`@Injectable`/`@Module`。`ValidationPipe`。`winston`/`pino` 替代 `console.log`。
