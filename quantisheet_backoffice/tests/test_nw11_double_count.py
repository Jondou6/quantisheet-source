"""PM review NW-11: a sub invoice entered as a QuantiSheet direct cost and
again in Back Office AP is counted once in job cost, and listed."""
from quantisheet_backoffice import cents, jobcost, jobs

from .helpers import ap_invoice, approve_ap


def test_same_invoice_counted_once(office, job):
    dcs = jobs.section(office, job, "direct_costs")
    assert dcs, "the test snapshot has direct costs"
    d = dcs[0]
    amt = cents.to_cents(d["amount"])
    before = jobcost.totals(office, job)
    iid = ap_invoice(office, d["vendor"], d["invoice"] or "X-1", d["date"],
                     cents.from_cents(amt), job_id=job,
                     code=d["cost_code"])
    approve_ap(office, iid)
    after = jobcost.totals(office, job)
    assert after["actual"] == before["actual"]          # not + amt again
    assert after["ap"] == before["ap"] + amt
    assert after["direct"] == before["direct"] - amt
    assert [x["direct_cost"] for x in after["duplicates"]] == [d["id"]]


def test_different_invoice_is_not_a_duplicate():
    ap = [{"id": 1, "number": "AP-1", "invoice_no": "INV-7", "vendor":
           "Example Sitework LLC", "invoice_date": "2026-12-01",
           "total": 21_000_000}]
    same = {"vendor": "example sitework, l.l.c.", "invoice": "inv 7",
            "amount": "1.00", "date": "2026-12-20"}
    assert jobcost.duplicate_of(same, ap)["id"] == 1
    other = dict(same, invoice="INV-8")
    assert jobcost.duplicate_of(other, ap) is None
    nonum = {"vendor": "Example Sitework", "invoice": "",
             "amount": "210000.00", "date": "2026-12-05"}
    assert jobcost.duplicate_of(nonum, ap)["id"] == 1
    late = dict(nonum, date="2027-01-20")
    assert jobcost.duplicate_of(late, ap) is None
