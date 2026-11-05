"""r36 v2 step 7 (G3.2): Import Actuals - a CSV / Excel file of actual
costs (and quantities) by cost code or by the item id of an earlier
export. Preview first; a bad file or bad rows never give a partial
write; several items on one code share the amount by estimate cost (to
the cent, flagged); unmatched codes are listed. Into the drawing only -
never the price database. Made-up data only."""
import csv
import os
from decimal import Decimal

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import assemblies, estimate_lines as EL, settings          # noqa: E402
from app.estimating import _io, actuals                             # noqa: E402
from estimate_helpers import blank_doc                              # noqa: E402

D = Decimal


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(assemblies, "LIBRARY_PATH",
                        str(tmp_path / "assemblies.json"))
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", None)


def _doc():
    d = blank_doc()
    ids = EL.add(d, [EL.new_line("Test footing", 10, "cy", mat=30,
                                 code="03 30 00"),          # 300
                     EL.new_line("Test slab", 10, "cy", mat=10,
                                 code="03 30 00"),          # 100
                     EL.new_line("Test drywall", 1000, "sf", mat="2.00",
                                 code="09 29 00"),
                     EL.new_line("Test a", 1, "ea", mat=1, code="10 00 00"),
                     EL.new_line("Test b", 1, "ea", mat=1, code="10 00 00"),
                     EL.new_line("Test c", 1, "ea", mat=1, code="10 00 00")])
    return d, ids


def _csv(path, rows, enc="utf-8"):
    with open(path, "w", newline="", encoding=enc) as f:
        csv.writer(f).writerows(rows)
    return str(path)


def test_preview_matches_by_code_and_shares_pro_rata(tmp_path):
    d, ids = _doc()
    p = _csv(tmp_path / "a.csv", [
        ["Cost Code", "Description", "Actual Cost", "Actual Qty"],
        ["03-30-00", "Concrete", "1000.00", ""],
        ["092900", "Drywall", "2,150.50", "1100"],
        ["10 00 00", "Specialties", "100.00", ""],
        ["99 99 99", "Unknown", "55.00", ""]])
    before = actuals.read(d)
    pv = actuals.import_preview(d, p)
    assert actuals.read(d) == before                    # preview writes nothing
    by = {r["id"]: r for r in pv["rows"]}
    assert by[ids[0]]["cost"] == D("750.00") and by[ids[1]]["cost"] == \
        D("250.00")
    assert "shared" in by[ids[0]]["how"]
    assert by[ids[2]]["cost"] == D("2150.50") and by[ids[2]]["qty"] == \
        D("1100")
    three = [by[i]["cost"] for i in ids[3:]]
    assert sum(three) == D("100.00") and sorted(three) == \
        [D("33.33"), D("33.33"), D("33.34")]
    assert [u["code"] for u in pv["unmatched"]] == ["99 99 99"]
    assert by[ids[0]]["qty"] is None            # shared: qty not guessed


def test_apply_writes_everything_once_and_is_repeatable(tmp_path):
    d, ids = _doc()
    p = _csv(tmp_path / "a.csv", [["Code", "Amount"], ["09 29 00", "2000"]])
    n = actuals.apply_import(d, actuals.import_preview(d, p))
    assert n == 1 and actuals.read(d)[ids[2]]["cost"] == "2000.00"
    actuals.apply_import(d, actuals.import_preview(d, p))
    assert len(actuals.read(d)) == 1                 # replaced, not doubled
    assert "imported" in actuals.read(d)[ids[2]]["note"]


def test_bad_rows_are_listed_and_the_rest_kept(tmp_path):
    d, ids = _doc()
    p = _csv(tmp_path / "a.csv", [["Cost code", "Actual cost"],
                                  ["09 29 00", "abc"],
                                  ["03 30 00", "400"],
                                  ["", "12"]])
    pv = actuals.import_preview(d, p)
    assert [s["line"] for s in pv["skipped"]] == [2, 4]
    assert "abc" in pv["skipped"][0]["why"]
    assert {r["id"] for r in pv["rows"]} == {ids[0], ids[1]}


def test_a_broken_file_writes_nothing(tmp_path):
    d, ids = _doc()
    actuals.record(d, ids[2], cost="5")
    before = actuals.read(d)
    p = tmp_path / "bad.csv"
    p.write_bytes(b"Code,Amount\n09 29 00,10\n\x00\x00\x00garbage")
    with pytest.raises(_io.TableError):
        actuals.import_preview(d, str(p))
    q = _csv(tmp_path / "nohead.csv", [["foo", "bar"], ["1", "2"]])
    with pytest.raises(actuals.ActualsError):
        actuals.import_preview(d, q)
    assert actuals.read(d) == before


def test_windows_1252_file_is_read(tmp_path):
    d, ids = _doc()
    p = _csv(tmp_path / "w.csv", [["Cost Code", "Description", "Actual Cost"],
                                  ["09 29 00", "Plâtre café", "10"]],
             enc="cp1252")
    pv = actuals.import_preview(d, p)
    assert pv["rows"][0]["cost"] == D("10.00")


def test_item_ids_from_an_earlier_export_match_first(tmp_path):
    d, ids = _doc()
    e = tmp_path / "e.csv"
    actuals.export(actuals.compare(d), str(e))
    rows = list(csv.reader(open(e, encoding="utf-8-sig")))
    h = rows[0]
    for r in rows[1:]:
        r[h.index("Actual cost")] = "12.34"
        r[h.index("Actual qty")] = "3"
    p = _csv(tmp_path / "back.csv", rows)
    pv = actuals.import_preview(d, p)
    assert {r["id"] for r in pv["rows"]} == set(ids)
    assert all(r["how"] == "item id" and r["cost"] == D("12.34") and
               r["qty"] == D("3") for r in pv["rows"])


def test_dangerous_text_is_not_a_formula_in_the_export(tmp_path):
    d, ids = _doc()
    p = _csv(tmp_path / "a.csv", [["Code", "Description", "Amount"],
                                  ["09 29 00", "=HYPERLINK(\"x\")", "5"]])
    actuals.apply_import(d, actuals.import_preview(d, p))
    e = tmp_path / "e.csv"
    actuals.export(actuals.compare(d), str(e))
    txt = open(e, encoding="utf-8-sig").read()
    assert ",=HYPERLINK" not in txt and "\n=HYPERLINK" not in txt


def test_import_never_touches_the_price_database(tmp_path):
    from app import pricedb
    d, ids = _doc()
    p = _csv(tmp_path / "a.csv", [["Code", "Amount"], ["09 29 00", "2000"]])
    had = os.path.exists(pricedb.path())
    actuals.apply_import(d, actuals.import_preview(d, p))
    assert os.path.exists(pricedb.path()) == had
