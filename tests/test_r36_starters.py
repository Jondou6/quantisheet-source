"""r36 v2 step 4: blank starter templates and EXAMPLE crews.

Starter estimate templates for common trades (commercial building GC,
sitework / civil utilities, residential / insurance repair) and a civil
pay-item list: structure, units, cost types and quantity formulas off
takeoff group placeholders - every price blank (0) and every template
marked as a blank starter. EXAMPLE crews: production rates labelled
EXAMPLE, no wages ($0 with a fill-in prompt). Nothing is installed until
asked; installing never replaces a file or crew you already have."""
import json
import os
import re
from decimal import Decimal

import pytest

from app import estimate_lines as EL, heavy, settings          # noqa: E402
from app.estimating import costlink, starters, templates      # noqa: E402

MONEY = ("mat", "lab", "eqp", "sub")


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", None)
    os.makedirs(settings.DIR, exist_ok=True)


def test_three_trade_starters_validate_with_blank_prices():
    tpls = starters.estimate_templates()
    names = " | ".join(t["name"] for t in tpls).lower()
    for trade in ("commercial building", "sitework", "residential"):
        assert trade in names
    assert len(tpls) == 3
    for t in tpls:
        assert t == templates.validate(t)
        assert "blank prices" in t["name"].lower()
        assert starters.MARK in t["note"]
        assert len(t["items"]) >= 12
        phs = templates.placeholders(t)
        assert len(phs) >= 5
        for it in t["items"]:
            assert all(Decimal(it[k] or 0) == 0 for k in MONEY), it
            assert it["unit"] and it["cost_type"] in EL.COST_TYPES[1:]
            assert "EXAMPLE" in it["note"] or "blank" in it["note"].lower()
            if it["placeholder"]:
                assert it["group_type"] in ("area", "length", "count")
                assert it["formula"] and costlink.check_formula(it["formula"])
                re.compile(it["match"])
        hrs = [it for it in t["items"] if Decimal(it["hours"] or 0)]
        assert hrs and all("EXAMPLE" in it["note"] for it in hrs)


def test_civil_pay_item_starter_has_pipe_and_structure_items():
    t = starters.civil_pay_items()
    assert t == templates.validate(t) and t["kind"] == "bid_items"
    assert starters.MARK in t["note"]
    descs = " | ".join(i["desc"].lower() for i in t["items"])
    for w in ("water", "sanitary", "storm", "manhole", "inlet",
              "mobilization"):
        assert w in descs
    assert all(i["unit"] and Decimal(i["owner_qty"]) == 0
               for i in t["items"])
    assert len({i["no"] for i in t["items"]}) == len(t["items"])


def test_install_writes_once_and_never_replaces_yours():
    paths = starters.install()
    assert len(paths["written"]) == 4 and paths["skipped"] == []
    saved = templates.list_saved()
    assert len(saved) == 4
    mine = paths["written"][0]
    with open(mine, encoding="utf-8") as f:
        data = json.load(f)
    data["items"][0]["mat"] = "12.50"           # you filled in a price
    with open(mine, "w", encoding="utf-8") as f:
        json.dump(data, f)
    again = starters.install()
    assert again["written"] == [] and len(again["skipped"]) == 4
    assert templates.load(mine)["items"][0]["mat"] == "12.50"


def test_example_crews_have_no_wages_and_example_production():
    pack = starters.crew_pack()
    assert pack["labor"] and pack["equipment"] and pack["crews"]
    for lab in pack["labor"]:
        assert all(Decimal(str(lab[k])) == 0 for k in ("base", "fringe"))
        assert "EXAMPLE" in lab["desc"] and "enter your" in lab["desc"]
    for e in pack["equipment"]:
        assert all(Decimal(str(e[k])) == 0 for k in
                   ("own_hr", "op_hr", "rent_month"))
        assert "EXAMPLE" in e["desc"] and "enter your" in e["desc"]
    codes = {x["code"] for x in pack["labor"] + pack["equipment"]}
    for c in pack["crews"]:
        assert c["code"].startswith("EX-")
        assert {m[0] for m in c["labor"] + c["equipment"]} <= codes
        assert "EXAMPLE" in c["desc"] and c["production"]
        for p in c["production"]:
            assert p["rate"] > 0 and p["unit"] and "EXAMPLE" in p["note"]


def test_install_crews_adds_only_missing_codes():
    heavy.save_items("labor", [{"code": "EX-LAB", "desc": "my laborer",
                                "base": 31}], note="mine")
    n = starters.install_crews(confirm=lambda q: True)      # v2 step 5: asks
    lib = heavy.library()
    assert lib["labor"]["EX-LAB"]["base"] == 31          # yours kept
    assert lib["labor"]["EX-LAB"]["desc"] == "my laborer"
    pack = starters.crew_pack()
    total = sum(len(pack[k]) for k in ("labor", "equipment", "crews"))
    assert n == total - 1
    assert all(c["code"] in lib["crews"] for c in pack["crews"])
    assert starters.install_crews(confirm=lambda q: True) == 0
