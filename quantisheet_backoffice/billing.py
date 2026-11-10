"""AR: billing contracts, SOV and change orders (P1-10), progress invoices
from certified pay applications (P1-11), retainage (P1-12), T&M and other
invoices (P1-13), and their journal postings (P1-19).

The SOV, change orders and pay-app numbers belong to QuantiSheet
(decision 3 = A): Back Office shows them read-only and invoices the
certified numbers; it never recomputes a certified application.
"""
from __future__ import annotations

import json
from datetime import timedelta

from . import cents, clock, interface, jobs, ledger, tax, timeentry

EDIT_IN_QS = "edit in QuantiSheet > Billing"
TYPES = ("Progress", "T&M", "Retainage", "Other")
OPEN = ("Approved", "Sent", "Partly paid")


class BillingError(ValueError):
    pass


# ---- contracts (P1-10) ---------------------------------------------------

def set_contract(office, job_id, owner="", bill_to="", contact_email="",
                 terms=None, retainage_work=None, retainage_stored=None,
                 release_rule="", tax_code_id=None, material_markup="0",
                 sub_markup="0", tax_flags=None) -> int:
    office.require("ar.edit", "billing_contract", job_id)
    j = jobs.job(office, job_id)
    proj = json.loads(j["project"] or "{}")
    fields = dict(owner=owner or proj.get("owner", ""), bill_to=bill_to,
                  contact_email=contact_email,
                  terms=terms if terms is not None else
                  office.company()["net_terms"],
                  retainage_work=str(retainage_work or j["retainage_work"] or "0"),
                  retainage_stored=str(retainage_stored or
                                       j["retainage_stored"] or "0"),
                  release_rule=release_rule, tax_code_id=tax_code_id,
                  material_markup=str(cents.D(material_markup)),
                  sub_markup=str(cents.D(sub_markup)),
                  tax_flags=tax_flags or {})
    with office.db.tx():
        c = contract_for(office, job_id)
        if c:
            office.db.update("billing_contracts", c["id"], **fields)
            cid = c["id"]
        else:
            cid = office.db.insert("billing_contracts", job_id=job_id, **fields)
        office.audit("change" if c else "create", "billing_contract", cid,
                     None, {k: v for k, v in fields.items()})
    return cid


def contract_for(office, job_id) -> dict | None:
    return office.db.one("SELECT * FROM billing_contracts WHERE job_id = ? "
                         "AND deleted = 0", (job_id,))


def set_rate(office, job_id, kind, code, regular="0", overtime="0",
             double="0", rate="0") -> int:
    office.require("ar.edit", "billing_rate", code)
    c = contract_for(office, job_id) or {"id": set_contract(office, job_id)}
    with office.db.tx():
        rid = office.db.insert("billing_rates", contract_id=c["id"], kind=kind,
                               code=code, regular=cents.to_cents(regular),
                               overtime=cents.to_cents(overtime),
                               double=cents.to_cents(double),
                               rate=cents.to_cents(rate))
        office.audit("create", "billing_rate", rid, None,
                     {"kind": kind, "code": code})
    return rid


def _rate(office, contract_id, kind, code) -> dict | None:
    return office.db.one("SELECT * FROM billing_rates WHERE contract_id = ? AND "
                         "kind = ? AND code = ? AND deleted = 0 "
                         "ORDER BY id DESC", (contract_id, kind, code))


def _payapps(office, job_id) -> list[dict]:
    return sorted(jobs.section(office, job_id, "payapps"),
                  key=lambda a: a["number"])


def _invoiced_app_numbers(office, job_id) -> set[int]:
    return {r["payapp_no"] for r in office.db.rows(
        "SELECT payapp_no FROM ar_invoices WHERE job_id = ? AND type = "
        "'Progress' AND status != 'Void' AND deleted = 0", (job_id,))}


def retainage_outstanding(office, job_id) -> dict:
    rows = office.db.rows("SELECT kind, SUM(amount) AS s FROM retainage_ledger "
                          "WHERE job_id = ? AND deleted = 0 GROUP BY kind",
                          (job_id,))
    k = {r["kind"]: r["s"] or 0 for r in rows}
    held, rel, rec = k.get("held", 0), k.get("released", 0), k.get("received", 0)
    return {"held": held, "released": rel, "received": rec,
            "outstanding": held - rel, "released_unpaid": rel - rec}


