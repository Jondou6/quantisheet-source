"""Live check of the free aerial sources from this PC: Census geocoder and
USGS NAIP Plus. Saves .run/aerial_live.pdf.

    python tools/aerial_live.py ["address or lat, lon"] [width_ft]
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app import aerial, annotate                              # noqa: E402


def main(argv):
    where = argv[0].strip('"') if argv else "1000 Main St, Conway, SC"
    if where.lower().endswith(".pdf"):
        import fitz
        site = aerial.find_site(fitz.open(where))
        print(f"from the plans: {site}")
        if not site:
            return 1
        where = site["query"]
    width = float(argv[1]) if len(argv) > 1 else 1000
    t = time.time()
    lat, lon, m = aerial.geocode(where)
    print(f"geocode: {lat:.6f}, {lon:.6f}  {m}  ({time.time() - t:.1f}s)")
    t = time.time()
    doc = aerial.aerial_document(aerial.NAIPSource(width_ft=width), lat, lon)
    sc = annotate.read_scales(doc)[0]
    print(f"photo: page {doc[0].rect.width:.0f} x {doc[0].rect.height:.0f} "
          f"pt, spans {doc[0].rect.width / sc['ppu']:.0f} ft "
          f"({time.time() - t:.1f}s)")
    out = os.path.join(ROOT, ".run", "aerial_live.pdf")
    doc.save(out)
    pix = doc[0].get_pixmap(dpi=30)
    print("photo mean brightness", sum(pix.samples[::97]) / len(
        pix.samples[::97]))
    print("saved", out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
