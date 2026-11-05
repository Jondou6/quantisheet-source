"""Payroll calculation (P2-01): gross pay, overtime, union scale,
prevailing-wage rates and fringes, from approved time.

Back Office calculates GROSS pay only and hands it to the company's
licensed payroll provider (P2-02). It never calculates tax withholding,
files anything or moves money (decision 8 = A).

Rates (per time line, by the line's date, so a later rate change never
alters an earlier period):
  1. prevailing wage: the job's wage determination for the worker's
     classification (base + fringes). The worker gets the higher of the
     determination base and their own rate.
  2. otherwise the worker's own rate: union scale for their union local and
     labor class, else their pay rate, else the labor class rate table,
     else the labor class cost rate.
Overtime: hours over the daily limits (when the rule sets them) and then
regular hours over the weekly limit in each 7-day pay week, taken from the
last hours worked in the week. PTO and holiday hours are paid at the
worker's own rate and are not hours worked. Fringes are paid per hour
worked at the straight amount (never multiplied for overtime).
Two overtime pay bases, chosen per rule (the register names the one used):
  rate_in_effect    OT hours paid at 1.5 x the rate of the hours worked
  weighted_average  all hours at straight time, plus a premium of 0.5 x
                    the week's weighted-average regular rate per OT hour
                    (1.0 x for double time)
Have the company's CPA or payroll provider confirm the rule for each state
and contract before relying on it.
"""
from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal

from . import cents, clock, jobs

KINDS = ("prevailing", "union", "class")
BASES = ("rate_in_effect", "weighted_average")
FRINGE_TO = ("cash", "plan")
WORKED = ("REG", "OT", "DT")


class PayrollError(ValueError):
    pass


# ---- setup ---------------------------------------------------------------

def pay_setup(office, worker_id, pay_rate=None, classification=None,
              union_local=None, labor_class=None) -> int:
    """Pay fields for a worker (kept on the employee file, P2-04)."""
    office.require("payroll.run", "worker", worker_id)
    w = office.db.get("workers", worker_id)
    if w is None:
        raise PayrollError(f"no worker {worker_id}")
    e = office.db.one("SELECT * FROM employees WHERE worker_id = ? AND "
                      "deleted = 0", (worker_id,))
    fields = {}
    if pay_rate is not None:
        fields["pay_rate"] = cents.amount_in(pay_rate)
    if classification is not None:
        fields["classification"] = classification
    if union_local is not None:
        fields["union_local"] = union_local
    if labor_class is not None:
        fields["labor_class"] = labor_class
    with office.db.tx():
        if e is None:
            eid = office.db.insert("employees", worker_id=worker_id,
                                   name=w["name"],
                                   employee_no=w["employee_no"],
                                   labor_class=w["labor_class"],
                                   status="Active", **fields)
        else:
            eid = e["id"]
            office.db.update("employees", eid, **fields)
        if labor_class is not None:
            office.db.update("workers", worker_id, labor_class=labor_class)
        office.audit("pay setup", "employee", eid,
                     e and {k: e.get(k) for k in fields}, fields)
    return eid


def _employee(office, worker_id) -> dict:
    return office.db.one("SELECT * FROM employees WHERE worker_id = ? AND "
                         "deleted = 0", (worker_id,)) or {}


def _fringes(items) -> list[dict]:
    out = []
    for f in items or ():
        to = f.get("to", "plan")
        if to not in FRINGE_TO:
            raise PayrollError("a fringe goes to 'cash' or 'plan'")
        out.append({"name": str(f["name"]), "amount": cents.amount_in(
            f["amount"]), "to": to})
    return out


