"""QS-025 follow-up (Nov 4): moving the payroll key must never cost
existing payroll data. Made-up data only."""
import os
import shutil

import pytest
from cryptography.fernet import Fernet

from quantisheet_backoffice import crypto, hr, settings
from quantisheet_backoffice.office import Office
from quantisheet_backoffice.r111 import paykeys


def _open(folder):
    o = Office(str(folder))
    o.act_as("admin@bo.test")
    return o


def _legacy_company(tmp_path):
    """A company folder as 1.0.7 left it: datakey.bin beside the DB."""
    from .helpers import make_office
    folder = tmp_path / "bo_home" / "company"
    o = make_office(str(folder))
    eid = hr.add_employee(o, "T. Example", "E100", "2026-01-05",
                          ssn="900-00-2222")
    key = o.crypto.data_key()
    o.db.close()
    shutil.rmtree(os.path.dirname(paykeys.location(str(folder))))
    be = crypto.default_backend()
    with open(folder / "datakey.bin", "wb") as fh:
        fh.write(be.protect(key))
    return folder, eid, key


def test_legacy_key_moves_and_old_payroll_still_opens(tmp_path):
    folder, eid, key = _legacy_company(tmp_path)
    raw = open(folder / "datakey.bin", "rb").read()
    o = _open(folder)
    assert o.crypto.data_key() == key
    assert hr.reveal(o, eid, "ssn") == "900-00-2222"
    stub = open(folder / "datakey.bin", "rb").read()
    assert stub.startswith(b"qskey1:") and key not in stub
    slot = os.path.dirname(paykeys.location(str(folder)))
    assert open(os.path.join(slot, "legacy-datakey.bin"), "rb").read() == raw


def test_missing_key_is_an_error_not_a_new_key(tmp_path):
    folder, _eid, key = _legacy_company(tmp_path)
    Office(str(folder)).db.close()                 # migrates
    shutil.rmtree(os.path.dirname(paykeys.location(str(folder))))
    with pytest.raises(paykeys.PayKeyError, match="NOT made"):
        Office(str(folder))
    # nothing was minted in its place
    assert not os.path.isfile(paykeys.location(str(folder)))


def test_moved_folder_finds_its_key(tmp_path):
    folder, _eid, key = _legacy_company(tmp_path)
    Office(str(folder)).db.close()
    moved = tmp_path / "bo_home" / "renamed company"
    os.replace(folder, moved)
    o = _open(moved)
    assert o.crypto.data_key() == key


def test_restore_file_without_opening(tmp_path):
    folder, eid, key = _legacy_company(tmp_path)
    _open(folder).db.close()
    # a backup made the same way paykeys.backup writes it
    import json
    salt = os.urandom(16)
    pk = crypto.backup_key("correct horse 7", salt, 1000)
    blob = paykeys.MAGIC + json.dumps(
        {"format": 1, "salt": salt.hex(), "rounds": 1000}).encode() + \
        b"\n" + Fernet(pk).encrypt(key)
    bk = tmp_path / "k.qskey"
    bk.write_bytes(blob)
    shutil.rmtree(os.path.dirname(paykeys.location(str(folder))))
    with pytest.raises(paykeys.PayKeyError):
        Office(str(folder))
    with pytest.raises(paykeys.PayKeyError, match="Wrong"):
        paykeys.restore_file(str(folder), str(bk), "wrong password!")
    paykeys.restore_file(str(folder), str(bk), "correct horse 7")
    assert Office(str(folder)).crypto.data_key() == key


def test_failed_rotate_leaves_everything_readable(office, monkeypatch):
    eid = hr.add_employee(office, "R. Sample", "E200", "2026-02-02",
                          ssn="900-00-3333")
    before = office.crypto.data_key()
    from quantisheet_backoffice import security

    def boom(*a, **k):
        raise RuntimeError("power cut")
    monkeypatch.setattr(security, "rekey_chain", boom)
    with pytest.raises(RuntimeError):
        paykeys.rotate(office)
    assert office.crypto.data_key() == before
    assert hr.reveal(office, eid, "ssn") == "900-00-3333"
    assert security.verify_chain(office.db)["ok"]


def test_values_under_a_retired_key_still_open(office):
    token = office.crypto.encrypt("held under the first key")
    paykeys.rotate(office)
    assert office.crypto.decrypt(token) == "held under the first key"
