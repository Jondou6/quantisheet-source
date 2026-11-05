"""Labor Rates & Crews and Cost Books dialogs (Takeoff menu)."""
import datetime as _dt
import os

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QComboBox, QDateEdit, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFileDialog, QFormLayout, QHBoxLayout, QHeaderView, QInputDialog, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton,
    QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

from . import assemblies, costbook, labor
from .assembly_ui import adjust_combos, adjust_value


def _money(v):
    return f"${v:,.2f}"


def _cell(table, r, c):
    it = table.item(r, c)
    return it.text().strip() if it else ""


class LaborDialog(QDialog):
    """This job's labor rate, trade rates, crews and adjustment factors."""

    def __init__(self, doc, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.setWindowTitle("Labor Rates & Crews")
        self.resize(720, 560)
        job = assemblies.read_job(doc)
        lay = QVBoxLayout(self)
        tabs = QTabWidget()
        lay.addWidget(tabs)

        # job
        w = QWidget()
        form = QFormLayout(w)
        self.rate = QDoubleSpinBox()
        self.rate.setRange(0, 1000)
        self.rate.setDecimals(2)
        self.rate.setValue(float(job.get("labor_rate") or 0))
        form.addRow("Labor rate for parts without a crew ($/hr):", self.rate)
        form.addRow(QLabel("<b>Job-wide labor adjustments</b> (an assembly "
                           "can set its own)"))
        self.adjust = adjust_combos(form, job.get("adjust"))
        self.factor = QLabel("")
        form.addRow("Combined:", self.factor)
        for cb in self.adjust.values():
            cb.currentIndexChanged.connect(self._show_factor)
        self._show_factor()
        tabs.addTab(w, "This Job")

        # trade rates
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(QLabel("Hourly rate of each trade for this job (blank "
                           "uses your default). Crews are costed at the "
                           "average rate of their members."))
        book, region, as_of = assemblies.job_costbook(job)
        table = labor.rates(book.labor_rates(region, as_of) if book else
                            None)
        self._defaults = table
        mine = job.get("rates") or {}
        self.rates = QTableWidget(len(table), 3)
        self.rates.setHorizontalHeaderLabels(["Trade", "Default $/hr",
                                              "This job $/hr"])
        self.rates.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch)
        for r, trade in enumerate(sorted(table)):
            a = QTableWidgetItem(trade)
            a.setFlags(a.flags() & ~Qt.ItemIsEditable)
            b = QTableWidgetItem(f"{table.get(trade, 0):.2f}")
            b.setFlags(b.flags() & ~Qt.ItemIsEditable)
            self.rates.setItem(r, 0, a)
            self.rates.setItem(r, 1, b)
            self.rates.setItem(r, 2, QTableWidgetItem(
                f"{float(mine[trade]):.2f}" if trade in mine else ""))
        v.addWidget(self.rates)
        b = QPushButton("Loaded Rate Builder…")
        b.setToolTip("Build each trade's true hourly cost from its wage: "
                     "fringes, payroll burden, workers' comp, liability, "
                     "tools, supervision, per diem")
        b.clicked.connect(lambda: self.loaded_rates())
        v.addWidget(b)
        tabs.addTab(w, "Trade Rates")

        # crews
        w = QWidget()
        v = QVBoxLayout(w)
        self.crews = QTableWidget(0, 4)
        self.crews.setHorizontalHeaderLabels(["Code", "Crew", "Members",
                                              "$/crew-hr (this job)"])
        self.crews.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.Stretch)
        v.addWidget(self.crews)
        row = QHBoxLayout()
        add = QPushButton("New Crew…")
        add.clicked.connect(self._new_crew)
        row.addWidget(add)
        row.addStretch()
        v.addLayout(row)
        tabs.addTab(w, "Crews")
        self._fill_crews()
        self.rates.itemChanged.connect(lambda *_: self._fill_crews())

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _show_factor(self, *_):
        f = labor.factor(adjust_value(self.adjust))
        self.factor.setText(f"labor hours x{f:.3g}")

    def loaded_rates(self, dlg=None):
        """Open the Loaded Rate Builder; its rates go into "This job"."""
        from .loaded_rate_ui import open_for_job
        dlg = dlg or open_for_job(self.doc, self)
        self._loaded_dlg = dlg
        if dlg.result_rates is None and dlg.exec() != QDialog.Accepted:
            return None
        got = dlg.result_rates or {}
        rows = {_cell(self.rates, r, 0): r for r in range(self.rates.rowCount())}
        for trade, v in got.items():
            r = rows.get(trade)
            if r is None:
                r = self.rates.rowCount()
                self.rates.insertRow(r)
                a = QTableWidgetItem(trade)
                a.setFlags(a.flags() & ~Qt.ItemIsEditable)
                self.rates.setItem(r, 0, a)
                self.rates.setItem(r, 1, QTableWidgetItem(""))
            self.rates.setItem(r, 2, QTableWidgetItem(f"{v:.2f}"))
        return got

    def job_rates(self):
        out = {}
        for r in range(self.rates.rowCount()):
            t = _cell(self.rates, r, 2).replace("$", "")
            if t:
                try:
                    out[_cell(self.rates, r, 0)] = float(t)
                except ValueError:
                    pass
        return out

    def _fill_crews(self):
        rates = dict(getattr(self, "_defaults", {}) or {})
        rates.update(self.job_rates())
        cr = labor.crews()
        self.crews.setRowCount(len(cr))
        for r, code in enumerate(sorted(cr)):
            spec = cr[code]
            members = ", ".join(f"{n:g} {t}" for t, n in spec["members"])
            rate = labor.crew_rate(code, rates)
            for c, val in enumerate((code, spec.get("name", ""), members,
                                     _money(rate) if rate else "")):
                it = QTableWidgetItem(val)
                it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                self.crews.setItem(r, c, it)

    def _new_crew(self):
        code, ok = QInputDialog.getText(self, "New Crew", "Crew code "
                                        "(e.g. C-3):")
        if not ok or not code.strip():
            return
        text, ok = QInputDialog.getText(
            self, "New Crew", "Members, e.g. \"2 Carpenter, 1 Laborer\":")
        if not ok:
            return
        members = []
        for chunk in text.split(","):
            bits = chunk.strip().split(None, 1)
            if len(bits) == 2:
                try:
                    members.append([bits[1], float(bits[0])])
                    continue
                except ValueError:
                    pass
            if chunk.strip():
                members.append([chunk.strip(), 1])
        try:
            labor.save_crew(code.strip().upper(), text.strip(), members)
        except ValueError as e:
            QMessageBox.warning(self, "New Crew", str(e))
            return
        self._fill_crews()

    def apply(self):
        assemblies.set_job_settings(
            self.doc, labor_rate=self.rate.value(),
            rates=self.job_rates() or None,
            adjust=adjust_value(self.adjust) or None)

    def accept(self):
        self.apply()
        super().accept()


