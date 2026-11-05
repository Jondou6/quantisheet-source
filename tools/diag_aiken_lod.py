"""Diagnostic (read-only): the limits-of-disturbance line on a civil plan
(the dashed pen the 'LOD' labels sit on) - its length, whether it closes,
and the area inside; and silt fence (a thin line carrying small circles)
- its length (work copy).
    python tools/diag_aiken_lod.py C-501"""
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import app  # noqa: E402,F401
import fitz  # noqa: E402
import aiken_eval  # noqa: E402
from app import aitakeoff as ait, sitelines, tradetakeoff as tt  # noqa

num = sys.argv[1].upper()
doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))
rows = ait.plan_set(doc, None)
r = next(r for r in rows if (r.get("number") or "").upper() == num)
page = doc[r["page"]]
per_ft = tt._per_ft(r["scale"][1], r["scale"][2])
print(num, r.get("title"), r["scale"][0], "per_ft", per_ft)
lod = sitelines.lod(page, per_ft)
print("LOD:", {k: v for k, v in lod.items() if k != "loops"})
sf = sitelines.marked_lines(page, per_ft)
for g in sf:
    print("marked line:", {k: v for k, v in g.items() if k != "runs"})
