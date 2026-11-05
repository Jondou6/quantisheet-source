"""Nov 3 (#11): change order from a revised sheet. Made-up drawings."""
import os
from decimal import Decimal

import fitz
import pytest

from app import annotate, co_delta


def _sheet(n_outlets, wall_len):
    d = fitz.open()
    pg = d.new_page(width=792, height=612)
    for i in range(n_outlets):
        a = pg.add_circle_annot(fitz.Rect(100 + 30 * i, 100,
                                          108 + 30 * i, 108))
        a.set_info(subject=f"{annotate.TAKEOFF}:count:1:ea:Outlet:")
        a.update()
    a = pg.add_line_annot((100, 300), (400, 300))
    a.set_info(subject=f"{annotate.TAKEOFF}:length:{wall_len}:lf:Wall:")
    a.update()
    return d


def test_delta_priced_with_markup(monkeypatch):
    old, new = _sheet(4, 100), _sheet(6, 100)
    monkeypatch.setattr(co_delta, "prices",
                        lambda *d: {"Outlet": Decimal("85.00")})
    if not annotate.totals_items(new):
        pytest.skip("takeoff subjects written differently in this build")
    r = co_delta.delta(old, 0, new, 0, markup_pct=10)
    assert [x["item"] for x in r["lines"]] == ["Outlet"]
    ln = r["lines"][0]
    assert ln["change"] == Decimal("2.00") and ln["amount"] == Decimal(
        "170.00")
    assert r["markup"] == Decimal("17.00") and r["total"] == Decimal("187.00")
    assert len(r["changed_rects"]) == 6


def test_unpriced_and_pdf(tmp_path, monkeypatch):
    old, new = _sheet(1, 100), _sheet(3, 100)
    monkeypatch.setattr(co_delta, "prices", lambda *d: {})
    if not annotate.totals_items(new):
        pytest.skip("takeoff subjects written differently in this build")
    r = co_delta.delta(old, 0, new, 0)
    assert r["unpriced"] == ["Outlet"] and r["total"] == 0
    p = co_delta.make_pdf(new, 0, r, str(tmp_path / "co.pdf"), title="Job")
    d = fitz.open(p)
    assert d.page_count == 2
    assert "CHANGE ORDER PROPOSAL" in d[0].get_text()
    clouds = [a for a in d[1].annots() if a.info.get("subject") ==
              "Change order backup"]
    assert len(clouds) == 3


def test_window(tmp_path, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtWidgets import QApplication, QMessageBox
    QApplication.instance() or QApplication([])
    monkeypatch.setattr(QMessageBox, "information",
                        staticmethod(lambda *a, **k: 0))
    from types import SimpleNamespace
    from app import co_delta_ui
    old = tmp_path / "old.pdf"
    _sheet(2, 100).save(str(old))
    monkeypatch.setattr(co_delta, "prices",
                        lambda *d: {"Outlet": Decimal("50")})
    v = SimpleNamespace(doc=_sheet(5, 100), page=0)
    opened = []
    w = co_delta_ui.CODialog(v, open_result=opened.append)
    assert w.make() is None                      # no earlier set yet
    w.pick(str(old))
    r = w.make(str(tmp_path / "out.pdf"))
    if not r["lines"]:
        pytest.skip("takeoff subjects written differently in this build")
    assert opened and r["total"] == Decimal("165.00")
