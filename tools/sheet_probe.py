"""How many sheets get a sheet number, per PDF.

    python tools/sheet_probe.py [FOLDER or FILE] [--show]

--show prints each page's number and the words in its title block corner
for the pages that got none."""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import fitz  # noqa: E402

from app import sheets  # noqa: E402

args = [a.strip('"') for a in sys.argv[1:]]
show = "--show" in args
args = [a for a in args if a != "--show"]
target = args[0] if args else os.path.dirname(ROOT)
files = []
if os.path.isfile(target):
    files = [target]
else:
    for d, dirs, fs in os.walk(target):
        dirs[:] = [x for x in dirs if x not in (".venv", "__pycache__",
                                                 ".git", "build", "dist",
                                                 "release")]
        files += [os.path.join(d, f) for f in fs if f.lower().endswith(".pdf")]
for f in sorted(files):
    try:
        doc = fitz.open(f)
    except Exception:                                     # noqa: BLE001
        continue
    if not 3 <= doc.page_count <= 400:
        continue
    t = time.time()
    rows = sheets.scan(doc, keep_words=show)
    got = sum(1 for r in rows if r["number"])
    print(f"{got:4d}/{doc.page_count:<4d} {time.time() - t:5.1f}s  "
          f"{os.path.relpath(f, target)}", flush=True)
    if show:
        for r in rows:
            if not r["number"]:
                W = doc[r["page"]].rect.width
                H = doc[r["page"]].rect.height
                corner = [w[4] for w in r.get("words", [])
                          if w[0] > W * 0.7 and w[1] > H * 0.75][:40]
                print(f"   p{r['page'] + 1}: none  corner: {' '.join(corner)}")
    doc.close()
