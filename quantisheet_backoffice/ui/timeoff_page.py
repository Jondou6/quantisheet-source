"""Time Off page: stats, the team calendar, the requests table with search,
filter and sort, the request dialog (working days, holidays and the balance
after) and approve / decline / cancel - in the look of the Kargul calendar
design prototype (MIT, see THIRD_PARTY_NOTICES.txt)."""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (QComboBox, QDateEdit, QDialog,
                               QDialogButtonBox, QFormLayout, QFrame,
                               QHBoxLayout, QInputDialog, QLabel, QLineEdit,
                               QListWidget, QPushButton, QSplitter,
                               QVBoxLayout, QWidget)

from .. import cents, clock, hr, pto, timeoff
from .calendar_view import CalendarView
from .common import error, fill, heading, table

TINTS = ("rgba(0,164,117,0.12)", "rgba(248,140,47,0.12)",
         "rgba(23,139,232,0.12)")
STATUS_COLORS = {"Approved": "#00a475", "Pending": "#e07a1f",
                 "Rejected": "#ef4747", "Cancelled": "#757575"}
COLUMNS = (("Employee", "name"), ("From", "date_from"), ("To", None),
           ("Days", None), ("Hours", "total"), ("Status", "status"),
           ("Note", None))


def _h(v) -> str:
    return cents.hours_text(v or 0)


def _qd(d) -> QDate:
    d = clock.d(d)
    return QDate(d.year, d.month, d.day)


def _pd(q: QDate) -> date:
    return date(q.year(), q.month(), q.day())


class StatCard(QFrame):
    def __init__(self, tint, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"StatCard {{ background: {tint}; border-radius: "
                           "12px; }")
        v = QVBoxLayout(self)
        self.value = QLabel()
        f = self.value.font()
        f.setPointSizeF(f.pointSizeF() + 4)
        f.setBold(True)
        self.value.setFont(f)
        self.caption = QLabel()
        self.caption.setStyleSheet("color: #757575;")
        v.addWidget(self.value)
        v.addWidget(self.caption)

    def set(self, value, caption, tint=None):
        self.value.setText(value)
        self.caption.setText(caption)
        if tint:
            self.setStyleSheet(f"StatCard {{ background: {tint}; "
                               "border-radius: 12px; }")


class RequestDialog(QDialog):
    """Ask for time off: employee, first and last day, hours a day, note.
    The working days, hours and the balance after are shown as you type;
    OK stays off while the request can't be made."""

    def __init__(self, office, employees, employee_id=None, start=None,
                 end=None, parent=None):
        super().__init__(parent)
        self.office = office
        self.setWindowTitle("Request time off")
        form = QFormLayout(self)
        self.who = QComboBox()
        for e in employees:
            self.who.addItem(e["name"], e["id"])
        if employee_id:
            i = self.who.findData(employee_id)
            if i >= 0:
                self.who.setCurrentIndex(i)
        self.a = QDateEdit(_qd(start or clock.today()))
        self.b = QDateEdit(_qd(end or start or clock.today()))
        for w in (self.a, self.b):
            w.setCalendarPopup(True)
            w.setDisplayFormat("ddd MMM d, yyyy")
        self.hpd = QLineEdit("8")
        self.note = QLineEdit()
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        form.addRow("Employee", self.who)
        form.addRow("First day", self.a)
        form.addRow("Last day", self.b)
        form.addRow("Hours a day", self.hpd)
        form.addRow("Note", self.note)
        form.addRow(self.summary)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText(
            "Send request")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        form.addRow(self.buttons)
        for w in (self.a, self.b):
            w.dateChanged.connect(self.update_summary)
        self.hpd.textChanged.connect(self.update_summary)
        self.who.currentIndexChanged.connect(self.update_summary)
        self.update_summary()

    def values(self):
        return (self.who.currentData(), _pd(self.a.date()),
                _pd(self.b.date()), self.hpd.text().strip() or "0",
                self.note.text().strip())

    def update_summary(self):
        eid, a, b, hpd, _n = self.values()
        ok = False
        if eid is None:
            text = "No employees with a PTO policy."
        else:
            try:
                p = timeoff.preview(self.office, eid, a, b, hpd)
                text = (f"{p['days']} working day(s), {_h(p['hours'])} h. "
                        f"Available {_h(p['available'])} h; after this "
                        f"request {_h(p['after'])} h.")
                if p["why"]:
                    text += "\n" + p["why"]
                ok = p["ok"]
            except Exception as e:                        # noqa: BLE001
                text = str(e)
        self.summary.setText(text)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(ok)


