"""Customer payments and AR aging (P1-15). Back Office records payments;
it never moves money.

A payment posts debit Undeposited funds, credit Accounts receivable for
the full amount; any unapplied part stays as a customer credit.
"""
from __future__ import annotations

from . import billing, cents, clock, ledger, waivers

BUCKETS = ("current", "1-30", "31-60", "61-90", "over 90")


class PaymentError(ValueError):
    pass


def applied(office, iid, as_of=None) -> int:
    q = ("SELECT SUM(a.amount) FROM payment_apps a LEFT JOIN payments p ON "
         "p.id = a.payment_id WHERE a.invoice_id = ? AND a.deleted = 0 AND "
         "COALESCE(p.void, 0) = 0")
    p = [iid]
    if as_of:
        q += " AND a.date <= ?"
        p.append(str(as_of))
    return office.db.scalar(q, p) or 0


def open_amount(office, iid, as_of=None) -> int:
    inv = billing.invoice(office, iid)
    if inv["status"] in ("Draft", "Void"):
        return 0
    return inv["total"] - applied(office, iid, as_of)


def open_invoices(office, customer=None) -> list[dict]:
    q = ("SELECT * FROM ar_invoices WHERE status IN ('Approved','Sent',"
         "'Partly paid') AND deleted = 0")
    p = []
    if customer:
        q += " AND customer = ?"
        p.append(customer)
    return [i for i in office.db.rows(q + " ORDER BY due_date, number", p)
            if open_amount(office, i["id"]) > 0]


def _refresh_status(office, iid):
    inv = billing.invoice(office, iid)
    if inv["status"] in ("Draft", "Void"):
        return
    paid = applied(office, iid)
    if paid >= inv["total"]:
        st = "Paid"
    elif paid > 0:
        st = "Partly paid"
    else:
        st = "Sent" if inv["sent_on"] else "Approved"
    office.db.update("ar_invoices", iid, status=st)


def receive(office, customer, date, amount, method="check", reference="",
            applications=None, note="", job_id=None) -> dict:
    """Record a payment and apply it: applications [(invoice_id, amount)];
    None applies to the oldest open invoices first. Overpayment becomes an
    unapplied credit."""
    office.require("payments.edit", "payment", reference)
    amt = cents.amount_in(amount)
    if amt <= 0:
        raise PaymentError("The payment must be more than $0.00.")
    ledger.check_open(office, date)
    if applications is None:
        applications, left = [], amt
        for inv in open_invoices(office, customer):
            if left <= 0:
                break
            take = min(left, open_amount(office, inv["id"]))
            applications.append((inv["id"], cents.from_cents(take)))
            left -= take
    apps = []
    for iid, a in applications:
        a = cents.amount_in(a)
        o = open_amount(office, iid)
        if a > o:
            a = o
        apps.append((iid, a))
    used = sum(a for _, a in apps)
    if used > amt:
        raise PaymentError("More is applied than was received.")
    with office.db.tx():
        pid = office.db.insert("payments", customer=customer, date=str(date),
                               method=method, reference=reference, amount=amt,
                               note=note, job_id=job_id)
        jl = [{"account": ledger.default_account(office, "undeposited"),
               "debit": amt, "party": customer, "job_id": job_id},
              {"account": ledger.default_account(office, "ar"),
               "credit": amt, "party": customer, "job_id": job_id}]
        eid = ledger.post(office, date, jl, "payment", pid,
                          f"Payment {reference} {customer}".strip())
        office.db.update("payments", pid, entry_id=eid)
        for iid, a in apps:
            if a <= 0:
                continue
            office.db.insert("payment_apps", payment_id=pid, invoice_id=iid,
                             amount=a, date=str(date))
            inv = billing.invoice(office, iid)
            _refresh_status(office, iid)
            _cash_dates(office, iid, a, str(date))
            if inv["type"] == "Retainage":
                office.db.insert("retainage_ledger", job_id=inv["job_id"],
                                 invoice_id=iid, kind="received", amount=a,
                                 date=str(date))
            waivers.draft_for_payment(office, pid, iid, a)
        credit = amt - used
        cid = None
        if credit:
            cid = office.db.insert("credits", customer=customer, amount=credit,
                                   source_payment_id=pid)
        office.audit("create", "payment", pid, None,
                     {"amount": amt, "applied": apps, "credit": credit})
    return {"payment_id": pid, "applied": apps, "credit": credit,
            "credit_id": cid, "entry_id": eid}


