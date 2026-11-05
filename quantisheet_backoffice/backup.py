"""Encrypted backups (review fix; brief P1-04).

A backup file (backoffice-YYYYmmdd-HHMMSS.qsbk) is

    QSBK1\\n
    one line of JSON header\\n
    the database, encrypted with a fresh random key (Fernet)

The header holds that database key wrapped twice:
- "local": by this PC's data key (DPAPI-protected on Windows), so a restore
  on the same PC needs no password;
- "password": by a key made from the backup password (PBKDF2, 600,000
  rounds), together with the data key itself, so a restore on another PC
  with the password also brings back vendor tax IDs, bank details and the
  other encrypted fields.
Nothing in the file is readable without one of those keys. The backup
password is set once in Settings (Admin or Controller); its derived key is
kept in the database encrypted with the data key, so scheduled backups
don't ask for it.
"""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from datetime import datetime

from cryptography.fernet import Fernet, InvalidToken

from . import __version__, clock, crypto, fileguard, security, settings

MAGIC = b"QSBK1\n"
EXT = ".qsbk"
MIN_PASSWORD = 10
SQLITE_HEADER = b"SQLite format 3\x00"


class BackupError(RuntimeError):
    pass


def _pw_key(password: str, salt: bytes, rounds: int) -> bytes:
    return crypto.backup_key(password, salt, rounds)


def set_password(office, password: str) -> None:
    office.require("settings.edit", "backup", "password")
    if len(password or "") < MIN_PASSWORD:
        raise BackupError(f"The backup password needs at least "
                          f"{MIN_PASSWORD} characters.")
    salt = os.urandom(16)
    key = _pw_key(password, salt, crypto.BACKUP_ROUNDS)
    c = office.company()
    with office.db.tx():
        office.db.update("company", c["id"], backup_salt=
                         f"{crypto.BACKUP_ROUNDS}${salt.hex()}",
                         backup_key=office.crypto.encrypt(key.decode()))
        office.audit("backup password set", "company", c["id"])


def has_password(office) -> bool:
    return bool(office.company().get("backup_key"))


def _name(folder) -> str:
    stamp = clock.now().strftime("%Y%m%d-%H%M%S")
    dest = os.path.join(folder, f"backoffice-{stamp}{EXT}")
    n = 1
    while os.path.exists(dest):
        n += 1
        dest = os.path.join(folder, f"backoffice-{stamp}-{n}{EXT}")
    return dest


def make(office, folder: str | None = None, keep: int | None = None,
         require_password: bool = False) -> str:
    """Write an encrypted backup; keeps the last `keep` (default 30) plus
    the first of each month. Returns its path. Needs backup.run: a backup
    holds the whole company database (0.13.5 security fix)."""
    office.require("backup.run", "database", "backup")
    if require_password and not has_password(office):
        raise BackupError("Set a backup password in Settings first; without "
                          "it a backup can only be restored on this PC.")
    folder = settings.check_safe(folder or settings.backup_folder())
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".qsbo-dump-", dir=office.folder)
    os.close(fd)
    try:
        office.db.dump(tmp)
        with open(tmp, "rb") as fh:
            plain = fh.read()
    finally:
        os.remove(tmp)
    dbkey = Fernet.generate_key()
    datakey = office.crypto.data_key()
    header = {"format": 1, "created": clock.iso_now(), "app": __version__,
              "local": Fernet(datakey).encrypt(dbkey).decode()}
    c = office.company()
    if c.get("backup_key"):
        rounds, salt = c["backup_salt"].split("$")
        pk = office.crypto.decrypt(c["backup_key"]).encode()
        header["password"] = {"rounds": int(rounds), "salt": salt,
                              "dbkey": Fernet(pk).encrypt(dbkey).decode(),
                              "datakey": Fernet(pk).encrypt(datakey).decode()}
    dest = _name(folder)
    part = dest + ".part"
    with open(part, "wb") as fh:
        fh.write(MAGIC + json.dumps(header).encode() + b"\n" +
                 Fernet(dbkey).encrypt(plain))
    os.replace(part, dest)
    office.audit("backup", "database", "", None,
                 {"file": os.path.basename(dest),
                  "password_slot": "password" in header})
    _prune(folder, keep if keep is not None else
           int(settings.get("backup_keep", 30) or 30))
    return dest


