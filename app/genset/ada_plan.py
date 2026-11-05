"""ADA checks of a generated office or retail plan (2010 ADA Standards):
door clear widths, turning space in restrooms, route widths, the route
from the entrance to every room, and door maneuvering room. Plus the
chapter 2 scoping lines for what the set shows (app/ada_check.py).

    checks(plan) -> [(status, check, detail, section)]

The plan is drawn to wall centerlines; clear sizes take the partition off
(half each side). A swinging door's clear opening is its leaf less about
2 in. (the stop and the door's own thickness at 90 degrees). These are
checks of the drawings for a starter set - the design professional's
accessibility review still decides."""
from .layout import EXT_T, INT_T
from .model import levels

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"
DOOR_LOSS = 2.0 / 12          # ft lost from the leaf to the clear opening
CLEAR_DOOR = 32.0 / 12        # 404.2.3
ROUTE = 36.0 / 12             # 403.5.1
TURN = 60.0 / 12              # 304.3.1
PULL_DEPTH = 60.0 / 12        # Table 404.2.4.1, front approach, pull side
PUSH_DEPTH = 48.0 / 12        # ... push side
LATCH = 18.0 / 12             # beyond the latch, pull side
WC_CLEAR = (60.0 / 12, 56.0 / 12)   # 604.3.1


def _in(x):
    return f"{x * 12:.0f} in."


def _clear(rect):
    x0, y0, x1, y1 = rect
    return x1 - x0 - INT_T, y1 - y0 - INT_T


def _wall(plan, wid):
    return next((w for w in plan["walls"] if w["id"] == wid), None)


def _doors(lp):
    rooms = {r["id"]: r for r in lp["rooms"]}
    for o in lp["openings"]:
        if o["kind"] == "door":
            yield o, rooms.get(o.get("from_room")), rooms.get(o.get("to_room"))


def _depth(room, wall):
    """The room's clear depth perpendicular to the wall the door is in."""
    if room is None:
        return None                       # outside: open ground
    (ax, ay), (bx, by) = wall["a"], wall["b"]
    cw, cd = _clear(room["rect"])
    return cw if abs(ax - bx) < 1e-6 else cd


def _beyond(lp, o, wall):
    """Wall length left past each edge of the door (to the wall's ends)."""
    (ax, ay), (bx, by) = wall["a"], wall["b"]
    L = abs(bx - ax) + abs(by - ay)
    lo = o["along"] - o["width"] / 2
    hi = L - (o["along"] + o["width"] / 2)
    return lo - INT_T / 2, hi - INT_T / 2


def _route(lp):
    from .audit import _reached
    seen, rooms = _reached(lp)
    return rooms - seen


def checks(plan):
    out = []
    lvls = levels(plan)
    many = len(lvls) > 1
    for n, lp in enumerate(lvls, 1):
        tag = f"L{n}: " if many else ""
        narrow, tight, latch = [], [], []
        for o, a, b in _doors(lp):
            clear = o["width"] - DOOR_LOSS
            name = f"door {o.get('mark', o['id'])}"
            if clear + 1e-6 < CLEAR_DOOR:
                narrow.append(f"{name} {_in(clear)}")
            wall = _wall(lp, o["wall"])
            if wall is None or "mech" in (a and a["type"], b and b["type"]):
                continue           # 203.5: machinery spaces are exempt
            # pull side gets the deeper clearance: the side the door
            # swings into is unknown in v1, so ask for it on the smaller
            # room and the push depth on the other
            depths = [d for d in (_depth(a, wall), _depth(b, wall))
                      if d is not None]
            if depths and (min(depths) + 1e-6 < PUSH_DEPTH or
                           (len(depths) == 2 and
                            max(depths) + 1e-6 < PULL_DEPTH)):
                tight.append(f"{name} ({_in(min(depths))} deep)")
            if wall.get("kind") == "interior" and \
                    max(_beyond(lp, o, wall)) + 1e-6 < LATCH:
                latch.append(name)
        out.append((FAIL if narrow else PASS, tag + "Door clear width",
                    ("Under 32 in. clear: " + ", ".join(narrow)) if narrow
                    else "Every door 32 in. clear minimum", "404.2.3"))
        out.append((WARN if tight else PASS, tag + "Door maneuvering depth",
                    ("Less than 60 in. pull / 48 in. push: " +
                     ", ".join(tight)) if tight else
                    "60 in. pull side and 48 in. push side available",
                    "404.2.4.1"))
        out.append((WARN if latch else PASS, tag + "Latch-side clearance",
                    ("Under 18 in. of wall past the door: " +
                     ", ".join(latch)) if latch else
                    "18 in. of wall beside each interior door",
                    "404.2.4.1"))
        small = []
        for r in lp["rooms"]:
            if r["type"] not in ("restroom", "bath"):
                continue
            cw, cd = _clear(r["rect"])
            if min(cw, cd) + 1e-6 < TURN:
                small.append(f"{r['name']} {_in(cw)} x {_in(cd)}")
        has_rr = any(r["type"] in ("restroom", "bath") for r in lp["rooms"])
        if has_rr:
            out.append((FAIL if small else PASS,
                        tag + "Restroom turning space",
                        ("No 60 in. circle: " + ", ".join(small)) if small
                        else "60 in. turning circle fits in each restroom",
                        "603.2.1 / 304.3.1"))
            out.append((WARN, tag + "Water closet clearance",
                        "Lay out 60 x 56 in. clear at the toilet, its "
                        "centerline 16-18 in. from the side wall; grab "
                        "bars per 604.5", "604.2 / 604.3.1"))
        thin = [f"{r['name']} {_in(min(_clear(r['rect'])))}"
                for r in lp["rooms"] if r["type"] == "hall" and
                min(_clear(r["rect"])) + 1e-6 < ROUTE]
        out.append((FAIL if thin else PASS, tag + "Accessible route width",
                    ("Under 36 in. clear: " + ", ".join(thin)) if thin
                    else "Halls and routes 36 in. clear minimum", "403.5.1"))
        cut = _route(lp)
        names = sorted(r["name"] for r in lp["rooms"] if r["id"] in cut)
        if n == 1 or not many:
            out.append((FAIL if names else PASS,
                        tag + "Route to every room",
                        ("Not reached from the entrance: " +
                         ", ".join(names)) if names else
                        "Every room is reached through doors from the "
                        "entrance", "206.2.4"))
    entries = [o for o, a, _b in _doors(lvls[0])
               if o.get("from_room") == "EXT"]
    out.append((PASS if entries else FAIL, "Accessible entrance",
                f"{len(entries)} entrance door(s), 36 in. leaf; keep the "
                "landing level and the threshold 1/2 in. max" if entries
                else "No entrance door drawn", "206.4 / 404.2.5"))
    if many:
        out.append((WARN, "Accessible route between stories",
                    "Two stories: an elevator may be needed (206.2.3 "
                    "Exception 1 covers private buildings under three "
                    "stories, except shopping centers and health care "
                    "offices)", "206.2.3"))
    return out


