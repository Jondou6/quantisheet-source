"""Nov 2: Edit > Undo after counts added in one step (Count Library, Count
the Uncounted Copies, Count by Label) takes them all off again - with a
symbol drawn on the page and a sample kept in the PDF beforehand, as in
real use."""
import os

import pytest

fitz = pytest.importorskip("fitz")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import annotate, autocount  # noqa: E402
from test_gui import win, qapp  # noqa: E402,F401

SPOTS = [(380, 450), (460, 450), (540, 450)]


def _n(v, group):
    return sum(1 for it in annotate.takeoff_items(v.doc)
               if it["group"] == group)


def _marks(v, group):
    hits = [{"page": v.page, "rect": [x - 8, y - 8, x + 8, y + 8],
             "score": 0.9} for x, y in SPOTS]
    return autocount.count_marks(hits, group, v.doc)


def test_plain(win):
    v = win._view
    assert v.apply_marks(_marks(v, "A")) == 3 and _n(v, "A") == 3
    win.undo()
    assert _n(v, "A") == 0


def test_after_another_markup(win):
    """A markup made just before (through the program, as every tool does)
    stays; only the counts come off. (Drawing straight into the page's
    contents with PyMuPDF, outside the program's undo history, is not
    something any tool does - the Nov 1 window test did that, which is
    why its Undo check failed there.)"""
    v = win._view
    v.apply_marks([(v.page, "add_rect", {"rect": [100, 600, 160, 640]})])
    rects = len(list(v.doc[v.page].annots()))
    assert v.apply_marks(_marks(v, "B")) == 3
    win.undo()
    assert _n(v, "B") == 0
    assert len(list(v.doc[v.page].annots())) == rects


def test_after_a_sample_is_kept(win):
    from app import uncounted
    v = win._view
    uncounted.save_sample(v.doc, "C", b"\x89PNG fake")
    assert v.apply_marks(_marks(v, "C")) == 3
    win.undo()
    assert _n(v, "C") == 0


def test_review_counts_like_the_library(win):
    from app import count_library
    v = win._view
    kept = {"D": [{"page": v.page, "rect": [x - 8, y - 8, x + 8, y + 8],
                   "score": 0.9} for x, y in SPOTS]}
    assert v.apply_marks(count_library.review_marks(kept, v.doc)) == 3
    win.undo()
    assert _n(v, "D") == 0
