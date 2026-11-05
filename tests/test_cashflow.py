"""Cash flow from a cost-loaded schedule."""
import datetime as dt
import os

import fitz

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import settings                                     # noqa: E402
from app.pm import cashflow                                  # noqa: E402
from app.pm.store import ProjectStore                        # noqa: E402
from test_pm import qapp_pm                                  # noqa: E402,F401


def _store(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", {"author": "Pat Morgan"})
    s = ProjectStore(str(tmp_path / "job"))
    s.save_record("budget", {"cost_code": "03 30 00",
                             "description": "Concrete", "original": 40000})
    s.save_record("budget", {"cost_code": "09 21 16",
                             "description": "Drywall", "original": 20000})
    s.save_record("budget", {"cost_code": "01 50 00",
                             "description": "Temp facilities",
                             "original": 6000})
    s.save_record("activity", {"name": "Concrete", "duration": 20,
                               "start": "2026-09-01",
                               "cost_code": "03 30 00"})
    s.save_record("activity", {"name": "Drywall", "duration": 20,
                               "preds": [{"id": "A0001"}],
                               "cost_code": "09 21 16"})
    s.save_record("cost", {"date": "2026-09-15", "vendor": "Sam Sub",
                           "cost_code": "03 30 00", "amount": 15000,
                           "status": "Paid", "paid": "2026-10-05"})
    return s


def test_cost_curve(tmp_path, monkeypatch):
    s = _store(tmp_path, monkeypatch)
    today = dt.date(2026, 10, 1)
    data = cashflow.months(s, today)
    rows = {r["month"]: r for r in data["rows"]}
    assert set(rows) >= {"2026-09", "2026-10"}
    # everything in the budget is planned somewhere
    assert abs(data["rows"][-1]["cum_planned"] - 66000) < 1
    # concrete runs Sep 1 - 28 (20 workdays): its $40k is all September
    # plus the September share of the temp facilities
    assert rows["2026-09"]["planned"] > 40000
    assert rows["2026-09"]["actual"] == 15000
    assert rows["2026-10"]["paid"] == 15000
    assert rows["2026-10"]["net_cash"] == -15000
    # forecast to date ends at the forecast at completion
    assert abs(data["rows"][-1]["cum_forecast"] - 66000) < 1
    p = cashflow.pdf(s, str(tmp_path / "cf.pdf"), today)
    assert "Cash Flow" in fitz.open(p)[0].get_text()
    assert os.path.getsize(cashflow.xlsx(s, str(tmp_path / "cf.xlsx"),
                                         today)) > 0


def test_cash_flow_page(qapp_pm, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication
    from app.pm import center
    s = _store(tmp_path, monkeypatch)
    w = center.ProjectCenter(s)
    w.show()
    page = w.show_tool("cashflow")
    QApplication.processEvents()
    assert page.table.rowCount() >= 2
    page.curve.repaint()
    assert page._pdf(str(tmp_path / "x.pdf"))
    assert page._xlsx(str(tmp_path / "x.xlsx"))
    w.close()
