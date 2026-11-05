"""Phase 2 pages: Payroll (P2-01..P2-03), People (P2-04..P2-07),
Field (P2-08 punches, P2-10) and Cards (P2-09)."""
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QLabel, QPushButton,
                               QTabWidget, QVBoxLayout, QWidget)

from .. import (cards, cents, certified, certs, field, hr, office as
                office_mod, payroll, provider, pto, remote)
from .common import error, fill, heading, job_picker, money, table


class _Page(QWidget):
    def __init__(self, office, parent=None):
        super().__init__(parent)
        self.office = office
        self.lay = QVBoxLayout(self)

    def button(self, text, slot, perm=None, row=None):
        b = QPushButton(text)
        b.clicked.connect(lambda *_: self._run(slot))
        if perm:
            b.setEnabled(self.office.can(perm))
        (row or self.lay).addWidget(b)
        return b

    def _run(self, slot):
        try:
            slot()
        except Exception as e:                            # noqa: BLE001
            error(self, e)


def _h(v):
    return cents.hours_text(v or 0)


class PayrollPage(_Page):
    """Pay periods, Payroll Preview, provider export/import, certified
    payroll. Gross pay only: no tax withholding, filing or payments."""

    def __init__(self, office, parent=None):
        super().__init__(office, parent)
        self.lay.addWidget(heading("Payroll"))
        self.lay.addWidget(QLabel(
            "Gross pay from approved time, for your licensed payroll "
            "provider. Back Office does not withhold or file taxes or move "
            "money."))
        if not office.can("payroll.run"):
            self.lay.addWidget(QLabel("Payroll is for Payroll/HR, Controller "
                                      "and Admin users."))
            self.lay.addStretch(1)
            return
        self.periods = table(["Start", "End", "Pay date", "Status"],
                             [(p["start"], p["end"], p["pay_date"],
                               p["status"]) for p in self._periods()])
        self.lay.addWidget(self.periods)
        self.preview_grid = table(["Worker", "Emp no.", "REG h", "OT h",
                                   "DT h", "PTO h", "Gross", "Fringe cash",
                                   "Fringe plan", "Exceptions"])
        self.lay.addWidget(self.preview_grid)
        self.rule = QLabel("")
        self.lay.addWidget(self.rule)
        row = QHBoxLayout()
        self.button("Preview", self.preview, row=row)
        self.button("Finalize", self.finalize, "payroll.run", row=row)
        self.button("Export to provider…", self.export, "payroll.export",
                    row=row)
        self.button("Import provider register…", self.import_register,
                    "payroll.export", row=row)
        self.lay.addLayout(row)
        self.lay.addWidget(QLabel("Certified payroll: pick a job and the "
                                  "period row, then Print."))
        crow = QHBoxLayout()
        self.job = job_picker(office)
        crow.addWidget(self.job)
        self.button("Check / print certified payroll", self.certified,
                    "certified.edit", row=crow)
        self.lay.addLayout(crow)
        self.cp_msg = QLabel("")
        self.lay.addWidget(self.cp_msg)
        if self.periods.rowCount():
            self.periods.selectRow(self.periods.rowCount() - 1)
            self.preview()

    def _periods(self):
        return self.office.db.rows("SELECT * FROM pay_periods WHERE deleted = "
                                   "0 ORDER BY start")

    def _pid(self):
        ps = self._periods()
        r = self.periods.currentRow()
        if not ps:
            raise ValueError("Add a pay period first.")
        return ps[r if 0 <= r < len(ps) else -1]["id"]

    def preview(self):
        pv = payroll.preview(self.office, self._pid())
        fill(self.preview_grid, [
            (w["name"], w["employee_no"], _h(w["hours"]["REG"]),
             _h(w["hours"]["OT"]), _h(w["hours"]["DT"]),
             _h(w["hours"]["PTO"]), w["gross"], w["fringe_cash"],
             w["fringe_plan"], "; ".join(w["exceptions"]))
            for w in pv["workers"]], money_cols=(6, 7, 8))
        self.rule.setText(pv["rule"] + ("\n" + "\n".join(pv["exceptions"])
                                        if pv["exceptions"] else ""))
        return pv

    def finalize(self):
        payroll.finalize(self.office, self._pid())
        self.preview()

    def export(self):
        maps = self.office.db.rows("SELECT id FROM provider_maps WHERE "
                                   "deleted = 0 ORDER BY id")
        mid = maps[0]["id"] if maps else provider.add_map(self.office,
                                                          "Generic CSV")
        out = provider.export(self.office, self._pid(), mid)
        pd = out.get("non_wage_amount") or 0          # r38 G2.3
        extra = (f" Includes per diem {cents.fmt(pd)} as a non-wage line "
                 f"(not in gross).") if pd else ""
        self.rule.setText(f"Saved {out['path']} ({out['rows']} rows, "
                          f"{_h(out['hours'])} h). Upload it to your "
                          f"payroll provider.{extra}")

    def import_register(self):
        path, _ = QFileDialog.getOpenFileName(self, "Provider register", "",
                                              "CSV (*.csv)")
        if not path:
            return
        maps = self.office.db.rows("SELECT id FROM provider_maps WHERE "
                                   "deleted = 0 ORDER BY id")
        mid = maps[0]["id"] if maps else provider.add_map(self.office,
                                                          "Generic CSV")
        res = provider.import_register(self.office, self._pid(), mid,
                                       path=path)
        self.rule.setText(f"Imported {res['imported']}. " +
                          " ".join(res["unmatched"] + res["mismatches"]))

    def certified(self):
        p = payroll.period(self.office, self._pid())
        chk = certified.check(self.office, self.job.currentData(), p["end"])
        if chk["blocking"]:
            self.cp_msg.setText("Can't print: " + "; ".join(chk["blocking"]))
            return
        signers = self.office.db.rows("SELECT name FROM cp_signers WHERE "
                                      "active = 1 AND deleted = 0")
        if not signers:
            self.cp_msg.setText("Set up a statement of compliance signer.")
            return
        rid = certified.create(self.office, self.job.currentData(), p["end"],
                               signers[0]["name"])
        self.cp_msg.setText(f"Printed {certified.report(self.office, rid)['file_path']}")


