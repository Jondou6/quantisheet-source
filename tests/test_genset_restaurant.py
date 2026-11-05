"""Generate Set Phase 2: the stand-alone restaurant (A-2), 2,000 - 12,000
SF - its plan rules (pure Python) and its set (needs PyMuPDF and Modulor;
skipped without them)."""
import json

import pytest

from app import codecheck
from app.genset import audit, brief, build, layout, model, types
from app.genset.types import restaurant as rs


def _rs(sf=None, **kw):
    f = {"building_type": "restaurant"}
    if sf:
        f["gross_sf"] = sf
    f.update(kw)
    return layout.make_plan(f)


SWEEP = [(sf, dt) for sf in (2000, 2600, 3500, 5000, 6500, 8000, 10000,
                             12000) for dt in (False, True)]
BOH = {"KITCHEN", "PREP", "DISH", "WALK-IN COOLER", "WALK-IN FREEZER",
       "DRY STORAGE", "OFFICE"}


@pytest.mark.parametrize("sf,dt", SWEEP)
def test_sweep_validates_checks_clean_and_reaches_every_room(sf, dt):
    p = _rs(sf, drive_thru=dt)
    model.validate(p)
    fails = [r for r in audit.audit(p) if r[0] == "FAIL"]
    assert not fails, (sf, dt, fails)
    assert set(layout.reachable(p)) == {r["id"] for r in p["rooms"]}
    gross = (p["footprint"]["width"] + 0.5) * (p["footprint"]["depth"] + 0.5)
    assert abs(gross - sf) / sf <= 0.06
    assert p["project"]["occupancy"] == "A-2"
    names = {r["name"] for r in p["rooms"]}
    assert BOH | {"DINING", "MEN", "WOMEN"} <= names
    assert ("DRIVE-THRU" in names) == dt
    rooms = p["rooms"]
    for i, a in enumerate(rooms):
        for b in rooms[i + 1:]:
            assert model._overlap(a["rect"], b["rect"]) < 0.01
    from app.genset import ada_plan
    bad = [r for r in ada_plan.checks(p) if r[0] == "FAIL"]
    assert not bad, bad


@pytest.mark.parametrize("sf,dt", SWEEP)
def test_restrooms_are_sized_from_the_ipc_table(sf, dt):
    from app.genset import codes
    p = _rs(sf, drive_thru=dt)
    c = codes.analyze(p, store=False)
    load = c["exits"]["load"]
    fx = codecheck.fixtures(load, "A-2")
    assert p["restaurant"]["occupant_load"] == load
    assert p["restaurant"]["fixtures"] == fx
    for name in ("MEN", "WOMEN"):
        r = next(r for r in p["rooms"] if r["name"] == name)
        assert r["fixtures"] == {"wc": fx["wc_each"], "lav": fx["lav_each"]}
        w, d = r["rect"][2] - r["rect"][0], r["rect"][3] - r["rect"][1]
        need = rs.restroom_size(fx["wc_each"], fx["lav_each"])
        assert w >= need[0] - 0.5 and d >= need[1] - 0.5, (name, w, d)
    res = {c_: s for s, c_, _d in audit.audit(p)}
    assert res["Restrooms per IPC Table 2902.1 (A-2, screening)"] == "PASS"
    assert res["Separate men's and women's restrooms"] == "PASS"


@pytest.mark.parametrize("sf,dt", SWEEP)
def test_doors_and_exits(sf, dt):
    p = _rs(sf, drive_thru=dt)
    by = {r["id"]: r for r in p["rooms"]}
    walls = {w["id"]: w for w in p["walls"]}
    ext = [o for o in p["openings"] if o["kind"] == "door" and
           o.get("from_room") == "EXT"]
    assert len(ext) == 3                    # entrance, dining exit, service
    assert {walls[o["wall"]]["face"] for o in ext} == {"S", "W", "N"}
    rec = [o for o in ext if o.get("receiving")]
    assert len(rec) == 1 and by[rec[0]["to_room"]]["name"] == "KITCHEN"
    ent = next(o for o in ext if o.get("entrance"))
    assert by[ent["to_room"]]["name"] in ("DINING", "WAITING")
    # the dining room's two exits never pass through the kitchen
    assert len(rs.dining_exits(p)) >= 2
    # every back-of-house room opens off the kitchen (the freezer off the
    # prep room or the cooler)
    kid = next(r["id"] for r in p["rooms"] if r["name"] == "KITCHEN")
    off = {by[o["to_room"]]["name"] for o in p["openings"]
           if o.get("from_room") == kid}
    assert BOH - {"KITCHEN", "WALK-IN FREEZER"} <= off
    frz = next(o for o in p["openings"] if o.get("to_room") in by and
               by[o["to_room"]]["name"] == "WALK-IN FREEZER")
    assert by[frz["from_room"]]["name"] in ("PREP", "WALK-IN COOLER")
    c = p["code"]
    assert c["exits"]["have"] >= c["exits"]["need"]
    assert c["exits"]["width_have_in"] >= c["exits"]["width_need_in"]
    assert c["travel"]["limit"] == codecheck.travel_limit("A-2", True)
    assert c["travel"]["max_ft"] <= c["travel"]["limit"]
    if dt:
        win = [o for o in p["openings"] if o.get("drive_thru")]
        assert len(win) == 1 and win[0]["wall"] == "W2"
        assert by[win[0]["room"]]["name"] == "DRIVE-THRU"
        assert p["drive_thru"]["lane_w"] == rs.LANE_W
    else:
        assert "drive_thru" not in p


def test_brief_fields_for_a_restaurant():
    f = brief.parse("New 4,500 sf restaurant with a drive-thru, 140 seats, "
                    "60 parking spaces", use_ai=False)
    assert f["building_type"] == "restaurant" and f["occupancy"] == "A-2"
    assert (f["gross_sf"], f["seats"], f["drive_thru"], f["parking"]) == \
        (4500, 140, True, 60)
    p = layout.make_plan(f)
    assert p["restaurant"]["drive_thru"] and p["restaurant"]["seats"] == 140
    assert p["parking"]["spaces"] == 60 and not p["parking"]["assumed"]
    f = brief.parse("120 seat diner, new", use_ai=False)
    p = layout.make_plan(f)
    dining = next(r for r in p["rooms"] if r["name"] == "DINING")
    assert dining["area"] >= 0.95 * 120 * rs.SEAT_SF
    assert any("from 120 seats" in a for a in p["restaurant"]["assumed"])
    f = brief.parse("cafe, group A-2, 3,000 sf", use_ai=False)
    assert f["occupancy"] == "A-2"


@pytest.mark.parametrize("text,dt", [
    ("3,500 sf restaurant, 120 seats", False),
    ("cafe 2,400 sf", False),
    ("diner 3,000 sf, new", False),
    ("drive-thru coffee 2,200 sf", True),
    ("fast food restaurant with drive-through, 3,000 sf", True),
    ("coffee shop 2,500 sf", False),
    ("PEMB restaurant 4,000 sf", False),
    ("bistro 2,800 sf", False),
])
def test_detect_claims_restaurant_briefs(text, dt):
    hit = types.detect(text)
    assert hit and hit[0] == "restaurant" and hit[1] == "A-2", text
    f = brief.regex_fields(text)
    assert f["building_type"] == "restaurant"
    assert bool(f.get("drive_thru")) == dt


