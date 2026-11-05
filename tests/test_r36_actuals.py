"""r36 B3: estimate history - record what each estimate line really took
(quantity and cost), compare estimate vs actual, and keep your own
history file of unit costs that Estimate Error Check uses for outliers.
Made-up data only."""
import os
from decimal import Decimal

import fitz
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import assemblies, estimate_lines as EL, settings   # noqa: E402
from app.estimating import actuals, checks                    # noqa: E402
from estimate_helpers import blank_doc                        # noqa: E402

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
    ids = EL.add(d, [EL.new_line("Test footing", 10, "cy", mat=150,
                                 code="03 30 00"),
                     EL.new_line("Test drywall", 1000, "sf", mat="2.00",
                                 code="09 29 00")])
    return d, ids


def test_record_and_compare(tmp_path):
    d, ids = _doc()
    actuals.record(d, ids[0], qty="12", cost="2100")
    rows = {r["desc"]: r for r in actuals.compare(d)["rows"]}
    f = rows["Test footing"]
    assert f["est_cost"] == D("1500.00") and f["act_cost"] == D("2100.00")
    assert f["cost_var"] == D("600.00") and f["cost_var_pct"] == D("40.0")
    assert f["qty_var"] == D("2") and f["act_unit"] == D("175.00")
    assert rows["Test drywall"]["act_cost"] is None
    t = actuals.compare(d)["totals"]
    assert t["est_cost"] == D("3500.00") and t["act_cost"] == D("2100.00")
    assert t["lines_with_actuals"] == 1
    p = str(tmp_path / "j.pdf")
    d.save(p)
    assert actuals.read(fitz.open(p))[ids[0]]["cost"] == "2100.00"


def test_bad_values_and_unknown_line_refused():
    d, ids = _doc()
    with pytest.raises(actuals.ActualsError):
        actuals.record(d, ids[0], cost="lots")
    with pytest.raises(actuals.ActualsError):
        actuals.record(d, "nope", cost="1")


def test_history_file_feeds_the_outlier_check(tmp_path):
    hist = str(tmp_path / "my_history.json")
    for job, cost in (("Job 1", "2000"), ("Job 2", "2200")):
        d, ids = _doc()
        actuals.record(d, ids[1], qty="1000", cost=cost)
        actuals.archive(d, hist, job)
    h = actuals.load_history(hist)
    assert h[("09 29 00", "sf")] == [D("2.00"), D("2.20")]
    d, ids = _doc()
    EL.update(d, ids[1], mat="5.00")
    found = [f for f in checks.run(d, history=h) if f["rule"] == "outlier"]
    assert [f["item"] for f in found] == ["Test drywall"]
    # the same job archived twice replaces its own rows
    d, ids = _doc()
    actuals.record(d, ids[1], qty="1000", cost="9999")
    actuals.archive(d, hist, "Job 1")
    assert sorted(actuals.load_history(hist)[("09 29 00", "sf")]) == \
        [D("2.20"), D("10.00")]


def test_export(tmp_path):
    d, ids = _doc()
    actuals.record(d, ids[0], cost="1400")
    p = actuals.export(actuals.compare(d), str(tmp_path / "eva.csv"))
    assert "Estimate cost" in open(p, encoding="utf-8").read()
