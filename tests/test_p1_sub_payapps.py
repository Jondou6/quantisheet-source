"""P1 'sub pay apps feeding the owner app': 8 subs bill their SOV
progress, the GC reviews, and the approved totals roll into owner pay
app 4 by cost code (made-up subs and amounts)."""
import pytest

from app import settings
from app.collab import hub as hubmod
from app.pm import actions, cost, schema, subpay
from app.pm.store import ProjectStore

CODES = ["03 30 00", "04 20 00", "05 12 00", "06 10 00", "07 50 00",
         "08 11 00", "09 29 00", "26 05 00"]


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", {"author": "Test PM"})
    s = ProjectStore(str(tmp_path / "job"))
    for i, code in enumerate(CODES, 1):
        s.save_record("contract", {"item": str(i), "cost_code": code,
                                   "description": f"Example scope {i}",
                                   "scheduled": 100000.0})
        s.save_record("commitment", {
            "title": f"Example Sub {i}", "vendor": f"Example Sub {i}",
            "type": "Subcontract", "status": "Executed", "retainage": 10,
            "lines": [{"cost_code": code, "description": "Example work",
                       "amount": 80000.0}]})
    # owner apps 1-3, certified
    for m in ("2026-07-31", "2026-08-31", "2026-09-30"):
        pa = s.save_record("payapp", {"period_to": m, "status": "Draft"})
        pa["lines"] = cost.fill_payapp(s, pa)
        pa["status"] = "Certified"
        s.save_record("payapp", pa)
    return s


def _sub_app(s, i, period, work, stored=0.0, status="Submitted"):
    c = next(c for c in s.list("commitment")
             if c["title"] == f"Example Sub {i}")
    r = s.save_record("subpay", {"commitment": c["_id"],
                                 "period_to": period, "status": "Draft"})
    r["lines"] = subpay.fill(s, r)
    r["lines"][0]["this_period"] = work
    r["lines"][0]["stored"] = stored
    r["status"] = status
    return s.save_record("subpay", r)


def test_tool_is_in_the_schema_and_money_history():
    assert "subpay" in schema.TOOLS
    from app.pm import store as st
    assert "subpay" in st.MONEY


def test_eight_subs_roll_into_owner_app_4(store):
    s = store
    apps = [_sub_app(s, i, "2026-10-31", 1000.0 * i,
                     stored=500.0 if i == 2 else 0.0) for i in range(1, 9)]
    ctx = actions.Ctx(s, ask_text=lambda t, d="": "Example: wrong %")
    for r in apps[:7]:
        actions.run(ctx, "subpay", r, "Approve")
    actions.run(ctx, "subpay", apps[7], "Send Back")
    assert s.get("subpay", apps[7]["_id"])["status"] == "Rejected"
    pa4 = s.save_record("payapp", {"period_to": "2026-10-31",
                                   "status": "Draft"})
    assert cost.app_no(s, pa4) == 4
    r = subpay.roll_up(s, pa4)
    assert len(r["subs"]) == 7
    assert r["work"] == sum(1000.0 * i for i in range(1, 8))
    assert r["stored"] == 500.0
    pa4 = actions.run(ctx, "payapp", pa4, "Roll In Sub Pay Apps")
    pa4 = s.get("payapp", pa4["_id"])
    by_item = {l["item"]: l for l in pa4["lines"]}
    assert by_item["3"]["this_period"] == 3000.0
    assert by_item["2"]["stored"] == 500.0
    assert not by_item["8"].get("this_period")         # rejected sub
    total = sum(cost._f(l.get("this_period")) + cost._f(l.get("stored"))
                for l in pa4["lines"])
    assert total == r["work"] + r["stored"]
    vals = cost.payapp_values(s, pa4)                  # prints as app 4
    assert vals["g702"]
    # the same sub billing never goes to the owner twice
    assert all(s.get("subpay", a["_id"])["status"] == "Billed"
               for a in apps[:7])
    with pytest.raises(subpay.SubPayError):
        subpay.feed_owner(s, s.save_record(
            "payapp", {"period_to": "2026-10-31", "status": "Draft"}))


