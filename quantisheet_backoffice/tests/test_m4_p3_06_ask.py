"""Addendum P3-06 'Ask the books', tests 6.1-6.3 as the addendum writes
them: the local model only chooses the built-in report (or action) and its
dates and filters; every number comes from the report engine; actions are
a before/after list applied only on Apply and undone in one step.
Decision 6.3 = A (DECIDED, Jon, Oct 22, 2026): with the model stopped the
box says 'AI is unavailable' and offers a plain search - no keyword
fallback - and every report still runs from the menus."""
import re

import pytest

from quantisheet_backoffice import (actions, aicat, appay, assistant,
                                    banking, billing, jobcost, ledger,
                                    localai, payments, reports, security)

from .ai_fake import router
from .helpers import ap_invoice, approve_ap


@pytest.fixture
def full(office):
    office.set_company(accounting_mode="full")
    return office


def _costs(office, job):
    approve_ap(office, ap_invoice(office, "Example Ready-Mix", "RM-90",
                                  "2026-09-15", "1200.00", job_id=job))
    approve_ap(office, ap_invoice(office, "Example Ready-Mix", "RM-91",
                                  "2026-10-03", "500.00", job_id=job))


def _quarter_books(o, job):
    """Something on every P&L line, in and just outside the quarter."""
    for d, amt in (("2026-09-28", "4000.00"), ("2026-10-05", "9000.00")):
        iid = billing.create_other_invoice(o, job, d, [
            {"description": "Work", "amount": amt}],
            customer="Example Owner LLC")
        billing.approve(o, iid)
    _costs(o, job)                                       # COGS Sep + Oct
    for d, acct, amt in (("2026-10-06", "6000", "1500.00"),   # opex
                         ("2026-09-29", "6000", "1500.00"),
                         ("2026-10-07", "8000", "45.10")):    # other exp
        ledger.post_manual(o, d, [{"account": acct,
                                   "debit": int(amt.replace(".", ""))},
                                  {"account": "2800",
                                   "credit": int(amt.replace(".", ""))}],
                           "test")
    ledger.post_manual(o, "2026-10-08", [{"account": "1400", "debit": 1_233},
                                         {"account": "7000",
                                          "credit": 1_233}], "interest")


def test_6_1_this_quarters_pl_equals_the_report_to_the_cent(full, job,
                                                             fake_ollama):
    _quarter_books(full, job)
    fake_ollama.reply = router({"p&l": {"tool": "pl",
                                        "period": "this quarter"}})
    a = assistant.ask(full, "Pull this quarter's P&L")
    assert a["tool"] == "pl" and a["routed_by"] == "local model"
    assert (a["period"]["from"], a["period"]["to"]) == ("2026-10-01",
                                                        "2026-10-22")
    by_hand = reports.profit_and_loss(full, "2026-10-01", "2026-10-22")
    keys = ("revenue", "cogs", "gross_profit", "operating_expenses",
            "operating_income", "other_income", "other_expenses",
            "net_income")
    for k in keys:
        assert a["data"][k] == by_hand[k], k
        assert by_hand[k] != 0, k                 # every line has a value
    assert a["report"] == {"name": "Profit and loss", "from": "2026-10-01",
                           "to": "2026-10-22", "basis": "accrual"}
    assert "Profit and loss" in a["text"]
    assert "2026-10-01 to 2026-10-22" in a["text"]
    for k, label in assistant.PL_LINES:
        from quantisheet_backoffice import cents
        assert f"{label} {cents.fmt(by_hand[k])}" in a["text"]
    assert by_hand["revenue"] == 900_000                 # Sept left out


def _lumber(o):
    b = banking.add_account(o, "Operating - Example Bank", "1000",
                            statement_format="csv")
    rows = [("09/28/2026", "EXAMPLE LUMBER #3", "-50.00"),
            ("10/02/2026", "EXAMPLE LUMBER #12", "-80.00"),
            ("10/09/2026", "EXAMPLE LUMBER #47", "-95.10"),
            ("10/10/2026", "EXAMPLE SIGNS", "-20.00")]
    banking.import_statement(o, b, text="Date,Description,Amount\n" + "".join(
        f'{d},"{p}",{a}\n' for d, p, a in rows), fmt="csv")
    ids = {}
    for ln in banking.review_queue(o, b):
        banking.categorize(o, ln["id"], "6090")
        banking.accept(o, ln["id"])
        ids[ln["payee"]] = ln["id"]
    return b, ids


RECAT = {"recategorize": {"tool": "recategorize", "payee": "Example Lumber",
                          "period": "October",
                          "account": "Job cost - Material"}}


