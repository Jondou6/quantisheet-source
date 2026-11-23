"""Run Project Analysis on a spec book and print the answers (read-only):
python tools/diag_project_analysis.py <glob>"""
import glob
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def main(a):
    import fitz
    from app import projanalysis as pa
    path = sorted(glob.glob(os.path.join(ROOT, a[0])))[0]
    doc = fitz.open(path)
    t = time.time()
    rows = pa.run(doc)
    print(f"{doc.page_count} pages in {time.time() - t:.1f}s")
    for r in rows:
        where = "" if r["page"] is None else f"p{r['page'] + 1} {r['section']}"
        print(f"{r['label'][:34]:34} | {str(r['value'])[:90]} | {where[:40]}")
        for v, p in r.get("also") or []:
            print(f"{'':34}   also: {str(v)[:80]} p{(p or 0) + 1}")


if __name__ == "__main__":
    main(sys.argv[1:])
