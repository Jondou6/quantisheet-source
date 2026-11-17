"""Thin spaces a scan's fill_hollow looks at, with the pen comparison
(made-up plans from accuracy_hard; read-only):
python tools/diag_hollow.py PLAN [N] [--seed S]"""
import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import cv2                                                    # noqa: E402
import fitz                                                   # noqa: E402
import numpy as np                                            # noqa: E402


def main(a):
    import accuracy_hard as ah
    from app import autotakeoff as at
    only = int(a[0])
    n = int(a[1]) if len(a) > 1 and a[1].isdigit() else 6
    seed = int(a[a.index("--seed") + 1]) if "--seed" in a else 21
    rnd = random.Random(seed)
    doc = fitz.open()
    sheets = []
    for i in range(n):
        ppf = [18.0, 18.0, 13.5, 9.0, 18.0, 9.0, 13.5][i % 7]
        sheets.append(ah.Sheet(doc, rnd, ppf).build())
    doc = ah.as_scan(doc)
    page, s = doc[only], sheets[only]
    pl = at.Plan(page, {"ppu": s.ppf, "unit": "ft"}, claimed=False)
    zoom, ppf = pl.zoom, pl.ppf
    print("zoom", round(zoom, 3), "ppf px", round(ppf, 2))
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom),
                          colorspace=fitz.csGRAY, annots=False, alpha=False)
    gray = np.frombuffer(pix.samples, np.uint8).reshape(
        pix.height, pix.stride)[:, :pix.width]
    m = page.rotation_matrix
    boxes = [(fitz.Rect(w[:4]) * m).normalize() * zoom
             for w in page.get_text("words")]
    ink = at.scan_ink_of(gray)
    at._blank(ink, boxes)
    free = (ink == 0).astype(np.uint8)
    nl, lab, st, _c = cv2.connectedComponentsWithStats(free, connectivity=4)
    dist = cv2.distanceTransform(free, cv2.DIST_L2, 3)
    deep = np.zeros(nl, np.float32)
    np.maximum.at(deep, lab.ravel(), dist.ravel())
    long_ = np.maximum(st[:, 2], st[:, 3])
    h, w = ink.shape
    edge = (st[:, 0] <= 0) | (st[:, 1] <= 0) | \
        (st[:, 0] + st[:, 2] >= w) | (st[:, 1] + st[:, 3] >= h)
    thin = (2.0 * deep <= at.HOLLOW_MAX_FT * ppf) & ~edge
    thin[0] = False
    cand = thin & (long_ >= at.HOLLOW_MIN_FT * ppf)
    # the same sums as _light_boxes
    lbl = np.where(cand[lab], lab, 0)
    dark = (255.0 - gray.astype(np.float64)) / 255.0
    is_ink = ink > 0
    side = []
    for dy, dx in ((-3, 0), (3, 0), (0, -3), (0, 3)):
        near = np.roll(lbl, (dy, dx), axis=(0, 1))
        pick = is_ink & (near > 0)
        side.append(np.bincount(near[pick], weights=dark[pick],
                                minlength=nl))
    wide = st[:, 2] >= st[:, 3]
    run = st[:, 4] / np.maximum(2.0 * deep, 1.0)
    lighter = np.where(wide, np.minimum(side[0], side[1]),
                       np.minimum(side[2], side[3])) / np.maximum(run, 1.0)
    heavier = np.where(wide, np.maximum(side[0], side[1]),
                       np.maximum(side[2], side[3])) / np.maximum(run, 1.0)
    ref = lighter[cand & (run >= at.HOLLOW_REF_FT * ppf)]
    heavy = float(np.median(ref)) if len(ref) else 0
    print("candidates", int(cand.sum()), "ref", len(ref), "heavy",
          round(heavy, 3), "share", at.HOLLOW_PEN_SHARE)
    for k in np.nonzero(cand)[0]:
        x, y, bw, bh = st[k, :4]
        print(f"  at ({x / ppf:6.1f},{y / ppf:6.1f}) ft  {bw / ppf:5.1f} x "
              f"{bh / ppf:5.1f} ft  thick {2 * deep[k] / ppf:4.2f} ft  "
              f"lighter/heavy {lighter[k] / max(heavy, 1e-9):5.2f}  "
              f"heavier {heavier[k] / max(heavy, 1e-9):5.2f}")


if __name__ == "__main__":
    main(sys.argv[1:])
