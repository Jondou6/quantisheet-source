"""Generate Set Phase 1: the warehouse / industrial type (S-1 / F-1),
3,000 - 200,000 SF - its plan rules (pure Python) and its set (needs
PyMuPDF and Modulor; skipped without them)."""
import json
import math

import pytest

from app.genset import audit, brief, build, kernel_section, layout, model
from app.genset.types import warehouse as wh


def _wh(sf, cons="tilt-up", occ="S-1", **kw):
    return layout.make_plan(dict({"building_type": "warehouse",
                                  "gross_sf": sf, "construction": cons,
                                  "occupancy": occ}, **kw))


SWEEP = [(sf, cons) for sf in (5000, 10000, 25000, 50000, 100000, 150000,
                               200000) for cons in ("tilt-up", "pemb")]


@pytest.mark.parametrize("sf,cons", SWEEP)
def test_sweep_validates_checks_clean_and_reaches_every_room(sf, cons):
    for occ in ("S-1", "F-1"):
        p = _wh(sf, cons, occ)
        model.validate(p)
        fails = [r for r in audit.audit(p) if r[0] == "FAIL"]
        assert not fails, (sf, cons, occ, fails)
        assert set(layout.reachable(p)) == {r["id"] for r in p["rooms"]}
        gross = (p["footprint"]["width"] + 0.5) * \
            (p["footprint"]["depth"] + 0.5)
        assert abs(gross - sf) / sf <= 0.05
        assert p["project"]["occupancy"] == occ
        kinds = {r["type"] for r in p["rooms"]}
        assert {"lobby", "restroom", "riser"} <= kinds
        assert ("industrial" if occ == "F-1" else "warehouse") in kinds


@pytest.mark.parametrize("sf,cons", SWEEP)
def test_grid_lines_are_on_the_exterior_walls(sf, cons):
    from app.genset import grid
    p = _wh(sf, cons)
    g = p["grid"]
    W, D = p["footprint"]["width"], p["footprint"]["depth"]
    assert g["x"][0] == 0 and g["x"][-1] == W
    assert g["y"][0] == 0 and g["y"][-1] == D
    xs = {w["a"][0] for w in p["walls"] if w["kind"] == "exterior"}
    ys = {w["a"][1] for w in p["walls"] if w["kind"] == "exterior"}
    assert {g["x"][0], g["x"][-1]} == xs and {g["y"][0], g["y"][-1]} == ys
    bx, by = grid.bays(g)
    assert all(b == round(b) for b in bx + by)            # whole feet
    assert all(30 <= b <= 70 for b in bx + by), (bx, by)
    if g["speed_bay"]:
        assert by[-1] == 60.0                 # at the dock (north) wall
    assert len(g["x_labels"]) == len(g["x"]) and "I" not in g["y_labels"]


@pytest.mark.parametrize("sf,cons", SWEEP)
def test_overhead_doors_only_on_exterior_walls(sf, cons):
    p = _wh(sf, cons)
    walls = {w["id"]: w for w in p["walls"]}
    oh = [o for o in p["openings"] if o["kind"] == "overhead"]
    assert oh
    for o in oh:
        assert walls[o["wall"]]["kind"] == "exterior"
        if o.get("dock"):
            assert o["wall"] == "W3" and (o["width"], o["height"]) == \
                wh.DOCK
        else:
            assert (o["width"], o["height"]) == wh.DRIVE_IN
    docks = [o for o in oh if o.get("dock")]
    assert len(docks) == p["warehouse"]["docks"]
    assert len(docks) == max(1, round(sf / wh.SF_PER_DOCK)) or \
        any("dock doors fit" in w for w in p["warnings"])


def test_brief_fields_for_a_warehouse():
    text = ("New 100,000 sf distribution warehouse, tilt-up, 36' clear, "
            "18 dock doors, 2 drive-ins, 4,000 sf office, 120 parking "
            "spaces")
    f = brief.parse(text, use_ai=False)
    assert f["building_type"] == "warehouse" and f["occupancy"] == "S-1"
    assert f["gross_sf"] == 100000
    assert (f["docks"], f["drive_ins"], f["clear_ht"]) == (18, 2, 36.0)
    assert (f["construction"], f["office_sf"], f["parking"]) == \
        ("tilt-up", 4000.0, 120)
    p = layout.make_plan(f)
    assert p["warehouse"]["docks"] == 18
    assert p["warehouse"]["drive_ins"] == 2
    assert p["warehouse"]["clear_ht"] == 36.0
    assert p["level"]["plate_height"] == 36.0 + wh.STRUCTURE["tilt-up"]
    office = sum(r["area"] for r in p["rooms"] if r["zone"] == "office")
    assert 0.7 * 4000 <= office <= 1.3 * 4000
    assert not any("clear height" in a for a in p["warehouse"]["assumed"])
    f = brief.parse("40,000 sf PEMB manufacturing building", use_ai=False)
    p = layout.make_plan(f)
    assert p["project"]["occupancy"] == "F-1"
    assert p["roof"]["type"] == "gable" and p["roof"]["pitch"] == 1
    assert p["warehouse"]["clear_ht"] == 24.0
    assert any("clear height" in a for a in p["warehouse"]["assumed"])


