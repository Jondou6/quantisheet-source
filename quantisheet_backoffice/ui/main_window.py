"""QuantiSheet Back Office main window (P1-01): left navigation, one page
per area, status bar with the signed-in user and the last QuantiSheet
snapshot date. Pages are built when first opened and rebuilt on refresh."""
import os

from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox,
                               QFileDialog, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QMainWindow,
                               QPushButton, QStackedWidget, QTabWidget,
                               QVBoxLayout, QWidget)

from .. import (APP_NAME, __version__, ap, appay, approvals, cents, clock,
                fileguard, interface, jobcost, jobs, ledger, office as
                office_mod, payments, timeentry, waivers)
from .common import error, fill, heading, job_picker, money, table
from .exports_page import DropGuard, ExportsPage
from .time_page import TimePage          # r38 G2.4: the time-entry screen

NAV = ["Home", "Waiting on Me", "Assistant", "Time", "Payroll", "People",
       "Time Off", "Job Cost", "Job Cost Report", "Field", "Crew Board",
       "Pre-Task Plans", "Safety Meetings", "Incidents", "Equipment",
       "Warranty & Service Calls", "Checklist Templates",
       "Payables", "Cards", "Billing", "Payments & Aging", "Lien Waivers",
       "Exports", "Sync Center", "Books & Reports", "Payroll Key & Approvals",
       "Settings"]


class SignInDialog(QDialog):
    def __init__(self, office, parent=None):
        super().__init__(parent)
        self.office = office
        self.setWindowTitle(f"{APP_NAME} - sign in")
        lay = QFormLayout(self)
        self.email = QLineEdit()
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        lay.addRow("Email", self.email)
        lay.addRow("Password", self.password)
        self.msg = QLabel("")
        lay.addRow(self.msg)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                              QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.try_sign_in)
        bb.rejected.connect(self.reject)
        lay.addRow(bb)

    def try_sign_in(self):
        try:
            self.office.sign_in(self.email.text().strip(),
                                self.password.text())
        except Exception as e:                            # noqa: BLE001
            self.msg.setText(str(e))
            return False
        self.accept()
        return True


class Page(QWidget):
    def __init__(self, office, parent=None):
        super().__init__(parent)
        self.office = office
        self.lay = QVBoxLayout(self)


class HomePage(Page):
    def __init__(self, office, parent=None):
        super().__init__(office, parent)
        self.lay.addWidget(heading("Home"))
        o = office
        counts = [
            ("Approvals waiting on you (all kinds)",
             len(approvals.inbox(o)) if o.user else 0),
            ("AP invoices on compliance hold", o.db.scalar(
                "SELECT COUNT(DISTINCT invoice_id) FROM compliance_holds "
                "WHERE cleared_at IS NULL AND deleted = 0")),
            ("Open customer invoices", len(payments.open_invoices(o))),
            ("Missing lien waivers", len(waivers.missing(o))),
            ("Time not entered yesterday", len(timeentry.missing_time(
                o, (clock.today()).isoformat()))),
        ]
        try:                     # reviews 1 + 2 (Nov 4): never backed up
            from ..r111 import paykeys
            if paykeys.needs_backup(o):
                counts.insert(0, ("Payroll key never backed up (Payroll "
                                  "Key & Approvals)", 1))
        except Exception:                                 # noqa: BLE001
            pass
        self.counts = dict(counts)
        self.lay.addWidget(table(["To do", "Count"], counts))
        self.lay.addWidget(QLabel(
            f"Accounting mode: {office_mod.MODES[o.mode]}"))
        self.lay.addStretch(1)


def cents_hours(h):
    from .. import cents
    return cents.hours_text(h)


