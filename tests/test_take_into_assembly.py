"""Takeoff > Take Off Into Assembly (app/take_into_assembly.py): pick a CSI
division, then an assembly; the tool for its unit starts on a group bound
to the assembly (the group is named after it and the assembly is copied
into the job), so what is traced is priced in the Assemblies panel and the
proposal at once. Made-up data only."""
import os

import fitz
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import assemblies, take_into_assembly as TA             # noqa: E402
from test_gui import ANSWERS, win, qapp                          # noqa: E402,F401

SLAB = 'Slab on Grade - 4"'
WALL = 'Interior Wall - 2x4 @ 16" O.C.'
DOOR = "Door - Hollow Metal Frame & Wood Door"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(assemblies, "LIBRARY_PATH",
                        str(tmp_path / "assemblies.json"))


def _lib():
    return {a["name"]: a for a in assemblies.BUILT_IN}


# ---- pure ------------------------------------------------------------------

def test_tool_follows_the_assembly_unit():
    lib = _lib()
    assert TA.tool_for(lib[SLAB]) == "measure_area"
    assert TA.tool_for(lib[WALL]) == "measure_polylength"
    assert TA.tool_for(lib[DOOR]) == "count"
    assert TA.tool_for({"name": "No unit", "measure": ""}) == ""
    assert TA.UNIT[TA.measure_of(lib[SLAB])] == "SF"


def test_grouped_by_csi_division_job_copy_wins():
    lib = _lib()
    mine = dict(lib[SLAB], props={"Depth": 6, "Waste": 5})
    odd = {"name": "Test Thing Without Code", "measure": "count",
           "trade": "", "parts": []}
    unmeasured = {"name": "Test Lump", "measure": "", "parts": []}
    items = TA.catalog({"assemblies": {SLAB: mine, odd["name"]: odd,
                                       "Test Lump": unmeasured}}, lib)
    assert "Test Lump" not in items                 # nothing to measure
    assert items[SLAB]["props"]["Depth"] == 6       # the job's own copy
    groups = dict(TA.by_division(items))
    assert [a["name"] for a in groups["03"]] == [SLAB]
    assert WALL in [a["name"] for a in groups["09"]]
    assert [d for d, _ in TA.by_division(items)][-1] == TA.OTHER
    assert TA.division_label("09") == "09 Finishes"
    assert "Area (SF)" in TA.describe(items[SLAB])


def test_division_from_trade_when_uncoded():
    a = {"name": "Test Concrete Pad", "trade": "Concrete", "measure": "area"}
    assert TA.division_of(a) == "03"


def test_no_drawing_no_dialog():
    said = []

    class NoDoc:
        _view = None

        def _flash(self, text):
            said.append(text)
    assert TA.run(NoDoc()) is None
    assert said and "Open a drawing" in said[0]


# ---- in the app -------------------------------------------------------------

def test_command_on_takeoff_menu(win):
    assert win.command("Take Off Into Assembly") is not None


def test_take_off_into_slab_prices_as_traced(win):
    v = win._view
    assert v.calibrate(100.0, real=10, unit="ft", all_pages=True)
    dlg = win.take_into_assembly(show=False)
    assert dlg is not None
    assert dlg.select_division("03")
    assert dlg.select_assembly(SLAB)
    dlg.accept()
    assert dlg.chosen["name"] == SLAB
    assert TA.start(win, dlg.chosen)
    assert v.tool == "measure_area"
    assert SLAB in assemblies.read_job(v.doc)["assemblies"]      # bound
    pts = [fitz.Point(40, 40), fitz.Point(540, 40), fitz.Point(540, 240),
           fitz.Point(40, 240)]                                  # 50 x 20 ft
    assert v.commit_points("measure_area", pts)
    win.assemblies.refresh()
    row = [r for r in win.assemblies.rows if r["name"] == SLAB]
    assert row, [r["name"] for r in win.assemblies.rows]
    assert row[0]["quantity"] == pytest.approx(1000, abs=1)
    assert row[0]["total"] > 0
    # the proposal reads the same rollup
    rows, totals, _e = assemblies.rollup(v.doc)
    assert any(r["name"] == SLAB and r["total"] > 0 for r in rows)


def test_count_assembly_starts_count_on_its_group(win):
    v = win._view
    a = _lib()[DOOR]
    assert TA.start(win, a)
    assert v.tool == "count"
    assert v.count_group == DOOR
    assert DOOR in assemblies.read_job(v.doc)["assemblies"]


def test_cancel_changes_nothing(win, monkeypatch):
    from PySide6.QtWidgets import QDialog
    v = win._view
    before = dict(assemblies.read_job(v.doc)["assemblies"])
    cls = type(TA.TakeIntoAssemblyDialog(v.doc, win))
    monkeypatch.setattr(cls, "exec", lambda self: QDialog.Rejected)
    win.take_into_assembly()
    assert assemblies.read_job(v.doc)["assemblies"] == before
