"""Bid Leveling window (Takeoff > Bid Leveling, or Bid Tabs > Level)."""
import os
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFileDialog, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QMenu,
    QMessageBox, QPushButton, QSpinBox, QSplitter, QTableWidget,
    QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

from . import theme as _theme
from . import leveling
from .dmoney import c2 as _c2

COLORS = {"omit": QColor(255, 205, 205), "incl": QColor(225, 235, 255),
          "carry": QColor(255, 225, 170), "buyin": QColor(200, 230, 255),
          "outlier": QColor(240, 210, 255), "plug": QColor(205, 240, 205)}


def _it(text, right=False):
    it = QTableWidgetItem(str(text))
    it.setFlags(it.flags() & ~Qt.ItemIsEditable)
    if right:
        it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
    return it


class LevelingDialog(QDialog):
    def __init__(self, parent=None, project=None):
        super().__init__(parent)
        self.setWindowTitle("Bid Leveling")
        self.resize(1300, 800)
        self.bids = None
        self.res = None
        # plugs and adjustments ([{bidder, item, kind, amount, note}]);
        # on_plugs(list) is told every change (a bid package saves them)
        self.plugs = []
        self.on_plugs = None
        lay = QVBoxLayout(self)
        row = QHBoxLayout()
        row.addWidget(QLabel("Bids:"))
        self.project = QComboBox()
        self._load_projects(project)
        row.addWidget(self.project, 1)
        b = QPushButton("Use Files…")
        b.setToolTip("One bid tab per bidder (or one file with a bidder "
                     "column) - CSV, Excel or PDF")
        b.clicked.connect(lambda: self.use_files())
        row.addWidget(b)
        b = QPushButton("Sub Proposals (PDF)…")
        b.setToolTip("Subs' own quote PDFs (not bid tabs): line items, "
                     "lump sums, totals, exclusions and inclusions are read "
                     "from the text")
        b.clicked.connect(lambda: self.use_proposals())
        row.addWidget(b)
        lay.addLayout(row)
        row = QHBoxLayout()
        self.carry = self._spin(row, "Carry at ≥ median x", 1.5, 1.0, 5.0)
        self.buyin = self._spin(row, "Buy-in at ≤ median x", 0.65, 0.05, 1.0)
        self.z = self._spin(row, "Outlier (robust z) ≥", 3.5, 1.0, 10.0)
        row.addWidget(QLabel("Ignore items bid by fewer than"))
        self.minb = QSpinBox()
        self.minb.setRange(1, 50)
        self.minb.setValue(2)
        row.addWidget(self.minb)
        self.use_vocab = QCheckBox("Align by vocabulary")
        self.use_vocab.setChecked(True)
        row.addWidget(self.use_vocab)
        go = QPushButton("Level")
        go.setDefault(True)
        go.clicked.connect(lambda: self.run())
        row.addWidget(go)
        lay.addLayout(row)
        self.risk = QLabel("")
        self.risk.setWordWrap(True)
        lay.addWidget(self.risk)
        tabs = QTabWidget()
        lay.addWidget(tabs, 1)
        self.summary = QTableWidget(0, 10)
        self.summary.setHorizontalHeaderLabels(
            ["Bidder", "Base bid", "Omissions", "Added (median / plugs)",
             "Adjustments", "Leveled", "Carries", "Buy-ins", "Outliers",
             "Pattern"])
        self.summary.setContextMenuPolicy(Qt.CustomContextMenu)
        self.summary.customContextMenuRequested.connect(self._summary_menu)
        self.summary.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch)
        tabs.addTab(self.summary, "Leveled Totals")
        self.matrix = QTableWidget()
        self.matrix.setContextMenuPolicy(Qt.CustomContextMenu)
        self.matrix.customContextMenuRequested.connect(self._matrix_menu)
        tabs.addTab(self.matrix, "Matrix")
        self.gaps = QTableWidget(0, 6)
        self.gaps.setHorizontalHeaderLabels(["Description", "Unit", "Qty",
                                             "Median", "Omitted by",
                                             "Value"])
        self.gaps.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch)
        tabs.addTab(self.gaps, "Scope Gaps")
        pw = QWidget()
        pv = QVBoxLayout(pw)
        self.plug_table = QTableWidget(0, 5)
        self.plug_table.setHorizontalHeaderLabels(["Bidder", "Item", "Kind",
                                                   "Amount", "Why"])
        self.plug_table.horizontalHeader().setSectionResizeMode(
            4, QHeaderView.Stretch)
        pv.addWidget(self.plug_table, 1)
        pr = QHBoxLayout()
        rm = QPushButton("Remove Selected")
        rm.clicked.connect(lambda: self.remove_plug(
            self.plug_table.currentRow()))
        pr.addWidget(rm)
        sg = QPushButton("Suggest Plugs…")
        sg.setToolTip("For each item a bidder left out: the closest past "
                      "bid in your price database (escalated median), else "
                      "this job's median - you accept them")
        sg.clicked.connect(lambda: self.suggest_plugs())
        pr.addWidget(sg)
        pr.addWidget(QLabel("Right-click a matrix cell to plug a missing "
                            "item, mark it included or fix a price; "
                            "right-click a bidder on Leveled Totals for an "
                            "adjustment."))
        pr.addStretch()
        pv.addLayout(pr)
        tabs.addTab(pw, "Plugs && Adjustments")
        legend = QLabel("Matrix: <span style='background:#ffcdcd'>&nbsp;OMIT"
                        "&nbsp;</span> missing scope, <span style='background:"
                        "#e1ebff'>&nbsp;INCL&nbsp;</span> included elsewhere, "
                        "<span style='background:#ffe1aa'>&nbsp;^&nbsp;</span> "
                        "carry, <span style='background:#c8e6ff'>&nbsp;v&nbsp;"
                        "</span> buy-in, <span style='background:#f0d2ff'>"
                        "&nbsp;*&nbsp;</span> outlier, <span style='background:"
                        "#cdf0cd'>&nbsp;PLUG&nbsp;</span> your plug. Leveled ="
                        " base bid + omitted items at the median (or your "
                        "plug) + adjustments.")
        lay.addWidget(legend)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        b = bb.addButton("Export to Excel…", QDialogButtonBox.ActionRole)
        b.clicked.connect(lambda: self.export())
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _spin(self, row, label, val, lo, hi):
        row.addWidget(QLabel(label))
        sb = QDoubleSpinBox()
        sb.setRange(lo, hi)
        sb.setDecimals(2)
        sb.setSingleStep(0.05)
        sb.setValue(val)
        row.addWidget(sb)
        return sb

    def _load_projects(self, select=None):
        from . import bidtab
        self.project.clear()
        try:
            projs = [p for p in bidtab.projects() if p["bidders"] >= 2]
        except Exception:
            projs = []
        for p in projs:
            self.project.addItem(f"{p['name']} ({p['bidders']} bidders, "
                                 f"{p['bid_date']})", p["id"])
        if select is not None:
            i = self.project.findData(select)
            self.project.setCurrentIndex(max(0, i))

    def use_files(self, paths=None, bidder_column=False):
        if paths is None:
            paths, _ = QFileDialog.getOpenFileNames(
                self, "Bids to Level", "", "Bid tabs (*.csv *.tsv *.txt "
                "*.xlsx *.pdf)")
        if not paths:
            return None
        try:
            self.bids = leveling.from_files(paths, bidder_column)
        except Exception as e:
            QMessageBox.warning(self, "Bid Leveling", str(e))
            return None
        if len(self.bids) == 1 and len(paths) == 1:
            self.bids = leveling.from_files(paths, True)   # bidder column
        self.project.addItem(f"Files: {len(paths)} file(s), "
                             f"{len(self.bids)} bidders", "files")
        self.project.setCurrentIndex(self.project.count() - 1)
        return self.run()

    def use_proposals(self, paths=None):
        """Level subs' PDF proposals (Chief's v21). Lines that don't add up
        or money that couldn't be read are reported, never guessed."""
        from . import proposal_level
        if paths is None:
            paths, _ = QFileDialog.getOpenFileNames(
                self, "Sub Proposals to Level", "", "PDF proposals (*.pdf)")
        if not paths:
            return None
        props, notes = [], []
        for p in paths:
            try:
                pr = proposal_level.parse(p)
            except Exception as e:
                notes.append(f"{os.path.basename(p)}: couldn't read it "
                             f"({e}).")
                continue
            if not pr.get("lines"):
                notes.append(f"{os.path.basename(p)}: no priced lines found"
                             " (a scanned quote needs Make Searchable "
                             "first).")
                continue
            props.append(pr)
            c = proposal_level.check(pr)
            if c:
                notes.append(f"{pr['bidder']}: {c}")
        self.proposals = props
        if len(props) < 2:
            QMessageBox.information(
                self, "Bid Leveling", "Need 2 or more readable proposals."
                + ("\n\n" + "\n".join(notes) if notes else ""))
            return None
        self.bids = proposal_level.to_bids(props)
        self.project.addItem(f"Proposals: {len(props)} PDF(s)", "files")
        self.project.setCurrentIndex(self.project.count() - 1)
        res = self.run()
        if notes:
            QMessageBox.information(self, "Bid Leveling - check these",
                                    "\n".join(notes))
        return res

    def suggest_plugs(self, accept=None):
        """Plugs for omitted items from past bids (or this job's median);
        shown first, added only when accepted."""
        from . import proposal_level
        if self.res is None:
            QMessageBox.information(self, "Bid Leveling", "Level the bids "
                                    "first.")
            return []
        sug = proposal_level.suggest_plugs(self.res)
        if not sug:
            QMessageBox.information(self, "Bid Leveling", "Nothing is "
                                    "missing that a plug could fill.")
            return []
        if accept is None:
            lines = [f"{x['bidder']}: {x['item']} {x['qty']:g} {x['unit']} "
                     f"x ${_c2(x['unit_price']):,.2f} = ${_c2(x['amount']):,.2f} "
                     f"({x['source']})" for x in sug[:25]]
            accept = QMessageBox.question(
                self, "Suggest Plugs", f"Add these {len(sug)} plug(s)?\n\n"
                + "\n".join(lines) + ("\n…" if len(sug) > 25 else "")) == \
                QMessageBox.Yes
        if not accept:
            return []
        for x in proposal_level.as_plugs(sug):
            self.add_plug(x["bidder"], x["item"], x["kind"], x["amount"],
                          x["note"])
        self.run()
        return sug

    def run(self):
        src = self.project.currentData()
        if src is None:
            QMessageBox.information(self, "Bid Leveling", "Import a bid tab "
                                    "with 2 or more bidders, or Use Files.")
            return None
        bids = self.bids if src == "files" else leveling.from_project(src)
        try:
            self.res = leveling.run(
                bids, self.carry.value(), self.buyin.value(), self.z.value(),
                self.minb.value(), use_vocab=self.use_vocab.isChecked(),
                plugs=self.plugs)
        except ValueError as e:
            QMessageBox.warning(self, "Bid Leveling", str(e))
            return None
        self.fill()
        return self.res

    def fill(self):
        res = self.res
        self.risk.setText(
            f"<span style='color:#b00'><b>AWARD RISK:</b> {res['risk']}"
            "</span>" if res["risk"] else
            f"Low bidder on base bid is also low leveled: "
            f"<b>{res['results'][0]['bidder']}</b>.")
        t = self.summary
        t.setRowCount(len(res["results"]))
        for r, x in enumerate(res["results"]):
            adj = x.get("adjust", 0.0)
            for c, v in enumerate((x["bidder"], f"${x['base']:,.0f}",
                                   x["omissions"], f"${x['added']:,.0f}",
                                   f"{'+' if adj > 0 else ''}${adj:,.0f}"
                                   if adj else "",
                                   f"${x['leveled']:,.0f}", x["carries"],
                                   x["buyins"], x["outliers"], x["flag"])):
                it = _it(v, c in range(1, 9))
                if x.get("plug_notes"):
                    it.setToolTip("\n".join(x["plug_notes"]))
                t.setItem(r, c, it)
        b = res["bidders"]
        m = self.matrix
        m.setColumnCount(5 + len(b))
        m.setHorizontalHeaderLabels(["Description", "Unit", "Qty", "Median",
                                     "Spread %"] + b)
        m.setRowCount(len(res["items"]))
        for r, it in enumerate(res["items"]):
            for c, v in enumerate((it.desc, it.unit, f"{it.qty:g}",
                                   f"{_c2(it.median):,.2f}", f"{it.spread:.0f}")):
                m.setItem(r, c, _it(v, c >= 2))
            for k, bd in enumerate(b):
                text, mark = leveling.cell(res, it, bd)
                cell = _it(text + {"carry": " ^", "buyin": " v",
                                   "outlier": " *"}.get(mark, ""), True)
                if mark:
                    _theme.tint(cell, COLORS[mark])
                m.setItem(r, 5 + k, cell)
        m.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        g = self.gaps
        g.setRowCount(len(res["gaps"]))
        for r, it in enumerate(res["gaps"]):
            om = [x for x in b if x not in it.prices and x not in it.included]
            for c, v in enumerate((it.desc, it.unit, f"{it.qty:g}",
                                   f"{_c2(it.median):,.2f}", ", ".join(om),
                                   f"${it.median * it.qty:,.0f}")):
                g.setItem(r, c, _it(v, c in (2, 3, 5)))

        pt = self.plug_table
        pt.setRowCount(len(self.plugs))
        for r, p in enumerate(self.plugs):
            amt = leveling._num(p.get("amount"))
            for c, v in enumerate((p.get("bidder", ""), p.get("item", ""),
                                   p.get("kind", ""),
                                   "" if amt is None else f"{_c2(amt):,.2f}",
                                   p.get("note", ""))):
                pt.setItem(r, c, _it(v, c == 3))

    # ---------------------------------------------------------- plugs
    def _changed(self):
        if self.on_plugs:
            self.on_plugs([dict(p) for p in self.plugs])
        self.run()

    def add_plug(self, bidder, item, kind, amount=None, note=""):
        # one plug per bidder + item (adjustments can repeat)
        if kind != "Adjustment":
            self.plugs = [p for p in self.plugs if not (
                p.get("bidder") == bidder and p.get("kind") != "Adjustment"
                and str(p.get("item")) == str(item))]
        self.plugs.append({"bidder": bidder, "item": str(item or ""),
                           "kind": kind, "amount": amount, "note": note})
        self._changed()
        return self.plugs[-1]

    def remove_plug(self, index):
        if 0 <= index < len(self.plugs):
            self.plugs.pop(index)
            self._changed()

    def _item_ref(self, it):
        return it.item_no or it.desc

    def _matrix_menu(self, pos):
        if not self.res:
            return
        idx = self.matrix.indexAt(pos)
        r, c = idx.row(), idx.column()
        b = self.res["bidders"]
        if r < 0 or c < 5 or c - 5 >= len(b):
            return
        it, bidder = self.res["items"][r], b[c - 5]
        ref = self._item_ref(it)
        m = QMenu(self)
        if bidder not in it.prices:
            m.addAction(f"Plug a number for {bidder}…",
                        lambda: self._ask_plug(bidder, it, "Plug"))
            m.addAction(f"{bidder} included it in their number",
                        lambda: self.add_plug(bidder, ref, "Included"))
        else:
            m.addAction(f"Correct {bidder}'s unit price…",
                        lambda: self._ask_plug(bidder, it, "Override"))
        if leveling.plug_for(self.res, it, bidder):
            m.addAction("Clear plug", lambda: self._clear(bidder, ref))
        m.exec(self.matrix.viewport().mapToGlobal(pos))

    def _ask_plug(self, bidder, it, kind):
        if kind == "Plug":
            label = (f"Your number for {it.desc} ({it.qty:g} {it.unit}) "
                     f"from {bidder} - total $")
            start = it.median * it.qty
        else:
            label = f"{bidder}'s corrected unit price for {it.desc} - $"
            start = it.prices.get(bidder, it.median)
        val, ok = QInputDialog.getDouble(self, "Bid Leveling", label, start,
                                         -1e12, 1e12, 2)
        if not ok:
            return None
        note, _ok = QInputDialog.getText(self, "Bid Leveling", "Why "
                                         "(optional)")
        return self.add_plug(bidder, self._item_ref(it), kind, val,
                             note or "")

    def _clear(self, bidder, ref):
        self.plugs = [p for p in self.plugs if not (
            p.get("bidder") == bidder and p.get("kind") != "Adjustment"
            and str(p.get("item")) == str(ref))]
        self._changed()

    def _summary_menu(self, pos):
        if not self.res:
            return
        r = self.summary.indexAt(pos).row()
        if r < 0:
            return
        bidder = self.res["results"][r]["bidder"]
        m = QMenu(self)
        m.addAction(f"Add an adjustment for {bidder}…",
                    lambda: self._ask_adjust(bidder))
        m.exec(self.summary.viewport().mapToGlobal(pos))

    def _ask_adjust(self, bidder):
        val, ok = QInputDialog.getDouble(
            self, "Bid Leveling", f"Add to {bidder}'s leveled number "
            "(negative takes off) - $", 0, -1e12, 1e12, 2)
        if not ok or not val:
            return None
        note, _ok = QInputDialog.getText(self, "Bid Leveling",
                                         "What for (e.g. excludes bond)")
        return self.add_plug(bidder, "", "Adjustment", val, note or "")

    def export(self, path=None):
        if not self.res:
            return None
        if path is None:
            from .reportname import report_file_name
            src = self.project.currentData()
            proj = "" if src in (None, "files") else \
                self.project.currentText().rsplit(" (", 1)[0]
            path, _ = QFileDialog.getSaveFileName(
                self, "Export Bid Leveling",
                report_file_name("Bid Leveling", proj, ext=".xlsx"),
                "Excel (*.xlsx)")
        if not path:
            return None
        return leveling.export_xlsx(self.res, path)
