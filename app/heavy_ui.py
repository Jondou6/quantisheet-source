"""Civil estimate window (Civil tab): activities priced by crew and
production rate, the crews / equipment / labor libraries, the owner's bid
schedule, indirects, haul calculator, versions and field production."""
import os
from decimal import Decimal

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDateEdit,
                               QDialog,
                               QDoubleSpinBox, QFileDialog, QFormLayout,
                               QHBoxLayout, QHeaderView, QInputDialog,
                               QLabel, QMessageBox, QPushButton,
                               QTableWidget, QTableWidgetItem, QTabWidget,
                               QVBoxLayout, QWidget)

from . import heavy
from .dmoney import D, bad, fmt

RED = QColor(255, 215, 215)
TABS = ["Activities", "Crews", "Equipment", "Labor", "Bid Schedule",
        "Indirects", "Haul", "Versions", "Field", "Quotes", "Schedule",
        "Resources", "Forecast"]


def _ro(v, right=False):
    it = QTableWidgetItem("" if v is None else str(v))
    it.setFlags(it.flags() & ~Qt.ItemIsEditable)
    if right:
        it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
    return it


def _ed(v):
    return QTableWidgetItem("" if v is None else str(v))


def _pairs(text):
    """"FMN 1, OPR 2" -> [["FMN", 1], ["OPR", 2]]."""
    out = []
    for part in str(text or "").replace(";", ",").split(","):
        bits = part.split()
        if not bits:
            continue
        n = 1
        if len(bits) > 1:
            try:
                n = float(bits[-1])
                bits = bits[:-1]
            except ValueError:
                n = 1
        out.append([" ".join(bits), int(n) if n == int(n) else n])
    return out


def _pairs_text(pairs):
    return ", ".join(f"{c} {n:g}" if isinstance(n, (int, float)) else
                     f"{c} {n}" for c, n in pairs or [])


class Table(QTableWidget):
    """A table whose editable cells call back when changed."""

    def __init__(self, cols, on_edit=None):
        super().__init__(0, len(cols))
        self.setHorizontalHeaderLabels(cols)
        self.verticalHeader().setVisible(False)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self._filling = False
        self.on_edit = on_edit
        self.itemChanged.connect(self._changed)

    def _changed(self, it):
        if not self._filling and self.on_edit:
            self.on_edit(it.row(), it.column(), it.text())

    def fill(self, rows):
        """rows: [[QTableWidgetItem...]]"""
        self._filling = True
        self.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, it in enumerate(row):
                self.setItem(r, c, it)
        self._filling = False
        self.resizeColumnsToContents()


