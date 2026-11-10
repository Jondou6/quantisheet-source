"""Contract & Billing window: contract details, schedule of values, change
orders, pay applications and lien waivers."""
import os

from PySide6.QtCore import QDate, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDateEdit, QDialog, QDialogButtonBox,
    QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout, QHeaderView,
    QInputDialog, QLabel, QLineEdit, QMessageBox, QPlainTextEdit,
    QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QTabWidget,
    QVBoxLayout, QWidget)

from . import theme as _theme
from . import annotate, money
from .dmoney import c2 as _c2


def _m(v):
    v = _c2(v)                                  # half up, as the totals
    return f"${_c2(v):,.2f}" if v >= 0 else f"(${_c2(-v):,.2f})"


def _item(text, editable=False, right=False, bold=False):
    it = QTableWidgetItem(str(text))
    if not editable:
        it.setFlags(it.flags() & ~Qt.ItemIsEditable)
    if right:
        it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
    if bold:
        f = QFont()
        f.setBold(True)
        it.setFont(f)
    return it


def _date(s=None):
    d = QDateEdit()
    d.setCalendarPopup(True)
    d.setDisplayFormat("yyyy-MM-dd")
    q = QDate.fromString(s, "yyyy-MM-dd") if s else QDate.currentDate()
    d.setDate(q if q.isValid() else QDate.currentDate())
    return d


def _ds(d):
    return d.date().toString("yyyy-MM-dd")


def project_note(store):
    """What to say when the drawing belongs to a Project Center job (PM
    review NW-09: Billing on the ribbon showed an empty ledger while the
    job's pay apps were in Project Center)."""
    if store is None:
        return ""
    n_apps = len(store.list("payapp"))
    n_sov = len(store.list("contract"))
    return (f"This drawing is in the Project Center job "
            f"\u201c{store.name}\u201d: {n_sov} contract line(s) and {n_apps} "
            "pay application(s) are there. The billing on this window is a "
            "separate ledger kept inside this PDF.")



def friendly(e):
    """An error in words a person reads - never Python's own text, such as
    "could not convert string to float: 'abc'" (Chief's estimator test,
    Nov 7)."""
    import re
    t = str(e).strip()
    m = re.match(r"could not convert string to (?:float|int)(?: with base "
                 r"\d+)?: ?'?(.*?)'?$", t) or \
        re.match(r"invalid literal for int\(\) with base \d+: '?(.*?)'?$", t)
    if m:
        return f"\"{m.group(1)}\" isn't a number. Type a number, such as 1250.00."
    if isinstance(e, KeyError):
        return f"{t.strip(chr(39))} isn't on file."
    return t.strip("'") or "That couldn't be done."

