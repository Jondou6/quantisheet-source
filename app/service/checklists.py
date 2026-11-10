"""Maintenance checklists with readings (QuantiSheet 1.2, #8).

A checklist is a list of steps (check: done / not done / n.a.) and
readings (a number with its unit). Each completed checklist is kept per
unit and per work order, so a reading can be followed over time (suction
pressure, temperature split, amps...).

The templates are data, not code: the starting set below is copied into
service_checklist_templates.json in the data folder the first time it is
changed, and that file wins from then on. A reading may have a "watch"
range (low / high): outside it the reading is marked "check" - a flag for
the tech, never a pass/fail ruling. The starting templates carry no
ranges; the shop's own tech sets them (they depend on the equipment and
the day's conditions).
"""
import copy
import datetime as dt
import json
import os

from .. import dmoney
from . import files

FILE = "service_checklists.json"
KIND = "service_checklists"
TEMPLATES_FILE = "service_checklist_templates.json"

DEFAULT_TEMPLATES = {
    "cooling": {
        "name": "Cooling tune-up",
        "items": [
            {"key": "filter", "label": "Air filter checked / replaced",
             "kind": "check"},
            {"key": "coil_clean", "label": "Condenser coil cleaned",
             "kind": "check"},
            {"key": "drain", "label": "Condensate drain clear",
             "kind": "check"},
            {"key": "elec", "label": "Electrical connections tightened",
             "kind": "check"},
            {"key": "volts", "label": "Supply voltage", "kind": "reading",
             "unit": "V"},
            {"key": "comp_amps", "label": "Compressor amps",
             "kind": "reading", "unit": "A"},
            {"key": "fan_amps", "label": "Condenser fan amps",
             "kind": "reading", "unit": "A"},
            {"key": "cap_uf", "label": "Run capacitor", "kind": "reading",
             "unit": "uF"},
            {"key": "suction", "label": "Suction pressure", "kind": "reading",
             "unit": "psig"},
            {"key": "head", "label": "Liquid / head pressure",
             "kind": "reading", "unit": "psig"},
            {"key": "superheat", "label": "Superheat", "kind": "reading",
             "unit": "F"},
            {"key": "subcool", "label": "Subcooling", "kind": "reading",
             "unit": "F"},
            {"key": "return_t", "label": "Return air temperature",
             "kind": "reading", "unit": "F"},
            {"key": "supply_t", "label": "Supply air temperature",
             "kind": "reading", "unit": "F"},
        ]},
    "heating": {
        "name": "Heating tune-up (gas furnace)",
        "items": [
            {"key": "filter", "label": "Air filter checked / replaced",
             "kind": "check"},
            {"key": "burners", "label": "Burners inspected / cleaned",
             "kind": "check"},
            {"key": "flame_sensor", "label": "Flame sensor cleaned",
             "kind": "check"},
            {"key": "hx", "label": "Heat exchanger inspected",
             "kind": "check"},
            {"key": "venting", "label": "Venting inspected", "kind": "check"},
            {"key": "gas_in", "label": "Inlet gas pressure",
             "kind": "reading", "unit": "in. w.c."},
            {"key": "gas_man", "label": "Manifold gas pressure",
             "kind": "reading", "unit": "in. w.c."},
            {"key": "flame_ua", "label": "Flame signal", "kind": "reading",
             "unit": "uA"},
            {"key": "temp_rise", "label": "Temperature rise",
             "kind": "reading", "unit": "F"},
            {"key": "co_flue", "label": "CO in flue", "kind": "reading",
             "unit": "ppm"},
        ]},
    "water_heater": {
        "name": "Water heater service",
        "items": [
            {"key": "flush", "label": "Tank flushed", "kind": "check"},
            {"key": "anode", "label": "Anode rod checked", "kind": "check"},
            {"key": "tpr", "label": "T&P relief valve tested",
             "kind": "check"},
            {"key": "venting", "label": "Venting inspected", "kind": "check"},
            {"key": "set_t", "label": "Thermostat setting", "kind": "reading",
             "unit": "F"},
            {"key": "outlet_t", "label": "Hot water temperature at tap",
             "kind": "reading", "unit": "F"},
            {"key": "gas_in", "label": "Inlet gas pressure",
             "kind": "reading", "unit": "in. w.c."},
        ]},
}
STATES = ("done", "not done", "n/a", "")


class ChecklistError(ValueError):
    pass


def templates():
    out = copy.deepcopy(DEFAULT_TEMPLATES)
    p = files.path_for(TEMPLATES_FILE)
    if os.path.isfile(p):
        try:
            with open(p, encoding="utf-8") as f:
                saved = json.load(f)
            if isinstance(saved, dict):
                out.update(saved)
        except (OSError, ValueError):
            pass
    return out


