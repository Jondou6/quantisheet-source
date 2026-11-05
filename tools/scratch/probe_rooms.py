import os, sys, random
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import fitz
import accuracy_real as A
from app import autotakeoff
rnd = random.Random(int(sys.argv[1]) if len(sys.argv) > 1 else 7)
doc = fitz.open(); truth = A.plan(doc, rnd)
sc = {"ppu": A.PPF, "unit": "ft"}
plan = autotakeoff.Plan(doc[0], sc)
print("vector walls drawn:", plan.vector_walls)
tags = autotakeoff.room_tags(doc[0]); labs = autotakeoff.room_labels(doc[0], [t["pt"] for t in tags])
print("sf tags", len(tags), "name labels", len(labs), "truth", len(truth), sum(t["sf_tag"] for t in truth))
found, missed = autotakeoff.all_rooms(doc[0], sc)
for t in truth:
    c = fitz.Point((t["rect"].x0 + t["rect"].x1)/2, (t["rect"].y0 + t["rect"].y1)/2)
    hit = [r for r in found if min(p.x for p in r["pts"]) <= c.x <= max(p.x for p in r["pts"]) and min(p.y for p in r["pts"]) <= c.y <= max(p.y for p in r["pts"])]
    s = ", ".join(f"{r['name']} {r['sqft']:.0f}" for r in hit)
    print(f"{t['name']:14} true {t['sf']:7.1f} tag={t['sf_tag']!s:5} -> {s}")
print("missed:", [m["name"] for m in missed])
import cv2, numpy as np
cv2.imwrite(os.path.join(ROOT, ".run", "rooms_mask.png"), (1 - plan.walls) * 255)
doc.save(os.path.join(ROOT, ".run", "rooms_plan.pdf"))
