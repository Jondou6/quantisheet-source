"""Back-office assistant (P3-01) and 'Ask the books' (addendum P3-06).

How a question is answered:
1. Questions about personal or pay data (SSN, bank, date of birth, pay
   rates...) are declined by a fixed rule.
2. The local model (localai, chosen in Settings > AI) routes the question
   to ONE built-in tool from a fixed list and picks its words (job, cost
   code, period phrase, payee, account). Anything it says that is not on
   the list is ignored. The question is scrubbed of personal data first.
3. Decision 6.3 = A (DECIDED, Jon, Oct 22, 2026): with no model installed,
   chosen or running, the box says 'AI is unavailable' and offers a plain
   search of the books; it NEVER falls back to keywords on its own. Every
   report still runs from the menus.
4. Dates ('this quarter', 'last week', 'September', 'Q3', 'this year') are
   worked out here in code, never by the model.
5. The tool computes the answer with the same functions the reports use and
   the answer names the report, its dates and filters and the records it
   read. No number in an answer comes from the model.
6. Changes (recode time, bulk recategorize, draft a journal entry, add a
   bank rule) are shown as a before/after list and made only on Apply;
   each is logged and can be undone (actions.py).
Every question is logged in ai_actions (scrubbed question, tool, records
read, answer, model and version).
"""
from __future__ import annotations

import calendar
import json
import re
from datetime import date, timedelta
from decimal import InvalidOperation

from . import (actions, aiguard, ap, appay, approvals, cents, clock, jobcost,
               jobs, ledger, localai, payments, reports, timeentry, waivers)

UNAVAILABLE = ("AI is unavailable: no local model is installed or running "
               "(Settings > AI). Every report still runs from the menus. "
               "Plain search of the books:")

PERSONAL = re.compile(
    r"\b(ssn|social security|bank account|routing|account number|date of "
    r"birth|dob|birthday|pay ?rate|salary|salaries|wage|wages|home address|"
    r"tax id|tin|i-?9|w-?4|garnish)", re.I)
TOOLS = {
    "missing_time": "workers who have not turned in time (job, period)",
    "job_cost": "job cost actuals (job, cost code or trade, period)",
    "wip": "percent complete, earned, over/under billing (job, as of)",
    "payables": "open bills we owe vendors (vendor)",
    "receivables": "open invoices customers owe us (customer or job)",
    "cash": "bank and card balances (as of)",
    "approvals": "approvals that are stalled / overdue",
    "waivers": "lien waivers still missing",
    "over_commitment": "vendor invoices over their commitment",
    "pl": "profit and loss report (period)",
    "recode_time": "PROPOSE moving hours to another cost code "
                   "(worker, date, hours, from code, to code)",
    "recategorize": "PROPOSE moving accepted bank/card lines to another "
                    "account (payee, period, account)",
    "journal": "PROPOSE a journal entry (date, amount, debit_account, "
               "credit_account, memo)",
    "add_rule": "PROPOSE a bank rule (text, account)",
}
ROUTER_SYSTEM = (
    "You route a bookkeeper's question to one tool. Tools: " +
    "; ".join(f"{k}: {v}" for k, v in TOOLS.items()) +
    ". Answer only JSON: {\"tool\": \"<tool or empty>\", \"job\": \"<job "
    "number or name or empty>\", \"cost_code\": \"<code or trade word or "
    "empty>\", \"period\": \"<the period words from the question or "
    "empty>\", \"vendor\": \"\", \"customer\": \"\", \"worker\": \"\", "
    "\"hours\": \"\", \"from_code\": \"\", \"to_code\": \"\", \"date\": \"\", "
    "\"payee\": \"\", \"account\": \"\", \"amount\": \"\", "
    "\"debit_account\": \"\", \"credit_account\": \"\", \"text\": \"\", "
    "\"memo\": \"\"}."
    " Never answer the question yourself.")
HELP = ("Try: 'Pull this quarter's P&L', "
        "'Who hasn't turned in time for last week on job 2611?', "
        "'What did we spend on job 2611 concrete last month?', "
        "'Are we over-billed on 2611?', 'What do we owe vendors?', "
        "'Which approvals are stalled?', 'Which lien waivers are missing?'")


class AssistantError(RuntimeError):
    pass


# ---- dates -------------------------------------------------------------

MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
MONTHS.update({m.lower(): i for i, m in enumerate(calendar.month_abbr) if m})


def _month(y, m):
    return date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])


