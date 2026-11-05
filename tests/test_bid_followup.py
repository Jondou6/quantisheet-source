"""v19: open / view / intent tracking and automatic follow-ups (dry run)."""
import json

from app import bid_followup as fu
from app import bid_followup as ib  # was invite_boost (folded Nov 4)

PROJECT = {"name": "Riverside WWTP"}
SENDER = {"name": "Jon Smith", "email": "jon@yourco.test", "signature": "Jon"}


def _pkg():
    return {"title": "Yard Piping", "trades": "utilities", "due": "2026-11-12",
            "due_time": "2:00 PM", "bidders": [
                {"company": "A", "contact": "Amy Lee", "email": "a@x.test",
                 "token": "ta", "invited": "2026-10-01", "status": "Invited"},
                {"company": "B", "contact": "Bob", "email": "b@x.test",
                 "token": "tb", "invited": "2026-10-01", "status": "Invited",
                 "opened": "2026-10-02"},
                {"company": "C", "contact": "Cy", "email": "c@x.test",
                 "token": "tc", "invited": "2026-10-01", "status": "Viewed",
                 "opened": "2026-10-02", "viewed": "2026-10-02"},
                {"company": "D", "contact": "Di", "email": "d@x.test",
                 "token": "td", "invited": "2026-10-01",
                 "status": "Will Bid"},
                {"company": "E", "contact": "Ed", "email": "e@x.test",
                 "token": "te", "invited": "2026-10-01",
                 "status": "Won't Bid"}]}


def test_stage_of_each_bidder():
    p = _pkg()
    st = {b["company"]: fu.stage(b) for b in p["bidders"]}
    assert st == {"A": "not opened", "B": "opened", "C": "viewed",
                  "D": "bidding", "E": "declined"}


def test_open_pixel_and_intent_links_update_the_record():
    p = _pkg()
    assert fu.pixel_url("https://hub.test", "ta") == \
        "https://hub.test/bid.gif?t=ta"
    fu.record(p, "ta", "opened", when="2026-10-03")
    a = p["bidders"][0]
    assert a["opened"] == "2026-10-03" and fu.stage(a) == "opened"
    fu.record(p, "ta", "intent", value="unsure", reason="", when="2026-10-04")
    assert a["status"] == "Might Bid" and fu.stage(a) == "unsure"
    fu.record(p, "tb", "intent", value="no", reason="Too busy",
              when="2026-10-04")
    assert p["bidders"][1]["status"] == "Won't Bid"
    assert p["bidders"][1]["decline_reason"] == "Too busy"


def test_due_follow_ups_follow_the_sequence():
    p = _pkg()
    due = fu.due(p, today="2026-10-04")             # day 3
    assert [(d["company"], d["step"]) for d in due] == [("A", "not_opened")]
    due = fu.due(p, today="2026-10-06")             # day 5
    assert {(d["company"], d["step"]) for d in due} == {
        ("A", "not_opened"), ("B", "opened_no_click")}
    due = fu.due(p, today="2026-10-08")             # day 7
    assert ("C", "viewed_no_intent") in {(d["company"], d["step"])
                                          for d in due}
    assert all(d["company"] not in ("D", "E") for d in due)


def test_send_marks_steps_and_stops_repeats(tmp_path):
    p = _pkg()
    box = ib.DryRunOutbox(str(tmp_path / "ob"))
    n = fu.send_due(p, PROJECT, SENDER, box, today="2026-10-08",
                    link_for=lambda b: f"https://hub.test/bid.html?t={b['token']}")
    assert n == 3
    assert fu.due(p, today="2026-10-08") == []       # each step once
    a = p["bidders"][0]
    assert a["followups"] == ["not_opened"]
    txt = (tmp_path / "ob" / "0001-a@x.test.eml").read_text()
    assert "did this reach you" in txt.lower() and "Hi Amy" in txt
    log = [json.loads(x) for x in (tmp_path / "ob" / "log.jsonl")
           .read_text().splitlines()]
    assert {e["kind"] for e in log} == {"followup"}


def test_bid_week_reminder_unknown_call_list_and_coverage():
    p = _pkg()
    for b in p["bidders"]:
        b.setdefault("followups", []).extend(
            ["not_opened", "opened_no_click", "viewed_no_intent"])
    steps = {(d["company"], d["step"]) for d in fu.due(p, today="2026-11-09")}
    assert ("D", "due_reminder") in steps           # T-3, bidding
    assert ("A", "due_reminder") not in steps
    calls = fu.call_list(p, today="2026-11-10")      # T-2, still unknown
    assert [c["company"] for c in calls] == ["A", "B", "C"]
    cov = fu.coverage(p, today="2026-11-11", minimum=3)
    assert cov["alert"] and cov["likely"] == 1 and cov["trade"] == "utilities"


def test_replied_or_unsubscribed_stops_sequence():
    p = _pkg()
    p["bidders"][0]["replied"] = "2026-10-03"
    p["bidders"][1]["unsubscribed"] = True
    due = fu.due(p, today="2026-10-08")
    assert {d["company"] for d in due} == {"C"}
