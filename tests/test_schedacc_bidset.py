"""Bid-set scheduling (Nov 5 gold fixture): a made-up renovation bid -
bid-form scope list, plan sheets, two addenda and bidder Q&A, applied in
order. The answer key is the structure an experienced team scheduled for
this kind of job; every name and number in the fixture is invented.

The draft must: schedule every live line with a citation, keep the six
removed items off, hold rough-in inspection before close-in and one final
inspection before Substantial Completion, chain the long-lead and
owner-furnished items, size durations from quantities, start and finish
on workdays, and carry the "for reference only" note.
"""
import json
import os

import pytest

from app.pm.schedacc import bidset
from app.pm.schedacc.engine import compile_schedule
from app.pm.schedacc.score import score_bid

HERE = os.path.join(os.path.dirname(__file__), "data", "schedacc",
                    "renovation_bid")
DOCS = (("01_bid_form.txt", "bid", "Bid Form"),
        ("02_A1.1.txt", "drawing", "A1.1"),
        ("03_A1.2.txt", "drawing", "A1.2"),
        ("04_A2.1.txt", "drawing", "A2.1"),
        ("05_addendum_1.txt", "addendum", "Addendum 1"),
        ("06_addendum_2.txt", "addendum", "Addendum 2"),
        ("07_bidder_qa.txt", "qa", "Bidder Q&A"))


def _docs():
    out = []
    for name, kind, did in DOCS:
        with open(os.path.join(HERE, name), encoding="utf-8") as fh:
            out.append({"kind": kind, "id": did, "text": fh.read()})
    return out


