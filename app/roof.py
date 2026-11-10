"""Roof plan takeoff: the math for facets, linework and counts drawn by
the user on scaled plan sheets (roof plans and elevations).

Plans only. Nothing here reads images or any aerial data: the user draws
every facet and line and types the pitch; this module only adjusts the
measured plan quantities for slope and adds the derived rows (wall
flashing, membrane total, squares with and without waste, curb perimeter).

A roof item is a takeoff item (annotate.takeoff_items) with a "roof"
dict: {"type", "pitch" ("6" or "6,8"), "run", "sheet", "parapet_in",
"curb" ("4x6" ft), "membrane"}. apply() turns its plan value into the
true value; a missing or bad pitch is flagged "check pitch" and the plan
value is kept (never an assumed 4/12).
"""
import csv
import math
import re
from fractions import Fraction
from .dmoney import c2 as _c2

ROOF_TYPES = ["facet", "lowslope", "ridge", "hip", "valley", "eave", "rake",
              "drip", "step", "headwall", "parapet", "drain", "scupper",
              "curb", "rtu", "boot", "vent"]
AREA_TYPES = ("facet", "lowslope")
LINE_TYPES = ("ridge", "hip", "valley", "eave", "rake", "drip", "step",
              "headwall", "parapet")
COUNT_TYPES = ("drain", "scupper", "curb", "rtu", "boot", "vent")
RUNS = ("level", "slope", "hipvalley")
SHEETS = ("plan", "elevation")
MEMBRANES = ("TPO", "EPDM", "mod-bit", "BUR", "metal", "other")

DEFAULT_RUN = {"ridge": "level", "eave": "level", "parapet": "level",
               "headwall": "level", "curb": "level", "rake": "slope",
               "step": "slope", "drip": "slope", "hip": "hipvalley",
               "valley": "hipvalley"}

# (r, g, b) 0-1; headwall is drawn dashed (DASHED)
DEFAULT_COLORS = {"ridge": (1, 0, 0), "hip": (1, 0.5, 0),
                  "valley": (0, 0, 1), "eave": (0, 0.6, 0),
                  "rake": (0.5, 0, 0.5), "drip": (0, 0.5, 0.5),
                  "step": (0.6, 0.3, 0), "headwall": (0.6, 0.3, 0),
                  "parapet": (0.3, 0.3, 0.3)}
DASHED = ("headwall",)

NAMES = {"facet": "Roof", "lowslope": "Low slope", "ridge": "Ridge",
         "hip": "Hip", "valley": "Valley", "eave": "Eave", "rake": "Rake",
         "drip": "Drip edge", "step": "Step flashing",
         "headwall": "Headwall flashing", "parapet": "Parapet",
         "drain": "Drain", "scupper": "Scupper", "curb": "Curb",
         "rtu": "RTU", "boot": "Pipe boot", "vent": "Vent"}

# 12:12 is the hard cap everywhere (owner's rule): a steeper pitch is out
# of range and flagged, never used
MAX_PITCH = 12.0
CHECK = "check pitch"
PLANS_ONLY = "Roof takeoff works on scaled plan sheets only."


# ------------------------------------------------------------- factors
def slope_factor(rise):
    """Sloped length (or area) per plan foot at rise/12."""
    from . import tradetakeoff      # late: tradetakeoff needs fitz
    return tradetakeoff.slope_factor(rise)


def hip_valley_factor(r1, r2=None):
    """True length per plan foot of a hip or valley between pitches r1/12
    and r2/12 (r2 = r1 if not given)."""
    a = float(r1) / 12.0
    b = (float(r2) if r2 is not None else float(r1)) / 12.0
    if a == 0 or b == 0:
        return 1.0
    return math.sqrt(1 + (a * b) ** 2 / (a * a + b * b))


# --------------------------------------------------------------- pitch
def _num(s):
    """'6', '0.25', '1/4' or '1 1/2' as a float, else None."""
    s = s.strip()
    m = re.fullmatch(r"(\d+)\s+(\d+)\s*/\s*(\d+)", s)
    if m:
        d = int(m.group(3))
        return int(m.group(1)) + int(m.group(2)) / d if d else None
    m = re.fullmatch(r"(\d*\.?\d+)\s*/\s*(\d*\.?\d+)", s)
    if m:
        d = float(m.group(2))
        return float(m.group(1)) / d if d else None
    try:
        return float(s)
    except ValueError:
        return None


