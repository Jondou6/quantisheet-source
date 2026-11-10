"""Cost books: prices as plain text files (JSON) you can share, compare
and keep in version control, with an effective date, regional cost
indexes and yearly escalation.

An assembly part with a cost code (e.g. "09 21 16.13") takes its unit
cost, labor hours and crew from the job's cost book, escalated from the
book's effective date to the job's pricing date and multiplied by the
region's index. Switching books shows the change before it's applied.
(Built on the Venice AI draft.)

    {"name": "House 2026", "effective": "2026-01-01", "region": "national",
     "escalation": 0.04, "index": {"national": 1.0, "Boston": 1.21},
     "items": {"09 21 16.13": {"desc": "5/8 Type X gyp board", "unit": "sf",
               "material": 0.62, "labor": 0.017, "crew": "D-2"}}}

A book can also carry labor rates for each region ("rates": {region:
{trade: $/hr}}, burdened); a job priced from the book in that region
costs its crews at those rates (the job's own rates still win). Items may
say where their price came from ("source") and how firm it is ("basis":
researched, estimate, allowance...).

Equipment $ per unit is its own column ("equipment"; books saved before it
existed read as 0 with material unchanged). An imported price list's items
also say which edition they came from and when they were imported, and a
book imported from a licensed price list is local-only (see pricedb and
priceimport). The Location Factors table (locfactors.py) adjusts a job's
material / labor / equipment by region: location_adjustment() below.
"""
import csv
import datetime as _dt
import json
import logging
import os
import re
from decimal import Decimal

from . import csi, settings
from .dmoney import c2 as _c2

log = logging.getLogger(__name__)

DEFAULT_INDEX = {"national": 1.0}
# text an item can carry besides its prices
TAGS = ("source", "basis", "type", "edition", "imported", "license")
HOURS_PER_DAY = 8.0


def book_dir():
    path = os.path.join(settings.DIR, "costbooks")
    os.makedirs(path, exist_ok=True)
    return path


US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut",
    "DE": "Delaware", "DC": "District of Columbia", "FL": "Florida",
    "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois",
    "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky",
    "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana",
    "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire",
    "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio",
    "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania",
    "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont",
    "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
    "WI": "Wisconsin", "WY": "Wyoming", "PR": "Puerto Rico"}


