"""P1-17 accounting exports (17.1-17.4) and the addendum's changed tests
17.5 (account with no QuickBooks name) and 17.6 (company files refused,
trademark notice)."""
import csv
import os
import re

import pytest

from quantisheet_backoffice import ap, exports, fileguard, ledger

from .helpers import ap_invoice, approve_ap

PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _three(office, job):
    ids = []
    for vendor, no, amt in (("Example Ready-Mix", "RM-501", "25000.00"),
                            ("Example Lumber", "HL-88", "4800.00"),
                            ("Example Electric Supply", "CE-12", "1240.00")):
        iid = ap_invoice(office, vendor, no, "2026-10-12", amt, job_id=job)
        approve_ap(office, iid)
        ids.append(iid)
    return ids


def _iif_blocks(path):
    blocks, cur = [], None
    with open(path, encoding="utf-8") as fh:
        for line in fh.read().splitlines():
            f = line.split("\t")
            if f[0] == "TRNS":
                cur = [f]
            elif f[0] == "SPL":
                cur.append(f)
            elif f[0] == "ENDTRNS" and cur is not None:
                blocks.append(cur)
                cur = None
    return blocks


def test_17_1_ap_batch_to_iif_balances(office, job, tmp_path):
    ids = _three(office, job)
    office.act_as("ctl@bo.test")
    r = exports.export(office, "ap", "2026-10-01", "2026-10-31", "iif",
                       folder=str(tmp_path))
    assert r["count"] == 3 and r["total"] == 3_104_000 and not r["problems"]
    blocks = _iif_blocks(r["path"])
    assert len(blocks) == 3
    from decimal import Decimal
    for b in blocks:
        assert sum(Decimal(row[7]) for row in b) == 0       # AMOUNT column
        assert b[0][2] == "BILL"
    assert all(ap.invoice(office, i)["status"] == "Exported" for i in ids)
    assert r["number"] == "EXP-0001"


def test_17_2_missing_cost_code_listed_others_export(office, job, tmp_path):
    ids = _three(office, job)
    bad = ap_invoice(office, "Example Lumber", "HL-90", "2026-10-13", "500.00",
                     job_id=job, lines=[
                         {"cost_code": "03-3000", "category": "M",
                          "amount": "300.00"},
                         {"cost_code": "03-3000", "category": "M",
                          "amount": "200.00"}])
    approve_ap(office, bad)
    office.db.conn.execute("UPDATE ap_lines SET cost_code = '' WHERE "
                           "invoice_id = ? AND line_no = 2", (bad,))
    office.db.conn.commit()
    office.db.update("ap_invoices", bad, number="AP-0011")
    office.act_as("ctl@bo.test")
    r = exports.export(office, "ap", "2026-10-01", "2026-10-31", "csv",
                       folder=str(tmp_path))
    assert "AP-0011 line 2: no cost code" in r["problems"]
    assert r["count"] == 3
    assert ap.invoice(office, bad)["status"] == "Approved"


def test_17_3_again_finds_nothing_void_frees(office, job, tmp_path):
    ids = _three(office, job)
    office.act_as("ctl@bo.test")
    r = exports.export(office, "ap", "2026-10-01", "2026-10-31", "iif",
                       folder=str(tmp_path))
    again = exports.export(office, "ap", "2026-10-01", "2026-10-31", "iif",
                           folder=str(tmp_path))
    assert again["count"] == 0
    with pytest.raises(exports.ExportError):
        exports.void_batch(office, r["batch_id"], "  ")
    exports.void_batch(office, r["batch_id"], "QuickBooks import failed")
    assert all(ap.invoice(office, i)["status"] == "Approved" for i in ids)
    third = exports.export(office, "ap", "2026-10-01", "2026-10-31", "iif",
                           folder=str(tmp_path))
    assert third["count"] == 3 and third["number"] == "EXP-0002"


