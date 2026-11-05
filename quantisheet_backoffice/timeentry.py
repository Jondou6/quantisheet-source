"""Time entry by crew or individual, coded to job / phase / cost code
(P1-05), its approvals and the week lock (P1-06).

Hours are int hundredths. Time cards from QuantiSheet import as Draft
lines and are never imported twice.
"""
from __future__ import annotations

from datetime import timedelta

from . import approvals, cents, clock, jobs
from .security import Denied

PAY_TYPES = ("REG", "OT", "DT", "PTO", "HOL")
PAY_FACTOR = {"REG": "1", "OT": "1.5", "DT": "2", "PTO": "1", "HOL": "1"}
WEEK_LIMIT = 4000                    # 40.00 h


class TimeError(ValueError):
    pass


# ---- setup ---------------------------------------------------------------

# time cards brought in before QuantiSheet's rename were keyed with this
# prefix (time_lines.source_key); recognised so none comes in twice
OLD_CARD_PREFIX = "pdfstudio:timecard:"


def add_labor_class(office, code, description="", cost_rate="0",
                    burden_pct="0", billing_rate="0") -> int:
    office.require("settings.edit", "labor_class", code)
    with office.db.tx():
        cid = office.db.insert("labor_classes", code=code,
                               description=description,
                               cost_rate=cents.to_cents(cost_rate),
                               burden_pct=str(cents.D(burden_pct)),
                               billing_rate=cents.to_cents(billing_rate))
        office.audit("create", "labor_class", cid, None, {"code": code})
    return cid


def loaded_rate(office, class_code) -> int:
    """Cost rate x (1 + burden %), half up, in cents per hour."""
    c = office.db.one("SELECT * FROM labor_classes WHERE code = ?",
                      (class_code,))
    if c is None:
        return 0
    return c["cost_rate"] + cents.pct_of(c["cost_rate"], c["burden_pct"])


def add_worker(office, name, labor_class="", employee_no="", crew_id=None,
               user_id=None) -> int:
    office.require("time.edit", "worker", name)
    with office.db.tx():
        wid = office.db.insert("workers", name=name, labor_class=labor_class,
                               employee_no=employee_no, crew_id=crew_id,
                               active=1, user_id=user_id)
        office.audit("create", "worker", wid, None, {"name": name})
    return wid


def worker_by_name(office, name):
    return office.db.one("SELECT * FROM workers WHERE name = ? AND deleted = 0",
                         (name,))


def add_crew(office, name, foreman_user_id=None, members=()) -> int:
    office.require("time.edit", "crew", name)
    with office.db.tx():
        cid = office.db.insert("crews", name=name,
                               foreman_user_id=foreman_user_id)
        for w in members:
            office.db.update("workers", w, crew_id=cid)
        office.audit("create", "crew", cid, None, {"name": name})
    return cid


# ---- lines ---------------------------------------------------------------

def _payroll_final(office, d) -> None:
    """Time inside a final pay period (P2-01) can't change."""
    from . import payroll
    p = payroll.final_period_for(office, d)
    if p:
        raise TimeError(f"Payroll for {p['start']} to {p['end']} is final; "
                        f"this time can't change.")


def _week_locked(office, d) -> bool:
    we = jobs.week_ending(d)
    return bool(office.db.one("SELECT id FROM week_locks WHERE week_ending = ? "
                              "AND active = 1", (we,)))


def add_line(office, worker_id, date, job_id, cost_code, hours, pay_type="REG",
             phase="", equipment_code="", equipment_hours="0", note="",
             source="manual", source_key=None) -> int:
    office.require("time.edit", "time_line", "")
    if pay_type not in PAY_TYPES:
        raise TimeError(f"pay type must be one of {', '.join(PAY_TYPES)}")
    h = cents.hours(hours)
    if h < 0 or h > 2400:
        raise TimeError("hours must be between 0 and 24")
    if _week_locked(office, date):
        raise TimeError(f"The week ending {jobs.week_ending(date)} is locked.")
    _payroll_final(office, date)
    with office.db.tx():
        lid = office.db.insert("time_lines", worker_id=worker_id,
                               date=str(date), job_id=job_id, phase=phase,
                               cost_code=cost_code, pay_type=pay_type, hours=h,
                               equipment_code=equipment_code,
                               equipment_hours=cents.hours(equipment_hours),
                               note=note, status="Draft", source=source,
                               source_key=source_key)
        office.audit("create", "time_line", lid, None,
                     {"worker": worker_id, "date": str(date), "hours": h,
                      "cost_code": cost_code})
    return lid


