"""Diagnostic (read-only): run the legend device count on the given Aiken
sheets (work copy) and show, per symbol, hits before and after the
same-spot competition, and which symbol took each lost spot.
    python tools/diag_aiken_compete.py E-201 [E-301 ...]"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import app  # noqa: E402,F401
import fitz  # noqa: E402
import aiken_eval  # noqa: E402
from app import aitakeoff as ait, tradetakeoff as tt  # noqa: E402

doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))
rows = ait.plan_set(doc, None)
pg = {(r.get("number") or "").upper(): r["page"] for r in rows
      if r.get("kind") != "superseded"}
import re  # noqa: E402
show = re.compile(sys.argv[-1], re.I) if sys.argv[-1].startswith("~") is False and len(sys.argv) > 1 and not re.match(r"^[A-Z]-\d", sys.argv[-1], re.I) else None
legend_pages = [r["page"] for r in rows if r.get("kind") != "superseded"
                and (r.get("number") or "").upper().startswith("E")]
pages = sorted(set(legend_pages))
orig = tt._compete
before = {}


def spy(found):
    for f in found:
        before[f["name"]] = [dict(h) for h in f["hits"]]
    orig(found)
    for f in found:
        kept = {(h["page"], tuple(round(v, 1) for v in h["rect"]))
                for h in f["hits"]}
        lost = [h for h in before[f["name"]]
                if (h["page"], tuple(round(v, 1) for v in h["rect"]))
                not in kept]
        print(f"{f['name'][:50]:<50} before {len(before[f['name']]):>3}"
              f" after {len(f['hits']):>3}")
        for h in lost[:6]:
            r = h["rect"]
            cx, cy = (r[0] + r[2]) / 2, (r[1] + r[3]) / 2
            by = []
            for g in found:
                for k in g["hits"]:
                    q = k["rect"]
                    if k["page"] == h["page"] and \
                            abs((q[0] + q[2]) / 2 - cx) < 8 and \
                            abs((q[1] + q[3]) / 2 - cy) < 8:
                        by.append(f"{g['name'][:28]}@{k.get('score', 0):.2f}")
            print(f"     lost p{h['page']} ({cx:.0f},{cy:.0f}) "
                  f"s{h.get('score', 0):.2f} to {by}")


tt._compete = spy
rep = {}
found = tt.legend_counts(doc, pages, report=rep, time_limit=400,
                         disciplines={r["page"]: r.get("discipline", "")
                                      for r in rows})
print("not counted:", rep.get("not_counted"))
for f in found:
    if show and show.search(f["name"]):
        for h in f["hits"]:
            print("  hit", f["name"][:30], h["page"],
                  [round(v) for v in h["rect"]], round(h.get("score", 0), 2))
print("pages", {p: n for n, p in pg.items() if p in pages})
