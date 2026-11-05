"""P1-03 users, roles, approvals inbox and audit trail (3.1-3.3)."""
from datetime import datetime, timedelta

import pytest

from quantisheet_backoffice import ap, clock, security

from .helpers import PW


def test_3_1_viewer_cannot_edit_ap_invoice(office, job, qapp):
    office.act_as("ap@bo.test")
    vid = ap.add_vendor(office, "Example Ready-Mix")
    iid = ap.create_invoice(office, vid, "RM-1", "2026-10-12", "100.00",
                            job_id=job, lines=[{"cost_code": "03-3000",
                                                "amount": "100.00"}])
    office.act_as("viewer@bo.test")
    from quantisheet_backoffice.ui.ap_invoice import APInvoiceDialog
    dlg = APInvoiceDialog(office, iid)
    assert dlg.edit_buttons() and all(not b.isEnabled() for b in dlg.edit_buttons())
    assert all(f.isReadOnly() for f in dlg.fields())
    dlg.close()
    with pytest.raises(security.Denied):
        ap.save(office, iid, invoice_no="RM-2")
    assert ap.invoice(office, iid)["invoice_no"] == "RM-1"
    denied = security.audit_rows(office.db, user="Dana Ortiz", action="denied")
    assert denied and denied[-1]["record_type"] == "ap_invoice"


def test_3_2_tampered_audit_entry_breaks_chain(office):
    for i in range(5):
        office.audit("change", "test", i, {"v": i}, {"v": i + 1})
    assert security.verify_chain(office.db)["ok"]
    ids = [r["id"] for r in office.db.rows("SELECT id FROM audit ORDER BY id")]
    target = ids[-3]
    con = office.db.conn
    with pytest.raises(Exception):          # append-only in normal use
        con.execute("UPDATE audit SET after = 'x' WHERE id = ?", (target,))
    con.execute("DROP TRIGGER audit_no_update")        # 'by hand'
    con.execute("UPDATE audit SET after = '{\"v\": 99}' WHERE id = ?", (target,))
    res = security.verify_chain(office.db)
    assert not res["ok"] and res["broken_from"] == target
    assert res["broken"] == [i for i in ids if i >= target]


def test_3_3_five_wrong_passwords_lock_for_15_minutes(office):
    for _ in range(4):
        with pytest.raises(security.AuthError, match="Wrong"):
            office.sign_in("ap@bo.test", "nope")
    with pytest.raises(security.AuthError, match="locked for 15 minutes"):
        office.sign_in("ap@bo.test", "nope")
    with pytest.raises(security.AuthError, match="locked"):
        office.sign_in("ap@bo.test", PW)          # right password, still locked
    assert security.audit_rows(office.db, action="lockout")
    clock.set_now(clock.now() + timedelta(minutes=16))
    assert office.sign_in("ap@bo.test", PW)["role"] == "AP Clerk"
