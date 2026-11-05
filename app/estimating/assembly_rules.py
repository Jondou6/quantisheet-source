"""Assembly Rules (r36 v2 step 7, G1.1 / G1.5): YOUR rules file turns
takeoff groups into assemblies in one go - after an AI Takeoff, say.

    {"version": 1, "rules": [
      {"group": "Wall Type *", "type": "length", "assembly": "wall legend",
       "waste": {"Board": 10, "Studs": 5}},
      {"group": "re:\\\\blvt\\\\b", "type": "area",
       "assembly": "Flooring - Resilient (LVT/VCT)", "props": {"Waste": 8}},
      {"group": "*ceiling*", "assembly": {"measure": "area", "parts": [
          {"name": "Tile", "unit": "ea", "qty": "ceil(Area/4)"}]}}]}

  group     the takeoff group's name: exact (any case), a * ? pattern, or
            "re:" and a regular expression (searched, any case);
  type      optional: length, area or count;
  assembly  an assembly's name (your library, the built-ins, the
            catalogs), an assembly written in the rule, or "wall legend"
            (the wall type's assembly from the drawing set's legend, see
            wall_legends.py);
  props     property overrides (Height, Spacing, Waste ...);
  waste     Waste % per part: {"part name": %} - each part's quantity is
            multiplied by (1 + Waste_<part>/100).

The first rule that matches a group wins. Apply shows a preview first;
groups something already prices are left alone; groups no rule matches
are listed for review (nothing is dropped). The assembly is copied into
the job under the group's name - 0.13.9's own binding - in one write
(one Undo).

No bundled prices (G1.5): a built-in or shipped catalog assembly is
copied with every part's cost and labor hours at 0, and says so; your
own library assemblies (and catalogs you imported) keep their numbers.
QuantiSheet never makes or changes the price database here.
"""
import copy
import fnmatch
import json
import os
import re

from . import _io, safedb

RULES_FILE = "assembly_rules.json"
TYPES = ("length", "area", "count")
LEGEND = "wall legend"


class RulesError(ValueError):
    """The rules file can't be used."""


# ---- the rules file ---------------------------------------------------------

def validate(data):
    """The rules, checked; RulesError naming the rule otherwise."""
    if not isinstance(data, dict) or not isinstance(data.get("rules"), list):
        raise RulesError('Not an assembly rules file (it needs a "rules" '
                         "list).")
    out = []
    for i, r in enumerate(data["rules"], start=1):
        where = f"Rule {i}"
        if not isinstance(r, dict):
            raise RulesError(f"{where} is not a rule.")
        g = str(r.get("group") or "").strip()
        if not g:
            raise RulesError(f"{where} has no group name or pattern.")
        if g.lower().startswith("re:"):
            try:
                re.compile(g[3:], re.I)
            except re.error as e:
                raise RulesError(f"{where}: bad pattern {g!r} ({e})") from e
        t = str(r.get("type") or "").strip().lower()
        if t and t not in TYPES:
            raise RulesError(f"{where}: type must be length, area or count "
                             f"(not {t!r}).")
        a = r.get("assembly")
        if not a or not (isinstance(a, str) or (isinstance(a, dict) and
                                                a.get("parts"))):
            raise RulesError(f"{where} names no assembly.")
        for k, label in (("props", "property"), ("waste", "waste")):
            v = r.get(k) or {}
            if not isinstance(v, dict):
                raise RulesError(f"{where}: {label} values must be a list "
                                 "of name: number.")
            for name, num in v.items():
                try:
                    float(num)
                except (TypeError, ValueError):
                    raise RulesError(f"{where}: {label} {name!r} must be a "
                                     f"number (not {num!r}).") from None
        out.append({"group": g, "type": t, "assembly": copy.deepcopy(a),
                    "props": dict(r.get("props") or {}),
                    "waste": dict(r.get("waste") or {}),
                    "note": str(r.get("note") or "")[:200]})
    return {"version": 1, "rules": out}


def default_path():
    return _io.data_file(RULES_FILE)


def load(path=None):
    p = path or default_path()
    try:
        data = _io.read_json(p)
    except FileNotFoundError:
        raise RulesError(f"No rules file at {p} - write the example rules "
                         "file first, then edit it.") from None
    except (OSError, ValueError) as e:
        raise RulesError(f"{os.path.basename(p)} can't be read: {e}") from e
    return validate(data)


def save(rules, path=None):
    p = _io.check_user_path(path or default_path())
    validate(rules)
    _io.backup_file(p)
    _io.write_json(p, rules)
    return p


def example_rules():
    """EXAMPLE rules to start from - no prices in them."""
    note = "EXAMPLE - check the pattern and set your own waste"
    return {"version": 1, "rules": [
        {"group": "Wall Type *", "type": "length", "assembly": LEGEND,
         "waste": {"Board": 10, "Studs": 5, "Track": 5}, "note": note},
        {"group": "re:\\b(lvt|vct|resilient)\\b", "type": "area",
         "assembly": "Flooring - Resilient (LVT/VCT)", "props": {"Waste": 8},
         "note": note},
        {"group": "re:\\b(act|acoustic|ceiling)\\b", "type": "area",
         "assembly": "Ceiling - 2x2 ACT", "note": note},
        {"group": "re:\\b(interior wall|partition)\\b", "type": "length",
         "assembly": "Interior Wall - 3-5/8\" Metal Stud", "note": note},
    ]}


# ---- matching ------------------------------------------------------------------

