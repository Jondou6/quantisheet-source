"""A code summary for a generated set (sheet G-003) - a SCREENING, from
the code tables in app/codecheck.py (IBC 2021 / IPC 2021), never numbers
of its own. Anything those tables don't cover is printed as UNVERIFIED;
anything the brief didn't give is printed as assumed.

    occupant_load(plan) -> [row]      per room, IBC Table 1004.5 by the
                                      room's "use" (codecheck.USES key)
    exits_required(plan) -> dict      exits per story (1006.3.3), spaces
                                      needing two exits (Table 1006.2.1),
                                      egress door width (1005.3.2)
    travel_estimate(plan) -> dict     exit access travel (Table 1017.2) -
                                      a rectilinear estimate, labelled so
    fixtures_required(plan) -> [row]  IPC Table 2902.1 per portion
    sprinkler_notes(plan) -> [str]
    analyze(plan) -> dict             all of it (stored as plan["code"])
    sheet(page, plan)                 draws G-003 (needs PyMuPDF)

Used for the newer building types (types/*.py code_sheet); house and
small-commercial sets are unchanged."""
import math

from .. import codecheck
from .model import levels, rect_area

ASSUMED_SPRINKLERED = True


def _group(plan):
    return str(plan["project"].get("occupancy") or "B").upper()


def _zone_group(plan, room):
    """The occupancy of the part of the building the room is in: the
    office front is a B portion, the rest the building's group."""
    return "B" if room.get("zone") == "office" else _group(plan)


def _use(plan, room):
    return room.get("use") or codecheck.guess_use(room["name"],
                                                  _zone_group(plan, room))


def _main_use(plan, room):
    return codecheck.MAIN_USE.get(codecheck.letter(_zone_group(plan, room)),
                                  "business")


def occupant_load(plan):
    """[{number, name, use, label, area, factor, basis, load, group}]."""
    out = []
    for lp in levels(plan):
        for r in lp["rooms"]:
            use = _use(plan, r)
            label, factor, basis, _occ = codecheck.USES.get(
                use, codecheck.USES["business"])
            area = rect_area(r["rect"])
            out.append({"number": r["number"], "name": r["name"],
                        "use": use, "label": label, "area": round(area, 1),
                        "factor": factor, "basis": basis,
                        "load": codecheck.occupant_load(area, use,
                                                        _main_use(plan, r)),
                        "group": _zone_group(plan, r),
                        "room": r["id"]})
    return out


def _exit_doors(lp):
    return [o for o in lp["openings"] if o["kind"] == "door" and
            o.get("from_room") == "EXT"]


def _door_xy(lp, o):
    w = next(w for w in lp["walls"] if w["id"] == o["wall"])
    (ax, ay), (bx, by) = w["a"], w["b"]
    L = math.hypot(bx - ax, by - ay) or 1
    return ax + (bx - ax) * o["along"] / L, ay + (by - ay) * o["along"] / L


def exits_required(plan, rows=None):
    """Story load, exits needed and drawn, egress width, and the spaces
    over the one-exit limit with the doors they have."""
    rows = rows if rows is not None else occupant_load(plan)
    lp = levels(plan)[0]
    load = sum(r["load"] for r in rows)
    need = codecheck.exits_per_story(load)
    doors = _exit_doors(lp)
    lvl, _stair = codecheck.egress_factors(_group(plan),
                                           ASSUMED_SPRINKLERED)
    from .ada_plan import DOOR_LOSS
    width_in = sum((o["width"] - DOOR_LOSS) * 12 for o in doors)
    two = []
    for r in rows:
        one = codecheck.one_exit_max(r["group"])
        if r["load"] > one:
            n = sum(1 for o in lp["openings"] if o["kind"] == "door" and
                    r["room"] in (o.get("from_room"), o.get("to_room")))
            two.append({"name": r["name"], "load": r["load"], "max": one,
                        "doors": n})
    return {"load": load, "need": need, "have": len(doors),
            "factor_in": lvl, "width_need_in": round(load * lvl, 1),
            "width_have_in": round(width_in, 1), "two_exit_spaces": two}


def travel_estimate(plan):
    """The longest exit access travel, estimated as the rectilinear
    distance (no racks, no walls) from the room corners and centres to
    the nearest exit door - APPROXIMATE. The limit is the strictest of
    the rooms' groups (Table 1017.2, sprinklered as assumed)."""
    lp = levels(plan)[0]
    doors = [_door_xy(lp, o) for o in _exit_doors(lp)]
    worst, where, limit = 0.0, "", None
    for r in lp["rooms"]:
        x0, y0, x1, y1 = r["rect"]
        pts = [(x0 + 1, y0 + 1), (x1 - 1, y0 + 1), (x0 + 1, y1 - 1),
               (x1 - 1, y1 - 1), ((x0 + x1) / 2, (y0 + y1) / 2)]
        for px, py in pts:
            d = min((abs(px - dx) + abs(py - dy) for dx, dy in doors),
                    default=float("inf"))
            if d > worst:
                worst, where = d, r["name"]
        lim = codecheck.travel_limit(_zone_group(plan, r),
                                     ASSUMED_SPRINKLERED)
        if lim is not None:
            limit = lim if limit is None else min(limit, lim)
    return {"max_ft": round(worst, 1), "where": where, "limit": limit,
            "approximate": True}


