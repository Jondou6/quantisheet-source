"""Bid build-up (your estimate.py): markup cascade, trade margins, bond,
front-loading, and the proposal / SOV / CLI that use it."""
import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import assemblies, bidbuild, money, proposal       # noqa: E402
from test_gui import win, qapp                              # noqa: E402,F401
from test_planswift import _job                             # noqa: E402
from test_proposal import COMP                              # noqa: E402

TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(
    __file__))), "tools")
LINES = [{"trade": "03 Concrete", "direct": 600000, "material": 300000},
         {"trade": "26 Electrical", "direct": 400000, "material": 100000}]


@pytest.fixture(autouse=True)
def _own_settings(tmp_path, monkeypatch):
    from app import settings
    monkeypatch.setattr(assemblies, "LIBRARY_PATH",
                        str(tmp_path / "assemblies.json"))
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", None)


def test_cascade_order_and_trade_margin_once():
    b = bidbuild.build(LINES, dict(gc=8, tax=6, overhead=5, profit=8,
                                   insurance=2, contingency=5, bond="auto",
                                   margins="03=14"))
    assert [s["key"] for s in b["steps"]] == [
        "gc", "tax", "overhead", "profit", "margins", "insurance",
        "contingency", "bond"]
    # the concrete margin is 14% of concrete's subtotal after profit - once
    conc = (600000 + 48000 + 18000) * 1.05 * 1.08
    assert b["steps"][4]["amount"] == pytest.approx(conc * 0.14)
    assert round(sum(ln["price"] for ln in b["lines"]), 2) == b["total"]
    t = {x["trade"]: x for x in b["by_trade"]}
    assert t["03 Concrete"]["direct"] == 600000            # direct stays direct
    assert t["03 Concrete"]["margin_pct"] > t["26 Electrical"]["margin_pct"]
    # the bond is on the final contract, premium included
    bond = b["steps"][-1]
    assert bond["amount"] == pytest.approx(
        bidbuild.bond_premium(b["total"]), abs=0.01)


def test_bond_schedule_is_graduated():
    assert bidbuild.bond_premium(1_000_000) == pytest.approx(15000)
    assert bidbuild.bond_premium(2_000_000) == pytest.approx(27500)
    # no cliff: a bigger contract never has a smaller bond
    assert bidbuild.bond_premium(1_000_001) > bidbuild.bond_premium(999_999)
    flat = bidbuild.build(LINES, dict(bond="fixed", bond_rate=1.0))
    assert flat["steps"][-1]["amount"] == pytest.approx(flat["total"] * 0.01,
                                                       abs=0.01)


def test_front_load_keeps_total_and_gains_cash():
    vals = [300000.0, 500000.0, 200000.0, 400000.0]
    fl = bidbuild.front_load(vals, 0.06, 14, 7)
    assert sum(fl["values"]) == pytest.approx(sum(vals), abs=0.001)
    assert fl["values"][0] > vals[0] and fl["values"][-1] < vals[-1]
    assert fl["improvement"] > 0
    assert bidbuild.front_load([1000.0], 0.06)["improvement"] == \
        pytest.approx(0)
    with pytest.raises(ValueError):
        bidbuild.front_load(vals, 0.6)
    with pytest.raises(ValueError):
        bidbuild.parse_margins("03 Concrete 14")


def test_proposal_old_markups_unchanged_new_ones_add_up():
    d = _job()
    rows, totals, _ = assemblies.rollup(d)
    data = dict(proposal.defaults(d), tax=7, overhead=10, profit=10)
    p = proposal.price(d, data)
    assert p["total"] == pytest.approx(
        (totals["material"] * 1.07 + totals["labor_cost"]) * 1.21, abs=0.01)
    more = dict(data, gc=6, insurance=2, contingency=3, bond="auto",
                margins={rows[0]["trade"] or "General": 5}, detail="parts")
    q = proposal.price(d, more)
    assert q["total"] > p["total"]
    assert round(sum(ln["price"] for ln in q["lines"]), 2) == q["total"]
    assert q["extras"] > 0
    proposal.write(d, dict(more, detail="trade", sov_front_load=True,
                           front_load=0.08, months=10))
    flat = money.from_estimate(d, "trade")
    loaded = money.from_estimate(d, "trade", 0.08, 10)
    assert sum(l["scheduled"] for l in loaded) == pytest.approx(
        sum(l["scheduled"] for l in flat), abs=0.01)
    text = "".join(pg.get_text() for pg in proposal.make_pdf(
        d, dict(more, show_breakdown=True), COMP))
    assert "General conditions" in text and "Bond" in text


