"""Equipment & Service Records: what you installed at each property or
job (equipment, make, model, serial number, install date, warranty) and
the recurring service it needs (every N days / weeks / months / years),
with the next due dates worked out and reminders for service coming due
and warranties running out.

One JSON file you keep; the default is service_records.json in
QuantiSheet's data folder (settings.DIR), or any file you pick. Dates are
ISO (YYYY-MM-DD). Nothing is sent anywhere: reminders are a list you open.
"""
import calendar
import datetime as dt
import os
import uuid

from . import _io

UNITS = ("days", "weeks", "months", "years")
FILE_NAME = "service_records.json"
KIND = "service_records"


class ServiceError(ValueError):
    pass


def default_path():
    from .. import settings
    return os.path.join(settings.DIR, FILE_NAME)


def blank():
    return {"kind": KIND, "version": 1, "properties": [], "equipment": [],
            "services": []}


def _id():
    return uuid.uuid4().hex[:10]


def _date(v, what, blank_ok=True):
    if v in (None, ""):
        if blank_ok:
            return ""
        raise ServiceError(f"{what}: type a date (YYYY-MM-DD).")
    if isinstance(v, dt.date):
        return v.isoformat()
    try:
        return dt.date.fromisoformat(str(v).strip()).isoformat()
    except ValueError:
        raise ServiceError(f"{what}: {v!r} isn't a date (YYYY-MM-DD).")


def _d(v):
    return dt.date.fromisoformat(v) if v else None


def _txt(v, n=200):
    return " ".join(str(v or "").split())[:n]


def find(store, rid):
    for k in ("properties", "equipment", "services"):
        for r in store[k]:
            if r["id"] == rid:
                return r
    return None


def add_property(store, name, address="", customer="", notes=""):
    if not _txt(name):
        raise ServiceError("Name the property or job.")
    r = {"id": _id(), "name": _txt(name), "address": _txt(address, 300),
         "customer": _txt(customer), "notes": _txt(notes, 1000)}
    store["properties"].append(r)
    return r["id"]


def _prop(store, pid):
    if not any(p["id"] == pid for p in store["properties"]):
        raise ServiceError("That property isn't in the records.")


def add_equipment(store, prop, kind, make="", model="", serial="",
                  installed="", warranty_months=None, warranty_end="",
                  notes=""):
    _prop(store, prop)
    if warranty_months not in (None, ""):
        try:
            warranty_months = int(warranty_months)
        except (TypeError, ValueError):
            raise ServiceError("Warranty months must be a whole number.")
        if warranty_months < 0 or warranty_months > 1200:
            raise ServiceError("Warranty months is out of range.")
    else:
        warranty_months = None
    r = {"id": _id(), "property": prop, "kind": _txt(kind),
         "make": _txt(make), "model": _txt(model), "serial": _txt(serial),
         "installed": _date(installed, "Install date"),
         "warranty_months": warranty_months,
         "warranty_end": _date(warranty_end, "Warranty end"),
         "notes": _txt(notes, 1000)}
    store["equipment"].append(r)
    return r["id"]


def add_service(store, prop, title, every, unit, start, equipment="",
                last_done="", remind_days=14, notes=""):
    _prop(store, prop)
    try:
        every = int(every)
    except (TypeError, ValueError):
        raise ServiceError("'Every' must be a whole number.")
    if every < 1 or every > 3650:
        raise ServiceError("'Every' must be 1 or more.")
    if unit not in UNITS:
        raise ServiceError("Repeat in " + ", ".join(UNITS) + ".")
    r = {"id": _id(), "property": prop, "equipment": equipment or "",
         "title": _txt(title) or "Service", "every": every, "unit": unit,
         "start": _date(start, "Start date", blank_ok=False),
         "last_done": _date(last_done, "Last done"),
         "remind_days": int(remind_days or 0), "notes": _txt(notes, 1000),
         "history": []}
    store["services"].append(r)
    return r["id"]


def mark_done(store, sid, when):
    s = find(store, sid)
    if s is None or "every" not in s:
        raise ServiceError("That service isn't in the records.")
    s["last_done"] = _date(when, "Date done", blank_ok=False)
    s.setdefault("history", []).append(s["last_done"])
    return s


