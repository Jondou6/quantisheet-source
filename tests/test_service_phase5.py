"""1.2 phase 5 (Nov 5): good / better / best quotes as records (#6), the
tune-up planner (#7), warranty registrations (#9 / QW4), permits and
inspections (#10 / QW5), agreement auto-renew and the member discount.
Made-up data only."""
import datetime as dt

import pytest

from app import settings
from app.estimating import service
from app.service import (agreements, gbb, history, permits, planner,
                         pricebook, warranty, workorder)
from r111_support import isolate, qapp, records  # noqa: F401


@pytest.fixture(autouse=True)
def svc_home(tmp_path, monkeypatch):
    return isolate(tmp_path, monkeypatch)


def _book():
    b = pricebook.blank()
    good = pricebook.add_task(b, "Clean and check", "189.00", "",
                              hours="1", labor_cost="40", tier="Good")
    better = pricebook.add_task(b, "Replace capacitor", "265.00", "240.00",
                                hours="1", labor_cost="40", tier="Better",
                                parts=[{"desc": "Capacitor", "qty": "1",
                                        "cost": "18.00"}])
    best = pricebook.add_task(b, "Hard start kit", "120.00", "",
                              hours="0.5", labor_cost="40", tier="Best")
    return b, good, better, best


# ---- agreement defaults ----------------------------------------------------

def test_member_price_defaults_to_ten_percent_off():
    b, good, better, best = _book()
    assert pricebook.get(b, good)["member_price"] == "170.10"
    assert pricebook.get(b, better)["member_price"] == "240.00"  # as given
    settings.set("service_member_discount_pct", 15)
    t = pricebook.add_task(b, "Drain flush", "100", "")
    assert pricebook.get(b, t)["member_price"] == "85.00"


def test_agreement_defaults_and_auto_renew():
    d = agreements.defaults()
    assert d == {"visits": 2, "discount_pct": 10, "auto_renew": True}
    st = agreements.blank()
    a = agreements.add(st, "Test Jones", "300", 2, "2026-10-01",
                       site="Test Jones house")
    b = agreements.add(st, "Test Lee", "300", 2, "2026-10-01",
                       site="Test Lee house", auto_renew=False)
    assert agreements.renew_due(st, "2026-09-30") == []
    assert agreements.renew_due(st, "2027-10-02") == ["SA-0001"]
    agr = agreements.get(st, a)
    assert (agr["start"], agr["renewal"]) == ("2027-10-01", "2028-10-01")
    assert len(agr["renewals"]) == 2                    # two years caught up
    assert agreements.renew_due(st, "2027-10-02") == []
    assert agreements.get(st, b)["renewal"] == "2026-10-01"
    settings.set("service_agreement_auto_renew", False)
    assert agreements.defaults()["auto_renew"] is False


# ---- #6 good / better / best -----------------------------------------------

def test_quote_member_prices_from_an_active_agreement():
    b, good, better, best = _book()
    agr = agreements.blank()
    agreements.add(agr, "Test Smith", "300", 2, "2027-06-01",
                   site="Test Smith house")
    st = gbb.blank()
    qid = gbb.create(st, b, "Test Smith", "Test Smith house",
                     {"Good": [good], "Better": [good, better],
                      "Best": [good, better, best]}, agreements=agr,
                     when="2026-11-05")
    q = gbb.get(st, qid)
    assert q["number"] == "Q-0001" and q["member"] and \
        q["agreement"] == "SA-0001"
    assert [c["total"] for c in q["choices"]] == ["170.10", "410.10",
                                                  "518.10"]
    other = gbb.create(st, b, "Test Nobody", "Elsewhere",
                       {"Good": [good]}, agreements=agr, when="2026-11-05")
    assert gbb.get(st, other)["choices"][0]["total"] == "189.00"
    # a pricebook change later doesn't move the quote
    pricebook.get(b, good)["customer_price"] = "999.00"
    assert gbb.get(st, qid)["choices"][0]["total"] == "170.10"


