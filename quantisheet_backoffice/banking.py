"""Bank and card accounts, statement import, review queue, matching and
bank rules (addendum P2-11, P2-12; P2-09 card receipts). Full-books mode.

Files only: OFX/QFX (SGML or XML) and CSV with a saved column map. No live
bank feed and no Google service. Imported lines wait in a review queue and
never post by themselves: every posting is a user's Accept. Matching is
deterministic and only suggests; a category the user set is never changed
by a later rule; two equally good matches are both shown, never auto-picked.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from datetime import date, datetime, timedelta

from . import ap, appay, cents, clock, fileguard, ledger

STATUSES = ("New", "Suggested", "Accepted", "Excluded")
MATCH_DAYS = 5
OPERATORS = ("contains", "starts with", "equals")
CSV_DEFAULT_MAP = {"date": "Date", "amount": "Amount",
                   "payee": "Description", "memo": "Memo",
                   "reference": "Reference", "date_format": ""}


class BankError(ValueError):
    pass


def _full(office):
    office.require_full_books("Banking")


# ---- accounts ------------------------------------------------------------

def add_account(office, name, ledger_account, kind="bank", last4="",
                statement_format="ofx", column_map=None) -> int:
    """A bank or card account linked to a chart account. Only the last 4
    digits of the real account number are kept."""
    _full(office)
    office.require("bank.edit", "bank_account", name)
    if kind not in ("bank", "card"):
        raise BankError("kind must be bank or card")
    digits = re.sub(r"\D", "", str(last4 or ""))[-4:]
    aid = ledger._acct_id(office, ledger_account)
    with office.db.tx():
        bid = office.db.insert("bank_accounts", name=name, last4=digits,
                               account_id=aid, kind=kind,
                               statement_format=statement_format,
                               column_map=json.dumps(column_map or {}))
        office.audit("create", "bank_account", bid, None,
                     {"name": name, "last4": digits, "kind": kind})
    return bid


def bank_account(office, bid) -> dict:
    b = office.db.get("bank_accounts", bid)
    b["column_map"] = json.loads(b["column_map"] or "{}")
    return b


# ---- parsing -------------------------------------------------------------

def _ofx_date(s):
    s = (s or "").strip()[:8]
    return date(int(s[:4]), int(s[4:6]), int(s[6:8])).isoformat()


def parse_ofx(text: str) -> tuple[list[dict], list[tuple]]:
    """OFX 1.x SGML (tags without closing tags) or OFX 2.x XML -> lines."""
    rows, bad = [], []
    blocks = re.findall(r"<STMTTRN>(.*?)(?:</STMTTRN>|(?=<STMTTRN>)|"
                        r"(?=</BANKTRANLIST>))", text, re.S | re.I)
    for n, b in enumerate(blocks, start=1):
        f = {}
        for tag, val in re.findall(r"<([A-Z0-9.]+)>([^<\r\n]*)", b, re.I):
            f[tag.upper()] = val.strip()
        try:
            amt = cents.parse_amount(f.get("TRNAMT", ""))
            d = _ofx_date(f.get("DTPOSTED", ""))
        except (cents.MoneyError, ValueError) as e:
            bad.append((n, f"transaction {n}: {e}"))
            continue
        rows.append({"date": d, "amount": amt,
                     "payee": f.get("NAME") or f.get("PAYEE") or "",
                     "memo": f.get("MEMO", ""), "bank_id": f.get("FITID", ""),
                     "reference": f.get("CHECKNUM") or f.get("REFNUM") or ""})
    return rows, bad


def _csv_date(s, fmt=""):
    s = (s or "").strip()
    if fmt:
        return datetime.strptime(s, fmt).date().isoformat()
    for f in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%d-%b-%Y"):
        try:
            return datetime.strptime(s, f).date().isoformat()
        except ValueError:
            continue
    raise ValueError(f"date {s!r} can't be read")


def parse_csv(text: str, column_map=None) -> tuple[list[dict], list[tuple]]:
    """CSV with a column map {date, amount | debit+credit, payee, memo,
    reference, date_format}. A row that can't be read is listed with its
    row number (header = row 1) and the reason; nothing is guessed."""
    m = dict(CSV_DEFAULT_MAP, **(column_map or {}))
    rows, bad = [], []
    rd = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
    for n, r in enumerate(rd, start=2):
        try:
            d = _csv_date(r.get(m["date"]), m.get("date_format") or "")
        except ValueError as e:
            bad.append((n, f"row {n}: {e}"))
            continue
        try:
            if m.get("debit") and m.get("credit"):
                dr = (r.get(m["debit"]) or "").strip()
                cr = (r.get(m["credit"]) or "").strip()
                amt = (cents.parse_amount(cr) if cr else 0) - \
                    (cents.parse_amount(dr) if dr else 0)
            else:
                raw = (r.get(m["amount"]) or "").strip()
                amt = cents.parse_amount(raw)
        except cents.MoneyError:
            bad.append((n, f"row {n}: amount {raw!r} can't be read"
                        if not (m.get("debit") and m.get("credit")) else
                        f"row {n}: debit/credit can't be read"))
            continue
        rows.append({"date": d, "amount": amt,
                     "payee": (r.get(m["payee"]) or "").strip(),
                     "memo": (r.get(m.get("memo") or "") or "").strip(),
                     "reference": (r.get(m.get("reference") or "") or
                                   "").strip(), "bank_id": ""})
    return rows, bad


def _hash(bid, r):
    key = f"{bid}|{r['date']}|{r['amount']}|{r['payee'].strip().upper()}|" \
          f"{r['memo'].strip().upper()}"
    return hashlib.sha256(key.encode()).hexdigest()


# ---- import --------------------------------------------------------------

def import_statement(office, bank_account_id, path=None, text=None,
                     fmt=None) -> dict:
    """Read a statement file into the review queue. De-dup on the bank's
    transaction id (OFX FITID), else on date + amount + description.
    Posts nothing."""
    _full(office)
    office.require("bank.edit", "bank_account", bank_account_id)
    b = bank_account(office, bank_account_id)
    if path is not None:
        fileguard.refuse_company_file(path)
        with open(path, encoding="utf-8-sig", errors="replace") as fh:
            text = fh.read()
        if fmt is None:
            fmt = "csv" if str(path).lower().endswith(".csv") else "ofx"
    fmt = (fmt or b["statement_format"] or "ofx").lower()
    if fmt in ("ofx", "qfx"):
        rows, bad = parse_ofx(text)
    elif fmt == "csv":
        rows, bad = parse_csv(text, b["column_map"])
    else:
        raise BankError("statement format must be OFX, QFX or CSV")
    batch = f"IMP-{clock.iso_now()}"
    new = dup = 0
    ids = []
    with office.db.tx():
        for r in rows:
            h = _hash(bank_account_id, r)
            if r["bank_id"]:
                seen = office.db.scalar(
                    "SELECT COUNT(*) FROM statement_lines WHERE "
                    "bank_account_id = ? AND bank_id = ?",
                    (bank_account_id, r["bank_id"]))
            else:
                seen = office.db.scalar(
                    "SELECT COUNT(*) FROM statement_lines WHERE "
                    "bank_account_id = ? AND content_hash = ?",
                    (bank_account_id, h))
            if seen:
                dup += 1
                continue
            ids.append(office.db.insert(
                "statement_lines", bank_account_id=bank_account_id,
                date=r["date"], payee=r["payee"], memo=r["memo"],
                amount=r["amount"], bank_id=r["bank_id"], content_hash=h,
                status="New", import_batch=batch,
                reference=r.get("reference", "")))
            new += 1
        office.audit("import statement", "bank_account", bank_account_id,
                     None, {"new": new, "duplicates": dup,
                            "rejected": [x[1] for x in bad]})
    for lid in ids:
        suggest(office, lid)
    return {"new": new, "duplicates": dup, "rejected": bad, "ids": ids}


def line(office, lid) -> dict:
    ln = office.db.get("statement_lines", lid)
    ln["suggestion"] = json.loads(ln["suggestion"] or "null")
    return ln


def review_queue(office, bank_account_id=None, status=None) -> list[dict]:
    q = "SELECT id FROM statement_lines WHERE deleted = 0"
    p = []
    if bank_account_id:
        q += " AND bank_account_id = ?"
        p.append(bank_account_id)
    if status:
        q += " AND status = ?"
        p.append(status)
    else:
        q += " AND status IN ('New','Suggested')"
    return [line(office, r["id"]) for r in office.db.rows(q + " ORDER BY date, id", p)]


def _check_editable(office, ln):
    if ln["reconciliation_id"]:
        r = office.db.get("reconciliations", ln["reconciliation_id"])
        if r and r["status"] == "Finished":
            raise BankError("This line is in a finished reconciliation and "
                            "can't be changed.")


def edit_line(office, lid, **fields) -> None:
    """Correct a statement line's date, amount, payee or memo (before it is
    reconciled)."""
    _full(office)
    office.require("bank.edit", "statement_line", lid)
    ln = line(office, lid)
    _check_editable(office, ln)
    jl = office.db.one("SELECT j.id, j.entry_id FROM journal_lines j WHERE "
                       "j.statement_line_id = ?", (lid,))
    if jl and _line_reconciled(office, jl["id"]):
        raise BankError("This line is in a finished reconciliation and "
                        "can't be changed.")
    if "amount" in fields:
        fields["amount"] = cents.amount_in(fields["amount"])
    allowed = {k: v for k, v in fields.items() if k in
               ("date", "amount", "payee", "memo")}
    with office.db.tx():
        office.db.update("statement_lines", lid, **allowed)
        office.audit("change", "statement_line", lid,
                     {k: ln[k] for k in allowed}, allowed)


def _line_reconciled(office, journal_line_id) -> bool:
    from . import reconcile
    return reconcile.is_reconciled(office, journal_line_id)


# ---- rules ---------------------------------------------------------------

def add_rule(office, text, account, operator="contains", field="payee",
             job_id=None, cost_code="", priority=100, amount_min=None,
             amount_max=None) -> int:
    _full(office)
    office.require("bank.edit", "bank_rule", text)
    if operator not in OPERATORS:
        raise BankError(f"operator must be one of {', '.join(OPERATORS)}")
    aid = ledger._acct_id(office, account)
    with office.db.tx():
        rid = office.db.insert(
            "bank_rules", priority=priority, field=field, operator=operator,
            text=text, account_id=aid, job_id=job_id, cost_code=cost_code,
            amount_min=None if amount_min is None else
            cents.amount_in(amount_min),
            amount_max=None if amount_max is None else
            cents.amount_in(amount_max), active=1)
        office.audit("create", "bank_rule", rid, None,
                     {"text": text, "operator": operator, "account": aid})
    return rid


def _rule_hits(rule, ln) -> bool:
    val = (ln.get(rule["field"]) or "").upper()
    t = (rule["text"] or "").upper()
    ok = {"contains": t in val, "starts with": val.startswith(t),
          "equals": val == t}[rule["operator"]]
    a = abs(ln["amount"])
    if rule["amount_min"] is not None and a < rule["amount_min"]:
        ok = False
    if rule["amount_max"] is not None and a > rule["amount_max"]:
        ok = False
    return ok


# ---- matching ------------------------------------------------------------

def _near(d1, d2) -> bool:
    return abs((clock.d(d1) - clock.d(d2)).days) <= MATCH_DAYS


def _candidates(office, ln, b) -> list[dict]:
    out = []
    if b["kind"] == "bank" and ln["amount"] > 0:
        for p in office.db.rows(
                "SELECT * FROM payments WHERE void = 0 AND deleted = 0 AND "
                "deposited_on IS NULL AND amount = ?", (ln["amount"],)):
            if _near(p["date"], ln["date"]):
                ref = bool(p["reference"] and ln["reference"] and
                           p["reference"] == ln["reference"])
                out.append({"kind": "payment", "id": p["id"],
                            "label": f"payment {p['reference'] or p['id']} "
                                     f"from {p['customer']} on {p['date']}",
                            "reference": ref})
    if ln["amount"] < 0:
        amt = -ln["amount"]
        used = {r["journal_line_id"] for r in office.db.rows(
            "SELECT journal_line_id FROM statement_lines WHERE "
            "journal_line_id IS NOT NULL")}
        for p in office.db.rows(
                "SELECT bp.*, v.name FROM bill_payments bp JOIN vendors v ON "
                "v.id = bp.vendor_id WHERE bp.void = 0 AND bp.deleted = 0 "
                "AND bp.amount = ?", (amt,)):
            jl = _bank_line_of(office, p["entry_id"], b["account_id"])
            if jl is None or jl in used or not _near(p["date"], ln["date"]):
                continue
            ref = bool(p["reference"] and ln["reference"] and
                       p["reference"] == ln["reference"])
            out.append({"kind": "bill_payment", "id": p["id"],
                        "label": f"{p['method']} {p['reference']} to "
                                 f"{p['name']} on {p['date']}",
                        "reference": ref})
        for inv in office.db.rows(
                "SELECT i.*, v.name FROM ap_invoices i JOIN vendors v ON "
                "v.id = i.vendor_id WHERE i.deleted = 0 AND i.status IN "
                "('Approved','Exported','Partly paid')"):
            if appay.open_bill(office, inv["id"]) == amt:
                out.append({"kind": "bill", "id": inv["id"],
                            "label": f"open bill {inv['number']} "
                                     f"{inv['name']} {inv['invoice_no']}",
                            "reference": False})
    # a reference match outranks the rest
    if any(c["reference"] for c in out):
        out = [c for c in out if c["reference"]]
    return out


def _bank_line_of(office, entry_id, account_id):
    if not entry_id:
        return None
    r = office.db.one("SELECT id FROM journal_lines WHERE entry_id = ? AND "
                      "account_id = ?", (entry_id, account_id))
    return r["id"] if r else None


def suggest(office, lid) -> dict | None:
    """Work out (and store) the suggestion for one line: a matching
    posting, else the first rule that fits. Never posts; never overrides a
    user's own category."""
    ln = line(office, lid)
    if ln["status"] in ("Accepted", "Excluded"):
        return ln["suggestion"]
    b = bank_account(office, ln["bank_account_id"])
    if ln["user_categorized"]:
        s = {"kind": "category", "reason": "categorized by you",
             "account_id": ln["account_id"], "job_id": ln["job_id"],
             "cost_code": ln["cost_code"]}
    else:
        cands = _candidates(office, ln, b)
        s = None
        if len(cands) == 1:
            s = {"kind": "match", "match": cands[0],
                 "reason": f"same amount, within {MATCH_DAYS} days: "
                           f"{cands[0]['label']}"}
        elif len(cands) > 1:
            s = {"kind": "choose", "candidates": cands,
                 "reason": f"{len(cands)} equally good matches: choose one"}
        else:
            for r in office.db.rows("SELECT * FROM bank_rules WHERE active = 1 "
                                    "AND deleted = 0 ORDER BY priority, id"):
                if _rule_hits(r, ln):
                    s = {"kind": "rule", "rule_id": r["id"],
                         "account_id": r["account_id"], "job_id": r["job_id"],
                         "cost_code": r["cost_code"] or "",
                         "reason": f"rule: {r['field']} {r['operator']} "
                                   f"'{r['text']}'"}
                    break
    if s is None and (ln["suggestion"] or {}).get("kind") == "ai":
        return None          # keep an open AI suggestion (aicat) as it is
    with office.db.tx():
        office.db.update("statement_lines", lid,
                         suggestion=json.dumps(s) if s else None,
                         status="Suggested" if s else "New")
    return s


