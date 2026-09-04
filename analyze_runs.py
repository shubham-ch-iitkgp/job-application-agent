"""Summarize logs/runs/*.jsonl — which form fields keep getting skipped or fail.

Usage:
    python analyze_runs.py                 # all runs under logs/runs/
    python analyze_runs.py logs/runs/20260904-*.jsonl   # a subset

For each (field label, outcome) that is a skip or a failed fill, prints how many
times it happened, across how many distinct runs, with the field tag/type and a
couple of example run ids. Point it at the directory or hand the raw .jsonl files
to an LLM for a deeper read.
"""

import collections
import glob
import json
import os
import sys

RUNS_DIR = os.path.join(os.path.dirname(__file__), "logs", "runs")

BAD = {"skipped_no_plan", "skipped_llm", "skipped_no_value", "fill_failed"}


def main(argv: list[str]) -> int:
    paths = []
    for arg in argv:
        paths.extend(glob.glob(arg))
    if not paths:
        paths = sorted(glob.glob(os.path.join(RUNS_DIR, "*.jsonl")))
    if not paths:
        print(f"no run logs found (looked in {RUNS_DIR})")
        return 1

    runs = set()
    agg = collections.defaultdict(lambda: {"n": 0, "runs": set(), "tag": "",
                                           "type": "", "options": None,
                                           "plan_value": ""})
    totals = collections.Counter()

    for path in paths:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if rec.get("event") != "field_outcome":
                    continue
                runs.add(rec.get("run_id"))
                outcome = rec.get("outcome", "")
                totals[outcome] += 1
                if outcome not in BAD:
                    continue
                key = ((rec.get("label") or "").strip()[:80], outcome)
                e = agg[key]
                e["n"] += 1
                e["runs"].add(rec.get("run_id"))
                e["tag"] = rec.get("tag", "")
                e["type"] = rec.get("type", "")
                e["options"] = rec.get("options")
                e["plan_value"] = rec.get("plan_value", "")

    print(f"{len(paths)} log file(s), {len(runs)} run(s)\n")
    print("outcome totals:", dict(totals), "\n")
    if not agg:
        print("no skipped / failed fields \U0001f389")
        return 0

    print("skipped / failed fields (most frequent first):\n")
    for (label, outcome), e in sorted(agg.items(), key=lambda kv: -kv[1]["n"]):
        opts = "" if e["options"] is None else f"  options={e['options']}"
        pv = f"  planned={e['plan_value']!r}" if e["plan_value"] else ""
        egs = ", ".join(sorted(e["runs"])[:3])
        print(f"  [{outcome}] x{e['n']} in {len(e['runs'])} run(s) "
              f"({e['tag']}/{e['type']}){opts}{pv}")
        print(f"      {label!r}")
        print(f"      e.g. {egs}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