@pytest.mark.parametrize("text", [
    "drive-thru bank 3,000 sf", "3 bed 2 bath ranch, kitchen and dining, "
    "1800 sf", "4000 sf retail store, new", "2,400 sf office, new",
    "100,000 sf distribution warehouse, new"])
def test_detect_leaves_other_briefs_alone(text):
    f = brief.regex_fields(text)
    assert f.get("building_type") != "restaurant", text


def test_defaults_are_marked_assumed():
    p = _rs(6000, drive_thru=True)
    asm = " ".join(p["restaurant"]["assumed"])
    for word in ("walk-in", "seats", "parking spaces", "IPC Table 2902.1",
                 "hood", "grease interceptor", "receiving", "parapet",
                 "sprinklered", "drive-thru"):
        assert word in asm, word
    assert p["parking"]["assumed"] and p["drive_thru"]["assumed"]
    assert p["restaurant"]["grease_interceptor"]["assumed"]
    from app.genset import codes, notes
    nn = notes.template_project_notes(p)
    assert any(n.startswith("ASSUMED") for n in nn)
    assert codes.assumed(p) == p["restaurant"]["assumed"]
    assert any("903.2.1.2" in n for n in codes.sprinkler_notes(p))


def test_size_limits():
    with pytest.raises(model.PlanError, match="start at 2,000"):
        _rs(1500)
    with pytest.raises(model.PlanError, match="12,000"):
        _rs(15000)
    with pytest.raises(model.PlanError, match="gross SF or the number"):
        _rs()
    p = _rs(4000, stories=2)
    assert any("one story" in w for w in p["warnings"])
    assert model.stories(p) == 1
    p = _rs(seats=30)                         # under the smallest size
    assert p["project"]["gross_sf_target"] == 2000
    assert any("30 seats make" in w for w in p["warnings"])


def test_kitchen_part_plan_is_the_back_of_house():
    p = _rs(8000)
    sub = rs.kitchen_subplan(p)
    assert {r["zone"] for r in sub["rooms"]} == {"back"}
    assert BOH <= {r["name"] for r in sub["rooms"]}
    w_, d_ = sub["footprint"]["width"], sub["footprint"]["depth"]
    for r in sub["rooms"]:
        x0, y0, x1, y1 = r["rect"]
        assert -1e-6 <= x0 and x1 <= w_ + 1e-6
        assert -0.25 - 1e-6 <= y0 and y1 <= d_ + 1e-6
    for o in sub["openings"]:
        w = next(w for w in sub["walls"] if w["id"] == o["wall"])
        L = model.wall_length(w)
        assert 0.5 - 1e-6 <= o["along"] - o["width"] / 2
        assert o["along"] + o["width"] / 2 <= L - 0.5 + 1e-6
    assert any(o.get("receiving") for o in sub["openings"])


def test_schedules_quantities_scoping_and_code_lines():
    from app.genset import ada_plan, codes, quantities, schedules
    p = _rs(5000, drive_thru=True)
    q = {r[1]: r for r in quantities.rows(p)}
    fx = p["restaurant"]["fixtures"]
    assert q["Water closets (IPC 2902.1, A-2)"][2] == fx["wc"]
    assert q["Lavatories"][2] == fx["lav"]
    assert q["Type I kitchen hood (assumed)"][2] == p["restaurant"]["hood_lf"]
    assert q["Grease interceptor (assumed)"][2] == 1
    assert q["Drive-thru lane paving (assumed)"][2] > 0
    assert q["Storefront glazing"][2] > 0
    rows = schedules.room_rows(p)
    kit = next(r for r in rows if r[1] == "KITCHEN")
    assert kit[3:7] == ["QT", "QT", "FRP", "ACT-V"]
    assert {r[1] for r in schedules.window_rows(p)} >= {
        p["window_types"]["DT"]}
    proj = ada_plan.scoping(p)
    assert proj["use"] == "restaurant"
    assert proj["dining_seats"] == p["restaurant"]["seats_drawn"]
    assert {t["name"] for t in proj["toilet_rooms"]} == {"MEN", "WOMEN"}
    assert all(t["water_closets"] == fx["wc_each"]
               for t in proj["toilet_rooms"])
    from app import ada_check
    found = ada_check.check(proj)
    assert any("dining" in f.item.lower() for f in found)
    lines = rs.code_lines(p, codes.analyze(p, store=False))
    assert all(len(row) == 3 for row in lines)
    assert f"{fx['wc_each']} WC" in lines[0][1]


def test_parking_and_site():
    p = _rs(4000)
    pk = p["parking"]
    assert pk["spaces"] == 40                   # 10 per 1,000 SF assumed
    assert p["site"]["provided"]["front"] >= pk["depth"] - 1e-6
    res = {c: v for v, c, _d in audit.audit(p)}
    assert res["Parking field fits in front"] == "PASS"
    d = _rs(4000, drive_thru=True)
    assert d["site"]["lot_w"] >= p["site"]["lot_w"] + rs.LANE_W


def test_sheet_list():
    p = _rs(12000)
    assert [n for n, _t in build.sheets_for(p)] == [
        "G-001", "G-002", "G-003", "AS-101", "A-101", "A-102", "A-103",
        "A-201", "A-301", "A-601", "A-602", "A-701", "A-801"]
    assert dict(build.sheets_for(p))["A-102"] == "Enlarged Kitchen Plan"
    assert json.loads(model.to_json(p))["schema"] == model.SCHEMA


# ---- the set (PyMuPDF + Modulor) -----------------------------------------
def _set_tools():
    fitz = pytest.importorskip("fitz")
    if not callable(getattr(fitz, "open", None)):
        pytest.skip("PyMuPDF not installed (a stand-in module)")
    pytest.importorskip("modulor")
    return fitz


@pytest.mark.parametrize("brief_text", [
    "3,500 sf restaurant, new",
    "fast food restaurant with a drive-thru, 2,800 sf, new",
    "12,000 sf restaurant, 300 seats, new"])
