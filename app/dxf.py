"""AutoCAD DXF in and out (with the ezdxf library).

Import: a DXF drawing becomes a PDF sheet. Every DXF layer becomes a PDF
layer you can switch off, and the page gets the drawing's true scale, so
takeoff on an imported CAD file is exact from the first click.
Blocks, dimensions and leaders are exploded; curves are drawn as fine
polylines; text keeps its height and angle.

Export: a PDF page (its line work, text, markups and takeoff) to a DXF in
real-world units from the page's scale, with markups and each takeoff
group on their own layers, for the architect or engineer to pick up in
CAD.

DWG files must be saved as DXF first (any CAD program can).
"""
from . import safeio
import logging
import math
import re

import fitz
from .dmoney import c2 as _c2

log = logging.getLogger(__name__)

# $INSUNITS -> feet per unit
_FT_PER = {1: 1 / 12, 2: 1.0, 3: 5280.0, 4: 1 / 304.8, 5: 1 / 30.48,
           6: 3.280839895, 7: 3280.839895, 8: 1 / 12e6, 9: 1 / 12000,
           10: 3.0, 14: 1 / 3.048}
_METRIC = {4, 5, 6, 7, 14}
# architectural (paper inches per foot) and engineering (feet per inch)
ARCH = [12, 6, 3, 1.5, 1, 0.75, 0.5, 0.375, 0.25, 0.1875, 0.125, 0.09375, 0.0625,
        0.03125]
ENG = [10, 20, 30, 40, 50, 60, 100, 200, 300, 400, 500, 1000]
METRIC = [1, 2, 5, 10, 20, 25, 50, 75, 100, 200, 250, 500, 1000, 1250,
          2000, 2500, 5000, 10000]
SHEETS = {"ARCH D (36 x 24)": (2592, 1728), "ARCH E (48 x 36)": (3456, 2592),
          "ARCH C (24 x 18)": (1728, 1296), "Tabloid (17 x 11)": (1224, 792),
          "ISO A1": (2384, 1684), "ISO A0": (3370, 2384)}
UNIT_INSUNITS = {"in": 1, "ft": 2, "mi": 3, "mm": 4, "cm": 5, "m": 6,
                 "km": 7, "yd": 10}


class DXFError(ValueError):
    pass


def available():
    try:
        import ezdxf  # noqa: F401
        return True
    except ImportError:
        return False


def _ezdxf():
    try:
        import ezdxf
        return ezdxf
    except ImportError:
        raise DXFError("DXF support needs the ezdxf package. Run the "
                       "installer again, or: pip install ezdxf")


def _frac(x):
    for n, d in ((1, 32), (3, 32), (1, 16), (3, 16), (1, 8), (3, 8), (1, 4), (1, 2),
                 (3, 4), (3, 2)):
        if abs(x - n / d) < 1e-9:
            return f"{n}/{d}" if n < d else "1-1/2"
    return f"{x:g}"


# ---- import ----------------------------------------------------------------------

def _read(path):
    ezdxf = _ezdxf()
    try:
        return ezdxf.readfile(path)
    except IOError as e:
        raise DXFError(f"Can't open {path}: {e}")
    except ezdxf.DXFStructureError:
        from ezdxf import recover
        try:
            doc, _audit = recover.readfile(path)
            return doc
        except Exception as e:
            raise DXFError(f"This DXF is damaged and couldn't be "
                           f"recovered: {e}")


def _readable(rgb):
    """CAD colours are chosen for a black screen; yellow, cyan and light
    grey vanish on white paper. Keep the hue, darken what's too light."""
    r, g, b = (c / 255 for c in rgb)
    lum = 0.299 * r + 0.587 * g + 0.114 * b
    if lum > 0.92:
        return (0, 0, 0)                           # white -> black
    if lum > 0.45:
        f = 0.45 / lum
        return (r * f, g * f, b * f)
    return (r, g, b)


def _rgb(doc, e):
    from ezdxf import colors
    try:
        if e.dxf.hasattr("true_color"):
            return _readable(colors.int2rgb(e.dxf.true_color))
        aci = e.dxf.get("color", 256)
        if aci in (0, 256):
            layer = doc.layers.get(e.dxf.layer)
            aci = abs(layer.color) if layer else 7
        if aci in (7, 255) or aci <= 0:
            return (0, 0, 0)
        return _readable(colors.aci2rgb(aci))
    except Exception:
        return (0, 0, 0)


_STACK = re.compile(r"\\S([^;#^/]*)[#^/]([^;]*);")


