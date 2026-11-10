"""Flat-rate task pricebook.

A task has a customer price, an agreement-member price, the parts that
are built into the price, and the hours. Work orders bill the task.
Option quotes (estimating/quotes.py) use the same prices.

Money is Decimal. No prices ship with the program. No network calls.
"""
from decimal import Decimal

from .. import dmoney
from . import files

FILE = "service_pricebook.json"
KIND = "service_pricebook"
TIERS = ("base", "option", "Good", "Better", "Best")


class PriceError(ValueError):
    pass


def blank():
    return {"kind": KIND, "version": 1, "tasks": []}


def default_path():
    return files.path_for(FILE)


def load(path=None):
    return files.read(path or default_path(), KIND, blank)


def save(store, path=None):
    return files.write(path or default_path(), store)


def get(store, tid):
    for t in store["tasks"]:
        if t["id"] == tid:
            return t
    raise PriceError("That task isn't in the pricebook.")


def _parts(parts):
    out = []
    for p in parts or []:
        try:
            out.append({
                "sku": files.txt(p.get("sku"), 40),
                "desc": files.txt(p.get("desc")) or "Part",
                "qty": files.qty(p.get("qty", "1"), "Part quantity"),
                "unit": files.txt(p.get("unit"), 20) or "ea",
                "cost": files.money(p.get("cost", "0"), "Part cost"),
            })
        except files.FileError as e:
            raise PriceError(str(e)) from e
    return out


def add_task(store, name, customer_price, member_price, code="", hours="0",
             labor_cost="0", parts=None, description="", tier="option"):
    name = files.txt(name)
    if not name:
        raise PriceError("Name the task.")
    if tier not in TIERS:
        raise PriceError("Tier is base, option, Good, Better or Best.")
    try:
        if str(hours) in ("", "0", "0.0", "0.00"):
            hours_s = "0.00"
        else:
            hours_s = files.qty(hours, "Hours")
        row = {
            "id": files.new_id(), "code": files.txt(code, 40), "name": name,
            "description": files.txt(description, 1000),
            "customer_price": files.money(customer_price, "Customer price"),
            "member_price": files.money(member_price, "Member price")
            if str(member_price or "").strip() else _member_default(
                customer_price),
            "hours": hours_s,
            "labor_cost": files.money(labor_cost, "Labor cost per hour"),
            "parts": _parts(parts), "tier": tier,
        }
    except files.FileError as e:
        raise PriceError(str(e)) from e
    store["tasks"].append(row)
    return row["id"]


def _member_default(customer_price):
    """No member price given: the customer price less the member discount
    (service_member_discount_pct, 10% to start - Jon, Nov 5)."""
    from . import agreements
    pct = dmoney.D(agreements.defaults()["discount_pct"])
    return dmoney.text(dmoney.cents(dmoney.D(files.money(
        customer_price, "Customer price")) * (100 - pct) / 100))


def task_cost(task):
    """Built-in cost: hours x labor cost, plus each part's cost."""
    total = dmoney.cents(dmoney.D(task.get("hours") or 0) *
                         dmoney.D(task.get("labor_cost") or 0))
    for p in task.get("parts") or []:
        total += dmoney.cents(dmoney.D(p["qty"]) * dmoney.D(p["cost"]))
    return total


def price_of(task, member=False):
    return dmoney.cents(task["member_price"] if member else
                        task["customer_price"])


def as_quote_lines(tasks, member=False):
    """Lines for quotes.service_option_quote. Price is the task price."""
    lines = []
    for t in tasks:
        desc = t["name"] + (f" ({t['code']})" if t.get("code") else "")
        lines.append({"id": t["id"], "desc": desc, "qty": Decimal(1),
                      "unit": "ea", "price": price_of(t, member),
                      "cost": task_cost(t), "tier": t.get("tier") or "option"})
    return lines


def option_quote(store, task_ids, member=False, title="Service options",
                 selected_tier=""):
    """A good / better / best quote for these tasks, via estimating/quotes.py."""
    from ..estimating import quotes
    if not task_ids:
        raise PriceError("Pick at least one task.")
    tasks = [get(store, i) for i in task_ids]
    return quotes.service_option_quote(
        as_quote_lines(tasks, member=member), title=title,
        selected_tier=selected_tier)


def save_quote(path, quote, comp=None, data=None):
    from ..estimating import quotes
    return quotes.save_service_quote(path, quote, comp=comp, data=data)
