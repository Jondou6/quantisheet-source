"""Saved estimate layouts: named views of the SAME estimate lines,
regrouped and re-totalled.

The estimate is what Export My Estimate collects (estimate_export.collect:
assemblies, priced takeoff lines, added Estimate panel lines) plus, on
top of that direct cost:
  * the job's markups as set in Create Proposal (saved in the PDF; none
    until the proposal details have been saved): general conditions, sales
    tax on material, overhead, profit, insurance, contingency, escalation
    and bond - each one cents of its basis, in the bid build-up's order
    (trade margins are per proposal trade and are not in layouts),
  * the location adjustment, when the cost book module gives one (the
    same amount Export My Estimate shows).

    grand total = direct cost + markups + location adjustment

A layout only changes how that is shown: what the lines are grouped by
(CSI division, CSI section, cost type, bid item / trade, source, a tag of
your own, or nothing), which columns show, subtotals on or off, the sort
order, filters (a division range, cost types) and whether the markups and
adjustments are listed as lines at the bottom or spread into the lines.
Whatever it shows, every layout adds up to the same grand total to the
cent: lines a filter hides are one "Not shown (filtered out)" line, and a
spread amount is shared out in whole cents (largest remainder) so the
shares add up to it exactly.

Your own layouts and the tags are saved inside the PDF (embedded file
quantisheet_estimate_layouts.json) so they travel with the job; layouts can
be saved to a small JSON file and loaded into another job.
"""
import copy
import json
import logging
from decimal import Decimal

from . import csi, dmoney, embfiles
from .dmoney import c2 as _c2

log = logging.getLogger(__name__)

FILE = "quantisheet_estimate_layouts.json"
VERSION = 1
EXPORT_KIND = "quantisheet-estimate-layouts"
MAX_LAYOUTS = 100
MAX_TAGS = 5000
Z = Decimal("0.00")
TYPES = ("Material", "Labor", "Equipment", "Subcontract", "Allowance",
         "Other")
UNCODED = "Uncoded"

GROUP_BY = {"division": "CSI division", "section": "CSI section",
            "cost_type": "Cost type", "trade": "Bid item / trade",
            "source": "Source", "tag": "Custom tag", "none": "No grouping"}
COLUMNS = {"code": "Code", "source": "Source", "qty": "Quantity",
           "unit": "Unit", "unit_cost": "Unit Cost",
           "Material": "Material", "Labor": "Labor",
           "Equipment": "Equipment", "Subcontract": "Subcontract",
           "Allowance": "Allowance", "Other": "Other",
           "budget": "Budget / Allowance", "subcontract": "Subcontract",
           "takeoff": "Takeoff Priced", "adds": "Markups",
           "total": "Total"}
# a cost type column and the "Subcontract" of Budget vs Sub vs Takeoff
# share a word; the second is its own key
MONEY = set(TYPES) | {"budget", "subcontract", "takeoff", "adds", "total"}
SORTS = {"code": "By code", "desc": "By description",
         "total_desc": "Largest first", "total_asc": "Smallest first",
         "none": "As entered"}
ADJUST = {"lines": "List them as lines", "spread": "Spread into the lines"}
SOURCE_LABEL = {"assembly": "Assemblies", "takeoff": "Priced takeoff",
                "added": "Estimate lines"}
NOT_SHOWN = "Not shown (filtered out)"
TEXT_MAX = 80


class LayoutError(ValueError):
    pass


class LayoutStoreDamaged(LayoutError):
    """The layouts saved in this PDF can't be read. Nothing is written over
    them; keep_damaged_copy() keeps their bytes under another name and lets
    the job start a fresh layouts store."""

    def __init__(self, msg=None):
        super().__init__(msg or DAMAGED_MESSAGE)


DAMAGED_MESSAGE = (
    "The estimate layouts and tags saved in this PDF can't be read (the "
    "stored data is damaged), so nothing was saved: saving now would "
    "replace them. The damaged data is still in the PDF; open an earlier "
    "copy of the PDF, or keep a damaged copy to set it aside and start "
    "fresh.")


