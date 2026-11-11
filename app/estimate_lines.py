"""Added estimate lines: lines in the Estimate panel that aren't a takeoff
group of their own - typed in (Add Line), picked from a cost book (Add
From Cost Book) or made by the quick $/SF estimate.

Each line has a CSI code, a description, a cost type and a unit price
split into Mat / Lab / Eqp / Sub (dollars per unit). Its quantity is
typed in, or - when the line is linked to a takeoff group - is that
group's measured quantity, so it follows the markups as they're drawn.

    total = cents(qty x Mat) + cents(qty x Lab) + cents(qty x Eqp)
            + cents(qty x Sub)

so the four columns always add up to the total to the cent. Money is
Decimal throughout (see dmoney.py); the lines are saved inside the PDF
(embedded file quantisheet_estimate_lines.json, next to the takeoff prices
in quantisheet_estimate.json) so they travel with the drawings.

Deleting a line never touches a markup: a linked line only reads its
group.
"""
import datetime
import json
import logging
import uuid
from decimal import Decimal, InvalidOperation

from . import csi, dmoney, embfiles

log = logging.getLogger(__name__)

FILE = "quantisheet_estimate_lines.json"
VERSION = 1
MAX_LINES = 5000
PARTS = ("mat", "lab", "eqp", "sub")
PART_LABEL = {"mat": "Material", "lab": "Labor", "eqp": "Equipment",
              "sub": "Subcontract"}
# what the Cost Type column offers ("" = worked out from the split)
COST_TYPES = ("", "Material", "Labor", "Equipment", "Subcontract",
              "Allowance", "Other")
_TYPE_ALIAS = {"m": "Material", "mat": "Material", "material": "Material",
               "materials": "Material",
               "l": "Labor", "lab": "Labor", "labor": "Labor",
               "labour": "Labor",
               "e": "Equipment", "eq": "Equipment", "eqp": "Equipment",
               "equip": "Equipment", "equipment": "Equipment",
               "s": "Subcontract", "sub": "Subcontract",
               "subcontract": "Subcontract", "subcontractor": "Subcontract",
               "a": "Allowance", "allow": "Allowance",
               "allowance": "Allowance",
               "o": "Other", "other": "Other"}
# the cost type that takes a plain "Unit Cost" typed on a line
TYPE_PART = {"Material": "mat", "Labor": "lab", "Equipment": "eqp",
             "Subcontract": "sub", "Allowance": "sub", "Other": "sub"}
UNIT_PLACES = Decimal("0.0001")        # unit prices may be under a cent
QTY_PLACES = Decimal("0.0001")
LIMIT = Decimal("1e12")
TEXT_MAX = {"code": 40, "desc": 300, "unit": 12, "source": 120,
            "crew": 40, "note": 500, "cost_type": 20}


class LineError(ValueError):
    pass


# ---- values ---------------------------------------------------------------

def cost_type(v):
    """'Material', 'Labor'... for what a person typed ('m', 'sub'); '' for
    blank. Raises LineError for anything else."""
    t = " ".join(str(v or "").split()).lower()
    if not t or t in ("auto", "(auto)", "mixed"):
        return ""
    if t in _TYPE_ALIAS:
        return _TYPE_ALIAS[t]
    raise LineError(f"Cost type {str(v).strip()!r}: use one of "
                    + ", ".join(c for c in COST_TYPES if c))


_cost_type = cost_type


def number(v, what="value", places=UNIT_PLACES, blank=Decimal(0)):
    """Decimal from what a person typed ("$1,250", "2", "(5)") or a stored
    value; LineError for text that isn't a number or is out of range."""
    if v is None or (isinstance(v, str) and not v.strip()):
        return blank
    if isinstance(v, bool) or dmoney.bad(v):
        raise LineError(f"{what}: can't read {str(v).strip()!r} as a "
                        "number")
    d = dmoney.D(v)
    if not d.is_finite() or abs(d) > LIMIT:
        raise LineError(f"{what}: {str(v).strip()!r} is out of range")
    try:
        return d.quantize(places)
    except InvalidOperation:
        raise LineError(f"{what}: {str(v).strip()!r} is out of range")


def _safe(v, places=UNIT_PLACES):
    """number() for stored data: a bad value reads as 0 instead of
    stopping the panel (a PDF can come from anywhere)."""
    try:
        return number(v, places=places)
    except LineError:
        return Decimal(0)


