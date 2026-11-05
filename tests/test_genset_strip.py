"""Generate Set Phase 2: strip retail (multi-tenant M), 4,000 - 60,000 SF
- its plan rules (pure Python) and its set (needs PyMuPDF and Modulor;
skipped without them)."""
import json

import pytest

from app.genset import audit, brief, build, layout, model, types
from app.genset.types import strip as st


def _st(sf=None, **kw):
    f = {"building_type": "strip_retail"}
    if sf:
        f["gross_sf"] = sf
    f.update(kw)
    return layout.make_plan(f)


SWEEP = [(sf, n, caps) for sf in (4000, 9000, 20000, 40000, 60000)
         for n in (None, 3, 8) for caps in (0, 1, 2)]


@pytest.mark.parametrize("sf,n,caps", SWEEP)
def test_sweep_validates_checks_clean_and_reaches_every_room(sf, n, caps):
    p = _st(sf, tenants=n, end_caps=caps)
    model.validate(p)
    fails = [r for r in audit.audit(p) if r[0] == "FAIL"]
    assert not fails, (sf, n, caps, fails)
    assert set(layout.reachable(p)) == {r["id"] for r in p["rooms"]}
    gross = (p["footprint"]["width"] + 0.5) * (p["footprint"]["depth"] + 0.5)
    assert abs(gross - sf) / sf <= 0.05
    assert p["project"]["occupancy"] == "M"
    rooms = p["rooms"]
    for i, a in enumerate(rooms):               # no overlaps, by hand too
        for b in rooms[i + 1:]:
            assert model._overlap(a["rect"], b["rect"]) < 0.01
    tn = p["strip"]["tenants"]
    assert len(tn) >= 2
    if n:
        assert len(tn) == n or any("don't fit" in w for w in p["warnings"])
    for t in tn:                                # four rooms each, its own
        kinds = sorted(r["type"] for r in rooms if r["tenant"] == t["id"])
        assert kinds == ["mech", "restroom", "sales", "storage"]


@pytest.mark.parametrize("sf,n,caps", SWEEP)
def test_each_tenant_has_a_storefront_and_a_rear_door(sf, n, caps):
    p = _st(sf, tenants=n, end_caps=caps)
    doors = st.tenant_doors(p)
    assert set(doors) == {t["id"] for t in p["strip"]["tenants"]}
    for k, d in doors.items():
        assert d["front"] == 1 and d["rear"] == 1 and d["exits"] == 2, k
    tn = {r["id"]: r["tenant"] for r in p["rooms"]}
    for o in p["openings"]:                    # never through a demising
        if o["kind"] == "door" and o.get("from_room") in tn:
            assert tn[o["from_room"]] == tn[o["to_room"]]
    walls = {w["id"]: w for w in p["walls"]}
    dem = [w for w in p["walls"] if w.get("demising")]
    assert len({w["a"][0] for w in dem if w["a"][0] == w["b"][0]}) == \
        len(p["strip"]["tenants"]) - 1
    assert all(w["thickness"] == st.DEMISING_T for w in dem)
    assert not [o for o in p["openings"] if walls[o["wall"]].get("demising")]
    res = {c: s for s, c, _d in audit.audit(p)}
    assert res["Each tenant has a storefront and a rear door"] == "PASS"
    assert res["No door through a demising wall"] == "PASS"
    assert res["Every tenant room reached from the tenant's own doors"] == \
        "PASS"


def test_tenant_areas_add_up_to_the_building():
    for p in (_st(18000, tenants=6, end_caps=2), _st(7500), _st(50000)):
        rows = st.tenant_rows(p)
        W, D = p["footprint"]["width"], p["footprint"]["depth"]
        assert abs(sum(r["gross"] for r in rows) - (W + 0.5) * (D + 0.5)) \
            < 1.0
        caps = [r for r in rows if r["end_cap"]]
        typical = [r for r in rows if not r["end_cap"]]
        for c in caps:
            assert c["width"] > 1.3 * max(t["width"] for t in typical)
        res = {c: s for s, c, _d in audit.audit(p)}
        assert res["Tenant bays add up to the building"] == "PASS"


