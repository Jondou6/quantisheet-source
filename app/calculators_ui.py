"""Concrete, Brick / Block and Roofing calculator dialogs (Estimate tab).

Type the sizes, or fill them from a takeoff group on the open drawing (an
area group fills a slab's or a wall's area, a length group the length).
Results update as you type; Copy Results puts them on the clipboard."""
from PySide6.QtWidgets import (QApplication, QComboBox, QDialog,
                               QDialogButtonBox, QDoubleSpinBox, QFormLayout,
                               QHBoxLayout, QLabel, QPushButton, QSpinBox,
                               QTabWidget, QVBoxLayout, QWidget)

from . import calculators as calc

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
            f"<b>{r['cy_with_waste']:,.2f} cubic yards (CY)</b> with "
            f"{self.waste.value():g}% waste ({r['cy']:,.2f} CY net, "
            f"{r['cf']:,.1f} cu ft)<br>Order: <b>{r['order_cy']:,.2f} CY</b>"
            f" - {r['trucks']} truck(s) at {calc.TRUCK_CY:g} CY")
        return r

    def text(self):
        r = self.result()
        return (f"Concrete - {NAMES[self.shape.currentData()]} x "
                f"{self.qty.value()}: {r['cy_with_waste']:.2f} CY with "
                f"{self.waste.value():g}% waste; order {r['order_cy']:.2f} CY"
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
                f"({g['cy']:,.2f} CY net; order {g['order_cy']:,.2f} CY)")

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
            f"<b>{r['sand_tons']:,.2f} tons</b><br>"
            + (self._grout_text(r) + "<br>" if self._grout_text(r) else "")
            + "<span style='color:gray'>Mortar, sand and grout rates are "
            "starting points; use your supplier's.</span>")
        return r

    def text(self):
        r = self.result()
        return (f"Masonry - {self.unit.currentText()}: "
                f"{r['units_with_waste']} units with {self.waste.value():g}% "
                f"waste over {r['net_sf']:.1f} sf; {r['mortar_bags']} mortar "
                f"bags; {r['sand_tons']:.2f} tons sand"
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
                             else f"{v:,.2f}")
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
        lines = [f"<b>{r['squares_with_waste']:,.2f} squares</b> with "
                 f"{self.waste.value():g}% waste ({r['squares']:,.2f} net, "
                 f"{r['sloped_sf']:,.0f} sq ft sloped; factor "
                 f"{r['factor']:.3f})",
                 f"Order: <b>{r['order_squares']:,.2f} squares</b>"]
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

    def text(self):
        r = self.result()
        parts = [f"Roofing - {self.kind.currentText()}: "
                 f"{r['squares_with_waste']:.2f} squares with "
                 f"{self.waste.value():g}% waste "
                 f"(order {r['order_squares']:.2f})"]
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


class CalculatorDialog(QDialog):
    def __init__(self, parent=None, doc=None, tab=0):
        super().__init__(parent)
        self.setWindowTitle("Concrete, Masonry and Roofing Calculators")
        self.resize(560, 720)
        v = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.concrete = ConcreteTab(doc)
        self.masonry = MasonryTab(doc)
        self.roofing = RoofingTab(doc)
        self.tabs.addTab(self.concrete, "Concrete")
        self.tabs.addTab(self.masonry, "Brick && Block")
        self.tabs.addTab(self.roofing, "Roofing")
        self.tabs.setCurrentIndex(tab)
        v.addWidget(self.tabs, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        copy = bb.addButton("Copy Results", QDialogButtonBox.ActionRole)
        copy.clicked.connect(self.copy)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def copy(self):
        t = self.tabs.currentWidget().text()
        QApplication.clipboard().setText(t)
        return t