class BillingDialog(QDialog):
    """Non-modal: stays open beside the drawings."""

    edited = Signal()

    def __init__(self, doc, parent=None, selected_refs=None, project=None,
                 open_project=None):
        super().__init__(parent)
        self.doc = doc
        self.selected_refs = selected_refs or (lambda: [])
        self.setWindowTitle("Contract & Billing")
        self.resize(1100, 680)
        lay = QVBoxLayout(self)
        note = project_note(project)
        self.project_note = None
        if note:
            from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton
            row = QHBoxLayout()
            self.project_note = QLabel(note)
            self.project_note.setWordWrap(True)
            row.addWidget(self.project_note, 1)
            if open_project is not None:
                b = QPushButton("Open the job's Owner Pay Apps")
                b.clicked.connect(lambda _c=False: open_project())
                row.addWidget(b)
                # one billing ledger (P1): bring this PDF's billing into
                # the job once; from then on Billing opens the job's
                from .pm import ledger_import
                pv = ledger_import.preview(doc, project)
                if not pv["blocked"]:
                    imp = QPushButton("Bring this billing into the job…")
                    imp.clicked.connect(
                        lambda _c=False: self.bring_into_job(project,
                                                             open_project))
                    row.addWidget(imp)
            lay.addLayout(row)
        self.tabs = QTabWidget()
        lay.addWidget(self.tabs)
        self.tabs.addTab(self._contract_tab(), "Contract")
        self.tabs.addTab(self._sov_tab(), "Schedule of Values")
        self.tabs.addTab(self._co_tab(), "Change Orders")
        self.tabs.addTab(self._pay_tab(), "Pay Applications")
        self.tabs.addTab(self._waiver_tab(), "Lien Waivers")
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.close)
        lay.addWidget(bb)
        self.refresh()

    # ---- helpers ------------------------------------------------------------
    def _changed(self):
        self.edited.emit()
        self.refresh()

    def _try(self, fn, *a, **k):
        try:
            out = fn(*a, **k)
        except (money.BillingError, KeyError, ValueError) as e:
            QMessageBox.warning(self, "Contract & Billing", friendly(e))
            return None
        self._changed()
        return out if out is not None else True

    def _rname(self, kind, ext, number=None, when=None):
        """Default report file name - company rule, date first
        (app/reportname.py)."""
        from .reportname import report_file_name
        proj = (self.data.get("info") or {}).get("project", "")
        return report_file_name(kind, proj, number, when, ext)

    def _save_path(self, title, name, filt):
        base = os.path.dirname(self.doc.name or "") or os.path.expanduser("~")
        path, _ = QFileDialog.getSaveFileName(self, title,
                                              os.path.join(base, name), filt)
        return path

    def _open_file(self, path):
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def bring_into_job(self, project, open_project=None, ask=True):
        """Copy the ledger into the Project Center job (once), then open
        the job's pay apps - the one ledger from then on."""
        from PySide6.QtWidgets import QMessageBox
        from .pm import ledger_import
        pv = ledger_import.preview(self.doc, project)
        if pv["blocked"]:
            QMessageBox.information(self, "Contract & Billing",
                                    pv["blocked"])
            return None
        if ask and QMessageBox.question(
                self, "Contract & Billing",
                f"Bring into the job \u201c{project.name}\u201d: "
                f"{pv['contract']} contract line(s), {pv['change_orders']} "
                f"change order(s), {pv['pay_apps']} pay application(s) "
                f"({pv['certified']} certified)?\n\nFrom then on Billing "
                "opens the job's pay apps. This PDF's ledger stays as it "
                "is.") != QMessageBox.Yes:
            return None
        try:
            got = ledger_import.run(self.doc, project)
        except ledger_import.LedgerImportError as e:
            QMessageBox.warning(self, "Contract & Billing", str(e))
            return None
        if open_project is not None:
            open_project()
        self.close()
        return got

    def refresh(self):
        self.data = money.read(self.doc)
        self._fill_contract()
        self._fill_sov()
        self._fill_cos()
        self._fill_apps()
        self._fill_waiver_defaults()

    # ---- contract ------------------------------------------------------------
    def _contract_tab(self):
        w = QWidget()
        form = QFormLayout(w)
        labels = {"project": "Project", "project_address": "Project address",
                  "owner": "Owner", "contractor": "Contractor",
                  "architect": "Architect", "contract_no": "Contract no.",
                  "contract_date": "Contract date",
                  "contract_for": "Contract for"}
        self.info = {}
        for k in money.INFO_FIELDS:
            e = QLineEdit()
            self.info[k] = e
            form.addRow(labels[k] + ":", e)
        self.ret_work = QDoubleSpinBox()
        self.ret_stored = QDoubleSpinBox()
        for sp in (self.ret_work, self.ret_stored):
            sp.setRange(0, 100)
            sp.setDecimals(2)
            sp.setSuffix(" %")
        form.addRow("Retainage on completed work:", self.ret_work)
        form.addRow("Retainage on stored material:", self.ret_stored)
        self.contract_sum = QLabel("")
        form.addRow("Contract sum:", self.contract_sum)
        save = QPushButton("Save Contract Details")
        save.clicked.connect(self.save_contract)
        form.addRow(save)
        return w

    def _fill_contract(self):
        for k, e in self.info.items():
            e.setText(self.data["info"].get(k, ""))
        self.ret_work.setValue(float(self.data["retainage_work"]))
        self.ret_stored.setValue(float(self.data["retainage_stored"]))
        orig = money.original_contract(self.data)
        cos = sum(c["approved_amount"] for c in self.data["changes"]
                  if c["stage"] == "co")
        self.contract_sum.setText(f"{_m(orig)} original + {_m(cos)} change "
                                  f"orders = <b>{_m(orig + cos)}</b>")

    def save_contract(self):
        self._try(money.set_info, self.doc, self.ret_work.value(),
                  self.ret_stored.value(),
                  **{k: e.text() for k, e in self.info.items()})

    # ---- schedule of values -----------------------------------------------------
    def _sov_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(QLabel("The contract broken into lines. Executed change "
                           "orders are added at the end automatically."))
        self.sov = QTableWidget(0, 4)
        self.sov.setHorizontalHeaderLabels(["Item", "CSI", "Description",
                                            "Scheduled value $"])
        self.sov.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.Stretch)
        # wide enough for its heading ("cheduled value"; Nov 10)
        self.sov.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeToContents)
        self.sov.horizontalHeader().setMinimumSectionSize(60)
        v.addWidget(self.sov)
        row = QHBoxLayout()
        for label, fn in (("Add Line", self._sov_add),
                          ("Remove Line", self._sov_remove),
                          ("Build From Estimate…", self._sov_build),
                          ("Save Schedule", self.save_sov)):
            b = QPushButton(label)
            b.clicked.connect(lambda _c=False, _f=fn: _f())
            row.addWidget(b)
        row.addStretch()
        self.sov_total = QLabel("")
        row.addWidget(self.sov_total)
        v.addLayout(row)
        return w

    def _fill_sov(self, lines=None):
        lines = lines if lines is not None else self.data["sov"]
        self.sov.blockSignals(True)
        self.sov.setRowCount(len(lines))
        for r, l in enumerate(lines):
            co = bool(l.get("co"))
            self.sov.setItem(r, 0, _item(l.get("item", ""), not co))
            self.sov.setItem(r, 1, _item(l.get("csi", ""), not co))
            self.sov.setItem(r, 2, _item(l.get("desc", ""), not co))
            n = money._num(l.get("scheduled"))
            it = _item(str(l["scheduled"]) if n is None else f"{_c2(n):,.2f}",
                       not co, True)
            it.setData(Qt.UserRole, l.get("co", ""))
            self.sov.setItem(r, 3, it)
            if co:
                for c in range(4):
                    self.sov.item(r, c).setForeground(QColor(30, 90, 160))
        self.sov.blockSignals(False)
        bad = sum(money._num(l.get("scheduled")) is None for l in lines)
        tot = sum(money._num(l.get("scheduled")) or 0 for l in lines)
        self.sov_total.setText(f"Total {_m(tot)}" +
                               (f"  ({bad} can't be read)" if bad else ""))

    def sov_lines(self):
        out = []
        for r in range(self.sov.rowCount()):
            if self.sov.item(r, 3) and self.sov.item(r, 3).data(Qt.UserRole):
                continue                          # change order line
            cell = [self.sov.item(r, c).text().strip()
                    if self.sov.item(r, c) else "" for c in range(4)]
            out.append({"item": cell[0], "csi": cell[1], "desc": cell[2],
                        "scheduled": cell[3] if money._num(cell[3]) is None
                        else money._num(cell[3])})  # bad text: set_sov says so
        return out

    def _sov_add(self):
        lines = self.sov_lines() + [{"item": "", "csi": "", "desc":
                                     "New line", "scheduled": 0}]
        lines += [l for l in self.data["sov"] if l.get("co")]
        self._fill_sov(lines)

    def _sov_remove(self):
        r = self.sov.currentRow()
        if r >= 0 and not (self.sov.item(r, 3) and
                           self.sov.item(r, 3).data(Qt.UserRole)):
            self.sov.removeRow(r)

    def _sov_build(self, by=None):
        if by is None:
            choices = ["By trade", "By assembly", "By CSI division"]
            pick, ok = QInputDialog.getItem(
                self, "Build From Estimate", "Lines (at the proposal's "
                "prices, with the whole bid build-up):", choices, 0, False)
            if not ok:
                return None
            by = ("trade", "assembly", "csi")[choices.index(pick)]
        from . import proposal
        pd = proposal.read(self.doc)
        fl = float(pd.get("front_load") or 0) if pd.get("sov_front_load") \
            else 0.0
        lines = money.from_estimate(self.doc, by, fl,
                                    int(pd.get("months") or 12))
        if not lines:
            QMessageBox.information(self, "Build From Estimate",
                                    "There's no assembly takeoff to build "
                                    "from yet.")
            return None
        self._fill_sov(lines + [l for l in self.data["sov"] if l.get("co")])
        return lines

    def save_sov(self):
        return self._try(money.set_sov, self.doc, self.sov_lines())

    # ---- change orders --------------------------------------------------------
    def _co_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        self.cos = QTableWidget(0, 9)
        self.cos.setHorizontalHeaderLabels(
            ["PCO", "COR", "CO", "Title", "Stage", "Amount", "Days", "RFI",
             "Date"])
        self.cos.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.Stretch)
        self.cos.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.cos.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.cos.itemDoubleClicked.connect(lambda *_: self._co_edit())
        v.addWidget(self.cos)
        row = QHBoxLayout()
        for label, fn in (("New Change…", self._co_new),
                          ("From Selected Markup…", self._co_from_markups),
                          ("Edit…", self._co_edit),
                          ("Submit to Owner (COR)", self._co_submit),
                          ("Execute (CO)…", self._co_execute),
                          ("Reject", self._co_reject),
                          ("Print…", self._co_pdf),
                          ("Export Log…", self._co_log)):
            b = QPushButton(label)
            b.clicked.connect(lambda _c=False, _f=fn: _f())
            row.addWidget(b)
        row.addStretch()
        v.addLayout(row)
        self.co_total = QLabel("")
        v.addWidget(self.co_total)
        return w

    def _fill_cos(self):
        cs = self.data["changes"]
        self.cos.setRowCount(len(cs))
        pend = 0.0
        for r, c in enumerate(cs):
            amt = c["approved_amount"] if c["stage"] == "co" else c["amount"]
            days = c["approved_days"] if c["stage"] == "co" else c["days"]
            date = c.get("executed") or c.get("submitted") or c.get("raised")
            for col, val in enumerate((c["id"], c.get("cor_no", ""),
                                       c.get("co_no", ""), c["title"],
                                       money.STAGE_LABEL[c["stage"]],
                                       _m(amt), days, c.get("rfi", ""),
                                       date)):
                it = _item(val, right=col in (5, 6))
                it.setData(Qt.UserRole, c["id"])
                if c["stage"] in ("rejected", "void"):
                    it.setForeground(QColor(140, 140, 140))
                self.cos.setItem(r, col, it)
            if c["stage"] in ("pco", "cor"):
                pend += c["amount"]
        done = sum(c["approved_amount"] for c in cs if c["stage"] == "co")
        self.co_total.setText(f"Executed {_m(done)}   Pending (PCO + COR) "
                              f"{_m(pend)}")

    def _current_co(self):
        r = self.cos.currentRow()
        it = self.cos.item(r, 0) if r >= 0 else None
        if not it:
            QMessageBox.information(self, "Change Orders",
                                    "Select a change in the list first.")
            return None
        return it.data(Qt.UserRole)

    def _co_new(self, refs=None, cost=None):
        dlg = ChangeDialog(self, refs=refs, cost=cost)
        if dlg.exec() != QDialog.Accepted:
            return None
        return self._try(money.new_change, self.doc, **dlg.values())

    def _co_from_markups(self):
        refs = [r for r in self.selected_refs() if r]
        items = [it for it in annotate.totals_items(self.doc)
                 if it["ref"] in refs]
        if not items:
            QMessageBox.information(
                self, "Change From Markup", "Select a takeoff measurement "
                "on the drawing (the added or changed work) first, then "
                "try again.")
            return None
        cost, _price, problems = money.price_markups(self.doc, refs)
        if problems:
            QMessageBox.warning(self, "Change From Markup",
                                "\n".join(problems[:6]))
        return self._co_new(refs=refs, cost=cost)

    def _co_edit(self):
        cid = self._current_co()
        if not cid:
            return None
        c = money._find(self.data, cid)
        dlg = ChangeDialog(self, c)
        if dlg.exec() != QDialog.Accepted:
            return None
        return self._try(money.update_change, self.doc, cid, **dlg.values())

    def _co_submit(self):
        cid = self._current_co()
        return cid and self._try(money.submit, self.doc, cid)

    def _co_execute(self, amount=None):
        cid = self._current_co()
        if not cid:
            return None
        c = money._find(self.data, cid)
        if amount is None:
            amount, ok = QInputDialog.getDouble(
                self, "Execute Change Order", "Approved amount ($):",
                c["amount"], -1e9, 1e9, 2)
            if not ok:
                return None
        return self._try(money.execute, self.doc, cid, amount=amount)

    def _co_reject(self):
        cid = self._current_co()
        return cid and self._try(money.reject, self.doc, cid)

    def _co_pdf(self):
        cid = self._current_co()
        if not cid:
            return None
        c = money._find(self.data, cid)
        kind, no = (("Change Order", c["co_no"]) if c.get("co_no") else
                    ("Change Order Request", c["cor_no"])
                    if c.get("cor_no") else ("Change", c["id"]))
        path = self._save_path(
            "Print Change",
            self._rname(kind, ".pdf", str(no).rsplit("-", 1)[-1]),
            "PDF (*.pdf)")
        if path:
            money.change_pdf(self.doc, cid, path)
            self._open_file(path)
        return path

    def _co_log(self):
        path = self._save_path("Export Change Order Log",
                               self._rname("Change Order Log", ".xlsx"),
                               "Excel (*.xlsx)")
        if path:
            money.change_log_xlsx(self.doc, path)
        return path

    # ---- pay applications --------------------------------------------------------
    def _pay_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        top = QHBoxLayout()
        top.addWidget(QLabel("Application:"))
        self.app_pick = QComboBox()
        self.app_pick.currentIndexChanged.connect(lambda *_: self._fill_app())
        top.addWidget(self.app_pick)
        for label, fn in (("New Application…", self._app_new),
                          ("Retainage…", self._app_retainage),
                          ("Certify", self._app_certify),
                          ("Delete Draft", self._app_delete),
                          ("Application PDF…", self._app_pdf),
                          ("Excel…", self._app_xlsx)):
            b = QPushButton(label)
            b.clicked.connect(lambda _c=False, _f=fn: _f())
            top.addWidget(b)
        top.addStretch()
        v.addLayout(top)
        v.addWidget(QLabel("Type this period's work in dollars, or the "
                           "line's total % complete; Stored = materials on "
                           "site not yet installed."))
        self.app = QTableWidget(0, 10)
        self.app.setHorizontalHeaderLabels(
            ["Item", "Description", "Scheduled", "Previous", "This period",
             "Stored", "Total to date", "% complete", "Balance",
             "Retainage"])
        self.app.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.Stretch)
        self.app.itemChanged.connect(self._app_cell)
        v.addWidget(self.app)
        self.g702 = QLabel("")
        self.g702.setTextFormat(Qt.RichText)
        self.g702.setWordWrap(True)
        v.addWidget(self.g702)
        return w

    def _fill_apps(self):
        cur = self.app_pick.currentData()
        self.app_pick.blockSignals(True)
        self.app_pick.clear()
        for a in self.data["payapps"]:
            self.app_pick.addItem(
                f"No. {a['no']} - to {a['period_to']} "
                f"({'certified' if a.get('status') == 'certified' else 'draft'})",
                a["no"])
        i = self.app_pick.findData(cur)
        self.app_pick.setCurrentIndex(i if i >= 0 else
                                      self.app_pick.count() - 1)
        self.app_pick.blockSignals(False)
        self._fill_app()

    def _fill_app(self):
        no = self.app_pick.currentData()
        self.app.blockSignals(True)
        if no is None:
            self.app.setRowCount(0)
            self.g702.setText("No pay applications yet. Set up the schedule "
                              "of values, then New Application.")
            self.app.blockSignals(False)
            return
        v = money.compute(self.doc, no)
        locked = v["status"] == "certified"
        self.app.setRowCount(len(v["rows"]) + 1)
        for r, row in enumerate(v["rows"]):
            vals = [row["item"], row["desc"], _m(row["scheduled"]),
                    _m(row["previous"]), f"{_c2(row['this']):,.2f}",
                    f"{_c2(row['stored']):,.2f}", _m(row["completed"]),
                    f"{row['percent']:.1f}", _m(row["balance"]),
                    _m(row["retainage"])]
            for c, val in enumerate(vals):
                it = _item(val, editable=not locked and c in (4, 5, 7),
                           right=c >= 2)
                it.setData(Qt.UserRole, row["item"])
                if row["percent"] > 100.005:
                    _theme.tint(it, QColor(255, 225, 225))
                self.app.setItem(r, c, it)
        t = v["totals"]
        last = len(v["rows"])
        for c, val in enumerate(["", "Totals", _m(t["scheduled"]),
                                 _m(t["previous"]), _m(t["this"]),
                                 _m(t["stored"]), _m(t["completed"]), "",
                                 _m(t["balance"]), _m(t["retainage"])]):
            self.app.setItem(last, c, _item(val, right=c >= 2, bold=True))
        self.app.blockSignals(False)
        g = v["g702"]
        lines = " &nbsp; ".join(
            f"{k}. {_m(g[k])}" for k in ("1", "2", "3", "4", "5", "6", "7"))
        warn = ("<br><span style='color:#b00'>" + " ".join(v["warnings"]) +
                "</span>") if v["warnings"] else ""
        self.g702.setText(f"{lines}<br><b>8. Current payment due "
                          f"{_m(g['8'])}</b> &nbsp; 9. Balance to finish "
                          f"incl. retainage {_m(g['9'])} &nbsp; Retainage "
                          f"{v['retainage_work']:g}% work / "
                          f"{v['retainage_stored']:g}% stored" + warn)

    def _app_cell(self, it):
        no = self.app_pick.currentData()
        item = it.data(Qt.UserRole)
        if no is None or not item:
            return
        c = it.column()
        val = money._num(it.text())
        if val is None:                    # a typo: let set_progress say so
            val = it.text()
        kw = {4: {"work": val}, 5: {"stored": val}, 7: {"percent": val}}[c]
        try:
            money.set_progress(self.doc, no, item, **kw)
        except (money.BillingError, KeyError, ValueError) as e:
            QMessageBox.warning(self, "Contract & Billing", friendly(e))
        # rebuild after this signal returns (the edited cell is replaced)
        QTimer.singleShot(0, self._changed)

    def _app_new(self, period_to=None):
        if period_to is None:
            dlg = QDialog(self)
            dlg.setWindowTitle("New Pay Application")
            dlg.setMinimumWidth(340)            # room for the title (Nov 10)
            f = QFormLayout(dlg)
            end = _date()
            f.addRow("Period to:", end)
            bb = QDialogButtonBox(QDialogButtonBox.Ok |
                                  QDialogButtonBox.Cancel)
            bb.accepted.connect(dlg.accept)
            bb.rejected.connect(dlg.reject)
            f.addRow(bb)
            if dlg.exec() != QDialog.Accepted:
                return None
            period_to = _ds(end)
        no = self._try(money.new_pay_app, self.doc, period_to)
        if no:
            i = self.app_pick.findData(no)
            self.app_pick.setCurrentIndex(i)
        return no

    def _app_retainage(self):
        no = self.app_pick.currentData()
        if no is None:
            return None
        v = money.compute(self.doc, no)
        pct, ok = QInputDialog.getDouble(
            self, "Retainage", "Retainage % on completed work for this "
            "application (0 releases it on the final application):",
            v["retainage_work"], 0, 100, 2)
        if not ok:
            return None
        st, ok = QInputDialog.getDouble(
            self, "Retainage", "Retainage % on stored material:",
            v["retainage_stored"], 0, 100, 2)
        if not ok:
            return None
        return self._try(money.set_retainage, self.doc, no, pct, st)

    def _app_certify(self, confirm=True):
        no = self.app_pick.currentData()
        if no is None:
            return None
        if confirm and QMessageBox.question(
                self, "Certify", f"Certify application {no}? Its numbers "
                "will be locked.") != QMessageBox.Yes:
            return None
        return self._try(money.certify, self.doc, no)

    def _app_delete(self):
        no = self.app_pick.currentData()
        return no is not None and self._try(money.delete_pay_app, self.doc,
                                            no)

    def _app_pdf(self, path=None):
        no = self.app_pick.currentData()
        if no is None:
            return None
        path = path or self._save_path(
            "Pay Application",
            self._rname("Pay Application", ".pdf", no, self._period(no)),
            "PDF (*.pdf)")
        if path:
            money.pay_app_pdf(self.doc, no, path)
            self._open_file(path)
        return path

    def _period(self, no):
        """The pay app's period-to date (its report date), or None."""
        for a in self.data.get("payapps") or ():
            try:
                if int(a["no"]) == int(no):
                    return a.get("period_to")
            except (KeyError, TypeError, ValueError):
                pass
        return None

    def _app_xlsx(self):
        no = self.app_pick.currentData()
        if no is None:
            return None
        path = self._save_path(
            "Pay Application",
            self._rname("Pay Application", ".xlsx", no, self._period(no)),
            "Excel (*.xlsx)")
        if path:
            money.pay_app_xlsx(self.doc, no, path)
        return path

    # ---- lien waivers ------------------------------------------------------------
    def _waiver_tab(self):
        w = QWidget()
        f = QFormLayout(w)
        warn = QLabel(money.WAIVER_WARNING)
        warn.setWordWrap(True)
        warn.setStyleSheet("color: #a00;")
        f.addRow(warn)
        self.w_kind = QComboBox()
        for k, label in money.WAIVER_KINDS.items():
            self.w_kind.addItem(label, k)
        f.addRow("Kind:", self.w_kind)
        self.w_app = QComboBox()
        self.w_app.currentIndexChanged.connect(lambda *_: self._waiver_app())
        f.addRow("For pay application:", self.w_app)
        self.w_through = _date()
        f.addRow("Through date:", self.w_through)
        self.w_amount = QDoubleSpinBox()
        self.w_amount.setRange(0, 1e10)
        self.w_amount.setDecimals(2)
        self.w_amount.setPrefix("$ ")
        f.addRow("Amount:", self.w_amount)
        self.w_claimant = QLineEdit()
        f.addRow("Claimant:", self.w_claimant)
        self.w_payer = QLineEdit()
        f.addRow("Customer (paying):", self.w_payer)
        b = QPushButton("Create Waiver PDF…")
        b.clicked.connect(lambda _c=False: self._waiver_pdf())
        f.addRow(b)
        return w

    def _fill_waiver_defaults(self):
        self.w_app.blockSignals(True)
        self.w_app.clear()
        self.w_app.addItem("(none)", None)
        for a in self.data["payapps"]:
            self.w_app.addItem(f"No. {a['no']} to {a['period_to']}", a["no"])
        self.w_app.setCurrentIndex(self.w_app.count() - 1)
        self.w_app.blockSignals(False)
        self.w_claimant.setText(self.data["info"].get("contractor", ""))
        self.w_payer.setText(self.data["info"].get("owner", ""))
        self._waiver_app()

    def _waiver_app(self):
        no = self.w_app.currentData()
        if no is None:
            return
        v = money.compute(self.doc, no)
        self.w_amount.setValue(max(0.0, v["g702"]["8"]))
        self.w_through.setDate(QDate.fromString(v["period_to"],
                                                "yyyy-MM-dd"))

    def _waiver_pdf(self, path=None):
        kind = self.w_kind.currentData()
        rec = self._try(money.waiver, self.doc, kind, _ds(self.w_through),
                        self.w_amount.value(), self.w_claimant.text(),
                        self.w_payer.text(), app_no=self.w_app.currentData())
        if not rec:
            return None
        path = path or self._save_path(
            "Lien Waiver",
            self._rname("Lien Waiver", ".pdf", when=rec.get("through")),
            "PDF (*.pdf)")
        if path:
            money.waiver_pdf(self.doc, rec, path)
            self._open_file(path)
        return path


