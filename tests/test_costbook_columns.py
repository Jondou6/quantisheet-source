"""Cost book columns (brief item 7): Material $ and Equipment $ apart,
Labor Output (units per crew-day) and the unit Total in Edit Prices, and
Import CSV taking .xlsx too. Made-up items and prices only."""
import csv
import json
import os
import sqlite3
from decimal import Decimal

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import assemblies, cost_rollup, costbook, pricedb, settings  # noqa
from test_gui import ANSWERS, win, qapp                    # noqa: E402,F401


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(assemblies, "LIBRARY_PATH",
                        str(tmp_path / "assemblies.json"))
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", None)
    monkeypatch.setattr(pricedb, "user", lambda: "Pat Example")
    pricedb.state.update(offline="", copied=0.0)
    pricedb._BOOK_CACHE.clear()


def _test_book():
    """Material 1.20, Equipment 0.40, Labor 0.01 hrs/sf, a crew of 2
    workers at $40/hr."""
    b = costbook.Book({"name": "Test Columns", "effective": "2026-01-01",
                       "region": "national",
                       "rates": {"national": {"Carpenter": 40.0,
                                              "Helper": 40.0}}})
    b.set("03 31 13.35", "sf", material=1.20, labor=0.01, crew="C-2",
          desc="Test slab", equipment=0.40)
    return b


def test_unit_total_labor_output_and_equipment():
    b = _test_book()
    u = costbook.unit_cost(b, "03 31 13.35")
    assert u["labor_rate"] == Decimal(40)
    assert u["labor"] == Decimal("0.40")              # 0.01 x 40
    assert u["material"] == Decimal("1.20")
    assert u["equipment"] == Decimal("0.40")
    assert u["total"] == Decimal("2.00")
    assert costbook.unit_total(b, "03 31 13.35") == Decimal("2.00")
    assert u["output"] == Decimal(1600)               # (2 x 8) / 0.01
    assert costbook.labor_output(0.01, 2) == Decimal(1600)
    assert costbook.hours_from_output(400, 2) == Decimal("0.04")


def test_equipment_flows_to_the_rollup_equipment_column():
    b = _test_book()
    line = costbook.rollup_line(b, "03 31 13.35", 100, as_of="2026-01-01",
                                trade="Concrete")
    assert (line["M"], line["E"], line["L"]) == (
        Decimal("120.00"), Decimal("40.00"), Decimal("40.00"))
    t = cost_rollup.by_trade([line])["Concrete"]
    assert t["E"] == Decimal("40.00") and t["total"] == Decimal("200.00")
    # and an assembly part priced from the book gets equipment as well
    part = {"name": "Slab", "unit": "sf", "code": "03 31 13.35"}
    cost, hours = assemblies._book_price(part, b.get("03 31 13.35"), 1.0)
    assert cost == pytest.approx(1.60) and hours == pytest.approx(0.01)


def test_edit_prices_shows_the_new_columns(qapp, monkeypatch):
    from app.pricedb_ui import PriceEditor
    costbook.save(_test_book())
    ed = PriceEditor("Test Columns")
    heads = [ed.table.horizontalHeaderItem(c).text()
             for c in range(ed.table.columnCount())]
    for h in ("Material $", "Equipment $", "Labor Output", "Unit Total $"):
        assert h in heads
    assert "Material/Equip $" not in heads
    col = {h: i for i, h in enumerate(heads)}
    assert ed.table.item(0, col["Material $"]).text() == "1.2"
    assert ed.table.item(0, col["Equipment $"]).text() == "0.4"
    assert ed.table.item(0, col["Labor Output"]).text() == "1,600 sf/day"
    assert ed.table.item(0, col["Unit Total $"]).text() == "2.00"
    # editing Equipment $ saves it, and the total follows at once
    ed.table.item(0, col["Equipment $"]).setText("0.50")
    assert ed.table.item(0, col["Unit Total $"]).text() == "2.10"
    assert ed.save() >= 1
    assert costbook.find("Test Columns").get(
        "03 31 13.35")["equipment"] == pytest.approx(0.50)
    h = pricedb.history("Test Columns", "03 31 13.35")
    assert any(x["field"] == "equipment" and x["new"] == "0.5" for x in h)
    ed.close()