def add_rate(office, kind, base_rate, effective_from, effective_to=None,
             labor_class="", union_local="", job_id=None,
             determination_no="", classification="", fringes=()) -> int:
    office.require("payroll.run", "rate_table", kind)
    if kind not in KINDS:
        raise PayrollError(f"rate kind must be one of {', '.join(KINDS)}")
    if kind == "prevailing" and not (job_id and classification):
        raise PayrollError("a wage determination needs a job and a "
                           "classification")
    with office.db.tx():
        rid = office.db.insert(
            "rate_tables", kind=kind, labor_class=labor_class,
            union_local=union_local, job_id=job_id,
            determination_no=determination_no, classification=classification,
            effective_from=str(clock.d(effective_from)),
            effective_to=str(clock.d(effective_to)) if effective_to else None,
            base_rate=cents.amount_in(base_rate),
            fringes=json.dumps(_fringes(fringes)))
        office.audit("create", "rate_table", rid, None,
                     {"kind": kind, "base": base_rate,
                      "from": str(effective_from), "job": job_id,
                      "classification": classification})
    return rid


def add_ot_rule(office, name, weekly_over="40", daily_over=None,
                daily_dt_over=None, rate_basis="weighted_average",
                default=False) -> int:
    office.require("payroll.run", "ot_rule", name)
    if rate_basis not in BASES:
        raise PayrollError(f"rate basis must be one of {', '.join(BASES)}")
    h = lambda v: cents.hours(v) if v not in (None, "") else None  # noqa: E731
    with office.db.tx():
        if default:
            office.db.conn.execute("UPDATE ot_rules SET is_default = 0")
        rid = office.db.insert("ot_rules", name=name,
                               weekly_over=h(weekly_over),
                               daily_over=h(daily_over),
                               daily_dt_over=h(daily_dt_over),
                               rate_basis=rate_basis,
                               is_default=1 if default else 0)
        office.audit("create", "ot_rule", rid, None, {"name": name})
    return rid


FEDERAL = {"id": None, "name": "Federal weekly over 40 h", "weekly_over": 4000,
           "daily_over": None, "daily_dt_over": None,
           "rate_basis": "weighted_average"}


def ot_rule(office, rule_id=None) -> dict:
    if rule_id:
        r = office.db.get("ot_rules", rule_id)
        if r:
            return r
    r = office.db.one("SELECT * FROM ot_rules WHERE is_default = 1 AND "
                      "deleted = 0 ORDER BY id DESC")
    return r or dict(FEDERAL)


def rule_text(rule) -> str:
    parts = []
    if rule.get("daily_over"):
        parts.append(f"Daily over {cents.hours_text(rule['daily_over'])} h")
    if rule.get("daily_dt_over"):
        parts.append(f"double time over "
                     f"{cents.hours_text(rule['daily_dt_over'])} h a day")
    if rule.get("weekly_over"):
        parts.append(f"Weekly over {_h(rule['weekly_over'])} h")
    basis = ("OT paid at 1.5 x the rate of the hours worked"
             if rule["rate_basis"] == "rate_in_effect" else
             "OT premium 0.5 x the weighted-average regular rate")
    return f"{rule['name']}: {', '.join(parts) or 'no overtime limits'}; {basis}"


def _h(v) -> str:
    t = cents.hours_text(v)
    return t[:-3] if t.endswith(".00") else t


def add_period(office, start, end, pay_date, ot_rule_id=None) -> int:
    office.require("payroll.run", "pay_period", str(end))
    s, e = clock.d(start), clock.d(end)
    if e < s:
        raise PayrollError("the period ends before it starts")
    clash = office.db.one("SELECT id FROM pay_periods WHERE deleted = 0 AND "
                          "NOT (end < ? OR start > ?)", (str(s), str(e)))
    if clash:
        raise PayrollError("this period overlaps another pay period")
    with office.db.tx():
        pid = office.db.insert("pay_periods", start=str(s), end=str(e),
                               pay_date=str(clock.d(pay_date)), status="Open",
                               ot_rule_id=ot_rule_id)
        office.audit("create", "pay_period", pid, None,
                     {"start": str(s), "end": str(e)})
    return pid


def period(office, pid) -> dict:
    p = office.db.get("pay_periods", pid)
    if p is None:
        raise PayrollError(f"no pay period {pid}")
    return p