def _text(v, key):
    return " ".join(str(v if v is not None else "").split())[:TEXT_MAX.get(
        key, 200)]


def _link(v):
    if not isinstance(v, dict) or not v.get("name"):
        return None
    out = {"name": _text(v.get("name"), "desc"),
           "type": _text(v.get("type"), "unit"),
           "unit": _text(v.get("unit"), "unit")}
    # optional quantity formula off the group's quantity (r36): "qty / 32"
    formula = _text(v.get("formula"), "note")[:200]
    if formula:
        out["formula"] = formula
    return out


def link_quantity(link, quantity, count):
    """The line's quantity from its group by the link's formula of `qty`
    (the group's quantity in its own unit) and `count` (its markups), as
    a Decimal; raises assemblies.FormulaError when the formula fails."""
    from . import assemblies
    v = assemblies.evaluate(link["formula"], {"qty": float(quantity),
                                              "count": float(count or 0)})
    return dmoney.D(round(float(v), 6)).quantize(QTY_PLACES)


def _by_formula(link, g):
    try:
        return link_quantity(link, g["quantity"], g.get("count")), ""
    except Exception as e:                                # noqa: BLE001
        return Decimal(0), f"quantity formula {link['formula']!r}: {e}"


def _date(v):
    t = str(v or "").strip()[:10]
    try:
        datetime.date.fromisoformat(t)
        return t
    except ValueError:
        return ""


def today():
    return datetime.date.today().isoformat()


def clean(line):
    """A stored line, checked: every field present and of its kind."""
    ln = dict(line or {})
    out = {"id": _text(ln.get("id"), "code") or uuid.uuid4().hex[:12],
           "code": _text(ln.get("code"), "code"),
           "desc": _text(ln.get("desc"), "desc"),
           "unit": _text(ln.get("unit"), "unit"),
           "qty": str(_safe(ln.get("qty", 1), QTY_PLACES)),
           "link": _link(ln.get("link")),
           "source": _text(ln.get("source"), "source"),
           "crew": _text(ln.get("crew"), "crew"),
           "hours": str(_safe(ln.get("hours", 0))),
           "note": _text(ln.get("note"), "note"),
           # Nov 3 (stale price warning): the day its price was last set;
           # "" for lines priced before 1.0.6 (age unknown)
           "priced_on": _date(ln.get("priced_on"))}
    try:
        out["cost_type"] = cost_type(ln.get("cost_type"))
    except LineError:
        out["cost_type"] = ""
    for k in PARTS:
        out[k] = str(_safe(ln.get(k, 0)))
    return out


def new_line(desc="", qty=1, unit="ls", code="", cost_type="", mat=0, lab=0,
             eqp=0, sub=0, link=None, source="", hours=0, crew="", note=""):
    """A new line (raises LineError when a number can't be read)."""
    vals = {"desc": desc, "unit": unit, "code": code, "source": source,
            "crew": crew, "note": note, "link": link,
            "id": uuid.uuid4().hex[:12], "priced_on": today()}
    vals["cost_type"] = _cost_type(cost_type)
    vals["qty"] = str(number(qty, "Quantity", QTY_PLACES, Decimal(1)))
    vals["hours"] = str(number(hours, "Labor hours"))
    for k, v in (("mat", mat), ("lab", lab), ("eqp", eqp), ("sub", sub)):
        vals[k] = str(number(v, PART_LABEL[k]))
    if vals["code"]:
        vals["code"] = csi.parse_code(vals["code"]) or _text(vals["code"],
                                                             "code")
    return clean(vals)


# ---- storage --------------------------------------------------------------

def read(doc):
    """The document's added lines, in order (cleaned)."""
    try:
        if doc is None or FILE not in embfiles.names(doc):
            return []
        data = json.loads(embfiles.get(doc, FILE).decode("utf-8"))
    except Exception:                                     # noqa: BLE001
        log.warning("could not read the added estimate lines", exc_info=True)
        return []
    rows = data.get("lines") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        return []
    out, seen = [], set()
    for r in rows[:MAX_LINES]:
        if not isinstance(r, dict):
            continue
        ln = clean(r)
        while ln["id"] in seen:             # two lines must never share one
            ln["id"] = uuid.uuid4().hex[:12]
        seen.add(ln["id"])
        out.append(ln)
    return out


