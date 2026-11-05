"""Review of 0.12.39 (made-up jobs only): a generated commercial set is not
read as a house from its own self-check line, the roof row names the roof,
plumbing by others renames the combined rows, and the brief's drive-thru
side is drawn."""
import re

import pytest

from app.pm import autoschedule as au
from app.pm import productivity as prod
from app.pm import schedule_types as st

from test_productivity import FULL_SET, _genset_job, cfg  # noqa: F401


COMMERCIAL = [{"building_type": "warehouse", "gross_sf": 38000},
              {"building_type": "strip_retail", "gross_sf": 20000},
              {"building_type": "restaurant", "gross_sf": 4500}]


def _truss_rows(sc):
    return [a for a in au.plan(sc) if "truss" in a["name"].lower()]


# ---- #1 the self-check line is not evidence of a house ---------------------
@pytest.mark.parametrize("fields", COMMERCIAL)
@pytest.mark.parametrize("sidecar", [True, False])
def test_generated_commercial_set_is_not_residential(cfg, tmp_path, fields,
                                                     sidecar):
    sc = _genset_job(tmp_path, fields, cover=True, sidecar=sidecar)
    assert not sc["residential"], fields
    assert not st.roof_trusses(sc)
    assert _truss_rows(sc) == []
    assert prod.structure_family(sc) != "wood_framing"
    by = {a["key"]: a for a in au.plan(sc)}
    assert "300 SF/day" not in by["structure"]["basis"], \
        by["structure"]["basis"]
    if sidecar:
        assert sc["genset_type"] == fields["building_type"]


def test_strip_center_structure_is_not_wood_framing(cfg, tmp_path):
    sc = _genset_job(tmp_path, {"building_type": "strip_retail",
                                "gross_sf": 20000})
    by = {a["key"]: a for a in au.plan(sc)}
    # was 66 d (capped at 60) at the wood-framing rate
    assert by["structure"]["duration"] < 30, by["structure"]["basis"]


@pytest.mark.parametrize("sidecar", [True, False])
def test_generated_house_still_gets_trusses(cfg, tmp_path, sidecar):
    sc = _genset_job(tmp_path, {"building_type": "single_family",
                                "gross_sf": 1600}, sidecar=sidecar)
    assert sc["residential"]
    assert st.roof_trusses(sc)
    assert _truss_rows(sc)
    assert prod.structure_family(sc) == "wood_framing"


def test_self_check_words_alone_are_no_house():
    rows = [{"number": "A-101", "title": "FLOOR PLAN"}]
    lines = ["SELF-CHECK: PASS", "PASS",
             "No walking through bedrooms, baths or service rooms",
             "Garage door opens into the house (not a bedroom or bath)"]
    assert not au.scope(rows, area_sf=9000, texts=lines)["residential"]
    assert au.scope(rows, area_sf=1800, texts=lines + [
        "SINGLE-FAMILY RESIDENCE, 3 BEDROOMS"])["residential"]


def test_low_slope_roof_is_joists_even_on_a_residential_set():
    sc = {"residential": True, "area_sf": 4000.0,
          "set_quantities": {"roof_sq": (40.0, "genset: roof area "
                                                "(low-slope)")}}
    assert not st.roof_trusses(sc)
    sc["set_quantities"]["roof_sq"] = (21.0, "genset: roof area (pitched "
                                             "roof, roofing squares)")
    assert st.roof_trusses(sc)


# ---- #3 the roof row's BASIS names the roof --------------------------------
def test_roof_structure_basis_names_the_roof_area(cfg, tmp_path):
    sc = _genset_job(tmp_path, {"building_type": "warehouse",
                                "gross_sf": 38000})
    by = {a["key"]: a for a in au.plan(sc)}
    basis = by["roofstruct"]["basis"]
    assert "slab on grade" not in basis, basis
    assert "genset: roof area" in basis, basis
    roof_sf = sc["set_quantities"]["roof_sq"][0] * 100
    assert basis.startswith(f"{roof_sf:,.0f} SF roof"), basis
    # no set roof: the footprint estimate as before
    by = {a["key"]: a for a in au.plan(au.scope(FULL_SET, area_sf=12000))}
    assert "footprint" in by["roofstruct"]["basis"]


