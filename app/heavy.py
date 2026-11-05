"""Heavy civil estimating (HeavyBid-style): crews and production rates.

You estimate an activity ("8 in sewer, 6-10 ft deep") by the crew that
builds it and how fast: crew hours = quantity / production rate, and the
crew's hourly cost is its labor (burdened) plus its equipment (owned or
rented, with fuel). Materials, subcontracts and trucking are added per
activity. Indirects are priced by the job's duration. The owner's bid
schedule (pay items) gets the direct cost of its activities plus a share of
indirects and markup ("spreading"), optionally unbalanced, and the owner's
quantities are checked against your takeoff.

Company libraries - equipment, labor classes and crews - live in the price
database (shared by your estimators); a job's estimate lives in the PDF
(quantisheet_heavy.json). Money is Decimal throughout (dmoney.py).
"""
import copy
import csv
import datetime as _dt
import json
import logging
import math
import os
import uuid
from decimal import ROUND_HALF_UP, Decimal

from . import embfiles
from .dmoney import D, bad, cents

log = logging.getLogger(__name__)

FILE = "quantisheet_heavy.json"
STARTER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data",
                       "heavy_starter.json")
PERS = ("hour", "day")
INDIRECT_PERS = ("week", "month", "day", "LS")
QTY_FLAG_PCT = Decimal(10)
HUNDRED = Decimal(100)


class HeavyError(ValueError):
    pass


def _id():
    return uuid.uuid4().hex[:10]


def _now():
    return _dt.datetime.now().isoformat(timespec="minutes")


def _who(by=None):
    if by:
        return by
    from . import settings
    return settings.author()


# ================================================================ library
# equipment: {code, desc, class, own_hr, op_hr, fuel_gph, rent_month,
#             hours_month, use: "own" | "rent"}
# labor:     {code, desc, base, fringe, ot_pct, wc_rate, fica, unemp,
#             gl_pct, other_pct}
# crews:     {code, desc, labor: [[labor code, count]],
#             equipment: [[equipment code, count]]}
KINDS = {"equipment": "heavy_equipment", "labor": "heavy_labor",
         "crews": "heavy_crews", "activities": "heavy_activities",
         "masters": "heavy_masters"}
# what a saved activity keeps (job-specific things - quantity, takeoff
# group, pay item, quotes, schedule links - are left behind)
TEMPLATE_KEYS = ("name", "code", "unit", "crew", "rate", "per",
                 "materials", "sub", "tags", "notes")


def _starter():
    try:
        with open(STARTER, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"equipment": [], "labor": [], "crews": [], "settings": {}}


def library():
    """{"equipment": {code: rec}, "labor": {...}, "crews": {...},
    "settings": {...}} from the price database, filled from the starter
    library the first time."""
    from . import pricedb
    out = {k: {} for k in KINDS}
    with pricedb.connect() as con:
        for kind, table in KINDS.items():
            for r in con.execute(f"SELECT code, data FROM {table}"):
                try:
                    out[kind][r["code"]] = json.loads(r["data"])
                except ValueError:
                    pass
        row = con.execute("SELECT value FROM meta WHERE key='heavy_settings'"
                          ).fetchone()
    settings = json.loads(row["value"]) if row else None
    if not any(out.values()) and settings is None:
        st = _starter()
        for kind in KINDS:
            save_items(kind, st.get(kind) or [], note=STARTER_NOTE)
        set_settings(st.get("settings") or {})
        return library()
    out["settings"] = dict(_starter().get("settings") or {},
                           **(settings or {}))
    return out


STARTER_NOTE = "starter library"


def starter_updates():
    """Starter rates nobody has edited (still saved as the starter library)
    that differ from the starter file this version ships: {kind: [new
    records]}. Read only. Saved estimates price from the library, so these
    are offered (one notice in the Civil Estimate window) and only applied
    by apply_starter_updates() - never silently on launch, which re-priced
    open bids company-wide on a shared price database (0.12.4 review B1)."""
    from . import pricedb
    st = _starter()
    stale = {}
    try:
        with pricedb.connect() as con:
            for kind in ("equipment", "labor", "crews"):
                new = {r.get("code"): r for r in st.get(kind) or []}
                for r in con.execute(
                        f"SELECT code, data, note FROM {KINDS[kind]}"):
                    rec = new.get(r["code"])
                    if rec is None or r["note"] != STARTER_NOTE:
                        continue
                    try:
                        cur = json.loads(r["data"])
                    except ValueError:
                        cur = None
                    if cur != rec:
                        stale.setdefault(kind, []).append(rec)
    except pricedb.PriceDBError:
        return {}
    return stale


def apply_starter_updates():
    """The person accepted the newer starter rates: write them (still marked
    as the starter library). Returns how many rates changed. Raises
    PriceDBError when the price database can't be written."""
    stale = starter_updates()
    for kind, items in stale.items():
        save_items(kind, items, note=STARTER_NOTE)
    return sum(len(v) for v in stale.values())


def save_items(kind, items, note=""):
    """Add or replace library records (each needs a "code")."""
    from . import pricedb
    table = KINDS[kind]
    who, stamp = pricedb.user(), pricedb.now()
    with pricedb.connect(write=True) as con:
        for it in items:
            code = str(it.get("code") or "").strip()
            if not code:
                raise HeavyError("Every item needs a code.")
            con.execute(f"INSERT OR REPLACE INTO {table} (code, data, "
                        "modified, modified_by, note) VALUES (?,?,?,?,?)",
                        (code, json.dumps(it), stamp, who, note))
    return len(items)


def delete_item(kind, code):
    from . import pricedb
    with pricedb.connect(write=True) as con:
        con.execute(f"DELETE FROM {KINDS[kind]} WHERE code=?", (code,))


def set_settings(values):
    from . import pricedb
    cur = {}
    with pricedb.connect() as con:
        row = con.execute("SELECT value FROM meta WHERE key='heavy_settings'"
                          ).fetchone()
        if row:
            cur = json.loads(row["value"])
    cur.update(values or {})
    pricedb.set_meta("heavy_settings", cur)
    return cur


# ------------------------------------------------------------ labor burden
def burden(rec, wages=None):
    """Cost of one hour of a labor class, broken down (all Decimal):
    {"base", "ot", "taxes", "wc", "gl", "other", "fringe", "total"}.
    ot_pct = share of hours worked at time-and-a-half; taxes = FICA +
    unemployment (%); wc_rate = workers' comp $ per $100 of payroll.
    `wages` (a job's prevailing wage for this class) overrides base and
    fringe."""
    w = (wages or {}).get(rec.get("code")) or {}
    base = D(w.get("base", rec.get("base")))
    fringe = D(w.get("fringe", rec.get("fringe")))
    ot = base * D(rec.get("ot_pct")) / HUNDRED / 2
    pay = base + ot
    taxes = pay * (D(rec.get("fica", "7.65")) + D(rec.get("unemp", "3.0"))) \
        / HUNDRED
    wc = pay * D(rec.get("wc_rate")) / HUNDRED
    gl = pay * D(rec.get("gl_pct")) / HUNDRED
    other = pay * D(rec.get("other_pct")) / HUNDRED
    total = pay + taxes + wc + gl + other + fringe
    return {"base": cents(base), "ot": cents(ot), "taxes": cents(taxes),
            "wc": cents(wc), "gl": cents(gl), "other": cents(other),
            "fringe": cents(fringe), "total": cents(total),
            "prevailing": bool(w)}


