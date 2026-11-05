"""RFI / Submittal Log panel and the dialog that edits one item."""
import datetime

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDateEdit, QDialog,
    QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMenu, QMessageBox, QPlainTextEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from . import theme as _theme
from . import rfilog


class _Date(QWidget):
    """A date that can be left blank."""

    def __init__(self, value=""):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.on = QCheckBox()
        self.edit = QDateEdit()
        self.edit.setCalendarPopup(True)
        self.edit.setDisplayFormat("yyyy-MM-dd")
        lay.addWidget(self.on)
        lay.addWidget(self.edit, 1)
        self.on.toggled.connect(self.edit.setEnabled)
        self.set(value)

    def set(self, value):
        d = QDate.fromString(value or "", "yyyy-MM-dd")
        self.on.setChecked(d.isValid())
        self.edit.setEnabled(d.isValid())
        self.edit.setDate(d if d.isValid() else QDate.currentDate())

    def value(self):
        return self.edit.date().toString("yyyy-MM-dd") \
            if self.on.isChecked() else ""


class RfiDialog(QDialog):
    def __init__(self, item, parent=None):
        super().__init__(parent)
        self.item = dict(item)
        kind = item.get("kind", "RFI")
        self.setWindowTitle(f"{item.get('number') or kind}")
        self.resize(620, 640)
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.kind = QComboBox()
        self.kind.addItems(list(rfilog.KINDS))
        self.kind.setCurrentText(kind)
        self.kind.setEnabled(not item.get("number"))
        self.title = QLineEdit(item.get("title", ""))
        self.question = QPlainTextEdit(item.get("question", ""))
        self.question.setMinimumHeight(90)
        self.answer = QPlainTextEdit(item.get("answer", ""))
        self.answer.setMinimumHeight(70)
        self.spec = QLineEdit(item.get("spec", ""))
        self.spec.setPlaceholderText("e.g. 08 71 00")
        self.sheet = QLineEdit(item.get("sheet", ""))
        self.assigned = QLineEdit(item.get("assigned", ""))
        self.ball = QLineEdit(item.get("ball_in_court", ""))
        self.status = QComboBox()
        self.kind.currentTextChanged.connect(self._statuses)
        self._statuses(kind)
        self.status.setCurrentText(item.get("status") or
                                   self.status.itemText(0))
        self.sent = _Date(item.get("sent", ""))
        self.due = _Date(item.get("due", ""))
        self.returned = _Date(item.get("returned", ""))
        self.cost = QComboBox()
        self.cost.setEditable(True)
        self.cost.addItems(["", "None", "Possible", "Yes"])
        self.cost.setCurrentText(item.get("cost_impact", ""))
        self.sched = QComboBox()
        self.sched.setEditable(True)
        self.sched.addItems(["", "None", "Possible", "Yes"])
        self.sched.setCurrentText(item.get("schedule_impact", ""))
        self.notes = QPlainTextEdit(item.get("notes", ""))
        self.notes.setMaximumHeight(60)
        for label, w in (("Type", self.kind), ("Title", self.title),
                         ("Question", self.question), ("Answer", self.answer),
                         ("Spec section", self.spec), ("Sheet", self.sheet),
                         ("Assigned to", self.assigned),
                         ("Ball in court", self.ball), ("Status", self.status),
                         ("Sent", self.sent), ("Due", self.due),
                         ("Returned", self.returned),
                         ("Cost impact", self.cost),
                         ("Schedule impact", self.sched),
                         ("Notes", self.notes)):
            form.addRow(label, w)
        lay.addLayout(form)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _statuses(self, kind):
        cur = self.status.currentText()
        self.status.clear()
        self.status.addItems(rfilog.STATUSES.get(kind, ["Open"]))
        if cur:
            self.status.setCurrentText(cur)

    def values(self):
        return {"kind": self.kind.currentText(),
                "title": self.title.text().strip(),
                "question": self.question.toPlainText().strip(),
                "answer": self.answer.toPlainText().strip(),
                "spec": self.spec.text().strip(),
                "sheet": self.sheet.text().strip(),
                "assigned": self.assigned.text().strip(),
                "ball_in_court": self.ball.text().strip(),
                "status": self.status.currentText(),
                "sent": self.sent.value(), "due": self.due.value(),
                "returned": self.returned.value(),
                "cost_impact": self.cost.currentText().strip(),
                "schedule_impact": self.sched.currentText().strip(),
                "notes": self.notes.toPlainText().strip()}