def test_set_builds(brief_text, tmp_path):
    fitz = _set_tools()
    from app import genset_ui
    from test_genset_warehouse import _inside_draw
    out = str(tmp_path / "rest.pdf")
    res = genset_ui.generate({"brief": brief_text,
                              "form": {"name": "Test Restaurant"}}, out,
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
        assert "WALK-IN" in doc[labels.index("A-102")].get_text()
        g003 = doc[labels.index("G-003")].get_text()
        assert "CODE SUMMARY" in g003 and "A-2" in g003
        site = doc[labels.index("AS-101")].get_text()
        assert "PARKING" in site
        if "drive-thru" in brief_text:
            assert "DRIVE-THRU" in site
    finally:
        doc.close()
    assert res["self_check"] in ("PASS", "WARN")
    assert side["project"]["building_type"] == "restaurant"


# ---- AS-101 geometry: the layout as data, no PyMuPDF needed ---------------
def site_problems(plan):
    """Every label box that touches a stroked line (stalls, walks, lane,
    arrows, dimensions, setbacks, the lot, the building ...) or another
    label on the site plan, as (label, what it hits)."""
    from app.genset import views
    lay = views.site_layout(plan)
    texts = views.all_texts(lay)
    segs = views.all_segments(lay)
    out = []
    for t in texts:
        b = views.text_box(t)
        out.extend((t["s"], layer) for layer, a, c in segs
                   if views.seg_hits_box(a, c, b))
    boxes = [views.text_box(t) for t in texts]
    for i, t in enumerate(texts):
        for j in range(i + 1, len(texts)):
            if views.boxes_meet(boxes[i], boxes[j]):
                out.append((t["s"], texts[j]["s"]))
    return out


def sheet_box(lay, r):
    """A plan-feet rectangle on the sheet."""
    ox, oy, k = lay["ox"], lay["oy"], lay["ppf"]
    return (ox + r[0] * k, oy - r[3] * k, ox + r[2] * k, oy - r[1] * k)


def shrink(b, d):
    return (b[0] + d, b[1] + d, b[2] - d, b[3] - d)


def field_checks(plan):
    """Walk, dimensions and paving checks every parking site plan meets."""
    from app.genset import site as site_mod, views
    lay = views.site_layout(plan)
    f = lay["features"]
    assert lay["clashes"] == []
    # the walk runs beside the field, never through a parking row
    assert f["walks"]
    for w in f["walks"]:
        for r in f["rows"]:
            assert not views.boxes_meet(w["rect"], r), (w, r)
    # no dimension line or extension crosses the parking field
    rows = [shrink(sheet_box(lay, r), 0.5) for r in f["rows"]]
    for layer, a, c in views.all_segments(lay, {"dim"}):
        assert not any(views.seg_hits_box(a, c, rb) for rb in rows), (a, c)
    # the parking label is in the storefront walk band, the aisle labels
    # each in their aisle
    texts = views.all_texts(lay)
    band = sheet_box(lay, f["band"])
    pk = [t for t in texts if t["s"].startswith("PARKING")]
    assert pk and all(site_mod.inside(views.text_box(t), band) for t in pk)
    aisles = [sheet_box(lay, a) for a in f["aisles"]]
    al = [t for t in texts if "DRIVE AISLE" in t["s"]]
    assert len(al) == len(aisles)
    for t, a in zip(al, aisles):
        assert site_mod.inside(views.text_box(t), a)
    # the paving and the walks on the lot
    for r in f["rows"] + [f["band"]] + [w["rect"] for w in f["walks"]]:
        assert site_mod.inside(r, f["lot"]), r
    return lay


AS101 = [(sf, dt) for sf in (2000, 2600, 4000, 5000, 8000, 12000)
         for dt in (False, True)]


@pytest.mark.parametrize("sf,dt", AS101)
def test_site_plan_labels_clear_of_linework(sf, dt):
    p = _rs(sf, drive_thru=dt, seats=120 if sf == 4000 else None)
    assert site_problems(p) == []
    field_checks(p)


def test_site_plan_labels_clear_with_a_lot_from_the_brief():
    p = _rs(4000, drive_thru=True, lot={"w": 150, "d": 300,
                                       "setbacks": {"front": 25,
                                                    "side": 10,
                                                    "rear": 15}})
    assert site_problems(p) == []
    field_checks(p)


def _winding(poly, pt):
    """Winding number of the closed polygon around pt."""
    import math
    tot = 0.0
    for (x0, y0), (x1, y1) in zip(poly, poly[1:] + poly[:1]):
        a0 = math.atan2(y0 - pt[1], x0 - pt[0])
        a1 = math.atan2(y1 - pt[1], x1 - pt[0])
        d = a1 - a0
        while d > math.pi:
            d -= 2 * math.pi
        while d < -math.pi:
            d += 2 * math.pi
        tot += d
    return round(tot / (2 * math.pi))


@pytest.mark.parametrize("sf", (2000, 4000, 8000, 12000))
def test_drive_thru_lane_loops_round_the_building(sf):
    from app.genset import site as site_mod, views
    p = _rs(sf, drive_thru=True)
    lay = views.site_layout(p)
    f = lay["features"]
    ln = f["lane"]
    path = ln["path"]
    W, D = p["footprint"]["width"], p["footprint"]["depth"]
    # in from the far drive aisle, out into the first one
    assert site_mod.inside((*path[0], *path[0]), f["aisles"][-1])
    assert site_mod.inside((*path[-1], *path[-1]), f["aisles"][0])
    # orthogonal runs, round the building: closed through the parking
    # field it goes once round the building's centre, counterclockwise
    # (the window on the driver's left)
    for a, b in zip(path, path[1:]):
        assert abs(a[0] - b[0]) < 1e-9 or abs(a[1] - b[1]) < 1e-9
    assert _winding(path, (W / 2, D / 2)) == 1
    assert max(y for _x, y in path) > D            # behind the building
    # 12 ft wide, clear of the building, on the lot and in the setbacks
    # (the assumed lot is sized for it)
    assert ln["width"] == rs.LANE_W
    bld = shrink(f["building"], 0.01)
    for b in ln["boxes"]:
        assert not views.boxes_meet(b, bld), b
        assert site_mod.inside(b, f["lot"]) and site_mod.inside(
            b, f["envelope"])
    assert ln["in_lot"] and ln["in_setbacks"]
    # past the pick-up window on the east wall, on the queue run
    wx, wy, _ww = ln["window"]
    assert abs(wx - (W + 0.25)) < 1e-6 and path[1][1] < wy < path[2][1]
    win = next(o for o in p["openings"] if o.get("drive_thru"))
    assert wy == win["along"]
    # stacking for 8 cars (assumed) said, with the length shown
    assert ln["stack"] == rs.STACK and ln["need"] == rs.STACK * 20
    texts = views.all_texts(lay)
    stack = [t for t in texts if t["s"].startswith("STACKING 8 CARS "
                                                   "(ASSUMED)")]
    assert stack
    if ln["queue"] < ln["need"]:
        assert "VERIFY WITH ZONING" in stack[0]["s"]
    # the lane's label in the lane (the rear run), not rotated
    name = next(t for t in texts if t["s"].startswith("DRIVE-THRU LANE"))
    assert not name["rotate"] and "(ASSUMED)" in name["s"]
    assert site_mod.inside(views.text_box(name), sheet_box(lay,
                                                          ln["boxes"][2]))
    assert site_mod.inside(views.text_box(stack[0]),
                           sheet_box(lay, ln["boxes"][2]))
    # travel arrows on the queue, the rear and the return runs, each in
    # the lane and pointing the way round
    arrows = [it for it in lay["items"] if it["t"] == "arrows"]
    shafts = [it["placed"][0] for it in arrows if it["placed"]]
    assert len(shafts) >= 3
    lane_boxes = [sheet_box(lay, b) for b in ln["boxes"]]
    for a, b in shafts:
        assert any(site_mod.inside((*a, *a), lb) and
                   site_mod.inside((*b, *b), lb) for lb in lane_boxes)
    ups = [s for s in shafts if s[1][1] < s[0][1] - 1]        # north
    downs = [s for s in shafts if s[1][1] > s[0][1] + 1]      # south
    wests = [s for s in shafts if s[1][0] < s[0][0] - 1]
    xm = lay["ox"] + W / 2 * lay["ppf"]
    assert ups and all(s[0][0] > xm for s in ups)             # east side
    assert downs and all(s[0][0] < xm for s in downs)         # west side
    assert wests


def test_stacking_for_eight_cars_fits_the_4000_sf_sample():
    p = _rs(4000, drive_thru=True, seats=120)
    from app.genset import site as site_mod
    ln = site_mod.features(p)["lane"]
    assert ln["queue"] >= ln["need"] == 160
    assert not site_mod.features(p)["notes"]


def test_drive_thru_on_a_tight_lot_says_verify_with_zoning():
    from app.genset import site as site_mod, views
    p = _rs(4000, drive_thru=True, lot={"w": 110, "d": 280})
    f = site_mod.features(p)
    assert not (f["lane"]["in_lot"] and f["lane"]["in_setbacks"])
    lay = views.site_layout(p)
    assert any("VERIFY WITH ZONING" in t["s"] for t in views.all_texts(lay))


def test_assumed_lot_has_room_for_the_lane_and_walk():
    from app.genset import site as site_mod
    p, d = _rs(4000), _rs(4000, drive_thru=True)
    extra = 2 * (rs.LANE_W + site_mod.SIDE_WALK)
    assert d["site"]["lot_w"] >= p["site"]["lot_w"] + extra - 5
    assert not d["site"]["binding"] and d["site"]["on_lot"]


def test_site_quantities_follow_the_drawn_lane_and_walks():
    """0.12.35: the drive-thru paving is the lane drawn on AS-101 (its
    centreline x 12 ft), the 5 ft walks are counted, and the house-style
    4 ft walk across the parking field is gone."""
    from app.genset import quantities as gq, site
    p = _rs(4000, drive_thru=True)
    sq = site.site_quantities(p)
    ln = site.features(p)["lane"]
    assert sq["lane_sf"] == pytest.approx(sq["lane_lf"] * ln["width"])
    assert sq["lane_lf"] > 2 * p["footprint"]["depth"]     # goes round
    rows = {r[1]: r for r in rs.quantities(p)}
    assert rows["Drive-thru lane paving (assumed)"][2] == \
        pytest.approx(sq["lane_sf"], abs=1)
    assert rows["Side and service walks (assumed)"][2] > 0
    assert "Front walk, 4 ft" not in rows
    plain = {r[1] for r in rs.quantities(_rs(4000))}
    assert "Drive-thru lane paving (assumed)" not in plain
    house = layout.make_plan({"building_type": "house", "gross_sf": 2000})
    assert site.site_quantities(house) == {}
    assert "Front walk, 4 ft" in {r[1] for r in gq.rows(house)}


# ---- the pick-up window on the west wall (Oct 21) -------------------------
def _west(sf, **kw):
    """A drive-thru plan with the window moved to the west wall - no brief
    asks for it (the kitchen's drive-thru room is on the east), so an
    edited plan: plan["drive_thru"]["side"] "W" and the DT window on the
    west wall (W4 runs north to south: along = D - y)."""
    p = _rs(sf, drive_thru=True, **kw)
    D = p["footprint"]["depth"]
    win = next(o for o in p["openings"] if o.get("drive_thru"))
    y = win["along"]                               # the east wall: along = y
    win["wall"], win["along"] = "W4", D - y
    p["drive_thru"].update(side="W", window_wall="W4")
    return p, y


@pytest.mark.parametrize("sf", (2000, 4000, 8000, 12000))
def test_drive_thru_lane_with_the_window_on_the_west(sf):
    import math
    from app.genset import site as site_mod, views
    p, wy0 = _west(sf)
    lay = views.site_layout(p)
    f = lay["features"]
    ln = f["lane"]
    path = ln["path"]
    W, D = p["footprint"]["width"], p["footprint"]["depth"]
    assert ln["side"] == "W"
    # in from the far drive aisle, out into the first one
    assert site_mod.inside((*path[0], *path[0]), f["aisles"][-1])
    assert site_mod.inside((*path[-1], *path[-1]), f["aisles"][0])
    # orthogonal runs, once round the building counterclockwise: the
    # window on the driver's left, as on the east
    for a, b in zip(path, path[1:]):
        assert abs(a[0] - b[0]) < 1e-9 or abs(a[1] - b[1]) < 1e-9
    assert _winding(path, (W / 2, D / 2)) == 1
    assert max(y for _x, y in path) > D            # behind the building
    # 12 ft wide, clear of the building, on the lot and in the setbacks
    assert ln["width"] == rs.LANE_W
    bld = shrink(f["building"], 0.01)
    for b in ln["boxes"]:
        assert not views.boxes_meet(b, bld), b
        assert site_mod.inside(b, f["lot"]) and site_mod.inside(
            b, f["envelope"])
    assert ln["in_lot"] and ln["in_setbacks"]
    # the window on the west wall at the opening's height, on the west run
    # (southbound there: the building on the driver's left), the lane on
    # that wall
    wx, wy, _ww = ln["window"]
    assert abs(wx + 0.25) < 1e-6 and abs(wy - wy0) < 1e-9
    a, b = path[3], path[4]
    assert ln["window_run"] == 3 and a[1] > wy > b[1] and a[0] < -0.25
    assert abs(a[0] - (-0.25 - rs.LANE_W / 2)) < 1e-6
    # the queue is the lane to the window: up the east run, the rear and
    # down the west run
    q = sum(math.hypot(v[0] - u[0], v[1] - u[1])
            for u, v in zip(path[:3], path[1:4])) + (a[1] - wy)
    assert abs(ln["queue"] - q) < 0.1
    # the labels: the lane's name and stacking in the rear run, the
    # pick-up window in the west run, nothing on a line or another label
    texts = views.all_texts(lay)
    assert site_problems(p) == [] and lay["clashes"] == []
    name = next(t for t in texts if t["s"].startswith("DRIVE-THRU LANE"))
    stack = next(t for t in texts if t["s"].startswith("STACKING"))
    for t in (name, stack):
        assert site_mod.inside(views.text_box(t), sheet_box(
            lay, ln["boxes"][2]))
    pick = [t for t in texts if t["s"] in ("PICK-UP", "WINDOW")]
    assert len(pick) == 2
    for t in pick:
        assert site_mod.inside(views.text_box(t), sheet_box(
            lay, ln["boxes"][3]))
    # the arrows in the lane, up the east side, west across the rear and
    # down the west side
    shafts = [it["placed"][0] for it in lay["items"]
              if it["t"] == "arrows" and it["placed"]]
    assert len(shafts) >= 3
    lane_boxes = [sheet_box(lay, b_) for b_ in ln["boxes"]]
    for s, e in shafts:
        assert any(site_mod.inside((*s, *s), lb) and
                   site_mod.inside((*e, *e), lb) for lb in lane_boxes)
    xm = lay["ox"] + W / 2 * lay["ppf"]
    ups = [s for s in shafts if s[1][1] < s[0][1] - 1]
    downs = [s for s in shafts if s[1][1] > s[0][1] + 1]
    assert ups and all(s[0][0] > xm for s in ups)
    assert downs and all(s[0][0] < xm for s in downs)
    assert [s for s in shafts if s[1][0] < s[0][0] - 1]
    # the walk on the east now (away from the window), the paving on the
    # lot, the crosswalk where the lane comes in
    field_checks(p)
    walk = next(w for w in f["walks"] if w["kind"] == "street")["rect"]
    assert walk[0] >= W + 0.25 - 1e-6
    cw = f["crosswalk"]
    assert cw and cw[0] >= W + 0.25 - 1e-6 and \
        cw[1] < path[0][1] < cw[3]
    # the set says west
    assert "west side" in " ".join(rs.notes(p))
    assert not [r for r in audit.audit(p) if r[0] == "FAIL"]


def test_east_window_lane_is_the_same_loop():
    """Moving the window only moves the lane to that wall and the walk to
    the other side: the same counterclockwise loop and the same aisles."""
    from app.genset import site as site_mod
    e = site_mod.features(_rs(4000, drive_thru=True))["lane"]
    w = site_mod.features(_west(4000)[0])["lane"]
    assert [round(y, 6) for _x, y in e["path"]] == \
        [round(y, 6) for _x, y in w["path"]]
    assert e["path"][1][0] - e["path"][4][0] == \
        w["path"][1][0] - w["path"][4][0]
    assert e["window_run"] == 1 and w["window_run"] == 3
    assert w["queue"] > e["queue"]       # it queues round the back too


# ---- walks and the front setback in the self-check (Oct 21 review) --------
def _cuts(r, s):
    return (min(r[2], s[2]) - max(r[0], s[0]) > 1e-6 and
            min(r[3], s[3]) - max(r[1], s[1]) > 1e-6)


@pytest.mark.parametrize("sf,dt", [(2000, False), (2000, True),
                                   (4500, True), (12000, False),
                                   (12000, True)])
def test_walks_follow_the_field_and_parking_clears_the_front_setback(sf, dt):
    from app.genset import site as site_mod, views
    p = _rs(sf, drive_thru=dt)
    f = site_mod.features(p)
    stalls = [(min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]),
               max(a[1], b[1])) for a, b in f["stalls"]]
    for w in f["walks"]:
        r = w["rect"]
        assert not any(_cuts(r, x) for x in f["rows"] + f["aisles"]), w
        # no stall line through a walk
        assert not any(views.seg_hits_box(s[:2], s[2:], shrink(r, 0.01))
                       for s in stalls), w
    # every stall behind the front setback line
    ey0 = f["envelope"][1]
    assert all(min(a[1], b[1]) >= ey0 - 1e-6 for a, b in f["stalls"])
    assert all(r[1] >= ey0 - 1e-6 for r in f["rows"])
    res = {c: v for v, c, _d in audit.audit(p)}
    assert res["Walks beside the parking, not across stalls or aisles"] \
        == "PASS"
    assert res["Parking out of the front setback"] == "PASS"
    assert audit.summary(audit.audit(p)) == "PASS"


