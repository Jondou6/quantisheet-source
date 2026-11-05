"""Find what leaks open files: open a set in the window, do the usual
things, and after each one print how many files the process has open
(grouped by path) and the C runtime's FILE count.

    python tools/handles_probe.py FILE.pdf
"""
import collections
import ctypes
import os
import shutil
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

from app import settings                                      # noqa: E402

TMP = tempfile.mkdtemp(prefix="quantisheet-handles-")
settings.DIR = os.path.join(TMP, "cfg")
settings.PATH = os.path.join(settings.DIR, "settings.json")
settings._cache = {"author": "Probe"}
os.makedirs(settings.DIR, exist_ok=True)


def handles():
    try:
        k = ctypes.windll.kernel32
        n = ctypes.c_ulong()
        k.GetProcessHandleCount(k.GetCurrentProcess(), ctypes.byref(n))
        return n.value
    except Exception:
        return -1


def files():
    try:
        import psutil
        return [f.path for f in psutil.Process().open_files()]
    except Exception as e:
        return [f"(psutil unavailable: {e})"]


def report(label):
    fs = files()
    c = collections.Counter(os.path.basename(p) for p in fs)
    print(f"\n== {label}: {len(fs)} open files, {handles()} handles",
          flush=True)
    for name, n in c.most_common(8):
        print(f"   {n:4} x {name}", flush=True)


def main(argv):
    src = argv[0].strip('"')
    path = os.path.join(TMP, "set.pdf")
    shutil.copy(src, path)
    from PySide6.QtWidgets import QApplication, QMessageBox
    app = QApplication.instance() or QApplication([])
    for n in ("information", "warning", "critical"):
        setattr(QMessageBox, n, staticmethod(lambda *a, **k: 0))
    report("start")
    from app.main_window import MainWindow
    w = MainWindow()
    w.resize(1600, 950)
    w.show()
    app.processEvents()
    report("window")
    w.open_path(path)
    for _ in range(20):
        app.processEvents()
        time.sleep(0.05)
    report("after opening the set")
    v = w._view
    for p in range(min(40, v.doc.page_count)):
        v.go_to(p)
        app.processEvents()
    report("after flipping 40 sheets")
    from app import heavy
    t = time.time()
    heavy.civil_pages(v.doc)
    report(f"after civil_pages ({time.time() - t:.0f}s)")
    from app import acrobat2
    try:
        acrobat2.external_issue(v.doc, os.path.join(TMP, "ext.pdf"))
        report("after External Issue")
    except Exception as e:
        report(f"External Issue FAILED: {e}")
    v.dirty = False
    w.close()
    app.processEvents()
    report("after closing")
    shutil.rmtree(TMP, ignore_errors=True)
    os._exit(0)


if __name__ == "__main__":
    main(sys.argv[1:])
