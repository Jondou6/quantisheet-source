"""What a sheet says about its scale, read-only: every line with SCALE,
NTS or a graphic scale on the sheets Auto Scale found nothing for.
python tools/diag_scale_words.py <glob> [page numbers, comma separated]"""
import glob
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
PAT = re.compile(r"SCALE|N\.?T\.?S|HORIZ|VERT|=", re.I)


def main(a):
    import fitz
    from app import acrobat, aitakeoff as ait, autoscale
    doc = fitz.open(sorted(glob.glob(os.path.join(ROOT, a[0])))[0])
    need = ait.ocr_needed(doc)
    if need:
        acrobat.make_searchable(doc, sorted(need), vertical=True)
    if len(a) > 1:
        pages = [int(x) - 1 for x in a[1].split(",")]
    else:
        pages = [r["page"] for r in autoscale.detect(doc, use_ocr=False)
                 if r["status"] == "none"]
    for p in pages:
        page = doc[p]
        words = page.get_text("words")
        lines = {}
        for w in words:
            lines.setdefault((w[5], w[6]), []).append(w)
        print(f"== sheet {p + 1} ({page.rect.width / 72:.0f}x"
              f"{page.rect.height / 72:.0f} in)")
        n = 0
        for ws in lines.values():
            t = " ".join(w[4] for w in ws)
            if PAT.search(t) and len(t) < 90:
                print(f"   [{ws[0][0]:6.0f},{ws[0][1]:6.0f}] {t}")
                n += 1
                if n > 25:
                    break


if __name__ == "__main__":
    main(sys.argv[1:])