def test_self_check_flags_a_walk_across_the_field():
    from app.genset import site as site_mod
    p = _rs(4500, drive_thru=True)
    f = site_mod.features(p)
    r = f["rows"][0]
    # a walk from the storefront to the street straight down the field
    f["walks"].append({"rect": ((r[0] + r[2]) / 2 - 2, p["site"]["lot_y0"],
                                (r[0] + r[2]) / 2 + 2, r[3]),
                       "kind": "street"})
    got = {c: (v, d) for v, c, d in audit.site_checks(p, f)}
    v, d = got["Walks beside the parking, not across stalls or aisles"]
    assert v == "FAIL" and "crossing" in d


def test_self_check_warns_on_parking_in_the_front_setback():
    from app.genset import site as site_mod
    # deep enough for the field, not for the field and the front yard too
    p = _rs(4500, lot={"w": 150, "d": 280})
    f = site_mod.features(p)
    assert min(r[1] for r in f["rows"]) < f["envelope"][1]
    res = {c: (v, d) for v, c, d in audit.audit(p)}
    v, d = res["Parking out of the front setback"]
    assert v == "WARN" and "front setback" in d and "zoning" in d
    assert audit.summary(audit.audit(p)) != "PASS"
    # ... unless the brief allows parking in the front yard
    lot, _t = site_mod.read_lot("4500 sf restaurant, lot 150 x 280, "
                                "parking allowed in the front setback")
    assert lot["front_parking"] and lot["d"] == 280
    q = _rs(4500, lot=lot)
    res = {c: (v, d) for v, c, d in audit.audit(q)}
    assert res["Parking out of the front setback"][0] == "PASS"
    assert "allowed by the brief" in res["Parking out of the front "
                                         "setback"][1]
    # an assumed lot is drawn deep enough for both
    a = _rs(4500)
    assert a["site"]["provided"]["front"] >= a["parking"]["depth"] + \
        a["site"]["setbacks"]["front"] - 1e-6


