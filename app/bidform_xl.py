"""Bid form workbook and calculating bid form PDF (Nov 4, Jon).

From the owner's bid form (the BID FORM / PROPOSAL FORM / BID SCHEDULE
pages of the project manual, or of an addendum):

* parse(): the schedule's items (number, description, quantity, unit),
  the alternates and the addenda to acknowledge.
* workbook(): an Excel file for the estimator - yellow cells for the unit
  prices, lump sums and alternate amounts; Excel formulas for every line
  total (quantity x unit price), the subtotal, each alternate (added or
  taken off) and the base bid.
* read_workbook() + totals(): the amounts typed in it, worked out the same
  way in QuantiSheet (so nothing depends on Excel having saved its
  results).
* fill_pdf(): the bid form pages plus a "Bid Schedule" page of form fields
  whose totals calculate as they're typed (PDF form calculations), filled
  from the workbook in one click, the amount in words included; owner
  forms that already have fields get them filled too (bidform_auto).
* compare(): an addendum's bid form against the one the workbook was made
  from - items added, removed or with a new quantity, so every addendum
  review says whether the bid form changed.
"""
import datetime
import os
import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

UNITS = (r"LS|L\.S\.|LUMP\s+SUM|EA|EACH|LF|L\.F\.|SF|S\.F\.|SY|S\.Y\.|CY|"
         r"C\.Y\.|TON|TONS|HR|HRS|GAL|AC|ACRE|VF|VLF|DAY|DAYS|MO|LB|CF|MSF|"
         r"ALLOW|ALLOWANCE")
HEAD = re.compile(r"\b(bid\s+form|proposal\s+form|form\s+of\s+(?:bid|"
                  r"proposal)|bid\s+schedule|schedule\s+of\s+(?:bid\s+)?"
                  r"(?:items|prices)|unit\s+price\s+schedule)\b", re.I)
REVISED = re.compile(r"\b(revised|replace(?:ment|s)?|substitute|new)\b[^.\n]"
                     r"{0,40}\b(bid\s+form|proposal\s+form|bid\s+schedule)\b",
                     re.I)
ITEM = re.compile(rf"^\s*(\d{{1,3}}[A-Z]?)[.)]?\s+(.{{3,120}}?)\s+"
                  rf"([\d,]+(?:\.\d+)?)\s+({UNITS})\b", re.I)
LUMP = re.compile(rf"^\s*(\d{{1,3}}[A-Z]?)[.)]?\s+(.{{3,120}}?)\s+"
                  rf"(?:\(?\s*({UNITS})\s*\)?)\s*(?:\$|_|$)", re.I)
ALT = re.compile(r"^\s*(?:add(?:itive)?|deduct(?:ive)?)?\s*alternate\s*"
                 r"(?:no\.?\s*)?#?\s*(\d{1,2})\s*[:.\-)]?\s*(.{0,140})$", re.I)
ADD_ACK = re.compile(r"addend(?:um|a)\s*(?:no\.?\s*)?#?\s*(\d{1,2})", re.I)
CENT = Decimal("0.01")


class BidFormError(Exception):
    pass


def _d(v):
    s = str(v if v is not None else "").replace("$", "").replace(",", "")
    s = s.strip()
    if not s:
        return None
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def _unit(u):
    u = re.sub(r"[.\s]", "", u.upper())
    return {"LUMPSUM": "LS", "EACH": "EA", "ACRE": "AC",
            "ALLOWANCE": "ALLOW"}.get(u, u)


# ---- finding and reading the form -------------------------------------------------

def form_pages(doc, sections=None):
    """Pages of the bid form: its spec section (00 41 xx, or a section
    titled Bid Form / Proposal Form), else pages headed like one."""
    out = []
    for s in sections or []:
        if HEAD.search(s.get("title", "")) or \
                str(s.get("number", "")).startswith("00 41"):
            out += list(range(s["start"], s["end"] + 1))
    if not out:
        for i in range(doc.page_count):
            top = "\n".join(doc[i].get_text("text").splitlines()[:12])
            if HEAD.search(top):
                out.append(i)
    return sorted(set(out))


