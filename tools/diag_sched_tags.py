"""Diagnostic (read-only): how schedule keys are counted on one sheet of
an eval set (work copy) - the cells holding each key, the views, which
view each hit falls in, and the count_tags result.
    python tools/diag_sched_tags.py M-101 "OCU-1,OCU-2" [kind] --set colleton"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import app  # noqa: E402,F401
import fitz  # noqa: E402
import aiken_eval  # noqa: E402
from app import aitakeoff as ait, schedules as sc  # noqa: E402

num = sys.argv[1].upper()
keys = [k.strip() for k in sys.argv[2].split(",")]
kind = sys.argv[3] if len(sys.argv) > 3 else "mechanical equipment"
doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))
rows = ait.plan_set(doc, None)
r = next(r for r in rows if (r.get("number") or "").upper() == num and
         r.get("kind") != "superseded")
p = r["page"]
print(num, "page", p, r.get("title"), r.get("kind"), r.get("discipline"))
info = sc.sheet_info(doc[p], {})
ts = sc.read_cells(info["cells"], info["segs"], info["w"], info["h"],
                   r.get("discipline", ""))
print("tables on sheet:", [(t["title"][:30], t["kind"], len(t["rows"]))
                           for t in ts])
ex = sc.plan_exclusions(info, ts)
print("exclusions:", [tuple(round(v) for v in e) for e in ex][:12])
vs = sc.view_regions(sc.views(info["cells"], ex), info["segs"] or [],
                     info["w"], info["h"], ex)
print("views:", [(v["title"][:40], v.get("plan"),
                  tuple(round(x) for x in v.get("rect", ())[:4]),
                  tuple(round(x) for x in v.get("region", ())))
                 for v in vs])
km = {sc.norm_key(k, kind): k for k in keys}
for c in info["cells"]:
    if any(k.upper() in c["text"].upper() for k in keys):
        inx = any(sc._inside(c, e) for e in ex)
        v = sc.view_of(c, vs, info["w"])
        print(f"  cell {c['text']!r} at ({c['cx']:.0f},{c['cy']:.0f}) h "
              f"{c['h']:.1f} excluded={inx} view="
              f"{v['title'][:30] if v else None} match="
              f"{sc._tag_match(c['text'], km, kind)}")
out = sc.count_tags(info, km, kind, ex, vs)
print("main:", {k: len(v) for k, v in out["main"].items()})
print("other:", [(k, len(h), t[:30]) for k, h, t in out["other"]])
print("skipped:", out["skipped"], "main views:", out["main_views"])
