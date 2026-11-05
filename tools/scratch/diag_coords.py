import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import fitz
d = fitz.open(); pg = d.new_page(width=600, height=400)
pg.insert_text((100, 200), "HELLO", fontsize=20)
pg.draw_rect(fitz.Rect(300, 50, 320, 70), color=(0, 0, 0), fill=(0, 0, 0))
for rot in (0, 90):
    pg = d[0]; pg.set_rotation(rot)
    print("rot", rot, "rect", pg.rect, "mediabox", pg.mediabox)
    print(" words", [w[:5] for w in pg.get_text("words")])
    print(" dict span", [s["bbox"] for b in pg.get_text("dict")["blocks"] for l in b.get("lines", []) for s in l["spans"]])
    print(" search", pg.search_for("HELLO"))
    print(" drawings", [dr["rect"] for dr in pg.get_drawings()])
    pix = pg.get_pixmap(colorspace=fitz.csGRAY)
    import numpy as np
    a = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.stride)[:, :pix.width]
    ys, xs = np.nonzero(a < 128)
    print(" pix size", pix.width, pix.height, "ink bbox", xs.min(), ys.min(), xs.max(), ys.max())
    print(" rotation_matrix", pg.rotation_matrix)
