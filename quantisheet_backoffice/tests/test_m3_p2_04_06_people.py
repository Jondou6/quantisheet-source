"""P2-04 employee records and onboarding (4.1-4.2), P2-05 certifications
(5.1) and P2-06 PTO (6.1)."""
import os

import pytest

from quantisheet_backoffice import (certs, hr, pto, security, timeentry)
from quantisheet_backoffice.security import Denied

from .m3_helpers import WEEK, add_hr, approve_time


@pytest.fixture
def hro(office):
    add_hr(office)
    office.act_as("hr@bo.test")
    return office


def _chen(o, **kw):
    return hr.add_employee(o, "M. Chen", "E101", "2026-03-02",
                           labor_class="LAB", ssn="900-00-1234",
                           dob="1990-04-12", bank_routing="999999999",
                           bank_account="000099996789", **kw)


def test_4_1_ssn_reveal_is_logged_billing_sees_mask(hro):
    eid = _chen(hro)
    raw = hro.db.get("employees", eid)
    assert raw["ssn"].startswith("enc1:") and "1234" not in raw["ssn"]
    assert raw["bank_account"].startswith("enc1:")
    e = hr.employee(hro, eid)
    assert e["ssn"] == "***-**-1234" and e["bank_account"] == "********6789"
    assert hr.reveal(hro, eid, "ssn") == "900-00-1234"
    (a,) = security.audit_rows(hro.db, action="reveal")
    assert a["user"] == "Hana Reyes" and "ssn" in a["after"]
    assert "900-00" not in (a["after"] or "") + (a["before"] or "")
    hro.act_as("bill@bo.test")
    assert hr.employee(hro, eid)["ssn"] == "***-**-1234"
    with pytest.raises(Denied):
        hr.reveal(hro, eid, "ssn")
    assert len(security.audit_rows(hro.db, action="reveal")) == 1
    assert security.audit_rows(hro.db, action="denied")[-1]["record_id"] == \
        str(eid)


def test_4_2_i9_retention_date(hro):
    assert hr.i9_retention("2026-03-02", "2027-01-15") == "2029-03-02"
    assert hr.i9_retention("2026-03-02", "2029-06-01") == "2030-06-01"
    assert hr.i9_retention("2026-03-02") is None
    eid = _chen(hro)
    hr.terminate(hro, eid, "2027-01-15")
    assert hro.db.get("employees", eid)["i9_retain_until"] == "2029-03-02"


def test_4_onboarding_packet_review(hro, tmp_path):
    eid = _chen(hro)
    pk = hr.add_packet(hro, "Field hire (English, OR)", role="Field",
                       language="en", location="OR")
    oid = hr.start_onboarding(hro, eid, pk)
    with pytest.raises(hr.HRError, match="Section 1"):
        hr.complete_item(hro, oid, "I-9 Section 2 (employer review)")
    form = tmp_path / "w4.pdf"
    form.write_bytes(b"%PDF-1.4 filled W-4")
    hr.complete_item(hro, oid, "W-4 federal withholding",
                     data={"filing_status": "single"},
                     document=str(form), form_edition="2026")
    for item in hr.packet(hro, pk)["items"][1:]:
        hr.complete_item(hro, oid, item)
    hr.submit_onboarding(hro, oid)
    with pytest.raises(hr.HRError, match="note"):
        hr.review_onboarding(hro, oid, "reject")
    hr.review_onboarding(hro, oid, "approve")
    assert hr.onboarding(hro, oid)["status"] == "Final"
    (doc,) = hr.documents(hro, eid)
    blob = open(doc["file_path"], "rb").read()
    assert b"W-4" not in blob                          # encrypted on disk
    assert hr.open_document(hro, doc["id"]) == b"%PDF-1.4 filled W-4"


