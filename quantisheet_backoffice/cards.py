"""Credit card receipt tracking (P2-09).

Card statements come in through bank statement import (P2-11, same
de-dup and column maps). Each charge is matched to a captured receipt:
same amount, dates within 3 days and the merchant name agreeing make an
automatic match; a receipt that fits only partly is suggested for a person
to accept; charges with no receipt go on the Missing Receipts list. Coded
charges can be routed for approval (approval path 'card_charge'); an
accepted charge posts to the card's liability account and, when coded to a
job, counts in job cost. Reminders are drafts; nothing is sent.
"""
from __future__ import annotations

import os
import re
import shutil

from . import approvals, banking, cents, clock, fileguard, store

DAYS = 3
_STOP = {"INC", "LLC", "CO", "CORP", "THE", "AND", "OF", "STORE", "SUPPLY",
         "SUPPLIES", "COMPANY",
         "EXAMPLE", "SAMPLE", "TEST"}     # placeholder words in made-up names


class CardError(ValueError):
    pass


def _card(office, card_id):
    b = office.db.get("bank_accounts", card_id)
    if b is None or b["kind"] != "card":
        raise CardError(f"{card_id} is not a card account")
    return b


def set_cardholder(office, card_id, cardholder, cardholder_user_id=None,
                   default_job_id=None) -> None:
    office.require("bank.edit", "bank_account", card_id)
    _card(office, card_id)
    with office.db.tx():
        office.db.update("bank_accounts", card_id, cardholder=cardholder,
                         cardholder_user_id=cardholder_user_id,
                         default_job_id=default_job_id)
        office.audit("cardholder", "bank_account", card_id, None,
                     {"cardholder": cardholder, "default_job": default_job_id})


def cards_list(office) -> list[dict]:
    return office.db.rows("SELECT * FROM bank_accounts WHERE kind = 'card' AND "
                          "deleted = 0 ORDER BY name")


def add_receipt(office, card_id, date, merchant, amount, path=None,
                cardholder=None, job_id=None, cost_code="") -> int:
    office.require("cards.edit", "card_receipt", card_id)
    b = _card(office, card_id)
    dest = h = None
    if path:
        fileguard.refuse_company_file(path)
        dest = store.copy_into(os.path.join(office.documents_folder(),
                                            "receipts"), path)
        h = store.file_hash(dest)
    with office.db.tx():
        rid = office.db.insert(
            "card_receipts", card_id=card_id,
            cardholder=cardholder or b["cardholder"],
            date=str(clock.d(date)), merchant=merchant,
            amount=abs(cents.amount_in(amount)), file_path=dest, file_hash=h,
            status="Unmatched", job_id=job_id or b["default_job_id"],
            cost_code=cost_code)
        office.audit("create", "card_receipt", rid, None,
                     {"merchant": merchant, "amount": amount})
    return rid


def capture_receipt(office, card_id, path, engine=None, vendors=()) -> int:
    """Read a receipt photo or PDF with local OCR (P1-08) and add it; the
    fields still need a person to confirm low-confidence values."""
    from . import ocr
    f = ocr.extract(path, vendors=vendors, engine=engine)["fields"]
    get = lambda k: (f.get(k) or (None,))[0]          # noqa: E731
    total = get("total")
    if total is None:
        raise CardError("No total found on the receipt; enter it by hand.")
    return add_receipt(office, card_id, get("invoice_date") or clock.today(),
                       get("vendor") or os.path.basename(path), total,
                       path=path)


def _words(s) -> set[str]:
    return {w for w in re.findall(r"[A-Z]+", str(s).upper())
            if len(w) >= 3 and w not in _STOP}


def merchant_match(a, b) -> bool:
    wa, wb = _words(a), _words(b)
    return bool(wa & wb)


def _charges(office, card_id):
    return office.db.rows("SELECT * FROM statement_lines WHERE "
                          "bank_account_id = ? AND deleted = 0 AND amount < 0 "
                          "AND status != 'Excluded' AND receipt_id IS NULL "
                          "ORDER BY date, id", (card_id,))


def _open_receipts(office, card_id):
    return office.db.rows("SELECT * FROM card_receipts WHERE deleted = 0 AND "
                          "statement_line_id IS NULL AND (card_id = ? OR "
                          "card_id IS NULL) ORDER BY date, id", (card_id,))


