"""Tool Chest: saved, styled tools you can reuse with one click.

A tool is {"name", "tool", "color", "fill", "width", "opacity", "subject"},
where "tool" is a viewer tool id (e.g. "measure_length") and "subject" names
what it measures or counts ("Interior Wall"), which is how the estimate
groups quantities. Stored in ~/.quantisheet/toolchest.json.

Each group is a tool set. A tool can also carry (Nov 2):
  unit        the unit its measurements are kept in ("m" in a metric set)
  rise        vertical length added to each run ("8'")
  height      a wall height: runs become wall areas ("9'")
  openings    openings taken out of a wall ("3x7 x2")
  depth       the depth a volume tool suggests ("4\"")
  unit_cost   a price per unit, kept on each markup it makes
  fields      Markups List column values ({"Product": "Type X"}) kept on
              each markup it makes
A set can be saved as a .qstools file and opened on another computer, so
a whole team draws with the same tools (export_sets / read_sets / merge).
"""
import copy
import json
import logging
import os

from . import settings

log = logging.getLogger(__name__)

PATH = os.path.join(settings.DIR, "toolchest.json")

DEFAULT = {
    "Takeoff": [
        {"name": "Interior Wall", "tool": "measure_polylength",
         "color": [0.85, 0.1, 0.1], "width": 3, "subject": "Interior Wall"},
        {"name": "Exterior Wall", "tool": "measure_polylength",
         "color": [0.1, 0.3, 0.85], "width": 3, "subject": "Exterior Wall"},
        {"name": "Flooring", "tool": "measure_area",
         "color": [0.2, 0.65, 0.2], "fill": [0.2, 0.65, 0.2], "width": 1,
         "opacity": 0.35, "subject": "Flooring"},
        {"name": "Ceiling", "tool": "measure_area",
         "color": [0.55, 0.3, 0.75], "fill": [0.55, 0.3, 0.75], "width": 1,
         "opacity": 0.35, "subject": "Ceiling"},
        {"name": "Doors", "tool": "count", "color": [0.9, 0.45, 0],
         "subject": "Doors"},
        {"name": "Outlets", "tool": "count", "color": [0.85, 0.1, 0.1],
         "subject": "Outlets"},
        {"name": "Light Fixtures", "tool": "count", "color": [0.75, 0.6, 0],
         "subject": "Light Fixtures"},
    ],
    "Takeoff (Metric)": [
        {"name": "Interior Wall (m)", "tool": "measure_polylength",
         "color": [0.85, 0.1, 0.1], "width": 3, "subject": "Interior Wall",
         "unit": "m"},
        {"name": "Exterior Wall (m)", "tool": "measure_polylength",
         "color": [0.1, 0.3, 0.85], "width": 3, "subject": "Exterior Wall",
         "unit": "m"},
        {"name": "Flooring (m\u00b2)", "tool": "measure_area",
         "color": [0.2, 0.65, 0.2], "fill": [0.2, 0.65, 0.2], "width": 1,
         "opacity": 0.35, "subject": "Flooring", "unit": "m"},
        {"name": "Slab (m\u00b3)", "tool": "measure_volume",
         "color": [0.5, 0.5, 0.5], "fill": [0.5, 0.5, 0.5], "width": 1,
         "opacity": 0.35, "subject": "Slab", "unit": "m"},
        {"name": "Drywall (m\u00b2 wall)", "tool": "measure_wall",
         "color": [0.55, 0.3, 0.75], "width": 3, "subject": "Drywall",
         "unit": "m"},
    ],
    "Review": [
        {"name": "Revision Cloud", "tool": "add_cloud",
         "color": [0.9, 0, 0], "width": 2, "subject": "Revision"},
        {"name": "Question", "tool": "add_note", "color": [1, 0.8, 0],
         "subject": "Question"},
        {"name": "Callout Arrow", "tool": "arrow", "color": [0.9, 0, 0],
         "width": 2, "subject": "Callout"},
        {"name": "Hold Area", "tool": "add_rect", "color": [1, 0.5, 0],
         "fill": [1, 0.85, 0.4], "width": 2, "opacity": 0.4,
         "subject": "Hold"},
        {"name": "Approved Highlight", "tool": "add_highlight",
         "color": [0.4, 0.9, 0.4], "subject": "Approved"},
    ],
}

STYLE_KEYS = ("color", "fill", "width", "opacity", "subject", "unit",
              "rise", "height", "openings", "depth", "unit_cost", "fields",
              "line_style", "hatch", "layer")
TOOL_KEYS = ("name", "tool") + STYLE_KEYS
FILE_EXT = ".qstools"
FORMAT = "quantisheet-tool-sets"