def final_period_for(office, d) -> dict | None:
    return office.db.one("SELECT * FROM pay_periods WHERE status = 'Final' AND "
                         "deleted = 0 AND ? BETWEEN start AND end",
                         (str(clock.d(d)),))


# ---- rates ---------------------------------------------------------------

def _rate_row(office, d, **where):
    q = ("SELECT * FROM rate_tables WHERE deleted = 0 AND effective_from <= ? "
         "AND (effective_to IS NULL OR effective_to >= ?)")
    p = [d, d]
    for k, v in where.items():
        q += f" AND {k} IS ?"
        p.append(v)
    return office.db.one(q + " ORDER BY effective_from DESC, id DESC", p)


def resolve_rate(office, worker_id, job_id, d) -> dict:
    """{'base', 'fringes', 'source', 'prevailing', 'own'} for one hour of
    work by this worker on this job on date d."""
    d = str(clock.d(d))
    w = office.db.get("workers", worker_id)
    e = _employee(office, worker_id)
    lc = e.get("labor_class") or w["labor_class"] or ""
    own, own_src, fr = None, "", []
    if e.get("union_local"):
        r = _rate_row(office, d, kind="union", union_local=e["union_local"],
                      labor_class=lc)
        if r:
            own, fr = r["base_rate"], json.loads(r["fringes"] or "[]")
            own_src = f"Union local {e['union_local']} {lc} scale"
    if own is None and e.get("pay_rate"):
        own, own_src = e["pay_rate"], "Employee pay rate"
    if own is None and lc:
        r = _rate_row(office, d, kind="class", labor_class=lc)
        if r:
            own, fr = r["base_rate"], json.loads(r["fringes"] or "[]")
            own_src = f"Labor class {lc} rate table"
    if own is None and lc:
        c = office.db.one("SELECT cost_rate FROM labor_classes WHERE code = ?",
                          (lc,))
        if c and c["cost_rate"]:
            own, own_src = c["cost_rate"], f"Labor class {lc} cost rate"
    out = {"base": own, "fringes": fr, "source": own_src, "prevailing": False,
           "own": own}
    if job_id and e.get("classification"):
        r = _rate_row(office, d, kind="prevailing", job_id=job_id,
                      classification=e["classification"])
        if r:
            base = max(r["base_rate"], own or 0)
            src = (f"Prevailing wage {r['determination_no']} "
                   f"{r['classification']}").strip()
            if base != r["base_rate"]:
                src += " (own rate is higher)"
            out = {"base": base, "fringes": json.loads(r["fringes"] or "[]"),
                   "source": src, "prevailing": True, "own": own,
                   "determination": r["base_rate"]}
    return out


def has_determination(office, job_id, d=None) -> bool:
    q = "SELECT id FROM rate_tables WHERE kind = 'prevailing' AND deleted = 0 " \
        "AND job_id = ?"
    p = [job_id]
    if d:
        q += " AND effective_from <= ? AND (effective_to IS NULL OR " \
             "effective_to >= ?)"
        p += [str(d), str(d)]
    return office.db.one(q, p) is not None


# ---- calculation ---------------------------------------------------------

def _lines_in(office, p, statuses):
    q = ("SELECT t.*, w.name AS worker, w.employee_no FROM time_lines t "
         "JOIN workers w ON w.id = t.worker_id WHERE t.deleted = 0 AND "
         "t.date BETWEEN ? AND ? AND t.status IN (%s) ORDER BY w.name, "
         "t.worker_id, t.date, t.id" % ",".join("?" * len(statuses)))
    return office.db.rows(q, (p["start"], p["end"], *statuses))


