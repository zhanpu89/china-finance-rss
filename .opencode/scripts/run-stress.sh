#!/usr/bin/env bash
# Uniform stress-runner for the non-SSE surface (8053).
# Wraps the three existing suites in tests/ and tees each phase to
# /tmp/opencode/stress-<tag>-<n>.log (intermediate artifact, not committed).
#
# Usage:
#   bash .opencode/scripts/run-stress.sh --tag baseline [--quick] [--url http://127.0.0.1:8053]
#
# Phases:
#   1. stress_test.py   RSS+JSON+CDP panels, concurrency 20 (--quick: 1 iteration)
#   2. stress_all.py    all non-news JSON endpoints, concurrency 15, 60/60 (incl. memory check)
#   3. loadtest.py      6-phase suite incl. 20s sustained mixed load
#
# SSE (8054 /stream/*) is intentionally never touched.
# Exit code: 0 = all phases green; 1 = at least one phase reported failures.

set -u

TAG="run"
URL="http://127.0.0.1:8053"
QUICK=0
LOG_DIR="/tmp/opencode"

while [ $# -gt 0 ]; do
  case "$1" in
    --tag) TAG="${2:-run}"; shift 2 ;;
    --url) URL="${2:-$URL}"; shift 2 ;;
    --quick) QUICK=1; shift ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

mkdir -p "$LOG_DIR"
OVERALL=0
N=0

run_phase() {
  N=$((N + 1))
  local name="$1"; shift
  local log="$LOG_DIR/stress-$TAG-$N-$name.log"
  echo ""
  echo "════════════════════════════════════════════════════════"
  echo "[$N] ${name}  →  $log"
  echo "════════════════════════════════════════════════════════"
  # Run in poetry-free stdlib land inside the repo dir; tee keeps the log.
  ( cd /root/app/china-finance-rss && "$@" 2>&1 | tee "$log" )
  local rc=${PIPESTATUS[0]}
  if [ "$rc" -ne 0 ]; then
    echo "[$N] ${name}: FAILED (exit $rc)"
    OVERALL=1
  else
    echo "[$N] ${name}: OK"
  fi
}

# Phase 1: stress_test.py
if [ "$QUICK" -eq 1 ]; then
  run_phase "stress_test" python3 tests/stress_test.py --iterations 1 "$URL"
else
  run_phase "stress_test" python3 tests/stress_test.py "$URL"
fi

# Phase 2: stress_all.py
run_phase "stress_all" python3 tests/stress_all.py --concurrency 15 --requests 60 --url "$URL"

# Phase 3: loadtest.py (sustained 20s mixed load + batch scalability)
if [ "$QUICK" -eq 1 ]; then
  run_phase "loadtest" python3 tests/loadtest.py "$URL" --duration 10
else
  run_phase "loadtest" python3 tests/loadtest.py "$URL" --duration 20
fi

echo ""
echo "════════════════════════════════════════════════════════"
echo "stress run '$TAG' finished: overall exit = $OVERALL"
echo "logs in $LOG_DIR/stress-$TAG-*.log"
echo "════════════════════════════════════════════════════════"
exit $OVERALL