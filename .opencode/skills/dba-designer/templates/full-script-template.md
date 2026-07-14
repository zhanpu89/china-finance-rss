# DDL 模板

## 全量脚本

```sql
-- {项目名}_v{版本号}_full.sql
CREATE DATABASE IF NOT EXISTS `{db}` DEFAULT CHARACTER SET utf8mb4;
USE `{db}`;
-- 按依赖顺序：基础表 → 业务表 → 中间表
-- 每张表：CREATE TABLE IF NOT EXISTS ... COMMENT '...';
-- 索引 CREATE INDEX ... 包含在 CREATE TABLE 内
-- 每字段有 COMMENT，无 FOREIGN KEY
```

## 增量脚本

```sql
-- {项目名}_v{版本号}_migration.sql
-- ALTER TABLE ... ADD COLUMN ...;
-- 回滚方案：ALTER TABLE ... DROP COLUMN ...;
```
