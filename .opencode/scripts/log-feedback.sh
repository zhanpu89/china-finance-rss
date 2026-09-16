#!/usr/bin/env bash
# 记录用户反馈（纠正/吐槽/改向）日志（供 self-evolve 分析）
# 用法:
#   log-feedback.sh "<用户原话 verbatim>" [severity] [agent] [phase] [interpretation]
#   severity: 1=风格偏好, 2=能力缺失, 3=阻断级纠正（默认 2）
# 退出码: 0=写入成功, 1=参数缺失, 2=写入失败
# 写入 ~/.opencode/history/user-feedback.jsonl（用户级目录，不随项目清理）

VERBATIM="$1"
SEVERITY="${2:-2}"
AGENT="${3:-unknown}"
PHASE="${4:-unknown}"
INTERPRET="${5:-}"
HISTORY_DIR="${HOME:-/tmp}/.opencode/history"
TS_ISO=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
PROJECT_NAME=$(basename "$(pwd)")

[ -z "$VERBATIM" ] && echo "用法: log-feedback.sh \"<用户原话>\" [severity] [agent] [phase] [interpretation]" && exit 1
case "$SEVERITY" in 1|2|3) ;; *) echo "severity 必须为 1(风格)/2(能力)/3(阻断)" && exit 1 ;; esac

# JSON 转义：反斜杠/双引号/控制字符（防止用户原话破坏 JSON-Lines）
# 注意：必须 perl -0777（slurp 整段）—— 逐行模式下 -p 会把真实换行当记录分隔符，
#       导致出现多行 .jsonl 记录。先用 \r 防 \n 错位，再统一转义真实换行。
json_escape() {
  printf '%s' "$1" | perl -0777 -pe 's/\\/\\\\/g; s/"/\\"/g; s/\t/\\t/g; s/\r/\\r/g; s/\n/\\n/g;'
}
V_ESC=$(json_escape "$VERBATIM")
I_ESC=$(json_escape "$INTERPRET")

mkdir -p "$HISTORY_DIR"
if ! echo "{\"kind\":\"user-feedback\",\"verbatim\":\"${V_ESC}\",\"severity\":${SEVERITY},\"agent\":\"${AGENT}\",\"phase\":\"${PHASE}\",\"interpretation\":\"${I_ESC}\",\"project\":\"${PROJECT_NAME}\",\"ts_iso\":\"${TS_ISO}\",\"ts_epoch\":$(date +%s)000}" >> "${HISTORY_DIR}/user-feedback.jsonl" 2>/dev/null; then
  echo "  ⚠️ 用户反馈记录失败" >&2
  exit 2
fi
echo "  📝 已记录用户反馈 (severity=$SEVERITY, agent=$AGENT)"
