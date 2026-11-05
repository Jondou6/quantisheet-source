"""Field reports link (P2-10). No new daily log: Back Office reads
QuantiSheet's Daily Log manpower and Time Card production quantities from
the snapshot and sets them beside approved hours and job cost.

  manpower    per day: own-forces workers x hours each from the daily logs
              vs approved time on the job; any difference is flagged.
              Subcontractor manpower is listed, not compared.
  unit_costs  per cost code: production quantity (by unit) from time cards
              and job-cost actual -> cost per unit, half up.
"""
from __future__ import annotations

import re
from decimal import Decimal

from . import cents, jobcost, jobs, timeentry

_SUFFIX = {"LLC", "INC", "CO", "CORP", "LTD", "COMPANY", "THE"}


def _norm(name) -> str:
    words = [w for w in re.findall(r"[A-Z0-9]+", str(name).upper())
             if w not in _SUFFIX]
    return " ".join(words)


def _own(office, company) -> bool:
    if not str(company).strip():
        return True
    mine = _norm(office.company().get("name") or "")
    other = _norm(company)
    return bool(mine) and (mine == other or mine.startswith(other) or
                           other.startswith(mine))


def manpower(office, job_id, date_from=None, date_to=None) -> list[dict]:
    logs = {}
    for lg in jobs.section(office, job_id, "daily_logs"):
        d = lg["date"]
        if (date_from and d < str(date_from)) or (date_to and d > str(date_to)):
            continue
        day = logs.setdefault(d, {"workers": 0, "hours": 0, "others": {}})
        for m in lg["manpower"]:
            n = int(m["workers"])
            h = cents.hours(cents.D(m["hours"]) * n)
            if _own(office, m["company"]):
                day["workers"] += n
                day["hours"] += h
            else:
                o = day["others"].setdefault(m["company"],
                                             {"workers": 0, "hours": 0})
                o["workers"] += n
                o["hours"] += h
    approved = {}
    for ln in timeentry.approved_lines(office, job_id, date_from, date_to):
        if ln["pay_type"] in ("REG", "OT", "DT"):
            approved[ln["date"]] = approved.get(ln["date"], 0) + ln["hours"]
    out = []
    for d in sorted(set(logs) | set(approved)):
        lg = logs.get(d)
        ah = approved.get(d, 0)
        row = {"date": d, "log_workers": lg["workers"] if lg else None,
               "log_hours": lg["hours"] if lg else None,
               "approved_hours": ah,
               "others": [{"company": k, **v} for k, v in
                          sorted((lg or {"others": {}})["others"].items())]}
        if lg is None:
            row["difference"], row["flag"] = None, "no daily log"
        else:
            diff = lg["hours"] - ah
            row["difference"] = diff
            row["flag"] = f"{cents.hours_text(abs(diff))} h difference" \
                if diff else ""
        out.append(row)
    return out


def production(office, job_id) -> dict:
    """{(code, unit): Decimal quantity} from the time cards."""
    out = {}
    for tc in jobs.section(office, job_id, "timecards"):
        for p in tc.get("production") or []:
            if not p.get("cost_code") or not cents.D(p["qty"]):
                continue
            k = (p["cost_code"], p.get("unit") or "")
            out[k] = out.get(k, Decimal(0)) + cents.D(p["qty"])
    return out


def unit_costs(office, job_id) -> list[dict]:
    costs = jobcost.by_code(office, job_id)
    out = []
    for (code, unit), qty in sorted(production(office, job_id).items()):
        actual = costs.get(code, {}).get("actual", 0)
        per = int(cents.round_half_up(Decimal(actual) / qty)) if qty else 0
        out.append({"code": code, "unit": unit,
                    "qty": str(int(qty)) if qty == qty.to_integral_value()
                    else str(qty.normalize()), "actual": actual,
                    "unit_cost": per,
                    "text": f"{cents.fmt(per)} per {unit or 'unit'}"})
    return out
