"""Diagnostic (read-only): run AI Takeoff's walls + schedules + stage 3
(envelope / roof / site) on the Aiken work copy and print the stage 3
lines, review entries and any error, with the log going to the console.
    python tools/diag_aiken_stage3.py"""
import logging
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
logging.basicConfig(level=logging.WARNING, stream=sys.stdout,
                    format="LOG %(levelname)s %(name)s: %(message)s")
import app  # noqa: E402,F401
import fitz  # noqa: E402
import aiken_eval  # noqa: E402
from app import aitakeoff as ait  # noqa: E402

doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))
rows = ait.plan_set(doc, None)
engines = sys.argv[1:] or ["walls", "schedules", "envelope", "roof",
                           "site", "earthwork", "landscape"]
res = ait.run(doc, rows, engines=engines)
print("timing:", res.get("timing"))
for sh, d in res["sheets"].items():
    if d.get("walls"):
        print("sheet", sh + 1, "walls:", d["walls"])
for q in res["quantities"]:
    if q.get("engine") in ("envelope", "roof", "site", "earthwork",
                           "walls"):
        print("Q", q["engine"], q["name"], q["qty"], q["unit"],
              (q.get("basis") or "")[:120])
for v in res["review"]:
    if v.get("ai_derived") or v.get("engine") in ("walls",):
        print("R", v.get("engine"), v["name"], v.get("qty"), v.get("unit"),
              (v.get("why") or "")[:140])
print("problems:", [p for p in res["problems"] if "envelope" in p.lower()
                    or "site" in p.lower()])
