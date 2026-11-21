"""Concrete, Brick / Block, Roofing, Rebar, Beam, Column and Footing
calculator dialogs (Estimate tab; the last four Nov 19 - structcalc.py).

Type the sizes, or fill them from a takeoff group on the open drawing (an
area group fills a slab's or a wall's area, a length group the length).
Results update as you type; Copy Results puts them on the clipboard."""
from PySide6.QtWidgets import (QApplication, QComboBox, QDialog,
                               QDialogButtonBox, QDoubleSpinBox, QFormLayout,
                               QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QScrollArea,
                               QSpinBox, QTabWidget, QVBoxLayout, QWidget)

from . import calculators as calc, sitecalc as sitec, structcalc as sc
from .dmoney import c2 as _c2

# which fields each concrete shape asks for: (key, label, suffix, default)
FIELDS = {
    "slab": [("length", "Length", " ft", 20), ("width", "Width", " ft", 20),
             ("thick_in", "Thickness", " in", 4)],
    "footing": [("length", "Length", " ft", 100),
                ("width_in", "Width", " in", 20),
                ("depth_in", "Depth", " in", 10)],
    "wall": [("length", "Length", " ft", 40), ("height", "Height", " ft", 8),
             ("thick_in", "Thickness", " in", 8)],
    "column": [("dia_in", "Diameter", " in", 12),
               ("height", "Height", " ft", 10)],
    "pier": [("side_in", "Side", " in", 16), ("height", "Height", " ft", 4)],
    "steps": [("width", "Width", " ft", 4), ("rise_in", "Rise", " in", 7),
              ("run_in", "Run (tread)", " in", 11),
              ("count", "Steps", "", 3)],
}
NAMES = {"slab": "Slab / flatwork", "footing": "Continuous footing",
         "wall": "Wall", "column": "Round column / sonotube",
         "pier": "Square pier", "steps": "Steps"}


def _spin(value, suffix="", top=100000.0, dec=2):
    s = QDoubleSpinBox()
    s.setRange(0, top)
    s.setDecimals(dec)
    s.setValue(value)
    s.setSuffix(suffix)
    s.setKeyboardTracking(True)
    return s


def takeoff_groups(doc, types=("area", "length")):
    """{(name, type, unit): total} of the drawing's takeoff."""
    if doc is None:
        return {}
    from . import annotate
    out = {}
    for it in annotate.totals_items(doc):
        if it["type"] not in types:
            continue
        k = (it["group"] or it["type"].title(), it["type"], it["unit"])
        out[k] = out.get(k, 0.0) + float(it["value"] or 0)
    return out


class _Base(QWidget):
    def __init__(self, doc):
        super().__init__()
        self.doc = doc
        self.v = QVBoxLayout(self)
        self.form = QFormLayout()
        self.v.addLayout(self.form)
        self.out = QLabel()
        self.out.setObjectName("calcResult")
        self.out.setWordWrap(True)
        self.v.addWidget(self.out)
        self.v.addStretch(1)

    def _from_takeoff_row(self, types, apply):
        groups = takeoff_groups(self.doc, types)
        if not groups:
            return
        row = QHBoxLayout()
        box = QComboBox()
        box.addItem("(type the sizes)", None)
        for (name, t, unit), total in sorted(groups.items()):
            box.addItem(f"{name} - {total:,.1f} {unit}", (t, unit, total))
        btn = QPushButton("Use")
        btn.clicked.connect(lambda: box.currentData() and
                            apply(*box.currentData()))
        row.addWidget(box, 1)
        row.addWidget(btn)
        self.form.addRow("From takeoff", row)
        self.takeoff_box = box


class ConcreteTab(_Base):
    def __init__(self, doc=None):
        super().__init__(doc)
        self.shape = QComboBox()
        for s in calc.SHAPES:
            self.shape.addItem(NAMES[s], s)
        self.form.addRow("Shape", self.shape)
        self._from_takeoff_row(("area", "length"), self.use_takeoff)
        self.inputs = {}
        self.rows = QFormLayout()
        self.form.addRow(self.rows)
        self.qty = QSpinBox()
        self.qty.setRange(1, 100000)
        self.waste = _spin(5, " %", 50, 1)
        self.form.addRow("How many", self.qty)
        self.form.addRow("Waste", self.waste)
        for w in (self.qty, self.waste):
            w.valueChanged.connect(self.update)
        self.shape.currentIndexChanged.connect(self._shape_changed)
        self._shape_changed()

    def _shape_changed(self, *_):
        while self.rows.rowCount():
            self.rows.removeRow(0)
        self.inputs = {}
        for key, label, suf, val in FIELDS[self.shape.currentData()]:
            s = _spin(val, suf)
            s.valueChanged.connect(self.update)
            self.rows.addRow(label, s)
            self.inputs[key] = s
        self.update()

    def use_takeoff(self, mtype, unit, total):
        """An area fills a slab (length = area, width = 1); a length fills
        the length of a footing, wall or slab."""
        if mtype == "area":
            self.shape.setCurrentIndex(self.shape.findData("slab"))
            self.inputs["length"].setValue(total)
            self.inputs["width"].setValue(1)
        elif "length" in self.inputs:
            self.inputs["length"].setValue(total)
        self.update()

    def values(self):
        return {k: s.value() for k, s in self.inputs.items()}

    def result(self):
        return calc.concrete(self.shape.currentData(), self.qty.value(),
                             self.waste.value(), **self.values())

    def update(self, *_):
        try:
            r = self.result()
        except ValueError as e:
            self.out.setText(str(e))
            return None
        self.out.setText(
            f"<b>{_c2(r['cy_with_waste']):,.2f} cubic yards (CY)</b> with "
            f"{self.waste.value():g}% waste ({_c2(r['cy']):,.2f} CY net, "
            f"{r['cf']:,.1f} cu ft)<br>Order: <b>{_c2(r['order_cy']):,.2f} CY</b>"
            f" - {r['trucks']} truck(s) at {calc.TRUCK_CY:g} CY")
        return r

    def estimate_rows(self):
        """[(desc, qty, unit, code)] for Add to Estimate (Nov 20)."""
        r = self.result()
        return [(f"Concrete - {NAMES[self.shape.currentData()]}",
                 r["cy_with_waste"], "cy", "03 30 00")]

    def text(self):
        r = self.result()
        return (f"Concrete - {NAMES[self.shape.currentData()]} x "
                f"{self.qty.value()}: {_c2(r['cy_with_waste']):.2f} CY with "
                f"{self.waste.value():g}% waste; order {_c2(r['order_cy']):.2f} CY"
                f" ({r['trucks']} truck(s))")