def suggest_all(office, bank_account_id=None) -> int:
    n = 0
    for ln in review_queue(office, bank_account_id):
        if suggest(office, ln["id"]):
            n += 1
    return n


def categorize(office, lid, account, job_id=None, cost_code="") -> None:
    """The user's own category: kept from now on, rules never change it."""
    _full(office)
    office.require("bank.edit", "statement_line", lid)
    aid = ledger._acct_id(office, account)
    old = line(office, lid)["suggestion"]
    with office.db.tx():
        office.db.update("statement_lines", lid, account_id=aid,
                         job_id=job_id, cost_code=cost_code,
                         user_categorized=1)
        office.audit("categorize", "statement_line", lid, None,
                     {"account": aid, "job": job_id, "cost_code": cost_code})
        if old and old.get("kind") == "ai":
            from . import aicat
            aicat.on_categorize(office, lid, old, aid)
            office.db.update("statement_lines", lid, suggestion=None)
    suggest(office, lid)


# ---- accept / exclude ----------------------------------------------------

def _category(office, account_id, cost_code):
    a = ledger.account(office, account_id)
    cat = ""
    if a["type"] == "cogs":
        rev = {v: k for k, v in ledger.DEFAULT_POSTING.items()
               if k.startswith("cat:")}
        cat = (rev.get(a["number"]) or "cat:")[4:]
    return cat


