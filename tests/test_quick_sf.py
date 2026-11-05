"""Quick $/SF estimate from your own past jobs (Job Cost Feedback), as one
allowance line per CSI division. Made-up history only."""
import os
from decimal import Decimal

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import (estimate_lines as EL, pricehistory as ph,       # noqa: E402
                 quick_sf as Q, settings)
from estimate_helpers import blank_doc                           # noqa: E402


@pytest.fixture(autouse=True)
def _cfg(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", {"author": "Test Estimator"})
    os.makedirs(settings.DIR, exist_ok=True)


def _history():
    """3 past 'Test Garage' jobs at $80, $90 and $100 per SF (different
    sizes), 60% of each in division 03 and 40% in 09."""
    ids = []
    for n, (sf, cost) in enumerate([(2000, 160000), (1000, 90000),
                                    (1500, 150000)], 1):
        c = Decimal(cost)
        jid = ph.add_job(f"TG-{n}", f"Test garage {n}", lines=[
            {"code": "03 31 13", "desc": "Test slab", "unit": "SF",
             "qty": Decimal(sf), "unit_cost": c * Decimal("0.6") / sf},
            {"code": "09 91 23", "desc": "Test paint", "unit": "LS",
             "qty": Decimal(1), "unit_cost": c * Decimal("0.4")}],
            type="Test Garage", bid_total=c)
        Q.set_job_sf(jid, sf)
        ids.append(jid)
    return ids


def test_median_and_range_from_past_jobs():
    _history()
    res = Q.estimate("Test Garage", 1000)
    assert res["count"] == 3
    assert res["per_sf"] == Decimal("90.00")
    assert res["median"] == Decimal("90000.00")
    assert (res["low"], res["high"]) == (Decimal("80000.00"),
                                         Decimal("100000.00"))
    text = Q.describe(res)
    assert "$90,000.00" in text and "$80,000.00 - $100,000.00" in text


def test_one_allowance_line_per_division_adding_up():
    _history()
    res = Q.estimate("test garage", 1000)            # any case
    assert [(x["division"], x["amount"]) for x in res["lines"]] == [
        ("03", Decimal("54000.00")), ("09", Decimal("36000.00"))]
    lines = Q.to_lines(res)
    assert [x["code"] for x in lines] == ["03 00 00", "09 00 00"]
    assert all(x["cost_type"] == "Allowance" for x in lines)
    d = blank_doc()
    EL.add(d, lines)
    assert EL.total(EL.priced(d)) == Decimal("90000.00")


def test_no_history_says_so_and_creates_nothing():
    _history()
    assert Q.estimate("Test Warehouse", 1000) is None
    assert "No past jobs" in Q.describe(None, "Test Warehouse")
    with pytest.raises(Q.QuickSFError):
        Q.estimate("Test Garage", "")


def test_actual_costs_win_over_the_bid():
    jid = ph.add_job("TG-9", "Test garage 9", lines=[
        {"code": "03 31 13", "desc": "Test slab", "unit": "SF",
         "qty": Decimal(1000), "unit_cost": Decimal(50)}],
        type="Test Garage", bid_total=Decimal(50000))
    Q.set_job_sf(jid, 1000)
    ph.set_actuals(jid, [{"code": "03 31 13", "qty": 1000,
                          "cost": Decimal(70000)}])
    job = Q.history("Test Garage")[0]
    assert job["basis"] == "actual cost" and job["per_sf"] == Decimal(70)


def test_dialog(qapp_quick, qtbot):
    from app.estimate_ui import QuickSFDialog
    _history()
    d = blank_doc()
    dlg = QuickSFDialog(d)
    qtbot.addWidget(dlg)
    assert dlg.jobs.rowCount() == 3
    assert dlg.price_it("Test Warehouse", 1000) is None
    assert "No past jobs" in dlg.result.text()
    assert not dlg.add_button.isEnabled()
    assert dlg.add_to_estimate() == [] and EL.read(d) == []
    res = dlg.price_it("Test Garage", "1,000")
    assert res["median"] == Decimal("90000.00")
    assert "$90,000.00" in dlg.result.text()
    assert dlg.add_button.isEnabled()
    ids = dlg.add_to_estimate()
    assert len(ids) == 2 and len(EL.read(d)) == 2
    # a job's building SF typed in the past-jobs table is kept
    dlg2 = QuickSFDialog(None)
    qtbot.addWidget(dlg2)
    col = dlg2.JOB_COLS.index("Building SF")
    dlg2.jobs.item(0, col).setText("4000")
    jid = dlg2.jobs.item(0, col).data(0x0100)
    assert Q.job_sf(jid) == Decimal(4000)
    assert dlg2.price_it("Test Garage", 1000) is not None
    assert not dlg2.add_button.isEnabled()               # no document


@pytest.fixture
def qapp_quick():
    pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])