def parse_pitch(text):
    """Rise in 12 from '6', '6/12', '6:12', '6 in 12', '0.25', '1/4'
    or '1/4:12'. None if not a number or outside 0-12 (MAX_PITCH)."""
    if text is None or isinstance(text, bool):
        return None
    if isinstance(text, (int, float)):
        r = float(text)
    else:
        s = str(text).strip().lower().replace('"', "")
        m = re.fullmatch(r"(.+?)\s*(?::|/|in)\s*12", s)
        s = m.group(1) if m else s
        r = _num(s) if s else None
    if r is None or not math.isfinite(r) or not 0 <= r <= MAX_PITCH:
        return None
    return r


def parse_pitch2(text):
    """Both sides of a hip/valley: '6,8' -> (6.0, 8.0); '6' -> (6.0,
    6.0). None if either side is bad."""
    if text is None:
        return None
    parts = [p for p in re.split(r"[,;&]", str(text)) if p.strip()]
    if not 1 <= len(parts) <= 2:
        return None
    p = [parse_pitch(x) for x in parts]
    if None in p:
        return None
    return (p[0], p[-1])


def rise_text(r):
    """6 -> '6', 0.25 -> '1/4'."""
    if r == int(r):
        return str(int(r))
    f = Fraction(r).limit_denominator(16)
    if abs(float(f) - r) < 1e-9:
        w, n = divmod(f.numerator, f.denominator)
        return f"{w} {n}/{f.denominator}" if w else f"{n}/{f.denominator}"
    return f"{r:g}"


def pitch_text(roof):
    """'6/12', '1/4:12', '6/12 & 8/12', or '' if unpitched."""
    roof = roof or {}
    if run_of(roof) == "hipvalley" and roof.get("type") in ("hip",
                                                           "valley"):
        p = parse_pitch2(roof.get("pitch"))
        if not p:
            return ""
        a, b = (_one_pitch(x) for x in p)
        return a if a == b else f"{a} & {b}"
    p = parse_pitch(_first(roof.get("pitch")))
    return "" if p is None else _one_pitch(p)


def _one_pitch(r):
    t = rise_text(r)
    return f"{t}/12" if r == int(r) else f"{t}:12"


def _first(pitch):
    if pitch is None:
        return None
    return re.split(r"[,;&]", str(pitch))[0]


# -------------------------------------------------------------- items
def run_of(roof):
    """How the line runs: the roof's own run, else the type's default."""
    run = (roof or {}).get("run")
    if run in RUNS:
        return run
    return DEFAULT_RUN.get((roof or {}).get("type"), "level")


def factor_for(roof):
    """Plan-to-true factor for a roof dict, or None if a needed pitch is
    missing or bad (the caller flags 'check pitch')."""
    roof = roof or {}
    t = roof.get("type")
    if t in COUNT_TYPES or t not in ROOF_TYPES:
        return 1.0
    if roof.get("sheet") == "elevation":
        return 1.0
    if t in AREA_TYPES:
        p = parse_pitch(_first(roof.get("pitch")))
        return None if p is None else slope_factor(p)
    run = run_of(roof)
    if run == "level":
        return 1.0
    if run == "slope":
        p = parse_pitch(_first(roof.get("pitch")))
        return None if p is None else slope_factor(p)
    p = parse_pitch2(roof.get("pitch"))
    return None if p is None else hip_valley_factor(*p)


def apply(item, roof):
    """A new copy of takeoff `item` (value already net of cutouts and
    times its multiplier) with plan_value, factor, value = plan x factor
    and roof. Unpitched: factor None, value = plan, check 'check pitch'."""
    it = dict(item)
    roof = dict(roof or {})
    plan = float(it.get("value") or 0.0)
    f = factor_for(roof)
    it["plan_value"] = plan
    it["factor"] = f
    it["roof"] = roof
    if f is None:
        it["check"] = CHECK
        it["value"] = plan
        return it
    it.pop("check", None)
    it["value"] = plan * f
    for k in ("unit_value", "gross"):
        if isinstance(it.get(k), (int, float)):
            it[k] = it[k] * f
    return it


def roof_items(items, page=None):
    """The items that carry roof data (optionally on one page)."""
    return [it for it in items if isinstance(it.get("roof"), dict)
            and (page is None or it.get("page") == page)]


