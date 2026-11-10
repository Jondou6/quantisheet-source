"""Export My Estimate: the whole estimate in one summary - totals by CSI
division and by cost type - saved to PDF, Excel or CSV.

The estimate is everything priced in the job, at direct cost:
  * assemblies (assemblies.rollup: material and labor),
  * priced takeoff lines in the Estimate panel (estimate.lines; their
    cost type and code as typed on the line),
  * lines added in the Estimate panel (estimate_lines: the Mat / Lab /
    Eqp / Sub split).
A line without a CSI code goes under "Uncoded" and is still counted.
Money is Decimal cents; every total is a sum of cents, so the division
subtotals, the cost type totals and the grand total agree to the cent.
"""
import datetime as _dt
import logging
from decimal import Decimal

from . import csi, dmoney, safecell
from .dmoney import c2 as _c2

log = logging.getLogger(__name__)

TYPES = ("Material", "Labor", "Equipment", "Subcontract", "Allowance",
         "Other")
UNCODED = "Uncoded"
Z = Decimal("0.00")


def _type_of(text):
    """The summary column a line's cost type goes in ('Other' if none)."""
    from . import estimate_lines
    try:
        t = estimate_lines.cost_type(text)
    except estimate_lines.LineError:
        t = ""
    return t if t in TYPES else "Other"


def division_of(code):
    """("09", "Finishes") for a CSI code; ("", "Uncoded") without one."""
    c = csi.parse_code(code or "")
    if not c:
        try:
            from . import costbook
            d = costbook.division_of(code)
        except Exception:                                 # noqa: BLE001
            d = ""
    else:
        d = c[:2]
    if d in csi.DIVISIONS:
        t = csi.DIVISIONS[d]
        return d, t[:1].upper() + t[1:]
    return "", UNCODED


def _line(source, code, desc, qty, unit, unit_cost, by_type, trade="",
          key=""):
    by_type = {k: dmoney.cents(v) for k, v in by_type.items() if v}
    div, title = division_of(code)
    # "trade" (bid item) and "key" (which line it is, for a layout's tags:
    # estimate_layouts.py) ride along; the summary doesn't use them
    return {"source": source, "code": csi.parse_code(code or "") or
            str(code or ""), "division": div, "title": title, "desc": desc,
            "qty": dmoney.D(qty), "unit": unit or "",
            "unit_cost": dmoney.D(unit_cost), "by_type": by_type,
            "total": sum(by_type.values(), Z),
            "trade": trade or (title if div else "General"),
            "key": key or f"{source}:{desc}"}


def collect(doc):
    """[{source, code, division, title, desc, qty, unit, unit_cost,
    by_type: {type: Decimal}, total}] for every priced line."""
    from . import assemblies, estimate, estimate_lines
    out = []
    try:
        rows, _t, _e = assemblies.rollup(doc, added=False)
    except Exception:                                     # noqa: BLE001
        log.warning("assembly estimate left out", exc_info=True)
        rows = []
    for r in rows:
        mat, lab = dmoney.cents(r["material"]), dmoney.cents(r["labor_cost"])
        if not (mat or lab):
            continue
        qty = dmoney.D(round(r["quantity"], 4))
        out.append(_line("assembly", r.get("csi"), r["name"], qty, r["unit"],
                         ((mat + lab) / qty) if qty else 0,
                         {"Material": mat, "Labor": lab},
                         trade=r.get("trade") or "",
                         key=f"assembly:{r['name']}"))
    try:
        tl = estimate.lines(doc)
    except Exception:                                     # noqa: BLE001
        log.warning("takeoff lines left out", exc_info=True)
        tl = []
    for g in tl:
        t = dmoney.cents(g["total"])
        if not t:
            continue
        out.append(_line("takeoff", g.get("code"), g["name"],
                         dmoney.D(round(g["adjusted"], 4)), g["unit"],
                         g["unit_cost"], {_type_of(g.get("cost_type")): t},
                         key=f"takeoff:{g['name']}|{g['type']}|{g['unit']}"))
    for p in estimate_lines.priced(doc):
        if not p["total"]:
            continue
        bt = {}
        for k, v in estimate_lines.by_type([p]).items():
            bt[k if k in TYPES else "Other"] = v
        out.append(_line("added", p["code"], p["desc"], p["quantity"],
                         p["unit_label"], p["unit_cost"], bt,
                         key=f"added:{p['id']}"))
    return out