def equipment_rate(rec, fuel_price):
    """Cost of one hour of a machine: ownership (or rent spread over the
    hours it runs a month) + operating + fuel. {"own", "op", "fuel",
    "total"}."""
    if rec.get("use") == "rent":
        hrs = D(rec.get("hours_month") or 176)
        own = D(rec.get("rent_month")) / hrs if hrs else Decimal(0)
    else:
        own = D(rec.get("own_hr"))
    op = D(rec.get("op_hr"))
    fuel = D(rec.get("fuel_gph")) * D(fuel_price)
    return {"own": cents(own), "op": cents(op), "fuel": cents(fuel),
            "total": cents(own + op + fuel)}


LABOR_NUMS = ("base", "fringe", "ot_pct", "wc_rate", "fica", "unemp",
              "gl_pct", "other_pct")


def _unreadable(code, rec, keys, required=()):
    """Rate fields holding text D() would price at $0 ("twenty", "8.5O"),
    or left blank when they must be filled: ["LAB base 'twenty'"]."""
    out = []
    for k in keys:
        v = rec.get(k)
        if bad(v, blank_ok=k not in required):
            out.append(f"{code} {k} " + (repr(v) if str(
                "" if v is None else v).strip() else "(blank)"))
    return out


def crew_rate(crew, lib, job=None):
    """A crew's cost per working hour: {"labor", "equipment", "total",
    "people", "missing": [codes not in the library], "unreadable": [rate
    fields that are text or blank, priced at $0 - show them]}."""
    job = job or {}
    st = dict(lib.get("settings") or {}, **(job.get("settings") or {}))
    wages = job.get("wages") or {}
    labor = equip = Decimal(0)
    people, missing, unreadable = 0, [], []
    for code, n in crew.get("labor") or []:
        rec = lib["labor"].get(code)
        if rec is None:
            missing.append(code)
            continue
        w = wages.get(code) or {}
        unreadable += _unreadable(code, dict(rec, **{
            k: w[k] for k in ("base", "fringe") if k in w}), LABOR_NUMS,
            ("base",)) + _unreadable(f"crew {code}", {"count": n},
                                     ("count",), ("count",))
        labor += burden(rec, wages)["total"] * D(n)
        people += int(D(n))
    for code, n in crew.get("equipment") or []:
        rec = lib["equipment"].get(code)
        if rec is None:
            missing.append(code)
            continue
        rate = "rent_month" if rec.get("use") == "rent" else "own_hr"
        unreadable += _unreadable(code, rec, (rate, "op_hr", "fuel_gph") + (
            ("hours_month",) if rate == "rent_month" else ()), (rate,)) + \
            _unreadable(f"crew {code}", {"count": n}, ("count",), ("count",))
        equip += equipment_rate(rec, st.get("fuel", 4))["total"] * D(n)
    if crew.get("equipment"):
        unreadable += _unreadable("fuel", {"$/gal": st.get("fuel", 4)},
                                  ("$/gal",), ("$/gal",))
    return {"labor": cents(labor), "equipment": cents(equip),
            "total": cents(labor + equip), "people": people,
            "missing": missing, "unreadable": unreadable}


# ================================================================ job data
def blank():
    return {"settings": {"hours_per_day": 10, "markup_pct": 10,
                         "bond_pct": 0, "duration_weeks": 0},
            "activities": [], "pay_items": [], "indirects": [],
            "hauls": [], "versions": [], "wages": {}}


def read(doc):
    data = blank()
    try:
        if FILE in doc.embfile_names():
            saved = json.loads(doc.embfile_get(FILE).decode("utf-8"))
            if isinstance(saved, dict):
                for k, v in saved.items():
                    if k == "settings":
                        data["settings"].update(v or {})
                    else:
                        data[k] = v
    except Exception:
        log.warning("could not read the heavy civil estimate", exc_info=True)
    return data


def write(doc, data):
    embfiles.put(doc, FILE, json.dumps(data, indent=1).encode("utf-8"),
                 "QuantiSheet heavy civil estimate")


def add_activity(job, name, qty=0, unit="", crew="", rate=0, per="hour",
                 code="", pay_item="", tags=(), materials=(), sub=0,
                 group="", notes=""):
    if per not in PERS:
        raise HeavyError("Production is per hour or per day.")
    a = {"id": _id(), "name": name, "code": code, "pay_item": pay_item,
         "tags": list(tags), "qty": str(D(qty)), "unit": unit,
         "group": group, "crew": crew, "rate": str(D(rate)), "per": per,
         "materials": [dict(m) for m in materials], "sub": str(D(sub)),
         "notes": notes}
    job["activities"].append(a)
    return a


def takeoff_qty(doc, group):
    """The total of a takeoff group (measurements named `group`)."""
    from . import annotate
    tot, unit = Decimal(0), ""
    for it in annotate.totals_items(doc):
        if it.get("group") == group:
            tot += D(it["value"])
            unit = unit or it.get("unit", "")
    return tot, unit


# starting production rates for activities made from a takeoff (per crew
# hour). Rough industry rules of thumb - check them against your own
# production history (Civil > Production History).
START_RATES = {"pipe_small": ("PIPE", 35), "pipe_mid": ("PIPE", 25),
               "pipe_large": ("PIPE", 16), "structure": ("MH", 0.25),
               "volume": ("CUT", 60), "area": ("GRADE", 3600),
               "count": ("MH", 0.5)}


# Pipe production falls off with trench depth: more digging, a bigger box
# or shoring, slower backfill. Share of the 0-6 ft rate per depth band,
# from the takeoff group name ("8\" PDG, 10-14 ft deep"). An estimating
# starting point - tune it from your own crews (Civil > Production by
# Depth).
DEPTH_FACTORS = {"0-6": 1.0, "6-10": 0.8, "10-14": 0.6, "14-18": 0.45,
                 "over 18": 0.35, "unknown": 0.8}
DEPTH_LABELS = {"0-6": "0-6 ft deep", "6-10": "6-10 ft deep",
                "10-14": "10-14 ft deep", "14-18": "14-18 ft deep",
                "over 18": "over 18 ft deep",
                "unknown": "depth unknown (taken as about 8 ft)"}


def depth_factors(lib=None):
    st = (lib or {}).get("settings") or {}
    f = dict(DEPTH_FACTORS)
    for k, v in (st.get("depth_factors") or {}).items():
        try:
            if k in f and 0 < float(v) <= 2:
                f[k] = float(v)
        except (TypeError, ValueError):
            pass
    return f


def depth_band(name):
    """The depth band key of a takeoff group name ("unknown" for a civil
    group marked "depth unknown"), or None when the name says nothing
    about depth (a group you named yourself keeps the base rate)."""
    import re
    s = (name or "").lower()
    if "over 18 ft deep" in s:
        return "over 18"
    m = re.search(r"(\d+)-(\d+) ft deep", s)
    if m and f"{m.group(1)}-{m.group(2)}" in DEPTH_FACTORS:
        return f"{m.group(1)}-{m.group(2)}"
    return "unknown" if "depth unknown" in s else None


def _pipe_size(name):
    import re
    m = re.search(r'(\d+(?:\.\d+)?)\s*(?:"|in\b|-in|inch)', name or "")
    return float(m.group(1)) if m else None


_CIVIL_SHEET = None


def civil_pages(doc):
    """Pages that are civil / site sheets (number starting with C, or a
    utility, grading, paving or site title)."""
    import re
    from . import sheets
    global _CIVIL_SHEET
    if _CIVIL_SHEET is None:
        _CIVIL_SHEET = re.compile(r"\b(UTILIT|SEWER|SANITARY|WATER|STORM|"
                                  r"DRAIN|GRADING|SITE|PAVING|EROSION|"
                                  r"CIVIL)", re.I)
    out = []
    for r in sheets.scan(doc, numbers=False):
        num = (r["number"] or "").upper()
        # the sheet number's discipline letter decides; the title only
        # when there is no number (M101 "... DRAIN PIPING" is mechanical)
        if (num.startswith("C") and not num.startswith("CS")) or \
                (not num and _CIVIL_SHEET.search(r["title"] or "")):
            out.append(r["page"])
    return out


