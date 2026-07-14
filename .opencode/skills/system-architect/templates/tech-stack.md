# 技术栈 JSON Schema

`doc/arch/tech-stack.json` 格式（每个架构设计必须生成）：

```json
{
  "project": "项目名称",
  "version": "1.0",
  "generatedAt": "YYYY-MM-DD",
  "techStack": {
    "backend": { "language": "<LC-001>", "framework": "...", "orm": "...", "test": "..." },
    "database": { "type": "<LC-002>", "orm": "...", "cache": "..." },
    "frontend": { "framework": "<LC-FE-001>", "uiLib": "...", "stateManagement": "..." },
    "infrastructure": { "messageQueue": "...", "searchEngine": "...", "monitoring": "..." }
  },
  "totalComponents": 0
}
```

按实际技术选型填充，无则不填。`primaryLanguage` 必须对应 LC-001。禁止占位符。
