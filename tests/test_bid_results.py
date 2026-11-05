"""Nov 3 (#12): bid results (our number, low, gap) and hit rate by job
size and markup. Made-up jobs."""
from decimal import Decimal as D

import pytest

from app import dashboard as db


def _job(key, bid, est=None, low=None, result="Won"):
    return db._new_job(key, name=key, bid=D(bid), est_cost=D(est) if est
                       else None, low_bid=D(low) if low else None,
                       result=result)


def test_bid_results_gap():
    rows = db.bid_results([_job("A", "1100000", low="1000000",
                                result="Lost"),
                           _job("B", "500000", low="500000"),
                           _job("C", "200000")])
    a, b, c = rows
    assert a["gap"] == D("100000") and float(a["gap_pct"]) == pytest.approx(
        10.0)
    assert b["gap"] == 0
    assert c["gap"] is None and c["gap_pct"] is None


def test_hit_rate_by_size_and_markup():
    jobs = [_job("small", "100000", "92000"),
            _job("small2", "200000", "190000", result="Lost"),
            _job("mid", "800000", "700000"),
            _job("big", "6000000", "5000000", result="Lost")]
    rows = {r["label"]: r for r in db.hit_rate(jobs, by="size")}
    assert rows["Under $250K"]["won"] == 1 and rows["Under $250K"]["lost"] \
        == 1
    assert rows["$250K - $1M"]["rate"] is not None
    assert "$5M and up" in rows and "All jobs" in rows
    labels = [r["label"] for r in db.hit_rate(jobs, by="markup",
                                              total=False)]
    # 8.7%, 5.3%, 14.3%, 20% -> bands, in band order
    assert labels == ["5% - 10%", "10% - 15%", "15% and up"]
    assert set(db.HIT_BY) >= {"size", "markup"}
    assert all(k in db.BY_LABEL for k in db.HIT_BY)


def test_low_bid_needs_a_project():
    with pytest.raises(db.DashboardError):
        db.set_low_bid(_job("x", "1"), "100")
