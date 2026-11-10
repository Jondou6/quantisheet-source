"""Tools > Time Log: the window (logic: timelog.py)."""
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox,
                               QFileDialog, QHeaderView, QLabel,
                               QTableWidget, QTableWidgetItem, QVBoxLayout)

from . import timelog
from .dmoney import c2 as _c2


class TimeLogDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Time Log")
        self.resize(820, 520)
        lay = QVBoxLayout(self)
        lg = getattr(parent, "_timelog", None)
        if lg is not None:
            lg.flush()
        lay.addWidget(QLabel(
            "Active time on each job and sheet, counted while you work in "
            "it (it pauses after 2 minutes without the mouse or keyboard). "
            "Takeoff = a measuring or counting tool in use. Kept on this "
            "computer only."))
        self.on = QCheckBox("Keep a time log")
        self.on.setChecked(timelog.enabled())
        self.on.toggled.connect(self._toggle)
        lay.addWidget(self.on)
        tot = timelog.totals()
        self.jobs = QTableWidget(len(tot), 4)
        self.jobs.setHorizontalHeaderLabels(["Job", "Takeoff (h)",
                                             "Review / estimating (h)",
                                             "Total (h)"])
        for i, (name, t) in enumerate(sorted(tot.items())):
            for c, v in enumerate((name, f"{_c2(t['takeoff_min'] / 60):.2f}",
                                   f"{_c2(t['review_min'] / 60):.2f}",
                                   f"{_c2(t['total_min'] / 60):.2f}")):
                self.jobs.setItem(i, c, QTableWidgetItem(v))
        self.jobs.verticalHeader().hide()
        self.jobs.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeToContents)
        lay.addWidget(self.jobs)
        rows = timelog.rows()
        self.detail = QTableWidget(len(rows), 5)
        self.detail.setHorizontalHeaderLabels(["Job", "Day", "Sheet",
                                               "Takeoff (min)",
                                               "Total (min)"])
        for i, r in enumerate(rows):
            for c, v in enumerate((r["name"], r["day"], r["sheet"],
                                   f"{r['takeoff_min']:.1f}",
                                   f"{r['total_min']:.1f}")):
                self.detail.setItem(i, c, QTableWidgetItem(v))
        self.detail.verticalHeader().hide()
        lay.addWidget(self.detail, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        ex = bb.addButton("Export CSV…", QDialogButtonBox.ActionRole)
        ex.clicked.connect(lambda: self.export())
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _toggle(self, on):
        from . import settings
        settings.set(timelog.S_ON, bool(on))

    def export(self, path=None):
        if path is None:
            path, _ = QFileDialog.getSaveFileName(self, "Time Log",
                                                  "Time Log.csv",
                                                  "CSV (*.csv)")
            if not path:
                return None
        return timelog.export_csv(path)
