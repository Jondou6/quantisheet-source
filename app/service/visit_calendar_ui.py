"""Agreement visit calendar (Nov 5): a month of planned maintenance
visits from every active agreement - done, work order open, due with no
work order yet, or upcoming. open_window(parent) shows it."""
import datetime as dt

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QBrush, QColor, QTextCharFormat
from PySide6.QtWidgets import QCalendarWidget, QHBoxLayout, QLabel

from . import agreements, uiutil, workorder

COLORS = {"done": "#2e7d32", "open": "#1565c0", "due": "#c62828",
          "upcoming": "#6d4c41"}


class VisitCalendarWindow(uiutil.Desk):
    def __init__(self, parent=None, today=None):
        super().__init__("Agreement Visit Calendar", parent)
        self.today = today or dt.date.today()
        self.cal = QCalendarWidget()
        self.cal.setGridVisible(True)
        self.cal.setAccessibleName("Visit calendar")
        self.cal.setSelectedDate(QDate(self.today.year, self.today.month,
                                       self.today.day))
        self.cal.currentPageChanged.connect(lambda *_: self.reload())
        self.cal.selectionChanged.connect(self.show_day)
        self.key = QLabel("  ".join(
            f'<span style="color:{COLORS[s]}">&#9632;</span> '
            f'{agreements.STATE_TEXT[s]}' for s in agreements.STATES))
        self.key.setTextFormat(Qt.RichText)
        top = QHBoxLayout()
        top.addWidget(self.cal, 1)
        self.root.addLayout(top)
        self.root.addWidget(self.key)
        self.buttons(("Create due visits", self.due_clicked),
                     ("Today", self.go_today))
        self.table = uiutil.table(["Date", "Customer", "Site", "Agreement",
                                   "Status", "Work order"])
        self.table.setAccessibleName("Visits this month")
        self.root.addWidget(self.table, 1)
        self.finish()
        self._marked = []
        self.reload()

    def month(self):
        return agreements.month_range(self.cal.yearShown(),
                                      self.cal.monthShown())

    def reload(self):
        self.store = agreements.load()
        self.orders = workorder.load()
        since, until = self.month()
        self.visits = agreements.visit_calendar(
            self.store, self.orders, since, until, today=self.today)
        for d in self._marked:                     # clear last month's marks
            self.cal.setDateTextFormat(d, QTextCharFormat())
        self._marked = []
        worst = {}
        rank = {"due": 0, "open": 1, "upcoming": 2, "done": 3}
        for v in self.visits:
            s = worst.get(v["date"])
            if s is None or rank[v["state"]] < rank[s]:
                worst[v["date"]] = v["state"]
        for day, state in worst.items():
            qd = QDate.fromString(day, "yyyy-MM-dd")
            f = QTextCharFormat()
            f.setFontWeight(700)
            f.setForeground(QBrush(QColor(COLORS[state])))
            n = sum(1 for v in self.visits if v["date"] == day)
            f.setToolTip(f"{n} visit(s): {agreements.STATE_TEXT[state]}")
            self.cal.setDateTextFormat(qd, f)
            self._marked.append(qd)
        self.fill(self.visits)
        counts = {s: sum(1 for v in self.visits if v["state"] == s)
                  for s in agreements.STATES}
        self.msg.setText(
            f"{len(self.visits)} visit(s) this month: " + ", ".join(
                f"{counts[s]} {agreements.STATE_TEXT[s].lower()}"
                for s in agreements.STATES if counts[s]) if self.visits
            else "No agreement visits this month.")

    def fill(self, visits):
        uiutil.fill(self.table, [
            [v["date"], v["customer"], v["site"], v["number"],
             agreements.STATE_TEXT[v["state"]], v["work_order"]]
            for v in visits], [v["agreement_id"] for v in visits])

    def show_day(self):
        day = self.cal.selectedDate().toString("yyyy-MM-dd")
        on = [v for v in self.visits if v["date"] == day]
        self.fill(on or self.visits)

    def go_today(self):
        self.cal.setSelectedDate(QDate(self.today.year, self.today.month,
                                       self.today.day))
        self.cal.showSelectedDate()
        self.reload()

    def due_clicked(self):
        from ..estimating import service as records_api
        ids = self.guard(lambda: agreements.create_due_work_orders(
            self.store, self.orders, records_api.load(), today=self.today))
        if ids is None:
            return None
        workorder.save(self.orders)
        self.reload()
        self.msg.setText(f"{len(ids)} planned visit(s) opened. " +
                         self.msg.text())
        return ids


def open_window(parent=None):
    return uiutil.show(VisitCalendarWindow(parent))
