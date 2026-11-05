"""Company schedule templates, one per kind of work this office does.

Ground-up commercial, tenant improvement, MEP retrofit, and plumbing /
HVAC service. Defaults ship in this module. Edits are stored in the
user data folder and win over the defaults, slot by slot. Nothing here
is a company name or a logo.

A slot is included only when its project type matches and, when it names
divisions, at least one of those divisions is actually in the job.
General conditions (mobilization, closeout, the contract milestones) are
not tied to a trade division.
"""
import json
import os

FILE = "schedacc_templates.json"

BUILDING = ("ground_up_commercial", "tenant_improvement", "mep_retrofit")
ALL = BUILDING + ("plumbing_hvac_service",)
GROUND = ("ground_up_commercial",)
TI = ("tenant_improvement",)
MEP = ("mep_retrofit",)
SERVICE = ("plumbing_hvac_service",)

LABELS = {
    "ground_up_commercial": "Ground-up commercial",
    "tenant_improvement": "Tenant improvement",
    "mep_retrofit": "MEP retrofit",
    "plumbing_hvac_service": "Plumbing and HVAC service",
}

# code, name, wbs, division, class, workdays, calendar, roles,
# project types, divisions required (any one; empty = always)
_SLOTS = (
    ("NTP", "Notice to Proceed", "1.1", "01", "ntp", 0, "5day",
     (), ALL, ()),
    ("MOB", "Mobilization", "1.1", "01", "mobilization", 5, "5day",
     ("Superintendent",), BUILDING, ()),
    ("TEMP", "Temporary facilities", "1.1", "01", "temp_facilities", 5, "5day",
     ("Laborer",), BUILDING, ()),
    ("TUTIL", "Temporary utilities", "1.1", "01", "temp_utilities", 3, "5day",
     ("Electrician",), ("ground_up_commercial", "tenant_improvement"), ()),
    ("SWPPP", "Erosion and sediment control", "1.3", "31", "swppp", 5, "weather",
     ("Laborer",), GROUND, ()),
    ("DEMO", "Selective demolition", "1.3", "02", "demolition", 8, "5day",
     ("Laborer",), ("tenant_improvement", "mep_retrofit"), ("02",)),
    ("UG", "Underground utilities", "1.3", "31", "underground", 10, "weather",
     ("Operator",), GROUND, ("31", "33")),
    ("FOUND", "Foundations", "1.4", "03", "foundations", 10, "5day",
     ("Concrete crew",), GROUND, ("03",)),
    ("SLAB", "Slab on grade", "1.4", "03", "slab", 8, "5day",
     ("Concrete crew",), GROUND, ("03",)),
    ("CURE", "Concrete cure", "1.4", "03", "cure", 28, "7day",
     (), GROUND, ("03",)),
    ("STEEL", "Structural steel and deck", "1.4", "05", "structure", 15, "5day",
     ("Ironworker",), GROUND, ("05",)),
    ("MASON", "Masonry", "1.4", "04", "structure", 12, "5day",
     ("Mason",), BUILDING, ("04",)),
    ("WOOD", "Rough carpentry", "1.4", "06", "structure", 10, "5day",
     ("Carpenter",), BUILDING, ("06",)),
    ("ROOF", "Roofing", "1.5", "07", "roofing", 10, "weather",
     ("Roofer",), BUILDING, ("07",)),
    ("ENV", "Exterior enclosure", "1.5", "08", "envelope", 12, "weather",
     ("Carpenter",), BUILDING, ("08", "04")),
    ("OPEN", "Doors, frames and hardware", "1.5", "08", "openings", 5, "5day",
     ("Carpenter",), BUILDING, ("08",)),
    ("PLUMB", "Plumbing rough-in", "1.7", "22", "plumb_rough", 12, "5day",
     ("Plumber",), BUILDING, ("22",)),
    ("HVAC", "HVAC rough-in", "1.7", "23", "hvac_rough", 12, "5day",
     ("HVAC technician",), BUILDING, ("23",)),
    ("ELEC", "Electrical rough-in", "1.7", "26", "elec_rough", 12, "5day",
     ("Electrician",), BUILDING, ("26",)),
    ("FIRE", "Fire protection rough-in", "1.7", "21", "fire_rough", 8, "5day",
     ("Sprinkler fitter",), BUILDING, ("21",)),
    ("RINSP", "Rough-in inspection", "1.7", "01", "rough_in_inspection", 1, "5day",
     ("Inspector",), BUILDING, ("21", "22", "23", "26")),
    ("COVER", "Cover-up (drywall and ceilings)", "1.6", "09", "cover", 10, "5day",
     ("Drywall crew",), BUILDING, ("09",)),
    ("FINISH", "Finishes", "1.6", "09", "finishes", 12, "5day",
     ("Finishes crew",), BUILDING, ("09",)),
    ("TRIM", "MEP trim", "1.7", "22", "trim", 8, "5day",
     ("Plumber",), BUILDING, ("21", "22", "23", "26")),
    ("START", "Equipment startup", "1.8", "23", "startup", 5, "5day",
     ("HVAC technician",), BUILDING, ("22", "23", "26")),
    ("TAB", "Test and balance", "1.8", "23", "tab", 5, "5day",
     ("Balancer",), BUILDING, ("23",)),
    ("CX", "Commissioning", "1.8", "01", "commissioning", 10, "5day",
     ("Commissioning agent",), BUILDING, ()),
    ("PUNCH", "Punch list", "1.8", "01", "punch", 8, "5day",
     ("Superintendent",), BUILDING, ()),
    ("MARGIN", "Schedule margin", "1.8", "01", "margin", 5, "5day",
     ("Superintendent",), BUILDING, ()),
    ("SUBST", "Substantial Completion", "1.8", "01", "substantial", 0, "5day",
     (), ALL, ()),
    ("CLOSE", "Closeout documents, O&M and warranties", "1.8", "01", "closeout",
     10, "5day", ("Project engineer",), BUILDING, ()),
    ("TRAIN", "Owner training", "1.8", "01", "training", 3, "5day",
     ("Project engineer",), BUILDING, ()),
    ("DEMOB", "Demobilization", "1.1", "01", "demobilization", 3, "5day",
     ("Laborer",), BUILDING, ()),
    ("FINAL", "Final Completion", "1.8", "01", "final", 0, "5day",
     (), ALL, ()),
    # Plumbing and HVAC service. Short, and still a real network.
    ("SMOB", "Arrive and set up", "1.1", "01", "mobilization", 1, "5day",
     ("Technician",), SERVICE, ()),
    ("ISOL", "Isolate the system", "1.2", "22", "isolate", 1, "5day",
     ("Technician",), SERVICE, ()),
    ("DIAG", "Diagnose", "1.2", "22", "diagnose", 1, "5day",
     ("Technician",), SERVICE, ()),
    ("REPP", "Repair piping", "1.2", "22", "service_repair", 2, "5day",
     ("Plumber",), SERVICE, ("22",)),
    ("REPH", "Repair HVAC equipment", "1.2", "23", "service_repair", 2, "5day",
     ("HVAC technician",), SERVICE, ("23",)),
    ("PRESS", "Pressure test", "1.2", "22", "pressure_test", 1, "5day",
     ("Plumber",), SERVICE, ()),
    ("SINS", "Inspection hold point", "1.2", "01", "inspection", 1, "5day",
     ("Inspector",), SERVICE, ()),
    ("SSTART", "Startup", "1.3", "23", "startup", 1, "5day",
     ("Technician",), SERVICE, ()),
    ("SPROT", "Protect existing finishes", "1.1", "01", "temp_facilities", 1,
     "5day", ("Technician",), SERVICE, ()),
    ("SMAT", "Pick up materials", "1.2", "01", "material", 1, "5day",
     ("Technician",), SERVICE, ()),
    ("SWALK", "Customer walkthrough", "1.3", "01", "walkthrough", 1, "5day",
     ("Technician",), SERVICE, ()),
    ("STRAIN", "Customer training", "1.3", "01", "training", 1, "5day",
     ("Technician",), SERVICE, ()),
    ("STURN", "Turnover", "1.3", "01", "turnover", 1, "5day",
     ("Technician",), SERVICE, ()),
    ("SDOC", "Service closeout documents", "1.3", "01", "closeout", 2, "5day",
     ("Technician",), SERVICE, ()),
    ("SDEMOB", "Demobilize", "1.3", "01", "demobilization", 1, "5day",
     ("Technician",), SERVICE, ()),
    ("SPUNCH", "Punch corrections", "1.3", "01", "punch", 1, "5day",
     ("Technician",), SERVICE, ()),
)


