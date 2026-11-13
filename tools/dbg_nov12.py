"""Debug: the made-up shower sheet of tests/test_takeoff_nov12.py."""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tests"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import cv2, numpy as np
import test_takeoff_nov12 as T
from app import autotakeoff as at
doc, page = T.shower_sheet(stall_door="--stall" in sys.argv)
pg = at.cached_page(page)
out = os.path.join(ROOT, ".run", "hard"); os.makedirs(out, exist_ok=True)
at.DEBUG_DIR = out; at.DEBUG_TRACES = []
for c, ends in at.door_swings(pg, T.PPF):
    print("swing", c, ends)
plan = at.Plan(pg, T.SCALE, claimed=False)
print("doors closed", plan.doors_closed, "zoom", plan.zoom, "layers", len(plan.layers))
k = 4
tiles = []
for nm, L in (("walls0", plan.layers[0]), ("doorlines", plan._doorlines), ("wl", plan.wl)):
    im = cv2.resize((1 - (np.asarray(L) > 0).astype(np.uint8)) * 255, None, fx=k, fy=k, interpolation=cv2.INTER_NEAREST)
    tiles.append(im)
cv2.imwrite(os.path.join(out, "nov12_masks.png"), np.hstack(tiles))
by, missed = T._rooms(page)
for n, r in by.items():
    print(n, round(T._sf(r), 2), "truth", round(T.A_SF if n == "201" else T.B_SF, 2), [(round(q.x, 1), round(q.y, 1)) for q in r["pts"]][:30])
for d in at.DEBUG_TRACES:
    print("trace layer", d["layer"], "door", d["door"], "n", len(d["px"]))
