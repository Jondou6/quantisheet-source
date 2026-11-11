"""Quality: punch lists and three-phase inspections, saved inside the
job PDF.

* Punch items (P-001...) can be pinned to the drawing: a note marker that
  turns orange when the trade says it's done and green when it's checked
  and closed. Status: open -> ready for review -> closed (or back to open,
  or void).
* Three-phase inspections (preparatory, initial, follow-up) per
  definable feature of work, with a checklist. Closing an inspection turns
  each failed check into a punch item (a deficiency), and the next phase
  can be started from it.

(Built on the Venice AI draft.)
"""
import datetime as _dt
import json
import logging

from . import annotate, forms, settings
from . import embfiles

log = logging.getLogger(__name__)

FILE = "quantisheet_qa.json"
STATUSES = ("open", "ready", "closed", "void")
STATUS_LABEL = {"open": "Open", "ready": "Ready for review",
                "closed": "Closed", "void": "Void"}
PIN_COLOR = {"open": (0.85, 0.1, 0.1), "ready": (1.0, 0.55, 0.0),
             "closed": (0.1, 0.6, 0.2), "void": (0.55, 0.55, 0.55)}
PRIORITIES = ("low", "normal", "high", "safety")
PHASES = ("preparatory", "initial", "follow-up")
PHASE_LABEL = {"preparatory": "Preparatory", "initial": "Initial",
               "follow-up": "Follow-up"}
RESULTS = ("pass", "fail", "n/a")

TEMPLATES = {
    "preparatory": [
        "Plans, specifications and approved submittals reviewed",
        "Materials on site match the approved submittals",
        "Preliminary work complete and acceptable",
        "Required tests and inspections identified",
        "Mock-up or sample panel approved",
        "Work methods, tolerances and finishes agreed with the crew",
        "Activity hazard analysis reviewed with the crew",
    ],
    "initial": [
        "First work matches the plans, specs and submittals",
        "Layout and dimensions within tolerance",
        "Workmanship meets the agreed standard",
        "Fastening, supports and anchorage per details",
        "Penetrations, joints and sealants per details",
        "Required tests performed and recorded",
        "Safety requirements followed",
    ],
    "follow-up": [
        "Work continues to match the initial phase standard",
        "Deficiencies from earlier phases corrected",
        "Work protected from damage by following trades",
        "Testing complete and passed",
        "As-built changes recorded",
        "Area clean and ready for the next trade",
    ],
}


class QAError(ValueError):
    pass


def _today():
    return _dt.date.today().isoformat()


def _now():
    return _dt.datetime.now().isoformat(timespec="minutes")


def _who():
    try:
        return settings.author() or ""
    except Exception:
        return ""


def blank():
    return {"punch": [], "inspections": [], "counter": {"P": 0, "QI": 0}}


def read(doc):
    data = blank()
    try:
        if FILE in doc.embfile_names():
            saved = json.loads(doc.embfile_get(FILE).decode("utf-8"))
            if isinstance(saved, dict):
                for k, v in saved.items():
                    if k == "counter":
                        data["counter"].update(v or {})
                    else:
                        data[k] = v
    except Exception:
        log.warning("could not read QA data", exc_info=True)
    return data


def write(doc, data):
    raw = json.dumps(data).encode("utf-8")
    embfiles.put(doc, FILE, raw, "QuantiSheet quality")


def _next(data, prefix):
    data["counter"][prefix] = int(data["counter"].get(prefix, 0)) + 1
    return f"{prefix}-{data['counter'][prefix]:03d}"


def templates():
    """Built-in checklists, overridden by your own (settings
    "qa_templates")."""
    out = {k: list(v) for k, v in TEMPLATES.items()}
    for k, v in (settings.get("qa_templates") or {}).items():
        if k in out and isinstance(v, list) and v:
            out[k] = [str(x) for x in v]
    return out


# ---- punch list ------------------------------------------------------------------

