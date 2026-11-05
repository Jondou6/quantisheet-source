"""PyMuPDF drawing primitives for the sheets: text, walls, doors,
windows, tags, dimensions, level lines, north arrow, tables.

Plan coordinates are decimal feet with +Y north; a View maps them onto
the sheet at a scale (points per foot) with +Y up."""
import math
import os

import fitz

from .model import fmt_ftin

SHEET_W, SHEET_H = 2592.0, 1728.0                 # ARCH D, landscape
MARGIN = 36.0
TB_W = 324.0                                      # title block strip, 4.5"
DRAW = fitz.Rect(MARGIN + 36, MARGIN + 36,
                 SHEET_W - MARGIN - TB_W - 36, SHEET_H - MARGIN - 36)
INK = (0.08, 0.08, 0.1)
GREY = (0.45, 0.45, 0.48)
LIGHT = (0.86, 0.86, 0.88)
POCHE = (0.18, 0.18, 0.2)
RED = (0.78, 0.07, 0.07)

_FONTS = {}
_WIN = r"C:\Windows\Fonts"


def _font_files():
    # Embedded Arial reads back wrong (spaces as no-break spaces, hyphens as
    # soft hyphens, the em dash lost), which breaks Find and the takeoff
    # readers. The built-in Helvetica looks the same and reads back clean.
    if not os.environ.get("QUANTISHEET_GENSET_ARIAL"):
        return None, None
    reg = os.path.join(_WIN, "arial.ttf")
    bold = os.path.join(_WIN, "arialbd.ttf")
    if os.path.isfile(reg) and os.path.isfile(bold):
        return reg, bold
    return None, None


def font(bold=False):
    """(fontname to use on a page, fitz.Font for measuring)."""
    key = "b" if bold else "r"
    if key not in _FONTS:
        reg, bd = _font_files()
        path = bd if bold else reg
        if path:
            _FONTS[key] = ("ArialB" if bold else "Arial", fitz.Font(
                fontfile=path), path)
        else:
            name = "hebo" if bold else "helv"
            _FONTS[key] = (name, fitz.Font(name), None)
    return _FONTS[key]


def ensure_fonts(page):
    for bold in (False, True):
        name, _, path = font(bold)
        if path and name not in getattr(page, "_gs_fonts", set()):
            page.insert_font(fontname=name, fontfile=path)
            page._gs_fonts = getattr(page, "_gs_fonts", set()) | {name}


def text_width(s, size, bold=False):
    return font(bold)[1].text_length(s, fontsize=size)


def text(page, x, y, s, size=10, bold=False, color=INK, align="left",
         rotate=0):
    """Text with its baseline at y; align left/center/right on x.
    Written with a TextWriter: it reads back exactly (spaces, hyphens and
    the em dash), which Find and the takeoff readers rely on."""
    if not s:
        return
    _name, f, _path = font(bold)
    w = f.text_length(s, fontsize=size)
    if align == "center":
        x -= w / 2
    elif align == "right":
        x -= w
    tw = fitz.TextWriter(page.rect)
    tw.append((x, y), s, font=f, fontsize=size)
    morph = (fitz.Point(x + (w / 2 if align == "center" else 0), y),
             fitz.Matrix(rotate)) if rotate else None
    tw.write_text(page, color=color, morph=morph)


def fit(s, size, bold=False, max_w=None, min_size=7):
    """(text, size) that fits max_w points: shrink the type down to
    min_size, then cut the end with an ellipsis (Venice M-4: a long project
    name ran off the title block)."""
    s = s or ""
    if not max_w:
        return s, size
    while size > min_size and text_width(s, size, bold) > max_w:
        size -= 0.5
    if text_width(s, size, bold) > max_w:
        while s and text_width(s + "\u2026", size, bold) > max_w:
            s = s[:-1]
        s = s.rstrip() + "\u2026"
    return s, size


