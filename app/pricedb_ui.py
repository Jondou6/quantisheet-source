"""Price database windows: Edit Prices (items, labor rates, history),
Price Database (where it lives) and Bid Tabs."""
import logging
import datetime as _dt
import os
from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFileDialog, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMessageBox, QPushButton, QSplitter, QTableWidget, QTableWidgetItem,
    QTabWidget, QVBoxLayout, QWidget)

from . import theme as _theme
from . import costbook, pricedb
from .dmoney import c2 as _c2

US_STATES = sorted(costbook.STATES)


def _item(text, editable=False, right=False):
    it = QTableWidgetItem("" if text is None else str(text))
    if not editable:
        it.setFlags(it.flags() & ~Qt.ItemIsEditable)
    if right:
        it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
    return it


def _num(text):
    t = str(text or "").replace("$", "").replace(",", "").strip()
    return float(t) if t else 0.0


# ---- Edit Prices ---------------------------------------------------------------

class PriceEditor(QDialog):
    """Edit a cost book's prices and labor rates; every change is logged."""

    # Material $ and Equipment $ apart (0.13; older books had one
    # "Material/Equip $" column and keep their value under Material), the
    # Labor Output it takes (units per crew-day: crew size x 8 h / hours
    # per unit) and the unit Total at the book's region
    COLS = ["Code", "Description", "Unit", "Material $", "Equipment $",
            "Sub $", "Labor hrs/unit", "Crew", "Labor Output", "Unit Total $",
            "Basis", "Source", "Edition", "Changed"]
    EDIT = {3: "material", 4: "equipment", 5: "sub", 6: "labor", 7: "crew",
            10: "basis", 11: "source", 12: "edition"}
    MONEY_COLS = (3, 4, 5, 6, 8, 9)
    OUTPUT_COL, TOTAL_COL = 8, 9
    LIMIT = 600

    def __init__(self, name, parent=None):
        super().__init__(parent)
        self.name = name
        from . import costbook
        self.setWindowTitle(f"Edit Prices - {costbook.display_name(name)}")
        self.resize(1250, 720)
        lay = QVBoxLayout(self)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        tabs = QTabWidget()
        lay.addWidget(tabs, 1)

        w = QWidget()
        v = QVBoxLayout(w)
        row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search code, description, crew or "
                                       "source")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda *_: self.fill())
        row.addWidget(self.search, 1)
        self.basis = QComboBox()
        self.basis.addItems(["All", "researched", "estimate", "allowance",
                             "RSMeans", "RSMeans-calibrated", "quote"])
        self.basis.addItem("imported")          # Import Your Own Price List
        self.basis.currentIndexChanged.connect(lambda *_: self.fill())
        row.addWidget(QLabel("Basis:"))
        row.addWidget(self.basis)
        v.addLayout(row)
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.Stretch)
        self.table.itemChanged.connect(self._edited)
        v.addWidget(self.table)
        self.count = QLabel("")
        v.addWidget(self.count)
        tabs.addTab(w, "Prices")

        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(QLabel("Burdened labor rates ($/hr) by region, and the "
                           "materials index (1.00 = national)."))
        self.rates = QTableWidget()
        self.rates.itemChanged.connect(self._rate_edited)
        v.addWidget(self.rates)
        tabs.addTab(w, "Labor Rates")
        from .location_ui import LocationFactorsWidget
        self.locations = LocationFactorsWidget(self)
        tabs.addTab(self.locations, "Location Factors")

        w = QWidget()
        v = QVBoxLayout(w)
        row = QHBoxLayout()
        self.hist_code = QLineEdit()
        self.hist_code.setPlaceholderText("Item code (blank = whole book)")
        b = QPushButton("Show")
        b.clicked.connect(self.fill_history)
        row.addWidget(self.hist_code, 1)
        row.addWidget(b)
        v.addLayout(row)
        self.hist = QTableWidget(0, 7)
        self.hist.setHorizontalHeaderLabels(["When", "Who", "Code", "Field",
                                             "Was", "Now", "Note"])
        self.hist.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.Stretch)
        v.addWidget(self.hist)
        tabs.addTab(w, "History")
        self.history_tab = tabs.indexOf(w)
        tabs.currentChanged.connect(
            lambda i: self.fill_history() if i == self.history_tab else None)

        row = QHBoxLayout()
        row.addWidget(QLabel("Note for this change:"))
        self.note = QLineEdit()
        self.note.setPlaceholderText("e.g. ABC Supply quote 10/14")
        row.addWidget(self.note, 1)
        lay.addLayout(row)
        bb = QDialogButtonBox()
        self.save_btn = bb.addButton("Save Changes",
                                     QDialogButtonBox.AcceptRole)
        self.save_btn.clicked.connect(self.save)
        bb.addButton(QDialogButtonBox.Close).clicked.connect(self.reject)
        lay.addWidget(bb)
        self.reload()

    def reload(self):
        self.data = pricedb.load_book(self.name) or {"items": {},
                                                     "rates": {},
                                                     "index": {}}
        warn = pricedb.outside_change(self.name, self.data) \
            if self.data.get("modified") else ""
        if warn:
            from PySide6.QtWidgets import QMessageBox
            if QMessageBox.warning(
                    self, "Price Book", warn + "\n\nMark it as checked?",
                    QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
                pricedb.accept_outside_change(self.name)
        self.loaded = {c: it.get("modified") for c, it in
                       self.data["items"].items()}
        self.changes = {}
        self.rate_changes, self.index_changes = {}, {}
        try:
            self.book = costbook.Book(self.data)
        except Exception:                                 # noqa: BLE001
            self.book = costbook.Book({"name": self.name})
        off = pricedb.state.get("offline")
        where = pricedb.path()
        self.status.setText(
            (f"<span style='color:#b00'>{off}</span>" if off else
             f"Price database: {where}" +
             (" (shared)" if pricedb.is_shared() else " (this PC)")) +
            f"<br>Last changed {str(self.data.get('modified') or '')[:16]}"
            f" by {self.data.get('modified_by') or '?'}" +
            ("<br><span style='color:#b06000'>Licensed price data, kept "
             "only in this PC's price database (local-only). Sharing it "
             "needs the licence holder's OK.</span>"
             if pricedb.book_is_local_only(self.data) else "") +
            f"<br>Unit Total at {self.book.region}, as the book lists it "
            "(no escalation)")
        self.save_btn.setEnabled(not off)
        self.fill()
        self.fill_rates()

    # prices
    def fill(self):
        words = self.search.text().lower().split()
        basis = self.basis.currentText()
        rows = []
        for code, it in sorted(self.data["items"].items()):
            if basis != "All" and (it.get("basis") or "") != basis:
                continue
            hay = " ".join(str(x) for x in (code, it.get("desc"),
                                            it.get("crew"),
                                            it.get("source"))).lower()
            if words and not all(w in hay for w in words):
                continue
            rows.append((code, it))
        total = len(rows)
        rows = rows[:self.LIMIT]
        t = self.table
        t.blockSignals(True)
        t.setRowCount(len(rows))
        for r, (code, it) in enumerate(rows):
            ch = self.changes.get(code, {})
            out, tot, tip = self._computed(code, it)
            vals = [code, it.get("desc"), it.get("unit"),
                    f"{ch.get('material', it.get('material') or 0):g}",
                    f"{ch.get('equipment', it.get('equipment') or 0):g}",
                    f"{ch.get('sub', it.get('sub') or 0):g}",
                    f"{ch.get('labor', it.get('labor') or 0):g}",
                    ch.get("crew", it.get("crew") or ""), out, tot,
                    ch.get("basis", it.get("basis") or ""),
                    ch.get("source", it.get("source") or ""),
                    ch.get("edition", it.get("edition") or ""),
                    f"{str(it.get('modified') or '')[:10]} "
                    f"{it.get('modified_by') or ''}"]
            for c, val in enumerate(vals):
                cell = _item(val, c in self.EDIT, c in self.MONEY_COLS)
                if ch and self.EDIT.get(c) in ch:
                    _theme.tint(cell, Qt.yellow)
                if c == self.TOTAL_COL:
                    cell.setToolTip(tip)
                if c == 11 and it.get("imported"):
                    cell.setToolTip(f"Imported {it['imported']}" + (
                        " - licensed, this PC only" if it.get("license") ==
                        pricedb.LOCAL_ONLY else ""))
                t.setItem(r, c, cell)
        t.blockSignals(False)
        self.count.setText(f"{total} item(s)" + (
            f" - showing the first {self.LIMIT}; search to narrow"
            if total > self.LIMIT else "") +
            (f"; {len(self.changes)} changed, not saved"
             if self.changes else ""))

    def _edited(self, cell):
        field = self.EDIT.get(cell.column())
        if not field:
            return
        code = self.table.item(cell.row(), 0).text()
        text = cell.text()
        try:
            val = _num(text) if field in pricedb.NUMERIC else text.strip()
        except ValueError:
            QMessageBox.warning(self, "Edit Prices", f"{text!r} isn't a "
                                "number.")
            self.fill()
            return
        old = self.data["items"].get(code, {}).get(field)
        if field in pricedb.NUMERIC and abs(float(old or 0) - val) < 1e-9 or \
                field not in pricedb.NUMERIC and str(old or "") == val:
            self.changes.get(code, {}).pop(field, None)
            if not self.changes.get(code):
                self.changes.pop(code, None)
        else:
            self.changes.setdefault(code, {})[field] = val
            if field in pricedb.NUMERIC and "basis" not in \
                    self.changes[code]:
                self.changes[code]["basis"] = "quote"
        _theme.tint(cell, Qt.yellow)
        self._refresh_computed(cell.row(), code)
        self.count.setText(f"{len(self.changes)} changed, not saved")

    def _computed(self, code, it):
        """(Labor Output text, Unit Total text, tooltip) for an item with
        the unsaved changes applied."""
        item = dict(it, **self.changes.get(code, {}))
        try:
            u = costbook.unit_cost(self.book, item, None, None, code)
        except Exception:                                 # noqa: BLE001
            return "", "", ""
        unit = item.get("unit") or "unit"
        out = u["output"]
        out_txt = "" if out is None else (
            f"{out:,.0f} {unit}/day" if out >= 10 else
            f"{_c2(out):,.2f} {unit}/day")
        tot = u["total"]
        q = tot.quantize(Decimal("0.01"))
        tot_txt = f"{_c2(q):,.2f}" if q == tot or tot >= 10 else \
            f"{tot:,.4f}".rstrip("0")
        if u["labor_rate"] is not None:
            lab = (f"labor {u['labor_hours']:g} h x "
                   f"${_c2(u['labor_rate']):,.2f}/h = ${_c2(u['labor']):,.2f}")
        elif u["labor_hours"]:
            lab = "labor hours not costed here (no crew)"
        else:
            lab = "no labor"
        tip = (f"Material ${_c2(u['material']):,.2f} + equipment "
               f"${_c2(u['equipment']):,.2f} + sub ${_c2(u['sub']):,.2f} + {lab} "
               f"at {self.book.region}")
        if out is not None:
            tip += (f"\nLabor Output: crew of {u['crew_size']:g} x 8 h / "
                    f"{u['labor_hours']:g} h per {unit}")
        return out_txt, tot_txt, tip

    def _refresh_computed(self, row, code):
        it = self.data["items"].get(code)
        if it is None:
            return
        out, tot, tip = self._computed(code, it)
        t = self.table
        t.blockSignals(True)
        t.setItem(row, self.OUTPUT_COL, _item(out, right=True))
        cell = _item(tot, right=True)
        cell.setToolTip(tip)
        t.setItem(row, self.TOTAL_COL, cell)
        t.blockSignals(False)

    # rates
    def fill_rates(self):
        rates = self.data.get("rates") or {}
        regions = sorted(rates, key=lambda r: (r != "national", r))
        trades = sorted({t for tr in rates.values() for t in tr})
        t = self.rates
        t.blockSignals(True)
        t.setColumnCount(len(regions))
        t.setRowCount(len(trades) + 1)
        t.setHorizontalHeaderLabels(regions)
        t.setVerticalHeaderLabels(["Materials index"] + trades)
        idx = self.data.get("index") or {}
        for c, reg in enumerate(regions):
            t.setItem(0, c, _item(f"{float(idx.get(reg, 1.0)):.4f}", True,
                                  True))
            for r, trade in enumerate(trades, 1):
                v = rates.get(reg, {}).get(trade)
                t.setItem(r, c, _item("" if v is None else f"{_c2(v):.2f}", True,
                                      True))
        t.blockSignals(False)
        self._regions, self._trades = regions, trades

    def _rate_edited(self, cell):
        reg = self._regions[cell.column()]
        try:
            val = _num(cell.text())
        except ValueError:
            self.fill_rates()
            return
        if cell.row() == 0:
            self.index_changes[reg] = val
        else:
            trade = self._trades[cell.row() - 1]
            self.rate_changes.setdefault(reg, {})[trade] = val
        _theme.tint(cell, Qt.yellow)

    def fill_history(self):
        rows = pricedb.history(self.name, self.hist_code.text().strip() or
                               None, limit=1000)
        self.hist.setRowCount(len(rows))
        for r, h in enumerate(rows):
            for c, k in enumerate(("at", "by", "code", "field", "old", "new",
                                   "note")):
                self.hist.setItem(r, c, _item(str(h.get(k) or "")[:120]))
        return rows

    def save(self):
        if self.locations.dirty() and self.locations.save() is None:
            return None
        if not (self.changes or self.rate_changes or self.index_changes):
            self.accept()
            return 0
        note = self.note.text().strip()
        n = 0
        try:
            if self.changes:
                n += pricedb.update_items(self.name, self.changes,
                                          self.loaded, note)
            if self.rate_changes or self.index_changes:
                n += pricedb.update_rates(self.name, self.rate_changes,
                                          self.index_changes, note)
        except pricedb.Conflict as e:
            QMessageBox.warning(
                self, "Edit Prices", f"{e}\n\nNothing was saved. Click OK "
                "to load their changes, then make yours again.")
            self.reload()
            return None
        except pricedb.PriceDBError as e:
            QMessageBox.warning(self, "Edit Prices", str(e))
            return None
        self.reload()
        self.accept()
        return n


# ---- Price Database location --------------------------------------------------

class DatabaseDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Price Database")
        self.resize(640, 300)
        lay = QVBoxLayout(self)
        self.info = QLabel("")
        self.info.setWordWrap(True)
        self.info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.info)
        for label, fn, tip in (
                ("Use a Network Folder…", self.choose,
                 "Put the database on a shared drive so everyone uses the "
                 "same prices (or connect to one that's already there)"),
                ("Use This PC Only", self.local, "Go back to the database "
                 "in your own settings folder"),
                ("Back Up Now", self.backup, "Save a dated copy next to the "
                 "database (the last 10 are kept)"),
                ("Escalation from BLS Producer Prices…", self.escalation,
                 "Real price changes by trade for bid tabs and cost books"),
                ("Open Folder", self.folder, "")):
            b = QPushButton(label)
            b.setToolTip(tip)
            b.clicked.connect(lambda _c=False, _f=fn: _f())
            lay.addWidget(b)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.show_info()

    def show_info(self):
        try:
            names = pricedb.book_names()
            with pricedb.connect() as con:
                bids = con.execute("SELECT COUNT(*) FROM bid_projects"
                                   ).fetchone()[0]
                cats = con.execute("SELECT COUNT(*) FROM catalogs"
                                   ).fetchone()[0]
        except pricedb.PriceDBError as e:
            names, bids, cats = [], 0, 0
            pricedb.state["offline"] = str(e)
        off = pricedb.state.get("offline")
        p = pricedb.path()
        txt = (f"<b>{p}</b><br>" + ("Shared (network folder)" if
                                     pricedb.is_shared() else "This PC only")
               + f"<br>{len(names)} cost book(s), {cats} catalog(s), {bids} "
               "bid tab project(s)")
        if off:
            txt += f"<br><span style='color:#b00'>{off}</span>"
        warn = pricedb.sync_folder_warning(p)
        if warn:
            txt += f"<br><span style='color:#b06000'>{warn}</span>"
        txt += ("<br><br>Everyone points QuantiSheet at the same file (this "
                "window, Use a Network Folder). One person saves at a time; "
                "edits that clash with someone else's are refused, and "
                "every change is in each book's History.")
        self.info.setText(txt)
        self._fit_info()

    def _fit_info(self):
        """Tall enough for every wrapped line of the text (Chief's user
        test, Nov 6: the last sentence was cut off)."""
        w = max(self.info.width(), self.width() - 40, 560)
        need = self.info.heightForWidth(w)
        if need > 0:
            self.info.setMinimumHeight(need)
        self.adjustSize()
        if self.width() < 640:
            self.resize(640, self.height())

    def choose(self, folder=None):
        if folder is None:
            folder = QFileDialog.getExistingDirectory(
                self, "Folder for the shared price database")
        if not folder:
            return None
        target = pricedb.file_in(folder)          # QuantiSheet Prices.db
        warn = pricedb.sync_folder_warning(target)
        if warn and QMessageBox.question(
                self, "Price Database", warn + "\n\nUse it anyway?") != \
                QMessageBox.Yes:
            return None
        if not self._ask_local_only(target):
            return None
        exists = os.path.exists(target)
        if not exists and QMessageBox.question(
                self, "Price Database",
                f"Copy your current prices to {target} for everyone to "
                "use?") != QMessageBox.Yes:
            return None
        try:
            how = pricedb.use(target, copy_current=True)
        except Exception as e:
            QMessageBox.warning(self, "Price Database", f"Can't use {target}:"
                                f" {e}")
            return None
        costbook._MIGRATED.clear()
        from . import assembly_csv
        assembly_csv.forget_cache()
        self.show_info()
        left = pricedb.state.get("left_out") or []
        QMessageBox.information(
            self, "Price Database",
            ("Connected to the shared database." if how == "connected" else
             "Your prices were copied there.") + " Have the other "
            "estimators choose the same folder here." +
            (f"\n\nLeft out (licensed, this PC only): {', '.join(left)}."
             if left else ""))
        return how

    def _ask_local_only(self, target):
        """Licensed (local-only) books never go to a shared folder: say
        so and ask before moving. True to go ahead."""
        if not pricedb.is_shared(target):
            return True
        try:
            names = pricedb.local_only_books()
        except pricedb.PriceDBError:
            names = []
        if not names:
            return True
        return QMessageBox.question(
            self, "Price Database",
            f"{len(names)} book(s) of licensed price data ("
            + ", ".join(names[:6]) + (" ..." if len(names) > 6 else "") +
            ") can only be kept in this PC's local price database. They "
            "will be left out of the shared database (they stay on this "
            "PC, but can't be used while you use the shared one).\n\n"
            "Move to the shared folder without them?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == \
            QMessageBox.Yes

    def local(self):
        pricedb.use_local()
        from . import assembly_csv
        assembly_csv.forget_cache()
        self.show_info()

    def backup(self):
        try:
            dest = pricedb.snapshot()
        except Exception as e:
            QMessageBox.warning(self, "Price Database", str(e))
            return None
        QMessageBox.information(self, "Price Database", f"Saved {dest}")
        return dest

    def escalation(self):
        from .ppi_ui import EscalationDialog
        dlg = EscalationDialog(self)
        self._esc = dlg
        dlg.exec()
        return dlg

    def folder(self):
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(
            pricedb.path())))


