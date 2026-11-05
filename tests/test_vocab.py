"""Pay item vocabulary (your vocab.py / costdb.py) and bid tab grouping."""
import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import (assemblies, bidtab, bidtab_core, pricedb,  # noqa: E402
                 settings, vocab, vocab_core)
from test_gui import ANSWERS, win, qapp                    # noqa: E402,F401

TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(
    __file__))), "tools")


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(assemblies, "LIBRARY_PATH",
                        str(tmp_path / "assemblies.json"))
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", None)
    pricedb.state.update(offline="", copied=0.0)


def test_normalize_and_safe_matching():
    n = vocab_core.normalize
    assert n('PROVIDE 4" CONC SIDEWALK W/ REINF, TYP') == \
        "4 concrete sidewalk reinforcing"
    assert n('1 1/2" galv stl pipe') == "1.5 galvanized steel pipe"
    assert n("1-1/2 in pipe") == "1.5 pipe"
    assert n('3/4" plywood') == "0.75 plywood"
    m = vocab_core.Matcher(items=[(1, "Concrete sidewalk, 4 in", "SF"),
                                  (2, "Concrete, 4000 psi", "CY")],
                           aliases=[(1, n("conc walk 4 inch thick"))])
    assert m.match('4" conc sidewalk', "SF")["item_id"] == 1
    # a different size or unit never matches, however alike the words
    assert m.match("6 in conc sidewalk", "SF")["item_id"] is None
    assert m.match("conc sidewalk 4 in", "CY")["item_id"] is None
    assert m.match("conc walk 4 inch thick", "SF")["method"] == "alias"


def test_costdb_and_vocab_command_line(tmp_path, monkeypatch, capsys):
    monkeypatch.syspath_prepend(TOOLS)
    sys.modules.pop("vocab", None)
    import costdb
    import vocab as cli
    db = str(tmp_path / "cost.db")
    assert costdb.main(["--db", db, "init"]) == 0
    assert costdb.main(["--db", db, "seed"]) == 0
    assert costdb.main(["--db", db, "add-item", "--canonical",
                        "Concrete sidewalk, 4 in", "--unit", "SF", "--trade",
                        "03 Concrete", "--alias",
                        "4 in conc sidewalk|conc sidewalk 4in"]) == 0
    items = tmp_path / "items.txt"
    items.write_text('4" conc sidewalk SF\n6 in conc sidewalk SF\n'
                     'conc sidewalk 4in\n', encoding="utf-8")
    assert cli.main(["--db", db, "batch", str(items), "--out",
                     str(tmp_path / "m.csv")]) == 0
    out = (tmp_path / "m.csv").read_text()
    assert out.count("Concrete sidewalk, 4 in") == 2      # not the 6 in
    assert cli.main(["--db", db, "learn", str(items), "--min-score",
                     "0.5"]) == 0
    assert cli.main(["--db", db, "learn", str(items), "--min-score",
                     "0.5"]) == 0
    assert "learned 0" in capsys.readouterr().out          # no duplicates


def _tabs(tmp_path):
    p = tmp_path / "a.csv"
    p.write_text(bidtab_core.SAMPLE, encoding="utf-8")
    q = tmp_path / "b.csv"
    q.write_text('Description,Unit,Qty,Unit Price\n'
                 '"PROVIDE 4"" CONC SIDEWALK W/ REINF, TYP",SF,100,8.10\n'
                 '"Conc. sidewalk 4 in.",SF,50,8.40\n'
                 '"6 in conc sidewalk",SF,100,9.90\n', encoding="utf-8")
    bidtab.import_files([str(p)], "A", state="SC", bid_date="2025-06")
    bidtab.import_files([str(q)], "B", state="NC", bid_date="2025-06",
                        bidder="X")


def test_vocabulary_groups_bid_tabs(tmp_path):
    _tabs(tmp_path)
    before = {i["desc"]: i for i in bidtab.analyze(to="2025-06")}
    assert before["Concrete sidewalk, 4 in"]["bids"] == 3
    iid = vocab.add_item("Concrete sidewalk, 4 in", "SF", "03 Concrete")
    rows = {r["input"]: r for r in vocab.review()}
    assert rows["Conc. sidewalk 4 in."]["item_id"] == iid
    assert rows["6 in conc sidewalk"]["item_id"] is None
    loose = 'PROVIDE 4" CONC SIDEWALK W/ REINF, TYP'
    assert rows[loose]["item_id"] is None                  # below 0.82
    assert vocab.add_alias(iid, loose, "mapped")
    assert not vocab.add_alias(iid, loose, "mapped")       # once
    after = {i["desc"]: i for i in bidtab.analyze(to="2025-06")}
    side = after["Concrete sidewalk, 4 in"]
    assert side["bids"] == 5 and side["wordings"] == 3
    assert "6 in conc sidewalk" in after
    plain = {i["desc"]: i for i in bidtab.analyze(to="2025-06",
                                                  use_vocab=False)}
    assert plain["Concrete sidewalk, 4 in"]["bids"] == 3
    assert vocab.suggest()
    n = vocab.seed_from_catalog()
    assert n > 300 and vocab.seed_from_catalog() == 0
    assert vocab.learn(0.99) >= 0


def test_vocabulary_window(qapp, win, tmp_path):
    from app.pricedb_ui import BidTabDialog, VocabDialog
    _tabs(tmp_path)
    dlg = VocabDialog(win)
    assert dlg.review.rowCount() == 13                      # all unmatched
    six = [x for x in dlg.review_rows if x["input"] == "6 in conc sidewalk"]
    made = dlg.add_new(six, "Concrete sidewalk, 6 in")
    assert made and dlg.items.rowCount() == 1
    loose = [x for x in dlg.review_rows if "PROVIDE" in x["input"]]
    four = vocab.add_item("Concrete sidewalk, 4 in", "SF", "03 Concrete")
    dlg.refresh()
    assert dlg.map_to(loose, four) == 1
    assert "matched" in dlg.status.text()
    assert dlg.learn() >= 0
    tabs = BidTabDialog(None, win)
    descs = [tabs.items.item(r, 1).text() for r in
             range(tabs.items.rowCount())]
    assert "Concrete sidewalk, 4 in" in descs and \
        "Concrete sidewalk, 6 in" in descs
    tabs.by_vocab.setChecked(False)
    assert tabs.items.rowCount() > len(descs) - 1
