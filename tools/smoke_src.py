"""Run the installer's smoke check from source with a hang dump:
python tools/smoke_src.py [SECONDS]"""
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
limit = int(sys.argv[1]) if len(sys.argv) > 1 else 90
out = os.path.join(tempfile.mkdtemp(), "smoke.json")
env = dict(os.environ, QUANTISHEET_SMOKE=out, QT_QPA_PLATFORM="offscreen",
           PYTHONUNBUFFERED="1")
code = ("import faulthandler, sys; faulthandler.dump_traceback_later("
        f"{limit}, exit=True); from app import main; sys.exit(main.run())")
p = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env,
                   capture_output=True, text=True, timeout=limit + 60)
print("exit", p.returncode)
print(p.stdout[-4000:])
print(p.stderr[-8000:])
if os.path.exists(out):
    with open(out) as fh:
        res = json.load(fh)
    for k, c in res["checks"].items():
        print(("ok  " if c["ok"] else "BAD ") + k, c.get("s", ""),
              str(c.get("error", ""))[-300:])
else:
    print("no smoke result")