# ---- Bid Tabs -------------------------------------------------------------------

class ImportBidTab(QDialog):
    """Project details for bid tab files, with a preview of the columns."""

    def __init__(self, paths, parent=None):
        from . import bidtab
        super().__init__(parent)
        self.paths = paths
        self.setWindowTitle("Import Bid Tab")
        self.resize(820, 560)
        lay = QVBoxLayout(self)
        form = QFormLayout()
        base = os.path.splitext(os.path.basename(paths[0]))[0]
        self.name = QLineEdit(base)
        self.owner = QLineEdit()
        self.location = QLineEdit()
        self.state = QComboBox()
        self.state.addItem("")
        for ab in US_STATES:
            self.state.addItem(f"{ab} - {costbook.STATES[ab]}", ab)
        self.date = QLineEdit(_dt.date.today().strftime("%Y-%m"))
        self.date.setPlaceholderText("YYYY-MM")
        self.bidder = QLineEdit()
        self.bidder.setPlaceholderText("only if the file has no bidder "
                                       "column (blank = file name)")
        self.cols = QLineEdit()
        self.cols.setPlaceholderText("override columns, e.g. desc=2,unit=3,"
                                     "qty=4,price=5 (0 = first column)")
        self.cols.editingFinished.connect(self.refresh)
        self.create_new = QCheckBox("Make vocabulary items from wordings "
                                    "with no match that appear 3+ times")
        for label, w in (("Project:", self.name), ("Owner:", self.owner),
                         ("Location:", self.location), ("State:", self.state),
                         ("Bid date:", self.date), ("Bidder:", self.bidder),
                         ("Columns:", self.cols), ("", self.create_new)):
            form.addRow(label, w)
        lay.addLayout(form)
        self.found = QLabel("")
        self.found.setWordWrap(True)
        lay.addWidget(self.found)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Bidder", "Item", "Description",
                                              "Unit", "Qty", "Unit price"])
        self.table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.Stretch)
        lay.addWidget(self.table, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self._bidtab = bidtab
        self.refresh()

    def overrides(self):
        from . import bidtab_core
        return bidtab_core.parse_map(self.cols.text())

    def refresh(self):
        rows, notes = [], []
        for p in self.paths:
            try:
                cmap, got = self._bidtab.preview(p, self.overrides())
                notes.append(f"{os.path.basename(p)}: {len(got)} priced "
                             f"line(s); columns {cmap.index}")
                rows += got
            except Exception as e:
                notes.append(f"{os.path.basename(p)}: {e}")
        try:
            from . import vocab
            dec = vocab.route([r for r in rows if not getattr(r, "note", "")])
            k = {s: sum(1 for d in dec if d["status"] == s)
                 for s in ("auto", "review", "new")}
            inc = sum(1 for r in rows if getattr(r, "note", "") == "included")
            notes.append(f"Vocabulary: {k['auto']} match with confidence, "
                         f"{k['review']} would be queued for review, "
                         f"{k['new']} have no match" +
                         (f"; {inc} INCL line(s)" if inc else "") + ".")
        except Exception:
            logging.getLogger(__name__).debug("ignored error", exc_info=True)
        self.found.setText("<br>".join(notes))
        show = rows[:300]
        self.table.setRowCount(len(show))
        for r, b in enumerate(show):
            for c, v in enumerate((b.bidder, b.item_no, b.desc, b.unit,
                                   f"{b.qty:g}", f"{_c2(b.price):,.2f}")):
                self.table.setItem(r, c, _item(v, right=c >= 4))
        return rows

    def values(self):
        return {"name": self.name.text().strip(),
                "owner": self.owner.text().strip(),
                "location": self.location.text().strip(),
                "state": self.state.currentData() or "",
                "bid_date": self.date.text().strip(),
                "bidder": self.bidder.text().strip() or None,
                "overrides": self.overrides(),
                "create_new_min": 3 if self.create_new.isChecked() else 0}


class BidTabDialog(QDialog):
    """Public bid results: projects, the item library and a check of this
    job's estimate against them."""

    ITEM_COLS = ["Trade", "Description", "Unit", "Bids", "Projects", "Low",
                 "Median", "High", "Spread %", "Escalated median", "States",
                 "Bid dates", ""]

    def __init__(self, doc=None, parent=None):
        from . import bidtab
        super().__init__(parent)
        self.bidtab = bidtab
        self.doc = doc
        self.setWindowTitle("Bid Tabs")
        self.resize(1250, 780)
        lay = QVBoxLayout(self)
        split = QSplitter(Qt.Vertical)
        lay.addWidget(split, 1)

        top = QWidget()
        v = QVBoxLayout(top)
        v.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        row.addWidget(QLabel("<b>Projects</b>"))
        row.addStretch()
        for label, fn in (("Import Bid Tab…", self.import_files),
                          ("Remove Project", self.remove),
                          ("Escalation Rates…", self.edit_rates),
                          ("From BLS Prices…", self.bls_rates),
                          ("Vocabulary…", self.vocabulary)):
            b = QPushButton(label)
            b.clicked.connect(lambda _c=False, _f=fn: _f())
            row.addWidget(b)
        v.addLayout(row)
        self.proj = QTableWidget(0, 8)
        self.proj.setHorizontalHeaderLabels(["Project", "Owner", "Location",
                                             "State", "Bid date", "Bidders",
                                             "Items", "Added by"])
        self.proj.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch)
        self.proj.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.proj.itemSelectionChanged.connect(self.fill_items)
        v.addWidget(self.proj)
        split.addWidget(top)

        mid = QWidget()
        v = QVBoxLayout(mid)
        v.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search items")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda *_: self.fill_items())
        row.addWidget(self.search, 1)
        self.state = QComboBox()
        self.trade = QComboBox()
        for label, w in (("State:", self.state), ("Trade:", self.trade)):
            row.addWidget(QLabel(label))
            w.currentIndexChanged.connect(lambda *_: self.fill_items())
            row.addWidget(w)
        row.addWidget(QLabel("Escalate to:"))
        self.to = QLineEdit(_dt.date.today().strftime("%Y-%m"))
        self.to.setMaximumWidth(80)
        self.to.editingFinished.connect(self.fill_items)
        row.addWidget(self.to)
        self.only_sel = QCheckBox("Selected projects only")
        self.only_sel.toggled.connect(lambda *_: self.fill_items())
        row.addWidget(self.only_sel)
        self.by_vocab = QCheckBox("Group by vocabulary")
        self.by_vocab.setChecked(True)
        self.by_vocab.setToolTip("Count different wordings of the same item "
                                 "together (Vocabulary…)")
        self.by_vocab.toggled.connect(lambda *_: self.fill_items())
        row.addWidget(self.by_vocab)
        v.addLayout(row)
        self.items = QTableWidget(0, len(self.ITEM_COLS))
        self.items.setHorizontalHeaderLabels(self.ITEM_COLS)
        self.items.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.Stretch)
        self.items.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.items.setSortingEnabled(True)
        v.addWidget(self.items)
        self.count = QLabel("")
        v.addWidget(self.count)
        row = QHBoxLayout()
        for label, fn in (("Level Selected Project…", self.level),
                          ("Add Selected to Assembly Library",
                           self.add_selected),
                          ("Compare With This Job's Estimate", self.compare),
                          ("Export…", self.export)):
            b = QPushButton(label)
            b.clicked.connect(lambda _c=False, _f=fn: _f())
            row.addWidget(b)
        row.addStretch()
        v.addLayout(row)
        split.addWidget(mid)
        split.setSizes([260, 520])
        note = QLabel("Bid prices are installed unit prices including the "
                      "bidders' overhead and profit. Each bid is escalated "
                      "from its project's bid date at the trade's yearly "
                      "rate. Spreads over 35% are flagged REVIEW.")
        note.setWordWrap(True)
        lay.addWidget(note)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.refresh()

    def refresh(self):
        try:
            projs = self.bidtab.projects()
            states, trades = self.bidtab.states(), self.bidtab.trades()
        except pricedb.PriceDBError as e:
            QMessageBox.warning(self, "Bid Tabs", str(e))
            projs, states, trades = [], [], []
        self.proj.blockSignals(True)
        self.proj.setRowCount(len(projs))
        for r, p in enumerate(projs):
            for c, k in enumerate(("name", "owner", "location", "state",
                                   "bid_date", "bidders", "items",
                                   "added_by")):
                it = _item(p.get(k), right=c in (5, 6))
                if c == 0:
                    it.setData(Qt.UserRole, p["id"])
                self.proj.setItem(r, c, it)
        self.proj.blockSignals(False)
        for box, vals in ((self.state, states), (self.trade, trades)):
            cur = box.currentData()
            box.blockSignals(True)
            box.clear()
            box.addItem("All", None)
            for x in vals:
                box.addItem(x, x)
            i = box.findData(cur)
            box.setCurrentIndex(max(0, i))
            box.blockSignals(False)
        self.fill_items()

    def selected_projects(self):
        rows = {i.row() for i in self.proj.selectedItems()}
        return [self.proj.item(r, 0).data(Qt.UserRole) for r in sorted(rows)]

    def fill_items(self):
        sel = self.selected_projects() if self.only_sel.isChecked() else None
        try:
            self.data = self.bidtab.analyze(
                to=self.to.text().strip() or None,
                state=self.state.currentData(), trade=self.trade.currentData(),
                search=self.search.text(), projects_in=sel or None,
                use_vocab=self.by_vocab.isChecked())
        except ValueError as e:
            QMessageBox.warning(self, "Bid Tabs", str(e))
            return []
        t = self.items
        t.setSortingEnabled(False)
        t.setRowCount(len(self.data))
        for r, i in enumerate(self.data):
            dates = i["first"] if i["first"] == i["last"] else \
                f"{i['first']} to {i['last']}"
            vals = [i["trade"], i["desc"], i["unit"], i["bids"],
                    i["projects"], f"{_c2(i['low']):,.2f}", f"{_c2(i['median']):,.2f}",
                    f"{_c2(i['high']):,.2f}", f"{i['spread']:.0f}",
                    f"{_c2(i['esc_median']):,.2f}", " ".join(i["states"]), dates,
                    "REVIEW" if i["flag"] else ""]
            for c, val in enumerate(vals):
                it = _item(val, right=c in range(3, 10))
                if c in (3, 4):
                    it.setData(Qt.DisplayRole, int(val))
                if c == 0:
                    it.setData(Qt.UserRole, r)
                if c == 1 and i.get("wordings", 1) > 1:
                    it.setToolTip(f"{i['wordings']} different wordings in "
                                  "the bid tabs")
                t.setItem(r, c, it)
        t.setSortingEnabled(True)
        flagged = sum(1 for i in self.data if i["flag"])
        self.count.setText(f"{len(self.data)} item(s), {flagged} flagged")
        return self.data

    def chosen_items(self):
        rows = {i.row() for i in self.items.selectedItems()}
        return [self.data[self.items.item(r, 0).data(Qt.UserRole)]
                for r in sorted(rows)]

    def import_files(self, paths=None, values=None):
        if paths is None:
            paths, _ = QFileDialog.getOpenFileNames(
                self, "Import Bid Tab", "", "Bid tabs (*.csv *.tsv *.txt "
                "*.xlsx *.pdf);;All files (*)")
        if not paths:
            return None
        if values is None:
            dlg = ImportBidTab(paths, self)
            if dlg.exec() != QDialog.Accepted:
                return None
            values = dlg.values()
        values = dict(values)
        create = values.pop("create_new_min", 0)
        try:
            res = self.bidtab.import_and_route(paths, create_new_min=create,
                                               **values)
        except (ValueError, OSError, pricedb.PriceDBError) as e:
            QMessageBox.warning(self, "Import Bid Tab", str(e))
            return None
        self.refresh()
        self.last_import = res
        QMessageBox.information(
            self, "Import Bid Tab",
            f"Imported {res['rows']} line(s) from {res['bidders']} bidder(s)."
            f"\n\nVocabulary: {res['auto']} matched with confidence, "
            f"{res['review']} queued for review, {res['new']} with no match"
            + (f" ({res['created']} new item(s) made)" if res["created"] else
               "") + ". Bid Tabs > Vocabulary to review them.")
        return res

    def remove(self):
        ids = self.selected_projects()
        if not ids or QMessageBox.question(
                self, "Bid Tabs", f"Remove {len(ids)} project(s) and their "
                "bids from the price database?") != QMessageBox.Yes:
            return 0
        for pid in ids:
            self.bidtab.remove_project(pid)
        self.refresh()
        return len(ids)

    def edit_rates(self):
        rates = self.bidtab.rates()
        dlg = QDialog(self)
        dlg.setWindowTitle("Escalation Rates")
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel("Yearly escalation % by trade"))
        t = QTableWidget(len(rates), 2)
        t.setHorizontalHeaderLabels(["Trade", "% per year"])
        for r, (k, v) in enumerate(sorted(rates.items())):
            t.setItem(r, 0, _item(k))
            t.setItem(r, 1, _item(f"{v:g}", True, True))
        t.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        lay.addWidget(t)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)
        self._rates_dlg = (dlg, t)
        if dlg.exec() != QDialog.Accepted:
            return None
        return self._save_rates(t)

    def level(self):
        from .leveling_ui import LevelingDialog
        ids = self.selected_projects()
        dlg = LevelingDialog(self, ids[0] if ids else None)
        self._level = dlg
        if ids:
            dlg.run()
        dlg.show()
        return dlg

    def vocabulary(self):
        dlg = VocabDialog(self)
        self._vocab = dlg
        dlg.exec()
        self.fill_items()
        return dlg

    def bls_rates(self):
        from .ppi_ui import EscalationDialog
        dlg = EscalationDialog(self)
        self._esc = dlg
        dlg.exec()
        self.fill_items()
        return dlg

    def _save_rates(self, t):
        out = {}
        for r in range(t.rowCount()):
            try:
                out[t.item(r, 0).text()] = _num(t.item(r, 1).text())
            except ValueError:
                pass
        self.bidtab.set_rates(out)
        self.fill_items()
        return out

    def add_selected(self):
        items = self.chosen_items()
        if not items:
            QMessageBox.information(self, "Bid Tabs", "Select items first.")
            return []
        names = self.bidtab.add_to_library(items, self.to.text().strip())
        QMessageBox.information(
            self, "Bid Tabs", f"Added {len(names)} unit-price assemblies to "
            "your Assembly Library (named \"... (bid tabs)\").")
        return names

    def compare(self):
        if self.doc is None:
            return []
        rows = self.bidtab.compare(self.doc, self.to.text().strip() or None,
                                   items=self.data)
        dlg = QDialog(self)
        dlg.setWindowTitle("Estimate vs Bid Tabs")
        dlg.resize(1000, 480)
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel(
            "Your cost per unit (before markup) next to the bid median "
            "(installed, with the bidders' markup)." if rows else
            "None of this job's assemblies match a bid tab item with the "
            "same unit."))
        t = QTableWidget(len(rows), 8)
        t.setHorizontalHeaderLabels(["Assembly", "Qty", "Unit", "Yours/unit",
                                     "Bid item", "Bid low-high",
                                     "Bid median", "Yours vs median"])
        t.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for r, x in enumerate(rows):
            for c, val in enumerate((
                    x["assembly"], f"{x['quantity']:,.1f}", x["unit"],
                    f"{_c2(x['ours']):,.2f}", x["bid_item"],
                    f"{_c2(x['bid_low']):,.2f} - {_c2(x['bid_high']):,.2f}",
                    f"{_c2(x['bid_median']):,.2f}", f"{x['ratio'] * 100:.0f}%")):
                t.setItem(r, c, _item(val, right=c in (1, 3, 5, 6, 7)))
        lay.addWidget(t)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)
        self._compare_dlg = dlg
        dlg.show()
        return rows

    def export(self, path=None, fmt=None):
        if path is None:
            path, filt = QFileDialog.getSaveFileName(
                self, "Export Bid Tab Library", "bid tab library.csv",
                "Unit cost library (*.csv);;Full analysis (*.csv);;"
                "Trade rollup (*.csv)")
            if not path:
                return None
            fmt = "full" if filt.startswith("Full") else \
                "roll" if filt.startswith("Trade") else "lib"
        return self.bidtab.export(self.data, path, fmt or "lib",
                                  self.to.text().strip())


