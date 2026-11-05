import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import fitz
from app import civiltakeoff as ct
d = fitz.open()
pg = d.new_page(width=800, height=600)
sh = pg.new_shape()
sh.draw_line((50, 300), (750, 300)); sh.finish(width=1.0, color=(0, 0, 0))
sh.draw_line((209, 104), (260, 104)); sh.draw_line((260, 104), (300, 298))
sh.finish(width=0.25, color=(0, 0, 0)); sh.commit()
pg.insert_text((100, 108), '337 LF-6" SDR-26 PVC', fontsize=10)
labs = ct.pipe_labels(pg)
print([(l["rect"], l["size_pt"], l["center"]) for l in labs])
for p in pg.get_drawings():
    print(p.get("width"), [it[0] for it in p["items"]], p["items"][:3])
ct._leaders(pg, labs)
print(labs[0].get("leader"), labs[0]["center"])
