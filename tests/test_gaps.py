"""Features that close the gap with Bluebeam: line styles, hatches,
volume/angle/radius/diameter, viewports, legends, importing and
translating markups, custom columns and statuses, Quantity Link, layers."""
import os
import zipfile

import fitz
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import (annotate, columns, legend, qlink, settings,  # noqa: E402
                 styles, takeoff)
from test_gui import ANSWERS, win, qapp                     # noqa: E402,F401

P = fitz.Point


def _doc():
    d = fitz.open()
    d.new_page(width=800, height=600)
    return d


_PAGES = []


def _annots(doc, pno=0):
    page = doc[pno]
    _PAGES.append(page)          # annotations die with their Page object
    return list(page.annots())


@pytest.fixture(autouse=True)
def _own_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", None)


# ---- line styles and hatch -------------------------------------------------------

def test_line_style_on_new_and_existing_markups():
    d = _doc()
    op = annotate.new_op("add_rect", 0, rect=[100, 100, 200, 160],
                         dashes=[6, 2, 1, 2])
    assert annotate.apply_op(d, op)
    a = _annots(d)[0]
    assert [round(x) for x in a.border["dashes"]] == [6, 2, 1, 2]
    annotate.apply_op(d, annotate.new_op("set_annot", 0, target=op["id"],
                                         dashes=[]))
    assert not (_annots(d)[0].border.get("dashes") or [])
    styles.save_line_style("Fence", [10, 2, 2, 2, 2, 2])
    assert styles.line_styles()["Fence"] == [10, 2, 2, 2, 2, 2]


def test_hatch_follows_its_shape():
    d = _doc()
    op = annotate.new_op("add_polygon", 0,
                         pts=[[100, 100], [300, 100], [300, 200], [100, 200]],
                         hatch="Cross Hatch", color=[0, 0, 1])
    assert annotate.apply_op(d, op)
    a = _annots(d)
    hatch = [x for x in a if annotate.is_hatch(d, x)]
    assert len(hatch) == 1 and annotate.tag_of(hatch[0]) == op["id"]
    strokes = hatch[0].vertices
    assert len(strokes) > 20                      # many short lines
    for s in strokes:                             # all inside the shape
        for x, y in s:
            assert 99 <= x <= 301 and 99 <= y <= 201
    # not listed as a markup of its own
    assert [m["type"] for m in annotate.markup_items(d)] == ["Polygon"]
    # recolor redraws it in the new color; "None" removes it
    annotate.apply_op(d, annotate.new_op("set_annot", 0, target=op["id"],
                                         color=[1, 0, 0]))
    h = [x for x in _annots(d) if annotate.is_hatch(d, x)][0]
    assert list(h.colors["stroke"]) == pytest.approx([1, 0, 0])
    annotate.apply_op(d, annotate.new_op("set_annot", 0, target=op["id"],
                                         hatch=[]))
    assert not [x for x in _annots(d) if annotate.is_hatch(d, x)]
    # deleting the shape deletes its hatch too
    op2 = annotate.new_op("add_rect", 0, rect=[400, 100, 500, 200],
                          hatch=[[0, 5]])
    annotate.apply_op(d, op2)
    assert any(annotate.is_hatch(d, x) for x in _annots(d))
    annotate.apply_op(d, annotate.new_op("delete_annot", 0, target=op2["id"]))
    assert not any(annotate.is_hatch(d, x) for x in _annots(d))


def test_custom_hatch_and_parsing():
    assert styles.parse_hatch("30/5, 120/10") == [(30.0, 5.0), (120.0, 10.0)]
    assert styles.parse_dashes("4, 2") == [4.0, 2.0]
    styles.save_hatch("Roof", [(30, 5), (120, 10)])
    assert styles.hatches()["Roof"] == [(30.0, 5.0), (120.0, 10.0)]
    segs = styles.hatch_segments([(0, 0), (100, 0), (100, 40), (0, 40)],
                                 [(0, 10)])
    assert len(segs) == 4 and segs[0] == ((0.0, 5.0), (100.0, 5.0))


# ---- new measurements ------------------------------------------------------------

def test_angle_and_unit_helpers():
    assert takeoff.angle([P(10, 0), P(0, 0), P(0, 10)]) == pytest.approx(90)
    assert takeoff.angle([P(10, 0), P(0, 0), P(-10, 0)]) == pytest.approx(180)
    assert takeoff.convert(6, "in", "ft") == pytest.approx(0.5)
    assert takeoff.convert(1, "m", "ft") == pytest.approx(3.28084)


