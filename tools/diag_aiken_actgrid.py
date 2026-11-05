"""Diagnostic (read-only): the lay-in ceiling grid on an Aiken reflected
ceiling plan (app/actgrid) - the pens that look like a grid, the area the
grid covers, and a picture with the covered area tinted (work copy).
    python tools/diag_aiken_actgrid.py [A-201]  ->  .work/diag/<sheet>_act.png"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import app  # noqa: E402,F401
import fitz  # noqa: E402
import numpy as np  # noqa: E402
import aiken_eval  # noqa: E402
from app import actgrid, aitakeoff as ait, tradetakeoff as tt  # noqa

num = (sys.argv[1] if len(sys.argv) > 1 else "A-201").upper()
doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))
rows = ait.plan_set(doc, None)
r = next(r for r in rows if (r.get("number") or "").upper() == num and
         r.get("kind") != "superseded")
page = doc[r["page"]]
_l, ppu, unit = r["scale"]
pf = tt._per_ft(ppu, unit)
print(num, "page", r["page"], "scale", r["scale"][0], "per_ft", round(pf, 3),
      "rotation", page.rotation)
for style, segs in sorted(tt.styled_segments(page).items(),
                          key=lambda kv: -len(kv[1]))[:12]:
    hs, vs = actgrid._axis_segs(segs, pf)
    fh, sh, nh = actgrid._spaced(hs, pf)
    fv, sv, nv = actgrid._spaced(vs, pf)
    print(f"  style {style}: {len(segs)} segs, h {nh} pos {fh:.2f}@{sh}, "
          f"v {nv} pos {fv:.2f}@{sv}")
import collections  # noqa: E402
fg = actgrid.find_grid(page, pf)
if fg:
    for nm, ls in (("h", fg[1]), ("v", fg[2])):
        pos = sorted({round(c, 1) for _a, _b, c in ls})
        gaps = collections.Counter(round((b - a) / pf * 4) / 4
                                   for a, b in zip(pos, pos[1:]))
        print(f"  {nm} gaps (ft: count):", sorted(gaps.items(),
                                                   key=lambda kv: -kv[1])[:12])
        lens = collections.Counter(round((b - a) / pf) for a, b, _c in ls)
        print(f"  {nm} lengths (ft: count):", sorted(
            lens.items(), key=lambda kv: -kv[1])[:12])
g = actgrid.grid_area(page, pf)
if not g:
    print("no grid found")
    sys.exit(0)
print("grid:", g["style"], "lines", g["lines"], "tiles", g["spacing_ft"],
      "SF", g["sf"])
print(g["why"])
z = 1.0
pix = page.get_pixmap(matrix=fitz.Matrix(z, z))
img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
    pix.height, pix.width, pix.n).copy()
ox, oy, k = g["origin"]
ys, xs = np.nonzero(g["mask"])
# mask px -> page units -> displayed px (rotation 0 assumed for the tint)
px = ((xs / k + ox) * z).astype(int)
py = ((ys / k + oy) * z).astype(int)
ok = (px >= 0) & (px < pix.width) & (py >= 0) & (py < pix.height)
img[py[ok], px[ok], 0] = (img[py[ok], px[ok], 0] * 0.5).astype(np.uint8)
img[py[ok], px[ok], 1] = (img[py[ok], px[ok], 1] * 0.8).astype(np.uint8)
out = os.path.join(ROOT, ".work", "diag", f"{num}_act.png")
os.makedirs(os.path.dirname(out), exist_ok=True)
fitz.Pixmap(fitz.csRGB if pix.n == 3 else pix.colorspace, pix.width,
            pix.height, img.tobytes(), pix.alpha).save(out)
print("picture:", out)
