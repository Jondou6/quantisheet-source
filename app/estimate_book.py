"""AI Takeoff -> estimate workbook by CSI division.

The workbook an estimator prices from: a SUMMARY sheet (one row per
division, its cost and cost per SF), a BASE BID sheet (SR #, REF,
DESCRIPTION, QUANTITY, UNIT, WASTAGE, QUANTITY W/ WASTAGE, then labor,
material and equipment columns that work out the cost) and a UNITS &
WASTAGE sheet (the waste allowance per unit).

QuantiSheet fills in what the drawings say - description, sheet,
quantity and unit - and writes the formulas. Every rate cell (labor
hours, wages, material, equipment) and the markups are left blank for
the estimator: no price is ever filled in. Lines the AI found but could
not measure with confidence are listed in their division, shaded, with
the reason in the NOTES column - an estimator checks them; they are
never left out silently.

    collect(rows, res) -> [line]     lines from an AI Takeoff result
    write(path, lines, project=..., address=..., gsf=..., when=...)
"""
import datetime as _dt
import re

from . import csi
from .dmoney import c2 as _c2

ENGINE_OF = {"AI takeoff: rooms": "rooms", "AI takeoff: pipe runs": "pipes",
             "AI takeoff: civil": "civil", "AI takeoff: devices": "devices",
             "AI takeoff: schedules": "schedules",
             "AI takeoff: ducts": "ducts", "AI takeoff: steel": "steel",
             "AI takeoff: walls": "walls",
             "AI takeoff: finishes": "finishes"}
UNIT_OF = {"ea": "EA", "ft": "LF", "lf": "LF", "sf": "SF", "cy": "CY",
           "lb": "LBS", "lbs": "LBS", "sq ft": "SF", "sqft": "SF",
           "sq. ft.": "SF", "sy": "SY", "ls": "LS", "tons": "TONS",
           "sheets": "SHEETS", "rolls": "ROLLS"}
DISC_DIV = {"plumbing": "22", "mechanical": "23", "fire protection": "21",
            "electrical": "26", "fire alarm": "28", "telecom": "27",
            "civil": "33", "architectural": "09", "interiors": "09",
            "structural": "05", "landscape": "32"}
ENGINE_DIV = {"rooms": "09", "civil": "33", "walls": "09", "finishes": "09",
              "pipes": "22", "ducts": "23", "steel": "05", "roof": "07",
              "site": "32", "earthwork": "31", "slab": "03",
              "assembly": "09", "envelope": "07"}
# the waste allowance per unit (the estimator can change it in the sheet)
WASTE = [("EA", 0.0), ("LF", 0.1), ("SF", 0.1), ("SY", 0.1), ("LBS", 0.1),
         ("TONS", 0.1), ("CY", 0.1), ("LS", 0.0), ("SHEETS", 0.0),
         ("ROLLS", 0.0)]
HEAD = ["SR #", "REF", "DESCRIPTION", "QUANTITY", "UNIT", "WASTAGE",
        "QUANTITY W/ WASTAGE", "LABOR HOURS", "WAGES", "TOTAL LABOR HOUR",
        "TOTAL LABOR COST", "MATERIAL RATE", "TOTAL MATERIAL COST",
        "EQUIPMENT RATE", "TOTAL EQUIPMENT COSTS", "SUB COST", "",
        "NOTES"]
WIDTHS = [8.6, 13.5, 62, 10.6, 8.4, 10.6, 12.6, 10.6, 10.6, 13, 14, 10.6,
          12.5, 12.9, 13.6, 15.1, 4, 60]
FIRST_ROW = 11
_NOISE = re.compile(r"legend line not counted: (?:not a short device name|"
                    r"symbol is a plain)", re.I)


def _title(div):
    t = csi.DIVISIONS.get(div)
    if not t:
        return f"Division {div}"
    return " ".join(w if w in ("and", "of") else w[:1].upper() + w[1:]
                    for w in t.split())


