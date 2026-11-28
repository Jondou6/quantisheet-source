"""Takeoff marks made in the browser add-on's viewer (Nov 27, option B of
"view and mark up in the browser").

The add-on's viewer lets someone set a scale and click out lengths, areas
and counts on a PDF. It does NOT write quantities into the PDF. It sends
where the clicks were (and the scale that was set) beside the PDF, and
QuantiSheet works the quantities out here, with the same code its own
takeoff tools use. So there is one place a quantity comes from.

    <saved file>.pdf            the PDF (app/browserhost.py)
    <saved file>.pdf.qsweb.json the marks, removed once they are in

The file is JSON written by the browser, so nothing in it is trusted:
every number is checked, pages must exist, and the amounts are capped.

    {"v": 1,
     "scales": [{"page": 0, "ppu": 18.0, "unit": "ft", "name": "1/4\\" = 1'-0\\"",
                 "all": false}],
     "marks":  [{"page": 0, "type": "length", "pts": [[x, y], ...],
                 "group": "Walls"},
                {"page": 0, "type": "area", "pts": [...], "group": ""},
                {"page": 0, "type": "count", "pts": [[x, y]], "group": "Doors"}]}

Points are in the PDF's own coordinates (as the browser viewer reports
them); `ppu` is PDF points per unit.
"""
import json
import logging
import math
import os

from . import annotate, takeoff

log = logging.getLogger(__name__)

SUFFIX = ".qsweb.json"
METHOD = "browser viewer"
MAX_BYTES = 4 * 1024 * 1024
MAX_MARKS = 5000
MAX_POINTS = 2000
UNITS = tuple(takeoff.UNITS)
COLORS = {"length": [0.85, 0.1, 0.1], "area": [0.1, 0.45, 0.85],
          "count": [0.9, 0.5, 0.0]}


def sidecar(path):
    return path + SUFFIX


def clean(data):
    """The marks file as plain, checked values (or None when it isn't
    one). Bad entries are dropped, never repaired."""
    if not isinstance(data, dict) or data.get("v") != 1:
        return None
    out = {"v": 1, "scales": [], "marks": []}
    for s in (data.get("scales") or [])[:2000]:
        if not isinstance(s, dict):
            continue
        page, ppu = s.get("page"), _num(s.get("ppu"))
        unit = s.get("unit")
        if not _is_page(page) or ppu is None or not 1e-4 < ppu < 1e6 \
                or unit not in UNITS:
            continue
        out["scales"].append({"page": page, "ppu": ppu, "unit": unit,
                              "name": _text(s.get("name"), 40),
                              "all": s.get("all") is True})
    for m in (data.get("marks") or [])[:MAX_MARKS]:
        if not isinstance(m, dict) or \
                m.get("type") not in ("length", "area", "count"):
            continue
        pts = _points(m.get("pts"))
        need = {"length": 2, "area": 3, "count": 1}[m["type"]]
        if not _is_page(m.get("page")) or pts is None or len(pts) < need:
            continue
        if m["type"] == "count":
            pts = pts[:1]
        out["marks"].append({"page": m["page"], "type": m["type"],
                             "pts": pts, "group": _text(m.get("group"), 60)})
    return out


def _num(v):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    v = float(v)
    return v if math.isfinite(v) and abs(v) < 1e7 else None


def _is_page(v):
    return isinstance(v, int) and not isinstance(v, bool) and 0 <= v < 100000


def _text(v, most):
    if not isinstance(v, str):
        return ""
    return "".join(c for c in v if c.isprintable()).strip()[:most]


def _points(v):
    if not isinstance(v, list) or not 0 < len(v) <= MAX_POINTS:
        return None
    out = []
    for p in v:
        if not isinstance(p, (list, tuple)) or len(p) != 2:
            return None
        x, y = _num(p[0]), _num(p[1])
        if x is None or y is None:
            return None
        out.append((x, y))
    return out


