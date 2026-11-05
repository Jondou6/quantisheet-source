"""Invoice folder, approval stamp, waiting-on-me, vendor memory.
Made-up vendors and amounts only.
"""
import os

import pytest

from quantisheet_backoffice import ap, approvals, security, store
from quantisheet_backoffice.r111 import apdrop, apstamp, vendmem, waiting


def _invoice_pdf(path, number, vendor="Harbor Glass Supply", total="864.00"):
    import fitz
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((54, 72),
                     f"{vendor}\n100 Dock St\n\nINVOICE\n"
                     f"Invoice No: {number}\nInvoice Date: 2026-10-12\n"
                     f"Due Date: 2026-11-11\n\nGlass panes  {total}\n"
                     f"Total Due: ${total}\n", fontsize=11)
    doc.save(path)
    doc.close()


def test_drop_folder_captures_and_skips_prn(office, job, tmp_path):
    office.act_as("ap@bo.test")
    vid = ap.add_vendor(office, "Harbor Glass Supply")
    first = str(tmp_path / "hg-100.pdf")
    _invoice_pdf(first, "HG-100")
    res = ap.capture(office, first)
    iid = ap.create_invoice(
        office, vid, "HG-100", "2026-10-12", "864.00", job_id=job,
        lines=[{"cost_code": "03-3000", "amount": "864.00"}],
        capture_result=res)
    vendmem.learn_invoice(office, iid)
    folder = tmp_path / "incoming"
    folder.mkdir()
    _invoice_pdf(str(folder / "hg-101.pdf"), "HG-101", total="912.50")
    (folder / "printer.PRN").write_text("skip me", encoding="utf-8")
    (folder / "notes.txt").write_text("skip me", encoding="utf-8")
    apdrop.set_folder(office, str(folder))
    found = apdrop.scan(office)
    assert len(found) == 1
    assert found[0]["status"] == "captured"
    inv = ap.invoice(office, found[0]["invoice_id"])
    assert inv["job_id"] == job
    assert ap.lines(office, inv["id"])[0]["cost_code"] == "03-3000"
    assert apdrop.scan(office) == []
    office.act_as("viewer@bo.test")
    with pytest.raises(security.Denied):
        apdrop.scan(office)


def test_needs_review_when_the_total_is_missing(office, tmp_path):
    import fitz
    office.act_as("ap@bo.test")
    ap.add_vendor(office, "Harbor Glass Supply")
    folder = tmp_path / "incoming"
    folder.mkdir()
    path = str(folder / "blank.pdf")
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((54, 72), "Harbor Glass Supply\nInvoice No: HG-9\n"
                     "Invoice Date: 2026-10-12\n", fontsize=11)
    doc.save(path)
    doc.close()
    apdrop.set_folder(office, str(folder))
    found = apdrop.scan(office)
    assert found[0]["status"] == "needs_review"
    assert found[0]["invoice_id"] is None


def test_vendor_layout_and_approval_path(office, job, tmp_path):
    office.act_as("ap@bo.test")
    vid = ap.add_vendor(office, "Harbor Glass Supply")
    a = str(tmp_path / "a.pdf")
    b = str(tmp_path / "b.pdf")
    other = str(tmp_path / "other.pdf")
    _invoice_pdf(a, "HG-1")
    _invoice_pdf(b, "HG-2")
    _invoice_pdf(other, "ZZ-1", vendor="Other Glass Co", total="10.00")
    same = vendmem.layout_score(vendmem.layout_of(a), vendmem.layout_of(b))
    diff = vendmem.layout_score(vendmem.layout_of(a), vendmem.layout_of(other))
    assert same >= 70
    assert diff < same
    res = ap.capture(office, a)
    res_b = ap.capture(office, b)
    iid = ap.create_invoice(
        office, vid, "HG-1", "2026-10-12", "864.00", job_id=job,
        lines=[{"cost_code": "06-1000", "amount": "864.00"}],
        capture_result=res)
    steps = [approvals.step("role:Controller")]
    vendmem.remember(office, vid, res["doc_path"], job, "06-1000", steps)
    hint = vendmem.suggest(office, res_b)
    assert hint["job_id"] == job and hint["cost_code"] == "06-1000"
    assert hint["approval_steps"][0]["principals"] == ["role:Controller"]
    assert hint["layout_score"] >= 70
    office.act_as("admin@bo.test")
    vendmem.apply_rule(office, vid)
    office.act_as("ap@bo.test")
    assert ap.path_text(office, iid) == ["Controller"]


def test_stamp_leaves_the_original_and_names_the_approval(office, job, tmp_path):
    office.act_as("ap@bo.test")
    vid = ap.add_vendor(office, "Harbor Glass Supply")
    src = str(tmp_path / "hg-200.pdf")
    _invoice_pdf(src, "HG-200")
    res = ap.capture(office, src)
    iid = ap.create_invoice(
        office, vid, "HG-200", "2026-10-12", "864.00", job_id=job,
        lines=[{"cost_code": "03-3000", "amount": "864.00"}],
        capture_result=res)
    original = ap.invoice(office, iid)["doc_path"]
    before = store.file_hash(original)
    ap.submit(office, iid)
    office.act_as("pm@bo.test")
    done = waiting.approve(office, iid)
    assert ap.invoice(office, iid)["status"] == "Approved"
    assert store.file_hash(original) == before
    stamped = done["stamped"]
    assert os.path.isfile(stamped) and store.file_hash(stamped) != before
    import fitz
    text = fitz.open(stamped)[0].get_text()
    assert "APPROVED" in text
    assert "2611" in text and "03-3000" in text
    assert "$864.00" in text
    assert "Pat Morgan" in text
    assert "2026-10-22" in text
    remembered = vendmem.for_vendor(office, vid)
    assert remembered["cost_code"] == "03-3000"
    assert remembered["job_id"] == job


def test_waiting_reject_needs_a_reason(office, job, tmp_path):
    office.act_as("ap@bo.test")
    vid = ap.add_vendor(office, "Harbor Glass Supply")
    iid = ap.create_invoice(
        office, vid, "HG-300", "2026-10-12", "50.00", job_id=job,
        lines=[{"cost_code": "03-3000", "amount": "50.00"}])
    ap.submit(office, iid)
    office.act_as("pm@bo.test")
    assert [r["invoice_id"] for r in waiting.mine(office)] == [iid]
    with pytest.raises(approvals.ApprovalError):
        waiting.reject(office, iid, "")
    waiting.reject(office, iid, "Wrong job")
    assert ap.invoice(office, iid)["status"] == "Rejected"
    assert waiting.mine(office) == []


def test_stamp_refuses_a_draft(office, job):
    office.act_as("ap@bo.test")
    vid = ap.add_vendor(office, "Harbor Glass Supply")
    iid = ap.create_invoice(
        office, vid, "HG-1", "2026-10-12", "10.00", job_id=job,
        lines=[{"cost_code": "03-3000", "amount": "10.00"}])
    with pytest.raises(apstamp.StampError):
        apstamp.stamp_invoice(office, iid)
