# 决策存取质量规则（按需加载）

ai_memory 是 stateless 模式的唯一长效记忆层（工具前缀 `ai_memory_memory_*`）。**存入质量决定取出价值。**

## 写决策模板

每条 `ai_memory_memory_add_decision()` 必须按以下模板填写：

| 字段 | 规则 | 反例 | 正例 |
|------|------|------|------|
| `decision_type` | 从 taxonomy 中选一个 | — | `bug_fix` |
| `description` | 模板：**根因 → 方案 → 理由 → 结果** | "修复了编码问题" | "AGENTS.md 的 _detect_encoding 遇到 GB2312 抛出 InvalidEncodingError；改为 UTF-8-first 三段回退链（utf-8→gb2312→latin-1）；原因是 AGENTS.md 是 AGENTS 规范文件，99% 场景为 UTF-8" |
| `reasoning` | 描述被否决的方案及原因 | — | "优先检测 BOM 的方式被否决，因为 AGENTS.md 无 BOM；全 latin-1 fallback 被否决，会导致日文文件静默损坏" |
| `tags` | 逗号分隔，含模块/层级/语言 | `"bug"` | `"encoding,agents.md,python,bug_fix"` |

## 决策类型 taxonomy

| 类型 | 适用场景 |
|------|---------|
| `architecture` | 架构方案选择、模块划分 |
| `tech_choice` | 技术选型（框架/库/工具） |
| `bug_fix` | Bug 根因分析与修复 |
| `refactor` | 重构决策 |
| `performance` | 性能优化 |
| `security` | 安全相关 |
| `api_design` | 接口设计变更 |
| `process` | 流程/规范改进 |

## 质量门禁（存入前自检）

1. ❌ "修复了问题" → 根因是什么？写了才存
2. ❌ "选择了 A 方案" → 被否决的方案和理由呢？写了才存
3. ❌ 无 `tags` 或 tags 未含模块名 → 补了才存
4. ✅ 以上都满足 → 存
