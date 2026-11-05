"""Diagnostic (read-only): the last eval run's AI lines for a plan set
(key | qty unit | status | sheets), and the console tail.
    python tools/diag_eval_lines.py colleton [regex]"""
import csv
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import aiken_eval  # noqa: E402

aiken_eval.use_set(sys.argv[1] if len(sys.argv) > 1 else "aiken")
rx = re.compile(sys.argv[2]) if len(sys.argv) > 2 else None
out = os.path.join(aiken_eval.work_dir(), "out")
con = os.path.join(out, "console.txt")
if os.path.exists(con):
    t = open(con, encoding="utf-8", errors="replace").read()
    print("console tail:", t[-1500:])
if rx and rx.pattern == "PROBLEMS":
    for nm in ("problems.txt", "unfinished.csv"):
        fp = os.path.join(out, nm)
        if os.path.exists(fp):
            print("--", nm)
            print(open(fp, encoding="utf-8", errors="replace").read()[:6000])
    sys.exit(0)
f = os.path.join(out, "ai_lines.csv")
if not os.path.exists(f):
    print("no ai_lines.csv in", out)
    sys.exit(0)
print(f, os.path.getmtime(f))
with open(f, newline="", encoding="utf-8") as fh:
    for r in csv.DictReader(fh):
        if rx and not rx.search(r.get("key", "")):
            continue
        print(f"{r.get('key','')[:80]} | {r.get('qty','')} {r.get('unit','')}"
              f" | {r.get('status','')} | {r.get('sheets','')[:30]}")
rv = os.path.join(out, "review.csv")
if rx and os.path.exists(rv):
    print("-- review.csv rows matching")
    with open(rv, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if rx.search(" ".join(str(v) for v in r.values())):
                print(" | ".join(str(v)[:140] for v in r.values()))
