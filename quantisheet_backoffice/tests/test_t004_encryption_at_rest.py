"""Threat model T-004 (0.13.14): payroll, pay rates, contact details and
the audit details are encrypted in the database file; the audit chain is
keyed with a key kept outside the database (made-up data only)."""
import os
import re
import sqlite3

import pytest

from quantisheet_backoffice import hr, payroll, security, store

from .helpers import *  # noqa: F401,F403


def _raw(office, sql, params=()):
    con = sqlite3.connect(office.db.path)
    try:
        return con.execute(sql, params).fetchall()
    finally:
        con.close()


def test_contact_and_pay_rate_are_encrypted_on_disk(office):
    office.act_as("admin@bo.test")
    eid = hr.add_employee(office, "Example Worker", "E-901", "2026-01-05",
                          address="12 Example Ln", phone="555-0100",
                          email="worker@example.invalid")
    wid = hr.employee(office, eid)["worker_id"]
    payroll.pay_setup(office, wid, pay_rate="31.25")
    (addr, phone, email, rate), = _raw(
        office, "SELECT address, phone, email, pay_rate FROM employees "
        "WHERE id = ?", (eid,))
    for v in (addr, phone, email, rate):
        assert str(v).startswith("enc2:")
    raw = open(office.db.path, "rb").read()
    assert b"12 Example Ln" not in raw and b"worker@example" not in raw
    e = hr.employee(office, eid)
    assert e["address"] == "12 Example Ln" and e["email"].startswith("worker")
    assert office.db.get("employees", eid)["pay_rate"] == 3125


def test_audit_details_are_encrypted_and_chain_is_keyed(office):
    office.audit("change", "test", 1, {"pay": 100}, {"pay": 999_111})
    rows = _raw(office, "SELECT before, after, hash FROM audit")
    assert all(str(b or "enc2:").startswith("enc2:") and
               str(a or "enc2:").startswith("enc2:") for b, a, _h in rows)
    assert all(h.startswith("h2:") for _b, _a, h in rows)
    assert b"999111" not in open(office.db.path, "rb").read()
    assert security.verify_chain(office.db)["ok"]


def test_rewriting_the_chain_without_the_key_is_caught(office):
    for i in range(3):
        office.audit("change", "test", i, None, {"v": i})
    con = office.db.conn
    con.execute("DROP TRIGGER audit_no_update")
    # someone with the file but not the key re-hashes everything the old
    # (unkeyed) way after editing an entry
    prev = ""
    for e in office.db.rows("SELECT * FROM audit ORDER BY id"):
        h = security._entry_hash(prev, e, None)
        con.execute("UPDATE audit SET prev_hash = ?, hash = ? WHERE id = ?",
                    (prev, h, e["id"]))
        prev = h
    assert not security.verify_chain(office.db)["ok"]


def test_old_database_is_encrypted_and_rekeyed_once(tmp_path):
    """A company file from before 0.13.14 (plain values, unkeyed chain)."""
    import json
    from quantisheet_backoffice.office import Office
    from quantisheet_backoffice.crypto import _OwnerOnlyFile
    folder = tmp_path / "co"
    folder.mkdir()
    old = store.DB(str(folder / "backoffice.sqlite"))   # as 0.13.13 kept it
    eid = old.insert("employees", name="Example Old", employee_no="E-1",
                     address="9 Old Rd", pay_rate=2500)
    security.audit(old, "system", "change", "x", 1, None, {"a": 1})
    assert security.verify_chain(old)["ok"]
    old.close()
    o2 = Office(str(folder), crypto_backend=_OwnerOnlyFile())
    (addr, rate), = _raw(o2, "SELECT address, pay_rate FROM employees "
                         "WHERE id = ?", (eid,))
    assert addr.startswith("enc2:") and rate.startswith("enc2:")
    assert o2.db.get("employees", eid)["address"] == "9 Old Rd"
    assert o2.db.get("employees", eid)["pay_rate"] == 2500
    assert security.verify_chain(o2.db)["ok"]
    prot = [r for r in o2.db.rows("SELECT * FROM audit ORDER BY id")
            if r["action"] == "protect"]
    assert len(prot) == 1 and json.loads(prot[0]["after"])["old_chain_ok"]
    with pytest.raises(sqlite3.DatabaseError):           # trigger is back
        o2.db.conn.execute("UPDATE audit SET user = 'x'")
    n = o2.db.scalar("SELECT COUNT(*) FROM audit")
    o2.close()
    o3 = Office(str(folder), crypto_backend=_OwnerOnlyFile())  # not again
    assert o3.db.scalar("SELECT COUNT(*) FROM audit") == n
    o3.close()


def test_no_sql_filters_or_sums_on_encrypted_columns():
    """Encrypted columns can't be compared, sorted or added up in SQL:
    the code must never try (it adds payroll up in Python)."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cols = {c for cs in store.AUTO_ENCRYPT.values() for c in cs} - {
        "before", "after", "email", "rate", "base", "net"}
    pat = re.compile(r"(WHERE|AND|OR|ORDER BY|SUM\(|TOTAL\(|MAX\(|MIN\()"
                     r"[^\"']{0,40}\b(" + "|".join(sorted(cols)) + r")\b")
    bad = []
    for base, _d, files in os.walk(root):
        if "tests" in base:
            continue
        for f in files:
            if f.endswith(".py"):
                for i, ln in enumerate(open(os.path.join(base, f),
                                            encoding="utf-8"), 1):
                    if pat.search(ln) and "SELECT" in ln.upper() and \
                            ("employees" in ln or "payroll_lines" in ln or
                             "provider_registers" in ln):
                        bad.append(f"{f}:{i}")
    assert bad == []


@pytest.mark.skipif(os.name != "nt", reason="network paths are Windows-only")
def test_network_share_is_spotted():
    assert store.on_network_share(r"\\server\share\backoffice.sqlite")