# pipe system codes as the plumbing / HVAC engines name runs ('2" W')
PIPE_SYS = {"CW": "Cold water pipe", "HW": "Hot water pipe",
            "HWR": "Hot water return pipe", "W": "Waste pipe",
            "V": "Vent pipe", "VTR": "Vent through roof", "G": "Gas pipe",
            "SAN": "Sanitary pipe", "ST": "Storm pipe", "RL": "Rain leader",
            "CD": "Condensate drain", "RS": "Refrigerant suction",
            "RL/RS": "Refrigerant lines"}


def describe(name):
    """An engine's short name made readable for the estimate ('2" W' ->
    '2" Waste pipe'); other names unchanged."""
    m = re.match(r'^(\d+(?:[- ]\d/\d)?(?:/\d)?")\s+([A-Z/]{1,6})'
                 r'(\s+drops)?$', name or "")
    if m and m.group(2) in PIPE_SYS:
        return f"{m.group(1)} {PIPE_SYS[m.group(2)]}" + \
            (" (drops)" if m.group(3) else "")
    return name


def _spec_ref(code, sections):
    """'Spec 09 29 00 GYPSUM BOARD' for a line's CSI code ('09 21 16'):
    the project manual's section with the same number, else the one that
    shares its first four digits; '' when the manual has neither."""
    d = re.sub(r"\D", "", code or "")
    if len(d) < 4 or not sections:
        return ""
    keys = sorted(sections)
    hit = next((k for k in keys if re.sub(r"\D", "", k)[:6] == d[:6]), None) \
        or next((k for k in keys if re.sub(r"\D", "", k)[:4] == d[:4]), None)
    if not hit:
        return ""
    k = re.sub(r"\D", "", hit)
    return f"Spec {k[:2]} {k[2:4]} {k[4:6]} {sections[hit].title()}"


def _unit(u):
    u = str(u or "").strip()
    return UNIT_OF.get(u.lower(), u.upper() or "EA")


# review lines that repeat something already taken off (a device drawn on
# two plans, a key tagged on two sheets): their quantity is not added in
_ALREADY = re.compile(r"counted once|not counted twice|counted again|"
                      r"already (?:counted|in)|isn't added again|"
                      r"same key on|also tagged on|drawn again", re.I)


