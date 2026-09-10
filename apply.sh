#!/bin/bash
#
# apply.sh — convenience wrapper around main.py. It:
#   1. runs from the repo root (so .venv / data / logs resolve),
#   2. loads credentials from .env into the environment,
#   3. runs main.py, teeing all output to a timestamped file in logs/,
#   4. with no job URL, works the queue file at data/jobs.txt.
#
# Any arguments you pass are forwarded verbatim to main.py, so every main.py
# flag works here too (--manual / -m, --auto, --no-tailor, --force, --queue,
# --parallel / -p).
#
# Usage:
#   ./apply.sh <job_url> [<job_url> ...]   apply to one or more jobs
#   ./apply.sh                             work every URL in data/jobs.txt
#   ./apply.sh --manual <job_url>          manual mode — don't auto-fill; drive it
#                                          with the in-page buttons / terminal
#                                          (multi-page or login-walled forms, Workday)
#   ./apply.sh --parallel 5               keep 5 applications open at once; close any
#     (or -p 5)                            tab and the next queued job opens in its
#                                          place. Manual mode under -p is buttons-only.
#   ./apply.sh --auto <job_url>            force auto-fill even if local.yaml says manual
#   ./apply.sh --no-tailor <job_url>       upload the master CV as-is (skip tailoring)
#   ./apply.sh --force <job_url>           re-apply even if the URL is already in applied.csv
#   ./apply.sh --queue <file>              use a queue file other than data/jobs.txt
#   ./apply.sh -h | --help                 show this help and exit
#
# Always single-quote the URL — job URLs contain & and ? which the shell would
# otherwise interpret:  ./apply.sh 'https://site/apply?a=1&b=2'
#
# Prefix with APP_ENV=local to also read local.yaml, e.g.:
#   APP_ENV=local ./apply.sh --manual 'https://acme.wd5.myworkdayjobs.com/...'

usage() {
  # print the header comment block above (strip the leading "# ")
  sed -n '3,31p' "$0" | sed 's/^#\{1,\} \{0,1\}//; s/^#$//'
}

# --help / -h anywhere on the command line
for arg in "$@"; do
  case "$arg" in
    -h|--help) usage; exit 0 ;;
  esac
done

# 1. always operate from the repo root
cd "$(dirname "$0")"

# 2. load LLM_API_KEY (+ optional LLM_BASE_URL / LLM_MODEL / ...) from .env.
#    `set -a` exports every variable the file defines; `set +a` turns that back off.
if [ -f .env ]; then
  set -a; source .env; set +a
else
  echo "warning: no .env file found — LLM_API_KEY is probably unset" >&2
fi

# 3. one timestamped log per run
mkdir -p logs
LOG="logs/run-$(date +%Y%m%d-%H%M%S).log"
echo "  transcript : $LOG"

if [ -n "$1" ]; then
  # URL(s) and/or flags — forward as-is. main.py works data/jobs.txt itself when
  # it gets flags but no URL / --queue (e.g. `./apply.sh --parallel 5`).
  .venv/bin/python -u main.py "$@" 2>&1 | tee "$LOG"
else
  # no arguments at all — point it at the default queue file
  .venv/bin/python -u main.py --queue data/jobs.txt 2>&1 | tee "$LOG"
fi

echo "--- full output saved to $LOG"