def priced_by_assembly(doc, names, priced_names):
    """{takeoff line name: assembly name} for the takeoff groups an
    assembly prices (the group name finds the assembly, as the rollup
    does). `priced_names`: the assemblies that came out with a price."""
    from . import assemblies
    if doc is None or not priced_names:
        return {}
    try:
        job, lib = assemblies.read_job(doc), assemblies.library()
    except Exception:                                     # noqa: BLE001
        log.warning("assemblies unavailable", exc_info=True)
        return {}
    out = {}
    for n in names:
        a = assemblies.find(doc, n, job, lib)
        if a and a.get("name") in priced_names:
            out[n] = a["name"]
    return out


def unpriced(doc, priced_names=None):
    """Takeoff lines with a quantity but no price yet (review r41 F01: an
    export of measured-but-unpriced takeoffs used to be an empty $0.00
    summary). [{code, division, title, desc, qty, unit}] - listed in the
    exports with a blank price; never added to any total.

    A takeoff priced by its assembly is priced (Chief's estimator test,
    Nov 7: all 11 assembly-priced items were listed here again).
    `priced_names`: the assemblies with a price (worked out when None)."""
    from . import estimate
    if doc is None:
        return []
    try:
        tl = estimate.lines(doc)
    except Exception:                                     # noqa: BLE001
        log.warning("takeoff lines left out", exc_info=True)
        return []
    if priced_names is None:
        priced_names = {ln["desc"] for ln in collect(doc)
                        if ln["source"] == "assembly"}
    by_asm = priced_by_assembly(doc, [g["name"] for g in tl], priced_names)
    out = []
    for g in tl:
        if dmoney.cents(g.get("total") or 0):
            continue
        if g["name"] in by_asm:
            continue
        q = g.get("adjusted", g.get("quantity")) or 0
        if not q:
            continue
        div, title = division_of(g.get("code"))
        out.append({"code": csi.parse_code(g.get("code") or "") or
                    str(g.get("code") or ""), "division": div,
                    "title": title, "desc": g["name"],
                    "qty": dmoney.D(round(q, 4)), "unit": g.get("unit")
                    or ""})
    return out


def unpriced_note(s):
    n = len(s.get("unpriced") or [])
    if not n:
        return ""
    return (f"{n} takeoff item{'s have' if n != 1 else ' has'} no price yet "
            "- listed with quantity and a blank price, not in the totals. "
            "Price them all at once with Estimate > Price These (unit costs "
            "from your cost books are suggested), or in the Estimate panel.")


def _div_key(d):
    return (d == "", d)


def summary(doc=None, lines=None):
    """{"lines", "divisions": [{division, title, label, total, count,
    by_type}], "types": {type: Decimal}, "total", "location": [(label,
    Decimal)]} - divisions in CSI order, Uncoded last."""
    lines = collect(doc) if lines is None else lines
    divs = {}
    types = {}
    for ln in lines:
        d = divs.setdefault(ln["division"], {
            "division": ln["division"], "title": ln["title"], "total": Z,
            "count": 0, "by_type": {}, "lines": []})
        d["total"] += ln["total"]
        d["count"] += 1
        d["lines"].append(ln)
        for k, v in ln["by_type"].items():
            d["by_type"][k] = d["by_type"].get(k, Z) + v
            types[k] = types.get(k, Z) + v
    out = []
    for k in sorted(divs, key=_div_key):
        d = divs[k]
        d["label"] = (f"Division {d['division']} - {d['title']}"
                      if d["division"] else UNCODED)
        out.append(d)
    total = sum((d["total"] for d in out), Z)
    loc = []
    if doc is not None:
        from . import estimate_lines
        loc = estimate_lines.location_lines(
            total, types.get("Material", Z), types.get("Labor", Z),
            types.get("Equipment", Z), estimate_lines.job_region(doc))
    return {"lines": lines, "divisions": out,
            "types": {k: types[k] for k in TYPES if k in types},
            "total": total, "location": loc,
            "unpriced": unpriced(doc, {ln["desc"] for ln in lines
                                       if ln["source"] == "assembly"})}


