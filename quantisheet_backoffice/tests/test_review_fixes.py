"""Claude's review of M1/M2 (Oct 22, 2026): one test per fix."""
import csv
import os
import socket
import sqlite3
import stat
import sys
import tempfile
from decimal import Decimal

import pytest

from quantisheet_backoffice import (ap, billing, cents, crypto, exports,
                                    fileguard, handoff, ledger, migrate, ocr,
                                    output, security, settings, ten99)
from quantisheet_backoffice import backup as backupmod
from quantisheet_backoffice.office import Office

from .helpers import PW, ap_invoice, approve_ap


@pytest.fixture
def full(office):
    office.set_company(accounting_mode="full")
    return office


# ---- merge blocker 1: OCR renders scans in a temp folder, cleans up ----

def _scan_pdf(path):
    import fitz
    doc = fitz.open()
    pg = doc.new_page()
    pg.draw_rect(fitz.Rect(50, 50, 200, 120), color=(0, 0, 0), fill=(0, 0, 0))
    doc.save(path)
    doc.close()


class _SeenEngine:
    def __init__(self, fail=False):
        self.seen, self.fail = [], fail

    def read(self, image_path):
        self.seen.append(image_path)
        assert os.path.isfile(image_path)
        if self.fail:
            raise RuntimeError("tesseract crashed")
        return [("Invoice", 95), ("Total", 95), ("$12.50", 95)]


@pytest.mark.parametrize("fail", [False, True])
def test_ocr_scan_renders_to_temp_and_cleans_up(tmp_path, fail):
    folder = tmp_path / "user files"
    folder.mkdir()
    pdf = folder / "bill.pdf"
    _scan_pdf(str(pdf))
    mine = folder / "bill-page1.png"          # a user's file of that name
    mine.write_bytes(b"keep me")
    eng = _SeenEngine(fail)
    if fail:
        with pytest.raises(RuntimeError):
            ocr.extract(str(pdf), engine=eng)
    else:
        assert ocr.extract(str(pdf), engine=eng)["source"] == "ocr"
    (img,) = eng.seen
    assert os.path.dirname(img) != str(folder)
    assert not os.path.exists(img) and not os.path.exists(os.path.dirname(img))
    assert sorted(os.listdir(folder)) == ["bill-page1.png", "bill.pdf"]
    assert mine.read_bytes() == b"keep me"


# ---- should-fix: hook snapshot deleted from %TEMP% after import ----

def test_handoff_snapshot_deleted_only_from_hook_temp_folder(tmp_path):
    d = tempfile.mkdtemp(prefix="quantisheet-backoffice-")
    p = os.path.join(d, "snapshot.json")
    open(p, "w").write("{}")
    assert handoff.discard(p) is True
    assert not os.path.exists(p) and not os.path.exists(d)
    mine = tmp_path / "my snapshot.json"             # user-chosen file
    mine.write_text("{}")
    assert handoff.discard(str(mine)) is False and mine.exists()
    odd = tmp_path / "quantisheet-backoffice-x"      # right name, not in TEMP
    odd.mkdir()
    (odd / "snapshot.json").write_text("{}")
    assert handoff.discard(str(odd / "snapshot.json")) is False


def test_main_import_discards_handoff_even_when_import_fails():
    from quantisheet_backoffice import __main__ as m
    d = tempfile.mkdtemp(prefix="quantisheet-backoffice-")
    p = os.path.join(d, "snapshot.json")
    open(p, "w").write("{}")

    class Win:
        def import_snapshot(self, path):
            raise ValueError("bad snapshot")

    with pytest.raises(ValueError):
        m.import_handoff(Win(), p)
    assert not os.path.exists(p)


# ---- should-fix: safe file names inside the target folder ----

@pytest.mark.parametrize("raw,want", [
    ("INV-1001", "INV-1001"), ("../../evil", "evil"), ("a/b\\c:d", "a-b-c-d"),
    ("CON", "_CON"), ("lpt1.pdf", "_lpt1.pdf"), ("..", "file"),
    ("x<>|?*\"y", "x-y"), ("  trailing. ", "trailing"), ("a..b", "a.b")])
def test_safe_name(raw, want):
    assert fileguard.safe_name(raw) == want


