"""The assembly catalog (CSV) loaded into the library and priced."""
import os

import fitz
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import (annotate, assemblies, assembly_csv, costbook,  # noqa: E402
                 settings)
from test_gui import ANSWERS, win, qapp                    # noqa: E402,F401

FOOT = "Continuous strip footing, 24 in x 12 in"
SOG = "Slab on grade, 4 in, 6x6-W1.4 mesh"
BEAM = "Structural steel beam, W-shape"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(assemblies, "LIBRARY_PATH",
                        str(tmp_path / "assemblies.json"))
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", None)


def test_catalog_parses_cleanly():
    items, problems = assembly_csv.parse(assembly_csv.CATALOG)
    assert len(items) == 422 and not problems
    assert sum(len(a["parts"]) for a in items) == 1145
    assert len({a["name"] for a in items}) == 422
    by = {a["name"]: a for a in items}
    f = by[FOOT]
    assert f["measure"] == "length" and f["props"] == {"W": 24, "D": 12}
    assert f["csi"] == "03 00 00" and f["trade"] == "Concrete"
    parts = {p["name"]: p for p in assemblies.compute(
        f, {"length": 100, "area": 0, "count": 0, "perimeter": 0,
            "segments": 0, "volume": 0})}
    assert parts["Excavate trench"]["qty"] == pytest.approx(12.963, abs=1e-3)
    assert parts["Concrete, 3000 psi"]["qty"] == pytest.approx(
        100 * 2 * 1 / 27 * 1.05)                      # 5% waste
    assert parts["Place, vibrate & finish"]["labor_hours"] == pytest.approx(
        100 * 2 / 27 * 4.5)
    assert parts["Rebar #4 @ 12 in o.c."]["code"] == "A-03-STRIPFOOT.4"
    assert by[BEAM]["inputs"] == {"W": "weight (lb/LF)"}
    sy = next(a for a in items if a["unit"] == "SY")
    assert "(Area/9)" in sy["parts"][0]["qty"]
    gal = next(a for a in items if a["unit"] == "GAL")
    assert gal["measure"] == "volume"


def _job(sf=1000.0, beam_ft=None):
    d = fitz.open()
    d.new_page(width=2592, height=1728)
    annotate.apply_op(d, annotate.new_op("set_scale", 0, ppu=18, unit="ft"))
    side = 18 * sf ** 0.5
    annotate.apply_op(d, annotate.new_op(
        "add_polygon", 0, pts=[[100, 100], [100 + side, 100],
                               [100 + side, 100 + side], [100, 100 + side]],
        measure={"type": "area", "value": sf, "unit": "sq ft",
                 "group": SOG}))
    if beam_ft:
        annotate.apply_op(d, annotate.new_op(
            "add_polyline", 0, pts=[[100, 1500], [100 + 18 * beam_ft, 1500]],
            measure={"type": "length", "value": beam_ft, "unit": "ft",
                     "group": BEAM}))
    return d


def test_catalog_in_library_takeoff_inputs_and_cost_book(tmp_path):
    lib = assemblies.library()
    assert FOOT in lib and SOG in lib
    assert 'Interior Wall - 2x4 @ 16" O.C.' in lib       # built-ins kept
    d = _job(beam_ft=40)
    rows, totals, errors = assemblies.rollup(d)
    by = {r["name"]: r for r in rows}
    sog = {p["name"]: p for p in by[SOG]["parts"]}
    assert sog["Concrete, 3500 psi"]["qty"] == pytest.approx(
        1000 * 4 / 12 / 27 * 1.05)
    # the beam can't be priced until its weight is entered
    assert BEAM not in by and any("enter W (weight (lb/LF))" in e
                                  for e in errors)
    a = assemblies.find(d, BEAM)
    a["props"]["W"] = 22
    assemblies.set_job_assembly(d, a)
    rows, totals, errors = assemblies.rollup(d)
    beam = {p["name"]: p for p in
            {r["name"]: r for r in rows}[BEAM]["parts"]}
    assert beam["Structural steel"]["qty"] == pytest.approx(40 * 22 * 1.03)
    assert not errors
    # a cost book from the template prices the catalog parts by code
    tpl = assembly_csv.cost_book_template([assemblies.find(d, SOG)],
                                          str(tmp_path / "tpl.csv"))
    text = open(tpl, encoding="utf-8-sig").read().replace(
        "A-03-SOG-4.4,\"Concrete, 3500 psi\",cy,,",
        "A-03-SOG-4.4,\"Concrete, 3500 psi\",cy,150,")
    open(tpl, "w", encoding="utf-8-sig").write(text)
    book = costbook.from_csv(tpl, name="Prices")
    assert book.get("A-03-SOG-4.4")["material"] == 150
    assemblies.set_costbook(d, book)
    rows, totals, _ = assemblies.rollup(d)
    sog = {p["name"]: p for p in
           {r["name"]: r for r in rows}[SOG]["parts"]}
    assert sog["Concrete, 3500 psi"]["cost"] == pytest.approx(150)
    # material is to the cent per part (Chief's re-test, Nov 7)
    assert sog["Concrete, 3500 psi"]["material"] == pytest.approx(
        150 * 1000 * 4 / 12 / 27 * 1.05, abs=0.005)


def test_import_export_round_trip(tmp_path):
    items, _ = assembly_csv.parse(assembly_csv.CATALOG)
    some = items[:25]
    out = assembly_csv.write(some, str(tmp_path / "out.csv"))
    back, problems = assembly_csv.parse(out)
    assert not problems and len(back) == 25
    meas = {"length": 37, "area": 420, "count": 3, "volume": 270,
            "perimeter": 0, "segments": 0}
    for a, b in zip(some, back):
        for k in (a.get("inputs") or {}):
            a["props"][k] = b["props"][k] = 5
        qa = [round(p["qty"], 6) for p in assemblies.compute(a, meas)]
        qb = [round(p["qty"], 6) for p in assemblies.compute(b, meas)]
        assert qa == qb, a["name"]
    n, problems = assembly_csv.import_to_library(out)
    assert n == 25 and os.path.exists(assemblies.LIBRARY_PATH)


def test_library_window_search_and_csv(qapp, win, tmp_path):
    from app.assembly_ui import LibraryDialog
    dlg = LibraryDialog(win._view.doc, win)
    total = len(dlg.items)
    assert total >= 415
    dlg.search.setText("strip footing")
    names = [dlg.list.item(i).data(0x0100) for i in range(dlg.list.count())]
    assert FOOT in names and len([n for n in names if n]) < 10
    assert "of" in dlg.count.text()
    tpl = dlg._template(str(tmp_path / "t.csv"))
    assert "A-03-STRIPFOOT.1" in open(tpl, encoding="utf-8-sig").read()
    out = dlg._export_csv(str(tmp_path / "e.csv"))
    assert os.path.getsize(out) > 0
    dlg.search.setText("")
    row = next(i for i in range(dlg.list.count())
               if dlg.list.item(i).data(0x0100) == BEAM)
    dlg.list.setCurrentRow(row)
    assert "Enter before use" in dlg.info.text()
