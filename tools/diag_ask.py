"""Ask the Project on a PDF (read-only): python tools/diag_ask.py <glob>
"question" [--ai]"""
import glob
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def main(a):
    import fitz
    from app import askproject as ap
    doc = fitz.open(sorted(glob.glob(os.path.join(ROOT, a[0])))[0])
    chunks = ap.sources(doc, None, os.path.basename(doc.name))
    res = ap.answer(a[1], chunks, use_ai="--ai" in a)
    print("ANSWER:", res["answer"] or "(none)", res["error"])
    for i, h in enumerate(res["hits"], 1):
        print(f"[{i}] {h['where']} ({h['score']}): {h['text'][:220]}")


if __name__ == "__main__":
    main(sys.argv[1:])
