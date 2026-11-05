"""Diagnostic (read-only): the drawing paths and words around one point
of an Aiken sheet, in displayed coordinates (work copy).
    python tools/diag_aiken_probe.py C-501 940 733 [radius]"""
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
x, y = float(sys.argv[2]), float(sys.argv[3])
rad = float(sys.argv[4]) if len(sys.argv) > 4 else 12.0
doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))
rows = ait.plan_set(doc, None)
r = next(r for r in rows if (r.get("number") or "").upper() == num and
         r.get("kind") != "superseded")
page = doc[r["page"]]
inv = ~page.rotation_matrix
p = fitz.Point(x, y) * inv
box = fitz.Rect(p.x - rad, p.y - rad, p.x + rad, p.y + rad)
print(num, "display", (x, y), "page", (round(p.x, 1), round(p.y, 1)))
n = 0
for d in page.get_drawings():
    rr = d.get("rect")
    if rr is None or not rr.intersects(box):
        continue
    items = d.get("items", ())
    kinds = "".join(it[0] for it in items)
    big = rr.width > 6 * rad or rr.height > 6 * rad
    # items inside the box only, for big paths
    near = [it for it in items if any(
        hasattr(q, "x") and box.contains(q) for q in it[1:])]
    print(f"- type {d.get('type')} color {d.get('color')} fill "
          f"{d.get('fill')} width {d.get('width')} dashes "
          f"{d.get('dashes')} rect {[round(v, 1) for v in rr]} "
          f"items {len(items)} kinds {kinds[:40]}{'...' if big else ''}")
    for it in near[:12]:
        print("     ", it[0], [(round(q.x, 1), round(q.y, 1)) if
                                hasattr(q, "x") else q for q in it[1:]])
    n += 1
    if n > 25:
        break
for w in page.get_text("words"):
    if box.intersects(fitz.Rect(w[:4])):
        print("word", w[4], [round(v, 1) for v in w[:4]])
