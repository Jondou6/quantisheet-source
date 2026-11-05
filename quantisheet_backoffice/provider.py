"""Payroll provider files (P2-02): export the payroll preview as the
provider's import file; import the provider's register back.

Decision 9 = A: a generic CSV with a saved column map. Back Office never
files taxes or moves money (decision 8 = A); the register only fills in
actual labor cost, taxes and net pay for reports and pay stubs. No SSN or
bank number goes into the export: employees are matched by employee number.
"""
from __future__ import annotations

import csv
import io
import json
import os

from . import cents, clock, fileguard, payroll

EXPORT_COLUMNS = ["Employee number", "Employee name", "Period start",
                  "Period end", "Pay date", "Earning code", "Hours", "Rate",
                  "Amount", "Job", "Cost code"]
DEFAULT_EARNINGS = {"REG": "REG", "OT": "OT", "DT": "DT", "PTO": "PTO",
                    "HOL": "HOL"}
# r38 G2.3: approved per diem goes out as its own non-wage earning line
# (no hours, no rate), never inside gross. Mappable like the others; a map
# saved before this has no entry and gets the code as is.
NON_WAGE = {"PERDIEM": "PERDIEM"}
REGISTER_COLUMNS = {"employee_no": "Employee number", "gross": "Gross",
                    "employer_taxes": "Employer taxes",
                    "deductions": "Deductions", "net": "Net",
                    "reference": "Reference"}
DETAILS = ("employee", "job")


class ProviderError(ValueError):
    pass


def add_map(office, name, columns=None, earning_codes=None,
            detail="employee", register_columns=None) -> int:
    """columns: our export column -> the provider's heading (order kept).
    detail 'employee': one row per employee and earning type; 'job': per
    employee, earning type, job and cost code."""
    office.require("payroll.export", "provider_map", name)
    if detail not in DETAILS:
        raise ProviderError(f"detail must be one of {', '.join(DETAILS)}")
    cols = columns or {c: c for c in EXPORT_COLUMNS}
    bad = [c for c in cols if c not in EXPORT_COLUMNS]
    if bad:
        raise ProviderError(f"unknown export column {bad[0]!r}")
    with office.db.tx():
        mid = office.db.insert(
            "provider_maps", name=name, columns=json.dumps(cols),
            earning_codes=json.dumps({**DEFAULT_EARNINGS, **NON_WAGE,
                                      **(earning_codes or {})}),
            detail=detail,
            register_columns=json.dumps(dict(REGISTER_COLUMNS,
                                             **(register_columns or {}))))
        office.audit("create", "provider_map", mid, None, {"name": name})
    return mid


def provider_map(office, mid) -> dict:
    m = office.db.get("provider_maps", mid)
    if m is None:
        raise ProviderError(f"no provider map {mid}")
    for k in ("columns", "earning_codes", "register_columns"):
        m[k] = json.loads(m[k] or "{}")
    return m


def export_rows(office, pid, mid) -> list[dict]:
    from . import jobs
    m = provider_map(office, mid)
    pv = payroll.preview(office, pid)
    p = pv["period"]
    rows = []
    for w in pv["workers"]:
        groups = {}
        for ln in w["lines"]:
            key = (ln["pay_type"],) if m["detail"] == "employee" else \
                (ln["pay_type"], ln["job_id"], ln["cost_code"])
            g = groups.setdefault(key, {"hours": 0, "amount": 0,
                                        "rates": set()})
            g["hours"] += ln["hours"]
            g["amount"] += ln["gross"]
            g["rates"].add(ln["rate"])
        for key in sorted(groups, key=lambda k: (list(DEFAULT_EARNINGS)
                                                  .index(k[0]),) + tuple(
                                                      str(x) for x in k[1:])):
            g = groups[key]
            rate = next(iter(g["rates"])) if len(g["rates"]) == 1 else None
            job = ""
            code = ""
            if len(key) > 1:
                j = jobs.job(office, key[1]) if key[1] else None
                job, code = (j["number"] if j else ""), key[2] or ""
            rows.append({
                "Employee number": w["employee_no"],
                "Employee name": w["name"], "Period start": p["start"],
                "Period end": p["end"], "Pay date": p["pay_date"],
                "Earning code": m["earning_codes"].get(key[0], key[0]),
                "Hours": cents.hours_text(g["hours"]),
                "Rate": cents.text(rate) if rate is not None else "",
                "Amount": cents.text(g["amount"]), "Job": job,
                "Cost code": code, "_hours": g["hours"]})
    rows += _per_diem_rows(office, m, p, pv["workers"])
    return rows


