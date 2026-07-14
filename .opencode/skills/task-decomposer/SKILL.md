---
name: task-decomposer
description: |
  软件模块详细设计。将 SAD 拆解为模块级详设文档（含业务规则、OpenAPI、伪代码、DDL）。
  适用场景：
  - 有 SAD，需生成模块详设
  - 生成编码规范、项目规则文档
  - 需要精确接口契约和测试用例设计
  不适用场景（勿触发）：
  - 纯技术问答
  - 无架构文档的情况下直接写代码
  - 已有详设，只需编码（code-developer）
---
## 工作流

**Step 0：** 恢复模式（检查 `_PROGRESS.md`）→ 端类型探测（SAD→PRD→目录→询问）→ 确定执行路径（纯后端/含前端/含小程序）。

**Step 1：** 解析 SAD，识别模块/API/数据模型。含前端时必须比对接口需求缺口（规则零来源）。加载 `templates/progress-format.md`，立即写入 `_PROGRESS.md`。

**Step 2：** 加载 `resources/layer-model.md`。按 LC-001 分配 Layer 0-4，建立构建顺序。

**Step 2.5（不可跳过）：** 加载 `resources/chain-derivation.md`。7 条规则逐模块扫描：

| 规则 | 内容 |
|------|------|
| 规则零 | 需求缺口 → 补充接口 |
| 规则一 | PUT/DELETE/PATCH 有无对应 GET |
| 规则二 | 状态机完整性（枚举+校验+逆向） |
| 规则三 | 跨模块依赖（精确到接口路径） |
| 规则四 | 数据生命周期（解绑/恢复/查询） |
| 规则五 | 异步流程（任务状态查询+死信） |
| 规则六 | 权限与数据隔离 |

输出推导报告 → 用户确认 → 锁定接口清单。**确认前禁止 Step 3**。

**Step 3：** 加载 `templates/backend-detailed.md`。每文档 13 节。第 3 节必须是 `yaml` 代码块含 requestBody/responses/错误码。一次只生成一份，更新 `_PROGRESS.md` 后等"继续"。

**Step 4（含前端时）：** 加载 `templates/frontend-template.md` + `resources/frontend-guide.md`（按端跳转）。字段级双向核对（5A 正向：前端字段⊆后端；5B 反向：后端枚举/必填字段前端全部纳入）。三端架构时小程序写入前做前端×小程序字段名一致性比对。

**Step 5：** 加载 `templates/rules-template.md` + `resources/lang-engineering.md`（按 LC-001 跳转）。保存 `doc/detailed/编码规范.md` + `doc/detailed/项目规则.md`。自检：LC 无占位符、BR 有来源、ER 项目专属、无 `{例:`。

### 门禁

- 第 3 节为 `yaml` 代码块
- Step 2.5 补充接口已出现在第 1、3 节
- 前端/小程序已完成 5A/5B 核对
- 更新 `_PROGRESS.md` 后才写下一份

### 熔断

`_PROGRESS.md` 未创建就生成 / Step 2.5 未确认可进入 Step 3 / `tech-stack.json` 不存在且 SAD 无技术栈 / 连续生成多份未等"继续" / 写入失败 → 停止

> 📐 遵循 `.opencode/rules/json-write-safety.md`
