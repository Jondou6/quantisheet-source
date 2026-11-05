"""Document Control window (drawing register, transmittals, addenda) and
Quality window (punch list, three-phase inspections)."""
import os

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDateEdit, QDialog,
    QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QHeaderView,
    QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMessageBox, QPlainTextEdit, QPushButton, QTableWidget, QTableWidgetItem,
    QTabWidget, QVBoxLayout, QWidget)

from . import theme as _theme
from . import doccontrol, qa

RED = QColor(255, 225, 225)


def _item(text, data=None, editable=False):
    it = QTableWidgetItem("" if text is None else str(text))
    if not editable:
        it.setFlags(it.flags() & ~Qt.ItemIsEditable)
    if data is not None:
        it.setData(Qt.UserRole, data)
    return it


def _date(s=None, blank=False):
    d = QDateEdit()
    d.setCalendarPopup(True)
    d.setDisplayFormat("yyyy-MM-dd")
    if blank:
        d.setSpecialValueText(" ")
        d.setMinimumDate(QDate(2000, 1, 1))
    q = QDate.fromString(s, "yyyy-MM-dd") if s else None
    if q is not None and q.isValid():
        d.setDate(q)
    elif blank:
        d.setDate(d.minimumDate())
    else:
        d.setDate(QDate.currentDate())
    return d


def _ds(d):
    if d.specialValueText() and d.date() == d.minimumDate():
        return ""
    return d.date().toString("yyyy-MM-dd")


def _table(headers, stretch=1):
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.horizontalHeader().setSectionResizeMode(stretch, QHeaderView.Stretch)
    t.setSelectionBehavior(QAbstractItemView.SelectRows)
    t.setEditTriggers(QAbstractItemView.NoEditTriggers)
    return t


def _buttons(pairs):
    row = QHBoxLayout()
    for label, fn in pairs:
        b = QPushButton(label)
        b.clicked.connect(fn)
        row.addWidget(b)
    row.addStretch()
    return row


class _Base(QDialog):
    edited = Signal()
    go_to = Signal(int, object)          # page, markup ref or None

    def __init__(self, doc, parent, title):
        super().__init__(parent)
        self.doc = doc
        self.setWindowTitle(title)
        self.resize(1050, 640)

    def _try(self, fn, *a, **k):
        try:
            out = fn(*a, **k)
        except (doccontrol.DocControlError, qa.QAError, KeyError,
                ValueError) as e:
            QMessageBox.warning(self, self.windowTitle(), str(e).strip("'"))
            return None
        self.edited.emit()
        self.refresh()
        return out if out is not None else True

    def _save_path(self, title, name, filt):
        base = os.path.dirname(self.doc.name or "") or os.path.expanduser("~")
        path, _ = QFileDialog.getSaveFileName(self, title,
                                              os.path.join(base, name), filt)
        return path

    def _open_file(self, path):
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _rname(self, kind, ext, number=None, when=None):
        """Default report file name - company rule, date first
        (app/reportname.py)."""
        from .reportname import report_file_name
        return report_file_name(kind, self.project(), number, when, ext)

    def _export(self, fn, title, name, filt, *args):
        path = self._save_path(title, name, filt)
        if path:
            fn(self.doc, *args, path) if args else fn(self.doc, path)
            if path.lower().endswith(".pdf"):
                self._open_file(path)
        return path

    @staticmethod
    def _current(table):
        r = table.currentRow()
        it = table.item(r, 0) if r >= 0 else None
        return it.data(Qt.UserRole) if it else None

    def project(self):
        try:
            from . import money
            return money.read(self.doc)["info"].get("project", "")
        except Exception:
            return ""


# ---- document control ----------------------------------------------------------