def fixtures_required(plan, rows=None):
    """[{portion, group, load, fx}] - fx from codecheck.fixtures, or None
    when its short table has no row for the group (UNVERIFIED)."""
    rows = rows if rows is not None else occupant_load(plan)
    loads = {}
    for r in rows:
        loads[r["group"]] = loads.get(r["group"], 0) + r["load"]
    out = []
    for g, n in loads.items():
        name = "Office portion" if g == "B" and g != _group(plan) else \
            f"{g} portion"
        out.append({"portion": name, "group": g, "load": n,
                    "fx": codecheck.fixtures(n, g)})
    return out


def sprinkler_notes(plan):
    out = ["Assumed fully sprinklered (NFPA 13) - the travel distance "
           "limits use the sprinklered column of IBC Table 1017.2."]
    occ = _group(plan)
    if codecheck.letter(occ) in ("S", "F"):
        out.append("UNVERIFIED: whether IBC 903.2 requires sprinklers for "
                   "this fire area - not in this tool's tables.")
        out.append("UNVERIFIED: high-piled combustible storage (IFC "
                   "Chapter 32) - the commodity class and storage height "
                   "set the sprinkler design; not checked.")
    out.append("UNVERIFIED: construction type, allowable area and height "
               "(IBC Chapter 5) - not in this tool's tables.")
    if occ == "A-2":
        out.append("UNVERIFIED: IBC 903.2.1.2 - an A-2 fire area over "
                   "5,000 SF or for 100 or more occupants needs sprinklers; "
                   "the threshold is not in this tool's tables.")
        out.append("UNVERIFIED: commercial kitchen hood, grease duct and "
                   "its fire suppression (IMC 507 / NFPA 96) - by the "
                   "mechanical engineer.")
    if any(r.get("zone") == "office" for r in plan["rooms"]):
        out.append("The office front is counted as a B portion (accessory "
                   "or separated - by the design professional).")
    return out


def parking(plan):
    """(spaces, accessible, van) when the brief gave a parking count, or
    the parking field the building type drew (types/parts.py parking:
    its count may be assumed - "assumed" says so)."""
    pk = plan.get("parking") or {}
    if pk.get("spaces"):
        return {"spaces": int(pk["spaces"]), "accessible": pk["accessible"],
                "van": pk["van"], "assumed": bool(pk.get("assumed"))}
    n = (plan.get("warehouse") or {}).get("parking")
    if not n:
        return None
    acc = codecheck.accessible_parking(n)
    return {"spaces": n, "accessible": acc,
            "van": codecheck.van_parking(acc)}


def assumed(plan):
    """What the building type assumed (not in the brief): its plan's
    "assumed" list (plan["warehouse"], plan["strip"], plan["restaurant"])."""
    for k in ("warehouse", "strip", "restaurant"):
        got = (plan.get(k) or {}).get("assumed")
        if got:
            return list(got)
    return []


def analyze(plan, store=True):
    rows = occupant_load(plan)
    res = {"edition": codecheck.EDITION, "group": _group(plan),
           "sprinklered": ASSUMED_SPRINKLERED, "sprinklered_assumed": True,
           "rooms": rows, "exits": exits_required(plan, rows),
           "travel": travel_estimate(plan),
           "fixtures": fixtures_required(plan, rows),
           "notes": sprinkler_notes(plan), "parking": parking(plan)}
    if store:
        plan["code"] = res
    return res


def _fx_text(f):
    fx = f["fx"]
    if fx is None:
        return (f"UNVERIFIED - IPC Table 2902.1 row for {f['group']} not in "
                "this tool's short table")
    return (f"{fx['wc']} WC ({fx['wc_each']} per sex), {fx['lav']} lav "
            f"({fx['lav_each']} per sex), {fx['df']} drinking fountain, "
            f"{fx['service_sink']} service sink")


def _load_rows(c):
    rows = [[r["number"], r["name"][:30], r["label"][:96],
             f"{r['area']:,.0f}",
             f"{r['factor']} {r['basis']}" if r["factor"] else r["basis"],
             r["group"], str(r["load"])] for r in c["rooms"]]
    rows.append(["", "TOTAL", "", "", "", "", str(c["exits"]["load"])])
    return rows


LOAD_COLS = [("NO.", 60, "center"), ("SPACE", 260, "left"),
             ("FUNCTION (IBC TABLE 1004.5)", 470, "left"),
             ("AREA (SF)", 110, "right"), ("SF / OCC", 110, "right"),
             ("GROUP", 70, "center"), ("OCCUPANTS", 100, "right")]


def load_pages(plan):
    """[(a, b)]: the occupant load rows (and the total) split over G-003
    and its continuation sheets - the first as many as fit above the
    exits table, the others a full sheet each. Pure Python."""
    from .sheets import DRAW_Y0, DRAW_Y1, rows_fit, split_rows
    n = len(analyze(plan, store=False)["rooms"]) + 1
    y = DRAW_Y0 + 40
    return split_rows(n, rows_fit(y + 40, 17, DRAW_Y0 + 760),
                      rows_fit(y + 40, 17, DRAW_Y1 - 60))


