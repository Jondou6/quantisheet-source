"""AI Takeoff through the real window (offscreen), to catch crashes:
python tools/ai_takeoff_gui.py FILE.pdf [--start]"""
import faulthandler
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
LOG = os.path.join(ROOT, ".run", "ai_takeoff_gui.log")


def log(*a):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(time.strftime("%H:%M:%S ") + " ".join(map(str, a)) + "\n")


def main(path):
    open(LOG, "w").close()
    faulthandler.enable(open(LOG + ".fault", "w"))
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtWidgets import QApplication, QMessageBox, QDialog
    app = QApplication.instance() or QApplication([])
    for n in ("information", "warning", "critical"):
        setattr(QMessageBox, n, staticmethod(
            lambda *a, **k: log("MESSAGE", a[1:3]) or 0))
    QDialog.exec = lambda self, *a: 0
    from app.main_window import MainWindow
    w = MainWindow()
    w.show()
    w.open_path(path)
    app.processEvents()
    log("opened", w._view.doc.page_count, "pages")
    dlg = w.ai_takeoff(show=False)
    t = time.time()
    rows = dlg.read()
    log(f"read {len(rows)} sheets in {time.time() - t:.0f}s")
    t = time.time()
    res = dlg.run()
    log(f"ran in {time.time() - t:.0f}s;", "marks:",
        len(res["marks"]) if res else None)
    log(dlg.summary.toPlainText())
    w._view.dirty = False
    w.close()
    log("DONE")


if __name__ == "__main__":
    if "--start" in sys.argv:
        args = [a.strip('"') for a in sys.argv[1:] if a != "--start"]
        subprocess.Popen([sys.executable, os.path.abspath(__file__)] + args,
                         cwd=ROOT, creationflags=getattr(
                             subprocess, "CREATE_NO_WINDOW", 0),
                         stdout=subprocess.DEVNULL,
                         stderr=open(LOG + ".err", "w"))
        print("started")
    else:
        try:
            main(sys.argv[1].strip('"'))
        except Exception:
            import traceback
            log("FAILED", traceback.format_exc())