class Book:
    def __init__(self, data=None, path=None):
        data = dict(data or {})
        self.name = str(data.get("name") or "Cost Book")
        self.effective = str(data.get("effective") or
                             _dt.date.today().isoformat())
        self.region = str(data.get("region") or "national")
        try:
            self.escalation = float(data.get("escalation", 0.0))
        except (TypeError, ValueError):
            self.escalation = 0.0
        self.index = dict(DEFAULT_INDEX, **(data.get("index") or {}))
        self.rates = {str(r): {str(t): float(v) for t, v in (tr or {}).items()
                               if _isnum(v)}
                      for r, tr in (data.get("rates") or {}).items()
                      if isinstance(tr, dict)}
        self.regions = dict(data.get("regions") or {})
        self.notes = str(data.get("notes") or "")
        self.version = str(data.get("version") or "")
        # yearly escalation by CSI division (e.g. from BLS PPI), used for
        # items whose code names a division; the book's rate for the rest
        self.escalation_by_div = {
            str(k).zfill(2): float(v)
            for k, v in (data.get("escalation_by_div") or {}).items()
            if _isnum(v)}
        self.escalation_source = str(data.get("escalation_source") or "")
        # imported from a licensed price list: this PC's database only
        self.local_only = bool(data.get("local_only"))
        self.license_note = str(data.get("license_note") or "")
        self.items = {}
        for code, e in (data.get("items") or {}).items():
            if isinstance(e, dict):
                key = csi.parse_code(code) or str(code).strip()
                self.items[key] = {
                    "desc": str(e.get("desc", "")), "unit": str(e.get("unit",
                                                                       "")),
                    "material": _num(e.get("material")),
                    "labor": _num(e.get("labor", e.get("labour_hours"))),
                    "crew": str(e.get("crew") or ""),
                    "sub": _num(e.get("sub"))}
                if _num(e.get("equipment")):
                    self.items[key]["equipment"] = _num(e.get("equipment"))
                for k in TAGS:
                    if e.get(k):
                        self.items[key][k] = str(e[k])
                sz = _sizes(e.get("sizes"))
                if sz:
                    self.items[key]["sizes"] = sz
        self.path = path

    def to_dict(self):
        d = {"name": self.name, "effective": self.effective,
             "region": self.region, "escalation": self.escalation,
             "index": self.index, "items": self.items}
        if self.rates:
            d["rates"] = self.rates
        if self.regions:
            d["regions"] = self.regions
        if self.notes:
            d["notes"] = self.notes
        if self.version:
            d["version"] = self.version
        if self.escalation_by_div:
            d["escalation_by_div"] = self.escalation_by_div
        if self.escalation_source:
            d["escalation_source"] = self.escalation_source
        if self.local_only:
            d["local_only"] = True
        if self.license_note:
            d["license_note"] = self.license_note
        return d

    def region_names(self):
        """Every region the book prices, national first."""
        names = list(self.index)
        names += [r for r in self.rates if r not in names]
        return sorted(names, key=lambda r: (r != "national", r.lower()))

    def resolve_region(self, region):
        """The book's own name for `region`: exact, any case, or a 2-letter
        state code ("SC" -> "South Carolina"). None if the book has no such
        region; the book's default region for an empty one."""
        if not region:
            return self.region
        names = self.region_names()
        r = str(region).strip()
        for n in names:
            if n.lower() == r.lower():
                return n
        full = US_STATES.get(r.upper())
        if full:
            for n in names:
                if n.lower() == full.lower():
                    return n
        # "Charleston, SC" / "South Carolina - Coastal"
        for n in names:
            if n.lower() != "national" and n.lower() in r.lower():
                return n
        # a ZIP, city or region from your Location Factors table: that
        # region if the book prices it, else its state
        try:
            from . import locfactors
            row = locfactors.find_region(r)
        except Exception:
            log.debug("location lookup failed", exc_info=True)
            row = None
        if row:
            for cand in (row["region"], US_STATES.get(row.get("state", ""))):
                for n in names:
                    if cand and n.lower() == str(cand).lower():
                        return n
        return None

    def _reg(self, region):
        r = self.resolve_region(region)
        if r is None:
            log.warning("cost book %r has no region %r; using %r", self.name,
                        region, self.region)
            return self.region
        return r

    def labor_rates(self, region=None, as_of=None):
        """{trade: $/hr} for the region, escalated like the prices (the
        book's national rates fill in any trade the region lacks)."""
        reg = self._reg(region)
        table = dict(self.rates.get("national") or {})
        table.update(self.rates.get(reg) or {})
        if not table:
            return {}
        esc = self.factor("national", as_of) / float(
            self.index.get("national", 1.0) or 1.0)
        return {t: _c2(v * esc) for t, v in table.items()}

    def factor(self, region=None, as_of=None, code=None):
        """Region index x escalation from the book's date to `as_of` (at
        the item's division rate when the book has one for it)."""
        f = float(self.index.get(self._reg(region), 1.0))
        rate = self.escalation
        div = division_of(code) if code and self.escalation_by_div else ""
        if div in self.escalation_by_div:
            rate = self.escalation_by_div[div]
        try:
            start = _dt.date.fromisoformat(self.effective)
            when = _dt.date.fromisoformat(as_of) if as_of else \
                _dt.date.today()
            years = max(0.0, (when - start).days / 365.25)
        except (TypeError, ValueError):
            years = 0.0
        return f * (1.0 + rate) ** years

    def get(self, code):
        if not code:
            return None
        return self.items.get(csi.parse_code(code) or str(code).strip())

    def set(self, code, unit, material=0.0, labor=0.0, crew="", desc="",
            sub=0.0, equipment=0.0, **extra):
        key = csi.parse_code(code) or str(code).strip()
        old = self.items.get(key) or {}
        self.items[key] = {"desc": desc or csi.division_title(key),
                           "unit": unit, "material": float(material),
                           "labor": float(labor), "crew": crew,
                           "sub": float(sub)}
        if float(equipment or 0):
            self.items[key]["equipment"] = float(equipment)
        for k in TAGS:
            if extra.get(k):
                self.items[key][k] = str(extra[k])
        sizes = _sizes(extra["sizes"]) if "sizes" in extra else \
            old.get("sizes")
        if sizes:
            self.items[key]["sizes"] = sizes
        return self


