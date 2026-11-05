"""Claim-ready schedule records: the hash-chained update log, update
comparison, time impact analysis of delay events, concurrency, notice and
windows analysis."""
import datetime as dt

from app.pm import schema, schedule
from app.pm import schedule_record as sr
from test_schedule import _store

D = dt.date.fromisoformat
NOW = dt.datetime(2026, 10, 1, 8, 0)


def _act(s, name):
    return s.find("activity", name=name)[0]


def _edit(s, name, **kw):
    a = _act(s, name)
    a.update(kw)
    s.save_record("activity", a)


def _delay(s, **kw):
    kw.setdefault("title", "Delay")
    kw.setdefault("status", "Open")
    return s.save_record("delay", kw)


def test_chain_and_verify(tmp_path, monkeypatch):
    s = _store(tmp_path, monkeypatch)
    a = sr.snapshot(s, "baseline", note="Contract baseline", who="Pat",
                    now=NOW)
    assert a["n"] == 1 and a["prev_hash"] == "" and a["kind"] == "baseline"
    assert a["finish"] == "2026-11-23" and a["data_date"] == "2026-10-01"
    assert a["by"] == "Pat" and a["taken"] == "2026-10-01T08:00:00"
    assert set(a["critical"]) >= {"A0001", "A0002", "A0003", "A0007"}
    ft = next(x for x in a["activities"] if x["name"] == "Footings")
    assert (ft["es"], ft["ef"], ft["float"], ft["critical"]) == \
        ("2026-11-12", "2026-11-17", 0, True)
    assert ft["responsible"] == "ABC" and ft["preds"][0]["lag"] == 1
    _edit(s, "Footings", duration=6)
    b = sr.snapshot(s, now=NOW)
    assert b["n"] == 2 and b["prev_hash"] == a["hash"]
    assert b["finish"] == "2026-11-25"
    assert [e["n"] for e in sr.updates(s)] == [1, 2]
    assert sr.verify(s) == []
    # reopened from disk the chain still checks out
    from app.pm.store import ProjectStore
    s2 = ProjectStore(s.folder)
    assert len(sr.updates(s2)) == 2 and sr.verify(s2) == []
    # someone "fixes" the old finish date
    log = sr.updates(s)
    log[0]["finish"] = "2026-12-01"
    s.set_setting(sr.SETTING, log)
    probs = sr.verify(s)
    assert probs and all("Update 1" in p for p in probs)
    # re-hashing the edited entry breaks the link to the next one
    log[0]["hash"] = sr._hash(log[0])
    s.set_setting(sr.SETTING, log)
    probs = sr.verify(s)
    assert any("Update 2" in p and "chain" in p for p in probs)
    # dropping an update shows too
    s.set_setting(sr.SETTING, sr.updates(s)[1:])
    assert any("Update 2" in p for p in sr.verify(s))
    try:
        sr.snapshot(s, "guess")
        assert False, "bad kind accepted"
    except ValueError:
        pass


