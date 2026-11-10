"""Keeping a job's data safe (Nov 4, review QS-003 / QS-004 / QS-005 /
QS-031).

* A version stamp (quantisheet_meta.json) goes in with the job data on
  every save. A file stamped by a NEWER QuantiSheet opens to look at, but
  saving over it is refused (an older program can't know what it would
  lose). One migration per schema version runs on open (MIGRATIONS).
* A copy of the job data is kept on this computer at every save (the data
  folder, jobdata_backups). Email gateways, "print to PDF" and flattening
  strip a PDF's attachments; when a file comes back without its data, the
  copy is offered back - nothing is put in it without asking.
* Two people on one shared file: a small lock file beside the PDF says
  who has it open (".name.pdf.qslock", hidden, removed on close), and a
  save checks the file wasn't changed by someone else since it was opened
  (Overwrite / Save a Copy / Cancel).
"""
import base64
import datetime
import getpass
import hashlib
import json
import logging
import os
import socket

log = logging.getLogger(__name__)

SCHEMA = 1
META = "quantisheet_meta.json"
BACKUP_DIR = "jobdata_backups"
LOCK_HOURS = 12
MIGRATIONS = {}           # {from schema: fn(doc)} -> moves the data to n+1


# ---- version stamp ------------------------------------------------------------------

def read_meta(doc):
    try:
        if META in doc.embfile_names():
            d = json.loads(doc.embfile_get(META).decode("utf-8"))
            return d if isinstance(d, dict) else {}
    except Exception:                                     # noqa: BLE001
        log.debug("job meta unreadable", exc_info=True)
    return {}


def stamp(doc):
    """Write the version stamp, when the PDF carries job data."""
    from . import __version__, embfiles, jobdata
    if not [n for n in jobdata.names(doc) if n != META]:
        return False
    meta = {"schema": SCHEMA, "app": __version__,
            "saved": datetime.datetime.now().isoformat(timespec="seconds")}
    if read_meta(doc).get("schema") == SCHEMA and \
            read_meta(doc).get("app") == __version__:
        return False                         # nothing new: don't touch it
    embfiles.put(doc, META, json.dumps(meta).encode("utf-8"),
                 "QuantiSheet job data")
    return True


def check_open(doc):
    """{"newer": bool, "schema": n, "app": "x.y.z", "migrated": [n...]}.
    Runs the migrations for an older stamp."""
    m = read_meta(doc)
    try:
        sch = int(m.get("schema") or 0)
    except (TypeError, ValueError):
        sch = 0
    out = {"newer": sch > SCHEMA, "schema": sch, "app": m.get("app", ""),
           "migrated": []}
    if 0 < sch < SCHEMA:
        for n in range(sch, SCHEMA):
            fn = MIGRATIONS.get(n)
            if fn is not None:
                fn(doc)
                out["migrated"].append(n)
    return out


def newer_message(info):
    return (f"This file's QuantiSheet data was saved by a newer version "
            f"({info.get('app') or 'unknown'}). You can look at it, but "
            "saving is turned off so nothing in it is lost. Update "
            "QuantiSheet (Help > Check for Updates) to work on it.")


# ---- the copy kept on this computer -----------------------------------------------

def _dir():
    from . import settings
    return os.path.join(settings.DIR, BACKUP_DIR)


def _key(path):
    p = os.path.normcase(os.path.abspath(path))
    return hashlib.sha1(p.encode("utf-8")).hexdigest()[:20]


def backup_path(path):
    return os.path.join(_dir(), _key(path) + ".json")


FP_PAGES = 30


def drawing_fingerprint(doc):
    """What identifies the drawings themselves, not the file: page count,
    page sizes and a hash of the first pages' text (or, for a scanned
    sheet with no text, of a tiny picture of it). Survives an email
    gateway stripping attachments and a new file name (reviews 1 + 2,
    Nov 4: name + page count alone matched the wrong job)."""
    n = doc.page_count
    sizes = []
    for i in range(min(n, FP_PAGES)):
        r = doc[i].rect
        sizes.append([round(r.width), round(r.height)])
    h = hashlib.sha1()
    text = ""
    for i in range(min(n, 2)):
        try:
            text += " ".join(doc[i].get_text().split())
        except Exception:                                 # noqa: BLE001
            pass
    if text.strip():
        h.update(b"t:" + text.encode("utf-8", "ignore"))
    elif n:
        try:
            pix = doc[0].get_pixmap(dpi=10, annots=False)
            h.update(b"p:" + bytes(pix.samples))
        except Exception:                                 # noqa: BLE001
            pass
    return {"pages": n, "sizes": sizes, "content": h.hexdigest()[:24]}