def crew_day(office, crew_id, job_id, date, hours, splits) -> list[int]:
    """Whole crew at once: every member gets `hours`, split across cost
    codes by {code: hours} (must add to `hours`)."""
    total = sum(cents.hours(v) for v in splits.values())
    if total != cents.hours(hours):
        raise TimeError("the cost-code split must add up to the hours")
    out = []
    for w in office.db.rows("SELECT id FROM workers WHERE crew_id = ? AND "
                            "active = 1", (crew_id,)):
        for code, h in splits.items():
            out.append(add_line(office, w["id"], date, job_id, code, h))
    return out


def edit_line(office, line_id, **fields) -> None:
    office.require("time.edit", "time_line", line_id)
    ln = office.db.get("time_lines", line_id)
    _payroll_final(office, ln["date"])
    if _week_locked(office, ln["date"]) or ln["status"] == "Locked":
        office.audit("denied", "time_line", line_id, None,
                     {"reason": "week locked"})
        raise TimeError(f"The week ending {jobs.week_ending(ln['date'])} is "
                        f"locked; an Admin must unlock it first.")
    if ln["status"] not in ("Draft", "Rejected"):
        raise TimeError(f"A {ln['status']} line can't be edited.")
    if "hours" in fields:
        fields["hours"] = cents.hours(fields["hours"])
    with office.db.tx():
        office.db.update("time_lines", line_id, **fields)
        office.audit("change", "time_line", line_id,
                     {k: ln[k] for k in fields}, fields)
        from .r111.duties import note
        note(office, "time_line", line_id, "coded")


def copy_lines(office, worker_id, from_date, to_date) -> list[int]:
    """Copy yesterday (or any day) to another day as Draft."""
    out = []
    for ln in office.db.rows("SELECT * FROM time_lines WHERE worker_id = ? AND "
                             "date = ? AND deleted = 0", (worker_id,
                                                          str(from_date))):
        out.append(add_line(office, worker_id, to_date, ln["job_id"],
                            ln["cost_code"], cents.hours_text(ln["hours"]),
                            ln["pay_type"], ln["phase"],
                            ln["equipment_code"],
                            cents.hours_text(ln["equipment_hours"] or 0)))
    return out


def copy_week(office, worker_id, week_ending_from) -> list[int]:
    out = []
    end = clock.d(week_ending_from)
    for i in range(7):
        d = end - timedelta(days=6 - i)
        out += copy_lines(office, worker_id, d, d + timedelta(days=7))
    return out


def import_timecards(office, job_id, card_ids=None) -> list[int]:
    """QuantiSheet time cards -> Draft lines. Crew hours are coded to the
    production cost code; with several codes they are split by the crew
    hours on each; a card imported before adds nothing."""
    office.require("time.edit", "time_line", "import")
    out = []
    for card in jobs.section(office, job_id, "timecards"):
        key = card["id"] or f"{card['date']}|{card['foreman']}"
        if card_ids and key not in card_ids:
            continue
        prod = [p for p in card["production"] if p["cost_code"]]
        ph = {p["cost_code"]: cents.hours(p["hours"]) for p in prod}
        for i, crew in enumerate(card["crew"]):
            skey = f"quantisheet:timecard:{key}:{i}"
            # a card brought in before the program's rename carries the
            # old prefix - it still counts as brought in (never twice)
            old = OLD_CARD_PREFIX + skey[len("quantisheet:timecard:"):]
            if office.db.one("SELECT id FROM time_lines WHERE source_key "
                             "IN (?, ?) AND deleted = 0", (skey, old)):
                continue
            w = worker_by_name(office, crew["name"])
            wid = w["id"] if w else add_worker(office, crew["name"],
                                               crew["class"])
            h = cents.hours(crew["hours"])
            if len(ph) <= 1:
                parts = [(next(iter(ph), ""), h)]
            else:
                tot = sum(ph.values()) or len(ph)
                parts, left = [], h
                codes = list(ph)
                for j, code in enumerate(codes):
                    share = left if j == len(codes) - 1 else \
                        int(cents.round_half_up(cents.D(h) * ph[code] / tot))
                    left -= share if j < len(codes) - 1 else 0
                    parts.append((code, share))
            for j, (code, hh) in enumerate(parts):
                out.append(add_line(office, wid, card["date"], job_id, code,
                                    cents.hours_text(hh), source="quantisheet",
                                    source_key=skey if j == 0 else
                                    f"{skey}:{j}",
                                    note=f"Time card {card['foreman']}"))
    return out


