"""Write one embedded file or file-attachment out of a PDF, and stop there.

``extract(doc, name, allowed_ext)`` finds ``name`` in the document, writes
the bytes into a new temporary directory, and returns that path. It does
not open the PDF (pass a document that is already open), and it does not
open or run the file it wrote.

The last extension has to be on ``allowed_ext``. A blocked extension is
refused even when it is also on the allow-list. Names with a directory, a
drive, or ``..`` are reduced to the final component and that component is
written only inside the new temporary directory.
"""
import os
import shutil
import tempfile

from . import embfiles

class ExtractError(ValueError):
    """The attachment was not written."""


# Extensions Windows will run, install, or follow as a shortcut. The
# allow-list cannot put one of these back. The set is the types named for
# this extractor plus the usual blocked-attachment list (scripts,
# installers, shortcuts, and certificate files Windows will install).
DENY_EXT = frozenset({
    ".exe", ".lnk", ".bat", ".js", ".vbs", ".ps1", ".scr", ".cmd",
    ".msi", ".com", ".hta", ".jar",
    ".ade", ".adp", ".app", ".application", ".appref-ms", ".asp",
    ".bas", ".cab", ".cer", ".chm", ".cpl", ".crt", ".csh", ".der",
    ".diagcab", ".dll", ".drv", ".gadget", ".hlp", ".img", ".inf",
    ".ins", ".iso", ".isp", ".its", ".jse", ".ksh", ".lib", ".library-ms",
    ".mad", ".maf", ".mag", ".mam", ".maq", ".mar", ".mas", ".mat",
    ".mau", ".mav", ".maw", ".mda", ".mdb", ".mde", ".mdt", ".mdw",
    ".mdz", ".msc", ".msh", ".msh1", ".msh1xml", ".msh2", ".msh2xml",
    ".mshxml", ".msp", ".mst", ".msix", ".appx", ".appxbundle", ".ocx",
    ".ops", ".pcd", ".pif", ".plg", ".prf", ".prg", ".ps1xml", ".ps2",
    ".ps2xml", ".psc1", ".psc2", ".psd1", ".psm1", ".pst", ".py", ".pyc",
    ".pyw", ".reg", ".scf", ".sct", ".search-ms", ".settingcontent-ms",
    ".shb", ".shs", ".sys", ".theme", ".tmp", ".url", ".vb", ".vbe",
    ".vhd", ".vhdx", ".vsmacros", ".vsw", ".website", ".ws", ".wsc",
    ".wsf", ".wsh", ".xnk",
})

# Windows device names, with or without an extension (CON.pdf is CON).
_RESERVED = frozenset({
    "CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$",
} | {f"COM{n}" for n in range(1, 10)} | {f"LPT{n}" for n in range(1, 10)})

# Bidirectional marks and zero-width characters, so a name cannot hide
# its extension behind them.
_STRIP = frozenset(
    "\u200b\u200c\u200d\u200e\u200f\u202a\u202b\u202c\u202d\u202e"
    "\u2066\u2067\u2068\u2069\ufeff")

# Same prefix settings.TEMP_PREFIX uses, so a later temp sweep can see it.
_TEMP_PREFIX = "quantisheet-extract-"


MAX_BYTES = 200 * 1024 * 1024     # Nov 4: no attachment bigger than this


def extract(doc, name, allowed_ext, max_bytes=MAX_BYTES):
    """Write attachment ``name`` into a new temp directory and return the path.

    ``doc`` is an open PDF document, not a path. ``allowed_ext`` is one
    extension (``".pdf"`` or ``"pdf"``) or a list of them. The returned
    path is absolute, inside a directory created for this call, mode 0600
    where the operating system honours that mode.
    """
    if isinstance(doc, (str, bytes, os.PathLike)):
        raise ExtractError("Pass an open PDF document, not a path.")
    if not isinstance(name, str) or not name.strip():
        raise ExtractError("Bad attachment name.")
    if allowed_ext is None:
        raise ExtractError("An allow-list of extensions is required.")
    kind, key, filename = _find(doc, name)
    data = _bytes(doc, kind, key)
    if max_bytes is not None and len(data) > max_bytes:
        raise ExtractError(
            f"The attachment is too big to save ({len(data) / 1e6:,.0f} MB; "
            f"the limit is {max_bytes / 1e6:,.0f} MB).")
    # The name inside the PDF decides the type, not only the name asked for.
    leaf = _safe_leaf(filename or name, allowed_ext)
    directory = tempfile.mkdtemp(prefix=_TEMP_PREFIX)
    path = os.path.join(directory, leaf)
    try:
        _inside(directory, path)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(fd, data)
        finally:
            os.close(fd)
    except Exception:
        shutil.rmtree(directory, ignore_errors=True)
        raise
    return os.path.abspath(path)


# what Document > Attachments lets you save (documents, drawings, pictures)
SAVE_EXT = (".pdf", ".txt", ".csv", ".xlsx", ".xls", ".docx", ".doc",
            ".dwg", ".dxf", ".png", ".jpg", ".jpeg", ".tif", ".tiff",
            ".xml", ".json", ".zip")