def test_grid_is_on_the_exterior_and_demising_walls():
    p = _st(30000, tenants=10)
    g = p["grid"]
    W, D = p["footprint"]["width"], p["footprint"]["depth"]
    assert g["x"][0] == 0 and g["x"][-1] == W
    assert g["y"][0] == 0 and g["y"][-1] == D
    xs = {w["a"][0] for w in p["walls"] if w.get("demising") and
          w["a"][0] == w["b"][0]}
    assert xs <= set(g["x"])
    bx = [b - a for a, b in zip(g["x"], g["x"][1:])]
    assert max(bx) <= st.SPLIT_BAY + 1e-6
    assert g["assumed"]


def test_brief_fields_for_a_strip_center():
    text = ("New 6-tenant strip center, 18,000 sf, end caps at both ends, "
            "90 parking spaces")
    f = brief.parse(text, use_ai=False)
    assert f["building_type"] == "strip_retail" and f["occupancy"] == "M"
    assert (f["tenants"], f["end_caps"], f["parking"]) == (6, 2, 90)
    p = layout.make_plan(f)
    assert len(p["strip"]["tenants"]) == 6 and p["strip"]["end_caps"] == 2
    assert p["parking"]["spaces"] == 90 and not p["parking"]["assumed"]
    assert not any("parking spaces" in a for a in p["strip"]["assumed"])
    f = brief.parse("4 tenants of 1,500 sf, retail", use_ai=False)
    p = layout.make_plan(f)
    assert len(p["strip"]["tenants"]) == 4
    assert abs(p["project"]["gross_sf_target"] - 6000) < 1
    assert not any("not the brief's" in w for w in p["warnings"])


@pytest.mark.parametrize("text,n", [
    ("strip center 12,000 sf, 6 tenants", 6),
    ("retail strip 15,000 sf", None),
    ("new 8 tenant building 16,000 sf", 8),
    ("multi-tenant retail 10,000 sf", None),
    ("8 retail bays, 20,000 sf", 8),
    ("a 4-bay retail building 8,000 sf", 4),
    ("five tenant spaces, retail, 9,000 sf", 5),
    ("shopping center 40,000 sf", None),
    ("tilt-up strip center 20,000 sf, 8 tenants", 8),
    ("6-tenant strip center with a drive-thru end cap, 15,000 sf", 6),
])
def test_detect_claims_strip_briefs(text, n):
    hit = types.detect(text)
    assert hit and hit[0] == "strip_retail" and hit[1] == "M", text
    f = brief.regex_fields(text)
    assert f["building_type"] == "strip_retail"
    assert f.get("tenants") == n


@pytest.mark.parametrize("text,key", [
    ("multi-tenant office building 6,000 sf", "small_commercial"),
    ("office building with 4 tenants, 7,000 sf", "small_commercial"),
    ("4000 sf retail store, new", "small_commercial"),
    ("a shop 2000 sf", "small_commercial"),
    ("120 parking spaces, 100,000 sf warehouse", "warehouse"),
    ("tilt-up building 50,000 sf", "warehouse"),
])
def test_detect_leaves_offices_stores_and_warehouses_alone(text, key):
    f = brief.regex_fields(text)
    assert f["building_type"] == key, text


def test_defaults_are_marked_assumed():
    p = _st(24000)
    asm = " ".join(p["strip"]["assumed"])
    for word in ("tenant bays", "deep", "parking spaces", "per 1,000 SF",
                 "storefront", "demising", "parapet", "grid",
                 "sprinklered"):
        assert word in asm, word
    assert p["parking"]["assumed"] and p["grid"]["assumed"]
    from app.genset import codes, notes
    assert any(n.startswith("ASSUMED") for n in
               notes.template_project_notes(p))
    assert codes.assumed(p) == p["strip"]["assumed"]


def test_size_limits():
    with pytest.raises(model.PlanError, match="starts at 4,000"):
        _st(3000)
    with pytest.raises(model.PlanError, match="60,000"):
        _st(70000)
    with pytest.raises(model.PlanError, match="gross SF or the number"):
        _st()
    p = _st(20000, stories=2)
    assert any("one story" in w for w in p["warnings"])
    assert model.stories(p) == 1
    p = _st(4000, tenants=12)
    assert len(p["strip"]["tenants"]) < 12
    assert any("don't fit" in w for w in p["warnings"])


