"""Menus and dialogs for Chief's cost layer (v28 assembly_codes, v29
cost_rollup, v30 change_report).

Civil > HeavyBid-Coded Assemblies:
    Assembly Library (HeavyBid codes)...  load a CSV/XLSX library, export
                                          the blank template or the example
    Bind Takeoff Group to Assembly...     the user picks group + assembly
    Insert Assembly Line...               code + typed quantity
    Bid Summary (Coded Assemblies)...     by trade, tax, markup cascade
    Revision Change Report...             compare with an earlier PDF

The library path is a setting; bindings, inserted lines, cascade, tax % and
building SF are saved in the PDF with the other job data.
"""
import os
import shutil

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QDialog,
                               QDialogButtonBox, QDoubleSpinBox, QFileDialog,
                               QFormLayout, QHBoxLayout, QInputDialog,
                               QLabel, QLineEdit, QMessageBox,
                               QPlainTextEdit, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout)

from . import assembly_codes as ac, cost_rollup, settings
from .reportname import report_file_name

KEY = "assembly_codes_library"


def library_path():
    p = settings.get(KEY) or ""
    return p if p and os.path.exists(p) else ""


def load_library(parent=None, quiet=False):
    """{code: assembly} from the saved library, or {} (with a message)."""
    p = library_path()
    if not p:
        if not quiet:
            QMessageBox.information(
                parent, "Assembly Library",
                "No assembly library loaded yet. Use Civil > CivilBid-Coded "
                "Assemblies > Assembly Library to load your CSV or Excel "
                "file (or export the template to start one).")
        return {}
    try:
        return ac.read(p)
    except Exception as ex:
        if not quiet:
            QMessageBox.warning(parent, "Assembly Library",
                                f"Could not read {os.path.basename(p)}:\n{ex}")
        return {}


# ------------------------------------------------------------- library
class LibraryDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Assembly Library (CivilBid codes)")
        self.resize(820, 460)
        lay = QVBoxLayout(self)
        self.path = QLabel()
        self.path.setWordWrap(True)
        lay.addWidget(self.path)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Code", "Description", "Unit", "Trade", "Components",
             "Unpriced"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        lay.addWidget(self.table)
        row = QHBoxLayout()
        for text, fn in (("Load Library…", self.load),
                         ("Export Blank Template…",
                          lambda: self.export(ac.TEMPLATE, "template")),
                         ("Export Example…",
                          lambda: self.export(ac.EXAMPLE, "example"))):
            b = QPushButton(text)
            b.clicked.connect(lambda _c=False, f=fn: f())
            row.addWidget(b)
        row.addStretch(1)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        row.addWidget(close)
        lay.addLayout(row)
        self.refresh()

    def refresh(self):
        p = library_path()
        self.path.setText(f"Library: {p}" if p else
                          "No library loaded. Load your CSV/Excel file, or "
                          "export the template and fill in your own codes "
                          "and rates. No prices ship with QuantiSheet.")
        lib = load_library(self, quiet=True) if p else {}
        self.lib = lib
        self.table.setRowCount(len(lib))
        for r, a in enumerate(lib.values()):
            unpriced = sum(1 for c in a["components"] if c["rate"] is None)
            for c, v in enumerate((a["code"], a["desc"], a["unit"],
                                   a["trade"], len(a["components"]),
                                   unpriced or "")):
                self.table.setItem(r, c, QTableWidgetItem(str(v)))
        self.table.resizeColumnsToContents()

    def load(self, path=None):
        if path is None:
            path, _ = QFileDialog.getOpenFileName(
                self, "Load Assembly Library", "",
                "Library (*.csv *.xlsx)")
            if not path:
                return None
        try:
            lib = ac.read(path)
        except Exception as ex:
            QMessageBox.warning(self, "Assembly Library", str(ex))
            return None
        settings.set(KEY, path)
        self.refresh()
        return lib

    def export(self, src, what, path=None):
        if path is None:
            path, _ = QFileDialog.getSaveFileName(
                self, f"Export {what}", f"assembly_codes_{what}.csv",
                "CSV (*.csv)")
            if not path:
                return None
        shutil.copyfile(src, path)
        return path