# ---- a layout ---------------------------------------------------------------

def _text(v, n=TEXT_MAX):
    return " ".join(str(v if v is not None else "").split())[:n]


def _div2(v):
    """'3' / '03' / '03 30 00' -> '03'; '' for blank or not a division."""
    t = _text(v, 12)
    if not t:
        return ""
    c = csi.parse_code(t)
    d = c[:2] if c else (t.zfill(2) if t.isdigit() and len(t) <= 2 else "")
    return d if d in csi.DIVISIONS else ""


def normalize(layout):
    """A layout dict with every setting present and of its kind (anything
    unknown falls back to the default)."""
    lay = dict(layout or {})
    cols = []
    for c in lay.get("columns") or []:
        c = str(c)
        if c in COLUMNS and c not in cols:
            cols.append(c)
    f = lay.get("filters") if isinstance(lay.get("filters"), dict) else {}
    types = [t for t in (f.get("cost_types") or []) if t in TYPES]
    out = {"name": _text(lay.get("name")) or "Layout",
           "group_by": lay.get("group_by") if lay.get("group_by") in
           GROUP_BY else "division",
           "columns": cols or ["total"],
           "detail": bool(lay.get("detail", True)),
           "subtotals": bool(lay.get("subtotals", True)),
           "sort": lay.get("sort") if lay.get("sort") in SORTS else "code",
           "filters": {"div_from": _div2(f.get("div_from")),
                       "div_to": _div2(f.get("div_to")),
                       "cost_types": types},
           "adjustments": lay.get("adjustments") if lay.get("adjustments")
           in ADJUST else "lines",
           "note": _text(lay.get("note"), 300)}
    if lay.get("builtin"):
        out["builtin"] = True
    return out


_BUILTIN = [
    {"name": "By CSI division", "group_by": "division",
     "columns": ["code", "qty", "unit", "unit_cost", "Material", "Labor",
                 "Equipment", "Subcontract", "total"],
     "note": "Every line under its CSI division, with the Mat / Lab / Eqp "
             "/ Sub split."},
    {"name": "By bid item / trade", "group_by": "trade",
     "columns": ["qty", "unit", "total"],
     "note": "Lines under their bid item (an assembly's trade, else the "
             "division)."},
    {"name": "By cost type", "group_by": "cost_type",
     "columns": ["code", "qty", "unit", "total"],
     "note": "Each line's money under Material, Labor, Equipment, "
             "Subcontract, Allowance or Other (a split line shows in "
             "each)."},
    {"name": "Budget vs Sub vs Takeoff", "group_by": "division",
     "columns": ["budget", "subcontract", "takeoff", "total"],
     "detail": False,
     "note": "Side by side per division: allowance / budget lines, "
             "subcontract money and everything priced from takeoff."},
    {"name": "Owner presentation", "group_by": "division",
     "columns": ["total"], "detail": False, "adjustments": "spread",
     "note": "One price per division with the markups and adjustments "
             "folded in."},
]


def builtins():
    return [normalize(dict(x, builtin=True)) for x in _BUILTIN]


BUILTIN_NAMES = [x["name"] for x in _BUILTIN]


def new_layout(name="My layout", **kw):
    return normalize(dict({"name": name, "group_by": "division",
                           "columns": ["qty", "unit", "total"]}, **kw))


# ---- storage (inside the PDF) -----------------------------------------------

def _blank():
    return {"layouts": [], "tags": {}, "current": ""}


def _load(doc):
    """(data, damaged): the parsed store, or (None, True) when the embedded
    file exists but can't be read as a layouts store; (None, False) when
    there is none."""
    if doc is None or FILE not in embfiles.names(doc):
        return None, False
    try:
        data = json.loads(bytes(embfiles.get(doc, FILE)).decode("utf-8"))
    except Exception:                                     # noqa: BLE001
        log.warning("could not read the estimate layouts", exc_info=True)
        return None, True
    if not isinstance(data, dict):
        log.warning("the estimate layouts store is not a JSON object")
        return None, True
    return data, False


