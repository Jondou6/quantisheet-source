"""Vendors, AP invoice and receipt capture (P1-08), coding and approval
routing by thresholds with commitment and compliance checks (P1-09).

An approved invoice posts one balanced journal entry (P1-19): debit the
job-cost account of each line, credit Accounts payable for the amount
less retainage and Retainage payable for the retainage held.
"""
from __future__ import annotations

import json
from datetime import timedelta

from . import approvals, cents, clock, jobs, ledger, ocr, store
from .security import Denied

STATUSES = ("Draft", "In Approval", "Approved", "Rejected", "Exported",
            "Partly paid", "Paid", "Void")
OPEN_FOR_PAYMENT = ("Approved", "Exported", "Partly paid")


class APError(ValueError):
    pass


class DuplicateError(APError):
    def __init__(self, warnings):
        super().__init__("; ".join(warnings))
        self.warnings = warnings


class CaptureError(APError):
    pass


# ---- vendors -------------------------------------------------------------

def add_vendor(office, name, tax_id=None, bank=None, terms=30, is_1099=0,
               box_1099="NEC", w9=None, insurance_expires="",
               license_expires="", default_cost_code="", address="",
               email="", phone="", account_id=None) -> int:
    office.require("ap.edit", "vendor", name)
    with office.db.tx():
        vid = office.db.insert(
            "vendors", name=name, tax_id=office.crypto.encrypt(tax_id),
            bank=office.crypto.encrypt(bank), terms=terms, is_1099=is_1099,
            box_1099=box_1099, w9=w9, insurance_expires=insurance_expires,
            license_expires=license_expires,
            default_cost_code=default_cost_code, address=address,
            email=email, phone=phone, account_id=account_id)
        office.audit("create", "vendor", vid, None,
                     {"name": name, "tax_id": "(encrypted)" if tax_id else ""})
    return vid


def vendor(office, vid) -> dict:
    return office.db.get("vendors", vid)


def vendor_by_name(office, name) -> dict | None:
    return office.db.one("SELECT * FROM vendors WHERE lower(name) = lower(?) "
                         "AND deleted = 0", (name,))


def vendor_tax_id(office, vid, reveal=False) -> str:
    from .crypto import mask
    v = vendor(office, vid)
    plain = office.crypto.decrypt(v["tax_id"]) or ""
    if reveal:
        office.require("1099.full_tin", "vendor", vid)
        office.audit("reveal", "vendor", vid, None, {"field": "tax_id"})
        return plain
    return mask(plain)


def update_vendor(office, vid, **fields) -> None:
    office.require("ap.edit", "vendor", vid)
    old = vendor(office, vid)
    for k in ("tax_id", "bank"):
        if k in fields:
            fields[k] = office.crypto.encrypt(fields[k])
    with office.db.tx():
        office.db.update("vendors", vid, **fields)
        office.audit("change", "vendor", vid,
                     {k: old[k] for k in fields if k not in ("tax_id", "bank")},
                     {k: v for k, v in fields.items()
                      if k not in ("tax_id", "bank")})


def seed_vendors(office, job_id) -> list[int]:
    """Vendors from the snapshot's commitments and directory (companies)."""
    out = []
    for c in jobs.section(office, job_id, "commitments"):
        v = vendor_by_name(office, c["vendor"])
        w9 = {"Yes": 1, "No": 0}.get(c["w9"])
        if v is None:
            out.append(add_vendor(office, c["vendor"], w9=w9,
                                  insurance_expires=c["insurance_expires"],
                                  license_expires=c["license_expires"]))
        else:
            update_vendor(office, v["id"],
                          insurance_expires=c["insurance_expires"] or
                          v["insurance_expires"],
                          license_expires=c["license_expires"] or
                          v["license_expires"],
                          w9=w9 if w9 is not None else v["w9"])
    for m in jobs.section(office, job_id, "directory"):
        name = m["company"]
        if name and m["role"] in ("Subcontractor", "Supplier", "Vendor") and \
                not vendor_by_name(office, name):
            out.append(add_vendor(office, name, email=m["email"],
                                  phone=m["phone"]))
    return out


# ---- capture -------------------------------------------------------------

