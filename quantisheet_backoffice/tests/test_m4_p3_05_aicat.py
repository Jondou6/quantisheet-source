"""Addendum P3-05: AI categorization and reconciliation suggestions, tests
5.1-5.6 as the addendum writes them, plus the guard and audit details from
the M4 review. The model is a fake local server; nothing posts until a
person clicks Accept; every suggestion and decision is in ai_log + audit.
All names and numbers are made up (SSN 9xx, EIN 00-, a routing number that
fails the ABA check)."""
import pytest

from quantisheet_backoffice import (aicat, aiguard, aitrail, ap, appay,
                                    banking, billing, hr, ledger, localai,
                                    payments, reconcile, security,
                                    timeentry)

from . import conftest
from .helpers import ap_invoice, approve_ap


@pytest.fixture
def full(office):
    office.set_company(accounting_mode="full")
    return office


def _bank(o, rows):
    b = banking.add_account(o, "Operating - Example Bank", "1000",
                            statement_format="csv")
    text = "Date,Description,Amount\n" + "".join(
        f'{d},"{p}",{a}\n' for d, p, a in rows)
    banking.import_statement(o, b, text=text, fmt="csv")
    return b, {ln["payee"]: ln["id"] for ln in banking.review_queue(o, b)}


def _entries(o):
    return o.db.scalar("SELECT COUNT(*) FROM journal_entries")


def _audit(o, action):
    return security.audit_rows(o.db, action=action)


def _tb(o):
    tb = ledger.trial_balance(o)
    return (tb["debits"], tb["credits"],
            sorted((r["number"], r["balance"]) for r in tb["rows"])
            if "rows" in tb else None)


PAYEES = ["EXAMPLE PAVING", "EXAMPLE SIGNS", "EXAMPLE GLASS", "EXAMPLE TILE",
          "EXAMPLE ROOFING", "EXAMPLE PLUMBING", "EXAMPLE STEEL",
          "EXAMPLE PAINT", "EXAMPLE FENCE", "EXAMPLE DOORS",
          "EXAMPLE CRANE", "EXAMPLE SURVEY", "EXAMPLE PRINT",
          "EXAMPLE TOWING", "EXAMPLE SAFETY", "EXAMPLE LANDSCAPE",
          "EXAMPLE PORTA", "EXAMPLE DUMPSTER", "EXAMPLE FUEL",
          "EXAMPLE OFFICE SUPPLY", "EXAMPLE HARDWARE", "EXAMPLE INSULATION",
          "EXAMPLE MASONRY", "EXAMPLE CABINETS", "EXAMPLE CONCRETE PUMP",
          "EXAMPLE WATER UTILITY", "EXAMPLE POWER UTILITY",
          "EXAMPLE PHONE CO", "EXAMPLE INSURANCE", "EXAMPLE TRAINING"]


def test_5_1_unplugged_30_lines_suggested_by_the_local_model(full,
                                                             fake_ollama):
    """Network unplugged: 30 uncategorized lines get suggestions from the
    local model; the socket guard (conftest) sees no connection except
    localhost."""
    assert len(PAYEES) == 30
    rows = [(f"10/{1 + i % 20:02d}/2026", p, f"-{10 + i}.25")
            for i, p in enumerate(PAYEES)]
    b, ids = _bank(full, rows)
    fake_ollama.reply = lambda body: {"account": "6090", "confidence": 0.7,
                                      "reason": "general overhead"}
    before = list(conftest.GUARD["net"])
    n = aicat.suggest_queue(full, b)
    assert n["model_available"] and n["model"] == 30 and n["none"] == 0
    assert len(fake_ollama.chats()) == 30
    for lid in ids.values():
        s = banking.line(full, lid)["suggestion"]
        assert s["kind"] == "ai" and s["layer"] == "model"
        assert banking.line(full, lid)["status"] == "Suggested"
    assert conftest.GUARD["net"] == before == []       # localhost only
    hosts = {r[1] for r in fake_ollama.requests}
    assert hosts <= {"/api/tags", "/api/chat"}