def division_of(code):
    """The CSI division (2 digits) an item code names: "09 21 16" -> "09",
    catalog codes "A-03-SOG-4.4" / "A-HTL-09-..." / "A-WW-46-..." -> the
    number after the prefix; '' if none."""
    c = str(code or "").strip()
    m = re.match(r"^(\d{2})(?:[ .]|\d|$)", c)
    if m:
        return m.group(1)
    m = re.match(r"^A-(?:[A-Z]+-)?(\d{2})-", c)
    return m.group(1) if m else ""


def _isnum(v):
    try:
        float(v)
        return True
    except (TypeError, ValueError):
        return False


def _num(v):
    try:
        return float(str(v if v is not None else 0).replace("$", "")
                     .replace(",", "").strip() or 0)
    except ValueError:
        return 0.0


DB = "db:"


def load(path):
    """A book from the price database ("db:<name>") or a JSON file."""
    if str(path).startswith(DB):
        from . import pricedb
        data = pricedb.load_book(path[len(DB):])
        if data is None:
            raise ValueError(f"No cost book named {path[len(DB):]}")
        return Book(data, path=path)
    with open(path, encoding="utf-8") as f:
        return Book(json.load(f), path=None)


def save(book, path=None, note=""):
    """Save the book in the price database (returns "db:<name>"), or as a
    JSON file when `path` is a file path (an export)."""
    if path and not str(path).startswith(DB):
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(book.to_dict(), f, indent=1, sort_keys=True)
        os.replace(tmp, path)
        return path
    from . import pricedb
    pricedb.save_book(book.to_dict(), note=note)
    book.path = DB + book.name
    return book.path


_MIGRATED = set()


def _migrate():
    """Old cost book files (costbooks/*.json in the data folder) move into the
    database once."""
    from . import pricedb
    key = pricedb.path()
    if key in _MIGRATED:
        return
    _MIGRATED.add(key)
    try:
        pricedb.migrate_json(book_dir())
    except Exception:
        log.warning("cost book files not moved into the database",
                    exc_info=True)


# The shipped cost book: "QuantiSheet Starter <year>" (a price database or
# estimate saved before the rename is converted - oldnames)
STARTER = "QuantiSheet Starter"


def display_name(name):
    """A cost book's name as shown in the program (a name saved before the
    rename shows today's - oldnames)."""
    from . import oldnames
    return oldnames.new_book_name(name)


def list_books():
    """{name: "db:<name>"} of the books in the price database."""
    from . import pricedb
    _migrate()
    return {n: DB + n for n in pricedb.book_names()}


def find(name):
    from . import pricedb
    _migrate()
    data = pricedb.load_book(name)
    return Book(data, path=DB + data["name"]) if data else None


def delete(name):
    from . import pricedb
    pricedb.delete_book(name)


def _sizes(v):
    """A price-by-size table {"8": {"material", "labor"}} from a book
    entry (numbers alone are material prices)."""
    out = {}
    if not isinstance(v, dict):
        return out
    for k, e in v.items():
        try:
            size = float(str(k).replace('"', "").replace("in", "").strip())
        except ValueError:
            continue
        key = f"{size:g}"
        if isinstance(e, dict):
            out[key] = {"material": _num(e.get("material")),
                        "labor": _num(e.get("labor")),
                        "sub": _num(e.get("sub"))}
        elif _isnum(e):
            out[key] = {"material": float(e), "labor": 0.0, "sub": 0.0}
    return out


def size_price(item, size):
    """(item priced for this size, note): the book's price for the size
    (e.g. pipe diameter in inches), between two listed sizes in proportion,
    or the nearest listed size outside the table. Items without a size
    table come back as they are."""
    table = item.get("sizes") or {}
    try:
        d = float(size)
    except (TypeError, ValueError):
        return item, ""
    if not table or d <= 0:
        return item, ""
    pts = sorted((float(k), v) for k, v in table.items())
    out = dict(item)
    note = ""
    lo = max((p for p in pts if p[0] <= d), default=None,
             key=lambda p: p[0])
    hi = min((p for p in pts if p[0] >= d), default=None,
             key=lambda p: p[0])
    if lo and hi and lo[0] != hi[0]:
        t = (d - lo[0]) / (hi[0] - lo[0])
        pick = {k: lo[1][k] + t * (hi[1][k] - lo[1][k])
                for k in ("material", "labor", "sub")}
        note = ""                    # in between two sizes: fine
    else:
        near = lo or hi
        pick = dict(near[1])
        if near[0] != d:
            note = (f"{d:g} in isn't in the price table - priced at "
                    f"{near[0]:g} in")
    for k in ("material", "labor", "sub"):
        if pick.get(k) or k == "material":
            out[k] = pick.get(k) or 0.0
    return out, note


