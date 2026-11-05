"""r36 v2 step 1: the Estimating Tools window - Bid-Day 'Use This Quote'
puts the picked quote in the estimate (one Undo in the main window takes
it back), and the Quote, Material Order List and Estimate vs Actual pages
show takeoff groups priced by a unit cost and civil activities too.
Made-up data only."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QDialog                             # noqa: E402

from app import assemblies, estimate, estimate_lines as EL, heavy  # noqa: E402
from app.estimating import bidday, items, ui                      # noqa: E402
from estimate_helpers import area                                  # noqa: E402
from test_gui import ANSWERS, win, qapp                            # noqa: E402,F401
from test_r36_bidday import _sheet                                 # noqa: E402
from test_r36_end_to_end import LIB                                # noqa: E402


@pytest.fixture(autouse=True)
def _iso(tmp_path, monkeypatch):
    monkeypatch.setattr(assemblies, "LIBRARY_PATH",
                        str(tmp_path / "assemblies.json"))
    monkeypatch.setattr(QDialog, "exec", lambda self, *a: 0)
    monkeypatch.setattr(heavy, "library", lambda: LIB)   # no price db


def _bid(d):
    return [ln for ln in EL.read(d) if ln["source"].startswith("Bid day:")]


def test_use_this_quote_and_undo(win, qapp):
    d = win._view.doc
    bidday.save(d, _sheet())
    dlg = ui.open_tools(win, "bidday")
    pg = dlg.page("bidday")
    pg.refresh()
    pg.package.setCurrentText("Test earthwork")
    assert pg.bidder.itemText(0) == ui.LOWEST_COMPLETE
    pg.bidder.setCurrentText("Test Sub B")
    pg.use_quote()
    assert len(_bid(d)) == 3 and "plug" in pg.msg.text().lower()
    pg.use_quote()                                  # again: replaced
    assert len(_bid(d)) == 3
    win.undo()
    assert len(_bid(win._view.doc)) == 3            # back one step: once
    win.undo()
    assert _bid(win._view.doc) == []


def test_remove_quote_button(win, qapp):
    d = win._view.doc
    bidday.save(d, _sheet())
    pg = ui.open_tools(win, "bidday").page("bidday")
    pg.refresh()
    pg.package.setCurrentText("Test earthwork")
    pg.use_quote()
    pg.remove_quote()
    assert _bid(d) == []


def test_pages_show_takeoff_and_civil_items(win, qapp):
    d = win._view.doc
    area(d, "Test tile", 10, 10)
    estimate.set_price(d, "Test tile", "area", "sq ft", unit_cost=8,
                       cost_type="Material")
    job = heavy.blank()
    heavy.add_activity(job, "Test fine grade", qty=1000, unit="sq ft",
                       crew="TESTGRADE", rate=500,
                       materials=[{"desc": "Test seed", "qty_per": "0.01",
                                   "cost": "20", "unit": "lb"}])
    heavy.write(d, job)
    tid = items.takeoff_id("Test tile", "area", "sq ft")
    dlg = ui.open_tools(win, "quote")
    q = dlg.page("quote")
    q.refresh()
    assert tid in [r["id"] for r in q.rows] and len(q.rows) == 2
    m = dlg.page("materials")
    m.refresh()
    descs = [m.table.item(i, 2).text() for i in range(m.table.rowCount())]
    assert sorted(descs) == ["Test seed", "Test tile"]
    a = dlg.page("actuals")
    a.refresh()
    assert tid in a.ids and len(a.ids) == 2
    a.set_actual(tid, cost="700")
    from app.estimating import actuals
    assert actuals.read(d)[tid]["cost"] == "700.00"
