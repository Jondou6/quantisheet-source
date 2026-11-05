"""Diagnostic (read-only, work copy): what autowalls.doors finds on one
sheet of an eval set and why - each door's place, width and sweep, the
view it falls in, the nearest other swing (pairs and double counts), and
the door marks written on the sheet.
    python tools/diag_doors.py A-102 [ppu] --set colleton"""
import math
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
from app import aitakeoff as ait, autowalls as aw, schedules as sc  # noqa

num = sys.argv[1].upper()
ppu = float(sys.argv[2]) if len(sys.argv) > 2 else 9.0     # 1/8" = 1'-0"
doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))
rows = ait.plan_set(doc, None)
r = next(r for r in rows if (r.get("number") or "").upper() == num and
         r.get("kind") != "superseded")
p = r["page"]
page = doc[p]
print(num, "page", p + 1, r.get("title"), r.get("kind"), "ppu", ppu)
t0 = time.time()
ds = aw.doors(page, ppu, "ft")
print("doors():", len(ds), f"in {time.time() - t0:.1f}s")
info = sc.sheet_info(page, {})
ts = sc.read_cells(info["cells"], info["segs"], info["w"], info["h"],
                   r.get("discipline", ""))
ex = sc.plan_exclusions(info, ts)
vs = sc.view_regions(sc.views(info["cells"], ex), info["segs"] or [],
                     info["w"], info["h"], ex)
print("views:", [(v["title"][:34], v.get("plan"),
                  tuple(round(x) for x in v.get("region", ())))
                 for v in vs])


def view_at(x, y):
    for v in vs:
        g = v.get("region") or ()
        if len(g) == 4 and g[0] <= x <= g[2] and g[1] <= y <= g[3]:
            return v["title"][:24]
    return "-"


for i, d in enumerate(ds):
    x, y = d["hinge"]
    near = min((math.hypot(x - e["hinge"][0], y - e["hinge"][1]), j)
               for j, e in enumerate(ds) if j != i) if len(ds) > 1 else (0, -1)
    print(f"  {i:2d} ({x:6.0f},{y:6.0f}) x{d.get('leaves', 1)} w {d['width']:.2f} sweep "
          f"{d['sweep']:5.1f} view {view_at(x, y):24s} nearest "
          f"#{near[1]} {near[0] / ppu:5.1f} ft")
# door marks: short tags near swings (e.g. 101, 101A, D12)
words = page.get_text("words")
mark = re.compile(r"^[A-Z]?\d{2,3}[A-Z]?$")
tags = [w for w in words if mark.match(w[4])]
print("number-like words on sheet:", len(tags))
near_tags = 0
for d in ds:
    x, y = d["hinge"]
    rr = d["width"] * ppu * 2.0
    if any(math.hypot((w[0] + w[2]) / 2 - x, (w[1] + w[3]) / 2 - y) < rr
           for w in tags):
        near_tags += 1
print("doors with a number-like tag within 2 widths:", near_tags)
# the door schedule elsewhere in the set
for rr_ in rows:
    pg = doc[rr_["page"]]
    if "DOOR SCHEDULE" in pg.get_text().upper():
        print("door schedule on", rr_.get("number"), "page", rr_["page"] + 1)
