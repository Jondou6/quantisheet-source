"""Render the area around a word on a page to .run/crop_<page>.png.

    python tools/crop.py FILE.pdf PAGE WORD [HALF_WIDTH_PTS] [ZOOM]
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import fitz                                                   # noqa: E402


def main(argv):
    doc = fitz.open(argv[0].strip('"'))
    pno = int(argv[1]) - 1
    page = doc[pno]
    word = argv[2].strip('"')
    half = float(argv[3]) if len(argv) > 3 else 200
    zoom = float(argv[4]) if len(argv) > 4 else 3
    hits = page.search_for(word)
    if not hits:
        print("word not found")
        return
    r0 = hits[0]
    print("rotation", page.rotation, "hit", r0, "page.rect", page.rect)
    for tag, r in (("a", r0), ("b", r0 * page.rotation_matrix),
                   ("c", r0 * page.derotation_matrix)):
        c = fitz.Point((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2)
        clip = fitz.Rect(c.x - half, c.y - half, c.x + half, c.y + half) & \
            page.rect
        if clip.is_empty:
            print(tag, "empty")
            continue
        out = os.path.join(ROOT, ".run", f"crop_{pno + 1}{tag}.png")
        page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=clip).save(out)
        print(out, clip)


if __name__ == "__main__":
    main(sys.argv[1:])
