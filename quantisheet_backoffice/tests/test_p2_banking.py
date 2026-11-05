"""Addendum Phase 2, banking: P2-09 changed (9.2 card receipts through the
P2-11 import), P2-11 statement import (11.1-11.3), P2-12 matching and
rules (12.1-12.3), P2-13 reconciliation (13.1-13.3), plus mode gating."""
import pytest

from quantisheet_backoffice import (ap, appay, banking, billing, ledger,
                                    payments, reconcile, security)
from quantisheet_backoffice.office import ModeError
from quantisheet_backoffice.security import Denied

from .helpers import ap_invoice, approve_ap


@pytest.fixture
def full(office):
    office.set_company(accounting_mode="full")
    return office


def ofx(lines):
    """Made-up OFX 1.x (SGML) statement: lines = [(fitid, yyyymmdd,
    amount text, name, checknum)]."""
    out = ["OFXHEADER:100", "DATA:OFXSGML", "VERSION:102", "",
           "<OFX><BANKMSGSRSV1><STMTTRNRS><STMTRS><CURDEF>USD",
           "<BANKACCTFROM><BANKID>999999999<ACCTID>000012345678",
           "<ACCTTYPE>CHECKING</BANKACCTFROM>",
           "<BANKTRANLIST><DTSTART>20261001<DTEND>20261130"]
    for fitid, d, amt, name, chk in lines:
        out += ["<STMTTRN>", f"<TRNTYPE>{'CREDIT' if not amt.startswith('-') else 'DEBIT'}",
                f"<DTPOSTED>{d}120000", f"<TRNAMT>{amt}", f"<FITID>{fitid}",
                f"<NAME>{name}"] + ([f"<CHECKNUM>{chk}"] if chk else []) + \
               ["</STMTTRN>"]
    out += ["</BANKTRANLIST><LEDGERBAL><BALAMT>0<DTASOF>20261130",
            "</LEDGERBAL></STMTRS></STMTTRNRS></BANKMSGSRSV1></OFX>"]
    return "\n".join(out)


def _bank(office):
    return banking.add_account(office, "Operating - Example Bank", "1000",
                               last4="000012345678")


def test_mode_gating_export_mode_refuses_banking(office):
    assert office.mode == "export"
    with pytest.raises(ModeError):
        banking.add_account(office, "Operating", "1000")
    with pytest.raises(ModeError):
        reconcile.start(office, 1, "2026-10-31", "0")


def test_11_1_ofx_40_lines_then_zero(full, tmp_path):
    b = _bank(full)
    assert banking.bank_account(full, b)["last4"] == "5678"
    lines = [(f"FIT{n:04d}", f"202610{(n % 28) + 1:02d}",
              f"-{100 + n}.{n:02d}", f"PAYEE {n}", "") for n in range(40)]
    p = tmp_path / "oct.ofx"
    p.write_text(ofx(lines))
    r = banking.import_statement(full, b, str(p))
    assert (r["new"], r["duplicates"], r["rejected"]) == (40, 0, [])
    again = banking.import_statement(full, b, str(p))
    assert (again["new"], again["duplicates"]) == (0, 40)
    amts = sorted(l["amount"] for l in banking.review_queue(full, b))
    assert amts[0] == -13_939 and amts[-1] == -10_000


def test_11_1_csv_dedup_on_date_amount_description(full):
    b = banking.add_account(full, "Ops CSV", "1000", statement_format="csv")
    text = "Date,Description,Amount\n10/05/2026,EXAMPLE LUMBER,-50.00\n" \
           "10/06/2026,EXAMPLE HARDWARE,-12.34\n"
    assert banking.import_statement(full, b, text=text, fmt="csv")["new"] == 2
    r = banking.import_statement(full, b, text=text, fmt="csv")
    assert (r["new"], r["duplicates"]) == (0, 2)


