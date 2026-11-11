"""Takeoff items, PlanSwift-style: make "Outlets (count)" or "Wall Type A
(length)" first, with its own color, then click it in the Takeoff panel
and every click adds to it - no "What are you counting?" each time.

Items are kept in the PDF (embedded file quantisheet_takeoffitems.json), so
they are there with no markups yet; every group already drawn on the
sheets is an item too. Renaming, recoloring and deleting an item change its
markups through ordinary (undoable) set_annot / delete_annot marks."""
import json
import logging

from . import embfiles

log = logging.getLogger(__name__)
FILE = "quantisheet_takeoffitems.json"
TYPES = ("count", "length", "area")
TOOL = {"count": "count", "length": "measure_polylength",
        "area": "measure_area"}
LABEL = {"count": "Count", "length": "Length", "area": "Area"}
# strong, easy-to-tell-apart colors (also the panel's Clean Display)
PALETTE = [(0.85, 0.15, 0.15), (0.12, 0.42, 0.85), (0.1, 0.62, 0.25),
           (0.95, 0.55, 0.05), (0.55, 0.2, 0.75), (0.0, 0.65, 0.7),
           (0.85, 0.2, 0.6), (0.45, 0.35, 0.15), (0.2, 0.2, 0.2),
           (0.6, 0.7, 0.05), (0.95, 0.8, 0.1), (0.3, 0.55, 0.95),
           (0.75, 0.4, 0.3), (0.1, 0.4, 0.4), (0.9, 0.45, 0.65),
           (0.4, 0.15, 0.45)]


def _rgb(c):
    try:
        return tuple(round(float(x), 3) for x in list(c)[:3])
    except (TypeError, ValueError):
        return None


def read(doc):
    """The saved items: [{"name", "type", "color"}], in the order made."""
    out = []
    try:
        if FILE in embfiles.names(doc):
            saved = json.loads(embfiles.get(doc, FILE).decode("utf-8"))
            for it in (saved or {}).get("items", []):
                name = str(it.get("name") or "").strip()
                if name and it.get("type") in TYPES:
                    out.append({"name": name[:60], "type": it["type"],
                                "color": _rgb(it.get("color"))})
    except Exception:
        log.warning("could not read takeoff items", exc_info=True)
    return out


def write(doc, items):
    data = {"items": [{"name": it["name"], "type": it["type"],
                       "color": list(it["color"]) if it.get("color")
                       else None} for it in items]}
    embfiles.put(doc, FILE, json.dumps(data).encode("utf-8"),
                 "QuantiSheet takeoff items")


def key(it):
    return (it["name"], it["type"])


def items(doc, groups=None):
    """Every item - saved ones first, then groups drawn on the sheets that
    aren't saved - with its job total: [{"name", "type", "color", "total",
    "unit", "n", "pending", "n_pending", "refs": [(page, ref)], "saved"}].
    "pending": AI measurements flagged for review, not accepted yet - not
    in "total". `groups` is
    takeoff_tree.group_items(doc) when the caller already has it."""
    if groups is None:
        from .takeoff_tree import group_items
        groups = group_items(doc)
    drawn = {}
    for pno in sorted(groups):
        for (name, mtype, unit), g in groups[pno].items():
            if mtype not in TYPES:
                continue
            d = drawn.setdefault((name, mtype), {
                "total": 0.0, "n": 0, "refs": [], "color": None,
                "unit": unit, "pending": 0.0, "n_pending": 0})
            d["total"] += g["total"]
            d["n"] += g["n"]
            d["pending"] += g.get("pending", 0.0)
            d["n_pending"] += g.get("n_pending", 0)
            d["refs"] += [(pno, r) for r in g["refs"]]
            d["color"] = d["color"] or _rgb(g["color"])
    out = []
    for it in read(doc):
        if any(key(o) == key(it) for o in out):
            continue
        d = drawn.pop(key(it), None) or {}
        out.append({"name": it["name"], "type": it["type"],
                    "color": it["color"] or d.get("color"),
                    "total": d.get("total", 0.0), "n": d.get("n", 0),
                    "pending": d.get("pending", 0.0),
                    "n_pending": d.get("n_pending", 0),
                    "refs": d.get("refs", []),
                    "unit": d.get("unit") or ("ea" if it["type"] == "count"
                                              else ""),
                    "saved": True})
    for (name, mtype), d in sorted(drawn.items()):
        out.append({"name": name, "type": mtype, "color": d["color"],
                    "total": d["total"], "n": d["n"], "refs": d["refs"],
                    "pending": d["pending"], "n_pending": d["n_pending"],
                    "unit": d["unit"], "saved": False})
    return out


def find(doc, name, mtype, groups=None):
    for it in items(doc, groups):
        if key(it) == (name, mtype):
            return it
    return None


