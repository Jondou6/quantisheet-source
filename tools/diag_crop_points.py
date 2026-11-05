"""Diagnostic (read-only, work copy): PNG crops around points on one sheet
of an eval set, to look at what an engine found there. Crops go to
.run/crops (never shipped).
    python tools/diag_crop_points.py A-102 "1279,1296;893,1296" [half] --set colleton"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import app  # noqa: E402,F401
import fitz  # noqa: E402
import aiken_eval  # noqa: E402
from app import aitakeoff as ait  # noqa: E402

num = sys.argv[1].upper()
pts = [tuple(float(v) for v in p.split(",")) for p in sys.argv[2].split(";")]
half = float(sys.argv[3]) if len(sys.argv) > 3 else 60.0
doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))
r = next(r for r in ait.plan_set(doc, None)
         if (r.get("number") or "").upper() == num and
         r.get("kind") != "superseded")
page = doc[r["page"]]
out = os.path.join(ROOT, ".run", "crops")
os.makedirs(out, exist_ok=True)
for i, (x, y) in enumerate(pts):
    clip = fitz.Rect(x - half, y - half, x + half, y + half)
    pix = page.get_pixmap(clip=clip, dpi=300)
    f = os.path.join(out, f"{num}_{i}_{int(x)}_{int(y)}.png")
    pix.save(f)
    print(f)
