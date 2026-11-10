"""Editors for Project Center fields, one per field type in schema.py.

Every editor has ``value()``, ``set_value(v)`` and a ``changed`` signal,
so the record form can build itself from the schema and auto-save.
"""
import logging
import os
import re
from datetime import date, datetime

from PySide6.QtCore import QDate, QSize, Qt, QTimer, Signal, QUrl
from PySide6.QtGui import QDesktopServices, QIcon, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QCalendarWidget,
                               QComboBox, QCompleter, QFileDialog,
                               QFrame, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem,
                               QMenu, QPlainTextEdit, QPushButton,
                               QStyledItemDelegate, QTableWidget,
                               QTableWidgetItem, QToolButton, QVBoxLayout,
                               QWidget)

from .. import dmoney, icons, theme
from . import schema
from ..dmoney import c2 as _c2
from ..dmoney import _dec


# ---------------------------------------------------------------- dates
def parse_date(text):
    """'2026-10-15', '10/15/26', '10/15/2026', '10-15' -> ISO, '' if
    blank, None if unreadable."""
    t = (text or "").strip()
    if not t:
        return ""
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y", "%m-%d-%y",
                "%b %d %Y", "%b %d, %Y", "%d %b %Y"):
        try:
            return datetime.strptime(t, fmt).date().isoformat()
        except ValueError:
            pass
    for fmt in ("%m/%d", "%m-%d"):
        try:
            # parse with this year (a bare "2/29" is invalid in 1900)
            return datetime.strptime(f"{t}/{date.today().year}",
                                     fmt + "/%Y").date().isoformat()
        except ValueError:
            pass
    low = t.lower()
    if low in ("today", "t"):
        return date.today().isoformat()
    if low.startswith("+") and low[1:].isdigit():
        return schema.workdays_from(date.today(), int(low[1:])).isoformat()
    return None


def show_date(iso):
    """ISO -> 'Oct 15, 2026' for display."""
    if not iso:
        return ""
    try:
        d = date.fromisoformat(iso[:10])
    except ValueError:
        return iso
    return f"{d:%b} {d.day}, {d.year}"


class DateEdit(QWidget):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(4)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("mm/dd/yyyy, today, +5")
        self.edit.editingFinished.connect(self._done)
        h.addWidget(self.edit, 1)
        b = QToolButton()
        b.setIcon(icons.icon("calendar"))
        b.setAutoRaise(True)
        b.setToolTip("Pick a date")
        b.clicked.connect(self._pick)
        h.addWidget(b)
        self._iso = ""

    def _done(self):
        iso = parse_date(self.edit.text())
        if iso is None:
            self.edit.setStyleSheet(f"border:1px solid "
                                    f"{theme.color('danger').name()}")
            return
        self.edit.setStyleSheet("")
        if iso != self._iso:
            self._iso = iso
            self.edit.setText(show_date(iso))
            self.changed.emit()
        else:
            self.edit.setText(show_date(iso))

    def _pick(self):
        cal = QCalendarWidget()
        cal.setWindowFlags(Qt.Popup)
        if self._iso:
            d = date.fromisoformat(self._iso)
            cal.setSelectedDate(QDate(d.year, d.month, d.day))
        cal.clicked.connect(lambda qd: (self.set_value(
            qd.toString("yyyy-MM-dd")), self.changed.emit(), cal.close()))
        cal.move(self.mapToGlobal(self.rect().bottomLeft()))
        cal.resize(300, 220)
        cal.show()
        self._cal = cal

    def value(self):
        return self._iso

    def set_value(self, v):
        self._iso = v or ""
        self.edit.setText(show_date(self._iso))


class TextEdit(QLineEdit):
    changed = Signal()

    def __init__(self, parent=None, completions=None):
        super().__init__(parent)
        self.editingFinished.connect(self._done)
        self._last = ""
        if completions:
            c = QCompleter(completions, self)
            c.setCaseSensitivity(Qt.CaseInsensitive)
            c.setFilterMode(Qt.MatchContains)
            self.setCompleter(c)

    def _done(self):
        if self.text() != self._last:
            self._last = self.text()
            self.changed.emit()

    def value(self):
        return self.text().strip()

    def set_value(self, v):
        self._last = "" if v is None else str(v)
        self.setText(self._last)