def _per_diem_rows(office, m, p, workers) -> list[dict]:
    """r38 G2.3: one PERDIEM row per worker (per job and cost code with job
    detail) for approved per diem dated in the period. Workers come in the
    preview's order; per-diem-only workers follow by name."""
    from . import jobs, perdiem
    lines = perdiem.approved(office, None, p["start"], p["end"])
    if not lines:
        return []
    order = {w["worker_id"]: i for i, w in enumerate(workers)}
    groups = {}
    for ln in lines:
        key = (ln["worker_id"],) if m["detail"] == "employee" else \
            (ln["worker_id"], ln["job_id"], ln["cost_code"] or "")
        g = groups.setdefault(key, {"amount": 0, "name": ln["worker"],
                                    "employee_no": ln["employee_no"] or ""})
        g["amount"] += ln["amount"]
    rows = []
    code = m["earning_codes"].get("PERDIEM", "PERDIEM")
    for key in sorted(groups, key=lambda k: (order.get(k[0], len(order)),
                                             groups[k]["name"],) +
                      tuple(str(x) for x in k)):
        g = groups[key]
        job = cc = ""
        if len(key) > 1:
            j = jobs.job(office, key[1]) if key[1] else None
            job, cc = (j["number"] if j else ""), key[2]
        rows.append({"Employee number": g["employee_no"],
                     "Employee name": g["name"], "Period start": p["start"],
                     "Period end": p["end"], "Pay date": p["pay_date"],
                     "Earning code": code, "Hours": "", "Rate": "",
                     "Amount": cents.text(g["amount"]), "Job": job,
                     "Cost code": cc, "_hours": 0, "_non_wage": True})
    return rows


def export(office, pid, mid, path=None) -> dict:
    """Write the provider import file. Returns {'path', 'rows', 'hours',
    'amount', 'non_wage_amount'}: 'amount' is wages only (as in 0.13.9);
    per diem is 'non_wage_amount'. Nothing is sent: the user uploads the
    file to the provider."""
    office.require("payroll.export", "pay_period", pid)
    m = provider_map(office, mid)
    rows = export_rows(office, pid, mid)
    p = payroll.period(office, pid)
    if path is None:
        folder = os.path.join(office.output_folder(), "payroll")
        os.makedirs(folder, exist_ok=True)
        path = fileguard.safe_path(folder, f"payroll-{p['end']}-"
                                           f"{m['name'].replace(' ', '_')}.csv")
    fileguard.write_target(path)
    buf = io.StringIO()
    wr = csv.writer(buf, lineterminator="\n")
    wr.writerow(fileguard.safe_row(list(m["columns"].values())))
    for r in rows:
        wr.writerow(fileguard.safe_row([r[c] for c in m["columns"]]))
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(buf.getvalue())
    hours = sum(r["_hours"] for r in rows)
    amount = sum(cents.parse_amount(r["Amount"]) for r in rows
                 if not r.get("_non_wage"))
    non_wage = sum(cents.parse_amount(r["Amount"]) for r in rows
                   if r.get("_non_wage"))
    office.audit("export payroll", "pay_period", pid, None,
                 {"rows": len(rows), "hours": hours, "amount": amount,
                  "non_wage_amount": non_wage,
                  "file": os.path.basename(path)})
    return {"path": path, "rows": len(rows), "hours": hours,
            "amount": amount, "non_wage_amount": non_wage}


# ---- register import ------------------------------------------------------

def _read(path, text):
    if text is None:
        fileguard.refuse_company_file(path)
        with open(path, encoding="utf-8-sig") as fh:
            text = fh.read()
    return list(csv.DictReader(io.StringIO(text)))