def capture(office, path, engine=None, override_reason="") -> dict:
    """Read a PDF or photo: copies it into the data folder and suggests
    fields with a confidence each. Nothing is saved as an invoice yet.
    A likely duplicate is refused unless override_reason says why."""
    office.require("ap.edit", "ap_invoice", "capture")
    names = [v["name"] for v in office.db.rows(
        "SELECT name FROM vendors WHERE deleted = 0")]
    res = ocr.extract(path, names, engine)
    kept = store.copy_into(office.documents_folder(), path)
    res["doc_path"] = kept
    res["doc_hash"] = store.file_hash(kept)
    v = res["fields"].get("vendor")
    res["vendor_id"] = (vendor_by_name(office, v[0]) or {}).get("id") if v else None
    res["needs_confirm"] = [k for k, (_, c) in res["fields"].items()
                            if c == ocr.LOW]
    from .r111.dupblock import find, record_override
    fields = res["fields"]
    total_c = None
    if "total" in fields:
        try:
            total_c = cents.parse_amount(fields["total"][0])
        except cents.MoneyError:
            total_c = None
    reasons = find(office, res.get("vendor_id"),
                   (fields.get("invoice_no") or ("",))[0],
                   total_c,
                   (fields.get("invoice_date") or ("",))[0] or None,
                   doc_hash=res["doc_hash"])
    res["duplicates"] = reasons
    if reasons and not str(override_reason or "").strip():
        err = DuplicateError(reasons)
        err.capture = res
        raise err
    if reasons:
        record_override(office, None, reasons, override_reason,
                        res["doc_hash"])
        res["duplicate_override"] = {"who": office.who,
                                     "why": str(override_reason).strip()}
    return res


def duplicates(office, vendor_id, invoice_no, total_c, invoice_date,
               exclude_id=None, doc_hash=None) -> list[str]:
    """Same vendor and invoice number, or the same vendor and amount
    within 7 days, or the same file."""
    from .r111.dupblock import find
    return find(office, vendor_id, invoice_no, total_c, invoice_date,
                doc_hash=doc_hash, exclude_id=exclude_id)


def create_invoice(office, vendor_id, invoice_no, invoice_date, total,
                   tax="0", due_date=None, lines=None, commitment_no="",
                   job_id=None, capture_result=None, confirmed=(),
                   override_reason="", retainage=None, gl_date=None,
                   use_tax_code=None, final=False) -> int:
    office.require("ap.edit", "ap_invoice", invoice_no)
    total_c = cents.amount_in(total)
    tax_c = cents.amount_in(tax)
    if capture_result:
        low = [k for k in capture_result.get("needs_confirm", [])
               if k not in confirmed]
        if low:
            raise CaptureError("Confirm or edit the highlighted field(s) "
                               f"before saving: {', '.join(low)}")
    doc_hash = (capture_result or {}).get("doc_hash")
    dups = duplicates(office, vendor_id, invoice_no, total_c, invoice_date,
                      doc_hash=doc_hash)
    if dups and not (override_reason or "").strip():
        raise DuplicateError(dups)
    v = vendor(office, vendor_id)
    if due_date is None:
        due_date = (clock.d(invoice_date) +
                    timedelta(days=v["terms"] or 30)).isoformat()
    ret_c = 0
    if retainage is not None:
        ret_c = cents.amount_in(retainage)
    elif commitment_no and job_id:
        c = jobs.record(office, job_id, "commitments", commitment_no)
        if c:
            ret_c = cents.pct_of(total_c, c["retainage"])
    with office.db.tx():
        number = office.db.next_number("AP", "AP-{n:04d}")
        iid = office.db.insert(
            "ap_invoices", number=number, vendor_id=vendor_id,
            invoice_no=invoice_no, invoice_date=str(invoice_date),
            due_date=str(due_date), gl_date=str(gl_date or invoice_date),
            total=total_c, tax=tax_c, retainage=ret_c,
            commitment_no=commitment_no, job_id=job_id, status="Draft",
            doc_path=(capture_result or {}).get("doc_path"),
            doc_hash=(capture_result or {}).get("doc_hash"),
            ocr_text=(capture_result or {}).get("text"),
            ocr_conf={k: c for k, (_, c) in
                      (capture_result or {}).get("fields", {}).items()},
            dup_override=override_reason if dups else None,
            use_tax_code=use_tax_code, final=int(bool(final)))
        office.audit("create", "ap_invoice", iid, None,
                     {"number": number, "vendor": v["name"],
                      "invoice_no": invoice_no, "total": total_c,
                      "duplicate_warnings": dups,
                      "override_reason": override_reason if dups else ""})
        from .r111.duties import note
        note(office, "ap_invoice", iid, "entered")
        if dups:
            from .r111.dupblock import record_override
            record_override(office, iid, dups, override_reason,
                            doc_hash or "")
        if lines:
            _write_lines(office, iid, lines, job_id)
    return iid


