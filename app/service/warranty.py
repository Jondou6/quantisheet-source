"""Warranty registration tracker (QuantiSheet 1.2, #9 / QW4).

Each maker's registration window (days after install to register for the
longer warranty) is a rule in data, editable per brand and per model line.
At install or handover each unit gets a register-by date; the due list
counts down to it. The warranty card that ships with the unit is what
counts - these are starting values.

Brand rules (starting values, Nov 5, 2026). The sources are the makers'
own pages (Chief's research, Nov 5); anything not confirmed on the maker's
own page is marked UNVERIFIED and shown that way:
- Goodman 60 days, confirmed. Not required in CA, FL, GA, Quebec. The
  residential warranty excludes non-owner-occupied and commercial
  buildings; the commercial window is UNVERIFIED.
- Daikin 60 days, confirmed. Not required in CA, FL, Quebec. Different
  warranties for commercial properties; commercial window UNVERIFIED.
- Rheem 60 days (RH*L air handlers, RCF* coils) or 90 days (some lines -
  which ones is UNVERIFIED), confirmed on Rheem's pages. Commercial
  equipment: 1 year parts / 5 years compressor - registering does not
  extend it.
- Ruud 60 days, UNVERIFIED (not on ruud.com).
- Trane / American Standard 60, Carrier / Bryant 90, Lennox 60 calendar
  days (SC not exempt): the brief's starting values, to be confirmed.

Rules for units already registered never move when a rule changes: each
unit keeps the window it was given (re-apply on purpose to change it).
Also: a unit still under warranty flags its work orders, so warranty work
isn't billed to the customer by mistake.
"""
import copy
import datetime as dt
import json
import os

from . import files

FILE = "service_warranty.json"
KIND = "service_warranty"
RULES_FILE = "service_warranty_rules.json"

DEFAULT_RULES = {
    "Goodman": {"days": 60, "verified": True, "lines": {},
                "note": "Not required in CA, FL, GA, Quebec. Residential "
                        "warranty excludes commercial buildings; commercial "
                        "window UNVERIFIED."},
    "Daikin": {"days": 60, "verified": True, "lines": {},
               "note": "Not required in CA, FL, Quebec. Different warranties "
                       "for commercial properties; commercial window "
                       "UNVERIFIED."},
    "Rheem": {"days": 60, "verified": True,
              "lines": {"RH*L air handlers": 60, "RCF* coils": 60,
                        "90-day lines (UNVERIFIED which)": 90},
              "note": "Commercial equipment: 1 year parts / 5 years "
                      "compressor; registering does not extend it."},
    "Ruud": {"days": 60, "verified": False, "lines": {},
             "note": "UNVERIFIED - not confirmed on ruud.com."},
    "Trane / American Standard": {"days": 60, "verified": False,
                                  "lines": {}, "note": "Starting value - "
                                  "confirm on the warranty card."},
    "Carrier / Bryant": {"days": 90, "verified": False, "lines": {},
                         "note": "Starting value - confirm on the warranty "
                                 "card."},
    "Lennox": {"days": 60, "verified": False, "lines": {},
               "note": "60 calendar days; SC not exempt. Starting value - "
                       "confirm on the warranty card."},
}
DEFAULT_DAYS = 60
WARN_DAYS = 14


class WarrantyError(ValueError):
    pass


def rules():
    out = copy.deepcopy(DEFAULT_RULES)
    p = files.path_for(RULES_FILE)
    if os.path.isfile(p):
        try:
            with open(p, encoding="utf-8") as f:
                saved = json.load(f)
            if isinstance(saved, dict):
                out.update(saved)
        except (OSError, ValueError):
            pass
    return out


def save_rules(r):
    for brand, rule in r.items():
        try:
            d = int(rule["days"])
        except (KeyError, TypeError, ValueError):
            raise WarrantyError(f"{brand}: days must be a whole number.")
        if d < 0 or d > 3650:
            raise WarrantyError(f"{brand}: days out of range.")
    files.write(files.path_for(RULES_FILE), r)
    return r


def window(brand, line="", r=None):
    """(days, verified, note) for a brand / model line."""
    r = r or rules()
    rule = r.get(brand)
    if rule is None:
        return DEFAULT_DAYS, False, ("Brand not in the list - 60 days used; "
                                     "check the warranty card.")
    days = rule.get("lines", {}).get(line, rule["days"]) if line else \
        rule["days"]
    verified = rule.get("verified", False) and "UNVERIFIED" not in line
    return int(days), bool(verified), rule.get("note", "")


def blank():
    return {"kind": KIND, "version": 1, "units": []}


def default_path():
    return files.path_for(FILE)


def load(path=None):
    return files.read(path or default_path(), KIND, blank)


def save(store, path=None):
    return files.write(path or default_path(), store)


