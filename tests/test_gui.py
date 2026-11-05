"""Drives the desktop app's features offscreen, with dialogs answered
automatically. Run with QT_QPA_PLATFORM=offscreen if there's no display."""
import os

import fitz
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtGui import QColor                                  # noqa: E402
from PySide6.QtWidgets import (QApplication, QColorDialog,        # noqa: E402
                               QFileDialog, QInputDialog, QMessageBox)

import make_sample                                                # noqa: E402
from app import annotate                                          # noqa: E402
from app.main_window import MainWindow                            # noqa: E402

ANSWERS = {}


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def win(qapp, tmp_path, monkeypatch):
    ANSWERS.clear()
    ANSWERS.update({"text": "Hello", "multi": "A note", "double": 10.0,
                    "item": "ft", "int": 1, "open": "", "save": ""})
    monkeypatch.setattr(QInputDialog, "getText",
                        staticmethod(lambda *a, **k: (ANSWERS["text"], True)))
    monkeypatch.setattr(QInputDialog, "getMultiLineText",
                        staticmethod(lambda *a, **k: (ANSWERS["multi"], True)))
    monkeypatch.setattr(QInputDialog, "getDouble",
                        staticmethod(lambda *a, **k: (ANSWERS["double"], True)))
    monkeypatch.setattr(QInputDialog, "getItem",
                        staticmethod(lambda *a, **k: (ANSWERS["item"], True)))
    monkeypatch.setattr(QInputDialog, "getInt",
                        staticmethod(lambda *a, **k: (ANSWERS["int"], True)))
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.Yes))
    for name in ("information", "warning", "about"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(lambda *a, **k: 0))
    monkeypatch.setattr(QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: (ANSWERS["open"], "")))
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (ANSWERS["save"], "")))
    monkeypatch.setattr(QColorDialog, "getColor",
                        staticmethod(lambda *a, **k: QColor(0, 200, 0)))
    from app import settings, toolchest
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", None)
    monkeypatch.setattr(toolchest, "PATH", str(tmp_path / "cfg" / "tc.json"))
    monkeypatch.setattr(QFileDialog, "getOpenFileNames",
                        staticmethod(lambda *a, **k: ([ANSWERS["open"]], "")))
    path = str(tmp_path / "plan.pdf")
    make_sample.make(path)
    w = MainWindow()
    w.resize(1200, 900)
    assert w.open_path(path)
    qapp.processEvents()          # let the deferred fit-width run first
    w._view.set_zoom(1.0)         # (pytest-qt runs it at a later moment)
    yield w
    if w._view is not None:
        w._view.dirty = False
    w.close()
    # free it: windows left behind made every later theme switch restyle
    # dozens of hidden windows (40 s+ by the end of a run)
    w.deleteLater()
    qapp.processEvents()


def annots(v, page=None):
    pg = v.doc[v.page if page is None else page]
    return [(a.type[1], fitz.Rect(a.rect), a.info) for a in pg.annots()]


def text_rect(v, text):
    return v.pg.search_for(text)[0]


# ---- basics ------------------------------------------------------------------

def test_markup_tools(win):
    v = win._view
    r = text_rect(v, "General notes")
    assert v.commit_rect("add_highlight", r + (-2, -2, 2, 2)) == 1
    assert v.commit_rect("add_underline", text_rect(v, "ADA") + (-1, -1, 1, 1))
    assert v.commit_rect("add_strike", text_rect(v, "listed") + (-1, -1, 1, 1))
    for t in ("add_rect", "add_ellipse", "add_cloud"):
        assert v.commit_rect(t, fitz.Rect(400, 500, 480, 560)) == 1
    assert v.commit_line("add_line", fitz.Point(50, 650), fitz.Point(200, 650))
    assert v.commit_line("arrow", fitz.Point(50, 670), fitz.Point(200, 690))
    pts = [fitz.Point(300, 600), fitz.Point(350, 640), fitz.Point(400, 600)]
    assert v.commit_points("add_polyline", pts)
    assert v.commit_points("add_polygon", pts)
    stroke = [fitz.Point(100 + i * 3, 720 + (i % 5)) for i in range(30)]
    assert v.commit_stroke(stroke)
    assert v.commit_click("add_note", fitz.Point(500, 100))
    assert v.commit_rect("add_textbox", fitz.Rect(400, 120, 560, 160))
    types = [t for t, _, _ in annots(v)]
    for t in ("Highlight", "Underline", "StrikeOut", "Square", "Circle",
              "Line", "PolyLine", "Polygon", "Ink", "Text", "FreeText"):
        assert t in types, (t, types)
    hl = [r for t, r, _ in annots(v) if t == "Highlight"][0]
    assert hl.height < 20                    # hugs the text line
    assert v.dirty