def test_signed_choice_becomes_a_flat_rate_work_order():
    b, good, better, best = _book()
    st = gbb.blank()
    orders = workorder.blank()
    qid = gbb.create(st, b, "Test Smith", "Test Smith house",
                     {"Good": [good], "Better": [good, better]},
                     member=False, when="2026-11-05")
    with pytest.raises(gbb.QuoteRecordError):
        gbb.accept(st, qid, "Better", orders, signed_by="")
    with pytest.raises(gbb.QuoteRecordError):
        gbb.accept(st, qid, "Best", orders, signed_by="Test Smith")
    wo_id = gbb.accept(st, qid, "Better", orders, signed_by="Test Smith",
                       when="2026-11-06")
    wo = workorder.get(orders, wo_id)
    assert wo["billing"] == "flat" and wo["flat_price"] == "454.00"
    assert wo["book"]["hours"] == "2.00" and wo["book"]["parts"][0][
        "desc"] == "Capacitor"
    assert wo["quote_id"] == qid and "Q-0001 Better" in wo["complaint"]
    q = gbb.get(st, qid)
    assert (q["status"], q["chosen"], q["work_order"]) == (
        "accepted", "Better", "WO-0001")
    with pytest.raises(gbb.QuoteRecordError):
        gbb.accept(st, qid, "Good", orders, signed_by="Test Smith")
    # flat-rate ticket closes and invoices at the signed price
    workorder.add_time(orders, wo_id, "A Tester", "2", when="2026-11-07")
    workorder.no_parts(orders, wo_id)
    inv = workorder.close_and_invoice(orders, wo_id, notes="Done.",
                                      when="2026-11-07")
    assert inv["total"] == "454.00"


def test_decline_print_and_history(tmp_path):
    b, good, better, best = _book()
    st = gbb.blank()
    with pytest.raises(gbb.QuoteRecordError):
        gbb.create(st, b, "Test Smith", "Site", {})
    qid = gbb.create(st, b, "Test Smith", "Test Smith house",
                     {"Good": [good], "Best": [best]}, member=False,
                     when="2026-11-05")
    gbb.decline(st, qid, "Getting other prices", when="2026-11-06")
    assert "declined: Getting other prices" in gbb.summary(
        gbb.get(st, qid))
    oq = gbb.option_quote(gbb.get(st, qid))
    assert oq is not None
    out = tmp_path / "q.pdf"
    gbb.save_pdf(gbb.get(st, qid), str(out))
    assert out.stat().st_size > 500
    gbb.save(st)
    h = history.history(customer="Test Smith")
    assert [q["number"] for q in h["quotes"]] == ["Q-0001"]
    assert any(e[1] == "Quote" for e in h["events"])


# ---- #9 warranty -----------------------------------------------------------

def test_warranty_windows_and_countdown():
    st = warranty.blank()
    u = warranty.set_unit(st, "e1", "Goodman", installed="2026-11-01",
                          unit_text="Test AC 1")
    assert (u["window_days"], u["register_by"], u["verified"]) == (
        60, "2026-12-31", True)
    r = warranty.set_unit(st, "e2", "Ruud", installed="2026-11-01")
    assert r["verified"] is False
    h = warranty.set_unit(st, "e3", "Rheem", installed="2026-11-01",
                          line="90-day lines (UNVERIFIED which)")
    assert h["window_days"] == 90 and h["verified"] is False
    warranty.set_unit(st, "e4", "Daikin", installed="", unit_text="No date")
    warranty.set_unit(st, "e5", "Lennox", installed="2026-08-01",
                      commercial=True)
    rows = warranty.due(st, "2026-11-05")
    by = {r[4]: r for r in rows}
    assert "56 days left" in by["e1"][2] and not by["e1"][3]
    assert "UNVERIFIED" in by["e2"][2]
    assert by["e4"][0] == "" and "Install date needed" in by["e4"][2]
    assert by["e5"][3] and "closed on 2026-09-30" in by["e5"][2]
    assert rows[-1][4] == "e4"                     # no date sorts last
    warranty.mark_registered(st, "e1", "2026-11-05", "CONF-TEST")
    assert "e1" not in {r[4] for r in warranty.due(st, "2026-11-05")}


def test_rule_change_keeps_units_already_tracked():
    st = warranty.blank()
    warranty.set_unit(st, "e1", "Goodman", installed="2026-11-01")
    rules = warranty.rules()
    rules["Goodman"]["days"] = 30
    warranty.save_rules(rules)
    assert warranty.window("Goodman")[0] == 30
    assert warranty.set_unit(st, "e1", "Goodman",
                             installed="2026-11-01")["window_days"] == 60
    assert warranty.set_unit(st, "e1", "Goodman", installed="2026-11-01",
                             reapply=True)["window_days"] == 30
    with pytest.raises(warranty.WarrantyError):
        warranty.save_rules({"Goodman": {"days": "x"}})
    assert warranty.window("NoSuchBrand")[0] == 60


