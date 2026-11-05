"""Pieces the Phase 2 types (strip retail, restaurant) share: walls from
room rectangles, doors on a given wall, a part of the plan as a plan of
its own (the enlarged plans), the parking field in front, and the
quantity rows on top of the small-commercial takeoff.

Plain plan data - PyMuPDF is imported only inside part_sheet's drawing
function."""
import math

PARKING_ROW = 62.0          # ft: two 18 ft stalls and a 24 ft aisle, +2 ft
STALL_W = 9.0               # ft (assumed)
WALK = 10.0                 # ft storefront walk between the building and
                            # the first row (assumed)


def room(rid, number, name, kind, rect, target=None, **extra):
    """A room dict the way layout.build_level makes them."""
    from .. import program as prog
    x0, y0, x1, y1 = rect
    fin = prog.FINISHES.get(kind, ("TBD",) * 4)
    area = round((x1 - x0) * (y1 - y0), 2)
    out = {"id": rid, "number": str(number), "name": name, "type": kind,
           "rect": [x0, y0, x1, y1], "area": area,
           "target_sf": round(target if target is not None else area, 1),
           "finishes": {"floor": fin[0], "base": fin[1], "walls": fin[2],
                        "ceiling": fin[3]},
           "ceiling_ht": 10.0}
    out.update(extra)
    return out


def walls_for(rooms, W, D, thickness=None):
    """The exterior walls W1-W4 and a wall on every edge two rooms share
    (at least 1 ft) - build_level's rule. `thickness(a, b)` -> (ft, extra
    keys) for the wall between rooms a and b (default a 4 1/2" partition).
    Returns (walls, {(id_a, id_b): wall})."""
    from ..layout import INT_T, _exterior_walls, _shared
    walls = _exterior_walls(W, D)
    pair = {}
    for i, a in enumerate(rooms):
        for b in rooms[i + 1:]:
            sh = _shared(a, b)
            if sh is None or sh[3] - sh[2] < 1.0:
                continue
            o, f, lo, hi = sh
            pa, pb = ([f, lo], [f, hi]) if o == "v" else ([lo, f], [hi, f])
            t, more = thickness(a, b) if thickness else (INT_T, {})
            w = dict({"id": f"W{len(walls) + 1}", "a": pa, "b": pb,
                      "thickness": t, "kind": "interior", "face": None},
                     **more)
            walls.append(w)
            pair[(a["id"], b["id"])] = pair[(b["id"], a["id"])] = w
    return walls, pair


def wall_len(w):
    (ax, ay), (bx, by) = w["a"], w["b"]
    return math.hypot(bx - ax, by - ay)


def along_of(w, x, y):
    """Distance along wall w from its start to the point (x, y) on it."""
    (ax, ay), _b = w["a"], w["b"]
    return math.hypot(x - ax, y - ay)


def spans(openings):
    return [(o["wall"], o["along"] - o["width"] / 2,
             o["along"] + o["width"] / 2) for o in openings]


def free(openings, wall, lo, hi, margin=0.25):
    from ..layout import _fits
    return _fits(spans(openings), wall, lo, hi, margin=margin)


def place(openings, w, want, width, margin=0.25, lo=None, hi=None):
    """The along nearest `want` on wall w where an opening `width` wide
    fits (0.5 ft clear of the wall's ends and `margin` clear of the other
    openings), inside [lo, hi] when given; None if nowhere."""
    L = wall_len(w)
    a_min = max(0.5 + width / 2, (lo if lo is not None else 0) + width / 2)
    a_max = min(L - 0.5 - width / 2,
                (hi if hi is not None else L) - width / 2)
    if a_max < a_min - 1e-9:
        return None
    for k in range(0, int((a_max - a_min) / 0.25) + 3):
        for s in ((0,) if k == 0 else (1, -1)):
            a = min(a_max, max(a_min, want + s * k * 0.25))
            if free(openings, w["id"], a - width / 2, a + width / 2,
                    margin):
                return round(a, 3)
    return None


def renumber(openings, first=101):
    """Door ids D1.. and marks 101.. in order; window ids N1.."""
    nd = nw = 0
    for o in openings:
        if o["kind"] == "door":
            nd += 1
            o["id"], o["mark"] = f"D{nd}", str(first - 1 + nd)
        elif o["kind"] == "window":
            nw += 1
            o["id"] = f"N{nw}"


