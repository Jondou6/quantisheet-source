"""Lien waivers issued to owners and received from subs (P1-14).

Same four kinds as QuantiSheet's billing. Neutral wording by default
(decision 13 = A); where a state uses a statutory form the user attaches
that state's form PDF. Signing happens in QuantiSheet's E-Sign or in ink;
Back Office records the signed copy and its hash.
"""
from __future__ import annotations

from . import cents, clock, store

KINDS = {
    "conditional_progress": "Conditional waiver on progress payment",
    "unconditional_progress": "Unconditional waiver on progress payment",
    "conditional_final": "Conditional waiver on final payment",
    "unconditional_final": "Unconditional waiver on final payment",
}
# the 12 states named in QuantiSheet's waiver warning
STATUTORY_STATES = {
    "CA": "California", "TX": "Texas", "FL": "Florida", "GA": "Georgia",
    "AZ": "Arizona", "NV": "Nevada", "UT": "Utah", "MI": "Michigan",
    "MS": "Mississippi", "MO": "Missouri", "WY": "Wyoming",
    "MA": "Massachusetts"}
WARNING = ("Several states (" + ", ".join(STATUTORY_STATES.values()) +
           ") use their own statutory waiver wording. Attach the state's form "
           "where required and have counsel review.")
STATUSES = ("Draft", "Sent", "Signed", "Received", "Void")


class WaiverError(ValueError):
    pass


def create(office, direction, kind, job_id, through, amount, party="",
           vendor_id=None, state=None, form_path="", exceptions="",
           ar_invoice_id=None, payment_id=None, ap_invoice_id=None,
           commitment_no="", status="Draft") -> int:
    office.require("waivers.edit", "waiver", "")
    if kind not in KINDS:
        raise WaiverError(f"kind must be one of {', '.join(KINDS)}")
    if direction not in ("issued", "received"):
        raise WaiverError("direction must be issued or received")
    if state is None and job_id:
        state = (office.db.get("jobs", job_id) or {}).get("state") or ""
    state = (state or "").upper()
    if state in STATUTORY_STATES and not form_path:
        raise WaiverError(f"{STATUTORY_STATES[state]} uses a statutory form; "
                          f"attach it or pick another state")
    amt = cents.amount_in(amount)
    with office.db.tx():
        wid = office.db.insert(
            "waivers", direction=direction, kind=kind, job_id=job_id,
            party=party, vendor_id=vendor_id, through=str(through),
            amount=amt, exceptions=exceptions, state=state,
            form="statutory" if form_path else "neutral",
            form_path=form_path, status=status, ar_invoice_id=ar_invoice_id,
            payment_id=payment_id, ap_invoice_id=ap_invoice_id,
            commitment_no=commitment_no)
        office.audit("create", "waiver", wid, None,
                     {"kind": kind, "direction": direction, "amount": amt})
    return wid


def draft_for_invoice(office, iid) -> int | None:
    """Conditional progress waiver drafted when a progress invoice is
    approved (skipped, with a log entry, when the state needs a form)."""
    inv = office.db.get("ar_invoices", iid)
    try:
        return create(office, "issued", "conditional_progress", inv["job_id"],
                      inv["period_to"] or inv["invoice_date"],
                      cents.from_cents(inv["total"]),
                      party=inv["customer"], ar_invoice_id=iid)
    except WaiverError as e:
        office.audit("waiver skipped", "ar_invoice", iid, None, {"why": str(e)})
        return None


def draft_for_payment(office, payment_id, invoice_id, amount_c) -> int | None:
    """Unconditional progress waiver for the amount actually received."""
    inv = office.db.get("ar_invoices", invoice_id)
    if inv["type"] not in ("Progress", "Retainage"):
        return None
    kind = "unconditional_final" if inv["type"] == "Retainage" and \
        _retainage_cleared(office, inv["job_id"]) else "unconditional_progress"
    try:
        return create(office, "issued", kind, inv["job_id"],
                      inv["period_to"] or inv["invoice_date"],
                      cents.from_cents(amount_c),
                      party=inv["customer"], ar_invoice_id=invoice_id,
                      payment_id=payment_id)
    except WaiverError as e:
        office.audit("waiver skipped", "payment", payment_id, None,
                     {"why": str(e)})
        return None


def _retainage_cleared(office, job_id):
    from . import billing
    return billing.retainage_outstanding(office, job_id)["outstanding"] == 0


