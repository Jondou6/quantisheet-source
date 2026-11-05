"""Diagnostic (read-only): a close-up of one duct size's pieces on an Aiken
M sheet (work copy) - the pieces in red, that size's tags in green, other
tags in grey, words near the pieces listed.
    python tools/diag_aiken_ductcrop.py M-101 20x22  ->  .work/diag/<sheet>_<size>.png"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import app  # noqa: E402,F401
import fitz  # noqa: E402
import aiken_eval  # noqa: E402
from app import aitakeoff as ait, tradetakeoff as tt  # noqa: E402

num = sys.argv[1].upper()
want = sys.argv[2]
if re.match(r"^\d+in$", want):
    want = want[:-2] + '" round'
doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))
rows = ait.plan_set(doc, None)
r = next(r for r in rows if (r.get("number") or "").upper() == num and
         r.get("kind") != "superseded")
pno, (_l, ppu, unit) = r["page"], r["scale"]
page = doc[pno]
pf = tt._per_ft(ppu, unit)
tags = [l for l in tt.labels(page) if l["kind"] in ("duct", "round")]
bt, _un = tt.ducts_by_tag(page, ppu, unit)
g = next((g for g in bt if g["name"] == want), None)
if g is None:
    print("no group", want, [x["name"] for x in bt])
    sys.exit(0)
box = None
for pc in g["pieces"]:
    rr = fitz.Rect(pc["p0"], pc["p0"]) | pc["p1"]
    box = rr if box is None else box | rr
for t in tags:
    if t["name"] == want:
        box |= fitz.Point(t["center"])
box = (box + (-12 * pf, -12 * pf, 12 * pf, 12 * pf)) & \
    (page.rect * page.derotation_matrix).normalize()
print(num, want, "pieces", len(g["pieces"]), "box", [round(v) for v in box])
for pc in g["pieces"]:
    print(f"   {pc['length']:5.1f} LF width {pc['width']:5.1f} in "
          f"p0 {[round(v) for v in pc['p0']]} p1 {[round(v) for v in pc['p1']]}")
for t in tags:
    c = fitz.Point(t["center"])
    if box.contains(c):
        print("   tag", t["name"], [round(v) for v in c])
ws = [w for w in page.get_text("words") if box.contains(fitz.Rect(w[:4]))]
print("   words:", " ".join(w[4] for w in ws)[:600])
z = 2.0
m = page.rotation_matrix
cr = (box * m).normalize()                   # displayed coordinates
pix = page.get_pixmap(matrix=fitz.Matrix(z, z), clip=cr)
pic = fitz.open()
pp = pic.new_page(width=pix.width, height=pix.height)
pp.insert_image(pp.rect, pixmap=pix)


def to_pic(p):
    q = fitz.Point(p) * m
    return fitz.Point((q.x - cr.x0) * z, (q.y - cr.y0) * z)


for pc in g["pieces"]:
    pp.draw_line(to_pic(pc["p0"]), to_pic(pc["p1"]), color=(1, 0, 0),
                 width=2)
for t in tags:
    c = to_pic(t["center"])
    col = (0, 0.7, 0) if t["name"] == want else (0.5, 0.5, 0.5)
    pp.draw_rect(fitz.Rect(c.x - 10, c.y - 7, c.x + 10, c.y + 7), color=col,
                 width=1.5)
out = os.path.join(ROOT, ".work", "diag",
                   f"{num}_{re.sub(r'[^0-9A-Za-z]+', '_', want)}.png")
os.makedirs(os.path.dirname(out), exist_ok=True)
pp.get_pixmap().save(out)
print("picture:", out)