def _old_db(path):
    """A price database as 0.12.38 wrote it: items without the
    equipment / edition / imported / license columns."""
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
        INSERT INTO meta VALUES ('schema', '3');
        CREATE TABLE books (name TEXT PRIMARY KEY, effective TEXT,
            region TEXT, escalation REAL, notes TEXT, version TEXT,
            index_json TEXT, regions_json TEXT, created TEXT, modified TEXT,
            modified_by TEXT, extra_json TEXT);
        CREATE TABLE items (book TEXT, code TEXT, desc TEXT, unit TEXT,
            material REAL, labor REAL, crew TEXT, sub REAL, type TEXT,
            basis TEXT, source TEXT, modified TEXT, modified_by TEXT,
            sizes TEXT, PRIMARY KEY (book, code));
        INSERT INTO books VALUES ('Old Test Book', '2025-01-01', 'national',
            0.0, '', '', '{"national": 1.0}', '{}', '2025-01-01T00:00:00',
            '2025-01-01T00:00:00', 'Pat Example', '{}');
        INSERT INTO items VALUES ('Old Test Book', '09 29 10.30',
            'Test gyp board', 'sf', 0.55, 0.017, 'D-2', 0, '', 'estimate',
            'made-up', '2025-01-01T00:00:00', 'Pat Example', '');
    """)
    con.commit()
    con.close()


def test_old_book_opens_with_equipment_zero_and_saving_changes_nothing(
        qapp):
    os.makedirs(settings.DIR, exist_ok=True)
    _old_db(pricedb.path())
    data = pricedb.load_book("Old Test Book")
    it = data["items"]["09 29 10.30"]
    assert it["material"] == pytest.approx(0.55)
    assert "equipment" not in it                      # reads as 0
    b = costbook.find("Old Test Book")
    assert b.get("09 29 10.30").get("equipment", 0) == 0
    assert b.get("09 29 10.30")["material"] == pytest.approx(0.55)
    before = pricedb.content_hash(data)
    hist = len(pricedb.history("Old Test Book"))
    stamp = data["items"]["09 29 10.30"]["modified"]
    # saving through the API and through Edit Prices writes no change
    costbook.save(b)
    from app.pricedb_ui import PriceEditor
    ed = PriceEditor("Old Test Book")
    assert ed.save() == 0
    again = pricedb.load_book("Old Test Book")
    assert again["items"]["09 29 10.30"]["modified"] == stamp
    assert again["items"]["09 29 10.30"]["material"] == pytest.approx(0.55)
    assert len(pricedb.history("Old Test Book")) == hist
    assert pricedb.content_hash(again) == before
    ed.close()


def test_shipped_books_hash_as_before():
    """A book without the new fields hashes exactly as 0.12.38 did, so
    shipped-book updates still recognise unedited books."""
    import hashlib
    path = os.path.join(costbook.SHIPPED, "QuantiSheet Starter 2026.json")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    old_fields = ("desc", "unit", "material", "labor", "crew", "sub",
                  "type", "basis", "source")
    items = {c: {k: it.get(k) for k in old_fields}
             for c, it in data["items"].items()}
    blob = json.dumps([items, data.get("rates") or {},
                       data.get("index") or {},
                       data.get("escalation_by_div") or {}], sort_keys=True,
                      default=str)
    assert pricedb.content_hash(data) == hashlib.sha1(
        blob.encode("utf-8")).hexdigest()


ROWS = [["Code", "Description", "Unit", "Material", "Equipment", "Labor",
         "Crew", "Sub"],
        ["033113.35", "Test slab", "sf", "2.10", "0.15", "0.02", "F-4", ""],
        ["09 29 10.30", "Test gyp board", "sf", "0.55", "", "0.017", "D-2",
         ""],
        ["01 54 33.10", "Test scaffold", "mo", "300", "25", "0", "", ""]]


def test_same_rows_from_csv_and_xlsx_give_identical_books(tmp_path):
    import openpyxl
    c = tmp_path / "test prices.csv"
    with open(c, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(ROWS)
    x = tmp_path / "test prices.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    for r in ROWS:
        # numbers as numbers, the way Excel keeps them
        ws.append([float(v) if v.replace(".", "", 1).isdigit() and i > 2
                   else v for i, v in enumerate(r)])
    wb.save(x)
    a = costbook.from_csv(str(c), effective="2026-01-01")
    b = costbook.from_csv(str(x), effective="2026-01-01")
    assert a.to_dict() == b.to_dict()
    assert sorted(a.items) == ["01 54 33.10", "03 31 13.35", "09 29 10.30"]
    assert a.get("03 31 13.35")["equipment"] == pytest.approx(0.15)
    assert a.get("01 54 33.10")["equipment"] == pytest.approx(25)
    assert "equipment" not in a.get("09 29 10.30")


def test_cost_books_import_takes_xlsx(qapp, win, tmp_path, monkeypatch):
    import openpyxl
    from app.estimating_ui import CostBookDialog
    x = tmp_path / "Test xlsx book.xlsx"
    wb = openpyxl.Workbook()
    for r in ROWS:
        wb.active.append(r)
    wb.save(x)
    ANSWERS["open"] = str(x)
    ANSWERS["text"] = "Test xlsx book"
    ANSWERS["double"] = 0.0
    dlg = CostBookDialog(win._view.doc, win)
    dlg._import()
    b = costbook.find("Test xlsx book")
    assert b is not None and len(b.items) == 3
    assert b.get("03 31 13.35")["equipment"] == pytest.approx(0.15)
    dlg.close()

