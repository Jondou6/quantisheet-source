import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import fitz
from app import autowalls as aw
PPU = 18.0
src = fitz.open(); p = src.new_page(width=792, height=612)
ox = oy = 60
t8, t5 = 8 / 12, 5 / 12
def wall(x0, y0, x1, y1):
    p.draw_rect(fitz.Rect(ox + x0 * PPU, oy + y0 * PPU, ox + x1 * PPU, oy + y1 * PPU), color=None, fill=(0, 0, 0))
wall(0, 0, 20, t8); wall(0, 12 - t8, 20, 12); wall(0, 0, t8, 12); wall(20 - t8, 0, 20, 12); wall(10, t8, 10 + t5, 12 - t8)
pix = p.get_pixmap(dpi=150)
scan = fitz.open(); sp = scan.new_page(width=792, height=612)
sp.insert_image(sp.rect, stream=pix.tobytes("png"))
segs = aw.raster_segments(sp, PPU, "ft")
print(len(segs))
for s in segs:
    print([round((c - 60) / PPU, 2) for c in s])
ws = aw.walls(sp, PPU, "ft", segs=segs)
for w in ws:
    print(aw.wall_type(w["thickness"]), round(w["measured"], 2), round(w["length"], 2), [round((c - 60) / PPU, 2) for c in w["p0"] + w["p1"]])
