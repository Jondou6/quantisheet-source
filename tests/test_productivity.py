"""Build Schedule From Plans: durations from quantities and production
rates (app/pm/productivity.py) - the GC's table (load / save / merge), the
quantities read or estimated from the job, duration = quantity / (rate x
crews) within each family's min / max, the BASIS of every row, and the
0.12.32 review's acceptance numbers (item 5: durations no longer linear in
the floor area; the 38,000 SF warehouse no longer 1,216 days)."""
import datetime as dt
import json
import math
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["QUANTISHEET_NO_OPEN"] = "1"

import pytest                                                 # noqa: E402

from app.pm import autoschedule as au                         # noqa: E402
from app.pm import productivity as prod                       # noqa: E402
from app.pm import schedule                                   # noqa: E402
from app.pm import schedule_types as st                       # noqa: E402
from app.pm.store import ProjectStore                         # noqa: E402


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    """A settings folder of the test's own (no real productivity.json)."""
    from app import settings
    d = tmp_path / "cfg"
    monkeypatch.setattr(settings, "DIR", str(d))
    monkeypatch.setattr(settings, "PATH", str(d / "settings.json"))
    monkeypatch.setattr(settings, "_cache", {})
    return d


@pytest.fixture
def qapp():
    qw = pytest.importorskip("PySide6.QtWidgets")
    return qw.QApplication.instance() or qw.QApplication([])


def _rows(*pairs):
    return [{"number": n, "title": t} for n, t in pairs]


# a typical building set: site, structure, architecture, MEP, fire
FULL_SET = _rows(("C-101", "SITE PLAN"), ("C-201", "GRADING AND DRAINAGE "
                                          "PLAN"),
                 ("C-301", "UTILITY PLAN"), ("C-401", "PAVING PLAN"),
                 ("L-101", "LANDSCAPE PLAN"), ("S-101", "FOUNDATION PLAN"),
                 ("S-201", "ROOF FRAMING PLAN"), ("A-101", "FLOOR PLAN"),
                 ("A-201", "EXTERIOR ELEVATIONS"), ("A-301", "WALL SECTIONS"),
                 ("A-601", "DOOR SCHEDULE"), ("M-101", "HVAC PLAN"),
                 ("P-101", "PLUMBING PLAN"), ("E-101", "POWER PLAN"),
                 ("E-201", "LIGHTING PLAN"), ("FP-101", "FIRE SPRINKLER PLAN"),
                 ("FA-101", "FIRE ALARM PLAN"))
NTP = dt.date(2026, 11, 2)


def _sc_days(tmp_path, area, stories=1, sheets=FULL_SET):
    """Calendar days from NTP to Substantial Completion, through build()
    and the CPM."""
    sc = au.scope(sheets, area_sf=area, stories=stories)
    assert sc["type"] == "new_building"
    s = ProjectStore(str(tmp_path / f"p{int(area)}_{stories}"))
    au.build(s, sc, NTP)
    cpm = schedule.compute(s, NTP)
    assert not cpm["problems"]
    row = next(r for r in cpm["rows"] if r["name"] == "Substantial "
               "Completion")
    return (row["ef"] - NTP).days + 1


# ------------------------------------------------------------- the table
def test_every_family_is_complete_and_marked_assumed(cfg):
    t = prod.load()
    assert not t["edited"]
    for key, fam in t["families"].items():
        assert fam["rate"] > 0 and fam["crews"] >= 1, key
        assert 0 <= fam["min"] <= fam["max"], key
        assert fam["unit"] and fam["note"], key
        assert fam["qty"] in prod.estimates({"area_sf": 5000}, t), key
    # every family a template names exists
    for fams in prod.ACTIVITY_FAMILIES.values():
        for f in fams.values():
            # "@structure" / "@exterior": picked per job (structure_family,
            # exterior_family - review 0.12.39 added "@exterior" for the
            # tilt-up panel finishes)
            assert f in ("@structure", "@exterior") or f in t["families"], f
    assert "ASSUMED STARTING VALUE" in prod.__doc__


