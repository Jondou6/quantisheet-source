"""1.2 phase 6: the changeout proposal (#11) and the outside load report
(#12: takeoff inputs out, the designer's report in - QuantiSheet doesn't
calculate loads). Made-up data only."""
import csv
import datetime as dt
import os

import pytest

from app import settings  # noqa: F401
from app.estimating import service
from app.service import (agreements, changeout, gbb, history, loadcalc,
                         permits, pricebook, warranty, workorder)
from r111_support import isolate, qapp, records  # noqa: F401


@pytest.fixture(autouse=True)
def svc_home(tmp_path, monkeypatch):
    return isolate(tmp_path, monkeypatch)


def _takeoff():
    """Takeoff items the way annotate.takeoff_items gives them."""
    def it(t, v, u, label, mult=1):
        return {"type": t, "value": v, "unit": u, "label": label,
                "multiplier": mult}
    return [it("area", 700, "SF", "Office Suite"),
            it("area", 250, "SF", "Break Room"),
            it("area", 60, "SF", "Office Suite window S"),
            it("area", 30, "SF", "Office Suite window west"),
            it("area", 21, "SF", "Office Suite door N"),
            it("area", 24, "SF", "Break Room window"),
            it("length", 70, "LF", "Office Suite exterior wall"),
            it("length", 12, "LF", "Office Suite exterior wall", 2),
            it("length", 40, "LF", "Corridor exterior wall"),  # no room
            it("area", 5, "m2", "Server Closet"),         # not feet units
            it("count", 6, "EA", "Office Suite light")]


def _pdf(tmp_path, name="designer.pdf"):
    import fitz
    p = tmp_path / name
    with fitz.open() as d:
        d.new_page().insert_text((72, 72), "Made-up designer report")
        d.save(str(p))
    return str(p)


# ---- #12 outside load report ----------------------------------------------

def test_rooms_from_the_takeoff_are_measured():
    rooms = {r["name"]: r for r in loadcalc.from_takeoff(_takeoff())}
    assert set(rooms) == {"Office Suite", "Break Room"}
    o = rooms["Office Suite"]
    assert o["floor_sf"] == {"value": 700.0, "source": "measured"}
    assert o["ext_wall_lf"] == {"value": 94.0, "source": "measured"}
    assert o["windows"]["S"]["value"] == 60 and \
        o["windows"]["W"]["value"] == 30
    assert o["doors"]["N"] == {"value": 21.0, "source": "measured"}
    assert o["ceiling_ft"]["source"] == "missing"
    assert rooms["Break Room"]["windows"]["unknown"]["value"] == 24


def test_typed_values_are_entered_and_takeoff_wins_on_merge():
    typed = [loadcalc.room("Office Suite", floor_sf=650, ceiling_ft=9,
                           wall_height_ft=10),
             loadcalc.room("Lobby", floor_sf=300)]
    assert typed[0]["floor_sf"]["source"] == "entered"
    got = {r["name"]: r for r in loadcalc.merge_rooms(
        typed, loadcalc.from_takeoff(_takeoff()))}
    assert got["Office Suite"]["floor_sf"]["source"] == "measured"
    assert got["Office Suite"]["ceiling_ft"] == {"value": 9.0,
                                                 "source": "entered"}
    assert set(got) == {"Office Suite", "Lobby", "Break Room"}
    with pytest.raises(loadcalc.LoadReportError):
        loadcalc.room("")
    with pytest.raises(loadcalc.LoadReportError):
        loadcalc.room("X", floor_sf="lots")
    with pytest.raises(loadcalc.LoadReportError):
        loadcalc.room("X", windows={"NE": 10})


def test_exports_label_measured_entered_missing(tmp_path):
    st = loadcalc.blank()
    rooms = loadcalc.merge_rooms(
        [loadcalc.room("Office Suite", ceiling_ft=9)],
        loadcalc.from_takeoff(_takeoff()))
    rid = loadcalc.add(st, "Test Smith", "Test office", rooms,
                       when="2026-11-06")
    job = loadcalc.get(st, rid)
    assert job["number"] == "LR-0001"
    gaps = loadcalc.missing(job)
    assert ("Break Room", "Ceiling height") in gaps
    assert ("Office Suite", "Ceiling height") not in gaps
    c = loadcalc.export_csv(job, str(tmp_path / "in.csv"))
    with open(c, encoding="utf-8") as fh:
        rows = list(csv.reader(fh))
    head = rows[2]
    office = next(r for r in rows if r and r[0] == "Office Suite")
    assert office[head.index("Floor area (SF)")] == "700"
    assert office[head.index("Floor area source")] == "measured"
    assert office[head.index("Ceiling height source")] == "entered"
    brk = next(r for r in rows if r and r[0] == "Break Room")
    assert brk[head.index("Ceiling height source")] == "missing"
    p = loadcalc.export_pdf(job, str(tmp_path / "in.pdf"))
    import fitz
    with fitz.open(p) as d:
        text = "".join(pg.get_text() for pg in d)
    assert "measured" in text and "Still missing" in text
    assert "doesn't calculate loads" in text
    assert [e["kind"] for e in job["exports"]] == ["csv", "pdf"]


