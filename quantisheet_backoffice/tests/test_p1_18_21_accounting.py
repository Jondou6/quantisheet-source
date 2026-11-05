"""Addendum Phase 1: P1-18 chart of accounts (18.1-18.3), P1-19 journal
and trial balance (19.1-19.4), P1-20 AP aging and bill payments
(20.1-20.3), P1-21 period close (21.1-21.3)."""
import os

import pytest

from quantisheet_backoffice import (ap, appay, billing, cents, ledger, payments,
                                    security)
from quantisheet_backoffice.security import Denied

from .helpers import ap_invoice, approve_ap

SYSTEM = ("Accounts receivable", "Accounts payable", "Retainage receivable",
          "Retainage payable", "Sales tax payable", "Undeposited funds",
          "Opening balance equity", "Retained earnings")


def test_18_1_default_chart_and_system_accounts(office):
    accts = ledger.accounts(office)
    assert 35 <= len(accts) <= 50
    names = {a["name"]: a for a in accts}
    for n in SYSTEM + ("Operating bank", "Credit card", "Use tax payable",
                       "Contract revenue", "T&M revenue",
                       "Costs and estimated earnings in excess of billings",
                       "Billings in excess of costs and estimated earnings",
                       "Job cost - Labor", "Job cost - Material",
                       "Job cost - Equipment", "Job cost - Subcontract",
                       "Job cost - Other"):
        assert n in names, n
    for n in SYSTEM:
        a = names[n]
        assert a["system"] == 1
        with pytest.raises(ledger.LedgerError):
            ledger.delete_account(office, a["id"])
        with pytest.raises(ledger.LedgerError):
            ledger.change_account(office, a["id"], type="expense")
        with pytest.raises(ledger.LedgerError):
            ledger.change_account(office, a["id"], active=0)
        assert ledger.account(office, a["id"])["active"] == 1


def test_18_2_posted_account_cannot_delete_inactive_keeps_history(office):
    a = ledger.add_account(office, "6150", "Small tools", "expense")
    ledger.post(office, "2026-10-05", [
        {"account": a, "debit": 12_500},
        {"account": "1000", "credit": 12_500}], "test", 1, "tools")
    with pytest.raises(ledger.LedgerError, match="has posted lines"):
        ledger.delete_account(office, a)
    ledger.change_account(office, a, active=0)
    assert a not in [p["id"] for p in ledger.picker(office)]
    tb = ledger.trial_balance(office, "2026-10-31")
    assert any(r["account_id"] == a and r["debit"] == 12_500
               for r in tb["rows"])
    assert [r["debit"] for r in ledger.general_ledger(office, a)] == [12_500]


def test_18_3_import_chart_csv_rejects_two(office):
    before = office.db.row_counts()
    rows = ["number,name,type"]
    for i in range(10):
        rows.append(f"71{i:02d},Imported account {i},expense")
    rows.insert(4, "7200,Bad type,Assets!!")
    rows.insert(8, "1000,Duplicate bank,asset")
    text = "\n".join(rows) + "\n"
    assert len(rows) - 1 == 12
    r = ledger.import_chart_csv(office, text)
    assert len(r["imported"]) == 10
    reasons = [why for _row, why in r["rejected"]]
    assert reasons == ["type 'Assets!!' is not an account type",
                       "account number 1000 already exists"]
    after = office.db.row_counts()
    assert after["accounts"] - before["accounts"] == 10
    assert ledger.account_by_number(office, "1000")["name"] == "Operating bank"


def _inv1001(office, job3):
    billing.set_contract(office, job3)
    office.db.set_counter("INV", 999)
    for n in (1, 2):
        billing.approve(office, billing.invoice_from_payapp(office, job3, n))
    iid = billing.invoice_from_payapp(office, job3, 3)
    billing.approve(office, iid)
    return iid


def _lines(office, eid):
    out = []
    for ln in ledger.entry(office, eid)["lines"]:
        a = ledger.account(office, ln["account_id"])
        out.append((a["name"], ln["debit"], ln["credit"]))
    return sorted(out)


def test_19_1_invoice_posts_ar_retainage_revenue(office, job3):
    iid = _inv1001(office, job3)
    (e,) = ledger.entries_for(office, "ar_invoice", iid)
    assert _lines(office, e["id"]) == sorted([
        ("Accounts receivable", 6_750_000, 0),
        ("Retainage receivable", 750_000, 0),
        ("Contract revenue", 0, 7_500_000)])