CERTIFIED = ("certified", "paid")


def change_amount(c) -> int:
    """A change's amount: an executed CO its approved amount, a pending
    PCO / COR its requested amount (PM review NW-10: a pending PCO was
    listed at its blank approved amount, $0.00)."""
    if c.get("stage") == "co":
        return cents.to_cents(c.get("approved_amount") or c.get("amount")
                              or "0")
    return cents.to_cents(c.get("amount") or "0")


def latest_certified(office, job_id):
    """The newest certified (or paid) pay application from QuantiSheet,
    or None."""
    apps = [a for a in _payapps(office, job_id)
            if str(a.get("status") or "").lower() in CERTIFIED]
    return apps[-1] if apps else None


def contract_summary(office, job_id) -> dict:
    """Billed to date and retainage held come from the newest CERTIFIED
    pay application (its G702 lines 4 and 5) - what the owner has agreed
    - whether or not AR invoices have been made yet (PM review NW-10:
    'Retainage held $0.00' with $119,385 held on the certified apps).
    Without a certified app, from AR as before."""
    sov = jobs.section(office, job_id, "sov")
    chg = jobs.section(office, job_id, "changes")
    orig = interface.original_contract(sov)
    co = interface.executed_changes(chg)
    billed = 0
    inv_apps = _invoiced_app_numbers(office, job_id)
    for a in _payapps(office, job_id):
        if a["number"] in inv_apps:
            billed = cents.to_cents(a["summary"]["4"])
    ret = retainage_outstanding(office, job_id)
    held = ret["outstanding"]
    cert = latest_certified(office, job_id)
    if cert is not None:
        s = cert.get("summary") or {}
        billed = max(billed, cents.to_cents(s.get("4") or "0"))
        held = max(0, cents.to_cents(s.get("5") or "0") - ret["released"])
    return {"original": orig, "executed_changes": co,
            "contract_sum_to_date": orig + co,
            "pending_changes": interface.pending_changes(chg),
            "billed_to_date": billed, "retainage_held": held,
            "balance_to_finish": orig + co - billed,
            "note": EDIT_IN_QS}


def sov_view(office, job_id) -> list[dict]:
    """Original SOV lines plus executed change orders as their own lines,
    each marked billed / not yet billed (read-only copies)."""
    inv_apps = _invoiced_app_numbers(office, job_id)
    billed = {}
    for a in _payapps(office, job_id):
        if a["number"] not in inv_apps:
            continue
        for ln in a["lines"]:
            amt = sum(cents.to_cents(ln[k]) for k in
                      ("previous", "this_period", "stored"))
            billed[ln["item"]] = max(billed.get(ln["item"], 0), amt)
    out = []
    for s in jobs.section(office, job_id, "sov"):
        out.append({"item": s["item"], "cost_code": s["cost_code"],
                    "description": s["description"],
                    "scheduled": cents.to_cents(s["scheduled"]),
                    "billed": billed.get(s["item"], 0), "is_change": False,
                    "status": "billed" if billed.get(s["item"]) else
                    "not yet billed", "read_only": True})
    for c in jobs.section(office, job_id, "changes"):
        if c["stage"] != "co":
            continue
        item = c["co"] or c["id"]
        out.append({"item": item, "cost_code": "", "description": c["title"],
                    "scheduled": cents.to_cents(c["approved_amount"]),
                    "billed": billed.get(item, 0), "is_change": True,
                    "status": "billed" if billed.get(item) else
                    "not yet billed", "read_only": True,
                    "executed": c["executed"]})
    return out


def changes_view(office, job_id) -> dict:
    out = {"executed": [], "pending": [], "rejected": []}
    for c in jobs.section(office, job_id, "changes"):
        k = "executed" if c["stage"] == "co" else \
            "pending" if c["stage"] in ("pco", "cor") else "rejected"
        out[k].append(c)
    return out


# ---- AR invoices ---------------------------------------------------------

def _due(office, job_id, invoice_date, terms=None) -> str:
    c = contract_for(office, job_id) if job_id else None
    t = terms if terms is not None else \
        (c["terms"] if c else office.company()["net_terms"]) or 30
    return (clock.d(invoice_date) + timedelta(days=t)).isoformat()


