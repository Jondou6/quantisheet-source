"""Tools > Package Tracker: the window (logic: packages.py)."""
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox,
                               QComboBox, QDialog, QFormLayout, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QMessageBox,
                               QPlainTextEdit, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout)

from . import packages

COLS = ["Delivered", "Carrier", "Tracking #", "What", "From", "Job",
        "Expected", "Added", "Note", "Status (live)"]
EDITABLE = {3: "what", 4: "vendor", 5: "job", 6: "expected", 8: "note"}
ALL_JOBS = "All jobs"
MAX_OPEN = 10                 # Track All opens at most this many pages


def open_url(u):              # tests replace this
    QDesktopServices.openUrl(QUrl(u))


class PackageTracker(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Package Tracker")
        self.resize(980, 560)
        self.items = packages.load()
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(
            "Type or paste tracking numbers - or paste a whole shipping "
            "email and the numbers are picked out. FedEx, UPS, USPS and "
            "DHL are recognised; Track opens the carrier's own page."))
        top = QHBoxLayout()
        self.entry = QPlainTextEdit()
        self.entry.setPlaceholderText("1Z999AA10123456784\n"
                                      "9400 1000 0000 0000 0000 00")
        self.entry.setFixedHeight(70)
        self.entry.textChanged.connect(self._preview)
        top.addWidget(self.entry, 2)
        form = QFormLayout()
        self.what = QLineEdit()
        self.what.setPlaceholderText("e.g. Tile for Unit 4")
        self.vendor = QLineEdit()
        self.job = QLineEdit()
        self.expected = QLineEdit()
        self.expected.setPlaceholderText("e.g. 11/6 (optional)")
        form.addRow("What:", self.what)
        form.addRow("From:", self.vendor)
        form.addRow("Job:", self.job)
        form.addRow("Expected:", self.expected)
        top.addLayout(form, 2)
        col = QVBoxLayout()
        self.carrier = QComboBox()
        self.carrier.addItems(["Carrier: automatic"] +
                              list(packages.CARRIERS))
        col.addWidget(self.carrier)
        self.add_btn = QPushButton("Add")
        self.add_btn.setDefault(True)
        self.add_btn.clicked.connect(lambda: self.add_from_entry())
        col.addWidget(self.add_btn)
        col.addStretch(1)
        top.addLayout(col, 1)
        lay.addLayout(top)
        self.found = QLabel("")
        lay.addWidget(self.found)
        self.table = QTableWidget(0, len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().hide()
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.Interactive)
        hh.setStretchLastSection(True)
        self.table.cellDoubleClicked.connect(
            lambda r, c: c not in EDITABLE and c != 0 and self.track())
        self.table.itemChanged.connect(self._edited)
        lay.addWidget(self.table, 1)
        row = QHBoxLayout()
        for text, fn in (("Track", self.track),
                         ("Track All Not Delivered", self.track_all),
                         ("Copy Number", self.copy_number),
                         ("Change Carrier…", self.change_carrier),
                         ("Check Status", self.check_status),
                         ("Carrier Keys…", self.carrier_keys),
                         ("Remove", self.remove)):
            b = QPushButton(text)
            b.clicked.connect(lambda _c=False, f=fn: f())
            row.addWidget(b)
        row.addStretch(1)
        self.job_filter = QComboBox()
        self.job_filter.setMinimumWidth(140)
        self.job_filter.currentIndexChanged.connect(lambda _i: self.refresh())
        row.addWidget(self.job_filter)
        self.late_label = QLabel("")
        self.late_label.setStyleSheet("color:#b42318;font-weight:600")
        row.addWidget(self.late_label)
        self.show_done = QCheckBox("Show delivered")
        self.show_done.setChecked(False)
        self.show_done.toggled.connect(lambda _v: self.refresh())
        row.addWidget(self.show_done)
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        row.addWidget(close)
        lay.addLayout(row)
        self._filling = False
        self._fill_jobs()
        self.refresh()

    def _fill_jobs(self):
        cur = self.job_filter.currentText() or ALL_JOBS
        self.job_filter.blockSignals(True)
        self.job_filter.clear()
        self.job_filter.addItems([ALL_JOBS] + packages.jobs(self.items))
        i = self.job_filter.findText(cur)
        self.job_filter.setCurrentIndex(max(i, 0))
        self.job_filter.blockSignals(False)

    # ---- adding --------------------------------------------------------------
    def _numbers(self):
        text = self.entry.toPlainText()
        found = packages.find_numbers(text)
        if not found:                      # one number typed on its own
            for line in text.splitlines():
                n = packages.clean(line)
                if n and packages.detect(n):
                    found.append((n, packages.carrier(n)))
        return found

    def _preview(self):
        f = self._numbers()
        self.found.setText(
            "Found: " + ", ".join(f"{c} {n}" for n, c in f) if f else
            ("Not a tracking number FedEx, UPS, USPS or DHL use - pick the "
             "carrier to add it anyway." if self.entry.toPlainText().strip()
             else ""))

    def add_from_entry(self):
        found = self._numbers()
        pick = self.carrier.currentIndex()
        forced = packages.CARRIERS[pick - 1] if pick > 0 else None
        if not found and forced:
            n = packages.clean(self.entry.toPlainText().splitlines()[0]
                               if self.entry.toPlainText().strip() else "")
            if n:
                found = [(n, forced)]
        if not found:
            QMessageBox.information(self, "Package Tracker",
                                    "No tracking number found. Pick the "
                                    "carrier if it's an unusual number.")
            return 0
        for n, c in found:
            packages.add(self.items, n, what=self.what.text(),
                         vendor=self.vendor.text(), job=self.job.text(),
                         carrier_name=forced or c,
                         expected=self.expected.text())
        packages.save(self.items)
        self.entry.clear()
        self.what.clear()
        self.expected.clear()
        self._fill_jobs()
        self.refresh()
        return len(found)

    # ---- the table -----------------------------------------------------------
    def visible(self):
        show = self.show_done.isChecked()
        job = self.job_filter.currentText()
        return [p for p in reversed(self.items)
                if (show or not p.get("delivered")) and
                (job in ("", ALL_JOBS) or p.get("job", "") == job)]

    def refresh(self):
        self._filling = True
        rows = self.visible()
        self.table.setRowCount(len(rows))
        for r, p in enumerate(rows):
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled |
                         Qt.ItemIsSelectable)
            chk.setCheckState(Qt.Checked if p.get("delivered") else
                              Qt.Unchecked)
            chk.setData(Qt.UserRole, p["id"])
            self.table.setItem(r, 0, chk)
            late = packages.is_late(p)
            exp = p.get("expected", "")
            lv = p.get("live") or {}
            live = " - ".join(x for x in (
                lv.get("status", ""),
                f"due {lv['eta'][:10]}" if lv.get("eta") else "",
                lv.get("last_event", "") if lv.get("last_event") !=
                lv.get("status") else "") if x)
            if live and p.get("checked"):
                live += f"  (checked {p['checked']})"
            vals = [p.get("carrier") or "?", p["number"], p.get("what", ""),
                    p.get("vendor", ""), p.get("job", ""),
                    (exp + "  LATE") if late else exp,
                    p.get("added", ""), p.get("note", ""), live]
            for c, v in enumerate(vals, start=1):
                it = QTableWidgetItem(v)
                if c not in EDITABLE:
                    it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                if late:
                    from PySide6.QtGui import QColor
                    it.setForeground(QColor(180, 35, 24))
                self.table.setItem(r, c, it)
        self.table.resizeColumnsToContents()
        n = sum(1 for p in self.items if packages.is_late(p))
        self.late_label.setText(f"{n} late" if n else "")
        self._filling = False

    def _entry(self, row):
        it = self.table.item(row, 0)
        pid = it.data(Qt.UserRole) if it else None
        return next((p for p in self.items if p["id"] == pid), None)

    def selected(self):
        rows = sorted({i.row() for i in self.table.selectedItems()})
        if not rows and self.table.currentRow() >= 0:
            rows = [self.table.currentRow()]
        return [p for p in (self._entry(r) for r in rows) if p]

    def _edited(self, item):
        if self._filling:
            return
        p = self._entry(item.row())
        if p is None:
            return
        if item.column() == 0:
            p["delivered"] = item.checkState() == Qt.Checked
        elif item.column() == 6:
            d = packages.parse_date(item.text().replace("LATE", ""))
            p["expected"] = d.isoformat() if d else ""
        elif item.column() in EDITABLE:
            p[EDITABLE[item.column()]] = item.text().strip()
        else:
            return
        packages.save(self.items)
        if item.column() == 5:
            self._fill_jobs()
        if item.column() in (0, 6):
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, self.refresh)

    # ---- actions -------------------------------------------------------------
    def track(self):
        n = 0
        for p in self.selected():
            u = packages.url(p["number"], p.get("carrier"))
            if u:
                open_url(u)
                n += 1
        return n

    def track_all(self):
        todo = [p for p in self.items if not p.get("delivered")]
        n = 0
        for p in todo[-MAX_OPEN:]:
            u = packages.url(p["number"], p.get("carrier"))
            if u:
                open_url(u)
                n += 1
        return n

    def check_status(self, http=None):
        """Look up every package still on its way whose carrier has keys
        (packages_live.py). Without keys nothing is looked up."""
        from . import packages_live as PL
        keys = PL.load_keys()
        if not keys:
            QMessageBox.information(
                self, "Package Tracker",
                "Live status needs a carrier's developer keys - Carrier "
                "Keys… says what each carrier needs. Until then, Track "
                "opens the carrier's own page.")
            return 0
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            n, errors = PL.check(self.items, keys, http)
        finally:
            QApplication.restoreOverrideCursor()
        packages.save(self.items)
        self.refresh()
        msg = f"Checked {n} package(s)."
        if errors:
            msg += " Couldn't check: " + "; ".join(
                f"{k}: {v}" for k, v in list(errors.items())[:4])
        self.found.setText(msg)
        return n

    def carrier_keys(self, values=None):
        """The carriers' developer keys, kept only on this computer."""
        from . import packages_live as PL
        have = PL.load_keys()
        if values is None:
            from PySide6.QtWidgets import (QDialogButtonBox, QFormLayout,
                                           QGroupBox)
            dlg = QDialog(self)
            dlg.setWindowTitle("Carrier Keys")
            lay = QVBoxLayout(dlg)
            lay.addWidget(QLabel(
                "Keys from each carrier's developer site, for live status. "
                "Leave a carrier blank to keep using its tracking page. Kept "
                "only on this computer."))
            edits = {}
            for c, fields in PL.FIELDS.items():
                box = QGroupBox(c)
                f = QFormLayout(box)
                for fld in fields:
                    e = QLineEdit((have.get(c) or {}).get(fld, ""))
                    if "secret" in fld:
                        e.setEchoMode(QLineEdit.Password)
                    f.addRow(PL.LABELS[fld] + ":", e)
                    edits[(c, fld)] = e
                lay.addWidget(box)
            bb = QDialogButtonBox(QDialogButtonBox.Save |
                                  QDialogButtonBox.Cancel)
            bb.accepted.connect(dlg.accept)
            bb.rejected.connect(dlg.reject)
            lay.addWidget(bb)
            if dlg.exec() != QDialog.Accepted:
                return None
            values = {}
            for (c, fld), e in edits.items():
                values.setdefault(c, {})[fld] = e.text()
        return PL.save_keys(values)

    def copy_number(self):
        nums = [p["number"] for p in self.selected()]
        if nums:
            QApplication.clipboard().setText("\n".join(nums))
        return nums

    def change_carrier(self, to=None):
        sel = self.selected()
        if not sel:
            return None
        if to is None:
            from PySide6.QtWidgets import QInputDialog
            cur = sel[0].get("carrier") or packages.CARRIERS[0]
            to, ok = QInputDialog.getItem(
                self, "Change Carrier", "Carrier:", list(packages.CARRIERS),
                max(0, list(packages.CARRIERS).index(cur)
                    if cur in packages.CARRIERS else 0), False)
            if not ok:
                return None
        for p in sel:
            p["carrier"] = to
        packages.save(self.items)
        self.refresh()
        return to

    def remove(self, ask=True):
        sel = self.selected()
        if not sel:
            return 0
        if ask and QMessageBox.question(
                self, "Package Tracker",
                f"Take {len(sel)} package(s) off the list?") != \
                QMessageBox.Yes:
            return 0
        ids = {p["id"] for p in sel}
        self.items = [p for p in self.items if p["id"] not in ids]
        packages.save(self.items)
        self.refresh()
        return len(ids)


_open = []


def show(parent=None):
    """One tracker window at a time (not modal: work carries on)."""
    for d in _open:
        try:
            d.show()
            d.raise_()
            d.activateWindow()
            return d
        except RuntimeError:
            _open.remove(d)
    d = PackageTracker(parent)
    d.setAttribute(Qt.WA_DeleteOnClose)
    d.destroyed.connect(lambda *_a: _open.clear())
    _open.append(d)
    d.show()
    return d