def _hist(item, action, note="", by=None):
    item.setdefault("history", []).append(
        {"when": _now(), "who": by or _who(), "action": action,
         "note": note})


def add_punch(doc, description, location="", trade="", assignee="", due="",
              priority="normal", page=None, ref=None, source="", by=None):
    if not str(description).strip():
        raise QAError("Describe the punch item.")
    if priority not in PRIORITIES:
        priority = "normal"
    data = read(doc)
    pid = _next(data, "P")
    item = {"id": pid, "description": str(description).strip(),
            "location": location, "trade": trade, "assignee": assignee,
            "due": due or "", "priority": priority, "status": "open",
            "page": page, "ref": dict(ref) if ref else None,
            "source": source, "raised": _today(), "by": by or _who(),
            "closed": "", "history": []}
    _hist(item, "created", by=by)
    data["punch"].append(item)
    write(doc, data)
    return pid


def _punch(data, pid):
    for p in data["punch"]:
        if p["id"] == pid:
            return p
    raise KeyError(pid)


def get_punch(doc, pid):
    return _punch(read(doc), pid)


def pin(doc, pid, page, pt):
    """Drop a note marker for the item on page `page` at `pt` (unrotated
    page coordinates). Returns the marker's ref."""
    data = read(doc)
    p = _punch(data, pid)
    op = annotate.new_op("add_note", page, pt=[float(pt[0]), float(pt[1])],
                         text=f"{p['id']}: {p['description']}",
                         subject=f"Punch {p['id']}",
                         color=list(PIN_COLOR[p["status"]]),
                         author=p.get("by") or _who())
    if not annotate.apply_op(doc, op):
        raise QAError("Couldn't place the marker.")
    p["page"] = page
    p["ref"] = {"target": op["id"]}
    write(doc, data)
    return p["ref"]


def _recolor(doc, p):
    if not p.get("ref") or p.get("page") is None:
        return
    try:
        annotate.apply_op(doc, annotate.new_op(
            "set_annot", p["page"], **p["ref"],
            color=list(PIN_COLOR[p["status"]]),
            note=f"{p['id']}: {p['description']} "
                 f"[{STATUS_LABEL[p['status']]}]"))
    except Exception:
        log.warning("could not recolor punch marker", exc_info=True)


_MOVES = {"open": ("ready", "closed", "void"), "ready": ("open", "closed",
                                                         "void"),
          "closed": ("open",), "void": ("open",)}


def set_status(doc, pid, status, note="", by=None):
    """open -> ready (trade says done) -> closed (checked), or back to
    open (rejected / reopened), or void."""
    if status not in STATUSES:
        raise QAError(f"Status must be one of {', '.join(STATUSES)}.")
    data = read(doc)
    p = _punch(data, pid)
    if status == p["status"]:
        return p
    if status not in _MOVES[p["status"]]:
        raise QAError(f"{pid} is {STATUS_LABEL[p['status']].lower()}; it "
                      f"can't go to {STATUS_LABEL[status].lower()}.")
    old = p["status"]
    p["status"] = status
    p["closed"] = _today() if status == "closed" else ""
    _hist(p, f"{STATUS_LABEL[old]} -> {STATUS_LABEL[status]}", note, by)
    _recolor(doc, p)
    write(doc, data)
    return p


def update_punch(doc, pid, **fields):
    data = read(doc)
    p = _punch(data, pid)
    for k in ("description", "location", "trade", "assignee", "due",
              "priority"):
        if k in fields and fields[k] is not None:
            p[k] = str(fields[k])
    _hist(p, "edited")
    _recolor(doc, p)
    write(doc, data)
    return p


def punch(doc, status=None, trade=None, assignee=None, page=None,
          open_only=False):
    out = []
    for p in read(doc)["punch"]:
        if status and p["status"] != status:
            continue
        if open_only and p["status"] not in ("open", "ready"):
            continue
        if trade and p.get("trade") != trade:
            continue
        if assignee and p.get("assignee") != assignee:
            continue
        if page is not None and p.get("page") != page:
            continue
        out.append(p)
    return out


