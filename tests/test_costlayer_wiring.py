"""Wiring for Chief's v27 (second symbol) and v28-v30 (cost layer)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz                                                   # noqa: E402,F401
import pytest                                                 # noqa: E402
from PySide6.QtGui import QAction                             # noqa: E402
from test_gui import win, qapp                                # noqa: E402,F401

from app import assembly_codes as ac, costlayer_ui, settings


LIB = ("Biditem Code,Description,Unit,Trade,Activity Code,Resource Code,"
       "Type,Component,Qty per Unit,Component Unit,Rate\n"
       "00100,Partition,LF,Framing,00100.01,LAB01,L,Carpenter,0.5,HR,60\n"
       "00100,Partition,LF,Framing,00100.01,MAT01,M,Studs,1,LF,4\n")


@pytest.fixture
def lib_file(tmp_path, monkeypatch):
    p = tmp_path / "lib.csv"
    p.write_text(LIB, encoding="utf-8")
    store = {}
    monkeypatch.setattr(settings, "get", lambda k, d=None: store.get(k, d))
    monkeypatch.setattr(settings, "set", lambda k, v: store.__setitem__(k, v))
    store[costlayer_ui.KEY] = str(p)
    return p


def _items():
    return [{"group": "Walls", "type": "length", "unit": "LF",
             "value": 100, "page": 0, "rect": [0, 0, 10, 10]}]


def test_menu_has_cost_layer(win):
    names = [a.text() for a in win.findChildren(QAction)]
    for t in ("Assembly Library (CivilBid codes)…",
              "Bind Takeoff Group to Assembly…", "Insert Assembly Line…",
              "Bid Summary (Coded Assemblies)…", "Revision Change Report…"):
        assert t in names, t


def test_bind_and_summary(win, tmp_path, lib_file, monkeypatch):
    monkeypatch.setattr(ac.annotate, "takeoff_items",
                        lambda d, *a, **k: _items())
    r = costlayer_ui.bind_dialog(win, group="Walls", code="00100", waste=10)
    assert r == (("Walls", "length", "LF"), "00100")
    dlg = costlayer_ui.summary_dialog(win, show=False)
    # 100 LF: labor 50 h x 60 = 3000; material 110 LF x 4 = 440
    assert str(dlg.result["direct"]) == "3440.00"
    dlg.tax.setValue(10)
    dlg.casc.item(2, 1).setText("10")      # profit
    r = dlg.recalc()
    assert str(r["tax"]) == "44.00"
    assert str(r["total"]) == "3832.40"
    out = dlg.export(str(tmp_path / "s.csv"))
    assert os.path.exists(out)
    dlg.save()
    assert ac.read_job(win._view.doc)["tax_pct"] == "10.0"


def test_no_library_is_explained(win, monkeypatch):
    monkeypatch.setattr(settings, "get", lambda k, d=None: d)
    seen = []
    monkeypatch.setattr(costlayer_ui.QMessageBox, "information",
                        lambda *a, **k: seen.append(a[2]))
    assert costlayer_ui.load_library(win) == {}
    assert seen and "template" in seen[0]
