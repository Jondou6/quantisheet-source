"""build_set(plan, out_path): the starter set - ten sheets for a house
(eleven for a two-story one), eleven for office and retail, and the
building type's own list for the newer types (sheets.py, types/*.py).

G-001 Cover, G-002 General Notes, AS-101 Site Plan, A-101 Floor Plan
(A-102 Level 2), A-102/A-103 Roof Plan, A-201 Exterior Elevations, A-301
Building Section, A-601 Room Schedule, A-602 Door & Window Schedules,
A-701 Quantity Summary (A-801 Accessibility for office and retail). Every
page says FOR REVIEW - NOT FOR SEALING; the plan JSON is saved next to the
PDF (<out>.genset.json), and the quantities as <out>.quantities.csv.

PyMuPDF is imported where a sheet is drawn, so plan_from_brief and
sheets_for work without it."""
import datetime
import json
import logging
import os

from . import CREATOR, DISCLAIMER, model
from .kernel_modulor import Model

log = logging.getLogger(__name__)

SHEETS = [("G-001", "Cover"), ("G-002", "General Notes"),
          ("AS-101", "Site Plan"), ("A-101", "Floor Plan"),
          ("A-102", "Roof Plan"), ("A-201", "Exterior Elevations"),
          ("A-301", "Building Section"), ("A-601", "Room Schedule"),
          ("A-602", "Door & Window Schedules"),
          ("A-701", "Quantity Summary")]


def sheets_for(plan):
    """The sheet list [(number, title)]: ten sheets, eleven for a
    two-story house (a floor plan for each level; the roof plan moves to
    A-103) or for office and retail (A-801); a newer building type's own
    list (sheets.specs_for)."""
    from . import sheets
    return [(s.no, s.title) for s in sheets.specs_for(plan)]