class MasonryTab(_Base):
    def __init__(self, doc=None):
        super().__init__(doc)
        self.unit = QComboBox()
        self.unit.addItems(list(calc.UNITS))
        self.form.addRow("Unit", self.unit)
        self._from_takeoff_row(("area", "length"), self.use_takeoff)
        self.length = _spin(40, " ft")
        self.height = _spin(8, " ft")
        self.area = _spin(0, " sq ft (0 = length x height)")
        self.openings = _spin(0, " sq ft")
        self.wythes = QSpinBox()
        self.wythes.setRange(1, 4)
        self.joint = _spin(0.375, " in", 2, 3)
        self.waste = _spin(5, " %", 50, 1)
        self.mortar = _spin(calc.MORTAR_PER_1000["brick"], " bags / 1,000",
                            200, 1)
        self.sand = _spin(calc.SAND_TONS_PER_1000["brick"], " tons / 1,000",
                          20, 2)
        self.grout_spacing = QComboBox()
        self.grout_spacing.addItem("No grout", "none")
        self.grout_spacing.addItem("Solid grouted (every cell)", "solid")
        for sp in calc.GROUT_SPACINGS:
            self.grout_spacing.addItem(f'Cells at {sp}" o.c.', sp)
        self.grout_spacing.setCurrentIndex(1)
        self.bond_beam = _spin(0, " ft of bond beam", 100000, 1)
        self.grout_waste = _spin(calc.GROUT_WASTE_PCT, " %", 50, 1)
        self.grout_rate = _spin(calc.GROUT_CF_PER_SF[8],
                                " cu ft / sq ft solid", 2, 3)
        for label, w in (("Wall length", self.length),
                         ("Wall height", self.height),
                         ("or wall area", self.area),
                         ("Openings (less)", self.openings),
                         ("Wythes", self.wythes),
                         ("Mortar joint", self.joint),
                         ("Waste", self.waste),
                         ("Mortar (70 lb masonry cement)", self.mortar),
                         ("Sand", self.sand)):
            self.form.addRow(label, w)
            w.valueChanged.connect(self.update)
        self._grout_rows = []
        for label, w in (("Grout (CMU)", self.grout_spacing),
                         ("Bond beams", self.bond_beam),
                         ("Grout waste", self.grout_waste),
                         ("Grout rate", self.grout_rate)):
            self.form.addRow(label, w)
            self._grout_rows.append(w)
            if isinstance(w, QComboBox):
                w.currentIndexChanged.connect(self.update)
            else:
                w.valueChanged.connect(self.update)
        self.grout_rate.setToolTip(
            "Grout to fill every cell, per sq ft of wall. Starting points "
            "from published wall tables; check your block maker's.")
        self.unit.currentIndexChanged.connect(self._unit_changed)
        self._unit_changed()

    def _unit_changed(self, *_):
        u = self.unit.currentText()
        k = calc.kind_of(u)
        self.mortar.setValue(calc.MORTAR_PER_1000[k])
        self.sand.setValue(calc.SAND_TONS_PER_1000[k])
        w = calc.nominal_width(u)
        if w:
            self.grout_rate.setValue(calc.GROUT_CF_PER_SF.get(w, 0.30))
        for g in self._grout_rows:
            g.setEnabled(k == "cmu")
            lab = self.form.labelForField(g)
            if lab is not None:
                lab.setEnabled(k == "cmu")
        self.update()

    def use_takeoff(self, mtype, unit, total):
        if mtype == "area":
            self.area.setValue(total)
        else:
            self.length.setValue(total)
            self.area.setValue(0)
        self.update()

    def result(self):
        return calc.masonry(
            self.length.value(), self.height.value(),
            self.unit.currentText(), self.openings.value(),
            self.waste.value(), self.joint.value(), self.wythes.value(),
            area_sf=self.area.value() or None,
            mortar_per_1000=self.mortar.value(),
            sand_per_1000=self.sand.value(),
            grout_spacing=self.grout_spacing.currentData(),
            bond_beam_lf=self.bond_beam.value(),
            grout_waste_pct=self.grout_waste.value(),
            grout_cf_per_sf=self.grout_rate.value())

    def _grout_text(self, r, html=True):
        g = r.get("grout")
        if not g or self.grout_spacing.currentData() == "none" and \
                not g["bond_beam_cf"]:
            return ""
        b = (lambda t: f"<b>{t}</b>") if html else (lambda t: t)
        cy = format(g["cy_with_waste"], ",.2f") + " CY"
        return (f"Grout: {b(cy)} with {self.grout_waste.value():g}% waste "
                f"({_c2(g['cy']):,.2f} CY net; order {_c2(g['order_cy']):,.2f} CY)")

    def update(self, *_):
        try:
            r = self.result()
        except ValueError as e:
            self.out.setText(str(e))
            return None
        self.out.setText(
            f"<b>{r['units_with_waste']:,} {self.unit.currentText()}</b> "
            f"with {self.waste.value():g}% waste ({r['units']:,.0f} net, "
            f"{r['per_sf']:.3f} per sq ft over {r['net_sf']:,.1f} sq ft)<br>"
            f"Mortar: <b>{r['mortar_bags']:,} bags</b> - Sand: "
            f"<b>{_c2(r['sand_tons']):,.2f} tons</b><br>"
            + (self._grout_text(r) + "<br>" if self._grout_text(r) else "")
            + "<span style='color:gray'>Mortar, sand and grout rates are "
            "starting points; use your supplier's.</span>")
        return r

    def estimate_rows(self):
        r = self.result()
        rows = [(f"Masonry - {self.unit.currentText()}",
                 r["units_with_waste"], "ea", "04 20 00")]
        if r["mortar_bags"]:
            rows.append(("Masonry mortar", r["mortar_bags"], "bag",
                         "04 05 13"))
        if r["sand_tons"]:
            rows.append(("Masonry sand", r["sand_tons"], "ton", "04 05 13"))
        if self._grout_text(r):
            rows.append(("Masonry grout", r["grout"]["cy_with_waste"], "cy",
                         "04 05 16"))
        return rows

    def text(self):
        r = self.result()
        return (f"Masonry - {self.unit.currentText()}: "
                f"{r['units_with_waste']} units with {self.waste.value():g}% "
                f"waste over {r['net_sf']:.1f} sf; {r['mortar_bags']} mortar "
                f"bags; {_c2(r['sand_tons']):.2f} tons sand"
                + (f"; {self._grout_text(r, False)}" if self._grout_text(r)
                   else ""))


