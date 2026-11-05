"""Diagnostic (read-only): text lines on the Aiken work copy matching a
regular expression, with their sheet numbers.
    python tools/diag_aiken_text.py "PRIME|TACK|BINDER|AGGREGATE BASE" [C-]"""
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

rx = re.compile(sys.argv[1], re.I)
prefix = sys.argv[2].upper() if len(sys.argv) > 2 else ""
doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))
rows = ait.plan_set(doc, None)
for r in rows:
    num = (r.get("number") or f"p{r['page'] + 1}").upper()
    if prefix and not num.startswith(prefix):
        continue
    page = doc[r["page"]]
    seen = set()
    for b in page.get_text("dict").get("blocks", []):
        for ln in b.get("lines", []):
            t = " ".join(s.get("text", "") for s in ln.get("spans", []))
            t = re.sub(r"\s+", " ", t).strip()
            if t and rx.search(t) and t not in seen:
                seen.add(t)
                print(f"{num:<8} {t[:150]}")
