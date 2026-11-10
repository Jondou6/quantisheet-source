"""One service ticket per call.

Customer, site and unit come from Equipment & Service Records. The ticket
holds the complaint, the technician, time, parts and photos. Print a
fill-in PDF, then close it: closing requires notes, time and parts.
Close and invoice writes the invoice (time and material, or a flat-rate
task) in the same step and keeps the profit on the ticket.

Money is Decimal. No network calls.
"""
import datetime as dt
import os
from decimal import Decimal

from .. import dmoney
from . import files

FILE = "service_work_orders.json"
KIND = "service_work_orders"
BILLING = ("tm", "flat", "agreement")
CALL_TYPES = ("call", "pm")


class WorkOrderError(ValueError):
    pass


def blank():
    return {"kind": KIND, "version": 1, "next": 1, "invoice_next": 1,
            "settings": {"labor_bill": "0.00", "labor_cost": "0.00"},
            "techs": [], "orders": [], "invoices": []}


def default_path():
    return files.path_for(FILE)


def load(path=None):
    return files.read(path or default_path(), KIND, blank)


def save(store, path=None):
    return files.write(path or default_path(), store)


def _err(exc):
    if isinstance(exc, files.FileError):
        raise WorkOrderError(str(exc)) from exc
    raise exc


def get(store, wo_id):
    for wo in store["orders"]:
        if wo["id"] == wo_id:
            return wo
    raise WorkOrderError("That work order isn't on file.")


def _open(store, wo_id):
    wo = get(store, wo_id)
    if wo["status"] != "open":
        raise WorkOrderError(f"{wo['number']} is closed.")
    return wo


def set_rates(store, labor_bill, labor_cost):
    try:
        store["settings"] = {
            "labor_bill": files.money(labor_bill, "Labor price"),
            "labor_cost": files.money(labor_cost, "Labor cost"),
        }
    except files.FileError as e:
        _err(e)
    return store["settings"]


def _property(records, pid):
    from ..estimating import service
    rec = service.find(records, pid) if records is not None else None
    if not rec or "customer" not in rec:
        raise WorkOrderError("That site isn't in the service records.")
    return rec


def _equipment(records, eid, property_id):
    from ..estimating import service
    rec = service.find(records, eid) if records is not None else None
    if not rec or "kind" not in rec or "serial" not in rec:
        raise WorkOrderError("That unit isn't in the service records.")
    if property_id and rec.get("property") != property_id:
        raise WorkOrderError("That unit is not at this site.")
    return rec


def _unit_text(eq):
    return " ".join(p for p in (eq.get("kind"), eq.get("make"),
                                eq.get("model"), eq.get("serial")) if p)


