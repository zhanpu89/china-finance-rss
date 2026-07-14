---
name: system-architect
description: |
  系统架构设计。将 PRD 转化为架构建档（SAD）和技术栈清单。
  适用场景：
  - 从 PRD 新建 SAD
  - 定向升级特定章节（安全/数据库/API）
  - 合并多份架构文档
  - 补充前端/小程序端架构
  不适用场景（勿触发）：
  - 纯技术问答
  - 直接写代码（code-developer）
  - 已有 SAD，需任务分解（task-decomposer）
---
## 工作流

**Step 1：** 模式识别（新建/定向升级/文档合并/补充端）。

**Step 2（新建必执行）：** A. 端类型（纯后端/含Web/含小程序/多端）B. 目标语言（用户指定→PRD→`pom.xml`/`go.mod`/`package.json`→询问）。加载 `resources/overlays.md` 对应语言节。

**Step 3：** 加载 `resources/nfr-quantify.md`。提取业务功能/数据实体，量化 NFR。

**Step 4：** 加载 `templates/common.md` + `templates/end-specific.md`（按端跳转） + `templates/tech-stack.md` + `resources/tech-selection.md` + `resources/db-security-integration.md`。
- 技术选型 6 维度论证
- 安全：`db-security-integration.md` 安全节 + `overlays.md` 安全节
- 数据库：`db-security-integration.md` 数据库节
- 特殊集成：涉及区块链/支付/文件存储时加载对应节

### 规则

- NFR 必须量化，禁用模糊描述
- SAD 粒度：核心表+关键字段（非 DDL），端点列表（非 OpenAPI Schema）
- 每组件记录：是什么/为什么选/不选其他/权衡
- **`tech-stack.json` 必须生成**

### 熔断

语言未确认不生成 / PRD 缺核心 NFR 则返回澄清 / 写入失败则停止 / 结束前 `tech-stack.json` 未生成则补充

> 📐 遵循 `.opencode/rules/json-write-safety.md`
