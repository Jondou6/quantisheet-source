"""Show the close-up scale reading on one sheet (read-only, in memory):
python tools/diag_zoom_scale.py <glob> <page>"""
import glob
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def main(a):
    import fitz
    from app import acrobat, aitakeoff as ait, autoscale as asc
    doc = fitz.open(sorted(glob.glob(os.path.join(ROOT, a[0])))[0])
    p = int(a[1]) - 1
    if p in ait.ocr_needed(doc):
        acrobat.make_searchable(doc, [p], vertical=True)
    page = doc[p]
    print("rotation", page.rotation, "rect", page.rect)
    for w in page.get_text("words"):
        if str(w[4]).upper().startswith(("SCALE", "GRAPHIC")):
            print("word", [round(x) for x in w[:4]], w[4])

    real = asc._ocr_clip_text

    def ocr(pg, clip, dpi=asc.ZOOM_DPI, psm=11):
        t = real(pg, clip, dpi, psm)
        print("DPI", dpi, "psm", psm)
        print("CLIP", [round(x) for x in clip],
              "shown", [round(x) for x in (fitz.Rect(clip) *
                                           pg.rotation_matrix)])
        print("  TEXT:", t.replace("\n", " | ")[:300])
        return t
    asc._ocr_clip_text = ocr                 # the real order of tries
    print("RESULT", asc.zoom_scale(page))


if __name__ == "__main__":
    main(sys.argv[1:])
