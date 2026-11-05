"""Is the local AI working for Generate Set? Checks Ollama, the model, and
runs a few briefs and project notes through it.

    python tools/ai_check.py"""
import json
import os
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from app.ai import review  # noqa: E402
from app.genset import brief, layout, notes  # noqa: E402

print("host", review.HOST, "model", review.MODEL)
try:
    with urllib.request.urlopen(review.HOST.rstrip("/") + "/api/tags",
                                timeout=5) as r:
        tags = json.load(r)
    names = [m.get("name") for m in tags.get("models", [])]
    print("Ollama is running. Models:", names)
except Exception as e:                                   # noqa: BLE001
    print("Ollama is NOT running:", e)
    raise SystemExit(1)
if not any(n and n.split(":")[0] == review.MODEL.split(":")[0]
           for n in names):
    print(f"Model {review.MODEL} is not pulled. Run: ollama pull "
          f"{review.MODEL}")
    raise SystemExit(1)

BRIEFS = ["Three bedroom two bath ranch house for the Miller family at "
          "412 Oak Lane, about 1,700 square feet, new construction",
          "Small dental office, roughly 2,200 sf, renovation of an existing "
          "building",
          "Corner hardware store about 3500 sf new"]
for b in BRIEFS:
    t = time.time()
    raw = brief._ai_fields(b)
    f = brief.parse(b, use_ai=True)
    print(f"\nBRIEF: {b}\n  AI answer ({time.time() - t:.1f}s): {raw}")
    print("  used:", {k: f.get(k) for k in ("name", "address",
          "building_type", "occupancy", "work", "gross_sf", "beds",
          "baths", "ai_used")})
    print("  warnings:", f.get("warnings"))
    try:
        p = layout.make_plan(f)
        t = time.time()
        n, from_ai = notes.project_notes(p)
        print(f"  notes ({time.time() - t:.1f}s, from AI: {from_ai}):")
        for x in n:
            print("   -", x)
    except Exception as e:                               # noqa: BLE001
        print("  plan:", e)
