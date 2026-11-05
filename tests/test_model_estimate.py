"""Model Estimate: a building priced from its type, SF and options, two
ways - from your own job history ($/SF by division with editable factors)
and from a Generate Set plan's quantities priced with the job's
assemblies / cost book - as allowance lines by division, exact to the
cent. Made-up history, assemblies and prices only."""
import os
from decimal import Decimal

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import (assemblies, dmoney, estimate_lines as EL,       # noqa: E402
                 model_estimate as M, pricehistory as ph, quick_sf as Q,
                 settings)
from estimate_helpers import blank_doc, make_book                # noqa: E402
from test_gui import win, qapp                                   # noqa: E402,F401

TYPE = "Restaurant (stand-alone)"


@pytest.fixture(autouse=True)
def _cfg(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", {"author": "Test Estimator"})
    monkeypatch.setattr(assemblies, "LIBRARY_PATH",
                        str(tmp_path / "assemblies.json"))
    os.makedirs(settings.DIR, exist_ok=True)


def _history(btype=TYPE, with_21=False):
    """3 past jobs at $80, $90 and $100 per SF; each 50% division 03,
    20% division 05, 30% division 09 (or 25% 09 + 5% 21)."""
    for n, (sf, cost) in enumerate([(2000, 160000), (1000, 90000),
                                    (1500, 150000)], 1):
        c = Decimal(cost)
        parts = [("03 31 13", "0.5"), ("05 12 00", "0.2")]
        parts += [("09 29 10", "0.25"), ("21 13 13", "0.05")] if with_21 \
            else [("09 29 10", "0.3")]
        jid = ph.add_job(f"TR-{n}", f"Test restaurant {n}", lines=[
            {"code": code, "desc": f"Test {code}", "unit": "LS",
             "qty": Decimal(1), "unit_cost": c * Decimal(share)}
            for code, share in parts], type=btype, bid_total=c)
        Q.set_job_sf(jid, sf)


def _inp(**kw):
    args = dict(btype=TYPE, sf=2000, stories=2, structure="steel",
                exterior={"brick": 50}, roof="low", site_sf="",
                sprinklered=False)
    args.update(kw)
    return M.inputs(**args)


def _no_library(monkeypatch):
    monkeypatch.setattr(assemblies, "library", lambda: {})


# ---- (a) job history ----------------------------------------------------

def test_history_by_division_with_factors():
    _history()
    res = M.price_history(_inp())
    assert res["count"] == 3 and res["per_sf"] == Decimal("90.00")
    assert res["base_total"] == Decimal("180000.00")
    got = {x["division"]: x["amount"] for x in res["lines"]}
    # story +3% on every division, steel +10% of 05, brick $3/SF x 50%
    assert got == {"03": Decimal("92700.00"), "04": Decimal("3000.00"),
                   "05": Decimal("40680.00"), "09": Decimal("55620.00")}
    assert res["total"] == Decimal("192000.00") == sum(got.values())
    labels = " | ".join(e["label"] for e in res["effects"])
    assert "Each story above the first" in labels
    assert "Structure: steel frame (10%)" in labels
    assert "Exterior: brick" in labels


def test_factors_are_yours_to_edit():
    _history()
    M.set_factor("structure_steel", "25")
    res = M.price_history(_inp())
    got = {x["division"]: x["amount"] for x in res["lines"]}
    assert got["05"] == Decimal("36000") + Decimal("1080") + Decimal("9000")
    M.set_factor("structure_steel", "")                  # back to default
    assert next(f for f in M.factors() if f["key"] == "structure_steel")[
        "value"] == Decimal("10")
    with pytest.raises(M.ModelError):
        M.set_factor("structure_steel", "lots")


def test_sprinklers_fill_a_missing_division_only():
    _history()
    res = M.price_history(_inp(stories=1, structure="wood", exterior={},
                                sprinklered=True))
    got = {x["division"]: x["amount"] for x in res["lines"]}
    assert got["21"] == Decimal("7000.00")               # $3.50 x 2,000 SF
    assert res["total"] == Decimal("187000.00")


def test_sprinklers_already_in_history_are_not_added_twice():
    _history(with_21=True)
    on = M.price_history(_inp(stories=1, structure="wood", exterior={},
                              sprinklered=True))
    assert {x["division"]: x["amount"] for x in on["lines"]}["21"] == \
        Decimal("9000.00")                               # 5% of 180,000
    assert any("not added again" in n for n in on["notes"])
    off = M.price_history(_inp(stories=1, structure="wood", exterior={},
                               sprinklered=False))
    assert "21" not in {x["division"] for x in off["lines"]}
    assert off["total"] == Decimal("171000.00")


def test_history_lines_into_the_estimate_exact():
    _history()
    res = M.price_history(_inp())
    lines = M.to_lines(res)
    assert [x["code"] for x in lines] == ["03 00 00", "04 00 00",
                                          "05 00 00", "09 00 00"]
    assert all(x["cost_type"] == "Allowance" for x in lines)
    assert "job history" in lines[0]["note"] and TYPE in lines[0]["note"]
    assert "2,000 SF" in lines[0]["note"] and "steel" in lines[0]["note"]
    d = blank_doc()
    EL.add(d, lines)
    assert EL.total(EL.priced(d)) == res["total"]


# ---- (b) plan quantities --------------------------------------------------

def _assemblies(doc):
    assemblies.set_job_assembly(doc, {
        "name": "Test slab on grade", "measure": "area", "trade": "Test",
        "parts": [{"name": "Test concrete", "unit": "sf", "qty": "Area",
                   "cost": 5.0, "labor": 0.05}]})
    assemblies.set_job_assembly(doc, {
        "name": "Test gypsum board", "measure": "area", "trade": "Test",
        "parts": [{"name": "Test board", "unit": "sf", "qty": "Area",
                   "cost": 0.5, "labor": 0.01}]})


RATE = {"Test slab on grade": (Decimal("5"), Decimal("2.75")),
        "Test gypsum board": (Decimal("0.5"), Decimal("0.55"))}


def test_quantities_priced_with_the_jobs_assemblies(monkeypatch):
    _no_library(monkeypatch)
    d = blank_doc()
    _assemblies(d)
    inp = _inp(stories=1, structure="wood", exterior={})
    res = M.price_quantities(inp, d)
    assert not res["error"]
    priced = [r for r in res["rows"] if r.get("ext") is not None]
    assert {r["by"] for r in priced} == {"assembly Test slab on grade",
                                         "assembly Test gypsum board"}
    for r in priced:
        mat, lab = RATE[r["by"][9:]]
        assert r["ext"]["mat"] == dmoney.cents(r["qty"] * mat)
        assert r["ext"]["lab"] == dmoney.cents(r["qty"] * lab)
    # the slab's concrete CY is the same work: not priced again
    cy = next(r for r in res["rows"] if r["item"].startswith("Slab concr"))
    assert cy.get("ext") is None and "covered" in cy["status"]
    by = {x["division"]: x["amount"] for x in res["lines"]}
    assert set(by) == {"03", "09"}
    assert res["total"] == sum(r["total"] for r in priced) == \
        sum(by.values())
    # what had no price is listed with why
    why = {r["item"]: r["problem"] for r in res["unpriced"]}
    assert any(k.startswith("Floor finish") for k in why)
    assert all(why.values())
    lines = M.to_lines(res)
    assert "quantities" in lines[0]["note"]
    EL.add(d, lines)
    assert EL.total(EL.priced(d)) == res["total"]
    p = EL.priced(d)[0]
    assert p["ext"]["mat"] and p["ext"]["lab"]           # split kept


def test_quantities_priced_from_the_jobs_cost_book(monkeypatch):
    _no_library(monkeypatch)
    d = blank_doc()
    assemblies.set_costbook(d, make_book())
    res = M.price_quantities(_inp(stories=1, exterior={}), d)
    slab = next(r for r in res["rows"] if r["item"].startswith("Slab on"))
    assert slab["by"] == "Test Book 03 31 13.35"
    assert slab["total"] == dmoney.cents(slab["qty"] * Decimal("2.10"))
    assert res["lines"][0]["division"] == "03"


def test_more_stories_than_the_plan_draws_count_the_floors(monkeypatch):
    _no_library(monkeypatch)
    d = blank_doc()
    _assemblies(d)
    one = M.price_quantities(_inp(stories=1, sf=6000, exterior={}), d)
    two = M.price_quantities(_inp(stories=2, sf=6000, exterior={}), d)
    assert any("counted 2 times" in n for n in two["notes"])
    gyp = next(r for r in two["rows"] if r["item"].startswith("Gypsum"))
    assert "x 2 floors" in gyp["how"]
    assert any(r["item"].startswith("Upper floors") for r in two["rows"])
    assert one["total"] != two["total"]


def test_options_change_the_quantities():
    inp = _inp(stories=1, structure="pemb", roof="pitched",
               exterior={"brick": 25, "storefront": 10}, site_sf=40000,
               sprinklered=True)
    plan, floors, _n = M.make_plan(inp)
    rows = M.quantities(plan, inp, floors)
    items = [r["item"] for r in rows]
    assert "Roof, pitched" in items and \
        "Pre-engineered metal building system" in items
    assert "Fire sprinklers, wet system" in items
    assert "Site grading (site less building)" in items
    brick = next(r for r in rows if r["item"].startswith("Exterior brick"))
    net = next(r for r in rows if "metal building wall" in r["item"])
    assert brick["qty"] == (net["qty"] / 4).quantize(Decimal(1))
    assert brick["division"] == "04"


def test_nothing_to_price_with_says_what_is_missing(monkeypatch):
    _no_library(monkeypatch)
    d = blank_doc()
    res = M.run(_inp(stories=1), d)
    assert res["history"] is None
    assert res["quantities"]["lines"] == []
    assert "No assemblies and no cost book" in res["quantities"]["error"]
    assert "Nothing to price" in res["missing"] and \
        "Nothing was added" in res["missing"]
    assert M.to_lines(res["history"]) == [] and \
        M.to_lines(res["quantities"]) == []
    assert EL.read(d) == []


def test_a_type_generate_set_does_not_know():
    res = M.price_quantities(M.inputs("Test Car Wash", 3000))
    assert "not a Generate Set building type" in res["error"]
    # 2 floors of 1,000 SF: under what Generate Set plans a restaurant
    res = M.price_quantities(_inp(stories=2, sf=2000))
    assert "per floor" in res["error"] and res["lines"] == []


def test_inputs_are_checked():
    with pytest.raises(M.ModelError):
        M.inputs(TYPE, "")
    with pytest.raises(M.ModelError):
        M.inputs(TYPE, 2000, exterior={"brick": 70, "eifs": 40})
    with pytest.raises(M.ModelError):
        M.inputs(TYPE, 2000, structure="straw")
    inp = M.inputs("restaurant", "4500")
    assert inp["key"] == "restaurant" and inp["type"] == TYPE
    assert inp["structure"] == "wood" and inp["roof"] == "low"


# ---- the dialog -----------------------------------------------------------

@pytest.fixture
def qapp_model():
    pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_dialog_side_by_side_and_adds_lines(qapp_model, qtbot, monkeypatch):
    from app.estimate_ui import ModelEstimateDialog
    _no_library(monkeypatch)
    _history()
    d = blank_doc()
    _assemblies(d)
    dlg = ModelEstimateDialog(d)
    qtbot.addWidget(dlg)
    res = dlg.price_it(TYPE, "4,000", stories=1, structure="steel",
                       roof="low", exterior={"brick": 50},
                       sprinklered=False)
    # 4,000 SF x $90 = 360,000; steel +10% of 72,000; brick $3 x 2,000 SF
    assert res["history"]["total"] == Decimal("373200.00")
    assert dlg.hist_table.rowCount() == 4
    assert dlg.qdiv_table.rowCount() == len(res["quantities"]["lines"]) > 0
    assert dlg.qty_table.rowCount() == len(res["quantities"]["rows"])
    assert "NO PRICE" in " ".join(dlg.qty_table.item(r, 4).text() for r in
                                  range(dlg.qty_table.rowCount()))
    assert "$373,200.00" in dlg.hist_text.text()
    assert "difference" in dlg.result.text()
    assert dlg.add_hist.isEnabled() and dlg.add_qty.isEnabled()
    # a factor edited in the table re-prices
    assert dlg.set_factor("structure_steel", "25")
    assert dlg.res["history"]["total"] == Decimal("384000.00")
    qty_total = dlg.res["quantities"]["total"]
    ids = dlg.add_history()
    assert len(ids) == 4
    assert EL.total(EL.priced(d)) == Decimal("384000.00")
    # the quantities' lines, from a fresh dialog
    dlg2 = ModelEstimateDialog(d)
    qtbot.addWidget(dlg2)
    dlg2.price_it(TYPE, "4000", stories=1, structure="steel", roof="low",
                  exterior={"brick": 50})
    assert dlg2.add_quantities()
    assert EL.total(EL.priced(d)) == Decimal("384000.00") + qty_total


def test_dialog_without_a_document_or_anything_to_price(qapp_model, qtbot,
                                                         monkeypatch):
    from app.estimate_ui import ModelEstimateDialog
    _no_library(monkeypatch)
    dlg = ModelEstimateDialog(None)
    qtbot.addWidget(dlg)
    res = dlg.price_it(TYPE, 2000)
    assert res["missing"] and "Nothing was added" in dlg.result.text()
    assert not dlg.add_hist.isEnabled() and not dlg.add_qty.isEnabled()
    assert dlg.add_history() == [] and dlg.add_quantities() == []
    assert dlg.price_it(TYPE, "") is None
    assert "square feet" in dlg.result.text()


def test_quick_sf_dialog_opens_model_estimate(qapp_model, qtbot):
    from app.estimate_ui import QuickSFDialog
    d = blank_doc()
    q = QuickSFDialog(d)
    qtbot.addWidget(q)
    q.btype.setCurrentText(TYPE)
    q.sf.setText("4500")
    m = q.open_model(show=False)
    qtbot.addWidget(m)
    assert m.btype.currentText() == TYPE and m.sf.text() == "4500"


def test_estimate_menu_and_panel_open_it(win):
    from app.estimate_ui import LayoutsDialog, ModelEstimateDialog
    dlg = win.model_estimate(show=False)
    assert isinstance(dlg, ModelEstimateDialog) and dlg.doc is win._view.doc
    dlg.close()
    lay = win.estimate.estimate_layouts(show=False)
    assert isinstance(lay, LayoutsDialog)
    lay.close()
