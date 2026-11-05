"""Extra settings on a measurement, kept on the markup (Nov 2, scope list
items 6, 7, 8 and 12):

  rise      vertical length added to a run, in drawing units (conduit
            dropping 8 ft to a switch: the run measures plan + 8 ft);
  height    a wall height: the run becomes a wall area,
            length x height, less
  openings  the doors and windows in it, in square drawing units;
  show      the unit a volume is shown in ("cu yd" instead of "cu ft");
  to        the unit the measurement is kept in when it differs from the
            sheet's scale (a metric tool on a sheet scaled in feet).

The measurement's own value (in its subject) is always the final quantity,
so totals, estimates and exports need nothing new; these settings only say
how it was worked out, so a reshape, a convert or a change of height works
it out again the same way.
"""
import json
import re

KEY = "PSMeasureX"
FIELDS = ("rise", "height", "openings", "show", "to")
LENGTH_UNITS = ("ft", "in", "yd", "m", "cm", "mm")

# cubic units, in cubic feet / cubic metres
_CU_IMPERIAL = {"cu ft": 1.0, "cu yd": 27.0, "cu in": 1 / 1728.0}
_CU_METRIC = {"cu m": 1.0, "cu cm": 1e-6, "cu mm": 1e-9}


def read(doc, annot):
    """The markup's extra settings ({} when it has none)."""
    try:
        t, v = doc.xref_get_key(annot.xref, KEY)
    except Exception:
        return {}
    if t != "string" or not v:
        return {}
    try:
        d = json.loads(v)
    except ValueError:
        return {}
    return clean(d) if isinstance(d, dict) else {}


def clean(d):
    """Only the known settings, as numbers / short text."""
    out = {}
    for k in ("rise", "height", "openings"):
        try:
            v = float(d.get(k))
        except (TypeError, ValueError):
            continue
        if v == v and abs(v) < 1e7 and (k == "rise" or v >= 0):
            out[k] = round(v, 4)
    if out.get("height") == 0:
        out.pop("height")
        out.pop("openings", None)
    if not out.get("rise"):
        out.pop("rise", None)
    if not out.get("openings"):
        out.pop("openings", None)
    if d.get("to") in LENGTH_UNITS:
        out["to"] = d["to"]
    s = d.get("show")
    if isinstance(s, str) and (s in _CU_IMPERIAL or s in _CU_METRIC):
        out["show"] = s
    return out


def write(doc, annot, d):
    import fitz
    d = clean(d or {})
    if d:
        doc.xref_set_key(annot.xref, KEY, fitz.get_pdf_str(json.dumps(d)))
    else:
        doc.xref_set_key(annot.xref, KEY, "null")
    return d


# ---- the quantity --------------------------------------------------------------------

def run_value(plan_length, extra):
    """A run's quantity: its plan length plus any rise/drop, or - with a
    height - its wall area (length x height less openings, never below 0).
    Returns (type, value)."""
    extra = extra or {}
    length = float(plan_length) + abs(float(extra.get("rise") or 0))
    h = extra.get("height")
    if h:
        area = length * float(h) - float(extra.get("openings") or 0)
        return "area", max(0.0, area)
    return "length", length


def unit_for(mtype, unit):
    return {"area": f"sq {unit}", "volume": f"cu {unit}"}.get(mtype, unit)


def to_units(mtype, value, base, extra):
    """A value worked out in the sheet's unit `base` ("ft"), in the unit
    the measurement keeps (extra "to", else `base`): (value, unit text)."""
    from . import takeoff
    to = (extra or {}).get("to")
    power = {"length": 1, "area": 2, "volume": 3}.get(mtype, 1)
    if not to or to == base:
        return value, unit_for(mtype, base)
    f = takeoff.convert(1.0, base, to)
    return value * f ** power, unit_for(mtype, to)


def is_wall(extra):
    return bool((extra or {}).get("height"))


