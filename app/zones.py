"""AI Takeoff zones (Nov 1): boxes you draw on a sheet to say where AI
Takeoff's results count.

- "Only here" (include, green dashed): with one or more on a sheet, only
  what AI Takeoff finds inside them is added - one wing, one phase, the
  plan without its enlarged details.
- "Leave out" (exclude, red dashed): what it finds inside is not added - a
  title block, legend or schedule it took for plan, an area by others.

A zone is an ordinary rectangle markup (it saves with the PDF, moves and
deletes like any markup). Zones decide which finished results are kept -
by where each one sits (an outline's middle, a count's spot, a line's
middle) - and never change how anything is measured: the room, wall and
count engines run exactly as before, and a room is kept or left out
whole, never cut at a zone's edge.
"""
import fitz

from . import annotate

COLORS = {"include": (0.0, 0.55, 0.0), "exclude": (0.85, 0.0, 0.0)}
NOTES = {"include": "AI Takeoff zone: only here",
         "exclude": "AI Takeoff zone: leave out"}
NAMES = {"include": "Only Here", "exclude": "Leave Out"}


def mark(page, rect, kind):
    """The op (page, "add_rect", payload) for a zone box."""
    if kind not in COLORS:
        raise ValueError(kind)
    return (page, "add_rect", {"rect": list(fitz.Rect(rect).normalize()),
                               "zone": kind, "color": list(COLORS[kind]),
                               "dashes": [6, 4], "width": 1.5,
                               "note": NOTES[kind]})


def on_page(doc, page):
    """{"include": [Rect], "exclude": [Rect]} for page `page`."""
    out = {"include": [], "exclude": []}
    try:
        pg = doc[page]
    except (IndexError, ValueError):
        return out
    for a in annotate.iter_annots(pg):
        z = annotate.zone_of(doc, a)
        if z:
            out[z].append(fitz.Rect(a.rect))
    return out


def refs_on_page(doc, page):
    return [annotate.ref(a) for a in annotate.iter_annots(doc[page])
            if annotate.zone_of(doc, a)]


def any_zones(doc):
    return {p: z for p in range(doc.page_count)
            for z in [on_page(doc, p)] if z["include"] or z["exclude"]}


def _spot(kind, payload):
    """Where a result sits: an outline's / line's middle, a count's point."""
    pl = payload or {}
    pts = pl.get("pts")
    if pts:
        try:
            xs = [float(p[0]) for p in pts]
            ys = [float(p[1]) for p in pts]
        except (TypeError, ValueError, IndexError):
            return None
        if kind in ("add_polygon",) and len(pts) >= 3:
            # the area's centroid (the middle of an L-shape can be outside;
            # then the point on the outline nearest the vertex mean)
            a = cx = cy = 0.0
            n = len(xs)
            for i in range(n):
                j = (i + 1) % n
                c = xs[i] * ys[j] - xs[j] * ys[i]
                a += c
                cx += (xs[i] + xs[j]) * c
                cy += (ys[i] + ys[j]) * c
            if abs(a) > 1e-9:
                return fitz.Point(cx / (3 * a), cy / (3 * a))
        if len(pts) == 2 or kind in ("add_line", "add_polyline"):
            k = len(pts) // 2
            if len(pts) % 2:
                return fitz.Point(xs[k], ys[k])
            return fitz.Point((xs[k - 1] + xs[k]) / 2, (ys[k - 1] + ys[k]) / 2)
        return fitz.Point(sum(xs) / len(xs), sum(ys) / len(ys))
    if pl.get("pt"):
        try:
            return fitz.Point(float(pl["pt"][0]), float(pl["pt"][1]))
        except (TypeError, ValueError, IndexError):
            return None
    if pl.get("rect"):
        try:
            r = fitz.Rect(pl["rect"])
        except (TypeError, ValueError):
            return None
        return fitz.Point((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2)
    return None


def keeps(z, pt):
    """True when a result at `pt` counts under the zones `z` (on_page)."""
    if pt is None:
        return True
    if z["include"] and not any(r.contains(pt) for r in z["include"]):
        return False
    return not any(r.contains(pt) for r in z["exclude"])


def filter_marks(doc, marks):
    """AI Takeoff's marks [(page, kind, payload)] with those the zones leave
    out removed. Scales and other marks without a place are kept.
    Returns (kept, dropped)."""
    cache = {}
    kept, dropped = [], []
    for m in marks:
        page, kind, pl = m
        if kind == "set_scale" or not isinstance(page, int):
            kept.append(m)
            continue
        if page not in cache:
            cache[page] = on_page(doc, page)
        z = cache[page]
        if not z["include"] and not z["exclude"]:
            kept.append(m)
            continue
        (kept if keeps(z, _spot(kind, pl)) else dropped).append(m)
    return kept, dropped


def filter_result(doc, res, dropped):
    """The run's CHECK items that go with dropped outlines (same page and
    name), or that sit outside the zones themselves, are taken out of the
    review list too. Returns how many."""
    if not res:
        return 0
    gone = set()
    for page, _k, pl in dropped:
        g = ((pl or {}).get("measure") or {}).get("group")
        if g:
            gone.add((page, g))
    keep, n = [], 0
    cache = {}
    for x in res.get("review") or ():
        p = x.get("page")
        out = (p, x.get("name")) in gone
        if not out and isinstance(p, int) and x.get("rect"):
            if p not in cache:
                cache[p] = on_page(doc, p)
            try:
                r = fitz.Rect(x["rect"])
                out = not keeps(cache[p], fitz.Point((r.x0 + r.x1) / 2,
                                                     (r.y0 + r.y1) / 2))
            except (TypeError, ValueError):
                out = False
        if out:
            n += 1
        else:
            keep.append(x)
    if n:
        res["review"] = keep
    return n
