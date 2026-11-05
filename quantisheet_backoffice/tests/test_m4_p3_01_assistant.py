"""Brief Phase 3, P3-01 AI assistant on a local model: tests 1.1-1.3, plus
findings, reminders that are never sent, and the local-only rules.
Made-up data; the model is a fake local server (ai_fake) or none at all.
Decision 6.3 = A (Jon, Oct 22, 2026): with no model the assistant says 'AI
is unavailable' and offers a plain search; it never answers by keywords."""
import socket

import pytest

from quantisheet_backoffice import (actions, approvals, assistant, interface,
                                    jobs, localai, security, timeentry)

from . import conftest
from .ai_fake import router
from .helpers import BASE, stage
from .m3_helpers import approve_time, second_job, snapshot_with

LAST_WEEK = ["2026-10-12", "2026-10-13", "2026-10-14", "2026-10-15",
             "2026-10-16"]                     # today is Thu 2026-10-22
MISSING = {"turned in time": {"tool": "missing_time", "job": "2611",
                              "period": "last week"}}


def _crew(office, job):
    w = {n: timeentry.add_worker(office, n, "LAB")
         for n in ("M. Chen", "J. Ruiz", "T. Okafor", "L. Novak")}
    ids = []
    for d in LAST_WEEK:
        for n in ("M. Chen", "L. Novak"):
            ids.append(timeentry.add_line(office, w[n], d, job, "03-3000",
                                          "8"))
        if d != "2026-10-14":
            ids.append(timeentry.add_line(office, w["J. Ruiz"], d, job,
                                          "03-3000", "8"))
        tid = timeentry.add_line(office, w["T. Okafor"], d, job, "03-3000",
                                 "8")
        if d != "2026-10-15":
            ids.append(tid)                    # 10-15 stays Draft
    approve_time(office, ids)
    other = second_job(office)
    k = timeentry.add_worker(office, "K. Ito", "LAB")    # other job only
    timeentry.add_line(office, k, "2026-10-05", other, "03-3000", "8")
    return w


def test_1_1_missing_time_last_week_on_job_matches_report(office, job,
                                                          fake_ollama):
    _crew(office, job)
    rep = timeentry.missing_time_report(office, "2026-10-17", job)
    assert rep == {"J. Ruiz": ["2026-10-14"], "T. Okafor": ["2026-10-15"]}
    fake_ollama.reply = router(MISSING)
    a = assistant.ask(office, "Who hasn't turned in time for last week on "
                              "job 2611?")
    assert a["tool"] == "missing_time" and a["routed_by"] == "local model"
    assert a["data"] == rep
    assert "J. Ruiz" in a["text"] and "T. Okafor" in a["text"]
    for n in ("M. Chen", "L. Novak", "K. Ito"):
        assert n not in a["text"]
    q = office.db.get("ai_actions", a["question_id"])
    assert q["kind"] == "question" and q["tool"] == "missing_time"
    assert q["model"] == "llama3.2:latest" or q["model"] == "llama3.2"
    assert q["model_version"].startswith("0123456789ab")
    # no worker name went to the model
    sent = fake_ollama.sent_text()
    for n in ("Chen", "Ruiz", "Okafor", "Novak", "Ito"):
        assert n not in sent


def test_1_2_no_outbound_connection_but_localhost(office, job):
    for url in ("http://203.0.113.9:11434", "https://ai.example.com",
                "http://10.0.0.5:11434", "ftp://localhost"):
        with pytest.raises(localai.NotLocalError):
            localai.configure(url=url)
        with pytest.raises(localai.NotLocalError):
            localai.Client(url=url, model="m")
    assert localai.check_local("http://localhost:11434")
    assert localai.check_local("http://127.0.0.1:11434")
    assert localai.check_local("http://[::1]:11434")
    # the guard itself refuses a real outside connection (and records it)
    n = len(conftest.GUARD["net"])
    s = socket.socket()
    try:
        with pytest.raises(AssertionError, match="only this PC"):
            s.connect(("203.0.113.9", 9))
    finally:
        s.close()
    assert conftest.GUARD["net"][n:] == ["203.0.113.9"]
    del conftest.GUARD["net"][n:]