def keep_copy(doc, path):
    """Save a copy of the job data for `path`. Returns its file or None."""
    from . import jobdata, safeio
    snap = jobdata.snapshot(doc)
    if not [n for n in snap if n != META]:
        return None
    rec = {"file": os.path.abspath(path), "name": os.path.basename(path),
           "pages": doc.page_count, "fp": drawing_fingerprint(doc),
           "saved": datetime.datetime.now().isoformat(timespec="seconds"),
           "data": {n: base64.b64encode(b).decode("ascii")
                    for n, b in snap.items()}}
    os.makedirs(_dir(), exist_ok=True)
    out = backup_path(path)
    safeio.atomic_write(out, json.dumps(rec))
    return out


MATCH_SAME = "this file"
MATCH_DRAWINGS = "the same drawings (pages and sheet text match)"


def _match(rec, path, fp):
    """Why `rec` belongs to the opened file, or None."""
    rfp = rec.get("fp") or {}
    if rec.get("pages") != fp["pages"]:
        return None
    sizes = rfp.get("sizes")
    if sizes is not None and sizes != fp["sizes"]:
        return None
    if rfp.get("content") and rfp["content"] == fp["content"]:
        return MATCH_SAME if _same(rec, path) else MATCH_DRAWINGS
    if not rfp:                       # a copy kept before fingerprints
        return MATCH_SAME if _same(rec, path) else None
    # a different drawing with the same name and size (another job's
    # A-101.pdf) is never offered - a wrong offer is worse than none
    return None


def _same(rec, path):
    try:
        return os.path.normcase(os.path.abspath(rec.get("file") or "")) == \
            os.path.normcase(os.path.abspath(path))
    except Exception:                                     # noqa: BLE001
        return False