def test_volume_angle_radius_diameter_tools(win):
    v = win._view
    assert v.calibrate(240.0, real=24, unit="ft", all_pages=False)  # 10/ft
    ANSWERS["text"] = '6"'
    assert v.commit_points("measure_volume", [P(100, 100), P(300, 100),
                                              P(300, 300), P(100, 300)])
    vol = [i for i in annotate.takeoff_items(v.doc) if i["type"] == "volume"]
    assert vol[0]["value"] == pytest.approx(400 * 0.5)       # 20x20 ft x 6"
    assert vol[0]["unit"] == "cu ft"
    assert v.commit_points("measure_angle", [P(400, 100), P(400, 200),
                                             P(500, 200)])
    ang = [i for i in annotate.takeoff_items(v.doc) if i["type"] == "angle"]
    assert ang[0]["value"] == pytest.approx(90)
    assert v.commit_line("measure_radius", P(200, 400), P(250, 400))
    assert v.commit_line("measure_diameter", P(400, 400), P(500, 400))
    got = {i["type"]: i["value"] for i in annotate.takeoff_items(v.doc)}
    assert got["radius"] == pytest.approx(5)
    assert got["diameter"] == pytest.approx(10)
    types = {m["type"] for m in annotate.markup_items(v.doc)}
    assert {"Volume", "Angle", "Radius", "Diameter"} <= types


# ---- viewports -------------------------------------------------------------------

def test_viewport_scale_applies_inside_its_box(win):
    v = win._view
    assert v.calibrate(180.0, real=10, unit="ft", all_pages=False)  # 18/ft
    # a detail at 1/2" = 1'-0" (36 pt per ft) in the corner
    assert v.add_viewport(fitz.Rect(400, 300, 700, 550),
                          scale=('1/2" = 1\'-0"', 36.0, "ft"), name="Detail A")
    vps = annotate.read_viewports(v.doc, v.page)
    assert [x["name"] for x in vps] == ["Detail A"]
    before = len(annotate.takeoff_items(v.doc))
    assert v.commit_line("measure_length", P(450, 400), P(522, 400))  # 72 pt
    assert v.commit_line("measure_length", P(50, 50), P(122, 50))
    vals = [i["value"] for i in annotate.takeoff_items(v.doc)][before:]
    assert sorted(vals) == pytest.approx([2.0, 4.0])   # 2 ft in the detail
    # the page scale is untouched, and the viewport can be removed
    assert annotate.read_scales(v.doc)[v.page]["ppu"] == pytest.approx(18)
    assert v.remove_viewport("Detail A")
    assert not annotate.read_viewports(v.doc, v.page)
    assert annotate.read_scales(v.doc)[v.page]["ppu"] == pytest.approx(18)


# ---- legends ---------------------------------------------------------------------

def test_legend_lists_markups_and_refreshes(win):
    v = win._view
    for pg in range(v.doc.page_count):
        for a in list(v.doc[pg].annots()):
            v.doc[pg].delete_annot(a)
    v.reset_page_cache()
    assert v.calibrate(240.0, real=24, unit="ft", all_pages=False)
    v.style["subject"] = "Slab"
    v.commit_points("measure_area", [P(100, 100), P(200, 100), P(200, 200),
                                     P(100, 200)])
    v.style["subject"] = ""
    v.commit_rect("add_cloud", fitz.Rect(300, 100, 380, 160))
    v.commit_rect("add_cloud", fitz.Rect(300, 200, 380, 260))
    rows = legend.rows(v.doc, v.page)
    labels = {r["label"]: r["qty"] for r in rows}
    assert labels["Cloud"] == "2"
    assert labels["Slab (Area)"].startswith("1  |  100.00 sq ft")
    assert v.add_legend(fitz.Rect(450, 50, 650, 100))
    legs = legend.legends_on(v.doc, v.page)
    assert len(legs) == 1
    # legend rows aren't markups of their own; the legend is one
    types = [m["type"] for m in annotate.markup_items(v.doc)]
    assert types.count("Legend") == 1
    v.commit_rect("add_cloud", fitz.Rect(300, 300, 380, 360))
    assert v.refresh_legends()
    assert len(legend.legends_on(v.doc, v.page)) == 1
    texts = [a.info.get("content") for a in v.pg.annots()
             if annotate.is_label(v.doc, a)]
    assert "3" in texts


# ---- import, translate -----------------------------------------------------------

def test_import_markups_keeps_measurements_together(win, tmp_path):
    src = fitz.open()
    src.new_page(width=612, height=792)
    annotate.apply_op(src, annotate.new_op(
        "add_line", 0, pts=[[100, 100], [300, 100]], label="10' 0\"",
        measure={"type": "length", "value": 10, "unit": "ft",
                 "group": "Wall"}))
    annotate.apply_op(src, annotate.new_op(
        "add_rect", 0, rect=[100, 200, 200, 260], color=[0, 0.5, 0],
        dashes=[6, 3]))
    annotate.apply_op(src, annotate.new_op("add_note", 0, pt=[50, 50],
                                           text="Check this"))
    path = str(tmp_path / "theirs.pdf")
    src.save(path)
    v = win._view
    before = len(list(v.pg.annots()))
    n = win.import_markups(path)
    assert n == 3                                   # three groups
    after = list(v.pg.annots())
    assert len(after) - before == 4                 # line + label + rect + note
    items = [i for i in annotate.takeoff_items(v.doc) if i["group"] == "Wall"]
    assert items and items[0]["value"] == pytest.approx(10)
    rect = [a for a in after if a.type[0] == fitz.PDF_ANNOT_SQUARE
            and (a.border or {}).get("dashes")]
    assert rect and list(rect[-1].colors["stroke"]) == pytest.approx(
        [0, 0.5, 0], abs=0.01)
    # undo takes the whole import back
    win.undo()
    assert len(list(win._view.doc[0].annots())) == before


