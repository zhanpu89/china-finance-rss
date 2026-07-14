---
name: prd-writer
description: |
  需求分析与 PRD 文档撰写。通过结构化需求访谈将模糊想法转化为专业 PRD。
  适用场景：
  - 从粗略想法生成正式 PRD
  - 需求边界不清晰，需要多轮澄清
  - 定义用户画像、业务流程、功能/非功能需求
  - 全栈/多端项目，需按端拆分 PRD
  不适用场景（勿触发）：
  - 纯技术问答
  - 已有 PRD，只需开发代码（code-developer）
  - 需要架构设计（system-architect）
---
## 模式

| 模式 | 条件 |
|------|------|
| 标准 | 无结构化需求摘要 |
| 快速 | 有 `_requirements_summary.md` 或标注"需求已收集" → 跳过 Step 0-2 |
| **标准模式** Step 0：探测端类型（Web/小程序/App/纯后端）→ 锁定生成文件清单 → 用户确认 |
| Step 1：加载 `resources/interview-framework.md` → 5W1H 框架提问 5~8 个 |
| Step 2：多轮澄清（边界/用户场景/异常/KANO 优先级），每轮 5~8 问 |

### Step 3：PRD 生成

加载 `resources/filling-guide.md` + `templates/common.md` + `templates/end-specific.md`（按端类型跳转 `##` 节）。多端先 `_概览.md`，再各端独立文档。快速模式直接跳此步。

### 门禁

- 端文档数 = 锁定文件数
- 无技术术语，AC 无技术描述
- 后端文档无前端描述，前端文档只有业务交互
- 元数据完整（编号/版本/状态/日期/作者）
- 多端时 `_概览.md` 已最先生成

### 熔断

端类型未确认不生成，范围清单未满足不前进，技术术语出现即修复。

> 📐 遵循 `.opencode/rules/json-write-safety.md`
