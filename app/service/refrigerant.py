"""Refrigerant log for EPA Section 608 recordkeeping.

Each unit has a refrigerant and a full charge. Each visit records pounds
added, pounds recovered, the cylinder number and the technician's 608
certificate number.

Leak rate uses the annualizing method. The repair limits below are the
published thresholds for appliances with a full charge of 50 pounds or
more. Units under 50 pounds are still rated and marked when they pass the
same percentages; the repair rule itself does not apply to them.

40 CFR 82.152 (definitions) — annualizing method:

    leak rate (% per year) =
        (pounds of refrigerant added / pounds in the full charge)
        x (365 / days in the period)
        x 100

    The period is the shorter of 365 days and the days since the previous
    addition (or since the date the full charge was recorded). When that
    start date was never recorded, the period is 365 days so a missing
    date cannot inflate the rate.

40 CFR 82.157(c) — leak repair for appliances containing 50 or more
pounds of refrigerant (40 CFR Part 82, Subpart F, Clean Air Act
Section 608). Repair is required when the leak rate exceeds:

    * 30%  industrial process refrigeration
    * 20%  commercial refrigeration
    * 10%  comfort cooling
    * 10%  all other appliances

No network calls. Amounts are Decimal.
"""
import datetime as dt
from decimal import ROUND_HALF_UP, Decimal

from .. import dmoney
from . import files

FILE = "service_refrigerant.json"
KIND = "service_refrigerant"

# 40 CFR 82.157(c) thresholds, percent per year. See the module docstring.
THRESHOLDS = {
    "industrial_process": Decimal("30"),
    "commercial_refrigeration": Decimal("20"),
    "comfort_cooling": Decimal("10"),
    "other": Decimal("10"),
}
CATEGORY_LABELS = {
    "industrial_process": "industrial process refrigeration",
    "commercial_refrigeration": "commercial refrigeration",
    "comfort_cooling": "comfort cooling",
    "other": "other appliances",
}
# 40 CFR 82.157 applies at a full charge of 50 pounds or more.
REGULATORY_MIN_LBS = Decimal("50")


# shown in the window (review 2, Nov 4): these are compliance records, so
# say which rule text the thresholds come from and that it must be checked
# Jon (Nov 4): a qualified person will review these; until he confirms,
# they stay labeled NOT YET REVIEWED.
REVIEWED = False
RULE_NOTE = (("NOT YET REVIEWED - these thresholds haven't been checked by "
              "a compliance person. ") if not REVIEWED else "") + (
             "Thresholds: 40 CFR Part 82 Subpart F (Section 608) leak repair "
             "rule for appliances with 50 lb or more - industrial 30%, "
             "commercial refrigeration 20%, comfort cooling and others 10% a "
             "year. Newer rules (the AIM Act technology transitions and HFC "
             "leak management) may also apply. Not legal advice: have your "
             "compliance person confirm the current rules.")


class RefError(ValueError):
    pass


def _who():
    import getpass
    try:
        return getpass.getuser()
    except Exception:                                     # noqa: BLE001
        return ""


def _log(store, action, rid, before=None, after=None, why=""):
    """Every change is kept: who, when, what - entries are never edited
    or removed in place (review 2, Nov 4)."""
    store.setdefault("log", []).append({
        "at": dt.datetime.now().isoformat(timespec="seconds"),
        "by": _who(), "action": action, "id": rid,
        "before": before, "after": after, "why": why})


def correct_visit(store, visit_id, field, value, why):
    """Fix a typed mistake on a visit. The old value stays in the log with
    the reason; the visit is marked corrected."""
    if not files.txt(why):
        raise RefError("Say why the entry is being corrected.")
    allowed = ("lbs_added", "lbs_recovered", "cylinder", "cert_no", "tech",
               "notes", "date")
    if field not in allowed:
        raise RefError("That part of a visit can't be corrected.")
    v = next((v for v in store["visits"] if v["id"] == visit_id), None)
    if v is None:
        raise RefError("That visit isn't in the log.")
    try:
        if field in ("lbs_added", "lbs_recovered"):
            new = files.lbs(value, "Pounds")
        elif field == "date":
            new = files.iso_date(value, "Visit date", blank_ok=False)
        else:
            new = files.txt(value, 500 if field == "notes" else 40)
    except files.FileError as e:
        _err(e)
    old = v.get(field)
    v[field] = new
    v["corrected"] = True
    _log(store, "correct visit", visit_id, {field: old}, {field: new},
         files.txt(why, 300))
    return v


