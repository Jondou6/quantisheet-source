"""Bid leveling (your level.py) and routed bid tab imports (import_cost)."""
import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import (assemblies, bidtab, bidtab_core, level_core,  # noqa: E402
                 leveling, pricedb, settings, vocab)
from test_gui import ANSWERS, win, qapp                    # noqa: E402,F401

TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(
    __file__))), "tools")

TAB = """Item,Description,Unit,Qty,Bidder,Unit Price
1,"Excavation, unclassified",CY,1000,Acme,18.00
2,"Concrete sidewalk, 4 in",SF,2000,Acme,7.00
3,"Catch basin, precast",EA,10,Acme,INCL
4,"Chain link fence, 6 ft",LF,500,Acme,24.00
5,"Topsoil & seeding",SF,5000,Acme,0.60
6,"Storm sewer, RCP 18 in",LF,400,Acme,60.00
1,"Excavation, unclassified",CY,1000,Bolt,19.00
2,"Concrete sidewalk, 4 in",SF,2000,Bolt,7.40
3,"Catch basin, precast",EA,10,Bolt,3500.00
4,"Chain link fence, 6 ft",LF,500,Bolt,52.00
5,"Topsoil & seeding",SF,5000,Bolt,0.62
6,"Storm sewer, RCP 18 in",LF,400,Bolt,58.00
1,"Excavation, unclassified",CY,1000,Cobb,17.50
2,"Concrete sidewalk, 4 in",SF,2000,Cobb,7.20
3,"Catch basin, precast",EA,10,Cobb,3600.00
4,"Chain link fence, 6 ft",LF,500,Cobb,25.00
5,"Topsoil & seeding",SF,5000,Cobb,0.30
6,"Storm sewer, RCP 18 in",LF,400,Cobb,59.00
1,"Excavation, unclassified",CY,1000,Dyer,16.00
2,"Concrete sidewalk, 4 in",SF,2000,Dyer,6.90
3,"Catch basin, precast",EA,10,Dyer,By others
4,"Chain link fence, 6 ft",LF,500,Dyer,24.50
5,"Topsoil & seeding",SF,5000,Dyer,0.61
6,"Storm sewer, RCP 18 in",LF,400,Dyer,61.00
"""


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(assemblies, "LIBRARY_PATH",
                        str(tmp_path / "assemblies.json"))
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", None)
    pricedb.state.update(offline="", copied=0.0)


def _file(tmp_path):
    p = tmp_path / "tab.csv"
    p.write_text(TAB, encoding="utf-8")
    return str(p)


def test_incl_and_excluded_lines(tmp_path):
    rows = bidtab_core.parse_lines(TAB.strip().splitlines(), "x", {})
    notes = {(r.bidder, r.item_no): r.note for r in rows}
    assert notes[("Acme", "3")] == "included"
    assert notes[("Dyer", "3")] == "excluded"
    pid, n, b = bidtab.import_files([_file(tmp_path)], "Job", state="SC",
                                    bid_date="2026-09")
    cb = {i["desc"]: i for i in bidtab.analyze(to="2026-09")}[
        "Catch basin, precast"]
    assert cb["bids"] == 2 and cb["low"] == 3500           # no $0 prices


def test_leveling_finds_the_buried_omission(tmp_path):
    pid, n, b = bidtab.import_files([_file(tmp_path)], "Job", state="SC",
                                    bid_date="2026-09")
    res = leveling.run(leveling.from_project(pid))
    by = {r["bidder"]: r for r in res["results"]}
    # Dyer left the catch basins out ("By others"): low base, not low leveled
    assert by["Dyer"]["omissions"] == 1
    assert by["Dyer"]["added"] == pytest.approx(3550 * 10)
    # Acme carried them elsewhere (INCL): not an omission
    assert by["Acme"]["omissions"] == 0
    assert min(res["results"], key=lambda r: r["base"])["bidder"] == "Dyer"
    assert res["results"][0]["bidder"] != "Dyer" and "Dyer" in res["risk"]
    assert by["Bolt"]["carries"] == 1                       # fence at 2x
    assert by["Cobb"]["buyins"] == 1                        # topsoil at 0.5x
    # with 4 bids the robust test still catches the fence price
    assert by["Bolt"]["outliers"] >= 1
    cb = next(i for i in res["items"] if i.desc.startswith("Catch"))
    assert leveling.cell(res, cb, "Acme") == ("INCL", "incl")
    assert leveling.cell(res, cb, "Dyer")[1] == "omit"
    assert [g.desc for g in res["gaps"]] == ["Catch basin, precast"]
    out = leveling.export_xlsx(res, str(tmp_path / "lev.xlsx"))
    assert os.path.getsize(out) > 1000
    with pytest.raises(ValueError):
        leveling.run({"Only": []})