def _project(doc):
    try:
        from . import proposal
        return proposal.read(doc).get("project") or ""
    except Exception:                                     # noqa: BLE001
        return ""


# ---- CSV ------------------------------------------------------------------

def write_csv(path, s, project=""):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = safecell.writer(f)
        w.writerow(["Estimate summary", project,
                    _dt.date.today().isoformat()])
        w.writerow([])
        w.writerow(["Division", "Title", "Code", "Description", "Source",
                    "Quantity", "Unit", "Unit Cost"] + list(TYPES) +
                   ["Total"])
        for d in s["divisions"]:
            for ln in d["lines"]:
                w.writerow([d["division"] or UNCODED, d["title"], ln["code"],
                            ln["desc"], ln["source"], _num(ln["qty"]),
                            ln["unit"], _money_text(ln["unit_cost"], 4)] +
                           [_cell(ln["by_type"].get(k)) for k in TYPES] +
                           [str(ln["total"])])
        for u in s.get("unpriced") or []:
            w.writerow([u["division"] or UNCODED, u["title"], u["code"],
                        u["desc"], "takeoff (no price)", _num(u["qty"]),
                        u["unit"], ""] + [""] * len(TYPES) + [""])
        if s.get("unpriced"):
            w.writerow([unpriced_note(s)])
        w.writerow([])
        w.writerow(["By CSI division"])
        for d in s["divisions"]:
            w.writerow([d["division"] or UNCODED, d["title"], "", "", "",
                        "", "", ""] +
                       [_cell(d["by_type"].get(k)) for k in TYPES] +
                       [str(d["total"])])
        w.writerow([])
        w.writerow(["By cost type"])
        for k, v in s["types"].items():
            w.writerow([k, str(v)])
        w.writerow([])
        for label, v in s["location"] or [("Grand total", s["total"])]:
            w.writerow([label, str(dmoney.cents(v))])
    return path


def _cell(v):
    return str(v) if v else ""


def _num(q):
    t = f"{dmoney.D(q):f}"
    return t.rstrip("0").rstrip(".") if "." in t else t


def _money_text(v, places=2):
    d = dmoney.D(v).quantize(Decimal(1).scaleb(-places))
    return str(d)


# ---- Excel ----------------------------------------------------------------

MONEY_FMT = '"$"#,##0.00'


