"""Addendum P2-17 migration import (17.1-17.4). Made-up files only; the
IIF text is the tab-separated format QuickBooks Desktop exports."""
import pytest

from quantisheet_backoffice import (billing, cents, fileguard, ledger,
                                    migrate, payments, reports)

IIF_TYPES = ["BANK", "AR", "OCASSET", "FIXASSET", "OASSET", "AP", "CCARD",
             "OCLIAB", "LTLIAB", "EQUITY", "INC", "COGS", "EXP", "EXINC",
             "EXEXP"]
OPEN = [("QB-5001", "Cust 01", "08/15/2026", "09/14/2026", "4250.00"),
        ("QB-5002", "Cust 02", "09/01/2026", "10/01/2026", "1830.25"),
        ("QB-5003", "Cust 03", "09/10/2026", "10/10/2026", "12000.00"),
        ("QB-5004", "Cust 04", "06/30/2026", "07/30/2026", "640.10"),
        ("QB-5005", "Cust 05", "09/25/2026", "10/25/2026", "9999.99"),
        ("QB-5006", "Cust 06", "07/20/2026", "08/19/2026", "300.00")]
QB_AGING_TOTAL = "29020.34"          # the fixture's QuickBooks A/R aging


def iif_text():
    t = ["!ACCNT\tNAME\tACCNTTYPE\tDESC\tACCNUM",
         *[f"ACCNT\tQB Account {n:02d}\t{IIF_TYPES[n % len(IIF_TYPES)]}\t"
           f"made-up\t{50000 + n}" for n in range(45)],
         "!CUST\tNAME\tBADDR1\tEMAIL",
         *[f"CUST\tCust {n:02d}\t{n} Elm St\tc{n}@example.test"
           for n in range(1, 13)],
         "!VEND\tNAME\tPHONE1\t1099",
         *[f"VEND\tVendor {n:02d}\t555-01{n:02d}\t{'Y' if n % 3 == 0 else 'N'}"
           for n in range(1, 21)],
         "!TRNS\tTRNSID\tTRNSTYPE\tDATE\tACCNT\tNAME\tAMOUNT\tDOCNUM\tDUEDATE\tMEMO",
         "!SPL\tSPLID\tTRNSTYPE\tDATE\tACCNT\tNAME\tAMOUNT\tDOCNUM\tDUEDATE\tMEMO",
         "!ENDTRNS"]
    for num, cust, d, due, amt in OPEN:
        t += [f"TRNS\t\tINVOICE\t{d}\tAccounts Receivable\t{cust}\t{amt}\t"
              f"{num}\t{due}\topen",
              f"SPL\t\tINVOICE\t{d}\tQB Account 10\t{cust}\t-{amt}\t{num}\t\t",
              "ENDTRNS"]
    return "\n".join(t) + "\n"


@pytest.fixture
def full(office):
    office.set_company(accounting_mode="full")
    return office


@pytest.fixture
def iif(tmp_path):
    p = tmp_path / "company_lists.iif"
    p.write_text(iif_text(), encoding="utf-8")
    return str(p)


def test_17_1_counts_apply_no_duplicates(full, iif):
    pv = migrate.preview_iif(full, iif)
    assert {k: pv["counts"][k] for k in ("accounts", "customers", "vendors",
                                         "invoices")} == \
        {"accounts": 45, "customers": 12, "vendors": 20, "invoices": 6}
    assert pv["problems"] == []
    before = full.db.row_counts()
    migrate.apply_iif(full, iif, as_of="2026-09-30")
    after = full.db.row_counts()
    assert after["accounts"] - before["accounts"] == 45
    assert after["customers"] - before["customers"] == 12
    assert after["vendors"] - before["vendors"] == 20
    assert after["ar_invoices"] - before["ar_invoices"] == 6
    assert ledger.account_by_name(full, "QB Account 07")["qb_name"] == \
        "QB Account 07"
    again = migrate.preview_iif(full, iif)
    assert all(v == 0 for v in again["counts"].values())
    migrate.apply_iif(full, iif, as_of="2026-09-30")
    assert full.db.row_counts()["customers"] == after["customers"]
    assert full.db.row_counts()["ar_invoices"] == after["ar_invoices"]


