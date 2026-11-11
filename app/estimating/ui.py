"""Takeoff > Estimating Tools: one window, one page per tool.

Every page opens with no drawing open (its buttons that need one say so)
so the click-everything sweep never blocks on it. The work is done by the
engine modules beside this one; this file only shows and collects.
"""
import logging
import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox,
                               QDoubleSpinBox, QFileDialog, QFormLayout,
                               QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMessageBox, QPlainTextEdit,
                               QPushButton, QSizePolicy, QTableWidget,
                               QTableWidgetItem,
                               QStackedWidget, QVBoxLayout, QWidget)

from .. import dmoney
from ..dmoney import c2 as _c2

log = logging.getLogger(__name__)

MENU_TITLE = "Estimating Tools"
PAGES = [("check", "Estimate Error Check…"),
         ("templates", "Estimate Templates…"),
         ("quote", "Customer Quote With Options…"),
         ("materials", "Material Order List…"),
         ("supplier", "Supplier Price List Import…"),
         ("rates", "Match Rates && Price a Workbook…"),
         ("assembly_rules", "Assembly Rules && Wall-Type Assemblies…"),
         ("crew", "Crew Hours by Pay Item…"),
         ("bidday", "Bid-Day Quote Comparison…"),
         ("actuals", "Estimate vs Actual…"),
         ("service", "Equipment && Service Records…"),
         ("planning", "Planning Cost Model…")]
LAST = None


def _fmt(v):
    return "" if v is None else dmoney.fmt(v)


def _item(text, editable=False):
    it = QTableWidgetItem("" if text is None else str(text))
    if not editable:
        it.setFlags(it.flags() & ~Qt.ItemIsEditable)
    return it


def _fill(table, head, rows):
    table.blockSignals(True)
    table.clear()
    table.setColumnCount(len(head))
    table.setHorizontalHeaderLabels(head)
    table.setRowCount(len(rows))
    for r, row in enumerate(rows):
        for c, v in enumerate(row):
            table.setItem(r, c, v if isinstance(v, QTableWidgetItem)
                          else _item(v))
    table.resizeColumnsToContents()
    table.blockSignals(False)


def _data_dir():
    from .. import settings
    return settings.DIR


def _save_name(parent, title, name, filt):
    """Every save window starts in the data folder (v2 step 5)."""
    start = name if os.path.isabs(name) else os.path.join(_data_dir(), name)
    path, _ = QFileDialog.getSaveFileName(parent, title, start, filt)
    return path


def _open_name(parent, title, filt):
    """Every open window starts in the data folder (v2 step 5)."""
    path, _ = QFileDialog.getOpenFileName(parent, title, _data_dir(), filt)
    return path


def _ask(parent, text):
    """A clear Yes / No question; only Yes goes ahead."""
    return QMessageBox.question(
        parent, "Estimating Tools", text,
        QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes


def _say(parent, text, error=False):
    (QMessageBox.warning if error else QMessageBox.information)(
        parent, "Estimating Tools", text)


def wrap_long_labels(root, longest=50):
    """Sentences in a QLabel wrap instead of running off the window
    (Chief's estimator test, Nov 7: clipped messages and intros)."""
    for lab in root.findChildren(QLabel):
        if not lab.wordWrap() and len(lab.text()) > longest and \
                lab.buddy() is None:
            lab.setWordWrap(True)
    return root


class Page(QWidget):
    key = ""
    needs_doc = True

    def __init__(self, tools):
        super().__init__()
        self.tools = tools
        self.lay = QVBoxLayout(self)
        self.msg = QLabel("")
        self.msg.setWordWrap(True)

    @property
    def doc(self):
        """The main window's drawing now (v2 step 7: an Undo there swaps
        the document; the window used to keep the closed one)."""
        mw = self.tools.mw
        v = getattr(mw, "_view", None) if mw is not None else None
        d = getattr(v, "doc", None) if v is not None else None
        if d is not None and not getattr(d, "is_closed", False):
            return d
        return self.tools.doc

    def edited(self):
        mw = self.tools.mw
        if mw is not None and hasattr(mw, "_doc_edited"):
            try:
                mw._doc_edited()
            except Exception:                             # noqa: BLE001
                log.warning("could not mark the drawing edited",
                            exc_info=True)

    def no_doc(self):
        if self.doc is None:
            self.msg.setText("Open a drawing first.")
            return True
        return False

    def buttons(self, *specs):
        row = QHBoxLayout()
        out = []
        for text, slot in specs:
            b = QPushButton(text)
            b.clicked.connect(lambda _c=False, s=slot: self._safe(s))
            row.addWidget(b)
            out.append(b)
        row.addStretch(1)
        self.lay.addLayout(row)
        return out

    def _safe(self, slot):
        try:
            slot()
        except Exception as e:                            # noqa: BLE001
            log.warning("estimating tool failed", exc_info=True)
            self.msg.setText(str(e))

    def refresh(self):
        pass


# ---- B6 ----------------------------------------------------------------------

_SEED_DECLINED = set()          # price databases you said No for (this run)


def _civil(doc):
    """(job, lib) of the civil estimate, or (None, None) when it has none
    (the library is only read when there is a civil job); the activities
    take their takeoff quantities (flow.civil, a copy). v2 step 5: an
    empty price database is filled with the starter civil library only
    when you say Yes (asked once; No is remembered until QuantiSheet is
    closed)."""
    from . import flow, safedb

    def ask(question):
        key = safedb.path()
        if key in _SEED_DECLINED:
            return False
        from PySide6.QtWidgets import QApplication
        if _ask(QApplication.activeWindow(), question):
            return True
        _SEED_DECLINED.add(key)
        return False
    return flow.civil(doc, ask=ask)


class CheckPage(Page):
    key = "check"

    def __init__(self, tools):
        super().__init__(tools)
        self.lay.addWidget(QLabel("Finds zero quantities, lines without a "
                                  "price, unit mismatches, duplicates, civil "
                                  "activities without a crew, takeoff nobody "
                                  "priced and unit costs far from your own "
                                  "history file."))
        self.history = ""
        self.found = []
        self.buttons(("Run Check", self.run),
                     ("Use History File…", self.pick_history),
                     ("Rules…", self.pick_rules),
                     ("Export…", self.export))
        self.table = QTableWidget()
        self.lay.addWidget(self.table)
        self.lay.addWidget(self.msg)

    def pick_history(self):
        p = _open_name(self, "Your estimate history file", "JSON (*.json)")
        if p:
            self.history = p
            self.run()

    def pick_rules(self):
        dlg = RulesDialog(self)
        if dlg.exec():
            dlg.save()
            self.run()

    def run(self):
        from . import actuals, checks
        hist = actuals.load_history(self.history) if self.history else None
        job, lib = _civil(self.doc)
        self.found = checks.run(self.doc, job=job, lib=lib, history=hist)
        _fill(self.table, ["Severity", "Check", "Item", "Message"],
              [[f["severity"], checks.RULES[f["rule"]], f["item"],
                f["message"]] for f in self.found])
        s = checks.summary(self.found)
        self.msg.setText((f"{s['errors']} error(s), {s['warnings']} "
                          "warning(s)" if self.found else
                          "No problems found.") + off_note())

    def export(self):
        from . import checks
        p = _save_name(self, "Export check", "Estimate check.csv",
                       "CSV (*.csv);;Excel (*.xlsx)")
        if p:
            checks.export_csv(self.found, p)
            self.msg.setText(f"Saved {p}")


def off_note():
    """' (N rule(s) switched off: ...)' for the check page, or ''."""
    from . import checks
    off = sorted(checks.rules_off())
    if not off:
        return ""
    return (f" - {len(off)} rule(s) switched off (Rules…): " +
            ", ".join(checks.RULES[r] for r in off))


class RulesDialog(QDialog):
    """Estimate Error Check rules: a box per rule (untick to switch it
    off) with its How To text on hover and beside it."""

    def __init__(self, parent=None):
        super().__init__(parent)
        from PySide6.QtWidgets import QCheckBox, QScrollArea, QWidget
        from . import checks
        self.setWindowTitle("Estimate Error Check - Rules")
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Untick a rule to switch it off. Schedule "
                             "checks are advisory and never change the "
                             "takeoff."))
        inner = QWidget()
        il = QVBoxLayout(inner)
        off = checks.rules_off()
        self.boxes = {}
        for r, label in checks.RULES.items():
            b = QCheckBox(label)
            b.setChecked(r not in off)
            b.setToolTip(checks.HOW_TO[r])
            il.addWidget(b)
            h = QLabel(checks.HOW_TO[r])
            h.setWordWrap(True)
            h.setStyleSheet("color: gray; margin-left: 22px;")
            il.addWidget(h)
            self.boxes[r] = b
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setWidget(inner)
        lay.addWidget(sc)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.resize(560, 520)

    def save(self):
        from . import checks
        for r, b in self.boxes.items():
            checks.set_rule_on(r, b.isChecked())


# ---- A2 + B2 -----------------------------------------------------------------