def add(store, records=None, customer="", site="", address="",
        property_id="", equipment_id="", complaint="", tech="",
        billing="tm", agreement_id="", scheduled="", pm_visit="",
        call_type="call", when=None):
    """Open one ticket. Returns its id."""
    try:
        if property_id:
            prop = _property(records, property_id)
            customer = customer or prop.get("customer") or prop.get("name")
            site = site or prop.get("name") or ""
            address = address or prop.get("address") or ""
        customer = files.txt(customer)
        site = files.txt(site, 300)
        if not customer:
            raise WorkOrderError("Name the customer.")
        if not site:
            raise WorkOrderError("Name the site.")
        complaint = files.txt(complaint, 1000)
        if not complaint:
            raise WorkOrderError("Write the complaint.")
        if billing not in BILLING:
            raise WorkOrderError("Billing is time and material, flat-rate "
                                 "or agreement.")
        if call_type not in CALL_TYPES:
            raise WorkOrderError("A ticket is a call or a planned visit.")
        unit, eq_id = "", ""
        if equipment_id:
            eq = _equipment(records, equipment_id, property_id)
            unit, eq_id = _unit_text(eq), eq["id"]
        opened = files.iso_date(when or dt.date.today(), "Opened",
                                blank_ok=False)
        scheduled = files.iso_date(scheduled, "Scheduled")
        pm_visit = files.iso_date(pm_visit, "Visit date")
    except files.FileError as e:
        _err(e)
    n = int(store.get("next") or 1)
    store["next"] = n + 1
    wo = {"id": files.new_id(), "number": f"WO-{n:04d}",
          "opened": opened, "status": "open", "customer": customer,
          "site": site, "address": files.txt(address, 300),
          "property_id": property_id or "", "equipment_id": eq_id,
          "unit": unit, "complaint": complaint,
          "tech": files.txt(tech), "billing": billing,
          "agreement_id": agreement_id or "", "scheduled": scheduled,
          "pm_visit": pm_visit, "call_type": call_type,
          "flat_price": "", "task_id": "", "task_name": "", "member": False,
          "book": None, "time": [], "parts": [], "parts_recorded": False,
          "photos": [], "notes": "", "closed": "", "invoice_id": ""}
    prev = callback_of(store, wo)
    if prev is not None:
        wo["callback_of"] = prev["number"]
    store["orders"].append(wo)
    if wo["tech"] and wo["tech"] not in store["techs"]:
        store["techs"].append(wo["tech"])
    return wo["id"]


CALLBACK_DAYS = 30


def callback_days():
    """QW6 (1.2, Nov 5): a call on the same unit (or, with no unit, the
    same site) within this many days of the last visit is a callback.
    Setting service_callback_days."""
    from .. import settings
    try:
        v = settings.get("service_callback_days")
        n = CALLBACK_DAYS if v in (None, "") else int(v)
    except (TypeError, ValueError):
        n = CALLBACK_DAYS
    return max(n, 0)


def callback_of(store, wo, days=None):
    """The earlier ticket this one comes back to, or None. Planned
    maintenance visits are never callbacks."""
    days = callback_days() if days is None else days
    if not days or wo.get("call_type") == "pm":
        return None
    try:
        opened = dt.date.fromisoformat(wo["opened"])
    except (KeyError, ValueError):
        return None
    best = None
    for o in store.get("orders", []):
        if o is wo or o["id"] == wo.get("id"):
            continue
        if wo.get("equipment_id"):
            if o.get("equipment_id") != wo["equipment_id"]:
                continue
        elif not (wo.get("property_id") and
                  o.get("property_id") == wo["property_id"]) and \
                not (o.get("site") and o.get("site") == wo.get("site") and
                     o.get("customer") == wo.get("customer")):
            continue
        last = o.get("closed") or o.get("opened")
        try:
            d = dt.date.fromisoformat(str(last)[:10])
        except ValueError:
            continue
        if 0 <= (opened - d).days <= days and \
                (best is None or d > dt.date.fromisoformat(
                    str(best.get("closed") or best.get("opened"))[:10])):
            best = o
    return best


def add_time(store, wo_id, tech, hours, when=None, note="",
             bill=None, cost=None):
    wo = _open(store, wo_id)
    try:
        hrs = files.qty(hours, "Hours")
        when = files.iso_date(when or dt.date.today(), "Date", blank_ok=False)
        rates = store["settings"]
        bill_s = files.money(rates["labor_bill"] if bill is None else bill,
                             "Labor price")
        cost_s = files.money(rates["labor_cost"] if cost is None else cost,
                             "Labor cost")
    except files.FileError as e:
        _err(e)
    who = files.txt(tech) or wo["tech"]
    if not who:
        raise WorkOrderError("Name the technician on this time.")
    row = {"id": files.new_id(), "tech": who, "hours": hrs, "date": when,
           "note": files.txt(note, 300), "bill": bill_s, "cost": cost_s}
    wo["time"].append(row)
    if not wo["tech"]:
        wo["tech"] = who
    return row


