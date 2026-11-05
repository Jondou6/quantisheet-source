"""Room, door and window schedules - rows straight from the plan, and the
sheets that draw them (A-601, A-602). The rows need no PyMuPDF; the
sheets import it."""
from collections import Counter

from .model import fmt_ftin, levels


def _all_rooms(plan):
    return [r for lp in levels(plan) for r in lp["rooms"]]


def room_rows(plan):
    rows = []
    for r in _all_rooms(plan):
        f = r.get("finishes") or {}
        rows.append([r["number"], r["name"], f"{r['area']:,.0f}",
                     f.get("floor", ""), f.get("base", ""),
                     f.get("walls", ""), f.get("ceiling", ""),
                     fmt_ftin(r.get("ceiling_ht", 9.0))])
    g = plan.get("garage")
    if g:                                   # not heated, not in the total
        rows.append([g["number"], g["name"] + " - NOT HEATED",
                     f"{g['area']:,.0f}", "SC", "-", "GWB-FR", "EXP",
                     fmt_ftin(g["plate_height"])])
    return rows


def room_total(plan):
    return round(sum(r["area"] for r in _all_rooms(plan)), 1)


def door_rows(plan):
    rows = []
    lvls = levels(plan)
    for i, lp in enumerate(lvls):
        names = {r["id"]: f"{r['number']} {r['name']}" for r in lp["rooms"]}
        names["EXT"] = "EXTERIOR"
        names["GAR"] = "G01 GARAGE"
        for o in lp["openings"]:
            if o["kind"] != "door":
                continue
            rows.append([o["mark"], o["type"],
                         f"{fmt_ftin(o['width'])} x {fmt_ftin(o['height'])}",
                         plan["door_types"].get(o["type"], ""),
                         f"{names.get(o.get('from_room'), '?')} -> "
                         f"{names.get(o.get('to_room'), '?')}",
                         (f"L{i + 1} " if len(lvls) > 1 else "") +
                         o["wall"]])
    g = plan.get("garage")
    for k, (a, b) in enumerate((g or {}).get("overhead") or [], 1):
        rows.append([f"OH{k}", "OH",
                     f"{fmt_ftin(b - a)} x {fmt_ftin(g['overhead_h'])}",
                     plan["door_types"].get("OH", ""),
                     "G01 GARAGE -> EXTERIOR", "GAR"])
    return rows


def _marks(marks):
    """'OH1-OH12, OH14' from ['OH1', ..., 'OH12', 'OH14']."""
    import re
    nums = []
    for m in marks:
        g = re.fullmatch(r"([A-Z]+)(\d+)", m)
        nums.append((g.group(1), int(g.group(2))) if g else (m, None))
    out, i = [], 0
    while i < len(nums):
        p, n = nums[i]
        j = i
        while n is not None and j + 1 < len(nums) and \
                nums[j + 1] == (p, nums[j][1] + 1):
            j += 1
        out.append(f"{p}{n}" if j == i or n is None else
                   f"{p}{n}-{p}{nums[j][1]}")
        i = j + 1
    return ", ".join(out)


def overhead_rows(plan):
    """Dock and drive-in doors (opening kind "overhead"), one row per
    type and wall: [type, size, description, count, marks, wall]."""
    groups = {}
    lvls = levels(plan)
    for i, lp in enumerate(lvls):
        for o in lp["openings"]:
            if o["kind"] != "overhead":
                continue
            key = (o["type"], o["width"], o["height"],
                   (f"L{i + 1} " if len(lvls) > 1 else "") + o["wall"])
            groups.setdefault(key, []).append(o["mark"])
    return [[typ, f"{fmt_ftin(w)} x {fmt_ftin(h)}",
             plan["door_types"].get(typ, ""), str(len(m)), _marks(m), wall]
            for (typ, w, h, wall), m in sorted(groups.items())]


def window_rows(plan):
    ops = [o for lp in levels(plan) for o in lp["openings"]]
    count = Counter(o["type"] for o in ops if o["kind"] == "window")
    first = {}
    for o in ops:
        if o["kind"] == "window":
            first.setdefault(o["type"], o)
    rows = []
    for t in sorted(count):
        o = first[t]
        rows.append([t, plan["window_types"].get(t, ""),
                     f"{fmt_ftin(o['width'])} x {fmt_ftin(o['height'])}",
                     str(count[t]), fmt_ftin(o["sill"]),
                     fmt_ftin(o["sill"] + o["height"])])
    return rows