# ---- Vocabulary -------------------------------------------------------------------

class VocabDialog(QDialog):
    """The pay item vocabulary: map bid tab wordings to one canonical item
    each, so prices from different owners count together."""

    def __init__(self, parent=None):
        from . import vocab
        super().__init__(parent)
        self.vocab = vocab
        self.setWindowTitle("Pay Item Vocabulary")
        self.resize(1250, 720)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(
            "Left: every description in your bid tabs and what it matches. "
            "Right: your vocabulary (one name and unit per item). Map a "
            "wording to an item, add it as a new item, or let QuantiSheet learn"
            " the close matches. Sizes and units must agree for a match."))
        split = QSplitter()
        lay.addWidget(split, 1)
        left_tabs = QTabWidget()
        q = QWidget()
        qv = QVBoxLayout(q)
        qv.setContentsMargins(0, 0, 0, 0)
        self.queue = QTableWidget(0, 5)
        self.queue.setHorizontalHeaderLabels(["Bid tab wording", "Unit",
                                              "Suggested item", "Score",
                                              "Why it's queued"])
        self.queue.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch)
        self.queue.setSelectionBehavior(QAbstractItemView.SelectRows)
        qv.addWidget(self.queue)
        row = QHBoxLayout()
        for label, fn in (("Approve", lambda: self.decide(True)),
                          ("Approve as Selected Item →",
                           lambda: self.decide(True, True)),
                          ("Reject", lambda: self.decide(False))):
            b = QPushButton(label)
            b.clicked.connect(fn)
            row.addWidget(b)
        qv.addLayout(row)
        left = QWidget()
        v = QVBoxLayout(left)
        v.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        self.only_open = QCheckBox("Unmatched only")
        self.only_open.setChecked(True)
        self.only_open.toggled.connect(lambda *_: self.fill_review())
        row.addWidget(self.only_open)
        row.addStretch()
        v.addLayout(row)
        self.review = QTableWidget(0, 6)
        self.review.setHorizontalHeaderLabels(
            ["Bid tab wording", "Unit", "Lines", "Match", "How", "Score"])
        self.review.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch)
        self.review.setSelectionBehavior(QAbstractItemView.SelectRows)
        v.addWidget(self.review)
        row = QHBoxLayout()
        for label, fn in (("Add as New Item", self.add_new),
                          ("Map to Selected Item →", self.map_to),
                          ("Learn Close Matches", self.learn)):
            b = QPushButton(label)
            b.clicked.connect(lambda _=False, f=fn: f())
            row.addWidget(b)
        v.addLayout(row)
        left_tabs.addTab(left, "All Wordings")
        left_tabs.addTab(q, "Review Queue")
        self.left_tabs = left_tabs
        split.addWidget(left_tabs)
        right = QWidget()
        v = QVBoxLayout(right)
        v.setContentsMargins(0, 0, 0, 0)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search the vocabulary")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda *_: self.fill_items())
        v.addWidget(self.search)
        self.items = QTableWidget(0, 4)
        self.items.setHorizontalHeaderLabels(["Item", "Unit", "Trade",
                                              "Wordings"])
        self.items.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch)
        self.items.setSelectionBehavior(QAbstractItemView.SelectRows)
        v.addWidget(self.items)
        row = QHBoxLayout()
        for label, fn in (("Add Catalog Assembly Names", self.seed),
                          ("Remove Item", self.remove)):
            b = QPushButton(label)
            b.clicked.connect(lambda _=False, f=fn: f())
            row.addWidget(b)
        v.addLayout(row)
        split.addWidget(right)
        split.setSizes([700, 500])
        self.status = QLabel("")
        lay.addWidget(self.status)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.refresh()

    def refresh(self):
        self.fill_items()
        self.fill_review()
        self.fill_queue()

    def fill_queue(self):
        self.queue_rows = self.vocab.review_queue()
        t = self.queue
        t.setRowCount(len(self.queue_rows))
        for r, x in enumerate(self.queue_rows):
            for c, v in enumerate((x["desc"], x["unit"] or "",
                                   x["match"] or "", f"{_c2(x['score']):.2f}",
                                   x["reason"])):
                t.setItem(r, c, _item(v, right=c == 3))
        if hasattr(self, "left_tabs"):
            self.left_tabs.setTabText(1, f"Review Queue "
                                         f"({len(self.queue_rows)})")
        return self.queue_rows

    def decide(self, approve, to_selected=False, rows=None, item_id=None):
        rows = rows if rows is not None else self._sel(self.queue,
                                                       self.queue_rows)
        if to_selected and item_id is None:
            its = self._sel(self.items, self.item_rows)
            if not its:
                QMessageBox.information(self, "Vocabulary", "Select the item "
                                        "on the right.")
                return 0
            item_id = its[0]["id"]
        n = sum(1 for x in rows if self.vocab.decide(x["id"], approve,
                                                     item_id))
        self.refresh()
        return n

    def fill_items(self):
        self.item_rows = self.vocab.items(self.search.text())
        t = self.items
        t.setRowCount(len(self.item_rows))
        for r, i in enumerate(self.item_rows):
            for c, v in enumerate((i["canonical"], i["unit"], i["trade"] or "",
                                   str(i["aliases"]))):
                t.setItem(r, c, _item(v, right=c == 3))
        return self.item_rows

    def fill_review(self):
        rows = self.vocab.review()
        total = len(rows)
        matched = sum(1 for x in rows if x["item_id"])
        if self.only_open.isChecked():
            rows = [x for x in rows if not x["item_id"]]
        self.review_rows = rows
        t = self.review
        t.setRowCount(len(rows))
        for r, x in enumerate(rows):
            guess = x["match"] or (f"(closest: {x['best']})" if x.get("best")
                                   else "")
            for c, v in enumerate((x["input"], x["unit"] or "", str(x["lines"]),
                                   guess, x["method"], f"{_c2(x['score']):.2f}")):
                t.setItem(r, c, _item(v, right=c in (2, 5)))
        self.status.setText(f"{matched} of {total} bid tab wordings matched "
                            f"to your vocabulary of {len(self.vocab.items())} "
                            "items.")
        return rows

    def _sel(self, table, rows):
        return [rows[i.row()] for i in table.selectedItems()
                if i.column() == 0 and i.row() < len(rows)]

    def add_new(self, rows=None, name=None):
        rows = rows if rows is not None else self._sel(self.review,
                                                       self.review_rows)
        if not rows:
            return []
        made = []
        for x in rows:
            canon = name if (name and len(rows) == 1) else x["input"].strip()
            if name is None and len(rows) == 1:
                from PySide6.QtWidgets import QInputDialog
                text, ok = QInputDialog.getText(
                    self, "New Item", "Name for this item:", QLineEdit.Normal,
                    canon)
                if not ok or not text.strip():
                    return []
                canon = text.strip()
            iid = self.vocab.add_item(canon, x["unit"] or "EA",
                                      x.get("trade") or "",
                                      aliases=[x["input"]])
            made.append(iid)
        self.refresh()
        return made

    def map_to(self, rows=None, item_id=None):
        rows = rows if rows is not None else self._sel(self.review,
                                                       self.review_rows)
        if item_id is None:
            its = self._sel(self.items, self.item_rows)
            if not its:
                QMessageBox.information(self, "Vocabulary", "Select the item "
                                        "on the right to map to.")
                return 0
            item_id = its[0]["id"]
        n = sum(1 for x in rows if self.vocab.add_alias(item_id, x["input"],
                                                        "mapped"))
        self.refresh()
        return n

    def learn(self, min_score=0.92):
        n = self.vocab.learn(min_score)
        self.refresh()
        QMessageBox.information(self, "Vocabulary", f"Learned {n} wording(s) "
                                f"that matched at {min_score:.0%} or better.")
        return n

    def seed(self):
        n = self.vocab.seed_from_catalog()
        self.refresh()
        return n

    def remove(self):
        its = self._sel(self.items, self.item_rows)
        for i in its:
            self.vocab.remove_item(i["id"])
        self.refresh()
        return len(its)