class RoofingTab(_Base):
    """Roofing order quantities from the roof's plan area and pitch (or
    its sloped area) and typed eave / rake / ridge / hip / valley
    lengths. Typed numbers, a takeoff group, or a measurement report the
    user already has (Import Roof Report); nothing is fetched."""

    RATE_LABELS = (("bundles_per_square", "Shingle bundles", " / square"),
                   ("underlay_sq_per_roll", "Underlayment", " squares / roll"),
                   ("ice_water_lf_per_roll", "Ice && water", " ft / roll"),
                   ("ice_water_rows", "Ice && water rows at eaves", ""),
                   ("starter_lf_per_bundle", "Starter", " ft / bundle"),
                   ("ridge_lf_per_bundle", "Ridge cap", " ft / bundle"),
                   ("drip_piece_ft", "Drip edge piece", " ft"))

    def __init__(self, doc=None):
        super().__init__(doc)
        self.kind = QComboBox()
        self.kind.addItems(list(calc.ROOF_KINDS))
        self.form.addRow("Roof", self.kind)
        self._from_takeoff_row(("area", "length"), self.use_takeoff)
        rep = QHBoxLayout()
        self.report_btn = QPushButton("Import Roof Report…")
        self.report_btn.setToolTip(
            "Fill the sizes from a roof measurement report you already have "
            "(an EagleView report or a similar PDF or text file). Only the "
            "roof numbers are read; nothing is downloaded or sent. EagleView "
            "is a trademark of EagleView Technologies, Inc.; QuantiSheet is "
            "not affiliated with it.")
        self.report_btn.clicked.connect(lambda _c=False: self.import_report())
        self.report_note = QLabel("")
        self.report_note.setWordWrap(True)
        rep.addWidget(self.report_btn)
        rep.addWidget(self.report_note, 1)
        self.form.addRow("From a report", rep)
        self.plan = _spin(2000, " sq ft (plan)", 10000000, 1)
        self.sloped = _spin(0, " sq ft (0 = plan x pitch)", 10000000, 1)
        self.pitch = _spin(6, " in 12", calc.MAX_PITCH, 2)
        self.waste = _spin(10, " %", 50, 1)
        # 2 decimals so 96 ft 7 in (96.58 ft) from a report is kept as read
        self.eave = _spin(0, " ft", 1000000, 2)
        self.rake = _spin(0, " ft", 1000000, 2)
        self.ridge = _spin(0, " ft", 1000000, 2)
        self.hip = _spin(0, " ft", 1000000, 2)
        self.valley = _spin(0, " ft", 1000000, 2)
        for label, w in (("Roof area", self.plan), ("or sloped area",
                                                     self.sloped),
                         ("Pitch", self.pitch), ("Waste", self.waste),
                         ("Eaves", self.eave), ("Rakes", self.rake),
                         ("Ridges", self.ridge), ("Hips", self.hip),
                         ("Valleys", self.valley)):
            self.form.addRow(label, w)
            w.valueChanged.connect(self.update)
        self.rates = {}
        for key, label, suf in self.RATE_LABELS:
            v = calc.ROOF_DEFAULTS[key]
            w = _spin(v, suf, 1000, 0 if key == "ice_water_rows" else 1)
            self.form.addRow(label, w)
            w.valueChanged.connect(self.update)
            self.rates[key] = w
        self.kind.currentIndexChanged.connect(self.update)
        self.update()

    def import_report(self, path=None):
        """Fill sloped area, pitch and edge lengths from a report file.

        Every size the report gives is filled; a size it doesn't give is
        cleared to 0 (so two reports' numbers are never mixed); a size
        that doesn't fit its box is left alone and named in the note -
        except the pitch: a steeper pitch than the box takes (12:12 is the
        cap) sets it to 0, so the previous report's pitch is never used.
        Out-of-range sizes are shown in bold red."""
        import html
        from PySide6.QtCore import Qt
        from . import roof_report
        self.report_note.setTextFormat(Qt.PlainText)
        if path is None:
            from PySide6.QtWidgets import QFileDialog
            path, _ = QFileDialog.getOpenFileName(
                self, "Import Roof Report", "",
                "Roof reports (*.pdf *.txt);;All files (*)")
            if not path:
                return None
        try:
            got = roof_report.import_file(path)
        except roof_report.RoofReportError as e:
            self.report_note.setText(str(e))
            return None
        except Exception as e:                             # noqa: BLE001
            self.report_note.setText(f"Couldn't read that file: {e}")
            return None
        found = [f for f in roof_report.NAMES if f in got]
        notes = list(got.get("notes") or [])
        if not found:
            self.report_note.setText(" ".join(
                ["No roof measurements found in that file. Type the sizes."]
                + notes))
            return got
        widgets = {"sloped_sf": self.sloped, "pitch": self.pitch,
                   "ridge": self.ridge, "hip": self.hip,
                   "valley": self.valley, "rake": self.rake,
                   "eave": self.eave}
        units = {"sloped_sf": " sq ft", "pitch": " in 12"}
        filled, out_of_range, cleared = [], [], []
        pitch_out = None
        for f in roof_report.NAMES:
            w = widgets[f]
            if f in got:
                v = got[f]
                if w.minimum() <= v <= w.maximum():
                    w.setValue(v)
                    filled.append(f)
                else:
                    shown = (f"{v:,.0f}" if float(v).is_integer()
                             else f"{_c2(v):,.2f}")
                    what = (f"{roof_report.NAMES[f]} out of range "
                            f"({shown}{units.get(f, ' ft')})")
                    if f == "pitch":
                        # never keep the previous report's pitch
                        w.setValue(0)
                        pitch_out = what
                    else:
                        out_of_range.append(what)
            else:
                w.setValue(0)
                cleared.append(f)
        def esc(t):
            return html.escape(t, quote=False)
        loud = ('<b><span style="color:#c00000">{}</span></b>'.format)
        if filled:
            note = esc("Read: " + ", ".join(roof_report.NAMES[f]
                                            for f in filled))
        else:
            note = "Nothing filled"
        if pitch_out:
            note += ". " + loud(esc(pitch_out + ": set to 0 (pitch out of "
                                    "range - type it)"))
        if out_of_range:
            note += ". " + loud(esc("Not filled (left as they were): "
                                    + ", ".join(out_of_range)))
        if cleared:
            note += esc(". Not in the report, cleared to 0 (type them): "
                        + ", ".join(roof_report.NAMES[f] for f in cleared))
        note += ". Check them against the report."
        if notes:
            note += " " + esc(" ".join(notes))
        note += " " + esc(roof_report.TRADEMARK_NOTE if got.get("eagleview")
                          else roof_report.GENERIC_NOTE)
        self.report_note.setTextFormat(Qt.RichText)
        self.report_note.setText(note)
        self.update()
        return got

    def use_takeoff(self, mtype, unit, total):
        """An area group fills the plan area; a length group the eaves."""
        if mtype == "area":
            self.plan.setValue(total)
            self.sloped.setValue(0)
        else:
            self.eave.setValue(total)
        self.update()

    def result(self):
        return calc.roofing(
            self.plan.value(), self.pitch.value(), self.waste.value(),
            self.sloped.value() or None, self.eave.value(),
            self.rake.value(), self.ridge.value(), self.hip.value(),
            self.valley.value(), self.kind.currentText(),
            **{k: w.value() for k, w in self.rates.items()})

    def update(self, *_):
        try:
            r = self.result()
        except ValueError as e:
            self.out.setText(str(e))
            return None
        lines = [f"<b>{_c2(r['squares_with_waste']):,.2f} squares</b> with "
                 f"{self.waste.value():g}% waste ({_c2(r['squares']):,.2f} net, "
                 f"{r['sloped_sf']:,.0f} sq ft sloped; factor "
                 f"{r['factor']:.3f})",
                 f"Order: <b>{_c2(r['order_squares']):,.2f} squares</b>"]
        if r["bundles"]:
            lines.append(f"Shingles: <b>{r['bundles']:,} bundles</b>")
        lines.append(f"Underlayment: <b>{r['underlay_rolls']:,} rolls</b>")
        if r["ice_water_rolls"]:
            lines.append(f"Ice & water: <b>{r['ice_water_rolls']:,} rolls"
                         "</b> (eaves and valleys)")
        if r["starter_bundles"]:
            lines.append(f"Starter: <b>{r['starter_bundles']:,} bundles</b>"
                         f" ({r['starter_lf']:,.0f} ft)")
        if r["ridge_bundles"]:
            lines.append(f"Ridge cap: <b>{r['ridge_bundles']:,} bundles</b>"
                         f" ({r['ridge_lf']:,.0f} ft of ridge and hip)")
        if r["drip_pieces"]:
            lines.append(f"Drip edge: <b>{r['drip_pieces']:,} pieces</b> "
                         f"({r['drip_lf']:,.0f} ft)")
        lines.append("<span style='color:gray'>Coverage rates are starting "
                     "points; use the product's own.</span>")
        self.out.setText("<br>".join(lines))
        return r

    def estimate_rows(self):
        r = self.result()
        kind = self.kind.currentText()
        code = {"Shingles": "07 31 13", "Metal": "07 41 13"}.get(
            kind, "07 50 00")
        rows = [(f"Roofing - {kind}", r["squares_with_waste"], "sq", code)]
        for key, name, unit in (("bundles", "Shingle bundles", "bdl"),
                                ("underlay_rolls", "Roof underlayment",
                                 "roll"),
                                ("ice_water_rolls", "Ice and water shield",
                                 "roll"),
                                ("starter_bundles", "Starter strip", "bdl"),
                                ("ridge_bundles", "Ridge cap", "bdl"),
                                ("drip_pieces", "Drip edge", "ea")):
            if r.get(key):
                rows.append((name, r[key], unit, code))
        return rows

    def text(self):
        r = self.result()
        parts = [f"Roofing - {self.kind.currentText()}: "
                 f"{_c2(r['squares_with_waste']):.2f} squares with "
                 f"{self.waste.value():g}% waste "
                 f"(order {_c2(r['order_squares']):.2f})"]
        if r["bundles"]:
            parts.append(f"{r['bundles']} bundles")
        parts.append(f"{r['underlay_rolls']} underlayment rolls")
        if r["ice_water_rolls"]:
            parts.append(f"{r['ice_water_rolls']} ice & water rolls")
        if r["starter_bundles"]:
            parts.append(f"{r['starter_bundles']} starter bundles")
        if r["ridge_bundles"]:
            parts.append(f"{r['ridge_bundles']} ridge cap bundles")
        if r["drip_pieces"]:
            parts.append(f"{r['drip_pieces']} drip edge pieces")
        return "; ".join(parts)


def _combo(items, current=None):
    c = QComboBox()
    for label, data in items:
        c.addItem(label, data)
    if current is not None:
        c.setCurrentIndex(max(0, c.findData(current)))
    return c


def _note():
    n = QLabel(sc.DISCLAIMER)
    n.setWordWrap(True)
    n.setStyleSheet("color: gray;")
    return n


BAR_ITEMS = [(f"#{b} ({d:g}\" dia, {w:g} lb/ft)", b)
             for b, (d, w) in sorted(sc.BARS.items())]


