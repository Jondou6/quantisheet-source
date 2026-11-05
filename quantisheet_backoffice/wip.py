"""Work-in-progress and over/under billing report (P3-04).

Per job, as of a date:
  contract        contract amount to date (original + executed change orders,
                  from the QuantiSheet snapshot)
  estimated cost  the user's override for the job (set_estimate) or else the
                  job cost forecast at completion AS OF the report date
                  (budget/commitments vs actuals through that date, the
                  same figure as the Job Cost page run to that date)
  cost to date    job cost actuals through the date
  % complete      cost to date / estimated cost (capped at 100%); a job
                  with cost but no estimate is flagged 'estimate needed'
                  and shows 'n/a', never 0%
  earned          contract x % complete
  billed          progress, T&M and other invoices issued through the date,
                  gross of retainage (retainage releases are not new billing)
  over/under      billed - earned (positive = over-billed)
Money is int cents; the earned split is rounded half up once.
"""
from __future__ import annotations

import os
from decimal import ROUND_HALF_UP, Decimal

from . import billing, cents, clock, fileguard, jobcost, jobs

HEADERS = ["Job", "Name", "Contract", "Estimated cost", "Cost to date",
           "% complete", "Earned", "Billed to date", "Over (under) billed",
           "Estimate from"]


def set_estimate(office, job_id, amount, note="") -> None:
    """Override a job's estimated cost at completion ('' clears it)."""
    office.require("settings.edit", "wip_estimate", job_id)
    cur = office.db.one("SELECT * FROM wip_estimates WHERE job_id = ? AND "
                        "deleted = 0", (job_id,))
    with office.db.tx():
        if amount in ("", None):
            if cur:
                office.db.update("wip_estimates", cur["id"], deleted=1)
            office.audit("change", "wip_estimate", job_id,
                         {"amount": cur["amount"] if cur else None},
                         {"amount": None})
            return
        a = cents.amount_in(amount)
        if cur:
            office.db.update("wip_estimates", cur["id"], amount=a, note=note)
        else:
            office.db.insert("wip_estimates", job_id=job_id, amount=a,
                             note=note)
        office.audit("change", "wip_estimate", job_id,
                     {"amount": cur["amount"] if cur else None},
                     {"amount": a, "note": note})


def _billed(office, job_id, as_of) -> int:
    r = office.db.one(
        "SELECT COALESCE(SUM(amount + COALESCE(retainage, 0)), 0) AS b FROM "
        "ar_invoices WHERE job_id = ? AND deleted = 0 AND type != "
        "'Retainage' AND status NOT IN ('Draft','Void') AND invoice_date <= ?",
        (job_id, str(as_of)))
    return int(r["b"] or 0)


def job_row(office, job_id, as_of) -> dict | None:
    j = jobs.job(office, job_id)
    cs = billing.contract_summary(office, job_id)
    contract = cs["contract_sum_to_date"]
    if not contract:
        return None
    rows = jobcost.job_cost(office, job_id, date_to=str(as_of))
    cost = sum(r["actual"] for r in rows)
    ov = office.db.one("SELECT amount FROM wip_estimates WHERE job_id = ? "
                       "AND deleted = 0", (job_id,))
    if ov:
        est, source = ov["amount"], "your estimate"
    else:
        est = sum(r["forecast"] for r in rows)
        source = "job cost forecast"
    needed = est <= 0 and cost > 0
    if needed:
        source = "estimate needed"
    ratio = min(Decimal(cost) / Decimal(est), Decimal(1)) if est > 0 else \
        Decimal(0)
    earned = int((Decimal(contract) * ratio).quantize(
        Decimal(1), rounding=ROUND_HALF_UP))
    billed = _billed(office, job_id, as_of)
    return {"job_id": job_id, "number": j["number"], "name": j["name"],
            "contract": contract, "estimated_cost": est, "cost_to_date": cost,
            "pct_complete": "n/a" if needed else str((ratio * 100).quantize(
                Decimal("0.1"), rounding=ROUND_HALF_UP)),
            "estimate_needed": needed,
            "earned": earned, "billed": billed,
            "over_under": billed - earned, "estimate_source": source,
            "cost_over_estimate": est > 0 and cost > est}


def wip(office, as_of=None, job_ids=None) -> list[dict]:
    as_of = str(as_of or clock.today())
    ids = job_ids or [j["id"] for j in jobs.jobs(office)]
    return [r for r in (job_row(office, i, as_of) for i in ids) if r]