def write_xlsx(path, s, project=""):
    """Workbook with sheets By Division (SUM formulas for the totals), By
    Cost Type and Lines."""
    import openpyxl
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "By Division"
    bold = Font(bold=True)
    head = ["Division", "Title"] + list(TYPES) + ["Total"]
    safecell.append_row(ws, head)
    for c in ws[1]:
        c.font = bold
    for d in s["divisions"]:
        safecell.append_row(ws, [d["division"] or UNCODED, d["title"]] +
                            [float(d["by_type"].get(k, Z)) for k in TYPES] +
                            [float(d["total"])])
    first, last = 2, ws.max_row
    n = len(s["divisions"])
    row = ["Total", ""]
    for i in range(len(TYPES) + 1):
        col = get_column_letter(3 + i)
        row.append(safecell.Formula(f"=SUM({col}{first}:{col}{last})")
                   if n else 0)
    safecell.append_row(ws, row)
    for c in ws[ws.max_row]:
        c.font = bold
    for label, v in s["location"]:
        safecell.append_row(ws, [label, ""] + [""] * len(TYPES) + [float(v)])
    for r in ws.iter_rows(min_row=2, min_col=3, max_col=3 + len(TYPES)):
        for c in r:
            c.number_format = MONEY_FMT
    ws.column_dimensions["B"].width = 36
    for i in range(len(TYPES) + 1):
        ws.column_dimensions[get_column_letter(3 + i)].width = 14

    wt = wb.create_sheet("By Cost Type")
    safecell.append_row(wt, ["Cost Type", "Amount"])
    for c in wt[1]:
        c.font = bold
    for k, v in s["types"].items():
        safecell.append_row(wt, [k, float(v)])
    end = wt.max_row
    safecell.append_row(wt, ["Total", safecell.Formula(f"=SUM(B2:B{end})")
                             if end >= 2 else 0])
    wt[wt.max_row][0].font = bold
    for r in wt.iter_rows(min_row=2, min_col=2, max_col=2):
        for c in r:
            c.number_format = MONEY_FMT
    wt.column_dimensions["A"].width = 16
    wt.column_dimensions["B"].width = 16

    wl = wb.create_sheet("Lines")
    safecell.append_row(wl, ["Division", "Code", "Description", "Source",
                             "Quantity", "Unit", "Unit Cost"] + list(TYPES) +
                        ["Total"])
    for c in wl[1]:
        c.font = bold
    for d in s["divisions"]:
        for ln in d["lines"]:
            safecell.append_row(
                wl, [d["division"] or UNCODED, ln["code"], ln["desc"],
                     ln["source"], float(ln["qty"]), ln["unit"],
                     float(ln["unit_cost"])] +
                [float(ln["by_type"].get(k, Z)) for k in TYPES] +
                [float(ln["total"])])
    end = wl.max_row
    for u in s.get("unpriced") or []:
        safecell.append_row(
            wl, [u["division"] or UNCODED, u["code"], u["desc"],
                 "takeoff (no price)", float(u["qty"]), u["unit"], None] +
            [None] * len(TYPES) + [None])
    tcol = get_column_letter(8 + len(TYPES))
    safecell.append_row(wl, ["Total", "", "", "", "", "", "",
                             *[""] * len(TYPES),
                             safecell.Formula(f"=SUM({tcol}2:{tcol}{end})")
                             if end >= 2 else 0])
    wl[wl.max_row][0].font = bold
    if s.get("unpriced"):
        safecell.append_row(wl, [unpriced_note(s)])
    for r in wl.iter_rows(min_row=2, min_col=7, max_col=8 + len(TYPES)):
        for c in r:
            c.number_format = MONEY_FMT
    wl.column_dimensions["C"].width = 40
    if project:
        wb.properties.title = f"Estimate - {project}"
    wb.properties.creator = "QuantiSheet"
    wb.save(path)
    return path


# ---- PDF ------------------------------------------------------------------