def test_attach_the_designers_report(tmp_path):
    st = loadcalc.blank()
    rid = loadcalc.add(st, "Test Smith", "Test office",
                       loadcalc.from_takeoff(_takeoff()))
    job = loadcalc.get(st, rid)
    assert loadcalc.status(job) == "No load report attached."
    bad = tmp_path / "notes.pdf"
    bad.write_text("not a pdf")
    with pytest.raises(loadcalc.LoadReportError):
        loadcalc.attach_report(st, rid, str(bad), "Test Designer",
                               "2026-11-10")
    src = _pdf(tmp_path)
    with pytest.raises(loadcalc.LoadReportError):
        loadcalc.attach_report(st, rid, src, "", "2026-11-10")
    with pytest.raises(loadcalc.LoadReportError):
        loadcalc.attach_report(st, rid, src, "Test Designer", "2026-11-10",
                               cooling_btuh="lots")
    r = loadcalc.attach_report(st, rid, src, "Test Designer", "2026-11-10",
                               heating_btuh="61,000", cooling_btuh="88000",
                               recommended="7.5-ton RTU, gas heat")
    assert os.path.isfile(r["file"]) and os.path.isfile(src)  # copy kept
    assert r["file"] != src and r["original"] == "designer.pdf"
    s = loadcalc.status(job)
    assert "Test Designer, 2026-11-10" in s and "88,000" in s and \
        "7.5-ton RTU" in s


def test_no_sizing_math_and_no_trademarked_names():
    """Jon, Nov 4: no in-house load calcs. Nothing a user sees names the
    industry's trademarked load/duct procedures."""
    import inspect
    from app.service import changeout_ui, loadcalc_ui
    for mod in (loadcalc, loadcalc_ui, changeout, changeout_ui):
        src = inspect.getsource(mod)
        for word in ("12000", "tons_needed", "nominal(", "size_flag",
                     "BTU/h per", "sensible"):
            assert word not in src, (mod.__name__, word)
    import ast
    for mod in (loadcalc, loadcalc_ui, changeout, changeout_ui):
        tree = ast.parse(inspect.getsource(mod))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value,
                                                             str):
                low = node.value.lower()
                if node.value in loadcalc.BANNED:
                    continue                    # the list of banned names
                for word in loadcalc.BANNED:
                    if len(word) > 4:
                        assert word not in low, (mod.__name__, node.value)


# ---- #11 changeout proposal ------------------------------------------------

def _book():
    b = pricebook.blank()
    good = pricebook.add_task(b, "7.5-ton RTU changeout, standard",
                              "18400.00", "", hours="16", labor_cost="40",
                              tier="Good")
    better = pricebook.add_task(b, "7.5-ton RTU changeout, high efficiency",
                                "21200.00", "", hours="16", labor_cost="40",
                                tier="Better")
    best = pricebook.add_task(b, "7.5-ton RTU changeout, variable speed",
                              "25900.00", "", hours="18", labor_cost="40",
                              tier="Best")
    return b, good, better, best


EQ = {"Good": {"brand": "Goodman", "model": "TEST-G90", "tons": "7.5",
               "efficiency": "13.4 IEER", "warranty": "5 yr parts"},
      "Better": {"brand": "Daikin", "model": "TEST-D90", "tons": "7.5",
                 "efficiency": "15 IEER", "warranty": "5 yr parts"},
      "Best": {"brand": "Rheem", "model": "TEST-R90", "tons": "7.5",
               "efficiency": "17 IEER", "warranty": "5 yr parts"}}


