# 后端模块详细设计文档模板

> 严格按以下结构生成，所有 `{...}` 替换为实际内容。

```markdown
# {项目名称} — {模块名称} 详细设计文档
**文档编号**：DES-YYYYMMDD-NNN | **版本**：v1.0.0 | **状态**：🟡 草稿
**所属层次**：Layer {0/1/2/3/4}
**关联文档**：{架构设计文档路径}

## 1. 功能描述
- 功能1：{描述}

## 2. 业务规则
| 编号 | 规则描述 | 配置来源 |
|------|----------|---------|
| {MOD}-REG-01 | {具体约束，精确到字段、取值范围} | {硬编码/环境变量_KEY/配置文件_{key}/配置中心_{key}} |
| {MOD}-BIZ-01 | {业务规则} | 硬编码 |
> 配置来源取值：硬编码 | 环境变量_{KEY} | 配置文件_{key} | 配置中心_{key} | 注解参数

## 3. 接口定义（OpenAPI 3.0）
**{HTTP方法} {路径}**：请求/响应格式、认证方式、错误码

## 4. 功能逻辑 — 伪代码约束标记体系
| 标记 | 含义 |
|------|------|
| `# TRANSACTION_BEGIN/COMMIT/ROLLBACK` | 事务边界 |
| `# COMPENSATION:` | 后续步骤失败时的回滚操作 |
| `# FINALLY:` | 必须执行的资源清理 |
| `# LOCK: {类型} {资源}` | 并发控制（悲观锁/分布式锁） |
| `# OPTIMISTIC_LOCK: {version字段}` | 乐观锁 |
| `# RETRY: 最多{N}次，间隔{N}ms` | 失败重试 |
| `# LANGUAGE_SPECIFIC: {语言} - {提示}` | 语言特有模式 |
| `# TIMEOUT: {N}ms` | 操作超时 |
```python
def {func}({params}):
    # TRANSACTION_BEGIN
    # LOCK: 悲观锁 {table}.{key}
    # 步骤1: 参数校验
    if not validate_{field}(value):
        raise ValidationError("{CODE}", "{msg}")
    # 步骤2: 业务检查
    if repo.exists(...):
        raise ConflictError("{CODE}", "{msg}")
    # 步骤3: 核心业务
    # LANGUAGE_SPECIFIC: {lang} - {specific pattern}
    # 步骤4: 持久化
    # COMPENSATION: 步骤5失败则回退步骤4
    entity = {Entity}({fields})
    repo.save(entity)
    # 步骤5: 后置处理（消息、缓存、Token）
    # TIMEOUT: 5000ms / RETRY: 最多3次，200ms间隔
    # FINALLY: 关闭 {Resource}
    return {result}
```

## 5. 状态机与状态流转（有状态实体时需要）
状态枚举 → 合法转换表（当前→目标→触发操作→前置条件→副作用）→ 转换伪代码（含 guard + 乐观锁）

## 6. 算法说明
- {算法名}：参数，输出格式

## 7. DDL
标准 CREATE TABLE（含 id/created_at/updated_at/version/deleted，状态化实体含 status+version，适当索引）

## 8. 外部接口（本模块调用外部）
| 接口 | 协议 | 格式 | 说明 |

## 9. 内部接口（供其他模块调用）
**{HTTP方法} {路径}**：用途、认证方式、响应格式、调用约定（超时/重试/熔断）

## 10. 性能要求
| 接口 | P95 RT | TPS | 缓存策略 | 失效触发 |

## 11. 安全要求
传输安全 / 认证方式 / 敏感数据 / 防暴力破解 / SQL注入防护

## 12. 依赖关系
依赖其他模块：{无/接口路径} | 被其他模块依赖：{模块名}
```

### 文档质量检查清单
- [ ] 业务规则有编号，精确到字段约束，配置来源已标注
- [ ] 接口有完整 OpenAPI 定义，含错误响应
- [ ] 伪代码含约束标记（事务/补偿/锁/重试/清理/语言特有）
- [ ] 状态机含转换表、guard 条件、副作用、乐观锁
- [ ] DDL 含所有字段/注释/索引，状态实体含 status+version
- [ ] 缓存失效触发条件已填写
- [ ] 性能指标有具体数值（P95/P99 RT + TPS）
- [ ] 无 `{...}` 残留；头部元数据完整

### 版本号规则
MAJOR: 模块职责变更 | MINOR: 接口/规则重大调整 | PATCH: 局部修正
类型标记：🆕 v1.0.0 | 🐛 PATCH+1 | ➕ MINOR+1 | 🔄 MAJOR+1
强绑定：头部版本 = 变更记录最后一行版本

### 粒度判断
>5 功能域 → 拆分 | 2-5 功能 → 合并在一个文档 | 单功能 → 合并到相关模块

### 变更记录（最后一节）
| 版本 | 日期 | 变更类型 | 变更内容 | 变更人 |
