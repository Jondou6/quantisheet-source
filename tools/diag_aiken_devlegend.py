"""Diagnostic (read-only): the device legend rows on one Aiken sheet and
how many times each symbol matches on another sheet (work copy).
    python tools/diag_aiken_devlegend.py E-001 E-301 [threshold]"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import app  # noqa: E402,F401
import fitz  # noqa: E402
import aiken_eval  # noqa: E402
from app import aitakeoff as ait, autocount, tradetakeoff as tt  # noqa: E402

src, dst = sys.argv[1].upper(), sys.argv[2].upper()
th = float(sys.argv[3]) if len(sys.argv) > 3 else 0.8
doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))
rows = ait.plan_set(doc, None)
pg = {(r.get("number") or "").upper(): r["page"] for r in rows
      if r.get("kind") != "superseded"}
rej = []
legend = tt.legend_rows(doc[pg[src]], rejects=rej)
print(len(legend), "legend rows;", len(rej), "rejected")
for t, why in rej[:40]:
    print("  rejected:", t[:70], "-", why)
for name, sym in legend:
    clip = (sym + (-1.5, -1.5, 1.5, 1.5)) & doc[pg[src]].rect
    try:
        tpl = autocount.symbol_template(doc[pg[src]], clip)
        hits = autocount.find_symbols(doc, tpl, th, [pg[dst]])
        sc = sorted((round(h.get("score", 0), 2) for h in hits),
                    reverse=True)[:5]
    except Exception as e:                                # noqa: BLE001
        hits, sc = [], str(e)[:40]
    print(f"  {name[:50]:<50} sym {round(sym.width)}x{round(sym.height)}"
          f"  hits on {dst}: {len(hits)} {sc}")
# where the headings and the lines asked about sit
import re  # noqa: E402
want = re.compile(sys.argv[4], re.I) if len(sys.argv) > 4 else None
p = doc[pg[src]]
for w in p.get_text("words"):
    if w[4].strip(":").upper() in ("LEGEND", "SYMBOLS", "SYMBOL"):
        print("heading", w[4], [round(v) for v in w[:4]])
if want:
    for b in p.get_text("dict")["blocks"]:
        for ln in b.get("lines", []):
            t = " ".join(s_["text"] for s_ in ln["spans"])
            if want.search(t):
                print("line", [round(v) for v in ln["bbox"]], t[:60])
