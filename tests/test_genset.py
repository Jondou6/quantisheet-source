"""Generate Set v1: the plan rules (pure Python), the ten-sheet set (needs
Modulor), and the File menu / dialog wiring."""
import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest                                                  # noqa: E402

from app.genset import DISCLAIMER, brief, layout, model         # noqa: E402
from test_gui import win, qapp                                 # noqa: E402,F401

try:
    import modulor  # noqa: F401
    HAVE_MODULOR = True
except Exception:                                             # noqa: BLE001
    HAVE_MODULOR = False
# without Modulor the set tests FAIL, so a green suite always means the
# set was really built (Grok M11); set QUANTISHEET_ALLOW_NO_MODULOR=1 to skip
needs_modulor = pytest.mark.skipif(
    not HAVE_MODULOR and os.environ.get("QUANTISHEET_ALLOW_NO_MODULOR") == "1",
    reason="Modulor not installed (allowed by QUANTISHEET_ALLOW_NO_MODULOR)")


def _plan(text, **form):
    return layout.make_plan(brief.parse(text, form=form, use_ai=False))


@pytest.mark.parametrize("text", ["3 bed 2 bath ranch, about 1600 sf, new",
                                  "2,400 sf office, occupancy B, new",
                                  "4000 sf retail store, new"])
def test_plans_are_valid_and_every_room_is_reachable(text):
    p = _plan(text)
    model.validate(p)                           # raises on a broken plan
    assert set(layout.reachable(p)) == {r["id"] for r in p["rooms"]}
    assert p["disclaimer"] == DISCLAIMER
    assert p["source"]["kernel"] == "modulor"
    assert _plan(text) == p                     # deterministic


def test_brief_rules_and_form_wins():
    f = brief.regex_fields("New 3 bed 2.5 bath home, 1,850 sq ft")
    assert f["beds"] == 3 and f["baths"] == 3 and f["gross_sf"] == 1850
    assert f["building_type"] == "single_family"
    got = brief.parse("2400 sf office", form={"gross_sf": 3000.0},
                      use_ai=False)
    assert got["gross_sf"] == 3000.0 and got["occupancy"] == "B"


def test_ai_answer_is_clamped_and_never_places_geometry():
    raw = json.dumps({"gross_sf": 99999, "beds": 3, "walls": [1, 2],
                      "name": "Lake House"})
    f = brief.parse("a house", ask=lambda _p: raw)
    assert "walls" not in f and f.get("gross_sf") != 99999
    assert f["name"] == "Lake House" and f["ai_used"]


def test_ftin():
    assert model.fmt_ftin(9.5) == "9'-6\""
    assert model.fmt_ftin(12.0417) == "12'-0 1/2\""


@needs_modulor
def test_set_has_ten_marked_sheets_and_reads_back(tmp_path):
    import fitz
    from app import annotate, genset_ui
    out = str(tmp_path / "Smith_GenSet_v1.pdf")
    res = genset_ui.generate({"brief": "3 bed 2 bath house 1600 sf",
                              "form": {"name": "Smith Residence"}}, out,
                             use_ai=False)
    doc = fitz.open(out)
    assert doc.page_count == 10
    for i, pg in enumerate(doc):
        t = pg.get_text()
        assert DISCLAIMER in t, f"sheet {i + 1} has no disclaimer"
        assert "m2" not in t and "m²" not in t
    assert set(annotate.read_viewports(doc)) == {2, 3, 4, 5, 6}
    doc.close()
    side = json.load(open(res["sidecar"]))
    doors = sum(o["kind"] == "door" for o in side["openings"])
    back = genset_ui.check(out)
    assert back["doors"] == doors
    assert back["room_tags"] == len(side["rooms"])


def test_file_menu_has_generate_set(win):
    names = [a.text() for a in win.findChildren(type(win.menuBar()
                                                     .actions()[0]))]
    assert "Generate Set…" in names


def test_dialog_values_and_default_name(qapp):
    from app.genset_ui import GenerateSetDialog, default_name
    d = GenerateSetDialog()
    d.brief.setPlainText("3 bed house")
    d.name.setText("Lake / House")
    d.sf.setValue(1600)
    v = d.values()
    assert v["form"]["gross_sf"] == 1600.0
    assert v["form"]["firm"] == "[FIRM NAME]"
    assert default_name(v) == "Lake___House_GenSet_v1.pdf"
    assert DISCLAIMER in d.findChild(type(d.ai), "GenSetBanner").text()
    d.close()


# ---- Venice review of 0.12.14 -------------------------------------------
def test_8000_sf_commercial_fits_inside_120_by_80():          # M-3
    for text in ("8000 sf office, new", "8000 sf retail store, new"):
        p = _plan(text)
        fp = p["footprint"]
        assert fp["width"] <= 120 and fp["depth"] <= 80
        assert fp["width"] * fp["depth"] >= 7800


def test_rooms_that_only_touch_each_other_get_one_door_and_are_reached():
    p = _plan("400 sf 6 bed 4 bath house, new")              # M-1 / S-1
    model.validate(p)          # now also rejects overlapping openings
    assert set(layout.reachable(p)) == {r["id"] for r in p["rooms"]}
    doors = [(o["wall"], o["along"]) for o in p["openings"]]
    assert len(doors) == len(set(doors))


def test_no_sliver_rooms_and_every_room_has_a_door():         # M-2, N
    for sf in range(400, 8001, 400):
        for beds in (1, 3, 6, 8):
            p = layout.make_plan({"building_type": "single_family",
                                  "gross_sf": sf, "beds": beds, "baths": 4})
            ids = {r["id"] for r in p["rooms"]}
            assert set(layout.reachable(p)) == ids
            for r in p["rooms"]:
                x0, y0, x1, y1 = r["rect"]
                assert min(x1 - x0, y1 - y0) >= 3, (sf, beds, r["name"])
            if beds > 6:
                assert any("at most 6 bedrooms" in w for w in p["warnings"])


def test_validate_rejects_overlapping_openings():
    p = _plan("3 bed 2 bath house 1600 sf")
    o = dict(next(o for o in p["openings"] if o["kind"] == "window"))
    o["id"] = "X1"
    p["openings"].append(o)
    with pytest.raises(model.PlanError, match="overlap"):
        model.validate(p)


