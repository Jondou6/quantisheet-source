"""What sets the window's minimum width in each layout.

    python tools/width_probe.py
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

from PySide6.QtWidgets import (QApplication, QDialog, QDockWidget,  # noqa
                               QMessageBox, QToolBar)

from app import settings, theme                                    # noqa

TMP = tempfile.mkdtemp(prefix="quantisheet-width-")
settings.DIR = os.path.join(TMP, "cfg")
settings.PATH = os.path.join(settings.DIR, "settings.json")
settings._cache = {"author": "Pat Morgan"}
QMessageBox.information = staticmethod(lambda *a, **k: 0)
QMessageBox.warning = staticmethod(lambda *a, **k: 0)
QDialog.exec = lambda self, *a: 0


def main():
    app = QApplication.instance() or QApplication([])
    theme.apply(app, "light")
    from app.main_window import MainWindow
    import make_sample
    pdf = os.path.join(TMP, "A-101.pdf")
    make_sample.make(pdf)
    w = MainWindow()
    w.resize(1500, 900)
    w.show()
    w.open_path(pdf)
    lay = w.layouts

    def report(tag):
        for _ in range(4):
            app.processEvents()
        print(f"== {tag}: layout={lay.name} size={w.width()}x{w.height()} "
              f"minHint={w.minimumSizeHint().width()} "
              f"min={w.minimumWidth()}", flush=True)
        cw = w.centralWidget()
        print(f"   central minHint={cw.minimumSizeHint().width()}", flush=True)
        for t in w.findChildren(QToolBar):
            if t.parent() is w and t.isVisible():
                print(f"   toolbar {t.objectName() or t.windowTitle()!r} "
                      f"area={w.toolBarArea(t)} "
                      f"minHint={t.minimumSizeHint().width()} "
                      f"hint={t.sizeHint().width()} w={t.width()}", flush=True)
                for c in t.children():
                    if hasattr(c, "minimumSizeHint") and \
                            getattr(c, "isVisible", lambda: False)():
                        mh = c.minimumSizeHint().width()
                        if mh > 300:
                            print(f"      child {type(c).__name__} "
                                  f"{c.objectName()!r} minHint={mh}",
                                  flush=True)
        for d in w.findChildren(QDockWidget):
            if d.isVisible():
                print(f"   dock {d.windowTitle()!r} "
                      f"area={w.dockWidgetArea(d)} "
                      f"minHint={d.minimumSizeHint().width()} "
                      f"min={d.minimumWidth()} w={d.width()}", flush=True)

    w.showNormal()
    w.resize(1500, 900)
    report("start")
    for name in ("simple", "ribbon", "simple", "modern", "ribbon"):
        lay.set_layout(name)
        print(f"   right after set_layout: {w.width()} minHint "
              f"{w.minimumSizeHint().width()}", flush=True)
        report(f"after {name}")
    os._exit(0)


if __name__ == "__main__":
    main()
