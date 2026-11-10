"""Refrigerant recovery and cylinder records (QuantiSheet 1.2, #14).

- Disposal records, 40 CFR 82.156(a)(3): for appliances holding 5 to
  50 lb that are disposed of - the company, location, date of recovery
  and refrigerant type; monthly totals recovered by type; and transfers
  to a reclaimer (date, who, pounds by type).
- Cylinders: each recovery, disposable or new cylinder with its
  refrigerant and the truck it rides on (the Truck Stock trucks).
- Disposable cylinders, 40 CFR 84.116 (from Jan 1, 2028 by default): a
  printable statement that the heel was removed, or that the tech
  evacuated the cylinder to 15 in-Hg vacuum, signed by the tech.

The limits and dates are in the refrigerant rules (editable). A licensed
tech reviews them; QuantiSheet keeps records, it does not decide
compliance. No network calls.
"""
import datetime as dt
from decimal import Decimal

from .. import dmoney
from . import files

FILE = "service_recovery.json"
KIND = "service_recovery"
CYL_KINDS = ("recovery", "disposable", "new")
EMPTY_METHODS = {"heel": "Heel removed (refrigerant recovered from the "
                         "cylinder before disposal)",
                 "vacuum": "Evacuated to {vac} in-Hg vacuum by the "
                           "technician"}


class RecoveryError(ValueError):
    pass


def blank():
    return {"kind": KIND, "version": 1, "disposals": [], "transfers": [],
            "cylinders": [], "statements": []}


def default_path():
    return files.path_for(FILE)


def load(path=None):
    return files.read(path or default_path(), KIND, blank)


def save(store, path=None):
    return files.write(path or default_path(), store)


def _err(e):
    raise RecoveryError(str(e)) from e


def _rules():
    from . import refrigerant_rules
    return refrigerant_rules.load()


def add_disposal(store, when, location, refrigerant, lbs_recovered,
                 company="", appliance="", full_charge="", tech=""):
    """One appliance disposed of. Charges outside 5-50 lb are refused."""
    r = _rules()
    try:
        d = files.iso_date(when, "Date of recovery", blank_ok=False)
        rec = files.lbs(lbs_recovered, "Pounds recovered")
        charge = files.lbs(full_charge, "Full charge") if full_charge \
            not in ("", None) else ""
    except files.FileError as e:
        _err(e)
    if not files.txt(location):
        raise RecoveryError("Enter where the appliance was (the location).")
    if not files.txt(refrigerant):
        raise RecoveryError("Name the refrigerant type.")
    if charge:
        c = dmoney.D(charge)
        if c < dmoney.D(r["disposal_min_lbs"]) or \
                c > dmoney.D(r["disposal_max_lbs"]):
            raise RecoveryError(
                f"Disposal records here are for appliances of "
                f"{r['disposal_min_lbs']} to {r['disposal_max_lbs']} lb.")
    row = {"id": files.new_id(), "date": d,
           "company": files.txt(company) or _company(),
           "location": files.txt(location, 200),
           "refrigerant": files.txt(refrigerant, 40).upper(),
           "lbs": rec, "appliance": files.txt(appliance, 120),
           "full_charge": charge, "tech": files.txt(tech)}
    store["disposals"].append(row)
    return row["id"]


def _company():
    try:
        from .pdfdoc import company
        return (company() or {}).get("name", "")
    except Exception:                                     # noqa: BLE001
        return ""


def monthly_totals(store, year, month):
    """{refrigerant: pounds} recovered from disposals in one month."""
    key = f"{int(year):04d}-{int(month):02d}"
    out = {}
    for d in store["disposals"]:
        if d["date"].startswith(key):
            out[d["refrigerant"]] = out.get(d["refrigerant"], Decimal(0)) + \
                dmoney.D(d["lbs"])
    return {k: str(v) for k, v in sorted(out.items())}


def add_transfer(store, when, reclaimer, refrigerant, lbs, cylinder=""):
    try:
        d = files.iso_date(when, "Transfer date", blank_ok=False)
        q = files.lbs(lbs, "Pounds", allow_zero=False)
    except files.FileError as e:
        _err(e)
    if not files.txt(reclaimer):
        raise RecoveryError("Name the reclaimer.")
    row = {"id": files.new_id(), "date": d,
           "reclaimer": files.txt(reclaimer, 120),
           "refrigerant": files.txt(refrigerant, 40).upper(), "lbs": q,
           "cylinder": files.txt(cylinder, 40)}
    store["transfers"].append(row)
    return row["id"]


def add_cylinder(store, number, refrigerant, kind="recovery", truck=""):
    if kind not in CYL_KINDS:
        raise RecoveryError("Pick recovery, disposable or new.")
    if not files.txt(number):
        raise RecoveryError("Enter the cylinder number.")
    if any(c["number"] == files.txt(number, 40) for c in store["cylinders"]):
        raise RecoveryError("That cylinder number is already listed.")
    row = {"id": files.new_id(), "number": files.txt(number, 40),
           "refrigerant": files.txt(refrigerant, 40).upper(), "kind": kind,
           "truck": files.txt(truck, 80), "status": "in use"}
    store["cylinders"].append(row)
    return row["id"]