class HeavyDialog(QDialog):
    def _rname(self, kind, ext):
        """Default report file name - company rule, date first
        (app/reportname.py); the project is the PDF the job lives in."""
        from .reportname import report_file_name
        proj = os.path.splitext(os.path.basename(
            getattr(self.doc, "name", "") or ""))[0]
        return report_file_name(kind, proj, ext=ext)

    def __init__(self, win, tab=0):
        super().__init__(win)
        self.win = win
        v = getattr(win, "_view", None)
        # the job lives in this PDF; switching documents doesn't move it
        self._doc = v.doc if v is not None else None
        self.setWindowTitle("Civil Estimate - crews and production")
        self.resize(1300, 780)
        self.lib = heavy.library()
        self.job = heavy.read(self.doc) if self.doc is not None else \
            heavy.blank()
        v = QVBoxLayout(self)
        self.summary = QLabel()
        f = self.summary.font()
        f.setBold(True)
        self.summary.setFont(f)
        v.addWidget(self.summary)
        # newer starter rates are offered here, never applied on launch
        self.rates_bar = QWidget()
        h = QHBoxLayout(self.rates_bar)
        h.setContentsMargins(0, 0, 0, 0)
        self.rates_note = QLabel()
        self.rates_note.setWordWrap(True)
        h.addWidget(self.rates_note, 1)
        b = QPushButton("Use new rates")
        b.clicked.connect(self.use_new_rates)
        h.addWidget(b)
        v.addWidget(self.rates_bar)
        self._rates_offer()
        self.tabs = QTabWidget()
        v.addWidget(self.tabs, 1)
        for name in TABS:
            w = QWidget()
            getattr(self, "_build_" + name.lower().replace(" ", "_"))(w)
            self.tabs.addTab(w, name)
        self.problems = QLabel()
        self.problems.setWordWrap(True)
        self.problems.setStyleSheet("color:#b45309")
        v.addWidget(self.problems)
        self.tabs.setCurrentIndex(tab)
        self.refresh()

    @property
    def doc(self):
        return self._doc

    def _rates_offer(self):
        n = sum(len(x) for x in heavy.starter_updates().values())
        self.rates_note.setText(
            f"{n} starter rate{'s' if n != 1 else ''} you haven't edited "
            "have newer researched values. Estimates keep today's rates "
            "until you click Use new rates (it updates the price database "
            "for everyone who shares it, and re-prices estimates that use "
            "those rates).")
        self.rates_bar.setVisible(bool(n))

    def _typo(self, text, blank_ok=True):
        """A rate or cost cell got text D() would save as $0 ("twenty",
        "8.5O"), or a required rate was cleared: keep the old value and
        say so in the problems line."""
        if not bad(text, blank_ok):
            return False
        self.refresh()
        self.problems.setText(
            f"⚠ Can't read {text.strip()!r} as a number, so it wasn't saved."
            if text.strip() else "⚠ That rate can't be blank (it would "
            "price at $0), so it wasn't saved.")
        return True

    def use_new_rates(self):
        from . import pricedb
        try:
            heavy.apply_starter_updates()
        except pricedb.PriceDBError as e:
            self.rates_note.setText(f"Couldn't update the rates: {e}")
            return
        self.rates_bar.setVisible(False)
        self.refresh()

    def save(self):
        if self.doc is None:
            return
        heavy.write(self.doc, self.job)
        v = getattr(self.win, "_view", None)
        if v is not None and v.doc is self.doc:
            try:
                v.mark_dirty()
            except Exception:
                pass

    def refresh(self):
        self.lib = heavy.library()
        t = heavy.totals(self.job, self.lib)
        self.summary.setText(
            f"Direct {fmt(t['direct'])}  +  indirects {fmt(t['indirect'])}"
            f"  +  markup {fmt(t['markup'])}  +  bond {fmt(t['bond'])}  =  "
            f"bid {fmt(t['total'])}")
        self.problems.setText("⚠ " + "; ".join(t["problems"])
                              if t["problems"] else "")
        for name in TABS:
            fn = getattr(self, "_fill_" + name.lower().replace(" ", "_"),
                         None)
            if fn:
                fn()
        return t

    def _buttons(self, layout, specs):
        row = QHBoxLayout()
        for label, fn in specs:
            b = QPushButton(label)
            b.clicked.connect(lambda _c=False, f=fn: f())
            row.addWidget(b)
        row.addStretch()
        layout.addLayout(row)
        return row

    # ============================================================ activities
    ACOLS = ["Activity", "Pay item", "Cost code", "Qty", "Unit",
             "Takeoff group", "Crew", "Production", "Per", "Material $/unit",
             "Sub $", "Tags", "Crew hrs", "Days", "Total", "$/unit"]
    AKEYS = ["name", "pay_item", "code", "qty", "unit", "group", "crew",
             "rate", "per", "_mat", "sub", "_tags"]

    def _build_activities(self, w):
        v = QVBoxLayout(w)
        v.addWidget(QLabel("Price the work the way it's built: crew hours = "
                           "quantity / production rate. Tie an activity to "
                           "a takeoff group and its quantity follows the "
                           "takeoff."))
        self._buttons(v, [("Add Activity", self.add_activity),
                          ("Add From Takeoff Group…", self.add_from_group),
                          ("Add All Takeoff Groups", self.add_all_groups),
                          ("Refresh Quantities From Takeoff",
                           self.refresh_quantities),
                          ("Suggest Rate From Field History",
                           self.suggest_rate),
                          ("Delete", self.delete_activity)])
        self._buttons(v, [("Save to Library", self.save_to_library),
                          ("Add From Library…", self.add_from_library),
                          ("Save Estimate as Master…", self.save_master),
                          ("Start From Master…", self.start_from_master)])
        self.acts = Table(self.ACOLS, self._edit_activity)
        v.addWidget(self.acts, 1)

    def _fill_activities(self):
        rows = []
        for a, c in heavy.totals(self.job, self.lib)["activities"]:
            mat = sum((D(m.get("qty_per", 1)) * D(m.get("cost"))
                       for m in a.get("materials") or []), Decimal(0))
            vals = [a.get("name"), a.get("pay_item"), a.get("code"),
                    a.get("qty"), a.get("unit"), a.get("group"),
                    a.get("crew"), a.get("rate"), a.get("per"),
                    f"{mat:g}", a.get("sub"), ", ".join(a.get("tags") or [])]
            row = [_ed(x) for x in vals]
            row += [_ro(c["hours"], True), _ro(c["days"], True),
                    _ro(fmt(c["total"]), True), _ro(fmt(c["unit_cost"]),
                                                    True)]
            if c["problem"]:
                for it in row:
                    it.setBackground(RED)
                    it.setToolTip(c["problem"])
            rows.append(row)
        self.acts.fill(rows)

    def _edit_activity(self, r, c, text):
        a = self.job["activities"][r]
        k = self.AKEYS[c]
        if k in ("_mat", "qty", "rate", "sub") and self._typo(text):
            return
        if k == "_mat":
            a["materials"] = [{"desc": "materials", "qty_per": 1,
                               "cost": str(D(text))}]
        elif k == "_tags":
            a["tags"] = [t.strip() for t in text.split(",") if t.strip()]
        elif k == "per":
            a["per"] = "day" if text.strip().lower().startswith("d") \
                else "hour"
        elif k in ("qty", "rate", "sub"):
            a[k] = str(D(text))
        else:
            a[k] = text.strip()
        self.save()
        self.refresh()

    def add_activity(self, **kw):
        crew = next(iter(self.lib["crews"]), "")
        a = heavy.add_activity(self.job, kw.pop("name", "New activity"),
                               crew=kw.pop("crew", crew), **kw)
        self.save()
        self.refresh()
        return a

    def add_from_group(self, group=None):
        from . import annotate
        if self.doc is None:
            return None
        groups = sorted({it["group"] for it in
                         annotate.takeoff_items(self.doc) if it["group"]})
        if not groups:
            QMessageBox.information(self, "Civil Estimate",
                                    "There's no takeoff on this PDF yet.")
            return None
        if group is None:
            group, ok = QInputDialog.getItem(self, "From Takeoff",
                                             "Takeoff group:", groups, 0,
                                             False)
            if not ok:
                return None
        q, u = heavy.takeoff_qty(self.doc, group)
        return self.add_activity(name=group, qty=q, unit=u, group=group)

    def add_all_groups(self):
        """Every takeoff group not in the estimate yet, with a crew and a
        starting production rate."""
        if self.doc is None:
            return []
        from PySide6.QtWidgets import QApplication
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            pages = heavy.civil_pages(self.doc) if self.doc.page_count > 1 \
                else None
            new = heavy.activities_from_takeoff(self.doc, self.job,
                                                self.lib, pages or None)
        finally:
            QApplication.restoreOverrideCursor()
        self.save()
        self.refresh()
        return new

    def refresh_quantities(self):
        n = heavy.refresh_quantities(self.doc, self.job) if self.doc else 0
        self.save()
        self.refresh()
        return n

    def _current(self, table, items):
        r = table.currentRow()
        return items[r] if 0 <= r < len(items) else None

    def suggest_rate(self, apply=None):
        a = self._current(self.acts, self.job["activities"])
        if a is None or not a.get("code"):
            QMessageBox.information(self, "Civil Estimate", "Pick an "
                                    "activity with a cost code.")
            return None
        s = heavy.suggest_rate(a["code"])
        if s is None:
            QMessageBox.information(self, "Civil Estimate",
                                    f"No field history for {a['code']} "
                                    "yet.")
            return None
        if apply is None:
            apply = QMessageBox.question(
                self, "Production history",
                f"{a['code']}: {s['rate']} {s['unit']} per crew hour "
                f"(range {s['min']}-{s['max']}, {s['count']} days). Use "
                "it?") == QMessageBox.Yes
        if apply:
            a["rate"], a["per"] = str(s["rate"]), "hour"
            self.save()
            self.refresh()
        return s

    # ------------------------------------------------ library / masters
    def save_to_library(self, rows=None):
        """The selected activities (all when none is selected) into the
        company's activity library."""
        acts = self.job["activities"]
        if rows is None:
            rows = sorted({i.row() for i in self.acts.selectedIndexes()}) \
                or range(len(acts))
        keys = [heavy.save_to_library(acts[r], lib=self.lib)
                for r in rows if 0 <= r < len(acts)]
        self.refresh()
        return keys

    def add_from_library(self, key=None, qty=None):
        lib = heavy.library()
        if key is None:
            items = heavy.search_library(lib)
            if not items:
                QMessageBox.information(self, "Activity Library",
                                        "The library is empty. Select "
                                        "activities and click Save to "
                                        "Library.")
                return None
            labels = [f"{k} - {r.get('name', '')} ({r.get('crew', '')} "
                      f"@ {r.get('rate')}/{r.get('per', 'hour')})"
                      for k, r in items]
            pick, ok = QInputDialog.getItem(self, "Add From Library",
                                            "Activity:", labels, 0, True)
            if not ok or not pick:
                return None
            hits = [k for (k, _r), lb in zip(items, labels) if lb == pick] \
                or [k for k, _r in heavy.search_library(lib, pick)]
            if not hits:
                return None
            key = hits[0]
        if qty is None:
            qty, ok = QInputDialog.getDouble(self, "Add From Library",
                                             "Quantity", 0, 0, 1e9, 2)
            if not ok:
                return None
        a = heavy.add_from_library(self.job, key, lib, qty=qty)
        self.save()
        self.refresh()
        return a

    def save_master(self, name=None):
        if name is None:
            name, ok = QInputDialog.getText(self, "Master Estimate",
                                            "Name (e.g. Sewer extension)")
            if not ok or not name.strip():
                return None
        n = heavy.save_master(self.job, name)
        self.refresh()
        return n

    def start_from_master(self, name=None, confirm=True):
        lib = heavy.library()
        names = sorted(lib.get("masters") or {})
        if not names:
            QMessageBox.information(self, "Master Estimate", "No master "
                                    "estimates yet - Save Estimate as "
                                    "Master first.")
            return None
        if name is None:
            name, ok = QInputDialog.getItem(self, "Start From Master",
                                            "Master:", names, 0, False)
            if not ok:
                return None
        if confirm and self.job["activities"] and QMessageBox.question(
                self, "Start From Master", "Replace this estimate's "
                "activities and indirects with the master's? (Save a "
                "version first if you want to keep them.)") != \
                QMessageBox.Yes:
            return None
        new = heavy.new_from_master(name, lib, self.doc)
        for k in ("pay_items", "hauls", "versions", "wages"):
            new[k] = self.job.get(k, new[k])
        self.job = new
        self.save()
        self.refresh()
        return new

    # ------------------------------------------------ forecast
    FCOLS = ["Cost code", "Description", "Unit", "Budget", "Budget qty",
             "Installed", "% done", "Budget hrs", "Actual hrs", "Earned hrs",
             "Productivity", "Spent", "Projected", "Over (under)"]

    def _build_forecast(self, w):
        v = QVBoxLayout(w)
        v.addWidget(QLabel(
            "Cost to complete while the job runs: this estimate's budget "
            "by cost code against the project's time cards and direct "
            "costs. % done = installed / budget quantity; projected = "
            "spent / % done. Red runs more than 5% over."))
        self._buttons(v, [("Pick Project Center Folder…", self.pick_project),
                          ("Refresh", lambda: self._fill_forecast()),
                          ("Export…", self.export_forecast)])
        self.fc_proj = QLabel()
        v.addWidget(self.fc_proj)
        self.fc = Table(self.FCOLS)
        self.fc.setEditTriggers(QAbstractItemView.NoEditTriggers)
        v.addWidget(self.fc, 1)
        self.fc_note = QLabel()
        f = self.fc_note.font()
        f.setBold(True)
        self.fc_note.setFont(f)
        v.addWidget(self.fc_note)

    def _store(self):
        from .pm.store import ProjectStore
        folder = self.job["settings"].get("project_folder")
        if folder and ProjectStore.exists(folder):
            return ProjectStore(folder)
        return None

    def pick_project(self, folder=None):
        from .pm.store import ProjectStore
        if folder is None:
            folder = QFileDialog.getExistingDirectory(
                self, "Project Center folder of this job")
        if not folder or not ProjectStore.exists(folder):
            return None
        self.job["settings"]["project_folder"] = folder
        self.save()
        return self._fill_forecast()

    def _fill_forecast(self):
        st = self._store()
        if st is None:
            self.fc_proj.setText("No project picked yet.")
            self.fc.fill([])
            self.fc_note.setText("")
            return None
        self.fc_proj.setText("Project: " + self.job["settings"]
                             ["project_folder"])
        try:
            f = heavy.forecast(self.job, self.lib, st)
        except Exception as e:
            self.fc_note.setText(f"Couldn't read the project: {e}")
            return None

        def num(x, money=False):
            if x is None:
                return ""
            return fmt(x) if money else f"{x:,}"
        rows = []
        for r in f["rows"]:
            row = [_ro(r["code"]), _ro(r["desc"]), _ro(r["unit"]),
                   _ro(num(r["budget"], True), True),
                   _ro(num(r["budget_qty"]), True), _ro(num(r["qty"]), True),
                   _ro("" if r["pct"] is None else f"{r['pct']}%", True),
                   _ro(num(r["budget_hours"]), True),
                   _ro(num(r["hours"]), True),
                   _ro(num(r["earned_hours"]), True),
                   _ro(num(r["productivity"]), True),
                   _ro(num(r["spent"], True), True),
                   _ro(num(r["projected"], True), True),
                   _ro(num(r["variance"], True), True)]
            if r["flag"]:
                for it in row:
                    it.setBackground(RED)
            rows.append(row)
        self.fc.fill(rows)
        self.fc_note.setText(
            f"Budget {fmt(f['budget'])}  ·  spent {fmt(f['spent'])}  ·  "
            f"projected {fmt(f['projected'])}  ·  "
            f"{'over' if f['variance'] > 0 else 'under'} "
            f"{fmt(abs(f['variance']))}")
        return f

    def export_forecast(self, path=None):
        st = self._store()
        if st is None:
            return None
        if path is None:
            path, _ = QFileDialog.getSaveFileName(
                self, "Cost to Complete",
                self._rname("Cost to Complete", ".xlsx"),
                "Excel (*.xlsx);;CSV (*.csv)")
        if not path:
            return None
        return heavy.export_forecast(self.job, self.lib, st, path)

    def delete_activity(self):
        r = self.acts.currentRow()
        if 0 <= r < len(self.job["activities"]):
            self.job["activities"].pop(r)
            self.save()
            self.refresh()

    # ============================================================ crews
    CCOLS = ["Code", "Description", "Labor (class count, ...)",
             "Equipment (code count, ...)", "Labor $/hr", "Equip $/hr",
             "Crew $/hr"]

    def _build_crews(self, w):
        v = QVBoxLayout(w)
        v.addWidget(QLabel("Company crews (shared in the price database). "
                           "Labor and equipment are listed by code with "
                           "how many, e.g. \"FMN 1, OPR 2, LAB 3\"."))
        self._buttons(v, [("Add Crew", self.add_crew),
                          ("Delete", lambda: self._delete_lib(
                              "crews", self.crews))])
        self.crews = Table(self.CCOLS, self._edit_crew)
        v.addWidget(self.crews, 1)

    def _fill_crews(self):
        rows = []
        for code, c in sorted(self.lib["crews"].items()):
            cr = heavy.crew_rate(c, self.lib, self.job)
            row = [_ro(code), _ed(c.get("desc")),
                   _ed(_pairs_text(c.get("labor"))),
                   _ed(_pairs_text(c.get("equipment"))),
                   _ro(fmt(cr["labor"]), True),
                   _ro(fmt(cr["equipment"]), True),
                   _ro(fmt(cr["total"]), True)]
            if cr["missing"]:
                row[2].setBackground(RED)
                row[2].setToolTip("Not in the library: " +
                                  ", ".join(cr["missing"]))
            if cr["unreadable"]:
                row[6].setBackground(RED)
                row[6].setToolTip("Can't read: " +
                                  ", ".join(cr["unreadable"]))
            rows.append(row)
        self.crews.fill(rows)

    def _edit_crew(self, r, c, text):
        code = self.crews.item(r, 0).text()
        rec = dict(self.lib["crews"][code])
        if c == 1:
            rec["desc"] = text
        elif c == 2:
            rec["labor"] = _pairs(text)
        elif c == 3:
            rec["equipment"] = _pairs(text)
        heavy.save_items("crews", [rec])
        self.refresh()

    def add_crew(self, code=None, desc="", labor=(), equipment=()):
        if code is None:
            code, ok = QInputDialog.getText(self, "Add Crew", "Crew code")
            if not ok or not code.strip():
                return None
        heavy.save_items("crews", [{"code": code.strip(), "desc": desc,
                                    "labor": list(labor),
                                    "equipment": list(equipment)}])
        self.refresh()
        return code

    def _delete_lib(self, kind, table):
        r = table.currentRow()
        if r < 0:
            return
        code = table.item(r, 0).text()
        if QMessageBox.question(self, "Delete", f"Delete {code} from the "
                                "company library?") == QMessageBox.Yes:
            heavy.delete_item(kind, code)
            self.refresh()

    # ============================================================ equipment
    ECOLS = ["Code", "Description", "Class", "Own or rent", "Own $/hr",
             "Operating $/hr", "Fuel gal/hr", "Rent $/month", "Hours/month",
             "Total $/hr"]
    EKEYS = [None, "desc", "class", "use", "own_hr", "op_hr", "fuel_gph",
             "rent_month", "hours_month"]

    def _build_equipment(self, w):
        v = QVBoxLayout(w)
        row = QHBoxLayout()
        row.addWidget(QLabel("Fuel $/gal:"))
        self.fuel = QDoubleSpinBox()
        self.fuel.setRange(0, 20)
        self.fuel.setDecimals(2)
        self.fuel.editingFinished.connect(self._fuel_changed)
        row.addWidget(self.fuel)
        row.addWidget(QLabel("Ownership covers depreciation, interest, "
                             "insurance and storage; operating covers "
                             "repairs, tires and wear. Rented equipment "
                             "spreads the monthly rent over the hours it "
                             "runs."))
        row.addStretch()
        v.addLayout(row)
        self._buttons(v, [("Add Equipment", self.add_equipment),
                          ("Delete", lambda: self._delete_lib(
                              "equipment", self.equip))])
        self.equip = Table(self.ECOLS, self._edit_equipment)
        v.addWidget(self.equip, 1)

    def _fill_equipment(self):
        fuel = self.lib["settings"].get("fuel", 4)
        self.fuel.setValue(float(fuel))
        rows = []
        for code, e in sorted(self.lib["equipment"].items()):
            rate = heavy.equipment_rate(e, fuel)
            rows.append([_ro(code)] + [_ed(e.get(k, "")) for k in
                                       self.EKEYS[1:]] +
                        [_ro(fmt(rate["total"]), True)])
            rows[-1][0].setToolTip(e.get("source", ""))
        self.equip.fill(rows)

    def _fuel_changed(self):
        heavy.set_settings({"fuel": self.fuel.value()})
        self.refresh()

    def _edit_equipment(self, r, c, text):
        code = self.equip.item(r, 0).text()
        rec = dict(self.lib["equipment"][code])
        k = self.EKEYS[c]
        if k == "use":
            rec[k] = "rent" if text.strip().lower().startswith("r") \
                else "own"
        elif k in ("desc", "class"):
            rec[k] = text
        elif self._typo(text, k not in ("own_hr", "rent_month")):
            return
        else:
            rec[k] = float(D(text))
        rec["source"] = "your rate"
        heavy.save_items("equipment", [rec])
        self.refresh()

    def add_equipment(self, code=None, **rec):
        if code is None:
            code, ok = QInputDialog.getText(self, "Add Equipment", "Code")
            if not ok or not code.strip():
                return None
        heavy.save_items("equipment", [dict({"use": "own"}, code=code,
                                            **rec)])
        self.refresh()
        return code

    # ============================================================ labor
    LCOLS = ["Code", "Description", "Base $/hr", "Fringe $/hr", "OT %",
             "Workers' comp $/100", "FICA %", "Unemployment %", "GL %",
             "Other %", "Burdened $/hr", "Prevailing wage"]
    LKEYS = [None, "desc", "base", "fringe", "ot_pct", "wc_rate", "fica",
             "unemp", "gl_pct", "other_pct"]

    def _build_labor(self, w):
        v = QVBoxLayout(w)
        v.addWidget(QLabel("Burdened rate = (base + overtime premium) x (1 "
                           "+ taxes + workers' comp + insurance) + fringes. "
                           "A prevailing wage determination (Davis-Bacon) "
                           "replaces base and fringe on this job only."))
        self._buttons(v, [("Add Labor Class", self.add_labor),
                          ("Delete", lambda: self._delete_lib(
                              "labor", self.labor)),
                          ("Import Prevailing Wages (CSV)…",
                           self.import_wages),
                          ("Clear Prevailing Wages", self.clear_wages)])
        self.labor = Table(self.LCOLS, self._edit_labor)
        v.addWidget(self.labor, 1)

    def _fill_labor(self):
        rows = []
        wages = self.job.get("wages") or {}
        for code, rec in sorted(self.lib["labor"].items()):
            b = heavy.burden(rec, wages)
            w = wages.get(code)
            rows.append([_ro(code)] + [_ed(rec.get(k, "")) for k in
                                       self.LKEYS[1:]] +
                        [_ro(fmt(b["total"]), True),
                         _ro(f"{fmt(w['base'])} + {fmt(w['fringe'])}"
                             if w else "")])
            rows[-1][0].setToolTip(rec.get("source", ""))
        self.labor.fill(rows)

    def _edit_labor(self, r, c, text):
        code = self.labor.item(r, 0).text()
        rec = dict(self.lib["labor"][code])
        k = self.LKEYS[c]
        if k != "desc" and self._typo(text, k != "base"):
            return
        rec[k] = text if k == "desc" else float(D(text))
        rec["source"] = "your rate"
        heavy.save_items("labor", [rec])
        self.refresh()

    def add_labor(self, code=None, **rec):
        if code is None:
            code, ok = QInputDialog.getText(self, "Add Labor Class", "Code")
            if not ok or not code.strip():
                return None
        base = dict({"fica": 7.65, "unemp": 3.0, "gl_pct": 1.5,
                     "ot_pct": 10, "wc_rate": 8}, **rec)
        heavy.save_items("labor", [dict(base, code=code)])
        self.refresh()
        return code

    def import_wages(self, path=None):
        if path is None:
            path, _ = QFileDialog.getOpenFileName(
                self, "Wage Determination", "", "CSV (*.csv)")
        if not path:
            return None
        try:
            wages, left = heavy.read_wages_csv(path, self.lib)
        except (OSError, ValueError) as e:
            QMessageBox.warning(self, "Prevailing Wages",
                                f"Couldn't read {os.path.basename(path)}:\n{e}")
            return None
        self.job["wages"] = wages
        self.save()
        self.refresh()
        if left:
            QMessageBox.information(
                self, "Prevailing Wages", f"Matched {len(wages)} "
                "classification(s). Not matched to a labor class: " +
                ", ".join(left[:12]))
        return wages, left

    def clear_wages(self):
        self.job["wages"] = {}
        self.save()
        self.refresh()

    # ============================================================ bid sched
    PCOLS = ["Item", "Description", "Unit", "Owner qty", "Weight",
             "Your qty", "Qty diff %", "Direct cost", "Unit price",
             "Amount"]

    def _build_bid_schedule(self, w):
        v = QVBoxLayout(w)
        f = QHBoxLayout()
        f.addWidget(QLabel("Markup %:"))
        self.markup = QDoubleSpinBox()
        self.markup.setRange(0, 100)
        self.markup.editingFinished.connect(self._settings_changed)
        f.addWidget(self.markup)
        f.addWidget(QLabel("Bond %:"))
        self.bond = QDoubleSpinBox()
        self.bond.setRange(0, 10)
        self.bond.setDecimals(2)
        self.bond.editingFinished.connect(self._settings_changed)
        f.addWidget(self.bond)
        f.addWidget(QLabel("Weight above 1 moves indirects and markup onto "
                           "that item (front-loading); quantities more than "
                           "10% off the owner's are red."))
        f.addStretch()
        v.addLayout(f)
        self._buttons(v, [("Import Owner's Bid Schedule…", self.import_pay),
                          ("Export Priced Schedule…", self.export_pay)])
        self.pay = Table(self.PCOLS, self._edit_pay)
        v.addWidget(self.pay, 1)
        self.pay_note = QLabel()
        v.addWidget(self.pay_note)

    def _fill_bid_schedule(self):
        st = self.job["settings"]
        self.markup.setValue(float(D(st.get("markup_pct"))))
        self.bond.setValue(float(D(st.get("bond_pct"))))
        s = heavy.spread(self.job, self.lib)
        qc = {q["no"]: q for q in heavy.quantity_check(self.job)}
        rows = []
        for p, i in zip(self.job["pay_items"], s["items"]):
            q = qc.get(p["no"], {})
            row = [_ro(p["no"]), _ro(p.get("desc")), _ro(p.get("unit")),
                   _ed(p.get("owner_qty")), _ed(p.get("weight", "1")),
                   _ro(q.get("your_qty"), True),
                   _ro("" if q.get("diff_pct") is None else
                       f"{q['diff_pct']}%", True),
                   _ro(fmt(i["direct"]), True),
                   _ro(fmt(i["unit_price"]), True),
                   _ro(fmt(i["amount"]), True)]
            if q.get("flag"):
                for it in row:
                    it.setBackground(RED)
            rows.append(row)
        self.pay.fill(rows)
        bits = [f"Bid schedule total {fmt(s['bid'])}"]
        if s["unassigned"]:
            bits.append(f"{len(s['unassigned'])} activit(ies) worth "
                        f"{fmt(s['unassigned_cost'])} aren't on a pay item")
        if s["rounding"]:
            bits.append(f"rounding {fmt(s['rounding'])}")
        self.pay_note.setText(" · ".join(bits))

    def _settings_changed(self):
        self.job["settings"].update(markup_pct=self.markup.value(),
                                    bond_pct=self.bond.value())
        self.save()
        self.refresh()

    def _edit_pay(self, r, c, text):
        p = self.job["pay_items"][r]
        p["owner_qty" if c == 3 else "weight"] = str(D(text))
        self.save()
        self.refresh()

    def import_pay(self, path=None):
        if path is None:
            path, _ = QFileDialog.getOpenFileName(
                self, "Owner's Bid Schedule", "",
                "Bid schedule (*.csv *.xlsx)")
        if not path:
            return None
        try:
            self.job["pay_items"] = heavy.read_pay_items(path)
        except Exception as e:
            QMessageBox.warning(self, "Bid Schedule", str(e))
            return None
        self.save()
        self.refresh()
        return self.job["pay_items"]

    def export_pay(self, path=None):
        if path is None:
            path, _ = QFileDialog.getSaveFileName(
                self, "Priced Bid Schedule",
                self._rname("Bid Schedule", ".xlsx"),
                "Excel (*.xlsx);;CSV (*.csv)")
        if not path:
            return None
        return heavy.export_schedule(self.job, self.lib, path)

    # ============================================================ indirects
    ICOLS = ["Item", "Rate $", "Per (week, month, day, LS)", "Qty",
             "Weeks (blank = job)", "Total"]
    IKEYS = ["desc", "rate", "per", "qty", "duration"]

    def _build_indirects(self, w):
        v = QVBoxLayout(w)
        f = QHBoxLayout()
        f.addWidget(QLabel("Job duration (weeks):"))
        self.weeks = QDoubleSpinBox()
        self.weeks.setRange(0, 520)
        self.weeks.editingFinished.connect(self._weeks_changed)
        f.addWidget(self.weeks)
        f.addWidget(QLabel("Hours per day:"))
        self.hpd = QDoubleSpinBox()
        self.hpd.setRange(1, 24)
        self.hpd.editingFinished.connect(self._weeks_changed)
        f.addWidget(self.hpd)
        f.addStretch()
        v.addLayout(f)
        self._buttons(v, [("Add Indirect", self.add_indirect),
                          ("Add Typical Indirects", self.add_typical),
                          ("Delete", self.delete_indirect)])
        self.ind = Table(self.ICOLS, self._edit_indirect)
        v.addWidget(self.ind, 1)

    def _fill_indirects(self):
        st = self.job["settings"]
        self.weeks.setValue(float(D(st.get("duration_weeks"))))
        self.hpd.setValue(float(D(st.get("hours_per_day") or 10)))
        rows = [[_ed(i.get(k, "")) for k in self.IKEYS] +
                [_ro(fmt(heavy.indirect_cost(i, self.job)), True)]
                for i in self.job["indirects"]]
        self.ind.fill(rows)

    def _weeks_changed(self):
        self.job["settings"].update(duration_weeks=self.weeks.value(),
                                    hours_per_day=self.hpd.value())
        self.save()
        self.refresh()

    def _edit_indirect(self, r, c, text):
        i = self.job["indirects"][r]
        k = self.IKEYS[c]
        if k == "per":
            t = text.strip().lower()
            i[k] = next((p for p in heavy.INDIRECT_PERS
                         if p.lower().startswith(t[:1])), "LS")
        elif k == "desc":
            i[k] = text
        elif self._typo(text):
            return
        else:
            i[k] = str(D(text)) if text.strip() else ""
        self.save()
        self.refresh()

    def add_indirect(self, desc="New indirect", rate=0, per="week"):
        self.job["indirects"].append({"desc": desc, "rate": str(rate),
                                      "per": per, "qty": "1",
                                      "duration": ""})
        self.save()
        self.refresh()

    TYPICAL = [("Superintendent", 2800, "week"),
               ("Project manager (part)", 900, "week"),
               ("Field office trailer", 650, "month"),
               ("Toilets", 180, "month"), ("Small tools", 250, "week"),
               ("Traffic control", 1200, "week"),
               ("Testing / QC", 400, "week"),
               ("Mobilization", 15000, "LS")]

    def add_typical(self):
        for d, r, p in self.TYPICAL:
            self.job["indirects"].append({"desc": d + " (sample rate)",
                                          "rate": str(r), "per": p,
                                          "qty": "1", "duration": ""})
        self.save()
        self.refresh()

    def delete_indirect(self):
        r = self.ind.currentRow()
        if 0 <= r < len(self.job["indirects"]):
            self.job["indirects"].pop(r)
            self.save()
            self.refresh()

    # ============================================================ haul
    HAUL = [("cy_bank", "Bank cubic yards", 5000),
            ("swell_pct", "Swell %", 25), ("truck_cy", "Truck CY (loose)",
                                           14),
            ("miles", "Haul distance, miles (one way)", 5),
            ("mph_loaded", "Speed loaded, mph", 25),
            ("mph_empty", "Speed empty, mph", 35),
            ("load_min", "Load time, min", 4), ("dump_min", "Dump time, min",
                                                2),
            ("truck_hr", "Truck + driver $/hr", 95),
            ("loader_cyhr", "Loader CY/hr (loose)", 250),
            ("loader_hr", "Loader + operator $/hr", 150),
            ("trucks", "Trucks (0 = enough)", 0)]

    def _build_haul(self, w):
        v = QHBoxLayout(w)
        f = QFormLayout()
        self.haul_in = {}
        for k, label, val in self.HAUL:
            sb = QDoubleSpinBox()
            sb.setRange(0, 10_000_000)
            sb.setDecimals(1)
            sb.setValue(val)
            sb.valueChanged.connect(lambda _v: self._calc_haul())
            self.haul_in[k] = sb
            f.addRow(label, sb)
        left = QWidget()
        left.setLayout(f)
        v.addWidget(left)
        right = QVBoxLayout()
        self.haul_out = QLabel()
        self.haul_out.setTextFormat(Qt.RichText)
        right.addWidget(self.haul_out)
        b = QPushButton("Use Takeoff Earthwork Quantity…")
        b.clicked.connect(lambda: self.haul_from_takeoff())
        right.addWidget(b)
        b = QPushButton("Add as Trucking Activity")
        b.clicked.connect(lambda: self.add_haul_activity())
        right.addWidget(b)
        right.addStretch()
        v.addLayout(right, 1)
        self._calc_haul()

    def haul_inputs(self):
        return {k: str(sb.value()) for k, sb in self.haul_in.items()}

    def _calc_haul(self):
        r = heavy.haul(self.haul_inputs())
        self.haul_out.setText(
            f"<h3>{fmt(r['per_bank_cy'])} per bank CY</h3>"
            f"Loose: {r['loose_cy']} CY<br>Cycle: {r['cycle_min']} min<br>"
            f"Each truck hauls {r['truck_cyhr']} CY/hr<br>Trucks to keep "
            f"the loader busy: <b>{r['trucks_needed']}</b> (using "
            f"{r['trucks']})<br>Hours: {r['hours']}<br>Cost: "
            f"<b>{fmt(r['cost'])}</b>")
        return r

    def haul_from_takeoff(self, group=None):
        from . import annotate
        if self.doc is None:
            return None
        groups = sorted({it["group"] for it in annotate.takeoff_items(
            self.doc) if it["group"] and it["type"] in ("volume", "area")})
        if not groups:
            QMessageBox.information(self, "Haul", "No volume takeoff "
                                    "(Takeoff > Volume or Trade Takeoff > "
                                    "Earthwork) on this PDF.")
            return None
        if group is None:
            group, ok = QInputDialog.getItem(self, "Haul", "Earthwork:",
                                             groups, 0, False)
            if not ok:
                return None
        q, _u = heavy.takeoff_qty(self.doc, group)
        self.haul_in["cy_bank"].setValue(float(q))
        return q

    def add_haul_activity(self):
        r = self._calc_haul()
        h = self.haul_inputs()
        h["id"] = heavy._id()
        self.job["hauls"].append(h)
        a = heavy.add_activity(self.job, f"Haul off {h['cy_bank']} CY, "
                                         f"{h['miles']} mi",
                               qty=D(h["cy_bank"]), unit="CY",
                               sub=r["cost"], tags=["trucking"],
                               notes=f"haul {h['id']}: {r['trucks']} "
                                     f"trucks, {r['hours']} hr")
        self.save()
        self.refresh()
        return a

    # ============================================================ versions
    def _build_versions(self, w):
        v = QVBoxLayout(w)
        self._buttons(v, [("Save Version…", self.save_version),
                          ("Compare Two…", self.compare),
                          ("Restore Selected", self.restore)])
        self.vers = Table(["Version", "Saved", "By", "Total"])
        self.vers.setEditTriggers(QAbstractItemView.NoEditTriggers)
        v.addWidget(self.vers, 1)
        v.addWidget(QLabel("By tag (type tags on the Activities tab, "
                           "separated by commas):"))
        self.tags = Table(["Tag", "Total"])
        self.tags.setEditTriggers(QAbstractItemView.NoEditTriggers)
        v.addWidget(self.tags, 1)
        self.cmp = QLabel()
        self.cmp.setWordWrap(True)
        v.addWidget(self.cmp)

    def _fill_versions(self):
        self.vers.fill([[_ro(x["name"]), _ro(x["at"].replace("T", " ")),
                         _ro(x["by"]), _ro(fmt(x["total"]), True)]
                        for x in self.job["versions"]])
        self.tags.fill([[_ro(t), _ro(fmt(v), True)]
                        for t, v in heavy.by_tag(self.job, self.lib)
                        .items()])

    def save_version(self, name=None):
        if name is None:
            name, ok = QInputDialog.getText(self, "Save Version", "Name",
                                            text=f"Version "
                                            f"{len(self.job['versions']) + 1}")
            if not ok:
                return None
        v = heavy.save_version(self.job, name, self.lib)
        self.save()
        self.refresh()
        return v

    def compare(self, a=None, b=None):
        vs = self.job["versions"]
        if len(vs) < 2:
            QMessageBox.information(self, "Versions", "Save two versions "
                                    "first.")
            return None
        if a is None:
            names = [f"{i + 1}. {x['name']}" for i, x in enumerate(vs)]
            pa, ok = QInputDialog.getItem(self, "Compare", "From:", names,
                                          max(0, len(vs) - 2), False)
            if not ok:
                return None
            pb, ok = QInputDialog.getItem(self, "Compare", "To:", names,
                                          len(vs) - 1, False)
            if not ok:
                return None
            a, b = vs[names.index(pa)]["id"], vs[names.index(pb)]["id"]
        res = heavy.compare_versions(self.job, a, b, self.lib)
        lines = [f"{r['name']}: {fmt(r['a'])} → {fmt(r['b'])} "
                 f"({'+' if r['diff'] >= 0 else ''}{fmt(r['diff'])})"
                 for r in res["rows"][:20]]
        self.cmp.setText(f"Total {fmt(res['a'])} → {fmt(res['b'])}. " +
                         "; ".join(lines))
        return res

    def restore(self):
        r = self.vers.currentRow()
        if 0 <= r < len(self.job["versions"]):
            heavy.restore_version(self.job, self.job["versions"][r]["id"])
            self.save()
            self.refresh()

    # ============================================================ field
    def _build_field(self, w):
        v = QVBoxLayout(w)
        v.addWidget(QLabel(
            "Foremen enter daily time cards on the phone (the project's "
            "/project.html page > Time): crew hours, equipment hours and "
            "quantity installed by cost code. Approved cards become your "
            "production history - suggested rates on the Activities tab - "
            "and actual costs for Job Cost Feedback."))
        self._buttons(v, [("Open Time Cards (Project Center)",
                           self.open_timecards),
                          ("Record Production From a Project…",
                           self.record_from_project),
                          ("Look Up a Cost Code…", self.lookup)])
        self.field_out = QLabel()
        self.field_out.setWordWrap(True)
        v.addWidget(self.field_out)
        v.addStretch()

    def open_timecards(self):
        try:
            self.win.project_center()
        except Exception:
            pass

    def record_from_project(self, folder=None):
        from .pm.store import ProjectStore
        if folder is None:
            folder = QFileDialog.getExistingDirectory(
                self, "Project Center folder")
        if not folder or not ProjectStore.exists(folder):
            return None
        n = heavy.record_production(ProjectStore(folder))
        self.field_out.setText(f"Recorded {n} production day(s).")
        return n

    def lookup(self, code=None):
        if code is None:
            code, ok = QInputDialog.getText(self, "Production History",
                                            "Cost code")
            if not ok or not code.strip():
                return None
        s = heavy.suggest_rate(code.strip())
        self.field_out.setText(
            f"{code}: no history yet." if s is None else
            f"{code}: {s['rate']} {s['unit']} per crew hour (range "
            f"{s['min']}-{s['max']}, {s['count']} day(s)).")
        return s

    # ============================================================ quotes
    QCOLS = ["Vendor", "Material or sub", "Price", "Per (unit or LS)",
             "Amount", "Use", "Notes"]

    def _build_quotes(self, w):
        v = QVBoxLayout(w)
        v.addWidget(QLabel("Material and subcontractor quotes for each "
                           "activity. The one marked Use prices the "
                           "activity (the lowest, unless you pick "
                           "another); a wide spread between quotes often "
                           "means someone left scope out."))
        row = QHBoxLayout()
        row.addWidget(QLabel("Activity:"))
        self.q_act = QComboBox()
        self.q_act.currentIndexChanged.connect(lambda _i: self._fill_q())
        row.addWidget(self.q_act, 1)
        v.addLayout(row)
        self._buttons(v, [("Add Quote…", self.add_quote),
                          ("Use Selected", self.use_selected),
                          ("Use Lowest Everywhere", self.use_lowest),
                          ("Delete Quote", self.delete_quote)])
        self.quotes = Table(self.QCOLS, self._edit_quote)
        v.addWidget(self.quotes, 1)
        self.q_sheet = QLabel()
        self.q_sheet.setWordWrap(True)
        v.addWidget(self.q_sheet)

    def _q_activity(self):
        i = self.q_act.currentIndex()
        acts = self.job["activities"]
        return acts[i] if 0 <= i < len(acts) else None

    def _fill_quotes(self):
        keep = self.q_act.currentIndex()
        self.q_act.blockSignals(True)
        self.q_act.clear()
        for a in self.job["activities"]:
            n = len(a.get("quotes") or [])
            self.q_act.addItem(f"{a['name']}  ({n} quote{'s' * (n != 1)})")
        self.q_act.setCurrentIndex(min(max(keep, 0),
                                       self.q_act.count() - 1))
        self.q_act.blockSignals(False)
        self._fill_q()

    def _fill_q(self):
        a = self._q_activity()
        qs = (a or {}).get("quotes") or []
        rows = []
        for q in qs:
            amt = heavy.quote_amount(q, a.get("qty"))
            row = [_ed(q.get("vendor")), _ed(q.get("kind")),
                   _ed(q.get("price")), _ed(q.get("per")),
                   _ro(fmt(amt), True), _ro("✔" if q.get("use") else ""),
                   _ed(q.get("notes"))]
            rows.append(row)
        self.quotes.fill(rows)
        wide = [r for r in heavy.quote_sheet(self.job)
                if len(r["quotes"]) > 1 and r["spread"] > 0]
        self.q_sheet.setText("Biggest spreads: " + "; ".join(
            f"{r['activity']} ({r['kind']}) {fmt(r['spread'])}"
            for r in sorted(wide, key=lambda r: -r["spread"])[:5])
            if wide else "")

    QKEYS = ["vendor", "kind", "price", "per", None, None, "notes"]

    def _edit_quote(self, r, c, text):
        a = self._q_activity()
        q = a["quotes"][r]
        k = self.QKEYS[c]
        if k == "kind":
            q[k] = "sub" if text.strip().lower().startswith("s") \
                else "material"
        elif k == "per":
            q[k] = "LS" if text.strip().lower().startswith("l") else "unit"
        elif k == "price":
            if self._typo(text):
                return
            q[k] = str(D(text))
        elif k:
            q[k] = text.strip()
        self.save()
        self.refresh()

    def add_quote(self, vendor=None, price=None, kind="material",
                  per="unit"):
        a = self._q_activity()
        if a is None:
            return None
        if vendor is None:
            vendor, ok = QInputDialog.getText(self, "Add Quote", "Vendor")
            if not ok or not vendor.strip():
                return None
            kind, ok = QInputDialog.getItem(self, "Add Quote", "Quote for",
                                            ["material", "sub"], 0, False)
            if not ok:
                return None
            per, ok = QInputDialog.getItem(self, "Add Quote", "Priced",
                                           ["unit", "LS"], 0, False)
            if not ok:
                return None
            price, ok = QInputDialog.getDouble(self, "Add Quote",
                                               "Price $", 0, 0, 1e10, 2)
            if not ok:
                return None
        q = heavy.add_quote(a, vendor.strip(), price, kind, per)
        self.save()
        self.refresh()
        return q

    def use_selected(self):
        a = self._q_activity()
        r = self.quotes.currentRow()
        if a and 0 <= r < len(a.get("quotes") or []):
            heavy.use_quote(a, a["quotes"][r]["id"])
            self.save()
            self.refresh()

    def use_lowest(self):
        for a in self.job["activities"]:
            for kind in ("material", "sub"):
                heavy.pick_low(a, kind)
        self.save()
        self.refresh()

    def delete_quote(self):
        a = self._q_activity()
        r = self.quotes.currentRow()
        if a and 0 <= r < len(a.get("quotes") or []):
            a["quotes"].pop(r)
            self.save()
            self.refresh()

    # ============================================================ schedule
    SCOLS = ["Activity", "Follows", "Lag days", "Days (blank = crew days)",
             "Start day", "Finish day", "Bar"]

    def _build_schedule(self, w):
        v = QVBoxLayout(w)
        f = QHBoxLayout()
        f.addWidget(QLabel("Start date:"))
        self.start = QDateEdit()
        self.start.setCalendarPopup(True)
        self.start.setDisplayFormat("yyyy-MM-dd")
        self.start.dateChanged.connect(lambda _d: self._start_changed())
        f.addWidget(self.start)
        f.addWidget(QLabel("Days come from each activity's crew days. "
                           "Type which activity it follows (its name) to "
                           "chain them; work days are Monday to Friday."))
        f.addStretch()
        v.addLayout(f)
        self._buttons(v, [("Use Schedule Length for Indirects",
                           self.use_schedule_length),
                          ("Export Cash Flow…", self.export_cashflow)])
        self.sched = Table(self.SCOLS, self._edit_schedule)
        v.addWidget(self.sched, 1)
        self.sched_note = QLabel()
        v.addWidget(self.sched_note)

    def _fill_schedule(self):
        st = self.job["settings"]
        self.start.blockSignals(True)
        self.start.setDate(QDate.fromString(st.get("start") or
                                            QDate.currentDate().toString(
                                                "yyyy-MM-dd"), "yyyy-MM-dd"))
        self.start.blockSignals(False)
        s = heavy.schedule(self.job, self.lib)
        names = {a["id"]: a["name"] for a in self.job["activities"]}
        span = max(float(s["days"]), 1)
        rows = []
        for a, r in zip(self.job["activities"], s["rows"]):
            lead = int(round(float(r["start"]) / span * 40))
            bar = " " * lead + "█" * max(1, int(round(float(r["days"]) /
                                                      span * 40)))
            rows.append([_ro(a["name"]), _ed(names.get(a.get("after"), "")),
                         _ed(a.get("lag", "")),
                         _ed(a.get("days_override", "")),
                         _ro(r["start"], True), _ro(r["finish"], True),
                         _ro(bar)])
        self.sched.fill(rows)
        f = self.sched.font()
        f.setFamily("Consolas")
        # restyling a cell counts as a change: without the guard the edit
        # handler refreshes, which refills, which restyles... forever
        self.sched.blockSignals(True)
        try:
            for r in range(self.sched.rowCount()):
                it = self.sched.item(r, 6)
                if it:
                    it.setFont(f)
        finally:
            self.sched.blockSignals(False)
        note = f"{s['days']} work days ({s['weeks']} weeks)."
        if s["loops"]:
            note += " ⚠ Circular: " + ", ".join(s["loops"])
        self.sched_note.setText(note)

    def _edit_schedule(self, r, c, text):
        a = self.job["activities"][r]
        if c == 1:
            t = text.strip().lower()
            hit = next((x["id"] for x in self.job["activities"]
                        if x["name"].lower() == t and x is not a), None)
            if hit is None and t:
                hit = next((x["id"] for x in self.job["activities"]
                            if x["name"].lower().startswith(t) and
                            x is not a), None)
            a["after"] = hit or ""
        elif c == 2:
            a["lag"] = str(D(text)) if text.strip() else ""
        elif c == 3:
            a["days_override"] = str(D(text)) if text.strip() else ""
        self.save()
        self.refresh()

    def _start_changed(self):
        self.job["settings"]["start"] = self.start.date().toString(
            "yyyy-MM-dd")
        self.save()

    def use_schedule_length(self):
        s = heavy.schedule(self.job, self.lib)
        self.job["settings"]["duration_weeks"] = str(s["weeks"])
        self.save()
        self.refresh()
        return s["weeks"]

    def export_cashflow(self, path=None):
        if path is None:
            path, _ = QFileDialog.getSaveFileName(
                self, "Cash Flow", self._rname("Cash Flow", ".xlsx"),
                "Excel (*.xlsx);;CSV (*.csv)")
        if not path:
            return None
        import datetime as _dt
        start = _dt.date.fromisoformat(self.job["settings"].get("start") or
                                       _dt.date.today().isoformat())
        return heavy.export_cashflow(self.job, self.lib, path, start)

    # ============================================================ resources
    def _build_resources(self, w):
        v = QVBoxLayout(w)
        v.addWidget(QLabel("What the estimate needs: hours and cost by labor "
                           "class and by piece of equipment, and days by "
                           "crew."))
        self._buttons(v, [("Export Resources…", self.export_resources)])
        self.res_lab = Table(["Labor class", "Description", "Hours", "Cost"])
        self.res_eq = Table(["Equipment", "Description", "Own or rent",
                             "Hours", "Cost"])
        self.res_crew = Table(["Crew", "Crew days"])
        for t in (self.res_lab, self.res_eq, self.res_crew):
            t.setEditTriggers(QAbstractItemView.NoEditTriggers)
            v.addWidget(t, 1)

    def _fill_resources(self):
        r = heavy.resources(self.job, self.lib)
        self.res_lab.fill([[_ro(k), _ro(x["desc"]), _ro(x["hours"], True),
                            _ro(fmt(x["cost"]), True)]
                           for k, x in r["labor"].items()])
        self.res_eq.fill([[_ro(k), _ro(x["desc"]), _ro(x["use"]),
                           _ro(x["hours"], True), _ro(fmt(x["cost"]), True)]
                          for k, x in r["equipment"].items()])
        self.res_crew.fill([[_ro(k), _ro(d, True)]
                            for k, d in r["crew_days"].items()])
        return r

    def export_resources(self, path=None):
        if path is None:
            path, _ = QFileDialog.getSaveFileName(
                self, "Resources", self._rname("Resources", ".xlsx"),
                "Excel (*.xlsx);;CSV (*.csv)")
        if not path:
            return None
        return heavy.export_resources(self.job, self.lib, path)