def test_sketch_names_go_to_the_room_of_that_kind():
    p = layout.make_plan({"building_type": "single_family", "gross_sf": 1600,
                          "room_names": ["Great Room", "Owner Suite Bedroom",
                                         "Garage"]})
    names = {r["type"]: r["name"] for r in p["rooms"]}
    assert names["living"] == "GREAT ROOM"
    assert "OWNER SUITE BEDROOM" in [r["name"] for r in p["rooms"]
                                     if r["type"] == "bed"]
    assert "GARAGE" not in [r["name"] for r in p["rooms"]]


@needs_modulor
def test_long_names_stay_inside_the_title_block(tmp_path):     # M-4, M-5
    import fitz
    from app import genset_ui
    from app.genset import draw
    long = "Lakeview Estates Single-Family Residence and Detached Studio X"
    out = str(tmp_path / "long.pdf")
    genset_ui.generate({"brief": "3 bed 2 bath house 1600 sf",
                        "form": {"name": long, "firm": long,
                                 "address": long + " Road"}}, out,
                       use_ai=False)
    doc = fitz.open(out)
    edge = draw.SHEET_W - draw.MARGIN
    for pg in doc:
        for x0, y0, x1, y1, word, *_ in pg.get_text("words"):
            assert x1 <= edge + 1, (pg.number, word, x1)
    doc.close()
    assert os.path.isfile(out[:-4] + ".genset.json")
    assert not os.path.exists(out[:-4] + ".genset.json.tmp")


# ---- Grok review of 0.12.14 -------------------------------------------
def test_dialog_leaves_type_to_the_brief(qapp):                    # S1
    from app.genset import build
    from app.genset_ui import GenerateSetDialog
    d = GenerateSetDialog()
    d.brief.setPlainText("3,000 sf retail store, remodel existing")
    v = d.values()
    plan = build.plan_from_brief(v["brief"], form=v["form"], use_ai=False)
    pj = plan["project"]
    assert (pj["building_type"], pj["occupancy"], pj["work"]) == \
        ("small_commercial", "M", "existing")
    d.kind.setCurrentIndex(1)                   # an explicit pick wins
    v = d.values()
    plan = build.plan_from_brief(v["brief"], form=v["form"], use_ai=False)
    assert plan["project"]["building_type"] == "single_family"
    assert plan["project"]["occupancy"] == "R-3"
    d.close()


def test_total_sf_and_room_sizes_from_the_brief():                  # S2
    text = ("new house: living 400 sf, kitchen 250 sf, 3 bedrooms at 200 "
            "sf each, 2 baths 80 sf each; total about 1,800 sf")
    p = _plan(text)
    assert p["project"]["gross_sf_target"] == 1800
    big = _plan("living 600 sf, kitchen 400 sf, 3 bedrooms at 300 sf each;"
                " total 1,800 sf house")
    assert any(w.startswith("Program total") for w in big["warnings"])
    living = next(r for r in p["rooms"] if r["type"] == "living")
    beds = [r for r in p["rooms"] if r["type"] == "bed"]
    assert living["area"] > 250 and all(b["area"] > 120 for b in beds)
    with pytest.raises(model.PlanError, match="more than"):
        _plan("living 900 sf, kitchen 600 sf; total 1,000 sf house")


def test_ai_may_not_choose_the_size():                               # M4
    f = brief.parse("3 bed house, new",
                    ask=lambda _p: '{"gross_sf": 2500}')
    with pytest.raises(model.PlanError, match="gross SF"):
        layout.make_plan(f)


def test_brief_edge_cases():                                         # N2
    assert brief.regex_fields("house -1600 sf").get("gross_sf") is None
    assert brief.regex_fields("1.5e3 sf office")["gross_sf"] == 1500
    assert brief.regex_fields("400 sf studio cottage")["occupancy"] == "R-3"
    with pytest.raises(model.PlanError, match="starts at 400"):
        _plan("300 sf cabin")
    with pytest.raises(model.PlanError, match="sketch gives the shape"):
        layout.make_plan({"building_type": "single_family"})


def _doors(p):
    by = {r["id"]: r["type"] for r in p["rooms"]}
    return [(by.get(o["from_room"], "ext"), by[o["to_room"]])
            for o in p["openings"] if o["kind"] == "door"]


@pytest.mark.parametrize("sf", [400, 900, 1600, 2600, 4000, 8000])
@pytest.mark.parametrize("beds,baths", [(1, 1), (3, 2), (6, 4)])
def test_bedrooms_open_off_a_hall_and_have_windows(sf, beds, baths):  # M1/M2
    p = layout.make_plan({"building_type": "single_family", "gross_sf": sf,
                          "beds": beds, "baths": baths})
    model.validate(p)
    for frm, to in _doors(p):
        assert frm not in ("bed", "bath", "laundry", "mech"), (frm, to)
        if to in ("bed", "bath"):
            assert frm in ("hall", "living"), (frm, to)
    for r in p["rooms"]:
        if r["type"] == "bed":
            assert any(o["kind"] == "window" and o.get("room") == r["id"]
                       for o in p["openings"]), r["name"]


@pytest.mark.parametrize("text", ["2,400 sf office, occupancy B, new",
                                  "4000 sf retail store, new",
                                  "8000 sf retail store, new"])
def test_commercial_back_rooms_open_off_a_hall(text):
    p = _plan(text)
    for frm, to in _doors(p):
        assert frm not in ("restroom", "storage", "mech", "office")


def test_sketch_names_drop_numbers_and_garages():                    # M5
    p = layout.make_plan({"building_type": "single_family", "gross_sf": 1800,
                          "room_names": ["GREAT ROOM 101", "OWNER SUITE 102",
                                         "GARAGE 103"]})
    names = [r["name"] for r in p["rooms"]]
    assert "GREAT ROOM" in names and "OWNER SUITE" in names
    assert not any(n.startswith("GARAGE") for n in names)
    # 0.12.19: a garage on the sketch is drawn beside the house
    assert p["garage"]["cars"] == 2