_PIPE_SHEET = None
_NOT_PIPE_SHEET = None
_OVERALL = None


def pipe_plan_pages(doc, pages=None, loose=False):
    """The civil plan sheets pipe is taken off from: utility, sewer, water,
    storm, drainage and yard/process piping plans - not details, profiles,
    notes, erosion control (SWPPP), demolition, existing conditions,
    grading, paving or covers, and not an "overall" plan when the area
    plans it is cut into are in the set (the same pipe drawn twice).

    loose=True: when no sheet title names pipe, every civil sheet that
    isn't one of those (better than taking off the whole civil set)."""
    import re
    from . import sheets
    global _PIPE_SHEET, _NOT_PIPE_SHEET, _OVERALL
    if _PIPE_SHEET is None:
        _PIPE_SHEET = re.compile(r"\b(UTILIT|SEWER|SANITARY|WATER|STORM|"
                                 r"DRAINAGE|PIPING|PIPELINE|FORCE\s*MAIN)",
                                 re.I)
        _NOT_PIPE_SHEET = re.compile(
            r"\b(DETAILS?|S\.?W\.?P\.?P\.?P|EROSION|SEDIMENT|COVER|"
            r"NOTES|SCHEDULES?|LEGEND|DEMOLITION|DEMO\b|REMOVALS?|"
            r"EXISTING\s+(SITE\s+)?CONDITIONS|SURVEY|STABILI[SZ]ATION|"
            r"LANDSCAP|(?:PRE|POST)-?\s*DEVELOPMENT)", re.I)
        _OVERALL = re.compile(r"\b(OVERALL|KEY\s*PLAN|INDEX)\b", re.I)
    loose_skip = re.compile(r"\b(GRADING|PAVING|STAKING|LAYOUT|SITE\s+PLAN)",
                            re.I)
    picked, others = [], []
    for r in sheets.scan(doc, pages, numbers=False):
        t = r["title"] or ""
        num = (r["number"] or "").upper()
        if num and not num.startswith("C"):
            continue          # P-201 "water piping plan" is plumbing
        if num.startswith("CD") or _NOT_PIPE_SHEET.search(t):
            continue          # CD-sheets are civil details
        if re.search(r"\b(PROFILES?|SECTIONS?)\b", t, re.I) and \
                not re.search(r"\bPLAN\b", t, re.I):
            continue          # profiles only ("plan and profile" is kept)
        if _PIPE_SHEET.search(t):
            picked.append((r["page"], t))
        elif not loose_skip.search(t):
            others.append((r["page"], t))
    if not picked and loose:
        picked = others
    # an overall plan repeats its area plans
    if any(not _OVERALL.search(t) for _p, t in picked):
        picked = [(p, t) for p, t in picked if not _OVERALL.search(t)]
    return [p for p, _t in picked]


def activities_from_takeoff(doc, job, lib=None, pages=None):
    """One activity per takeoff group not yet in the estimate, with a crew
    and a starting production rate by kind (pipe by diameter, structures,
    earthwork, grading). `pages`: only takeoff on these pages (e.g.
    civil_pages - so a building's room areas don't become grading).
    Returns the new activities."""
    from . import annotate
    have = {a.get("group") for a in job["activities"]}
    groups = {}
    for it in annotate.totals_items(doc):
        if pages is not None and it["page"] not in pages:
            continue
        g = it.get("group")
        if g and "(existing)" in g:
            continue                 # existing pipe isn't new work
        if g and g not in have:
            groups.setdefault(g, it["type"])
    crews = (lib or {}).get("crews") or {}
    out = []
    for g, kind in sorted(groups.items()):
        q, unit = takeoff_qty(doc, g)
        if kind in ("length", "polylength"):
            size = _pipe_size(g) or 8
            key = "pipe_small" if size <= 10 else "pipe_mid" \
                if size <= 18 else "pipe_large"
            unit = "LF"
        elif kind == "count":
            key = "structure" if any(w in g.lower() for w in
                                     ("manhole", "mh", "inlet", "basin",
                                      "structure", "vault")) else "count"
            unit = "EA"
        elif kind == "volume":
            key, unit = "volume", unit or "CY"
        elif kind == "area":
            key = "area"
        else:
            continue
        crew, rate = START_RATES[key]
        note = "starting production rate - check it against your history"
        band = depth_band(g) if key.startswith("pipe_") else None
        if band:
            f = depth_factors(lib)[band]
            rate = round(rate * f, 1)
            note = (f"starting production rate x {f:g} for "
                    f"{DEPTH_LABELS[band]} - check it against your history")
        if crews and crew not in crews:
            crew = ""
        out.append(add_activity(job, g, qty=q, unit=unit, crew=crew,
                                rate=rate, group=g, notes=note))
    return out


def refresh_quantities(doc, job):
    """Activities tied to a takeoff group take its current total."""
    n = 0
    for a in job["activities"]:
        if a.get("group"):
            q, u = takeoff_qty(doc, a["group"])
            if str(q) != a.get("qty"):
                a["qty"] = str(q)
                a["unit"] = a.get("unit") or u
                n += 1
    return n


def activity_cost(a, lib, job, crews=None):
    """{"hours", "days", "labor", "equipment", "material", "sub", "total",
    "unit_cost", "problem"} for one activity (Decimal)."""
    st = job.get("settings") or {}
    hpd = D(st.get("hours_per_day") or 10)
    qty, rate = D(a.get("qty")), D(a.get("rate"))
    per_hour = rate / hpd if a.get("per") == "day" and hpd else rate
    out = {"hours": Decimal(0), "days": Decimal(0), "labor": Decimal(0),
           "equipment": Decimal(0), "problem": ""}
    # a quote in use replaces the typed price, so only check what's used
    used = [q.get("kind") for q in a.get("quotes") or [] if q.get("use")]
    unreadable = _unreadable("", a, ("qty", "rate") + (
        () if "sub" in used else ("sub",)))
    for q in a.get("quotes") or []:
        if q.get("use"):
            unreadable += _unreadable(
                f"quote {q.get('vendor') or ''}".strip(), q, ("price",),
                ("price",))
    if all(k == "sub" for k in used):
        for m in a.get("materials") or []:
            unreadable += _unreadable(
                f"material {m['desc']!r}" if m.get("desc") else "material",
                dict({"qty_per": 1}, **m), ("qty_per", "cost"),
                ("qty_per", "cost"))
    if a.get("crew"):
        crew = (crews or lib["crews"]).get(a["crew"])
        if crew is None:
            out["problem"] = f"crew {a['crew']} isn't in the library"
        elif per_hour <= 0:
            out["problem"] = "no production rate"
        else:
            cr = crew_rate(crew, lib, job)
            hours = qty / per_hour
            out.update(hours=hours.quantize(Decimal("0.01")),
                       days=(hours / hpd).quantize(Decimal("0.01")),
                       labor=cents(hours * cr["labor"]),
                       equipment=cents(hours * cr["equipment"]))
            if cr["missing"]:
                out["problem"] = "not in the library: " + \
                    ", ".join(cr["missing"])
            unreadable += cr["unreadable"]
    mat = sum((qty * D(m.get("qty_per", 1)) * D(m.get("cost"))
               for m in a.get("materials") or []), Decimal(0))
    sub = D(a.get("sub"))
    # a quote marked "use" replaces the typed material or sub price
    for q in a.get("quotes") or []:
        if not q.get("use"):
            continue
        amt = quote_amount(q, qty)
        if q.get("kind") == "sub":
            sub = amt
        else:
            mat = amt
    if unreadable:                  # never a silent $0 (0.12.4 review H3)
        out["problem"] = "; ".join(filter(None, [out["problem"], "can't "
                                   "read: " + ", ".join(
                                       u.strip() for u in unreadable)]))
    out["material"] = cents(mat)
    out["sub"] = cents(sub)
    out["total"] = cents(out["labor"] + out["equipment"] + out["material"] +
                         out["sub"])
    out["unit_cost"] = cents(out["total"] / qty) if qty else Decimal(0)
    return out


