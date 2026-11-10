"""Count library (Nov 1): the symbols a company counts on every job
(outlets, sprinkler heads, diffusers) kept once and tried on each new
plan set.

- An entry is a count name and the sample picture Count Symbol keeps
  (uncounted.save_sample) - add one from a count's right-click menu.
- The library is one JSON file. With the price database on a shared
  folder it sits beside it, so the whole office shares one library;
  otherwise it is in this PC's QuantiSheet folder. The 'count_library'
  setting can point it somewhere else.
- try_on() looks for each chosen entry on the chosen pages with the same
  whole-symbol matching Count Symbol uses (autocount.find_symbols, the
  patent design rules unchanged; the 'picture_count' switch honoured).
  Copies already counted under that name, and copies in the title block,
  schedules, legends and notes, are left out. A spot two entries both
  match is kept for the better score only.
- Nothing is counted straight away: the caller adds the hits as counts
  in review (REVIEW_METHOD), out of every total until a person accepts
  them in the Review Queue.
"""
import base64
import datetime
import json
import logging
import os
import tempfile

from . import settings
from .dmoney import c2 as _c2

log = logging.getLogger(__name__)

FILENAME = "QuantiSheet Count Library.json"
LOCAL = "count_library.json"
REVIEW_METHOD = "AI takeoff: count, from the count library (review)"
MAX_ENTRIES = 200
NAME_MAX = 80


def path():
    """Where the library file is (it may not exist yet)."""
    p = settings.get("count_library")
    if p:
        return p
    try:
        from . import pricedb
        if pricedb.is_shared():
            return os.path.join(os.path.dirname(pricedb.path()), FILENAME)
    except Exception:                                     # noqa: BLE001
        log.debug("price database location not read", exc_info=True)
    return os.path.join(settings.DIR, LOCAL)


def is_shared(p=None):
    p = os.path.normcase(os.path.abspath(p or path()))
    return not p.startswith(os.path.normcase(os.path.abspath(settings.DIR)))


def _read(p=None):
    p = p or path()
    try:
        with open(p, "r", encoding="utf-8") as f:
            d = json.load(f)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        log.warning("count library %s not read", p, exc_info=True)
        return {}
    ents = d.get("entries") if isinstance(d, dict) else None
    return ents if isinstance(ents, dict) else {}


def _write(entries, p=None):
    p = p or path()
    folder = os.path.dirname(p) or "."
    os.makedirs(folder, exist_ok=True)
    data = {"kind": "QuantiSheet count library", "version": 1,
            "entries": entries}
    fd, tmp = tempfile.mkstemp(prefix=".countlib_", suffix=".tmp", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1, sort_keys=True)
        os.replace(tmp, p)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def _clean(name):
    return " ".join((name or "").split())[:NAME_MAX]


def _who():
    try:
        from . import pricedb
        return pricedb.user()
    except Exception:                                     # noqa: BLE001
        return ""


def entries():
    """[{name, png (bytes), added, by}] sorted by name."""
    out = []
    for name, e in _read().items():
        try:
            png = base64.b64decode(e.get("png") or "")
        except (ValueError, TypeError):
            continue
        if png:
            out.append({"name": name, "png": png, "added": e.get("added", ""),
                        "by": e.get("by", ""),
                        "color": _color(e.get("color"))})
    return sorted(out, key=lambda e: e["name"].lower())


def _color(c):
    """An entry's count color [r, g, b] (0-1), or None."""
    if isinstance(c, (list, tuple)) and len(c) == 3 and all(
            isinstance(x, (int, float)) and 0 <= x <= 1 for x in c):
        return [float(x) for x in c]
    return None


def colors():
    """{name: color} of the entries that have their own color."""
    return {e["name"]: e["color"] for e in entries() if e.get("color")}


def set_color(name, color):
    """Recolor library entry `name`: its counts on the next job come in
    in this color. Returns True when changed."""
    ents = _read()
    key = next((k for k in ents if k.lower() == _clean(name).lower()), None)
    c = _color(color)
    if key is None or c is None:
        return False
    ents[key]["color"] = c
    _write(ents)
    return True


def names():
    return [e["name"] for e in entries()]


def has(name):
    return _clean(name).lower() in {n.lower() for n in _read()}


def add(name, png, color=None):
    """Keep `png` as library entry `name` (an entry of that name is
    replaced), counted in `color` on the next job. Returns the name kept.
    Raises ValueError for no name or picture, or a full library."""
    name = _clean(name)
    if not name or not png:
        raise ValueError("A count name and its sample picture are needed.")
    ents = _read()                       # read again: the file may be shared
    for k in list(ents):
        if k.lower() == name.lower():
            del ents[k]
    if len(ents) >= MAX_ENTRIES:
        raise ValueError(f"The count library is full ({MAX_ENTRIES} "
                         "symbols) - remove some first.")
    ents[name] = {"png": base64.b64encode(png).decode("ascii"),
                  "added": datetime.date.today().isoformat(), "by": _who()}
    if _color(color):
        ents[name]["color"] = _color(color)
    _write(ents)
    return name


