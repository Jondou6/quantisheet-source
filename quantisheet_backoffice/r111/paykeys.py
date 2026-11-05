"""Payroll data key: where it lives, and how it is rotated and backed up
(QS-025).

What was wrong:
  The key that encrypts payroll and HR fields (SSN, bank, pay rates,
  gross) is one Fernet data key. It was stored as datakey.bin beside the
  company database. On Windows that file is DPAPI-wrapped. On every other
  system it was the raw key with a 'plain:' prefix, mode 0600 only. A
  company folder on a share or in a sync folder therefore carried the key
  with the payroll file. Nothing in the program rotated that key.
  Replacing the file (install_key) left the previous key beside it and
  made existing ciphertext unreadable. Backup of the key existed only as
  a wrapped slot inside a full company backup, and only after a backup
  password was set. The self-service server wrote its own key in the
  clear as server.key in the server data directory. No key material is
  committed in the repository, and payroll CSV export does not write the
  key; the hole was the key file itself.

What this module does:
  The data key is sealed under a random seal in the signed-in OS user's
  profile (QS_BACKOFFICE_HOME / keys / ...), which is not the company
  data folder. The company folder keeps a stub that is not the key.
  rotate() makes a new data key and re-encrypts stored fields, the audit
  chain and HR / punch files. backup() / restore() write and read a
  password-wrapped key file. The key is not put in the audit log.
"""
from __future__ import annotations

import base64
import hashlib
import os
import sys

from cryptography.fernet import Fernet

from .. import clock, crypto, settings

STUB = b"qskey1:moved\n"
MAGIC = b"QSKEY1\n"


class PayKeyError(RuntimeError):
    pass


def slot_dir(company_folder: str) -> str:
    """Per-user directory for this company file, outside that folder when
    the company folder is not the whole profile."""
    digest = hashlib.sha256(os.path.realpath(company_folder).encode()
                            ).hexdigest()[:24]
    home = os.path.realpath(settings.home())
    company = os.path.realpath(company_folder)
    base = os.path.join(home, "keys")
    path = os.path.join(base, digest)
    if path == company or path.startswith(company + os.sep):
        path = os.path.join(home, "keys", digest)
    return path


def _seal_path(slot: str) -> str:
    return os.path.join(slot, "seal.bin")


def _key_path(slot: str) -> str:
    return os.path.join(slot, "key.bin")


def _write_file(path: str, data: bytes) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _read_seal(slot: str, backend) -> bytes:
    path = _seal_path(slot)
    if not os.path.isfile(path):
        seal = os.urandom(32)
        blob = backend.protect(seal) if sys.platform == "win32" else seal
        _write_file(path, blob)
        return seal
    raw = open(path, "rb").read()
    if sys.platform == "win32":
        return backend.unprotect(raw)
    return raw


def _fernet(seal: bytes) -> Fernet:
    return Fernet(base64.urlsafe_b64encode(seal[:32]))


def _write_sealed(slot: str, key: bytes, backend) -> None:
    seal = _read_seal(slot, backend)
    _write_file(_key_path(slot), b"sealed1:" + _fernet(seal).encrypt(key))


def _open_sealed(slot: str, backend) -> bytes:
    path = _key_path(slot)
    if not os.path.isfile(path):
        raise PayKeyError("The payroll key is not in this user's profile.")
    blob = open(path, "rb").read()
    if not blob.startswith(b"sealed1:"):
        raise PayKeyError("The payroll key file is not a sealed key.")
    seal = _read_seal(slot, backend)
    from cryptography.fernet import InvalidToken
    try:
        return _fernet(seal).decrypt(blob[len(b"sealed1:"):])
    except InvalidToken:
        raise PayKeyError("The payroll key does not open with this user's "
                          "seal.") from None


def _digest(company_folder: str) -> str:
    return hashlib.sha256(os.path.realpath(company_folder).encode()
                          ).hexdigest()[:24]


def _stub(company_folder: str, slot: str | None = None) -> None:
    """The company folder's datakey.bin becomes a note, not the key. It
    names the profile slot, so the same Windows user still finds the key
    when the folder's path changes (a new drive letter, OneDrive moved)."""
    path = os.path.join(company_folder, "datakey.bin")
    name = os.path.basename(slot or slot_dir(company_folder))
    _write_file(path, STUB + b"slot=" + name.encode() + b"\n")


