"""Filling a form by clicking into its fields (Nov 17), on a made-up form
whose fields have no appearance of their own (as many fillable PDFs ship):
the fields are tinted so they can be seen, a click opens a text field for
typing in place, Enter keeps it, Esc leaves it, Tab goes on to the next
field, and a click on a check box ticks it."""
import os

import pytest

fitz = pytest.importorskip("fitz")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from test_gui import win, qapp  # noqa: E402,F401


def made_up_form(path):
    d = fitz.open()
    p = d.new_page(width=612, height=792)
    for i, name in enumerate(("company", "cor_no", "notes")):
        w = fitz.Widget()
        w.rect = fitz.Rect(72, 100 + 40 * i, 300, 120 + 40 * i)
        w.field_type = fitz.PDF_WIDGET_TYPE_TEXT
        w.field_name = name
        w.field_value = ""
        p.add_widget(w)
    c = fitz.Widget()
    c.rect = fitz.Rect(72, 260, 86, 274)
    c.field_type = fitz.PDF_WIDGET_TYPE_CHECKBOX
    c.field_name = "approved"
    p.add_widget(c)
    d.save(path)
    d.close()
    # strip the text fields' appearances, as the reported form had none
    d = fitz.open(path)
    for w in d[0].widgets():
        if w.field_type == fitz.PDF_WIDGET_TYPE_TEXT:
            d.xref_set_key(w.xref, "AP", "null")
    d.saveIncr()
    d.close()
    return str(path)


def click(view, page_pt):
    r = view._q(fitz.Rect(page_pt, page_pt))
    ev = QMouseEvent(QMouseEvent.MouseButtonPress, QPointF(r.x(), r.y()),
                     QPointF(r.x(), r.y()), Qt.LeftButton, Qt.LeftButton,
                     Qt.NoModifier)
    view.mousePressEvent(ev)


def values(view):
    return {w.field_name: w.field_value for w in view.pg.widgets()}


def test_click_type_enter_tab_esc(win, tmp_path):
    assert win.open_path(made_up_form(tmp_path / "form.pdf"))
    v = win._view
    v.tool = "select"
    assert len(v.field_rects()) == 4                  # tinted, so seen
    click(v, fitz.Point(100, 110))                    # into 'company'
    ed, name = v._field_edit[0], v._field_edit[1]
    assert name == "company"
    ed.setText("Made Up Builders")
    ed.returnPressed.emit()
    QApplication.processEvents()
    assert values(v)["company"] == "Made Up Builders"
    # Tab from one field to the next keeps the first
    click(v, fitz.Point(100, 150))
    v._field_edit[0].setText("COR-7")
    assert v._field_tab() == "notes"
    assert values(v)["cor_no"] == "COR-7"
    # Esc leaves a field as it was
    v._field_edit[0].setText("not kept")
    v.close_field_editor(keep=False)
    assert values(v)["notes"] in ("", None)
    # a check box ticks on one click
    click(v, fitz.Point(79, 267))
    assert values(v)["approved"] not in ("Off", False, "", None)
    assert v._field_edit is None


def test_ctrl_click_still_selects(win, tmp_path):
    assert win.open_path(made_up_form(tmp_path / "form2.pdf"))
    v = win._view
    v.tool = "select"
    r = v._q(fitz.Rect(100, 110, 100, 110))
    ev = QMouseEvent(QMouseEvent.MouseButtonPress, QPointF(r.x(), r.y()),
                     QPointF(r.x(), r.y()), Qt.LeftButton, Qt.LeftButton,
                     Qt.ControlModifier)
    v.mousePressEvent(ev)
    assert getattr(v, "_field_edit", None) is None


def two_page_form(path):
    d = fitz.open()
    for pg, names in enumerate((("a1", "a2"), ("b1",))):
        p = d.new_page(width=612, height=792)
        for i, name in enumerate(names):
            w = fitz.Widget()
            w.rect = fitz.Rect(72, 100 + 40 * i, 300, 120 + 40 * i)
            w.field_type = fitz.PDF_WIDGET_TYPE_TEXT
            w.field_name = name
            w.field_value = ""
            p.add_widget(w)
    c = fitz.Widget()
    c.rect = fitz.Rect(72, 300, 300, 320)
    c.field_type = fitz.PDF_WIDGET_TYPE_COMBOBOX
    c.field_name = "trade"
    c.choice_values = ["Concrete", "Electrical", "Plumbing"]
    c.field_value = "Concrete"
    d[1].add_widget(c)
    d.save(path)
    d.close()
    return str(path)


def test_tab_goes_on_to_the_next_page(win, tmp_path):
    assert win.open_path(two_page_form(tmp_path / "two.pdf"))
    v = win._view
    v.tool = None
    click(v, fitz.Point(100, 150))                    # a2, last on page 1
    v._field_edit[0].setText("x")
    assert v._field_tab() == "b1"
    assert v.page == 1
    assert v._field_edit[1] == "b1"
    v.close_field_editor(keep=False)


def test_drop_down_opens_on_the_field(win, tmp_path):
    assert win.open_path(two_page_form(tmp_path / "dd.pdf"))
    v = win._view
    v.tool = None
    v.go_to(1)
    click(v, fitz.Point(100, 310))
    cb = v._choice_box
    cb.hidePopup()
    cb.activated.emit(1)
    QApplication.processEvents()
    assert values(v)["trade"] == "Electrical"


def test_fill_text_tool_fills_a_field_instead_of_adding_text(win, tmp_path):
    assert win.open_path(made_up_form(tmp_path / "form3.pdf"))
    v = win._view
    v.tool = "fs_text"
    n = len(list(v.pg.annots() or []))
    click(v, fitz.Point(100, 110))
    assert v._field_edit and v._field_edit[1] == "company"
    v.close_field_editor(keep=False)
    assert len(list(v.pg.annots() or [])) == n        # no text box added


def test_help_video_tutorials(win):
    opened = []
    assert win.video_tutorials(open_url=opened.append) == \
        "https://www.youtube.com/@QuantiSheet"
    assert opened == ["https://www.youtube.com/@QuantiSheet"]
    names = [a.text() for a in win._help_menu.actions()]
    assert "Video Tutorials" in names
