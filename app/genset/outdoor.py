"""A covered front porch and a rear deck (0.12.20).

Rules (Claude, Oct 19 - for Jon to confirm, see docs/GENSET_NOTES.md):
  * Houses only. "porch" / "front porch" / "covered porch" in the brief:
    a porch at the front door, 6 ft deep (8 ft if the brief says "wide" or
    "wraparound" - drawn as a front porch), as wide as the room the front
    door opens into, at least 10 ft and at most 24 ft; a slab a step down,
    posts at the corners and every 8 ft, a shed roof from just under the
    house eave (9'-6" at most) sloping out at about 2:12.
  * "deck" / "rear deck" / "back deck": a wood deck 10 ft deep behind the
    rear door, 12-20 ft wide, at the floor level, a 36" guard - verify
    the guard and stair rules locally.
  * Neither is heated or counted in the gross area. The site plan shows
    them; a porch in the front setback is noted (many towns allow it -
    verify).

Plan coordinates as the house (feet, x east, y north, (0, 0) at the
south-west wall centreline): the porch has y < 0, the deck y > depth.
"""
import re

PORCH_D = 6.0
POST = 0.5
_PORCH = re.compile(r"\b(?:(wide|deep|wraparound|wrap-around|covered|front|"
                    r"farmhouse)\s+)?porch(?:es)?\b", re.I)
_DECK = re.compile(r"\b(?:(rear|back|wood|large|big)\s+)?deck\b", re.I)
# "no porch", "without a covered front porch", "no wood deck" (Venice
# review M10: an adjective in between used to draw the porch anyway)
_NO = re.compile(r"\b(no|without)\s+(?:an?\s+)?(?:(?:front|rear|back|covered|"
                 r"wide|deep|wraparound|wrap-around|farmhouse|wood|large|big)"
                 r"\s+){0,3}(porch|deck)\b", re.I)
# a stated depth: "8 ft deep porch", "porch 10' deep", "porch, 8 feet deep"
_DEPTH = re.compile(r"(?:\b(\d{1,2}(?:\.\d)?)\s*(?:'|ft\.?|feet|foot)\s*"
                    r"(?:deep\s+)?(?:\w+\s+){0,2}porch\b|\bporch\b[^.;\n]{0,20}?"
                    r"\b(\d{1,2}(?:\.\d)?)\s*(?:'|ft\.?|feet|foot)\s*deep)",
                    re.I)


def read(text):
    """{"porch": depth or None, "deck": True or None} from the brief."""
    t = text or ""
    out = {}
    no = {m.group(2).lower() for m in _NO.finditer(t)}
    m = _PORCH.search(t)
    if m and "porch" not in no:
        wide = (m.group(1) or "").lower() in ("wide", "deep", "wraparound",
                                               "wrap-around", "farmhouse")
        out["porch"] = 8.0 if wide else PORCH_D
        d = _DEPTH.search(t)
        if d:                       # what the brief says, 4 - 12 ft
            out["porch"] = max(4.0, min(12.0, float(d.group(1) or
                                                     d.group(2))))
    m = _DECK.search(t)
    if m and "deck" not in no:
        out["deck"] = True
    return out


def _door(plan, wall):
    return next((o for o in plan["openings"] if o["kind"] == "door" and
                 o.get("from_room") == "EXT" and o["wall"] == wall), None)


PORCH_HIGH = 9.5          # where the shed roof meets the wall, at most
UNDER_EAVE = 0.25         # 3" below the main eave (Jon, Oct 20: "under eave")
SLAB = -0.5               # the porch slab, a step down
CLEAR = 6.0 + 8 / 12      # 6'-8" clear under the porch beam
BEAM = 0.6                # the beam / fascia depth drawn at the low edge


