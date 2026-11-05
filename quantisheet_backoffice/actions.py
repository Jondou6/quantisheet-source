"""Changes the assistant proposes (P3-01): each is shown as a before/after,
applied only when a person clicks Apply, logged under that person and
undoable. Kinds:

  recode_time  - move hours on a time line to another cost code (splits the
                 line when only part of it moves). An Approved line goes
                 back to Submitted and through its approval path again.
  recategorize - move many accepted bank/card lines to another account in
                 one go (one reclassifying entry per line; one Undo
                 reverses them all)
  journal      - a drafted journal entry, posted only on Apply (undo =
                 exact reversing entry)
  bank_rule    - add a bank rule (banking.add_rule)
  reminder     - a reminder TEXT for a person to copy and send; Back Office
                 sends nothing

Every proposal, apply, dismiss and undo is an ai_actions row plus audit rows.
"""
from __future__ import annotations

import json

from . import approvals, cents, clock, jobs, ledger, timeentry

KINDS = ("recode_time", "recategorize", "journal", "bank_rule", "reminder")


class ActionError(RuntimeError):
    pass


def _row(office, aid) -> dict:
    r = office.db.get("ai_actions", aid)
    if r is None or r["deleted"]:
        raise ActionError(f"no assistant action {aid}")
    for k in ("params", "before", "after", "undo", "records_read"):
        r[k] = json.loads(r[k] or "null")
    return r


def get(office, aid) -> dict:
    return _row(office, aid)


def pending(office) -> list[dict]:
    return [_row(office, r["id"]) for r in office.db.rows(
        "SELECT id FROM ai_actions WHERE status = 'proposed' AND deleted = 0 "
        "AND kind != 'question' ORDER BY id")]


def history(office) -> list[dict]:
    return [_row(office, r["id"]) for r in office.db.rows(
        "SELECT id FROM ai_actions WHERE status IN ('applied','undone',"
        "'dismissed') AND deleted = 0 ORDER BY id DESC")]


# ---- preview ------------------------------------------------------------

def _recode_preview(office, p):
    ln = office.db.get("time_lines", int(p["line_id"]))
    if ln is None or ln["deleted"]:
        raise ActionError("That time line no longer exists.")
    h = cents.hours(p["hours"])
    if h <= 0 or h > ln["hours"]:
        raise ActionError(f"Can move between 0 and "
                          f"{cents.hours_text(ln['hours'])} h of that line.")
    to = str(p["to_code"]).strip()
    codes = {c["code"] for c in jobs.section(office, ln["job_id"],
                                             "cost_codes")}
    if codes and to not in codes:
        raise ActionError(f"{to} is not a cost code on this job.")
    if ln["cost_code"] == to:
        raise ActionError("The line already has that cost code.")
    w = office.db.get("workers", ln["worker_id"])
    before = {"line_id": ln["id"], "worker": w["name"] if w else "",
              "date": ln["date"], "cost_code": ln["cost_code"],
              "hours": cents.hours_text(ln["hours"])}
    after = [{"cost_code": to, "hours": cents.hours_text(h)}]
    if h < ln["hours"]:
        after.insert(0, {"cost_code": ln["cost_code"],
                         "hours": cents.hours_text(ln["hours"] - h)})
    return before, {"lines": after}


def _recat_lines(office, p):
    to = ledger.account(office, ledger._acct_id(office, p["to_account"]))
    out = []
    for lid in p["line_ids"]:
        sl = office.db.get("statement_lines", int(lid))
        if sl is None or sl["status"] != "Accepted" or not sl["entry_id"]:
            raise ActionError(f"Bank line {lid} is not an accepted line.")
        bank = office.db.get("bank_accounts", sl["bank_account_id"])
        e = ledger.entry(office, sl["entry_id"])
        if e["reversed_by_id"]:
            raise ActionError(f"Bank line {lid}'s entry was reversed.")
        others = [ln for ln in e["lines"]
                  if ln["account_id"] != bank["account_id"]]
        if len(others) != 1:
            raise ActionError(f"Bank line {lid} is a match, not a "
                              f"category; it can't be recategorized.")
        out.append((sl, others[0], to))
    return out


