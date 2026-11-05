"""Time the snap index on the heavy plant-set sheets: reading the
drawing's lines vs building the lookup grid.

    python tools/snap_probe.py
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import app  # noqa: E402,F401
import fitz  # noqa: E402
from app import snap  # noqa: E402

SRC = os.path.join(os.path.expanduser("~"), "OneDrive", "Desktop",
                   "32410-004-IFC-Plant Drawings.pdf")
doc = fitz.open(SRC)
for p in [33, 34, 35, 40, 212, 213, 214, 215, 1, 100]:
    pg = doc[p]
    t = time.perf_counter()
    segs = snap.page_segments(pg)
    t1 = time.perf_counter()
    idx = snap.SnapIndex(segs, clip=snap.page_clip(pg))
    t2 = time.perf_counter()
    marks = snap.markup_points(pg)
    t3 = time.perf_counter()
    print(f"p{p+1:<4} segments {len(segs):>7}  read {1000*(t1-t):6.0f} ms  "
          f"index {1000*(t2-t1):6.0f} ms  markups {1000*(t3-t2):4.0f} ms",
          flush=True)
