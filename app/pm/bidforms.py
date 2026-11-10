"""Bid forms, addenda and the bid calendar for bid packages.

A bid form is the list of lines every bidder prices on the bid page, so
bids come back in the same shape and level line by line:

    Lump sum            one price for the line
    Unit price          bidder gives a unit price; total = qty x price
    Allowance           a fixed amount you set (qty x unit price you enter
                        in Qty) - carried in every bid as written
    Alternate           add (or deduct, negative) price, not in the base bid
    Yes / No            a question ("Bid bond included?")
    Text                a short answer ("Lead time for switchgear")

Templates come from the built-in set below, your own library (saved from
any package), another package, a CSV / Excel sheet, or straight from the
takeoff of the open drawings (each measured group becomes a unit-price
line with its quantity).
"""
import csv
import datetime as _dt
import json
import os
import re
from ..dmoney import c2 as _c2

TYPES = ["Lump sum", "Unit price", "Allowance", "Alternate", "Yes / No",
         "Text"]
PRICED = ("Lump sum", "Unit price", "Allowance")


def L(item, description, type="Lump sum", qty=None, unit="", note=""):
    return {"item": str(item), "description": description, "type": type,
            "qty": qty, "unit": unit, "note": note}


BUILT_IN = {
    "General - lump sum": [
        L(1, "Base bid - complete scope per plans and specs"),
        L(2, "Bond (if required)", "Lump sum"),
        L(3, "Bid bond included?", "Yes / No"),
        L(4, "Addenda acknowledged and included?", "Yes / No"),
        L(5, "Exclusions / clarifications", "Text"),
    ],
    "Site utilities": [
        L(1, "Mobilization", "Lump sum"),
        L(2, "8 in PVC SDR-35 gravity sewer, all depths", "Unit price", 0,
          "LF"),
        L(3, "48 in precast manhole, 0-8 ft", "Unit price", 0, "EA"),
        L(4, "Manhole extra depth over 8 ft", "Unit price", 0, "VF"),
        L(5, "Sewer service lateral, 4 in", "Unit price", 0, "EA"),
        L(6, "Water main, PVC C900", "Unit price", 0, "LF"),
        L(7, "Trench pavement restoration", "Unit price", 0, "SY"),
        L(8, "Rock excavation (allowance)", "Allowance", 0, "CY"),
        L(9, "Dewatering", "Lump sum"),
        L(10, "Testing (air, mandrel, CCTV, pressure)", "Lump sum"),
        L(11, "Traffic control", "Lump sum"),
        L(12, "Alt 1: ductile iron in lieu of PVC (add)", "Alternate"),
        L(13, "Bid bond included?", "Yes / No"),
    ],
    "Earthwork & paving": [
        L(1, "Mobilization", "Lump sum"),
        L(2, "Clearing & grubbing", "Lump sum"),
        L(3, "Unclassified excavation", "Unit price", 0, "CY"),
        L(4, "Embankment / fill, compacted", "Unit price", 0, "CY"),
        L(5, "Undercut & replace (allowance)", "Allowance", 0, "CY"),
        L(6, "Aggregate base course", "Unit price", 0, "SY"),
        L(7, "Asphalt surface course", "Unit price", 0, "TON"),
        L(8, "Concrete curb & gutter", "Unit price", 0, "LF"),
        L(9, "Erosion control", "Lump sum"),
        L(10, "Bid bond included?", "Yes / No"),
    ],
    "Concrete": [
        L(1, "Footings, complete", "Unit price", 0, "CY"),
        L(2, "Foundation walls, complete", "Unit price", 0, "CY"),
        L(3, "Slab on grade, complete", "Unit price", 0, "SF"),
        L(4, "Elevated slabs, complete", "Unit price", 0, "SF"),
        L(5, "Rebar (if separate)", "Unit price", 0, "TON"),
        L(6, "Winter protection", "Lump sum"),
        L(7, "Testing excluded?", "Yes / No"),
    ],
    "Plumbing": [
        L(1, "Base bid - plumbing complete", "Lump sum"),
        L(2, "Fixtures (per schedule)", "Lump sum"),
        L(3, "Underground sanitary", "Lump sum"),
        L(4, "Domestic water distribution", "Lump sum"),
        L(5, "Gas piping", "Lump sum"),
        L(6, "Permit & fees included?", "Yes / No"),
        L(7, "Lead time for water heaters", "Text"),
    ],
    "Mechanical / HVAC": [
        L(1, "Base bid - HVAC complete", "Lump sum"),
        L(2, "Equipment (per schedule)", "Lump sum"),
        L(3, "Ductwork & insulation", "Lump sum"),
        L(4, "Controls", "Lump sum"),
        L(5, "Test & balance", "Lump sum"),
        L(6, "Equipment lead time", "Text"),
    ],
    "Electrical": [
        L(1, "Base bid - electrical complete", "Lump sum"),
        L(2, "Service & distribution", "Lump sum"),
        L(3, "Lighting & controls", "Lump sum"),
        L(4, "Branch power & devices", "Lump sum"),
        L(5, "Fire alarm", "Lump sum"),
        L(6, "Temporary power", "Lump sum"),
        L(7, "Switchgear lead time", "Text"),
    ],
}