def test_load_save_merge_and_reset(cfg):
    assert not os.path.exists(prod.path())
    (cfg).mkdir(parents=True, exist_ok=True)
    with open(prod.path(), "w", encoding="utf-8") as fh:
        json.dump({"families": {"slab": {"rate": 5000, "crews": "two",
                                         "note": "our crew"},
                                "drywall": {"min": 20, "max": 10},
                                "no_such": {"rate": 1}},
                   "assumptions": {"story_height_ft": 20, "bogus": 3,
                                   "site_factor": -1}}, fh)
    t = prod.load()
    assert t["families"]["slab"]["rate"] == 5000         # Jon's edit wins
    assert t["families"]["slab"]["crews"] == 1           # junk ignored
    assert t["families"]["slab"]["note"] == "our crew"
    assert t["families"]["drywall"]["max"] == 20         # max >= min
    assert "no_such" not in t["families"]
    assert t["assumptions"]["story_height_ft"] == 20
    assert t["assumptions"]["site_factor"] == 3.0        # -1 ignored
    assert {"slab", "drywall"} <= t["edited"]
    # a family nobody edited keeps the default
    assert t["families"]["paint"] == prod.FAMILIES["paint"]
    # save writes only what differs from the defaults
    t["families"]["paint"]["crews"] = 3
    data = prod.save(t)
    assert set(data["families"]) == {"slab", "drywall", "paint"}
    assert data["assumptions"] == {"story_height_ft": 20}
    assert prod.load()["families"]["paint"]["crews"] == 3
    # a broken file: the defaults, no crash
    with open(prod.path(), "w", encoding="utf-8") as fh:
        fh.write("{not json")
    assert prod.load()["families"]["slab"]["rate"] == \
        prod.FAMILIES["slab"]["rate"]
    t = prod.reset()
    assert not os.path.exists(prod.path())
    assert t["families"] == prod.FAMILIES


# ------------------------------------------------------------- quantities
def test_quantities_from_area_and_levels(cfg):
    t = prod.load()
    est = prod.estimates({"area_sf": 20000, "stories": 2}, t)
    assert est["floor"][0] == 20000
    assert est["footprint"][0] == 10000
    w = math.sqrt(10000 / 2.0)                      # a 2:1 rectangle
    assert est["perimeter"][0] == pytest.approx(6 * w)
    assert est["roof_sq"][0] == pytest.approx(100)  # roof = footprint
    assert est["wall_sf"][0] == pytest.approx(6 * w * 14 * 2)
    assert "2 levels" in est["footprint"][1]
    # pipe LF: the takeoff's when there is one
    assert est["pipe_lf"][1].endswith("est.")
    est = prod.estimates({"area_sf": 20000, "pipe_lf": 900}, t)
    assert est["pipe_lf"] == (900, "takeoff: pipe")


def test_duration_maths_clamps_and_basis_text(cfg):
    t = prod.defaults()
    slab = t["families"]["slab"]
    slab.update(rate=2500, crews=1, min=3, max=40)
    d, text = prod.duration("slab", 12000, t)
    assert d == 5 == math.ceil(12000 / 2500)
    assert text == "12,000 SF slab / (2,500 SF/day x 1 crew) = 5 d " \
                   "(rate assumed)"
    slab["crews"] = 2
    assert prod.duration("slab", 12000, t)[0] == 3       # ceil(2.4)
    d, text = prod.duration("slab", 1000, t)
    assert d == 3 and "raised to the 3 d minimum" in text
    d, text = prod.duration("slab", 400000, t)
    assert d == 40 and "= 80 d, capped at the 40 d maximum" in text
    assert "2 crews" in text
    t["edited"].add("slab")
    assert prod.duration("slab", 12000, t)[1].endswith(
        "(rate from your production table)")


def test_every_row_has_a_basis_and_most_are_quantity_driven(cfg):
    sc = au.scope(FULL_SET, area_sf=12000)
    acts = au.plan(sc)
    assert all(a["basis"] for a in acts)
    q = [a for a in acts if a["quantity_driven"]]
    # the lead-ins (a few fixed days of layout / mock-ups in place of
    # lags - schedule_types.LEAD_INS) are steps, not quantities
    work = [a for a in acts if a["key"] not in st.LEAD_INS]
    assert len(q) / len(work) >= 0.60, (len(q), len(work))
    by = {a["key"]: a for a in acts}
    assert by["sc"]["basis"] == "milestone (0 d)"
    assert by["submittals"]["basis"] == "fixed 20 d"
    assert by["slab"]["family"] == "slab"
    assert by["slab"]["basis"].startswith("12,000 SF slab (footprint")
    fam = prod.FAMILIES["slab"]
    assert by["slab"]["duration"] == min(fam["max"], max(
        fam["min"], math.ceil(12000 / (fam["rate"] * fam["crews"]))))


def test_rows_without_a_rate_scale_by_the_square_root(cfg):
    sheets = FULL_SET + _rows(("C-001", "SITE DEMOLITION PLAN"))

    def plan(area):
        sc = au.scope(sheets, area_sf=area, project_type="new_building")
        assert "demolition" in sc["flags"]
        return {a["key"]: a for a in au.plan(sc)}
    small, big = plan(5000), plan(20000)
    assert small["demo"]["duration"] == 15             # 5 + 2 x 5: as before
    assert big["demo"]["duration"] == 30               # 15 x (20k/5k)^0.5
    assert "^0.5" in big["demo"]["basis"] and not big["demo"][
        "quantity_driven"]