def test_notes_keep_words_only():                                    # N1
    from app.genset import notes
    assert notes._clean("Use 16 inches on center") == ""
    assert notes._clean("Stamp as SEALED by the engineer") == ""
    assert notes._clean("Slab on grade with vapor retarder") == \
        "Slab on grade with vapor retarder."


def test_cli_refusal_is_a_message_not_a_traceback(tmp_path, capsys):  # N7
    from app.genset.__main__ import main
    rc = main(["--brief", "9,500 sf office building, new", "--no-ai",
               "--firm", "Test Firm", str(tmp_path / "x.pdf")])
    assert rc == 2 and "8,000 SF" in capsys.readouterr().err


# ---- Venice review of 0.12.15 -------------------------------------------
@pytest.mark.parametrize("ratio", [None, 1.0, 1.3, 2.2, 3.0])
@pytest.mark.parametrize("sf", [400, 500, 624, 1200, 3000])
def test_any_shape_keeps_a_bedroom_bath_windows_and_no_gaps(sf, ratio):
    """Venice M1 (a square 400 SF house lost its bed and bath), M2 (a
    narrow bedroom got no window) and M3 (an empty row left a gap)."""
    p = layout.make_plan({"building_type": "single_family", "gross_sf": sf,
                          "beds": 1, "baths": 1, "ratio": ratio})
    model.validate(p)
    kinds = [r["type"] for r in p["rooms"]]
    assert "bed" in kinds and "bath" in kinds
    for r in p["rooms"]:
        if r["type"] == "bed":
            assert any(o["kind"] == "window" and o.get("room") == r["id"]
                       for o in p["openings"])
    W, D = p["footprint"]["width"], p["footprint"]["depth"]
    assert sum(r["area"] for r in p["rooms"]) == pytest.approx(
        (W - 0.5) * (D - 0.5), abs=2)


# ---- the set checks itself ------------------------------------------------
def test_self_check_passes_good_plans_and_catches_broken_ones():
    from app.genset import audit
    p = _plan("3 bed 2 bath ranch, about 1600 sf, new")
    res = audit.audit(p)
    assert audit.summary(res) in ("PASS", "WARN")
    assert not [r for r in res if r[0] == "FAIL"]
    broken = model.clone(p)
    broken["rooms"].pop()                       # a gap in the floor
    d = next(o for o in broken["openings"] if o["kind"] == "door"
             and o["from_room"] != "EXT")
    broken["openings"].append(dict(d, id="DX", mark="999"))   # on top
    bad = {c for s, c, _d in audit.audit(broken) if s == "FAIL"}
    assert "Floor fully covered by rooms" in bad
    assert "Doors and windows fit their walls, none overlap" in bad


@needs_modulor
def test_self_check_is_on_the_cover(tmp_path):
    import fitz
    from app import genset_ui
    out = str(tmp_path / "s.pdf")
    res = genset_ui.generate({"brief": "3 bed 2 bath house 1600 sf"}, out,
                             use_ai=False)
    assert res["self_check"] in ("PASS", "WARN")
    t = fitz.open(out)[0].get_text()
    assert "SELF-CHECK:" in t and "Every room reached" in t
    side = json.load(open(res["sidecar"]))
    assert side["audit"] and side["audit"][0][0] in ("PASS", "WARN", "FAIL")


@needs_modulor
def test_the_plan_is_saved_for_cad_too(tmp_path):
    """Venice, Oct 19: a DXF of the floor plan beside the set."""
    import ezdxf
    from app import genset_ui
    out = str(tmp_path / "cad.pdf")
    res = genset_ui.generate({"brief": "3 bed 2 bath house 1600 sf",
                              "dxf": True}, out, use_ai=False)
    assert res["dxf"] and os.path.isfile(res["dxf"])
    doc = ezdxf.readfile(res["dxf"])
    assert doc.header["$INSUNITS"] == 2                  # feet
    msp = doc.modelspace()
    side = json.load(open(res["sidecar"]))
    doors = sum(o["kind"] == "door" for o in side["openings"])
    assert len(msp.query('ARC[layer=="A-DOOR"]')) == doors
    assert len(msp.query('LWPOLYLINE[layer=="A-WALL"]')) >= 1
    names = {e.dxf.text for e in msp.query('TEXT[layer=="A-AREA-IDEN"]')}
    assert {r["name"] for r in side["rooms"]} <= names
    assert not any("m2" in t or "m²" in t for t in names)


# ---- 0.12.17: site plan (lot, setbacks) and roof plan -------------------
def test_lot_and_setbacks_from_the_brief():
    from app.genset import site
    lot, rest = site.read_lot("1600 sf house, 75' x 150' lot, setbacks 25 "
                              "front, 8 side, 20 rear")
    assert (lot["w"], lot["d"]) == (75, 150)
    assert lot["setbacks"] == {"front": 25, "side": 8, "rear": 20}
    assert "1600 sf" in rest and "150" not in rest
    assert site.read_lot("0.25 acre lot")[0]["area"] == 10890
    assert site.read_lot("1/2 acre site")[0]["area"] == 21780
    # "back 2 bedrooms" is not a setback, and the bedrooms stay in the text
    lot, rest = site.read_lot("3 bed house, back 2 bedrooms, 1600 sf")
    assert lot is None and "2 bedrooms" in rest


def test_a_lot_size_is_never_the_building_size():
    f = brief.regex_fields("2,400 sf office on a 10,000 sf lot")
    assert f["gross_sf"] == 2400 and f["lot"]["area"] == 10000
    f = brief.regex_fields("new office on a 12,000 sf lot")
    assert "gross_sf" not in f


def test_site_fits_and_says_what_is_assumed():
    p = _plan("3 bed 2 bath house 1600 sf, lot 80 x 120")
    s = p["site"]
    assert (s["lot_w"], s["lot_d"]) == (80, 120)
    assert s["on_lot"] and not s["binding"]
    assert s["assumed"] == ["front", "rear", "side"]
    assert any("Setbacks assumed" in w for w in p["warnings"])
    # the building's face sits on the front setback, centred side to side
    assert abs(s["provided"]["front"] - 25) < 1e-6
    W = p["footprint"]["width"] + 0.5
    assert abs(s["provided"]["side"] - (80 - W) / 2) < 1e-6
    from app.genset import audit
    res = {c: st for st, c, _d in audit.audit(p)}
    assert res["Building inside the setbacks"] == "PASS"


