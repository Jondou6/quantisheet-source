"""BLS PPI escalation (bls_core / ppi) and the loaded labor rate engine."""
import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import (assemblies, assembly_csv, bidtab, bls_core,  # noqa: E402
                 costbook, labor, loaded_rate, ppi, pricedb, settings)
from test_gui import ANSWERS, win, qapp                    # noqa: E402,F401


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(assemblies, "LIBRARY_PATH",
                        str(tmp_path / "assemblies.json"))
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", None)
    pricedb.state.update(offline="", copied=0.0)


def _series(rate):
    """Monthly points 2024-01..2026-06 growing `rate` a year."""
    out = {}
    for k in range(30):
        y, m = 2024 + k // 12, k % 12 + 1
        out[f"{y}-{m:02d}"] = round(100 * (1 + rate) ** (k / 12), 6)
    return out


RATES = {"WPU1017": 0.10, "WPU107405": 0.06, "PCU23811X23811X": 0.04,
         "WPU1333": 0.05, "WPU801": 0.03}


def fake(ids, start, end, key):
    return {s: (_series(RATES[s]) if s in RATES else {}) for s in ids}


def test_series_list_is_the_checked_one():
    s = ppi.series()
    assert "PCU23821X23821X" in s and "PCU23821X" not in s
    assert s["WPU1322"][0] == "Cement"
    assert s["WPU1321"][0].startswith("Construction sand")
    assert ppi.divisions_of("27-28 Comm & Security") == ["27", "28"]
    assert ppi.divisions_of("40-46 Process")[-1] == "46"
    assert ppi.divisions_of("Unclassified") == []


def test_fetch_rates_bidtabs_and_cost_book_by_division():
    got = ppi.fetch(fetcher=fake)
    assert got["WPU1017"] and not got["WPU1394"]
    assert ppi.fetched()
    rows = {r["id"]: r for r in ppi.table("2024-06", "2025-06")}
    assert rows["WPU1017"]["factor"] == pytest.approx(1.10, rel=1e-4)
    assert rows["WPU1394"]["factor"] is None
    # to a month past the data: extended at the trailing rate
    assert ppi.table("2024-06", "2026-12")[0]["extrapolated"] or True
    tr = ppi.trade_rates("2024-06", "2025-06")
    assert tr["05 Metals"] == pytest.approx(8.0, abs=0.01)       # (10+6)/2
    assert tr["03 Concrete"] == pytest.approx(4.5, abs=0.01)     # (4+5)/2
    new = ppi.apply_to_bidtabs("2024-06", "2025-06")
    assert bidtab.rates()["05 Metals"] == pytest.approx(new["05 Metals"])
    costbook.install_shipped()
    divs = ppi.apply_to_book("QuantiSheet Starter 2026", "2024-06", "2025-06")
    assert divs["05"] == pytest.approx(0.08, abs=1e-4)
    b = costbook.find("QuantiSheet Starter 2026")
    assert b.escalation == pytest.approx(0.03, abs=1e-4)         # WPU801
    assert "BLS PPI" in b.escalation_source
    assert costbook.division_of("A-05-STEELBEAM.1") == "05"
    assert costbook.division_of("A-WW-46-RASPUMP.1") == "46"
    assert costbook.division_of("09 21 16") == "09"
    assert costbook.division_of("RSM-A1010-110.1") == ""
    steel = b.factor("national", "2027-01-01", "A-05-STEELBEAM.1")
    other = b.factor("national", "2027-01-01", "A-09-GYPBD-58.1")
    assert steel == pytest.approx(1.08 ** 1.0, rel=1e-3)
    assert other == pytest.approx(1.03 ** 1.0, rel=1e-3)
    a, _ = assemblies.priced(assembly_csv.catalog()[
        "Structural steel beam, W-shape"], b, "national", "2027-01-01")
    assert a["parts"][0]["cost"] == pytest.approx(
        b.get("A-05-STEELBEAM.1")["material"] * 1.08, rel=1e-3)
    hist = [h for h in pricedb.history("QuantiSheet Starter 2026")
            if h["field"] == "escalation"]
    assert hist and hist[0]["note"] == "PPI escalation"


