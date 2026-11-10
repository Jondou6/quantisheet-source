"""Step 1 of the Venice modules: units, labor/crews, cost books, CSI."""
import os

import fitz
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import (annotate, assemblies, costbook, csi, labor,   # noqa: E402
                 settings, units)
from test_gui import ANSWERS, win, qapp                    # noqa: E402,F401

WALL = 'Interior Wall - 2x4 @ 16" O.C.'
SLAB = 'Slab on Grade - 4"'
DOOR = "Door - Hollow Metal Frame & Wood Door"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(assemblies, "LIBRARY_PATH",
                        str(tmp_path / "assemblies.json"))
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", None)


def _job(unit="ft", ppu=18.0, wall=40.0, slab=1000.0):
    d = fitz.open()
    d.new_page(width=2592, height=1728)
    op = annotate.new_op
    annotate.apply_op(d, op("set_scale", 0, ppu=ppu, unit=unit))
    run = wall * ppu
    annotate.apply_op(d, op("add_polyline", 0,
                            pts=[[100, 100], [100 + run, 100]],
                            measure={"type": "length", "value": wall,
                                     "unit": unit, "group": WALL}))
    side = ppu * slab ** 0.5
    annotate.apply_op(d, op("add_polygon", 0,
                            pts=[[800, 200], [800 + side, 200],
                                 [800 + side, 200 + side], [800, 200 + side]],
                            measure={"type": "area", "value": slab,
                                     "unit": f"sq {unit}", "group": SLAB}))
    annotate.apply_op(d, op("add_count", 0, pt=[1500, 900], n=1,
                            measure={"type": "count", "value": 1,
                                     "unit": "ea", "group": DOOR}))
    return d


def _by(rows):
    return {r["name"]: r for r in rows}


# ---- units -----------------------------------------------------------------

def test_units_convert_and_refuse_unlike_things():
    q = units.q
    assert q(12, "in").to("ft").value == pytest.approx(1)
    assert (q(100, "sf") * q(0.5, "hr/sf")).to("hr").value == 50
    assert q(10, "sq m").to("sf").value == pytest.approx(107.639, abs=1e-3)
    assert q(1, "sq cm").to("si").value == pytest.approx(0.155, abs=1e-3)
    assert q(1, "cu yd").to("cf").value == pytest.approx(27)
    assert q(2, "cu m").to("cy").value == pytest.approx(2.6159, abs=1e-3)
    with pytest.raises(units.UnitError):
        q(3, "ft") + q(2, "sf")
    with pytest.raises(units.UnitError):
        units.measure_to_base(3, "ft", "area")
    assert units.measure_to_base(10, "sq m", "area") == pytest.approx(107.64,
                                                                     abs=.01)
    assert units.compatible("msf", "sq ft")
    assert not units.compatible("lf", "sf")


def test_metric_drawing_feeds_formulas_in_feet():
    d = _job(unit="m", ppu=60.0, wall=12.192, slab=92.903)  # 40 ft, 1000 sf
    rows, _, errors = assemblies.rollup(d)
    assert not errors
    by = {r["name"]: {p["name"]: p for p in r["parts"]} for r in _by(rows)
          .values()}
    assert by[WALL]["Studs"]["qty"] == 31           # same as a 40' wall
    assert by[SLAB]["Concrete"]["qty"] == 13.0      # same as 1000 sf
    assert by[SLAB]["Edge Form"]["qty"] == pytest.approx(126.5, abs=0.3)
    assert _by(rows)[SLAB]["unit"] == "sq m"        # shown as drawn


def test_wrong_measurement_type_is_an_error_not_a_bid():
    d = _job()
    # an area measured with a length assembly
    annotate.apply_op(d, annotate.new_op(
        "add_polygon", 0, pts=[[100, 600], [300, 600], [300, 800]],
        measure={"type": "area", "value": 50, "unit": "sq ft",
                 "group": WALL}))
    rows, _, errors = assemblies.rollup(d)
    assert any("measured by length" in e for e in errors)
    assert _by(rows)[WALL]["items"] == 1


# ---- CSI ---------------------------------------------------------------------

