"""Crash-safe file writes.

atomic_save(doc, path)  - save a PDF (PyMuPDF document) to a temp file in the
                          same folder, flush it to disk, then swap it in. If
                          anything fails the old file is untouched.
atomic_write(path, data) - the same for bytes or text.
backup_once(path)       - copy a file to <file>.bak once per session, before
                          it is changed in place (incremental saves).
"""
import logging
import os
import shutil

log = logging.getLogger(__name__)

_BACKED_UP = set()


def _tmp(path):
    return f"{path}.{os.getpid()}.tmp"


def _fsync(path):
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0))
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        pass


class FileInUseError(OSError):
    """The file to be replaced is open (on Windows an open PDF can't be
    swapped). The original is untouched."""


def same_file(doc, path):
    """True when `path` is the file `doc` was opened from."""
    name = getattr(doc, "name", "") or ""
    try:
        return bool(name) and os.path.normcase(os.path.abspath(name)) == \
            os.path.normcase(os.path.abspath(os.fspath(path)))
    except (TypeError, ValueError):
        return False


def atomic_save(doc, path, **kw):
    """doc.save(path, **kw) without ever leaving a half-written file.
    Windows won't replace a file PyMuPDF has open (the document's own file,
    or one open in a tab): that raises FileInUseError with a plain message
    and leaves the original as it was (review 3b B8)."""
    path = os.fspath(path)
    tmp = _tmp(path)
    try:
        doc.save(tmp, **kw)
        _fsync(tmp)
        try:
            os.replace(tmp, path)
        except PermissionError as e:
            raise FileInUseError(
                f"{os.path.basename(path)} is open (in QuantiSheet or another "
                "program), so it can't be replaced. Save under a different "
                "name, or close it first.") from e
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    return path


def atomic_write(path, data, encoding="utf-8"):
    path = os.fspath(path)
    tmp = _tmp(path)
    mode = "wb" if isinstance(data, (bytes, bytearray)) else "w"
    try:
        with open(tmp, mode, **({} if mode == "wb" else
                                {"encoding": encoding, "newline": ""})) as f:
            f.write(data)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    return path


def backup_once(path):
    """Copy `path` to `path`.bak once per session (before an in-place
    save). Returns the backup path, or None if skipped or not possible."""
    path = os.fspath(path)
    key = os.path.normcase(os.path.abspath(path))
    if key in _BACKED_UP or not os.path.isfile(path):
        return None
    bak = path + ".bak"
    try:
        tmp = _tmp(bak)
        shutil.copy2(path, tmp)
        os.replace(tmp, bak)
    except OSError:
        log.warning("couldn't back up %s before saving", path,
                    exc_info=True)
        return None
    _BACKED_UP.add(key)
    return bak


# ---- keeping a document's password protection on copies (S7) -------------
class UnprotectedCopyError(RuntimeError):
    """A copy of a password-protected document could not be written with
    its protection. Nothing was written (the caller may ask the user and
    save an unprotected copy on purpose)."""


def _keep():
    import fitz
    return getattr(fitz, "PDF_ENCRYPT_KEEP", 1)


def is_encrypted(doc):
    """True when `doc` is protected (a password to open it, or just
    permissions). Stays True after it was unlocked with authenticate()."""
    try:
        return bool((doc.metadata or {}).get("encryption"))
    except Exception:
        return False


def file_encrypted(path):
    """True when the PDF at `path` is encrypted."""
    import fitz
    try:
        d = fitz.open(os.fspath(path))
    except Exception:
        return False
    try:
        return bool(d.needs_pass or (d.metadata or {}).get("encryption"))
    except Exception:
        return False
    finally:
        d.close()


def save_keeping_encryption(doc, path, fallback=None, **kw):
    """doc.save(path, **kw); a protected document keeps its encryption,
    passwords and permissions exactly (PDF_ENCRYPT_KEEP). The saved file
    is checked: when KEEP raised or the file came back unencrypted, it is
    saved with `fallback` (save() keywords that encrypt it again, e.g.
    DocProtection.save_args()); with no fallback, or when that fails too,
    the file is removed and UnprotectedCopyError raised.
    Returns None (not protected), "keep" or "fallback"."""
    path = os.fspath(path)
    kw.pop("encryption", None)
    if not is_encrypted(doc):
        doc.save(path, **kw)
        return None
    try:
        doc.save(path, encryption=_keep(), **kw)
        if file_encrypted(path):
            return "keep"
        log.warning("saving with the document's own encryption wrote an "
                    "unencrypted file")
    except Exception:
        log.warning("saving with the document's own encryption failed",
                    exc_info=True)
    if fallback:
        try:
            doc.save(path, **dict(kw, **fallback))
            if file_encrypted(path):
                return "fallback"
        except Exception:
            log.warning("re-encrypting the saved copy failed", exc_info=True)
    try:
        os.remove(path)
    except OSError:
        pass
    raise UnprotectedCopyError(
        "The copy could not be saved with this document's password "
        "protection, so no file was written.")


def atomic_save_keeping_encryption(doc, path, fallback=None, **kw):
    """atomic_save() with save_keeping_encryption(): the temp file is
    checked before it replaces anything."""
    path = os.fspath(path)
    tmp = _tmp(path)
    try:
        how = save_keeping_encryption(doc, tmp, fallback, **kw)
        _fsync(tmp)
        try:
            os.replace(tmp, path)
        except PermissionError as e:
            raise FileInUseError(
                f"{os.path.basename(path)} is open (in QuantiSheet or another "
                "program), so it can't be replaced. Save under a different "
                "name, or close it first.") from e
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    return how


def protected_copy(doc, password=None, **kw):
    """An in-memory copy of `doc` (doc.tobytes(**kw), reopened) that keeps
    its encryption, unlocked with `password` when it needs one; saving it
    with save_keeping_encryption keeps the original passwords and
    permissions. An unprotected document: a plain copy.
    UnprotectedCopyError when a protected copy can't be made or opened."""
    import fitz
    kw.pop("encryption", None)
    if not is_encrypted(doc):
        return fitz.open("pdf", doc.tobytes(**kw))
    try:
        data = doc.tobytes(encryption=_keep(), **kw)
        copy = fitz.open("pdf", data)
    except Exception as e:
        raise UnprotectedCopyError(
            "A protected copy of this document could not be made.") from e
    if copy.needs_pass and not (password and copy.authenticate(password)):
        copy.close()
        raise UnprotectedCopyError(
            "A protected copy of this document could not be unlocked.")
    return copy


BIG_SET = 60


def gc_level(doc):
    """garbage= level for saving `doc`. Level 3 also merges duplicate
    objects, and that search grows with the square of the file: fine for
    a few sheets, but saving a copy of a 309-sheet set took 2.5 minutes and
    an 800-sheet set never finished. Big sets get level 1 (unused objects
    are still dropped, so removed content is still gone)."""
    try:
        return 3 if doc.page_count <= BIG_SET else 1
    except Exception:
        return 1
