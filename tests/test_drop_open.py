"""Dragging PDFs from Explorer onto the window opens them (Jon, Oct 21)."""
import fitz
from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDropEvent

from test_gui import win, qapp                                 # noqa: F401


def _mime(paths):
    m = QMimeData()
    m.setUrls([QUrl.fromLocalFile(str(p)) for p in paths])
    return m


def test_drop_a_pdf_opens_it_in_a_tab(win, tmp_path):
    d = fitz.open()
    d.new_page()
    p = tmp_path / "dropped.pdf"
    d.save(str(p))
    n = win.tabs.count()
    m = _mime([p])
    enter = QDragEnterEvent(QPoint(50, 50), Qt.CopyAction, m,
                            Qt.LeftButton, Qt.NoModifier)
    win.dragEnterEvent(enter)
    assert enter.isAccepted()
    drop = QDropEvent(QPointF(50, 50), Qt.CopyAction, m, Qt.LeftButton,
                      Qt.NoModifier)
    win.dropEvent(drop)
    assert win.tabs.count() == n + 1
    assert win.tabs.tabText(win.tabs.currentIndex()).startswith("dropped")


def test_non_pdf_is_refused(win, tmp_path):
    t = tmp_path / "notes.txt"
    t.write_text("x")
    m = _mime([t])
    enter = QDragEnterEvent(QPoint(5, 5), Qt.CopyAction, m, Qt.LeftButton,
                            Qt.NoModifier)
    win.dragEnterEvent(enter)
    assert not enter.isAccepted()
    assert win.acceptDrops()