class DocControlDialog(_Base):
    def __init__(self, doc, parent=None):
        super().__init__(doc, parent, "Document Control")
        lay = QVBoxLayout(self)
        self.tabs = QTabWidget()
        lay.addWidget(self.tabs)

        # register
        w = QWidget()
        v = QVBoxLayout(w)
        self.reg = _table(["Sheet", "Title", "Discipline", "Page", "Rev",
                           "Rev date", "Description"])
        self.reg.itemDoubleClicked.connect(self._reg_go)
        v.addWidget(self.reg)
        v.addLayout(_buttons([
            ("Read Sheets From Title Blocks", self.scan),
            ("Add Sheet…", self._reg_add), ("Edit…", self._reg_edit),
            ("Record Revision…", self._reg_rev),
            ("Transmit Selected…", self._reg_transmit),
            ("Print…", lambda: self._export(
                lambda d, p: doccontrol.register_pdf(d, p, self.project()),
                "Drawing Register", self._rname("Drawing Register", ".pdf"),
                "PDF (*.pdf)")),
            ("Excel…", lambda: self._export(
                doccontrol.register_xlsx, "Drawing Register",
                self._rname("Drawing Register", ".xlsx"),
                "Excel (*.xlsx)"))]))
        self.reg.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.reg_note = QLabel("")
        v.addWidget(self.reg_note)
        self.tabs.addTab(w, "Drawing Register")

        # transmittals
        w = QWidget()
        v = QVBoxLayout(w)
        self.trs = _table(["No.", "To", "Date", "Purpose", "Sent by",
                           "Items", "Due", "Received"], 1)
        v.addWidget(self.trs)
        v.addLayout(_buttons([
            ("New Transmittal…", lambda: self.new_transmittal()),
            ("Mark Received…", self._tr_ack),
            ("Print…", self._tr_pdf)]))
        self.tabs.addTab(w, "Transmittals")

        # addenda
        w = QWidget()
        v = QVBoxLayout(w)
        self.adds = _table(["No.", "Title", "Issued", "Sheets", "Bidders",
                            "Not acknowledged", "Priced", "Cost impact"], 1)
        v.addWidget(self.adds)
        v.addLayout(_buttons([
            ("New Addendum…", lambda: self.new_addendum()),
            ("Record Acknowledgement…", self._add_ack),
            ("Mark Priced…", lambda: self.mark_priced()),
            ("Print Log…", lambda: self._export(
                lambda d, p: doccontrol.addenda_pdf(d, p, self.project()),
                "Addenda Log", self._rname("Addenda Log", ".pdf"),
                "PDF (*.pdf)"))]))
        self.tabs.addTab(w, "Addenda")
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.close)
        lay.addWidget(bb)
        self.refresh()

    def refresh(self):
        data = doccontrol.read(self.doc)
        rows = doccontrol.register(self.doc, data)
        self.reg.setRowCount(len(rows))
        for r, s in enumerate(rows):
            vals = [s["number"], s["title"], s["discipline"],
                    "" if s["page"] is None else s["page"] + 1, s["rev"],
                    s["rev_date"], s["rev_desc"]]
            for c, val in enumerate(vals):
                it = _item(val, s["number"])
                if s["page"] is None:
                    it.setForeground(QColor(150, 150, 150))
                self.reg.setItem(r, c, it)
        self.reg_note.setText(
            f"{len(rows)} sheets. Grey = not in this PDF. Double-click a "
            "sheet to go to it." if rows else
            "No sheets yet: Read Sheets From Title Blocks.")
        trs = data["transmittals"]
        today = doccontrol._today()
        self.trs.setRowCount(len(trs))
        for r, t in enumerate(trs):
            late = not t["acks"] and t.get("due") and t["due"] < today
            vals = [t["id"], t["to"], t["date"], t["purpose"], t["method"],
                    len(t["items"]), t.get("due", ""),
                    ", ".join(f"{a['who']} {a['date']}" for a in t["acks"])
                    or ("OVERDUE" if late else "")]
            for c, val in enumerate(vals):
                it = _item(val, t["id"])
                if late:
                    _theme.tint(it, RED)
                self.trs.setItem(r, c, it)
        adds = data["addenda"]
        missing = doccontrol.unacknowledged(self.doc)
        self.adds.setRowCount(len(adds))
        for r, a in enumerate(adds):
            vals = [a["no"], a["title"], a["issued"], ", ".join(a["sheets"]),
                    len(a["bidders"]), ", ".join(missing.get(a["id"], [])),
                    a.get("priced_on", "") if a.get("priced") else
                    "NOT PRICED", a.get("cost", "")]
            for c, val in enumerate(vals):
                it = _item(val, a["id"])
                if missing.get(a["id"]):
                    _theme.tint(it, RED) if c == 5 else None
                if c == 6 and not a.get("priced"):
                    _theme.tint(it, RED)
                self.adds.setItem(r, c, it)

    # register
    def scan(self):
        found = self._try(doccontrol.scan_register, self.doc)
        if found:
            n, missing = found
            msg = f"Found {n} sheet(s)."
            if missing:
                msg += (f" {len(missing)} page(s) had no sheet number "
                        "(scans need Make Searchable first).")
            self.reg_note.setText(msg)
        return found

    def _reg_go(self, it):
        num = it.data(Qt.UserRole)
        s = doccontrol.read(self.doc)["sheets"].get(num)
        if s and s.get("page") is not None:
            self.go_to.emit(int(s["page"]), None)

    def _reg_add(self):
        num, ok = QInputDialog.getText(self, "Add Sheet", "Sheet number:")
        if not ok or not num.strip():
            return None
        title, ok = QInputDialog.getText(self, "Add Sheet", "Title:")
        if not ok:
            return None
        return self._try(doccontrol.set_sheet, self.doc, num, title)

    def _reg_edit(self):
        num = self._current(self.reg)
        if not num:
            return None
        s = doccontrol.read(self.doc)["sheets"][num]
        title, ok = QInputDialog.getText(self, f"Sheet {num}", "Title:",
                                         QLineEdit.Normal, s.get("title", ""))
        if not ok:
            return None
        return self._try(doccontrol.set_sheet, self.doc, num, title)

    def _selected_sheets(self):
        rows = sorted({i.row() for i in self.reg.selectedItems()})
        return [self.reg.item(r, 0).data(Qt.UserRole) for r in rows]

    def _reg_rev(self):
        nums = self._selected_sheets()
        if not nums:
            QMessageBox.information(self, "Record Revision",
                                    "Select the sheets that were revised.")
            return None
        dlg = QDialog(self)
        dlg.setWindowTitle("Record Revision")
        f = QFormLayout(dlg)
        f.addRow(QLabel(", ".join(nums)))
        rev = QLineEdit()
        rev.setPlaceholderText("e.g. 2 or B")
        f.addRow("Revision:", rev)
        date = _date()
        f.addRow("Date:", date)
        desc = QLineEdit()
        desc.setPlaceholderText("e.g. Addendum 1, ASI 3, Bulletin 2")
        f.addRow("Description:", desc)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        f.addRow(bb)
        if dlg.exec() != QDialog.Accepted:
            return None
        return self._try(doccontrol.add_revision, self.doc, nums,
                         rev.text(), _ds(date), desc.text())

    def _reg_transmit(self):
        nums = self._selected_sheets()
        return self.new_transmittal(doccontrol.items_for_sheets(self.doc,
                                                                nums))

    # transmittals
    def new_transmittal(self, items=None, values=None):
        if values is None:
            dlg = TransmittalDialog(self, items or [])
            if dlg.exec() != QDialog.Accepted:
                return None
            values = dlg.values()
        tid = self._try(doccontrol.new_transmittal, self.doc, **values)
        if tid:
            self.tabs.setCurrentIndex(1)
        return tid

    def _tr_ack(self):
        tid = self._current(self.trs)
        if not tid:
            return None
        who, ok = QInputDialog.getText(self, "Mark Received",
                                       "Received by:")
        if not ok:
            return None
        return self._try(doccontrol.acknowledge, self.doc, tid, who)

    def _tr_pdf(self):
        tid = self._current(self.trs)
        if not tid:
            return None
        return self._export(lambda d, p: doccontrol.transmittal_pdf(
            d, tid, p, self.project()), "Transmittal",
            self._rname("Transmittal", ".pdf", str(tid).rsplit("-", 1)[-1],
                        next((t.get("date") for t in
                              doccontrol.read(self.doc)["transmittals"]
                              if t.get("id") == tid), None)),
            "PDF (*.pdf)")

    # addenda
    def new_addendum(self, values=None):
        if values is None:
            dlg = QDialog(self)
            dlg.setWindowTitle("New Addendum")
            f = QFormLayout(dlg)
            title = QLineEdit()
            f.addRow("Title:", title)
            issued = _date()
            f.addRow("Issued:", issued)
            desc = QPlainTextEdit()
            desc.setMaximumHeight(100)
            f.addRow("Changes:", desc)
            sheets = QLineEdit(", ".join(self._selected_sheets()))
            sheets.setPlaceholderText("A-101, A-201")
            f.addRow("Sheets affected:", sheets)
            bidders = QPlainTextEdit()
            bidders.setPlaceholderText("One bidder per line")
            bidders.setMaximumHeight(90)
            f.addRow("Bidders:", bidders)
            bb = QDialogButtonBox(QDialogButtonBox.Ok |
                                  QDialogButtonBox.Cancel)
            bb.accepted.connect(dlg.accept)
            bb.rejected.connect(dlg.reject)
            f.addRow(bb)
            if dlg.exec() != QDialog.Accepted:
                return None
            values = {"title": title.text(), "issued": _ds(issued),
                      "desc": desc.toPlainText(),
                      "sheets": [s.strip() for s in sheets.text().split(",")
                                 if s.strip()],
                      "bidders": bidders.toPlainText().splitlines()}
        return self._try(doccontrol.add_addendum, self.doc, **values)

    def mark_priced(self, values=None):
        """Addenda Gate: this addendum is in the numbers - its cost impact
        (0 if none) and, optionally, the estimate line it went into."""
        aid = self._current(self.adds)
        if not aid:
            return None
        if values is None:
            from . import estimate_lines
            dlg = QDialog(self)
            dlg.setWindowTitle("Mark Addendum Priced")
            f = QFormLayout(dlg)
            cost = QLineEdit("0")
            f.addRow("Cost impact ($):", cost)
            line = QComboBox()
            line.addItem("(no particular line)", "")
            for ln in estimate_lines.read(self.doc):
                line.addItem(f"{ln['desc'] or ln['code']}"[:70], ln["id"])
            f.addRow("Estimate line:", line)
            got = _date()
            f.addRow("Received:", got)
            note = QLineEdit()
            f.addRow("Note:", note)
            bb = QDialogButtonBox(QDialogButtonBox.Ok |
                                  QDialogButtonBox.Cancel)
            bb.accepted.connect(dlg.accept)
            bb.rejected.connect(dlg.reject)
            f.addRow(bb)
            if dlg.exec() != QDialog.Accepted:
                return None
            values = {"cost": cost.text(), "line_id": line.currentData(),
                      "received": _ds(got), "note": note.text()}
        return self._try(doccontrol.price_addendum, self.doc, aid, **values)

    def _add_ack(self):
        aid = self._current(self.adds)
        if not aid:
            return None
        a = next(x for x in doccontrol.addenda(self.doc) if x["id"] == aid)
        left = doccontrol.unacknowledged(self.doc).get(aid, [])
        if left:
            who, ok = QInputDialog.getItem(self, "Acknowledgement",
                                           "Bidder:", left, 0, True)
        else:
            who, ok = QInputDialog.getText(self, "Acknowledgement",
                                           "Bidder:")
        if not ok or not str(who).strip():
            return None
        return self._try(doccontrol.ack_addendum, self.doc, a["id"], who)