def test_17_2_opening_trial_balance(full):
    rows = [("1000", "182500.00", ""), ("1500", "64000.00", ""),
            ("1550", "", "12800.00"), ("2600", "", "40000.00"),
            ("2800", "", "3150.55"), ("3100", "", "50000.00"),
            ("3000", "", "140549.44")]
    with pytest.raises(migrate.MigrateError) as e:
        migrate.opening_balances(full, "2026-09-30", rows)
    assert "difference $0.01" in str(e.value)
    assert full.db.scalar("SELECT COUNT(*) FROM journal_entries") == 0
    rows[-1] = ("3000", "", "140549.45")
    migrate.opening_balances(full, "2026-09-30", rows)
    bs = reports.balance_sheet(full, "2026-09-30")
    assert bs["balances"]
    got = {r["number"]: r["amount"] for s in bs["sections"].values()
           for r in s if r["number"]}
    for acct, dr, cr in rows:
        a = ledger.account_by_number(full, acct)
        natural = (cents.parse_amount(dr or "0") - cents.parse_amount(cr or "0"))
        if a["type"] != "asset":
            natural = -natural
        assert got[acct] == natural, acct
    with pytest.raises(migrate.MigrateError, match="item by item"):
        migrate.opening_balances(full, "2026-09-30",
                                 [("1100", "10.00", ""), ("3000", "", "10.00")])


def test_17_3_open_ar_aging_and_undo(full, iif):
    before = full.db.row_counts()
    batch = migrate.apply_iif(full, iif, as_of="2026-09-30")
    ag = payments.aging(full, "2026-10-01")
    assert ag["total"] == cents.parse_amount(QB_AGING_TOTAL)
    assert ledger.balance(full, "Accounts receivable", "2026-10-01") == \
        cents.parse_amount(QB_AGING_TOTAL)
    # something not in the batch stays
    keep = billing.create_other_invoice(full, None, "2026-10-01", [
        {"description": "x", "amount": "10.00"}], customer="Walk-in")
    migrate.undo(full, batch, "test")
    live = lambda t: full.db.scalar(f"SELECT COUNT(*) FROM {t} WHERE deleted = 0")
    assert live("customers") == before["customers"]
    assert live("vendors") == before["vendors"]
    assert live("ar_invoices") == 1 and billing.invoice(full, keep)
    assert live("accounts") == before["accounts"] or \
        live("accounts") - before["accounts"] == 0
    assert payments.aging(full, "2026-10-01")["total"] == 0
    assert ledger.balance(full, "Accounts receivable") == 0
    with pytest.raises(migrate.MigrateError):
        migrate.undo(full, batch, "twice")


def test_17_4_qbo_export_unknown_type_listed(full, tmp_path):
    acc = tmp_path / "Account List.csv"
    acc.write_text("Account,Type,Detail type,Description\n"
                   "Checking 2,Bank,Checking,\n"
                   "Shop rent,Expenses,Rent or lease,\n"
                   "Mystery wallet,Example Holdings,?,\n"
                   "Job sales,Income,Service/fee income,\n", encoding="utf-8")
    cus = tmp_path / "Customers.csv"
    cus.write_text("Customer,Email,Phone\nExample Medical Office,p@example.test,\n",
                   encoding="utf-8")
    files = {"accounts": str(acc), "customers": str(cus)}
    pv = migrate.preview_qbo(full, files)
    assert pv["problems"] == ["account 'Mystery wallet': unknown account type "
                              "'Example Holdings'"]
    assert pv["counts"]["accounts"] == 3 and pv["counts"]["customers"] == 1
    migrate.apply_qbo(full, files)
    assert ledger.account_by_name(full, "Shop rent")["type"] == "expense"
    assert ledger.account_by_name(full, "Mystery wallet") is None
    qbw = tmp_path / "Company.QBW"
    qbw.write_bytes(b"x")
    with pytest.raises(fileguard.CompanyFileError):
        migrate.preview_qbo(full, {"accounts": str(qbw)})
