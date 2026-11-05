import collections, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import fitz, ezdxf
from app import dxf
src = os.path.join(ROOT, ".run", "dxf_trial", "src", "gdsestimating__api-cw750-details.dxf")
doc = ezdxf.readfile(src)
info = dxf._gather(doc, doc.modelspace())
per = collections.defaultdict(lambda: [1e18, 1e18, -1e18, -1e18, 0])
for l, pts, *_ in info["lines"]:
    b = per[l]
    for x, y in pts:
        b[0] = min(b[0], x); b[1] = min(b[1], y); b[2] = max(b[2], x); b[3] = max(b[3], y)
    b[4] += 1
for l, v in sorted(per.items()):
    print("layer", l, [round(x, 1) for x in v[:4]], v[4], "on" if dxf._layer_on(doc, l) else "off")
print("text", len(info["text"]), "fills", len(info["fills"]), "tol", info["tol"])
for name in doc.layouts.names_in_taborder():
    if name == "Model":
        continue
    lay = doc.layouts.get(name)
    for e in lay.query("VIEWPORT"):
        x = e.dxf
        print(name, "vp id", x.get("id"), "status", x.get("status"), "c", x.center, "wh", x.width, x.height,
              "vc", x.get("view_center_point"), "vh", x.get("view_height"), "tgt", x.get("view_target_point"),
              "twist", x.get("view_twist_angle"), "dir", x.get("view_direction_vector"))
d = fitz.open(os.path.join(ROOT, ".run", "dxf_trial", "gdsestimating__api-cw750-details.pdf"))
pg = d[0]
dr = pg.get_drawings()
print("drawings", len(dr), "page", pg.rect)
bb = fitz.Rect()
for x in dr:
    bb |= x["rect"]
print("drawing bbox", bb)
print("ocgs", d.get_ocgs())