def name_of(item):
    """Display name: 'Roof 6/12', 'Low slope 1/4:12', 'Ridge', ..."""
    roof = item.get("roof") or {}
    t = roof.get("type")
    base = NAMES.get(t, str(t or "").title())
    if t in AREA_TYPES:
        p = pitch_text(roof)
        base = f"{base} {p}" if p else f"{base} (check pitch)"
        if t == "lowslope" and roof.get("membrane"):
            base += f" {roof['membrane']}"
    return base


# ------------------------------------------------------- squares, waste
def squares(sloped_sf):
    """Roofing squares (100 sq ft), no waste."""
    return float(sloped_sf) / 100.0


def with_waste(qty, pct):
    """qty plus pct percent waste (pct 10 = 10%)."""
    return float(qty) * (1 + float(pct or 0) / 100.0)


def _curb_size(text):
    """'4x6' ft -> (4.0, 6.0), else None."""
    m = re.fullmatch(r"\s*(\d*\.?\d+)\s*[x×*]\s*(\d*\.?\d+)\s*",
                     str(text or "").lower())
    if not m:
        return None
    return float(m.group(1)), float(m.group(2))


def _unit(items, types, default):
    for it in items:
        if (it.get("roof") or {}).get("type") in types and it.get("unit"):
            return it["unit"]
    return default


def _sum(items, types):
    return sum(it["value"] for it in items
               if (it.get("roof") or {}).get("type") in types)


def derived_items(items, waste_pct=None, parapet_default_in=None):
    """Computed rows from applied roof items, per page: parapet wall
    flashing, low-slope membrane total (and with waste), squares and
    squares with waste (two rows), curb perimeter. Each row is {name,
    value, quantity, unit, type: 'roof', page, group, how}."""
    out = []
    w = float(waste_pct or 0)
    pages = sorted({it.get("page", 0) for it in roof_items(items)})
    for pno in pages:
        its = roof_items(items, pno)
        area_u = _unit(its, AREA_TYPES, "sq ft")
        len_u = _unit(its, LINE_TYPES, "ft")

        def row(name, value, unit, how):
            out.append({"name": name, "value": value, "quantity": value,
                        "unit": unit, "type": "roof", "page": pno,
                        "group": "Roof", "how": how})

        flash = 0.0
        for it in its:
            r = it["roof"]
            if r.get("type") != "parapet":
                continue
            h = r.get("parapet_in", parapet_default_in)
            try:
                h = float(h)
            except (TypeError, ValueError):
                continue
            if math.isfinite(h) and h > 0:
                flash += it["value"] * h / 12.0
        if flash:
            row("Parapet wall flashing", flash, area_u,
                "parapet LF x wall height / 12")
        field = _sum(its, ("lowslope",))
        membrane = field + flash if field else 0.0
        if membrane:
            row("Low-slope membrane total", membrane, area_u,
                "low-slope field (sloped) + wall flashing")
            if w:
                row(f"Low-slope membrane with {w:g}% waste",
                    with_waste(membrane, w), area_u,
                    "membrane total x (1 + waste)")
        roof_sf = _sum(its, ("facet",)) + membrane
        if roof_sf:
            row("Roof squares (no waste)", squares(roof_sf), "sq",
                "sloped roof SF / 100")
            row(f"Roof squares with {w:g}% waste",
                squares(with_waste(roof_sf, w)), "sq",
                "sloped roof SF x (1 + waste) / 100")
        perim = 0.0
        for it in its:
            r = it["roof"]
            if r.get("type") not in ("curb", "rtu"):
                continue
            size = _curb_size(r.get("curb"))
            if size:
                perim += 2 * (size[0] + size[1]) * (it["value"] or 0)
        if perim:
            row("Curb perimeter", perim, len_u,
                "2 x (W + L) per curb / RTU")
    return out


# ------------------------------------------------------------- summary
HEADERS = ["Page", "Group", "Item", "Plan qty", "Pitch", "Factor",
           "True qty", "Unit", "Waste %", "With waste", "Squares"]


def _waste_for(waste, group):
    if isinstance(waste, dict):
        return float(waste.get(group, waste.get("", 0)) or 0)
    return float(waste or 0)