def test_exits_and_fixtures_come_from_the_code_tables():
    from app import codecheck
    from app.genset import codes
    p = _st(30000, tenants=8)
    c = p["code"]
    ex = c["exits"]
    assert ex["need"] == codecheck.exits_per_story(ex["load"])
    assert ex["have"] >= ex["need"]
    assert c["travel"]["limit"] == codecheck.travel_limit("M", True)
    loads = st._tenant_loads(p, c["rooms"])
    big = max(loads.values())
    lines = st.code_lines(p, c)
    fx = codecheck.fixtures(big, "M")
    assert f"{fx['wc']} WC" in lines[1][1]
    assert all(len(row) == 3 for row in lines)
    assert c["parking"]["spaces"] == p["parking"]["spaces"]
    assert c["parking"]["accessible"] == \
        codecheck.accessible_parking(p["parking"]["spaces"])
    assert codes.analyze(p, store=False)["parking"]["assumed"]


def test_parking_and_site():
    p = _st(20000)
    pk = p["parking"]
    assert pk["spaces"] == 80                    # 4 per 1,000 SF assumed
    s = p["site"]
    assert s["provided"]["front"] >= pk["depth"] - 1e-6
    res = {c: v for v, c, _d in audit.audit(p)}
    assert res["Parking field fits in front"] == "PASS"
    q = _st(20000, lot={"w": 400, "d": 150})    # no room for the field
    res = {c: v for v, c, _d in audit.audit(q)}
    assert res["Parking field fits in front"] == "WARN"


def test_enlarged_bay_is_the_typical_tenant_alone():
    p = _st(24000, tenants=8, end_caps=1)
    t = st.typical_tenant(p)
    assert not t["end_cap"] and t["x0"] > 0.3
    sub = st.bay_subplan(p)
    assert {r["tenant"] for r in sub["rooms"]} == {t["id"]}
    w_, d_ = sub["footprint"]["width"], sub["footprint"]["depth"]
    assert abs(w_ - (t["x1"] - t["x0"] - 0.5)) < 1e-6
    for r in sub["rooms"]:
        x0, y0, x1, y1 = r["rect"]
        assert -0.25 - 1e-6 <= x0 and x1 <= w_ + 0.25 + 1e-6
        assert -1e-6 <= y0 and y1 <= d_ + 1e-6
    for o in sub["openings"]:
        w = next(w for w in sub["walls"] if w["id"] == o["wall"])
        L = model.wall_length(w)
        assert 0.5 - 1e-6 <= o["along"] - o["width"] / 2
        assert o["along"] + o["width"] / 2 <= L - 0.5 + 1e-6
    ext = [o for o in sub["openings"] if o.get("from_room") == "EXT"]
    assert {o["wall"] for o in ext} == {"W1", "W3"}


def test_schedules_quantities_and_scoping():
    from app.genset import ada_plan, quantities, schedules
    p = _st(18000, tenants=6)
    rows = st.tenant_table_rows(p)
    assert len(rows) == 7 and rows[-1][0] == "TOTAL"
    assert len(schedules.room_rows(p)) == 24
    q = {r[1]: r for r in quantities.rows(p)}
    assert q["Storefront glazing"][2] > 0
    assert q["Demising walls (of the partitions)"][2] > 0
    assert q[f"Parking stalls ({p['parking']['spaces']})"][2] == \
        p["parking"]["spaces"]
    assert "Slab on grade (building)" in q
    proj = ada_plan.scoping(p)
    assert proj["use"] == "shopping_center"
    assert proj["tenant_spaces"] == 6
    assert proj["parking"][0]["total"] == p["parking"]["spaces"]


def test_sheet_list():
    p = _st(60000)
    nos = [n for n, _t in build.sheets_for(p)]
    six = [n for n, _t in build.sheets_for(_st(18000, tenants=6))]
    assert six[:7] == ["G-001", "G-002", "G-003", "AS-101", "A-101",
                       "A-102", "A-103"]
    assert six[-5:] == ["A-301", "A-601", "A-602", "A-701", "A-801"]
    # 34 tenants: the long schedules continue on the next sheets (see
    # test_long_schedules_continue_on_more_sheets)
    assert nos[:3] == ["G-001", "G-002", "G-003"] and "G-004" in nos
    assert "A-202" in nos                     # too long for a quad sheet
    small = [n for n, _t in build.sheets_for(_st(4000))]
    assert "A-201" in small
    assert json.loads(model.to_json(p))["schema"] == model.SCHEMA


# ---- the set (PyMuPDF + Modulor) -----------------------------------------
def _set_tools():
    fitz = pytest.importorskip("fitz")
    if not callable(getattr(fitz, "open", None)):
        pytest.skip("PyMuPDF not installed (a stand-in module)")
    pytest.importorskip("modulor")
    return fitz