def test_invoice_and_statement_files_stay_in_output_folder(office, job3,
                                                           tmp_path):
    billing.set_contract(office, job3, owner="../../Owner: CON")
    iid = billing.invoice_from_payapp(office, job3, 1,
                                      number_override="..\\..\\INV:1001")
    out = os.path.realpath(office.output_folder())
    p = output.invoice_pdf(office, iid)
    assert os.path.dirname(os.path.realpath(p)) == out
    assert os.path.basename(p) == "INV-1001.pdf"
    s = output.statement_pdf(office, "../../Owner: CON", "2026-10-22")
    assert os.path.dirname(os.path.realpath(s)) == out
    assert ".." not in os.path.basename(s) and ":" not in os.path.basename(s)
    with pytest.raises(fileguard.UnsafeNameError):
        fileguard.safe_path(str(tmp_path), "x", subdir="../up")


# ---- should-fix: CSV / Excel formula injection ----

@pytest.mark.parametrize("v,want", [
    ("=HYPERLINK(\"x\")", "'=HYPERLINK(\"x\")"), ("+1+1", "'+1+1"),
    ("@SUM(A1)", "'@SUM(A1)"), ("-2+3", "'-2+3"), ("\tx", "'\tx"),
    ("\rx", "'\rx"), ("-312.47", "-312.47"), ("+5", "+5"), ("Apex", "Apex"),
    (12, 12)])
def test_cell_escape(v, want):
    assert fileguard.safe_cell(v) == want


def test_exports_and_1099_escape_formulas(office, job, tmp_path):
    iid = ap_invoice(office, "=cmd|' /C calc'!A0", "+INV-1", "2026-10-02",
                     "312.47", job_id=job)
    approve_ap(office, iid)
    office.act_as("admin@bo.test")
    for fmt in ("csv", "xlsx"):
        r = exports.export(office, "ap", "2026-10-01", "2026-10-31", fmt,
                           folder=str(tmp_path / fmt))
        if fmt == "csv":
            cells = [c for row in csv.reader(open(r["path"], encoding="utf-8"))
                     for c in row]
        else:
            from openpyxl import load_workbook
            ws = load_workbook(r["path"]).active
            cells = [c.value for row in ws.iter_rows() for c in row]
            assert all(c.data_type != "f" for row in ws.iter_rows()
                       for c in row)
        txt = [c for c in cells if isinstance(c, str)]
        assert not any(c[:1] in "=+@" for c in txt if c)
        assert "'=cmd|' /C calc'!A0" in txt
        assert "'=cmd|' /C calc'!A0 +INV-1" in txt and "312.47" in txt
        office.db.conn.execute("UPDATE ap_invoices SET status = 'Approved'")
        office.db.conn.execute("DELETE FROM export_items")
    t = {"listed": [{"vendor": "@SUM(1+1)", "vendor_id": 1, "tin": "-1+2",
                     "box": "NEC", "total": 70_000, "w9": "on file"}]}
    import quantisheet_backoffice.ten99 as t99
    orig = t99.totals
    t99.totals = lambda o, y: t
    try:
        p = ten99.export_csv(office, 2026, str(tmp_path / "1099.csv"))
    finally:
        t99.totals = orig
    rows = list(csv.reader(open(p, encoding="utf-8")))
    assert rows[1][:2] == ["'@SUM(1+1)", "'-1+2"] and rows[1][3] == "700.00"


# ---- should-fix: 1099 export writes through fileguard ----

def test_1099_export_refuses_company_files_and_quantisheet_dir(office, tmp_path):
    with pytest.raises(fileguard.CompanyFileError):
        ten99.export_csv(office, 2026, str(tmp_path / "Company.QBW"))
    for name in (".quantisheet",):
        bad = os.path.join(os.path.expanduser("~"), name, "1099.csv")
        with pytest.raises(settings.UnsafePathError):
            ten99.export_csv(office, 2026, bad)


# ---- should-fix: encrypted backups, restorable on another PC ----

def test_backup_password_key_comes_from_crypto_backup_key(office, monkeypatch):
    from quantisheet_backoffice import crypto
    seen = []
    real = crypto.backup_key

    def spy(pw, salt, rounds=None):
        seen.append(rounds)
        return real(pw, salt, rounds)
    monkeypatch.setattr(crypto, "backup_key", spy)
    backupmod.set_password(office, "long backup phrase 42")
    assert seen == [crypto.BACKUP_ROUNDS]


