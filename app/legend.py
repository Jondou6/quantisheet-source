"""Markup legends: one row per kind of markup on a page (its color, what
it is, how many and how much), drawn as a framed table on the sheet.

A legend can also (Nov 2, kept on it as PSLegendOpts):
  scope "all"   total every page of the set, not just its own page;
  tools         list only a tool set's items (and show the ones not used
                yet, at zero) - one or more sets;
  live          redraw itself whenever a markup is added, changed or
                deleted (viewer.apply_marks);
  count         show how many markups next to the quantity.
"""
import json

from . import annotate

OPTS_KEY = "PSLegendOpts"


def rows(doc, pno):
    """Legend rows for page `pno`, in the order they first appear."""
    page = doc[pno]
    groups = {}
    hatched = {annotate.tag_of(x) for x in annotate.iter_annots(page)
               if annotate.is_hatch(doc, x)}
    nets = {it["tag"]: it for it in annotate.takeoff_items(doc)
            if it["page"] == pno and it["tag"]}
    for a in annotate.iter_annots(page):
        if annotate.is_label(doc, a) or annotate.is_hatch(doc, a) or \
                annotate.is_legend(doc, a):
            continue
        if a.type[1] in ("Link", "Widget", "Popup"):
            continue
        info = a.info or {}
        subj = info.get("subject", "")
        kind = annotate.friendly_type(a, subj, doc)
        color = list(annotate.markup_color(doc, a) or (0, 0, 0))
        name = subj
        value, unit, mtype, each = None, "", "other", 1.0
        if subj.startswith(annotate.TAKEOFF + ":"):
            parts = (subj.split(":", 5) + [""] * 6)
            mtype, unit, group = parts[1], parts[3], parts[4]
            if mtype == annotate.CUTOUT:
                continue                 # counted in its area's net value
            name = group or kind
            it = nets.get(annotate.tag_of(a))
            if it and isinstance(it.get("roof"), dict) and not group:
                from . import roof
                name = roof.name_of(it)
            try:
                value = it["value"] if it else float(parts[2])
            except ValueError:
                value = None
            if mtype == "count":
                try:
                    each = float(parts[2]) or 1.0
                except ValueError:
                    each = 1.0
                value, unit = None, ""
            elif mtype not in ("length", "area"):
                mtype = "other"
        key = (kind, name, annotate._hex(color))
        g = groups.setdefault(key, {"kind": kind, "name": name,
                                    "color": color, "n": 0, "total": 0.0,
                                    "unit": unit, "hatch": False,
                                    "type": mtype, "each": 0.0})
        g["n"] += 1
        g["each"] += each
        if value is not None:
            g["total"] += value
        if annotate.tag_of(a) in hatched:
            g["hatch"] = True
    out = []
    for g in groups.values():
        label = g["kind"] if not g["name"] or g["name"] == g["kind"] \
            else f"{g['name']} ({g['kind']})"
        qty = f"{g['n']}"
        if g["unit"] and g["total"]:
            qty += f"  |  {g['total']:,.2f} {g['unit']}"
        if g["type"] == "count":
            total = g["each"]
        elif g["type"] in ("length", "area"):
            total = g["total"]
        else:
            total = None
        out.append({"color": [round(c, 3) for c in g["color"][:3]],
                    "label": label, "qty": qty, "hatch": g["hatch"],
                    "type": g["type"], "name": g["name"] or g["kind"],
                    "kind": g["kind"], "n": g["n"], "total": total,
                    "unit": g["unit"]})
    return out


STYLES = ("takeoff", "classic")


def format_qty(row, style="classic"):
    """The quantity column: classic keeps the markup count and 2 decimals;
    takeoff shows only the quantity, 1 decimal, units in capitals."""
    if style != "takeoff":
        return str(row.get("qty", ""))
    q = _takeoff_qty(row)
    return f"({row.get('n', 0)})  {q}" if row.get("with_n") else q


def _takeoff_qty(row):
    total = row.get("total")
    if row.get("type") == "count":
        return _one(total if total is not None else row.get("n", 0))
    if total is None:
        return str(row.get("n", ""))
    unit = str(row.get("unit") or "").upper()
    return f"{_one(total)} {unit}".strip()


def _one(v):
    """1 decimal, halves up (408.25 -> 408.3, as takeoff programs show)."""
    from decimal import Decimal, ROUND_HALF_UP
    try:
        d = Decimal(repr(float(v))).quantize(Decimal("0.1"), ROUND_HALF_UP)
    except Exception:
        return str(v)
    return f"{d:,.1f}"


def format_label(row, style="classic"):
    """Classic: the name plus its type; takeoff: the name alone."""
    if style != "takeoff":
        return str(row.get("label", ""))
    return str(row.get("name") or row.get("kind") or row.get("label", ""))


def legends_on(doc, pno):
    """(op tag, rect, title) of each legend on the page."""
    return [x[:3] for x in _legends(doc, pno)]


def style_of(doc, a):
    t, v = doc.xref_get_key(a.xref, "PSLegendStyle")
    return v if t == "string" and v in STYLES else ""


