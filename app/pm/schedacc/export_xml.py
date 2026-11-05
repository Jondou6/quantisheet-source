"""PMXML and MSPDI writers.

PMXML element names and the order they are written follow the business
object schema published with MPXJ 16.x as p6apibo.xsd (namespace
``.../P6/V25.12/API/BusinessObjects``), which mirrors the integration
schema. That check was against the published schema text, not against a
live import. Nested ``Activity``, ``WBS``, ``Relationship`` and
``Calendar`` elements under ``Project`` are in that schema's ProjectType.
Resource-assignment children are a smaller set; their full sequence was
not re-checked element by element.

MSPDI follows the element order already used by ``schedule.export_msproject``
(the order Project's importer checks). Relationship type codes match that
writer: 0 FF, 1 FS, 2 SF, 3 SS. Lag is tenths of a minute.

Losses when writing MSPDI, because that format has no place for them:

- a second constraint is dropped
- mandatory start / finish become must-start-on / must-finish-on
- resource-dependent work becomes an ordinary task
- level of effort becomes an ordinary task
- several calendars are written, but a lag calendar option is not
"""
import datetime as _dt
import xml.etree.ElementTree as ET

from .model import (
    CONSTRAINT_LABEL, REL_LABEL, TYPE_LABEL, as_date,
)

PM_NS = "http://xmlns.oracle.com/Primavera/P6/V25.12/API/BusinessObjects"
MSP_NS = "http://schemas.microsoft.com/project"

# MSP constraint integers. 4 is the code this program already writes for
# "start no earlier than".
_MSP_CONSTRAINT = {
    "": 0,
    "as_late_as_possible": 1,
    "start_on": 2,
    "mandatory_start": 2,
    "finish_on": 3,
    "mandatory_finish": 3,
    "start_on_or_after": 4,
    "start_on_or_before": 5,
    "finish_on_or_after": 6,
    "finish_on_or_before": 7,
}
_MSP_REL = {"FF": "0", "FS": "1", "SF": "2", "SS": "3"}
_DOW = ("Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
        "Saturday")


def export_pmxml(doc, path):
    """Write a PMXML schedule (.xml)."""
    ET.register_namespace("", PM_NS)
    root = ET.Element(f"{{{PM_NS}}}APIBusinessObjects")
    project = _el(root, "Project")
    pid = 1
    _text(project, "ActivityDefaultCalendarObjectId", "1")
    _text(project, "DataDate", _dtm((doc.get("project") or {}).get("data_date"), "08:00:00"))
    _text(project, "FinishDate", _dtm((doc.get("project") or {}).get("early_finish"), "16:59:00"))
    _text(project, "Id", (doc.get("project") or {}).get("id") or "PRJ")
    if (doc.get("project") or {}).get("must_finish"):
        _text(project, "MustFinishByDate",
              _dtm(doc["project"]["must_finish"], "16:59:00"))
    _text(project, "Name", (doc.get("project") or {}).get("name") or "Project")
    _text(project, "ObjectId", str(pid))
    _text(project, "PlannedStartDate", _dtm((doc.get("project") or {}).get("start"), "08:00:00"))
    cals = list((doc.get("calendars") or {}).items())
    cal_id = {key: i + 1 for i, (key, _s) in enumerate(cals)}
    wbs_id = {}
    for i, w in enumerate(doc.get("wbs") or [], 1):
        wbs_id[w.get("code")] = 1000 + i
        node = _el(project, "WBS")
        _text(node, "Code", w.get("code") or "")
        _text(node, "Name", w.get("name") or "")
        _text(node, "ObjectId", str(wbs_id[w.get("code")]))
        parent = wbs_id.get(w.get("parent") or "")
        if parent:
            _text(node, "ParentObjectId", str(parent))
        _text(node, "ProjectObjectId", str(pid))
        _text(node, "SequenceNumber", str(i))
    act_id = {}
    for a in doc.get("activities") or []:
        act_id[a["code"]] = int(a.get("id") or len(act_id) + 1)
        node = _el(project, "Activity")
        _activity(node, a, pid, cal_id, wbs_id, act_id[a["code"]])
    rel_n = 1
    for rel in doc.get("relationships") or []:
        if rel.get("pred") not in act_id or rel.get("succ") not in act_id:
            continue
        node = _el(project, "Relationship")
        _text(node, "Lag", str(float(rel.get("lag_hours") or 0)))
        _text(node, "ObjectId", str(5000 + rel_n))
        _text(node, "PredecessorActivityObjectId", str(act_id[rel["pred"]]))
        _text(node, "PredecessorProjectObjectId", str(pid))
        _text(node, "SuccessorActivityObjectId", str(act_id[rel["succ"]]))
        _text(node, "SuccessorProjectObjectId", str(pid))
        _text(node, "Type", REL_LABEL.get(rel.get("type") or "FS", "Finish to Start"))
        rel_n += 1
    for key, spec in cals:
        node = _el(project, "Calendar")
        _calendar(node, spec, cal_id[key], pid, key == "5day")
    for asn in doc.get("assignments") or []:
        # Child order here is the field list we checked by name, not a full
        # sequence proof. ObjectId links are the ones the schema requires.
        node = _el(project, "ResourceAssignment")
        _text(node, "ActivityObjectId", str(act_id.get(asn.get("activity") or "", "")))
        _text(node, "ObjectId", str(asn.get("id") or ""))
        _text(node, "PlannedUnits", str(asn.get("budgeted_hours") or 0))
        _text(node, "ProjectObjectId", str(pid))
        _text(node, "RemainingUnits", str(asn.get("budgeted_hours") or 0))
        _text(node, "ResourceObjectId", str(asn.get("resource") or ""))
        _text(node, "RoleObjectId", str(asn.get("role") or ""))
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
    return path