def _parse(office, pid, mid, path=None, text=None) -> dict:
    m = provider_map(office, mid)
    rc = m["register_columns"]
    rows = _read(path, text)
    known = {w["employee_no"]: w["id"] for w in office.db.rows(
        "SELECT id, employee_no FROM workers WHERE deleted = 0 AND "
        "employee_no IS NOT NULL AND employee_no != ''")}
    fixed = set(rc.values())
    good, unmatched, problems = [], [], []
    for i, r in enumerate(rows, start=2):
        no = (r.get(rc["employee_no"]) or "").strip()
        if no not in known:
            unmatched.append(f"row {i}: employee number {no or '(blank)'} "
                             f"is not known")
            continue
        try:
            amt = lambda k: cents.parse_amount(r.get(rc[k]) or "0")  # noqa
            item = {"employee_no": no, "worker_id": known[no],
                    "gross": amt("gross"),
                    "employer_taxes": amt("employer_taxes"),
                    "deductions": {"Deductions": amt("deductions")},
                    "net": amt("net"),
                    "reference": (r.get(rc["reference"]) or "").strip(),
                    "taxes": {k: cents.parse_amount(v or "0")
                              for k, v in r.items()
                              if k and k not in fixed and "tax" in k.lower()}}
        except cents.MoneyError as e:
            problems.append(f"row {i}: {e}")
            continue
        good.append(item)
    calc = {w["worker_id"]: w["gross"]
            for w in payroll.preview(office, pid)["workers"]}
    mismatches = [f"{g['employee_no']}: register gross "
                  f"{cents.fmt(g['gross'])}, Back Office "
                  f"{cents.fmt(calc.get(g['worker_id'], 0))}"
                  for g in good if calc.get(g["worker_id"], 0) != g["gross"]]
    return {"rows": good, "unmatched": unmatched, "problems": problems,
            "mismatches": mismatches}


def preview_register(office, pid, mid, path=None, text=None) -> dict:
    office.require("payroll.export", "pay_period", pid)
    r = _parse(office, pid, mid, path, text)
    return {"matched": len(r["rows"]), "unmatched": r["unmatched"],
            "problems": r["problems"], "mismatches": r["mismatches"]}


def import_register(office, pid, mid, path=None, text=None) -> dict:
    """Import matched rows; unmatched and unreadable rows are listed and
    change nothing. Re-importing a worker's row for the period replaces it."""
    office.require("payroll.export", "pay_period", pid)
    r = _parse(office, pid, mid, path, text)
    batch = clock.iso_now()
    with office.db.tx():
        for g in r["rows"]:
            old = office.db.one("SELECT id FROM provider_registers WHERE "
                                "period_id = ? AND worker_id = ? AND "
                                "deleted = 0", (pid, g["worker_id"]))
            if old:
                office.db.soft_delete("provider_registers", old["id"])
            office.db.insert("provider_registers", period_id=pid,
                             worker_id=g["worker_id"],
                             employee_no=g["employee_no"], gross=g["gross"],
                             employer_taxes=g["employer_taxes"],
                             taxes=g["taxes"], deductions=g["deductions"],
                             net=g["net"], reference=g["reference"],
                             pay_date=payroll.period(office, pid)["pay_date"],
                             import_batch=batch)
        office.audit("import register", "pay_period", pid, None,
                     {"imported": len(r["rows"]),
                      "unmatched": len(r["unmatched"])})
    return {"imported": len(r["rows"]), "unmatched": r["unmatched"],
            "problems": r["problems"], "mismatches": r["mismatches"]}


def register(office, pid) -> list[dict]:
    rows = office.db.rows("SELECT * FROM provider_registers WHERE period_id = ? "
                          "AND deleted = 0 ORDER BY employee_no", (pid,))
    for r in rows:
        r["taxes"] = json.loads(r["taxes"] or "{}")
        r["deductions"] = json.loads(r["deductions"] or "{}")
    return rows


def stubs_for(office, worker_id) -> list[dict]:
    """Pay stubs from imported registers (for self-service, P2-07)."""
    rows = office.db.rows(
        "SELECT r.*, p.start, p.end FROM provider_registers r JOIN "
        "pay_periods p ON p.id = r.period_id WHERE r.worker_id = ? AND "
        "r.deleted = 0 ORDER BY p.end", (worker_id,))
    for r in rows:
        r["taxes"] = json.loads(r["taxes"] or "{}")
        r["deductions"] = json.loads(r["deductions"] or "{}")
    return rows
