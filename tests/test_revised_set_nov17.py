"""A revised set (Nov 17), made-up notes: what the new issue changed in the
work notes, sheet by sheet, and AI quantities counted in the revision
snapshot."""
import os
import sys

import fitz
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import callouts as co  # noqa: E402

try:
    from test_gui import win, qapp  # noqa: F401,E402
except Exception:                                         # noqa: BLE001
    pass


def blk(lines, sheet):
    return co.read_blocks([(lines, (0, 0, 9, 9))], sheet)


def old_set():
    return (blk(["INSTALL:", "2 - 6-INCH PLUG VALVE"], "C-1")
            + blk(["INSTALL:", "1 - 6-INCH PLUG VALVE"], "C-2")
            + blk(["REMOVE AND REPLACE:", "100 LF CHAIN LINK FENCE"], "C-7")
            + blk(["INSTALL:", "1 - 16-FOOT WIDE GATE"], "C-7"))


def new_set():
    return (blk(["INSTALL:", "2 - 6-INCH PLUG VALVE"], "C-1")
            + blk(["INSTALL:", "3 - 6 INCH PLUG VALVE"], "C-2")   # reworded
            + blk(["REMOVE AND REPLACE:", "112 LF CHAIN LINK FENCE"], "C-7")
            + blk(["INSTALL:", "1 - PIPE SUPPORT"], "C-9"))


def test_compare_lists_what_moved_and_where():
    rows = co.compare(old_set(), new_set())
    by = {r["what"]: r for r in rows}
    valve = next(r for r in rows if "PLUG VALVE" in r["what"])
    assert (valve["before"], valve["after"], valve["change"]) == (3, 5, 2)
    assert valve["kind"] == "changed" and valve["sheets"] == [("C-2", 2)]
    fence = next(r for r in rows if "FENCE" in r["what"])
    assert fence["change"] == 12 and fence["sheets"] == [("C-7", 12)]
    gate = next(r for r in rows if "GATE" in r["what"])
    assert gate["kind"] == "removed" and gate["after"] == 0
    sup = next(r for r in rows if "PIPE SUPPORT" in r["what"])
    assert sup["kind"] == "added" and sup["sheets"] == [("C-9", 1)]
    assert len(by) == 4
    assert rows[0]["change"] == 12                 # biggest change first
    text = co.compare_text(rows)
    assert any(t.startswith("+12 LF") and "(C-7: +12)" in t for t in text)
    assert any("(gone)" in t for t in text)


def test_same_set_no_change():
    assert co.compare(old_set(), old_set()) == []


def test_ai_quantities_in_the_revision_snapshot():
    from app import ai_quantities as aq, revisions
    d = fitz.open()
    d.new_page()
    aq.store(d, {"quantities": [{"engine": "steel", "name": "W8x10 beams",
                                 "qty": 100.0, "unit": "LB",
                                 "status": "taken off", "page": 0}]})
    before = revisions.snapshot(d)
    assert before["quantities"]["W8x10 beams|LB"] == 100.0
    aq.store(d, {"quantities": [{"engine": "steel", "name": "W8x10 beams",
                                 "qty": 140.0, "unit": "LB",
                                 "status": "taken off", "page": 0}]})
    ch = revisions.changes(before, revisions.snapshot(d))
    q = [x for x in ch["quantities"] if x["group"] == "W8x10 beams"]
    assert q and q[0]["change"] == 40.0


def test_the_window_compares(win, tmp_path, monkeypatch):
    from app import callout_scope as cs, callouts_ui as cu
    p_new, p_old = tmp_path / "new.pdf", tmp_path / "old.pdf"
    for p in (p_new, p_old):
        d = fitz.open()
        d.new_page()
        d.save(p)
    dlg = cu.WorkNotesDialog(str(p_new), win)
    assert dlg.compare(str(p_old)) is None          # nothing read yet
    dlg.rows = new_set()
    monkeypatch.setattr(cs, "read_set", lambda path, text="", **k:
                        (old_set(), {}))
    rows = dlg.compare(str(p_old))
    assert len(rows) == 4
    assert dlg.tabs.currentIndex() == dlg.changes_at
    assert dlg.changes.rowCount() == 4
    assert "4 work-note total(s) changed" in dlg.status.text()
    dlg.close()