class TemplatesPage(Page):
    key = "templates"

    def __init__(self, tools):
        super().__init__(tools)
        self.lay.addWidget(QLabel("Your own templates: a set of items with "
                                  "quantity formulas off takeoff groups, or "
                                  "a pay-item list for the civil estimate."))
        self.list = QListWidget()
        self.lay.addWidget(self.list)
        self.binds = QTableWidget()
        self.lay.addWidget(QLabel("Takeoff group for each placeholder:"))
        self.lay.addWidget(self.binds)
        from PySide6.QtWidgets import QCheckBox
        self.skip = QCheckBox("Leave out items whose placeholder has no "
                              "takeoff group")
        self.skip.setChecked(True)
        self.lay.addWidget(self.skip)
        self.buttons(("Add Starter Templates", self.add_starters),
                     ("Add EXAMPLE Crews", self.add_crews),
                     ("Civil: Starter Pay Items + Pipe Material",
                      self.civil_fill))
        self.buttons(("Save Estimate As Template…", self.save_lines),
                     ("Save Pay Items As Template…", self.save_items),
                     ("Open Template File…", self.open_file),
                     ("Suggest Takeoff Groups", self.suggest),
                     ("Apply To This Drawing", self.apply))
        self.lay.addWidget(self.msg)
        self.list.currentItemChanged.connect(lambda *_: self.show_binds())
        self.extra = []

    def refresh(self):
        from . import templates
        self.list.clear()
        for t in templates.list_saved() + self.extra:
            it = QListWidgetItem(f"{t['name']}  ({t['kind']}, {t['items']} "
                                 "items)")
            it.setData(Qt.UserRole, t["path"])
            self.list.addItem(it)

    def current(self):
        from . import templates
        it = self.list.currentItem()
        return templates.load(it.data(Qt.UserRole)) if it else None

    def show_binds(self):
        from . import costlink, templates
        tpl = self.current()
        names = templates.placeholders(tpl) if tpl and \
            tpl["kind"] == "estimate" else []
        groups = costlink.groups(self.doc)
        self.binds.clear()
        self.binds.setColumnCount(2)
        self.binds.setHorizontalHeaderLabels(["Placeholder", "Takeoff group"])
        self.binds.setRowCount(len(names))
        for r, n in enumerate(names):
            self.binds.setItem(r, 0, _item(n))
            cb = QComboBox()
            cb.addItem("(not linked)", None)
            for g in groups:
                cb.addItem(f"{g['name']} ({g['unit']})",
                           (g["name"], g["type"], g["unit"]))
                if g["name"] == n:
                    cb.setCurrentIndex(cb.count() - 1)
            self.binds.setCellWidget(r, 1, cb)

    def add_starters(self):
        from . import starters, templates
        if not _ask(self, "Add the blank starter templates (commercial "
                    "building GC, sitework / civil utilities, residential "
                    "/ insurance repair and a civil pay-item list) to "
                    f"{templates.folder()}? Every price is blank; "
                    "templates you already have are kept. Nothing is "
                    "added to the price database."):
            return
        r = starters.install()
        self.msg.setText(
            f"Added {len(r['written'])} blank starter template(s)"
            + (f"; kept {len(r['skipped'])} you already have"
               if r["skipped"] else "") + ". Every price is blank - fill in "
            "your own.")
        self.refresh()

    def add_crews(self):
        from . import starters
        asked = []

        def confirm(q):
            asked.append(q)
            return _ask(self, q)
        n = starters.install_crews(confirm=confirm)
        if n:
            self.msg.setText(f"Added {n} EXAMPLE crew / labor / equipment "
                             "record(s) - enter your wages and rates. A "
                             "backup copy of the price database is in the "
                             "data folder's backups folder.")
        elif asked:
            self.msg.setText("Nothing was added; the price database is "
                             "unchanged.")
        else:
            self.msg.setText("Your civil library already has every EXAMPLE "
                             "code; nothing was added.")

    def civil_fill(self):
        from . import starters
        from .. import heavy
        if self.no_doc():
            return
        job = heavy.read(self.doc)
        r = starters.civil_fill(job)
        heavy.write(self.doc, job)
        self.edited()
        self.msg.setText(
            f"Added {r['pay_items_added']} pay item(s); put "
            f"{r['assigned']} activit(ies) on a pay item; added pipe / "
            f"structure material (price blank) to {r['materials_added']}."
            + (f" Not matched: {', '.join(r['not_matched'][:5])}"
               if r["not_matched"] else ""))

    def suggest(self):
        from . import starters
        if self.no_doc():
            return
        tpl = self.current()
        if tpl is None or tpl["kind"] != "estimate":
            self.msg.setText("Pick an estimate template.")
            return
        self.show_binds()
        notes = []
        b = starters.suggest_bindings(self.doc, tpl, notes=notes)
        n = 0
        for r in range(self.binds.rowCount()):
            gs = b.get(self.binds.item(r, 0).text())
            if not gs:
                continue
            cb = self.binds.cellWidget(r, 1)
            if len(gs) == 1:
                i = cb.findData(tuple(gs[0]))
                if i >= 0:
                    cb.setCurrentIndex(i)
            else:
                cb.insertItem(1, f"({len(gs)} suggested groups: "
                              + ", ".join(g[0] for g in gs[:3])
                              + (" ..." if len(gs) > 3 else "") + ")",
                              [list(g) for g in gs])
                cb.setCurrentIndex(1)
            n += len(gs)
        self.msg.setText(f"Suggested {n} takeoff group(s) by name - check "
                         "them before you apply." + "".join(
                             "\n" + x for x in notes[:5]))

    def _name(self):
        from PySide6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "Template", "Template name:")
        return name.strip() if ok and name.strip() else ""

    def save_lines(self):
        from . import templates
        if self.no_doc():
            return
        name = self._name()
        if name:
            p = templates.save(templates.from_lines(self.doc, name))
            self.msg.setText(f"Saved {p}")
            self.refresh()

    def save_items(self):
        from . import templates
        from .. import heavy
        if self.no_doc():
            return
        name = self._name()
        if name:
            p = templates.save(templates.from_pay_items(heavy.read(self.doc),
                                                        name))
            self.msg.setText(f"Saved {p}")
            self.refresh()

    def open_file(self):
        from . import templates
        p = _open_name(self, "Open template", "JSON (*.json)")
        if p:
            t = templates.load(p)
            self.extra.append({"name": t["name"], "kind": t["kind"],
                               "path": p, "items": len(t["items"])})
            self.refresh()

    def apply(self):
        from . import templates
        from .. import heavy
        if self.no_doc():
            return
        tpl = self.current()
        if tpl is None:
            self.msg.setText("Pick a template.")
            return
        if tpl["kind"] == "bid_items":
            job = heavy.read(self.doc)
            added = templates.apply_bid_items(job, tpl)
            heavy.write(self.doc, job)
            self.msg.setText(f"Added {len(added)} pay item(s).")
        else:
            b = {}
            for r in range(self.binds.rowCount()):
                g = self.binds.cellWidget(r, 1).currentData()
                if g:
                    b[self.binds.item(r, 0).text()] = g
            ids = templates.apply(self.doc, tpl, b,
                                  skip_unlinked=self.skip.isChecked())
            self.msg.setText(f"Added {len(ids)} estimate line(s).")
        self.edited()


# ---- A3 + D1 -----------------------------------------------------------------

