"""Run another tool with Python's crash recorder on, in this same process,
so a hard crash prints where it happened, and a hang is stopped after
14 minutes with a dump of every thread (instead of freezing the runner):
    python tools/crash_wrap.py TOOL [ARGS...]"""
import faulthandler
import os
import runpy
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
args = [a.strip('"') for a in sys.argv[1:]]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    sys.stdout.reconfigure(line_buffering=True, errors="replace")
    sys.stderr.reconfigure(line_buffering=True, errors="replace")
except Exception:
    pass
faulthandler.enable(all_threads=True)
faulthandler.dump_traceback_later(840, exit=True)      # hang -> dump + exit
script = os.path.join(ROOT, "tools", args[0] + ".py")
sys.argv = [script] + args[1:]
sys.path.insert(0, ROOT)
try:
    runpy.run_path(script, run_name="__main__")
except SystemExit as e:
    print(f"\n[tool exited with {e.code}]")
    raise