def test_site_too_small_warns_and_fails():
    from app.genset import audit
    p = _plan("3,000 sf house, lot 80 x 100, setbacks front 25 side 10 "
              "rear 25")
    assert p["site"]["binding"]
    assert any("doesn't fit inside" in w for w in p["warnings"])
    res = {c: st for st, c, _d in audit.audit(p)}
    assert res["Building inside the setbacks"] == "WARN"
    p = _plan("3,000 sf house, lot 30 x 40")
    res = {c: st for st, c, _d in audit.audit(p)}
    assert res["Building fits on the lot"] == "FAIL"


def test_no_lot_given_draws_one_just_big_enough():
    p = _plan("1600 sf ranch house")
    s = p["site"]
    assert s["lot_from"] == "assumed" and s["on_lot"] and not s["binding"]
    assert s["lot_w"] % 5 == 0 and s["lot_d"] % 5 == 0


@needs_modulor
def test_site_and_roof_sheets(tmp_path):
    import fitz
    from app import annotate, genset_ui
    for text, roof_word in (("3 bed 2 bath house 1600 sf, lot 80 x 120",
                             "RIDGE"),
                            ("2,400 sf office, occupancy B, new", "RD")):
        out = str(tmp_path / "s.pdf")
        genset_ui.generate({"brief": text}, out, use_ai=False)
        doc = fitz.open(out)
        labels = [pg.get_label() for pg in doc]
        # office and retail sets have G-003 Code Summary too (Oct 20)
        assert [x for x in labels if x != "G-003"][:5] == \
            ["G-001", "G-002", "AS-101", "A-101", "A-102"]
        si, ri = labels.index("AS-101"), labels.index("A-102")
        site_t = doc[si].get_text()
        assert "PROPERTY LINE" in site_t and "SITE DATA" in site_t
        assert "SETBACK" in site_t
        roof_t = doc[ri].get_text()
        assert roof_word in roof_t and "ROOF PLAN" in roof_t
        vps = annotate.read_viewports(doc)
        assert vps[si][0]["name"] == "Site Plan"
        assert vps[ri][0]["name"] == "Roof Plan"
        assert "Lot" in doc[0].get_text()
        doc.close()


@needs_modulor
def test_dxf_has_the_property_line(tmp_path):
    import ezdxf
    from app import genset_ui
    out = str(tmp_path / "d.pdf")
    genset_ui.generate({"brief": "3 bed house 1600 sf, lot 80 x 120",
                        "dxf": True}, out, use_ai=False)
    dx = ezdxf.readfile(out[:-4] + ".dxf")
    props = [e for e in dx.modelspace() if e.dxf.layer == "C-PROP"]
    assert len(props) == 1
    xs = [p[0] for p in props[0].get_points()]
    assert abs(max(xs) - min(xs) - 80) < 1e-6


def test_bedroom_doors_open_onto_the_hall():
    """GENSET_NOTES 'later' item: never off the laundry or another
    service room (fixed by the hall layout; this keeps it fixed)."""
    for sf in range(600, 8001, 700):
        for beds in (1, 3, 6):
            for ratio in (None, 1.0, 2.2):
                p = layout.make_plan({"building_type": "single_family",
                                      "gross_sf": sf, "beds": beds,
                                      "baths": 2, "ratio": ratio})
                by = {r["id"]: r for r in p["rooms"]}
                for o in p["openings"]:
                    a, b = by.get(o.get("from_room")), by.get(
                        o.get("to_room"))
                    if o["kind"] == "door" and a and b and "bed" in (
                            a["type"], b["type"]):
                        other = b if a["type"] == "bed" else a
                        assert other["type"] == "hall", (sf, beds, ratio)


# ---- 0.12.17: two-story houses (center stair hall) ------------------------
def _two(sf=2400, beds=4, baths=3, ratio=None):
    return layout.make_plan({"building_type": "single_family",
                             "gross_sf": sf, "beds": beds, "baths": baths,
                             "stories": 2, "ratio": ratio})


def test_brief_reads_stories():
    assert brief.regex_fields("two story 2400 sf house")["stories"] == 2
    assert brief.regex_fields("2-story colonial, 2,800 sf")["stories"] == 2
    assert brief.regex_fields("one story ranch 1600 sf")["stories"] == 1
    f = brief.regex_fields("3 story 3000 sf house")
    assert f["stories"] == 2 and any("two stories" in w
                                     for w in f["warnings"])
    assert "stories" not in brief.regex_fields("3 bed 2 bath 1600 sf")


def test_two_story_house_plan():
    from app.genset import audit, twostory
    p = _two()
    model.validate(p)
    l1, l2 = model.levels(p)
    assert model.stories(p) == 2 and l2["level"]["floor_elev"] == 10.0
    # the stair is in the same place on both floors
    s1, s2 = l1["rooms"][0]["stair"], l2["rooms"][0]["stair"]
    assert s1["rect"] == s2["rect"] and (s1["label"], s2["label"]) == \
        ("UP", "DN")
    assert s1["risers"] == 16 and abs(s1["rise_in"] - 7.5) < 1e-6
    assert twostory.stair_numbers()[2] == 12.5
    # level 1: living rooms and the front door; level 2: the bedrooms
    assert {r["type"] for r in l1["rooms"]} >= {"living", "kitchen", "stair"}
    assert sum(r["type"] == "bed" for r in l2["rooms"]) == 4
    assert all(r["number"].startswith("2") for r in l2["rooms"])
    assert any(o.get("from_room") == "EXT" for o in l1["openings"])
    assert not any(o.get("from_room") == "EXT" for o in l2["openings"])
    # the primary bath opens off the primary bedroom (an en-suite)
    by = {r["id"]: r["name"] for r in l2["rooms"]}
    assert any(by.get(o.get("from_room")) == "PRIMARY BEDROOM" and
               by.get(o.get("to_room")) == "PRIMARY BATH"
               for o in l2["openings"])
    res = {c: st for st, c, _d in audit.audit(p)}
    assert "FAIL" not in res.values(), [r for r in audit.audit(p)
                                         if r[0] == "FAIL"]
    assert res["Every room reached from an outside door"] == "PASS"


