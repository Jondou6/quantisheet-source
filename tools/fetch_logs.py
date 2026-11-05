"""Copy the end of QuantiSheet's log, crash log and recent files into
.run/logs (for support): python tools/fetch_logs.py"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from app import settings  # noqa: E402

out = os.path.join(ROOT, ".run", "logs")
os.makedirs(out, exist_ok=True)
for name, keep in ((settings.LOG_NAME, 400000), ("crash.log", 200000)):
    p = os.path.join(settings.DIR, name)
    if os.path.exists(p):
        with open(p, "rb") as f:
            f.seek(max(0, os.path.getsize(p) - keep))
            data = f.read()
        with open(os.path.join(out, name), "wb") as f:
            f.write(data)
        print(name, os.path.getsize(p), "bytes")
s = settings._load() if hasattr(settings, "_load") else {}
recent = s.get("recent") or s.get("recent_files") or []
print("recent:", json.dumps(recent[:10], indent=1))
for k in s:
    if "recent" in k.lower():
        print(k, json.dumps(s[k])[:600])
