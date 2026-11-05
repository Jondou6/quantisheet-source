"""Run pytest with a time limit and print what it printed so far, plus
stack dumps of any test that runs longer than 40 s (finds hangs).
usage: tests_timed.py SECONDS pytest-args..."""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
limit = int(sys.argv[1])
cmd = [sys.executable, "-m", "pytest", "-v", "-p", "no:cacheprovider",
       "-o", "faulthandler_timeout=40"] + sys.argv[2:]
env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONUNBUFFERED="1")
p = subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=subprocess.PIPE,
                     stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                     errors="replace")
try:
    out, _ = p.communicate(timeout=limit)
except subprocess.TimeoutExpired:
    subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"],
                   capture_output=True) if sys.platform.startswith("win") \
        else p.kill()
    out, _ = p.communicate()
    out += f"\n[KILLED after {limit}s]\n"
try:
    sys.stdout.reconfigure(errors="replace")
except Exception:
    pass
print(out[-20000:])
