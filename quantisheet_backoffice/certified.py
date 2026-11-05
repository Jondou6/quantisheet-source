"""Certified payroll report and statement of compliance (P2-03).

Weekly, per prevailing-wage job, from FINAL payroll (P2-01) and, when it
has been imported, the provider's register (P2-02) for deductions and net.
Back Office's own layout carrying the information the federal weekly
certified payroll asks for (contractor, project and contract number,
payroll number, week ending, each worker's identifying number,
classification, daily and weekly hours, rates, fringes, gross, deductions
and net, plus a signed statement of compliance). Workers are identified by
employee number, never by SSN. The statement wording is our own: have
counsel check it against the current federal requirements before use.

A worker paid below the job's wage determination (base, or base + fringe)
blocks the report with the worker named. A printed report is a frozen file
with a hash; reprints return that file. A correction makes a new numbered
report marked 'Revised' with the same payroll number.
"""
from __future__ import annotations

import csv
import io
import json
import os
from datetime import timedelta

from . import cents, clock, fileguard, jobs, payroll, provider, store

DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


class CertifiedError(ValueError):
    pass


def add_signer(office, name, title) -> int:
    office.require("certified.edit", "cp_signer", name)
    with office.db.tx():
        sid = office.db.insert("cp_signers", name=name, title=title, active=1)
        office.audit("create", "cp_signer", sid, None,
                     {"name": name, "title": title})
    return sid


def _signer(office, name):
    s = office.db.one("SELECT * FROM cp_signers WHERE name = ? AND active = 1 "
                      "AND deleted = 0", (name,))
    if s is None:
        raise CertifiedError(f"{name} is not set up to sign the statement of "
                             f"compliance (Certified Payroll > Signers).")
    return s


def _period_for(office, week_ending):
    p = office.db.one("SELECT * FROM pay_periods WHERE deleted = 0 AND ? "
                      "BETWEEN start AND end ORDER BY id DESC",
                      (str(week_ending),))
    if p is None:
        raise CertifiedError(f"No pay period covers the week ending "
                             f"{week_ending}.")
    return p


def check(office, job_id, week_ending) -> dict:
    """Rows, totals, exceptions and blocking problems for one job-week."""
    office.require("certified.edit", "job", job_id)
    we = clock.d(week_ending)
    ws = we - timedelta(days=6)
    p = _period_for(office, we)
    pv = payroll.preview(office, p["id"])
    regs = {r["worker_id"]: r for r in provider.register(office, p["id"])}
    rows, exceptions, blocking = [], [], []
    if p["status"] != "Final":
        exceptions.append(f"Payroll for {p['start']} to {p['end']} is not "
                          f"final yet.")
    for w in pv["workers"]:
        mine = [ln for ln in w["lines"] if ln["job_id"] == job_id and
                ws <= clock.d(ln["date"]) <= we and
                ln["pay_type"] in payroll.WORKED]
        if not mine:
            continue
        e = office.db.one("SELECT * FROM employees WHERE worker_id = ? AND "
                          "deleted = 0", (w["worker_id"],)) or {}
        days, ot_days = [0] * 7, [0] * 7
        for ln in mine:
            i = (clock.d(ln["date"]) - ws).days
            (days if ln["pay_type"] == "REG" else ot_days)[i] += ln["hours"]
        name = w["name"]
        cls = e.get("classification") or ""
        if not cls:
            blocking.append(f"{name}: no classification")
        base = max(ln["base"] for ln in mine)
        hrs = sum(ln["hours"] for ln in mine)
        fringe = sum(ln["fringe_cash"] + ln["fringe_plan"] for ln in mine)
        fringe_rate = int(cents.round_half_up(cents.D(fringe) * 100 / hrs)) \
            if hrs else 0
        for ln in mine:
            det = payroll._rate_row(office, ln["date"], kind="prevailing",
                                    job_id=job_id, classification=cls) \
                if cls else None
            if det is None:
                continue
            paid = ln["base"]
            need_fr = sum(f["amount"] for f in json.loads(det["fringes"] or
                                                           "[]"))
            msg = None
            if paid < det["base_rate"]:
                msg = (f"{name}: paid {cents.fmt(paid)}/h, below the "
                       f"determination rate {cents.fmt(det['base_rate'])}/h "
                       f"({cls}, {det['determination_no']})")
            elif paid + fringe_rate < det["base_rate"] + need_fr:
                msg = (f"{name}: paid {cents.fmt(paid + fringe_rate)}/h with "
                       f"fringes, below the determination's "
                       f"{cents.fmt(det['base_rate'] + need_fr)}/h ({cls})")
            if msg and msg not in blocking:
                blocking.append(msg)
        reg = regs.get(w["worker_id"])
        gross_job = sum(ln["gross"] for ln in mine)
        rows.append({
            "worker_id": w["worker_id"], "name": name,
            "employee_no": w["employee_no"], "classification": cls,
            "apprentice": bool(e.get("apprentice")), "days": days,
            "ot_days": ot_days, "hours": hrs, "rate": base,
            "ot_rate": cents.mul(base, "1.5"), "fringe_rate": fringe_rate,
            "fringe_cash": sum(ln["fringe_cash"] for ln in mine),
            "fringe_plan": sum(ln["fringe_plan"] for ln in mine),
            "gross_project": gross_job, "gross_all": w["gross"],
            "taxes": sum(reg["taxes"].values()) if reg else None,
            "deductions": sum(reg["deductions"].values()) if reg else None,
            "net": reg["net"] if reg else None})
    if rows and not regs:
        exceptions.append("Deductions and net pay come from the payroll "
                          "provider's register, not imported yet.")
    totals = {"workers": len(rows),
              "hours": sum(r["hours"] for r in rows),
              "gross_project": sum(r["gross_project"] for r in rows),
              "fringe_cash": sum(r["fringe_cash"] for r in rows),
              "fringe_plan": sum(r["fringe_plan"] for r in rows)}
    return {"job_id": job_id, "week_ending": we.isoformat(),
            "week_start": ws.isoformat(), "period": p, "rows": rows,
            "totals": totals, "exceptions": exceptions,
            "blocking": blocking}


