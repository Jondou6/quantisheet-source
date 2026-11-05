"""Trade sequencing as data, not as a paragraph in the compiler.

Each rule names two activity classes, a relationship and a lag in
workdays of the lag calendar (0 unless a spec lag is applied later).
The company can edit the table; the copy in the user data folder wins.
A rule does nothing when one of the classes is not in the schedule, so
a tenant improvement that has no structure simply skips the structure
rules.
"""
import json
import os

FILE = "schedacc_rules.json"

# pred class, succ class, type, lag workdays, why it exists
_ROWS = (
    ("ntp", "mobilization", "FS", 0,
     "Work starts at notice to proceed."),
    ("ntp", "swppp", "FS", 0,
     "Erosion control is in place before the ground is opened."),
    ("mobilization", "temp_facilities", "FS", 0, ""),
    ("mobilization", "temp_utilities", "FS", 0, ""),
    ("swppp", "underground", "FS", 0, ""),
    ("underground", "foundations", "FS", 0,
     "Underground utilities and under-slab rough-in finish before foundations."),
    ("underground", "slab", "FS", 0,
     "Under-slab rough-in finishes before the slab is placed."),
    ("foundations", "slab", "FS", 0, ""),
    ("slab", "cure", "FS", 0, ""),
    ("foundations", "cure", "FS", 0, ""),
    ("cure", "structure", "FS", 0,
     "Structure waits on the concrete cure."),
    ("structure", "envelope", "FS", 0, ""),
    ("structure", "roofing", "FS", 0, ""),
    ("roofing", "plumb_rough", "FS", 0,
     "Interior rough-in starts after the roof is on."),
    ("roofing", "hvac_rough", "FS", 0, ""),
    ("roofing", "elec_rough", "FS", 0, ""),
    ("envelope", "plumb_rough", "FS", 0, ""),
    ("envelope", "hvac_rough", "FS", 0, ""),
    ("envelope", "elec_rough", "FS", 0, ""),
    ("envelope", "fire_rough", "FS", 0, ""),
    ("demolition", "plumb_rough", "FS", 0,
     "Rough-in follows demolition on a renovation."),
    ("demolition", "hvac_rough", "FS", 0, ""),
    ("demolition", "elec_rough", "FS", 0, ""),
    ("demolition", "cover", "FS", 0, ""),
    ("plumb_rough", "rough_in_inspection", "FS", 0,
     "Rough-in inspection is a hold point before cover-up."),
    ("hvac_rough", "rough_in_inspection", "FS", 0, ""),
    ("elec_rough", "rough_in_inspection", "FS", 0, ""),
    ("fire_rough", "rough_in_inspection", "FS", 0, ""),
    ("rough_in_inspection", "cover", "FS", 0,
     "Cover-up waits on the rough-in inspection."),
    ("footing_inspection", "slab", "FS", 0, ""),
    ("cover", "finishes", "FS", 0, ""),
    ("finishes", "trim", "FS", 0, ""),
    ("trim", "startup", "FS", 0, ""),
    ("startup", "tab", "FS", 0,
     "Startup and test-and-balance finish before commissioning."),
    ("tab", "commissioning", "FS", 0, ""),
    ("pressure_test", "startup", "FS", 0, ""),
    ("commissioning", "punch", "FS", 0, ""),
    ("final_inspection", "substantial", "FS", 0, ""),
    ("punch", "margin", "FS", 0, ""),
    ("margin", "substantial", "FS", 0,
     "Schedule margin is a visible activity, not hidden inside durations."),
    ("punch", "substantial", "FS", 0, ""),
    ("substantial", "closeout", "FS", 0, ""),
    ("substantial", "demobilization", "FS", 0, ""),
    ("closeout", "final", "FS", 0, ""),
    ("demobilization", "final", "FS", 0, ""),
    ("training", "final", "FS", 0, ""),
    # Service and repair work.
    ("mobilization", "isolate", "FS", 0,
     "The system is isolated before it is opened."),
    ("isolate", "diagnose", "FS", 0, ""),
    ("diagnose", "service_repair", "FS", 0, ""),
    ("service_repair", "pressure_test", "FS", 0, ""),
    ("service_repair", "startup", "FS", 0, ""),
    ("startup", "turnover", "FS", 0, ""),
    ("turnover", "closeout", "FS", 0, ""),
    ("walkthrough", "turnover", "FS", 0, ""),
)


def defaults():
    out = []
    for pred, succ, typ, lag, note in _ROWS:
        out.append({"id": f"{pred}_to_{succ}_{typ}",
                    "pred_cls": pred, "succ_cls": succ, "type": typ,
                    "lag_days": lag, "note": note})
    return out


def load(directory=None):
    rules = defaults()
    if not directory:
        return rules
    try:
        with open(os.path.join(directory, FILE), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return rules
    if isinstance(data, list) and data:
        return data
    if isinstance(data, dict) and isinstance(data.get("rules"), list):
        return data["rules"]
    return rules


def save(directory, rules):
    os.makedirs(directory, exist_ok=True)
    dest = os.path.join(directory, FILE)
    tmp = dest + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"rules": list(rules or [])}, fh, indent=2)
    os.replace(tmp, dest)
    return dest