def porch_roof(plan, depth):
    """(low, high, note) of the porch's shed roof. On a one-story house
    whose front is under an eave, the roof starts just under that eave
    (Jon, Oct 20) and slopes out at 2:12 where the headroom allows; the
    note says when it has to be flatter than 2:12."""
    roof = plan.get("roof") or {}
    lv = plan.get("level") or {}
    hi = PORCH_HIGH
    if "upper" not in plan and roof.get("type") == "gable" and \
            roof.get("ridge_dir", "x") == "x":     # the front is an eave
        eave = (float(lv.get("floor_elev", 0)) +
                float(lv.get("plate_height", 9.0)) -
                float(roof.get("pitch", 6)) / 12.0 *
                float(roof.get("overhang") or 0))
        hi = min(hi, eave - UNDER_EAVE)
    run = depth + 0.5
    lo_min = SLAB + CLEAR + BEAM
    if hi >= PORCH_HIGH:
        return 8.0, PORCH_HIGH, ""           # as before: 8'-0" to 9'-6"
    import math
    lo = max(hi - 2.0 / 12 * run, lo_min)
    lo = math.ceil(lo * 12 - 1e-6) / 12             # up to the inch
    note = ""
    if (hi - lo) / run * 12 < 2.0 - 1e-6:
        note = (f"The porch roof is {(hi - lo) / run * 12:.1f}:12 (it starts "
                "under the house eave and keeps 6'-8\" headroom): use a "
                "low-slope roof such as standing-seam metal, or lower the "
                "porch slab.")
    return round(lo, 3), round(hi, 3), note


def add(plan, wants, warnings):
    """Add plan["porch"] / plan["deck"]; warnings for what can't be."""
    if not wants:
        return
    if plan["project"]["building_type"] != "single_family":
        warnings.append("Porches and decks are drawn for houses only; left "
                        "out.")
        return
    W, D = plan["footprint"]["width"], plan["footprint"]["depth"]
    if wants.get("porch"):
        door = _door(plan, "W1")
        if door is None:
            warnings.append("No front door on the street side; porch left "
                            "out.")
        else:
            room = next(r for r in plan["rooms"]
                        if r["id"] == door["to_room"])
            c = door["along"]                     # W1 runs west to east
            w = max(10.0, min(24.0, room["rect"][2] - room["rect"][0]))
            x0 = max(-0.25, min(c - w / 2, W + 0.25 - w))
            g = plan.get("garage")
            if g and g["side"] == "W":
                x0 = max(x0, 0.25)
            if g and g["side"] == "E":
                x0 = min(x0, W - 0.25 - w)
            x0 = float(round(x0 * 2) / 2)
            d = float(wants["porch"])
            posts = []
            n = max(1, int(round(w / 8.0)))
            for k in range(n + 1):
                posts.append(round(x0 + POST / 2 + (w - POST) * k / n, 3))
            plan["porch"] = {"rect": [x0, -0.25 - d, x0 + w, -0.25],
                             "depth": d, "width": w, "posts": posts,
                             "area": round(w * d, 1),
                             "name": "COVERED PORCH"}
            lo, hi, note = porch_roof(plan, d)
            plan["porch"].update(roof_low=lo, roof_high=hi)
            if note:
                warnings.append(note)
    if wants.get("deck"):
        door = _door(plan, "W3")
        if door is None:
            warnings.append("No rear door on the back wall; deck left out "
                            "(it needs a door onto it).")
        else:
            c = W - door["along"]                 # W3 runs east to west
            w = 16.0 if W >= 30 else 12.0
            x0 = max(-0.25, min(c - w / 2, W + 0.25 - w))
            x0 = float(round(x0 * 2) / 2)
            plan["deck"] = {"rect": [x0, D + 0.25, x0 + w, D + 0.25 + 10.0],
                            "depth": 10.0, "width": w,
                            "area": round(w * 10.0, 1), "guard": 3.0,
                            "name": "DECK"}
    s = plan.get("site")
    p = plan.get("porch")
    if s and p and s["setbacks"]["front"] > s["provided"]["front"] - \
            p["depth"] + 1e-6:
        warnings.append(f"The porch reaches {p['depth']:g} ft into the "
                        "front setback - many towns allow a porch there; "
                        "verify.")
    dk = plan.get("deck")
    if s and dk and s["setbacks"]["rear"] > s["provided"]["rear"] - \
            dk["depth"] + 1e-6:
        warnings.append("The deck reaches into the rear setback - verify "
                        "what the town allows.")


def bounds(plan):
    """(x0, y0, x1, y1) of the porch and deck, or None."""
    rs = [plan[k]["rect"] for k in ("porch", "deck") if plan.get(k)]
    if not rs:
        return None
    return (min(r[0] for r in rs), min(r[1] for r in rs),
            max(r[2] for r in rs), max(r[3] for r in rs))