def _existing(office, job_id, week_ending):
    return office.db.rows("SELECT * FROM certified_reports WHERE job_id = ? "
                          "AND week_ending = ? AND deleted = 0 ORDER BY id",
                          (job_id, str(week_ending)))


def create(office, job_id, week_ending, signer, final=False,
           _revises=None, _reason="") -> int:
    office.require("certified.edit", "job", job_id)
    s = _signer(office, signer)
    chk = check(office, job_id, week_ending)
    if chk["period"]["status"] != "Final":
        raise CertifiedError("Finalize the payroll for this week first.")
    if chk["blocking"]:
        raise CertifiedError("Can't print: " + "; ".join(chk["blocking"]))
    if not chk["rows"]:
        raise CertifiedError("No payroll on this job for that week.")
    old = _existing(office, job_id, week_ending)
    if old and _revises is None:
        if any(o["status"] == "Submitted" for o in old):
            raise CertifiedError("A report for this week was submitted; use "
                                 "Correct to make a revised report.")
        payroll_no = old[0]["payroll_no"]
    elif _revises is not None:
        payroll_no = _revises["payroll_no"]
    else:
        payroll_no = 1 + (office.db.scalar(
            "SELECT MAX(payroll_no) FROM certified_reports WHERE job_id = ? "
            "AND deleted = 0", (job_id,)) or 0)
    revision = (_revises["revision"] + 1) if _revises else 0
    number = office.db.next_number("CP", "CP-{n:04d}")
    folder = os.path.join(office.output_folder(), "certified")
    os.makedirs(folder, exist_ok=True)
    path = fileguard.safe_path(folder, f"{number}.pdf")
    _pdf(office, chk, path, number, payroll_no, revision, final, s,
         _reason)
    h = store.file_hash(path)
    with office.db.tx():
        rid = office.db.insert(
            "certified_reports", number=number, job_id=job_id,
            week_ending=chk["week_ending"], payroll_no=payroll_no,
            revision=revision, final=1 if final else 0, signer=s["name"],
            signer_title=s["title"], signed_on=clock.today().isoformat(),
            file_path=path, file_hash=h,
            status="Revised" if revision else "Printed",
            totals=chk["totals"], revises_id=_revises and _revises["id"])
        office.audit("print", "certified_report", rid, None,
                     {"number": number, "payroll_no": payroll_no,
                      "revision": revision, "hash": h, "reason": _reason})
    return rid