class TransmittalDialog(QDialog):
    def __init__(self, parent, items):
        super().__init__(parent)
        self.setWindowTitle("New Transmittal")
        self.resize(760, 560)
        f = QFormLayout(self)
        self.to = QLineEdit()
        f.addRow("To:", self.to)
        self.cc = QLineEdit()
        f.addRow("CC:", self.cc)
        self.purpose = QComboBox()
        self.purpose.addItems(doccontrol.PURPOSES)
        self.purpose.setEditable(True)
        f.addRow("Purpose:", self.purpose)
        self.method = QComboBox()
        self.method.addItems(doccontrol.METHODS)
        self.method.setEditable(True)
        f.addRow("Sent by:", self.method)
        self.due = _date(blank=True)
        f.addRow("Response due:", self.due)
        self.items = QTableWidget(0, 5)
        self.items.setHorizontalHeaderLabels(["Document / sheet",
                                              "Description", "Rev", "Date",
                                              "Copies"])
        self.items.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.Stretch)
        for it in items:
            self._add(it)
        if not items:
            self._add({})
        f.addRow(self.items)
        row = _buttons([("Add Line", lambda: self._add({})),
                        ("Remove Line", lambda: self.items.removeRow(
                            self.items.currentRow()))])
        f.addRow(row)
        self.notes = QPlainTextEdit()
        self.notes.setMaximumHeight(80)
        f.addRow("Remarks:", self.notes)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        f.addRow(bb)

    def _add(self, it):
        r = self.items.rowCount()
        self.items.insertRow(r)
        for c, k in enumerate(("doc", "desc", "rev", "date", "copies")):
            self.items.setItem(r, c, QTableWidgetItem(
                str(it.get(k, 1 if k == "copies" else ""))))

    def values(self):
        rows = []
        for r in range(self.items.rowCount()):
            cell = [self.items.item(r, c).text().strip()
                    if self.items.item(r, c) else "" for c in range(5)]
            rows.append({"doc": cell[0], "desc": cell[1], "rev": cell[2],
                         "date": cell[3], "copies": cell[4] or "1"})
        return {"to": self.to.text(), "cc": self.cc.text(),
                "purpose": self.purpose.currentText(),
                "method": self.method.currentText(), "due": _ds(self.due),
                "notes": self.notes.toPlainText(), "items": rows}