def is_damaged(doc):
    """True when this PDF holds a layouts store that can't be read."""
    try:
        return _load(doc)[1]
    except Exception:                                     # noqa: BLE001
        log.warning("could not check the estimate layouts", exc_info=True)
        return True


def read_store(doc):
    """{"layouts": [your layouts], "tags": {line key: tag}, "current"}.
    A store that can't be read shows as empty with "damaged": True (its
    bytes stay in the PDF; write_store refuses to replace them)."""
    out = _blank()
    try:
        data, damaged = _load(doc)
    except Exception:                                     # noqa: BLE001
        log.warning("could not read the estimate layouts", exc_info=True)
        data, damaged = None, True
    if damaged:
        out["damaged"] = True
        return out
    if data is None:
        return out
    seen = set(BUILTIN_NAMES)
    for x in (data.get("layouts") or [])[:MAX_LAYOUTS]:
        if isinstance(x, dict):
            lay = normalize(dict(x, builtin=False))
            lay.pop("builtin", None)
            if lay["name"] not in seen:
                seen.add(lay["name"])
                out["layouts"].append(lay)
    tags = data.get("tags")
    if isinstance(tags, dict):
        for k, v in list(tags.items())[:MAX_TAGS]:
            t = _text(v, 60)
            if t:
                out["tags"][_text(k, 400)] = t
    out["current"] = _text(data.get("current"))
    return out


def write_store(doc, store):
    """Save `store` in the PDF. Raises LayoutStoreDamaged, writing nothing,
    when the store already in the PDF can't be read: unread data is never
    overwritten."""
    if store.get("damaged") or is_damaged(doc):
        raise LayoutStoreDamaged()
    data = {"version": VERSION,
            "layouts": [normalize(x) for x in store.get("layouts") or []],
            "tags": dict(store.get("tags") or {}),
            "current": _text(store.get("current"))}
    for x in data["layouts"]:
        x.pop("builtin", None)
    embfiles.put(doc, FILE, json.dumps(data).encode("utf-8"),
                 "QuantiSheet estimate layouts")


def damaged_name(when=None):
    """quantisheet_estimate_layouts.damaged-<YYYYMMDD-HHMMSS>.json"""
    import datetime
    when = when or datetime.datetime.now()
    return FILE[:-len(".json")] + when.strftime(".damaged-%Y%m%d-%H%M%S.json")


def keep_damaged_copy(doc, when=None):
    """Set a damaged layouts store aside: embed its bytes unchanged as
    damaged_name() and remove it from FILE so the job can save layouts
    again. Returns the copy's name, or None when there is nothing damaged.
    The copy is checked byte for byte before the original is removed."""
    if not is_damaged(doc):
        return None
    try:
        raw = bytes(embfiles.get(doc, FILE))
    except Exception as e:                                # noqa: BLE001
        raise LayoutError("Couldn't read the damaged layouts to keep a "
                          f"copy ({e}); nothing was changed.")
    name = damaged_name(when)
    taken = set(embfiles.names(doc))
    n = 1
    base_name = name
    while name in taken:
        n += 1
        name = base_name[:-len(".json")] + f"-{n}.json"
    embfiles.put(doc, name, raw, "QuantiSheet estimate layouts (damaged "
                 "copy, kept as found)")
    if bytes(embfiles.get(doc, name)) != raw:
        raise LayoutError("Couldn't keep a copy of the damaged layouts; "
                          "nothing was changed.")
    embfiles.delete(doc, FILE)
    return name


def layouts(doc=None):
    """The built-in layouts, then the job's own."""
    return builtins() + read_store(doc)["layouts"]


