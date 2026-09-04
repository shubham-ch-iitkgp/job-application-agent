"""Structured per-run log.

One JSONL file per (apply.sh run x job URL) under logs/runs/. Each line is one
event object: run_start, jd_capture, plan_request, plan_response, field_outcome,
page_fill, run_end. It's appended as the run progresses, so a mid-run crash still
leaves a usable file.

The point: after N runs you can grep logs/runs/*.jsonl (or run analyze_runs.py,
or hand the directory to an LLM) and answer "which fields keep getting skipped,
and what exactly were they".

Logging must never break a run — every write is wrapped, and open_run_log()
returns a no-op logger if the file can't be opened.
"""

import datetime
import json
import os
import subprocess
import time

RUNS_DIR = os.path.join(os.path.dirname(__file__), "logs", "runs")
_CAP = 8000  # per-string / per-payload character cap


def _clip(value, n: int = _CAP) -> str:
    s = value if isinstance(value, str) else json.dumps(value, default=str)
    if len(s) <= n:
        return s
    return s[:n] + f"...[+{len(s) - n} chars]"


def _git_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=os.path.dirname(__file__), capture_output=True, text=True, timeout=3,
        ).stdout.strip()
    except Exception:
        return ""


class RunLog:
    def __init__(self, path: str, run_id: str):
        self.path = path
        self.run_id = run_id

    def event(self, name: str, /, **fields) -> None:
        rec = {"ts": round(time.time(), 3), "run_id": self.run_id, "event": name}
        rec.update(fields)
        try:
            line = json.dumps(rec, default=str, ensure_ascii=False)
            with open(self.path, "a") as f:
                f.write(line + "\n")
        except Exception:
            pass  # a logging failure must never propagate into a run


class _NullLog:
    run_id = None
    path = None

    def event(self, name: str, /, **fields) -> None:
        pass


def open_run_log(url: str, slug: str, meta: dict) -> "RunLog | _NullLog":
    """Create logs/runs/<ts>__<slug>.jsonl and emit run_start. Returns a _NullLog
    (no-op) if anything goes wrong, so callers never have to check for None."""
    try:
        os.makedirs(RUNS_DIR, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        run_id = f"{ts}__{(slug or 'job')[:40]}"
        path = os.path.join(RUNS_DIR, f"{ts}__{(slug or 'job')[:80]}.jsonl")
        log = RunLog(path, run_id)
        log.event("run_start", url=url, git_sha=_git_sha(), **meta)
        return log
    except Exception:
        return _NullLog()
