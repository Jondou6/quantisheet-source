"""Good / better / best quotes kept as records (1.2, #6).

A quote is a customer, a site and up to three choices (Good, Better,
Best), each built from pricebook tasks. Prices are copied onto the quote
when it is made, so a later pricebook change doesn't move a quote the
customer already has. A customer with an active agreement gets member
prices. When the customer signs one choice it becomes a flat-rate work
order; the other choices are kept on the quote for the record.

Money is Decimal kept as cent text. No network calls.
"""
import datetime as dt
from decimal import Decimal

from .. import dmoney
from . import files
from . import pricebook

FILE = "service_quotes.json"
KIND = "service_quotes"
CHOICES = ("Good", "Better", "Best")
STATUSES = ("open", "accepted", "declined")


class QuoteRecordError(ValueError):
    pass


def blank():
    return {"kind": KIND, "version": 1, "next": 1, "quotes": []}


def default_path():
    return files.path_for(FILE)


def load(path=None):
    return files.read(path or default_path(), KIND, blank)


def save(store, path=None):
    return files.write(path or default_path(), store)


def get(store, qid):
    for q in store["quotes"]:
        if q["id"] == qid or q["number"] == qid:
            return q
    raise QuoteRecordError("That quote isn't on file.")


def _line(task, member):
    return {"task_id": task["id"], "code": task.get("code") or "",
            "name": task["name"],
            "price": dmoney.text(pricebook.price_of(task, member)),
            "cost": dmoney.text(pricebook.task_cost(task)),
            "hours": task.get("hours") or "0.00",
            "labor_cost": task.get("labor_cost") or "0.00",
            "parts": [dict(p) for p in task.get("parts") or []]}


def _total(lines, key="price"):
    return dmoney.text(dmoney.cents(sum(
        (dmoney.D(x[key]) for x in lines), Decimal(0))))


def create(store, book, customer, site, choices, member=None,
           agreements=None, property_id="", equipment_id="", title="",
           notes="", when=None):
    """Make an open quote. `choices` is {"Good": [task ids], ...}; at least
    one choice must have a task. `member` None means: look it up in the
    agreements store (an active agreement for this customer or site)."""
    customer = files.txt(customer)
    site = files.txt(site, 300)
    if not customer:
        raise QuoteRecordError("Name the customer.")
    if not site:
        raise QuoteRecordError("Name the site.")
    try:
        made = files.iso_date(when or dt.date.today(), "Quote date",
                              blank_ok=False)
    except files.FileError as e:
        raise QuoteRecordError(str(e)) from e
    agr_no = ""
    if member is None:
        member = False
        if agreements is not None:
            from . import agreements as agr_api
            agr = agr_api.covers(agreements, customer, made, property_id)
            if agr is not None:
                member, agr_no = True, agr["number"]
    out = []
    for name in CHOICES:
        ids = list((choices or {}).get(name) or [])
        if not ids:
            continue
        try:
            tasks = [pricebook.get(book, i) for i in ids]
        except pricebook.PriceError as e:
            raise QuoteRecordError(str(e)) from e
        lines = [_line(t, member) for t in tasks]
        out.append({"name": name, "lines": lines, "total": _total(lines),
                    "cost": _total(lines, "cost")})
    if not out:
        raise QuoteRecordError("Put at least one task in Good, Better or "
                               "Best.")
    n = int(store.get("next") or 1)
    store["next"] = n + 1
    q = {"id": files.new_id(), "number": f"Q-{n:04d}", "date": made,
         "status": "open", "customer": customer, "site": site,
         "property_id": property_id or "", "equipment_id": equipment_id or "",
         "title": files.txt(title, 200) or "Your options",
         "notes": files.txt(notes, 2000), "member": bool(member),
         "agreement": agr_no, "choices": out, "chosen": "", "signed_by": "",
         "signed_on": "", "work_order_id": "", "work_order": "",
         "declined_on": "", "decline_reason": ""}
    store["quotes"].append(q)
    return q["id"]


def choice(q, name):
    for c in q["choices"]:
        if c["name"] == name:
            return c
    raise QuoteRecordError(f"This quote has no {name} choice.")


