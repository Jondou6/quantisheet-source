"""Click every button on the left tool rail, with and without a drawing
open, and time each click. If one hangs, the Python stack is printed.

    python tools/rail_click_probe.py
"""
import faulthandler
import json
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["QUANTISHEET_NO_OPEN"] = "1"
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

from PySide6.QtCore import Qt, QTimer                               # noqa
from PySide6.QtTest import QTest                                    # noqa
from PySide6.QtWidgets import (QApplication, QDialog, QFileDialog,  # noqa
                               QInputDialog, QMessageBox, QWidget)

from app import settings, theme                                     # noqa

REAL = os.path.join(os.path.expanduser("~"), ".quantisheet", "settings.json")
pins = None
try:
    with open(REAL, encoding="utf-8") as f:
        pins = json.load(f).get("pinned_tools")
except Exception:                                                    # noqa
    pass

TMP = tempfile.mkdtemp(prefix="quantisheet-railprobe-")
settings.DIR = os.path.join(TMP, "cfg")
settings.PATH = os.path.join(settings.DIR, "settings.json")
settings._cache = {"author": "Tester", "autosave_mode": "off"}
if pins:
    settings._cache["pinned_tools"] = pins
SAID = []
QMessageBox.information = staticmethod(lambda *a, **k: SAID.append(a[2:3]) or 0)
QMessageBox.warning = staticmethod(lambda *a, **k: SAID.append(a[2:3]) or 0)
QMessageBox.critical = staticmethod(lambda *a, **k: SAID.append(a[2:3]) or 0)
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.No)
QInputDialog.getText = staticmethod(lambda *a, **k: ("Valves", True))
QInputDialog.getItem = staticmethod(lambda *a, **k: (a[3][0] if len(a) > 3 and a[3] else "", True))
QInputDialog.getDouble = staticmethod(lambda *a, **k: (10.0, True))
QInputDialog.getInt = staticmethod(lambda *a, **k: (1, True))
QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: ("", ""))
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: ("", ""))
QDialog.exec = lambda self, *a: (SAID.append(("dialog", self.windowTitle())), 0)[1]


def main():
    faulthandler.enable(all_threads=True)       # a hard crash shows where
    app = QApplication.instance() or QApplication([])
    theme.apply(app, "light")
    from app.main_window import MainWindow
    from app import modern_ui
    w = MainWindow()
    w.resize(1500, 900)
    w.show()
    lay = w.layouts
    print("layout", lay.name, "pins", pins, flush=True)

    def pump(n=5):
        for _ in range(n):
            app.processEvents()
            time.sleep(0.01)

    def click_all(tag):
        buttons = [b for b in lay.rail.findChildren(QWidget)
                   if b.isVisibleTo(w) and hasattr(b, "click")
                   and b.isEnabled()]
        print(f"== {tag}: {len(buttons)} enabled buttons", flush=True)
        for b in buttons:
            label = getattr(b, "_label", None) or b.text() or b.toolTip()
            SAID.clear()
            faulthandler.dump_traceback_later(25, exit=True)
            t = time.perf_counter()
            QTest.mouseClick(b, Qt.LeftButton)
            pump()
            dt = time.perf_counter() - t
            faulthandler.cancel_dump_traceback_later()
            v = getattr(w, "_view", None)
            tool = getattr(v, "tool", None) if v is not None else None
            flag = "SLOW" if dt > 2 else "ok  "
            print(f"   {flag} {dt:6.2f}s  {label!r:28} tool={tool} "
                  f"said={[s for s in SAID][:2]}", flush=True)
            if v is not None and tool:
                QTest.keyClick(v, Qt.Key_Escape)
                QTest.keyClick(v, Qt.Key_Escape)
                pump()
            # a second click on the same button (toggle off)
            faulthandler.dump_traceback_later(25, exit=True)
            t = time.perf_counter()
            QTest.mouseClick(b, Qt.LeftButton)
            pump()
            QTest.mouseClick(b, Qt.LeftButton)
            pump()
            dt2 = time.perf_counter() - t
            faulthandler.cancel_dump_traceback_later()
            if dt2 > 2:
                print(f"   SLOW {dt2:6.2f}s  {label!r} clicked twice more",
                      flush=True)
            if v is not None and getattr(v, "tool", None):
                QTest.keyClick(v, Qt.Key_Escape)
                QTest.keyClick(v, Qt.Key_Escape)
                pump()

    click_all("start page, no drawing")
    import make_sample
    pdf = os.path.join(TMP, "A-101.pdf")
    make_sample.make(pdf)
    w.open_path(pdf)
    pump(10)
    click_all("sample drawing open")
    big = os.path.join(os.path.expanduser("~"), "OneDrive", "Desktop",
                       "32410-004-IFC-Plant Drawings.pdf")
    if os.path.isfile(big):
        import shutil
        copy = os.path.join(TMP, "plant-copy.pdf")
        shutil.copy(big, copy)
        w.open_path(copy)
        pump(10)
        w._view.go_to(39)
        pump(10)
        click_all("copy of the plant set, page 40")
    print("done", flush=True)
    os._exit(0)


if __name__ == "__main__":
    main()
