"""Civil > Production by Depth…: how much a pipe crew slows down in deeper
trench, as a share of its 0-6 ft rate. Used when activities are made from
the takeoff (pipe groups carry their depth band)."""
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QDoubleSpinBox,
                               QFormLayout, QLabel, QVBoxLayout)

from . import heavy


class DepthDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Production by Depth")
        lay = QVBoxLayout(self)
        intro = QLabel(
            "Pipe laid per hour in each depth band, as a share of the "
            "0-6 ft rate. A 35 LF/hr crew at 0.6 lays 21 LF/hr at 10-14 ft. "
            "Starting values are estimates - set them from your own jobs. "
            "New activities use them; existing ones keep their rate.")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        form = QFormLayout()
        f = heavy.depth_factors(heavy.library())
        self.spins = {}
        for k, label in heavy.DEPTH_LABELS.items():
            s = QDoubleSpinBox()
            s.setRange(0.05, 2.0)
            s.setSingleStep(0.05)
            s.setDecimals(2)
            s.setValue(f[k])
            if k == "0-6":
                s.setEnabled(False)
            self.spins[k] = s
            form.addRow(label + ":", s)
        lay.addLayout(form)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.save)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def values(self):
        return {k: s.value() for k, s in self.spins.items()}

    def save(self):
        heavy.set_settings({"depth_factors": self.values()})
        self.accept()


def add_menu(mw, parent):
    mw._act(parent, "Production by Depth…", None,
            lambda: DepthDialog(mw).exec(), False)
