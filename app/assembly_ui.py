"""Assemblies panel and editor (PlanSwift-style estimating)."""
import copy

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton,
    QSplitter, QTableWidget, QTableWidgetItem, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget)

from . import assemblies, csi, labor

MEASURE_TOOL = {"length": "measure_polylength", "area": "measure_area",
                "volume": "measure_volume", "count": "count"}
MEASURE_LABEL = {"length": "Length (linear)", "area": "Area",
                 "volume": "Volume", "count": "Count"}
ADJUST_LABEL = {"height": "Working height", "conditions": "Conditions",
                "shift": "Shift", "season": "Season",
                "building": "Floors", "work": "Type of work",
                "site": "Site", "schedule": "Schedule",
                "quantity": "Quantities", "finish": "Finish standard",
                "rules": "Work rules"}


def adjust_combos(form, current, inherit=None):
    """Adjustment factor combos added to `form`; returns {group: combo}.
    `inherit` adds a first "(job setting)" choice."""
    out = {}
    for group, choices in labor.ADJUSTMENTS.items():
        cb = QComboBox()
        if inherit:
            cb.addItem(inherit, "")
        for name, f in choices.items():
            cb.addItem(f"{name}  (x{f:g})", name)
        i = cb.findData((current or {}).get(group, "" if inherit else
                                            next(iter(choices))))
        cb.setCurrentIndex(max(0, i))
        form.addRow(ADJUST_LABEL.get(group, group.title()) + ":", cb)
        out[group] = cb
    return out


def adjust_value(combos):
    return {g: cb.currentData() for g, cb in combos.items()
            if cb.currentData() and
            labor.ADJUSTMENTS[g].get(cb.currentData(), 1.0) != 1.0}


def _money(v):
    return f"${v:,.2f}"


def chest_item(a):
    """A Tool Chest-style tool that takes off with this assembly."""
    item = {"name": a["name"], "tool": MEASURE_TOOL.get(a.get("measure"),
                                                        "measure_polylength"),
            "subject": a["name"], "color": a.get("color") or [0.85, 0.1, 0.1],
            "width": 3}
    if a.get("measure") == "area":
        item.update(fill=item["color"], opacity=0.35, width=1)
    return item


# ---- panel --------------------------------------------------------------------------

