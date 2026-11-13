"""The pictures auto takeoff works from, for a box of a truth set's sheet.

    python tools/truth_layers.py SET X0 Y0 X1 Y1

Saves .run/hard/layers_<n>.png for each wall picture of the plan (all
ink, heavy pen only), the wall-layer picture when the sheet has wall
layers, side by side with the page itself. For seeing which picture
holds the line a traced room stopped at. The drawings stay on this
computer.
"""
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def run(name, box):
    import cv2
    import fitz
    import numpy as np
    import truth_rooms as tr
    from app import aitakeoff as ait, autotakeoff as at
    src = os.path.join(tr.PLANS, tr.FILES[name])
    tmp = tempfile.mkdtemp(prefix="qs-truth-")
    doc = fitz.open(shutil.copy(src, os.path.join(tmp, "set.pdf")))
    want = tr.SHEET[name]
    row = next(r for r in ait.plan_set(doc)
               if (r["number"] or "").upper().replace("-", "") == want and
               r["kind"] != "superseded")
    page = doc[row["page"]]
    sc = row["scale"]
    plan = at.Plan(at.cached_page(page), {"ppu": sc[1], "unit": sc[2]},
                   claimed=False)
    b = fitz.Rect(box)
    p0 = plan.to_px(b.tl)
    p1 = plan.to_px(b.br)
    x0, x1 = sorted((int(p0[0]), int(p1[0])))
    y0, y1 = sorted((int(p0[1]), int(p1[1])))
    out = os.path.join(ROOT, ".run", "hard")
    os.makedirs(out, exist_ok=True)
    pics = [("layer%d" % i, L) for i, L in enumerate(plan.layers)]
    if plan.wl is not None:
        pics.append(("wall_layers", plan.wl))
    k = 6
    tiles = []
    for nm, L in pics:
        crop = (np.asarray(L)[y0:y1, x0:x1] > 0).astype(np.uint8) * 255
        crop = cv2.resize(255 - crop, None, fx=k, fy=k,
                          interpolation=cv2.INTER_NEAREST)
        crop = cv2.cvtColor(crop, cv2.COLOR_GRAY2BGR)
        cv2.putText(crop, nm, (6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                    (0, 0, 255), 2)
        tiles.append(crop)
    pm = page.get_pixmap(matrix=fitz.Matrix(plan.zoom * k, plan.zoom * k),
                         clip=b)
    im = np.frombuffer(pm.samples, np.uint8).reshape(pm.h, pm.w, pm.n)
    im = cv2.cvtColor(im[:, :, :3].copy(), cv2.COLOR_RGB2BGR)
    h = min(t.shape[0] for t in tiles + [im])
    w = min(t.shape[1] for t in tiles + [im])
    strip = np.hstack([t[:h, :w] for t in [im] + tiles])
    path = os.path.join(out, "layers.png")
    cv2.imwrite(path, strip)
    print("wrote", path, strip.shape, "ppf", plan.ppf, "pictures",
          [n for n, _ in pics])
    doc.close()
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    run(sys.argv[1], [float(v) for v in sys.argv[2:6]])
