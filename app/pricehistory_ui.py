"""Job Cost Feedback window (Estimate > Job Cost Feedback): jobs, bid vs
actual by cost code, and suggested cost book prices from what jobs really
cost - applied only when you tick them."""
import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QFileDialog,
                               QHBoxLayout, QHeaderView, QInputDialog,
                               QLabel, QMessageBox, QPushButton, QSplitter,
                               QTableWidget, QTableWidgetItem, QTabWidget,
                               QVBoxLayout, QWidget)

from . import pricehistory as ph
from .dmoney import fmt

RED = QColor(255, 215, 215)


def _it(v, right=False):
    it = QTableWidgetItem("" if v is None else str(v))
    it.setFlags(it.flags() & ~Qt.ItemIsEditable)
    if right:
        it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
    return it


def _money(v):
    return "" if v is None else fmt(v)


class JobCostDialog(QDialog):
    def __init__(self, win=None):
        super().__init__(win)
        self.win = win
        self.setWindowTitle("Job Cost Feedback")
        self.resize(1200, 760)
        v = QVBoxLayout(self)
        intro = QLabel("Register a job from its locked bid, bring in what it "
                       "actually cost (Project Center or a job-cost CSV), "
                       "then close it: its unit costs feed the suggestions "
                       "below. A cost book changes only when you tick a "
                       "suggestion and apply it.")
        intro.setWordWrap(True)
        v.addWidget(intro)
        row = QHBoxLayout()
        for label, fn in (("Add This PDF's Bid as a Job…", self.add_from_pdf),
                          ("Import Actual Costs (CSV)…", self.import_csv),
                          ("Actuals from Project Center…",
                           self.from_project),
                          ("Close Job", self.close_job)):
            b = QPushButton(label)
            b.clicked.connect(lambda _c=False, f=fn: f())
            row.addWidget(b)
        row.addStretch()
        v.addLayout(row)
        split = QSplitter(Qt.Vertical)
        self.jobs = QTableWidget(0, 6)
        self.jobs.setHorizontalHeaderLabels(["Job", "Name", "Bid date",
                                             "Status", "Bid total",
                                             "Closed"])
        self.jobs.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.jobs.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.Stretch)
        self.jobs.itemSelectionChanged.connect(self.show_job)
        split.addWidget(self.jobs)
        tabs = QTabWidget()
        self.var = QTableWidget(0, 11)
        self.var.setHorizontalHeaderLabels(
            ["Code", "Description", "Unit", "Est qty", "Est unit",
             "Est cost", "Actual qty", "Actual unit", "Actual cost",
             "Over (under)", "%"])
        self.var.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.Stretch)
        tabs.addTab(self.var, "Bid vs Actual")
        sw = QWidget()
        sv = QVBoxLayout(sw)
        self.sug = QTableWidget(0, 7)
        self.sug.setHorizontalHeaderLabels(
            ["Apply", "Code", "Book price", "Suggested", "Range",
             "Jobs/quotes", "Change"])
        self.sug.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.Stretch)
        sv.addWidget(self.sug, 1)
        r2 = QHBoxLayout()
        b = QPushButton("Suggest Prices for This Job's Codes")
        b.clicked.connect(lambda: self.suggest())
        r2.addWidget(b)
        b = QPushButton("Apply Ticked to Cost Book…")
        b.setObjectName("primary")
        b.clicked.connect(lambda: self.apply())
        r2.addWidget(b)
        r2.addStretch()
        sv.addLayout(r2)
        tabs.addTab(sw, "Suggested Prices")
        split.addWidget(tabs)
        split.setSizes([220, 520])
        v.addWidget(split, 1)
        self.status = QLabel()
        self.status.setObjectName("muted")
        v.addWidget(self.status)
        self.rows = []
        self.suggestions = []
        self.refresh()

    # ---------------------------------------------------------- jobs
    def refresh(self, select=None):
        try:
            self.rows = ph.jobs()
        except Exception as e:
            self.status.setText(str(e))
            self.rows = []
        self.jobs.setRowCount(len(self.rows))
        for i, j in enumerate(self.rows):
            for c, val in enumerate((j["number"], j["name"], j["bid_date"],
                                     j["status"], _money(j["bid_total"]),
                                     j["closed"] or "")):
                self.jobs.setItem(i, c, _it(val, c == 4))
        if select is not None:
            for i, j in enumerate(self.rows):
                if j["id"] == select:
                    self.jobs.selectRow(i)
        return self.rows

    def job(self):
        r = self.jobs.currentRow()
        return self.rows[r] if 0 <= r < len(self.rows) else None

    def show_job(self):
        j = self.job()
        self.var.setRowCount(0)
        if not j:
            return []
        rows = ph.variance(j["id"])
        self.var.setRowCount(len(rows))
        for i, r in enumerate(rows):
            vals = (r["code"], r["desc"], r["unit"], r["est_qty"],
                    _money(r["est_unit"]), _money(r["est_cost"]),
                    r["act_qty"], _money(r["act_unit"]),
                    _money(r["act_cost"]), _money(r["diff"]),
                    "" if r["pct"] is None else f"{r['pct']}%")
            for c, val in enumerate(vals):
                it = _it(val, c >= 3)
                if r["flag"]:
                    it.setBackground(RED)
                self.var.setItem(i, c, it)
        flagged = sum(1 for r in rows if r["flag"])
        self.status.setText(f"{j['number']}: {len(rows)} line(s), "
                            f"{flagged} off by more than 10%.")
        return rows

    def add_from_pdf(self, number=None, name=None):
        v = getattr(self.win, "_view", None)
        if v is None:
            QMessageBox.information(self, "Job Cost Feedback",
                                    "Open the bid PDF first.")
            return None
        if number is None:
            number, ok = QInputDialog.getText(self, "Add Job", "Job number")
            if not ok or not number.strip():
                return None
            name, ok = QInputDialog.getText(self, "Add Job", "Job name")
            if not ok:
                return None
        try:
            jid = ph.job_from_doc(v.doc, number.strip(), name or "")
        except Exception as e:
            QMessageBox.warning(self, "Job Cost Feedback", str(e))
            return None
        self.refresh(select=jid)
        return jid

    def import_csv(self, path=None):
        j = self.job()
        if not j:
            QMessageBox.information(self, "Job Cost Feedback",
                                    "Pick a job first.")
            return None
        if path is None:
            path, _ = QFileDialog.getOpenFileName(
                self, "Job Cost Report", "", "CSV (*.csv)")
        if not path:
            return None
        try:
            got = ph.set_actuals(j["id"], ph.read_actuals_csv(path),
                                 source=os.path.basename(path))
        except Exception as e:
            QMessageBox.warning(self, "Job Cost Feedback", str(e))
            return None
        self.show_job()
        self.status.setText(f"{got[0]} line(s) matched, {got[1]} added "
                            "from the report.")
        return got

    def from_project(self, folder=None):
        from .pm.store import ProjectStore
        j = self.job()
        if not j:
            QMessageBox.information(self, "Job Cost Feedback",
                                    "Pick a job first.")
            return None
        if folder is None:
            folder = QFileDialog.getExistingDirectory(
                self, "Project Center folder of this job")
        if not folder or not ProjectStore.exists(folder):
            return None
        store = ProjectStore(folder)
        acts = ph.actuals_from_store(store)
        try:                    # civil time cards: crew and equipment cost
            from . import heavy
            acts = heavy.merge_actuals(acts, heavy.store_actuals(
                store, heavy.library()))
        except Exception:
            pass
        got = ph.set_actuals(j["id"], acts, source="project center")
        self.show_job()
        return got

    def close_job(self, confirm=True):
        j = self.job()
        if not j:
            return None
        if confirm and QMessageBox.question(
                self, "Close Job", f"Close {j['number']}? Its actual unit "
                "costs become price history.") != QMessageBox.Yes:
            return None
        try:
            n = ph.close_job(j["id"])
        except Exception as e:
            QMessageBox.warning(self, "Job Cost Feedback", str(e))
            return None
        self.refresh(select=j["id"])
        self.status.setText(f"Closed {j['number']}: {n} unit cost(s) "
                            "recorded.")
        return n

    # ---------------------------------------------------------- prices
    def _book(self, name=None):
        from . import costbook
        try:
            from . import pricedb
            names = pricedb.book_names()
        except Exception:
            names = []
        if name is None:
            if not names:
                return None
            name, ok = QInputDialog.getItem(self, "Cost Book", "Cost book:",
                                            names, 0, False)
            if not ok:
                return None
        return costbook.load(costbook.DB + name), name

    def suggest(self, book_name=None):
        j = self.job()
        codes = sorted({r["code"] for r in ph.lines(j["id"])}) if j else []
        got = self._book(book_name) if codes else None
        book = got[0] if got else None
        self.book_name = got[1] if got else None
        self.suggestions = [s for s in (ph.suggest(c, book) for c in codes)
                            if s]
        t = self.sug
        t.setRowCount(len(self.suggestions))
        for i, s in enumerate(self.suggestions):
            chk = QTableWidgetItem()
            chk.setFlags(chk.flags() | Qt.ItemIsUserCheckable)
            chk.setCheckState(Qt.Unchecked)
            t.setItem(i, 0, chk)
            change = ""
            if s["book"]:
                pct = (s["price"] - s["book"]) / s["book"] * 100
                change = f"{pct:+.1f}%"
            for c, val in enumerate((s["code"], _money(s["book"]),
                                     _money(s["price"]),
                                     f"{fmt(s['min'])} - {fmt(s['max'])}",
                                     s["count"], change), 1):
                t.setItem(i, c, _it(val, c >= 2))
        self.status.setText(f"{len(self.suggestions)} code(s) have price "
                            "history.")
        return self.suggestions

    def tick(self, row, on=True):
        self.sug.item(row, 0).setCheckState(Qt.Checked if on else
                                            Qt.Unchecked)

    def apply(self):
        picks = {s["code"]: s["price"] for i, s in
                 enumerate(self.suggestions)
                 if self.sug.item(i, 0).checkState() == Qt.Checked}
        if not picks or not getattr(self, "book_name", None):
            QMessageBox.information(self, "Job Cost Feedback",
                                    "Tick the suggestions to apply.")
            return None
        j = self.job()
        changed, skipped = ph.apply(self.book_name, picks,
                                    f"job {j['number']}" if j else "")
        msg = f"Updated {len(changed)} price(s) in {self.book_name}."
        if skipped:
            msg += f" Not in the book (skipped): {', '.join(skipped)}."
        self.status.setText(msg)
        return changed, skipped