def _new_invoice(office, job_id, type_, invoice_date, amount, number=None,
                 due_date=None, **fields) -> int:
    fmt = {"Retainage": ("RET", "RET-{n:04d}", 1)}.get(
        type_, ("INV", office.company()["invoice_format"] or "INV-{n:04d}",
                1001))
    number = number or office.db.next_number(fmt[0], fmt[1], fmt[2])
    if office.db.one("SELECT id FROM ar_invoices WHERE number = ?", (number,)):
        raise BillingError(f"invoice number {number} is already used")
    c = contract_for(office, job_id) if job_id else None
    customer = fields.pop("customer", None) or (c["owner"] if c else "")
    iid = office.db.insert(
        "ar_invoices", number=number, job_id=job_id,
        contract_id=c["id"] if c else None, customer=customer, type=type_,
        invoice_date=str(invoice_date),
        due_date=str(due_date or _due(office, job_id, invoice_date)),
        gl_date=str(fields.pop("gl_date", None) or invoice_date),
        amount=amount, status="Draft", **fields)
    return iid


def invoice(office, iid) -> dict:
    return office.db.get("ar_invoices", iid)


def invoice_by_number(office, number) -> dict | None:
    return office.db.one("SELECT * FROM ar_invoices WHERE number = ?", (number,))


def lines(office, iid) -> list[dict]:
    return office.db.rows("SELECT * FROM ar_lines WHERE invoice_id = ? AND "
                          "deleted = 0 ORDER BY line_no", (iid,))


def payapp(office, job_id, number) -> dict:
    a = jobs.record(office, job_id, "payapps", str(number))
    if a is None:
        raise BillingError(f"no pay application {number} in the last import")
    return a


def payapp_status(office, job_id, a) -> str:
    inv = office.db.one("SELECT * FROM ar_invoices WHERE job_id = ? AND type = "
                        "'Progress' AND payapp_no = ? AND status != 'Void'",
                        (job_id, a["number"]))
    if a["status"] not in interface.COUNTED:
        return "Draft in QuantiSheet"
    if inv is None:
        return "Certified"
    return {"Partly paid": "Partly paid", "Paid": "Paid"}.get(inv["status"],
                                                              "Invoiced")


def previous_retainage(office, job_id, number) -> int:
    prev = [a for a in _payapps(office, job_id)
            if a["number"] < number and a["status"] in interface.COUNTED]
    return cents.to_cents(prev[-1]["summary"]["5"]) if prev else 0


def invoice_from_payapp(office, job_id, number, invoice_date=None,
                        number_override=None) -> int:
    """One AR invoice from a certified pay application: amount due = its
    current payment due (line 8), retainage this period = retainage to date
    less the previous application's. Numbers are taken as certified."""
    office.require("ar.edit", "ar_invoice", f"payapp {number}")
    a = payapp(office, job_id, number)
    if a["status"] not in interface.COUNTED:
        raise BillingError(f"Pay application {number} is still Draft: "
                           f"certify it in QuantiSheet first.")
    if number in _invoiced_app_numbers(office, job_id):
        raise BillingError(f"Pay application {number} is already invoiced.")
    s = a["summary"]
    due = cents.to_cents(s["8"])
    ret_this = cents.to_cents(s["5"]) - previous_retainage(office, job_id,
                                                           number)
    d = invoice_date or a["period_to"]
    with office.db.tx():
        iid = _new_invoice(office, job_id, "Progress", d, due,
                           number=number_override, period_to=a["period_to"],
                           retainage=ret_this, tax=0, total=due,
                           payapp_no=number)
        office.db.insert("ar_lines", invoice_id=iid, line_no=1,
                         description=f"Progress billing, pay application "
                                     f"{number}, period to {a['period_to']}",
                         kind="progress", amount=due)
        office.audit("create", "ar_invoice", iid, None,
                     {"payapp": number, "amount": due,
                      "retainage_this_period": ret_this})
    return iid


def payapp_numbers(office, iid) -> dict:
    """The nine summary lines exactly as certified, for printing."""
    inv = invoice(office, iid)
    a = payapp(office, inv["job_id"], inv["payapp_no"])
    return {k: cents.to_cents(v) for k, v in a["summary"].items()}


