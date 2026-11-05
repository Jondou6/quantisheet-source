"""Calibrate dialog, length parsing, Open Recent, window memory."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import takeoff                                    # noqa: E402
from test_gui import win, qapp                              # noqa: E402,F401


@pytest.mark.parametrize("text, expected", [
    ("4'-6\"", (4.5, "ft")), ("4' 6 1/2\"", (4 + 6.5 / 12, "ft")),
    ("4ft 6in", (4.5, "ft")), ("54\"", (54.0, "in")), ("1.2 m", (1.2, "m")),
    ("12.5", (12.5, None)), ("4’-0”", (4.0, "ft")),
    ("1200mm", (1200.0, "mm")), ("abc", None), ("", None),
])
def test_parse_length(text, expected):
    got = takeoff.parse_length(text)
    if expected is None:
        assert got is None
    else:
        assert got[1] == expected[1]
        assert got[0] == pytest.approx(expected[0])


def test_calibrate_dialog(win):
    from PySide6.QtWidgets import QDialogButtonBox
    from app.calibrate_dialog import CalibrateDialog
    d = CalibrateDialog(144, 5, win)            # a 2" line on paper
    d.length.setText("4'-6\"")
    assert d.values() == (4.5, "ft", False)
    assert '1" on paper = 2.25 ft' in d.preview.text()
    d.all_pages.setChecked(True)
    d.length.setText("3 m")
    assert d.values() == (3.0, "m", True)
    assert d.unit.currentText() == "m"         # follows what was typed
    d.length.setText("nonsense")
    assert d.values() is None
    assert not d.bb.button(QDialogButtonBox.Ok).isEnabled()


def test_calibrate_uses_one_dialog(win, monkeypatch):
    from app import calibrate_dialog
    calls = []

    def fake(parent, dist, pages):
        calls.append((round(dist), pages))
        return (4.5, "ft", False)
    monkeypatch.setattr(calibrate_dialog, "ask_calibration", fake)
    v = win._view
    assert v.calibrate(72.0)
    assert calls == [(72, v.doc.page_count)]
    assert v.scale()["unit"] == "ft"
    assert v.scale()["ppu"] == pytest.approx(16.0)


def test_open_recent_and_window_memory(win, tmp_path):
    from app import settings
    win._fill_recent()
    names = [a.text() for a in win.recent_menu.actions()]
    assert any("plan.pdf" in n for n in names)
    win._save_window_state()
    saved = settings.get("window")
    assert saved and saved["geometry"]


def test_ctrl_wheel_zooms_at_cursor(win):
    from PySide6.QtCore import QPoint
    v = win._view
    before = v.zoom
    win._zoom_at(1.15, QPoint(200, 150))
    assert v.zoom == pytest.approx(before * 1.15)
    win._zoom_at(1 / 1.15, QPoint(200, 150))
    assert v.zoom == pytest.approx(before)


def test_real_ctrl_wheel_event_zooms(win):
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtWidgets import QApplication
    v = win._view
    before = v.zoom
    ev = QWheelEvent(QPointF(100, 100), QPointF(100, 100), QPoint(0, 0),
                     QPoint(0, 120), Qt.NoButton, Qt.ControlModifier,
                     Qt.NoScrollPhase, False)
    QApplication.sendEvent(v, ev)
    assert win._view.zoom == pytest.approx(before * 1.15)
