"""Nov 18: after Rotate All, Link Sheets and Unlink Sheets the drawing
area went blank until the view was refitted - a reset of the page cache
right after a redraw dropped the drawing it had just asked for. Now a
reset that leaves the sheet blank draws it again. Made-up sheets."""
import os

import pytest

fitz = pytest.importorskip("fitz")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from test_gui import win, qapp  # noqa: E402,F401


def made_up(path, n=3):
    d = fitz.open()
    for i in range(n):
        p = d.new_page(width=1224, height=792)
        p.insert_text((1100, 760), f"A-10{i + 1}", fontsize=16)
        p.insert_text((100, 100), f"SEE A-10{(i + 1) % n + 1}", fontsize=12)
    d.save(path)
    return str(path)


def settle(n=20):
    for _ in range(n):
        QApplication.processEvents()


def test_a_reset_that_leaves_the_sheet_blank_draws_it_again(win, tmp_path):
    assert win.open_path(made_up(tmp_path / "set.pdf"))
    v = win._view
    settle()
    v.rendered = None                   # as if waiting for the drawing
    v.reset_page_cache()
    settle()
    assert v.rendered is not None


def test_link_unlink_and_rotate_all_leave_a_drawing(win, tmp_path):
    assert win.open_path(made_up(tmp_path / "set2.pdf"))
    v = win._view
    settle()
    win.batch_link()
    settle()
    assert v.rendered is not None
    win.batch_link(remove=True)
    settle()
    assert v.rendered is not None
    win._page_action("rotate_right", list(range(v.doc.page_count)))
    settle()
    assert v.rendered is not None