def test_select_move_recolor_comment_delete(win):
    v = win._view
    v.commit_rect("add_rect", fitz.Rect(400, 500, 480, 560))
    v.select(v.annot_at(fitz.Point(400, 530)))
    assert v.selected and v.selected["type"] == "Square"
    assert v.move_selected(20, 10)
    r = [r for t, r, _ in annots(v) if t == "Square"][0]
    assert abs(r.x0 - 420) < 3 and abs(r.y0 - 510) < 3
    assert v.recolor_selected()
    assert v.edit_selected_comment()
    info = [i for t, _, i in annots(v) if t == "Square"][0]
    assert info["content"] == "A note"
    assert v.delete_selected()
    assert not [t for t, _, _ in annots(v) if t == "Square"]


def test_undo_redo(win):
    v = win._view
    v.commit_rect("add_rect", fitz.Rect(100, 500, 150, 550))
    assert len(annots(win._view)) == 1
    win.undo()
    assert len(annots(win._view)) == 0
    win.redo()
    assert len(annots(win._view)) == 1


def test_undo_mixed_markups_and_page_ops(win):
    v = win._view
    v.commit_rect("add_rect", fitz.Rect(100, 500, 150, 550))
    assert win._view.history.stack[-1][0] == "pages"     # cheap step
    win._page_action("rotate_right", [1])
    win._view.go_to(0)
    win._view.commit_rect("add_ellipse", fitz.Rect(200, 500, 250, 550))
    assert len(annots(win._view)) == 2
    win.undo()                                    # ellipse, in place
    assert len(annots(win._view)) == 1
    win.undo()                                    # rotation, reloaded
    assert win._view.doc[1].rotation == 0
    assert len(annots(win._view)) == 1
    win.undo()
    assert len(annots(win._view)) == 0
    win.redo()
    win.redo()
    win.redo()
    assert win._view.doc[1].rotation == 90
    win._view.go_to(0)
    assert len(annots(win._view)) == 2


def test_search(win):
    win.find()
    win.search.edit.setText("fire rating")
    win.search.step(1)
    assert len(win.search.hits) >= 3          # on every sheet
    assert win._view.search_current is not None
    win.search.step(1)
    win.search.step(1)
    win.search.step(1)
    assert win._view.page >= 1                # moved on to the next sheet
    win.search.close_bar()
    assert win._view.search_current is None


def test_print_to_pdf(win, tmp_path):
    from PySide6.QtPrintSupport import QPrinter
    out = str(tmp_path / "printed.pdf")
    p = QPrinter(QPrinter.HighResolution)
    p.setOutputFormat(QPrinter.PdfFormat)
    p.setOutputFileName(out)
    assert win.print_to(p)
    assert fitz.open(out).page_count == win._view.doc.page_count
    # review r41 F02: kept as lines and text, not a ~10 MB picture a page
    got = fitz.open(out)
    assert len(got[0].get_images()) == len(win._view.doc[0].get_images())
    assert got[0].get_text().strip() == win._view.doc[0].get_text().strip()


def test_thumbnails_and_zoom(win):
    assert win.thumbs.count() == win._view.doc.page_count
    win.thumbs._render_some()
    win._go_page(2)
    assert win._view.page == 2 and win.thumbs.currentRow() == 2
    win.fit_width()
    win.fit_page()
    assert 0.2 <= win._view.zoom <= 8


def test_save_and_reopen(win, tmp_path):
    v = win._view
    v.commit_rect("add_rect", fitz.Rect(100, 500, 150, 550))
    assert win.save_file()
    assert not v.dirty
    d = fitz.open(win._path)
    assert len(list(d[0].annots())) == 1
    d.close()
    ANSWERS["save"] = str(tmp_path / "copy.pdf")
    assert win.save_as()
    assert os.path.exists(tmp_path / "copy.pdf")


# ---- takeoff -------------------------------------------------------------------

def test_takeoff_scale_length_area_count(win, tmp_path):
    v = win._view
    assert v.calibrate(100.0, real=10, unit="ft", all_pages=True)
    assert v.scale()["ppu"] == pytest.approx(10.0)
    assert v.scale(2)["unit"] == "ft"
    assert v.commit_line("measure_length", fitz.Point(50, 450),
                         fitz.Point(250, 450))                 # 200 pt = 20 ft
    sq = [fitz.Point(300, 450), fitz.Point(400, 450), fitz.Point(400, 550),
          fitz.Point(300, 550)]                                # 10 x 10 ft
    assert v.commit_points("measure_area", sq)
    assert v.commit_points("measure_polylength", sq[:3])       # 20 ft
    v.count_group = "Outlets"
    v.commit_click("count", fitz.Point(80, 300))
    v.commit_click("count", fitz.Point(120, 300))
    items = annotate.takeoff_items(v.doc)
    by = {(i["type"], round(i["value"], 2)) for i in items}
    assert ("length", 20.0) in by and ("area", 100.0) in by
    counts = [i for i in items if i["type"] == "count"]
    assert len(counts) == 2 and counts[0]["group"] == "Outlets"
    labels = [i["content"] for t, _, i in annots(v) if t == "FreeText"]
    assert "20' 0\"" in labels and "100.00 sq ft" in labels
    q = win.quantities
    q.refresh()
    tot = q.summary()
    assert tot[("", "length", "ft")] == pytest.approx(40.0)
    assert tot[("Outlets", "count", "ea")] == 2
    out = q.export(str(tmp_path / "q.csv"))
    assert "Outlets" in open(out, encoding="utf-8-sig").read()