class JobCostPage(Page):
    def __init__(self, office, parent=None):
        super().__init__(office, parent)
        self.lay.addWidget(heading("Job Cost"))
        self.job = job_picker(office)
        self.lay.addWidget(self.job)
        # r38 G2.5: regular labor, overtime labor and per diem shown apart
        self.grid = table(["Code", "Description", "Revised budget",
                           "Committed", "Regular labor", "Overtime labor",
                           "Per diem", "AP + other", "Actual", "Remaining",
                           "% spent", "Forecast", "Variance"])
        self.lay.addWidget(self.grid)
        self.job.currentIndexChanged.connect(self.refresh)
        self.refresh()

    def refresh(self):
        jid = self.job.currentData()
        if jid is None:
            return
        dups = []
        rows = jobcost.job_cost(self.office, jid, duplicates=dups)
        if not hasattr(self, "dup_note"):
            self.dup_note = QLabel("")
            self.dup_note.setWordWrap(True)
            self.lay.insertWidget(self.lay.indexOf(self.grid), self.dup_note)
        # PM review NW-11: the same invoice in QuantiSheet direct costs and
        # in AP is counted once - and said so
        self.dup_note.setText(
            "Counted once: " + "; ".join(
                f"{d['vendor']} {d['invoice'] or ''} "
                f"({cents.fmt(d['amount'])}) is both a QuantiSheet direct "
                f"cost and AP {d['ap_number']}" for d in dups)
            if dups else "")
        self.dup_note.setVisible(bool(dups))
        fill(self.grid, [(r["code"], r["description"], r["revised"],
                          r["committed"], r["labor_regular"],
                          r["labor_overtime"], r["per_diem"],
                          r["ap"] + r["direct"], r["actual"], r["remaining"],
                          r["pct_spent"], r["forecast"], r["variance"])
                         for r in rows],
             money_cols=(2, 3, 4, 5, 6, 7, 8, 9, 11, 12))


class PayablesPage(DropGuard, Page):
    def __init__(self, office, parent=None):
        super().__init__(office, parent)
        self.setAcceptDrops(True)
        self.lay.addWidget(heading("Payables"))
        tabs = QTabWidget()
        rows = office.db.rows(
            "SELECT i.id, i.number, v.name, i.invoice_no, i.invoice_date, "
            "i.due_date, i.total, i.status FROM ap_invoices i JOIN vendors v "
            "ON v.id = i.vendor_id WHERE i.deleted = 0 ORDER BY i.id DESC")
        self.ids = [r["id"] for r in rows]
        self.register = table(["AP no.", "Vendor", "Invoice", "Date", "Due",
                               "Total", "Status"],
                              [(r["number"], r["name"], r["invoice_no"],
                                r["invoice_date"], r["due_date"], r["total"],
                                r["status"]) for r in rows], money_cols=(5,))
        self.register.doubleClicked.connect(self.open_invoice)
        try:            # 1.1.1: watch an invoice folder (r111.apdrop)
            from ..r111.ui import DropFolderBar
            self.lay.addWidget(DropFolderBar(office))
        except Exception:                                 # noqa: BLE001
            pass
        tabs.addTab(self.register, "AP invoices")
        ag = appay.aging(office, clock.today().isoformat())
        tabs.addTab(table(["AP no.", "Due", "Days late", "Bucket", "Open"],
                          [(r["number"], r["due_date"], r["days"],
                            r["bucket"], r["open"]) for r in ag["rows"]],
                          money_cols=(4,)), "AP aging")
        tabs.addTab(table(["Vendor", "Commitment", "Held"],
                          [(r.get("vendor", ""), r.get("commitment_no", ""),
                            r.get("held", 0)) for r in
                           appay.retainage_payable(office)], money_cols=(2,)),
                    "Retainage payable")
        self.lay.addWidget(tabs)

    def open_invoice(self, index):
        from .ap_invoice import APInvoiceDialog
        APInvoiceDialog(self.office, self.ids[index.row()], self).exec()

    def accept_file(self, path):
        try:
            res = ap.capture(self.office, path)
        except Exception as e:                            # noqa: BLE001
            return str(e)
        self.captured = res
        return ""