def _cell_text(v):
    """A spreadsheet cell as the text a CSV of it would hold."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    if isinstance(v, (_dt.datetime, _dt.date)):
        return v.isoformat()[:10]
    return " ".join(str(v).split())


def code_text(v):
    """A cost code as typed: Excel drops the leading zero of 033113 (a
    number), so a 5-digit code gets it back."""
    t = _cell_text(v)
    return t.zfill(6) if t.isdigit() and len(t) == 5 else t


def read_sheet(path):
    """(header, rows) of a spreadsheet: .xlsx / .xlsm (the first sheet) or
    CSV (Excel's Windows-1252 too). Every cell comes back as text, the
    header is the first row that has anything in it, and blank rows are
    left out."""
    if str(path).lower().endswith((".xlsx", ".xlsm")):
        import openpyxl
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        try:
            ws = wb.worksheets[0]
            rows = [[_cell_text(c) for c in r]
                    for r in ws.iter_rows(values_only=True)]
        finally:
            wb.close()
    else:
        from .textio import open_csv
        with open_csv(path) as f:
            from . import safecell      # a template we wrote: no "'"
            rows = [[safecell.unquote(_cell_text(c)) for c in r]
                    for r in csv.reader(f)]
    rows = [r for r in rows if any(c.strip() for c in r)]
    if not rows:
        return [], []
    head = [h.strip() for h in rows[0]]
    body = [r + [""] * (len(head) - len(r)) for r in rows[1:]]
    return head, body


def from_rows(head, rows, name, effective=None, escalation=0.0):
    """A book from spreadsheet rows (read_sheet) with columns Code,
    Description, Unit, Material, Equipment, Labor (hours per unit), Crew,
    Sub - and optionally Size: rows with a size (pipe diameter in inches)
    build that code's price by size."""
    book = Book({"name": name, "effective": effective,
                 "escalation": escalation})
    keys = [str(k).lower().strip() for k in head]
    for r in rows:
        low = {k: (v or "").strip() for k, v in zip(keys, r) if k}
        code = low.get("code") or low.get("csi") or low.get("cost code")
        code = code_text(code)
        if not code:
            continue
        equip = _num(low.get("equipment") or low.get("equipment $") or
                     low.get("equip"))
        size = low.get("size") or low.get("diameter") or ""
        if size:
            key = csi.parse_code(code) or str(code).strip()
            if key not in book.items:
                book.set(code, low.get("unit", "ea"),
                         material=_num(low.get("material") or
                                       low.get("cost")),
                         labor=_num(low.get("labor") or
                                    low.get("labor hours")),
                         desc=low.get("description") or
                         low.get("desc", ""), equipment=equip)
            book.items[key].setdefault("sizes", {}).update(_sizes({
                size: {"material": low.get("material") or
                       low.get("cost"),
                       "labor": low.get("labor") or
                       low.get("labor hours"),
                       "sub": low.get("sub")}}))
            continue
        book.set(code, low.get("unit", "ea"),
                 material=_num(low.get("material") or low.get("cost")),
                 labor=_num(low.get("labor") or low.get("labor hours")
                            or low.get("hours")),
                 crew=low.get("crew", ""), sub=_num(low.get("sub")),
                 desc=low.get("description") or low.get("desc", ""),
                 equipment=equip)
    return book


def from_csv(path, name=None, effective=None, escalation=0.0):
    """A book from a spreadsheet saved as CSV - or an Excel .xlsx file -
    with columns Code, Description, Unit, Material, Equipment, Labor
    (hours per unit), Crew, Sub - and optionally Size: rows with a size
    (pipe diameter in inches) build that code's price by size. The same
    rows give the same book from either kind of file."""
    head, rows = read_sheet(path)
    return from_rows(head, rows,
                     name or os.path.splitext(os.path.basename(path))[0],
                     effective, escalation)


from_xlsx = from_csv


# ---- unit costs ------------------------------------------------------------------

def _dec(v):
    from .dmoney import D
    return D(v)


def labor_output(hours_per_unit, crew_size=1.0, hours_per_day=HOURS_PER_DAY):
    """Units a crew puts in per day: (crew size x hours a day) / labor
    hours per unit (worker-hours). None when there are no hours."""
    h = _dec(hours_per_unit)
    if h <= 0:
        return None
    return _dec(crew_size) * _dec(hours_per_day) / h


def hours_from_output(output, crew_size=1.0, hours_per_day=HOURS_PER_DAY):
    """Labor hours per unit from a labor output (units per crew-day):
    (crew size x hours a day) / output. None without an output."""
    o = _dec(output)
    if o <= 0:
        return None
    return _dec(crew_size) * _dec(hours_per_day) / o


def crew_size(crew):
    from . import labor
    try:
        return labor.crew_size(crew) if crew else 1.0
    except Exception:
        return 1.0


def unit_cost(book, item, region=None, as_of=None, code=None):
    """One unit of a book item priced in `region` (default: the book's
    own) as of `as_of` (default: the book's date, so no escalation):
    {"material", "equipment", "sub", "labor" ($), "labor_hours",
    "labor_rate" (None when the item has no crew rate), "total",
    "output" (units per crew-day or None), "crew_size"}. Exact Decimals,
    not rounded."""
    from . import labor
    if isinstance(item, str):
        code, item = item, book.get(item) or {}
    item = item or {}
    reg = book._reg(region) if region else book.region
    when = as_of or book.effective
    f = _dec(round(book.factor(reg, when, code), 10))
    mat = _dec(item.get("material")) * f
    eqp = _dec(item.get("equipment")) * f
    sub = _dec(item.get("sub")) * f
    hours = _dec(item.get("labor"))
    rate = None
    if item.get("crew"):
        try:
            rate = labor.crew_rate(item["crew"],
                                   book.labor_rates(reg, when) or None)
        except Exception:
            rate = None
    lab = hours * _dec(rate) if rate is not None else Decimal(0)
    size = crew_size(item.get("crew"))
    return {"material": mat, "equipment": eqp, "sub": sub, "labor": lab,
            "labor_hours": hours, "labor_rate": None if rate is None else
            _dec(rate), "total": mat + eqp + sub + lab,
            "output": labor_output(hours, size), "crew_size": size}


def unit_total(book, code_or_item, region=None, as_of=None):
    """The item's total cost per unit (material + equipment + sub + labor)
    in the region, as an exact Decimal."""
    return unit_cost(book, code_or_item, region, as_of)["total"]


def rollup_line(book, code, qty, region=None, as_of=None, trade=None):
    """A cost book item as a cost_rollup line ({"L", "M", "E", "S",
    "total", ...} in cents): its Equipment $ lands in the trade's
    equipment column, material in material, labor $ in labor and sub in
    the total. Escalated to `as_of` like an estimate."""
    from .dmoney import cents
    item = book.get(code) or {}
    u = unit_cost(book, item, region, as_of or _dt.date.today().isoformat(),
                  code)
    q = _dec(qty)
    line = {"code": csi.parse_code(code) or str(code), "desc":
            item.get("desc", ""), "unit": item.get("unit", ""), "qty": q,
            "trade": trade or csi.division_title(code),
            "L": cents(u["labor"] * q), "M": cents(u["material"] * q),
            "E": cents(u["equipment"] * q), "S": cents(u["sub"] * q)}
    line["total"] = line["L"] + line["M"] + line["E"] + line["S"]
    return line


# ---- location factors (locfactors.py) -------------------------------------------

def location_adjustment(mat, lab, eqp, region):
    """The location adjustment of a base estimate (material, labor and
    equipment dollars, priced at national) in `region` (a region name
    from the Location Factors table, a ZIP, city or state). Exact money:

        {"region": "Testville" (None if not found), "found": bool,
         "factors": {"materials": Decimal, "labor": ..., "equipment": ...},
         "base": {"materials", "labor", "equipment", "total"},
         "materials", "labor", "equipment": adjustment $ (cents),
         "total": adjustment $, "percent": Decimal (1 place),
         "percent_text": "+12.0%", "grand_total": base + adjustment,
         "lines": [("Base estimate", $), ("Location adjustment (+12.0%)",
                   $), ("Grand total", $)]}
    """
    from . import locfactors
    return locfactors.adjustment(mat, lab, eqp, region)


def find_region(text):
    """The Location Factors row for a region name, ZIP, city or state
    (best match), or None."""
    from . import locfactors
    return locfactors.find_region(text)


def search_regions(text):
    """Location Factors rows matching a state, city, abbreviation or ZIP."""
    from . import locfactors
    return locfactors.search(text)


def location_factors():
    """Every row of the Location Factors table (starter rows and yours)."""
    from . import locfactors
    return locfactors.rows()


def job_region(doc):
    """The job's location region: the one picked for it (job info), else
    the region of its Job ZIP, else its cost book region; None if none."""
    from . import jobinfo
    return jobinfo.region(doc)


def from_job(doc, name):
    """A starting book from the prices in this job's assemblies: every part
    with a cost code becomes an item."""
    from . import assemblies
    book = Book({"name": name})
    job = assemblies.read_job(doc)
    seen = list(job["assemblies"].values()) + \
        [a for n, a in assemblies.library().items()
         if n not in job["assemblies"]]
    for a in seen:
        for p in a.get("parts") or []:
            if p.get("code") and not book.get(p["code"]):
                book.set(p["code"], p.get("unit", ""), p.get("cost") or 0,
                         p.get("labor") or 0, p.get("crew", ""),
                         desc=p.get("name", ""))
    return book


SHIPPED = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data",
                       "costbooks")