def mark_parts(store, wo_id, parts=()):
    """Record the parts used. An empty list means none were used."""
    wo = _open(store, wo_id)
    wo["parts"] = []
    for p in parts:
        add_part(store, wo_id, p.get("desc", ""), p.get("qty", "1"),
                 p.get("unit", "ea"), p.get("cost", "0"), p.get("price"),
                 sku=p.get("sku", ""))
    wo["parts_recorded"] = True
    return wo["parts"]


def add_part(store, wo_id, desc, qty, unit="ea", cost="0", price=None,
             sku="", truck_store=None, truck_id=""):
    """Add a part. With a truck, the quantity comes off that truck."""
    wo = _open(store, wo_id)
    try:
        q = files.qty(qty, "Quantity")
    except files.FileError as e:
        _err(e)
    if truck_id:
        if truck_store is None:
            raise WorkOrderError("Pick the truck the part comes off.")
        from . import truckstock
        try:
            line = truckstock.issue(truck_store, truck_id, sku or desc, q,
                                    work_order_id=wo_id)
        except truckstock.TruckError as e:
            raise WorkOrderError(str(e)) from e
    else:
        try:
            if not files.txt(desc):
                raise WorkOrderError("Name the part.")
            line = {"sku": files.txt(sku, 40), "desc": files.txt(desc),
                    "qty": q, "unit": files.txt(unit, 20) or "ea",
                    "cost": files.money(cost, "Part cost"),
                    "price": files.money(cost if price is None else price,
                                         "Part price"),
                    "truck_id": "", "part_id": "", "issue_id": ""}
        except files.FileError as e:
            _err(e)
    line["id"] = files.new_id()
    wo["parts"].append(line)
    wo["parts_recorded"] = True
    return line


def no_parts(store, wo_id):
    wo = _open(store, wo_id)
    if wo["parts"]:
        raise WorkOrderError("This ticket already has parts.")
    wo["parts_recorded"] = True
    return wo


def add_photo(store, wo_id, path, caption=""):
    wo = _open(store, wo_id)
    if not path or not os.path.isfile(path):
        raise WorkOrderError("Pick a photo file.")
    row = {"path": os.path.abspath(path), "caption": files.txt(caption, 200)}
    wo["photos"].append(row)
    return row


def set_notes(store, wo_id, notes):
    wo = _open(store, wo_id)
    wo["notes"] = files.txt(notes, 4000)
    return wo


def apply_task(store, wo_id, task, member=False):
    """Bill the ticket at the flat-rate task price (member price when asked)."""
    wo = _open(store, wo_id)
    if not task or not task.get("id"):
        raise WorkOrderError("Pick a flat-rate task.")
    price = task["member_price"] if member else task["customer_price"]
    wo["billing"] = "flat"
    wo["member"] = bool(member)
    wo["task_id"] = task["id"]
    wo["task_name"] = task.get("name") or "Flat-rate task"
    wo["flat_price"] = price
    wo["book"] = {"hours": task.get("hours") or "0",
                  "labor_cost": task.get("labor_cost") or "0.00",
                  "parts": [dict(p) for p in task.get("parts") or []]}
    return wo


def use_book(store, wo_id, tech="", truck_store=None, truck_id=""):
    """Put the task's built-in hours and parts on the ticket."""
    wo = _open(store, wo_id)
    book = wo.get("book") or None
    if not book:
        raise WorkOrderError("This ticket has no flat-rate task.")
    if wo["time"] or wo["parts"]:
        raise WorkOrderError("Time or parts are already on this ticket.")
    who = files.txt(tech) or wo["tech"] or "Technician"
    hours = dmoney.D(book.get("hours") or 0)
    if hours > 0:
        add_time(store, wo_id, who, hours, cost=book.get("labor_cost") or "0")
    for p in book.get("parts") or []:
        if truck_id and p.get("sku"):
            add_part(store, wo_id, p.get("desc") or p["sku"], p["qty"],
                     p.get("unit") or "ea", sku=p["sku"],
                     truck_store=truck_store, truck_id=truck_id)
        else:
            add_part(store, wo_id, p.get("desc") or "Part", p["qty"],
                     p.get("unit") or "ea", p.get("cost") or "0",
                     p.get("cost") or "0", sku=p.get("sku") or "")
    return wo


