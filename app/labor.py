"""Crews, labor rates and labor adjustment factors.

Estimators price labor as crews ("one journeyman and one apprentice"),
not bare hours. A crew's blended rate is the average of its members'
rates; assembly parts can name a crew, and hours are scaled by adjustment
factors for height, working conditions, shift and season.
(Built on the Venice AI draft.)
"""
from . import settings

CREWS = {
    "C-2": {"name": "Carpenter + helper",
            "members": [["Carpenter", 1], ["Helper", 1]]},
    "D-2": {"name": "Drywall hanger + taper",
            "members": [["Drywall Hanger", 1], ["Taper", 1]]},
    "E-2": {"name": "Electrician + apprentice",
            "members": [["Electrician", 1], ["Apprentice", 1]]},
    "P-2": {"name": "Plumber + apprentice",
            "members": [["Plumber", 1], ["Apprentice", 1]]},
    "M-3": {"name": "Mason crew (2 masons, 1 tender)",
            "members": [["Mason", 2], ["Mason Tender", 1]]},
    "S-3": {"name": "Ironworker gang",
            "members": [["Ironworker", 2], ["Apprentice", 1]]},
    "F-4": {"name": "Concrete finishing crew",
            "members": [["Cement Finisher", 2], ["Laborer", 2]]},
    "L-2": {"name": "Laborer + operator",
            "members": [["Laborer", 1], ["Operator", 1]]},
    "PT-1": {"name": "Painter", "members": [["Painter", 1]]},
    "L-1": {"name": "Laborers", "members": [["Laborer", 2]]},
    "R-2": {"name": "Rebar crew", "members": [["Rodman", 2]]},
    "RF-3": {"name": "Roofing crew (2 roofers, 1 laborer)",
             "members": [["Roofer", 2], ["Laborer", 1]]},
    "SM-2": {"name": "Sheet metal + HVAC mechanic",
             "members": [["Sheet Metal Worker", 1], ["HVAC Mechanic", 1]]},
    "SF-2": {"name": "Sprinkler fitter + apprentice",
             "members": [["Sprinkler Fitter", 1], ["Plumber Helper", 1]]},
    "G-2": {"name": "Glaziers", "members": [["Glazier", 2]]},
    "IN-2": {"name": "Insulators", "members": [["Insulator", 2]]},
    "T-2": {"name": "Tile setter + helper",
            "members": [["Tile Setter", 1], ["Helper", 1]]},
    "FL-2": {"name": "Floor layer + helper",
             "members": [["Floor Layer", 1], ["Helper", 1]]},
    "EL-2": {"name": "Elevator constructors",
             "members": [["Elevator Constructor", 2]]},
    "MW-2": {"name": "Millwrights", "members": [["Millwright", 2]]},
    "PF-2": {"name": "Pipefitter + welder",
             "members": [["Plumber", 1], ["Welder", 1]]},
    "UT-4": {"name": "Utility crew (pipelayer, 2 laborers, operator)",
             "members": [["Pipelayer", 1], ["Laborer", 2], ["Operator", 1]]},
    "PV-5": {"name": "Paving crew",
             "members": [["Paving Operator", 2], ["Laborer", 2],
                         ["Truck Driver", 1]]},
    "PD-4": {"name": "Pile driving crew",
             "members": [["Pile Driver", 1], ["Operator", 1], ["Laborer", 2]]},
    "LV-1": {"name": "Low-voltage / fire alarm tech",
             "members": [["Low Voltage Tech", 1]]},
    "TC-1": {"name": "Telecom tech", "members": [["Telecom Tech", 1]]},
    "AB-3": {"name": "Abatement crew", "members": [["Abatement Worker", 3]]},
    "LS-2": {"name": "Landscape crew", "members": [["Landscaper", 2]]},
    "FN-2": {"name": "Fence crew", "members": [["Fence Erector", 2]]},
    "SUP": {"name": "Superintendent", "members": [["Superintendent", 1]]},
    "PM": {"name": "Project manager", "members": [["Project Manager", 1]]},
}

