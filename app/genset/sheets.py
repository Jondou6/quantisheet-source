"""The sheet list of a set, as data: SheetSpec(no, title, draw, nts).

build.build_set starts every sheet in this order, draws the drawn sheets
(each returns its scale), then the NTS ones - the cover last of all
needs the drawings' scales, and it is first in the list, so the NTS
sheets are drawn after the drawn ones.

    base_sheets(plan)        the house / small-commercial set, exactly as
                             it has always been numbered
    floor_plan_sheets(plan)  A-101, A-102... one per level
    specs_for(plan)          the building type's list (types/*.py), or
                             base_sheets

A draw function is draw(ctx, page): ctx is a dict with the doc, the plan,
the Modulor models (one per level), the scales so far and the page
numbers; a drawn sheet returns (scale label, points per foot)."""
from dataclasses import dataclass


@dataclass
class SheetSpec:
    no: str
    title: str
    draw: object
    nts: bool = True


def _build():
    from . import build
    return build


def cover(ctx, page):
    _build()._cover(page, ctx["plan"], ctx["scales"])


def general_notes(ctx, page):
    _build()._notes(page, ctx["plan"])


def site_plan(ctx, page):
    from . import views
    return views.site_plan(ctx["doc"], page, ctx["plan"])


def level_plan(i, title):
    def run(ctx, page):
        from . import model, views
        lp = model.levels(ctx["plan"])[i]
        return views.plan_view(ctx["doc"], page, lp, ctx["models"][i],
                               title=title)
    return run


def roof_plan(ctx, page):
    from . import views
    return views.roof_plan(ctx["doc"], page, ctx["plan"])


def elevations(faces=None):
    def run(ctx, page):
        from . import views
        return views.elevations(ctx["doc"], page, ctx["plan"],
                                ctx["models"], faces=faces)
    return run


def section(ctx, page):
    from . import views
    return views.section(ctx["doc"], page, ctx["plan"])


def room_schedule(ctx, page):
    from . import schedules
    schedules.room_schedule_sheet(page, ctx["plan"])


def door_window(ctx, page):
    from . import schedules
    schedules.door_window_sheet(page, ctx["plan"])


def quantity_sheet(ctx, page):
    from . import quantities
    quantities.sheet(page, ctx["plan"])


def accessibility(ctx, page):
    from . import ada_plan
    ada_plan.sheet(page, ctx["plan"])


def code_summary(ctx, page):
    from . import codes
    codes.sheet(page, ctx["plan"])


def floor_plan_sheets(plan):
    """A-101 Floor Plan, or A-101 Level 1 / A-102 Level 2 ... for a
    building of several stories."""
    from . import model
    n = model.stories(plan)
    if n == 1:
        return [SheetSpec("A-101", "Floor Plan", level_plan(0, "Floor Plan"),
                          nts=False)]
    return [SheetSpec(f"A-10{i + 1}", f"Level {i + 1} Floor Plan",
                      level_plan(i, f"Level {i + 1} Floor Plan"), nts=False)
            for i in range(n)]


# draw.DRAW's width in points (ARCH D less the margins and the title
# block) - kept here so the sheet list needs no PyMuPDF; a test checks it
DRAW_W = 2592.0 - 36.0 - 324.0 - 36.0 - 72.0
DRAW_Y0, DRAW_Y1 = 36.0 + 36.0, 1728.0 - 36.0 - 36.0   # draw.DRAW's top, foot
QUAD_SCALE = 4.5                  # 1/16" = 1'-0"


def rows_fit(y, row_h, max_y):
    """The body rows draw.table(y=y, row_h=row_h, max_y=max_y) draws
    before it cuts the table off (the same test, so a schedule split with
    it never loses a row)."""
    yy, k = y + row_h, 0
    while not (yy + row_h > max_y):
        yy += row_h
        k += 1
    return k


def split_rows(n, first, rest):
    """[(a, b)]: n rows, `first` on the first sheet, then `rest` a sheet."""
    first, rest = max(1, first), max(1, rest)
    out = [(0, min(n, first))]
    while out[-1][1] < n:
        a = out[-1][1]
        out.append((a, min(n, a + rest)))
    return out