def volume_in(value, unit, to):
    """A volume in another cubic unit of the same system, or None."""
    for table in (_CU_IMPERIAL, _CU_METRIC):
        if unit in table and to in table:
            return value * table[unit] / table[to]
    return None


def volume_choices(unit):
    """The cubic units a volume in `unit` can be shown in."""
    for table in (_CU_IMPERIAL, _CU_METRIC):
        if unit in table:
            return list(table)
    return [unit]


def base_unit(unit):
    """'cu ft' -> 'ft', 'sq m' -> 'm', 'ft' -> 'ft'."""
    return unit.split(" ", 1)[1] if " " in unit else unit


# ---- typed openings ------------------------------------------------------------------

_ONE = re.compile(r"^\s*(?:(\d+)\s*[x@*]\s+)?(.+?)\s*[x×*]\s*(.+?)"
                  r"(?:\s*[x×*@]\s*(\d+))?\s*$", re.I)


def parse_openings(text, unit="ft"):
    """Openings typed as sizes, in square `unit`s, or None if unreadable.

    "3x7" one 3 x 7 door; "3x7 x2" or "2 x 3x7" two of them; several
    separated by commas or semicolons: "3'x7' x2, 6x4". A plain number is
    an area already ("42"). Sizes take feet and inches (3'-0"x6'-8")."""
    from . import takeoff
    text = (text or "").strip()
    if not text:
        return 0.0
    try:
        return max(0.0, float(text.replace(",", "")))
    except ValueError:
        pass
    total = 0.0
    for part in re.split(r"[;,]", text):
        if not part.strip():
            continue
        m = _ONE.match(part)
        if not m:
            return None
        lead, w, h, tail = m.groups()
        n = int(lead or tail or 1)
        sizes = []
        for s in (w, h):
            got = takeoff.parse_length(s.strip())
            if not got or got[0] <= 0:
                return None
            sizes.append(takeoff.convert(got[0], got[1], unit))
        total += n * sizes[0] * sizes[1]
    return total


# ---- the label -----------------------------------------------------------------------

def label_text(mtype, value, unit, group, extra, fmt_length=None):
    """The markup's label, saying how the quantity was made."""
    extra = extra or {}
    if mtype == "length":
        text = fmt_length(value, unit) if fmt_length else f"{value:,.2f} {unit}"
        if extra.get("rise"):
            r = abs(extra["rise"])
            rt = fmt_length(r, unit) if fmt_length else f"{r:g} {unit}"
            text += f" (incl. {rt} rise/drop)"
    elif mtype == "area" and is_wall(extra):
        u = base_unit(unit)
        h = extra["height"]
        ht = fmt_length(h, u) if fmt_length else f"{h:g} {u}"
        text = f"{value:,.2f} {unit} wall ({ht} high"
        if extra.get("openings"):
            text += f", less {extra['openings']:,.1f} {unit} openings"
        text += ")"
    else:
        text = f"{value:,.2f} {unit}"
    return join(group, text)


CAPTIONS = {"both": "Name and Quantity", "value": "Quantity Only",
            "name": "Name Only"}


def caption_mode():
    from . import settings
    m = settings.get("caption", "both")
    return m if m in CAPTIONS else "both"


def join(group, text, mode=None):
    """A measurement's caption: "Name: quantity", the quantity or the
    name, as Takeoff > Captions says."""
    mode = mode or caption_mode()
    if not group:
        return text
    if mode == "value":
        return text
    if mode == "name":
        return group
    return f"{group}: {text}"


def recaption(full, group, mode, quantity=None):
    """A caption `full` ("Name: quantity", or as another mode left it) in
    `mode`; `quantity` is the quantity text to use when the caption no
    longer has one (it shows the name only)."""
    if group and full.startswith(f"{group}: "):
        return join(group, full[len(group) + 2:], mode)
    if group and full == group:
        return join(group, quantity, mode) if quantity else full
    if group and mode in ("both", "name"):      # it shows the quantity only
        return join(group, full, mode)
    return full