def _write_lines(office, iid, lines, job_id):
    office.db.conn.execute("UPDATE ap_lines SET deleted = 1 WHERE invoice_id = ?",
                           (iid,))
    for n, ln in enumerate(lines, start=1):
        amt = ln["amount"]
        amt = cents.amount_in(amt)
        jid = ln.get("job_id", job_id)
        cat = ln.get("category") or (jobs.code_category(office, jid, ln.get(
            "cost_code", "")) if jid and ln.get("cost_code") else "")
        office.db.insert("ap_lines", invoice_id=iid, line_no=n, job_id=jid,
                         phase=ln.get("phase", ""),
                         cost_code=ln.get("cost_code", ""), category=cat,
                         description=ln.get("description", ""), amount=amt,
                         account_id=ln.get("account_id"),
                         box_1099=ln.get("box_1099"))
    from .r111.duties import note
    note(office, "ap_invoice", iid, "coded")


def invoice(office, iid) -> dict:
    return office.db.get("ap_invoices", iid)


def lines(office, iid) -> list[dict]:
    return office.db.rows("SELECT * FROM ap_lines WHERE invoice_id = ? AND "
                          "deleted = 0 ORDER BY line_no", (iid,))


def _editable(office, inv):
    if inv["status"] not in ("Draft", "Rejected"):
        raise APError(f"{inv['number']} is {inv['status']}; it can't be edited.")


def set_lines(office, iid, new_lines) -> None:
    office.require("ap.edit", "ap_invoice", iid)
    inv = invoice(office, iid)
    _editable(office, inv)
    with office.db.tx():
        before = lines(office, iid)
        _write_lines(office, iid, new_lines, inv["job_id"])
        office.audit("change", "ap_invoice", iid, {"lines": before},
                     {"lines": lines(office, iid)})


def save(office, iid, **fields) -> None:
    """Direct save through the model layer (permission checked, logged)."""
    office.require("ap.edit", "ap_invoice", iid)
    inv = invoice(office, iid)
    _editable(office, inv)
    for k in ("total", "tax", "retainage"):
        if k in fields and isinstance(fields[k], str):
            fields[k] = cents.parse_amount(fields[k])
    with office.db.tx():
        office.db.update("ap_invoices", iid, **fields)
        office.audit("change", "ap_invoice", iid, {k: inv[k] for k in fields},
                     fields)


# ---- routing, commitment and compliance (P1-09) --------------------------

def seed_default_rules(office) -> None:
    """Decision 16 = A: under $2,500 PM only; $2,500 to $25,000 PM then
    Controller; over $25,000 PM, Controller, then Admin."""
    if office.db.one("SELECT id FROM routing_rules LIMIT 1"):
        return
    pm, ctl, adm = (approvals.step("jobrole:PM"),
                    approvals.step("role:Controller"),
                    approvals.step("role:Admin"))
    with office.db.tx():
        office.db.insert("routing_rules", priority=900, min_amount=None,
                         max_amount=249_999, steps=[pm], active=1)
        office.db.insert("routing_rules", priority=910, min_amount=250_000,
                         max_amount=2_500_000, steps=[pm, ctl], active=1)
        office.db.insert("routing_rules", priority=920, min_amount=2_500_001,
                         max_amount=None, steps=[pm, ctl, adm], active=1)


def add_rule(office, priority, steps, job_id=None, vendor_id=None,
             cost_code=None, min_amount=None, max_amount=None,
             escalate_days=None, escalate_to=None) -> int:
    office.require("routing.edit", "routing_rule", "")
    with office.db.tx():
        rid = office.db.insert("routing_rules", priority=priority,
                               job_id=job_id, vendor_id=vendor_id,
                               cost_code=cost_code, min_amount=min_amount,
                               max_amount=max_amount, steps=steps,
                               escalate_days=escalate_days,
                               escalate_to=escalate_to, active=1)
        office.audit("create", "routing_rule", rid, None,
                     {"priority": priority, "steps": steps})
    return rid