def test_6_2_recategorize_october_lines_preview_apply_one_undo(full,
                                                               fake_ollama):
    b, ids = _lumber(full)
    fake_ollama.reply = router(RECAT)
    tb0 = ledger.trial_balance(full)
    a = assistant.ask(full, "Recategorize all October Example Lumber lines "
                            "to Job cost - Material")
    assert a["tool"] == "recategorize" and "not applied" in a["text"]
    act = actions.get(full, a["action_id"])
    assert [x["payee"] for x in act["before"]] == ["EXAMPLE LUMBER #12",
                                                   "EXAMPLE LUMBER #47"]
    assert {x["account"] for x in act["before"]} == {"6090 Overhead"}
    assert {x["account"] for x in act["after"]["lines"]} == {
        "5020 Job cost - Material"}
    # nothing changes until Apply
    assert ledger.balance(full, "5020") == 0
    assert ledger.trial_balance(full) == tb0
    actions.apply(full, a["action_id"])
    assert ledger.balance(full, "5020") == 17_510
    assert ledger.balance(full, "6090") == 7_000       # Sept + signs stay
    tb = ledger.trial_balance(full)
    assert tb["debits"] == tb["credits"]
    sl = banking.line(full, ids["EXAMPLE LUMBER #47"])
    assert ledger.account(full, sl["account_id"])["number"] == "5020"
    actions.undo(full, a["action_id"], "changed my mind")   # one Undo
    assert ledger.balance(full, "5020") == 0
    assert ledger.balance(full, "6090") == 24_510
    sl = banking.line(full, ids["EXAMPLE LUMBER #47"])
    assert ledger.account(full, sl["account_id"])["number"] == "6090"
    acts = [r["action"] for r in security.audit_rows(
        full.db, record_type="ai_action")
        if r["record_id"] == str(a["action_id"])]
    assert "assistant applied" in acts and "assistant undone" in acts


def test_6_2_the_correction_feeds_similarity(full, fake_ollama):
    b, ids = _lumber(full)
    fake_ollama.reply = router(RECAT)
    actions.apply(full, assistant.ask(
        full, "Recategorize all October Example Lumber lines to Job cost - "
              "Material")["action_id"])
    banking.import_statement(full, b, text="Date,Description,Amount\n"
                             "10/20/2026,EXAMPLE LUMBER #51,-12.00\n",
                             fmt="csv")
    new = [ln for ln in banking.review_queue(full, b)
           if ln["status"] in ("New", "Suggested")][0]
    calls = len(fake_ollama.chats())
    s = aicat.suggest_line(full, new["id"])
    assert s["layer"] == "similar" and len(fake_ollama.chats()) == calls
    assert ledger.account(full, s["account_id"])["number"] == "5020"


def test_6_2_drafted_journal_entry_posts_only_on_apply(full, fake_ollama):
    fake_ollama.reply = router({"journal": {
        "tool": "journal", "date": "2026-10-15", "amount": "250.00",
        "debit_account": "6050", "credit_account": "2800",
        "memo": "October accounting fee"}})
    n0 = full.db.scalar("SELECT COUNT(*) FROM journal_entries")
    a = assistant.ask(full, "Draft a journal entry for the October "
                            "accounting fee")
    assert a["tool"] == "journal" and "not posted" in a["text"]
    assert full.db.scalar("SELECT COUNT(*) FROM journal_entries") == n0
    act = actions.get(full, a["action_id"])
    assert [(x["account"], x["debit"], x["credit"]) for x in
            act["after"]["lines"]] == [("6050", "250.00", "0.00"),
                                       ("2800", "0.00", "250.00")]
    actions.apply(full, a["action_id"])
    assert ledger.balance(full, "6050") == 25_000
    actions.undo(full, a["action_id"])
    assert ledger.balance(full, "6050") == 0


def test_6_2_add_rule_is_a_proposal(full, fake_ollama):
    fake_ollama.reply = router({"rule": {"tool": "add_rule",
                                         "text": "EXAMPLE FUEL",
                                         "account": "6040"}})
    a = assistant.ask(full, "Add a rule: Example Fuel goes to vehicles")
    assert a["tool"] == "add_rule" and "not added" in a["text"]
    assert full.db.rows("SELECT * FROM bank_rules WHERE active = 1") == []
    actions.apply(full, a["action_id"])
    assert len(full.db.rows("SELECT * FROM bank_rules WHERE active = 1")) == 1
    actions.undo(full, a["action_id"])
    assert full.db.rows("SELECT * FROM bank_rules WHERE active = 1") == []


def test_6_3_model_stopped_unavailable_and_reports_still_run(full, job):
    """Decision 6.3 = A: no silent keyword answer."""
    _quarter_books(full, job)
    localai.configure(url="http://127.0.0.1:9", model="llama3.2")  # stopped
    a = assistant.ask(full, "Pull this quarter's P&L")
    assert a["tool"] == "unavailable" and "AI is unavailable" in a["text"]
    assert a.get("data") is None and not re.search(r"\$\d", a["text"])
    s = assistant.ask(full, "Example Ready-Mix")
    assert any(x["label"] == "Vendor Example Ready-Mix" for x in s["search"])
    # every report still runs from the menus (same functions)
    assert reports.profit_and_loss(full, "2026-10-01", "2026-10-22")[
        "revenue"] == 900_000
    tb = ledger.trial_balance(full)
    assert tb["debits"] == tb["credits"]
    assert jobcost.job_cost(full, job)
    assert appay.aging(full, "2026-10-22")["rows"]
    assert payments.aging(full, "2026-10-22")["rows"]
    localai.configure(model="")                           # none installed
    assert assistant.ask(full, "What do we owe vendors?")["tool"] == \
        "unavailable"


