"""Back up and restore QuantiSheet's own data (Nov 4, review QS-006).

What is in a backup (one .zip):
  * the per-user data folder (settings, Tool Chest, assemblies, cost books,
    price database, packages, time log, signing key, kept job data...);
  * the Back Office data folder, when there is one (databases are copied
    with SQLite's own backup, so a database in use is copied whole).
Left out: autosave copies, pre-save file copies, map tiles, logs (large,
and made again).

The backup holds private things (the signing key, carrier keys, payroll
data), so it is saved where the person chooses and they are told to keep
it private. Nothing is sent anywhere.

A weekly copy is made on its own (at most one a week, the last four
kept) in Documents\\QuantiSheet Backups (a zip is safe in OneDrive). The
live data folders are another matter: a database inside a synced folder
can be damaged while it syncs, so data_location_warning() says so.

The folders themselves are not moved (the review's ProgramData idea would
let everyone on the PC read one person's payroll data).
"""
import datetime
import json
import logging
import os
import shutil
import sqlite3
import tempfile
import zipfile

log = logging.getLogger(__name__)

SKIP_DIRS = {"autosave", "backups", "aerial_cache", "logs", "cache",
             "__pycache__", "thumbs"}
SKIP_EXT = {".log", ".tmp"}
KEEP = 4
WEEK = 7 * 24 * 3600
S_LAST = "data_backup_last"
S_DIR = "data_backup_dir"
SYNCED = ("onedrive", "dropbox", "google drive", "icloud", "box sync")
# keys and sign-ins (reviews 1 + 2, Nov 4): only in a backup that has a
# password. The Back Office folder (payroll) likewise - it has its own
# encrypted backup (File > Back Up) and the payroll key backup (.qskey).
KEY_PATTERNS = ("*.pem", "*.p12", "*.pfx", "*.key", "*.dpapi", "*token*",
                "*secret*", "carrier_keys.json", "company_sender.json",
                "company_dropbox.json", "*.qskey")
MAGIC = b"QSBACKUP1\n"
CHUNK = 1 << 20
ROUNDS = 600_000


class BackupError(RuntimeError):
    pass


def is_key_file(rel):
    import fnmatch
    base = os.path.basename(rel).lower()
    return any(fnmatch.fnmatch(base, p) for p in KEY_PATTERNS)


def backoffice_home():
    """The Back Office data folder (same rule as the Back Office's own
    settings; the host never imports that package)."""
    env = os.environ.get("QS_BACKOFFICE_HOME")
    if env:
        return env
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        return os.path.join(os.environ["LOCALAPPDATA"],
                            "QuantiSheetBackOffice")
    return os.path.join(os.path.expanduser("~"), ".quantisheet_backoffice")


def sources():
    from . import settings
    out = [("quantisheet", settings.DIR)]
    bo = backoffice_home()
    if os.path.isdir(bo):
        out.append(("backoffice", bo))
    return out


def is_synced(path):
    low = os.path.abspath(path).lower()
    return any(k in low for k in SYNCED)


def _copy_db(src, dst):
    """A consistent copy of a SQLite database (WAL included)."""
    a = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    try:
        b = sqlite3.connect(dst)
        try:
            a.backup(b)
        finally:
            b.close()
    finally:
        a.close()


def _is_db(path):
    try:
        with open(path, "rb") as f:
            return f.read(16) == b"SQLite format 3\x00"
    except OSError:
        return False