# ---- elevations stay inside the drawing area (Oct 21) ---------------------
class _BoxModel:
    """Stands in for the Modulor model: each face a plain wall outline."""

    def __init__(self, plan):
        self.plan = plan

    def elevation(self, face):
        fp = self.plan["footprint"]
        span = fp["width"] if face in ("S", "N") else fp["depth"]
        h = self.plan["level"]["plate_height"]
        return [[(0, 0), (span, 0), (span, h), (0, h)]]


@pytest.mark.parametrize("sf", (2000, 4000, 12000))
@pytest.mark.parametrize("dt", (False, True))
def test_elevations_drawn_inside_the_drawing_area(sf, dt, monkeypatch):
    """Every stroke and word on the A-2xx elevation sheets lands inside the
    drawing area (the 2,000 SF grade line ran 21 pt off its left edge)."""
    from test_genset_strip import _RecPage, _RecRect, _outside, \
        _record_with_stand_in
    from app.genset import draw, sheets, views
    area = _record_with_stand_in(monkeypatch)
    monkeypatch.setattr(views, "fitz", draw.fitz)
    monkeypatch.setattr(views, "DRAW", _RecRect(*area))
    monkeypatch.setattr(views, "_register_scale", lambda *a, **k: None)
    p = _rs(sf, drive_thru=dt)
    specs = [s for s in sheets.specs_for(p) if s.no.startswith("A-2")]
    assert specs
    for sp in specs:
        page = _RecPage()
        sp.draw({"plan": p, "doc": None, "models": _BoxModel(p),
                 "scales": {}, "pages": {}}, page)
        assert page.pts and page.texts, sp.no
        assert not _outside(page, area), (sp.no, _outside(page, area)[:4])


# ---- the parking field uses the lot's width (review of tonight's #10) -----
def _overlap(a, b):
    return (min(a[2], b[2]) - max(a[0], b[0]) > 1e-6 and
            min(a[3], b[3]) - max(a[1], b[1]) > 1e-6)


def _field_clear_of_lane_and_walks(f):
    lane = (f.get("lane") or {}).get("boxes") or []
    for r in f["rows"]:
        assert not any(_overlap(r, b) for b in lane), r
        assert not any(_overlap(r, w["rect"]) for w in f["walks"]), r
        assert _inside_x(r, f["envelope"]), r


def _inside_x(r, env):
    return r[0] >= env[0] - 1e-6 and r[2] <= env[2] + 1e-6


def test_drive_thru_field_widens_on_a_lot_it_would_run_off():
    from app.genset import site as site_mod
    p = _rs(3000, drive_thru=True, seats=40, lot={"w": 150, "d": 200})
    pk = p["parking"]
    W = p["footprint"]["width"]
    # the building-wide field was 3 rows (196 ft) and ran 174 ft past the
    # front lot line; the lot's width takes it to 2 rows
    assert pk["rows"] == 2 and pk["depth"] == 134.0
    segs = pk["segments"]
    assert segs[0] == [-0.25, W + 0.25]              # the building's width
    assert len(segs) == 3                            # past the lane, walk
    f = site_mod.features(p)
    _field_clear_of_lane_and_walks(f)
    # too deep for the 20 ft front yard: the building moves back for it
    # (owner, Oct 22 - it stayed on the front setback, 0 of 30 drawn and
    # a 133.5 ft rear yard left over), every space drawn on the lot
    fit = f["parking_fit"]
    assert fit["fits"] and fit["required"] == pk["spaces"] == 30
    assert fit["drawn"] == fit["on_lot"] == 30 and fit["short"] == 0
    assert fit["past_front"] == 0
    assert site_problems(p) == []
    res = {c: v for v, c, _d in audit.audit(p)}
    assert res["Parking field fits in front"] == "PASS"
    # the lane still loops round the building, on the lot
    assert f["lane"]["in_lot"]
    # the paving quantity is the widened field's
    q = {r[1]: r for r in rs.quantities(p)}
    paved = q["Parking field paving (assumed layout)"]
    width = sum(b - a for a, b in segs)
    assert paved[2] == pytest.approx(width * (pk["depth"] - 10.0), abs=1)
    assert "side setbacks" in paved[4]


