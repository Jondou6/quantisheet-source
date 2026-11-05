"""Nov 3: "QuantiSheet closed unexpectedly last time" shows at every start.
Print what the start-up check sees (read only): crash.log's size, the
offset kept in crashes\\seen.json, and the crash text it finds after it.

    python tools/crash_seen.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import crashreport                                  # noqa: E402
from app.main import log_folder                              # noqa: E402

crash = os.path.join(log_folder(), "crash.log")
print("log folder:", log_folder())
print("crash.log:", crash, os.path.getsize(crash) if os.path.exists(crash)
      else "missing")
seen_p = os.path.join(crashreport.folder(), "seen.json")
try:
    seen = json.load(open(seen_p, encoding="utf-8"))
except Exception as e:                                       # noqa: BLE001
    seen = {}
    print("seen.json unreadable:", repr(e))
print("seen.json:", seen_p, seen)
print("same file string:", seen.get("file") == crash)
start = seen.get("offset", 0) if seen.get("file") == crash else 0
text = open(crash, "rb").read()[start:].decode("utf-8", "replace")
m = crashreport._fatal(text)
print("new bytes:", len(text), "fatal match:", bool(m))
if m:
    print("----- around it:")
    print(text[max(0, m.start() - 600):m.start() + 400])
print("reports:", [os.path.basename(r) for r in crashreport.reports(8)])