def write(doc, lines):
    data = {"version": VERSION, "lines": [clean(x) for x in lines]}
    embfiles.put(doc, FILE, json.dumps(data).encode("utf-8"),
                 "QuantiSheet added estimate lines")


def add(doc, lines):
    """Append lines (dicts from new_line); returns their ids."""
    have = read(doc)
    new = [clean(x) for x in lines]
    ids = {x["id"] for x in have}
    for x in new:
        while x["id"] in ids:
            x["id"] = uuid.uuid4().hex[:12]
        ids.add(x["id"])
    if len(have) + len(new) > MAX_LINES:
        raise LineError(f"An estimate holds at most {MAX_LINES} added lines.")
    write(doc, have + new)
    return [x["id"] for x in new]


def get(doc, line_id):
    return next((x for x in read(doc) if x["id"] == line_id), None)


def update(doc, line_id, **fields):
    """Change fields of one line (values as typed; raises LineError)."""
    lines = read(doc)
    ln = next((x for x in lines if x["id"] == line_id), None)
    if ln is None:
        raise LineError("That line is no longer in the estimate.")
    for k, v in fields.items():
        if k in PARTS:
            new = str(number(v, PART_LABEL[k]))
            if new != ln[k]:
                ln["priced_on"] = today()
            ln[k] = new
        elif k == "qty":
            if ln.get("link"):
                raise LineError("This line's quantity comes from takeoff "
                                f"group {ln['link']['name']!r}; unlink it "
                                "to type a quantity.")
            ln[k] = str(number(v, "Quantity", QTY_PLACES))
        elif k == "hours":
            ln[k] = str(number(v, "Labor hours"))
        elif k == "cost_type":
            ln[k] = cost_type(v)
        elif k == "code":
            t = _text(v, "code")
            ln[k] = csi.parse_code(t) or t
        elif k == "link":
            ln[k] = _link(v)
        elif k in ("desc", "unit", "source", "crew", "note"):
            ln[k] = _text(v, k)
        elif k == "priced_on":                # "price still good" today
            ln[k] = _date(v) or today()
        else:
            raise LineError(f"unknown field {k!r}")
    write(doc, lines)
    return clean(ln)


def set_unit_cost(doc, line_id, value):
    """A plain unit cost typed on a line: it goes in the part the line's
    cost type names (Allowance / Other: Sub), else the one part that has a
    price, else Mat. A line split over several parts can't take one."""
    ln = get(doc, line_id)
    if ln is None:
        raise LineError("That line is no longer in the estimate.")
    v = number(value, "Unit cost")
    filled = [k for k in PARTS if Decimal(ln[k])]
    part = TYPE_PART.get(ln["cost_type"])
    if part is None:
        if len(filled) > 1:
            raise LineError("This line's unit cost is Mat + Lab + Eqp + Sub;"
                            " change those instead.")
        part = filled[0] if filled else "mat"
    elif any(k != part for k in filled):
        raise LineError("This line's unit cost is Mat + Lab + Eqp + Sub; "
                        "change those instead.")
    return update(doc, line_id, **{part: v})


def delete(doc, ids):
    """Remove the lines with these ids; returns how many went. Only the
    lines file changes - never a markup."""
    ids = set(ids)
    lines = read(doc)
    keep = [x for x in lines if x["id"] not in ids]
    if len(keep) != len(lines):
        write(doc, keep)
    return len(lines) - len(keep)


# ---- pricing --------------------------------------------------------------

def _groups(doc, page=None):
    from . import estimate
    try:
        return {(g["name"], g["type"], g["unit"]): g
                for g in estimate.lines(doc, page)}
    except Exception:                                     # noqa: BLE001
        log.warning("takeoff groups unavailable", exc_info=True)
        return {}


def convert(qty, from_unit, to_unit):
    """qty (Decimal) in from_unit as to_unit; raises units.UnitError when
    they're different kinds of thing."""
    a, b = str(from_unit or "").strip(), str(to_unit or "").strip()
    if not b or a.lower() == b.lower():
        return qty
    from . import units
    v = units.Quantity(float(qty), a).to(b).value
    return dmoney.D(v)


