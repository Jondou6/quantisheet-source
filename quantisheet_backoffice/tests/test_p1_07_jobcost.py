"""P1-07 job costing (7.1-7.3)."""
import json
import os

from quantisheet_backoffice import ap, approvals, cents, jobcost, jobs, timeentry
from quantisheet_backoffice import interface

from .helpers import approve_ap as approve_ap_, import_stage

DATA = os.path.join(os.path.dirname(__file__), "data")


def seed_7_1(office, job, approve_ap=True):
    """Concrete 03-3000: 120 approved h x $58.00 loaded, $22,400.00 of
    approved AP, $1,850.00 of QuantiSheet direct costs."""
    timeentry.add_labor_class(office, "LAB", "Laborer", "50.00", "16")
    approvals.set_path(office, "time_line", [approvals.step("jobrole:PM")],
                       job_id=job)
    ids = []
    for n, name in enumerate(["W1", "W2", "W3"]):
        wid = timeentry.add_worker(office, name, "LAB")
        for d in ("2026-10-12", "2026-10-13", "2026-10-14", "2026-10-15",
                  "2026-10-16"):
            ids.append(timeentry.add_line(office, wid, d, job, "03-3000", "8"))
    timeentry.submit(office, ids)
    office.act_as("pm@bo.test")
    timeentry.decide(office, ids, "approve")
    office.act_as("ap@bo.test")
    v = ap.vendor_by_name(office, "Example Ready-Mix") or \
        {"id": ap.add_vendor(office, "Example Ready-Mix")}
    inv_ids = []
    for no, amt, d in (("RM-1", "14000.00", "2026-10-06"),
                       ("RM-2", "8400.00", "2026-10-13")):
        inv_ids.append(ap.create_invoice(
            office, v["id"], no, d, amt, job_id=job,
            lines=[{"cost_code": "03-3000", "category": "M", "amount": amt}]))
    if approve_ap:
        for i in inv_ids:
            approve_ap_(office, i)
    office.act_as("admin@bo.test")
    return inv_ids


def test_7_1_concrete_budget_vs_actual(office, job):
    seed_7_1(office, job)
    r = jobcost.by_code(office, job)["03-3000"]
    assert r["original"] == r["revised"] == 4_800_000
    assert r["labor"] == 696_000 and cents.hours_text(r["hours"]) == "120.00"
    assert r["ap"] == 2_240_000 and r["direct"] == 185_000
    assert cents.fmt(r["actual"]) == "$31,210.00"
    assert r["pct_spent"] == "65.0"
    assert cents.fmt(r["remaining"]) == "$16,790.00"
    assert r["labor_estimated"]
    assert {s["type"] for s in r["sources"]} == {"time_line", "ap_line",
                                                  "direct_cost"}


def test_7_2_pending_ap_not_in_actual(office, job):
    inv = seed_7_1(office, job, approve_ap=False)
    r = jobcost.by_code(office, job)["03-3000"]
    assert r["ap"] == 0 and r["actual"] == 696_000 + 185_000
    approve_ap_(office, inv[0])
    assert jobcost.by_code(office, job)["03-3000"]["ap"] == 1_400_000


def test_7_3_matches_quantisheet_cost_summary_golden(office):
    """Golden file produced once by QuantiSheet's own pm/cost.by_code on the
    fixture project (see tools/make_costsummary_golden.py in the patch);
    the snapshot is what app/backoffice_hook.py wrote for that project."""
    snap = interface.load_snapshot(os.path.join(DATA, "golden_snapshot.json"))
    r = jobs.import_snapshot(office, snap)
    golden = json.load(open(os.path.join(DATA, "golden_costsummary.json")))
    ours = jobcost.by_code(office, r.job_id)
    assert golden["rows"], "golden file is empty"
    for code, g in golden["rows"].items():
        o = ours[code]
        assert cents.text(o["revised"]) == g["revised"], code
        assert cents.text(o["committed"]) == g["committed"], code
        assert cents.text(o["actual"]) == g["actual"], code
