#!/usr/bin/env bash
#
# Scheduled restart for china-finance-rss.
#
# Purpose: on low-spec hosts (e.g. 2C2G) the in-memory cache cannot be
# reclaimed after running for days, so consumers keep receiving stale data
# until the stack is restarted. This script performs a clean
# `docker compose down && docker compose up -d` and is meant to be invoked
# from the host crontab (e.g. daily at 02:00).
#
# It does NOT modify the application; it only recycles the running stack.
set -euo pipefail

# Resolve the project root from this script's own location so the cron
# entry keeps working regardless of where the repo is cloned.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

LOG_DIR="$PROJECT_ROOT/logs"
LOG_FILE="$LOG_DIR/restart.log"
mkdir -p "$LOG_DIR"

ts() { date '+%Y-%m-%d %H:%M:%S'; }

echo "[$(ts)] Scheduled restart starting (cwd=$(pwd))" >> "$LOG_FILE"

if ! docker compose down >> "$LOG_FILE" 2>&1; then
    echo "[$(ts)] ERROR: 'docker compose down' failed" >> "$LOG_FILE"
    exit 1
fi

if ! docker compose up -d >> "$LOG_FILE" 2>&1; then
    echo "[$(ts)] ERROR: 'docker compose up -d' failed" >> "$LOG_FILE"
    exit 1
fi

echo "[$(ts)] Scheduled restart completed" >> "$LOG_FILE"
