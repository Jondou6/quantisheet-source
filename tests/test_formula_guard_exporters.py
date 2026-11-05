"""Review F7 (security fix d, finished): every CSV / Excel exporter keeps
user text as text. A description, name or note that starts with = + - @
must never reach a spreadsheet as a live formula; the program's own
formulas (=SUM, =IF ...) stay formulas. The Sage import CSV gets the
leading characters stripped instead of an apostrophe. Made-up names and
example.invalid only."""
import csv
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import safecell

EVIL = '=HYPERLINK("http://example.invalid","x")'
AT = "@SUM(1)"
BAD_START = ("=", "+", "-", "@")


# ------------------------------------------------------------- helpers
def _csv_cells(path, delimiter=","):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return [c for row in csv.reader(f, delimiter=delimiter) for c in row]


def _text_cells(text, delimiter=","):
    return [c for row in csv.reader(text.splitlines(), delimiter=delimiter)
            for c in row]


def assert_csv_safe(cells, quoted=True):
    """No cell starts with = + - @ (plain numbers like -312.47 aside), and
    the made-up attack text is there, as text."""
    for c in cells:
        assert not safecell.risky(c), c
    if quoted:
        assert "'" + EVIL in cells and "'" + AT in cells, cells


def assert_xlsx_safe(path, own_formula=None):
    """No formula cell carries user text; EVIL / AT are text cells. With
    own_formula: at least one live formula containing it is still there."""
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.load_workbook(path)
    seen, own = set(), 0
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for c in row:
                v = c.value
                if c.data_type == "f":
                    assert "HYPERLINK" not in str(v) and \
                        "example.invalid" not in str(v), (ws.title, v)
                    if own_formula and own_formula in str(v):
                        own += 1
                if isinstance(v, str) and (EVIL in v or AT in v):
                    assert c.data_type == "s", (ws.title, c.coordinate)
                    seen.update(x for x in (EVIL, AT) if x in v)
    assert seen == {EVIL, AT}, seen
    if own_formula:
        assert own, f"no {own_formula} formula left"


@pytest.fixture
def pm_store(tmp_path, monkeypatch):
    from app import settings
    from app.pm.store import ProjectStore
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", {"author": "Example Super"})
    return ProjectStore(str(tmp_path / "Example Job"))


# ------------------------------------------------------------- exporters
def test_submittal_lookahead_excel(pm_store, tmp_path):
    pytest.importorskip("openpyxl")
    from datetime import date
    from app.pm import lookahead
    pm_store.save_record("submittal", {
        "title": EVIL, "spec": "03 30 00", "type": "Product Data",
        "status": "Not Submitted", "responsible": AT,
        "submit_by": "2026-10-30"})
    path = str(tmp_path / "look.xlsx")
    lookahead.export_xlsx(pm_store, path, 3, date(2026, 10, 20))
    assert_xlsx_safe(path)


def test_activity_lookahead_excel(pm_store, tmp_path):
    pytest.importorskip("openpyxl")
    from datetime import date
    from app.pm import activity_lookahead as la
    pm_store.save_record("activity", {"name": EVIL, "duration": 5,
                                      "start": "2026-11-03", "notes": AT,
                                      "constraints": AT})
    path = str(tmp_path / "act.xlsx")
    la.export_xlsx(pm_store, path, 2, date(2026, 11, 4))
    openpyxl = pytest.importorskip("openpyxl")
    ws = openpyxl.load_workbook(path).active
    for row in ws.iter_rows():
        for c in row:
            assert c.data_type != "f", (c.coordinate, c.value)
            if c.value == EVIL:
                assert c.data_type == "s"
    assert any(c.value == EVIL for row in ws.iter_rows() for c in row)


def test_scope_sheet_excel_keeps_its_own_formulas(tmp_path):
    pytest.importorskip("openpyxl")
    from app.pm import scope_sheet as ss
    sh = ss.new_sheet(csi="09 29 00", trade="Example Drywall", bidders=0,
                      header={"project": AT, "estimator": EVIL})
    ss.add_bidder(sh, company=EVIL)
    ss.add_bidder(sh, company=AT)
    ln = ss.add_line(sh, EVIL)
    ss.add_line(sh, AT)
    path = ss.export_xlsx([sh], str(tmp_path / "scope.xlsx"),
                          company={"name": AT, "logo": ""})
    assert_xlsx_safe(path, own_formula="SUM(")
    assert ln is not None