def _segments(rule, lines, week_start):
    """Split one worker's lines into (line, pay_type, hours) segments."""
    segs = []
    day_tot, week_reg = {}, {}
    for ln in lines:
        wk = (clock.d(ln["date"]) - week_start).days // 7
        if ln["pay_type"] in ("PTO", "HOL", "OT", "DT"):
            segs.append((ln, ln["pay_type"], ln["hours"], wk))
            continue
        h = ln["hours"]
        before = day_tot.get(ln["date"], 0)
        day_tot[ln["date"]] = before + h
        reg, ot, dt = h, 0, 0
        if rule.get("daily_dt_over"):
            over = max(0, before + h - max(before, rule["daily_dt_over"]))
            dt = min(h, over)
            reg -= dt
        if rule.get("daily_over"):
            over = max(0, before + reg - max(before, rule["daily_over"]))
            ot = min(reg, over)
            reg -= ot
        if rule.get("weekly_over"):
            so_far = week_reg.get(wk, 0)
            extra = max(0, so_far + reg - max(so_far, rule["weekly_over"]))
            extra = min(reg, extra)
            reg -= extra
            ot += extra
            week_reg[wk] = so_far + reg
        for t, v in (("REG", reg), ("OT", ot), ("DT", dt)):
            if v:
                segs.append((ln, t, v, wk))
    return segs


FACTOR = {"REG": Decimal(1), "OT": Decimal("1.5"), "DT": Decimal(2),
          "PTO": Decimal(1), "HOL": Decimal(1)}
PREMIUM = {"OT": Decimal("0.5"), "DT": Decimal(1)}


def _calc_worker(office, rule, wid, lines, week_start):
    rt = rule_text(rule)
    out_lines, exceptions = [], []
    name = lines[0]["worker"]
    segs = _segments(rule, lines, week_start)
    weeks = {}
    for ln, t, h, wk in segs:
        r = resolve_rate(office, wid, ln["job_id"], ln["date"])
        if t in ("PTO", "HOL"):
            r = dict(r, base=r["own"], fringes=[], prevailing=False,
                     source=r["source"] if not r["prevailing"] else
                     "Employee rate (PTO)")
        if r["base"] is None:
            exceptions.append(f"{name}: no pay rate for {ln['date']}")
            continue
        if (ln["job_id"] and t in WORKED and not r["prevailing"] and
                has_determination(office, ln["job_id"], ln["date"])):
            exceptions.append(f"{name}: no classification for prevailing-wage "
                              f"job {jobs.job(office, ln['job_id'])['number']}"
                              f"; paid own rate")
        hrs = Decimal(h) / 100
        if rule["rate_basis"] == "rate_in_effect" or t in ("PTO", "HOL"):
            gross = cents.mul(r["base"], hrs * FACTOR[t])
            rate = cents.mul(r["base"], FACTOR[t])
        else:
            gross = cents.mul(r["base"], hrs)
            rate = r["base"]
        cash = plan = 0
        fl = []
        if t in WORKED:
            for f in r["fringes"]:
                amt = cents.mul(f["amount"], hrs)
                fl.append({"name": f["name"], "to": f["to"], "amount": amt})
                if f["to"] == "cash":
                    cash += amt
                else:
                    plan += amt
        row = {"worker_id": wid, "job_id": ln["job_id"],
               "cost_code": ln["cost_code"], "date": ln["date"],
               "pay_type": t, "hours": h, "rate": rate, "base": r["base"],
               "gross": gross, "fringe_cash": cash, "fringe_plan": plan,
               "fringes": fl, "rate_source": r["source"], "rule": rt,
               "time_line_id": ln["id"], "prevailing": r["prevailing"]}
        out_lines.append(row)
        if t in WORKED:
            weeks.setdefault(wk, []).append(row)
    if rule["rate_basis"] == "weighted_average":
        for wk, rows in weeks.items():
            hours = sum(x["hours"] for x in rows)
            straight = sum(x["gross"] for x in rows)
            if not hours:
                continue
            rr = Decimal(straight) * 100 / Decimal(hours)   # cents per hour
            for x in rows:
                if x["pay_type"] in PREMIUM:
                    prem = int(cents.round_half_up(
                        rr * Decimal(x["hours"]) / 100 * PREMIUM[x["pay_type"]]))
                    x["gross"] += prem
                    x["premium"] = prem
                    x["regular_rate"] = str(cents.round_half_up(rr / 100,
                                                                "0.0001"))
    hours = {t: 0 for t in FACTOR}
    for x in out_lines:
        hours[x["pay_type"]] += x["hours"]
    gross = sum(x["gross"] for x in out_lines)
    cash = sum(x["fringe_cash"] for x in out_lines)
    plan = sum(x["fringe_plan"] for x in out_lines)
    return {"worker_id": wid, "name": name,
            "employee_no": lines[0]["employee_no"] or "",
            "hours": hours, "gross": gross, "fringe_cash": cash,
            "fringe_plan": plan, "total_pay": gross + cash, "rule": rt,
            "lines": out_lines, "exceptions": sorted(set(exceptions))}


