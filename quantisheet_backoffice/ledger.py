"""Chart of accounts, default posting accounts, the double-entry journal,
trial balance, general ledger and the accounting period close
(P1-18, P1-19, P1-21; manual entries P2-18).

Every journal entry balances to the cent or nothing is saved. Posted
entries are never edited: a void posts an exact reversing entry.
"""
from __future__ import annotations

import csv
import io
from datetime import timedelta

from . import cents, clock

TYPES = ("asset", "liability", "equity", "income", "cogs", "expense",
         "other income", "other expense")
TYPE_WORDS = {"asset": "asset", "assets": "asset", "liability": "liability",
              "liabilities": "liability", "equity": "equity",
              "income": "income", "revenue": "income",
              "cost of goods sold": "cogs", "cogs": "cogs",
              "expense": "expense", "expenses": "expense",
              "other income": "other income", "other expense": "other expense"}
DEBIT_NORMAL = ("asset", "cogs", "expense", "other expense")
SUBTYPES = ("", "bank", "credit card", "ar", "ap", "retainage receivable",
            "retainage payable", "tax payable", "system")
CONTROL_SUBTYPES = ("ar", "ap", "retainage receivable", "retainage payable",
                    "bank", "credit card")

# number, name, type, subtype, system  (our own construction chart)
DEFAULT_CHART = [
    ("1000", "Operating bank", "asset", "bank", 0),
    ("1010", "Payroll bank", "asset", "bank", 0),
    ("1050", "Undeposited funds", "asset", "system", 1),
    ("1100", "Accounts receivable", "asset", "ar", 1),
    ("1150", "Retainage receivable", "asset", "retainage receivable", 1),
    ("1200", "Costs and estimated earnings in excess of billings", "asset", "", 0),
    ("1300", "Stored materials", "asset", "", 0),
    ("1400", "Prepaid expenses", "asset", "", 0),
    ("1500", "Equipment and vehicles", "asset", "", 0),
    ("1550", "Accumulated depreciation", "asset", "", 0),
    ("1600", "Deposits", "asset", "", 0),
    ("2000", "Accounts payable", "liability", "ap", 1),
    ("2050", "Retainage payable", "liability", "retainage payable", 1),
    ("2100", "Billings in excess of costs and estimated earnings", "liability", "", 0),
    ("2200", "Sales tax payable", "liability", "tax payable", 1),
    ("2210", "Use tax payable", "liability", "tax payable", 0),
    ("2300", "Credit card", "liability", "credit card", 0),
    ("2400", "Accrued payroll", "liability", "", 0),
    ("2410", "Payroll liabilities", "liability", "", 0),
    ("2500", "Customer deposits", "liability", "", 0),
    ("2600", "Line of credit", "liability", "", 0),
    ("2700", "Equipment loans", "liability", "", 0),
    ("2800", "Accrued expenses", "liability", "", 0),
    ("3000", "Opening balance equity", "equity", "system", 1),
    ("3100", "Owner contributions", "equity", "", 0),
    ("3200", "Owner draws", "equity", "", 0),
    ("3900", "Retained earnings", "equity", "system", 1),
    ("4000", "Contract revenue", "income", "", 0),
    ("4100", "T&M revenue", "income", "", 0),
    ("4200", "Other job revenue", "income", "", 0),
    ("5010", "Job cost - Labor", "cogs", "", 0),
    ("5020", "Job cost - Material", "cogs", "", 0),
    ("5030", "Job cost - Equipment", "cogs", "", 0),
    ("5040", "Job cost - Subcontract", "cogs", "", 0),
    ("5050", "Job cost - Other", "cogs", "", 0),
    ("6000", "Overhead - Office rent", "expense", "", 0),
    ("6010", "Overhead - Utilities", "expense", "", 0),
    ("6020", "Overhead - Insurance", "expense", "", 0),
    ("6030", "Overhead - Office salaries", "expense", "", 0),
    ("6040", "Overhead - Vehicles and fuel", "expense", "", 0),
    ("6050", "Overhead - Professional fees", "expense", "", 0),
    ("6060", "Overhead - Small tools and supplies", "expense", "", 0),
    ("6070", "Overhead - Depreciation", "expense", "", 0),
    ("6080", "Overhead - Bank and card fees", "expense", "", 0),
    ("6090", "Overhead", "expense", "", 0),
    ("7000", "Interest income", "other income", "", 0),
    ("8000", "Interest expense", "other expense", "", 0),
]
DEFAULT_POSTING = {
    "ar": "1100", "ar_retainage": "1150", "revenue_contract": "4000",
    "revenue_tm": "4100", "revenue_other": "4200", "ap": "2000",
    "ap_retainage": "2050", "undeposited": "1050", "bank": "1000",
    "sales_tax": "2200", "use_tax": "2210", "card": "2300",
    "opening_equity": "3000", "retained": "3900", "overhead": "6090",
    "cat:L": "5010", "cat:M": "5020", "cat:E": "5030", "cat:S": "5040",
    "cat:O": "5050",
}
SYSTEM_NAMES = ("Accounts receivable", "Accounts payable",
                "Retainage receivable", "Retainage payable",
                "Sales tax payable", "Undeposited funds",
                "Opening balance equity", "Retained earnings")


