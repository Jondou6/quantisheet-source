"""Sales and use tax (P2-15; also runs in export mode).

Back Office ships no rates or rules as law: the user enters tax codes and
taxable flags, and the screen says to confirm them with a CPA. Taxes are
computed half up, posted to the code's liability account and reported by
jurisdiction. 'Record tax payment' only records it: no file, no filing.
"""
from __future__ import annotations

from . import cents, clock, ledger

CPA_NOTE = ("Construction tax treatment differs by state and contract type. "
            "Back Office ships no tax rates or rules: confirm every code and "
            "taxable flag with your CPA. Back Office does not file returns.")
KINDS = ("sales", "use")
LINE_KINDS = ("labor", "material", "equipment", "subcontract", "markup",
              "other")


class TaxError(ValueError):
    pass


def add_code(office, name, jurisdiction, rate, kind="sales",
             effective_from="", effective_to="", account_id=None) -> int:
    office.require("tax.edit", "tax_code", name)
    if kind not in KINDS:
        raise TaxError("kind must be sales or use")
    r = cents.D(rate)
    if r < 0 or r > 100:
        raise TaxError("rate must be a percent between 0 and 100")
    acct = account_id or ledger.default_account(
        office, "sales_tax" if kind == "sales" else "use_tax")
    with office.db.tx():
        tid = office.db.insert("tax_codes", name=name,
                               jurisdiction=jurisdiction, rate=str(r),
                               kind=kind, effective_from=effective_from,
                               effective_to=effective_to, account_id=acct)
        office.audit("create", "tax_code", tid, None,
                     {"name": name, "rate": str(r), "kind": kind})
    return tid


def code(office, tid) -> dict:
    return office.db.get("tax_codes", tid)


def tax_on(office, tid, taxable_c, date=None) -> int:
    c = code(office, tid)
    d = str(date or clock.today())
    if (c["effective_from"] and d < c["effective_from"]) or \
            (c["effective_to"] and d > c["effective_to"]):
        raise TaxError(f"tax code {c['name']} is not in effect on {d}")
    return cents.pct_of(taxable_c, c["rate"])


def record(office, doc_type, doc_id, tid, taxable_c, tax_c, date,
           entry_id=None) -> int:
    return office.db.insert("tax_lines", doc_type=doc_type, doc_id=doc_id,
                            tax_code_id=tid, taxable=taxable_c, tax=tax_c,
                            date=str(date), entry_id=entry_id)


def use_tax_lines(office, inv, ap_lines) -> list[dict]:
    """Use tax on material lines of a bill the vendor charged no tax on:
    debit the line's cost account, credit Use tax payable."""
    c = code(office, inv["use_tax_code"])
    if c["kind"] != "use":
        raise TaxError(f"{c['name']} is not a use tax code")
    out = []
    taxable = 0
    for ln in ap_lines:
        if (ln["category"] or "") != "M":
            continue
        t = cents.pct_of(ln["amount"], c["rate"])
        taxable += ln["amount"]
        acct = ln["account_id"] or ledger.cost_account(
            office, "M", ln["cost_code"], inv["vendor_id"], ln["job_id"])
        out.append({"account": acct, "debit": t, "job_id": ln["job_id"],
                    "cost_code": ln["cost_code"], "category": "M",
                    "memo": f"Use tax {c['name']}"})
        out.append({"account": c["account_id"], "credit": t,
                    "job_id": ln["job_id"], "memo": f"Use tax {c['name']}"})
    tot = sum(x.get("debit", 0) for x in out)
    if tot:
        record(office, "ap_invoice", inv["id"], c["id"], taxable, tot,
               inv["gl_date"])
    return out


def liability(office, date_from, date_to) -> list[dict]:
    """Per jurisdiction and code: tax posted in the period less payments
    recorded; equals the sum of the tax postings."""
    out = {}
    for t in office.db.rows("SELECT t.*, c.name, c.jurisdiction, c.kind, "
                            "c.account_id FROM tax_lines t JOIN tax_codes c "
                            "ON c.id = t.tax_code_id WHERE t.date BETWEEN ? "
                            "AND ? AND t.deleted = 0",
                            (str(date_from), str(date_to))):
        k = (t["jurisdiction"], t["name"])
        r = out.setdefault(k, {"jurisdiction": t["jurisdiction"],
                               "code": t["name"], "kind": t["kind"],
                               "taxable": 0, "tax": 0, "paid": 0,
                               "account_id": t["account_id"],
                               "code_id": t["tax_code_id"]})
        if t["doc_type"] == "tax_payment":
            r["paid"] += -t["tax"]
        else:
            r["taxable"] += t["taxable"]
            r["tax"] += t["tax"]
    for r in out.values():
        r["due"] = r["tax"] - r["paid"]
    return sorted(out.values(), key=lambda r: (r["jurisdiction"], r["code"]))


def record_payment(office, tid, amount_c, date, bank_number="1000",
                   reference="") -> int:
    """Records a tax payment made outside Back Office: debit the liability,
    credit the bank. No file and no filing."""
    office.require("tax.edit", "tax_code", tid)
    c = code(office, tid)
    with office.db.tx():
        eid = ledger.post(office, date,
                          [{"account": c["account_id"], "debit": amount_c},
                           {"account": bank_number, "credit": amount_c}],
                          "tax_payment", tid,
                          f"Tax payment {c['name']} {reference}".strip())
        record(office, "tax_payment", eid, tid, 0, -amount_c, date, eid)
    return eid
