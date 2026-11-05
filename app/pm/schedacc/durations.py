"""Durations from quantity, a production rate and a crew. Never from a model.

Order:

1. A duration the spec stated (cure, review period, a stated lead time)
   is already marked computed and is left alone.
2. A cost-book labor hour, when the activity has a quantity and the book
   has hours for that cost code: days = quantity / (crew output) times the
   estimate-versus-actual factor. ``costbook.labor_output`` is the output.
3. Else a production-rate family from the existing rate table, same formula,
   clamped to that family's minimum and maximum.
4. Else the template's number, marked estimated.

A quantity inferred from floor area is still estimated: it was not taken
off. The model is not asked for a number.
"""
import math

from .calendar import standard_specs

# activity class -> production-rate family in app.pm.productivity
FAMILY = {
    "slab": "slab",
    "underground": "underslab",
    "roofing": "roofing",
    "cover": "drywall",
    "finishes": "paint",
    "plumb_rough": "plumbing_rough",
    "hvac_rough": "hvac_rough",
    "elec_rough": "elec_rough",
    "fire_rough": "sprinkler_rough",
    "demolition": "selective_demo",
    "structure": "structure",
}


def _table(table):
    if table is not None:
        return table
    from .. import productivity
    return productivity.defaults()


def _items(book):
    if book is None:
        return {}
    if hasattr(book, "items") and isinstance(book.items, dict):
        return book.items
    if isinstance(book, dict):
        return book.get("items") or {}
    return {}


def _factor(actuals, division, code):
    """actual / estimate when both are present. Outliers are not applied."""
    for row in actuals or ():
        if not isinstance(row, dict):
            continue
        if row.get("factor") not in (None, "") and (
                not row.get("division") or row.get("division") == division
                or str(row.get("code") or "")[:2] == division):
            try:
                return float(row["factor"]), "stated factor"
            except (TypeError, ValueError):
                continue
        if code and str(row.get("code") or "") == code:
            est, act = row.get("est_unit"), row.get("act_unit")
            try:
                est, act = float(est), float(act)
            except (TypeError, ValueError):
                continue
            if est > 0 and act > 0:
                f = act / est
                if 0.25 <= f <= 4:
                    return f, "estimate versus actual"
                return 1.0, "estimate versus actual was out of range and was not used"
    return 1.0, ""


def _hours_per_day(doc, key):
    spec = (doc.get("calendars") or {}).get(key) or {}
    return float(spec.get("hours_per_day") or 8)


def set_hours(act, days, doc):
    hpd = _hours_per_day(doc, act.get("calendar") or "5day")
    days = max(0, int(math.ceil(days - 1e-9)))
    if act.get("type") in ("start_ms", "finish_ms"):
        days = 0
    act["orig_hours"] = days * hpd
    act["remain_hours"] = act["orig_hours"]
    act["dur_days"] = days
    return days


