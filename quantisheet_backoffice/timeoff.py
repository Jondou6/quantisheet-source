"""Time off and the team calendar (the Time Off page).

The page's look and behaviour follow the MIT-licensed Kargul calendar
design prototype (see THIRD_PARTY_NOTICES.txt); everything here is our own
code on Back Office's own data: PTO requests and balances (pto.py), time
lines (timeentry.py) and company holidays (this module).

    add_holiday / remove_holiday / holidays   company holidays (pto.edit)
    workdays(office, a, b)                    weekdays that aren't holidays
    preview(office, employee, a, b, hpd)      what a request would cost
    stats(office, employee=None)              available / pending / upcoming
    request_rows(office, ...)                 the requests table, any status
    cancel(office, rid)                       withdraw a pending request
    month_grid / week_days                    the calendar's dates
    events(office, start, end, ...)           what the calendar shows
    day_hours(office, start, end, ...)        hours worked per day

Hours are hundredths of an hour (ints), as everywhere in Back Office.
"""
from __future__ import annotations

from datetime import date, timedelta

from . import cents, clock, pto


class TimeOffError(ValueError):
    pass


# ------------------------------------------------------------- holidays
def add_holiday(office, d, name) -> int:
    office.require("pto.edit", "holiday", str(d))
    name = str(name or "").strip()
    if not name:
        raise TimeOffError("A holiday needs a name.")
    ds = clock.d(d).isoformat()
    if office.db.one("SELECT id FROM holidays WHERE date = ? AND deleted = 0",
                     (ds,)):
        raise TimeOffError(f"{ds} is already a holiday.")
    with office.db.tx():
        hid = office.db.insert("holidays", date=ds, name=name)
        office.audit("holiday add", "holiday", hid, None,
                     {"date": ds, "name": name})
    return hid


def remove_holiday(office, hid) -> None:
    office.require("pto.edit", "holiday", hid)
    with office.db.tx():
        office.db.soft_delete("holidays", hid)
        office.audit("holiday remove", "holiday", hid, None, {})


def holidays(office, start=None, end=None) -> list[dict]:
    sql = "SELECT id, date, name FROM holidays WHERE deleted = 0"
    args = []
    if start is not None:
        sql += " AND date >= ?"
        args.append(clock.d(start).isoformat())
    if end is not None:
        sql += " AND date <= ?"
        args.append(clock.d(end).isoformat())
    return office.db.rows(sql + " ORDER BY date", tuple(args))


def holiday_dates(office) -> set[str]:
    return {h["date"] for h in holidays(office)}


def workdays(office, a, b) -> list[date]:
    """The days a request from a to b uses: weekdays that are not company
    holidays."""
    return list(pto.workdays(a, b, holiday_dates(office)))


# ------------------------------------------------------------- requests
def preview(office, employee_id, a, b, hours_per_day="8") -> dict:
    """What a request would use and leave, before it is sent:
    {days, hours, available, pending, after, ok, why} (hours in
    hundredths)."""
    try:
        da, db_ = clock.d(a), clock.d(b)
    except Exception:                                     # noqa: BLE001
        return {"days": 0, "hours": 0, "available": 0, "pending": 0,
                "after": 0, "ok": False, "why": "Pick the dates."}
    if db_ < da:
        return {"days": 0, "hours": 0, "available": 0, "pending": 0,
                "after": 0, "ok": False,
                "why": "The last day is before the first."}
    days = workdays(office, da, db_)
    hpd = cents.hours(hours_per_day)
    total = hpd * len(days)
    bal = pto.balance(office, employee_id, da)["balance"]
    pend = pto.pending_hours(office, employee_id)
    after = bal - pend - total
    e = office.db.get("employees", employee_id)
    pol = office.db.get("pto_policies", e["pto_policy_id"]) \
        if e and e["pto_policy_id"] else None
    why = ""
    if not days:
        why = "No working days in that range (weekends and holidays " \
              "aren't counted)."
    elif after < 0 and not (pol and pol["allow_negative"]):
        why = (f"Not enough balance: {cents.hours_text(total)} h asked, "
               f"{cents.hours_text(max(bal - pend, 0))} h available.")
    return {"days": len(days), "hours": total, "available": bal - pend,
            "pending": pend, "after": after, "ok": not why, "why": why}


def cancel(office, rid, note="") -> None:
    """Withdraw a pending request (it was never time; nothing to undo)."""
    r = office.db.get("pto_requests", rid)
    if not r or r["deleted"]:
        raise TimeOffError("No such request.")
    office.require("pto.edit", "pto_request", rid)
    if r["status"] != "Pending":
        raise TimeOffError(f"This request is {r['status']}; only a pending "
                           "request can be cancelled.")
    with office.db.tx():
        office.db.update("pto_requests", rid, status="Cancelled",
                         decided_by=office.who, decided_at=clock.iso_now(),
                         note=note or r["note"])
        office.audit("cancel", "pto_request", rid, None, {"note": note})


