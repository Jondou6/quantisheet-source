"""Generate Set Phase 1 groundwork: the building-type registry, schema 2,
and - first of all - that houses, office and retail come out exactly as
they did before it (golden plan JSON written from the code before the
change, tests/data/genset_golden/)."""
import copy
import json
import os

import pytest

from app.genset import audit, brief, build, layout, model, types

GOLDEN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data",
                      "genset_golden")


def _cases():
    with open(os.path.join(GOLDEN, "cases.json"), encoding="utf-8") as f:
        return json.load(f)


def _plan(case):
    if "brief" in case:
        return build.plan_from_brief(case["brief"], use_ai=False)
    return layout.make_plan(dict(case["fields"]))


def _derived(p):
    from app.genset import ada_plan, notes, quantities, schedules
    out = {"audit": [list(r) for r in audit.audit(p)],
           "sheets": [list(s) for s in build.sheets_for(p)],
           "quantities": [list(r) for r in quantities.rows(p)],
           "rooms": schedules.room_rows(p), "doors": schedules.door_rows(p),
           "windows": schedules.window_rows(p),
           "notes": notes.template_project_notes(p)}
    if p["project"]["building_type"] != "single_family":
        out["ada"] = [list(r) for r in ada_plan.checks(p)]
        out["scoping"] = ada_plan.scoping(p)
    return json.loads(json.dumps(out))


@pytest.mark.parametrize("name", sorted(_cases()))
def test_golden_plans_are_byte_identical(name):
    """The plan JSON is byte for byte what the code wrote before the type
    registry - except the schema line, deliberately /1 -> /2."""
    got = model.to_json(_plan(_cases()[name])) + "\n"
    with open(os.path.join(GOLDEN, name + ".json"), encoding="utf-8") as f:
        want = f.read()
    assert '"schema": "pdfstudio.genset_plan/1"' in want
    want = want.replace('"pdfstudio.genset_plan/1"', json.dumps(model.SCHEMA))
    assert got == want


@pytest.mark.parametrize("name", sorted(_cases()))
def test_golden_checks_sheets_and_quantities_unchanged(name):
    with open(os.path.join(GOLDEN, "derived.json"), encoding="utf-8") as f:
        want = json.load(f)[name]
    got = _derived(_plan(_cases()[name]))
    for k in want:
        assert got[k] == want[k], (name, k)


def test_golden_plans_saved_under_the_old_name_still_read():
    """The golden plans were saved before the rename (schema
    "pdfstudio.genset_plan/1"): they read, as today's schema."""
    with open(os.path.join(GOLDEN, "house_1story.json"),
              encoding="utf-8") as f:
        p = model.from_json(f.read())
    assert p["schema"] == model.SCHEMA
    model.validate(p)
    assert model.SCHEMA == "quantisheet.genset_plan/2"
    with pytest.raises(model.PlanError):
        model.from_json(json.dumps({"schema": "pdfstudio.genset_plan/9"}))


def test_registry():
    assert types.keys()[:3] == ["single_family", "small_commercial",
                                "warehouse"]
    assert types.get(None).key == "single_family"
    assert types.get("something_old").key == "small_commercial"
    for k in types.LEGACY:                 # the old constants, unchanged
        lim = types.limits(k)
        assert lim["sf"] == (layout.MIN_SF, layout.MAX_SF)
        assert (lim["max_w"], lim["max_d"]) == (layout.MAX_W, layout.MAX_D)
    assert types.limits("warehouse")["sf"] == (3000, 200000)
    assert types.limits("single_family")["stories"] == (1, 2)
    assert set(types.occupancies()) >= {"R-3", "B", "M", "S-1", "F-1"}
    assert brief.TYPES == tuple(types.keys())
    assert types.get("small_commercial").ada_use_for("M") == "retail"
    assert types.get("small_commercial").ada_use_for("B") == "office"


