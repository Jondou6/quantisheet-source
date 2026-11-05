"""The structural grid of a big building: column lines 1, 2, 3... running
north-south (numbered west to east) and A, B, C... running east-west
(lettered south to north), on the exterior wall centrelines at the ends.

    make_grid(W, D, bay=50, end_bay=60) -> grid dict (plan["grid"])
    bays(grid) -> ([x bay sizes], [y bay sizes])
    draw_grid(page, view, grid)                 (needs PyMuPDF)

The bays are as even as the building allows: about `bay` ft each way,
with an `end_bay` speed bay along the north (dock) wall when the building
is deep enough. Bay sizes are an assumed starting point for the
structural engineer, and the plan says so."""

# no I or O: they read as 1 and 0 (the usual convention)
LETTERS = "ABCDEFGHJKLMNPQRSTUVWXYZ"


def _letters(n):
    out = []
    for i in range(n):
        if i < len(LETTERS):
            out.append(LETTERS[i])
        else:
            a, b = divmod(i, len(LETTERS))
            out.append(LETTERS[a - 1] + LETTERS[b])
    return out


def _even(length, bay):
    n = max(1, int(round(length / bay)))
    return [round(length * i / n, 3) for i in range(n + 1)]


def make_grid(W, D, bay=50.0, end_bay=60.0):
    """The grid for a W x D (centreline) building. A speed bay at the
    north wall only when what is left is at least 0.8 of a bay."""
    W, D = float(W), float(D)
    xs = _even(W, bay)
    speed = None
    if end_bay and D - end_bay >= 0.8 * bay:
        ys = _even(D - end_bay, bay) + [D]
        speed = float(end_bay)
    else:
        ys = _even(D, bay)
    return {"x": xs, "y": [round(y, 3) for y in ys],
            "x_labels": [str(i + 1) for i in range(len(xs))],
            "y_labels": _letters(len(ys)),
            "bay": float(bay), "speed_bay": speed, "assumed": True}


def bays(grid):
    xs, ys = grid["x"], grid["y"]
    return ([round(b - a, 3) for a, b in zip(xs, xs[1:])],
            [round(b - a, 3) for a, b in zip(ys, ys[1:])])


def describe(grid):
    """'50'-0" x 50'-0" typical bays, 60'-0" speed bay at the dock wall'"""
    from .model import fmt_ftin
    bx, by = bays(grid)
    typ_y = by[:-1] if grid.get("speed_bay") and len(by) > 1 else by
    txt = f"{fmt_ftin(max(bx))} x {fmt_ftin(max(typ_y))} typical bays"
    if grid.get("speed_bay"):
        txt += f", {fmt_ftin(grid['speed_bay'])} speed bay at the dock wall"
    return txt


def interior_columns(grid):
    """Column count at the grid intersections inside the exterior walls
    (the perimeter is carried by the walls / wall columns)."""
    return max(0, len(grid["x"]) - 2) * max(0, len(grid["y"]) - 2)


def draw_grid(page, view, grid, off_pt=118.0, size=8):
    """Dash-dot grid lines past the building, a bubble at both ends of
    each line (beyond the dimension strings), and the bay dimensions
    along the north and east sides."""
    from . import draw
    from .model import fmt_ftin
    xs, ys = grid["x"], grid["y"]
    W, D = xs[-1], ys[-1]
    k = view.k
    ext = off_pt / k                       # feet to the bubble centre
    r = 9.0                                # bubble radius, points
    for x, lab in zip(xs, grid["x_labels"]):
        a, b = view.p(x, -ext + r / k), view.p(x, D + ext - r / k)
        draw.line(page, a, b, color=draw.GREY, width=0.35,
                  dashes="[12 3 2 3] 0")
        for c in (view.p(x, -ext), view.p(x, D + ext)):
            _bubble(page, c, lab, r, size)
    for y, lab in zip(ys, grid["y_labels"]):
        a, b = view.p(-ext + r / k, y), view.p(W + ext - r / k, y)
        draw.line(page, a, b, color=draw.GREY, width=0.35,
                  dashes="[12 3 2 3] 0")
        for c in (view.p(-ext, y), view.p(W + ext, y)):
            _bubble(page, c, lab, r, size)
    # bay sizes: along the north side (x) and the east side (y)
    for a, b in zip(xs, xs[1:]):
        draw.dim(page, view.p(a, D + 0.25), view.p(b, D + 0.25),
                 fmt_ftin(b - a), off=-(off_pt - 34))
    for a, b in zip(ys, ys[1:]):
        draw.dim(page, view.p(W + 0.25, b), view.p(W + 0.25, a),
                 fmt_ftin(b - a), off=-(off_pt - 34))


def _bubble(page, c, label, r, size):
    from . import draw
    sh = page.new_shape()
    sh.draw_circle(c, r)
    sh.finish(color=draw.INK, fill=(1, 1, 1), width=0.6)
    sh.commit()
    draw.text(page, c.x, c.y + size * 0.36, label, size, bold=True,
              align="center")