def _stub_slot(company_folder: str):
    """The slot named by the company folder's stub, or None. Also tells
    whether there is a stub at all: (is_stub, slot path or None)."""
    path = os.path.join(company_folder, "datakey.bin")
    if not os.path.isfile(path):
        return False, None
    blob = open(path, "rb").read()
    if not blob.startswith(b"qskey1:"):
        return False, None
    for line in blob.decode("ascii", "replace").splitlines():
        if line.startswith("slot="):
            name = line[5:].strip()
            if name and all(c in "0123456789abcdef" for c in name):
                return True, os.path.join(settings.home(), "keys", name)
    return True, None


MISSING = ("The payroll key for this company isn't on this Windows login.\n\n"
           "It was moved into the profile of the Windows user who opened the "
           "company before (another login or another PC, or Windows was "
           "reset). Payroll and HR fields can't be opened without it, so a "
           "new key was NOT made.\n\nOpen Back Office as that user, or "
           "restore the key from a payroll key backup (.qskey).\n\nOn a "
           "shared company folder this is normal for each new Windows user "
           "or PC: restore the same .qskey once, with its password, and it "
           "opens from then on.")


def _legacy_key(path: str, backend):
    if not os.path.isfile(path):
        return None
    blob = open(path, "rb").read()
    if blob.startswith(STUB[:6]) or blob.startswith(b"qskey1:"):
        return None
    return backend.unprotect(blob)


def _retire_plaintext(company_folder: str, slot: str, backend) -> None:
    """Move leftover key files out of the company folder."""
    if not os.path.isdir(company_folder):
        return
    n = 1
    for name in sorted(os.listdir(company_folder)):
        if name != "datakey.bin" and not name.startswith("datakey.bin.replaced"):
            continue
        path = os.path.join(company_folder, name)
        if not os.path.isfile(path):
            continue
        raw = open(path, "rb").read()
        try:
            key = _legacy_key(path, backend)
            if key is not None:
                Fernet(key)
        except Exception:                             # noqa: BLE001
            continue        # won't open here: leave it where it is
        if key is None:
            continue
        while os.path.exists(os.path.join(slot, f"key.retired-{n}")):
            n += 1
        _write_sealed_named(slot, f"key.retired-{n}", key, backend)
        _write_file(os.path.join(slot, f"legacy-{name}"), raw)
        os.remove(path)     # moved: sealed + original bytes in the profile
        n += 1


def _write_sealed_named(slot, name, key, backend) -> None:
    seal = _read_seal(slot, backend)
    _write_file(os.path.join(slot, name), b"sealed1:" + _fernet(seal).encrypt(key))


def _find_slot(company_folder: str):
    slot = slot_dir(company_folder)
    if os.path.isfile(_key_path(slot)):
        return slot
    _is, named = _stub_slot(company_folder)
    if named and os.path.isfile(_key_path(named)):
        return named
    return None


def load_key(company_folder: str, backend) -> bytes:
    """The data key for this company. Migrates a legacy datakey.bin out
    of the company folder the first time it is opened.

    Never makes a new key when the company already had one (a stub says
    it was moved; a legacy file that won't open): that would leave every
    payroll field unreadable and mix two keys in one database. Raises
    PayKeyError(MISSING) instead."""
    found = _find_slot(company_folder)
    if found:
        key = _open_sealed(found, backend)
        _stub(company_folder, found)
        _retire_plaintext(company_folder, found, backend)
        return key
    slot = slot_dir(company_folder)
    is_stub, _named = _stub_slot(company_folder)
    if is_stub:
        raise PayKeyError(MISSING)
    legacy = os.path.join(company_folder, "datakey.bin")
    if os.path.isfile(legacy):
        raw = open(legacy, "rb").read()
        try:
            key = _legacy_key(legacy, backend)
            Fernet(key)
        except Exception:                             # noqa: BLE001
            raise PayKeyError(MISSING) from None
        os.makedirs(slot, exist_ok=True)
        # the original file, exactly as it was (still DPAPI-wrapped on
        # Windows), kept in the profile - not beside the database
        _write_file(os.path.join(slot, "legacy-datakey.bin"), raw)
    else:
        key = Fernet.generate_key()               # a brand-new company
    os.makedirs(slot, exist_ok=True)
    _write_sealed(slot, key, backend)
    if _open_sealed(slot, backend) != key:        # read it back first
        raise PayKeyError("The payroll key could not be saved in this "
                          "user's profile; nothing was moved.")
    _stub(company_folder, slot)
    _retire_plaintext(company_folder, slot, backend)
    return key


