"""Production Rates: every family row explains its unit, what the quantity
is measured from and what min / max days mean (review 0.12.35 item 18)."""
import pytest

QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from app.pm import productivity as prod                       # noqa: E402
from app.pm import productivity_ui as pui                     # noqa: E402


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    from app import settings
    d = tmp_path / "cfg"
    monkeypatch.setattr(settings, "DIR", str(d))
    monkeypatch.setattr(settings, "PATH", str(d / "settings.json"))
    monkeypatch.setattr(settings, "_cache", {})
    return d


@pytest.fixture
def qapp():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def test_every_family_tooltip_names_unit_source_and_min_max():
    for key, fam in prod.FAMILIES.items():
        tip = pui.family_tooltip(fam)
        assert f"Unit: {fam['unit']} of {fam['of']}" in tip, key
        assert "Quantity:" in tip, key
        assert fam["qty"] in pui.QTY_FROM, key     # a readable source
        assert pui.QTY_FROM[fam["qty"]] in tip, key
        if fam["takeoff"]:
            assert "takeoff" in tip, key
        assert "Min days" in tip and "Max days" in tip, key


def test_takeoff_words_are_readable():
    assert pui._takeoff_words(r"clearing|grubbing") == "clearing, grubbing"
    assert pui._takeoff_words(r"roof(?!\s*deck)") == "roof"
    assert pui._takeoff_words(r"\bslab|\bS\.?O\.?G\b") == "slab, S.O.G"
    assert pui._takeoff_words(r"window|curtain ?wall") == \
        "window, curtain wall"


def test_every_cell_of_every_family_row_has_the_tooltip(qapp, cfg):
    dlg = pui.edit_rates(show=False)
    t = dlg.table
    assert t.rowCount() == len(prod.FAMILIES)
    for r in range(t.rowCount()):
        tips = {t.item(r, c).toolTip() for c in range(t.columnCount())}
        assert len(tips) == 1
        tip = tips.pop()
        assert "Unit:" in tip and "Min days" in tip
    for r in range(dlg.assume.rowCount()):
        assert dlg.assume.item(r, 0).toolTip()
    dlg.close()
