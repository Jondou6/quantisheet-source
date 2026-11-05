"""Your own Location Factors table (brief item 4): search by state, city,
abbreviation or ZIP, the location adjustment as its own lines, edits in
the price history, and only QuantiSheet's own starter regions shipped.
Made-up region 'Testville' and ZIPs 99901-99905 only."""
import os
from decimal import Decimal

import fitz
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import (costbook, jobinfo, locfactors, pricedb,  # noqa: E402
                 settings)

TESTVILLE = {"region": "Testville", "state": "PA", "cities": "Testville",
             "zips": "99901-99905", "materials": 1.10, "labor": 1.20,
             "equipment": 1.00, "source": "made-up test factors"}


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", None)
    monkeypatch.setattr(pricedb, "user", lambda: "Pat Example")
    pricedb.state.update(offline="", copied=0.0)
    pricedb._BOOK_CACHE.clear()


def _add_testville():
    assert locfactors.save([dict(TESTVILLE)], note="test") >= 1


def _names(rows):
    return [r["region"] for r in rows]


def test_search_by_zip_name_and_state():
    _add_testville()
    assert _names(locfactors.search("99903"))[0] == "Testville"
    assert costbook.find_region("99903")["region"] == "Testville"
    assert _names(locfactors.search("testv")) == ["Testville"]
    pa = _names(costbook.search_regions("PA"))
    assert "Pennsylvania" in pa and "Testville" in pa
    assert "Pennsylvania" in _names(locfactors.search("pennsylvania"))
    assert locfactors.search("00000") == []
    assert costbook.find_region("00000") is None
    assert locfactors.no_match_message("00000") == \
        "No region for 00000 - pick one or add it"
    # a ZIP prefix row matches the ZIPs under it; an exact ZIP beats it
    locfactors.save([{"region": "Test County", "state": "PA",
                      "zips": "999", "materials": 1.05, "labor": 1.0,
                      "equipment": 1.0}])
    assert _names(locfactors.search("99903"))[:2] == ["Testville",
                                                      "Test County"]
    assert _names(locfactors.search("99950")) == ["Test County"]


def test_location_adjustment_is_three_lines_in_exact_money():
    _add_testville()
    adj = costbook.location_adjustment(6000, 3000, 1000, "Testville")
    assert adj["found"] and adj["region"] == "Testville"
    assert adj["materials"] == Decimal("600.00")
    assert adj["labor"] == Decimal("600.00")
    assert adj["equipment"] == Decimal("0.00")
    assert adj["total"] == Decimal("1200.00")
    assert adj["percent"] == Decimal("12.0")
    assert adj["percent_text"] == "+12.0%"
    assert adj["grand_total"] == Decimal("11200.00")
    assert adj["base"]["total"] == Decimal("10000.00")
    assert adj["lines"] == [
        ("Base estimate", Decimal("10000.00")),
        ("Location adjustment (+12.0%)", Decimal("1200.00")),
        ("Grand total", Decimal("11200.00"))]
    # by ZIP too, and an unknown region adjusts nothing
    assert costbook.location_adjustment(6000, 3000, 1000, "99903")[
        "total"] == Decimal("1200.00")
    none = costbook.location_adjustment(6000, 3000, 1000, "Nowhere Test")
    assert not none["found"] and none["total"] == Decimal("0.00")
    assert none["grand_total"] == Decimal("10000.00")


def test_factor_edits_are_logged_in_price_history():
    _add_testville()
    row = dict(TESTVILLE, labor=1.25)
    assert locfactors.save([row], note="our own jobs") == 1
    h = [x for x in pricedb.history(pricedb.LOCATION_BOOK)
         if x["code"] == "Testville" and x["field"] == "labor factor"]
    assert h and h[0]["old"] == "1.2" and h[0]["new"] == "1.25"
    assert h[0]["by"] == "Pat Example" and h[0]["at"]
    assert h[0]["note"] == "our own jobs"
    # editing a starter row logs the starter value as "old"
    pa = next(r for r in locfactors.rows() if r["region"] == "Pennsylvania")
    locfactors.save([dict(pa, materials=1.0)])
    h = [x for x in locfactors.history() if x["code"] == "Pennsylvania"]
    assert h[0]["field"] == "materials factor"
    assert float(h[0]["old"]) == pytest.approx(pa["materials"])
    assert h[0]["new"] == "1"
    # removing a row is logged and hides it
    assert locfactors.remove("Testville") == 1
    assert "Testville" not in _names(locfactors.rows())
    assert locfactors.history()[0]["field"] == "removed"


