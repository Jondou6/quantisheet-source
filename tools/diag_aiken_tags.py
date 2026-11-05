"""Diagnostic (read-only): tags of the given keys counted on one Aiken
sheet (work copy) the way schedule keys are counted.
    python tools/diag_aiken_tags.py A-101 window A.1,A.2,B,C"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import app  # noqa: E402,F401
import fitz  # noqa: E402
import aiken_eval  # noqa: E402
from app import aitakeoff as ait, schedules  # noqa: E402

num, kind, ks = sys.argv[1].upper(), sys.argv[2].replace("_", " "), sys.argv[3].split(",")
doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))
rows = ait.plan_set(doc, None)
r = next(r for r in rows if (r.get("number") or "").upper() == num)
info = schedules.sheet_info(doc[r["page"]], {})
ex = schedules.plan_exclusions(info, None)
keys = {schedules.norm_key(k, kind).upper(): schedules.norm_key(k, kind)
        for k in ks}
c = schedules.count_tags(info, keys, kind, ex)
print("views", c["views"], "main", c["main_views"], "skipped", c["skipped"])
for k, hs in sorted(c["main"].items()):
    print(" main", k, sum(h["n"] for h in hs),
          [(h["text"], [round(v) for v in h["rect"]], h.get("part"))
           for h in hs])
for k, hs, vt in c["other"]:
    print(" other", k, vt, len(hs))
# neighbours of each hit (text within 4 text heights) and nearby curves
segs = info["segs"] or []
for k, hs in sorted(c["main"].items()):
    for h in hs:
        x0, y0, x1, y1 = h["rect"]
        th = y1 - y0
        near = [d["text"] for d in info["cells"] if d["text"] != h["text"] and
                abs(d["cy"] - (y0 + y1) / 2) < 2 * th and
                x0 - 6 * th < d["cx"] < x1 + 6 * th]
        ns = sum(1 for s in segs if x0 - 3 * th < min(s[0], s[2]) and
                 max(s[0], s[2]) < x0 and abs((s[1] + s[3]) / 2 -
                                              (y0 + y1) / 2) < 1.5 * th)
        print("  near", k, [round(v) for v in h["rect"]], near[:6],
              "segs left:", ns)