class LedgerError(ValueError):
    pass


class ClosedPeriodError(LedgerError):
    pass


def seed_default_chart(office) -> None:
    db = office.db
    if db.one("SELECT id FROM accounts LIMIT 1"):
        return
    with db.tx():
        for num, name, typ, sub, system in DEFAULT_CHART:
            db.insert("accounts", number=num, name=name, type=typ,
                      subtype=sub, active=1, qb_name=name, sage_gl=num,
                      description="", system=system)
        for key, num in DEFAULT_POSTING.items():
            db.insert("posting_defaults", key=key,
                      account_id=account_by_number(office, num)["id"])


# ---- accounts ------------------------------------------------------------

def account(office, aid) -> dict:
    return office.db.get("accounts", aid)


def account_by_number(office, number) -> dict | None:
    return office.db.one("SELECT * FROM accounts WHERE number = ?",
                         (str(number),))


def account_by_name(office, name) -> dict | None:
    return office.db.one("SELECT * FROM accounts WHERE name = ?", (name,))


def accounts(office, include_inactive=False) -> list[dict]:
    q = "SELECT * FROM accounts WHERE deleted = 0"
    if not include_inactive:
        q += " AND active = 1"
    return office.db.rows(q + " ORDER BY number")


def picker(office) -> list[dict]:
    """Accounts shown in pickers: active only."""
    return accounts(office)


def default_account(office, key) -> int:
    r = office.db.one("SELECT account_id FROM posting_defaults WHERE key = ?",
                      (key,))
    if r is None:
        raise LedgerError(f"no default posting account for {key}")
    return r["account_id"]


def set_default(office, key, account_id) -> None:
    office.require("gl.manage", "posting_default", key)
    with office.db.tx():
        r = office.db.one("SELECT * FROM posting_defaults WHERE key = ?", (key,))
        if r:
            office.db.update("posting_defaults", r["id"], account_id=account_id)
        else:
            office.db.insert("posting_defaults", key=key, account_id=account_id)
        office.audit("change", "posting_default", key,
                     r and r["account_id"], account_id)


def set_cost_code_account(office, code, account_id) -> None:
    office.require("gl.manage", "cost_code_account", code)
    with office.db.tx():
        r = office.db.one("SELECT * FROM cost_code_accounts WHERE cost_code = ?",
                          (code,))
        if r:
            office.db.update("cost_code_accounts", r["id"], account_id=account_id)
        else:
            office.db.insert("cost_code_accounts", cost_code=code,
                             account_id=account_id)
        office.audit("change", "cost_code_account", code, None, account_id)