def test_fresh_install_ships_only_our_own_regions():
    costbook.install_shipped()
    names = costbook.list_books()
    assert names
    allowed = set(costbook.STATES.values()) | {"national"}
    for n in names:
        b = costbook.find(n)
        assert set(b.region_names()) <= allowed
        assert not b.local_only
        for it in b.items.values():
            assert not it.get("license") and not it.get("edition")
            assert not it.get("imported")
    rows = locfactors.rows()
    assert {r["origin"] for r in rows} == {"starter"}
    assert all(r["source"].startswith("QuantiSheet") for r in rows)
    assert set(_names(rows)) <= allowed
    assert not any(r.get("zips") or r.get("cities") for r in rows)


def test_book_regions_resolve_from_a_zip():
    _add_testville()
    b = costbook.Book({"name": "Test", "index": {"national": 1.0,
                                                 "Pennsylvania": 0.99}})
    assert b.resolve_region("99903") == "Pennsylvania"    # Testville, PA
    assert b.resolve_region("00000") is None


@pytest.fixture
def doc():
    d = fitz.open()
    d.new_page()
    return d


def test_job_region_from_zip_and_no_match_keeps_it(qtbot, doc):
    from app.location_ui import LocationFactorsDialog
    _add_testville()
    jobinfo.write(doc, job_zip="99903")
    assert costbook.job_region(doc) == "Testville"
    jobinfo.write(doc, location_region="Testville", job_zip="")
    dlg = LocationFactorsDialog(None, doc, search="00000")
    qtbot.addWidget(dlg)
    assert dlg.factors.message.text() == \
        "No region for 00000 - pick one or add it"
    assert dlg.factors.table.rowCount() == 0
    assert dlg.use_for_job() is None
    assert costbook.job_region(doc) == "Testville"     # stays
    dlg.factors.search.setText("testv")
    assert dlg.factors.table.rowCount() == 1
    assert dlg.use_for_job() == "Testville"


def test_table_window_add_edit_search_and_history(qtbot):
    from app.location_ui import KEYS, LocationFactorsDialog
    dlg = LocationFactorsDialog(None)
    qtbot.addWidget(dlg)
    w = dlg.factors
    w.add_region(**TESTVILLE)
    w.note.setText("test quote")
    assert w.save() >= 1
    w.search.setText("99903")
    assert w.table.rowCount() == 1
    assert w.table.item(0, 0).text() == "Testville"
    # edit the labor factor in the table, then save
    w.table.item(0, KEYS.index("labor")).setText("1.30")
    assert w.dirty()
    assert w.save() == 1
    assert next(r for r in locfactors.rows()
                if r["region"] == "Testville")["labor"] == pytest.approx(1.3)
    w.search.setText("PA")
    shown = [w.table.item(r, 0).text() for r in range(w.table.rowCount())]
    assert "Pennsylvania" in shown and "Testville" in shown
    rows = dlg.fill_history()
    assert any(h["field"] == "labor factor" and h["new"] == "1.3" and
               h["by"] == "Pat Example" for h in rows)
    assert dlg.hist.rowCount() == len(rows)


def test_edit_prices_has_the_location_factors_tab(qtbot):
    from app.pricedb_ui import PriceEditor
    b = costbook.Book({"name": "Test Loc Book"})
    b.set("03 31 13", "sf", material=1.0, desc="Test slab")
    costbook.save(b)
    ed = PriceEditor("Test Loc Book")
    qtbot.addWidget(ed)
    assert ed.locations.table.rowCount() >= 2
    ed.locations.add_region(**TESTVILLE)
    assert ed.save() == 0                      # book unchanged, factors saved
    assert "Testville" in _names(locfactors.rows())