def find(doc, name):
    return next((x for x in layouts(doc) if x["name"] == name), None)


def save_layout(doc, layout):
    """Add or replace (by name) one of the job's layouts."""
    lay = normalize(layout)
    lay.pop("builtin", None)
    if lay["name"] in BUILTIN_NAMES:
        raise LayoutError(f"{lay['name']!r} is a built-in layout; give "
                          "yours another name.")
    store = read_store(doc)
    rest = [x for x in store["layouts"] if x["name"] != lay["name"]]
    if len(rest) >= MAX_LAYOUTS:
        raise LayoutError(f"A job holds at most {MAX_LAYOUTS} layouts.")
    store["layouts"] = rest + [lay]
    write_store(doc, store)
    return lay


def delete_layout(doc, name):
    store = read_store(doc)
    if store.get("damaged"):
        raise LayoutStoreDamaged()
    keep = [x for x in store["layouts"] if x["name"] != name]
    if len(keep) == len(store["layouts"]):
        return False
    store["layouts"] = keep
    write_store(doc, store)
    return True


def tags(doc):
    return read_store(doc)["tags"]


def set_tag(doc, key, tag):
    """Tag one estimate line (its key from estimate_export.collect);
    blank clears it."""
    store = read_store(doc)
    t = _text(tag, 60)
    key = _text(key, 400)
    if t:
        if key not in store["tags"] and len(store["tags"]) >= MAX_TAGS:
            raise LayoutError(f"At most {MAX_TAGS} tagged lines.")
        store["tags"][key] = t
    else:
        store["tags"].pop(key, None)
    write_store(doc, store)


def set_current(doc, name):
    store = read_store(doc)
    if store["current"] != name:
        store["current"] = _text(name)
        write_store(doc, store)


# ---- share between jobs (a small JSON file) ---------------------------------

def to_json(items):
    data = {"kind": EXPORT_KIND, "version": VERSION,
            "layouts": []}
    for x in items:
        lay = normalize(x)
        lay.pop("builtin", None)
        data["layouts"].append(lay)
    return json.dumps(data, indent=1)


def from_json(text):
    """The layouts in a layouts file (LayoutError when it isn't one)."""
    try:
        data = json.loads(text)
    except (TypeError, ValueError) as e:
        raise LayoutError(f"Not a layouts file: {e}")
    if isinstance(data, dict) and data.get("kind") == EXPORT_KIND:
        rows = data.get("layouts")
    else:
        raise LayoutError("Not a QuantiSheet estimate layouts file.")
    if not isinstance(rows, list):
        raise LayoutError("The file has no layouts.")
    out = []
    for x in rows[:MAX_LAYOUTS]:
        if isinstance(x, dict):
            lay = normalize(dict(x, builtin=False))
            lay.pop("builtin", None)
            out.append(lay)
    return out


def export_file(path, items):
    with open(path, "w", encoding="utf-8") as f:
        f.write(to_json(items))
    return path


def import_file(doc, path):
    """Load a layouts file into the job; returns the names added. A name
    that is a built-in's gets " (imported)"; one of the job's own is
    replaced."""
    with open(path, encoding="utf-8") as f:
        items = from_json(f.read(1_000_000))
    store = read_store(doc)
    names = []
    for lay in items:
        name = lay["name"]
        while name in BUILTIN_NAMES:
            name = _text(f"{name} (imported)")
        lay["name"] = name
        store["layouts"] = [x for x in store["layouts"]
                            if x["name"] != name] + [lay]
        names.append(name)
    store["layouts"] = store["layouts"][-MAX_LAYOUTS:]
    write_store(doc, store)
    return names


# ---- the estimate: direct cost, markups, location adjustment ---------------

RATE_STEPS = (("gc", "General conditions", "direct"),
              ("tax", "Sales tax on material", "material"),
              ("overhead", "Overhead", "subtotal"),
              ("profit", "Profit", "subtotal"),
              ("insurance", "Insurance", "subtotal"),
              ("contingency", "Contingency", "subtotal"),
              ("escalation", "Escalation", "subtotal"))


