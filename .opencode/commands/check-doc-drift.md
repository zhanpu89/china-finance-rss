---
description: 检测代码与契约文档的接口漂移（接口路径、字段对齐）
agent: explore
---
# 文档-代码漂移检测

## 扫描范围

1. `doc/detailed/` — 各模块详设文档的第 3 节（API 调用表 / OpenAPI 规范），提取：
   - 接口路径（URL）
   - HTTP 方法
   - 请求参数字段及类型
   - 响应字段及类型

2. `src/` — 实际代码，提取：
   - 后端 controller/route 定义（路径、方法、参数）
   - 前端 API 调用层（路径、方法、请求参数、响应字段）

## 对比规则

| 对比项 | 严重程度 | 说明 |
|--------|---------|------|
| 接口在文档但无代码 | P1 | 文档定义但未实现 |
| 接口在代码但无文档 | P2 | 代码实现但文档未记录 |
| 路径不一致 | P0 | 同一接口路径不同 |
| HTTP 方法不一致 | P0 | GET vs POST 等 |
| 请求字段不一致 | P0 | 字段名/类型不匹配 |
| 响应字段不一致 | P0 | 字段名/类型不匹配 |

## 输出

Markdown 漂移报告，格式：

```markdown
# 文档-代码漂移报告
生成时间: {timestamp}

## P0 阻断项（必须修复）
- [{模块}] {描述}

## P1 告警
- [{模块}] {描述}

## P2 提示
- [{模块}] {描述}
```

## 修复（dispatch subagent 同步）

发现 P0/P1 漂移后，**不直接 edit 文档**，按漂移文件类型 dispatch 对应 subagent：

| 漂移文件 | subagent | 入参 |
|---------|----------|------|
| `doc/detailed/*.md` | `task-decomposer` | 漂移报告路径 + 目标文件路径 + 描述 |
| `doc/arch/SAD.md` | `system-architect` | 漂移报告路径 + 目标文件路径 + 描述 |
| `doc/prd/*.md` | `prd-writer` | 漂移报告路径 + 目标文件路径 + 描述 |

**prompt 模板：** `根据漂移报告 {report_path} 同步 {path}，只修改涉及部分，不重写全文。`

> 不含 `doc/` 前缀时默认走 `task-decomposer`。
