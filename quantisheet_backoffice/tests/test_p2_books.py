"""Addendum Phase 2, books: P2-14 statements and job P&L (14.1-14.4),
P2-15 sales and use tax (15.1-15.3), P2-16 1099 totals (16.1-16.2),
P2-18 manual journal entries (18.1-18.2), P2-19 dashboard (19.1-19.2)."""
import csv
from datetime import date, timedelta

import pytest

from quantisheet_backoffice import (ap, appay, billing, cents, ledger,
                                    payments, reports, security, tax, ten99)
from quantisheet_backoffice.security import Denied

from .helpers import ap_invoice, approve_ap
from .test_p1_07_jobcost import seed_7_1
from .test_p1_10_13_billing import seed_tm
from .test_p2_banking import _recon_setup


@pytest.fixture
def full(office):
    office.set_company(accounting_mode="full")
    return office


def _month_ends(year):
    for m in range(1, 13):
        nxt = date(year + (m == 12), m % 12 + 1, 1)
        yield (nxt - timedelta(days=1)).isoformat()


def test_14_1_balance_sheet_balances_every_month_end(full, job3, tmp_path):
    _recon_setup(full, job3, tmp_path)
    ledger.post_manual(full, "2026-03-31", [
        {"account": "6000", "debit": 250_000},
        {"account": "2800", "credit": 250_000}], "March rent accrual")
    ledger.post_manual(full, "2025-12-31", [
        {"account": "6050", "debit": 99_999},
        {"account": "3100", "credit": 99_999}], "prior-year fees")
    seen_current = False
    for d in _month_ends(2026):
        bs = reports.balance_sheet(full, d)
        assert bs["balances"], d
        assert bs["total_assets"] == bs["total_liabilities"] + \
            bs["total_equity"], d
        names = [r["name"] for r in bs["sections"]["equity"]]
        assert "Current-year earnings" in names
        seen_current |= any(r["name"] == "Current-year earnings" and
                            r["amount"] for r in bs["sections"]["equity"])
    assert seen_current


def _inv1001(office, job3):
    billing.set_contract(office, job3)
    office.db.set_counter("INV", 999)
    for n in (1, 2):
        billing.approve(office, billing.invoice_from_payapp(office, job3, n))
    iid = billing.invoice_from_payapp(office, job3, 3)
    billing.approve(office, iid)
    return iid


def test_14_2_accrual_vs_cash(full, job3):
    iid = _inv1001(full, job3)
    assert billing.invoice(full, iid)["invoice_date"] == "2026-10-31"
    cust = billing.invoice(full, iid)["customer"]
    payments.receive(full, cust, "2026-11-02", "60000.00",
                     applications=[(iid, "60000.00")])
    oct_a = reports.profit_and_loss(full, "2026-10-01", "2026-10-31")
    assert oct_a["revenue"] == 7_500_000
    oct_c = reports.profit_and_loss(full, "2026-10-01", "2026-10-31", "cash")
    nov_c = reports.profit_and_loss(full, "2026-11-01", "2026-11-30", "cash")
    assert oct_c["revenue"] == 0
    assert nov_c["revenue"] == 6_000_000
    assert [r["name"] for r in nov_c["sections"]["income"]] == \
        ["Contract revenue"]


def test_14_3_job_pl_october(full, job3):
    seed_7_1(full, job3)
    _inv1001(full, job3)
    j = reports.job_pl(full, job3, "2026-10-01", "2026-10-31")
    assert j["revenue"] == 7_500_000
    assert j["job_cost"] == 3_121_000
    assert j["gross_profit"] == 4_379_000
    assert j["margin"] == "58.4"


def test_14_4_cash_flow_equals_change_in_bank(full, job3, tmp_path):
    _recon_setup(full, job3, tmp_path)
    ledger.post_manual(full, "2026-11-10", [
        {"account": "1500", "debit": 1_800_000},
        {"account": "2700", "credit": 1_800_000}], "truck on loan")
    for a, b in (("2026-10-01", "2026-10-31"), ("2026-11-01", "2026-11-30"),
                 ("2026-01-01", "2026-12-31"), ("2026-09-01", "2026-11-15")):
        cf = reports.cash_flow(full, a, b)
        assert cf["net_change"] == cf["cash_end"] - cf["cash_begin"], (a, b)
        assert cf["net_change"] == cf["net_operating"] + \
            cf["net_investing"] + cf["net_financing"]
    nov = reports.cash_flow(full, "2026-11-01", "2026-11-30")
    assert any(r["name"] == "Equipment and vehicles" for r in nov["investing"])
    assert any(r["name"] == "Equipment loans" for r in nov["financing"])


