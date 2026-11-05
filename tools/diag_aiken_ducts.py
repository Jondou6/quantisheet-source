"""Diagnostic (read-only): Trade Takeoff ducts on an Aiken M sheet (work
copy), each group's tag size and its pieces' measured widths, and what
the AI duct check keeps.  python tools/diag_aiken_ducts.py M-101
Saves a picture with kept pieces (blue), review pieces (red) and size
tags (green boxes) to .work\\diag\\."""
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

num = (sys.argv[1] if len(sys.argv) > 1 else "M-101").upper()
doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))
rows = ait.plan_set(doc, None)
r = next(r for r in rows if (r.get("number") or "").upper() == num)
pno, (_l, ppu, unit) = r["page"], r["scale"]
page = doc[pno]
print(num, "page", pno + 1, r.get("title"), "scale", r["scale"])
tags = [l for l in tt.labels(page) if l["kind"] in ("duct", "round")]
print(len(tags), "size tags:", sorted({t["name"] for t in tags}))
inf = {}
bt, un = tt.ducts_by_tag(page, ppu, unit, info=inf)
print("by-tag styles (tagged pieces):", inf.get("styles"))
for g in bt:
    print(f"  BY TAG {g['name']:<12} {g['length']:7.1f} LF in "
          f"{len(g['pieces'])} pieces")
for u in un:
    print(f"  UNASSIGNED {u['name']:<16} {u['length']:7.1f} LF")
groups = bt
kept, review, dropped = ait.duct_groups(page, ppu, unit)
keep_ids = {id(pc) for g in kept for pc in g["pieces"]}
print("kept:", [(g["name"], round(g["length"], 1)) for g in kept])
print("review:", [(n, round(L, 1), w) for n, L, w in review])
print("dropped fragments:", dropped)
for g in groups:
    print(f"-- {g['name']}  tag w={g['w']} h={g['h']} tagged={g['tagged']} "
          f"total {g['length']:.1f} LF")
    for pc in sorted(g["pieces"], key=lambda p: -p["length"])[:12]:
        print(f"     {pc['length']:6.1f} LF  width {pc['width']:5.1f} in  "
              f"at ({pc['mid'][0]:.0f},{pc['mid'][1]:.0f})")
z = 0.35
pix = page.get_pixmap(matrix=fitz.Matrix(z, z))
pic = fitz.open()
pp = pic.new_page(width=pix.width, height=pix.height)
pp.insert_image(pp.rect, pixmap=pix)
for g in groups:
    for pc in g["pieces"]:
        a, b = pc["p0"], pc["p1"]
        col = (0, 0, 1) if any(pc["p0"] == q["p0"] for k in kept
                               for q in k["pieces"]) else (1, 0, 0)
        a, b = fitz.Point(a) * page.rotation_matrix, fitz.Point(b) * page.rotation_matrix
        pp.draw_line((a[0] * z, a[1] * z), (b[0] * z, b[1] * z), color=col,
                     width=2)
for t in tags:
    c = t["center"]
    c = fitz.Point(c) * page.rotation_matrix
    pp.draw_rect(fitz.Rect(c[0] * z - 4, c[1] * z - 3, c[0] * z + 4,
                           c[1] * z + 3), color=(0, 0.7, 0), width=1)
out = os.path.join(ROOT, ".work", "diag", f"{num}_ducts.png")
os.makedirs(os.path.dirname(out), exist_ok=True)
pp.get_pixmap(dpi=144).save(out)
print("picture:", out)
want = sys.argv[2] if len(sys.argv) > 2 else ""
if re.match(r"^\d+in$", want):
    want = want[:-2] + '" round'           # 8in -> 8" round
if want:
    for t in tags:
        if t["name"] == want:
            c = t["center"]
            near = [(g["name"], round(min(tt.dist_to_poly(c, [pc["p0"], pc["p1"]])
                                        for pc in g["pieces"]))) for g in groups if g["pieces"]]
            near.sort(key=lambda x: x[1])
            print("tag", want, [round(v) for v in c], "nearest groups:", near[:3])