def test_5_2_tb_unchanged_accept_posts_one_audit_then_undo(full,
                                                           fake_ollama):
    b, ids = _bank(full, [("10/07/2026", "EXAMPLE POWER UTILITY", "-412.33"),
                          ("10/08/2026", "EXAMPLE WATER UTILITY", "-55.00")])
    fake_ollama.reply = lambda body: {"account": "6010", "confidence": 0.92,
                                      "reason": "utility bill"}
    tb0, n0 = _tb(full), _entries(full)
    n = aicat.suggest_queue(full, b)
    assert n["model"] == 2
    assert _tb(full) == tb0 and _entries(full) == n0     # nothing posted
    lid = ids["EXAMPLE POWER UTILITY"]
    s = banking.line(full, lid)["suggestion"]
    # what the model was shown: date, amount, cleaned payee, the chart
    sent = fake_ollama.chats()[0]
    assert sent["model"] == "llama3.2" and sent["options"]["temperature"] == 0
    txt = sent["messages"][1]["content"]
    assert "6010 Overhead - Utilities" in txt and "2026-10-07" in txt
    assert "412.33" in txt and "EXAMPLE POWER UTILITY" in txt
    assert "1000 Operating bank" not in txt          # bank isn't a choice
    assert banking.accept_all_suggested(full, b) == []  # AI: own click
    eid = banking.accept(full, lid)
    assert _entries(full) == n0 + 1
    got = sorted((ledger.account(full, ln["account_id"])["number"],
                  ln["debit"], ln["credit"])
                 for ln in ledger.entry(full, eid)["lines"])
    assert got == [("1000", 0, 41_233), ("6010", 41_233, 0)]
    log = aitrail.get(full, s["ai_log_id"])
    assert log["status"] == "accepted" and log["entry_id"] == eid
    assert log["model"] == "llama3.2"
    assert log["model_version"].startswith("0123456789ab")
    assert log["proposal"]["account_id"] == s["account_id"]
    assert log["confidence"] == "0.92" and log["decided_by"] == "Ann Admin"
    assert log["input_hash"]
    assert _audit(full, "ai accepted")
    rev = aicat.undo_accept(full, lid, "wrong account")
    assert ledger.entry(full, eid)["reversed_by_id"] == rev
    assert ledger.balance(full, "6010") == 0
    assert banking.line(full, lid)["status"] == "New"
    assert aitrail.get(full, s["ai_log_id"])["status"] == "undone"
    tb = ledger.trial_balance(full)
    assert tb["debits"] == tb["credits"]


def test_5_3_user_rule_wins_and_user_categorized_line_never_changes(
        full, fake_ollama):
    banking.add_rule(full, "EXAMPLE FUEL", "6040")
    b, ids = _bank(full, [("10/05/2026", "EXAMPLE FUEL 57", "-61.20"),
                          ("10/06/2026", "EXAMPLE TRAINING", "-150.00")])
    fake_ollama.reply = lambda body: {"account": "6090", "confidence": 0.99}
    banking.categorize(full, ids["EXAMPLE TRAINING"], "6050")
    aicat.suggest_queue(full, b)
    fuel = banking.line(full, ids["EXAMPLE FUEL 57"])
    assert fuel["suggestion"]["kind"] == "rule"
    assert ledger.account(full, fuel["suggestion"]["account_id"])[
        "number"] == "6040"
    tr = banking.line(full, ids["EXAMPLE TRAINING"])
    assert tr["user_categorized"] == 1
    assert ledger.account(full, tr["account_id"])["number"] == "6050"
    assert tr["suggestion"]["kind"] != "ai"
    assert fake_ollama.chats() == []       # neither line asked the model
    assert aicat.suggest_line(full, ids["EXAMPLE TRAINING"])["kind"] != "ai"
    assert fake_ollama.chats() == []


def test_5_4_correction_then_similarity_with_zero_model_calls(full,
                                                              fake_ollama):
    b, ids = _bank(full, [("10/02/2026", "EXAMPLE LUMBER #12", "-80.00"),
                          ("10/09/2026", "EXAMPLE LUMBER #47", "-95.10")])
    fake_ollama.reply = lambda body: {"account": "6090", "confidence": 0.6,
                                      "reason": "overhead"}
    s1 = aicat.suggest_line(full, ids["EXAMPLE LUMBER #12"])
    assert s1["layer"] == "model"
    assert ledger.account(full, s1["account_id"])["number"] == "6090"
    banking.categorize(full, ids["EXAMPLE LUMBER #12"], "5020")  # corrected
    assert aitrail.get(full, s1["ai_log_id"])["status"] == "corrected"
    calls = len(fake_ollama.chats())
    s2 = aicat.suggest_line(full, ids["EXAMPLE LUMBER #47"])
    assert len(fake_ollama.chats()) == calls            # 0 model calls
    assert s2["kind"] == "ai" and s2["layer"] == "similar"
    a = ledger.account(full, s2["account_id"])
    assert (a["number"], a["name"]) == ("5020", "Job cost - Material")
    assert "EXAMPLE LUMBER #12" in s2["reason"]