def preview(office, pid) -> dict:
    """Payroll Preview: per worker hours by type, rate, gross, fringes and
    exceptions. A final period returns its frozen lines."""
    office.require("payroll.run", "pay_period", pid)
    p = period(office, pid)
    if p["status"] == "Final":
        return _frozen(office, p)
    rule = ot_rule(office, p["ot_rule_id"])
    approved = _lines_in(office, p, ("Approved", "Locked"))
    pending = _lines_in(office, p, ("Draft", "Submitted"))
    by_worker = {}
    for ln in approved:
        by_worker.setdefault(ln["worker_id"], []).append(ln)
    week_start = clock.d(p["start"])
    workers = [_calc_worker(office, rule, wid, lines, week_start)
               for wid, lines in by_worker.items()]
    exceptions = [x for w in workers for x in w["exceptions"]]
    waiting = {}
    for ln in pending:
        n, h = waiting.get(ln["worker"], (0, 0))
        waiting[ln["worker"]] = (n + 1, h + ln["hours"])
    for name, (n, h) in sorted(waiting.items()):
        exceptions.append(f"{name}: {n} time line{'s' if n > 1 else ''} "
                          f"({cents.hours_text(h)} h) not approved; not in "
                          f"this payroll")
    return {"period": p, "rule": rule_text(rule), "workers": workers,
            "exceptions": exceptions,
            "totals": {"gross": sum(w["gross"] for w in workers),
                       "fringe_cash": sum(w["fringe_cash"] for w in workers),
                       "fringe_plan": sum(w["fringe_plan"] for w in workers),
                       "hours": sum(sum(w["hours"].values())
                                    for w in workers)}}


def _frozen(office, p) -> dict:
    rows = office.db.rows("SELECT l.*, w.name, w.employee_no FROM payroll_lines "
                          "l JOIN workers w ON w.id = l.worker_id WHERE "
                          "l.period_id = ? AND l.deleted = 0 ORDER BY w.name, "
                          "l.worker_id, l.date, l.id", (p["id"],))
    workers = {}
    for r in rows:
        r["fringes"] = json.loads(r["fringes"] or "[]")
        r["prevailing"] = bool(r["prevailing"])
        w = workers.setdefault(r["worker_id"], {
            "worker_id": r["worker_id"], "name": r["name"],
            "employee_no": r["employee_no"] or "",
            "hours": {t: 0 for t in FACTOR}, "gross": 0, "fringe_cash": 0,
            "fringe_plan": 0, "rule": r["rule"], "lines": [],
            "exceptions": []})
        w["hours"][r["pay_type"]] += r["hours"]
        w["gross"] += r["gross"]
        w["fringe_cash"] += r["fringe_cash"]
        w["fringe_plan"] += r["fringe_plan"]
        w["lines"].append(r)
    ws = list(workers.values())
    for w in ws:
        w["total_pay"] = w["gross"] + w["fringe_cash"]
    return {"period": p, "rule": ws[0]["rule"] if ws else "", "workers": ws,
            "exceptions": [],
            "totals": {"gross": sum(w["gross"] for w in ws),
                       "fringe_cash": sum(w["fringe_cash"] for w in ws),
                       "fringe_plan": sum(w["fringe_plan"] for w in ws),
                       "hours": sum(sum(w["hours"].values()) for w in ws)}}


