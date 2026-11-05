"""QS-020: capture, drop folder and manual entry block duplicates."""
import shutil

import pytest

from quantisheet_backoffice import ap, security
from quantisheet_backoffice.r111 import apdrop


def _pdf(path, number="HG-1", total="220.00"):
    import fitz
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((54, 72),
                     "Harbor Glass Supply\n100 Dock St\n\nINVOICE\n"
                     f"Invoice No: {number}\nInvoice Date: 2026-10-12\n"
                     f"Total Due: ${total}\n", fontsize=11)
    doc.save(path)
    doc.close()


def test_capture_blocks_number_amount_and_file_hash(office, tmp_path):
    office.act_as("ap@bo.test")
    vid = ap.add_vendor(office, "Harbor Glass Supply")
    src = str(tmp_path / "a.pdf")
    _pdf(src, "HG-1", "220.00")
    res = ap.capture(office, src)
    iid = ap.create_invoice(
        office, vid, "HG-1", "2026-10-12", "220.00", capture_result=res,
        lines=[{"amount": "220.00"}])
    again = str(tmp_path / "b.pdf")
    _pdf(again, "HG-1", "220.00")
    with pytest.raises(ap.DuplicateError, match="same invoice number"):
        ap.capture(office, again)
    other = str(tmp_path / "c.pdf")
    _pdf(other, "HG-9", "220.00")
    with pytest.raises(ap.DuplicateError, match="within 7 days"):
        ap.capture(office, other)
    copy = str(tmp_path / "a-copy.pdf")
    shutil.copyfile(src, copy)
    with pytest.raises(ap.DuplicateError, match="same file"):
        ap.capture(office, copy)
    kept = ap.capture(office, copy, override_reason="second copy of the scan")
    assert kept["duplicate_override"]["who"] == "Alice Clerk"
    row = office.db.one("SELECT * FROM dup_overrides WHERE doc_hash = ? "
                        "ORDER BY id DESC LIMIT 1", (kept["doc_hash"],))
    assert row["who"] == "Alice Clerk"
    assert "scan" in row["why"]
    with pytest.raises(ap.DuplicateError, match="same file"):
        ap.create_invoice(office, vid, "HG-2", "2026-11-01", "10.00",
                          capture_result=res)
    ok = ap.create_invoice(
        office, vid, "HG-1", "2026-10-12", "220.00",
        override_reason="vendor confirmed this is a new bill",
        lines=[{"amount": "220.00"}])
    saved = office.db.one("SELECT * FROM dup_overrides WHERE invoice_id = ?",
                          (ok,))
    assert saved["who"] == "Alice Clerk"
    assert "vendor confirmed" in saved["why"]
    assert ap.invoice(office, iid)["doc_hash"]


def test_drop_folder_override_records_who(office, tmp_path):
    office.act_as("ap@bo.test")
    vid = ap.add_vendor(office, "Harbor Glass Supply")
    src = str(tmp_path / "orig.pdf")
    _pdf(src, "HG-7", "80.00")
    res = ap.capture(office, src)
    ap.create_invoice(office, vid, "HG-7", "2026-10-12", "80.00",
                      capture_result=res, lines=[{"amount": "80.00"}])
    folder = tmp_path / "in"
    folder.mkdir()
    shutil.copyfile(src, folder / "again.pdf")
    apdrop.set_folder(office, str(folder))
    found = apdrop.scan(office)
    assert len(found) == 1 and found[0]["status"] == "duplicate"
    assert "duplicate" in found[0]["message"]
    with pytest.raises(apdrop.DropError):
        apdrop.accept_duplicate(office, found[0]["id"], "  ")
    iid = apdrop.accept_duplicate(office, found[0]["id"],
                                  "clerk checked the second scan")
    assert ap.invoice(office, iid)["status"] == "Draft"
    row = office.db.one("SELECT * FROM dup_overrides WHERE invoice_id = ?",
                        (iid,))
    assert row["who"] == "Alice Clerk" and "second scan" in row["why"]
    office.act_as("viewer@bo.test")
    with pytest.raises(security.Denied):
        apdrop.accept_duplicate(office, found[0]["id"], "no")
