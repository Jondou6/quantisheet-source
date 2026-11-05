"""Proposals: a client-ready bid PDF from the assembly estimate.

Pricing, from each part of each assembly in the takeoff:

    cost   = material x (1 + tax%) + labor
    price  = cost x (1 + overhead%) x (1 + profit%)

plus, when set, the rest of the bid build-up (app/bidbuild.py): general
conditions, trade margins, insurance, contingency, escalation and bond.

Lines can be shown by trade (lump sums), by assembly (quantity, unit and
price), with every part, or by CSI division (each division's lines under
its heading and subtotal; lines without a code under "Uncoded"). Lines
added in the Estimate panel are priced like assemblies (see
estimate_lines.rollup_rows). The job's proposal details (client, project,
markups, scope, inclusions, exclusions, terms) are saved inside the PDF;
your company details are saved once in settings and reused on every job.
"""
import datetime
import json
import logging
import os

import fitz

from . import assemblies, settings
from . import embfiles

log = logging.getLogger(__name__)

JOB_FILE = "quantisheet_proposal.json"
DETAIL = {"trade": "By trade (lump sums)",
          "assembly": "By assembly (quantities and prices)",
          "parts": "Every part (full detail)",
          "csi": "By CSI division (division subtotals)"}

COMPANY_FIELDS = ("name", "address", "phone", "email", "website", "license",
                  "logo", "signer", "title")

DEFAULT_EXCLUSIONS = "\n".join([
    "Permits, fees and bonds",
    "Engineering, testing and inspections",
    "Work not shown on the drawings listed",
    "Overtime or after-hours work",
])
DEFAULT_TERMS = "\n".join([
    "Payment due within 30 days of invoice.",
    "Changes to the scope will be priced as change orders before the work "
    "is done.",
])


def company():
    c = settings.get("company") or {}
    return {k: str(c.get(k, "") or "") for k in COMPANY_FIELDS}


def save_company(values):
    settings.set("company", {k: str(values.get(k, "") or "")
                             for k in COMPANY_FIELDS})


def defaults(doc):
    title = (doc.metadata or {}).get("title") or \
        os.path.splitext(os.path.basename(doc.name or "Project"))[0]
    return {"client": "", "attention": "", "client_address": "",
            "project": title, "project_address": "",
            "number": datetime.date.today().strftime("%Y%m%d-01"),
            "date": datetime.date.today().isoformat(), "valid_days": 30,
            "detail": "trade", "tax": 0.0, "overhead": 10.0, "profit": 10.0,
            "show_breakdown": False,
            "scope": "Furnish all labor and materials for the work below, "
                     "per the drawings provided.",
            "inclusions": "", "exclusions": DEFAULT_EXCLUSIONS,
            "qualifications": "", "takeoff_notes": True,
            "show_schedule": False, "crew_size": 4,
            "terms": DEFAULT_TERMS}


def read(doc):
    data = defaults(doc)
    try:
        if JOB_FILE in doc.embfile_names():
            saved = json.loads(doc.embfile_get(JOB_FILE).decode("utf-8"))
            if isinstance(saved, dict):
                data.update(saved)
    except Exception:
        log.warning("could not read proposal data", exc_info=True)
    return data


def write(doc, data):
    raw = json.dumps(data, indent=1).encode("utf-8")
    embfiles.put(doc, JOB_FILE, raw, "QuantiSheet proposal details")