def test_translate_markups(win):
    v = win._view
    v.apply_marks([(0, "add_note", {"pt": [60, 60], "text": "door missing"}),
                   (0, "add_textbox", {"rect": [100, 300, 260, 330],
                                       "text": "verify height"})])
    n = win.translate_markups("Spanish",
                              texts_fn=lambda ts: [t.upper() for t in ts])
    assert n >= 2
    comments = {m["comment"] for m in annotate.markup_items(v.doc)}
    assert {"DOOR MISSING", "VERIFY HEIGHT"} <= comments


# ---- Markups List columns and statuses -------------------------------------------

def test_custom_columns_and_formula():
    d = _doc()
    annotate.apply_op(d, annotate.new_op("set_scale", 0, ppu=10, unit="ft"))
    annotate.apply_op(d, annotate.new_op(
        "add_polygon", 0, pts=[[0, 0], [100, 0], [100, 100], [0, 100]],
        label="100 sq ft", measure={"type": "area", "value": 100,
                                    "unit": "sq ft", "group": "Floor"}))
    columns.set_columns(d, [
        {"name": "Unit Price", "type": "number"},
        {"name": "Cost", "type": "formula", "formula": "Area * Unit_Price"},
        {"name": "Room", "type": "choice", "choices": ["Lobby", "Office"]},
        {"name": "Bad", "type": "formula", "formula": "Nope * 2"}])
    items = annotate.markup_items(d)
    key = columns.key_of(items[0])
    columns.set_value(d, key, "Unit Price", 4.5)
    columns.set_value(d, key, "Room", "Lobby")
    vals = columns.values_for(d, items)[key]
    assert vals["Cost"] == "450.00" and vals["Room"] == "Lobby"
    assert vals["Bad"].startswith("#ERR")
    # survives a save
    d2 = fitz.open(stream=d.tobytes(), filetype="pdf")
    assert [c["name"] for c in columns.read(d2)["columns"]][:2] == \
        ["Unit Price", "Cost"]


def test_custom_statuses():
    styles.set_custom_statuses(["Field Verify", "RFI Sent", ""])
    sts = annotate.statuses()
    assert sts[:6] == annotate.STATUSES
    assert sts[6:] == ["Field Verify", "RFI Sent", annotate.REVISED]


# ---- Quantity Link -----------------------------------------------------------------

def test_quantity_link_writes_workbook(tmp_path):
    d = _doc()
    for v in (10, 15):
        annotate.apply_op(d, annotate.new_op(
            "add_line", 0, pts=[[0, 0], [v * 10, 0]], label=f"{v}'",
            measure={"type": "length", "value": v, "unit": "ft",
                     "group": "Base"}))
    xlsx = str(tmp_path / "q.xlsx")
    assert qlink.update(d, xlsx) is None
    with zipfile.ZipFile(xlsx) as z:
        names = z.namelist()
        wb = z.read("xl/workbook.xml").decode()
        sheets = [z.read(n).decode() for n in names
                  if n.startswith("xl/worksheets/")]
    assert "Summary" in wb and "Measurements" in wb
    assert any(">25<" in s or ">25.0<" in s for s in sheets)
    doc_path = str(tmp_path / "plan.pdf")
    qlink.set_link(doc_path, xlsx)
    assert qlink.link_for(doc_path) == xlsx
    qlink.set_link(doc_path, None)
    assert qlink.link_for(doc_path) is None


# ---- layers ------------------------------------------------------------------------

def test_layers(win):
    from app.gap_dialogs import set_layer_visible
    v = win._view
    v.style["layer"] = "Electrical"
    v.commit_rect("add_rect", fitz.Rect(100, 100, 200, 200))
    xref = annotate.ocg_xref(v.doc, "Electrical", create=False)
    assert xref
    shapes = [a for a in v.pg.annots() if a.get_oc() == xref]
    assert len(shapes) == 1
    assert v.annot_at(P(150, 100)).get_oc() == xref
    set_layer_visible(v, xref, False)
    assert not v.doc.get_ocgs()[xref]["on"]
    hit = v.annot_at(P(150, 100))                  # hidden: not clickable
    assert hit is None or hit.get_oc() != xref
    set_layer_visible(v, xref, True)
    v.style.pop("layer")
    v.select(v.annot_at(P(150, 100)))
    v.change_selected(layer="Plumbing")
    px = annotate.ocg_xref(v.doc, "Plumbing", create=False)
    assert [a.get_oc() for a in v.pg.annots()
            if a.type[0] == fitz.PDF_ANNOT_SQUARE][-1] == px