class QuotePage(Page):
    key = "quote"

    def __init__(self, tools):
        super().__init__(tools)
        form = QFormLayout()
        self.mode = QComboBox()
        self.mode.addItems(["markup", "margin"])
        self.pct = QDoubleSpinBox()
        self.pct.setRange(-99, 99)
        self.pct.setSuffix(" %")
        self.tier_names = QLineEdit("Good, Better, Best")
        self.pick = QComboBox()
        form.addRow("Price from cost by:", self.mode)
        form.addRow("Percent:", self.pct)
        form.addRow("Option names:", self.tier_names)
        form.addRow("Customer picked:", self.pick)
        self.lay.addLayout(form)
        self.table = QTableWidget()
        self.lay.addWidget(self.table)
        row = QHBoxLayout()
        self.inc = QPlainTextEdit()
        self.inc.setPlaceholderText("Inclusions, one per line")
        self.exc = QPlainTextEdit()
        self.exc.setPlaceholderText("Exclusions, one per line")
        row.addWidget(self.inc)
        row.addWidget(self.exc)
        self.lay.addLayout(row)
        self.totals = QLabel("")
        self.totals.setWordWrap(True)
        self.lay.addWidget(self.totals)
        self.buttons(("Save Settings", self.save_spec),
                     ("Save Quote PDF…", self.save_pdf),
                     ("Export CSV…", self.export))
        self.lay.addWidget(self.msg)
        self.rows = []

    def tiers(self):
        return [t.strip() for t in self.tier_names.text().split(",")
                if t.strip()]

    def refresh(self):
        from . import quotes
        if self.no_doc():
            return
        spec = quotes.read(self.doc)
        self.mode.setCurrentText(spec["mode"])
        self.pct.setValue(float(dmoney.D(spec["pct"] or 0)))
        self.tier_names.setText(", ".join(spec["tiers"]))
        self.inc.setPlainText("\n".join(spec["inclusions"]))
        self.exc.setPlainText("\n".join(spec["exclusions"]))
        from . import items
        self.rows = items.collect(self.doc, *_civil(self.doc))["items"]
        _fill(self.table, ["Description", "Qty", "Unit", "Cost", "Goes in",
                           "Customer name"],
              [[r["desc"], r["qty"], r["unit"], _fmt(r["total"]), "",
                _item(spec["names"].get(r["id"]) or
                      quotes.friendly_name(r["desc"]), True)]
               for r in self.rows])
        for i, r in enumerate(self.rows):
            cb = QComboBox()
            cb.addItems(["Base"] + spec["tiers"] + ["Optional"])
            w = spec["assign"].get(r["id"], "base")
            cb.setCurrentText({"base": "Base", "option": "Optional"}.get(w, w))
            self.table.setCellWidget(i, 4, cb)
        self._picks(spec)
        self.show_totals(spec)

    def _picks(self, spec):
        self.pick.clear()
        self.pick.addItem("")
        self.pick.addItems(spec["tiers"])
        self.pick.setCurrentText(spec["selected_tier"])

    def set_where(self, line_id, where):
        for i, r in enumerate(self.rows):
            if r["id"] == line_id:
                self.table.cellWidget(i, 4).setCurrentText(where)

    def spec(self):
        from . import quotes
        s = quotes.read(self.doc)
        s.update(mode=self.mode.currentText(), pct=str(self.pct.value()),
                 tiers=self.tiers(),
                 inclusions=self.inc.toPlainText().splitlines(),
                 exclusions=self.exc.toPlainText().splitlines(),
                 selected_tier=self.pick.currentText())
        assign = {}
        for i, r in enumerate(self.rows):
            t = self.table.cellWidget(i, 4).currentText()
            assign[r["id"]] = {"Base": "base", "Optional": "option"}.get(t, t)
        s["assign"] = assign
        names = {}
        for i, r in enumerate(self.rows):
            cell = self.table.item(i, 5)
            t = " ".join(cell.text().split()) if cell else ""
            if t and t != quotes.friendly_name(r["desc"]):
                names[r["id"]] = t
        s["names"] = names
        return s

    def save_spec(self):
        from . import quotes
        if self.no_doc():
            return
        s = self.spec()
        quotes.write(self.doc, s)
        self.edited()
        self._picks(quotes.read(self.doc))
        self.show_totals(s)

    def show_totals(self, spec):
        from . import quotes
        q = quotes.compute(self.doc, spec, *_civil(self.doc))
        parts = [f"Base {_fmt(q['base']['price'])}"]
        parts += [f"{t['name']} {_fmt(t['total'])}" for t in q["tiers"]]
        if q["options"]:
            parts.append(f"{len(q['options'])} optional item(s)")
        if q["selected"]["total"] is not None:
            parts.append(f"Picked: {_fmt(q['selected']['total'])}")
        self.totals.setText("   |   ".join(parts))

    def save_pdf(self):
        from . import quotes
        if self.no_doc():
            return
        self.save_spec()
        p = _save_name(self, "Save quote", "Quote.pdf", "PDF (*.pdf)")
        if p:
            job, lib = _civil(self.doc)
            quotes.save_pdf(self.doc, p, job=job, lib=lib)
            self.msg.setText(f"Saved {p}")

    def export(self):
        from . import quotes
        if self.no_doc():
            return
        self.save_spec()
        p = _save_name(self, "Export quote", "Quote.csv",
                       "CSV (*.csv);;Excel (*.xlsx)")
        if p:
            quotes.export_csv(self.doc, p, None, *_civil(self.doc))
            self.msg.setText(f"Saved {p}")


# ---- A4 ----------------------------------------------------------------------

class MaterialsPage(Page):
    key = "materials"

    def __init__(self, tools):
        super().__init__(tools)
        self.lay.addWidget(QLabel("The material in the estimate by supplier. "
                                  "Type a supplier in the first column, or "
                                  "add your supplier price list files."))
        self.lists = []
        self.table = QTableWidget()
        self.table.itemChanged.connect(self._changed)
        self.lay.addWidget(self.table)
        self.buttons(("Add Supplier Price List File…", self.add_list),
                     ("Refresh", self.refresh), ("Export…", self.export))
        self.lay.addWidget(self.msg)
        self.order = {}

    def add_list(self):
        from . import supplier_prices
        p = _open_name(self, "Supplier price list file", "JSON (*.json)")
        if p:
            self.lists.append(supplier_prices.load(p))
            self.refresh()

    def refresh(self):
        from . import materials
        if self.no_doc():
            return
        self.order = materials.order_list(self.doc, self.lists,
                                          *_civil(self.doc))
        rows = []
        for who, items in self.order.items():
            for r in items:
                rows.append([_item("" if who == materials.NO_SUPPLIER
                                   else who, True), r.get("sku", ""),
                             r["desc"], r["qty"], r["unit"],
                             _fmt(r.get("supplier_price")), _fmt(r["cost"])])
        _fill(self.table, ["Supplier", "Item #", "Description", "Qty", "Unit",
                           "Supplier price", "Estimate cost"], rows)
        left = materials.no_cost_type(self.doc, *_civil(self.doc))
        self.msg.setText("" if not left else (
            f"{len(left)} priced item(s) have no cost type, so they are not "
            "on this list: " + ", ".join(i["desc"] for i in left[:5]) +
            (" ..." if len(left) > 5 else "") + " - pick a cost type in "
            "the Estimate panel."))

    def _changed(self, it):
        from . import materials
        if it.column() != 0 or self.doc is None:
            return
        desc = self.table.item(it.row(), 2).text()
        materials.set_supplier(self.doc, desc, it.text())
        self.edited()

    def export(self):
        from . import materials
        if self.no_doc():
            return
        p = _save_name(self, "Export order list", "Material order list.xlsx",
                       "Excel (*.xlsx);;CSV (*.csv)")
        if p:
            materials.export(self.order, p)
            self.msg.setText(f"Saved {p}")


# ---- A5 ----------------------------------------------------------------------

class SupplierPage(Page):
    key = "supplier"
    needs_doc = False

    def __init__(self, tools):
        from . import supplier_prices
        super().__init__(tools)
        self.lay.addWidget(QLabel("Import a supplier's price list (your CSV "
                                  "or Excel file) into a NEW price list file "
                                  "you name. Nothing is added to the price "
                                  "database."))
        form = QFormLayout()
        self.supplier = QLineEdit()
        self.effective = QLineEdit()
        self.effective.setPlaceholderText("YYYY-MM-DD")
        form.addRow("Supplier:", self.supplier)
        form.addRow("Prices good from:", self.effective)
        self.maps = {}
        for f in supplier_prices.FIELDS:
            cb = QComboBox()
            self.maps[f] = cb
            form.addRow(f"Column for {f}:", cb)
        self.lay.addLayout(form)
        self.table = QTableWidget()
        self.lay.addWidget(self.table)
        self.buttons(("Choose CSV or Excel File…", self.choose),
                     ("Save As New Price List…", self.save))
        self.lay.addWidget(self.msg)
        self.src, self.head, self.rows = "", [], []

    def choose(self):
        p = _open_name(self, "Supplier price list", "CSV or Excel (*.csv "
                       "*.xlsx)")
        if p:
            self.load(p)

    def load(self, path):
        from . import supplier_prices
        self.src = path
        self.head, self.rows = supplier_prices.read(path)
        guess = supplier_prices.guess_mapping(self.head)
        for f, cb in self.maps.items():
            cb.clear()
            cb.addItem("(none)", None)
            for i, h in enumerate(self.head):
                cb.addItem(h, i)
            if f in guess:
                cb.setCurrentIndex(guess[f] + 1)
        _fill(self.table, self.head, self.rows[:20])

    def mapping(self):
        return {f: cb.currentData() for f, cb in self.maps.items()
                if cb.currentData() is not None}

    def save(self):
        from . import supplier_prices
        if not self.src:
            self.msg.setText("Choose a file first.")
            return
        res = supplier_prices.build(self.head, self.rows, self.mapping(),
                                    self.supplier.text(),
                                    self.effective.text(),
                                    os.path.basename(self.src))
        p = _save_name(self, "New price list file", "Supplier prices.json",
                       "JSON (*.json)")
        if p:
            # the save window already asked before replacing a file; the
            # old one is kept in the data folder's backups folder first
            p, bak = supplier_prices._save(res["pricelist"], p,
                                           overwrite=os.path.exists(p))
            self.msg.setText(f"Saved {len(res['pricelist']['items'])} items "
                             f"to {p}; {len(res['skipped'])} row(s) skipped."
                             + (f" The old file is kept as {bak}." if bak
                                else ""))


