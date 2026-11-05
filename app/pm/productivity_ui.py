"""The production-rate table editor (Build From Plans > Production Rates…):
one row per activity family - unit, rate per crew-day, crews, minimum and
maximum days, note - plus the quantity assumptions. Saved to
productivity.json in the settings folder; Reset to defaults puts the
built-in (assumed) values back."""
import re

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QDialogButtonBox,
                               QHeaderView, QLabel, QMessageBox, QPushButton,
                               QTableWidget, QTableWidgetItem, QVBoxLayout)

from . import productivity as prod

COLS = ["Family", "Unit", "Rate / crew-day", "Crews", "Min days",
        "Max days", "Note"]
C_NAME, C_UNIT, C_RATE, C_CREWS, C_MIN, C_MAX, C_NOTE = range(7)
_NUM = {C_RATE: "rate", C_CREWS: "crews", C_MIN: "min", C_MAX: "max"}


def _g(v):
    return f"{v:g}" if isinstance(v, (int, float)) else str(v)


# what each fallback quantity (a family's "qty") is measured from, when
# nothing was taken off - see productivity.estimates()
QTY_FROM = {
    "floor": "the floor area read from the plans (room tags)",
    "footprint": "the footprint = floor area / levels",
    "perimeter": "the building perimeter, estimated as a rectangle of the "
                 "footprint (Footprint shape L:W)",
    "roof_sq": "the roof area = footprint (1 SQ = 100 SF)",
    "wall_sf": "the exterior wall area = perimeter x Story height x levels",
    "site_sf": "the site area = footprint x Site area factor",
    "site_perimeter": "the site perimeter, estimated from the site area",
    "board_sf": "the finished area (else the floor area) x SF of drywall per SF",
    "paint_sf": "the finished area (else the floor area) x SF painted per SF",
    "ceiling_sf": "the finished area (else the floor area) x SF of ceiling per SF",
    "glazing_sf": "the exterior wall area x Share that is glazing",
    "overhead_doors": "the overhead doors in a generated set's door schedule or a takeoff count (none counted: no row)",
    "doors": "the door schedule in a generated set, else the finished area (else the floor area) / SF per door",
    "partition_lf": "the finished area (else the floor area) x LF of partition per SF",
    "paving_sy": "the paved area = footprint x Paved area factor "
                 "(1 SY = 9 SF)",
    "landscape_sf": "the landscaped area = footprint x Landscaped area "
                    "factor",
    "pipe_lf": "the pipe taken off, else about one building perimeter of "
               "service runs",
}
_MEASURE = {"area": "area", "length": "length", "count": "count"}
_UNIT_WORD = {"SF": "square feet", "LF": "linear feet", "SQ": "roofing "
              "squares, 100 SF each", "SY": "square yards, 9 SF each",
              "EA": "each"}


def _takeoff_words(rx):
    """r"clearing|grubbing" -> "clearing, grubbing" (readable names)."""
    words = []
    for alt in str(rx).split("|"):
        w = re.sub(r"\(\?[!=].*?\)", "", alt)
        w = w.replace("\\b", "").replace("\\s*", " ").replace("\\s", " ")
        w = re.sub(r"[\\?^$*+()]", "", w).strip()
        if w and w.lower() not in (x.lower() for x in words):
            words.append(w)
    return ", ".join(words)


def family_tooltip(fam):
    """The row's tooltip: unit, what the quantity is measured from and what
    min / max days mean."""
    unit = fam.get("unit", "")
    lines = [f"{fam.get('name', '')}",
             f"Unit: {unit} of {fam.get('of', '')}"
             + (f" ({_UNIT_WORD[unit]})" if unit in _UNIT_WORD else "")
             + f"; rate = {unit} one crew does per working day."]
    src = QTY_FROM.get(fam.get("qty"), str(fam.get("qty") or "an estimate"))
    if fam.get("takeoff"):
        each = f" (or a count of them, {fam['per_each']:g} per {unit})" \
            if fam.get("per_each") else ""
        lines.append("Quantity: measured from the takeoff - "
                     f"{_MEASURE.get(fam.get('measure'), 'area')} of takeoff "
                     f"groups named like: {_takeoff_words(fam['takeoff'])}"
                     f"{each}. With no such takeoff: {src}.")
    else:
        lines.append(f"Quantity: {src}.")
    banded = {prod.FAMILIES[k]["name"] for k in prod.CREW_BAND
              if k in prod.FAMILIES}
    if fam.get("name") in banded:
        lines.append("Crews: at least the Crews column; a large job gets "
                     "more, (area worked / band SF)^0.5 up to the most "
                     "crews - see the \"Crews by area band\" "
                     "assumptions.")
    lines.append("Min days: the shortest this activity is ever scheduled, "
                 "even for a small quantity. Max days: the longest, even "
                 "for a large one. Duration = quantity / (rate x crews), "
                 "kept between the two.")
    return "\n".join(lines)