def create_other_invoice(office, job_id, invoice_date, lines_, customer="",
                         due_date=None, number=None, type_="Other",
                         tax_code_id=None, note="") -> int:
    office.require("ar.edit", "ar_invoice", "other")
    ls = []
    for ln in lines_:
        a = ln["amount"]
        a = cents.amount_in(a)
        ls.append({**ln, "amount": a})
    amount = sum(ln["amount"] for ln in ls)
    tax_c = 0
    if tax_code_id:
        tax_c = tax.tax_on(office, tax_code_id,
                           sum(ln["amount"] for ln in ls if ln.get("taxable")),
                           invoice_date)
    with office.db.tx():
        iid = _new_invoice(office, job_id, type_, invoice_date, amount,
                           number=number, due_date=due_date, customer=customer,
                           tax=tax_c, total=amount + tax_c, retainage=0,
                           tax_code_id=tax_code_id, note=note)
        for n, ln in enumerate(ls, start=1):
            office.db.insert("ar_lines", invoice_id=iid, line_no=n,
                             description=ln.get("description", ""),
                             cost_code=ln.get("cost_code", ""),
                             kind=ln.get("kind", "other"),
                             amount=ln["amount"],
                             taxable=int(bool(ln.get("taxable"))))
        office.audit("create", "ar_invoice", iid, None,
                     {"type": type_, "amount": amount, "tax": tax_c})
    return iid


# ---- retainage (P1-12) ---------------------------------------------------

def create_retainage_release(office, job_id, amount=None, pct=None,
                             invoice_date=None, note="") -> int:
    office.require("ar.edit", "ar_invoice", "retainage")
    held = retainage_outstanding(office, job_id)["outstanding"]
    if pct is not None:
        amt = cents.pct_of(held, pct)
    else:
        amt = cents.amount_in(amount)
    if amt <= 0:
        raise BillingError("The release amount must be more than $0.00.")
    if amt > held:
        raise BillingError(f"Only {cents.fmt(held)} of retainage is held; "
                           f"can't release {cents.fmt(amt)}.")
    d = invoice_date or clock.today().isoformat()
    with office.db.tx():
        iid = _new_invoice(office, job_id, "Retainage", d, amt, retainage=0,
                           tax=0, total=amt, note=note)
        office.db.insert("ar_lines", invoice_id=iid, line_no=1,
                         description=f"Retainage release{': ' + note if note else ''}",
                         kind="retainage", amount=amt)
        office.audit("create", "ar_invoice", iid, None,
                     {"type": "Retainage", "amount": amt, "note": note})
    return iid


# ---- T&M (P1-13) ---------------------------------------------------------

def _billed_on(office, source_type, source_id) -> str | None:
    r = office.db.one("SELECT i.number FROM billed_links b JOIN ar_invoices i "
                      "ON i.id = b.invoice_id WHERE b.source_type = ? AND "
                      "b.source_id = ? AND b.active = 1", (source_type,
                                                          source_id))
    return r["number"] if r else None


