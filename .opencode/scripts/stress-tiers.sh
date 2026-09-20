#!/usr/bin/env bash
# Five-tier (50/100/200/500/1000 codes) stress of the core real-time REST
# surface (8053).  Collects the code pool first, samples the container's
# memory/CPU while each tier runs, and records everything to a timestamped
# log under /tmp/opencode (intermediate artifact, never committed).
#
# Usage:
#   bash .opencode/scripts/stress-tiers.sh [--quick] [--url http://127.0.0.1:8053]
#
# SSE (8054) and the RSS feeds are intentionally never touched.

set -u

URL="http://127.0.0.1:8053"
PER_TIER=8
QUICK=0
LOG_DIR="/tmp/opencode"

while [ $# -gt 0 ]; do
  case "$1" in
    --url) URL="${2:-$URL}"; shift 2 ;;
    --quick) QUICK=1; shift ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

STAMP="$(date +%Y%m%d-%H%M%S)"
LOG="$LOG_DIR/stress-tiers-$STAMP.log"
mkdir -p "$LOG_DIR"

echo "===== tier stress run $STAMP =====" | tee "$LOG"
echo "url: $URL   per-tier: ${PER_TIER}s" | tee -a "$LOG"

# 1) gather the code pool (>=1000 realistic codes from board constituents)
python3 .opencode/scripts/gather-codepool.py --url "$URL" 2>&1 | tee -a "$LOG"
POOL="$LOG_DIR/codepool.json"

# 2) run the 5 tiers while sampling container memory
( cd /root/app/china-finance-rss && \
  python3 .opencode/scripts/stress-tiers.py --url "$URL" --pool "$POOL" \
    --per-tier "$PER_TIER" 2>&1 | tee -a "$LOG" ) &

STRESS_PID=$!

# 3) sample container stats while the tiers run (~every 5s)
while kill -0 "$STRESS_PID" 2>/dev/null; do
  docker stats china-finance-rss --no-stream --format \
    '{{.MemUsage}} {{.CPUPerc}}' 2>/dev/null >> "$LOG"
  sleep 5
done

wait "$STRESS_PID"
echo "===== done — log: $LOG =====" | tee -a "$LOG"