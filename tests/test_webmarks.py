"""Takeoff marks from the browser add-on's viewer (app/webmarks.py), Nov
27: the browser sends where the clicks were and the scale; QuantiSheet
works the quantities out with its own takeoff code. Made-up data only."""
import base64
import io
import json
import os
import struct

import fitz
import pytest

from app import annotate, browserhost, webmarks

SCALE = {"page": 0, "ppu": 18.0, "unit": "ft", "name": '1/4" = 1\'-0"',
         "all": False}
# PDF coordinates (y up), on a 612 x 792 page: a 180 pt run and a 180 pt
# square; at 18 points to the foot that is 10 ft and 100 sq ft
LENGTH = {"page": 0, "type": "length", "pts": [[72, 700], [252, 700]],
          "group": "Walls"}
AREA = {"page": 0, "type": "area", "group": "Slab",
        "pts": [[72, 400], [252, 400], [252, 580], [72, 580]]}
COUNT = {"page": 0, "type": "count", "pts": [[300, 300]], "group": "Doors"}


def _doc(pages=1):
    doc = fitz.open()
    for _ in range(pages):
        doc.new_page(width=612, height=792)
    return doc


def _data(*marks, scales=(SCALE,)):
    return {"v": 1, "scales": list(scales), "marks": list(marks)}


def test_quantities_are_worked_out_here_from_the_clicks():
    doc = _doc()
    marks, skipped = webmarks.build(doc, _data(LENGTH, AREA, COUNT, COUNT))
    assert skipped == 0
    kinds = [k for _p, k, _pl in marks]
    assert kinds == ["set_scale", "add_line", "add_polygon", "add_count",
                     "add_count"]
    assert marks[0][2] == {"ppu": 18.0, "unit": "ft",
                           "name": '1/4" = 1\'-0"'}
    line, poly = marks[1][2], marks[2][2]
    assert line["measure"] == {"type": "length", "value": 10.0, "unit": "ft",
                               "group": "Walls", "method": "browser viewer"}
    assert poly["measure"]["value"] == 100.0
    assert poly["measure"]["type"] == "area"
    assert poly["measure"]["unit"].startswith("sq")
    # the browser's y (up from the bottom) became the page's (down)
    assert line["pts"] == [[72.0, 92.0], [252.0, 92.0]]
    assert [m[2]["n"] for m in marks[3:]] == [1, 2]
    # and the marks land in the document as QuantiSheet's own takeoff
    for pno, kind, payload in marks:
        assert annotate.apply_op(doc, annotate.new_op(kind, pno, **payload))
    items = annotate.takeoff_items(doc)
    got = sorted((it["type"], it["group"], it["value"]) for it in items)
    assert got == [("area", "Slab", 100.0), ("count", "Doors", 1),
                   ("count", "Doors", 1), ("length", "Walls", 10.0)]


def test_no_scale_means_not_measured_never_guessed():
    doc = _doc(2)
    two = dict(LENGTH, page=1)
    marks, skipped = webmarks.build(doc, _data(LENGTH, two, COUNT))
    assert skipped == 1                      # page 2 has no scale
    assert [(p, k) for p, k, _pl in marks] == [
        (0, "set_scale"), (0, "add_line"), (0, "add_count")]
    every = dict(SCALE, all=True)
    marks, skipped = webmarks.build(doc, _data(LENGTH, two, scales=[every]))
    assert skipped == 0 and marks[0][2]["pages"] == [0, 1]


def test_a_scale_the_drawing_already_has_is_used():
    doc = _doc()
    annotate.apply_op(doc, annotate.new_op("set_scale", 0, ppu=36.0,
                                           unit="ft"))
    marks, skipped = webmarks.build(doc, _data(LENGTH, scales=[]))
    assert skipped == 0 and marks[0][2]["measure"]["value"] == 5.0