def report(office, rid) -> dict:
    r = office.db.get("certified_reports", rid)
    if r is None:
        raise CertifiedError(f"no certified report {rid}")
    r["totals"] = json.loads(r["totals"] or "{}")
    r["rows"] = check(office, r["job_id"], r["week_ending"])["rows"]
    return r


def mark_submitted(office, rid) -> None:
    office.require("certified.edit", "certified_report", rid)
    with office.db.tx():
        office.db.update("certified_reports", rid, status="Submitted",
                         submitted_on=clock.today().isoformat())
        office.audit("submitted", "certified_report", rid)


def reprint(office, rid) -> str:
    """The frozen file, checked against its hash."""
    r = office.db.get("certified_reports", rid)
    if store.file_hash(r["file_path"]) != r["file_hash"]:
        raise CertifiedError(f"{r['number']}'s file has changed since it was "
                             f"printed.")
    office.audit("reprint", "certified_report", rid)
    return r["file_path"]


def correct(office, rid, reason) -> int:
    if not str(reason).strip():
        raise CertifiedError("A correction needs a reason.")
    r = office.db.get("certified_reports", rid)
    return create(office, r["job_id"], r["week_ending"], r["signer"],
                  final=bool(r["final"]), _revises=r, _reason=reason)


# ---- CSV reports ---------------------------------------------------------

def fringe_csv(office, job_id, week_ending) -> str:
    chk = check(office, job_id, week_ending)
    buf = io.StringIO()
    wr = csv.writer(buf, lineterminator="\n")
    wr.writerow(fileguard.safe_row(["Employee number", "Name", "Classification", "Hours",
                 "Fringe per hour", "Fringe paid to plans",
                 "Fringe paid in cash"]))
    for r in chk["rows"]:
        wr.writerow(fileguard.safe_row([r["employee_no"], r["name"], r["classification"],
                     cents.hours_text(r["hours"]), cents.text(r["fringe_rate"]),
                     cents.text(r["fringe_plan"]), cents.text(r["fringe_cash"])]))
    return buf.getvalue()


def workforce_csv(office, job_id, date_from, date_to) -> str:
    """Hours and head count by classification, journeyworker vs apprentice.
    (No demographic fields: Back Office doesn't collect them.)"""
    office.require("certified.edit", "job", job_id)
    rows = office.db.rows(
        "SELECT l.worker_id, l.hours, e.classification, e.apprentice FROM "
        "payroll_lines l JOIN pay_periods p ON p.id = l.period_id LEFT JOIN "
        "employees e ON e.worker_id = l.worker_id AND e.deleted = 0 WHERE "
        "l.job_id = ? AND l.deleted = 0 AND p.status = 'Final' AND l.date "
        "BETWEEN ? AND ? AND l.pay_type IN ('REG','OT','DT')",
        (job_id, str(date_from), str(date_to)))
    agg = {}
    for r in rows:
        k = (r["classification"] or "(none)",
             "Apprentice" if r["apprentice"] else "Journeyworker")
        a = agg.setdefault(k, {"hours": 0, "workers": set()})
        a["hours"] += r["hours"]
        a["workers"].add(r["worker_id"])
    buf = io.StringIO()
    wr = csv.writer(buf, lineterminator="\n")
    wr.writerow(fileguard.safe_row(["Classification", "Level", "Workers", "Hours"]))
    for (cls, lvl), a in sorted(agg.items()):
        wr.writerow(fileguard.safe_row([cls, lvl, len(a["workers"]), cents.hours_text(a["hours"])]))
    return buf.getvalue()


# ---- PDF -----------------------------------------------------------------