def listing(doc):
    """[(name, kind)] of the attachments a person could want - not
    QuantiSheet's own job data kept inside the PDF."""
    out = []
    for kind, key, filename in _candidates(doc):
        name = str(filename or key)
        if _leaf(name).lower().startswith("quantisheet_"):
            continue
        out.append((name, kind))
    return out


def _find(doc, name):
    cands = _candidates(doc)
    want = name.casefold()
    leaf = _leaf(name).casefold()
    exact = [c for c in cands if _is_exact(c, want)]
    if len(exact) > 1:
        embedded = [c for c in exact if c[0] == "embedded"]
        if len(embedded) == 1:
            return embedded[0]
        raise ExtractError("More than one attachment has that name.")
    if len(exact) == 1:
        return exact[0]
    if leaf:
        loose = [c for c in cands if _leaf(c[2]).casefold() == leaf or
                 (c[0] == "embedded" and _leaf(str(c[1])).casefold() == leaf)]
        if len(loose) > 1:
            raise ExtractError("More than one attachment has that name.")
        if len(loose) == 1:
            return loose[0]
    raise ExtractError("No attachment with that name.")


def _is_exact(cand, want):
    kind, key, filename = cand
    if str(filename).casefold() == want:
        return True
    return kind == "embedded" and str(key).casefold() == want


def _candidates(doc):
    out = []
    try:
        names = list(doc.embfile_names() or [])
    except Exception as e:
        raise ExtractError("This document's attachments could not be read.") from e
    for embedded_name in names:
        filename = embedded_name
        try:
            info = doc.embfile_info(embedded_name) or {}
            filename = info.get("filename") or info.get("name") or embedded_name
        except Exception:
            filename = embedded_name
        out.append(("embedded", embedded_name, str(filename)))
    try:
        pages = list(doc)
    except Exception as e:
        raise ExtractError("This document's attachments could not be read.") from e
    for page in pages:
        try:
            annots = page.annots() or []
        except Exception:
            continue
        for annot in annots:
            try:
                if annot.type[1] != "FileAttachment":
                    continue
                info = annot.file_info or {}
                filename = str(info.get("filename") or "")
            except Exception:
                continue
            if not filename:
                continue
            # Read the bytes now. The annotation is not usable once the
            # page iterator has moved on.
            try:
                payload = annot.get_file()
            except Exception:
                continue
            if payload is None:
                continue
            out.append(("annot", bytes(payload), filename))
    return out


def _bytes(doc, kind, key):
    try:
        if kind == "embedded":
            data = embfiles.get(doc, key)
        else:
            data = key
    except Exception as e:
        raise ExtractError("The attachment could not be read.") from e
    if data is None:
        raise ExtractError("The attachment could not be read.")
    return bytes(data)


def _safe_leaf(name, allowed_ext):
    cleaned = "".join(ch for ch in str(name) if ch not in _STRIP)
    if "\x00" in cleaned or any(ord(ch) < 32 for ch in cleaned):
        raise ExtractError("Bad attachment name.")
    # A drive (C:\...) or a directory is reduced to the final component
    # before the checks, so the drive's colon is not an alternate stream.
    leaf = _leaf(cleaned).strip().rstrip(". ")
    if leaf in ("", ".", ".."):
        raise ExtractError("Bad attachment name.")
    # ":" left in the file name is an NTFS alternate stream
    # (note.pdf:hidden.exe).
    if ":" in leaf or any(ch in '<>"|?*' for ch in leaf):
        raise ExtractError("Bad attachment name.")
    if len(leaf) > 180:
        raise ExtractError("Attachment name is too long.")
    stem = leaf.split(".", 1)[0].rstrip(" .").upper()
    if stem in _RESERVED:
        raise ExtractError("Bad attachment name.")
    final, every = _extensions(leaf)
    allowed = _allow(allowed_ext)
    if every & DENY_EXT or final in DENY_EXT:
        raise ExtractError("That file type is blocked.")
    if final not in allowed:
        raise ExtractError("That file type is not on the allow-list.")
    return leaf


def _leaf(name):
    text = str(name).replace("\\", "/").rstrip("/")
    if not text:
        return ""
    return text.split("/")[-1]


def _extensions(leaf):
    parts = leaf.split(".")
    if len(parts) < 2:
        return "", set()
    every = {"." + part.lower() for part in parts[1:] if part.strip()}
    last = parts[-1].strip().lower()
    final = "." + last if last else ""
    return final, every


def _allow(allowed_ext):
    if isinstance(allowed_ext, str):
        items = [allowed_ext]
    else:
        try:
            items = list(allowed_ext)
        except TypeError as e:
            raise ExtractError("An allow-list of extensions is required.") from e
    out = set()
    for item in items:
        text = str(item or "").strip().lower()
        if not text:
            continue
        if not text.startswith("."):
            text = "." + text
        out.add(text)
    return out


def _inside(directory, path):
    base = os.path.realpath(directory)
    dest = os.path.realpath(path)
    if os.path.commonpath([base, dest]) != base:
        raise ExtractError("Bad attachment name.")
