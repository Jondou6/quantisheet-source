"""Estimate > Bid Form Workbook, and the Builder's Risk Quote Request
window (logic: bidform_xl.py, builders_risk.py)."""
import os

import fitz
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFileDialog,
                               QFormLayout, QLabel, QLineEdit, QMessageBox,
                               QPlainTextEdit, QPushButton, QVBoxLayout)

from . import bidform_xl as BX


class BidFormWorkbook(QDialog):
    """From the owner's bid form: the Excel workbook for the estimator, and
    the calculating bid form PDF filled from it with one click."""

    def __init__(self, parent=None, source=None, project="",
                 open_result=None, open_file=None):
        super().__init__(parent)
        self.setWindowTitle("Bid Form Workbook")
        self.resize(640, 420)
        self.open_result = open_result
        self.open_file = open_file or (lambda p: os.startfile(p))
        self.project = project
        self.src = None
        self.doc = None
        self.form = None
        self.book_path = None
        lay = QVBoxLayout(self)
        self.note = QLabel("Pick the bid form: the spec book (project "
                           "manual) or the bid form PDF itself.")
        self.note.setWordWrap(True)
        lay.addWidget(self.note)
        for text, fn in (("Pick Bid Form or Spec Book…", self.pick),
                         ("Make Excel Workbook", self.make_book),
                         ("Open Workbook", self.open_book),
                         ("Transfer to PDF", self.transfer),
                         ("Check an Addendum…", self.check_addendum)):
            b = QPushButton(text)
            b.clicked.connect(lambda _c=False, f=fn: f())
            lay.addWidget(b)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        if source:
            self.pick(source)

    def _say(self, text):
        self.note.setText(text)

    def pick(self, path=None):
        if path is None:
            path, _ = QFileDialog.getOpenFileName(self, "Bid Form", "",
                                                  "PDF (*.pdf)")
            if not path:
                return None
        from . import specs
        self.src, self.doc = path, fitz.open(path)
        try:
            secs = specs.find_sections(self.doc)
        except Exception:                                 # noqa: BLE001
            secs = []
        self.form = BX.read_form(self.doc, secs)
        if not self.project:
            self.project = os.path.splitext(os.path.basename(path))[0]
        f = self.form
        if not f["pages"]:
            self._say("No bid form found in that PDF (no page headed Bid "
                      "Form, Proposal Form or Bid Schedule).")
        else:
            self._say(f"Bid form on page(s) "
                      f"{', '.join(str(p + 1) for p in f['pages'][:8])}: "
                      f"{len(f['items'])} item(s), {len(f['alternates'])} "
                      f"alternate(s), addenda listed: "
                      f"{', '.join(map(str, f['addenda'])) or 'none'}.")
        self.book_path = self._default_book()
        return f

    def _default_book(self):
        if not self.src:
            return None
        return os.path.join(os.path.dirname(self.src),
                            f"{self.project} - Bid Form Workbook.xlsx")

    def make_book(self, path=None, ask=True):
        if not self.form or not self.form["pages"]:
            QMessageBox.information(self, self.windowTitle(),
                                    "Pick a bid form first.")
            return None
        path = path or self.book_path
        if os.path.exists(path) and ask and QMessageBox.question(
                self, self.windowTitle(),
                f"{os.path.basename(path)} is already there - replace it? "
                "(Prices typed in it would be lost.)") != QMessageBox.Yes:
            return None
        acks = []
        try:
            from . import doccontrol
            v = getattr(self.parent(), "_view", None)
            if v is not None:
                acks = [int(a["no"]) for a in doccontrol.addenda(v.doc)]
        except Exception:                                 # noqa: BLE001
            acks = []
        BX.workbook(self.form, path, self.project, acks)
        self.book_path = path
        self._say(f"Workbook saved: {os.path.basename(path)}. Type the "
                  "yellow cells, save it, then Transfer to PDF.")
        return path

    def open_book(self):
        if self.book_path and os.path.isfile(self.book_path):
            self.open_file(self.book_path)
            return self.book_path
        QMessageBox.information(self, self.windowTitle(),
                                "Make the workbook first.")
        return None

    def transfer(self, out=None):
        if not (self.book_path and os.path.isfile(self.book_path)):
            QMessageBox.information(self, self.windowTitle(),
                                    "Make and fill the workbook first.")
            return None
        try:
            book = BX.read_workbook(self.book_path)
        except Exception as e:                            # noqa: BLE001
            QMessageBox.warning(self, self.windowTitle(),
                                f"The workbook couldn't be read: {e}. Close "
                                "it in Excel and try again.")
            return None
        out = out or os.path.join(os.path.dirname(self.book_path),
                                  f"{self.project} - Bid Form (filled).pdf")
        t = BX.fill_pdf(self.doc, self.form["pages"], book, out,
                        self.project)
        miss = f" Still blank: item(s) {', '.join(t['missing'][:10])}." \
            if t["missing"] else ""
        self._say(f"Bid form filled: base bid ${t['base']:,.2f}. Saved as "
                  f"{os.path.basename(out)}.{miss}")
        if self.open_result:
            self.open_result(out)
        return t

    def check_addendum(self, path=None):
        """Does this addendum change the bid form? If it does, the workbook
        is made again from the new form, keeping the prices of items that
        didn't change."""
        if path is None:
            path, _ = QFileDialog.getOpenFileName(self, "Addendum", "",
                                                  "PDF (*.pdf)")
            if not path:
                return None
        add = fitz.open(path)
        chk = BX.addendum_check(add)
        if not chk["has_form"]:
            self._say(f"{os.path.basename(path)}: no bid form in this "
                      "addendum - the current one stands." +
                      (" It does mention a revised bid form; check the "
                       "addendum text." if chk["revised"] else ""))
            return chk
        ch = BX.compare(self.form or {}, chk["form"])
        chk["changes"] = ch
        msg = (f"{os.path.basename(path)} has a bid form (page "
               f"{', '.join(str(p + 1) for p in chk['pages'][:6])}): "
               f"{BX.change_text(ch)}.")
        old_prices = {}
        if self.book_path and os.path.isfile(self.book_path):
            try:
                for it in BX.read_workbook(self.book_path)["items"]:
                    old_prices[it["no"]] = it.get("price")
            except Exception:                             # noqa: BLE001
                old_prices = {}
        self.src, self.doc, self.form = path, add, dict(chk["form"],
                                                        pages=chk["pages"])
        new_book = os.path.join(
            os.path.dirname(path),
            f"{self.project} - Bid Form Workbook "
            f"({os.path.splitext(os.path.basename(path))[0]}).xlsx")
        BX.workbook(self.form, new_book, self.project)
        if old_prices:
            from openpyxl import load_workbook
            wb = load_workbook(new_book)
            ws = wb["Bid Form"]
            changed = {b["no"] for _a, b in ch["qty"]}
            for r in range(BX.FIRST, ws.max_row + 1):
                no = str(ws.cell(row=r, column=1).value or "")
                if no in old_prices and no not in changed and \
                        old_prices[no] is not None:
                    ws.cell(row=r, column=5, value=float(old_prices[no]))
            wb.save(new_book)
        self.book_path = new_book
        self._say(msg + f" New workbook: {os.path.basename(new_book)} "
                  "(prices kept for items that didn't change).")
        return chk