def test_takeoff_quantities_beat_the_estimates(cfg):
    takeoff = [{"type": "area", "group": "Slab on grade", "value": 12000,
                "unit": "ft"},
               {"type": "area", "group": "Existing slab", "value": 9999},
               {"type": "area", "group": "Drywall - Type X", "value": 60000,
                "unit": "ft"},
               {"type": "area", "group": "Asphalt paving", "value": 27000,
                "unit": "ft"},
               {"type": "length", "group": "8 in sewer", "value": 2400,
                "unit": "ft"},
               {"type": "count", "group": "CMU block", "value": 3375,
                "unit": "ea"}]
    sc = au.scope(FULL_SET, area_sf=5000, takeoff=takeoff)
    by = {a["key"]: a for a in au.plan(sc)}
    assert 'takeoff: "Slab on grade"' in by["slab"]["basis"]
    assert by["slab"]["basis"].startswith("12,000 SF slab")  # not 5,000
    assert by["drywall"]["basis"].startswith("60,000 SF board")
    assert by["paving"]["basis"].startswith("3,000 SY paving")
    assert by["utilities"]["duration"] == 30          # 2400 LF / 80
    assert by["structure"]["family"] == "cmu"         # what was taken off
    assert by["structure"]["basis"].startswith("3,000 SF wall")
    t = prod.load()
    for key, q in (("slab", 12000), ("drywall", 60000), ("paving", 3000)):
        fam = t["families"][prod.family_for("new_building", key, sc, t)]
        assert by[key]["duration"] == min(fam["max"], max(
            fam["min"], math.ceil(q / (fam["rate"] * fam["crews"]))))
    # no takeoff: the estimate
    sc = au.scope(FULL_SET, area_sf=5000)
    by = {a["key"]: a for a in au.plan(sc)}
    assert by["slab"]["basis"].startswith("5,000 SF slab (footprint")
    assert by["structure"]["family"] == "structure"


def test_your_rates_and_crews_drive_the_plan(cfg):
    sc = au.scope(FULL_SET, area_sf=40000)
    before = {a["key"]: a for a in au.plan(sc)}
    t = prod.load()
    t["families"]["slab"].update(rate=1000, crews=2, max=100)
    prod.save(t)
    after = {a["key"]: a for a in au.plan(sc)}
    assert after["slab"]["duration"] == 20            # 40,000 / (1,000 x 2)
    assert "x 2 crews" in after["slab"]["basis"]
    assert "rate from your production table" in after["slab"]["basis"]
    assert after["paint"]["duration"] == before["paint"]["duration"]


def test_build_stores_the_basis_in_the_activity_notes(cfg, tmp_path):
    s = ProjectStore(str(tmp_path / "p"))
    sc = au.scope(FULL_SET, area_sf=8000)
    res = au.build(s, sc, NTP)
    slab = next(a for a in s.list("activity") if a["name"] ==
                "Slab on grade")
    assert slab["notes"].startswith("BASIS: 8,000 SF slab")
    assert slab["basis"] and slab["family"] == "slab"
    phases = [a for a in s.list("activity") if a["name"] == "Foundations"]
    assert phases and not phases[0].get("notes")      # summary rows: none
    assert "activities sized from quantities" in res["basis"]
    assert res["basis"] in au.summary_text({}, sc, res)


# ------------------------------------------------------------- acceptance
def test_review_item5_durations_are_not_linear_in_area(cfg, tmp_path):
    days = {a: _sc_days(tmp_path, a) for a in (5000, 10000, 20000, 40000)}
    assert days[5000] < days[10000] < days[20000] < days[40000]
    assert days[40000] / days[5000] <= 2.5, days        # was 4.55


def test_review_item5_warehouse_lands_within_200_to_400_days(cfg, tmp_path):
    d = _sc_days(tmp_path, 38402)                      # was 1,216
    assert 200 <= d <= 400, d


