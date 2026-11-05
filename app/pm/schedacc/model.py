"""Plain records for a compiled schedule.

Durations are stored in hours, the way a CPM engine keeps them, and shown
in workdays of the activity's own calendar (hours / hours-per-day). Dates
on the document are ISO strings so a draft can be saved as JSON.

Activity types follow the usual six: task dependent, resource dependent,
level of effort, start milestone, finish milestone, WBS summary.
Relationship types are FS, SS, FF and SF. Constraint names are the usual
ten (see ``cpm.py``).
"""
import datetime as _dt

HOURS_PER_DAY = 8

TASK = "task"
RESOURCE = "resource"
LOE = "loe"
START_MS = "start_ms"
FINISH_MS = "finish_ms"
WBS_SUM = "wbs_summary"
MILESTONES = (START_MS, FINISH_MS)
DERIVED = (LOE, WBS_SUM)          # dates come from other activities

# PMXML / display labels. Internal codes stay short.
TYPE_LABEL = {
    TASK: "Task Dependent",
    RESOURCE: "Resource Dependent",
    LOE: "Level of Effort",
    START_MS: "Start Milestone",
    FINISH_MS: "Finish Milestone",
    WBS_SUM: "WBS Summary",
}

REL_TYPES = ("FS", "SS", "FF", "SF")
REL_LABEL = {
    "FS": "Finish to Start",
    "SS": "Start to Start",
    "FF": "Finish to Finish",
    "SF": "Start to Finish",
}

# Constraint codes. Forward / backward behaviour is in cpm.py.
ASAP = ""
MSO = "start_on"             # Start On
MSOB = "start_on_or_before"  # Start On or Before
MSOA = "start_on_or_after"   # Start On or After
MEO = "finish_on"
MEOB = "finish_on_or_before"
MEOA = "finish_on_or_after"
ALAP = "as_late_as_possible"
MAND_START = "mandatory_start"
MAND_FIN = "mandatory_finish"

CONSTRAINT_LABEL = {
    ASAP: "",
    MSO: "Start On",
    MSOB: "Start On or Before",
    MSOA: "Start On or After",
    MEO: "Finish On",
    MEOB: "Finish On or Before",
    MEOA: "Finish On or After",
    ALAP: "As Late As Possible",
    MAND_START: "Mandatory Start",
    MAND_FIN: "Mandatory Finish",
}

# DCMA PAM 200.1 treats these as hard constraints.
HARD_CONSTRAINTS = (MSO, MSOB, MEO, MEOB, MAND_START, MAND_FIN)

DUR_FIXED_UNITS = "fixed_duration_units"          # Fixed Duration and Units
DUR_FIXED_RATE = "fixed_duration_units_time"      # Fixed Duration and Units/Time
DUR_FIXED_QTY = "fixed_units"
DUR_FIXED_UPH = "fixed_units_time"

PCT_DURATION = "duration"
PCT_PHYSICAL = "physical"
PCT_UNITS = "units"
PCT_SCOPE = "scope"

NOT_STARTED = "not_started"
ACTIVE = "active"
COMPLETE = "complete"

PRIORITY = ("top", "high", "normal", "low", "lowest")


def as_date(value):
    if value is None or value == "":
        return None
    if isinstance(value, _dt.datetime):
        return value.date()
    if isinstance(value, _dt.date):
        return value
    text = str(value).strip()
    if not text:
        return None
    return _dt.date.fromisoformat(text[:10])


def iso(value):
    d = as_date(value)
    return d.isoformat() if d else ""


def new_schedule(name="Project", start=None, data_date=None):
    start = as_date(start) or _dt.date.today()
    data = as_date(data_date) or start
    return {
        "project": {
            "name": name or "Project",
            "id": "PRJ",
            "start": start.isoformat(),
            "data_date": data.isoformat(),
            "must_finish": "",
            "finish": "",
            "early_finish": "",
            "critical_hours": 0,
            "hours_per_day": HOURS_PER_DAY,
            "baseline": "",
            "calendar": "5day",
        },
        "options": default_options(),
        "calendars": {},
        "wbs": [],
        "activities": [],
        "relationships": [],
        "roles": [],
        "resources": [],
        "assignments": [],
        "codes": [],
        "facts": [],
        "conflicts": [],
        "baselines": [],
        "log": [],
        "rubric": {},
        "health": {},
        "narrative": "",
        "review": [],
        "status": "incomplete",
        "ingest": {},
    }


