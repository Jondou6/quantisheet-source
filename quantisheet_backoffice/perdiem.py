"""Per diem (r38 G2.1): a flat daily amount paid to a worker for a day on a
job, kept apart from wages.

Back Office ships no per diem rate and no amount: nothing is made until a
user sets a job's rate (set_job_rate) or types an amount. One per diem per
worker per day. Lines are Draft -> Submitted -> Approved (record type
"per_diem", the same approval paths as time) -> Locked with the week
(timeentry.lock_week), and can't change inside a final pay period.
Approved / Locked per diem rolls up to the job's cost code in job cost as
its own column (not labor). Amounts are int cents.
"""
from __future__ import annotations

from . import approvals, cents, clock, jobs, timeentry

KINDS = ("Per diem", "Meals", "Lodging")
RECORD = "per_diem"
COUNTED = ("Approved", "Locked")


class PerDiemError(ValueError):
    pass


def _amount(v) -> int:
    c = cents.amount_in(v)          # dollars as text / Decimal; ints refused
    if c <= 0:
        raise PerDiemError("a per diem must be more than $0.00")
    return c


# ---- rates (set by the user; none shipped) --------------------------------

def set_job_rate(office, job_id, amount, cost_code="", effective_from="") -> int:
    office.require("time.approve", "per_diem_rate", job_id)
    c = _amount(amount)
    eff = str(clock.d(effective_from)) if effective_from else "0000-01-01"
    with office.db.tx():
        rid = office.db.insert("per_diem_rates", job_id=job_id, amount=c,
                               cost_code=cost_code, effective_from=eff)
        office.audit("create", "per_diem_rate", rid, None,
                     {"job": job_id, "amount": c, "cost_code": cost_code,
                      "effective_from": eff})
    return rid


def job_rate(office, job_id, date) -> dict | None:
    return office.db.one(
        "SELECT * FROM per_diem_rates WHERE job_id = ? AND deleted = 0 AND "
        "effective_from <= ? ORDER BY effective_from DESC, id DESC LIMIT 1",
        (job_id, str(clock.d(date))))


# ---- lines ----------------------------------------------------------------

def _guard_date(office, d) -> None:
    if timeentry._week_locked(office, d):
        raise PerDiemError(f"The week ending {jobs.week_ending(d)} is locked.")
    try:
        timeentry._payroll_final(office, d)
    except timeentry.TimeError as e:
        raise PerDiemError(str(e)) from None


def _taken(office, worker_id, date, skip_id=None) -> bool:
    return bool(office.db.one(
        "SELECT id FROM per_diem_lines WHERE worker_id = ? AND date = ? AND "
        "deleted = 0 AND id IS NOT ?", (worker_id, str(date), skip_id)))


def add(office, worker_id, date, job_id, cost_code="", amount=None,
        kind="Per diem", note="", source="manual", source_key=None) -> int:
    office.require("time.edit", "per_diem", "")
    d = str(clock.d(date))
    if kind not in KINDS:
        raise PerDiemError(f"kind must be one of {', '.join(KINDS)}")
    if amount is None:
        rate = job_rate(office, job_id, d)
        if rate is None:
            raise PerDiemError("This job has no per diem rate set; type an "
                               "amount or set the job's rate first.")
        c = rate["amount"]
        cost_code = cost_code or rate["cost_code"]
    else:
        c = _amount(amount)
    _guard_date(office, d)
    if _taken(office, worker_id, d):
        raise PerDiemError(f"This worker already has a per diem on {d}.")
    with office.db.tx():
        pid = office.db.insert("per_diem_lines", worker_id=worker_id, date=d,
                               job_id=job_id, cost_code=cost_code, kind=kind,
                               amount=c, note=note, status="Draft",
                               source=source, source_key=source_key)
        office.audit("create", "per_diem", pid, None,
                     {"worker": worker_id, "date": d, "amount": c,
                      "cost_code": cost_code})
    return pid


def _editable(office, pid) -> dict:
    ln = office.db.get("per_diem_lines", pid)
    if ln is None or ln["deleted"]:
        raise PerDiemError(f"Per diem {pid} not found.")
    _guard_date(office, ln["date"])
    if ln["status"] == "Locked":
        raise PerDiemError(f"The week ending {jobs.week_ending(ln['date'])} "
                           f"is locked; an Admin must unlock it first.")
    if ln["status"] not in ("Draft", "Rejected"):
        raise PerDiemError(f"A {ln['status']} per diem can't be changed.")
    return ln


def edit(office, pid, **fields) -> None:
    office.require("time.edit", "per_diem", pid)
    ln = _editable(office, pid)
    allowed = {"amount", "cost_code", "kind", "note", "job_id", "date"}
    bad = set(fields) - allowed
    if bad:
        raise PerDiemError(f"can't change {', '.join(sorted(bad))}")
    if "amount" in fields:
        fields["amount"] = _amount(fields["amount"])
    if "kind" in fields and fields["kind"] not in KINDS:
        raise PerDiemError(f"kind must be one of {', '.join(KINDS)}")
    if "date" in fields:
        fields["date"] = str(clock.d(fields["date"]))
        _guard_date(office, fields["date"])
        if _taken(office, ln["worker_id"], fields["date"], pid):
            raise PerDiemError(f"This worker already has a per diem on "
                               f"{fields['date']}.")
    with office.db.tx():
        office.db.update("per_diem_lines", pid, **fields)
        office.audit("change", "per_diem", pid, {k: ln[k] for k in fields},
                     fields)