def _activity(node, act, pid, cal_id, wbs_id, oid):
    """Fields in the schema's sequence (only the ones we have)."""
    hpd = 8
    hours = float(act.get("orig_hours") or 0)
    def put(name, value):
        if value is None or value == "":
            return
        _text(node, name, value)
    put("ActualFinishDate", _dtm(act.get("actual_finish"), "16:59:00") if act.get("actual_finish") else "")
    put("ActualStartDate", _dtm(act.get("actual_start"), "08:00:00") if act.get("actual_start") else "")
    put("AtCompletionDuration", str(hours))
    put("CalendarObjectId", str(cal_id.get(act.get("calendar") or "5day", 1)))
    put("DurationPercentComplete", str(act.get("percent") or 0))
    put("DurationType", "Fixed Duration and Units")
    put("EarlyFinishDate", _dtm(act.get("ef"), "16:59:00"))
    put("EarlyStartDate", _dtm(act.get("es"), "08:00:00"))
    put("ExpectedFinishDate", _dtm(act.get("expected_finish"), "16:59:00") if act.get("expected_finish") else "")
    put("FinishDate", _dtm(act.get("ef"), "16:59:00"))
    if act.get("float_path"):
        put("FloatPath", str(act.get("float_path")))
        put("FloatPathOrder", str(act.get("float_path_order") or ""))
    if act.get("free_float_hours") is not None:
        put("FreeFloat", str(act.get("free_float_hours")))
    put("Id", act.get("code") or "")
    put("IsCritical", "true" if act.get("critical") else "false")
    put("IsLongestPath", "true" if act.get("longest_path") else "false")
    put("LateFinishDate", _dtm(act.get("lf"), "16:59:00"))
    put("LateStartDate", _dtm(act.get("ls"), "08:00:00"))
    put("Name", (act.get("name") or "")[:120])
    put("ObjectId", str(oid))
    put("PercentCompleteType", "Duration")
    put("PlannedDuration", str(hours))
    put("PlannedFinishDate", _dtm(act.get("bl_finish") or act.get("ef"), "16:59:00"))
    put("PlannedStartDate", _dtm(act.get("bl_start") or act.get("es"), "08:00:00"))
    if act.get("constraint_date"):
        put("PrimaryConstraintDate", _dtm(act.get("constraint_date"), "08:00:00"))
    label = CONSTRAINT_LABEL.get(act.get("constraint") or "", "")
    if label:
        put("PrimaryConstraintType", label)
    put("ProjectObjectId", str(pid))
    put("RemainingDuration", str(act.get("remain_hours") if act.get("remain_hours") is not None else hours))
    put("RemainingEarlyFinishDate", _dtm(act.get("ef"), "16:59:00"))
    put("RemainingEarlyStartDate", _dtm(act.get("es"), "08:00:00"))
    if act.get("resume"):
        put("ResumeDate", _dtm(act.get("resume"), "08:00:00"))
    if act.get("constraint2"):
        put("SecondaryConstraintDate", _dtm(act.get("constraint2_date"), "08:00:00"))
        put("SecondaryConstraintType", CONSTRAINT_LABEL.get(act.get("constraint2"), ""))
    put("StartDate", _dtm(act.get("es"), "08:00:00"))
    put("Status", {"not_started": "Not Started", "active": "In Progress",
                   "complete": "Completed"}.get(act.get("status") or "", "Not Started"))
    if act.get("suspend"):
        put("SuspendDate", _dtm(act.get("suspend"), "16:59:00"))
    if act.get("total_float_hours") is not None:
        put("TotalFloat", str(act.get("total_float_hours")))
    put("Type", TYPE_LABEL.get(act.get("type") or "task", "Task Dependent"))
    wid = wbs_id.get(act.get("wbs") or "")
    if wid:
        put("WBSObjectId", str(wid))