def route(office, iid) -> dict:
    inv = invoice(office, iid)
    codes = {ln["cost_code"] for ln in lines(office, iid)}
    for r in office.db.rows("SELECT * FROM routing_rules WHERE active = 1 AND "
                            "deleted = 0 ORDER BY priority, id"):
        if r["job_id"] and r["job_id"] != inv["job_id"]:
            continue
        if r["vendor_id"] and r["vendor_id"] != inv["vendor_id"]:
            continue
        if r["cost_code"] and r["cost_code"] not in codes:
            continue
        if r["min_amount"] is not None and inv["total"] < r["min_amount"]:
            continue
        if r["max_amount"] is not None and inv["total"] > r["max_amount"]:
            continue
        steps = json.loads(r["steps"])
        # over its commitment: the final approval is an Admin's, with a
        # reason (P1-09 test 2), whatever band the amount falls in
        if over_commitment(office, iid) and \
                steps[-1]["principals"] != ["role:Admin"]:
            steps.append(approvals.step("role:Admin"))
        return {"rule_id": r["id"], "steps": steps,
                "escalate_days": r["escalate_days"],
                "escalate_to": r["escalate_to"]}
    raise APError("no routing rule matches this invoice")


def path_text(office, iid) -> list[str]:
    return [" / ".join(approvals.label(p) for p in s["principals"])
            for s in route(office, iid)["steps"]]


def commitment_status(office, job_id, number, exclude_invoice=None) -> dict:
    c = jobs.record(office, job_id, "commitments", number)
    if c is None:
        raise APError(f"no commitment {number} on this job")
    original = sum(cents.to_cents(ln["amount"]) for ln in c["lines"])
    snap_inv = sum(cents.to_cents(d["amount"]) for d in
                   jobs.section(office, job_id, "direct_costs")
                   if d.get("commitment") == number)
    bo = office.db.rows("SELECT id, total, retainage FROM ap_invoices WHERE "
                        "job_id = ? AND commitment_no = ? AND status NOT IN "
                        "('Void','Rejected') AND deleted = 0", (job_id, number))
    bo_inv = sum(r["total"] for r in bo if r["id"] != exclude_invoice)
    held = sum(r["retainage"] or 0 for r in bo if r["id"] != exclude_invoice)
    invoiced = snap_inv + bo_inv
    return {"number": number, "vendor": c["vendor"], "original": original,
            "approved_changes": 0, "revised": original, "invoiced": invoiced,
            "remaining": original - invoiced, "retainage_held": held,
            "retainage_pct": c["retainage"]}


def over_commitment(office, iid) -> int:
    inv = invoice(office, iid)
    if not inv["commitment_no"] or not inv["job_id"]:
        return 0
    st = commitment_status(office, inv["job_id"], inv["commitment_no"],
                           exclude_invoice=iid)
    over = st["invoiced"] + inv["total"] - st["revised"]
    return max(over, 0)


def warnings(office, iid) -> list[str]:
    out = []
    over = over_commitment(office, iid)
    if over:
        out.append(f"over commitment by {cents.fmt(over)}")
    inv = invoice(office, iid)
    out += duplicates(office, inv["vendor_id"], inv["invoice_no"],
                      inv["total"], inv["invoice_date"], exclude_id=iid)
    out += expiring_soon(office, inv)
    return out


def _cover_dates(office, inv):
    v = vendor(office, inv["vendor_id"])
    ins, lic = v["insurance_expires"], v["license_expires"]
    if inv["commitment_no"] and inv["job_id"]:
        c = jobs.record(office, inv["job_id"], "commitments",
                        inv["commitment_no"])
        if c:
            ins = c["insurance_expires"] or ins
            lic = c["license_expires"] or lic
    return ins, lic


def expiring_soon(office, inv, days=30) -> list[str]:
    """Insurance or license running out within `days` (not yet expired -
    that's a hold): a warning while there is still time to get the new
    certificate (P1 compliance tracking)."""
    import datetime as _dt
    today = clock.today()
    out = []
    for what, d in zip(("insurance", "license"), _cover_dates(office, inv)):
        if not d:
            continue
        try:
            end = _dt.date.fromisoformat(str(d)[:10])
        except ValueError:
            continue
        n = (end - today).days
        if 0 <= n <= days:
            out.append(f"{what} expires {end.isoformat()} (in {n} day"
                       f"{'s' if n != 1 else ''}) - ask for the new "
                       "certificate")
    return out


