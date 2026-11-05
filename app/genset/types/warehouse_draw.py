"""The warehouse's own drawings: A-102 Enlarged Office Plan and A-301
Building Section. PyMuPDF is imported inside the drawing functions;
office_subplan() is plain plan data (tests use it without PyMuPDF)."""
import math

EDGE = 0.25                                   # half the exterior wall


def _clip(w, box):
    """The part of an axis-aligned wall inside box (x0, y0, x1, y1), as
    (a, b, offset along the wall to the new a), or None."""
    (ax, ay), (bx, by) = w["a"], w["b"]
    x0, y0, x1, y1 = box
    e = 1e-6
    if abs(ay - by) < e:                       # runs east-west
        if not (y0 - e <= ay <= y1 + e):
            return None
        lo, hi = max(min(ax, bx), x0), min(max(ax, bx), x1)
        if hi - lo < 0.5:
            return None
        a, b = ((lo, ay), (hi, ay)) if bx >= ax else ((hi, ay), (lo, ay))
    elif abs(ax - bx) < e:                     # runs north-south
        if not (x0 - e <= ax <= x1 + e):
            return None
        lo, hi = max(min(ay, by), y0), min(max(ay, by), y1)
        if hi - lo < 0.5:
            return None
        a, b = ((ax, lo), (ax, hi)) if by >= ay else ((ax, hi), (ax, lo))
    else:
        return None
    off = math.hypot(a[0] - ax, a[1] - ay)
    return [a[0], a[1]], [b[0], b[1]], off


def office_subplan(plan):
    """The office block as a plan of its own (same coordinates): its
    rooms, the walls clipped to it and the openings in them. The
    footprint runs to the centreline of the partitions on the east and
    north, so the dimension strings close on them."""
    x0, y0, x1, y1 = plan["warehouse"]["office_rect"]
    box = (0.0, 0.0, x1, y1)
    walls, opens = [], []
    for w in plan["walls"]:
        if w["kind"] == "open":
            continue
        got = _clip(w, box)
        if got is None:
            continue
        a, b, off = got
        nw = dict(w, a=a, b=b)
        L = math.hypot(b[0] - a[0], b[1] - a[1])
        walls.append(nw)
        for o in plan["openings"]:
            if o["wall"] != w["id"]:
                continue
            al = o["along"] - off
            if al - o["width"] / 2 >= 0.5 - 1e-6 and \
                    al + o["width"] / 2 <= L - 0.5 + 1e-6:
                opens.append(dict(o, along=round(al, 3)))
    rooms = [r for r in plan["rooms"] if r.get("zone") == "office"]
    sub = {k: v for k, v in plan.items()
           if k not in ("grid", "garage", "porch", "deck", "truck_court")}
    sub.update(footprint=dict(plan["footprint"], width=x1 - EDGE,
                              depth=y1 - EDGE),
               walls=walls, rooms=rooms, openings=opens)
    return sub


def office_plan(ctx, page):
    """A-102: the office front at a larger scale, every door and window
    tagged (A-101 shows the whole building at a small scale)."""
    from .. import draw, views
    from ..draw import DRAW, GREY
    sub = office_subplan(ctx["plan"])
    m = ctx["Model"](sub)                  # Modulor builds its walls too
    label, ppf = views.plan_view(ctx["doc"], page, sub, m,
                                 title="Enlarged Office Plan",
                                 overall=False, margin_pt=100.0)
    draw.text(page, DRAW.x0 + 10, DRAW.y1 - 80,
              "Dimensions to the outside face of the exterior walls and the "
              "centreline of the partitions to the warehouse. See A-101 for "
              "the whole building.", 10, color=GREY)
    return label, ppf


