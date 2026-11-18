"""Rotate All / Link Sheets / Unlink Sheets with the real drawing process,
then is the sheet drawn? (made-up sheets; offscreen window)"""
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def main():
    import fitz
    from PySide6.QtWidgets import QApplication, QMessageBox
    from app import settings
    tmp = tempfile.mkdtemp()
    settings.DIR = os.path.join(tmp, "cfg")
    settings.PATH = os.path.join(settings.DIR, "s.json")
    settings._cache = None
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
    for n_ in ("information", "warning"):
        setattr(QMessageBox, n_, staticmethod(lambda *a, **k: 0))
    app = QApplication.instance() or QApplication([])
    from app.main_window import MainWindow
    from test_blank_view_nov18 import made_up
    path = made_up(os.path.join(tmp, "set.pdf"))
    w = MainWindow()
    w.open_path(path)
    v = w._view

    def settle(s=3.0):
        t = time.time()
        while time.time() - t < s:
            app.processEvents()
            time.sleep(0.02)
    settle()
    print("drawer", v._drawer() is not None)
    for name, fn in (("link", lambda: w.batch_link()),
                     ("unlink", lambda: w.batch_link(remove=True)),
                     ("rotate all", lambda: w._page_action(
                         "rotate_right", list(range(v.doc.page_count))))):
        fn()
        settle()
        print(name, "drawn" if v.rendered is not None else "BLANK",
              "pending", list(v._pf_pending.items())[:3],
              "local", getattr(v, "_local_page", None), "edits", v._edits,
              "page", v.page, "zoom", round(v.zoom, 4))
    for x in w._all_views():
        x.dirty = False
    w.close()


if __name__ == "__main__":
    main()