# ---- B1 ----------------------------------------------------------------------

class CrewPage(Page):
    key = "crew"

    def __init__(self, tools):
        super().__init__(tools)
        self.lay.addWidget(QLabel("Crew hours, crew days and direct cost per "
                                  "pay item from your crews and production "
                                  "rates (Civil > Crew Estimate)."))
        self.table = QTableWidget()
        self.lay.addWidget(self.table)
        self.buttons(("Refresh", self.refresh), ("Export…", self.export))
        self.lay.addWidget(self.msg)
        self.result = None

    def refresh(self):
        from . import crewhours
        if self.no_doc():
            return
        job, lib = _civil(self.doc)
        if job is None:
            self.msg.setText("This drawing has no civil crew estimate yet.")
            _fill(self.table, [], [])
            return
        self.result = r = crewhours.by_pay_item(job, lib)
        _fill(self.table, ["Pay item", "Description", "Qty", "Unit",
                           "Crew hours", "Crew days", "Crews", "Direct",
                           "Per unit"],
              [[x["no"], x["desc"], x["owner_qty"], x["unit"], x["hours"],
                x["crew_days"], "; ".join(f"{k} {v} h" for k, v in
                                          x["crews"].items()),
                _fmt(x["direct"]), _fmt(x["unit_cost"])]
               for x in r["items"] + [r["unassigned"]]])
        self.msg.setText(f"{r['total_hours']} crew hours. " +
                         " ".join(r["problems"][:5]))

    def export(self):
        from . import crewhours
        if self.result is None:
            self.refresh()
        if self.result is None:
            return
        p = _save_name(self, "Export crew hours", "Crew hours.xlsx",
                       "Excel (*.xlsx);;CSV (*.csv)")
        if p:
            crewhours.export(self.result, p)
            self.msg.setText(f"Saved {p}")


# ---- B4 ----------------------------------------------------------------------

LOWEST_COMPLETE = "(lowest complete quote)"


class BidDayPage(Page):
    key = "bidday"

    def __init__(self, tools):
        super().__init__(tools)
        self.lay.addWidget(QLabel("Quotes for one scope package side by side. "
                                  "Import a CSV: Item, Description, Unit, "
                                  "Qty, My plug, then one column per bidder "
                                  "(excl or blank = not quoted)."))
        self.package = QComboBox()
        self.package.currentTextChanged.connect(lambda *_: self.show_sheet())
        self.lay.addWidget(self.package)
        self.table = QTableWidget()
        self.lay.addWidget(self.table)
        row = QHBoxLayout()
        row.addWidget(QLabel("Quote to use:"))
        self.bidder = QComboBox()
        row.addWidget(self.bidder, 1)
        self.lay.addLayout(row)
        self.buttons(("New Package From Takeoff…", self.pick_takeoff),
                     ("Blank Bid Form…", self.export_form),
                     ("Import Quotes CSV…", self.import_csv),
                     ("Use This Quote", self.use_quote),
                     ("Remove From Estimate", self.remove_quote),
                     ("Export…", self.export),
                     ("Delete Package", self.delete))
        self.lay.addWidget(self.msg)
        self.result = None

    def refresh(self):
        from . import bidday
        if self.no_doc():
            return
        self.package.blockSignals(True)
        self.package.clear()
        self.package.addItems(bidday.packages(self.doc))
        self.package.blockSignals(False)
        self.show_sheet()

    def show_sheet(self):
        from . import bidday
        sheet = bidday.load(self.doc, self.package.currentText()) \
            if self.doc is not None else None
        if sheet is None:
            _fill(self.table, [], [])
            self.bidder.clear()
            return None
        self.result = r = bidday.compare(sheet)
        names = [b["name"] for b in r["bidders"]]
        keep = self.bidder.currentText()
        self.bidder.clear()
        self.bidder.addItems([LOWEST_COMPLETE] + names)
        if keep in names:
            self.bidder.setCurrentText(keep)
        rows = []
        for x in r["rows"]:
            cells = []
            for n in names:
                c = x["cells"][n]
                cells.append("MISSING" if c["amount"] is None else
                             ("plug " if c["plug"] else "") + _fmt(
                                 c["amount"]))
            rows.append([x["id"], x["desc"], x["unit"], x["qty"]] + cells)
        by = {b["name"]: b for b in r["bidders"]}
        rows.append(["", "Leveled total", "", ""] +
                    [_fmt(by[n]["total"]) for n in names])
        _fill(self.table, ["Item", "Description", "Unit", "Qty"] + names,
              rows)
        ap = sheet.get("applied") or {}
        self.msg.setText(f"Lowest leveled: {r['lowest_leveled'] or '-'};  "
                         f"lowest complete: {r['lowest_complete'] or '-'}"
                         + (f";  in the estimate: {ap['bidder']}"
                            if ap.get("bidder") else ""))
        try:                       # Nov 11: qualification at a glance
            from .. import qualify_ui
            q = qualify_ui.line([(n, by[n]["total"]) for n in names])
            if q:
                self.msg.setText(self.msg.text() + "<br>" + q)
        except Exception:                                 # noqa: BLE001
            pass
        return None

    def pick_takeoff(self):
        """Pick takeoff groups for a new package (nothing retyped)."""
        from PySide6.QtWidgets import (QDialog, QDialogButtonBox,
                                       QInputDialog, QListWidget,
                                       QListWidgetItem)
        from .. import estimate
        if self.no_doc():
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("Takeoff groups for the package")
        lay = QVBoxLayout(dlg)
        lst = QListWidget()
        for g in estimate.lines(self.doc):
            it = QListWidgetItem(f"{g['name']}  ({_c2(g['quantity']):,.2f} "
                                 f"{g['unit']})")
            it.setData(Qt.UserRole, (g["name"], g["type"], g["unit"]))
            it.setCheckState(Qt.Unchecked)
            lst.addItem(it)
        lay.addWidget(lst)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)
        if not dlg.exec():
            return
        keys = [lst.item(i).data(Qt.UserRole) for i in range(lst.count())
                if lst.item(i).checkState() == Qt.Checked]
        name, ok = QInputDialog.getText(self, "Package", "Scope package:")
        if ok and name.strip() and keys:
            self.from_takeoff(name.strip(), keys)

    def from_takeoff(self, package, keys):
        from . import bidday
        from .. import estimate
        want = [tuple(k) for k in keys]
        groups = [g for g in estimate.lines(self.doc)
                  if (g["name"], g["type"], g["unit"]) in want]
        old = bidday.load(self.doc, package)
        sheet = bidday.new_sheet(package, bidday.scope_from_takeoff(groups),
                                 (old or {}).get("bidders") or [])
        bidday.save(self.doc, sheet)
        self.edited()
        self.refresh()
        self.package.setCurrentText(package)
        self.msg.setText(f"{len(groups)} takeoff group(s) in package "
                         f"{package}. Send the Blank Bid Form, then Import "
                         "Quotes CSV.")

    def export_form(self):
        from . import bidday
        sheet = bidday.load(self.doc, self.package.currentText()) \
            if self.doc is not None else None
        if sheet is None:
            return
        p = _save_name(self, "Blank bid form", f"{sheet['package']} bid "
                       "form.csv", "CSV (*.csv);;Excel (*.xlsx)")
        if p:
            bidday.export_form(sheet, p)
            self.msg.setText(f"Saved {p}")

    def use_quote(self):
        from . import bidday
        pkg = self.package.currentText()
        if self.no_doc() or not pkg:
            return
        who = self.bidder.currentText()
        which = "the lowest complete quote" if who in (
            "", LOWEST_COMPLETE) else f"{who}'s quote"
        if not _ask(self, f"Put {which} for {pkg} into the estimate? This package's bid-day "
                    "lines already in the estimate are replaced (Undo "
                    "takes it back). Nothing is written to the price "
                    "database."):
            return
        from .. import qualify_ui
        r = getattr(self, "result", None) or {}
        name = who if who not in ("", LOWEST_COMPLETE) else \
            r.get("lowest_complete") or ""
        amt = next((b["total"] for b in r.get("bidders") or []
                    if b["name"] == name), None)
        ov = qualify_ui.confirm(self, name, amt, "Bid Day") if name else \
            qualify_ui.NO_WARNING
        if ov == qualify_ui.CANCELLED:
            return
        res = bidday.apply_quote(self.doc, pkg, None if who in (
            "", LOWEST_COMPLETE) else who)
        bidday.set_extra(self.doc, pkg, "award_override",
                         ov if isinstance(ov, dict) else None)
        self.edited()
        self.show_sheet()
        bits = [f"{len(res['line_ids'])} line(s) of {res['bidder']}'s quote "
                f"({res['how']}) in the estimate, {_fmt(res['total'])}"]
        if res["plugs"]:
            bits.append(f"{len(res['plugs'])} plug(s) marked PLUG: "
                        + ", ".join(res["plugs"]))
        if res["missing"]:
            bits.append(f"{len(res['missing'])} item(s) nobody priced, in "
                        "at 0: " + ", ".join(res["missing"]))
        self.msg.setText(".  ".join(bits))

    def remove_quote(self):
        from . import bidday
        pkg = self.package.currentText()
        if self.no_doc() or not pkg:
            return
        n = bidday.remove_quote(self.doc, pkg)
        self.edited()
        self.show_sheet()
        self.msg.setText(f"{n} line(s) of package {pkg} taken out of the "
                         "estimate")

    def import_csv(self):
        from PySide6.QtWidgets import QInputDialog
        from . import bidday
        if self.no_doc():
            return
        p = _open_name(self, "Quotes CSV", "CSV or Excel (*.csv *.xlsx)")
        if not p:
            return
        name, ok = QInputDialog.getText(self, "Package", "Scope package:",
                                        text=self.package.currentText())
        if ok and name.strip():
            bidday.save(self.doc, bidday.read_csv(
                p, name.strip(), base=bidday.load(self.doc, name.strip())))
            self.edited()
            self.refresh()
            self.package.setCurrentText(name.strip())

    def export(self):
        from . import bidday
        if self.result is None:
            return
        p = _save_name(self, "Export comparison", "Bid day.xlsx",
                       "Excel (*.xlsx);;CSV (*.csv)")
        if p:
            bidday.export(self.result, p)
            self.msg.setText(f"Saved {p}")

    def delete(self):
        from . import bidday
        if self.doc is not None and self.package.currentText():
            bidday.delete(self.doc, self.package.currentText())
            self.edited()
            self.refresh()


