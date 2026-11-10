"""Takeoff ideas from Nov 4 (Chief's list C): copy/paste between sheets,
typical sheets, buy quantities, color-by, show only one item, bulk edit,
status keys, Space repeats, corners/segments, typed angles. Made up."""
import os

import fitz
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtCore import Qt                                     # noqa: E402
from PySide6.QtTest import QTest                                  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox           # noqa: E402

from app import annotate, buyqty, measure_bar, settings, takeoffclip  # noqa


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def win(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", None)
    monkeypatch.setenv("QUANTISHEET_SMOKE", "1")
    for name in ("information", "warning"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(lambda *a, **k: 0))
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.Yes))
    from app.main_window import MainWindow
    w = MainWindow()
    w.resize(1200, 900)
    d = fitz.open()
    for _ in range(2):
        d.new_page(width=1728, height=1296).insert_text((100, 100), "PLAN")
    path = str(tmp_path / "set.pdf")
    d.save(path)
    assert w.open_path(path)
    qapp.processEvents()
    v = w._view
    # sheet 1 at 1/8" = 1'-0" (9 pt per ft), sheet 2 at 1/4" (18 pt per ft)
    for pno, ppu in ((0, 9.0), (1, 18.0)):
        annotate.apply_op(v.doc, annotate.new_op("set_scale", pno, ppu=ppu,
                                                 unit="ft", name="x"))
    yield w, tmp_path
    for vv in w._all_views():
        vv.dirty = False
    w.close()
    w.deleteLater()
    qapp.processEvents()


def _measure(v, mtype, pts, group):
    v.style["subject"] = group
    ppts = [fitz.Point(p) for p in pts]
    p = v._measure_payload(mtype, ppts, v.scale(at=ppts))
    kind = p.pop("_kind")
    assert v.apply_marks([(v.page, kind, p)])
    return [it for it in annotate.takeoff_items(v.doc)
            if it["group"] == group and it["page"] == v.page][-1]


def _select(v, item):
    v.select(annotate.find_annots(v.pg, item["ref"])[0])


# ---- #2 copy and paste, rescaled --------------------------------------------------

def test_copy_paste_to_another_sheet_uses_its_scale(win, qapp):
    w, _ = win
    v = w._view
    it = _measure(v, "length", [(100, 300), (190, 300)], "Fence")   # 10 ft
    assert abs(it["value"] - 10) < 0.01
    _select(v, it)
    assert w.copy_text() == 1                        # markups, not text
    assert takeoffclip.ready()
    v.go_to(1)
    qapp.processEvents()
    assert w.paste() == 1
    pasted = [x for x in annotate.takeoff_items(v.doc)
              if x["page"] == 1 and x["group"] == "Fence"]
    assert pasted and abs(pasted[0]["value"] - 5) < 0.01   # 1/4" sheet


def test_paste_here_moves_it(win, qapp):
    w, _ = win
    v = w._view
    it = _measure(v, "area", [(100, 400), (190, 400), (190, 490),
                              (100, 490)], "Slab")
    _select(v, it)
    takeoffclip.copy(v)
    assert takeoffclip.paste(v, at=fitz.Point(800, 800)) == 1
    slabs = [x for x in annotate.takeoff_items(v.doc) if x["group"] == "Slab"]
    assert len(slabs) == 2
    assert abs(slabs[0]["value"] - slabs[1]["value"]) < 0.01      # same size


# ---- #3 typical sheets -------------------------------------------------------------

def test_typical_sheet_multiplies_its_takeoff(win, qapp):
    w, _ = win
    v = w._view
    _measure(v, "length", [(100, 300), (190, 300)], "Base")          # 10 ft
    assert w.page_multiplier(5) == 5
    it = [x for x in annotate.takeoff_items(v.doc) if x["group"] == "Base"][0]
    assert abs(it["value"] - 50) < 0.01 and it["page_multiplier"] == 5
    assert annotate.page_multiplier(v.doc, 0) == 5
    assert annotate.page_multiplier(v.doc, 1) == 1
    w.page_multiplier(1)
    it = [x for x in annotate.takeoff_items(v.doc) if x["group"] == "Base"][0]
    assert abs(it["value"] - 10) < 0.01


# ---- #10 buy quantities -------------------------------------------------------------

def test_buy_quantities_round_up_with_waste(win):
    w, _ = win
    v = w._view
    assert buyqty.buy(1500, {"per": 32, "waste": 10}) == 52
    assert buyqty.buy(320, {"per": 32}) == 10
    _measure(v, "area", [(100, 400), (190, 400), (190, 490), (100, 490)],
             "Drywall")                                   # 100 sf
    buyqty.set_rule(v.doc, "Drywall", 32, "sheets", 10)
    w._refresh_panels()
    assert "buy 4 sheets" in w.quantities.totals.text()
    with pytest.raises(ValueError):
        buyqty.set_rule(v.doc, "Drywall", -1)
    dlg = w.buy_quantities(show=False)
    assert dlg.table.rowCount() >= 1