def _num(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


# ---- pricing -------------------------------------------------------------------

def price(doc, data, page=None):
    """The proposal's lines and totals. Returns a dict:
    lines: [{trade, name, qty, unit, price}] at the chosen detail,
    material, tax, labor, cost, overhead, profit, total, errors, and
    steps: the whole bid build-up (general conditions, tax, overhead,
    profit, trade margins, insurance, contingency, escalation, bond)."""
    from . import bidbuild
    rows, _totals, errors = assemblies.rollup(doc, page)
    detail = data.get("detail", "trade")
    parts = []
    for r in rows:
        for q in r["parts"]:
            m = q["material"]
            lab = q.get("labor_cost", 0.0)
            # sales tax is on material only: an added line's equipment and
            # sub are in "material" (not labor) but not taxed
            parts.append({"trade": r["trade"] or "General", "row": r,
                          "part": q, "direct": m + lab,
                          "material": q.get("material_only", m)})
    built = bidbuild.build(parts, data, cents=False)
    lines, by_trade, by_row = [], {}, {}
    for w in built["lines"]:
        r, q, p = w["row"], w["part"], w["price"]
        if detail == "parts":
            lines.append({"trade": r["trade"], "name":
                          f"{r['name']} - {q['name']}", "qty": q["qty"],
                          "unit": q["unit"], "price": p,
                          "assembly": r["name"], "part": q["name"]})
        by_row[id(r)] = by_row.get(id(r), 0.0) + p
    for r in rows:
        r_price = by_row.get(id(r), 0.0)
        if detail in ("assembly", "csi"):
            lines.append({"trade": r["trade"], "name": r["name"],
                          "qty": r["quantity"], "unit": r["unit"],
                          "price": r_price, "csi": r.get("csi") or ""})
        t = by_trade.setdefault(r["trade"] or "General",
                                {"trade": r["trade"] or "General",
                                 "name": r["trade"] or "General", "qty": None,
                                 "unit": "", "price": 0.0, "items": []})
        t["price"] += r_price
        t["items"].append(r["name"])
    if detail == "trade":
        lines = list(by_trade.values())
    elif detail == "csi":
        for ln in lines:
            ln["division"], ln["group"] = division_group(ln.get("csi"))
        lines.sort(key=lambda ln: (ln["division"] == "", ln["division"]))
    step = {s["key"]: s["amount"] for s in built["steps"]}
    material = built["material"]
    labor = built["direct"] - material
    tax_amt = step.get("tax", 0.0)
    cost = material + tax_amt + labor
    overhead = step.get("overhead", 0.0)
    profit = step.get("profit", 0.0)
    total = built["total"]
    # round each line to cents and make them add up to the total exactly
    for ln in lines:
        ln["price"] = round(ln["price"], 2)
    if lines:
        lines[-1]["price"] = round(
            lines[-1]["price"] + total - sum(ln["price"] for ln in lines), 2)
    loc = _location(doc, parts, total)
    return {"lines": lines, "material": material, "tax": tax_amt,
            "location": loc,
            "labor": labor, "cost": cost, "overhead": overhead,
            "profit": profit, "total": total, "errors": errors,
            "direct": built["direct"], "steps": built["steps"],
            "by_trade": built["by_trade"],
            "extras": total - cost - overhead - profit}


# ---- qualifications from the takeoff (Nov 2) -------------------------------------

def _names(items, limit=6):
    names = sorted({it["group"] or it["type"].title() for it in items})
    more = len(names) - limit
    return ", ".join(names[:limit]) + (f" and {more} more" if more > 0
                                       else "")


def takeoff_notes(doc):
    """What the takeoff assumed, in plain words, for the proposal's
    Qualifications: AI items not checked (left out of the price), AI
    items a person checked, wall heights and openings, rise/drop added to
    runs, typical areas counted more than once. [] when there is
    nothing to say."""
    from . import annotate
    items = annotate.takeoff_items(doc)
    out = []
    pending = [it for it in items if it.get("pending")]
    if pending:
        out.append(f"{len(pending)} item(s) found by AI Takeoff and not "
                   f"checked yet ({_names(pending)}) are not in this "
                   "price.")
    checked = [it for it in items if not it.get("pending") and
               str(it.get("origin", "")).startswith("ai")]
    if checked:
        out.append(f"Quantities for {_names(checked)} were taken off with "
                   "AI Takeoff and checked by a person.")
    from . import measure_extra, takeoff
    walls = {}
    for it in items:
        ex = it.get("extra") or {}
        if ex.get("height") and not it.get("pending"):
            u = measure_extra.base_unit(it["unit"])
            key = (it["group"] or "Wall", takeoff.fmt(ex["height"], u),
                   bool(ex.get("openings")))
            walls[key] = walls.get(key, 0) + 1
    for (name, h, opening), _n in sorted(walls.items()):
        out.append(f"{name} wall areas use a {h} wall height" +
                   (", less the openings shown" if opening else
                    " with no openings taken out") + ".")
    rises = {}
    for it in items:
        ex = it.get("extra") or {}
        if ex.get("rise") and not it.get("pending"):
            key = (it["group"] or "Runs",
                   takeoff.fmt(abs(ex["rise"]), it["unit"]))
            rises[key] = rises.get(key, 0) + 1
    for (name, r), n in sorted(rises.items()):
        out.append(f"{name}: {n} run(s) include {r} of rise/drop each, "
                   "an allowance not drawn on the plans.")
    for it in items:
        m = it.get("multiplier") or 1
        if m != 1 and not it.get("pending"):
            out.append(f"{it['group'] or it['type'].title()} on page "
                       f"{it['page'] + 1} is counted as typical x {m:g}.")
    return out[:30]


def schedule(doc, crew=4, page=None):
    """Rough schedule from the estimate's labor: {"hours", "days"} -
    total labor hours over a crew of `crew` working 8-hour days. None
    when the estimate has no labor."""
    try:
        rows, _t, _e = assemblies.rollup(doc, page)
    except Exception:
        return None
    hours = sum(float(r.get("labor_hours") or 0) for r in rows)
    crew = max(1, int(_num(crew, 4)))
    if hours <= 0:
        return None
    return {"hours": hours, "days": hours / (crew * 8.0), "crew": crew}


def division_group(code):
    """("03", "Division 03 - Concrete") for a CSI code; ("", "Uncoded")
    when it has none."""
    from . import csi
    c = csi.parse_code(code or "")
    div = c[:2] if c and c[:2] in csi.DIVISIONS else ""
    if not div:
        return "", "Uncoded"
    title = csi.DIVISIONS[div]
    return div, f"Division {div} - {title[:1].upper()}{title[1:]}"


def _location(doc, parts, total):
    """[(label, amount)] 'Base estimate / Location adjustment / Grand
    total' when the cost book module offers a location adjustment, else
    []: the adjustment is on the direct material, labor and equipment."""
    from . import costbook
    if not hasattr(costbook, "location_adjustment"):
        return []
    from . import estimate_lines
    mat = lab = eqp = 0.0
    for p in parts:
        q = p["part"]
        e = q.get("equipment", 0.0)
        mat += q.get("material_only", q["material"] - e - q.get("sub", 0.0))
        lab += q.get("labor_cost", 0.0)
        eqp += e
    try:
        return [(label, float(v)) for label, v in
                estimate_lines.location_lines(
                    round(total, 2), round(mat, 2), round(lab, 2),
                    round(eqp, 2), estimate_lines.job_region(doc))]
    except Exception:                                     # noqa: BLE001
        log.warning("location adjustment left off", exc_info=True)
        return []


# ---- document ---------------------------------------------------------------------
# Drawn directly with PyMuPDF (fixed columns, our own text wrapping) so the
# layout is exact and predictable on every machine.

def _money(v):
    return f"${v:,.2f}"


def _lines(text):
    return [ln.strip(" -\u2022\t") for ln in str(text or "").splitlines()
            if ln.strip(" -\u2022\t")]


NAVY = (0.12, 0.23, 0.37)
GREY = (0.4, 0.4, 0.4)
INK = (0.13, 0.13, 0.13)
RULE = (0.75, 0.75, 0.75)
PAPER = fitz.paper_rect("letter")
LEFT, RIGHT, TOP, BOTTOM = 50, PAPER.width - 50, 50, PAPER.height - 62


def _clean(text):
    """Base-14 fonts cover Latin-1; swap the usual typographic marks."""
    return (str(text or "").replace("\u2019", "'").replace("\u2018", "'")
            .replace("\u201c", '"').replace("\u201d", '"')
            .replace("\u2013", "-").replace("\u2014", "-")
            .replace("\u2022", "-"))


def _wrap(text, width, size, font="helv"):
    out = []
    for para in _clean(text).split("\n"):
        words, line = para.split(" "), ""
        for w in words:
            trial = (line + " " + w) if line else w
            if fitz.get_text_length(trial, fontname=font, fontsize=size) \
                    <= width or not line:
                line = trial
            else:
                out.append(line)
                line = w
        out.append(line)
    return out


class _Writer:
    """A cursor that flows text down pages."""

    def __init__(self, doc):
        self.doc = doc
        self.page = None
        self.y = TOP
        self.new_page()

    def new_page(self):
        self.page = self.doc.new_page(width=PAPER.width, height=PAPER.height)
        self.y = TOP

    def need(self, h):
        if self.y + h > BOTTOM:
            self.new_page()

    def text(self, x, y, s, size=10, font="helv", color=INK, align="left",
             right=None):
        s = _clean(s)
        if align == "right":
            x = (right or RIGHT) - fitz.get_text_length(
                s, fontname=font, fontsize=size)
        self.page.insert_text((x, y), s, fontsize=size, fontname=font,
                              color=color)

    def para(self, s, size=10, x=LEFT, width=None, color=INK, gap=3,
             font="helv"):
        width = width or (RIGHT - x)
        lh = size * 1.3
        for ln in _wrap(s, width, size, font):
            self.need(lh)
            self.y += lh
            self.text(x, self.y - size * 0.25, ln, size, font, color)
        self.y += gap

    def heading(self, s):
        self.need(40)
        self.y += 14
        self.y += 13
        self.text(LEFT, self.y, s, 12, "hebo", NAVY)
        self.y += 6

    def rule(self, color=RULE, width=0.6):
        self.page.draw_line((LEFT, self.y), (RIGHT, self.y), color=color,
                            width=width)


def _header(w, data, comp):
    top = TOP
    x = LEFT
    logo = comp.get("logo")
    y = top
    if logo and os.path.isfile(logo):
        try:
            r = fitz.Rect(LEFT, top, LEFT + 170, top + 60)
            w.page.insert_image(r, filename=logo, keep_proportion=True)
            y = top + 64
        except Exception:
            log.warning("could not add logo %s", logo, exc_info=True)
    y += 14
    w.text(x, y, comp.get("name") or "Your Company", 13, "hebo")
    contact = [comp.get("address", "").replace("\n", ", "),
               " | ".join(v for v in (comp.get("phone"), comp.get("email"),
                                      comp.get("website")) if v),
               f"License {comp['license']}" if comp.get("license") else ""]
    for ln in [c for c in contact if c]:
        y += 11
        w.text(x, y, ln, 8.5, color=GREY)
    try:
        date = datetime.date.fromisoformat(str(data.get("date")))
    except ValueError:
        date = datetime.date.today()
    until = date + datetime.timedelta(days=int(_num(data.get("valid_days"),
                                                    30)))
    ry = top + 22
    w.text(0, ry, "PROPOSAL", 24, "hebo", NAVY, align="right")
    for ln in (f"No. {data.get('number', '')}", f"Date: {date:%B %d, %Y}",
               f"Valid until: {until:%B %d, %Y}"):
        ry += 12
        w.text(0, ry, ln, 9, color=GREY, align="right")
    w.y = max(y, ry) + 12
    w.rule(INK, 0.8)
    # prepared for / project, side by side
    col = (RIGHT - LEFT) / 2
    left = [("hebo", data.get("client") or "")]
    if data.get("attention"):
        left.append(("helv", "Attn: " + data["attention"]))
    left += [("helv", ln) for ln in str(data.get("client_address") or "")
             .splitlines() if ln.strip()]
    right = [("hebo", data.get("project") or "")] + \
        [("helv", ln) for ln in str(data.get("project_address") or "")
         .splitlines() if ln.strip()]
    y0 = w.y + 18
    w.text(LEFT, y0, "PREPARED FOR", 8, "hebo", NAVY)
    w.text(LEFT + col, y0, "PROJECT", 8, "hebo", NAVY)
    ys = []
    for x0, items in ((LEFT, left), (LEFT + col, right)):
        y = y0
        for font, ln in items:
            for part in _wrap(ln, col - 12, 10, font):
                y += 13
                w.text(x0, y, part, 10, font)
        ys.append(y)
    w.y = max(ys) + 6


def _pricing(w, data, priced):
    detail = data.get("detail", "trade")
    w.heading("Pricing")
    qx, ux, px = RIGHT - 150, RIGHT - 142, RIGHT     # qty right, unit, price
    name_w = (RIGHT - 100 - LEFT - 8) if detail == "trade" else \
        (qx - 60 - LEFT)
    w.need(20)
    w.y += 12
    w.text(LEFT, w.y, "WORK" if detail == "trade" else "ITEM", 8, "hebo",
           NAVY)
    if detail != "trade":
        w.text(0, w.y, "QTY", 8, "hebo", NAVY, align="right", right=qx)
        w.text(ux, w.y, "UNIT", 8, "hebo", NAVY)
    w.text(0, w.y, "PRICE", 8, "hebo", NAVY, align="right", right=px)
    w.y += 5
    w.rule()
    group = None
    gkey = "group" if detail == "csi" else "assembly"
    grouped = detail in ("parts", "csi")
    for ln in priced["lines"]:
        if grouped and ln.get(gkey) != group:
            group = ln.get(gkey)
            sub_total = sum(x["price"] for x in priced["lines"]
                            if x.get(gkey) == group)
            heads = _wrap(group, name_w, 10, "hebo")
            w.need(13 * len(heads) + 8 + 21)   # heading + first part
            y = w.y + 13
            w.text(0, y, _money(sub_total), 10, "hebo", align="right",
                   right=px)
            for i, part in enumerate(heads):
                w.text(LEFT, y + 13 * i, part, 10, "hebo")
            w.y = y + 13 * (len(heads) - 1) + 6
            w.rule()
        shown = ln.get("part") if detail == "parts" else ln["name"]
        indent = 12 if grouped else 0
        name_lines = _wrap(shown, name_w - indent, 10,
                           "hebo" if detail == "trade" else "helv")
        sub = _wrap(", ".join(ln.get("items", [])), name_w, 8.5) \
            if detail == "trade" and ln.get("items") else []
        h = 13 * len(name_lines) + 11 * len(sub) + 8
        w.need(h)
        y = w.y + 13
        w.text(0, y, _money(ln["price"]), 10, align="right", right=px,
               color=GREY if detail == "parts" else INK)
        if detail != "trade":
            w.text(0, y, f"{ln['qty']:,.2f}", 10, align="right", right=qx)
            w.text(ux, y, ln["unit"], 10)
        for i, part in enumerate(name_lines):
            w.text(LEFT + indent, y + 13 * i, part, 10,
                   "hebo" if detail == "trade" else "helv",
                   color=GREY if detail == "parts" else INK)
        y += 13 * (len(name_lines) - 1)
        for part in sub:
            y += 11
            w.text(LEFT + 8, y, part, 8.5, color=GREY)
        w.y = y + 6
        w.rule()
    rows = []
    if data.get("show_breakdown"):
        rows = [("Material", priced["material"]), ("Labor", priced["labor"])]
        for st in priced.get("steps") or []:
            rows.append((st["label"], st["amount"]))
    # the breakdown and the total stay together on one page
    w.need(13 * len(rows) + 30)
    for label, amount in rows:
        w.need(13)
        w.y += 13
        w.text(0, w.y, label, 9, color=GREY, align="right", right=px - 90)
        w.text(0, w.y, _money(amount), 9, color=GREY, align="right",
               right=px)
    loc = priced.get("location") or []
    w.need(26 + 15 * len(loc))
    w.y += 8
    w.page.draw_line((px - 200, w.y), (px, w.y), color=INK, width=1)
    if loc:
        # Base estimate / Location adjustment (+x%) / Grand total
        for i, (label, amount) in enumerate(loc):
            last = i == len(loc) - 1
            w.y += 16 if last else 14
            w.text(0, w.y, label.upper() if last else label,
                   12 if last else 10, "hebo" if last else "helv",
                   align="right", right=px - 90)
            w.text(0, w.y, _money(amount), 12 if last else 10,
                   "hebo" if last else "helv", align="right", right=px)
        w.y += 4
        return
    w.y += 16
    w.text(0, w.y, "TOTAL", 12, "hebo", align="right", right=px - 90)
    w.text(0, w.y, _money(priced["total"]), 12, "hebo", align="right",
           right=px)
    w.y += 4


def _acceptance(w, data, comp):
    w.need(150)                                   # keep it all together
    w.heading("Acceptance")
    w.para("The prices, scope and terms above are accepted. You are "
           "authorized to do the work as described.", 9, color=GREY)
    col = (RIGHT - LEFT) / 2
    y = w.y + 44
    for x0, who, sub in (
            (LEFT, data.get("client") or "Client", ""),
            (LEFT + col, comp.get("signer") or comp.get("name") or
             "Contractor", comp.get("title") or "")):
        w.page.draw_line((x0, y), (x0 + col - 30, y), color=INK, width=0.7)
        w.text(x0, y + 13, who, 10, "hebo")
        yy = y + 13
        if sub:
            yy += 11
            w.text(x0, yy, sub, 8.5, color=GREY)
        w.text(x0, yy + 11, "Signature / Date", 8.5, color=GREY)
    w.y = y + 50


COVER_IMAGE_H = 230          # tallest the project image is drawn (points)


def _job_cover(w, data, doc):
    """Job info on the cover page (jobinfo.py): the project image, then
    the description and the website / contact line. Nothing when the job
    has none of them."""
    from . import jobinfo
    try:
        img = jobinfo.image_bytes(doc)
    except Exception:                                     # noqa: BLE001
        log.warning("project image left off", exc_info=True)
        img = None
    desc = str(data.get("description") or "").strip()
    site = str(data.get("website") or "").strip()
    if img:
        try:
            pix = fitz.Pixmap(img)
            iw, ih = max(1, pix.width), max(1, pix.height)
            pix = None
            h = min(COVER_IMAGE_H, (RIGHT - LEFT) * ih / iw)
            wd = h * iw / ih
            w.need(h + 16)
            w.y += 10
            r = fitz.Rect(LEFT, w.y, LEFT + wd, w.y + h)
            w.page.insert_image(r, stream=img, keep_proportion=True)
            w.y += h + 4
        except Exception:                                 # noqa: BLE001
            log.warning("could not add the project image", exc_info=True)
    if desc:
        w.y += 6
        w.para(desc, 10)
    if site:
        w.para(site, 9, color=GREY)


def make_pdf(doc, data, comp=None, page=None):
    """The proposal as a new PDF document."""
    comp = comp if comp is not None else company()
    priced = price(doc, data, page)
    out = fitz.open()
    w = _Writer(out)
    _header(w, data, comp)
    _job_cover(w, data, doc)               # job info: image + description
    if data.get("scope"):
        w.heading("Scope of Work")
        w.para(data["scope"])
    _pricing(w, data, priced)
    if data.get("show_schedule"):
        sch = schedule(doc, data.get("crew_size", 4), page)
        if sch:
            w.heading("Schedule")
            w.para(f"About {max(1, round(sch['days'])):,} working day(s) "
                   f"with a crew of {sch['crew']} ({sch['hours']:,.0f} "
                   "labor hours), from the start of work. A rough guide "
                   "from the estimate, not a commitment.")
    quals = _lines(data.get("qualifications"))
    if data.get("takeoff_notes", True):
        quals += takeoff_notes(doc)
    for title, key in (("Qualifications", None),
                       ("Inclusions", "inclusions"),
                       ("Exclusions", "exclusions")):
        items = quals if key is None else _lines(data.get(key))
        if items:
            w.heading(title)
            for it in items:
                lines = _wrap(it, RIGHT - LEFT - 16, 10)
                w.need(13 * len(lines))
                w.page.draw_circle((LEFT + 4, w.y + 9.5), 1.6, color=INK,
                                   fill=INK)
                for part in lines:
                    w.y += 13
                    w.text(LEFT + 14, w.y - 2.5, part, 10)
                w.y += 1
    if data.get("terms"):
        w.heading("Terms")
        w.para(data["terms"])
    _acceptance(w, data, comp)
    n = out.page_count
    for i, pg in enumerate(out):
        pg.insert_text((LEFT, PAPER.height - 30),
                       _clean(f"{comp.get('name') or ''}  |  Proposal "
                              f"{data.get('number', '')}  |  Page {i + 1} "
                              f"of {n}"),
                       fontsize=7.5, color=GREY)
    out.set_metadata({"title": f"Proposal - {data.get('project', '')}",
                      "author": comp.get("name", ""),
                      "subject": f"Proposal {data.get('number', '')}",
                      "creator": "QuantiSheet"})
    return out