@pytest.mark.parametrize("ext", ["xlsx", "csv"])
def test_roof_summary(tmp_path, ext):
    if ext == "xlsx":
        pytest.importorskip("openpyxl")
    from app import roof
    rows = [[EVIL, "Count", AT, "", "", "", 3, "ea", "", "", ""],
            ["A-101", "Derived", "Example ridge", 40.0, "", 1.0, 40.0, "lf",
             "", "", ""]]
    path = roof.export_summary(str(tmp_path / f"roof.{ext}"), rows)
    if ext == "xlsx":
        assert_xlsx_safe(path)
    else:
        assert_csv_safe(_csv_cells(path))


def test_sage_import_csv_strips_formula_starts(tmp_path):
    pytest.importorskip("fitz")          # sage_export -> assembly_codes
    from app import sage_export as sage
    rows = [{"Job": "2417", "Extra": AT, "Cost Code": "09-2900",
             "Category": "M", "Description": EVIL, "Units": Decimal("12"),
             "Unit of Measure": "-SF", "Amount": Decimal("-312.47")}]
    path = sage.export_csv(str(tmp_path / "sage.csv"), rows)
    cells = _csv_cells(path)
    for c in cells:
        assert not safecell.risky(c), c
        assert not c.startswith("'"), c         # Sage wants no apostrophe
    assert 'HYPERLINK("http://example.invalid","x")' in cells
    assert "SUM(1)" in cells and "SF" in cells
    assert "-312.47" in cells                   # numbers are left alone


def test_leveling_matrix_and_gaps(tmp_path):
    from app import level_core as lc
    it = lc.Item("k1", EVIL, "EA", 1)
    it.item_no = AT
    it.prices = {AT: 10.0, "Example Co": 12.0}
    bidders = [AT, "Example Co", "Example Omit Co"]
    m = tmp_path / "matrix.csv"
    lc.write_matrix(Path(m), [it], bidders, {}, 1.5, 0.5)
    assert_csv_safe(_csv_cells(m))
    g = tmp_path / "gaps.csv"
    lc.write_gaps(Path(g), [it], bidders, {}, 1)
    cells = _csv_cells(g)
    assert_csv_safe(cells, quoted=False)
    assert "'" + EVIL in cells


def test_bid_tab_library_export(tmp_path, monkeypatch):
    from app import bidtab
    items = [{"trade": AT, "desc": EVIL, "unit": "SF", "median": 2.5,
              "bids": 3, "low": 2.0, "high": 3.0, "esc_median": 2.6}]
    path = bidtab.export(items, str(tmp_path / "lib.csv"), "lib")
    assert_csv_safe(_csv_cells(path))


def test_bid_tab_core_render():
    from app import bidtab_core as core
    st = core.ItemStats(n=2, low=1.0, median=2.0, mean=2.0, high=3.0,
                        spread_pct=10.0)
    items = [core.Item(desc=EVIL, unit="SF", trade=AT, qty=10.0, stats=st)]
    roll = [core.Rollup(trade=AT, items=1, extended_base=20.0,
                        extended_low=10.0, extended_escalated=21.0,
                        avg_spread=10.0, max_spread=10.0)]
    for fmt in ("lib", "full"):
        assert_csv_safe(_text_cells(core.render(items, roll, fmt, 0, {},
                                                3.0)))
    assert_csv_safe(_text_cells(core.render(items, roll, "tsv", 0, {}, 3.0),
                                "\t"))
    cells = _text_cells(core.render(items, roll, "roll", 0, {}, 3.0))
    assert "'" + AT in cells and not any(safecell.risky(c) for c in cells)


def test_heavy_table_csv(tmp_path):
    from app import heavy
    path = heavy.export_rows(str(tmp_path / "t.csv"), "Example",
                             [["Item", "Description"], [AT, EVIL],
                              ["", -5.25]])
    cells = _csv_cells(path)
    assert_csv_safe(cells)
    assert "-5.25" in cells


