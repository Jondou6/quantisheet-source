"""Scheduler: build a schedule like Microsoft Project, inside QuantiSheet,
with or without a drawing open.

An editable grid on the left (ID, activity, duration, start, finish,
predecessors, % done, responsible), the Gantt chart on the right, row for
row. Type an activity and press Enter for the next; durations like 5, 5d,
2w (0 = milestone); predecessors by row number - "3", "3,5", "4SS+2",
"6FF-1". Indent / Outdent make summary rows that span their activities.
Shift + drag from one bar to another links them. Ctrl+Z undoes.

The schedule lives in a project folder (the same "activity" records
Project Center, cash flow and the Gantt / lookahead PDFs use), so a
schedule built here is the project's schedule. A new schedule needs only
a name.
"""
import copy
import datetime as _dt
import logging
import os
import re

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QColor, QFont, QKeySequence
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox,
                               QComboBox,
                               QDialog, QDialogButtonBox, QFileDialog,
                               QFormLayout, QFrame, QHBoxLayout,
                               QHeaderView, QInputDialog, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMainWindow,
                               QMessageBox, QPushButton, QScrollArea,
                               QSplitter, QTableWidget, QTableWidgetItem,
                               QMenu, QToolBar, QToolButton, QVBoxLayout,
                               QWidget)

from .. import icons, settings
from ..reportname import report_file_name
from . import schedule
from .scheduleui import HEAD, ROW, SCALES, GanttChart
from ..dmoney import c2 as _c2

COLS = [("ID", 40), ("Activity", 260), ("Duration", 70), ("Start", 84),
        ("Finish", 84), ("Predecessors", 110), ("% Done", 60),
        ("Responsible", 110)]
C_ID, C_NAME, C_DUR, C_START, C_FIN, C_PRED, C_PCT, C_RESP = range(8)
EDITABLE = {C_NAME, C_DUR, C_START, C_FIN, C_PRED, C_PCT, C_RESP}
INDENT = "      "
_PRED = re.compile(r"^\s*(\d+)\s*(FS|SS|FF|SF)?\s*(?:([+-])\s*(\d+)\s*"
                   r"(?:d|days?)?)?\s*$", re.I)
DEFAULT_FOLDER = os.path.join(os.path.expanduser("~"), "Documents",
                              "QuantiSheet Schedules")


# ------------------------------------------------------------- parsing
def parse_duration(text):
    """'5', '5d', '5 days', '2w', '1.5w', '0' -> workdays (int), or None."""
    t = str(text or "").strip().lower()
    m = re.match(r"^(\d+(?:\.\d+)?)\s*(d|day|days|w|wk|wks|week|weeks|"
                 r"mo|month|months)?$", t)
    if not m:
        return None
    n = float(m.group(1))
    u = (m.group(2) or "d")[0]
    n *= 5 if u == "w" else 20 if u == "m" else 1
    return int(round(n))


def parse_date(text):
    t = str(text or "").strip()
    if not t:
        return None
    for fmt in ("%m/%d/%y", "%m/%d/%Y", "%Y-%m-%d", "%m-%d-%y", "%m-%d-%Y",
                "%b %d %Y", "%b %d, %Y"):
        try:
            return _dt.datetime.strptime(t, fmt).date()
        except ValueError:
            continue
    return None


def parse_preds(text, rows):
    """'3, 5SS+2' -> preds lines, row numbers counted from 1 in `rows`
    (outline order). Returns (lines, [bad tokens])."""
    out, bad = [], []
    for tok in re.split(r"[,;]+", str(text or "")):
        if not tok.strip():
            continue
        m = _PRED.match(tok)
        if not m:
            bad.append(tok.strip())
            continue
        i = int(m.group(1)) - 1
        if not 0 <= i < len(rows):
            bad.append(tok.strip())
            continue
        lag = int(m.group(4) or 0) * (-1 if m.group(3) == "-" else 1)
        out.append({"id": rows[i]["_no"], "type": (m.group(2) or "FS").upper(),
                    "lag": lag})
    return out, bad


def preds_text(rec, rows):
    """A record's predecessors written as row numbers ("3, 5SS+2")."""
    find = schedule.resolver(rows)
    pos = {r["_id"]: i + 1 for i, r in enumerate(rows)}
    parts = []
    for ref, t, lag in schedule.parse_preds(rec):
        rid = find(ref)
        n = pos.get(rid)
        if n is None:
            parts.append(ref)
            continue
        s = str(n) + ("" if t == "FS" and not lag else t)
        if lag:
            s += f"{'+' if lag > 0 else ''}{int(lag)}"
        parts.append(s)
    return ", ".join(parts)