def _calendar(node, spec, oid, pid, default):
    _text(node, "HoursPerDay", str(spec.get("hours_per_day") or 8))
    _text(node, "HoursPerWeek", str((spec.get("hours_per_day") or 8) * len(spec.get("weekdays") or [])))
    _text(node, "IsDefault", "true" if default else "false")
    _text(node, "Name", spec.get("name") or spec.get("key") or "Calendar")
    _text(node, "ObjectId", str(oid))
    _text(node, "ProjectObjectId", str(pid))
    _text(node, "Type", "Project")
    week = _el(node, "StandardWorkWeek")
    working = set(spec.get("weekdays") or [])
    for i, name in enumerate(_DOW):
        day = _el(week, "StandardWorkHours")
        _text(day, "DayOfWeek", name)
        if i in working:
            _work(day, "08:00:00", "11:59:00")
            if (spec.get("hours_per_day") or 8) > 8:
                _work(day, "13:00:00", "23:59:00")
            elif (spec.get("hours_per_day") or 8) >= 8:
                _work(day, "13:00:00", "16:59:00")
    hols = spec.get("holidays") or []
    if hols:
        wrap = _el(node, "HolidayOrExceptions")
        for h in hols:
            ex = _el(wrap, "HolidayOrException")
            # A non-work day. The published schema fragment does not show
            # minOccurs="0" on WorkTime; real files omit WorkTime for a
            # day off, and that is what we write.
            _text(ex, "Date", _dtm(h, "00:00:00"))


def _work(parent, start, finish):
    wt = _el(parent, "WorkTime")
    _text(wt, "Start", start)
    _text(wt, "Finish", finish)


