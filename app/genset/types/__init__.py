"""The building types Generate Set knows, in one registry.

    get(key) -> BuildingType          (an unknown key reads as commercial,
                                       as every non-house plan always has)
    for_plan(plan) -> BuildingType
    keys() -> ["single_family", "small_commercial", "warehouse",
                                       "strip_retail", "restaurant"]
    detect(text) -> (key, occupancy, hits) or None
    limits(key) -> {"sf": (lo, hi), "stories": (lo, hi), "max_w", "max_d"}

detect() only answers for the newer types (those with patterns); a brief
it doesn't claim goes on to the original house / office / retail rules in
brief.py, unchanged. Adding a type: a module with TYPE = BuildingType(...)
and its line in _ORDER."""
import re

from . import commercial, house, restaurant, strip, warehouse
from .base import BuildingType

# detect() tries the newer types in this order: warehouse, then strip
# retail, then restaurant (Phase 2) - all before brief.py's retail / office
# rules. Strip before restaurant: "a 6-tenant strip center with a
# drive-thru end cap" is the strip center (the restaurant is a tenant).
_ORDER = (house.TYPE, commercial.TYPE, warehouse.TYPE, strip.TYPE,
          restaurant.TYPE)
REGISTRY = {t.key: t for t in _ORDER}
LEGACY = ("single_family", "small_commercial")

__all__ = ["BuildingType", "REGISTRY", "LEGACY", "get", "for_plan", "keys",
           "detect", "limits", "occupancies"]


def get(key):
    if not key:
        return REGISTRY["single_family"]
    return REGISTRY.get(key) or REGISTRY["small_commercial"]


def for_plan(plan):
    return get((plan.get("project") or {}).get("building_type")
               or "single_family")


def keys():
    return [t.key for t in _ORDER]


def occupancies():
    """Every occupancy label any type may carry, in registry order."""
    out = []
    for t in _ORDER:
        out += [o for o in t.occupancies if o not in out]
    return out


def limits(key):
    return get(key).limits()


def detect(text):
    """(key, occupancy, hits) for the first newer type whose words are in
    the brief, else None. `hits` lists the words found. A type whose only
    hits are its `weak` patterns (a warehouse's "tilt-up", "PEMB") gives
    way to a later type with words of its own."""
    t = text or ""
    found = []
    for tp in _ORDER:
        if not tp.patterns and tp.detect is None:
            continue
        hits, strong = [], False
        for rx in tp.patterns:
            for m in re.finditer(rx, t, re.I):
                hits.append(m.group(0).strip().lower())
                strong = strong or rx not in tp.weak
        if tp.detect is not None:
            more = [h for h in (tp.detect(t) or []) if h not in hits]
            hits += more
            strong = strong or bool(more)
        if hits:
            found.append((tp, hits, strong))
    if not found:
        return None
    tp, hits, _s = next((f for f in found if f[2]), found[0])
    occ = tp.default_occ
    for rx, grp in tp.occ_rules:
        if re.search(rx, t, re.I):
            occ = grp
            break
    return tp.key, occ, hits