# ---- #4 plumbing not in contract -------------------------------------------
def test_plumbing_not_in_contract_renames_combined_rows():
    sc = au.scope(FULL_SET, area_sf=6000,
                  texts=["ALL PLUMBING IS NOT IN CONTRACT"])
    assert "plumbing" in sc["excluded_trades"]
    names = [a["name"] for a in au.plan(sc)]
    assert not [n for n in names if "plumbing" in n.lower()], names
    assert "Under-slab electrical" in names and "Electrical trim" in names
    # electrical by others too: no combined row is left
    sc = au.scope(FULL_SET, area_sf=6000,
                  texts=["ALL PLUMBING IS NOT IN CONTRACT.",
                         "ELECTRICAL WORK BY OTHERS (N.I.C.)"])
    names = [a["name"] for a in au.plan(sc)]
    assert not [n for n in names if re.search(r"plumbing|electrical",
                                              n, re.I)], names
    # electrical alone, as before
    sc = au.scope(FULL_SET, area_sf=6000,
                  texts=["ELECTRICAL WORK BY OTHERS (N.I.C.)"])
    names = [a["name"] for a in au.plan(sc)]
    assert "Under-slab plumbing" in names and "Plumbing trim" in names


# ---- #5 the brief's drive-thru side ----------------------------------------
@pytest.mark.parametrize("text,side", [
    ("New 3,500 sf restaurant with a drive-thru window on the west side",
     "W"),
    ("3,500 sf restaurant, west-side drive-thru", "W"),
    ("3,500 sf restaurant with a drive-thru on the east side", "E"),
    ("3,500 sf restaurant with a drive-thru", None),
    ("3,500 sf restaurant with a drive-thru, parking on the west", None),
])
def test_brief_reads_the_drive_thru_side(text, side):
    from app.genset import brief
    f = brief.parse(text, use_ai=False)
    assert f["drive_thru"] and f.get("drive_thru_side") == side, text


def test_drive_thru_on_the_west_side_from_the_brief():
    from app.genset import audit, brief, layout, model, views
    f = brief.parse("New 3,500 sf restaurant with a drive-thru window on "
                    "the west side", use_ai=False)
    p = layout.make_plan(f)
    model.validate(p)
    assert p["drive_thru"]["side"] == "W" and not p["drive_thru"]["assumed"]
    win = next(o for o in p["openings"] if o.get("drive_thru"))
    by = {r["id"]: r for r in p["rooms"]}
    assert win["wall"] == "W4" and by[win["room"]]["name"] == "DRIVE-THRU"
    assert by[win["room"]]["rect"][0] < 1.0         # on the west wall
    asm = " ".join(p["restaurant"]["assumed"])
    assert "window on the east" not in asm and "drive-thru lane" in asm
    # the set checks itself clean, the lane on the west
    assert [r for r in audit.audit(p) if r[0] != "PASS"] == []
    lay = views.site_layout(p)
    ln = lay["features"]["lane"]
    assert ln["side"] == "W" and ln["in_lot"] and ln["in_setbacks"]
    assert lay["clashes"] == []
    assert set(layout.reachable(p)) == {r["id"] for r in p["rooms"]}


@pytest.mark.parametrize("sf", (2000, 3500, 8000, 12000))
def test_west_plan_is_the_east_plan_mirrored(sf):
    from app.genset import audit, layout
    e = layout.make_plan({"building_type": "restaurant", "gross_sf": sf,
                          "drive_thru": True})
    w = layout.make_plan({"building_type": "restaurant", "gross_sf": sf,
                          "drive_thru": True, "drive_thru_side": "W"})
    W = e["footprint"]["width"]

    def at(p):
        walls = {x["id"]: x for x in p["walls"]}
        out = {}
        for o in p["openings"]:
            (ax, ay), (bx, by) = walls[o["wall"]]["a"], walls[o["wall"]]["b"]
            t = o["along"] / max(1e-9, ((bx - ax) ** 2 + (by - ay) ** 2)
                                 ** 0.5)
            out[o["id"]] = (ax + (bx - ax) * t, ay + (by - ay) * t)
        return out
    pe, pw = at(e), at(w)
    for k, (x, y) in pe.items():
        assert abs(pw[k][0] - (W - x)) < 1e-6 and \
            abs(pw[k][1] - y) < 1e-6, k
    assert [r for r in audit.audit(w) if r[0] == "FAIL"] == []
    assert e["drive_thru"]["assumed"] and e["drive_thru"]["side"] == "E"


def test_north_side_drive_thru_is_said_not_drawn():
    from app.genset import layout
    p = layout.make_plan({"building_type": "restaurant", "gross_sf": 3500,
                          "drive_thru": True, "drive_thru_side": "N"})
    assert p["drive_thru"]["side"] == "E" and p["drive_thru"]["assumed"]
    assert any("north side" in w for w in p["warnings"])