def set_status(office, wid, status, signed_path="") -> None:
    office.require("waivers.edit", "waiver", wid)
    if status not in STATUSES:
        raise WaiverError(f"status must be one of {', '.join(STATUSES)}")
    w = office.db.get("waivers", wid)
    fields = {"status": status}
    if signed_path:
        kept = store.copy_into(office.documents_folder(), signed_path)
        fields.update(signed_path=kept, signed_hash=store.file_hash(kept))
    with office.db.tx():
        office.db.update("waivers", wid, **fields)
        office.audit("change", "waiver", wid, {"status": w["status"]}, fields)


def waivers(office, direction=None, job_id=None) -> list[dict]:
    q, p = "SELECT * FROM waivers WHERE deleted = 0", []
    if direction:
        q += " AND direction = ?"
        p.append(direction)
    if job_id:
        q += " AND job_id = ?"
        p.append(job_id)
    return office.db.rows(q + " ORDER BY id", p)


def require(office, job_id, vendor_id, kind) -> int:
    office.require("waivers.edit", "waiver_requirement", vendor_id)
    with office.db.tx():
        rid = office.db.insert("waiver_requirements", job_id=job_id,
                               vendor_id=vendor_id, kind=kind)
        office.audit("create", "waiver_requirement", rid, None,
                     {"job": job_id, "vendor": vendor_id, "kind": kind})
    return rid


def required_kinds(office, job_id, vendor_id) -> list[str]:
    return [r["kind"] for r in office.db.rows(
        "SELECT kind FROM waiver_requirements WHERE vendor_id = ? AND "
        "(job_id = ? OR job_id IS NULL) AND deleted = 0", (vendor_id, job_id))]


def has_received(office, vendor_id, job_id, kind) -> bool:
    return bool(office.db.one(
        "SELECT id FROM waivers WHERE direction = 'received' AND vendor_id = ? "
        "AND (job_id = ? OR ? IS NULL) AND kind = ? AND status = 'Received' "
        "AND deleted = 0", (vendor_id, job_id, job_id, kind)))


def missing(office) -> list[dict]:
    out = []
    for r in office.db.rows("SELECT * FROM waiver_requirements WHERE deleted = 0"):
        if not has_received(office, r["vendor_id"], r["job_id"], r["kind"]):
            out.append(r)
    return out


BODY = {
    "conditional": ("On receipt by the claimant of a payment of {amount} from "
                    "{payer} for labor, services, equipment or material "
                    "furnished to the job named below through {through}, the "
                    "claimant releases its lien and payment-bond rights for "
                    "that work, to the extent of that payment. This release "
                    "takes effect only when the claimant actually receives "
                    "the payment."),
    "unconditional": ("The claimant has received a payment of {amount} from "
                      "{payer} for labor, services, equipment or material "
                      "furnished to the job named below through {through}, "
                      "and releases its lien and payment-bond rights for that "
                      "work to the extent of the payment received."),
}


def pdf(office, wid, path) -> str:
    """Neutral-wording waiver PDF (our own text); a statutory form must be
    attached and filled by the user instead."""
    import fitz
    w = office.db.get("waivers", wid)
    j = office.db.get("jobs", w["job_id"]) if w["job_id"] else None
    comp = office.company()
    doc = fitz.open()
    pg = doc.new_page(width=612, height=792)
    pg.insert_text((54, 64), KINDS[w["kind"]].upper(), fontsize=13,
                   fontname="hebo")
    pg.insert_textbox(fitz.Rect(54, 74, 558, 110), WARNING, fontsize=7.5,
                      color=(0.6, 0, 0))
    y = 124
    for k, v in (("Claimant", comp["name"] if w["direction"] == "issued"
                  else w["party"]),
                 ("Paying party", w["party"] if w["direction"] == "issued"
                  else comp["name"]),
                 ("Job", f"{j['number']} {j['name']}" if j else ""),
                 ("Through date", w["through"]),
                 ("Amount", cents.fmt(w["amount"])),
                 ("Exceptions", w["exceptions"] or "None")):
        pg.insert_text((54, y), f"{k}:", fontsize=10, fontname="hebo")
        pg.insert_text((170, y), str(v or ""), fontsize=10)
        y += 18
    body = BODY["conditional" if w["kind"].startswith("conditional")
                else "unconditional"].format(
        amount=cents.fmt(w["amount"]), payer=w["party"] or "the payer",
        through=w["through"])
    pg.insert_textbox(fitz.Rect(54, y + 10, 558, y + 140), body, fontsize=10)
    pg.insert_text((54, y + 190), "Signature: ______________________   "
                   "Date: ____________", fontsize=10)
    doc.set_metadata({"title": f"{KINDS[w['kind']]} - {j['name'] if j else ''}",
                      "producer": "QuantiSheet Back Office"})
    doc.save(path)
    doc.close()
    return path
