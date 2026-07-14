# 编码规范 / 项目规则文档模板

> ⚠️ **只写项目特有约定，不写通用最佳实践。**

## 编码规范模板 → `doc/detailed/编码规范.md`

```markdown
# {项目} 编码规范 | **版本**：1.0 | **技术栈**：{主要技术栈}

## 1. 项目结构
{从架构文档复制真实目录树}

## 2. 项目特有编码约定
### 2.1 分层调用约束（核心防架构漂移）
| 调用来源 | 允许调用 | 禁止调用 | 说明 |

### 2.2 事务与并发策略
| 场景 | 策略 | 实现方式 | 来源 |

### 2.3 异常与响应格式
| 场景 | 处理方式 | 响应结构 |

### 2.4 缓存策略
| 数据 | key 格式 | TTL | 失效触发 | 来源 |

### 2.5 其他项目特有约定
- {如：跨模块调用必须通过 Feign Client，禁止直接调用 Mapper}

## 3. 技术栈版本
| 技术 | 版本 | 用途 |
```

## 项目规则文档模板 → `doc/detailed/项目规则.md`

> 跨 Skill 共享约束基准，所有 LC/BR/ER/CC 内容必须从架构文档和详设逐条提取。

```markdown
# {项目} 项目规则文档 | **版本**：1.0 | **生效日期**：{日期}
**维护说明**：task-decomposer 生成，架构或设计变更时同步更新

## 第零部分：语言契约（Language Contract）
| 编号 | 契约项 | 值 |
|------|--------|-----|
| LC-001 | 目标语言 | {Java/Python/Go/Node.js} |
| LC-002 | 语言版本 | {如 Java 17} |
| LC-003 | Web 框架 | {Spring Boot/FastAPI/Gin/Express} |
| LC-004 | 数据访问层 | {MyBatis/SQLAlchemy/GORM/Prisma} |
| LC-005 | 包管理 | {Maven/pip+poetry/go mod/npm} |
| LC-006 | 测试框架 | {JUnit 5/pytest/testing/Jest} |
| LC-007 | 日志框架 | {SLF4J/logging/zap/winston} |
| LC-008 | 工具库偏好 | {Hutool/pendulum/标准库} |
| LC-009 | 构建产物 | {Fat JAR/Python Package/Go Binary/Node Bundle} |
| LC-010 | 代码分层模型 | {Controller-Service-Mapper/Router-Service-Repository} |

### Web 前端契约（LC-FE）
| LC-FE-001~010 | 框架/构建/UI库/状态管理/HTTP/CSS/路由/测试/包管理/分层 |

### 小程序契约（LC-MP）
| LC-MP-001~008 | 框架/基础库/UI库/状态管理/请求/分包/测试/分层 |

## 第一部分：业务规则层（Business Rules）
**⛔ 所有内容从架构文档和详设逐条提取，标注来源，精确到字段/阈值。**

### BR-GLOBAL：全局
| 编号 | 描述 | 适用范围 | 违反后果 |

### BR-AUTH：认证授权
| 编号 | 描述 | 实现方式 | 来源 |
BR-A-001: 认证方式/JWT|OAuth2/Token有效期 | BR-A-002: 登录失败锁定策略 | BR-A-003: Token刷新机制 | BR-A-004: 认证白名单

### BR-DATA：数据完整性 / BR-AUDIT：审计追踪（类似结构）

## 第二部分：工程规则层（Engineering Rules）
> ⚠️ 只写项目专属约束，不复制通用语言规则。

### ER-FORBIDDEN：项目专属禁止项
| 禁止项 | 涉及模块 | 原因 | 正确方式 | 来源 |

### ER-REQUIRED：必须实现项（格式同上）
### ER-SECURITY：安全要求（格式同上）
### ER-PERFORMANCE：性能要求（含阈值）

## 第三部分：实现完整性契约（Completeness Contract）
- CC-001 零占位：禁止 `TODO` / `UnsupportedOperationException` / `return null` / `// mock data`
- CC-002 伪代码完整翻译：详设 §4 每个伪代码步骤必须有对应实现；信息不足时询问用户
- CC-003 外部依赖：已定义接口→实现调用；未定义但逻辑清晰→生成+标注；不清晰→询问
- CC-004 业务规则完整性：详设 §2 每条规则必须有对应代码实现

## 第四部分：跨 Skill 约束传递
| Skill | 使用方式 |
|-------|---------|
| code-developer | 生成前读本文档；每个方法后对照 CC-001~004 自检；输出前对照 ER 检查 |
| code-reviewer | 违反 ER-SECURITY → P0；违反 CC-001 → P0；违反 ER-FORBIDDEN → P1 |
| tester | 每条 BR 规则 → 至少 1 正向+1 反向用例；每条 ER-SECURITY → 安全用例 |

## 附录：规则变更记录
| 版本 | 日期 | 变更内容 | 变更原因 |
```

### 项目规则质量检查清单
- [ ] LC-001~LC-010 全部填写，无 `{...}`
- [ ] BR 节无「例：」字样，每条有来源标注
- [ ] ER 节每一条均为项目专属，非通用规则
- [ ] CC 节已包含
- [ ] 全文无 `{N}` 占位符
