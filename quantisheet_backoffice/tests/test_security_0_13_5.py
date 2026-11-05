"""0.13.5 security fixes in Back Office: backups need backup.run (and an
export can't get round it), the File menu follows the permission, every
way to plaintext HR data needs hr.reveal, and terminating an employee
needs hr.edit. Made-up people and companies only."""
import pytest

from quantisheet_backoffice import backup, exports, hr, security
from quantisheet_backoffice.security import Denied

from .helpers import ap_invoice, approve_ap
from .m3_helpers import add_hr


def _denied(office, perm):
    return [r for r in security.audit_rows(office.db, action="denied")
            if perm in (r["after"] or "")]


# ---- backup.run ------------------------------------------------------------

@pytest.mark.parametrize("who", ["viewer@bo.test", "ap@bo.test",
                                 "bill@bo.test", "pm@bo.test"])
def test_backup_needs_backup_run(office, tmp_path, who):
    office.act_as(who)
    with pytest.raises(Denied):
        backup.make(office, str(tmp_path / "bk"))
    assert backup.backups(str(tmp_path / "bk")) == []
    assert _denied(office, "backup.run")


@pytest.mark.parametrize("who", ["admin@bo.test", "ctl@bo.test"])
def test_admin_and_controller_can_back_up(office, tmp_path, who):
    office.act_as(who)
    path = backup.make(office, str(tmp_path / "bk"))
    assert backup.backups(str(tmp_path / "bk")) == [path]


def test_not_signed_in_cannot_back_up(office, tmp_path):
    office.user = None
    with pytest.raises(Denied):
        backup.make(office, str(tmp_path / "bk"))


def test_export_alone_does_not_make_a_backup(office, job, tmp_path):
    iid = ap_invoice(office, "Example Framing", "INV-1", "2026-10-02",
                     "312.47", job_id=job)
    approve_ap(office, iid)
    before = backup.backups()
    office.act_as("ap@bo.test")                 # export.run, no backup.run
    assert office.can("export.run") and not office.can("backup.run")
    r = exports.export(office, "ap", "2026-10-01", "2026-10-31", "csv",
                       folder=str(tmp_path / "out"))
    assert r["count"] == 1 and r["path"]
    assert backup.backups() == before            # no company dump written
    assert not _denied(office, "backup.run")     # and nothing tried


def test_export_by_controller_still_backs_up_first(office, job, tmp_path):
    iid = ap_invoice(office, "Example Framing", "INV-2", "2026-10-02",
                     "100.00", job_id=job)
    approve_ap(office, iid)
    before = len(backup.backups())
    office.act_as("ctl@bo.test")
    exports.export(office, "ap", "2026-10-01", "2026-10-31", "csv",
                   folder=str(tmp_path / "out"))
    assert len(backup.backups()) == before + 1


def test_file_menu_follows_permissions(office, qapp):
    from quantisheet_backoffice.ui.main_window import BackOfficeWindow
    office.act_as("viewer@bo.test")
    w = BackOfficeWindow(office)
    assert not w.backup_action.isEnabled()
    assert not w.backup_pw_action.isEnabled()
    assert not w.restore_action.isEnabled()
    w.close()
    office.act_as("ctl@bo.test")
    w = BackOfficeWindow(office)
    assert w.backup_action.isEnabled() and w.restore_action.isEnabled()
    w.close()
    office.act_as("admin@bo.test")
    w = BackOfficeWindow(office)
    assert w.backup_action.isEnabled()
    office.act_as("viewer@bo.test")
    w.update_status()                       # re-checked on a status update
    assert not w.backup_action.isEnabled()
    w.close()


# ---- HR plaintext: hr.reveal -------------------------------------------------

@pytest.fixture
def hro(office):
    add_hr(office)
    office.act_as("hr@bo.test")
    return office


def _example(o):
    return hr.add_employee(o, "Example Worker", "E900", "2026-03-02",
                           labor_class="LAB", ssn="900-00-5555",
                           bank_account="000099990000")


def test_decrypt_field_needs_the_permission(hro):
    eid = _example(hro)
    token = hro.db.get("employees", eid)["ssn"]
    assert hro.decrypt_field("hr.reveal", token, "employee", eid) == \
        "900-00-5555"
    hro.act_as("bill@bo.test")                  # hr.view only
    with pytest.raises(Denied):
        hro.decrypt_field("hr.reveal", token, "employee", eid)
    with pytest.raises(Denied):
        hr.reveal(hro, eid, "ssn")
    assert hr.employee(hro, eid)["ssn"] == "***-**-5555"   # masked is fine
    hro.act_as("viewer@bo.test")
    with pytest.raises(Denied):
        hro.decrypt_field("hr.reveal", token, "employee", eid)


def test_hr_documents_need_reveal(hro, tmp_path):
    eid = _example(hro)
    f = tmp_path / "w4.pdf"
    f.write_bytes(b"%PDF-1.4 example W-4")
    did = hr.add_document(hro, eid, "W-4 federal withholding", str(f))
    assert hr.open_document(hro, did) == b"%PDF-1.4 example W-4"
    hro.act_as("ctl@bo.test")                   # hr.view, no hr.reveal
    with pytest.raises(Denied):
        hr.open_document(hro, did)
    hro.act_as("hr@bo.test")
    with pytest.raises(hr.HRError):
        hr.open_document(hro, 999999)


# ---- hr.terminate: hr.edit ----------------------------------------------------

def test_terminate_needs_hr_edit(hro):
    eid = _example(hro)
    hro.act_as("bill@bo.test")                  # hr.view, no hr.edit
    with pytest.raises(Denied):
        hr.terminate(hro, eid, "2027-01-15")
    e = hro.db.get("employees", eid)
    assert e["status"] != "Terminated" and not e["termination_date"]
    assert hro.db.get("workers", e["worker_id"])["active"] == 1
    assert _denied(hro, "hr.edit")
    hro.act_as("hr@bo.test")
    hr.terminate(hro, eid, "2027-01-15")
    assert hro.db.get("employees", eid)["status"] == "Terminated"
