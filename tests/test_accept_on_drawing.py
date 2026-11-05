"""Nov 1: accept or deny AI takeoff right on the drawing - select a
dashed AI markup and press A (accept) or D (deny), or right-click.
With the AI Takeoff run's result open, a room's CHECK item is decided
with its outline (as the Review Queue does)."""
import os

import pytest

fitz = pytest.importorskip("fitz")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent  # noqa: E402

from app import annotate  # noqa: E402
from test_gui import win, qapp  # noqa: E402,F401

PPU = 10.0


def _ai_area(v, group="OFFICE 101", x=300, method="AI takeoff: rooms"
             + annotate.REVIEW_SUFFIX):
    v.apply_marks([(v.page, "set_scale", {"ppu": PPU, "unit": "ft"})])
    v.apply_marks([(v.page, "add_polygon", {
        "pts": [[x, 300], [x + 50, 300], [x + 50, 350], [x, 350]],
        "label": f"{group}: 25 sq ft", "badge": True, "dashes": [4, 3],
        "measure": {"type": "area", "value": 25.0, "unit": "sq ft",
                    "group": group, "method": method}})])
    return _find(v, group)


def _find(v, group):
    for a in annotate.iter_annots(v.pg):
        if (a.info or {}).get("subject", "").endswith(":" + group) and \
                annotate.reshapable(v.doc, a):
            return a
    return None


def _state(v, group):
    a = _find(v, group)
    if a is None:
        return None
    return (annotate.status_of(v.doc, a), annotate.is_pending(v.doc, a))


def _key(v, k):
    ov = QKeyEvent(QEvent.ShortcutOverride, k, Qt.NoModifier, "a")
    took = v.event(ov)
    v.keyPressEvent(QKeyEvent(QEvent.KeyPress, k, Qt.NoModifier, "a"))
    return took


def test_a_accepts_the_selected_ai_markup(win):
    v = win._view
    v.select(_ai_area(v))
    assert v.ai_open_refs()
    assert _key(v, Qt.Key_A)                 # taken before the tool keys
    assert _state(v, "OFFICE 101") == ("Accepted", False)
    assert not annotate.is_badge(v.doc, _find(v, "OFFICE 101")) and \
        not [a for a in v.pg.annots() if annotate.is_badge(v.doc, a)]
    assert any(it["group"] == "OFFICE 101"
               for it in annotate.totals_items(v.doc))  # in the totals now
    win.undo()
    assert _state(v, "OFFICE 101")[1]                    # pending again


def test_d_denies(win):
    v = win._view
    v.select(_ai_area(v))
    _key(v, Qt.Key_D)
    assert _state(v, "OFFICE 101") is None
    win.undo()
    assert _state(v, "OFFICE 101") is not None


def test_keys_left_alone_for_hand_markups(win):
    v = win._view
    v.select(_ai_area(v, "MINE", method="manual"))
    assert v.ai_open_refs() == []
    ov = QKeyEvent(QEvent.ShortcutOverride, Qt.Key_A, Qt.NoModifier, "a")
    ov.ignore()
    v.event(ov)
    assert not ov.isAccepted()                # the tool key keeps working
    assert v.decide_selected(True) == 0


def test_several_selected_one_step(win):
    v = win._view
    _ai_area(v, "R1", x=100)
    _ai_area(v, "R2", x=200)
    v.select(_find(v, "R1"))           # (an annot doesn't outlive its page)
    v.select(_find(v, "R2"), add=True)
    assert len(v.ai_open_refs()) == 2
    assert v.decide_selected(True) == 2
    assert _state(v, "R1") == ("Accepted", False) == _state(v, "R2")
    win.undo()
    assert _state(v, "R1")[1] and _state(v, "R2")[1]


def test_with_the_run_open_the_room_check_item_is_decided_too(win):
    v = win._view
    a = _ai_area(v, "OFFICE 101")

    class Dlg:
        result = {"review": [{"engine": "rooms", "page": v.page,
                              "name": "OFFICE 101", "qty": 25.0,
                              "unit": "SF", "why": "trace +6%"}],
                  "quantities": []}
    win._ai_dlg = Dlg()
    v.select(a)
    assert v.decide_selected(True) == 1
    assert Dlg.result["review"] == []                    # decided with it
    assert any(q.get("name") == "OFFICE 101" and q.get("reviewed")
               for q in Dlg.result["quantities"])
    assert _state(v, "OFFICE 101") == ("Accepted", False)
