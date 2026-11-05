"""Auto Takeoff Rooms on real sheets: per room tag, the area found vs the
tag, plus a picture of what was found and the wall mask.

    python tools/rooms_real.py FILE.pdf PAGE[,PAGE...]   (1-based pages)
Writes .run/rooms_real/<page>.png and _mask.png, prints the table."""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import fitz                                                   # noqa: E402
import numpy as np                                            # noqa: E402
import cv2                                                    # noqa: E402
from app import autotakeoff, sheets                           # noqa: E402

OUT = os.path.join(ROOT, ".run", "rooms_real")


def run(path, pages):
    os.makedirs(OUT, exist_ok=True)
    doc = fitz.open(path)
    tot = ok5 = ok12 = 0
    for p in pages:
        page = doc[p - 1]
        row = sheets.scan(doc, [p - 1], numbers=False)[0]
        if not row["scale"]:
            print(f"page {p}: no scale read")
            continue
        sc = {"ppu": row["scale"][1], "unit": row["scale"][2]}
        t = time.time()
        found, missed = autotakeoff.all_rooms(page, sc, skip_measured=False)
        print(f"\n== page {p} {row['number']} {row['title']} "
              f"{row['scale'][0]} ({time.time() - t:.1f}s)")
        for r in sorted(found, key=lambda r: r["name"] or ""):
            tag = r.get("tag_sf")
            err = (r["sqft"] - tag) / tag if tag else None
            if tag:
                tot += 1
                ok5 += abs(err) <= 0.05
                ok12 += abs(err) <= 0.12
            print(f"  {r['name'][:28]:28s} tag {tag or '-':>6} found "
                  f"{r['sqft']:8.1f}  {'' if err is None else f'{err:+.1%}'}")
        for t_ in missed:
            if t_.get("sf"):
                tot += 1
            print(f"  {(t_.get('name') or '?')[:28]:28s} tag "
                  f"{t_.get('sf') or '-':>6} MISSED")
        # pictures
        plan = autotakeoff.Plan(page, sc, claimed=False)
        cv2.imwrite(os.path.join(OUT, f"{p}_mask.png"),
                    (1 - plan.walls) * 255)
        pix = page.get_pixmap(matrix=fitz.Matrix(plan.zoom, plan.zoom),
                              annots=False, alpha=False)
        img = np.frombuffer(pix.samples, np.uint8).reshape(
            pix.height, pix.width, pix.n)[:, :, :3].copy()
        over = img.copy()
        rng = np.random.default_rng(1)
        for r in found:
            pts = np.array([plan.to_px(q) for q in r["pts"]], np.int32)
            col = [int(c) for c in rng.integers(60, 230, 3)]
            cv2.fillPoly(over, [pts.reshape(-1, 1, 2)], col)
        img = cv2.addWeighted(over, 0.45, img, 0.55, 0)
        for r in found:
            pts = np.array([plan.to_px(q) for q in r["pts"]], np.int32)
            cv2.polylines(img, [pts.reshape(-1, 1, 2)], True, (0, 0, 200), 2)
        for t_ in missed:
            x, y = plan.to_px(t_["pt"])
            cv2.circle(img, (int(x), int(y)), 14, (0, 0, 255), 3)
        cv2.imwrite(os.path.join(OUT, f"{p}.png"), img[:, :, ::-1])
    print(f"\nTOTAL tagged {tot}: within 5% {ok5}, within 12% {ok12}")


if __name__ == "__main__":
    path = sys.argv[1].strip('"')
    pages = [int(x) for x in sys.argv[2].split(",")]
    if len(sys.argv) > 3:                     # experiment: minimum line weight
        os.environ["QUANTISHEET_ROOMS_MINW"] = sys.argv[3]
    run(path, pages)
