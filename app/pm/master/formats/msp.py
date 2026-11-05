"""MS Project XML (MSPDI, File > Save As > XML) -> neutral rows.

A NEW read-only path (design 3.3-3.4): it never calls the Scheduler's
import_msproject / _merge, never writes holidays or anything else, and
only reads the file. DOCTYPE / ENTITY files are refused before parsing.
The master ID is read from a task text field, Text30 by default
(setting "msp_field"); found by the project's ExtendedAttribute
definition (FieldName or Alias), else Text30's standard FieldID."""
import os
import re
import xml.etree.ElementTree as ET

from ... import schedule
from .. import model
from . import common

FIELD_IDS = {"Text30": "188744016"}      # INFERRED (MSPDI field id)


def _hours(iso):
    m = re.fullmatch(r"-?P(?:(\d+(?:\.\d+)?)D)?(?:T(?:(\d+(?:\.\d+)?)H)?"
                     r"(?:(\d+(?:\.\d+)?)M)?(?:(\d+(?:\.\d+)?)S)?)?",
                     (iso or "").strip())
    if not m or not iso:
        return None
    d, h, mi, s = (float(x or 0) for x in m.groups())
    return d * 24 + h + mi / 60 + s / 3600


def read(store, path, company, now=None):
    out = common.new_out("msp")
    name = os.path.basename(path)
    data = common.load(path, out)
    if data is None:
        return out
    try:
        root = ET.fromstring(data)
    except ET.ParseError as ex:
        out["errors"].append(common.err(name, f"This isn't readable XML "
                                        f"({ex})."))
        return out
    ns = root.tag.split("}")[0] + "}" if root.tag.startswith("{") else ""

    def t(el, tag):
        x = el.find(ns + tag)
        return x.text.strip() if x is not None and x.text else ""
    tasks = root.find(ns + "Tasks")
    if not root.tag.endswith("Project") or tasks is None:
        out["errors"].append(common.err(name, "This isn't a Microsoft "
                                        "Project XML file (no Tasks)."))
        return out
    dd = common.data_date(store, t(root, "StatusDate"), out, now)
    try:
        per_day = float(t(root, "MinutesPerDay") or 480) / 60
    except ValueError:
        per_day = 8.0
    per_day = per_day or 8.0
    want = model.config(store).get("msp_field") or "Text30"
    fid = FIELD_IDS.get(want, "")
    eas = root.find(ns + "ExtendedAttributes")
    for ea in eas.findall(ns + "ExtendedAttribute") if eas is not None \
            else ():
        if want in (t(ea, "FieldName"), t(ea, "Alias")):
            fid = t(ea, "FieldID") or fid
    items = []
    all_tasks = tasks.findall(ns + "Task")
    if len(all_tasks) > common.MAX_ROWS:
        out["errors"].append(common.err(name, f"More than {common.MAX_ROWS} "
                                        "tasks."))
        return out
    for k, task in enumerate(all_tasks, 1):
        uid = t(task, "UID")
        if not uid or uid == "0" or t(task, "Summary") == "1":
            continue
        nm = t(task, "Name")
        where = f"Task UID {uid} '{nm}'"
        mid = ""
        for ea in task.findall(ns + "ExtendedAttribute"):
            if fid and t(ea, "FieldID") == fid:
                mid = t(ea, "Value")
        hrs = _hours(t(task, "Duration"))
        vals = {"duration": common.duration(hrs, per_day)}
        if t(task, "Duration") and hrs is None:
            out["errors"].append(common.err(where, f"Duration "
                                            f"'{t(task, 'Duration')}' isn't "
                                            "readable."))
        try:
            pc = t(task, "PercentComplete")
            vals["percent"] = float(pc) if pc else None
            if vals["percent"] is not None and vals["percent"] == \
                    int(vals["percent"]):
                vals["percent"] = int(vals["percent"])
        except ValueError:
            vals["percent"] = None
            out["errors"].append(common.err(where, "% complete isn't a "
                                            "number."))
        for f, tag in (("actual_start", "ActualStart"),
                       ("actual_finish", "ActualFinish")):
            v = t(task, tag)[:10]
            if v and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
                out["errors"].append(common.err(where, f"{tag} '{v}' isn't "
                                                "a date."))
                v = ""
            vals[f] = v or None
        if vals["actual_finish"] and vals["percent"] is not None and \
                vals["percent"] < 100 and vals["actual_start"]:
            vals["percent"] = 100
        links = [f"msp:{t(pl, 'PredecessorUID')}"
                 for pl in task.findall(ns + "PredecessorLink")
                 if t(pl, "PredecessorUID")]
        items.append({"ref": f"msp:{uid}", "ids": [(want, mid)] if mid
                      else [], "ext": f"msp:{uid}", "name": nm,
                      "where": where, "values": vals, "links": links,
                      "row": k})
    file_hol = set(schedule.msproject_holidays(root, ns))
    if file_hol:
        lo = (dd.replace(day=1)).isoformat()
        hi = dd.replace(year=dd.year + 1).isoformat()
        cal = schedule.Calendar(dd, store.setting("holidays") or ())
        master = {d.isoformat() for d in cal.hol}
        extra = sorted(d for d in file_hol - master if lo <= d <= hi)
        missing = sorted(d for d in master - file_hol if lo <= d <= hi)
        if extra or missing:
            out["warnings"].append(common.err(
                "calendar", "The sub's calendar differs from the master's "
                "(the master calendar is used; nothing is changed)." +
                (" Sub's days off not in the master: " + ", ".join(extra)
                 + "." if extra else "") +
                (" Master days off the sub works: " + ", ".join(missing) +
                 "." if missing else "")))
    # (no project id here: reading must not create one - it writes)
    out["meta"] = {"company": company, "cycle": dd.isoformat(),
                   "rev": "unknown"}
    return common.build(store, company, items, out, want)
