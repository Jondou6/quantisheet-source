"""PlanSwift-style features: assemblies, Auto Scale, Auto Bookmark."""
import os
import zipfile

import fitz
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import annotate, assemblies, sheets, takeoff     # noqa: E402
from test_gui import ANSWERS, win, qapp                    # noqa: E402,F401

WALL = 'Interior Wall - 2x4 @ 16" O.C.'
SLAB = 'Slab on Grade - 4"'
DOOR = "Door - Hollow Metal Frame & Wood Door"


@pytest.fixture(autouse=True)
def _own_library(tmp_path, monkeypatch):
    monkeypatch.setattr(assemblies, "LIBRARY_PATH",
                        str(tmp_path / "assemblies.json"))


def _job():
    """A 1/4" = 1'-0" sheet with a 40' wall (one corner), a 1000 sf slab
    and two doors."""
    d = fitz.open()
    d.new_page(width=2592, height=1728)
    op = annotate.new_op
    annotate.apply_op(d, op("set_scale", 0, ppu=18, unit="ft"))
    annotate.apply_op(d, op("add_polyline", 0,
                            pts=[[100, 100], [100 + 18 * 25, 100],
                                 [100 + 18 * 25, 100 + 18 * 15]],
                            measure={"type": "length", "value": 40,
                                     "unit": "ft", "group": WALL}))
    side = 18 * 1000 ** 0.5
    annotate.apply_op(d, op("add_polygon", 0,
                            pts=[[800, 200], [800 + side, 200],
                                 [800 + side, 200 + side], [800, 200 + side]],
                            measure={"type": "area", "value": 1000,
                                     "unit": "sq ft", "group": SLAB}))
    for x in (1500, 1600):
        annotate.apply_op(d, op("add_count", 0, pt=[x, 900], n=1,
                                measure={"type": "count", "value": 1,
                                         "unit": "ea", "group": DOOR}))
    return d


def test_formulas_are_safe_and_useful():
    ev = assemblies.evaluate
    assert ev("ceil(Length*12/Spacing)+1", {"length": 40, "spacing": 16}) == 31
    assert ev("=roundup(7.2, 0.5)", {}) == 7.5
    assert ev("2 if Height > 10 else 1", {"height": 12}) == 2
    for bad in ("__import__('os')", "Length.real", "open('x')", "Length*",
                "nope + 1"):
        with pytest.raises(assemblies.FormulaError):
            ev(bad, {"length": 1})


def test_library_assemblies_all_compute():
    for a in assemblies.library().values():
        meas = {"length": 40, "area": 1000, "perimeter": 130, "count": 2,
                "segments": 1}
        parts = assemblies.compute(a, meas)
        assert parts and all(p["qty"] >= 0 for p in parts), a["name"]


def test_rollup_from_real_measurements(tmp_path):
    d = _job()
    rows, totals, errors = assemblies.rollup(d)
    assert not errors
    by = {r["name"]: {p["name"]: p for p in r["parts"]} for r in rows}
    wall = by[WALL]
    assert wall["Studs"]["qty"] == 32               # 30 + end + corner
    assert wall["Drywall Sheets"]["qty"] == 25
    slab = by[SLAB]
    assert slab["Concrete"]["qty"] == 13.0
    assert slab["Edge Form"]["qty"] == pytest.approx(126.5, abs=0.2)
    assert by[DOOR]["Hinges"]["qty"] == 6
    assert totals["material"] > 0 and totals["labor_hours"] > 0
    assert totals["total"] == pytest.approx(
        totals["material"] + totals["labor_hours"] * totals["labor_rate"])
    out = assemblies.export_xlsx(d, str(tmp_path / "est.xlsx"))
    with zipfile.ZipFile(out) as z:
        assert "xl/worksheets/sheet2.xml" in z.namelist()
        assert b"Drywall Sheets" in z.read("xl/worksheets/sheet2.xml")


def test_job_copy_prices_and_rate_live_in_the_pdf(tmp_path):
    d = _job()
    a = assemblies.find(d, DOOR)
    a["parts"][1]["cost"] = 1000.0                   # Wood Door
    assemblies.set_job_assembly(d, a)
    assemblies.set_labor_rate(d, 80)
    path = str(tmp_path / "job.pdf")
    d.save(path)
    d2 = fitz.open(path)
    rows, totals, _ = assemblies.rollup(d2)
    door = {p["name"]: p for p in
            next(r for r in rows if r["name"] == DOOR)["parts"]}
    assert door["Wood Door"]["material"] == 2000.0
    assert totals["labor_rate"] == 80


def test_bad_formula_is_reported_not_crashing():
    d = _job()
    a = assemblies.find(d, DOOR)
    a["parts"][0]["qty"] = "Count * Nope"
    assemblies.set_job_assembly(d, a)
    rows, _, errors = assemblies.rollup(d)
    assert errors and "Nope" in errors[0]
    assert DOOR not in [r["name"] for r in rows]


def test_user_library(tmp_path):
    a = {"name": "Base Cabinets", "measure": "length", "trade": "Casework",
         "props": {}, "parts": [{"name": "Cabinet", "unit": "lf",
                                 "qty": "Length", "cost": 250, "labor": 0.5}]}
    assemblies.save_to_library(a)
    assert "Base Cabinets" in assemblies.library()