def build(doc, data):
    """(marks, skipped): the (page, kind, payload) marks QuantiSheet's
    viewer applies, in order - scales first - and how many of the
    browser's marks were left out (no such page, no scale there)."""
    import fitz
    from . import measure_extra
    data = clean(data)
    if data is None:
        return [], 0
    marks, skipped = [], 0
    n_pages = doc.page_count
    scales = {}                         # page -> {"ppu", "unit"}
    for s in data["scales"]:
        if s["page"] >= n_pages:
            continue
        payload = {"ppu": s["ppu"], "unit": s["unit"]}
        if s["name"]:
            payload["name"] = s["name"]
        pages = list(range(n_pages)) if s["all"] else [s["page"]]
        if s["all"]:
            payload["pages"] = pages
        marks.append((s["page"], "set_scale", payload))
        for p in pages:
            scales[p] = {"ppu": s["ppu"], "unit": s["unit"]}
    counts = {}                         # (page, group) -> how many so far
    for m in data["marks"]:
        pno = m["page"]
        if pno >= n_pages:
            skipped += 1
            continue
        page = doc[pno]
        # the browser's PDF coordinates -> the page coordinates marks use
        mat = page.transformation_matrix
        ppts = [fitz.Point(x, y) * mat for x, y in m["pts"]]
        group = m["group"]
        if m["type"] == "count":
            key = (pno, group)
            if key not in counts:
                counts[key] = sum(
                    1 for it in annotate.takeoff_items(doc)
                    if it["type"] == "count" and it["page"] == pno
                    and it["group"] == group)
            counts[key] += 1
            marks.append((pno, "add_count", {
                "pt": [ppts[0].x, ppts[0].y], "n": counts[key],
                "color": COLORS["count"],
                "measure": {"type": "count", "value": 1, "unit": "ea",
                            "group": group, "method": METHOD}}))
            continue
        # the scale set in the browser for this page, else the one the
        # drawing already carries; none -> not measured (never guessed)
        sc = scales.get(pno) or annotate.scale_at(
            doc, pno, [(q.x, q.y) for q in ppts])
        if not sc or not sc.get("ppu"):
            skipped += 1
            continue
        if m["type"] == "length":
            value = takeoff.path_length(ppts) / sc["ppu"]
            kind = "add_line" if len(ppts) == 2 else "add_polyline"
        else:
            value = takeoff.polygon_area(ppts) / sc["ppu"] ** 2
            kind = "add_polygon"
        if not value > 0:
            skipped += 1
            continue
        value, unit_text = measure_extra.to_units(m["type"], value,
                                                  sc["unit"], {})
        label = measure_extra.label_text(m["type"], value, unit_text, group,
                                         {}, takeoff.fmt)
        payload = {"pts": [[q.x, q.y] for q in ppts],
                   "color": COLORS[m["type"]], "label": label,
                   "measure": {"type": m["type"], "value": round(value, 4),
                               "unit": unit_text, "group": group,
                               "method": METHOD}}
        if kind == "add_polygon":
            payload["fill"] = COLORS["area"]
        marks.append((pno, kind, payload))
    return marks, skipped


def read(path):
    """The marks waiting beside `path`, or None."""
    side = sidecar(path)
    try:
        if not os.path.isfile(side) or os.path.getsize(side) > MAX_BYTES:
            return None
        with open(side, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        log.warning("browser marks beside %s unreadable", path)
        return None


def take(view, path):
    """Put the browser's marks beside `path` into the open document
    `view`, as one step Undo takes back, and remove the marks file.
    Returns (measurements added, left out) or None when there were none."""
    data = read(path)
    side = sidecar(path)
    if data is None:
        if os.path.isfile(side):        # unreadable or too big: not kept
            _remove(side)
        return None
    marks, skipped = build(view.doc, data)
    added = 0
    if marks:
        hint, view.method_hint = view.method_hint, None
        try:
            view.apply_marks(marks)
        finally:
            view.method_hint = hint
        added = sum(1 for _p, k, _pl in marks if k != "set_scale")
    _remove(side)
    return added, skipped


def _remove(path):
    try:
        os.remove(path)
    except OSError:
        log.debug("marks file not removed", exc_info=True)


def write(path, data):
    """Keep the browser's marks beside the saved PDF (browserhost)."""
    data = clean(data)
    if data is None or not (data["scales"] or data["marks"]):
        return False
    raw = json.dumps(data).encode("utf-8")
    if len(raw) > MAX_BYTES:
        return False
    with open(sidecar(path), "wb") as f:
        f.write(raw)
    return True