def make(out_path, srcs=None, password=None, include_keys=None,
         verify_after=True):
    """Write the backup. Without a password: a plain zip WITHOUT keys,
    sign-ins or the Back Office folder (they're listed as left out). With
    one: everything, encrypted (AES-GCM, key from the password). Then it
    is opened again and checked (verify). Returns {"files": n, "bytes":
    size, "left_out": [...], "encrypted": bool, "verified": {...}}."""
    from . import __version__
    srcs = srcs if srcs is not None else sources()
    if include_keys is None:
        include_keys = bool(password)
    if include_keys and not password:
        raise BackupError("Keys and the Back Office data go only into a "
                          "backup with a password.")
    if password is not None and len(password) < 10:
        raise BackupError("Use a backup password of at least 10 characters.")
    left_out = []
    if not include_keys:
        keep = []
        for name, root in srcs:
            if name == "backoffice":
                left_out.append("Back Office data (use its own File > Back "
                                "Up, or a backup with a password)")
            else:
                keep.append((name, root))
        srcs = keep
    n = 0
    tmpdir = tempfile.mkdtemp(prefix="qs-backup-")
    part = out_path + ".part"
    zpath = os.path.join(tmpdir, "backup.zip") if password else part
    try:
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("quantisheet_backup.json", json.dumps({
                "app": __version__,
                "made": datetime.datetime.now().isoformat(timespec="seconds"),
                "parts": [name for name, _ in srcs],
                "keys_included": bool(include_keys)}))
            for name, root in srcs:
                for dirpath, dirs, files in os.walk(root):
                    dirs[:] = [d for d in dirs if d.lower() not in SKIP_DIRS]
                    for fn in files:
                        if os.path.splitext(fn)[1].lower() in SKIP_EXT or \
                                fn.endswith(("-wal", "-shm", "-journal")):
                            continue
                        full = os.path.join(dirpath, fn)
                        rel = os.path.relpath(full, root).replace("\\", "/")
                        arc = f"{name}/{rel}"
                        if not include_keys and is_key_file(rel):
                            left_out.append(f"{name}/{rel}")
                            continue
                        try:
                            if _is_db(full):
                                tmp = os.path.join(tmpdir, f"db{n}")
                                _copy_db(full, tmp)
                                z.write(tmp, arc)
                            else:
                                z.write(full, arc)
                            n += 1
                        except (OSError, sqlite3.Error):
                            log.warning("backup: skipped %s", full,
                                        exc_info=True)
            if left_out:
                z.writestr("LEFT OUT.txt", "Not in this backup (no backup "
                           "password was set):\n" + "\n".join(left_out))
        if password:
            _encrypt_file(zpath, part, password)
        os.replace(part, out_path)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
        if os.path.exists(part):
            try:
                os.remove(part)
            except OSError:
                pass
    out = {"files": n, "bytes": os.path.getsize(out_path),
           "left_out": left_out, "encrypted": bool(password)}
    if verify_after:
        out["verified"] = verify(out_path, password, expect=n)
    return out


# ---- the password-protected form -------------------------------------------

def _key(password, salt, rounds):
    import hashlib
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt,
                               rounds, 32)


def _encrypt_file(src, dst, password):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    salt = os.urandom(16)
    aes = AESGCM(_key(password, salt, ROUNDS))
    head = json.dumps({"format": 1, "salt": salt.hex(), "rounds": ROUNDS,
                       "chunk": CHUNK}).encode()
    with open(src, "rb") as fi, open(dst, "wb") as fo:
        fo.write(MAGIC + head + b"\n")
        i = 0
        while True:
            block = fi.read(CHUNK)
            last = len(block) < CHUNK
            nonce = os.urandom(12)
            ad = i.to_bytes(8, "big") + (b"L" if last else b"M")
            ct = aes.encrypt(nonce, block, ad)
            fo.write(len(ct).to_bytes(4, "big") + (b"L" if last else b"M") +
                     nonce + ct)
            i += 1
            if last:
                break


def is_encrypted(path):
    try:
        with open(path, "rb") as f:
            return f.read(len(MAGIC)) == MAGIC
    except OSError:
        return False


def _decrypt_file(src, dst, password):
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    with open(src, "rb") as fi:
        if fi.read(len(MAGIC)) != MAGIC:
            raise BackupError("This isn't a password-protected backup.")
        head = json.loads(fi.readline())
        rounds = int(head["rounds"])
        if not 1 <= rounds <= 5_000_000:
            raise BackupError("The backup file is damaged.")
        aes = AESGCM(_key(password or "", bytes.fromhex(head["salt"]),
                          rounds))
        i = 0
        with open(dst, "wb") as fo:
            while True:
                n = fi.read(4)
                if len(n) < 4:
                    raise BackupError("The backup file is cut short.")
                kind = fi.read(1)
                nonce = fi.read(12)
                ct = fi.read(int.from_bytes(n, "big"))
                try:
                    fo.write(aes.decrypt(nonce, ct,
                                         i.to_bytes(8, "big") + kind))
                except InvalidTag:
                    raise BackupError("Wrong backup password, or the file "
                                      "is damaged.") from None
                i += 1
                if kind == b"L":
                    break


def _opened(path, password, tmpdir):
    """A path to the plain zip of `path` (decrypted into tmpdir)."""
    if is_encrypted(path):
        if not password:
            raise BackupError("This backup has a password.")
        z = os.path.join(tmpdir, "open.zip")
        _decrypt_file(path, z, password)
        return z
    return path


