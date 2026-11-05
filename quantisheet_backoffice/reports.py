"""Financial statements, job-cost P&L and the finance dashboard (addendum
P2-14, P2-19). Every number is computed from journal lines (job cost from
the P1-07 engine, which is what the brief's 7.1 figure is). Our own wording
and layout.

Cash basis: revenue and cost on AR invoices and AP bills count when cash
moves: each customer payment applied to an invoice recognizes that much,
split over the invoice's income lines by their share; each bill payment
likewise over the bill's cost lines. Other entries (manual, bank
categorized) are cash already and count as posted.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from . import cents, clock, jobcost, ledger

PL_TYPES = ("income", "cogs", "expense", "other income", "other expense")


def _accts(office):
    return {a["id"]: a for a in ledger.accounts(office, include_inactive=True)}


def _accrual(office, date_from, date_to, job_id=None):
    return ledger.balances(office, as_of=date_to, date_from=date_from,
                           job_id=job_id)


def _split(amount, weights):
    """amount split over {key: weight} in whole cents, remainder to the
    largest weight, so the parts add up exactly."""
    tot = sum(weights.values())
    if not tot:
        return {}
    out = {k: amount * w // tot for k, w in weights.items()}
    rest = amount - sum(out.values())
    if rest:
        k = max(weights, key=lambda k: weights[k])
        out[k] += rest
    return out


def _cash(office, date_from, date_to, job_id=None):
    acc = _accts(office)
    bal = defaultdict(int)
    q = ("SELECT l.*, e.source_type, e.date FROM journal_lines l JOIN "
         "journal_entries e ON e.id = l.entry_id WHERE e.date BETWEEN ? "
         "AND ? AND e.source_type NOT IN ('ar_invoice', 'ap_invoice')")
    for ln in office.db.rows(q, (str(date_from), str(date_to))):
        if job_id is not None and ln["job_id"] != job_id:
            continue
        if acc[ln["account_id"]]["type"] in PL_TYPES:
            bal[ln["account_id"]] += ln["debit"] - ln["credit"]

    def pl_weights(source_type, sid):
        w = defaultdict(int)
        for e in ledger.entries_for(office, source_type, sid):
            if e["reverses_id"] or e["reversed_by_id"]:
                continue
            for ln in e["lines"]:
                if acc[ln["account_id"]]["type"] in PL_TYPES and \
                        (job_id is None or ln["job_id"] == job_id):
                    w[ln["account_id"]] += ln["debit"] - ln["credit"]
        return w

    for pa in office.db.rows(
            "SELECT a.invoice_id, a.amount, COALESCE(a.date, p.date) AS d "
            "FROM payment_apps a JOIN payments p ON p.id = a.payment_id "
            "WHERE p.void = 0 AND a.invoice_id IS NOT NULL AND "
            "COALESCE(a.date, p.date) BETWEEN ? AND ?",
            (str(date_from), str(date_to))):
        inv = office.db.get("ar_invoices", pa["invoice_id"])
        w = pl_weights("ar_invoice", pa["invoice_id"])
        cash = pa["amount"]
        if inv["tax"]:                       # tax share is not revenue
            cash -= pa["amount"] * inv["tax"] // inv["total"]
        mag = {k: -v for k, v in w.items()}  # income is credit
        for k, v in _split(cash, mag).items():
            bal[k] -= v
    for pa in office.db.rows(
            "SELECT a.invoice_id, a.amount FROM bill_payment_apps a JOIN "
            "bill_payments p ON p.id = a.payment_id WHERE p.void = 0 AND "
            "p.date BETWEEN ? AND ?", (str(date_from), str(date_to))):
        w = pl_weights("ap_invoice", pa["invoice_id"])
        for k, v in _split(pa["amount"], w).items():
            bal[k] += v
    return dict(bal)


def profit_and_loss(office, date_from, date_to, basis="accrual",
                    job_id=None) -> dict:
    bal = _cash(office, date_from, date_to, job_id) if basis == "cash" else \
        _accrual(office, date_from, date_to, job_id)
    acc = _accts(office)
    sec = {t: [] for t in PL_TYPES}
    for aid, b in sorted(bal.items(), key=lambda x: acc[x[0]]["number"]):
        a = acc[aid]
        if a["type"] not in PL_TYPES or b == 0:
            continue
        natural = -b if a["type"] in ("income", "other income") else b
        sec[a["type"]].append({"number": a["number"], "name": a["name"],
                               "amount": natural, "account_id": aid})
    tot = {t: sum(r["amount"] for r in rows) for t, rows in sec.items()}
    gp = tot["income"] - tot["cogs"]
    op = gp - tot["expense"]
    net = op + tot["other income"] - tot["other expense"]
    return {"from": str(date_from), "to": str(date_to), "basis": basis,
            "sections": sec, "revenue": tot["income"], "cogs": tot["cogs"],
            "gross_profit": gp, "operating_expenses": tot["expense"],
            "operating_income": op, "other_income": tot["other income"],
            "other_expenses": tot["other expense"], "net_income": net}


def _fy_start(office, as_of) -> str:
    fys = (office.company().get("fiscal_year_start") or "01-01")
    y = clock.d(as_of).year
    start = f"{y}-{fys}"
    if start > str(as_of):
        start = f"{y - 1}-{fys}"
    return start


def balance_sheet(office, as_of) -> dict:
    """Assets = liabilities + equity, with prior years' results in
    Retained earnings and this year's as a Current-year earnings line."""
    bal = ledger.balances(office, as_of=as_of)
    acc = _accts(office)
    fy = _fy_start(office, as_of)
    prior = ledger.balances(office, as_of=(clock.d(fy) - timedelta(days=1))
                            .isoformat())
    sec = {"asset": [], "liability": [], "equity": []}
    for aid, b in sorted(bal.items(), key=lambda x: acc[x[0]]["number"]):
        a = acc[aid]
        if a["type"] not in sec or b == 0:
            continue
        natural = b if a["type"] == "asset" else -b
        sec[a["type"]].append({"number": a["number"], "name": a["name"],
                               "amount": natural, "account_id": aid})
    pl_prior = -sum(v for k, v in prior.items()
                    if acc[k]["type"] in PL_TYPES)
    pl_all = -sum(v for k, v in bal.items() if acc[k]["type"] in PL_TYPES)
    current = pl_all - pl_prior
    if pl_prior:
        re_ = ledger.account_by_number(office, ledger.DEFAULT_POSTING["retained"])
        row = next((r for r in sec["equity"] if r["account_id"] == re_["id"]),
                   None)
        if row:
            row["amount"] += pl_prior
        else:
            sec["equity"].append({"number": re_["number"],
                                  "name": re_["name"] + " (prior years)",
                                  "amount": pl_prior, "account_id": re_["id"]})
    sec["equity"].append({"number": "", "name": "Current-year earnings",
                          "amount": current, "account_id": None})
    ta = sum(r["amount"] for r in sec["asset"])
    tl = sum(r["amount"] for r in sec["liability"])
    te = sum(r["amount"] for r in sec["equity"])
    return {"as_of": str(as_of), "sections": sec, "total_assets": ta,
            "total_liabilities": tl, "total_equity": te,
            "balances": ta == tl + te}


