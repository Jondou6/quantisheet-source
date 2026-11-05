"""An independent check of the AI Takeoff (accuracy round 6): the same
quantity worked out a second way, from different linework, and the two
compared - as an estimator checks a takeoff before it goes out. Where
they disagree the takeoff gets a CHECK line saying so. One quantity is
changed (Jon, Oct 31): a gross floor area the room check disagrees with
goes to review instead of the totals - an outline that took in a porch
or the site is not counted unseen.

    run(res) -> [check]   each {name, a, b, unit, off (fraction), ok,
                           a_from, b_from, why}

Checks:
- interior wall length (wall-type tags on the plan) against half of the
  rooms' perimeters less the exterior wall (every interior wall bounds
  two rooms, the exterior one);
- room floor area against the building's gross area (rooms are usually
  80-95% of it - the rest is walls, shafts, chases);
- ceiling area against the floor area of the rooms that have a ceiling.
"""
import re

TOL = 0.15                    # disagreement that earns a CHECK line


def _walls_lf(res):
    """(interior LF, exterior LF) from the wall-type marks: a type whose
    legend builds siding / brick / sheathing is exterior."""
    from . import wall_assembly
    legend = {}
    for w in (res.get("walls") or {}).values():
        legend.update(w.get("legend") or {})
    inner = outer = 0.0
    for sh in (res.get("sheets") or {}).values():
        for g, v in (sh.get("walls") or {}).items():
            m = re.match(r"Wall Type (\S+)$", g)
            if m:
                kinds = {c["kind"] for c in wall_assembly.components(
                    legend.get(m.group(1), ""))}
                if kinds & {"siding", "brick", "sheathing"}:
                    continue
                inner += v
            elif g == "Exterior Walls":
                outer += v
    return inner, outer


def _check(name, a, b, unit, a_from, b_from, lo=None, hi=None):
    if not a or not b:
        return None
    off = (a - b) / b
    if lo is not None:
        ok = lo <= a / b <= hi
    else:
        ok = abs(off) <= TOL
    return {"name": name, "a": round(a, 1), "b": round(b, 1), "unit": unit,
            "off": round(off, 3), "ok": ok, "a_from": a_from,
            "b_from": b_from}


def run(res):
    out = []
    fin = res.get("finishes") or {}
    rooms = fin.get("rooms") or []
    perim = sum((r.get("base_lf") or 0.0) + (r.get("door_lf") or 0.0)
                for r in rooms)
    inner, ext = _walls_lf(res)
    if perim and ext:
        from_rooms = max(0.0, (perim - ext) / 2.0)
        c = _check("Interior wall length", inner, from_rooms, "LF",
                   "wall-type tags on the plan",
                   f"half the room perimeters ({perim:,.0f} LF) less the "
                   f"exterior wall ({ext:,.0f} LF)")
        if c:
            out.append(c)
    floor = sum(r.get("floor_sf") or 0.0 for r in rooms)
    gsf = next((q["qty"] for q in res.get("quantities") or ()
                if q.get("name") == "Gross floor area"), None)
    if floor and gsf:
        c = _check("Room floor area", floor, gsf, "SF", "the rooms",
                   "the building's gross area", lo=0.78, hi=0.97)
        if c:
            out.append(c)
    ceil = sum(r.get("ceiling_sf") or 0.0 for r in rooms)
    with_ceiling = sum(r.get("floor_sf") or 0.0 for r in rooms
                       if r.get("ceiling_sf"))
    if ceil and with_ceiling:
        c = _check("Ceiling area", ceil, with_ceiling, "SF",
                   "the ceiling finishes", "the floor area of the rooms "
                   "with a ceiling", lo=0.95, hi=1.05)
        if c:
            out.append(c)
    for c in out:
        if c["ok"]:
            c["why"] = ""
            continue
        c["why"] = (f"{c['name']}: {c['a']:,.0f} {c['unit']} from "
                    f"{c['a_from']}, {c['b']:,.0f} {c['unit']} from "
                    f"{c['b_from']} ({c['off']:+.0%}) - one of them is "
                    "missing or adding something; check")
        res.setdefault("review", []).append({
            "sheet": "set", "page": None, "name": f"Cross-check: "
            f"{c['name']}", "qty": None, "unit": c["unit"],
            "engine": "check", "why": c["why"]})
        res.setdefault("problems", []).append(c["why"])
    for c in out:
        if c["name"] == "Room floor area" and not c["ok"]:
            _gross_to_review(res, c)
    res["checks"] = out
    return out


def _gross_to_review(res, c):
    """The gross floor area line, taken off, moved to review with the
    cross-check's reason (its quantity kept for the person to accept)."""
    for q in res.get("quantities") or []:
        if q.get("name") == "Gross floor area" and \
                q.get("status") == "taken off":
            q["status"] = "review"
            res.setdefault("review", []).append({
                "sheet": q.get("sheet"), "page": q.get("page"),
                "name": "Gross floor area", "qty": q["qty"],
                "unit": q.get("unit", "SF"), "engine": "walls",
                "csi": q.get("csi", ""),
                "why": "the room cross-check disagrees - " + c["why"],
                "confidence": 0.4,
                # the same quantity line, listed for review: not a
                # second line in the estimate
                "line": True})