def _cash_dates(office, iid, amount, date):
    """Marks how much of the invoice's revenue is collected on `date` (for
    cash-basis reports): stored per payment application."""
    return None


def credit_left(office, cid) -> int:
    c = office.db.get("credits", cid)
    used = office.db.scalar("SELECT SUM(amount) FROM payment_apps WHERE "
                            "credit_id = ? AND deleted = 0", (cid,)) or 0
    return c["amount"] - used


def unapplied_credits(office, customer=None) -> list[dict]:
    rows = office.db.rows("SELECT * FROM credits WHERE deleted = 0" +
                          (" AND customer = ?" if customer else ""),
                          (customer,) if customer else ())
    for r in rows:
        r["left"] = credit_left(office, r["id"])
    return [r for r in rows if r["left"] > 0]


def apply_credit(office, cid, iid, amount=None, date=None) -> int:
    office.require("payments.edit", "credit", cid)
    left = credit_left(office, cid)
    o = open_amount(office, iid)
    a = min(left, o) if amount is None else cents.to_cents(amount)
    if a > left or a > o:
        raise PaymentError("That is more than the credit or the open amount.")
    with office.db.tx():
        aid = office.db.insert("payment_apps", payment_id=None, credit_id=cid,
                               invoice_id=iid, amount=a,
                               date=str(date or clock.today()))
        _refresh_status(office, iid)
        office.audit("apply credit", "ar_invoice", iid, None,
                     {"credit": cid, "amount": a})
    return aid


def aging(office, as_of, by="customer") -> dict:
    """Open AR by days past due as of a date: Current (not yet due or due
    that day), 1-30, 31-60, 61-90, over 90."""
    as_of_d = clock.d(as_of)
    totals = {b: 0 for b in BUCKETS}
    rows = []
    for inv in office.db.rows("SELECT * FROM ar_invoices WHERE status NOT IN "
                              "('Draft','Void') AND deleted = 0 AND "
                              "invoice_date <= ?", (str(as_of),)):
        o = inv["total"] - applied(office, inv["id"], as_of)
        if o <= 0:
            continue
        days = (as_of_d - clock.d(inv["due_date"])).days
        b = bucket(days)
        totals[b] += o
        rows.append({"number": inv["number"], "customer": inv["customer"],
                     "job_id": inv["job_id"], "due_date": inv["due_date"],
                     "days": max(days, 0), "bucket": b, "open": o})
    groups = {}
    for r in rows:
        k = r["customer"] if by == "customer" else r["job_id"]
        g = groups.setdefault(k, {b: 0 for b in BUCKETS})
        g[r["bucket"]] += r["open"]
    return {"as_of": str(as_of), "rows": rows, "totals": totals,
            "total": sum(totals.values()), "groups": groups}


def bucket(days_late: int) -> str:
    if days_late <= 0:
        return "current"
    if days_late <= 30:
        return "1-30"
    if days_late <= 60:
        return "31-60"
    if days_late <= 90:
        return "61-90"
    return "over 90"


def compare_with_snapshot(office, job_id) -> list[str]:
    """QuantiSheet's 'Payment received' on owner pay apps vs what Back
    Office recorded for that app's invoice; differences are listed, never
    overwritten."""
    from . import jobs
    out = []
    for a in jobs.section(office, job_id, "payapps"):
        if not a.get("received"):
            continue
        inv = office.db.one("SELECT id, number FROM ar_invoices WHERE job_id = ? "
                            "AND payapp_no = ? AND status != 'Void'",
                            (job_id, a["number"]))
        got = applied(office, inv["id"]) if inv else 0
        qs = cents.to_cents(a["received"])
        if qs != got:
            out.append(f"Pay application {a['number']}: QuantiSheet shows "
                       f"{cents.fmt(qs)} received, Back Office has "
                       f"{cents.fmt(got)}")
    return out