def verify(path, password=None, expect=None):
    """Open the backup again and check it (review, Nov 4): the zip reads
    whole, the file count is right, every database passes SQLite's
    integrity_check. Raises BackupError loudly on any failure."""
    tmpdir = tempfile.mkdtemp(prefix="qs-verify-")
    try:
        zp = _opened(path, password, tmpdir)
        try:
            with zipfile.ZipFile(zp) as z:
                bad = z.testzip()
                if bad:
                    raise BackupError(f"The backup is damaged ({bad}).")
                names = [i for i in z.infolist() if not i.is_dir() and
                         i.filename not in ("quantisheet_backup.json",
                                            "LEFT OUT.txt")]
                if expect is not None and len(names) != expect:
                    raise BackupError(f"The backup holds {len(names)} "
                                      f"files, not {expect}.")
                dbs = 0
                for info in names:
                    with z.open(info) as f:
                        if f.read(16) != b"SQLite format 3\x00":
                            continue
                    out = os.path.join(tmpdir, f"v{dbs}.db")
                    with z.open(info) as src, open(out, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    c = sqlite3.connect(out)
                    try:
                        r = c.execute("PRAGMA integrity_check").fetchone()
                    finally:
                        c.close()
                    if not r or r[0] != "ok":
                        raise BackupError(f"A database in the backup "
                                          f"failed its check: "
                                          f"{info.filename}")
                    dbs += 1
        except zipfile.BadZipFile:
            raise BackupError("The backup isn't a readable zip.") from None
        return {"files": len(names), "databases_checked": dbs}
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def contents(zip_path, password=None):
    tmpdir = tempfile.mkdtemp(prefix="qs-backup-")
    try:
        zp = _opened(zip_path, password, tmpdir)
        with zipfile.ZipFile(zp) as z:
            meta = json.loads(z.read("quantisheet_backup.json").decode(
                "utf-8"))
            meta["count"] = len([i for i in z.namelist()
                                 if i not in ("quantisheet_backup.json",
                                              "LEFT OUT.txt")])
        meta["encrypted"] = is_encrypted(zip_path)
        return meta
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def restore(zip_path, targets=None, safety_dir=None, password=None):
    tmpdir = tempfile.mkdtemp(prefix="qs-restore-")
    try:
        return _restore(_opened(zip_path, password, tmpdir), targets,
                        safety_dir or os.path.dirname(
                            os.path.abspath(zip_path)), password)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _restore(zip_path, targets=None, safety_dir=None, password=None):
    """Put a backup back. The data there now is backed up first
    (safety_dir, or next to the backup). Returns the safety copy's path."""
    targets = targets or dict(sources())
    targets.setdefault("backoffice", backoffice_home())
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H%M%S")
    safety = os.path.join(safety_dir or os.path.dirname(
        os.path.abspath(zip_path)), f"QuantiSheet data before restore "
        f"{stamp}.zip")
    # the safety copy keeps everything that is there now: with the
    # restore's password it can hold the keys too
    if password:
        safety = safety[:-4] + ".qsbackup"
    make(safety, [(k, v) for k, v in targets.items() if os.path.isdir(v)],
         password=password, include_keys=bool(password))
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            if info.filename in ("quantisheet_backup.json",
                                 "LEFT OUT.txt") or info.is_dir():
                continue
            part, _, rel = info.filename.partition("/")
            root = targets.get(part)
            if not root or not rel:
                continue
            dest = os.path.normpath(os.path.join(root, rel))
            if not dest.startswith(os.path.normpath(root) + os.sep):
                continue                        # no paths out of the folder
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with z.open(info) as src, open(dest + ".restoring", "wb") as f:
                shutil.copyfileobj(src, f)
            os.replace(dest + ".restoring", dest)
    return safety


def default_dir():
    from . import settings
    chosen = settings.get(S_DIR)
    if chosen:
        return chosen
    docs = os.path.join(os.path.expanduser("~"), "Documents")
    return os.path.join(docs, "QuantiSheet Backups")


def weekly(now=None, folder=None):
    """The automatic weekly copy. Returns its path, or None (not due,
    or the folder is synced and wasn't chosen on purpose)."""
    from . import settings
    import time
    now = now or time.time()
    if now - float(settings.get(S_LAST) or 0) < WEEK:
        return None
    folder = folder or default_dir()
    os.makedirs(folder, exist_ok=True)
    name = datetime.datetime.fromtimestamp(now).strftime(
        "QuantiSheet data %Y-%m-%d.zip")
    out = os.path.join(folder, name)
    make(out)
    settings.set(S_LAST, now)
    old = sorted(f for f in os.listdir(folder)
                 if f.startswith("QuantiSheet data ") and f.endswith(".zip")
                 and "before restore" not in f)
    for f in old[:-KEEP]:
        try:
            os.remove(os.path.join(folder, f))
        except OSError:
            pass
    return out


def data_location_warning():
    """A plain warning when a live data folder (with its databases) is
    inside a synced folder, else ''."""
    bad = [p for _n, p in sources() if is_synced(p)]
    if not bad:
        return ""
    return ("QuantiSheet's data folder is inside a synced folder (" +
            "; ".join(bad) + "). Databases there can be damaged while "
            "they sync. Ask IT to keep that folder out of syncing, or set "
            "QS_BACKOFFICE_HOME / move it to a local folder, and use Tools "
            "> Back Up My QuantiSheet Data for copies.")
