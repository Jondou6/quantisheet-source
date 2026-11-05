"""Diagnostic (read-only): the line types legends define by a sample line
and their length on each sheet (work copy).
    python tools/diag_aiken_linetypes.py C-"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import app  # noqa: E402,F401
import fitz  # noqa: E402
import aiken_eval  # noqa: E402
from app import aitakeoff as ait, tradetakeoff as tt  # noqa: E402

pre = sys.argv[1].upper() if len(sys.argv) > 1 else "C-"
doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))
rows = ait.plan_set(doc, None)
for r in rows:
    if not (r.get("number") or "").upper().startswith(pre) or \
            r.get("kind") == "superseded":
        continue
    lt = tt.legend_linetypes(doc[r["page"]])
    if not lt:
        continue
    per_ft = tt._per_ft(r["scale"][1], r["scale"][2]) if r.get("scale") \
        else None
    print("==", r["number"], r.get("title"), r.get("scale") and r["scale"][0])
    for o in lt:
        ft = o["length"] / per_ft if per_ft else None
        print(f"   {o['name'][:40]:<40} {tt.style_name(o['style']):<28} "
              f"{(f'{ft:,.0f} ft' if ft is not None else '?'):>10} "
              f"shared={o['shared']}")
