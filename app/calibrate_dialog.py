"""Set Scale: one dialog, like Bluebeam's Calibrate."""
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QDialog,
                               QDialogButtonBox, QFormLayout, QHBoxLayout,
                               QLabel, QLineEdit, QRadioButton, QVBoxLayout)

from . import settings, takeoff


class CalibrateDialog(QDialog):
    def __init__(self, dist_points, page_count, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Set Scale")
        self.dist = dist_points
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(
            f"The line you drew is {dist_points / 72:.3f}\" long on paper.\n"
            "Type what it measures on the drawing:"))
        form = QFormLayout()
        self.length = QLineEdit()
        self.length.setPlaceholderText("e.g.  4'-6\"   or   12.5   or   3 m")
        form.addRow("Length:", self.length)
        self.unit = QComboBox()
        self.unit.addItems(takeoff.UNITS)
        last = settings.get("calibrate_unit") or "ft"
        if last in takeoff.UNITS:
            self.unit.setCurrentText(last)
        form.addRow("Units:", self.unit)
        lay.addLayout(form)

        row = QHBoxLayout()
        self.this_page = QRadioButton("This page")
        self.all_pages = QRadioButton(f"All {page_count} pages")
        grp = QButtonGroup(self)
        grp.addButton(self.this_page)
        grp.addButton(self.all_pages)
        self.this_page.setChecked(True)
        row.addWidget(QLabel("Apply to:"))
        row.addWidget(self.this_page)
        row.addWidget(self.all_pages)
        row.addStretch()
        if page_count > 1:
            lay.addLayout(row)

        self.preview = QLabel(" ")
        self.preview.setStyleSheet("color: #555;")
        lay.addWidget(self.preview)
        self.bb = QDialogButtonBox(QDialogButtonBox.Ok |
                                   QDialogButtonBox.Cancel)
        self.bb.accepted.connect(self.accept)
        self.bb.rejected.connect(self.reject)
        lay.addWidget(self.bb)
        self.length.textChanged.connect(self._update)
        self.unit.currentTextChanged.connect(self._update)
        self._update()
        self.length.setFocus()

    def values(self):
        """(real length, unit, all pages) or None if not valid."""
        parsed = takeoff.parse_length(self.length.text())
        if not parsed or parsed[0] <= 0:
            return None
        real, unit = parsed
        return real, unit or self.unit.currentText(), \
            self.all_pages.isChecked()

    def _update(self):
        v = self.values()
        ok = self.bb.button(QDialogButtonBox.Ok)
        ok.setEnabled(v is not None)
        if v is None:
            self.preview.setText("Enter a length to see the scale."
                                 if self.length.text().strip() else " ")
            return
        real, unit, _ = v
        if unit != self.unit.currentText():
            self.unit.blockSignals(True)
            self.unit.setCurrentText(unit)
            self.unit.blockSignals(False)
        self.preview.setText("Scale: " +
                             takeoff.scale_text(self.dist / real, unit))

    def accept(self):
        v = self.values()
        if v:
            settings.set("calibrate_unit", v[1])
            super().accept()


def ask_calibration(parent, dist_points, page_count):
    """Show the dialog; returns (real, unit, all_pages) or None."""
    dlg = CalibrateDialog(dist_points, page_count, parent)
    if dlg.exec() == QDialog.Accepted:
        return dlg.values()
    return None
