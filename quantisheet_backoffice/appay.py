"""Bill payments and AP aging (P1-20). Recorded only: Back Office never
moves money or writes bank payment files.

A bill payment posts debit Accounts payable (or Retainage payable),
credit the bank account. Compliance holds (P1-09) and the final-payment
waiver check (P1-14) still block payment.
"""
from __future__ import annotations

from . import ap, cents, clock, ledger, waivers
from .payments import BUCKETS, bucket


class PayError(ValueError):
    pass


def paid(office, iid, kind="bill", as_of=None) -> int:
    q = ("SELECT SUM(a.amount) FROM bill_payment_apps a JOIN bill_payments p "
         "ON p.id = a.payment_id WHERE a.invoice_id = ? AND a.kind = ? AND "
         "p.void = 0 AND a.deleted = 0")
    prm = [iid, kind]
    if as_of:
        q += " AND p.date <= ?"
        prm.append(str(as_of))
    return office.db.scalar(q, prm) or 0


def open_bill(office, iid, as_of=None) -> int:
    inv = ap.invoice(office, iid)
    if inv["status"] not in ap.OPEN_FOR_PAYMENT + ("Paid",):
        return 0
    return inv["total"] - (inv["retainage"] or 0) - paid(office, iid, "bill",
                                                         as_of)


def open_retainage(office, iid) -> int:
    inv = ap.invoice(office, iid)
    if inv["status"] not in ap.OPEN_FOR_PAYMENT + ("Paid",):
        return 0
    return (inv["retainage"] or 0) - paid(office, iid, "retainage")


def _refresh(office, iid):
    inv = ap.invoice(office, iid)
    if open_bill(office, iid) <= 0 and open_retainage(office, iid) <= 0:
        st = "Paid"
    elif paid(office, iid) or paid(office, iid, "retainage"):
        st = "Partly paid" if open_bill(office, iid) > 0 else "Paid"
    else:
        st = "Exported" if inv["exported_batch"] else "Approved"
    office.db.update("ap_invoices", iid, status=st)


def pay(office, vendor_id, date, applications, method="check", reference="",
        bank_number="1000", final=False, override_reason="", note="") -> int:
    """applications: [(ap_invoice_id, amount, 'bill'|'retainage')]."""
    office.require("billpay.edit", "bill_payment", reference)
    ledger.check_open(office, date)
    apps = []
    for item in applications:
        iid, amt = item[0], item[1]
        kind = item[2] if len(item) > 2 else "bill"
        amt = cents.amount_in(amt)
        inv = ap.invoice(office, iid)
        if inv["vendor_id"] != vendor_id:
            raise PayError(f"{inv['number']} is not this vendor's bill.")
        holds = ap.open_holds(office, iid)
        if holds:
            raise PayError(f"{inv['number']} has a compliance hold: " +
                           "; ".join(h["reason"] for h in holds))
        left = open_bill(office, iid) if kind == "bill" else \
            open_retainage(office, iid)
        if amt > left:
            raise PayError(f"{inv['number']}: {cents.fmt(amt)} is more than the "
                           f"open {cents.fmt(left)}.")
        apps.append((iid, amt, kind, inv))
        if kind == "retainage" and amt == left:
            final = True
        if inv["final"]:
            final = True
    if final:
        v = ap.vendor(office, vendor_id)
        jobs_ = {a[3]["job_id"] for a in apps}
        missing = [j for j in jobs_ if not waivers.has_received(
            office, vendor_id, j, "unconditional_final")]
        if missing:
            if office.role not in ("Controller", "Admin") or \
                    not (override_reason or "").strip():
                office.audit("denied", "bill_payment", "", None,
                             {"reason": "final waiver missing",
                              "vendor": v["name"]})
                raise PayError(f"Final payment to {v['name']} is blocked until "
                               f"an unconditional final waiver is marked "
                               f"Received (or a Controller overrides with a "
                               f"reason).")
    total = sum(a[1] for a in apps)
    bank = ledger.account_by_number(office, bank_number)
    with office.db.tx():
        pid = office.db.insert("bill_payments", vendor_id=vendor_id,
                               date=str(date), method=method,
                               reference=reference, amount=total,
                               bank_account_id=bank["id"], note=note,
                               final=int(bool(final)),
                               override_reason=override_reason or None)
        v = ap.vendor(office, vendor_id)
        jl = []
        for iid, amt, kind, inv in apps:
            office.db.insert("bill_payment_apps", payment_id=pid,
                             invoice_id=iid, kind=kind, amount=amt)
            jl.append({"account": ledger.default_account(
                office, "ap" if kind == "bill" else "ap_retainage"),
                "debit": amt, "party": v["name"], "job_id": inv["job_id"]})
        jl.append({"account": bank["id"], "credit": total, "party": v["name"],
                   "memo": f"{method} {reference}".strip()})
        eid = ledger.post(office, date, jl, "bill_payment", pid,
                          f"Bill payment {reference} {v['name']}".strip())
        office.db.update("bill_payments", pid, entry_id=eid)
        for iid, *_ in apps:
            _refresh(office, iid)
        office.audit("create", "bill_payment", pid, None,
                     {"total": total, "apps": [(a[0], a[1], a[2]) for a in apps],
                      "final": bool(final), "override": override_reason})
    return pid


def aging(office, as_of) -> dict:
    as_of_d = clock.d(as_of)
    totals = {b: 0 for b in BUCKETS}
    rows = []
    for inv in office.db.rows("SELECT * FROM ap_invoices WHERE status IN "
                              "('Approved','Exported','Partly paid','Paid') "
                              "AND deleted = 0 AND invoice_date <= ?",
                              (str(as_of),)):
        o = inv["total"] - (inv["retainage"] or 0) - \
            paid(office, inv["id"], "bill", as_of)
        if o <= 0:
            continue
        days = (as_of_d - clock.d(inv["due_date"])).days
        b = bucket(days)
        totals[b] += o
        rows.append({"number": inv["number"], "vendor_id": inv["vendor_id"],
                     "job_id": inv["job_id"], "due_date": inv["due_date"],
                     "days": max(days, 0), "bucket": b, "open": o})
    return {"as_of": str(as_of), "rows": rows, "totals": totals,
            "total": sum(totals.values())}


def cash_requirements(office, through) -> list[dict]:
    out = []
    for inv in office.db.rows("SELECT * FROM ap_invoices WHERE status IN "
                              "('Approved','Exported','Partly paid') AND "
                              "deleted = 0 AND due_date <= ? ORDER BY due_date",
                              (str(through),)):
        o = open_bill(office, inv["id"])
        if o > 0:
            out.append({"number": inv["number"], "due_date": inv["due_date"],
                        "open": o})
    run = 0
    for r in out:
        run += r["open"]
        r["running"] = run
    return out


def retainage_payable(office) -> list[dict]:
    out = {}
    for inv in office.db.rows("SELECT * FROM ap_invoices WHERE retainage > 0 "
                              "AND status IN ('Approved','Exported',"
                              "'Partly paid','Paid') AND deleted = 0"):
        k = (inv["job_id"], inv["commitment_no"] or "", inv["vendor_id"])
        r = out.setdefault(k, {"job_id": k[0], "commitment_no": k[1],
                               "vendor_id": k[2], "held": 0, "paid": 0})
        r["held"] += inv["retainage"]
        r["paid"] += paid(office, inv["id"], "retainage")
    for r in out.values():
        r["open"] = r["held"] - r["paid"]
    return list(out.values())
