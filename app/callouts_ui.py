"""Civil > Work Notes Takeoff: the quantities a retrofit set states in
its notes, its summary table, its keyed notes and its specification
(callouts.py, callout_scope.py). It is a list to check and export;
Add to Estimate puts the totals in the Estimate panel as lines to price
(Nov 16), each saying which sheets it came from and linked to the total,
which is kept with AI Takeoff's quantities so a note is in the estimate
once (Nov 17)."""
import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QApplication, QDialog, QDialogButtonBox,
                               QFileDialog, QHBoxLayout, QHeaderView, QLabel,
                               QMessageBox, QPushButton, QTableWidget,
                               QTableWidgetItem, QTabWidget, QVBoxLayout)

from . import callout_scope as cs
from . import callouts as co

SOURCE = "Work Notes Takeoff"
TO_CHECK = "Check before pricing: "


def estimate_lines(rows):
    """[(desc, qty, unit, note)] for the estimate, one per total with a
    quantity: 'Install 2 EA 6-INCH PLUG VALVE' becomes the line
    'Install 6-INCH PLUG VALVE', 2 EA, its sheets in the note. A total
    still to be measured (no length) is left out."""
    out = []
    for s in co.summary([r for r in rows if r["qty"]]):
        desc = " ".join(x for x in (s["action"], s["what"]) if x)
        sheets = ", ".join(str(x) for x in s["sheets"] if x)
        note = (f"From {SOURCE}, sheet{'s' if len(s['sheets']) != 1 else ''}"
                f" {sheets}." if sheets else f"From {SOURCE}.")
        if s["check"]:
            note += " " + TO_CHECK + "; ".join(s["check"])
        out.append((desc, s["qty"], s["unit"], note[:500]))
    return out


def add_to_estimate(doc, rows):
    """Put the totals in the estimate (Nov 17: one place for work notes).
    Each total is kept with the job's takeoff quantities (the same store
    AI Takeoff uses, so a note is never in the estimate twice) and gets
    one estimate line linked to it, to price: the line's quantity follows
    when the notes are read and added again. A line this window added
    before (same description) is linked in place, keeping its price.
    Returns (added, updated, left out)."""
    from . import ai_quantities as aq
    from . import estimate_lines as el
    totals = []
    lines = []
    for desc, qty, unit, note in estimate_lines(rows):
        u = str(unit or "").upper()
        totals.append({"name": desc, "qty": qty, "unit": u,
                       "basis": note})
        lines.append((desc, u, note))
    aq.store_worknotes(doc, totals)
    have = {}
    for x in el.read(doc):
        if x.get("source") == SOURCE:
            have.setdefault(x["desc"], x)
    new, updated = [], 0
    for desc, u, note in lines:
        link = {"name": desc[:300], "type": aq.TYPE, "unit": u}
        old = have.get(desc[:300])
        if old is not None:
            el.update(doc, old["id"], link=link, unit=u.lower(), note=note)
            updated += 1
            continue
        new.append(el.new_line(desc=desc, unit=u.lower(), source=SOURCE,
                               note=note, link=link))
    if new:
        el.add(doc, new)
    left = sum(1 for s in co.summary(rows) if not s["qty"])
    return len(new), updated, left


CHECK = QColor("#fff3c4")
INK = QColor("#111111")