def is_overdue(p, today=None):
    return p["status"] in ("open", "ready") and bool(p.get("due")) and \
        p["due"] < (today or _today())


def summary(doc, today=None):
    items = read(doc)["punch"]
    by_status = {s: 0 for s in STATUSES}
    by_trade = {}
    for p in items:
        by_status[p["status"]] += 1
        if p["status"] in ("open", "ready"):
            t = p.get("trade") or "(no trade)"
            by_trade[t] = by_trade.get(t, 0) + 1
    return {"total": len(items), "by_status": by_status,
            "open_by_trade": by_trade,
            "overdue": sum(1 for p in items if is_overdue(p, today))}


def _sheet_names(doc):
    """{page: sheet number} from the drawing register, else ''."""
    try:
        from . import doccontrol
        return {r["page"]: r["number"] for r in doccontrol.register(doc)
                if r["page"] is not None}
    except Exception:
        return {}


def punch_pdf(doc, path, items=None, project="", title="Punch List"):
    items = items if items is not None else punch(doc)
    names = _sheet_names(doc)
    s = summary(doc)
    f = forms.Form(title, project, landscape=True)
    f.fields([("Items", len(items)), ("Open", s["by_status"]["open"]),
              ("Ready for review", s["by_status"]["ready"]),
              ("Overdue", s["overdue"])], cols=4)
    f.table(["No.", "Description", "Location", "Sheet", "Trade",
             "Assigned to", "Priority", "Due", "Status"],
            [[p["id"], p["description"], p.get("location", ""),
              names.get(p.get("page"), "" if p.get("page") is None else
                        f"p.{p['page'] + 1}"),
              p.get("trade", ""), p.get("assignee", ""), p["priority"],
              p.get("due", ""), STATUS_LABEL[p["status"]]] for p in items],
            [0.7, 4, 1.6, 0.8, 1.2, 1.3, 0.8, 0.9, 1.2],
            fills=[(1, 0.9, 0.9) if is_overdue(p) else None for p in items])
    f.signatures(["Prepared by", "Trade acknowledged", "Date"])
    return f.save(path)


def punch_xlsx(doc, path):
    from . import acrobat
    names = _sheet_names(doc)
    rows = [["No.", "Description", "Location", "Sheet", "Page", "Trade",
             "Assigned to", "Priority", "Due", "Status", "Raised", "Closed",
             "From inspection"]]
    for p in punch(doc):
        rows.append([p["id"], p["description"], p.get("location", ""),
                     names.get(p.get("page"), ""),
                     "" if p.get("page") is None else p["page"] + 1,
                     p.get("trade", ""), p.get("assignee", ""),
                     p["priority"], p.get("due", ""),
                     STATUS_LABEL[p["status"]], p.get("raised", ""),
                     p.get("closed", ""), p.get("source", "")])
    acrobat.write_xlsx(path, [("Punch List", rows)])
    return path


# ---- three-phase inspections ---------------------------------------------------------

def new_inspection(doc, phase, feature, area="", trade="", date=None,
                   inspector="", checks=None, spec="", attendees=""):
    """An inspection of one definable feature of work (e.g. "Metal stud
    framing, Level 2"). `checks` defaults to the phase's checklist."""
    if phase not in PHASES:
        raise QAError(f"Phase must be one of {', '.join(PHASES)}.")
    if not str(feature).strip():
        raise QAError("Name the feature of work being inspected.")
    checks = [c for c in (checks if checks is not None else
                          templates()[phase]) if str(c).strip()]
    if not checks:
        raise QAError("The checklist is empty.")
    data = read(doc)
    iid = _next(data, "QI")
    data["inspections"].append({
        "id": iid, "phase": phase, "feature": str(feature).strip(),
        "area": area, "trade": trade, "spec": spec,
        "date": date or _today(), "inspector": inspector or _who(),
        "attendees": attendees, "status": "open", "closed": "",
        "items": [{"check": str(c), "result": "", "note": ""}
                  for c in checks], "punch": [], "notes": ""})
    write(doc, data)
    return iid