class View:
    """Plan feet -> sheet points: x right, y up, `ppf` points per foot,
    (ox, oy) is where plan (0, 0) lands."""

    def __init__(self, ox, oy, ppf):
        self.ox, self.oy, self.k = ox, oy, ppf

    def p(self, x, y):
        return fitz.Point(self.ox + x * self.k, self.oy - y * self.k)

    def rect(self, x0, y0, x1, y1):
        return fitz.Rect(self.p(x0, y1), self.p(x1, y0))


def polygons(page, view, polys, fill=POCHE, color=INK, width=0.6):
    """Filled polygons (outer boundaries and holes, even-odd)."""
    if not polys:
        return
    sh = page.new_shape()
    for poly in polys:
        pts = [view.p(x, y) for x, y in poly]
        if len(pts) >= 3:
            sh.draw_polyline(pts + [pts[0]])
    sh.finish(color=color, fill=fill, width=width, even_odd=True,
              closePath=True)
    sh.commit()


def line(page, a, b, color=INK, width=0.6, dashes=None):
    sh = page.new_shape()
    sh.draw_line(a, b)
    # open: finish() would close the subpath, retracing the line (a
    # dashed line's way back fills in its gaps)
    sh.finish(color=color, width=width, dashes=dashes, closePath=False)
    sh.commit()


def rect(page, r, color=INK, width=0.6, fill=None):
    sh = page.new_shape()
    sh.draw_rect(r)
    sh.finish(color=color, width=width, fill=fill)
    sh.commit()


def _wall_frame(w, along):
    (ax, ay), (bx, by) = w["a"], w["b"]
    L = math.hypot(bx - ax, by - ay) or 1
    ux, uy = (bx - ax) / L, (by - ay) / L
    return (ax + ux * along, ay + uy * along), (ux, uy), (-uy, ux)


def door(page, view, w, o, into=1):
    """A door in plan: the leaf (a line) and its 90 degree swing - a
    quarter circle drawn as four Bezier arcs, the form the auto takeoff
    already finds. `into` 1/-1: which side of the wall it swings to."""
    (cx, cy), (ux, uy), (nx, ny) = _wall_frame(w, o["along"])
    half = o["width"] / 2
    t = w["thickness"] / 2
    hx, hy = cx - ux * half + nx * t * into, cy - uy * half + ny * t * into
    r = o["width"]
    tip = (hx + nx * r * into, hy + ny * r * into)
    line(page, view.p(hx, hy), view.p(*tip), width=1.0)
    sh = page.new_shape()
    a0 = math.atan2(ny * into, nx * into)
    a1 = math.atan2(uy, ux)
    # sweep from the leaf (normal) to the jamb (along the wall)
    da = (a1 - a0 + math.pi) % (2 * math.pi) - math.pi
    steps = 4
    for i in range(steps):
        t0 = a0 + da * i / steps
        t1 = a0 + da * (i + 1) / steps
        p0 = (hx + r * math.cos(t0), hy + r * math.sin(t0))
        p3 = (hx + r * math.cos(t1), hy + r * math.sin(t1))
        kk = 4 / 3 * math.tan((t1 - t0) / 4)
        p1 = (p0[0] - kk * r * math.sin(t0), p0[1] + kk * r * math.cos(t0))
        p2 = (p3[0] + kk * r * math.sin(t1), p3[1] - kk * r * math.cos(t1))
        sh.draw_bezier(view.p(*p0), view.p(*p1), view.p(*p2), view.p(*p3))
    sh.finish(color=INK, width=0.4, closePath=False)   # no chord
    sh.commit()


