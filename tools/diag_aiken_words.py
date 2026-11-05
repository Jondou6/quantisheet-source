"""Diagnostic (read-only): counts of short words on Aiken sheets, and the
words just left of a legend line (work copy).
    python tools/diag_aiken_words.py E-1 "S|S3|S4|SD|SM" [legend text]"""
import collections
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import app  # noqa: E402,F401
import fitz  # noqa: E402
import aiken_eval  # noqa: E402
from app import aitakeoff as ait  # noqa: E402

pre = sys.argv[1].upper()
rx = re.compile("^(?:" + sys.argv[2] + ")$")
leg = sys.argv[3].upper() if len(sys.argv) > 3 else None
doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))
rows = ait.plan_set(doc, None)
for r in rows:
    num = (r.get("number") or "").upper()
    if not num.startswith(pre) or r.get("kind") == "superseded":
        continue
    page = doc[r["page"]]
    ws = page.get_text("words")
    c = collections.Counter(w[4] for w in ws if rx.match(w[4]))
    print(num, r.get("title"), r.get("kind"), dict(c))
    if leg:
        for w in ws:
            if leg.split()[0] == w[4].upper():
                near = [x[4] for x in ws if abs(x[1] - w[1]) < 6 and
                        w[0] - 60 < x[0] < w[0]]
                print("   legend line at", [round(v) for v in w[:4]],
                      "left of it:", near)