# ---- B3 ----------------------------------------------------------------------

class ActualsPage(Page):
    key = "actuals"

    def __init__(self, tools):
        super().__init__(tools)
        self.lay.addWidget(QLabel("Type the actual quantity and cost of each "
                                  "estimate item as the job goes; add the "
                                  "finished job "
                                  "to your history file for the outlier "
                                  "check."))
        self.table = QTableWidget()
        self.table.itemChanged.connect(self._changed)
        self.lay.addWidget(self.table)
        self.buttons(("Refresh", self.refresh),
                     ("Import Actuals…", self.import_actuals),
                     ("Add Job To History File…", self.archive),
                     ("Export…", self.export))
        self.lay.addWidget(self.msg)
        self.ids = []

    def refresh(self):
        from . import actuals
        if self.no_doc():
            return
        r = actuals.compare(self.doc, *_civil(self.doc))
        self.ids = [x["id"] for x in r["rows"]]
        self._filling = True
        try:
            _fill(self.table, ["Description", "Unit", "Est. qty",
                               "Actual qty", "Est. cost", "Actual cost",
                               "Variance", "Variance %",
                               # v2 step 7: waste and the variance split
                               "Installed qty", "Measured qty",
                               "Waste % planned", "Waste % actual",
                               "Qty variance", "Price variance"],
                  [[x["desc"], x["unit"], x["est_qty"],
                    _item("" if x["act_qty"] is None else x["act_qty"], True),
                    _fmt(x["est_cost"]),
                    _item("" if x["act_cost"] is None else x["act_cost"],
                          True),
                    _fmt(x["cost_var"]), "" if x["cost_var_pct"] is None else
                    f"{x['cost_var_pct']}%",
                    _item("" if x.get("act_installed") is None else
                          x["act_installed"], True),
                    "" if x.get("net_qty") is None else x["net_qty"],
                    f"{x['waste_pct']}%" if x.get("waste_pct") is not None
                    else x.get("waste_basis", ""),
                    "" if x.get("act_waste_pct") is None else
                    f"{x['act_waste_pct']}%",
                    "" if x.get("qty_var_cost") is None else
                    _fmt(x["qty_var_cost"]),
                    "" if x.get("price_var") is None else
                    _fmt(x["price_var"])] for x in r["rows"]])
        finally:
            self._filling = False
        t = r["totals"]
        self.msg.setText(f"Estimate {_fmt(t['est_cost'])}; actual so far "
                         f"{_fmt(t['act_cost'])} on {t['lines_with_actuals']}"
                         " line(s)")

    def _changed(self, it):
        if it.column() not in (3, 5, 8) or getattr(self, "_filling", False):
            return
        r = it.row()
        cell = self.table.item

        def txt(c):
            return cell(r, c).text() if cell(r, c) is not None else None
        try:
            self.set_actual(self.ids[r], qty=txt(3), cost=txt(5),
                            installed=txt(8))
        except Exception as e:                            # noqa: BLE001
            self.msg.setText(str(e))

    def set_actual(self, line_id, qty=None, cost=None, installed=None):
        from . import actuals
        old = actuals.read(self.doc).get(line_id, {})
        job, lib = _civil(self.doc)
        actuals.record(self.doc, line_id,
                       qty=old.get("qty") if qty is None else qty,
                       cost=old.get("cost") if cost is None else cost,
                       installed=old.get("installed") if installed is None
                       else installed, note=old.get("note", ""),
                       job=job, lib=lib)
        self.edited()
        self.refresh()

    def import_actuals(self):
        """v2 step 7: actual costs by cost code (or item id) from a CSV /
        Excel file - preview, then one write (one Undo)."""
        from . import _io, actuals
        if self.no_doc():
            return
        p = _open_name(self, "Actuals file", "CSV or Excel (*.csv *.xlsx)")
        if not p:
            return
        try:
            pv = actuals.import_preview(self.doc, p, *_civil(self.doc))
        except (actuals.ActualsError, _io.TableError, OSError) as e:
            msg = str(e)
            if "nothing was imported" not in msg:
                msg += " - nothing was imported."
            self.msg.setText(msg)
            return
        lines = [f"{r['desc']}: {_fmt(r['cost']) if r['cost'] is not None else ''}"
                 f"  ({r['how']})" for r in pv["rows"][:12]]
        more = len(pv["rows"]) - len(lines)
        text = (f"Record actuals for {len(pv['rows'])} item(s) from "
                f"{pv['file']}?\n\n" + "\n".join(lines) +
                (f"\n... and {more} more" if more > 0 else "") +
                f"\n\nNot matched: {len(pv['unmatched'])}; rows skipped: "
                f"{len(pv['skipped'])}.")
        if not pv["rows"]:
            self.msg.setText(f"No row of {pv['file']} matched an estimate "
                             f"item (not matched: {len(pv['unmatched'])}, "
                             f"skipped: {len(pv['skipped'])}) - nothing was "
                             "imported.")
            return
        if not _ask(self, text):
            return
        n = actuals.apply_import(self.doc, pv)
        self.edited()
        self.refresh()
        um = ", ".join(str(u["code"]) for u in pv["unmatched"][:5])
        self.msg.setText(f"Imported actuals for {n} item(s); not matched: "
                         f"{len(pv['unmatched'])}" + (f" ({um})" if um else "")
                         + f"; rows skipped: {len(pv['skipped'])}" + (
                             " (" + "; ".join(f"line {s['line']}: {s['why']}"
                                              for s in pv["skipped"][:3]) +
                             ")" if pv["skipped"] else ""))

    def archive(self):
        from PySide6.QtWidgets import QInputDialog
        from . import actuals
        if self.no_doc():
            return
        p = _save_name(self, "Your history file", "Estimate history.json",
                       "JSON (*.json)")
        if not p:
            return
        job, ok = QInputDialog.getText(self, "Job", "Job name:")
        if ok and job.strip():
            n = actuals.archive(self.doc, p, job, *_civil(self.doc))
            self.msg.setText(f"{n} line(s) of {job} in {p}")

    def export(self):
        from . import actuals
        if self.no_doc():
            return
        p = _save_name(self, "Export", "Estimate vs actual.xlsx",
                       "Excel (*.xlsx);;CSV (*.csv)")
        if p:
            actuals.export(actuals.compare(self.doc, *_civil(self.doc)), p)
            self.msg.setText(f"Saved {p}")


# ---- D2 + D3 -----------------------------------------------------------------

def _form(parent, title, fields):
    """A small form; {name: text} or None when cancelled."""
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    lay = QFormLayout(dlg)
    edits = {}
    for name, label, default in fields:
        if isinstance(default, list):
            e = QComboBox()
            e.addItems([str(x) for x in default])
        else:
            e = QLineEdit(str(default or ""))
        edits[name] = e
        lay.addRow(label, e)
    bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    bb.accepted.connect(dlg.accept)
    bb.rejected.connect(dlg.reject)
    lay.addRow(bb)
    if dlg.exec() != QDialog.Accepted:
        return None
    return {k: (e.currentText() if isinstance(e, QComboBox) else e.text())
            for k, e in edits.items()}


