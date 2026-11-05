"""Leader search for one room tag: the thin lines near it, the seeds and
what detect finds at each, at the page and detail scales.

    python tools/leader_debug.py FILE.pdf PAGE NAME
"""
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import fitz                                                   # noqa: E402
from app import autotakeoff as at, sheets                     # noqa: E402


def main():
    doc = fitz.open(sys.argv[1].strip('"'))
    page = doc[int(sys.argv[2]) - 1]
    want = sys.argv[3].upper()
    row = sheets.scan(doc, [page.number], numbers=False)[0]
    sc = {"ppu": row["scale"][1], "unit": row["scale"][2]}
    tags = at.room_tags(page)
    t = next(x for x in tags if want in (x["name"] or "").upper())
    print("tag", t, "rotation", page.rotation)
    det = at.detail_scales(page)
    print("detail scales:", [(round(q.x), round(q.y), l) for q, _, _, l in det])
    ds = at.detail_scale_at(t["pt"], det, page.rect)
    print("detail scale here:", ds)
    thin = at._thin_lines(page)
    px, py = t["pt"].x, t["pt"].y
    near = sorted((min(math.hypot(a[0] - px, a[1] - py),
                       math.hypot(b[0] - px, b[1] - py)), a, b)
                  for a, b in thin)[:15]
    for d, a, b in near:
        print(f"  line {d:6.1f}pt from tag: {tuple(round(v,1) for v in a)} "
              f"-> {tuple(round(v,1) for v in b)}")
    # all strokes near, any width
    for dr in page.get_drawings():
        r = dr["rect"] * page.rotation_matrix
        if r.intersects(fitz.Rect(px - 40, py - 40, px + 80, py + 40)):
            print("  drawing", dr.get("type"), dr.get("width"),
                  [it[0] for it in dr["items"]][:6], r.round())
    seeds = at.leader_seeds(t["pt"], thin)
    print("seeds", [(round(s.x), round(s.y)) for s in seeds])
    plans = [("page", at.Plan(page, sc, claimed=False))]
    if ds:
        plans.append(("detail", at.Plan(page, {"ppu": ds[0], "unit": ds[1]},
                                        claimed=False)))
    oth = [u["pt"] for u in tags if u is not t]
    for nm, pl in plans:
        for sp in [t["pt"]] + seeds:
            r = pl.detect(sp, oth, expected=t["sf"])
            print(f"  {nm} seed {round(sp.x)},{round(sp.y)}:",
                  None if r is None else round(r["sqft"], 1))


main()
