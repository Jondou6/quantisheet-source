"""Live check of the aerial site layers: fetch the NAIP photo and each
layer for one site and save them, plus a finished page.

    python tools/site_layers_probe.py "LAT, LON" [WIDTH_FT]"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from app import aerial  # noqa: E402

lat, lon = (float(v) for v in sys.argv[1].strip('"').split(","))
width = float(sys.argv[2]) if len(sys.argv) > 2 else 1500.0
out = os.path.join(ROOT, ".run", "site_layers")
os.makedirs(out, exist_ok=True)
t = time.time()
photo, mpp = aerial.NAIPSource(width_ft=width).fetch(lat, lon, 0, 0, 0)
print(f"photo {len(photo) // 1024} KB in {time.time() - t:.1f}s")
import fitz  # noqa: E402
pix = fitz.Pixmap(photo)
w, h = pix.width, pix.height
fpp = mpp / 0.3048
for key in aerial.SITE_LAYERS:
    t = time.time()
    data = aerial.site_layer(key, lat, lon, w * fpp, h * fpp, w, h)
    print(f"{key:9s} {'OK ' + str(len(data) // 1024) + ' KB' if data else 'none'}"
          f"  {time.time() - t:.1f}s", flush=True)
    if data:
        open(os.path.join(out, key + ".png"), "wb").write(data)
layers = aerial.site_layers(list(aerial.SITE_LAYERS), lat, lon, w * fpp,
                            h * fpp, w, h)
doc = aerial.aerial_document_from(photo, mpp, lat, lon, "USGS NAIP Plus",
                                  "", layers=layers)
doc.save(os.path.join(out, "site_page.pdf"))
doc[0].get_pixmap(dpi=40).save(os.path.join(out, "site_page.png"))
print("saved", out)