# ---- quality --------------------------------------------------------------------

class QualityDialog(_Base):
    def __init__(self, doc, parent=None, where=None, selected=None):
        """where() -> (page, unrotated point) to pin new items at;
        selected() -> (page, ref) of the selected markup, or None."""
        super().__init__(doc, parent, "Quality: Punch List & Inspections")
        self.where = where or (lambda: None)
        self.selected = selected or (lambda: None)
        lay = QVBoxLayout(self)
        self.tabs = QTabWidget()
        lay.addWidget(self.tabs)

        w = QWidget()
        v = QVBoxLayout(w)
        top = QHBoxLayout()
        top.addWidget(QLabel("Show:"))
        self.filter = QComboBox()
        self.filter.addItem("Open and ready for review", "active")
        self.filter.addItem("All", "all")
        for s in qa.STATUSES:
            self.filter.addItem(qa.STATUS_LABEL[s], s)
        self.filter.currentIndexChanged.connect(lambda *_: self.refresh())
        top.addWidget(self.filter)
        top.addWidget(QLabel("Trade:"))
        self.trade = QComboBox()
        self.trade.currentIndexChanged.connect(lambda *_: self._fill_punch())
        top.addWidget(self.trade)
        top.addStretch()
        self.counts = QLabel("")
        top.addWidget(self.counts)
        v.addLayout(top)
        self.pl = _table(["No.", "Description", "Location", "Trade",
                          "Assigned to", "Priority", "Due", "Status",
                          "Page"], 1)
        self.pl.itemDoubleClicked.connect(self._pl_go)
        v.addWidget(self.pl)
        v.addLayout(_buttons([
            ("New Item…", lambda: self.new_punch()),
            ("Edit…", self._pl_edit),
            ("Ready for Review", lambda: self._pl_status("ready")),
            ("Close (Verified)", lambda: self._pl_status("closed")),
            ("Reopen", lambda: self._pl_status("open")),
            ("Void", lambda: self._pl_status("void")),
            ("Print…", self._pl_pdf),
            ("Excel…", lambda: self._export(qa.punch_xlsx, "Punch List",
                                            self._rname("Punch List",
                                                        ".xlsx"),
                                            "Excel (*.xlsx)"))]))
        self.tabs.addTab(w, "Punch List")

        w = QWidget()
        v = QVBoxLayout(w)
        self.ins = _table(["No.", "Phase", "Feature of work", "Area",
                           "Trade", "Date", "Result", "Deficiencies"], 2)
        self.ins.itemDoubleClicked.connect(lambda *_: self._ins_open())
        v.addWidget(self.ins)
        v.addLayout(_buttons([
            ("New Inspection…", lambda: self.new_inspection()),
            ("Open Checklist…", self._ins_open),
            ("Start Next Phase", self._ins_next),
            ("Print…", self._ins_pdf)]))
        self.tabs.addTab(w, "Three-Phase Inspections")
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.close)
        lay.addWidget(bb)
        self.refresh()

    def refresh(self):
        data = qa.read(self.doc)
        trades = sorted({p.get("trade") for p in data["punch"]
                         if p.get("trade")})
        cur = self.trade.currentData()
        self.trade.blockSignals(True)
        self.trade.clear()
        self.trade.addItem("All trades", None)
        for t in trades:
            self.trade.addItem(t, t)
        i = self.trade.findData(cur)
        self.trade.setCurrentIndex(max(0, i))
        self.trade.blockSignals(False)
        self._fill_punch(data)
        ins = data["inspections"]
        self.ins.setRowCount(len(ins))
        for r, x in enumerate(ins):
            res = {"open": "Open", "passed": "Passed",
                   "failed": "Failed"}[x["status"]]
            vals = [x["id"], qa.PHASE_LABEL[x["phase"]], x["feature"],
                    x.get("area", ""), x.get("trade", ""), x["date"], res,
                    ", ".join(x.get("punch", []))]
            for c, val in enumerate(vals):
                it = _item(val, x["id"])
                if x["status"] == "failed":
                    _theme.tint(it, RED)
                self.ins.setItem(r, c, it)

    def _fill_punch(self, data=None):
        data = data or qa.read(self.doc)
        f = self.filter.currentData()
        t = self.trade.currentData()
        items = [p for p in data["punch"]
                 if (f == "all" or (f == "active" and p["status"] in
                                    ("open", "ready")) or p["status"] == f)
                 and (not t or p.get("trade") == t)]
        self.pl.setRowCount(len(items))
        for r, p in enumerate(items):
            vals = [p["id"], p["description"], p.get("location", ""),
                    p.get("trade", ""), p.get("assignee", ""), p["priority"],
                    p.get("due", ""), qa.STATUS_LABEL[p["status"]],
                    "" if p.get("page") is None else p["page"] + 1]
            for c, val in enumerate(vals):
                it = _item(val, p["id"])
                if qa.is_overdue(p):
                    _theme.tint(it, RED)
                self.pl.setItem(r, c, it)
        s = qa.summary(self.doc)
        self.counts.setText(
            f"Open {s['by_status']['open']}  Ready {s['by_status']['ready']}"
            f"  Closed {s['by_status']['closed']}  Overdue {s['overdue']}")
        self.shown = items

    # punch
    def new_punch(self, values=None, link=None):
        """`link`: "selected" (attach to the selected markup), "pin" (drop
        a marker in the middle of the view) or None."""
        if values is None:
            dlg = PunchDialog(self, has_selection=bool(self.selected()))
            if dlg.exec() != QDialog.Accepted:
                return None
            values, link = dlg.values(), dlg.link()
        sel = self.selected() if link == "selected" else None
        if sel:
            values = dict(values, page=sel[0], ref=sel[1])
        pid = self._try(qa.add_punch, self.doc, **values)
        if pid and link == "pin":
            spot = self.where()
            if spot:
                self._try(qa.pin, self.doc, pid, spot[0], spot[1])
        return pid

    def _pl_edit(self):
        pid = self._current(self.pl)
        if not pid:
            return None
        dlg = PunchDialog(self, qa.get_punch(self.doc, pid))
        if dlg.exec() != QDialog.Accepted:
            return None
        return self._try(qa.update_punch, self.doc, pid, **dlg.values())

    def _pl_status(self, status):
        pid = self._current(self.pl)
        if not pid:
            QMessageBox.information(self, "Punch List",
                                    "Select an item first.")
            return None
        return self._try(qa.set_status, self.doc, pid, status)

    def _pl_go(self, it):
        p = qa.get_punch(self.doc, it.data(Qt.UserRole))
        if p.get("page") is not None:
            self.go_to.emit(int(p["page"]), p.get("ref"))

    def _pl_pdf(self):
        items = getattr(self, "shown", None)
        trade = self.trade.currentData()
        title = f"Punch List - {trade}" if trade else "Punch List"
        return self._export(lambda d, p: qa.punch_pdf(
            d, p, items, self.project(), title), "Punch List",
            self._rname(title, ".pdf"), "PDF (*.pdf)")

    # inspections
    def new_inspection(self, values=None):
        if values is None:
            dlg = InspectionDialog(self)
            if dlg.exec() != QDialog.Accepted:
                return None
            values = dlg.values()
        iid = self._try(qa.new_inspection, self.doc, **values)
        if iid:
            self.tabs.setCurrentIndex(1)
        return iid

    def _ins_open(self):
        iid = self._current(self.ins)
        if not iid:
            return None
        dlg = ChecklistDialog(self, self.doc, iid)
        dlg.exec()
        self.edited.emit()
        self.refresh()
        return dlg

    def _ins_next(self):
        iid = self._current(self.ins)
        return iid and self._try(qa.next_phase, self.doc, iid)

    def _ins_pdf(self):
        iid = self._current(self.ins)
        if not iid:
            return None
        return self._export(lambda d, p: qa.inspection_pdf(
            d, iid, p, self.project()), "Inspection",
            self._rname("Inspection", ".pdf", str(iid).rsplit("-", 1)[-1],
                        qa.get_inspection(self.doc, iid).get("date")),
            "PDF (*.pdf)")