# ------------------------------------------------------------- the dialogs
def test_rates_editor_round_trip(qapp, cfg):
    from app.pm import productivity_ui as pui
    dlg = pui.ProductivityDialog()
    assert dlg.table.rowCount() == len(prod.FAMILIES)
    r = dlg.row_of("slab")
    assert dlg.table.item(r, pui.C_RATE).text() == \
        f"{prod.FAMILIES['slab']['rate']:g}"
    dlg.set_value("slab", "crews", "2")
    dlg.set_value("drywall", "rate", "4,500")
    dlg.set_value("paint", "min", "abc")                # not a number
    dlg.assume.item(dlg._akeys.index("story_height_ft"), 1).setText("18")
    problems = dlg.save_table()
    assert any("Painting" in p for p in problems)
    t = prod.load()
    assert t["families"]["slab"]["crews"] == 2
    assert t["families"]["drywall"]["rate"] == 4500
    assert t["families"]["paint"]["min"] == prod.FAMILIES["paint"]["min"]
    assert t["assumptions"]["story_height_ft"] == 18
    again = pui.ProductivityDialog()                    # reopened
    assert again.table.item(again.row_of("slab"), pui.C_CREWS).text() == "2"
    again.reset()
    assert not os.path.exists(prod.path())
    assert again.table.item(again.row_of("slab"), pui.C_CREWS).text() == \
        f"{prod.FAMILIES['slab']['crews']:g}"
    assert prod.load()["families"] == prod.FAMILIES
    dlg.close()
    again.close()


def _sched(tmp_path):
    from app.pm import scheduler as sch
    st = sch.create_schedule("Job", folder=str(tmp_path / "job"))
    w = sch.Scheduler(st)
    w._quiet = True
    return w


def test_build_dialog_opens_the_rates_and_uses_them(qapp, cfg, tmp_path):
    w = _sched(tmp_path)
    dlg = w.build_from_plans(show=False)
    ed = dlg.edit_rates(show=False)
    ed.set_value("slab", "rate", "1000")
    ed.set_value("slab", "crews", "2")
    ed.set_value("slab", "max", "100")
    ed.save_table()
    sc = au.scope(FULL_SET, area_sf=40000)
    dlg.show_info({"ct": au.contract_time([]), "scope": sc, "sheets": 17,
                   "divisions": [], "area_found": True})
    assert dlg.area.text() == "40000"
    res = dlg.build()
    assert res and res["activities"] > 30
    slab = next(a for a in w.store.list("activity")
                if a["name"] == "Slab on grade")
    assert slab["duration"] == 20 and "x 2 crews" in slab["notes"]
    ed.close()
    w.close()


def test_build_dialog_says_when_the_type_is_unclear(qapp, cfg, tmp_path):
    from app.pm import schedule_types as st
    w = _sched(tmp_path)
    dlg = w.build_from_plans(show=False)
    sc = au.scope(texts=["LIFT STATION", "WASTEWATER TREATMENT PLANT"])
    assert sc["detected"]["ambiguous"]
    dlg.show_info({"ct": au.contract_time([]), "scope": sc, "sheets": 1,
                   "divisions": []})
    a, b = (st.label(k) for k in sc["detected"]["candidates"][:2])
    text = dlg.found.text()
    assert f"Project type unclear: {a} or {b} - pick one" in text
    assert "not recognized" not in text.split("Scope:")[0]
    assert text.count("(score ") >= 2               # both candidates listed
    assert dlg.ptype.currentData() == st.UNKNOWN
    assert "unclear" in dlg.ptype.currentText()
    assert dlg.build() is None                      # the person picks first
    assert dlg.last_message.startswith(f"Project type unclear: {a} or {b}")
    # nothing recognized at all: the old wording
    dlg.show_info({"ct": au.contract_time([]), "scope": au.scope(),
                   "sheets": 1, "divisions": []})
    assert "Project type not recognized" in dlg.found.text()
    assert "not recognized" in dlg.ptype.currentText()
    w.close()


def test_scheduler_shows_the_basis_on_the_duration(qapp, cfg, tmp_path):
    from app.pm import scheduler as sch
    s = ProjectStore(str(tmp_path / "grid"))
    au.build(s, au.scope(FULL_SET, area_sf=8000), NTP)
    w = sch.Scheduler(s, None)
    t = w.table
    row = next(r for r in range(t.rowCount())
               if t.item(r, sch.C_NAME) and
               t.item(r, sch.C_NAME).text().strip() == "Slab on grade")
    tip = t.item(row, sch.C_DUR).toolTip()
    assert tip.startswith("Basis: 8,000 SF slab")
    w.close()


# ------------------------------------------------------------- 0.12.35 #3
WH_SHEETS = _rows(("G-001", "COVER"), ("AS-101", "SITE PLAN"),
                  ("A-101", "FLOOR PLAN"), ("A-102", "ENLARGED OFFICE PLAN"),
                  ("A-103", "ROOF PLAN"), ("A-201", "EXTERIOR ELEVATIONS"),
                  ("A-301", "BUILDING SECTION"), ("A-601", "ROOM SCHEDULE"),
                  ("A-602", "DOOR & WINDOW SCHEDULES"))