def _plain(e, t):
    """Text without AutoCAD formatting codes: %%u/%%d/%%c/%%p in TEXT,
    and MTEXT formatting, with stacked fractions as 1/2."""
    try:
        if t == "MTEXT":
            from ezdxf.tools.text import plain_mtext
            raw = _STACK.sub(lambda m: f" {m.group(1)}/{m.group(2)}",
                             e.text)
            return plain_mtext(raw).replace("  ", " ").strip()
        from ezdxf.tools.text import plain_text
        return plain_text(e.dxf.text)
    except Exception:
        return e.plain_text() if hasattr(e, "plain_text") else e.dxf.text


def _layer_on(doc, name):
    layer = doc.layers.get(name)
    if layer is None:
        return True
    try:
        return layer.is_on() and not layer.is_frozen()
    except Exception:
        return True


_DASHES = [("PHANTOM", "[10 2 2 2 2 2] 0"), ("DASHDOT", "[6 2 1 2] 0"),
           ("CENTER", "[9 2 2 2] 0"), ("HIDDEN", "[4 2] 0"),
           ("DASHED", "[5 3] 0"), ("DASH", "[5 3] 0"), ("DOT", "[1 2] 0"),
           ("DIVIDE", "[6 2 1 2 1 2] 0"), ("BORDER", "[6 2 6 2 1 2] 0")]


def _style(doc, e, layer):
    """(dash pattern or None, line width in points)."""
    lt = str(e.dxf.get("linetype", "BYLAYER") or "BYLAYER").upper()
    lay = doc.layers.get(layer)
    if lt == "BYLAYER" and lay is not None:
        lt = str(lay.dxf.get("linetype", "CONTINUOUS")).upper()
    dash = None
    for key, pat in _DASHES:
        if key in lt:
            dash = pat
            break
    lw = e.dxf.get("lineweight", -1)
    if lw == -1 and lay is not None:
        lw = lay.dxf.get("lineweight", -3)
    width = max(0.2, lw / 100 * 72 / 25.4) if lw and lw > 0 else 0.4
    return dash, _c2(width)


def _flat(p, tol):
    out = []
    for sub in p.sub_paths():
        pts = [(v.x, v.y) for v in sub.flattening(tol, segments=8)]
        if len(pts) > 1:
            out.append(pts)
    return out


