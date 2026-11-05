"""Job costing: budget vs committed vs actual by cost code (P1-07).

Computed, never stored. Same definitions as QuantiSheet's Cost Summary:
  revised budget = original + approved changes (as QuantiSheet sends it)
  committed      = commitment schedule-of-values lines
  actual         = approved time x loaded rate (estimated until the pay
                   period is final; then payroll gross + fringes + burden,
                   P2-01/P2-02) + approved AP invoice lines
                   + QuantiSheet direct costs + bank and card charges
                   coded to the job (P2-09)
                   + approved per diem (r38 G2.1; its own column, not labor)
  labor is shown split as regular (REG, PTO, HOL) and overtime (OT, DT),
  with hours (r38 G2.5)
  remaining      = revised - actual
  cost to complete = what's left of the larger of revised and committed
  variance       = revised - (actual + cost to complete)
Back Office never writes actuals back into QuantiSheet (decision 4 = A).

A published Job Cost Report (r111.sagejc) overlays its own codes: original
estimate, total estimate, total committed and JTD cost replace the books
figures for those codes only, and overrun is set from the report. Codes
the report does not mention are unchanged. Nothing is written back into
the snapshot; unpublish drops the overlay.
"""
from __future__ import annotations

from . import cents, jobs, payroll, perdiem, timeentry

AP_COUNTED = ("Approved", "Exported", "Partly paid", "Paid")
OVERTIME = ("OT", "DT")      # r38 G2.5: overtime labor; REG/PTO/HOL regular


def _in(d, date_from, date_to):
    return (not date_from or d >= str(date_from)) and \
        (not date_to or d <= str(date_to))


def _vkey(name) -> str:
    """Vendor names compared loosely: case, punctuation and company
    suffixes (LLC, Inc...) don't matter."""
    import re
    t = re.sub(r"[^a-z0-9& ]+", " ", str(name or "").lower())
    t = re.sub(r"\bl\s+l\s+c\b", "llc", t)
    w = t.split()
    while w and w[-1] in ("llc", "inc", "co", "corp", "company", "ltd",
                          "lp", "llp", "pllc"):
        w.pop()
    return " ".join(w)


def _ikey(number) -> str:
    import re
    return re.sub(r"[^a-z0-9]", "", str(number or "").lower())


def _days(a, b) -> int:
    import datetime as _dt
    try:
        return abs((_dt.date.fromisoformat(str(a)[:10]) -
                    _dt.date.fromisoformat(str(b)[:10])).days)
    except ValueError:
        return 9999


def duplicate_of(d, ap_invoices) -> dict | None:
    """The Back Office AP invoice a QuantiSheet direct cost repeats, or
    None (PM review NW-11: the same $210,000 sub invoice entered in both
    was counted twice). Same vendor and invoice number; without a number,
    same vendor and amount within 7 days."""
    vk, ik = _vkey(d.get("vendor")), _ikey(d.get("invoice"))
    amt = cents.to_cents(d.get("amount") or "0")
    for a in ap_invoices:
        if not vk or _vkey(a["vendor"]) != vk:
            continue
        if ik and _ikey(a["invoice_no"]) == ik:
            return a
        if not ik and a["total"] == amt and \
                _days(a["invoice_date"], d.get("date")) <= 7:
            return a
    return None