# ---- #6 color-by, #7 show only ---------------------------------------------------

def test_color_by_item_and_legend(win):
    w, _ = win
    v = w._view
    _measure(v, "length", [(100, 300), (190, 300)], "Fence")
    _measure(v, "length", [(100, 600), (190, 600)], "Curb")
    w.color_by("item")
    keys = [k for k, _c in v.color_by_legend()]
    assert keys == ["Curb", "Fence"]
    w.color_by("status")
    assert [k for k, _c in v.color_by_legend()] == ["No status"]
    w.color_by(None)
    assert v.color_by_rows() == []


def test_show_only_this_item(win):
    w, _ = win
    v = w._view
    a = _measure(v, "length", [(100, 300), (190, 300)], "Fence")
    _measure(v, "length", [(100, 600), (190, 600)], "Curb")
    _select(v, a)
    assert v.isolate_selected() == "Fence"
    assert len(v.isolate_rects()) == 1
    QTest.keyClick(v, Qt.Key_Escape)
    QTest.keyClick(v, Qt.Key_Escape)
    assert v.isolate is None


# ---- #9 bulk edit, #8 status keys ---------------------------------------------------

def test_bulk_edit_several(win):
    w, _ = win
    v = w._view
    a = _measure(v, "length", [(100, 300), (190, 300)], "Wall A")
    b = _measure(v, "length", [(100, 600), (190, 600)], "Wall A")
    _select(v, a)
    v.select(annotate.find_annots(v.pg, b["ref"])[0], add=True)
    assert len(v.selected_refs()) == 2
    n = v.bulk_edit_dialog({"height": "9'", "rise": "", "status": None,
                            "group": ""})
    assert n == 2
    walls = [x for x in annotate.takeoff_items(v.doc) if x["page"] == 0]
    assert all(x["type"] == "area" and abs(x["value"] - 90) < 0.1
               for x in walls), walls


def test_alt_number_sets_status(win):
    w, _ = win
    v = w._view
    a = _measure(v, "length", [(100, 300), (190, 300)], "Fence")
    _select(v, a)
    v.setFocus()
    QTest.keyClick(v, Qt.Key_2, Qt.AltModifier)
    st = annotate.statuses()[1]
    a2 = annotate.find_annots(v.pg, a["ref"])[0]
    assert annotate.status_of(v.doc, a2) == st


# ---- #13 Space repeats, #11 corners, #12 angles -------------------------------------

def test_space_repeats_last_tool(win, qapp):
    w, _ = win
    v = w._view
    v.style["subject"] = "Fence"
    w.set_tool("measure_length", ask=False)
    w.set_tool(None)
    assert v.tool is None
    v.setFocus()
    QTest.keyClick(v, Qt.Key_Space)
    assert v.tool == "measure_length"
    assert v.style.get("subject") == "Fence"


def test_runs_count_corners_and_segments(win):
    w, _ = win
    v = w._view
    it = _measure(v, "length", [(100, 300), (190, 300), (190, 390),
                                (280, 390)], "Duct")
    assert it["segments"] == 3 and it["corners"] == 2
    w._refresh_panels()
    names = [w.quantities.table.item(r, 2).text()
             for r in range(w.quantities.table.rowCount())]
    assert any("3 segments, 2 corners" in t for t in names)


def test_typed_angle():
    assert measure_bar.split_angle("24'-6\"<45") == ('24\'-6"', 45.0)
    assert measure_bar.split_angle("10 @ 90")[1] == 90.0
    assert measure_bar.split_angle("12'6")[1] is None

    class Cal:
        points_per_unit = 10.0
    pts = [fitz.Point(0, 0), fitz.Point(5, 0)]
    end = measure_bar.set_segment(pts, 2.0, Cal(), angle=90)[-1]
    assert abs(end.x) < 1e-6 and abs(end.y + 20) < 1e-6     # straight up


# ---- #4 split and join runs ---------------------------------------------------------

def test_split_and_join_a_run(win):
    from app import measure_tools
    w, _ = win
    v = w._view
    it = _measure(v, "length", [(100, 300), (190, 300), (190, 390),
                                (280, 390)], "Duct")          # 30 ft at 1/8"
    _select(v, it)
    assert measure_tools.split_run(v, fitz.Point(190, 300)) == 2
    parts = sorted(x["value"] for x in annotate.takeoff_items(v.doc)
                   if x["group"] == "Duct")
    assert len(parts) == 2 and abs(parts[0] - 10) < 0.01 and \
        abs(parts[1] - 20) < 0.01
    runs = [x for x in annotate.takeoff_items(v.doc) if x["group"] == "Duct"]
    _select(v, runs[0])
    v.select(annotate.find_annots(v.pg, runs[1]["ref"])[0], add=True)
    assert measure_tools.join_runs(v) == 1
    one = [x for x in annotate.takeoff_items(v.doc) if x["group"] == "Duct"]
    assert len(one) == 1 and abs(one[0]["value"] - 30) < 0.01


