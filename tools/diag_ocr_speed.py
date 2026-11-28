"""How long the whole-sheet OCR takes on a plan set, read-only (nothing
is saved): python tools/diag_ocr_speed.py <glob> [pages]

Prints the pages that need OCR, the tiles per page, how many tiles are
blank paper, the time per tile, and the total make_searchable time."""
import glob
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def main(a):
    import fitz
    from app import acrobat, aitakeoff as ait
    path = sorted(glob.glob(os.path.join(ROOT, a[0])))[0]
    doc = fitz.open(path)
    need = sorted(ait.ocr_needed(doc))
    if len(a) > 1:
        need = need[:int(a[1])]
    print("cpu cores:", os.cpu_count(), " pages needing OCR:", len(need),
          "of", doc.page_count)
    tiles = blank = 0
    real = acrobat._tess_tile
    stats = {"n": 0, "t": 0.0}

    def timed(exe, png, *k, **kw):
        t = time.time()
        try:
            return real(exe, png, *k, **kw)
        finally:
            stats["n"] += 1
            stats["t"] += time.time() - t
    acrobat._tess_tile = timed
    if hasattr(acrobat, "_blank_tile"):
        before = acrobat._blank_tile

        def count(pix):
            nonlocal tiles, blank
            tiles += 1
            b = before(pix)
            blank += bool(b)
            return b
        acrobat._blank_tile = count
    t0 = time.time()
    acrobat.make_searchable(doc, need, vertical=None)
    total = time.time() - t0
    print(f"make_searchable: {total:.1f}s for {len(need)} pages "
          f"({total / max(1, len(need)):.1f}s a page)")
    print(f"tesseract runs: {stats['n']}, {stats['t']:.1f}s of tesseract "
          f"time ({stats['t'] / max(1, stats['n']):.2f}s each)")
    if tiles:
        print(f"tiles drawn: {tiles}, blank and skipped: {blank}")
    t0 = time.time()
    from app import autoscale
    rows = autoscale.detect(doc, use_ocr=True)
    print(f"autoscale.detect after OCR: {time.time() - t0:.1f}s, "
          f"{sum(r['status'] == 'ok' for r in rows)} ok, "
          f"{sum(r['status'] == 'check' for r in rows)} check, "
          f"{sum(r['status'] == 'none' for r in rows)} none")


if __name__ == "__main__":
    main(sys.argv[1:])