def make_pdf(s, project="", comp=None):
    """The summary as a new PDF: each CSI division as a heading with its
    subtotal and lines, then the totals by cost type and the grand total
    (with the location adjustment lines when there are any)."""
    import fitz
    from . import proposal as P
    comp = comp if comp is not None else P.company()
    out = fitz.open()
    w = P._Writer(out)
    w.y = P.TOP + 14
    w.text(P.LEFT, w.y, comp.get("name") or "", 11, "hebo")
    w.text(0, w.y + 8, "ESTIMATE SUMMARY", 20, "hebo", P.NAVY,
           align="right")
    w.y += 26
    w.text(0, w.y, f"{project}  |  {_dt.date.today():%B %d, %Y}" if project
           else f"{_dt.date.today():%B %d, %Y}", 9, color=P.GREY,
           align="right")
    w.y += 8
    w.rule(P.INK, 0.8)
    w.heading("By CSI division")
    px, qx, ux = P.RIGHT, P.RIGHT - 150, P.RIGHT - 142
    name_w = qx - 60 - P.LEFT
    for d in s["divisions"]:
        heads = P._wrap(d["label"], name_w, 10, "hebo")
        w.need(13 * len(heads) + 8 + 21)
        y = w.y + 13
        w.text(0, y, P._money(float(d["total"])), 10, "hebo",
               align="right", right=px)
        for i, part in enumerate(heads):
            w.text(P.LEFT, y + 13 * i, part, 10, "hebo")
        w.y = y + 13 * (len(heads) - 1) + 6
        w.rule()
        for ln in d["lines"]:
            label = f"{ln['code']}  {ln['desc']}" if ln["code"] else \
                ln["desc"]
            parts = P._wrap(label, name_w - 12, 9.5)
            w.need(13 * len(parts) + 6)
            y = w.y + 12
            w.text(0, y, P._money(float(ln["total"])), 9.5, color=P.GREY,
                   align="right", right=px)
            if ln["qty"]:
                w.text(0, y, f"{_c2(float(ln['qty'])):,.2f}", 9.5, color=P.GREY,
                       align="right", right=qx)
                w.text(ux, y, ln["unit"], 9.5, color=P.GREY)
            for i, part in enumerate(parts):
                w.text(P.LEFT + 12, y + 12 * i, part, 9.5, color=P.GREY)
            w.y = y + 12 * (len(parts) - 1) + 5
        w.y += 2
        w.rule()
    if s.get("unpriced"):
        w.heading("Not priced yet")
        for part in P._wrap(unpriced_note(s), P.RIGHT - P.LEFT, 9):
            w.need(13)
            w.y += 12
            w.text(P.LEFT, w.y, part, 9, color=P.GREY)
        w.y += 4
        for u in s["unpriced"]:
            label = f"{u['code']}  {u['desc']}" if u["code"] else u["desc"]
            parts = P._wrap(label, name_w - 12, 9.5)
            w.need(13 * len(parts) + 6)
            y = w.y + 12
            w.text(0, y, f"{_c2(float(u['qty'])):,.2f}", 9.5, color=P.GREY,
                   align="right", right=qx)
            w.text(ux, y, u["unit"], 9.5, color=P.GREY)
            w.text(0, y, "-", 9.5, color=P.GREY, align="right", right=px)
            for i, part in enumerate(parts):
                w.text(P.LEFT + 12, y + 12 * i, part, 9.5, color=P.GREY)
            w.y = y + 12 * (len(parts) - 1) + 5
        w.y += 2
        w.rule()
    w.heading("By cost type")
    for k, v in s["types"].items():
        w.need(14)
        w.y += 14
        w.text(P.LEFT, w.y, k, 10)
        w.text(0, w.y, P._money(float(v)), 10, align="right", right=px)
    rows = s["location"] or [("Total", s["total"])]
    w.need(30 + 15 * len(rows))
    w.y += 10
    w.page.draw_line((px - 220, w.y), (px, w.y), color=P.INK, width=1)
    for i, (label, v) in enumerate(rows):
        last = i == len(rows) - 1
        w.y += 16 if last else 14
        w.text(0, w.y, label.upper() if last else label,
               12 if last else 10, "hebo" if last else "helv",
               align="right", right=px - 100)
        w.text(0, w.y, P._money(float(v)), 12 if last else 10,
               "hebo" if last else "helv", align="right", right=px)
    n = out.page_count
    for i, pg in enumerate(out):
        pg.insert_text((P.LEFT, P.PAPER.height - 30),
                       P._clean(f"{comp.get('name') or ''}  |  Estimate "
                                f"summary  |  Page {i + 1} of {n}"),
                       fontsize=7.5, color=P.GREY)
    out.set_metadata({"title": f"Estimate - {project}" if project else
                      "Estimate", "author": comp.get("name", ""),
                      "creator": "QuantiSheet"})
    return out


def save_pdf(doc, path, s=None):
    s = s if s is not None else summary(doc)
    out = make_pdf(s, _project(doc))
    try:
        out.save(path, garbage=3, deflate=True)
    finally:
        out.close()
    return path