def cost_account(office, category="", cost_code="", vendor_id=None,
                 job_id=None) -> int:
    """Posting account for a cost: cost code override, then vendor
    override, then the category's job-cost account (or overhead when the
    line has no job)."""
    if cost_code:
        r = office.db.one("SELECT account_id FROM cost_code_accounts WHERE "
                          "cost_code = ? AND deleted = 0", (cost_code,))
        if r:
            return r["account_id"]
    if vendor_id:
        v = office.db.get("vendors", vendor_id)
        if v and v["account_id"]:
            return v["account_id"]
    if job_id is None and not category:
        return default_account(office, "overhead")
    return default_account(office, f"cat:{(category or 'O')[:1].upper()}")


def add_account(office, number, name, type_, subtype="", parent_id=None,
                qb_name="", sage_gl="", description="") -> int:
    office.require("gl.manage", "account", number)
    if type_ not in TYPES:
        raise LedgerError(f"type {type_!r} is not one of {', '.join(TYPES)}")
    if subtype not in SUBTYPES:
        raise LedgerError(f"subtype {subtype!r} is not known")
    if account_by_number(office, number):
        raise LedgerError(f"account number {number} already exists")
    with office.db.tx():
        aid = office.db.insert("accounts", number=str(number), name=name,
                               type=type_, subtype=subtype,
                               parent_id=parent_id, active=1,
                               qb_name=qb_name, sage_gl=sage_gl,
                               description=description, system=0)
        office.audit("create", "account", aid, None,
                     {"number": number, "name": name, "type": type_})
    return aid


def has_lines(office, aid) -> bool:
    return bool(office.db.scalar("SELECT COUNT(*) FROM journal_lines WHERE "
                                 "account_id = ?", (aid,)))


def change_account(office, aid, **fields) -> None:
    office.require("gl.manage", "account", aid)
    a = account(office, aid)
    if a["system"]:
        if "type" in fields and fields["type"] != a["type"]:
            raise LedgerError(f"{a['name']} is a system account; its type "
                              f"can't change")
        if "active" in fields and not fields["active"]:
            raise LedgerError(f"{a['name']} is a system account; it can't "
                              f"be made inactive")
        if "subtype" in fields and fields["subtype"] != a["subtype"]:
            raise LedgerError(f"{a['name']} is a system account; its subtype "
                              f"can't change")
    if "type" in fields and fields["type"] not in TYPES:
        raise LedgerError(f"type {fields['type']!r} is not known")
    with office.db.tx():
        office.db.update("accounts", aid, **fields)
        office.audit("change", "account", aid, {k: a[k] for k in fields}, fields)


def delete_account(office, aid) -> None:
    office.require("gl.manage", "account", aid)
    a = account(office, aid)
    if a["system"]:
        raise LedgerError(f"{a['name']} is a system account and can't be deleted")
    if has_lines(office, aid):
        raise LedgerError(f"{a['number']} {a['name']} has posted lines; make "
                          f"it inactive instead")
    with office.db.tx():
        office.db.soft_delete("accounts", aid)
        office.audit("delete", "account", aid, a, None)