def load():
    try:
        with open(PATH, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and all(isinstance(v, list)
                                          for v in data.values()):
            return data
    except FileNotFoundError:
        pass
    except (OSError, ValueError):
        log.warning("tool chest file unreadable; using defaults")
    return copy.deepcopy(DEFAULT)


def save(chest):
    try:
        os.makedirs(settings.DIR, exist_ok=True)
        tmp = PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(chest, f, indent=2)
        os.replace(tmp, PATH)
    except OSError:
        log.warning("could not save tool chest", exc_info=True)


def add(chest, group, item):
    chest.setdefault(group, []).append(item)
    save(chest)


def remove(chest, group, index):
    items = chest.get(group, [])
    if 0 <= index < len(items):
        items.pop(index)
        if not items:
            chest.pop(group, None)
        save(chest)


def style_of(item):
    """The viewer style a tool draws with. A unit cost goes in with the
    tool's column values (fields["Unit Cost"])."""
    out = {k: item[k] for k in STYLE_KEYS if item.get(k) is not None
           and k not in ("unit_cost", "fields")}
    fields = dict(item.get("fields") or {})
    if item.get("unit_cost") not in (None, ""):
        fields["Unit Cost"] = item["unit_cost"]
    if fields:
        out["fields"] = fields
    return out


def clean_tool(item, known=None):
    """A tool from a file, with only the keys a tool has, or None. `known`:
    the tool ids this program has (others are left out)."""
    if not isinstance(item, dict):
        return None
    name = str(item.get("name") or "").strip()[:60]
    tool = item.get("tool")
    if not name or not isinstance(tool, str) or \
            (known is not None and tool not in known):
        return None
    out = {"name": name, "tool": tool}
    for k in ("color", "fill"):
        c = item.get(k)
        if isinstance(c, (list, tuple)) and len(c) == 3 and all(
                isinstance(x, (int, float)) and 0 <= x <= 1 for x in c):
            out[k] = [float(x) for x in c]
    for k, lo, hi in (("width", 0, 50), ("opacity", 0.05, 1),
                      ("unit_cost", 0, 1e9)):
        x = item.get(k)
        if isinstance(x, (int, float)) and lo <= x <= hi:
            out[k] = float(x)
    for k in ("subject", "unit", "rise", "height", "openings", "depth",
              "line_style", "hatch", "layer"):
        x = item.get(k)
        if isinstance(x, (int, float)) and k in ("rise", "height",
                                                 "openings"):
            out[k] = float(x)
        elif isinstance(x, str) and x.strip():
            out[k] = x.strip()[:60]
    if out.get("unit") and out["unit"] not in ("ft", "in", "yd", "m", "cm",
                                               "mm"):
        out.pop("unit")
    f = item.get("fields")
    if isinstance(f, dict):
        clean = {}
        for k, x in list(f.items())[:30]:
            k = str(k).strip()[:40]
            if not k:
                continue
            if isinstance(x, (int, float)) and not isinstance(x, bool):
                clean[k] = x
            elif isinstance(x, str):
                clean[k] = x[:120]
        if clean:
            out["fields"] = clean
    return out


def export_sets(chest, groups, path, statuses=None, columns=None):
    """Save tool sets `groups` (with the custom statuses and Markups List
    columns to go with them) as a .qstools file for the team."""
    data = {"format": FORMAT, "version": 1,
            "sets": {g: [clean_tool(t) for t in chest.get(g, [])
                         if clean_tool(t)] for g in groups if g in chest}}
    if statuses:
        data["statuses"] = [str(x)[:40] for x in statuses if str(x).strip()]
    if columns:
        data["columns"] = list(columns)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)
    return path


class ToolSetError(ValueError):
    pass


def read_sets(path, known=None):
    """{"sets": {name: [tool]}, "statuses": [...], "columns": [...]} from a
    .qstools file. Raises ToolSetError when it isn't one."""
    try:
        if os.path.getsize(path) > 2_000_000:
            raise ToolSetError("That file is too big to be a tool set.")
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        if isinstance(e, ToolSetError):
            raise
        raise ToolSetError("That file can't be read as a tool set.") \
            from None
    if not isinstance(data, dict) or data.get("format") != FORMAT or \
            not isinstance(data.get("sets"), dict):
        raise ToolSetError("That file isn't a QuantiSheet tool set.")
    sets = {}
    for name, items in list(data["sets"].items())[:50]:
        name = str(name).strip()[:60]
        if not name or not isinstance(items, list):
            continue
        tools = [t for t in (clean_tool(x, known) for x in items[:200]) if t]
        if tools:
            sets[name] = tools
    if not sets:
        raise ToolSetError("That tool set file has no tools in it.")
    out = {"sets": sets}
    st = data.get("statuses")
    if isinstance(st, list):
        out["statuses"] = [str(x).strip()[:40] for x in st[:50]
                           if str(x).strip()]
    cols = data.get("columns")
    if isinstance(cols, list):
        out["columns"] = [c for c in cols[:40] if isinstance(c, dict)]
    return out


def merge(chest, sets):
    """Put `sets` into the chest: a set with the same name is replaced, so
    everyone on the team ends up with the same tools. Saves; returns the
    set names."""
    for name, tools in sets.items():
        chest[name] = [dict(t) for t in tools]
    save(chest)
    return list(sets)
