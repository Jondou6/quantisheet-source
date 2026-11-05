"""Page through the heavy sheets of the plant set (a copy) and measure how
long the window is unresponsive, with the drawing process off and on.

    python tools/page_turn_probe.py [off|on]
"""
import os
import shutil
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["QUANTISHEET_NO_OPEN"] = "1"
MODE = (sys.argv[1] if len(sys.argv) > 1 else "on").lower()
os.environ["QUANTISHEET_DRAW_PROCESS"] = "1" if MODE == "on" else "0"
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

from PySide6.QtCore import QTimer                                    # noqa
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox     # noqa

from app import settings, theme                                      # noqa

TMP = tempfile.mkdtemp(prefix="quantisheet-turns-")
settings.DIR = os.path.join(TMP, "cfg")
settings.PATH = os.path.join(settings.DIR, "settings.json")
settings._cache = {"author": "Tester", "autosave_mode": "off"}
QMessageBox.information = staticmethod(lambda *a, **k: 0)
QDialog.exec = lambda self, *a: 0
SRC = os.path.join(os.path.expanduser("~"), "OneDrive", "Desktop",
                   "32410-004-IFC-Plant Drawings.pdf")
HEAVY = list(range(33, 45)) + list(range(212, 217))      # 0-based pages


def main():
    app = QApplication.instance() or QApplication([])
    theme.apply(app, "light")
    from app.main_window import MainWindow
    copy = os.path.join(TMP, "plant-copy.pdf")
    shutil.copy(SRC, copy)
    w = MainWindow()
    w.resize(1600, 950)
    w.show()
    w.open_path(copy)
    v = w._view
    gaps = []
    state = {"last": time.perf_counter()}

    def beat():
        now = time.perf_counter()
        gaps.append(now - state["last"])
        state["last"] = now
    t = QTimer()
    t.timeout.connect(beat)
    t.start(10)

    def run_for(secs):
        end = time.perf_counter() + secs
        while time.perf_counter() < end:
            app.processEvents()
            time.sleep(0.003)

    v.go_to(HEAVY[0] - 1)
    run_for(3)                                  # settle, let it draw ahead
    turn_times, worst = [], []
    for p in HEAVY:
        gaps.clear()
        state["last"] = time.perf_counter()
        t0 = time.perf_counter()
        v.go_to(p)                              # what Page Down does
        turn_times.append(time.perf_counter() - t0)
        # what the window does 0.4 s later on a real screen: get snapping
        # ready (the offscreen test window doesn't count as visible)
        v.snap_enabled = True
        QTimer.singleShot(400, v.snap_index)
        run_for(4.0)                            # reading the sheet
        worst.append(max(gaps) if gaps else 0)
    t.stop()
    print(f"drawing process {MODE.upper()}  ({len(HEAVY)} heavy sheets)",
          flush=True)
    print(f"  page turn itself: mean {1000*sum(turn_times)/len(turn_times):.0f}"
          f" ms, max {1000*max(turn_times):.0f} ms", flush=True)
    print(f"  longest freeze while reading each sheet: mean "
          f"{1000*sum(worst)/len(worst):.0f} ms, max {1000*max(worst):.0f} ms",
          flush=True)
    print("  per sheet (turn / worst freeze after), ms:", flush=True)
    print("   " + "  ".join(f"p{p+1}:{a*1000:.0f}/{b*1000:.0f}"
                            for p, a, b in zip(HEAVY, turn_times, worst)),
          flush=True)
    from app import render_worker
    render_worker.get().stop() if render_worker._worker else None
    os._exit(0)


if __name__ == "__main__":
    main()