@pytest.mark.parametrize("text,key,occ", [
    ("100,000 sf distribution warehouse, new", "warehouse", "S-1"),
    ("40,000 sf manufacturing plant", "warehouse", "F-1"),
    ("12,000 sf machine shop", "warehouse", "F-1"),
    ("industrial building 20,000 sf", "warehouse", "F-1"),
    ("industrial warehouse 60,000 sf", "warehouse", "S-1"),
    ("fulfillment center 150,000 sf", "warehouse", "S-1"),
    ("cross-dock facility, 80,000 sf", "warehouse", "S-1"),
    ("5,000 sf flex space", "warehouse", "S-1"),
    ("tilt-up building 50,000 sf", "warehouse", "S-1"),
    ("PEMB 10,000 sf", "warehouse", "S-1"),
    ("metal building, 8,000 sf", "warehouse", "S-1"),
    ("30,000 sf with 6 dock doors", "warehouse", "S-1"),
    ("2 drive-ins, 9,000 sf", "warehouse", "S-1"),
    ("32' clear, 75,000 sf", "warehouse", "S-1"),
    ("logistics hub 120,000 sf", "warehouse", "S-1"),
])
def test_detect_claims_industrial_briefs(text, key, occ):
    hit = types.detect(text)
    assert hit and hit[0] == key and hit[1] == occ and hit[2], text
    f = brief.regex_fields(text)
    assert (f["building_type"], f["occupancy"]) == (key, occ)


@pytest.mark.parametrize("text", [
    "3 bed 2 bath ranch, about 1600 sf, new",
    "2,400 sf office, occupancy B, new", "4000 sf retail store, new",
    "3,000 sf retail store, remodel existing", "9,500 sf office building",
    "two story 2400 sf house, 4 bed 3 bath", "1600 sf house, garage",
    "a shop 2000 sf", "dental clinic 3,000 sf", "studio cottage 400 sf",
])
def test_detect_leaves_house_office_retail_alone(text):
    assert types.detect(text) is None
    f = brief.regex_fields(text)
    assert f.get("building_type") in (None, "single_family",
                                      "small_commercial")


def test_occupancy_words_and_form_pick():
    f = brief.regex_fields("60,000 sf warehouse, occupancy F-1")
    assert f["occupancy"] == "F-1"
    # an occupancy the type can't carry is ignored (an "R-1" house)
    f = brief.regex_fields("3 bed house 1600 sf, group R-1")
    assert f["occupancy"] == "R-3"
    got = brief.parse("a building, 20,000 sf, 4 dock doors",
                      form={"building_type": "warehouse"}, use_ai=False)
    assert got["occupancy"] == "S-1" and got["docks"] == 4


def test_ai_limits_follow_the_building_type():
    raw = json.dumps({"building_type": "warehouse", "gross_sf": 150000})
    f = brief.parse("big storage building, 150,000 sf, 12 dock doors",
                    ask=lambda _p: raw)
    assert f["building_type"] == "warehouse" and f["gross_sf"] == 150000
    assert f["docks"] == 12
    raw = json.dumps({"gross_sf": 50000})       # a house stays <= 8,000
    f = brief.parse("3 bed house, a few thousand sq ft", ask=lambda _p: raw)
    assert "gross_sf" not in f
    assert "warehouse" in brief.PROMPT and "S-1" in brief.PROMPT


