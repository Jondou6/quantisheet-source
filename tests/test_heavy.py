"""Civil tab (HCSS-style): crews and production, equipment and labor
rates, owner's bid schedule, indirects, haul, versions, prevailing wages,
time cards and production history."""
import csv
import datetime as dt
import os
from decimal import Decimal

import fitz
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import annotate, heavy, pricedb, settings          # noqa: E402

D = Decimal


@pytest.fixture(autouse=True)
def _cfg(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", {"author": "Pat Morgan"})
    os.makedirs(settings.DIR, exist_ok=True)


def _doc():
    d = fitz.open()
    d.new_page(width=1224, height=792)
    annotate.apply_op(d, annotate.new_op("set_scale", 0, ppu=18.0,
                                         unit="ft"))
    for x in (100, 300):
        annotate.apply_op(d, annotate.new_op(
            "add_line", 0, pts=[[x, 100], [x + 100, 100]],
            measure={"type": "length", "value": 600, "unit": "ft",
                     "group": "8 in sewer"}))
    return d


def test_library_seeded_and_rates():
    lib = heavy.library()
    assert {"EXC-20", "BOX-8x20"} <= set(lib["equipment"])
    assert {"FMN", "LAB"} <= set(lib["labor"]) and "PIPE" in lib["crews"]
    # labor: (base + OT premium) x (taxes + comp + GL) + fringe
    b = heavy.burden({"code": "X", "base": 20, "fringe": 5, "ot_pct": 10,
                      "wc_rate": 8, "fica": 7.65, "unemp": 3, "gl_pct": 1.5,
                      "other_pct": 0})
    assert b["ot"] == D("1.00") and b["total"] == D("30.23")
    # prevailing wage replaces base and fringe
    pw = heavy.burden({"code": "X", "base": 20, "fringe": 5},
                      {"X": {"base": "30", "fringe": "10"}})
    assert pw["base"] == D("30.00") and pw["prevailing"]
    # equipment: owned vs rented spread over hours
    assert heavy.equipment_rate({"own_hr": 40, "op_hr": 20, "fuel_gph": 4},
                                4.25)["total"] == D("77.00")
    assert heavy.equipment_rate({"use": "rent", "rent_month": 3520,
                                 "hours_month": 176}, 4)["own"] == D("20.00")
    cr = heavy.crew_rate({"labor": [["LAB", 2], ["NOPE", 1]],
                          "equipment": []}, lib)
    assert cr["people"] == 2 and cr["missing"] == ["NOPE"]
    # edits persist in the price database
    heavy.save_items("labor", [dict(lib["labor"]["LAB"], base=99)])
    assert heavy.library()["labor"]["LAB"]["base"] == 99
    heavy.delete_item("labor", "LAB")
    assert "LAB" not in heavy.library()["labor"]
    heavy.set_settings({"fuel": 5})
    assert heavy.library()["settings"]["fuel"] == 5


def test_activities_from_takeoff_and_totals():
    lib = {"equipment": {"E": {"own_hr": 50, "op_hr": 0, "fuel_gph": 0}},
           "labor": {"L": {"code": "L", "base": 25, "fica": 0, "unemp": 0}},
           "crews": {"C": {"labor": [["L", 4]], "equipment": [["E", 1]]}},
           "settings": {"fuel": 4}}
    d = _doc()
    job = heavy.read(d)
    q, u = heavy.takeoff_qty(d, "8 in sewer")
    assert q == D(1200)
    a = heavy.add_activity(job, "Sewer", qty=q, unit="LF", crew="C",
                           rate=300, per="day", group="8 in sewer",
                           pay_item="2", code="33-31",
                           materials=[{"qty_per": 1, "cost": "11"}],
                           tags=["Phase 1"])
    with pytest.raises(heavy.HeavyError):
        heavy.add_activity(job, "x", per="week")
    c = heavy.activity_cost(a, lib, job)
    # 300 LF/day over 10 hr = 30 LF/hr -> 40 crew hours at $150/hr
    assert c["hours"] == D("40.00") and c["days"] == D("4.00")
    assert c["labor"] == D("4000.00") and c["equipment"] == D("2000.00")
    assert c["material"] == D("13200.00") and c["total"] == D("19200.00")
    assert c["unit_cost"] == D("16.00")
    heavy.add_activity(job, "Bad", qty=10, crew="ZZ")
    t = heavy.totals(job, lib)
    assert any("ZZ" in p for p in t["problems"])
    job["activities"].pop()
    job["indirects"] = [{"desc": "Super", "rate": "2000", "per": "week"},
                        {"desc": "Mob", "rate": "5000", "per": "LS"},
                        {"desc": "Trailer", "rate": "520", "per": "month",
                         "duration": "52"}]
    job["settings"].update(duration_weeks=4, markup_pct=10, bond_pct=1)
    t = heavy.totals(job, lib)
    assert t["indirect"] == D("13000.00") + D("6240.00")
    assert t["markup"] == D("3844.00")
    assert t["total"] == t["direct"] + t["indirect"] + t["markup"] + t["bond"]
    assert heavy.by_tag(job, lib) == {"Phase 1": D("19200.00")}
    # the takeoff grows -> the activity follows
    annotate.apply_op(d, annotate.new_op(
        "add_line", 0, pts=[[500, 100], [600, 100]],
        measure={"type": "length", "value": 300, "unit": "ft",
                 "group": "8 in sewer"}))
    assert heavy.refresh_quantities(d, job) == 1
    assert D(job["activities"][0]["qty"]) == D(1500)
    heavy.write(d, job)
    assert heavy.read(fitz.open("pdf", d.tobytes()))["activities"][0][
        "name"] == "Sewer"


def _sched(tmp_path):
    p = tmp_path / "bid.csv"
    with open(p, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Owner: City", "", "", ""])
        w.writerow(["Item No.", "Description", "Unit", "Est. Quantity"])
        w.writerow(["1", "Mobilization", "LS", "1"])
        w.writerow(["2", "8 in PVC sewer", "LF", "1,000"])
        w.writerow(["", "", "", ""])
    return str(p)


def test_bid_schedule_spread_and_quantity_check(tmp_path):
    lib = heavy.library()
    job = heavy.blank()
    job["pay_items"] = heavy.read_pay_items(_sched(tmp_path))
    assert [p["no"] for p in job["pay_items"]] == ["1", "2"]
    assert job["pay_items"][1]["owner_qty"] == "1000"
    heavy.add_activity(job, "Mob", qty=1, unit="LS", sub=3000, pay_item="1")
    heavy.add_activity(job, "Pipe", qty=1200, unit="LF", sub=36000,
                       pay_item="2")
    heavy.add_activity(job, "Loose", qty=1, sub=777)
    job["indirects"] = [{"desc": "Overhead", "rate": "3900", "per": "LS"}]
    job["settings"]["markup_pct"] = 0
    s = heavy.spread(job, lib)
    i1, i2 = s["items"]
    assert i1["share"] == D("300.00") and i2["share"] == D("3600.00")
    assert i2["unit_price"] == D("39.60") and i2["amount"] == D("39600.00")
    assert s["unassigned_cost"] == D("777.00")
    assert s["bid"] + s["unassigned_cost"] + s["rounding"] == s["total"]
    # front-load mobilization
    job["pay_items"][0]["weight"] = "11"
    s2 = heavy.spread(job, lib)
    assert s2["items"][0]["share"] > i1["share"] and \
        s2["items"][1]["share"] < i2["share"]
    qc = {q["no"]: q for q in heavy.quantity_check(job)}
    assert qc["2"]["diff_pct"] == D("20.0") and qc["2"]["flag"]
    assert not qc["1"]["flag"]
    out = heavy.export_schedule(job, lib, str(tmp_path / "s.csv"))
    rows = list(csv.reader(open(out)))
    assert rows[0][0] == "Item" and rows[-1][1] == "Total bid"
    import openpyxl
    x = heavy.export_schedule(job, lib, str(tmp_path / "s.xlsx"))
    assert openpyxl.load_workbook(x).worksheets[0]["B2"].value == \
        "Mobilization"
    bad = tmp_path / "bad.csv"
    bad.write_text("a,b\n1,2\n")
    with pytest.raises(heavy.HeavyError):
        heavy.read_pay_items(str(bad))


def test_haul():
    r = heavy.haul({"cy_bank": 5000, "swell_pct": 25, "truck_cy": 14,
                    "miles": 6, "mph_loaded": 30, "mph_empty": 40,
                    "load_min": 4, "dump_min": 2, "truck_hr": 95,
                    "loader_cyhr": 250, "loader_hr": 150})
    # cycle 6 + 12 + 9 = 27 min; 31.1 CY/hr a truck; 9 trucks keep up
    assert r["cycle_min"] == D("27.0") and r["trucks_needed"] == 9
    assert r["loose_cy"] == D("6250.0") and r["hours"] == D("25.0")
    assert r["cost"] == D("25125.00") and r["per_bank_cy"] == D("5.03")
    few = heavy.haul({"cy_bank": 5000, "miles": 6, "trucks": 3})
    assert few["trucks"] == 3 and few["hours"] > r["hours"]


def test_versions_compare_restore():
    lib = heavy.library()
    job = heavy.blank()
    heavy.add_activity(job, "A", qty=1, sub=100)
    v1 = heavy.save_version(job, "First", lib)
    job["activities"][0]["sub"] = "150"
    heavy.add_activity(job, "B", qty=1, sub=50)
    v2 = heavy.save_version(job, "", lib)
    assert v2["name"] == "Version 2" and v2["by"]
    c = heavy.compare_versions(job, v1["id"], v2["id"], lib)
    assert c["diff"] > 0
    names = {r["name"]: r["diff"] for r in c["rows"]}
    assert names["A"] == D("50.00") and names["B"] == D("50.00")
    heavy.restore_version(job, v1["id"])
    assert len(job["activities"]) == 1 and len(job["versions"]) == 2


def test_prevailing_wages_csv(tmp_path):
    lib = heavy.library()
    p = tmp_path / "wd.csv"
    p.write_text("Classification,Rate,Fringe\n"
                 "Laborer,$21.50,4.10\nOPR,29.00,8.00\n"
                 "Ironworker,35,12\n")
    wages, left = heavy.read_wages_csv(str(p), lib)
    assert wages["LAB"]["base"] == "21.50" and wages["OPR"]["fringe"] == \
        "8.00"
    assert left == ["Ironworker"]
    assert heavy.burden(lib["labor"]["LAB"], wages)["prevailing"]


class FakeStore:
    name = "Sewer Job"

    def __init__(self, cards, costs=()):
        self.cards, self.costs = cards, list(costs)

    def list(self, coll):
        return self.cards if coll == "timecard" else \
            self.costs if coll == "cost" else []


CARD = {"_id": "c1", "date": "2026-10-01", "status": "Approved",
        "crew": [{"name": "Al", "class": "LAB", "hours": 10},
                 {"name": "Bo", "class": "OPR", "hours": 10}],
        "equipment": [{"code": "EXC-20", "hours": 8}],
        "production": [{"cost_code": "SEW", "qty": 240, "unit": "LF",
                        "hours": 8},
                       {"cost_code": "MH", "qty": 1, "unit": "EA",
                        "hours": 2}]}


def test_timecards_actuals_and_production_history():
    lib = heavy.library()
    hrs = heavy.timecard_hours(CARD)
    assert hrs["SEW"]["qty"] == D(240) and hrs["SEW"]["crew_hours"] == 8
    costs = heavy.timecard_costs(CARD, lib)
    day = (heavy.burden(lib["labor"]["LAB"])["total"] * 10 +
           heavy.burden(lib["labor"]["OPR"])["total"] * 10 +
           heavy.equipment_rate(lib["equipment"]["EXC-20"],
                                lib["settings"]["fuel"])["total"] * 8)
    assert abs(sum(costs.values()) - day) <= D("0.02")
    assert costs["SEW"] > costs["MH"] * 3
    draft = dict(CARD, _id="c2", status="Draft")
    st = FakeStore([CARD, draft])
    acts = heavy.store_actuals(st, lib)
    assert {a["code"] for a in acts} == {"SEW", "MH"}
    # merge with direct costs: costs add, cost-record quantity wins
    merged = {m["code"]: m for m in heavy.merge_actuals(
        [{"code": "SEW", "cost": D(500), "qty": D(250), "unit": "LF"},
         {"code": "01", "cost": D(9), "qty": None}], acts)}
    assert merged["SEW"]["qty"] == D(250) and \
        merged["SEW"]["cost"] == D(500) + costs["SEW"]
    assert merged["MH"]["qty"] == D(1) and "01" in merged
    # production: recorded once per approved card
    assert heavy.record_production(st) == 2
    assert heavy.record_production(st) == 0
    later = dict(CARD, _id="c3", date="2026-10-02",
                 production=[{"cost_code": "SEW", "qty": 360, "unit": "LF",
                              "hours": 10}])
    heavy.record_production(FakeStore([later]))
    s = heavy.suggest_rate("SEW", today=dt.date(2026, 10, 15))
    assert s["count"] == 2 and s["unit"] == "LF"
    assert s["min"] == D("30.00") and s["max"] == D("36.00")
    assert D(30) <= s["rate"] <= D(36)
    assert heavy.suggest_rate("nothing") is None


def test_time_card_approval_is_office_only(tmp_path, monkeypatch):
    from app.collab import hub as hubmod
    H = hubmod.Hub(str(tmp_path / "hub"))
    H._caller = {"role": "sub", "email": "f@x.example", "name": "Fred"}
    H._can_write("timecard", None, False, {"status": "Submitted"})
    with pytest.raises(hubmod.HubError, match="approve"):
        H._can_write("timecard", None, False, {"status": "Approved"})
    with pytest.raises(hubmod.HubError):
        H._can_write("timecard", {"status": "Approved", "_by": "Fred"},
                     False, {"notes": "x"})
    H._caller = {"role": "pm", "email": "p@x.example", "name": "Pat"}
    H._can_write("timecard", None, False, {"status": "Approved"})


def test_timecard_tool_and_phone_tab():
    from app.pm import schema
    t = schema.TOOLS["timecard"]
    keys = [f["key"] for f in t["fields"]]
    assert {"crew", "equipment", "production", "status"} <= set(keys)
    assert t["statuses"] == ["Draft", "Submitted", "Approved"]
    from app.collab import hub as hubmod
    assert "timecard" in hubmod.SUB_COLLS
    html = open(os.path.join(os.path.dirname(hubmod.__file__), "web",
                             "project.html"), encoding="utf-8").read()
    assert 'data-tab="timecard"' in html and "function timecard()" in html


def test_civil_window(tmp_path, monkeypatch):
    pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtWidgets import QApplication
    from app import heavy_ui
    from app.heavy_ui import HeavyDialog, _pairs, _pairs_text
    QApplication.instance() or QApplication([])

    def no_popup(*a, **k):                   # a popup would hang the test
        raise AssertionError(f"unexpected message box: {a[1:3]}")
    for n in ("warning", "information", "question"):
        monkeypatch.setattr(heavy_ui.QMessageBox, n, no_popup)
    assert _pairs("FMN 1, OPR 2; LAB") == [["FMN", 1], ["OPR", 2],
                                          ["LAB", 1]]
    assert _pairs_text([["FMN", 1], ["LAB", 2.5]]) == "FMN 1, LAB 2.5"

    class View:
        def __init__(self):
            self.doc, self.dirty = _doc(), 0

        def mark_dirty(self):
            self.dirty += 1

    class Win:
        _view = View()
    win = Win()
    from PySide6.QtWidgets import QWidget
    holder = QWidget()
    dlg = HeavyDialog(holder, 0)
    dlg.win = win
    dlg._doc = win._view.doc
    dlg.job = heavy.read(dlg._doc)
    a = dlg.add_from_group("8 in sewer")
    assert D(a["qty"]) == 1200 and a["crew"]
    assert dlg.acts.rowCount() == 1 and win._view.dirty
    # edit the production rate in the table
    dlg.acts.item(0, dlg.AKEYS.index("rate")).setText("40")
    assert dlg.job["activities"][0]["rate"] == "40"
    assert "bid" in dlg.summary.text()
    dlg.import_pay(_sched(tmp_path))
    assert dlg.pay.rowCount() == 2
    dlg.add_typical()
    assert dlg.ind.rowCount() == len(dlg.TYPICAL)
    dlg.haul_in["cy_bank"].setValue(1000)
    ha = dlg.add_haul_activity()
    assert "trucking" in ha["tags"] and D(ha["sub"]) > 0
    dlg.save_version("v1")
    dlg.acts.item(0, dlg.AKEYS.index("qty")).setText("2000")
    dlg.save_version("v2")
    res = dlg.compare(dlg.job["versions"][0]["id"],
                      dlg.job["versions"][1]["id"])
    assert res["diff"] > 0
    assert dlg.export_pay(str(tmp_path / "out.xlsx"))
    code = dlg.add_crew("TEST", "test crew", [["LAB", 2]], [])
    assert code == "TEST" and "TEST" in heavy.library()["crews"]
    assert dlg.lookup("SEW") is None
    # quotes, schedule, resources tabs
    dlg.q_act.setCurrentIndex(0)
    q = dlg.add_quote("Ferguson", 9.5)
    assert q["use"] and dlg.quotes.rowCount() == 1
    dlg.add_quote("Core", 12)
    dlg.quotes.setCurrentCell(1, 0)
    dlg.use_selected()
    assert dlg.job["activities"][0]["quotes"][1]["use"]
    dlg.use_lowest()
    assert dlg.job["activities"][0]["quotes"][0]["use"]
    # filling the Schedule tab must not count as editing it (a restyled
    # cell used to call the edit handler, which refilled... until a crash)
    calls = []
    real = dlg._edit_schedule
    dlg.sched.on_edit = lambda *a: (calls.append(a), real(*a))
    dlg._fill_schedule()
    assert calls == []
    assert dlg.sched.rowCount() == len(dlg.job["activities"])
    dlg.sched.item(1, 1).setText(dlg.job["activities"][0]["name"])
    assert dlg.job["activities"][1]["after"] == dlg.job["activities"][0]["id"]
    assert dlg.use_schedule_length() > 0
    assert dlg.export_cashflow(str(tmp_path / "cf.xlsx"))
    assert dlg.res_lab.rowCount() > 0
    assert dlg.export_resources(str(tmp_path / "res.csv"))
    # library and masters
    keys = dlg.save_to_library([0])
    assert keys and keys[0] in heavy.library()["activities"]
    n = len(dlg.job["activities"])
    dlg.add_from_library(keys[0], qty=10)
    assert len(dlg.job["activities"]) == n + 1
    dlg.save_master("Test master")
    dlg.start_from_master("Test master", confirm=False)
    assert dlg.job["master"] == "Test master"
    assert dlg.fc.rowCount() == 0          # no project picked yet
    # saved into the PDF
    assert heavy.read(dlg._doc)["versions"][1]["name"] == "v2"


LIB = {"equipment": {"E": {"desc": "exc", "own_hr": 50}},
       "labor": {"L": {"code": "L", "desc": "lab", "base": 25, "fica": 0,
                       "unemp": 0}},
       "crews": {"C": {"labor": [["L", 4]], "equipment": [["E", 1]]}},
       "settings": {"fuel": 4}}


def _two():
    job = heavy.blank()
    a = heavy.add_activity(job, "Sewer", qty=1200, unit="LF", crew="C",
                           rate=300, per="day")
    b = heavy.add_activity(job, "MH", qty=6, unit="EA", crew="C", rate=2,
                           per="day")
    b["after"] = a["id"]
    return job, a, b


def test_quotes_lowest_used_and_spread():
    job, a, b = _two()
    heavy.add_quote(a, "Ferguson", 11)
    heavy.add_quote(a, "Core", "10.50")
    assert [q["use"] for q in a["quotes"]] == [False, True]
    assert heavy.activity_cost(a, LIB, job)["material"] == D("12600.00")
    heavy.use_quote(a, a["quotes"][0]["id"])
    assert heavy.activity_cost(a, LIB, job)["material"] == D("13200.00")
    heavy.add_quote(b, "Precast Co", 18000, kind="sub", per="LS")
    assert heavy.activity_cost(b, LIB, job)["sub"] == D("18000.00")
    sheet = {(r["activity"], r["kind"]): r for r in heavy.quote_sheet(job)}
    assert sheet[("Sewer", "material")]["spread"] == D("600.00")
    with pytest.raises(heavy.HeavyError):
        heavy.add_quote(a, "x", 1, kind="labor")


def test_resources_schedule_and_cashflow(tmp_path):
    job, a, b = _two()
    r = heavy.resources(job, LIB)
    # 4 + 3 crew days at 10 hr: 70 crew hours, 4 laborers each
    assert r["labor"]["L"]["hours"] == D("280.0")
    assert r["equipment"]["E"]["cost"] == D("3500.00")
    assert r["crew_days"]["C"] == D("7.0")
    s = heavy.schedule(job, LIB)
    rows = {x["name"]: x for x in s["rows"]}
    assert rows["MH"]["start"] == D("4.0") and s["days"] == D("7.0")
    b["lag"] = "2"
    assert heavy.schedule(job, LIB)["days"] == D("9.0")
    b["days_override"] = "1"
    assert heavy.schedule(job, LIB)["days"] == D("7.0")
    a["after"] = b["id"]
    assert heavy.schedule(job, LIB)["loops"]
    a["after"] = ""
    job["indirects"] = [{"desc": "x", "rate": "1000", "per": "LS"}]
    cf = heavy.cashflow(job, LIB, dt.date(2026, 11, 25))
    assert [m["month"] for m in cf] == ["2026-11", "2026-12"]
    assert cf[-1]["cumulative"] == heavy.totals(job, LIB)["total"]
    assert heavy._workday(dt.date(2026, 10, 16), 1) == dt.date(2026, 10, 19)
    out = heavy.export_cashflow(job, LIB, str(tmp_path / "cf.csv"),
                                dt.date(2026, 11, 25))
    assert list(csv.reader(open(out)))[0][0] == "Month"
    assert heavy.export_resources(job, LIB, str(tmp_path / "r.xlsx"))


def test_real_rate_sources_in_starter():
    import json
    st = json.load(open(heavy.STARTER, encoding="utf-8"))
    assert all("BLS" in l["source"] for l in st["labor"])
    assert st["settings"]["fuel"] > 4 and "EIA" in st["settings"][
        "fuel_source"]
    # every machine names where its rate came from (FEMA 2025 or a rental
    # price sheet) and says plainly what is an estimate
    assert all(("FEMA" in e["source"] or "Sunbelt" in e["source"])
               for e in st["equipment"])
    assert all("ASSUMPTION" in e["source"] or "ESTIMATE" in e["source"]
               for e in st["equipment"])
    assert all("SC20260043" in l["source"] for l in st["labor"])


def test_activities_from_takeoff_groups():
    d = _doc()
    annotate.apply_op(d, annotate.new_op(
        "add_line", 0, pts=[[100, 300], [200, 300]],
        measure={"type": "length", "value": 400, "unit": "ft",
                 "group": '24" RCP storm'}))
    annotate.apply_op(d, annotate.new_op(
        "add_count", 0, pt=[700, 300], n=1, color=[0.85, 0.2, 0.1],
        measure={"type": "count", "value": 1, "unit": "ea",
                 "group": "Manhole, 6-8 ft"}))
    annotate.apply_op(d, annotate.new_op(
        "add_line", 0, pts=[[100, 400], [200, 400]],
        measure={"type": "length", "value": 900, "unit": "ft",
                 "group": '6" water (existing), depth unknown'}))
    lib = heavy.library()
    job = heavy.blank()
    new = {a["name"]: a for a in heavy.activities_from_takeoff(d, job, lib)}
    assert not any("existing" in n for n in new)
    assert new["8 in sewer"]["crew"] == "PIPE" and \
        D(new["8 in sewer"]["rate"]) == 35
    assert D(new['24" RCP storm']["rate"]) == 16
    assert new["Manhole, 6-8 ft"]["crew"] == "MH" and \
        new["Manhole, 6-8 ft"]["unit"] == "EA"
    # run again: nothing doubled
    assert heavy.activities_from_takeoff(d, job, lib) == []
    assert heavy.totals(job, lib)["total"] > 0


def test_activity_library_and_master_estimates():
    lib = heavy.library()
    job = heavy.blank()
    a = heavy.add_activity(job, "8 in sewer 6-8 ft", qty=1200, unit="LF",
                           crew="PIPE", rate=35, code="33-31-00",
                           materials=[{"qty_per": 1, "cost": "11"}],
                           tags=["sewer"], group="8 in sewer",
                           pay_item="2")
    a["quotes"] = [{"vendor": "x"}]
    key = heavy.save_to_library(a, lib=lib)
    assert key == "33-31-00"
    lib = heavy.library()
    rec = lib["activities"][key]
    assert rec["crew_def"]["labor"] and "quotes" not in rec and \
        "qty" not in rec and "pay_item" not in rec
    assert [k for k, _ in heavy.search_library(lib, "SEWER 8")] == [key]
    assert heavy.search_library(lib, "storm") == []
    job2 = heavy.blank()
    b = heavy.add_from_library(job2, key, lib, qty=500)
    assert (b["code"], b["crew"], b["rate"], b["qty"]) == \
        ("33-31-00", "PIPE", "35", "500")
    assert heavy.activity_cost(b, lib, job2)["material"] == D("5500.00")
    # the crew comes back with it if it was deleted from the library
    heavy.delete_item("crews", "PIPE")
    lib = heavy.library()
    heavy.add_from_library(heavy.blank(), key, lib, qty=1)
    assert "PIPE" in heavy.library()["crews"]
    with pytest.raises(heavy.HeavyError):
        heavy.add_from_library(job2, "nope", lib)
    # a master: activities without quantities, picking them up from
    # takeoff groups of the same name
    job["indirects"] = [{"desc": "Super", "rate": "2800", "per": "week"}]
    job["settings"]["markup_pct"] = 12
    heavy.save_master(job, "Sewer extension")
    lib = heavy.library()
    d = _doc()
    new = heavy.new_from_master("Sewer extension", lib, d)
    assert D(new["activities"][0]["qty"]) == 1200
    assert new["indirects"][0]["desc"] == "Super" and \
        new["settings"]["markup_pct"] == 12
    blank_q = heavy.new_from_master("Sewer extension", lib)
    assert D(blank_q["activities"][0]["qty"]) == 0
    with pytest.raises(heavy.HeavyError):
        heavy.save_master(job, " ")


def test_cost_to_complete_forecast(tmp_path):
    lib = heavy.library()
    job = heavy.blank()
    heavy.add_activity(job, "Sewer", qty=1000, unit="LF", crew="PIPE",
                       rate=25, code="SEW",
                       materials=[{"qty_per": 1, "cost": "10"}])
    heavy.add_activity(job, "Manholes", qty=4, unit="EA", sub=20000,
                       code="MH")
    budget = {a["code"]: c for a, c in
              heavy.totals(job, lib)["activities"]}
    card = {"_id": "c1", "date": "2026-10-01", "status": "Approved",
            "crew": [{"class": "LAB", "hours": 40}],
            "equipment": [],
            "production": [{"cost_code": "SEW", "qty": 250, "unit": "LF",
                            "hours": 8}]}
    st = FakeStore([card], costs=[
        {"cost_code": "SEW", "amount": 6000, "quantity": 250, "unit": "LF"},
        {"cost_code": "XTRA", "amount": 900}])
    f = heavy.forecast(job, lib, st)
    rows = {r["code"]: r for r in f["rows"]}
    sew = rows["SEW"]
    assert sew["pct"] == D("25.0") and sew["qty"] == D(250)
    assert sew["budget"] == budget["SEW"]["total"]
    assert sew["projected"] == heavy.cents(sew["spent"] / D("0.25"))
    assert sew["earned_hours"] == (budget["SEW"]["hours"] *
                                   D("0.25")).quantize(D("0.01"))
    assert sew["productivity"] == (sew["earned_hours"] / 8).quantize(
        D("0.01"))
    assert sew["flag"] == (sew["variance"] > sew["budget"] * 5 / 100)
    # nothing installed yet: the budget stands; unbudgeted cost is flagged
    assert rows["MH"]["projected"] == D("20000.00") and \
        rows["MH"]["pct"] == D("0.0")
    assert rows["XTRA"]["flag"] and rows["XTRA"]["projected"] == \
        D("900.00")
    assert f["projected"] == sum(r["projected"] for r in f["rows"])
    out = heavy.export_forecast(job, lib, st, str(tmp_path / "f.csv"))
    assert list(csv.reader(open(out)))[0][0] == "Cost code"


def test_unedited_starter_rates_follow_a_new_starter(monkeypatch):
    """An install seeded with the old sample rates is offered the
    researched ones and gets them once accepted (never silently on launch:
    that re-priced open bids); a rate the estimator saved is left alone."""
    lib = heavy.library()
    old = dict(lib["equipment"]["EXC-20"], own_hr=48, op_hr=28)
    heavy.save_items("equipment", [old], note=heavy.STARTER_NOTE)
    mine = dict(lib["equipment"]["DOZ-D6"], own_hr=1.0)
    heavy.save_items("equipment", [mine], note="edited by Jon")
    assert heavy.library()["equipment"]["EXC-20"]["own_hr"] == 48
    assert heavy.apply_starter_updates() == 1
    lib = heavy.library()
    st = {r["code"]: r for r in heavy._starter()["equipment"]}
    assert lib["equipment"]["EXC-20"] == st["EXC-20"]
    assert lib["equipment"]["DOZ-D6"]["own_hr"] == 1.0


def test_pipe_production_slows_with_depth():
    d = fitz.open()
    d.new_page(width=1224, height=792)
    annotate.apply_op(d, annotate.new_op("set_scale", 0, ppu=18.0,
                                         unit="ft"))
    for i, g in enumerate(('8" PDG, 0-6 ft deep', '8" PDG, 10-14 ft deep',
                           '8" PDG, depth unknown', '24" ML, over 18 ft deep')):
        annotate.apply_op(d, annotate.new_op(
            "add_line", 0, pts=[[100, 100 + 40 * i], [200, 100 + 40 * i]],
            measure={"type": "length", "value": 100, "unit": "ft",
                     "group": g}))
    lib = heavy.library()
    job = heavy.blank()
    acts = {a["name"]: a for a in heavy.activities_from_takeoff(d, job, lib)}
    assert D(acts['8" PDG, 0-6 ft deep']["rate"]) == 35
    assert D(acts['8" PDG, 10-14 ft deep']["rate"]) == D("21")
    assert D(acts['8" PDG, depth unknown']["rate"]) == 28
    assert D(acts['24" ML, over 18 ft deep']["rate"]) == D("5.6")
    assert "x 0.6 for 10-14 ft deep" in acts['8" PDG, 10-14 ft deep']["notes"]
    # your own factors
    heavy.set_settings({"depth_factors": {"10-14": 0.5, "6-10": "junk"}})
    lib = heavy.library()
    assert heavy.depth_factors(lib)["10-14"] == 0.5
    assert heavy.depth_factors(lib)["6-10"] == 0.8      # bad value ignored
    job = heavy.blank()
    acts = {a["name"]: a for a in heavy.activities_from_takeoff(d, job, lib)}
    assert D(acts['8" PDG, 10-14 ft deep']["rate"]) == D("17.5")


def test_production_by_depth_window(qapp=None):
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from app import production_ui
    dlg = production_ui.DepthDialog()
    dlg.spins["10-14"].setValue(0.55)
    dlg.save()
    assert heavy.depth_factors(heavy.library())["10-14"] == 0.55
