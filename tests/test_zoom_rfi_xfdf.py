"""Marquee zoom and Previous View, the RFI / submittal log, and XFDF."""
import datetime
import os

import fitz
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import acrobat2, annotate, rfilog, xfdf          # noqa: E402
from test_gui import win, qapp                              # noqa: E402,F401

_KEEP = []


def _mouse(v, kind, x, y, button, buttons):
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication
    t = {"press": QEvent.MouseButtonPress, "move": QEvent.MouseMove,
         "release": QEvent.MouseButtonRelease}[kind]
    p = QPointF(x, y)
    ev = QMouseEvent(t, p, v.mapToGlobal(p), button, buttons,
                     Qt.NoModifier)
    QApplication.sendEvent(v, ev)


# ---- marquee zoom ------------------------------------------------------------------

def test_zoom_to_rect_and_previous_view(win):
    v = win._view
    before = v.zoom
    win.zoom_to_rect(fitz.Rect(100, 100, 200, 150))
    vp = win._scroll.viewport()
    want = min((vp.width() - 24) / 100, (vp.height() - 24) / 50, 8.0)
    assert v.zoom == pytest.approx(want, rel=0.01)
    assert win.previous_view()
    assert v.zoom == pytest.approx(before)


def test_right_drag_zooms_and_right_click_opens_menu(win, monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QMenu
    monkeypatch.setattr(QMenu, "exec", lambda *a, **k: None)
    v = win._view
    for a in list(v.pg.annots()):                 # an empty spot to click
        v.pg.delete_annot(a)
    v.reset_page_cache()
    before = v.zoom
    _mouse(v, "press", 40, 40, Qt.RightButton, Qt.RightButton)
    _mouse(v, "move", 140, 110, Qt.NoButton, Qt.RightButton)
    _mouse(v, "release", 140, 110, Qt.RightButton, Qt.NoButton)
    assert v.zoom > before                       # zoomed into the box
    menus = []
    v.view_menu.disconnect()                     # don't open a real menu
    v.view_menu.connect(lambda pos: menus.append(pos))
    _mouse(v, "press", 60, 60, Qt.RightButton, Qt.RightButton)
    _mouse(v, "release", 61, 60, Qt.RightButton, Qt.NoButton)
    assert len(menus) == 1                       # a click, not a drag
    win.set_tool("zoom")
    assert v.tool == "zoom"
    v.commit_rect("zoom", fitz.Rect(10, 10, 60, 40))
    assert v.tool is None                        # back to Select after


# ---- RFI / submittal log ------------------------------------------------------------

def test_rfi_numbers_status_and_dates():
    d = fitz.open()
    d.new_page()
    a = rfilog.add(d, "RFI", title="Door 104 hardware", due="2020-01-01",
                   sent="2019-12-20")
    b = rfilog.add(d, "RFI", title="Slab depth")
    s = rfilog.add(d, "Submittal", title="Storefront shop drawings",
                   spec="08 41 13")
    assert [a["number"], b["number"], s["number"]] == \
        ["RFI-001", "RFI-002", "SUB-001"]
    assert s["status"] == "Open"
    assert rfilog.is_overdue(a)
    assert rfilog.days_open(a, datetime.date(2020, 1, 4)) == 15
    rfilog.update(d, a["id"], status="Answered", returned="2020-01-03",
                  answer="Use hardware set 4")
    a2 = [x for x in rfilog.items(d) if x["id"] == a["id"]][0]
    assert not rfilog.is_overdue(a2) and rfilog.days_open(a2) == 14
    assert rfilog.delete(d, b["id"])
    c = rfilog.add(d, "RFI", title="Next")
    assert c["number"] == "RFI-003"              # numbers aren't reused
    # the log is job data: Remove Hidden Information keeps it
    acrobat2.sanitize(d)
    assert len(rfilog.items(d)) == 3


def test_rfi_exports(tmp_path):
    d = fitz.open()
    d.new_page()
    rfilog.add(d, "RFI", title="Beam size at grid C", question="Confirm "
               "W12x26 at C/4.", due="2001-01-01", cost_impact="Possible")
    rfilog.add(d, "Submittal", title="Door hardware", status="Approved")
    csv_path = rfilog.export_csv(d, str(tmp_path / "log.csv"))
    text = open(csv_path, encoding="utf-8-sig").read()
    assert "RFI-001" in text and "Overdue" in text
    assert os.path.getsize(rfilog.export_xlsx(d, str(tmp_path / "l.xlsx")))
    pdf = fitz.open(rfilog.export_pdf(d, str(tmp_path / "log.pdf"),
                                      project="Shelter Cove"))
    words = " ".join(p.get_text() for p in pdf)
    assert "RFI-001" in words and "SUB-001" in words
    assert "Confirm W12x26" in words


def test_create_rfi_from_selected_markup(win, monkeypatch):
    from app.rfi_ui import RfiDialog
    monkeypatch.setattr(RfiDialog, "exec", lambda self: 1)
    v = win._view
    v.apply_marks([(0, "add_note", {"pt": [80, 80],
                                    "text": "Detail 5/A-501 missing"})])
    note = [a for a in v.pg.annots() if a.type[1] == "Text"][-1]
    v.select(note)
    it = win.new_rfi("RFI", from_selection=True)
    assert it["number"] == "RFI-001"
    assert it["title"] == "Detail 5/A-501 missing"
    assert it["page"] == 0 and it["markup"]
    assert win.rfis.table.rowCount() == 1
    assert win._view.dirty


# ---- XFDF -------------------------------------------------------------------------------

def _marked_doc():
    d = fitz.open()
    d.new_page(width=612, height=792)
    d[0].insert_text((100, 400), "highlight me", fontsize=14)
    ops = [
        annotate.new_op("add_rect", 0, rect=[100, 100, 200, 150],
                        color=[0, 0, 1], fill=[1, 1, 0], dashes=[6, 3],
                        author="Jon", note="check this"),
        annotate.new_op("add_line", 0, pts=[[50, 600], [300, 650]],
                        arrow=True, color=[1, 0, 0]),
        annotate.new_op("add_polygon", 0,
                        pts=[[300, 100], [400, 100], [400, 200], [300, 200]],
                        label="Slab: 100.00 sq ft",
                        measure={"type": "area", "value": 100,
                                 "unit": "sq ft", "group": "Slab"}),
        annotate.new_op("add_ink", 0, strokes=[[[50, 50], [60, 70],
                                                [80, 60]]]),
        annotate.new_op("add_highlight", 0, rect=[98, 385, 190, 405]),
        annotate.new_op("add_textbox", 0, rect=[400, 500, 560, 530],
                        text="See RFI-001"),
        annotate.new_op("add_note", 0, pt=[30, 700], text="sticky"),
    ]
    for op in ops:
        assert annotate.apply_op(d, op)
    return d


def _summary(d):
    page = d[0]
    _KEEP.append(page)
    return sorted((a.type[1], (a.info or {}).get("content", ""))
                  for a in page.annots())


def test_xfdf_round_trip(tmp_path):
    d = _marked_doc()
    path = str(tmp_path / "m.xfdf")
    n = xfdf.export(d, path)
    page = d[0]
    _KEEP.append(page)
    assert n == sum(1 for a in page.annots() if a.type[0] in xfdf.TAGS)
    sq_el = [e for e in xfdf.parse(path) if e.tag.endswith("square")][0]
    rect = [float(x) for x in sq_el.get("rect").split(",")]
    assert rect == pytest.approx([100, 642, 200, 692], abs=1.5)  # PDF y-up
    blank = fitz.open()
    blank.new_page(width=612, height=792)
    for pno, kind, payload in xfdf.import_marks(blank, path):
        assert annotate.apply_op(blank, annotate.new_op(kind, pno,
                                                        **payload))
    assert _summary(blank) == _summary(d)
    bpage = blank[0]
    _KEEP.append(bpage)
    sq = [a for a in bpage.annots() if a.type[1] == "Square"][0]
    assert list(sq.rect) == pytest.approx([100, 100, 200, 150], abs=1.5)
    assert list(sq.colors["stroke"]) == pytest.approx([0, 0, 1], abs=0.01)
    assert [round(x) for x in sq.border["dashes"]] == [6, 3]
    line = [a for a in bpage.annots() if a.type[1] == "Line"][0]
    assert line.line_ends[1] == fitz.PDF_ANNOT_LE_OPEN_ARROW
    # the measurement and its label came back together, value intact
    items = annotate.takeoff_items(blank)
    assert [(i["group"], i["value"]) for i in items] == [("Slab", 100)]
    labels = [a for a in bpage.annots() if annotate.is_label(blank, a)]
    assert len(labels) == 1


def test_xfdf_from_another_program(tmp_path):
    path = tmp_path / "acrobat.xfdf"
    path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<xfdf xmlns="http://ns.adobe.com/xfdf/" xml:space="preserve">'
        '<annots>'
        '<polygon page="0" rect="90,90,310,210" color="#00FF00" width="2" '
        'title="Arch" subject="Area"><contents>Lobby</contents>'
        '<vertices>100,100,300,100,300,200,100,200</vertices></polygon>'
        '<square page="5" rect="0,0,10,10"/>'
        '<circle page="0" rect="10,10,50,50" interior-color="#FF0000" '
        'opacity="0.5"/>'
        '</annots></xfdf>', encoding="utf-8")
    d = fitz.open()
    d.new_page(width=612, height=792)
    marks = xfdf.import_marks(d, str(path))
    assert len(marks) == 2                       # page 5 doesn't exist
    for pno, kind, payload in marks:
        annotate.apply_op(d, annotate.new_op(kind, pno, **payload))
    page = d[0]
    _KEEP.append(page)
    poly = [a for a in page.annots() if a.type[1] == "Polygon"][0]
    ys = sorted({round(p[1]) for p in poly.vertices})
    assert ys == [592, 692]                      # 792 - 200, 792 - 100
    assert poly.info["content"] == "Lobby" and poly.info["title"] == "Arch"
    circ = [a for a in page.annots() if a.type[1] == "Circle"][0]
    assert circ.opacity == pytest.approx(0.5, abs=0.01)


def test_xfdf_menu_commands(win, tmp_path):
    v = win._view
    path = str(tmp_path / "out.xfdf")
    n = win.export_xfdf(path)
    assert n == sum(1 for p in v.doc for a in p.annots()
                    if a.type[0] in xfdf.TAGS)
    before = len(list(v.pg.annots()))
    win.import_markups(path)
    if n:
        assert len(list(win._view.pg.annots())) > before