def test_measure_without_scale_asks_first(win):
    v = win._view
    assert v.commit_line("measure_length", fitz.Point(0, 0),
                         fitz.Point(100, 0)) == 0


def test_count_symbol(win):
    v = win._view
    box = fitz.Rect(57, 237, 113, 283)      # one of the three EXIT boxes
    n = v.count_symbol(box, group="Exit sign", all_pages=True)
    assert n >= 9                             # 3 per sheet x 3 sheets
    counts = [i for i in annotate.takeoff_items(v.doc)
              if i["group"] == "Exit sign"]
    assert len(counts) == n


def test_count_by_label(win):
    dlg = win.auto_count_label(show=False, text="EXIT")
    assert dlg.find(quiet=True) >= 9
    assert dlg.count() == 9
    items = [i for i in annotate.takeoff_items(win._view.doc)
             if i["group"] == "EXIT"]
    assert len(items) == 9


# ---- page tools ------------------------------------------------------------------

def test_page_tools(win, tmp_path):
    v = win._view
    doc = v.doc
    first = doc[0].get_text()[:40]
    win._page_action("rotate_right", [0])
    assert win._view.doc[0].rotation == 90
    win._page_action("insert_blank", [0])
    assert win._view.doc.page_count == 4
    assert win._view.doc[1].get_text().strip() == ""
    win._page_action("delete", [1])
    assert win._view.doc.page_count == 3
    win._move_page(0, 2)
    assert win._view.doc[2].get_text()[:40] == first
    other = str(tmp_path / "other.pdf")
    make_sample.make(other)
    ANSWERS["open"] = other
    win._page_action("insert_pdf", [2])
    assert win._view.doc.page_count == 6
    ANSWERS["save"] = str(tmp_path / "extract.pdf")
    win._page_action("extract", [0, 1])
    assert fitz.open(tmp_path / "extract.pdf").page_count == 2
    ANSWERS["text"], ANSWERS["int"] = "EX", 100
    win.bates()
    assert "EX000100" in win._view.doc[0].get_text()
    ANSWERS["text"], ANSWERS["int"] = "DRAFT", 30
    win.watermark()
    assert "DRAFT" in win._view.doc[0].get_text()
    win.undo()
    assert "DRAFT" not in win._view.doc[0].get_text()
    assert win.thumbs.count() == win._view.doc.page_count


def test_markup_on_rotated_page(win):
    win._page_action("rotate_right", [0])
    v = win._view
    screen = fitz.Rect(100, 100, 200, 140)
    v.commit_rect("add_rect", screen)
    a = [r for t, r, _ in annots(v) if t == "Square"][0]
    shown = annotate.from_page(v.pg, a)
    assert abs(shown.x0 - 100) < 3 and abs(shown.y1 - 140) < 3


def test_compare(win, tmp_path):
    other = str(tmp_path / "other.pdf")
    d = fitz.open()
    d.new_page().insert_text((50, 50), "something else")
    d.save(other)
    ANSWERS["open"] = other
    win.compare_with()
    assert win.tabs.count() == 2
    text = win._view.doc[0].get_text()
    assert "+ something else" in text


# ---- editing ------------------------------------------------------------------------

def test_edit_text(win):
    v = win._view
    r = text_rect(v, "General notes")
    assert v.edit_text_at(r.tl + (3, 3), new_text="Project notes")
    t = v.pg.get_text()
    assert "Project notes" in t and "General notes" not in t


def test_image(win, tmp_path):
    png = str(tmp_path / "img.png")
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 40, 30), False)
    pix.clear_with(200)
    pix.save(png)
    ANSWERS["open"] = png
    v = win._view
    assert v.commit_rect("add_image", fitz.Rect(400, 600, 480, 660))
    assert v.pg.get_images()