def link_problem(link, unit):
    """Why a line priced per `unit` can't follow `link`'s group, or ''."""
    from . import units
    if link.get("formula"):            # the formula gives the line's unit
        return ""
    try:
        convert(Decimal(1), link.get("unit"), unit)
    except (units.UnitError, ValueError, OverflowError) as e:
        return (f"{link.get('name')} is measured in {link.get('unit')!r}; "
                f"this line is priced per {unit!r} ({e})")
    return ""


def kind_of(p):
    """The cost type a priced line is shown and totalled under: its own,
    else the one part it has, else 'Mixed' ('' when it has no price)."""
    if p.get("cost_type"):
        return p["cost_type"]
    filled = [k for k in PARTS if p["unit"][k]] if isinstance(
        p.get("unit"), dict) else []
    if len(filled) == 1:
        return PART_LABEL[filled[0]]
    return "Mixed" if filled else ""


def price(line, groups=None):
    """One line with its money: {..., "quantity" (Decimal), "unit_price":
    {mat, lab, eqp, sub}, "unit_cost", "ext": {mat, lab, eqp, sub},
    "total" (all Decimal), "linked", "count", "problem"}."""
    ln = clean(line)
    out = dict(ln)
    up = {k: Decimal(ln[k]) for k in PARTS}
    qty, problem, count = Decimal(ln["qty"]), "", None
    link = ln.get("link")
    if link:
        g = (groups or {}).get((link["name"], link["type"], link["unit"]))
        if g is None:
            qty = Decimal(0)
            problem = (f"Takeoff group {link['name']!r} has no markups "
                       "(here)")
        elif link.get("formula"):                       # r36
            count = g.get("count")
            qty, problem = _by_formula(link, g)
        else:
            count = g.get("count")
            try:
                qty = convert(dmoney.D(round(float(g["quantity"]), 6)),
                              link["unit"], ln["unit"] or link["unit"])
                qty = qty.quantize(QTY_PLACES)
            except Exception as e:                        # noqa: BLE001
                qty = Decimal(0)
                problem = (f"{link['name']} is in {link['unit']!r}, this "
                           f"line is per {ln['unit']!r}: {e}")
    # a measured quantity is priced as shown, to 2 places; a typed one
    # exactly as typed (rounding.py, policy 2)
    from . import rounding
    money_qty = rounding.money_qty(qty) if link else qty
    ext = {}
    for k in PARTS:
        try:
            ext[k] = dmoney.cents(money_qty * up[k])
        except InvalidOperation:
            ext[k] = Decimal("0.00")
            problem = problem or "amount out of range"
    out.update({"quantity": qty, "unit_price": up,
                "unit_cost": sum(up.values(), Decimal(0)), "ext": ext,
                "total": sum(ext.values(), Decimal("0.00")),
                "linked": bool(link), "count": count, "problem": problem,
                "unit_label": ln["unit"] or (link or {}).get("unit", "")})
    out["kind"] = kind_of({"cost_type": ln["cost_type"], "unit": up})
    return out


def priced(doc, page=None, lines=None):
    """Every added line priced. With `page`, only linked lines, at that
    page's quantity (a typed line isn't on any page)."""
    lines = read(doc) if lines is None else lines
    if page is not None:
        lines = [x for x in lines if x.get("link")]
    groups = _groups(doc, page) if any(x.get("link") for x in lines) else {}
    return [price(x, groups) for x in lines]


def total(rows):
    return sum((r["total"] for r in rows), Decimal("0.00"))


def by_type(rows):
    """{cost type: Decimal} for priced lines: the Mat / Lab / Eqp / Sub
    split, except a line marked Allowance or Other, which counts whole."""
    out = {}
    for r in rows:
        if r.get("cost_type") in ("Allowance", "Other"):
            out[r["cost_type"]] = out.get(r["cost_type"], Decimal("0.00")) \
                + r["total"]
            continue
        for k in PARTS:
            if r["ext"][k]:
                lab = PART_LABEL[k]
                out[lab] = out.get(lab, Decimal("0.00")) + r["ext"][k]
    return out


# ---- a line from a cost book ---------------------------------------------