class PunchDialog(QDialog):
    def __init__(self, parent, item=None, has_selection=False):
        super().__init__(parent)
        p = item or {}
        self.setWindowTitle(f"Punch Item {p.get('id', '')}".strip())
        f = QFormLayout(self)
        self.desc = QLineEdit(p.get("description", ""))
        f.addRow("Description:", self.desc)
        self.loc = QLineEdit(p.get("location", ""))
        self.loc.setPlaceholderText("e.g. Room 204, north wall")
        f.addRow("Location:", self.loc)
        self.trade = QLineEdit(p.get("trade", ""))
        f.addRow("Trade:", self.trade)
        self.assignee = QLineEdit(p.get("assignee", ""))
        f.addRow("Assigned to:", self.assignee)
        self.priority = QComboBox()
        for x in qa.PRIORITIES:
            self.priority.addItem(x.title(), x)
        self.priority.setCurrentIndex(max(0, self.priority.findData(
            p.get("priority", "normal"))))
        f.addRow("Priority:", self.priority)
        self.due = _date(p.get("due"), blank=True)
        f.addRow("Due:", self.due)
        self.where = None
        if item is None:
            self.where = QComboBox()
            if has_selection:
                self.where.addItem("Attach to the selected markup",
                                   "selected")
            self.where.addItem("Pin a marker in the middle of the view",
                               "pin")
            self.where.addItem("Don't place on the drawing", None)
            f.addRow("On the drawing:", self.where)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        f.addRow(bb)

    def link(self):
        return self.where.currentData() if self.where else None

    def values(self):
        return {"description": self.desc.text(), "location": self.loc.text(),
                "trade": self.trade.text(), "assignee": self.assignee.text(),
                "priority": self.priority.currentData(), "due": _ds(self.due)}

    def accept(self):
        if not self.desc.text().strip():
            QMessageBox.warning(self, "Punch Item", "Describe the item.")
            return
        super().accept()


class InspectionDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("New Inspection")
        self.resize(620, 560)
        f = QFormLayout(self)
        self.phase = QComboBox()
        for k in qa.PHASES:
            self.phase.addItem(qa.PHASE_LABEL[k], k)
        self.phase.currentIndexChanged.connect(self._load)
        f.addRow("Phase:", self.phase)
        self.feature = QLineEdit()
        self.feature.setPlaceholderText("e.g. Metal stud framing")
        f.addRow("Feature of work:", self.feature)
        self.area = QLineEdit()
        f.addRow("Area:", self.area)
        self.trade = QLineEdit()
        f.addRow("Trade:", self.trade)
        self.spec = QLineEdit()
        self.spec.setPlaceholderText("e.g. 09 22 16")
        f.addRow("Spec section:", self.spec)
        self.attendees = QLineEdit()
        f.addRow("Attendees:", self.attendees)
        self.date = _date()
        f.addRow("Date:", self.date)
        self.checks = QPlainTextEdit()
        f.addRow("Checklist (one per line):", self.checks)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        f.addRow(bb)
        self._load()

    def _load(self, *_):
        self.checks.setPlainText("\n".join(
            qa.templates()[self.phase.currentData()]))

    def values(self):
        return {"phase": self.phase.currentData(),
                "feature": self.feature.text(), "area": self.area.text(),
                "trade": self.trade.text(), "spec": self.spec.text(),
                "attendees": self.attendees.text(), "date": _ds(self.date),
                "checks": [c for c in self.checks.toPlainText().splitlines()
                           if c.strip()]}

    def accept(self):
        if not self.feature.text().strip():
            QMessageBox.warning(self, "Inspection",
                                "Name the feature of work.")
            return
        super().accept()