STATUSES = ("Pending", "Approved", "Rejected", "Cancelled")


def request_rows(office, status=None, search="", employee_id=None,
                 sort="date_from", descending=False) -> list[dict]:
    """The requests table: every request (or one status), filtered by a
    search over the employee name and note, sorted by a column."""
    sql = ("SELECT r.*, e.name FROM pto_requests r JOIN employees e ON "
           "e.id = r.employee_id WHERE r.deleted = 0")
    args = []
    if status:
        sql += " AND r.status = ?"
        args.append(status)
    if employee_id:
        sql += " AND r.employee_id = ?"
        args.append(employee_id)
    rows = office.db.rows(sql, tuple(args))
    s = str(search or "").strip().lower()
    if s:
        rows = [r for r in rows if s in (r["name"] or "").lower() or
                s in (r["note"] or "").lower() or s in r["status"].lower()]
    key = {"date_from": lambda r: (r["date_from"], r["id"]),
           "name": lambda r: ((r["name"] or "").lower(), r["date_from"]),
           "status": lambda r: (STATUSES.index(r["status"])
                                if r["status"] in STATUSES else 9,
                                r["date_from"]),
           "total": lambda r: (r["total"] or 0, r["date_from"])}[sort]
    rows.sort(key=key, reverse=descending)
    for r in rows:
        r["days"] = len(workdays(office, r["date_from"], r["date_to"]))
    return rows


def stats(office, employee_id=None, today=None) -> dict:
    """The three numbers over the requests table. For one employee:
    hours available (balance less pending), pending and upcoming
    (approved, not yet taken). For the whole team (employee_id None):
    pending requests, people off today and approved days ahead."""
    t = clock.d(today or clock.today())
    if employee_id:
        b = pto.balance(office, employee_id, t)["balance"]
        pend = pto.pending_hours(office, employee_id)
        up = office.db.scalar(
            "SELECT COALESCE(SUM(l.hours), 0) FROM time_lines l JOIN "
            "employees e ON e.worker_id = l.worker_id WHERE e.id = ? AND "
            "l.pay_type = 'PTO' AND l.deleted = 0 AND l.date > ?",
            (employee_id, t.isoformat())) or 0
        return {"available": b - pend, "pending": pend, "upcoming": up,
                "labels": ("Available", "Pending", "Upcoming")}
    pending = office.db.scalar(
        "SELECT COUNT(*) FROM pto_requests WHERE status = 'Pending' AND "
        "deleted = 0") or 0
    off_today = office.db.scalar(
        "SELECT COUNT(DISTINCT worker_id) FROM time_lines WHERE pay_type = "
        "'PTO' AND deleted = 0 AND date = ?", (t.isoformat(),)) or 0
    ahead = office.db.scalar(
        "SELECT COUNT(*) FROM time_lines WHERE pay_type = 'PTO' AND "
        "deleted = 0 AND date > ? AND date <= ?",
        (t.isoformat(), (t + timedelta(days=30)).isoformat())) or 0
    return {"pending": pending, "off_today": off_today, "days_ahead": ahead,
            "labels": ("Pending requests", "Off today",
                       "Days off, next 30 days")}


# ------------------------------------------------------------- calendar
def week_start(d, starts_on=0) -> date:
    """Monday (starts_on 0) or Sunday (6) on or before d."""
    d = clock.d(d)
    return d - timedelta(days=(d.weekday() - starts_on) % 7)


def week_days(d, starts_on=0) -> list[date]:
    s = week_start(d, starts_on)
    return [s + timedelta(days=i) for i in range(7)]


def month_grid(year, month, starts_on=0) -> list[list[date]]:
    """Whole weeks covering the month: 4 to 6 rows of 7 dates."""
    first = date(year, month, 1)
    d = week_start(first, starts_on)
    rows = []
    while True:
        rows.append([d + timedelta(days=i) for i in range(7)])
        d += timedelta(days=7)
        if d.month != month or d.year != year:
            if d > first:
                break
    return rows