def _ar_paid(o, n, amount):
    iid = billing.create_other_invoice(o, None, "2026-10-01",
                                       [{"description": f"Work {n}",
                                         "amount": amount}],
                                       customer="Example Owner LLC")
    billing.approve(o, iid)
    return payments.receive(o, "Example Owner LLC", f"2026-10-0{n + 1}",
                            amount, reference=f"CHK 70{n}",
                            applications=[(iid, amount)])["payment_id"]


def _bill_paid(o, n, amount):
    iid = ap_invoice(o, "Example Supply Co", f"ES-{n}", "2026-10-01", amount)
    approve_ap(o, iid)
    who = o.user
    o.act_as("ap@bo.test")
    appay.pay(o, ap.invoice(o, iid)["vendor_id"], f"2026-10-1{n}",
              [(iid, amount)], reference=f"50{n}")
    o.act_as(who["id"])


def test_5_5_three_deposits_three_bill_payments_six_matches(full):
    b = banking.add_account(full, "Operating - Example Bank", "1000",
                            statement_format="csv")
    for n, a in ((1, "1000.00"), (2, "2000.00"), (3, "3000.00")):
        _ar_paid(full, n, a)
    for n, a in ((1, "100.00"), (2, "200.00"), (3, "300.00")):
        _bill_paid(full, n, a)
    text = "Date,Description,Amount\n" + "".join([
        "10/03/2026,DEPOSIT,1000.00\n", "10/04/2026,DEPOSIT,2000.00\n",
        "10/05/2026,DEPOSIT,3000.00\n", "10/12/2026,CHECK 501,-100.00\n",
        "10/13/2026,CHECK 502,-200.00\n", "10/14/2026,CHECK 503,-300.00\n"])
    banking.import_statement(full, b, text=text, fmt="csv")
    lines = banking.review_queue(full, b)
    assert [ln["suggestion"]["kind"] for ln in lines] == ["match"] * 6
    for ln in lines:
        banking.accept(full, ln["id"])
    rid = reconcile.start(full, b, "2026-10-31", "5400.00", beginning="0")
    n_log = full.db.scalar("SELECT COUNT(*) FROM ai_log")
    r = aicat.recon_suggestions(full, rid)       # pure: a refresh
    assert full.db.scalar("SELECT COUNT(*) FROM ai_log") == n_log
    r = aicat.run_recon_suggestions(full, rid)   # the user's click
    assert len(r["suggestions"]) == 6
    assert full.db.scalar("SELECT COUNT(*) FROM ai_log") == n_log + 6
    aicat.run_recon_suggestions(full, rid)       # again: not logged twice
    assert full.db.scalar("SELECT COUNT(*) FROM ai_log") == n_log + 6
    assert reconcile.status(full, rid)["cleared"] == 0     # nothing ticked
    st = aicat.apply_recon(full, rid, [s["ai_log_id"] for s in
                                       r["suggestions"]])
    assert st["difference_text"] == "$0.00"
    assert st["label"] == "Ready to finish"
    assert reconcile.status(full, rid)["status"] == "Open"  # not finished
    reconcile.finish(full, rid)                  # the user's Finish click
    assert reconcile.status(full, rid)["status"] == "Finished"
    assert [x["status"] for x in aitrail.history(full, "reconciliation",
                                                 rid)] == ["accepted"] * 6


SSN, ROUTING, ACCT, DOB = "900-00-0001", "999999999", "000099990001", \
    "1985-03-12"
TIN, VBANK = "00-0000001", "000077770002"
PHONE, EMAIL = "555-0100-777", "hana.r@example.test"
ADDRESS = "12 Example Lane\nSpringfield, ZZ 00001"


def test_fake_numbers_are_obviously_fake():
    d = [int(c) for c in ROUTING]
    assert (3 * (d[0] + d[3] + d[6]) + 7 * (d[1] + d[4] + d[7]) +
            d[2] + d[5] + d[8]) % 10 != 0            # fails the ABA check
    assert SSN.startswith("9") and TIN.startswith("00")


