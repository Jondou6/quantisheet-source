"""Why aren't a room's benches counted? (Nov 5, HMB 109.) Runs AI
Takeoff on a page with app.autotakeoff._with_benches watched: for each
call it saves the floor before/after, the wall-layer ink and the thick
(wall) mask side by side, and lists every small closed-off space with
the test it failed. Read-only; writes .run/bench_debug/.

    python tools/bench_debug.py FILE.pdf PAGE(1-based) [MIN_SF]"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import cv2                                                    # noqa: E402
import fitz                                                   # noqa: E402
import numpy as np                                            # noqa: E402

OUT = os.path.join(ROOT, ".run", "bench_debug")


def why(r, ink, thick, ppf):
    """The same tests as _with_benches, reported per space."""
    from app import autotakeoff as at
    free = (1 - np.maximum(r, ink)) & (1 - thick)
    n, lab, st, _c = cv2.connectedComponentsWithStats(free, connectivity=4)
    dist = cv2.distanceTransform((1 - r).astype(np.uint8), cv2.DIST_L2, 3)
    line = max(3.0, at.BENCH_LINE_FT * ppf)
    H, W = r.shape
    out = []
    for i in range(1, n):
        x, y, w, h, a = st[i]
        sf = a / ppf ** 2
        if sf < 0.5 or sf > 3 * at.BENCH_MAX_SF:
            continue
        res = {"x": int(x), "y": int(y), "w_ft": round(w / ppf, 2),
               "h_ft": round(h / ppf, 2), "sf": round(sf, 2)}
        if a > at.BENCH_MAX_SF * ppf ** 2:
            res["fail"] = "bigger than BENCH_MAX_SF"
        elif min(w, h) > at.BENCH_MAX_DEPTH_FT * ppf:
            res["fail"] = "deeper than BENCH_MAX_DEPTH_FT"
        elif x == 0 or y == 0 or x + w >= W or y + h >= H:
            res["fail"] = "touches the edge of the area"
        else:
            m = (lab[y:y + h, x:x + w] == i).astype(np.uint8)
            m = np.pad(m, 2)
            ring = cv2.dilate(m, np.ones((3, 3), np.uint8)) & (1 - m)
            ys, xs = np.nonzero(ring)
            ys, xs = ys + y - 2, xs + x - 2
            ok = (ys >= 0) & (xs >= 0) & (ys < H) & (xs < W)
            ys, xs = ys[ok], xs[ok]
            if r[ys, xs].any():
                res["fail"] = "touches the floor"
            else:
                share = float((dist[ys, xs] <= line).mean())
                res["edge_share"] = round(share, 2)
                res["dist_ft_min_med"] = [round(float(dist[ys, xs].min()) / ppf, 2),
                                          round(float(np.median(dist[ys, xs])) / ppf, 2)]
                if share < at.BENCH_EDGE_SHARE:
                    res["fail"] = "outline share too low"
                else:
                    res["fail"] = ""
        out.append(res)
    return out


def main():
    path, p = sys.argv[1].strip('"'), int(sys.argv[2])
    min_sf = float(sys.argv[3]) if len(sys.argv) > 3 else 60.0
    os.makedirs(OUT, exist_ok=True)
    from app import autotakeoff as at
    orig = at._with_benches
    calls = []

    def watch(r, ink, thick, ppf):
        got = orig(r, ink, thick, ppf)
        if r.sum() / ppf ** 2 >= min_sf:
            k = len(calls)
            img = np.hstack([r * 255, got * 255, ink * 255, thick * 255])
            cv2.imwrite(os.path.join(OUT, f"call{k:02d}.png"),
                        img.astype(np.uint8))
            calls.append({"call": k, "floor_sf": round(r.sum() / ppf ** 2, 1),
                          "added_sf": round((got.sum() - r.sum()) / ppf ** 2,
                                            2), "ppf": round(ppf, 2),
                          "shape": list(r.shape),
                          "spaces": why(r, ink, thick, ppf)})
        return got
    at._with_benches = watch
    prev = fitz.TOOLS.set_small_glyph_heights()
    fitz.TOOLS.set_small_glyph_heights(False)
    doc = fitz.open(path)
    found, _m = at.all_rooms(at.cached_page(doc[p - 1]),
                             {"ppu": 18.0, "unit": "ft"})
    fitz.TOOLS.set_small_glyph_heights(prev)
    with open(os.path.join(OUT, "calls.json"), "w", encoding="utf-8") as f:
        json.dump(calls, f, indent=1)
    for c in calls:
        print(c["call"], c["floor_sf"], "added", c["added_sf"], "ppf",
              c["ppf"], "spaces", len(c["spaces"]))


if __name__ == "__main__":
    main()