def remove(name):
    ents = _read()
    gone = [k for k in ents if k.lower() == _clean(name).lower()]
    for k in gone:
        del ents[k]
    if gone:
        _write(ents)
    return bool(gone)


def rename(old, new):
    new = _clean(new)
    ents = _read()
    key = next((k for k in ents if k.lower() == _clean(old).lower()), None)
    if key is None or not new:
        return False
    if new.lower() != key.lower() and any(k.lower() == new.lower()
                                          for k in ents):
        raise ValueError(f"'{new}' is already in the count library.")
    ents[new] = ents.pop(key)
    _write(ents)
    return True


def add_from_drawing(doc, group, color=None):
    """Add count `group`'s saved sample (from Count Symbol) to the
    library, in `color` (default: the color its counts have here). Raises
    LookupError when the drawing has no sample for it."""
    from . import uncounted
    png = uncounted.sample(doc, group)
    if not png:
        raise LookupError(f"No sample saved for '{group}' in this drawing - "
                          "count it once with Count Symbol first.")
    if color is None:
        color = _count_color(doc, group)
    return add(group, png, color)


def _count_color(doc, group):
    from . import annotate
    for it in annotate.takeoff_items(doc):
        if it["type"] == "count" and it["group"] == group:
            for a in annotate.find_annots(doc[it["page"]], it["ref"]):
                c = annotate.markup_color(doc, a)
                if c:
                    return list(c)[:3]
    return None


def _picture_on():
    try:
        from .aitakeoff import picture_count_on
        return picture_count_on()
    except Exception:                                     # noqa: BLE001
        return True


def try_on(doc, pages=None, names_=None, threshold=0.8, progress=None,
           finder=None, plan_filter=None):
    """Look for library entries (names_ None: all) on `pages` (None: every
    page). Returns ({name: [hits]}, info) - hits {page, rect, score}
    not yet counted under that name; info {"dropped": spots won by
    another entry, "left_out": in title blocks / legends / notes,
    "already": already counted, "stopped": bool}. progress(i, n, name)
    -> False stops. Raises RuntimeError when picture counting is off."""
    if not _picture_on():
        raise RuntimeError("Counting by picture is turned off (setting "
                           "'picture_count'), so the count library can't "
                           "be used.")
    from . import autocount, count_several, uncounted
    finder = finder or autocount.find_symbols
    if plan_filter is None:
        plan_filter = autocount._in_plan_area
    want = None if names_ is None else {n.lower() for n in names_}
    chosen = [e for e in entries()
              if want is None or e["name"].lower() in want]
    pset = None if pages is None else set(pages)
    cache = {}
    results = {}
    info = {"dropped": 0, "left_out": 0, "already": 0, "stopped": False}
    for i, e in enumerate(chosen):
        if progress is not None and progress(i, len(chosen), e["name"]) \
                is False:
            info["stopped"] = True
            break
        try:
            hits = finder(doc, e["png"], threshold, pset, cache=cache)
        except Exception:                                 # noqa: BLE001
            log.info("count library entry %r skipped", e["name"],
                     exc_info=True)
            continue
        keep = []
        by_page = {}
        for h in hits:
            by_page.setdefault(h["page"], []).append(h)
        for p, hs in by_page.items():
            try:
                ok = plan_filter(doc[p], [h["rect"] for h in hs])
                ok = {tuple(_c2(v) for v in r) for r in ok}
                inside = [h for h in hs
                          if tuple(_c2(v) for v in h["rect"]) in ok]
            except Exception:                             # noqa: BLE001
                inside = hs
            info["left_out"] += len(hs) - len(inside)
            marks = uncounted.count_rects(doc, p, e["name"])
            for h in inside:
                if uncounted.is_counted(h["rect"], marks):
                    info["already"] += 1
                else:
                    keep.append(h)
        results[e["name"]] = keep
    kept, dropped = count_several.resolve_overlaps(results)
    info["dropped"] = len(dropped)
    return kept, info


def review_marks(kept, doc, colors=None):
    """Count marks (page, kind, payload) for try_on's hits: each entry its
    own count name, dashed with the AI badge, in review (REVIEW_METHOD)."""
    from . import autocount, count_several
    out = []
    for i, (name, hits) in enumerate(sorted(kept.items())):
        if not hits:
            continue
        if colors is None:
            colors = globals()["colors"]()
        col = (colors or {}).get(name) or \
            count_several.CLASS_COLORS[i % len(count_several.CLASS_COLORS)]
        for h in hits:
            h["method"] = REVIEW_METHOD
        for m in autocount.count_marks(hits, name, doc, col):
            m[2]["badge"] = True
            m[2]["dashes"] = [3, 2]
            out.append(m)
    return out