def export_mspdi(doc, path):
    """Write an MSPDI schedule (.xml). Losses are listed on the document."""
    losses = []
    ET.register_namespace("", MSP_NS)
    root = ET.Element(f"{{{MSP_NS}}}Project")

    def sub(el, name, text=None):
        node = ET.SubElement(el, f"{{{MSP_NS}}}{name}")
        if text is not None:
            node.text = str(text)
        return node

    sub(root, "Name", (doc.get("project") or {}).get("name") or "Project")
    sub(root, "ScheduleFromStart", 1)
    if (doc.get("project") or {}).get("start"):
        sub(root, "StartDate", _dtm(doc["project"]["start"], "08:00:00"))
    sub(root, "CalendarUID", 1)
    sub(root, "MinutesPerDay", 480)
    sub(root, "MinutesPerWeek", 2400)
    sub(root, "DaysPerMonth", 20)
    cals = list((doc.get("calendars") or {}).items())
    cal_uid = {key: i + 1 for i, (key, _s) in enumerate(cals)} or {"5day": 1}
    wrap = sub(root, "Calendars")
    for key, spec in cals:
        cal = sub(wrap, "Calendar")
        sub(cal, "UID", cal_uid[key])
        sub(cal, "Name", spec.get("name") or key)
        sub(cal, "IsBaseCalendar", 1)
        sub(cal, "BaseCalendarUID", -1)
        days = sub(cal, "WeekDays")
        working = set(spec.get("weekdays") or [])
        for i in range(7):
            wd = sub(days, "WeekDay")
            sub(wd, "DayType", i + 1)          # 1 = Sunday
            on = i in working
            sub(wd, "DayWorking", 1 if on else 0)
            if on:
                times = sub(wd, "WorkingTimes")
                for a, b in (("08:00:00", "12:00:00"), ("13:00:00", "17:00:00")):
                    t = sub(times, "WorkingTime")
                    sub(t, "FromTime", a)
                    sub(t, "ToTime", b)
        if spec.get("holidays"):
            exs = sub(cal, "Exceptions")
            for h in spec["holidays"]:
                ex = sub(exs, "Exception")
                sub(ex, "EnteredByOccurrences", 0)
                tp = sub(ex, "TimePeriod")
                sub(tp, "FromDate", _dtm(h, "00:00:00"))
                sub(tp, "ToDate", _dtm(h, "23:59:00"))
                sub(ex, "Occurrences", 1)
                sub(ex, "Name", f"Holiday {h}")
                sub(ex, "Type", 1)
                sub(ex, "DayWorking", 0)
    # WBS as summary tasks, then the activities under them.
    tasks = sub(root, "Tasks")
    uid = {}
    n = 1
    wbs_uid = {}
    counters = []
    outline_of = {}
    for w in doc.get("wbs") or []:
        level = w.get("code", "1").count(".")
        del counters[level + 1:]
        while len(counters) <= level:
            counters.append(0)
        counters[level] += 1
        wbs_uid[w.get("code")] = n
        outline_of[w.get("code")] = ".".join(str(c) for c in counters)
        t = sub(tasks, "Task")
        sub(t, "UID", n)
        sub(t, "ID", n)
        sub(t, "Name", w.get("name") or w.get("code"))
        sub(t, "Type", 1)
        sub(t, "OutlineNumber", outline_of[w.get("code")])
        sub(t, "OutlineLevel", level + 1)
        sub(t, "Summary", 1)
        sub(t, "Milestone", 0)
        n += 1
    act_uid = {}
    child_count = {}
    for a in doc.get("activities") or []:
        if a.get("type") == "wbs_summary":
            continue
        if a.get("type") == "resource":
            losses.append(f"{a.get('code')}: resource-dependent work saved as a normal task")
        if a.get("type") == "loe":
            losses.append(f"{a.get('code')}: level of effort saved as a normal task")
        if a.get("constraint2"):
            losses.append(f"{a.get('code')}: secondary constraint was not written")
        if a.get("constraint") in ("mandatory_start", "mandatory_finish"):
            losses.append(f"{a.get('code')}: mandatory constraint saved as a must-on constraint")
        parent = a.get("wbs") or ""
        base = outline_of.get(parent, "1")
        level = base.count(".") + 1
        child_count[parent] = child_count.get(parent, 0) + 1
        outline = f"{base}.{child_count[parent]}" if parent else str(child_count[parent])
        act_uid[a["code"]] = n
        t = sub(tasks, "Task")
        sub(t, "UID", n)
        sub(t, "ID", n)
        sub(t, "Name", a.get("name") or "")
        sub(t, "Type", 0)
        sub(t, "OutlineNumber", outline)
        sub(t, "OutlineLevel", level + 1 if parent else 1)
        if a.get("es"):
            sub(t, "Start", _dtm(a.get("es"), "08:00:00"))
        if a.get("ef"):
            sub(t, "Finish", _dtm(a.get("ef"), "17:00:00"))
        hours = float(a.get("orig_hours") or 0)
        sub(t, "Duration", f"PT{hours:.0f}H0M0S")
        sub(t, "DurationFormat", 7)
        milestone = a.get("type") in ("start_ms", "finish_ms")
        sub(t, "Milestone", 1 if milestone else 0)
        sub(t, "Summary", 0)
        sub(t, "CalendarUID", cal_uid.get(a.get("calendar") or "5day", 1))
        sub(t, "PercentComplete", int(float(a.get("percent") or 0)))
        if a.get("actual_start"):
            sub(t, "ActualStart", _dtm(a.get("actual_start"), "08:00:00"))
        if a.get("actual_finish"):
            sub(t, "ActualFinish", _dtm(a.get("actual_finish"), "17:00:00"))
        kind = a.get("constraint") or ""
        if kind:
            sub(t, "ConstraintType", _MSP_CONSTRAINT.get(kind, 0))
            if a.get("constraint_date"):
                sub(t, "ConstraintDate", _dtm(a.get("constraint_date"), "08:00:00"))
        note = a.get("why") or a.get("basis") or ""
        if note:
            sub(t, "Notes", note)
        seen = set()
        for rel in doc.get("relationships") or []:
            if rel.get("succ") != a["code"] or rel.get("pred") not in act_uid:
                continue
            if rel["pred"] in seen:
                continue
            seen.add(rel["pred"])
            pl = sub(t, "PredecessorLink")
            sub(pl, "PredecessorUID", act_uid[rel["pred"]])
            sub(pl, "Type", _MSP_REL.get(rel.get("type") or "FS", "1"))
            # tenths of a minute; 8 hours = 4800, matching the existing writer
            sub(pl, "LinkLag", int(round(float(rel.get("lag_hours") or 0) * 600)))
            sub(pl, "LagFormat", 7)
        if a.get("bl_start") and a.get("bl_finish"):
            b = sub(t, "Baseline")
            sub(b, "Number", 0)
            sub(b, "Start", _dtm(a.get("bl_start"), "08:00:00"))
            sub(b, "Finish", _dtm(a.get("bl_finish"), "17:00:00"))
        n += 1
    doc["export_losses"] = losses
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
    return path


def _el(parent, name):
    return ET.SubElement(parent, f"{{{PM_NS}}}{name}")


def _text(parent, name, value):
    node = ET.SubElement(parent, f"{{{PM_NS}}}{name}")
    node.text = "" if value is None else str(value)
    return node


def _dtm(value, clock):
    d = as_date(value)
    if not d:
        return ""
    return f"{d.isoformat()}T{clock}"