@pytest.mark.parametrize("brief_text", [
    "6-tenant strip center, 18,000 sf, end caps, new",
    "strip center 40,000 sf, 16 tenants, new",
    "4 tenants of 1,200 sf, retail, new"])
def test_set_builds(brief_text, tmp_path):
    fitz = _set_tools()
    from app import genset_ui
    from test_genset_warehouse import _inside_draw
    out = str(tmp_path / "strip.pdf")
    res = genset_ui.generate({"brief": brief_text,
                              "form": {"name": "Test Strip"}}, out,
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
        assert "TENANT AREA SCHEDULE" in doc[labels.index("A-601")].get_text()
        assert "PARKING" in doc[labels.index("AS-101")].get_text()
        g003 = doc[labels.index("G-003")].get_text()
        assert "CODE SUMMARY" in g003 and "per tenant" in g003
    finally:
        doc.close()
    assert res["self_check"] in ("PASS", "WARN")
    assert side["project"]["building_type"] == "strip_retail"


# ---- AS-101 geometry: the layout as data, no PyMuPDF needed ---------------
@pytest.mark.parametrize("sf,n", [(4000, None), (9000, 3), (20000, None),
                                  (40000, 8), (60000, None)])
def test_site_plan_labels_clear_of_linework(sf, n):
    from test_genset_restaurant import field_checks, site_problems
    p = _st(sf, tenants=n) if n else _st(sf)
    assert site_problems(p) == []
    lay = field_checks(p)
    assert lay["features"]["lane"] is None


def test_site_plan_walk_is_on_the_door_side_of_the_field():
    from app.genset import site as site_mod
    p = _st(20000)
    f = site_mod.features(p)
    door = next(o for o in p["openings"] if o.get("from_room") == "EXT"
                and o["wall"] == "W1")
    w = f["walks"][0]["rect"]
    W = p["footprint"]["width"]
    assert (w[2] <= -0.25 + 1e-6) == (door["along"] <= W / 2)
    assert w[1] == p["site"]["lot_y0"]               # out to the street


def test_site_plan_unchanged_for_types_without_parking():
    from app.genset import site as site_mod
    q = build.plan_from_brief("3 bed 2 bath house 1600 sf", use_ai=False)
    assert "parking" not in q and site_mod.features(q) is None


# ---- a lot from the brief too small for the parking (Oct 21) --------------
def test_small_lot_parking_is_drawn_honestly_and_labels_stay_on_the_lot():
    from test_genset_restaurant import sheet_box, site_problems
    from app.genset import audit, site as site_mod, views
    p = _st(20000, lot={"w": 400, "d": 150})
    lay = views.site_layout(p)
    f = lay["features"]
    fit = f["parking_fit"]
    # only what fits on the lot is drawn (review of 0.12.38 #8): the
    # 20 ft front yard takes no row - nothing past the front lot line
    assert not fit["fits"] and fit["past_front"] == 0
    assert fit["required"] == p["parking"]["spaces"] == 80
    assert fit["drawn"] == fit["on_lot"] == 0 and fit["short"] == 80
    assert f["rows"] == [] and f["stalls"] == [] and f["hc"] == []
    # no label on a line or on another label, nothing left unplaced
    assert site_problems(p) == [] and lay["clashes"] == []
    # the drawing says so, on the lot in the front yard
    lot = sheet_box(lay, f["lot"])
    msg = [t for t in views.all_texts(lay)
           if t["s"].startswith("PARKING DOES NOT FIT THE LOT")]
    assert msg and "ZONING" in msg[0]["s"]
    assert site_mod.inside(views.text_box(msg[0]), lot)
    # the notes text, and the self-check
    assert site_mod.parking_fit_text(fit) == \
        "NO - 0 of 80 spaces fit on the lot; 80 short"
    res = {c: v for v, c, _d in audit.audit(p)}
    assert res["Parking field fits in front"] == "WARN"
    # a lot with room: none of it
    q = _st(20000)
    assert site_mod.features(q)["parking_fit"]["fits"]
    assert not any(t["s"].startswith("PARKING DOES NOT FIT")
                   for t in views.all_texts(views.site_layout(q)))


def _stalls_on_the_lot(lay):
    """Every parking row, stall line and HC mark of the layout inside the
    lot line (sheet points)."""
    from test_genset_restaurant import sheet_box
    from app.genset import site as site_mod, views
    f = lay["features"]
    lot = sheet_box(lay, f["lot"])
    lot = (lot[0] - 0.01, lot[1] - 0.01, lot[2] + 0.01, lot[3] + 0.01)
    for it in lay["items"]:
        if it["layer"] in ("row", "stall"):
            for a, b in views.item_segments(it):
                assert site_mod.inside((*a, *a), lot) and \
                    site_mod.inside((*b, *b), lot), (it["layer"], a, b)
    for st_ in f["stalls"]:
        (x0, y0), (x1, y1) = st_
        assert site_mod.inside((min(x0, x1), min(y0, y1), max(x0, x1),
                                max(y0, y1)), f["lot"]), st_
    for t in views.all_texts(lay):
        if t["s"] == "HC":
            assert site_mod.inside(views.text_box(t), lot)


@pytest.mark.parametrize("brief_text,drawn", [
    ("strip center 20000 sf on a 1 acre lot", 0),
    # a deep front yard: one row single-loaded, the rest short
    ("strip center 20000 sf on a 1 acre lot, front setback 80 ft", 30)])
def test_one_acre_strip_draws_only_the_stalls_on_the_lot(brief_text, drawn,
                                                         monkeypatch):
    from test_genset_restaurant import _draw_site_plan_recorded
    from app.genset import site as site_mod
    p = build.plan_from_brief(brief_text, use_ai=False)
    assert p["project"]["building_type"] == "strip_retail"
    assert p["site"]["lot_w"] * p["site"]["lot_d"] == \
        pytest.approx(43560, rel=0.01)
    lay, segs, page = _draw_site_plan_recorded(p, monkeypatch)
    f = lay["features"]
    fit = f["parking_fit"]
    need = p["parking"]["spaces"]
    assert not fit["fits"] and fit["drawn"] == fit["on_lot"] == drawn
    assert fit["short"] == need - drawn > 0 and fit["past_front"] == 0
    assert all(r[1] >= f["lot"][1] - 1e-6 for r in f["rows"])
    assert len(f["rows"]) == (1 if drawn else 0)
    _stalls_on_the_lot(lay)
    # the site data and the notes on the drawn sheet say the shortfall
    txt = " ".join(t[4] for t in page.texts)
    short = f"NO - {drawn} of {need} spaces fit on the lot; " \
        f"{need - drawn} short"
    assert "Parking fits the lot" in txt and short in txt
    assert "The parking does not fit the lot: " + short[5:] in txt
    assert "PARKING DOES NOT FIT THE LOT" in txt
    assert site_mod.parking_fit_text(fit) == short


def test_one_acre_strip_moves_the_building_back_for_the_field(monkeypatch):
    """Owner, Oct 22: a 12,000 SF strip center on a 1 acre lot - the field
    didn't fit in front of the building on the front setback (0 of 48
    drawn, a 123.5 ft rear yard left over); the building moves back just
    as far as the field needs (the walk, a row and a single-loaded row:
    114 ft), keeping its 25 ft rear setback."""
    from test_genset_restaurant import _draw_site_plan_recorded, \
        _street_label_clear, site_problems
    from app.genset import audit, site as site_mod
    from app.genset.types.parts import PARKING_ROW, WALK
    p = build.plan_from_brief("strip center 12000 sf on a 1 acre lot",
                              use_ai=False)
    assert p["project"]["building_type"] == "strip_retail"
    s = p["site"]
    D = p["footprint"]["depth"]
    assert s["lot_w"] * s["lot_d"] == pytest.approx(43560, rel=0.01)
    need = WALK + PARKING_ROW + site_mod.STALL_D + 24
    assert s["provided"]["front"] == pytest.approx(need) == 114.0
    assert s["set_back_for_parking"]
    assert s["provided"]["rear"] >= s["setbacks"]["rear"]
    assert s["provided"]["rear"] == pytest.approx(s["lot_d"] - 114 -
                                                  (D + 0.5))
    assert not s["binding"]
    lay, _segs, page = _draw_site_plan_recorded(p, monkeypatch)
    f = lay["features"]
    fit = f["parking_fit"]
    assert fit["fits"] and fit["drawn"] == p["parking"]["spaces"] == 48
    _stalls_on_the_lot(lay)
    _street_label_clear(lay)
    assert site_problems(p) == [] and lay["clashes"] == []
    res = {c: v for v, c, _d in audit.audit(p)}
    assert res["Parking field fits in front"] == "PASS"
    assert res["Building inside the setbacks"] == "PASS"
    assert "FAIL" not in res.values()
    txt = " ".join(t[4] for t in page.texts)
    assert "PARKING DOES NOT FIT THE LOT" not in txt
    assert "The building is set back 114'-0\" from the front lot line" in \
        txt


@pytest.mark.parametrize("lot", [{"w": 400, "d": 150}, None])
def test_lot_too_shallow_even_with_the_building_back_says_the_shortfall(
        lot, monkeypatch):
    """Where even the building at its rear setback leaves too little in
    front for the field (a 20,000 SF strip center on a 400 x 150 lot, or
    on 1 acre), the building stays on the front setback and the shortfall
    is said, as before."""
    from test_genset_restaurant import _draw_site_plan_recorded, \
        _street_label_clear, site_problems
    from app.genset import audit
    p = _st(20000, lot=lot) if lot else build.plan_from_brief(
        "strip center 20000 sf on a 1 acre lot", use_ai=False)
    s = p["site"]
    assert s["provided"]["front"] == s["setbacks"]["front"] == 20.0
    assert "set_back_for_parking" not in s
    lay, _segs, page = _draw_site_plan_recorded(p, monkeypatch)
    fit = lay["features"]["parking_fit"]
    assert not fit["fits"] and fit["short"] == 80 - fit["drawn"] > 0
    _street_label_clear(lay)
    assert site_problems(p) == [] and lay["clashes"] == []
    res = {c: v for v, c, _d in audit.audit(p)}
    assert res["Parking field fits in front"] == "WARN"
    txt = " ".join(t[4] for t in page.texts)
    assert "PARKING DOES NOT FIT THE LOT" in txt
    assert "The building is set back" not in txt


def test_small_lot_site_data_and_notes_say_the_parking_does_not_fit():
    fitz = pytest.importorskip("fitz")
    if not callable(getattr(fitz, "open", None)):
        pytest.skip("PyMuPDF not installed (a stand-in module)")
    from app.genset import draw, views
    p = _st(20000, lot={"w": 400, "d": 150})
    doc = fitz.open()
    try:
        page = doc.new_page(width=draw.SHEET_W, height=draw.SHEET_H)
        views.site_plan(doc, page, p)
        txt = " ".join(page.get_text().split())
        assert "Parking fits the lot" in txt
        assert "NO - 0 of 80 spaces fit on the lot; 80 short" in txt
        assert "The parking does not fit the lot" in txt
        assert "only the stalls that fit are drawn" in txt
        assert "zoning and the civil engineer" in txt
    finally:
        doc.close()


# ---- long schedules: more tenants than one sheet holds (Oct 21) -----------
class _RecPoint:
    def __init__(self, x=0, y=None):
        if y is None:
            x, y = x
        self.x, self.y = float(x), float(y)

    def __iter__(self):
        return iter((self.x, self.y))


class _RecRect:
    def __init__(self, *a):
        if len(a) == 1:
            a = tuple(a[0])
        if len(a) == 2:
            a = (a[0].x, a[0].y, a[1].x, a[1].y)
        self.x0, self.y0, self.x1, self.y1 = (float(v) for v in a)

    width = property(lambda s: s.x1 - s.x0)
    height = property(lambda s: s.y1 - s.y0)

    def __iter__(self):
        return iter((self.x0, self.y0, self.x1, self.y1))


class _RecFont:
    def __init__(self, name=None, fontfile=None):
        self.bold = name == "hebo"

    def text_length(self, s, fontsize=11):
        # a little wider than Helvetica's average, so a pass here holds
        # for the real font
        return (0.62 if self.bold else 0.58) * fontsize * len(s)


class _RecWriter:
    def __init__(self, rect):
        self.items = []

    def append(self, pos, s, font=None, fontsize=11):
        self.items.append((tuple(pos), s, fontsize, font))

    def write_text(self, page, color=None, morph=None):
        for (x, y), s, fs, f in self.items:
            page.texts.append((x, y - 0.75 * fs, x + f.text_length(s, fs),
                               y + 0.22 * fs, s))


class _RecShape:
    def __init__(self, page):
        self.page = page

    def _pts(self, *ps):
        for p in ps:
            if isinstance(p, _RecRect):
                self.page.pts += [(p.x0, p.y0), (p.x1, p.y1)]
            elif isinstance(p, _RecPoint):
                self.page.pts.append((p.x, p.y))

    def draw_rect(self, r):
        self._pts(r)

    def draw_line(self, a, b):
        self._pts(a, b)

    def draw_polyline(self, pts):
        self._pts(*pts)

    def draw_circle(self, c, r):
        self._pts(_RecPoint(c.x - r, c.y - r), _RecPoint(c.x + r, c.y + r))

    def draw_bezier(self, *pts):
        self._pts(*pts)

    def finish(self, **kw):
        pass

    def commit(self):
        pass


class _RecPage:
    """A sheet that records where every word and stroke lands."""
    number = 0

    def __init__(self):
        from app.genset import draw
        self.rect = _RecRect(0, 0, draw.SHEET_W, draw.SHEET_H)
        self.texts, self.pts = [], []

    def new_shape(self):
        return _RecShape(self)

    def insert_font(self, **kw):
        pass


def _record_with_stand_in(monkeypatch):
    """draw.py on the recording stand-in (no PyMuPDF needed); returns the
    drawing area (x0, y0, x1, y1) from the sheet constants."""
    import types as _types
    from app.genset import draw, sheets
    rec = _types.SimpleNamespace(Point=_RecPoint, Rect=_RecRect,
                                 Matrix=lambda *a: a, Font=_RecFont,
                                 TextWriter=_RecWriter)
    area = (72.0, sheets.DRAW_Y0, 72.0 + sheets.DRAW_W, sheets.DRAW_Y1)
    monkeypatch.setattr(draw, "fitz", rec)
    monkeypatch.setattr(draw, "DRAW", _RecRect(*area))
    monkeypatch.setattr(draw, "_FONTS", {})
    return area


def _outside(page, area):
    x0, y0, x1, y1 = area
    out = [(round(a), round(b)) for a, b in page.pts
           if not (x0 - 1 <= a <= x1 + 1 and y0 - 1 <= b <= y1 + 1)]
    out += [s for a, b, c, d, s in page.texts
            if a < x0 - 1 or b < y0 - 1 or c > x1 + 1 or d > y1 + 1]
    return out


@pytest.mark.parametrize("sf,n,caps", [(60000, 40, 0), (60000, 40, 2),
                                       (60000, None, 0), (40000, 30, 1),
                                       (30000, 40, 0), (9000, 10, 0),
                                       (4000, None, 0)])
def test_long_schedules_continue_on_more_sheets(sf, n, caps, monkeypatch):
    from app.genset import ada_plan, codes, schedules, sheets
    p = _st(sf, tenants=n, end_caps=caps)
    specs = sheets.specs_for(p)
    nos = [s.no for s in specs]
    assert len(set(nos)) == len(nos)
    for pre in ("G-0", "A-6", "A-8"):         # numbered in order, no gaps
        got = [int(x.rsplit("-", 1)[1]) for x in nos if x.startswith(pre)]
        assert got == list(range(got[0], got[0] + len(got))), nos
    # every row on exactly one sheet, in order
    rooms = schedules.room_rows(p)
    doors = schedules.door_rows(p)
    for parts_, total in (
            (codes.load_pages(p),
             len(codes.analyze(p, store=False)["rooms"]) + 1),
            (st.room_pages(p), len(rooms)), (schedules.door_pages(p),
                                             len(doors)),
            (ada_plan.scoping_pages(p), len(ada_plan._scoping_rows(p)))):
        assert parts_[0][0] == 0 and parts_[-1][1] == total
        assert all(a[1] == b[0] and a[0] < a[1]
                   for a, b in zip(parts_, parts_[1:]))
    if len(p["strip"]["tenants"]) <= 4:       # a small center: one each
        assert nos[-5:] == ["A-301", "A-601", "A-602", "A-701", "A-801"]
    # drawn on the recording stand-in: inside the drawing area, never cut
    # off, every room and door listed
    area = _record_with_stand_in(monkeypatch)
    seen = {"G": [], "A-6": []}
    for sp in specs:
        if not (sp.no.startswith(("G-003", "G-004", "G-005", "G-006",
                                  "A-6", "A-7", "A-8"))):
            continue
        page = _RecPage()
        sp.draw({"plan": p, "doc": None, "models": [], "scales": {},
                 "pages": {}}, page)
        assert not _outside(page, area), (sp.no, _outside(page, area)[:4])
        words = [t[4] for t in page.texts]
        assert not any("more rows than fit" in w for w in words), sp.no
        seen["G" if sp.no.startswith("G") else "A-6"] += words \
            if sp.no.startswith(("G", "A-6")) else []
    marks = [d[0] for d in doors]
    assert all(m in seen["A-6"] for m in marks)
    assert all(r[0] in seen["A-6"] for r in rooms)
    assert all(r[0] in seen["G"] for r in rooms)
    assert any(w.startswith("TOTAL  ") for w in seen["A-6"])


# ---- plumbing per tenant (Oct 21 review) ----------------------------------
def test_plumbing_one_unisex_restroom_per_mercantile_tenant():
    """IPC 2902.2 Exc. 3 (2015+): separate facilities aren't required in
    a mercantile space of 100 occupants or less - one single-user
    restroom per tenant passes, at 4,000 SF and for typical bays."""
    from app.genset import codes
    for p in (_st(4000), _st(4000, tenants=5, bay_d=40), _st(20000),
              _st(60000), _st(60000, tenants=40, end_caps=2)):
        loads = st._tenant_loads(p, codes.analyze(p, store=False)["rooms"])
        assert max(loads.values()) <= st.MERCANTILE_MAX == 100
        pl = st.plumbing(p)
        assert not pl["over"] and set(pl["need_wc"].values()) == {1}
        res = {c: (v, d) for v, c, d in audit.audit(p)}
        v, d = res["Plumbing fixtures per tenant (IPC 2902.1, M row)"]
        assert v == "PASS" and "IPC 2902.2 Exc. 3 (2015+)" in d
        assert "per sex" not in d


def test_plumbing_over_100_occupants_follows_the_table():
    from app import codecheck
    # two huge bays (the set warns they're wide): well over 100 each
    p = _st(60000, tenants=2)
    loads = st._tenant_loads(p)
    assert min(loads.values()) > st.MERCANTILE_MAX
    pl = st.plumbing(p)
    for k, ld in loads.items():
        assert pl["need_wc"][k] == codecheck.fixtures(ld, "M")["wc"]
    fx = codecheck.fixtures(max(loads.values()), "M")
    assert pl["over"] == sorted(loads) and pl["fx"] == fx
    assert f"asks {fx['wc']} WC ({fx['wc_each']} per sex" in pl["detail"]
    res = {c: v for v, c, _d in audit.audit(p)}
    assert res["Plumbing fixtures per tenant (IPC 2902.1, M row)"] == "WARN"
    # a tenant of another group would get Exc. 2 (15 or fewer) instead
    small = st.plumbing(p, loads={"T1": 16}, group="B")
    assert small["limit"] == st.SINGLE_USER_MAX == 15 and small["over"]
    assert "Exc. 2" in small["cite"]


# ---- the tenant bays in the sidecar (Oct 21 review) -----------------------
def test_tenant_bays_ride_along_with_the_rooms():
    p = _st(18000, tenants=6, end_caps=1)
    side = json.loads(model.to_json(p))
    bays = side["tenant_bays"]
    assert [b["id"] for b in bays] == [t["id"] for t in
                                      p["strip"]["tenants"]]
    W, D = p["footprint"]["width"], p["footprint"]["depth"]
    assert abs(sum(b["area_sf"] for b in bays) - (W + 0.5) * (D + 0.5)) < 1
    assert abs(sum(b["frontage_ft"] for b in bays) - (W + 0.5)) < 1e-6
    rows = {r["id"]: r for r in st.tenant_rows(p)}
    room_ids = {r["id"] for r in side["rooms"]}
    for b in bays:
        assert b["area_sf"] == rows[b["id"]]["gross"]
        assert b["frontage_ft"] == rows[b["id"]]["width"]
        assert set(b["rooms"]) <= room_ids
    assert bays[-1]["end_cap"] and not bays[0]["end_cap"]


def test_strip_field_uses_the_lot_width_review_10():
    """A strip center on a wide, shallow lot: the building-long field ran
    off the front; the lot's width makes it one row that fits."""
    from test_genset_restaurant import field_checks, site_problems
    from app.genset import site as site_mod
    p = _st(9000, lot={"w": 300, "d": 180})
    pk = p["parking"]
    assert pk["rows"] == 1 and pk["segments"]
    f = site_mod.features(p)
    assert f["parking_fit"]["fits"]
    assert f["parking_fit"]["drawn"] == pk["spaces"]
    field_checks(p)
    assert site_problems(p) == []
    env = f["envelope"]
    assert all(env[0] - 1e-6 <= r[0] and r[2] <= env[2] + 1e-6
               for r in f["rows"])
    # unchanged where the field already fit
    assert "segments" not in _st(9000)["parking"]