# ------------------------------------------------------------- binding
def _groups(doc):
    return sorted(ac.group_quantities(doc).items(),
                  key=lambda kv: kv[0][0].lower())


def bind_dialog(mw, group=None, code=None, waste=None):
    v = mw._view
    if v is None:
        return None
    lib = load_library(mw)
    if not lib:
        return None
    gs = _groups(v.doc)
    if not gs:
        QMessageBox.information(mw, "Bind to Assembly",
                                "This PDF has no takeoff yet.")
        return None
    binds = ac.read_job(v.doc)["bindings"]
    names = []
    for (g, t, u), q in gs:
        b = binds.get(ac.key_of(g, t, u))
        names.append(f"{g} ({t}, {q:.2f} {u})"
                     + (f"  → {b['code']}" if b else ""))
    if group is None:
        pick, ok = QInputDialog.getItem(mw, "Bind to Assembly",
                                        "Takeoff group:", names, 0, False)
        if not ok:
            return None
        key = gs[names.index(pick)][0]
    else:
        key = next(k for k, _ in gs if k[0] == group)
    codes = [f"{a['code']}  {a['desc']} ({a['unit']})" for a in lib.values()]
    if code is None:
        pick, ok = QInputDialog.getItem(mw, "Bind to Assembly",
                                        f"Assembly for {key[0]}:", codes, 0,
                                        False)
        if not ok:
            return None
        code = list(lib)[codes.index(pick)]
    if waste is None:
        waste, ok = QInputDialog.getDouble(
            mw, "Bind to Assembly", "Waste % (material only):", 0, 0, 100, 1)
        if not ok:
            return None
    ac.bind(v.doc, *key, code, waste, library=lib)
    v.mark_dirty()
    mw._flash(f"{key[0]} bound to assembly {code}")
    return key, code


def insert_dialog(mw, code=None, qty=None, note=""):
    v = mw._view
    if v is None:
        return None
    lib = load_library(mw)
    if not lib:
        return None
    if code is None:
        codes = [f"{a['code']}  {a['desc']} ({a['unit']})"
                 for a in lib.values()]
        pick, ok = QInputDialog.getItem(mw, "Insert Assembly Line",
                                        "Assembly:", codes, 0, False)
        if not ok:
            return None
        code = list(lib)[codes.index(pick)]
    if qty is None:
        qty, ok = QInputDialog.getDouble(
            mw, "Insert Assembly Line",
            f"Quantity ({lib[code]['unit']}):", 1, 0, 1e9, 2)
        if not ok or qty <= 0:
            return None
        note, _ = QInputDialog.getText(mw, "Insert Assembly Line",
                                       "Note (optional):")
    ac.insert(v.doc, code, qty, note)
    v.mark_dirty()
    mw._flash(f"Inserted {qty} × {code}")
    return code, qty


# ------------------------------------------------------------- summary
def _job_inputs(doc):
    d = ac.read_job(doc)
    casc = d.get("cascade") or cost_rollup.DEFAULT_CASCADE
    return [tuple(x) for x in casc], d.get("tax_pct", "0"), \
        d.get("building_sf", "")