def test_csi_codes():
    for t in ("092116", "09 21 16", "9.21.16", "09-21-16"):
        assert csi.parse_code(t) == "09 21 16"
    assert csi.parse_code("09 21 16.13") == "09 21 16.13"
    assert csi.parse_code("drywall") == ""
    assert csi.division_title("09 21 16") == "Finishes"
    assert csi.classify("gypsum board partition").startswith("09")
    rows, _, _ = assemblies.rollup(_job())
    assert _by(rows)[WALL]["csi"] == "09 21 16"
    assert _by(rows)[SLAB]["csi"] == "03 30 00"


# ---- labor -------------------------------------------------------------------

def test_crews_rates_and_adjustments():
    assert labor.crew_rate("D-2") == pytest.approx((46 + 47) / 2)
    assert labor.crew_rate("D-2", {"Taper": 53}) == pytest.approx(49.5)
    assert labor.crew_rate("nope") is None
    assert labor.crew_days(16, "D-2") == 1.0
    assert labor.factor({"height": "Over 20 ft", "shift": "Overtime"}) == \
        pytest.approx(1.18 * 1.5)
    labor.save_crew("C-3", "Framing crew", [["Carpenter", 2],
                                            ["Laborer", 1]])
    assert labor.crew_rate("C-3") == pytest.approx((48 * 2 + 34) / 3)


def test_rollup_uses_crew_rates_and_adjustment_factors():
    d = _job()
    base, bt, _ = assemblies.rollup(d)
    door_hrs = _by(base)[DOOR]["labor_hours"]
    a = assemblies.find(d, DOOR)
    for p in a["parts"]:
        p["crew"] = "C-2"
    a["adjust"] = {"conditions": "Occupied"}
    assemblies.set_job_assembly(d, a)
    assemblies.set_job_settings(d, adjust={"height": "Up to 20 ft"},
                                rates={"Carpenter": 60})
    rows, totals, errors = assemblies.rollup(d)
    assert not errors
    door = _by(rows)[DOOR]
    assert door["labor_hours"] == pytest.approx(door_hrs * 1.12 * 1.05)
    # labor cost is each part's hours x rate to the cent (Nov 7)
    assert door["labor_cost"] == pytest.approx(door["labor_hours"] * 46,
                                               abs=0.01)
    assert door["crew_days"] == pytest.approx(door["labor_hours"] / 16)
    # the wall only gets the job-wide factor, at the job labor rate
    wall = _by(rows)[WALL]
    assert wall["labor_hours"] == pytest.approx(
        _by(base)[WALL]["labor_hours"] * 1.05)
    assert wall["labor_cost"] == pytest.approx(wall["labor_hours"] *
                                               totals["labor_rate"], abs=0.01)


# ---- cost books -----------------------------------------------------------------

def _book():
    b = costbook.Book({"name": "House 2026", "effective": "2026-01-01",
                       "escalation": 0.04,
                       "index": {"national": 1.0, "Boston": 1.2}})
    b.set("08 14 16", "ea", material=500, labor=2.0, crew="C-2",
          desc="Wood door")
    b.set("09 29 00", "msf", material=600, labor=10, desc="Gyp board")
    return b


def test_cost_book_factor_csv_and_save(tmp_path):
    b = _book()
    assert b.factor("Boston", "2026-01-01") == pytest.approx(1.2)
    assert b.factor("national", "2027-01-01") == pytest.approx(1.04, abs=1e-3)
    path = costbook.save(b)
    assert costbook.list_books() == {"House 2026": path}
    assert costbook.find("House 2026").get("081416")["material"] == 500
    csvp = tmp_path / "prices.csv"
    csvp.write_text("Code,Description,Unit,Material,Labor,Crew\n"
                    "092116,Gyp board,sf,\"$1,000.50\",0.02,D-2\n"
                    ",blank row,,,,\n", encoding="utf-8")
    c = costbook.from_csv(str(csvp))
    assert list(c.items) == ["09 21 16"]
    assert c.get("09 21 16")["material"] == 1000.5