def tm_preview(office, job_id, date_from, date_to, cost_codes=None) -> dict:
    c = contract_for(office, job_id)
    if c is None:
        raise BillingError("Set up the billing contract and rates first.")
    already = set()
    groups = {}
    for ln in timeentry.approved_lines(office, job_id, date_from, date_to):
        if cost_codes and ln["cost_code"] not in cost_codes:
            continue
        b = _billed_on(office, "time_line", ln["id"])
        if b:
            already.add(b)
            continue
        r = _rate(office, c["id"], "labor", ln["labor_class"])
        if r is None:
            raise BillingError(f"No billing rate for labor class "
                               f"{ln['labor_class']}.")
        rate = {"REG": r["regular"], "OT": r["overtime"],
                "DT": r["double"]}.get(ln["pay_type"], r["regular"])
        k = ("labor", ln["labor_class"], ln["pay_type"])
        g = groups.setdefault(k, {"kind": "labor", "code": ln["labor_class"],
                                  "pay_type": ln["pay_type"], "rate": rate,
                                  "hours": 0, "sources": []})
        g["hours"] += ln["hours"]
        g["sources"].append(("time_line", ln["id"]))
        if ln["equipment_code"] and ln["equipment_hours"]:
            er = _rate(office, c["id"], "equipment", ln["equipment_code"])
            if er is None:
                raise BillingError(f"No billing rate for equipment "
                                   f"{ln['equipment_code']}.")
            k = ("equipment", ln["equipment_code"], "")
            g = groups.setdefault(k, {"kind": "equipment",
                                      "code": ln["equipment_code"],
                                      "pay_type": "", "rate": er["rate"],
                                      "hours": 0, "sources": []})
            g["hours"] += ln["equipment_hours"]
    out = []
    for (kind, code, pt), g in sorted(groups.items()):
        amt = cents.mul(g["rate"], cents.D(g["hours"]) / 100)
        desc = f"{'Labor' if kind == 'labor' else 'Equipment'} {code}" + \
            (f" {pt}" if pt else "") + \
            f": {cents.hours_text(g['hours'])} h x {cents.fmt(g['rate'])}"
        out.append({"kind": kind, "description": desc, "code": code,
                    "quantity": cents.hours_text(g["hours"]),
                    "rate": g["rate"], "amount": amt, "include": True,
                    "sources": g["sources"]})
    q = ("SELECT l.*, i.number, i.invoice_date, v.name AS vendor FROM ap_lines l "
         "JOIN ap_invoices i ON i.id = l.invoice_id JOIN vendors v ON "
         "v.id = i.vendor_id WHERE l.job_id = ? AND l.deleted = 0 AND "
         "i.status IN ('Approved','Exported','Partly paid','Paid') AND "
         "i.invoice_date BETWEEN ? AND ? AND l.category IN ('M','S','E','O')")
    for ln in office.db.rows(q, (job_id, str(date_from), str(date_to))):
        if cost_codes and ln["cost_code"] not in cost_codes:
            continue
        b = _billed_on(office, "ap_line", ln["id"])
        if b:
            already.add(b)
            continue
        kind = {"M": "material", "S": "subcontract", "E": "equipment",
                "O": "other"}[ln["category"]]
        out.append({"kind": kind, "description": f"{ln['vendor']} "
                    f"{ln['number']}: {ln['description']}".rstrip(": "),
                    "code": ln["cost_code"], "quantity": "1",
                    "rate": ln["amount"], "amount": ln["amount"],
                    "include": True, "sources": [("ap_line", ln["id"])]})
        pct = c["material_markup"] if kind == "material" else \
            c["sub_markup"] if kind == "subcontract" else "0"
        if cents.D(pct):
            out.append({"kind": "markup", "description":
                        f"Markup {pct}% on {ln['number']}",
                        "code": ln["cost_code"], "quantity": "1",
                        "rate": 0, "amount": cents.pct_of(ln["amount"], pct),
                        "include": True, "sources": [],
                        "markup_of": kind})
    msg = ""
    if not out and already:
        msg = "already billed on " + ", ".join(sorted(already))
    return {"lines": out, "message": msg,
            "total": sum(x["amount"] for x in out if x["include"])}


def create_tm_invoice(office, job_id, date_from, date_to, invoice_date=None,
                      cost_codes=None, change_ref="", exclude=()) -> int:
    office.require("ar.edit", "ar_invoice", "T&M")
    pv = tm_preview(office, job_id, date_from, date_to, cost_codes)
    ls = [x for i, x in enumerate(pv["lines"]) if i not in exclude and x["include"]]
    if not ls:
        raise BillingError(pv["message"] or "No unbilled approved time or "
                           "costs in that range.")
    c = contract_for(office, job_id)
    flags = json.loads(c["tax_flags"] or "{}")
    amount = sum(x["amount"] for x in ls)
    taxable = sum(x["amount"] for x in ls if flags.get(x["kind"]))
    tax_c = tax.tax_on(office, c["tax_code_id"], taxable, invoice_date or
                       date_to) if c["tax_code_id"] and taxable else 0
    d = invoice_date or str(date_to)
    with office.db.tx():
        iid = _new_invoice(office, job_id, "T&M", d, amount, retainage=0,
                           tax=tax_c, total=amount + tax_c,
                           change_ref=change_ref,
                           tax_code_id=c["tax_code_id"] if tax_c else None,
                           period_to=str(date_to))
        for n, x in enumerate(ls, start=1):
            lid = office.db.insert("ar_lines", invoice_id=iid, line_no=n,
                                   description=x["description"],
                                   cost_code=x["code"], kind=x["kind"],
                                   quantity=x["quantity"], rate=x["rate"],
                                   amount=x["amount"],
                                   taxable=int(bool(flags.get(x["kind"]))))
            for st, sid in x["sources"]:
                office.db.insert("billed_links", ar_line_id=lid,
                                 invoice_id=iid, source_type=st,
                                 source_id=sid, active=1)
        office.audit("create", "ar_invoice", iid, None,
                     {"type": "T&M", "amount": amount, "tax": tax_c,
                      "change_ref": change_ref})
    return iid