class HolidaysDialog(QDialog):
    def __init__(self, office, parent=None):
        super().__init__(parent)
        self.office = office
        self.setWindowTitle("Company holidays")
        v = QVBoxLayout(self)
        v.addWidget(QLabel("Holidays aren't working days: time off over a "
                           "holiday doesn't use PTO."))
        self.list = QListWidget()
        v.addWidget(self.list)
        row = QHBoxLayout()
        self.day = QDateEdit(_qd(clock.today()))
        self.day.setCalendarPopup(True)
        self.name = QLineEdit()
        self.name.setPlaceholderText("Holiday name")
        add = QPushButton("Add")
        rem = QPushButton("Remove selected")
        add.clicked.connect(self.add)
        rem.clicked.connect(self.remove)
        for w in (self.day, self.name, add, rem):
            row.addWidget(w)
        v.addLayout(row)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.reject)
        v.addWidget(close)
        self.refresh()

    def refresh(self):
        self.rows = timeoff.holidays(self.office)
        self.list.clear()
        for h in self.rows:
            self.list.addItem(f"{h['date']}  {h['name']}")

    def add(self):
        try:
            timeoff.add_holiday(self.office, _pd(self.day.date()),
                                self.name.text())
            self.name.clear()
        except Exception as e:                            # noqa: BLE001
            error(self, e)
        self.refresh()

    def remove(self):
        i = self.list.currentRow()
        if 0 <= i < len(self.rows):
            try:
                timeoff.remove_holiday(self.office, self.rows[i]["id"])
            except Exception as e:                        # noqa: BLE001
                error(self, e)
        self.refresh()


