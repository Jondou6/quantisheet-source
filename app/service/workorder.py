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
    store["orders"].append(wo)
    if wo["tech"] and wo["tech"] not in store["techs"]:
        store["techs"].append(wo["tech"])
    return wo["id"]


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


def create_invoice(store, wo_id, when=None):
    wo = get(store, wo_id)
    if wo["status"] != "closed":
        raise WorkOrderError("Close the ticket before invoicing.")
    if wo.get("invoice_id"):
        raise WorkOrderError("This ticket already has an invoice.")
    totals = ticket_profit(store, wo)
    n = int(store.get("invoice_next") or 1)
    store["invoice_next"] = n + 1
    inv = {"id": files.new_id(), "number": f"INV-{n:04d}",
           "work_order_id": wo_id, "work_order_number": wo["number"],
           "date": files.iso_date(when or wo["closed"] or dt.date.today(),
                                  "Invoice date", blank_ok=False),
           "customer": wo["customer"], "site": wo["site"],
           "address": wo.get("address") or "", "billing": wo["billing"],
           "lines": invoice_lines(store, wo),
           "total": dmoney.text(totals["price"]),
           "cost": dmoney.text(totals["cost"]),
           "profit": dmoney.text(totals["profit"])}
    store["invoices"].append(inv)
    wo["invoice_id"] = inv["id"]
    return inv


def close_and_invoice(store, wo_id, notes=None, when=None, pdf_path=None,
                      comp=None, write_pdf=True):
    """Close the ticket and write its invoice. One step."""
    close(store, wo_id, notes=notes, when=when)
    inv = create_invoice(store, wo_id, when=when)
    if write_pdf:
        path = pdf_path or files.path_for(f"{inv['number']}.pdf")
        invoice_pdf(store, inv["id"], path, comp=comp)
        inv["pdf"] = path
    return inv


def _money_lines(sheet, lines, total):
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
    sheet.text(400, sheet.y, "Total", 11, True)
    sheet.text(500, sheet.y, dmoney.fmt(total), 11, True)


def invoice_pdf(store, invoice_id, path, comp=None):
    from .pdfdoc import Sheet
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
    sheet.text(400, y, inv["date"], 9)
    sheet.text(400, y + 14, "Work order " + inv["work_order_number"], 9)
    sheet.y = y + (40 if inv.get("address") else 28)
    _money_lines(sheet, inv["lines"], inv["total"])
    return sheet.save(path)


def print_work_order(store, wo_id, path, comp=None):
    """A fill-in work order, filled from the ticket and still editable."""
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
    sheet.text(36, sheet.y, "Office", 8, True, color=(0.38, 0.40, 0.42))
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