def test_estimate_command_line(tmp_path, monkeypatch, capsys):
    monkeypatch.syspath_prepend(TOOLS)
    for m in ("vocab", "costdb", "estimate"):
        sys.modules.pop(m, None)
    import costdb
    import estimate
    db = str(tmp_path / "cost.db")
    costdb.main(["--db", db, "init"])
    costdb.main(["--db", db, "seed"])
    costdb.main(["--db", db, "add-item", "--canonical",
                 "Concrete sidewalk, 4 in", "--unit", "SF", "--trade",
                 "03 Concrete"])
    costdb.main(["--db", db, "add-source", "--name", "S1", "--kind",
                 "bid_tab"])
    costdb.main(["--db", db, "add-price", "--item", "1", "--value", "7.40",
                 "--source", "1", "--date", "2026-03"])
    t = tmp_path / "t.csv"
    # unit_cost before unit: the unit column must still be "unit"
    t.write_text("unit_cost,description,qty,unit,cost_type,trade\n"
                 ',"4 in conc sidewalk",2000,SF,Material,\n'
                 ',"Concrete sidewalk 4 in",10,CY,,\n'
                 "42000,Panelboards,1,LS,Material,26 Electrical\n",
                 encoding="utf-8")
    sov = tmp_path / "sov.csv"
    assert estimate.main(["--takeoff", str(t), "--db", db, "--margin",
                          "03=14", "--tax", "6", "--front-load", "0.06",
                          "--out", str(tmp_path / "bid.csv"), "--sov",
                          str(sov), "--sov-front-loaded"]) == 0
    io = capsys.readouterr()
    assert "1 lines had no price" in io.err        # the CY line, not priced
    bid = (tmp_path / "bid.csv").read_text()
    assert "7.40" in bid and ",SF," in bid
    rows = sov.read_text().strip().splitlines()
    total = float(rows[-1].split(",")[2])
    assert sum(float(r.split(",")[2]) for r in rows[1:-1]) == \
        pytest.approx(total, abs=0.001)
    assert estimate.main(["--direct", "2500000", "--gc", "9", "--profit",
                          "8"]) == 0


def test_bid_buildup_window(qapp, win):
    from app.bidbuild_ui import BidBuildDialog
    from app.proposal_ui import ProposalDialog
    d = _job()
    dlg = BidBuildDialog(d, win, proposal.defaults(d))
    dlg.rate["gc"].setValue(6)
    dlg.bond.setCurrentIndex(1)
    dlg.margins.setText("General=5")
    p = dlg.refresh()
    assert p and dlg.steps.rowCount() == len(p["steps"]) + 2
    assert dlg.trades.rowCount() >= 1
    dlg.margins.setText("bad")
    dlg.refresh()                                   # no crash, field shows red
    assert "ffd6d6" in dlg.margins.styleSheet()
    dlg.margins.setText("")
    pd = ProposalDialog(d, win)
    before = proposal.price(d, pd.values())["total"]
    pd.build_up(dlg)
    assert proposal.price(d, pd.values())["total"] > before
    assert "general conditions" in pd.summary.text()
    assert isinstance(win.bid_buildup(show=False), BidBuildDialog)
    empty = BidBuildDialog(None, win, {})
    assert empty.refresh() is None
    empty.direct.setValue(1_000_000)
    assert empty.refresh()["total"] > 1_000_000
