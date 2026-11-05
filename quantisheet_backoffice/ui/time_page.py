"""Time page (r38 G2.4): enter and correct time, submit it for approval,
import QuantiSheet time cards and turn a day's punches into Draft time.
Per diem (r38 G2.1) sits under the time list: set a job's rate (none is
shipped), make per diem from time, add one by hand, submit and approve.

Everything goes through timeentry / remote (permissions, week lock, final
payroll and approvals are theirs); the page only collects the fields.
Messages and errors are shown on the page, never in a modal box."""
from PySide6.QtWidgets import (QComboBox, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QWidget)

from .. import cents, clock, jobs, perdiem, remote, timeentry
from .common import fill, heading, job_picker, table

HEADERS = ["Date", "Worker", "Job", "Cost code", "Pay type", "Hours",
           "Status", "Source"]
LIMIT = 500
PD_HEADERS = ["Date", "Worker", "Job", "Cost code", "Kind", "Amount",
              "Status", "Source"]


class TimePage(QWidget):
    def __init__(self, office, parent=None):
        super().__init__(parent)
        from PySide6.QtWidgets import QVBoxLayout
        self.office = office
        self.lay = QVBoxLayout(self)
        self.lay.addWidget(heading("Time"))
        form_w = QWidget()
        form = QFormLayout(form_w)
        self.worker = QComboBox()
        for w in office.db.rows("SELECT id, name FROM workers WHERE active = 1"
                                " AND deleted = 0 ORDER BY name"):
            self.worker.addItem(w["name"], w["id"])
        self.date = QLineEdit(clock.today().isoformat())
        self.job = job_picker(office)
        self.code = QComboBox()
        self.code.setEditable(True)
        self.pay_type = QComboBox()
        self.pay_type.addItems(list(timeentry.PAY_TYPES))
        self.hours = QLineEdit("8")
        form.addRow("Worker", self.worker)
        form.addRow("Date (YYYY-MM-DD)", self.date)
        form.addRow("Job", self.job)
        form.addRow("Cost code", self.code)
        form.addRow("Pay type", self.pay_type)
        form.addRow("Hours", self.hours)
        self.lay.addWidget(form_w)
        self.job.currentIndexChanged.connect(self._fill_codes)
        self._fill_codes()
        row = QHBoxLayout()
        can = office.can("time.edit")
        self.add_btn = self._button("Add Line", self._add_from_form, row, can)
        self.edit_btn = self._button("Change Selected", self._edit_from_form,
                                     row, can)
        self.submit_btn = self._button("Submit Selected", self.submit_selected,
                                       row, can)
        self.import_btn = self._button("Import QuantiSheet Time Cards",
                                       self.import_timecards, row, can)
        self.punch_btn = self._button("Convert Punches to Time",
                                      self.convert_punches, row, can)
        self.lay.addLayout(row)
        self.msg = QLabel("" if can else
                          "Time entry needs the time.edit permission.")
        self.msg.setWordWrap(True)
        self.lay.addWidget(self.msg)
        self.grid = table(HEADERS)
        self.lay.addWidget(self.grid, 3)
        self._per_diem_panel(office, can)
        self.refresh()

    def _per_diem_panel(self, office, can):
        self.lay.addWidget(heading("Per diem"))
        prow = QHBoxLayout()
        prow.addWidget(QLabel("Amount $"))
        self.pd_amount = QLineEdit("")          # no default: none is shipped
        self.pd_amount.setPlaceholderText("per day, e.g. 0.00")
        self.pd_amount.setMaximumWidth(120)
        prow.addWidget(self.pd_amount)
        self.pd_kind = QComboBox()
        self.pd_kind.addItems(list(perdiem.KINDS))
        prow.addWidget(self.pd_kind)
        appr = office.can("time.approve")
        self.pd_rate_btn = self._button("Set Job Per Diem Rate",
                                        self._rate_from_form, prow, appr)
        self.pd_add_btn = self._button("Add Per Diem", self._pd_add_from_form,
                                       prow, can)
        self.pd_make_btn = self._button("Make Per Diem From Time (week)",
                                        self._make_from_form, prow, can)
        self.pd_submit_btn = self._button("Submit Selected Per Diem",
                                          self.submit_per_diem, prow, can)
        self.pd_approve_btn = self._button("Approve Selected Per Diem",
                                           self.approve_per_diem, prow, appr)
        self.lay.addLayout(prow)
        self.pd_grid = table(PD_HEADERS)
        self.lay.addWidget(self.pd_grid, 2)

    # ---- widgets -------------------------------------------------------
    def _button(self, text, slot, row, enabled):
        b = QPushButton(text)
        b.setProperty("r38_slot", slot.__name__)
        b.clicked.connect(self._clicked)
        b.setEnabled(enabled)
        row.addWidget(b)
        return b

    def _clicked(self, *_):
        b = self.sender()
        if b is not None:
            self._run(getattr(self, b.property("r38_slot")))

    def _run(self, slot):
        try:
            slot()
        except Exception as e:                            # noqa: BLE001
            self.msg.setText(f"Not done: {e}")

    def _fill_codes(self, *_):
        # also called while Qt tears the combo boxes down (its model goes
        # first and the index changes to -1): then there is nothing to fill
        if self.job.currentIndex() < 0:
            return
        try:
            cur = self.code.currentText()
            self.code.clear()
            self.code.addItems(sorted(jobs.cost_codes(
                self.office, self.job.currentData())))
        except (RuntimeError, AttributeError):        # widget already gone
            return
        if cur:
            self.code.setCurrentText(cur)

    def refresh(self):
        self.rows = self.office.db.rows(
            "SELECT t.id, t.date, w.name, j.number AS job, t.cost_code, "
            "t.pay_type, t.hours, t.status, t.source FROM time_lines t "
            "JOIN workers w ON w.id = t.worker_id LEFT JOIN jobs j ON "
            "j.id = t.job_id WHERE t.deleted = 0 ORDER BY t.date DESC, "
            f"t.id DESC LIMIT {LIMIT}")
        fill(self.grid, [(r["date"], r["name"], r["job"], r["cost_code"],
                          r["pay_type"], cents.hours_text(r["hours"] or 0),
                          r["status"], r["source"]) for r in self.rows])

        self.pd_rows = perdiem.lines(self.office, LIMIT)
        fill(self.pd_grid, [(r["date"], r["worker"], r["job"], r["cost_code"],
                             r["kind"], cents.text(r["amount"] or 0),
                             r["status"], r["source"]) for r in self.pd_rows])

    # ---- actions ---------------------------------------------------------
    def add_line(self, worker_id, date, job_id, cost_code, pay_type, hours):
        if worker_id is None:
            raise ValueError("Pick a worker.")
        if job_id is None:
            raise ValueError("Pick a job.")
        lid = timeentry.add_line(self.office, worker_id, clock.d(date)
                                 .isoformat(), job_id, cost_code.strip(),
                                 hours, pay_type)
        self.refresh()
        self.msg.setText(f"Added {pay_type} {cents.hours_text(cents.hours(hours))}"
                         f" h on {date}.")
        return lid

    def _add_from_form(self):
        self.add_line(self.worker.currentData(), self.date.text().strip(),
                      self.job.currentData(), self.code.currentText(),
                      self.pay_type.currentText(), self.hours.text().strip())

    def select_line(self, line_id):
        for i, r in enumerate(self.rows):
            if r["id"] == line_id:
                self.grid.selectRow(i)
                return
        raise ValueError("That line isn't in the list.")

    def _selected(self):
        rows = sorted({ix.row() for ix in self.grid.selectedIndexes()})
        if not rows:
            r = self.grid.currentRow()
            rows = [r] if r >= 0 else []
        ids = [self.rows[r]["id"] for r in rows if 0 <= r < len(self.rows)]
        if not ids:
            raise ValueError("Select a line first.")
        return ids

    def edit_selected(self, hours=None, pay_type=None, cost_code=None):
        fields = {k: v for k, v in (("hours", hours), ("pay_type", pay_type),
                                    ("cost_code", cost_code)) if v}
        if fields.get("pay_type") and \
                fields["pay_type"] not in timeentry.PAY_TYPES:
            raise ValueError("Unknown pay type.")
        ids = self._selected()
        for lid in ids:
            timeentry.edit_line(self.office, lid, **fields)
        self.refresh()
        self.msg.setText(f"Changed {len(ids)} line(s).")

    def _edit_from_form(self):
        self.edit_selected(hours=self.hours.text().strip(),
                           pay_type=self.pay_type.currentText(),
                           cost_code=self.code.currentText().strip())

    def submit_selected(self):
        ids = self._selected()
        timeentry.submit(self.office, ids)
        self.refresh()
        self.msg.setText(f"Submitted {len(ids)} line(s) for approval.")

    def import_timecards(self):
        jid = self.job.currentData()
        if jid is None:
            raise ValueError("Pick a job.")
        ids = timeentry.import_timecards(self.office, jid)
        self.refresh()
        self.msg.setText(f"Imported {len(ids)} time line(s) from QuantiSheet "
                         "time cards (Draft). Cards imported before add "
                         "nothing.")

    def convert_punches(self):
        d = clock.d(self.date.text().strip()).isoformat()
        ids = remote.punches_to_time_for_day(self.office, d)
        self.refresh()
        self.msg.setText(f"Made {len(ids)} Draft time line(s) from the "
                         f"punches on {d}.")

    # ---- per diem (r38 G2.1) ---------------------------------------------
    def set_rate(self, job_id, amount, cost_code=""):
        if job_id is None:
            raise ValueError("Pick a job.")
        perdiem.set_job_rate(self.office, job_id, amount, cost_code.strip())
        self.msg.setText(f"Per diem rate for the job set to ${amount} a day "
                         f"(cost code {cost_code.strip() or 'from time'}).")

    def _rate_from_form(self):
        self.set_rate(self.job.currentData(), self.pd_amount.text().strip(),
                      self.code.currentText())

    def add_per_diem(self, worker_id, date, job_id, cost_code, amount=None,
                     kind="Per diem"):
        if worker_id is None:
            raise ValueError("Pick a worker.")
        if job_id is None:
            raise ValueError("Pick a job.")
        pid = perdiem.add(self.office, worker_id, clock.d(date).isoformat(),
                          job_id, cost_code.strip(), amount or None, kind)
        self.refresh()
        self.msg.setText(f"Added a {kind.lower()} on {date} (Draft).")
        return pid

    def _pd_add_from_form(self):
        self.add_per_diem(self.worker.currentData(), self.date.text().strip(),
                          self.job.currentData(), self.code.currentText(),
                          self.pd_amount.text().strip() or None,
                          self.pd_kind.currentText())

    def make_per_diem(self, date_from, date_to):
        ids = perdiem.from_time(self.office, clock.d(date_from).isoformat(),
                                clock.d(date_to).isoformat())
        self.refresh()
        extra = ""
        if not ids and not self.office.db.scalar(
                "SELECT COUNT(*) FROM per_diem_rates WHERE deleted = 0"):
            extra = " No job has a per diem rate set yet."
        self.msg.setText(f"Made {len(ids)} Draft per diem line(s) from time "
                         f"{date_from} to {date_to}.{extra}")
        return ids

    def _make_from_form(self):
        from datetime import timedelta
        we = clock.d(jobs.week_ending(self.date.text().strip()))
        self.make_per_diem((we - timedelta(days=6)).isoformat(), we.isoformat())

    def select_per_diem(self, pid):
        for i, r in enumerate(self.pd_rows):
            if r["id"] == pid:
                self.pd_grid.selectRow(i)
                return
        raise ValueError("That per diem isn't in the list.")

    def _pd_selected(self):
        rows = sorted({ix.row() for ix in self.pd_grid.selectedIndexes()})
        if not rows:
            r = self.pd_grid.currentRow()
            rows = [r] if r >= 0 else []
        ids = [self.pd_rows[r]["id"] for r in rows if 0 <= r < len(self.pd_rows)]
        if not ids:
            raise ValueError("Select a per diem line first.")
        return ids

    def submit_per_diem(self):
        ids = self._pd_selected()
        perdiem.submit(self.office, ids)
        self.refresh()
        self.msg.setText(f"Submitted {len(ids)} per diem line(s) for approval.")

    def approve_per_diem(self):
        ids = self._pd_selected()
        perdiem.decide(self.office, ids, "approve")
        self.refresh()
        self.msg.setText(f"Approved {len(ids)} per diem line(s) (or passed "
                         "them to the next approver).")
