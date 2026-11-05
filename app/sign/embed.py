"""Store the audit trail inside the PDF as an embedded file."""
import os
import shutil
import tempfile

import fitz
from .audit import AuditLog
from .. import embfiles

NAME = "quantisheet_audit.json"


def embed_audit(src, out, log=None):
    """Write `log` into a copy of `src` at `out`.

    - If `log` is None, the existing trail is kept (or a new one started).
    - An existing trail is updated rather than silently left unchanged
      (the original ignored the "already exists" error).
    - The change is saved incrementally, so existing signatures stay valid.
    """
    if log is None:
        log = read_audit(src)
        if log is None:
            log = AuditLog()
            log.add("created", "system", "audit log initialized")
    data = log.to_json().encode("utf-8")

    same = os.path.abspath(src) == os.path.abspath(out)
    if not same:
        shutil.copyfile(src, out)
    doc = fitz.open(out)
    try:
        # replace rather than embfile_upd(), which is broken in some
        # PyMuPDF releases (it crashes when given bytes)
        embfiles.put(doc, NAME, data, "QuantiSheet audit trail")
        if doc.can_save_incrementally():
            doc.save(out, incremental=True,
                     encryption=fitz.PDF_ENCRYPT_KEEP)
            return out
        fd, tmp = tempfile.mkstemp(suffix=".pdf",
                                   dir=os.path.dirname(os.path.abspath(out)))
        os.close(fd)
        doc.save(tmp, garbage=1, deflate=True)
    finally:
        doc.close()
    os.replace(tmp, out)
    return out


def read_audit(src):
    doc = fitz.open(src)
    try:
        if NAME in doc.embfile_names():
            return AuditLog.from_json(doc.embfile_get(NAME).decode("utf-8"))
    except (ValueError, KeyError, TypeError, UnicodeDecodeError):
        return None
    finally:
        doc.close()
    return None