def import_chart_csv(office, path_or_text, apply=True) -> dict:
    """CSV with number,name,type[,subtype,qb_name,sage_gl,description].
    Returns {'imported': [...], 'rejected': [(row, reason)]}; a bad row is
    listed and skipped, the rest go in."""
    from . import fileguard
    office.require("gl.manage", "account", "import")
    if "\n" in str(path_or_text) or "," in str(path_or_text) and \
            not str(path_or_text).lower().endswith(".csv"):
        text = str(path_or_text)
    else:
        fileguard.refuse_company_file(path_or_text)
        with open(path_or_text, encoding="utf-8-sig", newline="") as fh:
            text = fh.read()
    rows = list(csv.DictReader(io.StringIO(text)))
    seen = {a["number"] for a in office.db.rows("SELECT number FROM accounts")}
    ok, bad = [], []
    for i, r in enumerate(rows, start=2):
        r = {(k or "").strip().lower(): (v or "").strip() for k, v in r.items()}
        num, name = r.get("number", ""), r.get("name", "")
        typ = TYPE_WORDS.get(r.get("type", "").lower())
        if not num or not name:
            bad.append((i, "number and name are required"))
        elif typ is None:
            bad.append((i, f"type {r.get('type')!r} is not an account type"))
        elif num in seen:
            bad.append((i, f"account number {num} already exists"))
        elif r.get("subtype", "") not in SUBTYPES:
            bad.append((i, f"subtype {r.get('subtype')!r} is not known"))
        else:
            seen.add(num)
            ok.append((num, name, typ, r))
    if apply:
        with office.db.tx():
            for num, name, typ, r in ok:
                office.db.insert("accounts", number=num, name=name, type=typ,
                                 subtype=r.get("subtype", ""), active=1,
                                 qb_name=r.get("qb_name", ""),
                                 sage_gl=r.get("sage_gl", ""),
                                 description=r.get("description", ""),
                                 system=0)
            office.audit("import", "account", "chart", None,
                         {"imported": len(ok), "rejected": bad})
    return {"imported": [o[0] for o in ok], "rejected": bad}


# ---- period close (P1-21) ------------------------------------------------

def closed_through(office) -> str | None:
    r = office.db.one("SELECT closed_through FROM period_closes WHERE "
                      "active = 1 ORDER BY id DESC LIMIT 1")
    return r["closed_through"] if r else None


def check_open(office, date) -> None:
    ct = closed_through(office)
    if ct and str(date)[:10] <= ct:
        raise ClosedPeriodError(f"Books are closed through {ct}")


def first_open_date(office, date) -> str:
    ct = closed_through(office)
    d = str(date)[:10]
    if ct and d <= ct:
        return (clock.d(ct) + timedelta(days=1)).isoformat()
    return d


def close_books(office, through) -> None:
    office.require("period.close", "period", through)
    with office.db.tx():
        for r in office.db.rows("SELECT id FROM period_closes WHERE active = 1"):
            office.db.update("period_closes", r["id"], active=0)
        office.db.insert("period_closes", closed_through=str(through),
                         closed_by=office.who, ts=clock.iso_now(), active=1)
        office.audit("close books", "period", through, None,
                     {"closed_through": str(through)})


def reopen_books(office, reason) -> None:
    if office.role != "Admin":
        office.audit("denied", "period", "", None,
                     {"permission": "period.reopen", "role": office.role})
        from .security import Denied
        raise Denied("Only an Admin can reopen the books.")
    if not (reason or "").strip():
        raise LedgerError("A reason is required to reopen the books.")
    with office.db.tx():
        r = office.db.one("SELECT * FROM period_closes WHERE active = 1 "
                          "ORDER BY id DESC LIMIT 1")
        if r is None:
            raise LedgerError("The books are not closed.")
        office.db.update("period_closes", r["id"], active=0,
                         reopened_by=office.who, reopen_reason=reason,
                         reopened_at=clock.iso_now())
        office.audit("reopen books", "period", r["closed_through"],
                     {"closed_through": r["closed_through"]},
                     {"reason": reason})


# ---- journal (P1-19) -----------------------------------------------------

def _acct_id(office, a) -> int:
    if isinstance(a, int):
        return a
    r = account_by_number(office, a) or account_by_name(office, a)
    if r is None:
        raise LedgerError(f"no account {a!r}")
    return r["id"]


