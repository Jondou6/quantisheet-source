"""Civil > Work Notes Takeoff: the quantities a retrofit set states in
its notes, its summary table, its keyed notes and its specification
(callouts.py, callout_scope.py). Nothing is added to the takeoff from
here: it is a list to check and export."""
import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QApplication, QDialog, QDialogButtonBox,
                               QFileDialog, QHBoxLayout, QHeaderView, QLabel,
                               QMessageBox, QPushButton, QTableWidget,
                               QTableWidgetItem, QTabWidget, QVBoxLayout)

from . import callout_scope as cs
from . import callouts as co

CHECK = QColor("#fff3c4")
INK = QColor("#111111")


class WorkNotesDialog(QDialog):
    def __init__(self, path, parent=None, go_to=None):
        super().__init__(parent)
        self.path, self.go_to = path, go_to
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
            "Double-click a row to go to its sheet.")
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
        v.addWidget(self.tabs, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        x = bb.addButton("Export to Excel…", QDialogButtonBox.ActionRole)
        x.clicked.connect(lambda: self.export())
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
                          go_to=view.go_to if view is not None else None)
    if modal:
        dlg.exec()
    else:
        dlg.show()
    return dlg
