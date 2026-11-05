"""Screenshot of the window with the Takeoff panel after auto rooms on a
page of a copy of FILE: python tools/shot_takeoff.py FILE PAGE OUT.png"""
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

from PySide6.QtWidgets import QApplication, QMessageBox      # noqa: E402

from app import settings                                      # noqa: E402

TMP = tempfile.mkdtemp(prefix="quantisheet-shot-")
settings.DIR = os.path.join(TMP, "cfg")
settings.PATH = os.path.join(settings.DIR, "settings.json")
settings._cache = None
for n in ("information", "warning"):
    setattr(QMessageBox, n, staticmethod(lambda *a, **k: 0))


def main(argv):
    src, page, out = argv[0].strip('"'), int(argv[1]) - 1, argv[2]
    cp = os.path.join(TMP, "copy.pdf")
    shutil.copy(src, cp)
    app = QApplication.instance() or QApplication([])
    from app.main_window import MainWindow
    w = MainWindow()
    w.resize(1600, 950)
    w.show()
    w.open_path(cp)
    app.processEvents()
    v = w._view
    v.go_to(page)
    w.auto_takeoff_rooms()
    app.processEvents()
    w.takeoff_dock.raise_()
    w._refresh_panels()
    for _ in range(5):
        app.processEvents()
    w.grab().save(out)
    print(out, w.takeoff_tree.tree.topLevelItemCount(), "sheets")


if __name__ == "__main__":
    main(sys.argv[1:])