def part_has_next(part):
    return part["k"] + 1 < len(part["group"])


def _cont_note(page, x, y, part, size=9):
    """'Continued on G-004.' / 'Continued from G-003.' under a split
    schedule."""
    from . import draw
    from .sheets import part_nos
    prev, nxt = part_nos(part)
    s = " ".join(t for t in (
        f"Continued from {prev}." if prev else "",
        f"Continued on {nxt}." if nxt else "") if t)
    draw.text(page, x, y, s, size, color=draw.GREY)


def sheet(page, plan, part=None):
    """G-003: the code summary - occupant load by room, exits, travel,
    egress width, plumbing fixtures, and what wasn't checked. With a part
    (sheets.continued) only its occupant load rows; a continuation sheet
    has the rest of the table alone."""
    from . import draw
    from .draw import DRAW
    c = analyze(plan, store=False)
    x, y = DRAW.x0 + 20, DRAW.y0 + 40
    if part is not None and part["k"]:
        draw.text(page, x, y, "CODE SUMMARY - SCREENING ONLY (CONTINUED)",
                  16, bold=True)
        a, b = part["rows"]
        yy = draw.table(page, x, y + 40, LOAD_COLS, _load_rows(c)[a:b],
                        size=9, row_h=17, max_y=DRAW.y1 - 60)
        _cont_note(page, x, yy + 16, part)
        return
    draw.text(page, x, y, "CODE SUMMARY - SCREENING ONLY", 16, bold=True)
    draw.text(page, x, y + 20, f"{c['edition']}. From the tables in "
              "QuantiSheet's code check; local amendments, the adopted edition "
              "and the exceptions decide. Code analysis by the design "
              "professional.", 10, color=draw.GREY)
    rows = _load_rows(c)
    if part is not None:
        rows = rows[:part["rows"][1]]
    yy = draw.table(page, x, y + 40, LOAD_COLS, rows, size=9, row_h=17,
                    max_y=DRAW.y0 + 760) + 30
    if part is not None and part_has_next(part):
        _cont_note(page, x, yy - 14, part)
        yy += 6
    ex, tr = c["exits"], c["travel"]
    lines = [
        ["Exits from the story (IBC 1006.3.3)",
         f"{ex['need']} needed for {ex['load']} occupants",
         f"{ex['have']} exit doors drawn"],
        ["Egress door width (IBC 1005.3.2)",
         f"{ex['width_need_in']:.0f} in. ({ex['factor_in']} in. per "
         "occupant)", f"{ex['width_have_in']:.0f} in. clear drawn"],
        ["Exit access travel (IBC Table 1017.2)",
         f"{tr['limit']} ft max (sprinklered, assumed)" if tr["limit"]
         else "UNVERIFIED - group not in the table",
         f"about {tr['max_ft']:.0f} ft ({tr['where']}) - APPROXIMATE, "
         "rectilinear, no racking"]]
    for s in ex["two_exit_spaces"]:
        lines.append([f"Two exits: {s['name'][:28]} (Table 1006.2.1)",
                      f"{s['load']} occupants > {s['max']}",
                      f"{s['doors']} doors drawn"])
    for f in c["fixtures"]:
        lines.append([f"Plumbing, {f['portion']} (IPC 2902.1)",
                      f"{f['load']} occupants", _fx_text(f)])
    pk = c["parking"]
    lines.append(["Accessible parking (IBC 1106.1)",
                  f"{pk['accessible']} accessible, {pk['van']} van, of "
                  f"{pk['spaces']}" + (" (count assumed)" if
                                       pk.get("assumed") else "")
                  if pk else "parking count not in the brief",
                  "show on the site plan"])
    from . import types       # the building type's own lines (tenants...)
    lines += [list(x) for x in types.for_plan(plan).run(
        "code_lines", plan, c, default=None) or []]
    cols2 = [("ITEM", 420, "left"), ("REQUIRED", 420, "left"),
             ("THIS SET", 640, "left")]
    yy = draw.table(page, x, yy, cols2, [[a[:70], b[:72], t_[:110]]
                                         for a, b, t_ in lines],
                    size=9, row_h=18, max_y=DRAW.y1 - 260) + 30
    draw.text(page, x, yy, "NOT CHECKED HERE / ASSUMED", 11, bold=True)
    asm = assumed(plan)
    notes_ = c["notes"] + (["Assumed (not in the brief): " +
                            "; ".join(asm) + "."] if asm else [])
    ny = yy + 20
    for i, n in enumerate(notes_):
        words, line_ = f"{i + 1}. {n}".split(), ""
        for w in words:                     # wrap to the drawing width
            if line_ and draw.text_width(line_ + " " + w, 9) > \
                    DRAW.width - 60:
                draw.text(page, x, ny, line_, 9)
                ny += 13
                line_ = "    " + w
            else:
                line_ = (line_ + " " + w).strip() if line_.strip() else \
                    line_ + w
        draw.text(page, x, ny, line_, 9)
        ny += 16