def _json(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture(scope="module")
def draft():
    return compile_schedule(bid_set=_docs(), ntp="2026-11-30",
                            project_name="Station 4 (test)",
                            settings={"allow_ai": False})


def test_addenda_and_answers_remove_six_items_in_order():
    got = bidset.resolve(_docs())
    removed = {x["key"]: x["removed_by"] for x in got["removed"]}
    assert removed == {"B3": "Addendum 1 item 1", "B4": "Addendum 1 item 2",
                       "B10": "Addendum 2 item 3", "B11": "Bidder Q&A Q2",
                       "B12": "Bidder Q&A Q3", "B14": "Bidder Q&A Q4"}
    keys = {x["key"] for x in got["lines"]}
    assert {"B2", "B5", "B13", "A1.1-1", "A1.2-9", "A2.1-1", "X1",
            "X2"} <= keys
    # "Yes, prime and paint" and the clarification remove nothing
    assert "B2" in keys and len(got["lines"]) == 22


def test_later_document_wins_and_unclear_answers_stay_put():
    docs = [{"kind": "bid", "id": "Bid", "text":
             "1. Paint the lobby walls (about 2,000 SF).\n"
             "2. Replace the lobby ceiling tile.\n"},
            {"kind": "addendum", "id": "Add 1", "text": "1. Delete item 1."},
            {"kind": "addendum", "id": "Add 2", "text":
             "1. ADD: Paint the lobby walls (about 2,000 SF)."},
            {"kind": "qa", "id": "QA", "text":
             "Q1: Is the lobby work still in?\nA1: It is not required.\n"}]
    got = bidset.resolve(docs)
    keys = [x["key"] for x in got["lines"]]
    assert "B1" in keys                     # restored by Addendum 2
    assert ("restored", "B1", "Add 2 item 1",
            "Paint the lobby walls (about 2,000 SF)") in got["log"]
    # "lobby" alone matches both lines - nothing is removed on a guess
    assert "B2" in keys and got["log"][-1][0] == "unmatched"


def test_quantities_rates_and_flags():
    assert bidset.quantity("Treat steel (about 4,500 SF).") == (4500.0, "SF")
    assert bidset.quantity("Re-install doors (24 doors)") == (24.0, "EA")
    assert bidset.lead_days("lead time is 8 weeks") == 40
    p = bidset.plan_line({"text": "Treat corrosion on structural steel "
                          "(about 4,500 SF)", "source": "x"})
    assert (p["cls"], p["days"], p["duration_kind"]) == ("coating", 45,
                                                         "computed")
    q = bidset.plan_line({"text": "Repair the ceiling crack", "source": "x"})
    assert q["quantity_missing"] and q["duration_kind"] == "estimated"
    o = bidset.plan_line({"text": "Owner-furnished, owner-installed "
                          "casework (OFOI)", "source": "x"})
    assert o["owner_installed"] and o["owner_furnished"]


def test_draft_passes_the_completeness_gate(draft):
    names = {c["name"]: c for c in draft["rubric"]["checks"]}
    for key in ("scope_to_activity", "activity_to_source", "removed_scope",
                "hold_points", "workdays", "logic", "long_lead",
                "submittals"):
        assert names[key]["passed"], (key, names[key]["detail"])
    assert draft["status"] == "finished", draft["rubric"]["gaps"]


def test_draft_against_the_answer_key(draft):
    exp = _json("expected.json")
    got = score_bid(draft["activities"], exp)
    assert got["missed"] == [] and got["recall"] == 1.0
    assert got["forbidden"] == []
    assert got["order"] == [], got["order"]
    assert got["durations"] == [], got["durations"]
    assert got["weekend"] == []


def test_older_draft_shape_fails_the_same_key():
    """The Nov 4 kind of draft (bid list only) is what this fixture is
    here to catch: missing interior work, removed items scheduled."""
    old = _json("older_draft.json")["activities"]
    got = score_bid(old, {**_json("expected.json"),
                          "activities": [dict(e, cls=None) for e in
                                         _json("expected.json")["activities"]]})
    assert got["recall"] < 0.6
    assert len(got["forbidden"]) == 6
    assert "Interior demolition" in got["missed"]
    assert any("Structural steel" in d for d in got["durations"])


def test_one_final_inspection_and_holds(draft):
    acts = draft["activities"]
    finals = [a for a in acts if a["cls"] == "final_inspection"]
    assert len(finals) == 1
    rinsp = [a for a in acts if a["cls"] == "rough_in_inspection"]
    assert len(rinsp) == 1
    cover = [a for a in acts if a["cls"] == "cover"]
    assert all(c["es"] > rinsp[0]["ef"] for c in cover)


def test_chains_citations_and_caveat(draft):
    acts = draft["activities"]
    hood = [a for a in acts if "hood" in a["name"].lower()]
    classes = {a["cls"] for a in hood}
    assert {"submittal_submit", "submittal_review", "release", "fabrication",
            "delivery", "hood_install"} <= classes
    assert {a["cls"] for a in acts if "casework" in a["name"].lower()} >= {
        "owner_furnish", "owner_delivery", "casework"}
    inst = next(a for a in acts if a["cls"] == "casework")
    assert inst["roles"] == ["Owner"]
    for a in acts:
        if a.get("scope_key"):
            c = a["citations"][0]
            assert c["document"] and c["source"]
    assert draft["caveat"].startswith("For reference only")
    assert draft["narrative"].startswith("For reference only")
    assert "removed by Bidder Q&A Q2" in draft["narrative"]
    gaps = draft["scope"]["quantity_gaps"]
    assert any("ceiling crack" in g for g in gaps)
    steel = next(a for a in acts if "structural steel" in a["name"].lower())
    assert steel["calendar"] == "weather" and "4500 SF" in steel["basis"]


def test_nothing_names_other_scheduling_software(draft):
    blob = (draft["narrative"] + json.dumps(draft["scope"]) +
            " ".join(a["name"] for a in draft["activities"])).lower()
    for word in ("primavera", "p6", "ms project", "microsoft project",
                 "smartsheet", "procore"):
        assert word not in blob


def test_spec_path_is_unchanged_without_a_bid_set():
    from test_schedacc_gold import _drawings, _load
    doc = compile_schedule(spec_pages=_load("tenant_improvement.txt"),
                           drawings=_drawings("tenant_improvement"),
                           project_type="tenant_improvement",
                           ntp="2026-11-30", settings={"allow_ai": False})
    assert "scope" not in doc and "caveat" not in doc
    assert doc["status"] == "finished"


def test_exports_carry_the_caveat(draft, tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    from app.pm.schedacc.export_xlsx import export_xlsx
    p = export_xlsx(draft, str(tmp_path / "s.xlsx"))
    wb = openpyxl.load_workbook(p)
    assert wb["Notes"]["A1"].value.startswith("For reference only")
    rows = [r[0].value for r in wb["Notes"].iter_rows()]
    assert any(v and "water softener" in v for v in rows)
