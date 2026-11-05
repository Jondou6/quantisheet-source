"""The ADA module: the 2010 Standards index, the scoping checker (its
tables checked against the Standards' own text), and the ADA checks of
generated office / retail sets."""
import math
import os
import re

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest                                                  # noqa: E402

from app import ada_check as ac                                # noqa: E402
from app import ada_ref as ref                                 # noqa: E402
from test_gui import ANSWERS, win, qapp                  # noqa: E402,F401


def _pairs(table_text):
    """'1 to 25\\n1\\n26 to 50\\n2...' -> [(25, 1), (50, 2), ...] for rows
    whose answer is a plain number."""
    lines = [s.strip() for s in table_text.split("\n") if s.strip()]
    out = []
    for a, b in zip(lines, lines[1:]):
        m = re.fullmatch(r"(\d+) to (\d+)", a)
        if m and re.fullmatch(r"\d+", b):
            out.append((int(m.group(2)), int(b)))
    return out


def _table(sid, name):
    t = ref.find(sid)["text"]
    return t[t.index(name):]


# ------------------------------------------------------------- the index
def test_index_has_the_whole_standards():
    secs = ref.sections()
    assert len(secs) > 1100
    for sid in ("101.1", "206.2.3", "208.2", "208.2.4", "213.3.1",
                "221.2.1.1", "224.2", "304.3.1", "404.2.3", "404.2.4.1",
                "502.2", "604.8.1.1", "1009.2"):
        assert ref.find(sid), sid
    assert ref.find("404.2.3")["title"] == "Clear Width"
    assert "32 inches (815 mm) minimum" in ref.find("404.2.3")["text"]
    assert any(s["id"].startswith("DOJ 35.151") for s in secs)
    # no running heads, footers or the back index left in the text
    for s in secs:
        assert "2010 Standards:" not in s["text"], s["id"]
        assert "INDEX TO THE" not in s["text"], s["id"]
    assert len(ref.find("1010.1")["text"]) < 2000
    # every subsection has its parent
    ids = {s["id"] for s in secs}
    assert not [i for i in ids if "." in i and not i.startswith("DOJ")
                and i.rsplit(".", 1)[0] not in ids]


def test_search():
    assert ref.search("404.2.3")[0]["id"] == "404.2.3"
    assert ref.search("§ 208.2")[0]["id"] == "208.2"
    assert [s["id"] for s in ref.search("404.2")][:2] == ["404.2",
                                                         "404.2.1"]
    assert "404.2.4.1" in [s["id"] for s in
                           ref.search("door maneuvering")[:2]]
    assert "227.2" in [s["id"] for s in ref.search("checkout aisle")]
    assert ref.search("") == [] and ref.search("zzzqqq") == []
    assert [k["id"] for k in ref.children("404.2.4")] == \
        ["404.2.4.1", "404.2.4.2", "404.2.4.3", "404.2.4.4"]
    assert ref.parent("404.2.4.1")["id"] == "404.2.4"


# ---------------------------------------- the tables, against the text
def test_parking_table_matches_the_standards():
    rows = _pairs(_table("208.2", "Table 208.2"))
    assert rows == ac.PARKING
    t = ref.find("208.2")["text"]
    assert "501 to 1000\n2 percent of total" in t
    assert "20, plus 1 for each 100, or fraction there of, over 1000" in t
    assert "every six or fraction of six" in ref.find("208.2.4")["text"]
    assert "Ten percent" in ref.find("208.2.1")["text"]
    assert "Twenty percent" in ref.find("208.2.2")["text"]


def test_wheelchair_table_matches_the_standards():
    rows = _pairs(_table("221.2.1.1", "Table 221.2.1.1"))
    assert rows == [r for r in ac.WHEELCHAIR if r[1]]
    t = ref.find("221.2.1.1")["text"]
    assert "6, plus 1 for each 150, or fraction thereof" in t
    assert "36, plus 1 for each 200, or fraction thereof" in t