def _legends(doc, pno):
    out = []
    for a in annotate.iter_annots(doc[pno]):
        if annotate.is_legend(doc, a):
            out.append((annotate.tag_of(a), list(a.rect),
                        (a.info or {}).get("content", "Legend"),
                        style_of(doc, a), opts_of(doc, a)))
    return out


def refresh_marks(doc, pno, live_only=False):
    """Marks that redraw every legend on page `pno` with current rows
    (only the live ones with live_only). Each keeps its options."""
    marks = []
    for tag, rect, title, style, opts in _legends(doc, pno):
        if not tag or (live_only and not opts.get("live")):
            continue
        p = {"rect": rect, "title": title, "rows": rows_for(doc, pno, opts)}
        if style:
            p["style"] = style
        if opts:
            p["opts"] = opts
        marks.append((pno, "delete_annot", {"target": tag}))
        marks.append((pno, "add_legend", p))
    return marks


# ---- options (Nov 2) ---------------------------------------------------------------

_TOOL_TYPE = {"measure_length": "length", "measure_polylength": "length",
              "measure_area": "area", "measure_volume": "other",
              "measure_wall": "area", "auto_area": "area",
              "trace_outline": "area", "trace_length": "length",
              "count": "count", "symbol": "count"}


def set_tools(chest, names):
    """The tools of Tool Chest sets `names`, as a legend keeps them:
    [{"name", "type", "color"}] (one per item name)."""
    out, seen = [], set()
    for g in names:
        for t in chest.get(g, []):
            name = t.get("subject") or t.get("name")
            if not name or name in seen:
                continue
            seen.add(name)
            typ = _TOOL_TYPE.get(t.get("tool"))
            if t.get("height") and typ == "length":
                typ = "area"
            out.append({"name": name, "type": typ or "other",
                        "color": list(t.get("color") or (0, 0, 0))[:3]})
    return out


def clean_opts(o):
    o = o if isinstance(o, dict) else {}
    out = {}
    if o.get("scope") == "all":
        out["scope"] = "all"
    for k in ("live", "count"):
        if o.get(k):
            out[k] = True
    sets = [str(x)[:60] for x in o.get("sets") or [] if str(x).strip()]
    if sets:
        out["sets"] = sets[:5]
    tools = []
    for t in o.get("tools") or []:
        if isinstance(t, dict) and t.get("name"):
            tools.append({"name": str(t["name"])[:60],
                          "type": t.get("type") if t.get("type") in (
                              "length", "area", "count") else "other",
                          "color": [float(c) for c in (t.get("color") or
                                                       [0, 0, 0])[:3]]})
    if tools:
        out["tools"] = tools[:60]
    return out


def opts_of(doc, a):
    t, v = doc.xref_get_key(a.xref, OPTS_KEY)
    if t != "string" or not v:
        return {}
    try:
        return clean_opts(json.loads(v))
    except ValueError:
        return {}


def _merge(rows_lists):
    """Rows of several pages as one: same kind, name and color add up."""
    merged = {}
    for rows_ in rows_lists:
        for r in rows_:
            k = (r["kind"], r["name"], tuple(r["color"]))
            m = merged.get(k)
            if m is None:
                merged[k] = dict(r)
                continue
            m["n"] += r["n"]
            m["hatch"] = m["hatch"] or r["hatch"]
            if r.get("total") is not None:
                m["total"] = (m.get("total") or 0.0) + r["total"]
    out = []
    for m in merged.values():
        qty = f"{m['n']}"
        if m["unit"] and m.get("total") and m["type"] != "count":
            qty += f"  |  {m['total']:,.2f} {m['unit']}"
        m["qty"] = qty
        out.append(m)
    return out


def rows_for(doc, pno, opts=None):
    """The rows a legend with `opts` shows on page `pno`."""
    opts = clean_opts(opts)
    if opts.get("scope") == "all":
        r = _merge([rows(doc, i) for i in range(doc.page_count)])
    else:
        r = rows(doc, pno)
    tools = opts.get("tools")
    if tools:
        want = {t["name"] for t in tools}
        r = [x for x in r if x["name"] in want]
        have = {x["name"] for x in r}
        for t in tools:
            if t["name"] not in have:
                r.append({"color": t["color"], "label": t["name"],
                          "qty": "0", "hatch": False, "type": t["type"],
                          "name": t["name"], "kind": t["name"], "n": 0,
                          "total": 0.0, "unit": ""})
        order = {t["name"]: i for i, t in enumerate(tools)}
        r.sort(key=lambda x: order.get(x["name"], 999))
    if opts.get("count"):
        for x in r:
            x["with_n"] = True
    return r


def live_pages(doc):
    """{page: [scope]} of the pages with a legend that keeps itself up to
    date ("all": it totals every page)."""
    out = {}
    for pno in range(doc.page_count):
        for a in annotate.iter_annots(doc[pno]):
            if annotate.is_legend(doc, a):
                o = opts_of(doc, a)
                if o.get("live"):
                    out.setdefault(pno, []).append(o.get("scope", "page"))
    return out
