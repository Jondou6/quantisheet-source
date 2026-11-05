"""P1-14 lien waivers (14.1-14.3), P1-15 payments and AR aging
(15.1-15.3), P1-16 invoice PDF and email-ready output (16.1-16.3)."""
import email
import os

import fitz
import pytest

from quantisheet_backoffice import (ap, appay, billing, cents, output,
                                    payments, waivers)

from .helpers import ap_invoice, approve_ap
from .test_p1_10_13_billing import seed_tm


def _inv1001(office, job3, approve=True):
    billing.set_contract(office, job3, contact_email="dana@example.test")
    office.db.set_counter("INV", 999)
    for n in (1, 2):
        billing.approve(office, billing.invoice_from_payapp(office, job3, n))
    iid = billing.invoice_from_payapp(office, job3, 3)
    if approve:
        billing.approve(office, iid)
    return iid


def test_14_1_conditional_then_unconditional_for_amount_received(office, job3):
    iid = _inv1001(office, job3)
    ws = [w for w in waivers.waivers(office, "issued") if w["ar_invoice_id"] == iid]
    assert [(w["kind"], w["amount"], w["through"]) for w in ws] == \
        [("conditional_progress", 6_750_000, "2026-10-31")]
    inv = billing.invoice(office, iid)
    payments.receive(office, inv["customer"], "2026-11-02", "60000.00",
                     applications=[(iid, "60000.00")])
    ws = [w for w in waivers.waivers(office, "issued") if w["ar_invoice_id"] == iid]
    assert ("unconditional_progress", 6_000_000) in \
        [(w["kind"], w["amount"]) for w in ws]
    assert not any(w["kind"] == "unconditional_progress" and
                   w["amount"] == 6_750_000 for w in ws)


def test_14_2_statutory_state_needs_form(office, job, tmp_path):
    office.db.update("jobs", job, state="CA")
    with pytest.raises(waivers.WaiverError) as e:
        waivers.create(office, "issued", "conditional_progress", job,
                       "2026-10-31", "1000.00")
    assert str(e.value) == ("California uses a statutory form; attach it or "
                            "pick another state")
    form = tmp_path / "ca_form.pdf"
    d = fitz.open(); d.new_page(); d.save(str(form)); d.close()
    wid = waivers.create(office, "issued", "conditional_progress", job,
                         "2026-10-31", "1000.00", form_path=str(form))
    assert office.db.get("waivers", wid)["form"] == "statutory"
    assert set(waivers.STATUTORY_STATES.values()) >= {"California", "Texas"}
    assert len(waivers.STATUTORY_STATES) == 12


def test_14_3_final_payment_blocked_without_final_waiver(office, job):
    ap.seed_vendors(office, job)
    apex = ap.vendor_by_name(office, "Example Framing")
    ap.update_vendor(office, apex["id"], insurance_expires="2027-09-30")
    iid = ap_invoice(office, "Example Framing", "AF-9", "2026-10-20", "2000.00",
                     job_id=job, code="06-1000", cat="S",
                     commitment_no="SC-004", final=True)
    office.db.conn.execute("UPDATE snap_records SET data = replace(data, "
                           "'2026-09-30', '2027-09-30') WHERE section = "
                           "'commitments'")
    approve_ap(office, iid, override_reason="ok")
    open_amt = appay.open_bill(office, iid)
    office.act_as("ap@bo.test")
    with pytest.raises(appay.PayError, match="unconditional final waiver"):
        appay.pay(office, apex["id"], "2026-10-25",
                  [(iid, cents.from_cents(open_amt))],
                  reference="5020", final=True)
    office.act_as("ctl@bo.test")
    with pytest.raises(appay.PayError):
        appay.pay(office, apex["id"], "2026-10-25",
                  [(iid, cents.from_cents(open_amt))],
                  reference="5020", final=True, override_reason="")
    wid = waivers.create(office, "received", "unconditional_final", job,
                         "2026-10-25", "2000.00", party="Example Framing",
                         vendor_id=apex["id"])
    waivers.set_status(office, wid, "Received")
    office.act_as("ap@bo.test")
    pid = appay.pay(office, apex["id"], "2026-10-25", [(iid, cents.from_cents(open_amt))],
                    reference="5020", final=True)
    assert pid


