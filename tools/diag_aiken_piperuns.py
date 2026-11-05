"""Diagnostic (read-only): the pipe runs inside an area of one Aiken sheet
(displayed coordinates, as diag_aiken_crop takes them): length, dashed or
solid, double-line share and pair spacing, the size each took and its
neighbours (work copy).
    python tools/diag_aiken_piperuns.py P-101 880 900 1300 1150"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import app  # noqa: E402,F401
import fitz  # noqa: E402
import aiken_eval  # noqa: E402
from app import aitakeoff as ait, tradetakeoff as tt  # noqa: E402

num = sys.argv[1].upper()
box = fitz.Rect(*(float(v) for v in sys.argv[2:6]))
doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))
rows = ait.plan_set(doc, None)
r = next(r for r in rows if (r.get("number") or "").upper() == num)
page = doc[r["page"]]
pb = box * page.derotation_matrix
print(num, "area (page coords)", [round(v) for v in pb])
tt.mep_runs(page, r["scale"][1], r["scale"][2],
            debug=(pb.x0, pb.y0, pb.x1, pb.y1))
for t in tt.labels(page):
    if t["kind"] == "pipe" and fitz.Rect(t["rect"]).intersects(pb):
        print("  tag", t["name"], [round(v) for v in t["rect"]])
