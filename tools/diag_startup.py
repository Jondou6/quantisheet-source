"""How long QuantiSheet takes to start, read-only, with settings of its own:
python tools/diag_startup.py

Runs a fresh Python that imports the program and opens the main window
(offscreen), and prints the time to the window and the slowest imports
(python -X importtime), so start-up can be measured on every build."""
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = os.path.join(ROOT, ".venv", "Scripts", "python.exe")
if not os.path.exists(PY):
    PY = sys.executable

CHILD = r"""
import os, sys, time, tempfile
t0 = time.perf_counter()
sys.path.insert(0, ROOT)
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtWidgets import QApplication
app = QApplication([])
t1 = time.perf_counter()
from app import settings
settings.DIR = tempfile.mkdtemp(prefix="qs_start_")
settings.PATH = os.path.join(settings.DIR, "settings.json")
settings._cache = None
from app.main_window import MainWindow
t2 = time.perf_counter()
w = MainWindow()
w.show()
app.processEvents()
t3 = time.perf_counter()
print(f"TIMES qt={t1 - t0:.2f} import={t2 - t1:.2f} window={t3 - t2:.2f} "
      f"total={t3 - t0:.2f} modules={len(sys.modules)} "
      f"app_modules={sum(1 for m in sys.modules if m.startswith('app'))}")
"""


def main():
    code = "ROOT = %r\n" % ROOT + CHILD
    best = None
    for _ in range(3):
        p = subprocess.run([PY, "-c", code], capture_output=True, text=True,
                           cwd=ROOT, timeout=300,
                           creationflags=getattr(subprocess,
                                                 "CREATE_NO_WINDOW", 0))
        line = [ln for ln in p.stdout.splitlines() if ln.startswith("TIMES")]
        if not line:
            print(p.stdout[-2000:], p.stderr[-2000:])
            return 1
        total = float(re.search(r"total=([\d.]+)", line[0]).group(1))
        if best is None or total < best[0]:
            best = (total, line[0])
    print("best of 3:", best[1][6:])
    p = subprocess.run([PY, "-X", "importtime", "-c", code],
                       capture_output=True, text=True, cwd=ROOT, timeout=300,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW",
                                             0))
    rows = []
    for ln in p.stderr.splitlines():
        m = re.match(r"import time:\s+(\d+) \|\s+(\d+) \|(\s*)(\S+)", ln)
        if m:
            rows.append((int(m.group(2)), len(m.group(3)), m.group(4)))
    top = [r for r in rows if r[1] <= 3]
    top.sort(reverse=True)
    print("slowest top-level imports (cumulative ms):")
    for us, _d, name in top[:25]:
        print(f"  {us / 1000:8.0f}  {name}")
    mine = sorted((r for r in rows if r[2].startswith("app.")),
                  reverse=True)[:25]
    print("slowest QuantiSheet modules (cumulative ms):")
    for us, _d, name in mine:
        print(f"  {us / 1000:8.0f}  {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
