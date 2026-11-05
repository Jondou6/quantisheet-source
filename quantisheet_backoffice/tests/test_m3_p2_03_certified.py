"""P2-03 certified payroll report and statement of compliance (3.1-3.2).
Back Office's own layout carrying what the federal weekly certified
payroll asks for; employee numbers only, never SSNs."""
import os

import pytest

from quantisheet_backoffice import cents, certified, payroll, store, timeentry

from .m3_helpers import WEEK, add_hr, approve_time

WE = "2026-10-25"
CREW = [("A. Brooks", "E301", "Carpenter", "8"),
        ("J. Park", "E302", "Carpenter", "8"),
        ("L. Nguyen", "E303", "Laborer", "8"),
        ("S. Okafor", "E304", "Laborer", "9")]


def _setup(office, job, park_det="52.40"):
    add_hr(office)
    office.act_as("admin@bo.test")
    timeentry.add_labor_class(office, "CARP", "Carpenter", "40.00", "0")
    office.act_as("hr@bo.test")
    for cls, base, fr in (("Carpenter", park_det, "21.10"),
                          ("Laborer", "38.75", "18.20")):
        payroll.add_rate(office, "prevailing", base, "2026-01-01",
                         job_id=job, determination_no="WD OR20260001",
                         classification=cls,
                         fringes=[{"name": "Health & pension",
                                   "amount": fr, "to": "plan"}])
    ids = []
    for name, no, cls, h in CREW:
        wid = timeentry.add_worker(office, name, "CARP", employee_no=no)
        payroll.pay_setup(office, wid, pay_rate="30.00", classification=cls)
        ids += [timeentry.add_line(office, wid, d, job, "03-3000", h)
                for d in WEEK]
    approve_time(office, ids)
    pid = payroll.add_period(office, "2026-10-19", WE, "2026-10-30")
    payroll.finalize(office, pid)
    certified.add_signer(office, "Ann Admin", "Owner")
    return pid


def test_3_1_totals_match_register_and_low_rate_blocks(office, job):
    pid = _setup(office, job, park_det="48.00")
    # the determination is modified afterwards (same effective date):
    # J. Park and A. Brooks were paid $48.00, now below the $52.40 rate
    payroll.add_rate(office, "prevailing", "52.40", "2026-01-01", job_id=job,
                     determination_no="WD OR20260001 mod 1",
                     classification="Carpenter",
                     fringes=[{"name": "Health & pension", "amount": "21.10",
                               "to": "plan"}])
    chk = certified.check(office, job, WE)
    assert len(chk["rows"]) == 4
    reg_job = sum(ln["gross"] for w in payroll.preview(office, pid)["workers"]
                  for ln in w["lines"] if ln["job_id"] == job)
    assert chk["totals"]["gross_project"] == reg_job
    assert chk["totals"]["hours"] == sum(cents.hours(h) * 5
                                         for *_, h in CREW)
    assert any(b.startswith("J. Park: paid $48.00/h, below the determination "
                            "rate $52.40/h") for b in chk["blocking"])
    with pytest.raises(certified.CertifiedError, match="J. Park"):
        certified.create(office, job, WE, signer="Ann Admin")


def test_3_1_four_workers_report(office, job):
    pid = _setup(office, job)
    rid = certified.create(office, job, WE, signer="Ann Admin", final=True)
    r = certified.report(office, rid)
    reg_job = sum(ln["gross"] for w in payroll.preview(office, pid)["workers"]
                  for ln in w["lines"] if ln["job_id"] == job)
    assert r["totals"]["gross_project"] == reg_job
    assert r["totals"]["workers"] == 4
    okafor = next(x for x in r["rows"] if x["name"] == "S. Okafor")
    assert [cents.hours_text(h) for h in okafor["days"]] == \
        ["9.00", "9.00", "9.00", "9.00", "4.00", "0.00", "0.00"]
    assert [cents.hours_text(h) for h in okafor["ot_days"]] == \
        ["0.00", "0.00", "0.00", "0.00", "5.00", "0.00", "0.00"]
    text = certified.pdf_text(r["file_path"])
    assert "Statement of Compliance" in text and "E304" in text
    assert "social security" not in text.lower()


def test_3_2_reprint_same_hash_and_revised_report(office, job):
    _setup(office, job)
    rid = certified.create(office, job, WE, signer="Ann Admin", final=True)
    r = certified.report(office, rid)
    certified.mark_submitted(office, rid)
    again = certified.reprint(office, rid)
    assert store.file_hash(again) == r["file_hash"]
    with pytest.raises(certified.CertifiedError, match="submitted"):
        certified.create(office, job, WE, signer="Ann Admin")
    new = certified.correct(office, rid, "fringe amount typo")
    n = certified.report(office, new)
    assert n["number"] != r["number"] and n["revision"] == 1
    assert n["payroll_no"] == r["payroll_no"] and n["status"] == "Revised"
    assert "revised" in certified.pdf_text(n["file_path"]).lower()
    assert os.path.isfile(r["file_path"])            # original kept
    assert certified.report(office, rid)["status"] == "Submitted"
