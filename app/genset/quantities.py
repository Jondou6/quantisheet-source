"""Quantities from the generated set, for a first estimate (0.12.20;
in the PDF for the Quantities panel since 0.12.21).

Everything is measured from the plan JSON - the same numbers the sheets
are drawn from - so the takeoff and the drawings agree. They are gross
quantities with no waste; the sheet says so. Rows:
    (group, item, quantity, unit, how it was measured)
"""
import csv
import math

from .model import fmt_ftin, levels, rect_area, wall_length

GROUPS = ["Site & foundation", "Framing & walls", "Openings", "Finishes",
          "Roof", "Garage, porch & deck"]


def _r(x, nd=0):
    return round(float(x), nd)


def rows(plan):
    """The quantity rows; a building type with its own takeoff
    (types/warehouse.py) gives them itself."""
    from . import types
    got = types.for_plan(plan).run("quantities", plan, default=None)
    if got is not None:
        return list(got)
    out = []

    def add(group, item, qty, unit, how=""):
        if qty:
            out.append((group, item, qty, unit, how))

    W, D = plan["footprint"]["width"], plan["footprint"]["depth"]
    lvls = levels(plan)
    t = 0.25
    foot = (W + 2 * t) * (D + 2 * t)
    lv1 = plan["level"]
    slab_t = float(lv1.get("slab") or 0.33)
    # ---- site & foundation
    add(GROUPS[0], "Slab on grade (house)", _r(foot), "SF",
        "outside face of the walls")
    add(GROUPS[0], f"Slab concrete, {slab_t * 12:.0f}\" thick", _r(
        foot * slab_t / 27, 1), "CY", "slab area x thickness, no waste")
    perim = 2 * (W + D + 4 * t)
    add(GROUPS[0], "Perimeter footing / thickened edge", _r(perim), "LF",
        "house perimeter, outside face")
    # ---- framing & walls, floor by floor
    for i, lp in enumerate(lvls):
        tag = f"L{i + 1} " if len(lvls) > 1 else ""
        h = lp["level"]["plate_height"]
        ext = [w for w in lp["walls"] if w["kind"] == "exterior"]
        inn = [w for w in lp["walls"] if w["kind"] == "interior"]
        ext_lf = sum(wall_length(w) for w in ext)
        int_lf = sum(wall_length(w) for w in inn)
        ops = lp["openings"]
        ext_ids = {w["id"] for w in ext}
        ext_open = sum(o["width"] * o["height"] for o in ops
                       if o["wall"] in ext_ids)
        add(GROUPS[1], f"{tag}Exterior walls", _r(ext_lf), "LF",
            f"centreline, {h:g} ft plate")
        add(GROUPS[1], f"{tag}Exterior wall area, net", _r(
            ext_lf * h - ext_open), "SF",
            "gross less doors and windows (siding, sheathing, insulation)")
        add(GROUPS[1], f"{tag}Interior partitions", _r(int_lf), "LF",
            f"centreline, {h:g} ft")
        int_open = sum(o["width"] * o["height"] for o in ops
                       if o["wall"] not in ext_ids)
        add(GROUPS[1], f"{tag}Gypsum board, walls", _r(
            (2 * int_lf * h - 2 * int_open) + (ext_lf * h - ext_open)),
            "SF", "partitions both sides + inside of exterior walls")
        if i:
            add(GROUPS[1], "Floor framing (level 2)", _r(foot), "SF",
                "over level 1, stairwell not deducted")
    st = plan["rooms"][0].get("stair") if plan.get("upper") else None
    if st:
        add(GROUPS[1], f"Stair, {st['risers']} risers x {st['width']:g} ft",
            1, "EA", f"{st['rise_in']:.2f}\" risers, {st['tread_in']:g}\" "
            "treads, plus guards and rails")
    # ---- openings
    doors, wins = {}, {}
    for lp in lvls:
        for o in lp["openings"]:
            key = (o["type"], o["width"], o["height"])
            (doors if o["kind"] == "door" else wins)[key] = \
                (doors if o["kind"] == "door" else wins).get(key, 0) + 1
    for (typ, w, h), n in sorted(doors.items()):
        add(GROUPS[2], f"Door {typ}: {plan['door_types'].get(typ, '')}", n,
            "EA", f"{fmt_ftin(w)} x {fmt_ftin(h)}")
    for (typ, w, h), n in sorted(wins.items()):
        add(GROUPS[2], f"Window {typ}: "
            f"{plan['window_types'].get(typ, '')}", n, "EA",
            f"{fmt_ftin(w)} x {fmt_ftin(h)}")
    # ---- finishes (floor, base, ceiling) by code
    floor, ceil, base = {}, {}, {}
    for lp in lvls:
        for r in lp["rooms"]:
            f = r.get("finishes") or {}
            a = rect_area(r["rect"])
            x0, y0, x1, y1 = r["rect"]
            kf, kc, kb = (f.get(k) or "TBD" for k in ("floor", "ceiling",
                                                       "base"))
            floor[kf] = floor.get(kf, 0) + a
            ceil[kc] = ceil.get(kc, 0) + a
            base[kb] = base.get(kb, 0) + 2 * ((x1 - x0) + (y1 - y0))
    for code, a in sorted(floor.items()):
        add(GROUPS[3], f"Floor finish {code}", _r(a), "SF",
            "room areas, no waste")
    for code, lf in sorted(base.items()):
        if code not in ("-", "TBD"):
            add(GROUPS[3], f"Base {code}", _r(lf), "LF",
                "room perimeters, doors not deducted")
    for code, a in sorted(ceil.items()):
        add(GROUPS[3], f"Ceiling {code}", _r(a), "SF", "room areas")
    # ---- roof
    roof = plan["roof"]
    ov = float(roof.get("overhang") or 0)
    plan_area = (W + 2 * t + 2 * ov) * (D + 2 * t + 2 * ov)
    if roof["type"] == "gable":
        f = math.sqrt(1 + (roof["pitch"] / 12.0) ** 2)
        add(GROUPS[4], f"Roof, {roof['pitch']:g}:12 gable", _r(
            plan_area * f), "SF", f"plan area incl. {ov:g} ft overhang x "
            f"slope factor {f:.3f}")
        add(GROUPS[4], "Roofing squares", _r(plan_area * f / 100, 1), "SQ",
            "no waste")
        # the ridge runs along x (east-west), or along y on a deep house
        along, across = (D, W) if roof.get("ridge_dir") == "y" else (W, D)
        add(GROUPS[4], "Ridge", _r(along + 2 * t + 2 * ov), "LF")
        add(GROUPS[4], "Eaves / gutters", _r(2 * (along + 2 * t + 2 * ov)),
            "LF")
        add(GROUPS[4], "Rakes", _r(4 * (across / 2 + t + ov) * f), "LF")
    else:
        add(GROUPS[4], "Low-slope roof membrane", _r(plan_area), "SF",
            "inside the parapet, no turn-ups")
        add(GROUPS[4], "Parapet", _r(perim), "LF",
            f"{roof.get('parapet', 0):g} ft high")
        add(GROUPS[4], "Roof drains", 2, "EA", "plus overflows - by the "
            "design professional")
    # ---- site paving (drawn on AS-101)
    st_ = plan.get("site")
    g = plan.get("garage")
    if st_:
        ly = float(st_["lot_y0"])
        if g and g.get("overhead"):
            a = min(x for x, _ in g["overhead"])
            b = max(x for _, x in g["overhead"])
            add(GROUPS[0], "Driveway paving",
                _r((b - a + 2) * max(0.0, -t - ly)),
                "SF", "overhead doors + 1 ft each side, to the lot line")
        door = next((o for o in plan["openings"] if o.get("from_room") ==
                     "EXT" and o["wall"] == "W1"), None)
        if door and not plan.get("parking"):   # parking: AS-101 draws
            p_ = plan.get("porch")              # the walk beside the field
            end = p_["rect"][1] if p_ else -t
            add(GROUPS[0], "Front walk, 4 ft", _r(4 * max(0.0, end - ly)),
                "SF",
                "front door (or porch) to the lot line")
    # ---- garage, porch, deck
    g = plan.get("garage")
    if g:
        add(GROUPS[5], f"Garage slab ({g['cars']}-car)", _r(
            g["width"] * (g["depth"] + 2 * t)), "SF")
        # front, back and the outer side (2 x width + depth) - the house
        # wall is the fourth (Venice review S1: was 2 x depth + width)
        add(GROUPS[5], "Garage walls (3 sides)", _r(
            2 * g["width"] + g["depth"]), "LF",
            f"{g['plate_height']:g} ft plate, overhead door openings "
            "not deducted")
        gf = math.sqrt(1 + (g["pitch"] / 12.0) ** 2)
        add(GROUPS[5], "Garage roof", _r(
            (g["width"] + g["overhang"]) * (g["depth"] + 2 * g["overhang"])
            * gf), "SF")
        for k, (a, b) in enumerate(g["overhead"], 1):
            add(GROUPS[5], f"Overhead door OH{k}", 1, "EA",
                f"{b - a:g} x {g['overhead_h']:g} ft")
    p = plan.get("porch")
    if p:
        add(GROUPS[5], "Porch slab", _r(p["area"]), "SF")
        add(GROUPS[5], "Porch roof", _r((p["width"] + 1) * (p["depth"] +
                                                         0.5)), "SF")
        add(GROUPS[5], "Porch posts", len(p["posts"]), "EA")
    d = plan.get("deck")
    if d:
        add(GROUPS[5], "Deck", _r(d["area"]), "SF", "framing and decking")
        add(GROUPS[5], "Deck guard", _r(2 * d["depth"] + d["width"]), "LF",
            '36" - verify stairs and guards locally')
    return out