def test_guest_room_tables_match_the_standards():
    t = _table("224.2", "Table 224.2")
    lines = [s.strip() for s in t.split("\n") if s.strip()]
    rows = []
    for i, s in enumerate(lines):
        m = re.fullmatch(r"(\d+) to (\d+)", s)
        if m and i + 3 < len(lines) and all(
                re.fullmatch(r"\d+", x) for x in lines[i + 1:i + 4]):
            rows.append((int(m.group(2)),) + tuple(
                int(x) for x in lines[i + 1:i + 4]))
    assert rows == ac.GUEST
    comm = _pairs(_table("224.4", "Table 224.4"))
    assert comm == [r for r in ac.COMM if r[1]]


def test_receiver_table_matches_the_standards():
    t = ref.find("219.3")["text"]
    for frag in ("2, plus 1 per 25 seats", "20, plus 1 per 33 seats",
                 "35, plus 1 per 50 seats", "55 plus 1 per 100 seats",
                 "Or fraction thereof", "but no fewer than two"):
        assert frag in t, frag


# ----------------------------------------------------------- the numbers
@pytest.mark.parametrize("n,need", [
    (0, 0), (1, 1), (25, 1), (26, 2), (100, 4), (101, 5), (500, 9),
    (501, 11), (1000, 20), (1001, 21), (1100, 21), (1101, 22)])
def test_parking(n, need):
    assert ac.parking_required(n) == need


def test_parking_medical_and_vans():
    assert ac.parking_required(80, "outpatient") == 8
    assert ac.parking_required(81, "outpatient") == 9
    assert ac.parking_required(80, "rehab") == 16
    assert [ac.van_required(n) for n in (0, 1, 6, 7, 12, 13)] == \
        [0, 1, 1, 2, 2, 3]


def test_assembly_numbers():
    assert [ac.wheelchair_spaces(n) for n in (3, 4, 26, 151, 501, 650,
                                              651, 5000, 5001)] == \
        [0, 1, 2, 5, 7, 7, 8, 36, 37]
    assert ac.receivers(50) == (2, 2)
    assert ac.receivers(51) == (3, 2)
    assert ac.receivers(201) == (9, 3)
    assert ac.receivers(1000) == (36, 9)
    assert ac.receivers(2001) == (56, 14)


def test_lodging_numbers():
    assert ac.guest_mobility(51) == (3, 1, 4)
    assert ac.guest_mobility(501) == (11, 6, 16)
    assert ac.guest_mobility(1001) == (21, 11, 32)
    assert ac.guest_communication(1) == 0
    assert ac.guest_communication(501) == 26
    assert ac.guest_communication(1100) == 53


def test_bad_counts_are_ignored():
    for bad in (None, "", "abc", -3, float("nan"), float("inf"), True):
        assert ac._n(bad) == 0
    assert ac.check({"parking": [{"total": "nan"}, "x", None]}) is not None
    assert ac.check("not a dict")


# ----------------------------------------------------------- the checker
def _find(fs, text):
    return [f for f in fs if text in f.item]


def test_elevator_exception_only_for_small_private_buildings():
    small = ac.check({"use": "office", "stories": 2, "sf_per_story": 9000})
    assert _find(small, "between stories")[0].required == "Not required"
    big = ac.check({"use": "office", "stories": 3, "sf_per_story": 9000})
    assert _find(big, "between stories")[0].required == "Required"
    tiny = ac.check({"use": "office", "stories": 4, "sf_per_story": 2500})
    assert _find(tiny, "between stories")[0].required == "Not required"
    for p in ({"use": "shopping_center", "stories": 2},
              {"use": "health_office", "stories": 2},
              {"use": "office", "stories": 2, "title": "II"}):
        f = _find(ac.check(p), "between stories")[0]
        assert f.required == "Required", p
    f = _find(ac.check({"use": "office", "stories": 3, "elevator": False}),
              "between stories")[0]
    assert f.status == "short"


