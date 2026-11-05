"""r36 v2 step 7 (G1.2): an assembly for each wall type in the drawing
set's wall-type legend - studs, track, board, sealant, screws, tape and
compound (and batt, furring, rigid, sheathing, vapor barrier, CMU,
siding when the legend names them), worked out with 0.13.9's own
wall_assembly factors as formulas over Length and Height, every part at
$0 with its own Waste % (0 until you set it) and a cost code so YOUR
cost book can price it. Made-up legends only."""
import math
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import assemblies, settings, wall_assembly                 # noqa: E402
from app.estimating import checks, wall_legends as WL                # noqa: E402
from estimate_helpers import blank_doc                              # noqa: E402

DESCS = [
    '3-5/8" MTL. STUDS @ 16" O.C. W/ 5/8" TYPE X GYPSUM BOARD EACH SIDE',
    '6" METAL STUDS @ 24" O.C. W/ 5/8" TYPE X GYP. BD. ONE SIDE, BATT '
    'INSULATION, 7/8" MTL FURRING',
    '8" CMU W/ 2" RIGID INSULATION, GLASS MAT GYPSUM SHEATHING, VAPOR '
    'BARRIER, CEMENT BOARD SIDING',
]


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(assemblies, "LIBRARY_PATH",
                        str(tmp_path / "assemblies.json"))
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", None)


def _short(name):
    return name.split(" - ", 1)[1]


@pytest.mark.parametrize("desc", DESCS)
@pytest.mark.parametrize("lf,h", [(100, 10), (37.5, 9.33), (8, 12)])
def test_parity_with_0139_wall_lines_at_zero_waste(desc, lf, h):
    comps = wall_assembly.components(desc)
    a = WL.assembly_for("1A", desc, h)
    parts = assemblies.compute(a, {"length": lf, "segments": 1})
    want = {_short(x["name"]): x for x in wall_assembly.lines("1A", lf, h,
                                                              comps)}
    got = {p["name"]: p for p in parts}
    assert sorted(got) == sorted(want)
    for k, w in want.items():
        assert round(got[k]["qty"], 1) == w["qty"], k
        assert got[k]["unit"] == w["unit"]


def test_every_money_field_is_zero_and_each_part_has_waste_and_a_code():
    a = WL.assembly_for("1A", DESCS[0], 10)
    assert a["name"] == "Wall Type 1A" and a["measure"] == "length"
    for p in a["parts"]:
        assert p["cost"] == 0 and p["labor"] == 0
        assert p["code"] in ("09 21 16", "04 22 00")
    waste = [k for k in a["props"] if k.startswith("Waste_")]
    assert len(waste) == len(a["parts"])
    assert all(a["props"][k] == 0 for k in waste)


def test_per_part_waste_is_applied():
    a = WL.assembly_for("1A", DESCS[0], 10)
    key = next(k for k in a["props"] if k.startswith("Waste_") and
               "board" in k.lower())
    a["props"][key] = 10
    parts = {p["name"]: p for p in assemblies.compute(
        a, {"length": 100, "segments": 1})}
    board = next(v for k, v in parts.items() if "type X gypsum board" in k)
    assert board["qty"] == pytest.approx(2000 * 1.1)
    studs = next(v for k, v in parts.items() if "metal studs" in k)
    assert studs["qty"] == pytest.approx((math.ceil(100 / (16 / 12)) + 1)
                                         * 10)


def test_status_verified_inferred_and_no_height():
    legend = {"1A": DESCS[0] + ' H= 10\'-0"', "2B": DESCS[1],
              "3C": "8\" HORIZONTAL JOINT REINFORCEMENT", "9Z": "SEE SPEC"}
    out = WL.build(legend, heights={"1A": 10.0}, general_height=9.0)
    by = {b["code"]: b for b in out["types"]}
    assert by["1A"]["status"] == "VERIFIED"
    assert by["2B"]["status"] == "INFERRED"                # general note
    assert "general" in by["2B"]["why"]
    assert by["3C"]["status"] == "INFERRED"                # CMU inferred
    assert out["unreadable"] == ["9Z"]
    out = WL.build({"2B": DESCS[1]}, heights={}, general_height=9.0,
                   plate=11.5)                     # elevations first (AI)
    assert out["types"][0]["status"] == "INFERRED"
    assert "elevations" in out["types"][0]["why"]
    assert out["types"][0]["assembly"]["props"]["Height"] == 11.5
    out = WL.build({"2B": DESCS[1]}, heights={}, general_height=None)
    b = out["types"][0]
    assert b["status"] == "NEEDS HEIGHT" and b["assembly"]["props"][
        "Height"] == 0


def test_apply_binds_unpriced_wall_groups_in_one_write(monkeypatch):
    from app import annotate, embfiles, estimate
    d = blank_doc()
    for i, g in enumerate(("Wall Type 1A", "Wall Type 2B", "Wall Type 4D")):
        annotate.apply_op(d, annotate.new_op(
            "add_line", 0, pts=[[100, 100 + 50 * i], [300, 100 + 50 * i]],
            measure={"type": "length", "value": 20, "unit": "ft",
                     "group": g}))
    estimate.set_price(d, "Wall Type 4D", "length", "ft", unit_cost=9,
                       cost_type="Material")
    out = WL.build({"1A": DESCS[0], "2B": DESCS[1], "4D": DESCS[0],
                    "7X": DESCS[0]}, heights={"1A": 10, "2B": 12, "4D": 10,
                                               "7X": 10})
    puts = []
    real = embfiles.put
    monkeypatch.setattr(embfiles, "put", lambda *a, **k: (puts.append(a[1]),
                                                          real(*a, **k)))
    res = WL.apply(d, out)
    assert puts == [assemblies.JOB_FILE]                   # one write
    assert res["bound"] == ["Wall Type 1A", "Wall Type 2B"]
    assert res["priced_already"] == ["Wall Type 4D"]
    assert res["no_group"] == ["Wall Type 7X"]
    rows, _t, _e = assemblies.rollup(d, added=False)
    names = {r["name"] for r in rows}
    assert names == {"Wall Type 1A", "Wall Type 2B"}
    assert all(r["material"] == 0 and r["labor_cost"] == 0 for r in rows)
    assert WL.apply(d, out)["bound"] == []                 # idempotent


def test_no_legend_found_says_so(monkeypatch):
    d = blank_doc()
    monkeypatch.setattr(WL, "_read", lambda doc, rows=None: ({}, [], ""))
    out = WL.from_doc(d, rows=[])
    assert out["types"] == [] and "no wall-type legend" in out["message"]
