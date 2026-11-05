"""Screenshots of the modern (Acrobat-style) layout for review.

    python tools/modern_screens.py [OUT_DIR] [PDF]
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["QUANTISHEET_NO_OPEN"] = "1"
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

from PySide6.QtWidgets import QApplication, QDialog, QMessageBox  # noqa

from app import settings, theme                                    # noqa

TMP = tempfile.mkdtemp(prefix="quantisheet-modern-")
settings.DIR = os.path.join(TMP, "cfg")
settings.PATH = os.path.join(settings.DIR, "settings.json")
settings._cache = {"author": "Pat Morgan"}
QMessageBox.information = staticmethod(lambda *a, **k: 0)
QMessageBox.warning = staticmethod(lambda *a, **k: 0)
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Discard)
QDialog.exec = lambda self, *a: 0


def main(argv):
    out = argv[0] if argv else os.path.join(ROOT, ".run", "modernshots")
    os.makedirs(out, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    theme.apply(app, "light")
    from app.main_window import MainWindow
    pdf = argv[1] if len(argv) > 1 and os.path.isfile(argv[1]) else None
    if pdf is None:
        import make_sample
        pdf = os.path.join(TMP, "A-101 Floor Plan.pdf")
        make_sample.make(pdf)
    w = MainWindow()
    w.resize(1600, 950)
    w.show()
    w.open_path(pdf)
    app.processEvents()
    lay = w.layouts

    def shot(name):
        for _ in range(3):
            app.processEvents()
        p = os.path.join(out, name)
        w.grab().save(p)
        print("saved", p, flush=True)

    shot("1_modern_window.png")
    from PySide6.QtWidgets import QTabBar
    for bar in w.findChildren(QTabBar):
        if bar.parent() is w:
            tabs = [bar.tabText(i) for i in range(bar.count())]
            print("tab bar", bar.isVisible(), bar.geometry().getRect(), tabs,
                  "current", bar.currentIndex(), flush=True)
    for d in w.findChildren(__import__("PySide6.QtWidgets",
                                       fromlist=["QDockWidget"]).QDockWidget):
        print("dock", d.windowTitle(), "visible", d.isVisible(),
              "area", int(w.dockWidgetArea(d).value)
              if hasattr(w.dockWidgetArea(d), "value") else w.dockWidgetArea(d),
              d.geometry().getRect(), flush=True)
    lay.dock.show()
    lay.dock.raise_()
    app.processEvents()
    shot("2_all_tools.png")
    lay.panel.search.setText("area")
    shot("3_all_tools_search.png")
    lay.panel.search.clear()
    lay.dock.hide()
    w.set_tool("add_cloud")
    shot("4_tool_strip_cloud.png")
    w.set_tool(None)
    theme.apply(app, "dark")
    lay.dock.show()
    lay.dock.raise_()
    shot("5_dark.png")
    theme.apply(app, "light")
    os._exit(0)


if __name__ == "__main__":
    main(sys.argv[1:])
