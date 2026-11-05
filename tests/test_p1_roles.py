"""P1 'roles and permissions': an accountant can certify an owner pay app;
a superintendent can't edit pay apps (or other money records) but keeps
the field records; every refusal is written to the project's activity
(made-up users)."""
import json
import os

import pytest

from app.collab import hub as hubmod

PW = "example pass 42"


@pytest.fixture
def hub(tmp_path):
    hubmod._FAILS.clear()
    hubmod._LOCKED.clear()
    H = hubmod.Hub(str(tmp_path / "hub"))
    key = H.call("proj.open", {"project": "Example Job", "password": PW,
                               "user": "Example GC"}, {}, True)["key"]
    admin = H.call("user.add", {"project": "Example Job", "key": key,
                                "email": "gc@example.com", "role": "admin",
                                "name": "Example GC", "password": PW},
                   {}, True)["key"]
    keys = {"admin": admin}
    for role in ("accountant", "super"):
        H.call("user.add", {"project": "Example Job", "key": admin,
                            "email": f"{role}@example.com", "role": role,
                            "name": f"Example {role}", "password": PW},
               {}, True)
        keys[role] = H.call("proj.open", {
            "project": "Example Job", "email": f"{role}@example.com",
            "password": PW}, {}, True)["key"]
    yield H, keys, tmp_path
    hubmod._FAILS.clear()
    hubmod._LOCKED.clear()


def _put(H, key, coll, rec):
    return H.call("rec.put", {"project": "Example Job", "key": key,
                              "coll": coll, "record": rec}, {}, True)


def test_accountant_certifies_super_cannot_touch_pay_apps(hub):
    H, keys, tmp = hub
    r = _put(H, keys["admin"], "payapp", {"period_to": "2026-11-30",
                                          "status": "Draft"})
    rec = dict(r["record"])
    got = _put(H, keys["accountant"], "payapp",
               {"_id": rec["_id"], "status": "Certified"})
    assert not got.get("denied")
    no = _put(H, keys["super"], "payapp", {"_id": rec["_id"],
                                           "notes": "x"})
    assert "Superintendents can't" in no["denied"]
    ok = _put(H, keys["super"], "daily", {"date": "2026-11-16",
                                          "work": "Example pour"})
    assert not ok.get("denied")
    acc = _put(H, keys["accountant"], "daily", {"date": "2026-11-17"})
    assert acc.get("denied")


def test_refusals_are_logged(hub):
    H, keys, tmp = hub
    _put(H, keys["super"], "commitment", {"title": "Example sub"})
    rows = []
    for base, _d, files in os.walk(str(tmp / "hub")):
        for f in files:
            if f == "activity.jsonl":
                rows += [json.loads(x) for x in open(os.path.join(base, f),
                                                     encoding="utf-8")]
    denied = [r for r in rows if r["action"] == "denied"]
    assert denied and denied[-1]["role"] == "super"