class ChecklistDialog(QDialog):
    """Answer an inspection's checks; close it to send failures to the
    punch list."""

    def __init__(self, parent, doc, iid):
        super().__init__(parent)
        self.doc, self.iid = doc, iid
        i = qa.get_inspection(doc, iid)
        self.setWindowTitle(f"{i['id']} {qa.PHASE_LABEL[i['phase']]} - "
                            f"{i['feature']}")
        self.resize(820, 520)
        v = QVBoxLayout(self)
        self.table = QTableWidget(len(i["items"]), 3)
        self.table.setHorizontalHeaderLabels(["Check", "Result", "Note"])
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.Stretch)
        self.locked = i["status"] != "open"
        self.combos = []
        for r, x in enumerate(i["items"]):
            self.table.setItem(r, 0, _item(x["check"]))
            cb = QComboBox()
            cb.addItem("", "")
            for res in qa.RESULTS:
                cb.addItem(res.upper(), res)
            cb.setCurrentIndex(max(0, cb.findData(x["result"])))
            cb.setEnabled(not self.locked)
            self.table.setCellWidget(r, 1, cb)
            self.combos.append(cb)
            self.table.setItem(r, 2, _item(x.get("note", ""),
                                           editable=not self.locked))
        v.addWidget(self.table)
        self.status = QLabel("Closed: " + i["status"] if self.locked else
                             "FAIL items become punch items when you close "
                             "the inspection.")
        v.addWidget(self.status)
        bb = QDialogButtonBox()
        if not self.locked:
            save = bb.addButton("Save", QDialogButtonBox.ApplyRole)
            save.clicked.connect(self.save)
            close = bb.addButton("Close Inspection",
                                 QDialogButtonBox.AcceptRole)
            close.clicked.connect(self.close_inspection)
        bb.addButton(QDialogButtonBox.Cancel if not self.locked else
                     QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def set_result(self, row, result, note=None):
        self.combos[row].setCurrentIndex(self.combos[row].findData(result))
        if note is not None:
            self.table.item(row, 2).setText(note)

    def save(self):
        for r, cb in enumerate(self.combos):
            qa.answer(self.doc, self.iid, r, cb.currentData(),
                      self.table.item(r, 2).text())
        return True

    def close_inspection(self):
        self.save()
        try:
            i = qa.close_inspection(self.doc, self.iid)
        except qa.QAError as e:
            QMessageBox.warning(self, "Inspection", str(e))
            return None
        self.accept()
        return i