class AssembliesPanel(QWidget):
    """The estimate by assembly: each assembly with its parts, material,
    labor and totals, worked out live from the takeoff."""

    changed = Signal()                 # job data in the PDF changed
    take_off = Signal(dict)            # start measuring with an assembly

    COLS = ["Item", "CSI / Code", "Quantity", "Unit", "Unit Cost",
            "Material", "Labor Hrs", "Crew", "Crew Days", "Labor", "Total"]

    def __init__(self):
        super().__init__()
        self.doc = None
        self.current_page = 0
        self.rows = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        top = QHBoxLayout()
        lib = QPushButton("Assembly Library…")
        lib.setToolTip("Pick an assembly to take off with, or create and "
                       "edit assemblies")
        lib.clicked.connect(self.open_library)
        self.edit_btn = QPushButton("Edit Assembly…")
        self.edit_btn.clicked.connect(self.edit_selected)
        self.measure_btn = QPushButton("Take Off")
        self.measure_btn.setToolTip("Measure more with the selected assembly")
        self.measure_btn.clicked.connect(self._take_off_selected)
        top.addWidget(lib)
        top.addWidget(self.edit_btn)
        top.addWidget(self.measure_btn)
        top.addStretch()
        top.addWidget(QLabel("Labor rate $/hr:"))
        self.rate = QDoubleSpinBox()
        self.rate.setRange(0, 1000)
        self.rate.setDecimals(2)
        self.rate.editingFinished.connect(self._rate_changed)
        top.addWidget(self.rate)
        self.page_only = QCheckBox("This page only")
        self.page_only.toggled.connect(lambda _: self.refresh())
        top.addWidget(self.page_only)
        lay.addLayout(top)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(self.COLS)
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.itemDoubleClicked.connect(lambda *_: self.edit_selected())
        lay.addWidget(self.tree)
        bottom = QHBoxLayout()
        self.total = QLabel("")
        bottom.addWidget(self.total)
        bottom.addStretch()
        export = QPushButton("Export to Excel…")
        export.clicked.connect(self._export_dialog)
        bottom.addWidget(export)
        lay.addLayout(bottom)
        self.problems = QLabel("")
        self.problems.setStyleSheet("color: #b00;")
        self.problems.setWordWrap(True)
        lay.addWidget(self.problems)

    def set_doc(self, doc):
        self.doc = doc
        self.refresh()

    def refresh(self):
        self.tree.clear()
        if self.doc is None or self.doc.is_closed:
            self.total.setText("")
            return
        job = assemblies.read_job(self.doc)
        self.rate.blockSignals(True)
        self.rate.setValue(float(job.get("labor_rate") or 0))
        self.rate.blockSignals(False)
        page = self.current_page if self.page_only.isChecked() else None
        self.rows, totals, errors = assemblies.rollup(self.doc, page)
        bold = QFont()
        bold.setBold(True)
        trade = None
        for r in self.rows:
            if r["trade"] != trade:
                trade = r["trade"]
                t = QTreeWidgetItem([trade or "Other"])
                t.setFont(0, bold)
                t.setForeground(0, QColor(80, 80, 80))
                t.setFlags(Qt.ItemIsEnabled)
                self.tree.addTopLevelItem(t)
            it = QTreeWidgetItem([
                r["name"], r.get("csi", ""), f"{r['quantity']:,.2f}",
                r["unit"], "", _money(r["material"]),
                f"{r['labor_hours']:,.1f}", "", f"{r['crew_days']:,.1f}",
                _money(r["labor_cost"]), _money(r["total"])])
            it.setData(0, Qt.UserRole, r["name"])
            tip = f"{r['items']} measurement(s)"
            if r.get("csi"):
                tip += f"\nCSI {r['csi']} {csi.division_title(r['csi'])}"
            if abs(r.get("adjust", 1.0) - 1.0) > 1e-9:
                tip += f"\nLabor hours x{r['adjust']:.3g} (adjustments)"
            it.setToolTip(0, tip)
            for c in range(len(self.COLS)):
                it.setFont(c, bold)
            t.addChild(it)
            for q in r["parts"]:
                ch = QTreeWidgetItem([
                    q["name"], q.get("code", ""), f"{q['qty']:,.2f}",
                    q["unit"], _money(q["cost"]), _money(q["material"]),
                    f"{q['labor_hours']:,.1f}", q.get("crew", ""),
                    f"{q['crew_days']:,.1f}", _money(q["labor_cost"]),
                    _money(q["total"])])
                if q.get("crew"):
                    ch.setToolTip(7, f"{q['crew']} at "
                                     f"{_money(q['labor_rate'])}/crew-hr")
                ch.setData(0, Qt.UserRole, r["name"])
                it.addChild(ch)
            it.setExpanded(True)
            t.setExpanded(True)
        for i in range(1, len(self.COLS)):
            self.tree.resizeColumnToContents(i)
        if self.rows:
            self.total.setText(
                f"<b>Material {_money(totals['material'])} + Labor "
                f"{_money(totals['labor_cost'])} "
                f"({totals['labor_hours']:,.1f} hrs) = "
                f"Total {_money(totals['total'])}</b>" +
                (f" &nbsp; priced from "
                 f"{assemblies._costbook_shown(totals['costbook'])}"
                 f" ({totals.get('region') or 'national'})"
                 if totals.get("costbook") else ""))
        else:
            self.total.setText("No assembly takeoff yet. Open the Assembly "
                               "Library, pick an assembly and measure.")
        self.problems.setText("Problems: " + "; ".join(errors[:5])
                              if errors else "")

    def selected_name(self):
        it = self.tree.currentItem()
        return it.data(0, Qt.UserRole) if it else None

    def _rate_changed(self):
        if self.doc is None:
            return
        assemblies.set_labor_rate(self.doc, self.rate.value())
        self.changed.emit()
        self.refresh()

    def _take_off_selected(self):
        name = self.selected_name()
        if not name or self.doc is None:
            QMessageBox.information(self, "Assemblies",
                                    "Select an assembly in the list first.")
            return
        a = assemblies.find(self.doc, name)
        if a:
            self.take_off.emit(a)

    def edit_selected(self):
        name = self.selected_name()
        if not name or self.doc is None:
            return
        a = assemblies.find(self.doc, name)
        if a is None:
            return
        dlg = AssemblyEditor(a, self, title=f"Edit Assembly - {name}")
        if dlg.exec() == QDialog.Accepted:
            new = dlg.assembly()
            assemblies.set_job_assembly(self.doc, new)
            if dlg.to_library.isChecked():
                assemblies.save_to_library(new)
            self.changed.emit()
            self.refresh()

    def open_library(self):
        dlg = LibraryDialog(self.doc, self)
        if dlg.exec() == QDialog.Accepted and dlg.chosen:
            self.use(dlg.chosen)
        elif dlg.edited:
            self.changed.emit()
            self.refresh()

    def use(self, a):
        """Copy an assembly into the job (if new) and start measuring."""
        if self.doc is not None:
            job = assemblies.read_job(self.doc)
            if a["name"] not in job["assemblies"]:
                assemblies.set_job_assembly(self.doc, a)
                self.changed.emit()
        self.take_off.emit(a)

    def _export_dialog(self):
        if self.doc is None:
            return
        import os
        from .reportname import report_file_name
        proj = os.path.splitext(os.path.basename(
            getattr(self.doc, "name", "") or ""))[0]
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Estimate",
            report_file_name("Estimate", proj, ext=".xlsx"),
            "Excel (*.xlsx)")
        if path:
            page = self.current_page if self.page_only.isChecked() else None
            assemblies.export_xlsx(self.doc, path, page)