INTERIOR = ("drywall", "paint", "ceilings", "flooring", "doors", "casework")


def _warehouse_set(tmp_path):
    """A made-up 38,000 SF warehouse with a 3,000 SF office, as Generate
    Set leaves it beside its PDF: <name>.genset.json and
    <name>.quantities.csv (the PDF itself isn't needed here)."""
    from app.genset import layout, quantities
    plan = layout.make_plan({"building_type": "warehouse",
                             "gross_sf": 38000, "office_sf": 3000})
    pdf = tmp_path / "Sample_Warehouse.pdf"
    (tmp_path / "Sample_Warehouse.genset.json").write_text(
        json.dumps(plan), encoding="utf-8")
    quantities.write_csv(plan, str(tmp_path /
                                   "Sample_Warehouse.quantities.csv"))
    return plan, str(pdf)


def test_review3_warehouse_interiors_from_the_generate_set_data(cfg,
                                                              tmp_path):
    plan, pdf = _warehouse_set(tmp_path)
    gs = au.read_genset(pdf)
    assert gs and gs["plan"] and gs["rows"]
    assert "Sample_Warehouse.genset.json" in gs["source"]
    area = sum(r["area"] for r in plan["rooms"])
    sc = au.scope(WH_SHEETS, area_sf=area, genset=gs,
                  texts=["WAREHOUSE / INDUSTRIAL BUILDING"])
    by = {a["key"]: a for a in au.plan(sc)}
    for k in ("drywall", "paint", "flooring"):
        assert by[k]["duration"] <= 15, (k, by[k]["basis"])
    for k in INTERIOR:
        assert "genset:" in by[k]["basis"], (k, by[k]["basis"])
    # sized off the office, not the 38,000 SF floor
    assert prod.quantity("drywall", sc)[0] < 12000
    assert prod.quantity("doors", sc)[0] < 40
    assert prod.quantity("flooring", sc)[0] < 4000
    # most work rows come from the set's own quantities
    work = [a for a in by.values() if a["duration"] > 0]
    from_set = [a for a in work if "genset:" in a["basis"]]
    assert len(from_set) / len(work) >= 0.60, (len(from_set), len(work))
    assert "from the Generate Set quantities" in au.basis_summary(
        list(by.values()))


def test_review3_csv_alone_and_embedded_rows_work_too(cfg, tmp_path):
    plan, pdf = _warehouse_set(tmp_path)
    os.remove(os.path.splitext(pdf)[0] + ".genset.json")
    gs = au.read_genset(pdf)
    assert gs and gs["plan"] is None and gs["rows"]
    area = sum(r["area"] for r in plan["rooms"])
    by = {a["key"]: a for a in au.plan(au.scope(WH_SHEETS, area_sf=area,
                                                genset=gs))}
    assert by["drywall"]["duration"] <= 15 and \
        "genset:" in by["drywall"]["basis"]
    # the rows embedded in the PDF (estimate.set_items' dicts)
    rows = [{"group": g, "item": i, "quantity": q, "unit": u, "how": h}
            for g, i, q, u, h in prod._rows_of(gs["rows"])]
    q = prod.set_quantities(rows)
    assert q["doors"][0] < 40 and q["finish_floor_sf"][0] < 4000


def test_review3_area_changed_by_hand_drops_the_set_quantities(cfg,
                                                               tmp_path):
    plan, pdf = _warehouse_set(tmp_path)
    sc = au.scope(WH_SHEETS, area_sf=38000, genset=au.read_genset(pdf))
    sc["area_sf"] = 80000                       # typed in the dialog
    est = prod.estimates(sc)
    assert "genset" not in est["floor"][1]


def test_review3_warehouse_without_the_set_data(cfg):
    # room tags: the warehouse bay is left out of the finishes
    rooms = [{"name": "WAREHOUSE", "sf": 35000},
             {"name": "OPEN OFFICE", "sf": 1800},
             {"name": "BREAK ROOM", "sf": 600}, {"name": "LOBBY", "sf": 600}]
    sc = au.scope(WH_SHEETS, area_sf=38000, rooms=rooms)
    by = {a["key"]: a for a in au.plan(sc)}
    for k in ("drywall", "paint", "flooring"):
        assert by[k]["duration"] <= 15, (k, by[k]["basis"])
    assert "room tags (takeoff)" in by["drywall"]["basis"]
    assert prod.quantity("flooring", sc)[0] == pytest.approx(3000)
    # no tags, no set data: an assumed office share - and it says so
    sc = au.scope(WH_SHEETS, area_sf=38000,
                  texts=["WAREHOUSE / INDUSTRIAL BUILDING"])
    by = {a["key"]: a for a in au.plan(sc)}
    for k in ("drywall", "paint", "flooring"):
        assert by[k]["duration"] <= 15, (k, by[k]["basis"])
        assert "floor area (fallback)" in by[k]["basis"]
        assert "warehouse" in by[k]["basis"]
    assert prod.quantity("flooring", sc)[0] == pytest.approx(3800)
    # an ordinary building: the whole floor, named as the fallback
    by = {a["key"]: a for a in au.plan(au.scope(FULL_SET, area_sf=12000))}
    assert "floor area (fallback)" in by["drywall"]["basis"]


