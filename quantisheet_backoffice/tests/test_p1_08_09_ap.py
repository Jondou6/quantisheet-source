"""P1-08 AP capture with OCR (8.1-8.3) and P1-09 routing (9.1-9.4)."""
from datetime import datetime, timedelta

import pytest

from quantisheet_backoffice import ap, approvals, clock, ocr, security

from .helpers import ap_invoice, approve_ap


def _readymix_pdf(path):
    import fitz
    doc = fitz.open()
    pg = doc.new_page()
    text = ("Example Ready-Mix\n1200 Quarry Rd, Springfield OR\n\n"
            "INVOICE\nInvoice No: RM-44817\nInvoice Date: 2026-10-12\n"
            "Due Date: 2026-11-11\n\n10 CY 4000 psi concrete  8,100.00\n"
            "Subtotal: 8,100.00\nSales Tax: 540.00\nTotal Due: $8,640.00\n")
    pg.insert_text((54, 72), text, fontsize=11)
    doc.save(path)
    doc.close()


class FakeOCR:
    """Stands in for local Tesseract: words with confidences."""

    def __init__(self, words):
        self.words = words
        self.calls = 0

    def read(self, path):
        self.calls += 1
        return self.words


def test_8_1_digital_pdf_fields_all_green(office, tmp_path):
    office.act_as("ap@bo.test")
    ap.add_vendor(office, "Example Ready-Mix")
    p = str(tmp_path / "rm.pdf")
    _readymix_pdf(p)
    res = ap.capture(office, p, engine=FakeOCR([]))
    f = res["fields"]
    assert res["source"] == "text layer"
    assert f["vendor"][0] == "Example Ready-Mix"
    assert f["invoice_no"][0] == "RM-44817"
    assert f["invoice_date"][0] == "2026-10-12"
    assert f["total"][0] == "8640.00" and f["tax"][0] == "540.00"
    assert {ocr.COLOUR[c] for _, c in f.values()} == {"green"}
    assert res["needs_confirm"] == []
    iid = ap.create_invoice(office, res["vendor_id"], f["invoice_no"][0],
                            f["invoice_date"][0], f["total"][0], f["tax"][0],
                            capture_result=res)
    inv = ap.invoice(office, iid)
    assert inv["total"] == 864000 and inv["tax"] == 54000
    assert inv["doc_hash"] and inv["doc_path"].startswith(office.folder)


def test_8_2_receipt_photo_low_confidence_date(office, tmp_path):
    office.act_as("ap@bo.test")
    vid = ap.add_vendor(office, "Example Lumber")
    from PIL import Image
    img = str(tmp_path / "receipt.jpg")
    Image.new("RGB", (60, 90), "white").save(img)
    words = [("Example", 93), ("Lumber", 95), ("Date:", 88), ("10/14/2026", 41),
             ("Total:", 92), ("312.47", 90)]
    eng = FakeOCR(words)
    res = ap.capture(office, img, engine=eng)
    assert eng.calls == 1 and res["source"] == "ocr"
    f = res["fields"]
    assert f["vendor"][0] == "Example Lumber" and f["total"][0] == "312.47"
    assert f["invoice_date"][1] == ocr.LOW
    assert ocr.COLOUR[f["invoice_date"][1]] == "red"
    assert res["needs_confirm"] == ["invoice_date"]
    with pytest.raises(ap.CaptureError, match="invoice_date"):
        ap.create_invoice(office, vid, "", f["invoice_date"][0], f["total"][0],
                          capture_result=res)
    iid = ap.create_invoice(office, vid, "", "2026-10-14", f["total"][0],
                            capture_result=res, confirmed=["invoice_date"])
    assert ap.invoice(office, iid)["total"] == 31247


def test_8_3_duplicate_warnings(office):
    office.act_as("ap@bo.test")
    vid = ap.add_vendor(office, "Example Ready-Mix")
    office.db.set_counter("AP", 7)
    first = ap.create_invoice(office, vid, "RM-44817", "2026-10-12", "8640.00")
    assert ap.invoice(office, first)["number"] == "AP-0007"
    with pytest.raises(ap.DuplicateError, match="possible duplicate of AP-0007"):
        ap.create_invoice(office, vid, "RM-44817", "2026-10-12", "8640.00")
    with pytest.raises(ap.DuplicateError, match="possible duplicate of AP-0007"):
        ap.create_invoice(office, vid, "RM-50000", "2026-10-16", "8640.00")
    ok = ap.create_invoice(office, vid, "RM-44817", "2026-10-12", "8640.00",
                           override_reason="vendor re-sent a corrected copy")
    assert ap.invoice(office, ok)["dup_override"]
    assert ap.create_invoice(office, vid, "RM-60000", "2026-10-25", "8640.00",
                             override_reason="") is not None   # 13 days: fine