def accept(office, lid, choice=None) -> int | None:
    """Accept a line's suggestion (or, for 'choose', the candidate the user
    picked: choice = (kind, id)). Returns the journal entry id posted, or
    None when the line is linked to a posting that already exists."""
    _full(office)
    office.require("bank.edit", "statement_line", lid)
    ln = line(office, lid)
    if ln["status"] == "Accepted":
        raise BankError("This line is already accepted.")
    b = bank_account(office, ln["bank_account_id"])
    if b["kind"] == "card":
        from . import cards
        if cards.waiting_approval(office, lid):
            raise BankError("This card charge is waiting for approval.")
    s = ln["suggestion"]
    if s is None:
        raise BankError("Pick a category or a match first.")
    if s["kind"] == "choose":
        if choice is None:
            raise BankError("Several postings match this line equally; "
                            "choose one.")
        m = next((c for c in s["candidates"] if (c["kind"], c["id"]) ==
                  tuple(choice)), None)
        if m is None:
            raise BankError("That choice is not one of the matches.")
        s = {"kind": "match", "match": m}
    eid = None
    with office.db.tx():
        if s["kind"] == "match":
            m = s["match"]
            if m["kind"] == "payment":
                p = office.db.get("payments", m["id"])
                eid = ledger.post(office, ln["date"], [
                    {"account": b["account_id"], "debit": ln["amount"],
                     "party": p["customer"], "memo": f"Deposit {ln['payee']}",
                     "statement_line_id": lid},
                    {"account": ledger.default_account(office, "undeposited"),
                     "credit": ln["amount"], "party": p["customer"]}],
                    "deposit", lid, f"Deposit of payment {p['reference']}")
                office.db.update("payments", p["id"], deposited_on=ln["date"])
                _link(office, eid, b["account_id"], lid)
            elif m["kind"] == "bill_payment":
                p = office.db.get("bill_payments", m["id"])
                jl = _bank_line_of(office, p["entry_id"], b["account_id"])
                office.db.update("statement_lines", lid, journal_line_id=jl,
                                 entry_id=p["entry_id"])
                office.db.update("journal_lines", jl, statement_line_id=lid)
            elif m["kind"] == "bill":
                inv = ap.invoice(office, m["id"])
                pid = appay.pay(office, inv["vendor_id"], ln["date"],
                                [(inv["id"], cents.from_cents(-ln["amount"]))],
                                method="card" if b["kind"] == "card" else
                                "bank", reference=ln["reference"] or
                                ln["payee"], bank_number=ledger.account(
                                    office, b["account_id"])["number"])
                eid = office.db.get("bill_payments", pid)["entry_id"]
                _link(office, eid, b["account_id"], lid)
        else:
            acct = s.get("account_id")
            if not acct:
                raise BankError("Pick a category or a match first.")
            job, code = s.get("job_id"), s.get("cost_code") or ""
            cat = _category(office, acct, code)
            amt = ln["amount"]
            other = {"account": acct, "job_id": job, "cost_code": code,
                     "category": cat, "party": ln["payee"],
                     "memo": ln["memo"] or ln["payee"]}
            mine = {"account": b["account_id"], "party": ln["payee"],
                    "statement_line_id": lid}
            if amt < 0:
                lines = [dict(other, debit=-amt), dict(mine, credit=-amt)]
            else:
                lines = [dict(mine, debit=amt), dict(other, credit=amt)]
            eid = ledger.post(office, ln["date"], lines, "statement_line",
                              lid, f"{b['name']}: {ln['payee']}")
            _link(office, eid, b["account_id"], lid)
            if s["kind"] == "rule":
                office.db.conn.execute("UPDATE bank_rules SET times_used = "
                                       "times_used + 1 WHERE id = ?",
                                       (s["rule_id"],))
        office.db.update("statement_lines", lid, status="Accepted")
        office.audit("accept", "statement_line", lid, None,
                     {"suggestion": s, "entry": eid})
        if s.get("kind") == "ai":
            from . import aicat
            aicat.on_accept(office, lid, s, eid)
    return eid


def _link(office, eid, account_id, lid):
    jl = _bank_line_of(office, eid, account_id)
    office.db.update("statement_lines", lid, journal_line_id=jl, entry_id=eid)
    if jl:
        office.db.update("journal_lines", jl, statement_line_id=lid)


def accept_all_suggested(office, bank_account_id) -> list[int]:
    """'Accept all suggested' (still the user's click): every line with one
    clear suggestion; lines needing a choice and AI suggestions (each one
    needs its own click) are left."""
    done = []
    for ln in review_queue(office, bank_account_id, "Suggested"):
        if ln["suggestion"] and ln["suggestion"]["kind"] not in ("choose",
                                                                 "ai"):
            accept(office, ln["id"])
            done.append(ln["id"])
    return done


def exclude(office, lid, reason="") -> None:
    _full(office)
    office.require("bank.edit", "statement_line", lid)
    sug = line(office, lid)["suggestion"] or {}
    with office.db.tx():
        office.db.update("statement_lines", lid, status="Excluded")
        office.audit("exclude", "statement_line", lid, None,
                     {"reason": reason})
        if sug.get("kind") == "ai":
            from . import aitrail
            aitrail.decide(office, sug["ai_log_id"], "rejected",
                           detail={"reason": "line excluded"})
