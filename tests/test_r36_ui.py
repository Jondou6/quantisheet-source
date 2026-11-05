"""r36: Takeoff > Estimating Tools menu and its window - every page opens
with no drawing open and with one, and the pages do their job through
the same engine functions the other r36 tests cover. Made-up data only."""
import os
from decimal import Decimal

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QDialog, QMenu                     # noqa: E402

from app import assemblies, estimate_lines as EL                  # noqa: E402
from app.estimating import quotes, service, ui                    # noqa: E402
from estimate_helpers import area                                  # noqa: E402
from test_gui import ANSWERS, win, qapp                            # noqa: E402,F401


@pytest.fixture(autouse=True)
def _iso(tmp_path, monkeypatch):
    monkeypatch.setattr(assemblies, "LIBRARY_PATH",
                        str(tmp_path / "assemblies.json"))
    monkeypatch.setattr(QDialog, "exec", lambda self, *a: 0)


def _menu(win):
    for a in win.menuBar().actions():
        m = a.menu()
        if m is None:
            continue
        for b in m.actions():
            if b.menu() is not None and b.text() == ui.MENU_TITLE:
                return b.menu()
    return None


def test_menu_has_every_tool_and_each_opens(win, qapp):
    m = _menu(win)
    assert isinstance(m, QMenu)
    labels = [a.text() for a in m.actions() if a.text()]
    assert labels == [label for _k, label in ui.PAGES]
    for a in m.actions():
        a.trigger()
        qapp.processEvents()
    assert ui.LAST is not None
    assert ui.LAST.stack.count() == len(ui.PAGES)    # v2 step 4: drop-down, no tabs


def test_every_page_with_no_drawing_open(qapp, tmp_path, monkeypatch):
    from app import settings
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "_cache", None)
    dlg = ui.EstimatingTools(None, doc=None)
    for i in range(dlg.stack.count()):              # v2 step 4: drop-down
        dlg.picker.setCurrentIndex(i)
        dlg.stack.widget(i).refresh()
        qapp.processEvents()
    dlg.close()


def test_pages_work_on_an_open_drawing(win, qapp, tmp_path):
    d = win._view.doc
    area(d, "Test floor", 10, 10)
    ids = EL.add(d, [EL.new_line("Test base work", 1, "ls", sub=1000),
                     EL.new_line("Test good finish", 100, "sf", mat=2),
                     EL.new_line("Test zero", 0, "ea", mat=5)])
    dlg = ui.open_tools(win, "check")
    chk = dlg.page("check")
    chk.run()
    assert chk.table.rowCount() >= 2               # zero qty + unpriced
    q = dlg.page("quote")
    q.refresh()
    q.set_where(ids[1], "Good")
    q.pct.setValue(25)
    q.save_spec()
    assert quotes.read(d)["assign"][ids[1]] == "Good"
    assert "Good" in q.totals.text()
    ANSWERS["save"] = str(tmp_path / "quote.pdf")
    q.save_pdf()
    assert os.path.isfile(tmp_path / "quote.pdf")
    mat = dlg.page("materials")
    mat.refresh()
    assert mat.table.rowCount() == 1       # the one line with material $
    act = dlg.page("actuals")
    act.refresh()
    act.set_actual(ids[0], cost="1100")
    assert act.table.rowCount() == 3
    from app.estimating import actuals
    assert actuals.read(d)[ids[0]]["cost"] == "1100.00"
    pl = dlg.page("planning")
    pl.design.setText("Q=2")
    pl.add_row(["Test unit", "1", "Q", "1000", "1", "0", "", "", "0", "1",
                "0"])
    pl.calculate()
    assert "2,000.00" in pl.result.text()
    sv = dlg.page("service")
    sv.path = str(tmp_path / "svc.json")
    s = service.blank()
    p = service.add_property(s, "Test house")
    service.add_service(s, p, "Test filter", 1, "months", "2026-01-01")
    service.save(s, sv.path)
    sv.reload()
    assert sv.due.rowCount() == 1
    tpl = dlg.page("templates")
    tpl.refresh()
    dlg.close()


def test_bidday_supplier_and_crew_pages(win, qapp, tmp_path):
    from app import heavy
    d = win._view.doc
    bids = tmp_path / "bids.csv"
    bids.write_text("Item,Description,Unit,Qty,My plug,Test A,Test B\n"
                    "1,Test strip,SY,10,,100,90\n"
                    "2,Test haul,CY,5,500,400,excl\n", encoding="utf-8")
    ANSWERS["open"] = str(bids)
    ANSWERS["text"] = "Test earthwork"
    dlg = ui.open_tools(win, "bidday")
    bd = dlg.page("bidday")
    bd.import_csv()
    assert bd.package.currentText() == "Test earthwork"
    assert "lowest complete: Test A" in bd.msg.text()
    lst = tmp_path / "dealer.csv"
    lst.write_text("SKU,Description,Unit,Price\nX1,Test stud,EA,3.10\n",
                   encoding="utf-8")
    sp = dlg.page("supplier")
    sp.load(str(lst))
    sp.supplier.setText("Test Yard")
    ANSWERS["save"] = str(tmp_path / "yard.json")
    sp.save()
    assert os.path.isfile(tmp_path / "yard.json")
    job = heavy.blank()
    job["pay_items"] = [{"no": "1", "desc": "Test item", "unit": "LF",
                         "owner_qty": "10", "weight": "1"}]
    heavy.add_activity(job, "Test act", qty=10, unit="LF", sub=100,
                       pay_item="1")
    heavy.write(d, job)
    cr = dlg.page("crew")
    cr.refresh()
    assert cr.table.rowCount() == 2                 # pay item + unassigned
    dlg.close()