class ServicePage(Page):
    key = "service"
    needs_doc = False

    def __init__(self, tools):
        from . import service
        super().__init__(tools)
        self.path = service.default_path()
        self.where = QLabel("")
        self.lay.addWidget(self.where)
        self.buttons(("Open Records File…", self.open_file),
                     ("Add Property / Job…", self.add_property),
                     ("Add Equipment…", self.add_equipment),
                     ("Add Recurring Service…", self.add_service),
                     ("Mark Service Done…", self.mark_done),
                     ("Export…", self.export))
        self.lay.addWidget(QLabel("Equipment and warranties:"))
        self.equip = QTableWidget()
        self.lay.addWidget(self.equip)
        self.lay.addWidget(QLabel("Coming due (next 60 days) and overdue:"))
        self.due = QTableWidget()
        self.lay.addWidget(self.due)
        self.lay.addWidget(self.msg)
        self.store = None

    def refresh(self):
        self.reload()

    def reload(self):
        import datetime as dt
        from . import service
        self.store = service.load(self.path)
        today = dt.date.today()
        self.where.setText(f"Records file: {self.path}")
        props = {p["id"]: p["name"] for p in self.store["properties"]}
        _fill(self.equip, ["Property", "Equipment", "Make", "Model",
                           "Serial", "Installed", "Warranty ends", "Status"],
              [[props.get(e["property"], ""), e["kind"], e["make"],
                e["model"], e["serial"], e["installed"],
                (service.warranty_end(e) or ""),
                service.warranty_status(e, today)]
               for e in self.store["equipment"]])
        rem = service.reminders(self.store, today, 60)
        _fill(self.due, ["Due", "What", "Property", "Days left"],
              [[x["date"], x["title"], x["property"], x["days_left"]]
               for x in rem])

    def focus(self, what, rid):
        """Ctrl+K picked a record: select its equipment row (a property:
        its first unit). Returns the row, or None."""
        if self.store is None:
            self.reload()
        rows = self.store.get("equipment") or []
        key = "id" if what == "equipment" else "property"
        row = next((i for i, e in enumerate(rows) if e.get(key) == rid),
                   None)
        if row is not None:
            self.equip.selectRow(row)
            self.equip.scrollToItem(self.equip.item(row, 0))
        elif what == "property":
            name = next((p["name"] for p in self.store.get("properties", [])
                         if p.get("id") == rid), "")
            self.msg.setText(f"{name}: no equipment recorded yet - "
                             "Add Equipment…")
        return row

    def _save(self):
        from . import service
        service.save(self.store, self.path)
        self.reload()

    def open_file(self):
        p = _save_name(self, "Records file (new or existing)",
                       "Service records.json", "JSON (*.json)")
        if p:
            self.path = p
            self.reload()

    def _pick_property(self):
        names = [p["name"] for p in self.store["properties"]]
        if not names:
            self.msg.setText("Add a property or job first.")
            return None
        return names

    def _prop_id(self, name):
        return next(p["id"] for p in self.store["properties"]
                    if p["name"] == name)

    def add_property(self):
        from . import service
        v = _form(self, "Property / job", [("name", "Name:", ""),
                                           ("address", "Address:", ""),
                                           ("customer", "Customer:", "")])
        if v:
            service.add_property(self.store, **v)
            self._save()

    def add_equipment(self):
        from . import service
        names = self._pick_property()
        if not names:
            return
        v = _form(self, "Equipment", [
            ("prop", "Property:", names), ("kind", "Equipment:", ""),
            ("make", "Make:", ""), ("model", "Model:", ""),
            ("serial", "Serial:", ""),
            ("installed", "Installed (YYYY-MM-DD):", ""),
            ("warranty_months", "Warranty (months):", ""),
            ("warranty_end", "or warranty ends (YYYY-MM-DD):", "")])
        if v:
            v["prop"] = self._prop_id(v["prop"])
            service.add_equipment(self.store, **v)
            self._save()

    def add_service(self):
        from . import service
        names = self._pick_property()
        if not names:
            return
        v = _form(self, "Recurring service", [
            ("prop", "Property:", names), ("title", "Service:", ""),
            ("every", "Every:", "12"), ("unit", "Unit:", list(service.UNITS)),
            ("start", "First due (YYYY-MM-DD):", ""),
            ("last_done", "Last done (optional):", "")])
        if v:
            v["prop"] = self._prop_id(v["prop"])
            service.add_service(self.store, **v)
            self._save()

    def mark_done(self):
        import datetime as dt
        from . import service
        titles = [s["title"] for s in self.store["services"]]
        if not titles:
            return
        v = _form(self, "Service done", [("title", "Service:", titles),
                                         ("when", "Date done:",
                                          dt.date.today().isoformat())])
        if v:
            sid = next(s["id"] for s in self.store["services"]
                       if s["title"] == v["title"])
            service.mark_done(self.store, sid, v["when"])
            self._save()

    def export(self):
        import datetime as dt
        from . import service
        p = _save_name(self, "Export records", "Service records.xlsx",
                       "Excel (*.xlsx);;CSV (*.csv)")
        if p:
            service.export(self.store, p, dt.date.today())
            self.msg.setText(f"Saved {p}")


# ---- C -----------------------------------------------------------------------

PLAN_COLS = ["Process", "Count", "Size formula (X)", "Capital a",
             "Capital b", "Capital c", "Curve min X", "Curve max X", "O&M a",
             "O&M b", "O&M c"]


class PlanningPage(Page):
    key = "planning"
    needs_doc = False

    def __init__(self, tools):
        super().__init__(tools)
        self.lay.addWidget(QLabel("Planning-level estimate from YOUR process "
                                  "list and YOUR cost curves: cost = a x X^b "
                                  "+ c per unit. No cost curves come with "
                                  "QuantiSheet."))
        form = QFormLayout()
        self.design = QLineEdit()
        self.design.setPlaceholderText("Design values, e.g. Q=2, BOD=250")
        self.cont = QLineEdit("0")
        self.eng = QLineEdit("0")
        self.years = QLineEdit("")
        self.rate = QLineEdit("")
        form.addRow("Design values:", self.design)
        form.addRow("Contingency %:", self.cont)
        form.addRow("Engineering %:", self.eng)
        # "&&": a single & made the M a shortcut and hid it (Nov 7)
        form.addRow("O&&M years (optional):", self.years)
        form.addRow("Discount rate %:", self.rate)
        self.lay.addLayout(form)
        self.table = QTableWidget(0, len(PLAN_COLS))
        self.table.setHorizontalHeaderLabels(PLAN_COLS)
        self.lay.addWidget(self.table)
        self.buttons(("Add Process", lambda: self.add_row()),
                     ("Remove Process", self.remove_row),
                     ("Calculate", self.calculate),
                     ("Open Model…", self.open_file),
                     ("Save Model As…", self.save_file),
                     ("Export Results…", self.export))
        self.result = QLabel("")
        self.result.setWordWrap(True)
        self.lay.addWidget(self.result)
        self.lay.addWidget(self.msg)
        self.last = None

    def add_row(self, values=None):
        r = self.table.rowCount()
        self.table.insertRow(r)
        vals = values or ["Process", "1", "Q", "", "1", "0", "", "", "", "1",
                          "0"]
        for c, v in enumerate(vals):
            self.table.setItem(r, c, QTableWidgetItem(str(v)))

    def remove_row(self):
        r = self.table.currentRow()
        if r >= 0:
            self.table.removeRow(r)

    def model(self):
        from . import parametric
        m = parametric.blank("Planning model")
        for part in self.design.text().split(","):
            if "=" in part:
                k, v = part.split("=", 1)
                m["design"][k.strip()] = v.strip()

        def cell(r, c):
            it = self.table.item(r, c)
            return it.text().strip() if it else ""
        for r in range(self.table.rowCount()):
            m["processes"].append({
                "name": cell(r, 0), "count": cell(r, 1) or "1",
                "params": {"X": cell(r, 2) or "0"},
                "capital": {"a": cell(r, 3), "b": cell(r, 4),
                            "c": cell(r, 5), "min": cell(r, 6),
                            "max": cell(r, 7)},
                "om": {"a": cell(r, 8), "b": cell(r, 9), "c": cell(r, 10)}})
        m.update(contingency_pct=self.cont.text() or "0",
                 engineering_pct=self.eng.text() or "0",
                 years=self.years.text(), rate_pct=self.rate.text())
        return m

    def calculate(self):
        from . import parametric
        self.last = r = parametric.evaluate(self.model())
        t = r["totals"]
        lines = [f"{p['name']}: X {p['x']}, capital {_fmt(p['capital'])}, "
                 f"O&M {_fmt(p['om'])}/yr" for p in r["processes"]]
        lines.append(f"Capital subtotal {_fmt(t['capital_subtotal'])}, "
                     f"contingency {_fmt(t['contingency'])}, engineering "
                     f"{_fmt(t['engineering'])}, capital total "
                     f"{_fmt(t['capital_total'])}")
        lines.append(f"O&M {_fmt(t['om_annual'])} per year" + (
            f", present worth {_fmt(t['present_worth'])}"
            if t["present_worth"] is not None else ""))
        lines += ["Warning: " + w for w in r["warnings"]]
        self.result.setText("\n".join(lines))

    def open_file(self):
        from . import parametric
        p = _open_name(self, "Open model", "JSON (*.json)")
        if not p:
            return
        m = parametric.load(p)
        self.design.setText(", ".join(f"{k}={v}" for k, v in
                                      m["design"].items()))
        self.cont.setText(m["contingency_pct"])
        self.eng.setText(m["engineering_pct"])
        self.years.setText(m["years"])
        self.rate.setText(m["rate_pct"])
        self.table.setRowCount(0)
        for pr in m["processes"]:
            c, o = pr["capital"], pr["om"]
            self.add_row([pr["name"], pr["count"],
                          next(iter(pr["params"].values()), "0"),
                          c.get("a", ""), c.get("b", ""), c.get("c", ""),
                          c.get("min", ""), c.get("max", ""), o.get("a", ""),
                          o.get("b", ""), o.get("c", "")])

    def save_file(self):
        from . import parametric
        p = _save_name(self, "Save model", "Planning model.json",
                       "JSON (*.json)")
        if p:
            parametric.save(self.model(), p)
            self.msg.setText(f"Saved {p}")

    def export(self):
        from . import parametric
        if self.last is None:
            self.calculate()
        p = _save_name(self, "Export results", "Planning estimate.xlsx",
                       "Excel (*.xlsx);;CSV (*.csv)")
        if p:
            parametric.export(self.last, p)
            self.msg.setText(f"Saved {p}")


