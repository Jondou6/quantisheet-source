"""The drawn sheets: A-101 floor plan, A-201 exterior elevations, A-301
building section. Each registers its drawing area as a scaled viewport,
so takeoff works the moment the set opens."""
import math

import fitz

from . import draw, kernel_section
from .draw import DRAW, GREY, INK, LIGHT, View
from .model import fmt_ftin

_SCALES_V1 = [("1/4\" = 1'-0\"", 18.0), ("3/16\" = 1'-0\"", 13.5),
              ("1/8\" = 1'-0\"", 9.0), ("3/32\" = 1'-0\"", 6.75),
              ("1/16\" = 1'-0\"", 4.5)]
# 1/32" for the big buildings (a 200,000 SF warehouse); a house or small
# commercial plan always fits at 1/16" or larger, so never reaches it
SCALES = _SCALES_V1 + [("1/32\" = 1'-0\"", 2.25)]
DIM_MARGIN = 6.0          # ft of room around the building for dimensions


def choose_scale(w_ft, h_ft, area, margin=DIM_MARGIN, title_pt=90,
                 margin_pt=None):
    """The largest standard scale at which w x h (plus margin) fits.
    `margin_pt`: a margin in sheet points instead (grid bubbles and
    dimension strings take the same paper at any scale)."""
    for label, ppf in SCALES:
        m = margin_pt / ppf if margin_pt is not None else margin
        if (w_ft + 2 * m) * ppf <= area.width and \
                (h_ft + 2 * m) * ppf <= area.height - title_pt:
            return label, ppf
    return SCALES[-1]


def _register_scale(doc, pno, rect, ppf, label, name):
    from .. import annotate
    annotate.apply_op(doc, annotate.new_op(
        "set_scale", pno, viewport={"name": name, "rect": list(rect),
                                    "ppu": ppf, "unit": "ft",
                                    "label": label}))


def _wall(plan, wid):
    return next(w for w in plan["walls"] if w["id"] == wid)


def _into(plan, w, o):
    """Which side of wall w door o swings to: +1 left of a->b, -1 right."""
    if w["kind"] == "exterior":
        return 1                          # the exterior walls run CCW
    to = next((r for r in plan["rooms"] if r["id"] == o.get("to_room")),
              None)
    if to is None:
        return 1
    (ax, ay), (bx, by) = w["a"], w["b"]
    x0, y0, x1, y1 = to["rect"]
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    cross = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
    return 1 if cross > 0 else -1


def _stair(page, v, st):
    """A straight stair in plan: treads, the outline, and an arrow from
    the bottom with UP (the floor below) or DN (the floor above)."""
    x0, y0, x1, y1 = st["rect"]
    tread = st["tread_in"] / 12.0
    n = st["risers"] - 1                                   # treads
    draw.rect(page, v.rect(x0, y0, x1, y1), width=0.9,
              fill=(0.96, 0.96, 0.97))
    up = st.get("dir", "N") == "N"
    for k in range(1, n):
        y = y0 + k * tread if up else y1 - k * tread
        draw.line(page, v.p(x0, y), v.p(x1, y), width=0.4)
    xm = (x0 + x1) / 2
    bottom, topy = (y0, y1) if up else (y1, y0)
    a, b = (bottom, topy) if st.get("label") == "UP" else (topy, bottom)
    pa, pb = v.p(xm, a + (0.6 if a < b else -0.6)), \
        v.p(xm, b - (0.6 if a < b else -0.6))
    draw.line(page, pa, pb, width=0.8)
    import math as _m
    ang = _m.atan2(pb.y - pa.y, pb.x - pa.x)
    for sgn in (0.45, -0.45):
        draw.line(page, pb, fitz.Point(pb.x - 8 * _m.cos(ang - sgn),
                                       pb.y - 8 * _m.sin(ang - sgn)),
                  width=0.8)
    lab = f"{st.get('label', 'UP')} {st['risers']}R"
    draw.text(page, pa.x + 4, pa.y + (12 if pa.y < pb.y else -4), lab, 8,
              bold=True)


def _garage_plan(page, v, g):
    """The garage beside the house: slab, its own walls, the overhead
    doors (dashed, as is usual for a door overhead) and its tag."""
    from .garage import walls as gwalls
    gx0, gy0, gx1, gy1 = g["rect"]
    draw.rect(page, v.rect(gx0, gy0, gx1, gy1), color=None, width=0,
              fill=(0.95, 0.95, 0.95))
    for r in gwalls(g):
        draw.rect(page, v.rect(*r), color=INK, width=0.4, fill=draw.POCHE)
    for a, b in g["overhead"]:
        for dy in (0.0, 1.5):
            draw.line(page, v.p(a, gy0 + dy), v.p(b, gy0 + dy),
                      color=GREY, width=0.6, dashes="[5 3] 0")
        draw.mark(page, v.p((a + b) / 2, gy0 - 1.6), "OH", "circle", 8)
    c = v.p((gx0 + gx1) / 2, (gy0 + gy1) / 2)
    draw.text(page, c.x, c.y - 4, g["name"], 11, bold=True, align="center")
    draw.text(page, c.x, c.y + 10, g["number"], 9, align="center")
    draw.text(page, c.x, c.y + 22, f"{g['area']:,.0f} SF (NOT HEATED)", 9,
              color=GREY, align="center")


def _outdoor_plan(page, v, plan):
    """The porch (slab, posts, its roof edge dashed) and the deck (boards
    and the guard)."""
    p = plan.get("porch")
    if p:
        x0, y0, x1, y1 = p["rect"]
        draw.rect(page, v.rect(x0, y0, x1, y1), width=0.6,
                  fill=(0.96, 0.96, 0.96))
        sh = page.new_shape()
        sh.draw_rect(v.rect(x0 - 0.5, y0 - 0.5, x1 + 0.5, y1))
        sh.finish(color=GREY, width=0.5, dashes="[5 3] 0")
        sh.commit()
        for px in p["posts"]:
            draw.rect(page, v.rect(px - 0.25, y0, px + 0.25, y0 + 0.5),
                      width=0.4, fill=INK)
        c = v.p((x0 + x1) / 2, (y0 + y1) / 2)
        draw.text(page, c.x, c.y + 3, p["name"], 8, bold=True,
                  align="center")
    d = plan.get("deck")
    if d:
        x0, y0, x1, y1 = d["rect"]
        draw.rect(page, v.rect(x0, y0, x1, y1), width=0.9,
                  fill=(0.97, 0.95, 0.92))
        k = 1.0
        while x0 + k < x1 - 0.01:
            draw.line(page, v.p(x0 + k, y0), v.p(x0 + k, y1),
                      color=LIGHT, width=0.3)
            k += 1.0
        c = v.p((x0 + x1) / 2, (y0 + y1) / 2)
        draw.text(page, c.x, c.y, d["name"], 9, bold=True, align="center")
        draw.text(page, c.x, c.y + 11, f"{d['area']:,.0f} SF, 36\" GUARD",
                  7, color=GREY, align="center")


def plan_view(doc, page, plan, model, title="Floor Plan", overall=True,
              margin_pt=None):
    """A floor plan. `overall`: the O/S dimension strings (an enlarged
    part plan leaves them out); `margin_pt`: paper kept around the plan
    for its dimension strings, in points. A plan with a structural grid
    gets its grid lines and bubbles, and at big-building scales tags only
    the rooms the tag fits in."""
    from .garage import bbox
    from .outdoor import bounds
    W, D = plan["footprint"]["width"], plan["footprint"]["depth"]
    bx0, by0, bx1, by1 = bbox(plan)
    ob = bounds(plan)
    if ob:
        bx0, by0 = min(bx0, ob[0]), min(by0, ob[1])
        bx1, by1 = max(bx1, ob[2]), max(by1, ob[3])
    g = plan.get("garage")
    grid = plan.get("grid")
    if grid or margin_pt:
        label, ppf = choose_scale(bx1 - bx0, by1 - by0, DRAW,
                                  margin_pt=margin_pt or GRID_MARGIN_PT)
    else:
        label, ppf = choose_scale(bx1 - bx0, by1 - by0, DRAW)
    ox = DRAW.x0 + (DRAW.width - (bx1 - bx0) * ppf) / 2 - bx0 * ppf
    oy = DRAW.y0 + (DRAW.height - 90 + (by1 - by0) * ppf) / 2 + by0 * ppf
    v = View(ox, oy, ppf)
    # the dimension strings go below a porch
    extra = (plan["porch"]["depth"] + 0.5) * ppf if plan.get("porch") \
        else 0.0
    # rooms (a faint fill so the plan reads), then the walls from Modulor
    for r in plan["rooms"]:
        draw.rect(page, v.rect(*r["rect"]), color=None, width=0,
                  fill=(0.985, 0.985, 0.99))
    draw.polygons(page, v, model.plan_outline())
    for w in plan["walls"]:             # one space, no partition: dashed
        if w.get("kind") == "open":
            draw.line(page, v.p(*w["a"]), v.p(*w["b"]), color=GREY,
                      width=0.4, dashes="[2 4] 0")
    if grid:
        from .grid import draw_grid
        draw_grid(page, v, grid)
    if g:
        _garage_plan(page, v, g)
    _outdoor_plan(page, v, plan)
    for o in plan["openings"]:
        w = _wall(plan, o["wall"])
        if o["kind"] == "door":
            draw.door(page, v, w, o, _into(plan, w, o))
        elif o["kind"] == "overhead":
            draw.overhead(page, v, w, o)
        else:
            draw.window(page, v, w, o)
    for r in plan["rooms"]:
        if r.get("stair"):
            _stair(page, v, r["stair"])
    for r in plan["rooms"]:
        st = r.get("stair")
        if st:           # the tag in the clear space beside the stair
            hx0, hy0, hx1, hy1 = r["rect"]
            sx0, sy0, sx1, sy1 = st["rect"]
            free = (hy0, sy0) if sy0 - hy0 >= hy1 - sy1 else (sy1, hy1)
            draw.room_tag(page, v, dict(r, rect=[hx0, free[0], hx1,
                                                 free[1]]), size=8)
            continue
        if grid and min(r["rect"][2] - r["rect"][0],
                        r["rect"][3] - r["rect"][1]) * ppf < 60:
            continue              # too small at this scale: see the part plan
        draw.room_tag(page, v, r, size=11 if ppf >= 13 else 9)
    # marks: doors just inside, windows just outside
    for o in plan["openings"]:
        w = _wall(plan, o["wall"])
        (cx, cy), (ux, uy), (nx, ny) = draw._wall_frame(w, o["along"])
        if grid and ppf < 9 and o["kind"] != "overhead" and (
                o["kind"] == "window" or w["kind"] != "exterior"):
            continue              # the office's marks are on its part plan
        if o["kind"] == "overhead":
            off = -(w["thickness"] / 2 + 2.0 + 10.0 / ppf)
            draw.mark(page, v.p(cx + nx * off, cy + ny * off), o["mark"],
                      "circle", 7)
        elif o["kind"] == "door":
            into = _into(plan, w, o)
            off = (w["thickness"] / 2 + o["width"] * 0.55) * into
            at = v.p(cx + nx * off + ux * o["width"] * 0.25,
                     cy + ny * off + uy * o["width"] * 0.25)
            draw.mark(page, at, o["mark"], "circle", 8)
        else:
            off = -(w["thickness"] / 2 + 1.1)
            draw.mark(page, v.p(cx + nx * off, cy + ny * off), o["mark"],
                      "hex", 8)
    # dimensions: overall, and the room breaks along the south and west
    t = 0.25
    xs = sorted({round(x, 3) for r in plan["rooms"] if abs(r["rect"][1] - t)
                 < 1e-6 for x in (r["rect"][0], r["rect"][2])})
    ys = sorted({round(y, 3) for r in plan["rooms"] if abs(r["rect"][0] - t)
                 < 1e-6 for y in (r["rect"][1], r["rect"][3])})
    # strings run to the outside face of the exterior walls (Grok N4), so
    # a takeoff of the outline agrees with the printed overall size
    o = t                                   # half the exterior wall
    xs = [-o] + [x for x in xs if t < x < W - t] + [W + o]
    ys = [-o] + [y for y in ys if t < y < D - t] + [D + o]
    for a, b in zip(xs, xs[1:]):
        draw.dim(page, v.p(b, -o), v.p(a, -o), fmt_ftin(b - a),
                 off=-52 - extra)
    if overall:
        draw.dim(page, v.p(W + o, -o), v.p(-o, -o),
                 fmt_ftin(W + 2 * o) + " O/S", off=-80 - extra)
    # west strings clear a garage on the west (Venice review M8)
    wx = ((g["width"] + g["overhang"]) * ppf + 10) if g and \
        g["side"] == "W" else 0
    for a, b in zip(ys, ys[1:]):
        draw.dim(page, v.p(-o, a), v.p(-o, b), fmt_ftin(b - a),
                 off=-52 - wx)
    if overall:
        draw.dim(page, v.p(-o, -o), v.p(-o, D + o),
                 fmt_ftin(D + 2 * o) + " O/S", off=-80 - wx)
    if len(ys) == 2:
        # nothing breaks the west wall (a side hall runs its length): the
        # room breaks go on the east side instead
        ye = sorted({round(y, 3) for r in plan["rooms"]
                     if abs(r["rect"][2] - (W - t)) < 1e-6
                     for y in (r["rect"][1], r["rect"][3])})
        ye = [-o] + [y for y in ye if t < y < D - t] + [D + o]
        ex = ((g["width"] + g["overhang"]) * ppf + 10) if g and \
            g["side"] == "E" else 0
        if len(ye) > 2:
            for a, b in zip(ye, ye[1:]):
                draw.dim(page, v.p(W + o, b), v.p(W + o, a), fmt_ftin(b - a),
                         off=-52 - ex)
    draw.north_arrow(page, fitz.Point(DRAW.x1 - 60, DRAW.y0 + 60))
    if g:                   # the garage's width, beside the house's
        gx0, _gy0, gx1, _gy1 = g["rect"]
        a, b = (gx0, gx1 + 0.25) if g["side"] == "E" else (gx0 - 0.25, gx1)
        draw.dim(page, v.p(b, -0.25), v.p(a, -0.25), fmt_ftin(b - a),
                 off=-52 - extra)
    draw.title_under(page, DRAW.x0 + 10, DRAW.y1 - 40, title, label)
    area = v.rect(bx0 - DIM_MARGIN, min(by0, 0) - DIM_MARGIN,
                  bx1 + DIM_MARGIN, by1 + DIM_MARGIN)
    _register_scale(doc, page.number, area, ppf, label, title)
    return label, ppf


