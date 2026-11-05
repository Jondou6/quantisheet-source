"""Service agreements on top of Equipment & Service Records.

An agreement is a customer, a price, how many visits a year, and the
renewal date. When a visit is due, a planned-maintenance work order is
opened. Renewal is warned at 90, 60 and 30 days. Profit is the agreement
price minus the time and parts used on its visits.

Money is Decimal. No network calls.
"""
import datetime as dt
from decimal import Decimal

from .. import dmoney
from ..estimating import service as records_api
from . import files

FILE = "service_agreements.json"
KIND = "service_agreements"
BANDS = (30, 60, 90)


class AgreementError(ValueError):
    pass


def blank():
    return {"kind": KIND, "version": 1, "next": 1, "agreements": []}


def default_path():
    return files.path_for(FILE)


def load(path=None):
    return files.read(path or default_path(), KIND, blank)


def save(store, path=None):
    return files.write(path or default_path(), store)


def _err(exc):
    if isinstance(exc, files.FileError):
        raise AgreementError(str(exc)) from exc
    raise exc


def get(store, aid):
    for agr in store["agreements"]:
        if agr["id"] == aid:
            return agr
    raise AgreementError("That agreement isn't on file.")


def interval(visits):
    """(step, unit) between planned visits. Months when the year divides
    evenly, otherwise days."""
    visits = int(visits)
    if 12 % visits == 0:
        return 12 // visits, "months"
    return max(int(round(365 / visits)), 1), "days"


def add(store, customer, price, visits_per_year, renewal, property_id="",
        site="", start="", notes="", records=None, status="active"):
    try:
        visits = int(str(visits_per_year).strip())
    except (TypeError, ValueError):
        raise AgreementError("Visits per year must be a whole number.")
    if visits < 1 or visits > 52:
        raise AgreementError("Visits per year must be from 1 to 52.")
    try:
        renewal_s = files.iso_date(renewal, "Renewal", blank_ok=False)
        if start:
            start_s = files.iso_date(start, "Start", blank_ok=False)
        else:
            start_s = records_api.add_interval(
                dt.date.fromisoformat(renewal_s), -1, "years").isoformat()
        price_s = files.money(price, "Agreement price")
    except files.FileError as e:
        _err(e)
    if dt.date.fromisoformat(start_s) >= dt.date.fromisoformat(renewal_s):
        raise AgreementError("The renewal date must be after the start.")
    if property_id:
        prop = records_api.find(records, property_id) if records else None
        if not prop or "customer" not in prop:
            raise AgreementError("That site isn't in the service records.")
        customer = customer or prop.get("customer") or prop.get("name")
        site = site or prop.get("name") or ""
    customer = files.txt(customer)
    site = files.txt(site, 300)
    if not customer:
        raise AgreementError("Name the customer.")
    if not site:
        raise AgreementError("Name the site.")
    n = int(store.get("next") or 1)
    store["next"] = n + 1
    agr = {"id": files.new_id(), "number": f"SA-{n:04d}",
           "customer": customer, "site": site, "property_id": property_id or "",
           "price": price_s, "visits_per_year": visits, "start": start_s,
           "renewal": renewal_s, "notes": files.txt(notes, 1000),
           "status": "cancelled" if status == "cancelled" else "active"}
    store["agreements"].append(agr)
    return agr["id"]


def cancel(store, aid):
    agr = get(store, aid)
    agr["status"] = "cancelled"
    return agr


def visit_dates(agr):
    """The planned visit dates in the current term, before renewal."""
    start = dt.date.fromisoformat(agr["start"])
    renewal = dt.date.fromisoformat(agr["renewal"])
    step, unit = interval(agr["visits_per_year"])
    out, d = [], start
    while d < renewal and len(out) < int(agr["visits_per_year"]):
        out.append(d)
        d = records_api.add_interval(d, step, unit)
    return out


def _existing_visits(orders):
    return {(wo.get("agreement_id"), wo.get("pm_visit"))
            for wo in orders.get("orders") or []}