@pytest.mark.parametrize("text, want", [
    ('SCALE: 1/4" = 1\'-0"', 18.0), ('1 1/2" = 1\'-0"', 108.0),
    ('3/32"=1\'-0"', 6.75), ('SCALE: 1"=30\'-0"', 2.4),
    ('SCALE: 1" = 20\'', 3.6), ("SCALE 1:100", 1000 / 100 / 25.4 * 72),
])
def test_find_scales(text, want):
    assert takeoff.find_scales(text)[0][1] == pytest.approx(want)


def test_main_scale_prefers_the_plan_over_details():
    t = ('DIMENSION PLAN SCALE: 1/4" = 1\'-0"  BRICK EXPANSION JOINT '
         'SCALE: 1 1/2" = 1\'-0"')
    assert takeoff.main_scale(t)[1] == 18.0
    assert takeoff.main_scale("SCALE: NO SCALE") is None


def _title_block_words():
    """Words like A-102's title block, with a vertical plot stamp."""
    return [
        (2356, 1474, 2388, 1487, "SHEET"), (2391, 1474, 2419, 1487, "TITLE:"),
        (2360, 1489, 2468, 1516, "DIMENSION"), (2473, 1489, 2540, 1516,
                                               "FLOOR"),
        (2424, 1511, 2476, 1538, "PLAN"),
        (2550, 1521, 2561, 1540, "Local"),             # vertical stamp
        (2550, 1547, 2561, 1581, "C:\\REVIT"),
        (2444, 1607, 2461, 1624, "AS"), (2465, 1607, 2509, 1624, "NOTED"),
        (2356, 1609, 2387, 1622, "SCALE"),
        (2356, 1626, 2402, 1639, "DRAWING"), (2405, 1626, 2422, 1639, "NO."),
        (2380, 1633, 2482, 1687, "A-102"),
        (2085, 259, 2112, 272, "A-102"), (2277, 714, 2300, 727, "A-401"),
    ]


def test_sheet_info_reads_number_and_title():
    n, t = sheets.sheet_info(_title_block_words(), 2592, 1728)
    assert (n, t) == ("A-102", "DIMENSION FLOOR PLAN")


def test_sheet_bookmarks_keep_others_and_rerun_cleanly():
    d = fitz.open()
    for _ in range(3):
        d.new_page()
    d.set_toc([[1, "Specs", 3]])
    labels = {0: "A-101 - FLOOR PLAN", 1: "A-102 - DIMENSION FLOOR PLAN"}
    assert sheets.apply_bookmarks(d, labels) == 2
    assert sheets.apply_bookmarks(d, labels) == 2       # again: no dupes
    toc = d.get_toc()
    assert toc == [[1, "Sheets", 1], [2, "A-101 - FLOOR PLAN", 1],
                   [2, "A-102 - DIMENSION FLOOR PLAN", 2], [1, "Specs", 3]]


def _sheet_pdf(path):
    d = fitz.open()
    p = d.new_page(width=2592, height=1728)
    p.insert_text((2356, 1484), "SHEET TITLE:", fontsize=10)
    p.insert_text((2360, 1512), "FLOOR PLAN", fontsize=22)
    p.insert_text((2356, 1619), "SCALE", fontsize=10)
    p.insert_text((2380, 1680), "A-101", fontsize=44)
    p.insert_text((300, 1600), 'FLOOR PLAN   SCALE: 1/4" = 1\'-0"', fontsize=12)
    p.draw_line((100, 100), (100 + 18 * 40, 100))      # a 40' wall
    d.save(path)


def test_sheet_setup_and_assembly_takeoff_in_the_app(win, tmp_path,
                                                     monkeypatch):
    from PySide6.QtWidgets import QDialog
    from app import sheets_dialog
    path = str(tmp_path / "a101.pdf")
    _sheet_pdf(path)
    assert win.open_path(path)
    monkeypatch.setattr(sheets_dialog.SheetSetupDialog, "exec",
                        lambda self: QDialog.Accepted)
    done = win.sheet_setup(scales=True, bookmarks=True)
    assert done and any("scale" in x for x in done)
    v = win._view
    assert v.scale()["ppu"] == 18.0
    assert ["Sheets", "A-101 - FLOOR PLAN"] == [e[1] for e in
                                                v.doc.get_toc()][:2]
    # take off a wall with an assembly
    a = assemblies.library()[WALL]
    win.assemblies.use(a)
    assert v.tool == "measure_polylength"
    v.set_zoom(1.0)
    assert v.commit_points("measure_polylength",
                           [fitz.Point(100, 100), fitz.Point(820, 100)])
    win.assemblies.refresh()
    rows = win.assemblies.rows
    assert rows and rows[0]["name"] == WALL
    studs = {p["name"]: p for p in rows[0]["parts"]}["Studs"]["qty"]
    assert studs == 31                                # 30 + end stud
    assert WALL in assemblies.read_job(v.doc)["assemblies"]
    assert "Total" in win.assemblies.total.text()