def post(office, date, lines, source_type="", source_id=None, memo="",
         reverses_id=None, auto_reverse=0, batch_id=None,
         check_period=True) -> int:
    """Post one balanced entry. lines: [{account, debit, credit, job_id,
    cost_code, category, party, memo}] with int cents. Debits must equal
    credits to the cent or nothing is saved (and the attempt is logged)."""
    db = office.db
    clean = []
    for ln in lines:
        dr, cr = ln.get("debit", 0) or 0, ln.get("credit", 0) or 0
        if not all(isinstance(x, int) and not isinstance(x, bool)
                   for x in (dr, cr)):
            raise LedgerError("journal amounts must be int cents")
        # A negative amount belongs on the other side (an AP credit memo's
        # negative cost line is a credit, its negative AP line a debit).
        net = dr - cr
        dr, cr = (net, 0) if net > 0 else (0, -net)
        if dr == 0 and cr == 0:
            continue
        clean.append({**ln, "account_id": _acct_id(office, ln["account"]),
                      "debit": dr, "credit": cr})
    td = sum(x["debit"] for x in clean)
    tc = sum(x["credit"] for x in clean)
    if td != tc or not clean:
        diff = td - tc
        office.audit("post refused", source_type, source_id, None,
                     {"debits": td, "credits": tc, "difference": diff,
                      "memo": memo})
        raise LedgerError(f"Debits {cents.fmt(td)} and credits {cents.fmt(tc)} "
                          f"differ by {cents.fmt(abs(diff))}; nothing was "
                          f"posted.")
    if check_period:
        try:
            check_open(office, date)
        except ClosedPeriodError:
            office.audit("post refused", source_type, source_id, None,
                         {"reason": "closed period", "date": str(date)})
            raise
    with db.tx():
        number = db.next_number("JE", "JE-{n:06d}")
        eid = db.insert("journal_entries", number=number, date=str(date)[:10],
                        source_type=source_type, source_id=source_id,
                        memo=memo, posted_by=office.who,
                        posted_at=clock.iso_now(), reverses_id=reverses_id,
                        auto_reverse=auto_reverse, batch_id=batch_id)
        for x in clean:
            db.insert("journal_lines", entry_id=eid, account_id=x["account_id"],
                      debit=x["debit"], credit=x["credit"],
                      job_id=x.get("job_id"), cost_code=x.get("cost_code"),
                      category=x.get("category"), party=x.get("party"),
                      memo=x.get("memo") or memo,
                      cash_date=x.get("cash_date"))
        office.audit("post", "journal_entry", eid, None,
                     {"number": number, "date": str(date)[:10],
                      "source": f"{source_type}:{source_id}", "total": td})
    return eid


def entry(office, eid) -> dict:
    e = office.db.get("journal_entries", eid)
    e["lines"] = office.db.rows("SELECT * FROM journal_lines WHERE entry_id = ? "
                                "ORDER BY id", (eid,))
    return e


def entries_for(office, source_type, source_id) -> list[dict]:
    return [entry(office, r["id"]) for r in office.db.rows(
        "SELECT id FROM journal_entries WHERE source_type = ? AND "
        "source_id = ? ORDER BY id", (source_type, source_id))]


def reverse(office, eid, date, memo="") -> int:
    """Exact reversing entry dated `date` (or the first open day after a
    close); the original stays."""
    e = entry(office, eid)
    if e["reversed_by_id"]:
        raise LedgerError(f"{e['number']} is already reversed")
    d = first_open_date(office, date)
    lines = [{"account": ln["account_id"], "debit": ln["credit"],
              "credit": ln["debit"], "job_id": ln["job_id"],
              "cost_code": ln["cost_code"], "category": ln["category"],
              "party": ln["party"], "memo": ln["memo"]}
             for ln in e["lines"]]
    with office.db.tx():
        rid = post(office, d, lines, e["source_type"], e["source_id"],
                   memo or f"Reverses {e['number']}", reverses_id=eid)
        office.db.update("journal_entries", eid, reversed_by_id=rid)
    return rid


def reverse_source(office, source_type, source_id, date) -> list[int]:
    out = []
    for e in entries_for(office, source_type, source_id):
        if not e["reversed_by_id"] and not e["reverses_id"]:
            out.append(reverse(office, e["id"], date))
    return out


# ---- manual journal entries (P2-18) --------------------------------------

