"""Dialogs fit the screen and can be moved, minimized and maximized (Jon,
Oct 22: with large Windows text the Roofing calculator was taller than the
screen - the title bar was off the top, so it couldn't be moved)."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import Qt                                   # noqa: E402
from PySide6.QtWidgets import (QApplication, QDialog,           # noqa: E402
                               QDialogButtonBox, QDoubleSpinBox,
                               QFormLayout, QLabel, QMessageBox,
                               QScrollArea, QVBoxLayout)

from app import dialog_fit                                      # noqa: E402


@pytest.fixture
def app():
    a = QApplication.instance() or QApplication([])
    dialog_fit.install(a)
    return a


def _tall(rows=80):
    d = QDialog()
    v = QVBoxLayout(d)
    form = QFormLayout()
    for i in range(rows):
        form.addRow(f"Row {i}", QDoubleSpinBox())
    v.addLayout(form)
    v.addWidget(QLabel("result"))
    bb = QDialogButtonBox(QDialogButtonBox.Close)
    bb.rejected.connect(d.reject)
    v.addWidget(bb)
    return d, bb


def test_tall_dialog_scrolls_and_fits(app):
    d, bb = _tall()
    d.show()
    app.processEvents()
    a = d.screen().availableGeometry()
    assert d.height() <= a.height()
    assert d.frameGeometry().top() >= a.top()      # title bar on screen
    assert d.findChild(QScrollArea, "FitScroll") is not None
    # the buttons stay outside the scroll area, visible
    assert bb.parent() is d and bb.isVisible()
    # every row is still there (inside the scroll area)
    assert len(d.findChildren(QDoubleSpinBox)) == 80
    assert all(s.isVisibleTo(d) for s in d.findChildren(QDoubleSpinBox))
    d.close()


def test_every_dialog_can_be_minimized_and_maximized(app):
    d, _ = _tall(2)
    d.show()
    app.processEvents()
    f = d.windowFlags()
    assert f & Qt.WindowMinimizeButtonHint and f & Qt.WindowMaximizeButtonHint
    assert f & Qt.WindowCloseButtonHint
    # a small one is left alone: no scroll area
    assert d.findChild(QScrollArea, "FitScroll") is None
    d.close()


def test_message_boxes_untouched(app):
    m = QMessageBox()
    m.setText("hello")
    m.show()
    app.processEvents()
    assert not m.property(dialog_fit.DONE)
    m.close()


def test_calculator_dialog_fits(app):
    from app.calculators_ui import CalculatorDialog
    d = CalculatorDialog(None, None, 2)
    d.show()
    app.processEvents()
    a = d.screen().availableGeometry()
    assert d.frameGeometry().top() >= a.top()
    assert d.height() <= a.height()
    labels = [w.text() for w in d.findChildren(QLabel)]
    assert any(t == "Ice && water" for t in labels)   # shows "Ice & water"
    d.close()