def test_11_2_bad_csv_amount_rejected_others_exact(full):
    b = banking.add_account(full, "Ops CSV", "1000", statement_format="csv")
    text = ("Date,Description,Amount\n"
            "10/01/2026,DEPOSIT,\"1,234.50\"\n"
            "10/02/2026,FUEL,-0.10\n"
            "10/03/2026,TYPO,\"1,234.5x\"\n"
            "10/04/2026,REFUND,(312.47)\n")
    r = banking.import_statement(full, b, text=text, fmt="csv")
    assert r["rejected"] == [(4, "row 4: amount '1,234.5x' can't be read")]
    assert sorted(l["amount"] for l in banking.review_queue(full, b)) == \
        [-31_247, -10, 123_450]


def test_11_3_import_posts_nothing(full, tmp_path):
    b = _bank(full)
    tb0 = ledger.trial_balance(full)
    n0 = full.db.scalar("SELECT COUNT(*) FROM journal_entries")
    p = tmp_path / "s.ofx"
    p.write_text(ofx([("A1", "20261005", "-50.00", "X", ""),
                      ("A2", "20261006", "250.00", "Y", "")]))
    banking.import_statement(full, b, str(p))
    banking.add_rule(full, "X", "6090")
    banking.suggest_all(full, b)
    assert ledger.trial_balance(full) == tb0
    assert full.db.scalar("SELECT COUNT(*) FROM journal_entries") == n0


def _inv1001_paid(office, job3):
    billing.set_contract(office, job3)
    office.db.set_counter("INV", 999)
    for n in (1, 2):
        billing.approve(office, billing.invoice_from_payapp(office, job3, n))
    iid = billing.invoice_from_payapp(office, job3, 3)
    billing.approve(office, iid)
    cust = billing.invoice(office, iid)["customer"]
    pid = payments.receive(office, cust, "2026-11-02", "60000.00",
                           reference="CHK 88123",
                           applications=[(iid, "60000.00")])["payment_id"]
    return iid, pid


def test_12_1_deposit_matches_payment(full, job3, tmp_path):
    iid, pid = _inv1001_paid(full, job3)
    b = _bank(full)
    rev0 = ledger.balance(full, "4000")
    p = tmp_path / "nov.ofx"
    p.write_text(ofx([("D1", "20261103", "60000.00", "DEPOSIT", "")]))
    (lid,) = banking.import_statement(full, b, str(p))["ids"]
    s = banking.line(full, lid)["suggestion"]
    assert s["kind"] == "match" and s["match"] == {
        "kind": "payment", "id": pid, "reference": False,
        "label": s["match"]["label"]}
    eid = banking.accept(full, lid)
    lines = sorted((ledger.account(full, l["account_id"])["name"], l["debit"],
                    l["credit"]) for l in ledger.entry(full, eid)["lines"])
    assert lines == [("Operating bank", 6_000_000, 0),
                     ("Undeposited funds", 0, 6_000_000)]
    assert ledger.balance(full, "4000") == rev0          # no second revenue
    assert full.db.get("payments", pid)["deposited_on"] == "2026-11-03"
    assert banking.line(full, lid)["status"] == "Accepted"


def test_12_2_rule_suggests_5_of_6_user_category_kept(full, job, tmp_path):
    b = _bank(full)
    rows = [(f"H{n}", f"2026100{n + 1}", f"-{200 + n * 11}.{n}7",
             f"EXAMPLE LUMBER #{n}", "") for n in range(6)]
    p = tmp_path / "h.ofx"
    p.write_text(ofx(rows))
    ids = banking.import_statement(full, b, str(p))["ids"]
    banking.categorize(full, ids[5], "6090")              # user: Overhead
    banking.add_rule(full, "EXAMPLE LUMBER", "5020", job_id=job,
                     cost_code="03-3000")
    banking.suggest_all(full, b)
    ss = [banking.line(full, i)["suggestion"] for i in ids]
    assert [s["kind"] for s in ss] == ["rule"] * 5 + ["category"]
    mat = ledger.account_by_number(full, "5020")["id"]
    assert all(s["account_id"] == mat and s["cost_code"] == "03-3000"
               for s in ss[:5])
    assert ss[5]["account_id"] == ledger.account_by_number(full, "6090")["id"]


