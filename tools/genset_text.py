"""Print what text extraction sees on each Generate Set sample page."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import fitz  # noqa: E402

p = sys.argv[1].strip('"') if len(sys.argv) > 1 else os.path.join(
    ROOT, ".run", "genset", "house_1600.pdf")
doc = fitz.open(p)
for i, pg in enumerate(doc):
    t = pg.get_text()
    print(f"--- page {i+1} fonts {[f[3] for f in pg.get_fonts()]}  "
          f"chars {len(t)}")
    print(repr(t[:400]))
from app import annotate  # noqa: E402
print("viewports", {k: [v['name'] for v in vs]
                    for k, vs in annotate.read_viewports(doc).items()})