def _collect(doc, entities, out, depth=0, parent=None):
    """Flatten entities into lines, fills and text, exploding blocks.
    Block contents on layer 0 take the layer of the block reference, as in
    AutoCAD. Layers that are off are collected too (and marked)."""
    from ezdxf import path as ezpath
    for e in entities:
        t = e.dxftype()
        layer = e.dxf.get("layer", "0")
        if layer == "0" and parent:
            layer = parent
            try:
                e.dxf.layer = parent
            except Exception:
                logging.getLogger(__name__).debug("ignored error", exc_info=True)
        try:
            if t in ("INSERT", "DIMENSION", "LEADER", "MLEADER",
                     "MULTILEADER", "ARC_DIMENSION", "RADIAL_DIMENSION",
                     "DIAMETRIC_DIMENSION", "ACAD_TABLE", "MINSERT"):
                if depth < 8:
                    _collect(doc, list(e.virtual_entities()), out,
                             depth + 1, layer)
                continue
            color = _rgb(doc, e)
            if t in ("TEXT", "ATTRIB", "MTEXT"):
                text = _plain(e, t)
                if not str(text).strip():
                    continue
                ins = e.dxf.insert
                if t == "MTEXT":
                    ap = int(e.dxf.get("attachment_point", 1))
                    hfrac = (0, 0.5, 1)[(ap - 1) % 3]
                    vfrac = (1, 0.5, 0)[(ap - 1) // 3]
                else:
                    ha = int(e.dxf.get("halign", 0))
                    va = int(e.dxf.get("valign", 0))
                    hfrac = {1: 0.5, 2: 1, 4: 0.5}.get(ha, 0)
                    vfrac = {2: 0.5, 3: 1}.get(va, 0)
                    if (ha or va) and ha not in (3, 5) and \
                            e.dxf.hasattr("align_point"):
                        ins = e.dxf.align_point
                h = e.dxf.get("char_height" if t == "MTEXT" else "height",
                              1.0)
                rot = e.dxf.get("rotation", 0.0)
                if t == "MTEXT" and e.dxf.hasattr("text_direction"):
                    d = e.dxf.text_direction
                    rot = math.degrees(math.atan2(d.y, d.x))
                out["text"].append((layer, (ins.x, ins.y), float(h),
                                    float(rot), str(text), color,
                                    (hfrac, vfrac)))
                continue
            if t in ("POINT", "ATTDEF", "VIEWPORT", "IMAGE", "WIPEOUT",
                     "XLINE", "RAY", "OLE2FRAME", "3DSOLID", "BODY",
                     "REGION", "MESH"):
                continue
            if t == "HATCH":
                loops = []
                for p in ezpath.from_hatch(e):
                    loops += _flat(p, out["tol"])
                if e.dxf.get("solid_fill", 0):
                    if loops:
                        out["fills"].append((layer, loops, color))
                    continue
                n = 0
                try:
                    from ezdxf.render import hatching
                    for ln in hatching.hatch_entity(e):
                        out["lines"].append((layer, [(ln.start.x,
                                                      ln.start.y),
                                                     (ln.end.x, ln.end.y)],
                                             color, None, 0.25))
                        n += 1
                        if n > 20000:
                            break
                except Exception:
                    n = 0
                if not n:
                    for pts in loops:
                        out["lines"].append((layer, pts, color, None, 0.25))
                continue
            if t in ("SOLID", "TRACE", "3DFACE"):
                vs = [e.dxf.get(k) for k in ("vtx0", "vtx1", "vtx3",
                                              "vtx2")]
                pts = [(v.x, v.y) for v in vs if v is not None]
                if t == "3DFACE":
                    out["lines"].append((layer, pts + pts[:1], color, None,
                                         0.4))
                elif len(pts) >= 3:
                    out["fills"].append((layer, [pts], color))
                continue
            dash, width = _style(doc, e, layer)
            for pts in _flat(ezpath.make_path(e), out["tol"]):
                out["lines"].append((layer, pts, color, dash, width))
        except Exception:
            out["skipped"] += 1


def _extents(info, layers=None):
    xs, ys = [], []
    for l, pts, *_ in info["lines"]:
        if layers is None or l in layers:
            xs += [p[0] for p in pts]
            ys += [p[1] for p in pts]
    for l, loops, _c in info["fills"]:
        if layers is None or l in layers:
            for pts in loops:
                xs += [p[0] for p in pts]
                ys += [p[1] for p in pts]
    for l, (x, y), *_ in info["text"]:
        if layers is None or l in layers:
            xs.append(x)
            ys.append(y)
    if not xs:
        return None
    return min(xs), min(ys), max(xs), max(ys)


def pick_scale(w_units, h_units, insunits, sheet=(2592, 1728), margin=72):
    """(points per drawing unit, scale name, ppu, unit) - the largest
    standard scale at which the drawing fits the sheet."""
    avail_w, avail_h = sheet[0] - 2 * margin, sheet[1] - 2 * margin
    metric = insunits in _METRIC
    ft_per = _FT_PER.get(insunits, 1 / 12)   # unitless: assume inches
    if metric:
        m_per_unit = ft_per / 3.280839895
        for n in METRIC:
            k = 72 / 0.0254 / n * m_per_unit     # points per unit
            if w_units * k <= avail_w and h_units * k <= avail_h:
                return k, f"1:{n}", 72 / 0.0254 / n, "m"
        k = min(avail_w / max(w_units, 1e-9), avail_h / max(h_units, 1e-9))
        return k, "fit to sheet", k / m_per_unit, "m"
    for inch_per_ft in ARCH:
        k = 72 * inch_per_ft * ft_per
        if w_units * k <= avail_w and h_units * k <= avail_h:
            return k, f"{_frac(inch_per_ft)}\" = 1'-0\"", 72 * inch_per_ft, \
                "ft"
    for ft_per_in in ENG:
        k = 72 / ft_per_in * ft_per
        if w_units * k <= avail_w and h_units * k <= avail_h:
            return k, f"1\" = {ft_per_in}'", 72 / ft_per_in, "ft"
    k = min(avail_w / max(w_units, 1e-9), avail_h / max(h_units, 1e-9))
    return k, "fit to sheet", k / ft_per, "ft"


def scale_label(k, insunits):
    """A readable name for `k` points per drawing unit, and (ppu, unit)."""
    ft_per = _FT_PER.get(insunits, 1 / 12)
    if insunits in _METRIC:
        ppm = k / (ft_per / 3.280839895)            # points per metre
        n = 72 / 0.0254 / ppm
        return (f"1:{round(n):g}" if abs(n - round(n)) < 0.02 * n
                else f"1:{n:.1f}"), ppm, "m"
    ppf = k / ft_per                               # points per foot
    inch = ppf / 72
    for a in ARCH:
        if abs(inch - a) < 0.005 * a:
            return f"{_frac(a)}\" = 1'-0\"", ppf, "ft"
    fpi = 72 / ppf
    for e in ENG:
        if abs(fpi - e) < 0.005 * e:
            return f"1\" = {e}'", ppf, "ft"
    ratio = 12 / inch                       # real size / paper size
    if ratio < 4:                           # details: 1:2.2 reads better
        return f"1:{ratio:.3g}", ppf, "ft"
    return f"1\" = {fpi:.3g}'", ppf, "ft"


def _clip_seg(a, b, v):
    """Liang-Barsky: the part of segment a-b inside rect v, or None."""
    x0, y0 = a
    dx, dy = b[0] - x0, b[1] - y0
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, x0 - v[0]), (dx, v[2] - x0), (-dy, y0 - v[1]),
                 (dy, v[3] - y0)):
        if p == 0:
            if q < 0:
                return None
            continue
        t = q / p
        if p < 0:
            if t > t1:
                return None
            t0 = max(t0, t)
        else:
            if t < t0:
                return None
            t1 = min(t1, t)
    return ((x0 + t0 * dx, y0 + t0 * dy), (x0 + t1 * dx, y0 + t1 * dy))