# ---- the parking field (AS-101) --------------------------------------------
def parking(W, spaces, ratio=None, gross=None):
    """The parking field in front of the building: double-loaded rows the
    building's length, about 62 ft each, behind a 10 ft walk (all
    assumed - layout, count and ratio by zoning and the civil engineer).
    On a lot from the brief that the field would run off, site.site_for
    moves the building back toward the rear setback for it, and
    site.widen_parking() widens it to the side setbacks when that is not
    enough."""
    from ... import codecheck
    per_row = 2 * max(1, int((W + 0.5) // STALL_W))
    rows = max(1, int(math.ceil(spaces / per_row)))
    acc = codecheck.accessible_parking(spaces)
    return {"spaces": int(spaces), "ratio": ratio, "side": "S",
            "rows": rows, "depth": WALK + rows * PARKING_ROW,
            "accessible": acc, "van": codecheck.van_parking(acc),
            "assumed": ratio is not None,
            "per_1000": round(spaces / gross * 1000, 2) if gross else None}


def field_fits(plan):
    """Every space of the parking field drawn on the lot in front of the
    building (site.features' parking_fit) - the building may have been
    moved back for it (site.site_for, Oct 22), to just the depth the rows
    take. Without a site to draw: the front yard at least the field's
    depth."""
    from .. import site as site_mod
    pk, s = plan.get("parking"), plan.get("site") or {}
    try:
        fit = (site_mod.features(plan) or {}).get("parking_fit")
    except Exception:                                # noqa: BLE001
        fit = None
    if fit is not None:
        return bool(fit["fits"])
    return s["provided"]["front"] + 1e-6 >= pk["depth"]


def field_width(pk, W):
    """The parking field's paved width: the building's, or the widened
    field's parts added up (site.widen_parking)."""
    return float(pk.get("width") or (W + 0.5))


def field_words(pk, plain):
    """How the paving quantity's width is described."""
    return "the field's width (to the side setbacks) x the parking rows" \
        if pk.get("segments") else plain


# ---- enlarged part plans -----------------------------------------------------
def part_plan(plan, box, rooms):
    """The part of the plan inside box (x0, y0, x1, y1), centreline feet,
    as a plan of its own with its south-west corner at the origin: the
    rooms given, the walls clipped to the box and the openings in them.
    An edge of the box on a partition maps to where an outside face would
    be, so the dimension strings close on the partition centrelines (as
    the warehouse's office plan does)."""
    from .warehouse_draw import _clip
    W, D = plan["footprint"]["width"], plan["footprint"]["depth"]
    bx0, by0, bx1, by1 = box
    e = 1e-6
    sx = 0.0 if bx0 < e else bx0 + 0.25
    sy = 0.0 if by0 < e else by0 + 0.25
    w_ = (W - sx) if bx1 > W - e else (bx1 - sx - 0.25)
    d_ = (D - sy) if by1 > D - e else (by1 - sy - 0.25)
    walls, opens = [], []
    for w in plan["walls"]:
        if w["kind"] == "open":
            got = _clip(w, box)
            if got:
                a, b, _off = got
                walls.append(dict(w, a=[a[0] - sx, a[1] - sy],
                                  b=[b[0] - sx, b[1] - sy]))
            continue
        got = _clip(w, box)
        if got is None:
            continue
        a, b, off = got
        L = math.hypot(b[0] - a[0], b[1] - a[1])
        walls.append(dict(w, a=[a[0] - sx, a[1] - sy],
                          b=[b[0] - sx, b[1] - sy]))
        for o in plan["openings"]:
            if o["wall"] != w["id"]:
                continue
            al = o["along"] - off
            if al - o["width"] / 2 >= 0.5 - 1e-6 and \
                    al + o["width"] / 2 <= L - 0.5 + 1e-6:
                opens.append(dict(o, along=round(al, 3)))
    ids = {r["id"] for r in rooms}
    walls = [w for w in walls if w["kind"] != "open" or
             set(w.get("rooms") or ()) <= ids]
    rs = [dict(r, rect=[r["rect"][0] - sx, r["rect"][1] - sy,
                        r["rect"][2] - sx, r["rect"][3] - sy])
          for r in rooms]
    sub = {k: v for k, v in plan.items()
           if k not in ("grid", "garage", "porch", "deck", "truck_court")}
    sub.update(footprint=dict(plan["footprint"], width=w_, depth=d_),
               walls=walls, rooms=rs, openings=opens,
               _shift=[sx, sy])
    return sub


def part_sheet(sub_fn, title, note):
    """A sheet's draw function for an enlarged part plan: sub_fn(plan) ->
    the part (part_plan), drawn at a larger scale with every door and
    window tagged, and a one-line note under it."""
    def run(ctx, page):
        from .. import draw, views
        from ..draw import DRAW, GREY
        sub = sub_fn(ctx["plan"])
        m = ctx["Model"](sub)              # Modulor builds its walls too
        label, ppf = views.plan_view(ctx["doc"], page, sub, m, title=title,
                                     overall=False, margin_pt=100.0)
        draw.text(page, DRAW.x0 + 10, DRAW.y1 - 80, note, 10, color=GREY)
        return label, ppf
    return run


# ---- quantities ---------------------------------------------------------------
def base_quantities(plan):
    """The small-commercial takeoff of this plan (quantities.rows as an
    office or retail building), "house" words taken out."""
    from .. import quantities as q
    p = dict(plan, project=dict(plan["project"],
                                building_type="small_commercial"))
    out = []
    for g, item, qty, unit, how in q.rows(p):
        out.append((g, item.replace("(house)", "(building)"), qty, unit,
                    how.replace("house perimeter", "building perimeter")))
    return out
