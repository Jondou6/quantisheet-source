"""Diagnostic (read-only): the set's wall-type legend as AI Takeoff reads
it, the parts read from each description and the heights found (work
copy).  python tools/diag_aiken_wallasm.py"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import app  # noqa: E402,F401
import fitz  # noqa: E402
import aiken_eval  # noqa: E402
from app import aitakeoff as ait, wall_assembly as wa, envelope  # noqa: E402

doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))
rows = ait.plan_set(doc, None)
leg, pages = ait.wall_legend(doc, rows)
num = {r["page"]: r.get("number") for r in rows}
print("legend pages", [num.get(p) for p in pages])
for code, d in sorted(leg.items()):
    print(f"== {code}: {d}")
    print("   parts:", wa.components(d))
print("heights", ait.wall_heights(leg, ""))
ep = [r["page"] for r in rows if ait._ELEV_T.search(r.get("title") or "")]
print("elevation sheets", [num.get(p) for p in ep])
print("levels", envelope.wall_heights_from_levels([doc[p] for p in ep]))
