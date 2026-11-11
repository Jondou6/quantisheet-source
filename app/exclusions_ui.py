"""The Exclusions table (who excludes what), shared by the Leveling
window, the Leveling Board and Scope Sheets. See exclusions.py."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFileDialog,
                               QHeaderView, QInputDialog, QLabel, QMenu,
                               QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

from . import exclusions as ex

COLORS = {ex.EXCLUDED: QColor("#ffcdcd"), ex.INCLUDED: QColor("#cdf0cd"),
          ex.NOT_STATED: QColor("#f2f2f2")}
ONLY = QColor("#ff9d9d")
INK = QColor("#111111")


class ExclusionsPanel(QWidget):
    """Rows: exclusions (similar wordings together). Columns: bidders.
    `action`: (label, fn(bidder, wording)) offered on an excluded cell.
    `moves_changed` fires with the new split/merge choices so the owner
    can keep them."""
    moves_changed = Signal(dict)

    def __init__(self, parent=None, action=None):
        super().__init__(parent)
        self.bids, self.moves, self.rows = [], {}, []
        self.action = action
        self.source = None           # fn(bidder, wording): show its source
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        self.note = QLabel("")
        self.note.setWordWrap(True)
        v.addWidget(self.note)
        self.table = QTableWidget(0, 0)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setWordWrap(True)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._menu)
        self.table.cellDoubleClicked.connect(self._open)
        v.addWidget(self.table, 1)
        v.addWidget(QLabel(
            "<span style='background:#ffcdcd;color:#111'>&nbsp;Excluded"
            "&nbsp;</span> <span style='background:#ff9d9d;color:#111'>"
            "&nbsp;<b>ONLY this bidder excludes it</b>&nbsp;</span> "
            "<span style='background:#cdf0cd;color:#111'>&nbsp;Included"
            "&nbsp;</span> <span style='background:#f2f2f2;color:#111'>"
            "&nbsp;Not stated&nbsp;</span>  Each cell shows the bidder's "
            "own words; double-click an excluded cell to see it in "
            "the bidder's proposal. Similar wordings share a row: "
            "right-click to split one off or merge two rows."))

    # ------------------------------------------------------------- data
    def set_bids(self, bids, moves=None):
        self.bids = list(bids or [])
        self.moves = dict(moves or {})
        self.fill()

    def bidders(self):
        out = []
        for b in self.bids:
            if b["bidder"] not in out:
                out.append(b["bidder"])
        return out

    def fill(self):
        self.rows = ex.matrix(self.bids, self.moves)
        names = self.bidders()
        t = self.table
        t.setColumnCount(1 + len(names))
        t.setHorizontalHeaderLabels(["Exclusion"] + names)
        t.setRowCount(len(self.rows))
        bold = QFont()
        bold.setBold(True)
        for r, row in enumerate(self.rows):
            it = QTableWidgetItem(row["label"])
            if len(row["wordings"]) > 1:
                it.setToolTip("Wordings in this row:\n" +
                              "\n".join(row["wordings"]))
            t.setItem(r, 0, it)
            for k, n in enumerate(names):
                cell = row["cells"][n]
                only = row["only"] == n
                text = ex.cell_text(cell)
                if only:
                    text = "ONLY ONE - " + text
                c = QTableWidgetItem(text)
                c.setBackground(ONLY if only else COLORS[cell["state"]])
                c.setForeground(INK)
                if only:
                    c.setFont(bold)
                c.setData(Qt.UserRole, (r, n))
                t.setItem(r, 1 + k, c)
        h = t.horizontalHeader()
        h.setSectionResizeMode(QHeaderView.Stretch)
        t.resizeRowsToContents()
        n_only = sum(1 for r in self.rows if r["only"])
        if not self.rows:
            self.note.setText("No exclusions were read from these bids.")
        else:
            self.note.setText(
                f"{len(self.rows)} exclusion(s) across {len(names)} "
                f"bidder(s); {n_only} excluded by one bidder only." if
                len(names) >= 2 else f"{len(self.rows)} exclusion(s).")
        return self.rows

    # ---------------------------------------------------------- changes
    def _set_moves(self, moves):
        self.moves = moves
        self.fill()
        self.moves_changed.emit(dict(moves))

    def split(self, wording):
        self._set_moves(ex.split(self.moves, wording))

    def merge(self, row, into):
        self._set_moves(ex.merge(self.moves, row, into))

    def automatic(self, row):
        m = dict(self.moves)
        for w in row["wordings"]:
            m = ex.unmove(m, w)
        self._set_moves(m)

    def _menu(self, pos):
        idx = self.table.indexAt(pos)
        if idx.row() < 0 or idx.row() >= len(self.rows):
            return
        row = self.rows[idx.row()]
        m = QMenu(self)
        if idx.column() >= 1:
            n = self.bidders()[idx.column() - 1]
            cell = row["cells"][n]
            if cell["state"] == ex.EXCLUDED:
                for w in cell["texts"]:
                    if self.action:
                        m.addAction(f"{self.action[0]} ({n}: {w[:40]})",
                                    lambda n=n, w=w: self.action[1](n, w))
                    if self.source:
                        m.addAction(f"Show where {n} says this",
                                    lambda n=n, w=w: self.source(n, w))
                m.addSeparator()
        if len(row["wordings"]) > 1:
            for w in row["wordings"]:
                m.addAction(f"Split off: {w[:50]}",
                            lambda w=w: self.split(w))
        others = [r for r in self.rows if r is not row]
        if others:
            m.addAction("Merge this row into…", lambda: self._ask_merge(row))
        if any(ex.norm(w) in self.moves for w in row["wordings"]):
            m.addAction("Back to automatic grouping",
                        lambda: self.automatic(row))
        if not m.isEmpty():
            m.exec(self.table.viewport().mapToGlobal(pos))

    def _open(self, r, c):
        """Double-click an excluded cell: show where the bidder says it."""
        if not self.source or c < 1 or not 0 <= r < len(self.rows):
            return None
        n = self.bidders()[c - 1]
        cell = self.rows[r]["cells"][n]
        if cell["state"] != ex.EXCLUDED:
            return None
        return self.source(n, cell["texts"][0])

    def _ask_merge(self, row):
        others = [r for r in self.rows if r is not row]
        name, ok = QInputDialog.getItem(
            self, "Exclusions", f"Merge \"{row['label']}\" into:",
            [r["label"] for r in others], 0, False)
        if ok and name:
            self.merge(row, next(r for r in others if r["label"] == name))

    # ----------------------------------------------------------- export
    def table_rows(self):
        return ex.table(self.bids, self.moves)

    def export(self, path=None, title="Exclusions"):
        if path is None:
            path, _ = QFileDialog.getSaveFileName(
                self, "Export Exclusions", f"{title}.xlsx", "Excel (*.xlsx)")
        if not path:
            return None
        from . import acrobat
        acrobat.write_xlsx(path, [("Exclusions", self.table_rows())])
        return path


class ExclusionsDialog(QDialog):
    def __init__(self, parent=None, title="Exclusions", action=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(980, 520)
        v = QVBoxLayout(self)
        self.panel = ExclusionsPanel(self, action)
        v.addWidget(self.panel, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        b = bb.addButton("Export to Excel…", QDialogButtonBox.ActionRole)
        b.clicked.connect(lambda: self.panel.export(title=title))
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