# ---- approve / void and posting (P1-19) ----------------------------------

def approve(office, iid, gl_date=None) -> int:
    office.require("ar.approve", "ar_invoice", iid)
    inv = invoice(office, iid)
    if inv["status"] != "Draft":
        raise BillingError(f"{inv['number']} is {inv['status']}.")
    if gl_date:
        office.db.update("ar_invoices", iid, gl_date=str(gl_date))
        inv = invoice(office, iid)
    ledger.check_open(office, inv["gl_date"])
    with office.db.tx():
        eid = post_invoice(office, iid)
        office.db.update("ar_invoices", iid, status="Approved", entry_id=eid)
        if inv["type"] == "Progress" and inv["retainage"]:
            office.db.insert("retainage_ledger", job_id=inv["job_id"],
                             invoice_id=iid,
                             kind="held" if inv["retainage"] > 0 else "released",
                             amount=abs(inv["retainage"]), date=inv["gl_date"])
        if inv["type"] == "Retainage":
            office.db.insert("retainage_ledger", job_id=inv["job_id"],
                             invoice_id=iid, kind="released",
                             amount=inv["amount"], date=inv["gl_date"])
        if inv["tax"] and inv["tax_code_id"]:
            taxable = sum(ln["amount"] for ln in lines(office, iid)
                          if ln["taxable"])
            tax.record(office, "ar_invoice", iid, inv["tax_code_id"], taxable,
                       inv["tax"], inv["gl_date"], eid)
        office.audit("approve", "ar_invoice", iid, {"status": "Draft"},
                     {"status": "Approved", "entry": eid})
        if inv["type"] == "Progress":
            from . import waivers
            waivers.draft_for_invoice(office, iid)
    return eid


def post_invoice(office, iid) -> int:
    inv = invoice(office, iid)
    j = inv["job_id"]
    cust = inv["customer"]
    ar = ledger.default_account(office, "ar")
    jl = []
    if inv["type"] == "Progress":
        ret = inv["retainage"] or 0
        jl.append({"account": ar, "debit": inv["total"], "job_id": j,
                   "party": cust})
        if ret > 0:
            jl.append({"account": ledger.default_account(office, "ar_retainage"),
                       "debit": ret, "job_id": j, "party": cust})
        elif ret < 0:
            jl.append({"account": ledger.default_account(office, "ar_retainage"),
                       "credit": -ret, "job_id": j, "party": cust})
        jl.append({"account": ledger.default_account(office, "revenue_contract"),
                   "credit": inv["amount"] + ret, "job_id": j, "party": cust})
    elif inv["type"] == "Retainage":
        jl.append({"account": ar, "debit": inv["total"], "job_id": j,
                   "party": cust})
        jl.append({"account": ledger.default_account(office, "ar_retainage"),
                   "credit": inv["amount"], "job_id": j, "party": cust})
    else:
        key = "revenue_tm" if inv["type"] == "T&M" else "revenue_other"
        jl.append({"account": ar, "debit": inv["total"], "job_id": j,
                   "party": cust})
        for ln in lines(office, iid):
            jl.append({"account": ledger.default_account(office, key),
                       "credit": ln["amount"], "job_id": j,
                       "cost_code": ln["cost_code"], "party": cust,
                       "memo": ln["description"]})
        if inv["tax"]:
            acct = tax.code(office, inv["tax_code_id"])["account_id"] \
                if inv["tax_code_id"] else ledger.default_account(office,
                                                                  "sales_tax")
            jl.append({"account": acct, "credit": inv["tax"], "job_id": j,
                       "party": cust, "memo": "Sales tax"})
    return ledger.post(office, inv["gl_date"], jl, "ar_invoice", iid,
                       f"Invoice {inv['number']} {cust}".strip())


