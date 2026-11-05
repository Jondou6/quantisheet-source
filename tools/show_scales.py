"""Print the scales saved in a PDF and each sheet's printed scale.

    python tools/show_scales.py FILE.pdf [PAGES 1-based, comma list]
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import fitz                                                   # noqa: E402

from app import annotate, sheets                              # noqa: E402

doc = fitz.open(sys.argv[1].strip('"'))
pages = [int(p) - 1 for p in sys.argv[2].split(",")] if len(sys.argv) > 2 \
    else range(doc.page_count)
saved = annotate.read_scales(doc)
for r in sheets.scan(doc, list(pages), numbers=False):
    s = saved.get(r["page"])
    print(f"p{r['page'] + 1:>3} {r['label'][:44]:44} printed "
          f"{r['scale'][0] if r['scale'] else '-':16} saved "
          f"{(str(round(s['ppu'], 3)) + ' pt/' + s['unit']) if s else '-'}")
n = {}
for it in annotate.takeoff_items(doc):
    n[(it["page"], it["type"])] = n.get((it["page"], it["type"]), 0) + 1
print("measurements:", {f"p{p + 1} {t}": c for (p, t), c in sorted(n.items())})
