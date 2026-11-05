"""Debug civil takeoff on civil_real seeds: python tools/civil_debug.py SEED"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import civil_real                                             # noqa: E402
from app import civiltakeoff as ct, tradetakeoff as tt        # noqa: E402

seed = int(sys.argv[1]) if len(sys.argv) > 1 else 3
doc, truth = civil_real.make(seed)
pg = doc[0]
print("zones", ct.profile_zones(pg))
for l in ct.pipe_labels(pg):
    print("LABEL", l["name"], [round(v) for v in l["center"]], l["dir"])
res = ct.takeoff(doc, scales={0: (civil_real.PPU, "ft")})
for p in res["pipes"]:
    print("PIPE", p["name"], round(p["length"], 1), p["style_name"])
    for r in p["runs"]:
        print("   run", round(r["length"], 1), [round(v) for v in r["pts"][0]],
              [round(v) for v in r["pts"][-1]], len(r["pts"]))
print("truth", truth["lf"])