class WorkNotesDialog(QDialog):
    def __init__(self, path, parent=None, go_to=None, estimate=None):
        super().__init__(parent)
        self.path, self.go_to, self.estimate = path, go_to, estimate
        self.spec, self.rows, self.facts = "", [], {}
        self.setWindowTitle("Work Notes Takeoff - " + os.path.basename(path))
        self.resize(1080, 620)
        v = QVBoxLayout(self)
        note = QLabel(
            "Reads what the drawings <b>say</b>: boxed work notes "
            "(INSTALL: 2 - 6-INCH PLUG VALVE), the summary table, numbered "
            "and keyed notes, and the fence line as drawn. Choose the "
            "specification to work out posts and barbed wire from its "
            "rules. Yellow rows need a look - the Check column says why. "
            "Double-click a row to go to its sheet. Add to Estimate puts "
            "the totals in the Estimate panel to price.")
        note.setWordWrap(True)
        v.addWidget(note)
        h = QHBoxLayout()
        self.spec_label = QLabel("Specification: none chosen")
        b = QPushButton("Choose Specification…")
        b.clicked.connect(lambda: self.choose_spec())
        self.read_btn = QPushButton("Read the Drawings")
        self.read_btn.clicked.connect(lambda: self.read())
        h.addWidget(self.spec_label, 1)
        h.addWidget(b)
        h.addWidget(self.read_btn)
        v.addLayout(h)
        self.status = QLabel("")
        v.addWidget(self.status)
        self.tabs = QTabWidget()
        self.totals = self._table()
        self.every = self._table()
        self.every.cellDoubleClicked.connect(self._open)
        self.tabs.addTab(self.totals, "Totals")
        self.tabs.addTab(self.every, "Every row")
        self.changes = self._table()
        self.changes_at = self.tabs.addTab(self.changes, "Changes")
        self.tabs.setTabEnabled(self.changes_at, False)
        self.changed = []
        v.addWidget(self.tabs, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        x = bb.addButton("Export to Excel…", QDialogButtonBox.ActionRole)
        x.clicked.connect(lambda: self.export())
        c = bb.addButton("Compare with Earlier Set…",
                         QDialogButtonBox.ActionRole)
        c.setToolTip("Read an earlier issue of the drawings and list what "
                     "this set changed in the work notes, sheet by sheet")
        c.clicked.connect(lambda: self.compare())
        a = bb.addButton("Add to Estimate", QDialogButtonBox.ActionRole)
        a.setToolTip("Put the totals in the Estimate panel as lines to "
                     "price, each with the sheets it came from")
        a.clicked.connect(lambda: self.to_estimate())
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    @staticmethod
    def _table():
        t = QTableWidget(0, 0)
        t.setEditTriggers(QTableWidget.NoEditTriggers)
        t.setSelectionBehavior(QTableWidget.SelectRows)
        t.setWordWrap(True)
        return t

    def choose_spec(self, path=None):
        if path is None:
            path, _ = QFileDialog.getOpenFileName(
                self, "Specification", os.path.dirname(self.path),
                "PDF (*.pdf)")
        if not path:
            return None
        self.spec = path
        self.spec_label.setText("Specification: " + os.path.basename(path))
        if self.rows:
            self.read()
        return path

    def read(self):
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            text = cs.pdf_text(self.spec) if self.spec else ""
            self.rows, self.facts = cs.read_set(self.path, text)
        except Exception as e:                            # noqa: BLE001
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "Work Notes Takeoff",
                                f"The drawings couldn't be read: {e}")
            return None
        QApplication.restoreOverrideCursor()
        self.fill()
        return self.rows

    def compare(self, path=None):
        """Compare with an earlier issue of the set (Nov 17): the Changes
        tab lists every work-note total that moved - added, gone or
        changed - with the sheets where it changed. Returns the rows."""
        if not self.rows:
            self.status.setText("Read the Drawings first, then compare.")
            return None
        if path is None:
            path, _ = QFileDialog.getOpenFileName(
                self, "Earlier Set of the Drawings",
                os.path.dirname(self.path), "PDF (*.pdf)")
            if not path:
                return None
        if os.path.abspath(path) == os.path.abspath(self.path):
            self.status.setText("Pick the earlier issue - that is this set.")
            return None
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            text = cs.pdf_text(self.spec) if self.spec else ""
            old, _facts = cs.read_set(path, text)
        except Exception as e:                            # noqa: BLE001
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "Work Notes Takeoff",
                                f"The earlier set couldn't be read: {e}")
            return None
        QApplication.restoreOverrideCursor()
        self.changed = co.compare(old, self.rows)
        head = ["Change", "Action", "Item", "Before", "Now", "Unit",
                "Sheets"]
        body = [[{"added": "New", "removed": "Gone"}.get(r["kind"],
                                                          "Changed"),
                 r["action"], r["what"], r["before"], r["after"], r["unit"],
                 ", ".join(f"{sh or '?'}: {d:+g}" for sh, d in r["sheets"])]
                for r in self.changed]
        self._put(self.changes, [head] + (body or [["", "", "No change in "
                                                    "the work notes", "",
                                                    "", "", ""]]),
                  check_col=0)
        self.tabs.setTabEnabled(self.changes_at, True)
        self.tabs.setCurrentIndex(self.changes_at)
        self.status.setText(
            f"Compared with {os.path.basename(path)}: "
            f"{len(self.changed)} work-note total(s) changed." if
            self.changed else f"Compared with {os.path.basename(path)}: "
            "no work-note total changed.")
        return self.changed

    def fill(self):
        tot, _ = co.table([r for r in self.rows if r["qty"]])
        self._put(self.totals, tot, check_col=len(tot[0]) - 1)
        each = cs.sheet_table(self.rows)
        self._put(self.every, each, check_col=len(each[0]) - 1)
        said = []
        if "post_spacing_ft" in self.facts:
            said.append(f"posts at {self.facts['post_spacing_ft']:g} ft")
        if "barbed_strands" in self.facts:
            said.append(f"{self.facts['barbed_strands']} strands of "
                        "barbed wire")
        need = sum(1 for r in self.rows if r["check"])
        self.status.setText(
            f"{len(self.rows)} rows; {need} to check. " +
            ("From the specification: " + ", ".join(said) + "."
             if said else ("The specification gave no fence rule."
                           if self.spec else "")))
        if not self.rows:
            self.status.setText("No work notes were found on these sheets.")

    @staticmethod
    def _put(t, rows, check_col):
        t.setColumnCount(len(rows[0]))
        t.setHorizontalHeaderLabels([str(c) for c in rows[0]])
        t.setRowCount(len(rows) - 1)
        for i, row in enumerate(rows[1:]):
            flag = bool(row[check_col])
            for j, c in enumerate(row):
                it = QTableWidgetItem(str(c))
                if flag:
                    it.setBackground(CHECK)
                    it.setForeground(INK)
                t.setItem(i, j, it)
        hd = t.horizontalHeader()
        hd.setSectionResizeMode(QHeaderView.Interactive)
        t.resizeColumnsToContents()
        for j in range(t.columnCount()):
            if t.columnWidth(j) > 380:
                t.setColumnWidth(j, 380)
        hd.setStretchLastSection(True)

    def _open(self, r, _c):
        if not 0 <= r < len(self.rows):
            return None
        page = self.rows[r].get("page")
        if page is None or not self.go_to:
            return None
        self.go_to(int(page))
        return page

    def to_estimate(self, say=None):
        say = say or (lambda t: QMessageBox.information(
            self, "Work Notes Takeoff", t))
        if not self.rows:
            say("Read the drawings first.")
            return None
        est = self.estimate
        doc = getattr(est, "doc", None)
        if doc is None:
            say("Open the drawing set in the main window first: the lines "
                "are saved in its PDF.")
            return None
        from . import estimate_lines as el
        try:
            added, updated, left = add_to_estimate(doc, self.rows)
        except el.LineError as e:
            say(str(e))
            return None
        if hasattr(est, "changed"):
            est.changed.emit()
        if hasattr(est, "refresh"):
            est.refresh()
        parts = [f"{added} line{'s' if added != 1 else ''} added to the "
                 "estimate"]
        if updated:
            parts.append(f"{updated} updated with the new quantity")
        text = ", ".join(parts) + ". They have no price yet: type a unit " \
            "cost in the Estimate panel. The note on each line says which " \
            "sheets it came from and what to check."
        if left:
            text += (f" {left} total{'s' if left != 1 else ''} still to be "
                     "measured (no length yet) were left out.")
        say(text)
        return added, updated, left

    def export(self, path=None):
        if not self.rows:
            QMessageBox.information(self, "Work Notes Takeoff",
                                    "Read the drawings first.")
            return None
        if path is None:
            base = os.path.splitext(os.path.basename(self.path))[0]
            path, _ = QFileDialog.getSaveFileName(
                self, "Export Work Notes Takeoff",
                os.path.join(os.path.dirname(self.path),
                             base + " - work notes takeoff.xlsx"),
                "Excel (*.xlsx)")
        if not path:
            return None
        return cs.export_xlsx(self.rows, path)


def show(win, modal=True):
    path = getattr(win, "_path", None)
    if not path or not os.path.isfile(path):
        QMessageBox.information(
            win, "Work Notes Takeoff",
            "Open the drawing set first (save it if it is new).")
        return None
    view = getattr(win, "_view", None)
    dlg = WorkNotesDialog(path, win,
                          go_to=view.go_to if view is not None else None,
                          estimate=getattr(win, "estimate", None))
    if modal:
        dlg.exec()
    else:
        dlg.show()
    return dlg
