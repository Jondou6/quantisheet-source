"""Refrigerant log: 608 fields, annualizing leak rate, EPA thresholds."""
import datetime as dt
import os
from decimal import Decimal

import fitz
import pytest

from app.service import refrigerant
from r111_support import isolate, qapp, records, use_company  # noqa: F401


@pytest.fixture(autouse=True)
def svc_home(tmp_path, monkeypatch):
    return isolate(tmp_path, monkeypatch)


def test_the_regulation_is_cited_next_to_the_rate():
    src = open(refrigerant.__file__, encoding="utf-8").read()
    assert "40 CFR 82.152" in src
    assert "40 CFR 82.157" in src
    assert "annualizing" in src.lower()
    assert refrigerant.THRESHOLDS == {
        "industrial_process": Decimal("30"),
        "commercial_refrigeration": Decimal("20"),
        "comfort_cooling": Decimal("10"),
        "other": Decimal("10"),
    }
    assert refrigerant.REGULATORY_MIN_LBS == Decimal("50")


def _unit(store, rec, eq, charge, category, charge_date=""):
    return refrigerant.add_unit(store, rec, eq, "R-410A", charge, category,
                                charge_date=charge_date)


def test_annualizing_method_and_the_published_limits():
    rec, _p, eq = records()
    store = refrigerant.blank()
    when = dt.date(2026, 6, 1)
    uid = _unit(store, rec, eq, "100", "comfort_cooling")
    refrigerant.add_visit(store, uid, when, lbs_added="10", cylinder="CYL-1",
                          cert_no="608-100", tech="A Tester")
    info = refrigerant.leak_rate(store, uid)
    # no charge date: the period is 365 days, so the rate is not inflated
    assert info["days"] == 365
    assert info["rate"] == Decimal("10.00")
    assert info["over"] is False
    assert info["regulatory"] is True
    assert refrigerant.flag_text(info) == ""

    store2 = refrigerant.blank()
    uid = _unit(store2, rec, eq, "100", "comfort_cooling",
                charge_date=(when - dt.timedelta(days=100)).isoformat())
    refrigerant.add_visit(store2, uid, when, lbs_added="15", lbs_recovered="4",
                          cylinder="CYL-2", cert_no="608-100", tech="A Tester")
    info = refrigerant.leak_rate(store2, uid)
    # (15 / 100) * (365 / 100) * 100 = 54.75; recovered pounds stay out of it
    assert info["days"] == 100
    assert info["rate"] == Decimal("54.75")
    assert info["added"] == Decimal("15")
    assert info["over"] is True
    assert "54.75%" in refrigerant.flag_text(info)
    assert "comfort cooling" in refrigerant.flag_text(info)

    # a second addition uses the gap since the previous one, not the sum
    refrigerant.add_visit(store2, uid, when + dt.timedelta(days=100),
                          lbs_added="10", cylinder="CYL-2", cert_no="608-100")
    later = refrigerant.leak_rate(store2, uid)
    assert later["days"] == 100
    assert later["rate"] == Decimal("36.50")

    # the 365-day cap: a 400-day gap is annualized over 365
    store3 = refrigerant.blank()
    uid = _unit(store3, rec, eq, "100", "commercial_refrigeration",
                charge_date=(when - dt.timedelta(days=400)).isoformat())
    refrigerant.add_visit(store3, uid, when, lbs_added="20", cylinder="CYL-3",
                          cert_no="608-9")
    capped = refrigerant.leak_rate(store3, uid)
    assert capped["days"] == 365
    assert capped["rate"] == Decimal("20.00")
    assert capped["over"] is False
    refrigerant.add_visit(store3, uid, when + dt.timedelta(days=365),
                          lbs_added="21", cylinder="CYL-3", cert_no="608-9")
    # previous addition is 365 days back; 21% is over the 20% commercial limit
    over = refrigerant.leak_rate(store3, uid)
    assert over["rate"] == Decimal("21.00")
    assert over["over"] is True

    store4 = refrigerant.blank()
    uid = _unit(store4, rec, eq, "100", "industrial_process")
    refrigerant.add_visit(store4, uid, when, lbs_added="30", cylinder="CYL-4",
                          cert_no="608-1")
    assert refrigerant.leak_rate(store4, uid)["over"] is False
    store5 = refrigerant.blank()
    uid = _unit(store5, rec, eq, "10", "comfort_cooling")
    refrigerant.add_visit(store5, uid, when, lbs_added="2", cylinder="CYL-5",
                          cert_no="608-2")
    small = refrigerant.leak_rate(store5, uid)
    assert small["rate"] == Decimal("20.00")
    assert small["over"] is True
    assert small["regulatory"] is False
    assert "under 50 lb" in refrigerant.flag_text(small)
    assert refrigerant.flagged(store5)[0]["unit_id"] == uid