def _pdf(office, chk, path, number, payroll_no, revision, final, signer,
         reason):
    import fitz
    from .output import _Pg
    c = office.company()
    j = jobs.job(office, chk["job_id"])
    proj = json.loads(j.get("project") or "{}") if j.get("project") else {}
    doc = fitz.open()
    pg = _Pg(doc)
    pg.p.set_rotation(0)
    pg.t(54, 50, c.get("name") or "", 12, True)
    for i, ln in enumerate((c.get("address") or "").splitlines()[:2]):
        pg.t(54, 63 + 10 * i, ln, 8)
    title = "Certified Payroll Report (prevailing wage)"
    if revision:
        title += f" - REVISED (revision {revision})"
    pg.t(54, 98, title, 13, True)
    pg.t(54, 114, f"Report {number}    Payroll no. {payroll_no}"
                  f"{'    FINAL' if final else ''}    Week ending "
                  f"{chk['week_ending']}", 9)
    pg.t(54, 126, f"Project: {j['name']} ({j['number']})    Location: "
                  f"{proj.get('address', '')}", 8.5)
    pg.t(54, 137, f"Contract no.: {proj.get('contract_no', '') or '-'}", 8.5)
    pg.line(143)
    y = 156
    hdr = ["Employee / no. / class"] + list(DAYS) + ["Hours", "Rate", "Gross"]
    xs = [54, 220, 248, 276, 304, 332, 360, 388, 420, 462, 520]
    for x, h in zip(xs, hdr):
        pg.t(x, y, h, 7.5, True)
    y += 12
    for r in chk["rows"]:
        if y > 700:
            pg = _Pg(doc)
            y = 60
        pg.t(54, y, r["name"], 8, True)
        pg.t(54, y + 9, f"{r['employee_no']}  {r['classification']}"
                        f"{' (apprentice)' if r['apprentice'] else ''}", 7)
        for i in range(7):
            s = cents.hours_text(r["days"][i]) if r["days"][i] else ""
            if r["ot_days"][i]:
                s += f"+{cents.hours_text(r['ot_days'][i])}OT"
            pg.t(xs[1 + i], y, s, 6.5)
        pg.t(xs[8], y, cents.hours_text(r["hours"]), 7.5)
        pg.t(xs[9], y, cents.text(r["rate"]), 7.5)
        pg.t(xs[10], y, cents.text(r["gross_project"]), 7.5)
        ded = "deductions/net from provider register not imported" \
            if r["net"] is None else \
            (f"Gross all work {cents.fmt(r['gross_all'])}  Taxes "
             f"{cents.fmt(r['taxes'])}  Other deductions "
             f"{cents.fmt(r['deductions'])}  Net {cents.fmt(r['net'])}")
        pg.t(220, y + 9, f"OT rate {cents.text(r['ot_rate'])}  Fringe "
                         f"{cents.text(r['fringe_rate'])}/h (plan "
                         f"{cents.text(r['fringe_plan'])}, cash "
                         f"{cents.text(r['fringe_cash'])})  {ded}", 6.5)
        y += 24
    t = chk["totals"]
    pg.line(y)
    pg.t(54, y + 12, f"Totals: {t['workers']} workers, "
                     f"{cents.hours_text(t['hours'])} h, gross on this project "
                     f"{cents.fmt(t['gross_project'])}", 8.5, True)
    if reason:
        pg.t(54, y + 24, f"Revised because: {reason}", 8)
    pg = _Pg(doc)
    pg.t(54, 60, "Statement of Compliance", 13, True)
    lines = [
        f"I, {signer['name']}, {signer['title']} of {c.get('name') or ''},",
        f"state for payroll no. {payroll_no} (week ending "
        f"{chk['week_ending']}) on {j['name']}:",
        "1. I pay or supervise the payment of the people on this payroll.",
        "   Each was paid the full wages earned for the week, with no",
        "   rebates or deductions other than those the law allows.",
        "2. This payroll is correct and complete. No one was paid less than",
        "   the wage determination rate for the classification of work done.",
        "3. Any apprentice listed is registered in an approved program.",
        "4. Fringe benefits were paid to plans or in cash as shown.",
        "Exceptions: " + ("; ".join(chk["exceptions"]) or "none"),
        "",
        f"Signed: ______________________   {signer['name']}, "
        f"{signer['title']}",
        "Date:   ______________________",
        "",
        "Knowingly false statements can bring civil or criminal penalties.",
    ]
    for i, ln in enumerate(lines):
        pg.t(54, 90 + 14 * i, ln, 9)
    doc.set_metadata({"title": f"{number} certified payroll",
                      "creator": "QuantiSheet Back Office"})
    doc.save(path)
    doc.close()


def pdf_text(path) -> str:
    import fitz
    with fitz.open(path) as d:
        return "\n".join(p.get_text() for p in d)