class BuildersRiskRequest(QDialog):
    """Builder's risk: the summary for the insurance company, saved as a
    PDF and emailed from here."""

    def __init__(self, doc, parent=None, spec_doc=None, spec_items=None,
                 folder=None, open_result=None, send=None):
        super().__init__(parent)
        from . import builders_risk as BR
        self.BR = BR
        self.doc, self.spec_doc, self.spec_items = doc, spec_doc, spec_items
        self.folder = folder
        self.open_result = open_result
        self.send = send
        self.pdf = None
        self.setWindowTitle("Builder's Risk Quote Request")
        self.resize(640, 640)
        v = BR.values(doc, spec_items)
        f = QFormLayout(self)
        self.ed = {}
        for key, label in (("project", "Project"), ("address", "Address"),
                           ("owner", "Owner"),
                           ("amount", "Estimated amount ($)"),
                           ("start", "Estimated start"),
                           ("finish", "Estimated completion")):
            e = QLineEdit(f"{v[key]:,.2f}" if key == "amount" and v[key]
                          else str(v.get(key) or ""))
            f.addRow(label + ":", e)
            self.ed[key] = e
        for key, label in (("work", "Summary of work"),
                           ("requirements", "Builder's risk requirements")):
            e = QPlainTextEdit(str(v.get(key) or ""))
            e.setMaximumHeight(110)
            f.addRow(label + ":", e)
            self.ed[key] = e
        self.base = v
        self.to = QLineEdit(BR.agent())
        self.to.setPlaceholderText("agent@insurance-company.com")
        f.addRow("Email to:", self.to)
        self.msg = QPlainTextEdit()
        self.msg.setPlaceholderText("Anything else for the agent (optional)")
        self.msg.setMaximumHeight(70)
        f.addRow("Note:", self.msg)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        f.addRow(self.status)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        b1 = bb.addButton("Save PDF", QDialogButtonBox.ActionRole)
        b1.clicked.connect(lambda: self.save_pdf())
        b2 = bb.addButton("Email to Insurance", QDialogButtonBox.ActionRole)
        b2.clicked.connect(lambda: self.email())
        bb.rejected.connect(self.reject)
        f.addRow(bb)

    def current(self):
        v = dict(self.base)
        for k, e in self.ed.items():
            v[k] = e.toPlainText() if isinstance(e, QPlainTextEdit) else \
                e.text()
        v["amount"] = BX._d(v["amount"]) or v["amount"]
        return v

    def save_pdf(self, path=None):
        import tempfile
        v = self.current()
        if path is None:
            folder = self.folder if self.folder and os.access(
                self.folder, os.W_OK) else tempfile.mkdtemp(prefix="qs_br_")
            path = os.path.join(folder, self.BR.file_name(v))
        self.BR.request_pdf(v, path, self.spec_doc, self.spec_items)
        self.pdf = path
        self.status.setText(f"Saved {os.path.basename(path)}.")
        if self.open_result:
            self.open_result(path)
        return path

    def email(self):
        to = self.to.text().strip()
        if not to:
            QMessageBox.information(self, self.windowTitle(),
                                    "Type the insurance contact's email "
                                    "first.")
            return None
        if not self.pdf:
            self.save_pdf()
        try:
            how = self.BR.email(self.current(), self.pdf, to,
                                self.msg.toPlainText(), send=self.send)
        except Exception as e:                            # noqa: BLE001
            QMessageBox.warning(self, self.windowTitle(),
                                f"The email couldn't be made: {e}")
            return None
        from . import mail
        try:
            said = mail.describe(how)
        except Exception:                                 # noqa: BLE001
            said = str(how)
        self.status.setText(f"Email to {to}: {said}")
        return how
