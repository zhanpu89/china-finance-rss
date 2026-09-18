#!/usr/bin/env bash
# Inspect service logs within a window: count status codes & anomalies.
# Usage: bash .opencode/scripts/inspect-logs.sh [--since 45m]
set -u
SINCE="45m"
if [ "${1:-}" = "--since" ] && [ $# -ge 2 ]; then
  SINCE="$2"
fi
LOG="$(docker logs china-finance-rss --since "$SINCE" 2>&1)"
echo "─── total log lines ───"
printf '%s\n' "$LOG" | wc -l
echo "─── HTTP status distribution ───"
printf '%s\n' "$LOG" | grep -oE '" (200|201|304|400|404|429|500|502|503|504) ' | sort | uniq -c | sort -rn
echo "─── error/anomaly lines (last 20) ───"
printf '%s\n' "$LOG" | grep -iE 'error|exception|traceback|refused|reset|timeout|overflow|queue' | tail -20
echo "─── first 5 lines / last 5 lines ───"
printf '%s\n' "$LOG" | head -5
printf '%s\n' "$LOG" | tail -5