def _sum(rows, qty_key, each_key):
    total = Decimal("0.00")
    for row in rows:
        total += dmoney.cents(dmoney.D(row[qty_key]) * dmoney.D(row[each_key]))
    return total


def ticket_profit(store, wo):
    """Price, cost and profit for one ticket. Amounts are Decimal."""
    if isinstance(wo, str):
        wo = get(store, wo)
    labor_cost = _sum(wo["time"], "hours", "cost")
    labor_price = _sum(wo["time"], "hours", "bill")
    part_cost = _sum(wo["parts"], "qty", "cost")
    part_price = _sum(wo["parts"], "qty", "price")
    cost = labor_cost + part_cost
    if wo["billing"] == "flat":
        price = dmoney.cents(wo.get("flat_price") or 0)
    elif wo["billing"] == "agreement":
        price = Decimal("0.00")
    else:
        price = labor_price + part_price
    return {"price": price, "cost": cost, "profit": price - cost,
            "billing": wo["billing"]}


def _ready(wo):
    if not str(wo.get("notes") or "").strip():
        raise WorkOrderError("Add notes before closing.")
    if not any(dmoney.D(t["hours"]) > 0 for t in wo["time"]):
        raise WorkOrderError("Add time before closing.")
    if not wo.get("parts_recorded"):
        raise WorkOrderError("Add parts before closing. Use no-parts when "
                             "none were used.")
    if wo["billing"] == "flat" and dmoney.D(wo.get("flat_price") or 0) <= 0:
        raise WorkOrderError("Set the flat-rate price before closing.")


def close(store, wo_id, notes=None, when=None):
    wo = _open(store, wo_id)
    if notes is not None:
        wo["notes"] = files.txt(notes, 4000)
    _ready(wo)
    wo["status"] = "closed"
    try:
        wo["closed"] = files.iso_date(when or dt.date.today(), "Closed",
                                      blank_ok=False)
    except files.FileError as e:
        _err(e)
    return wo


def invoice_lines(store, wo):
    if isinstance(wo, str):
        wo = get(store, wo)
    if wo["billing"] == "flat":
        amount = dmoney.text(dmoney.cents(wo.get("flat_price") or 0))
        return [{"desc": wo.get("task_name") or "Flat-rate task",
                 "qty": "1", "unit": "ea", "price": amount, "amount": amount}]
    if wo["billing"] == "agreement":
        return [{"desc": "Planned maintenance, covered by the service "
                         "agreement",
                 "qty": "1", "unit": "ea", "price": "0.00",
                 "amount": "0.00"}]
    lines = []
    for t in wo["time"]:
        amount = dmoney.text(dmoney.cents(dmoney.D(t["hours"]) *
                                          dmoney.D(t["bill"])))
        lines.append({"desc": f"Labor, {t['tech']}", "qty": t["hours"],
                      "unit": "hr", "price": t["bill"], "amount": amount})
    for p in wo["parts"]:
        amount = dmoney.text(dmoney.cents(dmoney.D(p["qty"]) *
                                          dmoney.D(p["price"])))
        lines.append({"desc": p["desc"], "qty": p["qty"], "unit": p["unit"],
                      "price": p["price"], "amount": amount})
    return lines


# ---- sales tax, card fee, member discount (Jon via Chief, Nov 7) -----------
# The rates are percents kept as decimal strings. Each invoice keeps the
# rates it was made with, so changing a default never changes a past
# invoice. Every amount is in cents, rounded half-up.

TAX_RATES = ["0"] + [f"{6 + k / 2:.1f}" for k in range(9)]   # 0, 6.0-10.0
CARD_FEE_PCT = "3.5"


