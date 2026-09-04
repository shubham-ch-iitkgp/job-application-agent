#!/bin/bash
# Usage:
#   ./apply.sh <job_url>          - apply to one job
#   ./apply.sh                    - run the queue in jobs.txt (one URL per line)
cd "$(dirname "$0")"
set -a; source .env; set +a
mkdir -p logs
LOG="logs/run-$(date +%Y%m%d-%H%M%S).log"
if [ -n "$1" ]; then
  .venv/bin/python -u main.py "$@" 2>&1 | tee "$LOG"
else
  .venv/bin/python -u main.py --queue data/jobs.txt 2>&1 | tee "$LOG"
fi
echo "--- full output saved to $LOG"
