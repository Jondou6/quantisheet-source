"""The lot, the setbacks and where the building sits (Venice, Oct 19: a
buildable envelope that says which limit binds).

Read from the brief: "lot 80 x 120", "75' x 150' lot", "10,000 sf lot",
"0.25 acre lot", and setbacks such as "setbacks 25 front, 10 side, 20 rear".
Whatever the brief leaves out is assumed and marked ASSUMED - VERIFY WITH
ZONING; the drawing never presents a guess as the zoning rule.

The street is to the south (the front door is on the south wall). Plan
coordinates as everywhere else: feet, (0, 0) at the south-west corner of
the wall centrelines, so the building's outside face starts at -0.25."""
import math
import re

SETBACKS = {"single_family": {"front": 25.0, "side": 10.0, "rear": 25.0},
            "small_commercial": {"front": 20.0, "side": 10.0, "rear": 20.0}}
FACE = 0.25                                       # half the exterior wall
SIDE_WALK = 5.0           # ft: the walk from the storefront walk to the
                          # street, along the parking field (assumed)
CAR_LEN = 20.0            # ft of drive-thru lane per stacked car (assumed)
STALL_D = 18.0            # ft: stall depth inside a 62 ft parking row

_N = r"(\d[\d,]*(?:\.\d+)?)"
_FT = r"\s*(?:'|ft\.?|feet|foot)?"
_BY = r"\s*(?:x|×|by)\s*"
_LOT = r"(?:lot|site|parcel|property)"
_SF = r"\s*(?:sf|s\.f\.|sq\.?\s*ft|square\s*feet|sqft|ft2|ft²)"
# "lot 80 x 120", "Lot size: about 75 x 150 ft", "lot is approx. 80x120"
_HEAD = (r"\s*(?:size|area|dimensions?)?\s*(?:is|of|:|-|=)?\s*"
         r"(?:about|approx\w*\.?|around|~)?\s*")
_DIMS = [re.compile(r"\b" + _LOT + _HEAD
                    + _N + _FT + _BY + _N + _FT + r"(?:\s*" + _LOT + r")?",
                    re.I),
         re.compile(_N + _FT + _BY + _N + _FT + r"\s*" + _LOT + r"\b", re.I)]
_AREA = [re.compile(r"\b" + _LOT + _HEAD
                    + _N + _SF + r"\b", re.I),
         re.compile(_N + _SF + r"\s*" + _LOT + r"\b", re.I)]
_ACRE = [re.compile(r"(\d+(?:\.\d+)?|\d+/\d+)\s*(?:-\s*)?ac(?:re)?s?\b"
                    r"(?:\s*" + _LOT + r")?", re.I)]
_KIND = r"(front|sides?|rear|back)"
# "front setback 25", "25 ft side yard" anywhere; inside a "setbacks ..."
# phrase also "25 front, 10 side" / "front 25', side 10'" - but only with a
# unit or a comma / end after the number, so "back 2 bedrooms" or "side 1
# car garage" next to "setbacks per zoning" is never a setback (Fable
# review M4).
_UNIT = r"\s*(?:'|ft\.?|feet|foot)"
_END = r"(?=\s*(?:[,;.)/]|and\b|$|(?:front|sides?|rear|back)\b))"
_SB_NAMED = [re.compile(r"\b" + _KIND + r"\s*(?:yard|setback)s?\s*(?:of|is|:|="
                        r"|-)?\s*" + _N + _FT, re.I),
             re.compile(_N + _FT + r"\s*" + _KIND + r"\s*(?:yard|setback)s?",
                        re.I)]
_SB_PHRASE = re.compile(r"\bsetbacks?\b[^.;\n]{0,80}", re.I)
_SB_IN = [re.compile(r"\b" + _KIND + r"\s*(?:of|is|:|=|-)?\s*" + _N +
                     r"(?:" + _UNIT + r"|" + _END + r")", re.I),
          re.compile(_N + r"(?:" + _UNIT + r")?\s*" + _KIND +
                     r"\b(?=\s*(?:[,;.)/]|and\b|$|\d))", re.I)]

# "parking allowed in the front setback", "front yard parking permitted"
_FRONT_PARKING = re.compile(
    r"\bparking\s+(?:is\s+)?(?:allowed|permitted|ok)\s+in\s+(?:the\s+)?"
    r"front\s+(?:yard|setback)s?\b|\bfront[- ](?:yard|setback)\s+parking\s+"
    r"(?:is\s+)?(?:allowed|permitted|ok)\b", re.I)


