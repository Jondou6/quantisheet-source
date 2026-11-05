"""Point the Documents panel at a folder (the Desktop by default) the way a
person would, and measure how long the window stops answering.

    python tools/docs_probe.py [FOLDER] [SECONDS]
"""
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["QUANTISHEET_NO_OPEN"] = "1"
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

from PySide6.QtCore import QTimer                                    # noqa
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox     # noqa

from app import settings, theme                                      # noqa

TMP = tempfile.mkdtemp(prefix="quantisheet-docs-")
settings.DIR = os.path.join(TMP, "cfg")
settings.PATH = os.path.join(settings.DIR, "settings.json")
settings._cache = {"author": "Tester", "autosave_mode": "off"}
QMessageBox.information = staticmethod(lambda *a, **k: 0)
QDialog.exec = lambda self, *a: 0


def main(argv):
    folder = (argv[0].strip('"') if argv else
              os.path.join(os.path.expanduser("~"), "OneDrive", "Desktop"))
    secs = float(argv[1]) if len(argv) > 1 else 20
    app = QApplication.instance() or QApplication([])
    theme.apply(app, "light")
    from app.main_window import MainWindow
    w = MainWindow()
    w.resize(1600, 950)
    w.show()
    gaps = []
    last = [time.perf_counter()]

    def beat():
        now = time.perf_counter()
        gaps.append((now - last[0], now))
        last[0] = now
    t = QTimer()
    t.timeout.connect(beat)
    t.start(10)
    for _ in range(20):
        app.processEvents()
    d = w.documents
    t0 = time.perf_counter()
    last[0] = t0
    gaps.clear()
    d.set_folder(folder)
    w.docs_dock.show()
    w.docs_dock.raise_()
    set_time = time.perf_counter() - t0
    end = time.perf_counter() + secs
    while time.perf_counter() < end:
        app.processEvents()
        time.sleep(0.003)
    t.stop()
    worst = sorted(gaps, reverse=True)[:5]
    print(f"folder: {folder}", flush=True)
    print(f"set_folder + show returned in {set_time*1000:.0f} ms", flush=True)
    print(f"rows: {d.tree.topLevelItemCount()} top level; still counting: "
          f"{len(d._pending)}", flush=True)
    print("longest freezes (ms, at s after start): " + ", ".join(
        f"{g*1000:.0f} @ {at - t0:.1f}s" for g, at in worst), flush=True)
    os._exit(0)


if __name__ == "__main__":
    main(sys.argv[1:])
