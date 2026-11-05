"""Diagnostic (read-only): one schedule table on a sheet of an eval set
(work copy) as read_cells sees it - title, kind, why, header columns,
rows, and the raw text cells inside its box.
    python tools/diag_sched_table.py M-201 "EXHAUST FAN" --set colleton"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import app  # noqa: E402,F401
import fitz  # noqa: E402
import aiken_eval  # noqa: E402
from app import aitakeoff as ait, schedules as sc  # noqa: E402

num = sys.argv[1].upper()
want = sys.argv[2].upper()
doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))
rows = ait.plan_set(doc, None)
r = next(r for r in rows if (r.get("number") or "").upper() == num and
         r.get("kind") != "superseded")
info = sc.sheet_info(doc[r["page"]], {})
ts = sc.read_cells(info["cells"], info["segs"], info["w"], info["h"],
                   r.get("discipline", ""))
for t in ts:
    if want not in t["title"].upper():
        continue
    print("==", t["title"], "| kind", t["kind"], "| confident",
          t.get("confident"), "| why", t.get("why"), "| key", t.get("key"))
    print("   bbox", [round(v) for v in t["bbox"]], "skip", t.get("skip"))
    print("   columns:", {k: v for k, v in t.items() if k in (
        "cols", "header", "qty_col", "desc_col")})
    for row in t["rows"][:12]:
        print("   row:", {k: (str(v)[:30]) for k, v in row.items()
                          if not k.startswith("_")})
    x0, y0, x1, y1 = t["bbox"]
    cs = [c for c in info["cells"] if x0 - 160 <= c["cx"] <= x1 + 4 and
          y0 - 30 <= c["cy"] <= y1 + 60]
    cs.sort(key=lambda c: (round(c["cy"] / 4), c["cx"]))
    line, last = [], None
    for c in cs[:220]:
        if last is not None and abs(c["cy"] - last) > 3:
            print("   |", " | ".join(line))
            line = []
        line.append(f"{c['text'][:24]}@{c['cx']:.0f}")
        last = c["cy"]
    if line:
        print("   |", " | ".join(line))