def test_form_fields(win):
    v = win._view
    ANSWERS["text"] = "Name"
    assert v.commit_rect("field_text", fitz.Rect(300, 680, 500, 700))
    ANSWERS["text"] = "Approved"
    assert v.commit_rect("field_checkbox", fitz.Rect(300, 710, 314, 724))
    ANSWERS["text"] = "Status"
    v.commit_rect("field_combo", fitz.Rect(300, 730, 420, 748))
    names = {w.field_name: w for w in v.pg.widgets()}
    assert set(names) >= {"Name", "Approved", "Status"}
    w = v.widget_at(fitz.Point(310, 690))
    assert v.fill_field(w, "Jane Doe")
    w = v.widget_at(fitz.Point(306, 716))
    assert v.fill_field(w, True)
    vals = {w.field_name: w.field_value for w in v.pg.widgets()}
    assert vals["Name"] == "Jane Doe"
    assert vals["Approved"] not in ("Off", False, "")


def test_redact(win):
    v = win._view
    r = text_rect(v, "General notes")
    v.commit_rect("add_redact", r + (-2, -2, 2, 2))
    assert "General notes" not in v.pg.get_text()


def test_freetext_edit(win):
    v = win._view
    v.commit_rect("add_textbox", fitz.Rect(400, 120, 560, 160))
    v.select(v.annot_at(fitz.Point(450, 140)))
    ANSWERS["multi"] = "Changed"
    assert v.edit_selected_text()
    info = [i for t, _, i in annots(v) if t == "FreeText"][0]
    assert info["content"] == "Changed"


# ---- Bluebeam-style features -------------------------------------------------------

def test_markups_list_status_filter_export(win, tmp_path):
    v = win._view
    v.commit_rect("add_cloud", fitz.Rect(100, 500, 200, 560))
    v.commit_click("add_note", fitz.Point(300, 100))
    win._refresh_panels()
    m = win.markups
    assert len(m.items) == 2
    types = [i["type"] for i in m.items]
    assert "Cloud" in types and "Note" in types, types
    cloud = [i for i in m.items if i["type"] == "Cloud"][0]
    assert cloud["subject"] == "Cloud" and cloud["author"]
    assert cloud["date"].startswith("20")
    win._markup_change(cloud["page"], cloud["ref"], {"status": "Accepted"})
    win._refresh_panels()
    assert [i["status"] for i in m.items if i["type"] == "Cloud"] == ["Accepted"]
    m.status_filter.setCurrentIndex(1 + annotate.STATUSES.index("Accepted"))
    assert len(m.visible_items()) == 1
    m.status_filter.setCurrentIndex(0)
    m.filter.setText("note")
    assert [i["type"] for i in m.visible_items()] == ["Note"]
    m.filter.setText("")
    out = m.export(str(tmp_path / "m.csv"))
    assert "Accepted" in open(out, encoding="utf-8-sig").read()
    win._markup_delete([(cloud["page"], cloud["ref"])])
    win._refresh_panels()
    assert len(m.items) == 1


def test_measurement_labels_not_listed_twice(win):
    v = win._view
    v.calibrate(100.0, real=10, unit="ft", all_pages=False)
    v.commit_line("measure_length", fitz.Point(50, 450), fitz.Point(250, 450))
    win._refresh_panels()
    assert len(win.markups.items) == 1
    assert win.markups.items[0]["measure"] == "20.00 ft"


def test_properties_edit_selection_and_tool(win):
    v = win._view
    v.commit_rect("add_rect", fitz.Rect(100, 500, 200, 560))
    v.select(v.annot_at(fitz.Point(100, 530)))
    p = win.properties
    p.refresh()
    p._set("width", 4)
    p._set("fill", [1, 0.9, 0.2])
    p._set("opacity", 0.5)
    p._set("subject", "Hold area")
    p._set("note", "check this")
    a = v.pg.first_annot
    assert a.border["width"] == 4 and a.colors["fill"]
    assert abs(a.opacity - 0.5) < 0.01
    assert a.info["subject"] == "Hold area"
    assert a.info["content"] == "check this"
    v.select(None)
    win.set_tool("add_ellipse")
    p.refresh()
    p._set("color", [0, 0.5, 0])
    p._set("width", 3)
    v.commit_rect("add_ellipse", fitz.Rect(300, 500, 380, 560))
    e = [a for a in v.pg.annots() if a.type[1] == "Circle"][0]
    assert e.border["width"] == 3
    assert tuple(round(c, 1) for c in e.colors["stroke"]) == (0, 0.5, 0)