class BillingPage(Page):
    def __init__(self, office, parent=None):
        super().__init__(office, parent)
        from .. import billing
        from .billing_page import ContractPage
        self.lay.addWidget(heading("Billing"))
        self.job = job_picker(office)
        self.lay.addWidget(self.job)
        # 1.2 (Nov 5): closed service work orders' invoices, posted once
        from PySide6.QtWidgets import QPushButton
        self.svc_btn = QPushButton("Bring In QuantiSheet Service Invoices")
        self.svc_btn.setEnabled(office.can("ar.edit"))
        self.svc_btn.clicked.connect(lambda _c=False: self.service_invoices())
        self.lay.addWidget(self.svc_btn)
        self.svc_msg = QLabel("")
        self.svc_msg.setWordWrap(True)
        self.lay.addWidget(self.svc_msg)
        self.holder = QVBoxLayout()
        self.lay.addLayout(self.holder)
        self.register_box = QVBoxLayout()
        self.lay.addLayout(self.register_box)
        self.register_table = None
        self.show_register()
        self._cp = ContractPage
        self.job.currentIndexChanged.connect(self.refresh)
        self.refresh()

    def show_register(self):
        """The invoice register, read again (after an import it showed 0
        rows until reopened - Chief's re-test, Nov 7)."""
        from .. import billing
        if self.register_table is not None:
            self.register_box.removeWidget(self.register_table)
            self.register_table.deleteLater()
        reg = billing.register(self.office)
        self.register_table = table(
            ["Invoice", "Type", "Date", "Customer", "Total", "Status"],
            [(r["number"], r["type"], r["invoice_date"], r["customer"],
              r["total"], r["status"]) for r in reg], money_cols=(4,))
        self.register_box.addWidget(self.register_table)
        return self.register_table

    def service_invoices(self, ask=None):
        """Bring in the service invoices of the picked job (the QuantiSheet
        service department's job). Posting needs ar.approve and a yes."""
        from .. import billing
        jid = self.job.currentData()
        if jid is None:
            self.svc_msg.setText("Pick the service job first.")
            return None
        post = self.office.can("ar.approve")
        if post:
            if ask is None:
                from PySide6.QtWidgets import QMessageBox
                ask = lambda t: QMessageBox.question(           # noqa: E731
                    self, "Service invoices", t) == QMessageBox.Yes
            post = ask("Post the new service invoices to the books now? "
                       "(No: bring them in as Draft.) Each invoice is posted "
                       "once; one already here adds nothing.")
        res = billing.import_service_invoices(self.office, jid, post=post)
        self.svc_msg.setText(
            f"{len(res['created'])} service invoice(s) brought in"
            + (f", {len(res['posted'])} posted" if res["posted"] else
               " as Draft")
            + (f"; {len(res['reversed'])} reversed" if res["reversed"]
               else "")
            + (f"; skipped: " + "; ".join(f"{n} ({w})"
                                          for n, w in res["skipped"])
               if res["skipped"] else "") + ".")
        self.show_register()
        self.refresh()
        return res

    def refresh(self):
        while self.holder.count():
            w = self.holder.takeAt(0).widget()
            if w:
                w.deleteLater()
        jid = self.job.currentData()
        if jid is not None:
            self.holder.addWidget(self._cp(self.office, jid))


class PaymentsPage(Page):
    def __init__(self, office, parent=None):
        super().__init__(office, parent)
        self.lay.addWidget(heading("Payments & Aging"))
        ag = payments.aging(office, clock.today().isoformat())
        self.lay.addWidget(QLabel("  ".join(f"{k}: {money(v)}" for k, v in
                                            ag["totals"].items()) +
                                  f"   Total: {money(ag['total'])}"))
        self.lay.addWidget(table(["Invoice", "Customer", "Due", "Days late",
                                  "Bucket", "Open"],
                                 [(r["number"], r["customer"], r["due_date"],
                                   r["days"], r["bucket"], r["open"])
                                  for r in ag["rows"]], money_cols=(5,)))
        self.lay.addWidget(QLabel("Back Office records payments; it never "
                                  "moves money."))


class WaiversPage(Page):
    def __init__(self, office, parent=None):
        super().__init__(office, parent)
        self.lay.addWidget(heading("Lien Waivers"))
        tabs = QTabWidget()
        for d, label in (("issued", "Issued"), ("received", "Received")):
            tabs.addTab(table(["Kind", "Job", "Party", "Through", "Amount",
                               "Status"],
                              [(w["kind"].replace("_", " "), w["job_id"],
                                w["party"], w["through"], w["amount"],
                                w["status"]) for w in
                               waivers.waivers(office, d)], money_cols=(4,)),
                        label)
        self.lay.addWidget(tabs)
        self.lay.addWidget(QLabel(waivers.WARNING))