def _street_label_clear(lay):
    """The STREET label in the street (below the front lot line), clear of
    the parking rows, the lane and every other label and line."""
    from app.genset import site as site_mod, views
    f = lay["features"]
    st = [t for t in views.all_texts(lay) if t["s"].startswith("STREET")]
    assert len(st) == 1
    b = views.text_box(st[0])
    lot = sheet_box(lay, f["lot"])
    assert b[1] > lot[3]                           # past the front lot line
    keep = f["rows"] + list((f.get("lane") or {}).get("boxes") or ())
    assert not any(views.boxes_meet(b, sheet_box(lay, r)) for r in keep)
    assert not any(views.seg_hits_box(a, c, b)
                   for _l, a, c in views.all_segments(lay))
    others = [views.text_box(t) for t in views.all_texts(lay)
              if t is not st[0]]
    assert not any(views.boxes_meet(b, o) for o in others)
    return st[0]


def test_drive_thru_building_moves_back_for_the_field(monkeypatch):
    """Owner, Oct 22: on a lot from the brief the field doesn't fit in
    front of a building on the front setback, the building moves back
    toward the rear setback - as far as the field (the storefront walk
    and the rows) needs and no further - keeping its rear setback and the
    drive-thru lane and its service walk behind it on the lot."""
    from test_genset_strip import _stalls_on_the_lot
    from app.genset import site as site_mod, views
    from app.genset.types.parts import PARKING_ROW, WALK
    p = _rs(3000, drive_thru=True, seats=40, lot={"w": 150, "d": 200})
    s, pk = p["site"], p["parking"]
    D = p["footprint"]["depth"]
    sb = s["setbacks"]
    # just the field's depth: the walk band, a row, the second row
    need = WALK + 2 * PARKING_ROW - 2
    assert s["provided"]["front"] == pytest.approx(need) == 132.0
    assert s["set_back_for_parking"]
    assert s["provided"]["rear"] == pytest.approx(200 - 132 - (D + 0.5))
    assert s["provided"]["rear"] >= sb["rear"]          # its own setback
    assert not s["binding"] and s["on_lot"]
    lay, _segs, page = _draw_site_plan_recorded(p, monkeypatch)
    f = lay["features"]
    assert f["parking_fit"]["fits"] and f["parking_fit"]["drawn"] == 30
    assert all(r[1] >= f["lot"][1] - 1e-6 for r in f["rows"])
    _stalls_on_the_lot(lay)
    _field_clear_of_lane_and_walks(f)
    # a foot further forward and a row would run off the lot
    q = json.loads(json.dumps(p))
    q["site"]["lot_y0"] += 1.0
    assert not site_mod.features(q)["parking_fit"]["fits"]
    # the lane loop: in from the far aisle, round the back, out the first
    # aisle - on the lot, beside the building inside the side setbacks,
    # and behind it with its service walk in the rear yard
    ln = f["lane"]
    path = ln["path"]
    assert site_mod.inside((*path[0], *path[0]), f["aisles"][-1])
    assert site_mod.inside((*path[-1], *path[-1]), f["aisles"][0])
    assert _winding(path, (p["footprint"]["width"] / 2, D / 2)) == 1
    assert ln["in_lot"]
    env = f["envelope"]
    for b in ln["boxes"]:
        assert site_mod.inside(b, f["lot"])
        assert env[0] - 1e-6 <= b[0] and b[2] <= env[2] + 1e-6
    rear = [w["rect"] for w in f["walks"] if w["kind"] == "service" and
            w["rect"][1] >= D]
    assert rear and rear[0][3] - rear[0][1] == site_mod.SIDE_WALK
    assert max(b[3] for b in ln["boxes"]) <= f["lot"][3] + 1e-6
    assert "the lane does not fit on the lot" not in f["notes"]
    # the queue is longer for it: 42 ft shown before, now 130 ft
    assert ln["queue"] > 120
    # the STREET label clear of the field, the lane and everything else
    _street_label_clear(lay)
    assert site_problems(p) == [] and lay["clashes"] == []
    assert views.field_crossings(lay) == []
    # the self-checks
    res = {c: v for v, c, _d in audit.audit(p)}
    assert res["Parking field fits in front"] == "PASS"
    assert res["Building inside the setbacks"] == "PASS"
    assert res["Walks beside the parking, not across stalls or aisles"] \
        == "PASS"
    assert "FAIL" not in res.values()
    # the drawing, site data and notes
    txt = " ".join(t[4] for t in page.texts)
    assert "PARKING DOES NOT FIT THE LOT" not in txt
    assert "Parking fits the lot" not in txt
    assert "The building is set back 132'-0\" from the front lot line" in \
        txt
    assert "20'-0\" req. / 132'-0\" shown" in txt


def test_widened_field_that_fits_passes_the_field_checks():
    p = _rs(2000, drive_thru=True, lot={"w": 200, "d": 150})
    assert p["parking"].get("segments") and p["parking"]["rows"] == 1
    lay = field_checks(p)
    f = lay["features"]
    assert f["parking_fit"]["fits"]
    _field_clear_of_lane_and_walks(f)
    assert site_problems(p) == []
    # the building just the field's depth back (70 ft - it was 72): the
    # lane and its service walk then fit inside the rear setback line
    assert p["site"]["provided"]["front"] == 70.0
    assert f["lane"]["in_lot"] and f["lane"]["in_setbacks"]
    q = _rs(3000, lot={"w": 150, "d": 200})           # no drive-thru
    segs = q["parking"]["segments"]
    assert segs[0][1] > q["footprint"]["width"] + 0.25   # out to a setback
    _field_clear_of_lane_and_walks(_features(q))


def _features(p):
    from app.genset import site as site_mod
    return site_mod.features(p)


def test_field_stays_building_wide_when_it_fits_or_nothing_is_saved():
    for p in (_rs(3000, drive_thru=True),                  # assumed lot
              _rs(3000, drive_thru=True, lot={"w": 150, "d": 400}),
              _rs(4000, drive_thru=True, lot={"w": 100, "d": 160})):
        assert "segments" not in p["parking"], p["site"]


# ---- the drive-thru lane edges are open lines (review of 0.12.38 #3) ------
class _PathShape:
    """A recording Shape with PyMuPDF's path rules: a draw_* call that
    starts where the last one ended continues the same subpath (no new
    moveto), a rect is a closed subpath of its own, and finish() closes
    the subpath in progress unless closePath=False - then strokes every
    segment drawn since the last finish when it has a colour."""

    def __init__(self, page):
        self.page = page
        self.segs, self.start, self.last = [], None, None

    def _to(self, a, b):
        a, b = (a.x, a.y), (b.x, b.y)
        if self.last is None or self.last != a:
            self.start = a                                # moveto
        self.segs.append((a, b))
        self.last = b

    def draw_line(self, a, b):
        self._to(a, b)

    def draw_polyline(self, pts):
        from test_genset_strip import _RecPoint
        if self.last is None or self.last != (pts[0].x, pts[0].y):
            self.start, self.last = (pts[0].x, pts[0].y), None
        self.last = (pts[0].x, pts[0].y)
        for a, b in zip(pts, pts[1:]):
            self._to(_RecPoint(*a), _RecPoint(*b))

    def draw_rect(self, r):
        c = [(r.x0, r.y0), (r.x1, r.y0), (r.x1, r.y1), (r.x0, r.y1),
             (r.x0, r.y0)]
        self.segs += list(zip(c, c[1:]))
        self.start = self.last = (r.x0, r.y0)

    def draw_circle(self, c, r):
        self.start = self.last = None

    def draw_bezier(self, *pts):
        for a, b in zip(pts, pts[1:]):           # the control polygon
            self._to(a, b)

    def finish(self, closePath=True, color=(0, 0, 0), **kw):
        if closePath and self.start is not None and self.last is not None \
                and self.last != self.start:
            self.segs.append((self.last, self.start))
        if color is not None:
            self.page.segs.extend(self.segs)
        self.segs, self.start, self.last = [], None, None

    def commit(self):
        pass