def test_tool_chest_use_and_add(win):
    v = win._view
    win.apply_scale_preset('1/4" = 1\'-0"', 18.0, "ft", all_pages=True)
    walls = [i for i in win.chest.chest["Takeoff"]
             if i["name"] == "Interior Wall"][0]
    win.use_chest_tool(walls)
    assert v.tool == "measure_polylength" and v.style["subject"] == "Interior Wall"
    v.commit_points("measure_polylength", [fitz.Point(100, 400),
                                           fitz.Point(280, 400),
                                           fitz.Point(280, 580)])
    items = annotate.takeoff_items(v.doc)
    assert items[0]["group"] == "Interior Wall"
    assert items[0]["value"] == pytest.approx(20.0)          # 360 pt / 18
    doors = [i for i in win.chest.chest["Takeoff"] if i["name"] == "Doors"][0]
    win.use_chest_tool(doors)
    assert v.tool == "count" and v.count_group == "Doors"
    v.commit_click("count", fitz.Point(400, 300))
    # save a markup as a new tool
    win.set_tool(None)
    v.commit_rect("add_cloud", fitz.Rect(100, 600, 200, 660))
    v.select(v.annot_at(fitz.Point(100, 630)))
    ANSWERS["text"] = "My Cloud"
    ANSWERS["item"] = "Review"
    win.add_selected_to_chest()
    names = [i["name"] for i in win.chest.chest["Review"]]
    assert "My Cloud" in names
    mine = [i for i in win.chest.chest["Review"] if i["name"] == "My Cloud"][0]
    assert mine["tool"] == "add_cloud"
    from app import toolchest
    assert "My Cloud" in open(toolchest.PATH).read()       # saved to disk


def test_estimate_pricing(win, tmp_path):
    v = win._view
    win.apply_scale_preset('1" = 20\'', 3.6, "ft", all_pages=True)
    v.style = {"subject": "Curb"}
    v.tool = "measure_length"
    v.commit_line("measure_length", fitz.Point(50, 450), fitz.Point(122, 450))
    v.commit_line("measure_length", fitz.Point(50, 470), fitz.Point(122, 470))
    e = win.estimate
    e.refresh()
    curb = [g for g in e.rows if g["name"] == "Curb"][0]
    assert curb["quantity"] == pytest.approx(40.0)            # 2 x 20 ft
    e.set_price("Curb", "length", "ft", unit_cost=12.5, waste=10)
    curb = [g for g in e.rows if g["name"] == "Curb"][0]
    assert curb["total"] == pytest.approx(40 * 1.1 * 12.5)
    assert "$550.00" in e.total.text()
    from app import estimate
    assert estimate.read_prices(v.doc)                       # stored in PDF
    out = str(tmp_path / "est.csv")
    estimate.export_csv(v.doc, out)
    assert "Grand Total" in open(out, encoding="utf-8-sig").read()


def test_scale_presets_values():
    from app import takeoff
    arch = dict(takeoff.PRESETS["Architectural"])
    assert arch['1/4" = 1\'-0"'] == (18.0, "ft")
    assert dict(takeoff.PRESETS["Engineering"])['1" = 20\''][0] == 3.6


def test_snapshot_and_paste(win):
    v = win._view
    assert v.snapshot(fitz.Rect(50, 50, 250, 150))
    assert not QApplication.clipboard().image().isNull()
    v.go_to(1)
    assert v.paste_image(fitz.Point(300, 400))
    assert v.pg.get_images()


def test_tabs_documents_bookmarks(win, tmp_path):
    other = str(tmp_path / "second.pdf")
    make_sample.make(other)
    assert win.open_path(other)
    assert win.tabs.count() == 2
    assert win.open_path(other) and win.tabs.count() == 2   # no duplicate
    win.tabs.setCurrentIndex(0)
    assert os.path.basename(win._path) == "plan.pdf"
    win.bookmarks.add_bookmark("Sheet A1", 0)
    win.bookmarks.add_bookmark("Sheet A3", 2)
    assert [t[1] for t in win._view.doc.get_toc()] == ["Sheet A1", "Sheet A3"]
    win.documents.set_folder(str(tmp_path))
    names = []
    root = win.documents.tree.invisibleRootItem()
    for i in range(root.childCount()):
        names.append(root.child(i).text(0))
    assert "plan.pdf" in names and "second.pdf" in names
    win.tabs.setCurrentIndex(1)
    win._view.dirty = False
    assert win.close_tab(1)
    assert win.tabs.count() == 1


# ---- Acrobat-style tools in the app ---------------------------------------------

def test_combine_opens_new_tab(win, tmp_path):
    a, b = str(tmp_path / "a.pdf"), str(tmp_path / "b.pdf")
    make_sample.make(a)
    make_sample.make(b)
    from PySide6.QtWidgets import QFileDialog as FD
    FD.getOpenFileNames = staticmethod(lambda *x, **k: ([a, b], ""))
    v = win.combine_files()
    assert v is not None and v.doc.page_count == 6
    assert win.tabs.count() == 2 and win._path is None
    ANSWERS["save"] = str(tmp_path / "combined.pdf")
    assert win.save_file()                      # asks where, then saves
    assert os.path.exists(tmp_path / "combined.pdf")
    assert os.path.basename(win._path) == "combined.pdf"