def test_15_1_tm_invoice_sales_tax(office, job):
    seed_tm(office, job)
    tid = tax.add_code(office, "OR-METRO", "Metro County", "8.25")
    billing.set_contract(office, job, material_markup="15", sub_markup="10",
                         tax_code_id=tid, tax_flags={"material": True,
                                                     "markup": True,
                                                     "labor": False})
    iid = billing.create_tm_invoice(office, job, "2026-10-20", "2026-10-20")
    inv = billing.invoice(office, iid)
    assert inv["tax"] == 11_765                 # 8.25% of $1,426.00, half up
    billing.approve(office, iid)
    (e,) = ledger.entries_for(office, "ar_invoice", iid)
    st = [l for l in e["lines"] if ledger.account(office, l["account_id"])
          ["name"] == "Sales tax payable"]
    assert [(l["debit"], l["credit"]) for l in st] == [(0, 11_765)]
    assert tax.CPA_NOTE.startswith("Construction tax treatment differs")


def test_15_2_use_tax_on_untaxed_bill(office, job):
    tid = tax.add_code(office, "OR-USE", "Metro County", "6.00", kind="use")
    iid = ap_invoice(office, "Example Lumber", "HL-500", "2026-10-21", "500.00",
                     job_id=job, use_tax_code=tid)
    approve_ap(office, iid)
    (e,) = ledger.entries_for(office, "ap_invoice", iid)
    named = sorted((ledger.account(office, l["account_id"])["name"],
                    l["debit"], l["credit"]) for l in e["lines"])
    assert ("Use tax payable", 0, 3_000) in named
    assert ("Job cost - Material", 3_000, 0) in named
    assert sum(l["debit"] for l in e["lines"]) == \
        sum(l["credit"] for l in e["lines"])
    rep = tax.liability(office, "2026-10-01", "2026-10-31")
    assert [(r["code"], r["tax"]) for r in rep] == [("OR-USE", 3_000)]


def test_15_3_liability_equals_postings_payment_clears(office, job, tmp_path):
    seed_tm(office, job)
    sid = tax.add_code(office, "OR-METRO", "Metro County", "8.25")
    uid = tax.add_code(office, "OR-USE", "Metro County", "6.00", kind="use")
    billing.set_contract(office, job, material_markup="15", tax_code_id=sid,
                         tax_flags={"material": True, "markup": True})
    billing.approve(office, billing.create_tm_invoice(
        office, job, "2026-10-20", "2026-10-20"))
    approve_ap(office, ap_invoice(office, "Example Lumber", "HL-501",
                                  "2026-10-21", "500.00", job_id=job,
                                  use_tax_code=uid))
    rep = tax.liability(office, "2026-10-01", "2026-10-31")
    posted = ledger.balance(office, "2200") + ledger.balance(office, "2210")
    assert sum(r["due"] for r in rep) == posted == 11_765 + 3_000
    files0 = sorted(p.name for p in tmp_path.iterdir())
    for r in rep:
        tax.record_payment(office, r["code_id"], r["due"], "2026-11-15",
                           reference="paid online by the user")
    rep2 = tax.liability(office, "2026-10-01", "2026-11-30")
    assert all(r["due"] == 0 for r in rep2)
    assert ledger.balance(office, "2200") == ledger.balance(office, "2210") == 0
    assert sorted(p.name for p in tmp_path.iterdir()) == files0


def _pay(office, vendor, amount, method, ref, job):
    v = ap.vendor_by_name(office, vendor)
    if v is None:
        vid = ap.add_vendor(office, vendor, is_1099=1)
    else:
        vid = v["id"]
    iid = ap_invoice(office, vendor, f"{ref}-B", "2026-03-02", amount,
                     job_id=job)
    approve_ap(office, iid)
    who = office.user
    office.act_as("ap@bo.test")
    appay.pay(office, vid, "2026-03-20", [(iid, amount)], method=method,
              reference=ref)
    office.act_as(who["id"])
    return vid


def test_16_1_threshold_and_card_excluded(office, job):
    office.act_as("admin@bo.test")
    a = _pay(office, "Example Concrete Finishing", "2400.00", "check", "6001", job)
    b = _pay(office, "Example Drywall", "1999.99", "check", "6002", job)
    c = _pay(office, "Example Rentals", "5000.00", "card", "6003", job)
    t = ten99.totals(office, 2026)
    assert t["threshold"] == 200_000
    assert [(r["vendor"], r["total"]) for r in t["listed"]] == \
        [("Example Concrete Finishing", 240_000)]
    assert [r["vendor"] for r in t["below"]] == ["Example Drywall"]
    assert [(r["vendor"], r["note"]) for r in t["excluded"]] == \
        [("Example Rentals", "paid by card")]
    assert ten99.threshold(office, 2025) == 60_000
    assert "IRS" in t["note"]