def test_two_story_no_door_into_the_side_of_the_stair():
    from app.genset import model as m_
    for sf in (1800, 2400, 3200, 4400, 6000):
        p = _two(sf)
        for lp in m_.levels(p):
            sx0, sy0, sx1, sy1 = lp["rooms"][0]["stair"]["rect"]
            walls = {w["id"]: w for w in lp["walls"]}
            for o in lp["openings"]:
                w = walls[o["wall"]]
                (ax, ay), (bx, by_) = w["a"], w["b"]
                if o["kind"] != "door" or abs(ax - bx) > 1e-6:
                    continue
                if not sx0 - 1e-6 <= ax <= sx1 + 1e-6:
                    continue
                lo = ay + o["along"] - o["width"] / 2
                hi = ay + o["along"] + o["width"] / 2
                assert hi <= sy0 + 1e-6 or lo >= sy1 - 1e-6, (sf, o)


def test_two_story_sweep_never_fails_its_self_check():
    from app.genset import audit
    n = 0
    for sf in range(1600, 8001, 700):
        for beds, baths in ((2, 1), (3, 2), (4, 3), (5, 4)):
            for ratio in (None, 1.0, 2.2):
                p = _two(sf, beds, baths, ratio)
                n += 1
                bad = [r for r in audit.audit(p) if r[0] == "FAIL"]
                assert not bad, (sf, beds, baths, ratio, bad)
    assert n == 120


def test_two_story_limits():
    with pytest.raises(model.PlanError, match="start at 1,200"):
        _two(1000)
    p = layout.make_plan({"building_type": "small_commercial",
                          "occupancy": "B", "gross_sf": 4000,
                          "stories": 2})
    assert "upper" not in p
    assert any("Two-story office" in w for w in p["warnings"])


@needs_modulor
def test_two_story_set(tmp_path):
    import fitz
    import ezdxf
    from app import annotate, genset_ui
    out = str(tmp_path / "two.pdf")
    res = genset_ui.generate({"brief": "two story 2400 sf house, 4 bed 3 "
                                       "bath, new", "dxf": True}, out,
                             use_ai=False)
    assert res["pages"] == 11
    doc = fitz.open(out)
    labels = [pg.get_label() for pg in doc]
    assert labels[2:6] == ["AS-101", "A-101", "A-102", "A-103"]
    assert "UP 16R" in doc[3].get_text() and "DN 16R" in doc[4].get_text()
    assert "LEVEL 2 FLOOR PLAN" in doc[4].get_text()
    assert "ROOF PLAN" in doc[5].get_text()
    assert "LEVEL 2" in doc[6].get_text()          # elevations
    assert "PLATE L2" in doc[7].get_text()         # section
    sched = doc[8].get_text()
    assert "PRIMARY BEDROOM" in sched and "201" in sched
    vps = annotate.read_viewports(doc)
    assert {2, 3, 4, 5, 6, 7} <= set(vps)
    assert "Stories" in doc[0].get_text()
    doc.close()
    assert genset_ui.check(out)["room_tags"] > 0
    dx = ezdxf.readfile(res["dxf"])
    texts = {e.dxf.text for e in dx.modelspace().query("TEXT")}
    assert {"LEVEL 1", "LEVEL 2", "PRIMARY BEDROOM"} <= texts


# ---- 0.12.19: attached garage --------------------------------------------
def test_brief_reads_the_garage():
    from app.genset import garage
    assert garage.read("3 bed house with a 2-car garage") == 2
    assert garage.read("three car garage, 2400 sf") == 3
    assert garage.read("single-car garage") == 1
    assert garage.read("1600 sf house, attached garage") == 2
    assert garage.read("1600 sf house, no garage") is None
    assert brief.regex_fields("1600 sf house, garage")["garage"] == 2


def test_garage_on_the_plan():
    from app.genset import audit, site
    for stories in (1, 2):
        p = layout.make_plan({"building_type": "single_family",
                              "gross_sf": 2400, "beds": 3, "baths": 2,
                              "stories": stories, "garage": 2})
        g = p["garage"]
        assert g["cars"] == 2 and g["width"] == 22.0
        door = next(o for o in p["openings"] if o.get("from_room") == "GAR")
        into = next(r for r in p["rooms"] if r["id"] == door["to_room"])
        assert into["type"] not in ("bed", "bath") and door["type"] == "C"
        # no house window looks into the garage
        wall = "W2" if g["side"] == "E" else "W4"
        D = p["footprint"]["depth"]
        for o in p["openings"]:
            if o["kind"] == "window" and o["wall"] == wall:
                y = o["along"] if wall == "W2" else D - o["along"]
                assert y > g["depth"], o
        res = {c: st for st, c, _d in audit.audit(p)}
        assert "FAIL" not in res.values()
        assert res["Garage door opens into the house (not a bedroom or "
                   "bath)"] == "PASS"
        # the site counts the garage
        assert p["site"]["coverage"] * p["site"]["lot_w"] * \
            p["site"]["lot_d"] > site._covered(dict(p, garage=None)) - 1
    p = layout.make_plan({"building_type": "small_commercial",
                          "occupancy": "B", "gross_sf": 2400, "garage": 2})
    assert "garage" not in p
    assert any("houses only" in w for w in p["warnings"])


def test_garage_sweep_never_fails():
    from app.genset import audit
    for stories in (1, 2):
        for sf in (1400, 2000, 3200, 5000):
            for cars in (1, 2, 3):
                for ratio in (None, 2.2):
                    p = layout.make_plan({
                        "building_type": "single_family", "gross_sf": sf,
                        "beds": 3, "baths": 2, "stories": stories,
                        "ratio": ratio, "garage": cars})
                    assert p.get("garage"), (stories, sf, cars, ratio)
                    bad = [r for r in audit.audit(p) if r[0] == "FAIL"]
                    assert not bad, (stories, sf, cars, ratio, bad)