def test_warranty_from_records_and_billing_warning():
    rec, prop, eq = records()
    gm = service.add_equipment(rec, prop, "Heat pump", make="goodman",
                               model="TEST-HP", installed="2026-10-20",
                               warranty_months=120)
    am = service.add_equipment(rec, prop, "AC", make="American Standard",
                               installed="2026-10-20")
    assert warranty.brand_of("goodman") == "Goodman"
    assert warranty.brand_of("Bryant") == "Carrier / Bryant"
    assert warranty.brand_of("TestCo") == "TestCo"
    st = warranty.blank()
    done = warranty.sync_from_records(st, rec, ids={gm, am})
    assert set(done) == {gm, am}
    assert warranty.entry(st, gm)["register_by"] == "2026-12-19"
    assert warranty.entry(st, am)["brand"] == "Trane / American Standard"
    orders = workorder.blank()
    w = workorder.add(orders, rec, property_id=prop, equipment_id=gm,
                      complaint="No cool", when="2026-11-05")
    assert "under warranty" in warranty.billing_warning(
        workorder.get(orders, w), rec, "2026-11-05")
    w2 = workorder.add(orders, rec, property_id=prop, equipment_id=eq,
                       complaint="No heat", when="2026-11-05")
    assert warranty.billing_warning(workorder.get(orders, w2), rec,
                                    "2026-11-05") == ""      # expired


# ---- #10 permits -----------------------------------------------------------

def test_which_jobs_need_a_permit():
    assert permits.needs_permit("hvac_changeout")
    assert permits.needs_permit("gas_line")
    assert permits.needs_permit("backflow_install")
    assert not permits.needs_permit("water_heater")
    assert not permits.needs_permit("repipe")
    settings.set("service_permit_types", ["water_heater"])
    assert permits.needs_permit("water_heater")
    assert not permits.needs_permit("gas_line")


def test_permit_flow_and_close_warning():
    orders = workorder.blank()
    w = workorder.add(orders, customer="Test Smith", site="Test Smith house",
                      complaint="Changeout", when="2026-11-05")
    with pytest.raises(permits.PermitError):
        permits.set_permit(orders, w, job_type="hvac_changeout")
    p = permits.set_permit(orders, w, job_type="hvac_changeout",
                           jurisdiction="myrtle_beach")
    wo = workorder.get(orders, w)
    assert p["needed"] and "no permit number" in permits.close_warning(wo)
    permits.set_permit(orders, w, number="TEST-123")
    permits.add_inspection(orders, w, "rough", "2026-11-06", "passed")
    permits.add_inspection(orders, w, "final", "2026-11-09", "scheduled")
    msg = permits.close_warning(wo)
    assert "final inspection hasn't passed" in msg and "4:00 PM" in msg
    assert permits.open_permits(orders)[0][0] == "WO-0001"
    permits.add_inspection(orders, w, "final", "2026-11-10", "passed")
    assert permits.close_warning(wo) == ""
    assert permits.open_permits(orders) == []
    w2 = workorder.add(orders, customer="Test Smith",
                       site="Test Smith house", complaint="Gas line",
                       when="2026-11-12")
    assert permits.remembered(orders, workorder.get(orders, w2)) == \
        "myrtle_beach"
    w3 = workorder.add(orders, customer="Test Lee", site="Lee house",
                       complaint="Water heater", when="2026-11-12")
    p3 = permits.set_permit(orders, w3, job_type="water_heater")
    assert not p3["needed"] and permits.close_warning(
        workorder.get(orders, w3)) == ""
    for k, o in permits.OFFICES.items():
        assert o["name"] and "unverified" in o, k


# ---- #7 tune-up planner ----------------------------------------------------

def _agreements(n):
    st = agreements.blank()
    for i in range(n):
        agreements.add(st, f"Test Customer {i:02d}", "300", 2,
                       "2028-03-15", site=f"Test site {i:02d}",
                       start="2027-03-15")
    return st