def test_stamp_and_crop_tools(win):
    v = win._view
    ANSWERS["item"] = "Approved"
    assert v.commit_rect("add_stamp", fitz.Rect(350, 600, 550, 660))
    assert [a.type[1] for a in v.pg.annots()] == ["Stamp"]
    win.set_tool("crop")
    v.commit_rect("crop", fitz.Rect(40, 40, 400, 400))
    assert win._view.doc[0].cropbox.width == pytest.approx(360, abs=1)
    win.undo()
    assert win._view.doc[0].cropbox.width == pytest.approx(612, abs=1)


def test_redact_dialog_and_exports(win, tmp_path):
    from app.acrobat_dialogs import RedactDialog
    dlg = RedactDialog(win._view.doc, win)
    dlg.text.setText("fire rating")
    assert len(dlg.hits) == 6
    win._view.apply_marks(dlg.marks())
    assert "fire rating" not in win._view.doc[0].get_text().lower()
    ANSWERS["save"] = str(tmp_path / "out.docx")
    assert win.export_as("docx")
    ANSWERS["save"] = str(tmp_path / "out.xlsx")
    assert win.export_as("xlsx")
    # exports run on a worker thread now: wait for both files
    _wait_until(lambda: zipfile_ready(tmp_path / "out.docx") and
                zipfile_ready(tmp_path / "out.xlsx"))
    assert zipfile_ok(tmp_path / "out.docx") and zipfile_ok(tmp_path / "out.xlsx")


def _wait_until(pred, timeout=60.0):
    import time
    from PySide6.QtWidgets import QApplication
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        QApplication.processEvents()
        if pred():
            return True
        time.sleep(0.05)
    raise AssertionError("timed out waiting for the background job")


def zipfile_ready(p):
    try:
        return zipfile_ok(p)
    except Exception:
        return False


def zipfile_ok(p):
    import zipfile
    with zipfile.ZipFile(p) as z:
        return z.testzip() is None


def test_prepare_and_clear_form(win):
    v = win._view
    v.pg.insert_text((72, 700), "Inspector: ______________________")
    v.reset_page_cache()
    assert win.prepare_form() == 1
    w = list(v.pg.widgets())[0]
    assert "Inspector" in w.field_name
    v.fill_field(w, "Jon")
    assert list(v.pg.widgets())[0].field_value == "Jon"
    win.clear_form()
    assert list(v.pg.widgets())[0].field_value in ("", None)


# ---- Fill & Sign, callout, date stamp, create/split/compare in the app -----------

def test_fill_and_sign_tools(win):
    v = win._view
    from app import signature, settings
    sig = {"w": 1.0, "h": 0.4, "strokes": [[[0, 0.2], [0.3, 0], [0.6, 0.4],
                                            [1.0, 0.1]]]}
    settings.set("signature", sig)
    assert signature.saved("signature")
    assert v.commit_rect("fs_signature", fitz.Rect(300, 650, 450, 700))
    ink = [a for a in v.pg.annots() if a.type[1] == "Ink"][0]
    assert ink.rect.width > 100 and ink.info["subject"] == "Signature"
    ANSWERS["text"] = "Pat Morgan"
    assert v.commit_click("fs_text", fitz.Point(100, 680))
    assert v.commit_click("fs_check", fitz.Point(80, 700))
    assert v.commit_click("fs_date", fitz.Point(100, 720))
    assert v.commit_click("date_stamp", fitz.Point(400, 80))
    texts = [a.info["content"] for a in v.pg.annots()
             if a.type[1] == "FreeText"]
    assert "Pat Morgan" in texts
    assert any(t.startswith("RECEIVED") for t in texts)
    ANSWERS["multi"] = "See note"
    assert v.commit_line("callout", fitz.Point(100, 300), fitz.Point(300, 250))
    win._refresh_panels()
    types = [i["type"] for i in win.markups.items]
    assert "Text Box" in types and "Pen" in types


def test_create_split_compare_in_app(win, tmp_path):
    t = tmp_path / "memo.txt"
    t.write_text("Memo to file", encoding="utf-8")
    from PySide6.QtWidgets import QFileDialog as FD
    FD.getOpenFileNames = staticmethod(lambda *a, **k: ([str(t)], ""))
    made = win.create_pdf()
    assert made and "Memo to file" in made[0].doc[0].get_text()
    win.tabs.setCurrentIndex(0)
    ANSWERS["item"] = "Every N pages"
    ANSWERS["int"] = 1
    FD.getExistingDirectory = staticmethod(lambda *a, **k: str(tmp_path / "parts"))
    out = win.split_doc()
    assert len(out) == 3
    other = str(tmp_path / "rev.pdf")
    make_sample.make(other)
    d = fitz.open(other)
    d[0].draw_line((50, 700), (500, 700), width=3)
    d.saveIncr()
    d.close()
    ANSWERS["open"] = other
    v, stats = win.compare_visual()
    assert stats[0] > 0 and stats[1] == 0


