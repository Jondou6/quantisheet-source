"""Chief's v23-v26 wired into the window: the measurement bar and snap chip
in the status bar (only while measuring), snap modes, Field Mode (Ctrl+5),
Undo Steps, and the triage controls on the Count Symbol review."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz                                                   # noqa: E402
from test_gui import win, qapp                                # noqa: E402,F401


def test_measure_bar_shows_only_while_measuring_and_typed_length(win):
    v = win._view
    assert v.calibrate(240.0, real=24, unit="ft", all_pages=False)  # 10/ft
    assert win.measure_bar.isHidden() and win.chip_snap.isHidden()
    win.set_tool("measure_polylength")
    assert not win.measure_bar.isHidden() and not win.chip_snap.isHidden()
    assert win.chip_snap.text().startswith("Snap: END")
    # first point placed, cursor off to the right: type 12'6
    v._pts = [fitz.Point(100, 100)]
    v._mouse = fitz.Point(180, 100)
    v.update_measure_bar()
    assert "Length" in win.measure_bar.readout.text()
    win.measure_bar.entry.setText("12'6")
    win.measure_bar._enter()
    assert len(v._pts) == 2 and abs(v._pts[1].x - 225) < 0.01
    win.measure_bar.add_requested.emit()          # Add to takeoff
    assert v._pts == []
    from app import annotate
    items = [i for i in annotate.takeoff_items(v.doc)
             if i["type"] == "length"]
    assert items and abs(items[-1]["value"] - 12.5) < 0.01
    win.set_tool("select") if "select" in win._tool_actions else \
        win.set_tool(None)
    assert win.measure_bar.isHidden()


def test_bar_says_when_there_is_no_scale(win):
    v = win._view
    v.set_tool("measure_polylength")       # the window asks first: no scale
    v.measure_bar = win.measure_bar
    v._pts = [fitz.Point(100, 100)]
    v._mouse = fitz.Point(180, 100)
    v.update_measure_bar()
    assert "No scale" in win.measure_bar.readout.text()
    assert v.bar_commit(5.0) is False and len(v._pts) == 1


def test_snap_modes_menu_updates_views_and_settings(win):
    from app import settings
    win._snap_mode_actions["MID"].setChecked(False)
    assert "MID" not in win._view._snap_modes
    assert "MID" not in settings.get("snap_modes")
    assert "MID" not in win.chip_snap.text()
    win._snap_mode_actions["MID"].setChecked(True)
    assert "MID" in win._view._snap_modes


def test_field_mode_and_density(win):
    bar = win.active_ribbon_bar()
    bar.show()
    win._field_action.trigger()
    assert win.field_mode.on and bar.isHidden()
    assert "min-height: 40px" in win.styleSheet()
    win._field_action.trigger()
    assert not win.field_mode.on and not bar.isHidden()
    assert win.styleSheet() == ""
    win.set_density("compact")
    assert "min-height: 24px" in win.styleSheet()
    win.set_density("comfortable")
    assert win.styleSheet() == ""


def test_undo_steps_setting(win):
    assert win.set_undo_steps(50) == 50
    assert win._view.history.limit == 50
    win.set_undo_steps(0)
    assert win._view.history.limit >= 10 ** 9


def test_count_review_gets_triage_controls(qapp):
    from PySide6.QtCore import Qt
    from app import count_triage
    from app import autocount as autocount_boost
    d = fitz.open()
    d.new_page()
    hits = [{"page": 0, "rect": [10 + 30 * i, 10, 30 + 30 * i, 30],
             "score": s, "band": "high" if s >= 0.9 else "review"}
            for i, s in enumerate((0.97, 0.85, 0.75, 0.5))]
    dlg = autocount_boost.CountReviewDialog(d, hits, "Outlets")
    t = count_triage.attach(dlg, accept=0.92, reject=0.6)
    checked = lambda: [dlg.list.item(i).checkState() == Qt.Checked
                       for i in range(dlg.list.count())]
    # dialog lists lowest score first: 0.5, 0.75, 0.85, 0.97
    assert checked() == [False, False, False, True]
    dlg.accept_slider.setValue(80)                 # 0.85 now auto-accepted
    assert checked() == [False, False, True, True]
    # Y on the current (doubtful) one keeps it whatever the sliders do
    dlg.list.setCurrentRow(1)
    assert dlg.triage_key("Y")
    dlg.accept_slider.setValue(99)
    assert checked()[1] is True and checked()[2] is False
    assert "match" in dlg.why_label.text()
    assert len(dlg.accepted()) == len(t.accepted())