def save_templates(tpls):
    for key, t in tpls.items():
        if not t.get("name") or not isinstance(t.get("items"), list):
            raise ChecklistError(f"Template {key}: a name and items needed.")
        seen = set()
        for it in t["items"]:
            if it.get("kind") not in ("check", "reading") or \
                    not it.get("key") or it["key"] in seen:
                raise ChecklistError(f"Template {key}: each item needs a "
                                     "unique key and kind check/reading.")
            seen.add(it["key"])
            for b in ("low", "high"):
                if it.get(b) not in (None, "") and \
                        dmoney.bad(it[b], blank_ok=False):
                    raise ChecklistError(f"{it['label']}: {b} isn't a "
                                         "number.")
    files.write(files.path_for(TEMPLATES_FILE), tpls)


def blank():
    return {"kind": KIND, "version": 1, "done": []}


def default_path():
    return files.path_for(FILE)


def load(path=None):
    return files.read(path or default_path(), KIND, blank)


def save(store, path=None):
    return files.write(path or default_path(), store)


def _watch(item, value):
    if value in ("", None):
        return ""
    v = dmoney.D(value)
    lo, hi = item.get("low"), item.get("high")
    if lo not in (None, "") and v < dmoney.D(lo):
        return "check (low)"
    if hi not in (None, "") and v > dmoney.D(hi):
        return "check (high)"
    return ""


def record(store, template_key, values, equipment_id="", work_order_id="",
           when=None, tech="", notes="", tpls=None):
    """Keep one completed checklist. values: {item key: state or number}."""
    tpls = tpls or templates()
    t = tpls.get(template_key)
    if t is None:
        raise ChecklistError("Pick a checklist.")
    if not equipment_id and not work_order_id:
        raise ChecklistError("Pick the unit (or the work order).")
    rows = []
    for it in t["items"]:
        v = values.get(it["key"], "")
        v = "" if v is None else str(v).strip()
        if it["kind"] == "check":
            if v not in STATES:
                raise ChecklistError(f"{it['label']}: done, not done or n/a.")
            rows.append({"key": it["key"], "label": it["label"],
                         "kind": "check", "value": v})
        else:
            if v and dmoney.bad(v, blank_ok=False):
                raise ChecklistError(f"{it['label']}: {v!r} isn't a number.")
            rows.append({"key": it["key"], "label": it["label"],
                         "kind": "reading", "unit": it.get("unit", ""),
                         "value": format(dmoney.D(v).normalize(), "f")
                         if v else "", "watch": _watch(it, v)})
    try:
        d = files.iso_date(when or dt.date.today(), "Date", blank_ok=False)
    except files.FileError as e:
        raise ChecklistError(str(e)) from e
    row = {"id": files.new_id(), "template": template_key,
           "name": t["name"], "date": d, "equipment_id": equipment_id,
           "work_order_id": work_order_id, "tech": files.txt(tech),
           "notes": files.txt(notes, 1000), "items": rows}
    store["done"].append(row)
    return row["id"]


def for_unit(store, equipment_id):
    return sorted((c for c in store["done"]
                   if c["equipment_id"] == equipment_id),
                  key=lambda c: c["date"])


def for_work_order(store, wo_id):
    return [c for c in store["done"] if c["work_order_id"] == wo_id]


def trend(store, equipment_id, key):
    """[(date, value, unit, watch)] for one reading on one unit, oldest
    first."""
    out = []
    for c in for_unit(store, equipment_id):
        for it in c["items"]:
            if it["key"] == key and it["kind"] == "reading" and it["value"]:
                out.append((c["date"], it["value"], it.get("unit", ""),
                            it.get("watch", "")))
    return out


def change_text(points):
    """'up 12.5 psig since 2026-04-01' from a trend, or ''."""
    if len(points) < 2:
        return ""
    (d0, v0, u, _w), (_d1, v1, _u, _w2) = points[0], points[-1]
    delta = dmoney.D(v1) - dmoney.D(v0)
    if delta == 0:
        return f"no change since {d0}"
    word = "up" if delta > 0 else "down"
    return f"{word} {format(abs(delta).normalize(), 'f')} {u} since {d0}"


def printable_pdf(template_key, path, wo=None, comp=None, tpls=None):
    """A paper checklist (also fillable), for techs on paper."""
    from .pdfdoc import Sheet
    t = (tpls or templates())[template_key]
    sheet = Sheet(t["name"], comp, subtitle=(wo or {}).get("number", ""))
    if wo:
        sheet.text(36, sheet.y + 12, f"{wo['customer']}   {wo['site']}   "
                   f"{wo.get('unit') or ''}", 9, True)
        sheet.y += 20
    sheet.section("01", "Checklist")
    for it in t["items"]:
        sheet.need(22)
        sheet.y += 20
        if it["kind"] == "check":
            sheet.combo(f"c_{it['key']}", (36, sheet.y - 12, 110, sheet.y + 2),
                        ["", "done", "not done", "n/a"])
            sheet.text(120, sheet.y, it["label"], 9)
        else:
            sheet.text_field(f"c_{it['key']}",
                             (36, sheet.y - 12, 110, sheet.y + 2))
            sheet.text(120, sheet.y, f"{it['label']} ({it.get('unit', '')})",
                       9)
    sheet.y += 26
    sheet.label(36, sheet.y, "Notes")
    sheet.text_field("c_notes", (36, sheet.y + 4, 560, sheet.y + 60),
                     multiline=True)
    return sheet.save(path)