class RebarTab(_Base):
    """Bars for a slab (length x width, or a takeoff area) or continuous
    bars along a footing or wall, with laps at stock lengths."""
    MODES = [("Slab or mat - length x width", "grid"),
             ("Slab from a takeoff area", "area"),
             ("Continuous bars (footing / wall)", "linear")]

    def __init__(self, doc=None):
        super().__init__(doc)
        self.mode = _combo(self.MODES)
        self.form.addRow("Layout", self.mode)
        self._from_takeoff_row(("area", "length"), self.use_takeoff)
        self.bar = _combo(BAR_ITEMS, 4)
        self.form.addRow("Bar", self.bar)
        self.length = _spin(20, " ft")
        self.wide = _spin(20, " ft")
        self.area = _spin(400, " sq ft", 10000000)
        self.spacing = _spin(12, " in o.c.", 120, 1)
        self.cover = _spin(3, " in", 24, 1)
        self.each_way = QComboBox()
        self.each_way.addItems(["Each way", "One way"])
        self.count = QSpinBox()
        self.count.setRange(1, 100)
        self.count.setValue(2)
        self.lap = QSpinBox()
        self.lap.setRange(0, 120)
        self.lap.setValue(sc.LAP_DIAMETERS)
        self.lap.setSuffix(" bar diameters")
        self.stock = _spin(sc.STOCK_FT, " ft", 60, 0)
        self.waste = _spin(5, " %", 50, 1)
        self.rows = {}
        for key, label, w in (("length", "Length", self.length),
                              ("width", "Width", self.wide),
                              ("area", "Area", self.area),
                              ("spacing", "Spacing", self.spacing),
                              ("cover", "Edge cover", self.cover),
                              ("each_way", "Direction", self.each_way),
                              ("count", "Bars side by side", self.count),
                              ("lap", "Lap splice", self.lap),
                              ("stock", "Stock length", self.stock),
                              ("waste", "Waste", self.waste)):
            self.form.addRow(label, w)
            self.rows[key] = w
            sig = getattr(w, "valueChanged", None) or \
                w.currentIndexChanged
            sig.connect(self.update)
        self.bar.currentIndexChanged.connect(self.update)
        self.mode.currentIndexChanged.connect(self._mode_changed)
        self._mode_changed()

    def _mode_changed(self, *_):
        m = self.mode.currentData()
        show = {"grid": ("length", "width", "spacing", "cover", "each_way"),
                "area": ("area", "spacing", "each_way"),
                "linear": ("length", "count")}[m]
        for key, w in self.rows.items():
            vis = key in show or key in ("lap", "stock", "waste")
            w.setVisible(vis)
            lab = self.form.labelForField(w)
            if lab is not None:
                lab.setVisible(vis)
        self.update()

    def use_takeoff(self, mtype, unit, total):
        """An area group is a slab by area; a length group is continuous
        bars along it."""
        mode = "area" if mtype == "area" else "linear"
        self.mode.setCurrentIndex(self.mode.findData(mode))
        (self.area if mtype == "area" else self.length).setValue(total)
        self.update()

    def result(self):
        m, bar = self.mode.currentData(), self.bar.currentData()
        kw = dict(waste_pct=self.waste.value(), stock_ft=self.stock.value(),
                  diameters=self.lap.value())
        each = self.each_way.currentIndex() == 0
        if m == "grid":
            return sc.rebar_grid(self.length.value(), self.wide.value(),
                                 self.spacing.value(), bar,
                                 self.cover.value(), each, **kw)
        if m == "area":
            return sc.rebar_area(self.area.value(), self.spacing.value(),
                                 bar, each, **kw)
        return sc.rebar_linear(self.length.value(), self.count.value(), bar,
                               **kw)

    def update(self, *_):
        try:
            r = self.result()
        except (ValueError, AttributeError) as e:
            self.out.setText(str(e))
            return None
        bars = f"{r['bars']:,} bars, " if r["bars"] else ""
        self.out.setText(
            f"<b>{r['lf']:,.0f} LF of #{self.bar.currentData()}</b> "
            f"({bars}{r['laps']:,} laps) - <b>{r['lb_with_waste']:,.0f} lb"
            f"</b> with {self.waste.value():g}% waste "
            f"({r['tons']:,.3f} tons), {r['sticks']:,} sticks at "
            f"{self.stock.value():g} ft")
        return r

    def estimate_rows(self):
        r = self.result()
        return [(f"Reinforcing steel #{self.bar.currentData()} - "
                 f"{self.mode.currentText()}", r["lb_with_waste"], "lb",
                 "03 21 00")]

    def text(self):
        r = self.result()
        return (f"Rebar - #{self.bar.currentData()} "
                f"{self.mode.currentText()}: {r['lf']:,.0f} LF, "
                f"{r['lb_with_waste']:,.0f} lb with {self.waste.value():g}% "
                f"waste, {r['sticks']} sticks")


class _CheckTab(_Base):
    """A preliminary check: results as a small table of OK / Check."""

    def __init__(self, doc=None):
        super().__init__(doc)
        self.v.insertWidget(self.v.count() - 1, _note())

    @staticmethod
    def _rows(checks):
        out = []
        for name, actual, allowed, ok in checks:
            out.append(f"{name}: {actual:,.3g} vs {allowed:,.3g} allowed - "
                       + ("<b style='color:#1b7f3b'>OK</b>" if ok else
                          "<b style='color:#b00020'>OVER</b>"))
        return "<br>".join(out)


class BeamTab(_CheckTab):
    """Simple-span beam or header: reactions, moment, shear, deflection
    and, with the section and allowables typed, the checks."""

    def __init__(self, doc=None):
        super().__init__(doc)
        self.span = _spin(10, " ft", 200)
        self.w = _spin(200, " plf", 100000, 1)
        self.p = _spin(0, " lb", 1000000, 0)
        self.a = _spin(5, " ft from left", 200)
        self.kind = _combo([("Wood - solid sawn or LVL", "wood"),
                            ("Typed section (steel, glulam...)", "typed")])
        self.b = _spin(4, " in nominal", 48, 2)
        self.d = _spin(10, " in nominal", 48, 2)
        self.nominal = QComboBox()
        self.nominal.addItems(["Sawn lumber (nominal sizes)",
                               "Actual size (LVL, glulam)"])
        self.plies = QSpinBox()
        self.plies.setRange(1, 6)
        self.A = _spin(10, " in²", 1000, 2)
        self.S = _spin(30, " in³", 10000, 2)
        self.I = _spin(150, " in⁴", 100000, 1)
        self.Fb = _spin(900, " psi", 100000, 0)
        self.Fv = _spin(180, " psi", 100000, 0)
        self.E = _spin(1600000, " psi", 40000000, 0)
        self.limit = QSpinBox()
        self.limit.setRange(60, 2000)
        self.limit.setValue(360)
        self.limit.setPrefix("L / ")
        self.rows = {}
        for key, label, wdg in (("span", "Span", self.span),
                                ("w", "Uniform load (with own weight)",
                                 self.w),
                                ("p", "Point load", self.p),
                                ("a", "Point load at", self.a),
                                ("kind", "Member", self.kind),
                                ("nominal", "Sizes", self.nominal),
                                ("b", "Width", self.b),
                                ("d", "Depth", self.d),
                                ("plies", "Plies", self.plies),
                                ("A", "Area (shear: web area)", self.A),
                                ("S", "Section modulus S", self.S),
                                ("I", "Moment of inertia I", self.I),
                                ("Fb", "Allowable bending Fb'", self.Fb),
                                ("Fv", "Allowable shear Fv'", self.Fv),
                                ("E", "E (modulus)", self.E),
                                ("limit", "Deflection limit", self.limit)):
            self.form.addRow(label, wdg)
            self.rows[key] = wdg
            sig = getattr(wdg, "valueChanged", None) or \
                wdg.currentIndexChanged
            sig.connect(self.update)
        self.kind.currentIndexChanged.connect(self._kind_changed)
        self._kind_changed()

    def _kind_changed(self, *_):
        wood = self.kind.currentData() == "wood"
        for key, wdg in self.rows.items():
            vis = (key not in ("nominal", "b", "d", "plies") or wood) and \
                (key not in ("A", "S", "I") or not wood)
            wdg.setVisible(vis)
            lab = self.form.labelForField(wdg)
            if lab is not None:
                lab.setVisible(vis)
        self.update()

    def section(self):
        if self.kind.currentData() == "typed":
            return {"A": self.A.value(), "S": self.S.value(),
                    "I": self.I.value()}, False
        conv = sc.dressed if self.nominal.currentIndex() == 0 else \
            (lambda v: v)
        return sc.rect_section(conv(self.b.value()), conv(self.d.value()),
                               self.plies.value()), True

    def result(self):
        sec, rect = self.section()
        return sc.beam(self.span.value(), self.w.value(), self.p.value(),
                       self.a.value() if self.p.value() else None, sec,
                       self.E.value(), self.Fb.value(), self.Fv.value(),
                       self.limit.value(), rect=rect)

    def update(self, *_):
        try:
            r = self.result()
        except (ValueError, AttributeError) as e:
            self.out.setText(str(e))
            return None
        self.out.setText(
            f"Reactions: <b>{r['R1']:,.0f} lb</b> left, <b>{r['R2']:,.0f} lb"
            f"</b> right. Largest moment <b>{r['Mmax']:,.0f} ft-lb</b> at "
            f"{r['x_Mmax']:,.1f} ft; shear {r['Vmax']:,.0f} lb.<br>" +
            self._rows(r["checks"]))
        return r

    def text(self):
        r = self.result()
        verdict = "all OK" if all(c[3] for c in r["checks"]) else \
            "something is OVER"
        return (f"Beam - {self.span.value():g} ft span: R {r['R1']:,.0f} / "
                f"{r['R2']:,.0f} lb, M {r['Mmax']:,.0f} ft-lb; {verdict} "
                f"(preliminary)")