def _recat_preview(office, p):
    rows = _recat_lines(office, p)
    if not rows:
        raise ActionError("No lines to recategorize.")
    before, after = [], []
    for sl, jl, to in rows:
        frm = ledger.account(office, jl["account_id"])
        amt = jl["debit"] - jl["credit"]
        before.append({"line": sl["id"], "date": sl["date"],
                       "payee": sl["payee"], "amount": cents.text(amt),
                       "account": f"{frm['number']} {frm['name']}"})
        after.append({"line": sl["id"], "date": sl["date"],
                      "payee": sl["payee"], "amount": cents.text(amt),
                      "account": f"{to['number']} {to['name']}"})
    return before, {"lines": after}


def _journal_lines(office, p):
    lines = []
    for ln in p["lines"]:
        a = ledger.account(office, ledger._acct_id(office, ln["account"]))
        lines.append({"account": a["number"], "name": a["name"],
                      "debit": cents.text(cents.amount_in(
                          str(ln.get("debit") or "0"))),
                      "credit": cents.text(cents.amount_in(
                          str(ln.get("credit") or "0"))),
                      "memo": ln.get("memo", "")})
    dr = sum(cents.amount_in(x["debit"]) for x in lines)
    cr = sum(cents.amount_in(x["credit"]) for x in lines)
    if dr != cr or dr == 0:
        raise ActionError(f"The drafted entry doesn't balance (debits "
                          f"{cents.text(dr)}, credits {cents.text(cr)}).")
    return lines


def _preview(office, kind, p):
    if kind == "recode_time":
        return _recode_preview(office, p)
    if kind == "recategorize":
        return _recat_preview(office, p)
    if kind == "journal":
        return None, {"date": str(clock.d(p["date"])), "memo": p.get(
            "memo", ""), "lines": _journal_lines(office, p)}
    if kind == "bank_rule":
        return None, {"rule": f"{p.get('field', 'payee')} "
                              f"{p.get('operator', 'contains')} "
                              f"'{p['text']}' -> {p['account']}"}
    if kind == "reminder":
        return None, {"to": p.get("to", ""), "text": p["text"]}
    raise ActionError(f"unknown action {kind!r}")


def propose(office, kind, params, question="", records_read=(),
            model="", input_hash="", model_version="") -> int:
    office.require("ai.use", "ai_action", kind)
    if kind not in KINDS:
        raise ActionError(f"unknown action {kind!r}")
    before, after = _preview(office, kind, params)
    with office.db.tx():
        aid = office.db.insert(
            "ai_actions", question=question, tool=kind, kind=kind,
            params=json.dumps(params), records_read=json.dumps(
                list(records_read)), before=json.dumps(before),
            after=json.dumps(after), status="proposed", model=model,
            model_version=model_version, input_hash=input_hash)
        office.audit("assistant proposed", "ai_action", aid, before,
                     {"kind": kind, "after": after})
    return aid


def dismiss(office, aid, reason="") -> None:
    office.require("ai.use", "ai_action", aid)
    a = _row(office, aid)
    if a["status"] != "proposed":
        raise ActionError(f"This suggestion is {a['status']}.")
    with office.db.tx():
        office.db.update("ai_actions", aid, status="dismissed",
                         applied_by=office.who, applied_at=clock.iso_now())
        office.audit("assistant dismissed", "ai_action", aid, None,
                     {"reason": reason})


# ---- apply / undo --------------------------------------------------------

def _check_time_open(office, ln):
    timeentry._payroll_final(office, ln["date"])
    if timeentry._week_locked(office, ln["date"]) or ln["status"] == "Locked":
        raise ActionError(f"The week ending {jobs.week_ending(ln['date'])} "
                          f"is locked.")


def _reapprove(office, ids) -> None:
    """A changed Approved line goes back through its approval path."""
    for lid in ids:
        ln = office.db.get("time_lines", lid)
        office.db.update("time_lines", lid, status="Submitted")
        approvals.start(office, "time_line", lid,
                        approvals.path_for(office, "time_line",
                                           ln["job_id"]), ln["job_id"])
        office.audit("change", "time_line", lid, {"status": "Approved"},
                     {"status": "Submitted",
                      "reason": "changed by an assistant action; needs "
                                "approval again"})


