"""Diagnostic (read-only): each Aiken sheet's scale graded against its
printed dimensions (app/scalecheck), with a few samples (work copy).
    python tools/diag_aiken_scale.py [A-|M-|...]"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import app  # noqa: E402,F401
import fitz  # noqa: E402
import aiken_eval  # noqa: E402
from app import aitakeoff as ait, scalecheck, tradetakeoff as tt  # noqa

ALL = "all" in sys.argv[2:]
pre = sys.argv[1].upper() if len(sys.argv) > 1 else ""
doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))
rows = ait.plan_set(doc, None)
for r in rows:
    if not r.get("scale") or not (r.get("number") or "").upper().startswith(
            pre) or r.get("kind") == "superseded":
        continue
    _l, ppu, unit = r["scale"]
    oth = ait._other_scales(doc[r["page"]])
    g = scalecheck.grade(doc[r["page"]], tt._per_ft(ppu, unit), others=oth)
    print(f"{r['number']:<7} {r['scale'][0]:<16} grade={g['grade']} "
          f"ratio={g['ratio']} n={g['n']} other={g.get('other_view')}/{oth} "
          f"agree={g['spread']} {g['why'][:70]}")
    for s in g["samples"][:None if ALL else 3]:
        print("        ", s)
