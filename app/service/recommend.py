"""Technician recommendations, one list per unit.

Each line is a photo and a note, and optionally a price or a flat-rate
task. One click turns the unit's list into an option quote through
estimating/quotes.py (good / better / best, or optional items).

No network calls.
"""
import datetime as dt

from . import files

FILE = "service_recommendations.json"
KIND = "service_recommendations"


class RecommendError(ValueError):
    pass


def blank():
    return {"kind": KIND, "version": 1, "items": []}


def default_path():
    return files.path_for(FILE)


def load(path=None):
    return files.read(path or default_path(), KIND, blank)


def save(store, path=None):
    return files.write(path or default_path(), store)


def for_unit(store, equipment_id):
    return [r for r in store["items"] if r["equipment_id"] == equipment_id]


def add(store, records, equipment_id, note="", photo="", price="",
        task_id="", tier="option", when=None):
    from ..estimating import service
    eq = service.find(records, equipment_id) if records is not None else None
    if not eq or "kind" not in eq:
        raise RecommendError("That unit isn't in the service records.")
    note = files.txt(note, 1000)
    if not note and not task_id:
        raise RecommendError("Write a note or pick a pricebook task.")
    if tier not in ("base", "option", "Good", "Better", "Best"):
        raise RecommendError("Tier is base, option, Good, Better or Best.")
    try:
        price_s = files.money(price, "Price", allow_blank=True) if \
            str(price or "").strip() else ""
    except files.FileError as e:
        raise RecommendError(str(e)) from e
    row = {"id": files.new_id(), "equipment_id": equipment_id,
           "property_id": eq.get("property") or "",
           "unit": " ".join(p for p in (eq.get("kind"), eq.get("model"),
                                        eq.get("serial")) if p),
           "note": note, "photo": str(photo or "").strip(),
           "price": price_s, "task_id": task_id or "", "tier": tier,
           "created": files.iso_date(when or dt.date.today(), "Date",
                                     blank_ok=False)}
    store["items"].append(row)
    return row["id"]


def quote_for_unit(store, equipment_id, pricebook=None, member=False,
                   title="", selected_tier=""):
    """The unit's recommendations as an option quote (quotes.py)."""
    from ..estimating import quotes
    from . import pricebook as book
    rows = for_unit(store, equipment_id)
    if not rows:
        raise RecommendError("This unit has no recommendations.")
    lines = []
    for r in rows:
        photo = r.get("photo") or ""
        if r.get("task_id"):
            if pricebook is None:
                raise RecommendError("Open the pricebook for a task "
                                     "recommendation.")
            task = book.get(pricebook, r["task_id"])
            line = book.as_quote_lines([task], member=member)[0]
            line["tier"] = r.get("tier") or line["tier"]
            if r.get("note"):
                line["desc"] = r["note"]
            if photo:
                line["photo"] = photo
        else:
            if not r.get("price"):
                raise RecommendError("Set a price or a pricebook task on "
                                     "each recommendation.")
            line = {"id": r["id"], "desc": r["note"] or "Recommended work",
                    "qty": 1, "unit": "ea", "price": r["price"], "cost": "0",
                    "tier": r.get("tier") or "option"}
            if photo:
                line["photo"] = photo
        lines.append(line)
    heading = title or ("Recommended work" if not rows[0].get("unit")
                        else f"Recommended work — {rows[0]['unit']}")
    return quotes.service_option_quote(lines, title=heading,
                                       selected_tier=selected_tier)


def save_quote(path, quote, comp=None, data=None):
    from ..estimating import quotes
    return quotes.save_service_quote(path, quote, comp=comp, data=data)
