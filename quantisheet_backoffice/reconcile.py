"""Bank reconciliation (addendum P2-13). Full-books mode.

One statement period at a time per bank or card account, in order. The
beginning balance is the last finished reconciliation's ending balance.
Difference = statement ending balance - (beginning + cleared items);
Finish only at $0.00. Finished reconciliations lock their lines. Only the
latest one can be undone, by a Controller or Admin with a reason.
"""
from __future__ import annotations

import json

from . import cents, clock, ledger


class ReconcileError(ValueError):
    pass


def _ledger_account(office, bank_account_id):
    return office.db.get("bank_accounts", bank_account_id)["account_id"]


def _finished(office, bank_account_id):
    return office.db.rows("SELECT * FROM reconciliations WHERE "
                          "bank_account_id = ? AND status = 'Finished' AND "
                          "deleted = 0 ORDER BY period_end, id",
                          (bank_account_id,))


def reconciliation(office, rid) -> dict:
    r = office.db.get("reconciliations", rid)
    r["cleared"] = json.loads(r["cleared"] or "[]")
    return r


def reconciled_line_ids(office, bank_account_id=None) -> set[int]:
    out = set()
    q = "SELECT cleared FROM reconciliations WHERE status = 'Finished' " \
        "AND deleted = 0"
    p = []
    if bank_account_id:
        q += " AND bank_account_id = ?"
        p.append(bank_account_id)
    for r in office.db.rows(q, p):
        out |= set(json.loads(r["cleared"] or "[]"))
    return out


def is_reconciled(office, journal_line_id) -> bool:
    return journal_line_id in reconciled_line_ids(office)


def start(office, bank_account_id, period_end, ending, beginning=None) -> int:
    """Open the next reconciliation. `beginning` may be given only for the
    account's first one; later ones start from the last ending balance."""
    office.require_full_books("Bank reconciliation")
    office.require("bank.edit", "reconciliation", bank_account_id)
    if office.db.scalar("SELECT COUNT(*) FROM reconciliations WHERE "
                        "bank_account_id = ? AND status = 'Open' AND "
                        "deleted = 0", (bank_account_id,)):
        raise ReconcileError("Finish or delete the open reconciliation "
                             "first.")
    done = _finished(office, bank_account_id)
    if done:
        if beginning is not None:
            raise ReconcileError("The beginning balance comes from the last "
                                 "reconciliation.")
        if str(period_end) <= done[-1]["period_end"]:
            raise ReconcileError("Reconcile periods in order.")
        beg = done[-1]["ending"]
        pstart = done[-1]["period_end"]
    else:
        beg = cents.amount_in(beginning or "0")
        pstart = ""
    with office.db.tx():
        rid = office.db.insert("reconciliations",
                               bank_account_id=bank_account_id,
                               period_start=pstart, period_end=str(period_end),
                               beginning=beg, ending=cents.amount_in(ending),
                               cleared_total=0, status="Open", cleared="[]")
        office.audit("start", "reconciliation", rid, None,
                     {"period_end": str(period_end), "beginning": beg})
    return rid


def items(office, rid) -> list[dict]:
    """Every posting to the account up to the statement date that is not
    in an earlier finished reconciliation; amount signed (+ in, - out)."""
    r = reconciliation(office, rid)
    acct = _ledger_account(office, r["bank_account_id"])
    done = reconciled_line_ids(office, r["bank_account_id"]) - set(r["cleared"])
    a = ledger.account(office, acct)
    sign = 1 if a["type"] in ledger.DEBIT_NORMAL else -1
    out = []
    for ln in office.db.rows(
            "SELECT l.id, l.debit, l.credit, l.memo, l.party, e.date, "
            "e.number, e.source_type, e.source_id FROM journal_lines l JOIN "
            "journal_entries e ON e.id = l.entry_id WHERE l.account_id = ? "
            "AND e.date <= ? ORDER BY e.date, l.id",
            (acct, r["period_end"])):
        if ln["id"] in done:
            continue
        ref = ""
        if ln["source_type"] == "bill_payment":
            bp = office.db.get("bill_payments", ln["source_id"])
            ref = f"{bp['method']} {bp['reference']}".strip() if bp else ""
        out.append({"line_id": ln["id"], "date": ln["date"],
                    "amount": (ln["debit"] - ln["credit"]) * sign,
                    "memo": ln["memo"] or "", "party": ln["party"] or "",
                    "reference": ref, "entry": ln["number"],
                    "cleared": ln["id"] in r["cleared"]})
    return out


