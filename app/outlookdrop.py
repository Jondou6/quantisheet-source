"""A PDF dragged out of an Outlook message onto QuantiSheet (Jon, Nov
27: the Outlook plan's option A - no add-in; bid sets and addenda arrive
by email).

An attachment dragged from Outlook is not a file on disk yet. Outlook
hands over a list of file names ("FileGroupDescriptorW") and, on request,
each file's bytes ("FileContents"). This saves the PDFs among them in
Downloads\\QuantiSheet (the folder the browser add-on uses) and gives back
the saved paths for the window to open.

Two ways to the bytes, tried in order:
  1. what the drag itself carries (works when one file was dragged and
     the mail program hands its bytes over the simple way);
  2. classic Outlook itself, asked through its own automation (the one
     QuantiSheet already uses to send email, app/mail.py): the
     attachments selected in the Outlook window in front, by name.

Only PDFs are saved: the name must end in .pdf and the bytes must start
with %PDF. Nothing else in the message is read.
"""
import logging
import os
import struct

log = logging.getLogger(__name__)

NAMES = 'application/x-qt-windows-mime;value="FileGroupDescriptorW"'
BYTES = 'application/x-qt-windows-mime;value="FileContents"'
_ENTRY = 592                    # one FILEDESCRIPTORW
_NAME_AT = 72                   # where its file name starts
MAX_FILES = 20
MAX_BYTES = 2 * 1024 ** 3


def names(mime):
    """The file names a drag from a mail program carries ([] for any
    other drag)."""
    try:
        if not mime.hasFormat(NAMES):
            return []
        raw = bytes(mime.data(NAMES))
    except Exception:                                     # noqa: BLE001
        return []
    return parse_names(raw)


def parse_names(raw):
    if len(raw) < 4:
        return []
    (n,) = struct.unpack_from("<I", raw, 0)
    out = []
    for i in range(min(n, 500)):
        at = 4 + i * _ENTRY + _NAME_AT
        chunk = raw[at:at + 520]
        if len(chunk) < 2:
            break
        name = chunk.decode("utf-16-le", "replace").split("\x00", 1)[0]
        if name:
            out.append(name)
    return out


def pdf_names(mime):
    return [n for n in names(mime) if n.lower().endswith(".pdf")]


def is_pdf(data):
    return b"%PDF-" in bytes(data[:1024])


def _carried(mime):
    """The bytes the drag itself hands over (the first file's), or None."""
    try:
        if not mime.hasFormat(BYTES):
            return None
        data = bytes(mime.data(BYTES))
    except Exception:                                     # noqa: BLE001
        return None
    return data if data and is_pdf(data) else None


def _save(folder, name, data):
    from . import browserhost
    os.makedirs(folder, exist_ok=True)
    path = browserhost.free_path(folder, browserhost.safe_name(name))
    with open(path, "wb") as f:
        f.write(data)
    return path


def _from_outlook(wanted, folder, connect=None):
    """Ask classic Outlook for the selected attachments named in `wanted`
    and save them. [] when Outlook isn't there or has nothing selected."""
    from . import browserhost
    want = {n.lower() for n in wanted}
    out = []
    co = None
    try:
        if connect is None:
            import pythoncom
            import win32com.client
            pythoncom.CoInitialize()
            co = pythoncom
            # the Outlook that is running: never start one for a drop
            app = win32com.client.GetActiveObject("Outlook.Application")
        else:
            app = connect()
        win = app.ActiveWindow()
        picked = []
        try:                         # the attachments selected in it
            sel = win.AttachmentSelection
            picked = [sel.Item(i) for i in range(1, sel.Count + 1)]
        except Exception:                                 # noqa: BLE001
            picked = []
        if not [a for a in picked if str(a.FileName).lower() in want]:
            # none selected by that name: the open message's own
            try:
                item = win.CurrentItem           # a message window
            except Exception:                             # noqa: BLE001
                item = win.Selection.Item(1)     # the reading pane
            atts = item.Attachments
            picked = [atts.Item(i) for i in range(1, atts.Count + 1)]
        os.makedirs(folder, exist_ok=True)
        for a in picked:
            name = str(a.FileName)
            if name.lower() not in want or len(out) >= MAX_FILES:
                continue
            want.discard(name.lower())           # one of each name
            path = browserhost.free_path(folder, browserhost.safe_name(name))
            a.SaveAsFile(path)
            if _saved_pdf(path):
                out.append(path)
    except Exception:                                     # noqa: BLE001
        log.info("Outlook didn't hand over the dragged attachment",
                 exc_info=True)
    finally:
        if co is not None:
            co.CoUninitialize()
    return out


def _saved_pdf(path):
    """Keep the saved file only when it really is a PDF."""
    try:
        ok = 0 < os.path.getsize(path) <= MAX_BYTES
        if ok:
            with open(path, "rb") as f:
                ok = is_pdf(f.read(1024))
        if not ok:
            os.remove(path)
        return ok
    except OSError:
        return False


def save(mime, folder=None):
    """What can be saved while the drop is happening: (saved paths, the
    PDF names still to fetch). The names left are for later() once the
    drop is over - Outlook can't be asked for anything while it is still
    busy with its own drag."""
    wanted = pdf_names(mime)[:MAX_FILES]
    if not wanted:
        return [], []
    data = _carried(mime)
    if data is not None and len(names(mime)) == 1:
        try:
            return [_save(folder or _folder(), wanted[0], data)], []
        except OSError:
            log.warning("dragged PDF not saved", exc_info=True)
            return [], []
    try:                    # for the log, if Outlook can't supply it either
        save.last_formats = ", ".join(mime.formats())[:600]
    except Exception:                                     # noqa: BLE001
        save.last_formats = ""
    return [], wanted


save.last_formats = ""


def later(wanted, folder=None, connect=None):
    """After the drop: the PDFs named `wanted`, from classic Outlook."""
    got = _from_outlook(wanted, folder or _folder(), connect)
    if not got:
        log.info("mail drag not opened (%s); it carried: %s",
                 ", ".join(wanted)[:200], save.last_formats)
    return got


def _folder():
    from . import browserhost
    return browserhost.folder()