# ================================================================ quotes
def quote_amount(q, qty):
    """A vendor or sub quote's price for the activity: per unit x qty, or
    lump sum."""
    p = D(q.get("price"))
    return cents(p * D(qty) if q.get("per", "unit") == "unit" else p)


def add_quote(a, vendor, price, kind="material", per="unit", notes="",
              use=None, valid_until=""):
    """Add a quote to an activity. The first quote of a kind, or the
    lowest when use is None and it's cheaper, becomes the one used."""
    if kind not in ("material", "sub") or per not in ("unit", "LS"):
        raise HeavyError("A quote is material or sub, per unit or LS.")
    q = {"id": _id(), "vendor": vendor, "kind": kind, "price": str(D(price)),
         "per": per, "notes": notes, "use": False, "at": _now(),
         "valid_until": str(valid_until or "")[:10]}
    a.setdefault("quotes", []).append(q)
    if use is None:
        pick_low(a, kind)
    elif use:
        use_quote(a, q["id"])
    return q


def use_quote(a, qid):
    """Use this quote (and no other of its kind) for the activity."""
    q = next(x for x in a.get("quotes") or [] if x["id"] == qid)
    for x in a["quotes"]:
        if x["kind"] == q["kind"]:
            x["use"] = x["id"] == qid
    return q


def pick_low(a, kind):
    qs = [q for q in a.get("quotes") or [] if q["kind"] == kind]
    if not qs:
        return None
    low = min(qs, key=lambda q: quote_amount(q, a.get("qty")))
    return use_quote(a, low["id"])


def quote_sheet(job):
    """Every activity's quotes side by side: [{"activity", "kind",
    "quotes": [{vendor, amount, use, low}], "spread"}] (spread = high -
    low, a sign of a scope gap when it's large)."""
    out = []
    for a in job["activities"]:
        for kind in ("material", "sub"):
            qs = [q for q in a.get("quotes") or [] if q["kind"] == kind]
            if not qs:
                continue
            amts = [quote_amount(q, a.get("qty")) for q in qs]
            low = min(amts)
            out.append({"activity": a["name"], "id": a["id"], "kind": kind,
                        "quotes": [dict(q, amount=m, low=m == low)
                                   for q, m in zip(qs, amts)],
                        "spread": max(amts) - low})
    return out


# ================================================================ resources
def resources(job, lib):
    """Hours and cost by labor class and by piece of equipment across the
    estimate - who and what the job needs. {"labor": {code: {"hours",
    "cost", "desc"}}, "equipment": {...}, "crew_days": {crew: days}}."""
    st = dict(lib.get("settings") or {}, **(job.get("settings") or {}))
    wages = job.get("wages") or {}
    lab, eq, crews = {}, {}, {}
    for a, c in totals(job, lib)["activities"]:
        crew = lib["crews"].get(a.get("crew") or "")
        if not crew or not c["hours"]:
            continue
        crews[a["crew"]] = crews.get(a["crew"], Decimal(0)) + c["days"]
        for code, n in crew.get("labor") or []:
            rec = lib["labor"].get(code)
            if rec is None:
                continue
            e = lab.setdefault(code, {"hours": Decimal(0),
                                      "cost": Decimal(0),
                                      "desc": rec.get("desc", "")})
            h = c["hours"] * D(n)
            e["hours"] += h
            e["cost"] += h * burden(rec, wages)["total"]
        for code, n in crew.get("equipment") or []:
            rec = lib["equipment"].get(code)
            if rec is None:
                continue
            e = eq.setdefault(code, {"hours": Decimal(0),
                                     "cost": Decimal(0),
                                     "desc": rec.get("desc", ""),
                                     "use": rec.get("use", "own")})
            h = c["hours"] * D(n)
            e["hours"] += h
            e["cost"] += h * equipment_rate(rec, st.get("fuel", 4))["total"]
    for d in (lab, eq):
        for e in d.values():
            e["hours"] = e["hours"].quantize(Decimal("0.1"))
            e["cost"] = cents(e["cost"])
    return {"labor": dict(sorted(lab.items())),
            "equipment": dict(sorted(eq.items())),
            "crew_days": {k: v.quantize(Decimal("0.1"))
                          for k, v in sorted(crews.items())}}


# ================================================================ schedule
def schedule(job, lib):
    """Work days for each activity from its crew days. An activity starts
    when the one it follows ("after", an activity id) finishes, plus its
    lag in days; otherwise on day 0. Returns {"rows": [{id, name, start,
    finish, days}], "days", "weeks", "loops": [names]}."""
    acts = {a["id"]: a for a in job["activities"]}
    cost = {a["id"]: c for a, c in totals(job, lib)["activities"]}
    done, loops = {}, []

    def finish(aid, seen=()):
        if aid in done:
            return done[aid][1]
        a = acts[aid]
        start = Decimal(0)
        after = a.get("after")
        if after in acts:
            if after in seen or after == aid:
                loops.append(a["name"])
            else:
                start = finish(after, seen + (aid,))
        start += D(a.get("lag"))
        days = D(a.get("days_override")) or cost[aid]["days"]
        done[aid] = (start, start + days)
        return start + days
    for aid in acts:
        finish(aid)
    rows = [{"id": aid, "name": acts[aid]["name"],
             "start": done[aid][0].quantize(Decimal("0.1")),
             "finish": done[aid][1].quantize(Decimal("0.1")),
             "days": (done[aid][1] - done[aid][0]).quantize(Decimal("0.1"))}
            for aid in acts]
    total = max((r["finish"] for r in rows), default=Decimal(0))
    return {"rows": rows, "days": total,
            "weeks": (total / 5).quantize(Decimal("0.1")),
            "loops": sorted(set(loops))}


def _workday(start, n):
    """The calendar date n work days (Mon-Fri) after start."""
    d, n = start, int(n)
    while d.weekday() >= 5:
        d += _dt.timedelta(days=1)
    while n > 0:
        d += _dt.timedelta(days=1)
        if d.weekday() < 5:
            n -= 1
    return d


def cashflow(job, lib, start=None):
    """Cost by month: each activity spread evenly over its work days,
    indirects evenly over the job, markup and bond in proportion.
    [{"month": "2026-11", "direct", "indirect", "total", "cumulative"}]"""
    start = start or _dt.date.fromisoformat(
        (job.get("settings") or {}).get("start") or
        _dt.date.today().isoformat())
    t = totals(job, lib)
    sch = schedule(job, lib)
    cost = {a["id"]: c["total"] for a, c in t["activities"]}
    months = {}

    def add(day, key, amt):
        m = _workday(start, day).strftime("%Y-%m")
        e = months.setdefault(m, {"direct": Decimal(0),
                                  "indirect": Decimal(0)})
        e[key] += amt
    for r in sch["rows"]:
        n = max(1, int(math.ceil(r["days"])))
        for i in range(n):
            add(int(r["start"]) + i, "direct", cost[r["id"]] / n)
    span = max(1, int(math.ceil(sch["days"])))
    extra = t["total"] - t["direct"]
    for i in range(span):
        add(i, "indirect", extra / span)
    out, run = [], Decimal(0)
    for m in sorted(months):
        e = months[m]
        tot = cents(e["direct"] + e["indirect"])
        run += tot
        out.append({"month": m, "direct": cents(e["direct"]),
                    "indirect": cents(e["indirect"]), "total": tot,
                    "cumulative": run})
    if out:                      # keep the pennies honest
        diff = t["total"] - run
        out[-1]["total"] += diff
        out[-1]["cumulative"] += diff
    return out