@needs_modulor
def test_garage_set(tmp_path):
    import fitz
    import ezdxf
    from app import genset_ui
    out = str(tmp_path / "gar.pdf")
    res = genset_ui.generate({"brief": "3 bed 2 bath house 1800 sf with a "
                                       "2-car garage, lot 90 x 120",
                              "dxf": True}, out, use_ai=False)
    doc = fitz.open(out)
    text = {pg.get_label(): pg.get_text() for pg in doc}
    assert "GARAGE (2-CAR)" in text["A-101"]
    assert "GARAGE ROOF" in text["A-102"]
    assert "DRIVE" in text["AS-101"] and "GARAGE" in text["AS-101"]
    assert "OH1" in text["A-602"] and "G01 GARAGE" in text["A-602"]
    assert "NOT HEATED" in text["A-601"]
    assert "2-car, attached" in text["G-001"]
    doc.close()
    dx = ezdxf.readfile(res["dxf"])
    assert "GARAGE (2-CAR)" in {e.dxf.text for e in
                                dx.modelspace().query("TEXT")}


@needs_modulor
def test_two_story_section_goes_through_the_stair(tmp_path):
    import fitz
    from app import genset_ui
    out = str(tmp_path / "s2.pdf")
    genset_ui.generate({"brief": "two story 2400 sf house, 3 bed 2 bath"},
                       out, use_ai=False)
    doc = fitz.open(out)
    sec = next(pg for pg in doc if pg.get_label() == "A-301")
    assert "THROUGH THE STAIR" in sec.get_text()
    doc.close()


# ---- 0.12.20: front porch and rear deck ---------------------------------
def test_brief_reads_porch_and_deck():
    from app.genset import outdoor
    assert outdoor.read("house with a covered front porch") == {"porch": 6.0}
    assert outdoor.read("farmhouse, wraparound porch")["porch"] == 8.0
    assert outdoor.read("rear deck") == {"deck": True}
    assert outdoor.read("no porch, back deck") == {"deck": True}
    assert outdoor.read("3 bed 2 bath 1600 sf") == {}


def test_porch_and_deck_on_the_plan():
    for stories in (1, 2):
        p = layout.make_plan({"building_type": "single_family",
                              "gross_sf": 2200, "beds": 3, "baths": 2,
                              "stories": stories, "porch": 6.0,
                              "deck": True, "garage": 2})
        por, dk = p["porch"], p["deck"]
        W, D = p["footprint"]["width"], p["footprint"]["depth"]
        x0, y0, x1, y1 = por["rect"]
        assert y1 == -0.25 and y1 - y0 == 6.0 and 10 <= x1 - x0 <= 24
        front = next(o for o in p["openings"] if o.get("from_room") ==
                     "EXT" and o["wall"] == "W1")
        assert x0 <= front["along"] <= x1          # the porch is at the door
        assert len(por["posts"]) >= 2
        assert dk["rect"][1] == D + 0.25 and dk["rect"][3] - \
            dk["rect"][1] == 10.0
        g = p["garage"]["rect"]
        for r in (por["rect"], dk["rect"]):      # never on the garage
            assert r[2] <= g[0] + 1e-6 or r[0] >= g[2] - 1e-6 or \
                r[3] <= g[1] or r[1] >= g[3]
        assert "porch" not in model.levels(p)[-1] or stories == 1


@needs_modulor
def test_porch_and_deck_set(tmp_path):
    import fitz
    from app import genset_ui
    out = str(tmp_path / "pd.pdf")
    genset_ui.generate({"brief": "3 bed 2 bath house 1800 sf, covered front "
                                 "porch, rear deck, lot 90 x 140"}, out,
                       use_ai=False)
    doc = fitz.open(out)
    text = {pg.get_label(): pg.get_text() for pg in doc}
    assert "COVERED PORCH" in text["A-101"] and "DECK" in text["A-101"]
    assert "PORCH ROOF" in text["A-102"]
    assert "PORCH" in text["AS-101"]
    assert "covered porch" in text["G-001"]
    doc.close()


# ---- Fable review (Oct 19) ---------------------------------------------
def test_review_setbacks_need_a_unit_or_a_comma():                   # M4
    f = brief.parse("1800 sf house, setbacks per zoning, back 2 bedrooms "
                    "front 1 bedroom, 2 bath", use_ai=False)
    assert not (f.get("lot") or {}).get("setbacks") and f["beds"] == 2
    f = brief.regex_fields("setbacks per the survey, front entry 2 steps "
                           "up, side 1 car garage")
    assert not (f.get("lot") or {}).get("setbacks")
    for text in ("setbacks front 20 side 5 rear 15",
                 "setbacks 20 front 5 side 15 rear",
                 "setbacks: front 20', sides 5', rear 15'"):
        sb = brief.regex_fields(text)["lot"]["setbacks"]
        assert sb == {"front": 20, "side": 5, "rear": 15}, (text, sb)
    f = brief.regex_fields("Lot size: about 75 x 150 ft. three bedrooms, "
                           "two baths, 2000 sf")
    assert (f["lot"]["w"], f["lot"]["d"], f["beds"], f["baths"]) == \
        (75, 150, 3, 2)


def test_review_no_upstairs_window_under_the_garage_roof():          # M5
    from app.genset import garage as g_
    for sf in (1600, 2400, 3600):
        for beds, baths in ((3, 2), (4, 3)):
            p = layout.make_plan({"building_type": "single_family",
                                  "gross_sf": sf, "beds": beds,
                                  "baths": baths, "stories": 2,
                                  "garage": 2})
            g = p.get("garage")
            if not g:
                continue
            wall = "W2" if g["side"] == "E" else "W4"
            D = p["footprint"]["depth"]
            for o in model.levels(p)[1]["openings"]:
                if o["kind"] != "window" or o["wall"] != wall:
                    continue
                y = o["along"] if wall == "W2" else D - o["along"]
                ya, yb = y - o["width"] / 2, y + o["width"] / 2
                if yb <= 0 or ya >= g["depth"]:
                    continue
                yy = min(max(g["depth"] / 2, ya), yb)
                roof = g["plate_height"] + g["pitch"] / 12 * min(
                    yy, g["depth"] - yy)
                assert 10.0 + o["sill"] >= roof + g_.ROOF_CLEAR, (sf, o)