def add_months(d, n) -> date:
    d = clock.d(d)
    m = d.month - 1 + n
    y, m = d.year + m // 12, m % 12 + 1
    import calendar
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def events(office, start, end, employee_id=None, pending=True) -> list[dict]:
    """What the calendar shows between start and end (inclusive), all-day
    items: holidays, approved time off (one run per request, or per run of
    PTO days entered by hand), pending requests.
    [{kind: holiday|timeoff|pending, start, end, title, who, ref}]."""
    s, e = clock.d(start).isoformat(), clock.d(end).isoformat()
    out = [{"kind": "holiday", "start": h["date"], "end": h["date"],
            "title": h["name"], "who": "", "ref": ("holiday", h["id"])}
           for h in holidays(office, s, e)]
    where = ""
    args = [e, s]
    if employee_id:
        where = " AND r.employee_id = ?"
        args.append(employee_id)
    states = ("Approved", "Pending") if pending else ("Approved",)
    for r in office.db.rows(
            "SELECT r.*, e.name FROM pto_requests r JOIN employees e ON "
            "e.id = r.employee_id WHERE r.deleted = 0 AND r.date_from <= ? "
            "AND r.date_to >= ? AND r.status IN (" +
            ",".join("?" * len(states)) + ")" + where,
            (args[0], args[1], *states, *args[2:])):
        out.append({"kind": "timeoff" if r["status"] == "Approved"
                    else "pending", "start": r["date_from"],
                    "end": r["date_to"], "who": r["name"],
                    "title": r["name"] + ("" if r["status"] == "Approved"
                                          else " (pending)"),
                    "ref": ("pto_request", r["id"])})
    # PTO time entered without a request (payroll corrections): runs of
    # consecutive days per person
    sql = ("SELECT l.date, l.worker_id, w.name FROM time_lines l JOIN "
           "workers w ON w.id = l.worker_id WHERE l.pay_type = 'PTO' AND "
           "l.deleted = 0 AND (l.source IS NULL OR l.source != 'pto') AND "
           "l.date BETWEEN ? AND ?")
    a2 = [s, e]
    if employee_id:
        sql += (" AND l.worker_id = (SELECT worker_id FROM employees WHERE "
                "id = ?)")
        a2.append(employee_id)
    runs = {}
    for ln in sorted(office.db.rows(sql, tuple(a2)),
                     key=lambda x: (x["worker_id"], x["date"])):
        lst = runs.setdefault(ln["worker_id"], [])
        if lst and clock.d(lst[-1]["end"]) + timedelta(days=1) >= \
                clock.d(ln["date"]):
            lst[-1]["end"] = max(lst[-1]["end"], ln["date"])
        else:
            lst.append({"kind": "timeoff", "start": ln["date"],
                        "end": ln["date"], "who": ln["name"],
                        "title": ln["name"], "ref": ("worker",
                                                     ln["worker_id"])})
    for lst in runs.values():
        out += lst
    order = {"holiday": 0, "timeoff": 1, "pending": 2}
    out.sort(key=lambda x: (x["start"], order[x["kind"]], x["title"]))
    return out


def lanes(items, days) -> list[tuple[dict, int, int, int]]:
    """Stack multi-day all-day items into lanes for one row of days:
    [(item, lane, first column, last column)], each item in the lowest
    lane free across its whole span (a request's bar doesn't jump lanes
    from day to day)."""
    ds = [d.isoformat() for d in days]
    out, busy = [], []
    for it in sorted(items, key=lambda x: (x["start"], x["end"])):
        if it["end"] < ds[0] or it["start"] > ds[-1]:
            continue
        c0 = max(0, next((i for i, d in enumerate(ds) if d >= it["start"]),
                         0))
        c1 = max(i for i, d in enumerate(ds) if d <= it["end"])
        lane = 0
        while any(lane == ln and not (c1 < a or c0 > b)
                  for ln, a, b in busy):
            lane += 1
        busy.append((lane, c0, c1))
        out.append((it, lane, c0, c1))
    return out


def day_hours(office, start, end, employee_id=None) -> dict:
    """Hours on time lines per day (any status but rejected), split into
    worked (REG/OT/DT) and PTO: {iso date: {"work": h, "pto": h}}."""
    sql = ("SELECT date, pay_type, SUM(hours) AS h FROM time_lines WHERE "
           "deleted = 0 AND status != 'Rejected' AND date BETWEEN ? AND ?")
    args = [clock.d(start).isoformat(), clock.d(end).isoformat()]
    if employee_id:
        sql += (" AND worker_id = (SELECT worker_id FROM employees WHERE "
                "id = ?)")
        args.append(employee_id)
    out = {}
    for r in office.db.rows(sql + " GROUP BY date, pay_type", tuple(args)):
        k = "pto" if r["pay_type"] == "PTO" else \
            "work" if r["pay_type"] in ("REG", "OT", "DT") else None
        if k:
            out.setdefault(r["date"], {"work": 0, "pto": 0})[k] += r["h"]
    return out