def matches(rule, name, mtype):
    if rule["type"] and rule["type"] != mtype:
        return False
    g = rule["group"]
    if g.lower().startswith("re:"):
        return re.search(g[3:], name, re.I) is not None
    if any(c in g for c in "*?["):
        return fnmatch.fnmatchcase(name.lower(), g.lower())
    return name.strip().lower() == g.lower()


def _own_names():
    """Names of YOUR assemblies: your library file and the catalogs you
    imported (they carry a source); the rest ships with QuantiSheet."""
    from .. import assemblies
    names = set()
    try:
        with open(assemblies.LIBRARY_PATH, encoding="utf-8") as f:
            names |= {a.get("name") for a in json.load(f)
                      if isinstance(a, dict)}
    except (OSError, ValueError):
        pass
    return names


def _with_waste(a, waste):
    """Per-part waste: Waste_<part> properties (set, or added and used).
    Returns the parts the assembly doesn't have (a pattern rule covers
    many groups - "Wall Type *" - and not every wall type has board)."""
    from .. import assemblies
    missing = []
    props = a.setdefault("props", {})
    by = {assemblies.var_name(p.get("name", "")): p for p in a["parts"]}
    for name, pct in waste.items():
        key = f"Waste_{name}"
        have = {k.lower(): k for k in props}
        if key.lower() in have:
            props[have[key.lower()]] = float(pct)
            continue
        part = by.get(assemblies.var_name(name))
        if part is None:
            missing.append(name)
            continue
        vk = "Waste_" + assemblies.var_name(name)
        props[vk] = float(pct)
        part["qty"] = f"({part['qty']})*(1+{vk}/100)"
    return missing


def _zero(a):
    for p in a.get("parts") or []:
        p["cost"] = 0.0
        p["labor"] = 0.0
    a["source"] = (a.get("source") + "; " if a.get("source") else "") + \
        "sample prices removed - price it from your cost book"
    return a


@safedb.read_only
def preview(doc, rules, legend=None, job=None):
    """What Apply would do: {"rows": [{group, type, unit, rule, assembly,
    status ('apply', 'priced', 'needs review', 'error'), why, zeroed,
    new}], "counts"}. Nothing is written."""
    from .. import assemblies, estimate
    from . import checks
    rules = validate(rules)
    lib = assemblies.library()
    own = _own_names()
    priced = checks.priced_groups(doc, job)
    leg = {t["name"].lower(): t for t in (legend or {}).get("types") or []}
    rows = []
    for g in estimate.lines(doc):
        key = (g["name"], g["type"], g["unit"])
        row = {"group": g["name"], "type": g["type"], "unit": g["unit"],
               "rule": None, "assembly": "", "status": "needs review",
               "why": "no rule matches this group", "zeroed": False,
               "new": None}
        rows.append(row)
        if key in priced:
            row.update(status="priced", why="already priced - left alone")
            continue
        for i, r in enumerate(rules["rules"], start=1):
            if matches(r, g["name"], g["type"]):
                row["rule"] = i
                _build(row, r, g, lib, own, leg)
                break
    counts = {k: sum(1 for x in rows if x["status"] == k)
              for k in ("apply", "priced", "needs review", "error")}
    return {"rows": rows, "counts": counts}


def _build(row, r, g, lib, own, leg):
    a = r["assembly"]
    try:
        if isinstance(a, dict):
            new, label, zero = copy.deepcopy(a), "(written in the rule)", \
                False
        elif a.strip().lower() == LEGEND:
            t = leg.get(g["name"].lower())
            if t is None:
                raise RulesError("the wall-type legend has no type for "
                                 "this group")
            new, label, zero = copy.deepcopy(t["assembly"]), \
                f"wall legend ({t['status']})", False
        else:
            src = lib.get(a) or next((v for k, v in lib.items()
                                      if k.lower() == a.lower()), None)
            if src is None:
                raise RulesError(f"no such assembly {a!r}")
            new, label = copy.deepcopy(src), src["name"]
            zero = src["name"] not in own and not src.get("source")
        m = new.get("measure")
        if m in TYPES and m != g["type"]:
            raise RulesError(f"{label} is a {m} assembly; the group is "
                             f"{g['type']}")
        new.setdefault("props", {}).update(
            {k: float(v) for k, v in r["props"].items()})
        missing = _with_waste(new, r["waste"])
        if zero:
            _zero(new)
        new["name"] = g["name"]
        new.setdefault("measure", g["type"])
        new["rule"] = row["rule"]
        why = ["sample prices set to 0"] if zero else []
        if missing:
            why.append("waste not used for " + ", ".join(missing) +
                       " (not a part of this assembly; its parts are: " + ", ".join(
                           p.get("name", "") for p in new["parts"]) + ")")
        row.update(assembly=label, status="apply", zeroed=zero, new=new,
                   why="; ".join(why))
    except RulesError as e:
        row.update(assembly=a if isinstance(a, str) else "(in the rule)",
                   status="error", why=str(e))


def apply(doc, pv, job=None):
    """Bind the previewed 'apply' rows - one write (one Undo). Returns
    how many groups got an assembly; already-priced groups are skipped."""
    from .. import assemblies
    from . import checks
    priced = checks.priced_groups(doc, job)
    ajob = assemblies.read_job(doc)
    n = 0
    for r in pv["rows"]:
        if r["status"] != "apply" or r["new"] is None:
            continue
        if (r["group"], r["type"], r["unit"]) in priced:
            continue
        ajob["assemblies"][r["group"]] = copy.deepcopy(r["new"])
        n += 1
    if n:
        assemblies.write_job(doc, ajob)
    return n
