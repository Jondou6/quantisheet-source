"""Diagnostic (read-only): each wall-type tag on a sheet, the nearest wall
and the thin lines that start at the tag (leaders), from the work copy.
    python tools/diag_tag_leaders.py A-101 [code]"""
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import app  # noqa: E402,F401
import fitz  # noqa: E402
import aiken_eval  # noqa: E402
from app import aitakeoff as ait, autowalls, tradetakeoff as tt  # noqa: E402

num = sys.argv[1].upper()
only = sys.argv[2] if len(sys.argv) > 2 else None
doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))
row = next(r for r in ait.plan_set(doc, None)
           if (r.get("number") or "").upper() == num)
page = doc[row["page"]]
_l, ppu, unit = row["scale"]
pf = tt._per_ft(ppu, unit)
ws = autowalls.walls(page, ppu, unit)
thin = autowalls._thin_lines(page)
# all short strokes, any width, for comparison
alls = []
for p in page.get_drawings():
    for it in p.get("items", ()):
        if it[0] == "l":
            alls.append(((it[1].x, it[1].y), (it[2].x, it[2].y),
                         p.get("width")))
print(num, "per_ft", pf, "walls", len(ws), "thin lines", len(thin))
for t in [t for t in autowalls.find_type_tags(page) if t["code"] in "12345" and len(t["code"]) == 1]:
    if only and t["code"] != only:
        continue
    px, py = t["pt"]
    r = t["r"]
    d = min((autowalls._seg_dist(px, py, w["p0"], w["p1"]) - w["thickness"]
             / 24 * pf for w in ws), default=None)
    lead = []
    for a, b, wd in alls:
        da, db = math.hypot(a[0] - px, a[1] - py), math.hypot(b[0] - px,
                                                             b[1] - py)
        dn = min(da, db)
        L = math.hypot(b[0] - a[0], b[1] - a[1])
        if dn <= 2.5 * r and L >= 6:
            lead.append((round(dn / r, 2), round(L / pf, 1), round(wd or 0, 2)))
    hit = autowalls._leader_walls(thin, t, ws, pf)
    print(f"{t['code']:>4} {t['shape']:<8} at ({px:.0f},{py:.0f}) r={r:.1f} "
          f"nearest wall face {d / pf if d is not None else -1:.1f} ft; "
          f"leader walls {hit}; lines near {sorted(lead)[:6]}")
