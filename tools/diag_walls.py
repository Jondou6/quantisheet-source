"""Diagnostic: the scanned-plan wall test, printing each wall's numbers."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import fitz  # noqa: E402
from app import autowalls  # noqa: E402
PPU = float(sys.argv[1]) if len(sys.argv) > 1 else 18.0
src = fitz.open()
p = src.new_page(width=792, height=612)
ox, oy = 60, 60
t8, t5 = 8 / 12, 5 / 12


def wall(x0, y0, x1, y1):
    p.draw_rect(fitz.Rect(ox + x0 * PPU, oy + y0 * PPU, ox + x1 * PPU,
                          oy + y1 * PPU), color=None, fill=(0, 0, 0))


wall(0, 0, 20, t8)
wall(0, 12 - t8, 20, 12)
wall(0, 0, t8, 12)
wall(20 - t8, 0, 20, 12)
wall(10, t8, 10 + t5, 12 - t8)
pix = p.get_pixmap(dpi=150)
scan = fitz.open()
sp = scan.new_page(width=792, height=612)
sp.insert_image(sp.rect, stream=pix.tobytes("png"))
segs = autowalls.raster_segments(sp, PPU, "ft")
print("segs type", type(segs).__name__, "resolution attr",
      {k: getattr(segs, k) for k in dir(segs) if "res" in k.lower() or "pix" in k.lower()})
info = {}
ws = autowalls.walls(sp, PPU, "ft", segs=segs, info=info)
for w in ws:
    print({k: (round(v, 2) if isinstance(v, float) else v) for k, v in w.items()
           if k not in ("p0", "p1")})
print("classes", info.get("classes"))
print(autowalls.summary(ws, []))