class TimeOffPage(QWidget):
    def __init__(self, office, parent=None, today=None):
        super().__init__(parent)
        self.office = office
        self.today = clock.d(today or clock.today())
        self.lay = QVBoxLayout(self)
        self.lay.addWidget(heading("Time off"))
        if not office.can("hr.view"):
            self.lay.addWidget(QLabel("Time off is for HR, payroll and office "
                                      "users."))
            self.lay.addStretch(1)
            self.ready = False
            return
        self.ready = True
        self.emps = [e for e in hr.employees(office)]
        top = QHBoxLayout()
        self.who = QComboBox()
        self.who.addItem("Whole team", None)
        for e in self.emps:
            self.who.addItem(e["name"], e["id"])
        self.who.currentIndexChanged.connect(self.refresh)
        top.addWidget(QLabel("Show"))
        top.addWidget(self.who)
        top.addStretch(1)
        self.request_btn = QPushButton("Request time off")
        self.request_btn.clicked.connect(lambda: self.new_request())
        self.request_btn.setEnabled(office.can("pto.edit"))
        self.holidays_btn = QPushButton("Holidays…")
        self.holidays_btn.clicked.connect(self.edit_holidays)
        self.holidays_btn.setEnabled(office.can("pto.edit"))
        self.yearend_btn = QPushButton("Year end…")
        self.yearend_btn.clicked.connect(lambda: self.show_year_end())
        self.report_btn = QPushButton("Print report…")
        self.report_btn.clicked.connect(lambda: self.print_report())
        top.addWidget(self.request_btn)
        top.addWidget(self.holidays_btn)
        top.addWidget(self.yearend_btn)
        top.addWidget(self.report_btn)
        self.lay.addLayout(top)
        cards = QHBoxLayout()
        self.cards = [StatCard(t) for t in TINTS]
        for c in self.cards:
            cards.addWidget(c)
        self.lay.addLayout(cards)
        split = QSplitter(Qt.Orientation.Vertical)
        self.cal = CalendarView(self._source, today=self.today)
        self.cal.rangeSelected.connect(self.new_request)
        self.cal.itemActivated.connect(self.show_item)
        split.addWidget(self.cal)
        low = QWidget()
        lv = QVBoxLayout(low)
        lv.setContentsMargins(0, 0, 0, 0)
        filt = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search name, note or status")
        self.search.textChanged.connect(self.refresh_table)
        self.status = QComboBox()
        self.status.addItem("All requests", None)
        for s in timeoff.STATUSES:
            self.status.addItem(s, s)
        self.status.currentIndexChanged.connect(self.refresh_table)
        filt.addWidget(self.search, 1)
        filt.addWidget(self.status)
        lv.addLayout(filt)
        self.sort_key, self.sort_desc = "date_from", True
        self.grid = table([c for c, _k in COLUMNS])
        self.grid.horizontalHeader().sectionClicked.connect(self.sort_by)
        self.grid.horizontalHeader().setStretchLastSection(True)
        lv.addWidget(self.grid)
        acts = QHBoxLayout()
        self.approve_btn = QPushButton("Approve")
        self.decline_btn = QPushButton("Decline")
        self.cancel_btn = QPushButton("Cancel request")
        self.approve_btn.clicked.connect(lambda: self.decide("approve"))
        self.decline_btn.clicked.connect(lambda: self.decide("reject"))
        self.cancel_btn.clicked.connect(self.cancel)
        self.approve_btn.setEnabled(office.can("pto.approve"))
        self.decline_btn.setEnabled(office.can("pto.approve"))
        self.cancel_btn.setEnabled(office.can("pto.edit"))
        for b in (self.approve_btn, self.decline_btn, self.cancel_btn):
            acts.addWidget(b)
        acts.addStretch(1)
        self.message = QLabel("")
        acts.addWidget(self.message)
        lv.addLayout(acts)
        split.addWidget(low)
        split.setSizes([420, 260])
        self.lay.addWidget(split, 1)
        self.refresh()

    # data -----------------------------------------------------------
    def employee_id(self):
        return self.who.currentData() if self.ready else None

    def _source(self, a, b):
        eid = self.employee_id() if hasattr(self, "who") else None
        return (timeoff.events(self.office, a, b, employee_id=eid),
                timeoff.day_hours(self.office, a, b, eid) if eid else {})

    def refresh(self):
        if not self.ready:
            return
        eid = self.employee_id()
        s = timeoff.stats(self.office, eid, today=self.today)
        if eid:
            vals = [f"{_h(s['available'])} h available",
                    f"{_h(s['pending'])} h pending",
                    f"{_h(s['upcoming'])} h upcoming"]
            caps = ["To book time off", "Awaiting approval",
                    "Approved, not yet taken"]
        else:
            vals = [f"{s['pending']} pending", f"{s['off_today']} off today",
                    f"{s['days_ahead']} days off"]
            caps = ["Requests awaiting approval", "People on time off today",
                    "Booked in the next 30 days"]
        # green = time you can take / is being taken, orange = waiting
        tints = TINTS if eid else (TINTS[1], TINTS[0], TINTS[2])
        for c, v, cap, t in zip(self.cards, vals, caps, tints):
            c.set(v, cap, t)
        self.cal.reload()
        self.refresh_table()

    def refresh_table(self):
        if not self.ready:
            return
        self.rows = timeoff.request_rows(
            self.office, status=self.status.currentData(),
            search=self.search.text(), employee_id=self.employee_id(),
            sort=self.sort_key, descending=self.sort_desc)
        fill(self.grid, [(r["name"], r["date_from"], r["date_to"], r["days"],
                          _h(r["total"]), r["status"], r["note"] or "")
                         for r in self.rows])
        from PySide6.QtGui import QColor
        for i, r in enumerate(self.rows):
            it = self.grid.item(i, 5)
            if it is not None:
                it.setForeground(QColor(STATUS_COLORS.get(r["status"],
                                                          "#1d1d1d")))

    def sort_by(self, col):
        key = COLUMNS[col][1]
        if not key:
            return
        if key == self.sort_key:
            self.sort_desc = not self.sort_desc
        else:
            self.sort_key, self.sort_desc = key, False
        self.refresh_table()

    def selected(self):
        r = self.grid.currentRow()
        if not (0 <= r < len(self.rows)):
            raise ValueError("Select a request first.")
        return self.rows[r]

    # actions --------------------------------------------------------
    def new_request(self, start=None, end=None, accept=None):
        """Open the request dialog (from the button, or a range dragged on
        the calendar). `accept` lets tests drive the dialog."""
        if not self.office.can("pto.edit"):
            return None
        emps = [e for e in self.emps if e.get("pto_policy_id")]
        dlg = RequestDialog(self.office, emps, self.employee_id(), start,
                            end, self)
        ok = accept(dlg) if accept else dlg.exec() == QDialog.DialogCode.Accepted
        if not ok:
            return None
        eid, a, b, hpd, note = dlg.values()
        try:
            rid = pto.request(self.office, eid, a, b, hpd, note=note)
        except Exception as e:                            # noqa: BLE001
            error(self, e)
            return None
        self.message.setText("Request sent.")
        self.refresh()
        return rid

    def decide(self, decision):
        try:
            r = self.selected()
            pto.decide(self.office, r["id"], decision)
            self.message.setText(f"{r['name']}: "
                                 f"{'approved' if decision == 'approve' else 'declined'}.")
        except Exception as e:                            # noqa: BLE001
            error(self, e)
        self.refresh()

    def cancel(self):
        try:
            r = self.selected()
            timeoff.cancel(self.office, r["id"])
            self.message.setText(f"{r['name']}: request cancelled.")
        except Exception as e:                            # noqa: BLE001
            error(self, e)
        self.refresh()

    def edit_holidays(self):
        HolidaysDialog(self.office, self).exec()
        self.refresh()

    def year_end_text(self, year=None):
        """The year-end carry-over as text (what the dialog shows)."""
        year = int(year or clock.d(self.today or clock.today()).year)
        rows = timeoff.year_end(self.office, year)
        if not rows:
            return f"No one has a time-off policy for {year}."
        lines = [f"Carry-over at the end of {year} (hours):", ""]
        for r in rows:
            lim = "no limit" if r["limit"] is None else \
                f"limit {_h(r['limit'])}"
            lines.append(f"{r['name']}: balance {_h(r['balance'])}, "
                         f"{lim} - carries {_h(r['carried'])}"
                         + (f", loses {_h(r['lost'])}" if r["lost"] else ""))
        return "\n".join(lines)

    def show_year_end(self, year=None):
        from PySide6.QtWidgets import QMessageBox
        text = self.year_end_text(year)
        QMessageBox.information(self, "Year end", text)
        return text

    def print_report(self, year=None, path=None):
        """The time-off report PDF; opens it when made from the button."""
        try:
            out = timeoff.report_pdf(
                self.office, year or clock.d(self.today or
                                             clock.today()).year,
                path=path, today=self.today)
        except Exception as e:                            # noqa: BLE001
            error(self, e)
            return None
        if path is None:
            try:
                from PySide6.QtCore import QUrl
                from PySide6.QtGui import QDesktopServices
                QDesktopServices.openUrl(QUrl.fromLocalFile(out))
            except Exception:                             # noqa: BLE001
                pass
        return out

    def show_item(self, it):
        if it.get("ref", (None,))[0] == "pto_request":
            for i, r in enumerate(self.rows):
                if r["id"] == it["ref"][1]:
                    self.grid.selectRow(i)
                    self.grid.setCurrentCell(i, 0)
                    return
            self.status.setCurrentIndex(0)
            self.search.clear()
            self.show_item(it) if any(r["id"] == it["ref"][1]
                                      for r in self.rows) else None
        else:
            self.message.setText(self.cal.tooltip(it).replace("\n", " · "))