def summary_rows(items, waste=None, page_labels=None):
    """Rows for the roof summary table (lists of HEADERS values), by page
    -> group, with totals per group and for all, then the checks, counts
    and derived rows. `waste` is a percent, or {group: percent}; it
    applies to area items only. Numbers are floats ('' where blank)."""
    labels = page_labels or {}
    its = roof_items(items)
    agg = {}
    for it in its:
        r = it["roof"]
        f = it.get("factor")
        k = (it.get("page", 0), it.get("group") or "", name_of(it),
             pitch_text(r), None if f is None else round(f, 6),
             it.get("unit", ""))
        a = agg.setdefault(k, {"plan": 0.0, "true": 0.0,
                               "area": r.get("type") in AREA_TYPES})
        a["plan"] += it.get("plan_value", it["value"])
        a["true"] += it["value"]
    out, tot, last = [], {}, None
    for k in sorted(agg, key=lambda k: (k[0], k[1], k[2], k[5])):
        pno, group, name, pitch, f, unit = k
        if last is not None and last != (pno, group):
            out += _total_rows(tot, last, labels)
        last = (pno, group)
        a = agg[k]
        plab = labels.get(pno, str(pno + 1))
        w = _waste_for(waste, group) if a["area"] else ""
        ww = with_waste(a["true"], w) if a["area"] else ""
        sq = squares(a["true"]) if a["area"] else ""
        out.append([plab, group, name, a["plan"],
                    pitch or (CHECK if f is None else ""),
                    CHECK if f is None else f, a["true"], unit, w, ww, sq])
        for key in ((pno, group, unit), ("All", "", unit)):
            t = tot.setdefault(key, [0.0, 0.0, 0.0, 0.0, False])
            t[0] += a["plan"]
            t[1] += a["true"]
            if a["area"]:
                t[2] += ww
                t[3] += sq
                t[4] = True
    if last is not None:
        out += _total_rows(tot, last, labels)
        out += _total_rows(tot, ("All", ""), labels)
    out += _checks(its, labels)
    for d in derived_items(its, _waste_for(waste, "")):
        out.append([labels.get(d["page"], str(d["page"] + 1)), "Derived",
                    d["name"], "", "", "", d["value"], d["unit"],
                    "", "", ""])
    return out


def _total_rows(tot, g, labels):
    out = []
    for (p, grp, unit), t in sorted(tot.items(), key=lambda x: x[0][2]):
        if (p, grp) != g:
            continue
        name = "Total, all pages" if p == "All" else \
            f"Total {grp}".strip()
        plab = p if p == "All" else labels.get(p, str(p + 1))
        out.append([plab, grp, name, t[0], "", "", t[1], unit,
                    "", t[2] if t[4] else "", t[3] if t[4] else ""])
    return out


def _checks(its, labels):
    """Drip edge drawn vs eave + rake, and every count, per page."""
    out = []
    for pno in sorted({it.get("page", 0) for it in its}):
        p = [it for it in its if it.get("page", 0) == pno]
        lab = labels.get(pno, str(pno + 1))
        u = _unit(p, LINE_TYPES, "ft")
        drip, er = _sum(p, ("drip",)), _sum(p, ("eave", "rake"))
        if drip or er:
            out.append([lab, "Check", "Drip edge drawn", "", "",
                        "", drip, u, "", "", ""])
            out.append([lab, "Check", "Eave + rake", "", "", "",
                        er, u, "", "", ""])
        for t in COUNT_TYPES:
            n = _sum(p, (t,))
            if n:
                out.append([lab, "Count", NAMES[t], "", "", "",
                            n, "ea", "", "", ""])
        curbs = _sum(p, ("curb", "rtu"))
        if curbs and _sum(p, ("rtu",)):
            out.append([lab, "Count", "Curbs (incl. RTU)", "", "",
                        "", curbs, "ea", "", "", ""])
    return out


def export_summary(path, rows):
    """Write the summary to .xlsx (openpyxl) or CSV (UTF-8 BOM, CRLF)."""
    table = [HEADERS] + [list(r) for r in rows]
    if path.lower().endswith(".xlsx"):
        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Roof Summary"
        from . import safecell
        for row in table:
            safecell.append_row(ws, row)    # page labels, names: text
        for row in ws.iter_rows(min_row=2):
            for c in row[3:]:
                if isinstance(c.value, float):
                    c.number_format = "#,##0.00" if c.column != 6 \
                        else "0.0000"
        wb.save(path)
    else:
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            from . import safecell
            w = safecell.writer(f, lineterminator="\r\n")
            for i, row in enumerate(table):
                w.writerow([_cell(v, j) if i else v
                            for j, v in enumerate(row)])
    return path


def _cell(v, col):
    if isinstance(v, float):
        return f"{v:.4f}" if col == 5 else f"{_c2(v):.2f}"
    return v