def _reapprove_if_needed(office, lid) -> None:
    """After an undo the restored line still needs approval again (it is
    not put back to Approved by an undo)."""
    if office.db.get("time_lines", lid)["status"] == "Approved":
        _reapprove(office, [lid])


def _apply_recode(office, aid, p):
    office.require("time.edit", "time_line", p["line_id"])
    ln = office.db.get("time_lines", int(p["line_id"]))
    _check_time_open(office, ln)
    h = cents.hours(p["hours"])
    to = str(p["to_code"]).strip()
    if h <= 0 or h > ln["hours"]:
        raise ActionError("The line changed since this was suggested.")
    was_approved = ln["status"] == "Approved"
    if h == ln["hours"]:
        office.db.update("time_lines", ln["id"], cost_code=to)
        office.audit("change", "time_line", ln["id"],
                     {"cost_code": ln["cost_code"]},
                     {"cost_code": to, "by": "assistant", "action": aid})
        if was_approved:
            _reapprove(office, [ln["id"]])
        return {"line_id": ln["id"], "old_code": ln["cost_code"],
                "new_line": None, "hours": ln["hours"], "code": to,
                "reapproval": was_approved}
    office.db.update("time_lines", ln["id"], hours=ln["hours"] - h)
    keep = {k: ln[k] for k in ("worker_id", "date", "job_id", "phase",
                               "pay_type", "note", "status")}
    nid = office.db.insert("time_lines", **keep, cost_code=to, hours=h,
                           equipment_code="", equipment_hours=0,
                           source="assistant", source_key=f"ai_action:{aid}")
    office.audit("change", "time_line", ln["id"], {"hours": ln["hours"]},
                 {"hours": ln["hours"] - h, "by": "assistant",
                  "action": aid})
    office.audit("create", "time_line", nid, None,
                 {"split_from": ln["id"], "cost_code": to, "hours": h,
                  "by": "assistant", "action": aid})
    if was_approved:
        _reapprove(office, [ln["id"], nid])
    return {"line_id": ln["id"], "old_code": ln["cost_code"],
            "new_line": nid, "hours": h, "code": to,
            "reapproval": was_approved}


def _apply_recat(office, aid, p):
    office.require("bank.edit", "statement_line", "recategorize")
    office.require_full_books("Recategorize")
    done = []
    for sl, jl, to in _recat_lines(office, p):
        amt = jl["debit"] - jl["credit"]
        frm = jl["account_id"]
        common = {"job_id": jl["job_id"], "cost_code": jl["cost_code"],
                  "party": jl["party"], "memo": f"Recategorize line "
                                                f"{sl['id']}"}
        if amt >= 0:
            lines = [dict(common, account=to["id"], debit=amt),
                     dict(common, account=frm, credit=amt)]
        else:
            lines = [dict(common, account=frm, debit=-amt),
                     dict(common, account=to["id"], credit=-amt)]
        d = ledger.first_open_date(office, sl["date"])
        eid = ledger.post(office, d, lines, "recategorize", sl["id"],
                          f"Recategorize {sl['payee']} to {to['number']}")
        done.append({"line": sl["id"], "entry": eid,
                     "account_id": sl["account_id"],
                     "user_categorized": sl["user_categorized"]})
        office.db.update("statement_lines", sl["id"], account_id=to["id"],
                         user_categorized=1)
        office.audit("recategorize", "statement_line", sl["id"],
                     {"account": frm}, {"account": to["id"], "entry": eid,
                                        "action": aid})
    return {"entries": done}


