"""Single-page Auto Takeoff finds its candidates on a worker thread, on a
copy of the drawing, so the window keeps drawing while it runs."""
import os
import threading
import time

import fitz

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer                              # noqa: E402
from PySide6.QtWidgets import QApplication                     # noqa: E402

from app import autotakeoff_review as atr                      # noqa: E402


def test_collect_runs_off_the_gui_thread(monkeypatch):
    app = QApplication.instance() or QApplication([])
    doc = fitz.open()
    doc.new_page(width=300, height=200)
    seen = {}

    def slow(d, pno, scale, types, height=None, sides=2):
        seen["thread"] = threading.current_thread()
        seen["same_doc"] = d is doc
        time.sleep(0.6)
        return [{"id": 0, "type": "rooms", "group": "Office", "value": 1.0}]
    monkeypatch.setattr(atr, "collect", slow)
    ticks = []
    t = QTimer()
    t.timeout.connect(lambda: ticks.append(1))
    t.start(50)
    got = atr.collect_in_background(None, doc, 0, {"ppu": 1.0, "unit": "ft"},
                                    ("rooms",), None, 2)
    t.stop()
    assert got and got[0]["group"] == "Office"
    assert seen["thread"] is not threading.main_thread()
    assert seen["same_doc"] is False            # a copy, not the open one
    assert len(ticks) >= 5                       # the window kept running


def test_collect_error_comes_back(monkeypatch):
    app = QApplication.instance() or QApplication([])
    doc = fitz.open()
    doc.new_page()

    def bad(*a, **k):
        raise RuntimeError("scale too small")
    monkeypatch.setattr(atr, "collect", bad)
    try:
        atr.collect_in_background(None, doc, 0, {"ppu": 1.0}, ("rooms",),
                                  None, 2)
    except atr.AutoTakeoffFailed as e:
        assert "scale too small" in str(e)
    else:
        raise AssertionError("no error")