def save_xlsx(doc, path, s=None):
    return write_xlsx(path, s if s is not None else summary(doc),
                      _project(doc))


def save_csv(doc, path, s=None):
    return write_csv(path, s if s is not None else summary(doc),
                     _project(doc))


# ---- a saved layout (estimate_layouts.py) ---------------------------------

def _view_amount(cells, keys, k):
    """A line's text for column k; an amount-only line (adjustment, not
    shown, grand total) puts its amount in the last column when the layout
    hides Total."""
    if k in cells:
        return cells[k]
    if "total" not in keys and keys and k == keys[-1]:
        return cells.get("total", "")
    return ""


def _plain(text):
    """'$1,234.50' / '-$3.00' -> '1234.50' / '-3.00' (CSV and Excel take
    numbers, not display text); other text unchanged."""
    t = str(text or "")
    raw = t.replace("$", "").replace(",", "")
    try:
        Decimal(raw)
    except Exception:                                     # noqa: BLE001
        return t
    return raw if raw else t


def write_view_csv(path, v, project=""):
    from . import estimate_layouts as L
    keys = [k for k, _l in v["columns"]]
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = safecell.writer(f)
        w.writerow([f"Estimate - {v['name']}", project,
                    _dt.date.today().isoformat()])
        w.writerow([])
        w.writerow(["", "Description"] + [lb for _k, lb in v["columns"]])
        for kind, label, cells in L.flat_rows(v):
            w.writerow([kind, label] +
                       [_plain(_view_amount(cells, keys, k)) for k in keys])
        for n in v["notes"]:
            w.writerow(["note", n])
    return path


def write_view_xlsx(path, v, project=""):
    import openpyxl
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter
    from . import estimate_layouts as L
    keys = [k for k, _l in v["columns"]]
    wb = openpyxl.Workbook()
    ws = wb.active
    title = "".join(c for c in v["name"] if c not in "[]:*?/\\")[:31]
    ws.title = title or "Layout"
    bold = Font(bold=True)
    safecell.append_row(ws, ["Description"] +
                        [lb for _k, lb in v["columns"]])
    for c in ws[1]:
        c.font = bold
    for kind, label, cells in L.flat_rows(v):
        row = [label]
        for k in keys:
            t = _view_amount(cells, keys, k)
            p = _plain(t)
            num = None
            if t and (p != t or k == "qty"):
                try:
                    num = float(Decimal(p))
                except Exception:                         # noqa: BLE001
                    num = None
            row.append(num if num is not None else t)
        safecell.append_row(ws, row)
        if kind in ("group", "subtotal", "total"):
            for c in ws[ws.max_row]:
                c.font = bold
    for i, k in enumerate(keys):
        col = get_column_letter(2 + i)
        if k in L.MONEY or k == "unit_cost" or (
                k == keys[-1] and "total" not in keys):
            for r in ws.iter_rows(min_row=2, min_col=2 + i, max_col=2 + i):
                for c in r:
                    if isinstance(c.value, float):
                        c.number_format = MONEY_FMT
        ws.column_dimensions[col].width = 16
    ws.column_dimensions["A"].width = 48
    if v["notes"]:
        safecell.append_row(ws, [])
        for n in v["notes"]:
            safecell.append_row(ws, [n])
    if project:
        wb.properties.title = f"Estimate - {project} - {v['name']}"
    wb.properties.creator = "QuantiSheet"
    wb.save(path)
    return path


PDF_COLS = 5          # columns beside the description that fit a page


