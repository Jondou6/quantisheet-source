"""tools/accuracy_gate.py: what counts as worse (made-up numbers; the real
plan sets never come into the tests)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "tools"))
import accuracy_gate as g                                   # noqa: E402

BASE = {"rooms": {"ok": 2, "n": 3, "rooms": {
    "101": {"sf": 100.0, "err": 1.0, "ok": True},
    "102": {"sf": 90.0, "err": -3.0, "ok": True},
    "103": {"sf": 50.0, "err": 20.0, "ok": False}}},
    "scales": {"x": {"1": ["ok", '1/4" = 1\'-0"'], "2": ["none", None],
                     "3": ["check", '1" = 20\'']}}}


def _copy(d):
    import json
    return json.loads(json.dumps(d))


def test_same_run_is_not_a_regression():
    assert g.compare(BASE, _copy(BASE)) == []


def test_a_room_that_fails_now_or_a_lost_scale_is():
    now = _copy(BASE)
    now["rooms"]["rooms"]["102"] = {"sf": 70.0, "err": -25.0, "ok": False}
    now["scales"]["x"]["3"] = ["none", None]
    now["scales"]["x"]["1"] = ["ok", '1/8" = 1\'-0"']
    bad = g.compare(BASE, now)
    assert len(bad) == 3
    assert any("room 102" in b for b in bad)
    assert any("sheet 3" in b for b in bad) and any("sheet 1" in b
                                                    for b in bad)


def test_getting_better_is_not_a_regression():
    now = _copy(BASE)
    now["rooms"]["rooms"]["103"] = {"sf": 51.0, "err": 2.0, "ok": True}
    now["rooms"]["ok"] = 3
    now["scales"]["x"]["2"] = ["check", '1" = 10\'']
    assert g.compare(BASE, now) == []
    assert g.summary(now) == "rooms 3/3, x scales 3/3"
