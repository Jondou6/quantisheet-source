"""Small shared widgets: read-only tables, money cells, a job picker."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QLabel,
                               QMessageBox, QTableWidget, QTableWidgetItem)

from .. import cents


def money(c) -> str:
    return cents.fmt(c or 0)


def table(headers, rows=(), money_cols=()) -> QTableWidget:
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    t.verticalHeader().setVisible(False)
    fill(t, rows, money_cols)
    return t


def fill(t: QTableWidget, rows, money_cols=()) -> None:
    t.setRowCount(0)
    for r in rows:
        i = t.rowCount()
        t.insertRow(i)
        for j, v in enumerate(r):
            text = money(v) if j in money_cols else ("" if v is None else str(v))
            it = QTableWidgetItem(text)
            if j in money_cols:
                it.setTextAlignment(Qt.AlignmentFlag.AlignRight |
                                    Qt.AlignmentFlag.AlignVCenter)
            t.setItem(i, j, it)
    t.resizeColumnsToContents()


def heading(text) -> QLabel:
    lab = QLabel(text)
    f = lab.font()
    f.setPointSize(f.pointSize() + 3)
    f.setBold(True)
    lab.setFont(f)
    return lab


def job_picker(office) -> QComboBox:
    cb = QComboBox()
    for j in office.db.rows("SELECT id, number, name FROM jobs WHERE "
                            "deleted = 0 ORDER BY number"):
        cb.addItem(f"{j['number']} {j['name']}", j["id"])
    return cb


def error(parent, text) -> None:
    QMessageBox.warning(parent, "QuantiSheet Back Office", str(text))