def export_rows(path, sheet, rows):
    """A small table to Excel (.xlsx) or CSV."""
    from . import safeio
    if str(path).lower().endswith(".xlsx"):
        import tempfile
        from . import acrobat
        fd, tmp = tempfile.mkstemp(suffix=".xlsx")
        os.close(fd)
        acrobat.write_xlsx(tmp, [(sheet, rows)])
        with open(tmp, "rb") as f:
            safeio.atomic_write(path, f.read())
        os.remove(tmp)
    else:
        import io
        buf = io.StringIO()
        from . import safecell
        safecell.writer(buf).writerows(rows)     # text never a formula
        safeio.atomic_write(path, buf.getvalue())
    return path


def export_resources(job, lib, path):
    r = resources(job, lib)
    rows = [["Labor class", "Description", "Hours", "Cost"]]
    rows += [[k, v["desc"], float(v["hours"]), float(v["cost"])]
             for k, v in r["labor"].items()]
    rows += [[], ["Equipment", "Description", "Hours", "Cost"]]
    rows += [[k, v["desc"], float(v["hours"]), float(v["cost"])]
             for k, v in r["equipment"].items()]
    rows += [[], ["Crew", "Crew days"]]
    rows += [[k, float(v)] for k, v in r["crew_days"].items()]
    return export_rows(path, "Resources", rows)


def export_cashflow(job, lib, path, start=None):
    rows = [["Month", "Direct", "Indirect, markup, bond", "Total",
             "Cumulative"]]
    rows += [[m["month"], float(m["direct"]), float(m["indirect"]),
              float(m["total"]), float(m["cumulative"])]
             for m in cashflow(job, lib, start)]
    return export_rows(path, "Cash Flow", rows)


def indirect_cost(it, job):
    """Rate x how many (weeks/months/days of the job, or the item's own)."""
    st = job.get("settings") or {}
    weeks = D(it.get("duration")) if it.get("duration") not in (None, "") \
        else D(st.get("duration_weeks"))
    per = it.get("per", "LS")
    n = {"week": weeks, "month": weeks * 12 / 52,
         "day": weeks * 5, "LS": Decimal(1)}.get(per, Decimal(1))
    return cents(D(it.get("rate")) * n * D(it.get("qty") or 1))


def totals(job, lib):
    """The estimate: {"activities": [(activity, cost)], "direct",
    "indirect", "markup", "bond", "total", "problems"}."""
    rows, problems = [], []
    direct = Decimal(0)
    for a in job["activities"]:
        c = activity_cost(a, lib, job)
        rows.append((a, c))
        direct += c["total"]
        if c["problem"]:
            problems.append(f"{a['name']}: {c['problem']}")
    indirect = sum((indirect_cost(i, job) for i in job["indirects"]),
                   Decimal(0))
    st = job.get("settings") or {}
    markup = cents((direct + indirect) * D(st.get("markup_pct")) / HUNDRED)
    bond = cents((direct + indirect + markup) * D(st.get("bond_pct")) /
                 HUNDRED)
    return {"activities": rows, "direct": cents(direct),
            "indirect": cents(indirect), "markup": markup, "bond": bond,
            "total": cents(direct + indirect + markup + bond),
            "problems": problems}


def by_tag(job, lib):
    """{tag: total} - the estimate sliced by your own tags (phase, area,
    estimator...)."""
    out = {}
    for a, c in totals(job, lib)["activities"]:
        for t in a.get("tags") or ["(untagged)"]:
            out[t] = out.get(t, Decimal(0)) + c["total"]
    return dict(sorted(out.items()))


# ================================================================ pay items
def read_pay_items(path):
    """The owner's bid schedule from CSV or Excel: item no., description,
    unit, quantity."""
    rows = []
    if str(path).lower().endswith((".xlsx", ".xlsm")):
        import openpyxl
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        rows = [[("" if c is None else str(c)) for c in r]
                for r in wb.worksheets[0].iter_rows(values_only=True)]
    else:
        from .textio import open_csv          # Excel's Windows-1252 too
        with open_csv(path) as f:
            rows = list(csv.reader(f))

    def pick(head, *names):
        # exact header first, then "starts with", then "contains"
        for test in (lambda h, n: h == n, lambda h, n: h.startswith(n),
                     lambda h, n: n in h):
            for n in names:
                for i, h in enumerate(head):
                    if h and test(h, n):
                        return i
        return None
    for hi, head in enumerate(rows[:15]):
        h = [str(x).strip().lower() for x in head]
        no = pick(h, "item no", "item", "pay item", "line", "no")
        de = pick(h, "description", "desc")
        un = pick(h, "unit", "uom", "units")
        qt = pick(h, "quantity", "qty", "est. qty", "estimated quantity")
        if de is not None and qt is not None:
            out = []
            for r in rows[hi + 1:]:
                if len(r) <= max(de, qt) or not str(r[de]).strip():
                    continue
                out.append({"no": str(r[no]).strip() if no is not None and
                            no < len(r) else str(len(out) + 1),
                            "desc": str(r[de]).strip(),
                            "unit": str(r[un]).strip() if un is not None
                            and un < len(r) else "",
                            "owner_qty": str(D(r[qt])), "weight": "1"})
            return out
    raise HeavyError("No description and quantity columns found.")


def spread(job, lib):
    """Pay item prices: each item's direct cost (its activities), plus
    indirects, markup and bond shared in proportion to direct cost x the
    item's weight (1 = even; above 1 front-loads it). Unit prices are
    rounded to cents; the rounding left over is reported.
    Returns {"items": [...], "unassigned": [activities], "total",
    "rounding"}."""
    t = totals(job, lib)
    by_item = {}
    unassigned = []
    for a, c in t["activities"]:
        if a.get("pay_item"):
            by_item.setdefault(a["pay_item"], []).append((a, c))
        else:
            unassigned.append(a)
    extra = t["total"] - t["direct"]
    items = job["pay_items"]
    weights = {}
    for p in items:
        direct = sum((c["total"] for _a, c in by_item.get(p["no"], [])),
                     Decimal(0))
        weights[p["no"]] = direct * D(p.get("weight") or 1)
    wsum = sum(weights.values(), Decimal(0))
    note = ""
    if not wsum and items and extra:
        # no direct cost on any pay item yet: share indirects, markup and
        # bond by weight alone so they stay in the bid instead of vanishing
        weights = {p["no"]: D(p.get("weight") or 1) for p in items}
        wsum = sum(weights.values(), Decimal(0))
        note = ("No activities are on pay items yet, so indirects, markup "
                "and bond were shared evenly across the pay items.")
    out = []
    amount_sum = Decimal(0)
    for p in items:
        acts = by_item.get(p["no"], [])
        direct = sum((c["total"] for _a, c in acts), Decimal(0))
        share = extra * weights[p["no"]] / wsum if wsum else Decimal(0)
        qty = D(p.get("owner_qty"))
        unit_price = cents((direct + share) / qty) if qty else Decimal(0)
        amount = cents(unit_price * qty)
        amount_sum += amount
        out.append({"no": p["no"], "desc": p.get("desc", ""),
                    "unit": p.get("unit", ""), "owner_qty": qty,
                    "direct": cents(direct), "share": cents(share),
                    "unit_price": unit_price, "amount": amount,
                    "unit_cost": cents(direct / qty) if qty else
                    Decimal(0)})
    unassigned_cost = sum((c["total"] for a, c in t["activities"]
                           if not a.get("pay_item")), Decimal(0))
    return {"items": out, "unassigned": unassigned,
            "unassigned_cost": cents(unassigned_cost),
            "total": t["total"], "bid": cents(amount_sum),
            "rounding": cents(t["total"] - unassigned_cost - amount_sum),
            "note": note}


