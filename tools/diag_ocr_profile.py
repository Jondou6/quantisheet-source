"""Profile make_searchable on a few sheets of a set, read-only:
python tools/diag_ocr_profile.py <glob> [pages]"""
import cProfile
import glob
import os
import pstats
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def main(a):
    import fitz
    from app import acrobat, aitakeoff as ait
    doc = fitz.open(sorted(glob.glob(os.path.join(ROOT, a[0])))[0])
    need = sorted(ait.ocr_needed(doc))[:int(a[1]) if len(a) > 1 else 3]
    pr = cProfile.Profile()
    pr.enable()
    acrobat.make_searchable(doc, need)
    pr.disable()
    st = pstats.Stats(pr)
    st.sort_stats("cumulative").print_stats(28)


if __name__ == "__main__":
    main(sys.argv[1:])