def find_copy(path, doc=None):
    """The copy kept for this file, with rec["match"] saying why: the same
    file, or the same drawings under any name (page sizes and sheet text
    match). Never by name and page count alone. None when there is
    none."""
    if doc is None:
        try:
            with open(backup_path(path), encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return None
    fp = drawing_fingerprint(doc)
    rank = {MATCH_SAME: 0, MATCH_DRAWINGS: 1}
    found = []
    try:
        names = [fn for fn in os.listdir(_dir()) if fn.endswith(".json")]
    except OSError:
        return None
    for fn in names:
        try:
            with open(os.path.join(_dir(), fn), encoding="utf-8") as f:
                rec = json.load(f)
        except (OSError, ValueError):
            continue
        why = _match(rec, path, fp)
        if why is None:
            continue
        found.append(dict(rec, match=why))
    if not found:
        return None
    # the strongest match; the newest save among equals
    found.sort(key=lambda r: str(r.get("saved") or ""), reverse=True)
    found.sort(key=lambda r: rank[r["match"]])
    return found[0]


def put_back(doc, rec):
    """Put a kept copy's job data into the document. Returns the names."""
    from . import jobdata
    data = {n: base64.b64decode(b) for n, b in (rec.get("data") or {}).items()}
    jobdata.restore(doc, data, overwrite=False)
    return sorted(data)


def lost_data(doc, path):
    """A kept copy when the opened file has no job data but this computer
    has a copy of it (the file lost it on the way); else None."""
    from . import jobdata
    if [n for n in jobdata.names(doc) if n != META]:
        return None
    return find_copy(path, doc)


# ---- two people, one file ----------------------------------------------------------

_SHARED = ("onedrive - ", "sharepoint", "dropbox", "\\box\\",
           "google drive", "teams")


def is_shared(path):
    """A file other people can open too: a network share or mapped drive,
    or a company / shared sync folder. Only those get a lock file."""
    p = os.path.abspath(path)
    low = p.lower()
    if low.startswith("\\\\"):
        return True
    if any(k in low for k in _SHARED):
        return True
    if os.name == "nt":
        try:
            import ctypes
            root = os.path.splitdrive(p)[0] + "\\"
            return ctypes.windll.kernel32.GetDriveTypeW(root) == 4  # remote
        except Exception:                                 # noqa: BLE001
            return False
    return False


def lock_path(path):
    """The lock file beside the PDF. Not "~$" (Office's owner-file prefix,
    which cleanup tools delete - review 1, Nov 4)."""
    d, n = os.path.split(os.path.abspath(path))
    return os.path.join(d, f".{n}.qslock")


def _old_lock_path(path):
    d, n = os.path.split(os.path.abspath(path))
    return os.path.join(d, f"~${n}.qslock")


def unc(path):
    """The same file as a \\\\server\\share path when it's on a mapped
    drive (S:\\Jobs\\x.pdf -> \\\\srv\\jobs\\Jobs\\x.pdf), else the absolute
    path - so two spellings of one file are seen as one."""
    p = os.path.abspath(path)
    if os.name != "nt" or p.startswith("\\\\"):
        return p
    try:
        import ctypes
        from ctypes import wintypes
        drive = os.path.splitdrive(p)[0]
        buf = ctypes.create_unicode_buffer(1024)
        n = wintypes.DWORD(len(buf))
        if ctypes.windll.mpr.WNetGetConnectionW(drive, buf,
                                                ctypes.byref(n)) == 0:
            return buf.value.rstrip("\\") + p[len(drive):]
    except Exception:                                     # noqa: BLE001
        pass
    return p


def _alive(pid):
    """Is process `pid` running on this machine?"""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes
            h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
            if not h:
                return False
            code = ctypes.c_ulong()
            ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
            ctypes.windll.kernel32.CloseHandle(h)
            return code.value == 259                      # STILL_ACTIVE
        except Exception:                                 # noqa: BLE001
            return True
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except OSError:
        return True


def _me():
    try:
        user = getpass.getuser()
    except Exception:                                     # noqa: BLE001
        user = os.environ.get("USERNAME", "someone")
    now = datetime.datetime.now().isoformat(timespec="seconds")
    return {"user": user, "machine": socket.gethostname(),
            "pid": os.getpid(), "since": now, "beat": now}


def _read_lock(path):
    for lp in (lock_path(path), _old_lock_path(path)):
        try:
            with open(lp, encoding="utf-8") as f:
                rec = json.load(f)
            if isinstance(rec, dict):
                return rec
        except (OSError, ValueError):
            continue
    return None


def who_has(path, now=None):
    """Someone else's live lock on this file: {user, machine, since,
    "you": True when it's you in another window} or None. Same machine:
    live only while that QuantiSheet is running. Other machine: until
    LOCK_HOURS after its last save / heartbeat."""
    rec = _read_lock(path)
    if rec is None:
        return None
    me = _me()
    if rec.get("machine") == me["machine"]:
        if rec.get("pid") == me["pid"]:
            return None                              # this window
        if not _alive(rec.get("pid")):
            return None                              # it closed or crashed
        if rec.get("user") == me["user"]:
            return dict(rec, you=True)               # you, another window
        return rec
    try:
        beat = datetime.datetime.fromisoformat(rec.get("beat") or
                                               rec.get("since", ""))
    except ValueError:
        return None
    now = now or datetime.datetime.now()
    if (now - beat).total_seconds() > LOCK_HOURS * 3600:
        return None                                  # stale
    return rec


def take_lock(path):
    """Write our lock beside the file, created only when nobody else
    holds it (no check-then-write race). True when written."""
    lp = lock_path(path)
    for _ in range(2):
        try:
            fd = os.open(lp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        except FileExistsError:
            if who_has(path) is not None:
                return False
            try:                                     # stale or ours
                os.remove(lp)
            except OSError:
                return False
            continue
        except OSError:
            return False
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(dict(_me(), unc=unc(path)), f)
        if os.name == "nt":
            try:
                import ctypes
                ctypes.windll.kernel32.SetFileAttributesW(lp, 0x2)  # hidden
            except Exception:                             # noqa: BLE001
                pass
        return True
    return False


def touch_lock(path):
    """Refresh our lock's heartbeat (each save), so a long session's lock
    doesn't go stale while it's in use."""
    lp = lock_path(path)
    rec = _read_lock(path)
    me = _me()
    if not rec or rec.get("pid") != me["pid"] or \
            rec.get("machine") != me["machine"]:
        return False
    rec["beat"] = me["beat"]
    try:            # "r+", not "w": Windows refuses "w" on a hidden file
        with open(lp, "r+", encoding="utf-8") as f:
            f.seek(0)
            json.dump(rec, f)
            f.truncate()
        return True
    except OSError:
        return False


def drop_lock(path):
    """Remove our own lock (never someone else's)."""
    me = _me()
    for lp in (lock_path(path), _old_lock_path(path)):
        try:
            with open(lp, encoding="utf-8") as f:
                rec = json.load(f)
            if rec.get("machine") == me["machine"] and \
                    rec.get("pid", me["pid"]) == me["pid"]:
                os.remove(lp)
                return True
        except (OSError, ValueError):
            pass
    return False


SYNCED_WARNING = ("This file is in a synced folder (OneDrive, SharePoint, "
                  "Dropbox...). Locks there aren't reliable and conflict "
                  "copies are likely - use File > Copies & Cloud > Work on a Local "
                  "Copy, then Copy Back to the Original when you are done.")


_SYNCED = ("onedrive", "sharepoint", "dropbox", "\\box\\", "google drive",
           "icloud")


def is_synced_folder(path):
    low = os.path.abspath(path).lower()
    return any(k in low for k in _SYNCED)


def _edges(path, n=65536):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        h.update(f.read(n))
        try:
            f.seek(-n, os.SEEK_END)
        except OSError:
            f.seek(0)
        h.update(f.read(n))
    return h.hexdigest()[:16]


def fingerprint(path):
    """(size, mtime in ns, hash of the first and last 64 KB) of the file
    on disk, or None - whole-second time + size missed a same-size save
    within the second on a share (review 1, Nov 4)."""
    try:
        st = os.stat(path)
        return (st.st_size, st.st_mtime_ns, _edges(path))
    except OSError:
        return None


def changed_since(path, seen):
    """True when the file on disk isn't the one we opened / last saved."""
    now = fingerprint(path)
    if seen is None or now is None:
        return False
    if len(seen) != len(now):            # kept by an older version
        return (now[0], int(now[1] // 1_000_000_000)) != tuple(seen[:2])
    return now != tuple(seen)


# ---- local copy workflow (Venice #14, Nov 4) ------------------------------
# For a file on a share or in a synced folder: work on a copy on this PC,
# then copy it back - refused if someone changed the original meanwhile.

LOCAL_DIR = "local_copies"
_SIDE = ".qslocal.json"


class CopyBackError(Exception):
    pass


def local_root():
    from . import settings
    return os.path.join(settings.DIR, LOCAL_DIR)


def make_local_copy(path, root=None):
    """Copy `path` to this PC and return the copy's path. A note beside
    the copy remembers the original and what it looked like."""
    import shutil
    path = os.path.abspath(path)
    tag = hashlib.sha1(unc(path).lower().encode("utf-8")).hexdigest()[:10]
    folder = os.path.join(root or local_root(), tag)
    os.makedirs(folder, exist_ok=True)
    local = os.path.join(folder, os.path.basename(path))
    tmp = local + ".copying"
    shutil.copy2(path, tmp)
    os.replace(tmp, local)
    with open(local + _SIDE, "w", encoding="utf-8") as f:
        json.dump({"original": path, "seen": list(fingerprint(path) or ()),
                   "copied": datetime.datetime.now().isoformat(
                       timespec="seconds")}, f)
    return local


def local_copy_info(local):
    """The note for a local copy ({original, seen, copied}), or None."""
    try:
        with open(os.path.abspath(local) + _SIDE, encoding="utf-8") as f:
            info = json.load(f)
        return info if isinstance(info, dict) and info.get("original") \
            else None
    except (OSError, ValueError):
        return None


def _replace_retrying(src, dst, tries=6, pause=0.25):
    """os.replace, tried again for a moment when Windows says the file is
    in use: a sync client or a virus scanner often holds it for a blink
    right after a save."""
    import time
    for i in range(tries):
        try:
            return os.replace(src, dst)
        except PermissionError:
            if i == tries - 1:
                raise
            time.sleep(pause)


def copy_back(local, force=False):
    """Put the local copy back over the original. Refused (CopyBackError)
    when the original changed since the copy was made, unless force - the
    caller then keeps theirs as "<name> (mine).pdf" instead of losing
    either. Returns the path written."""
    import shutil
    info = local_copy_info(local)
    if not info:
        raise CopyBackError("This isn't a local copy QuantiSheet made.")
    orig = info["original"]
    if not os.path.isdir(os.path.dirname(orig)):
        raise CopyBackError(f"The original's folder isn't reachable now: "
                            f"{os.path.dirname(orig)}")
    if os.path.exists(orig) and changed_since(orig, info.get("seen")) \
            and not force:
        raise CopyBackError(
            "Someone changed the original since you made your copy. "
            "Copying back would overwrite their work.")
    if force and os.path.exists(orig) and \
            changed_since(orig, info.get("seen")):
        base, ext = os.path.splitext(orig)
        target = f"{base} (mine){ext}"
    else:
        target = orig
    tmp = target + ".qscopy"
    try:
        shutil.copy2(local, tmp)
        _replace_retrying(tmp, target)
    except OSError as e:
        # Windows refuses (WinError 5/32) while the original is open in a
        # tab or another program; take the half-written copy away again
        # and say so plainly (Chief's estimator test, Nov 7)
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            log.warning("couldn't remove %s", tmp, exc_info=True)
        raise CopyBackError(
            f"The original couldn't be replaced - it's open somewhere "
            f"(another tab, another program or another person). Close it "
            f"and try Copy Back again. Your local copy is unchanged.\n\n"
            f"({e.strerror or e})") from e
    if target == orig:
        info["seen"] = list(fingerprint(orig) or ())
        info["copied_back"] = datetime.datetime.now().isoformat(
            timespec="seconds")
        with open(os.path.abspath(local) + _SIDE, "w", encoding="utf-8") as f:
            json.dump(info, f)
    return target