def _rate(v):
    if v in (None, "") or dmoney.bad(v):
        return Decimal(0)
    d = dmoney.D(v)
    return d if d.is_finite() and abs(d) < 1000 else Decimal(0)


def job_markups(doc):
    """The job's markup rates (%) as saved in Create Proposal, or {} when
    the proposal details were never saved (no markups)."""
    if doc is None:
        return {}
    try:
        from . import proposal
        if proposal.JOB_FILE not in embfiles.names(doc):
            return {}
        data = proposal.read(doc)
    except Exception:                                     # noqa: BLE001
        log.warning("proposal markups unavailable", exc_info=True)
        return {}
    out = {k: data.get(k) for k, _l, _b in RATE_STEPS}
    out["bond"] = data.get("bond") or "none"
    out["bond_rate"] = data.get("bond_rate")
    return out


def markups(direct, material, rates):
    """[{key, label, rate, basis, amount}] - each step cents of its basis:
    general conditions on the direct cost, tax on material, the rest on
    the running subtotal, bond on the final amount."""
    rates = rates or {}
    steps, running = [], dmoney.cents(direct)
    for key, label, basis in RATE_STEPS:
        r = _rate(rates.get(key))
        if not r:
            continue
        b = direct if basis == "direct" else material if \
            basis == "material" else running
        amt = dmoney.cents(dmoney.D(b) * r / 100)
        if not amt:
            continue
        steps.append({"key": key, "label": f"{label} ({r.normalize():f}%)",
                      "rate": r, "basis": basis, "amount": amt})
        running += amt
    mode = str(rates.get("bond") or "none")
    if mode in ("auto", "fixed") and running > 0:
        from . import bidbuild
        if mode == "fixed":
            flat = _rate(rates.get("bond_rate")) / 100
            amt = dmoney.cents(running * flat / (1 - flat)) if \
                0 < flat < 1 else Z
            label = f"Bond ({(flat * 100).normalize():f}%)"
        else:
            s = float(running)
            prem = bidbuild.bond_premium(s)
            for _ in range(20):
                nxt = bidbuild.bond_premium(s + prem)
                if abs(nxt - prem) < 0.005:
                    prem = nxt
                    break
                prem = nxt
            amt = dmoney.cents(prem)
            label = "Bond"
        if amt:
            steps.append({"key": "bond", "label": label, "rate": None,
                          "basis": "subtotal", "amount": amt})
    return steps


def _location(doc, direct, types):
    """(label, Decimal) of the location adjustment Export My Estimate shows,
    or None."""
    from . import estimate_lines
    try:
        rows = estimate_lines.location_lines(
            direct, types.get("Material", Z), types.get("Labor", Z),
            types.get("Equipment", Z), estimate_lines.job_region(doc))
    except Exception:                                     # noqa: BLE001
        log.warning("location adjustment left out", exc_info=True)
        return None
    if not rows or len(rows) < 2:
        return None
    amt = dmoney.cents(rows[-1][1]) - dmoney.cents(rows[0][1])
    label = rows[1][0] if len(rows) == 3 else "Location adjustment"
    return (label, amt) if amt else None


def base(doc=None, lines=None, rates=None, location=None):
    """{"lines", "direct", "types", "adjustments": [{key, label, basis,
    amount}], "total"}. `lines` (estimate_export.collect rows), `rates`
    (markup %) and `location` ((label, amount), or False for none) are
    read from the job when not given."""
    from . import estimate_export
    if lines is None:
        lines = estimate_export.collect(doc) if doc is not None else []
    direct = sum((ln["total"] for ln in lines), Z)
    types = {}
    for ln in lines:
        for k, v in ln["by_type"].items():
            types[k] = types.get(k, Z) + v
    if rates is None:
        rates = job_markups(doc)
    adj = markups(direct, types.get("Material", Z), rates)
    if location is None:
        location = _location(doc, direct, types) if doc is not None \
            else None
    if location:
        label, amt = location
        amt = dmoney.cents(amt)
        if amt:
            adj.append({"key": "location", "label": str(label),
                        "basis": "location", "amount": amt})
    total = direct + sum((a["amount"] for a in adj), Z)
    return {"lines": lines, "direct": direct, "types": types,
            "adjustments": adj, "total": total}