def test_previous_and_overbilling_and_typed_lines(store):
    s = store
    a = _sub_app(s, 1, "2026-09-30", 70000.0, status="Approved")
    b = _sub_app(s, 1, "2026-10-31", 20000.0)
    assert b["lines"][0]["previous"] == 70000.0
    assert subpay.problems(b)                          # 90k of 80k
    with pytest.raises(subpay.SubPayError):
        subpay.review(s, b["_id"], True)
    assert subpay.review(s, b["_id"], True,
                         note="Example: approved CO pending")["status"] \
        == "Approved"
    pa4 = s.save_record("payapp", {"period_to": "2026-10-31",
                                   "status": "Draft"})
    pa4["lines"] = cost.fill_payapp(s, pa4)
    pa4["lines"][0]["this_period"] = 5.0               # PM typed it
    rep = subpay.feed_owner(s, pa4)
    assert rep["kept"] == ["1"] and rep["fed"] == []
    assert a["_id"] not in rep["subs"]                 # earlier period


def test_unmatched_code_stops_the_roll_in(store):
    s = store
    c = s.save_record("commitment", {
        "title": "Example Sub 9", "vendor": "Example Sub 9",
        "status": "Executed", "lines": [{"cost_code": "31 23 00",
                                         "amount": 5000.0}]})
    r = s.save_record("subpay", {"commitment": c["_id"],
                                 "period_to": "2026-10-31"})
    r["lines"] = subpay.fill(s, r)
    r["lines"][0]["this_period"] = 1000.0
    r["status"] = "Approved"
    s.save_record("subpay", r)
    pa4 = s.save_record("payapp", {"period_to": "2026-10-31",
                                   "status": "Draft"})
    with pytest.raises(subpay.SubPayError) as e:
        subpay.feed_owner(s, pa4)
    assert "31 23 00" in str(e.value)
    assert s.get("subpay", r["_id"])["status"] == "Approved"
    with pytest.raises(subpay.SubPayError):          # not a draft
        subpay.feed_owner(s, s.list("payapp")[0])


PW = "example pass 42"


def test_hub_sub_submits_only_gc_reviews(tmp_path):
    hubmod._FAILS.clear()
    hubmod._LOCKED.clear()
    H = hubmod.Hub(str(tmp_path / "hub"))
    key = H.call("proj.open", {"project": "Example Job", "password": PW,
                               "user": "Example GC"}, {}, True)["key"]
    admin = H.call("user.add", {"project": "Example Job", "key": key,
                                "email": "gc@example.com", "role": "admin",
                                "name": "Example GC", "password": PW},
                   {}, True)["key"]
    keys = {}
    for role in ("sub", "accountant", "super"):
        H.call("user.add", {"project": "Example Job", "key": admin,
                            "email": f"{role}@example.com", "role": role,
                            "name": f"Example {role}", "password": PW},
               {}, True)
        keys[role] = H.call("proj.open", {
            "project": "Example Job", "email": f"{role}@example.com",
            "password": PW}, {}, True)["key"]

    def put(k, rec):
        return H.call("rec.put", {"project": "Example Job", "key": k,
                                  "coll": "subpay", "record": rec}, {},
                      True)
    got = put(keys["sub"], {"period_to": "2026-10-31",
                            "status": "Submitted"})
    assert not got.get("denied")
    rid = got["record"]["_id"]
    no = put(keys["sub"], {"_id": rid, "status": "Approved"})
    assert "Only the PM or accountant" in no["denied"]
    assert put(keys["super"], {"_id": rid, "status": "Approved"})["denied"]
    assert "Superintendents can't" in put(keys["super"], {
        "period_to": "2026-10-31"})["denied"]
    assert not put(keys["accountant"], {"_id": rid,
                                        "status": "Approved"}).get("denied")
    assert "Only the PM or accountant" in put(keys["sub"], {
        "_id": rid, "review_note": "x"})["denied"]
    hubmod._FAILS.clear()
    hubmod._LOCKED.clear()