def _people(o):
    hr.add_employee(o, "Hana Reyes", "E-100", "2024-02-01", ssn=SSN,
                    bank_routing=ROUTING, bank_account=ACCT, dob=DOB,
                    phone=PHONE, email=EMAIL, address=ADDRESS)
    timeentry.add_worker(o, "Kofi Ito", "LAB")          # worker only
    timeentry.add_worker(o, "Ann", "LAB")               # one-word name
    ap.add_vendor(o, "Example Paint", tax_id=TIN, bank=VBANK)


def test_5_6_no_ssn_bank_or_employee_name_reaches_the_model(full,
                                                            fake_ollama):
    _people(full)
    b, ids = _bank(full, [
        ("10/07/2026", f"REIMB HANA REYES {ACCT}", "-88.00"),
        ("10/08/2026", f"PAYROLL ADJ {SSN} RT {ROUTING}", "-10.00"),
        ("10/09/2026", f"EXAMPLE PAINT TIN {TIN} ACH {VBANK}", "-300.00"),
        ("10/10/2026", "TRANSFER REYES, HANA", "-20.00"),
        ("10/11/2026", "CHECK REYES H", "-30.00"),
        ("10/12/2026", "MILEAGE KOFI ITO", "-40.00"),
        ("10/13/2026", f"REFUND {PHONE} {EMAIL}", "-50.00"),
        ("10/14/2026", "SHIP TO 12 EXAMPLE LANE", "-60.00"),
        ("10/15/2026", "ANNUAL FEE EXAMPLE BANK", "-70.00"),
        ("10/16/2026", "LUNCH ANN", "-80.00")])
    fake_ollama.reply = lambda body: {"account": "6090", "confidence": 0.6}
    aicat.suggest_queue(full, b)
    assert len(fake_ollama.chats()) == 10
    sent = fake_ollama.sent_text()
    for bad in (SSN, "900000001", ROUTING, ACCT, DOB, TIN, "000000001",
                VBANK, PHONE, "5550100777", EMAIL, "12 Example Lane"):
        assert bad.lower() not in sent.lower()
    low = sent.lower()
    for name in ("hana", "reyes", "kofi", "ito"):
        assert f" {name}" not in low and f"{name} " not in low
    assert "LUNCH [person]" in sent or "LUNCH" not in sent
    assert "ANNUAL FEE" in sent            # 'Ann' never mangles ANNUAL


@pytest.mark.parametrize("text,want", [
    ("Hana Reyes lunch", "[person] lunch"),
    ("TRANSFER REYES, HANA", "TRANSFER [person]"),
    ("CHECK REYES H 77", "CHECK [person] 77"),
    ("paid H. Reyes", "paid [person]"),
    ("MILEAGE KOFI ITO", "MILEAGE [person]"),
    ("ANNUAL FEE", "ANNUAL FEE"),
    ("lunch with ann", "lunch with [person]"),
    ("REYES HARDWARE", "REYES HARDWARE"),
])
def test_name_forms_and_word_boundaries(full, text, want):
    _people(full)
    assert aiguard.scrub(text, aiguard.protected_values(full)) == want


def test_5_6_a_prompt_still_holding_pii_is_not_sent(full, fake_ollama,
                                                    monkeypatch):
    _people(full)
    monkeypatch.setattr(aiguard, "scrub", lambda text, values=None: text)
    c = localai.Client()
    for text in (f"line {SSN}", f"acct {ACCT}", "Hana Reyes lunch",
                 f"born {DOB}", f"vendor {TIN}", "Reyes, Hana",
                 "Kofi Ito mileage", f"call {PHONE}", f"mail {EMAIL}"):
        with pytest.raises(aiguard.PIIBlocked):
            c.chat(full, "system", text)
    assert fake_ollama.chats() == []


