# _MEMORY_CACHE.md 模板

此模板供编排器在每 Phase 开始前重建 _MEMORY_CACHE.md 时参考。
不从文件读取，仅作格式参考。

---

```markdown
【历史经验参考】
搜索角度 A（模块名: xxx）：
  - [P-高] {session title} — {summary 第一句}
搜索角度 B（技术关键词: xxx）：
  - [P-中] {session title} — {summary 第一句}
注入理由：
  - {结果1} 对本次任务有帮助：{具体说明}

【当前 Phase 上下文】
Phase: 5a | 强度: 🟢-light | 请求: {用户请求摘要} | 前序产出: {路径}
关键决策: {列表}
下一步: {描述}

【变更范围】（P5a 后注入）
modules: order,payment | endpoints: POST /api/orders/* | 影响程度: 中

【Bug 清单】（Bug-fix Loop 时注入）
- BUG-001: {描述} | 状态: 未修复 | 文件: {路径}
```