class ColumnTab(_CheckTab):
    """Axial capacity of a wood post or a steel column."""

    def __init__(self, doc=None):
        super().__init__(doc)
        self.kind = _combo([("Wood post (solid)", "wood"),
                            ("Steel column", "steel")])
        self.tall = _spin(10, " ft", 200)
        self.K = _spin(1.0, "", 5, 2)
        self.load = _spin(0, " lb load (optional)", 10000000, 0)
        self.b = _spin(4, " in nominal", 48, 2)
        self.d = _spin(4, " in nominal", 48, 2)
        self.plies = QSpinBox()
        self.plies.setRange(1, 6)
        self.Fc = _spin(1000, " psi", 100000, 0)
        self.Emin = _spin(580000, " psi", 10000000, 0)
        self.A = _spin(5.26, " in²", 1000, 2)
        self.r = _spin(1.23, " in", 100, 3)
        self.Fy = _spin(50000, " psi", 200000, 0)
        self.method = _combo([("ASD (Pn / 1.67)", "ASD"),
                              ("LRFD (0.9 Pn)", "LRFD")])
        self.rows = {}
        for key, label, wdg in (("kind", "Member", self.kind),
                                ("height", "Unbraced height", self.tall),
                                ("K", "Effective length factor K", self.K),
                                ("load", "Load", self.load),
                                ("b", "Width", self.b),
                                ("d", "Depth", self.d),
                                ("plies", "Plies", self.plies),
                                ("Fc", "Allowable compression Fc'", self.Fc),
                                ("Emin", "Emin'", self.Emin),
                                ("A", "Area A", self.A),
                                ("r", "Least radius of gyration r", self.r),
                                ("Fy", "Yield Fy", self.Fy),
                                ("method", "Method", self.method)):
            self.form.addRow(label, wdg)
            self.rows[key] = wdg
            sig = getattr(wdg, "valueChanged", None) or \
                wdg.currentIndexChanged
            sig.connect(self.update)
        self.kind.currentIndexChanged.connect(self._kind_changed)
        self._kind_changed()

    def _kind_changed(self, *_):
        wood = self.kind.currentData() == "wood"
        for key, wdg in self.rows.items():
            vis = (key not in ("b", "d", "plies", "Fc", "Emin") or wood) and \
                (key not in ("A", "r", "Fy", "method") or not wood)
            wdg.setVisible(vis)
            lab = self.form.labelForField(wdg)
            if lab is not None:
                lab.setVisible(vis)
        self.update()

    def result(self):
        if self.kind.currentData() == "wood":
            return sc.wood_column(self.tall.value(),
                                  sc.dressed(self.b.value()),
                                  sc.dressed(self.d.value()),
                                  self.Fc.value(), self.Emin.value(),
                                  self.K.value(), plies=self.plies.value())
        return sc.steel_column(self.tall.value(), self.A.value(),
                               self.r.value(), self.Fy.value(),
                               K=self.K.value(),
                               method=self.method.currentData())

    def update(self, *_):
        try:
            r = self.result()
        except (ValueError, AttributeError) as e:
            self.out.setText(str(e))
            return None
        wood = self.kind.currentData() == "wood"
        slender = (f"le/d = {r['le_d']:,.1f}" if wood else
                   f"KL/r = {r['KLr']:,.0f}") + (
            "" if r["slender_ok"] else
            " - <b style='color:#b00020'>too slender</b> (over " +
            ("50" if wood else "200") + ")")
        txt = (f"Allowable axial load about <b>{r['P_allow_lb']:,.0f} lb"
               f"</b>. {slender}.")
        if self.load.value():
            txt += "<br>" + self._rows([("Load (lb)", self.load.value(),
                                         r["P_allow_lb"],
                                         self.load.value() <=
                                         r["P_allow_lb"]
                                         and r["slender_ok"])])
        self.out.setText(txt)
        return r

    def text(self):
        r = self.result()
        return (f"Column - {self.kind.currentText()}, {self.tall.value():g}"
                f" ft: about {r['P_allow_lb']:,.0f} lb allowable "
                f"(preliminary)")


class FootingTab(_CheckTab):
    """Footing size from the load and the allowable soil pressure."""

    def __init__(self, doc=None):
        super().__init__(doc)
        self.kind = _combo([("Square pad under a column", "pad"),
                            ("Continuous under a wall", "continuous")])
        self.load = _spin(20000, " lb", 10000000, 0)
        self.soil = _spin(2000, " psf allowable", 100000, 0)
        self.thick = _spin(12, " in thick", 120, 1)
        self.round = _spin(2, " in", 24, 1)
        self.count = QSpinBox()
        self.count.setRange(1, 10000)
        for label, wdg in (("Footing", self.kind), ("Load", self.load),
                           ("Soil bearing", self.soil),
                           ("Thickness", self.thick),
                           ("Round size up to", self.round),
                           ("How many / LF of wall", self.count)):
            self.form.addRow(label, wdg)
            sig = getattr(wdg, "valueChanged", None) or \
                wdg.currentIndexChanged
            sig.connect(self.update)
        self.kind.currentIndexChanged.connect(self._kind_changed)
        self._kind_changed()

    def _kind_changed(self, *_):
        pad = self.kind.currentData() == "pad"
        self.load.setSuffix(" lb" if pad else " plf")
        self.form.labelForField(self.count).setText(
            "How many pads" if pad else "Wall length (LF)")
        if not pad and self.count.value() == 1:
            self.count.setValue(100)
        self.update()

    def result(self):
        return sc.footing_size(self.load.value(), self.soil.value(),
                               self.thick.value(), self.kind.currentData(),
                               self.round.value())

    def update(self, *_):
        try:
            r = self.result()
        except (ValueError, AttributeError) as e:
            self.out.setText(str(e))
            return None
        n = self.count.value()
        if self.kind.currentData() == "pad":
            cy = r["cy"] * n
            size = f"<b>{_ft_in(r['side_ft'])} square</b>"
        else:
            cy = r["cy"] * n / 100
            size = f"<b>{_ft_in(r['width_ft'])} wide</b>"
        self.out.setText(
            f"{size} x {self.thick.value():g} in - bearing "
            f"{r['bearing_psf']:,.0f} psf with its own weight.<br>Concrete: "
            f"<b>{_c2(cy):,.2f} CY</b> net for {n:,} "
            + ("pad(s)" if self.kind.currentData() == "pad" else "LF"))
        return r

    def estimate_rows(self):
        r = self.result()
        n = self.count.value()
        pad = self.kind.currentData() == "pad"
        cy = r["cy"] * n if pad else r["cy"] * n / 100
        size = _ft_in(r["side_ft"] if pad else r["width_ft"])
        return [(f"Footing concrete - {self.kind.currentText()} {size} x "
                 f"{self.thick.value():g} in (preliminary size)", cy, "cy",
                 "03 30 00")]

    def text(self):
        r = self.result()
        size = r.get("side_ft") or r.get("width_ft")
        return (f"Footing - {self.kind.currentText()}: {_ft_in(size)} "
                f"x {self.thick.value():g} in (preliminary)")


