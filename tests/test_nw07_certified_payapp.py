"""PM review NW-07 (Must): a certified owner pay app is final. Editing it
is refused, and later applications keep the numbers they were certified
with (made-up job)."""
import pytest

from app import settings
from app.pm import cost
from app.pm.store import ProjectStore, StoreError


@pytest.fixture
def s(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", {"author": "Test PM"})
    st = ProjectStore(str(tmp_path / "job"))
    for i, (d, amt) in enumerate((("Sitework", 1_000_000),
                                  ("Concrete", 2_000_000),
                                  ("Steel", 1_500_000)), 1):
        st.save_record("contract", {"item": str(i), "description": d,
                                    "scheduled": amt})
    return st


def _app(st, period, work):
    a = st.save_record("payapp", {"period_to": period, "retainage_work": 10,
                                  "retainage_stored": 10})
    a["lines"] = cost.fill_payapp(st, a)
    for ln in a["lines"]:
        ln["this_period"] = work.get(ln["item"], 0)
    a = st.save_record("payapp", a)
    a["status"] = "Certified"
    return st.save_record("payapp", a)


def _certify_three(st):
    a1 = _app(st, "2026-11-30", {"1": 100_000, "2": 50_000})
    a2 = _app(st, "2026-12-31", {"1": 150_000, "2": 100_000})
    a3 = _app(st, "2027-01-31", {"2": 200_000, "3": 75_000})
    return a1, a2, a3


def test_certified_app_cant_be_edited(s):
    a1, _a2, a3 = _certify_three(s)
    before = cost.payapp_values(s, a3)["g702"]
    assert a1.get("certified_values")
    edit = dict(a1, lines=[dict(ln) for ln in a1["lines"]])
    edit["lines"][1]["this_period"] = 999_999
    with pytest.raises(StoreError) as ei:
        s.save_record("payapp", edit)
    assert "Certified" in str(ei.value) and "next application" in \
        str(ei.value)
    with pytest.raises(StoreError):
        s.save_record("payapp", dict(a1, status="Draft"))
    with pytest.raises(StoreError):
        s.delete("payapp", a1["_id"])
    s.flush()
    again = ProjectStore(s.folder)            # save / reopen
    after = cost.payapp_values(again, again.get("payapp", a3["_id"]))
    assert after["g702"]["4"] == before["4"] == 675_000
    assert after["g702"]["7"] == before["7"]


def test_certified_numbers_kept_even_if_older_data_changes(s):
    """Belt and braces: a certified app prints the numbers it was
    certified with, whatever the earlier records say later."""
    a1, _a2, a3 = _certify_three(s)
    want = cost.payapp_values(s, a3)["g702"]
    # simulate an old file edited outside the lock
    raw = s.coll("payapp")[a1["_id"]]
    raw["lines"][1]["this_period"] = 999_999
    got = cost.payapp_values(s, a3)["g702"]
    assert got["4"] == want["4"] and got["7"] == want["7"]


def test_payment_fields_stay_open(s):
    a1, _a2, _a3 = _certify_three(s)
    paid = s.save_record("payapp", dict(a1, status="Paid", received=135_000,
                                        received_on="2026-12-20",
                                        notes="Check 1001"))
    assert paid["status"] == "Paid" and paid["received"] == 135_000


def test_certified_snapshot_is_write_once(s):
    """Chief review Q1: the frozen numbers, date and certifier of a
    Certified / Paid app can't be overwritten by a later save."""
    a1, _a2, _a3 = _certify_three(s)
    snap = a1["certified_values"]
    assert snap and a1["certified"] and a1["certified_by"]
    for k, v in (("certified_values", {"g702": {"4": 1}}),
                 ("certified", "2020-01-01T00:00:00+00:00"),
                 ("certified_by", "someone-else")):
        with pytest.raises(StoreError):
            s.save_record("payapp", dict(a1, **{k: v}))
    paid = s.save_record("payapp", dict(a1, status="Paid",
                                        received_on="2026-12-15"))
    assert paid["certified_values"] == snap          # kept through Paid
    with pytest.raises(StoreError):
        s.save_record("payapp", dict(paid, certified_values={}))


def test_app_certified_before_the_snapshot_gets_one_once(s):
    """An app certified before 0.13.14 has no snapshot: its next save
    adds one, and from then on it is fixed."""
    a1, _a2, _a3 = _certify_three(s)
    raw = s.coll("payapp")[a1["_id"]]
    for k in ("certified_values", "certified", "certified_by"):
        raw.pop(k, None)                   # as an older version saved it
    got = s.save_record("payapp", dict(raw, notes="paid by check"))
    assert got["certified_values"]
    with pytest.raises(StoreError):
        s.save_record("payapp", dict(got, certified_values={"x": 1}))