def test_compare_flags_retroactive_and_critical(tmp_path, monkeypatch):
    s = _store(tmp_path, monkeypatch)
    s.set_setting("data_date", "2026-11-03")
    _edit(s, "Mobilize", actual_start="2026-11-02",
          actual_finish="2026-11-03", status="Complete", percent=100)
    a = sr.snapshot(s, now=NOW)
    # the next update rewrites history and changes the plan
    _edit(s, "Mobilize", actual_start="2026-10-30")
    _edit(s, "Excavate", actual_start="2026-10-28", status="In Progress",
          percent=10)                      # before update 1's data date
    _edit(s, "Rebar", duration=10)
    _edit(s, "Survey", preds=[{"id": "A0001", "type": "SS"}])
    s.save_record("activity", {"name": "Backfill", "duration": 2,
                               "preds": [{"id": "A0005"}]})
    b = sr.snapshot(s, now=NOW)
    c = sr.compare(a, b)
    assert (c["from"], c["to"]) == (1, 2)
    retro = {(r["_no"], r["field"]) for r in c["retroactive"]}
    assert ("A0001", "actual_start") in retro
    assert ("A0002", "actual_start") in retro
    assert ("A0001", "actual_finish") not in retro      # unchanged
    assert any("A0001" in f and "changed after" in f
               for f in c["red_flags"])
    assert [d["_no"] for d in c["durations"]] == ["A0005"]
    assert c["durations"][0]["before"] == 3 and \
        c["durations"][0]["after"] == 10
    assert [x["_no"] for x in c["logic"]] == ["A0004"]
    assert "A0001 SS" in c["logic"][0]["after"]
    assert [x["name"] for x in c["added"]] == ["Backfill"]
    assert c["removed"] == []
    # Rebar (now 12 days with Backfill) drives; the slab path has float
    assert "A0005" in c["critical_entered"]
    assert "A0007" in c["critical_left"]
    assert c["finish_after"] > c["finish_before"]
    assert c["finish_workdays"] > 0
    assert c["finish_calendar_days"] >= c["finish_workdays"]
    # the same update against itself: nothing to report
    same = sr.compare(b, b)
    assert not (same["retroactive"] or same["durations"] or same["logic"]
                or same["critical_entered"] or same["red_flags"])
    assert same["finish_workdays"] == 0


def test_tia_on_the_critical_path(tmp_path, monkeypatch):
    s = _store(tmp_path, monkeypatch)
    sr.snapshot(s, "baseline", now=NOW)
    # Footings changed after the base update: TIA must use the update
    _edit(s, "Footings", duration=9)
    # redesign after excavation, before footings. Excavate ends Nov 10;
    # the fragnet runs Nov 11-13, footings Nov 16-19 (it had a 1-day lag
    # after excavation, so 3 days of fragnet push it 2), slab Nov 20-25.
    rec = _delay(s, title="Footing redesign", responsibility="Owner",
                 cause="Design error / RFI response",
                 event_start="2026-11-05",
                 fragnet=[{"name": "Redesign footings", "duration": 3,
                           "pred": "A0002", "succ": "A0003"}])
    r = sr.tia(s, rec)
    assert r["base_update"] == 1
    assert r["finish_before"] == D("2026-11-23")
    assert r["finish_after"] == D("2026-11-25")
    assert r["impact_workdays"] == 2 and r["impact_calendar_days"] == 2
    assert r["fragnet_on_critical"]
    assert "TIA-F1" in r["critical_after"] and "A0003" in r["critical_after"]
    # nothing was saved
    assert len(s.list("activity")) == 7
    assert _act(s, "Footings")["preds"] == [{"id": "2", "type": "FS",
                                             "lag": 1}]
    # 3 more workdays on footings: slab Nov 23, 24, 25 and 27 (Thanksgiving
    # Nov 26 is a holiday) - 3 workdays but 4 calendar days
    rec2 = _delay(s, title="Rock in footings", responsibility="Owner",
                  cause="Differing site conditions",
                  event_start="2026-11-12",
                  affected=[{"id": "A0003", "days": 3}])
    r2 = sr.tia(s, rec2)
    assert r2["finish_after"] == D("2026-11-27")
    assert r2["impact_workdays"] == 3 and r2["impact_calendar_days"] == 4
    assert not r2["fragnet_on_critical"]
    # with no update before the event, the live schedule is the base
    early = _delay(s, title="Early", event_start="2026-09-01",
                   affected=[{"id": "A0003", "days": 1}])
    r3 = sr.tia(s, early)
    assert r3["base_update"] is None
    # live: Footings 9 days ends Nov 24, slab Nov 25, 27, 30, Dec 1
    assert r3["finish_before"] == D("2026-12-01")
    assert r3["finish_after"] == D("2026-12-02")
    assert r3["impact_workdays"] == 1
    assert any("live schedule" in n for n in r3["notes"])
    allr = sr.tia_all(s)
    assert [x["_no"] for x in allr] == [early["_no"], rec["_no"],
                                        rec2["_no"]]