def _apex_30k(office, job):
    ap.seed_vendors(office, job)
    apex = ap.vendor_by_name(office, "Example Framing")
    office.db.conn.execute("UPDATE snap_records SET data = replace(data, "
                           "'2026-09-30', '2027-09-30') WHERE section = "
                           "'commitments'")
    office.db.conn.commit()
    ap.update_vendor(office, apex["id"], insurance_expires="2027-09-30")
    iid = ap_invoice(office, "Example Framing", "AF-1030", "2026-10-15",
                     "30000.00", job_id=job, code="06-1000", cat="S",
                     commitment_no="SC-004")
    # the fixture already has $96,000.00 invoiced on the $120,000.00
    # commitment, so this bill is $6,000.00 over: Admin signs off last
    approve_ap(office, iid, override_reason="CO-007 pending with Apex")
    return apex, iid


def test_19_2_ap_invoice_posting(office, job):
    apex, iid = _apex_30k(office, job)
    (e,) = ledger.entries_for(office, "ap_invoice", iid)
    assert _lines(office, e["id"]) == sorted([
        ("Job cost - Subcontract", 3_000_000, 0),
        ("Accounts payable", 0, 2_700_000),
        ("Retainage payable", 0, 300_000)])
    cost = [ln for ln in e["lines"] if ln["debit"]][0]
    assert cost["job_id"] == job and cost["cost_code"] == "06-1000" and \
        cost["category"] == "S"


def test_19_3_payment_and_trial_balance(office, job3):
    iid = _inv1001(office, job3)
    cust = billing.invoice(office, iid)["customer"]
    # the two earlier invoices' own AR is cleared first so AR shows only 1001
    for n in (1, 2):
        p = office.db.one("SELECT * FROM ar_invoices WHERE payapp_no = ?", (n,))
        payments.receive(office, cust, "2026-10-01",
                         cents.from_cents(p["total"]),
                         applications=[(p["id"], cents.from_cents(p["total"]))])
    pid = payments.receive(office, cust, "2026-11-02", "60000.00",
                           applications=[(iid, "60000.00")])["payment_id"]
    (e,) = ledger.entries_for(office, "payment", pid)
    assert _lines(office, e["id"]) == sorted([
        ("Undeposited funds", 6_000_000, 0),
        ("Accounts receivable", 0, 6_000_000)])
    tb = ledger.trial_balance(office)
    assert tb["debits"] == tb["credits"]
    assert ledger.balance(office, "Accounts receivable") == 750_000


def test_19_4_void_reverses_and_unbalanced_refused(office, job3):
    iid = _inv1001(office, job3)
    (orig,) = ledger.entries_for(office, "ar_invoice", iid)
    billing.void(office, iid, "2026-10-25", "Wrong period")
    es = ledger.entries_for(office, "ar_invoice", iid)
    assert len(es) == 2 and es[0]["id"] == orig["id"]
    rev = es[1]
    assert rev["date"] == "2026-10-25" and rev["reverses_id"] == orig["id"]
    assert sorted((l["account_id"], l["debit"], l["credit"]) for l in
                  rev["lines"]) == sorted((l["account_id"], l["credit"],
                                           l["debit"]) for l in orig["lines"])
    n_entries = office.db.scalar("SELECT COUNT(*) FROM journal_entries")
    n_lines = office.db.scalar("SELECT COUNT(*) FROM journal_lines")
    with pytest.raises(ledger.LedgerError, match=r"differ by \$0\.01"):
        ledger.post(office, "2026-10-26", [
            {"account": "1000", "debit": 10_001},
            {"account": "4000", "credit": 10_000}], "test hook", 99)
    assert office.db.scalar("SELECT COUNT(*) FROM journal_entries") == n_entries
    assert office.db.scalar("SELECT COUNT(*) FROM journal_lines") == n_lines
    log = security.audit_rows(office.db)
    assert any(r["action"] == "post refused" and r["record_type"] ==
               "test hook" for r in log)


def _bill(office, vendor, number, amount, due, job):
    iid = ap_invoice(office, vendor, f"V-{number}", "2026-06-01", amount,
                     job_id=job, due_date=due)
    approve_ap(office, iid)
    office.db.update("ap_invoices", iid, number=number)
    return iid