def post_manual(office, date, lines, memo="", auto_reverse=False,
                attachment="") -> int:
    office.require_full_books("Manual journal entries")
    office.require("gl.journal", "journal_entry", "manual")
    for ln in lines:
        a = account(office, _acct_id(office, ln["account"]))
        if a["subtype"] in ("ar", "ap", "retainage receivable",
                            "retainage payable"):
            raise LedgerError(f"{a['name']} is a control account: use an "
                              f"invoice or bill")
        if a["subtype"] in ("bank", "credit card"):
            raise LedgerError(f"{a['name']} is a bank account: use banking "
                              f"or a payment")
    with office.db.tx():
        eid = post(office, date, lines, "manual", None,
                   memo + (f" [{attachment}]" if attachment else ""),
                   auto_reverse=int(bool(auto_reverse)))
        office.db.update("journal_entries", eid, source_id=eid)
        if auto_reverse:
            d = clock.d(date)
            nxt = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
            rid = reverse(office, eid, nxt.isoformat(),
                          f"Auto-reversal of {entry(office, eid)['number']}")
            office.db.update("journal_entries", rid, source_id=eid)
    return eid


# ---- reports -------------------------------------------------------------

def _sign(a) -> int:
    return 1 if a["type"] in DEBIT_NORMAL else -1


def balances(office, as_of=None, date_from=None, basis="accrual",
             job_id=None) -> dict:
    """{account_id: debit-minus-credit cents} over the date range."""
    q = ("SELECT l.account_id, SUM(l.debit) AS d, SUM(l.credit) AS c "
         "FROM journal_lines l JOIN journal_entries e ON e.id = l.entry_id "
         "WHERE 1=1")
    p = []
    datecol = "e.date" if basis == "accrual" else \
        "COALESCE(l.cash_date, e.date)"
    if basis == "cash":
        q += " AND (l.cash_date IS NOT NULL OR e.source_type NOT IN " \
             "('ar_invoice', 'ap_invoice'))"
    if as_of:
        q += f" AND {datecol} <= ?"
        p.append(str(as_of))
    if date_from:
        q += f" AND {datecol} >= ?"
        p.append(str(date_from))
    if job_id is not None:
        q += " AND l.job_id = ?"
        p.append(job_id)
    q += " GROUP BY l.account_id"
    return {r["account_id"]: (r["d"] or 0) - (r["c"] or 0)
            for r in office.db.rows(q, p)}


def trial_balance(office, as_of=None) -> dict:
    bal = balances(office, as_of)
    rows = []
    for a in accounts(office, include_inactive=True):
        b = bal.get(a["id"], 0)
        if b == 0:
            continue
        rows.append({"number": a["number"], "name": a["name"],
                     "type": a["type"], "debit": b if b > 0 else 0,
                     "credit": -b if b < 0 else 0, "account_id": a["id"]})
    td = sum(r["debit"] for r in rows)
    tc = sum(r["credit"] for r in rows)
    return {"rows": rows, "debits": td, "credits": tc, "as_of": as_of}


def balance(office, number_or_id, as_of=None) -> int:
    """Natural balance (positive = normal side) of one account."""
    aid = _acct_id(office, number_or_id)
    a = account(office, aid)
    return balances(office, as_of).get(aid, 0) * _sign(a)


def general_ledger(office, number_or_id, date_from=None, date_to=None):
    aid = _acct_id(office, number_or_id)
    q = ("SELECT e.number, e.date, e.source_type, e.source_id, e.memo, "
         "l.debit, l.credit, l.job_id, l.cost_code, l.party, l.id AS line_id "
         "FROM journal_lines l JOIN journal_entries e ON e.id = l.entry_id "
         "WHERE l.account_id = ?")
    p = [aid]
    if date_from:
        q += " AND e.date >= ?"
        p.append(str(date_from))
    if date_to:
        q += " AND e.date <= ?"
        p.append(str(date_to))
    rows = office.db.rows(q + " ORDER BY e.date, e.id, l.id", p)
    run = 0
    for r in rows:
        run += r["debit"] - r["credit"]
        r["running"] = run
    return rows