def quantity_check(job, flag_pct=QTY_FLAG_PCT):
    """Owner's quantity vs yours (the activities on each pay item, in its
    unit). [{"no", "desc", "unit", "owner_qty", "your_qty", "diff_pct",
    "flag"}]"""
    out = []
    for p in job["pay_items"]:
        mine = [a for a in job["activities"] if a.get("pay_item") == p["no"]
                and (not p.get("unit") or not a.get("unit") or
                     a["unit"].strip().upper() == p["unit"].strip().upper())]
        # the activities on a pay item usually share its quantity
        # (excavate, lay, backfill the same LF), so the largest is "yours"
        yours = max((D(a.get("qty")) for a in mine), default=None)
        owner = D(p.get("owner_qty"))
        pct = ((yours - owner) / owner * 100).quantize(Decimal("0.1")) \
            if yours is not None and owner else None
        out.append({"no": p["no"], "desc": p.get("desc", ""),
                    "unit": p.get("unit", ""), "owner_qty": owner,
                    "your_qty": yours, "diff_pct": pct,
                    "flag": pct is not None and abs(pct) > flag_pct})
    return out


def export_schedule(job, lib, path):
    """The priced bid schedule as Excel (.xlsx) or CSV."""
    from . import safeio
    s = spread(job, lib)
    rows = [["Item", "Description", "Unit", "Quantity", "Unit price",
             "Amount"]]
    rows += [[i["no"], i["desc"], i["unit"], float(i["owner_qty"]),
              float(i["unit_price"]), float(i["amount"])]
             for i in s["items"]]
    rows += [[], ["", "Total bid", "", "", "", float(s["bid"])]]
    if str(path).lower().endswith(".xlsx"):
        import tempfile
        from . import acrobat
        fd, tmp = tempfile.mkstemp(suffix=".xlsx")
        os.close(fd)
        acrobat.write_xlsx(tmp, [("Bid Schedule", rows)])
        with open(tmp, "rb") as f:
            safeio.atomic_write(path, f.read())
        os.remove(tmp)
    else:
        import io
        buf = io.StringIO()
        from . import safecell
        safecell.writer(buf).writerows(rows)     # text never a formula
        safeio.atomic_write(path, buf.getvalue())
    return path


# ================================================================ hauling
def haul(h):
    """Truck haul: cycle time, trucks to keep the loader busy, hours and
    cost per bank cubic yard. Inputs (h): cy_bank, swell_pct, truck_cy
    (loose), miles, mph_loaded, mph_empty, load_min, dump_min, truck_hr,
    loader_cyhr (loose), loader_hr, trucks (blank = enough)."""
    bank = D(h.get("cy_bank"))
    loose = bank * (1 + D(h.get("swell_pct", 25)) / HUNDRED)
    miles = D(h.get("miles"))
    cyc = D(h.get("load_min", 4)) + D(h.get("dump_min", 2))
    for k in ("mph_loaded", "mph_empty"):
        v = D(h.get(k, 25))
        if v > 0:
            cyc += miles / v * 60
    cyc = cyc.quantize(Decimal("0.1"))
    truck_cy = D(h.get("truck_cy", 14))
    per_truck = (Decimal(60) / cyc * truck_cy) if cyc else Decimal(0)
    loader = D(h.get("loader_cyhr", 250))
    need = int(math.ceil(loader / per_truck)) if per_truck else 0
    trucks = int(D(h.get("trucks"))) or need      # 0 or blank = enough
    rate = min(loader, trucks * per_truck) if trucks else Decimal(0)
    hours = (loose / rate) if rate else Decimal(0)
    cost = hours * (trucks * D(h.get("truck_hr", 95)) +
                    D(h.get("loader_hr", 150)))
    return {"loose_cy": loose.quantize(Decimal("0.1")), "cycle_min": cyc,
            "truck_cyhr": per_truck.quantize(Decimal("0.1")),
            "trucks_needed": need, "trucks": trucks,
            "hours": hours.quantize(Decimal("0.1")), "cost": cents(cost),
            "per_bank_cy": cents(cost / bank) if bank else Decimal(0)}


# ================================================================ versions
def save_version(job, name, lib, by=None):
    snap = {k: copy.deepcopy(job[k]) for k in
            ("activities", "pay_items", "indirects", "settings", "wages")}
    v = {"id": _id(), "name": name or f"Version {len(job['versions']) + 1}",
         "at": _now(), "by": _who(by),
         "total": str(totals(job, lib)["total"]), "snapshot": snap}
    job["versions"].append(v)
    return v


def _as_job(v):
    return dict(blank(), **copy.deepcopy(v["snapshot"]))


def compare_versions(job, a_id, b_id, lib):
    """Rows by activity: [{"name", "a", "b", "diff"}] plus the totals."""
    va = next(v for v in job["versions"] if v["id"] == a_id)
    vb = next(v for v in job["versions"] if v["id"] == b_id)
    ta, tb = totals(_as_job(va), lib), totals(_as_job(vb), lib)
    ca = {a["name"]: c["total"] for a, c in ta["activities"]}
    cb = {a["name"]: c["total"] for a, c in tb["activities"]}
    rows = []
    for n in sorted(set(ca) | set(cb)):
        x, y = ca.get(n, Decimal(0)), cb.get(n, Decimal(0))
        if x != y:
            rows.append({"name": n, "a": x, "b": y, "diff": y - x})
    for k in ("indirect", "markup", "bond"):
        if ta[k] != tb[k]:
            rows.append({"name": f"({k})", "a": ta[k], "b": tb[k],
                         "diff": tb[k] - ta[k]})
    return {"rows": rows, "a": ta["total"], "b": tb["total"],
            "diff": tb["total"] - ta["total"]}


def restore_version(job, v_id):
    v = next(v for v in job["versions"] if v["id"] == v_id)
    for k, val in copy.deepcopy(v["snapshot"]).items():
        job[k] = val
    return job


# ================================================================ wages
def read_wages_csv(path, lib):
    """A prevailing wage determination (Davis-Bacon) saved as CSV:
    classification, rate, fringe. Matched to your labor classes by code or
    description. Returns ({class code: {base, fringe, source}},
    [unmatched classifications])."""
    from .textio import open_csv
    with open_csv(path) as f:          # Excel's Windows-1252 CSVs too
        rows = list(csv.reader(f))
    out, left = {}, []
    names = {(r.get("desc") or "").strip().lower(): c
             for c, r in lib["labor"].items()}
    codes = {c.lower(): c for c in lib["labor"]}
    for r in rows:
        if len(r) < 2 or not r[0].strip():
            continue
        if D(r[1]) == 0:
            continue                       # header or blank
        key = r[0].strip().lower()
        code = codes.get(key) or names.get(key) or next(
            (c for n, c in names.items() if n and (n in key or key in n)),
            None)
        if code is None:
            left.append(r[0].strip())
            continue
        out[code] = {"base": str(D(r[1])),
                     "fringe": str(D(r[2])) if len(r) > 2 else "0",
                     "source": os.path.basename(path)}
    return out, left