def clip_polyline(pts, v):
    """The pieces of a polyline inside rect v = (x0, y0, x1, y1)."""
    out, cur = [], []
    for a, b in zip(pts, pts[1:]):
        c = _clip_seg(a, b, v)
        if c is None:
            if len(cur) > 1:
                out.append(cur)
            cur = []
            continue
        if cur and abs(cur[-1][0] - c[0][0]) < 1e-9 and \
                abs(cur[-1][1] - c[0][1]) < 1e-9:
            cur.append(c[1])
        else:
            if len(cur) > 1:
                out.append(cur)
            cur = [c[0], c[1]]
    if len(cur) > 1:
        out.append(cur)
    return out


def clip_polygon(pts, v):
    """Sutherland-Hodgman: a closed outline cut to rect v."""
    def cut(poly, inside, cross):
        res = []
        for i, cur in enumerate(poly):
            prev = poly[i - 1]
            if inside(cur):
                if not inside(prev):
                    res.append(cross(prev, cur))
                res.append(cur)
            elif inside(prev):
                res.append(cross(prev, cur))
        return res

    def xcross(x):
        return lambda a, b: (x, a[1] + (b[1] - a[1]) * (x - a[0]) /
                             ((b[0] - a[0]) or 1e-12))

    def ycross(y):
        return lambda a, b: (a[0] + (b[0] - a[0]) * (y - a[1]) /
                             ((b[1] - a[1]) or 1e-12), y)
    poly = list(pts)
    for inside, cross in ((lambda p: p[0] >= v[0], xcross(v[0])),
                          (lambda p: p[0] <= v[2], xcross(v[2])),
                          (lambda p: p[1] >= v[1], ycross(v[1])),
                          (lambda p: p[1] <= v[3], ycross(v[3]))):
        if not poly:
            break
        poly = cut(poly, inside, cross)
    return poly


def _draw(page, info, P, k, ocg=None, layers=None, view=None,
          min_text=0.25):
    """Draw collected geometry on `page`. P maps drawing -> page points;
    `layers` limits which layers; `view` (x0, y0, x1, y1) clips to that
    rectangle (drawing units), as a viewport does."""
    def visible(pts):
        if view is None:
            return True
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        return not (max(xs) < view[0] or min(xs) > view[2] or
                    max(ys) < view[1] or min(ys) > view[3])

    def inside(pts):
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        return min(xs) >= view[0] and max(xs) <= view[2] and \
            min(ys) >= view[1] and max(ys) <= view[3]
    groups = {}
    for layer, pts, color, dash, width in info["lines"]:
        if layers is not None and layer not in layers:
            continue
        if not visible(pts):
            continue
        pieces = [pts] if view is None or inside(pts) else \
            clip_polyline(pts, view)
        for piece in pieces:
            groups.setdefault((layer, color, dash, width), []).append(piece)
    for (layer, color, dash, width), polys in groups.items():
        shape = page.new_shape()
        for pts in polys:
            shape.draw_polyline([P(*p) for p in pts])
        shape.finish(color=color, width=width, dashes=dash, closePath=False,
                     oc=(ocg or {}).get(layer, 0))
        shape.commit()
    for layer, loops, color in info["fills"]:
        if layers is not None and layer not in layers:
            continue
        if not any(visible(pts) for pts in loops):
            continue
        if view is not None:
            loops = [lp if inside(lp) else clip_polygon(lp, view)
                     for lp in loops]
            loops = [lp for lp in loops if len(lp) >= 3]
            if not loops:
                continue
        shape = page.new_shape()
        for pts in loops:
            shape.draw_polyline([P(*p) for p in pts] + [P(*pts[0])])
        shape.finish(color=None, fill=color, even_odd=True,
                     oc=(ocg or {}).get(layer, 0))
        shape.commit()
    for layer, (x, y), h, rot, text, color, (hf, vf) in info["text"]:
        if layers is not None and layer not in layers:
            continue
        size = h * k
        if size < min_text or (view is not None and not inside([(x, y)])):
            continue
        lines = text.splitlines() or [text]
        block = (len(lines) - 1) * size * 1.25
        for i, line in enumerate(lines):
            pt = P(x, y)
            m = fitz.Matrix(-rot)
            w = fitz.get_text_length(line, "helv", size) if hf else 0
            off = fitz.Point(-w * hf, i * size * 1.25 + vf * size -
                             (block * (1 - vf) if vf < 1 else 0)) * m
            try:
                page.insert_text(pt + off, line, fontsize=size,
                                 color=color, morph=(pt + off, m),
                                 oc=(ocg or {}).get(layer, 0))
            except Exception:
                info["skipped"] += 1