def test_switching_tools_keeps_a_drawn_shape(win):
    """GUI user test r42 F01: an area drawn but not yet added vanished
    when another tool was picked; it's added instead."""
    import fitz as _f
    v = win._view
    before = len(list(v.pg.annots()))
    v.set_tool("add_polygon")
    v._pts = [_f.Point(100, 100), _f.Point(220, 100), _f.Point(220, 200)]
    v.set_tool("add_line")
    assert len(list(v.pg.annots())) == before + 1
    v._pts = [_f.Point(100, 100)]         # one point: nothing to keep
    v.set_tool(None)
    assert len(list(v.pg.annots())) == before + 1


def test_tool_switch_keeps_only_real_drawn_shapes(win):
    """Chief review Q3: switching tools keeps a half-drawn area or line
    only - never a cut-out, too few points, or a shape Escape cleared."""
    import fitz as _f
    v = win._view
    before = len(list(v.pg.annots()))
    v.set_tool("measure_cutout")
    v._pts = [_f.Point(100, 100), _f.Point(220, 100), _f.Point(220, 200)]
    v.set_tool("add_line")
    v.set_tool("add_polygon")
    v._pts = [_f.Point(100, 100), _f.Point(220, 100)]     # 2 of 3 points
    v.set_tool("add_line")
    v.set_tool("add_polygon")
    v._pts = [_f.Point(100, 100), _f.Point(220, 100), _f.Point(220, 200)]
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtCore import QEvent
    v.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Escape,
                              Qt.NoModifier))
    v.set_tool("add_line")
    assert len(list(v.pg.annots())) == before


def test_snapshot_feedback_and_png(win, tmp_path, qapp):
    """PM review NW-01: the snapshot area flashes, a note offers Save as
    PNG, and a whole big sheet is copied smaller, not as ~104 MB."""
    import fitz as _f
    from app.viewer import PdfView
    v = win._view
    assert v.snapshot(_f.Rect(50, 50, 250, 150)) == 1
    assert v._snap_flash is not None
    toast = win._snap_toast
    from PySide6.QtWidgets import QLabel
    assert not toast.isHidden()         # shown (the test window isn't)
    assert any("Snapshot copied" in w.text()
               for w in toast.findChildren(QLabel))
    out = win.save_snapshot_png(str(tmp_path / "s.png"))
    assert out and open(out, "rb").read(4) == b"\x89PNG"
    big = _f.Rect(0, 0, 36 * 72, 24 * 72)
    dpi = PdfView.snapshot_dpi(big)
    assert dpi < 200
    assert 36 * 24 * dpi * dpi <= PdfView.SNAPSHOT_MAX_PX
    assert PdfView.snapshot_dpi(_f.Rect(0, 0, 200, 100)) == 200


def test_fit_page_keeps_the_sheet_above_the_page_bar(win, qapp):
    """GUI user test r42 F12: at Fit Page the floating page bar hid the
    title block; the sheet now fits above it."""
    win.show()
    qapp.processEvents()
    nav = win.page_nav
    nav.sync()
    qapp.processEvents()
    win.fit_page()
    qapp.processEvents()
    if nav.isVisible():
        assert nav.reserve() > 0
        vp = win._scroll.viewport()
        r = win._view.pg.rect
        assert r.height * win._view.zoom <= vp.height() - nav.reserve()
    win.hide()


def test_area_and_length_ask_for_a_name(win, monkeypatch):
    """GUI user test r42 F08: measurements were all 'Area' / 'Length'."""
    from PySide6.QtWidgets import QInputDialog as _QID
    import fitz as _f
    v = win._view
    assert v.calibrate(240.0, real=24, unit="ft", all_pages=False)
    asked = []
    monkeypatch.setattr(_QID, "getText", staticmethod(
        lambda *a, **k: (asked.append(k.get("text")) or "Carpet", True)))
    win.set_tool("measure_area")
    assert v.style.get("subject") == "Carpet"
    v._pts = [_f.Point(100, 100), _f.Point(220, 100), _f.Point(220, 200)]
    v._finish_points()
    from app import annotate
    groups = {i.get("group") for i in annotate.takeoff_items(v.doc)}
    assert "Carpet" in groups
    win.set_tool(None)
    win.set_tool("measure_area")              # suggests the last name
    assert asked[-1] == "Carpet"
    monkeypatch.setattr(_QID, "getText",
                        staticmethod(lambda *a, **k: ("", False)))
    win.set_tool(None)
    win.set_tool("measure_length")            # cancel: still measures
    assert v.tool == "measure_length" and not v.style.get("subject")


