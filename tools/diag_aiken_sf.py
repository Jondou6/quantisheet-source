"""Diagnostic (read-only): the 'SF' (silt fence) marks on an Aiken SWPPP
sheet and the pens drawn through them (work copy).
    python tools/diag_aiken_sf.py C-501 [label]  ->  .work/diag/<sheet>_sf.png"""
import collections
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import app  # noqa: E402,F401
import fitz  # noqa: E402
import aiken_eval  # noqa: E402
from app import aitakeoff as ait, tradetakeoff as tt  # noqa: E402

num = (sys.argv[1] if len(sys.argv) > 1 else "C-501").upper()
lab = (sys.argv[2] if len(sys.argv) > 2 else "SF").upper()
doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))
rows = ait.plan_set(doc, None)
r = next(r for r in rows if (r.get("number") or "").upper() == num and
         r.get("kind") != "superseded")
page = doc[r["page"]]
pf = tt._per_ft(r["scale"][1], r["scale"][2]) if r.get("scale") else None
print(num, "page", r["page"], "scale", r.get("scale") and r["scale"][0],
      "per_ft", pf, "rotation", page.rotation)
ws = [w for w in page.get_text("words") if w[4].strip().upper() == lab]
print(len(ws), "words", lab)
for w in ws[:8]:
    print("   ", [round(v, 1) for v in w[:4]])
styles = tt.styled_segments(page)
near = collections.Counter()
for st, segs in styles.items():
    for x0, y0, x1, y1 in segs:
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        L = math.hypot(x1 - x0, y1 - y0)
        for w in ws:
            cx, cy = (w[0] + w[2]) / 2, (w[1] + w[3]) / 2
            h = max(w[3] - w[1], 2)
            # the segment's nearest point to the word
            if L == 0:
                continue
            t = max(0, min(1, ((cx - x0) * (x1 - x0) + (cy - y0) * (y1 - y0))
                           / (L * L)))
            d = math.hypot(x0 + t * (x1 - x0) - cx, y0 + t * (y1 - y0) - cy)
            if d <= 3 * h:
                near[st] += 1
                break
for st, n in near.most_common(10):
    segs = styles[st]
    tot = sum(math.hypot(s[2] - s[0], s[3] - s[1]) for s in segs)
    lens = collections.Counter(round(math.hypot(s[2] - s[0], s[3] - s[1]), 1)
                               for s in segs)
    print(f"  {st}: {n} segs near labels, {len(segs)} segs, total "
          f"{tot / pf if pf else tot:,.1f} ft; common lengths "
          f"{lens.most_common(5)}")
from app import sitelines  # noqa: E402
gs = sitelines.marker_chains(page, pf)
for g in gs[:8]:
    print(f"  markers {g['size_pt']}pt {g['color']}: {g['markers']} in "
          f"{len(g['chains'])} rows, spacing {g['spacing_ft']} ft, "
          f"length {g['length_ft']} ft, drawn {g.get('drawn_ft')} ft")
m = page.rotation_matrix
z = 0.75
pix = page.get_pixmap(matrix=fitz.Matrix(z, z))
out = os.path.join(ROOT, ".work", "diag", f"{num}_sf.png")
os.makedirs(os.path.dirname(out), exist_ok=True)
pix.save(out)
d = fitz.open()
pg = d.new_page(width=pix.width, height=pix.height)
pg.insert_image(pg.rect, filename=out)
cols = [(1, 0, 0), (0, 0, 1), (0, 0.6, 0), (1, 0, 1)]
for k, g in enumerate(gs[:4]):
    for ch in g["chains"]:
        for x, y in ch:
            q = fitz.Point(x, y) * m * z
            pg.draw_circle(q, 3, color=cols[k], width=1.5)
pg.get_pixmap().save(out)
print("picture:", out)