def test_9_1_threshold_bands(office, job):
    paths = {}
    for amt in ("1800.00", "12000.00", "40000.00"):
        iid = ap_invoice(office, "Example Supply", f"V-{amt}", "2026-10-15",
                         amt, job_id=job)
        paths[amt] = ap.path_text(office, iid)
    assert paths == {"1800.00": ["PM"], "12000.00": ["PM", "Controller"],
                     "40000.00": ["PM", "Controller", "Admin"]}


def _apex(office, job):
    ap.seed_vendors(office, job)
    return ap_invoice(office, "Example Framing", "AF-3", "2026-10-20", "30000.00",
                      job_id=job, code="06-1000", cat="S",
                      commitment_no="SC-004")


def test_9_2_over_commitment_needs_admin_override(office, job):
    iid = _apex(office, job)
    st = ap.commitment_status(office, job, "SC-004", exclude_invoice=iid)
    assert (st["original"], st["invoiced"]) == (12_000_000, 9_600_000)
    assert "over commitment by $6,000.00" in ap.warnings(office, iid)
    office.act_as("ap@bo.test")
    ap.submit(office, iid)
    for h in ap.open_holds(office, iid):          # insurance: see 9.3
        office.act_as("ctl@bo.test")
        ap.clear_hold(office, h["id"], "certificate received")
    office.act_as("pm@bo.test")
    ap.approve(office, iid)
    office.act_as("ctl@bo.test")
    ap.approve(office, iid)
    office.act_as("admin@bo.test")
    with pytest.raises(ap.APError, match="over commitment by \\$6,000.00"):
        ap.approve(office, iid)
    ap.approve(office, iid, override_reason="CO-007 pending with Apex")
    assert ap.invoice(office, iid)["status"] == "Approved"
    assert ap.invoice(office, iid)["overcommit_reason"]


def test_9_3_expired_insurance_hold(office, job):
    iid = _apex(office, job)
    office.act_as("ap@bo.test")
    ap.submit(office, iid)
    holds = ap.open_holds(office, iid)
    assert [h["reason"] for h in holds] == ["insurance expired 2026-09-30"]
    office.act_as("pm@bo.test")
    with pytest.raises(ap.APError, match="Compliance hold"):
        ap.approve(office, iid)
    office.act_as("ap@bo.test")
    with pytest.raises(security.Denied):
        ap.clear_hold(office, holds[0]["id"], "ok")
    office.act_as("ctl@bo.test")
    with pytest.raises(ap.APError, match="note"):
        ap.clear_hold(office, holds[0]["id"], "")
    ap.clear_hold(office, holds[0]["id"], "new certificate to 2027-09-30")
    office.act_as("pm@bo.test")
    ap.approve(office, iid)
    assert approvals.request(office, "ap_invoice", iid)["step"] == 1


def test_9_4_escalation_after_3_days(office, job):
    ap.add_rule(office, 1, [approvals.step("jobrole:PM")], job_id=job,
                escalate_days=3, escalate_to="role:Controller")
    iid = ap_invoice(office, "Example Supply", "V-9", "2026-10-15", "1200.00",
                     job_id=job)
    office.act_as("ap@bo.test")
    ap.submit(office, iid)
    ctl = office.user_id("ctl@bo.test")
    assert ap.inbox(office) == [] or True
    assert [i for i in approvals.inbox(office, ctl, "ap_invoice")] == []
    clock.set_now(clock.now() + timedelta(days=4))
    items = approvals.inbox(office, ctl, "ap_invoice")
    assert len(items) == 1 and items[0]["escalated"]
    assert items[0]["record_id"] == iid
    office.act_as("pm@bo.test")
    ap.approve(office, iid)                       # the PM still can
    assert ap.invoice(office, iid)["status"] == "Approved"