def _draw_site_plan_recorded(plan, monkeypatch):
    """views.site_plan drawn on the recording stand-in: (layout, stroked
    segments in sheet points, page)."""
    from test_genset_strip import _RecPage, _record_with_stand_in
    from app.genset import draw, views
    _record_with_stand_in(monkeypatch)            # draw.py on the stand-in
    monkeypatch.setattr(views, "fitz", draw.fitz)
    monkeypatch.setattr(views, "DRAW", draw.DRAW)
    monkeypatch.setattr(views, "_register_scale", lambda *a, **k: None)
    page = _RecPage()
    page.segs = []
    page.new_shape = lambda: _PathShape(page)
    views.site_plan(None, page, plan)
    return views.site_layout(plan), page.segs, page


def _long_lines_across_rows(lay, segs):
    """Drawn segments longer than a stall that run into a parking row."""
    import math
    from app.genset import site as site_mod, views
    rows = [shrink(sheet_box(lay, r), 0.5) for r in lay["features"]["rows"]]
    stall = site_mod.STALL_D * lay["ppf"] + 0.5
    return [(a, b) for a, b in segs
            if math.hypot(b[0] - a[0], b[1] - a[1]) > stall and
            any(views.seg_hits_box(a, b, r) for r in rows)]


def _closed_lane_edges(monkeypatch):
    """Make the site plan draw its polylines closed (PyMuPDF's default)."""
    from app.genset import views
    orig = views._Sheet.poly
    monkeypatch.setattr(views._Sheet, "poly", lambda self, pts, layer, **kw:
                        orig(self, pts, layer, **dict(kw, closePath=True)))


DT_SETS = [("E", 2000), ("E", 4500), ("E", 12000), ("W", 4000)]


@pytest.mark.parametrize("side,sf", DT_SETS)
def test_lane_edges_drawn_open_no_line_across_the_field(side, sf,
                                                        monkeypatch):
    from app.genset import views
    p = _west(sf)[0] if side == "W" else _rs(sf, drive_thru=True)
    assert p["drive_thru"].get("side", "E") == side
    lay, segs, _page = _draw_site_plan_recorded(p, monkeypatch)
    f = lay["features"]
    assert f["lane"] and f["rows"]
    edges = [it for it in lay["items"] if it["t"] == "poly"]
    assert len(edges) == 2 and all(it["layer"] == "lane" and
                                   it["kw"]["closePath"] is False
                                   for it in edges)
    # what the stand-in stroked: every lane edge segment, none closing it
    lane = [sheet_box(lay, b) for b in f["lane"]["boxes"]]
    for it in edges:
        pts = [tuple(q) for q in it["pts"]]
        for a, b in zip(pts, pts[1:]):
            assert (a, b) in segs
        assert (pts[-1], pts[0]) not in segs
    assert _long_lines_across_rows(lay, segs) == []
    assert views.field_crossings(lay) == []
    res = {c: v for v, c, _d in audit.audit(p)}
    assert res["No site plan line across the parking but the lane and "
               "crosswalks"] == "PASS"
    assert lane                                     # (the lane is drawn)


@pytest.mark.parametrize("side,sf", [("E", 4500), ("W", 4000)])
def test_self_check_fails_a_plan_drawn_with_a_closed_lane_edge(side, sf,
                                                               monkeypatch):
    from app.genset import views
    p = _west(sf)[0] if side == "W" else _rs(sf, drive_thru=True)
    _closed_lane_edges(monkeypatch)
    lay, segs, _page = _draw_site_plan_recorded(p, monkeypatch)
    # the stand-in sees the closing segments run across the parking ...
    assert len(_long_lines_across_rows(lay, segs)) >= 2
    # ... and so does the self-check
    cross = views.field_crossings(lay)
    assert len(cross) >= 2 and {c[0] for c in cross} == {"lane"}
    res = {c: (v, d) for v, c, d in audit.audit(p)}
    v, d = res["No site plan line across the parking but the lane and "
               "crosswalks"]
    assert v == "FAIL" and "lane" in d
    assert audit.summary(audit.audit(p)) == "FAIL"


def test_field_crossings_flags_a_stray_line_but_not_the_crosswalk():
    from app.genset import views
    p = _rs(4500, drive_thru=True)
    lay = views.site_layout(p)
    f = lay["features"]
    assert f["crosswalk"] and views.field_crossings(lay) == []
    r = sheet_box(lay, f["rows"][0])
    lay["items"].append({"t": "line", "a": (r[0] - 5, r[1] - 5),
                         "b": (r[2] + 5, r[3] + 5), "color": (0, 0, 0),
                         "width": 0.6, "dashes": None, "layer": "walk"})
    assert [c[0] for c in views.field_crossings(lay)] == ["walk"]
    got = {c: v for v, c, _d in audit.site_checks(p, lay=lay)}
    assert got["No site plan line across the parking but the lane and "
               "crosswalks"] == "FAIL"


def test_drive_thru_field_draws_only_the_rows_on_the_lot():
    """The strip center's 'only what fits' rule (review of 0.12.38 #8) is
    the same features() code: a widened restaurant field with a deep
    front yard keeps the rows on the lot - one double-loaded row here -
    and the lane still comes in and goes out through its aisle."""
    from test_genset_strip import _stalls_on_the_lot
    from app.genset import site as site_mod, views
    # 190 ft deep: the 132 ft field, the building and its 20 ft rear
    # setback take 198.5 - too shallow even with the building moved back
    # (Oct 22), so it stays on the front setback
    p = _rs(3000, drive_thru=True, seats=40,
            lot={"w": 150, "d": 190, "setbacks": {"front": 80}})
    assert p["parking"]["rows"] == 2 and p["parking"].get("segments")
    assert p["site"]["provided"]["front"] == 80.0
    assert "set_back_for_parking" not in p["site"]
    lay = views.site_layout(p)
    f = lay["features"]
    fit = f["parking_fit"]
    assert not fit["fits"] and 0 < fit["drawn"] < fit["required"] == 30
    assert fit["short"] == 30 - fit["drawn"]
    assert len(f["aisles"]) == 1
    assert all(r[1] >= f["lot"][1] - 1e-6 for r in f["rows"])
    _stalls_on_the_lot(lay)
    _field_clear_of_lane_and_walks(f)
    path = f["lane"]["path"]
    assert site_mod.inside((*path[0], *path[0]), f["aisles"][-1])
    assert site_mod.inside((*path[-1], *path[-1]), f["aisles"][0])
    assert views.field_crossings(lay) == []
    assert site_problems(p) == [] and lay["clashes"] == []


