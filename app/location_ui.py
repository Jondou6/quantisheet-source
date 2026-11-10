"""Location Factors window: your table of regions and factors, a search
box ('Search state, city, abbreviation or ZIP') that picks the region for
the job, and the table's change history."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QDialog,
                               QDialogButtonBox, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QMessageBox,
                               QPushButton, QTableWidget, QTableWidgetItem,
                               QTabWidget, QVBoxLayout, QWidget)

from . import locfactors, pricedb
from .dmoney import c2 as _c2

COLS = ["Region", "State", "Cities", "ZIP prefixes / ZIPs", "Materials",
        "Labor", "Equipment", "Source note", "From"]
KEYS = ["region", "state", "cities", "zips", "materials", "labor",
        "equipment", "source"]
PLACEHOLDER = "Search state, city, abbreviation or ZIP"


def _cell(text, editable=True, right=False):
    it = QTableWidgetItem("" if text is None else str(text))
    if not editable:
        it.setFlags(it.flags() & ~Qt.ItemIsEditable)
    if right:
        it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
    return it


class LocationFactorsWidget(QWidget):
    """The editable table with its search box. Changes are kept until
    save() (each change goes in the price history)."""

    def __init__(self, parent=None, search=""):
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(QLabel(
            "Your location factors (1.00 = national). Starter rows are "
            "QuantiSheet's own public-source state index; add cities, ZIPs "
            "and factors from your own data or quotes."))
        self.search = QLineEdit(search)
        self.search.setPlaceholderText(PLACEHOLDER)
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda *_: self.fill())
        v.addWidget(self.search)
        self.message = QLabel("")
        self.message.setWordWrap(True)
        v.addWidget(self.message)
        self.table = QTableWidget(0, len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        self.table.horizontalHeader().setSectionResizeMode(
            7, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.itemChanged.connect(self._edited)
        v.addWidget(self.table, 1)
        row = QHBoxLayout()
        for label, fn in (("Add Region", self.add_region),
                          ("Remove Region", self.remove_selected)):
            b = QPushButton(label)
            b.clicked.connect(lambda _=False, f=fn: f())
            row.addWidget(b)
        row.addWidget(QLabel("Note:"))
        self.note = QLineEdit()
        self.note.setPlaceholderText("where the factors came from, e.g. "
                                     "our 2026 jobs in Testville")
        row.addWidget(self.note, 1)
        self.save_btn = QPushButton("Save Location Factors")
        self.save_btn.clicked.connect(lambda: self.save())
        row.addWidget(self.save_btn)
        v.addLayout(row)
        self.reload()

    # ---- data --------------------------------------------------------------
    def reload(self):
        try:
            self.rows = locfactors.rows()
        except pricedb.PriceDBError as e:
            self.rows = []
            self.message.setText(str(e))
        self.edits = {}          # original region (lower) -> edited row
        self.added = []
        self.removed = []
        self.fill()

    def _current(self):
        """The rows as edited here (not saved yet)."""
        out = []
        for r in self.rows:
            key = r["region"].lower()
            if key in self.removed:
                continue
            out.append(self.edits.get(key, r))
        return out + self.added

    def fill(self):
        text = self.search.text().strip()
        rows = self._current()
        shown = locfactors.search(text, rows) if text else rows
        if text and not shown:
            self.message.setText(locfactors.no_match_message(text))
        elif text:
            self.message.setText(f"{len(shown)} region(s): "
                                 + ", ".join(r["region"] for r in shown[:8])
                                 + (" ..." if len(shown) > 8 else ""))
        else:
            self.message.setText(f"{len(rows)} region(s)")
        t = self.table
        t.blockSignals(True)
        t.setRowCount(len(shown))
        for i, r in enumerate(shown):
            for c, k in enumerate(KEYS):
                val = r.get(k, "")
                if k in locfactors.KINDS:
                    try:
                        f = float(val)
                        val = f"{_c2(f):.2f}" if abs(_c2(f) - f) < 1e-9 \
                            else f"{f:.4f}".rstrip("0")
                    except (TypeError, ValueError):
                        val = ""
                cell = _cell(val, True, k in locfactors.KINDS)
                if c == 0:
                    cell.setData(Qt.UserRole, id(r))
                t.setItem(i, c, cell)
            t.setItem(i, 8, _cell({"starter": "starter", "edited":
                                   "starter, edited", "yours": "yours",
                                   "new": "new (not saved)"}.get(
                                       r.get("origin"), ""), False))
        t.blockSignals(False)
        self._shown = shown
        return shown

    def matches(self):
        return list(getattr(self, "_shown", []))

    def selected_region(self):
        rows = sorted({i.row() for i in self.table.selectedItems()})
        if rows and rows[0] < len(self._shown):
            return self._shown[rows[0]]["region"]
        if len(self._shown) == 1 and self.search.text().strip():
            return self._shown[0]["region"]
        return None

    def _edited(self, cell):
        r = cell.row()
        if r >= len(self._shown):
            return
        src = self._shown[r]
        k = KEYS[cell.column()] if cell.column() < len(KEYS) else None
        if not k:
            return
        text = cell.text().strip()
        if k in locfactors.KINDS:
            try:
                val = float(text.replace(",", "") or 1.0)
                if val <= 0:
                    raise ValueError
            except ValueError:
                QMessageBox.warning(self, "Location Factors",
                                    f"{text!r} isn't a factor (a number "
                                    "above 0, 1.00 = national).")
                self.fill()
                return
        else:
            val = text.upper() if k == "state" else text
        new = dict(src, **{k: val})
        if src in self.added:
            self.added[self.added.index(src)] = new
        else:
            key = (src.get("_was") or src["region"]).lower()
            new["_was"] = src.get("_was") or src["region"]
            self.edits[key] = new
        self._shown[r] = new
        self.message.setText("Changed, not saved - Save Location Factors "
                             "to keep it.")

    def add_region(self, region="New region", **values):
        row = {"region": region, "state": "", "cities": "", "zips": "",
               "materials": 1.0, "labor": 1.0, "equipment": 1.0,
               "source": "", "origin": "new"}
        row.update(values)
        self.added.append(row)
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
        self.fill()
        self.table.scrollToBottom()
        return row

    def remove_selected(self, region=None):
        region = region or self.selected_region()
        if not region:
            return None
        for r in list(self.added):
            if r["region"] == region:
                self.added.remove(r)
                self.fill()
                return region
        self.removed.append(region.lower())
        self.fill()
        return region

    def dirty(self):
        return bool(self.edits or self.added or self.removed)

    def save(self):
        """Save the changes (logged in the price history). Returns the
        number of changes logged, or None when refused."""
        if not self.dirty():
            return 0
        note = self.note.text().strip()
        names = [r["region"].strip().lower() for r in self._current()]
        dup = sorted({n for n in names if names.count(n) > 1})
        if dup:
            QMessageBox.warning(self, "Location Factors", "Two rows have "
                                "the same region name: " + ", ".join(dup))
            return None
        try:
            n = 0
            for key in self.removed:
                n += locfactors.remove(key, note)
            rows = list(self.edits.values()) + self.added
            n += locfactors.save(rows, note)
        except pricedb.PriceDBError as e:
            QMessageBox.warning(self, "Location Factors", str(e))
            return None
        self.reload()
        self.message.setText(f"Saved ({n} change(s) in the history).")
        return n


class LocationFactorsDialog(QDialog):
    """The table, its history and - with a job open - Use for This Job."""

    def __init__(self, parent=None, doc=None, search=""):
        super().__init__(parent)
        self.doc = doc
        self.setWindowTitle("Location Factors")
        self.resize(1100, 620)
        lay = QVBoxLayout(self)
        tabs = QTabWidget()
        lay.addWidget(tabs, 1)
        self.factors = LocationFactorsWidget(self, search)
        tabs.addTab(self.factors, "Regions")
        w = QWidget()
        v = QVBoxLayout(w)
        self.hist = QTableWidget(0, 6)
        self.hist.setHorizontalHeaderLabels(["When", "Who", "Region",
                                             "Field", "Was", "Now"])
        self.hist.horizontalHeader().setSectionResizeMode(
            5, QHeaderView.Stretch)
        v.addWidget(self.hist)
        tabs.addTab(w, "History")
        tabs.currentChanged.connect(
            lambda i: self.fill_history() if i == 1 else None)
        self.job_label = QLabel("")
        self.job_label.setWordWrap(True)
        lay.addWidget(self.job_label)
        bb = QDialogButtonBox()
        self.use_btn = None
        if doc is not None:
            self.use_btn = bb.addButton("Use for This Job",
                                        QDialogButtonBox.ApplyRole)
            self.use_btn.clicked.connect(lambda: self.use_for_job())
        bb.addButton(QDialogButtonBox.Ok).clicked.connect(self.accept)
        bb.addButton(QDialogButtonBox.Close).clicked.connect(self.reject)
        lay.addWidget(bb)
        self._show_job()

    def chosen(self):
        return self.factors.selected_region()

    def _show_job(self):
        if self.doc is None:
            self.job_label.setText("")
            return
        from . import jobinfo
        reg, how = jobinfo.region_source(self.doc)
        self.job_label.setText(
            f"This job's region: <b>{reg}</b> ({how})" if reg else
            "This job has no location region yet.")

    def use_for_job(self, region=None):
        """Pick the region for the open job (the searched one, or the
        selected row). Without a match the job keeps its region."""
        if self.doc is None:
            return None
        region = region or self.chosen()
        if not region:
            text = self.factors.search.text().strip()
            self.factors.message.setText(
                locfactors.no_match_message(text) if text else
                "Select a region first.")
            return None
        from . import jobinfo
        jobinfo.write(self.doc, location_region=region)
        self._show_job()
        par = self.parent()
        if hasattr(par, "_doc_edited"):
            par._doc_edited()
        return region

    def accept(self):
        if self.factors.dirty() and self.factors.save() is None:
            return
        super().accept()

    def fill_history(self):
        try:
            rows = locfactors.history()
        except pricedb.PriceDBError:
            rows = []
        self.hist.setRowCount(len(rows))
        for r, h in enumerate(rows):
            for c, k in enumerate(("at", "by", "code", "field", "old",
                                   "new")):
                self.hist.setItem(r, c, _cell(str(h.get(k) or "")[:120],
                                              False))
        return rows
