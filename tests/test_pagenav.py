"""Acrobat-style page bar and pages drawn ahead for instant page turns."""
import os

import fitz

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import annotate                                     # noqa: E402
from test_gui import win, qapp                               # noqa: E402,F401


def _doc(path, n=5):
    d = fitz.open()
    for i in range(n):
        d.new_page().insert_text((72, 72), f"PAGE {i + 1}", fontsize=30)
    d.save(path)
    return path


def test_page_bar(qapp, win, tmp_path):
    win.open_path(_doc(str(tmp_path / "five.pdf")))
    v = win._view
    nav = win.page_nav
    qapp.processEvents()
    assert not nav.isHidden() and nav.count.text() == "/ 5"
    assert not nav.prev_b.isEnabled() and nav.next_b.isEnabled()
    nav.next()
    assert v.page == 1 and nav.page_box.text() == "2"
    nav.last()
    assert v.page == 4 and not nav.next_b.isEnabled()
    nav.page_box.setText("3")
    nav._typed()
    assert v.page == 2
    nav.first()
    assert v.page == 0
    win.command("Last Page").trigger()
    assert v.page == 4
    z = v.zoom
    win._zoom(1.25)
    assert nav.zoom_lbl.text() == f"{v.zoom * 100:.0f}%" and v.zoom > z


def test_pages_drawn_ahead(qapp, win, tmp_path):
    win.open_path(_doc(str(tmp_path / "ahead.pdf")))
    v = win._view
    v.go_to(1)
    v._prefetch()                   # what the idle timer does
    v._prefetch()
    pages = {k[1] for k in v._prefetched}
    assert {0, 1, 2} <= pages
    cached = [val[0] for k, val in v._prefetched.items() if k[1] == 2][0]
    v.next_page()
    assert v.rendered is cached     # no new render: instant
    # an edit forgets pages drawn before it
    v.apply_marks([(2, "add_rect", {"rect": [100, 100, 200, 200]})])
    assert not any(k[1] == 2 and k[4] < v._edits for k in v._prefetched)
    assert len(list(v.doc[2].annots())) == 1