def _units(doc):
    insunits = int(doc.header.get("$INSUNITS", 0) or 0)
    if not insunits:
        insunits = 4 if int(doc.header.get("$MEASUREMENT", 0) or 0) else 1
    return insunits


def _gather(doc, space):
    try:
        ext = (doc.header.get("$EXTMIN"), doc.header.get("$EXTMAX"))
        tol = max(1e-6, (abs(ext[1][0] - ext[0][0]) +
                         abs(ext[1][1] - ext[0][1])) / 6000)
        if not tol < 1e9:
            tol = 0.01
    except Exception:
        tol = 0.01
    info = {"lines": [], "fills": [], "text": [], "skipped": 0, "tol": tol}
    _collect(doc, space, info)
    return info


def _viewports(lay):
    """The viewports of a layout that show the model in plan view. The
    first viewport of a layout is the sheet itself (id 1) and is skipped.
    Layouts that weren't the active one store status 0 for every
    viewport, so 0 isn't taken to mean "off" there."""
    all_vp = [e for e in lay if e.dxftype() == "VIEWPORT"]
    out = []
    for i, e in enumerate(all_vp):
        vid = int(e.dxf.get("id", 0) or 0)
        if vid == 1 or (vid == 0 and i == 0):
            continue
        if vid > 1 and int(e.dxf.get("status", 1)) == 0:
            continue                               # really switched off
        if e.dxf.get("view_height", 0) <= 0:
            continue
        d = e.dxf.get("view_direction_vector")
        if d is not None and (abs(d.x) > 1e-9 or abs(d.y) > 1e-9):
            continue                               # 3D / isometric view
        out.append(e)
    return out


def _mostly_off(doc, info):
    """True when the layers that are on hold under a fifth of the
    drawing - files saved with nearly everything switched off (some
    converters do this) - so importing as-is would look empty."""
    total = on = 0
    for key in ("lines", "fills", "text"):
        for x in info[key]:
            total += 1
            on += _layer_on(doc, x[0])
    return total > 0 and on < 0.2 * total


def layouts(path):
    """[(layout name, number of viewports)] of the DXF's paper space
    sheets, in tab order."""
    doc = _read(path)
    out = []
    for name in doc.layouts.names_in_taborder():
        if name.lower() == "model":
            continue
        lay = doc.layouts.get(name)
        vps = _viewports(lay)
        if len(lay):
            out.append((name, len(vps)))
    return out