# ================================================================ field
def timecard_hours(card):
    """{cost code: {"qty", "unit", "crew_hours"}} from a time card's
    production lines."""
    out = {}
    for p in card.get("production") or []:
        code = str(p.get("cost_code") or "").strip()
        if not code:
            continue
        e = out.setdefault(code, {"qty": Decimal(0), "unit":
                                  p.get("unit", ""),
                                  "crew_hours": Decimal(0)})
        e["qty"] += D(p.get("qty"))
        e["crew_hours"] += D(p.get("hours"))
    return out


def timecard_costs(card, lib, job=None):
    """What a day cost by cost code: crew labor and equipment hours at
    library rates, split over the cost codes in proportion to the hours
    worked on each. {code: Decimal}."""
    job = job or {}
    st = dict(lib.get("settings") or {}, **(job.get("settings") or {}))
    labor = Decimal(0)
    for m in card.get("crew") or []:
        rec = lib["labor"].get(m.get("class"))
        if rec:
            labor += burden(rec, job.get("wages"))["total"] * D(m.get("hours"))
    equip = Decimal(0)
    for e in card.get("equipment") or []:
        rec = lib["equipment"].get(e.get("code"))
        if rec:
            equip += equipment_rate(rec, st.get("fuel", 4))["total"] * \
                D(e.get("hours"))
    hrs = timecard_hours(card)
    tot = sum((v["crew_hours"] for v in hrs.values()), Decimal(0))
    out = {}
    for code, v in hrs.items():
        share = v["crew_hours"] / tot if tot else Decimal(1) / len(hrs)
        out[code] = cents((labor + equip) * share)
    return out


# ================================================================ library
def save_to_library(a, code=None, lib=None, note=""):
    """Keep an activity (crew, production, materials) to reuse in other
    bids. `code` is the library key (default: its cost code, else its
    name). Returns the key."""
    key = str(code or a.get("code") or a.get("name") or "").strip()
    if not key:
        raise HeavyError("Give the activity a name or cost code first.")
    rec = {k: copy.deepcopy(a.get(k)) for k in TEMPLATE_KEYS
           if a.get(k) not in (None, "")}
    # "code" is the library key; the activity's own cost code is kept
    rec.update(cost_code=a.get("code", ""), code=key, saved=_now(),
               by=_who())
    if lib:          # remember the crew's make-up, in case it's changed
        crew = lib["crews"].get(a.get("crew") or "")
        if crew:
            rec["crew_def"] = copy.deepcopy(crew)
    save_items("activities", [rec], note=note or "saved from an estimate")
    return key


def add_from_library(job, key, lib, qty=0, group="", pay_item=""):
    """A new activity in the job from a saved one."""
    rec = (lib.get("activities") or {}).get(key)
    if rec is None:
        raise HeavyError(f"{key} isn't in the activity library.")
    if rec.get("crew") and rec["crew"] not in lib["crews"] and \
            rec.get("crew_def"):
        save_items("crews", [dict(rec["crew_def"], code=rec["crew"])],
                   note=f"from library activity {key}")
        lib["crews"][rec["crew"]] = rec["crew_def"]
    a = add_activity(job, rec.get("name") or key, qty=qty,
                     unit=rec.get("unit", ""), crew=rec.get("crew", ""),
                     rate=rec.get("rate", 0), per=rec.get("per", "hour"),
                     code=rec.get("cost_code", ""),
                     pay_item=pay_item, tags=rec.get("tags") or (),
                     materials=rec.get("materials") or (),
                     sub=rec.get("sub", 0), group=group,
                     notes=rec.get("notes", ""))
    a["from_library"] = key
    return a


def search_library(lib, text=""):
    """Saved activities whose key, name, cost code or tags match `text`
    (all words), sorted by name: [(key, rec)]."""
    words = [w.lower() for w in str(text or "").split()]
    out = []
    for key, rec in (lib.get("activities") or {}).items():
        hay = " ".join(str(x) for x in (key, rec.get("name"),
                                        rec.get("cost_code"),
                                        " ".join(rec.get("tags") or []),
                                        rec.get("unit"))).lower()
        if all(w in hay for w in words):
            out.append((key, rec))
    return sorted(out, key=lambda kv: (kv[1].get("name") or kv[0]).lower())


def save_master(job, name, note=""):
    """Keep a whole estimate - activities (without quantities), indirects
    and settings - as a master to start new bids from."""
    name = str(name or "").strip()
    if not name:
        raise HeavyError("Name the master estimate.")
    acts = []
    for a in job["activities"]:
        t = {k: copy.deepcopy(a.get(k)) for k in TEMPLATE_KEYS
             if a.get(k) not in (None, "")}
        t["group"] = a.get("group", "")
        acts.append(t)
    rec = {"code": name, "activities": acts,
           "indirects": copy.deepcopy(job["indirects"]),
           "settings": {k: v for k, v in job["settings"].items()
                        if k not in ("start", "project_folder")},
           "saved": _now(), "by": _who()}
    save_items("masters", [rec], note=note or "master estimate")
    return name


def new_from_master(name, lib, doc=None):
    """A new estimate from a master: its activities (quantities picked up
    from takeoff groups of the same name when `doc` is given), indirects
    and settings."""
    rec = (lib.get("masters") or {}).get(name)
    if rec is None:
        raise HeavyError(f"No master estimate named {name}.")
    job = blank()
    job["settings"].update(copy.deepcopy(rec.get("settings") or {}))
    job["indirects"] = copy.deepcopy(rec.get("indirects") or [])
    for t in rec.get("activities") or []:
        qty, unit = Decimal(0), t.get("unit", "")
        if doc is not None and t.get("group"):
            q, u = takeoff_qty(doc, t["group"])
            if q:
                qty, unit = q, unit or u
        a = add_activity(job, t.get("name") or "activity", qty=qty,
                         unit=unit, crew=t.get("crew", ""),
                         rate=t.get("rate", 0), per=t.get("per", "hour"),
                         code=t.get("code", ""), tags=t.get("tags") or (),
                         materials=t.get("materials") or (),
                         sub=t.get("sub", 0), group=t.get("group", ""),
                         notes=t.get("notes", ""))
        a["from_master"] = name
    job["master"] = name
    return job


# ================================================================ forecast
FORECAST_FLAG_PCT = Decimal(5)


def card_hours(store, statuses=("Submitted", "Approved")):
    """Crew hours and quantity installed by cost code from the project's
    time cards: {code: {"hours", "qty", "unit"}}."""
    from .pm import cost as pmcost
    out = {}
    for card in store.list("timecard"):
        if card.get("status") not in statuses:
            continue
        for code, v in timecard_hours(card).items():
            k = pmcost.code_key(code)
            e = out.setdefault(k, {"hours": Decimal(0), "qty": Decimal(0),
                                   "unit": v["unit"]})
            e["hours"] += v["crew_hours"]
            e["qty"] += v["qty"]
    return out