def _num(s):
    if "/" in s:
        a, b = s.split("/", 1)
        return float(a) / float(b) if float(b) else None
    try:
        return float(s.replace(",", ""))
    except ValueError:
        return None


def read_lot(text):
    """(lot fields or None, the text with the lot phrases taken out).
    The rest of the brief reader gets the text without them, so a
    "10,000 sf lot" is never read as the building's size."""
    t = text or ""
    lot = {}
    spans = []

    def take(m):
        spans.append(m.span())

    for rx in _DIMS:
        m = rx.search(t)
        if m and "w" not in lot:
            a, b = _num(m.group(1)), _num(m.group(2))
            if a and b and 20 <= min(a, b) and max(a, b) <= 2000:
                # frontage first, as lots are written ("80 x 120")
                lot["w"], lot["d"] = a, b
                take(m)
    if "w" not in lot:
        for rx in _AREA:
            m = rx.search(t)
            if m:
                a = _num(m.group(1))
                if a and 1500 <= a <= 2_000_000:
                    lot["area"] = a
                    take(m)
                    break
    if "w" not in lot and "area" not in lot:
        for rx in _ACRE:
            m = rx.search(t)
            if m:
                a = _num(m.group(1))
                if a and 0.03 <= a <= 40:
                    lot["area"] = round(a * 43560.0)
                    take(m)
                    break
    m = _FRONT_PARKING.search(t)
    if m:
        lot["front_parking"] = True
        take(m)
    sb = {}

    def setback(kind, val, span):
        v = _num(val)
        k = {"back": "rear", "sides": "side"}.get(kind.lower(),
                                                  kind.lower())
        if v is not None and 0 <= v <= 200 and k not in sb:
            sb[k] = v
            spans.append(span)

    def kind_val(m):
        a, b = m.group(1), m.group(2)
        return (a, b) if not a[0].isdigit() else (b, a)

    for rx in _SB_NAMED:
        for m in rx.finditer(t):
            setback(*kind_val(m), m.span())
    for ph in _SB_PHRASE.finditer(t):
        seg = ph.group(0)
        # one way of writing per phrase: "front 25, side 10" or "25 front,
        # 10 side" - whichever comes first (a number or a side's name)
        kw = re.search(r"\b" + _KIND + r"\b", seg, re.I)
        num = re.search(r"\d", seg)
        if not kw or not num:
            continue
        order = [_SB_IN[1]] if num.start() < kw.start() else [_SB_IN[0]]
        for rx in order:
            for m in rx.finditer(seg):
                a, b = m.span()
                setback(*kind_val(m), (ph.start() + a, ph.start() + b))
    if sb:
        lot["setbacks"] = sb
    merged = []
    for a, b in sorted(spans):
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    for a, b in reversed(merged):
        t = t[:a] + " " + t[b:]
    return (lot or None), t


def _up5(x):
    return float(math.ceil(x / 5.0 - 1e-9) * 5)