def window(page, view, w, o):
    """A window in plan: three parallel lines across the wall."""
    (cx, cy), (ux, uy), (nx, ny) = _wall_frame(w, o["along"])
    half = o["width"] / 2
    t = w["thickness"] / 2
    for f in (-1, 0, 1):
        ax, ay = cx - ux * half + nx * t * f, cy - uy * half + ny * t * f
        bx, by = cx + ux * half + nx * t * f, cy + uy * half + ny * t * f
        line(page, view.p(ax, ay), view.p(bx, by), width=0.5)
    for s in (-1, 1):
        ax, ay = cx + ux * half * s - nx * t, cy + uy * half * s - ny * t
        bx, by = cx + ux * half * s + nx * t, cy + uy * half * s + ny * t
        line(page, view.p(ax, ay), view.p(bx, by), width=0.5)


def overhead(page, view, w, o):
    """An overhead (dock or drive-in) door in plan: the jambs across the
    wall and the door overhead as two dashed lines just inside - the way
    the garage's overhead doors are drawn."""
    (cx, cy), (ux, uy), (nx, ny) = _wall_frame(w, o["along"])
    half = o["width"] / 2
    t = w["thickness"] / 2
    for s in (-1, 1):
        ax, ay = cx + ux * half * s - nx * t, cy + uy * half * s - ny * t
        bx, by = cx + ux * half * s + nx * t, cy + uy * half * s + ny * t
        line(page, view.p(ax, ay), view.p(bx, by), width=0.6)
    for d in (t, t + 1.5):
        ax, ay = cx - ux * half + nx * d, cy - uy * half + ny * d
        bx, by = cx + ux * half + nx * d, cy + uy * half + ny * d
        line(page, view.p(ax, ay), view.p(bx, by), color=GREY, width=0.6,
             dashes="[5 3] 0")


def room_tag(page, view, room, size=11):
    """Name, number and area in US ft2 (from the plan, never Modulor)."""
    x0, y0, x1, y1 = room["rect"]
    c = view.p((x0 + x1) / 2, (y0 + y1) / 2)
    text(page, c.x, c.y - 4, room["name"], size, bold=True, align="center")
    text(page, c.x, c.y + size + 1, room["number"], size - 2,
         align="center")
    text(page, c.x, c.y + 2 * size + 1, f"{room['area']:,.0f} SF",
         size - 2, color=GREY, align="center")


def mark(page, at, label, shape="circle", size=9):
    """A door (circle) or window (hexagon) mark."""
    r = size * 0.95
    sh = page.new_shape()
    if shape == "circle":
        sh.draw_circle(at, r)
    else:
        pts = [fitz.Point(at.x + r * math.cos(math.pi / 3 * i),
                          at.y + r * math.sin(math.pi / 3 * i))
               for i in range(6)]
        sh.draw_polyline(pts + [pts[0]])
    sh.finish(color=INK, fill=(1, 1, 1), width=0.5)
    sh.commit()
    text(page, at.x, at.y + size * 0.35, label, size * 0.8, align="center")


def dim(page, a, b, label, off=24, size=8):
    """A dimension between points a and b (sheet points), offset `off` to
    the left of a->b, with ticks and the text in the middle."""
    dx, dy = b.x - a.x, b.y - a.y
    L = math.hypot(dx, dy) or 1
    nx, ny = -dy / L, dx / L
    a2 = fitz.Point(a.x + nx * off, a.y + ny * off)
    b2 = fitz.Point(b.x + nx * off, b.y + ny * off)
    for p, q in ((a, a2), (b, b2)):
        line(page, fitz.Point(p.x + nx * 3, p.y + ny * 3),
             fitz.Point(q.x + nx * 4, q.y + ny * 4), color=GREY, width=0.3)
    line(page, a2, b2, width=0.4)
    for p in (a2, b2):
        line(page, fitz.Point(p.x - 3, p.y + 3), fitz.Point(p.x + 3,
                                                           p.y - 3),
             width=0.8)
    mid = fitz.Point((a2.x + b2.x) / 2, (a2.y + b2.y) / 2)
    if abs(dy) > abs(dx):                         # vertical: rotated text
        text(page, mid.x - 3, mid.y, label, size, align="center",
             rotate=90)
    else:
        text(page, mid.x, mid.y - 3, label, size, align="center")


