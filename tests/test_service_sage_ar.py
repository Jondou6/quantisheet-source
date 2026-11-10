"""Service invoices to Sage AR (Nov 5): a preview, one send per invoice,
held invoices that don't add up, a reverse file, no formulas. Made-up
customers only."""
import csv
import os

import pytest

from app.service import sage_ar, workorder
from r111_support import isolate, qapp  # noqa: F401


@pytest.fixture(autouse=True)
def svc_home(tmp_path, monkeypatch):
    return isolate(tmp_path, monkeypatch)


def _store():
    store = workorder.blank()
    workorder.set_rates(store, "100", "40")
    for cust, hrs in (("Test Smith", "2"), ("=HYPERLINK(1)", "1.5")):
        wid = workorder.add(store, customer=cust, site="1 Test Lane",
                            complaint="No cooling")
        workorder.add_time(store, wid, "A Tester", hrs)
        workorder.add_part(store, wid, "Test capacitor", "1", cost="10",
                           price="25")
        workorder.close_and_invoice(store, wid, notes="Replaced the test "
                                    "capacitor.", write_pdf=False,
                                    when="2026-11-02")
    return store


def _read(p):
    return list(csv.reader(open(p, encoding="utf-8-sig")))


def test_export_once_with_reverse_file(tmp_path):
    store = _store()
    rws, held = sage_ar.rows(store)
    pv = sage_ar.preview(rws, held)
    assert (pv["invoices"], pv["lines"], held) == (2, 4, [])
    assert pv["total"] == "400.00"            # 3.5 h at 100 + 2 x 25
    out = sage_ar.export(store, str(tmp_path / "s.csv"))
    rows = _read(out["file"])
    assert rows[0] == sage_ar.DEFAULT_COLUMNS
    assert {r[1] for r in rows[1:]} == {"INV-0001", "INV-0002"}
    assert all(not r[0].startswith("=") for r in rows[1:])   # no formulas
    assert rows[1][3] == "2026-12-02"                       # net 30
    rev = _read(out["reverse"])
    amt = rows[0].index("Amount")
    assert sum(float(r[amt]) for r in rows[1:]) == \
        -sum(float(r[amt]) for r in rev[1:]) == 400.0
    assert all(i.get("sage_sent") for i in store["invoices"])
    with pytest.raises(sage_ar.SageARError, match="Nothing to send"):
        sage_ar.export(store, str(tmp_path / "t.csv"))
    with pytest.raises(sage_ar.SageARError, match="Already sent"):
        sage_ar.export(store, str(tmp_path / "t.csv"),
                       invoices=store["invoices"])
    again = sage_ar.export(store, str(tmp_path / "u.csv"),
                           invoices=store["invoices"], again=True)
    assert again["preview"]["invoices"] == 2


def test_an_invoice_that_does_not_add_up_is_held(tmp_path):
    store = _store()
    store["invoices"][0]["total"] = "999.00"
    rws, held = sage_ar.rows(store)
    assert held and held[0][0] == "INV-0001" and "add to" in held[0][1]
    out = sage_ar.export(store, str(tmp_path / "s.csv"))
    assert {r[1] for r in _read(out["file"])[1:]} == {"INV-0002"}
    assert not store["invoices"][0].get("sage_sent")


def test_column_layout_is_a_setting(tmp_path):
    from app import settings
    settings.set("service_sage_ar_columns", ["Invoice", "Amount", "Bogus"])
    store = _store()
    out = sage_ar.export(store, str(tmp_path / "s.csv"))
    assert _read(out["file"])[0] == ["Invoice", "Amount"]


def test_window_button(qapp, tmp_path):
    from app.service import workorder_ui
    store = _store()
    workorder.save(store)
    w = workorder_ui.WorkOrderWindow()
    out = w.sage_clicked(path=str(tmp_path / "w.csv"), ask=lambda t: True)
    assert out and os.path.isfile(out["file"])
    assert all(i.get("sage_sent") for i in workorder.load()["invoices"])
    assert w.sage_clicked(path=str(tmp_path / "x.csv"),
                          ask=lambda t: True) is None      # nothing new
    w.close()