def next_color(doc, groups=None):
    """The first palette color no item uses yet."""
    used = {_rgb(it["color"]) for it in items(doc, groups) if it["color"]}
    for c in PALETTE:
        if _rgb(c) not in used:
            return c
    return PALETTE[len(used) % len(PALETTE)]


def _saved_list(doc, groups=None):
    """The saved list with every drawn item added, so a change to one
    keeps the others' order and colors."""
    return [{"name": it["name"], "type": it["type"], "color": it["color"]}
            for it in items(doc, groups)]


def add(doc, name, mtype, color=None):
    """Save a new item (or return the one already called that)."""
    name = str(name or "").strip()[:60]
    if not name or mtype not in TYPES:
        raise ValueError("an item needs a name and a type")
    cur = read(doc)
    for it in cur:
        if key(it) == (name, mtype):
            return it
    drawn = find(doc, name, mtype)
    it = {"name": name, "type": mtype,
          "color": _rgb(color) or (drawn or {}).get("color")
          or next_color(doc)}
    write(doc, cur + [it])
    return it


def _replace(doc, old_key, new):
    """Swap the saved record `old_key` for `new` (None = remove it)."""
    lst = _saved_list(doc)
    out = []
    for it in lst:
        if key(it) == old_key:
            if new is not None:
                out.append(new)
        elif new is None or key(it) != key(new):
            out.append(it)
    write(doc, out)


def rename(doc, name, mtype, new):
    """Rename an item; returns the set_annot marks that rename its
    markups (apply them with view.apply_marks)."""
    new = str(new or "").strip()[:60]
    it = find(doc, name, mtype)
    if it is None or not new or new == name:
        return []
    _replace(doc, (name, mtype), {"name": new, "type": mtype,
                                  "color": it["color"]})
    return [(pno, "set_annot", dict(r, group=new)) for pno, r in it["refs"]]


def reassign_preview(doc, name, mtype, new):
    """What renaming `name` to `new` would move, before it moves:
    {"pieces", "pages" (sorted page indexes), "merge" (True when `new` is
    already an item of this type, so the pieces join it)}."""
    it = find(doc, name, mtype)
    refs = (it or {}).get("refs") or []
    new = str(new or "").strip()[:60]
    merge = bool(new) and new != name and any(
        key(x) == (new, mtype) for x in items(doc))
    return {"pieces": len(refs), "pages": sorted({p for p, _ in refs}),
            "merge": merge}


def reassign_text(preview, name, new):
    """The question asked before a reassign, from reassign_preview()."""
    n, pages = preview["pieces"], preview["pages"]
    s = (f"Move {n} piece{'s' * (n != 1)} on {len(pages)} "
         f"page{'s' * (len(pages) != 1)} from \"{name}\" to \"{new}\"?")
    if preview["merge"]:
        s += f"\n\n\"{new}\" is already an item: they join it."
    return s + "\n\n(Edit > Undo puts them back.)"


def recolor(doc, name, mtype, color):
    """Give an item a new color; returns the set_annot marks that recolor
    its markups (areas get the fill too)."""
    it = find(doc, name, mtype)
    c = _rgb(color)
    if it is None or c is None:
        return []
    _replace(doc, (name, mtype), {"name": name, "type": mtype, "color": c})
    extra = {"color": list(c)}
    if mtype == "area":
        extra["fill"] = list(c)
    return [(pno, "set_annot", dict(r, **extra)) for pno, r in it["refs"]]


def duplicate(doc, name, mtype):
    """A new, empty item like this one: "Outlets (2)", the next color."""
    it = find(doc, name, mtype)
    if it is None:
        return None
    taken = {it2["name"] for it2 in items(doc) if it2["type"] == mtype}
    i = 2
    while f"{name} ({i})" in taken:
        i += 1
    return add(doc, f"{name} ({i})", mtype, next_color(doc))


def remove(doc, name, mtype):
    """Forget an item; returns the delete_annot marks for its markups."""
    it = find(doc, name, mtype)
    if it is None:
        return []
    _replace(doc, (name, mtype), None)
    return [(pno, "delete_annot", dict(r)) for pno, r in it["refs"]]


def unit_label(it):
    return {"count": "ea"}.get(it["type"], it.get("unit") or "")


def fmt_total(it):
    s = _fmt_total(it)
    if it.get("n_pending"):
        # flagged for review, not accepted: beside the total, not in it
        p = _fmt_total(dict(it, total=it.get("pending") or 0.0))
        s += f" (+{p} pending)"
    return s


def _fmt_total(it):
    unit = unit_label(it)
    v = it.get("total") or 0.0
    if it["type"] == "count" and float(v).is_integer():
        return f"{int(v):,} ea"
    if not unit:                     # nothing measured yet
        return f"{v:,.1f} ({it['type']})" if v else f"0 ({it['type']})"
    return f"{v:,.1f} {unit}"