def tax_rate_text(rate):
    r = dmoney.D(rate or 0)
    return "No tax (0%)" if r == 0 else f"{r:.1f}%"


def default_tax_rate():
    """Settings > service_tax_rate: one of TAX_RATES (0 when unset)."""
    from .. import settings
    v = str(settings.get("service_tax_rate", "0") or "0").strip()
    return v if v in TAX_RATES else "0"


def card_fee_pct():
    """Settings > service_card_fee_pct, 3.5 when unset (0-10)."""
    from .. import settings
    try:
        v = dmoney.D(settings.get("service_card_fee_pct", CARD_FEE_PCT))
    except Exception:                                     # noqa: BLE001
        v = dmoney.D(CARD_FEE_PCT)
    if v < 0 or v > 10:
        v = dmoney.D(CARD_FEE_PCT)
    return f"{v.normalize():f}"


def set_payment(store, wo_id, tax_rate=None, card=None):
    """The tax rate and card choice for this ticket's invoice."""
    wo = get(store, wo_id)
    if tax_rate is not None:
        r = str(tax_rate).strip().rstrip("%").strip()
        r = "0" if r in ("", "0", "0.0", "No tax") else r
        if r not in TAX_RATES:
            try:
                r = f"{dmoney.D(r):.1f}"
            except Exception:                             # noqa: BLE001
                pass
        if r not in TAX_RATES:
            raise WorkOrderError("Pick a sales tax rate from the list "
                                 "(0%, or 6% to 10% in half-percent steps).")
        wo["tax_rate"] = r
    if card is not None:
        wo["card"] = bool(card)
    return wo


def _pct_of(amount, pct):
    return dmoney.cents(dmoney.D(amount) * dmoney.D(pct) / 100)


def member_discount(wo, agreements_store=None, today=None):
    """(percent, agreement number) when this ticket is a repair for a
    customer with an active service agreement, else (None, None). Planned
    visits are covered by the agreement; a flat-rate task already priced
    at the member price isn't discounted twice."""
    if wo.get("billing") != "tm" or wo.get("call_type") == "pm" or \
            wo.get("agreement_id") or wo.get("member"):
        return None, None
    from . import agreements
    try:
        st = agreements_store if agreements_store is not None else \
            agreements.load()
    except Exception:                                     # noqa: BLE001
        return None, None
    agr = agreements.covers(st, wo.get("customer"), today or wo.get(
        "closed") or None, wo.get("property_id") or "")
    if agr is None:
        return None, None
    pct = agr.get("discount_pct")
    if pct in (None, ""):
        pct = agreements.defaults()["discount_pct"]
    pct = dmoney.D(pct)
    if pct <= 0:
        return None, None
    return f"{pct.normalize():f}", agr["number"]


def invoice_money(store, wo, agreements_store=None):
    """Lines and amounts for the invoice: the work, then the member
    discount, sales tax and card fee each as a line of its own."""
    totals = ticket_profit(store, wo)
    base = invoice_lines(store, wo)
    sub = totals["price"]
    extra = []
    pct, agr_no = member_discount(wo, agreements_store)
    disc = _pct_of(sub, pct) if pct else dmoney.D("0.00")
    if disc:
        extra.append({"desc": f"Member discount ({pct}%, agreement "
                              f"{agr_no})", "qty": "1", "unit": "ea",
                      "price": dmoney.text(-disc), "amount":
                      dmoney.text(-disc), "kind": "discount"})
    taxable = sub - disc
    rate = wo.get("tax_rate")
    rate = default_tax_rate() if rate in (None, "") else str(rate)
    tax = _pct_of(taxable, rate)
    if tax:
        extra.append({"desc": f"Sales tax ({tax_rate_text(rate)})",
                      "qty": "1", "unit": "ea", "price": dmoney.text(tax),
                      "amount": dmoney.text(tax), "kind": "tax"})
    card = bool(wo.get("card"))
    fee_pct = card_fee_pct() if card else "0"
    fee = _pct_of(taxable + tax, fee_pct) if card else dmoney.D("0.00")
    if fee:
        extra.append({"desc": f"Credit card service fee ({fee_pct}%)",
                      "qty": "1", "unit": "ea", "price": dmoney.text(fee),
                      "amount": dmoney.text(fee), "kind": "card_fee"})
    return {"lines": base + extra, "subtotal": sub, "discount": disc,
            "discount_pct": pct or "", "agreement": agr_no or "",
            "tax_rate": rate, "tax": tax, "card": card,
            "card_fee_pct": fee_pct if card else "", "card_fee": fee,
            "total": taxable + tax + fee, "cost": totals["cost"],
            "profit": taxable - totals["cost"]}


