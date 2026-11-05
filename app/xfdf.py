"""XFDF: the markup exchange format Acrobat and Bluebeam read and write.

export(doc, path) writes every markup; import_marks(doc, path) turns an
XFDF file into "import_annots" marks (one undoable step when applied).

XFDF uses PDF coordinates (origin bottom-left of the page box); QuantiSheet
ops use PyMuPDF's unrotated page coordinates (origin top-left).
QuantiSheet's own details (measurement labels, status, hatch) ride along in
extra "ps-*" attributes that other programs ignore.
"""
import re
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape, quoteattr

import fitz

from . import annotate

NS = "http://ns.adobe.com/xfdf/"

TAGS = {
    fitz.PDF_ANNOT_SQUARE: "square", fitz.PDF_ANNOT_CIRCLE: "circle",
    fitz.PDF_ANNOT_LINE: "line", fitz.PDF_ANNOT_POLY_LINE: "polyline",
    fitz.PDF_ANNOT_POLYGON: "polygon", fitz.PDF_ANNOT_INK: "ink",
    fitz.PDF_ANNOT_HIGHLIGHT: "highlight",
    fitz.PDF_ANNOT_UNDERLINE: "underline",
    fitz.PDF_ANNOT_STRIKE_OUT: "strikeout",
    fitz.PDF_ANNOT_FREE_TEXT: "freetext", fitz.PDF_ANNOT_TEXT: "text",
    fitz.PDF_ANNOT_STAMP: "stamp",
}
TYPES = {v: k for k, v in TAGS.items()}
ENDS = ["None", "Square", "Circle", "Diamond", "OpenArrow", "ClosedArrow",
        "Butt", "ROpenArrow", "RClosedArrow", "Slash"]
PS_KEYS = {"PSKind": "ps-kind", "PSLabel": "ps-label",
           "PSBadge": "ps-badge",
           "PSStatus": "ps-status", "PSHatch": "ps-hatch"}


# ---- coordinates ----------------------------------------------------------------

def _box(doc, page):
    """The page box (crop box, else media box) in PDF coordinates."""
    x = page.xref
    for _ in range(32):
        for key in ("CropBox", "MediaBox"):
            t, v = doc.xref_get_key(x, key)
            if t == "array":
                nums = [float(n) for n in re.findall(r"-?\d+(?:\.\d+)?", v)]
                if len(nums) == 4:
                    x0, y0, x1, y1 = nums
                    return min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)
        t, v = doc.xref_get_key(x, "Parent")
        if t != "xref":
            break
        x = int(v.split()[0])
    r = page.mediabox
    return r.x0, r.y0, r.x1, r.y1


def _to_pdf(box, x, y):
    return x + box[0], box[3] - y


def _from_pdf(box, x, y):
    return x - box[0], box[3] - y


def _num(v):
    return f"{v:.4f}".rstrip("0").rstrip(".")


def _hex(c):
    if not c:
        return None
    c = list(c)[:3]
    return "#" + "".join(f"{int(round(max(0, min(1, v)) * 255)):02X}"
                         for v in c)


def _color(h):
    if not h or not re.fullmatch(r"#[0-9A-Fa-f]{6}", h.strip()):
        return None
    h = h.strip()
    return [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]


# ---- export ----------------------------------------------------------------------

def export(doc, path, pages=None):
    """Write the document's markups to an XFDF file. Returns the count."""
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             f'<xfdf xmlns="{NS}" xml:space="preserve">', "<annots>"]
    n = 0
    fname = (doc.name or "").replace("\\", "/").split("/")[-1]
    for pno, page in enumerate(doc):
        if pages is not None and pno not in pages:
            continue
        box = _box(doc, page)
        for a in annotate.iter_annots(page):
            tag = TAGS.get(a.type[0])
            if tag is None:
                continue
            lines.append(_annot_xml(doc, page, a, pno, box, tag))
            n += 1
    lines += ["</annots>", f'<f href={quoteattr(fname)}/>' if fname else "",
              "</xfdf>"]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(x for x in lines if x))
    return n