def site_for(plan, lot=None):
    """The site dict for the plan (stored as plan["site"]) and the warnings
    it raises."""
    lot = lot or {}
    bt = plan["project"]["building_type"]
    from .garage import bbox
    bx0, _by0, bx1, by1 = bbox(plan)            # the house and any garage
    W, D = bx1 - bx0, by1
    wo, do = W + 2 * FACE, D + 2 * FACE               # outside face
    req = dict(SETBACKS.get(bt) or _type_setbacks(bt))
    given = lot.get("setbacks") or {}
    req.update(given)
    sb_from = "brief" if len(given) == 3 else ("brief + assumed" if given
                                                 else "assumed")
    warn = []
    park = _parking_depth(plan)            # a parking field in front
    lane = _lane(plan)                     # a drive-thru lane at the side
    # the parking field stays behind the front setback unless the brief
    # allows parking in the front yard ("parking allowed in the front
    # setback")
    yard_ok = bool(lot.get("front_parking"))
    park_front = (park if yard_ok else park + req["front"]) if park else 0.0
    # a drive-thru lane wraps the sides and the rear, outside a service
    # walk (features() below) - room for both inside the setbacks
    wrap = lane + SIDE_WALK if lane else 0.0
    if lot.get("w"):
        lw, ld, lot_from = float(lot["w"]), float(lot["d"]), "brief"
    elif lot.get("area"):
        # only the area: a lot 1.5 times as deep as it is wide - or, when
        # that is too narrow for the building and its side yards, that
        # wide and the rest deep
        a = float(lot["area"])
        lw = round(math.sqrt(a / 1.5))
        need_w = wo + 2 * req["side"] + 2 * wrap
        if lw < need_w:
            lw = math.ceil(need_w)
        ld = round(a / lw)
        lot_from = "brief area (proportions assumed)"
    else:
        lw = _up5(wo + 2 * req["side"] + 2 * wrap)
        # a truck court behind the dock wall comes before the rear setback;
        # a parking field in front is at least the front setback deep
        ld = _up5(do + max(req["front"], park_front) + req["rear"] +
                  _court(plan) + wrap)
        lot_from = "assumed"
    # centred side to side, the face of the building on the front setback
    left = (lw - wo) / 2
    front = req["front"]
    back = False                          # moved back for the parking
    need = _field_need(plan, bx0 - FACE - left, lw) if park and \
        lot_from != "assumed" else None
    moved = None if need is None else _back_for(
        need, front, do, ld, req, wrap, _court(plan), yard_ok)
    if park_front > front and do + park_front + req["rear"] + wrap + \
            _court(plan) <= ld + 1e-6:
        front = park_front                # the parking in front of it
    elif moved is not None:
        # a lot from the brief the field doesn't fit in front of the
        # building on the front setback: the building moves back toward
        # the rear setback as far as the field needs and no further
        # (owner, Oct 22)
        front, back = moved, True
    elif park > front and do + park + req["rear"] <= ld + 1e-6:
        front = park                      # in the front yard: the self-
                                          # check warns
    if do + front > ld:                   # the building runs off the back
        front = max(0.0, ld - do)
    lot_x0 = bx0 - FACE - left            # lot's SW corner, plan feet
    lot_y0 = -FACE - front
    provided = {"front": front, "rear": ld - front - do,
                "side": min(left, lw - left - wo)}
    env = (lw - 2 * req["side"], ld - req["front"] - req["rear"])
    on_lot = wo <= lw + 1e-6 and do <= ld + 1e-6
    binding = [k for k in ("front", "side", "rear")
               if provided[k] < req[k] - 1e-6]
    if not on_lot:
        warn.append(f"The building ({wo:,.0f}' x {do:,.0f}') is bigger "
                    f"than the lot ({lw:,.0f}' x {ld:,.0f}').")
    elif binding:
        warn.append("The building doesn't fit inside the "
                    + ", ".join(binding) + " setback"
                    + ("s" if len(binding) > 1 else "")
                    + f" (buildable area {max(env[0], 0):,.0f}' x "
                    f"{max(env[1], 0):,.0f}').")
    if lot_from != "brief" and lot.get("area"):
        warn.append(f"Lot dimensions not in the brief - drawn {lw:g}' x "
                    f"{ld:g}' from its {float(lot['area']):,.0f} SF area "
                    "(proportions assumed); get the survey.")
    elif lot_from != "brief":
        warn.append("Lot size not in the brief - drawn just big enough for "
                    "the building and setbacks; get the survey.")
    if sb_from != "brief":
        warn.append("Setbacks assumed (" + ", ".join(
            f"{k} {req[k]:g}'" for k in ("front", "side", "rear")
            if k not in given) + ") - verify with zoning.")
    site = {"lot_w": float(lw), "lot_d": float(ld), "lot_from": lot_from,
            "lot_x0": round(lot_x0, 3), "lot_y0": round(lot_y0, 3),
            "setbacks": req, "setbacks_from": sb_from,
            "assumed": sorted(k for k in ("front", "side", "rear")
                              if k not in given),
            "provided": {k: round(v, 2) for k, v in provided.items()},
            "envelope": [round(max(env[0], 0), 2), round(max(env[1], 0), 2)],
            "on_lot": on_lot, "binding": binding,
            "coverage": round(_covered(plan) / (lw * ld), 4) if lw * ld
            else 0,
            "street": "south"}
    if park:                    # front-yard parking allowed by the brief
        site["front_parking"] = yard_ok
    if back and front > req["front"] + 1e-6:
        site["set_back_for_parking"] = True
    return site, warn


def _back_for(need, front, do, ld, req, wrap, court, yard_ok):
    """How far the building's face sits from the front lot line when it
    moves back for a parking field `need` deep (_field_need), or None
    when even at the rear it can't: the field out of the front setback
    when the lot has room for that (and the drive-thru lane and its
    service walk inside the rear setback line), else just on the lot -
    the self-check warns. Behind the building always its own rear setback
    and room on the lot for the lane and its service walk (in the rear
    yard then - the lane's label says so), so the loop stays whole.
    Where even that doesn't fit, site_for keeps the building where it
    was and the shortfall is said (features() parking_fit)."""
    clear = need + (0.0 if yard_ok else req["front"])
    if do + clear + req["rear"] + wrap + court <= ld + 1e-6:
        return max(front, clear)
    if do + max(front, need) + court + max(req["rear"], wrap) <= ld + 1e-6:
        return max(front, need)
    return None