class RfiPanel(QWidget):
    """The log as a table: filter, add, edit, delete, go to, export."""

    go_to = Signal(int, object)          # page, markup ref
    edited = Signal()                    # the PDF changed

    def __init__(self):
        super().__init__()
        self.doc = None
        self.rows = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        bar = QHBoxLayout()
        self.view_filter = QComboBox()
        self.view_filter.addItems(["All", "Open", "Overdue", "RFIs", "Submittals"])
        self.view_filter.currentIndexChanged.connect(self.refresh)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.refresh)
        bar.addWidget(self.view_filter)
        bar.addWidget(self.search, 1)
        lay.addLayout(bar)
        self.table = QTableWidget(0, len(rfilog.headers()))
        self.table.setHorizontalHeaderLabels(rfilog.headers())
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.Stretch)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.cellDoubleClicked.connect(lambda r, c: self.edit(r))
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._menu)
        lay.addWidget(self.table)
        row = QHBoxLayout()
        for text, slot in (("New RFI", lambda: self.new("RFI")),
                           ("New Submittal", lambda: self.new("Submittal")),
                           ("Edit", lambda: self.edit()),
                           ("Go To", self.go)):
            b = QPushButton(text)
            b.clicked.connect(lambda _c=False, _f=slot: _f())
            row.addWidget(b)
        exp = QPushButton("Export…")
        m = QMenu(exp)
        m.addAction("PDF Log…", lambda: self.export("pdf"))
        m.addAction("Excel…", lambda: self.export("xlsx"))
        m.addAction("CSV…", lambda: self.export("csv"))
        exp.setMenu(m)
        row.addStretch()
        row.addWidget(exp)
        lay.addLayout(row)
        self.count = QLabel("")
        lay.addWidget(self.count)

    def set_doc(self, doc):
        self.doc = doc
        self.refresh()

    def refresh(self, *_):
        self.table.setRowCount(0)
        if self.doc is None or self.doc.is_closed:
            self.rows = []
            return
        mode = self.view_filter.currentText()
        text = self.search.text().lower().strip()
        all_items = rfilog.items(self.doc)
        self.rows = []
        today = datetime.date.today()
        for it in all_items:
            if mode == "Open" and not rfilog.is_open(it):
                continue
            if mode == "Overdue" and not rfilog.is_overdue(it, today):
                continue
            if mode == "RFIs" and it.get("kind") != "RFI":
                continue
            if mode == "Submittals" and it.get("kind") != "Submittal":
                continue
            if text and text not in " ".join(
                    str(v) for v in it.values()
                    if isinstance(v, (str, int, float))).lower():
                continue
            self.rows.append(it)
        for it in self.rows:
            r = self.table.rowCount()
            self.table.insertRow(r)
            overdue = rfilog.is_overdue(it, today)
            for c, v in enumerate(rfilog._row(it, today)):
                cell = QTableWidgetItem(str(v))
                if overdue:
                    _theme.tint(cell, QColor(255, 225, 225))
                self.table.setItem(r, c, cell)
        n_open = sum(1 for it in all_items if rfilog.is_open(it))
        n_late = sum(1 for it in all_items if rfilog.is_overdue(it, today))
        self.count.setText(f"{len(all_items)} item(s), {n_open} open, "
                           f"{n_late} overdue")

    def _selected(self, row=None):
        if row is None:
            row = self.table.currentRow()
        return self.rows[row] if 0 <= row < len(self.rows) else None

    def new(self, kind="RFI", fields=None):
        if self.doc is None:
            return None
        base = {"kind": kind, **(fields or {})}
        dlg = RfiDialog(base, self)
        if not dlg.exec():
            return None
        vals = dlg.values()
        vals.update({k: v for k, v in (fields or {}).items()
                     if k in ("page", "markup", "source")})
        it = rfilog.add(self.doc, **vals)
        self.edited.emit()
        self.refresh()
        return it

    def edit(self, row=None):
        it = self._selected(row)
        if it is None:
            return None
        dlg = RfiDialog(it, self)
        if not dlg.exec():
            return None
        vals = dlg.values()
        vals.pop("kind", None)
        out = rfilog.update(self.doc, it["id"], **vals)
        self.edited.emit()
        self.refresh()
        return out

    def delete(self):
        it = self._selected()
        if it is None:
            return
        if QMessageBox.question(self, "Delete", f"Delete {it['number']}?") \
                != QMessageBox.Yes:
            return
        rfilog.delete(self.doc, it["id"])
        self.edited.emit()
        self.refresh()

    def go(self):
        it = self._selected()
        if it and it.get("page") is not None:
            self.go_to.emit(int(it["page"]), it.get("markup"))

    def _menu(self, pos):
        if self._selected() is None:
            return
        m = QMenu(self)
        m.addAction("Edit…", lambda: self.edit())
        m.addAction("Go To Markup", self.go)
        m.addSeparator()
        m.addAction("Delete", self.delete)
        m.exec(self.table.viewport().mapToGlobal(pos))

    def export(self, fmt, path=None):
        if self.doc is None:
            return None
        if path is None:
            filt = {"pdf": "PDF (*.pdf)", "xlsx": "Excel (*.xlsx)",
                    "csv": "CSV (*.csv)"}[fmt]
            import os
            from .reportname import report_file_name
            proj = os.path.splitext(os.path.basename(
                getattr(self.doc, "name", "") or ""))[0]
            path, _ = QFileDialog.getSaveFileName(
                self, "Export Log",
                report_file_name("RFI-Submittal Log", proj, ext=f".{fmt}"),
                filt)
            if not path:
                return None
        fn = {"pdf": rfilog.export_pdf, "xlsx": rfilog.export_xlsx,
              "csv": rfilog.export_csv}[fmt]
        return fn(self.doc, path)