class CostBookDialog(QDialog):
    """Pick the cost book this job is priced from, import or start books,
    and see what switching would change before applying it."""

    def __init__(self, doc, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.setWindowTitle("Cost Books")
        self.resize(820, 600)
        job = assemblies.read_job(doc)
        self.current, cur_region, cur_asof = assemblies.job_costbook(
            job, default=False)
        lay = QVBoxLayout(self)
        self.now = QLabel("")
        lay.addWidget(self.now)
        top = QHBoxLayout()
        left = QVBoxLayout()
        left.addWidget(QLabel("<b>Your cost books</b>"))
        self.books = QListWidget()
        self.books.currentItemChanged.connect(self._picked)
        left.addWidget(self.books)
        btns = QHBoxLayout()
        for label, fn in (("Import CSV…", self._import),
                          ("Import RSMeans…", self._import_rsmeans),
                          ("New From This Job…", self._from_job)):
            b = QPushButton(label)
            b.clicked.connect(lambda _c=False, _f=fn: _f())
            btns.addWidget(b)
        left.addLayout(btns)
        btns = QHBoxLayout()
        for label, fn, tip in (
                ("Import Your Own Price List…", self._import_own,
                 "A price list or cost data export you're licensed to use "
                 "(.xlsx or CSV): map its columns, kept only on this PC"),
                ("Location Factors…", self._location_factors,
                 "Your regions and their materials / labor / equipment "
                 "factors; search by state, city or ZIP")):
            b = QPushButton(label)
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False, f=fn: f())
            btns.addWidget(b)
        left.addLayout(btns)
        btns = QHBoxLayout()
        for label, fn in (("Edit Prices…", self._edit_prices),
                          ("Escalation (BLS)…", self._escalation),
                          ("Price Database…", self._database),
                          ("Export JSON…", self._export_json)):
            b = QPushButton(label)
            b.clicked.connect(lambda _c=False, _f=fn: _f())
            btns.addWidget(b)
        left.addLayout(btns)
        self.db_label = QLabel("")
        self.db_label.setWordWrap(True)
        left.addWidget(self.db_label)
        top.addLayout(left, 2)
        right = QFormLayout()
        self.info = QLabel("")
        self.info.setWordWrap(True)
        right.addRow(self.info)
        self.region = QComboBox()
        self.region.setEditable(False)
        self.region.currentIndexChanged.connect(self._region_info)
        right.addRow("Region:", self.region)
        self.region_info = QLabel("")
        self.region_info.setWordWrap(True)
        right.addRow(self.region_info)
        self.default_btn = QPushButton("Make Default for New Jobs")
        self.default_btn.setToolTip("Jobs that haven't picked a cost book "
                                    "are priced from this book and region")
        self.default_btn.clicked.connect(self._make_default)
        right.addRow(self.default_btn)
        self.as_of = QDateEdit()
        self.as_of.setCalendarPopup(True)
        self.as_of.setDisplayFormat("yyyy-MM-dd")
        d = _dt.date.fromisoformat(cur_asof) if cur_asof else _dt.date.today()
        self.as_of.setDate(QDate(d.year, d.month, d.day))
        right.addRow("Price as of:", self.as_of)
        prev = QPushButton("Preview Change")
        prev.clicked.connect(self.preview)
        right.addRow(prev)
        top.addLayout(right, 3)
        lay.addLayout(top)
        self._region_hint = cur_region
        self.diff = QTableWidget(0, 4)
        self.diff.setHorizontalHeaderLabels(["Assembly", "Now", "With this "
                                             "book", "Change"])
        self.diff.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch)
        lay.addWidget(self.diff)
        self.summary = QLabel("")
        self.summary.setWordWrap(True)
        lay.addWidget(self.summary)
        bb = QDialogButtonBox()
        self.use = bb.addButton("Use This Book for the Job",
                                QDialogButtonBox.AcceptRole)
        own = bb.addButton("Use Assemblies' Own Prices",
                           QDialogButtonBox.ResetRole)
        bb.addButton(QDialogButtonBox.Close)
        self.use.clicked.connect(self._use)
        own.clicked.connect(self._own)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self._fill()

    # ---- list ------------------------------------------------------------
    def _fill(self, select=None):
        job = assemblies.read_job(self.doc)
        dflt, dreg = assemblies.default_costbook()
        if self.current:
            txt = ("This job is priced from "
                   f"<b>{costbook.display_name(self.current.name)}</b>.")
        elif dflt is not None and not job.get("own_prices"):
            txt = ("This job uses your default book "
                   f"<b>{costbook.display_name(dflt.name)}</b> "
                   f"({dreg or dflt.region}).")
        else:
            txt = "This job uses the prices in its assemblies (no cost book)."
        self.now.setText(txt)
        self.books.clear()
        from . import pricedb
        try:
            self.paths = costbook.list_books()
        except pricedb.PriceDBError as e:
            self.paths = {}
            pricedb.state["offline"] = str(e)
        off = pricedb.state.get("offline")
        self.db_label.setText(
            f"<span style='color:#b00'>{off}</span>" if off else
            f"<small>Price database: {pricedb.path()}"
            + (" (shared)" if pricedb.is_shared() else "") + "</small>")
        names = list(self.paths)
        if self.current and self.current.name not in self.paths:
            names.insert(0, self.current.name)
        for n in names:
            it = QListWidgetItem(costbook.display_name(n) + (
                "  (this job)" if self.current and n == self.current.name
                else ""))
            it.setData(Qt.UserRole, n)
            self.books.addItem(it)
        want = select or (self.current.name if self.current else None)
        for i in range(self.books.count()):
            if self.books.item(i).data(Qt.UserRole) == want:
                self.books.setCurrentRow(i)
                return
        if self.books.count():
            self.books.setCurrentRow(0)

    def book(self):
        it = self.books.currentItem()
        if not it:
            return None
        name = it.data(Qt.UserRole)
        if name in self.paths:
            try:
                return costbook.load(self.paths[name])
            except (OSError, ValueError) as e:
                QMessageBox.warning(self, "Cost Books", f"Can't read {name}: "
                                    f"{e}")
                return None
        return self.current if self.current and \
            self.current.name == name else None

    def _picked(self, *_):
        b = self.book()
        self.region.clear()
        if not b:
            self.info.setText("")
            return
        self.region.blockSignals(True)
        for r in b.region_names():
            label = f"{r}  (materials x{float(b.index.get(r, 1.0)):g}"
            label += ", own labor rates)" if r in b.rates else ")"
            self.region.addItem(label, r)
        hint = self._region_hint
        if hint not in b.region_names():
            hint = self._job_zip_region(b) or costbook.home_region(b)
        i = self.region.findData(hint)
        self.region.setCurrentIndex(max(0, i))
        self.region.blockSignals(False)
        basis = {}
        for it in b.items.values():
            k = it.get("basis") or "unmarked"
            basis[k] = basis.get(k, 0) + 1
        kinds = ", ".join(f"{n} {k}" for k, n in sorted(
            basis.items(), key=lambda x: -x[1])) if len(basis) > 1 or \
            "unmarked" not in basis else ""
        txt = (f"<b>{costbook.display_name(b.name)}</b><br>"
               f"{len(b.items)} items, prices as of "
               f"{b.effective}, escalation {b.escalation * 100:.1f}%/yr")
        if kinds:
            txt += f"<br>{kinds}"
        if b.escalation_by_div:
            txt += (f"<br>Escalation by division ({len(b.escalation_by_div)}"
                    f" divisions): {b.escalation_source or 'custom'}")
        if b.notes:
            txt += f"<br><small>{b.notes}</small>"
        self.info.setText(txt)
        self._region_info()
        self.diff.setRowCount(0)
        self.summary.setText("")

    def _job_zip_region(self, book):
        """The book's region for the job's location (Job Info: picked
        region or Job ZIP, through your Location Factors), or None."""
        try:
            from . import jobinfo
            reg = jobinfo.region(self.doc)
            return book.resolve_region(reg) if reg else None
        except Exception:                                 # noqa: BLE001
            return None

    def _region_info(self, *_):
        b = self.book()
        reg = self.region.currentData()
        if not b or not reg:
            self.region_info.setText("")
            return
        rates = b.labor_rates(reg, self.as_of.date().toString("yyyy-MM-dd"))
        if not rates:
            self.region_info.setText("Labor at your trade rates (Labor "
                                     "Rates & Crews).")
            return
        show = [t for t in ("Carpenter", "Laborer", "Electrician", "Plumber",
                            "Operator", "Mason") if t in rates]
        self.region_info.setText(
            "Labor (burdened $/hr): " + ", ".join(
                f"{t} ${rates[t]:,.2f}" for t in show) +
            f" and {max(0, len(rates) - len(show))} more trades.")

    def _make_default(self):
        b = self.book()
        if not b:
            return
        costbook.set_default(b, self.region.currentData())
        self._fill(b.name)

    def _import_rsmeans(self, path=None):
        if path is None:
            path, _ = QFileDialog.getOpenFileName(
                self, "Import RSMeans", "", "RSMeans assemblies export "
                "(*.txt *.csv);;All files (*)")
        if not path:
            return None
        from . import rsmeans
        try:
            res = rsmeans.import_file(path)
        except (OSError, ValueError) as e:
            QMessageBox.warning(self, "Import RSMeans", str(e))
            return None
        QMessageBox.information(
            self, "Import RSMeans",
            f"Added {res['assemblies']} RSMeans assemblies to the Assembly "
            f"Library and made the cost book \"{res['book']}\" (your "
            f"starter prices plus RSMeans). {len(res['calibrated'])} catalog "
            "assemblies were calibrated to RSMeans"
            + (f"; {len(res['skipped'])} matched but were left alone." if
               res["skipped"] else ".") +
            "\n\nPick it here and click Make Default for New Jobs to use it.")
        self._fill(res["book"])
        return res

    def _choice(self):
        return (self.book(), self.region.currentData(),
                self.as_of.date().toString("yyyy-MM-dd"))

    # ---- actions -----------------------------------------------------------
    def preview(self):
        book, region, as_of = self._choice()
        if not book:
            return None
        diff, before, after, problems = assemblies.reprice(
            self.doc, book, region, as_of)
        self.diff.setRowCount(len(diff))
        for r, d in enumerate(diff):
            ch = d["change"]
            for c, val in enumerate((d["name"], _money(d["before"]),
                                     _money(d["after"]),
                                     ("+" if ch > 0 else "") + _money(ch))):
                it = QTableWidgetItem(val)
                if c:
                    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.diff.setItem(r, c, it)
        pct = f" ({(after - before) / before * 100:+.1f}%)" if before else ""
        txt = (f"Total now {_money(before)}, with "
               f"{costbook.display_name(book.name)} "
               f"{_money(after)}{pct}. Factor x{book.factor(region, as_of):.3f}"
               f" for {region} as of {as_of}.")
        if problems:
            txt += "<br><span style='color:#b00'>" + "<br>".join(
                problems[:6]) + "</span>"
        self.summary.setText(txt)
        return diff

    def _use(self):
        book, region, as_of = self._choice()
        if not book:
            return
        self.preview()
        assemblies.set_costbook(self.doc, book, region, as_of)
        self.accept()

    def _own(self):
        assemblies.set_costbook(self.doc, None)
        self.accept()

    def _import(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Cost Book", "", "Spreadsheet (*.csv *.xlsx);;"
            "Cost book (*.json)")
        if not path:
            return
        try:
            if path.lower().endswith(".json"):
                book = costbook.load(path)
                book.path = None
            else:
                name, ok = QInputDialog.getText(
                    self, "Import Cost Book", "Name:", QLineEdit.Normal,
                    os.path.splitext(os.path.basename(path))[0])
                if not ok:
                    return
                rate, ok = QInputDialog.getDouble(
                    self, "Import Cost Book", "Escalation per year (%):", 0,
                    -20, 50, 1)
                if not ok:
                    return
                book = costbook.from_csv(path, name=name or None,
                                         escalation=rate / 100)
        except (OSError, ValueError, KeyError) as e:
            QMessageBox.warning(self, "Import Cost Book", str(e))
            return
        if not book.items:
            QMessageBox.warning(
                self, "Import Cost Book", "No items found. The sheet needs "
                "a Code column, plus Description, Unit, Material, Equipment,"
                " Labor (hours per unit), Crew and Sub.")
            return
        costbook.save(book)
        self._fill(book.name)

    def _import_own(self, path=None):
        """Import Your Own Price List (priceimport_ui.py)."""
        from .priceimport_ui import ImportPriceListDialog
        dlg = ImportPriceListDialog(self, path)
        self._own_dlg = dlg
        if dlg.exec() and dlg.result:
            self._fill(dlg.result["book"].name)
        return dlg

    def _location_factors(self):
        from .location_ui import LocationFactorsDialog
        dlg = LocationFactorsDialog(self, self.doc)
        self._loc_dlg = dlg
        dlg.exec()
        return dlg

    def _from_job(self):
        name, ok = QInputDialog.getText(self, "New Cost Book", "Name:",
                                        QLineEdit.Normal, "My Prices")
        if not ok or not name.strip():
            return
        book = costbook.from_job(self.doc, name.strip())
        if not book.items:
            QMessageBox.information(
                self, "New Cost Book", "None of the assemblies' parts have a "
                "cost code yet. Add codes in Edit Assembly (Cost code "
                "column), then try again.")
            return
        costbook.save(book)
        self._fill(book.name)

    def _edit_prices(self):
        from .pricedb_ui import PriceEditor
        b = self.book()
        if not b:
            return None
        if not str(b.path or "").startswith(costbook.DB):
            QMessageBox.information(self, "Edit Prices", "This book is only "
                                    "in the job. Import it first.")
            return None
        dlg = PriceEditor(b.name, self)
        self._editor = dlg
        dlg.exec()
        self._fill(b.name)
        return dlg

    def _escalation(self):
        from .ppi_ui import EscalationDialog
        b = self.book()
        dlg = EscalationDialog(self, b.name if b else None)
        self._esc = dlg
        dlg.exec()
        self._fill(b.name if b else None)
        return dlg

    def _database(self):
        from .pricedb_ui import DatabaseDialog
        dlg = DatabaseDialog(self)
        dlg.exec()
        self._fill()
        return dlg

    def _export_json(self, path=None):
        b = self.book()
        if not b:
            return None
        from .priceimport_ui import confirm_share
        if not confirm_share(self, b, "export"):       # licensed: ask first
            return None
        if path is None:
            path, _ = QFileDialog.getSaveFileName(
                self, "Export Cost Book", b.name + ".json",
                "Cost book (*.json)")
        if not path:
            return None
        return costbook.save(b, path)