def _annot_xml(doc, page, a, pno, box, tag):
    info = a.info or {}
    colors = a.colors or {}
    border = a.border or {}
    r = fitz.Rect(a.rect)
    x0, y1 = _to_pdf(box, r.x0, r.y0)
    x1, y0 = _to_pdf(box, r.x1, r.y1)
    fringe = None
    if tag in ("square", "circle"):
        inner = annotate.inner_rect(doc, a)
        if inner != r:
            fringe = (inner.x0 - r.x0, inner.y0 - r.y0, r.x1 - inner.x1,
                      r.y1 - inner.y1)          # left, top, right, bottom
    attrs = {"page": str(pno),
             "rect": ",".join(_num(v) for v in (x0, y0, x1, y1)),
             "fringe": ",".join(_num(v) for v in fringe) if fringe else "",
             "name": info.get("id") or f"ps{a.xref}",
             "title": info.get("title", ""),
             "subject": info.get("subject", ""),
             "date": info.get("modDate", ""),
             "creationdate": info.get("creationDate", ""),
             "flags": "print"}
    if colors.get("stroke"):
        attrs["color"] = _hex(colors["stroke"])
    if colors.get("fill") and tag in ("square", "circle", "polygon",
                                      "line", "polyline"):
        attrs["interior-color"] = _hex(colors["fill"])
    if border.get("width", -1) > 0:
        attrs["width"] = _num(border["width"])
    if border.get("dashes"):
        attrs["style"] = "dash"
        attrs["dashes"] = ",".join(_num(d) for d in border["dashes"])
    if border.get("clouds", -1) > 0:
        attrs["style"] = "cloudy"
        attrs["intensity"] = _num(border["clouds"])
    if a.opacity is not None and 0 <= a.opacity < 1:
        attrs["opacity"] = _num(a.opacity)
    for key, attr in PS_KEYS.items():
        t, v = doc.xref_get_key(a.xref, key)
        if t != "null":
            attrs[attr] = v
    inner = []
    v = a.vertices or []
    if tag == "line" and len(v) >= 2:
        attrs["start"] = ",".join(_num(c) for c in _to_pdf(box, *v[0]))
        attrs["end"] = ",".join(_num(c) for c in _to_pdf(box, *v[1]))
        le = a.line_ends or (0, 0)
        attrs["head"] = ENDS[le[0]] if 0 <= le[0] < len(ENDS) else "None"
        attrs["tail"] = ENDS[le[1]] if 0 <= le[1] < len(ENDS) else "None"
    elif tag in ("polyline", "polygon") and v:
        pts = ";".join(",".join(_num(c) for c in _to_pdf(box, *p)) for p in v)
        inner.append(f"<vertices>{pts}</vertices>")
    elif tag == "ink" and v:
        gest = "".join(
            "<gesture>" + ";".join(",".join(_num(c) for c in
                                            _to_pdf(box, *p)) for p in s)
            + "</gesture>" for s in v)
        inner.append(f"<inklist>{gest}</inklist>")
    elif tag in ("highlight", "underline", "strikeout") and v:
        attrs["coords"] = ",".join(_num(c) for p in v
                                   for c in _to_pdf(box, *p))
    elif tag == "freetext":
        da = doc.xref_get_key(a.xref, "DA")[1] or "/Helv 10 Tf 0 g"
        inner.append(f"<defaultappearance>{escape(da)}</defaultappearance>")
    elif tag == "text":
        attrs["icon"] = "Comment"
    elif tag == "stamp":
        attrs["icon"] = (info.get("subject") or "Draft").replace(" ", "")
    content = info.get("content", "")
    if content:
        inner.insert(0, f"<contents>{escape(content)}</contents>")
    a_txt = " ".join(f"{k}={quoteattr(str(val))}" for k, val in attrs.items()
                     if val not in (None, ""))
    return f"<{tag} {a_txt}>{''.join(inner)}</{tag}>"


# ---- import ------------------------------------------------------------------------

def _pairs(text):
    nums = [float(n) for n in re.split(r"[,;\s]+", (text or "").strip())
            if n]
    return [(nums[i], nums[i + 1]) for i in range(0, len(nums) - 1, 2)]


def _local(tag):
    return tag.split("}", 1)[-1]


def parse(path):
    """[(page, serialized annotation dict)] from an XFDF file."""
    from . import safexml                   # threat model T-007
    root = safexml.parse(path).getroot()
    annots = None
    for el in root:
        if _local(el.tag) == "annots":
            annots = el
    return list(annots) if annots is not None else []


