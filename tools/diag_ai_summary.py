"""Ask the local AI (Ollama on this PC) for Project Analysis's scope
summary of a spec book and print it (read-only):
python tools/diag_ai_summary.py <glob>"""
import glob
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def main(a):
    import fitz
    from app import projanalysis as pa
    sys.stdout.reconfigure(errors="replace")
    path = sorted(glob.glob(os.path.join(ROOT, a[0])))[0]
    doc = fitz.open(path)
    rows = pa.run(doc)
    src = pa.ai_source(doc, rows)
    print(f"source: {len(src)} chars from pages",
          sorted({int(x.split(']')[0]) for x in src.split('[page ')[1:]}))
    t = time.time()
    try:
        out = pa.ai_summary(doc, rows)
    except Exception as e:                               # noqa: BLE001
        print("AI error:", e)
        return
    print(f"AI summary in {time.time() - t:.0f}s:\n{out}")


if __name__ == "__main__":
    main(sys.argv[1:])