def test_level_command_line(tmp_path, monkeypatch, capsys):
    monkeypatch.syspath_prepend(TOOLS)
    for m in ("bidtab", "vocab", "level"):
        sys.modules.pop(m, None)
    import level
    p = _file(tmp_path)
    assert level.main([p, "--bidder-column", "--matrix",
                       str(tmp_path / "m.csv"), "--gaps",
                       str(tmp_path / "g.csv")]) == 0
    out = capsys.readouterr().out
    assert "AWARD RISK: 'Dyer'" in out
    assert "INCL" in (tmp_path / "m.csv").read_text()


def test_routed_import_auto_review_new(tmp_path):
    vocab.add_item("Concrete sidewalk, 4 in", "SF", "03 Concrete")
    vocab.add_item("Catch basin, precast", "EA", "33 Utilities")
    vocab.add_item("Storm sewer, RCP 18 in", "LF", "33 Utilities")
    vocab.add_item("Storm sewer, RCP 18 in", "EA", "33 Utilities")
    q = tmp_path / "b.csv"
    q.write_text('Description,Unit,Qty,Unit Price\n'
                 '"Conc. sidewalk 4 in.",SF,50,8.40\n'          # auto
                 '"6 in conc sidewalk",SF,100,9.90\n'           # new (size)
                 '"Precast catch basin",EA,4,3300\n'            # auto
                 '"Concrete sidewalk 4 in",CY,10,500\n'         # unit -> review
                 '"Hydro seeding",SF,9000,0.25\n'
                 '"Hydro seeding",SF,9000,0.26\n'
                 '"Hydro seeding",SF,9000,0.27\n', encoding="utf-8")
    res = bidtab.import_and_route([str(q)], "Rt 9", state="NC",
                                  bid_date="2026-08", bidder="X",
                                  create_new_min=3)
    assert res["rows"] == 7
    assert res["auto"] == 2 and res["review"] == 1
    assert res["new"] == 4 and res["created"] == 1          # hydro seeding
    queue = vocab.review_queue()
    assert len(queue) == 1 and "unit CY vs SF" in queue[0]["reason"]
    assert vocab.decide(queue[0]["id"], False)
    assert vocab.review_queue() == []
    assert vocab.rejected()
    names = {i["canonical"] for i in vocab.items()}
    assert "Hydro seeding" in names
    # auto lines became aliases: they match exactly from now on
    m = vocab.matcher()
    assert m.match("Precast catch basin", "EA")["method"] in ("exact", "alias")


def test_import_cost_command_line(tmp_path, monkeypatch, capsys):
    monkeypatch.syspath_prepend(TOOLS)
    for m in ("bidtab", "vocab", "costdb", "import_cost"):
        sys.modules.pop(m, None)
    import costdb
    import import_cost
    db = str(tmp_path / "cost.db")
    costdb.main(["--db", db, "init"])
    costdb.main(["--db", db, "seed"])
    costdb.main(["--db", db, "add-item", "--canonical",
                 "Concrete sidewalk, 4 in", "--unit", "SF", "--trade",
                 "03 Concrete"])
    q = tmp_path / "b.csv"
    q.write_text('Description,Unit,Qty,Unit Price\n'
                 '"Conc sidewalk 4 in",SF,50,8.40\n'
                 '"6 in conc sidewalk",SF,100,9.90\n', encoding="utf-8")
    args = [str(q), "--db", db, "--source", "T1", "--create-source",
            "--commit"]
    assert import_cost.main(args) == 0
    out = capsys.readouterr().out
    assert "auto        1" in out and "new         1" in out
    # running the same commit again is refused instead of doubling prices
    assert import_cost.main(args) == 1
    assert import_cost.main(args + ["--replace-source"]) == 0


def test_leveling_window(qapp, win, tmp_path):
    from app.leveling_ui import LevelingDialog
    pid, n, b = bidtab.import_files([_file(tmp_path)], "Job", state="SC",
                                    bid_date="2026-09")
    dlg = win.bid_leveling(pid)
    assert isinstance(dlg, LevelingDialog)
    res = dlg.run()
    assert res and dlg.summary.rowCount() == 4
    assert "AWARD RISK" in dlg.risk.text()
    assert dlg.matrix.rowCount() == 6 and dlg.gaps.rowCount() == 1
    assert dlg.export(str(tmp_path / "x.xlsx"))
    f = LevelingDialog(win)
    assert f.use_files([_file(tmp_path)], True)