def scoping(plan):
    """The ada_check project this set describes, as far as it can tell."""
    occ = plan["project"].get("occupancy", "B")
    rr = [r for lp in levels(plan) for r in lp["rooms"]
          if r["type"] in ("restroom", "bath")]
    entries = [o for o in levels(plan)[0]["openings"]
               if o["kind"] == "door" and o.get("from_room") == "EXT"]
    per = plan["footprint"]["width"] * plan["footprint"]["depth"]
    from . import types
    tp = types.for_plan(plan)
    proj = {"title": "III",
            "use": tp.ada_use_for(occ),
            "stories": len(levels(plan)), "sf_per_story": round(per),
            "public_entrances": len(entries),
            "accessible_entrances": len(entries),
            "single_user_toilets_cluster": len(rr) if len(rr) > 1 else 0,
            "toilet_rooms": [{"name": r["name"], "water_closets": 1,
                              "lavatories": 1} for r in rr]}
    # the building type's own lines (tenant spaces, dining seats, parking)
    return tp.run("scoping", plan, proj, default=proj)


def _scoping_rows(plan):
    from .. import ada_check
    found = [f for f in ada_check.check(scoping(plan))
             if f.group not in ("General",)]
    return [[f.item[:150], str(f.required)[:90], f.cite[:50]]
            for f in found]


def scoping_pages(plan):
    """[(a, b)]: the scoping rows split over A-801 and its continuation
    sheets - the first under the checks table, the others a full sheet
    each. Pure Python."""
    from .sheets import DRAW_Y0, DRAW_Y1, rows_fit, split_rows
    y = DRAW_Y0 + 40
    n_chk = len(checks(plan))
    k = rows_fit(y + 40, 17, DRAW_Y1 - 300)
    yy = y + 40 + 17 * (min(n_chk, k) + 1 + (n_chk > k)) + 24
    return split_rows(len(_scoping_rows(plan)), rows_fit(yy + 8, 17,
                                                         DRAW_Y1 - 60),
                      rows_fit(y + 40, 17, DRAW_Y1 - 60))


SCOPING_COLS = [("REQUIREMENT", 700, "left"), ("NEED", 420, "left"),
                ("SECTION", 250, "left")]


def sheet(page, plan, part=None):
    """A-801: the accessibility checks and the scoping lines. With a part
    (sheets.continued) only its scoping rows; a continuation sheet has
    the rest of the scoping table alone."""
    from . import draw
    from .codes import _cont_note, part_has_next
    from .draw import DRAW
    x, y = DRAW.x0 + 20, DRAW.y0 + 40
    if part is not None and part["k"]:
        draw.text(page, x, y, "ACCESSIBILITY - SCOPING (CONTINUED)", 16,
                  bold=True)
        a, b = part["rows"]
        yy = draw.table(page, x, y + 40, SCOPING_COLS,
                        _scoping_rows(plan)[a:b], size=9, row_h=17,
                        max_y=DRAW.y1 - 60)
        _cont_note(page, x, yy + 16, part)
        return
    draw.text(page, x, y, "ACCESSIBILITY (2010 ADA STANDARDS)", 16,
              bold=True)
    draw.text(page, x, y + 20, "Checked from these drawings. Section "
              "numbers are the 2010 ADA Standards for Accessible Design "
              "(US DOJ). The design professional's accessibility review "
              "decides.", 10, color=draw.GREY)
    cols = [("RESULT", 80, "center"), ("CHECK", 300, "left"),
            ("FINDING", 820, "left"), ("SECTION", 170, "left")]
    rows = [[s, c[:60], d[:175], sec] for s, c, d, sec in checks(plan)]
    yy = draw.table(page, x, y + 40, cols, rows, size=9, row_h=17,
                    max_y=DRAW.y1 - 300) + 24
    draw.text(page, x, yy, "SCOPING (CHAPTER 2)", 11, bold=True)
    srows = _scoping_rows(plan)
    if part is not None:
        srows = srows[:part["rows"][1]]
    yy = draw.table(page, x, yy + 8, SCOPING_COLS, srows, size=9, row_h=17,
                    max_y=DRAW.y1 - 60)
    if part is not None and part_has_next(part):
        _cont_note(page, x, yy + 16, part)