# ---- v2 step 7: Match Rates (G4.1-G4.4) ----------------------------------------

class RatesPage(Page):
    key = "rates"
    needs_doc = False

    def __init__(self, tools):
        super().__init__(tools)
        self.lay.addWidget(QLabel(
            "Unpriced takeoff groups matched to YOUR cost books (read only). "
            "Exact matches are ticked; loose ones are shown unticked with "
            "the reason - tick them only if they are right."))
        self.table = QTableWidget()
        self.table.itemChanged.connect(self._ticked)
        self.lay.addWidget(self.table)
        self.buttons(("Match Takeoff Groups", self.refresh),
                     ("Apply Ticked…", self.apply),
                     ("Save Matches…", self.save_matches),
                     ("Load Matches…", self.load_matches),
                     ("Price a Workbook…", self.price_workbook))
        self.lay.addWidget(self.msg)
        self.rows, self.mode, self.wb_path, self.mapping = [], "drawing", \
            None, None

    def _map(self):
        from . import boq
        if self.mapping is None:
            try:
                self.mapping = boq.load_matches()
            except boq.MatchError as e:
                self.msg.setText(str(e))
                self.mapping = {"version": 1, "matches": {}}
        return self.mapping

    def _show(self, res, what):
        from PySide6.QtCore import Qt
        self.rows = res["rows"]
        self.table.blockSignals(True)
        _fill(self.table, ["Use", what, "Unit", "Qty", "Match",
                           "Cost book item", "Unit cost", "How / why"],
              [["", r["target"]["name"], r["target"]["unit"],
                r["target"]["qty"], {"exact": "exact", "fuzzy": "loose",
                                     "none": "none"}[r["status"]],
                "" if r["item"] is None else
                f"{r['item']['source']} - {r['item']['desc']} "
                f"({r['item']['unit']})",
                "" if r["unit_cost"] is None else r["unit_cost"],
                r["reason"] or r["how"]] for r in self.rows])
        self.table.blockSignals(True)
        for i, r in enumerate(self.rows):
            it = self.table.item(i, 0)
            if r["item"] is not None:
                it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                it.setCheckState(Qt.Checked if r["ticked"] else Qt.Unchecked)
        self.table.blockSignals(False)
        c = res["counts"]
        self.msg.setText(
            f"exact {c['exact']}, loose {c['fuzzy']}, none {c['none']}"
            + (f"; {res['already_priced']} group(s) already priced, left "
               "alone" if res.get("already_priced") else ""))

    def _ticked(self, it):
        from PySide6.QtCore import Qt
        if it.column() == 0 and it.row() < len(self.rows):
            self.rows[it.row()]["ticked"] = it.checkState() == Qt.Checked

    def _books(self):
        from . import boq
        try:
            return boq.read_books()
        except Exception as e:                            # noqa: BLE001
            self.msg.setText(f"Your cost books can't be read: {e}")
            return None

    def refresh(self):
        from . import boq
        if self.no_doc():
            return
        books = self._books()
        if books is None:
            return
        self.mode, self.wb_path = "drawing", None
        self._show(boq.match(self.doc, books, self._map()), "Takeoff group")
        if not books:
            self.msg.setText(self.msg.text() + " - no cost books in your "
                             "price database (Takeoff > Cost Books…)")

    def price_workbook(self):
        from . import boq, workbook_pricer as WP
        p = _open_name(self, "Estimate Workbook to price", "Excel (*.xlsx)")
        if not p:
            return
        books = self._books()
        if books is None:
            return
        try:
            lines = WP.read_workbook(p)
        except WP.WorkbookError as e:
            self.msg.setText(str(e))
            return
        job = None
        if self.doc is not None:
            from .. import assemblies
            job = assemblies.read_job(self.doc)
        self.mode, self.wb_path = "workbook", p
        self._show(WP.match(lines, books, self._map(), job), "Workbook line")
        self.msg.setText(self.msg.text() + f" - tick the lines, then Apply "
                         f"Ticked… writes a new copy of "
                         f"{os.path.basename(p)}")

    def apply(self):
        from . import boq, workbook_pricer as WP
        if not self.rows:
            self.msg.setText("Click Match Takeoff Groups or Price a "
                             "Workbook… first.")
            return
        ticked = [r for r in self.rows if r["ticked"] and r["item"]]
        if not ticked:
            self.msg.setText("Nothing is ticked.")
            return
        if self.mode == "workbook":
            if not _ask(self, f"Fill the rates of {len(ticked)} ticked "
                        f"line(s) into a NEW copy of "
                        f"{os.path.basename(self.wb_path)}? The original "
                        "is not changed."):
                return
            try:
                out = WP.write_priced(self.wb_path, self.rows)
            except (WP.WorkbookError, _io_errors()) as e:
                self.msg.setText(str(e))
                return
            self.msg.setText(
                f"Saved {out['path']} ({out['filled']} line(s) priced"
                + (f"; left out: " + "; ".join(
                    f"{s['name']}: {s['why']}" for s in out["skipped"][:4])
                   if out["skipped"] else "") + ")")
            return
        if self.no_doc():
            return
        pv = boq.preview(self.doc, self.rows)
        text = "\n".join(f"{x['name']}: {x['unit_cost']}/{x['unit']} = "
                         f"{_fmt(x['total'])} ({'unit cost' if x['mode'] == 'price' else 'linked line'})"
                         for x in pv["rows"][:15])
        if len(pv["rows"]) > 15:
            text += f"\n... and {len(pv['rows']) - 15} more"
        if not _ask(self, f"Price {len(pv['rows'])} takeoff group(s)? "
                    f"Adds {_fmt(pv['total'])}.\n\n{text}\n\nOne Undo "
                    "takes it all back."):
            return
        out = boq.apply(self.doc, self.rows)
        self.edited()
        msg = (f"{out['priced']} group(s) priced, {out['lines']} linked "
               f"line(s) added")
        if out["skipped"]:
            msg += "; left out: " + "; ".join(
                f"{s['name']}: {s['why']}" for s in out["skipped"][:4])
        self.refresh()
        self.msg.setText(msg + ". " + self.msg.text())

    def save_matches(self):
        from . import boq
        p = _save_name(self, "Save your matches", boq.MATCH_FILE,
                       "JSON (*.json)")
        if not p:
            return
        try:
            n = boq.save_matches(boq.remember(self._map(), self.rows), p)
        except (boq.MatchError, _io_errors()) as e:
            self.msg.setText(str(e))
            return
        self.mapping = boq.load_matches(p)
        self.msg.setText(f"{n} match(es) saved in {p}")

    def load_matches(self):
        from . import boq
        p = _open_name(self, "Your matches file", "JSON (*.json)")
        if not p:
            return
        try:
            self.mapping = boq.load_matches(p)
        except boq.MatchError as e:
            self.msg.setText(str(e))
            return
        self.msg.setText(f"{len(self.mapping['matches'])} saved match(es) "
                         f"from {p}")


# ---- v2 step 7: Assembly Rules and wall-type assemblies (G1.1, G1.2) -----------