def _plan(office, card_id):
    charges = _charges(office, card_id)
    receipts = _open_receipts(office, card_id)
    full_for = {}            # receipt id -> charges it fully fits
    info = []
    for c in charges:
        cands = [r for r in receipts if r["amount"] == -c["amount"]]
        full = []
        for r in cands:
            days = abs((clock.d(r["date"]) - clock.d(c["date"])).days)
            if days <= DAYS and merchant_match(r["merchant"], c["payee"]):
                full.append(r)
                full_for.setdefault(r["id"], []).append(c["id"])
        info.append((c, cands, full))
    auto, suggested, missing, used = [], [], [], set()
    for c, cands, full in info:
        if len(full) == 1 and full_for[full[0]["id"]] == [c["id"]]:
            auto.append({"line_id": c["id"], "receipt_id": full[0]["id"]})
            used.add(full[0]["id"])
    for c, cands, full in info:
        if any(a["line_id"] == c["id"] for a in auto):
            continue
        left = [r for r in cands if r["id"] not in used]
        if not left:
            missing.append(c)
            continue
        r = left[0]
        days = abs((clock.d(r["date"]) - clock.d(c["date"])).days)
        why = ["same amount"]
        if days > DAYS:
            why.append(f"dates {days} days apart")
        if not merchant_match(r["merchant"], c["payee"]):
            why.append(f"merchant '{r['merchant']}' vs '{c['payee']}'")
        if len(left) > 1:
            why.append(f"{len(left)} receipts fit")
        suggested.append({"line_id": c["id"], "receipt_id": r["id"],
                          "reason": "; ".join(why)})
    return auto, suggested, missing


def match(office, card_id) -> dict:
    """Apply the automatic matches; return what was matched, suggested and
    is still missing a receipt."""
    office.require("cards.edit", "bank_account", card_id)
    _card(office, card_id)
    auto, suggested, missing = _plan(office, card_id)
    with office.db.tx():
        for a in auto:
            _link(office, a["line_id"], a["receipt_id"], "auto")
    return {"auto": auto, "suggested": suggested,
            "missing": [c["id"] for c in missing]}


def _link(office, lid, rid, how):
    office.db.update("statement_lines", lid, receipt_id=rid)
    office.db.update("card_receipts", rid, statement_line_id=lid,
                     status="Matched")
    office.audit("match receipt", "statement_line", lid, None,
                 {"receipt": rid, "how": how})


def accept_match(office, lid, rid) -> None:
    office.require("cards.edit", "statement_line", lid)
    ln = office.db.get("statement_lines", lid)
    r = office.db.get("card_receipts", rid)
    if ln["receipt_id"] or r["statement_line_id"]:
        raise CardError("Already matched.")
    with office.db.tx():
        _link(office, lid, rid, "accepted suggestion")


def unmatch(office, lid) -> None:
    office.require("cards.edit", "statement_line", lid)
    ln = office.db.get("statement_lines", lid)
    if not ln["receipt_id"]:
        return
    with office.db.tx():
        office.db.update("card_receipts", ln["receipt_id"],
                         statement_line_id=None, status="Unmatched")
        office.db.update("statement_lines", lid, receipt_id=None)
        office.audit("unmatch receipt", "statement_line", lid)


def missing(office, card_id=None) -> list[dict]:
    """Charges with no receipt and nothing that could be one."""
    ids = [card_id] if card_id else [c["id"] for c in cards_list(office)]
    out = []
    for cid in ids:
        b = _card(office, cid)
        for c in _plan(office, cid)[2]:
            c["cardholder"] = b["cardholder"] or ""
            c["card"] = f"{b['name']} ...{b['last4']}"
            out.append(c)
    return out


def reminder_text(office, cardholder, charges) -> str:
    """A reminder for a person to send (nothing is sent)."""
    lines = [f"Hi {cardholder},", "",
             "These card charges still need a receipt:"]
    for c in charges:
        lines.append(f"  {c['date']}  {c['payee']}  "
                     f"{cents.fmt(-c['amount'])}")
    lines += ["", "Please snap a photo of each receipt and send it to the "
              "office. Thank you."]
    return "\n".join(lines)


# ---- coding and approval --------------------------------------------------

def _routed(office) -> bool:
    return office.db.one("SELECT id FROM approval_paths WHERE record_type = "
                         "'card_charge' AND deleted = 0") is not None


def code(office, lid, account, job_id=None, cost_code="") -> None:
    """Code a charge; with a 'card_charge' approval path it then waits for
    approval before it can be accepted (posted)."""
    ln = office.db.get("statement_lines", lid)
    _card(office, ln["bank_account_id"])
    banking.categorize(office, lid, account, job_id=job_id,
                       cost_code=cost_code)
    from .r111.duties import note
    note(office, "card_charge", lid, "coded")
    if _routed(office):
        with office.db.tx():
            approvals.start(office, "card_charge", lid,
                            approvals.path_for(office, "card_charge", job_id),
                            job_id)


def approve(office, lid, decision="approve", reason="") -> dict:
    office.require("cards.approve" if not office.can("cards.edit") else
                   "cards.edit", "statement_line", lid)
    return approvals.decide(office, "card_charge", lid, decision, reason)


def waiting_approval(office, lid) -> bool:
    req = approvals.request(office, "card_charge", lid)
    return req is not None and req["status"] != "approved"