def totals(rows) -> dict:
    keys = ("contract", "estimated_cost", "cost_to_date", "earned", "billed",
            "over_under")
    return {k: sum(r[k] for r in rows) for k in keys}


def _cells(r):
    return [r["number"], r["name"], cents.text(r["contract"]),
            cents.text(r["estimated_cost"]), cents.text(r["cost_to_date"]),
            r["pct_complete"], cents.text(r["earned"]), cents.text(r["billed"]),
            cents.text(r["over_under"]), r["estimate_source"]]


def _target(office, path, as_of, ext):
    if path:
        return fileguard.write_target(path)
    folder = os.path.join(office.output_folder(), "reports")
    os.makedirs(folder, exist_ok=True)
    return fileguard.safe_path(folder, f"WIP {as_of}.{ext}")


def to_xlsx(office, as_of=None, path=None) -> str:
    from openpyxl import Workbook
    as_of = str(as_of or clock.today())
    rows = wip(office, as_of)
    path = _target(office, path, as_of, "xlsx")
    wb = Workbook()
    ws = wb.active
    ws.title = "WIP"
    ws.append(fileguard.safe_row([f"Work in progress as of {as_of}"]))
    ws.append(fileguard.safe_row(HEADERS))
    for r in rows:
        c = _cells(r)
        ws.append(fileguard.safe_row(c[:2]) + [Decimal(x) for x in c[2:5]] +
                  [Decimal(c[5]) / 100 if c[5] != "n/a" else "n/a"] +
                  [Decimal(x) for x in c[6:9]] +
                  fileguard.safe_row([c[9]]))
    t = totals(rows)
    ws.append(["Total", ""] + [Decimal(cents.text(t[k])) for k in
                               ("contract", "estimated_cost",
                                "cost_to_date")] + [None] +
              [Decimal(cents.text(t[k])) for k in ("earned", "billed",
                                                    "over_under")])
    for row in ws.iter_rows(min_row=3):
        for cell in row[2:9]:
            cell.number_format = "0.0%" if cell.column == 6 else "#,##0.00"
    wb.save(path)
    office.audit("export", "wip", as_of, None, {"path": path})
    return path


def to_pdf(office, as_of=None, path=None) -> str:
    import fitz
    from .output import _Pg
    as_of = str(as_of or clock.today())
    rows = wip(office, as_of)
    path = _target(office, path, as_of, "pdf")
    doc = fitz.open()
    pg = _Pg(doc)
    c = office.company()
    pg.t(54, 54, c.get("name") or "", 13, True)
    pg.t(54, 80, f"Work in progress as of {as_of}", 14, True)
    cols = [(40, None, "Job"), (78, None, "Name"), (0, 248, "Contract"),
            (0, 304, "Est. cost"), (0, 360, "Cost to date"),
            (0, 398, "% complete"), (0, 454, "Earned"), (0, 512, "Billed"),
            (0, 572, "Over (under)")]
    y = 110
    for x, right, h in cols:
        pg.t(x, y, h, 8, True, right=right)
    pg.line(y + 4)
    y += 16
    for r in rows + ([dict(totals(rows), number="Total", name="",
                           pct_complete="")] if rows else []):
        pct = r["pct_complete"]
        vals = [r["number"], (r["name"] or "")[:24], cents.fmt(r["contract"]),
                cents.fmt(r["estimated_cost"]), cents.fmt(r["cost_to_date"]),
                (pct + "%") if pct not in ("", "n/a") else pct,
                cents.fmt(r["earned"]), cents.fmt(r["billed"]),
                cents.fmt(r["over_under"])]
        for (x, right, _), v in zip(cols, vals):
            pg.t(x, y, v, 7, r["number"] == "Total", right=right)
        y += 13
        if y > 740:
            pg = _Pg(doc)
            y = 60
    flagged = [r["number"] for r in rows if r.get("estimate_needed")]
    if flagged:
        pg.t(40, y + 8, "Estimate needed (cost but no estimate): " +
             ", ".join(flagged), 7, True)
    pg.t(40, max(y + 24, 700), "Billed to date is gross of retainage; "
         "percent complete is cost to date / estimated cost.", 7)
    doc.save(path)
    doc.close()
    office.audit("export", "wip", as_of, None, {"path": path})
    return path