def forecast(job, lib, store, flag_pct=FORECAST_FLAG_PCT):
    """Cost to complete by cost code while the job runs: the estimate's
    budget (cost, quantity, crew hours) against what the time cards and
    direct costs say so far.

    Per code: pct complete = installed / budget quantity; earned hours =
    budget hours x pct; productivity = earned / actual hours (above 1 is
    ahead); projected final = cost so far / pct (the budget when nothing
    is installed yet); variance = projected - budget; "flag" when it runs
    over by more than flag_pct %. Returns {"rows", "budget", "spent",
    "projected", "variance"} (Decimal)."""
    from .pm import cost as pmcost
    from .pricehistory import actuals_from_store
    budget = {}
    for a, c in totals(job, lib)["activities"]:
        k = pmcost.code_key(a.get("code") or a.get("name"))
        e = budget.setdefault(k, {"code": k, "desc": a.get("name", ""),
                                  "unit": a.get("unit", ""),
                                  "cost": Decimal(0), "qty": Decimal(0),
                                  "hours": Decimal(0)})
        e["cost"] += c["total"]
        e["qty"] += D(a.get("qty"))
        e["hours"] += c["hours"]
    acts = {r["code"]: r for r in merge_actuals(
        actuals_from_store(store), store_actuals(store, lib))}
    hrs = card_hours(store)
    rows = []
    q2 = Decimal("0.01")
    for k in sorted(set(budget) | set(acts)):
        b = budget.get(k, {"code": k, "desc": "", "unit": "",
                           "cost": Decimal(0), "qty": Decimal(0),
                           "hours": Decimal(0)})
        a = acts.get(k, {})
        spent = cents(D(a.get("cost")))
        qty = D(a.get("qty")) if a.get("qty") not in (None, "") else \
            hrs.get(k, {}).get("qty", Decimal(0))
        ah = hrs.get(k, {}).get("hours", Decimal(0))
        pct = (qty / b["qty"]) if b["qty"] else None
        if pct is not None and pct > 0:
            projected = cents(spent / pct)
        elif spent and not b["cost"]:
            projected = spent            # not in the estimate at all
        else:
            projected = max(cents(b["cost"]), spent)
        earned = (b["hours"] * pct).quantize(q2) if pct is not None \
            else None
        prod = (earned / ah).quantize(q2) if earned is not None and ah \
            else None
        var = projected - cents(b["cost"])
        flag = bool(b["cost"]) and var > cents(b["cost"]) * flag_pct / \
            HUNDRED or (not b["cost"] and spent > 0)
        rows.append({"code": k, "desc": b["desc"] or a.get("desc", ""),
                     "unit": b["unit"] or a.get("unit", ""),
                     "budget": cents(b["cost"]), "budget_qty": b["qty"],
                     "budget_hours": b["hours"].quantize(q2),
                     "qty": qty, "hours": ah, "spent": spent,
                     "pct": None if pct is None else
                     (pct * 100).quantize(Decimal("0.1")),
                     "earned_hours": earned, "productivity": prod,
                     "unit_cost": cents(spent / qty) if qty else None,
                     "projected": projected, "variance": var,
                     "flag": flag})
    tb = sum((r["budget"] for r in rows), Decimal(0))
    ts = sum((r["spent"] for r in rows), Decimal(0))
    tp = sum((r["projected"] for r in rows), Decimal(0))
    return {"rows": rows, "budget": tb, "spent": ts, "projected": tp,
            "variance": tp - tb}


def export_forecast(job, lib, store, path):
    f = forecast(job, lib, store)
    head = ["Cost code", "Description", "Unit", "Budget", "Budget qty",
            "Installed", "% complete", "Budget hours", "Actual hours",
            "Earned hours", "Productivity", "Spent", "Projected final",
            "Over (under)"]
    rows = [head]

    def n(v):
        return "" if v is None else float(v)
    for r in f["rows"]:
        rows.append([r["code"], r["desc"], r["unit"], n(r["budget"]),
                     n(r["budget_qty"]), n(r["qty"]), n(r["pct"]),
                     n(r["budget_hours"]), n(r["hours"]),
                     n(r["earned_hours"]), n(r["productivity"]),
                     n(r["spent"]), n(r["projected"]), n(r["variance"])])
    rows += [[], ["", "Total", "", float(f["budget"])] + [""] * 7 +
             [float(f["spent"]), float(f["projected"]),
              float(f["variance"])]]
    return export_rows(path, "Cost to Complete", rows)


def store_actuals(store, lib):
    """Actual cost and quantity installed by cost code from a project's
    approved (or submitted) time cards - for Job Cost Feedback."""
    by = {}
    for card in store.list("timecard"):
        if card.get("status") not in ("Submitted", "Approved"):
            continue
        costs = timecard_costs(card, lib)
        for code, v in timecard_hours(card).items():
            e = by.setdefault(code, {"code": code, "cost": Decimal(0),
                                     "qty": Decimal(0), "unit": v["unit"],
                                     "desc": "time cards"})
            e["cost"] += costs.get(code, Decimal(0))
            e["qty"] += v["qty"]
    return list(by.values())


def merge_actuals(costs, cards):
    """Direct-cost actuals plus time-card actuals, by cost code: costs add
    up; the quantity comes from the cost records when they have one (so
    nothing is counted twice), otherwise from the time cards."""
    from .pm import cost as pmcost
    by = {}
    for r in costs:
        by[r["code"]] = dict(r)
    for r in cards:
        k = pmcost.code_key(r["code"])
        e = by.get(k)
        if e is None:
            by[k] = dict(r, code=k)
            continue
        e["cost"] = D(e.get("cost")) + D(r.get("cost"))
        if e.get("qty") in (None, "") or not D(e.get("qty")):
            e["qty"] = D(r.get("qty"))
            e["unit"] = e.get("unit") or r.get("unit", "")
    return list(by.values())


def record_production(store, job_label="", region=""):
    """Approved time cards' production -> production history (units per
    crew hour by cost code). Each card is recorded once. Returns how many
    rows were added."""
    from . import pricedb
    n = 0
    with pricedb.connect(write=True) as con:
        done = {r[0] for r in con.execute(
            "SELECT source FROM production_obs WHERE source LIKE 'card %'")}
        for card in store.list("timecard"):
            if card.get("status") != "Approved":
                continue
            src = f"card {store.name}/{card.get('_id')}"
            if src in done:
                continue
            for code, v in timecard_hours(card).items():
                if v["crew_hours"] <= 0 or v["qty"] <= 0:
                    continue
                con.execute(
                    "INSERT INTO production_obs (code, unit, qty, "
                    "crew_hours, rate, job, date, conditions, source, "
                    "added_by) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (code, v["unit"], str(v["qty"]), str(v["crew_hours"]),
                     str((v["qty"] / v["crew_hours"]).quantize(
                         Decimal("0.0001"))), job_label or store.name,
                     card.get("date") or "", region, src, pricedb.user()))
                n += 1
    return n


def suggest_rate(code, n=10, today=None):
    """Your production rate for a cost code from field history: a
    weighted median (more crew hours and newer days count more) of units
    per crew hour. {"rate", "min", "max", "count", "unit"} or None."""
    from . import pricedb
    from .pricehistory import _months, weighted_median, HALF_LIFE_MONTHS
    today = today or _dt.date.today()
    with pricedb.connect() as con:
        rows = [dict(r) for r in con.execute(
            "SELECT * FROM production_obs WHERE code=? ORDER BY date DESC, "
            "id DESC", (code,))][:n]
    if not rows:
        return None
    vals, wts = [], []
    for r in rows:
        m = _months(r["date"], today)
        vals.append(D(r["rate"]))
        wts.append(D(r["crew_hours"]).sqrt() *
                   Decimal(str(0.5 ** (m / HALF_LIFE_MONTHS))))
    rate = weighted_median(vals, wts)
    q = Decimal("0.01")
    return {"code": code, "rate": rate.quantize(q, ROUND_HALF_UP),
            "min": min(vals).quantize(q), "max": max(vals).quantize(q),
            "count": len(rows), "unit": rows[0]["unit"]}