def _proposal(tmp_path, report=True, **kw):
    rec, prop, old = records()
    b, good, better, best = _book()
    jobs = loadcalc.blank()
    rid = loadcalc.add(jobs, "Test Smith", "Test Smith house",
                       loadcalc.from_takeoff(_takeoff()), property_id=prop)
    if report:
        loadcalc.attach_report(jobs, rid, _pdf(tmp_path), "Test Designer",
                               "2026-11-10", "61000", "88000",
                               "7.5-ton RTU")
    agr = agreements.blank()
    agreements.add(agr, "Test Smith", "300", 2, "2027-06-01",
                   site="Test Smith house")
    quotes = gbb.blank()
    args = dict(permit_fee="450", duct_changes="New supply plenum and "
                "transition", duct_price="1200")
    args.update(kw)
    qid = changeout.create(quotes, b, "Test Smith", "Test Smith house",
                           {"Good": [good], "Better": [better],
                            "Best": [best]}, EQ, records=rec,
                           equipment_id=old,
                           load_job=loadcalc.get(jobs, rid), agreements=agr,
                           when="2026-11-06", **args)
    return rec, prop, old, quotes, qid


def test_proposal_lines_permit_fee_and_ducts(tmp_path):
    rec, prop, old, quotes, qid = _proposal(tmp_path)
    q = gbb.get(quotes, qid)
    co = q["changeout"]
    assert q["kind"] == "changeout" and q["property_id"] == prop
    assert co["existing"]["equipment_id"] == old
    # member price on the equipment (10% off); fee and ducts at full price
    assert [c["total"] for c in q["choices"]] == [
        "18210.00", "20730.00", "24960.00"]
    names = [x["name"] for x in q["choices"][0]["lines"]]
    assert names[1:] == ["Permit and inspection fees",
                         "Duct changes: New supply plenum and transition"]
    assert co["permit_needed"] is True and co["permit_fee"] == "450.00"
    assert co["load_report"]["attached"] and \
        changeout.load_warning(q) == ""
    with pytest.raises(changeout.ChangeoutError):
        _proposal(tmp_path, duct_changes="", duct_price="300")
    with pytest.raises(changeout.ChangeoutError):
        _proposal(tmp_path, permit_fee="-5")


def test_no_load_report_is_a_warning_not_a_block(tmp_path):
    rec, prop, old, quotes, qid = _proposal(tmp_path, report=False)
    assert "No load report attached" in changeout.load_warning(
        gbb.get(quotes, qid))
    q2 = gbb.blank()
    b, good, better, best = _book()
    i = changeout.create(q2, b, "Test Lee", "Lee shop", {"Good": [good]},
                         {"Good": EQ["Good"]}, existing="Old RTU",
                         permit_required=False, permit_fee="450")
    co = gbb.get(q2, i)["changeout"]
    assert co["permit_needed"] is False and co["permit_fee"] == ""
    assert co["load_report"] is None


def test_proposal_needs_equipment_and_the_old_unit():
    b, good, better, best = _book()
    quotes = gbb.blank()
    with pytest.raises(changeout.ChangeoutError):
        changeout.create(quotes, b, "Test Smith", "Site", {"Good": [good]},
                         {"Good": {"brand": "Goodman"}}, existing="Old AC")
    with pytest.raises(changeout.ChangeoutError):
        changeout.create(quotes, b, "Test Smith", "Site", {"Good": [good]},
                         {"Good": EQ["Good"]})
    with pytest.raises(changeout.ChangeoutError):
        changeout.create(quotes, b, "Test Smith", "Site", {"Good": [good]},
                         {"Good": dict(EQ["Good"], tons="big")},
                         existing="Old AC")
    assert quotes["quotes"] == []


def test_signed_proposal_opens_a_work_order_with_the_permit(tmp_path):
    rec, prop, old, quotes, qid = _proposal(tmp_path)
    orders = workorder.blank()
    wo_id = changeout.accept(quotes, qid, "Better", orders, rec,
                             signed_by="Test Smith", when="2026-11-06")
    wo = workorder.get(orders, wo_id)
    assert wo["billing"] == "flat" and wo["flat_price"] == "20730.00"
    assert wo["changeout"]["equipment"]["model"] == "TEST-D90"
    assert wo["permit"]["job_type"] == "hvac_changeout" and \
        wo["permit"]["needed"]
    assert "no permit number" in permits.close_warning(wo)
    with pytest.raises(changeout.ChangeoutError):
        changeout.accept(quotes, qid, "Good", orders, rec,
                         signed_by="Test Smith")