# ---- the view ----------------------------------------------------------------

def allocate(amount, weights):
    """`amount` (cents) shared over `weights` in whole cents that add up
    to it exactly (largest remainder; ties to the first). Equal shares
    when every weight is 0."""
    n = len(weights)
    if not n:
        return []
    amount = dmoney.cents(amount)
    ws = [abs(dmoney.D(w)) for w in weights]
    tot = sum(ws, Decimal(0))
    if not tot:
        ws, tot = [Decimal(1)] * n, Decimal(n)
    sign = -1 if amount < 0 else 1
    whole = int((abs(amount) * 100).to_integral_value())
    raw = [Decimal(whole) * w / tot for w in ws]
    got = [int(r) for r in raw]                  # floor: all positive
    left = whole - sum(got)
    order = sorted(range(n), key=lambda i: (-(raw[i] - got[i]), i))
    for i in order[:left]:
        got[i] += 1
    return [(Decimal(sign * g) / 100).quantize(Decimal("0.01"))
            for g in got]


def _kind(by_type):
    keys = [k for k, v in by_type.items() if v]
    return keys[0] if len(keys) == 1 else ("Mixed" if keys else "Other")


def _pieces(lines, explode, tags):
    out = []
    for i, ln in enumerate(lines):
        common = {"code": ln.get("code", ""), "desc": ln.get("desc", ""),
                  "source": ln.get("source", ""),
                  "qty": dmoney.D(ln.get("qty")), "unit": ln.get("unit", ""),
                  "division": ln.get("division", ""),
                  "title": ln.get("title", UNCODED),
                  "trade": ln.get("trade") or "General",
                  "key": ln.get("key", ""), "order": i,
                  "tag": tags.get(ln.get("key", ""), "")}
        bt = {k: v for k, v in ln["by_type"].items() if v}
        if explode and bt:
            for k in TYPES:
                if k in bt:
                    q = common["qty"]
                    out.append(dict(common, by_type={k: bt[k]}, kind=k,
                                    total=bt[k], unit_cost=(bt[k] / q)
                                    .quantize(Decimal("0.0001")) if q
                                    else Decimal(0)))
        else:
            out.append(dict(common, by_type=bt, kind=_kind(bt),
                            total=ln["total"],
                            unit_cost=dmoney.D(ln.get("unit_cost"))))
    return out


def _keep(p, f):
    lo, hi = f.get("div_from"), f.get("div_to")
    if lo or hi:
        d = p["division"]
        if not d or (lo and d < lo) or (hi and d > hi):
            return False
    types = f.get("cost_types")
    if types and p["kind"] not in types:
        return False
    return True


def _group(p, how):
    """(sort key, label) of the group a piece goes in."""
    if how == "division":
        d = p["division"]
        return ((d == "", d), f"Division {d} - {p['title']}" if d
                else UNCODED)
    if how == "section":
        c = csi.parse_code(p["code"] or "")
        sec = c[:8] if c else ""
        if not sec:
            return ((True, ""), UNCODED)
        return ((False, sec), f"{sec} - {p['title']}")
    if how == "cost_type":
        k = p["kind"]
        i = TYPES.index(k) if k in TYPES else len(TYPES)
        return ((i, k), k)
    if how == "trade":
        t = p["trade"] or "General"
        return ((t.lower(), t), t)
    if how == "source":
        s = p["source"]
        order = list(SOURCE_LABEL)
        return ((order.index(s) if s in order else 9, s),
                SOURCE_LABEL.get(s, s or "Other"))
    if how == "tag":
        t = p["tag"]
        return ((t == "", t.lower()), t or "(untagged)")
    return ((0,), "All lines")


