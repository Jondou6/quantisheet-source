"""What a civil set gives the program, sheet by sheet (read-only):
python tools/diag_civil_set.py <glob> [--png PAGE OUTDIR]
Rotation, how much real text, the scale words in the text, what Auto
Scale finds, vector drawing count, and whether it's a picture."""
import glob
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
_SC = re.compile(r"SCALE|1\s*\"|=\s*\d+\s*'|\d+\s*'\s*-|HORIZ|VERT|FEET",
                 re.I)


def main(a):
    import fitz
    from app import autoscale, aitakeoff as ait, sheets
    path = sorted(glob.glob(os.path.join(ROOT, a[0])))[0]
    doc = fitz.open(path)
    print(os.path.basename(path), doc.page_count, "pages")
    rows = autoscale.detect(doc, use_ocr=False)
    info = sheets.scan(doc, list(range(doc.page_count)), numbers=True)
    for pno, page in enumerate(doc):
        words = page.get_text("words")
        sc = [w[4] for w in words if _SC.search(w[4])][:12]
        try:
            nd = len(page.get_drawings())
        except Exception:                                 # noqa: BLE001
            nd = -1
        r = rows[pno]
        print(f"p{pno + 1:>2} {info[pno].get('number') or '?':8} "
              f"rot {page.rotation:3} words {len(words):5} draw {nd:6} "
              f"raster {ait.raster_only(page)} | {info[pno].get('title', '')[:34]:34} "
              f"| auto: {r['label'] or '-'} ({r['status']}) | scale words: "
              f"{' '.join(sc)[:90]}")
    if "--png" in a:
        i = a.index("--png")
        p, out = int(a[i + 1]) - 1, a[i + 2]
        os.makedirs(os.path.join(ROOT, out), exist_ok=True)
        f = os.path.join(ROOT, out, f"p{p + 1}.png")
        doc[p].get_pixmap(dpi=40).save(f)
        print("wrote", f)


if __name__ == "__main__":
    main(sys.argv[1:])