def apply(doc, takeoff=None, cost_book=None, table=None, actuals=None,
          area_sf=None, stories=1, crew_size=4):
    table = _table(table)
    items = _items(cost_book)
    families = table.get("families") or {}
    estimates = None
    if area_sf:
        from .. import productivity
        estimates = productivity.estimates(
            {"area_sf": area_sf, "stories": stories or 1,
             "area_found": True})
    by_div = {}
    for it in takeoff or ():
        if not isinstance(it, dict):
            continue
        div = str(it.get("division") or "")[:2]
        by_div.setdefault(div, []).append(it)
    for act in doc.get("activities") or ():
        if act.get("duration_kind") == "computed":
            continue
        if act.get("type") in ("start_ms", "finish_ms", "loe", "wbs_summary"):
            continue
        fam_key = FAMILY.get(act.get("cls") or "")
        fam = families.get(fam_key) if fam_key else None
        qty, how, ids, from_takeoff = _quantity(act, by_div, fam)
        factor, factor_how = _factor(actuals, act.get("division") or "",
                                      act.get("cost_code") or "")
        book_days = _from_book(act, items, qty, crew_size, factor)
        if book_days is not None:
            set_hours(act, book_days, doc)
            act["duration_kind"] = "computed"
            act["quantity"] = qty
            act["takeoff_ids"] = ids
            act["basis"] = (f"{qty:g} {act.get('quantity_unit') or ''} / "
                            f"cost book labor, crew {crew_size:g}"
                            + (f", factor {factor:g} ({factor_how})"
                               if factor_how else ""))
            continue
        if fam and qty and from_takeoff:
            rate = float(fam.get("rate") or 0)
            crews = float(fam.get("crews") or 1) or 1
            if rate > 0:
                days = qty / (rate * crews) * factor
                days = min(float(fam.get("max") or days),
                           max(float(fam.get("min") or 1), days))
                set_hours(act, days, doc)
                act["duration_kind"] = "computed"
                act["quantity"] = qty
                act["quantity_unit"] = fam.get("unit") or ""
                act["family"] = fam_key
                act["takeoff_ids"] = ids
                act["basis"] = (f"{qty:g} {fam.get('unit') or ''} / "
                                f"({rate:g} per crew-day x {crews:g} crew)"
                                + (f" x {factor:g}" if factor != 1 else "")
                                + f" from the production table ({how})")
                continue
        if fam and estimates and not from_takeoff:
            key = fam.get("qty")
            if key and key in estimates and estimates[key][0]:
                qty = float(estimates[key][0])
                rate = float(fam.get("rate") or 0)
                crews = float(fam.get("crews") or 1) or 1
                if rate > 0 and qty > 0:
                    days = qty / (rate * crews) * factor
                    days = min(float(fam.get("max") or days),
                               max(float(fam.get("min") or 1), days))
                    set_hours(act, days, doc)
                    act["duration_kind"] = "estimated"
                    act["quantity"] = qty
                    act["family"] = fam_key
                    act["basis"] = (f"estimated from floor area ({estimates[key][1]}), "
                                    f"not a takeoff: {days:.0f} days")
                    continue
        # Template number already stored. Keep it labeled estimated.
        act["duration_kind"] = act.get("duration_kind") or "estimated"
        if not act.get("basis"):
            days = (act.get("orig_hours") or 0) / _hours_per_day(
                doc, act.get("calendar") or "5day")
            act["basis"] = f"template default {days:.0f} workdays, estimated"
    return doc


def _quantity(act, by_div, fam):
    rows = by_div.get(act.get("division") or "", [])
    if not rows:
        return None, "", [], False
    unit = (fam or {}).get("unit") or ""
    matched = []
    for it in rows:
        iu = str(it.get("unit") or "")
        if unit and iu and iu.lower() != str(unit).lower() and \
                iu.lower() not in str(unit).lower():
            continue
        try:
            q = float(it.get("quantity") or 0)
        except (TypeError, ValueError):
            continue
        if q > 0:
            matched.append(it)
    if not matched:
        return None, "", [], False
    total = sum(float(it["quantity"]) for it in matched)
    ids = [str(it.get("id") or it.get("name") or "") for it in matched]
    return total, "takeoff", ids, True


def _from_book(act, items, qty, crew_size, factor):
    if not qty or not items:
        return None
    code = act.get("cost_code") or ""
    row = None
    if code and code in items:
        row = items[code]
    else:
        div = act.get("division") or ""
        for key, item in items.items():
            if str(key).startswith(div) and div:
                row = item
                break
    if not row:
        return None
    hours = row.get("labor") if isinstance(row, dict) else None
    try:
        hours = float(hours or 0)
    except (TypeError, ValueError):
        return None
    if hours <= 0:
        return None
    from ... import costbook
    output = costbook.labor_output(hours, crew_size)
    if not output:
        return None
    return float(qty) / float(output) * factor
