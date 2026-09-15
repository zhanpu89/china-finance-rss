#!/usr/bin/env bash
# 记录 task() subagent 调用日志（供 self-evolve 分析）
# 用法: log-skill.sh <skill_id> <task描述> [ok|fail]
# 退出码: 0=写入成功, 1=写入失败
# 写入 ~/.opencode/history/{skill}.jsonl（用户级目录，不随项目清理）

SKILL="$1"
TASK_DESC="${2:-unknown}"
OK="${3:-ok}"
HISTORY_DIR="${HOME:-/tmp}/.opencode/history"
TS_ISO=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

[ -z "$SKILL" ] && echo "用法: log-skill.sh <skill_id> <task描述> [ok|fail]" && exit 1

mkdir -p "$HISTORY_DIR"
# JSON-Lines 格式：每行一个 JSON 对象，含 ISO 时间戳
echo "{\"skill\":\"${SKILL}\",\"task\":\"${TASK_DESC:0:200}\",\"ok\":$( [ "$OK" = "ok" ] && echo true || echo false ),\"ts_iso\":\"${TS_ISO}\",\"ts_epoch\":$(date +%s)000}" >> "${HISTORY_DIR}/${SKILL}.jsonl"
echo "  📝 已记录 $SKILL 调用日志"