def test_16_2_missing_w9_masked_tin_controlled_export(office, job, tmp_path):
    office.act_as("admin@bo.test")
    vid = _pay(office, "Example Concrete Finishing", "2400.00", "check", "6001",
               job)
    ap.update_vendor(office, vid, tax_id="00-0003456", w9=0)
    miss = ten99.missing_w9(office, 2026)
    assert [r["vendor"] for r in miss] == ["Example Concrete Finishing"]
    assert miss[0]["tin"] == "*****3456"
    office.act_as("ap@bo.test")
    with pytest.raises(Denied):
        ten99.export_csv(office, 2026, str(tmp_path / "x.csv"), full_tins=True)
    office.act_as("ctl@bo.test")
    p = ten99.export_csv(office, 2026, str(tmp_path / "1099.csv"),
                         full_tins=True)
    rows = list(csv.reader(open(p, encoding="utf-8")))
    assert rows[1][:2] == ["Example Concrete Finishing", "00-0003456"]
    log = security.audit_rows(office.db)
    assert any(r["action"] == "export 1099" for r in log)
    assert any(r["action"] == "denied" for r in log)


def test_18_1_unbalanced_and_control_accounts(full):
    full.act_as("ctl@bo.test")
    with pytest.raises(ledger.LedgerError, match=r"differ by \$0\.01"):
        ledger.post_manual(full, "2026-10-31", [
            {"account": "6000", "debit": 100_000},
            {"account": "2800", "credit": 99_999}], "bad")
    for acct in ("1100", "2000"):
        with pytest.raises(ledger.LedgerError, match="use an invoice or bill"):
            ledger.post_manual(full, "2026-10-31", [
                {"account": acct, "debit": 100},
                {"account": "6000", "credit": 100}], "no")
    full.act_as("ap@bo.test")
    with pytest.raises(Denied):
        ledger.post_manual(full, "2026-10-31", [
            {"account": "6000", "debit": 100},
            {"account": "2800", "credit": 100}], "clerk")


def test_18_2_accrual_auto_reverses(full):
    full.act_as("ctl@bo.test")
    eid = ledger.post_manual(full, "2026-10-31", [
        {"account": "6050", "debit": 450_000},
        {"account": "2800", "credit": 450_000}], "Audit fee accrual",
        auto_reverse=True)
    e = ledger.entry(full, eid)
    rev = ledger.entry(full, e["reversed_by_id"])
    assert rev["date"] == "2026-11-01" and rev["reverses_id"] == eid
    assert ledger.balance(full, "2800", "2026-10-31") == 450_000
    assert ledger.balance(full, "2800", "2026-11-01") == 0
    posts = [r for r in security.audit_rows(full.db) if r["action"] == "post"]
    assert {str(eid), str(rev["id"])} <= {str(r["record_id"]) for r in posts}


def _opex_month(office, d, amt):
    ledger.post_manual(office, d, [{"account": "6000", "debit": amt},
                                   {"account": "2800", "credit": amt}],
                       "rent accrual")


def test_19_1_cash_coverage(full):
    ledger.post(full, "2026-06-30", [{"account": "1000", "debit": 9_000_000},
                                     {"account": "3100", "credit": 9_000_000}],
                "opening", 1, "owner money")
    for d, amt in (("2026-07-31", 3_000_000), ("2026-08-31", 3_600_000),
                   ("2026-09-30", 4_200_000)):
        _opex_month(full, d, amt)
    dash = reports.dashboard(full, "2026-07-01", "2026-09-30")
    assert dash["cash"]["cash_on_hand"] == 9_000_000
    assert dash["cash"]["avg_monthly_opex"] == 3_600_000
    assert dash["cash"]["coverage_months"] == "2.5"


def test_19_2_panels_equal_statements_for_any_range(full, job3, tmp_path):
    _recon_setup(full, job3, tmp_path)
    _opex_month(full, "2026-10-15", 123_456)
    for a, b in (("2026-10-01", "2026-10-31"), ("2026-11-01", "2026-11-30"),
                 ("2026-09-01", "2026-12-31")):
        dash = reports.dashboard(full, a, b)
        pl = reports.profit_and_loss(full, a, b)
        cf = reports.cash_flow(full, a, b)
        assert dash["revenue"]["total"] == pl["revenue"]
        assert dash["expenses"]["total"] == pl["cogs"] + \
            pl["operating_expenses"] + pl["other_expenses"]
        assert dash["cash"]["net_cash_flow"] == cf["net_change"]
        assert dash["range"] == (a, b)