def test_backup_is_encrypted_and_restores_on_another_pc(office, tmp_path):
    vid = ap.add_vendor(office, "Example Framing", tax_id="00-0000001",
                        bank="000099996789")
    with pytest.raises(backupmod.BackupError, match="backup password"):
        backupmod.make(office, str(tmp_path / "bk"), require_password=True)
    backupmod.set_password(office, "long backup phrase 42")
    bk = backupmod.make(office, str(tmp_path / "bk"))
    raw = open(bk, "rb").read()
    assert raw.startswith(b"QSBK1\n")
    assert b"SQLite format 3" not in raw and b"Example Framing" not in raw
    assert bk.endswith(".qsbk")
    # another PC: a different data folder with its own data key
    other = tmp_path / "other pc"
    o2 = Office(str(other))
    o2.close()
    with pytest.raises(backupmod.BackupError, match="password"):
        backupmod.restore(str(other), bk, password="wrong phrase 123")
    backupmod.restore(str(other), bk, password="long backup phrase 42")
    o3 = Office(str(other))
    o3.act_as("admin@bo.test")
    assert ap.vendor_tax_id(o3, vid, reveal=True) == "00-0000001"
    assert o3.crypto.decrypt(ap.vendor(o3, vid)["bank"]) == "000099996789"
    o3.close()
    # same PC: the local slot restores without the password
    backupmod.restore(office.folder, bk)
    assert "encrypted" in settings.onedrive_warning("D:/OneDrive/d")
    assert not hasattr(office.db, "backup")


# ---- should-fix: no DNS lookup for the .eml Message-ID ----

def test_eml_message_id_fixed_domain_no_dns(office, job3, monkeypatch):
    def no_dns(*a, **k):
        raise AssertionError("DNS lookup")
    monkeypatch.setattr(socket, "getfqdn", no_dns)
    monkeypatch.setattr(socket, "gethostname", no_dns)
    billing.set_contract(office, job3, contact_email="dana@example.test")
    iid = billing.invoice_from_payapp(office, job3, 1)
    billing.approve(office, iid)
    m = output.email_invoice(office, iid, opener=lambda p: None,
                             outlook=False)
    from email import message_from_bytes
    msg = message_from_bytes(open(m["path"], "rb").read())
    assert msg["Message-ID"].strip().endswith(
        "@quantisheet-backoffice.invalid>")


# ---- should-fix: PBKDF2 600,000 rounds, old hashes upgraded on login ----

def test_pbkdf2_rounds_and_upgrade_on_login(office, monkeypatch):
    import importlib
    import quantisheet_backoffice.security as sec_mod
    src = open(sec_mod.__file__, encoding="utf-8").read()
    assert "PBKDF2_ROUNDS = 600_000" in src
    old = sec_mod.hash_password(PW).replace(
        f"pbkdf2${sec_mod.PBKDF2_ROUNDS}$", "pbkdf2$1000$")
    salt, _ = old.split("$")[2:]
    import hashlib
    dk = hashlib.pbkdf2_hmac("sha256", PW.encode(), bytes.fromhex(salt), 1000)
    old = f"pbkdf2$1000${salt}${dk.hex()}"
    uid = office.user_id("viewer@bo.test")
    office.db.update("users", uid, pw_hash=old)
    assert security.needs_rehash(old)
    with pytest.raises(security.AuthError):
        security.login(office.db, "viewer@bo.test", "wrong pw")
    security.login(office.db, "viewer@bo.test", PW)
    new = office.db.get("users", uid)["pw_hash"]
    assert new.split("$")[1] == str(security.PBKDF2_ROUNDS)
    assert security.check_password(PW, new) and not security.needs_rehash(new)
    assert "600_000" in open(crypto.__file__, encoding="utf-8").read()


# ---- should-fix: '(-5)' is rejected; one rule for amount_in ----

def test_parse_amount_parenthesised_negative_rejected():
    assert cents.parse_amount("(5)") == -500
    assert cents.parse_amount("-5") == -500
    assert cents.parse_amount("(312.47)") == -31_247
    for bad in ("(-5)", "-(5)", "(-$5.00)", "--5"):
        with pytest.raises(cents.MoneyError):
            cents.parse_amount(bad)


def test_amount_in_takes_dollars_as_str_or_decimal_never_int():
    assert cents.amount_in("1,234.50") == 123_450
    assert cents.amount_in(Decimal("12.345")) == 1235
    assert cents.amount_in(cents.from_cents(31_247)) == 31_247
    for bad in (1250, True, 1.5, None):
        with pytest.raises(cents.MoneyError):
            cents.amount_in(bad)
    with pytest.raises(cents.MoneyError):
        cents.parse_amount(5)


