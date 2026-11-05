"""Bookmarks in combined spec books."""
import os

import fitz

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.docks import bookmark_targets          # noqa: E402

# what get_toc(simple=False) returns for a combined spec book: one entry per
# original file with an empty destination, then the real sections
TOC = [
    [1, "Specs.pdf", 1, {"kind": 1, "page": 0, "to": fitz.Point(0, 1)}],
    [2, "033000.pdf", 1, {"kind": 1, "page": 0, "to": fitz.Point(0, 1)}],
    [3, "SECTION 033000", 4, {"kind": 1, "page": 3, "to": fitz.Point(72, 300)}],
    [2, "Details.pdf", -1, {"kind": 0, "page": -1}],
    [3, "Sheets", -1, {"kind": 0, "page": -1}],
    [4, "PART 1", 5, {"kind": 1, "page": 4, "to": fitz.Point(72, 150)}],
]


class _Doc:
    is_closed = False

    def get_toc(self, simple=True):
        return TOC if not simple else [e[:3] for e in TOC]


def test_empty_file_bookmarks_go_to_first_section():
    t = bookmark_targets(TOC)
    assert t[0][0] == 1                      # the book itself: page 1
    assert t[1] == (4, 300)                  # borrowed from its child
    assert t[2] == (4, 300)
    assert t[3] == (5, 150) and t[4] == (5, 150)   # through two levels


def test_panel_click_goes_to_section():
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from app.docks import BookmarksPanel
    p = BookmarksPanel()
    p.set_doc(_Doc())
    hits = []
    p.go_spot.connect(lambda pg, y: hits.append((pg, round(y))))
    p.go_page.connect(lambda pg: hits.append((pg, None)))
    p._clicked(p.tree.topLevelItem(0).child(0), 0)
    assert hits[-1] == (3, 300)              # 0-based page index
