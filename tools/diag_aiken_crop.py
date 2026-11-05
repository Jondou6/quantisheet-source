"""Diagnostic (read-only): a picture of part of one Aiken sheet (work
copy), displayed coordinates.  python tools/diag_aiken_crop.py M-101 600
1050 900 1200 [zoom]  ->  .work/diag/<sheet>_crop.png"""
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
x0, y0, x1, y1 = (float(v) for v in sys.argv[2:6])
z = float(sys.argv[6]) if len(sys.argv) > 6 else 2.0
doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))
rows = ait.plan_set(doc, None)
r = next(r for r in rows if (r.get("number") or "").upper() == num)
page = doc[r["page"]]
full = page.get_pixmap(matrix=fitz.Matrix(z, z))       # as displayed
ir = fitz.IRect(int(x0 * z), int(y0 * z), int(x1 * z), int(y1 * z))
pix = fitz.Pixmap(full.colorspace, ir, full.alpha)
pix.clear_with(255)
pix.copy(full, ir)
out = os.path.join(ROOT, ".work", "diag", f"{num}_crop.png")
os.makedirs(os.path.dirname(out), exist_ok=True)
pix.save(out)
print(out, pix.width, pix.height)
