# 建表规则

## 必备字段

`id`(BIGINT PK AUTO_INCREMENT) / `created_at`(DATETIME(3)) / `updated_at`(DATETIME(3)) / `deleted_at`(DATETIME(3) NULL 软删除) / `created_by`(VARCHAR(64)) / `updated_by`(VARCHAR(64))

## 规范

- 金额用 BIGINT（分），禁用 DECIMAL/FLOAT/DOUBLE
- ENUM → TINYINT + COMMENT
- VARCHAR 按实际长度（非 255），TEXT 不存可查询字段
- 物理 FOREIGN KEY 禁止 → 注释 `-- FK`
- 表名 snake_case 复数，每字段有 COMMENT
