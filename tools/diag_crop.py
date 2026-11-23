"""Render part of a page to a PNG in .run (read-only):
python tools/diag_crop.py <glob> <page> <x0> <y0> <x1> <y1> [dpi] [name]
Coordinates are PDF points."""
import glob
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def main(a):
    import fitz
    doc = fitz.open(sorted(glob.glob(os.path.join(ROOT, a[0])))[0])
    pg = doc[int(a[1]) - 1]
    r = fitz.Rect(*[float(x) for x in a[2:6]]) & pg.rect
    dpi = int(a[6]) if len(a) > 6 else 150
    name = a[7] if len(a) > 7 else "crop"
    out = os.path.join(ROOT, ".run", f"{name}.png")
    pg.get_pixmap(clip=r, dpi=dpi).save(out)
    print(out, pg.rect, r)


if __name__ == "__main__":
    main(sys.argv[1:])