# digits, with commas only as thousands separators; a leading - or (...)
_NUMBER = re.compile(r"^-?(?:\d+|\d{1,3}(?:,\d{3})+)?(?:\.\d*)?$")
MAX_NUMBER = 1e12              # a trillion: more is a typing mistake
NUMBER_HELP = ("Type a number such as 1,250.50 - digits, an optional "
               "decimal point, commas only between thousands, and no more "
               "than 1,000,000,000,000.")


def read_number(text):
    """The number typed in a field, or None when it isn't one. Refused
    rather than guessed at (Chief's round 7, Nov 9): nan, inf and 1e400;
    more than a trillion; "1.000,50" (it was read as 1.00) and "1,2,3"
    (it was read as 123)."""
    t = str(text or "").replace("$", "").strip()
    if not t:
        return None
    if t.startswith("(") and t.endswith(")"):
        t = "-" + t[1:-1].strip()
    if not _NUMBER.match(t) or not any(ch.isdigit() for ch in t):
        return None
    v = float(t.replace(",", ""))
    if v != v or abs(v) > MAX_NUMBER:
        return None
    return v


def number_text(v):
    """A number for a lines table: thousands separators, no cents on a
    whole number, two decimals otherwise - more (up to four) only when
    the number has them, so a row of 0.125 and its total 0.375 agree."""
    d = _dec(round(float(v), 6))
    if d == d.to_integral_value():
        return f"{int(d):,}"
    places = max(2, min(4, -d.normalize().as_tuple().exponent))
    return f"{d:,.{places}f}"


class NumberEdit(TextEdit):
    def __init__(self, parent=None, money=False):
        super().__init__(parent)
        self.money = money
        self.setAlignment(Qt.AlignRight)
        self.setPlaceholderText("$0.00" if money else "0")

    def value(self):
        v = read_number(self.text())
        if v is None:
            return None
        return _c2(v) if self.money else (int(v) if v == int(v) else v)

    def set_value(self, v):
        if v in (None, ""):
            super().set_value("")
        elif self.money:
            super().set_value(f"{_c2(float(v)):,.2f}")    # half up
        else:
            super().set_value(f"{v:g}" if isinstance(v, float) else str(v))

    def _done(self):
        v = self.value()
        if self.text().strip() and v is None:
            self.setStyleSheet(f"border:1px solid {theme.color('danger').name()}")
            self.setToolTip(NUMBER_HELP)
            return
        self.setStyleSheet("")
        self.setToolTip("")
        self.set_value(v)
        super()._done()


class LongEdit(QPlainTextEdit):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTabChangesFocus(True)
        self.setMinimumHeight(70)
        self._last = ""
        self.textChanged.connect(self._grow)

    def _grow(self):
        h = int(self.document().size().height() *
                self.fontMetrics().lineSpacing()) + 16
        self.setFixedHeight(max(70, min(260, h)))

    def focusOutEvent(self, e):
        super().focusOutEvent(e)
        if self.toPlainText() != self._last:
            self._last = self.toPlainText()
            self.changed.emit()

    def value(self):
        return self.toPlainText().strip()

    def set_value(self, v):
        self._last = v or ""
        self.setPlainText(self._last)


class ChoiceEdit(QComboBox):
    changed = Signal()

    def __init__(self, options, parent=None, editable=False):
        super().__init__(parent)
        self.setEditable(editable)
        self.addItems([o for o in options])
        self.currentTextChanged.connect(lambda _t: self.changed.emit())
        if editable:
            c = self.completer()
            if c:
                c.setFilterMode(Qt.MatchContains)
                c.setCompletionMode(QCompleter.PopupCompletion)

    def value(self):
        return self.currentText().strip()

    def set_value(self, v):
        self.blockSignals(True)
        v = "" if v is None else str(v)
        i = self.findText(v)
        if i < 0 and v:
            self.addItem(v)
            i = self.count() - 1
        self.setCurrentIndex(max(i, 0) if v or self.findText("") < 0
                             else self.findText(""))
        if self.isEditable():
            self.setEditText(v)
        self.blockSignals(False)


