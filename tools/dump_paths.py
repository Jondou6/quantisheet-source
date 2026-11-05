"""Dump the vector strokes around a word on a page (for door / wall
detection work).

    python tools/dump_paths.py FILE.pdf PAGE WORD [FEET_AROUND] [PTS_PER_FT]
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import fitz                                                   # noqa: E402

from app import autotakeoff                                   # noqa: E402


def main(argv):
    doc = fitz.open(argv[0].strip('"'))
    page = doc[int(argv[1]) - 1]
    word = argv[2].strip("\"")
    ft = float(argv[3]) if len(argv) > 3 else 8
    ppf = float(argv[4]) if len(argv) > 4 else 18.0
    print("rotation", page.rotation, "rect", page.rect)
    hits = page.search_for(word)
    if not hits:
        print("word not found")
        return
    r = hits[0]
    if page.rotation:
        r = r * page.derotation_matrix
    c = fitz.Point((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2)
    box = fitz.Rect(c.x - ft * ppf, c.y - ft * ppf, c.x + ft * ppf,
                    c.y + ft * ppf)
    print("word at", c, "box", box)
    for pi, p in enumerate(page.get_drawings()):
        items = [it for it in p.get("items", ())
                 if any(box.contains(q) for q in it[1:]
                        if isinstance(q, fitz.Point))]
        if not items:
            continue
        print(f"path {pi} w={p.get('width')} color={p.get('color')} "
              f"dashes={p.get('dashes')} n={len(p['items'])}")
        for it in items[:40]:
            pts = " ".join(f"({q.x - c.x:6.1f},{q.y - c.y:6.1f})"
                           for q in it[1:] if isinstance(q, fitz.Point))
            L = abs(it[2] - it[1]) / ppf if it[0] == "l" else 0
            print(f"   {it[0]} {pts}  {L:.2f}ft")
    print("bifolds:", [(a - c, b - c) for a, b in
                       autotakeoff.bifolds(page, ppf)
                       if box.contains(a) or box.contains(b)])


if __name__ == "__main__":
    main(sys.argv[1:])