def _sort_key(how):
    if how == "desc":
        return lambda r: (r["desc"].lower(), r["order"])
    if how == "total_desc":
        return lambda r: (-r["value"]["total"], r["order"])
    if how == "total_asc":
        return lambda r: (r["value"]["total"], r["order"])
    if how == "none":
        return lambda r: r["order"]
    return lambda r: (r["code"] == "", r["code"], r["desc"].lower(),
                      r["order"])


def _values(p, cols):
    bt = p["by_type"]
    adds = p.get("adds", Z)
    budget = bt.get("Allowance", Z)
    sub = bt.get("Subcontract", Z)
    v = {k: bt.get(k, Z) for k in TYPES}
    v.update({"budget": budget, "subcontract": sub,
              "takeoff": p["total"] - budget - sub, "adds": adds,
              "total": p["total"] + adds})
    return v


def render(layout, b, tags=None):
    """The estimate `b` (base()) shown by `layout`:

    {"name", "layout", "columns": [(key, label)], "groups": [{"label",
    "rows": [{key: value, "desc"}], "subtotal": {money key: Decimal},
    "count"}], "adjustments": [(label, Decimal)] (listed, not spread),
    "not_shown": (label, Decimal) or None, "column_totals", "direct",
    "total", "notes"}

    The groups' totals + the listed adjustments + the not-shown line
    always equal b["total"]."""
    lay = normalize(layout)
    tags = tags or {}
    f = lay["filters"]
    explode = lay["group_by"] == "cost_type" or bool(f["cost_types"])
    pieces = _pieces(b["lines"], explode, tags)
    for p in pieces:
        p["adds"] = Z
    notes = []
    listed = []
    spread = lay["adjustments"] == "spread"
    for a in b["adjustments"]:
        if not spread or not pieces:
            listed.append((a["label"], a["amount"]))
            continue
        if a["basis"] == "material":
            w = [p["by_type"].get("Material", Z) for p in pieces]
        elif a["basis"] == "location":
            w = [sum((p["by_type"].get(k, Z) for k in
                      ("Material", "Labor", "Equipment")), Z)
                 for p in pieces]
        elif a["basis"] == "direct":
            w = [p["total"] for p in pieces]
        else:
            w = [p["total"] + p["adds"] for p in pieces]
        if not any(w):
            w = [p["total"] + p["adds"] for p in pieces]
        for p, share in zip(pieces, allocate(a["amount"], w)):
            p["adds"] += share
    if spread and b["adjustments"] and pieces:
        notes.append("Spread into the lines: " + ", ".join(
            a["label"] for a in b["adjustments"]) + ".")
    shown = [p for p in pieces if _keep(p, f)]
    hidden = [p for p in pieces if not _keep(p, f)]
    groups = {}
    for p in shown:
        k, label = _group(p, lay["group_by"])
        g = groups.setdefault(k, {"label": label, "rows": [], "count": 0,
                                  "subtotal": {}})
        row = {"code": p["code"], "desc": p["desc"],
               "source": SOURCE_LABEL.get(p["source"], p["source"]),
               "qty": p["qty"], "unit": p["unit"],
               "unit_cost": p["unit_cost"], "order": p["order"],
               "value": _values(p, lay["columns"]), "key": p["key"],
               "tag": p["tag"]}
        g["rows"].append(row)
        g["count"] += 1
        for m in MONEY:
            g["subtotal"][m] = g["subtotal"].get(m, Z) + row["value"][m]
    out_groups = []
    for k in sorted(groups):
        g = groups[k]
        g["rows"].sort(key=_sort_key(lay["sort"]))
        out_groups.append(g)
    if lay["sort"] in ("total_desc", "total_asc") and not lay["detail"]:
        out_groups.sort(key=lambda g: g["subtotal"]["total"],
                        reverse=lay["sort"] == "total_desc")
    not_shown = None
    if hidden:
        amt = sum((p["total"] + p["adds"] for p in hidden), Z)
        not_shown = (NOT_SHOWN, amt)
        notes.append(f"{len(hidden)} line(s) left out by the filters are "
                     "one line so the total still matches.")
    col_tot = {m: sum((g["subtotal"].get(m, Z) for g in out_groups), Z)
               for m in MONEY}
    total = col_tot["total"] + sum((v for _l, v in listed), Z) + \
        (not_shown[1] if not_shown else Z)
    if total != b["total"]:                     # never: say so, loudly
        log.error("layout %r totals %s, the estimate %s", lay["name"],
                  total, b["total"])
    return {"name": lay["name"], "layout": lay,
            "columns": [(c, COLUMNS[c]) for c in lay["columns"]],
            "groups": out_groups, "adjustments": listed,
            "not_shown": not_shown, "column_totals": col_tot,
            "direct": b["direct"], "total": total,
            "estimate_total": b["total"], "notes": notes}


