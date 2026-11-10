"""Where service invoices and hours go (QuantiSheet 1.2 phase 2, Nov 5):
Back Office by default, Sage or hh2 as a setting - each with the same
holds, sent once, and a way back out. Made-up data only."""
import csv
import os

import pytest

from app import settings
from app.service import invoice_route as IR, timecards, workorder
from r111_support import isolate, qapp  # noqa: F401


@pytest.fixture(autouse=True)
def svc_home(tmp_path, monkeypatch):
    return isolate(tmp_path, monkeypatch)


def _store(n=2):
    st = workorder.blank()
    workorder.set_rates(st, "100", "40")
    for k in range(n):
        w = workorder.add(st, customer=f"Test Customer {k}",
                          site=f"{k} Test Lane", complaint="No heat")
        workorder.add_time(st, w, "A Tester", "2", when="2026-11-02")
        workorder.add_part(st, w, "Test igniter", "1", cost="20",
                           price="45.50")
        workorder.close_and_invoice(st, w, notes="Replaced the igniter.",
                                    write_pdf=False, when="2026-11-02")
    return st


def test_route_setting_defaults_to_back_office():
    assert IR.route() == "backoffice"
    IR.set_route("hh2")
    assert IR.route() == "hh2"
    with pytest.raises(IR.RouteError):
        IR.set_route("quickbooks")
    settings.set("service_invoice_route", "nonsense")
    assert IR.route() == "backoffice"


def test_back_office_once_with_holds_and_reversal():
    st = _store(3)
    st["invoices"][2]["total"] = "1.00"            # doesn't add up
    got = []
    out = IR.send_backoffice(st, start=got.append)
    assert out["sent"] == ["INV-0001", "INV-0002"]
    assert out["held"][0][0] == "INV-0003" and "lines add to" in \
        out["held"][0][1]
    snap = got[0]
    assert snap["interface_version"] == 1
    assert snap["project"]["number"] == "SERVICE" and snap["timecards"] == []
    item = snap["service_invoices"][0]
    assert item["number"] == "INV-0001" and item["total"] == "245.50"
    assert sum(float(ln["amount"]) for ln in item["lines"]) == 245.50
    assert st["invoices"][0]["bo_sent"]
    with pytest.raises(IR.RouteError):              # nothing new
        IR.send_backoffice(st, start=got.append)
    with pytest.raises(IR.RouteError):
        IR.send_backoffice(st, invoices=st["invoices"][:1],
                           start=got.append)
    with pytest.raises(IR.RouteError):
        IR.reverse_backoffice(st, st["invoices"][0]["id"], "  ",
                              start=got.append)
    rev = IR.reverse_backoffice(st, st["invoices"][0]["id"],
                                "wrong customer", start=got.append)
    assert rev["service_invoices"] == [
        {"id": st["invoices"][0]["id"], "number": "INV-0001",
         "date": rev["service_invoices"][0]["date"], "reverse": True,
         "reason": "wrong customer"}]
    with pytest.raises(IR.RouteError):
        IR.reverse_backoffice(st, st["invoices"][0]["id"], "again",
                              start=got.append)
    with pytest.raises(IR.RouteError):              # never sent
        IR.reverse_backoffice(st, st["invoices"][2]["id"], "x",
                              start=got.append)


def test_hh2_folder_pdfs_manifest_and_reverse(tmp_path):
    st = _store(2)
    folder = str(tmp_path / "hh2")
    out = IR.export_hh2(st, folder)
    names = sorted(os.listdir(folder))
    assert "INV-0001.pdf" in names and "INV-0002.pdf" in names
    rows = list(csv.reader(open(out["manifest"], encoding="utf-8-sig")))
    assert rows[0] == IR.HH2_COLUMNS
    amt = rows[0].index("Amount")
    assert rows[1][0] == "INV-0001" and rows[1][amt] == "245.50"
    back = list(csv.reader(open(out["reverse"], encoding="utf-8-sig")))
    assert back[1][amt] == "-245.50"
    assert all(i["hh2_sent"] for i in st["invoices"])
    with pytest.raises(IR.RouteError):
        IR.export_hh2(st, folder)
    settings.set("service_hh2_invoice_columns", ["Invoice", "Amount",
                                                 "Bogus"])
    again = IR.export_hh2(st, str(tmp_path / "h2"), again=True)
    assert list(csv.reader(open(again["manifest"], encoding="utf-8-sig")))[0] \
        == ["Invoice", "Amount"]


def test_hh2_time_csv_each_entry_once(tmp_path):
    st = _store(2)
    p = str(tmp_path / "t.csv")
    out = timecards.hh2_csv(st, p, "2026-11-02", "2026-11-08")
    assert out["entries"] == 2
    rows = list(csv.reader(open(p, encoding="utf-8-sig")))
    assert rows[0] == timecards.HH2_TIME_COLUMNS
    assert rows[1][0] == "A Tester" and rows[1][4] == "2.00"
    back = list(csv.reader(open(out["reverse"], encoding="utf-8-sig")))
    assert back[1][4] == "-2.00"
    with pytest.raises(ValueError):
        timecards.hh2_csv(st, p, "2026-11-02", "2026-11-08")
    assert timecards.hh2_csv(st, p, "2026-11-02", "2026-11-08",
                             again=True)["entries"] == 2


def test_windows_send_and_reverse(qapp, tmp_path):
    from app.service import dispatch_ui, workorder_ui
    st = _store(1)
    workorder.save(st)
    w = workorder_ui.WorkOrderWindow()
    assert w.route.currentData() == "backoffice"
    got = []
    out = w.send_clicked(ask=lambda t: True, start=got.append)
    assert out["sent"] == ["INV-0001"] and "Bring In" in w.msg.text()
    assert w.send_clicked(ask=lambda t: True, start=got.append) is None
    assert "Nothing new" in w.msg.text()
    w.table.selectRow(0)
    snap = w.reverse_clicked(why="duplicate", start=got.append)
    assert snap["service_invoices"][0]["reverse"]
    w.route.setCurrentIndex(w.route.findData("hh2"))
    assert IR.route() == "hh2"
    out = w.send_clicked(ask=lambda t: True, target=str(tmp_path / "f"))
    assert out["sent"] == ["INV-0001"]
    w.close()
    settings.set("service_time_route", "hh2")
    from PySide6.QtCore import QDate
    d = dispatch_ui.DispatchWindow()
    d.day.setDate(QDate(2026, 11, 4))
    res = d.hours_clicked(path=str(tmp_path / "h.csv"))
    assert res["entries"] == 1 and "no published time import" in \
        d.msg.text()
    assert d.hours_clicked(path=str(tmp_path / "h.csv")) is None
    d.close()