STATES = {"AL": "Alabama", "AK": "Alaska", "AZ": "Arizona",
          "AR": "Arkansas", "CA": "California", "CO": "Colorado",
          "CT": "Connecticut", "DE": "Delaware", "FL": "Florida",
          "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois",
          "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky",
          "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
          "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
          "MS": "Mississippi", "MO": "Missouri", "MT": "Montana",
          "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire",
          "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
          "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio",
          "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania",
          "RI": "Rhode Island", "SC": "South Carolina",
          "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas",
          "UT": "Utah", "VT": "Vermont", "VA": "Virginia",
          "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin",
          "WY": "Wyoming", "DC": "District of Columbia"}


def install_shipped():
    """Put the cost books that come with QuantiSheet into the price
    database (a newer shipped version replaces the book only if nobody has
    edited it) and make the starter book your default the first time.
    Returns the file names installed or updated."""
    from . import pricedb
    done = []
    if not os.path.isdir(SHIPPED):
        return done
    _migrate()
    marks = pricedb.meta("shipped") or {}
    if not isinstance(marks, dict):
        marks = {}
    for n in sorted(os.listdir(SHIPPED)):
        if not n.endswith(".json"):
            continue
        try:
            with open(os.path.join(SHIPPED, n), encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            continue
        ver = str(data.get("version", ""))
        mine = marks.get(n)
        cur = pricedb.load_book(data["name"])
        if cur is not None and mine is None and \
                pricedb.content_hash(cur) == pricedb.content_hash(data):
            marks[n] = {"version": ver, "hash": pricedb.content_hash(cur)}
            done.append(n)
            continue              # already there (moved from the old folder)
        if cur is not None:
            if mine is None or mine.get("version") == ver or \
                    pricedb.content_hash(cur) != mine.get("hash"):
                continue          # same version, or edited since
        pricedb.save_book(data, note=f"QuantiSheet {ver}")
        marks[n] = {"version": ver,
                    "hash": pricedb.content_hash(pricedb.load_book(
                        data["name"]))}
        done.append(n)
    if done:
        pricedb.set_meta("shipped", marks)
    if settings.get("default_costbook") is None:
        name = next((b for b in pricedb.book_names()
                     if b.startswith(STARTER)), None)
        if name:
            starter = find(name)
            settings.set("default_costbook",
                         {"name": starter.name,
                          "region": home_region(starter)})
    return done


def home_region(book):
    """The region of your company address (Settings > Company), if the
    book prices it; else the book's own region."""
    import re
    try:
        from . import proposal
        addr = proposal.company().get("address", "")
    except Exception:
        addr = ""
    names = set(book.region_names())
    for ab in re.findall(r"\b([A-Z]{2})\b\s*\d{5}", addr or ""):
        if STATES.get(ab) in names:
            return STATES[ab]
    for full in STATES.values():
        if full in (addr or "") and full in names:
            return full
    return book.region


def set_default(book, region=None):
    """Use this book (and region) for jobs that haven't picked one; None
    stops using a default."""
    settings.set("default_costbook", None if book is None else
                 {"name": book.name, "region": region or book.region})