def room_schedule_sheet(page, plan):
    from . import draw
    from .draw import DRAW
    x, y = DRAW.x0 + 20, DRAW.y0 + 40
    draw.text(page, x, y, "ROOM FINISH SCHEDULE", 16, bold=True)
    cols = [("NO.", 70, "center"), ("ROOM NAME", 300, "left"),
            ("AREA (SF)", 120, "right"), ("FLOOR", 120, "center"),
            ("BASE", 100, "center"), ("WALLS", 130, "center"),
            ("CEILING", 120, "center"), ("CLG HT", 110, "center")]
    yy = draw.table(page, x, y + 20, cols, room_rows(plan), size=10,
                    max_y=DRAW.y1 - 120)
    draw.text(page, x + 370 + 120 - 5, yy + 20,
              f"TOTAL  {room_total(plan):,.0f} SF", 11, bold=True,
              align="right")
    _legend(page, x, yy + 60, [
        "LVP luxury vinyl plank  LVT luxury vinyl tile  CPT carpet  "
        "CPT-T carpet tile  CT ceramic tile  SC sealed concrete",
        "WD wood base  RB rubber base  GWB gypsum board  GWB-PT painted  "
        "GWB-MR moisture resistant  GWB-FR fire-rated (garage side)  "
        "ACT acoustic ceiling tile  EXP exposed structure"] + (
        ["QT quarry tile  FRP fiberglass reinforced panel  ACT-V "
         "vinyl-faced (washable) ceiling tile  MFR by the walk-in "
         "manufacturer"] if any(r.get("finishes", {}).get("floor") in
                                ("QT", "MFR") for r in _all_rooms(plan))
        else []))


DOOR_COLS = [("MARK", 70, "center"), ("TYPE", 60, "center"),
             ("SIZE (W x H)", 170, "center"), ("DESCRIPTION", 300, "left"),
             ("LOCATION (FROM -> TO)", 420, "left"), ("WALL", 70, "center")]


def door_pages(plan):
    """[(a, b)]: the door rows split over the door & window sheet (as many
    as fit above the window schedule) and continuation sheets (a full
    sheet each). Pure Python."""
    from .sheets import DRAW_Y0, DRAW_Y1, rows_fit, split_rows
    y = DRAW_Y0 + 40
    return split_rows(len(door_rows(plan)), rows_fit(y + 20, 20,
                                                     DRAW_Y0 + 900),
                      rows_fit(y + 20, 20, DRAW_Y1 - 80))


def door_window_sheet(page, plan, part=None):
    """A-602: the door, overhead door and window schedules. With a part
    (sheets.continued) only its door rows; a continuation sheet has the
    rest of the door schedule alone."""
    from . import draw
    from .codes import _cont_note, part_has_next
    from .draw import DRAW
    x, y = DRAW.x0 + 20, DRAW.y0 + 40
    cols = DOOR_COLS
    rows = door_rows(plan)
    if part is not None:
        a, b = part["rows"]
        rows = rows[a:b]
    if part is not None and part["k"]:
        draw.text(page, x, y, "DOOR SCHEDULE (CONTINUED)", 16, bold=True)
        yy = draw.table(page, x, y + 20, cols, rows, size=10,
                        max_y=DRAW.y1 - 80)
        _cont_note(page, x, yy + 16, part)
        return
    draw.text(page, x, y, "DOOR SCHEDULE", 16, bold=True)
    yy = draw.table(page, x, y + 20, cols, rows, size=10,
                    max_y=DRAW.y0 + 900)
    if part is not None and part_has_next(part):
        _cont_note(page, x, yy + 16, part)
    oh = overhead_rows(plan)
    if oh:                              # dock and drive-in doors
        yo = yy + 50
        draw.text(page, x, yo, "OVERHEAD DOOR SCHEDULE", 16, bold=True)
        cols_oh = [("TYPE", 80, "center"), ("SIZE (W x H)", 160, "center"),
                   ("DESCRIPTION", 520, "left"), ("COUNT", 80, "center"),
                   ("MARKS", 380, "left"), ("WALL", 70, "center")]
        yy = draw.table(page, x, yo + 20, cols_oh, oh, size=10,
                        max_y=DRAW.y1 - 300)
    y2 = yy + 70
    draw.text(page, x, y2, "WINDOW SCHEDULE", 16, bold=True)
    cols = [("TYPE", 70, "center"), ("DESCRIPTION", 330, "left"),
            ("SIZE (W x H)", 170, "center"), ("COUNT", 90, "center"),
            ("SILL", 110, "center"), ("HEAD", 110, "center")]
    draw.table(page, x, y2 + 20, cols, window_rows(plan), size=10,
               max_y=DRAW.y1 - 80)


def _legend(page, x, y, lines):
    from . import draw
    for i, s in enumerate(lines):
        draw.text(page, x, y + i * 16, s, 9, color=draw.GREY)