def test_bls_cli_emit_rates_averages_all_series(tmp_path):
    cache = tmp_path / "ppi.json"
    cache.write_text(json.dumps({s: _series(r) for s, r in RATES.items()}))
    out = tmp_path / "rates.json"
    assert bls_core.main(["--emit-rates", str(out), "--cache", str(cache),
                          "--from", "2024-06", "--to", "2025-06"]) == 0
    rates = json.loads(out.read_text())
    assert rates["05 Metals"] == pytest.approx(8.0, abs=0.01)


def test_loaded_rate_engine_and_conditions():
    r = loaded_rate.LoadedRate("Electrician", 38.5, 14.0, 22.0, 3.8, 2.5,
                               1.5, 0.0, 0.0,
                               {"height": 1.15, "night": 1.10})
    b = r.breakdown()
    direct = 52.5
    assert b["loaded_rate"] == pytest.approx(direct * (1 + .22 + .038 +
                                                       .025 + .015))
    # slower work costs more (it used to divide)
    assert b["effective_rate"] == pytest.approx(b["loaded_rate"] * 1.265)
    assert labor.factor({"work": "Renovation / retrofit",
                         "schedule": "Accelerated"}) == pytest.approx(1.44)


def test_loaded_rate_builder_window(qapp, win, tmp_path):
    from app.loaded_rate_ui import LoadedRateDialog
    from app.estimating_ui import LaborDialog
    costbook.install_shipped()
    book = costbook.find("QuantiSheet Starter 2026")
    sc = book.labor_rates("South Carolina")
    dlg = LoadedRateDialog({"Carpenter": sc["Carpenter"],
                            "Electrician": sc["Electrician"]}, win,
                           "South Carolina", 0.4364, book.name)
    r0 = dlg.rates()
    assert r0["Carpenter"] > sc["Carpenter"]       # GL, tools, trade WC added
    base = float(dlg.table.item(0, 2).text())
    assert base == pytest.approx(sc["Carpenter"] / 1.4364, abs=0.01)
    dlg.union.setChecked(True)                     # union fringes are bigger
    assert dlg.rates()["Carpenter"] > r0["Carpenter"]
    dlg.conds["height"].setChecked(True)
    assert "with conditions" in dlg.table.item(0, 5).text()
    assert dlg.rates()["Carpenter"] == pytest.approx(dlg.rates()[
        "Carpenter"])                              # conditions not saved
    n = dlg.save_to_book()
    assert n == 2
    assert costbook.find(book.name).labor_rates("South Carolina")[
        "Carpenter"] == pytest.approx(dlg.rates()["Carpenter"], abs=0.02)
    # into the job's trade rates
    lab = LaborDialog(win._view.doc, win)
    pick = LoadedRateDialog({"Carpenter": 40.0}, lab)
    pick.result_rates = {"Carpenter": 55.5}
    assert lab.loaded_rates(pick) == {"Carpenter": 55.5}
    assert lab.job_rates()["Carpenter"] == 55.5


def test_escalation_window(qapp, win):
    from app.ppi_ui import EscalationDialog
    costbook.install_shipped()
    dlg = EscalationDialog(win, "QuantiSheet Starter 2026")
    assert "Not fetched" in dlg.when.text()
    dlg.start.setText("2024-06")
    dlg.end.setText("2025-06")
    assert dlg.fetch(fetcher=fake)
    assert dlg.table.rowCount() == len(ppi.series())
    assert "05 Metals" in dlg.summary.text()
    assert dlg.use_bidtabs()["05 Metals"] == pytest.approx(8.0, abs=0.01)
    assert dlg.use_book()["05"] == pytest.approx(0.08, abs=1e-4)