def test_what_the_browser_sends_is_checked_not_trusted():
    assert webmarks.clean({"v": 2}) is None
    assert webmarks.clean([1, 2]) is None
    bad = _data(
        {"page": 0, "type": "volume", "pts": [[0, 0], [1, 1]]},
        {"page": -1, "type": "length", "pts": [[0, 0], [1, 1]]},
        {"page": 0, "type": "length", "pts": [[0, 0]]},
        {"page": 0, "type": "length", "pts": [[0, 0], [float("nan"), 1]]},
        {"page": 0, "type": "length", "pts": [[0, 0], ["1", 1]]},
        {"page": True, "type": "count", "pts": [[0, 0]]},
        {"page": 0, "type": "area", "pts": [[0, 0], [1, 1]]},
        "junk",
        scales=[{"page": 0, "ppu": 0, "unit": "ft"},
                {"page": 0, "ppu": 18, "unit": "parsecs"},
                {"page": 0, "ppu": float("inf"), "unit": "ft"}, 7])
    assert webmarks.clean(bad) == {"v": 1, "scales": [], "marks": []}
    ok = webmarks.clean(_data(dict(COUNT, group="Doors\x00\n" + "x" * 90,
                                   extra="ignored", value=999)))
    m = ok["marks"][0]
    assert set(m) == {"page", "type", "pts", "group"}    # no value taken
    assert "\x00" not in m["group"] and len(m["group"]) == 60
    # a page the drawing doesn't have is left out, not an error
    marks, skipped = webmarks.build(_doc(), _data(dict(LENGTH, page=5)))
    assert skipped == 1 and len(marks) == 1


def test_the_marks_ride_beside_the_pdf_and_are_taken_once(tmp_path):
    pdf = tmp_path / "plan.pdf"
    doc = _doc()
    doc.save(str(pdf))
    doc.close()
    assert not webmarks.write(str(pdf), {"v": 1, "marks": []})
    assert webmarks.write(str(pdf), _data(LENGTH, COUNT))
    side = webmarks.sidecar(str(pdf))
    assert os.path.isfile(side)

    class View:
        method_hint = "trace"
        applied = None

        def __init__(self, d):
            self.doc = d

        def apply_marks(self, marks):
            assert self.method_hint is None      # "browser viewer" stays
            self.applied = list(marks)
            return len(self.applied)
    v = View(fitz.open(str(pdf)))
    assert webmarks.take(v, str(pdf)) == (2, 0)
    assert v.method_hint == "trace" and len(v.applied) == 3
    assert not os.path.exists(side)
    assert webmarks.take(v, str(pdf)) is None
    with open(side, "w") as f:                   # junk beside a PDF
        f.write("{not json")
    assert webmarks.take(v, str(pdf)) is None and not os.path.exists(side)
    v.doc.close()


def test_the_browser_line_keeps_the_marks_beside_the_saved_pdf(tmp_path):
    pdf = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
    msgs = [{"type": "begin", "name": "plan.pdf"},
            {"type": "data", "b64": base64.b64encode(pdf).decode()},
            {"type": "end", "marks": _data(LENGTH)}]
    wire = b"".join(struct.pack("<I", len(b)) + b for b in
                    (json.dumps(m).encode() for m in msgs))
    opened = []
    rx = browserhost.Receiver(where=str(tmp_path), opener=opened.append)
    assert browserhost.serve(io.BytesIO(wire), io.BytesIO(), rx) == 0
    assert sorted(os.listdir(tmp_path)) == ["plan.pdf",
                                            "plan.pdf.qsweb.json"]
    kept = json.load(open(webmarks.sidecar(opened[0])))
    assert kept["marks"][0]["type"] == "length"
    # marks that are not marks never stop the PDF opening
    rx2 = browserhost.Receiver(where=str(tmp_path / "b"),
                               opener=opened.append)
    msgs[2] = {"type": "end", "marks": {"v": 9, "run": "calc"}}
    wire = b"".join(struct.pack("<I", len(b)) + b for b in
                    (json.dumps(m).encode() for m in msgs))
    browserhost.serve(io.BytesIO(wire), io.BytesIO(), rx2)
    assert os.listdir(tmp_path / "b") == ["plan.pdf"] and len(opened) == 2


@pytest.fixture
def win(tmp_path, monkeypatch):
    pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtWidgets import QApplication, QMessageBox
    from app import settings
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", None)
    monkeypatch.setenv("QUANTISHEET_SMOKE", "1")
    for name in ("information", "warning"):
        monkeypatch.setattr(QMessageBox, name,
                            staticmethod(lambda *a, **k: 0))
    from app.main_window import MainWindow
    w = MainWindow()
    yield w
    for i in range(w.tabs.count()):
        t = w.tabs.widget(i)
        if getattr(t, "view", None) is not None:
            t.view.dirty = False
    w.close()
    app.processEvents()


