"""PTO policies, accruals and requests (P2-06).

Accrual is per hour worked (approved REG/OT/DT time; PTO and holiday hours
are not hours worked) or a fixed amount per pay period, by tenure band. The
balance never goes over the cap: hours earned while at the cap are lost,
and the balance carries into a new year only up to the carryover limit.
Approved requests become PTO time lines (P1-05), which payroll exports as
the PTO pay type.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal

from . import cents, clock


class PTOError(ValueError):
    pass


def add_policy(office, name, per_hours=None, per_period=None, cap=None,
               carryover=None, tenure=(), union_local="", jobsite="",
               allow_negative=False) -> int:
    """per_hours: hours worked per 1 h of PTO. tenure: [{'years': n,
    'per_hours': ..}] bands that replace per_hours from n years of service."""
    office.require("pto.edit", "pto_policy", name)
    with office.db.tx():
        pid = office.db.insert(
            "pto_policies", name=name,
            per_hours=str(cents.D(per_hours)) if per_hours else None,
            per_period=cents.hours(per_period) if per_period else None,
            cap=cents.hours(cap) if cap else None,
            carryover=cents.hours(carryover) if carryover else None,
            tenure=json.dumps(list(tenure)), union_local=union_local,
            jobsite=jobsite, allow_negative=1 if allow_negative else 0)
        office.audit("create", "pto_policy", pid, None, {"name": name})
    return pid


def assign(office, employee_id, policy_id) -> None:
    office.require("pto.edit", "employee", employee_id)
    with office.db.tx():
        office.db.update("employees", employee_id, pto_policy_id=policy_id)
        office.audit("pto policy", "employee", employee_id, None,
                     {"policy": policy_id})


def adjust(office, employee_id, d, hours, note) -> int:
    office.require("pto.edit", "employee", employee_id)
    if not str(note).strip():
        raise PTOError("An adjustment needs a note.")
    with office.db.tx():
        lid = office.db.insert("pto_ledger", employee_id=employee_id,
                               date=str(clock.d(d)), kind="adjust",
                               hours=cents.hours(hours), note=note)
        office.audit("pto adjust", "employee", employee_id, None,
                     {"hours": str(hours), "note": note})
    return lid


def _rate_for(pol, e, d):
    per = pol["per_hours"]
    if e["hire_date"]:
        yrs = (d - clock.d(e["hire_date"])).days // 365
        for band in sorted(json.loads(pol["tenure"] or "[]"),
                           key=lambda b: b["years"]):
            if yrs >= band["years"] and band.get("per_hours"):
                per = str(band["per_hours"])
    return Decimal(per) if per else None


def balance(office, employee_id, as_of=None) -> dict:
    """Hours in hundredths: worked, earned (before the cap), accrued
    (credited), used, balance."""
    d_end = clock.d(as_of or clock.today())
    e = office.db.get("employees", employee_id)
    pol = office.db.get("pto_policies", e["pto_policy_id"]) \
        if e["pto_policy_id"] else None
    events = []
    for ln in office.db.rows(
            "SELECT date, hours, pay_type FROM time_lines WHERE worker_id = ? "
            "AND deleted = 0 AND status IN ('Approved','Locked') AND date <= ?",
            (e["worker_id"], d_end.isoformat())):
        kind = "use" if ln["pay_type"] == "PTO" else \
            ("work" if ln["pay_type"] in ("REG", "OT", "DT") else None)
        if kind:
            events.append((ln["date"], 1 if kind == "work" else 2, kind,
                           ln["hours"]))
    for x in office.db.rows("SELECT * FROM pto_ledger WHERE employee_id = ? "
                            "AND deleted = 0 AND date <= ?",
                            (employee_id, d_end.isoformat())):
        events.append((x["date"], 0, x["kind"], x["hours"]))
    events.sort()
    worked = used = 0
    earned = accrued = Decimal(0)
    bal = Decimal(0)
    cap = Decimal(pol["cap"]) if pol and pol["cap"] else None
    year = None
    for dt, _, kind, h in events:
        dd = clock.d(dt)
        if pol and pol["carryover"] is not None and year and dd.year > year:
            bal = min(bal, Decimal(pol["carryover"]))
        year = dd.year
        if kind == "work":
            worked += h
            per = _rate_for(pol, e, dd) if pol else None
            if per:
                gain = Decimal(h) / per
                earned += gain
                room = (cap - bal) if cap is not None else gain
                got = max(Decimal(0), min(gain, room))
                accrued += got
                bal += got
        elif kind == "use":
            used += h
            bal -= h
        else:                              # adjust / accrued per period
            bal += h
            accrued += h
    if pol and pol["carryover"] is not None and year and d_end.year > year:
        # into a new year with nothing booked in it yet: the carry-over
        # limit still applies from Jan 1 (it was only applied at the next
        # event of the new year before 0.13.12)
        bal = min(bal, Decimal(pol["carryover"]))
    r = lambda v: int(cents.round_half_up(v))          # noqa: E731
    out = {"worked": worked, "earned": r(earned), "accrued": r(accrued),
           "used": used, "balance": r(bal), "cap": int(cap) if cap else None}
    t = f"{cents.hours_text(out['balance'])} h"
    if cap is not None and out["earned"] > out["accrued"]:
        t += (f" ({cents.hours_text(out['earned'])} h earned, capped at "
              f"{cents.hours_text(int(cap))} h)")
    out["text"] = t
    return out


def accrue_period(office, policy_id, d) -> int:
    """Per-period policies: credit each assigned employee (up to the cap)."""
    office.require("pto.edit", "pto_policy", policy_id)
    pol = office.db.get("pto_policies", policy_id)
    if not pol["per_period"]:
        raise PTOError("This policy accrues per hour worked.")
    n = 0
    for e in office.db.rows("SELECT id FROM employees WHERE pto_policy_id = ? "
                            "AND deleted = 0 AND status != 'Terminated'",
                            (policy_id,)):
        b = balance(office, e["id"], d)["balance"]
        h = pol["per_period"]
        if pol["cap"]:
            h = max(0, min(h, pol["cap"] - b))
        if h:
            with office.db.tx():
                office.db.insert("pto_ledger", employee_id=e["id"],
                                 date=str(clock.d(d)), kind="accrued",
                                 hours=h, note=f"policy {pol['name']}")
            n += 1
    return n


def workdays(a, b, skip=()):
    """Weekdays from a to b (inclusive) that are not in `skip` (ISO dates:
    company holidays)."""
    d = clock.d(a)
    while d <= clock.d(b):
        if d.weekday() < 5 and d.isoformat() not in skip:
            yield d
        d += timedelta(days=1)


def _holiday_set(office) -> set:
    return {r["date"] for r in office.db.rows(
        "SELECT date FROM holidays WHERE deleted = 0")}


def _days(a, b, office=None):
    """A request's days: weekdays, less company holidays when the office
    is given (a holiday is paid as a holiday, not taken from PTO)."""
    return workdays(a, b, _holiday_set(office) if office is not None
                    else ())


def _pending(office, employee_id) -> int:
    return office.db.scalar("SELECT COALESCE(SUM(total), 0) FROM pto_requests "
                            "WHERE employee_id = ? AND status = 'Pending' AND "
                            "deleted = 0", (employee_id,)) or 0


def request(office, employee_id, date_from, date_to, hours_per_day="8",
            source="desktop", remote_id=None, note="") -> int:
    if source == "desktop":
        office.require("pto.edit", "employee", employee_id)
    if remote_id:
        old = office.db.one("SELECT id FROM pto_requests WHERE remote_id = ?",
                            (remote_id,))
        if old:
            return old["id"]
    days = list(_days(date_from, date_to, office))
    if not days:
        raise PTOError("Pick at least one working day (weekends and "
                       "holidays aren't counted).")
    hpd = cents.hours(hours_per_day)
    total = hpd * len(days)
    e = office.db.get("employees", employee_id)
    pol = office.db.get("pto_policies", e["pto_policy_id"]) \
        if e["pto_policy_id"] else None
    left = balance(office, employee_id, date_from)["balance"] - \
        _pending(office, employee_id)
    if total > left and not (pol and pol["allow_negative"]):
        raise PTOError(f"Not enough PTO balance: asking "
                       f"{cents.hours_text(total)} h, "
                       f"{cents.hours_text(max(left, 0))} h available.")
    with office.db.tx():
        rid = office.db.insert("pto_requests", employee_id=employee_id,
                               date_from=str(clock.d(date_from)),
                               date_to=str(clock.d(date_to)),
                               hours_per_day=hpd, total=total,
                               status="Pending", source=source,
                               remote_id=remote_id, note=note)
        office.audit("pto request", "employee", employee_id, None,
                     {"request": rid, "hours": total, "source": source})
    return rid


pending_hours = _pending


def requests(office, status="Pending") -> list[dict]:
    return office.db.rows("SELECT r.*, e.name FROM pto_requests r JOIN "
                          "employees e ON e.id = r.employee_id WHERE r.status "
                          "= ? AND r.deleted = 0 ORDER BY r.date_from",
                          (status,))


def decide(office, rid, decision, note="") -> list[int]:
    """Approve: one Approved PTO time line per weekday. Returns their ids."""
    office.require("pto.approve", "pto_request", rid)
    r = office.db.get("pto_requests", rid)
    if r["status"] != "Pending":
        raise PTOError(f"This request is {r['status']}.")
    e = office.db.get("employees", r["employee_id"])
    if decision == "approve":
        from . import payroll
        for d in _days(r["date_from"], r["date_to"], office):
            p = payroll.final_period_for(office, d)
            if p:
                raise PTOError(f"Payroll for {p['start']} to {p['end']} is "
                               f"final; PTO in it can't be added.")
    ids = []
    with office.db.tx():
        if decision == "approve":
            for d in _days(r["date_from"], r["date_to"], office):
                ids.append(office.db.insert(
                    "time_lines", worker_id=e["worker_id"], date=d.isoformat(),
                    job_id=None, phase="", cost_code="", pay_type="PTO",
                    hours=r["hours_per_day"], equipment_code="",
                    equipment_hours=0, note=f"PTO request {rid}",
                    status="Approved", source="pto",
                    source_key=f"pto:{rid}:{d.isoformat()}"))
            status = "Approved"
        elif decision == "reject":
            status = "Rejected"
        else:
            raise PTOError("decision is approve or reject")
        office.db.update("pto_requests", rid, status=status,
                         decided_by=office.who, decided_at=clock.iso_now(),
                         note=note or r["note"])
        office.audit(decision, "pto_request", rid, None,
                     {"time_lines": ids, "note": note})
    return ids