def collect(rows, res):
    """The AI Takeoff result as estimate lines: [{div, ref, description,
    qty, unit, status ('taken off' | 'review'), note}] - one per (name,
    unit, status), quantities added up over the sheets."""
    by_page = {r["page"]: r for r in rows or ()}

    def sheet_no(p):
        r = by_page.get(p) or {}
        return r.get("number") or f"p{p + 1}"
    lines = {}

    def add(engine, name, qty, unit, status, page, div=None, note="",
            sheet=None, csi_code=""):
        k = (name, unit, status)
        ln = lines.setdefault(k, {"description": name, "qty": 0.0,
                                  "unit": unit, "status": status,
                                  "refs": [], "divs": {}, "notes": [],
                                  "has_qty": False, "csi": ""})
        if csi_code and not ln["csi"]:
            ln["csi"] = csi_code
        if isinstance(qty, (int, float)):
            ln["qty"] += qty
            ln["has_qty"] = True
        s = sheet_no(page) if page is not None else (
            sheet if sheet and sheet != "set" else None)
        if s and s not in ln["refs"]:
            ln["refs"].append(s)
        d = div or DISC_DIV.get((by_page.get(page) or {}).get(
            "discipline")) or ENGINE_DIV.get(engine, "")
        if d:
            ln["divs"][d] = ln["divs"].get(d, 0) + 1
        if note and note not in ln["notes"]:
            ln["notes"].append(note)
    for p, _kind, pl in res.get("marks") or ():
        m = pl.get("measure") or {}
        if str(m.get("method") or "").endswith(" (review)"):
            continue            # in review: listed from res["review"] below
        eng = ENGINE_OF.get(m.get("method"), m.get("method") or "")
        typ = m.get("type")
        if typ == "count":
            qty, unit = 1.0, "EA"
        elif typ == "area":
            qty, unit = float(m.get("value") or 0), "SF"
        else:
            qty, unit = float(m.get("value") or 0), "LF"
        add(eng, m.get("group") or "Item", qty, unit, "taken off", p,
            (m.get("csi") or "")[:2] or None, csi_code=m.get("csi") or "")
    for x in res.get("quantities") or ():
        st = x.get("status") or "taken off"
        add(x.get("engine") or "", x["name"], x.get("qty"),
            _unit(x.get("unit")), "taken off" if st == "taken off" else
            "review", x.get("page"), (x.get("csi") or "")[:2] or None,
            "" if st == "taken off" else (x.get("basis") or ""),
            x.get("sheet"), csi_code=x.get("csi") or "")
    for x in res.get("review") or ():
        if x.get("line"):
            continue        # a quantity line above, already in as review
        eng = x.get("engine") or ""
        q = x.get("qty")
        if q is None and _NOISE.search(x.get("why") or ""):
            continue       # a legend line that isn't an item ('UL U419')
        why = x.get("why") or "check"
        if isinstance(q, (int, float)) and _ALREADY.search(why):
            # the same thing drawn again: kept for a look, never added in
            why = f"{q:g} more found here, not added - {why}"
            q = None
        add(eng, x["name"], q if isinstance(q, (int, float)) else None,
            _unit(x.get("unit") or ("EA" if eng in ("devices", "schedules")
                                    else "")), "review", x.get("page"),
            (x.get("csi") or "")[:2] or None, why,
            x.get("sheet"), csi_code=x.get("csi") or "")
    mats = res.get("materials") or {}
    out = []
    for ln in lines.values():
        div = max(ln["divs"], key=ln["divs"].get) if ln["divs"] else "01"
        raw = ln["description"]
        base = re.sub(r"\s+drops$", "", raw)
        mat = mats.get(raw) or mats.get(base)
        desc = describe(raw)
        if mat:
            desc = f"{desc} - {mat}"
        ref_sec = _spec_ref(ln["csi"], res.get("spec_sections") or {})
        if ref_sec and not mat:
            ln["notes"].append(ref_sec)
        out.append({"div": div, "ref": "/".join(ln["refs"][:4]),
                    "description": desc,
                    "qty": _c2(ln["qty"]) if ln["has_qty"] else None,
                    "unit": ln["unit"], "status": ln["status"],
                    "note": "; ".join(ln["notes"])[:400]})
    out.sort(key=lambda l: (l["div"], l["status"] != "taken off",
                            l["ref"], l["description"].lower()))
    return out


def _safe(v):
    """Text a spreadsheet won't run as a formula."""
    if isinstance(v, str) and v[:1] in ("=", "+", "-", "@") and \
            not re.match(r"^-?\d", v):
        return "'" + v
    return v


# Division 01 lines every job carries: listed once, 1 LS each, for the
# estimator to price or delete (they aren't taken off the drawings)
GENERAL = ["Supervision and coordination", "Submittals and shop drawings",
           "Temporary facilities and controls", "Mobilization",
           "Final cleaning", "Bonds", "Scaffolding and lifts"]


def general_lines():
    return [{"div": "01", "ref": "", "description": d, "qty": 1.0,
             "unit": "LS", "status": "taken off",
             "note": "general requirement - price it or delete the line"}
            for d in GENERAL]


