#!/usr/bin/env bash
# 记录 task() subagent 调用日志（供 self-evolve 分析）
# 用法: log-skill.sh <skill_id> <task描述> [ok|fail]
# 写入 ~/.opencode/history/{skill}.jsonl（用户级目录，不随项目清理）

SKILL="$1"
TASK_DESC="${2:-unknown}"
OK="${3:-ok}"
HISTORY_DIR="${HOME:-/tmp}/.opencode/history"

[ -z "$SKILL" ] && echo "用法: log-skill.sh <skill_id> <task描述> [ok|fail]" && exit 1

mkdir -p "$HISTORY_DIR"
echo "{\"skill\":\"$SKILL\",\"task\":\"${TASK_DESC:0:200}\",\"ok\":$( [ "$OK" = "ok" ] && echo true || echo false ),\"ts\":$(date +%s)000}" >> "$HISTORY_DIR/${SKILL}.jsonl"
echo "  📝 已记录 $SKILL 调用日志"