def delete(office, pid) -> None:
    office.require("time.edit", "per_diem", pid)
    _editable(office, pid)
    with office.db.tx():
        office.db.soft_delete("per_diem_lines", pid)
        office.audit("delete", "per_diem", pid)


def from_time(office, date_from, date_to, job_id=None) -> list[int]:
    """Draft per diem for each worker-day with time on a job that has a
    rate. The day goes to the job (then cost code) with the most hours;
    days that already have a per diem are skipped, so a rerun adds nothing."""
    office.require("time.edit", "per_diem", "from_time")
    q = ("SELECT worker_id, date, job_id, cost_code, SUM(hours) AS h FROM "
         "time_lines WHERE deleted = 0 AND hours > 0 AND date BETWEEN ? AND ? "
         "GROUP BY worker_id, date, job_id, cost_code "
         "ORDER BY worker_id, date, h DESC, job_id, cost_code")
    best = {}
    for r in office.db.rows(q, (str(date_from), str(date_to))):
        best.setdefault((r["worker_id"], r["date"]), r)
    out = []
    for (wid, d), r in sorted(best.items()):
        if job_id is not None and r["job_id"] != job_id:
            continue
        rate = job_rate(office, r["job_id"], d)
        if rate is None or _taken(office, wid, d):
            continue
        if timeentry._week_locked(office, d):
            continue
        try:
            timeentry._payroll_final(office, d)
        except timeentry.TimeError:
            continue
        out.append(add(office, wid, d, r["job_id"],
                       rate["cost_code"] or r["cost_code"],
                       cents.from_cents(rate["amount"]),
                       source="time", source_key=f"{wid}:{d}"))
    return out


# ---- submit / approve -----------------------------------------------------

def submit(office, ids) -> None:
    office.require("time.edit", "per_diem", "submit")
    for pid in ids:
        ln = office.db.get("per_diem_lines", pid)
        codes = jobs.cost_codes(office, ln["job_id"])
        if not ln["cost_code"]:
            raise PerDiemError(f"Per diem {pid} has no cost code.")
        if ln["cost_code"] not in codes:
            j = jobs.job(office, ln["job_id"])
            raise PerDiemError(f"Cost code {ln['cost_code']} is not in job "
                               f"{j['number']}'s code list.")
        if ln["status"] not in ("Draft", "Rejected"):
            raise PerDiemError(f"A {ln['status']} per diem can't be submitted.")
    for pid in ids:
        ln = office.db.get("per_diem_lines", pid)
        with office.db.tx():
            office.db.update("per_diem_lines", pid, status="Submitted",
                             reject_reason=None)
            approvals.start(office, RECORD, pid,
                            approvals.path_for(office, RECORD, ln["job_id"]),
                            ln["job_id"])


def _owner(office, ln):
    w = office.db.get("workers", ln["worker_id"])
    return w["user_id"] if w else None


def decide(office, ids, decision, reason="") -> None:
    office.require("time.approve", "per_diem", "approve")
    for pid in ids:
        ln = office.db.get("per_diem_lines", pid)
        approvals.precheck(office, RECORD, pid, decision, reason,
                           owner_id=_owner(office, ln))
        with office.db.tx():
            req = approvals.decide(office, RECORD, pid, decision, reason,
                                   owner_id=_owner(office, ln))
            if req["status"] == "rejected":
                office.db.update("per_diem_lines", pid, status="Draft",
                                 reject_reason=reason)
            elif req["status"] == "approved":
                office.db.update("per_diem_lines", pid, status="Approved")


def status_text(office, pid) -> str:
    ln = office.db.get("per_diem_lines", pid)
    req = approvals.request(office, RECORD, pid)
    if ln["status"] == "Submitted" and req:
        return f"{ln['status']}, {approvals.waiting_on(office, req)}"
    return ln["status"]


def approved(office, job_id=None, date_from=None, date_to=None) -> list[dict]:
    q = ("SELECT p.*, w.name AS worker, w.employee_no, w.labor_class FROM "
         "per_diem_lines p JOIN workers w ON w.id = p.worker_id WHERE "
         "p.status IN ('Approved','Locked') AND p.deleted = 0")
    prm = []
    if job_id is not None:
        q += " AND p.job_id = ?"
        prm.append(job_id)
    if date_from:
        q += " AND p.date >= ?"
        prm.append(str(date_from))
    if date_to:
        q += " AND p.date <= ?"
        prm.append(str(date_to))
    return office.db.rows(q + " ORDER BY p.date, p.id", prm)


def lines(office, limit=500) -> list[dict]:
    return office.db.rows(
        "SELECT p.*, w.name AS worker, j.number AS job FROM per_diem_lines p "
        "LEFT JOIN workers w ON w.id = p.worker_id LEFT JOIN jobs j ON "
        "j.id = p.job_id WHERE p.deleted = 0 ORDER BY p.date DESC, p.id DESC "
        "LIMIT ?", (limit,))