def test_toilet_rooms():
    fs = ac.check({"toilet_rooms": [
        {"name": "Men", "compartments": 3, "urinals": 3, "lavatories": 2,
         "wheelchair_compartments": 1, "ambulatory_compartments": 0},
        {"name": "Women", "compartments": 5, "lavatories": 2}]})
    assert _find(fs, "Men: ambulatory")[0].status == "short"
    assert not _find(fs, "Women: ambulatory")     # 5 water closets only
    assert _find(fs, "Men: accessible urinal")
    assert _find(fs, "Men: wheelchair")[0].status == "ok"


def test_parking_and_entrances_status():
    fs = ac.check({"parking": [{"total": 120, "accessible": 4, "van": 1}],
                   "public_entrances": 3, "accessible_entrances": 2})
    acc = _find(fs, "accessible spaces")[0]
    assert (acc.required, acc.provided, acc.status) == (5, 4, "short")
    assert _find(fs, "van spaces")[0].status == "ok"
    assert _find(fs, "Public entrances")[0].required == 2
    assert _find(fs, "Signs at entrances")


def test_every_cite_is_a_real_section():
    p = {"use": "hospital", "stories": 3, "parking": [{"total": 300}],
         "loading_zone_ft": 150, "public_entrances": 4, "tenant_spaces": 2,
         "toilet_rooms": [{"compartments": 6, "urinals": 2,
                           "lavatories": 3}],
         "single_user_toilets_cluster": 3, "drinking_fountains": 3,
         "assembly_areas": [{"seats": 400, "aisle_seats": 60}],
         "dining_seats": 90, "work_surfaces": 10, "counter_types": 2,
         "checkout_aisles": 3, "dressing_rooms": 30, "lockers": 50,
         "guest_rooms": 120, "patient_rooms": 40}
    fs = ac.check(p)
    assert len(fs) > 30
    for f in fs:
        for sid in re.findall(r"\d{3,4}(?:\.\d+)*", f.cite):
            assert ref.find(sid), (f.item, sid)
    text = ac.report_text(p, fs)
    assert "Screening aid only" in text and "[208.2 / Table 208.2]" in text


def test_saved_in_the_pdf(tmp_path):
    fitz = pytest.importorskip("fitz")
    if not hasattr(fitz, "open") or not callable(getattr(fitz, "open")):
        pytest.skip("no PyMuPDF")
    doc = fitz.open()
    doc.new_page()
    ac.write(doc, {"use": "retail", "stories": 2})
    path = str(tmp_path / "a.pdf")
    doc.save(path)
    assert ac.read(fitz.open(path))["use"] == "retail"
    assert ac.read(fitz.open())["use"] == "office"


# --------------------------------------- generated office / retail sets
def test_commercial_plans_pass_the_ada_checks():
    from app.genset import ada_plan, layout
    for occ in ("B", "M"):
        for sf in (1000, 1500, 2400, 4000, 8000):
            p = layout.make_plan({"building_type": "small_commercial",
                                  "occupancy": occ, "gross_sf": sf})
            res = {c: (s, d) for s, c, d, _sec in ada_plan.checks(p)}
            for c in ("Door clear width", "Restroom turning space",
                      "Accessible route width", "Route to every room",
                      "Accessible entrance", "Door maneuvering depth"):
                assert res[c][0] == "PASS", (occ, sf, c, res[c])
            doors = [o for o in p["openings"] if o["kind"] == "door"]
            assert all(o["width"] >= 3.0 for o in doors), (occ, sf)
            hall = [r for r in p["rooms"] if r["type"] == "hall"]
            assert all(min(r["rect"][2] - r["rect"][0],
                           r["rect"][3] - r["rect"][1]) >= 5.0
                       for r in hall)


