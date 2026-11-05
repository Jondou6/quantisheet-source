"""Signed time-and-material tags.

A tag lists labor, material and equipment lines and prints to a PDF.
Signing uses app.sign.signer.sign_pdf and does not change that module.
The tag links to a Project Center change event (the event tool's own
save_record); this module only reads that API.

Money is Decimal. No network calls. Signing does not contact a time
server: no timestamp URL is passed.
"""
import datetime as dt
from decimal import Decimal

from .. import dmoney
from . import files

FILE = "service_tm_tags.json"
KIND = "service_tm_tags"
KINDS = ("labor", "material", "equipment")


class TagError(ValueError):
    pass


def blank():
    return {"kind": KIND, "version": 1, "next": 1, "tags": []}


def default_path():
    return files.path_for(FILE)


def load(path=None):
    return files.read(path or default_path(), KIND, blank)


def save(store, path=None):
    return files.write(path or default_path(), store)


def get(store, tid):
    for t in store["tags"]:
        if t["id"] == tid:
            return t
    raise TagError("That tag isn't on file.")


def add(store, customer, site="", description="", when=None):
    customer = files.txt(customer)
    if not customer:
        raise TagError("Name the customer.")
    try:
        opened = files.iso_date(when or dt.date.today(), "Date",
                                blank_ok=False)
    except files.FileError as e:
        raise TagError(str(e)) from e
    n = int(store.get("next") or 1)
    store["next"] = n + 1
    tag = {"id": files.new_id(), "number": f"TM-{n:04d}", "date": opened,
           "customer": customer, "site": files.txt(site, 300),
           "description": files.txt(description, 1000), "lines": [],
           "status": "draft", "signed": "", "change_event_id": "",
           "change_event_no": ""}
    store["tags"].append(tag)
    return tag["id"]


def add_line(store, tag_id, kind, desc, qty, unit, cost, price,
             cost_code=""):
    tag = get(store, tag_id)
    if tag["status"] != "draft":
        raise TagError(f"{tag['number']} is already signed.")
    if kind not in KINDS:
        raise TagError("A line is labor, material or equipment.")
    if not files.txt(desc):
        raise TagError("Describe the line.")
    try:
        row = {"id": files.new_id(), "kind": kind, "desc": files.txt(desc),
               "qty": files.qty(qty, "Quantity"),
               "unit": files.txt(unit, 20) or "ea",
               "cost": files.money(cost, "Cost"),
               "price": files.money(price, "Price"),
               "cost_code": files.txt(cost_code, 40)}
    except files.FileError as e:
        raise TagError(str(e)) from e
    tag["lines"].append(row)
    return row


def totals(tag):
    price = Decimal("0.00")
    cost = Decimal("0.00")
    for ln in tag["lines"]:
        qty = dmoney.D(ln["qty"])
        price += dmoney.cents(qty * dmoney.D(ln["price"]))
        cost += dmoney.cents(qty * dmoney.D(ln["cost"]))
    return {"price": price, "cost": cost, "profit": price - cost}


def build_pdf(tag, path, comp=None):
    """Printable tag. The signature line is filled by sign() afterwards."""
    from .pdfdoc import Sheet
    got = totals(tag)
    sheet = Sheet("Time & Material Tag", comp, subtitle=tag["number"])
    sheet.section("01", "Job")
    y = sheet.y + 14
    sheet.text(36, y, tag["customer"], 12, True)
    sheet.text(36, y + 14, tag.get("site") or "", 9)
    sheet.text(360, y, tag["date"], 9)
    if tag.get("description"):
        sheet.text(36, y + 28, tag["description"], 9)
        y += 16
    sheet.y = y + 28
    sheet.section("02", "Lines")
    sheet.y += 12
    for ln in tag["lines"]:
        sheet.need(16)
        sheet.y += 14
        ext = dmoney.cents(dmoney.D(ln["qty"]) * dmoney.D(ln["price"]))
        sheet.text(36, sheet.y, ln["kind"].capitalize(), 8,
                   color=(0.38, 0.40, 0.42))
        sheet.text(100, sheet.y, ln["desc"][:48], 9)
        sheet.text(360, sheet.y, f"{ln['qty']} {ln['unit']}", 8)
        sheet.text(470, sheet.y, dmoney.fmt(ext), 9, True)
    sheet.y += 10
    sheet.rule()
    sheet.y += 16
    sheet.text(360, sheet.y, "Total", 11, True)
    sheet.text(470, sheet.y, dmoney.fmt(got["price"]), 11, True)
    sheet.need(70)
    sheet.y += 36
    sheet.text(36, sheet.y, "Customer signature", 8,
               color=(0.38, 0.40, 0.42))
    sheet.page.draw_line((36, sheet.y + 22), (280, sheet.y + 22),
                         color=(0.12, 0.14, 0.16), width=0.7)
    sheet.text(300, sheet.y, "Date", 8, color=(0.38, 0.40, 0.42))
    sheet.page.draw_line((300, sheet.y + 22), (420, sheet.y + 22),
                         color=(0.12, 0.14, 0.16), width=0.7)
    return sheet.save(path)


def sign(tag, src, dest, signer_name="QuantiSheet User", key_path=None,
         cert_path=None):
    """Sign `src` onto `dest` with app.sign.signer.sign_pdf.

    No timestamp server is used. The signer module is not modified.
    """
    from ..sign import signer
    if not tag.get("lines"):
        raise TagError("Add lines before signing.")
    signer.sign_pdf(src, dest, reason="Time and material tag",
                    location=tag.get("site") or "",
                    signer_name=signer_name or "QuantiSheet User",
                    key_path=key_path, cert_path=cert_path)
    tag["signed"] = dest
    tag["status"] = "signed"
    return dest


def link_change_event(tag, pm_store, reason="Other"):
    """Create a change event for this tag and store its id on the tag.

    `pm_store` is a Project Center store. Only save_record is called.
    """
    if pm_store is None:
        raise TagError("Pick the project the change event belongs to.")
    if not tag.get("lines"):
        raise TagError("Add lines before linking a change event.")
    from ..pm.schema import EVENT_REASONS
    if reason not in EVENT_REASONS:
        reason = "Other"
    lines = []
    for ln in tag["lines"]:
        qty = dmoney.D(ln["qty"])
        cost = dmoney.cents(qty * dmoney.D(ln["cost"]))
        price = dmoney.cents(qty * dmoney.D(ln["price"]))
        markup = Decimal("0.00")
        if cost > 0:
            markup = ((price - cost) / cost * Decimal(100)).quantize(
                Decimal("0.01"))
        lines.append({"cost_code": ln.get("cost_code") or "",
                      "description": f"{ln['kind']}: {ln['desc']}",
                      "vendor": "", "cost": dmoney.text(cost),
                      "markup": format(markup, "f"),
                      "price": dmoney.text(price)})
    got = totals(tag)
    rec = pm_store.save_record("event", {
        "title": f"T&M {tag['number']}: {tag['customer']}",
        "reason": reason, "scope": "Out of Scope", "lines": lines,
        "status": "Open",
        "description": (tag.get("description") or "") +
        (f"\nTag {tag['number']}. Price {dmoney.fmt(got['price'])}." ),
    })
    tag["change_event_id"] = rec["_id"]
    tag["change_event_no"] = rec.get("_no") or ""
    return rec