GRID_MARGIN_PT = 150.0    # paper around a gridded plan: dims + bubbles

FACES = [("S", "South Elevation"), ("E", "East Elevation"),
         ("N", "North Elevation"), ("W", "West Elevation")]
FACE_WALL = {"S": "W1", "E": "W2", "N": "W3", "W": "W4"}


def elevation_layout(plan):
    """"quad" or "full" - see sheets.elevation_layout."""
    from .sheets import elevation_layout as _el
    return _el(plan)


def _garage_face(g, face, W, D):
    """How the garage shows on an elevation: None (hidden behind the
    house), ("side", wall u-range, roof u-range) beside the house on the
    front and back, or ("gable", u-range) in front of a side face."""
    gx0, gy0, gx1, gy1 = g["rect"]
    o, gov = 0.25, g["overhang"]
    east = g["side"] == "E"
    if face == "S":
        return ("side", (W + o, gx1 + o), (W + o, gx1 + o + gov)) if east \
            else ("side", (gx0 - o, -o), (gx0 - o - gov, -o))
    if face == "N":
        return ("side", (W - gx1 - o, -o), (W - gx1 - o - gov, -o)) \
            if east else ("side", (W + o, W - gx0 + o),
                          (W + o, W - gx0 + o + gov))
    if face == "E" and east:
        return ("gable", (gy0 - o, gy1 + o))
    if face == "W" and not east:
        return ("gable", (D - gy1 - o, D - gy0 + o))
    return None


def _draw_garage_face(page, v, g, how):
    plate = g["plate_height"]
    p = g["pitch"] / 12.0
    gov = g["overhang"]
    top = plate + p * g["depth"] / 2
    eave = plate - p * gov
    wall_fill, roof_fill = (0.95, 0.95, 0.955), (0.9, 0.9, 0.91)
    if how[0] == "side":
        (a, b), (ra, rb) = how[1], how[2]
        draw.polygons(page, v, [[(ra, eave), (rb, eave), (rb, top),
                                 (ra, top)]], fill=roof_fill, width=0.9)
        draw.polygons(page, v, [[(a, 0), (b, 0), (b, plate), (a, plate)]],
                      fill=wall_fill, width=0.9)
    else:
        a, b = how[1]
        draw.polygons(page, v, [[(a - gov, eave), ((a + b) / 2, top),
                                 (b + gov, eave)]], fill=roof_fill,
                      width=0.9)
        draw.polygons(page, v, [[(a, 0), (b, 0), (b, plate), (a, plate)]],
                      fill=wall_fill, width=0.9)
        draw.text(page, v.p((a + b) / 2, 0).x, v.p(0, plate / 2).y,
                  "GARAGE", 8, color=GREY, align="center")


def _outdoor_u(plan, face, W, D):
    """The u-ranges the porch and deck take on a face's elevation."""
    out = []
    for key in ("porch", "deck"):
        it = plan.get(key)
        if not it or (key, face) in (("porch", "N"), ("deck", "S")):
            continue                    # hidden behind the house
        x0, y0, x1, y1 = it["rect"]
        if face == "S":
            out.append((x0 - 0.5, x1 + 0.5))
        elif face == "N":
            out.append((W - x1 - 0.5, W - x0 + 0.5))
        elif face == "E":
            out.append((y0 - 0.5, y1 + 0.5))
        else:
            out.append((D - y1 - 0.5, D - y0 + 0.5))
    return out


def _outdoor_face(page, v, plan, face, W, D):
    """Porch posts and its shed roof; the deck's guard. Seen from the
    front or back they stand in front of the house; from the sides, beside
    it."""
    p = plan.get("porch")
    if p and face == "N":
        p = None                    # behind the house from the back
    if p:
        x0, y0, x1, y1 = p["rect"]
        lo, hi = p["roof_low"], p["roof_high"]
        if face in ("S", "N"):
            xs = p["posts"] if face == "S" else [W - x for x in p["posts"]]
            a, b = (x0, x1) if face == "S" else (W - x1, W - x0)
            draw.polygons(page, v, [[(a - 0.5, lo - 0.6), (b + 0.5,
                                                          lo - 0.6),
                                     (b + 0.5, lo), (a - 0.5, lo)]],
                          fill=(0.9, 0.9, 0.91), width=0.8)
            if face == "S":
                for px in xs:
                    draw.rect(page, v.rect(px - 0.25, -0.5, px + 0.25,
                                           lo - 0.6), width=0.6,
                              fill=(0.97, 0.97, 0.97))
                draw.line(page, v.p(a, -0.5), v.p(b, -0.5), width=0.8)
        else:
            # from the side: a post and the roof sloping down to the front
            u_out, u_in = (y0, y1) if face == "E" else (D - y0, D - y1)
            draw.polygons(page, v, [[(u_out - 0.5, lo - 0.6),
                                     (u_out - 0.5, lo), (u_in, hi),
                                     (u_in, hi - 0.6)]] if face == "E" else
                          [[(u_out + 0.5, lo - 0.6), (u_out + 0.5, lo),
                            (u_in, hi), (u_in, hi - 0.6)]],
                          fill=(0.9, 0.9, 0.91), width=0.8)
            pu = u_out + (0.25 if face == "E" else -0.25)
            draw.rect(page, v.rect(pu - 0.25, -0.5, pu + 0.25, lo - 0.6),
                      width=0.6, fill=(0.97, 0.97, 0.97))
    d = plan.get("deck")
    if d:
        x0, y0, x1, y1 = d["rect"]
        g = d["guard"]
        if face in ("S", "N"):
            if face == "S":
                return                      # behind the house
            a, b = W - x1, W - x0
        elif face == "E":
            a, b = y0, y1
        else:
            a, b = D - y1, D - y0
        draw.polygons(page, v, [[(a, -0.6), (b, -0.6), (b, 0.0),
                                 (a, 0.0)]], fill=(0.85, 0.8, 0.72),
                      width=0.6)
        draw.line(page, v.p(a, g), v.p(b, g), width=0.9)
        u = a
        while u <= b + 1e-6:
            draw.line(page, v.p(u, 0.0), v.p(u, g), width=0.3)
            u += 0.5


