"""The G-003 code summary (app/genset/codes.py) uses app/codecheck.py's
tables and nothing else: every number it prints is codecheck's."""
import pytest

from app import codecheck
from app.genset import codes, layout
from app.genset.model import rect_area


def _wh(sf, occ="S-1", **kw):
    return layout.make_plan(dict({"building_type": "warehouse",
                                  "gross_sf": sf, "occupancy": occ}, **kw))


@pytest.mark.parametrize("sf,occ", [(5000, "S-1"), (60000, "S-1"),
                                    (200000, "S-1"), (40000, "F-1")])
def test_occupant_loads_are_codecheck_s(sf, occ):
    p = _wh(sf, occ)
    rows = codes.occupant_load(p)
    by = {r["id"]: r for r in p["rooms"]}
    assert len(rows) == len(p["rooms"])
    for r in rows:
        room = by[r["room"]]
        main = codecheck.MAIN_USE[codecheck.letter(r["group"])]
        assert r["use"] in codecheck.USES
        assert r["load"] == codecheck.occupant_load(
            rect_area(room["rect"]), r["use"], main)
        assert r["factor"] == codecheck.USES[r["use"]][1]
        assert r["group"] == ("B" if room["zone"] == "office" else occ)
    bay = [r for r in rows if r["group"] == occ]
    assert all(r["use"] == ("industrial" if occ == "F-1" else "warehouse")
               for r in bay)


@pytest.mark.parametrize("sf,occ", [(5000, "S-1"), (200000, "S-1"),
                                    (40000, "F-1")])
def test_fixtures_exits_and_travel_are_codecheck_s(sf, occ):
    p = _wh(sf, occ)
    c = codes.analyze(p, store=False)
    loads = {}
    for r in c["rooms"]:
        loads[r["group"]] = loads.get(r["group"], 0) + r["load"]
    got = {f["group"]: f for f in c["fixtures"]}
    assert set(got) == set(loads)
    for g, n in loads.items():
        assert got[g]["load"] == n
        assert got[g]["fx"] == codecheck.fixtures(n, g)
    if occ == "F-1":                    # not in codecheck's short table
        assert got["F-1"]["fx"] is None
        assert "UNVERIFIED" in codes._fx_text(got["F-1"])
    ex = c["exits"]
    assert ex["load"] == sum(loads.values())
    assert ex["need"] == codecheck.exits_per_story(ex["load"])
    assert ex["factor_in"] == codecheck.egress_factors(occ, True)[0]
    assert ex["width_need_in"] == round(ex["load"] * ex["factor_in"], 1)
    for s in ex["two_exit_spaces"]:
        row = next(r for r in c["rooms"] if r["name"] == s["name"])
        assert s["max"] == codecheck.one_exit_max(row["group"])
        assert s["load"] > s["max"]
    lims = {codecheck.travel_limit(r["group"], True) for r in c["rooms"]}
    assert c["travel"]["limit"] == min(x for x in lims if x is not None)
    assert c["sprinklered_assumed"]
    assert any("UNVERIFIED" in n for n in c["notes"])


def test_parking_from_the_brief():
    from app.genset import brief
    f = brief.parse("80,000 sf warehouse, 140 parking spaces", use_ai=False)
    c = codes.analyze(layout.make_plan(f), store=False)
    acc = codecheck.accessible_parking(140)
    assert c["parking"] == {"spaces": 140, "accessible": acc,
                            "van": codecheck.van_parking(acc)}
    assert codes.analyze(_wh(80000), store=False)["parking"] is None


def test_codecheck_helpers_match_its_tables():
    assert [codecheck.exits_per_story(n) for n in (1, 500, 501, 1000,
                                                   1001)] == [2, 2, 3, 3, 4]
    assert codecheck.egress_factors("B", True, True) == (0.15, 0.2)
    assert codecheck.egress_factors("B", True, False) == (0.2, 0.3)
    assert codecheck.egress_factors("H-2", True, True) == (0.2, 0.3)
    for g in ("S-1", "F-1", "B", "M"):
        assert codecheck.one_exit_max(g) == codecheck._lookup(
            codecheck.ONE_EXIT_MAX, g)
        assert codecheck.travel_limit(g, True) == \
            codecheck._lookup(codecheck.TRAVEL, g)[1]
        assert codecheck.travel_limit(g, False) == \
            codecheck._lookup(codecheck.TRAVEL, g)[0]
    assert codecheck.travel_limit("Z-9") is None


def test_plan_carries_its_code_summary():
    p = _wh(30000)
    assert p["code"]["edition"] == codecheck.EDITION
    assert p["code"] == codes.analyze(p, store=False)


def test_code_sheet_prints_codecheck_s_numbers(tmp_path):
    fitz = pytest.importorskip("fitz")
    if not callable(getattr(fitz, "open", None)):
        pytest.skip("PyMuPDF not installed (a stand-in module)")
    from app.genset.titleblock import start_sheet
    p = _wh(200000)
    doc = fitz.open()
    pg = start_sheet(doc, p, "G-003", "Code Summary", "NTS")
    codes.sheet(pg, p)
    text = doc[0].get_text()
    c = codes.analyze(p, store=False)
    assert "CODE SUMMARY" in text and "UNVERIFIED" in text
    for r in c["rooms"]:
        assert r["name"] in text
    assert f"{c['exits']['need']} needed for {c['exits']['load']} " \
        "occupants" in text
    s1 = next(f for f in c["fixtures"] if f["group"] == "S-1")
    assert f"{s1['fx']['wc']} WC" in text
    doc.close()
