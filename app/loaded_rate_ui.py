"""Loaded Rate Builder: the true hourly cost of each trade from its wage
(fringes, payroll burden, workers' comp, liability, small tools,
supervision, per diem), using your loaded_rate engine."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFormLayout, QHBoxLayout, QHeaderView, QLabel, QMessageBox, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout)

from . import labor
from . import loaded_rate as eng

# QuantiSheet trade -> engine preset (trade family the WC class and union
# fringe ratio come from)
PRESET_OF = {
    "Carpenter": "Carpenter", "Helper": "Apprentice", "Laborer": "Laborer",
    "Electrician": "Electrician", "Apprentice": "Apprentice",
    "Plumber": "Plumber", "Plumber Helper": "Apprentice",
    "Sprinkler Fitter": "Pipefitter", "Mason": "Mason",
    "Mason Tender": "Laborer", "Cement Finisher": "Cement Mason",
    "Drywall Hanger": "Drywall Hanger", "Taper": "Drywall Hanger",
    "Ironworker": "Ironworker", "Rodman": "Ironworker",
    "Operator": "Operating Engineer", "Painter": "Painter",
    "Roofer": "Roofer", "Sheet Metal Worker": "Sheet Metal",
    "HVAC Mechanic": "Pipefitter", "Glazier": "Glazier",
    "Insulator": "Carpenter", "Tile Setter": "Tile Setter",
    "Floor Layer": "Tile Setter", "Elevator Constructor": "Electrician",
    "Millwright": "Pipefitter", "Welder": "Ironworker",
    "Pipelayer": "Laborer", "Paving Operator": "Operating Engineer",
    "Truck Driver": "Teamster", "Pile Driver": "Ironworker",
    "Low Voltage Tech": "Electrician", "Telecom Tech": "Electrician",
    "Abatement Worker": "Laborer", "Landscaper": "Laborer",
    "Fence Erector": "Laborer", "Superintendent": "General Foreman",
    "Project Manager": "General Foreman", "Foreman": "Foreman",
}

# workers' comp cost relative to the national median (Oregon DCBS 2024
# premium index ranking, all classes)
STATE_WC = {"South Carolina": 0.94, "North Carolina": 0.87, "Florida": 0.92,
            "Virginia": 0.67, "Georgia": 1.00, "Tennessee": 0.73,
            "Pennsylvania": 1.05, "New Jersey": 1.98}
OPEN_SHOP_FRINGE = 0.25    # health + retirement as a share of wage (BLS ECEC)

COLS = ["Trade", "Preset", "Base wage", "Fringes", "WC %", "Loaded $/hr",
        "Rate now", "Change"]


def _cell(text, edit=False, right=True):
    it = QTableWidgetItem(text)
    if not edit:
        it.setFlags(it.flags() & ~Qt.ItemIsEditable)
    if right:
        it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
    return it


class LoadedRateDialog(QDialog):
    """`rates` = the trade rates in use now ({trade: $/hr}); `burden` =
    the burden already in them (to back out the base wage); `region`
    picks the state's workers' comp level."""

    def __init__(self, rates, parent=None, region="national", burden=0.44,
                 book=None, as_of=None):
        super().__init__(parent)
        self.setWindowTitle(f"Loaded Rate Builder - {region}")
        self.resize(1050, 680)
        self.now = dict(rates)
        self.region, self.burden_in, self.book = region, burden, book
        self.as_of = as_of
        self.result_rates = None
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(
            "Builds each trade's true hourly cost from its wage. Base wages "
            "start from the rates in use (with their burden taken back out);"
            " edit any cell. Workers' comp is the trade's class rate scaled "
            f"to {region}."))
        form = QFormLayout()
        row = QHBoxLayout()
        self.spins = {}
        for key, label, val, hi in (
                ("burden", "Payroll burden %", eng.DEFAULT_BURDEN_PCT, 60),
                ("gl", "General liability %", eng.DEFAULT_GL_PCT, 20),
                ("tools", "Small tools %", eng.DEFAULT_TOOLS_PCT, 20),
                ("super", "Supervision %", eng.DEFAULT_SUPER_PCT, 40),
                ("per_diem", "Per diem $/hr", 0.0, 100)):
            sb = QDoubleSpinBox()
            sb.setRange(0, hi)
            sb.setDecimals(2)
            sb.setValue(val)
            sb.valueChanged.connect(self.recalc)
            row.addWidget(QLabel(label))
            row.addWidget(sb)
            self.spins[key] = sb
        form.addRow(row)
        row = QHBoxLayout()
        self.union = QCheckBox("Union scale fringes (trade preset ratio)")
        self.union.toggled.connect(self.reset)
        row.addWidget(self.union)
        row.addWidget(QLabel("Conditions:"))
        self.conds = {}
        for name in ("height", "night", "winter", "occupied", "retrofit"):
            cb = QCheckBox(f"{name} x{eng.CONDITIONS[name][0]:g}")
            cb.setToolTip(eng.CONDITIONS[name][1])
            cb.toggled.connect(self.recalc)
            row.addWidget(cb)
            self.conds[name] = cb
        row.addStretch()
        form.addRow(row)
        lay.addLayout(form)
        self.table = QTableWidget(0, len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch)
        self.table.itemChanged.connect(lambda *_: self.recalc())
        lay.addWidget(self.table, 1)
        self.summary = QLabel("")
        self.summary.setWordWrap(True)
        lay.addWidget(self.summary)
        bb = QDialogButtonBox(QDialogButtonBox.Cancel)
        self.use = bb.addButton("Use These Rates", QDialogButtonBox.AcceptRole)
        self.use.setToolTip("Loaded rates (without the conditions, which "
                            "the labor adjustments apply to hours)")
        self.use.clicked.connect(self._use)
        if book:
            b = bb.addButton(f"Save to {book} ({region})",
                             QDialogButtonBox.ActionRole)
            b.clicked.connect(self.save_to_book)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.reset()

    # ---- rows ------------------------------------------------------------------
    def reset(self, *_):
        wc_rel = STATE_WC.get(self.region, 1.0)
        t = self.table
        t.blockSignals(True)
        trades = sorted(self.now)
        t.setRowCount(len(trades))
        for r, trade in enumerate(trades):
            pname = PRESET_OF.get(trade, "Laborer")
            p = eng.PRESETS[pname]
            base = self.now[trade] / (1 + self.burden_in) if self.now[trade] \
                else p.base
            fr = base * (p.fringes / p.base) if self.union.isChecked() else \
                base * OPEN_SHOP_FRINGE
            t.setItem(r, 0, _cell(trade, right=False))
            box = QComboBox()
            box.addItems(sorted(eng.PRESETS))
            box.setCurrentText(pname)
            box.currentTextChanged.connect(
                lambda _t, row=r: self._preset_changed(row))
            t.setCellWidget(r, 1, box)
            t.setItem(r, 2, _cell(f"{base:.2f}", True))
            t.setItem(r, 3, _cell(f"{fr:.2f}", True))
            t.setItem(r, 4, _cell(f"{p.wc * wc_rel:.2f}", True))
            for c in (5, 6, 7):
                t.setItem(r, c, _cell(""))
        t.blockSignals(False)
        self.recalc()

    def _preset_changed(self, row):
        p = eng.PRESETS[self.table.cellWidget(row, 1).currentText()]
        self.table.item(row, 4).setText(
            f"{p.wc * STATE_WC.get(self.region, 1.0):.2f}")

    def _num(self, r, c):
        try:
            return float(self.table.item(r, c).text().replace("$", "")
                         .replace(",", ""))
        except (AttributeError, ValueError):
            return 0.0

    def rate_for(self, r, conditions=True):
        s = self.spins
        conds = {n: eng.CONDITIONS[n][0] for n, cb in self.conds.items()
                 if cb.isChecked()} if conditions else {}
        lr = eng.LoadedRate(
            trade=self.table.item(r, 0).text(), base=self._num(r, 2),
            fringes=self._num(r, 3), burden_pct=s["burden"].value(),
            wc_pct=self._num(r, 4), gl_pct=s["gl"].value(),
            tools_pct=s["tools"].value(), super_pct=s["super"].value(),
            per_diem=s["per_diem"].value(), conditions=conds)
        return lr.breakdown()

    def recalc(self, *_):
        t = self.table
        t.blockSignals(True)
        tot_now = tot_new = 0.0
        for r in range(t.rowCount()):
            b = self.rate_for(r, conditions=False)
            eff = self.rate_for(r)["effective_rate"]
            now = self.now.get(t.item(r, 0).text(), 0.0)
            t.item(r, 5).setText(f"{b['loaded_rate']:.2f}" + (
                f"  ({eff:.2f} with conditions)" if eff != b["loaded_rate"]
                else ""))
            t.item(r, 6).setText(f"{now:.2f}")
            t.item(r, 7).setText(f"{(b['loaded_rate'] - now) / now * 100:+.0f}%"
                                 if now else "")
            tot_now += now
            tot_new += b["loaded_rate"]
        t.blockSignals(False)
        if t.rowCount():
            self.summary.setText(
                f"Average trade rate {tot_new / t.rowCount():.2f} $/hr loaded "
                f"vs {tot_now / t.rowCount():.2f} now"
                + (f" ({(tot_new - tot_now) / tot_now * 100:+.0f}%)"
                   if tot_now else "") + ". Conditions "
                "are shown for reference; in an estimate they're applied to "
                "hours by the labor adjustments, so they aren't saved into "
                "the rates.")

    def rates(self):
        return {self.table.item(r, 0).text():
                round(self.rate_for(r, conditions=False)["loaded_rate"], 2)
                for r in range(self.table.rowCount())}

    def _use(self):
        self.result_rates = self.rates()
        self.accept()

    def save_to_book(self):
        from . import costbook, pricedb
        # the rates shown are escalated to the pricing date; the book keeps
        # them at its own date
        esc = 1.0
        b = costbook.find(self.book)
        if b is not None:
            esc = b.factor("national", self.as_of) / float(
                b.index.get("national", 1.0) or 1.0)
        try:
            n = pricedb.update_rates(
                self.book, {self.region: {t: round(v / esc, 4) for t, v in
                                          self.rates().items()}},
                note="Loaded Rate Builder")
        except pricedb.PriceDBError as e:
            QMessageBox.warning(self, "Loaded Rates", str(e))
            return None
        QMessageBox.information(self, "Loaded Rates",
                                f"Saved {n} rate change(s) to {self.book} "
                                f"({self.region}).")
        self.result_rates = self.rates()
        self.accept()
        return n


def open_for_job(doc, parent=None):
    """Builder for the job's book and region (or your default rates)."""
    from . import assemblies
    job = assemblies.read_job(doc)
    book, region, as_of = assemblies.job_costbook(job)
    if book is not None and book.rates:
        reg = region or book.region
        rates = book.labor_rates(reg, as_of)
        burden = float(((book.regions or {}).get(reg) or {}).get(
            "burden", 0.44))
        name = book.name if str(book.path or "").startswith("db:") else None
        return LoadedRateDialog(rates, parent, reg, burden, name, as_of)
    return LoadedRateDialog(labor.rates(), parent, "national", 0.44)
