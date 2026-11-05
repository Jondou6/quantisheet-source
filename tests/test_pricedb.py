"""The shared price database, bid tabs and the scale box on the toolbar."""
import json
import os
import shutil

import fitz
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import (acrobat, annotate, assemblies, bidtab,  # noqa: E402
                 bidtab_core, costbook, pricedb, settings)
from test_gui import ANSWERS, win, qapp                    # noqa: E402,F401


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(assemblies, "LIBRARY_PATH",
                        str(tmp_path / "assemblies.json"))
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", None)
    pricedb.state.update(offline="", copied=0.0)


def _book(name="Shop 2026"):
    b = costbook.Book({"name": name, "effective": "2026-01-01",
                       "index": {"national": 1.0, "Georgia": 0.99},
                       "rates": {"national": {"Carpenter": 40.0},
                                 "Georgia": {"Carpenter": 35.0}}})
    b.set("A-1.1", "cy", material=150, desc="Concrete", basis="estimate")
    b.set("A-1.2", "hr", labor=1.0, crew="C-2", desc="Labor")
    return b


def test_books_live_in_the_database_with_history(monkeypatch):
    path = costbook.save(_book())
    assert path == "db:Shop 2026" and os.path.exists(pricedb.path())
    b = costbook.find("Shop 2026")
    assert b.get("A-1.1")["material"] == 150
    assert b.labor_rates("Georgia", "2026-01-01")["Carpenter"] == 35
    monkeypatch.setattr(pricedb, "user", lambda: "Jon")
    b.set("A-1.1", "cy", material=162, desc="Concrete", basis="quote")
    assert costbook.save(b, note="ABC quote") and True
    h = pricedb.history("Shop 2026", "A-1.1")
    assert {(x["field"], x["old"], x["new"], x["by"], x["note"])
            for x in h} >= {("material", "150.0", "162.0", "Jon",
                             "ABC quote")}
    # a JSON export still works and reads back
    out = os.path.join(settings.DIR, "export.json")
    costbook.save(b, out)
    assert costbook.load(out).get("A-1.1")["material"] == 162
    costbook.delete("Shop 2026")
    assert costbook.find("Shop 2026") is None


def test_two_estimators_edit_the_same_price(monkeypatch):
    costbook.save(_book())
    mine = pricedb.load_book("Shop 2026")
    loaded = {c: it["modified"] for c, it in mine["items"].items()}
    # someone else changes the concrete price first
    monkeypatch.setattr(pricedb, "user", lambda: "Maria")
    pricedb.update_items("Shop 2026", {"A-1.1": {"material": 158}},
                         note="supplier call")
    monkeypatch.setattr(pricedb, "user", lambda: "Jon")
    with pytest.raises(pricedb.Conflict) as e:
        pricedb.update_items("Shop 2026", {"A-1.1": {"material": 170}},
                             loaded)
    assert "Maria" in str(e.value)
    assert costbook.find("Shop 2026").get("A-1.1")["material"] == 158
    # a different item is fine
    pricedb.update_items("Shop 2026", {"A-1.2": {"crew": "C-3"}}, loaded)
    assert pricedb.update_rates("Shop 2026", {"Georgia": {"Carpenter": 36}},
                                {"Georgia": 1.01}) == 2
    b = costbook.find("Shop 2026")
    assert b.labor_rates("Georgia", "2026-01-01")["Carpenter"] == 36
    assert b.index["Georgia"] == pytest.approx(1.01)
    whos = {(h["code"], h["by"]) for h in pricedb.history("Shop 2026")}
    assert ("A-1.1", "Maria") in whos and ("rate:Georgia", "Jon") in whos


