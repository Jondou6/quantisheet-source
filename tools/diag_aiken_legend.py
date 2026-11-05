"""Diagnostic (read-only): the wall-type legend and wall heights AI Takeoff
reads from the Aiken work copy.  python tools/diag_aiken_legend.py"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import app  # noqa: E402,F401
import fitz  # noqa: E402
import aiken_eval  # noqa: E402
from app import aitakeoff as ait  # noqa: E402

doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))
rows = ait.plan_set(doc, None)
legend, pages = ait.wall_legend(doc, rows)
print("legend pages:", [p + 1 for p in pages])
for code, d in sorted(legend.items()):
    print(f"  {code:<6} {d}")
text = "\n".join(doc[p].get_text() for p in pages)
print("heights:", ait.wall_heights(legend, text))