def parse(texts):
    """{"items": [{"no", "desc", "qty", "unit"}], "alternates": [{"no",
    "desc", "kind": "add"|"deduct"}], "addenda": [n...]} from the form's
    page texts."""
    items, alts, adds, seen = [], [], set(), set()
    for t in texts:
        for raw in str(t or "").splitlines():
            ln = " ".join(raw.replace("–", "-").split())
            if not ln:
                continue
            for m in ADD_ACK.finditer(ln):
                adds.add(int(m.group(1)))
            m = ALT.match(ln)
            if m:
                no = m.group(1)
                if no not in {a["no"] for a in alts}:
                    kind = "deduct" if re.search(r"deduct", ln, re.I) \
                        else "add"
                    desc = re.sub(r"[\s_$.]+$", "", m.group(2)).strip()
                    alts.append({"no": no, "desc": desc, "kind": kind})
                continue
            m = ITEM.match(ln)
            if m and m.group(1) not in seen:
                q = _d(m.group(3))
                if q is not None and q > 0:
                    seen.add(m.group(1))
                    items.append({"no": m.group(1), "desc": m.group(2)
                                  .strip(" .:-_"), "qty": q,
                                  "unit": _unit(m.group(4))})
                continue
            m = LUMP.match(ln)
            if m and m.group(1) not in seen:
                seen.add(m.group(1))
                items.append({"no": m.group(1), "desc": m.group(2)
                              .strip(" .:-_"), "qty": Decimal(1),
                              "unit": _unit(m.group(3))})
    return {"items": items, "alternates": alts, "addenda": sorted(adds)}


def read_form(doc, sections=None):
    pages = form_pages(doc, sections)
    parsed = parse([doc[i].get_text("text") for i in pages])
    parsed["pages"] = pages
    return parsed


# ---- the Excel workbook -------------------------------------------------------------

FIRST = 7                     # first item row in the workbook