# ------------------------------------------------------------- window
class Scheduler(QMainWindow):
    def __init__(self, store, main=None):
        super().__init__()
        self.store = store
        self.main = main
        self.setWindowTitle(f"Scheduler — {store.name}")
        self.resize(1500, 860)
        self.undo_stack, self.redo_stack = [], []
        self._filling = False
        self.order = []                     # outline rows (records)
        self.levels = {}
        self.cpm = {"rows": []}
        self._build()
        self.refresh()
        self._listener = lambda coll: coll in (None, "activity") and \
            QTimer.singleShot(0, self._external_change)
        store.listeners.append(self._listener)

    # ---------------------------------------------------------- layout
    def _build(self):
        tb = QToolBar("Schedule")
        tb.setMovable(False)
        self.addToolBar(tb)
        self.acts_by_name = {}

        def act(text, slot, key=None, icon=None, tip=None):
            a = QAction(text, self)
            if icon:
                a.setIcon(icons.icon(icon))
            if key:
                a.setShortcut(QKeySequence(key))
                a.setShortcutContext(Qt.WindowShortcut)
            a.setToolTip((tip or text) + (f" ({key})" if key else ""))
            a.triggered.connect(lambda _c=False: slot())
            tb.addAction(a)
            self.acts_by_name[text] = a
            return a
        act("New Schedule", self.new_schedule, icon="new")
        act("Open Schedule", self.open_schedule, icon="open")
        tb.addSeparator()
        act("Insert", self.insert_row, "Insert", "page_add",
            "Insert an activity above the selected one")
        act("Delete", self.delete_rows, None, "page_delete")
        act("Outdent", self.outdent, "Alt+Shift+Left", "page_prev")
        act("Indent", self.indent, "Alt+Shift+Right", "page_next",
            "Make it part of the summary above")
        act("Move Up", lambda: self.move_row(-1), "Ctrl+Up", None)
        act("Move Down", lambda: self.move_row(1), "Ctrl+Down", None)
        act("Link", self.link_selected, "Ctrl+F2", "link",
            "Link the selected activities in order (finish-to-start)")
        act("Unlink", self.unlink_selected, "Ctrl+Shift+F2", None)
        tb.addSeparator()
        act("Undo", self.undo, "Ctrl+Z", "undo")
        act("Redo", self.redo, "Ctrl+Y", "redo")
        tb.addSeparator()
        self.scale = QComboBox()
        self.scale.addItems(list(SCALES))
        self.scale.setCurrentText("Weeks")
        self.scale.currentTextChanged.connect(lambda _t: self.refresh())
        tb.addWidget(self.scale)
        self.crit = QCheckBox("Critical only")
        self.crit.toggled.connect(lambda _c: self.refresh())
        tb.addWidget(self.crit)
        act("Today", self.go_today, None, "calendar",
            "Scroll the chart to today")
        tb.addSeparator()
        act("Project Start", self.project_start, None, "calendar",
            "The day work can start (activities with nothing before them "
            "start here)")
        act("Holidays", self.holidays, None, None)
        act("Set Baseline", self.baseline, None, "history")
        tb.addSeparator()
        act("Import", self.import_file, None, "import",
            "Microsoft Project (XML) or Primavera P6 (XER)")
        act("Export MS Project", self.export, None, "export")
        act("Save PDF", self.pdf, None, "print",
            "The Gantt chart on 11x17 sheets")
        act("3-Week Lookahead", lambda: self.pdf(lookahead=True), None,
            None)
        act("Project Center", self.open_center, None, "home")
        # the claim record, here as well as on Project Center's Gantt
        # Chart page (Jon couldn't find it there, Oct 21)
        cl = QToolButton()
        cl.setText("Claims && Recovery")
        cl.setIcon(icons.icon("flag"))
        cl.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        cl.setPopupMode(QToolButton.InstantPopup)
        cl.setToolTip("Save a schedule update, the Delay Log, the recovery "
                      "schedule, the quality check and the claim package")
        m = QMenu(cl)
        for text, slot in (("Save Schedule Update…", self.save_update),
                           ("Delay Log", self.delay_log),
                           ("Recovery Schedule…", self.recovery),
                           (None, None),
                           ("Schedule Quality Check (PDF)…",
                            self.quality_check),
                           ("Claim Package (PDF)…", self.claim_package)):
            if text is None:
                m.addSeparator()
                continue
            a = m.addAction(text)
            a.triggered.connect(lambda _c=False, f=slot: f())
            self.acts_by_name[text] = a
        cl.setMenu(m)
        tb.addWidget(cl)
        self.claims_button = cl
        tb.addSeparator()
        act("Build Schedule From Plans", lambda: self.build_from_plans(), None,
            "gantt", "Read the drawing set and spec book: contract time, "
            "scope and size, then draft the schedule")

        body = QWidget()
        v = QVBoxLayout(body)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        self.summary = QLabel()
        self.summary.setObjectName("muted")
        self.summary.setContentsMargins(12, 6, 12, 6)
        v.addWidget(self.summary)
        self.note = QLabel()
        self.note.setWordWrap(True)
        self.note.setStyleSheet("color:#c62828")
        self.note.setContentsMargins(12, 0, 12, 6)
        self.note.setVisible(False)
        v.addWidget(self.note)
        split = QSplitter(Qt.Horizontal)
        self.table = QTableWidget(0, len(COLS))
        self.table.setHorizontalHeaderLabels([c for c, _w in COLS])
        for i, (_c, w) in enumerate(COLS):
            self.table.setColumnWidth(i, w)
        self.table.horizontalHeader().setSectionResizeMode(
            C_NAME, QHeaderView.Stretch)
        self.table.horizontalHeader().setFixedHeight(HEAD)
        vh = self.table.verticalHeader()
        vh.setVisible(False)
        vh.setSectionResizeMode(QHeaderView.Fixed)
        vh.setDefaultSectionSize(ROW)
        vh.setMinimumSectionSize(ROW)
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.DoubleClicked |
                                   QAbstractItemView.EditKeyPressed |
                                   QAbstractItemView.AnyKeyPressed)
        self.table.itemChanged.connect(self._edited)
        self.table.itemSelectionChanged.connect(self._sel_changed)
        self.table.installEventFilter(self)
        split.addWidget(self.table)
        self.chart = GanttChart(table=False)
        self.chart.changed.connect(self._chart_changed)
        self.chart.linked.connect(self.link)
        self.chart.selected.connect(self._chart_selected)
        self.chart.opened.connect(self._open_record)
        self.scroll = QScrollArea()
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setWidget(self.chart)
        self.scroll.setWidgetResizable(False)
        split.addWidget(self.scroll)
        split.setSizes([760, 740])
        v.addWidget(split, 1)
        tip = QLabel("Enter = next activity  ·  Insert = add above  ·  "
                     "Alt+Shift+→ / ← = indent / outdent  ·  Ctrl+F2 = link "
                     "selected  ·  Shift+drag bar to bar = link  ·  drag a "
                     "bar to move it, its end to change the duration  ·  "
                     "Predecessors: 3, 5SS+2, 6FF-1")
        tip.setObjectName("muted")
        tip.setContentsMargins(12, 4, 12, 4)
        v.addWidget(tip)
        self.setCentralWidget(body)
        # one vertical scroll for both sides
        self.table.verticalScrollBar().valueChanged.connect(
            self.scroll.verticalScrollBar().setValue)
        self.scroll.verticalScrollBar().valueChanged.connect(
            self.table.verticalScrollBar().setValue)

    # ---------------------------------------------------------- data
    def acts(self):
        return self.store.list("activity")

    def refresh(self, keep_row=None):
        self.chart.px = SCALES.get(self.scale.currentText(), 9.0)
        acts = self.acts()
        # cached: re-run only when activities/holidays change (review 3 #7)
        self.cpm = schedule.cached(self.store) if acts else {"rows": [], "problems": [],
                                       "finish": None, "critical": []}
        byrow = {r["_id"]: r for r in self.cpm["rows"]}
        ol = schedule.outline(acts)
        self.order = [a for a, _l, _s in ol]
        self.levels = {a["_id"]: lvl for a, lvl, _s in ol}
        shown = [byrow[a["_id"]] for a in self.order if a["_id"] in byrow]
        if self.crit.isChecked():
            shown = [r for r in shown if r["critical"]]
        self.shown = shown
        self.chart.set_data(self.cpm, shown)
        self._fill(shown)
        rows = self.cpm["rows"]
        if rows:
            n = len([r for r in rows if not r.get("summary")])
            self.summary.setText(
                f"{self.store.name}  ·  {n} activities  ·  "
                f"{self.cpm['start']:%b %d, %Y} to "
                f"{self.cpm['finish']:%b %d, %Y}  ·  "
                f"{len(self.cpm['critical'])} critical")
        else:
            self.summary.setText(f"{self.store.name}  ·  type the first "
                                 "activity below")
        probs = self.cpm.get("problems") or []
        self.note.setVisible(bool(probs))
        self.note.setText("  ".join(probs[:4]))
        self._seen = self.store.version
        if keep_row is not None and self.table.rowCount():
            self.table.setCurrentCell(min(keep_row, self.table.rowCount()
                                          - 1), C_NAME)
        self.undo_act_state()

    def undo_act_state(self):
        self.acts_by_name["Undo"].setEnabled(bool(self.undo_stack))
        self.acts_by_name["Redo"].setEnabled(bool(self.redo_stack))

    def _fill(self, shown):
        self._filling = True
        try:
            t = self.table
            t.setRowCount(len(shown) + 1)          # + the blank "new" row
            bold = QFont(t.font())
            bold.setBold(True)
            pos = {a["_id"]: k + 1 for k, a in enumerate(self.order)}
            for i, r in enumerate(shown):
                lvl = self.levels.get(r["_id"], 0)
                summ = bool(r.get("summary"))
                pt = preds_text(r, self.order)
                vals = [str(pos.get(r["_id"], "")),
                        INDENT * lvl + str(r.get("name") or ""),
                        "" if summ else (f"{r['dur']}d" if r["dur"] else
                                         "0d (milestone)"),
                        f"{r['es']:%m/%d/%y}", f"{r['ef']:%m/%d/%y}",
                        "" if summ else pt,
                        f"{schedule._num(r.get('percent')):g}%",
                        str(r.get("responsible") or "")]
                for c, val in enumerate(vals):
                    it = QTableWidgetItem(val)
                    it.setData(Qt.UserRole, r["_id"])
                    ro = c not in EDITABLE or (summ and c in (C_DUR, C_FIN,
                                                              C_PRED, C_PCT))
                    if ro:
                        it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                    if summ:
                        it.setFont(bold)
                    if r["critical"] and c == C_NAME and not summ:
                        it.setForeground(QColor("#d32f2f"))
                    if c == C_DUR and r.get("basis") and not summ:
                        # how Build From Plans sized it (quantity / rate)
                        it.setToolTip("Basis: " + str(r["basis"]))
                    if c == C_START and r.get("start") and not summ:
                        it.setToolTip("Start no earlier than "
                                      f"{r['start']} (clear it to let the "
                                      "links decide)")
                    t.setItem(i, c, it)
            n = len(shown)
            for c in range(len(COLS)):
                it = QTableWidgetItem("")
                it.setData(Qt.UserRole, None)
                if c != C_NAME:
                    it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                t.setItem(n, c, it)
            t.item(n, C_NAME).setToolTip("Type a new activity here")
        finally:
            self._filling = False

    def row_id(self, row):
        it = self.table.item(row, 0)
        return it.data(Qt.UserRole) if it is not None else None

    def selected_ids(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        return [rid for rid in (self.row_id(r) for r in rows) if rid]

    # ---------------------------------------------------------- undo
    def _snap(self):
        return copy.deepcopy(self.store.coll("activity")), \
            copy.deepcopy(self.store.data["settings"].get("project_start"))

    def checkpoint(self):
        self.undo_stack.append(self._snap())
        del self.undo_stack[:-100]
        self.redo_stack.clear()

    def _restore(self, snap):
        coll, ps = snap
        cur = self.store.coll("activity")
        with self.store.lock:
            for rid in set(cur) | set(coll):
                old, new = cur.get(rid), coll.get(rid)
                if old == new:
                    continue
                if new is None:                 # created since: delete it
                    old["_deleted"] = True
                    old["_dirty"] = True
                    self.store._queue("activity", rid, [], old.get("_rev"),
                                      delete=True)
                    continue
                rec = copy.deepcopy(new)
                rec["_dirty"] = True
                cur[rid] = rec
                fields = [k for k in set(rec) | set(old or {})
                          if not k.startswith("_")]
                self.store._queue("activity", rid, fields,
                                  (old or {}).get("_rev"),
                                  delete=bool(rec.get("_deleted")))
            if ps is None:
                self.store.data["settings"].pop("project_start", None)
            else:
                self.store.data["settings"]["project_start"] = ps
            self.store.save()
        self.store._changed("activity")

    def undo(self):
        if not self.undo_stack:
            return False
        self.redo_stack.append(self._snap())
        self._restore(self.undo_stack.pop())
        self.refresh()
        return True

    def redo(self):
        if not self.redo_stack:
            return False
        self.undo_stack.append(self._snap())
        self._restore(self.redo_stack.pop())
        self.refresh()
        return True

    def save(self, rec):
        return self.store.save_record("activity", rec)

    def _external_change(self):
        """Someone changed the schedule elsewhere (Project Center, a
        teammate's sync): show it. Our own edits are already shown."""
        if getattr(self, "_seen", None) == self.store.version:
            return
        try:
            self.refresh(keep_row=self.table.currentRow())
        except RuntimeError:
            pass                            # window already closed

    # ---------------------------------------------------------- editing
    def _sibs(self, parent):
        """The rows under `parent` (None = top level) in order, read from
        the store (not the last refresh: several can be added at once)."""
        acts = self.acts()
        ids = {a["_id"] for a in acts}
        par = parent if parent in ids else None
        return sorted([a for a in acts if ((a.get("parent") if
                                            a.get("parent") in ids else None)
                                           == par)], key=schedule._seq)

    def _renumber(self, parent):
        """Give the rows under `parent` the positions 1, 2, 3... (so there's
        always room to insert between two of them)."""
        for k, a in enumerate(self._sibs(parent)):
            if schedule._num(a.get("seq"), None) != float(k + 1):
                a["seq"] = float(k + 1)
                self.save(a)

    def _gap(self, parent, before_id):
        """A position just before `before_id` among `parent`'s rows."""
        sibs = self._sibs(parent)
        k = next((i for i, x in enumerate(sibs) if x["_id"] == before_id),
                 None)
        if k is None:
            return self._next_seq(parent)
        hi = schedule._seq(sibs[k])[0]
        lo = schedule._seq(sibs[k - 1])[0] if k > 0 else hi - 2
        if hi - lo < 1e-6:
            self._renumber(parent)
            return self._gap(parent, before_id)
        return (lo + hi) / 2

    def _next_seq(self, parent):
        s = self._sibs(parent)
        return (schedule._seq(s[-1])[0] + 1) if s else 1.0

    def add_activity(self, name, duration=5, after=None, parent=None,
                     **fields):
        """A new activity at the end of `parent` (or right after `after`,
        same level). Returns the record."""
        if after is not None:
            a = self.store.get("activity", after)
            parent = a.get("parent") if a else parent
            sibs = self._sibs(parent)
            k = next((i for i, x in enumerate(sibs) if x["_id"] == after), -1)
            seq = self._gap(parent, sibs[k + 1]["_id"]) \
                if 0 <= k < len(sibs) - 1 else self._next_seq(parent)
        else:
            seq = self._next_seq(parent)
        rec = dict(name=name, duration=duration, seq=seq,
                   status="Not Started", **fields)
        if parent:
            rec["parent"] = parent
        self._saving = True
        try:
            return self.save(rec)
        finally:
            self._saving = False

    def _edited(self, it):
        if self._filling:
            return
        r, c = it.row(), it.column()
        rid = it.data(Qt.UserRole)
        text = it.text()
        if rid is None:                          # the blank "new" row
            name = text.strip()
            if c != C_NAME or not name:
                return
            self.checkpoint()
            last = self.order[-1] if self.order else None
            parent = last.get("parent") if last else None
            self.add_activity(name, 5, parent=parent)
            self.refresh(keep_row=r + 1)
            return
        rec = self.store.get("activity", rid)
        if rec is None:
            return
        msg = self.apply_edit(rec, c, text)
        if msg:
            QMessageBox.information(self, "Scheduler", msg)
        self.refresh(keep_row=r)

    def apply_edit(self, rec, col, text):
        """Change one cell. Returns a message when the text was refused."""
        text = str(text or "")
        if col == C_NAME:
            name = text.strip()
            if not name:
                return "An activity needs a name (Delete removes it)."
            new = {"name": name}
        elif col == C_DUR:
            n = parse_duration(text)
            if n is None:
                return f"Not a duration: {text!r} (try 5, 5d or 2w)."
            new = {"duration": n}
        elif col == C_START:
            if not text.strip():
                new = {"start": ""}
            else:
                d = parse_date(text)
                if d is None:
                    return f"Not a date: {text!r} (try 11/02/26)."
                new = {"start": d.isoformat()}
        elif col == C_FIN:
            d = parse_date(text)
            row = next((x for x in self.cpm["rows"] if x["_id"] ==
                        rec["_id"]), None)
            if d is None or row is None:
                return f"Not a date: {text!r} (try 11/20/26)."
            cal = self.cpm["cal"]
            if d < row["es"]:
                return "The finish can't be before the start."
            new = {"duration": cal.index(d) - cal.index(row["es"]) + 1}
        elif col == C_PRED:
            lines, bad = parse_preds(text, self.order)
            if bad:
                return ("Predecessors are row numbers, with an optional "
                        "type and lag: 3, 5SS+2, 6FF-1. Couldn't use: " +
                        ", ".join(bad))
            lines = [x for x in lines if x["id"] != rec.get("_no")]
            new = {"preds": lines}
        elif col == C_PCT:
            t = text.strip().rstrip("%")
            try:
                pc = max(0.0, min(100.0, float(t or 0)))
            except ValueError:
                return f"Not a percent: {text!r}."
            new = {"percent": pc, "status": "Complete" if pc >= 100 else
                   "In Progress" if pc > 0 else "Not Started"}
            if pc > 0 and not rec.get("actual_start"):
                row = next((x for x in self.cpm["rows"]
                            if x["_id"] == rec["_id"]), None)
                if row:
                    new["actual_start"] = row["es"].isoformat()
            if pc >= 100 and not rec.get("actual_finish"):
                new["actual_finish"] = _dt.date.today().isoformat()
        elif col == C_RESP:
            new = {"responsible": text.strip()}
        else:
            return None
        if all(rec.get(k) == v for k, v in new.items()):
            return None
        self.checkpoint()
        rec.update(new)
        self._saving = True
        try:
            self.save(rec)
        finally:
            self._saving = False
        return None

    def _chart_changed(self, rid, fields):
        rec = self.store.get("activity", rid)
        if not rec:
            return
        self.checkpoint()
        rec.update(fields)
        self.save(rec)
        self.refresh()

    def link(self, pred_id, succ_id, typ="FS", lag=0):
        """`succ` can't start until `pred` finishes (or by `typ`)."""
        a = self.store.get("activity", succ_id)
        p = self.store.get("activity", pred_id)
        if not a or not p or a["_id"] == p["_id"]:
            return False
        lines = list(a.get("preds") or [])
        if any(str(x.get("id")) == p["_no"] for x in lines):
            return False
        self.checkpoint()
        lines.append({"id": p["_no"], "type": typ, "lag": lag})
        a["preds"] = lines
        self.save(a)
        self.refresh()
        return True

    def link_selected(self):
        ids = self.selected_ids()
        if len(ids) < 2:
            return 0
        self.checkpoint()
        n = 0
        for a_id, b_id in zip(ids, ids[1:]):
            p, a = self.store.get("activity", a_id), \
                self.store.get("activity", b_id)
            lines = list(a.get("preds") or [])
            if not any(str(x.get("id")) == p["_no"] for x in lines):
                lines.append({"id": p["_no"], "type": "FS", "lag": 0})
                a["preds"] = lines
                self.save(a)
                n += 1
        self.refresh()
        return n

    def unlink_selected(self):
        ids = self.selected_ids()
        recs = [self.store.get("activity", i) for i in ids]
        nos = {r["_no"] for r in recs}
        self.checkpoint()
        n = 0
        for r in recs:
            keep = [x for x in r.get("preds") or []
                    if str(x.get("id")) not in nos]
            if len(ids) == 1:
                keep = []                   # one row: clear all its links
            if keep != (r.get("preds") or []):
                r["preds"] = keep
                self.save(r)
                n += 1
        self.refresh()
        return n

    def insert_row(self, name="New activity"):
        sel = self.selected_ids()
        r = self.table.currentRow()
        rid = sel[0] if sel else (self.row_id(r) if r >= 0 else None)
        if sel:
            r = [x["_id"] for x in self.shown].index(sel[0])
        self.checkpoint()
        if rid is None:
            rec = self.add_activity(name)
        else:
            a = self.store.get("activity", rid)
            rec = self.save(dict(name=name, duration=5,
                                 seq=self._gap(a.get("parent"), rid),
                                 status="Not Started",
                                 **({"parent": a["parent"]}
                                    if a.get("parent") else {})))
        self.refresh(keep_row=max(0, r))
        return rec

    def delete_rows(self, ask=True):
        ids = self.selected_ids()
        if not ids:
            return 0
        summ = schedule.summaries(self.acts())
        all_ids = list(ids)
        for i in ids:
            all_ids += [k for k in summ.get(i, []) if k not in all_ids]
        if ask and len(all_ids) > 1 and QMessageBox.question(
                self, "Delete", f"Delete {len(all_ids)} activities"
                + (" (with the activities under the summary)" if
                   len(all_ids) > len(ids) else "") + "?") != \
                QMessageBox.Yes:
            return 0
        self.checkpoint()
        nos = set()
        for i in all_ids:
            rec = self.store.get("activity", i)
            if rec:
                nos.add(rec["_no"])
            self.store.delete("activity", i)
        # links to what was deleted go too
        for a in self.acts():
            keep = [x for x in a.get("preds") or []
                    if str(x.get("id")) not in nos]
            if keep != (a.get("preds") or []):
                a["preds"] = keep
                self.save(a)
        r = self.table.currentRow()
        self.refresh(keep_row=max(0, r))
        return len(all_ids)

    def indent(self):
        """The selected rows go under the activity above them (which
        becomes a summary)."""
        ids = self.selected_ids()
        if not ids:
            return 0
        first = next(a for a in self.order if a["_id"] == ids[0])
        sibs = self._sibs(first.get("parent"))
        k = next(i for i, x in enumerate(sibs) if x["_id"] == ids[0])
        if k == 0:
            return 0                       # nothing above at that level
        new_parent = sibs[k - 1]
        self.checkpoint()
        base = self._next_seq(new_parent["_id"])
        n = 0
        for j, rid in enumerate(ids):
            a = self.store.get("activity", rid)
            if (a.get("parent") or None) != (first.get("parent") or None):
                continue                   # only the same level moves
            a["parent"] = new_parent["_id"]
            a["seq"] = base + j
            self.save(a)
            n += 1
        p = self.store.get("activity", new_parent["_id"])
        if p.get("preds"):                 # a summary's own links aren't
            p["preds"] = []                # used
            self.save(p)
        self.refresh(keep_row=self.table.currentRow())
        return n

    def outdent(self):
        ids = self.selected_ids()
        n = 0
        self.checkpoint()
        for rid in reversed(ids):
            a = self.store.get("activity", rid)
            par = self.store.get("activity", a.get("parent")) \
                if a.get("parent") else None
            if par is None:
                continue
            a["parent"] = par.get("parent") or ""
            a["seq"] = schedule._seq(par)[0] + 0.5 / (n + 1)
            self.save(a)
            n += 1
        if not n:
            self.undo_stack.pop()
        self.refresh(keep_row=self.table.currentRow())
        return n

    def move_row(self, step):
        ids = self.selected_ids()
        if len(ids) != 1:
            return False
        a = next(x for x in self.order if x["_id"] == ids[0])
        sibs = self._sibs(a.get("parent"))
        k = next(i for i, x in enumerate(sibs) if x["_id"] == a["_id"])
        j = k + step
        if not 0 <= j < len(sibs):
            return False
        self.checkpoint()
        self._renumber(a.get("parent"))
        sibs = self._sibs(a.get("parent"))
        b = sibs[j]
        sa, sb = schedule._seq(sibs[k])[0], schedule._seq(b)[0]
        ra, rb = self.store.get("activity", a["_id"]), \
            self.store.get("activity", b["_id"])
        ra["seq"], rb["seq"] = sb, sa
        self.save(ra)
        self.save(rb)
        self.refresh()
        rows = [r["_id"] for r in self.shown]
        if a["_id"] in rows:
            self.table.selectRow(rows.index(a["_id"]))
        return True

    # ---------------------------------------------------------- keys
    def eventFilter(self, obj, ev):
        from PySide6.QtCore import QEvent
        if obj is self.table and ev.type() == QEvent.KeyPress:
            k = ev.key()
            if k == Qt.Key_Delete and self.table.state() != \
                    QAbstractItemView.EditingState:
                self.delete_rows()
                return True
            if k in (Qt.Key_Return, Qt.Key_Enter) and self.table.state() \
                    != QAbstractItemView.EditingState:
                r = self.table.currentRow()
                self.table.setCurrentCell(min(r + 1, self.table.rowCount()
                                              - 1), C_NAME)
                self.table.editItem(self.table.currentItem())
                return True
        return super().eventFilter(obj, ev)

    def _sel_changed(self):
        ids = self.selected_ids()
        self.chart.sel = ids[0] if ids else None
        self.chart.update()

    def _chart_selected(self, rid):
        rows = [r["_id"] for r in self.shown]
        if rid in rows:
            self.table.selectRow(rows.index(rid))

    def _open_record(self, rid):
        c = self.open_center()
        if c is not None:
            try:
                c.open_record("activity", rid)
            except Exception:
                pass

    # ---------------------------------------------------------- tools
    def go_today(self):
        x = self.chart.x(_dt.date.today())
        self.scroll.horizontalScrollBar().setValue(max(0, int(x) - 120))

    def project_start(self, date=None):
        if date is None:
            cur = self.store.setting("project_start") or \
                _dt.date.today().isoformat()
            text, ok = QInputDialog.getText(
                self, "Project Start", "Work can start on (MM/DD/YY):",
                text=_dt.date.fromisoformat(cur).strftime("%m/%d/%y"))
            if not ok:
                return None
            date = parse_date(text)
            if date is None:
                QMessageBox.information(self, "Project Start",
                                        f"Not a date: {text}")
                return None
        self.checkpoint()
        self.store.set_setting("project_start", date.isoformat())
        self.refresh()
        return date

    def holidays(self):
        cur = ", ".join(self.store.setting("holidays") or [])
        text, ok = QInputDialog.getMultiLineText(
            self, "Holidays", "Non-work days (YYYY-MM-DD or MM/DD/YY), "
            "separated by commas or lines:", cur)
        if not ok:
            return None
        days = set(re.findall(r"\d{4}-\d{2}-\d{2}", text))
        for m in re.findall(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b", text):
            d = parse_date(m)
            if d:
                days.add(d.isoformat())
        self.store.set_setting("holidays", sorted(days))
        self.refresh()
        return sorted(days)

    def baseline(self):
        try:
            n = schedule.set_baseline(self.store)
        except schedule.BaselineLocked as ex:       # Master Schedule lock
            self.last_baseline_message = str(ex)
            self.statusBar().showMessage(self.last_baseline_message, 12000)
            if not getattr(self, "_quiet", False):
                QMessageBox.information(self, "Set Baseline", str(ex))
            return 0
        try:                       # the baseline is part of the record
            from . import schedule_record
            schedule_record.snapshot(self.store, "baseline",
                                     f"Baseline set for {n} activities")
        except Exception as ex:                     # noqa: BLE001
            # the baseline itself is saved; say the record wasn't updated
            # (review 0.12.38 #10 - this used to be swallowed)
            logging.getLogger(__name__).exception(
                "Set Baseline: schedule record snapshot failed")
            self.last_baseline_message = (
                "Baseline saved, but the schedule record could not be "
                f"updated: {ex}")
            self.refresh()
            self.statusBar().showMessage(self.last_baseline_message, 12000)
            if not getattr(self, "_quiet", False):
                QMessageBox.warning(self, "Set Baseline",
                                    self.last_baseline_message)
            return n
        self.last_baseline_message = f"Baseline saved for {n} activities"
        self.refresh()
        self.statusBar().showMessage(self.last_baseline_message, 4000)
        return n

    def import_file(self, path=None):
        if path is None:
            path, _ = QFileDialog.getOpenFileName(
                self, "Import Schedule", "", "Schedules (*.xml *.xer);;"
                "Microsoft Project XML (*.xml);;Primavera P6 (*.xer)")
        if not path:
            return 0
        self.checkpoint()
        ver = self.store.version
        try:
            fn = schedule.import_xer if path.lower().endswith(".xer") \
                else schedule.import_msproject
            n = fn(self.store, path)
        except Exception as ex:
            partial = self.store.version != ver
            if not partial:
                self.undo_stack.pop()       # nothing changed
            else:
                self.refresh()              # keep the snapshot (3 #31)
            QMessageBox.warning(self, "Import Schedule",
                                f"Couldn't read that file: {ex}" +
                                ("\n\nPart of it was brought in; Ctrl+Z "
                                 "takes that back out." if partial else ""))
            return 0
        self.refresh()
        self.statusBar().showMessage(f"Imported {n} activities", 4000)
        return n

    def export(self, path=None):
        path = path or QFileDialog.getSaveFileName(
            self, "Export Schedule", f"{self.store.name}.xml",
            "Microsoft Project XML (*.xml)")[0]
        if not path:
            return None
        schedule.export_msproject(self.store, path)
        self.statusBar().showMessage(f"Exported {os.path.basename(path)}",
                                     4000)
        return path

    def pdf(self, lookahead=False, path=None):
        name = report_file_name("Lookahead" if lookahead else "Schedule",
                                self.store.name)
        path = path or QFileDialog.getSaveFileName(
            self, "Save PDF", os.path.join(self.store.folder, name),
            "PDF (*.pdf)")[0]
        if not path:
            return None
        if lookahead:
            schedule.lookahead_pdf(self.store, path)
        else:
            schedule.gantt_pdf(self.store, path, title=f"{self.store.name}"
                               " - Project Schedule")
        if self.main is not None and not os.environ.get("QUANTISHEET_NO_OPEN"):
            self.main.open_path(path)
        return path

    # ---------------------------------------------------------- claims
    def save_update(self, note=None):
        """A dated, fingerprinted copy of the schedule (schedule_record)."""
        from . import schedule_record
        if note is None:
            note, ok = QInputDialog.getText(
                self, "Save Schedule Update",
                "Note for this update (e.g. \"October update\"):")
            if not ok:
                return None
        e = schedule_record.snapshot(self.store, "update", note or "")
        self.statusBar().showMessage(f"Schedule update {e['n']} saved", 4000)
        return e

    def delay_log(self):
        c = self.open_center()
        if c is not None:
            c.show_tool("delay")
        return c

    def recovery(self):
        from .recovery_ui import RecoveryDialog
        d = RecoveryDialog(self.store, self, None)
        d.finished.connect(lambda *_: self.refresh())
        d.show()
        self._recovery = d
        return d

    def _claim_pdf(self, title, stem, export, path=None):
        if path is None:
            name = report_file_name(stem, self.store.name)
            path = QFileDialog.getSaveFileName(
                self, title, os.path.join(self.store.folder, name),
                "PDF (*.pdf)")[0]
        if not path:
            return None
        export(self.store, path)
        if self.main is not None and not os.environ.get("QUANTISHEET_NO_OPEN"):
            self.main.open_path(path)
        self.statusBar().showMessage(f"Saved {os.path.basename(path)}", 4000)
        return path

    def quality_check(self, path=None):
        from . import schedule_check
        return self._claim_pdf("Schedule Quality Check",
                               "Schedule Quality Check",
                               schedule_check.export_pdf, path)

    def claim_package(self, path=None):
        from . import claim_package
        return self._claim_pdf("Claim Package", "Schedule Claim Package",
                               claim_package.export_pdf, path)

    def open_center(self):
        from . import center
        try:
            return center.open_center(self.store.folder, self.main)
        except Exception as ex:
            QMessageBox.warning(self, "Project Center", str(ex))
            return None

    def build_from_plans(self, plans=None, spec=None, show=True):
        if plans is None and self.main is not None and \
                getattr(self.main, "_path", None):
            plans = self.main._path
        dlg = BuildFromPlansDialog(self, plans, spec)
        if show:
            dlg.exec()
        return dlg

    def fit_to_contract(self, target=None):
        """Shorten the work on the driving path so Substantial Completion
        makes the contract date (autoschedule.fit_result); says so when a
        lead-time row drives the finish."""
        from . import autoschedule as au
        ntp = schedule._d(self.store.setting("project_start")) or \
            _dt.date.today()
        if target is None:
            return None
        self.checkpoint()
        res = au.fit_result(self.store, target, ntp)
        got = res["finish"]
        self.refresh()
        text = f"Substantial Completion now {got:%b %d, %Y}" if got else \
            "No Substantial Completion milestone to fit"
        if got and res.get("message"):
            text += ". " + res["message"]
        self.last_fit_message = text
        self.statusBar().showMessage(text, 12000 if res.get("message")
                                     else 6000)
        if got and res.get("message") and \
                not getattr(self, "_quiet", False):
            QMessageBox.information(self, "Fit to Contract", text)
        return got

    def new_schedule(self):
        st = new_schedule_dialog(self)
        if st is not None:
            open_scheduler(st, self.main)

    def open_schedule(self):
        st = choose_schedule(self)
        if st is not None:
            open_scheduler(st, self.main)

    def closeEvent(self, e):
        try:
            self.store.listeners.remove(self._listener)
        except ValueError:
            pass
        super().closeEvent(e)


# ------------------------------------------------------------- opening
_WINDOWS = []


def open_scheduler(store, main=None):
    w = Scheduler(store, main)
    _WINDOWS.append(w)
    w.setAttribute(Qt.WA_DeleteOnClose)
    w.destroyed.connect(lambda *_: _WINDOWS.remove(w) if w in _WINDOWS
                        else None)
    recent = [f for f in settings.get("pm_recent", []) if f != store.folder]
    settings.set("pm_recent", ([store.folder] + recent)[:8])
    w.show()
    return w


def create_schedule(name, folder=None, start=None):
    """A new project (just a name) for a schedule. Returns its store."""
    from .store import ProjectStore, open_store
    name = (name or "").strip() or "New Schedule"
    if folder is None:
        safe = re.sub(r'[\\/:*?"<>|]+', "-", name).strip(" .") or "Schedule"
        folder = os.path.join(DEFAULT_FOLDER, safe)
        k = 2
        while ProjectStore.exists(folder):
            folder = os.path.join(DEFAULT_FOLDER, f"{safe} ({k})")
            k += 1
    os.makedirs(folder, exist_ok=True)
    st = open_store(folder)
    st.data["name"] = name
    if start:
        st.data["settings"]["project_start"] = start.isoformat()
    st.save()
    return st


def new_schedule_dialog(parent=None, name=None, start=None):
    if name is None:
        d = QDialog(parent)
        d.setWindowTitle("New Schedule")
        f = QFormLayout(d)
        ed = QLineEdit()
        ed.setPlaceholderText("e.g. Shelter Cove - Site Utilities")
        sd = QLineEdit(_dt.date.today().strftime("%m/%d/%y"))
        f.addRow("Project / schedule name", ed)
        f.addRow("Work starts", sd)
        where = QLabel(f"Saved in {DEFAULT_FOLDER}")
        where.setObjectName("muted")
        f.addRow(where)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(d.accept)
        bb.rejected.connect(d.reject)
        f.addRow(bb)
        if not d.exec() or not ed.text().strip():
            return None
        name, start = ed.text().strip(), parse_date(sd.text())
    return create_schedule(name, start=start)


def choose_schedule(parent=None, title="Scheduler",
                    prompt="Open a schedule (each project has one), or start "
                           "a new one:", new_label="New Schedule…"):
    """Recent projects, New Schedule, or a project folder. Returns a store
    or None. Other project tools (the Weekly Owner Report) pass their own
    title, prompt and button text (Jon, Oct 22: the owner report's picker
    said "Scheduler")."""
    from .store import ProjectStore, open_store
    recent = [f for f in settings.get("pm_recent", []) if os.path.isdir(f)
              and ProjectStore.exists(f)]
    d = QDialog(parent)
    d.setWindowTitle(title)
    d.setMinimumWidth(520)
    v = QVBoxLayout(d)
    lab = QLabel(prompt)
    lab.setWordWrap(True)
    v.addWidget(lab)
    lw = QListWidget()
    for f in recent:
        try:
            name = ProjectStore(f).name
        except Exception:
            name = os.path.basename(f)
        it = QListWidgetItem(icons.icon("gantt"), f"{name}\n{f}")
        it.setData(Qt.UserRole, f)
        lw.addItem(it)
    v.addWidget(lw)
    out = {}
    row = QHBoxLayout()
    nb = QPushButton(new_label)
    nb.setObjectName("primary")
    ob = QPushButton("Open Folder…")
    row.addWidget(nb)
    row.addWidget(ob)
    row.addStretch()
    cancel = QPushButton("Cancel")
    row.addWidget(cancel)
    v.addLayout(row)

    def pick(it):
        out["folder"] = it.data(Qt.UserRole)
        d.accept()

    def new():
        st = new_schedule_dialog(d)
        if st is not None:
            out["store"] = st
            d.accept()

    def folder():
        f = QFileDialog.getExistingDirectory(d, "Project folder")
        if f:
            out["folder"] = f
            d.accept()
    lw.itemDoubleClicked.connect(pick)
    lw.itemActivated.connect(pick)
    nb.clicked.connect(new)
    ob.clicked.connect(folder)
    cancel.clicked.connect(d.reject)
    if not d.exec():
        return None
    if "store" in out:
        return out["store"]
    st = open_store(out["folder"])
    if not ProjectStore.exists(out["folder"]):
        st.save()
    return st


# ------------------------------------------------------------- from plans
class BuildFromPlansDialog(QDialog):
    """Build Schedule From Plans. Pick the drawing set and the spec
    book, Read them (contract time with its pages, scope, building area),
    check or change what was read, then Build the draft into this
    schedule."""

    def __init__(self, sched, plans_path=None, spec_path=None):
        super().__init__(sched)
        self.sched = sched
        self.info = None
        self.setWindowTitle("Build Schedule From Plans")
        self.resize(760, 620)
        v = QVBoxLayout(self)
        f = QFormLayout()
        self.plans = QLineEdit(plans_path or "")
        self.spec = QLineEdit(spec_path or "")
        for ed, label, title in ((self.plans, "Drawing set (PDF)",
                                  "Drawing set"),
                                 (self.spec, "Spec book / bid documents",
                                  "Spec book")):
            row = QHBoxLayout()
            row.addWidget(ed, 1)
            b = QPushButton("Browse…")
            b.clicked.connect(lambda _c=False, e=ed, t=title: self._pick(e,
                                                                         t))
            row.addWidget(b)
            f.addRow(label, row)
        # Nov 5 (bid set): addenda and bidder Q&A, in the order issued -
        # the detailed draft applies them before building (later wins)
        self.addenda = []
        arow = QHBoxLayout()
        self.addenda_lbl = QLabel("None")
        self.addenda_lbl.setWordWrap(True)
        arow.addWidget(self.addenda_lbl, 1)
        ab = QPushButton("Add…")
        ab.setToolTip("Addenda and bidder questions and answers, oldest "
                      "first. Removed items stay off the schedule.")
        ab.clicked.connect(lambda: self.add_addenda())
        arow.addWidget(ab)
        cb = QPushButton("Clear")
        cb.clicked.connect(lambda: self.add_addenda([], replace=True))
        arow.addWidget(cb)
        f.addRow("Addenda and Q&A (in order)", arow)
        today = _dt.date.today()
        nxt = today + _dt.timedelta(days=(7 - today.weekday()) % 7 or 7)
        self.ntp = QLineEdit(nxt.strftime("%m/%d/%y"))
        f.addRow("Notice to Proceed", self.ntp)
        v.addLayout(f)
        rb = QPushButton("Read the Plans && Specs")
        rb.setObjectName("primary")
        rb.clicked.connect(lambda: self.read())
        v.addWidget(rb)
        g = QFormLayout()
        from . import schedule_types as _st
        self.ptype = QComboBox()
        self.ptype.addItem("(not recognized - pick the project type)",
                           _st.UNKNOWN)
        for key, text in _st.TYPES.items():
            self.ptype.addItem(text, key)
        self.ptype.setToolTip("Detected from the sheet titles, spec sections"
                              ", drawing text and equipment schedules - "
                              "change it if it's wrong.")
        g.addRow("Project type", self.ptype)
        self.leads = QLineEdit()
        self.leads.setPlaceholderText("e.g. generator 30, ats 20 - weeks "
                                      "(blank = assumed starting values)")
        g.addRow("Long-lead equipment (weeks)", self.leads)
        self.area = QLineEdit()
        self.area.setPlaceholderText("from the room tags")
        self.levels = QLineEdit("1")
        self.days = QLineEdit()
        self.days.setPlaceholderText("contract days, from the specs")
        self.basis = QComboBox()
        self.basis.addItems(["calendar", "working"])
        self.sub_days = QLineEdit()
        self.sub_days.setPlaceholderText("blank = same as the contract time")
        g.addRow("Building area (SF)", self.area)
        g.addRow("Levels", self.levels)
        drow = QHBoxLayout()
        drow.addWidget(self.days)
        drow.addWidget(self.basis)
        g.addRow("Contract time (days)", drow)
        g.addRow("Days to Substantial Completion", self.sub_days)
        self.rates_btn = QPushButton("Production Rates…")
        self.rates_btn.setToolTip("Durations are quantity / (rate x crews):"
                                  " set the rates, crews and min / max days"
                                  " per activity family (assumed starting "
                                  "values until you change them).")
        self.rates_btn.clicked.connect(lambda: self.edit_rates())
        g.addRow("Durations", self.rates_btn)
        # PR 8 (Nov 4): the detailed draft - long-lead chains (submit,
        # review, release, fabricate, deliver), a completeness check that
        # must pass before it says "built", and why each activity is there
        self.detailed = QCheckBox("Detailed draft (new): long-lead chains "
                                  "and a completeness check")
        self.detailed.setChecked(bool(settings.get("schedacc_detailed",
                                                   False)))
        self.detailed.setToolTip(
            "Builds from the specs, drawings and your production rates "
            "with full procurement chains for long-lead items. If "
            "something needed is missing, it lists the gaps instead of "
            "saying the schedule is built.")
        g.addRow("", self.detailed)
        v.addLayout(g)
        self.found = QLabel("")
        self.found.setWordWrap(True)
        self.found.setTextInteractionFlags(Qt.TextSelectableByMouse)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setWidget(self.found)
        v.addWidget(sc, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Cancel)
        self.build_btn = bb.addButton("Build Schedule",
                                      QDialogButtonBox.AcceptRole)
        bb.accepted.connect(self.build)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def _build_detailed(self, st, sc, ntp, ask=None):
        """The PR 8 compiler (pm/schedacc). The local AI is used only if
        the setting schedacc_ai is on; it fills facts, never durations."""
        from .schedacc import apply as sa_apply
        from .schedacc import engine
        ptype = DETAILED_TYPE.get(sc.get("type"))
        if ptype is None and getattr(self.sched, "service", False):
            ptype = "plumbing_hvac_service"
        spec = self.spec.text().strip() or None
        plans = self.plans.text().strip() or None
        bid_set = None
        if self.addenda:
            from .schedacc import bidset
            bid_set = bidset.from_files(
                spec if spec and os.path.isfile(spec) else None,
                plans if plans and os.path.isfile(plans) else None,
                [p for p in self.addenda if os.path.isfile(p)])
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            doc = engine.compile_schedule(
                bid_set=bid_set,
                spec_pdf=spec if spec and os.path.isfile(spec) else None,
                drawings_pdf=plans if plans and os.path.isfile(plans)
                else None,
                project_type=ptype, ntp=ntp.isoformat(),
                project_name=st.name or "Project",
                area_sf=sc.get("area_sf"), stories=sc.get("stories") or 1,
                settings={"allow_ai": bool(settings.get("schedacc_ai",
                                                        False))})
        except Exception as e:                            # noqa: BLE001
            QApplication.restoreOverrideCursor()
            logging.getLogger(__name__).warning("detailed draft failed",
                                                exc_info=True)
            self.last_message = f"The detailed draft couldn't be made: {e}"
            if not getattr(self.sched, "_quiet", False):
                QMessageBox.warning(self, "Build Schedule", self.last_message)
            return None
        QApplication.restoreOverrideCursor()
        self.draft = doc
        if doc.get("status") != "finished":
            lines = ["The detailed draft has gaps - it is NOT a finished "
                     "schedule yet:", ""] + _detailed_gaps(doc)
            self.last_message = "\n".join(lines)
            if ask is None:
                if getattr(self.sched, "_quiet", False):
                    return None
                ask = lambda text: QMessageBox.question(   # noqa: E731
                    self, "Detailed Draft", text + "\n\nPut the draft in "
                    "anyway, to finish by hand?") == QMessageBox.Yes
            if not ask(self.last_message):
                return None
        self.sched.checkpoint()
        sa_apply.apply_to_store(st, doc, replace=True)
        self.result = {"detailed": doc}
        self.sched.refresh()
        self.accept()
        n = len(doc.get("activities") or ())
        self.last_message = (f"Detailed draft: {n} activities" +
                             (", completeness check passed" if
                              doc.get("status") == "finished" else
                              " (with gaps to finish)"))
        if doc.get("caveat"):
            self.last_message += "\n\n" + doc["caveat"]
        if not getattr(self.sched, "_quiet", False):
            QMessageBox.information(self.sched, "Detailed Draft",
                                    self.last_message)
        return self.result

    def edit_rates(self, show=True):
        """The production-rate table (productivity_ui); the next Build
        uses what's saved there."""
        from . import productivity_ui
        dlg = productivity_ui.ProductivityDialog(self)
        if show:
            dlg.exec()
        return dlg

    def add_addenda(self, paths=None, replace=False):
        if paths is None:
            paths, _ = QFileDialog.getOpenFileNames(
                self, "Addenda and Q&A (oldest first)", "",
                "PDF or text (*.pdf *.txt)")
        self.addenda = list(paths) if replace else self.addenda + [
            p for p in paths if p not in self.addenda]
        self.addenda_lbl.setText("; ".join(
            f"{i}. {os.path.basename(p)}" for i, p in
            enumerate(self.addenda, 1)) or "None")
        if self.addenda:
            self.detailed.setChecked(True)     # only the detailed draft
        return self.addenda

    def _pick(self, ed, title):
        p, _ = QFileDialog.getOpenFileName(self, title, ed.text(),
                                           "PDF (*.pdf)")
        if p:
            ed.setText(p)

    def read(self):
        from PySide6.QtWidgets import QApplication
        import fitz
        from . import autoschedule as au
        docs = {}
        for key, ed in (("plans", self.plans), ("spec", self.spec)):
            path = ed.text().strip().strip('"')
            if path:
                try:
                    docs[key] = fitz.open(path)
                except Exception as e:
                    QMessageBox.warning(self, "Build Schedule",
                                        f"Couldn't open {path}: {e}")
                    return None
        if not docs:
            QMessageBox.information(self, "Build Schedule", "Pick the "
                                    "drawing set, the spec book, or both.")
            return None
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self.info = au.read_job(docs.get("plans"), docs.get("spec"),
                                    progress=lambda t: (
                                        self.found.setText(t),
                                        QApplication.processEvents()))
        finally:
            QApplication.restoreOverrideCursor()
            for d in docs.values():
                d.close()
        return self.show_info()

    def show_info(self, info=None):
        """Fill the fields and the found text from a read_job() result."""
        from . import schedule_types as _st
        if info is not None:
            self.info = info
        ct, sc = self.info["ct"], self.info["scope"]
        unclear = _unclear(sc.get("detected") or {})
        self.ptype.setItemText(0, f"(unclear: {unclear} - pick one)" if
                               unclear else
                               "(not recognized - pick the project type)")
        i = self.ptype.findData(sc.get("type") or "unknown")
        self.ptype.setCurrentIndex(max(0, i))
        self.leads.setText(_st.format_lead_weeks(sc))
        if self.info.get("area_found"):
            self.area.setText(f"{sc['area_sf']:.0f}")
        self.levels.setText(str(sc["stories"]))
        fin = ct.get("final")
        if fin:
            self.days.setText(str(fin["days"]))
            self.basis.setCurrentText(fin["basis"])
        if ct.get("substantial"):
            self.sub_days.setText(str(ct["substantial"]["days"]))
        self.found.setText(self._found_text())
        return self.info

    def _found_text(self):
        ct, sc = self.info["ct"], self.info["scope"]
        lines = [f"<b>{self.info.get('sheets', 0)} sheets, "
                 f"{len(self.info.get('divisions') or ())} spec divisions "
                 "read.</b>"]
        if not ct["found"]:
            lines.append("No contract time found - type it above.")
        for x in ct["found"][:12]:
            what = (f"{x['days']} {x['basis']} days" if x.get("days") else
                    x.get("date", ""))
            lines.append(f"p. {x['page']}: <b>{what}</b> "
                         f"({x['kind'].replace('_', ' ')}) - "
                         f"<i>{_esc(x['text'][:160])}</i>")
        if ct.get("ld_per_day"):
            lines.append(f"Liquidated damages ${_c2(ct['ld_per_day']):,.2f}/day "
                         f"(p. {', '.join(map(str, ct['ld_pages']))}).")
        for c in ct.get("conflicts", []):
            lines.append(f"<span style='color:#c62828'><b>Check:</b> "
                         f"{_esc(c)}</span>")
        det = sc.get("detected") or {}
        unclear = _unclear(det)
        if sc.get("type") == "unknown" and unclear:
            lines.append(f"<span style='color:#c62828'><b>Project type "
                         f"unclear: {_esc(unclear)} - pick one</b> above "
                         "(the evidence is close; no type is assumed)."
                         "</span>")
            scores = det.get("scores") or {}
            why = det.get("why") or {}
            for k in det.get("candidates") or ():
                lines.append(f"&nbsp;&nbsp;<b>{_esc(_type_label(k))}</b> "
                             f"(score {scores.get(k, 0):g}):")
                for e in why.get(k, [])[:5]:
                    lines.append("&nbsp;&nbsp;&nbsp;&nbsp;- " + _esc(e))
        elif sc.get("type") == "unknown":
            lines.append("<span style='color:#c62828'><b>Project type not "
                         "recognized</b> - pick it above (no building is "
                         "assumed).</span>")
        else:
            lines.append(f"<b>Project type: {_esc(sc.get('type_label'))}"
                         f"</b> (score {det.get('score', 0):g}) because of:")
            for e in (sc.get("evidence") or [])[:12]:
                lines.append("&nbsp;&nbsp;- " + _esc(e))
        shown = set(det.get("candidates") or ()) if unclear else set()
        others = [f"{_esc(_type_label(k))} {v:g}" for k, v in
                  det.get("ranked", [])[1:4] if k not in shown]
        if others:
            lines.append("Other types considered: " + ", ".join(others))
        eq = sc.get("equipment") or []
        if eq:
            lines.append("Equipment: " + ", ".join(
                _esc((e["tag"] + " " if e.get("tag") else "") +
                     f"({e['desc']})" + (" - long lead" if
                                         e.get("long_lead") else ""))
                for e in eq[:12]))
        lines.append("Scope: " + ", ".join(sorted(sc["flags"])))
        lines += [_esc(n) for n in sc.get("notes", [])]
        return "<br>".join(lines)

    def inputs(self):
        """(scope, contract time, NTP) from the fields."""
        from . import autoschedule as au
        info = self.info or {"ct": au.contract_time([]),
                             "scope": au.scope()}
        from . import schedule_types as _st
        sc = dict(info["scope"])
        try:
            sc["area_sf"] = float(self.area.text().replace(",", ""))
            sc["area_found"] = True
        except ValueError:
            pass
        sc["lead_weeks"] = _st.parse_lead_weeks(self.leads.text())
        if "*" in sc["lead_weeks"]:            # a bare number
            w = sc["lead_weeks"].pop("*")
            first = next((e["kind"] for e in sc.get("equipment") or ()
                          if e.get("long_lead")), "generator")
            sc["lead_weeks"].setdefault(first, w)
        picked = self.ptype.currentData() or _st.UNKNOWN
        detected = (sc.get("detected") or {}).get("type")
        sc = au.retype(sc, picked, picked=picked != detected)
        try:
            sc["stories"] = max(1, int(self.levels.text()))
        except ValueError:
            pass
        ct = dict(info["ct"])
        try:
            d = int(self.days.text())
            ct["final"] = {"days": d, "basis": self.basis.currentText(),
                           "pages": (ct.get("final") or {}).get("pages", [])}
        except ValueError:
            pass
        try:
            d = int(self.sub_days.text())
            ct["substantial"] = {"days": d, "basis":
                                 self.basis.currentText(), "pages":
                                 (ct.get("substantial") or {}).get(
                                     "pages", [])}
        except ValueError:
            pass
        ntp = parse_date(self.ntp.text()) or _dt.date.today()
        return sc, ct, ntp

    def build(self, replace=None):
        from . import autoschedule as au
        st = self.sched.store
        sc, ct, ntp = self.inputs()
        if sc.get("type") == "unknown":
            unclear = _unclear(sc.get("detected") or {})
            self.last_message = (
                f"Project type unclear: {unclear} - pick one, then Build."
                if unclear else "The project type wasn't recognized from "
                "the plans and specs. Pick the project type, then Build.")
            if not getattr(self.sched, "_quiet", False):
                QMessageBox.information(self, "Build Schedule",
                                        self.last_message)
            return None
        if st.list("activity"):
            if replace is None:
                replace = QMessageBox.question(
                    self, "Build Schedule", "This project already has a "
                    "schedule. Replace it with the draft? (Undo brings it "
                    "back.)") == QMessageBox.Yes
            if not replace:
                return None
        if self.detailed.isChecked():
            settings.set("schedacc_detailed", True)
            return self._build_detailed(st, sc, ntp)
        settings.set("schedacc_detailed", False)
        self.sched.checkpoint()
        res = au.build(st, sc, ntp, ct, replace=True)
        self.result = res
        self.sched.refresh()
        lines = au.summary_text(ct, sc, res)
        late = (res["fit"].get("substantial_days_spare") or 0) < 0
        self.accept()
        if not getattr(self.sched, "_quiet", False):
            msg = QMessageBox(self.sched)
            msg.setWindowTitle("Schedule built")
            msg.setText("\n".join(lines))
            if late:
                fb = msg.addButton("Fit to Contract", QMessageBox.ActionRole)
            msg.addButton(QMessageBox.Ok)
            msg.exec()
            if late and msg.clickedButton() is fb:
                self.sched.fit_to_contract(res["fit"]["required_substantial"])
        return res


DETAILED_TYPE = {"new_building": "ground_up_commercial",
                 "renovation": "tenant_improvement",
                 "hvac_replacement": "mep_retrofit"}


def _detailed_gaps(doc):
    """Plain lines for a detailed draft that isn't finished."""
    rub = doc.get("rubric") or {}
    hl = doc.get("health") or {}
    out = [f"Completeness: {rub.get('passed_checks', 0)} of "
           f"{rub.get('total', 0)} checks passed."]
    for gap in (rub.get("gaps") or [])[:12]:
        out.append("- " + (gap if isinstance(gap, str) else
                           str(gap.get("message") or gap.get("text") or
                               gap.get("name") or gap)))
    if hl:
        out.append(f"Schedule health: {hl.get('score', 0)}")
    return out


def _unclear(det):
    """"New building or Renovation / tenant fit-out" when detect() found
    the top types too close to call, else None."""
    cands = det.get("candidates") or []
    if not det.get("ambiguous") or len(cands) < 2:
        return None
    names = [_type_label(k) for k in cands]
    return ", ".join(names[:-1]) + " or " + names[-1]


def _type_label(key):
    from . import schedule_types as _st
    return _st.label(key)


def _esc(t):
    import html
    return html.escape(str(t))