# ------------------------------------------------------------- 0.12.38 #1
def _genset_scope(tmp_path, fields, read_sf, texts=()):
    """A made-up Generate Set set (sidecar files beside the PDF) read with
    a floor area `read_sf` from the drawing text."""
    from app.genset import layout, quantities
    plan = layout.make_plan(fields)
    name = fields["building_type"]
    (tmp_path / f"{name}.genset.json").write_text(json.dumps(plan),
                                                   encoding="utf-8")
    quantities.write_csv(plan, str(tmp_path / f"{name}.quantities.csv"))
    gs = au.read_genset(str(tmp_path / f"{name}.pdf"))
    return au.scope(WH_SHEETS, area_sf=read_sf, genset=gs, texts=list(texts))


@pytest.mark.parametrize("fields,gap,texts,items", [
    ({"building_type": "warehouse", "gross_sf": 38000}, 1.06,
     ["WAREHOUSE / INDUSTRIAL BUILDING"],
     {"storefront", "overhead_doors", "joists", "roofing", "doors"}),
    ({"building_type": "strip_retail", "gross_sf": 20000}, 1.085, [],
     {"storefront", "joists", "roofing", "doors"}),
])
def test_review38_set_quantities_win_over_the_area_read(cfg, tmp_path,
                                                        fields, gap, texts,
                                                        items):
    """The area read from the drawing text 5.7% / 7.8% off the set's rooms
    (the old 5% gate threw the set's quantities away):
    the set's quantities still size the job (T4 chains, T5 >= 60%
    'genset'), and a note names both areas."""
    sc = _genset_scope(tmp_path, fields, 0, texts)
    set_sf = sc["set_quantities"]["floor"][0]
    sc = _genset_scope(tmp_path, fields, round(set_sf * gap), texts)
    acts = au.plan(sc)
    by = {a["key"]: a for a in acts}
    for it in items:                 # submit -> review -> deliver -> install
        d = by[f"deliver_{it}"]
        assert d["preds"][0][0] == f"appr_{it}"
        assert any(f"deliver_{it}" in {p for p, _t, _l in a["preds"]}
                   for a in acts if not a["key"].startswith(
                       ("sub_", "appr_", "deliver_"))), it
    work = [a for a in acts if a["duration"] > 0]
    share = sum("genset:" in a["basis"] for a in work) / len(work)
    assert share >= 0.60, share
    floor_rows = [a for a in work if "(genset: room areas" in a["basis"]]
    assert floor_rows
    read = f"{round(set_sf * gap):,.0f} SF"
    assert all(read in a["basis"] and f"{set_sf:,.0f} SF" in a["basis"]
               for a in floor_rows), floor_rows[0]["basis"]
    note = [n for n in sc["notes"] if n.startswith("Floor area:")]
    assert note and read in note[0] and f"{set_sf:,.0f} SF" in note[0]
    if "overhead_doors" in items:
        n = sc["set_quantities"]["overhead_doors"][0]
        assert by["oh_doors"]["name"].startswith(f"Overhead doors ({n:g})")
        assert by["oh_doors"]["basis"].startswith(f"{n:g} EA overhead doors"
                                                  " (genset:")


def test_review38_far_apart_areas_say_why_the_set_is_not_used(cfg,
                                                              tmp_path):
    sc = _genset_scope(tmp_path, {"building_type": "warehouse",
                                  "gross_sf": 38000}, 80000,
                       ["WAREHOUSE / INDUSTRIAL BUILDING"])
    est = prod.estimates(sc)
    assert "genset" not in est["floor"][1]
    assert not any(n.startswith("Quantities from the Generate Set")
                   for n in sc["notes"])
    assert any("not used for the quantities" in n and "80,000 SF" in n
               for n in sc["notes"])
    # the door count doesn't depend on the area: still the set's
    assert est["overhead_doors"][1].startswith("genset:")


