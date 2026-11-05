"""Takeoff keys (one-key takeoff tools) and the unpriced-markup chip."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import annotate                                       # noqa: E402
from app import quickaccess as wb  # was workflow_boost (folded Nov 4)  # noqa: E402
from test_gui import win, qapp                                # noqa: E402,F401


def test_takeoff_keys_swap_and_restore(win):
    b = wb.install_takeoff_keys(win)
    acts = win._tool_actions
    assert acts["add_line"].shortcut().toString() == "L"
    b.set_takeoff_keys(True)
    assert acts["measure_length"].shortcut().toString() == "L"
    assert acts["measure_area"].shortcut().toString() == "A"
    assert acts["count"].shortcut().toString() == "C"
    assert acts["calibrate"].shortcut().toString() == "S"
    # no two actions share a key (Qt would fire neither)
    keys = [a.shortcut().toString() for a in acts.values() if a.shortcut().toString()]
    assert len(keys) == len(set(keys))
    assert "Takeoff" in b.keys_chip.text()
    b.set_takeoff_keys(False)
    assert acts["add_line"].shortcut().toString() == "L"
    assert acts["measure_length"].shortcut().toString() == "Shift+L"


def test_unpriced_chip_counts_open_markups(win):
    b = wb.install_takeoff_keys(win)
    b.refresh_unpriced(now=True)
    before = b.unpriced_count
    annotate.apply_op(win._view.doc, annotate.new_op(
        "add_cloud", 0, rect=[100, 100, 200, 200]))
    win.quantities.refresh()            # counted just after (Nov 3) ...
    assert b._unpriced_queued
    b._count_unpriced()                 # ... as the timer does
    assert b.unpriced_count == before + 1
    assert f"{b.unpriced_count} unpriced" in b.unpriced_chip.text()
    b.unpriced_chip.click()
    assert win.unpriced_act.isChecked()