class BooksPage(Page):
    """Trial balance always (the ledger runs in both modes); banking,
    reconciliation and the full statements only in full-books mode."""

    def __init__(self, office, parent=None):
        super().__init__(office, parent)
        self.lay.addWidget(heading("Books & Reports"))
        tb = ledger.trial_balance(office, clock.today().isoformat())
        self.lay.addWidget(QLabel(
            f"Trial balance: debits {money(tb['debits'])}, credits "
            f"{money(tb['credits'])}"))
        self.lay.addWidget(table(["Account", "Name", "Debit", "Credit"],
                                 [(r["number"], r["name"], r["debit"],
                                   r["credit"]) for r in tb["rows"]],
                                 money_cols=(2, 3)))
        from .ai_pages import WipBox
        self.lay.addWidget(WipBox(office))
        if office.mode != "full":
            self.lay.addWidget(QLabel(
                "Banking, reconciliation and financial statements are part of "
                f"'{office_mod.MODES['full']}' (Settings > Accounting)."))
        else:
            try:
                from .. import reports
                pl = reports.profit_and_loss(
                    office, f"{clock.today().year}-01-01",
                    clock.today().isoformat())
                self.lay.addWidget(QLabel(
                    f"Net income this year: {money(pl['net_income'])}"))
            except Exception:                             # noqa: BLE001
                pass


class SettingsPage(Page):
    def __init__(self, office, parent=None):
        super().__init__(office, parent)
        self.lay.addWidget(heading("Settings"))
        c = office.company()
        form = QFormLayout()
        self.name = QLineEdit(c.get("name") or "")
        self.mode = QComboBox()
        for k, v in office_mod.MODES.items():
            self.mode.addItem(v, k)
        self.mode.setCurrentIndex(list(office_mod.MODES).index(office.mode))
        form.addRow("Company name", self.name)
        form.addRow("Accounting", self.mode)
        form.addRow("Data folder", QLabel(office.folder))
        form.addRow("Books closed through",
                    QLabel(ledger.closed_through(office) or "(not closed)"))
        from .. import localai
        cfg = localai.config()
        self.ai_url = QLineEdit(cfg["url"])
        self.ai_model = QComboBox()
        self.ai_model.setEditable(True)
        self.ai_model.addItem(cfg["model"])
        self.ai_find = QPushButton("Find local models")
        self.ai_find.clicked.connect(self.find_models)
        ai_row = QHBoxLayout()
        ai_row.addWidget(self.ai_model, 1)
        ai_row.addWidget(self.ai_find)
        self.ai_api = QComboBox()
        for k, v in localai.APIS.items():
            self.ai_api.addItem(v, k)
        self.ai_api.setCurrentIndex(list(localai.APIS).index(cfg["api"]))
        self.ai_threshold = QLineEdit(cfg["threshold"])
        self.ai_threshold.setToolTip("AI suggestions at or above this "
                                     "confidence can be accepted together "
                                     "with one click (0 to 1).")
        self.ai_test = QPushButton("Test connection")
        self.ai_test.clicked.connect(self.test_ai)
        self.ai_test_result = QLabel("")
        test_row = QHBoxLayout()
        test_row.addWidget(self.ai_test)
        test_row.addWidget(self.ai_test_result, 1)
        form.addRow("AI (this PC only)", self.ai_url)
        form.addRow("AI runtime", self.ai_api)
        form.addRow("AI model", ai_row)
        form.addRow("Bulk-accept confidence", self.ai_threshold)
        form.addRow("", test_row)
        form.addRow("", QLabel("AI suggestions can be wrong; check before "
                               "accepting. With no model, AI is unavailable "
                               "and every report still runs from the "
                               "menus."))
        self.lay.addLayout(form)
        self.save_btn = QPushButton("Save")
        self.save_btn.setEnabled(office.can("settings.edit"))
        self.save_btn.clicked.connect(self.save)
        self.lay.addWidget(self.save_btn)
        self.lay.addWidget(QLabel(fileguard.TRADEMARK_NOTICE))
        self.lay.addStretch(1)

    def save(self):
        try:
            self.office.set_company(name=self.name.text(),
                                    accounting_mode=self.mode.currentData())
            from .. import localai
            localai.configure(url=self.ai_url.text().strip(),
                              model=self.ai_model.currentText().strip(),
                              api=self.ai_api.currentData(),
                              threshold=self.ai_threshold.text().strip())
        except Exception as e:                            # noqa: BLE001
            error(self, e)

    def find_models(self):
        """Ask the LOCAL Ollama which models are installed (button only)."""
        from .. import localai
        try:
            names = localai.Client(url=self.ai_url.text().strip(),
                                   model="",
                                   api=self.ai_api.currentData()).models()
        except Exception as e:                            # noqa: BLE001
            error(self, e)
            return
        cur = self.ai_model.currentText()
        self.ai_model.clear()
        self.ai_model.addItems(names or [cur])

    def test_ai(self):
        """Settings > AI 'Test connection' (button only, this PC only)."""
        from .. import localai
        try:
            c = localai.Client(url=self.ai_url.text().strip(),
                               model=self.ai_model.currentText().strip(),
                               api=self.ai_api.currentData(),
                               timeout=localai.TAGS_TIMEOUT)
            self.ai_test_result.setText(c.test_connection())
        except Exception as e:                            # noqa: BLE001
            self.ai_test_result.setText(f"Not reachable: {e}")