def backups(folder: str | None = None) -> list[str]:
    folder = folder or settings.backup_folder()
    if not os.path.isdir(folder):
        return []
    return sorted(os.path.join(folder, f) for f in os.listdir(folder)
                  if f.startswith("backoffice-") and f.endswith(EXT))


def _prune(folder, keep):
    files = backups(folder)
    months = {}
    for f in files:
        months.setdefault(os.path.basename(f)[11:17], f)
    monthly = set(months.values())
    for f in files[:-keep] if keep > 0 else []:
        if f not in monthly:
            os.remove(f)


def backup_date(path: str) -> str:
    b = os.path.basename(path)[11:26]
    try:
        return datetime.strptime(b, "%Y%m%d-%H%M%S").isoformat(sep=" ")
    except ValueError:
        return ""


def _read(path):
    fileguard.refuse_company_file(path)
    settings.check_safe(path)
    with open(path, "rb") as fh:
        data = fh.read()
    if not data.startswith(MAGIC):
        raise BackupError("This is not a Back Office backup file.")
    head, _, body = data[len(MAGIC):].partition(b"\n")
    try:
        return json.loads(head), body
    except ValueError:
        raise BackupError("The backup file is damaged.") from None


MAX_ROUNDS = 5_000_000          # a header can't make a restore hang


def restore(folder: str, path: str, password: str | None = None,
            crypto_backend=None, office=None) -> None:
    """Replace the database in `folder` with the backup. Without a password
    only a backup made on this PC opens; with the backup password it opens
    anywhere and this folder's data key becomes the backup's. With
    `office` (the window passes it) the signed-in user must be allowed to
    change settings (threat model T-015); the current database is kept
    beside it as backoffice.sqlite.pre-restore-<time> first."""
    if office is not None:
        office.require("settings.edit", "backup", "restore")
    folder = settings.check_safe(folder)
    header, body = _read(path)
    datakey = None
    if password:
        slot = header.get("password")
        if not slot:
            raise BackupError("This backup was made before a backup password "
                              "was set; restore it on the PC that made it.")
        try:
            rounds = int(slot["rounds"])
        except (KeyError, TypeError, ValueError):
            raise BackupError("The backup file is damaged.") from None
        if not 1 <= rounds <= MAX_ROUNDS:
            raise BackupError("The backup file is damaged (key settings "
                              "out of range).")
        pk = _pw_key(password, bytes.fromhex(slot["salt"]), rounds)
        try:
            dbkey = Fernet(pk).decrypt(slot["dbkey"].encode())
            datakey = Fernet(pk).decrypt(slot["datakey"].encode())
        except InvalidToken:
            raise BackupError("Wrong backup password.") from None
    else:
        fc = crypto.FieldCrypto(folder, crypto_backend)
        try:
            dbkey = Fernet(fc.data_key()).decrypt(header["local"].encode())
        except InvalidToken:
            raise BackupError("This backup was made on another PC: restore "
                              "it with the backup password.") from None
    try:
        plain = Fernet(dbkey).decrypt(body)
    except InvalidToken:
        raise BackupError("The backup file is damaged.") from None
    if not plain.startswith(SQLITE_HEADER):
        raise BackupError("The backup file is damaged.")
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".qsbo-restore-", dir=folder)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(plain)
        live = os.path.join(folder, "backoffice.sqlite")
        if os.path.exists(live):
            import shutil
            import time
            shutil.copy2(live, live + time.strftime(
                ".pre-restore-%Y%m%d-%H%M%S"))
        src = sqlite3.connect(tmp)
        dst = sqlite3.connect(live)
        try:
            if src.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise BackupError("The backup file is damaged.")
            src.backup(dst)
        finally:
            src.close()
            dst.close()
    finally:
        os.remove(tmp)
    if datakey is not None:
        crypto.FieldCrypto.install_key(folder, datakey, crypto_backend)
    from .store import DB
    db = DB(os.path.join(folder, "backoffice.sqlite"))
    # the restored file's own chain: keyed (0.13.14+) or, for an older
    # backup, unkeyed - the next open then checks and re-keys it whole
    db.crypto = crypto.FieldCrypto(folder, crypto_backend)
    keyed = db.one("SELECT id FROM counters WHERE kind = 'protect_v2'")
    if not keyed:
        db.crypto = None
    try:
        security.audit(db, "system", "restore", "database", "", None,
                       {"file": os.path.basename(path),
                        "created": header.get("created"),
                        "with_password": bool(password)})
    finally:
        db.close()