# ------------------------------------------------------- 0.12.38 T8
def test_review38_warehouse_bay_work_is_not_behind_the_office(cfg,
                                                              tmp_path):
    """T8 (made-up 38,000 SF Generate Set warehouse): the office's
    insulation and trim are sized from the office, the bay's trim runs
    after the rough-in inspections beside the office finishes, and
    Substantial Completion is within 300 calendar days of NTP."""
    sc = _genset_scope(tmp_path, {"building_type": "warehouse",
                                  "gross_sf": 38000}, 38000,
                       ["WAREHOUSE / INDUSTRIAL BUILDING"])
    by = {a["key"]: a for a in au.plan(sc)}
    assert by["insulation"]["duration"] <= 6, by["insulation"]["basis"]
    assert by["mep_trim"]["duration"] <= 8, by["mep_trim"]["basis"]
    bay = by["bay_trim"]
    assert [p for p, _t, _l in bay["preds"]] == ["inspect"]
    assert "warehouse bay" in bay["basis"] and "genset:" in bay["basis"]
    assert bay["duration"] > by["mep_trim"]["duration"]
    s = ProjectStore(str(tmp_path / "p"))
    ntp = dt.date(2026, 11, 2)
    au.build(s, sc, ntp, {})
    cpm = schedule.compute(s, ntp)
    sc_row = next(r for r in cpm["rows"]
                  if r["name"] == "Substantial Completion")
    assert 120 <= (sc_row["ef"] - ntp).days <= 300
    # an office building keeps one trim row for the whole floor
    by = {a["key"]: a for a in au.plan(au.scope(FULL_SET, area_sf=12000))}
    assert "bay_trim" not in by


# ------------------------------------------------------- 0.12.39 norms
# The starter rates were reviewed against public production figures (the
# sources are in productivity.py): durations by job type now land in the
# ranges a US GC would expect, a large job puts more than one crew on the
# floor-wide trades, a tilt-up warehouse is sized as tilt-up panels and
# its bay's MEP is not office density.
def _genset_job(tmp_path, fields, cover=True, sidecar=True):
    """A Generate Set job as Build From Plans reads it (its sheet list,
    notes and sidecar files): the scope. `cover`: the drawing text has the
    cover sheet's self-check lines too ("No walking through bedrooms..."),
    as page_lines() reads them off G-001; `sidecar`: the .genset.json is
    beside the PDF (else only the quantities CSV)."""
    from app.genset import audit, layout, notes, quantities, \
        sheets as gsheets
    plan = layout.make_plan(dict(fields))
    name = f"{fields['building_type']}_{int(fields['gross_sf'])}"
    if sidecar:
        (tmp_path / f"{name}.genset.json").write_text(json.dumps(plan),
                                                       encoding="utf-8")
    quantities.write_csv(plan, str(tmp_path / f"{name}.quantities.csv"))
    gs = au.read_genset(str(tmp_path / f"{name}.pdf"))
    rows = [{"number": sp.no, "title": sp.title.upper()}
            for sp in gsheets.specs_for(plan)]
    texts = list(notes.GENERAL) + list(notes.template_project_notes(plan))
    if cover:
        res = audit.audit(plan)
        texts.append(f"SELF-CHECK: {audit.summary(res)}")
        for st_, chk, det in res:
            texts += [st_, chk + (f"  ({det})" if det else "")]
    return au.scope(rows, area_sf=sum(r["area"] for r in plan["rooms"]),
                    texts=texts, genset=gs)


def _days(sc, tmp_path, tag):
    s = ProjectStore(str(tmp_path / tag))
    au.build(s, sc, NTP, {})
    cpm = schedule.compute(s, NTP)
    row = next(r for r in cpm["rows"] if r["name"] == "Substantial "
               "Completion")
    return (row["ef"] - NTP).days


MONTH = 30.4


@pytest.mark.parametrize("fields,lo,hi", [
    # the review's sanity targets, in months to Substantial Completion
    # (with the defaults at 0.12.39: 5.0, 5.9, 7.7 and 7.2 months; the
    # 38,000 SF warehouse was 9.4 months with structure at 1,000 SF/day
    # and the rough-ins at one crew over the whole floor)
    ({"building_type": "single_family", "gross_sf": 1600}, 4, 6),
    ({"building_type": "restaurant", "gross_sf": 4500}, 5, 7),
    ({"building_type": "strip_retail", "gross_sf": 20000}, 6, 9),
    ({"building_type": "warehouse", "gross_sf": 38000}, 7, 10),
])
def test_review39_job_lengths_land_in_the_expected_ranges(cfg, tmp_path,
                                                          fields, lo, hi):
    d = _days(_genset_job(tmp_path, fields), tmp_path, "p")
    assert lo * MONTH <= d <= hi * MONTH, (fields, d, round(d / MONTH, 1))


