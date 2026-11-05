"""The generated floor plan as an AutoCAD DXF (feet), so an architect can
pick it up in CAD instead of retyping it (Venice, Oct 19: "the generator
becomes a starting point rather than a dead end").

Layers follow the US National CAD Standard names:
    A-WALL        wall outlines (Modulor's footprints, openings cut)
    A-DOOR        door leaves and swings
    A-GLAZ        windows
    A-AREA-IDEN   room name, number and area
    A-ANNO-NOTE   the FOR REVIEW - NOT FOR SEALING note
    C-PROP        the property line (from the brief, or assumed)
    C-PROP-SBCK   the setback lines (dashed)
    A-FLOR-OTLN   a porch or deck outline
Coordinates are plan feet: x east, y north, (0, 0) at the south-west
corner of the wall centrelines - the same numbers as the .genset.json."""
import math

from . import DISCLAIMER

LAYERS = {"A-WALL": 7, "A-DOOR": 2, "A-GLAZ": 4, "A-AREA-IDEN": 3,
          "A-ANNO-NOTE": 1, "C-PROP": 6, "C-PROP-SBCK": 8,
          "A-FLOR-OTLN": 5}


def _frame(w, along):
    (ax, ay), (bx, by) = w["a"], w["b"]
    L = math.hypot(bx - ax, by - ay) or 1
    ux, uy = (bx - ax) / L, (by - ay) / L
    return (ax + ux * along, ay + uy * along), (ux, uy), (-uy, ux)


