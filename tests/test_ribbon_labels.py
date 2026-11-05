"""Ribbon labels are never cut ("Dat...ase", "Scop...eets"): a button is
always wide enough for its whole label in the font it ends up with (Jon,
Oct 22: the theme's larger font came after the width was fixed)."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtGui import QAction                             # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget          # noqa: E402

from app.ribbon import RibbonGroup, RibbonPage                # noqa: E402

LABELS = ["Price Database", "Add From Cost Book", "Quick $/SF Estimate",
          "Cost Estimate", "Brick & Block", "Bid Tabs", "Leveling",
          "Scope Sheets", "Bid Build-up", "Checklist", "Location Factors"]


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def _fits(b):
    text = b.text().replace("&&", "&")
    return b.width() >= b.fontMetrics().horizontalAdvance(text) + 8


def test_whole_labels_with_a_large_font(app):
    host = QWidget()
    host.setStyleSheet("#RibbonButton { font-size: 17px; }")
    page = RibbonPage(host)
    acts = [QAction(t, host) for t in LABELS]
    g = page.group("Estimate")
    for a in acts[:1]:
        g.large(a)
    g.small(acts[1:3])
    for a in acts[3:]:
        g.large(a)
    page.resize(500, 120)          # narrower than the buttons: it scrolls
    host.resize(500, 120)
    host.show()
    app.processEvents()
    for b in g.buttons:
        assert _fits(b), (b.text(), b.width())
    assert page.horizontalScrollBar().maximum() > 0
    host.close()
