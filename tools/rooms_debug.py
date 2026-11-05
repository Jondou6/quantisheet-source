"""Why did a room get missed? For each room tag on a page: the tag point,
whether it sits on wall, how much clear floor is round it, and a crop of
the page and of the wall mask around it.

    python tools/rooms_debug.py FILE.pdf PAGE [NAME,NAME...]
Writes .run/rooms_debug/<page>_<name>.png (page | mask side by side)."""
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import fitz                                                   # noqa: E402
import numpy as np                                            # noqa: E402
import cv2                                                    # noqa: E402
from app import autotakeoff as at, sheets                     # noqa: E402

OUT = os.path.join(ROOT, ".run", "rooms_debug")


def main():
    path = sys.argv[1].strip('"')
    p = int(sys.argv[2])
    want = [w.strip().upper() for w in sys.argv[3].split(",")] \
        if len(sys.argv) > 3 else []
    os.makedirs(OUT, exist_ok=True)
    doc = fitz.open(path)
    page = doc[p - 1]
    row = sheets.scan(doc, [p - 1], numbers=False)[0]
    sc = {"ppu": row["scale"][1], "unit": row["scale"][2]}
    t = time.time()
    plan = at.Plan(page, sc, claimed=False)
    print(f"plan {time.time() - t:.1f}s vectors={plan.from_vectors} "
          f"vwalls={plan.vector_walls} doors={plan.doors_closed} "
          f"ppf={plan.ppf:.1f}")
    ppf_pt = sc["ppu"] / at.FT_PER_UNIT[sc["unit"]]
    from collections import Counter
    rad = Counter()
    kinds = Counter()
    for pth in page.get_drawings():
        for it in pth.get("items", ()):
            kinds[it[0]] += 1
            if it[0] != "c":
                continue
            p0, p1, p2, p3 = it[1:5]
            mid = p0 * 0.125 + p1 * 0.375 + p2 * 0.375 + p3 * 0.125
            g = at._circle3(p0, mid, p3)
            if g:
                rad[round(g[1] / ppf_pt * 2) / 2] += 1
    print("items", dict(kinds))
    print("curve radii ft", sorted(rad.items())[:40])
    print("swings", len(at.door_swings(page, ppf_pt)))
    pix = page.get_pixmap(matrix=fitz.Matrix(plan.zoom, plan.zoom),
                          annots=False, alpha=False)
    img = np.frombuffer(pix.samples, np.uint8).reshape(
        pix.height, pix.width, pix.n)[:, :, :3].copy()
    dist = plan._dist()
    tags = at.room_tags(page)
    tags += at.room_labels(page, skip=[t["pt"] for t in tags])
    for t in tags:
        name = (t.get("name") or "?").upper()
        if want and not any(w in name for w in want):
            continue
        x, y = plan.to_px(t["pt"])
        xi, yi = int(x), int(y)
        print(f"{name[:30]:30s} sf={t.get('sf')} px=({xi},{yi}) "
              f"wall={int(plan.walls[yi, xi])} "
              f"clear={dist[yi, xi] / plan.ppf:.2f}ft")
        if os.environ.get("PATHS") or want == ["JAN"]:
            inv = ~page.rotation_matrix
            q = t["pt"] * inv
            box = fitz.Rect(q.x - 1.5 * ppf_pt, q.y - 1.5 * ppf_pt,
                            q.x + 1.5 * ppf_pt, q.y + 1.5 * ppf_pt)
            for pth in page.get_drawings():
                if not fitz.Rect(pth["rect"]).intersects(box):
                    continue
                its = pth.get("items", ())
                print(f"    path rect={tuple(round(v) for v in pth['rect'])}"
                      f" type={pth.get('type')} w={pth.get('width')} "
                      f"col={pth.get('color')} fill={pth.get('fill')} "
                      f"dash={pth.get('dashes')!r} n={len(its)} "
                      f"kinds={''.join(sorted(set(i[0][0] for i in its)))}")
                for it in its[:6]:
                    print("       ", it[0], [tuple(round(v, 1) for v in x)
                                             for x in it[1:3]
                                             if hasattr(x, "x")])
        for d in at.DOOR_STEPS:
            c = plan._region((x, y), d)
            a = plan.sqft(cv2.contourArea(c)) if c is not None else None
            print(f"    door {d}: {'-' if a is None else f'{a:.1f}'}")
        r = int(10 * plan.ppf)
        y0, y1 = max(0, yi - r), min(img.shape[0], yi + r)
        x0, x1 = max(0, xi - r), min(img.shape[1], xi + r)
        a = img[y0:y1, x0:x1].copy()
        m = cv2.cvtColor(((1 - plan.walls[y0:y1, x0:x1]) * 255)
                         .astype(np.uint8), cv2.COLOR_GRAY2BGR)
        for im in (a, m):
            cv2.circle(im, (xi - x0, yi - y0), 6, (0, 0, 255), 2)
        safe = re.sub(r"[^A-Z0-9]+", "_", name)[:24]
        cv2.imwrite(os.path.join(OUT, f"{p}_{safe}.png"),
                    np.hstack([a, m]))


if __name__ == "__main__":
    main()