def set_cleared(office, rid, line_ids, cleared=True) -> dict:
    r = reconciliation(office, rid)
    if r["status"] != "Open":
        raise ReconcileError("This reconciliation is finished.")
    ok = {i["line_id"] for i in items(office, rid)}
    cur = set(r["cleared"])
    for lid in line_ids:
        if lid not in ok:
            raise ReconcileError(f"line {lid} is not in this period")
        if cleared:
            cur.add(lid)
        else:
            cur.discard(lid)
    tot = sum(i["amount"] for i in items(office, rid) if i["line_id"] in cur)
    with office.db.tx():
        office.db.update("reconciliations", rid, cleared=json.dumps(sorted(cur)),
                         cleared_total=tot)
    return status(office, rid)


def status(office, rid) -> dict:
    r = reconciliation(office, rid)
    diff = r["ending"] - (r["beginning"] + r["cleared_total"])
    return {"beginning": r["beginning"], "ending": r["ending"],
            "cleared": r["cleared_total"], "difference": diff,
            "difference_text": cents.fmt(diff),
            "can_finish": diff == 0 and r["status"] == "Open",
            "status": r["status"],
            "label": ("Ready to finish" if diff == 0 and r["status"] == "Open"
                      else r["status"] if r["status"] != "Open"
                      else f"Difference {cents.fmt(diff)}")}


def finish(office, rid) -> None:
    st = status(office, rid)
    if not st["can_finish"]:
        raise ReconcileError(f"Difference is {st['difference_text']}; "
                             f"Finish needs $0.00.")
    r = reconciliation(office, rid)
    with office.db.tx():
        office.db.update("reconciliations", rid, status="Finished",
                         finished_by=office.who, finished_at=clock.iso_now())
        for lid in r["cleared"]:
            sl = office.db.one("SELECT statement_line_id FROM journal_lines "
                               "WHERE id = ?", (lid,))
            if sl and sl["statement_line_id"]:
                office.db.update("statement_lines", sl["statement_line_id"],
                                 reconciliation_id=rid)
        office.audit("finish", "reconciliation", rid, None,
                     {"cleared": r["cleared"], "ending": r["ending"]})


def undo(office, rid, reason) -> None:
    if office.role not in ("Controller", "Admin"):
        office.audit("denied", "reconciliation", rid, None,
                     {"permission": "recon.undo", "role": office.role})
        from .security import Denied
        raise Denied("Only a Controller or Admin can undo a reconciliation.")
    if not (reason or "").strip():
        raise ReconcileError("A reason is required to undo a reconciliation.")
    r = reconciliation(office, rid)
    done = _finished(office, r["bank_account_id"])
    if not done or done[-1]["id"] != rid:
        raise ReconcileError("Only the latest reconciliation can be undone; "
                             "undo the later one first.")
    with office.db.tx():
        office.db.update("reconciliations", rid, status="Open",
                         undone_by=office.who, undo_reason=reason)
        office.db.conn.execute("UPDATE statement_lines SET reconciliation_id "
                               "= NULL WHERE reconciliation_id = ?", (rid,))
        office.audit("undo", "reconciliation", rid, {"status": "Finished"},
                     {"reason": reason})


def report(office, rid) -> dict:
    its = items(office, rid)
    st = status(office, rid)
    return {**st, "cleared_items": [i for i in its if i["cleared"]],
            "outstanding": [i for i in its if not i["cleared"]]}


def report_pdf(office, rid, path) -> str:
    import fitz
    rep = report(office, rid)
    r = reconciliation(office, rid)
    b = office.db.get("bank_accounts", r["bank_account_id"])
    doc = fitz.open()
    pg = doc.new_page()
    y = 60
    pg.insert_text((54, y), f"Bank reconciliation - {b['name']} "
                   f"(...{b['last4']}) through {r['period_end']}", fontsize=13)
    y += 24
    for label, k in (("Beginning balance", "beginning"),
                     ("Cleared items", "cleared"),
                     ("Statement ending balance", "ending"),
                     ("Difference", "difference")):
        pg.insert_text((54, y), f"{label}: {cents.fmt(rep[k])}", fontsize=10)
        y += 14
    for title, key in (("Cleared", "cleared_items"),
                       ("Outstanding", "outstanding")):
        y += 10
        pg.insert_text((54, y), title, fontsize=11)
        y += 14
        for i in rep[key]:
            if y > 760:
                pg = doc.new_page()
                y = 60
            pg.insert_text((54, y), f"{i['date']}  {i['reference'] or i['memo']}"
                           f"  {i['party']}  {cents.fmt(i['amount'])}",
                           fontsize=9)
            y += 12
    doc.save(path)
    doc.close()
    return path
