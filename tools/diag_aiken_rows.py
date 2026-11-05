"""Diagnostic (read-only): the text rows under one schedule title on an
Aiken sheet (work copy), as the schedule reader groups them, with x / y
and the vertical rules near the header.
    python tools/diag_aiken_rows.py P-301 "PLUMBING FIXTURE SCHEDULE" [30]"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import app  # noqa: E402,F401
import fitz  # noqa: E402
import aiken_eval  # noqa: E402
from app import aitakeoff as ait, schedules  # noqa: E402

num, rx = sys.argv[1].upper(), re.compile(sys.argv[2], re.I)
n = int(sys.argv[3]) if len(sys.argv) > 3 else 30
doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))
rows = ait.plan_set(doc, None)
r = next(r for r in rows if (r.get("number") or "").upper() == num)
info = schedules.sheet_info(doc[r["page"]], {})
cells, segs = info["cells"], info["segs"]
title = next(c for c in cells if rx.search(c["text"]))
print("title", title["text"], [round(v, 1) for v in (title["x0"], title["y0"],
                                                      title["x1"], title["y1"])],
      "h", round(title["h"], 2))
th = title["h"]
below = [c for c in cells if c is not title and c["y0"] >= title["y1"] - 0.3 *
         th and c["cy"] <= title["y1"] + 60 * th and
         title["x0"] - 80 * th <= c["cx"] <= title["x1"] + 80 * th]
for i, row in enumerate(schedules.group_rows(below)[:n]):
    print(f"{i:>2} cy {row[0]['cy']:7.1f} h {row[0]['h']:.1f} | " +
          " | ".join(f"{c['text'][:24]}@{c['x0']:.0f}-{c['x1']:.0f}"
                     for c in row))
vx = sorted({round(s[0], 1) for s in segs if abs(s[0] - s[2]) <= 0.6 and
             title["x0"] - 80 * th <= s[0] <= title["x1"] + 80 * th and
             title["y1"] <= max(s[1], s[3]) and
             min(s[1], s[3]) <= title["y1"] + 60 * th})
print("vertical rules x:", vx)
for x in vx[:20]:
    ps = sorted((round(min(s[1], s[3]), 1), round(max(s[1], s[3]), 1))
                for s in segs if abs(s[0] - s[2]) <= 0.6 and abs(s[0] - x) <= 0.2)
    print("  x", x, ps[:12], "..." if len(ps) > 12 else "")