class PersonEdit(ChoiceEdit):
    """A directory name (or an email typed in)."""

    def __init__(self, store, parent=None):
        names = [""] + sorted({p["name"] for p in store.people()
                               if p["name"]} |
                              {d.get("name", "") for d in
                               store.list("distlist")} - {""})
        super().__init__(names, parent, editable=True)
        self.lineEdit().setPlaceholderText("Name or email")
        self.lineEdit().editingFinished.connect(self.changed.emit)


class PeopleEdit(TextEdit):
    """Several people: 'Name; Name; email@x.com'. Completes each name."""

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.names = sorted({p["name"] for p in store.people()
                             if p["name"]} | {d.get("name", "") for d in
                                              store.list("distlist")} -
                            {""})
        self.setPlaceholderText("Names, lists or emails, separated by ;")
        self._comp = QCompleter(self.names, self)
        self._comp.setCaseSensitivity(Qt.CaseInsensitive)
        self._comp.setFilterMode(Qt.MatchContains)
        self._comp.setWidget(self)
        self._comp.activated.connect(self._insert)
        self.textEdited.connect(self._complete)

    def _complete(self, text):
        part = text.split(";")[-1].strip()
        if len(part) >= 1:
            self._comp.setCompletionPrefix(part)
            self._comp.complete()

    def _insert(self, name):
        parts = [p.strip() for p in self.text().split(";")][:-1]
        self.setText("; ".join(parts + [name]) + "; ")

    def value(self):
        return [p.strip() for p in self.text().split(";") if p.strip()]

    def set_value(self, v):
        if isinstance(v, str):
            v = [v] if v else []
        super().set_value("; ".join(v or []))


class RefEdit(ChoiceEdit):
    """Another record, shown as 'RFI-003  Footing depth'."""

    def __init__(self, store, ref, parent=None):
        self.store, self.ref = store, ref
        t = schema.TOOLS.get(ref, {})
        self.ids = [""]
        labels = [""]
        for r in store.list(ref):
            self.ids.append(r["_id"])
            labels.append(f"{r.get('_no', '')}  "
                          f"{r.get(t.get('title_field', 'title'), '')}")
        super().__init__(labels, parent)

    def value(self):
        i = self.currentIndex()
        return self.ids[i] if 0 <= i < len(self.ids) else ""

    def set_value(self, v):
        self.blockSignals(True)
        self.setCurrentIndex(self.ids.index(v) if v in self.ids else 0)
        self.blockSignals(False)


# ---------------------------------------------------------------- tables
class _ComboDelegate(QStyledItemDelegate):
    def __init__(self, options, parent=None, editable=False):
        super().__init__(parent)
        self.options, self.editable = options, editable

    def createEditor(self, parent, opt, index):
        c = QComboBox(parent)
        c.setEditable(self.editable)
        c.addItems(self.options)
        return c

    def setEditorData(self, ed, index):
        v = index.data(Qt.EditRole) or ""
        i = ed.findText(v)
        if i >= 0:
            ed.setCurrentIndex(i)
        elif self.editable:
            ed.setEditText(v)

    def setModelData(self, ed, model, index):
        model.setData(index, ed.currentText(), Qt.EditRole)