# ---- no stray closing lines on any sheet (Oct 22) -------------------------
# Shape.finish() closes the path unless told closePath=False: the section's
# roof line got a line eave to eave, the stair profile a diagonal back down,
# the dashed 'ridge beyond' its fourth side, every door swing a chord.
class _ClosingShape(_PathShape):
    """_PathShape that also notes each closing finish() adds: (from, to,
    already drawn) on page.closings."""

    def finish(self, closePath=True, color=(0, 0, 0), **kw):
        if closePath and color is not None and self.start is not None \
                and self.last is not None and self.last != self.start:
            seg = (self.last, self.start)
            self.page.closings.append(
                (seg[0], seg[1], seg in self.segs or seg[::-1] in self.segs))
        if closePath and self.start is not None and self.last == self.start:
            self.page.closed += 1                 # a closed outline, kept
        super().finish(closePath=closePath, color=color, **kw)


class _OutlineModel:
    """Stands in for Modulor: the walls as boxes, each face a plain wall."""

    def __init__(self, plan):
        self.plan = plan

    def plan_outline(self):
        out = []
        for w in self.plan["walls"]:
            (ax, ay), (bx, by) = w["a"], w["b"]
            t = w["thickness"] / 2
            x0, x1 = sorted((ax, bx))
            y0, y1 = sorted((ay, by))
            out.append([(x0 - t, y0 - t), (x1 + t, y0 - t), (x1 + t, y1 + t),
                        (x0 - t, y1 + t)])
        return out

    def elevation(self, face):
        fp = self.plan["footprint"]
        span = fp["width"] if face in ("S", "N") else fp["depth"]
        h = self.plan["level"]["plate_height"]
        return [[(0, 0), (span, 0), (span, h), (0, h)]]


def _draw_set_on_path_stand_in(plan, monkeypatch, shape=None):
    """Every sheet of the set (title block included) drawn as build_set
    draws it, on the path-semantics stand-in: {sheet no: page}."""
    import sys
    import types as _types
    from test_genset_strip import _RecPage, _record_with_stand_in
    from app.genset import draw, notes, sheets, site as site_mod, \
        titleblock, views
    _record_with_stand_in(monkeypatch)
    monkeypatch.setitem(sys.modules, "fitz", draw.fitz)   # build's import
    for mod in (views, titleblock):
        monkeypatch.setattr(mod, "fitz", draw.fitz)
    monkeypatch.setattr(views, "DRAW", draw.DRAW)
    monkeypatch.setattr(views, "_register_scale", lambda *a, **k: None)
    shape = shape or _ClosingShape
    plan = model.clone(plan)
    plan["project"]["date"] = "2026-10-22"
    plan["audit"] = [list(r) for r in audit.audit(plan)]
    plan["notes"]["project"] = notes.template_project_notes(plan)
    plan["notes"]["from_ai"] = False
    plan["notes"]["general"] = list(notes.GENERAL)
    if not plan.get("site"):
        plan["site"], _w = site_mod.site_for(plan)
    specs = sheets.specs_for(plan)
    pages = {}

    def new_page(width=0, height=0):
        page = _RecPage()
        page.number = len(pages)
        page.segs, page.closings, page.closed = [], [], 0
        page.new_shape = lambda: shape(page)
        return page

    doc = _types.SimpleNamespace(new_page=new_page)
    for sp in specs:
        pages[sp.no] = titleblock.start_sheet(doc, plan, sp.no, sp.title,
                                              "NTS" if sp.nts else " ")
    ctx = {"doc": None, "plan": plan, "scales": {}, "pages": {},
           "sheets": [(sp.no, sp.title) for sp in specs],
           "models": [_OutlineModel(lp) for lp in model.levels(plan)],
           "Model": _OutlineModel}
    for sp in specs:
        if not sp.nts:
            ctx["scales"][sp.no], _ = sp.draw(ctx, pages[sp.no])
    for sp in specs:
        if sp.nts:
            ctx["scales"][sp.no] = "NTS"
    for sp in specs:
        if sp.nts:
            sp.draw(ctx, pages[sp.no])
    return pages


def _golden(name):
    import os
    d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data",
                     "genset_golden")
    with open(os.path.join(d, name + ".json"), encoding="utf-8") as f:
        return json.load(f)


ALL_SETS = {
    "house_1story": lambda: _golden("house_1story"),
    "house_2story": lambda: _golden("house_2story"),
    "house_2story_narrow": lambda: _golden("house_2story_narrow"),
    "house_garage": lambda: _golden("house_garage"),
    "house_porch_deck": lambda: _golden("house_porch"),
    "office": lambda: _golden("office"),
    "retail": lambda: _golden("retail"),
    "retail_existing": lambda: _golden("retail_existing"),
    "restaurant": lambda: _rs(2000),
    "restaurant_drive_thru": lambda: _rs(4000, drive_thru=True),
    "strip": lambda: layout.make_plan({"building_type": "strip_retail",
                                       "gross_sf": 9000}),
    "warehouse_tilt_up": lambda: layout.make_plan(
        {"building_type": "warehouse", "gross_sf": 20000}),
    "warehouse_pemb": lambda: layout.make_plan(
        {"building_type": "warehouse", "gross_sf": 20000,
         "construction": "pemb"}),
}


@pytest.mark.parametrize("name", sorted(ALL_SETS))
def test_no_sheet_strokes_a_closing_line_it_did_not_draw(name, monkeypatch):
    plan = ALL_SETS[name]()
    if name == "house_porch_deck":
        assert plan.get("porch") and plan.get("deck")
    if name == "house_2story_narrow":                 # the dashed U
        from app.genset import kernel_section
        assert kernel_section.section_geometry(plan).get("ridge_beyond")
    if name == "warehouse_pemb":
        assert plan["roof"]["type"] == "gable"
    pages = _draw_set_on_path_stand_in(plan, monkeypatch)
    # a line that was never drawn: the roof's eave to eave, a door's chord
    stray = {no: [c[:2] for c in pg.closings if not c[2]][:3]
             for no, pg in pages.items() if any(not c[2] for c in pg.closings)}
    assert stray == {}, (name, stray)
    # nor a drawn line stroked back over itself (a dashed one's gaps fill)
    back = {no: [c[:2] for c in pg.closings][:3]
            for no, pg in pages.items() if pg.closings}
    assert back == {}, (name, back)
    # the closed shapes (wall poche, marks, the north arrow) stay closed
    assert sum(pg.closed for pg in pages.values()) > 0
    assert all(pg.segs for pg in pages.values())


def test_closing_line_check_sees_a_finish_that_closes(monkeypatch):
    """The check above, with every finish() closing (the old default): the
    section's roof, stair and ridge, and the plans' door swings, show."""
    class _AlwaysCloses(_ClosingShape):
        def finish(self, closePath=True, **kw):
            super().finish(closePath=True, **kw)

    pages = _draw_set_on_path_stand_in(_golden("house_2story_narrow"),
                                       monkeypatch, shape=_AlwaysCloses)
    from app.genset import sheets
    nos = {sp.no: sp for sp in sheets.specs_for(_golden(
        "house_2story_narrow"))}
    sec = [no for no, sp in nos.items()
           if getattr(sp.draw, "__name__", "") == "section"]
    assert sec and any(not dup for _a, _b, dup in pages[sec[0]].closings)
    plans = [no for no, pg in pages.items() if no.startswith("A-1") and
             any(not dup for _a, _b, dup in pg.closings)]
    assert plans                                  # the door swing chords