def test_5_1_expiring_list_and_time_warning(hro, job):
    eid = hr.add_employee(hro, "J. Park", "E302", "2025-05-01",
                          labor_class="OPR")
    fk = certs.add_type(hro, "Forklift operator", renew_months=36)
    certs.add_cert(hro, eid, fk, number="FL-8812", issued="2023-11-10",
                   expires="2026-11-10")
    certs.require_for_job(hro, job, fk)
    soon = certs.expiring(hro, as_of="2026-10-22", days=30)
    assert [(c["employee"], c["type"], c["expires"]) for c in soon] == \
        [("J. Park", "Forklift operator", "2026-11-10")]
    wid = hr.employee(hro, eid)["worker_id"]
    ok = timeentry.add_line(hro, wid, "2026-11-09", job, "03-3000", "8")
    late = timeentry.add_line(hro, wid, "2026-11-12", job, "03-3000", "8")
    assert certs.time_warnings(hro, ok) == []
    assert certs.time_warnings(hro, late) == [
        "J. Park: Forklift operator expired 2026-11-10; job 2611 requires it"]
    with pytest.raises(certs.CertError, match="expired"):
        certs.assign_to_job(hro, eid, job, "2026-11-12")
    assert certs.assign_to_job(hro, eid, job, "2026-11-09") is None


def test_6_1_accrual_capped(hro, job):
    eid = hr.add_employee(hro, "R. Diaz", "E401", "2025-01-06",
                          labor_class="LAB")
    pol = pto.add_policy(hro, "Field PTO", per_hours="30", cap="40")
    pto.assign(hro, eid, pol)
    wid = hr.employee(hro, eid)["worker_id"]
    hro.act_as("admin@bo.test")
    ids = []
    d0 = "2025-01-06"
    from datetime import date, timedelta
    day = date.fromisoformat(d0)
    while len(ids) < 150:                       # 150 x 10 h = 1,500 h
        if day.weekday() < 5:
            ids.append(timeentry.add_line(hro, wid, day.isoformat(), job,
                                          "03-3000", "10"))
        day += timedelta(days=1)
    approve_time(hro, ids)
    hro.act_as("hr@bo.test")
    b = pto.balance(hro, eid, as_of="2026-10-22")
    assert (b["worked"], b["earned"], b["accrued"], b["used"],
            b["balance"]) == (150_000, 5_000, 4_000, 0, 4_000)
    assert b["text"] == "40.00 h (50.00 h earned, capped at 40.00 h)"


def test_6_request_approval_becomes_pto_time(hro, job):
    eid = hr.add_employee(hro, "R. Diaz", "E401", "2025-01-06",
                          labor_class="LAB")
    pol = pto.add_policy(hro, "Field PTO", per_hours="30", cap="40")
    pto.assign(hro, eid, pol)
    pto.adjust(hro, eid, "2026-10-01", "16", "opening balance")
    rid = pto.request(hro, eid, "2026-10-26", "2026-10-27", "8")
    with pytest.raises(pto.PTOError, match="balance"):
        pto.request(hro, eid, "2026-11-02", "2026-11-04", "8")
    lines = pto.decide(hro, rid, "approve")
    rows = [hro.db.get("time_lines", i) for i in lines]
    assert [(r["date"], r["pay_type"], r["hours"], r["status"])
            for r in rows] == [("2026-10-26", "PTO", 800, "Approved"),
                               ("2026-10-27", "PTO", 800, "Approved")]
    assert pto.balance(hro, eid, as_of="2026-10-31")["balance"] == 0


def test_6_pto_approval_refused_inside_final_payroll(hro, job):
    from quantisheet_backoffice import payroll
    eid = hr.add_employee(hro, "R. Diaz", "E401", "2025-01-06",
                          labor_class="LAB")
    pol = pto.add_policy(hro, "Field PTO", per_hours="30", cap="40")
    pto.assign(hro, eid, pol)
    pto.adjust(hro, eid, "2026-10-01", "16", "opening balance")
    rid = pto.request(hro, eid, "2026-10-20", "2026-10-20", "8")
    pid = payroll.add_period(hro, "2026-10-19", "2026-10-25", "2026-10-30")
    payroll.finalize(hro, pid)
    with pytest.raises(pto.PTOError, match="final"):
        pto.decide(hro, rid, "approve")
    assert hro.db.rows("SELECT * FROM time_lines WHERE pay_type = 'PTO'") == []