def test_tia_absorbed_by_float(tmp_path, monkeypatch):
    s = _store(tmp_path, monkeypatch)
    sr.snapshot(s, now=NOW)
    # Survey (float) gets a 2-day fragnet before the milestone
    rec = _delay(s, title="Survey redo", responsibility="Contractor",
                 event_start="2026-11-04",
                 fragnet=[{"name": "Resurvey", "duration": 2,
                           "pred": "A0004", "succ": "A0006"}])
    r = sr.tia(s, rec)
    assert r["impact_workdays"] == 0 and r["impact_calendar_days"] == 0
    assert not r["fragnet_on_critical"]
    assert any("float" in n for n in r["notes"])
    # Rebar has 4 workdays of float: +4 is absorbed, +5 is one day late
    rb = _delay(s, title="Rebar late", event_start="2026-11-10",
                affected=[{"id": "Rebar", "days": 4}])
    assert sr.tia(s, rb)["impact_workdays"] == 0
    rb["affected"] = [{"id": "A0005", "days": 5}]
    rb = s.save_record("delay", rb)
    assert sr.tia(s, rb)["impact_workdays"] == 1
    bad = _delay(s, title="Bad refs", event_start="2026-11-10",
                 fragnet=[{"name": "X", "duration": 1, "pred": "A0099"}],
                 affected=[{"id": "Nope", "days": 2}])
    notes = " ".join(sr.tia(s, bad)["notes"])
    assert "A0099" in notes and "Nope" in notes


def test_concurrency_and_notice(tmp_path, monkeypatch):
    s = _store(tmp_path, monkeypatch)
    o = _delay(s, title="Owner hold", responsibility="Owner",
               event_start="2026-11-05", event_end="2026-11-10",
               notice_date="2026-11-12")
    c = _delay(s, title="Crew short", responsibility="Contractor",
               event_start="2026-11-09", event_end="2026-11-12",
               notice_date="2026-11-10")
    _delay(s, title="Rain", responsibility="Force majeure / weather",
           event_start="2026-11-05", event_end="2026-11-20")
    _delay(s, title="Later sub", responsibility="Contractor",
           event_start="2026-11-11")
    _delay(s, title="Dropped", responsibility="Contractor",
           event_start="2026-11-06", status="Withdrawn")
    cc = sr.concurrency(s)
    assert len(cc) == 1
    assert (cc[0]["owner"], cc[0]["contractor"]) == (o["_no"], c["_no"])
    assert (cc[0]["start"], cc[0]["end"], cc[0]["days"]) == \
        (D("2026-11-09"), D("2026-11-10"), 2)
    n = sr.notice_late(s, o)                     # 7 days: just in time
    assert (n["late"], n["days"], n["limit"], n["given"]) == \
        (False, 7, 7, True)
    assert "contract governs" in n["note"]
    o["notice_date"] = "2026-11-13"                     # 8 days
    assert sr.notice_late(s, o)["late"]
    assert not sr.notice_late(s, c)["late"]
    s.set_setting("notice_days", 14)
    assert not sr.notice_late(s, o)["late"]
    s.set_setting("notice_days", 0)
    late = sr.notice_late(s, {"event_start": "2026-11-05"},
                          today=D("2026-11-06"))
    assert late["late"] and not late["given"]


def test_windows(tmp_path, monkeypatch):
    s = _store(tmp_path, monkeypatch)
    sr.snapshot(s, "baseline", now=NOW)
    ev = _delay(s, title="Owner change", responsibility="Owner",
                event_start="2026-11-02")
    _delay(s, title="Before the baseline", event_start="2026-09-15")
    s.set_setting("data_date", "2026-11-03")
    _edit(s, "Mobilize", actual_start="2026-11-02",
          actual_finish="2026-11-03", status="Complete", percent=100)
    _edit(s, "Footings", duration=6)
    sr.snapshot(s, now=NOW)
    s.set_setting("data_date", "2026-11-10")
    sr.snapshot(s, now=NOW)
    w = sr.windows(s)
    assert len(w) == 2
    assert (w[0]["from"], w[0]["to"]) == (1, 2)
    assert (w[0]["start"], w[0]["end"]) == ("2026-10-01", "2026-11-03")
    assert (w[0]["finish_before"], w[0]["finish_after"]) == \
        ("2026-11-23", "2026-11-25")
    assert w[0]["workdays"] == 2 and w[0]["calendar_days"] == 2
    assert w[0]["events"] == [ev["_no"]]
    assert w[1]["events"] == []
    assert sr.verify(s) == []


