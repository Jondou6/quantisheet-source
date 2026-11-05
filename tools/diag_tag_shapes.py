"""Diagnostic (read-only): the drawn paths around short words on a sheet
(work copy) - what shape a tag symbol is drawn with.
    python tools/diag_tag_shapes.py A-101 [1-5] [n]"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import app  # noqa: E402,F401
import fitz  # noqa: E402
import aiken_eval  # noqa: E402
from app import aitakeoff as ait, autowalls  # noqa: E402

num = sys.argv[1].upper()
rx = re.compile("^(?:" + sys.argv[2] + ")$")
n = int(sys.argv[3]) if len(sys.argv) > 3 else 6
doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))
row = next(r for r in ait.plan_set(doc, None)
           if (r.get("number") or "").upper() == num)
page = doc[row["page"]]
paths = page.get_drawings()
words = [w for w in page.get_text("words") if rx.match(w[4])]
print(num, "rotation", page.rotation, "words", len(words), "paths",
      len(paths))
print("tags found:", sorted({t["code"] for t in
                             autowalls.find_type_tags(page)}))
for w in words[:n]:
    cx, cy = (w[0] + w[2]) / 2, (w[1] + w[3]) / 2
    print(f"-- word {w[4]!r} at ({cx:.1f}, {cy:.1f}) h={w[3] - w[1]:.1f}")
    for p in paths:
        r = p.get("rect")
        if r is None or not (r.x0 - 1 <= cx <= r.x1 + 1 and
                             r.y0 - 1 <= cy <= r.y1 + 1):
            continue
        if max(r.width, r.height) > 60:
            continue
        kinds = [it[0] for it in p.get("items", ())]
        print(f"   rect {r.width:.1f}x{r.height:.1f} type={p.get('type')} "
              f"close={p.get('closePath')} w={p.get('width')} items={kinds} "
              f"shape={autowalls._shape(p)}")
        pts = [(round(it[1].x - cx, 1), round(it[1].y - cy, 1),
                round(it[2].x - cx, 1), round(it[2].y - cy, 1))
               for it in p.get("items", ()) if it[0] == "l"]
        if pts:
            print("      lines (from word centre):", pts[:14])
    # nearby small paths not containing it (a shape drawn in pieces)
    near = [p for p in paths if p.get("rect") is not None and
            max(p["rect"].width, p["rect"].height) <= 20 and
            abs((p["rect"].x0 + p["rect"].x1) / 2 - cx) <= 8 and
            abs((p["rect"].y0 + p["rect"].y1) / 2 - cy) <= 8]
    for p in near[:8]:
        r = p["rect"]
        print(f"   near {r.width:.1f}x{r.height:.1f} items="
              f"{[it[0] for it in p.get('items', ())]}")