class MetalStudTab(_Base):
    """Cold-formed steel framing: a stud wall or a joist area - studs,
    track, bridging and weight from the member names (362S162-33)."""

    def __init__(self, doc=None):
        super().__init__(doc)
        self.kind = _combo([("Stud wall", "wall"),
                            ("Floor or roof joists", "joists")])
        self.form.addRow("Framing", self.kind)
        self._from_takeoff_row(("length", "area"), self.use_takeoff)
        self.length = _spin(40, " ft")
        self.tall = _spin(10, " ft", 100)
        self.spacing = _combo([('12" o.c.', 12), ('16" o.c.', 16),
                               ('19.2" o.c.', 19.2), ('24" o.c.', 24)], 16)
        self.openings = QSpinBox()
        self.openings.setRange(0, 1000)
        self.per_opening = QSpinBox()
        self.per_opening.setRange(0, 20)
        self.per_opening.setValue(4)
        self.corners = QSpinBox()
        self.corners.setRange(0, 1000)
        self.bridging = _spin(4, " ft apart", 20, 1)
        self.stud = QLineEdit("362S162-33")
        self.track = QLineEdit("362T125-33")
        self.span = _spin(16, " ft", 100)
        self.wide = _spin(30, " ft")
        self.waste = _spin(5, " %", 50, 1)
        self.rows = {}
        for key, label, wdg in (
                ("length", "Wall length", self.length),
                ("height", "Wall height", self.tall),
                ("span", "Joist span", self.span),
                ("width", "Width of the area", self.wide),
                ("spacing", "Spacing", self.spacing),
                ("openings", "Openings", self.openings),
                ("per_opening", "Extra studs per opening", self.per_opening),
                ("corners", "Corners / intersections", self.corners),
                ("bridging", "Bridging rows", self.bridging),
                ("stud", "Stud / joist (e.g. 362S162-33)", self.stud),
                ("track", "Track / rim (e.g. 362T125-33)", self.track),
                ("waste", "Waste", self.waste)):
            self.form.addRow(label, wdg)
            self.rows[key] = wdg
            sig = getattr(wdg, "valueChanged", None) or \
                getattr(wdg, "textChanged", None) or \
                wdg.currentIndexChanged
            sig.connect(self.update)
        self.kind.currentIndexChanged.connect(self._kind_changed)
        self._kind_changed()

    def _kind_changed(self, *_):
        wall = self.kind.currentData() == "wall"
        only_wall = ("length", "height", "openings", "per_opening",
                     "corners", "bridging")
        only_joist = ("span", "width")
        for key, wdg in self.rows.items():
            vis = not ((key in only_wall and not wall) or
                       (key in only_joist and wall))
            wdg.setVisible(vis)
            lab = self.form.labelForField(wdg)
            if lab is not None:
                lab.setVisible(vis)
        if wall and self.stud.text().startswith("800"):
            self.stud.setText("362S162-33")
            self.track.setText("362T125-33")
        elif not wall and self.stud.text().startswith("362"):
            self.stud.setText("800S200-54")
            self.track.setText("800T200-54")
            self.spacing.setCurrentIndex(self.spacing.findData(24))
        self.update()

    def use_takeoff(self, mtype, unit, total):
        """A length group is the wall length; an area group a joist area
        (width = area / span)."""
        if mtype == "length":
            self.kind.setCurrentIndex(self.kind.findData("wall"))
            self.length.setValue(total)
        else:
            self.kind.setCurrentIndex(self.kind.findData("joists"))
            if self.span.value():
                self.wide.setValue(total / self.span.value())
        self.update()

    def result(self):
        if self.kind.currentData() == "wall":
            return sc.cfs_wall(self.length.value(), self.tall.value(),
                               self.spacing.currentData(),
                               self.openings.value(), self.corners.value(),
                               self.per_opening.value(), 2,
                               self.bridging.value(), self.stud.text(),
                               self.track.text(), self.waste.value())
        return sc.cfs_joists(self.span.value(), self.wide.value(),
                             self.spacing.currentData(), self.stud.text(),
                             self.track.text(), self.waste.value())

    def update(self, *_):
        try:
            r = self.result()
        except (ValueError, AttributeError) as e:
            self.out.setText(str(e))
            return None
        if self.kind.currentData() == "wall":
            self.out.setText(
                f"<b>{r['studs']:,} studs</b> at {self.tall.value():g} ft "
                f"({r['stud_lf']:,.0f} LF) - <b>{r['track_lf']:,.0f} LF of "
                f"track</b> ({r['track_pieces']:,} pieces at 10 ft) - "
                f"{r['bridging_lf']:,.0f} LF of bridging "
                f"({r.get('bridging_rows', 0)} rows)<br>About "
                f"<b>{r['lb']:,.0f} lb</b> of steel (studs and track, with "
                f"{self.waste.value():g}% waste)")
        else:
            self.out.setText(
                f"<b>{r['joists']:,} joists</b> at {self.span.value():g} ft "
                f"({r['joist_lf']:,.0f} LF) - <b>{r['rim_lf']:,.0f} LF of "
                f"rim track</b><br>About <b>{r['lb']:,.0f} lb</b> of steel")
        return r

    def estimate_rows(self):
        r = self.result()
        stud, track = self.stud.text().upper(), self.track.text().upper()
        if self.kind.currentData() == "wall":
            rows = [(f"Metal studs {stud} x {self.tall.value():g} ft",
                     r["studs"], "ea", "05 40 00"),
                    (f"Metal track {track}", r["track_lf"], "lf",
                     "05 40 00")]
            if r["bridging_lf"]:
                rows.append(("Metal stud bridging", r["bridging_lf"], "lf",
                             "05 40 00"))
            return rows
        return [(f"Metal joists {stud} x {self.span.value():g} ft",
                 r["joists"], "ea", "05 40 00"),
                (f"Metal rim track {track}", r["rim_lf"], "lf", "05 40 00")]

    def text(self):
        r = self.result()
        if self.kind.currentData() == "wall":
            return (f"Metal studs - {self.stud.text().upper()}: {r['studs']} "
                    f"studs, {r['track_lf']:,.0f} LF track, "
                    f"{r['bridging_lf']:,.0f} LF bridging, about "
                    f"{r['lb']:,.0f} lb")
        return (f"Metal joists - {self.stud.text().upper()}: {r['joists']} "
                f"joists, {r['rim_lf']:,.0f} LF rim, about {r['lb']:,.0f} lb")


class SteelTab(_Base):
    """Structural steel weight from a member list (shape, length, count)
    with an allowance for connections."""

    def __init__(self, doc=None):
        super().__init__(doc)
        from PySide6.QtWidgets import QPlainTextEdit
        self.list = QPlainTextEdit(
            "W12x26, 24, 6\nHSS6x6x1/4, 12, 4\nL4x4x1/4, 8, 10")
        self.list.setPlaceholderText("shape, length ft, count - one per line")
        self.list.setMinimumHeight(160)
        self.form.addRow("Members (shape, length ft, count)", self.list)
        self.extra = _spin(10, " % for connections, plates, bolts", 100, 1)
        self.form.addRow("Allowance", self.extra)
        help_ = QLabel("Shapes: W12x26, C10x15.3, WT6x13 (the number after "
                       "the x is lb/ft), HSS6x4x1/4, HSS6.625x0.280, "
                       "PIPE4.5x0.237, L4x4x1/4, PL1/2x12, RD1, SQ1.")
        help_.setWordWrap(True)
        help_.setStyleSheet("color: gray;")
        self.form.addRow(help_)
        self.list.textChanged.connect(self.update)
        self.extra.valueChanged.connect(self.update)
        self.update()

    def result(self):
        return sc.steel_list(self.list.toPlainText(), self.extra.value())

    def update(self, *_):
        try:
            r = self.result()
        except (ValueError, AttributeError) as e:
            self.out.setText(str(e))
            return None
        lines = [f"{x['count']} x {x['shape']} @ {x['length']:g} ft = "
                 f"{x['lb']:,.0f} lb" for x in r["rows"]]
        bad = ("<br><span style='color:#b00020'>Not read: " +
               "; ".join(r["bad"]) + "</span>") if r["bad"] else ""
        self.out.setText(
            "<br>".join(lines) + f"<br><b>{r['lb_with_extra']:,.0f} lb = "
            f"{_c2(r['tons']):,.2f} tons</b> with {self.extra.value():g}% "
            f"allowance ({r['lb']:,.0f} lb of members)" + bad)
        return r

    def estimate_rows(self):
        r = self.result()
        return [(f"Structural steel - {len(r['rows'])} member line(s), "
                 f"{self.extra.value():g}% connection allowance",
                 r["tons"], "ton", "05 12 00")]

    def text(self):
        r = self.result()
        return (f"Structural steel - {len(r['rows'])} line(s): "
                f"{r['lb_with_extra']:,.0f} lb, {_c2(r['tons']):,.2f} tons with "
                f"{self.extra.value():g}% allowance")