def write_csv(plan, path):
    from .. import safecell
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = safecell.writer(f)
        w.writerow(["Group", "Item", "Quantity", "Unit", "Measured"])
        for r in rows(plan):
            w.writerow(r)
    return path


def sheet(page, plan):
    """A-701: the quantities, grouped, with the caveat."""
    from . import draw
    from .draw import DRAW
    x, y = DRAW.x0 + 20, DRAW.y0 + 40
    draw.text(page, x, y, "QUANTITY SUMMARY", 16, bold=True)
    draw.text(page, x, y + 20, "Measured from these drawings for a first "
              "estimate - gross quantities, no waste or laps. Verify "
              "against the final design.", 10, color=draw.GREY)
    draw.text(page, x, y + 34, "To price them: open this PDF in QuantiSheet "
              "- the Quantities panel lists each row as a Set line.", 10,
              color=draw.GREY)
    cols = [("ITEM", 620, "left"), ("QTY", 120, "right"),
            ("UNIT", 70, "center"), ("HOW IT WAS MEASURED", 560, "left")]
    yy = y + 52
    data = rows(plan)
    groups = list(GROUPS)
    for r in data:                  # a building type's own groups, after
        if r[0] not in groups:
            groups.append(r[0])
    for grp in groups:
        part = [[r[1], f"{r[2]:,}" if isinstance(r[2], int) else
                 f"{r[2]:,.1f}".rstrip("0").rstrip("."), r[3], r[4]]
                for r in data if r[0] == grp]
        if not part:
            continue
        if yy > DRAW.y1 - 160:
            draw.text(page, x, yy + 14, "(continued in the .quantities.csv "
                      "file)", 10, color=draw.GREY)
            break
        draw.text(page, x, yy + 14, grp.upper(), 11, bold=True)
        yy = draw.table(page, x, yy + 22, cols, part, size=9, row_h=17,
                        max_y=DRAW.y1 - 120) + 8