class SummaryDialog(QDialog):
    def __init__(self, mw, lib):
        super().__init__(mw)
        self.mw, self.lib, self.doc = mw, lib, mw._view.doc
        self.setWindowTitle("Bid Summary (Coded Assemblies)")
        self.resize(760, 640)
        casc, tax, sf = _job_inputs(self.doc)
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.tax = QDoubleSpinBox()
        self.tax.setRange(0, 100)
        self.tax.setDecimals(3)
        self.tax.setValue(float(tax or 0))
        self.sf = QLineEdit(str(sf or ""))
        self.sf.setPlaceholderText("enter building SF for cost per SF")
        form.addRow("Sales tax on material %:", self.tax)
        form.addRow("Building SF:", self.sf)
        lay.addLayout(form)
        lay.addWidget(QLabel("Markups (applied top to bottom, each on the "
                             "running subtotal):"))
        self.casc = QTableWidget(len(casc), 2)
        self.casc.setHorizontalHeaderLabels(["Markup", "%"])
        self.casc.horizontalHeader().setStretchLastSection(True)
        for r, (k, p) in enumerate(casc):
            it = QTableWidgetItem(cost_rollup.LABELS.get(k, k.title()))
            it.setData(Qt.UserRole, k)
            it.setFlags(it.flags() & ~Qt.ItemIsEditable)
            self.casc.setItem(r, 0, it)
            self.casc.setItem(r, 1, QTableWidgetItem(str(p)))
        self.casc.setMaximumHeight(240)
        lay.addWidget(self.casc)
        mv = QHBoxLayout()
        for text, d in (("Move Up", -1), ("Move Down", 1)):
            b = QPushButton(text)
            b.clicked.connect(lambda _c=False, d=d: self.move(d))
            mv.addWidget(b)
        calc = QPushButton("Recalculate")
        calc.clicked.connect(self.recalc)
        mv.addWidget(calc)
        mv.addStretch(1)
        lay.addLayout(mv)
        self.out = QPlainTextEdit()
        self.out.setReadOnly(True)
        lay.addWidget(self.out)
        bb = QDialogButtonBox()
        self.export_btn = bb.addButton("Export…", QDialogButtonBox.ActionRole)
        self.export_btn.clicked.connect(lambda: self.export())
        save = bb.addButton("Save to Job", QDialogButtonBox.AcceptRole)
        save.clicked.connect(self.save)
        bb.addButton(QDialogButtonBox.Close).clicked.connect(self.reject)
        lay.addWidget(bb)
        self.recalc()

    def move(self, d):
        r = self.casc.currentRow()
        n = r + d
        if r < 0 or not 0 <= n < self.casc.rowCount():
            return
        for c in range(2):
            a, b = self.casc.takeItem(r, c), self.casc.takeItem(n, c)
            self.casc.setItem(r, c, b)
            self.casc.setItem(n, c, a)
        self.casc.setCurrentCell(n, 1)
        self.recalc()

    def cascade(self):
        out = []
        for r in range(self.casc.rowCount()):
            k = self.casc.item(r, 0).data(Qt.UserRole)
            p = (self.casc.item(r, 1).text() or "0").replace("%", "").strip()
            out.append((k, p))
        return out

    def recalc(self):
        try:
            lines, unbound = ac.priced_lines(self.doc, self.lib)
            self.result = cost_rollup.summary(
                lines, self.cascade(), self.tax.value(),
                self.sf.text().replace(",", "").strip() or None)
        except Exception as ex:
            self.result = None
            self.out.setPlainText(f"Could not calculate: {ex}")
            return None
        rows = cost_rollup.table(self.result)
        txt = []
        for row in rows[1:]:
            amt = row[5]
            amt = f"{amt:,.2f}" if hasattr(amt, "quantize") else str(amt)
            txt.append(f"{row[1]:<44} {amt:>16}")
        unpriced = sorted({u for ln in lines for u in ln["unpriced"]})
        if unbound:
            txt.append("")
            txt.append(f"NOT PRICED - {len(unbound)} takeoff group(s) with "
                       "no assembly bound:")
            txt += [f"  {u['group']} ({u['type']}, {u['qty']:.2f} "
                    f"{u['unit']})" + (f" - {u['why']}" if u.get('why')
                                       else "") for u in unbound]
        if unpriced:
            txt.append("")
            txt.append("Components with no rate (counted as $0 - enter "
                       "rates in the library):")
            txt += [f"  {u}" for u in unpriced]
        self.out.setPlainText("\n".join(txt))
        return self.result

    def save(self):
        d = ac.read_job(self.doc)
        d["cascade"] = [list(x) for x in self.cascade()]
        d["tax_pct"] = str(self.tax.value())
        d["building_sf"] = self.sf.text().strip()
        ac.write_job(self.doc, d)
        self.mw._view.mark_dirty()
        self.accept()

    def export(self, path=None):
        r = self.recalc()
        if r is None:
            return None
        if path is None:
            path, _ = QFileDialog.getSaveFileName(
                self, "Export Bid Summary", report_file_name(
                    "Bid Summary", os.path.splitext(os.path.basename(
                        getattr(self.doc, "name", "") or ""))[0],
                    ext=".xlsx"),
                "Excel (*.xlsx);;CSV (*.csv)")
            if not path:
                return None
        return cost_rollup.export(path, r)