def _slot(row):
    (code, name, wbs, div, cls, days, calendar, roles, types, needs) = row
    return {
        "code": code, "name": name, "wbs": wbs, "division": div, "cls": cls,
        "days": days, "calendar": calendar, "roles": list(roles),
        "types": list(types), "needs": list(needs),
        "milestone": days == 0 and cls in (
            "ntp", "substantial", "final") or code in ("NTP", "SUBST", "FINAL"),
    }


def default_library():
    return {
        "assumptions": {
            "default_crew_size": 4,
            "schedule_margin_days": 5,
            "weather_months": [],
            "fab_chunk_days": 40,
            "review_days": 10,
            "delivery_days": 3,
        },
        "slots": [_slot(r) for r in _SLOTS],
    }


def load(directory=None):
    lib = default_library()
    if not directory:
        return lib
    try:
        with open(os.path.join(directory, FILE), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return lib
    if not isinstance(data, dict):
        return lib
    if isinstance(data.get("assumptions"), dict):
        lib["assumptions"].update(data["assumptions"])
    saved = {s.get("code"): s for s in data.get("slots") or []
             if isinstance(s, dict) and s.get("code")}
    if saved:
        merged = []
        seen = set()
        for slot in lib["slots"]:
            if slot["code"] in saved:
                row = dict(slot)
                row.update({k: v for k, v in saved[slot["code"]].items()
                            if k in row or k in ("days", "name", "roles",
                                                 "calendar", "cls")})
                merged.append(row)
                seen.add(slot["code"])
            else:
                merged.append(slot)
        for code, row in saved.items():
            if code not in seen:
                merged.append(row)
        lib["slots"] = merged
    return lib


def save(directory, library):
    os.makedirs(directory, exist_ok=True)
    dest = os.path.join(directory, FILE)
    tmp = dest + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(library, fh, indent=2)
    os.replace(tmp, dest)
    return dest


def update_slot(directory, code, changes):
    """Write one slot back. Used when a person confirms a duration."""
    lib = load(directory)
    for slot in lib["slots"]:
        if slot.get("code") == code:
            slot.update(changes or {})
            break
    else:
        lib["slots"].append(dict(changes or {}, code=code))
    save(directory, lib)
    return lib


def slots_for(library, project_type, divisions, swppp=False):
    divs = set(divisions or ())
    out = []
    for slot in library.get("slots") or ():
        types = slot.get("types") or ()
        if types and project_type not in types:
            continue
        needs = slot.get("needs") or ()
        if slot.get("code") == "SWPPP":
            if project_type != "ground_up_commercial" and "31" not in divs \
                    and not swppp:
                continue
        elif needs and not (set(needs) & divs):
            continue
        out.append(dict(slot))
    return out