def write(path, lines, project="", address="", gsf=None, when=None,
          general=True):
    """The estimate workbook at `path` (xlsx). Rates and markups blank.
    `general` adds the Division 01 lines (1 LS each, to price)."""
    if general and not any(l["div"] == "01" and l["unit"] == "LS"
                           for l in lines):
        lines = general_lines() + list(lines)
    import openpyxl
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter as col

    when = when or _dt.date.today()
    wb = openpyxl.Workbook()
    summ = wb.active
    summ.title = "SUMMARY"
    bid = wb.create_sheet("BASE BID")
    uw = wb.create_sheet("UNITS & WASTAGE")
    bold = Font(name="Arial", bold=True)
    norm = Font(name="Arial")
    head_fill = PatternFill("solid", fgColor="D9E1F2")
    div_fill = PatternFill("solid", fgColor="FCE4D6")
    input_fill = PatternFill("solid", fgColor="FFF2CC")
    review_fill = PatternFill("solid", fgColor="FFE699")
    thin = Side(style="thin", color="BFBFBF")
    box = Border(left=thin, right=thin, top=thin, bottom=thin)

    # ---- units & wastage
    uw["B2"], uw["C2"] = "Unit", "Wastage"
    for c in ("B2", "C2"):
        uw[c].font = bold
    for i, (u, w) in enumerate(WASTE):
        uw.cell(3 + i, 2, u)
        uw.cell(3 + i, 3, w).number_format = "0%"
        uw.cell(3 + i, 3).fill = input_fill
    uw.column_dimensions["B"].width = 12
    uw.column_dimensions["C"].width = 12
    last_w = 2 + len(WASTE)

    # ---- base bid
    bid["A3"], bid["B3"] = "Project:", "=SUMMARY!B2"
    bid["A5"], bid["B5"] = "Address:", "=SUMMARY!B4"
    bid["A7"], bid["B7"] = "Scope:", "Quantities from AI Takeoff"
    bid["A9"], bid["B9"] = "Date:", "=SUMMARY!B10"
    bid["B9"].number_format = "yyyy-mm-dd"
    for i, h in enumerate(HEAD):
        c = bid.cell(10, i + 1, h or None)
        c.font = bold
        c.fill = head_fill
        c.alignment = Alignment(wrap_text=True, vertical="center",
                                horizontal="center")
        c.border = box
    for i, w in enumerate(WIDTHS):
        bid.column_dimensions[col(i + 1)].width = w
    bid.freeze_panes = "D11"
    r = FIRST_ROW
    subtotal = {}
    seq = 0
    by_div = {}
    for ln in lines:
        by_div.setdefault(ln["div"], []).append(ln)
    for div in sorted(by_div):
        title = csi.DIVISIONS.get(div, f"Division {div}").upper()
        c = bid.cell(r, 7, f"{div}. {title}")
        c.font = bold
        for k in range(1, 17):
            bid.cell(r, k).fill = div_fill
        r += 1
        first = r
        for ln in by_div[div]:
            rv = ln["status"] != "taken off"
            seq += 1
            bid.cell(r, 1, seq)
            bid.cell(r, 2, _safe(ln["ref"]) or None)
            bid.cell(r, 3, _safe(ln["description"]))
            if ln["qty"] is not None:
                bid.cell(r, 4, ln["qty"]).number_format = "#,##0.00"
            bid.cell(r, 5, ln["unit"])
            bid.cell(r, 6, f"=IFERROR(VLOOKUP(E{r},'UNITS & WASTAGE'!"
                           f"$B$3:$C${last_w},2,0),0)").number_format = "0%"
            bid.cell(r, 7, f'=IF(D{r}="","",(F{r}*D{r})+D{r})')
            bid.cell(r, 7).number_format = "#,##0.00"
            bid.cell(r, 10, f'=IF(G{r}="","",H{r}*G{r})')
            bid.cell(r, 11, f'=IF(J{r}="","",I{r}*J{r})')
            bid.cell(r, 13, f'=IF(G{r}="","",L{r}*G{r})')
            bid.cell(r, 15, f'=IF(G{r}="","",N{r}*G{r})')
            bid.cell(r, 16, f'=IF(D{r}="","",N(K{r})+N(M{r})+N(O{r}))')
            for k in (8, 9, 12, 14):
                bid.cell(r, k).fill = input_fill
            for k in (11, 13, 15, 16, 9, 12, 14):
                bid.cell(r, k).number_format = '#,##0.00'
            if rv:
                for k in (1, 2, 3, 4, 5, 6, 7):
                    bid.cell(r, k).fill = review_fill
                bid.cell(r, 18, _safe("CHECK - " + (ln.get("note") or
                                                    "found, not measured")))
            elif ln.get("note"):
                bid.cell(r, 18, _safe(ln["note"]))
            for k in range(1, 17):
                bid.cell(r, k).font = norm
                bid.cell(r, k).border = box
            r += 1
        bid.cell(r, 15, "SUBTOTAL").font = bold
        bid.cell(r, 16, f"=SUM(P{first}:P{r - 1})").font = bold
        bid.cell(r, 16).number_format = "#,##0.00"
        subtotal[div] = f"'BASE BID'!P{r}"
        r += 2
    sub_cells = ",".join(f"P{v.split('!P')[1]}" for v in subtotal.values())
    proj = r
    bid.cell(proj, 1, "PROJECTED COST").font = bold
    bid.cell(proj, 16, f"=SUM({sub_cells})" if sub_cells else 0).font = bold
    for i, nm in enumerate(("OVERHEAD AND PROFIT", "INSURANCE",
                            "CONTINGENCY")):
        rr = proj + 1 + i
        bid.cell(rr, 1, nm).font = bold
        bid.cell(rr, 15).fill = input_fill
        bid.cell(rr, 15).number_format = "0.0%"
        bid.cell(rr, 16, f"=$P${proj}*N(O{rr})")
    bid.cell(proj + 4, 1, "SUGGESTED BID").font = bold
    bid.cell(proj + 4, 16, f"=SUM(P{proj}:P{proj + 3})").font = bold
    for rr in range(proj, proj + 5):
        bid.cell(rr, 16).number_format = "#,##0.00"
    n = proj + 6
    notes = [
        "NOTES:",
        "Quantities and descriptions come from QuantiSheet AI Takeoff of the "
        "drawings; REF is the sheet each was taken from.",
        "Shaded lines were found but not measured with confidence - check "
        "them (the reason is in NOTES) before pricing.",
        "Yellow cells are for the estimator: labor hours, wages, material "
        "and equipment rates, markups. No prices are filled in.",
        "LBS = Pound, SF = Square Feet, LF = Linear Feet, EA = Each, CY = "
        "Cubic Yard, SY = Square Yard, LS = Lump Sum"]
    for i, t in enumerate(notes):
        bid.cell(n + i, 2 if i else 1, t).font = bold if not i else norm

    # ---- summary
    summ["A2"], summ["B2"] = "Project ID:", _safe(project or "")
    summ["A4"], summ["B4"] = "Project Address:", _safe(address or "")
    summ["A6"] = "No. of Floors:"
    summ["A8"], summ["B8"] = "Building GSF", gsf if gsf else None
    summ["A10"], summ["B10"] = "Date", when
    summ["B10"].number_format = "yyyy-mm-dd"
    for c in ("B2", "B4", "B6", "B8"):
        summ[c].fill = input_fill
    for i, h in enumerate(("DIVISION NO.", "DESCRIPTION", "TOTAL DIV. COST",
                           "TOTAL DIV. COST (PER SF)")):
        c = summ.cell(12, i + 1, h)
        c.font = bold
        c.fill = head_fill
        c.border = box
    rr = 13
    for div in sorted(subtotal):
        summ.cell(rr, 1, div)
        summ.cell(rr, 2, _title(div))
        summ.cell(rr, 3, f"={subtotal[div]}").number_format = "#,##0.00"
        summ.cell(rr, 4, f'=IF(N($B$8)=0,"",C{rr}/$B$8)')
        summ.cell(rr, 4).number_format = "#,##0.00"
        rr += 1
    tot = rr
    summ.cell(tot, 1, "PROJECTED COST").font = bold
    summ.cell(tot, 3, f"=SUM(C13:C{tot - 1})" if tot > 13 else 0)
    summ.cell(tot, 4, f'=IF(N($B$8)=0,"",C{tot}/$B$8)')
    for i, nm in enumerate(("OVERHEAD AND PROFIT", "INSURANCE",
                            "CONTINGENCY")):
        k = tot + 2 + i
        summ.cell(k, 1, nm)
        summ.cell(k, 2).fill = input_fill
        summ.cell(k, 2).number_format = "0.0%"
        summ.cell(k, 3, f"=$C${tot}*N(B{k})")
    summ.cell(tot + 5, 1, "SUGGESTED BASE BID").font = bold
    summ.cell(tot + 5, 3, f"=C{tot}+SUM(C{tot + 2}:C{tot + 4})")
    for k in range(tot, tot + 6):
        summ.cell(k, 3).number_format = "#,##0.00"
    summ.column_dimensions["A"].width = 24
    summ.column_dimensions["B"].width = 48
    summ.column_dimensions["C"].width = 18
    summ.column_dimensions["D"].width = 22
    wb.save(path)
    return {"lines": len(lines), "divisions": len(subtotal),
            "review": sum(1 for l in lines if l["status"] != "taken off")}