def test_opening_the_pdf_brings_the_browsers_takeoff_in(win, tmp_path):
    pdf = tmp_path / "A-101 Made-up Plan.pdf"
    doc = _doc()
    doc.save(str(pdf))
    doc.close()
    webmarks.write(str(pdf), _data(LENGTH, AREA, COUNT))
    assert win.open_path(str(pdf))
    v = win._view
    items = annotate.takeoff_items(v.doc)
    assert sorted((it["type"], it["value"]) for it in items) == [
        ("area", 100.0), ("count", 1), ("length", 10.0)]
    assert annotate.read_scales(v.doc)[0]["ppu"] == 18.0
    assert not os.path.exists(webmarks.sidecar(str(pdf)))
    assert v.dirty                              # the user chooses to save
    win.undo()                                  # one step takes it back
    assert annotate.takeoff_items(v.doc) == []


def test_a_page_stored_sideways_measures_the_same():
    """Nov 28: tried in a test browser on a page with /Rotate 90 - a line
    drawn left to right on screen arrives as a line up the PDF page, and
    the scale by two points gave back the length typed in."""
    doc = fitz.open()
    doc.new_page(width=612, height=792).set_rotation(90)
    assert doc[0].rect.width == 792              # shown sideways
    data = _data({"page": 0, "type": "length", "group": "Run",
                  "pts": [[369, 695], [369, 719]]},
                 scales=[{"page": 0, "ppu": 2.4, "unit": "ft",
                          "name": "10 ft by two points", "all": False}])
    marks, skipped = webmarks.build(doc, data)
    assert skipped == 0
    line = marks[1][2]
    assert line["measure"]["value"] == 10.0
    # the marks' own coordinates are the page before it is turned
    assert line["pts"] == [[369.0, 97.0], [369.0, 73.0]]
    assert annotate.apply_op(doc, annotate.new_op("add_line", 0, **line))
    # and on screen the line lies inside the sideways page
    page = doc[0]                    # kept: its annotations need it
    a = next(page.annots())
    shown = (a.rect * page.rotation_matrix).normalize()
    assert page.rect.contains(shown)
    assert shown.width > shown.height            # left to right on screen


CUT = {"page": 0, "type": "cutout", "group": "",
       "pts": [[100, 430], [136, 430], [136, 466], [100, 466]]}   # 2 x 2 ft


def test_a_cut_out_is_taken_off_the_area_it_was_drawn_in(win, tmp_path):
    """Nov 28: a cut-out drawn in the browser comes off its area the way
    QuantiSheet's own Cutout tool does it: 100 sq ft less a 2 ft square."""
    pdf = tmp_path / "A-102 Made-up Plan.pdf"
    doc = _doc()
    doc.save(str(pdf))
    doc.close()
    stray = dict(CUT, pts=[[400, 100], [436, 100], [436, 136], [400, 136]])
    webmarks.write(str(pdf), _data(AREA, CUT, stray))
    assert win.open_path(str(pdf))
    v = win._view
    items = annotate.takeoff_items(v.doc)
    assert [(it["type"], it["group"], it["value"]) for it in items] == [
        ("area", "Slab", 96.0)]                  # net of the cut-out
    cuts = [it for it in annotate.takeoff_items(v.doc, include_cutouts=True)
            if it["type"] == annotate.CUTOUT]
    assert [c["value"] for c in cuts] == [4.0]   # the stray one was left out
    win.undo()                                   # the cut-out
    assert annotate.takeoff_items(v.doc)[0]["value"] == 100.0
    win.undo()                                   # then the area
    assert annotate.takeoff_items(v.doc) == []


def test_cut_outs_wait_for_their_areas():
    doc = _doc()
    marks, skipped = webmarks.build(doc, _data(AREA, CUT))
    assert [k for _p, k, _pl in marks] == ["set_scale", "add_polygon"]
    assert skipped == 0
    # before the area is in the document there is nothing to take it off
    assert webmarks.cutouts(doc, _data(AREA, CUT)) == ([], 1)
    for pno, kind, payload in marks:
        annotate.apply_op(doc, annotate.new_op(kind, pno, **payload))
    more, left = webmarks.cutouts(doc, _data(AREA, CUT))
    assert left == 0 and len(more) == 1
    m = more[0][2]["measure"]
    assert (m["type"], m["value"], m["group"]) == ("cutout", 4.0, "Slab")
    assert m["parent"] and more[0][2]["label"].startswith("Cutout -4.00")