def finalize(office, pid) -> None:
    """Freeze the period: its lines become the job-cost labor actuals and
    its time can no longer be edited."""
    office.require("payroll.run", "pay_period", pid)
    p = period(office, pid)
    if p["status"] == "Final":
        raise PayrollError("This payroll is already final.")
    pv = preview(office, pid)
    blocking = [x for x in pv["exceptions"] if "no pay rate" in x]
    if blocking:
        raise PayrollError("Fix before finalizing: " + "; ".join(blocking))
    with office.db.tx():
        for w in pv["workers"]:
            for x in w["lines"]:
                office.db.insert(
                    "payroll_lines", period_id=pid, worker_id=x["worker_id"],
                    job_id=x["job_id"], cost_code=x["cost_code"],
                    date=x["date"], pay_type=x["pay_type"], hours=x["hours"],
                    rate=x["rate"], base=x["base"], gross=x["gross"],
                    fringe_cash=x["fringe_cash"],
                    fringe_plan=x["fringe_plan"], fringes=x["fringes"],
                    rate_source=x["rate_source"], rule=x["rule"],
                    time_line_id=x["time_line_id"],
                    prevailing=1 if x["prevailing"] else 0)
        office.db.update("pay_periods", pid, status="Final",
                         finalized_by=office.who,
                         finalized_at=clock.iso_now())
        office.audit("finalize", "pay_period", pid, None,
                     {"gross": pv["totals"]["gross"],
                      "workers": len(pv["workers"])})


def register(office, pid) -> list[dict]:
    """Payroll register rows (one per worker)."""
    return [{k: w[k] for k in ("name", "employee_no", "hours", "gross",
                               "fringe_cash", "fringe_plan", "total_pay",
                               "rule")}
            for w in preview(office, pid)["workers"]]


# ---- job cost actuals ----------------------------------------------------

def labor_actuals(office) -> dict:
    """{time_line_id: {'amount', 'gross', 'source'}} for time in final
    periods: gross + fringes + burden. Burden is the labor class burden %
    on gross, or, once the provider's register is imported, the worker's
    employer taxes from it spread over their lines by gross."""
    rows = office.db.rows(
        "SELECT l.*, w.labor_class FROM payroll_lines l JOIN workers w ON "
        "w.id = l.worker_id JOIN pay_periods p ON p.id = l.period_id WHERE "
        "l.deleted = 0 AND p.status = 'Final'")
    regs = {(r["period_id"], r["worker_id"]): r for r in office.db.rows(
        "SELECT * FROM provider_registers WHERE deleted = 0")}
    groups = {}
    for r in rows:
        groups.setdefault((r["period_id"], r["worker_id"]), []).append(r)
    out = {}
    for key, lines in groups.items():
        reg = regs.get(key)
        burden = {}
        if reg and reg["employer_taxes"]:
            tot = sum(x["gross"] for x in lines) or 1
            left = reg["employer_taxes"]
            for i, x in enumerate(lines):
                share = left if i == len(lines) - 1 else int(cents.round_half_up(
                    Decimal(reg["employer_taxes"]) * x["gross"] / tot))
                left -= share if i < len(lines) - 1 else 0
                burden[x["id"]] = share
        for x in lines:
            if x["id"] in burden:
                b = burden[x["id"]]
            else:
                c = office.db.one("SELECT burden_pct FROM labor_classes WHERE "
                                  "code = ?", (x["labor_class"],))
                b = cents.pct_of(x["gross"], c["burden_pct"]) if c else 0
            a = out.setdefault(x["time_line_id"], {
                "amount": 0, "gross": 0,
                "source": "payroll register" if reg else "payroll"})
            a["amount"] += x["gross"] + x["fringe_cash"] + x["fringe_plan"] + b
            a["gross"] += x["gross"]
    return out


def week_bounds(end) -> tuple[str, str]:
    e = clock.d(end)
    return (e - timedelta(days=6)).isoformat(), e.isoformat()
