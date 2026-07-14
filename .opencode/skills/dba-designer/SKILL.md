---
name: dba-designer
description: |
  数据库设计。根据后端详设生成 DDL 脚本（MySQL / PostgreSQL / TiDB）。
  适用场景：
  - 从详设第6节 DDL 草稿生成完整建表脚本
  - 增量 ALTER TABLE 变更
  - 验证三范式、索引策略、数据安全
  不适用场景（勿触发）：
  - 生成业务代码（code-developer）
  - 生成详设文档（task-decomposer）
  - 已有 DDL 只需要执行
  - 纯 SQL 语法问答
---
## 产出物

`doc/db/` 下：建表脚本 + 迁移脚本(增量) + 数据库设计说明文档。

## 工作流

**Step 0：** 恢复模式 → 数据库类型（项目规则 LC-002 → SAD → 询问）→ 全量/增量。

**Step 1：** 逐文档提取 §2(约束) §5(特殊结构) §6(DDL) §9(性能)。无 DDL 则从接口逆推并标注。写入 `_PROGRESS.md`。

**Step 2：** 加载 `resources/table-rules.md`。
- **必备字段：** `id`(PK)、`created_at`、`updated_at`、`deleted_at`、`created_by`、`updated_by`
- **类型规范：** 金额用 BIGINT、VARCHAR 按实际、TEXT 不存可查询字段、DATETIME(3)、ENUM→TINYINT+注释、禁止 FOREIGN KEY（改为 `-- FK` 注释）

**Step 3：** 加载 `resources/index-rules.md`。按查询场景设计索引。**禁止：** 低选择独立索引、>5字段、重复、TEXT全列。

**Step 4：** 加载 `resources/dialect-diff.md` + `templates/table-ddl-template.md`（按 LC-002）。`CREATE TABLE IF NOT EXISTS`（幂等）。每字段 `COMMENT`。增量模式→`ALTER TABLE`。一次一张表，更新 `_PROGRESS.md` 后等确认。

**Step 5：** 加载 `templates/full-script-template.md`。按依赖合并。增量模式→`{项目名}_v{版本号}_migration.sql` + 回滚方案。

**Step 6：** 输出 `doc/db/{项目名}_数据库设计说明.md`（表清单→ER图→索引→决策→变更记录）。

### 门禁

- `CREATE TABLE IF NOT EXISTS`
- 含必备字段，每字段 COMMENT
- 无 FOREIGN KEY，无 DECIMAL/FLOAT 存金额，无 ENUM
- 无保留字字段名，无占位符
- 更新 `_PROGRESS.md` 后才写下一张

### 熔断

`_PROGRESS.md` 未创建 / `doc/detailed/` 无详设 / 数据库类型未知 / 写入失败 / 连续多张未等确认 / 含 FOREIGN KEY 或占位符 → 停止

> 📐 遵循 `.opencode/rules/json-write-safety.md`