class PeoplePage(_Page):
    """Employees (masked), HR queue, certifications, PTO, self-service."""

    def __init__(self, office, parent=None):
        super().__init__(office, parent)
        self.lay.addWidget(heading("People"))
        if not office.can("hr.view"):
            self.lay.addWidget(QLabel("Employee records are for HR, payroll "
                                      "and office users."))
            self.lay.addStretch(1)
            return
        tabs = QTabWidget()
        self.lay.addWidget(tabs)
        # employees
        w = QWidget()
        v = QVBoxLayout(w)
        self.emps = hr.employees(office)
        self.grid = table(["Name", "Emp no.", "Status", "Class", "Hire date",
                           "SSN", "Bank", "I-9"],
                          [(e["name"], e["employee_no"], e["status"],
                            e["labor_class"], e["hire_date"], e["ssn"],
                            e["bank_account"], e["i9_status"])
                           for e in self.emps])
        v.addWidget(self.grid)
        self.revealed = QLabel("")
        v.addWidget(self.revealed)
        self.reveal_btn = self.button("Reveal SSN (logged)", self.reveal_ssn,
                                      "hr.reveal", row=v)
        tabs.addTab(w, "Employees")
        # HR queue
        w = QWidget()
        v = QVBoxLayout(w)
        q = hr.queue(office)
        self.changes = q["changes"]
        self.queue_grid = table(["Employee", "Change", "New value", "From"],
                                [(c["name"], c["field"], c["value"],
                                  c["source"]) for c in self.changes] +
                                [(o["name"], "onboarding packet", "",
                                  "desktop") for o in q["onboarding"]])
        v.addWidget(self.queue_grid)
        self.button("Approve selected change", self.approve_change,
                    "hr.approve", row=v)
        tabs.addTab(w, "HR queue")
        # certifications
        w = QWidget()
        v = QVBoxLayout(w)
        mx = certs.matrix(office)
        types = sorted({t for row in mx.values() for t in row})
        v.addWidget(table(["Employee"] + types,
                          [[n] + [mx[n].get(t, "") for t in types]
                           for n in sorted(mx)]))
        v.addWidget(QLabel("Expiring in 30 days:"))
        v.addWidget(table(["Employee", "Certification", "Expires", "Status"],
                          [(c["employee"], c["type"], c["expires"],
                            c["status"]) for c in certs.expiring(office)]))
        tabs.addTab(w, "Certifications")
        # PTO
        w = QWidget()
        v = QVBoxLayout(w)
        self.pto_reqs = pto.requests(office)
        self.pto_grid = table(["Employee", "From", "To", "Hours", "Source"],
                              [(r["name"], r["date_from"], r["date_to"],
                                _h(r["total"]), r["source"])
                               for r in self.pto_reqs])
        v.addWidget(self.pto_grid)
        self.button("Approve selected PTO", self.approve_pto, "pto.approve",
                    row=v)
        v.addWidget(table(["Employee", "Balance"], [
            (e["name"], pto.balance(office, e["id"])["text"])
            for e in self.emps if e.get("pto_policy_id")]))
        tabs.addTab(w, "PTO")
        # self-service
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(QLabel(
            "Optional self-service server (its own service; QuantiSheet's "
            "relay never carries HR data). Nothing is sent until you click."))
        self.remote_msg = QLabel("")
        v.addWidget(self.remote_msg)
        self.button("Publish to self-service", self.publish, "remote.sync",
                    row=v)
        self.button("Pull requests and punches", self.pull, "remote.sync",
                    row=v)
        tabs.addTab(w, "Self-service")

    def _sel(self, rows, grid):
        r = grid.currentRow()
        if not (0 <= r < len(rows)):
            raise ValueError("Select a row first.")
        return rows[r]

    def reveal_ssn(self):
        e = self._sel(self.emps, self.grid)
        self.revealed.setText(f"{e['name']}: "
                              f"{hr.reveal(self.office, e['id'], 'ssn')}")

    def approve_change(self):
        hr.decide_change(self.office, self._sel(self.changes,
                                                self.queue_grid)["id"],
                         "approve")

    def approve_pto(self):
        pto.decide(self.office, self._sel(self.pto_reqs, self.pto_grid)["id"],
                   "approve")

    def publish(self):
        r = remote.publish(self.office)
        self.remote_msg.setText(f"Published {r['accounts']} people, "
                                f"{r['stubs']} pay stubs, {r['jobs']} jobs.")

    def pull(self):
        r = remote.pull(self.office)
        self.remote_msg.setText(f"{r['changes']} changes, {r['pto']} PTO "
                                f"requests, {r['punches']} punches. " +
                                " ".join(r["problems"]))