def test_review_shallow_house_and_detached_garage():               # M6 N7
    from app.genset import garage
    p = layout.make_plan({"building_type": "single_family", "gross_sf": 400,
                          "beds": 1, "baths": 1, "garage": 2})
    assert "garage" not in p
    assert any("needs 20 ft" in w for w in p["warnings"])
    for t in ("detached garage later", "existing 2-car garage",
              "garage not needed", "no garage"):
        assert garage.read("1800 sf house, " + t) is None, t
    assert garage.read("1800 sf house, attached 2-car garage") == 2


# ---- 0.12.21: quantity summary -----------------------------------------
def test_quantities_follow_the_plan():
    from app.genset import quantities
    p = layout.make_plan({"building_type": "single_family", "gross_sf": 1600,
                          "beds": 3, "baths": 2, "garage": 2, "deck": True})
    q = {r[1]: r for r in quantities.rows(p)}
    W, D = p["footprint"]["width"], p["footprint"]["depth"]
    assert q["Slab on grade (house)"][2] == round((W + 0.5) * (D + 0.5))
    assert q["Exterior walls"][2] == round(2 * (W + D))
    doors = sum(o["kind"] == "door" for o in p["openings"])
    assert sum(r[2] for r in quantities.rows(p)
               if r[1].startswith("Door ")) == doors
    floors = sum(r[2] for r in quantities.rows(p)
                 if r[1].startswith("Floor finish"))
    assert abs(floors - sum(r["area"] for r in p["rooms"])) < 3
    assert not any("TBD" in r[1] for r in quantities.rows(p))
    assert q["Roofing squares"][3] == "SQ" and "Deck" in q
    two = layout.make_plan({"building_type": "single_family",
                            "gross_sf": 2400, "beds": 4, "baths": 3,
                            "stories": 2})
    names = [r[1] for r in quantities.rows(two)]
    assert "L2 Exterior walls" in names and any(n.startswith("Stair")
                                                for n in names)
    assert not any("TBD" in n for n in names)


@needs_modulor
def test_quantity_sheet_and_csv(tmp_path):
    import csv
    import fitz
    from app import genset_ui
    out = str(tmp_path / "q.pdf")
    res = genset_ui.generate({"brief": "3 bed 2 bath house 1600 sf, 2-car "
                                       "garage"}, out, use_ai=False)
    doc = fitz.open(out)
    last = doc[-1]
    assert last.get_label() == "A-701"
    t = last.get_text()
    assert "QUANTITY SUMMARY" in t and "Roofing squares" in t
    doc.close()
    rows = list(csv.reader(open(res["quantities"], encoding="utf-8")))
    assert rows[0] == ["Group", "Item", "Quantity", "Unit", "Measured"]
    assert any(r[1] == "Garage slab (2-car)" for r in rows)


def test_set_quantities_priced_in_the_estimate(tmp_path):
    """0.12.21: the set's quantities ride in the PDF, show in the
    Quantities panel as "set" lines, take a price, and export."""
    import csv
    import fitz
    from app import estimate, genset_ui
    out = str(tmp_path / "e.pdf")
    genset_ui.generate({"brief": "3 bed 2 bath house 1600 sf"}, out,
                       use_ai=False)
    doc = fitz.open(out)
    items = estimate.set_items(doc)
    assert items and all(it["page"] == doc.page_count - 1 for it in items)
    lines = estimate.lines(doc)
    sq = next(g for g in lines if g["name"] == "Roofing squares")
    assert sq["type"] == "set" and sq["unit"] == "SQ" and sq["quantity"] > 10
    estimate.set_price(doc, "Roofing squares", "set", "SQ", unit_cost=400,
                       waste=10)
    sq = next(g for g in estimate.lines(doc) if g["name"] == "Roofing squares")
    assert abs(sq["total"] - round(sq["quantity"] * 1.1 * 400, 2)) < 0.02
    assert not estimate.lines(doc, page=0)      # only on the A-701 page
    path = str(tmp_path / "e.csv")
    estimate.export_csv(doc, path)
    text = open(path, encoding="utf-8-sig").read()
    assert "Roofing squares" in text and ",set," in text
    doc.close()


def test_set_quantities_bad_data_is_skipped():
    """A PDF from anywhere can carry the set file: bad rows are skipped,
    huge or endless numbers refused, a stale page index clamped."""
    import json
    from app import estimate

    class Doc:
        page_count = 3

        def embfile_names(self):
            return [estimate.SET_FILE]

        def embfile_get(self, name):
            return json.dumps({"page": 40, "rows": [
                {"item": "Good", "unit": "SF", "quantity": 12.5},
                {"item": "Text", "unit": "SF", "quantity": "lots"},
                {"item": "Inf", "unit": "SF", "quantity": float("inf")},
                {"item": "Neg", "unit": "SF", "quantity": -4},
                {"item": "", "unit": "SF", "quantity": 3},
                "not a row"]}).encode()
    items = estimate.set_items(Doc())
    assert [i["item"] for i in items] == ["Good"]
    assert items[0]["page"] == 2


def test_driveway_and_walk_quantities():
    """0.12.21: the paving drawn on AS-101 is counted - the drive from the
    overhead doors, the walk to the porch edge (not under the porch)."""
    from app.genset import build, quantities
    p = build.plan_from_brief("3 bed 2 bath house 1600 sf, 2-car garage, "
                              "front porch", use_ai=False)
    rows = {r[1]: r[2] for r in quantities.rows(p)}
    ly = p["site"]["lot_y0"]
    assert rows["Driveway paving"] > 0
    assert rows["Front walk, 4 ft"] == round(4 * (p["porch"]["rect"][1] - ly))
    q = build.plan_from_brief("3 bed 2 bath house 1600 sf", use_ai=False)
    rows = {r[1]: r[2] for r in quantities.rows(q)}
    assert "Driveway paving" not in rows
    assert rows["Front walk, 4 ft"] == round(4 * (-0.25 - q["site"]["lot_y0"]))


