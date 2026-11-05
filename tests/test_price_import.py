"""Import Your Own Price List (brief item 3, generic): map columns from
.xlsx / CSV, CSI codes normalised, unreadable codes under 'Needs code',
source / edition / import date on every row, and the book kept local-only:
refused on a shared price database, left out when the database moves to
a shared folder, a warning (Cancel by default) before export, and never
in the build. Made-up file 'my_licensed_costs.xlsx', source 'Test
Licensed Export', edition '2099' only."""
import csv
import json
import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtCore import Qt                                # noqa: E402
from PySide6.QtWidgets import QMessageBox                    # noqa: E402

from app import costbook, pricedb, priceimport, settings     # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import ship_check                                            # noqa: E402

SOURCE, EDITION = "Test Licensed Export", "2099"
HEAD = ["Code", "Description", "Unit", "Material", "Labor", "Equipment",
        "Hours", "Labor Output"]
ROWS = [["033113", "Test slab on grade", "sf", 2.10, 0.80, 0.15, 0.02, ""],
        ["03 31 13.35", "Test slab, finished", "sf", 2.40, 0.90, 0.20, "",
         400],
        ["09-29-10", "Test gyp board", "sf", 0.55, 0.40, 0, 0.017, ""],
        ["abc", "Test row without a code", "ea", 10, 5, 0, 0.1, ""]]


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", None)
    monkeypatch.setattr(pricedb, "user", lambda: "Pat Example")
    pricedb.state.update(offline="", copied=0.0, left_out=[])
    pricedb._BOOK_CACHE.clear()
    said = []
    for n in ("information", "warning", "critical"):
        monkeypatch.setattr(QMessageBox, n, staticmethod(
            lambda *a, **k: said.append(a[2] if len(a) > 2 else "") or 0))
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.Yes))
    return said


def _xlsx(tmp_path, rows=ROWS, head=HEAD):
    import openpyxl
    p = tmp_path / "my_licensed_costs.xlsx"
    wb = openpyxl.Workbook()
    wb.active.append(head)
    for r in rows:
        wb.active.append(r)
    wb.save(p)
    return str(p)


def _import(tmp_path, **kw):
    return priceimport.import_file(_xlsx(tmp_path), name="My Test Prices",
                                   source=SOURCE, edition=EDITION,
                                   crew_size=2, **kw)


def test_codes_normalised_and_needs_code(tmp_path):
    head, rows = priceimport.read(_xlsx(tmp_path))
    m = priceimport.guess_mapping(head)
    assert m == {"code": 0, "desc": 1, "unit": 2, "material": 3,
                 "labor": 4, "equipment": 5, "hours": 6, "output": 7}
    res = priceimport.build(head, rows, m, "My Test Prices", SOURCE,
                            EDITION, crew_size=2)
    assert res["imported"] == ["03 31 13", "03 31 13.35", "09 29 10"]
    assert [x["code"] for x in res["needs_code"]] == ["abc"]
    assert res["needs_code"][0]["row"] == 5          # spreadsheet row
    for raw, want in (("033113", "03 31 13"), ("03 31 13", "03 31 13"),
                      ("03-31-13", "03 31 13"),
                      ("03 31 13.35", "03 31 13.35"), ("33113", "03 31 13"),
                      ("abc", ""), ("3", ""), ("99 99 99", "")):
        assert priceimport.normalize_code(raw) == want, raw
    # a fixed code imports the row; a skipped one stays out
    res = priceimport.build(head, rows, m, "x", SOURCE, fixes={3:
                                                               "01 54 33"})
    assert "01 54 33" in res["imported"] and not res["needs_code"]
    res = priceimport.build(head, rows, m, "x", SOURCE, skip={3})
    assert not res["needs_code"] and len(res["imported"]) == 3


def test_every_row_carries_source_edition_and_date(tmp_path, qtbot):
    res = _import(tmp_path)
    b = costbook.find("My Test Prices")
    assert b.local_only
    for code in ("03 31 13", "03 31 13.35", "09 29 10"):
        it = b.get(code)
        assert it["source"] == SOURCE and it["edition"] == EDITION
        assert it["imported"] == priceimport.today()
        assert it["license"] == pricedb.LOCAL_ONLY
    it = b.get("03 31 13")
    assert it["material"] == pytest.approx(2.10)
    assert it["equipment"] == pytest.approx(0.15)
    assert it["labor"] == pytest.approx(0.02)
    assert res["saved"] == "db:My Test Prices"
    # Edit Prices shows Source and Edition, and they survive reopening
    from app.pricedb_ui import PriceEditor
    for _ in range(2):
        pricedb._BOOK_CACHE.clear()
        ed = PriceEditor("My Test Prices")
        qtbot.addWidget(ed)
        heads = [ed.table.horizontalHeaderItem(c).text()
                 for c in range(ed.table.columnCount())]
        src, ed_col = heads.index("Source"), heads.index("Edition")
        for r in range(ed.table.rowCount()):
            assert ed.table.item(r, src).text() == SOURCE
            assert ed.table.item(r, ed_col).text() == EDITION
        assert "local-only" in ed.status.text()
        ed.close()


