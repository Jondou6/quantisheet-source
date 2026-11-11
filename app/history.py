"""Undo / redo.

Two kinds of step:

* "pages" - markup edits. Only the annotations of the touched pages are
  recorded (the page's /Annots array plus the annotation objects and their
  appearance streams), before and after the edit. Undo and redo rewrite
  those few objects in place: instant, and a few KB per step even on a
  700-page, 15 MB spec book.
* "full" - anything else (page operations, redaction, text edits,
  bookmarks...). The whole document is saved to memory after the change,
  as before.

The document must keep its object numbers between steps, so snapshots use
doc.tobytes() with no garbage collection (its default).
"""
import logging
import re

import fitz

_REF = re.compile(r"(\d+)\s+0\s+R")
# keys that lead away from the annotation: its page, its form-field parent
# (shared with widgets on other pages), the annotation it replies to
_SKIP_KEYS = {"P", "Parent", "IRT", "Kids", "Dest", "D"}
_STRUCTURAL = re.compile(r"/Type\s*/(Page|Pages|Catalog)\b")


def _refs(text):
    return [int(m) for m in _REF.findall(text or "")]


_SKIP_RE = re.compile(r"/(?:P|Parent|IRT|Kids|Dest|D)\s+\d+\s+0\s+R"
                      r"|/(?:Kids|Dest|D)\s*\[[^\]]*\]")


# object source -> (structural?, references). The same markup text gives
# the same answer, and most markups don't change between two edits: the
# regex work was half of every undo record (torture test, Nov 10)
_SCAN = {}


def _scan(src):
    got = _SCAN.get(src)
    if got is None:
        if len(_SCAN) > 50000:
            _SCAN.clear()
        got = (bool(_STRUCTURAL.search(src)), _refs(_SKIP_RE.sub("", src)))
        _SCAN[src] = got
    return got


def _capture(doc, x, objs, page_xref):
    """Record object `x` and the objects it uses (appearance streams,
    fonts, popups). Reads each object's source once and finds its
    references in the text (looking keys up one by one was slow on
    sheets with hundreds of markups)."""
    todo = [x]
    n = doc.xref_length()
    while todo:
        x = todo.pop()
        if x in objs or x <= 0 or x >= n or x == page_xref:
            continue
        src = doc.xref_object(x, compressed=False)
        structural, refs = _scan(src)
        if structural:
            continue
        stream = doc.xref_stream(x) if doc.xref_is_stream(x) else None
        objs[x] = (src, stream)
        todo += refs


def page_state(doc, pno):
    """Everything that defines page `pno`'s annotations."""
    page_xref = doc.page_xref(pno)
    annots = doc.xref_get_key(page_xref, "Annots")
    objs = {}
    for x in _refs(annots[1]):
        _capture(doc, x, objs, page_xref)
    # form fields are also listed in the catalog's /AcroForm
    cat = doc.pdf_catalog()
    form = doc.xref_get_key(cat, "AcroForm")
    if form[0] == "xref":
        fx = _refs(form[1])[0]
        objs[fx] = (doc.xref_object(fx, compressed=False), None)
        fields = doc.xref_get_key(fx, "Fields")
        if fields[0] == "xref":
            for x in _refs(fields[1]):
                objs[x] = (doc.xref_object(x, compressed=False), None)
    return {"page": page_xref, "annots": annots, "objs": objs,
            "form": form if form[0] != "xref" else None,
            "rot": doc.xref_get_key(page_xref, "Rotate")}


def restore_page(doc, st):
    n = doc.xref_length()
    for x, (src, stream) in sorted(st["objs"].items()):
        if x < n:
            # most markups on the page didn't change: rewriting (and
            # recompressing) every one of them made undo slow
            try:
                if doc.xref_object(x, compressed=False) == src and (
                        stream is None or doc.xref_stream(x) == stream):
                    continue
            except Exception:
                logging.getLogger(__name__).debug("ignored error", exc_info=True)
        while x >= doc.xref_length():
            doc.get_new_xref()
        doc.update_object(x, src)
        if stream is not None:
            doc.update_stream(x, stream, new=True, compress=True)
            if doc.xref_get_key(x, "DecodeParms")[0] != "null":
                doc.xref_set_key(x, "DecodeParms", "null")
    typ, val = st["annots"]
    doc.xref_set_key(st["page"], "Annots", val if typ != "null" else "null")
    if "rot" in st:
        typ, val = st["rot"]
        doc.xref_set_key(st["page"], "Rotate",
                         val if typ != "null" else "null")
    if st.get("form"):
        typ, val = st["form"]
        doc.xref_set_key(doc.pdf_catalog(), "AcroForm",
                         val if typ != "null" else "null")