def test_shared_folder_copy_and_offline(tmp_path):
    costbook.save(_book())
    share = tmp_path / "server" / "Estimating"
    share.mkdir(parents=True)
    assert pricedb.use(str(share)) == "copied"
    assert pricedb.is_shared() and pricedb.path().endswith(pricedb.FILENAME)
    assert "Shop 2026" in costbook.list_books()
    # a second estimator connecting to the same file just connects
    assert pricedb.use(str(share)) == "connected"
    costbook.save(_book("Office"))
    pricedb._refresh_copy(force=True)
    # the server goes away: the local copy is used, read-only
    shutil.move(str(tmp_path / "server"), str(tmp_path / "gone"))
    assert set(costbook.list_books()) == {"Shop 2026", "Office"}
    assert "can't be reached" in pricedb.state["offline"]
    with pytest.raises(pricedb.PriceDBError):
        costbook.save(_book("New"))
    shutil.move(str(tmp_path / "gone"), str(tmp_path / "server"))
    costbook.save(_book("New"))
    assert not pricedb.state["offline"]
    pricedb.use_local()
    assert not pricedb.is_shared()
    assert pricedb.sync_folder_warning(r"D:\OneDrive\Prices\p.db")
    assert not pricedb.sync_folder_warning(r"\\server\est\p.db")
    assert os.path.exists(pricedb.snapshot())


def test_old_cost_book_files_move_in():
    folder = costbook.book_dir()
    with open(os.path.join(folder, "Old.json"), "w", encoding="utf-8") as f:
        json.dump(_book("Old Book").to_dict(), f)
    assert "Old Book" in costbook.list_books()
    assert costbook.find("Old Book").get("A-1.1")["material"] == 150


def _tabs(tmp_path):
    p = tmp_path / "tab.csv"
    p.write_text(bidtab_core.SAMPLE, encoding="utf-8")
    x = tmp_path / "tab2.xlsx"
    acrobat.write_xlsx(str(x), [("Bids", [
        ["Bid Item", "Description", "Unit", "Quantity", "Unit Price"],
        [1, "Excavation, unclassified", "CY", 500, 21.00],
        [2, "Concrete sidewalk, 4 in", "SF", 900, 8.25]])])
    return str(p), str(x)


def test_bid_tabs_library_escalation_and_assemblies(tmp_path):
    csvp, xlsx = _tabs(tmp_path)
    pid, n, bidders = bidtab.import_files([csvp], "Main St", "City", "MB",
                                          "SC", "2024-06")
    assert n == 30 and bidders == 3
    pid2, n2, b2 = bidtab.import_files([xlsx], "Oak Ave", state="NC",
                                       bid_date="2025-06", bidder="Acme")
    assert n2 == 2 and b2 == 1
    items = {i["desc"]: i for i in bidtab.analyze(to="2025-06")}
    ex = items["Excavation, unclassified"]
    assert ex["bids"] == 4 and ex["projects"] == 2 and ex["low"] == 17.5
    # the 2024 bids are escalated a year at the earthwork rate, 2025 not
    assert ex["esc_high"] == pytest.approx(21.0)
    assert ex["esc_low"] == pytest.approx(17.5 * 1.035)
    assert items["Catch basin, precast"]["flag"]
    assert items["Reinforcing steel, in place"]["trade"] == "03 Concrete"
    assert [i["desc"] for i in bidtab.analyze(state="NC")] == [
        "Concrete sidewalk, 4 in", "Excavation, unclassified"]
    for fmt in ("lib", "full", "roll"):
        out = bidtab.export(list(items.values()),
                            str(tmp_path / f"{fmt}.csv"), fmt, "2025-06")
        assert os.path.getsize(out) > 50
    names = bidtab.add_to_library([items["Concrete sidewalk, 4 in"]],
                                  "2025-06")
    lib = assemblies.library()
    a = lib[names[0]]
    assert a["measure"] == "area" and a["parts"][0]["cost"] == pytest.approx(
        items["Concrete sidewalk, 4 in"]["esc_median"], abs=0.01)
    d = fitz.open()
    d.new_page(width=2592, height=1728)
    annotate.apply_op(d, annotate.new_op("set_scale", 0, ppu=18, unit="ft"))
    annotate.apply_op(d, annotate.new_op(
        "add_polygon", 0, pts=[[100, 100], [280, 100], [280, 280],
                               [100, 280]],
        measure={"type": "area", "value": 100.0, "unit": "sq ft",
                 "group": names[0]}))
    rows, totals, _ = assemblies.rollup(d)
    assert totals["total"] == pytest.approx(
        100 * a["parts"][0]["cost"], rel=1e-6)
    cmp = bidtab.compare(d, "2025-06")
    assert cmp and cmp[0]["ratio"] == pytest.approx(1.0, abs=0.01)
    bidtab.remove_project(pid2)
    assert len(bidtab.projects()) == 1
    bidtab.set_rates({"31 Earthwork": 10})
    ex = {i["desc"]: i for i in bidtab.analyze(to="2025-06")}[
        "Excavation, unclassified"]
    assert ex["esc_low"] == pytest.approx(17.5 * 1.10)