def section(ctx, page):
    """A-301: a transverse section at mid-length, looking west - the
    dock-high slab, the truck court below it at the dock wall, the
    walls, the roof (low slope inside a parapet, or a 1:12 gable), the
    roof structure band and the clear height (all assumed)."""
    from .. import draw, views
    from ..draw import DRAW, GREY, INK, LIGHT, View
    from ..model import fmt_ftin
    plan = ctx["plan"]
    wh = plan["warehouse"]
    D = plan["footprint"]["depth"]
    lv, roof = plan["level"], plan["roof"]
    eave = lv["plate_height"]
    clear = wh["clear_ht"]
    dock = wh["dock_height"]
    par = float(roof.get("parapet") or 0)
    if roof["type"] == "gable":
        top = eave + roof["pitch"] / 12.0 * D / 2
    else:
        top = eave + par
    court = 40.0                               # ft of truck court drawn
    span = D + court + 20
    label, ppf = views.choose_scale(span, top + dock + 6, DRAW)
    ox = DRAW.x0 + (DRAW.width - span * ppf) / 2 + 20 * ppf
    oy = DRAW.y0 + (DRAW.height - 90 + (top + dock) * ppf) / 2 + 40 - \
        dock * ppf
    v = View(ox, oy, ppf)
    slab = lv["slab"]
    # grades: the front (south) walk a step down, the truck court at the
    # dock wall 4 ft down (assumed)
    draw.line(page, v.p(-20, -0.5), v.p(-EDGE, -0.5), width=1.6)
    draw.line(page, v.p(D + EDGE, -dock), v.p(D + court, -dock), width=1.6)
    draw.rect(page, v.rect(-EDGE, -slab, D + EDGE, 0.0), fill=LIGHT,
              width=0.9)
    # the dock wall's foundation down to the court, and the walls
    draw.rect(page, v.rect(D - EDGE, -dock, D + EDGE, 0.0), fill=draw.POCHE,
              width=0.6)
    wall_top = eave + (par if roof["type"] != "gable" else 0.0)
    for u in (0.0, D):
        draw.rect(page, v.rect(u - EDGE, 0.0, u + EDGE, wall_top),
                  fill=draw.POCHE, width=0.6)
    # columns at the grid lines across the cut (seen beyond)
    for y in plan["grid"]["y"][1:-1]:
        draw.rect(page, v.rect(y - 0.5, 0.0, y + 0.5, clear), color=GREY,
                  width=0.5, fill=(0.93, 0.93, 0.94))
    # the roof structure band and the roof
    sh = page.new_shape()
    if roof["type"] == "gable":
        pts = [(-roof.get("overhang", 0), eave), (D / 2, top),
               (D + roof.get("overhang", 0), eave)]
        sh.draw_polyline([v.p(u, z) for u, z in pts])
        sh.finish(color=INK, width=2.2, closePath=False)
        sh.commit()
        sh = page.new_shape()
        sh.draw_polyline([v.p(0, clear), v.p(D / 2, clear + (top - eave)),
                          v.p(D, clear)])
        sh.finish(color=GREY, width=0.6, dashes="[4 2] 0",
                  closePath=False)
        sh.commit()
        struct_lbl = "RIGID FRAMES AND PURLINS BY THE PEMB SUPPLIER"
    else:
        sh.draw_polyline([v.p(0, eave), v.p(D, eave)])
        sh.finish(color=INK, width=2.2, closePath=False)
        sh.commit()
        draw.line(page, v.p(0.25, clear), v.p(D - 0.25, clear), color=GREY,
                  width=0.6, dashes="[4 2] 0")
        struct_lbl = "ROOF JOISTS AND GIRDERS BY THE STRUCTURAL ENGINEER"
    mid = v.p(D * 0.3, (clear + eave) / 2)
    draw.text(page, mid.x, mid.y + 3, struct_lbl, 8, color=GREY)
    # the clear height and the dock
    draw.dim(page, v.p(D * 0.62, 0.0), v.p(D * 0.62, clear),
             fmt_ftin(clear) + " CLEAR (ASSUMED)", off=0)
    dk = v.p(D + 2, -dock / 2)
    draw.text(page, dk.x, dk.y, f"TRUCK COURT {fmt_ftin(dock)} BELOW FLOOR "
              "(ASSUMED) - DOCK LEVELER AT EACH DOCK DOOR", 8, color=GREY)
    so = v.p(-19, -0.5)
    draw.text(page, so.x, so.y - 4, "FRONT (OFFICE SIDE)", 8, color=GREY)
    marks = [("T.O. SLAB", 0.0), ("TRUCK COURT", -dock),
             ("CLEAR", clear), ("EAVE / BEARING", eave)]
    marks.append(("RIDGE", top) if roof["type"] == "gable" else
                 ("T.O. PARAPET", top))
    x_end = v.p(D + court, 0).x
    for name, z in marks:
        draw.level_line(page, v.p(-20, 0).x, x_end, v.p(0, z).y, name, z)
    draw.title_under(page, DRAW.x0 + 10, DRAW.y1 - 40,
                     "Building Section (transverse, at mid-length)", label)
    area = v.rect(-20, -dock - 2, D + court, top + 3)
    views._register_scale(ctx["doc"], page.number, area, ppf, label,
                          "Building Section")
    return label, ppf