def _edit_count(doc):
    from . import annotate
    return annotate.edit_count(doc)


def _fingerprint(doc, pno):
    """Cheap check that a page's markups weren't replaced or added to."""
    try:
        return (doc.xref_length(),
                doc.xref_get_key(doc.page_xref(pno), "Annots"))
    except Exception:                                     # noqa: BLE001
        return None


def _size(states):
    return sum(len(s) + len(b or b"") for st in states.values()
               for s, b in st["objs"].values()) + 200 * len(states)


MIN_BUDGET = 64 * 1024 * 1024       # bytes of undo per document, at least
RAM_SHARE = 0.10                      # of the RAM free when the doc opens


def _available_ram():
    """Bytes of RAM available now, or None if it can't be read."""
    try:
        import ctypes
        if hasattr(ctypes, "windll"):
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong),
                            ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong),
                            ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong),
                            ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong),
                            ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            st = MEMORYSTATUSEX()
            st.dwLength = ctypes.sizeof(st)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
                return int(st.ullAvailPhys)
            return None
    except Exception:
        return None
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    return None


def default_budget():
    """Undo memory for one document: ~10% of free RAM, at least 64 MB."""
    ram = _available_ram()
    return max(MIN_BUDGET, int(ram * RAM_SHARE)) if ram else MIN_BUDGET


class _Step(tuple):
    """One undo step: (kind, a, b, size), plus the name it's undone by
    (Venice #17, Nov 4: "Undo Bulk Edit (412 items)")."""
    label = None


def _step(kind, a, b, size, label=None):
    st = _Step((kind, a, b, size))
    st.label = label
    return st