def to_pdf(path, out_path, sheet="ARCH D (36 x 24)", what="model",
           names=None):
    """Draw a DXF as PDF and save it to `out_path`.

    what="model": model space on one sheet at the largest standard scale
    that fits, each DXF layer a PDF layer (layers that were off in the
    drawing come in switched off).
    what="layouts": each paper space layout (`names`, default all) as its
    own page, as plotted: title block plus every viewport at its scale,
    each viewport registered as a QuantiSheet viewport for takeoff.
    Returns a summary dict."""
    doc = _read(path)
    if what == "layouts":
        return _layouts_pdf(doc, path, out_path, names)
    from . import annotate
    insunits = _units(doc)
    info = _gather(doc, doc.modelspace())
    all_layers = sorted({x[0] for x in info["lines"]} |
                        {x[0] for x in info["fills"]} |
                        {x[0] for x in info["text"]})
    turned_on = _mostly_off(doc, info)
    on = set(all_layers) if turned_on else \
        {l for l in all_layers if _layer_on(doc, l)}
    # fit everything, so layers switched on later aren't off the sheet
    ext = _extents(info)
    if ext is None:
        raise DXFError("The DXF has no drawing in model space.")
    x0, y0, x1, y1 = ext
    W, H = SHEETS.get(sheet, SHEETS["ARCH D (36 x 24)"])
    if (y1 - y0) > (x1 - x0) * 1.15:
        W, H = H, W                                   # portrait drawing
    k, name, ppu, unit = pick_scale(x1 - x0, y1 - y0, insunits, (W, H))
    ox = (W - (x1 - x0) * k) / 2
    oy = (H - (y1 - y0) * k) / 2

    def P(x, y):
        return fitz.Point(ox + (x - x0) * k, H - oy - (y - y0) * k)

    out = fitz.open()
    page = out.new_page(width=W, height=H)
    ocg = {l: out.add_ocg(l, on=l in on) for l in all_layers}
    _draw(page, info, P, k, ocg)
    out.set_metadata({"title": path.replace("\\", "/").split("/")[-1],
                      "creator": "QuantiSheet (DXF import)"})
    annotate.apply_op(out, annotate.new_op("set_scale", 0, ppu=ppu,
                                           unit=unit, name=name))
    safeio.atomic_save(out, out_path, garbage=3, deflate=True)
    out.close()
    return {"scale": name, "layers": len(all_layers),
            "layers_off": len(all_layers) - len(on), "turned_on": turned_on,
            "entities": len(info["lines"]) + len(info["fills"]) +
            len(info["text"]),
            "skipped": info["skipped"], "sheet": sheet, "pages": 1}


def _layouts_pdf(doc, path, out_path, names=None):
    from . import annotate
    insunits = _units(doc)
    model = _gather(doc, doc.modelspace())
    mlayers = ({x[0] for x in model["lines"]} | {x[0] for x in model["fills"]}
               | {x[0] for x in model["text"]})
    on = {l for l in mlayers if _layer_on(doc, l)}
    turned_on = _mostly_off(doc, model)
    out = fitz.open()
    ocg = {}

    def ocg_for(names):
        for n in names:
            if n not in ocg:
                ocg[n] = out.add_ocg(n, on=turned_on or _layer_on(doc, n))
        return ocg
    summary = {"pages": 0, "viewports": 0, "skipped": 0, "scales": [],
               "sheet": "as plotted", "layers": 0, "layers_off": 0}
    for lname in doc.layouts.names_in_taborder():
        if lname.lower() == "model" or (names and lname not in names):
            continue
        lay = doc.layouts.get(lname)
        if not len(lay):
            continue
        dl = lay.dxf_layout.dxf
        mm = int(dl.get("plot_paper_units", 0)) == 1
        ptpp = 72 / 25.4 if mm else 72.0            # points per paper unit
        paper = _gather(doc, [e for e in lay if e.dxftype() != "VIEWPORT"])
        vps = _viewports(lay)
        boxes = []
        for vp in vps:
            c, w, h = vp.dxf.center, vp.dxf.width, vp.dxf.height
            boxes.append((c.x - w / 2, c.y - h / 2, c.x + w / 2, c.y + h / 2))
        ext = _extents(paper, {l for l in ({x[0] for x in paper["lines"]} |
                                           {x[0] for x in paper["text"]} |
                                           {x[0] for x in paper["fills"]})
                               if _layer_on(doc, l)}) or _extents(paper)
        xs = [b[0] for b in boxes] + [b[2] for b in boxes]
        ys = [b[1] for b in boxes] + [b[3] for b in boxes]
        if ext:
            xs += [ext[0], ext[2]]
            ys += [ext[1], ext[3]]
        if not xs:
            continue
        x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
        m = 18
        W = (x1 - x0) * ptpp + 2 * m
        H = (y1 - y0) * ptpp + 2 * m
        if W > 14400 or H > 14400:                 # odd paper units
            ptpp = min(14000 / max(x1 - x0, 1e-9), 14000 / max(y1 - y0,
                                                              1e-9))
            W = (x1 - x0) * ptpp + 2 * m
            H = (y1 - y0) * ptpp + 2 * m

        def P(x, y, x0=x0, y1=y1, ptpp=ptpp):
            return fitz.Point(m + (x - x0) * ptpp, m + (y1 - y) * ptpp)

        page = out.new_page(width=W, height=H)
        pno = out.page_count - 1
        biggest = None
        for i, vp in enumerate(vps):
            c, w, h = vp.dxf.center, vp.dxf.width, vp.dxf.height
            vh = vp.dxf.view_height
            vc = vp.dxf.get("view_center_point")
            tgt = vp.dxf.get("view_target_point")
            mx = vc.x + (tgt.x if tgt else 0)
            my = vc.y + (tgt.y if tgt else 0)
            s = h / vh                              # paper per model unit
            k = s * ptpp                            # points per model unit
            view = (mx - w / s / 2, my - vh / 2, mx + w / s / 2, my + vh / 2)
            r = fitz.Rect(P(c.x - w / 2, c.y + h / 2),
                          P(c.x + w / 2, c.y - h / 2))
            try:
                frozen = set(vp.frozen_layers or [])
            except Exception:
                frozen = set()

            def PM(x, y, view=view, k=k, r=r):
                return fitz.Point(r.x0 + (x - view[0]) * k,
                                  r.y0 + (view[3] - y) * k)
            # every layer comes in; the ones that are off (or frozen in
            # this viewport) start switched off
            _draw(page, model, PM, k, ocg_for(mlayers),
                  layers=mlayers - frozen, view=view)
            label, ppu, unit = scale_label(k, insunits)
            summary["scales"].append(label)
            annotate.apply_op(out, annotate.new_op(
                "set_scale", pno, viewport={
                    "name": f"Viewport {i + 1}", "rect": list(r),
                    "ppu": ppu, "unit": unit, "label": label}))
            if biggest is None or r.get_area() > biggest[0]:
                biggest = (r.get_area(), ppu, unit, label)
        players = ({x[0] for x in paper["lines"]} |
                   {x[0] for x in paper["text"]} |
                   {x[0] for x in paper["fills"]})
        _draw(page, paper, P, ptpp, ocg_for(players))
        if biggest:
            annotate.apply_op(out, annotate.new_op(
                "set_scale", pno, ppu=biggest[1], unit=biggest[2],
                name=biggest[3]))
        summary["skipped"] += paper["skipped"]
        summary["viewports"] += len(vps)
        summary["pages"] += 1
    if not out.page_count:
        out.close()
        raise DXFError("This DXF has no paper space sheets. Import the "
                       "model space instead.")
    summary["skipped"] += model["skipped"]
    summary["layers"] = len(ocg)
    summary["layers_off"] = 0 if turned_on else \
        sum(1 for n in ocg if not _layer_on(doc, n))
    summary["turned_on"] = turned_on
    summary["scale"] = ", ".join(sorted(set(summary["scales"]))) or \
        "no viewports"
    out.set_metadata({"title": path.replace("\\", "/").split("/")[-1],
                      "creator": "QuantiSheet (DXF import)"})
    toc = [[1, n, i + 1] for i, n in enumerate(
        [n for n in doc.layouts.names_in_taborder() if n.lower() != "model"
         and (not names or n in names) and len(doc.layouts.get(n))])]
    if len(toc) == out.page_count:
        out.set_toc(toc)
    safeio.atomic_save(out, out_path, garbage=3, deflate=True)
    out.close()
    return summary