def view(doc, layout, b=None):
    """render() for the job (its lines, markups, location and tags)."""
    b = b if b is not None else base(doc)
    return render(layout, b, tags(doc) if doc is not None else {})


def cell(row_or_totals, key):
    """Display text of one cell of a view row ({"value": ...}) or of a
    group subtotal / column totals dict."""
    if "value" in row_or_totals:
        if key in MONEY:
            return dmoney.fmt(row_or_totals["value"][key])
        v = row_or_totals.get(key, "")
        if key == "qty":
            q = dmoney.D(v)
            return f"{_c2(q):,.2f}" if q else ""
        if key == "unit_cost":
            d = dmoney.D(v)
            if not d:
                return ""
            places = 2 if d == d.quantize(Decimal("0.01")) else 4
            q = d.quantize(Decimal(1).scaleb(-places))
            return f"{'-' if q < 0 else ''}${abs(q):,.{places}f}"
        return str(v or "")
    if key in MONEY:
        return dmoney.fmt(row_or_totals.get(key, Z))
    return ""


def flat_rows(v):
    """The view as a list of (kind, label, {column key: text}) rows - kind
    "group", "line", "subtotal", "adjustment", "not_shown", "total" - in
    the order they're shown (the screen table and the CSV use it)."""
    lay = v["layout"]
    keys = [k for k, _l in v["columns"]]
    out = []
    one_line = not lay["detail"]
    for g in v["groups"]:
        if one_line:
            out.append(("subtotal", g["label"],
                        {k: cell(g["subtotal"], k) for k in keys}))
            continue
        out.append(("group", g["label"], {}))
        for r in g["rows"]:
            label = r["desc"] or r["code"] or "(no description)"
            out.append(("line", label, {k: cell(r, k) for k in keys}))
        if lay["subtotals"]:
            out.append(("subtotal", f"Subtotal - {g['label']}",
                        {k: cell(g["subtotal"], k) for k in keys}))
    # the amount of a not-shown / adjustment / total line is under
    # "total" even when the layout hides that column (writers put it in
    # the last column then)
    if v["not_shown"]:
        out.append(("not_shown", v["not_shown"][0],
                    {"total": dmoney.fmt(v["not_shown"][1])}))
    if v["adjustments"]:
        out.append(("subtotal", "Direct cost",
                    {"total": dmoney.fmt(v["direct"])}))
        for label, amt in v["adjustments"]:
            out.append(("adjustment", label, {"total": dmoney.fmt(amt)}))
    out.append(("total", "Grand total", {"total": dmoney.fmt(v["total"])}))
    return out


def copy_layout(layout, name):
    lay = copy.deepcopy(normalize(layout))
    lay.pop("builtin", None)
    lay["name"] = _text(name) or lay["name"]
    return lay