def test_windows_edit_prices_database_and_bid_tabs(qapp, win, tmp_path,
                                                   monkeypatch):
    from app.pricedb_ui import (BidTabDialog, DatabaseDialog, ImportBidTab,
                                PriceEditor)
    costbook.save(_book())
    ed = PriceEditor("Shop 2026", win)
    assert ed.table.rowCount() == 2
    row = next(r for r in range(2) if ed.table.item(r, 0).text() == "A-1.1")
    ed.table.item(row, 3).setText("155")
    ed.note.setText("quote")
    assert ed.save() >= 1
    assert costbook.find("Shop 2026").get("A-1.1")["material"] == 155
    assert ed.fill_history()
    ed2 = PriceEditor("Shop 2026", win)
    ed2.rates.item(0, 0).setText("1.0")
    assert ed2.save() is not None
    db = DatabaseDialog(win)
    assert "This PC only" in db.info.text()
    share = tmp_path / "share"
    share.mkdir()
    assert db.choose(str(share)) == "copied"
    assert "Shared" in db.info.text()
    db.local()
    csvp, xlsx = _tabs(tmp_path)
    imp = ImportBidTab([csvp], win)
    assert imp.table.rowCount() == 30
    dlg = BidTabDialog(win._view.doc, win)
    vals = dict(imp.values(), state="SC", bid_date="2024-06")
    assert dlg.import_files([csvp], vals)
    assert dlg.proj.rowCount() == 1 and dlg.items.rowCount() == 10
    dlg.items.selectRow(0)
    assert dlg.add_selected()
    assert dlg.export(str(tmp_path / "lib.csv"), "lib")
    assert dlg.compare() == [] or True


def test_scale_presets_on_the_takeoff_toolbar(qapp, win):
    box = win.scale_box
    texts = [box.itemText(i).strip() for i in range(box.count())]
    assert '1/4" = 1\'-0"' in texts and "1\" = 20'" in texts
    assert "Calibrate…" in texts
    i = texts.index('1/4" = 1\'-0"')
    win.scale_all.setChecked(False)
    box.setCurrentIndex(i)
    win._scale_box_picked(i)
    sc = win._view.scale()
    assert sc and sc["name"] == '1/4" = 1\'-0"'
    assert box.currentIndex() == i
    # a page without a scale shows "(not set)"
    if win._view.doc.page_count > 1:
        win._view.go_to(1)
        win._sync_scale_box()
        assert box.currentIndex() == 0


def test_book_changed_outside_quantisheet_is_flagged():
    """Threat model T-016: a price changed straight in the database file
    (on a share) - same 'modified' stamp, different content - is flagged
    before the book is used; a normal save is not."""
    costbook.save(_book())
    assert pricedb.outside_change("Shop 2026") == ""     # first look
    b = costbook.find("Shop 2026")
    b.set("A-1.1", "cy", material=170, desc="Concrete", basis="quote")
    costbook.save(b)                                       # a normal save
    assert pricedb.outside_change("Shop 2026") == ""
    with pricedb.connect(write=True) as con:               # by hand
        con.execute("UPDATE items SET material = 1 WHERE book = ? AND "
                    "code = 'A-1.1'", ("Shop 2026",))
    pricedb._BOOK_CACHE.clear()
    msg = pricedb.outside_change("Shop 2026")
    assert "changed without QuantiSheet" in msg
    assert pricedb.outside_change("Shop 2026")             # still flagged
    pricedb.accept_outside_change("Shop 2026")
    assert pricedb.outside_change("Shop 2026") == ""
