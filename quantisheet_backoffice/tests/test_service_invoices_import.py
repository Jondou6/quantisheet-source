"""Service desk invoices into Back Office (QuantiSheet 1.2, Nov 5): the
additive service_invoices section of the interface v1 snapshot. Each
invoice is posted once; a reversal voids it as its own ledger entry;
one whose lines don't add up is rejected at the door. Made-up data."""
from quantisheet_backoffice import billing, interface, jobs, ledger


def _inv(n, lines=(("Labor 2 h", "200.00"), ("Capacitor", "45.50")),
         total="245.50", **kw):
    return dict({"id": f"inv{n}", "number": f"INV-{n:04d}",
                 "date": "2026-11-03", "customer": "Test Smith",
                 "site": "1 Test Lane", "work_order": f"WO-{n:04d}",
                 "lines": [{"description": d, "qty": "1", "unit": "ea",
                            "price": a, "amount": a} for d, a in lines],
                 "total": total}, **kw)


def _snap(invoices):
    return {"interface_version": 1,
            "source": {"app": "QuantiSheet test", "file": "service work "
                       "orders", "folder": "", "taken_at": "2026-11-05T09:00"},
            "project": {"name": "Service Department", "number": "SERVICE",
                        "address": "", "owner": "", "contractor": "",
                        "architect": "", "contract_no": "",
                        "contract_date": "", "state": ""},
            "cost_codes": [], "budget": [], "estimate": [], "activities": [],
            "contract": {"retainage_work": "0", "retainage_stored": "0",
                         "sov": []},
            "changes": [], "payapps": [], "commitments": [],
            "direct_costs": [], "timecards": [], "directory": [],
            "daily_logs": [], "service_invoices": invoices}


def _bring(office, invoices, post=True):
    snap = interface.load_snapshot(_snap(invoices))
    job = jobs.import_snapshot(office, snap).job_id
    return snap, job, billing.import_service_invoices(office, job, post=post)


def test_posted_once_and_bad_totals_rejected(office):
    office.act_as("bill@bo.test")
    bad = _inv(2, total="999.00")
    snap, job, res = _bring(office, [_inv(1), bad])
    assert [r[0] for r in snap.rejected] == ["service_invoices"]
    assert "lines add to 245.50, invoice says 999.00" in snap.rejected[0][2]
    assert len(res["created"]) == 1 and res["posted"] == res["created"]
    inv = billing.invoice_by_number(office, "SVC-INV-0001")
    assert inv["status"] == "Approved" and inv["total"] == 24550
    assert inv["customer"] == "Test Smith"
    assert len(ledger.entries_for(office, "ar_invoice", inv["id"])) == 1
    # sent again (and again): nothing new
    _s, _j, again = _bring(office, [_inv(1)])
    assert again["created"] == [] and again["skipped"][0][1] == \
        "already in Back Office"


def test_reversal_is_its_own_entry(office):
    office.act_as("bill@bo.test")
    _s, job, _r = _bring(office, [_inv(3)])
    iid = billing.invoice_by_number(office, "SVC-INV-0003")["id"]
    rev = {"id": "inv3", "number": "INV-0003", "date": "2026-11-06",
           "reverse": True, "reason": "billed the wrong customer"}
    snap = interface.load_snapshot(_snap([_inv(3), rev]))
    assert not snap.rejected
    jobs.import_snapshot(office, snap)
    res = billing.import_service_invoices(office, job, post=True)
    assert res["reversed"] == [iid]
    assert billing.invoice(office, iid)["status"] == "Void"
    entries = ledger.entries_for(office, "ar_invoice", iid)
    assert len(entries) == 2                  # the original stays, plus one
    again = billing.import_service_invoices(office, job, post=True)
    assert again["reversed"] == [] and ("SVC-INV-0003", "already reversed") \
        in again["skipped"]
    # a reversal with no reason is refused at the door
    snap = interface.load_snapshot(_snap([dict(rev, reason="")]))
    assert snap.rejected and "needs a reason" in snap.rejected[0][2]


def test_draft_when_not_posting(office):
    office.act_as("bill@bo.test")
    _s, _j, res = _bring(office, [_inv(4)], post=False)
    inv = billing.invoice(office, res["created"][0])
    assert inv["status"] == "Draft" and res["posted"] == []


def test_open_billing_page_shows_the_imported_invoices(office, qapp):
    """Chief's re-test, Nov 7 (D8): the register stayed at 0 rows after
    an import until the page was reopened."""
    from quantisheet_backoffice.ui.main_window import BillingPage
    snap = interface.load_snapshot(_snap([_inv(1), _inv(2), _inv(3)]))
    job = jobs.import_snapshot(office, snap).job_id
    page = BillingPage(office)
    i = page.job.findData(job)
    assert i >= 0
    page.job.setCurrentIndex(i)
    before = page.register_table.rowCount()
    res = page.service_invoices(ask=lambda t: True)
    assert len(res["created"]) == 3
    assert page.register_table.rowCount() == before + 3