def test_install_adds_the_unit_and_starts_the_warranty_clock(tmp_path):
    rec, prop, old, quotes, qid = _proposal(tmp_path)
    wst = warranty.blank()
    with pytest.raises(changeout.ChangeoutError):        # not signed yet
        changeout.install(quotes, qid, rec, wst, "2026-11-20")
    orders = workorder.blank()
    changeout.accept(quotes, qid, "Good", orders, rec,
                     signed_by="Test Smith", when="2026-11-06")
    eid = changeout.install(quotes, qid, rec, wst, "2026-11-20",
                            serial="SN-NEW-1")
    eq = service.find(rec, eid)
    assert (eq["make"], eq["model"], eq["serial"], eq["installed"]) == (
        "Goodman", "TEST-G90", "SN-NEW-1", "2026-11-20")
    assert service.find(rec, old)["replaced"] == "2026-11-20"
    u = warranty.entry(wst, eid)
    assert (u["brand"], u["register_by"], u["verified"]) == (
        "Goodman", "2027-01-19", True)
    with pytest.raises(changeout.ChangeoutError):
        changeout.install(quotes, qid, rec, wst, "2026-11-21")


def test_proposal_pdf_and_history(tmp_path):
    rec, prop, old, quotes, qid = _proposal(tmp_path)
    out = tmp_path / "p.pdf"
    changeout.proposal_pdf(gbb.get(quotes, qid), str(out))
    import fitz
    with fitz.open(str(out)) as d:
        text = "".join(p.get_text() for p in d)
    for s in ("TEST-D90", "Load report by Test Designer", "88,000",
              "Permit and inspection fees", "Duct changes", "registration",
              "$24,960.00"):
        assert s in text, s
    low = text.lower()
    for word in loadcalc.BANNED:
        assert word not in low
    gbb.save(quotes)
    service.save(rec)
    h = history.history(property_id=prop)
    assert [q["number"] for q in h["quotes"]] == ["Q-0001"]


# ---- windows ---------------------------------------------------------------

def test_phase6_windows(qapp, tmp_path):  # noqa: F811
    from app.service import changeout_ui, loadcalc_ui
    lw = loadcalc_ui.LoadReportWindow(today=dt.date(2026, 11, 6))
    lw.customer.setText("Test Smith")
    lw.site.setText("Test office")
    assert lw.takeoff_clicked() is None              # no drawing open
    assert len(lw.takeoff_clicked(items=_takeoff())) == 2
    rows = lw.room_rows()
    assert rows[0]["floor_sf"]["source"] == "measured"
    lw.rooms.item(0, 2).setText("9")                 # ceiling, typed
    lw.rooms.item(0, 1).setText("710")               # override measured
    rows = lw.room_rows()
    assert rows[0]["ceiling_ft"] == {"value": 9.0, "source": "entered"}
    assert rows[0]["floor_sf"]["source"] == "entered"
    assert lw.pdf_clicked(path=str(tmp_path / "in.pdf"))
    assert lw.csv_clicked(path=str(tmp_path / "in.csv"))
    lw.designer.setText("Test Designer")
    lw.cool.setText("88000")
    lw.rec.setText("7.5-ton RTU")
    assert lw.attach_clicked(path=_pdf(tmp_path))
    assert "Load report attached" in lw.msg.text()
    lw.close()

    rec, prop, old = records()
    service.save(rec)
    b, good, better, best = _book()
    pricebook.save(b)
    w = changeout_ui.ChangeoutWindow(today=dt.date(2026, 11, 6))
    w.site.setCurrentIndex(w.site.findData(prop))
    w.unit.setCurrentIndex(w.unit.findData(old))
    assert "No load report" in w.size_lbl.text() or w.calc.count() == 2
    w.calc.setCurrentIndex(1)
    assert "Load report attached" in w.size_lbl.text()
    for k, v in EQ["Good"].items():
        w.eq["Good"][k].setText(v)
    w.lists["Good"].item(0).setSelected(True)
    w.permit_fee.setText("450")
    w.duct.setText("New transition")
    w.duct_price.setText("600")
    assert w.save_clicked()
    q = gbb.load()["quotes"][0]
    assert q["choices"][0]["total"] == "19450.00"   # 18400 + 450 + 600
    w.table.selectRow(0)
    assert w.print_clicked(path=str(tmp_path / "p.pdf"))
    w.signer.setText("Test Smith")
    assert w.accept_clicked()
    w.table.selectRow(0)
    w.installed.setText("2026-11-20")
    assert w.install_clicked()
    assert "Register with Goodman by 2027-01-19" in w.msg.text()
    w.close()