def old_keys(company_folder: str, backend) -> list:
    """Earlier keys of this company (rotated or replaced), newest first.
    Kept sealed in the profile so anything still under one of them - an
    old backup, a file rotate didn't reach, a rotate cut off by a crash -
    still opens."""
    slot = _find_slot(company_folder) or slot_dir(company_folder)
    if not os.path.isdir(slot):
        return []
    names = [n for n in os.listdir(slot) if n.startswith("key.retired-")]

    def num(n):
        try:
            return int(n.rsplit("-", 1)[1])
        except ValueError:
            return 0
    out = []
    for n in sorted(names, key=num, reverse=True):
        try:
            out.append(_open_sealed_path(os.path.join(slot, n), slot,
                                         backend))
        except Exception:                             # noqa: BLE001
            continue
    return out


def restore_file(company_folder: str, path: str, password: str,
                 backend=None) -> None:
    """Install a key backup without opening the company - for when the
    company won't open because its key is missing (MISSING)."""
    from cryptography.fernet import InvalidToken
    import json
    backend = backend or crypto.default_backend()
    data = open(path, "rb").read()
    if not data.startswith(MAGIC):
        raise PayKeyError("This is not a payroll key backup.")
    head, _, blob = data[len(MAGIC):].partition(b"\n")
    try:
        header = json.loads(head)
        rounds = int(header["rounds"])
        salt = bytes.fromhex(header["salt"])
    except (ValueError, KeyError, TypeError):
        raise PayKeyError("The key backup is damaged.") from None
    if not 1 <= rounds <= 5_000_000:
        raise PayKeyError("The key backup is damaged.")
    pk = crypto.backup_key(password, salt, rounds)
    try:
        key = Fernet(pk).decrypt(blob)
    except InvalidToken:
        raise PayKeyError("Wrong key-backup password.") from None
    write_key(company_folder, key, backend)


def write_key(company_folder: str, key: bytes, backend=None) -> None:
    """Install `key` in the per-user slot. A different key already there
    is kept sealed as key.retired-N, not next to the database."""
    backend = backend or crypto.default_backend()
    slot = _find_slot(company_folder) or slot_dir(company_folder)
    os.makedirs(slot, exist_ok=True)
    live = _key_path(slot)
    if os.path.isfile(live):
        current = _open_sealed(slot, backend)
        if current == key:
            _stub(company_folder, slot)
            return
        n = 1
        while os.path.exists(os.path.join(slot, f"key.retired-{n}")):
            n += 1
        os.replace(live, os.path.join(slot, f"key.retired-{n}"))
    _write_sealed(slot, key, backend)
    _stub(company_folder, slot)


def location(company_folder: str) -> str:
    return _key_path(_find_slot(company_folder) or slot_dir(company_folder))


def synced_warning(company_folder: str) -> str:
    return settings.onedrive_warning(slot_dir(company_folder))