def test_15_1_ar_aging_buckets(office, job3):
    iid = _inv1001(office, job3, approve=False)
    office.db.update("ar_invoices", iid, invoice_date="2026-10-15",
                     due_date="2026-11-14", gl_date="2026-10-15")
    billing.approve(office, iid)
    cust = billing.invoice(office, iid)["customer"]
    # the two earlier progress invoices are paid in full
    for n in (1, 2):
        prior = office.db.one("SELECT * FROM ar_invoices WHERE payapp_no = ?", (n,))
        payments.receive(office, cust, "2026-10-01", cents.text(prior["total"]),
                         applications=[(prior["id"], cents.text(prior["total"]))])
    for num, amt, due in (("INV-0998", "18250.00", "2026-10-20"),
                          ("INV-0990", "9400.00", "2026-09-24"),
                          ("INV-0981", "3125.00", "2026-08-09"),
                          ("INV-0975", "1980.00", "2026-07-15")):
        o = billing.create_other_invoice(office, job3, "2026-06-01",
                                         [{"description": "Extra", "amount": amt}],
                                         customer=cust, due_date=due, number=num)
        billing.approve(office, o)
    o = office.db.one("SELECT id FROM ar_invoices WHERE number = 'INV-0998'")["id"]
    payments.receive(office, cust, "2026-10-25", "8250.00",
                     applications=[(o, "8250.00")])
    r = billing.create_other_invoice(office, job3, "2026-10-01",
                                     [{"description": "Retainage", "amount":
                                       "22500.00"}], customer=cust,
                                     due_date="2026-10-31", number="RET-0901",
                                     type_="Other")
    billing.approve(office, r)
    ag = payments.aging(office, "2026-10-31")
    t = ag["totals"]
    assert t == {"current": 9_000_000, "1-30": 1_000_000, "31-60": 940_000,
                 "61-90": 312_500, "over 90": 198_000}
    assert cents.fmt(ag["total"]) == "$114,505.00"
    days = {r["number"]: r["days"] for r in ag["rows"]}
    assert days["INV-0998"] == 11 and days["INV-0990"] == 37
    assert days["INV-0981"] == 83 and days["INV-0975"] == 108


def test_15_2_partial_payment(office, job3):
    iid = _inv1001(office, job3)
    inv = billing.invoice(office, iid)
    payments.receive(office, inv["customer"], "2026-11-02", "60000.00",
                     applications=[(iid, "60000.00")])
    assert billing.invoice(office, iid)["status"] == "Partly paid"
    assert payments.open_amount(office, iid) == 750_000
    due = inv["due_date"]
    row = [r for r in payments.aging(office, due)["rows"] if r["number"] ==
           "INV-1001"][0]
    assert row["bucket"] == "current" and row["open"] == 750_000


def test_15_3_overpayment_credit(office, job3):
    iid = _inv1001(office, job3)
    cust = billing.invoice(office, iid)["customer"]
    res = payments.receive(office, cust, "2026-11-02", "70000.00",
                           applications=[(iid, "70000.00")])
    assert res["applied"] == [(iid, 6_750_000)] and res["credit"] == 250_000
    assert billing.invoice(office, iid)["status"] == "Paid"
    cr = payments.unapplied_credits(office, cust)
    assert [c["left"] for c in cr] == [250_000]
    nxt = billing.create_other_invoice(office, None, "2026-11-05",
                                       [{"description": "Deposit",
                                         "amount": "1000.00"}], customer=cust)
    billing.approve(office, nxt)
    payments.apply_credit(office, cr[0]["id"], nxt)
    assert payments.open_amount(office, nxt) == 0
    assert payments.unapplied_credits(office, cust)[0]["left"] == 150_000


def test_16_1_invoice_pdf(office, job3, tmp_path):
    iid = _inv1001(office, job3)
    p = output.invoice_pdf(office, iid, str(tmp_path / "INV-1001.pdf"))
    doc = fitz.open(p)
    assert doc.page_count == 3                  # cover + summary + detail
    cover = doc[0].get_text()
    assert "INVOICE" in cover and "$67,500.00" in cover
    assert doc.metadata["title"] == "Invoice INV-1001 - Example Clinic"
    assert output.SUMMARY_TITLE in doc[1].get_text()


def test_16_2_email_with_outlook_absent(office, job3):
    iid = _inv1001(office, job3)
    opened = []
    msg = output.email_invoice(office, iid, opener=opened.append, outlook=False)
    assert msg["via"] == "eml" and opened == [msg["path"]]
    em = email.message_from_bytes(open(msg["path"], "rb").read())
    assert em["To"] == "dana@example.test"
    assert em["Subject"] == ("Invoice INV-1001 - Example Clinic - Period "
                             "to 2026-10-31")
    atts = [p.get_filename() for p in em.walk() if p.get_filename()]
    assert atts == ["INV-1001.pdf"]
    assert billing.invoice(office, iid)["status"] == "Approved"   # not Sent
    assert office.db.scalar("SELECT COUNT(*) FROM sent_log") == 0
    billing.mark_sent(office, iid, "dana@example.test")
    assert billing.invoice(office, iid)["status"] == "Sent"


def test_16_3_tm_backup_bundle(office, job, tmp_path):
    from PIL import Image
    seed_tm(office, job)
    hl = office.db.one("SELECT * FROM ap_invoices WHERE invoice_no = 'HL-77'")
    img = str(tmp_path / "hl77.png")
    Image.new("RGB", (40, 60), "white").save(img)
    office.db.update("ap_invoices", hl["id"], doc_path=img)
    iid = billing.create_tm_invoice(office, job, "2026-10-20", "2026-10-20")
    b = output.tm_backup(office, iid)
    assert len(b["time_lines"]) == 5
    assert [r["ap"] for r in b["receipts"]] == [hl["number"]]
    assert b["total"] == billing.invoice(office, iid)["total"] == 417_200
    p = output.tm_backup_pdf(office, iid, str(tmp_path / "backup.pdf"))
    doc = fitz.open(p)
    assert "$4,172.00" in doc[0].get_text() and doc.page_count == 2
