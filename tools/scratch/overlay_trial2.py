"""Rotated-revision trial on the real A-301: the 'revision' is the sheet
turned 0.8 degrees and shifted (like a skewed scan / re-plot), with a new
room drawn. Checks automatic and manual (2-point) alignment."""
import math, os, sys, time
R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, R)
import fitz
from app import overlay
src = fitz.open(os.path.join(R, "trial", "ShelterCove_A-sheets.pdf"))
i = [overlay.sheet_number(p) for p in src].index("A-301")
old = fitz.open(); old.insert_pdf(src, from_page=i, to_page=i)
w, h = old[0].rect.width, old[0].rect.height
t = math.radians(0.8)
a, b = math.cos(t), math.sin(t)
cx, cy = w / 2, h / 2
truth = overlay.from_affine(a, b, cx - (a * cx - b * cy) + 9, cy - (b * cx + a * cy) - 5)
rev = fitz.open(); q = rev.new_page(width=w, height=h)
ops, name, x = overlay._place(q, old, 0, truth)
overlay._write(rev, q, [ops])
r = overlay.map_rect(fitz.Rect(w * 0.55, h * 0.20, w * 0.65, h * 0.28), truth)
q.draw_rect(r, width=2)
outdir = os.path.join(R, "trial_output", "overlay"); os.makedirs(outdir, exist_ok=True)
rp = os.path.join(outdir, "A-301 rotated REV.pdf"); rev.save(rp)
rev = fitz.open(rp)
print("truth", [round(v, 4) for v in truth])
t0 = time.time(); m = overlay.align(old[0], rev[0]); print("auto", [round(float(v), 4) for v in m], f"{time.time()-t0:.1f}s")
ch, pct = overlay.changes(old[0], rev[0], m); print("auto changes", len(ch), pct)
pts = [(w * 0.1, h * 0.1), (w * 0.9, h * 0.85)]
mm = overlay.align_points(pts, [overlay.map_point(p, truth) for p in pts], old[0], rev[0])
print("manual", [round(float(v), 4) for v in mm])
ch2, pct2 = overlay.changes(old[0], rev[0], mm); print("manual changes", len(ch2), pct2, [[round(v) for v in c] for c in ch2])
res = [{"old": 0, "new": 0, "sheet": "A-301", "align": mm, "changes": ch2, "changed_pct": pct2}]
doc = overlay.overlay_document(old, rev, res, "Original", "Rotated REV")
doc.save(os.path.join(outdir, "overlay_rotated.pdf"))
doc[0].get_pixmap(dpi=40).save(os.path.join(outdir, "overlay_rotated.png"))
print("done")