def _cash_accounts(office):
    return {a["id"] for a in ledger.accounts(office, include_inactive=True)
            if a["subtype"] == "bank"}


def cash_flow(office, date_from, date_to) -> dict:
    """Indirect method: net income, then changes in the other balance
    sheet accounts sorted into operating / investing / financing."""
    acc = _accts(office)
    cash_ids = _cash_accounts(office)
    chg = _accrual(office, date_from, date_to)
    net = profit_and_loss(office, date_from, date_to)["net_income"]
    ops, inv, fin = [], [], []
    for aid, d in sorted(chg.items(), key=lambda x: acc[x[0]]["number"]):
        a = acc[aid]
        if aid in cash_ids or a["type"] in PL_TYPES or d == 0:
            continue
        effect = -d                    # more asset = less cash, etc.
        row = {"number": a["number"], "name": a["name"], "amount": effect}
        n = int(a["number"]) if a["number"].isdigit() else 0
        if a["type"] == "asset" and 1500 <= n < 1700 and n != 1600:
            inv.append(row)
        elif a["type"] == "equity" or (a["type"] == "liability" and
                                       a["number"] in ("2600", "2700")):
            fin.append(row)
        else:
            ops.append(row)
    o = net + sum(r["amount"] for r in ops)
    i = sum(r["amount"] for r in inv)
    f = sum(r["amount"] for r in fin)
    start = (clock.d(date_from) - timedelta(days=1)).isoformat()
    begin = sum(ledger.balances(office, as_of=start).get(k, 0)
                for k in cash_ids)
    end = sum(ledger.balances(office, as_of=date_to).get(k, 0)
              for k in cash_ids)
    return {"from": str(date_from), "to": str(date_to), "net_income": net,
            "operating": ops, "investing": inv, "financing": fin,
            "net_operating": o, "net_investing": i, "net_financing": f,
            "net_change": o + i + f, "cash_begin": begin, "cash_end": end}


