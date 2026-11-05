"""v13: Ctrl+Z removes one point at a time while drawing, then undoes
document steps - one undo list for everything, with a history list."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz                                                   # noqa: E402
from app import history as undo_boost  # was undo_boost (folded Nov 4)  # noqa: E402
from test_gui import win, qapp                                # noqa: E402,F401


def _pt(x, y):
    return fitz.Point(x, y)


def test_ctrl_z_pops_points_then_redo_puts_them_back(win):
    undo_boost.install(win)
    v = win._view
    v._pts = [_pt(10, 10), _pt(50, 10), _pt(50, 60)]
    pos = v.history.pos
    win.undo()
    assert len(v._pts) == 2 and v.history.pos == pos   # doc untouched
    win.undo()
    assert len(v._pts) == 1
    win.redo()
    assert len(v._pts) == 2 and v._pts[-1] == _pt(50, 10)
    win.undo()
    win.undo()
    assert v._pts == []


def test_undo_falls_through_to_document_steps(win):
    undo_boost.install(win)
    v = win._view
    n0 = len(list(v.doc[0].annots()))
    v.apply_marks([(0, "add_rect", {"rect": [20, 20, 80, 80]})])
    assert len(list(v.doc[0].annots())) == n0 + 1
    v._pts = []
    win.undo()
    assert len(list(win._view.doc[0].annots())) == n0


def test_new_point_clears_point_redo(win):
    undo_boost.install(win)
    v = win._view
    v._pts = [_pt(1, 1), _pt(2, 2)]
    win.undo()
    v._pts.append(_pt(9, 9))
    win.redo()                     # nothing to redo for points now
    assert v._pts[-1] == _pt(9, 9) and len(v._pts) == 2


def test_history_list_and_go_back(win):
    undo_boost.install(win)
    v = win._view
    for k in range(3):
        v.apply_marks([(0, "add_rect", {"rect": [10 + k * 30, 10,
                                                  30 + k * 30, 30]})])
    v._pts = [_pt(5, 5)]
    rows = undo_boost.history_rows(win)
    assert rows[0]["kind"] == "points" and rows[0]["label"].startswith("1 point")
    steps = [r for r in rows if r["kind"] != "points"]
    assert len(steps) >= 3 and steps[0]["current"]
    pos = v.history.pos
    undo_boost.go_back(win, 2)       # 2 document steps back (points first)
    assert win._view._pts == []
    assert win._view.history.pos == pos - 2
    cur = [r for r in undo_boost.history_rows(win) if r["current"]]
    assert cur[0]["index"] == pos - 2
    assert "(undone)" in undo_boost.history_rows(win)[0]["label"]


def test_install_rewires_ctrl_z_action(win):
    undo_boost.install(win)
    from PySide6.QtGui import QAction
    acts = [a for a in win.findChildren(QAction) if a.text() == "Undo"]
    assert acts
    v = win._view
    v._pts = [_pt(1, 1), _pt(2, 2)]
    acts[0].trigger()
    assert len(v._pts) == 1
