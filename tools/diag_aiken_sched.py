"""Diagnostic (read-only): the schedules read on one Aiken sheet (work
copy) - title, kind, columns, rows, confident / why - and a picture of
the sheet with each table's box.  python tools/diag_aiken_sched.py A-801"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import app  # noqa: E402,F401
import fitz  # noqa: E402
import aiken_eval  # noqa: E402
from app import aitakeoff as ait, schedules  # noqa: E402

num = sys.argv[1].upper()
doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))
rows = ait.plan_set(doc, None)
r = next(r for r in rows if (r.get("number") or "").upper() == num)
page = doc[r["page"]]
print(num, "page", r["page"] + 1, r.get("title"), r.get("discipline"),
      "rotation", page.rotation, "engines", r.get("engines"))
ts = schedules.read_page(page, r.get("discipline", ""))
for t in ts:
    print("=" * 60)
    print(t.get("title"), "| kind", t.get("kind"), "| confident",
          t.get("confident"), "| skip", t.get("skip"), "| why", t.get("why"))
    print("  bbox", [round(v) for v in t.get("bbox", ())])
    print("  columns", t.get("columns"))
    for row in (t.get("rows") or [])[:30]:
        print("   ", {k: v for k, v in row.items() if v})
    print("  rows:", len(t.get("rows") or []))
z = 0.5
pix = page.get_pixmap(matrix=fitz.Matrix(z, z))
pic = fitz.open()
pp = pic.new_page(width=pix.width, height=pix.height)
pp.insert_image(pp.rect, pixmap=pix)
for t in ts:
    x0, y0, x1, y1 = t["bbox"]
    pp.draw_rect(fitz.Rect(x0 * z, y0 * z, x1 * z, y1 * z),
                 color=(1, 0, 0) if not t.get("confident") else (0, 0, 1),
                 width=1.5)
out = os.path.join(ROOT, ".work", "diag", f"{num}_sched.png")
os.makedirs(os.path.dirname(out), exist_ok=True)
pp.get_pixmap(dpi=110).save(out)
print("picture:", out)
