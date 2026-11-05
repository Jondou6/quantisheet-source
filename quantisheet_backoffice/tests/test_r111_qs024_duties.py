"""QS-024: the person who entered or coded a record cannot approve it."""
import pytest

from quantisheet_backoffice import ap, approvals, security
from quantisheet_backoffice.r111 import duties
from quantisheet_backoffice.security import Denied


def _invoice(office, number="HG-1"):
    vid = ap.vendor_by_name(office, "Harbor Glass Supply")
    vid = vid["id"] if vid else ap.add_vendor(office, "Harbor Glass Supply")
    return ap.create_invoice(
        office, vid, number, "2026-10-12", "40.00",
        lines=[{"cost_code": "03-3000", "amount": "40.00",
                "description": "Glass"}])


def test_enterer_cannot_approve_until_an_admin_allows_it(office):
    iid = _invoice(office, "HG-20")
    uid = office.user["id"]
    ap.add_rule(office, 1, [approvals.step(f"user:{uid}")])
    ap.submit(office, iid)
    from quantisheet_backoffice.r111 import waiting
    with pytest.raises(Denied, match="own record"):
        waiting.approve(office, iid)
    assert ap.invoice(office, iid)["status"] == "In Approval"
    denied = security.audit_rows(office.db, action="denied")
    assert denied and "own record" in (denied[-1]["after"] or "")
    with pytest.raises(Denied, match="Only an Admin"):
        office.act_as("ctl@bo.test")
        duties.set_self_approval(office, True, "one person office")
    office.act_as("admin@bo.test")
    with pytest.raises(duties.DutyError):
        duties.set_self_approval(office, True, " ")
    duties.set_self_approval(office, True, "one person office")
    assert duties.self_approval_on(office)
    waiting.approve(office, iid)
    assert ap.invoice(office, iid)["status"] == "Approved"
    logged = security.audit_rows(office.db, action="self-approval")
    assert logged and "Ann Admin" in (logged[-1]["after"] or "")
    setting = security.audit_rows(office.db, action="self-approval setting")
    assert setting and "one person office" in (setting[-1]["after"] or "")


def test_coder_cannot_approve_and_someone_else_can(office):
    iid = _invoice(office, "HG-21")
    ctl = office.user_id("ctl@bo.test")
    pm = office.user_id("pm@bo.test")
    ap.add_rule(office, 1, [approvals.step(f"user:{ctl}")])
    office.act_as("ctl@bo.test")
    ap.set_lines(office, iid, [{"cost_code": "06-1000", "amount": "40.00",
                                "description": "Coded"}])
    office.act_as("admin@bo.test")
    ap.submit(office, iid)
    office.act_as("ctl@bo.test")
    with pytest.raises(Denied, match="own record"):
        ap.approve(office, iid)
    assert ap.invoice(office, iid)["status"] == "In Approval"
    office.act_as("admin@bo.test")
    approvals.reassign(office, "ap_invoice", iid, pm, "hand to Pat")
    office.act_as("pm@bo.test")
    ap.approve(office, iid)
    assert ap.invoice(office, iid)["status"] == "Approved"


# ---- reviews 1 + 2 (Nov 4): by user id, not by name -------------------------

def test_renaming_the_enterer_does_not_let_them_approve(office):
    from quantisheet_backoffice.r111 import waiting
    iid = _invoice(office, "HG-40")
    uid = office.user["id"]
    assert uid in duties.parties(office, "ap_invoice", iid)
    ap.add_rule(office, 1, [approvals.step(f"user:{uid}")])
    ap.submit(office, iid)
    office.db.conn.execute("UPDATE users SET name = 'Ann A. Admin' "
                           "WHERE id = ?", (uid,))
    office.act_as(uid)
    with pytest.raises(Denied, match="own record"):
        waiting.approve(office, iid)


def test_two_people_with_one_name_are_told_apart(office):
    from quantisheet_backoffice.r111 import waiting
    office.act_as("admin@bo.test")
    twin = security.add_user(office.db, "Ann Admin", "ann2@bo.test",
                             "Approver", "correct horse 7", "")
    iid = _invoice(office, "HG-41")             # entered by the first Ann
    ap.add_rule(office, 1, [approvals.step(f"user:{twin}")])
    ap.submit(office, iid)
    office.act_as("ann2@bo.test")
    waiting.approve(office, iid)                # the other Ann may approve
    assert ap.invoice(office, iid)["status"] == "Approved"
