"""Print the sentences on one spec page that match a pattern (read-only):
python tools/diag_spec_page.py <glob> <page> <pattern>"""
import glob
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def main(a):
    import fitz
    from app import bidterms
    doc = fitz.open(sorted(glob.glob(os.path.join(ROOT, a[0])))[0])
    t = bidterms._page_text(doc[int(a[1]) - 1])
    rx = re.compile(a[2], re.I)
    for s in re.split(r"(?<=[.;])\s+", t):
        if rx.search(s):
            print("-", s[:600])


if __name__ == "__main__":
    main(sys.argv[1:])
