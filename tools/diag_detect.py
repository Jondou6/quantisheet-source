"""Auto Scale as the program runs it (OCR on) for every sheet of a set,
read-only: python tools/diag_detect.py <glob>"""
import glob
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def main(a):
    import fitz
    from app import autoscale, aitakeoff as ait
    doc = fitz.open(sorted(glob.glob(os.path.join(ROOT, a[0])))[0])
    need = ait.ocr_needed(doc)
    if need:
        from app import acrobat
        acrobat.make_searchable(doc, sorted(need), vertical=True)
    sheets = {r["page"]: r for r in ait.plan_set(doc, None)}
    t0 = time.time()
    rows = autoscale.detect(doc, use_ocr=True)
    print(f"{len(rows)} pages in {time.time() - t0:.0f}s")
    for r in rows:
        s = sheets.get(r["page"], {})
        print(f"{r['page'] + 1:3d} {s.get('number') or '?':8s} "
              f"{r['status']:5s} label={r.get('label')!s:14.14s} "
              f"src={r.get('source') or '-':8s} {r.get('note', '')[:60]}")


if __name__ == "__main__":
    main(sys.argv[1:])
