"""Bid Build-up window (Estimate > Bid Build-up, or Create Proposal >
Pricing > Bid Build-up): every markup, margin by trade and front-loading."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFormLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from . import bidbuild, proposal
from .dmoney import c2 as _c2

BOND = [("none", "No bond"), ("auto", "Surety schedule (graduated)"),
        ("fixed", "Flat rate")]
KEYS = bidbuild.RATE_KEYS + ["bond", "bond_rate", "margins", "front_load",
                             "months", "discount", "retention",
                             "payment_days", "sov_front_load"]


def _m(v):
    return f"${v:,.0f}"


def _it(text, right=True):
    it = QTableWidgetItem(str(text))
    it.setFlags(it.flags() & ~Qt.ItemIsEditable)
    if right:
        it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
    return it


def _spin(val, hi=100.0, dec=2, suffix=" %"):
    s = QDoubleSpinBox()
    s.setRange(0, hi)
    s.setDecimals(dec)
    s.setSuffix(suffix)
    s.setValue(float(val or 0))
    return s


class BidBuildDialog(QDialog):
    def __init__(self, doc, parent=None, data=None, page=None):
        super().__init__(parent)
        self.setWindowTitle("Bid Build-up")
        self.resize(1050, 720)
        self.doc, self.page = doc, page
        self.data = dict(data if data is not None else proposal.read(doc))
        if not self.data:                    # no job open: proposal defaults
            self.data = {"overhead": 10.0, "profit": 10.0}
        d = self.data
        lay = QHBoxLayout(self)
        left = QWidget()
        f = QFormLayout(left)
        self.rate = {}
        labels = dict((k, l) for k, l, _b in bidbuild.STEPS)
        notes = {"gc": " (of direct)", "tax": " (of material)"}
        for k in bidbuild.RATE_KEYS:
            s = _spin(d.get(k))
            s.valueChanged.connect(self.refresh)
            self.rate[k] = s
            f.addRow(labels[k] + notes.get(k, "") + ":", s)
        self.bond = QComboBox()
        for k, label in BOND:
            self.bond.addItem(label, k)
        self.bond.setCurrentIndex(max(0, [k for k, _ in BOND].index(
            d.get("bond") or "none") if (d.get("bond") or "none") in
            dict(BOND) else 0))
        self.bond.currentIndexChanged.connect(self.refresh)
        f.addRow("Bond:", self.bond)
        self.bond_rate = _spin(d.get("bond_rate") or 1.0, 10)
        self.bond_rate.valueChanged.connect(self.refresh)
        f.addRow("Flat bond rate:", self.bond_rate)
        self.margins = QLineEdit(bidbuild.format_margins(
            bidbuild.parse_margins(d.get("margins") or {})))
        self.margins.setPlaceholderText("03 Concrete=14, 26 Electrical=6")
        self.margins.setToolTip("Extra margin % by trade, on top of profit. "
                                "A division number ('03=14') matches every "
                                "trade in that division.")
        self.margins.textChanged.connect(self.refresh)
        f.addRow("Trade margins:", self.margins)
        self.direct = _spin(0, 1e10, 0, "")
        self.direct.setPrefix("$ ")
        self.direct.setToolTip("Used only when the job has no assembly "
                               "takeoff - a quick bid from a direct cost")
        self.direct.valueChanged.connect(self.refresh)
        f.addRow("Direct cost (no takeoff):", self.direct)

        g = QGroupBox("Front-loading (cash flow)")
        gf = QFormLayout(g)
        self.fl = _spin(d.get("front_load") or 0.06, 0.49, 3, "")
        self.fl.setSingleStep(0.01)
        self.months = QSpinBox()
        self.months.setRange(1, 120)
        self.months.setValue(int(d.get("months") or 12))
        self.disc = _spin(d.get("discount") or 7.0, 50)
        self.ret = _spin(10.0 if d.get("retention") is None
                         else d.get("retention"), 50)
        self.pay = QSpinBox()
        self.pay.setRange(0, 180)
        self.pay.setSuffix(" days")
        self.pay.setValue(int(d.get("payment_days") or 30))
        for w, label in ((self.fl, "Factor"), (self.months, "Duration "
                         "(months)"), (self.disc, "Discount rate / yr"),
                         (self.ret, "Retention"), (self.pay, "Paid after")):
            w.valueChanged.connect(self.refresh)
            gf.addRow(label + ":", w)
        self.use_fl = QCheckBox("Use front-loaded values when building the "
                                "Schedule of Values")
        self.use_fl.setChecked(bool(d.get("sov_front_load")))
        gf.addRow(self.use_fl)
        self.fl_text = QLabel("")
        self.fl_text.setWordWrap(True)
        gf.addRow(self.fl_text)
        f.addRow(g)
        lay.addWidget(left)

        right = QVBoxLayout()
        self.head = QLabel("")
        self.head.setTextFormat(Qt.RichText)
        right.addWidget(self.head)
        self.steps = QTableWidget(0, 4)
        self.steps.setHorizontalHeaderLabels(["Step", "Rate", "Amount",
                                              "Running total"])
        self.steps.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch)
        right.addWidget(self.steps, 1)
        right.addWidget(QLabel("<b>Margin by trade</b> (markup allocated "
                               "line by line, so the trades add up to the "
                               "bid)"))
        self.trades = QTableWidget(0, 6)
        self.trades.setHorizontalHeaderLabels(
            ["Trade", "Direct", "Share", "Extra margin", "Price", "Margin"])
        self.trades.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch)
        right.addWidget(self.trades, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        right.addWidget(bb)
        lay.addLayout(right, 2)
        self.result = None
        self.refresh()

    def values(self):
        d = {k: s.value() for k, s in self.rate.items()}
        d["bond"] = self.bond.currentData()
        d["bond_rate"] = self.bond_rate.value()
        try:
            d["margins"] = bidbuild.parse_margins(self.margins.text())
        except ValueError:
            d["margins"] = bidbuild.parse_margins(self.data.get("margins")
                                                  or {})
        d.update(front_load=self.fl.value(), months=self.months.value(),
                 discount=self.disc.value(), retention=self.ret.value(),
                 payment_days=self.pay.value(),
                 sov_front_load=self.use_fl.isChecked())
        return d

    def compute(self):
        data = dict(self.data, **self.values(), detail="trade")
        p = proposal.price(self.doc, data, self.page) if self.doc else None
        if p and p["lines"]:
            return p, [ln["price"] for ln in p["lines"]]
        if self.direct.value() > 0:
            b = bidbuild.build([{"trade": "Direct cost",
                                 "direct": self.direct.value(),
                                 "material": 0.0}], data)
            b["lines"] = [{"price": w["price"]} for w in b["lines"]]
            return b, [w["price"] for w in b["lines"]]
        return None, []

    def refresh(self, *_):
        self.bond_rate.setEnabled(self.bond.currentData() == "fixed")
        bad = False
        try:
            bidbuild.parse_margins(self.margins.text())
        except ValueError:
            bad = True
        self.margins.setStyleSheet("background:#ffd6d6" if bad else "")
        p, values = self.compute()
        self.result = p
        if not p:
            self.head.setText("<b>No assembly takeoff yet.</b> Take off with "
                              "assemblies, or enter a direct cost.")
            self.steps.setRowCount(0)
            self.trades.setRowCount(0)
            self.fl_text.setText("")
            return None
        self.head.setText(
            f"Direct cost <b>{_m(p['direct'])}</b> &nbsp; → &nbsp; Bid "
            f"<b>{_m(p['total'])}</b> &nbsp; (markup "
            f"{_c2((p['total'] - p['direct']) / p['direct'] * 100 if p['direct'] else 0):.2f}"
            f"% of direct)")
        st = p["steps"]
        self.steps.setRowCount(len(st) + 2)
        self.steps.setItem(0, 0, _it("Direct cost", False))
        self.steps.setItem(0, 3, _it(_m(p["direct"])))
        for r, s in enumerate(st, 1):
            for c, v in enumerate((s["label"], f"{_c2(s['rate']):.2f}%",
                                   _m(s["amount"]), _m(s["running"]))):
                self.steps.setItem(r, c, _it(v, c > 0))
        self.steps.setItem(len(st) + 1, 0, _it("BID", False))
        self.steps.setItem(len(st) + 1, 3, _it(_m(p["total"])))
        bt = p["by_trade"]
        self.trades.setRowCount(len(bt))
        for r, t in enumerate(bt):
            for c, v in enumerate((t["trade"], _m(t["direct"]),
                                   f"{t['share_pct']:.1f}%",
                                   f"{t['extra_margin_pct']:g}%",
                                   _m(t["price"]), f"{t['margin_pct']:.1f}%")):
                self.trades.setItem(r, c, _it(v, c > 0))
        if self.fl.value() > 0 and len(values) > 1:
            fl = bidbuild.front_load(values, self.fl.value(),
                                     self.months.value(), self.disc.value(),
                                     self.ret.value(), self.pay.value())
            warn = (" <span style='color:#b00'>Lines move more than 10% - "
                    "an owner can reject a materially unbalanced bid.</span>"
                    if fl["max_change_pct"] > 10 else "")
            self.fl_text.setText(
                f"Cash flow value {_m(fl['base_npv'])} → "
                f"{_m(fl['loaded_npv'])}: <b>{_m(fl['improvement'])} "
                f"({_c2(fl['improvement_pct']):.2f}%)</b> better. Total bid "
                f"unchanged; lines move up to {fl['max_change_pct']:.1f}%."
                + warn)
        else:
            self.fl_text.setText("Needs 2 or more SOV lines (trades)."
                                 if self.fl.value() > 0 else "")
        return p

    def accept(self):
        self.data.update(self.values())
        super().accept()