def test_17_4_sage_file_uses_saved_column_map(office, job, tmp_path):
    _three(office, job)
    office.act_as("admin@bo.test")
    cols = ["Vendor", "Invoice", "Invoice Date", "Job", "Cost Code",
            "Category", "Amount", "Retainage", "Description"]
    exports.set_column_map(office, "sage", "ap", cols)
    office.act_as("ctl@bo.test")
    r = exports.export(office, "ap", "2026-10-01", "2026-10-31", "sage",
                       folder=str(tmp_path))
    with open(r["path"], encoding="utf-8") as fh:
        rows = list(csv.reader(fh))
    assert rows[0] == cols
    assert rows[1][cols.index("Cost Code")] == "03-3000"
    sample = os.environ.get("QS_SAGE_AP_SAMPLE")
    if not sample:
        pytest.skip("decision 6: Jon's own Sage 300 CRE AP sample file is not "
                    "here yet; set QS_SAGE_AP_SAMPLE to compare column order")
    with open(sample, encoding="utf-8-sig") as fh:
        want = next(csv.reader(fh))
    assert rows[0] == want


def test_17_5_account_without_quickbooks_name(office, job, tmp_path):
    ids = _three(office, job)
    office.act_as("admin@bo.test")
    acct = ledger.add_account(office, "5100", "Job cost - Materials", "cogs")
    ledger.set_cost_code_account(office, "09-2000", acct)
    bad = ap_invoice(office, "Example Lumber", "HL-91", "2026-10-14", "700.00",
                     job_id=job, code="09-2000", cat="M")
    approve_ap(office, bad)
    office.act_as("ctl@bo.test")
    r = exports.export(office, "ap", "2026-10-01", "2026-10-31", "iif",
                       folder=str(tmp_path))
    assert "account 5100 Job cost - Materials: no QuickBooks name" in \
        r["problems"]
    assert r["count"] == 3
    assert ap.invoice(office, bad)["status"] == "Approved"
    assert "HL-91" not in open(r["path"], encoding="utf-8").read()


def test_17_6_company_files_refused_and_notice(office, qapp, tmp_path):
    for name in ("Company.QBW", "backup.qbb", "x.Qbw"):
        p = tmp_path / name
        p.write_bytes(b"not really")
        with pytest.raises(fileguard.CompanyFileError) as e:
            fileguard.refuse_company_file(str(p))
        assert str(e.value) == fileguard.MESSAGE == (
            "QuantiSheet does not open QuickBooks company files; export IIF "
            "or Export data files from QuickBooks first")
    # every import entry point goes through the guard first
    from quantisheet_backoffice import migrate
    with pytest.raises(fileguard.CompanyFileError):
        ledger.import_chart_csv(office, str(tmp_path / "Company.QBW"))
    with pytest.raises(fileguard.CompanyFileError):
        migrate.read_file(str(tmp_path / "Company.QBW"))
    # no code path opens those extensions: only fileguard names them
    hits = []
    for root, _dirs, files in os.walk(PKG):
        if os.sep + "tests" in root:
            continue
        for f in files:
            if f.endswith(".py") and f != "fileguard.py":
                text = open(os.path.join(root, f), encoding="utf-8").read()
                if re.search(r"\.qb[wbmx]\b", text, re.I):
                    hits.append(f)
    assert hits == []
    from quantisheet_backoffice.ui.exports_page import ExportsPage
    page = ExportsPage(office)
    assert page.notice.text() == fileguard.TRADEMARK_NOTICE == (
        "QuickBooks is a trademark of Intuit Inc. QuantiSheet is not "
        "affiliated with or endorsed by Intuit.")
    assert page.drop_file(str(tmp_path / "Company.QBW")) == fileguard.MESSAGE


def test_17_6_restore_and_open_refuse_company_files(office, tmp_path):
    from quantisheet_backoffice.store import DB
    qbb = tmp_path / "Company.QBB"
    qbb.write_bytes(b"not ours")
    with pytest.raises(fileguard.CompanyFileError):
        from quantisheet_backoffice import backup
        backup.restore(office.folder, str(qbb))
    with pytest.raises(fileguard.CompanyFileError):
        DB(str(tmp_path / "Company.qbw"))
    assert qbb.read_bytes() == b"not ours"
