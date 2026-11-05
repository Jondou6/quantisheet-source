"""AutoSave and crash recovery for the PDF editor.

Two layers, like Office:

* AutoSave (on by default) saves open documents to their own files every
  couple of minutes while they have changes. It saves incrementally, so it
  is quick even on big sets and keeps existing signatures valid. It waits
  while you are dragging or drawing, or while a dialog is open.
* Recovery copies: a document that has never been saved, one AutoSave
  can't write (read-only, locked by another program), or every document
  when AutoSave is set to "recovery copies only", is copied to
  ~/.quantisheet/autosave. If QuantiSheet closes unexpectedly, the next start
  offers to recover them. Copies are removed once the work is saved or
  deliberately discarded.

Settings: autosave_mode = "file" | "recovery" | "off",
          autosave_minutes (default 2).
"""
import datetime
import hashlib
import json
import logging
import os
import uuid

import fitz
from PySide6.QtCore import QObject, Qt, QTimer
from PySide6.QtWidgets import QApplication

from . import settings

# Identifies this run of QuantiSheet. Recovery copies used to be matched by
# process id, but Windows reuses ids, so a crashed session's copy could be
# taken for this session's and never offered.
SESSION = uuid.uuid4().hex

log = logging.getLogger(__name__)
MODES = ("file", "recovery", "off")
DEFAULT_MINUTES = 2


def mode():
    m = settings.get("autosave_mode", "file")
    return m if m in MODES else "file"


def minutes():
    try:
        return max(1, min(60, int(settings.get("autosave_minutes",
                                               DEFAULT_MINUTES))))
    except (TypeError, ValueError):
        return DEFAULT_MINUTES


def folder():
    d = os.path.join(settings.DIR, "autosave")
    os.makedirs(d, exist_ok=True)
    return d


def _key(view, path):
    ident = os.path.abspath(path) if path else f"untitled-{id(view)}"
    return hashlib.sha1(ident.encode("utf-8")).hexdigest()[:16]


def recovery_paths(view, path):
    k = _key(view, path)
    d = folder()
    return os.path.join(d, k + ".pdf"), os.path.join(d, k + ".json")


def write_recovery(view, path, title="Untitled"):
    # a password-protected PDF is never written out unprotected: no
    # recovery copy for it (0.13.5 security review)
    if (getattr(view.doc, "metadata", None) or {}).get("encryption") or \
            getattr(view.doc, "is_encrypted", False):
        return None
    pdf, meta = recovery_paths(view, path)
    tmp = pdf + ".tmp"
    view.doc.save(tmp, garbage=0, deflate=True)
    os.replace(tmp, pdf)
    with open(meta, "w", encoding="utf-8") as f:
        json.dump({"original": os.path.abspath(path) if path else "",
                   "title": title,
                   "saved": datetime.datetime.now().isoformat(
                       timespec="seconds"),
                   "pages": view.doc.page_count, "pid": os.getpid(),
                   "session": SESSION}, f)
    return pdf


def drop_recovery(view, path):
    for p in recovery_paths(view, path):
        try:
            os.remove(p)
        except OSError:
            pass


def pending():
    """Recovery copies left by a session that didn't close normally:
    [{pdf, original, title, saved, pages}] newest first."""
    out = []
    d = folder()
    for name in os.listdir(d):
        if not name.endswith(".json"):
            continue
        meta = os.path.join(d, name)
        pdf = meta[:-5] + ".pdf"
        try:
            with open(meta, encoding="utf-8") as f:
                m = json.load(f)
        except (OSError, ValueError):
            continue
        if not os.path.exists(pdf):
            continue
        if m.get("session") == SESSION:          # ours, this session
            continue
        orig = m.get("original") or ""
        if orig and os.path.exists(orig) and \
                os.path.getmtime(orig) >= os.path.getmtime(pdf):
            for p in (meta, pdf):                # the file is newer
                try:
                    os.remove(p)
                except OSError:
                    pass
            continue
        out.append(dict(m, pdf=pdf, meta=meta))
    out.sort(key=lambda m: m.get("saved", ""), reverse=True)
    return out


def discard(item):
    for p in (item.get("pdf"), item.get("meta")):
        try:
            os.remove(p)
        except (OSError, TypeError):
            pass


class AutoSaver(QObject):
    """Runs in the main window. ``tick()`` does one pass (tests call it)."""

    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.last = None              # datetime of the last autosave
        self.problem = ""
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.restart()

    def restart(self):
        self.timer.stop()
        if mode() != "off":
            self.timer.start(minutes() * 60 * 1000)
        self.win._autosave_status()

    def _busy(self):
        if QApplication.mouseButtons() != Qt.NoButton:
            return True
        if QApplication.activeModalWidget() is not None:
            return True
        return False

    def tabs(self):
        from .main_window import DocTab
        for i in range(self.win.tabs.count()):
            t = self.win.tabs.widget(i)
            if isinstance(t, DocTab):
                yield t

    def tick(self, force=False):
        """Save every changed document. Returns how many were saved."""
        m = mode()
        if m == "off" and not force:
            return 0
        if self._busy() and not force:
            QTimer.singleShot(15000, self.tick)      # try again shortly
            return 0
        n = 0
        self.problem = ""
        for tab in list(self.tabs()):
            v = tab.view
            if not v.dirty:
                continue
            if getattr(v, "session", None) and \
                    getattr(v.session, "role", "") == "peer":
                continue                 # the host saves a shared document
            try:
                if m == "file" and tab.path and self._save_file(tab):
                    drop_recovery(v, tab.path)
                    n += 1
                    continue
                write_recovery(v, tab.path, getattr(tab, "title", "") or
                               os.path.basename(tab.path or "Untitled"))
                n += 1
            except Exception as e:
                log.warning("autosave of %s failed: %s", tab.path, e)
                self.problem = str(e)
        if n:
            self.last = datetime.datetime.now()
        self.win._autosave_status()
        return n

    def _save_file(self, tab):
        """Save to the document's own file if that is quick and allowed."""
        v = tab.view
        path = tab.path
        if not os.path.exists(path) or not os.access(path, os.W_OK):
            self.problem = f"{os.path.basename(path)} is read-only - kept " \
                           "a recovery copy instead"
            return False
        doc = v.doc
        same = bool(doc.name) and os.path.abspath(doc.name) == \
            os.path.abspath(path)
        if not (same and doc.can_save_incrementally()):
            # a full rewrite reloads the document under you; leave that
            # to a real Save and keep a recovery copy meanwhile
            return False
        try:
            self.win._write(path, view=v)
        except Exception as e:
            self.problem = f"Couldn't save {os.path.basename(path)} " \
                           f"({e}) - kept a recovery copy instead"
            return False
        v.dirty = False
        if v is self.win._view:
            self.win._update_status()
        else:
            i = self.win.tabs.indexOf(tab)
            self.win.tabs.setTabText(i, os.path.basename(path))
        return True

    def saved(self, view, path):
        """A normal save happened: the recovery copy isn't needed."""
        drop_recovery(view, path)

    def closed(self, view, path):
        drop_recovery(view, path)