def test_bulk_accept_at_threshold_each_undoable(full, fake_ollama):
    localai.configure(threshold="0.80")
    b, ids = _bank(full, [("10/07/2026", "EXAMPLE POWER UTILITY", "-10.00"),
                          ("10/08/2026", "EXAMPLE SIGNS", "-20.00")])
    fake_ollama.reply = lambda body: (
        {"account": "6010", "confidence": 0.9} if "POWER" in
        body["messages"][1]["content"] else
        {"account": "6090", "confidence": 0.5})
    aicat.suggest_queue(full, b)
    r = aicat.accept_bulk(full, b)
    assert r["accepted"] == [ids["EXAMPLE POWER UTILITY"]]
    assert r["below_threshold"] == 1
    assert banking.line(full, ids["EXAMPLE SIGNS"])["status"] == "Suggested"
    aicat.undo_accept(full, ids["EXAMPLE POWER UTILITY"])
    assert ledger.balance(full, "6010") == 0
    with pytest.raises(ValueError):
        localai.configure(threshold="1.5")


def test_model_job_and_cost_code_kept_only_when_real(full, fake_ollama, job):
    b, ids = _bank(full, [("10/07/2026", "EXAMPLE CONCRETE PUMP", "-900.00"),
                          ("10/08/2026", "EXAMPLE CRANE", "-800.00")])
    fake_ollama.reply = lambda body: (
        {"account": "5030", "job": "2611", "cost_code": "03-3000",
         "confidence": 0.8} if "PUMP" in body["messages"][1]["content"]
        else {"account": "5030", "job": "9999", "cost_code": "03-3000",
              "confidence": 0.8})
    aicat.suggest_queue(full, b)
    s = banking.line(full, ids["EXAMPLE CONCRETE PUMP"])["suggestion"]
    assert s["job_id"] == job and s["cost_code"] == "03-3000"
    s = banking.line(full, ids["EXAMPLE CRANE"])["suggestion"]
    assert s["job_id"] is None and s["cost_code"] == ""


def test_no_model_installed_degrades_and_cancel_stops(full, fake_ollama):
    b, ids = _bank(full, [("10/02/2026", "EXAMPLE LUMBER #12", "-80.00"),
                          ("10/09/2026", "EXAMPLE LUMBER #47", "-95.10"),
                          ("10/09/2026", "EXAMPLE POWER UTILITY", "-41.00")])
    banking.categorize(full, ids["EXAMPLE LUMBER #12"], "5020")
    banking.accept(full, ids["EXAMPLE LUMBER #12"])
    localai.configure(model="")                      # no model chosen
    assert localai.client() is None
    n = aicat.suggest_queue(full, b)
    assert n["model_available"] is False
    assert (n["similar"], n["none"]) == (1, 1)
    assert banking.line(full, ids["EXAMPLE POWER UTILITY"])["status"] == \
        "New"
    localai.configure(url="http://127.0.0.1:9", model="llama3.2")  # stopped
    assert aicat.suggest_queue(full, b)["model_available"] is False
    localai.configure(url=fake_ollama.url, model="llama3.2")
    n = aicat.suggest_queue(full, b, cancelled=lambda: True)
    assert n["cancelled"] and fake_ollama.chats() == []


def test_bad_model_answers_discarded_and_rejected(full, fake_ollama):
    b, ids = _bank(full, [("10/07/2026", "EXAMPLE THING", "-10.00"),
                          ("10/09/2026", "EXAMPLE OFFICE SUPPLY 9", "-20.00")])
    fake_ollama.reply = lambda body: {"account": "1000", "confidence": 1}
    assert aicat.suggest_line(full, ids["EXAMPLE THING"]) is None
    assert banking.line(full, ids["EXAMPLE THING"])["status"] == "New"
    assert aitrail.history(full)[-1]["status"] == "discarded"
    fake_ollama.reply = lambda body: {"account": "6060", "confidence": 0.5}
    s2 = aicat.suggest_line(full, ids["EXAMPLE OFFICE SUPPLY 9"])
    assert s2["low"]
    aicat.dismiss(full, ids["EXAMPLE OFFICE SUPPLY 9"], "not right")
    assert aitrail.get(full, s2["ai_log_id"])["status"] == "rejected"
    assert _audit(full, "ai rejected")


def test_openai_compatible_localhost_runtime(full, fake_ollama):
    localai.configure(api="openai")
    b, ids = _bank(full, [("10/07/2026", "EXAMPLE POWER UTILITY", "-10.00")])
    fake_ollama.reply = lambda body: {"account": "6010", "confidence": 0.9}
    n = aicat.suggest_queue(full, b)
    assert n["model"] == 1
    assert {p for _, p, _ in fake_ollama.requests} == {
        "/v1/models", "/v1/chat/completions"}
