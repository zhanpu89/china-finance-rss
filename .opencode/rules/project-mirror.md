# 项目镜像消费规则（Project Mirror）

> **【通用方法论 · 项目资产】** 本文件随工具分发的版本是跨项目通用的专家标准。安装到项目后，整个 `.opencode/` 即成为你的**项目资产**——可直接改写本文件沉淀团队/项目专属规则，也可在项目 `opencode.json` 的 `instructions` 中增删规则条目。工具不预设任何项目特定内容。

项目已生成 `.opencode/project/` 镜像时，它描述的是**本项目**（不是通用 pipeline）。识别它、遵守它、回写它，是"专职开发者"与"通用工具"的分界。

## 1. 使用前必读

每个 agent 开始工作前，若 `.opencode/project/` 存在，**先读**：
- `conventions.md` — 本项目已确立的命名/分层/异常/事务/配置/测试约定
- `profile.md` 的「项目特色 / 约束 / 踩坑」节 — 本项目特有的限制

读到的约定**就是本项目的行为规范**，与全局 rules 冲突时，项目约定的"具象优先"（项目约定是在本项目语言/技术栈下的落地形态）。

## 2. 遵守，而不是重发明

- 编码时：新代码的命名/分层/异常处理**必须**符合 conventions.md 已记录的模式（已有模式优先于通用模板）。
- 设计时：详设的分层/接口划分对齐 profile.md 的目录结构与既有边界。
- 评审时：把 conventions.md 作为评审依据之一，代码违反项目约定 → 记为问题。

## 3. 回写（添砖加瓦）

工作过程中**从存量代码归纳出稳定的新约定**时，输出 `>>PROJECT: {节} → {事实}` 标记（编排器统一收集回写 conventions.md）：

```
>>PROJECT: 命名规范 → 本项目中 service 接口以 Service 结尾
>>PROJECT: 异常与错误处理 → 业务异常统一返回 AppError{code}
```

**仅回写符合两条的事实**：① ≥2 个同类实现证实是稳定模式 ② 对未来编码有约束力。单次实现、偶然风格、一次性 hack **不回写**（避免镜像被噪音污染）。

## 4. 不越界

- 只有编排器能执行 `mirror-log.sh` 回写。subagent 只输出 `>>PROJECT:` 标记，不直接改 conventions.md/profile.md（权限已 deny 容器；改镜像权限在编排器）。
- 项目专属能力（本项目特有的 gate/helper）提升走 self-evolve 的 `project-scripts` 目标，落在 `.opencode/project/scripts/`，不混入通用 `.opencode/scripts/`。