def test_model_never_supplies_numbers(office, job, fake_ollama):
    _costs(office, job)
    fake_ollama.reply = lambda body: {
        "tool": "job_cost", "job": "2611", "cost_code": "concrete",
        "period": "last month", "answer": "$999,999.00"}
    a = assistant.ask(office, "How did the clinic's concrete go in money "
                              "terms in the month before this one?")
    assert a["routed_by"] == "local model" and a["tool"] == "job_cost"
    assert a["period"]["label"] == "September 2026"
    assert "$1,200.00" in a["text"] and "999" not in a["text"]
    assert any(r.startswith("ap_line:") for r in a["records"])


def test_personal_data_questions_declined_before_any_model(office, job,
                                                           fake_ollama):
    for q in ("What is Hana Reyes's SSN?", "Show M. Chen's bank account",
              "What's the pay rate for J. Ruiz?", "date of birth of T. Okafor"):
        a = assistant.ask(office, q)
        assert a["tool"] == "declined"
        assert "personal or pay data" in a["text"]
    assert fake_ollama.chats() == []


def test_unknown_tool_no_keyword_fallback_and_rights_kept(office, job,
                                                          fake_ollama):
    fake_ollama.reply = lambda body: {"tool": "delete_everything"}
    a = assistant.ask(office, "What do we owe vendors?")
    assert a["tool"] == "" and "couldn't match" in a["text"]
    assert "search" in a and not re.search(r"\$\d", a["text"])
    office.act_as("viewer@bo.test")
    with pytest.raises(security.Denied):
        assistant.ask(office, "What do we owe vendors?")


def test_typed_ssn_is_scrubbed_before_logging(office, fake_ollama):
    fake_ollama.reply = lambda body: {"tool": ""}
    a = assistant.ask(office, "Who is 900-00-0001 and 000099990001?")
    q = office.db.get("ai_actions", a["question_id"])
    assert "900-00-0001" not in q["question"]
    assert "000099990001" not in q["question"]
    assert "[id]" in q["question"]
    assert "900-00-0001" not in fake_ollama.sent_text()
    localai.configure(model="")
    a = assistant.ask(office, "find 900-00-0001")
    assert "900-00-0001" not in office.db.get("ai_actions",
                                               a["question_id"])["question"]


def test_bad_model_values_are_an_answer_not_a_crash(office, fake_ollama):
    fake_ollama.reply = lambda body: {"tool": "recode_time", "hours": "abc",
                                      "from_code": "03-3000",
                                      "to_code": "03-2000",
                                      "worker": "[person]",
                                      "date": "2026-10-19"}
    from quantisheet_backoffice import timeentry
    from .test_m4_p3_01_assistant import _job_with_2000
    job = _job_with_2000(office)
    w = timeentry.add_worker(office, "M. Chen", "LAB")
    timeentry.add_line(office, w, "2026-10-19", job, "03-3000", "8")
    a = assistant.ask(office, "Recode 4 h from 03-3000 to 03-2000 for "
                              "M. Chen on 2026-10-19")
    assert a["tool"] == "recode_time" and "action_id" not in a
    fake_ollama.reply = lambda body: {"tool": "journal", "amount": "1e999x",
                                      "debit_account": "6050",
                                      "credit_account": "2800"}
    a = assistant.ask(office, "draft an entry")
    assert "action_id" not in a


@pytest.mark.parametrize("words,want", [
    ("last week", ("2026-10-11", "2026-10-17")),
    ("this week", ("2026-10-18", "2026-10-24")),
    ("last month", ("2026-09-01", "2026-09-30")),
    ("this month", ("2026-10-01", "2026-10-22")),
    ("this quarter", ("2026-10-01", "2026-10-22")),
    ("quarter to date", ("2026-10-01", "2026-10-22")),
    ("QTD", ("2026-10-01", "2026-10-22")),
    ("last quarter", ("2026-07-01", "2026-09-30")),
    ("Q3", ("2026-07-01", "2026-09-30")),
    ("in September", ("2026-09-01", "2026-09-30")),
    ("October", ("2026-10-01", "2026-10-31")),
    ("October 2025", ("2025-10-01", "2025-10-31")),
    ("last year", ("2025-01-01", "2025-12-31")),
    ("year to date", ("2026-01-01", "2026-10-22")),
    ("", (None, "2026-10-22")),
    ("as of 2026-10-31", (None, "2026-10-31")),
    ("from 2026-10-05 to 2026-10-01", ("2026-10-01", "2026-10-05")),
])
def test_periods_worked_out_in_code(words, want):
    p = assistant.resolve_period(words)
    assert (p["from"], p["to"]) == want


def test_last_quarter_in_january_is_previous_year():
    from datetime import date
    p = assistant.resolve_period("last quarter", date(2027, 1, 15))
    assert (p["from"], p["to"]) == ("2026-10-01", "2026-12-31")
