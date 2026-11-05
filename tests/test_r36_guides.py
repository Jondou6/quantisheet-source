"""r36 v2 step 4: short in-app guides. Every Estimating Tools page has a
'How to' text, and a one-page takeoff-to-quote walkthrough; both open
from the dialog's button row (no extra page in the drop-down) without
blocking."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton       # noqa: E402

from app import settings                                      # noqa: E402
from app.estimating import guides, ui                         # noqa: E402


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", None)


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def test_every_page_has_a_short_how_to():
    keys = [k for k, _l in ui.PAGES]
    assert sorted(guides.GUIDES) == sorted(keys)
    for k in keys:
        title, text = guides.guide(k)
        steps = [ln for ln in text.splitlines() if ln[:2].strip().rstrip(
            ".").isdigit()]
        assert title and 3 <= len(steps) <= 10, k
        assert len(text.splitlines()) <= 40, k


def test_walkthrough_covers_takeoff_to_quote():
    title, text = guides.walkthrough()
    low = text.lower()
    for w in ("takeoff", "template", "error check", "quote", "material",
              "bid day", "crew hours", "actual"):
        assert w in low, w
    assert len(text.splitlines()) <= 60


def test_dialog_buttons_open_the_guides(app):
    dlg = ui.EstimatingTools(None, None, "quote")
    texts = [b.text() for b in dlg.findChildren(QPushButton)]
    assert "How To…" in texts and "Takeoff to Quote Walkthrough…" in texts
    assert dlg.stack.count() == len(ui.PAGES)             # no extra page
    g = dlg.show_guide()
    assert g.isVisible() and guides.guide("quote")[1] in g.text()
    w = dlg.show_walkthrough()
    assert w.isVisible() and guides.walkthrough()[1] in w.text()
    dlg.go("bidday")
    assert guides.guide("bidday")[1] in dlg.show_guide().text()
    for x in (g, w, dlg):
        x.close()


def test_templates_page_has_starter_buttons(app):
    dlg = ui.EstimatingTools(None, None, "templates")
    texts = [b.text() for b in dlg.page("templates").findChildren(
        QPushButton)]
    for t in ("Add Starter Templates", "Add EXAMPLE Crews",
              "Civil: Starter Pay Items + Pipe Material",
              "Suggest Takeoff Groups"):
        assert t in texts
    dlg.close()