def test_plan_spreads_visits_over_workdays_by_tech():
    st = _agreements(10)
    orders = workorder.blank()
    start, end = planner.season_dates("spring", 2027)
    assert (start, end) == (dt.date(2027, 3, 1), dt.date(2027, 5, 31))
    rows = planner.plan(st, orders, ["Tech A", "Tech B"], start, end,
                        today="2027-02-01", cap=2)
    assert len(rows) == 10
    days = {}
    for r in rows:
        assert dt.date.fromisoformat(r["date"]).weekday() < 5
        days[(r["date"], r["tech"])] = days.get((r["date"], r["tech"]),
                                                0) + 1
    assert max(days.values()) <= 2
    assert {r["tech"] for r in rows} == {"Tech A", "Tech B"}
    assert sum(planner.weekly_load(rows).values()) == 10
    with pytest.raises(planner.PlanError):
        planner.plan(st, orders, [" "], start, end, today="2027-02-01")
    with pytest.raises(planner.PlanError):
        planner.plan(st, orders, ["Tech A"], dt.date(2027, 3, 15),
                     dt.date(2027, 3, 16), today="2027-02-01", cap=1)
    settings.set("service_season_spring", "04-01..04-30")
    assert planner.season_dates("spring", 2027)[0] == dt.date(2027, 4, 1)
    settings.set("service_season_spring", "bad")
    with pytest.raises(planner.PlanError):
        planner.season_dates("spring", 2027)


def test_plan_makes_work_orders_once_and_an_ics(tmp_path):
    st = _agreements(3)
    orders = workorder.blank()
    start, end = dt.date(2027, 3, 1), dt.date(2027, 5, 31)
    rows = planner.plan(st, orders, ["Tech A"], start, end,
                        today="2027-02-01")
    ids = planner.make_work_orders(st, orders, rows, today="2027-02-01")
    assert len(ids) == 3
    wo = workorder.get(orders, ids[0])
    assert (wo["call_type"], wo["billing"], wo["tech"]) == (
        "pm", "agreement", "Tech A")
    assert planner.make_work_orders(st, orders, rows,
                                    today="2027-02-01") == []
    assert planner.plan(st, orders, ["Tech A"], start, end,
                        today="2027-02-01") == []      # all have WOs now
    rows[0]["customer"] = "Test, Comma; Semi"
    text = planner.ics(rows)
    assert text.startswith("BEGIN:VCALENDAR\r\n") and \
        text.count("BEGIN:VEVENT") == 3
    assert "Test\\, Comma\\; Semi" in text
    out = planner.save_ics(rows, str(tmp_path / "t.ics"))
    with open(out, encoding="utf-8", newline="") as f:
        assert f.read() == text
    assert min(r["date"] for r in rows) >= "2027-03-15"   # term start


# ---- windows ---------------------------------------------------------------

def test_phase5_windows(qapp, tmp_path):  # noqa: F811
    from app.service import gbb_ui, permit_ui, planner_ui, warranty_ui
    from app.service import workorder_ui
    b, good, better, best = _book()
    pricebook.save(b)
    w = gbb_ui.QuotesWindow()
    w.customer.setText("Test Smith")
    w.site.setText("Test Smith house")
    w.lists["Good"].item(0).setSelected(True)
    qid = w.save_clicked()
    assert qid and w.table.rowCount() == 1
    w.table.selectRow(0)
    w.signer.setText("Test Smith")
    assert w.accept_clicked()
    assert workorder.load()["orders"][0]["billing"] == "flat"
    w.close()

    agreements.save(_agreements(2))
    p = planner_ui.PlannerWindow(today=dt.date(2027, 2, 1))
    p.techs.setText("Tech A")
    assert len(p.plan_clicked()) == 2
    assert p.ics_clicked(path=str(tmp_path / "plan.ics"))
    p.close()

    rec, prop, eq = records()
    service.add_equipment(rec, prop, "AC", make="Goodman",
                          installed="2026-11-01")
    service.save(rec)
    ww = warranty_ui.WarrantyWindow(today=dt.date(2026, 11, 5))
    ww.sync_clicked()
    assert ww.table.rowCount() == 2               # TestCo + Goodman
    ww.close()

    orders = workorder.load()
    wid = orders["orders"][0]["id"]
    d = permit_ui.PermitDialog(orders, wid)
    d.job.setCurrentIndex(d.job.findData("gas_line"))
    d.office.setCurrentIndex(d.office.findData("conway"))
    assert "BS&A" in d.info.text()
    d.number.setText("TEST-9")
    assert d.save_clicked()
    workorder.save(orders)
    d.close()

    wo_w = workorder_ui.WorkOrderWindow()
    wo_w.table.selectRow(0)
    asked = []
    wo_w.close_clicked(ask=lambda t: asked.append(t) or False)
    assert asked and "final inspection" in asked[0]
    assert "Not closed" in wo_w.msg.text()
    assert workorder.load()["orders"][0]["status"] == "open"
    wo_w.close()
