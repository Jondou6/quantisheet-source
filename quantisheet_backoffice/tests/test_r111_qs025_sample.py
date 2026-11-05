"""The payroll key move on Chief's made-up 1.0.7-style company
(tests/sample_data/payroll_company): datakey.bin beside the database, in
the off-Windows "plain:" form. Always on a copy - the sample is never
changed."""
import os
import shutil
import sys

import pytest

from quantisheet_backoffice import crypto
from quantisheet_backoffice.r111 import paykeys
from quantisheet_backoffice.store import DB

SAMPLE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "tests", "sample_data", "payroll_company")
pytestmark = pytest.mark.skipif(not os.path.isdir(SAMPLE),
                                reason="sample data not present")


def _copy(tmp_path):
    dst = tmp_path / "bo_home" / "sample company"
    shutil.copytree(SAMPLE, dst)
    return str(dst)


def _people(folder, backend):
    fc = crypto.FieldCrypto(folder, backend)
    db = DB(os.path.join(folder, "backoffice.sqlite"))
    db.crypto = fc
    try:
        return fc, db.rows("SELECT name, phone, email, pay_rate FROM "
                           "employees ORDER BY employee_no")
    finally:
        db.close()


def test_sample_moves_and_every_payroll_field_still_opens(tmp_path):
    before = open(os.path.join(SAMPLE, "datakey.bin"), "rb").read()
    folder = _copy(tmp_path)
    be = crypto._OwnerOnlyFile()
    fc, people = _people(folder, be)
    assert [p["phone"] for p in people] == ["555-0100", "555-0101",
                                            "555-0102"]
    assert sorted(p["pay_rate"] for p in people) == [1850, 2500, 3000]
    key = fc.data_key()
    assert key == before[len(b"plain:"):]
    stub = open(os.path.join(folder, "datakey.bin"), "rb").read()
    assert stub.startswith(b"qskey1:") and key not in stub
    # opened again: same key, same people
    fc2, again = _people(folder, be)
    assert fc2.data_key() == key and again == people
    # the sample itself is untouched
    assert open(os.path.join(SAMPLE, "datakey.bin"), "rb").read() == before


@pytest.mark.skipif(sys.platform != "win32", reason="Windows DPAPI only")
def test_a_key_this_login_cant_open_is_refused_not_replaced(tmp_path):
    folder = _copy(tmp_path)
    with pytest.raises(paykeys.PayKeyError, match="NOT made"):
        crypto.FieldCrypto(folder, crypto.default_backend())
    # the old key file is left exactly as it was
    assert open(os.path.join(folder, "datakey.bin"), "rb").read() == \
        open(os.path.join(SAMPLE, "datakey.bin"), "rb").read()