def void(office, iid, date=None, reason="") -> None:
    office.require("ar.edit", "ar_invoice", iid)
    inv = invoice(office, iid)
    if not (reason or "").strip():
        raise BillingError("A reason is required to void.")
    if office.db.scalar("SELECT COUNT(*) FROM payment_apps a JOIN payments p "
                        "ON p.id = a.payment_id WHERE a.invoice_id = ? AND "
                        "p.void = 0", (iid,)):
        raise BillingError(f"{inv['number']} has payments applied; "
                           f"unapply them first.")
    d = str(date or clock.today())
    with office.db.tx():
        if inv["status"] != "Draft":
            ledger.reverse_source(office, "ar_invoice", iid, d)
        office.db.conn.execute("UPDATE billed_links SET active = 0 WHERE "
                               "invoice_id = ?", (iid,))
        office.db.conn.execute("UPDATE retainage_ledger SET deleted = 1 WHERE "
                               "invoice_id = ?", (iid,))
        office.db.conn.execute("UPDATE tax_lines SET deleted = 1 WHERE "
                               "doc_type = 'ar_invoice' AND doc_id = ?", (iid,))
        office.db.update("ar_invoices", iid, status="Void", void_date=d)
        office.audit("void", "ar_invoice", iid, {"status": inv["status"]},
                     {"status": "Void", "reason": reason})


def mark_sent(office, iid, sent_to, sent_on=None) -> None:
    """The user records that they sent it (Back Office never sends)."""
    office.require("ar.edit", "ar_invoice", iid)
    inv = invoice(office, iid)
    with office.db.tx():
        office.db.update("ar_invoices", iid, status="Sent" if
                         inv["status"] == "Approved" else inv["status"],
                         sent_to=sent_to,
                         sent_on=str(sent_on or clock.today()))
        office.db.insert("sent_log", invoice_id=iid, sent_to=sent_to,
                         ts=clock.iso_now(), file_hash=inv["pdf_hash"],
                         recorded_by=office.who)
        office.audit("sent", "ar_invoice", iid, None, {"to": sent_to})


# ---- service desk invoices (QuantiSheet 1.2, Nov 5) -----------------------

SERVICE_PREFIX = "SVC-"


def import_service_invoices(office, job_id, post=False, gl_date=None):
    """Closed service work orders' invoices from the QuantiSheet snapshot
    (section service_invoices) -> AR invoices, each once: the Back Office
    number is SVC-<QuantiSheet number>, and one already there adds
    nothing. post=True approves and posts them (ar.approve). A reversal in the
    snapshot voids the posted invoice - the ledger keeps the original and
    a reversing entry, nothing is edited or deleted.

    Returns {"created", "posted", "reversed", "skipped"}; skipped lists
    (number, why)."""
    office.require("ar.edit", "ar_invoice", "service")
    out = {"created": [], "posted": [], "reversed": [], "skipped": []}
    recs = jobs.section(office, job_id, "service_invoices")
    for r in [x for x in recs if not x.get("reverse")]:
        num = SERVICE_PREFIX + r["number"]
        if invoice_by_number(office, num):
            out["skipped"].append((num, "already in Back Office"))
            continue
        iid = create_other_invoice(
            office, job_id, r["date"],
            [{"description": " ".join(p for p in (
                ln["description"], f"({ln['qty']} {ln['unit']})"
                if ln.get("qty") else "") if p),
              "amount": ln["amount"], "kind": "service",
              "taxable": ln.get("taxable")} for ln in r["lines"]],
            customer=r["customer"], number=num,
            note=f"Service work order {r['work_order']} {r['site']}".strip())
        if cents.to_cents(r["total"]) != invoice(office, iid)["amount"]:
            raise BillingError(f"{num}: total doesn't match its lines")
        out["created"].append(iid)
        if post:
            approve(office, iid, gl_date=gl_date)
            out["posted"].append(iid)
    for r in [x for x in recs if x.get("reverse")]:
        num = SERVICE_PREFIX + r["number"]
        inv = invoice_by_number(office, num)
        if inv is None:
            out["skipped"].append((num, "reversal for an invoice that "
                                        "isn't in Back Office"))
            continue
        if inv["status"] == "Void":
            out["skipped"].append((num, "already reversed"))
            continue
        void(office, inv["id"], date=r["date"] or None,
             reason=f"QuantiSheet reversal: {r['reason']}")
        out["reversed"].append(inv["id"])
    return out


def register(office) -> list[dict]:
    return office.db.rows("SELECT * FROM ar_invoices WHERE deleted = 0 "
                          "ORDER BY number")
