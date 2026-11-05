import json
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QLineEdit, QLabel, QComboBox, QMessageBox, QHeaderView
)
from . import rules as rules_mod


class RulesDialog(QDialog):
    def __init__(self, view, parent=None):
        super().__init__(parent)
        self.view = view
        self.setWindowTitle("Auto-Markup Rules")
        self.resize(640, 420)
        layout = QVBoxLayout(self)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Pattern (regex)", "Mark", "Color"])
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch)
        layout.addWidget(self.table)

        for r in rules_mod.DEFAULT_RULES:
            self._add_row(r["pattern"], r["mark"], r["color"])

        nl = QHBoxLayout()
        nl.addWidget(QLabel("Natural language:"))
        self.nl = QLineEdit()
        self.nl.setPlaceholderText("e.g. underline every fire rating in red")
        self.nl.returnPressed.connect(self._from_nl)
        nl.addWidget(self.nl, 1)
        add = QPushButton("Add")
        add.clicked.connect(self._from_nl)
        nl.addWidget(add)
        layout.addLayout(nl)

        btns = QHBoxLayout()
        add_row = QPushButton("Add Row")
        add_row.clicked.connect(lambda: self._add_row("", "highlight", [1, 1, 0]))
        del_row = QPushButton("Remove Row")
        del_row.clicked.connect(
            lambda: self.table.removeRow(self.table.currentRow()))
        run = QPushButton("Apply to Document")
        run.clicked.connect(self._apply)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        btns.addWidget(add_row)
        btns.addWidget(del_row)
        btns.addStretch()
        btns.addWidget(run)
        btns.addWidget(close)
        layout.addLayout(btns)

    def _add_row(self, pattern, mark, color):
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(pattern))
        combo = QComboBox()
        combo.addItems(rules_mod.MARKS)
        combo.setCurrentText(mark)
        self.table.setCellWidget(row, 1, combo)
        self.table.setItem(row, 2, QTableWidgetItem(json.dumps(color)))

    def _from_nl(self):
        text = self.nl.text().strip()
        if not text:
            return
        r = rules_mod.parse_nl_rule(text)
        self._add_row(r["pattern"], r["mark"], r["color"])
        self.nl.clear()

    def _collect(self):
        out = []
        for row in range(self.table.rowCount()):
            pat = self.table.item(row, 0)
            if not pat or not pat.text().strip():
                continue
            mark = self.table.cellWidget(row, 1).currentText()
            try:
                color = json.loads(self.table.item(row, 2).text())
            except (ValueError, AttributeError):
                color = [1, 1, 0]
            out.append({"pattern": pat.text(), "mark": mark, "color": color})
        return out

    def _apply(self):
        marks = rules_mod.find_marks(self.view.doc, self._collect())
        n = self.view.apply_marks(marks)
        QMessageBox.information(self, "Rules", f"{n} marks applied")
