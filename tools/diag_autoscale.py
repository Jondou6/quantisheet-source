"""Diagnostic (read-only, work copy): Auto Scale on every sheet of an eval
set - status counts, and for each sheet that isn't 'ok' its number, kind,
note and the scale-like text printed on it (what we failed to read).
    python tools/diag_autoscale.py --set colleton"""
import collections
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import app  # noqa: E402,F401
import fitz  # noqa: E402
import aiken_eval  # noqa: E402
from app import aitakeoff as ait, autoscale  # noqa: E402

doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))
sheets = {r["page"]: r for r in ait.plan_set(doc, None)}
t0 = time.time()
rows = autoscale.detect(doc, use_ocr=False)
print(f"{len(rows)} pages in {time.time() - t0:.1f}s:",
      dict(collections.Counter(r["status"] for r in rows)))
SC = re.compile(r"(SCALE[^\n]{0,40}|\d+/\d+\"?\s*=\s*1'?-?0\"?|"
                r"1\"\s*=\s*\d+'|N\.?T\.?S\.?|NOT TO SCALE|AS NOTED)", re.I)
for r in rows:
    s = sheets.get(r["page"], {})
    hits = []
    for m in SC.finditer(doc[r["page"]].get_text()):
        t = " ".join(m.group(0).split())
        if t not in hits:
            hits.append(t)
    flag = r["status"] if r["status"] != "ok" else "ok  "
    print(f"{r['page'] + 1:3d} {s.get('number') or '?':8s} {flag:5s} "
          f"{(s.get('kind') or '')[:10]:10s} label={r.get('label')!s:14.14s} "
          f"src={r.get('source') or '-':5s} {r.get('note', '')[:50]:50s} "
          f"| {'; '.join(hits[:6])[:120]}")