def _enc1_cells(office, old):
    out = []
    names = [r[0] for r in office.db.conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'")]
    for name in names:
        if name.startswith("sqlite_"):
            continue
        cols = office.db.conn.execute(f"PRAGMA table_info({name})").fetchall()
        idcol = any(c[1] == "id" for c in cols)
        if not idcol:
            continue
        for col in cols:
            cname = col[1]
            try:
                rows = office.db.conn.execute(
                    f"SELECT id, {cname} FROM {name} WHERE "
                    f"typeof({cname}) = 'text' AND {cname} LIKE 'enc1:%'"
                ).fetchall()
            except Exception:                         # noqa: BLE001
                continue
            for rid, val in rows:
                out.append((name, cname, rid, old.decrypt(val)))
    return out


def _enc2_cells(office):
    from .. import store
    out = []
    for table, cols in store.AUTO_ENCRYPT.items():
        have = {r[1] for r in office.db.conn.execute(
            f"PRAGMA table_info({table})")}
        for col in cols:
            if col not in have:
                continue
            for row in office.db.rows(f"SELECT id, {col} FROM {table}"):
                if row[col] is None:
                    continue
                out.append((table, col, row["id"], row[col]))
    return out


def _files(office, old):
    """Encrypted blobs on disk (HR documents, punch photos)."""
    found = []
    for sql in (
            "SELECT file_path FROM hr_documents WHERE deleted = 0 AND "
            "file_path IS NOT NULL",
            "SELECT photo_path FROM punches WHERE deleted = 0 AND "
            "photo_path IS NOT NULL"):
        try:
            rows = office.db.conn.execute(sql).fetchall()
        except Exception:                             # noqa: BLE001
            continue
        for (path,) in rows:
            if path and os.path.isfile(path):
                found.append((path, old.decrypt_bytes(open(path, "rb").read())))
    return found


def rotate(office) -> dict:
    """New data key. Fields, the audit chain and encrypted files are
    rewritten - the database in one transaction, so a failure leaves it
    exactly as it was. Every earlier key stays sealed in the profile
    (old_keys), so nothing under it becomes unreadable. The key itself is
    not written to the log."""
    office.require("settings.edit", "payroll_key", "rotate")
    old = office.crypto
    old_key = old.data_key()
    enc2 = _enc2_cells(office)
    enc1 = _enc1_cells(office, old)
    files = _files(office, old)
    new_key = Fernet.generate_key()
    backend = old.backend
    write_key(office.folder, new_key, backend)       # old one -> retired
    temps = []
    try:
        fresh = crypto.FieldCrypto(office.folder, backend)
        if fresh.data_key() != new_key:
            raise PayKeyError("The new payroll key did not save.")
        # the new key reads both old and new values (FieldCrypto keeps
        # earlier keys), so switch before re-encrypting: rekey_chain reads
        # rows that are already under the new key
        office.crypto = fresh
        office.db.crypto = fresh
        with office.db.tx():
            office.db.conn.execute("DROP TRIGGER IF EXISTS audit_no_update")
            for table, col, rid, plain in enc2:
                token = fresh.encrypt_value(plain)
                office.db.conn.execute(
                    f"UPDATE {table} SET {col} = ? WHERE id = ?", (token, rid))
            for table, col, rid, plain in enc1:
                token = fresh.encrypt(plain if isinstance(plain, str)
                                      else str(plain))
                office.db.conn.execute(
                    f"UPDATE {table} SET {col} = ? WHERE id = ?", (token, rid))
            for path, data in files:
                tmp = path + ".rotating"
                with open(tmp, "wb") as fh:
                    fh.write(fresh._f.encrypt(data))
                temps.append((tmp, path))
            from .. import security
            security.rekey_chain(office.db, fresh.audit_key())
            office.db.conn.execute(
                "CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE "
                "ON audit BEGIN SELECT RAISE(ABORT, 'the audit log is "
                "append-only'); END")
            office.audit("rotate payroll key", "database", "", None,
                         {"fields": len(enc1) + len(enc2),
                          "files": len(files), "who": office.who})
    except Exception:
        for tmp, _path in temps:
            try:
                os.remove(tmp)
            except OSError:
                pass
        write_key(office.folder, old_key, backend)
        office.crypto = crypto.FieldCrypto(office.folder, backend)
        office.db.crypto = office.crypto
        raise
    for tmp, path in temps:      # after the commit; either key opens them
        os.replace(tmp, path)
    return {"fields": len(enc1) + len(enc2), "files": len(files)}


def retired_keys(office) -> list:
    """[{"name", "date"}] of earlier keys still kept sealed on this PC."""
    slot = os.path.dirname(location(office.folder))
    out = []
    try:
        names = sorted(n for n in os.listdir(slot)
                       if n.startswith("key.retired-"))
    except OSError:
        return []
    import datetime as _dt
    for n in names:
        try:
            t = os.path.getmtime(os.path.join(slot, n))
            out.append({"name": n, "date": _dt.datetime.fromtimestamp(t)
                        .isoformat(timespec="minutes")})
        except OSError:
            continue
    return out


def _still_under_old(office) -> int:
    """How many stored values or files the current key alone can't open
    (they'd need an old key)."""
    cur = Fernet(office.crypto.data_key())
    bad = 0
    names = [r[0] for r in office.db.conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'")]
    for name in names:
        if name.startswith("sqlite_"):
            continue
        for col in office.db.conn.execute(f"PRAGMA table_info({name})"):
            c = col[1]
            try:
                vals = office.db.conn.execute(
                    f"SELECT {c} FROM {name} WHERE typeof({c}) = 'text' AND "
                    f"({c} LIKE 'enc1:%' OR {c} LIKE 'enc2:%')").fetchall()
            except Exception:                             # noqa: BLE001
                continue
            for (v,) in vals:
                try:
                    cur.decrypt(v[5:].encode("ascii"))
                except Exception:                         # noqa: BLE001
                    bad += 1
    for sql in ("SELECT file_path FROM hr_documents WHERE deleted = 0 AND "
                "file_path IS NOT NULL",
                "SELECT photo_path FROM punches WHERE deleted = 0 AND "
                "photo_path IS NOT NULL"):
        try:
            rows = office.db.conn.execute(sql).fetchall()
        except Exception:                                 # noqa: BLE001
            continue
        for (path,) in rows:
            if path and os.path.isfile(path):
                try:
                    cur.decrypt(open(path, "rb").read())
                except Exception:                         # noqa: BLE001
                    bad += 1
    return bad


RETIRE_WARNING = (
    "Retire the old payroll keys?\n\n"
    "After a rotation the old keys are kept so older backups still open. "
    "If a key may have leaked, retire them: they're destroyed on this PC, "
    "and company backups made before the last rotation will no longer "
    "open their payroll and HR fields. Back up the current key first.")


def retire_old_keys(office) -> int:
    """Destroy the sealed earlier keys (Admin / settings rights; logged).
    Refused while anything stored still needs one. Returns how many."""
    office.require("settings.edit", "payroll_key", "retire")
    left = _still_under_old(office)
    if left:
        raise PayKeyError(f"{left} stored value(s) still need an old key - "
                          "rotate the key again first, then retire.")
    slot = os.path.dirname(location(office.folder))
    gone = 0
    for rec in retired_keys(office):
        p = os.path.join(slot, rec["name"])
        try:
            size = os.path.getsize(p)
            with open(p, "r+b") as fh:          # overwrite, then remove
                fh.write(os.urandom(size))
            os.remove(p)
            gone += 1
        except OSError:
            continue
    office.crypto = crypto.FieldCrypto(office.folder, office.crypto.backend)
    office.db.crypto = office.crypto
    office.audit("retire old payroll keys", "database", "", None,
                 {"keys": gone, "who": office.who})
    return gone


def backup(office, path, password: str) -> str:
    """Password-wrapped copy of the data key. The file does not hold the
    key in the clear."""
    office.require("settings.edit", "payroll_key", "backup")
    if len(password or "") < 10:
        raise PayKeyError("The key backup needs a password of at least "
                          "10 characters.")
    from .. import fileguard
    path = fileguard.write_target(path)
    salt = os.urandom(16)
    pk = crypto.backup_key(password, salt, crypto.BACKUP_ROUNDS)
    blob = Fernet(pk).encrypt(office.crypto.data_key())
    header = {"format": 1, "salt": salt.hex(),
              "rounds": crypto.BACKUP_ROUNDS,
              "created": clock.iso_now()}
    import json
    raw = MAGIC + json.dumps(header).encode() + b"\n" + blob
    if office.crypto.data_key() in raw:
        raise PayKeyError("Refusing to write a key file that contains the "
                          "raw key.")
    _write_file(path, raw)
    # read it back with the password before calling it a backup
    if _unwrap(open(path, "rb").read(), password) != office.crypto.data_key():
        raise PayKeyError("The key backup didn't read back; it was not "
                          "kept as your backup. Try another place.")
    _mark_backed_up(office, path)
    office.audit("backup payroll key", "database", "", None,
                 {"file": os.path.basename(path), "who": office.who})
    return path


def _unwrap(data: bytes, password: str) -> bytes:
    from cryptography.fernet import InvalidToken
    import json
    if not data.startswith(MAGIC):
        raise PayKeyError("This is not a payroll key backup.")
    head, _, blob = data[len(MAGIC):].partition(b"\n")
    try:
        header = json.loads(head)
        rounds = int(header["rounds"])
        salt = bytes.fromhex(header["salt"])
    except (ValueError, KeyError, TypeError):
        raise PayKeyError("The key backup is damaged.") from None
    if not 1 <= rounds <= 5_000_000:
        raise PayKeyError("The key backup is damaged.")
    pk = crypto.backup_key(password, salt, rounds)
    try:
        return Fernet(pk).decrypt(blob)
    except InvalidToken:
        raise PayKeyError("Wrong key-backup password.") from None


def _key_id(key: bytes) -> str:
    return hashlib.sha256(b"qskey-id:" + key).hexdigest()[:16]


def _marker(office) -> str:
    return os.path.join(os.path.dirname(location(office.folder)),
                        "backed_up.json")


def _mark_backed_up(office, path) -> None:
    import json
    _write_file(_marker(office), json.dumps(
        {"key": _key_id(office.crypto.data_key()),
         "file": os.path.basename(path), "at": clock.iso_now()}).encode())


def last_backup(office):
    """{"at", "file"} of the last verified key backup of the key in use,
    or None."""
    import json
    try:
        with open(_marker(office), "rb") as fh:
            rec = json.loads(fh.read())
    except (OSError, ValueError):
        return None
    if rec.get("key") != _key_id(office.crypto.data_key()):
        return None
    return {"at": rec.get("at") or "", "file": rec.get("file") or ""}


def needs_backup(office) -> bool:
    """True until the key in use has a verified .qskey backup - after the
    move into the profile, a new company, or a rotation (reviews 1 + 2,
    Nov 4: without one, a new PC, a second Windows user or a Windows reset
    locks the office out of payroll)."""
    import json
    try:
        with open(_marker(office), "rb") as fh:
            rec = json.loads(fh.read())
        return rec.get("key") != _key_id(office.crypto.data_key())
    except (OSError, ValueError):
        return True


NEEDS_BACKUP = (
    "Back up the payroll key now.\n\n"
    "The key that unlocks payroll and HR fields is kept in this Windows "
    "user's profile. A new PC, another Windows user or a Windows reset "
    "can't open payroll without a key backup (.qskey) and its password.\n\n"
    "Save the backup somewhere other than the company folder (a USB drive "
    "or the office safe), and keep the password with your other important "
    "passwords.")


def restore(office, path, password: str) -> None:
    """Install a key backup into this user's profile. The password is not
    stored."""
    office.require("settings.edit", "payroll_key", "restore")
    from .. import fileguard
    from cryptography.fernet import InvalidToken
    import json
    fileguard.refuse_company_file(path)
    data = open(path, "rb").read()
    if not data.startswith(MAGIC):
        raise PayKeyError("This is not a payroll key backup.")
    head, _, blob = data[len(MAGIC):].partition(b"\n")
    try:
        header = json.loads(head)
        rounds = int(header["rounds"])
        salt = bytes.fromhex(header["salt"])
    except (ValueError, KeyError, TypeError):
        raise PayKeyError("The key backup is damaged.") from None
    if not 1 <= rounds <= 5_000_000:
        raise PayKeyError("The key backup is damaged.")
    pk = crypto.backup_key(password, salt, rounds)
    try:
        key = Fernet(pk).decrypt(blob)
    except InvalidToken:
        raise PayKeyError("Wrong key-backup password.") from None
    write_key(office.folder, key, office.crypto.backend)
    office.crypto = crypto.FieldCrypto(office.folder, office.crypto.backend)
    office.db.crypto = office.crypto
    _mark_backed_up(office, path)        # that file is this key's backup
    office.audit("restore payroll key", "database", "", None,
                 {"file": os.path.basename(path), "who": office.who})


def server_key(data_dir: str) -> bytes:
    """Self-service server key, sealed in the user profile. A legacy
    plaintext server.key in `data_dir` is moved and replaced with a stub."""
    backend = crypto.default_backend()
    slot = slot_dir(os.path.join(data_dir, "server-key"))
    os.makedirs(slot, exist_ok=True)
    live = os.path.join(slot, "server.key")
    legacy = os.path.join(data_dir, "server.key")
    if os.path.isfile(live):
        key = _open_sealed_path(live, slot, backend)
    else:
        key = None
        if os.path.isfile(legacy):
            blob = open(legacy, "rb").read()
            if not blob.startswith(b"qskey1:"):
                key = blob.strip()
        if not key:
            key = Fernet.generate_key()
        _write_sealed_named(slot, "server.key", key, backend)
    _write_file(legacy, b"qskey1:server\n")
    return key


def _open_sealed_path(path, slot, backend) -> bytes:
    blob = open(path, "rb").read()
    if not blob.startswith(b"sealed1:"):
        raise PayKeyError("The server key file is not sealed.")
    seal = _read_seal(slot, backend)
    from cryptography.fernet import InvalidToken
    try:
        return _fernet(seal).decrypt(blob[len(b"sealed1:"):])
    except InvalidToken:
        raise PayKeyError("The server key does not open.") from None
