"""Outside load report: takeoff inputs out, the designer's report in
(QuantiSheet 1.2, #12).

QuantiSheet does not calculate heating or cooling loads (Jon, Nov 4: "No
in-house load calcs"). It does two things:

1. Gathers the inputs an outside designer needs for each room - floor
   area, ceiling height, exterior wall length and height, window and door
   areas (with the way they face when known) - from the drawing's takeoff
   where it can, typed in where it can't, and exports them as a printable
   PDF and a CSV. Every value says where it came from: measured (takeoff),
   entered (typed), or missing.
2. Attaches the designer's report PDF to the job and records what it
   says: heating and cooling load, the recommended equipment, who did it
   and when. A changeout proposal shows that report, or warns when there
   isn't one.

No sizing math here or anywhere it's used. The trademarked names of the
industry's load and duct design procedures never appear in what a user
sees (the test suite checks this).

No network calls.
"""
import csv
import datetime as dt
import os
import re
import shutil

from . import files
from ..dmoney import c2 as _c2

FILE = "service_load_reports.json"
KIND = "service_load_reports"
FOLDER = "load_reports"
ORIENT = ("N", "E", "S", "W", "unknown")
SOURCES = ("measured", "entered", "missing")
FIELDS = (("floor_sf", "Floor area", "SF"),
          ("ceiling_ft", "Ceiling height", "ft"),
          ("ext_wall_lf", "Exterior wall length", "LF"),
          ("wall_height_ft", "Exterior wall height", "ft"))
BANNED = ("manual j", "manual d", "manual s", "acca")
NOTE = ("Inputs for the outside designer. QuantiSheet doesn't calculate "
        "loads; the designer's report decides the equipment size.")


class LoadReportError(ValueError):
    pass


def blank():
    return {"kind": KIND, "version": 1, "next": 1, "jobs": []}


def default_path():
    return files.path_for(FILE)


def load(path=None):
    return files.read(path or default_path(), KIND, blank)


def save(store, path=None):
    return files.write(path or default_path(), store)


def get(store, rid):
    for j in store["jobs"]:
        if j["id"] == rid or j["number"] == rid:
            return j
    raise LoadReportError("That load report job isn't on file.")


# ---- values with their source --------------------------------------------

def val(value=None, source=None):
    """{"value", "source"}: a number and where it came from."""
    if value in (None, ""):
        return {"value": None, "source": "missing"}
    try:
        x = float(str(value).replace(",", ""))
    except ValueError:
        raise LoadReportError(f"{value!r} isn't a number.") from None
    if x < 0 or x > 1e6:
        raise LoadReportError(f"{x:g} is out of range.")
    src = source or "entered"
    if src not in SOURCES[:2]:
        raise LoadReportError(f"Unknown source {src!r}.")
    return {"value": _c2(x), "source": src}


def room(name, **kw):
    """A room; kw: floor_sf, ceiling_ft, ext_wall_lf, wall_height_ft (a
    number = entered, or a val() dict), windows / doors {orient: number or
    val()}."""
    name = files.txt(name, 80)
    if not name:
        raise LoadReportError("Name each room.")

    def v(x):
        return dict(x) if isinstance(x, dict) else val(x)
    out = {"name": name}
    for key, _l, _u in FIELDS:
        out[key] = v(kw.get(key))
    for kind in ("windows", "doors"):
        got = kw.get(kind) or {}
        bad = [k for k in got if k not in ORIENT]
        if bad:
            raise LoadReportError(f"{name}: facing must be N, E, S, W or "
                                  "unknown.")
        out[kind] = {o: v(got[o]) for o in ORIENT if got.get(o) not in
                     (None, "")}
    return out


_ORIENT_WORD = {"north": "N", "east": "E", "south": "S", "west": "W",
                "n": "N", "e": "E", "s": "S", "w": "W"}


def _facing(label):
    for tok in re.findall(r"[a-z]+", label.lower()):
        if tok in _ORIENT_WORD:
            return _ORIENT_WORD[tok]
    return "unknown"