def test_printing_shows_page_n_of_total(win, tmp_path, monkeypatch):
    """Nov 3: printing showed only a spinning cursor; now "Printing page
    2 of 3" with Cancel."""
    from PySide6.QtPrintSupport import QPrinter

    class Raster(QPrinter):           # print the pictures, as to a printer
        def outputFileName(self):
            return ""

    class Prog:
        def __init__(self, stop_at=None):
            self.labels, self.stop_at, self.n = [], stop_at, 0

        def setLabelText(self, t):
            self.labels.append(t)

        def setValue(self, v):
            self.n = v

        def wasCanceled(self):
            return self.stop_at is not None and self.n >= self.stop_at

        def close(self):
            pass
    doc = win._view.doc
    total = min(3, doc.page_count)
    for stop, want in ((None, True), (1, False)):
        prog = Prog(stop)
        monkeypatch.setattr(win, "_print_progress", lambda t, p=prog: p)
        p = Raster(QPrinter.ScreenResolution)
        p.setOutputFormat(QPrinter.PdfFormat)
        QPrinter.setOutputFileName(p, str(tmp_path / f"r{stop}.pdf"))
        p.setFromTo(1, total)
        assert win.print_to(p) is want
        assert prog.labels[0].startswith(f"Printing page 1 of {total}")
        if want:
            assert len(prog.labels) == total
        else:
            assert len(prog.labels) == 2            # stopped on page 2
    real = type(win)._print_progress(win, 5)          # the real window
    assert real is not None and real.maximum() == 5
    real.close()


def test_print_preview_pages_and_paper(win, tmp_path):
    """Nov 3: File > Print Preview shows each page on its paper, one at a
    time, and prints the pages chosen there."""
    from PySide6.QtPrintSupport import QPrinter
    from app.print_preview import PrintPreview, fit, preview_image
    from PySide6.QtCore import QRectF
    # a 36x24 sheet on a letter page's printable area keeps its shape
    x, y, w, h = fit(3600, 2400, QRectF(0, 0, 500, 700))
    assert (w, h) == (500, pytest.approx(500 * 2 / 3))
    doc = win._view.doc
    p = QPrinter(QPrinter.HighResolution)
    img = preview_image(doc[0], p, long_px=400)
    assert max(img.width(), img.height()) == pytest.approx(400, abs=2)
    dlg = PrintPreview(doc, p, current=0, parent=win)
    assert dlg.where.text() == f"Page 1 of {doc.page_count}"
    dlg.step(1)
    assert dlg.page == min(1, doc.page_count - 1)
    assert dlg.pages() == list(range(doc.page_count))      # All
    dlg.cur_rb.setChecked(True)
    assert dlg.pages() == [dlg.page]
    dlg.some_rb.setChecked(True)
    dlg.range.setText("1, 2")
    assert dlg.pages() == [0, 1][:doc.page_count]
    out = str(tmp_path / "preview.pdf")
    p.setOutputFormat(QPrinter.PdfFormat)
    p.setOutputFileName(out)
    assert win.print_preview(dialog=dlg)
    assert fitz.open(out).page_count == len(dlg.pages())
    assert win.command("Print Preview") is not None


def test_hold_the_wheel_and_drag_to_pan(win, qapp):
    """Nov 3 (Jon): pan with the mouse's scroll-wheel button."""
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    v = win._view
    v.set_zoom(4.0)
    qapp.processEvents()
    sa = v._scroller()
    assert sa is not None
    h, vb = sa.horizontalScrollBar(), sa.verticalScrollBar()
    h.setValue(h.maximum() // 2)
    vb.setValue(vb.maximum() // 2)
    x0, y0 = h.value(), vb.value()

    def ev(kind, pos, button, buttons):
        p = QPointF(*pos)
        return QMouseEvent(kind, p, v.mapToGlobal(p.toPoint()).toPointF(),
                           button, buttons, Qt.NoModifier)
    v.mousePressEvent(ev(QEvent.MouseButtonPress, (300, 300),
                         Qt.MiddleButton, Qt.MiddleButton))
    assert v.cursor().shape() == Qt.ClosedHandCursor
    v.mouseMoveEvent(ev(QEvent.MouseMove, (200, 250), Qt.NoButton,
                        Qt.MiddleButton))
    assert (h.value(), vb.value()) == (x0 + 100, y0 + 50)
    v.mouseReleaseEvent(ev(QEvent.MouseButtonRelease, (200, 250),
                           Qt.MiddleButton, Qt.NoButton))
    assert v._mpan is None and v.cursor().shape() != Qt.ClosedHandCursor