def _cover(page, plan, scales):
    import fitz
    from . import draw, schedules, types
    from .draw import DRAW, GREY, RED
    tp = types.for_plan(plan)
    pj = plan["project"]
    W, D = plan["footprint"]["width"], plan["footprint"]["depth"]
    x, y = DRAW.x0 + 20, DRAW.y0 + 50
    draw.text(page, x, y, pj.get("name") or "Untitled Project", 34,
              bold=True)
    draw.text(page, x, y + 34, pj.get("address") or "ADDRESS TBD", 14,
              color=GREY)
    draw.text(page, x, y + 64, "STARTER CONSTRUCTION DOCUMENT SET", 14,
              bold=True)
    kind = "Single-family residence" if pj["building_type"] == \
        "single_family" else (tp.cover_label or "Small commercial building")
    data = [["Building type", kind],
            ["Work", (pj.get("work") or "new").title()],
            ["Occupancy group (label only)", pj.get("occupancy") or ""],
            ["Gross area (target)", f"{pj.get('gross_sf_target', 0):,.0f} SF"],
            ["Footprint (outside face)",
             f"{model.fmt_ftin(W + 0.5)} x {model.fmt_ftin(D + 0.5)}"
             f"  ({(W + 0.5) * (D + 0.5):,.0f} SF gross" + (
                 f" a floor, {(W + 0.5) * (D + 0.5) * model.stories(plan):,.0f}"
                 " SF in all)" if model.stories(plan) > 1 else ")")],
            ["Rooms (net)", f"{sum(len(lp['rooms']) for lp in model.levels(plan))}"
                            f" rooms, {schedules.room_total(plan):,.0f} SF"],
            ["Lot", _lot_line(plan)],
            ["Garage", (lambda g: f"{g['cars']}-car, attached on the "
                        f"{'east' if g['side'] == 'E' else 'west'}, "
                        f"{model.fmt_ftin(g['width'])} x "
                        f"{model.fmt_ftin(g['depth'])} ({g['area']:,.0f} SF, "
                        "not in the gross area); door into the "
                        f"{g['into'].lower()}")(plan["garage"])
             if plan.get("garage") else "none"],
            ["Porch / deck", ", ".join(
                f"{plan[k]['name'].lower()} {model.fmt_ftin(plan[k]['width'])}"
                f" x {model.fmt_ftin(plan[k]['depth'])}"
                for k in ("porch", "deck") if plan.get(k)) or "none"],
            ["Stories", str(model.stories(plan)) + (
                "  (stair hall, bedrooms upstairs; 10'-0\" floor to floor)"
                if model.stories(plan) > 1 else "")],
            ["Construction type", "by design professional"],
            ["Code analysis", "by design professional"],
            ["Drawn with", f"{CREATOR}, Modulor "
                           f"{plan['source'].get('modulor_version') or ''}"],
            ["Brief read by", "local AI (" + str(plan["source"].get(
                "ai_model")) + ")" if plan["source"].get("ai_used")
             else "form fields and text rules (no AI)"]]
    data = tp.run("cover", plan, data, default=data)
    yy = draw.table(page, x, y + 100, [("PROJECT DATA", 320, "left"),
                                       ("", 600, "left")], data, size=11,
                    row_h=26)
    data_y = yy                          # the foot of the project data
    idx = [[n, t, scales.get(n, "NTS")] for n, t in sheets_for(plan)]
    iy = draw.table(page, x + 1000, y + 100, [("SHEET", 110, "left"),
                                              ("TITLE", 420, "left"),
                                              ("SCALE", 180, "left")], idx,
                    size=11, row_h=26)
    # the set checks itself (audit.py): PASS / WARN / FAIL per check
    from . import audit
    res = plan.get("audit") or audit.audit(plan)
    overall = audit.summary(res)
    col = {"PASS": (0.13, 0.5, 0.2), "WARN": (0.75, 0.5, 0.0),
           "FAIL": RED}
    ay = iy + 40
    draw.text(page, x + 1000, ay, f"SELF-CHECK: {overall}", 12, bold=True,
              color=col[overall])
    draw.text(page, x + 1150, ay, "geometry and consistency of these "
              "drawings - not a code review", 9, color=GREY)
    for i, (st, chk, det) in enumerate(res):
        yy = ay + 22 + i * 18
        draw.text(page, x + 1000, yy, st, 10, bold=True, color=col[st])
        line_ = chk + (f"  ({det})" if det else "")
        txt, sz = draw.fit(line_, 10, False, 660)
        draw.text(page, x + 1050, yy, txt, sz)
    # warnings box
    wy = yy + 50
    warn = plan.get("warnings") or ["None."]
    if wy + 40 + 18 * min(len(warn), 24) > DRAW.y1 - 132 and \
            data_y + 50 < wy:
        # a long sheet index and self-check (a big strip center): the
        # box is in the left column, so under the project data instead
        wy = data_y + 50
    # as many as fit above the disclaimer band (24 at most)
    cap = max(1, min(24, int((DRAW.y1 - 120 - 12 - wy - 40) // 18)))
    if len(warn) > cap > 1:
        warn = warn[:cap - 1] + [f"... and {len(warn) - cap + 1} more (see "
                                 "the .genset.json file)"]
    elif len(warn) > cap:
        warn = [f"{len(warn)} warnings - see the .genset.json file"]
    h = 40 + 18 * len(warn)
    draw.rect(page, fitz.Rect(x, wy, x + 920, wy + h), color=RED, width=1.2)
    draw.text(page, x + 12, wy + 24, "WARNINGS", 12, bold=True, color=RED)
    for i, w in enumerate(warn[:24]):
        draw.text(page, x + 12, wy + 44 + i * 18, "• " + w, 10)
    # disclaimer band
    band = fitz.Rect(DRAW.x0, DRAW.y1 - 120, DRAW.x1, DRAW.y1 - 40)
    draw.rect(page, band, color=RED, width=2, fill=(1, 0.95, 0.95))
    draw.text(page, band.x0 + band.width / 2, band.y0 + 34, DISCLAIMER, 26,
              bold=True, color=RED, align="center")
    draw.text(page, band.x0 + band.width / 2, band.y0 + 60,
              "A computer-generated starting point. Not a permit set. A "
              "licensed design professional must verify all information.",
              12, color=RED, align="center")


def _lot_line(plan):
    s = plan.get("site") or {}
    if not s:
        return "not given"
    fits = "fits the setbacks" if s["on_lot"] and not s["binding"] else \
        "DOES NOT fit the setbacks"
    src = "" if s["lot_from"] == "brief" else " (assumed)"
    return (f"{model.fmt_ftin(s['lot_w'])} x {model.fmt_ftin(s['lot_d'])}"
            f"{src}, {s['coverage']:.0%} coverage, {fits}")


def _notes(page, plan):
    from . import draw, notes
    from .draw import DRAW, GREY
    x, y = DRAW.x0 + 20, DRAW.y0 + 40
    col_w = (DRAW.width - 60) / 2

    def block(x, y, title, items, numbered=True):
        draw.text(page, x, y, title, 16, bold=True)
        y += 30
        for i, n in enumerate(items, 1):
            lines = _wrap(n, 92)
            for j, ln in enumerate(lines):
                prefix = f"{i}." if (numbered and j == 0) else ""
                draw.text(page, x, y, prefix, 11, bold=True)
                draw.text(page, x + 30, y, ln, 11)
                y += 16
            y += 8
        return y

    block(x, y, "GENERAL NOTES", notes.GENERAL)
    pn = plan["notes"].get("project") or []
    src = "(written by the local AI - review)" if plan["notes"].get(
        "from_ai") else "(template)"
    yy = block(x + col_w + 30, y, "PROJECT NOTES", pn)
    draw.text(page, x + col_w + 30, yy + 4, src, 9, color=GREY)


def _wrap(s, width):
    words, lines, cur = s.split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > width:
            lines.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    if cur:
        lines.append(cur)
    return lines or [""]


def build_set(plan, out_path, ask_notes=None, use_ai=True, dxf=False):
    """Draw the set. Returns a summary dict. Raises KernelMissing without
    Modulor (never a geometry fallback), PlanError for an impossible plan.
    Nothing half-written is left at out_path."""
    import fitz
    from .. import safeio
    from . import draw, notes, sheets as sheets_mod
    from .titleblock import start_sheet
    plan = model.clone(plan)
    plan["project"]["date"] = plan["project"].get("date") or \
        datetime.date.today().isoformat()
    model.validate(plan)             # a clear PlanError before Modulor runs
    from . import audit
    plan["audit"] = [list(r) for r in audit.audit(plan)]
    models = [Model(lp) for lp in model.levels(plan)]   # Modulor builds it
    m = models[0]
    plan["source"]["modulor_version"] = m.version
    specs = sheets_mod.specs_for(plan)
    sheets = [(sp.no, sp.title) for sp in specs]
    if not plan["notes"].get("project"):
        pn, from_ai = notes.project_notes(plan, ask=ask_notes) \
            if use_ai else (notes.template_project_notes(plan), False)
        plan["notes"]["project"], plan["notes"]["from_ai"] = pn, from_ai
    plan["notes"]["general"] = list(notes.GENERAL)
    doc = fitz.open()
    scales = {}
    pages = {}
    # every sheet is started in order; the cover is filled in last (its
    # sheet index needs the drawings' scales)
    for sp in specs:
        lbl = "NTS" if sp.nts else " "                   # drawn: below
        pages[sp.no] = start_sheet(doc, plan, sp.no, sp.title, lbl).number
    # a Page object goes stale when pages are added or ops applied, so each
    # step fetches its page fresh by number
    if not plan.get("site"):                 # an older .genset.json
        from . import site as site_mod
        plan["site"], _w = site_mod.site_for(plan)
    ctx = {"doc": doc, "plan": plan, "models": models, "scales": scales,
           "pages": pages, "sheets": sheets, "Model": Model}
    drawn = [sp for sp in specs if not sp.nts]
    for sp in drawn:                         # the drawings, in sheet order
        scales[sp.no], _ = sp.draw(ctx, doc[pages[sp.no]])
    # the scale in the title block of the drawn sheets
    for sp in drawn:
        pg = doc[pages[sp.no]]
        x0 = draw.SHEET_W - draw.MARGIN - draw.TB_W + 16
        y = draw.SHEET_H - draw.MARGIN - 420 + 64 + 18 + 11 + 6
        draw.text(pg, x0, y, scales[sp.no], 11)
    for sp in specs:
        if sp.nts:
            scales[sp.no] = "NTS"
    for sp in specs:                         # the cover first: it is G-001
        if sp.nts:
            sp.draw(ctx, doc[pages[sp.no]])
    from . import quantities
    try:                        # the quantities travel with the PDF, so the
        from .. import estimate  # Quantities panel prices them (0.12.21)
        estimate.write_set_items(doc, quantities.rows(plan), pages["A-701"],
                                 "A-701")
    except Exception:                                     # noqa: BLE001
        log.warning("set quantities not embedded", exc_info=True)
    doc.set_page_labels([{"startpage": i, "prefix": no, "style": ""}
                         for i, (no, _t) in enumerate(sheets)])
    doc.set_metadata({"title": f"{plan['project'].get('name')} - starter "
                               "set", "subject": DISCLAIMER,
                      "creator": CREATOR, "producer": CREATOR,
                      "author": plan["project"].get("firm") or "",
                      "keywords": "generate set; " + DISCLAIMER})
    doc.set_toc([[1, f"{no} {title}", i + 1]
                 for i, (no, title) in enumerate(sheets)])
    out_path = os.path.abspath(out_path)
    side = os.path.splitext(out_path)[0] + ".genset.json"
    # the plan file first, written to a temp file and moved into place, so
    # the PDF and its plan are never out of step (Venice M-5)
    tmp = side + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(plan, f, indent=2)
        safeio.atomic_save(doc, out_path, garbage=3, deflate=True)
        os.replace(tmp, side)
    finally:
        doc.close()
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
    qty_path = os.path.splitext(out_path)[0] + ".quantities.csv"
    try:                        # the takeoff, for the estimate
        quantities.write_csv(plan, qty_path)
    except OSError:
        log.warning("quantities CSV not written", exc_info=True)
        qty_path = None
    dxf_path = None
    if dxf:                     # the plan for CAD, beside the PDF
        from . import dxf_out
        try:
            dxf_path = dxf_out.write(plan, models,
                                     os.path.splitext(out_path)[0] + ".dxf")
        except Exception:                                 # noqa: BLE001
            log.warning("DXF of the plan not written", exc_info=True)
    return {"path": out_path, "sidecar": side, "dxf": dxf_path,
            "quantities": qty_path, "pages": len(sheets),
            "scales": scales, "warnings": list(plan.get("warnings") or []),
            "notes_from_ai": plan["notes"]["from_ai"],
            "self_check": audit.summary(plan["audit"]),
            "modulor": m.version}


def plan_from_brief(text, form=None, sketch=None, sketch_page=0,
                    use_ai=True, ask=None):
    """Brief (+ form fields, + sketch) -> plan JSON."""
    from . import brief, layout
    f = brief.parse(text, form=form, ask=ask, use_ai=use_ai)
    if sketch:
        from . import sketch as sk
        ratio, names, warn = sk.footprint_from(sketch, sketch_page)
        if ratio:
            f["ratio"] = ratio
        if names:
            f["room_names"] = names
        if warn:
            f["warnings"] = list(f.get("warnings") or []) + [warn]
        f["sketch"] = sk.describe(sketch)
    return layout.make_plan(f)