class AiRfiDialog(QDialog):
    """Findings from Review > AI: Find RFIs & Questions. Tick the ones to
    keep and edit the wording; the kept ones become RFIs."""

    COLS = ["Keep", "Question", "Reason", "Reference", "Page", "Quote",
            "Found by"]

    def __init__(self, findings, note="", parent=None):
        super().__init__(parent)
        self.findings = list(findings)
        self.setWindowTitle("AI: Find RFIs & Questions")
        self.resize(1200, 680)
        lay = QVBoxLayout(self)
        intro = QLabel(
            f"{len(self.findings)} possible RFI(s). \"Check\" items come from "
            "rules (missing sheets, spec sections, unscheduled equipment, "
            "open scope); \"AI\" items come from the local model - review "
            "them before sending. Double-click a question to reword it."
            + (f"<br><b>{note}</b>" if note else ""))
        intro.setWordWrap(True)
        lay.addWidget(intro)
        self.table = QTableWidget(len(self.findings), len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        h = self.table.horizontalHeader()
        # the question gets the room; reason and quote get a fixed share
        # you can drag wider, the small columns fit their contents
        h.setSectionResizeMode(QHeaderView.ResizeToContents)
        h.setSectionResizeMode(1, QHeaderView.Stretch)
        for c, w in ((2, 260), (5, 220)):
            h.setSectionResizeMode(c, QHeaderView.Interactive)
            self.table.setColumnWidth(c, w)
        h.setMinimumSectionSize(40)
        self.table.verticalHeader().setVisible(False)
        self.table.setWordWrap(True)
        for r, f in enumerate(self.findings):
            keep = QTableWidgetItem()
            keep.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            keep.setCheckState(Qt.Checked if f.get("source") == "check"
                               else Qt.Unchecked)
            self.table.setItem(r, 0, keep)
            vals = [f.get("question", ""), f.get("reason", ""),
                    f.get("reference", ""),
                    "" if f.get("page") is None else str(f["page"] + 1) +
                    (" (specs)" if f.get("doc") == "specs" else ""),
                    f.get("quote", ""),
                    "Check" if f.get("source") == "check" else "AI"]
            for c, v in enumerate(vals, 1):
                cell = QTableWidgetItem(str(v))
                if c != 1:
                    cell.setFlags(cell.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(r, c, cell)
        self.table.resizeRowsToContents()
        h.sectionResized.connect(
            lambda *_: self.table.resizeRowsToContents())
        lay.addWidget(self.table)
        row = QHBoxLayout()
        for text, state in (("Keep All", Qt.Checked),
                            ("Keep None", Qt.Unchecked)):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, s=state: self._all(s))
            row.addWidget(b)
        row.addStretch()
        lay.addLayout(row)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Create RFIs")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _all(self, state):
        for r in range(self.table.rowCount()):
            self.table.item(r, 0).setCheckState(state)

    def set_checked(self, rows):
        for r in range(self.table.rowCount()):
            self.table.item(r, 0).setCheckState(
                Qt.Checked if r in rows else Qt.Unchecked)

    def selected(self):
        out = []
        for r, f in enumerate(self.findings):
            if self.table.item(r, 0).checkState() == Qt.Checked:
                out.append({**f, "question":
                            self.table.item(r, 1).text().strip()})
        return [f for f in out if f["question"]]


class RfiFindingsPanel(QDialog):
    """Review > Find RFIs (v36): one panel. Rule findings appear as soon as
    the set is scanned (no AI needed); each has its citation and a ready
    CSI-style draft. Tick findings and press Draft RFI. "Reword with AI" is
    optional and streams from the local model."""

    COLS = ["Use", "Severity", "Finding", "Sheets"]
    piece = Signal(int, str)

    def __init__(self, parent=None, on_draft=None, on_specs=None,
                 on_goto=None):
        super().__init__(parent)
        from .ai import rfi_rules
        self._rules = rfi_rules
        self.on_draft, self.on_specs, self.on_goto = on_draft, on_specs, on_goto
        self.findings, self.drafts, self.spec_path = [], {}, None
        self.setWindowTitle("Find RFIs")
        self.setModal(False)
        self.resize(1150, 620)
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        self.status = QLabel("Scanning the drawing set…")
        self.status.setWordWrap(True)
        top.addWidget(self.status, 1)
        b = QPushButton("Add Specs PDF…")
        b.setToolTip("Also check the drawings against a project manual "
                     "(missing sections, pipe class).")
        b.clicked.connect(self._specs)
        top.addWidget(b)
        lay.addLayout(top)
        body = QHBoxLayout()
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(QHeaderView.ResizeToContents)
        h.setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.currentCellChanged.connect(lambda r, *_: self._show(r))
        self.table.cellDoubleClicked.connect(lambda r, _c: self._goto(r))
        body.addWidget(self.table, 3)
        self.text = QPlainTextEdit()
        self.text.textChanged.connect(self._edited)
        body.addWidget(self.text, 2)
        lay.addLayout(body, 1)
        row = QHBoxLayout()
        for label, fn in (("Go to Sheet", lambda: self._goto(self._row())),
                          ("Reword with AI", self._polish)):
            b = QPushButton(label)
            b.clicked.connect(lambda _c=False, _f=fn: _f())
            row.addWidget(b)
            if label == "Reword with AI":
                b.setToolTip("Optional. The local model rewords the "
                             "question only; it's rejected if it changes "
                             "any number or sheet.")
                self.ai_btn = b
        row.addStretch()
        self.draft_btn = QPushButton("Draft RFI")
        self.draft_btn.setDefault(True)
        self.draft_btn.clicked.connect(self._draft)
        row.addWidget(self.draft_btn)
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        row.addWidget(close)
        lay.addLayout(row)
        self.piece.connect(self._piece)
        self._busy = None

    # ---- filling ---------------------------------------------------------------------
    def set_findings(self, findings, note=""):
        self.findings = list(findings)
        self.drafts = {i: self._rules.draft(f)
                       for i, f in enumerate(self.findings)}
        self.table.setRowCount(len(self.findings))
        for r, f in enumerate(self.findings):
            use = QTableWidgetItem()
            use.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled |
                         Qt.ItemIsSelectable)
            use.setCheckState(Qt.Unchecked)
            self.table.setItem(r, 0, use)
            for c, v in enumerate((f.get("severity", ""),
                                   f.get("title") or f["question"],
                                   f.get("reference", "")), 1):
                self.table.setItem(r, c, QTableWidgetItem(str(v)))
        n = len(self.findings)
        hi = sum(f.get("severity") == "high" for f in self.findings)
        self.status.setText(
            (f"{n} finding(s), {hi} high. Each cites the sheets it came from. "
             "Tick the ones to send and press Draft RFI; double-click to go "
             "to the sheet." if n else "No findings in this set.") +
            (f"  <b>{note}</b>" if note else ""))
        if n:
            self.table.selectRow(0)
            self._show(0)

    def _row(self):
        return self.table.currentRow()

    def _show(self, r):
        self._showing = None
        self.text.setPlainText(self.drafts.get(r, ""))
        self._showing = r

    def _edited(self):
        r = getattr(self, "_showing", None)
        if r is not None and self._busy is None:
            self.drafts[r] = self.text.toPlainText()

    def _goto(self, r):
        if 0 <= r < len(self.findings) and self.on_goto:
            self.on_goto(self.findings[r])

    def _specs(self):
        path, _ = QFileDialog.getOpenFileName(self, "Specifications PDF", "",
                                              "PDF (*.pdf)")
        if path and self.on_specs:
            self.spec_path = path
            self.status.setText("Checking against the specifications…")
            self.on_specs(path)

    # ---- output ----------------------------------------------------------------------
    def selected(self):
        rows = [r for r in range(self.table.rowCount())
                if self.table.item(r, 0).checkState() == Qt.Checked]
        if not rows and 0 <= self._row() < len(self.findings):
            rows = [self._row()]
        return [dict(self.findings[r], draft=self.drafts.get(r, ""))
                for r in rows]

    def set_checked(self, rows):
        for r in range(self.table.rowCount()):
            self.table.item(r, 0).setCheckState(
                Qt.Checked if r in rows else Qt.Unchecked)

    def _draft(self):
        sel = self.selected()
        if sel and self.on_draft:
            made = self.on_draft(sel, self.spec_path) or []
            self.status.setText(f"Drafted {len(made)} RFI(s) in the RFI log.")

    # ---- optional AI wording ---------------------------------------------------------
    def _polish(self, ask=None, wait=False):
        r = self._row()
        if not 0 <= r < len(self.findings) or self._busy is not None:
            return
        f = self.findings[r]
        self._busy = r
        self.ai_btn.setEnabled(False)
        self.status.setText("Rewording with the local model…")
        self._stream = []

        def work():
            return self._rules.polish(
                f, ask=ask, on_text=lambda s: self.piece.emit(r, s))

        def done(res):
            text, ok = res
            self._busy = None
            self.ai_btn.setEnabled(True)
            base = self._rules.draft(dict(f, question=text))
            if r == self._row():
                self._showing = None
                self.text.setPlainText(base if ok else self.drafts[r])
                self._showing = r
            if ok:
                self.drafts[r] = base
            self.status.setText(
                "Reworded. Check it before sending." if ok else
                "The model's wording changed a number or reference, so the "
                "original question was kept.")

        def fail(err):
            self._busy = None
            self.ai_btn.setEnabled(True)
            if r == self._row():
                self._show(r)
            self.status.setText(f"AI not available ({err}). The draft is "
                                "complete without it.")
        if wait:
            try:
                return done(work())
            except Exception as e:
                return fail(e)
        from . import bg
        bg.run(work, done, fail, self)

    def _piece(self, r, s):
        if r == self._busy and r == self._row():
            self._stream.append(s)
            self._showing = None
            self.text.setPlainText("Rewording…\n\n" + "".join(self._stream))
