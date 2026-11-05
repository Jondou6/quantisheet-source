"""Diagnostic (read-only): dark filled shapes and rings near a point on an
Aiken sheet, as app/tradetakeoff's ring-symbol matcher sees them.
    python tools/diag_aiken_fills.py E-201 484 399 [radius]"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import app  # noqa: E402,F401
import fitz  # noqa: E402
import aiken_eval  # noqa: E402
from app import aitakeoff as ait, tradetakeoff as tt  # noqa: E402

num = sys.argv[1].upper()
x, y = float(sys.argv[2]), float(sys.argv[3])
rad = float(sys.argv[4]) if len(sys.argv) > 4 else 10.0
doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))
rows = ait.plan_set(doc, None)
r = next(r for r in rows if (r.get("number") or "").upper() == num and
         r.get("kind") != "superseded")
page = doc[r["page"]]
box = fitz.Rect(x - rad, y - rad, x + rad, y + rad)
for p in page.get_drawings():
    rr = fitz.Rect(p["rect"])
    if not box.intersects(rr) or rr.width > 4 * rad:
        continue
    print(p.get("type"), p.get("fill"), [round(v, 1) for v in rr],
          "fill->", tt._dark_fill(p), "ring->", tt._ring_like(p))
