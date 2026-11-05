"""Nov 4 wiring: Allow This Duplicate on the Payables folder bar, and the
Payroll Key & Approvals page. Made-up data only."""
import shutil

from quantisheet_backoffice import ap, hr
from quantisheet_backoffice.r111 import apdrop, duties
from quantisheet_backoffice.r111.ui import DropFolderBar, SecurityPage
from quantisheet_backoffice.ui.main_window import NAV, PAGES

from .test_r111_qs020_duplicates import _pdf


def test_page_is_on_the_nav():
    assert "Payroll Key & Approvals" in NAV
    assert PAGES["Payroll Key & Approvals"] is SecurityPage


def test_allow_this_duplicate_from_the_folder_bar(office, tmp_path, qapp):
    office.act_as("ap@bo.test")
    vid = ap.add_vendor(office, "Harbor Glass Supply")
    src = str(tmp_path / "orig.pdf")
    _pdf(src, "HG-9", "75.00")
    res = ap.capture(office, src)
    ap.create_invoice(office, vid, "HG-9", "2026-10-12", "75.00",
                      capture_result=res, lines=[{"amount": "75.00"}])
    folder = tmp_path / "in"
    folder.mkdir()
    shutil.copyfile(src, folder / "again.pdf")
    bar = DropFolderBar(office)
    bar.timer.stop()
    bar.path.setText(str(folder))
    bar.use_folder()
    bar.scan_now()
    assert bar.dups.rowCount() == 1
    bar.dups.selectRow(0)
    assert bar.allow_selected("  ") is None            # a reason is needed
    iid = bar.allow_selected("second scan checked by clerk")
    assert iid and ap.invoice(office, iid)
    assert bar.dups.rowCount() == 0


def test_security_page_backup_rotate_restore(office, tmp_path, qapp):
    eid = hr.add_employee(office, "Q. Example", "E300", "2026-03-02",
                          ssn="900-00-4444")
    keyfile = str(tmp_path / "k.qskey")
    pg = SecurityPage(office, pick_save=lambda: keyfile,
                      pick_open=lambda: keyfile,
                      ask_password=lambda t: "example pass 1")
    assert pg.backup() == keyfile
    done = pg.rotate(confirmed=True)
    assert done and done["fields"] >= 1
    assert hr.reveal(office, eid, "ssn") == "900-00-4444"
    assert pg.restore() is True                      # the pre-rotate key
    assert hr.reveal(office, eid, "ssn") == "900-00-4444"


def test_self_approval_toggle_is_admin_only(office, qapp):
    pg = SecurityPage(office)
    assert "off" in pg.selfapp.text()
    assert pg.toggle_self_approval("one-person office") is True
    assert duties.self_approval_on(office)
    office.act_as("ap@bo.test")
    assert pg.toggle_self_approval("try") is None
    assert duties.self_approval_on(office)


def test_missing_key_offers_the_backup(office, tmp_path, monkeypatch):
    import os
    from quantisheet_backoffice import settings
    from quantisheet_backoffice.__main__ import open_or_restore_key
    from quantisheet_backoffice.office import Office
    from quantisheet_backoffice.r111 import paykeys
    pg = SecurityPage(office, pick_save=lambda: str(tmp_path / "k.qskey"),
                      ask_password=lambda t: "example pass 1")
    pg.backup()
    folder = office.folder
    key = office.crypto.data_key()
    office.close()
    shutil.rmtree(os.path.dirname(paykeys.location(folder)))
    monkeypatch.setattr(settings, "data_folder", lambda: folder)
    asked = []

    def ask(msg):
        asked.append(msg)
        return (str(tmp_path / "k.qskey"), "example pass 1")
    o = open_or_restore_key(lambda: Office(folder), ask=ask)
    assert asked and "NOT made" in asked[0]
    assert o.crypto.data_key() == key
    o.close()


# ---- Nov 4 help-page check: two field screens ---------------------------

def _job(office, number="99-J-1"):
    return office.db.insert("jobs", number=number, name="Example Job",
                            project={}, retainage_work="0",
                            retainage_stored="0", state="",
                            last_snapshot_at="", source={})


def test_blank_signature_pad_is_not_a_signature(office, qapp):
    from quantisheet_backoffice.r111 import safety
    from quantisheet_backoffice.r111.ui import SafetyPage
    pg = SafetyPage(office)
    if pg.topics.count() == 0:
        import pytest
        pytest.skip("no safety topics seeded")
    pg.who.setText("A. Example")
    pg.pad.strokes = []
    pg.add_signed()
    assert "sign on the pad" in pg.status.text()
    assert pg.meeting_id is None or not office.db.rows(
        "SELECT id FROM safety_attendees WHERE deleted = 0")


def test_pre_task_plan_saves_what_is_typed(office, qapp):
    from quantisheet_backoffice.r111 import jha
    from quantisheet_backoffice.r111.ui import JhaPage
    _job(office)
    pg = JhaPage(office)
    pg.job.setText("99-J-1")
    pg.task.setText("Set trusses")
    pg.hazards.setPlainText("Falls")
    pg.controls.setPlainText("Harness and tie-off")
    pid = pg.save_plan()
    assert pid and jha.get_plan(office, pid)["task"] == "Set trusses"
    pg.task.setText("Set and brace trusses")
    assert pg.save_plan() == pid                    # same plan, updated
    assert jha.get_plan(office, pid)["task"] == "Set and brace trusses"


