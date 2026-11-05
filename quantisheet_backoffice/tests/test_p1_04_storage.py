"""P1-04 storage, exact money, backups and PII encryption (4.1-4.3)."""
import os
import sqlite3

import pytest

from quantisheet_backoffice import billing, cents
from quantisheet_backoffice.office import Office
from quantisheet_backoffice.store import DB

from .helpers import import_stage


def test_4_1_exact_money(office):
    db = office.db
    with db.tx():
        a = db.insert("credits", customer="x", amount=cents.to_cents("0.10"))
        b = db.insert("credits", customer="x", amount=cents.to_cents("0.20"))
    s = db.get("credits", a)["amount"] + db.get("credits", b)["amount"]
    assert cents.from_cents(s) == cents.D("0.30")
    assert cents.fmt(s) == "$0.30"
    assert cents.pct_of(cents.to_cents("1234.55"), "10") == 12346   # half up
    parts = cents.split(cents.to_cents("100.00"), 3)
    assert parts == [3334, 3333, 3333] and sum(parts) == 10000
    with pytest.raises(cents.MoneyError):
        cents.to_cents(0.1)
    with pytest.raises(TypeError):
        db.insert("credits", customer="x", amount=0.3)


def test_4_2_backup_delete_restore(office, job3, tmp_path):
    billing.set_contract(office, job3, contact_email="dana@example.test")
    for n in (1, 2, 3):
        billing.approve(office, billing.invoice_from_payapp(office, job3, n))
    before = office.db.row_counts()
    total = office.db.scalar("SELECT SUM(total) FROM ar_invoices")
    from quantisheet_backoffice import backup
    bk = backup.make(office, str(tmp_path / "bk"))
    path, folder = office.db.path, office.folder
    office.close()
    os.remove(path)
    assert not os.path.exists(path)
    backup.restore(folder, bk)
    o2 = Office(folder)
    after = o2.db.row_counts()
    assert after.pop("audit") == before.pop("audit") + 1   # + the restore
    assert after == before
    assert o2.db.rows("SELECT action FROM audit ORDER BY id DESC LIMIT 1"
                      )[0]["action"] == "restore"
    assert o2.db.scalar("SELECT SUM(total) FROM ar_invoices") == total == \
        5400000 + 8100000 + 6750000
    assert backup.backup_date(bk)
    o2.close()


def test_4_3_tax_id_is_ciphertext_on_disk(office):
    from quantisheet_backoffice import ap
    vid = ap.add_vendor(office, "Example Framing", tax_id="00-0000001")
    office.close()
    raw = open(os.path.join(office.folder, "backoffice.sqlite"), "rb").read()
    assert b"00-0000001" not in raw and b"000000001" not in raw
    con = sqlite3.connect(os.path.join(office.folder, "backoffice.sqlite"))
    stored = con.execute("SELECT tax_id FROM vendors WHERE id = ?",
                         (vid,)).fetchone()[0]
    con.close()
    assert stored.startswith("enc1:") and "7654321" not in stored
    o2 = Office(office.folder)
    o2.act_as("ctl@bo.test")
    assert ap.vendor_tax_id(o2, vid) == "*****0001"
    assert ap.vendor_tax_id(o2, vid, reveal=True) == "00-0000001"
    assert "Sensitive fields encrypted" in o2.crypto.status()
    o2.close()
