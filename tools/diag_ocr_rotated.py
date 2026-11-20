"""OCR one sheet as it is shown (rotation kept) and list what it finds
that matters for takeoff - scales, stations, pipe callouts (read-only):
python tools/diag_ocr_rotated.py <glob> PAGE [--raw]"""
import glob
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
KEY = re.compile(r"SCALE|\d\"?\s*=|STA|\d\+\d\d|FM|FORCE|MAIN|PVC|DIP|HDPE|"
                 r"MH|MANHOLE|LF|\d+\"|INV|ARV|AIR", re.I)


def main(a):
    import fitz
    from app import acrobat, ocr
    path = sorted(glob.glob(os.path.join(ROOT, a[0])))[0]
    p = int(a[1]) - 1
    doc = fitz.open(path)
    page = doc[p]
    print("tesseract:", bool(ocr.find_tesseract()), "rotation",
          page.rotation, "rect", page.rect)
    have = {w[4] for w in page.get_text("words")}
    t = time.time()
    words = acrobat.ocr_page_words(page)      # as shown: rotation kept
    print(f"{len(words)} words in {time.time() - t:.1f}s; "
          f"{sum(1 for _r, w in words if w not in have)} not in the text")
    hits = [w for _r, w in words if KEY.search(w)]
    print("takeoff words:", " | ".join(hits[:150]))
    if "--raw" in a:
        print(" ".join(w for _r, w in words)[:4000])


if __name__ == "__main__":
    main(sys.argv[1:])
