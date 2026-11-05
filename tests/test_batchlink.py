"""Batch Link: sheet references become links to their sheets."""
import os

import fitz

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QMessageBox                    # noqa: E402

from app import batchlink                                    # noqa: E402
from test_gui import win, qapp                               # noqa: E402,F401

SHEETS = [("A-101", "FLOOR PLAN"), ("A-501", "DETAILS"),
          ("S-201", "FRAMING PLAN")]


def _set():
    d = fitz.open()
    for num, title in SHEETS:
        p = d.new_page(width=1224, height=792)
        p.draw_rect(fitz.Rect(1030, 640, 1210, 780))
        p.insert_text((1040, 700), title, fontsize=10)
        p.insert_text((1040, 760), num, fontsize=24)
    p = d[0]
    p.insert_text((200, 300), "3/A-501", fontsize=9)
    p.insert_text((200, 340), "SEE S-201 FOR FRAMING", fontsize=9)
    p.insert_text((200, 380), "A-101", fontsize=9)       # itself: no link
    d[2].insert_text((300, 300), "SIM. 5/A-501.", fontsize=9)
    return d


def test_find_and_link():
    d = _set()
    smap = batchlink.sheet_map(d)
    assert smap == {"A101": 0, "A501": 1, "S201": 2}
    assert batchlink.norm("a501") == batchlink.norm("A-501")
    refs = batchlink.find_refs(d, smap)
    got = sorted((r["page"], r["target"]) for r in refs)
    assert got == [(0, 1), (0, 2), (2, 1)]
    assert batchlink.link_all(d, refs) == 3
    assert batchlink.link_all(d) == 0                    # nothing new
    links = d[0].get_links()
    assert sorted(ln["page"] for ln in links) == [1, 2]
    # other links are left alone by Remove
    d[1].insert_link({"kind": fitz.LINK_URI, "from": fitz.Rect(10, 10, 50,
                      20), "uri": "https://example.com"})
    assert batchlink.remove_all(d) == 3
    assert d[0].get_links() == []
    assert len(d[1].get_links()) == 1


def test_link_sheets_in_app_and_click(qapp, win, tmp_path, monkeypatch):
    path = str(tmp_path / "set.pdf")
    _set().save(path)
    win.open_path(path)
    v = win._view
    assert win.batch_link() == 3
    assert v.doc[0].get_links()
    ln = v.link_at(fitz.Rect(v.doc[0].get_links()[0]["from"]).tl + (1, 1))
    assert ln is not None
    win.follow_link(ln)
    assert v.page == ln["page"]
    assert win.previous_view()
    assert v.page == 0
    win.undo()
    assert v.doc[0].get_links() == []
    # web links ask first
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.No))
    assert not win.follow_link({"kind": fitz.LINK_URI,
                                "uri": "https://example.com"})
