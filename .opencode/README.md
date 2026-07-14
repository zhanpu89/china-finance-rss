# my-skills

10 个软件工程 AI 技能，覆盖 PRD→架构→详设→DDL→编码→测试 全流程。

## 技能一览

| 技能 | 角色 | 工具名 |
|------|------|--------|
| **prd-writer** | 需求分析 → PRD | `call_prd_writer` |
| **review-expert** | 文档/用例评审 | `call_review_expert` |
| **system-architect** | 架构设计 + 技术栈 | `call_system_architect` |
| **task-decomposer** | 详设拆分 + 项目规则 | `call_task_decomposer` |
| **code-developer** | 编码实现（精准定位 + doc-sync） | `call_code_developer` |
| **code-reviewer** | 代码评审 | `call_code_reviewer` |
| **tester** | 测试用例 + 测试代码 | `call_tester` |
| **dba-designer** | 数据库 DDL 设计 | `call_dba_designer` |
| **self-evolve** | 工具自我进化 | `call_self_evolve` |
| **pipeline-orchestrator** | 全流程编排器 | `call_pipeline_orchestrator` |

## 目录结构

```
.opencode/
├── opencode.json        # agent 注册
├── rules/               # 始终/按需加载的行为规则
│   ├── precise-location.md     # ⚡ 精准定位
│   ├── endpoint-lock.md        # ⚡ 端锁定（契约稳定分级）
│   ├── code-discipline.md      # 🌀 编码纪律
│   ├── doc-alignment.md        # 🌀 文档同步
│   └── json-write-safety.md    # 📐 JSON 写入安全
├── skills/{skill}/
│   ├── SKILL.md          # 技能指令（YAML + 工作流）
│   ├── resources/        # 参考文档
│   └── templates/        # 输出模板
├── scripts/              # 质量门禁 + 辅助脚本
│   ├── check-*.sh        # 8 个阶段检查（PRD/架构/详设/DB/代码/评审/用例/测试）
│   └── log-skill.sh      # task() 调用日志（供 self-evolve 分析）
└── commands/
    └── check-doc-drift.md      # `/check-doc-drift` — 文档-代码接口漂移检测
```

## 关键设计

- **评审隔离**：评审 Phase 启动全新 subagent，入参仅含文档路径，杜绝自审自判
- **记忆注入**：每个 Phase 前检索历史经验，注入 subagent prompt 避免重复踩坑
- **Doc-sync**：编码不直接改契约文档，输出 `>>DOC_SYNC:` 清单由编排器统一同步
- **Token 优化**：通用模式用映射表替代重复段落，always-loaded 总量缩减约 27%

