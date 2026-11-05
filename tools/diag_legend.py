"""Diagnostic (read-only, work copy): legend symbol counts on chosen pages
of an eval set, with the time taken (PM review NW-18 acceptance).
    python tools/diag_legend.py 68-71 --set colleton"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import app  # noqa: E402,F401
import fitz  # noqa: E402
import aiken_eval  # noqa: E402
from app import tradetakeoff as tt  # noqa: E402

a, b = (int(x) for x in sys.argv[1].split("-"))
pages = list(range(a - 1, b))
doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))
rep = {}
t = time.time()
got = tt.legend_counts(doc, pages, report=rep)
print(f"{len(got)} symbols in {time.time() - t:.1f}s on pages {a}-{b}")
for c in got:
    print(f"  {c['name'][:50]:50s} {len(c['hits'])}")
print("not counted:", rep.get("not_counted", [])[:10])
print("rejected legend lines:", len(rep.get("rejected", [])))