def summary_dialog(mw, show=True):
    if mw._view is None:
        return None
    lib = load_library(mw)
    if not lib:
        return None
    dlg = SummaryDialog(mw, lib)
    if show:
        dlg.exec()
    return dlg


# ------------------------------------------------------------- changes
def change_report(mw, old_path=None, show=True):
    """Compare the open PDF (new revision) with an earlier PDF of the same
    job, priced with the saved library and this job's cascade and tax."""
    import fitz
    from . import change_report as cr
    v = mw._view
    if v is None:
        return None
    lib = load_library(mw)
    if not lib:
        return None
    if old_path is None:
        old_path, _ = QFileDialog.getOpenFileName(
            mw, "Change Report: pick the EARLIER revision PDF",
            os.path.dirname(mw._path or ""), "PDF (*.pdf)")
        if not old_path:
            return None
    try:
        old = fitz.open(old_path)
    except Exception as ex:
        QMessageBox.warning(mw, "Change Report", f"Could not open:\n{ex}")
        return None
    casc, tax, _sf = _job_inputs(v.doc)
    try:
        res = cr.compare(old, v.doc, lib, casc, tax)
    finally:
        old.close()
    text = cr.text(res)
    if not show:
        return res, text
    dlg = QDialog(mw)
    dlg.setWindowTitle("Revision Change Report")
    dlg.resize(720, 560)
    lay = QVBoxLayout(dlg)
    lay.addWidget(QLabel(f"Earlier: {os.path.basename(old_path)}   →   "
                         f"Now: {os.path.basename(mw._path or 'open PDF')}"))
    box = QPlainTextEdit(text)
    box.setReadOnly(True)
    lay.addWidget(box)
    bb = QDialogButtonBox(QDialogButtonBox.Close)
    exp = bb.addButton("Export…", QDialogButtonBox.ActionRole)

    def do_export():
        p, _ = QFileDialog.getSaveFileName(dlg, "Export Change Report",
                                           report_file_name(
                                               "Change Report",
                                               os.path.splitext(
                                                   os.path.basename(
                                                       mw._path or ""))[0],
                                               ext=".txt"),
                                           "Text (*.txt)")
        if p:
            with open(p, "w", encoding="utf-8") as f:
                f.write(text)
    exp.clicked.connect(do_export)
    bb.rejected.connect(dlg.reject)
    lay.addWidget(bb)
    dlg.exec()
    return res, text


def add_menu(mw, parent):
    """Civil > CivilBid-Coded Assemblies submenu."""
    m = parent.addMenu("CivilBid-Coded Assemblies")
    mw._act(m, "Assembly Library (CivilBid codes)…", None,
            lambda: LibraryDialog(mw).exec(), False)
    mw._act(m, "Bind Takeoff Group to Assembly…", None,
            lambda: bind_dialog(mw))
    mw._act(m, "Insert Assembly Line…", None, lambda: insert_dialog(mw))
    m.addSeparator()
    mw._act(m, "Bid Summary (Coded Assemblies)…", None,
            lambda: summary_dialog(mw))
    mw._act(m, "Revision Change Report…", None, lambda: change_report(mw))
    return m
