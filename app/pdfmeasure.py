"""Write QuantiSheet's scales as the PDF standard's measuring viewports
(ISO 32000 §12.9: /VP with a rectilinear /Measure), so Acrobat, Bluebeam
and other PDF tools measure our scaled sheets in real units too.

QuantiSheet's own copy (the job-data file read by annotate.read_scales) stays
the one QuantiSheet reads; this is the copy other programs read. Idea from
Venice's review (Oct 19); written here to the spec - Venice's version had the
ratio as a number pair instead of a text string plus NumberFormat arrays."""
import logging

import fitz

log = logging.getLogger(__name__)
UNIT_LABEL = {"ft": ("ft", "sq ft"), "in": ("in", "sq in"),
              "m": ("m", "sq m"), "mm": ("mm", "sq mm"), "yd": ("yd", "sq yd")}


def ratio_text(ppu, unit="ft"):
    """'1/4 in = 1 ft' style text for /R (what other programs show)."""
    drawn_in = ppu / 72.0
    if unit == "ft":
        if drawn_in >= 1:
            return f"{drawn_in:g} in = 1 ft"
        # architectural first (1/4 in = 1 ft), then engineering (1 in = 20 ft)
        for d in (2, 4, 8, 16, 32):
            n = drawn_in * d
            if abs(n - round(n)) < 1e-6:
                return f"{round(n)}/{d} in = 1 ft"
        den = 1 / drawn_in
        if abs(den - round(den)) < 1e-6:
            return f"1 in = {round(den)} ft"
        return f"{drawn_in:.4f} in = 1 ft"
    return f"1 pt = {1 / ppu:.6g} {unit}"


def _num(x):
    s = f"{x:.10f}".rstrip("0").rstrip(".")
    return s if s not in ("", "-0") else "0"


def _measure(ppu, unit):
    lin, area = UNIT_LABEL.get(unit, (unit, "sq " + unit))
    fmt = ("<</Type/NumberFormat/U({u})/C {c}/F/D/D 100"
           "/RT( )/SS( )>>")
    return ("<</Type/Measure/Subtype/RL/R({r})"
            "/X[{x}]/D[{d}]/A[{a}]>>").format(
        r=ratio_text(ppu, unit),
        x=fmt.format(u=lin, c=_num(1.0 / ppu)),     # points -> unit
        d=fmt.format(u=lin, c="1"),
        a=fmt.format(u=area, c="1"))


def _bbox(page, rect=None):
    """A rect in PDF user space (y up). None: the whole page."""
    if rect is None:
        r = page.mediabox
    else:
        r = fitz.Rect(rect) * ~page.transformation_matrix
    r = r.normalize()
    return f"[{_num(r.x0)} {_num(r.y0)} {_num(r.x1)} {_num(r.y1)}]"


def sync_page(doc, pno, entry):
    """Write page `pno`'s /VP from QuantiSheet's scale entry ({"ppu", "unit",
    "viewports": [...]}) - or remove it when there's no scale. Viewports
    come first: other programs use the first one that contains the point,
    and the whole-page scale last."""
    try:
        page = doc[pno]
        vps = []
        for v in (entry or {}).get("viewports") or []:
            if isinstance(v, dict) and v.get("ppu", 0) > 0:
                vps.append("<</Type/Viewport/BBox{b}/Name({n})/Measure{m}>>"
                           .format(b=_bbox(page, v["rect"]),
                                   n=str(v.get("name", "Viewport"))[:40]
                                   .replace("(", "[").replace(")", "]"),
                                   m=_measure(v["ppu"], v.get("unit", "ft"))))
        if (entry or {}).get("ppu", 0) > 0:
            vps.append("<</Type/Viewport/BBox{b}/Name(Sheet scale)/Measure{m}>>"
                       .format(b=_bbox(page), m=_measure(
                           entry["ppu"], entry.get("unit", "ft"))))
        doc.xref_set_key(page.xref, "VP", "[" + "".join(vps) + "]" if vps
                         else "null")
        return True
    except Exception:                                     # noqa: BLE001
        log.debug("PDF measuring viewport not written", exc_info=True)
        return False


def read_page(doc, pno):
    """[(name, ratio text, points per unit, unit)] from a page's /VP - for
    checking, and for scales set by other programs."""
    import re
    page = doc[pno]
    kind, val = doc.xref_get_key(page.xref, "VP")
    if kind == "null" or not val:
        return []
    out = []
    for m in re.finditer(r"/Name\s*\(([^)]*)\).*?/R\s*\(([^)]*)\).*?/X\s*\[\s*"
                         r"<<(.*?)>>", val, re.S):
        c = re.search(r"/C\s+([\d.eE+-]+)", m.group(3))
        u = re.search(r"/U\s*\(([^)]*)\)", m.group(3))
        if c and float(c.group(1)) > 0:
            out.append((m.group(1), m.group(2), 1 / float(c.group(1)),
                        u.group(1) if u else ""))
    return out