def write(plan, model, path):
    """Write the plan to `path` (.dxf). `model` is the kernel_modulor
    Model the set was drawn from. Returns the path."""
    import ezdxf
    from ezdxf import units
    from ezdxf.enums import TextEntityAlignment
    from .views import _into, _wall
    doc = ezdxf.new("R2010", setup=True)
    doc.units = units.FT
    doc.header["$INSUNITS"] = 2                         # feet
    doc.header["$MEASUREMENT"] = 0                      # imperial
    for name, color in LAYERS.items():
        doc.layers.add(name, color=color)
    msp = doc.modelspace()
    from .model import levels
    models = model if isinstance(model, (list, tuple)) else [model]
    W = plan["footprint"]["width"]
    for i, (lp, mi) in enumerate(zip(levels(plan), models)):
        # level 2 sits beside level 1, 30 ft to the east
        dx = i * (W + 30.0)
        if len(models) > 1:
            msp.add_text(f"LEVEL {i + 1}", height=1.5,
                         dxfattribs={"layer": "A-ANNO-NOTE"}
                         ).set_placement((dx, plan["footprint"]["depth"]
                                          + 4))
        # walls: Modulor's outlines, exactly what the PDF plan shows
        for poly in mi.plan_outline():
            if len(poly) >= 3:
                msp.add_lwpolyline([(x + dx, y) for x, y in poly], close=True,
                                   dxfattribs={"layer": "A-WALL"})
        for o in lp["openings"]:
            w = _wall(lp, o["wall"])
            (cx, cy), (ux, uy), (nx, ny) = _frame(w, o["along"])
            cx += dx
            half, t = o["width"] / 2, w["thickness"] / 2
            if o["kind"] == "door":
                into = _into(lp, w, o)
                hx = cx - ux * half + nx * t * into
                hy = cy - uy * half + ny * t * into
                r = o["width"]
                tip = (hx + nx * r * into, hy + ny * r * into)
                msp.add_line((hx, hy), tip, dxfattribs={"layer": "A-DOOR"})
                a0 = math.degrees(math.atan2(ny * into, nx * into))
                a1 = math.degrees(math.atan2(uy, ux))
                d = (a1 - a0 + 180) % 360 - 180
                start, end = (a0, a1) if d > 0 else (a1, a0)
                msp.add_arc((hx, hy), r, start, end,
                            dxfattribs={"layer": "A-DOOR"})
            elif o["kind"] == "overhead":        # dashed, as the garage's
                ox, oy = nx * (t + 1.5), ny * (t + 1.5)
                msp.add_line((cx - ux * half + ox, cy - uy * half + oy),
                             (cx + ux * half + ox, cy + uy * half + oy),
                             dxfattribs={"layer": "A-DOOR",
                                         "linetype": "DASHED"})
            else:
                for k in (-1.0, 0.0, 1.0):
                    ox, oy = nx * t * k, ny * t * k
                    msp.add_line((cx - ux * half + ox, cy - uy * half + oy),
                                 (cx + ux * half + ox, cy + uy * half + oy),
                                 dxfattribs={"layer": "A-GLAZ"})
        for r in lp["rooms"]:
            x0, y0, x1, y1 = r["rect"]
            mx, my = (x0 + x1) / 2 + dx, (y0 + y1) / 2
            h = 0.6 if min(x1 - x0, y1 - y0) >= 8 else 0.4
            for k, txt in enumerate((r["name"], r["number"],
                                     f"{r['area']:,.0f} SF")):
                msp.add_text(txt, height=h if k == 0 else h * 0.8,
                             dxfattribs={"layer": "A-AREA-IDEN"}
                             ).set_placement((mx, my + h * (1.2 - 1.4 * k)),
                                             align=TextEntityAlignment.MIDDLE_CENTER)
    g = plan.get("garage")
    if g:                       # the garage's own walls and overhead doors
        from .garage import walls as gwalls
        for x0, y0, x1, y1 in gwalls(g):
            msp.add_lwpolyline([(x0, y0), (x1, y0), (x1, y1), (x0, y1)],
                               close=True, dxfattribs={"layer": "A-WALL"})
        for a, b in g["overhead"]:
            msp.add_line((a, g["rect"][1] + 1.5), (b, g["rect"][1] + 1.5),
                         dxfattribs={"layer": "A-DOOR",
                                     "linetype": "DASHED"})
        gx0, gy0, gx1, gy1 = g["rect"]
        msp.add_text(g["name"], height=0.6,
                     dxfattribs={"layer": "A-AREA-IDEN"}).set_placement(
            ((gx0 + gx1) / 2, (gy0 + gy1) / 2),
            align=TextEntityAlignment.MIDDLE_CENTER)
    for key in ("porch", "deck"):           # outlines on A-FLOR-OTLN
        it = plan.get(key)
        if it:
            x0, y0, x1, y1 = it["rect"]
            msp.add_lwpolyline([(x0, y0), (x1, y0), (x1, y1), (x0, y1)],
                               close=True,
                               dxfattribs={"layer": "A-FLOR-OTLN"})
            msp.add_text(it["name"], height=0.5,
                         dxfattribs={"layer": "A-AREA-IDEN"}
                         ).set_placement(((x0 + x1) / 2, (y0 + y1) / 2),
                                         align=TextEntityAlignment.MIDDLE_CENTER)
    s = plan.get("site")
    if s:                       # property line and setbacks (assumed or not)
        x0, y0 = s["lot_x0"], s["lot_y0"]
        x1, y1 = x0 + s["lot_w"], y0 + s["lot_d"]
        msp.add_lwpolyline([(x0, y0), (x1, y0), (x1, y1), (x0, y1)],
                           close=True, dxfattribs={"layer": "C-PROP"})
        sb = s["setbacks"]
        ex0, ey0 = x0 + sb["side"], y0 + sb["front"]
        ex1, ey1 = x1 - sb["side"], y1 - sb["rear"]
        if ex1 > ex0 and ey1 > ey0:
            msp.add_lwpolyline([(ex0, ey0), (ex1, ey0), (ex1, ey1),
                                (ex0, ey1)], close=True,
                               dxfattribs={"layer": "C-PROP-SBCK",
                                           "linetype": "DASHED"})
    msp.add_text(DISCLAIMER, height=1.0,
                 dxfattribs={"layer": "A-ANNO-NOTE"}).set_placement(
        (0, -6))
    msp.add_text(f"{plan['project'].get('name') or ''} - generated by "
                 "QuantiSheet; verify everything", height=0.6,
                 dxfattribs={"layer": "A-ANNO-NOTE"}).set_placement((0, -8))
    doc.saveas(path)
    return path