def test_ada_plan_finds_a_narrow_door_and_a_small_restroom():
    from app.genset import ada_plan, layout
    p = layout.make_plan({"building_type": "small_commercial",
                          "occupancy": "B", "gross_sf": 2400})
    door = next(o for o in p["openings"] if o["kind"] == "door" and
                o["from_room"] != "EXT")
    door["width"] = 2.667
    rr = next(r for r in p["rooms"] if r["type"] == "restroom")
    rr["rect"][2] = rr["rect"][0] + 4.5
    res = {c: s for s, c, _d, _sec in ada_plan.checks(p)}
    assert res["Door clear width"] == "FAIL"
    assert res["Restroom turning space"] == "FAIL"


def test_house_sets_have_no_ada_sheet_and_keep_their_doors():
    from app.genset import build, layout
    house = layout.make_plan({"building_type": "single_family",
                              "gross_sf": 1600, "beds": 3, "baths": 2})
    assert "A-801" not in dict(build.sheets_for(house))
    inner = [o for o in house["openings"] if o["kind"] == "door" and
             o["from_room"] != "EXT"]
    assert any(math.isclose(o["width"], 2.667) for o in inner)
    shop = layout.make_plan({"building_type": "small_commercial",
                             "occupancy": "M", "gross_sf": 3000})
    assert build.sheets_for(shop)[-1] == ("A-801", "Accessibility")


def test_scoping_from_a_set():
    from app.genset import ada_plan, layout
    p = layout.make_plan({"building_type": "small_commercial",
                          "occupancy": "M", "gross_sf": 3000})
    proj = ada_plan.scoping(p)
    assert proj["use"] == "retail" and proj["stories"] == 1
    fs = ac.check(proj)
    assert _find(fs, "RESTROOM 1: room complies with 603")


def test_commercial_set_has_the_accessibility_sheet(tmp_path):
    fitz = pytest.importorskip("fitz")
    pytest.importorskip("modulor")
    from app import genset_ui
    out = str(tmp_path / "shop.pdf")
    res = genset_ui.generate({"brief": "3,000 sf retail store, new"}, out,
                             use_ai=False)
    doc = fitz.open(out)
    assert res["pages"] == doc.page_count == 12      # with G-003 (Oct 20)
    assert doc[-1].get_label() == "A-801"
    text = doc[-1].get_text()
    assert "ACCESSIBILITY (2010 ADA STANDARDS)" in text
    assert "404.2.3" in text and "SCOPING" in text
    assert "FAIL" not in text


def test_ada_window(qapp):
    from app.ada_ui import AdaDialog
    dlg = AdaDialog(None)
    ref_tab = dlg.ref
    ref_tab.q.setText("van parking")
    assert ref_tab.hits.count() > 0
    dlg.read("404.2.3")
    assert "32 inches" in ref_tab.view.toPlainText()
    ck = dlg.checker
    ck.ed["stories"].setText("3")
    ck.ed["sf_per_story"].setText("12000")
    ck.parking.add({"total": "120", "accessible": "4"})
    ck.run(save=False)
    items = [ck.found.item(r, 1).text() for r in range(ck.found.rowCount())]
    assert any("between stories" in t for t in items)
    assert "short" in ck.summary.text()
    dlg.close()


def test_module_tab_works_without_a_drawing(win):
    """Module > ADA opens with no drawing open (0.12.26 had the items
    greyed out until a PDF was open)."""
    # Nov 4: the Module tab's groups are on Project now (fewer tabs)
    from app import quickaccess
    assert quickaccess.where_is(win, win.command("ADA Checker"))[1] == \
        "Project"
    assert not [m for m in win._ribbon_missing if "ADA" in m]
    for name in ("ADA Standards PDF", "ADA Standards (2010)",
                 "ADA Checker"):
        a = win.command(name)
        assert a is not None and a.isEnabled(), name
    dlg = win.ada(1)
    assert dlg.isVisible() and dlg.tabs.currentIndex() == 1
    dlg.close()
    assert win.ada_pdf(80)
    assert win._view.doc.page_count == 279 and win._view.page == 79
    assert "ADA Standards" in win._view.doc[0].get_text()