def test_12_3_two_equal_bills_no_auto_pick(full, job, tmp_path):
    a = ap_invoice(full, "Example Lumber", "HL-301", "2026-10-02", "312.47",
                   job_id=job)
    c = ap_invoice(full, "Example Lumber", "HL-302", "2026-10-15", "312.47",
                   job_id=job)
    approve_ap(full, a)
    approve_ap(full, c)
    b = _bank(full)
    p = tmp_path / "x.ofx"
    p.write_text(ofx([("B1", "20261020", "-312.47", "EXAMPLE LUMBER", "")]))
    (lid,) = banking.import_statement(full, b, str(p))["ids"]
    s = banking.line(full, lid)["suggestion"]
    assert s["kind"] == "choose"
    assert sorted(x["id"] for x in s["candidates"]) == sorted([a, c])
    assert banking.accept_all_suggested(full, b) == []
    with pytest.raises(banking.BankError, match="choose one"):
        banking.accept(full, lid)
    banking.accept(full, lid, choice=("bill", c))
    assert ap.invoice(full, c)["status"] == "Paid"
    assert ap.invoice(full, a)["status"] == "Approved"


def test_9_2_card_statement_receipt_posts_to_card(full, job):
    card = banking.add_account(full, "Company Card", "2300", kind="card",
                               last4="4111111111111111",
                               statement_format="csv")
    text = "Date,Description,Amount\n10/14/2026,EXAMPLE LUMBER,-312.47\n"
    (lid,) = banking.import_statement(full, card, text=text, fmt="csv")["ids"]
    assert [l["id"] for l in banking.review_queue(full, card)] == [lid]
    banking.categorize(full, lid, "5020", job_id=job, cost_code="03-3000")
    eid = banking.accept(full, lid)
    lines = sorted((ledger.account(full, l["account_id"])["name"], l["debit"],
                    l["credit"], l["job_id"], l["cost_code"] or "")
                   for l in ledger.entry(full, eid)["lines"])
    assert lines == [("Credit card", 0, 31_247, None, ""),
                     ("Job cost - Material", 31_247, 0, job, "03-3000")]


def _recon_setup(office, job3, tmp_path):
    """Opening $50,000.00 reconciled through 09-30; then the 12.1 deposit,
    check 5012 to Apex ($27,000.00), a $312.47 Example Lumber debit and
    check 5013 to Example Electric ($1,150.00, not yet cleared)."""
    b = _bank(office)
    ledger.post(office, "2026-09-30", [
        {"account": "1000", "debit": 5_000_000},
        {"account": "3000", "credit": 5_000_000}], "opening", 1, "Opening")
    r0 = reconcile.start(office, b, "2026-09-30", "50000.00", beginning="0")
    reconcile.set_cleared(office, r0, [i["line_id"] for i in
                                       reconcile.items(office, r0)])
    reconcile.finish(office, r0)
    iid, pid = _inv1001_paid(office, job3)
    ap.seed_vendors(office, job3)
    apex = ap.vendor_by_name(office, "Example Framing")
    office.db.conn.execute("UPDATE snap_records SET data = replace(data, "
                           "'2026-09-30', '2027-09-30') WHERE section = "
                           "'commitments'")
    office.db.conn.commit()
    ap.update_vendor(office, apex["id"], insurance_expires="2027-09-30")
    bill = ap_invoice(office, "Example Framing", "AF-1030", "2026-10-15",
                      "30000.00", job_id=job3, code="06-1000", cat="S",
                      commitment_no="SC-004")
    approve_ap(office, bill, override_reason="CO-007 pending with Apex")
    ce = ap_invoice(office, "Example Electric Supply", "CE-40", "2026-10-20",
                    "1150.00", job_id=job3)
    approve_ap(office, ce)
    office.act_as("ap@bo.test")
    appay.pay(office, apex["id"], "2026-10-30", [(bill, "27000.00")],
              reference="5012")
    appay.pay(office, ap.invoice(office, ce)["vendor_id"], "2026-11-05",
              [(ce, "1150.00")], reference="5013")
    office.act_as("admin@bo.test")
    banking.add_rule(office, "EXAMPLE LUMBER", "5020", job_id=job3,
                     cost_code="03-3000")
    p = tmp_path / "nov.ofx"
    p.write_text(ofx([("D1", "20261103", "60000.00", "DEPOSIT", ""),
                      ("C1", "20261104", "-27000.00", "CHECK", "5012"),
                      ("H1", "20261106", "-312.47", "EXAMPLE LUMBER", "")]))
    ids = banking.import_statement(office, b, str(p))["ids"]
    for i in ids:
        banking.accept(office, i)
    rid = reconcile.start(office, b, "2026-11-30", "82687.53")
    return b, rid