def test_levels_read_floors_and_audit_asks_the_type():
    """A building with plan["floors"] is checked floor by floor, and the
    whole-building room check is the type's - an office needs a
    restroom, not a bedroom and a bath (it always asked for those)."""
    p = layout.make_plan({"building_type": "small_commercial",
                          "occupancy": "B", "gross_sf": 2400})
    up = {"level": {"name": "L2", "floor_elev": 14.0, "plate_height": 12.0,
                    "slab": 0.0},
          "walls": copy.deepcopy(p["walls"]),
          "rooms": copy.deepcopy(p["rooms"]),
          "openings": [o for o in copy.deepcopy(p["openings"])
                       if o.get("from_room") != "EXT"]}
    p["floors"] = [up]
    lv = model.levels(p)
    assert len(lv) == 2 and lv[1]["level"]["name"] == "L2"
    assert "floors" not in lv[1] and model.stories(p) == 2
    model.validate(p)
    res = {c: s for s, c, _d in audit.audit(p)}
    assert "Has a bedroom and a bath" not in res
    assert res["Has a restroom"] == "PASS"
    house = layout.make_plan({"building_type": "single_family",
                              "gross_sf": 2400, "stories": 2, "beds": 3,
                              "baths": 2})
    res = {c: s for s, c, _d in audit.audit(house)}
    assert res["Has a bedroom and a bath"] == "PASS"


def test_validate_rules_for_the_new_opening_and_wall_kinds():
    p = layout.make_plan({"building_type": "small_commercial",
                          "occupancy": "B", "gross_sf": 2400})
    inner = next(w for w in p["walls"] if w["kind"] == "interior")
    q = copy.deepcopy(p)
    q["openings"].append({"id": "OHX", "kind": "overhead", "mark": "OHX",
                          "type": "OH-D", "wall": inner["id"],
                          "along": model.wall_length(inner) / 2,
                          "width": 1.0, "height": 10.0})
    with pytest.raises(model.PlanError, match="exterior"):
        model.validate(q)


def test_footprint_limits_from_the_type():
    with pytest.raises(model.PlanError, match="8,000 SF"):
        layout.footprint(9000, "small_commercial")
    with pytest.raises(model.PlanError, match="starts at 400"):
        layout.footprint(300, "single_family")
    assert layout.footprint(1600, "single_family") == (50.0, 32.0)


def test_sheet_list_for_the_old_types_is_unchanged():
    one = [("G-001", "Cover"), ("G-002", "General Notes"),
           ("AS-101", "Site Plan"), ("A-101", "Floor Plan"),
           ("A-102", "Roof Plan"), ("A-201", "Exterior Elevations"),
           ("A-301", "Building Section"), ("A-601", "Room Schedule"),
           ("A-602", "Door & Window Schedules"),
           ("A-701", "Quantity Summary")]
    h = layout.make_plan({"building_type": "single_family",
                          "gross_sf": 1600})
    assert build.sheets_for(h) == one
    two = layout.make_plan({"building_type": "single_family",
                            "gross_sf": 2400, "stories": 2})
    assert [n for n, _t in build.sheets_for(two)][2:6] == \
        ["AS-101", "A-101", "A-102", "A-103"]
    shop = layout.make_plan({"building_type": "small_commercial",
                             "occupancy": "M", "gross_sf": 8000})
    # office and retail also get the G-003 Code Summary (Jon, Oct 20)
    assert build.sheets_for(shop) == one[:2] + [("G-003", "Code Summary")] + \
        one[2:] + [("A-801", "Accessibility")]


def test_scales_and_the_sheet_constants():
    fitz = pytest.importorskip("fitz")
    if not callable(getattr(fitz, "open", None)):
        pytest.skip("PyMuPDF not installed (a stand-in module)")
    from app.genset import draw, sheets, views
    assert views.SCALES[-1] == ("1/32\" = 1'-0\"", 2.25)
    assert [k for _l, k in views.SITE_SCALES] == \
        [18.0, 13.5, 9.0, 6.75, 4.5, 3.6, 2.4, 1.8, 1.44, 0.72]
    assert sheets.DRAW_W == draw.DRAW.width
    # every house / commercial plan fits at 1/16" or larger
    for bt, sf in (("single_family", 8000), ("small_commercial", 8000)):
        p = layout.make_plan({"building_type": bt, "gross_sf": sf,
                              "occupancy": "B" if bt != "single_family"
                              else "R-3"})
        W, D = p["footprint"]["width"], p["footprint"]["depth"]
        assert views.choose_scale(W, D, draw.DRAW)[1] >= 4.5
        assert sheets.elevation_layout(p) == "quad"