def workbook(form, path, project="", addenda_ack=()):
    """The estimator's workbook. Returns path. Yellow cells are typed;
    everything else is a formula."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.worksheet.datavalidation import DataValidation
    wb = Workbook()
    ws = wb.active
    ws.title = "Bid Form"
    f = "Arial"
    bold = Font(name=f, bold=True)
    norm = Font(name=f)
    blue = Font(name=f, color="0000FF")
    yellow = PatternFill("solid", fgColor="FFFF00")
    thin = Side(style="thin", color="BFBFBF")
    box = Border(top=thin, bottom=thin, left=thin, right=thin)
    ws["A1"] = f"Bid Form - {project}".strip(" -")
    ws["A1"].font = Font(name=f, bold=True, size=14)
    ws["A2"] = ("Type the yellow cells only (blue text). Line totals, the "
                "subtotal, the alternates and the base bid are formulas. "
                "Then QuantiSheet > Bid Form Workbook > Transfer to PDF.")
    ws["A2"].font = Font(name=f, italic=True, size=9)
    ws["A3"] = "Made"
    ws["B3"] = datetime.date.today().isoformat()
    ws["A3"].font = ws["B3"].font = norm
    heads = ["Item", "Description", "Quantity", "Unit", "Unit Price",
             "Line Total"]
    for c, h in enumerate(heads, 1):
        cell = ws.cell(row=FIRST - 1, column=c, value=h)
        cell.font = bold
        cell.border = box
    r = FIRST
    for it in form["items"]:
        ws.cell(row=r, column=1, value=it["no"]).font = norm
        ws.cell(row=r, column=2, value=it["desc"]).font = norm
        q = ws.cell(row=r, column=3, value=float(it["qty"]))
        q.font = norm
        q.number_format = "#,##0.00"
        ws.cell(row=r, column=4, value=it["unit"]).font = norm
        p = ws.cell(row=r, column=5)
        p.fill, p.font, p.number_format = yellow, blue, "$#,##0.00"
        t = ws.cell(row=r, column=6, value=f"=ROUND(C{r}*E{r},2)")
        t.font, t.number_format = norm, "$#,##0.00"
        for c in range(1, 7):
            ws.cell(row=r, column=c).border = box
        r += 1
    last = r - 1
    sub = r
    ws.cell(row=sub, column=5, value="Subtotal").font = bold
    s = ws.cell(row=sub, column=6, value=f"=SUM(F{FIRST}:F{last})"
                if last >= FIRST else 0)
    s.font, s.number_format = bold, "$#,##0.00"
    r = sub + 2
    ws.cell(row=r, column=1, value="Alternates").font = bold
    r += 1
    for c, h in enumerate(["No.", "Description", "Add / Deduct",
                           "", "Amount", "Changes the bid by"], 1):
        if h:
            ws.cell(row=r, column=c, value=h).font = bold
    r += 1
    alt_first = r
    dv = DataValidation(type="list", formula1='"Add,Deduct"',
                        allow_blank=False)
    ws.add_data_validation(dv)
    for a in form["alternates"]:
        ws.cell(row=r, column=1, value=a["no"]).font = norm
        ws.cell(row=r, column=2, value=a["desc"]).font = norm
        k = ws.cell(row=r, column=3, value="Deduct" if a["kind"] ==
                    "deduct" else "Add")
        k.font, k.fill = blue, yellow
        dv.add(k)
        amt = ws.cell(row=r, column=5)
        amt.fill, amt.font, amt.number_format = yellow, blue, "$#,##0.00"
        e = ws.cell(row=r, column=6,
                    value=f'=IF(C{r}="Deduct",-E{r},E{r})')
        e.font, e.number_format = norm, "$#,##0.00"
        r += 1
    alt_last = r - 1
    r += 1
    ws.cell(row=r, column=5, value="BASE BID").font = Font(name=f, bold=True,
                                                           size=12)
    b = ws.cell(row=r, column=6, value=f"=F{sub}")
    b.font, b.number_format = Font(name=f, bold=True, size=12), "$#,##0.00"
    base_row = r
    r += 1
    if form["alternates"]:
        ws.cell(row=r, column=5, value="Base bid with all alternates").font \
            = bold
        w = ws.cell(row=r, column=6, value=f"=F{base_row}+SUM(F{alt_first}:"
                                           f"F{alt_last})")
        w.font, w.number_format = bold, "$#,##0.00"
        r += 1
    r += 1
    ws.cell(row=r, column=1, value="Addenda acknowledged").font = bold
    acks = sorted(set(form.get("addenda") or []) | set(addenda_ack))
    ws.cell(row=r, column=2, value=", ".join(f"No. {n}" for n in acks) or
            "(none listed)").font = norm
    ws.column_dimensions["A"].width = 8
    ws.column_dimensions["B"].width = 46
    for col in "CDEF":
        ws.column_dimensions[col].width = 16
    ws["B2"].alignment = Alignment(wrap_text=False)
    # where things are, for read_workbook
    meta = wb.create_sheet("QuantiSheet")
    meta.sheet_state = "hidden"
    for k, v in (("first", FIRST), ("last", last), ("sub", sub),
                 ("alt_first", alt_first), ("alt_last", alt_last),
                 ("base", base_row)):
        meta.append([k, v])
    wb.save(path)
    return path


def read_workbook(path):
    """The amounts typed in the workbook: {"items": [{no, desc, qty,
    unit, price}], "alternates": [{no, desc, kind, amount}]}."""
    from openpyxl import load_workbook
    wb = load_workbook(path, data_only=False)
    if "Bid Form" not in wb.sheetnames:
        raise BidFormError("That workbook isn't a QuantiSheet bid form.")
    ws = wb["Bid Form"]
    meta = {}
    if "QuantiSheet" in wb.sheetnames:
        meta = {r[0]: int(r[1]) for r in wb["QuantiSheet"].iter_rows(
            values_only=True) if r and r[0]}
    first, last = meta.get("first", FIRST), meta.get("last", 0)
    items = []
    for r in range(first, last + 1):
        no = ws.cell(row=r, column=1).value
        if no in (None, ""):
            continue
        items.append({"no": str(no), "desc": ws.cell(row=r, column=2).value,
                      "qty": _d(ws.cell(row=r, column=3).value) or Decimal(0),
                      "unit": ws.cell(row=r, column=4).value,
                      "price": _d(ws.cell(row=r, column=5).value)})
    alts = []
    for r in range(meta.get("alt_first", 0), meta.get("alt_last", -1) + 1):
        no = ws.cell(row=r, column=1).value
        if no in (None, ""):
            continue
        alts.append({"no": str(no), "desc": ws.cell(row=r, column=2).value,
                     "kind": "deduct" if str(ws.cell(row=r, column=3).value)
                     .lower().startswith("d") else "add",
                     "amount": _d(ws.cell(row=r, column=5).value)})
    return {"items": items, "alternates": alts}


def totals(book):
    """The workbook's formulas, worked out: line totals, subtotal, base
    bid, each alternate's signed amount. Blank prices count as missing."""
    lines, missing = [], []
    for it in book["items"]:
        if it.get("price") is None:
            missing.append(it["no"])
            amt = None
        else:
            amt = (it["qty"] * it["price"]).quantize(CENT, ROUND_HALF_UP)
        lines.append(dict(it, total=amt))
    sub = sum((x["total"] for x in lines if x["total"] is not None),
              Decimal("0.00"))
    alts = []
    for a in book["alternates"]:
        amt = a.get("amount")
        signed = None if amt is None else (-amt if a["kind"] == "deduct"
                                           else amt)
        alts.append(dict(a, signed=signed))
    return {"lines": lines, "subtotal": sub, "base": sub, "alternates": alts,
            "missing": missing,
            "with_alternates": sub + sum((a["signed"] for a in alts
                                          if a["signed"] is not None),
                                         Decimal("0.00"))}