def _insp(data, iid):
    for i in data["inspections"]:
        if i["id"] == iid:
            return i
    raise KeyError(iid)


def get_inspection(doc, iid):
    return _insp(read(doc), iid)


def inspections(doc, phase=None, feature=None):
    return [i for i in read(doc)["inspections"]
            if (not phase or i["phase"] == phase) and
            (not feature or i["feature"] == feature)]


def answer(doc, iid, index, result, note=None):
    if result not in RESULTS and result != "":
        raise QAError(f"Result must be one of {', '.join(RESULTS)}.")
    data = read(doc)
    i = _insp(data, iid)
    if i["status"] != "open":
        raise QAError(f"{iid} is closed.")
    item = i["items"][int(index)]
    item["result"] = result
    if note is not None:
        item["note"] = str(note)
    write(doc, data)
    return item


def close_inspection(doc, iid, notes="", page=None, due=""):
    """Every check must be answered. Failed checks become punch items
    (deficiencies) for the trade. Returns the inspection."""
    data = read(doc)
    i = _insp(data, iid)
    if i["status"] != "open":
        raise QAError(f"{iid} is already closed.")
    left = [n + 1 for n, x in enumerate(i["items"]) if not x["result"]]
    if left:
        raise QAError(f"Answer every check first (still open: "
                      f"{', '.join(map(str, left))}).")
    fails = [x for x in i["items"] if x["result"] == "fail"]
    i["status"] = "failed" if fails else "passed"
    i["closed"] = _today()
    if notes:
        i["notes"] = notes
    write(doc, data)
    made = []
    for x in fails:
        desc = f"{i['feature']}: {x['check']}" + (f" - {x['note']}"
                                                  if x.get("note") else "")
        made.append(add_punch(
            doc, desc, location=i.get("area", ""), trade=i.get("trade", ""),
            due=due, priority="high", page=page, source=iid))
    if made:
        data = read(doc)
        _insp(data, iid)["punch"] = made
        write(doc, data)
    return get_inspection(doc, iid)


def next_phase(doc, iid, date=None):
    """Start the following phase for the same feature of work."""
    i = get_inspection(doc, iid)
    k = PHASES.index(i["phase"])
    phase = PHASES[min(k + 1, len(PHASES) - 1)]
    return new_inspection(doc, phase, i["feature"], i.get("area", ""),
                          i.get("trade", ""), date=date,
                          inspector=i.get("inspector", ""),
                          spec=i.get("spec", ""))


def inspection_pdf(doc, iid, path, project=""):
    i = get_inspection(doc, iid)
    f = forms.Form(f"{PHASE_LABEL[i['phase']]} Phase Inspection {i['id']}",
                   project)
    f.fields([("Feature of work", i["feature"]), ("Date", i["date"]),
              ("Area", i.get("area", "")), ("Trade", i.get("trade", "")),
              ("Spec section", i.get("spec", "")),
              ("Inspector", i.get("inspector", "")),
              ("Attendees", i.get("attendees", "")),
              ("Result", {"open": "Open", "passed": "Passed",
                          "failed": "Failed"}[i["status"]])])
    f.table(["#", "Check", "Result", "Note"],
            [[n + 1, x["check"], x["result"].upper() if x["result"] else "",
              x.get("note", "")] for n, x in enumerate(i["items"])],
            [0.4, 5, 0.8, 3.4], ["l", "l", "c", "l"],
            fills=[(1, 0.9, 0.9) if x["result"] == "fail" else None
                   for x in i["items"]])
    if i.get("punch"):
        f.para("Deficiencies added to the punch list: " +
               ", ".join(i["punch"]))
    if i.get("notes"):
        f.heading("Notes")
        f.para(i["notes"])
    f.signatures(["QC manager", "Superintendent", "Trade foreman"])
    return f.save(path)