def make_view_pdf(v, project="", comp=None):
    """A layout as a new PDF: each group as a heading with its subtotal
    (and its lines when the layout shows them), then the listed markups
    and the grand total. At most PDF_COLS columns fit beside the
    description; the rest are named at the end (the Excel file has
    all)."""
    import fitz
    from . import estimate_layouts as L
    from . import proposal as P
    comp = comp if comp is not None else P.company()
    keys = [k for k, _l in v["columns"]]
    label_of = dict(v["columns"])
    if len(keys) > PDF_COLS:
        keep = ["total"] if "total" in keys else []
        for k in keys:
            if len(keep) >= PDF_COLS:
                break
            if k not in keep:
                keep.append(k)
        shown = [k for k in keys if k in keep]
    else:
        shown = list(keys)
    dropped = [label_of[k] for k in keys if k not in shown]
    out = fitz.open()
    w = P._Writer(out)
    w.y = P.TOP + 14
    w.text(P.LEFT, w.y, comp.get("name") or "", 11, "hebo")
    w.text(0, w.y + 8, "ESTIMATE", 20, "hebo", P.NAVY, align="right")
    w.y += 26
    sub = f"{v['name']}  |  {_dt.date.today():%B %d, %Y}"
    w.text(0, w.y, f"{project}  |  {sub}" if project else sub, 9,
           color=P.GREY, align="right")
    w.y += 8
    w.rule(P.INK, 0.8)
    colw = 74
    rights = [P.RIGHT - colw * (len(shown) - 1 - i) for i in
              range(len(shown))]
    name_w = (rights[0] - colw if rights else P.RIGHT) - P.LEFT - 6
    w.need(24)
    w.y += 18
    for k, x in zip(shown, rights):
        w.text(0, w.y, label_of[k].upper()[:14], 7, "hebo", P.NAVY,
               align="right", right=x)
    w.text(P.LEFT, w.y, "DESCRIPTION", 7, "hebo", P.NAVY)
    w.y += 4
    w.rule()

    def row(label, cells, size=9.5, font="helv", color=P.GREY, indent=0):
        parts = P._wrap(label, name_w - indent, size, font)
        w.need(13 * len(parts) + 6)
        y = w.y + 12
        for k, x in zip(shown, rights):
            t = _view_amount(cells, shown, k)
            if t:
                w.text(0, y, t, size, font, color, align="right", right=x)
        for i, part in enumerate(parts):
            w.text(P.LEFT + indent, y + 12 * i, part, size, font, color)
        w.y = y + 12 * (len(parts) - 1) + 5

    for kind, label, cells in L.flat_rows(v):
        if kind == "group":
            w.need(40)
            w.y += 6
            row(label, {}, 10, "hebo", P.INK)
            w.rule()
        elif kind == "line":
            row(label, cells, 9, indent=12)
        elif kind == "subtotal":
            row(label, cells, 10, "hebo", P.INK)
            w.rule()
        elif kind == "total":
            w.need(30)
            w.y += 6
            w.page.draw_line((P.RIGHT - 220, w.y), (P.RIGHT, w.y),
                             color=P.INK, width=1)
            row("GRAND TOTAL", cells, 12, "hebo", P.INK)
        else:
            row(label, cells, 10, "helv", P.INK)
    notes = list(v["notes"])
    if dropped:
        notes.append("Columns not on this PDF (they are in the Excel "
                     "file): " + ", ".join(dropped) + ".")
    for n in notes:
        w.para(n, 8, color=P.GREY)
    n = out.page_count
    for i, pg in enumerate(out):
        pg.insert_text((P.LEFT, P.PAPER.height - 30),
                       P._clean(f"{comp.get('name') or ''}  |  Estimate - "
                                f"{v['name']}  |  Page {i + 1} of {n}"),
                       fontsize=7.5, color=P.GREY)
    out.set_metadata({"title": f"Estimate - {project} - {v['name']}"
                      if project else f"Estimate - {v['name']}",
                      "author": comp.get("name", ""),
                      "creator": "QuantiSheet"})
    return out


def save_view_pdf(doc, path, v):
    out = make_view_pdf(v, _project(doc))
    try:
        out.save(path, garbage=3, deflate=True)
    finally:
        out.close()
    return path


def save_view_xlsx(doc, path, v):
    return write_view_xlsx(path, v, _project(doc))


def save_view_csv(doc, path, v):
    return write_view_csv(path, v, _project(doc))