# ------------------------------------------------------------- library
def _lib_path():
    from .. import settings
    return os.path.join(settings.DIR, "bid_forms.json")


def library():
    """{name: lines}: built-in templates, then your own (yours win)."""
    out = {k: [dict(x) for x in v] for k, v in BUILT_IN.items()}
    try:
        with open(_lib_path(), encoding="utf-8") as f:
            mine = json.load(f)
        for k, v in (mine or {}).items():
            if isinstance(v, list):
                out[str(k)] = clean(v)
    except (OSError, ValueError):
        pass
    return out


def save_template(name, lines):
    from .. import settings
    os.makedirs(settings.DIR, exist_ok=True)
    try:
        with open(_lib_path(), encoding="utf-8") as f:
            mine = json.load(f) or {}
    except (OSError, ValueError):
        mine = {}
    mine[str(name).strip()[:80]] = clean(lines)
    with open(_lib_path(), "w", encoding="utf-8") as f:
        json.dump(mine, f, indent=1)
    return name


def clean(lines):
    """Lines with known keys and types; numbered when they have no item."""
    out = []
    for i, ln in enumerate(lines or []):
        if not isinstance(ln, dict):
            continue
        d = str(ln.get("description") or "").strip()
        if not d:
            continue
        t = str(ln.get("type") or "Lump sum").strip()
        t = _TYPE_ALIAS.get(t.lower(), t)
        if t not in TYPES:
            t = "Lump sum"
        try:
            q = float(str(ln.get("qty")).replace(",", "")) \
                if ln.get("qty") not in (None, "") else None
        except ValueError:
            q = None
        out.append({"item": str(ln.get("item") or i + 1).strip()[:12],
                    "description": d[:300], "type": t,
                    "qty": q, "unit": str(ln.get("unit") or "")[:12],
                    "note": str(ln.get("note") or "")[:300]})
    return out


_TYPE_ALIAS = {"ls": "Lump sum", "lump": "Lump sum", "lump sum": "Lump sum",
               "unit": "Unit price", "unit price": "Unit price",
               "up": "Unit price", "allowance": "Allowance",
               "alt": "Alternate", "alternate": "Alternate",
               "yes/no": "Yes / No", "yes / no": "Yes / No",
               "y/n": "Yes / No", "text": "Text", "question": "Text"}