def test_labor_output_with_hours_blank(tmp_path):
    """Crew of 2 x 8 h, output 400 sf/day -> (2 x 8) / 400 = 0.04 h/sf."""
    _import(tmp_path)
    it = costbook.find("My Test Prices").get("03 31 13.35")
    assert it["labor"] == pytest.approx(0.04)
    head, rows = priceimport.read(_xlsx(tmp_path))
    prev = priceimport.preview(head, rows, priceimport.guess_mapping(head),
                               crew_size=2, hours_per_day=8)
    assert prev[1]["hours"] == "0.04" and prev[1]["hours_from"] == "output"
    assert prev[3]["status"] == "Needs code"


def _share(tmp_path):
    share = tmp_path / "share" / "Test Office"
    share.mkdir(parents=True)
    return str(share / pricedb.FILENAME)


def test_refused_on_a_shared_price_database(tmp_path, qtbot, _isolated):
    settings.set("price_db", _share(tmp_path))
    assert pricedb.is_shared()
    with pytest.raises(pricedb.LocalOnlyError) as e:
        _import(tmp_path)
    assert "can only be kept in this PC's local price database" in \
        str(e.value)
    assert "My Test Prices" not in pricedb.book_names()
    # the window says so too and writes nothing
    from app.priceimport_ui import ImportPriceListDialog
    dlg = ImportPriceListDialog(None, _xlsx(tmp_path))
    qtbot.addWidget(dlg)
    dlg.source.setText(SOURCE)
    dlg.edition.setText(EDITION)
    assert "this PC's local price database" in dlg.where.text()
    assert dlg.do_import() is None
    assert any("can only be kept in this PC's local price database" in m
               for m in _isolated)
    assert pricedb.book_names() == []


def test_moving_to_a_shared_folder_asks_and_leaves_it_out(tmp_path, qtbot,
                                                          monkeypatch):
    other = costbook.Book({"name": "Test Shared Book"})
    other.set("03 31 13", "sf", material=1.0, desc="Test slab")
    costbook.save(other)
    _import(tmp_path)
    assert pricedb.local_only_books() == ["My Test Prices"]
    from app.pricedb_ui import DatabaseDialog
    asked = []

    def question(*a, **k):
        asked.append(a[2])
        return QMessageBox.Yes
    monkeypatch.setattr(QMessageBox, "question", staticmethod(question))
    db = DatabaseDialog()
    qtbot.addWidget(db)
    folder = os.path.dirname(_share(tmp_path))
    assert db.choose(folder) == "copied"
    assert any("can only be kept in this PC's local price database" in q
               and "My Test Prices" in q for q in asked)
    assert pricedb.is_shared()
    assert pricedb.book_names() == ["Test Shared Book"]
    assert pricedb.state["left_out"] == ["My Test Prices"]
    with open(pricedb.path(), "rb") as f:
        assert SOURCE.encode() not in f.read()
    # this PC's own database still has it
    pricedb.use_local()
    assert "My Test Prices" in pricedb.book_names()
    # saying No moves nothing
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.No))
    other_share = tmp_path / "share2"
    other_share.mkdir()
    assert db.choose(str(other_share)) is None
    assert not pricedb.is_shared()


def test_export_warns_with_cancel_as_default(tmp_path, qtbot, monkeypatch):
    from app import priceimport_ui
    _import(tmp_path)
    b = costbook.find("My Test Prices")
    box = priceimport_ui.share_warning_box(None, b.name, "export")
    assert box.defaultButton() is box.button(QMessageBox.Cancel)
    assert "licensed price data" in box.text()
    assert "licence holder" in box.informativeText()
    shown = []

    def fake_exec(self):
        shown.append((self.text(), self.defaultButton()))
        return 0                                     # Cancel: nothing out
    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    assert priceimport_ui.confirm_share(None, b) is False
    assert shown and shown[0][1] is not None
    # an ordinary book is exported without asking
    plain = costbook.Book({"name": "Test Plain"})
    assert priceimport_ui.confirm_share(None, plain) is True
    assert len(shown) == 1
    # Cost Books > Export JSON asks and, on Cancel, writes nothing
    from app.estimating_ui import CostBookDialog
    import fitz
    d = fitz.open()
    d.new_page()
    dlg = CostBookDialog(d)
    qtbot.addWidget(dlg)
    for i in range(dlg.books.count()):
        if dlg.books.item(i).data(Qt.UserRole) == "My Test Prices":
            dlg.books.setCurrentRow(i)
    out = tmp_path / "exported.json"
    assert dlg._export_json(str(out)) is None
    assert not out.exists() and len(shown) == 2


