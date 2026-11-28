"""The words around each SCALE on some sheets, as Auto Scale's text has
them, read-only: python tools/diag_scale_ctx.py <glob> 13,15,30"""
import glob
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def main(a):
    import fitz
    from app import acrobat, aitakeoff as ait, autoscale
    doc = fitz.open(sorted(glob.glob(os.path.join(ROOT, a[0])))[0])
    pages = [int(x) - 1 for x in a[1].split(",")]
    need = [p for p in ait.ocr_needed(doc) if p in pages]
    if need:
        acrobat.make_searchable(doc, sorted(need), vertical=True)
    for p in pages:
        flat = " ".join(doc[p].get_text().split())
        print(f"== sheet {p + 1}: scale_none={autoscale.scale_none(flat)}")
        for m in re.finditer(r"SCALE", flat, re.I):
            print("   ", repr(flat[max(0, m.start() - 25):m.end() + 25]))


if __name__ == "__main__":
    main(sys.argv[1:])