# ---- library -------------------------------------------------------------------------

class LibraryDialog(QDialog):
    """Pick an assembly to take off with; create, copy or edit them."""

    def __init__(self, doc, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Assembly Library")
        self.resize(1040, 620)
        self.doc = doc
        self.chosen = None
        self.edited = False
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Pick an assembly and click <b>Take Off</b>, "
                             "then measure on the drawing. Quantities, "
                             "parts and costs fill in as you go."))
        split = QSplitter()
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search assemblies (name, CSI, ID)")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda *_: self._fill())
        ll.addWidget(self.search)
        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._show)
        self.list.itemDoubleClicked.connect(lambda *_: self._take())
        ll.addWidget(self.list)
        self.count = QLabel("")
        ll.addWidget(self.count)
        split.addWidget(left)
        self.detail = QTableWidget(0, 5)
        self.detail.setHorizontalHeaderLabels(
            ["Part", "Unit", "Quantity formula", "Unit cost", "Labor hrs/unit"])
        hh = self.detail.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.Stretch)
        hh.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.detail.setWordWrap(False)
        self.detail.setEditTriggers(QAbstractItemView.NoEditTriggers)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        self.info = QLabel("")
        self.info.setWordWrap(True)
        rl.addWidget(self.info)
        rl.addWidget(self.detail)
        split.addWidget(right)
        split.setSizes([340, 700])
        split.setStretchFactor(1, 1)
        lay.addWidget(split, 1)              # the lists get the spare room
        row = QHBoxLayout()
        for text, slot in (("New…", self._new), ("Copy…", self._copy),
                           ("Edit…", self._edit),
                           ("Import CSV…", self._import_csv),
                           ("Export CSV…", self._export_csv),
                           ("Cost Book Template…", self._template)):
            b = QPushButton(text)
            b.clicked.connect(lambda _c=False, _f=slot: _f())
            row.addWidget(b)
        row.addStretch()
        take = QPushButton("Take Off")
        take.setDefault(True)
        take.clicked.connect(self._take)
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        row.addWidget(take)
        row.addWidget(close)
        lay.addLayout(row)
        self._fill()

    def _all(self):
        items = assemblies.library()
        if self.doc is not None:
            items.update(assemblies.read_job(self.doc)["assemblies"])
        return items

    def _fill(self, select=None):
        self.items = self._all()
        self.list.clear()
        trade = None
        bold = QFont()
        bold.setBold(True)
        words = self.search.text().lower().split() \
            if hasattr(self, "search") else []
        shown = 0
        for name in sorted(self.items, key=lambda n: (
                self.items[n].get("csi", "") or "99",
                self.items[n].get("trade", ""), n)):
            a = self.items[name]
            hay = " ".join(str(a.get(k, "")) for k in
                           ("name", "trade", "csi", "id", "area")).lower()
            if words and not all(w in hay for w in words):
                continue
            shown += 1
            if a.get("trade", "") != trade:
                trade = a.get("trade", "")
                h = QListWidgetItem(trade or "Other")
                h.setFlags(Qt.NoItemFlags)
                h.setFont(bold)
                self.list.addItem(h)
            it = QListWidgetItem("   " + name)
            it.setData(Qt.UserRole, name)
            self.list.addItem(it)
            if name == select:
                self.list.setCurrentItem(it)
        if hasattr(self, "count"):
            self.count.setText(f"{shown} of {len(self.items)} assemblies")

    def _current(self):
        it = self.list.currentItem()
        name = it.data(Qt.UserRole) if it else None
        return self.items.get(name) if name else None

    def _show(self, *_):
        a = self._current()
        self.detail.setRowCount(0)
        if not a:
            self.info.setText("")
            return
        props = ", ".join(f"{k} = {v:g}" if isinstance(v, (int, float))
                          else f"{k} = {v}"
                          for k, v in (a.get("props") or {}).items())
        extra = ""
        if a.get("id") or a.get("csi"):
            extra += (f"<br>{a.get('id', '')}  CSI {a.get('csi', '')}"
                      f"{'  per ' + a['unit'] if a.get('unit') else ''}")
        if a.get("inputs"):
            extra += ("<br><span style='color:#b00'>Enter before use: " +
                      ", ".join(f"{k} = {d}" for k, d in a["inputs"].items())
                      + "</span>")
        if a.get("notes"):
            extra += f"<br><i>{a['notes']}</i>"
        self.info.setText(f"<b>{a['name']}</b><br>Measure: "
                          f"{MEASURE_LABEL.get(a.get('measure'), '?')}"
                          f"<br>Properties: {props or 'none'}{extra}")
        for p in a.get("parts") or []:
            r = self.detail.rowCount()
            self.detail.insertRow(r)
            for c, v in enumerate((p.get("name", ""), p.get("unit", ""),
                                   str(p.get("qty", "")),
                                   f"{float(p.get('cost') or 0):,.2f}",
                                   f"{float(p.get('labor') or 0):g}")):
                cell = QTableWidgetItem(v)
                cell.setToolTip(v)
                self.detail.setItem(r, c, cell)

    def _import_csv(self, path=None):
        from . import assembly_csv
        if path is None:
            path, _ = QFileDialog.getOpenFileName(
                self, "Import Assemblies", "", "Assemblies (*.csv)")
            if not path:
                return None
        try:
            n, problems = assembly_csv.import_to_library(path)
        except (OSError, ValueError, KeyError) as e:
            QMessageBox.warning(self, "Import Assemblies", str(e))
            return None
        self.edited = True
        self._fill()
        msg = f"Added {n} assemblies to your library."
        if problems:
            msg += (f"\n\n{len(problems)} formula problem(s):\n" +
                    "\n".join(problems[:10]))
        QMessageBox.information(self, "Import Assemblies", msg)
        return n

    def _shown(self):
        names = [self.list.item(i).data(Qt.UserRole)
                 for i in range(self.list.count())]
        return [self.items[n] for n in names if n in self.items]

    def _export_csv(self, path=None):
        from . import assembly_csv
        if path is None:
            path, _ = QFileDialog.getSaveFileName(
                self, "Export Assemblies", "Assemblies.csv", "CSV (*.csv)")
            if not path:
                return None
        return assembly_csv.write(self._shown(), path)

    def _template(self, path=None):
        """A cost book to fill in for the assemblies shown."""
        from . import assembly_csv
        if path is None:
            path, _ = QFileDialog.getSaveFileName(
                self, "Cost Book Template", "Cost Book Template.csv",
                "CSV (*.csv)")
            if not path:
                return None
        assembly_csv.cost_book_template(self._shown(), path)
        QMessageBox.information(
            self, "Cost Book Template", "Fill in the Material and Labor "
            "columns, then use Takeoff > Cost Books > Import CSV and pick "
            "it for the job. Parts are matched by their Code.")
        return path

    def _take(self):
        a = self._current()
        if a:
            self.chosen = copy.deepcopy(a)
            self.accept()

    def _save(self, a, dlg):
        if self.doc is not None and dlg.to_job.isChecked():
            assemblies.set_job_assembly(self.doc, a)
        if dlg.to_library.isChecked():
            assemblies.save_to_library(a)
        self.edited = True
        self._fill(select=a["name"])

    def _new(self):
        dlg = AssemblyEditor({"name": "New Assembly", "measure": "length",
                              "trade": "", "props": {"Height": 9},
                              "parts": [{"name": "Material", "unit": "lf",
                                         "qty": "Length", "cost": 0,
                                         "labor": 0}]}, self,
                             title="New Assembly", library_default=True)
        if dlg.exec() == QDialog.Accepted:
            self._save(dlg.assembly(), dlg)

    def _copy(self):
        a = self._current()
        if not a:
            return
        b = copy.deepcopy(a)
        b["name"] = a["name"] + " (copy)"
        dlg = AssemblyEditor(b, self, title="Copy Assembly",
                             library_default=True)
        if dlg.exec() == QDialog.Accepted:
            self._save(dlg.assembly(), dlg)

    def _edit(self):
        a = self._current()
        if not a:
            return
        dlg = AssemblyEditor(a, self, title=f"Edit Assembly - {a['name']}")
        if dlg.exec() == QDialog.Accepted:
            self._save(dlg.assembly(), dlg)


