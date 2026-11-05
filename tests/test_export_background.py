"""Exports run on a worker thread, so the window keeps working
(review 0.12.29 step 9: Excel held the window 25 s, DXF 14 s)."""
import os
import time

import pytest

from test_gui import win, qapp                                 # noqa: F401


def _wait(pred, timeout=30.0):
    from PySide6.QtWidgets import QApplication
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        QApplication.processEvents()
        if pred():
            return True
        time.sleep(0.02)
    return False


def test_excel_export_does_not_block_the_window(win, monkeypatch, tmp_path):
    from app import acrobat
    out = str(tmp_path / "slow.xlsx")

    def slow(doc, path):
        time.sleep(1.5)
        open(path, "wb").write(b"x")
        return 1
    monkeypatch.setattr(acrobat, "export_excel", slow)
    monkeypatch.setattr(win, "_ask_save", lambda *a, **k: out)
    t = time.monotonic()
    assert win.export_as("xlsx") == out
    assert time.monotonic() - t < 1.0            # returned before the work
    assert _wait(lambda: os.path.exists(out))


def test_dxf_export_does_not_block_the_window(win, monkeypatch, tmp_path):
    from app import dxf
    out = str(tmp_path / "slow.dxf")

    def slow(doc, page, path):
        time.sleep(1.5)
        open(path, "w").write("0\nEOF\n")
        return {"entities": 1, "units": "ft"}
    monkeypatch.setattr(dxf, "from_page", slow)
    t = time.monotonic()
    assert win.export_dxf(out) == out
    assert time.monotonic() - t < 1.0
    assert _wait(lambda: os.path.exists(out))


def test_flashed_message_is_not_overwritten_by_the_tool_hint(win):
    win._flash("Generated 12 sheets - FOR REVIEW", 15000)
    win._update_status()
    assert "Generated 12 sheets" in win.statusBar().currentMessage()


def test_theme_switch_shows_a_wait_cursor(win, monkeypatch):
    from PySide6.QtWidgets import QApplication
    from app import theme
    seen = []
    monkeypatch.setattr(theme, "apply", lambda app, mode, save=True:
                        seen.append(QApplication.overrideCursor() is not None))
    monkeypatch.setattr(QApplication, "overrideCursor",
                        QApplication.overrideCursor)
    win.set_theme("dark")
    assert seen == [True]
    assert QApplication.overrideCursor() is None