def test_cylinder_and_certificate_are_required_and_the_log_prints(
        tmp_path, monkeypatch):
    use_company(monkeypatch)
    rec, prop, eq = records()
    store = refrigerant.blank()
    uid = _unit(store, rec, eq, "80", "comfort_cooling")
    try:
        refrigerant.add_visit(store, uid, "2026-06-01", lbs_added="1")
        assert False, "a cylinder number is required"
    except refrigerant.RefError:
        pass
    try:
        refrigerant.add_visit(store, uid, "2026-06-01", lbs_recovered="1",
                              cylinder="CYL-9")
        assert False, "the 608 certificate number is required"
    except refrigerant.RefError:
        pass
    refrigerant.add_visit(store, uid, "2026-06-01", lbs_added="1.5",
                          lbs_recovered="0.25", cylinder="CYL-9",
                          cert_no="608-77", tech="A Tester")
    path = refrigerant.site_log_pdf(store, rec, prop, str(tmp_path / "log.pdf"))
    with fitz.open(path) as doc:
        text = doc[0].get_text()
    assert "Test Plumbing Co" in text
    assert "SN-TEST-1" in text
    assert "CYL-9" in text
    assert "608-77" in text
    assert "R-410A" in text
    other = service_other_site(rec)
    path2 = refrigerant.site_log_pdf(
        store, rec, other, str(tmp_path / "empty.pdf"))
    with fitz.open(path2) as doc:
        assert "No refrigerant records" in doc[0].get_text()


def service_other_site(rec):
    from app.estimating import service
    return service.add_property(rec, "Test other house", "2 Test St",
                                customer="Test Other")


def test_window_records_a_visit(qapp):
    from app.estimating import service
    from app.service.refrigerant_ui import RefrigerantWindow
    rec, _p, _eq = records()
    service.save(rec)
    win = RefrigerantWindow()
    assert win.unit.count() == 1
    win.gas.setText("R-410A")
    win.charge.setText("60")
    win.category.setCurrentIndex(win.category.findData("comfort_cooling"))
    win.charge_date.setText("2026-01-01")
    win.add_unit_clicked()
    assert "added" in win.msg.text().lower()
    win.added.setText("6")
    win.cylinder.setText("CYL-T")
    win.cert.setText("608-5")
    win.tech.setText("A Tester")
    win.when.setText("2026-06-01")
    win.add_visit_clicked()
    assert "Over the 10%" in win.table.item(0, 5).text()
    win.close()


def test_every_change_is_logged_and_corrections_keep_the_old_value():
    """Review 2 (Nov 4): refrigerant entries are compliance records."""
    import pytest
    from app.estimating import service
    from app.service import refrigerant as R
    recs = service.blank()
    pid = service.add_property(recs, "Example Clinic", "123 Example St")
    eid = service.add_equipment(recs, pid, "RTU", make="ExampleAir",
                                model="X1", serial="S1")
    st = R.blank()
    uid = R.add_unit(st, recs, eid, "R-410A", "60", "comfort_cooling",
                     "2026-01-10")
    vid = R.add_visit(st, uid, "2026-03-01", lbs_added="5", cylinder="C-1",
                      cert_no="608-0001", tech="A. Example")
    assert [h["action"] for h in R.history(st)] == ["add unit", "add visit"]
    with pytest.raises(R.RefError):
        R.correct_visit(st, vid, "lbs_added", "4", "  ")
    R.correct_visit(st, vid, "lbs_added", "4", "typed 5, scale read 4")
    log = R.history(st, vid)[-1]
    assert float(log["before"]["lbs_added"]) == 5     # stored as "5.000"
    assert log["why"] == "typed 5, scale read 4"
    assert next(v for v in st["visits"] if v["id"] == vid)["corrected"]
    assert "Not legal advice" in R.RULE_NOTE