# ---- reviews 1 + 2 (Nov 4): a payroll key backup is asked for ---------------

def test_key_backup_is_asked_for_until_one_exists(office, tmp_path, qapp):
    from quantisheet_backoffice.__main__ import ask_key_backup
    from quantisheet_backoffice.r111 import paykeys
    assert paykeys.needs_backup(office)
    asked = []
    keyfile = str(tmp_path / "k.qskey")
    pg = SecurityPage(office, pick_save=lambda: keyfile,
                      ask_password=lambda t: "example pass 1")
    # "Remind Me Next Time": nothing made, asked again next start
    assert ask_key_backup(None, office, page=pg,
                          ask=lambda t: asked.append(t) or False) is False
    assert paykeys.needs_backup(office)
    assert ask_key_backup(None, office, page=pg,
                          ask=lambda t: asked.append(t) or True) is True
    assert "Windows reset" in asked[0]
    assert not paykeys.needs_backup(office)
    # a rotation makes a new key: a new backup is needed
    pg.rotate(confirmed=True)
    assert paykeys.needs_backup(office)


def test_backup_is_read_back_before_it_counts(office, tmp_path, monkeypatch):
    from quantisheet_backoffice.r111 import paykeys
    real = paykeys._write_file

    def torn(path, data):
        real(path, data[:-10] if path.endswith(".qskey") else data)
    monkeypatch.setattr(paykeys, "_write_file", torn)
    import pytest
    with pytest.raises(paykeys.PayKeyError):
        paykeys.backup(office, str(tmp_path / "bad.qskey"),
                       "example pass 1")
    assert paykeys.needs_backup(office)


def test_viewers_are_not_asked(office, qapp):
    from quantisheet_backoffice.__main__ import ask_key_backup
    office.act_as("viewer@bo.test")
    assert ask_key_backup(None, office, ask=lambda t: True) is False


def test_last_key_backup_date_and_home_warning(office, tmp_path, qapp):
    from quantisheet_backoffice.r111 import paykeys
    from quantisheet_backoffice.ui.main_window import HomePage
    pg = SecurityPage(office, pick_save=lambda: str(tmp_path / "k.qskey"),
                      ask_password=lambda t: "example pass 1")
    assert "NEVER" in pg.where.text()
    assert any("never backed up" in k for k in HomePage(office).counts)
    pg.backup()
    pg.refresh()
    assert "Last key backup: 20" in pg.where.text()
    assert paykeys.last_backup(office)["file"] == "k.qskey"
    assert not any("never backed up" in k for k in HomePage(office).counts)
    assert "each new Windows user" in paykeys.MISSING


def test_recurring_vendor_same_amount_is_not_a_duplicate(office):
    from quantisheet_backoffice import ap
    from quantisheet_backoffice.r111 import dupblock
    office.act_as("ap@bo.test")
    vid = ap.add_vendor(office, "Example Fuel Cards")
    ap.create_invoice(office, vid, "F-1", "2026-10-01", "250.00",
                      lines=[{"amount": "250.00"}])
    got = dupblock.find(office, vid, "F-2", 25000, "2026-10-05")
    assert got and "same vendor and amount" in got[0]
    dupblock.set_recurring(office, vid, True)
    assert dupblock.find(office, vid, "F-2", 25000, "2026-10-05") == []
    # the same invoice number is still caught
    assert dupblock.find(office, vid, "F-1", 25000, "2026-10-05")


def test_prn_refusal_says_how_to_print_to_pdf(tmp_path):
    import pytest
    from quantisheet_backoffice.r111 import sagejc
    p = tmp_path / "report.PRN"
    p.write_text("x")
    with pytest.raises(sagejc.SageError, match="Print to PDF"):
        sagejc.read_pdf(str(p))


def test_retire_old_keys_after_a_rotation(office, tmp_path, qapp):
    from quantisheet_backoffice.r111 import paykeys
    eid = hr.add_employee(office, "K. Example", "E400", "2026-03-02",
                          ssn="900-00-5555")
    first = office.crypto.data_key()
    pg = SecurityPage(office)
    assert pg.retire(confirmed=True) == 0          # nothing kept yet
    pg.rotate(confirmed=True)
    assert paykeys.retired_keys(office)
    assert "older key(s) kept" in pg.where.text()
    assert pg.retire(confirmed=True) >= 1
    assert paykeys.retired_keys(office) == []
    assert hr.reveal(office, eid, "ssn") == "900-00-5555"
    from cryptography.fernet import MultiFernet
    assert not isinstance(office.crypto._f, MultiFernet) or \
        len(office.crypto._f._fernets) == 1
    assert office.crypto.data_key() != first


def test_retire_is_refused_while_something_needs_an_old_key(office):
    import pytest
    from quantisheet_backoffice.r111 import paykeys
    token = office.crypto.encrypt("left under the first key")
    office.db.conn.execute("CREATE TABLE extra_notes (id INTEGER PRIMARY "
                           "KEY, v TEXT)")
    office.db.conn.execute("INSERT INTO extra_notes (v) VALUES (?)",
                           (token,))
    paykeys.rotate(office)          # extra_notes.v is re-encrypted too...
    office.db.conn.execute("UPDATE extra_notes SET v = ?", (token,))
    with pytest.raises(paykeys.PayKeyError, match="still need an old key"):
        paykeys.retire_old_keys(office)