def test_delay_tool_registered():
    t = schema.TOOLS["delay"]
    assert (t["title"], t["one"], t["group"], t["prefix"]) == \
        ("Delay Log", "Delay event", "Project", "D-")
    assert t["icon"] == schema.TOOLS["issue"]["icon"]
    keys = {f["key"] for f in t["fields"]}
    assert keys >= {"title", "description", "cause", "responsibility",
                    "event_start", "event_end", "notice_date", "notice_to",
                    "notice_ref", "affected", "fragnet", "refs",
                    "days_requested", "days_granted", "cost", "status"}
    f = schema.field("delay", "cause")
    assert f["type"] == "choice" and "Weather beyond normal" in f["options"]
    assert schema.field("delay", "responsibility")["options"] == \
        ["Owner", "Contractor", "Third party", "Force majeure / weather",
         "Concurrent / shared"]
    assert schema.field("delay", "cost")["type"] == "money"
    assert schema.field("delay", "description")["type"] == "long"
    frag = schema.field("delay", "fragnet")
    assert frag["type"] == "lines" and \
        [c[0] for c in frag["cols"]] == ["name", "duration", "pred", "succ"]
    assert [c[0] for c in schema.field("delay", "affected")["cols"]] == \
        ["id", "days", "note"]
    assert t["closed"] == ["Granted", "Denied", "Withdrawn"]
    assert "Notice Given" in t["statuses"]
    assert set(t["columns"]) - {"_no"} <= keys
    assert schema.defaults("delay")["status"] == "Open"
    assert not schema.is_closed("delay", {"status": "Submitted"})
    assert schema.is_closed("delay", {"status": "Granted"})


def test_numbering(tmp_path, monkeypatch):
    s = _store(tmp_path, monkeypatch)
    assert _delay(s, event_start="2026-11-05")["_no"] == "D-001"
    assert schedule.compute(s)["finish"] == D("2026-11-23")


def test_anchor_catches_a_full_rewrite_and_a_dropped_update(tmp_path,
                                                             monkeypatch):
    """Review 0.12.34 #4: the head hash and count are kept outside the
    chain, so re-hashing every update or dropping the last one shows."""
    s = _store(tmp_path, monkeypatch)
    sr.snapshot(s, "baseline", now=NOW)
    _edit(s, "Footings", duration=6)
    b = sr.snapshot(s, now=NOW)
    a = sr.anchor(s)
    assert (a["count"], a["head"]) == (2, b["hash"])
    assert sr.verify(s) == [] and sr.verify_notes(s) == []
    good = sr.updates(s)
    # rewrite every update with fresh hashes: the chain itself checks out
    log = sr.updates(s)
    log[0]["finish"] = "2026-12-01"
    prev = ""
    for e in log:
        e["prev_hash"] = prev
        e["hash"] = sr._hash(e)
        prev = e["hash"]
    s.set_setting(sr.SETTING, log)
    probs = sr.verify(s)
    assert any("head hash does not match the recorded head" in p.lower()
               for p in probs), probs
    # drop the last update (the rest untouched)
    s.set_setting(sr.SETTING, good[:-1])
    probs = sr.verify(s)
    assert any("chain shorter than recorded (1 vs 2)" in p.lower()
               for p in probs), probs
    # removing the anchor after updates were anchored is reported too
    s.set_setting(sr.SETTING, good)
    assert sr.verify(s) == []
    s.set_setting(sr.ANCHOR, None)
    assert any("recorded head" in p for p in sr.verify(s))


