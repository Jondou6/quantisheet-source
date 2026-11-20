"""Takeoff > Wood Sheathing Helper (Nov 19)."""
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox,
                               QDoubleSpinBox, QFormLayout, QLabel,
                               QVBoxLayout)

from . import sheathing as sh


def area_groups(doc):
    """[(label, group)] of the takeoff's area lines."""
    from . import estimate
    out = []
    for g in estimate.lines(doc):
        u = str(g.get("unit") or "").lower()
        if u in ("sq ft", "sf", "ft2", "sqft") and g.get("quantity"):
            out.append((f"{g['name']} - {g['quantity']:,.1f} {g['unit']}",
                        g))
    return out


class SheathingDialog(QDialog):
    def __init__(self, doc, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.added = None
        self.setWindowTitle("Wood Sheathing Helper")
        v = QVBoxLayout(self)
        f = QFormLayout()
        self.area = QComboBox()
        self.groups = area_groups(doc)
        for label, _g in self.groups:
            self.area.addItem(label)
        if not self.groups:
            self.area.addItem("(no area takeoff yet - measure the deck or "
                              "wall first)")
        f.addRow("Area takeoff:", self.area)
        self.use = QComboBox()
        self.use.addItems(list(sh.USES))
        f.addRow("Used as:", self.use)
        self.spacing = QComboBox()
        self.spacing.addItems([f'{s:g}"' for s in sh.SPACINGS])
        self.spacing.setCurrentText('24"')
        f.addRow("Framing spacing (o.c.):", self.spacing)
        self.waste = QDoubleSpinBox()
        self.waste.setRange(0, 50)
        self.waste.setValue(10)
        self.waste.setSuffix(" %")
        f.addRow("Waste:", self.waste)
        v.addLayout(f)
        self.result = QLabel()
        self.result.setWordWrap(True)
        v.addWidget(self.result)
        src = QLabel(f"Source: {sh.SOURCE}. Check the drawings' structural "
                     "notes before ordering.")
        src.setWordWrap(True)
        src.setStyleSheet("color: gray;")
        v.addWidget(src)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        self.add_btn = bb.addButton("Add to Estimate",
                                    QDialogButtonBox.ActionRole)
        self.add_btn.clicked.connect(lambda: self.add_to_estimate())
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        for w in (self.area, self.use, self.spacing):
            w.currentIndexChanged.connect(lambda _=0: self.refresh())
        self.waste.valueChanged.connect(lambda _=0: self.refresh())
        self.refresh()

    def choice(self):
        s = float(self.spacing.currentText().rstrip('"'))
        p = sh.pick(self.use.currentText(), s)
        g = self.groups[self.area.currentIndex()][1] if self.groups \
            else None
        n = sh.sheets(g["quantity"], self.waste.value()) if g else 0
        return p, g, n

    def refresh(self):
        try:
            p, g, n = self.choice()
        except sh.SheathingError as e:
            self.result.setText(str(e))
            self.add_btn.setEnabled(False)
            return None
        self.result.setText(
            f"<b>{p['rating']}</b>, {p['thickness']} "
            f"(also made {', '.join(p['thicknesses'][1:]) or '-'}): "
            f"{p['note']}." + (f"<br><b>{n}</b> sheets of 4x8 for "
                               f"{g['quantity']:,.1f} SF with "
                               f"{self.waste.value():g}% waste." if g else ""))
        self.add_btn.setEnabled(g is not None)
        return p

    def add_to_estimate(self):
        """One estimate line, linked to the area: the sheet count follows
        the takeoff. Returns the line id."""
        from . import estimate_lines as el
        p, g, n = self.choice()
        if g is None:
            return None
        link = {"name": g["name"], "type": g["type"], "unit": g["unit"],
                "formula": sh.formula(self.waste.value())}
        ids = el.add(self.doc, [el.new_line(
            desc=sh.description(p), unit="ea", link=link,
            source="Wood Sheathing Helper",
            note=f"{sh.SOURCE}; {self.waste.value():g}% waste")])
        self.added = ids[0]
        self.result.setText(self.result.text() +
                            "<br>Added to the estimate - price it there.")
        return self.added