def test_genset_quantities_csv(tmp_path, monkeypatch):
    from app.genset import quantities as q
    monkeypatch.setattr(q, "rows", lambda plan: [(AT, EVIL, 12, "SF", "")])
    path = q.write_csv(None, str(tmp_path / "q.csv"))
    assert_csv_safe(_csv_cells(path))


def _rollup():
    one = Decimal("1.00")
    return {"trades": {EVIL: {"L": one, "M": one, "E": one,
                              "total": Decimal("3.00")}},
            "direct": Decimal("3.00"), "tax_pct": Decimal("6"),
            "material": one, "tax": Decimal("0.06"),
            "steps": [{"label": AT, "pct": Decimal("5"),
                       "amount": Decimal("0.15")}],
            "total": Decimal("3.21"), "building_sf": Decimal("100"),
            "per_sf": Decimal("0.03"), "per_sf_text": "0.03"}


@pytest.mark.parametrize("ext", ["xlsx", "csv"])
def test_cost_rollup(tmp_path, ext):
    pytest.importorskip("fitz")          # cost_rollup -> annotate
    if ext == "xlsx":
        pytest.importorskip("openpyxl")
    from app import cost_rollup
    path = str(tmp_path / f"bid.{ext}")
    cost_rollup.export(path, _rollup())
    if ext == "xlsx":
        assert_xlsx_safe(path)
    else:
        cells = _csv_cells(path)
        assert "'" + EVIL in cells and not any(safecell.risky(c)
                                               for c in cells)
        assert any(AT in c and c.startswith("'") for c in cells)


def test_assembly_csv_and_round_trip(tmp_path):
    pytest.importorskip("fitz")          # parse -> assemblies -> annotate
    from app import assembly_csv
    asm = [{"id": "EX-1", "name": EVIL, "measure": "area", "csi": "09",
            "trade": AT, "parts": [{"name": AT, "qty": "A * 1.1",
                                    "unit": "sf", "type": "Material",
                                    "code": "09 29 00"}]}]
    path = assembly_csv.write(asm, str(tmp_path / "asm.csv"))
    assert_csv_safe(_csv_cells(path))
    # the apostrophe comes off again on import
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    got, _problems = assembly_csv.parse(rows)
    assert got and got[0]["name"].startswith(EVIL)
    tpl = assembly_csv.cost_book_template(asm, str(tmp_path / "book.csv"))
    assert_csv_safe(_csv_cells(tpl))


@pytest.mark.parametrize("ext", ["xlsx", "csv"])
def test_assembly_codes_library(tmp_path, ext):
    pytest.importorskip("fitz")          # assembly_codes -> annotate
    if ext == "xlsx":
        pytest.importorskip("openpyxl")
    from app import assembly_codes as ac
    row = [AT, EVIL] + [""] * (len(ac.COLS) - 2)
    path = str(tmp_path / f"lib.{ext}")
    ac.write_rows(path, [row])
    if ext == "xlsx":
        assert_xlsx_safe(path)
    else:
        assert_csv_safe(_csv_cells(path))
    back = ac._rows(path)
    assert back[1][:2] == [AT, EVIL]          # read back as it was


def test_vocab_batch_output(tmp_path, monkeypatch):
    from app import vocab_core as vc
    src = tmp_path / "in.txt"
    src.write_text(EVIL + "\n" + AT + "\n", encoding="utf-8")

    class _M:
        def __init__(self, *a):
            pass

        def match(self, line):
            return {"input": line, "match": AT, "item_id": 7, "unit": "SF",
                    "score": 1.0, "method": "exact"}

    monkeypatch.setattr(vc, "Matcher", _M)
    out = tmp_path / "out.csv"
    vc.cmd_batch(None, SimpleNamespace(threshold=0.8, path=src, column=None,
                                       out=out))
    assert_csv_safe(_csv_cells(out))


def test_unquote_only_undoes_safe_cell():
    for v in (EVIL, AT, "+1+1", "-2+3"):
        assert safecell.unquote(safecell.safe_cell(v)) == v
    for v in ("'Example", "'5", "'-312.47", "Example", 5, None):
        assert safecell.unquote(v) == v