def elevations(doc, page, plan, model, faces=None):
    """`model`: the Modulor model of each floor (a list for a two-story
    house, one model otherwise); upper floors stand on the floor below.
    `faces`: None draws all four in quarters; ("S", "N") or ("E", "W")
    draws those two, each in a full-width half of the sheet."""
    from .model import levels, top_level
    models = model if isinstance(model, (list, tuple)) else [model]
    lvls = levels(plan)
    W, D = plan["footprint"]["width"], plan["footprint"]["depth"]
    roof = plan["roof"]
    lv = plan["level"]
    floor = lv["floor_elev"]
    tl = top_level(plan)
    plate = tl["floor_elev"] + tl["plate_height"]       # the roof's plate
    top = kernel_section.ridge_height(plan)
    ov = float(roof.get("overhang") or 0)
    gx, gy = DRAW.width / 2, DRAW.height / 2
    if faces is None:
        todo = list(FACES)
        quads = [fitz.Rect(DRAW.x0 + (i % 2) * gx, DRAW.y0 + (i // 2) * gy,
                           DRAW.x0 + (i % 2 + 1) * gx,
                           DRAW.y0 + (i // 2 + 1) * gy)
                 for i in range(4)]
    else:
        todo = [f for f in FACES if f[0] in faces]
        quads = [fitz.Rect(DRAW.x0, DRAW.y0 + i * gy, DRAW.x1,
                           DRAW.y0 + (i + 1) * gy) for i in range(len(todo))]
    gar = plan.get("garage")
    extra = (gar["width"] + gar["overhang"]) if gar else 0.0
    longest = max(W + extra, D) + 2 * ov
    if faces is not None:       # these faces only: their own longest
        longest = max((W + extra) if f in ("S", "N") else D
                      for f, _t in todo) + 2 * ov
    if faces is None:
        label, ppf = choose_scale(longest, top, quads[0], margin=4,
                                  title_pt=80)
    else:                       # level marks and their names past the end
        label, ppf = choose_scale(longest, top, quads[0], title_pt=80,
                                  margin_pt=110)
    later = []                    # scales go in after all drawing is done
    for (face, title), q in zip(todo, quads):
        span = W if face in ("S", "N") else D
        gf = _garage_face(gar, face, W, D) if gar else None
        u0, u1 = 0.0, span
        if gf and gf[0] == "side":
            u0, u1 = min(u0, gf[2][0]), max(u1, gf[2][1])
        for lo_, hi_ in _outdoor_u(plan, face, W, D):
            u0, u1 = min(u0, lo_), max(u1, hi_)
        ox = q.x0 + (q.width - (u1 - u0) * ppf) / 2 - 30 - u0 * ppf
        oy = q.y1 - 90
        v = View(ox, oy, ppf)
        # grade, 6 ft past the building each way - kept on this face's part
        # of the sheet: a set drawn big enough (the 2,000 SF restaurant,
        # the 2-story house, the office) ran 6 ft off the left of the
        # drawing area.
        ga, gb = v.p(u0 - 6, 0), v.p(u1 + 6, 0)
        if ga.x < q.x0:
            ga = fitz.Point(q.x0, ga.y)
        if gb.x > q.x1:
            gb = fitz.Point(q.x1, gb.y)
        draw.line(page, ga, gb, width=1.6)
        if gf and gf[0] == "side":      # beside the house, under its eave
            _draw_garage_face(page, v, gar, gf)
        # roof first (behind), then the wall face from Modulor
        if roof["type"] == "gable":
            rise_ov = roof["pitch"] / 12.0 * ov
            eave = plate - rise_ov
            eaves = ("E", "W") if roof.get("ridge_dir") == "y" else \
                ("S", "N")             # the faces under an eave
            if face in eaves:
                pts = [(-ov, eave), (span + ov, eave), (span + ov, top),
                       (-ov, top)]
            else:
                pts = [(-ov, eave), (span / 2, top), (span + ov, eave)]
            draw.polygons(page, v, [pts], fill=(0.93, 0.93, 0.94), width=0.9)
        else:
            draw.polygons(page, v, [[(0, plate), (span, plate),
                                     (span, top), (0, top)]],
                          fill=(0.93, 0.93, 0.94), width=0.9)
        # the corner returns: the face runs to the outside of the walls at
        # either end (Grok N4: elevations were 6" short of the plan)
        o = 0.25
        wid = FACE_WALL[face]
        prev_plate = None
        for lp, m in zip(lvls, models):
            f0 = lp["level"]["floor_elev"]
            p0 = f0 + lp["level"]["plate_height"]
            faces = [[(u, z + f0) for u, z in poly]
                     for poly in m.elevation(face)]
            band = [[(-o, prev_plate), (span + o, prev_plate),
                     (span + o, f0), (-o, f0)]] if prev_plate is not None \
                and f0 > prev_plate else []
            draw.polygons(page, v, faces + band + [
                [(-o, f0), (0, f0), (0, p0), (-o, p0)],
                [(span, f0), (span + o, f0), (span + o, p0),
                 (span, p0)]], fill=(0.97, 0.97, 0.975), width=0.9)
            prev_plate = p0
        # openings from the plan (Modulor gives the bare outline -
        # workaround 3): frames, and a meeting rail on the windows
        for o in [dict(o_, _f0=lp["level"]["floor_elev"]) for lp in lvls
                  for o_ in lp["openings"]]:
            if o["wall"] != wid:
                continue
            f0 = o["_f0"]
            a, b = o["along"] - o["width"] / 2, o["along"] + o["width"] / 2
            if o["kind"] in ("door", "overhead"):
                z0, z1 = f0, f0 + o["height"]
            else:
                z0, z1 = f0 + o["sill"], f0 + o["sill"] + o["height"]
            draw.rect(page, v.rect(a, z0, b, z1), width=0.9,
                      fill=(0.82, 0.86, 0.9) if o["kind"] == "window"
                      else (0.9, 0.88, 0.85))
            if o["kind"] == "window":
                zm = (z0 + z1) / 2
                draw.line(page, v.p(a, zm), v.p(b, zm), width=0.6)
            elif o["kind"] == "overhead":   # the sections, as the garage's
                for k in (1, 2, 3):
                    draw.line(page, v.p(a, z0 + (z1 - z0) * k / 4),
                              v.p(b, z0 + (z1 - z0) * k / 4), width=0.4)
            draw.mark(page, v.p((a + b) / 2, z1 + 1.6), o["mark"],
                      "hex" if o["kind"] == "window" else "circle", 7)
        if gf and gf[0] == "gable":     # in front of this side of the house
            _draw_garage_face(page, v, gar, gf)
        _outdoor_face(page, v, plan, face, W, D)
        if gf and face in ("S", "N"):
            gx0_, _y, gx1_, _y2 = gar["rect"]
            for a, b in (gar["overhead"] if face == "S" else []):
                h = gar["overhead_h"]
                draw.rect(page, v.rect(a, 0, b, h), width=0.9,
                          fill=(0.9, 0.88, 0.85))
                for k in (1, 2, 3):
                    draw.line(page, v.p(a, h * k / 4), v.p(b, h * k / 4),
                              width=0.4)
                draw.mark(page, v.p((a + b) / 2, h + 1.6), "OH", "circle",
                          7)
        # levels
        x_end = v.p(u1 + ov + 2, 0).x
        x_start = v.p(u0 - ov - 2, 0).x
        marks = [("FLOOR", floor)] + [
            (f"LEVEL {i + 1}", lp["level"]["floor_elev"])
            for i, lp in enumerate(lvls) if i] + [
            ("PLATE", plate),
            ("RIDGE" if roof["type"] == "gable" else "T.O. PARAPET", top)]
        for name, z in marks:
            draw.level_line(page, x_start, x_end, v.p(0, z).y, name, z)
        draw.title_under(page, q.x0 + 20, q.y1 - 40, title, label,
                         num=str(FACES.index((face, title)) + 1))
        if faces is not None:          # the dock wall's grade, explained
            note = next(((plan.get(k) or {}).get("elev_note", {}).get(face)
                         for k in ("warehouse", "strip", "restaurant")
                         if (plan.get(k) or {}).get("elev_note")), None)
            if note:
                draw.text(page, q.x0 + 20, q.y1 - 12, note, 9, color=GREY)
        later.append((fitz.Rect(q.x0 + 4, q.y0 + 4, q.x1 - 4, q.y1 - 60),
                      title))
    pno = page.number
    for rect, title in later:
        _register_scale(doc, pno, rect, ppf, label, title)
    return label, ppf


def section(doc, page, plan):
    geo = kernel_section.section_geometry(plan)
    D = geo.get("span", plan["footprint"]["depth"])     # the cut's length
    top = geo["top"]
    label, ppf = choose_scale(D + 4, top + 2, DRAW)
    ox = DRAW.x0 + (DRAW.width - D * ppf) / 2
    oy = DRAW.y0 + (DRAW.height - 90 + top * ppf) / 2 + 40
    v = View(ox, oy, ppf)
    u0, u1, z0, z1 = geo["slab"]
    draw.rect(page, v.rect(u0, z0, u1, z1), fill=LIGHT, width=0.9)
    draw.line(page, v.p(u0 - 6, z0), v.p(u1 + 6, z0), width=1.6)    # grade
    for a, b, za, zb in geo.get("floors", ()):
        draw.rect(page, v.rect(a, za, b, zb), fill=LIGHT, width=0.9)
    for a, b, za, zb, kind in geo["walls"]:
        draw.rect(page, v.rect(a, za, b, zb), fill=draw.POCHE, width=0.6)
    if geo.get("stair"):                    # the stair, cut through
        sh = page.new_shape()
        sh.draw_polyline([v.p(u, z) for u, z in geo["stair"]])
        sh.finish(color=INK, width=1.4, closePath=False)
        sh.commit()
    # ceilings between the exterior walls
    for c in geo.get("ceilings") or [geo["ceiling"]]:
        draw.line(page, v.p(0.25, c), v.p(D - 0.25, c), color=GREY,
                  width=0.6, dashes="[4 2] 0")
    roof = geo["roof"]
    sh = page.new_shape()
    sh.draw_polyline([v.p(u, z) for u, z in roof])
    sh.finish(color=INK, width=2.2, closePath=False)   # eave to eave: open
    sh.commit()
    if geo.get("ridge_beyond"):       # dashed, with the gable ends to it
        (ua, zr), (ub, _z) = geo["ridge_beyond"]
        za = roof[0][1]
        sh = page.new_shape()
        sh.draw_polyline([v.p(ua, za), v.p(ua, zr), v.p(ub, zr),
                          v.p(ub, za)])
        sh.finish(color=GREY, width=0.8, dashes="[6 3] 0",
                  closePath=False)
        sh.commit()
        mid = v.p((ua + ub) / 2, zr)
        draw.text(page, mid.x, mid.y - 6, "RIDGE (BEYOND)", 8, color=GREY,
                  align="center")
    if "parapet" in geo:
        for u in (0.0, D):
            draw.rect(page, v.rect(u - 0.25, geo["plate"], u + 0.25,
                                   geo["parapet"]), fill=draw.POCHE)
    x_end = v.p(D + 3, 0).x
    lvls = []
    ceil = geo.get("ceilings") or [geo["ceiling"]]
    for name, z in geo["levels"] + [
            ("CEILING" if len(ceil) == 1 else f"CEILING L{i + 1}", c)
            for i, c in enumerate(ceil)]:
        same = next((i for i, (_n, zz) in enumerate(lvls)
                     if abs(zz - z) < 0.25), None)
        if same is None:
            lvls.append((name, z))
        else:                          # one marker, both names
            lvls[same] = (lvls[same][0] + " / " + name, lvls[same][1])
    for name, z in lvls:
        draw.level_line(page, v.p(-3, 0).x, x_end, v.p(0, z).y, name, z)
    draw.title_under(page, DRAW.x0 + 10, DRAW.y1 - 40,
                     ("Building Section (lengthwise, through the stair)"
                      if plan["roof"].get("ridge_dir") == "y" else
                      "Building Section (transverse, through the stair)")
                     if geo.get("stair") else
                     "Building Section (across, at mid-depth)"
                     if geo.get("turned") else
                     "Building Section (transverse, at mid-length)", label)
    area = v.rect(-4, -2, D + 4, top + 3)
    _register_scale(doc, page.number, area, ppf, label, "Building Section")
    return label, ppf


# ---- roof plan and site plan (0.12.17) ----------------------------------
def _arrow(page, a, b, width=0.8):
    """A slope arrow from a to b (sheet points), head at b (downhill)."""
    import math as _m
    draw.line(page, a, b, width=width)
    ang = _m.atan2(b.y - a.y, b.x - a.x)
    for s in (0.45, -0.45):
        draw.line(page, b, fitz.Point(b.x - 9 * _m.cos(ang - s),
                                      b.y - 9 * _m.sin(ang - s)),
                  width=width)


def roof_plan(doc, page, plan):
    """A-102: the roof outline at the eaves, the ridge, slope arrows and
    the building's outside face dashed below."""
    from .garage import bbox
    W, D = plan["footprint"]["width"], plan["footprint"]["depth"]
    roof = plan["roof"]
    ov = float(roof.get("overhang") or 0)
    o = 0.25
    bx0, _by0, bx1, by1 = bbox(plan)
    pd = (plan["porch"]["depth"] + 0.5) if plan.get("porch") else 0.0
    label, ppf = choose_scale(bx1 - bx0 + 2 * ov, max(D, by1) + pd + 2 * ov,
                              DRAW)
    ox = DRAW.x0 + (DRAW.width - (bx1 - bx0) * ppf) / 2 - bx0 * ppf
    oy = DRAW.y0 + (DRAW.height - 90 + (max(D, by1) + pd) * ppf) / 2 - \
        pd * ppf
    v = View(ox, oy, ppf)
    gar = plan.get("garage")
    if gar:                  # the garage's lower gable roof, under the eave
        gx0, gy0, gx1, gy1 = gar["rect"]
        gov = gar["overhang"]
        if gar["side"] == "E":
            ga, gb = W + o, gx1 + o + gov
        else:
            ga, gb = gx0 - o - gov, -o
        draw.rect(page, v.rect(ga, gy0 - o - gov, gb, gy1 + o + gov),
                  width=1.4, fill=(0.93, 0.93, 0.94))
        ym = (gy0 + gy1) / 2
        draw.line(page, v.p(ga, ym), v.p(gb, ym), width=1.2)
        xm = (ga + gb) / 2
        for top, bot in ((ym - 1.0, gy0 + 1.0), (ym + 1.0, gy1 - 1.0)):
            _arrow(page, v.p(xm, top), v.p(xm, bot))
        draw.text(page, v.p(xm, 0).x + 6, v.p(0, ym - 4).y,
                  f"{gar['pitch']:g}:12", 9)
        draw.text(page, v.p(xm, 0).x, v.p(0, ym + 2).y, "GARAGE ROOF", 9,
                  bold=True, align="center")
    por = plan.get("porch")
    if por:                         # the porch's shed roof, sloping out
        px0, py0, px1, py1 = por["rect"]
        draw.rect(page, v.rect(px0 - 0.5, py0 - 0.5, px1 + 0.5, py1),
                  width=1.2, fill=(0.93, 0.93, 0.94))
        pm = (px0 + px1) / 2
        _arrow(page, v.p(pm, py1 - 0.5), v.p(pm, py0 + 0.3))
        rise = por["roof_high"] - por["roof_low"]
        draw.text(page, v.p(pm, 0).x + 6, v.p(0, (py0 + py1) / 2).y,
                  f"{rise / (por['depth'] + 0.5) * 12:.0f}:12 PORCH ROOF",
                  8)
    x0, y0, x1, y1 = -o - ov, -o - ov, W + o + ov, D + o + ov
    draw.rect(page, v.rect(x0, y0, x1, y1), width=1.8,
              fill=(0.95, 0.95, 0.96))
    # the walls below
    draw.rect(page, v.rect(-o, -o, W + o, D + o), color=GREY, width=0.6)
    sh = page.new_shape()
    sh.draw_rect(v.rect(-o, -o, W + o, D + o))
    sh.finish(color=GREY, width=0.6, dashes="[6 4] 0")
    sh.commit()
    size = 10 if ppf >= 9 else 8
    if roof["type"] == "gable" and roof.get("ridge_dir") == "y":
        xm = W / 2                     # the ridge north-south (0.12.21)
        draw.line(page, v.p(xm, y0), v.p(xm, y1), width=1.6)
        draw.text(page, v.p(xm, D / 2).x + 6, v.p(xm, D / 2).y, "RIDGE",
                  size, bold=True)
        pitch = f"{roof['pitch']:g}:12"
        for frac in (0.25, 0.75):
            y = D * frac
            for a, b in ((xm - 1.0, x0 + 2.0), (xm + 1.0, x1 - 2.0)):
                _arrow(page, v.p(a, y), v.p(b, y))
                mid = v.p((a + b) / 2, y)
                draw.text(page, mid.x, mid.y - 6, pitch, size,
                          align="center")
        for y, side in ((-o + 1.0, "SOUTH"), (D + o - 1.0, "NORTH")):
            p_ = v.p(W * 0.5, y)
            draw.text(page, p_.x, p_.y + (-4 if side == "SOUTH" else 12),
                      "GABLE END (RAKE)", size - 1, color=GREY,
                      align="center")
        for x, side in ((x0, "W"), (x1, "E")):
            p_ = v.p(x, D * 0.5)
            draw.text(page, p_.x + (6 if side == "W" else -6), p_.y + 16,
                      "EAVE / GUTTER", size - 1, color=GREY,
                      align="left" if side == "W" else "right")
        note = (f"Gable roof, {pitch}, ridge north-south (gable to the "
                f"street), {fmt_ftin(ov)} overhang. Roofing, underlayment, "
                "ventilation and framing by the design professional.")
    elif roof["type"] == "gable":
        ym = D / 2
        draw.line(page, v.p(x0, ym), v.p(x1, ym), width=1.6)
        draw.text(page, v.p(W / 2, ym).x, v.p(W / 2, ym).y - 6, "RIDGE",
                  size, bold=True, align="center")
        pitch = f"{roof['pitch']:g}:12"
        for frac in (0.25, 0.75):
            x = W * frac
            for top, bot in ((ym - 1.0, y0 + 2.0), (ym + 1.0, y1 - 2.0)):
                _arrow(page, v.p(x, top), v.p(x, bot))
                mid = v.p(x, (top + bot) / 2)
                draw.text(page, mid.x + 6, mid.y, pitch, size)
        for x, side in ((-o + 1.0, "WEST"), (W + o - 1.0, "EAST")):
            p_ = v.p(x, D * 0.62)               # inside the wall line
            draw.text(page, p_.x, p_.y, "GABLE END (RAKE)", size - 1,
                      color=GREY, align="left" if side == "WEST" else
                      "right")
        for y, txt in ((y0, "EAVE / GUTTER"), (y1, "EAVE / GUTTER")):
            p_ = v.p(W * 0.5, y)
            draw.text(page, p_.x, p_.y + (14 if y == y0 else -6), txt,
                      size - 1, color=GREY, align="center")
        note = (f"Gable roof, {pitch}, ridge east-west, {fmt_ftin(ov)} "
                "overhang. Roofing, underlayment, ventilation and framing "
                "by the design professional.")
    else:
        # low-slope roof inside a parapet: slope to two drains
        t = 0.67
        sh = page.new_shape()
        sh.draw_rect(v.rect(-o + t, -o + t, W + o - t, D + o - t))
        sh.finish(color=INK, width=0.6)
        sh.commit()
        drains = [(W * 0.25, D / 2), (W * 0.75, D / 2)]
        for dx, dy in drains:
            c = v.p(dx, dy)
            sh = page.new_shape()
            sh.draw_circle(c, 6)
            sh.finish(color=INK, width=0.8)
            sh.commit()
            draw.text(page, c.x, c.y + 18, "RD", size, bold=True,
                      align="center")
            for tx, ty in ((dx, D - 2.0), (dx, 2.0),
                           (dx - W * 0.2, dy), (dx + W * 0.2, dy)):
                a = v.p(tx, ty)
                b = fitz.Point(a.x + (c.x - a.x) * 0.8,
                               a.y + (c.y - a.y) * 0.8)
                _arrow(page, a, b)
        draw.text(page, v.p(W / 2, D).x, v.p(W / 2, D).y + 22,
                  "PARAPET", size, color=GREY, align="center")
        slope = {0.25: "1/4", 0.125: "1/8", 0.5: "1/2"}.get(
            roof["pitch"], f"{roof['pitch']:g}")
        draw.text(page, v.p(W * 0.25, D / 2).x + 30,
                  v.p(W * 0.25, D / 2).y - 10, f"{slope}:12 MIN.", size)
        note = (f"Low-slope roof, {slope}:12 minimum to roof drains "
                f"(RD), {fmt_ftin(float(roof.get('parapet') or 0))} parapet. "
                "Drain sizes, overflow, membrane and insulation by the design "
                "professional.")
    draw.dim(page, v.p(x1, y0), v.p(x0, y0), fmt_ftin(x1 - x0), off=-40)
    draw.dim(page, v.p(x0, y0), v.p(x0, y1), fmt_ftin(y1 - y0), off=-40)
    draw.north_arrow(page, fitz.Point(DRAW.x1 - 60, DRAW.y0 + 60))
    draw.text(page, DRAW.x0 + 10, DRAW.y1 - 80, note, 10, color=GREY)
    draw.title_under(page, DRAW.x0 + 10, DRAW.y1 - 40, "Roof Plan", label)
    area = v.rect(min(x0, bx0 - 3) - DIM_MARGIN, y0 - DIM_MARGIN,
                  max(x1, bx1 + 3) + DIM_MARGIN, max(y1, by1 + 3) + DIM_MARGIN)
    _register_scale(doc, page.number, area, ppf, label, "Roof Plan")
    return label, ppf


SITE_SCALES = _SCALES_V1 + [("1\" = 20'-0\"", 3.6), ("1\" = 30'-0\"", 2.4),
                        ("1\" = 40'-0\"", 1.8), ("1\" = 50'-0\"", 1.44),
                        ("1\" = 100'-0\"", 0.72)]


def _walk_end(plan):
    """Where the front walk meets the house: the porch's front edge when
    there is a porch at the door, else the wall."""
    p = plan.get("porch")
    return p["rect"][1] if p else -0.25


# ---- AS-101 as data: the layout first, then the drawing --------------------
# site_layout() works out every rect, line and label of the site plan in
# sheet points (no PyMuPDF needed), so the tests can check that no label
# sits on linework; site_plan() then only draws the list.
GREEN = (0.2, 0.5, 0.25)
_DRAW_BOX = (draw.MARGIN + 36, draw.MARGIN + 36,
             draw.SHEET_W - draw.MARGIN - draw.TB_W - 36,
             draw.SHEET_H - draw.MARGIN - 36)
SITE_TABLE_W = 640
# Helvetica widths (per 1,000 em) for measuring without PyMuPDF
_HELV = dict(zip("ABCDEFGHIJKLMNOPQRSTUVWXYZ",
                 (667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556,
                  833, 722, 778, 667, 778, 722, 667, 611, 722, 667, 944, 667,
                  667, 611)))
_HELV.update({c: 556 for c in "0123456789"})
_HELV.update({" ": 278, "'": 191, '"': 355, "-": 333, ".": 278, ",": 278,
              "(": 333, ")": 333, "/": 278, ":": 278, "%": 889, "x": 500})


def _tw(s, size, bold=False):
    """Text width in points: PyMuPDF's font when there is one, else the
    Helvetica table (bold about 6% wider), a little generous."""
    try:
        return draw.text_width(s, size, bold)
    except Exception:                         # no PyMuPDF (tests)
        w = sum(_HELV.get(c, _HELV.get(c.upper(), 556) if c.isalpha()
                          else 556) for c in s)
        return w / 1000.0 * size * (1.08 if bold else 1.02)


def _fit(s, size, bold=False, max_w=None, min_size=7):
    """draw.fit with _tw."""
    s = s or ""
    if not max_w:
        return s, size
    while size > min_size and _tw(s, size, bold) > max_w:
        size -= 0.5
    if _tw(s, size, bold) > max_w:
        while s and _tw(s + "…", size, bold) > max_w:
            s = s[:-1]
        s = s.rstrip() + "…"
    return s, size


def text_box(t):
    """The sheet box (x0, y0, x1, y1) a text item covers: caps height
    above the baseline, a descender below; rotated 90 it reads up the
    sheet about its anchor."""
    s, size = t["s"], t["size"]
    w = _tw(s, size, t.get("bold"))
    x, y = t["x"], t["y"]
    al = t.get("align", "left")
    x0 = x - w / 2 if al == "center" else (x - w if al == "right" else x)
    asc, dsc = 0.75 * size, 0.22 * size
    if not t.get("rotate"):
        return (x0, y - asc, x0 + w, y + dsc)
    # the morph pivot is x (the given x for centre, else x0) on the
    # baseline; (dx, dy) on the sheet goes to (dy, -dx)
    px = x if al == "center" else x0
    return (px - asc, y - (x0 + w - px), px + dsc, y - (x0 - px))


def seg_hits_box(a, b, box, pad=0.0):
    """Does segment a-b touch the box (Liang-Barsky)?"""
    x0, y0, x1, y1 = box[0] - pad, box[1] - pad, box[2] + pad, box[3] + pad
    t0, t1 = 0.0, 1.0
    dx, dy = b[0] - a[0], b[1] - a[1]
    for p, q in ((-dx, a[0] - x0), (dx, x1 - a[0]), (-dy, a[1] - y0),
                 (dy, y1 - a[1])):
        if abs(p) < 1e-12:
            if q < 0:
                return False
            continue
        r = q / p
        if p < 0:
            t0 = max(t0, r)
        else:
            t1 = min(t1, r)
        if t0 > t1:
            return False
    return True


def boxes_meet(a, b, pad=0.0):
    return not (a[2] + pad <= b[0] or b[2] + pad <= a[0] or
                a[3] + pad <= b[1] or b[3] + pad <= a[1])


def item_segments(it):
    """The stroked segments of a layout item (sheet points)."""
    t = it["t"]
    if t == "line":
        return [(it["a"], it["b"])]
    if t == "poly":
        p = list(it["pts"])
        # as PyMuPDF strokes it: finish() closes the path unless told not
        # to (closePath defaults to True there)
        if it["kw"].get("closePath", True) and len(p) > 2 and \
                tuple(p[0]) != tuple(p[-1]):
            p.append(p[0])
        return list(zip(p, p[1:]))
    if t == "rect" and it["kw"].get("color", INK) is not None and \
            it["kw"].get("width", 0.6):
        x0, y0, x1, y1 = it["r"]
        c = [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]
        return list(zip(c, c[1:]))
    return []


class _Sheet:
    """Collects the site plan's items in drawing order."""

    def __init__(self, ox, oy, k):
        self.ox, self.oy, self.k = ox, oy, k
        self.items = []

    def p(self, x, y):
        return (self.ox + x * self.k, self.oy - y * self.k)

    def r(self, x0, y0, x1, y1):
        a, b = self.p(x0, y1), self.p(x1, y0)
        return (a[0], a[1], b[0], b[1])

    def add(self, it, layer):
        it["layer"] = layer
        self.items.append(it)
        return it

    def rect(self, r, layer, **kw):
        return self.add({"t": "rect", "r": r, "kw": kw}, layer)

    def line(self, a, b, layer, color=INK, width=0.6, dashes=None):
        return self.add({"t": "line", "a": a, "b": b, "color": color,
                         "width": width, "dashes": dashes}, layer)

    def poly(self, pts, layer, **kw):
        """An open polyline unless closePath=True is asked for: PyMuPDF's
        Shape.finish() closes the path by default, which drew the drive-
        thru lane edges with a segment from the lane's exit back to its
        entry across the parking (review of 0.12.38 #3)."""
        kw.setdefault("closePath", False)
        return self.add({"t": "poly", "pts": pts, "kw": kw}, layer)

    def text(self, x, y, s, size=10, bold=False, color=INK, align="left",
             rotate=0, layer="label"):
        if not s:
            return None
        return self.add({"t": "text", "x": x, "y": y, "s": s, "size": size,
                         "bold": bold, "color": color, "align": align,
                         "rotate": rotate}, layer)

    def dim(self, a, b, label, off=24, size=8):
        """draw.dim as items (the same strokes and text)."""
        dx, dy = b[0] - a[0], b[1] - a[1]
        L = math.hypot(dx, dy) or 1
        nx, ny = -dy / L, dx / L
        a2 = (a[0] + nx * off, a[1] + ny * off)
        b2 = (b[0] + nx * off, b[1] + ny * off)
        for p, q in ((a, a2), (b, b2)):
            self.line((p[0] + nx * 3, p[1] + ny * 3),
                      (q[0] + nx * 4, q[1] + ny * 4), "dim", color=GREY,
                      width=0.3)
        self.line(a2, b2, "dim", width=0.4)
        for p in (a2, b2):
            self.line((p[0] - 3, p[1] + 3), (p[0] + 3, p[1] - 3), "dim",
                      width=0.8)
        mid = ((a2[0] + b2[0]) / 2, (a2[1] + b2[1]) / 2)
        if abs(dy) > abs(dx):
            self.text(mid[0] - 3, mid[1], label, size, align="center",
                      rotate=90, layer="dim_label")
        elif _tw(label, size) + 2 > L - 6:
            # wider than the dimension: past the ends of the extension
            # lines on the side away from what is dimensioned, clear of
            # the ticks
            y = mid[1] - 9 if ny <= 0 else mid[1] + 4 + 0.75 * size + 1.5
            self.text(mid[0], y, label, size, align="center",
                      layer="dim_label")
        else:
            self.text(mid[0], mid[1] - 3, label, size, align="center",
                      layer="dim_label")

    def label(self, lines, cands, color=GREY, layer="label", gap=2.0):
        """A label placed later (place()): lines [(text, size, bold)],
        candidate centres [(cx, cy, rotate)] best first."""
        return self.add({"t": "label", "lines": lines, "cands": cands,
                         "color": color, "gap": gap}, layer)


def _label_texts(lb, cx, cy, rot):
    """The text items of label lb centred on (cx, cy)."""
    out = []
    if rot:                                   # one line, reading up
        s, size, bold = lb["lines"][0]
        out.append({"t": "text", "x": cx + 0.265 * size, "y": cy, "s": s,
                    "size": size, "bold": bold, "color": lb["color"],
                    "align": "center", "rotate": 90})
        return out
    hs = [0.97 * size for _s, size, _b in lb["lines"]]
    y = cy - (sum(hs) + lb["gap"] * (len(hs) - 1)) / 2
    for (s, size, bold), h in zip(lb["lines"], hs):
        out.append({"t": "text", "x": cx, "y": y + 0.75 * size, "s": s,
                    "size": size, "bold": bold, "color": lb["color"],
                    "align": "center", "rotate": 0})
        y += h + lb["gap"]
    return out


def place(sh, order=None):
    """Put each label at its first candidate clear of the linework, the
    labels already placed and the arrows; then the arrows (candidate
    positions) clear of the labels. A label with no clear candidate takes
    the one with the fewest clashes and is listed in sh.clashes."""
    segs = [(a, b) for it, a, b in _seen_segments(sh.items)
            if it["t"] != "label" and it["layer"] != "arrow_cand"]
    boxes = [text_box(it) for it in sh.items if it["t"] == "text"]
    sh.clashes = []
    labels = [it for it in sh.items if it["t"] == "label"]
    labels.sort(key=lambda it: it.get("prio", 5))
    arrows = [it for it in sh.items if it["layer"] == "arrow_cand"]

    def clashes(texts):
        n = 0
        for t in texts:
            b = text_box(t)
            n += sum(1 for a, c in segs if seg_hits_box(a, c, b, 0.6))
            n += sum(1 for o in boxes if boxes_meet(b, o, 0.6))
        return n
    for lb in [x for x in labels if x.get("prio", 5) < 3] + arrows + \
            [x for x in labels if x.get("prio", 5) >= 3]:
        if lb["layer"] == "arrow_cand":
            lb["t"], lb["layer"] = "arrows", "arrow"
            lb["placed"] = []
            for c in lb["cands"]:
                lines = _arrow_lines(*c)
                if not any(seg_hits_box(a, b, o, 1.0) for a, b in lines
                           for o in boxes):
                    lb["placed"] = lines
                    segs.extend(lines)
                    break
            continue
        best = None
        for cx, cy, rot in lb["cands"]:
            texts = _label_texts(lb, cx, cy, rot)
            n = clashes(texts)
            if best is None or n < best[0]:
                best = (n, texts)
            if n == 0:
                break
        if best is None:
            lb["t"], lb["texts"] = "texts", []
            continue
        if best[0]:
            sh.clashes.append(lb["lines"][0][0])
        lb["t"], lb["texts"] = "texts", best[1]
        boxes.extend(text_box(t) for t in best[1])


def _arrow_lines(a, b, head=6.0):
    """A travel arrow a -> b (sheet points): the shaft and the head."""
    ang = math.atan2(b[1] - a[1], b[0] - a[0])
    out = [(a, b)]
    for s in (0.45, -0.45):
        out.append((b, (b[0] - head * math.cos(ang - s),
                        b[1] - head * math.sin(ang - s))))
    return out


def all_texts(lay):
    """Every text item of a placed layout."""
    out = []
    for it in lay["items"]:
        if it["t"] == "text":
            out.append(it)
        elif it["t"] == "texts":
            out.extend(it["texts"])
    return out


def all_segments(lay, layers=None):
    """(layer, a, b) for every stroked segment of a placed layout that is
    still seen (_seen_segments)."""
    return [(it["layer"], a, b) for it, a, b in _seen_segments(lay["items"])
            if not layers or it["layer"] in layers]


def _seen_segments(items):
    """(item, a, b) for every stroked segment of the items, in order, less
    the parts of a setback line the drive-thru lane's paving (drawn after
    it) paints over - with the building moved back for the parking the
    lane can run in the rear yard across the rear setback line (Oct 22),
    and a label on the paving there is on no line one can see."""
    out = []
    for i, it in enumerate(items):
        segs = it["placed"] if it["t"] == "arrows" else item_segments(it)
        if it["layer"] == "setback" and segs:
            over = [x["r"] for x in items[i + 1:]
                    if x["layer"] == "lane_fill" and x["t"] == "rect"]
            if over:
                segs = [s for a, b in segs for s in _uncovered(a, b, over)]
        out.extend((it, a, b) for a, b in segs)
    return out


def _uncovered(a, b, boxes):
    """The parts of the axis-aligned segment a-b outside the boxes' insides
    (a segment along a box's edge stays)."""
    if abs(a[1] - b[1]) < 1e-9:
        k, c = 0, a[1]
    elif abs(a[0] - b[0]) < 1e-9:
        k, c = 1, a[0]
    else:
        return [(a, b)]
    lo, hi = sorted((a[k], b[k]))
    parts = [(lo, hi)]
    for bx in boxes:
        if not (bx[1 - k] < c < bx[3 - k]):
            continue
        cut0, cut1 = bx[k], bx[k + 2]
        nxt = []
        for p0, p1 in parts:
            if cut1 <= p0 or cut0 >= p1:
                nxt.append((p0, p1))
                continue
            if cut0 > p0:
                nxt.append((p0, cut0))
            if cut1 < p1:
                nxt.append((cut1, p1))
        parts = nxt
    if parts == [(lo, hi)]:
        return [(a, b)]

    def pt(v):
        return (v, c) if k == 0 else (c, v)
    return [(pt(p0), pt(p1)) for p0, p1 in parts if p1 - p0 > 1e-9]


# lines that belong in the field: the rows' own outlines and stall lines,
# and the setback lines (zoning reference lines - parking in a front yard
# is its own check)
_FIELD_OWN = ("row", "stall", "setback")


def _seg_in_boxes(a, b, boxes, pad=1.0):
    """Every point of segment a-b inside one of the boxes (padded)."""
    n = max(2, int(math.hypot(b[0] - a[0], b[1] - a[1]) / 2.0) + 1)
    for i in range(n + 1):
        t = i / n
        x, y = a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t
        if not any(r[0] - pad <= x <= r[2] + pad and
                   r[1] - pad <= y <= r[3] + pad for r in boxes):
            return False
    return True


def field_crossings(lay):
    """[(layer, a, b)] for every stroked segment of a placed site layout
    that runs through a parking row (its stalls and aisle), sheet points -
    a drawing error. The rows' own lines, the stall lines and the setback
    lines belong there; the drive-thru lane's edges and arrows count only
    while they stay on the lane's paving, the crosswalk's bars only in
    the crosswalk (review of 0.12.38 #3: a closed lane edge drew a line
    from the lane's exit back to its entry across the field)."""
    f = lay.get("features") or {}
    if not f.get("rows"):
        return []
    ox, oy, k = lay["ox"], lay["oy"], lay["ppf"]

    def sheet(r):
        return (ox + r[0] * k, oy - r[3] * k, ox + r[2] * k, oy - r[1] * k)
    rows = [sheet(r) for r in f["rows"]]
    rows = [(r[0] + 0.5, r[1] + 0.5, r[2] - 0.5, r[3] - 0.5) for r in rows]
    lane = [sheet(b) for b in (f.get("lane") or {}).get("boxes") or ()]
    cw = [sheet(f["crosswalk"])] if f.get("crosswalk") else []
    out = []
    for layer, a, b in all_segments(lay):
        if layer in _FIELD_OWN:
            continue
        if not any(seg_hits_box(a, b, r) for r in rows):
            continue
        if layer in ("lane", "arrow") and lane and \
                _seg_in_boxes(a, b, lane):
            continue
        if layer == "crosswalk" and cw and _seg_in_boxes(a, b, cw):
            continue
        out.append((layer, a, b))
    return out


def site_layout(plan):
    """AS-101 as data: {"label", "ppf", "ox", "oy", "area", "items",
    "features", "clashes"} - every rect, line and text of the drawing in
    sheet points, in drawing order - or None without a site."""
    s = plan.get("site")
    if not s:
        return None
    from . import site as site_mod
    W, D = plan["footprint"]["width"], plan["footprint"]["depth"]
    lw, ld = s["lot_w"], s["lot_d"]
    lx, ly = s["lot_x0"], s["lot_y0"]
    sb = s["setbacks"]
    dx0, dy0, dx1, dy1 = _DRAW_BOX
    area_r = (dx0, dy0, dx1 - SITE_TABLE_W - 40, dy1)
    aw, ah = area_r[2] - area_r[0], area_r[3] - area_r[1]
    street = 30.0                                  # ft drawn for the street
    label, ppf = SITE_SCALES[-1]
    for lb, k in SITE_SCALES:
        # 12 ft round the lot - and at the small scales at least 60 pt
        # each side, the room the lot dimension and the side setback
        # labels take west of it (a 60,000 SF strip center's ran off the
        # drawing area)
        if (lw + 24) * k <= aw and (ld + street + 24) * k <= ah - 110 and \
                lw * k + 120 <= aw:
            label, ppf = lb, k
            break
    ox = area_r[0] + (aw - lw * ppf) / 2 - lx * ppf
    oy = area_r[1] + (ah - 110 + ld * ppf) / 2 - street * ppf / 2 + ly * ppf
    v = _Sheet(ox, oy, ppf)
    P, R = v.p, v.r
    pk = plan.get("parking")
    dt = plan.get("drive_thru")
    feat = site_mod.features(plan) if (pk or dt) else None
    # the street
    v.rect(R(lx - 12, ly - street, lx + lw + 12, ly - 4), "street",
           color=None, width=0, fill=(0.93, 0.93, 0.93))
    if feat:
        _street_label(v, feat, lx, ly, lw, street)
    else:
        v.text(P(lx + lw / 2, 0)[0], P(0, ly - street / 2)[1] + 5,
               "STREET (NAME AND RIGHT-OF-WAY BY SURVEY)", 11, bold=True,
               color=GREY, align="center")
    # the buildable area, the setbacks, then the property line on top
    ex0, ey0 = lx + sb["side"], ly + sb["front"]
    ex1, ey1 = lx + lw - sb["side"], ly + ld - sb["rear"]
    if ex1 > ex0 and ey1 > ey0:
        v.rect(R(ex0, ey0, ex1, ey1), "envelope_fill", color=None, width=0,
               fill=(0.9, 0.96, 0.9))
        v.rect(R(ex0, ey0, ex1, ey1), "setback", color=GREEN, width=0.8,
               dashes="[8 4] 0")
    v.rect(R(lx, ly, lx + lw, ly + ld), "lot", color=INK, width=2.0,
           dashes="[18 4 3 4] 0")
    top = P(0, ly + ld)[1]
    if feat:
        cands = [(P(lx + lw * f_, 0)[0], top - 11, 0)
                 for f_ in (0.5, 0.4, 0.6, 0.3, 0.7, 0.2, 0.8, 0.1, 0.9)]
        v.label([("PROPERTY LINE", 9, True)], cands, color=INK)
    else:
        v.text(P(lx + lw / 2, ly + ld)[0], P(0, ly + ld)[1] - 8,
               "PROPERTY LINE", 9, bold=True, align="center")
    # the building (outside face) and the roof edge
    o = 0.25
    ov = float(plan["roof"].get("overhang") or 0)
    if ov:
        v.rect(R(-o - ov, -o - ov, W + o + ov, D + o + ov), "roof",
               color=GREY, width=0.6, dashes="[4 3] 0")
    v.rect(R(-o, -o, W + o, D + o), "building", color=INK, width=1.4,
           fill=(0.78, 0.78, 0.8))
    from .garage import bbox
    bx0, _by0, bx1, _by1 = bbox(plan)
    gar = plan.get("garage")
    if gar:
        gx0, gy0, gx1, gy1 = gar["rect"]
        gr = (gx0, -o, gx1 + o, gy1 + o) if gar["side"] == "E" else \
            (gx0 - o, -o, gx1, gy1 + o)
        v.rect(R(*gr), "building", color=INK, width=1.4,
               fill=(0.88, 0.88, 0.88))
        gc = P((gr[0] + gr[2]) / 2, (gr[1] + gr[3]) / 2)
        v.text(gc[0], gc[1], "GARAGE", 9, bold=True, align="center")
        # the driveway to the street
        a, b = min(x for x, _ in gar["overhead"]), \
            max(x for _, x in gar["overhead"])
        if -o > ly + 0.5:                # not when it's at the lot line
            v.rect(R(a - 1, ly, b + 1, -o), "drive", color=GREY, width=0.5,
                   fill=(0.93, 0.93, 0.93))
            v.text(P((a + b) / 2, 0)[0], P(0, (ly - o) / 2)[1], "DRIVE", 8,
                   color=GREY, align="center")
    tc = plan.get("truck_court")
    if tc:                      # behind the dock wall (assumed depth)
        tx0, tx1 = -o, W + o
        ty0, ty1 = D + o, D + o + float(tc["depth"])
        v.rect(R(tx0, ty0, tx1, ty1), "truck_court", color=GREY, width=0.6,
               fill=(0.9, 0.9, 0.9), dashes="[6 3] 0")
        tcc = P(W / 2, (ty0 + ty1) / 2)
        v.text(tcc[0], tcc[1], "TRUCK COURT " + fmt_ftin(
            float(tc["depth"])) + (" (ASSUMED)" if tc.get("assumed")
                                   else ""), 10, bold=True, color=GREY,
            align="center")
        v.dim(P(W * 0.6, ty0), P(W * 0.6, ty1), fmt_ftin(ty1 - ty0), off=0)
    if feat:
        _site_features(v, plan, feat)
    for key in ("porch", "deck"):
        it = plan.get(key)
        if it:
            v.rect(R(*it["rect"]), key, color=INK, width=0.8,
                   fill=(0.93, 0.93, 0.93) if key == "porch" else
                   (0.94, 0.91, 0.86))
            ic = P((it["rect"][0] + it["rect"][2]) / 2,
                   (it["rect"][1] + it["rect"][3]) / 2)
            v.text(ic[0], ic[1] + 3, key.upper(), 7, color=GREY,
                   align="center")
    if s["binding"] and ex1 > ex0 and ey1 > ey0:
        # where the building crosses a setback: the line again, in red
        v.rect(R(ex0, ey0, ex1, ey1), "setback", color=draw.RED, width=1.2,
               dashes="[8 4] 0")
    c = P(W / 2, D / 2)
    gross = (W + 2 * o) * (D + 2 * o)
    for i, (txt, sz, b) in enumerate((("PROPOSED BUILDING", 11, True),
                                      (f"{gross:,.0f} SF FOOTPRINT", 9,
                                       False),
                                      ("FIN. FLOOR 0'-0\" (DATUM)", 8,
                                       False))):
        t_, sz2 = _fit(txt, sz, b, max(40, (W + 0.5) * ppf - 8))
        v.text(c[0], c[1] - 10 + i * 14, t_, sz2, bold=b, align="center")
    door = next((op for op in plan["openings"] if op.get("from_room") ==
                 "EXT" and op["wall"] == "W1"), None)
    pr = s["provided"]
    if feat:
        _site_dims(v, plan, s, feat)
    else:
        # front door / walk
        if door and _walk_end(plan) > ly + 0.5:   # none when the porch or
            a = door["along"]                      # house is at the lot line
            v.rect(R(a - 2, ly, a + 2, _walk_end(plan)), "walk", color=GREY,
                   width=0.5, fill=(0.97, 0.97, 0.97))
            v.text(P(a + 2.5, 0)[0] + 4, P(0, (ly - o) / 2)[1], "WALK", 8,
                   color=GREY)
        # dimensions: the lot, and the setbacks as drawn
        v.dim(P(lx + lw, ly), P(lx, ly), fmt_ftin(lw) + " LOT",
              off=-(street * ppf + 22))
        v.dim(P(lx, ly), P(lx, ly + ld), fmt_ftin(ld) + " LOT", off=-34)
        # the front dimension on the side away from the walk
        mx = W * 0.85 if door and door["along"] < W / 2 else W * 0.15
        v.dim(P(mx, ly), P(mx, -o), fmt_ftin(pr["front"]), off=0)
        v.dim(P(W * 0.15, D + o), P(W * 0.15, ly + ld), fmt_ftin(
            pr["rear"]), off=0)
        my = D * 0.3
        v.dim(P(bx0 - o, my), P(lx, my), fmt_ftin(bx0 - o - lx), off=0)
        v.dim(P(lx + lw, my), P(bx1 + o, my), fmt_ftin(lx + lw - bx1 - o),
              off=0)
    # setback labels (say when they are assumed)

    def sblab(k):
        return f"{fmt_ftin(sb[k])} {k.upper()} SETBACK" + (
            " (ASSUMED)" if k in s.get("assumed", ()) else "")
    if ex1 > ex0 and ey1 > ey0 and feat:
        _setback_labels(v, s, sblab, (ex0, ey0, ex1, ey1))
    elif ex1 > ex0 and ey1 > ey0:
        g = GREEN
        v.text(P((ex0 + ex1) / 2, 0)[0], P(0, ey0)[1] - 5, sblab("front"), 8,
               color=g, align="center")
        v.text(P((ex0 + ex1) / 2, 0)[0], P(0, ey1)[1] + 11, sblab("rear"), 8,
               color=g, align="center")
        v.text(P(ex0, 0)[0] + 11, P(0, (ey0 + ey1) / 2)[1], sblab("side"),
               8, color=g, align="center", rotate=90)
        v.text(P(ex1, 0)[0] - 4, P(0, (ey0 + ey1) / 2)[1], sblab("side"),
               8, color=g, align="center", rotate=90)
    place(v)
    return {"label": label, "ppf": ppf, "ox": ox, "oy": oy,
            "area_r": area_r, "street": street, "items": v.items,
            "features": feat, "clashes": v.clashes, "gross": gross}


def _street_label(v, f, lx, ly, lw, street):
    """The street's name, placed like the other labels (place()): in the
    street, where it has always been first (the middle of the lot's
    frontage), then along the street and up and down in it - clear of
    every drawn line and label, and never on the parking or the lane
    (Oct 22: with the building moved back for the field, the fixed label
    landed on it). Placed before every other label, as the plain text it
    was."""
    P = v.p
    s, size = "STREET (NAME AND RIGHT-OF-WAY BY SURVEY)", 11
    y0 = P(0, ly - street / 2)[1] + 5                 # the old baseline
    # the label's centre for that baseline (_label_texts)
    cy = y0 - 0.75 * size + 0.97 * size / 2
    lo, hi = P(0, ly - 4)[1], P(0, ly - street)[1]   # the street, sheet y
    keep = [r for r in f.get("rows") or ()] + [
        b for b in (f.get("lane") or {}).get("boxes") or ()]
    keep = [v.r(*r) for r in keep]
    w = _tw(s, size, True)
    cands = []
    for dy in (0, -7, 7, -14, 14):
        y = cy + dy
        if dy and not (lo + 0.97 * size / 2 + 1 <= y <=
                       hi - 0.97 * size / 2 - 1):
            continue                                  # out of the street
        for t in (0.5, 0.4, 0.6, 0.3, 0.7, 0.2, 0.8, 0.1, 0.9):
            x = P(lx + lw * t, 0)[0]
            box = (x - w / 2, y - 0.97 * size / 2, x + w / 2,
                   y + 0.97 * size / 2)
            if any(boxes_meet(box, r, 0.6) for r in keep):
                continue                              # not on the parking
            cands.append((x, y, 0))
    lb = v.label([(s, size, True)], cands or [(P(lx + lw / 2, 0)[0], cy,
                                               0)], color=GREY)
    lb["prio"] = -2


def _site_features(v, plan, f):
    """The walks, the parking field and the drive-thru lane, with their
    labels (placed clear of the linework)."""
    P, R = v.p, v.r
    pk = plan.get("parking")
    for w in f["walks"]:
        v.rect(R(*w["rect"]), "walk", color=GREY, width=0.5,
               fill=(0.97, 0.97, 0.97))
    if f["band"]:
        v.rect(R(*f["band"]), "band", color=GREY, width=0.4,
               fill=(0.97, 0.97, 0.97))
    for r in f["rows"]:
        v.rect(R(*r), "row", color=GREY, width=0.5, fill=(0.9, 0.9, 0.9))
    for a, b in f["stalls"]:
        v.line(P(*a), P(*b), "stall", color=INK, width=0.35)
    lot = v.r(*f["lot"])
    for (x, y), st in zip(f["hc"], f.get("hc_stalls") or [None] * len(
            f["hc"])):
        # in the stall, first where it has always been; then along the
        # stall, the spots inside the lot first (a field that runs past
        # the lot line must not put the mark on the line)
        c = P(x, y)
        cands = [(c[0], c[1] + 3 - 0.75 * 6 + 0.97 * 6 / 2, 0)]
        if st:
            more = [P(x, st[1] + (st[3] - st[1]) * t)
                    for t in (0.3, 0.7, 0.2, 0.8, 0.12, 0.88, 0.4, 0.6)]
            more.sort(key=lambda q: not (lot[1] + 6 < q[1] < lot[3] - 6))
            cands += [(q[0], q[1], 0) for q in more]
        lb = v.label([("HC", 6, True)], cands, color=INK, layer="hc")
        lb["prio"] = -1
    for a in f["aisles"]:
        xs = [a[0] + (a[2] - a[0]) * t for t in (0.5, 0.35, 0.65, 0.2, 0.8)]
        cy = P(0, (a[1] + a[3]) / 2)[1]
        v.label([("24'-0\" DRIVE AISLE", 7, False)],
                [(P(x, 0)[0], cy, 0) for x in xs])
    if pk and f["band"]:
        b = R(*f["band"])
        bw = b[2] - b[0] - 8
        head = f"PARKING - {pk['spaces']} SPACES ({pk['accessible']} " \
            "ACCESSIBLE)"
        tail = "COUNT AND LAYOUT ASSUMED" if pk.get("assumed") else ""
        one = head + (" - " + tail if tail else "")
        cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
        bh = b[3] - b[1]
        if _tw(one, 8, True) <= bw and bh >= 9.5 or not tail:
            lines = [_fit(one, 8, True, bw, 5) + (True,)]
        else:
            s1, z1 = _fit(head, 8, True, bw, 5)
            s2, z2 = _fit(tail, 7, False, bw, 5)
            lines = [(s1, z1, True), (s2, z2, False)]
            if bh < 0.97 * (z1 + z2) + 3:             # too thin for two
                lines = [_fit(one, 8, True, bw, 4) + (True,)]
        lb = v.label(lines, [(cx, cy, 0)] + [
            (b[0] + (b[2] - b[0]) * t, cy, 0) for t in (0.4, 0.6)])
        lb["prio"] = 1
    fit = f.get("parking_fit")
    if fit and not fit["fits"]:
        # only the stalls that fit are drawn (review of 0.12.38 #8); the
        # front aisle says so - or, with no row on the lot, the front yard
        # between the storefront walk and the lot line, then the street
        lx0, ly0, lx1, ly1 = f["lot"]
        off = [a for a in f["aisles"] if (a[1] + a[3]) / 2 < ly0] or \
            f["aisles"]
        cands = []
        for a in reversed(off):
            cy = P(0, (a[1] + a[3]) / 2)[1]
            for dy in (0, 7, -7, 14, -14):
                cands += [(P(a[0] + (a[2] - a[0]) * t, 0)[0], cy + dy, 0)
                          for t in (0.5, 0.3, 0.7, 0.2, 0.8, 0.4, 0.6)]
        if not cands:
            fr = min([r[1] for r in f["rows"]] +
                     ([f["band"][1]] if f["band"] else [0.0]))
            ts = (0.5, 0.3, 0.7, 0.2, 0.8, 0.4, 0.6, 0.1, 0.9)
            for yy, dys in (((fr + ly0) / 2, (0, 3, -3)),
                            (ly0 - 9, (0, -4, 4, -8))):
                cy = P(0, yy)[1]
                cands += [(P(lx0 + (lx1 - lx0) * t, 0)[0], cy + dy, 0)
                          for dy in dys for t in ts]
        # after the aisle labels (the items' order), in the same aisles
        v.label([("PARKING DOES NOT FIT THE LOT - VERIFY WITH ZONING / "
                  "CIVIL", 8, True)], cands, color=draw.RED)
    lane = f.get("lane")
    if lane:
        _lane_items(v, plan, f, lane)
    if f["crosswalk"]:
        cx0, cy0, cx1, cy1 = f["crosswalk"]
        y = cy0 + 1.5
        while y < cy1 - 1.0:
            v.line(P(cx0, y), P(cx1, y), "crosswalk", color=GREY, width=0.8)
            y += 2.0
    # the walk's name, inside the walk to the street
    st = next((w["rect"] for w in f["walks"] if w["kind"] == "street"), None)
    if st:
        x = P((st[0] + st[2]) / 2, 0)[0]
        y0, y1 = st[1], min(st[3], -0.25)
        ts = (0.5, 0.3, 0.7, 0.15, 0.85, 0.05, 0.95, 0.4, 0.6)
        ys = [P(0, y0 + (y1 - y0) * t)[1] for t in ts]
        # in the walk; else just outside it, on the side away from the
        # field (a setback line can run down the walk)
        wr = R(*st)
        out = -1 if st[2] <= f["building"][0] + 1e-6 else 1
        xo = (wr[0] - 3 - 4) if out < 0 else (wr[2] + 3 + 4)
        lb = v.label([("WALK", 8, False)], [(x, y, 90) for y in ys] +
                     [(xo, y, 90) for y in ys])
        lb["prio"] = 4


def _lane_items(v, plan, f, lane):
    """The drive-thru lane: the paving, its edges, the pick-up window,
    travel arrows and the label in the lane."""
    P, k = v.p, v.k
    for b in lane["boxes"]:
        v.rect(v.r(*b), "lane_fill", color=None, width=0,
               fill=(0.93, 0.93, 0.93))
    for e in lane["edges"]:
        v.poly([P(*p) for p in e], "lane", color=GREY, width=0.6)
    wx, wy, ww = lane["window"]
    v.line(P(wx, wy - ww / 2), P(wx, wy + ww / 2), "window", color=INK,
           width=2.5)
    L = lane["width"]
    path = lane["path"]
    # the pick-up window, in the lane beside it (the east run, or the
    # west one for a window on the west wall)
    qx = path[lane.get("window_run", 1)][0]
    lines = [_fit("PICK-UP", 6, True, L * k - 4, 3.5) + (True,),
             _fit("WINDOW", 6, True, L * k - 4, 3.5) + (True,)]
    lb = v.label(lines, [(P(qx, 0)[0], P(0, wy + d)[1], 0)
                         for d in (0, 3, -3, 6, -6, 9, -9)])
    lb["prio"] = 1
    # the lane's name and the stacking, in the rear run of the lane
    a, b = path[2], path[3]
    run = abs(b[0] - a[0]) * k - 12
    stack, need, queue = lane["stack"], lane["need"], lane["queue"]
    l1 = f"DRIVE-THRU LANE {fmt_ftin(L)} WIDE (ASSUMED)"
    if queue >= need - 1e-6:
        l2 = (f"STACKING {stack} CARS (ASSUMED) - {queue:.0f}' TO THE "
              "WINDOW")
    else:
        l2 = (f"STACKING {stack} CARS (ASSUMED) - {queue:.0f}' OF "
              f"{need:.0f}' SHOWN - VERIFY WITH ZONING")
    lines = [_fit(l1, 7, True, run, 4) + (True,),
             _fit(l2, 6, False, run, 4) + (False,)]
    if not lane["in_lot"] or not lane["in_setbacks"]:
        l3 = ("OFF THE LOT" if not lane["in_lot"] else
              "IN A REQUIRED YARD") + " - VERIFY WITH ZONING"
        lines.append(_fit(l3, 6, True, run, 4) + (True,))
    yc = P(0, a[1])[1]
    xs = [a[0] + (b[0] - a[0]) * t for t in (0.5, 0.45, 0.55, 0.4, 0.6)]
    lb = v.label(lines, [(P(x, 0)[0], yc, 0) for x in xs], gap=1.5)
    lb["prio"] = 0
    for cands in lane["arrows"]:
        v.add({"t": "arrow_cand", "cands": [(P(*t), P(*h)) for t, h in
                                            cands]}, "arrow_cand")


def _site_dims(v, plan, s, f):
    """The dimensions, all outside the lot: the lot below the street and
    up the west side, the front and rear yards up the east side, the side
    yards above the rear lot line."""
    from .garage import bbox
    P = v.p
    lx, ly, lw, ld = s["lot_x0"], s["lot_y0"], s["lot_w"], s["lot_d"]
    D = plan["footprint"]["depth"]
    o = 0.25
    bx0, _by0, bx1, _by1 = bbox(plan)
    pr = s["provided"]
    # below the street - or below the parking when it runs off the lot
    low = min([ly] + [r[1] for r in f["rows"]])
    v.dim(P(lx + lw, ly), P(lx, ly), fmt_ftin(lw) + " LOT",
          off=-(max(30.0, ly - low + 4) * v.k + 22))
    v.dim(P(lx, ly), P(lx, ly + ld), fmt_ftin(ld) + " LOT", off=-34)
    ex = lx + lw
    if -o > ly + 0.5:
        v.dim(P(ex, ly), P(ex, -o), fmt_ftin(pr["front"]), off=24)
    if ly + ld > D + o + 0.5:
        v.dim(P(ex, D + o), P(ex, ly + ld), fmt_ftin(pr["rear"]), off=24)
    top = ly + ld
    if bx0 - o > lx + 0.5:
        v.dim(P(bx0 - o, top), P(lx, top), fmt_ftin(bx0 - o - lx), off=22)
    if lx + lw > bx1 + o + 0.5:
        v.dim(P(lx + lw, top), P(bx1 + o, top),
              fmt_ftin(lx + lw - bx1 - o), off=22)


def _setback_labels(v, s, sblab, env):
    """The setback labels beside their lines, clear of the parking and
    the lane; off the lot beside the line when the lot has no room."""
    P = v.p
    ex0, ey0, ex1, ey1 = env
    lx, lw = s["lot_x0"], s["lot_w"]
    fx = (0.5, 0.3, 0.7, 0.15, 0.85, 0.05, 0.95, 0.4, 0.6, 0.22, 0.78)
    for key, y, out in (("front", ey0, 1), ("rear", ey1, -1)):
        lines = [(sblab(key), 8, False)]
        h = 0.97 * 8
        ly_ = P(0, y)[1]
        cands = []
        for side in (out, -out):            # outside the envelope first
            for t in fx:
                cands.append((P(ex0 + (ex1 - ex0) * t, 0)[0],
                              ly_ + side * (3 + h / 2), 0))
        w = _tw(lines[0][0], 8)
        cands.append((P(lx + lw, 0)[0] + 46 + w / 2, ly_, 0))
        cands.append((P(lx, 0)[0] - 52 - w / 2, ly_, 0))
        v.label(lines, cands, color=GREEN)["prio"] = 6
    for x, out in ((ex0, -1), (ex1, 1)):
        lines = [(sblab("side"), 8, False)]
        xs = P(x, 0)[0]
        cands = []
        for side in (out, -out):
            for t in (0.5, 0.35, 0.65, 0.2, 0.8, 0.1, 0.9):
                cands.append((xs + side * (3 + 0.97 * 4),
                              P(0, ey0 + (ey1 - ey0) * t)[1], 90))
        v.label(lines, cands, color=GREEN)["prio"] = 6


def _draw_items(page, items):
    """Draw a site_layout's items."""
    def pt(p):
        return fitz.Point(p[0], p[1])
    for it in items:
        t = it["t"]
        if t == "rect":
            sh = page.new_shape()
            sh.draw_rect(fitz.Rect(*it["r"]))
            sh.finish(**it["kw"])
            sh.commit()
        elif t == "line":
            draw.line(page, pt(it["a"]), pt(it["b"]), color=it["color"],
                      width=it["width"], dashes=it["dashes"])
        elif t == "poly":
            sh = page.new_shape()
            sh.draw_polyline([pt(p) for p in it["pts"]])
            sh.finish(**it["kw"])
            sh.commit()
        elif t == "arrows":
            for a, b in it["placed"]:
                draw.line(page, pt(a), pt(b), width=0.8)
        elif t in ("text", "texts"):
            for x in ([it] if t == "text" else it["texts"]):
                draw.text(page, x["x"], x["y"], x["s"], x["size"],
                          bold=x["bold"], color=x["color"], align=x["align"],
                          rotate=x["rotate"])


def site_plan(doc, page, plan):
    """AS-101: the lot, the setbacks (assumed ones say so), the buildable
    area and the building, with a site data table."""
    lay = site_layout(plan)
    if not lay:
        return "NTS", 0
    s = plan["site"]
    lw, ld = s["lot_w"], s["lot_d"]
    lx, ly = s["lot_x0"], s["lot_y0"]
    sb = s["setbacks"]
    label, ppf = lay["label"], lay["ppf"]
    area_r = fitz.Rect(*lay["area_r"])
    street = lay["street"]
    v = View(lay["ox"], lay["oy"], ppf)
    _draw_items(page, lay["items"])
    pk, dt, tc = plan.get("parking"), plan.get("drive_thru"), \
        plan.get("truck_court")
    pr = s["provided"]
    gross = lay["gross"]
    draw.north_arrow(page, fitz.Point(area_r.x1 - 50, DRAW.y0 + 60))
    draw.title_under(page, DRAW.x0 + 10, DRAW.y1 - 40, "Site Plan", label)
    # site data
    tx = DRAW.x1 - SITE_TABLE_W
    rows = [["Lot", f"{fmt_ftin(lw)} x {fmt_ftin(ld)}  ({lw * ld:,.0f} SF)",
             s["lot_from"]],
            ["Building footprint", f"{gross:,.0f} SF" + (
                f" + garage {plan['garage']['width'] * (plan['garage']['depth'] + 0.5):,.0f} SF"
                if plan.get("garage") else ""), "this set"],
            ["Lot coverage", f"{s['coverage']:.1%}", "verify limit"]]
    if tc:
        rows.append(["Truck court", f"{fmt_ftin(float(tc['depth']))} deep "
                     "at the dock wall", "ASSUMED" if tc.get("assumed")
                     else "brief"])
    fit = (lay["features"] or {}).get("parking_fit")
    if pk:
        rows.append(["Parking", f"{pk['spaces']} spaces, "
                     f"{pk['accessible']} accessible ({pk['van']} van)",
                     "ASSUMED" if pk.get("assumed") else "brief"])
        if fit and not fit["fits"]:
            from .site import parking_fit_text
            rows.append(["Parking fits the lot", parking_fit_text(fit),
                         "verify (zoning)"])
    lane = (lay["features"] or {}).get("lane")
    if dt:
        rows.append(["Drive-thru lane", f"{fmt_ftin(float(dt['lane_w']))} "
                     "wide, round the building, window on the " + (
                         "east" if dt.get("side", "E") == "E" else "west"),
                     "ASSUMED"])
        if lane:
            rows.append(["Drive-thru stacking", f"{lane['stack']} cars, "
                         f"{lane['need']:.0f}' req. / {lane['queue']:.0f}' "
                         "shown", "ASSUMED - verify"])
    for k in ("front", "side", "rear"):
        rows.append([f"{k.title()} setback",
                     f"{fmt_ftin(sb[k])} req. / {fmt_ftin(pr[k])} shown",
                     "ASSUMED" if k in s.get("assumed", ()) else "brief"])
    rows.append(["Buildable area", f"{fmt_ftin(s['envelope'][0])} x "
                 f"{fmt_ftin(s['envelope'][1])}", ""])
    ok = s["on_lot"] and not s["binding"]
    rows.append(["Fits the setbacks", "YES" if ok else "NO - " + (
        ", ".join(s["binding"]) or "larger than the lot"), ""])
    yy = draw.table(page, tx, DRAW.y0 + 40, [("SITE DATA", 190, "left"),
                                             ("", 290, "left"),
                                             ("SOURCE", 160, "left")],
                    rows, size=10, row_h=24)
    if not ok:
        draw.text(page, tx, yy + 18, "The building does not fit: " + (
            "it crosses the " + ", ".join(s["binding"]) + " setback (red)."
            if s["on_lot"] else "it is larger than the lot."), 11,
            bold=True, color=draw.RED)
        yy += 22
    notes_ = ["Lot lines, easements, utilities, grades and the street are "
              "by survey - none were supplied.",
              "Setbacks marked ASSUMED are placeholders. Verify front, side "
              "and rear setbacks, lot coverage, height and parking with the "
              "local zoning code.",
              "Drainage, grading, driveway and utility connections by the "
              "design professional / civil engineer."]
    if s.get("set_back_for_parking"):
        # site.site_for moved the building back for the field (Oct 22)
        from .site import SIDE_WALK
        rear_dt = dt and lane and pr["rear"] < sb["rear"] + float(
            dt["lane_w"]) + SIDE_WALK - 1e-6
        notes_.append(
            f"The building is set back {fmt_ftin(pr['front'])} from the "
            f"front lot line ({fmt_ftin(sb['front'])} front setback "
            "required) so the parking field fits in front of it, leaving "
            f"a {fmt_ftin(pr['rear'])} rear yard" + (
                " with the drive-thru lane and its service walk in it"
                if rear_dt else "") + " - verify with zoning and the civil "
            "engineer.")
    if fit and not fit["fits"]:
        from .site import parking_fit_text
        notes_.append(
            "The parking does not fit the lot: " + parking_fit_text(fit)[5:]
            + " - only the stalls that fit are drawn (red note). The count, "
            "the layout and the lot - shared or off-site parking, a "
            "variance, a smaller building - to be resolved with zoning and "
            "the civil engineer.")
    if dt:
        from .site import CAR_LEN
        notes_.append(
            "Drive-thru lane assumed: one way round the building with the "
            "pick-up window on the driver's side, stacking for "
            f"{int(dt.get('stack') or 8)} cars at {CAR_LEN:g} ft each, the "
            "menu board, curbs and signage by the civil engineer - verify "
            "lane width, stacking and yards with zoning.")
    ny = yy + 30
    draw.text(page, tx, ny, "SITE NOTES", 12, bold=True)
    for i, n in enumerate(notes_, 1):
        ny += 20
        for j, ln in enumerate(_wrap_words(n, 78)):
            draw.text(page, tx, ny, f"{i}." if j == 0 else "", 10, bold=True)
            draw.text(page, tx + 22, ny, ln, 10)
            ny += 14
    area = v.rect(lx - 12, ly - street, lx + lw + 12, ly + ld + 12)
    _register_scale(doc, page.number, area, ppf, label, "Site Plan")
    return label, ppf


def _wrap_words(s, width):
    words, lines, cur = s.split(), [], ""
    for w in words:
        if cur and len(cur) + len(w) + 1 > width:
            lines.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    return lines + ([cur] if cur else [])