def history(store, rid=None):
    """The change log, oldest first (for one unit or visit when given)."""
    return [r for r in store.get("log", [])
            if rid is None or r.get("id") == rid]


def blank():
    return {"kind": KIND, "version": 1, "units": [], "visits": [], "log": []}


def default_path():
    return files.path_for(FILE)


def load(path=None):
    return files.read(path or default_path(), KIND, blank)


def save(store, path=None):
    return files.write(path or default_path(), store)


def _err(exc):
    if isinstance(exc, files.FileError):
        raise RefError(str(exc)) from exc
    raise exc


def add_unit(store, records, equipment_id, refrigerant, full_charge,
             category, charge_date=""):
    from ..estimating import service
    eq = service.find(records, equipment_id) if records is not None else None
    if not eq or "kind" not in eq:
        raise RefError("That unit isn't in the service records.")
    if category not in THRESHOLDS:
        raise RefError("Pick industrial process, commercial refrigeration, "
                       "comfort cooling, or other.")
    if not files.txt(refrigerant):
        raise RefError("Name the refrigerant.")
    try:
        charge = files.lbs(full_charge, "Full charge", allow_zero=False)
        charged = files.iso_date(charge_date, "Charge date")
    except files.FileError as e:
        _err(e)
    if any(u["equipment_id"] == equipment_id for u in store["units"]):
        raise RefError("That unit already has a refrigerant record.")
    row = {"id": files.new_id(), "equipment_id": equipment_id,
           "property_id": eq.get("property") or "",
           "unit": " ".join(p for p in (eq.get("kind"), eq.get("make"),
                                        eq.get("model"), eq.get("serial"))
                            if p),
           "refrigerant": files.txt(refrigerant, 80),
           "full_charge": charge, "category": category,
           "charge_date": charged}
    store["units"].append(row)
    _log(store, "add unit", row["id"], None, dict(row))
    return row["id"]


def _unit(store, uid):
    for u in store["units"]:
        if u["id"] == uid:
            return u
    raise RefError("That unit isn't in the refrigerant log.")


def add_visit(store, unit_id, when, lbs_added="0", lbs_recovered="0",
              cylinder="", cert_no="", tech="", notes=""):
    _unit(store, unit_id)
    try:
        added = files.lbs(lbs_added, "Pounds added")
        recovered = files.lbs(lbs_recovered, "Pounds recovered")
        when_s = files.iso_date(when, "Visit date", blank_ok=False)
    except files.FileError as e:
        _err(e)
    if dmoney.D(added) == 0 and dmoney.D(recovered) == 0:
        raise RefError("Enter pounds added or pounds recovered.")
    if dmoney.D(added) > 0 or dmoney.D(recovered) > 0:
        if not files.txt(cylinder):
            raise RefError("Enter the cylinder number.")
        if not files.txt(cert_no):
            raise RefError("Enter the technician's 608 certificate number.")
    row = {"id": files.new_id(), "unit_id": unit_id, "date": when_s,
           "lbs_added": added, "lbs_recovered": recovered,
           "cylinder": files.txt(cylinder, 40),
           "cert_no": files.txt(cert_no, 40),
           "tech": files.txt(tech), "notes": files.txt(notes, 500)}
    store["visits"].append(row)
    _log(store, "add visit", row["id"], None, dict(row))
    return row["id"]


def _additions(store, unit_id):
    rows = [v for v in store["visits"]
            if v["unit_id"] == unit_id and dmoney.D(v["lbs_added"]) > 0]
    rows.sort(key=lambda v: v["date"])
    return rows