class FieldPage(_Page):
    """Daily Log manpower vs approved hours, unit costs, punch exceptions."""

    def __init__(self, office, parent=None):
        super().__init__(office, parent)
        self.lay.addWidget(heading("Field"))
        self.job = job_picker(office)
        self.lay.addWidget(self.job)
        self.lay.addWidget(QLabel("Manpower from QuantiSheet daily logs vs "
                                  "approved hours"))
        self.man = table(["Date", "Log workers", "Log hours",
                          "Approved hours", "Flag"])
        self.lay.addWidget(self.man)
        self.lay.addWidget(QLabel("Unit cost by code (time card production)"))
        self.units = table(["Code", "Quantity", "Unit", "Actual", "Unit cost"])
        self.lay.addWidget(self.units)
        self.lay.addWidget(QLabel("Punch exceptions (accepted, for the "
                                  "approver)"))
        self.lay.addWidget(table(["Worker", "Punch", "Job", "Flags"], [
            (p["name"], p["when"], p["job_number"], "; ".join(p["flags"]))
            for p in remote.exceptions(office)]))
        self.job.currentIndexChanged.connect(self.refresh)
        self.refresh()

    def refresh(self):
        jid = self.job.currentData()
        if jid is None:
            return
        fill(self.man, [(r["date"], r["log_workers"],
                         _h(r["log_hours"]) if r["log_hours"] is not None
                         else "", _h(r["approved_hours"]), r["flag"])
                        for r in field.manpower(self.office, jid)])
        fill(self.units, [(u["code"], u["qty"], u["unit"], u["actual"],
                           u["text"]) for u in field.unit_costs(self.office,
                                                                jid)],
             money_cols=(3,))


class CardsPage(_Page):
    """Cards & cardholders, Match, Missing Receipts (P2-09)."""

    def __init__(self, office, parent=None):
        super().__init__(office, parent)
        self.lay.addWidget(heading("Cards"))
        if office.mode != "full":
            self.lay.addWidget(QLabel(
                "Card statements come in through Banking, part of "
                f"'{office_mod.MODES['full']}' (Settings > Accounting)."))
            self.lay.addStretch(1)
            return
        self.cards = cards.cards_list(office)
        self.lay.addWidget(table(["Card", "Last 4", "Cardholder"],
                                 [(c["name"], c["last4"], c["cardholder"])
                                  for c in self.cards]))
        self.msg = QLabel("")
        self.lay.addWidget(self.msg)
        self.button("Match receipts", self.match, "cards.edit")
        self.lay.addWidget(QLabel("Missing receipts"))
        self.lay.addWidget(table(["Date", "Merchant", "Amount", "Cardholder"],
                                 [(c["date"], c["payee"], -c["amount"],
                                   c["cardholder"])
                                  for c in (cards.missing(office)
                                            if self.cards else [])],
                                 money_cols=(2,)))

    def match(self):
        out = []
        for c in self.cards:
            m = cards.match(self.office, c["id"])
            out.append(f"{c['name']}: {len(m['auto'])} matched, "
                       f"{len(m['suggested'])} to review, "
                       f"{len(m['missing'])} missing")
        self.msg.setText("; ".join(out))