def week_lines(office, worker_id, week_ending) -> list[dict]:
    end = clock.d(week_ending)
    start = end - timedelta(days=6)
    return office.db.rows(
        "SELECT * FROM time_lines WHERE worker_id = ? AND date BETWEEN ? AND ? "
        "AND deleted = 0 ORDER BY date, id",
        (worker_id, start.isoformat(), end.isoformat()))


def weekly_total(office, worker_id, week_ending) -> dict:
    """{'hours': int, 'flag': str} - flag only (Phase 1); Phase 2 pays OT."""
    tot = sum(ln["hours"] for ln in week_lines(office, worker_id, week_ending)
              if ln["pay_type"] in ("REG", "OT", "DT"))
    flag = ""
    if tot > WEEK_LIMIT:
        flag = f"over 40 h: {cents.hours_text(tot - WEEK_LIMIT)} h may be overtime"
    return {"hours": tot, "flag": flag, "colour": "yellow" if flag else ""}


def missing_time(office, date, worker_ids=None) -> list[str]:
    d = clock.d(date)
    if d.weekday() >= 5:
        return []
    ws = office.db.rows("SELECT * FROM workers WHERE active = 1 AND deleted = 0")
    return [w["name"] for w in ws
            if (worker_ids is None or w["id"] in worker_ids) and
            not office.db.one("SELECT id FROM time_lines WHERE worker_id = ? "
                              "AND date = ? AND deleted = 0",
                              (w["id"], d.isoformat()))]


TURNED_IN = ("Submitted", "Approved", "Locked")


def missing_time_report(office, week_ending, job_id=None) -> dict:
    """Missing Time report for one week (Mon-Fri): {worker name: [dates]}
    for every workday with no submitted or approved hours. With a job, the
    workers counted are those with any time on that job in the four weeks
    up to the week end (or, for a job with none yet, every active worker)."""
    end = clock.d(jobs.week_ending(week_ending))
    days = [end - timedelta(days=n) for n in range(5, 0, -1)]   # Mon-Fri
    ws = office.db.rows("SELECT * FROM workers WHERE active = 1 AND "
                        "deleted = 0 ORDER BY name")
    if job_id is not None:
        since = (end - timedelta(days=27)).isoformat()
        on_job = {r["worker_id"] for r in office.db.rows(
            "SELECT DISTINCT worker_id FROM time_lines WHERE job_id = ? AND "
            "deleted = 0 AND date BETWEEN ? AND ?",
            (job_id, since, end.isoformat()))}
        if on_job:
            ws = [w for w in ws if w["id"] in on_job]
    out = {}
    for w in ws:
        miss = [d.isoformat() for d in days if not office.db.one(
            "SELECT id FROM time_lines WHERE worker_id = ? AND date = ? AND "
            "deleted = 0 AND hours > 0 AND status IN (?,?,?)",
            (w["id"], d.isoformat(), *TURNED_IN))]
        if miss:
            out[w["name"]] = miss
    return out


# ---- submit / approve / lock (P1-06) -------------------------------------

def submit(office, line_ids) -> None:
    office.require("time.edit", "time_line", "submit")
    for lid in line_ids:
        ln = office.db.get("time_lines", lid)
        codes = jobs.cost_codes(office, ln["job_id"])
        j = jobs.job(office, ln["job_id"])
        if not ln["cost_code"]:
            raise TimeError(f"Time line {lid} has no cost code.")
        if ln["cost_code"] not in codes:
            raise TimeError(f"Cost code {ln['cost_code']} is not in job "
                            f"{j['number']}'s code list.")
    for lid in line_ids:
        ln = office.db.get("time_lines", lid)
        with office.db.tx():
            office.db.update("time_lines", lid, status="Submitted",
                             reject_reason=None)
            approvals.start(office, "time_line", lid,
                            approvals.path_for(office, "time_line",
                                               ln["job_id"]),
                            ln["job_id"])


