"""Tune-up planner window (1.2 phase 5, #7).

Pick spring or fall, the techs and how many tune-ups a tech does a day;
the plan spreads every agreement visit with no work order yet over the
workdays. Then make the planned-maintenance work orders and/or save an
.ics calendar file (saved only, never sent). open_window(parent).
"""
import datetime as dt

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (QComboBox, QDateEdit, QFileDialog,
                               QHBoxLayout, QLabel, QLineEdit, QSpinBox)

from ..estimating import service as records_api
from . import agreements, files, planner, uiutil, workorder


class PlannerWindow(uiutil.Desk):
    def __init__(self, parent=None, today=None):
        super().__init__("Tune-up Planner", parent)
        self.today = today or dt.date.today()
        self.rows = []
        top = QHBoxLayout()
        self.season = QComboBox()
        self.season.setAccessibleName("Season")
        self.season.addItem("Spring", "spring")
        self.season.addItem("Fall", "fall")
        self.start = QDateEdit()
        self.end = QDateEdit()
        for w, name in ((self.start, "Start"), (self.end, "End")):
            w.setCalendarPopup(True)
            w.setDisplayFormat("yyyy-MM-dd")
            w.setAccessibleName(name)
        self.techs = QLineEdit()
        self.techs.setPlaceholderText("Techs, separated by commas")
        self.techs.setAccessibleName("Techs")
        self.cap = QSpinBox()
        self.cap.setRange(1, 20)
        self.cap.setValue(planner.per_day())
        self.cap.setAccessibleName("Tune-ups per tech per day")
        for lbl, w in (("Season", self.season), ("From", self.start),
                       ("To", self.end), ("Techs", self.techs),
                       ("Per tech per day", self.cap)):
            top.addWidget(QLabel(lbl))
            top.addWidget(w, 2 if w is self.techs else 0)
        self.root.addLayout(top)
        self.buttons(("Plan", self.plan_clicked),
                     ("Make work orders", self.make_clicked),
                     ("Save calendar (.ics)…", self.ics_clicked))
        self.table = uiutil.table(["Date", "Tech", "Customer", "Site",
                                   "Agreement", "Visit planned for"])
        self.table.setAccessibleName("Tune-up plan")
        self.root.addWidget(self.table, 1)
        self.load_lbl = QLabel("")
        self.load_lbl.setWordWrap(True)
        self.root.addWidget(self.load_lbl)
        self.finish()
        self.season.currentIndexChanged.connect(self._season_changed)
        self.store = agreements.load()
        self.orders = workorder.load()
        self.techs.setText(", ".join(self.orders.get("techs", [])))
        self._season_changed()

    def _season_changed(self):
        year = self.today.year
        a, b = self.guard(lambda: planner.season_dates(
            self.season.currentData(), year)) or (self.today, self.today)
        if b < self.today:
            a, b = planner.season_dates(self.season.currentData(), year + 1)
        for w, d in ((self.start, a), (self.end, b)):
            w.setDate(QDate(d.year, d.month, d.day))

    def _dates(self):
        return (dt.date.fromisoformat(self.start.date().toString(
            "yyyy-MM-dd")), dt.date.fromisoformat(self.end.date().toString(
                "yyyy-MM-dd")))

    def plan_clicked(self):
        self.store = agreements.load()
        self.orders = workorder.load()
        start, end = self._dates()
        rows = self.guard(lambda: planner.plan(
            self.store, self.orders, self.techs.text().split(","), start,
            end, today=self.today, cap=self.cap.value()))
        if rows is None:
            return None
        self.rows = rows
        uiutil.fill(self.table, [[r["date"], r["tech"], r["customer"],
                                  r["site"], r["number"], r["planned"]]
                                 for r in rows])
        load = planner.weekly_load(rows)
        self.load_lbl.setText("Week of: " + "; ".join(
            f"{wk} {tech} {n}" for (wk, tech), n in sorted(load.items()))
            if load else "")
        self.msg.setText(f"{len(rows)} tune-up(s) planned." if rows else
                         "No agreement visits without a work order in "
                         "these dates.")
        return rows

    def make_clicked(self):
        if not self.rows:
            self.msg.setText("Plan first.")
            return None
        ids = self.guard(lambda: planner.make_work_orders(
            self.store, self.orders, self.rows, records_api.load(),
            today=self.today))
        if ids is None:
            return None
        workorder.save(self.orders)
        self.msg.setText(f"{len(ids)} planned-maintenance work order(s) "
                         "opened.")
        return ids

    def ics_clicked(self, _checked=False, path=None):
        if not self.rows:
            self.msg.setText("Plan first.")
            return None
        if path is None:
            path, _ = QFileDialog.getSaveFileName(
                self, "Tune-up calendar", files.path_for(
                    f"Tune-ups {self.season.currentText()}.ics"),
                "Calendar (*.ics)")
        if not path:
            return None
        got = self.guard(lambda: planner.save_ics(self.rows, path))
        if got:
            self.msg.setText(f"Saved {path} - import it into the calendar "
                             "you use. Nothing was sent.")
        return got


def open_window(parent=None):
    return uiutil.show(PlannerWindow(parent))