def _field_need(plan, lot_x0, lw):
    """How deep the parking field is drawn in front of the building's face
    (the storefront walk band and the rows) when every space is drawn, as
    features() lays it out: the field's parts clipped to the side lot
    lines; the last row single-loaded (the building side) when that holds
    the spaces left. None when the field's rows can't hold them all."""
    from .types.parts import PARKING_ROW, STALL_W, WALK
    pk = plan.get("parking")
    if not pk:
        return None
    W = plan["footprint"]["width"]
    segs = [tuple(g) for g in pk.get("segments") or [(-FACE, W + FACE)]]
    segs = [(max(a, lot_x0), min(b, lot_x0 + lw)) for a, b in segs]
    per_side = sum(max(1, int((b - a + 1e-9) // STALL_W)) for a, b in segs
                   if b - a >= STALL_W - 1e-9)
    left = int(pk["spaces"])
    aisle = PARKING_ROW - 2 - 2 * STALL_D
    for k in range(int(pk["rows"])):
        if not per_side:
            break
        if left <= per_side:
            return WALK + k * PARKING_ROW + STALL_D + aisle
        left -= 2 * per_side
        if left <= 0:
            return WALK + k * PARKING_ROW + PARKING_ROW - 2
    return None


def _type_setbacks(bt):
    """Assumed setbacks for a building type not in SETBACKS (types/*.py);
    a house's for anything unknown."""
    from . import types
    tp = types.REGISTRY.get(bt)
    return dict(tp.setbacks) if tp and tp.setbacks else \
        dict(SETBACKS["single_family"])


def _court(plan):
    """Depth of the truck court behind the building (0: none)."""
    return float((plan.get("truck_court") or {}).get("depth") or 0)


def _parking_depth(plan):
    """Depth of the parking field in front of the building (0: none) -
    types/parts.py parking()."""
    return float((plan.get("parking") or {}).get("depth") or 0)


def _lane(plan):
    """Width of a drive-thru lane beside the building (0: none)."""
    return float((plan.get("drive_thru") or {}).get("lane_w") or 0)


def _covered(plan):
    """Ground the buildings cover: the house to its outside face, plus the
    garage beside it (it shares the house wall)."""
    W, D = plan["footprint"]["width"], plan["footprint"]["depth"]
    area = (W + 2 * FACE) * (D + 2 * FACE)
    g = plan.get("garage")
    if g:
        area += g["width"] * (g["depth"] + 2 * FACE)
    return area


# ---- what AS-101 draws around a commercial building (plan feet) -----------
def _box(a, b, half, ext_a, ext_b):
    """The rectangle a lane `half` wide each side covers along the
    orthogonal segment a-b, run on past a / b by ext_a / ext_b."""
    (x0, y0), (x1, y1) = a, b
    if abs(y0 - y1) < 1e-9:                       # east-west
        lo, hi = (x0, x1) if x0 <= x1 else (x1, x0)
        ea, eb = (ext_a, ext_b) if x0 <= x1 else (ext_b, ext_a)
        return (lo - ea, y0 - half, hi + eb, y0 + half)
    lo, hi = (y0, y1) if y0 <= y1 else (y1, y0)
    ea, eb = (ext_a, ext_b) if y0 <= y1 else (ext_b, ext_a)
    return (x0 - half, lo - ea, x0 + half, hi + eb)


def offset_path(pts, d):
    """The orthogonal polyline pts offset d to its left (mitred)."""
    def nrm(a, b):
        dx, dy = b[0] - a[0], b[1] - a[1]
        L = math.hypot(dx, dy) or 1.0
        return -dy / L, dx / L
    out = []
    for i, p in enumerate(pts):
        ns = []
        if i > 0:
            ns.append(nrm(pts[i - 1], p))
        if i < len(pts) - 1:
            ns.append(nrm(p, pts[i + 1]))
        if len(ns) == 2 and abs(ns[0][0] * ns[1][0] + ns[0][1] * ns[1][1]) \
                > 0.5:                              # straight on
            ns = ns[:1]
        out.append((p[0] + sum(n[0] for n in ns) * d,
                    p[1] + sum(n[1] for n in ns) * d))
    return out


def inside(r, box, tol=1e-6):
    """Rectangle r (x0, y0, x1, y1) inside box."""
    return (r[0] >= box[0] - tol and r[1] >= box[1] - tol and
            r[2] <= box[2] + tol and r[3] <= box[3] + tol)


def features(plan):
    """The parking field, the walk to the street and the drive-thru lane
    around the building, as plan-feet data (views.site_plan draws it and
    the tests check it): rows, aisles, stall lines, walks, the lane's
    centreline, edges and boxes, its arrows, the pick-up window and the
    stacking it gives. None when the plan has neither parking nor a
    drive-thru. All of it assumed - layout by the civil engineer."""
    s = plan.get("site")
    pk, dt = plan.get("parking"), plan.get("drive_thru")
    if not s or not (pk or dt):
        return None
    from .types.parts import PARKING_ROW, STALL_W, WALK
    W, D = plan["footprint"]["width"], plan["footprint"]["depth"]
    o = FACE
    lx, ly, lw, ld = s["lot_x0"], s["lot_y0"], s["lot_w"], s["lot_d"]
    lot = (lx, ly, lx + lw, ly + ld)
    sb = s["setbacks"]
    env = (lx + sb["side"], ly + sb["front"], lx + lw - sb["side"],
           ly + ld - sb["rear"])
    f = {"lot": lot, "envelope": env,
         "building": (-o, -o, W + o, D + o),
         "band": None, "rows": [], "aisles": [], "stalls": [], "hc": [],
         "hc_stalls": [], "walks": [], "crosswalk": None, "lane": None,
         "notes": [], "parking_fit": None, "side_aisles": []}
    if pk:
        y_top = -o - WALK
        f["band"] = (-o, y_top, W + o, -o)        # the storefront walk
        # the building's width; or, when the field was widened to the lot
        # (field_segments), the main part first, then the parts beside it
        # (past the walks and the drive-thru lane)
        segs = [tuple(g) for g in pk.get("segments") or [(-o, W + o)]]
        # only what fits on the lot is drawn (review of 0.12.38 #8): the
        # parts clipped to the side lot lines, and no row past the front
        # lot line - a row with room for its aisle and the stalls on the
        # building side only is drawn single-loaded; the shortfall is in
        # parking_fit (the red note and the site data say so)
        segs = [(max(sx0, lx), min(sx1, lx + lw)) for sx0, sx1 in segs]
        segs = [g for g in segs if g[1] - g[0] >= STALL_W - 1e-9]
        spaces = int(pk["spaces"])
        left = spaces
        acc = int(pk.get("accessible") or 0)
        aisle = PARKING_ROW - 2 - 2 * STALL_D
        for k in range(int(pk["rows"])):
            y1 = y_top - k * PARKING_ROW
            y0 = y1 - PARKING_ROW + 2
            sides = ((y1, -1), (y0, 1))                # the two stall rows
            if y0 < ly - 1e-6:                   # past the front lot line
                y0 = y1 - STALL_D - aisle
                if y0 < ly - 1e-6:
                    break
                sides = ((y1, -1),)
            if not segs:
                break
            for si, (sx0, sx1) in enumerate(segs):
                f["rows"].append((sx0, y0, sx1, y1))
                (f["aisles"] if si == 0 else f["side_aisles"]).append(
                    (sx0, y0 + STALL_D if len(sides) == 2 else y0, sx1,
                     y1 - STALL_D))
            for side_y, sgn in sides:
                ya, yb = side_y, side_y + sgn * STALL_D
                for sx0, sx1 in segs:
                    n_st = max(1, int((sx1 - sx0 + 1e-9) // STALL_W))
                    cnt = 0
                    for j in range(n_st):
                        if left <= 0:
                            break
                        x = sx0 + j * STALL_W
                        f["stalls"].append(((x, ya), (x, yb)))
                        if acc > 0:
                            f["hc"].append((x + STALL_W / 2, (ya + yb) / 2))
                            f["hc_stalls"].append((x, min(ya, yb),
                                                   x + STALL_W, max(ya, yb)))
                            acc -= 1
                        left -= 1
                        cnt += 1
                    if cnt:                          # close the last stall
                        x = sx0 + cnt * STALL_W
                        f["stalls"].append(((x, ya), (x, yb)))
        # does the field fit the lot? (site_for moves the building back
        # for it as far as the rear setback and the drive-thru lane
        # allow; where even that is too shallow the building stays on the
        # front setback and a field deeper than the front yard would run
        # past the front lot line - only the stalls on the lot are drawn,
        # and the shortfall is said)
        drawn = spaces - max(0, left)
        f["parking_fit"] = {"fits": drawn >= spaces, "drawn": drawn,
                            "on_lot": drawn, "required": spaces,
                            "short": spaces - drawn, "past_front": 0.0}
    # the walk to the street: along the edge of the field, on the side
    # away from the drive-thru queue (else the side of the front door)
    door = next((op for op in plan["openings"] if op.get("from_room") ==
                 "EXT" and op["wall"] == "W1"), None)
    dside = (dt.get("side") or "E") if dt else None
    if dt:
        wside = "W" if dside == "E" else "E"
    else:
        wside = "W" if (door is None or door["along"] <= W / 2) else "E"
    room_w, room_e = -o - lx, lx + lw - (W + o)
    sw = max(0.0, min(SIDE_WALK, room_w if wside == "W" else room_e))
    if pk and sw >= 3.0 and -o > ly + 0.5:
        top = -o
        x0, x1 = ((-o - sw, -o) if wside == "W" else (W + o, W + o + sw))
        f["walks"].append({"rect": (x0, ly, x1, top), "kind": "street"})
    if dt:
        _lane_features(plan, f, dt, wside, sw, door)
    return f


def field_segments(plan):
    """Where a parking field as wide as the lot allows can go, plan feet:
    [(x0, x1)] between the side setback lines, the building's own width
    first (always kept), then the parts beside it - clear of the walk to
    the street and of the drive-thru lane and its service walk, which run
    the field's whole depth here (review of tonight's changes #10). Parts
    narrower than a stall are left out."""
    from .types.parts import STALL_W
    s = plan["site"]
    W = plan["footprint"]["width"]
    o = FACE
    lx, lw = s["lot_x0"], s["lot_w"]
    side = s["setbacks"]["side"]
    ex0, ex1 = lx + side, lx + lw - side
    dt = plan.get("drive_thru")
    room_w, room_e = -o - lx, lx + lw - (W + o)
    # columns kept clear, as features() and _lane_features() lay them out
    west = east = 0.0                    # how far each side is taken
    if dt:
        L = float(dt["lane_w"])
        is_e = (dt.get("side") or "E") == "E"
        room_r = room_w if is_e else room_e
        sw_r = max(0.0, min(SIDE_WALK, room_r - L))
        east = L + (0.0 if is_e else sw_r)
        west = L + (sw_r if is_e else 0.0)
    else:
        door = next((op for op in plan["openings"] if op.get("from_room")
                     == "EXT" and op["wall"] == "W1"), None)
        wside = "W" if (door is None or door["along"] <= W / 2) else "E"
        sw = max(0.0, min(SIDE_WALK, room_w if wside == "W" else room_e))
        if wside == "W":
            west = sw
        else:
            east = sw
    main = [-o, W + o]
    out = []
    if west == 0.0:
        main[0] = min(main[0], ex0)
    elif -o - west - ex0 >= STALL_W - 1e-9:
        out.append((ex0, -o - west))
    if east == 0.0:
        main[1] = max(main[1], ex1)
    elif ex1 - (W + o + east) >= STALL_W - 1e-9:
        out.append((W + o + east, ex1))
    return [tuple(main)] + out


def _per_row(segs):
    from .types.parts import STALL_W
    return 2 * sum(max(1, int((b - a + 1e-9) // STALL_W)) for a, b in segs)


def widen_parking(plan, lot=None):
    """A field that doesn't fit the lot (deeper than the front yard, even
    with the building moved back as far as site_for can) uses the lot's
    width instead of only the building's - fewer, wider rows - and the
    site is worked out again for the shallower field (site_for then
    moves the building back just as far as that field needs). The
    field stays as it was when that doesn't save a row, the lot is
    assumed (drawn big enough) or the brief allows front-yard parking.
    A field that fits only with the building moved back into the field's
    front setback or the drive-thru lane into the rear yard is widened
    too when the wider field then keeps them out (Oct 22).
    Returns site_for's warnings for the site kept, or None when nothing
    changed."""
    from .types.parts import PARKING_ROW, WALK
    pk, s = plan.get("parking"), plan.get("site")
    if not pk or not s or pk.get("segments") or s.get("lot_from") != \
            "brief":
        return None
    f = features(plan) or {}
    fit = f.get("parking_fit")
    if not fit:
        return None
    if fit["fits"] and (not s.get("set_back_for_parking") or
                        _clean(f, s) == (True, True)):
        return None
    if fit["fits"]:
        # a field that fitted under site_for's rule before Oct 22 (in the
        # front yard, the building just behind it) is kept as it was
        do = s["lot_d"] - s["provided"]["front"] - s["provided"]["rear"]
        sb = s["setbacks"]
        if float(pk["depth"]) > sb["front"] and \
                do + float(pk["depth"]) + sb["rear"] <= s["lot_d"] + 1e-6:
            return None
    segs = field_segments(plan)
    rows = max(1, int(math.ceil(int(pk["spaces"]) / _per_row(segs))))
    if rows >= int(pk["rows"]):
        return None
    old = plan["parking"], plan["site"]
    plan["parking"] = dict(pk, rows=rows, depth=WALK + rows * PARKING_ROW,
                           segments=[[round(a, 3), round(b, 3)]
                                     for a, b in segs],
                           width=round(sum(b - a for a, b in segs), 3))
    plan["site"], warn = site_for(plan, lot)
    if fit["fits"]:                 # widened only if it's cleaner for it
        g = features(plan) or {}
        if not ((g.get("parking_fit") or {}).get("fits") and
                _clean(g, plan["site"]) > _clean(f, s)):
            plan["parking"], plan["site"] = old
            return None
    return warn


def _clean(f, s):
    """(the field out of the front setback - or front-yard parking allowed
    by the brief -, the drive-thru lane beside and behind the building
    inside the setback lines) for features f of site s."""
    env = f["envelope"]
    out = bool(s.get("front_parking")) or all(
        r[1] >= env[1] - 1e-6 for r in f["rows"])
    ln = f.get("lane")
    lane = ln is None or all(inside(b, env) for b in ln["boxes"][1:-1])
    return out, lane


def _window_y(plan, win, D):
    """The plan y of a window on the east or west wall (its wall runs
    either way: the east wall south to north, the west one north to
    south)."""
    w = next((w for w in plan["walls"] if w["id"] == win["wall"]), None)
    if w is None:
        return win["along"]
    ay, by = w["a"][1], w["b"][1]
    return ay + win["along"] if by >= ay else ay - win["along"]


def _lane_features(plan, f, dt, wside, sw, door):
    """The drive-thru lane, one way round the building counterclockwise
    (the pick-up window on the driver's left): in from the far drive
    aisle up the east side, round the rear and down the west side into
    the first drive aisle. With the window on the east wall the queue is
    the east run and the lane is on that wall; with it on the west wall
    the window is on the west run (the queue the east run, the rear and
    the west run to the window). A service walk between the building and
    the lane on the other side and the rear."""
    W, D = plan["footprint"]["width"], plan["footprint"]["depth"]
    o = FACE
    lx, ly, lx1, ly1 = f["lot"]
    L = float(dt["lane_w"])
    h = L / 2
    east = (dt.get("side") or "E") == "E"
    room_e, room_w = lx1 - (W + o), -o - lx
    room_r = room_w if east else room_e                   # the walk side
    room_b = ly1 - (D + o)                                 # behind
    sw_r = max(0.0, min(SIDE_WALK, room_r - L))
    sw_b = max(0.0, min(SIDE_WALK, room_b - L))
    if f["aisles"]:
        a_in = f["aisles"][-1]                   # the far aisle: stacking
        a_out = f["aisles"][0]
        ye, yx = (a_in[1] + a_in[3]) / 2, (a_out[1] + a_out[3]) / 2
    else:
        ye = yx = ly + h
    # the lane on the window's wall, outside the service walk on the other
    xe = W + o + h + (0.0 if east else sw_r)
    xw = -o - h - (sw_r if east else 0.0)
    yr = D + o + sw_b + h
    path = [(W + o, ye), (xe, ye), (xe, yr), (xw, yr), (xw, yx), (-o, yx)]
    boxes = []
    for i in range(len(path) - 1):
        boxes.append(_box(path[i], path[i + 1], h,
                          0.0 if i == 0 else h,
                          0.0 if i == len(path) - 2 else h))
    win = next((op for op in plan["openings"] if op.get("drive_thru")),
               None)
    wy = _window_y(plan, win, D) if win else D / 2
    ww = win["width"] if win else 4.0
    if east:
        queue = h + (wy - ye)
    else:
        queue = (xe - (W + o)) + (yr - ye) + (xe - xw) + (yr - wy)
    stack = int(dt.get("stack") or 8)
    need = stack * CAR_LEN
    # arrows: (tail, head) along the centreline, in the direction of travel
    def along(a, b, t, ln):
        cx, cy = a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t
        dx, dy = b[0] - a[0], b[1] - a[1]
        L_ = math.hypot(dx, dy) or 1.0
        ux, uy = dx / L_, dy / L_
        return ((cx - ux * ln / 2, cy - uy * ln / 2),
                (cx + ux * ln / 2, cy + uy * ln / 2))
    arrows = []                      # candidates per segment, best first
    wseg = 1 if east else 3          # the run past the window
    q0, q1 = path[wseg], path[wseg + 1]
    span_q = max(1.0, abs(q1[1] - q0[1]))
    t_win = abs(wy - q0[1]) / span_q
    split = [(wseg, [t_win / 2, t_win * 0.3, t_win * 0.7]),
             (wseg, [t_win + (1 - t_win) / 2])]
    rest = [(2, [0.15, 0.85, 0.1, 0.9])]
    plain = (3, [0.5, 0.35, 0.65]) if east else (1, [0.5, 0.35, 0.65])
    for seg, ts in (split + rest + [plain] if east else
                    [plain] + rest + split):
        a, b = path[seg], path[seg + 1]
        ln = min(10.0, math.hypot(b[0] - a[0], b[1] - a[1]) / 4)
        arrows.append([along(a, b, t, ln) for t in ts if 0 < t < 1])
    lane = {"width": L, "path": path, "boxes": boxes,
            "edges": [offset_path(path, h), offset_path(path, -h)],
            "window": (W + o if east else -o, wy, ww),
            "queue": round(queue, 1), "window_run": wseg,
            "stack": stack, "need": need, "arrows": arrows,
            "side": "E" if east else "W",
            "in_lot": all(inside(b, f["lot"]) for b in boxes),
            "in_setbacks": all(inside(b, f["envelope"]) for b in boxes)}
    f["lane"] = lane
    if queue < need - 1e-6:
        f["notes"].append(f"stacking {queue:.0f}' of {need:.0f}' shown")
    if room_e < L or room_w < L or room_b < L:
        f["notes"].append("the lane does not fit on the lot")
    elif not lane["in_setbacks"]:
        f["notes"].append("the lane is in a required yard")
    # the service walk: down the side away from the window (and on to the
    # street, across the lane's end there) and across the rear, between
    # the building and the lane
    walks = [w for w in f["walks"] if w["kind"] != "street"]
    street = [w for w in f["walks"] if w["kind"] == "street"]
    if sw_r >= 3.0:
        x0, x1 = -o - sw_r, -o
        if not east:
            x0, x1 = W + o, W + o + sw_r
        y0 = street[0]["rect"][1] if street else -o
        walks.append({"rect": (x0, y0, x1, D + o + (sw_b if sw_b >= 3.0
                                                    else 0.0)),
                      "kind": "street" if street else "service"})
        street = []
        yc = yx if east else ye
        f["crosswalk"] = (x0, yc - h, x1, yc + h)
    if sw_b >= 3.0:
        bx0 = -o - (sw_r if (east and sw_r >= 3.0) else 0.0)
        bx1 = W + o + (sw_r if (not east and sw_r >= 3.0) else 0.0)
        walks.append({"rect": (bx0, D + o, bx1, D + o + sw_b),
                      "kind": "service"})
    f["walks"] = street + walks


def parking_fit_text(fit):
    """'NO - 26 of 80 spaces fit on the lot; 54 short' - for the site
    data table and the notes (only the stalls that fit are drawn)."""
    if fit is None or fit["fits"]:
        return "YES" if fit else ""
    need = fit.get("required", fit["drawn"])
    out = f"NO - {fit['on_lot']} of {need} spaces fit on the lot"
    short = fit.get("short", need - fit["on_lot"])
    if short > 0:
        out += f"; {short} short"
    if fit.get("past_front", 0) > 0:
        out += f"; the field runs {fit['past_front']:.0f}' past the front " \
            "lot line"
    return out


def site_quantities(plan):
    """Paving from the drawn site features (0.12.35): the drive-thru lane
    as its centreline length x its width (exact for square turns - the
    inside corner's shortfall equals the outside corner's overrun), the
    queue length and the side / service walks. {} without features."""
    try:
        f = features(plan)
    except Exception:                                # noqa: BLE001
        return {}
    if not f:
        return {}
    out = {}
    ln = f.get("lane")
    if ln:
        pts = ln["path"]
        cl = sum(math.hypot(b[0] - a[0], b[1] - a[1])
                 for a, b in zip(pts, pts[1:]))
        out["lane_lf"] = round(cl, 1)
        out["lane_sf"] = round(cl * ln["width"], 1)
        out["queue_lf"] = ln["queue"]
        out["stack"] = ln["stack"]
    walks = sum((r[2] - r[0]) * (r[3] - r[1])
                for r in (w["rect"] for w in f.get("walks") or []))
    if walks:
        out["walk_sf"] = round(walks, 1)
    return out