def compliance_watch(office, days=30) -> list[dict]:
    """Every vendor whose insurance or license has expired (payments are
    held) or runs out within `days` - for the AP page."""
    import datetime as _dt
    today = clock.today()
    out = []
    for v in office.db.rows("SELECT * FROM vendors WHERE deleted = 0 "
                            "ORDER BY name"):
        for what in ("insurance", "license"):
            d = v.get(f"{what}_expires")
            if not d:
                continue
            try:
                end = _dt.date.fromisoformat(str(d)[:10])
            except ValueError:
                continue
            n = (end - today).days
            if n <= days:
                out.append({"vendor": v["name"], "what": what,
                            "expires": end.isoformat(), "days": n,
                            "status": "HOLD - expired" if n < 0 else
                            f"expires in {n} days"})
    out.sort(key=lambda x: x["days"])
    return out


def _compliance_reasons(office, inv) -> list[str]:
    v = vendor(office, inv["vendor_id"])
    today = clock.today().isoformat()
    ins, lic, w9 = v["insurance_expires"], v["license_expires"], v["w9"]
    if inv["commitment_no"] and inv["job_id"]:
        c = jobs.record(office, inv["job_id"], "commitments",
                        inv["commitment_no"])
        if c:
            ins = c["insurance_expires"] or ins
            lic = c["license_expires"] or lic
            if c["w9"] in ("Yes", "No"):
                w9 = 1 if c["w9"] == "Yes" else 0
    out = []
    if ins and ins < today:
        out.append(f"insurance expired {ins}")
    if lic and lic < today:
        out.append(f"license expired {lic}")
    if w9 == 0:
        out.append("no W-9 on file")
    from . import waivers
    for kind in waivers.required_kinds(office, inv["job_id"], v["id"]):
        if not waivers.has_received(office, v["id"], inv["job_id"], kind):
            out.append(f"waiver missing ({kind.replace('_', ' ')})")
    return out


def open_holds(office, iid) -> list[dict]:
    return office.db.rows("SELECT * FROM compliance_holds WHERE invoice_id = ? "
                          "AND cleared_at IS NULL AND deleted = 0", (iid,))


def check_compliance(office, iid) -> list[dict]:
    inv = invoice(office, iid)
    have = {h["reason"] for h in office.db.rows(
        "SELECT reason FROM compliance_holds WHERE invoice_id = ?", (iid,))}
    with office.db.tx():
        for reason in _compliance_reasons(office, inv):
            if reason not in have:
                hid = office.db.insert("compliance_holds", invoice_id=iid,
                                       reason=reason)
                office.audit("hold", "ap_invoice", iid, None,
                             {"hold": hid, "reason": reason})
    return open_holds(office, iid)


def clear_hold(office, hold_id, note) -> None:
    office.require("compliance.clear", "compliance_hold", hold_id)
    if not (note or "").strip():
        raise APError("A note is required to clear a compliance hold.")
    with office.db.tx():
        office.db.update("compliance_holds", hold_id, cleared_by=office.who,
                         cleared_at=clock.iso_now(), note=note)
        h = office.db.get("compliance_holds", hold_id)
        office.audit("clear hold", "ap_invoice", h["invoice_id"], None,
                     {"reason": h["reason"], "note": note})


def submit(office, iid) -> dict:
    office.require("ap.edit", "ap_invoice", iid)
    inv = invoice(office, iid)
    _editable(office, inv)
    ls = lines(office, iid)
    if not ls:
        raise APError(f"{inv['number']} has no coding lines.")
    if sum(ln["amount"] for ln in ls) != inv["total"]:
        raise APError(f"{inv['number']}: the lines add to "
                      f"{cents.fmt(sum(ln['amount'] for ln in ls))}, not the "
                      f"total {cents.fmt(inv['total'])}.")
    r = route(office, iid)
    with office.db.tx():
        office.db.update("ap_invoices", iid, status="In Approval")
        approvals.start(office, "ap_invoice", iid, r["steps"], inv["job_id"],
                        r["escalate_days"], r["escalate_to"])
        check_compliance(office, iid)
    return r