def test_defaults_are_marked_assumed():
    p = _wh(60000, cons=None)
    asm = " ".join(p["warehouse"]["assumed"])
    for word in ("tilt-up", "clear height", "speed bay", "office about",
                 "dock doors", "drive-in", "truck court", "sprinklered"):
        assert word in asm, word
    assert p["truck_court"]["assumed"] and p["grid"]["assumed"]
    from app.genset import notes
    assert any(n.startswith("ASSUMED") for n in
               notes.template_project_notes(p))


def test_size_limits():
    with pytest.raises(model.PlanError, match="start at 3,000"):
        _wh(2000)
    with pytest.raises(model.PlanError, match="200,000"):
        _wh(250000)
    p = _wh(80000, stories=2)
    assert any("one story" in w for w in p["warnings"])
    assert model.stories(p) == 1


def test_the_warehouse_is_one_space_around_the_office():
    from app.genset import kernel_modulor
    p = _wh(50000)
    opened = [w for w in p["walls"] if w["kind"] == "open"]
    assert len(opened) == 1
    a, b = opened[0]["rooms"]
    by = {r["id"]: r for r in p["rooms"]}
    assert by[a]["type"] == by[b]["type"] == "warehouse"
    assert not [o for o in p["openings"] if o["wall"] == opened[0]["id"]]
    ops = kernel_modulor.ops(p)
    assert len([o for o in ops if o["op"] == "add_wall"]) == \
        len(p["walls"]) - 1
    assert all(o["type"] in ("door", "window") for o in ops
               if o["op"] == "add_opening")
    # turned east-west, it would still never be cut as a wall
    q = json.loads(json.dumps(p))
    w = next(w for w in q["walls"] if w["kind"] == "open")
    w["a"], w["b"] = [0.25, 40.0], [30.0, 40.0]
    assert all(k != "open" for _y, _t, k in kernel_section.cut_walls(q, 10))
    res = {c: s for s, c, _d in audit.audit(p)}
    assert res["Every room has a door"] == "PASS"
    assert res["Every room reached from an outside door"] == "PASS"


def test_office_part_plan_is_the_office_alone():
    from app.genset.types import warehouse_draw
    p = _wh(100000)
    sub = warehouse_draw.office_subplan(p)
    x0, y0, x1, y1 = p["warehouse"]["office_rect"]
    assert {r["zone"] for r in sub["rooms"]} == {"office"}
    for w in sub["walls"]:
        for x, y in (w["a"], w["b"]):
            assert -1e-6 <= x <= x1 + 1e-6 and -1e-6 <= y <= y1 + 1e-6
    for o in sub["openings"]:
        w = next(w for w in sub["walls"] if w["id"] == o["wall"])
        L = model.wall_length(w)
        assert 0.5 - 1e-6 <= o["along"] - o["width"] / 2
        assert o["along"] + o["width"] / 2 <= L - 0.5 + 1e-6
    front = next(o for o in sub["openings"] if o.get("from_room") == "EXT"
                 and o["wall"] == "W1")
    assert front["to_room"] == p["rooms"][0]["id"]      # into the lobby


def test_exits_and_travel_from_the_code_tables():
    from app import codecheck
    for sf in (5000, 50000, 200000):
        p = _wh(sf)
        c = p["code"]
        ex = c["exits"]
        assert ex["need"] == codecheck.exits_per_story(ex["load"])
        assert ex["have"] >= ex["need"]
        assert c["travel"]["limit"] == codecheck.travel_limit("S-1", True)
        assert c["travel"]["max_ft"] <= c["travel"]["limit"]
        assert c["travel"]["approximate"]


