"""r36 v2 step 2: general fixes found by the real-job test (Aiken and
Colleton plan sets, EXAMPLE costs) - each one a plain rule, nothing
specific to those jobs. Made-up data only.

  1. a bid-day scope list can be made from takeoff groups (no retyping),
     and the scope items remember their group;
  2. Error Check: a takeoff group in a bid-day package that is in the
     estimate is priced (it was flagged "not priced anywhere");
  3. Error Check: a group whose markups are all accounted for in the
     pre-bid checklist (excluded with a reason, RFI, priced) is not
     flagged "not priced anywhere";
  4. one estimate run scans the drawing's takeoff once, not once per
     module and civil activity (Aiken: 13 full scans per refresh)."""
import os
from decimal import Decimal

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import annotate, assemblies, estimate, heavy, prebid, settings  # noqa: E402,E501
from app.estimating import bidday, checks, flow, items                  # noqa: E402
from estimate_helpers import area, blank_doc                            # noqa: E402

D = Decimal
LIB = {"equipment": {}, "labor": {"TL": {"code": "TL", "base": "10",
                                         "fringe": "0"}},
       "crews": {"TC": {"labor": [["TL", 1]], "equipment": []}},
       "settings": {"fuel": 0}}


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(assemblies, "LIBRARY_PATH",
                        str(tmp_path / "assemblies.json"))
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", None)


def _doc():
    d = blank_doc()
    area(d, "Test ceiling A", 10, 10)
    area(d, "Test ceiling B", 10, 20, x0=300)
    area(d, "Test room 101", 5, 5, x0=700)
    return d


def _unpriced(d, job=None):
    return sorted(f["item"] for f in checks.run(d, job=job)
                  if f["rule"] == "unpriced_takeoff")


def test_scope_from_takeoff_groups_keeps_quantities_and_groups():
    d = _doc()
    gs = [g for g in estimate.lines(d) if g["name"].startswith(
        "Test ceiling")]
    scope = bidday.scope_from_takeoff(gs)
    assert [(s["desc"], s["unit"], s["qty"]) for s in scope] == [
        ("Test ceiling A", "sq ft", "100"), ("Test ceiling B", "sq ft",
                                              "200")]
    sheet = bidday.new_sheet("Test ceilings", scope,
                             [{"name": "Test Sub", "prices": {"1": "600",
                                                              "2": "1200"}}])
    assert sheet["scope"][0]["group"] == {"name": "Test ceiling A",
                                          "type": "area", "unit": "sq ft"}


def test_groups_in_an_applied_bid_package_are_priced():
    d = _doc()
    gs = [g for g in estimate.lines(d) if g["name"].startswith(
        "Test ceiling")]
    bidday.save(d, bidday.new_sheet(
        "Test ceilings", bidday.scope_from_takeoff(gs),
        [{"name": "Test Sub", "prices": {"1": "600", "2": "1200"}}]))
    assert _unpriced(d) == ["Test ceiling A", "Test ceiling B",
                            "Test room 101"]          # not used yet
    bidday.apply_quote(d, "Test ceilings")
    assert _unpriced(d) == ["Test room 101"]
    # the same group with its own unit cost too: counted twice
    estimate.set_price(d, "Test ceiling A", "area", "sq ft", unit_cost=3)
    dp = [f for f in checks.run(d) if f["rule"] == "double_priced"]
    assert [f["item"] for f in dp] == ["Test ceiling A"]
    assert "bid-day package" in dp[0]["message"]
    bidday.remove_quote(d, "Test ceilings")
    assert "Test ceiling B" in _unpriced(d)


def test_prebid_accounted_markups_are_not_unpriced():
    d = _doc()
    for a in d[0].annots():
        if (a.info or {}).get("subject", "").endswith("Test room 101"):
            prebid.set_scope(d, a, "excluded", reason="Room outline only")
    assert "Test room 101" not in _unpriced(d)
    assert "Test ceiling A" in _unpriced(d)


def test_one_run_scans_the_takeoff_once(monkeypatch):
    d = _doc()
    job = heavy.blank()
    for g in ("Test ceiling A", "Test ceiling B", "Test room 101"):
        heavy.add_activity(job, f"{g} work", unit="sq ft", crew="TC",
                           rate=100, group=g)
    heavy.write(d, job)
    n = {"scans": 0}
    real = annotate._takeoff_items

    def counted(*a, **k):
        n["scans"] += 1
        return real(*a, **k)
    monkeypatch.setattr(annotate, "_takeoff_items", counted)
    r = flow.run(d, lib=LIB)
    assert n["scans"] <= 2              # with and without cutouts at most
    civ = [i for i in r["estimate"]["items"] if i["kind"] == "civil"]
    assert sum(i["hours"] for i in civ) == D("3.25")   # 325 sf / 100 per hr
    n["scans"] = 0
    items.collect(d, *flow.civil(d, LIB))
    assert n["scans"] <= 2