def from_takeoff(items, unit_to_ft=None):
    """Rooms from the drawing's takeoff (annotate.takeoff_items): area
    markups are rooms (their label is the room name); an area labelled
    "<room> window [N/E/S/W]" or "<room> door ..." is glazing / a door; a
    length labelled "<room> exterior wall" is that room's wall. Values in
    feet units only (SF, LF, ft) are taken; anything else is left out so
    it stays visibly missing. Returns rooms, all values "measured"."""
    rooms, extra = {}, []
    ok_area = {"sf", "ft2", "sq ft", "ft²"}
    ok_len = {"lf", "ft", "'"}
    for it in items or ():
        label = " ".join(str(it.get("label") or "").split())
        unit = str(it.get("unit") or "").lower().strip()
        typ = it.get("type")
        if not label:
            continue
        low = label.lower()
        qty = float(it.get("value") or 0) * float(it.get("multiplier") or 1)
        if typ == "area" and unit in ok_area and not re.search(
                r"\b(?:window|glass|glazing|door)s?\b", low):
            r = rooms.setdefault(label, room(label))
            r["floor_sf"] = val(qty + (r["floor_sf"]["value"] or 0),
                                "measured")
        else:
            extra.append((typ, unit, label, low, qty))
    for typ, unit, label, low, qty in extra:
        target = next((r for n, r in sorted(rooms.items(), key=lambda x:
                                             -len(x[0]))
                       if low.startswith(n.lower() + " ")), None)
        if target is None:
            continue
        if typ == "length" and unit in ok_len and "exterior wall" in low:
            cur = target["ext_wall_lf"]["value"] or 0
            target["ext_wall_lf"] = val(cur + qty, "measured")
        elif typ == "area" and unit in ok_area:
            kind = "doors" if re.search(r"\bdoors?\b", low) else "windows"
            o = _facing(label[len(target["name"]):])
            cur = (target[kind].get(o) or {}).get("value") or 0
            target[kind][o] = val(cur + qty, "measured")
    return list(rooms.values())


def merge_rooms(old, new):
    """Takeoff rooms over typed ones: a measured value replaces an entered
    or missing one; typed values the takeoff doesn't have are kept."""
    by = {r["name"].lower(): r for r in old}
    out = [dict(r) for r in old]
    idx = {r["name"].lower(): i for i, r in enumerate(out)}
    for r in new:
        k = r["name"].lower()
        if k not in by:
            out.append(r)
            continue
        cur = dict(out[idx[k]])
        for key, _l, _u in FIELDS:
            if r[key]["source"] == "measured":
                cur[key] = r[key]
        for kind in ("windows", "doors"):
            m = dict(cur.get(kind) or {})
            m.update({o: v for o, v in r[kind].items()
                      if v["source"] == "measured"})
            cur[kind] = m
        out[idx[k]] = cur
    return out


# ---- jobs --------------------------------------------------------------------

def add(store, customer, site, rooms=(), property_id="", when=None,
        notes=""):
    customer = files.txt(customer)
    site = files.txt(site, 300)
    if not customer:
        raise LoadReportError("Name the customer.")
    if not site:
        raise LoadReportError("Name the site.")
    try:
        day = files.iso_date(when or dt.date.today(), "Date", blank_ok=False)
    except files.FileError as e:
        raise LoadReportError(str(e)) from e
    n = int(store.get("next") or 1)
    store["next"] = n + 1
    job = {"id": files.new_id(), "number": f"LR-{n:04d}", "date": day,
           "customer": customer, "site": site,
           "property_id": property_id or "", "notes": files.txt(notes, 2000),
           "rooms": [dict(r) for r in rooms], "exports": [], "report": None}
    store["jobs"].append(job)
    return job["id"]


def missing(job):
    """[(room, what)] still missing - shown before an export."""
    out = []
    for r in job["rooms"]:
        for key, label, _u in FIELDS:
            if r[key]["source"] == "missing":
                out.append((r["name"], label))
        if not r.get("windows"):
            out.append((r["name"], "Windows (none entered)"))
    return out


def _cell(v):
    return "" if v["value"] is None else f"{v['value']:g}"


def _openings(r, kind):
    return "; ".join(f"{o} {_cell(v)} SF ({v['source']})"
                     for o, v in (r.get(kind) or {}).items()) or "missing"


def export_csv(job, path):
    head = ["Room"]
    for _k, label, unit in FIELDS:
        head += [f"{label} ({unit})", f"{label} source"]
    head += ["Windows SF by facing (source)", "Doors SF by facing (source)"]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow([f"{job['number']} - {job['customer']} - {job['site']}"])
        w.writerow([NOTE])
        w.writerow(head)
        for r in job["rooms"]:
            row = [r["name"]]
            for key, _l, _u in FIELDS:
                row += [_cell(r[key]), r[key]["source"]]
            row += [_openings(r, "windows"), _openings(r, "doors")]
            w.writerow(row)
    job["exports"].append({"kind": "csv", "on": dt.date.today().isoformat(),
                           "file": os.path.basename(path)})
    return path


