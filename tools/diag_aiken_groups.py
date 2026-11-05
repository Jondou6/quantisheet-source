"""Diagnostic (read-only): rows of the last Aiken scorecard's
score_groups.csv whose group id matches a pattern (work copy).
    python tools/diag_aiken_groups.py "H23-D"""
import csv
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import aiken_eval  # noqa: E402

rx = re.compile(sys.argv[1] if len(sys.argv) > 1 else ".")
f = os.path.join(aiken_eval.work_dir(), "out", "score_groups.csv")
print(f, os.path.getmtime(f))
with open(f, newline="", encoding="utf-8") as fh:
    for row in csv.DictReader(fh):
        gid = next(iter(row.values()))
        if rx.search(gid or ""):
            print(" | ".join(str(v)[:60] for v in row.values()))