class _FormTab(_Base):
    """A tab built from a list of (key, label, widget) rows."""

    def _rows_in(self, rows):
        self.rows = getattr(self, "rows", {})
        for key, label, wdg in rows:
            self.form.addRow(label, wdg)
            self.rows[key] = wdg
            sig = getattr(wdg, "valueChanged", None) or \
                getattr(wdg, "textChanged", None) or \
                wdg.currentIndexChanged
            sig.connect(self.update)

    def _show(self, keys):
        for key, wdg in self.rows.items():
            vis = key in keys
            wdg.setVisible(vis)
            lab = self.form.labelForField(wdg)
            if lab is not None:
                lab.setVisible(vis)

    def update(self, *_):
        try:
            r = self.result()
        except (ValueError, AttributeError, KeyError) as e:
            self.out.setText(str(e))
            return None
        self.out.setText(self.html(r))
        return r


class EarthworkTab(_FormTab):
    """A cut (L x W x D) or a pipe trench: bank, loose and compacted CY
    and truck loads."""

    def __init__(self, doc=None):
        super().__init__(doc)
        self.kind = _combo([("Mass excavation (L x W x D)", "cut"),
                            ("Pipe trench", "trench")])
        self.form.addRow("Work", self.kind)
        self._from_takeoff_row(("area", "length"), self.use_takeoff)
        self.length = _spin(100, " ft", 100000)
        self.wide = _spin(50, " ft", 100000)
        self.area = _spin(0, " sq ft (or L x W)", 10000000)
        self.depth = _spin(3, " ft", 100)
        self.bottom = _spin(3, " ft", 50)
        self.slope = _spin(0, " : 1 (H:V, 0 = vertical)", 3, 2)
        self.pipe = _spin(8, " in", 144, 0)
        self.bedding = _spin(6, " in", 48, 1)
        self.swell = _spin(sitec.SWELL_PCT, " %", 100, 1)
        self.shrink = _spin(sitec.SHRINK_PCT, " %", 50, 1)
        self.truck = _spin(sitec.TRUCK_CY, " loose CY / load", 40, 1)
        self._rows_in((("length", "Length", self.length),
                       ("wide", "Width", self.wide),
                       ("area", "Area", self.area),
                       ("depth", "Depth", self.depth),
                       ("bottom", "Trench bottom width", self.bottom),
                       ("slope", "Side slope", self.slope),
                       ("pipe", "Pipe size", self.pipe),
                       ("bedding", "Bedding depth", self.bedding),
                       ("swell", "Swell (bank to loose)", self.swell),
                       ("shrink", "Shrink (bank to compacted)", self.shrink),
                       ("truck", "Truck", self.truck)))
        self.kind.currentIndexChanged.connect(self._kind_changed)
        self._kind_changed()

    def _kind_changed(self, *_):
        cut = self.kind.currentData() == "cut"
        self._show(("length", "wide", "area", "depth", "swell", "shrink",
                    "truck") if cut else
                   ("length", "depth", "bottom", "slope", "pipe", "bedding",
                    "swell", "truck"))
        self.update()

    def use_takeoff(self, mtype, unit, total):
        if mtype == "area":
            self.kind.setCurrentIndex(self.kind.findData("cut"))
            self.area.setValue(total)
        else:
            self.kind.setCurrentIndex(self.kind.findData("trench"))
            self.length.setValue(total)
        self.update()

    def result(self):
        if self.kind.currentData() == "cut":
            bank = self.area.value() * self.depth.value() / sitec.CY \
                if self.area.value() else None
            return sitec.excavation(self.length.value(), self.wide.value(),
                                    self.depth.value(), bank,
                                    self.swell.value(), self.shrink.value(),
                                    self.truck.value())
        return sitec.trench(self.length.value(), self.depth.value(),
                            self.bottom.value(), self.slope.value(),
                            self.pipe.value(), self.bedding.value(),
                            self.swell.value(), self.truck.value())

    def html(self, r):
        if self.kind.currentData() == "cut":
            return (f"<b>{_c2(r['bank_cy']):,.2f} CY bank</b> - "
                    f"{_c2(r['loose_cy']):,.2f} CY loose to haul "
                    f"(<b>{r['loads']:,} loads</b>), "
                    f"{_c2(r['compacted_cy']):,.2f} CY compacted fill")
        return (f"Top width {r['top_width_ft']:,.1f} ft - <b>"
                f"{_c2(r['excavation_cy']):,.2f} CY excavation</b>, "
                f"{_c2(r['bedding_cy']):,.2f} CY bedding, "
                f"{_c2(r['backfill_cy']):,.2f} CY backfill; "
                f"{_c2(r['loose_cy']):,.2f} CY loose ({r['loads']:,} loads)")

    def estimate_rows(self):
        r = self.result()
        if self.kind.currentData() == "cut":
            return [("Excavation (bank measure)", r["bank_cy"], "cy",
                     "31 23 16"),
                    ("Haul off (loose)", r["loose_cy"], "cy", "31 23 16")]
        return [("Trench excavation", r["excavation_cy"], "cy", "31 23 33"),
                ("Pipe bedding", r["bedding_cy"], "cy", "31 23 33"),
                ("Trench backfill", r["backfill_cy"], "cy", "31 23 33")]

    def text(self):
        return "Earthwork - " + _plain(self.html(self.result()))


class AggregateTab(_FormTab):
    """Stone, sand, topsoil or hot-mix asphalt: CY and tons over an
    area."""

    def __init__(self, doc=None):
        super().__init__(doc)
        self.mat = _combo([(k, k) for k in sitec.TONS_PER_CY])
        self.form.addRow("Material", self.mat)
        self._from_takeoff_row(("area",), self.use_takeoff)
        self.area = _spin(10000, " sq ft", 100000000)
        self.thick = _spin(6, " in", 120, 2)
        self.density = _spin(1.4, " tons / CY", 5, 2)
        self.waste = _spin(5, " %", 50, 1)
        self._rows_in((("area", "Area", self.area),
                       ("thick", "Thickness (compacted)", self.thick),
                       ("density", "Weight", self.density),
                       ("waste", "Waste / compaction", self.waste)))
        self.mat.currentIndexChanged.connect(self._mat_changed)
        self._mat_changed()

    def _mat_changed(self, *_):
        self.density.setValue(sitec.TONS_PER_CY[self.mat.currentData()])
        self.update()

    def use_takeoff(self, mtype, unit, total):
        self.area.setValue(total)
        self.update()

    def result(self):
        return sitec.material_tons(self.area.value(), self.thick.value(),
                                   self.density.value(), self.waste.value())

    def html(self, r):
        return (f"<b>{_c2(r['tons']):,.2f} tons</b> of "
                f"{self.mat.currentText().lower()} - "
                f"{_c2(r['cy_with_waste']):,.2f} CY with "
                f"{self.waste.value():g}% ({_c2(r['cy']):,.2f} CY net)")

    def estimate_rows(self):
        r = self.result()
        code = "32 12 16" if "Asphalt" in self.mat.currentText() else \
            "31 05 16"
        return [(f"{self.mat.currentText()}, {self.thick.value():g} in",
                 r["tons"], "ton", code)]

    def text(self):
        return "Aggregate / asphalt - " + _plain(self.html(self.result()))