# ------------------------------------------------------------- year end
def year_end(office, year) -> list[dict]:
    """What each employee carries into the next year (read-only): the
    balance on Dec 31 of `year`, the policy's carry-over limit, the hours
    carried and the hours lost. Hours in hundredths, like pto.balance.
    Employees with no policy are left out."""
    end = date(int(year), 12, 31)
    out = []
    for e in office.db.rows("SELECT id, name, pto_policy_id, status FROM "
                            "employees WHERE deleted = 0 ORDER BY name"):
        if not e["pto_policy_id"]:
            continue
        pol = office.db.get("pto_policies", e["pto_policy_id"])
        b = pto.balance(office, e["id"], end)["balance"]
        limit = pol["carryover"] if pol and pol["carryover"] is not None \
            else None
        carried = b if limit is None else min(b, limit)
        out.append({"employee_id": e["id"], "name": e["name"],
                    "policy": pol["name"] if pol else "",
                    "balance": b, "limit": limit,
                    "carried": max(carried, 0) if b >= 0 else b,
                    "lost": max(b - carried, 0)})
    return out


def report_pdf(office, year=None, path=None, today=None) -> str:
    """A printable time-off report for one year: per employee the hours
    available today, used this year, pending and upcoming, and the
    year-end carry-over (carried / lost at the policy's limit); then
    every request of the year with its status, and the holidays."""
    import os

    import fitz

    from . import fileguard
    from .output import _Pg
    t = clock.d(today or clock.today())
    year = int(year or t.year)
    if path:
        path = fileguard.write_target(path)
    else:
        folder = os.path.join(office.output_folder(), "reports")
        os.makedirs(folder, exist_ok=True)
        path = fileguard.safe_path(folder, f"Time Off {year}.pdf")
    h = cents.hours_text
    doc = fitz.open()
    pg = _Pg(doc)
    c = office.company()
    pg.t(54, 54, c.get("name") or "", 13, True)
    pg.t(54, 80, f"Time off {year}  (printed {t.isoformat()})", 14, True)
    cols = [(54, None, "Employee"), (0, 300, "Available"),
            (0, 360, "Used " + str(year)), (0, 412, "Pending"),
            (0, 466, "Upcoming"), (0, 512, "Carry"), (0, 558, "Lost")]
    y = 110
    for x, right, head in cols:
        pg.t(x, y, head, 8, True, right=right)
    pg.line(y + 4)
    y += 16
    ye = {r["employee_id"]: r for r in year_end(office, year)}
    jan1, dec31 = date(year, 1, 1).isoformat(), date(year, 12, 31).isoformat()
    for e in office.db.rows("SELECT id, name, worker_id FROM employees "
                            "WHERE deleted = 0 ORDER BY name"):
        s = stats(office, e["id"], t)
        used = office.db.scalar(
            "SELECT COALESCE(SUM(hours), 0) FROM time_lines WHERE worker_id "
            "= ? AND pay_type = 'PTO' AND deleted = 0 AND date >= ? AND "
            "date <= ? AND date <= ?",
            (e["worker_id"], jan1, dec31, t.isoformat())) or 0
        r = ye.get(e["id"])
        vals = [(e["name"] or "")[:40], h(s["available"]), h(used),
                h(s["pending"]), h(s["upcoming"]),
                h(r["carried"]) if r else "-",
                h(r["lost"]) if r else "-"]
        for (x, right, _), v in zip(cols, vals):
            pg.t(x, y, v, 8, right=right)
        y += 13
        if y > 720:
            pg, y = _Pg(doc), 60
    pg.t(54, y + 10, "Hours. Carry / Lost: the balance on Dec 31 against "
         "the policy's carry-over limit (no limit: all of it carries).", 7)
    y += 34
    reqs = [r for r in request_rows(office, sort="date_from")
            if r["date_to"] >= jan1 and r["date_from"] <= dec31]
    pg.t(54, y, f"Requests {year} ({len(reqs)})", 11, True)
    y += 16
    for r in reqs:
        if y > 740:
            pg, y = _Pg(doc), 60
        pg.t(54, y, f"{r['date_from']} to {r['date_to']}", 8)
        pg.t(160, y, (r["name"] or "")[:34], 8)
        pg.t(0, y, f"{h(r['total'] or 0)} h", 8, right=420)
        pg.t(430, y, r["status"], 8)
        pg.t(490, y, (r["note"] or "")[:16], 7)
        y += 12
    hol = holidays(office, jan1, dec31)
    if hol:
        y += 10
        if y > 700:
            pg, y = _Pg(doc), 60
        pg.t(54, y, f"Holidays {year}", 11, True)
        y += 16
        for x in hol:
            if y > 740:
                pg, y = _Pg(doc), 60
            pg.t(54, y, f"{x['date']}  {x['name']}", 8)
            y += 12
    doc.save(path)
    doc.close()
    office.audit("export", "timeoff_report", str(year), None, {"path": path})
    return path