from .people_pages import CardsPage, FieldPage, PayrollPage, PeoplePage  # noqa: E402
from .ai_pages import AssistantPage, SyncPage  # noqa: E402
from .timeoff_page import TimeOffPage  # noqa: E402

PAGES = {"Home": HomePage, "Time": TimePage, "Job Cost": JobCostPage,
         "Payroll": PayrollPage, "People": PeoplePage,
         "Time Off": TimeOffPage, "Field": FieldPage,
         "Cards": CardsPage,
         "Payables": PayablesPage, "Billing": BillingPage,
         "Payments & Aging": PaymentsPage, "Lien Waivers": WaiversPage,
         "Exports": ExportsPage, "Books & Reports": BooksPage,
         "Assistant": AssistantPage, "Sync Center": SyncPage,
         "Settings": SettingsPage}

# 1.1.1 (Nov 4): Waiting on Me, the Job Cost Report import, the field
# pages (crew board, pre-task plans, safety, incidents, equipment,
# warranty) and the checklist template editor - quantisheet_backoffice.r111
from ..r111 import ui as _r111  # noqa: E402
PAGES.update({"Waiting on Me": _r111.WaitingPage,
              "Job Cost Report": _r111.ReportPage,
              "Crew Board": _r111.CrewBoardPage,
              "Pre-Task Plans": _r111.JhaPage,
              "Safety Meetings": _r111.SafetyPage,
              "Incidents": _r111.IncidentPage,
              "Equipment": _r111.EquipmentPage,
              "Warranty & Service Calls": _r111.WarrantyPage,
              "Checklist Templates": _r111.QaTemplatePage,
              "Payroll Key & Approvals": _r111.SecurityPage})