def from_book(book, code, region=None, as_of=None, job=None, qty=1,
              link=None):
    """A line for cost book item `code`, priced as the job prices it: the
    region index and escalation on material, equipment and sub; labor
    hours at the crew's rate (the book's labor rates for the region, then
    the job's own) or the job's labor rate."""
    from . import labor
    item = book.get(code)
    if item is None:
        raise LineError(f"{code} is not in {book.name}")
    key = csi.parse_code(code) or str(code).strip()
    try:
        f = dmoney.D(book.factor(region, as_of, key))
    except Exception:                                     # noqa: BLE001
        f = Decimal(1)
    job = job or {}
    rate = None
    hrs = dmoney.D(item.get("labor") or 0)
    if hrs and item.get("crew"):
        try:
            rates = dict(book.labor_rates(region, as_of))
            rates.update(job.get("rates") or {})
            rate = labor.crew_rate(item["crew"], rates)
        except Exception:                                 # noqa: BLE001
            rate = None
    if rate is None:
        rate = job.get("labor_rate", 55.0)
    eqp = item.get("equipment", item.get("eqp", 0)) or 0
    return new_line(
        desc=item.get("desc") or csi.division_title(key), qty=qty,
        unit=item.get("unit") or "ea", code=key,
        mat=(dmoney.D(item.get("material") or 0) * f).quantize(UNIT_PLACES),
        eqp=(dmoney.D(eqp) * f).quantize(UNIT_PLACES),
        sub=(dmoney.D(item.get("sub") or 0) * f).quantize(UNIT_PLACES),
        lab=(hrs * dmoney.D(rate or 0)).quantize(UNIT_PLACES),
        hours=hrs, crew=item.get("crew") or "", link=link,
        source=book.name)


# ---- what other parts of the program read ---------------------------------

def rollup_rows(doc, taken=()):
    """Added lines as assembly-rollup rows (assemblies.rollup), so the
    proposal, the assembly Excel export, the bid build-up and the SOV see
    them as they see assemblies. "material" holds everything that isn't
    labor (Mat + Eqp + Sub); "material_only" is the Mat part (what sales
    tax applies to)."""
    rows, names = [], set(taken)
    for p in priced(doc):
        if not p["total"] and not p["quantity"]:
            continue
        name = p["desc"] or p["code"] or "Estimate line"
        base, n = name, 2
        while name in names:
            name = f"{base} ({n})"
            n += 1
        names.add(name)
        code = csi.parse_code(p["code"]) or ""
        trade = csi.DIVISIONS.get(code[:2], "") if code else ""
        trade = trade[:1].upper() + trade[1:] if trade else "General"
        e = p["ext"]
        mat = float(e["mat"])
        other = float(e["eqp"] + e["sub"])
        lab = float(e["lab"])
        hours = float(p["quantity"] * Decimal(p["hours"] or 0))
        part = {"name": name, "unit": p["unit_label"],
                "qty": float(p["quantity"]), "cost": float(p["unit_cost"]),
                "material": mat + other, "material_only": mat,
                "equipment": float(e["eqp"]), "sub": float(e["sub"]),
                "labor_hours": hours, "labor_cost": lab,
                "labor_rate": (lab / hours) if hours else 0.0,
                "crew_days": hours / 8.0, "crew": p.get("crew", ""),
                "code": code, "total": float(p["total"]),
                "line_id": p["id"]}
        rows.append({"name": name, "trade": trade, "csi": code,
                     "measure": "line", "quantity": float(p["quantity"]),
                     "unit": p["unit_label"], "items": 1, "parts": [part],
                     "adjust": 1.0, "material": mat + other,
                     "labor_hours": hours, "labor_cost": lab,
                     "crew_days": hours / 8.0, "total": float(p["total"]),
                     "added": True, "line_id": p["id"]})
    return rows


SAGE_CATEGORY = {"mat": "M", "lab": "L", "eqp": "E", "sub": "S"}


def sage_lines(doc):
    """Added lines as plain lines for sage_export.job_cost_rows: one per
    cost category with money (an Allowance / Other line: one 'O' line)."""
    out = []
    for p in priced(doc):
        base = {"code": p["code"], "desc": p["desc"], "unit": p["unit_label"],
                "qty": p["quantity"], "source": "estimate line"}
        if p["cost_type"] in ("Allowance", "Other"):
            if p["total"]:
                out.append(dict(base, category="O", total=p["total"]))
            continue
        for k in PARTS:
            if p["ext"][k]:
                out.append(dict(base, category=SAGE_CATEGORY[k],
                                total=p["ext"][k]))
    return out