def resolve_period(text: str, today=None) -> dict:
    """Period words -> {'from', 'to', 'label'} (ISO dates). Empty or
    unknown words -> everything up to today ('to date')."""
    t = (text or "").lower()
    today = today or clock.today()
    iso = re.findall(r"\b(\d{4}-\d{2}-\d{2})\b", t)
    if len(iso) >= 2:
        a, b = sorted(iso[:2])
        return {"from": a, "to": b, "label": f"{a} to {b}"}
    if len(iso) == 1 and re.search(r"\b(as of|through|thru|until|by|on)\s+"
                                   + iso[0], t):
        return {"from": None, "to": iso[0], "label": f"to {iso[0]}"}
    if "last week" in t or "previous week" in t:
        we = clock.d(jobs.week_ending(today)) - timedelta(days=7)
        return {"from": (we - timedelta(days=6)).isoformat(),
                "to": we.isoformat(), "label": f"week ending {we}",
                "week_ending": we.isoformat()}
    if "this week" in t:
        we = clock.d(jobs.week_ending(today))
        return {"from": (we - timedelta(days=6)).isoformat(),
                "to": we.isoformat(), "label": f"week ending {we}",
                "week_ending": we.isoformat()}
    if "last month" in t or "previous month" in t:
        y, m = (today.year, today.month - 1) if today.month > 1 else \
            (today.year - 1, 12)
        a, b = _month(y, m)
        return {"from": a.isoformat(), "to": b.isoformat(),
                "label": a.strftime("%B %Y")}
    qs = 3 * ((today.month - 1) // 3) + 1
    if re.search(r"\b(this|current) quarter|quarter to date|\bqtd\b", t):
        a, _ = _month(today.year, qs)
        return {"from": a.isoformat(), "to": today.isoformat(),
                "label": f"Q{(qs + 2) // 3} {today.year} to date"}
    if re.search(r"\b(last|previous|prior) quarter", t):
        y, m = (today.year, qs - 3) if qs > 1 else (today.year - 1, 10)
        a, _ = _month(y, m)
        _, b = _month(y, m + 2)
        return {"from": a.isoformat(), "to": b.isoformat(),
                "label": f"Q{(m + 2) // 3} {y}"}
    if "this month" in t or "month to date" in t:
        a, _ = _month(today.year, today.month)
        return {"from": a.isoformat(), "to": today.isoformat(),
                "label": f"{a.strftime('%B %Y')} to date"}
    q = re.search(r"\bq([1-4])\b", t)
    if q:
        n = int(q.group(1))
        a, _ = _month(today.year, 3 * n - 2)
        _, b = _month(today.year, 3 * n)
        return {"from": a.isoformat(), "to": b.isoformat(),
                "label": f"Q{n} {today.year}"}
    if "last year" in t:
        y = today.year - 1
        return {"from": f"{y}-01-01", "to": f"{y}-12-31", "label": str(y)}
    if "this year" in t or "year to date" in t or "ytd" in t:
        return {"from": f"{today.year}-01-01", "to": today.isoformat(),
                "label": f"{today.year} to date"}
    for w in re.findall(r"[a-z]+", t):
        if w in MONTHS and w not in ("may",) or (w == "may" and
                                                  "in may" in t):
            m = MONTHS[w]
            y = today.year if m <= today.month else today.year - 1
            yr = re.search(r"\b" + w + r"\w*\s+(\d{4})\b", t)
            if yr:
                y = int(yr.group(1))
            a, b = _month(y, m)
            return {"from": a.isoformat(), "to": b.isoformat(),
                    "label": a.strftime("%B %Y")}
    return {"from": None, "to": today.isoformat(), "label": "to date"}


# ---- words -> records -------------------------------------------------------

def find_job(office, text) -> dict | None:
    t = (text or "").lower()
    js = jobs.jobs(office)
    for j in js:
        if re.search(r"(?<![\w-])" + re.escape(str(j["number"]).lower()) +
                     r"(?![\w-])", t):
            return j
    for j in js:
        name = (j["name"] or "").lower()
        if name and (name in t or any(
                w in t for w in name.split() if len(w) > 4 and
                w not in ("example",))):
            return j
    return js[0] if len(js) == 1 and not t.strip() else None


def find_code(office, job_id, text) -> dict | None:
    t = (text or "").lower()
    codes = jobs.section(office, job_id, "cost_codes") if job_id else []
    m = re.search(r"\b\d{2}-\d{4}\b", t)
    if m:
        return next((c for c in codes if c["code"] == m.group(0)),
                    {"code": m.group(0), "description": ""})
    for c in codes:
        d = (c["description"] or "").lower()
        if d and (d in t or any(w in t for w in d.split() if len(w) > 3)):
            return c
    return None


# ---- tools -----------------------------------------------------------------

def _need_job(job):
    if job is None:
        raise AssistantError("Which job? Name the job number, e.g. 2611.")


def tool_missing_time(office, job, period, **_):
    if not (office.can("time.approve") or office.can("time.edit")):
        raise AssistantError("Missing time needs a time role.")
    we = period.get("week_ending") or jobs.week_ending(
        clock.d(period["to"]) if period.get("to") else clock.today())
    rep = timeentry.missing_time_report(office, we, job["id"] if job else
                                        None)
    where = f" on job {job['number']}" if job else ""
    if not rep:
        text = f"Everyone has turned in time{where} for the week ending {we}."
    else:
        parts = [f"{n} ({', '.join(d[5:] for d in ds)})"
                 for n, ds in rep.items()]
        text = (f"{len(rep)} worker(s) with no submitted or approved hours "
                f"on a workday{where}, week ending {we}: " +
                "; ".join(parts) + ". Same list as the Missing Time report.")
    return {"text": text, "data": rep,
            "records": [f"missing_time_report:{we}"]}


def tool_job_cost(office, job, period, code=None, **_):
    _need_job(job)
    kw = {"date_from": period.get("from"), "date_to": period.get("to")}
    rows = jobcost.job_cost(office, job["id"], **kw)
    if code:
        rows = [r for r in rows if r["code"] == code["code"]]
    act = sum(r["actual"] for r in rows)
    lab = sum(r["labor"] for r in rows)
    apc = sum(r["ap"] for r in rows)
    dct = sum(r["direct"] for r in rows)
    recs = [f"{s['type']}:{s['id']}" for r in rows for s in r["sources"]]
    what = f"{code['code']} {code.get('description', '')}".strip() \
        if code else "all cost codes"
    text = (f"Job {job['number']} {job['name']}, {what}, {period['label']}: "
            f"{cents.fmt(act)} actual cost (labor {cents.fmt(lab)}, vendor "
            f"invoices {cents.fmt(apc)}, direct {cents.fmt(dct)}) from "
            f"{len(recs)} record(s).")
    return {"text": text, "data": {"actual": act, "labor": lab, "ap": apc,
                                   "direct": dct}, "records": recs}


def tool_wip(office, job, period, **_):
    from . import wip
    rows = wip.wip(office, period["to"], [job["id"]] if job else None)
    if not rows:
        return {"text": "No jobs with a contract yet.", "data": [],
                "records": []}
    parts = []
    for r in rows:
        ob = r["over_under"]
        word = "over-billed" if ob > 0 else "under-billed" if ob < 0 else \
            "billed even"
        pc = "estimate needed" if r.get("estimate_needed") else \
            f"{r['pct_complete']}% complete"
        parts.append(f"Job {r['number']}: {pc}, "
                     f"earned {cents.fmt(r['earned'])}, billed "
                     f"{cents.fmt(r['billed'])}, {word} "
                     f"{cents.fmt(abs(ob))}")
    return {"text": f"WIP as of {period['to']}: " + "; ".join(parts) + ".",
            "data": rows, "records": [f"wip:{r['job_id']}" for r in rows]}


def tool_payables(office, period, vendor_text="", **_):
    ag = appay.aging(office, period["to"])
    rows = ag["rows"]
    if vendor_text:
        v = ap.vendor_by_name(office, vendor_text)
        rows = [r for r in rows if v and r["vendor_id"] == v["id"]]
    tot = sum(r["open"] for r in rows)
    return {"text": f"Open vendor bills as of {ag['as_of']}: "
                    f"{cents.fmt(tot)} on {len(rows)} bill(s).",
            "data": {"total": tot}, "records":
                [f"ap_invoice:{r['number']}" for r in rows]}


def tool_receivables(office, period, job=None, **_):
    ag = payments.aging(office, period["to"])
    rows = [r for r in ag["rows"] if not job or r["job_id"] == job["id"]]
    tot = sum(r["open"] for r in rows)
    late = sum(r["open"] for r in rows if r["days"] > 0)
    return {"text": f"Customers owe {cents.fmt(tot)} on {len(rows)} "
                    f"invoice(s) as of {ag['as_of']}; {cents.fmt(late)} is "
                    f"past due.", "data": {"total": tot, "past_due": late},
            "records": [f"ar_invoice:{r['number']}" for r in rows]}


def tool_cash(office, period, **_):
    rows = office.db.rows("SELECT * FROM accounts WHERE subtype IN "
                          "('bank','credit card') AND deleted = 0 "
                          "ORDER BY number")
    parts, recs, tot = [], [], 0
    for a in rows:
        b = ledger.balance(office, a["id"], period["to"])
        tot += b
        parts.append(f"{a['number']} {a['name']} {cents.fmt(b)}")
        recs.append(f"account:{a['number']}")
    return {"text": f"Balances as of {period['to']}: " + "; ".join(parts) +
                    f" (net {cents.fmt(tot)}).", "data": {"net": tot},
            "records": recs}


def tool_approvals(office, **_):
    od = approvals.overdue(office)
    if not od:
        return {"text": "No approvals are stalled.", "data": [],
                "records": []}
    parts = [f"{r['record_type']} {r['record_id']} waiting on "
             f"{approvals.waiting_on(office, r)}" for r in od]
    return {"text": f"{len(od)} stalled approval(s): " + "; ".join(parts),
            "data": od, "records": [f"approval:{r['id']}" for r in od]}


def tool_waivers(office, **_):
    ms = waivers.missing(office)
    if not ms:
        return {"text": "No lien waivers are missing.", "data": [],
                "records": []}
    parts = []
    for r in ms:
        v = ap.vendor(office, r["vendor_id"])
        j = jobs.job(office, r["job_id"])
        parts.append(f"{v['name'] if v else r['vendor_id']} "
                     f"({r['kind']}, job {j['number'] if j else ''})")
    return {"text": f"{len(ms)} missing lien waiver(s): " + "; ".join(parts),
            "data": ms, "records": [f"waiver_requirement:{r['id']}"
                                    for r in ms]}


def tool_over_commitment(office, **_):
    out = []
    for inv in office.db.rows("SELECT id, number FROM ap_invoices WHERE "
                              "deleted = 0 AND status NOT IN ('Void',"
                              "'Rejected')"):
        o = ap.over_commitment(office, inv["id"])
        if o > 0:
            out.append((inv, o))
    if not out:
        return {"text": "No vendor invoice is over its commitment.",
                "data": [], "records": []}
    return {"text": "Over commitment: " + "; ".join(
        f"{i['number']} by {cents.fmt(o)}" for i, o in out) + ".",
            "data": [{"id": i["id"], "over": o} for i, o in out],
            "records": [f"ap_invoice:{i['id']}" for i, _ in out]}


def tool_recode_time(office, job, params, question, **_):
    """Builds a proposal (actions.propose); nothing changes until Apply."""
    w = timeentry.worker_by_name(office, params.get("worker", ""))
    if w is None:
        raise AssistantError("Which worker? Name them as on the time sheet.")
    d = clock.d(params["date"]).isoformat()
    frm = params["from_code"]
    q = ("SELECT * FROM time_lines WHERE worker_id = ? AND date = ? AND "
         "cost_code = ? AND deleted = 0")
    p = [w["id"], d, frm]
    if job:
        q += " AND job_id = ?"
        p.append(job["id"])
    ln = office.db.one(q + " ORDER BY id", p)
    if ln is None:
        raise AssistantError(f"No time for {w['name']} on {d} under {frm}.")
    aid = actions.propose(office, "recode_time",
                          {"line_id": ln["id"], "hours": params["hours"],
                           "to_code": params["to_code"]}, question,
                          [f"time_line:{ln['id']}"])
    a = actions.get(office, aid)
    after = ", ".join(f"{x['hours']} h {x['cost_code']}"
                      for x in a["after"]["lines"])
    return {"text": f"Suggested change (not applied): {w['name']} {d}, "
                    f"{a['before']['hours']} h {frm} -> {after}. Click "
                    f"Apply to make it; it can be undone.",
            "data": {"action_id": aid}, "records": [f"time_line:{ln['id']}"],
            "action_id": aid}


PL_LINES = [("revenue", "Revenue"), ("cogs", "Cost of goods sold"),
            ("gross_profit", "Gross profit"),
            ("operating_expenses", "Operating expenses"),
            ("operating_income", "Operating income (loss)"),
            ("other_income", "Other income"),
            ("other_expenses", "Other expenses"),
            ("net_income", "Net income (loss)")]


def tool_pl(office, period, job=None, **_):
    """Runs the same Profit and loss report as Books & Reports."""
    d_to = period.get("to") or clock.today().isoformat()
    d_from = period.get("from") or f"{clock.d(d_to).year}-01-01"
    pl = reports.profit_and_loss(office, d_from, d_to)
    parts = [f"{lab} {cents.fmt(pl[k])}" for k, lab in PL_LINES]
    return {"text": f"Report: Profit and loss ({pl['basis']}), {d_from} to "
                    f"{d_to}. " + "; ".join(parts) + ".",
            "data": pl, "records": [f"report:profit_and_loss:{d_from}:"
                                    f"{d_to}"],
            "report": {"name": "Profit and loss", "from": d_from,
                       "to": d_to, "basis": pl["basis"]}}


def find_account(office, text) -> dict | None:
    t = (text or "").strip()
    if not t:
        return None
    m = re.search(r"\b(\d{4})\b", t)
    if m:
        a = ledger.account_by_number(office, m.group(1))
        if a:
            return a
    low = t.lower()
    accts = ledger.accounts(office)
    for a in accts:
        if a["name"].lower() == low:
            return a
    hits = [a for a in accts if a["name"].lower() in low]
    return max(hits, key=lambda a: len(a["name"])) if hits else None


def tool_recategorize(office, params, period, question, **_):
    """Builds ONE proposal for all matching accepted bank / card lines."""
    from . import aicat
    to = find_account(office, params.get("account", ""))
    if to is None:
        raise AssistantError("Which account? Name it as in the chart, e.g. "
                             "'Job cost - Material' or 5020.")
    want = aicat.clean_payee(params.get("payee", ""))
    if not want:
        raise AssistantError("Which payee? e.g. 'Example Lumber'.")
    q = ("SELECT * FROM statement_lines WHERE deleted = 0 AND status = "
         "'Accepted' AND entry_id IS NOT NULL AND date <= ?")
    p = [period["to"]]
    if period.get("from"):
        q += " AND date >= ?"
        p.append(period["from"])
    ids = []
    for sl in office.db.rows(q + " ORDER BY date, id", p):
        if want not in aicat.clean_payee(sl["payee"]):
            continue
        bank = office.db.get("bank_accounts", sl["bank_account_id"])
        e = ledger.entry(office, sl["entry_id"])
        others = [x for x in e["lines"]
                  if x["account_id"] != bank["account_id"]]
        if e["reversed_by_id"] or len(others) != 1:
            continue
        if others[0]["account_id"] != to["id"]:
            ids.append(sl["id"])
    if not ids:
        raise AssistantError(f"No accepted '{params.get('payee')}' lines in "
                             f"{period['label']} that are not already "
                             f"{to['number']} {to['name']}.")
    aid = actions.propose(office, "recategorize",
                          {"line_ids": ids, "to_account": to["number"]},
                          question, [f"statement_line:{i}" for i in ids])
    return {"text": f"Suggested change (not applied): {len(ids)} "
                    f"'{params.get('payee')}' line(s), {period['label']}, "
                    f"to {to['number']} {to['name']}. The before/after list "
                    f"is below; nothing changes until you click Apply, and "
                    f"one Undo restores them all.",
            "data": {"action_id": aid}, "action_id": aid,
            "records": [f"statement_line:{i}" for i in ids]}


def tool_journal(office, params, question, **_):
    dr = find_account(office, params.get("debit_account", ""))
    cr = find_account(office, params.get("credit_account", ""))
    if dr is None or cr is None:
        raise AssistantError("Name both accounts (debit and credit).")
    amt = str(params.get("amount") or "").replace("$", "").strip()
    d = params.get("date") or ""
    d = clock.d(d).isoformat() if d else clock.today().isoformat()
    memo = str(params.get("memo") or "")[:200]
    aid = actions.propose(office, "journal", {
        "date": d, "memo": memo,
        "lines": [{"account": dr["number"], "debit": amt, "memo": memo},
                  {"account": cr["number"], "credit": amt, "memo": memo}]},
        question, [f"account:{dr['number']}", f"account:{cr['number']}"])
    return {"text": f"Drafted journal entry (not posted): {d}, debit "
                    f"{dr['number']} {dr['name']}, credit {cr['number']} "
                    f"{cr['name']}, {cents.fmt(cents.amount_in(amt))}. Click "
                    f"Apply to post it; it can be undone.",
            "data": {"action_id": aid}, "action_id": aid, "records": []}


def tool_add_rule(office, params, question, **_):
    to = find_account(office, params.get("account", ""))
    text = str(params.get("text") or params.get("payee") or "").strip()
    if to is None or not text:
        raise AssistantError("A rule needs the payee text and an account.")
    aid = actions.propose(office, "bank_rule",
                          {"text": text, "account": to["number"]}, question)
    return {"text": f"Suggested bank rule (not added): payee contains "
                    f"'{text}' -> {to['number']} {to['name']}. Click Apply "
                    f"to add it; it can be undone.",
            "data": {"action_id": aid}, "action_id": aid, "records": []}


TOOL_FUNCS = {"missing_time": tool_missing_time, "job_cost": tool_job_cost,
              "wip": tool_wip, "payables": tool_payables,
              "receivables": tool_receivables, "cash": tool_cash,
              "approvals": tool_approvals, "waivers": tool_waivers,
              "over_commitment": tool_over_commitment, "pl": tool_pl,
              "recode_time": tool_recode_time,
              "recategorize": tool_recategorize, "journal": tool_journal,
              "add_rule": tool_add_rule}


# ---- routing -----------------------------------------------------------------

RECODE = re.compile(
    r"(?:recode|move)\s+(\d+(?:\.\d+)?)\s*(?:h|hrs?|hours?)\b.*?from\s+"
    r"(\d{2}-\d{4})\s+to\s+(\d{2}-\d{4})(?:.*?\bfor\s+(.+?))?"
    r"(?:\s+on\s+(\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}(?:/\d{2,4})?))?\s*\??$",
    re.I)
RECODE_FIELDS = ("hours", "from_code", "to_code", "date")


def recode_reading(question: str) -> dict:
    """A pattern reading of a recode request. Used ONLY next to the model's
    routing (never instead of it): for the worker's name, which is
    scrubbed before the model sees the question, and as a second reading
    shown when it differs from the model's."""
    m = RECODE.search(question)
    if not m:
        return {}
    return {"hours": m.group(1), "from_code": m.group(2),
            "to_code": m.group(3), "worker": (m.group(4) or "").strip(),
            "date": m.group(5) or ""}


def merge_recode(model: dict, reading: dict) -> tuple[dict, list[str]]:
    """The model's values win for hours, codes and date (it read the whole
    sentence); the worker comes from the local reading because names never
    reach the model. Returns (params, differences)."""
    out = dict(model)
    w = str(model.get("worker") or "")
    if not w or "[" in w:
        out["worker"] = reading.get("worker", "")
    diffs = []
    for k in RECODE_FIELDS:
        mv, rv = str(model.get(k) or ""), str(reading.get(k) or "")
        if not mv and rv:
            out[k] = rv
        elif mv and rv and mv != rv:
            diffs.append(f"{k}: model {mv}, pattern {rv}")
    return out, diffs


def model_route(office, question, client) -> tuple[dict, dict]:
    r = client.chat(office, ROUTER_SYSTEM, question)
    ans = localai.parse_json(r["text"])
    if ans.get("tool") not in TOOL_FUNCS:
        ans["tool"] = ""
    return ans, {"model": r["model"], "input_hash": r["input_hash"],
                 "model_version": r.get("model_version", "")}


SEARCH_STOP = {"the", "and", "for", "what", "who", "how", "much", "did", "our",
               "are", "was", "with", "from", "this", "that", "all", "show",
               "pull", "run", "give", "list", "any", "have", "has", "job",
               "jobs", "last", "week", "month", "year", "quarter", "lines"}


def plain_search(office, text: str, limit: int = 25) -> list[dict]:
    """A plain text search of the books - no model, no guessing: jobs,
    vendors, customers' invoices, vendor bills, bank lines, accounts."""
    words = [w for w in re.findall(r"[A-Za-z0-9-]{3,}", text or "")
             if w.lower() not in SEARCH_STOP]
    if not words:
        return []
    out, seen = [], set()

    def add(kind, rid, label):
        if (kind, rid) not in seen and len(out) < limit:
            seen.add((kind, rid))
            out.append({"type": kind, "id": rid, "label": label})
    for w in words:
        like = f"%{w}%"
        for r in office.db.rows("SELECT id, number, name FROM jobs WHERE "
                                "deleted = 0 AND (number LIKE ? OR name LIKE "
                                "?)", (like, like)):
            add("job", r["id"], f"Job {r['number']} {r['name']}")
        for r in office.db.rows("SELECT id, name FROM vendors WHERE deleted "
                                "= 0 AND name LIKE ?", (like,)):
            add("vendor", r["id"], f"Vendor {r['name']}")
        for r in office.db.rows("SELECT id, number, customer FROM ar_invoices "
                                "WHERE deleted = 0 AND (number LIKE ? OR "
                                "customer LIKE ?)", (like, like)):
            add("ar_invoice", r["id"],
                f"Invoice {r['number']} {r['customer'] or ''}".strip())
        for r in office.db.rows("SELECT id, number, invoice_no FROM "
                                "ap_invoices WHERE deleted = 0 AND (number "
                                "LIKE ? OR invoice_no LIKE ?)", (like, like)):
            add("ap_invoice", r["id"],
                f"Bill {r['number']} ({r['invoice_no'] or ''})")
        for r in office.db.rows("SELECT id, date, payee, amount FROM "
                                "statement_lines WHERE deleted = 0 AND "
                                "(payee LIKE ? OR memo LIKE ?)", (like, like)):
            add("statement_line", r["id"], f"Bank line {r['date']} "
                f"{r['payee']} {cents.fmt(r['amount'])}")
        for r in office.db.rows("SELECT id, number, name FROM accounts WHERE "
                                "deleted = 0 AND (number LIKE ? OR name LIKE "
                                "?)", (like, like)):
            add("account", r["id"], f"Account {r['number']} {r['name']}")
    return out


def _unavailable(question, why=""):
    return {"text": UNAVAILABLE, "tool": "unavailable", "records": [],
            "routed_by": "none", "why": why}


def ask(office, question: str, client=None) -> dict:
    """Answer one question. Returns {'text', 'tool', 'records', 'routed_by',
    'question_id', 'action_id'?, 'search'?, 'report'?}."""
    office.require("ai.use", "assistant", "ask")
    question = (question or "").strip()
    meta = {"model": "", "input_hash": "", "model_version": ""}
    if PERSONAL.search(question):
        res = {"text": "I don't answer questions about personal or pay data "
                       "(SSN, bank, date of birth, pay). Open People with the "
                       "right role for that.", "tool": "declined",
               "records": [], "routed_by": "rule"}
        return _log(office, question, res, {}, meta)
    c = client if client is not None else localai.client()
    try:
        up = c is not None and c.available()
    except localai.Cancelled:
        res = {"text": "Cancelled.", "tool": "cancelled", "records": [],
               "routed_by": "none"}
        return _log(office, question, res, {}, meta)
    if not up:
        res = _unavailable(question, "no model")
        res["search"] = plain_search(office, question)
        return _log(office, question, res, {}, meta)
    try:
        route, meta = model_route(office, question, c)
    except localai.Cancelled:
        res = {"text": "Cancelled.", "tool": "cancelled", "records": [],
               "routed_by": "none"}
        return _log(office, question, res, {}, meta)
    except localai.AIUnavailable:
        res = _unavailable(question, "model did not answer")
        res["search"] = plain_search(office, question)
        return _log(office, question, res, {}, meta)
    except aiguard.PIIBlocked as e:
        res = {"text": str(e), "tool": "declined", "records": [],
               "routed_by": "rule"}
        return _log(office, question, res, {}, meta)
    tool = route.get("tool") or ""
    if not tool:
        res = {"text": "I couldn't match that to a built-in report or "
                       "action. " + HELP + " Plain search of the books:",
               "tool": "", "records": [], "routed_by": "local model",
               "search": plain_search(office, question)}
        return _log(office, question, res, route, meta)
    note = ""
    if tool == "recode_time":
        route, diffs = merge_recode(route, recode_reading(question))
        if diffs:
            note = (" Read two ways (" + "; ".join(diffs) + "): the model's "
                    "reading is used - check the before/after.")
    job = find_job(office, route.get("job") or question)
    period = resolve_period(route.get("period") or question)
    code = find_code(office, job["id"] if job else None,
                     route.get("cost_code") or question) \
        if tool == "job_cost" else None
    try:
        out = TOOL_FUNCS[tool](
            office, job=job, period=period, code=code, params=route,
            question=question, vendor_text=route.get("vendor", ""))
    except (AssistantError, actions.ActionError, ledger.LedgerError,
            cents.MoneyError, InvalidOperation, KeyError, ValueError,
            TypeError) as e:
        out = {"text": (str(e) or "That didn't work.") + " " + HELP,
               "records": []}
    res = {"text": out["text"] + note, "tool": tool,
           "records": out.get("records", []), "routed_by": "local model",
           "data": out.get("data"), "period": period,
           "job": job["number"] if job else ""}
    for k in ("action_id", "report"):
        if out.get(k):
            res[k] = out[k]
    return _log(office, question, res, route, meta)


def _log(office, question, res, route, meta) -> dict:
    """The question is stored scrubbed (no SSN, bank number or name a
    person typed is kept in plain text)."""
    safe_q = aiguard.scrub_for_log(office, question)
    safe_p = {k: aiguard.scrub_for_log(office, str(v))
              for k, v in route.items() if v}
    with office.db.tx():
        qid = office.db.insert(
            "ai_actions", question=safe_q, tool=res["tool"],
            params=json.dumps(safe_p, default=str),
            records_read=json.dumps(res["records"][:500]),
            answer=res["text"], kind="question", status="answered",
            model=meta.get("model", ""),
            model_version=meta.get("model_version", ""),
            input_hash=meta.get("input_hash", ""))
        office.audit("assistant question", "ai_action", qid, None,
                     {"tool": res["tool"], "routed_by": res["routed_by"],
                      "records": len(res["records"])})
    res["question_id"] = qid
    return res


# ---- findings (the panel's list) ----------------------------------------------

def findings(office, as_of=None) -> list[dict]:
    """What needs a person's attention: missing time last week, coding gaps,
    invoices over commitment, stalled approvals, missing waivers. Each comes
    with a draft reminder text a person may copy and send."""
    office.require("ai.use", "assistant", "findings")
    today = clock.d(as_of) if as_of else clock.today()
    out = []
    we = (clock.d(jobs.week_ending(today)) - timedelta(days=7)).isoformat()
    for name, ds in timeentry.missing_time_report(office, we).items():
        out.append({"kind": "missing_time",
                    "text": f"{name}: no submitted hours on "
                            f"{', '.join(ds)}", "records": [f"worker:{name}"],
                    "reminder": f"Hi {name}, please turn in your time for "
                                f"{', '.join(ds)} (week ending {we})."})
    since = (today - timedelta(days=28)).isoformat()
    for ln in office.db.rows(
            "SELECT t.*, w.name AS worker FROM time_lines t JOIN workers w "
            "ON w.id = t.worker_id WHERE t.deleted = 0 AND t.date >= ? AND "
            "t.status != 'Rejected'", (since,)):
        codes = {c["code"] for c in jobs.section(office, ln["job_id"],
                                                 "cost_codes")}
        if not ln["cost_code"] or (codes and ln["cost_code"] not in codes):
            out.append({"kind": "coding_gap",
                        "text": f"{ln['worker']} {ln['date']}: "
                                f"{cents.hours_text(ln['hours'])} h with "
                                f"cost code '{ln['cost_code'] or '(none)'}'",
                        "records": [f"time_line:{ln['id']}"],
                        "reminder": f"Please check the cost code on "
                                    f"{ln['worker']}'s time for "
                                    f"{ln['date']}."})
    for r in tool_over_commitment(office)["data"]:
        inv = ap.invoice(office, r["id"])
        out.append({"kind": "over_commitment",
                    "text": f"{inv['number']} is {cents.fmt(r['over'])} over "
                            f"commitment {inv['commitment_no']}",
                    "records": [f"ap_invoice:{inv['id']}"],
                    "reminder": f"Invoice {inv['invoice_no']} is over the "
                                f"commitment {inv['commitment_no']}; is a "
                                f"change order coming?"})
    for r in approvals.overdue(office):
        out.append({"kind": "stalled_approval",
                    "text": f"{r['record_type']} {r['record_id']} waiting on "
                            f"{approvals.waiting_on(office, r)}",
                    "records": [f"approval:{r['id']}"],
                    "reminder": f"A {r['record_type'].replace('_', ' ')} is "
                                f"waiting for your approval."})
    for r in waivers.missing(office):
        v = ap.vendor(office, r["vendor_id"])
        out.append({"kind": "missing_waiver",
                    "text": f"{v['name'] if v else ''}: {r['kind']} lien "
                            f"waiver missing",
                    "records": [f"waiver_requirement:{r['id']}"],
                    "reminder": f"Please send your {r['kind']} lien waiver "
                                f"so we can release payment."})
    return out


def draft_reminder(office, finding: dict) -> int:
    """Turn a finding's reminder into a proposal; 'applying' it only marks
    the text as used - Back Office never sends it."""
    return actions.propose(office, "reminder",
                           {"to": finding.get("text", "").split(":")[0],
                            "text": finding["reminder"]},
                           records_read=finding.get("records", ()))