def continued(parts, no, title, cont_title, draw_part):
    """SheetSpecs for a schedule split over sheets: the first is `no`,
    the others take the next numbers (renumber() puts the rest of the
    series after them). draw_part(ctx, page, part) draws one; part is
    {"k", "rows": (a, b), "group": the specs} - part_nos(part) gives the
    sheet numbers before and after it once the set is numbered."""
    pre, num = no.rsplit("-", 1)
    group = []
    for k, rows in enumerate(parts):
        part = {"k": k, "rows": rows, "group": group}
        group.append(SheetSpec(f"{pre}-{int(num) + k:0{len(num)}d}",
                               cont_title if k else title,
                               (lambda pt: lambda ctx, page:
                                draw_part(ctx, page, pt))(part)))
    return list(group)


def part_nos(part):
    """(previous sheet no, next sheet no) of a continued schedule's part,
    None at the ends."""
    g, k = part["group"], part["k"]
    return (g[k - 1].no if k else None,
            g[k + 1].no if k + 1 < len(g) else None)


def renumber(specs, series):
    """The sheets of a series ("A-6") numbered in order from the first
    one's number - after a schedule gained continuation sheets."""
    got = [s for s in specs if s.no.startswith(series)]
    if got:
        pre, num = got[0].no.rsplit("-", 1)
        for i, s in enumerate(got):
            s.no = f"{pre}-{int(num) + i:0{len(num)}d}"
    return specs


def elevation_layout(plan):
    """"quad": all four faces on one sheet (a quarter each, the way every
    house and small commercial set is drawn); "full": the building's
    longest face doesn't fit a quarter sheet at 1/16" (with views.
    elevations' 4 ft margin each side) - S and N go on one sheet, E and W
    on the next, each face the sheet's full width."""
    W, D = plan["footprint"]["width"], plan["footprint"]["depth"]
    gar = plan.get("garage")
    extra = (gar["width"] + gar["overhang"]) if gar else 0.0
    ov = float(plan["roof"].get("overhang") or 0)
    longest = max(W + extra, D) + 2 * ov
    return "quad" if (longest + 8) * QUAD_SCALE <= DRAW_W / 2 else "full"


def elevation_sheets(plan, first="A-201"):
    """One A-201 with the four faces, or - for a building too long for a
    quarter sheet at 1/16" - A-201 South & North and A-202 East & West."""
    if elevation_layout(plan) == "quad":
        return [SheetSpec(first, "Exterior Elevations", elevations(None),
                          nts=False)]
    return [SheetSpec("A-201", "Exterior Elevations - South & North",
                      elevations(("S", "N")), nts=False),
            SheetSpec("A-202", "Exterior Elevations - East & West",
                      elevations(("E", "W")), nts=False)]


def base_sheets(plan):
    """G-001 Cover, G-002 General Notes, AS-101 Site Plan, A-101 Floor
    Plan (A-102 Level 2), A-102/A-103 Roof Plan, A-201 Exterior
    Elevations, A-301 Building Section, A-601 Room Schedule, A-602 Door &
    Window Schedules, A-701 Quantity Summary, and A-801 Accessibility for
    office and retail."""
    plans = floor_plan_sheets(plan)
    from . import types
    out = [SheetSpec("G-001", "Cover", cover),
           SheetSpec("G-002", "General Notes", general_notes)]
    if getattr(types.for_plan(plan), "code_sheet", False):
        # office and retail too (Jon, Oct 20)
        out.append(SheetSpec("G-003", "Code Summary", code_summary))
    out.append(SheetSpec("AS-101", "Site Plan", site_plan, nts=False))
    out += plans
    out.append(SheetSpec(f"A-10{len(plans) + 1}", "Roof Plan", roof_plan,
                         nts=False))
    out += elevation_sheets(plan)
    out += [SheetSpec("A-301", "Building Section", section, nts=False),
            SheetSpec("A-601", "Room Schedule", room_schedule),
            SheetSpec("A-602", "Door & Window Schedules", door_window),
            SheetSpec("A-701", "Quantity Summary", quantity_sheet)]
    if plan["project"].get("building_type", "single_family") != \
            "single_family":
        out.append(SheetSpec("A-801", "Accessibility", accessibility))
    return out


def specs_for(plan):
    from . import types
    got = types.for_plan(plan).run("sheets", plan, default=None)
    return list(got) if got is not None else base_sheets(plan)