DEFAULT_RATES = {
    "Carpenter": 48.0, "Helper": 32.0, "Drywall Hanger": 46.0,
    "Taper": 47.0, "Electrician": 58.0, "Apprentice": 34.0,
    "Plumber": 60.0, "Mason": 50.0, "Mason Tender": 36.0,
    "Ironworker": 62.0, "Cement Finisher": 47.0, "Laborer": 34.0,
    "Operator": 52.0, "Painter": 42.0, "Rodman": 49.0, "Roofer": 41.0,
    "Sheet Metal Worker": 47.0, "HVAC Mechanic": 47.0,
    "Sprinkler Fitter": 50.0, "Plumber Helper": 32.0, "Glazier": 42.0,
    "Insulator": 37.0, "Tile Setter": 41.0, "Floor Layer": 41.0,
    "Elevator Constructor": 79.0, "Millwright": 48.0, "Welder": 39.0,
    "Pipelayer": 36.0, "Paving Operator": 39.0, "Truck Driver": 42.0,
    "Pile Driver": 52.0, "Low Voltage Tech": 43.0, "Telecom Tech": 46.0,
    "Abatement Worker": 36.0, "Landscaper": 28.0, "Fence Erector": 34.0,
    "Superintendent": 78.0, "Project Manager": 88.0,
}

# a factor above 1 takes more hours
ADJUSTMENTS = {
    "height": {"Floor level": 1.0, "Up to 20 ft": 1.05, "Over 20 ft": 1.18},
    "conditions": {"Open / new": 1.0, "Occupied": 1.12, "Congested": 1.25,
                   "Confined": 1.4},
    "shift": {"Day": 1.0, "Second shift": 1.1, "Third shift": 1.15,
              "Overtime": 1.5},
    "season": {"Normal": 1.0, "Winter": 1.1, "Extreme heat/cold": 1.2},
    # from the loaded-rate engine's site conditions (labor.py you sent)
    "building": {"Ground floor": 1.0, "Upper floors": 1.10},
    "work": {"New work": 1.0, "Renovation / retrofit": 1.20},
    "site": {"Normal": 1.0, "Remote": 1.10},
    "schedule": {"Normal": 1.0, "Accelerated": 1.20},
    "quantity": {"Normal": 1.0, "Small quantities": 1.25},
    "finish": {"Standard": 1.0, "High finish": 1.15},
    "rules": {"Normal": 1.0, "Restrictive work rules": 1.05},
}


def crews():
    """Built-in crews plus your own (settings "crews")."""
    out = {k: dict(v) for k, v in CREWS.items()}
    for code, spec in (settings.get("crews") or {}).items():
        if isinstance(spec, dict) and spec.get("members"):
            out[str(code)] = spec
    return out


def save_crew(code, name, members):
    """members: [[trade, count], ...]"""
    clean = [[str(t).strip(), float(n)] for t, n in members
             if str(t).strip() and float(n) > 0]
    if not code or not clean:
        raise ValueError("A crew needs a code and at least one member.")
    cur = dict(settings.get("crews") or {})
    cur[code] = {"name": name or code, "members": clean}
    settings.set("crews", cur)


def rates(job_rates=None):
    out = dict(DEFAULT_RATES)
    out.update({k: float(v) for k, v in (settings.get("labor_rates") or {})
                .items()})
    out.update({k: float(v) for k, v in (job_rates or {}).items()})
    return out


def crew_rate(crew, job_rates=None):
    """Blended $ per crew-hour, or None if the crew is unknown."""
    spec = crews().get(crew) if isinstance(crew, str) else crew
    if not spec:
        return None
    table = rates(job_rates)
    people = sum(float(n) for _, n in spec["members"])
    if not people:
        return None
    cost = sum(float(n) * float(table.get(t, 45.0))
               for t, n in spec["members"])
    return cost / people


def crew_size(crew):
    spec = crews().get(crew) if isinstance(crew, str) else crew
    return sum(float(n) for _, n in spec["members"]) if spec else 1.0


def crew_days(hours, crew, hours_per_day=8.0):
    """Labor hours as days of the whole crew working together."""
    return float(hours) / (crew_size(crew) * hours_per_day)


def factor(adjust):
    """Combined multiplier for {"height": "Over 20 ft", ...}."""
    m = 1.0
    for group, choice in (adjust or {}).items():
        m *= float(ADJUSTMENTS.get(group, {}).get(choice, 1.0))
    return m


def describe(adjust):
    parts = [f"{choice}" for group, choice in (adjust or {}).items()
             if ADJUSTMENTS.get(group, {}).get(choice, 1.0) != 1.0]
    return ", ".join(parts)