def entry(store, equipment_id):
    return next((u for u in store["units"]
                 if u["equipment_id"] == equipment_id), None)


def set_unit(store, equipment_id, brand, installed="", line="",
             commercial=False, unit_text="", reapply=False):
    """Give a unit its register-by date (installed blank: "install date
    needed"). A unit that already has one keeps it unless reapply."""
    brand = files.txt(brand, 80)
    if not brand:
        raise WarrantyError("Pick the brand.")
    try:
        inst = files.iso_date(installed, "Install date")
    except files.FileError as e:
        raise WarrantyError(str(e)) from e
    u = entry(store, equipment_id)
    if u is not None and u.get("window_days") is not None and not reapply \
            and u.get("installed") == inst and u["brand"] == brand:
        return u
    days, verified, note = window(brand, line)
    row = {"equipment_id": equipment_id, "brand": brand,
           "line": files.txt(line, 80), "installed": inst,
           "commercial": bool(commercial), "unit": files.txt(unit_text, 200),
           "window_days": days, "verified": verified, "note": note,
           "register_by": (dt.date.fromisoformat(inst) +
                           dt.timedelta(days=days)).isoformat()
           if inst else "", "registered_on": (u or {}).get("registered_on",
                                                           "")}
    if u is None:
        store["units"].append(row)
    else:
        u.clear()
        u.update(row)
    return row


def mark_registered(store, equipment_id, when=None, confirmation=""):
    u = entry(store, equipment_id)
    if u is None:
        raise WarrantyError("Set the brand and install date first.")
    try:
        u["registered_on"] = files.iso_date(when or dt.date.today(),
                                            "Registered on", blank_ok=False)
    except files.FileError as e:
        raise WarrantyError(str(e)) from e
    u["confirmation"] = files.txt(confirmation, 80)
    return u


def due(store, today=None):
    """[(register_by or "", unit, what, late, equipment_id)] for units not
    registered."""
    today = today or dt.date.today()
    if isinstance(today, str):
        today = dt.date.fromisoformat(today)
    out = []
    for u in store["units"]:
        if u.get("registered_on"):
            continue
        name = u.get("unit") or u["brand"]
        if not u.get("register_by"):
            out.append(("", name, "Install date needed for the "
                                  "registration countdown", False,
                        u["equipment_id"]))
            continue
        by = dt.date.fromisoformat(u["register_by"])
        left = (by - today).days
        what = (f"Register with {u['brand']} by {by} ({left} days left"
                + ("" if u.get("verified") else "; window UNVERIFIED")
                + ")") if left >= 0 else \
            f"Registration window with {u['brand']} closed on {by}"
        if u.get("commercial"):
            what += " - commercial unit: check the commercial warranty"
        out.append((u["register_by"], name, what, left < 0,
                    u["equipment_id"]))
    out.sort(key=lambda r: (r[0] == "", r[0]))
    return out


def billing_warning(wo, records, today=None):
    """Text when the ticket's unit is still under warranty and the ticket
    bills time or parts to the customer - or ""."""
    from ..estimating import service as records_api
    if not wo.get("equipment_id") or wo.get("billing") == "agreement":
        return ""
    eq = records_api.find(records, wo["equipment_id"]) if records else None
    if not eq or "kind" not in eq:
        return ""
    today = today or dt.date.today()
    if isinstance(today, str):
        today = dt.date.fromisoformat(today)
    st = records_api.warranty_status(eq, today)
    if st in ("active", "expiring"):
        end = records_api.warranty_end(eq)
        return (f"This unit is under warranty until {end}. Check whether "
                "this is warranty work before billing the customer.")
    return ""


def brand_of(make, r=None):
    """The rule brand for a make written on the record ("goodman", "Amer.
    Standard"...), or the make itself when no rule matches."""
    make = " ".join(str(make or "").split())
    if not make:
        return ""
    low = make.lower()
    for brand in (r or rules()):
        for part in brand.lower().split(" / "):
            first = part.split()[0]
            if low == part or low.startswith(first) or first in low.split():
                return brand
    return make


def sync_from_records(store, records, ids=None, commercial=False):
    """Give every unit on the service records that has a make a register-by
    date (installed blank: "install date needed"). Units already tracked
    keep their window. `ids` limits it (e.g. the units a handover just
    added). Returns the equipment ids touched."""
    r = rules()
    done = []
    for eq in records.get("equipment", []):
        if ids is not None and eq["id"] not in ids:
            continue
        if not eq.get("make"):
            continue
        brand = brand_of(eq["make"], r)
        text = " ".join(p for p in (eq.get("kind"), eq.get("make"),
                                    eq.get("model"), eq.get("serial")) if p)
        set_unit(store, eq["id"], brand, installed=eq.get("installed") or "",
                 commercial=commercial, unit_text=text)
        done.append(eq["id"])
    return done
