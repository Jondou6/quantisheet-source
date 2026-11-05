"""v14: Lock Bid Set toggle - while locked the takeoff is read-only."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest                                                 # noqa: E402
from app import annotate, bidlock, prebid                     # noqa: E402
from test_gui import win, qapp, ANSWERS                       # noqa: E402,F401


class _OK:
    ok = True


def _takeoff(v):
    v.apply_marks([(0, "add_polyline", {
        "pts": [[60, 300], [290, 300]],
        "measure": {"type": "length", "value": 12.0, "unit": "ft",
                    "group": "Wall"}})])
    return [a for a in v.doc[0].annots()
            if (a.info or {}).get("subject", "").startswith(annotate.TAKEOFF)]


def test_blocked_kinds():
    assert bidlock.blocks("add_count", {"pt": [1, 1]})
    assert bidlock.blocks("set_scale", {"ppu": 2})
    assert bidlock.blocks("add_rect", {"rect": [0, 0, 9, 9],
                                       "measure": {"type": "area"}})
    assert not bidlock.blocks("add_rect", {"rect": [0, 0, 9, 9]})


def test_locked_bid_refuses_takeoff_edits_but_allows_notes(win):
    bidlock.install(win)
    v = win._view
    tk = _takeoff(v)
    assert tk
    prebid.lock(v.doc, 1000, report=_OK())
    assert bidlock.is_locked(v.doc)
    n = len(list(v.doc[0].annots()))
    v.apply_marks([(0, "add_polyline", {
        "pts": [[60, 100], [290, 100]],
        "measure": {"type": "length", "value": 9.0, "unit": "ft"}})])
    v.apply_marks([(0, "delete_annot", annotate.ref(tk[0]))])
    assert len(list(v.doc[0].annots())) == n          # nothing changed
    assert prebid.lock_state(v.doc)["stale"] is False
    v.apply_marks([(0, "add_rect", {"rect": [10, 10, 40, 40]})])
    assert len(list(v.doc[0].annots())) == n + 1      # plain markup ok
    v.apply_marks([(0, "set_annot", dict(annotate.ref(tk[0]),
                                         status="Accepted"))])
    assert annotate.status_of(v.doc, tk[0]) == "Accepted"
    assert "locked" in bidlock.banner_text(v.doc).lower()


def test_toggle_unlocks_with_reason_then_relocks(win, monkeypatch):
    bidlock.install(win)
    v = win._view
    prebid.lock(v.doc, 1000, report=_OK())
    ANSWERS["text"] = "Addendum 3"
    assert bidlock.toggle(win) == "unlocked"
    assert not bidlock.is_locked(v.doc)
    log = prebid.read(v.doc)["log"]
    assert log[-1]["action"] == "unlocked" and log[-1]["reason"] == "Addendum 3"
    _takeoff(v)                                       # editable again
    monkeypatch.setattr(prebid, "check", lambda d: _OK())
    assert bidlock.toggle(win) == "locked"
    assert bidlock.is_locked(v.doc)


def test_unlock_needs_reason(win):
    bidlock.install(win)
    v = win._view
    prebid.lock(v.doc, 1000, report=_OK())
    ANSWERS["text"] = "   "
    assert bidlock.toggle(win) is None
    assert bidlock.is_locked(v.doc)


def test_toggle_refuses_lock_when_checklist_not_ready(win):
    bidlock.install(win)
    v = win._view
    v.apply_marks([(0, "add_rect", {"rect": [10, 10, 40, 40]})])
    assert bidlock.toggle(win) is None                # open markup: not ready
    assert not bidlock.is_locked(v.doc)
