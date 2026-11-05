"""Trial of Compare Revisions on a real set: makes a fake 'revision' of
trial/ShelterCove_A-sheets.pdf (one sheet re-plotted 12 pt right / 7 pt
up, sheets reversed, a wall erased and a new one drawn) and compares."""
import os, sys, time
R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, R)
import fitz
from app import overlay
src = os.path.join(R, "trial", "ShelterCove_A-sheets.pdf")
outdir = os.path.join(R, "trial_output", "overlay")
os.makedirs(outdir, exist_ok=True)
old = fitz.open(src)
print("pages", old.page_count, [overlay.sheet_number(p) for p in old])
rev = fitz.open()
order = list(range(old.page_count))[::-1]
for k, i in enumerate(order):
    p = old[i]
    q = rev.new_page(width=p.rect.width, height=p.rect.height)
    shift = (12, -7) if k == 0 else (0, 0)
    r = p.rect + (shift[0], shift[1], shift[0], shift[1])
    q.show_pdf_page(r, old, i)
    if k == 0:
        w, h = p.rect.width, p.rect.height
        # erase a block and draw new walls
        box = fitz.Rect(w * 0.30, h * 0.35, w * 0.42, h * 0.50) + (12, -7, 12, -7)
        q.draw_rect(box, color=None, fill=(1, 1, 1))
        q.draw_rect(fitz.Rect(w * 0.55, h * 0.20, w * 0.65, h * 0.28) + (12, -7, 12, -7), width=2)
        q.insert_text((w * 0.55 + 12, h * 0.19 - 7), "NEW STORAGE 104A", fontsize=10)
revpath = os.path.join(outdir, "ShelterCove_A-sheets REV1.pdf")
rev.save(revpath)
t = time.time()
res = overlay.compare(old, fitz.open(revpath))
print(f"compared in {time.time() - t:.1f}s")
for r in res:
    print(r["sheet"], r["old"], r["new"], tuple(round(float(x), 3) for x in r["align"]), len(r["changes"]), r["changed_pct"])
    for c in r["changes"][:6]:
        print("    ", [round(v) for v in c])
doc = overlay.overlay_document(old, fitz.open(revpath), res, "Original", "REV1")
op = os.path.join(outdir, "overlay.pdf")
doc.save(op, garbage=1, deflate=True)
print("overlay", op, os.path.getsize(op))
# a picture of the changed sheet
k = next(n for n, r in enumerate(res) if r["changes"])
pix = doc[k].get_pixmap(dpi=40)
pix.save(os.path.join(outdir, "overlay_changed_sheet.png"))
c = res[k]["changes"][0]
clip = fitz.Rect(c.x0 - 60, c.y0 - 60, c.x1 + 60, c.y1 + 60)
doc[k].get_pixmap(dpi=110, clip=clip).save(os.path.join(outdir, "overlay_zoom.png"))
print("done")
