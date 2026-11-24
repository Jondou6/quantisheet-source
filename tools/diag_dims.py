"""Dimension strings Auto Scale reads on one sheet and the line each one
measured (read-only, prints numbers only):
python tools/diag_dims.py <glob> <page>"""
import glob
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def main(a):
    import fitz
    from app import autoscale as asc, takeoff
    doc = fitz.open(sorted(glob.glob(os.path.join(ROOT, a[0])))[0])
    page = doc[int(a[1]) - 1]
    words = page.get_text("words")
    dims = asc._dimension_words(words)
    print("page", a[1], "rotation", page.rotation, "dims", len(dims))
    r = asc.dimension_scale(page, words)
    print("result", r["ppu"], "n", r["n"])
    vals = sorted(r["values"])
    print("values", [round(v, 1) for v in vals])
    for w in words:
        got = takeoff.parse_length(w[4])
        if got and got[1] == "ft" and got[0] >= asc.MIN_DIM_FT and \
                "'" in w[4].translate(takeoff._QUOTES):
            print(" dim", repr(w[4]), [round(x) for x in w[:4]])
    print("scales on sheet", takeoff.find_scales(page.get_text())[:8])


if __name__ == "__main__":
    main(sys.argv[1:])
