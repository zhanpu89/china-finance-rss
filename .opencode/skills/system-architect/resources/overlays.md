# 语言技术栈特化规则

按 LC-001 跳转。以下是**跨项目通用的语言技术栈专家推荐**（编码阶段据此锁定本项目实际采用的技术栈，避免重复选型）。"AI 已知"的标准框架知识不写在这里——本文件是通用起点，安装到项目后应改写为「本项目锁定用这套」。

## Java

- 认证：Spring Security + JWT（Access 15min + Refresh 7d），Redis 黑名单吊销
- 密码：BCryptPasswordEncoder（cost=12）
- ORM：Spring Data JPA / MyBatis-Plus
- API：RESTful，Swagger/OpenAPI 3.0

## Python

- 认证：FastAPI `Depends()` + `python-jose` JWT
- 密码：`passlib` + `bcrypt`
- ORM：SQLAlchemy 2.0 async
- API：FastAPI，Pydantic v2

## Go

- 认证：`gin` middleware + `golang-jwt`
- 密码：`golang.org/x/crypto/bcrypt`
- ORM：GORM
- API：Gin，`swaggo/swag`

## Node.js

- 认证：`passport` + `jsonwebtoken`
- 密码：`bcrypt`
- ORM：TypeORM / Prisma
- API：NestJS / Express，`@nestjs/swagger`