class AssemblyRulesPage(Page):
    key = "assembly_rules"

    def __init__(self, tools):
        super().__init__(tools)
        self.lay.addWidget(QLabel(
            "YOUR rules turn takeoff groups into assemblies (preview first, "
            "one Undo). Built-in assemblies come in with every price at $0; "
            "wall types are built from the set's wall-type legend at $0."))
        self.table = QTableWidget()
        self.lay.addWidget(self.table)
        self.buttons(("Preview Rules", self.refresh),
                     ("Apply Rules…", self.apply),
                     ("Open Rules File…", self.open_rules),
                     ("Write Example Rules File…", self.write_example),
                     ("Build Wall-Type Assemblies…", self.build_walls))
        self.lay.addWidget(self.msg)
        self.rules_path, self.legend, self.pv = None, None, None

    def _rules(self):
        from . import assembly_rules as AR
        return AR.load(self.rules_path)

    def _legend(self, rules=None):
        from . import assembly_rules as AR, wall_legends as WL
        if self.legend is None and (rules is None or any(
                isinstance(r["assembly"], str) and
                r["assembly"].strip().lower() == AR.LEGEND
                for r in rules["rules"])):
            self.legend = WL.from_doc(self.doc)
        return self.legend

    def refresh(self):
        from . import assembly_rules as AR
        if self.no_doc():
            return
        try:
            rules = self._rules()
        except AR.RulesError as e:
            self.msg.setText(str(e))
            return
        self.pv = AR.preview(self.doc, rules, legend=self._legend(rules))
        _fill(self.table, ["Takeoff group", "Type", "Rule", "Assembly",
                           "Status", "Why"],
              [[r["group"], r["type"], r["rule"] or "", r["assembly"],
                r["status"], r["why"]] for r in self.pv["rows"]])
        c = self.pv["counts"]
        self.msg.setText(", ".join(f"{k} {v}" for k, v in c.items()))

    def apply(self):
        from . import assembly_rules as AR
        if self.pv is None:
            self.refresh()
        if self.pv is None or not self.pv["counts"]["apply"]:
            self.msg.setText("No group to apply a rule to.")
            return
        todo = [r for r in self.pv["rows"] if r["status"] == "apply"]
        text = "\n".join(f"{r['group']} <- {r['assembly']}"
                         + (" ($0 prices)" if r["zeroed"] else "")
                         for r in todo[:15])
        if not _ask(self, f"Give {len(todo)} takeoff group(s) an assembly?"
                    f"\n\n{text}\n\nNeeds review (no rule): "
                    f"{self.pv['counts']['needs review']}. One Undo takes "
                    "it all back."):
            return
        n = AR.apply(self.doc, self.pv)
        self.edited()
        self.pv = None
        self.refresh()
        self.msg.setText(f"{n} group(s) got an assembly. " + self.msg.text())

    def open_rules(self):
        p = _open_name(self, "Your assembly rules file", "JSON (*.json)")
        if p:
            self.rules_path = p
            self.pv = None
            self.refresh()

    def write_example(self):
        from . import assembly_rules as AR
        p = _save_name(self, "Example assembly rules file", AR.RULES_FILE,
                       "JSON (*.json)")
        if not p:
            return
        try:
            self.rules_path = AR.save(AR.example_rules(), p)
        except (AR.RulesError, _io_errors()) as e:
            self.msg.setText(str(e))
            return
        self.msg.setText(f"Saved {p} - EXAMPLE rules; edit them to match "
                         "your group names and waste.")

    def build_walls(self):
        from . import wall_legends as WL
        if self.no_doc():
            return
        self.legend = None
        built = self._legend()
        if not built["types"]:
            self.msg.setText(built["message"])
            return
        st = {}
        for t in built["types"]:
            st[t["status"]] = st.get(t["status"], 0) + 1
        summary = ", ".join(f"{k} {v}" for k, v in sorted(st.items()))
        text = "\n".join(f"{t['name']}: {t['parts']} parts, {t['status']}"
                         f" - {t['why']}" for t in built["types"][:15])
        if not _ask(self, f"Build {len(built['types'])} wall-type "
                    f"assemblies at $0 ({summary})?\n\n{text}\n\nThey "
                    "go on the matching \"Wall Type\" takeoff groups that "
                    "nothing prices yet. One Undo."):
            return
        res = WL.apply(self.doc, built)
        if res["bound"]:
            self.edited()
        self.msg.setText(
            f"{summary}. On takeoff groups: "
            + (", ".join(res["bound"]) or "none")
            + (f"; already priced: {', '.join(res['priced_already'])}"
               if res["priced_already"] else "")
            + (f"; no takeoff group: {', '.join(res['no_group'])}"
               if res["no_group"] else "")
            + (f"; legend text not readable: "
               f"{', '.join(built['unreadable'])}" if built["unreadable"]
               else ""))


def _io_errors():
    from . import _io
    return (_io.PathError, OSError)


PAGE_CLASSES = {c.key: c for c in (CheckPage, TemplatesPage, QuotePage,
                                   MaterialsPage, SupplierPage, RatesPage,
                                   AssemblyRulesPage, CrewPage,
                                   BidDayPage, ActualsPage, ServicePage,
                                   PlanningPage)}


class GuideWindow(QDialog):
    def __init__(self, parent, title, text):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(560, 480)
        lay = QVBoxLayout(self)
        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setPlainText(text)
        lay.addWidget(self.view)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.close)
        lay.addWidget(bb)

    def text(self):
        return self.view.toPlainText()


class EstimatingTools(QDialog):
    def __init__(self, mw=None, doc=None, start="check"):
        super().__init__(mw)
        self.mw = mw
        self.doc = doc
        self.setWindowTitle("Estimating Tools")
        self.resize(980, 680)
        lay = QVBoxLayout(self)
        # a drop-down, not a tab bar: 10 tabs don't fit (they scrolled with
        # arrows at 980 x 680 on Windows at 150 %, step-3 test)
        top = QHBoxLayout()
        lab = QLabel("&Page:")
        self.picker = QComboBox()
        self.picker.setObjectName("estimating_page_picker")
        self.picker.setFocusPolicy(Qt.StrongFocus)
        self.picker.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        lab.setBuddy(self.picker)
        # never squeezed by the wide drop-down (Chief's estimator test,
        # Nov 7: "Page:" was cut off)
        lab.setMinimumWidth(lab.fontMetrics().horizontalAdvance("Page:")
                            + 12)
        lab.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        top.addWidget(lab)
        top.addWidget(self.picker)
        top.addStretch(1)
        lay.addLayout(top)
        self.stack = QStackedWidget()
        lay.addWidget(self.stack)
        self.pages = {}
        for key, label in PAGES:
            p = PAGE_CLASSES[key](self)
            wrap_long_labels(p)
            self.pages[key] = p
            self.stack.addWidget(p)
            self.picker.addItem(label.replace("…", "").replace("&&", "&"),
                                key)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        how = bb.addButton("How To…", QDialogButtonBox.HelpRole)
        how.clicked.connect(lambda _c=False: self.show_guide())
        walk = bb.addButton("Takeoff to Quote Walkthrough…",
                            QDialogButtonBox.HelpRole)
        walk.clicked.connect(lambda _c=False: self.show_walkthrough())
        lay.addWidget(bb)
        self.guide_windows = []
        self.picker.currentIndexChanged.connect(self._picked)
        for keys, step in (("Ctrl+PgDown", 1), ("Ctrl+PgUp", -1)):
            sc = QShortcut(QKeySequence(keys), self)
            sc.activated.connect(lambda st=step: self.step(st))
        self.go(start)

    def page(self, key):
        return self.pages[key]

    def _guide(self, title, text):
        g = GuideWindow(self, title, text)
        self.guide_windows.append(g)
        g.show()                                  # not modal: read and work
        return g

    def show_guide(self):
        from . import guides
        key = self.current_key()
        title, text = guides.guide(key)
        return self._guide(f"How to: {title}", text)

    def show_walkthrough(self):
        from . import guides
        return self._guide(*guides.walkthrough())

    def go(self, key):
        keys = [k for k, _l in PAGES]
        i = keys.index(key) if key in keys else 0
        self.picker.blockSignals(True)
        self.picker.setCurrentIndex(i)
        self.picker.blockSignals(False)
        self._picked(i)

    def current_key(self):
        return self.picker.currentData()

    def step(self, n):
        c = self.picker.count()
        self.picker.setCurrentIndex((self.picker.currentIndex() + n) % c)

    def _picked(self, i):
        if i < 0:
            return
        self.stack.setCurrentIndex(i)
        self._shown(i)

    def _shown(self, i):
        p = self.stack.widget(i)
        try:
            p.refresh()
        except Exception as e:                            # noqa: BLE001
            log.warning("estimating tool page failed", exc_info=True)
            p.msg.setText(str(e))


def open_tools(mw, key="check", focus=None, show=True):
    """focus=("equipment" | "property", id) selects that service record
    (Ctrl+K, Nov 4)."""
    global LAST
    v = getattr(mw, "_view", None)
    dlg = EstimatingTools(mw, v.doc if v else None, key)
    LAST = dlg
    if focus and key == "service":
        try:
            dlg.pages["service"].focus(*focus)
        except Exception:                                 # noqa: BLE001
            import logging
            logging.getLogger(__name__).debug("focus", exc_info=True)
    if show:
        dlg.exec()
    return dlg


def add_menu(mw, parent):
    sub = parent.addMenu(MENU_TITLE)
    for key, label in PAGES:
        mw._act(sub, label, None, lambda k=key: open_tools(mw, k), False)
    return sub