def test_1_2_redirect_to_an_outside_host_is_refused(office, fake_ollama):
    """A local server answering 302 -> another host: not followed."""
    fake_ollama.redirect_to = "http://203.0.113.9"
    c = localai.Client()
    before = len(conftest.GUARD["net"])
    with pytest.raises(localai.AIUnavailable, match="redirect"):
        c.chat(office, "system", "hello")
    with pytest.raises(localai.AIUnavailable, match="redirect"):
        c.models()
    assert c.available() is False
    assert len(conftest.GUARD["net"]) == before        # never connected
    assert all(p.startswith(("/api/", "/v1/")) for _, p, _ in
               fake_ollama.requests)


def test_1_2_unplugged_with_no_model_says_unavailable(office, job):
    """Decision 6.3 = A: no keyword fallback; a plain search instead."""
    _crew(office, job)
    localai.configure(url="http://127.0.0.1:9", model="llama3.2")  # dead
    before = len(conftest.GUARD["net"])
    a = assistant.ask(office, "Who hasn't turned in time for last week on "
                              "job 2611?")
    assert a["tool"] == "unavailable" and a["routed_by"] == "none"
    assert "AI is unavailable" in a["text"]
    assert "J. Ruiz" not in a["text"] and a.get("data") is None
    assert any(x["type"] == "job" for x in a["search"])
    assert assistant.findings(office)                  # not AI; still works
    assert len(conftest.GUARD["net"]) == before


def _job_with_2000(office):
    s = snapshot_with(stage(1), cost_codes=BASE["cost_codes"] + [
        {"code": "03-2000", "description": "Forming", "category": "L"}])
    return jobs.import_snapshot(office, interface.load_snapshot(s)).job_id


def _audit_actions(office, aid):
    return [r["action"] for r in security.audit_rows(
        office.db, record_type="ai_action") if r["record_id"] == str(aid)]


def test_1_3_recode_4h_apply_then_undo_both_in_audit(office):
    job = _job_with_2000(office)
    w = timeentry.add_worker(office, "M. Chen", "LAB")
    lid = timeentry.add_line(office, w, "2026-10-19", job, "03-3000", "8")
    aid = actions.propose(office, "recode_time", {
        "line_id": lid, "hours": "4", "to_code": "03-2000"})
    a = actions.get(office, aid)
    assert a["status"] == "proposed"
    assert a["before"]["hours"] == "8.00" and a["before"]["cost_code"] == \
        "03-3000"
    assert a["after"]["lines"] == [{"cost_code": "03-3000", "hours": "4.00"},
                                   {"cost_code": "03-2000", "hours": "4.00"}]
    assert office.db.get("time_lines", lid)["hours"] == 800
    actions.apply(office, aid)
    got = sorted((r["cost_code"], r["hours"]) for r in office.db.rows(
        "SELECT * FROM time_lines WHERE worker_id = ? AND deleted = 0", (w,)))
    assert got == [("03-2000", 400), ("03-3000", 400)]
    actions.undo(office, aid, "wrong week")
    got = sorted((r["cost_code"], r["hours"]) for r in office.db.rows(
        "SELECT * FROM time_lines WHERE worker_id = ? AND deleted = 0", (w,)))
    assert got == [("03-3000", 800)]
    acts = _audit_actions(office, aid)
    assert "assistant applied" in acts and "assistant undone" in acts
    assert actions.get(office, aid)["applied_by"] == "Ann Admin"
    assert actions.get(office, aid)["undone_by"] == "Ann Admin"


RECODE_Q = "Recode 4 h from 03-3000 to 03-2000 for M. Chen on 2026-10-19"