class ProductivityDialog(QDialog):
    """Edit the production rates. save_table() writes them; reset() puts
    the defaults back in the grid (Save to keep them)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Production Rates")
        self.resize(900, 640)
        v = QVBoxLayout(self)
        tip = QLabel("Duration = quantity / (rate x crews), kept between "
                     "the minimum and maximum days. Every value starts as "
                     "an ASSUMED starting value, checked against public "
                     "production figures (DOT production tables, trade "
                     "and manufacturer guides) - set your own; your "
                     "values are used for every Build From Plans. Crews "
                     "is the fewest: on a large job the floor-wide trades "
                     "get more (Crews by area band, below).")
        tip.setWordWrap(True)
        v.addWidget(tip)
        self.table = QTableWidget(0, len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(C_NAME, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(C_NOTE, QHeaderView.Stretch)
        v.addWidget(self.table, 3)
        v.addWidget(QLabel("Quantity assumptions (used when nothing was "
                           "taken off for an activity):"))
        self.assume = QTableWidget(0, 2)
        self.assume.setHorizontalHeaderLabels(["Assumption", "Value"])
        self.assume.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch)
        v.addWidget(self.assume, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Save |
                              QDialogButtonBox.Cancel)
        self.reset_btn = QPushButton("Reset to defaults")
        bb.addButton(self.reset_btn, QDialogButtonBox.ResetRole)
        self.reset_btn.clicked.connect(self.reset)
        bb.accepted.connect(self._save_and_close)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self.fill(prod.load())

    # ------------------------------------------------------------- grid
    def fill(self, table):
        self._keys = list(table["families"])
        t = self.table
        t.setRowCount(len(self._keys))
        for r, key in enumerate(self._keys):
            fam = table["families"][key]
            vals = [fam["name"], f"{fam['unit']} {fam['of']}",
                    _g(fam["rate"]), _g(fam["crews"]), _g(fam["min"]),
                    _g(fam["max"]), fam.get("note") or ""]
            tip = family_tooltip(fam)
            for c, val in enumerate(vals):
                it = QTableWidgetItem(val)
                it.setData(Qt.UserRole, key)
                it.setToolTip(tip)
                if c in (C_NAME, C_UNIT):
                    it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                t.setItem(r, c, it)
        self._akeys = list(table["assumptions"])
        a = self.assume
        a.setRowCount(len(self._akeys))
        for r, key in enumerate(self._akeys):
            it = QTableWidgetItem(prod.ASSUMPTIONS[key][1])
            it.setData(Qt.UserRole, key)
            it.setFlags(it.flags() & ~Qt.ItemIsEditable)
            it.setToolTip(prod.ASSUMPTIONS[key][1])
            a.setItem(r, 0, it)
            a.setItem(r, 1, QTableWidgetItem(_g(table["assumptions"][key])))

    def row_of(self, key):
        return self._keys.index(key)

    def set_value(self, key, field, value):
        """Type a value into the grid (as the person would)."""
        col = {v: k for k, v in _NUM.items()}.get(field, C_NOTE)
        self.table.item(self.row_of(key), col).setText(str(value))

    def values(self):
        """(table, problems): the grid as a productivity table; cells that
        aren't usable numbers are listed and keep their old value."""
        table = prod.load()
        problems = []
        for r, key in enumerate(self._keys):
            fam = table["families"][key]
            for c, field in _NUM.items():
                text = (self.table.item(r, c).text() or "").replace(",", "")
                try:
                    x = float(text)
                    if x < 0 or (field in ("rate", "crews") and x <= 0):
                        raise ValueError
                except ValueError:
                    problems.append(f"{fam['name']}: {COLS[c]} "
                                    f"\"{text}\"")
                    continue
                fam[field] = x
            fam["note"] = self.table.item(r, C_NOTE).text()
            if fam["max"] < fam["min"]:
                problems.append(f"{fam['name']}: max days below min days")
                fam["max"] = fam["min"]
        for r, key in enumerate(self._akeys):
            text = (self.assume.item(r, 1).text() or "").replace(",", "")
            try:
                x = float(text)
                if x <= 0:
                    raise ValueError
                table["assumptions"][key] = x
            except ValueError:
                problems.append(f"{prod.ASSUMPTIONS[key][1]}: \"{text}\"")
        return table, problems

    def save_table(self):
        table, problems = self.values()
        prod.save(table)
        return problems

    def reset(self):
        """The built-in values back in the grid (and the saved edits
        removed)."""
        self.fill(prod.reset())

    def _save_and_close(self):
        problems = self.save_table()
        if problems:
            QMessageBox.warning(self, "Production Rates", "These weren't "
                                "numbers and kept their old values:\n" +
                                "\n".join(problems[:12]))
        self.accept()


def edit_rates(parent=None, show=True):
    dlg = ProductivityDialog(parent)
    if show:
        dlg.exec()
    return dlg