def test_20_1_ap_aging(office, job):
    _bill(office, "Example Ready-Mix", "AP-0007", "8640.00", "2026-11-11", job)
    _bill(office, "Example Lumber", "AP-0009", "312.47", "2026-10-21", job)
    _bill(office, "Example Lumber", "AP-0010", "4200.00", "2026-09-20", job)
    _bill(office, "Example Electric Supply", "AP-0012", "1150.00",
          "2026-07-15", job)
    ag = appay.aging(office, "2026-10-31")
    assert ag["totals"] == {"current": 864_000, "1-30": 31_247,
                            "31-60": 420_000, "61-90": 0, "over 90": 115_000}
    assert ag["total"] == 1_430_247
    days = {r["number"]: r["days"] for r in ag["rows"]}
    assert days == {"AP-0007": 0, "AP-0009": 10, "AP-0010": 41,
                    "AP-0012": 108}


def test_20_2_check_to_apex(office, job, tmp_path):
    apex, iid = _apex_30k(office, job)
    files_before = sorted(os.listdir(office.folder))
    office.act_as("ap@bo.test")
    pid = appay.pay(office, apex["id"], "2026-10-30", [(iid, "27000.00")],
                    method="check", reference="5012")
    assert ap.invoice(office, iid)["status"] == "Paid"
    (e,) = ledger.entries_for(office, "bill_payment", pid)
    assert _lines(office, e["id"]) == sorted([
        ("Accounts payable", 2_700_000, 0),
        ("Operating bank", 0, 2_700_000)])
    assert appay.open_retainage(office, iid) == 300_000
    assert ledger.balance(office, "Retainage payable") == 300_000
    assert sorted(os.listdir(office.folder)) == files_before


def test_20_3_partial_payment(office, job):
    apex, iid = _apex_30k(office, job)
    office.act_as("ap@bo.test")
    appay.pay(office, apex["id"], "2026-10-30", [(iid, "10000.00")],
              reference="5013")
    inv = ap.invoice(office, iid)
    assert inv["status"] == "Partly paid"
    assert appay.open_bill(office, iid) == 1_700_000
    row = [r for r in appay.aging(office, inv["due_date"])["rows"]
           if r["number"] == inv["number"]][0]
    assert row["bucket"] == "current" and row["open"] == 1_700_000


def test_21_1_closed_period_refuses_approval(office, job):
    office.act_as("ctl@bo.test")
    ledger.close_books(office, "2026-09-30")
    iid = ap_invoice(office, "Example Lumber", "HL-50", "2026-09-28", "640.00",
                     job_id=job)
    with pytest.raises(ledger.ClosedPeriodError) as e:
        approve_ap(office, iid)
    assert str(e.value) == "Books are closed through 2026-09-30"
    assert ap.invoice(office, iid)["status"] == "In Approval"
    approve_ap(office, iid, gl_date="2026-10-01")
    inv = ap.invoice(office, iid)
    assert inv["status"] == "Approved" and inv["invoice_date"] == "2026-09-28"
    (e2,) = ledger.entries_for(office, "ap_invoice", iid)
    assert e2["date"] == "2026-10-01"


def test_21_2_void_after_close_posts_in_october(office, job):
    iid = billing.create_other_invoice(office, job, "2026-09-15", [
        {"description": "Extra work", "amount": "2400.00"}], customer="Owner")
    billing.approve(office, iid)
    before = ledger.trial_balance(office, "2026-09-30")
    office.act_as("ctl@bo.test")
    ledger.close_books(office, "2026-09-30")
    office.act_as("admin@bo.test")
    billing.void(office, iid, "2026-10-22", "Duplicate")
    rev = ledger.entries_for(office, "ar_invoice", iid)[-1]
    assert rev["date"] == "2026-10-22"
    after = ledger.trial_balance(office, "2026-09-30")
    assert (after["debits"], after["credits"], after["rows"]) == \
        (before["debits"], before["credits"], before["rows"])
    # a void dated inside the closed month lands on the first open day
    j2 = billing.create_other_invoice(office, job, "2026-10-02", [
        {"description": "More", "amount": "100.00"}], customer="Owner")
    billing.approve(office, j2)
    office.db.update("ar_invoices", j2, gl_date="2026-10-02")
    assert ledger.first_open_date(office, "2026-09-29") == "2026-10-01"


def test_21_3_reopen_rules_and_audit(office):
    office.act_as("ctl@bo.test")
    ledger.close_books(office, "2026-09-30")
    with pytest.raises(Denied):
        ledger.reopen_books(office, "fix a bill")
    office.act_as("admin@bo.test")
    with pytest.raises(ledger.LedgerError):
        ledger.reopen_books(office, "")
    ledger.reopen_books(office, "Late vendor bill for September")
    assert ledger.closed_through(office) is None
    acts = [r["action"] for r in security.audit_rows(office.db)]
    assert "close books" in acts and "reopen books" in acts
    assert security.verify_chain(office.db)["ok"]