# ---- location adjustment (when the cost book module offers one) ----------

def location_adjustment(mat, lab, eqp, region):
    """{"mat", "lab", "eqp", "total"} (Decimal cents) from
    costbook.location_adjustment(mat, lab, eqp, region), or None when the
    cost book module has no such function or it can't answer. Its answer
    may be a dict by cost type, a sequence (mat, lab, eqp) or one
    number."""
    from . import costbook
    fn = getattr(costbook, "location_adjustment", None)
    if not callable(fn):
        return None
    try:
        res = fn(float(mat), float(lab), float(eqp), region)
    except Exception:                                     # noqa: BLE001
        log.warning("location adjustment unavailable", exc_info=True)
        return None
    keys = {"mat": ("mat", "material", "materials", "m"),
            "lab": ("lab", "labor", "labour", "l"),
            "eqp": ("eqp", "equipment", "equip", "e", "eq")}
    out = {"mat": Decimal("0.00"), "lab": Decimal("0.00"),
           "eqp": Decimal("0.00")}
    try:
        if isinstance(res, dict):
            low = {str(k).lower(): v for k, v in res.items()}
            if low.get("found") is False:
                return None                 # no such region: no adjustment
            shown = _lines_of(low.get("lines"))
            if shown:
                out["lines"] = shown
            for k, names in keys.items():
                for n in names:
                    if n in low and not dmoney.bad(low[n]):
                        out[k] = dmoney.cents(low[n])
                        break
            if "total" in low and not dmoney.bad(low["total"]) and \
                    not any(out[k] for k in ("mat", "lab", "eqp")):
                out["total"] = dmoney.cents(low["total"])
                return out
        elif isinstance(res, (list, tuple)):
            vals = [dmoney.cents(v) for v in list(res)[:3]
                    if not dmoney.bad(v)]
            for k, v in zip(("mat", "lab", "eqp"), vals):
                out[k] = v
        elif res is None:
            return None
        elif not dmoney.bad(res):
            out["total"] = dmoney.cents(res)
            return out
        else:
            return None
    except (InvalidOperation, TypeError, ValueError):
        log.warning("location adjustment: can't read %r", res)
        return None
    out["total"] = out["mat"] + out["lab"] + out["eqp"]
    return out


def _lines_of(v):
    """[(label, Decimal)] x3 from the cost book module's own "lines", or
    None when they aren't that."""
    try:
        rows = [(str(a), dmoney.cents(b)) for a, b in v]
    except (TypeError, ValueError, InvalidOperation):
        return None
    return rows if len(rows) == 3 and all(lb for lb, _ in rows) else None


def job_region(doc):
    """The job's location region: the cost book module's answer when it
    has one (job info, Job ZIP...), else the job's cost book region, or
    None."""
    from . import costbook
    fn = getattr(costbook, "job_region", None)
    if callable(fn):
        try:
            r = fn(doc)
            if isinstance(r, dict):
                r = r.get("name") or r.get("region")
            if r:
                return str(r)
        except Exception:                                 # noqa: BLE001
            log.warning("job location region unavailable", exc_info=True)
    try:
        from . import assemblies
        book, region, _as_of = assemblies.job_costbook(
            assemblies.read_job(doc))
        if book is not None:
            return region or book.region
        return region
    except Exception:                                     # noqa: BLE001
        log.warning("job region unavailable", exc_info=True)
        return None


def location_lines(base, mat, lab, eqp, region):
    """[(label, Decimal)] for 'Base estimate / Location adjustment (+x%) /
    Grand total', or [] when there's no location adjustment to show."""
    adj = location_adjustment(mat, lab, eqp, region)
    if adj is None:
        return []
    # no adjustment, no lines: "Location adjustment (+0.0%) $0.00" on a
    # proposal said nothing (Chief's estimator test, Nov 7)
    if not dmoney.cents(adj.get("total") or 0):
        return []
    base = dmoney.cents(base)
    own = adj.get("lines")
    if own and own[0][1] == base:
        return own
    pct = (adj["total"] / base * 100).quantize(Decimal("0.1")) if base \
        else Decimal("0.0")
    sign = "+" if pct >= 0 else ""
    return [("Base estimate", base),
            (f"Location adjustment ({sign}{pct}%)", adj["total"]),
            ("Grand total", base + adj["total"])]