def test_1_3_recode_from_a_question_is_only_a_proposal(office, fake_ollama):
    job = _job_with_2000(office)
    w = timeentry.add_worker(office, "M. Chen", "LAB")
    lid = timeentry.add_line(office, w, "2026-10-19", job, "03-3000", "8")
    fake_ollama.reply = router({"recode": {
        "tool": "recode_time", "hours": "4", "from_code": "03-3000",
        "to_code": "03-2000", "worker": "[person]", "date": "2026-10-19"}})
    a = assistant.ask(office, RECODE_Q)
    assert a["tool"] == "recode_time" and "not applied" in a["text"]
    assert "Read two ways" not in a["text"]
    assert office.db.get("time_lines", lid)["cost_code"] == "03-3000"
    assert [p["id"] for p in actions.pending(office)] == [a["action_id"]]
    assert "M. Chen" not in fake_ollama.sent_text()
    actions.dismiss(office, a["action_id"], "no")
    assert actions.pending(office) == []


def test_1_3_model_reading_wins_and_both_readings_are_shown(office,
                                                            fake_ollama):
    """When the model and the pattern read the hours differently the
    model's is used (it reads the whole sentence) and both are shown."""
    job = _job_with_2000(office)
    w = timeentry.add_worker(office, "M. Chen", "LAB")
    timeentry.add_line(office, w, "2026-10-19", job, "03-3000", "8")
    fake_ollama.reply = router({"recode": {
        "tool": "recode_time", "hours": "2", "from_code": "03-3000",
        "to_code": "03-2000", "date": "2026-10-19"}})
    a = assistant.ask(office, RECODE_Q)
    assert "Read two ways (hours: model 2, pattern 4)" in a["text"]
    after = actions.get(office, a["action_id"])["after"]["lines"]
    assert {"cost_code": "03-2000", "hours": "2.00"} in after


def test_1_3_recoding_an_approved_line_needs_approval_again(office):
    job = _job_with_2000(office)
    w = timeentry.add_worker(office, "M. Chen", "LAB")
    lid = timeentry.add_line(office, w, "2026-10-19", job, "03-3000", "8")
    approve_time(office, [lid])
    assert office.db.get("time_lines", lid)["status"] == "Approved"
    aid = actions.propose(office, "recode_time", {
        "line_id": lid, "hours": "4", "to_code": "03-2000"})
    actions.apply(office, aid)
    rows = office.db.rows("SELECT * FROM time_lines WHERE worker_id = ? AND "
                          "deleted = 0 ORDER BY id", (w,))
    assert [r["status"] for r in rows] == ["Submitted", "Submitted"]
    for r in rows:
        req = approvals.request(office, "time_line", r["id"])
        assert req and req["status"] == "pending"
    approve_time(office, [r["id"] for r in rows])
    assert {office.db.get("time_lines", r["id"])["status"]
            for r in rows} == {"Approved"}


def test_recode_refused_on_locked_week_and_without_rights(office):
    job = _job_with_2000(office)
    w = timeentry.add_worker(office, "M. Chen", "LAB")
    lid = timeentry.add_line(office, w, "2026-10-19", job, "03-3000", "8")
    with pytest.raises(actions.ActionError, match="not a cost code"):
        actions.propose(office, "recode_time", {"line_id": lid, "hours": "4",
                                                "to_code": "99-9999"})
    aid = actions.propose(office, "recode_time", {
        "line_id": lid, "hours": "8", "to_code": "03-2000"})
    office.act_as("viewer@bo.test")
    with pytest.raises(security.Denied):
        actions.apply(office, aid)
    office.act_as("admin@bo.test")
    timeentry.lock_week(office, "2026-10-24")
    with pytest.raises(actions.ActionError, match="locked"):
        actions.apply(office, aid)
    assert office.db.get("time_lines", lid)["cost_code"] == "03-3000"


def test_findings_and_reminders_are_text_only(office, job):
    _crew(office, job)
    f = assistant.findings(office)
    kinds = {x["kind"] for x in f}
    assert "missing_time" in kinds
    mt = next(x for x in f if x["kind"] == "missing_time")
    aid = assistant.draft_reminder(office, mt)
    actions.apply(office, aid)
    a = actions.get(office, aid)
    assert a["kind"] == "reminder" and a["undo"] == {}
    assert "please turn in your time" in a["after"]["text"]


def test_viewer_cannot_use_the_assistant(office):
    office.act_as("viewer@bo.test")
    with pytest.raises(security.Denied):
        assistant.ask(office, "what do we owe vendors?")
