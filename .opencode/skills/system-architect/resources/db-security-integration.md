# 安全 / 数据库 / 特殊集成

## 安全

- 认证：按 LC-001 见 `overlays.md` 对应语言节（JWT + Refresh Token + Redis 黑名单）
- RBAC：三表模型（用户/角色/权限），禁止角色嵌入用户表
- 敏感数据：AES-256-GCM 存储，BCrypt 哈希密码
- 防攻击：SQL注入/CSRF/XSS/限流/参数校验

## 数据库

- 命名：snake_case 表名，复数名词。软删除 `deleted_at`。时间戳 `DATETIME(3)`。枚举 `TINYINT + COMMENT`
- NFR：索引策略(覆盖/复合/最左前缀)、分库分表策略、连接池

## 特殊集成

- 区块链：hash 上链，数据链下存储
- 支付：异步回调+幂等表，超时撤销
- 文件存储：OSS/S3 + CDN + 签名URL，限制大小+类型