class LinesEdit(QWidget):
    """A small table (manpower, review steps, agenda topics...)."""
    changed = Signal()

    def __init__(self, cols, store=None, parent=None):
        super().__init__(parent)
        self.cols = cols
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)
        self.table = QTableWidget(0, len(cols))
        self.table.setHorizontalHeaderLabels([c[1] for c in cols])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.AllEditTriggers)
        names = sorted({p["name"] for p in store.people()}) if store else []
        for i, c in enumerate(cols):
            if c[2] == "choice":
                self.table.setItemDelegateForColumn(
                    i, _ComboDelegate(list(c[3]), self.table))
            elif c[2] == "person":
                self.table.setItemDelegateForColumn(
                    i, _ComboDelegate([""] + names, self.table, True))
        self.table.itemChanged.connect(self._cell)
        self._orig = []
        v.addWidget(self.table)
        h = QHBoxLayout()
        add = QPushButton("Add row")
        add.setIcon(icons.icon("new"))
        add.clicked.connect(lambda _c=False: self.add_row())
        rm = QPushButton("Remove row")
        rm.clicked.connect(self.remove_row)
        h.addWidget(add)
        h.addWidget(rm)
        h.addStretch()
        self.total = QLabel("")
        self.total.setObjectName("muted")
        h.addWidget(self.total)
        v.addLayout(h)
        self._loading = False

    def _fit(self):
        n = self.table.rowCount()
        hh = self.table.horizontalHeader().height()
        rh = self.table.verticalHeader().defaultSectionSize()
        self.table.setFixedHeight(hh + rh * max(1, min(n, 12)) + 6)
        if any(c[2] == "number" for c in self.cols):
            from . import schema
            rows = [{c[0]: (self.table.item(r, i).text()
                            if self.table.item(r, i) else "")
                     for i, c in enumerate(self.cols)} for r in range(n)]
            parts = []
            for label, s, bad in schema.line_totals(self.cols, rows):
                if s or bad:               # shown, never a silent 0
                    txt = number_text(s)
                    parts.append(f"{label}: {txt}" +
                                 (f" ({bad} can't be read)" if bad else ""))
            self.total.setText("   ".join(parts))

    def _cell(self, _item):
        if not self._loading:
            self._fit()
            self.changed.emit()

    def add_row(self, values=None):
        self._loading = True
        r = self.table.rowCount()
        self.table.insertRow(r)
        self._orig.insert(r, dict(values or {}))
        for i, c in enumerate(self.cols):
            v = (values or {}).get(c[0], "")
            if c[2] == "date":
                v = show_date(v)
            elif c[2] == "number" and isinstance(v, (int, float)) and \
                    not isinstance(v, bool) and abs(v) >= 1000:
                v = number_text(v)
            self.table.setItem(r, i, QTableWidgetItem("" if v is None
                                                      else str(v)))
        self._loading = False
        self._fit()
        if values is None:
            self.table.setCurrentCell(r, 0)
            self.table.editItem(self.table.item(r, 0))
            self.changed.emit()

    def remove_row(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()},
                      reverse=True) or ([self.table.rowCount() - 1]
                                        if self.table.rowCount() else [])
        for r in rows:
            self.table.removeRow(r)
            if r < len(self._orig):
                del self._orig[r]
        self._fit()
        self.changed.emit()

    def value(self):
        out = []
        for r in range(self.table.rowCount()):
            # keep keys the table doesn't show (a bidder's link token...)
            row = dict(self._orig[r]) if r < len(self._orig) else {}
            for i, c in enumerate(self.cols):
                it = self.table.item(r, i)
                t = (it.text() if it else "").strip()
                if c[2] == "number":
                    try:
                        t = float(t.replace(",", "").replace("$", "")) \
                            if t else None
                        if t is not None and t == int(t):
                            t = int(t)
                    except ValueError:
                        t = None
                elif c[2] == "date":
                    t = parse_date(t) or ""
                row[c[0]] = t
            if any(row.get(c[0]) not in ("", None) for c in self.cols):
                out.append(row)
        return out

    def set_value(self, rows):
        self._loading = True
        self.table.setRowCount(0)
        self._orig = []
        self._loading = False
        for row in rows or []:
            self.add_row(row)
        self._fit()