def test_narrow_lot_reshapes_the_house():
    """0.12.21: a house too wide for a lot the brief gives is made deeper
    and narrower (front still the front), only when that fits the setbacks
    and the self-check is no worse; without a lot nothing changes."""
    from app.genset import audit, build
    p = build.plan_from_brief("3 bed 2 bath house 1800 sf, lot 45 x 130, "
                              "setbacks 20 front, 5 side, 20 rear",
                              use_ai=False)
    fp = p["footprint"]
    assert fp["from"] == "fit to the lot" and fp["depth"] > fp["width"]
    assert p["site"]["on_lot"] and not p["site"]["binding"]
    assert any("Proportions changed to fit the lot" in w
               for w in p["warnings"])
    assert audit.summary(audit.audit(p)) != "FAIL"
    door = next(o for o in p["openings"] if o.get("from_room") == "EXT"
                and o["wall"] == "W1")
    assert door["to_room"] == p["rooms"][0]["id"]       # into the main room
    hall = next(r for r in p["rooms"] if r["name"] == "HALL")
    x0, y0, x1, y1 = hall["rect"]
    assert y1 - y0 > x1 - x0                            # runs front to back
    q = build.plan_from_brief("3 bed 2 bath house 1800 sf", use_ai=False)
    assert q["footprint"]["from"] == "brief"
    assert q["footprint"]["width"] > q["footprint"]["depth"]
    # a lot nothing can fit: the original proportions, and the warning
    r = build.plan_from_brief("3 bed 2 bath house 1800 sf, lot 25 x 100",
                              use_ai=False)
    assert r["footprint"]["from"] == "brief" and not r["site"]["on_lot"]


def test_narrow_two_story_fits_the_lot():
    """Reshaped only when no room comes out long and skinny. A floor too
    narrow for a wing each side of a center hall (0.12.23) gets a side
    hall along the west wall and one wide wing - a row house."""
    from app.genset import audit, build, layout, model
    p = build.plan_from_brief("3 bed 2 bath two story house 2400 sf, lot "
                              "50 x 120, side setback 5 ft", use_ai=False)
    assert p["footprint"]["from"] == "fit to the lot"
    assert p["footprint"]["width"] + 0.5 <= 40
    assert audit.summary(audit.audit(p)) != "FAIL"
    assert layout._lanky(p) == 0
    q = build.plan_from_brief("3 bed 2 bath two story house 2400 sf, lot "
                              "40 x 120, side setback 5 ft", use_ai=False)
    assert q["footprint"]["from"] == "fit to the lot"
    assert q["footprint"]["width"] + 0.5 <= 30
    assert not q["site"]["binding"] and layout._lanky(q) == 0
    assert audit.summary(audit.audit(q)) != "FAIL"
    for lp in model.levels(q):
        hall = lp["rooms"][0]
        assert hall["rect"][0] < 1                  # along the west wall
        assert all(r["rect"][0] >= hall["rect"][2] - 1e-6
                   for r in lp["rooms"][1:])        # one wing, east
    st = q["rooms"][0]["stair"]
    assert st["rect"][0] < 1                        # stair on the wall side



def test_deep_house_keeps_deck_back_door_and_lit_rooms():
    """0.12.22 review: a deep house gets its back door at the end of the
    hall (so a deck can go there); a garage keeps every room lit when a
    side allows it and names the room its door really opens into; with a
    garage the ridge stays east-west (the garage roof meets a gable)."""
    from app.genset import audit, build
    p = build.plan_from_brief("3 bed 2 bath house 1800 sf, lot 45 x 130, "
                              "setbacks 20 front, 5 side, 20 rear, front "
                              "porch, rear deck", use_ai=False)
    assert p["footprint"]["depth"] > p["footprint"]["width"]
    assert p.get("deck") and p["roof"]["ridge_dir"] == "y"
    back = [o for o in p["openings"] if o.get("from_room") == "EXT"
            and o["wall"] == "W3"]
    assert back
    q = build.plan_from_brief("3 bed 2 bath house 1200 sf, lot 50 x 150, "
                              "setbacks 20 front, 5 side, 20 rear, 1 car "
                              "garage", use_ai=False)
    g = q["garage"]
    door = next(o for o in q["openings"] if o["id"] == g["door"])
    assert g["into"] == next(r["name"] for r in q["rooms"]
                             if r["id"] == door["to_room"])
    assert q["roof"]["ridge_dir"] == "x"
    assert sum(o.get("from_room") == "EXT" for o in q["openings"]) >= 2
    assert not [r for r in audit.audit(q) if r[0] != "PASS" and
                "window" in r[1].lower()]


def test_venice_review_fixes():
    """0.12.24, verified findings from the Venice review."""
    from app.genset import audit, build, layout, model, outdoor, quantities
    # S1: three garage walls are 2 x width + depth
    for cars in (1, 2, 3):
        p = build.plan_from_brief(f"3 bed 2 bath house 1800 sf, {cars} car "
                                  "garage", use_ai=False)
        g = p["garage"]
        row = next(r for r in quantities.rows(p)
                   if r[1] == "Garage walls (3 sides)")
        assert row[2] == round(2 * g["width"] + g["depth"])
    # M10: "no covered porch" draws none; a stated depth is used
    assert "porch" not in outdoor.read("no covered porch, rear deck")
    assert outdoor.read("a porch 10 ft deep")["porch"] == 10.0
    # M12: a gap along the front fails the dimension check
    p = build.plan_from_brief("3 bed 2 bath house 1600 sf", use_ai=False)
    assert audit._chain(p)
    front = [r for r in p["rooms"] if abs(r["rect"][1] - 0.25) < 1e-6]
    front.sort(key=lambda r: r["rect"][0])
    front[0]["rect"][2] -= 3.0
    assert not audit._chain(p)
    # M13: rooms left out are data, not only a sentence
    q = build.plan_from_brief("4 bed 3 bath two story house 1300 sf",
                              use_ai=False)
    assert q["dropped"] and layout._left_out(q) == len(q["dropped"])
    # N10: a side hall gets a window on each floor
    r = build.plan_from_brief("3 bed 2 bath two story house 2400 sf, lot 40 "
                              "x 120, side setback 5 ft", use_ai=False)
    for lp in model.levels(r):
        hall = lp["rooms"][0]
        assert any(o["kind"] == "window" and o["room"] == hall["id"]
                   for o in lp["openings"])
    assert audit.summary(audit.audit(r)) != "FAIL"