# ---- a lot given as an area (Oct 21 review) -------------------------------
@pytest.mark.parametrize("text,area", [
    ("4,000 sf restaurant with drive-thru on a 1 acre lot", 43560),
    ("strip center 20,000 sf, 0.75 ac", 32670),
    ("strip center 20,000 sf on a 40,000 SF lot", 40000),
    ("3 bed 2 bath house 1600 sf, 0.25 acre lot", 10890)])
def test_lot_given_as_an_area(text, area):
    from app.genset import build, site
    lot, _t = site.read_lot(text)
    assert lot == {"area": area}
    p = build.plan_from_brief(text, use_ai=False)
    s = p["site"]
    assert s["lot_from"] == "brief area (proportions assumed)"
    assert abs(s["lot_w"] * s["lot_d"] - area) / area < 0.01
    assert not any(w.startswith("Lot size not in the brief")
                   for w in p["warnings"])
    assert any(w.startswith("Lot dimensions not in the brief") and
               f"{area:,.0f} SF area" in w for w in p["warnings"])
    # the gross area is the building's, never the lot's
    assert p["project"]["gross_sf_target"] != area
    # proportions that fit the building and its side yards when the area
    # allows (a strip center is wide, not deep)
    W = p["footprint"]["width"] + 0.5
    assert s["lot_w"] >= W + 2 * s["setbacks"]["side"] - 1e-6


# ---- elevations stay inside the drawing area, every type (Oct 21) ---------
class _LevelBox:
    """Stands in for one floor's Modulor model: each face a plain wall
    outline the floor's plate height tall."""

    def __init__(self, lp):
        self.lp = lp

    def elevation(self, face):
        fp = self.lp["footprint"]
        span = fp["width"] if face in ("S", "N") else fp["depth"]
        h = self.lp["level"]["plate_height"]
        return [[(0, 0), (span, 0), (span, h), (0, h)]]


@pytest.mark.parametrize("name,fields", [
    ("house_1story", None), ("house_2story", None),
    ("house_2story_narrow", None), ("house_garage", None),
    ("house_porch", None), ("office", None), ("office_8000", None),
    ("retail", None), ("retail_existing", None),
    ("fields_house_small", None), ("fields_retail_8000", None),
    ("wh20000", {"building_type": "warehouse", "gross_sf": 20000}),
    ("wh60000", {"building_type": "warehouse", "gross_sf": 60000}),
    ("wh200000", {"building_type": "warehouse", "gross_sf": 200000})])
def test_elevations_drawn_inside_the_drawing_area_every_type(
        name, fields, monkeypatch):
    """Every stroke and word on the A-2xx elevation sheets lands inside the
    drawing area for houses (1- and 2-story), office, retail and warehouse
    sizes - the grade line, 6 ft past the building, ran off the left edge
    of the 2-story house (x=69) and the office (x=19.5)."""
    from test_genset_strip import _RecPage, _RecRect, _outside, \
        _record_with_stand_in
    from app.genset import draw, sheets, views
    area = _record_with_stand_in(monkeypatch)
    monkeypatch.setattr(views, "fitz", draw.fitz)
    monkeypatch.setattr(views, "DRAW", _RecRect(*area))
    monkeypatch.setattr(views, "_register_scale", lambda *a, **k: None)
    if fields is None:
        p = _plan(_cases()[name])
    else:
        p = layout.make_plan(dict(fields, name="T"))
    boxes = [_LevelBox(lp) for lp in model.levels(p)]
    specs = [s for s in sheets.specs_for(p) if s.no.startswith("A-2")]
    assert specs
    for sp in specs:
        page = _RecPage()
        sp.draw({"plan": p, "doc": None, "models": boxes,
                 "scales": {}, "pages": {}}, page)
        assert page.pts and page.texts, (name, sp.no)
        assert not _outside(page, area), (name, sp.no,
                                          _outside(page, area)[:4])