def default_options():
    """Scheduling options. The factory default for which calendar a lag
    uses is not the same in every version of the reference engine; this
    compiler defaults to the successor activity's calendar because a
    calendar-day cure has to be able to start the next morning, including
    a Saturday. All four lag calendars are implemented.
    """
    return {
        "out_of_sequence": "retained",     # retained | override | actual
        "ss_lag_from": "early",            # early | actual
        "total_float": "smallest",         # start | finish | smallest
        "critical": "float",               # float | longest
        "lag_calendar": "successor",       # predecessor | successor | 24hour | project
        "open_ends_critical": False,
        "use_expected_finish": True,
        "ignore_external": True,
        "float_paths": 5,
        "float_paths_use_total_float": False,
        "near_critical_days": 10,
        "level": False,
        "recalculate_costs": True,
    }


def blank_activity(code, name, **kw):
    act = {
        "id": 0,
        "code": code,
        "name": name,
        "wbs": kw.get("wbs") or "1",
        "calendar": kw.get("calendar") or "5day",
        "type": kw.get("type") or TASK,
        "duration_type": kw.get("duration_type") or DUR_FIXED_UNITS,
        "pct_type": kw.get("pct_type") or PCT_DURATION,
        "status": kw.get("status") or NOT_STARTED,
        "cls": kw.get("cls") or "",
        "division": kw.get("division") or "",
        "cost_code": kw.get("cost_code") or "",
        "orig_hours": float(kw.get("orig_hours") or 0),
        "remain_hours": float(kw.get("remain_hours")
                              if kw.get("remain_hours") is not None
                              else kw.get("orig_hours") or 0),
        "actual_hours": 0.0,
        "percent": float(kw.get("percent") or 0),
        "constraint": kw.get("constraint") or "",
        "constraint_date": iso(kw.get("constraint_date")),
        "constraint2": kw.get("constraint2") or "",
        "constraint2_date": iso(kw.get("constraint2_date")),
        "expected_finish": iso(kw.get("expected_finish")),
        "actual_start": iso(kw.get("actual_start")),
        "actual_finish": iso(kw.get("actual_finish")),
        "suspend": iso(kw.get("suspend")),
        "resume": iso(kw.get("resume")),
        "priority": kw.get("priority") or "normal",
        "roles": list(kw.get("roles") or ()),
        "budget_cost": float(kw.get("budget_cost") or 0),
        "actual_cost": float(kw.get("actual_cost") or 0),
        "chain_id": kw.get("chain_id") or "",
        "template_slot": kw.get("template_slot") or "",
        "duration_kind": kw.get("duration_kind") or "estimated",
        "basis": kw.get("basis") or "",
        "family": kw.get("family") or "",
        "quantity": kw.get("quantity"),
        "quantity_unit": kw.get("quantity_unit") or "",
        "citations": list(kw.get("citations") or ()),
        "takeoff_ids": list(kw.get("takeoff_ids") or ()),
        "human_edited": False,
        "confirmed": False,
        "by_others": bool(kw.get("by_others")),
        "fabrication_na": bool(kw.get("fabrication_na")),
        "phase": kw.get("phase") or "",
        "area": kw.get("area") or "",
        "steps": list(kw.get("steps") or ()),
        "external_early_start": "",
        "external_late_finish": "",
    }
    return act


def is_milestone(act):
    return act.get("type") in MILESTONES or (
        act.get("type") not in DERIVED and float(act.get("orig_hours") or 0) == 0
        and act.get("type") != TASK)


def workdays_of(act, hours=None):
    """Duration in the activity calendar's workdays."""
    from .calendar import hours_per_day
    hpd = hours_per_day(act.get("calendar") or "5day", act)
    h = act.get("remain_hours") if hours is None else hours
    if h is None:
        h = act.get("orig_hours") or 0
    if act.get("type") in MILESTONES:
        return 0
    return float(h) / hpd if hpd else 0.0