def test_job_priced_from_cost_book_with_units_and_reprice_preview(tmp_path):
    d = _job()
    a = assemblies.find(d, DOOR)
    a["parts"][1]["code"] = "08 14 16"           # Wood Door, ea
    assemblies.set_job_assembly(d, a)
    w = assemblies.find(d, WALL)
    w["parts"][4]["code"] = "09 29 00"           # Tape & Mud, sf vs msf
    assemblies.set_job_assembly(d, w)
    before, bt, _ = assemblies.rollup(d)
    book = _book()
    diff, old, new, problems = assemblies.reprice(d, book, "Boston",
                                                  "2026-01-01")
    assert not problems
    assert old == pytest.approx(bt["total"])
    # nothing changed yet
    assert assemblies.rollup(d)[1]["total"] == pytest.approx(bt["total"])
    assemblies.set_costbook(d, book, "Boston", "2026-01-01")
    path = str(tmp_path / "job.pdf")
    d.save(path)
    d2 = fitz.open(path)                          # book travels in the PDF
    rows, totals, errors = assemblies.rollup(d2)
    assert not errors and totals["costbook"] == "House 2026"
    door = {p["name"]: p for p in _by(rows)[DOOR]["parts"]}["Wood Door"]
    assert door["cost"] == pytest.approx(600)     # 500 x Boston 1.2
    assert door["crew"] == "C-2"
    assert door["labor_cost"] == pytest.approx(2 * 1.0 * 40)   # C-2 $40/hr
    tape = {p["name"]: p for p in _by(rows)[WALL]["parts"]}["Tape & Mud"]
    assert tape["cost"] == pytest.approx(0.72)    # $600/msf x 1.2 per sf
    assert totals["total"] == pytest.approx(new)
    by = {x["name"]: x for x in diff}
    assert by[DOOR]["change"] == pytest.approx(
        _by(rows)[DOOR]["total"] - _by(before)[DOOR]["total"])
    # back to the assemblies' own prices
    assemblies.set_costbook(d2, None)
    assert assemblies.rollup(d2)[1]["total"] == pytest.approx(bt["total"])


def test_cost_book_unit_mismatch_and_missing_code_are_reported():
    d = _job()
    a = assemblies.find(d, DOOR)
    a["parts"][0]["code"] = "09 29 00"            # HM Frame (ea) vs msf
    a["parts"][2]["code"] = "99 99 99"            # not in the book
    assemblies.set_job_assembly(d, a)
    assemblies.set_costbook(d, _book())
    _, _, errors = assemblies.rollup(d)
    assert any("prices per 'msf'" in e for e in errors)
    assert any("99 99 99 is not in House 2026" in e for e in errors)


def test_from_job_builds_a_starting_book():
    d = _job()
    a = assemblies.find(d, DOOR)
    a["parts"][1]["code"] = "081416"
    assemblies.set_job_assembly(d, a)
    b = costbook.from_job(d, "Mine")
    assert b.get("08 14 16")["material"] == 410.0


# ---- UI ------------------------------------------------------------------------

def test_editor_and_dialogs(qapp, win, tmp_path):
    from app.assembly_ui import AssemblyEditor
    from app.estimating_ui import CostBookDialog, LaborDialog
    d = _job()
    path = str(tmp_path / "j.pdf")
    d.save(path)
    win.open_path(path)
    v = win._view
    ed = AssemblyEditor(assemblies.find(v.doc, DOOR))
    assert ed.parts.columnCount() == 7
    ed.csi.setText("081416")
    ed.parts.item(1, 5).setText("08 14 16")
    ed.parts.item(1, 6).setText("c-2")
    ed.adjust["shift"].setCurrentIndex(ed.adjust["shift"].findData(
        "Overtime"))
    a = ed.assembly()
    assert a["csi"] == "08 14 16" and a["adjust"] == {"shift": "Overtime"}
    assert a["parts"][1]["code"] == "08 14 16" and \
        a["parts"][1]["crew"] == "C-2"
    ed.csi.setText("drywall")
    assert "not a" in ed.csi_title.text()

    dlg = LaborDialog(v.doc, win)
    dlg.rate.setValue(70)
    dlg.adjust["height"].setCurrentIndex(
        dlg.adjust["height"].findData("Over 20 ft"))
    dlg.apply()
    job = assemblies.read_job(v.doc)
    assert job["labor_rate"] == 70 and job["adjust"] == {"height":
                                                         "Over 20 ft"}

    costbook.save(_book())
    cb = CostBookDialog(v.doc, win)
    assert cb.books.count() == 1
    assert cb.preview() is not None and cb.diff.rowCount() >= 3
    cb._use()
    assert assemblies.read_job(v.doc)["costbook"]["name"] == "House 2026"
    win.assemblies.set_doc(v.doc)
    assert win.assemblies.tree.columnCount() == 11
    assert "House 2026" in win.assemblies.total.text()