class BackOfficeWindow(QMainWindow):
    def __init__(self, office, parent=None):
        super().__init__(parent)
        self.office = office
        self.setWindowTitle(f"{APP_NAME} {__version__}")
        central = QWidget()
        lay = QHBoxLayout(central)
        self.nav = QListWidget()
        self.nav.addItems(NAV)
        self.nav.setFixedWidth(170)
        self.stack = QStackedWidget()
        lay.addWidget(self.nav)
        lay.addWidget(self.stack, 1)
        self.setCentralWidget(central)
        self.pages = {}
        self.nav.currentRowChanged.connect(self.show_page)
        m = self.menuBar().addMenu("&File")
        m.addAction("Import QuantiSheet snapshot…", self.ask_snapshot)
        self.backup_action = m.addAction("Back up now", self.backup)
        self.backup_pw_action = m.addAction("Set backup password…",
                                            self.set_backup_password)
        self.restore_action = m.addAction("Restore from backup…",
                                          self.restore_backup)
        m.addSeparator()
        m.addAction("Exit", self.close)
        self.nav.setCurrentRow(0)
        self.update_status()

    # File-menu actions follow the signed-in user's permissions (0.13.5
    # security fix): a backup is a full copy of the company database.
    FILE_PERMS = {"backup_action": "backup.run",
                  "backup_pw_action": "settings.edit",
                  "restore_action": "settings.edit"}

    def update_actions(self):
        for attr, perm in self.FILE_PERMS.items():
            act = getattr(self, attr, None)
            if act is not None:
                ok = self.office.can(perm)
                act.setEnabled(ok)
                act.setToolTip("" if ok else f"Needs the {perm} permission.")

    def page_names(self):
        return [self.nav.item(i).text() for i in range(self.nav.count())]

    def show_page(self, row):
        name = NAV[row]
        old = self.pages.pop(name, None)
        if old is not None:
            self.stack.removeWidget(old)
            old.deleteLater()
        try:
            pg = PAGES[name](self.office)
        except Exception as e:                            # noqa: BLE001
            pg = QLabel(f"{name}: {e}")
        self.pages[name] = pg
        self.stack.addWidget(pg)
        self.stack.setCurrentWidget(pg)
        return pg

    def last_snapshot_date(self) -> str:
        r = self.office.db.one("SELECT MAX(taken_at) AS d FROM snapshot_imports")
        return (r["d"] or "")[:10] if r else ""

    def update_status(self):
        who = self.office.who or "not signed in"
        snap = self.last_snapshot_date() or "none yet"
        self.statusBar().showMessage(f"Signed in: {who}    Last QuantiSheet "
                                     f"snapshot: {snap}")
        self.update_actions()

    def import_snapshot(self, path) -> list[str]:
        fileguard.refuse_company_file(path)
        changes = jobs.import_snapshot(self.office,
                                       interface.load_snapshot(path))
        self.update_status()
        self.show_page(self.nav.currentRow())
        return changes

    def ask_snapshot(self):
        path, _ = QFileDialog.getOpenFileName(self, "QuantiSheet snapshot", "",
                                              "Snapshot (*.json)")
        if path:
            try:
                self.import_snapshot(path)
            except Exception as e:                        # noqa: BLE001
                error(self, e)

    def backup(self):
        from .. import backup
        if not self.office.can("backup.run"):
            error(self, PermissionError("Only an Admin or Controller can "
                                        "make a backup."))
            return
        try:
            if not backup.has_password(self.office) and \
                    self.office.can("settings.edit"):
                self.set_backup_password()
            path = backup.make(self.office)
            self.statusBar().showMessage(f"Encrypted backup saved: {path}")
        except Exception as e:                            # noqa: BLE001
            error(self, e)

    def _ask_password(self, title, prompt):
        from PySide6.QtWidgets import QInputDialog, QLineEdit
        pw, ok = QInputDialog.getText(self, title, prompt,
                                      QLineEdit.EchoMode.Password)
        return pw if ok else None

    def set_backup_password(self):
        from .. import backup
        if not self.office.can("settings.edit"):
            error(self, PermissionError("Only an Admin or Controller can "
                                        "set the backup password."))
            return
        pw = self._ask_password("Backup password", "Backup password (needed "
                                "to restore on another PC; keep it safe):")
        if not pw:
            return
        if self._ask_password("Backup password", "Type it again:") != pw:
            error(self, ValueError("The two passwords differ."))
            return
        try:
            backup.set_password(self.office, pw)
        except Exception as e:                            # noqa: BLE001
            error(self, e)

    def restore_backup(self):
        from PySide6.QtWidgets import QMessageBox
        from .. import backup
        if not self.office.can("settings.edit"):
            error(self, PermissionError("Only an Admin or Controller can "
                                        "restore a backup."))
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Restore from backup", backup.backups()[-1]
            if backup.backups() else "", "Back Office backup (*.qsbk)")
        if not path:
            return
        if QMessageBox.question(self, APP_NAME, "Replace ALL current Back "
                                "Office data with this backup?") != \
                QMessageBox.StandardButton.Yes:
            return
        pw = self._ask_password("Restore", "Backup password (leave empty "
                                "for a backup made on this PC):")
        if pw is None:
            return
        try:
            backup.restore(self.office.folder, path, password=pw or None,
                           office=self.office)
        except Exception as e:                            # noqa: BLE001
            error(self, e)
            return
        QMessageBox.information(self, APP_NAME, "Restored. Back Office will "
                                "close now; start it again.")
        self.close()