def add_interval(d, n, unit):
    if unit == "days":
        return d + dt.timedelta(days=n)
    if unit == "weeks":
        return d + dt.timedelta(weeks=n)
    months = n * (12 if unit == "years" else 1)
    y, m = divmod(d.month - 1 + months, 12)
    y += d.year
    m += 1
    return dt.date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def warranty_end(eq):
    if eq.get("warranty_end"):
        return _d(eq["warranty_end"])
    if eq.get("installed") and eq.get("warranty_months") is not None:
        return add_interval(_d(eq["installed"]), int(eq["warranty_months"]),
                            "months")
    return None


def warranty_status(eq, today, warn_days=60):
    end = warranty_end(eq)
    if end is None:
        return "unknown"
    if today > end:
        return "expired"
    return "expiring" if (end - today).days <= warn_days else "active"


def next_due(s):
    """Last done + the interval, else the start date."""
    if s.get("last_done"):
        return add_interval(_d(s["last_done"]), s["every"], s["unit"])
    return _d(s["start"])


def due_list(store, today, within_days=30):
    """Services due within `within_days` (or overdue), soonest first."""
    props = {p["id"]: p for p in store["properties"]}
    out = []
    for s in store["services"]:
        nd = next_due(s)
        left = (nd - today).days
        if left <= within_days:
            out.append({"id": s["id"], "title": s["title"],
                        "property": props.get(s["property"], {}).get(
                            "name", ""), "next_due": nd, "days_left": left,
                        "overdue": left < 0})
    return sorted(out, key=lambda x: x["next_due"])


def reminders(store, today, within_days=30):
    """Service due and warranties ending within `within_days`."""
    out = [dict(x, kind="service", date=x["next_due"])
           for x in due_list(store, today, within_days)]
    props = {p["id"]: p for p in store["properties"]}
    for e in store["equipment"]:
        end = warranty_end(e)
        if end is not None and 0 <= (end - today).days <= within_days:
            out.append({"kind": "warranty", "id": e["id"],
                        "title": f"Warranty ends: {e['kind']} "
                                 f"{e['model']}".strip(),
                        "property": props.get(e["property"], {}).get(
                            "name", ""), "date": end,
                        "days_left": (end - today).days, "overdue": False})
    return sorted(out, key=lambda x: x["date"])


def validate(store):
    if not isinstance(store, dict) or store.get("kind") != KIND:
        raise ServiceError("Not a QuantiSheet service records file.")
    for k in ("properties", "equipment", "services"):
        if not isinstance(store.get(k), list):
            raise ServiceError(f"The file has no {k} list.")
    return store


def save(store, path=None):
    """To `path`, or the data folder's service records file (only inside
    the data folder: _io.data_file, v2 step 5)."""
    return _io.write_json(path or _io.data_file(FILE_NAME), validate(store))


def load(path=None):
    p = path or default_path()
    if not os.path.isfile(p):
        return blank()
    try:
        return validate(_io.read_json(p))
    except ValueError as e:
        if isinstance(e, ServiceError):
            raise
        raise ServiceError(f"Can't read {os.path.basename(p)}: {e}")


def export(store, path, today):
    props = {p["id"]: p for p in store["properties"]}
    head = ["Property", "Customer", "Equipment", "Make", "Model", "Serial",
            "Installed", "Warranty ends", "Warranty", "Service", "Every",
            "Next due"]
    rows = []
    for e in store["equipment"]:
        p = props.get(e["property"], {})
        end = warranty_end(e)
        rows.append([p.get("name", ""), p.get("customer", ""), e["kind"],
                     e["make"], e["model"], e["serial"], e["installed"],
                     end.isoformat() if end else "",
                     warranty_status(e, today), "", "", ""])
    for s in store["services"]:
        p = props.get(s["property"], {})
        rows.append([p.get("name", ""), p.get("customer", ""), "", "", "",
                     "", "", "", "", s["title"],
                     f"{s['every']} {s['unit']}", next_due(s).isoformat()])
    return _io.write_table(path, head, rows, "Service records")
