"""Every ribbon box sits at the same height (Jon, Oct 20: the View group's
buttons sat lower than File / Tools / Compare)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint                              # noqa: E402

from app.ribbon import RibbonButton                            # noqa: E402
from test_gui import win, qapp                                 # noqa: E402,F401


def test_large_buttons_share_one_top(win):
    win.resize(1900, 900)
    win.show()
    rb = win.ribbon
    for name in list(rb.pages):
        rb.show_page(name)
        win.repaint()
        page = rb.pages[name]
        page.widget().layout().activate()
        tops, heights = set(), set()
        for g in page.groups.values():
            g.layout().activate()
            for b in g.buttons:
                if isinstance(b, RibbonButton) and b.isVisibleTo(page):
                    tops.add(b.mapTo(page.widget(), QPoint(0, 0)).y())
                    heights.add(b.height())
        assert len(tops) <= 1, (name, sorted(tops))
        assert len(heights) <= 1, (name, sorted(heights))


def test_wide_tab_shows_more_arrows(qapp):
    """GUI user test r42 F04: a tab wider than the window hid its last
    buttons; arrows at the edge now say there's more and scroll to it."""
    from PySide6.QtGui import QAction
    from app.ribbon import Ribbon
    rb = Ribbon()
    pg = rb.page("Wide")
    for i in range(40):
        a = QAction(f"Button number {i}", rb)
        pg.group(f"G{i}").large(a)
    rb.resize(500, 160)
    rb.show()
    rb.show_page("Wide")
    qapp.processEvents()
    assert pg.more_right.isVisible() and not pg.more_left.isVisible()
    pg.scroll_by_page(1)
    qapp.processEvents()
    assert pg.more_left.isVisible()
    pg.horizontalScrollBar().setValue(pg.horizontalScrollBar().maximum())
    qapp.processEvents()
    assert not pg.more_right.isVisible()
    rb.close()
