"""Service tech hours -> Back Office time cards (Nov 5): one card per
logged entry, the service job, interface v1 shape, the week's window
sends through backoffice_hook without starting anything in the test."""
import json

import pytest

from app.service import timecards, workorder
from r111_support import isolate, qapp  # noqa: F401


@pytest.fixture(autouse=True)
def svc_home(tmp_path, monkeypatch):
    return isolate(tmp_path, monkeypatch)


def _orders():
    st = workorder.blank()
    workorder.set_rates(st, "100", "40")
    w = workorder.add(st, customer="Test Smith", site="1 Test Lane",
                      complaint="No cooling")
    workorder.add_time(st, w, "A Tester", "2", when="2026-11-02")
    workorder.add_time(st, w, "B Tester", "1.25", when="2026-11-03")
    workorder.add_time(st, w, "A Tester", "3", when="2026-11-10")  # next wk
    return st


def test_cards_one_per_entry_in_the_week():
    from app import settings
    settings.set("service_labor_code", "SV-100")
    cards = timecards.cards(_orders(), "2026-11-02", "2026-11-08")
    assert [(c["date"], c["foreman"], c["crew"][0]["hours"]) for c in cards] \
        == [("2026-11-02", "A Tester", "2.00"), ("2026-11-03", "B Tester",
                                                 "1.25")]
    assert all(c["id"].startswith("svc:") for c in cards)
    assert cards[0]["production"][0]["cost_code"] == "SV-100"
    snap = timecards.snapshot(_orders(), "2026-11-02", "2026-11-08")
    assert snap["interface_version"] == 1
    assert snap["project"]["number"] == "SERVICE"
    json.dumps(snap)                                  # all plain JSON
    assert timecards.summary(snap)["hours"] == {"A Tester": "2.00",
                                                "B Tester": "1.25"}


def test_dispatch_sends_the_week(qapp):
    from PySide6.QtCore import QDate
    from app.service import dispatch_ui
    workorder.save(_orders())
    w = dispatch_ui.DispatchWindow()
    w.day.setDate(QDate(2026, 11, 4))
    assert w.week() == ("2026-11-02", "2026-11-08")
    sent = []
    snap = w.hours_clicked(ask=lambda t: True, start=sent.append)
    assert sent and sent[0] is snap and len(snap["timecards"]) == 2
    w.day.setDate(QDate(2026, 12, 1))
    assert w.hours_clicked(ask=lambda t: True, start=sent.append) is None
    w.close()