# ---- editor ---------------------------------------------------------------------------

class AssemblyEditor(QDialog):
    """Edit an assembly's properties and parts, with a live preview."""

    def __init__(self, assembly, parent=None, title="Assembly",
                 library_default=False):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(900, 640)
        a = copy.deepcopy(assembly)
        self.extra = {k: v for k, v in a.items()
                      if k not in ("name", "trade", "measure", "props",
                                   "parts", "csi", "adjust")}
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.name = QLineEdit(a.get("name", ""))
        form.addRow("Name:", self.name)
        self.trade = QLineEdit(a.get("trade", ""))
        form.addRow("Trade:", self.trade)
        self.measure = QComboBox()
        for k, label in MEASURE_LABEL.items():
            self.measure.addItem(label, k)
        i = self.measure.findData(a.get("measure", "length"))
        self.measure.setCurrentIndex(max(0, i))
        form.addRow("Measure by:", self.measure)
        crow = QHBoxLayout()
        self.csi = QLineEdit(a.get("csi", ""))
        self.csi.setPlaceholderText("e.g. 09 21 16")
        self.csi_title = QLabel("")
        self.csi.textChanged.connect(self._csi_changed)
        sug = QPushButton("Suggest")
        sug.setToolTip("Suggest a MasterFormat code from the name and trade")
        sug.clicked.connect(self._suggest_csi)
        crow.addWidget(self.csi)
        crow.addWidget(sug)
        crow.addWidget(self.csi_title, 1)
        form.addRow("CSI code:", crow)
        top = QHBoxLayout()
        top.addLayout(form, 3)
        adj = QFormLayout()
        adj.addRow(QLabel("<b>Labor adjustments</b>"))
        self.adjust = adjust_combos(adj, a.get("adjust"), "(job setting)")
        top.addLayout(adj, 2)
        lay.addLayout(top)
        self._csi_changed()

        lay.addWidget(QLabel("<b>Properties</b> (numbers formulas can use, "
                             "e.g. Height, Spacing, Waste %)"))
        self.props = QTableWidget(0, 2)
        self.props.setHorizontalHeaderLabels(["Property", "Value"])
        self.props.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch)
        self.props.setMaximumHeight(130)
        for k, v in (a.get("props") or {}).items():
            self._add_row(self.props, [k, f"{v:g}" if isinstance(
                v, (int, float)) else str(v)])
        lay.addWidget(self.props)
        lay.addLayout(self._buttons(self.props, ["", "0"]))

        lay.addWidget(QLabel(
            "<b>Parts</b> - quantity formulas can use Length, Area, "
            "Perimeter, Count, Segments, the properties, and parts above "
            "(spaces as _). Functions: ceil, floor, round, roundup(x, step), "
            "min, max."))
        self.parts = QTableWidget(0, 7)
        self.parts.setHorizontalHeaderLabels(
            ["Part", "Unit", "Quantity formula", "Unit cost $",
             "Labor hrs / unit", "Cost code", "Crew"])
        self.parts.horizontalHeaderItem(5).setToolTip(
            "Code in the job's cost book (e.g. 09 21 16.13); when the book "
            "has it, its price and labor are used instead")
        self.parts.horizontalHeaderItem(6).setToolTip(
            "Crew code (e.g. D-2); labor is costed at the crew's blended "
            "rate. Crews: " + ", ".join(labor.crews()))
        self.parts.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.Stretch)
        for p in a.get("parts") or []:
            self._add_row(self.parts, [
                p.get("name", ""), p.get("unit", ""), str(p.get("qty", "")),
                f"{float(p.get('cost') or 0):g}",
                f"{float(p.get('labor') or 0):g}", p.get("code", ""),
                p.get("crew", "")])
        lay.addWidget(self.parts)
        lay.addLayout(self._buttons(self.parts, ["New Part", "ea", "Count",
                                                 "0", "0", "", ""]))

        prev = QHBoxLayout()
        prev.addWidget(QLabel("<b>Try it:</b>"))
        self.sample = {}
        for key, default in (("Length", 40), ("Area", 1000),
                             ("Perimeter", 130), ("Volume", 400),
                             ("Count", 1), ("Segments", 1)):
            sp = QDoubleSpinBox()
            sp.setRange(0, 1e7)
            sp.setDecimals(2)
            sp.setValue(default)
            sp.valueChanged.connect(self._preview)
            prev.addWidget(QLabel(key))
            prev.addWidget(sp)
            self.sample[key.lower()] = sp
        prev.addStretch()
        lay.addLayout(prev)
        self.result = QLabel("")
        self.result.setWordWrap(True)
        self.result.setTextFormat(Qt.RichText)
        lay.addWidget(self.result)

        save_row = QHBoxLayout()
        self.to_job = QCheckBox("Use in this job")
        self.to_job.setChecked(True)
        self.to_library = QCheckBox("Save to my library (all jobs)")
        self.to_library.setChecked(library_default)
        save_row.addWidget(self.to_job)
        save_row.addWidget(self.to_library)
        save_row.addStretch()
        lay.addLayout(save_row)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        for t in (self.props, self.parts):
            t.itemChanged.connect(lambda *_: self._preview())
        self.measure.currentIndexChanged.connect(lambda *_: self._preview())
        self._preview()

    @staticmethod
    def _add_row(table, values):
        r = table.rowCount()
        table.insertRow(r)
        for c, v in enumerate(values):
            table.setItem(r, c, QTableWidgetItem(str(v)))

    def _buttons(self, table, blank):
        row = QHBoxLayout()
        add = QPushButton("Add")
        add.clicked.connect(lambda: self._add_row(table, blank))
        rem = QPushButton("Remove")
        rem.clicked.connect(lambda: table.removeRow(table.currentRow())
                            if table.currentRow() >= 0 else None)
        up = QPushButton("Move Up")
        up.clicked.connect(lambda: self._move(table, -1))
        down = QPushButton("Move Down")
        down.clicked.connect(lambda: self._move(table, 1))
        for b in (add, rem, up, down):
            row.addWidget(b)
        row.addStretch()
        return row

    def _move(self, table, d):
        r = table.currentRow()
        if r < 0 or not 0 <= r + d < table.rowCount():
            return
        vals = [[(table.item(i, c).text() if table.item(i, c) else "")
                 for c in range(table.columnCount())] for i in (r, r + d)]
        table.blockSignals(True)
        for i, row in zip((r + d, r), vals):
            for c, v in enumerate(row):
                table.setItem(i, c, QTableWidgetItem(v))
        table.blockSignals(False)
        table.setCurrentCell(r + d, 0)
        self._preview()

    @staticmethod
    def _cell(table, r, c):
        it = table.item(r, c)
        return it.text().strip() if it else ""

    def assembly(self):
        props = {}
        for r in range(self.props.rowCount()):
            k = self._cell(self.props, r, 0)
            if not k:
                continue
            v = self._cell(self.props, r, 1)
            try:
                props[k] = float(v)
            except ValueError:
                props[k] = v
        parts = []
        for r in range(self.parts.rowCount()):
            name = self._cell(self.parts, r, 0)
            if not name:
                continue

            def num(c):
                try:
                    return float(self._cell(self.parts, r, c) or 0)
                except ValueError:
                    return 0.0
            part = {"name": name, "unit": self._cell(self.parts, r, 1),
                    "qty": self._cell(self.parts, r, 2) or "0",
                    "cost": num(3), "labor": num(4)}
            code = self._cell(self.parts, r, 5)
            if code:
                part["code"] = csi.parse_code(code) or code
            crew = self._cell(self.parts, r, 6)
            if crew:
                part["crew"] = crew.upper() if crew.upper() in labor.crews() \
                    else crew
            parts.append(part)
        out = {**self.extra, "name": self.name.text().strip(),
               "trade": self.trade.text().strip(),
               "measure": self.measure.currentData(), "props": props,
               "parts": parts}
        code = csi.parse_code(self.csi.text())
        if code:
            out["csi"] = code
        adjust = adjust_value(self.adjust)
        if adjust:
            out["adjust"] = adjust
        return out

    def _csi_changed(self, *_):
        code = csi.parse_code(self.csi.text())
        t = self.csi.text().strip()
        if not t:
            self.csi_title.setText("")
        elif code:
            self.csi_title.setText(csi.division_title(code))
        else:
            self.csi_title.setText("<span style='color:#b00'>not a "
                                   "MasterFormat code</span>")

    def _suggest_csi(self):
        code = csi.classify(self.name.text() + " " + self.trade.text())
        if code:
            self.csi.setText(code)
        else:
            self.csi_title.setText("No suggestion - type the code")

    def _preview(self):
        a = self.assembly()
        meas = {k: sp.value() for k, sp in self.sample.items()}
        m = a["measure"]
        for k in ("length", "area", "perimeter", "count", "segments",
                  "volume"):
            if (m == "length" and k in ("area", "perimeter", "count",
                                        "volume")) or \
                    (m == "area" and k in ("length", "count", "segments",
                                           "volume")) or \
                    (m == "volume" and k in ("length", "count",
                                             "segments")) or \
                    (m == "count" and k != "count"):
                meas[k] = 0.0
        try:
            parts = assemblies.compute(a, meas)
        except assemblies.FormulaError as e:
            self.result.setText(f"<span style='color:#b00'>Problem: "
                                f"{e}</span>")
            return False
        mat = sum(p["material"] for p in parts)
        hrs = sum(p["labor_hours"] for p in parts)
        self.result.setText(
            "For this sample: " + ", ".join(
                f"{p['name']} <b>{p['qty']:,.2f}</b> {p['unit']}"
                for p in parts) +
            f"<br>Material <b>{_money(mat)}</b>, labor <b>{hrs:,.1f} hrs</b>")
        return True

    def accept(self):
        if not self.name.text().strip():
            QMessageBox.warning(self, "Assembly", "Give the assembly a name.")
            return
        if not self._preview():
            QMessageBox.warning(self, "Assembly",
                                "Fix the formula problem shown first.")
            return
        if self.csi.text().strip() and not csi.parse_code(self.csi.text()):
            QMessageBox.warning(self, "Assembly",
                                "The CSI code isn't a MasterFormat code "
                                "(e.g. 09 21 16). Fix it or clear it.")
            return
        super().accept()