def _owner(office, ln) -> int | None:
    w = office.db.get("workers", ln["worker_id"])
    return w["user_id"] if w else None


def decide(office, line_ids, decision, reason="") -> None:
    office.require("time.approve", "time_line", "approve")
    for lid in line_ids:
        ln = office.db.get("time_lines", lid)
        approvals.precheck(office, "time_line", lid, decision, reason,
                           owner_id=_owner(office, ln))
        with office.db.tx():
            req = approvals.decide(office, "time_line", lid, decision, reason,
                                   owner_id=_owner(office, ln))
            if req["status"] == "rejected":
                office.db.update("time_lines", lid, status="Draft",
                                 reject_reason=reason)
            elif req["status"] == "approved":
                office.db.update("time_lines", lid, status="Approved")


def status_text(office, line_id) -> str:
    ln = office.db.get("time_lines", line_id)
    req = approvals.request(office, "time_line", line_id)
    if ln["status"] == "Submitted" and req:
        return f"{ln['status']}, {approvals.waiting_on(office, req)}"
    return ln["status"]


def lock_week(office, week_ending) -> None:
    office.require("time.approve", "week", week_ending)
    we = str(week_ending)
    end = clock.d(we)
    start = (end - timedelta(days=6)).isoformat()
    with office.db.tx():
        office.db.insert("week_locks", week_ending=we, locked_by=office.who,
                         ts=clock.iso_now(), active=1)
        office.db.conn.execute(
            "UPDATE time_lines SET status = 'Locked' WHERE status = 'Approved' "
            "AND date BETWEEN ? AND ?", (start, we))
        office.db.conn.execute(                      # r38 G2.1: per diem too
            "UPDATE per_diem_lines SET status = 'Locked' WHERE status = "
            "'Approved' AND deleted = 0 AND date BETWEEN ? AND ?", (start, we))
        office.audit("lock", "week", we)


def unlock_week(office, week_ending, reason) -> None:
    if office.role != "Admin":
        office.audit("denied", "week", week_ending, None,
                     {"permission": "time.unlock"})
        raise Denied("Only an Admin can unlock a week.")
    if not (reason or "").strip():
        raise TimeError("A reason is required to unlock a week.")
    we = str(week_ending)
    end = clock.d(we)
    start = (end - timedelta(days=6)).isoformat()
    with office.db.tx():
        for r in office.db.rows("SELECT id FROM week_locks WHERE week_ending = ? "
                                "AND active = 1", (we,)):
            office.db.update("week_locks", r["id"], active=0,
                             unlocked_by=office.who, unlock_reason=reason)
        office.db.conn.execute(
            "UPDATE time_lines SET status = 'Approved' WHERE status = 'Locked' "
            "AND date BETWEEN ? AND ?", (start, we))
        office.db.conn.execute(                      # r38 G2.1: per diem too
            "UPDATE per_diem_lines SET status = 'Approved' WHERE status = "
            "'Locked' AND deleted = 0 AND date BETWEEN ? AND ?", (start, we))
        office.audit("unlock", "week", we, None, {"reason": reason})


def approved_lines(office, job_id=None, date_from=None, date_to=None):
    q = ("SELECT t.*, w.labor_class, w.name AS worker FROM time_lines t "
         "JOIN workers w ON w.id = t.worker_id WHERE t.status IN "
         "('Approved','Locked') AND t.deleted = 0")
    p = []
    if job_id is not None:
        q += " AND t.job_id = ?"
        p.append(job_id)
    if date_from:
        q += " AND t.date >= ?"
        p.append(str(date_from))
    if date_to:
        q += " AND t.date <= ?"
        p.append(str(date_to))
    return office.db.rows(q + " ORDER BY t.date, t.id", p)


def labor_cost(office, ln) -> int:
    """Estimated labor cost of a line: hours x loaded rate x pay factor."""
    rate = loaded_rate(office, ln["labor_class"])
    return cents.mul(rate, cents.D(ln["hours"]) / 100 *
                     cents.D(PAY_FACTOR[ln["pay_type"]]))