def job_cost(office, job_id, date_from=None, date_to=None, category=None,
             duplicates=None):
    """Rows by cost code. A QuantiSheet direct cost that repeats an AP
    invoice already in Back Office is counted once (the AP invoice) and
    listed in `duplicates` (a list the caller passes) with both sides."""
    rows = {}

    def row(code, desc="", cat=""):
        r = rows.setdefault(code or "(no code)", {
            "code": code or "(no code)", "description": desc,
            "category": cat, "original": 0, "revised": 0, "committed": 0,
            "labor": 0, "ap": 0, "direct": 0, "per_diem": 0, "hours": 0,
            "labor_regular": 0, "labor_overtime": 0, "hours_regular": 0,
            "hours_overtime": 0,
            "budget_hours": 0, "sources": []})
        if desc and not r["description"]:
            r["description"] = desc
        if cat and not r["category"]:
            r["category"] = cat
        return r

    for c in jobs.section(office, job_id, "cost_codes"):
        row(c["code"], c["description"], c["category"])
    for b in jobs.section(office, job_id, "budget"):
        r = row(b["code"], b["description"], b["category"])
        r["original"] += cents.to_cents(b["original"])
        r["revised"] += cents.to_cents(b["revised"])
    for e in jobs.section(office, job_id, "estimate"):
        if e["unit"].lower() in ("h", "hr", "hrs", "hour", "hours", "mh"):
            row(e["code"])["budget_hours"] += cents.hours(e["quantity"])
    for c in jobs.section(office, job_id, "commitments"):
        for ln in c["lines"]:
            r = row(ln["cost_code"], ln["description"])
            r["committed"] += cents.to_cents(ln["amount"])
    actuals = payroll.labor_actuals(office)
    for ln in timeentry.approved_lines(office, job_id, date_from, date_to):
        r = row(ln["cost_code"], cat="L")
        act = actuals.get(ln["id"])
        cost = act["amount"] if act else timeentry.labor_cost(office, ln)
        r["labor"] += cost
        r["hours"] += ln["hours"]
        part = "overtime" if ln["pay_type"] in OVERTIME else "regular"
        r["labor_" + part] += cost                      # r38 G2.5
        r["hours_" + part] += ln["hours"]
        if act is None:
            r["labor_est"] = r.get("labor_est", 0) + cost
        r["sources"].append({"type": "time_line", "id": ln["id"],
                             "date": ln["date"], "who": ln["worker"],
                             "hours": ln["hours"], "amount": cost,
                             "estimated": act is None})
    for p in perdiem.approved(office, job_id, date_from, date_to):   # r38 G2.1
        r = row(p["cost_code"])
        r["per_diem"] += p["amount"]
        r["sources"].append({"type": "per_diem", "id": p["id"],
                             "date": p["date"], "who": p["worker"],
                             "kind": p["kind"], "amount": p["amount"]})
    q = ("SELECT l.*, i.number, i.invoice_date, i.status, v.name AS vendor "
         "FROM ap_lines l JOIN ap_invoices i ON i.id = l.invoice_id "
         "JOIN vendors v ON v.id = i.vendor_id WHERE l.job_id = ? AND "
         "l.deleted = 0 AND i.deleted = 0 AND i.status IN (%s)" %
         ",".join("?" * len(AP_COUNTED)))
    for ln in office.db.rows(q, (job_id, *AP_COUNTED)):
        if not _in(ln["invoice_date"], date_from, date_to):
            continue
        r = row(ln["cost_code"], cat=ln["category"])
        r["ap"] += ln["amount"]
        r["sources"].append({"type": "ap_line", "id": ln["id"],
                             "date": ln["invoice_date"],
                             "who": ln["vendor"], "doc": ln["number"],
                             "amount": ln["amount"]})
    inv_q = ("SELECT i.id, i.number, i.invoice_no, i.invoice_date, "
             "v.name AS vendor, "
             "SUM(l.amount) AS total FROM ap_invoices i JOIN vendors v ON "
             "v.id = i.vendor_id JOIN ap_lines l ON l.invoice_id = i.id "
             "WHERE l.job_id = ? AND l.deleted = 0 AND i.deleted = 0 AND "
             "i.status IN (%s) GROUP BY i.id" %
             ",".join("?" * len(AP_COUNTED)))
    ap_invoices = office.db.rows(inv_q, (job_id, *AP_COUNTED))
    for d in jobs.section(office, job_id, "direct_costs"):
        if not _in(d["date"], date_from, date_to):
            continue
        dup = duplicate_of(d, ap_invoices)
        if dup is not None:
            if duplicates is not None:
                duplicates.append({"direct_cost": d.get("id"),
                                   "vendor": d.get("vendor"),
                                   "invoice": d.get("invoice"),
                                   "amount": cents.to_cents(d["amount"]),
                                   "ap_invoice": dup["id"],
                                   "ap_number": dup["number"]})
            continue                      # counted once, as the AP invoice
        r = row(d["cost_code"], d.get("description", ""), d["category"])
        amt = cents.to_cents(d["amount"])
        r["direct"] += amt
        r["sources"].append({"type": "direct_cost", "id": d["id"],
                             "date": d["date"], "who": d["vendor"],
                             "doc": d["invoice"], "amount": amt})
    q = ("SELECT jl.*, e.date, sl.payee, b.kind FROM journal_lines jl JOIN "
         "journal_entries e ON e.id = jl.entry_id JOIN statement_lines sl ON "
         "sl.id = e.source_id JOIN bank_accounts b ON b.id = "
         "sl.bank_account_id WHERE e.source_type = 'statement_line' AND "
         "jl.job_id = ? AND e.reversed_by_id IS NULL AND e.reverses_id IS "
         "NULL AND jl.deleted = 0")
    for ln in office.db.rows(q, (job_id,)):
        if not _in(ln["date"], date_from, date_to):
            continue
        amt = (ln["debit"] or 0) - (ln["credit"] or 0)
        r = row(ln["cost_code"], cat=ln["category"] or "")
        r["direct"] += amt
        r["sources"].append({"type": f"{ln['kind']}_charge", "id": ln["id"],
                             "date": ln["date"], "who": ln["payee"],
                             "amount": amt})
    sage = _sage_published(office, job_id)
    for code, s in sage.items():
        row(code, s.get("description") or "", "")
    out = []
    for r in sorted(rows.values(), key=lambda r: r["code"]):
        if category and r["category"] != category:
            continue
        r["actual"] = r["labor"] + r["ap"] + r["direct"] + r["per_diem"]
        r["remaining"] = r["revised"] - r["actual"]
        r["pct_spent"] = cents.percent_text(r["actual"], r["revised"])
        etc = max(max(r["revised"], r["committed"]) - r["actual"], 0)
        r["cost_to_complete"] = etc
        r["forecast"] = r["actual"] + etc
        r["variance"] = r["revised"] - r["forecast"]
        r["labor_estimated"] = r.pop("labor_est", 0) > 0
        s = sage.get(r["code"])
        if s:
            # Books figures stay on the row (books_*) so unpublish, or a
            # later read with the report withdrawn, is not the only copy.
            r["books_original"] = r["original"]
            r["books_revised"] = r["revised"]
            r["books_committed"] = r["committed"]
            r["books_actual"] = r["actual"]
            r["original"] = s["original"]
            r["revised"] = s["total_estimate"]
            r["committed"] = s["committed"]
            r["actual"] = s["jtd"]
            r["remaining"] = r["revised"] - r["actual"]
            r["pct_spent"] = cents.percent_text(r["actual"], r["revised"])
            etc = max(max(r["revised"], r["committed"]) - r["actual"], 0)
            r["cost_to_complete"] = etc
            r["forecast"] = r["actual"] + etc
            r["variance"] = s["variance"]
            r["overrun"] = bool(s["overrun"])
            r["actual_from_report"] = True
            r["sources"].append({"type": "sage_jtd", "id": s["import_id"],
                                 "date": s.get("imported_on") or "",
                                 "doc": s.get("source_name") or "",
                                 "amount": s["jtd"]})
        out.append(r)
    return out


def _sage_published(office, job_id) -> dict:
    from .r111.sagejc import published_map
    return published_map(office, job_id)


def by_code(office, job_id, **kw) -> dict:
    return {r["code"]: r for r in job_cost(office, job_id, **kw)}


def totals(office, job_id, **kw) -> dict:
    dups = []
    rows = job_cost(office, job_id, duplicates=dups, **kw)
    keys = ("original", "revised", "committed", "labor", "ap", "direct",
            "per_diem", "actual", "remaining", "labor_regular",
            "labor_overtime", "hours_regular", "hours_overtime")
    t = {k: sum(r[k] for r in rows) for k in keys}
    t["by_category"] = {}
    for r in rows:
        c = r["category"] or "O"
        t["by_category"][c] = t["by_category"].get(c, 0) + r["actual"]
    t["duplicates"] = dups
    return t


def labor_hours(office, job_id, **kw) -> list[dict]:
    return [{"code": r["code"], "budget_hours": r["budget_hours"],
             "actual_hours": r["hours"]} for r in job_cost(office, job_id, **kw)
            if r["budget_hours"] or r["hours"]]
