"""Select Text and Copy Text (Nov 3, Jon: "i need to be able to copy
text if I open a pdf")."""
import os

import fitz
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtCore import QPointF, Qt                            # noqa: E402
from PySide6.QtGui import QMouseEvent                             # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox           # noqa: E402

from app import textsel                                           # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _pdf(path, rot=0):
    d = fitz.open()
    p = d.new_page(width=792, height=612)
    p.insert_text((72, 100), "GENERAL NOTES apply to all sheets")
    p.insert_text((72, 120), "Verify dimensions in the field")
    p.insert_text((400, 300), "Room 101 Office")
    if rot:
        p.set_rotation(rot)
    d.new_page()                         # page 2: no text (like a scan)
    d.save(path)
    return path


def test_pick_flow_box_and_text():
    d = fitz.open(_pdf(os.path.join(os.environ.get("TMP", "/tmp"),
                                    "qs_textsel_unit.pdf")))
    ws = textsel.words(d[0])
    s = textsel.word_at(ws, fitz.Point(80, 97))
    assert ws[s][4] == "GENERAL"
    e = textsel.word_at(ws, fitz.Point(110, 117))
    txt = textsel.text_of(ws, textsel.pick(ws, fitz.Point(80, 97),
                                           fitz.Point(110, 117), s))
    assert txt.startswith("GENERAL NOTES apply") and "\n" in txt
    assert txt.split("\n")[1] == ws[e][4] or txt.endswith(ws[e][4])
    box = textsel.pick(ws, fitz.Point(390, 280), fitz.Point(600, 310))
    assert textsel.text_of(ws, box) == "Room 101 Office"
    assert textsel.word_at(ws, fitz.Point(700, 500)) is None
    assert len(textsel.rects(ws, range(len(ws)))) == 3


@pytest.fixture
def win(qapp, tmp_path, monkeypatch):
    from app import settings
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", None)
    for name in ("information", "warning"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(lambda *a, **k: 0))
    from app.main_window import MainWindow
    w = MainWindow()
    w.resize(1200, 900)
    yield w, tmp_path
    if w._view is not None:
        w._view.dirty = False
    w.close()
    w.deleteLater()
    qapp.processEvents()


def _drag(v, a, b):
    """Drag in the view from page point a to b (unrotated page coords)."""
    def wp(p):
        q = fitz.Point(p) * v.pg.rotation_matrix
        return QPointF(q.x * v.zoom, q.y * v.zoom)
    for t, pos, btn, btns in (
            (QMouseEvent.MouseButtonPress, wp(a), Qt.LeftButton,
             Qt.LeftButton),
            (QMouseEvent.MouseMove, wp(b), Qt.NoButton, Qt.LeftButton),
            (QMouseEvent.MouseButtonRelease, wp(b), Qt.LeftButton,
             Qt.NoButton)):
        QApplication.sendEvent(v, QMouseEvent(t, pos, pos, btn, btns,
                                              Qt.NoModifier))


@pytest.mark.parametrize("rot", [0, 90])
def test_select_and_copy_in_window(win, qapp, rot):
    w, tmp = win
    path = _pdf(str(tmp / f"plan{rot}.pdf"), rot)
    assert w.open_path(path)
    qapp.processEvents()
    v = w._view
    v.set_zoom(1.0)
    assert w.command("Select Text") is not None
    assert w.command("Copy Text") is not None
    w.set_tool("select_text")
    assert v.tool == "select_text"
    _drag(v, (80, 97), (150, 98))
    assert v.selected_text().startswith("GENERAL NOTES")
    assert v.text_rects()
    QApplication.clipboard().clear()
    assert w.copy_text() == v.selected_text()
    assert QApplication.clipboard().text() == v.selected_text()
    # box an area that starts off the text
    _drag(v, (390, 280), (600, 310))
    assert v.selected_text() == "Room 101 Office"
    assert w.select_all_text() == len(v.page_words())
    assert "Verify dimensions" in v.selected_text()
    assert "Room 101" in w.copy_text(page=True)
    v.next_page()
    qapp.processEvents()
    assert v.selected_text() == "" and w.copy_text() == ""
    assert w.select_all_text() == 0
    w.set_tool(None)
    assert v.text_sel is None


def test_double_click_word_with_select_tool(win, qapp):
    w, tmp = win
    assert w.open_path(_pdf(str(tmp / "p.pdf")))
    qapp.processEvents()
    v = w._view
    v.set_zoom(1.0)
    w.set_tool(None)
    assert v.select_word_at(fitz.Point(140, 115), switch=True)
    assert v.tool == "select_text"
    assert v.selected_text() == "dimensions"


def test_table_from_a_schedule():
    def W(x, y, t, b):
        return (x, y, x + len(t) * 5, y + 8, t, b, 0, 0)
    ws = [W(10, 10, "MARK", 0), W(80, 10, "SIZE", 1), W(150, 10, "TYPE", 2),
          W(10, 22, "101", 3), W(80, 22, "3-0", 4), W(98, 22, "x", 4),
          W(106, 22, "7-0", 4), W(150, 22, "A", 5),
          W(10, 34, "102", 6), W(150, 34, "B", 7)]
    rows = textsel.table(ws, range(len(ws)))
    assert rows == [["MARK", "SIZE", "TYPE"], ["101", "3-0 x 7-0", "A"],
                    ["102", "", "B"]]
    assert textsel.table_text(rows).split("\n")[1] == "101\t3-0 x 7-0\tA"


def test_copy_table_and_markup_text_in_window(win, qapp):
    w, tmp = win
    assert w.open_path(_pdf(str(tmp / "t.pdf")))
    qapp.processEvents()
    v = w._view
    v.set_zoom(1.0)
    assert w.command("Copy as Table (for Excel)") is not None
    assert w._tool_actions["select_text"].shortcut().toString() == "I"
    assert w.copy_table() == ""                       # nothing selected
    w.set_tool("select_text")
    _drag(v, (60, 85), (300, 125))
    t = w.copy_table()
    assert t.startswith("GENERAL NOTES") and "\n" in t
    assert QApplication.clipboard().text() == t
    # a selected text box: Ctrl+C copies its words
    w.set_tool(None)
    from app import annotate
    pg = v.pg
    a = pg.add_freetext_annot(fitz.Rect(300, 400, 500, 440), "Paint P-1")
    a.update()
    v.select(a)
    assert w.copy_text() == "Paint P-1"