def test_unanchored_record_from_before_the_upgrade(tmp_path, monkeypatch):
    """A job saved before anchoring: verify() doesn't call it tampering;
    it says 'not anchored yet', and the next update anchors it."""
    s = _store(tmp_path, monkeypatch)
    sr.snapshot(s, "baseline", now=NOW)
    sr.snapshot(s, now=NOW)
    old = []
    for e in sr.updates(s):              # as 0.12.35 wrote them
        e.pop("anchored", None)
        e["prev_hash"] = old[-1]["hash"] if old else ""
        e["hash"] = sr._hash(e)
        old.append(e)
    s.set_setting(sr.SETTING, old)
    s.set_setting(sr.ANCHOR, None)
    assert sr.anchor(s) is None
    assert sr.verify(s) == []
    notes = sr.verify_notes(s)
    assert notes and "not anchored yet" in notes[0]
    c = sr.snapshot(s, now=NOW)
    assert sr.anchor(s)["count"] == 3 and sr.anchor(s)["head"] == c["hash"]
    assert sr.verify(s) == [] and sr.verify_notes(s) == []


def test_tia_refuses_a_negative_impact(tmp_path, monkeypatch):
    """Review 0.12.34 #5: -10 workdays is refused (not 'absorbed by
    float'), 0 is accepted, +5 on critical work adds 5."""
    from app.pm import actions
    s = _store(tmp_path, monkeypatch)
    sr.snapshot(s, now=NOW)
    neg = _delay(s, title="Shorter", event_start="2026-11-10",
                 affected=[{"id": "A0003", "days": -10}])
    try:
        sr.tia(s, neg)
        assert False, "a negative impact was accepted"
    except ValueError as e:
        assert "below 0" in str(e) and "A0003" in str(e)
    assert sr.check_inputs(neg)
    frag = _delay(s, title="Neg fragnet", event_start="2026-11-10",
                  fragnet=[{"name": "Undo", "duration": -10,
                            "pred": "A0002", "succ": "A0003"}])
    try:
        sr.tia(s, frag)
        assert False, "a negative fragnet was accepted"
    except ValueError as e:
        assert "Undo" in str(e) and "below 0" in str(e)
    zero = _delay(s, title="Nothing", event_start="2026-11-10",
                  affected=[{"id": "A0003", "days": 0}])
    r0 = sr.tia(s, zero)
    assert r0["impact_workdays"] == 0
    five = _delay(s, title="Five", event_start="2026-11-10",
                  affected=[{"id": "A0003", "days": 5}])
    r5 = sr.tia(s, five)
    assert r5["finish_before"] == D("2026-11-23")
    assert r5["impact_workdays"] == 5
    # tia_all reports the refused one instead of failing
    allr = {x["_no"]: x for x in sr.tia_all(s)}
    assert "below 0" in allr[neg["_no"]]["error"]
    assert allr[neg["_no"]]["impact_workdays"] is None
    assert allr[five["_no"]]["impact_workdays"] == 5
    # the Delay Log action says why and leaves the event alone
    said = []
    ctx = actions.Ctx(s, ask=lambda *a: None, notify=said.append)
    assert actions.run(ctx, "delay", neg, "Time Impact Analysis") is None
    assert said and "below 0" in said[0]
    assert s.get("delay", neg["_id"])["status"] == "Open"


def test_notice_period_setting(tmp_path, monkeypatch):
    """Review 0.12.34 #2: notice period 21 days - notice on day 15 is on
    time; the default 7 days makes it late."""
    s = _store(tmp_path, monkeypatch)
    rec = _delay(s, title="Owner hold", responsibility="Owner",
                 event_start="2026-11-02", notice_date="2026-11-17")
    n = sr.notice_late(s, rec)
    assert (n["days"], n["limit"], n["late"]) == (15, 7, True)
    s.set_setting("notice_days", 21)
    n = sr.notice_late(s, rec)
    assert (n["days"], n["limit"], n["late"]) == (15, 21, False)
    s.set_setting("notice_days", "")                 # blank = default
    assert sr.notice_late(s, rec)["limit"] == 7
