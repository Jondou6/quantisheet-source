"""Why a file didn't open, in words that say what to do (Venice #9, Nov 4),
and a repair pass for a damaged PDF (Venice #10).

Kinds: "missing", "permission", "in_use", "not_pdf", "damaged",
"password", "internal". Each has a plain message and a next step; the
technical detail goes in Details.
"""
import errno
import logging
import os

log = logging.getLogger(__name__)

TEXT = {
    "missing": ("The file isn't there any more.",
                "It may have been moved, renamed or deleted. Open it from "
                "where it is now (File > Open)."),
    "permission": ("Windows won't let QuantiSheet read this file.",
                   "Check that you have permission for that folder, or copy "
                   "the file somewhere of your own and open the copy."),
    "in_use": ("Another program has this file open and locked.",
               "Close it there (or wait for a sync to finish), then open "
               "it again."),
    "not_pdf": ("This isn't a PDF.",
                "Open a .pdf file, or use File > Convert to PDF first."),
    "damaged": ("This PDF is damaged.",
                "QuantiSheet can try to repair a copy (your file isn't "
                "changed). Otherwise ask for a new copy of the file."),
    "password": ("This PDF needs a password.",
                 "Ask whoever sent it for the password."),
    "internal": ("QuantiSheet hit a problem opening this file.",
                 "Try again. If it keeps happening, use Help > Report an "
                 "Issue so it can be fixed."),
}


def classify(exc, path=""):
    """The kind of open failure for exception `exc`."""
    if isinstance(exc, FileNotFoundError) or \
            (path and not os.path.exists(path)):
        return "missing"
    if isinstance(exc, PermissionError):
        win = getattr(exc, "winerror", None)
        return "in_use" if win in (32, 33) else "permission"
    if isinstance(exc, OSError) and getattr(exc, "errno", None) in (
            errno.EACCES, errno.EPERM):
        return "permission"
    text = str(exc).lower()
    if "password" in text or "encrypt" in text:
        return "password"
    if "no objects found" in text or "not a pdf" in text or \
            "unknown file type" in text or "failed to open" in text and \
            path and not path.lower().endswith(".pdf"):
        return "not_pdf"
    if any(k in text for k in ("damaged", "syntax", "xref", "trailer",
                               "cannot", "broken", "format error",
                               "zlib", "repair", "eof")):
        return "damaged"
    if path and os.path.isfile(path):
        try:
            with open(path, "rb") as f:
                head = f.read(1024)
            if b"%PDF" not in head:
                return "not_pdf"
            return "damaged"
        except OSError:
            pass
    return "internal"


def message(kind, path=""):
    head, step = TEXT.get(kind, TEXT["internal"])
    name = os.path.basename(path) if path else "The file"
    return f"{name}: {head}", step


def repair(path, out=None):
    """Try to read a damaged PDF and save a cleaned copy beside it
    ("<name> (repaired).pdf"). The original is never changed. Returns the
    copy's path, or raises the last error."""
    import fitz
    with open(path, "rb") as f:
        data = f.read()
    start = data.find(b"%PDF")
    if start > 0:
        data = data[start:]            # junk before the header
    doc = fitz.open("pdf", data)       # MuPDF rebuilds a broken xref
    try:
        if doc.page_count == 0:
            raise ValueError("no readable pages")
        base, _ext = os.path.splitext(path)
        out = out or f"{base} (repaired).pdf"
        n = 2
        while os.path.exists(out):
            out = f"{base} (repaired {n}).pdf"
            n += 1
        doc.save(out, garbage=4, deflate=True, clean=True)
    finally:
        doc.close()
    log.info("repaired %s -> %s", path, out)
    return out