class DrywallTab(_FormTab):
    """Gypsum board, tape, joint compound and screws."""

    def __init__(self, doc=None):
        super().__init__(doc)
        self._from_takeoff_row(("area",), self.use_takeoff)
        self.walls = _spin(4000, " sq ft", 10000000)
        self.ceil = _spin(0, " sq ft", 10000000)
        self.openings = _spin(0, " sq ft", 10000000)
        self.board = _combo([(k, k) for k in sitec.BOARD_SF])
        self.layers = QSpinBox()
        self.layers.setRange(1, 4)
        self.waste = _spin(10, " %", 50, 1)
        self.tape = _spin(sitec.TAPE_LF_PER_1000, " LF / 1,000 SF", 2000, 0)
        self.mud = _spin(sitec.COMPOUND_LB_PER_1000, " lb / 1,000 SF", 1000,
                         0)
        self.screws = _spin(sitec.SCREWS_PER_1000, " / 1,000 SF", 5000, 0)
        self._rows_in((("walls", "Wall area (one face)", self.walls),
                       ("ceil", "Ceiling area", self.ceil),
                       ("openings", "Less openings", self.openings),
                       ("board", "Board size", self.board),
                       ("layers", "Layers", self.layers),
                       ("waste", "Waste", self.waste),
                       ("tape", "Tape", self.tape),
                       ("mud", "Joint compound", self.mud),
                       ("screws", "Screws", self.screws)))
        self.update()

    def use_takeoff(self, mtype, unit, total):
        self.walls.setValue(total)
        self.update()

    def result(self):
        return sitec.drywall(self.walls.value(), self.ceil.value(),
                             self.openings.value(),
                             self.board.currentData(), self.layers.value(),
                             self.waste.value(), self.tape.value(),
                             self.mud.value(), self.screws.value())

    def html(self, r):
        return (f"<b>{r['boards']:,} boards</b> ({self.board.currentText()})"
                f" for {r['net_sf']:,.0f} SF with {self.waste.value():g}% "
                f"waste - {r['tape_lf']:,.0f} LF tape, "
                f"{r['compound_lb']:,.0f} lb joint compound, "
                f"{r['screws']:,} screws")

    def estimate_rows(self):
        r = self.result()
        return [(f"Gypsum board {self.board.currentText()}", r["boards"],
                 "ea", "09 29 00"),
                ("Joint tape", r["tape_lf"], "lf", "09 29 00"),
                ("Joint compound", r["compound_lb"], "lb", "09 29 00"),
                ("Drywall screws", r["screws"], "ea", "09 29 00")]

    def text(self):
        return "Drywall - " + _plain(self.html(self.result()))


class PaintTab(_FormTab):
    """Gallons of paint and primer for an area."""

    def __init__(self, doc=None):
        super().__init__(doc)
        self._from_takeoff_row(("area",), self.use_takeoff)
        self.area = _spin(5000, " sq ft", 100000000)
        self.coats = QSpinBox()
        self.coats.setRange(1, 5)
        self.coats.setValue(2)
        self.cover = _spin(sitec.PAINT_SF_PER_GAL, " SF / gal per coat",
                           2000, 0)
        self.primer = QSpinBox()
        self.primer.setRange(0, 3)
        self.pcover = _spin(300, " SF / gal per coat", 2000, 0)
        self.waste = _spin(10, " %", 50, 1)
        self._rows_in((("area", "Area to paint", self.area),
                       ("coats", "Finish coats", self.coats),
                       ("cover", "Finish coverage", self.cover),
                       ("primer", "Primer coats", self.primer),
                       ("pcover", "Primer coverage", self.pcover),
                       ("waste", "Waste", self.waste)))
        self.update()

    def use_takeoff(self, mtype, unit, total):
        self.area.setValue(total)
        self.update()

    def result(self):
        return sitec.paint(self.area.value(), self.coats.value(),
                           self.cover.value(), self.primer.value(),
                           self.pcover.value(), self.waste.value())

    def html(self, r):
        out = (f"<b>{r['finish_gal']:,} gal finish</b> "
               f"({r['finish_pails']} five-gallon + {r['finish_extra']} gal)")
        if r["primer_gal"]:
            out += (f", <b>{r['primer_gal']:,} gal primer</b> "
                    f"({r['primer_pails']} five-gallon + "
                    f"{r['primer_extra']} gal)")
        return out

    def estimate_rows(self):
        r = self.result()
        rows = [(f"Paint, {self.coats.value()} coats", r["finish_gal"],
                 "gal", "09 91 00")]
        if r["primer_gal"]:
            rows.append(("Primer", r["primer_gal"], "gal", "09 91 00"))
        return rows

    def text(self):
        return "Paint - " + _plain(self.html(self.result()))


def _plain(html):
    import re as _re
    return _re.sub(r"<[^>]+>", "", html)


def _ft_in(ft):
    inches = int(round(ft * 12))
    return f"{inches // 12}'-{inches % 12}\""


class CalculatorDialog(QDialog):
    def __init__(self, parent=None, doc=None, tab=0):
        super().__init__(parent)
        self.setWindowTitle("Calculators")
        self.resize(560, 720)
        v = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.concrete = ConcreteTab(doc)
        self.masonry = MasonryTab(doc)
        self.roofing = RoofingTab(doc)
        self.tabs.addTab(self.concrete, "Concrete")
        self.tabs.addTab(self.masonry, "Brick && Block")
        self.tabs.addTab(self.roofing, "Roofing")
        self.rebar = RebarTab(doc)
        self.beam = BeamTab(doc)
        self.column = ColumnTab(doc)
        self.footing = FootingTab(doc)
        self.studs = MetalStudTab(doc)
        self.steel = SteelTab(doc)
        self.earth = EarthworkTab(doc)
        self.aggregate = AggregateTab(doc)
        self.drywall = DrywallTab(doc)
        self.paint = PaintTab(doc)
        for w, name in ((self.rebar, "Rebar"), (self.beam, "Beam / Header"),
                        (self.column, "Column / Post"),
                        (self.footing, "Footing Size"),
                        (self.studs, "Metal Studs"),
                        (self.steel, "Structural Steel"),
                        (self.earth, "Earthwork"),
                        (self.aggregate, "Aggregate / Asphalt"),
                        (self.drywall, "Drywall"), (self.paint, "Paint")):
            # the longer forms scroll rather than stretch the window
            area = QScrollArea()
            area.setWidgetResizable(True)
            area.setWidget(w)
            self.tabs.addTab(area, name)
        self.tabs.setCurrentIndex(tab)
        v.addWidget(self.tabs, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        copy = bb.addButton("Copy Results", QDialogButtonBox.ActionRole)
        copy.clicked.connect(self.copy)
        # Nov 20: the quantities straight onto the estimate
        self.doc = doc
        self.add_btn = bb.addButton("Add to Estimate",
                                    QDialogButtonBox.ActionRole)
        self.add_btn.clicked.connect(lambda: self.add_to_estimate())
        self.tabs.currentChanged.connect(lambda _i: self._can_add())
        self._can_add()
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def _tab(self):
        w = self.tabs.currentWidget()
        return w.widget() if isinstance(w, QScrollArea) else w

    def _can_add(self):
        ok = self.doc is not None and hasattr(self._tab(), "estimate_rows")
        self.add_btn.setEnabled(ok)
        self.add_btn.setToolTip(
            "" if ok else "Open a drawing to add to its estimate" if
            self.doc is None else "This tab is a check - nothing to add")
        return ok

    def add_to_estimate(self):
        """The current tab's quantities as estimate lines (price them on
        the estimate). Returns the new line ids."""
        from . import estimate_lines as el
        from .dmoney import half_up
        if not self._can_add():
            return []
        tab = self._tab()
        try:
            rows = [r for r in tab.estimate_rows() if r[1]]
        except ValueError as e:
            tab.out.setText(str(e))
            return []
        if not rows:
            return []
        note = tab.text()
        ids = el.add(self.doc, [el.new_line(desc=d, qty=half_up(q, 2),
                                            unit=u, code=c,
                                            source="Calculators", note=note)
                                for d, q, u, c in rows])
        win = self.parent()
        if win is not None and hasattr(win, "_doc_edited"):
            win._doc_edited()
        tab.out.setText(tab.out.text() + f"<br><i>Added {len(ids)} line(s) "
                        "to the estimate - price them there.</i>")
        return ids

    def copy(self):
        t = self._tab().text()
        QApplication.clipboard().setText(t)
        return t