# ---- the calculating PDF ------------------------------------------------------------

def _money(v):
    return "" if v is None else f"{v:,.2f}"


def _field(page, name, rect, value="", calc=None, fmt=True, readonly=False):
    import fitz
    w = fitz.Widget()
    w.field_name = name
    w.field_type = fitz.PDF_WIDGET_TYPE_TEXT
    w.rect = rect
    w.text_fontsize = 8
    w.field_value = value
    if fmt:
        w.script_format = 'AFNumber_Format(2, 0, 0, 0, "$", true);'
        w.script_keystroke = 'AFNumber_Keystroke(2, 0, 0, 0, "$", true);'
    if calc:
        w.script_calc = calc
    if readonly:
        w.field_flags |= fitz.PDF_FIELD_IS_READ_ONLY
    page.add_widget(w)
    return w


def schedule_page(out, book, project=""):
    """A "Bid Schedule" page of fields that calculate in the PDF:
    qty x price per line, the subtotal, signed alternates, the base bid."""
    import fitz
    from . import bidform_auto
    t = totals(book)
    pg = out.new_page(width=612, height=792)
    y = 46
    pg.insert_text((36, y), f"BID SCHEDULE{(' - ' + project) if project else ''}",
                   fontsize=13, fontname="hebo")
    y += 16
    pg.insert_text((36, y), "Totals calculate as prices are typed. Filled "
                   "from the QuantiSheet bid form workbook.", fontsize=7.5,
                   fontname="helv")
    y += 18
    cols = [(36, "Item"), (70, "Description"), (330, "Qty"), (380, "Unit"),
            (420, "Unit price"), (505, "Line total")]
    for x, h in cols:
        pg.insert_text((x, y), h, fontsize=8, fontname="hebo")
    y += 6
    names = []
    for i, ln in enumerate(t["lines"], 1):
        if y > 640:
            pg = out.new_page(width=612, height=792)
            y = 50
        pg.insert_text((36, y + 10), str(ln["no"]), fontsize=8)
        pg.insert_text((70, y + 10), str(ln["desc"] or "")[:52], fontsize=8)
        _field(pg, f"qty_{i}", fitz.Rect(325, y, 375, y + 13),
               f"{ln['qty']:f}".rstrip("0").rstrip("."), fmt=False,
               readonly=True)
        pg.insert_text((380, y + 10), str(ln["unit"] or ""), fontsize=8)
        _field(pg, f"price_{i}", fitz.Rect(418, y, 498, y + 13),
               _money(ln.get("price")))
        _field(pg, f"total_{i}", fitz.Rect(503, y, 576, y + 13),
               _money(ln["total"]),
               calc=f'AFSimple_Calculate("PRD", new Array("qty_{i}", '
                    f'"price_{i}"));', readonly=True)
        names.append(f"total_{i}")
        y += 16
    y += 6
    pg.insert_text((420, y + 10), "Subtotal", fontsize=9, fontname="hebo")
    arr = ", ".join(f'"{n}"' for n in names) or '"total_0"'
    _field(pg, "subtotal", fitz.Rect(503, y, 576, y + 14),
           _money(t["subtotal"]),
           calc=f"AFSimple_Calculate(\"SUM\", new Array({arr}));",
           readonly=True)
    y += 26
    if t["alternates"]:
        pg.insert_text((36, y + 10), "Alternates", fontsize=9,
                       fontname="hebo")
        y += 16
        for i, a in enumerate(t["alternates"], 1):
            sign = "Deduct" if a["kind"] == "deduct" else "Add"
            pg.insert_text((36, y + 10), f"No. {a['no']}", fontsize=8)
            pg.insert_text((70, y + 10), f"{sign}: {a['desc'] or ''}"[:60],
                           fontsize=8)
            _field(pg, f"alt_{i}", fitz.Rect(418, y, 498, y + 13),
                   _money(a.get("amount")))
            _field(pg, f"alt_signed_{i}", fitz.Rect(503, y, 576, y + 13),
                   _money(a["signed"]),
                   calc=(f'event.value = (this.getField("alt_{i}").value'
                         f' || 0) * {-1 if sign == "Deduct" else 1};'),
                   readonly=True)
            y += 16
        y += 6
    pg.insert_text((420, y + 11), "BASE BID", fontsize=11, fontname="hebo")
    _field(pg, "base_bid", fitz.Rect(503, y, 576, y + 16),
           _money(t["base"]),
           calc='event.value = this.getField("subtotal").value;',
           readonly=True)
    y += 24
    pg.insert_text((36, y + 10), "Amount in words:", fontsize=8,
                   fontname="hebo")
    _field(pg, "base_bid_words", fitz.Rect(120, y, 576, y + 14),
           bidform_auto.amount_in_words(t["base"]), fmt=False)
    return t


