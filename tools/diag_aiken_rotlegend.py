"""Diagnostic (read-only): a rotated sheet's legend as displayed - the
headings and the text lines below them in displayed coordinates, and the
linework found left of each line (work copy).
    python tools/diag_aiken_rotlegend.py P-001"""
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
doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))
rows = ait.plan_set(doc, None)
r = next(r for r in rows if (r.get("number") or "").upper() == num)
page = doc[r["page"]]
m, dm = page.rotation_matrix, page.derotation_matrix
print("rotation", page.rotation, "rect", page.rect, "mediabox", page.mediabox)
words = page.get_text("words")
lines = {}
for w in words:
    lines.setdefault((w[5], w[6]), []).append(w)
disp = []
for k, ws in lines.items():
    rr = fitz.Rect(ws[0][:4])
    for w in ws[1:]:
        rr |= fitz.Rect(w[:4])
    disp.append((rr * m, " ".join(w[4] for w in ws), rr))
heads = [d for d in disp if d[1].strip(":").upper() in
         ("LEGEND", "SYMBOLS", "SYMBOL", "PLUMBING LEGEND")]
paths = page.get_drawings()
for h in heads:
    print("HEAD", h[1], [round(v) for v in h[0]], "page", [round(v) for v in h[2]])
    below = sorted([d for d in disp if h[0].y1 - 1 <= d[0].y0 <= h[0].y1 + 1100
                    and h[0].x0 - 150 <= d[0].x0 <= h[0].x0 + 450],
                   key=lambda d: d[0].y0)
    for d in below[:80]:
        rr = d[0]
        hg = max(rr.height, 6)
        box = fitz.Rect(rr.x0 - 6 * hg, rr.y0 - 0.8 * hg, rr.x0 - 3,
                        rr.y1 + 0.8 * hg)
        sym = tt._ink_box(page, box * dm, exclude=[], paths=paths, whole=True)
        wide = fitz.Rect(rr.x0 - 12 * hg, box.y0, box.x1, box.y1)
        sw = tt._ink_box(page, wide * dm, exclude=[], paths=paths, whole=True)
        print("   ", [round(v) for v in rr], d[1][:50], "sym",
              [round(v) for v in sym * m] if sym else None, "wide",
              [round(v) for v in sw * m] if sw else None)
for name, sym in tt.legend_rows(page):
    print("ROW", name, [round(v) for v in sym])