def job_pl(office, job_id, date_from, date_to) -> dict:
    """Revenue billed on the job (ledger) less job cost from the P1-07
    engine (approved time at loaded rates, approved AP, imported direct
    costs) for the same dates."""
    pl = profit_and_loss(office, date_from, date_to, job_id=job_id)
    rev = pl["revenue"]
    rows = jobcost.job_cost(office, job_id, date_from=str(date_from),
                            date_to=str(date_to))
    by_cat = defaultdict(int)
    for r in rows:
        by_cat[r["category"] or "O"] += r["actual"]
    cost = sum(r["actual"] for r in rows)
    gp = rev - cost
    return {"job_id": job_id, "from": str(date_from), "to": str(date_to),
            "revenue": rev, "job_cost": cost, "by_category": dict(by_cat),
            "gross_profit": gp, "margin": cents.percent_text(gp, rev)}


def _months_back(as_of, n):
    d = clock.d(as_of).replace(day=1)
    out = []
    for _ in range(n):
        end = d - timedelta(days=1)
        d = end.replace(day=1)
        out.append((d.isoformat(), end.isoformat()))
    return out


def dashboard(office, date_from, date_to) -> dict:
    """Home panels for a month range; every figure from the statements
    above."""
    pl = profit_and_loss(office, date_from, date_to)
    cf = cash_flow(office, date_from, date_to)
    cash = cf["cash_end"]
    # the 3 whole months before the month after the range's end
    months = _months_back((clock.d(date_to) + timedelta(days=1)).isoformat(),
                          3)
    opex = [profit_and_loss(office, a, b)["operating_expenses"]
            for a, b in months]
    avg = sum(opex) // 3 if opex else 0
    from decimal import Decimal, ROUND_HALF_UP
    cover = (Decimal(cash) / Decimal(avg)).quantize(
        Decimal("0.1"), rounding=ROUND_HALF_UP) if avg else None
    exp_total = pl["cogs"] + pl["operating_expenses"] + pl["other_expenses"]
    return {
        "cash": {"net_cash_flow": cf["net_change"], "cash_on_hand": cash,
                 "avg_monthly_opex": avg,
                 "coverage_months": None if cover is None else str(cover)},
        "expenses": {"total": exp_total,
                     "net_margin": cents.percent_text(pl["net_income"],
                                                      pl["revenue"]),
                     "expense_ratio": cents.percent_text(exp_total,
                                                         pl["revenue"]),
                     "by_category": {s: sum(r["amount"] for r in
                                            pl["sections"][s])
                                     for s in ("cogs", "expense",
                                               "other expense")}},
        "revenue": {"total": pl["revenue"]},
        "range": (str(date_from), str(date_to))}