def export_pdf(job, path, comp=None):
    from .leave_behind import _wrap
    from .pdfdoc import Sheet, fit
    sheet = Sheet("Load Calculation Inputs", comp, subtitle=job["number"])
    sheet.section("01", "Job")
    y = sheet.y + 12
    sheet.text(36, y, job["customer"], 11, True)
    sheet.text(36, y + 14, job["site"], 9)
    sheet.text(400, y, f"Date: {job['date']}", 9)
    sheet.y = y + 22
    for chunk in _wrap(NOTE + "  M = measured from the drawings, E = "
                       "entered by hand, - = missing.", 112):
        sheet.y += 11
        sheet.text(36, sheet.y, chunk, 8.5, True)
    sheet.y += 8
    sheet.section("02", "Rooms")
    cols = ((36, "Room"), (190, "Floor SF"), (250, "Ceiling ft"),
            (312, "Ext wall LF"), (382, "Wall ht ft"))
    sheet.y += 14
    for x, t in cols:
        sheet.label(x, sheet.y, t)
    sheet.label(442, sheet.y, "Windows / doors SF by facing")
    tag = {"measured": "M", "entered": "E", "missing": "-"}
    for r in job["rooms"]:
        sheet.need(28)
        sheet.y += 14
        sheet.text(36, sheet.y, fit(r["name"], 150, 9.5), 9.5, True)
        for (x, _t), (key, _l, _u) in zip(cols[1:], FIELDS):
            v = r[key]
            sheet.text(x, sheet.y, (f"{_cell(v)} " if v["value"] is not None
                                    else "") + tag[v["source"]], 9)
        for i, kind in enumerate(("windows", "doors")):
            got = r.get(kind) or {}
            text = (kind.title() + ": " + (", ".join(
                f"{o} {_cell(v)} {tag[v['source']]}" for o, v in got.items())
                or "-"))
            sheet.text(442, sheet.y + 11 * i, fit(text, 134, 8), 8)
        sheet.y += 10
    gaps = missing(job)
    if gaps:
        sheet.need(30)
        sheet.y += 8
        sheet.section("03", "Still missing")
        for name, what in gaps:
            sheet.need(12)
            sheet.y += 11
            sheet.text(36, sheet.y, fit(f"{name}: {what}", 540, 8.5), 8.5)
    job["exports"].append({"kind": "pdf", "on": dt.date.today().isoformat(),
                           "file": os.path.basename(path)})
    return sheet.save(path)


def _is_pdf(path):
    try:
        with open(path, "rb") as fh:
            return fh.read(5) == b"%PDF-"
    except OSError:
        return False


def attach_report(store, rid, pdf_path, designer, report_date, heating_btuh="",
                  cooling_btuh="", recommended="", notes=""):
    """Copy the designer's report into the data folder and record what it
    says. The original file is left where it was."""
    job = get(store, rid)
    designer = files.txt(designer, 120)
    if not designer:
        raise LoadReportError("Who prepared the report?")
    if not pdf_path or not os.path.isfile(pdf_path) or not _is_pdf(pdf_path):
        raise LoadReportError("Pick the designer's report PDF.")
    try:
        on = files.iso_date(report_date, "Report date", blank_ok=False)
    except files.FileError as e:
        raise LoadReportError(str(e)) from e

    def btu(x, what):
        if x in (None, ""):
            return None
        try:
            v = float(str(x).replace(",", ""))
        except ValueError:
            raise LoadReportError(f"{what}: {x!r} isn't a number.") from None
        if v <= 0 or v > 1e8:
            raise LoadReportError(f"{what} is out of range.")
        return round(v)
    folder = files.path_for(FOLDER)
    os.makedirs(folder, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9 ._-]+", "_", os.path.basename(pdf_path))
    dest = os.path.join(folder, f"{job['number']} {safe}")
    shutil.copyfile(pdf_path, dest)
    job["report"] = {"file": dest, "original": os.path.basename(pdf_path),
                     "designer": designer, "date": on,
                     "heating_btuh": btu(heating_btuh, "Heating load"),
                     "cooling_btuh": btu(cooling_btuh, "Cooling load"),
                     "recommended": files.txt(recommended, 200),
                     "notes": files.txt(notes, 1000),
                     "attached_on": dt.date.today().isoformat()}
    return job["report"]


def status(job):
    """One line: what the attached report says, or that there isn't one."""
    r = (job or {}).get("report")
    if not r:
        return "No load report attached."
    bits = [f"Load report attached: {r['designer']}, {r['date']}"]
    if r.get("cooling_btuh"):
        bits.append(f"cooling {r['cooling_btuh']:,} BTU/h")
    if r.get("heating_btuh"):
        bits.append(f"heating {r['heating_btuh']:,} BTU/h")
    if r.get("recommended"):
        bits.append(f"recommended {r['recommended']}")
    return "; ".join(bits) + "."


def summary(job):
    return f"{job['number']} {job['customer']} - {status(job)}"


def for_site(store, property_id="", customer=""):
    want = " ".join(str(customer or "").lower().split())
    return [j for j in store["jobs"] if (property_id and j.get(
        "property_id") == property_id) or (not property_id and want and
        " ".join(j["customer"].lower().split()) == want)]