def create_invoice(store, wo_id, when=None, agreements_store=None):
    wo = get(store, wo_id)
    if wo["status"] != "closed":
        raise WorkOrderError("Close the ticket before invoicing.")
    if wo.get("invoice_id"):
        raise WorkOrderError("This ticket already has an invoice.")
    m = invoice_money(store, wo, agreements_store)
    n = int(store.get("invoice_next") or 1)
    store["invoice_next"] = n + 1
    t = dmoney.text
    inv = {"id": files.new_id(), "number": f"INV-{n:04d}",
           "work_order_id": wo_id, "work_order_number": wo["number"],
           "date": files.iso_date(when or wo["closed"] or dt.date.today(),
                                  "Invoice date", blank_ok=False),
           "customer": wo["customer"], "site": wo["site"],
           "address": wo.get("address") or "", "billing": wo["billing"],
           "lines": m["lines"], "terms_days": terms_days(),
           "subtotal": t(m["subtotal"]), "discount": t(m["discount"]),
           "discount_pct": m["discount_pct"], "agreement": m["agreement"],
           "tax_rate": m["tax_rate"], "tax": t(m["tax"]),
           "card": m["card"], "card_fee_pct": m["card_fee_pct"],
           "card_fee": t(m["card_fee"]),
           "total": t(m["total"]), "cost": t(m["cost"]),
           "profit": t(m["profit"])}
    store["invoices"].append(inv)
    wo["invoice_id"] = inv["id"]
    return inv


def close_and_invoice(store, wo_id, notes=None, when=None, pdf_path=None,
                      comp=None, write_pdf=True, tax_rate=None, card=None,
                      agreements_store=None):
    """Close the ticket and write its invoice. One step."""
    if tax_rate is not None or card is not None:
        set_payment(store, wo_id, tax_rate, card)
    close(store, wo_id, notes=notes, when=when)
    inv = create_invoice(store, wo_id, when=when,
                         agreements_store=agreements_store)
    if write_pdf:
        path = pdf_path or files.path_for(f"{inv['number']}.pdf")
        invoice_pdf(store, inv["id"], path, comp=comp)
        inv["pdf"] = path
    return inv


def _money_lines(sheet, lines, total, label="Total"):
    sheet.section("02", "Charges")
    y0 = sheet.y + 4
    sheet.label(36, y0, "Description")
    sheet.label(360, y0, "Qty")
    sheet.label(420, y0, "Price")
    sheet.label(500, y0, "Amount")
    sheet.y = y0 + 6
    for ln in lines:
        sheet.need(16)
        sheet.y += 14
        sheet.text(36, sheet.y, ln["desc"][:64], 9)
        sheet.text(360, sheet.y, f"{ln['qty']} {ln['unit']}", 8)
        sheet.text(420, sheet.y, dmoney.fmt(ln["price"]), 8)
        sheet.text(500, sheet.y, dmoney.fmt(ln["amount"]), 9, True)
    sheet.y += 8
    sheet.rule()
    sheet.y += 16
    sheet.text(400 if label == "Total" else 330, sheet.y, label, 11, True)
    sheet.text(500, sheet.y, dmoney.fmt(total), 11, True)