def _ids(office, rid, amounts):
    return [i["line_id"] for i in reconcile.items(office, rid)
            if i["amount"] in amounts]


def test_13_1_difference_and_finish(full, job3, tmp_path):
    b, rid = _recon_setup(full, job3, tmp_path)
    assert reconcile.status(full, rid)["beginning"] == 5_000_000
    st = reconcile.set_cleared(full, rid, _ids(full, rid, (6_000_000,
                                                           -2_700_000,
                                                           -31_247)))
    assert st["difference"] == 0 and st["can_finish"]
    st = reconcile.set_cleared(full, rid, _ids(full, rid, (-31_247,)),
                               cleared=False)
    assert st["difference_text"] == "-$312.47" and not st["can_finish"]
    with pytest.raises(reconcile.ReconcileError):
        reconcile.finish(full, rid)


def test_13_2_finished_lines_locked_report_outstanding(full, job3, tmp_path):
    b, rid = _recon_setup(full, job3, tmp_path)
    reconcile.set_cleared(full, rid, _ids(full, rid, (6_000_000, -2_700_000,
                                                      -31_247)))
    reconcile.finish(full, rid)
    harbor = [l for l in full.db.rows("SELECT id FROM statement_lines WHERE "
                                      "payee = 'EXAMPLE LUMBER'")][0]["id"]
    with pytest.raises(banking.BankError, match="finished reconciliation"):
        banking.edit_line(full, harbor, amount="-300.00")
    with pytest.raises(banking.BankError):
        banking.edit_line(full, harbor, date="2026-11-07")
    with pytest.raises(Exception):          # the ledger itself is fixed
        full.db.conn.execute("UPDATE journal_lines SET debit = 1 WHERE id = ?",
                             (_ids(full, rid, (-31_247,)) or [0])[0])
    rep = reconcile.report(full, rid)
    out = [(i["reference"], i["amount"]) for i in rep["outstanding"]]
    assert out == [("check 5013", -115_000)]
    p = reconcile.report_pdf(full, rid, str(tmp_path / "rec.pdf"))
    import fitz
    assert "$1,150.00" in fitz.open(p)[0].get_text().replace("-$", "$")


def test_13_3_only_latest_undone_by_controller(full, job3, tmp_path):
    b, rid = _recon_setup(full, job3, tmp_path)
    first = full.db.one("SELECT id FROM reconciliations WHERE period_end = "
                        "'2026-09-30'")["id"]
    reconcile.set_cleared(full, rid, _ids(full, rid, (6_000_000, -2_700_000,
                                                      -31_247)))
    reconcile.finish(full, rid)
    full.act_as("ap@bo.test")
    with pytest.raises(Denied):
        reconcile.undo(full, rid, "wrong")
    full.act_as("ctl@bo.test")
    with pytest.raises(reconcile.ReconcileError, match="latest"):
        reconcile.undo(full, first, "older one")
    with pytest.raises(reconcile.ReconcileError):
        reconcile.undo(full, rid, " ")
    reconcile.undo(full, rid, "bank corrected the statement")
    assert reconcile.status(full, rid)["status"] == "Open"
    reconcile.undo(full, first, "now it is the latest")
    acts = [(r["action"], r["record_id"]) for r in
            security.audit_rows(full.db) if r["record_type"] ==
            "reconciliation"]
    assert ("undo", str(rid)) in [(a, str(i)) for a, i in acts]
    assert ("undo", str(first)) in [(a, str(i)) for a, i in acts]
    assert any(a == "denied" for a, _ in acts)