def _cyl(store, cid):
    for c in store["cylinders"]:
        if c["id"] == cid or c["number"] == cid:
            return c
    raise RecoveryError("That cylinder isn't listed.")


def move_cylinder(store, cid, truck):
    c = _cyl(store, cid)
    c["truck"] = files.txt(truck, 80)
    return c


def on_truck(store, truck):
    return [c for c in store["cylinders"]
            if c["truck"] == truck and c["status"] == "in use"]


def statement_required(when=None):
    when = when or dt.date.today()
    if isinstance(when, str):
        when = dt.date.fromisoformat(when)
    return when.isoformat() >= _rules()["disposable_cylinder_from"]


def empty_statement(store, cid, when, method, tech, cert_no):
    """Record that a disposable cylinder was emptied before disposal."""
    c = _cyl(store, cid)
    if c["kind"] != "disposable":
        raise RecoveryError("The statement is for disposable cylinders.")
    if method not in EMPTY_METHODS:
        raise RecoveryError("Pick heel removed or evacuated to vacuum.")
    if not files.txt(tech) or not files.txt(cert_no):
        raise RecoveryError("Enter the technician and 608 certificate "
                            "number.")
    try:
        d = files.iso_date(when, "Date", blank_ok=False)
    except files.FileError as e:
        _err(e)
    row = {"id": files.new_id(), "cylinder": c["id"], "number": c["number"],
           "refrigerant": c["refrigerant"], "date": d, "method": method,
           "tech": files.txt(tech), "cert_no": files.txt(cert_no, 40)}
    store["statements"].append(row)
    c["status"] = "emptied"
    return row["id"]


def statement_pdf(store, statement_id, path, comp=None):
    from .pdfdoc import Sheet, fit
    s = next((x for x in store["statements"] if x["id"] == statement_id),
             None)
    if s is None:
        raise RecoveryError("That statement isn't recorded.")
    vac = _rules()["disposable_cylinder_vacuum_inhg"]
    sheet = Sheet("Disposable cylinder statement", comp)
    sheet.section("01", "Cylinder emptied before disposal")
    for label, val in (("Cylinder", s["number"]),
                       ("Refrigerant", s["refrigerant"]),
                       ("Date", s["date"]),
                       ("How it was emptied",
                        EMPTY_METHODS[s["method"]].format(vac=vac)),
                       ("Technician", s["tech"]),
                       ("608 certificate", s["cert_no"])):
        sheet.y += 14
        sheet.text(36, sheet.y, label, 9, True)
        sheet.text(170, sheet.y, fit(val, 390, 9), 9)
    sheet.y += 40
    sheet.text(36, sheet.y, "Technician signature: "
               "_______________________________    Date: ____________", 9)
    sheet.y += 20
    sheet.text(36, sheet.y, fit("40 CFR 84.116 statement. Not legal advice: "
                                "your licensed tech confirms the current "
                                "rule.", 540, 8), 8)
    return sheet.save(path)


def disposal_log_pdf(store, year, month, path, comp=None):
    """The month's disposal records and totals by type, and transfers."""
    from .pdfdoc import Sheet, fit
    key = f"{int(year):04d}-{int(month):02d}"
    sheet = Sheet("Refrigerant recovery log", comp, subtitle=key)
    sheet.section("01", "Appliances disposed of (5 to 50 lb)")
    rows = [d for d in store["disposals"] if d["date"].startswith(key)]
    if not rows:
        sheet.y += 14
        sheet.text(36, sheet.y, "No disposals recorded this month.", 9)
    for d in sorted(rows, key=lambda d: d["date"]):
        sheet.need(14)
        sheet.y += 12
        sheet.text(36, sheet.y, fit(
            f"{d['date']}  {d['company']}  {d['location']}  "
            f"{d['refrigerant']} {d['lbs']} lb  {d['appliance']}", 540, 8), 8)
    sheet.section("02", "Recovered this month by type")
    for k, v in monthly_totals(store, year, month).items():
        sheet.y += 12
        sheet.text(36, sheet.y, f"{k}: {v} lb", 9)
    sheet.section("03", "Sent to a reclaimer")
    for t in sorted((t for t in store["transfers"]
                     if t["date"].startswith(key)), key=lambda t: t["date"]):
        sheet.need(14)
        sheet.y += 12
        sheet.text(36, sheet.y, fit(
            f"{t['date']}  {t['reclaimer']}  {t['refrigerant']} {t['lbs']} lb"
            f"  cylinder {t['cylinder']}", 540, 8), 8)
    return sheet.save(path)