def fill_pdf(doc, pages, book, out_path, project=""):
    """The bid form pages (as issued) + the calculating Bid Schedule page,
    filled from the workbook. Fields the owner's form already has are
    filled by name too (Base Bid, Alternate 1, Unit Price 3...)."""
    import fitz
    from . import bidform_auto
    out = fitz.open()
    for p in pages:
        out.insert_pdf(doc, from_page=p, to_page=p)
    t = schedule_page(out, book, project)
    vals = {"base": t["base"],
            "words": bidform_auto.amount_in_words(t["base"]),
            "alternates": {int(a["no"]): abs(a["signed"]) for a in
                           t["alternates"] if a["signed"] is not None and
                           str(a["no"]).isdigit()},
            "unit_prices": {int(ln["no"]): ln["price"] for ln in t["lines"]
                            if ln.get("price") is not None and
                            str(ln["no"]).isdigit()},
            "addenda": {}}
    if pages:
        sub = fitz.open()
        sub.insert_pdf(out, from_page=0, to_page=len(pages) - 1)
        try:
            bidform_auto.fill(sub, vals)
            # put the filled originals back in front of the schedule
            out.delete_pages(0, len(pages) - 1)
            out.insert_pdf(sub, from_page=0, to_page=len(pages) - 1,
                           start_at=0)
        except Exception:                                 # noqa: BLE001
            pass
    try:
        out.need_appearances(True)        # readers redraw the calculations
    except Exception:                                     # noqa: BLE001
        pass
    out.save(out_path, garbage=3, deflate=True)
    out.close()
    return t


# ---- addenda: did the bid form change? -----------------------------------------------

def addendum_check(doc):
    """{"has_form": bool, "revised": bool, "pages": [...], "form": parsed}
    for an addendum PDF - every addendum review asks this."""
    pages = form_pages(doc)
    revised = any(REVISED.search(doc[i].get_text("text"))
                  for i in range(doc.page_count))
    form = parse([doc[i].get_text("text") for i in pages]) if pages else \
        {"items": [], "alternates": [], "addenda": []}
    return {"has_form": bool(pages), "revised": revised or bool(pages),
            "pages": pages, "form": form}


def compare(old, new):
    """Bid form changes, old -> new parsed forms: {"added", "removed",
    "qty", "alternates_added", "alternates_removed"}."""
    o = {i["no"]: i for i in old.get("items", [])}
    n = {i["no"]: i for i in new.get("items", [])}
    oa = {a["no"] for a in old.get("alternates", [])}
    na = {a["no"] for a in new.get("alternates", [])}
    return {"added": [n[k] for k in n if k not in o],
            "removed": [o[k] for k in o if k not in n],
            "qty": [(o[k], n[k]) for k in n if k in o and
                    (o[k]["qty"] != n[k]["qty"] or
                     o[k]["unit"] != n[k]["unit"])],
            "alternates_added": sorted(na - oa),
            "alternates_removed": sorted(oa - na)}


def change_text(ch):
    parts = []
    if ch["added"]:
        parts.append("new items " + ", ".join(i["no"] for i in ch["added"]))
    if ch["removed"]:
        parts.append("items removed " + ", ".join(i["no"] for i in
                                                    ch["removed"]))
    if ch["qty"]:
        parts.append("quantities changed on " + ", ".join(
            f"{a['no']} ({a['qty']:,} -> {b['qty']:,} {b['unit']})"
            for a, b in ch["qty"]))
    if ch["alternates_added"]:
        parts.append("new alternates " + ", ".join(ch["alternates_added"]))
    if ch["alternates_removed"]:
        parts.append("alternates removed " + ", ".join(
            ch["alternates_removed"]))
    return "; ".join(parts) or "no changes to the items or alternates"