def import_marks(doc, path, layer=None):
    """Marks that add the XFDF file's markups to `doc` (pages that don't
    exist are skipped). Markups that shared a name (a measurement and its
    label) stay together."""
    groups = {}
    order = []
    for el in parse(path):
        tag = _local(el.tag)
        if tag not in TYPES:
            continue
        try:
            pno = int(el.get("page", "0"))
        except ValueError:
            continue
        if not 0 <= pno < doc.page_count:
            continue
        d = _to_dict(doc, doc[pno], el, tag)
        if d is None:
            continue
        # markups that share a name on a page stay together, as the
        # docstring says (review 3b C9); unnamed ones stay apart
        name = el.get("name") or f"\0n{len(order)}"
        key = (pno, name)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(d)
    marks = []
    for key in order:
        payload = {"annots": groups[key]}
        if layer:
            payload["layer"] = layer
        marks.append((key[0], "import_annots", payload))
    return marks


def _to_dict(doc, page, el, tag):
    box = _box(doc, page)
    nums = [float(n) for n in re.split(r"[,\s]+", el.get("rect", "")) if n]
    if len(nums) != 4:
        return None
    fr = [float(n) for n in re.split(r"[,\s]+", el.get("fringe", "")) if n]
    if len(fr) == 4 and tag in ("square", "circle"):
        # the shape sits inside its rect by the fringe (PDF /RD)
        # fringe is left, top, right, bottom; XFDF y runs up
        nums = [nums[0] + fr[0], nums[1] + fr[3], nums[2] - fr[2],
                nums[3] - fr[1]]
    ax, ay = _from_pdf(box, nums[0], nums[1])
    bx, by = _from_pdf(box, nums[2], nums[3])
    d = {"type": TYPES[tag], "rect": list(fitz.Rect(ax, ay, bx, by)
                                          .normalize()),
         "colors": {}, "width": 1.0, "dashes": [], "clouds": -1,
         "opacity": -1, "line_ends": [0, 0], "keys": {},
         "info": {"title": el.get("title", ""),
                  "subject": el.get("subject", ""), "content": ""}}
    c = _color(el.get("color"))
    if c:
        d["colors"]["stroke"] = c
    f = _color(el.get("interior-color"))
    if f:
        d["colors"]["fill"] = f
    try:
        d["width"] = float(el.get("width", "1"))
    except ValueError:
        pass
    if el.get("dashes"):
        d["dashes"] = [float(x) for x in re.split(r"[,\s]+", el.get("dashes"))
                       if x]
    if el.get("style") == "cloudy":
        try:
            d["clouds"] = float(el.get("intensity", "1"))
        except ValueError:
            d["clouds"] = 1
    try:
        op = float(el.get("opacity", "-1"))
        d["opacity"] = op if 0 < op < 1 else -1
    except ValueError:
        pass
    for key, attr in PS_KEYS.items():
        if el.get(attr) is not None:
            v = el.get(attr)
            d["keys"][key] = ["bool", v] if key in ("PSLabel", "PSBadge") \
                else ["string", v]
    for child in el:
        name = _local(child.tag)
        if name == "contents":
            d["info"]["content"] = child.text or ""
        elif name == "vertices":
            d["vertices"] = [list(_from_pdf(box, *p))
                             for p in _pairs(child.text)]
        elif name == "inklist":
            d["vertices"] = [[list(_from_pdf(box, *p))
                              for p in _pairs(g.text)] for g in child]
        elif name == "defaultappearance":
            m = re.search(r"([\d.]+)\s+Tf", child.text or "")
            if m:
                d["fontsize"] = float(m.group(1))
    if tag == "line":
        pts = _pairs(el.get("start", "")) + _pairs(el.get("end", ""))
        if len(pts) < 2:
            return None
        d["vertices"] = [list(_from_pdf(box, *p)) for p in pts[:2]]
        d["line_ends"] = [ENDS.index(el.get("head", "None"))
                          if el.get("head") in ENDS else 0,
                          ENDS.index(el.get("tail", "None"))
                          if el.get("tail") in ENDS else 0]
    if tag in ("highlight", "underline", "strikeout"):
        d["vertices"] = [list(_from_pdf(box, *p))
                         for p in _pairs(el.get("coords", ""))]
    return d