def test_schedules_and_quantities():
    from app.genset import quantities, schedules
    p = _wh(100000)
    oh = schedules.overhead_rows(p)
    dock = next(r for r in oh if r[0] == "OH-D")
    assert int(dock[3]) == p["warehouse"]["docks"]
    assert dock[4].startswith("OH1-OH")
    assert not [r for r in schedules.door_rows(p) if r[0].startswith("OH")]
    q = {r[1]: r for r in quantities.rows(p)}
    assert q["Tilt-up wall panels, gross"][2] > 0
    assert q["Dock levelers (assumed at every dock door)"][2] == \
        p["warehouse"]["docks"]
    assert q["Dock bumpers"][2] == 2 * p["warehouse"]["docks"]
    pe = {r[1]: r for r in quantities.rows(_wh(100000, "pemb"))}
    assert pe["PEMB rigid frames (interior grid lines)"][2] == \
        len(_wh(100000, "pemb")["grid"]["x"]) - 2
    assert "Tilt-up wall panels, gross" not in pe
    assert schedules._marks(["OH1", "OH2", "OH3", "OH5"]) == "OH1-OH3, OH5"


def test_site_has_the_truck_court():
    p = _wh(100000)
    s = p["site"]
    tc = p["truck_court"]["depth"]
    assert s["provided"]["rear"] >= tc + s["setbacks"]["rear"] - 1e-6
    res = {c: st for st, c, _d in audit.audit(p)}
    assert res["Truck court fits on the lot"] == "PASS"
    q = layout.make_plan({"building_type": "warehouse", "gross_sf": 100000,
                          "lot": {"w": 500, "d": 300}})
    res = {c: st for st, c, _d in audit.audit(q)}
    assert res["Truck court fits on the lot"] == "WARN"


def test_sheet_list():
    p = _wh(200000)
    nos = [n for n, _t in build.sheets_for(p)]
    assert nos == ["G-001", "G-002", "G-003", "AS-101", "A-101", "A-102",
                   "A-103", "A-201", "A-202", "A-301", "A-601", "A-602",
                   "A-701", "A-801"]
    small = [n for n, _t in build.sheets_for(_wh(5000))]
    assert "A-202" not in small and "A-201" in small
    assert json.loads(model.to_json(p))["schema"] == model.SCHEMA


# ---- the set (PyMuPDF + Modulor) -----------------------------------------
def _set_tools():
    fitz = pytest.importorskip("fitz")
    if not callable(getattr(fitz, "open", None)):
        pytest.skip("PyMuPDF not installed (a stand-in module)")
    pytest.importorskip("modulor")
    return fitz


def _inside_draw(page):
    """Drawings and words left of the title block that stray outside the
    sheet's DRAW area (the border and the watermark aside)."""
    from app.genset import DISCLAIMER, draw
    D = draw.DRAW
    out = []
    for d in page.get_drawings():
        r = d["rect"]
        if r.x0 >= D.x1 or r.width >= D.width + 2:
            continue                   # the title block, the sheet border
        if r.x0 < D.x0 - 2 or r.y0 < D.y0 - 2 or r.x1 > D.x1 + 2 or \
                r.y1 > D.y1 + 2:
            out.append(("drawing", tuple(round(v) for v in r)))
    wm = set(DISCLAIMER.split())
    for x0, y0, x1, y1, word, *_ in page.get_text("words"):
        if x0 >= D.x1 or word in wm:
            continue
        if x0 < D.x0 - 2 or y0 < D.y0 - 2 or x1 > D.x1 + 2 or y1 > D.y1 + 2:
            out.append((word, round(x0), round(y0)))
    return out


@pytest.mark.parametrize("brief_text", [
    "200,000 sf distribution warehouse, tilt-up, new",
    "200,000 sf PEMB warehouse, new",
    "8,000 sf flex space, new"])
def test_set_builds_and_the_plan_fits_the_sheet(brief_text, tmp_path):
    fitz = _set_tools()
    from app import genset_ui
    out = str(tmp_path / "wh.pdf")
    res = genset_ui.generate({"brief": brief_text,
                              "form": {"name": "Test Warehouse"}}, out,
                             use_ai=False)
    side = json.load(open(res["sidecar"]))
    sheets = build.sheets_for(side)
    doc = fitz.open(out)
    try:
        assert res["pages"] == doc.page_count == len(sheets)
        labels = [pg.get_label() for pg in doc]
        assert labels == [n for n, _t in sheets]
        from app.genset import DISCLAIMER
        for pg in doc:
            assert DISCLAIMER in pg.get_text()
        a101 = doc[labels.index("A-101")]
        assert not _inside_draw(a101), _inside_draw(a101)[:5]
        g003 = doc[labels.index("G-003")].get_text()
        assert "CODE SUMMARY" in g003 and "UNVERIFIED" in g003
        assert "OVERHEAD DOOR SCHEDULE" in \
            doc[labels.index("A-602")].get_text()
        assert "TRUCK COURT" in doc[labels.index("AS-101")].get_text()
    finally:
        doc.close()
    assert res["self_check"] in ("PASS", "WARN")
    assert side["project"]["building_type"] == "warehouse"
    assert math.isclose(side["grid"]["x"][-1], side["footprint"]["width"])