def approve(office, iid, override_reason="", gl_date=None) -> dict:
    office.require("ap.approve", "ap_invoice", iid)
    inv = invoice(office, iid)
    if inv["status"] != "In Approval":
        raise APError(f"{inv['number']} is {inv['status']}, not in approval.")
    holds = check_compliance(office, iid)
    if holds:
        office.audit("denied", "ap_invoice", iid, None,
                     {"reason": "compliance hold"})
        raise APError("Compliance hold: " + "; ".join(h["reason"] for h in holds)
                      + ". A Controller must clear it first.")
    req = approvals.request(office, "ap_invoice", iid)
    last = req["step"] + 1 >= len(req["steps"])
    over = over_commitment(office, iid)
    if gl_date:
        save_gl_date(office, iid, gl_date)
        inv = invoice(office, iid)
    if last:
        if over:
            if office.role != "Admin" or not (override_reason or "").strip():
                office.audit("denied", "ap_invoice", iid, None,
                             {"reason": "over commitment",
                              "over": over})
                raise APError(f"over commitment by {cents.fmt(over)}: final "
                              f"approval needs an Admin override reason.")
        ledger.check_open(office, inv["gl_date"])
    approvals.precheck(office, "ap_invoice", iid, "approve", override_reason,
                       owner_id=_owner(office, inv))
    with office.db.tx():
        req = approvals.decide(office, "ap_invoice", iid, "approve",
                               override_reason, owner_id=_owner(office, inv))
        if over and last:
            office.db.update("ap_invoices", iid, overcommit_reason=override_reason)
            office.audit("override", "ap_invoice", iid, None,
                         {"over_commitment": over, "reason": override_reason})
        if req["status"] == "approved":
            office.db.update("ap_invoices", iid, status="Approved")
            eid = post_invoice(office, iid)
            office.db.update("ap_invoices", iid, entry_id=eid)
    return req


def save_gl_date(office, iid, gl_date):
    """Post on another date (e.g. after a close); the vendor's invoice date
    stays on the invoice."""
    inv = invoice(office, iid)
    with office.db.tx():
        office.db.update("ap_invoices", iid, gl_date=str(gl_date))
        office.audit("change", "ap_invoice", iid, {"gl_date": inv["gl_date"]},
                     {"gl_date": str(gl_date)})


def _owner(office, inv):
    u = office.db.one("SELECT id FROM users WHERE name = ?", (inv["created_by"],))
    return u["id"] if u else None


def reject(office, iid, reason) -> None:
    office.require("ap.approve", "ap_invoice", iid)
    inv = invoice(office, iid)
    approvals.precheck(office, "ap_invoice", iid, "reject", reason,
                       owner_id=_owner(office, inv))
    with office.db.tx():
        approvals.decide(office, "ap_invoice", iid, "reject", reason,
                         owner_id=_owner(office, inv))
        office.db.update("ap_invoices", iid, status="Rejected")


def post_invoice(office, iid) -> int:
    inv = invoice(office, iid)
    v = vendor(office, inv["vendor_id"])
    jl = []
    for ln in lines(office, iid):
        acct = ln["account_id"] or ledger.cost_account(
            office, ln["category"], ln["cost_code"], inv["vendor_id"],
            ln["job_id"])
        jl.append({"account": acct, "debit": ln["amount"],
                   "job_id": ln["job_id"], "cost_code": ln["cost_code"],
                   "category": ln["category"], "party": v["name"],
                   "memo": ln["description"] or f"{v['name']} {inv['invoice_no']}"})
    ret = inv["retainage"] or 0
    jl.append({"account": ledger.default_account(office, "ap"),
               "credit": inv["total"] - ret, "party": v["name"],
               "job_id": inv["job_id"]})
    if ret:
        jl.append({"account": ledger.default_account(office, "ap_retainage"),
                   "credit": ret, "party": v["name"], "job_id": inv["job_id"]})
    if inv["use_tax_code"] and not inv["tax"]:
        from . import tax
        jl += tax.use_tax_lines(office, inv, lines(office, iid))
    return ledger.post(office, inv["gl_date"], jl, "ap_invoice", iid,
                       f"Bill {inv['number']} {v['name']} {inv['invoice_no']}")


def void(office, iid, date, reason) -> None:
    office.require("ap.edit", "ap_invoice", iid)
    inv = invoice(office, iid)
    if not (reason or "").strip():
        raise APError("A reason is required to void.")
    if office.db.scalar("SELECT COUNT(*) FROM bill_payment_apps a JOIN "
                        "bill_payments p ON p.id = a.payment_id WHERE "
                        "a.invoice_id = ? AND p.void = 0", (iid,)):
        raise APError(f"{inv['number']} has payments; void them first.")
    with office.db.tx():
        ledger.reverse_source(office, "ap_invoice", iid, date)
        office.db.update("ap_invoices", iid, status="Void")
        office.audit("void", "ap_invoice", iid, {"status": inv["status"]},
                     {"reason": reason})


def inbox(office) -> list[dict]:
    return approvals.inbox(office, record_type="ap_invoice")