class ChangeDialog(QDialog):
    """New or edit a change: title, reason, amount (or cost + markup)."""

    def __init__(self, parent, change=None, refs=None, cost=None):
        super().__init__(parent)
        c = change or {}
        self.refs = refs if refs is not None else c.get("refs") or []
        self.setWindowTitle(f"Change {c.get('id', '')}".strip())
        f = QFormLayout(self)
        self.title = QLineEdit(c.get("title", ""))
        f.addRow("Title:", self.title)
        self.reason = QPlainTextEdit(c.get("reason", ""))
        self.reason.setPlaceholderText("What changed and why (owner request, "
                                       "RFI answer, field condition…)")
        self.reason.setMaximumHeight(110)
        f.addRow("Description:", self.reason)
        self.rfi = QLineEdit(c.get("rfi", ""))
        self.rfi.setPlaceholderText("e.g. RFI-004")
        f.addRow("RFI:", self.rfi)
        cost = c.get("cost") if cost is None else cost
        self.cost = QDoubleSpinBox()
        self.cost.setRange(-1e9, 1e9)
        self.cost.setDecimals(2)
        self.cost.setPrefix("$ ")
        self.cost.setValue(float(cost or 0))
        f.addRow("Cost:", self.cost)
        self.markup = QDoubleSpinBox()
        self.markup.setRange(0, 100)
        self.markup.setDecimals(2)
        self.markup.setSuffix(" %")
        self.markup.setValue(float(c.get("markup_pct") if c.get(
            "markup_pct") is not None else 15))
        f.addRow("Overhead && profit:", self.markup)
        self.amount = QDoubleSpinBox()
        self.amount.setRange(-1e9, 1e9)
        self.amount.setDecimals(2)
        self.amount.setPrefix("$ ")
        f.addRow("Amount (change in contract sum):", self.amount)
        self.days = QSpinBox()
        self.days.setRange(-3650, 3650)
        self.days.setValue(int(c.get("days") or 0))
        f.addRow("Change in contract time (days):", self.days)
        if self.refs:
            f.addRow(QLabel(f"Priced from {len(self.refs)} takeoff "
                            f"measurement(s)."))
        self.cost.valueChanged.connect(self._price)
        self.markup.valueChanged.connect(self._price)
        if c.get("amount") is not None and change:
            self.amount.setValue(float(c["amount"]))
        else:
            self._price()
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        f.addRow(bb)

    def _price(self, *_):
        if self.cost.value():
            self.amount.setValue(_c2(self.cost.value() *
                                       (1 + self.markup.value() / 100)))

    def values(self):
        return {"title": self.title.text(),
                "reason": self.reason.toPlainText(),
                "rfi": self.rfi.text().strip(),
                "amount": self.amount.value(), "days": self.days.value(),
                "cost": self.cost.value() if self.cost.value() else None,
                "markup_pct": self.markup.value()
                if self.cost.value() else None,
                "refs": self.refs}

    def accept(self):
        if not self.title.text().strip():
            QMessageBox.warning(self, "Change", "Give the change a title.")
            return
        super().accept()
