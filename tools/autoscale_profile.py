"""Where Auto Scale spends its time (cProfile, first N sheets).

    python tools/autoscale_profile.py [N]
"""
import cProfile
import os
import pstats
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import app  # noqa: E402,F401
import fitz  # noqa: E402
from app import autoscale  # noqa: E402

SRC = os.path.join(os.path.expanduser("~"), "OneDrive", "Desktop",
                   "32410-004-IFC-Plant Drawings.pdf")
n = int(sys.argv[1]) if len(sys.argv) > 1 else 60
doc = fitz.open(SRC)
pr = cProfile.Profile()
pr.enable()
autoscale.detect(doc, pages=range(n), use_ocr=False)
pr.disable()
st = pstats.Stats(pr)
st.sort_stats("cumulative").print_stats(28)
st.sort_stats("tottime").print_stats(15)