def create_due_work_orders(agreements, orders, records=None, today=None):
    """Open a planned-maintenance work order for each visit that is due
    and does not already have one. Returns the new work-order ids."""
    from . import workorder
    today = today or dt.date.today()
    if isinstance(today, str):
        today = dt.date.fromisoformat(today)
    have = _existing_visits(orders)
    created = []
    for agr in agreements["agreements"]:
        if agr.get("status") == "cancelled":
            continue
        for d in visit_dates(agr):
            if d > today:
                continue
            key = (agr["id"], d.isoformat())
            if key in have:
                continue
            wo_id = workorder.add(
                orders, records, customer=agr["customer"], site=agr["site"],
                property_id=agr.get("property_id") or "",
                complaint=f"Planned maintenance visit ({agr['number']})",
                billing="agreement", agreement_id=agr["id"],
                scheduled=d.isoformat(), pm_visit=d.isoformat(),
                call_type="pm", when=today)
            have.add(key)
            created.append(wo_id)
    return created


def renewal_warnings(store, today=None):
    """Agreements inside 90 days of renewal (or past it).

    `band` is 30, 60, 90, or "overdue": the tightest window the date is in.
    """
    today = today or dt.date.today()
    if isinstance(today, str):
        today = dt.date.fromisoformat(today)
    out = []
    for agr in store["agreements"]:
        if agr.get("status") == "cancelled":
            continue
        renewal = dt.date.fromisoformat(agr["renewal"])
        days = (renewal - today).days
        if days < 0:
            band = "overdue"
        elif days <= 30:
            band = 30
        elif days <= 60:
            band = 60
        elif days <= 90:
            band = 90
        else:
            continue
        out.append({"id": agr["id"], "number": agr["number"],
                    "customer": agr["customer"], "site": agr["site"],
                    "renewal": agr["renewal"], "days_left": days, "band": band})
    return sorted(out, key=lambda r: r["days_left"])


def covers(store, customer, today=None, property_id=""):
    """The active agreement for this customer or site, or None."""
    today = today or dt.date.today()
    if isinstance(today, str):
        today = dt.date.fromisoformat(today)
    want = " ".join(str(customer or "").lower().split())
    for agr in store["agreements"]:
        if agr.get("status") == "cancelled":
            continue
        start = dt.date.fromisoformat(agr["start"])
        renewal = dt.date.fromisoformat(agr["renewal"])
        if not (start <= today <= renewal):
            continue
        if property_id and agr.get("property_id") == property_id:
            return agr
        if want and " ".join(agr["customer"].lower().split()) == want:
            return agr
    return None


def profit(agr, orders):
    """Agreement price versus the time and parts used on its tickets."""
    from . import workorder
    if isinstance(agr, str):
        raise AgreementError("Pass the agreement record and the work orders.")
    cost = Decimal("0.00")
    for wo in orders.get("orders") or []:
        if wo.get("agreement_id") != agr["id"]:
            continue
        cost += workorder.ticket_profit(orders, wo)["cost"]
    price = dmoney.cents(agr["price"])
    return {"price": price, "cost": cost, "profit": price - cost}


def summary_pdf(store, orders, path, comp=None, today=None):
    """One page the office can print: price, visits, renewal, profit."""
    from .pdfdoc import Sheet
    today = today or dt.date.today()
    sheet = Sheet("Service agreements", comp)
    warnings = {w["id"]: w for w in renewal_warnings(store, today)}
    sheet.section("01", "Agreements")
    for agr in store["agreements"]:
        sheet.need(36)
        got = profit(agr, orders)
        warn = warnings.get(agr["id"])
        band = ""
        if warn:
            band = ("Renewal overdue" if warn["band"] == "overdue"
                    else f"Renewal inside {warn['band']} days")
        sheet.y += 14
        sheet.text(36, sheet.y, f"{agr['number']}  {agr['customer']}", 10, True)
        sheet.y += 12
        sheet.text(36, sheet.y,
                   f"{agr['site']}    {agr['visits_per_year']} visits / year"
                   f"    renews {agr['renewal']}    {band}", 8)
        sheet.y += 12
        sheet.text(36, sheet.y,
                   f"Price {dmoney.fmt(got['price'])}    "
                   f"Time and parts {dmoney.fmt(got['cost'])}    "
                   f"Profit {dmoney.fmt(got['profit'])}", 9)
    return sheet.save(path)