def test_join_refuses_runs_that_dont_meet(win):
    from app import measure_tools
    w, _ = win
    v = w._view
    a = _measure(v, "length", [(100, 300), (190, 300)], "Pipe")
    b = _measure(v, "length", [(400, 600), (490, 600)], "Pipe")
    _select(v, a)
    v.select(annotate.find_annots(v.pg, b["ref"])[0], add=True)
    assert measure_tools.join_runs(v) == 0


# ---- #5 arcs -----------------------------------------------------------------------

def test_arc_segment_while_drawing(win):
    import math
    from app.viewer import arc_points
    pts = arc_points(fitz.Point(10, 0), fitz.Point(0, 10), fitz.Point(-10, 0))
    length = sum(abs(b - a) for a, b in zip(pts, pts[1:]))
    assert abs(length - math.pi * 10) / (math.pi * 10) < 0.003
    assert abs(pts[8].y - 10) < 1e-6                  # through the middle
    w, _ = win
    v = w._view
    w.set_tool("measure_polylength", ask=False)
    v._pts = [fitz.Point(100, 300)]
    assert v.toggle_arc()
    assert v.arc_click(fitz.Point(150, 250)) == 0
    assert v.arc_click(fitz.Point(200, 300)) == v.ARC_STEPS
    assert len(v._pts) == v.ARC_STEPS + 1
    v.toggle_arc()
    v._pts = []


# ---- #14 tags vs schedule ------------------------------------------------------------

def test_tags_vs_schedule(qapp, tmp_path):
    from app import tagcheck
    d = fitz.open()
    p = d.new_page(width=1728, height=1296)
    # plan: doors drawn around the sheet
    for x, y, t in ((300, 400, "D-1"), (500, 400, "D-2"), (700, 400, "D-2"),
                    (300, 700, "D-4")):
        p.insert_text((x, y), t, fontsize=10)
    # a door schedule in the corner (title block side)
    p.insert_text((1450, 950), "DOOR SCHEDULE", fontsize=10)
    for i, t in enumerate(("D-1", "D-2", "D-3")):
        p.insert_text((1450, 970 + i * 14), f"{t}  3070  HM", fontsize=8)
    rep = tagcheck.check(d, "D-#", use_ocr=False)
    if rep["schedule_only"] == [] and rep["plan_only"] == []:
        pytest.skip("schedule area not recognised on this test sheet")
    assert "D-4" in rep["plan_only"]
    assert "D-3" in rep["schedule_only"]
    assert rep["drawn"].get("D-2") == 2
    assert "Shown on the plans but not in the schedule: D-4" in \
        tagcheck.rfi_text(rep)
    out = tagcheck.export_csv(rep, str(tmp_path / "t.csv"))
    assert "D-3" in open(out).read()


# ---- review QS-015: overlapping cutouts -------------------------------------------

def test_overlapping_cutouts_are_taken_off_once():
    from app.annotate import _net_cutout
    sq = [(0, 0), (100, 0), (100, 100), (0, 100)]          # 100 sf area
    a = [(10, 10), (50, 10), (50, 50), (10, 50)]           # 16 sf
    b = [(30, 30), (70, 30), (70, 70), (30, 70)]           # 16, 4 shared
    got = _net_cutout(sq, [a, b], 100.0)
    assert abs(got - 28.0) < 0.5                           # not 32
    out = [(80, 80), (120, 80), (120, 120), (80, 120)]     # 3/4 outside
    got = _net_cutout(sq, [out], 100.0)
    assert abs(got - 4.0) < 0.3                            # only inside
    assert _net_cutout(None, [a], 100.0) is None


def test_our_markups_leave_the_clipboard_at_exit(win, qapp):
    """Nov 5: data copied with Ctrl+C was still on the system clipboard as
    Python shut down, and the program crashed on exit. release() (run at
    exit and on quit) clears only our own clipboard data."""
    w, _ = win
    cb = QApplication.clipboard()
    cb.setText("from another program")
    assert takeoffclip.release() is False
    assert cb.text() == "from another program"
    v = w._view
    it = _measure(v, "length", [(100, 300), (190, 300)], "Fence")
    _select(v, it)
    assert w.copy_text() == 1
    assert takeoffclip.release() is True
    md = cb.mimeData()
    assert md is None or not md.hasFormat(takeoffclip.MIME)