def level_line(page, x0, x1, y, label, elev):
    """A level marker: dashed line, a target symbol and 'LABEL / elev'."""
    line(page, fitz.Point(x0, y), fitz.Point(x1, y), color=GREY, width=0.4,
         dashes="[6 3] 0")
    sh = page.new_shape()
    c = fitz.Point(x1 + 10, y)
    sh.draw_circle(c, 5)
    sh.finish(color=INK, width=0.5)
    sh.commit()
    text(page, x1 + 20, y - 2, label, 8, bold=True)
    text(page, x1 + 20, y + 8, fmt_ftin(elev), 8, color=GREY)


def north_arrow(page, at, size=28):
    sh = page.new_shape()
    sh.draw_circle(at, size)
    sh.finish(color=INK, width=0.6)
    tip = fitz.Point(at.x, at.y - size * 0.85)
    l_ = fitz.Point(at.x - size * 0.35, at.y + size * 0.5)
    r_ = fitz.Point(at.x + size * 0.35, at.y + size * 0.5)
    sh.draw_polyline([tip, r_, fitz.Point(at.x, at.y + size * 0.2), l_, tip])
    sh.finish(color=INK, fill=INK, width=0.5)
    sh.commit()
    text(page, at.x, at.y - size - 6, "N", 12, bold=True, align="center")


def title_under(page, x, y, title, scale_label, num="1"):
    """A drawing title: a circled number, the title, the scale."""
    sh = page.new_shape()
    c = fitz.Point(x + 14, y)
    sh.draw_circle(c, 13)
    sh.finish(color=INK, width=0.8)
    sh.commit()
    text(page, c.x, c.y + 4, num, 11, bold=True, align="center")
    text(page, x + 36, y - 1, title.upper(), 14, bold=True)
    line(page, fitz.Point(x + 36, y + 4),
         fitz.Point(x + 36 + text_width(title.upper(), 14, True), y + 4),
         width=1.2)
    text(page, x + 36, y + 18, f"SCALE: {scale_label}", 9, color=GREY)


def table(page, x, y, cols, rows, size=9, row_h=None, head_fill=LIGHT,
          max_y=None):
    """A ruled table: cols [(title, width, align)], rows [[str]]. Returns
    the y below it."""
    row_h = row_h or size * 2.0
    W = sum(c[1] for c in cols)
    rect(page, fitz.Rect(x, y, x + W, y + row_h), fill=head_fill, width=0.6)
    cx = x
    for title, w, align in cols:
        tx = cx + 5 if align == "left" else (cx + w - 5 if align ==
                                              "right" else cx + w / 2)
        text(page, tx, y + row_h * 0.68, title, size, bold=True, align=align)
        cx += w
    yy = y + row_h
    for row in rows:
        if max_y and yy + row_h > max_y:
            text(page, x, yy + row_h * 0.7, "(continued - more rows than "
                 "fit this sheet)", size, color=GREY)
            yy += row_h
            break
        cx = x
        for (title, w, align), val in zip(cols, row):
            tx = cx + 5 if align == "left" else (cx + w - 5 if align ==
                                                  "right" else cx + w / 2)
            text(page, tx, yy + row_h * 0.68, str(val), size, align=align)
            cx += w
        line(page, fitz.Point(x, yy + row_h), fitz.Point(x + W, yy + row_h),
             color=GREY, width=0.3)
        yy += row_h
    cx = x
    for _, w, _ in cols:
        line(page, fitz.Point(cx, y), fitz.Point(cx, yy), color=GREY,
             width=0.3)
        cx += w
    line(page, fitz.Point(cx, y), fitz.Point(cx, yy), color=GREY, width=0.3)
    rect(page, fitz.Rect(x, y, x + W, yy), width=0.8)
    return yy