def test_the_window_maps_previews_and_imports(tmp_path, qtbot):
    from app.priceimport_ui import ImportPriceListDialog
    dlg = ImportPriceListDialog(None, _xlsx(tmp_path))
    qtbot.addWidget(dlg)
    assert dlg.mapping()["code"] == 0 and dlg.mapping()["output"] == 7
    assert dlg.preview.rowCount() == 4
    assert dlg.preview.item(0, 1).text() == "03 31 13"
    assert dlg.needs.rowCount() == 1
    assert dlg.needs.item(0, 1).text() == "abc"
    dlg.crew.setValue(2)
    dlg.name.setText("My Test Prices")
    dlg.source.setText(SOURCE)
    dlg.edition.setText(EDITION)
    assert dlg.fix_code(0, "01 54 33")
    assert dlg.needs.rowCount() == 0
    res = dlg.do_import()
    assert res and len(res["imported"]) == 4
    assert costbook.find("My Test Prices").get(
        "03 31 13.35")["labor"] == pytest.approx(0.04)


def test_csv_works_the_same(tmp_path):
    p = tmp_path / "my_licensed_costs.csv"
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(HEAD)
        w.writerows(ROWS)
    head, rows = priceimport.read(str(p))
    res = priceimport.build(head, rows, priceimport.guess_mapping(head),
                            "x", SOURCE, EDITION, crew_size=2)
    assert res["imported"] == ["03 31 13", "03 31 13.35", "09 29 10"]


def test_build_contains_no_local_only_rows(tmp_path):
    """Ship check: app/data/costbooks (and so the installer, portable zip
    and team zip built from it) holds no book or row tagged local-only;
    a build that did is stopped."""
    tags = (SOURCE,)
    data = os.path.join(ROOT, "app", "data")
    assert ship_check.local_only_problems(data, tags) == []
    assert ship_check.require_no_local_only(
        os.path.join(data, "costbooks"), "app/data/costbooks", tags) == []
    # a made-up build with an exported local-only book is refused
    _import(tmp_path)
    build = tmp_path / "build" / "app" / "data" / "costbooks"
    build.mkdir(parents=True)
    costbook.save(costbook.find("My Test Prices"),
                  str(build / "mine.json"))
    with open(build / "mine.json", encoding="utf-8") as f:
        assert json.load(f)["local_only"] is True
    found = ship_check.local_only_problems(str(tmp_path / "build"), tags)
    assert found and "mine.json" in found[0]
    with pytest.raises(RuntimeError):
        ship_check.require_no_local_only(str(tmp_path / "build"),
                                         "the test build", tags)
    # ...inside a zip too, and a price database file with such rows
    import zipfile
    z = tmp_path / "zips" / "team.zip"
    z.parent.mkdir()
    with zipfile.ZipFile(z, "w") as zf:
        zf.write(build / "mine.json", "app/data/costbooks/mine.json")
    assert ship_check.local_only_problems(str(z.parent), tags)
    assert ship_check.local_only_problems(pricedb.path(), tags)


def test_no_vendor_names_in_the_importer():
    """Generic: the importer, its window and these tests name no cost-data
    vendor (the words are built here so this file doesn't name them)."""
    words = ["".join(w) for w in (("B", "N", "i "), ("e", "Con", "verge"),
                                  ("RS", "Means"), ("Gor", "dian"),
                                  ("Crafts", "man"))]
    for rel in ("app/priceimport.py", "app/priceimport_ui.py",
                "app/locfactors.py", "app/location_ui.py", "app/jobinfo.py",
                "app/jobinfo_ui.py", "tests/test_price_import.py",
                "tests/test_location_factors.py", "tests/test_job_info.py",
                "tests/test_costbook_columns.py"):
        with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
            text = f.read().lower()
        for w in words:
            assert w.lower() not in text, (rel, w)
