"""OCR the given sheets in memory and print the text lines the civil
engine sees that look like scales, pipe or structure callouts (read-only):
python tools/diag_ocr_lines.py <glob> 6 11"""
import glob
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

_ARG = sys.argv[sys.argv.index("--pat") + 1] if "--pat" in sys.argv else None
PAT = re.compile(_ARG or
                 r"SCALE|LF|PVC|DIP|FM|FORCE|MAIN|MANHOLE|MH|STA|\d+\+\d\d|"
                 r"\d+'", re.I)


def main(a):
    import fitz
    from app import acrobat, civiltakeoff as ct
    doc = fitz.open(sorted(glob.glob(os.path.join(ROOT, a[0])))[0])
    pages = [int(x) - 1 for x in a[1:] if x.isdigit()]
    if "--tags-off" in a:
        globals()["_NO_TAGS"] = True
    acrobat.make_searchable(doc, pages)
    for p in pages:
        items = ct.lines_sized(doc[p])
        print(f"== p{p + 1}: {len(items)} lines")
        lab, every = ct.stations(doc[p], items)
        print("  STA labelled:", sorted(lab))
        print("  all stations:", sorted(every))
        for t in ct.structure_tags(doc[p]):
            print("  TAG", t["id"], t["kind"], t.get("station"),
                  [round(v) for v in t["rect"]], t["text"][:50])
        if "--sta" in sys.argv:
            continue
        for t, r, size, dr in items:
            if PAT.search(t):
                print(f"  ({r.x0:6.0f},{r.y0:6.0f}) s{size:4.1f} "
                      f"d{dr[0]:+.0f},{dr[1]:+.0f} {t[:70]}")


if __name__ == "__main__":
    main(sys.argv[1:])