def _book(c):
    hours = sum((dmoney.D(x["hours"]) for x in c["lines"]), Decimal(0))
    cost = sum((dmoney.D(x["hours"]) * dmoney.D(x["labor_cost"])
                for x in c["lines"]), Decimal(0))
    rate = (cost / hours) if hours else Decimal(0)
    parts = [dict(p) for x in c["lines"] for p in x["parts"]]
    return {"hours": dmoney.text(dmoney.cents(hours)),
            "labor_cost": dmoney.text(dmoney.cents(rate)), "parts": parts}


def accept(store, qid, name, orders, records=None, signed_by="",
           when=None, tech="", scheduled=""):
    """The customer signed `name`. Opens a flat-rate work order at that
    choice's total and returns its id. A quote is accepted once."""
    q = get(store, qid)
    if q["status"] != "open":
        raise QuoteRecordError(f"{q['number']} is already {q['status']}.")
    c = choice(q, name)
    signed_by = files.txt(signed_by)
    if not signed_by:
        raise QuoteRecordError("Write who signed.")
    try:
        on = files.iso_date(when or dt.date.today(), "Signed", blank_ok=False)
    except files.FileError as e:
        raise QuoteRecordError(str(e)) from e
    from . import workorder as wo_api
    what = "; ".join(x["name"] for x in c["lines"])
    try:
        wo_id = wo_api.add(
            orders, records, customer=q["customer"], site=q["site"],
            property_id=q["property_id"] if records else "",
            equipment_id=q["equipment_id"] if records else "",
            complaint=f"{q['number']} {c['name']}: {what}", tech=tech,
            billing="flat", scheduled=scheduled, when=on)
    except wo_api.WorkOrderError as e:
        raise QuoteRecordError(str(e)) from e
    wo = wo_api.get(orders, wo_id)
    wo["property_id"] = wo["property_id"] or q["property_id"]
    wo["flat_price"] = c["total"]
    wo["member"] = q["member"]
    wo["task_id"] = c["lines"][0]["task_id"] if len(c["lines"]) == 1 else ""
    wo["task_name"] = f"{c['name']} ({q['number']}): {what}"[:300]
    wo["book"] = _book(c)
    wo["quote_id"] = q["id"]
    q.update(status="accepted", chosen=c["name"], signed_by=signed_by,
             signed_on=on, work_order_id=wo_id, work_order=wo["number"])
    return wo_id


def decline(store, qid, reason="", when=None):
    q = get(store, qid)
    if q["status"] != "open":
        raise QuoteRecordError(f"{q['number']} is already {q['status']}.")
    try:
        on = files.iso_date(when or dt.date.today(), "Declined",
                            blank_ok=False)
    except files.FileError as e:
        raise QuoteRecordError(str(e)) from e
    q.update(status="declined", declined_on=on,
             decline_reason=files.txt(reason, 500))
    return q


def option_quote(q):
    """The same quote in the shape estimating/quotes.py prints."""
    from ..estimating import quotes
    lines = []
    for c in q["choices"]:
        for x in c["lines"]:
            desc = x["name"] + (f" ({x['code']})" if x["code"] else "")
            lines.append({"id": x["task_id"], "desc": desc, "qty": 1,
                          "unit": "ea", "price": x["price"],
                          "cost": x["cost"], "tier": c["name"]})
    return quotes.service_option_quote(
        lines, title=q["title"], notes=q["notes"],
        tiers=[c["name"] for c in q["choices"]], selected_tier=q["chosen"])


def save_pdf(q, path, comp=None):
    return pricebook.save_quote(path, option_quote(q), comp=comp)


def for_customer(store, customer="", property_id=""):
    want = " ".join(str(customer or "").lower().split())
    out = []
    for q in store["quotes"]:
        if property_id and q.get("property_id") == property_id:
            out.append(q)
        elif not property_id and want and \
                " ".join(q["customer"].lower().split()) == want:
            out.append(q)
    return out


def summary(q):
    tot = ", ".join(f"{c['name']} {dmoney.fmt(c['total'])}"
                    for c in q["choices"])
    if q["status"] == "accepted":
        st = f"signed {q['chosen']} -> {q['work_order']}"
    elif q["status"] == "declined":
        st = "declined" + (f": {q['decline_reason']}"
                           if q["decline_reason"] else "")
    else:
        st = "open"
    return f"{q['number']} {q['date']} {tot} ({st})" + \
        (" member prices" if q["member"] else "")
