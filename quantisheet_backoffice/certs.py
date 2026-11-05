"""Certifications and licenses with expiry reminders (P2-05).

Expired certifications that a job requires block assigning the worker to
that job and put a warning on time coded to it. Reminders are drafts for a
person to send; nothing is sent.
"""
from __future__ import annotations

from datetime import timedelta

from . import clock, jobs


class CertError(ValueError):
    pass


def add_type(office, name, renew_months=None) -> int:
    office.require("certs.edit", "cert_type", name)
    with office.db.tx():
        tid = office.db.insert("cert_types", name=name,
                               renew_months=renew_months)
        office.audit("create", "cert_type", tid, None, {"name": name})
    return tid


def add_cert(office, employee_id, type_id, number="", issued=None,
             expires=None, file_path=None) -> int:
    office.require("certs.edit", "employee_cert", employee_id)
    t = office.db.get("cert_types", type_id)
    if expires is None and issued and t["renew_months"]:
        d = clock.d(issued)
        m = d.month - 1 + t["renew_months"]
        expires = d.replace(year=d.year + m // 12, month=m % 12 + 1,
                            day=min(d.day, 28)).isoformat()
    with office.db.tx():
        cid = office.db.insert("employee_certs", employee_id=employee_id,
                               type_id=type_id, number=number,
                               issued=str(clock.d(issued)) if issued else None,
                               expires=str(clock.d(expires)) if expires
                               else None, file_path=file_path)
        office.audit("create", "employee_cert", cid, None,
                     {"employee": employee_id, "type": t["name"],
                      "expires": expires})
    return cid


def require_for_job(office, job_id, type_id) -> int:
    office.require("certs.edit", "job", job_id)
    with office.db.tx():
        rid = office.db.insert("job_cert_requirements", job_id=job_id,
                               type_id=type_id)
        office.audit("require cert", "job", job_id, None, {"type": type_id})
    return rid


def _latest(office, employee_id, type_id):
    return office.db.one("SELECT * FROM employee_certs WHERE employee_id = ? "
                         "AND type_id = ? AND deleted = 0 ORDER BY expires "
                         "DESC", (employee_id, type_id))


def matrix(office) -> dict:
    """{employee name: {type name: expires or ''}}."""
    types = office.db.rows("SELECT * FROM cert_types WHERE deleted = 0 "
                           "ORDER BY name")
    out = {}
    for e in office.db.rows("SELECT id, name FROM employees WHERE deleted = 0 "
                            "AND status != 'Terminated' ORDER BY name"):
        out[e["name"]] = {}
        for t in types:
            c = _latest(office, e["id"], t["id"])
            out[e["name"]][t["name"]] = (c["expires"] or "no expiry") if c \
                else ""
    return out


def expiring(office, as_of=None, days=30) -> list[dict]:
    d = clock.d(as_of or clock.today())
    end = d + timedelta(days=days)
    rows = office.db.rows(
        "SELECT c.*, e.name AS employee, t.name AS type FROM employee_certs c "
        "JOIN employees e ON e.id = c.employee_id JOIN cert_types t ON "
        "t.id = c.type_id WHERE c.deleted = 0 AND e.status != 'Terminated' "
        "AND c.expires IS NOT NULL AND c.expires <= ? ORDER BY c.expires",
        (end.isoformat(),))
    out = []
    for r in rows:
        newer = office.db.one("SELECT id FROM employee_certs WHERE employee_id "
                              "= ? AND type_id = ? AND expires > ? AND "
                              "deleted = 0", (r["employee_id"], r["type_id"],
                                              r["expires"]))
        if newer:
            continue
        r["status"] = "expired" if r["expires"] < d.isoformat() else \
            "expiring"
        out.append(r)
    return out


def reminder_text(office, cert) -> str:
    return (f"Hi {cert['employee']}, your {cert['type']} "
            f"{'expired' if cert['status'] == 'expired' else 'expires'} on "
            f"{cert['expires']}. Please renew it and send the office a copy.")


def _problems(office, employee_id, job_id, d) -> list[str]:
    e = office.db.get("employees", employee_id)
    out = []
    for req in office.db.rows("SELECT r.type_id, t.name FROM "
                              "job_cert_requirements r JOIN cert_types t ON "
                              "t.id = r.type_id WHERE r.job_id = ? AND "
                              "r.deleted = 0", (job_id,)):
        c = _latest(office, employee_id, req["type_id"])
        num = jobs.job(office, job_id)["number"]
        if c is None:
            out.append(f"{e['name']}: no {req['name']} on file; job {num} "
                       f"requires it")
        elif c["expires"] and c["expires"] < str(d):
            out.append(f"{e['name']}: {req['name']} expired {c['expires']}; "
                       f"job {num} requires it")
    return out


def time_warnings(office, time_line_id) -> list[str]:
    ln = office.db.get("time_lines", time_line_id)
    if not ln or not ln["job_id"]:
        return []
    e = office.db.one("SELECT id FROM employees WHERE worker_id = ? AND "
                      "deleted = 0", (ln["worker_id"],))
    if e is None:
        return []
    return _problems(office, e["id"], ln["job_id"], ln["date"])


def assign_to_job(office, employee_id, job_id, d=None) -> None:
    """Refuses when a certification the job requires is missing or expired."""
    probs = _problems(office, employee_id, job_id, clock.d(d or clock.today()))
    if probs:
        raise CertError("; ".join(probs))
    return None
