"""QS-025: payroll data key stays out of the company folder, logs and exports."""
import os

from quantisheet_backoffice import hr, security
from quantisheet_backoffice.r111 import paykeys
from quantisheet_backoffice.server.app import ServerApp


def _raw_key(office) -> bytes:
    return office.crypto.data_key()


def test_key_is_sealed_outside_the_company_folder(office):
    key = _raw_key(office)
    company = office.folder
    stub = open(os.path.join(company, "datakey.bin"), "rb").read()
    assert stub.startswith(b"qskey1:")
    assert key not in stub
    assert b"plain:" not in stub
    slot = paykeys.location(company)
    assert not os.path.realpath(slot).startswith(os.path.realpath(company) + os.sep)
    sealed = open(slot, "rb").read()
    assert sealed.startswith(b"sealed1:")
    assert key not in sealed
    assert key not in open(office.db.path, "rb").read()


def test_rotate_and_key_backup_roundtrip(office, tmp_path):
    eid = hr.add_employee(office, "A. Nguyen", "E900", "2026-03-02",
                          ssn="900-00-1111")
    assert hr.reveal(office, eid, "ssn") == "900-00-1111"
    before = _raw_key(office)
    done = paykeys.rotate(office)
    assert done["fields"] >= 1
    assert _raw_key(office) != before
    assert hr.reveal(office, eid, "ssn") == "900-00-1111"
    assert security.verify_chain(office.db)["ok"]
    blob = b"".join(open(p, "rb").read()
                    for p in (office.db.path,
                              os.path.join(office.folder, "datakey.bin")))
    assert _raw_key(office) not in blob
    assert before not in blob
    text = " ".join((r["after"] or "") + (r["before"] or "")
                    for r in security.audit_rows(office.db))
    assert before.decode() not in text
    assert _raw_key(office).decode() not in text
    path = paykeys.backup(office, str(tmp_path / "payroll.qskey"),
                          "correct horse 7")
    backed = open(path, "rb").read()
    assert backed.startswith(b"QSKEY1\n")
    assert _raw_key(office) not in backed
    os.remove(paykeys.location(office.folder))
    paykeys.restore(office, path, "correct horse 7")
    assert hr.reveal(office, eid, "ssn") == "900-00-1111"


def test_server_key_is_not_plaintext_in_the_data_dir(tmp_path):
    data = tmp_path / "srv"
    app = ServerApp(str(data), office_token="t" * 24)
    stub = (data / "server.key").read_bytes()
    assert stub.startswith(b"qskey1:")
    token = app.f.encrypt(b"payroll")
    assert app.f.decrypt(token) == b"payroll"
    assert token not in stub