class History:
    """`source` returns the document's bytes (for "full" steps); pass
    `initial` to start from bytes you already have (e.g. the file)."""

    def __init__(self, source, limit=200, max_bytes=None, initial=None):
        self._source = source if callable(source) else (lambda: source)
        self.limit = limit
        # per document; None = sized to the RAM free right now
        self.max_bytes = default_budget() if max_bytes is None else max_bytes
        self.reset(initial)

    # ---- recording -----------------------------------------------------------
    def reset(self, initial=None):
        self._after = None
        data = self._source() if initial is None else initial
        self.stack = [("full", data, None, len(data))]
        self.pos = 0

    def _push(self, entry):
        if entry[0] != "pages":
            self._after = None
        self.stack = self.stack[:self.pos + 1]
        self.stack.append(entry)
        self.pos = len(self.stack) - 1
        self._trim()

    def snapshot(self, data=None, label=None):
        """A "full" step: call after changing the document. `label` names
        it for Undo ("Delete Pages (3)")."""
        data = self._source() if data is None else data
        if self.stack[self.pos][0] == "full" and \
                self.stack[self.pos][1] == data:
            return                                  # nothing changed
        self._push(_step("full", data, None, len(data), label))

    def begin_pages(self, doc, pages):
        """Call before a markup edit on `pages`; pass the result to
        commit_pages() afterwards.

        A page whose state the last commit recorded, untouched since, is
        not read again (torture test, Nov 10: every markup read all the
        page's markups twice - 218 ms for one rectangle on a sheet with
        500). Untouched means: stamp() was called after that commit, the
        document's edit counter hasn't moved since, and the page's markup
        list and the object count are the same."""
        out = {}
        hit = self._after
        valid = hit is not None and hit["count"] is not None and \
            hit["doc"] == id(doc) and hit["count"] == _edit_count(doc)
        for p in sorted(set(pages)):
            if valid and p in hit["after"] and \
                    hit["fp"].get(p) == _fingerprint(doc, p):
                out[p] = hit["after"][p]
            else:
                out[p] = page_state(doc, p)
        return out

    def stamp(self, doc):
        """Call when the edit just committed is finished (the window has
        recorded it as a change): its pages may be reused by the next
        begin_pages() if nothing changes in between."""
        if self._after is not None and self._after["doc"] == id(doc):
            self._after["count"] = _edit_count(doc)

    def commit_pages(self, doc, before, label=None):
        after = {p: page_state(doc, p) for p in before}
        self._after = {"doc": id(doc), "count": None, "after": after,
                       "fp": {p: _fingerprint(doc, p) for p in after}}
        if after == before:
            return
        self._push(_step("pages", before, after,
                         _size(before) + _size(after), label))

    def undo_label(self):
        """The name of the step Undo would take back, or None."""
        if self.pos <= 0:
            return None
        return getattr(self.stack[self.pos], "label", None)

    def redo_label(self):
        if self.pos >= len(self.stack) - 1:
            return None
        return getattr(self.stack[self.pos + 1], "label", None)

    # ---- memory --------------------------------------------------------------------
    def _trim(self):
        self._evict_bytes()
        too_many = len(self.stack) > self.limit
        if not too_many or self.pos < 2:
            return
        # Drop the older half in one go: the oldest kept step becomes the
        # new starting point (one rebuild every limit/2 steps).
        k = max(1, min(self.pos - 1, len(self.stack) // 2))
        if self.stack[k][0] != "full":
            data = self.state_bytes(k)
            self.stack[k] = ("full", data, None, len(data))
        del self.stack[:k]
        self.pos -= k

    def _evict_bytes(self):
        """Over the memory budget: drop the oldest full snapshot (and the
        markup steps resting on it), one at a time, until it fits. The
        next full snapshot becomes the starting point, so nothing has to
        be rebuilt. The current step is never dropped."""
        total = sum(e[3] for e in self.stack)
        while total > self.max_bytes:
            nxt = next((j for j in range(1, self.pos + 1)
                        if self.stack[j][0] == "full"), None)
            if nxt is None:
                return          # only markup steps since the base: small
            total -= sum(e[3] for e in self.stack[:nxt])
            del self.stack[:nxt]
            self.pos -= nxt

    def state_bytes(self, i):
        """The whole document as it was after step `i`."""
        j = max(n for n in range(i + 1) if self.stack[n][0] == "full")
        data = self.stack[j][1]
        if j == i:
            return data
        doc = fitz.open(stream=data, filetype="pdf")
        for e in self.stack[j + 1:i + 1]:
            if e[0] == "full":                       # not reached
                doc = fitz.open(stream=e[1], filetype="pdf")
            else:
                for st in e[2].values():
                    restore_page(doc, st)
        out = doc.tobytes()
        doc.close()
        return out

    # ---- undo / redo -----------------------------------------------------------------
    def can_undo(self):
        return self.pos > 0

    def can_redo(self):
        return self.pos < len(self.stack) - 1

    def undo(self, doc=None):
        """Step back. Returns bytes to reload, or (for markup steps, done
        in place on `doc`) the set of page numbers that changed."""
        self._after = None
        if self.pos <= 0:
            return None
        e = self.stack[self.pos]
        if e[0] == "pages" and doc is not None:
            for st in e[1].values():
                restore_page(doc, st)
            self.pos -= 1
            return set(e[1])
        self.pos -= 1
        return self.state_bytes(self.pos)

    def redo(self, doc=None):
        self._after = None
        if self.pos >= len(self.stack) - 1:
            return None
        self.pos += 1
        e = self.stack[self.pos]
        if e[0] == "pages" and doc is not None:
            for st in e[2].values():
                restore_page(doc, st)
            return set(e[2])
        return self.state_bytes(self.pos)


# ======================================================================
# One undo list for points and document steps (was undo_boost.py;
# folded Nov 4, 1.1.1)
#
# One undo list for everything (v13).
#
# Ctrl+Z while a length/area is being drawn removes the last point, one at a
# time (Ctrl+Y puts it back); once no points are left, Ctrl+Z undoes the
# last document step as before. `history_rows` lists the whole list - points
# in progress first, then document steps newest first - and `go_back`
# steps back to any row. Wire with `history.install(win)` once after the
# menus are built (main_window.py), or call `undo`/`redo` from
# MainWindow.undo/redo.


_REDO = "_ub_point_redo"


def _view(win):
    return getattr(win, "_view", None)


def _redo_stack(v):
    st = getattr(v, _REDO, None)
    if st is None or st[0] is not v._pts:
        st = (v._pts, [])            # new drawing: point redo starts empty
        setattr(v, _REDO, st)
    return st[1]


def undo(win, doc_undo):
    v = _view(win)
    if v is not None and getattr(v, "_pts", None):
        red = _redo_stack(v)
        red.append(v._pts.pop())
        setattr(v, "_ub_len", len(v._pts))
        v.update()
        return "point"
    doc_undo()
    return "doc"


def redo(win, doc_redo):
    v = _view(win)
    if v is not None and getattr(v, "_pts", None) is not None:
        st = getattr(v, _REDO, None)
        if st and st[0] is v._pts and st[1] and \
                getattr(v, "_ub_len", -1) == len(v._pts):
            v._pts.append(st[1].pop())
            v._ub_len = len(v._pts)
            v.update()
            return "point"
        if v._pts:
            return None              # drawing: don't redo the document
    doc_redo()
    return "doc"


def history_rows(win):
    """[{kind, label, current, index}] newest first. kind is "points"
    (the drawing in progress) or the history step kind."""
    v = _view(win)
    rows = []
    if v is None:
        return rows
    n = len(getattr(v, "_pts", None) or [])
    if n:
        rows.append({"kind": "points", "index": None, "current": True,
                     "label": f"{n} point{'s' if n != 1 else ''} being drawn"})
    h = v.history
    for i in range(len(h.stack) - 1, -1, -1):
        e = h.stack[i]
        if i == 0:
            label = "Opened"
        elif getattr(e, "label", None):
            label = e.label
        elif e[0] == "pages":
            pages = sorted(e[2]) if isinstance(e[2], dict) else []
            label = "Markup edit, page " + ", ".join(
                str(p + 1) for p in pages[:6]) if pages else "Markup edit"
        else:
            label = "Document edit"
        state = "" if i <= h.pos else " (undone)"
        rows.append({"kind": e[0], "index": i, "label": label + state,
                     "current": i == h.pos})
    return rows


def go_back(win, steps):
    """Undo `steps` document steps; points in progress are dropped first."""
    v = _view(win)
    if v is None:
        return
    if v._pts:
        v._pts = []
        v.update()
    for _ in range(int(steps)):
        if not win._view.history.can_undo():
            break
        win._ub_doc_undo()


try:
    from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QListWidget,
                                   QListWidgetItem, QVBoxLayout)
except ImportError:                    # history works without Qt
    QDialog = object


class UndoListDialog(QDialog):
    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.setWindowTitle("Undo History")
        lay = QVBoxLayout(self)
        self.list = QListWidget()
        lay.addWidget(self.list)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        b = bb.addButton("Go Back to Here", QDialogButtonBox.ActionRole)
        b.clicked.connect(self.back_to_selected)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.fill()

    def fill(self):
        self.list.clear()
        for r in history_rows(self.win):
            it = QListWidgetItem(("▶ " if r["current"] else "   ") +
                                 r["label"])
            it.setData(256, r["index"])
            self.list.addItem(it)

    def back_to_selected(self):
        it = self.list.currentItem()
        if it is None or it.data(256) is None:
            return
        go_back(self.win, max(0, self.win._view.history.pos - it.data(256)))
        self.fill()


def install(win):
    """Route Undo/Redo (menu, ribbon, Ctrl+Z/Ctrl+Y) through the one list
    and add Edit > Undo History…"""
    if getattr(win, "_ub_installed", False):
        return
    from PySide6.QtGui import QAction
    doc_undo, doc_redo = win.undo, win.redo
    win._ub_doc_undo = doc_undo
    win.undo = lambda: undo(win, doc_undo)
    win.redo = lambda: redo(win, doc_redo)
    for a in win.findChildren(QAction):
        if a.text() in ("Undo", "Redo"):
            try:
                a.triggered.disconnect()
            except (RuntimeError, TypeError):
                pass
            fn = win.undo if a.text() == "Undo" else win.redo
            a.triggered.connect(lambda _c=False, f=fn: f())
    act = QAction("Undo History…", win)
    act.triggered.connect(lambda _c=False: UndoListDialog(win).exec())
    win.addAction(act)
    win._ub_history_action = act
    win._ub_installed = True