# ---- export ------------------------------------------------------------------------

def _bezier(p0, p1, p2, p3, n=8):
    out = []
    for i in range(1, n + 1):
        t = i / n
        a = (1 - t) ** 3
        b = 3 * (1 - t) ** 2 * t
        c = 3 * (1 - t) * t * t
        d = t ** 3
        out.append((a * p0.x + b * p1.x + c * p2.x + d * p3.x,
                    a * p0.y + b * p1.y + c * p2.y + d * p3.y))
    return out


def _safe_layer(name):
    bad = '<>/\\":;?*|=`,'
    s = "".join("_" if c in bad else c for c in str(name)).strip()
    return s[:250] or "0"


def from_page(pdf, pno, path, drawing=True, text=True, markups=True):
    """Write page `pno` to a DXF at `path`. Returns {"units", "entities"}."""
    from . import annotate
    ezdxf = _ezdxf()
    from ezdxf import colors
    page = pdf[pno]
    sc = annotate.read_scales(pdf).get(pno)
    if sc and sc.get("ppu"):
        unit = sc.get("unit", "ft")
        per = 1 / float(sc["ppu"])               # drawing units per point
        insunits = UNIT_INSUNITS.get(unit, 0)
    else:
        unit, per, insunits = "in", 1 / 72, 1    # paper inches
    rot = page.rotation_matrix
    H = page.rect.height                         # page as displayed

    def P(pt):
        q = fitz.Point(pt) * rot
        return (q.x * per, (H - q.y) * per)

    doc = ezdxf.new("R2010", setup=True)
    doc.header["$INSUNITS"] = insunits
    doc.header["$MEASUREMENT"] = 1 if unit in ("m", "mm", "cm", "km") else 0
    msp = doc.modelspace()
    count = 0

    def layer(name, aci=7):
        name = _safe_layer(name)
        if name not in doc.layers:
            doc.layers.add(name, color=aci)
        return name

    def tc(c):
        if not c:
            return None
        return colors.rgb2int(tuple(int(max(0, min(1, v)) * 255)
                                    for v in c[:3]))

    if drawing:
        lay = layer("PDF-Drawing")
        for d in page.get_drawings():
            attr = {"layer": lay}
            col = tc(d.get("color") or d.get("fill"))
            if col is not None and col != 0:
                attr["true_color"] = col
            for it in d.get("items", ()):
                op = it[0]
                if op == "l":
                    msp.add_line(P(it[1]), P(it[2]), dxfattribs=attr)
                elif op == "c":
                    pts = [P(it[1])] + [P(fitz.Point(x, y)) for x, y in
                                        _bezier(*[fitz.Point(v) for v in
                                                  it[1:5]])]
                    msp.add_lwpolyline(pts, dxfattribs=attr)
                elif op == "re":
                    r = fitz.Rect(it[1])
                    msp.add_lwpolyline([P(r.tl), P(r.tr), P(r.br), P(r.bl)],
                                       close=True, dxfattribs=attr)
                elif op == "qu":
                    q = fitz.Quad(it[1])
                    msp.add_lwpolyline([P(q.ul), P(q.ur), P(q.lr), P(q.ll)],
                                       close=True, dxfattribs=attr)
                else:
                    continue
                count += 1
    if text:
        lay = layer("PDF-Text")
        for b in page.get_text("dict").get("blocks", []):
            for line in b.get("lines", []):
                dx, dy = line.get("dir", (1, 0))
                # direction as displayed (rotation applied)
                dvec = fitz.Point(dx, dy) * rot - fitz.Point(0, 0) * rot
                angle = math.degrees(math.atan2(-dvec.y, dvec.x))
                for span in line.get("spans", []):
                    s = span.get("text", "").strip()
                    if not s:
                        continue
                    h = span["size"] * 0.7 * per        # cap height
                    msp.add_text(s, height=h, rotation=angle,
                                 dxfattribs={"layer": lay}).set_placement(
                        P(span["origin"]))
                    count += 1
    if markups:
        for a in annotate.iter_annots(page):
            info = a.info or {}
            subj = info.get("subject", "")
            if annotate.is_hatch(pdf, a):
                continue
            if subj.startswith(annotate.TAKEOFF + ":"):
                parts = (subj.split(":") + [""] * 6)
                lay = layer(f"Takeoff-{parts[4] or parts[1]}", 1)
            else:
                lay = layer(f"Markups-{subj or a.type[1]}", 3)
            col = tc((a.colors or {}).get("stroke"))
            attr = {"layer": lay}
            if col:
                attr["true_color"] = col
            t = a.type[0]
            verts = a.vertices or []
            try:
                if t in (fitz.PDF_ANNOT_POLYGON, fitz.PDF_ANNOT_POLY_LINE,
                         fitz.PDF_ANNOT_LINE) and verts:
                    msp.add_lwpolyline([P(v) for v in verts],
                                       close=t == fitz.PDF_ANNOT_POLYGON,
                                       dxfattribs=attr)
                elif t == fitz.PDF_ANNOT_INK and verts:
                    for stroke in verts:
                        msp.add_lwpolyline([P(v) for v in stroke],
                                           dxfattribs=attr)
                elif t == fitz.PDF_ANNOT_FREE_TEXT:
                    r = fitz.Rect(a.rect)          # unrotated, like verts
                    s = info.get("content", "")
                    if s:
                        m = msp.add_mtext(s, dxfattribs=attr)
                        m.dxf.char_height = max(r.height / 3, 6) * per
                        m.set_location(P(r.tl))
                elif t in (fitz.PDF_ANNOT_SQUARE, fitz.PDF_ANNOT_CIRCLE,
                           fitz.PDF_ANNOT_TEXT, fitz.PDF_ANNOT_STAMP):
                    r = fitz.Rect(a.rect)
                    if t == fitz.PDF_ANNOT_CIRCLE:
                        c = P((r.tl + r.br) / 2)
                        msp.add_ellipse(
                            c, major_axis=(r.width / 2 * per, 0),
                            ratio=max(0.01, min(1, r.height /
                                                max(r.width, 1e-6))),
                            dxfattribs=attr)
                    else:
                        msp.add_lwpolyline([P(r.tl), P(r.tr), P(r.br),
                                            P(r.bl)], close=True,
                                           dxfattribs=attr)
                    if info.get("content"):
                        msp.add_text(info["content"][:250],
                                     height=8 * per,
                                     dxfattribs=attr).set_placement(
                            P(r.bl))
                else:
                    continue
                count += 1
            except Exception:
                log.warning("skipped a markup in DXF export", exc_info=True)
    doc.saveas(path)
    return {"units": unit, "entities": count}
