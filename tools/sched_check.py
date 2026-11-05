"""Run Build Schedule From Plans' reading on a drawing set (a copy) and
print what it found: type, evidence, equipment, sheets, and the activity
list. usage: python tools/sched_check.py plans.pdf [spec.pdf]"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import fitz                                                   # noqa: E402

from app.pm import autoschedule as au                         # noqa: E402

plans = fitz.open(sys.argv[1])
spec = fitz.open(sys.argv[2]) if len(sys.argv) > 2 else None
job = au.read_job(plans=plans, spec=spec)
from app import sheets as _sheets                             # noqa: E402
print("SHEETS:", job["sheets"])
for r in _sheets.scan(plans, numbers=False):
    print("  ", r.get("page"), r.get("number"), "|", r.get("title"))
print("SCOPE TYPE:", job["scope"].get("type"))
print("TYPE:", job["type"], "| ranked:", (job.get("detected") or {}).get("ranked"))
for v in job.get("evidence") or []:
    print("  evidence:", v)
print("EQUIPMENT:")
for e in job.get("equipment") or []:
    print("  ", e)
sc = job["scope"]
print("FLAGS:", sorted(sc.get("flags", [])))
print("AREA:", sc.get("area_sf"), "found:", job.get("area_found"))
if sc.get("type") and sc["type"] != "unknown":
    acts = au.plan(sc)
    print(f"ACTIVITIES ({len(acts)}):")
    for a in acts:
        print(f"   {a['phase'][:16]:16} {a['duration']:4}d  {a['name']}")
    print("SUMMARY:")
    for ln in au.summary_text(job["ct"], sc, {}):
        print("  ", ln)
else:
    print("NO PLAN: type unknown - the dialog would ask")