def leak_rate(store, unit_id):
    """The annualizing-method leak rate for the latest addition.

    Returns rate (percent per year, 2 decimals), the pounds added, the
    days used, the category threshold, whether the rate is over it, and
    whether 40 CFR 82.157's 50-pound rule applies. See the module docstring.
    """
    unit = _unit(store, unit_id)
    charge = dmoney.D(unit["full_charge"])
    threshold = THRESHOLDS[unit["category"]]
    additions = _additions(store, unit_id)
    if not additions or charge <= 0:
        rate = Decimal("0.00")
        return {"rate": rate, "added": Decimal("0"), "days": 0,
                "full_charge": charge, "threshold": threshold,
                "over": False,
                "regulatory": charge >= REGULATORY_MIN_LBS,
                "category": unit["category"]}
    latest = additions[-1]
    if len(additions) >= 2:
        ref = dt.date.fromisoformat(additions[-2]["date"])
    elif unit.get("charge_date"):
        ref = dt.date.fromisoformat(unit["charge_date"])
    else:
        ref = None
    if ref is None:
        days = 365
    else:
        days = (dt.date.fromisoformat(latest["date"]) - ref).days
        if days < 1:
            days = 1
    window = min(days, 365)
    added = dmoney.D(latest["lbs_added"])
    # 40 CFR 82.152 annualizing method. See the module docstring.
    rate = (added / charge) * (Decimal(365) / Decimal(window)) * Decimal(100)
    rate = rate.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return {"rate": rate, "added": added, "days": window,
            "full_charge": charge, "threshold": threshold,
            "over": rate > threshold,
            "regulatory": charge >= REGULATORY_MIN_LBS,
            "category": unit["category"], "as_of": latest["date"]}


def _pct(d):
    if d == d.to_integral():
        return str(int(d))
    return f"{d:.2f}"


def flag_text(info):
    """A short sentence when the unit is over its limit, else ''."""
    if not info.get("over"):
        return ""
    label = CATEGORY_LABELS.get(info["category"], "this equipment")
    text = (f"Leak rate {_pct(info['rate'])}% per year. Over the "
            f"{_pct(info['threshold'])}% leak-rate limit for {label}.")
    if not info.get("regulatory"):
        text += " Full charge is under 50 lb."
    return text


def flagged(store):
    out = []
    for unit in store["units"]:
        info = leak_rate(store, unit["id"])
        if info["over"]:
            out.append(dict(info, unit_id=unit["id"], unit=unit["unit"],
                            text=flag_text(info)))
    return out


def site_log_pdf(store, records, property_id, path, comp=None):
    """A printable refrigerant log for one site."""
    from ..estimating import service
    from .pdfdoc import Sheet
    prop = service.find(records, property_id) if records is not None else None
    if not prop or "customer" not in prop:
        raise RefError("That site isn't in the service records.")
    units = [u for u in store["units"] if u["property_id"] == property_id]
    sheet = Sheet("Refrigerant log", comp, subtitle=prop.get("name") or "")
    sheet.section("01", prop.get("name") or "Site")
    sheet.y += 12
    sheet.text(36, sheet.y, prop.get("customer") or "", 10, True)
    sheet.y += 12
    sheet.text(36, sheet.y, prop.get("address") or "", 8)
    if not units:
        sheet.y += 20
        sheet.text(36, sheet.y, "No refrigerant records at this site.", 9)
        return sheet.save(path)
    for unit in units:
        info = leak_rate(store, unit["id"])
        sheet.section("Unit", unit["unit"] or "Unit")
        sheet.y += 12
        sheet.text(36, sheet.y,
                   f"{unit['refrigerant']}    full charge "
                   f"{unit['full_charge']} lb    "
                   f"{CATEGORY_LABELS[unit['category']]}", 9)
        sheet.y += 12
        rate = (f"Leak rate {info['rate']}% per year"
                if info["days"] else "No refrigerant added yet")
        mark = flag_text(info)
        sheet.text(36, sheet.y, rate + ("    " + mark if mark else ""), 9, True)
        visits = [v for v in store["visits"] if v["unit_id"] == unit["id"]]
        visits.sort(key=lambda v: v["date"])
        for v in visits:
            sheet.need(14)
            sheet.y += 12
            sheet.text(36, sheet.y,
                       f"{v['date']}  added {v['lbs_added']} lb  "
                       f"recovered {v['lbs_recovered']} lb  "
                       f"cylinder {v['cylinder']}  cert {v['cert_no']}  "
                       f"{v['tech']}", 8)
    return sheet.save(path)