# ---- should-fix: migration respects closed periods ----

def test_migration_refuses_closed_period(full, tmp_path):
    ledger.close_books(full, "2026-09-30")
    from .test_p2_migrate import iif_text
    p = tmp_path / "old.iif"
    p.write_text(iif_text(), encoding="utf-8")
    n0 = full.db.scalar("SELECT COUNT(*) FROM journal_entries")
    with pytest.raises(migrate.MigrateError, match="closed through 2026-09-30"):
        migrate.apply_iif(full, str(p), as_of="2026-09-30")
    with pytest.raises(migrate.MigrateError, match="closed through 2026-09-30"):
        migrate.opening_balances(full, "2026-09-30",
                                 [("1000", "100.00", "0"),
                                  ("3000", "0", "100.00")])
    assert full.db.scalar("SELECT COUNT(*) FROM journal_entries") == n0
    assert full.db.scalar("SELECT COUNT(*) FROM ar_invoices") == 0
    migrate.apply_iif(full, str(p), as_of="2026-10-01")      # open: fine
    assert full.db.scalar("SELECT COUNT(*) FROM ar_invoices") == 6


# ---- should-fix: negative AP credit memos post the right way round ----

def test_negative_lines_post_on_the_other_side(full):
    eid = ledger.post(full, "2026-10-05", [
        {"account": "5020", "debit": -25_000},
        {"account": "2000", "credit": -25_000}], "test", 1, "credit memo")
    got = sorted((ledger.account(full, ln["account_id"])["number"],
                  ln["debit"], ln["credit"])
                 for ln in ledger.entry(full, eid)["lines"])
    assert got == [("2000", 25_000, 0), ("5020", 0, 25_000)]


def test_ap_credit_memo_reduces_ap_and_cost(full, job):
    ap0, mat0 = ledger.balance(full, "2000"), ledger.balance(full, "5020")
    iid = ap_invoice(full, "Example Lumber", "CM-7", "2026-10-06", "-250.00",
                     job_id=job)
    approve_ap(full, iid)
    assert ledger.balance(full, "2000") == ap0 - 25_000
    assert ledger.balance(full, "5020") == mat0 - 25_000
    tb = ledger.trial_balance(full)
    assert tb["debits"] == tb["credits"]


# ---- should-fix: Tesseract never found in the current folder ----

def test_tesseract_lookup_absolute_path_dirs_only(tmp_path, monkeypatch):
    name = "tesseract.exe" if sys.platform == "win32" else "tesseract"
    here = tmp_path / "cwd"
    here.mkdir()
    fake = here / name
    fake.write_text("#!/bin/sh\n")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    monkeypatch.chdir(here)
    monkeypatch.setenv("PATH", os.pathsep.join(["", ".", "cwd", "rel/bin"]))
    monkeypatch.setattr(ocr, "KNOWN_DIRS", ())
    assert ocr.find_tesseract() is None
    good = tmp_path / "bin"
    good.mkdir()
    (good / name).write_text("#!/bin/sh\n")
    (good / name).chmod(0o755)
    monkeypatch.setenv("PATH", os.pathsep.join([".", str(good)]))
    assert ocr.find_tesseract() == str(good / name)
    assert ocr.TesseractOCR().exe == str(good / name)


# ---- should-fix: made-up company names only ----

OLD_NAMES = ("Northwind", "Apex Framing", "Harbor Lumber", "Ridgeline",
             "Maple Ridge", "Delta Concrete", "Coastal Electric",
             "Valley Supply", "Valley Pump", "Foxtrot Rentals", "Echo Drywall",
             "Metro Paint", "Pine Clinic", "First Bank", "Crypto Holdings",
             "Harbor Warehouse")


def test_fixture_company_names_are_example_names():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    hits = []
    for d, _, fs in os.walk(root):
        if "__pycache__" in d:
            continue
        for f in fs:
            if f == os.path.basename(__file__) or not f.endswith(
                    (".py", ".json", ".txt", ".md", ".js", ".html", ".csv")):
                continue
            t = open(os.path.join(d, f), encoding="utf-8").read()
            hits += [(f, n) for n in OLD_NAMES
                     if n.lower() in t.lower()]
    assert hits == []