def terms_days():
    """Days to pay a service invoice (setting service_invoice_terms_days,
    30 when unset; 0 means due on receipt)."""
    from .. import settings
    try:
        n = int(settings.get("service_invoice_terms_days", 30))
    except (TypeError, ValueError):
        n = 30
    return max(0, min(n, 365))


def due_date(inv, days=None):
    days = terms_days() if days is None else days
    try:
        d = dt.date.fromisoformat(str(inv.get("date") or "")[:10])
    except ValueError:
        return ""
    return (d + dt.timedelta(days=days)).isoformat()


def terms_text(days=None):
    days = terms_days() if days is None else days
    return "Due on receipt" if days == 0 else f"Net {days}"


def invoice_pdf(store, invoice_id, path, comp=None):
    """The customer invoice: bill-to, invoice date, terms and due date,
    charges, a sales tax line and remit-to (Chief's estimator test, Nov 7:
    the hh2 copy had no due date, terms, remit-to or tax line)."""
    from .pdfdoc import Sheet, company
    inv = next((i for i in store["invoices"] if i["id"] == invoice_id), None)
    if inv is None:
        raise WorkOrderError("That invoice isn't on file.")
    sheet = Sheet("Invoice", comp, subtitle=inv["number"])
    sheet.section("01", "Bill to")
    y = sheet.y + 12
    sheet.text(36, y, inv["customer"], 11, True)
    sheet.text(36, y + 14, inv["site"], 9)
    if inv.get("address"):
        sheet.text(36, y + 26, inv["address"], 9)
    days = inv.get("terms_days")
    days = terms_days() if days is None else int(days)
    for i, (k, v) in enumerate((
            ("Invoice date", inv["date"]),
            ("Terms", terms_text(days)),
            ("Due date", due_date(inv, days)),
            ("Work order", inv["work_order_number"]))):
        sheet.label(380, y + 14 * i, k)
        sheet.text(450, y + 14 * i, v, 9, k == "Due date")
    sheet.y = y + 50
    base = [ln for ln in inv["lines"] if not ln.get("kind")]
    sub = inv.get("subtotal") or inv["total"]
    _money_lines(sheet, base, sub, "Subtotal")
    rows = []
    if dmoney.D(inv.get("discount") or 0):
        rows.append((f"Member discount ({inv.get('discount_pct')}%)",
                     "-" + dmoney.fmt(inv["discount"])))
    rate = inv.get("tax_rate")
    rows.append((f"Sales tax ({tax_rate_text(rate)})" if rate not in
                 (None, "") else "Sales tax",
                 dmoney.fmt(inv.get("tax") or "0.00")))
    if inv.get("card"):
        rows.append((f"Credit card service fee ({inv.get('card_fee_pct')}%)",
                     dmoney.fmt(inv.get("card_fee") or "0.00")))
    for label, amount in rows:
        sheet.y += 14
        sheet.text(330, sheet.y, label, 9)
        sheet.text(500, sheet.y, amount, 9)
    sheet.y += 16
    sheet.text(330, sheet.y, "Amount due", 11, True)
    sheet.text(500, sheet.y, dmoney.fmt(inv["total"]), 11, True)
    c = company(comp)
    remit = [x for x in (c.get("name"), c.get("address"),
                         " | ".join(v for v in (c.get("phone"),
                                                c.get("email")) if v))
             if x]
    if remit:
        sheet.need(30 + 12 * len(remit))
        sheet.y += 26
        sheet.label(36, sheet.y, "Remit to")
        for line in remit:
            for part in str(line).splitlines():
                sheet.y += 12
                sheet.text(36, sheet.y, part, 9)
    sheet.y += 18
    sheet.text(36, sheet.y, f"Please pay by {due_date(inv, days)} and put "
               f"{inv['number']} on your payment.", 8)
    return sheet.save(path)