def apply(office, aid) -> dict:
    """The user's click."""
    office.require("ai.use", "ai_action", aid)
    a = _row(office, aid)
    if a["status"] != "proposed":
        raise ActionError(f"This suggestion is {a['status']}.")
    p = a["params"]
    with office.db.tx():
        if a["kind"] == "recode_time":
            undo = _apply_recode(office, aid, p)
        elif a["kind"] == "recategorize":
            undo = _apply_recat(office, aid, p)
        elif a["kind"] == "journal":
            eid = ledger.post_manual(
                office, a["after"]["date"],
                [{"account": x["account"],
                  "debit": cents.amount_in(x["debit"]),
                  "credit": cents.amount_in(x["credit"]),
                  "memo": x["memo"]} for x in a["after"]["lines"]],
                a["after"]["memo"] or "Drafted by the assistant")
            undo = {"entry": eid}
        elif a["kind"] == "bank_rule":
            from . import banking
            rid = banking.add_rule(office, p["text"], p["account"],
                                   operator=p.get("operator", "contains"),
                                   field=p.get("field", "payee"))
            undo = {"rule_id": rid}
        else:                        # reminder: text only, nothing is sent
            undo = {}
        office.db.update("ai_actions", aid, status="applied",
                         applied_by=office.who, applied_at=clock.iso_now(),
                         undo=json.dumps(undo))
        office.audit("assistant applied", "ai_action", aid, a["before"],
                     {"kind": a["kind"], "after": a["after"], "undo": undo})
    return undo


def undo(office, aid, reason="") -> None:
    office.require("ai.use", "ai_action", aid)
    a = _row(office, aid)
    if a["status"] != "applied":
        raise ActionError("Only an applied suggestion can be undone.")
    u = a["undo"] or {}
    with office.db.tx():
        if a["kind"] == "recode_time":
            office.require("time.edit", "time_line", u["line_id"])
            ln = office.db.get("time_lines", u["line_id"])
            _check_time_open(office, ln)
            if u["new_line"]:
                nl = office.db.get("time_lines", u["new_line"])
                if nl["deleted"] or nl["cost_code"] != u["code"] or \
                        nl["hours"] != u["hours"]:
                    raise ActionError("The moved hours were changed since; "
                                      "undo by hand.")
                office.db.update("time_lines", nl["id"], deleted=1)
                office.db.update("time_lines", ln["id"],
                                 hours=ln["hours"] + u["hours"])
                office.audit("delete", "time_line", nl["id"], None,
                             {"undo_action": aid})
                office.audit("change", "time_line", ln["id"],
                             {"hours": ln["hours"]},
                             {"hours": ln["hours"] + u["hours"],
                              "undo_action": aid})
                if u.get("reapproval"):
                    _reapprove_if_needed(office, ln["id"])
            else:
                if ln["cost_code"] != u["code"]:
                    raise ActionError("The line was changed since; undo by "
                                      "hand.")
                office.db.update("time_lines", ln["id"],
                                 cost_code=u["old_code"])
                office.audit("change", "time_line", ln["id"],
                             {"cost_code": u["code"]},
                             {"cost_code": u["old_code"], "undo_action": aid})
                if u.get("reapproval"):
                    _reapprove_if_needed(office, ln["id"])
        elif a["kind"] == "recategorize":
            office.require("bank.edit", "statement_line", "recategorize")
            for x in u["entries"]:
                ledger.reverse(office, x["entry"],
                               ledger.first_open_date(office, clock.today()),
                               f"Undo recategorize (action {aid})")
                office.db.update("statement_lines", x["line"],
                                 account_id=x["account_id"],
                                 user_categorized=x["user_categorized"])
                office.audit("recategorize undone", "statement_line",
                             x["line"], None, {"action": aid})
        elif a["kind"] == "journal":
            office.require("gl.journal", "journal_entry", u["entry"])
            ledger.reverse(office, u["entry"],
                           ledger.first_open_date(office, clock.today()),
                           f"Undo drafted entry (action {aid})")
        elif a["kind"] == "bank_rule":
            office.db.update("bank_rules", u["rule_id"], active=0)
            office.audit("change", "bank_rule", u["rule_id"],
                         {"active": 1}, {"active": 0, "undo_action": aid})
        office.db.update("ai_actions", aid, status="undone",
                         undone_by=office.who, undone_at=clock.iso_now())
        office.audit("assistant undone", "ai_action", aid, a["after"],
                     {"reason": reason})