# ---------------------------------------------------------------- files
IMAGE_EXT = (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp")


class AttachEdit(QWidget):
    changed = Signal()

    def __init__(self, store, parent=None, photos=False):
        super().__init__(parent)
        self.store = store
        self.refs = []
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        self.list = QListWidget()
        self.list.setViewMode(QListWidget.IconMode if photos else
                              QListWidget.ListMode)
        self.list.setIconSize(QSize(96, 72) if photos else QSize(16, 16))
        self.list.setResizeMode(QListWidget.Adjust)
        self.list.setFixedHeight(120 if photos else 84)
        self.list.itemDoubleClicked.connect(self._open)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._menu)
        v.addWidget(self.list)
        h = QHBoxLayout()
        b = QPushButton("Add photos…" if photos else "Attach files…")
        b.setIcon(icons.icon("photo" if photos else "attach"))
        b.clicked.connect(self._add)
        h.addWidget(b)
        h.addStretch()
        hint = QLabel("or drop files here")
        hint.setObjectName("muted")
        h.addWidget(hint)
        v.addLayout(h)
        self.setAcceptDrops(True)
        self.photos = photos

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        paths = [u.toLocalFile() for u in e.mimeData().urls()
                 if u.isLocalFile()]
        self.add_paths(paths)

    def _add(self):
        flt = "Images (*.jpg *.jpeg *.png *.gif *.bmp *.webp)" \
            if self.photos else "All files (*)"
        paths, _ = QFileDialog.getOpenFileNames(self, "Attach", "", flt)
        self.add_paths(paths)

    def add_paths(self, paths):
        """Copy the files in now; upload them in the background (a big
        photo set used to freeze the window, review 3 #5)."""
        queued = False
        for p in paths:
            if os.path.isfile(p):
                try:
                    ref = self.store.attach(p, defer=True)
                    queued = True
                except TypeError:            # a store without queueing
                    ref = self.store.attach(p)
                self.refs.append(ref)
        if paths:
            self._fill()
            self.changed.emit()
        if queued and getattr(self.store, "connected", False):
            from .. import bg
            bg.run(self.store.push_attachments, lambda _r: None,
                   lambda e: logging.getLogger(__name__).info(
                       "attachment upload deferred: %s", e),
                   self)

    def _fill(self):
        self.list.clear()
        for ref in self.refs:
            it = QListWidgetItem(ref["name"])
            it.setToolTip(f"{ref['name']}  ({ref.get('size', 0) // 1024} KB,"
                          f" {ref.get('by', '')})")
            icon = icons.icon("attach")
            if (ref.get("ext") or "").lower() in IMAGE_EXT:
                local = os.path.join(self.store.att_dir(),
                                     ref["sha256"] + ref.get("ext", ""))
                if os.path.exists(local):
                    pm = QPixmap(local)
                    if not pm.isNull():
                        icon = QIcon(pm.scaled(192, 144, Qt.KeepAspectRatio,
                                               Qt.SmoothTransformation))
            it.setIcon(icon)
            self.list.addItem(it)

    def _open(self, item):
        ref = self.refs[self.list.row(item)]
        try:
            path = self.store.attachment_path(ref)
        except Exception as e:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Attachment", str(e))
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _menu(self, pos):
        item = self.list.itemAt(pos)
        if item is None:
            return
        m = QMenu(self)
        m.addAction("Open", lambda: self._open(item))
        m.addAction("Remove", lambda: self._remove(self.list.row(item)))
        m.exec(self.list.mapToGlobal(pos))

    def _remove(self, i):
        del self.refs[i]
        self._fill()
        self.changed.emit()

    def value(self):
        return list(self.refs)

    def set_value(self, v):
        self.refs = list(v or [])
        self._fill()


class ThreadEdit(QWidget):
    """A discussion: earlier messages, then a reply box."""
    changed = Signal()

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.msgs = []
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        self.view = QLabel()
        self.view.setWordWrap(True)
        self.view.setTextFormat(Qt.RichText)
        self.view.setTextInteractionFlags(Qt.TextSelectableByMouse)
        v.addWidget(self.view)
        h = QHBoxLayout()
        self.box = QLineEdit()
        self.box.setPlaceholderText("Write a comment and press Enter")
        self.box.returnPressed.connect(self._post)
        h.addWidget(self.box, 1)
        b = QPushButton("Post")
        b.clicked.connect(self._post)
        h.addWidget(b)
        v.addLayout(h)

    def _post(self):
        t = self.box.text().strip()
        if not t:
            return
        self.msgs.append({"by": self.store.me,
                          "at": datetime.now().isoformat(timespec="minutes"),
                          "text": t})
        self.box.clear()
        self._fill()
        self.changed.emit()

    def _fill(self):
        import html
        if not self.msgs:
            self.view.setText(f"<span style='color:{theme.color('muted').name()}'>"
                              "No comments yet.</span>")
            return
        rows = []
        for m in self.msgs:
            when = m.get("at", "").replace("T", " ")
            rows.append(f"<p style='margin:2px 0 8px 0'><b>"
                        f"{html.escape(m.get('by', ''))}</b> "
                        f"<span style='color:{theme.color('muted').name()}'>"
                        f"{html.escape(when)}</span><br>"
                        f"{html.escape(m.get('text', ''))}</p>")
        self.view.setText("".join(rows))

    def value(self):
        return list(self.msgs)

    def set_value(self, v):
        self.msgs = list(v or [])
        self._fill()