def test_review39_warehouse_38000_sf_is_exactly_219_days(cfg, tmp_path):
    """The figure the release notes give: a made-up Generate Set 38,000 SF
    warehouse, default settings, NTP Monday 2026-11-02, the default
    project calendar, calendar days from NTP to the Substantial Completion
    finish = 219. Pinned, so a change in the job length shows up here (and
    the release notes get updated with it)."""
    assert NTP == dt.date(2026, 11, 2) and NTP.weekday() == 0
    d = _days(_genset_job(tmp_path, {"building_type": "warehouse",
                                     "gross_sf": 38000}), tmp_path, "p")
    assert d == 219, (d, round(d / MONTH, 1))


def test_review39_crews_by_area_band(cfg):
    t = prod.defaults()
    band = t["assumptions"]["crew_band_sf"]
    most = t["assumptions"]["max_crews"]
    # small jobs: the Crews column; 4x the band: 2 crews; capped
    assert prod.band_crews("elec_rough", band / 2, t) == (1, "")
    n, text = prod.band_crews("elec_rough", 4 * band, t)
    assert n == 2 and "2 crews by area band" in text and "^0.5" in text
    assert prod.band_crews("elec_rough", 100 * band, t)[0] == most
    # the structure, slab and sitework are not banded
    for key in ("slab", "footings", "tilt_up", "structure", "paving"):
        assert prod.band_crews(key, 100 * band, t) == \
            (t["families"][key]["crews"], "")
    # the Crews column is the floor; max_crews 1 turns the band off
    t["families"]["drywall"]["crews"] = 3
    assert prod.band_crews("drywall", 4 * band, t)[0] == 3
    t["assumptions"]["max_crews"] = 1
    assert prod.band_crews("paint", 100 * band, t) == (1, "")
    # the durations still grow with the floor (no jump at a band edge)
    sizes = [prod.size("new_building", "elec_rough",
                       {"area_sf": a}, prod.defaults())
             for a in range(5000, 80001, 2500)]
    days = [s["duration"] for s in sizes]
    assert days == sorted(days), days
    big = sizes[-1]
    assert big["crews"] > 1 and "crews by area band" in big["basis"]


def test_review39_structure_and_exterior_from_what_the_set_is(cfg, tmp_path):
    wh = _genset_job(tmp_path, {"building_type": "warehouse",
                                "gross_sf": 38000})
    assert prod.structure_family(wh) == "tilt_up"
    by = {a["key"]: a for a in au.plan(wh)}
    assert by["structure"]["family"] == "tilt_up"
    assert by["structure"]["basis"].startswith("32,270 SF wall panels")
    # the panels are the wall: their finishes, not 40 d of cladding
    assert by["exterior"]["family"] == "panel_finish"
    assert by["exterior"]["duration"] < 40
    pemb = _genset_job(tmp_path, {"building_type": "warehouse",
                                  "gross_sf": 20000, "construction": "pemb"})
    assert prod.structure_family(pemb) == "steel_erection"
    house = _genset_job(tmp_path, {"building_type": "single_family",
                                   "gross_sf": 1600})
    assert prod.structure_family(house) == "wood_framing"
    # an office set that names no structure keeps the mixed rate
    assert prod.structure_family(au.scope(FULL_SET, area_sf=8000)) == \
        "structure"


def test_review39_warehouse_bay_rough_ins_are_not_office_density(cfg,
                                                                 tmp_path):
    sc = _genset_job(tmp_path, {"building_type": "warehouse",
                                "gross_sf": 38000})
    by = {a["key"]: a for a in au.plan(sc)}
    floor = sc["set_quantities"]["floor"][0]
    share = prod.ASSUMPTIONS["bay_rough_share"][0]
    for k in ("plumb_rough", "hvac_rough", "elec_rough", "underslab"):
        assert "bay MEP density" in by[k]["basis"], by[k]["basis"]
        assert "genset:" in by[k]["basis"]
    q = prod.size("new_building", "elec_rough", sc)["quantity"]
    fin = prod.finished_area(sc)[0]
    assert q == pytest.approx(fin + (floor - fin) * share, rel=1e-6)
    # was 35 d (capped) at one crew over the whole floor
    assert by["elec_rough"]["duration"] <= 25, by["elec_rough"]["basis"]
    # an office building: the whole floor at full density
    by = {a["key"]: a for a in au.plan(au.scope(FULL_SET, area_sf=12000))}
    assert "bay MEP density" not in by["elec_rough"]["basis"]
