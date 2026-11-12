"""Nov 11, bidding phase E: the Bid Board - invitations that come to us,
their dates, duplicates, go / no-go, results, and reading an invitation
email. Made-up companies, projects and addresses only."""
import datetime as dt
import os
from decimal import Decimal

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import bidboard as B, bidinvite, settings               # noqa: E402

try:                                     # the window tests' fixtures
    from test_gui import win, qapp                              # noqa: F401
except Exception:                                         # noqa: BLE001
    pass


@pytest.fixture(autouse=True)
def cfg(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", {"author": "Pat Morgan"})


def _school(**kw):
    o = {"project": "Riverside Elementary School Addition",
         "gc": "Example Builders",
         "address": "1200 River Road, Springfield, SC",
         "due": "12/4/2026", "due_time": "2:00 PM",
         "job_walk": "11/20/2026 10:00 AM", "rfi_due": "Nov 25, 2026",
         "estimator": "Pat", "trade": "Plumbing"}
    o.update(kw)
    return o


# ---- 5a: the log ---------------------------------------------------------------

def test_an_opportunity_typed_in_with_no_email():
    a = B.save(_school(amount="$1,234,500.505"))
    assert (a["due"], a["job_walk"], a["rfi_due"]) == (
        "2026-12-04", "2026-11-20 10:00 AM", "2026-11-25")
    assert a["amount"] == "1234500.51" and a["status"] == "Undecided"
    assert a["created"] and B.get(a["id"])["project"] == a["project"]
    a["estimator"] = "Lee"
    b = B.save(a)
    assert b["created"] == a["created"] and len(B.load()) == 1
    with pytest.raises(B.BoardError):
        B.save({"gc": "Nobody"})                     # no project name
    with pytest.raises(B.BoardError):
        B.save(_school(amount="about a million"))
    assert B.clean(_school(due="soon"))["due"] == ""
    assert B.clean(_school(status="Maybe"))["status"] == "Undecided"
    B.remove(a["id"])
    assert B.load() == []


def test_status_pipeline_and_the_order_of_the_list():
    a = B.save(_school())
    b = B.save({"project": "Oak Street Medical Office", "gc": "Sample "
                "Construction", "due": "2026-11-30"})
    c = B.save({"project": "Town Hall Roof", "gc": "Example Builders",
                "due": "2026-10-01", "status": "Lost"})
    assert [o["project"] for o in sorted(B.load(), key=B.sort_key)] == [
        "Oak Street Medical Office", a["project"], "Town Hall Roof"]
    got = B.set_status(a["id"], "Won", "1,000,000")
    assert got["status"] == "Won" and got["amount"] == "1000000.00" and \
        got["decided_at"]
    with pytest.raises(B.BoardError):
        B.set_status(a["id"], "Sort of")
    with pytest.raises(B.BoardError):
        B.set_status("gone", "Won")
    assert b and c


# ---- 5b: the calendar ---------------------------------------------------------

def test_calendar_and_ics(tmp_path):
    a = B.save(_school())
    B.save({"project": "Town Hall Roof", "due": "2026-10-01",
            "status": "Lost"})
    ev = B.events()
    assert [(e["date"], e["what"]) for e in ev] == [
        ("2026-11-20", "Job walk"), ("2026-11-25", "Questions due"),
        ("2026-12-04", "Bid due")]             # a lost bid has no dates
    assert ev[0]["time"] == "10:00 AM" and ev[2]["time"] == "2:00 PM"
    p = B.to_ics(ev, str(tmp_path / "b.ics"))
    text = open(p, encoding="utf-8", newline="").read()
    assert text.startswith("BEGIN:VCALENDAR\r\n") and \
        text.count("BEGIN:VEVENT") == 3
    assert "DTSTART;VALUE=DATE:20261204" in text and \
        "DTEND;VALUE=DATE:20261205" in text
    assert "SUMMARY:Bid due: Riverside Elementary School Addition " \
        "(Example Builders) 2:00 PM" in text
    assert "ATTENDEE" not in text and "ORGANIZER" not in text   # no sending
    assert a


# ---- 5d: duplicates -----------------------------------------------------------

def test_same_project_from_another_gc_is_caught_and_says_why():
    a = B.save(_school())
    new = B.clean({"project": "Riverside Elem. Addition",
                   "gc": "Sample Construction",
                   "address": "1200 River Rd, Springfield SC",
                   "due": "2026-12-05"})
    dups = B.duplicates(new)
    assert len(dups) == 1 and dups[0][0]["id"] == a["id"]
    why = "; ".join(dups[0][1])
    assert "same address" in why and "project names alike" in why and \
        "due 1 day(s) apart" in why and "another GC (Example Builders)" in why
    # not everything due that week is the same job
    other = B.clean({"project": "Oak Street Medical Office",
                     "gc": "Example Builders", "due": "2026-12-04",
                     "address": "88 Oak Street, Springfield, SC"})
    assert B.duplicates(other) == []
    # a like-named job a year later is another job
    later = B.clean({"project": "Riverside Elementary School Addition",
                     "gc": "Example Builders", "due": "2027-12-04"})
    assert B.duplicates(later) == []
    # same number on another street is not the same address
    assert B.why_same(B.clean({"project": "Annex", "address":
                               "1200 Lake Road, Springfield"}), a) == []


def test_groups_and_dismissing_a_wrong_match():
    a = B.save(_school())
    b = B.save({"project": "Riverside Elem. Addition", "gc": "Sample "
                "Construction", "due": "2026-12-05"})
    c = B.save({"project": "Riverside Elementary Addition", "gc": "Demo "
                "Contracting", "due": "2026-12-04"})
    g = B.groups()
    assert {g[x["id"]] for x in (a, b, c)} == {(1, "same project, 3 GCs")}
    B.save(B.dismiss(B.dismiss(b, a["id"]), c["id"]))
    g = B.groups()
    assert b["id"] not in g and g[a["id"]] == (1, "same project, 2 GCs")
    assert B.duplicates(B.get(a["id"]))[0][0]["id"] == c["id"]


# ---- 5e: results --------------------------------------------------------------

def _history():
    for i, st in enumerate(["Won", "Won", "Lost", "Submitted", "Declined",
                            "Accepted"]):
        B.save({"project": f"Example job {i}", "gc": "Example Builders",
                "due": f"2026-{9 + i // 3:02d}-1{i}", "status": st,
                "estimator": "Pat", "amount": "100000"})
    B.save({"project": "Sample tower", "gc": "Sample Construction",
            "due": "2026-10-20", "status": "Lost", "estimator": "Lee"})


def test_win_rate_counts_won_and_lost_only():
    _history()
    rows = {r["gc"]: r for r in B.win_rate_by_gc()}
    ex = rows["Example Builders"]
    assert (ex["won"], ex["lost"], ex["pending"], ex["declined"],
            ex["open"]) == (2, 1, 1, 1, 1)
    assert ex["rate"] == 66.7                    # 2 of 3, not 2 of 6
    assert rows["Sample Construction"]["rate"] == 0.0
    B.save({"project": "New one", "gc": "Demo Contracting"})
    assert {r["gc"]: r for r in B.win_rate_by_gc()}[
        "Demo Contracting"]["rate"] is None      # nothing decided yet
    months = B.bids_per_month()
    assert [(m["month"], m["submitted"], m["won"], m["lost"])
            for m in months] == [("2026-09", 3, 2, 1), ("2026-10", 2, 0, 1)]
    wl = {r["estimator"]: r for r in B.workload(
        today=dt.date(2026, 10, 10))}
    assert wl["Pat"]["open"] == 1 and wl["Pat"]["due_7"] == 1 and \
        wl["Pat"]["next_due"] == "2026-10-15"
    assert wl["(nobody yet)"]["open"] == 1


def test_results_show_in_the_dashboard_by_gc():
    from app import dashboard as db
    _history()
    assert "gc" in db.HIT_BY and db.BY_LABEL["gc"] == "GC (bid to)"
    jobs = [db._new_job(j.pop("key"), **j) for j in B.dashboard_jobs()]
    assert len(jobs) == 6                        # the open one isn't a bid
    assert {j["result"] for j in jobs} == {"Won", "Lost", "Pending",
                                           "No bid"}
    assert jobs[0]["bid"] == Decimal("100000.00")
    rows = {r["label"]: r for r in db.hit_rate(jobs, "gc")}
    ex = rows["Example Builders"]
    assert (ex["won"], ex["lost"], ex["decided"]) == (2, 1, 3)
    assert float(ex["rate"]) == pytest.approx(66.7, abs=0.05)
    # the dashboard's own load picks them up
    data = db.load(price_db=False)
    assert sum(1 for j in data["jobs"] if j["key"].startswith("bb:")) == 6
    # ... and a list of folders given by hand does not
    assert not [j for j in db.load([], price_db=False)["jobs"]
                if j["key"].startswith("bb:")]


# ---- 5f: go / no-go -----------------------------------------------------------

def test_go_score_weights_are_settings():
    assert B.go_score({})["score"] is None
    sc = B.go_score({"scope": "Yes", "location": "Partly",
                     "workload": "No"})
    assert sc == {"score": 59.1, "recommendation": "Look closer",
                  "answered": 3, "of": 6}
    assert B.go_score({k: "Yes" for k, _l in B.FACTORS})[
        "recommendation"] == "Go"
    assert B.go_score({k: "No" for k, _l in B.FACTORS})[
        "recommendation"] == "No-go"
    B.set_go_settings({"scope": 100, "location": 0, "workload": 0})
    assert B.go_score({"scope": "Yes", "location": "No",
                       "workload": "No"})["score"] == 100.0
    assert B.go_settings()["weights"]["relationship"] == 20   # untouched
    B.set_go_settings(go=90, maybe=80)
    assert B.go_score({"scope": "Yes", "relationship": "Partly"})[
        "recommendation"] == "Go"                # 110 of 120 = 91.7
    with pytest.raises(B.BoardError):
        B.set_go_settings(go=40, maybe=60)
    with pytest.raises(B.BoardError):
        B.set_go_settings({k: 0 for k, _l in B.FACTORS})
    settings.set(B.GO_KEY, {"weights": {"scope": "lots"}, "go": "x"})
    assert B.go_settings()["weights"]["scope"] == 25 and \
        B.go_settings()["go"] == 65              # junk falls back


def test_the_person_decides_and_the_reason_is_kept():
    a = B.save(_school())
    with pytest.raises(B.BoardError):
        B.record_decision(a, {}, "Maybe", "")
    o = B.save(B.record_decision(
        a, {k: "No" for k, _l in B.FACTORS}, "Go",
        "Owner asked for us by name", "Pat Morgan"))
    g = o["go"]
    assert g["recommendation"] == "No-go" and g["decision"] == "Go" and \
        g["reason"] == "Owner asked for us by name" and g["by"] == \
        "Pat Morgan" and g["at"]
    assert o["status"] == "Accepted"
    assert B.get(o["id"])["go"]["answers"]["scope"] == "No"
    _history()
    assert B.history_answer("Example Builders") == "Yes"       # 2 of 3
    assert B.history_answer("Sample Construction") == ""       # 1 decided


# ---- 5c: reading an invitation -----------------------------------------------

EMAIL = """Hello,

Example Builders invites you to bid the following:

Project: Riverside Elementary School Addition
Location: 1200 River Road, Springfield, SC 29501
General Contractor: Example Builders Inc.
Trade: Division 22 Plumbing
Bids due: Friday, December 4, 2026 at 2:00 PM EST
Pre-bid meeting: 11/20/2026 10:00 AM at the site
RFIs due: Nov 25, 2026
Plans: https://plans.example.com/riverside/abc123.

Thanks,
Pat Morgan
"""


def _eml(path, body=EMAIL, html=False):
    from email.message import EmailMessage
    m = EmailMessage()
    m["From"] = "Pat Morgan <pat@examplebuilders.example>"
    m["To"] = "bids@sample-plumbing.example"
    m["Subject"] = "Invitation to Bid: Riverside Elementary School Addition"
    if html:
        m.set_content("see the html part")
        m.add_alternative("<html><body>" + body.replace("\n", "<br>") +
                          "<script>ignored()</script></body></html>",
                          subtype="html")
    else:
        m.set_content(body)
    with open(path, "wb") as f:
        f.write(bytes(m))
    return str(path)


def test_invitation_email_becomes_a_draft(tmp_path):
    p = _eml(tmp_path / "invite.eml")
    before = open(p, "rb").read()
    draft, found = bidinvite.from_file(p)
    assert draft["project"] == "Riverside Elementary School Addition"
    assert draft["gc"] == "Example Builders Inc"
    assert (draft["due"], draft["due_time"]) == ("2026-12-04", "2:00 PM EST")
    assert draft["job_walk"] == "2026-11-20 10:00 AM"
    assert draft["rfi_due"] == "2026-11-25"
    assert draft["address"] == "1200 River Road, Springfield, SC 29501"
    assert draft["location"] == "Springfield, SC"
    assert draft["plan_links"] == "https://plans.example.com/riverside/abc123"
    assert draft["status"] == "Undecided" and draft["source"] == "invite.eml"
    assert set(found) >= {"project", "gc", "due", "job_walk", "rfi_due",
                          "address", "plan_links"}
    assert open(p, "rb").read() == before         # the email is not changed
    assert B.load() == []                         # and nothing was saved


def test_invitation_with_little_in_it_and_other_files(tmp_path):
    draft, found = bidinvite.parse(
        "ITB - Oak Street Medical Office", "Lee", "lee@gmail.com",
        "Bids are due December 9, 2026 at 3pm. Job walk Dec 2, 2026 at 9 AM.")
    assert draft["project"] == "Oak Street Medical Office"
    assert draft["gc"] == ""                      # a mail service isn't a GC
    assert (draft["due"], draft["due_time"]) == ("2026-12-09", "3pm")
    assert draft["job_walk"] == "2026-12-02 9 AM"
    assert "gc" not in found and "address" not in found
    with pytest.raises(B.BoardError) as e:
        bidinvite.from_file(str(tmp_path / "invite.msg"))
    assert ".eml" in str(e.value)
    d2, _f = bidinvite.from_file(_eml(tmp_path / "h.eml", html=True))
    assert d2["due"] == "2026-12-04" and "ignored()" not in d2["notes"]


# ---- the window -----------------------------------------------------------------

@pytest.fixture
def board(monkeypatch):
    pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtWidgets import QApplication, QMessageBox
    QApplication.instance() or QApplication([])
    said = []
    for n in ("information", "warning"):
        monkeypatch.setattr(QMessageBox, n, staticmethod(
            lambda *a, **k: said.append(a[2]) or 0))
    from app import bidboard_ui
    w = bidboard_ui.BidBoard()
    w.said = said
    return w


def test_board_window_add_duplicate_warning_and_tabs(board, tmp_path):
    w = board
    assert w.table.rowCount() == 0 and "drag a saved email" in w.note.text()
    dlg = w.add(_school(), show=False)
    assert dlg.save()["project"].startswith("Riverside")
    w.refresh()
    assert w.table.rowCount() == 1
    # the same job from another GC: warned once, with the reason; saved
    # only when the user saves again
    dlg = w.from_email(_eml(tmp_path / "i.eml", EMAIL.replace(
        "Example Builders Inc.", "Sample Construction")), show=False)
    assert "Read from the email" in dlg.findChildren(
        type(dlg.warn))[0].text()
    assert dlg.save() is None and "already on the board" in dlg.warn.text()
    assert "same address" in dlg.warn.text() and len(B.load()) == 1
    assert dlg.save() is not None and len(B.load()) == 2
    w.refresh()
    same = [w.table.item(r, 11).text() for r in range(2)]
    assert all("same project, 2 GCs" in s for s in same)
    assert "price each once" in w.note.text()
    assert w.cal.rowCount() == 6
    assert w.export_ics(str(tmp_path / "c.ics"))
    # bad date typed: not saved, said why
    dlg = w.add({"project": "X job", "due": "the 4th"}, show=False)
    dlg.w["due"].setText("the 4th")
    assert dlg.save() is None and "wasn't understood" in dlg.warn.text()


def test_board_window_go_no_go_status_and_results(board):
    w = board
    B.save(_school())
    w.refresh()
    assert w.go(show=False) is None and "Select a row" in w.said[-1]
    w.table.selectRow(0)
    g = w.go(show=False)
    assert "Answer what you know" in g.score.text()
    g.box["scope"].setCurrentText("Yes")
    g.box["workload"].setCurrentText("No")
    assert "Recommendation" in g.score.text()
    assert g.decide("Go") is None                 # no reason: not decided
    g.reason.setText("Repeat client")
    o = g.decide("Go")
    assert o["status"] == "Accepted" and o["go"]["reason"] == "Repeat client"
    assert g.weights({"weights": {"scope": 50}, "go": 70, "maybe": 40})[
        "weights"]["scope"] == 50
    w.refresh()
    w.table.selectRow(0)
    assert "Go (score" in w.table.item(0, 10).text()
    assert w.set_status("Won", "250,000")["amount"] == "250000.00"
    w.filter.setCurrentText("Everything")
    assert w.table.item(0, 9).text() == "$250,000.00"
    assert w.by_gc.item(0, 3).text() == "100%"
    assert w.by_month.rowCount() == 1
    w.table.selectRow(0)
    assert w.remove(confirm=False) is False and w.remove(confirm=True)
    assert B.load() == []


def test_main_window_command(win):
    from app import simple_menu
    names = [n for _t, _g, ns, _a in simple_menu.TREE for n in ns]
    assert "Bid Board" in names
    assert win.command("Bid Board") is not None
    dlg = win.bid_board()
    assert dlg.isVisible()
    dlg.close()