def _read_table(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in (".xlsx", ".xlsm"):
        import openpyxl
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        try:
            rows = [[("" if c is None else str(c)) for c in r]
                    for r in wb.active.iter_rows(values_only=True)]
        finally:
            wb.close()                  # read-only keeps the file open
    elif ext in (".xls", ".ods", ".numbers"):
        # the old binary Excel format was read as text and came out as
        # garbage or a crash (review 3 #42)
        raise ValueError(f"{os.path.basename(path)} is an older spreadsheet "
                         "format. Save it as .xlsx or .csv and import that.")
    else:
        from ..textio import open_csv         # Excel's Windows-1252 too
        with open_csv(path) as f:
            rows = list(csv.reader(f))
    return [r for r in rows if any(str(c).strip() for c in r)]


def import_rows(path):
    """Bidders from a CSV or Excel sheet: [{company, contact, email, phone,
    trade}] (headers in any order and case)."""
    rows = _read_table(path)
    if not rows:
        return []
    head = [str(h).strip().lower() for h in rows[0]]

    def col(*names):
        for n in names:
            for i, h in enumerate(head):
                if n in h:
                    return i
        return None
    ci = {"company": col("company", "firm", "vendor", "subcontractor",
                         "name"),
          "contact": col("contact", "estimator", "person"),
          "email": col("email", "e-mail", "mail"),
          "phone": col("phone", "tel", "cell"),
          "trade": col("trade", "csi", "division", "scope")}
    if ci["contact"] == ci["company"]:
        ci["contact"] = None
    out = []
    for r in rows[1:]:
        d = {k: (str(r[i]).strip() if i is not None and i < len(r) else "")
             for k, i in ci.items()}
        if not (d["company"] or d["email"]):
            continue
        if d["email"] and "@" not in d["email"]:
            d["email"] = ""
        out.append(d)
    return out


def import_lines(path):
    """Bid form lines from a CSV or Excel sheet with columns like Item,
    Description, Type, Qty, Unit (headers in any order and case)."""
    rows = _read_table(path)
    if not rows:
        return []
    head = [str(h).strip().lower() for h in rows[0]]

    def col(*names):
        for n in names:
            for i, h in enumerate(head):
                if h == n or h.startswith(n):
                    return i
        return None
    ci = {"item": col("item", "no", "#", "line"),
          "description": col("description", "desc", "scope", "work"),
          "type": col("type", "kind"),
          "qty": col("qty", "quantity"), "unit": col("unit", "uom"),
          "note": col("note", "comment")}
    if ci["description"] is None:              # no header row
        ci = {"item": 0, "description": 1, "type": None,
              "qty": 2 if len(rows[0]) > 2 else None,
              "unit": 3 if len(rows[0]) > 3 else None, "note": None}
        body = rows
    else:
        body = rows[1:]
    out = []
    for r in body:
        d = {k: (r[i] if i is not None and i < len(r) else "")
             for k, i in ci.items()}
        if not d.get("type"):
            d["type"] = "Unit price" if d.get("qty") and d.get("unit") \
                else "Lump sum"
        out.append(d)
    return clean(out)


def from_takeoff(doc):
    """Unit-price lines from the takeoff in `doc`: one per measured group,
    with its total quantity - so every bidder prices your quantities."""
    from .. import annotate
    groups = {}
    for it in annotate.takeoff_items(doc):
        g = it.get("group") or it.get("type", "").title() or "Item"
        unit = _unit(it)
        k = (g, unit)
        groups[k] = groups.get(k, 0.0) + float(it.get("value") or 0) * \
            float(it.get("multiplier") or 1)
    out = []
    for i, ((g, unit), q) in enumerate(sorted(groups.items()), 1):
        out.append({"item": str(i), "description": g, "type": "Unit price",
                    "qty": _c2(q), "unit": unit, "note": ""})
    return out


def _unit(it):
    u = str(it.get("unit") or "")
    t = it.get("type")
    if t == "count":
        return "EA"
    if t == "area":
        return "SF" if "ft" in u else u.upper()
    if t == "volume":
        return "CY"
    return {"ft": "LF", "m": "M", "in": "IN", "yd": "YD"}.get(u, u.upper())


# ------------------------------------------------------------- totals
_GROUPED = re.compile(r"[-+]?\d{1,3}(,\d{3})+(\.\d*)?")


def num(v):
    """A typed amount, or None. Commas only as thousands separators:
    "1,234.50" is 1234.5 but "1,2,3" is not a number (review 3 #20)."""
    if v in (None, ""):
        return None
    t = str(v).replace("$", "").strip()
    if "," in t:
        if not _GROUPED.fullmatch(t):
            return None
        t = t.replace(",", "")
    try:
        return float(t)
    except ValueError:
        return None


def line_total(line, value):
    """Dollars a line adds: lump sum = price; unit price = qty x price;
    allowance = qty (the amount you set) or the bidder's price."""
    t = line.get("type")
    v = num(value)
    if t == "Lump sum":
        return v or 0.0
    if t == "Unit price":
        return (v or 0.0) * (num(line.get("qty")) or 0.0)
    if t == "Allowance":
        q = num(line.get("qty"))
        # a blank or 0 amount means "not set": use the bidder's price
        # (the built-in forms ship their allowances at 0)
        return q if q else (v or 0.0)
    return 0.0


def totals(lines, values):
    """{"base", "alternates": {item: amount}, "missing": [items]} for a
    bidder's values {index: value}. Missing = priced lines left blank."""
    base, alts, missing = 0.0, {}, []
    for i, ln in enumerate(lines or []):
        v = (values or {}).get(str(i))
        t = ln.get("type")
        if t in PRICED:
            if t != "Allowance" and num(v) is None:
                missing.append(ln.get("item") or str(i + 1))
            base += line_total(ln, v)
        elif t == "Alternate" and num(v) is not None:
            alts[ln.get("item") or str(i + 1)] = num(v)
    return {"base": _c2(base), "alternates": alts, "missing": missing}


def to_leveling(rec):
    """{bidder: [rows]} for app.leveling from the package's bid forms (and
    plain amounts from bidders who only sent a number)."""
    lines = rec.get("form") or []
    out = {}
    for b in rec.get("bidders") or []:
        name = b.get("company") or b.get("contact") or "?"
        vals = b.get("form_values") or {}
        rows = []
        if lines and vals:
            for i, ln in enumerate(lines):
                t = ln.get("type")
                if t not in PRICED:
                    continue
                v = num(vals.get(str(i)))
                if v is None and t != "Allowance":
                    continue                     # omitted: leveling sees it
                # same rules as line_total (review 3 #9)
                q = num(ln.get("qty"))
                qty = q if q is not None else 1.0
                if t == "Unit price":
                    price = v
                elif t == "Allowance":
                    # live's rule (line_total): 0/blank = use the bid
                    price = q if q else (v or 0.0)
                    qty = 1.0
                else:
                    price, qty = v, 1.0
                rows.append({"desc": ln.get("description"),
                             "unit": ln.get("unit") or
                             ("LS" if t != "Unit price" else "EA"),
                             "qty": qty, "price": price,
                             "item_no": ln.get("item") or str(i + 1),
                             "bidder": name, "note": ""})
        elif num(b.get("amount")) is not None:
            rows.append({"desc": rec.get("title") or "Base bid",
                         "unit": "LS", "qty": 1.0,
                         "price": num(b.get("amount")), "item_no": "1",
                         "bidder": name, "note": ""})
        if rows:
            out[name] = rows
    return out


# ------------------------------------------------------------- addenda
def next_addendum(rec):
    nums = [int(m.group(1)) for a in rec.get("addenda") or []
            for m in [re.search(r"(\d+)", str(a.get("number") or ""))] if m]
    return (max(nums) + 1) if nums else 1


# ------------------------------------------------------------- calendar
EVENT_FIELDS = [("due", "Bids due", "due_time"),
                ("prebid", "Pre-bid meeting", None),
                ("rfi_due", "Questions due", None),
                ("site_visit", "Site visit", None)]


def _as_date(v):
    if not v:
        return None
    if isinstance(v, _dt.date):
        return v
    s = str(v).strip()
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        try:
            return _dt.date(int(m.group(1)), int(m.group(2)),
                            int(m.group(3)))
        except ValueError:
            return None
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", s)
    if m:
        y = int(m.group(3))
        y = y + 2000 if y < 100 else y
        try:
            return _dt.date(y, int(m.group(1)), int(m.group(2)))
        except ValueError:
            return None
    return None


def _time_of(s):
    m = re.search(r"(\d{1,2})(?::(\d{2}))?\s*([AaPp])\.?[Mm]", str(s or ""))
    if not m:
        return None
    h = int(m.group(1)) % 12 + (12 if m.group(3).lower() == "p" else 0)
    return _dt.time(h, int(m.group(2) or 0))


def events(store, project=None):
    """Calendar events of one project's bid packages: [{date, time, kind,
    title, project, package, record, folder, status}]."""
    out = []
    for r in store.list("bidpkg"):
        if r.get("_deleted"):
            continue
        for key, kind, tkey in EVENT_FIELDS:
            d = _as_date(r.get(key))
            if d is None:
                continue
            t = _time_of(r.get(tkey) if tkey else r.get(key))
            out.append({"date": d, "time": t, "kind": kind,
                        "title": f"{kind}: {r.get('title') or ''}",
                        "project": project or store.name,
                        "package": r.get("_no") or "",
                        "record": r.get("_id"),
                        "folder": getattr(store, "folder", ""),
                        "status": r.get("status") or ""})
    return out


def all_events(folders=None):
    """Events across every project this PC knows (Project Center's
    recent projects, plus any `folders` given)."""
    from .. import settings
    from .store import open_store
    seen, out = set(), []
    for f in list(folders or []) + list(settings.get("pm_recent", []) or []):
        key = os.path.normcase(os.path.abspath(f))
        if key in seen or not os.path.isdir(f):
            continue
        seen.add(key)
        try:
            st = open_store(f)
        except Exception:
            continue
        out += events(st)
    out.sort(key=lambda e: (e["date"], e["time"] or _dt.time(0, 0)))
    return out


def to_ics(evts, path):
    """An .ics calendar file (Outlook, Google, phones)."""
    def esc(s):
        return str(s).replace("\\", "\\\\").replace(";", "\\;") \
            .replace(",", "\\,").replace("\n", "\\n")
    stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0",
             "PRODID:-//QuantiSheet//Bid Calendar//EN", "CALSCALE:GREGORIAN"]
    for i, e in enumerate(evts):
        uid = f"{e.get('record') or i}-{e['kind'].replace(' ', '')}" \
              f"@quantisheet"
        lines += ["BEGIN:VEVENT", f"UID:{uid}", f"DTSTAMP:{stamp}"]
        if e.get("time"):
            start = _dt.datetime.combine(e["date"], e["time"])
            end = start + _dt.timedelta(hours=1)
            lines += [f"DTSTART:{start:%Y%m%dT%H%M%S}",
                      f"DTEND:{end:%Y%m%dT%H%M%S}"]
        else:
            lines += [f"DTSTART;VALUE=DATE:{e['date']:%Y%m%d}",
                      f"DTEND;VALUE=DATE:"
                      f"{e['date'] + _dt.timedelta(days=1):%Y%m%d}"]
        lines += [f"SUMMARY:{esc(e['project'] + ' - ' + e['title'])}",
                  f"DESCRIPTION:{esc(e.get('package', ''))}",
                  "END:VEVENT"]
        if e["kind"] == "Bids due":
            lines.insert(-1, "BEGIN:VALARM")
            lines.insert(-1, "TRIGGER:-P1D")
            lines.insert(-1, "ACTION:DISPLAY")
            lines.insert(-1, f"DESCRIPTION:{esc(e['title'])}")
            lines.insert(-1, "END:VALARM")
    lines.append("END:VCALENDAR")
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write("\r\n".join(lines) + "\r\n")
    return path