class WeatherEdit(QWidget):
    """Daily log weather: high, low, rain, sky, wind - filled in with one
    click from Open-Meteo for the project's town."""
    changed = Signal()

    def __init__(self, store, date_getter=None, parent=None):
        super().__init__(parent)
        self.store = store
        self.date_getter = date_getter
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        self.f = {}
        for key, label, w in (("high", "High °F", 60), ("low", "Low °F", 60),
                              ("precip", "Rain in", 60),
                              ("sky", "Sky", 110), ("wind", "Wind mph", 60)):
            e = QLineEdit()
            e.setPlaceholderText(label)
            e.setToolTip(label)
            e.setFixedWidth(w if key != "sky" else 120)
            e.editingFinished.connect(self.changed.emit)
            self.f[key] = e
            h.addWidget(e)
        b = QPushButton("Get weather")
        b.setIcon(icons.icon("sun"))
        b.clicked.connect(self.fetch)
        h.addWidget(b)
        h.addStretch()

    def fetch(self):
        from PySide6.QtWidgets import QInputDialog, QMessageBox
        from . import weather
        place = self.store.setting("location") or ""
        if not place:
            place, ok = QInputDialog.getText(
                self, "Project location",
                "Town or address of the job site (for the weather):")
            if not ok or not place.strip():
                return
            self.store.set_setting("location", place.strip())
            place = place.strip()
        day = (self.date_getter() if self.date_getter else "") or \
            date.today().isoformat()
        # the web lookup runs in the background (review 3 #36)
        from .. import bg

        def done(w):
            self.set_value(w)
            self.changed.emit()
        bg.run(lambda: weather.daily(place, day), done,
               lambda msg: QMessageBox.warning(self, "Weather", msg), self)

    def value(self):
        return {k: e.text().strip() for k, e in self.f.items()
                if e.text().strip()}

    def set_value(self, v):
        v = v or {}
        if isinstance(v, str):
            v = {"sky": v}
        for k, e in self.f.items():
            e.setText(str(v.get(k, "")))


class TemplateEdit(ChoiceEdit):
    def __init__(self, parent=None):
        from .templates import INSPECTIONS
        super().__init__([""] + list(INSPECTIONS), parent)


class Pill(QWidget):
    """A rounded status label (painted, so no stylesheet can flatten it)."""

    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self._text = ""
        self.set_status(text)

    def set_status(self, text):
        self._text = text or ""
        kind = schema.STATUS_COLORS.get(self._text, "muted")
        self._fg = {"good": "ok", "bad": "danger", "warn": "warn",
                    "accent": "accent_text", "accent2": "accent_text",
                    "muted": "muted"}[kind]
        f = self.font()
        f.setBold(True)
        self.setFont(f)
        fm = self.fontMetrics()
        self.setFixedSize(fm.horizontalAdvance(self._text) + 22,
                          fm.height() + 6)
        self.setVisible(bool(self._text))
        self.update()

    def text(self):
        return self._text

    def paintEvent(self, e):
        from PySide6.QtGui import QColor, QPainter
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = QColor(theme.color(self._fg))
        bg = QColor(c)
        bg.setAlpha(38)
        r = self.rect().adjusted(0, 0, -1, -1)
        p.setPen(Qt.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        p.setPen(c)
        p.drawText(r, Qt.AlignCenter, self._text)


def editor_for(field, store, form=None):
    t = field["type"]
    if t == "long":
        return LongEdit()
    if t == "date":
        return DateEdit()
    if t in ("number", "money"):
        return NumberEdit(money=(t == "money"))
    if t == "choice":
        return ChoiceEdit(list(field.get("options") or []))
    if t == "person":
        return PersonEdit(store)
    if t == "people":
        return PeopleEdit(store)
    if t == "ref":
        return RefEdit(store, field["ref"])
    if t == "lines":
        return LinesEdit(field["cols"], store)
    if t == "attachments":
        return AttachEdit(store, photos=field["key"] == "photos")
    if t == "thread":
        return ThreadEdit(store)
    if t == "weather":
        return WeatherEdit(store, (lambda: form.current.get("date"))
                           if form else None)
    if t == "template":
        return TemplateEdit()
    if t == "csi":
        from .. import csi
        opts = list(store.setting("spec_sections") or []) + [
            f"{k} 00 00 {v}" for k, v in sorted(csi.DIVISIONS.items())]
        e = TextEdit(completions=opts)
        e.setPlaceholderText("e.g. 03 30 00")
        return e
    return TextEdit()