def missing_company():
    """What the invoice's remit-to is missing from the Company Profile."""
    from .pdfdoc import company
    c = company()
    return [k for k in ("name", "address") if not c.get(k)]


def print_work_order(store, wo_id, path, comp=None, office=False):
    """A fill-in work order, filled from the ticket and still editable.
    The customer copy never shows cost or profit (Chief's estimator test,
    Nov 7); office=True adds the Price / Cost / Profit line for the office
    copy."""
    from .pdfdoc import Sheet
    wo = get(store, wo_id)
    prof = ticket_profit(store, wo)
    sheet = Sheet("Work Order", comp, subtitle=wo["number"])
    sheet.section("01", "Call")
    y = sheet.y + 4
    pairs = (("wo_number", "Work order", wo["number"], 36, 150),
             ("wo_date", "Opened", wo["opened"], 220, 320),
             ("wo_tech", "Technician", wo["tech"], 360, 560),
             ("wo_customer", "Customer", wo["customer"], 36, 280),
             ("wo_site", "Site", wo["site"], 300, 560),
             ("wo_address", "Address", wo.get("address") or "", 36, 360),
             ("wo_unit", "Unit", wo.get("unit") or "", 380, 560))
    # two rows of fields laid out by hand, then the wide ones
    tops = [y, y, y, y + 28, y + 28, y + 56, y + 56]
    for (name, label, value, x0, x1), top in zip(pairs, tops):
        sheet.label(x0, top, label)
        sheet.text_field(name, (x0, top + 2, x1, top + 16), value)
    sheet.y = y + 80
    sheet.label(36, sheet.y, "Complaint")
    sheet.text_field("wo_complaint", (36, sheet.y + 4, 560, sheet.y + 40),
                     wo["complaint"], multiline=True)
    sheet.y += 52
    sheet.section("02", "Time and parts")
    time_txt = "\n".join(
        f"{t['date']}  {t['tech']}  {t['hours']} hr  {t.get('note', '')}"
        for t in wo["time"])
    parts_txt = "\n".join(
        f"{p['qty']} {p['unit']}  {p['desc']}" for p in wo["parts"])
    if wo.get("parts_recorded") and not wo["parts"]:
        parts_txt = "No parts used."
    sheet.label(36, sheet.y, "Time")
    sheet.text_field("wo_time", (36, sheet.y + 4, 560, sheet.y + 48),
                     time_txt, multiline=True)
    sheet.y += 56
    sheet.label(36, sheet.y, "Parts")
    sheet.text_field("wo_parts", (36, sheet.y + 4, 560, sheet.y + 48),
                     parts_txt, multiline=True)
    sheet.y += 56
    sheet.label(36, sheet.y, "Notes")
    sheet.text_field("wo_notes", (36, sheet.y + 4, 560, sheet.y + 48),
                     wo.get("notes") or "", multiline=True)
    sheet.y += 60
    if office:
        sheet.text(36, sheet.y, "Office copy", 8, True,
                   color=(0.38, 0.40, 0.42))
        sheet.y += 12
        sheet.text(36, sheet.y,
                   f"Price {dmoney.fmt(prof['price'])}    "
                   f"Cost {dmoney.fmt(prof['cost'])}    "
                   f"Profit {dmoney.fmt(prof['profit'])}", 9)
    for ph in wo.get("photos") or []:
        if not os.path.isfile(ph.get("path") or ""):
            continue
        sheet.need(160)
        sheet.y += 12
        try:
            import fitz
            sheet.page.insert_image(
                fitz.Rect(36, sheet.y, 220, sheet.y + 130),
                filename=ph["path"], keep_proportion=True)
        except Exception:                                 # noqa: BLE001
            continue
        if ph.get("caption"):
            sheet.text(230, sheet.y + 14, ph["caption"], 8)
        sheet.y += 140
    return sheet.save(path)
