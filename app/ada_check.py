"""ADA checker for commercial projects (2010 ADA Standards, chapter 2
scoping). You give the counts - parking, entrances, stories, toilet rooms,
seats, guest rooms - and it says what the Standards require, what you have,
and the section for each line.

Every number here is copied from the Standards text in app/data/ada2010.json
(tests/test_ada.py checks the tables against it). Fractions round up
(104.2). The answer is a screening aid: alterations, historic buildings,
and the many exceptions decide the real answer, and so does the code your
jurisdiction adopted.

    project = {"title": "II"|"III", "use": "office", "stories": 2, ...}
    check(project) -> [Finding, ...]
"""
import math
from dataclasses import dataclass, field, asdict

USES = {
    "office": "Office",
    "retail": "Retail / mercantile",
    "shopping_center": "Shopping center or mall",
    "health_office": "Professional office of a health care provider",
    "restaurant": "Restaurant / bar",
    "assembly": "Assembly (theater, worship, auditorium, arena)",
    "lodging": "Hotel / motel (transient lodging)",
    "hospital": "Hospital (stays over 24 hours)",
    "rehab": "Rehabilitation facility / outpatient PT",
    "outpatient": "Hospital outpatient facility",
    "long_term_care": "Licensed long-term care (nursing home)",
    "transit": "Transportation terminal, station or airport",
    "school": "School / education",
    "warehouse": "Warehouse / industrial (with public areas)",
    "residential": "Apartments / residential (not HUD-funded)",
}
# private buildings that never get the elevator exception (206.2.3 Exc. 1)
NO_ELEVATOR_EXCEPTION = {"shopping_center", "health_office", "transit"}


@dataclass
class Finding:
    item: str
    cite: str
    required: object = None          # number, or text
    provided: object = None          # None: you didn't say
    status: str = "info"             # ok | short | info | check
    note: str = ""
    group: str = ""
    page: object = None              # a measured element: where it is
    ref: object = None

    def as_dict(self):
        return asdict(self)


def _n(v, default=0):
    """A count from the form: a whole number 0 or more."""
    if v is None or v == "" or isinstance(v, bool):
        return default
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(f) or f < 0:
        return default
    return int(f)


def _up(x):
    return int(math.ceil(x - 1e-9))


def _pct(n, pct):
    """pct of n, rounded up (104.2)."""
    return _up(n * pct / 100.0)


# ----------------------------------------------------------------- tables
# Table 208.2 Parking Spaces: (top of band, required)
PARKING = [(25, 1), (50, 2), (75, 3), (100, 4), (150, 5), (200, 6),
           (300, 7), (400, 8), (500, 9)]


def parking_required(total, use="general"):
    """Accessible spaces for one parking facility (208.2, 208.2.1-2)."""
    total = _n(total)
    if total <= 0:
        return 0
    if use == "outpatient":
        return _pct(total, 10)                     # 208.2.1
    if use == "rehab":
        return _pct(total, 20)                     # 208.2.2
    for top, req in PARKING:
        if total <= top:
            return req
    if total <= 1000:
        return _pct(total, 2)
    return 20 + _up((total - 1000) / 100.0)


def residential_parking(total, units_):
    """Resident parking (208.2.3.1-2): where there is at least one space
    per unit, one accessible space per unit with mobility features, and
    2 percent (no fewer than one) of the spaces beyond one per unit."""
    total, units_ = _n(total), _n(units_)
    mobility = max(1, _pct(units_, 5)) if units_ else 0
    if total < units_:
        return parking_required(total)       # under one per unit: Table
    extra = total - units_
    return mobility + (max(1, _pct(extra, 2)) if extra else 0)


def van_required(accessible):
    """One van space for every six or fraction of six (208.2.4)."""
    return _up(_n(accessible) / 6.0)


# Table 221.2.1.1 Number of Wheelchair Spaces in Assembly Areas
WHEELCHAIR = [(3, 0), (25, 1), (50, 2), (150, 4), (300, 5), (500, 6)]


def wheelchair_spaces(seats):
    seats = _n(seats)
    for top, req in WHEELCHAIR:
        if seats <= top:
            return req
    if seats <= 5000:
        return 6 + _up((seats - 500) / 150.0)
    return 36 + _up((seats - 5000) / 200.0)


def receivers(seats):
    """(receivers, hearing-aid compatible) - Table 219.3 and 219.3."""
    seats = _n(seats)
    if seats <= 0:
        return 0, 0
    if seats <= 50:
        r = 2
    elif seats <= 500:
        r = 2 + _up((seats - 50) / 25.0)
    elif seats <= 1000:
        r = 20 + _up((seats - 500) / 33.0)
    elif seats <= 2000:
        r = 35 + _up((seats - 1000) / 50.0)
    else:
        r = 55 + _up((seats - 2000) / 100.0)
    hac = 2 if seats <= 200 else max(2, _up(r / 4.0))
    return r, hac


# Table 224.2 Guest Rooms with Mobility Features:
# (top, without roll-in showers, with roll-in showers, total)
GUEST = [(25, 1, 0, 1), (50, 2, 0, 2), (75, 3, 1, 4), (100, 4, 1, 5),
         (150, 5, 2, 7), (200, 6, 2, 8), (300, 7, 3, 10), (400, 8, 4, 12),
         (500, 9, 4, 13)]
# Table 224.4 Guest Rooms with Communication Features
COMM = [(1, 0), (25, 2), (50, 4), (75, 7), (100, 9), (150, 12), (200, 14),
        (300, 17), (400, 20), (500, 22)]


def guest_mobility(rooms):
    """(without roll-in, with roll-in, total)."""
    rooms = _n(rooms)
    if rooms <= 0:
        return 0, 0, 0
    for top, a, b, t in GUEST:
        if rooms <= top:
            return a, b, t
    if rooms <= 1000:
        return _pct(rooms, 2), _pct(rooms, 1), _pct(rooms, 3)
    k = _up((rooms - 1000) / 100.0)
    return 20 + k, 10 + k, 30 + 2 * k


def guest_communication(rooms):
    rooms = _n(rooms)
    for top, req in COMM:
        if rooms <= top:
            return req
    if rooms <= 1000:
        return _pct(rooms, 5)
    # "50, plus 3 for each 100 over 1000"; a fraction rounds up (104.2)
    return 50 + _up(3 * (rooms - 1000) / 100.0)


# ----------------------------------------------------------------- checks
def _cmp(item, cite, req, have, group, note=""):
    if have is None:
        status = "info"
    else:
        status = "ok" if have >= req else "short"
    return Finding(item, cite, req, have, status, note, group)


def _have(d, key):
    """A provided count, or None when the field was left empty."""
    v = d.get(key)
    if v is None or v == "":
        return None
    return _n(v)


def _parking(p, out):
    lots = p.get("parking") or []
    use = p.get("use", "")
    for i, lot in enumerate(lots, 1):
        if not isinstance(lot, dict):
            continue
        total = _n(lot.get("total"))
        if total <= 0:
            continue
        kind = lot.get("serves") or (
            "outpatient" if use == "outpatient" else
            "rehab" if use == "rehab" else "general")
        name = lot.get("name") or f"Parking facility {i}"
        units_ = _n(p.get("dwelling_units"))
        if kind == "general" and use == "residential" and units_ and \
                lot.get("serves") != "guests":
            req, cite = residential_parking(total, units_), \
                "208.2.3.1 / 208.2.3.2"
        else:
            req = parking_required(total, kind)
            cite = {"outpatient": "208.2.1", "rehab": "208.2.2"}.get(
                kind, "208.2 / Table 208.2")
        out.append(_cmp(f"{name}: accessible spaces ({total} total)", cite,
                        req, _have(lot, "accessible"), "Parking"))
        out.append(_cmp(f"{name}: van spaces (of the accessible)",
                        "208.2.4", van_required(req), _have(lot, "van"),
                        "Parking", "Van: 132 in. wide with a 60 in. aisle, "
                        "or 96 in. with a 96 in. aisle (502.2, 502.3.1)"))
    if lots:
        out.append(Finding(
            "Location of accessible parking", "208.3.1",
            "Shortest accessible route to an accessible entrance",
            None, "check", "Count each parking facility separately "
            "(208.2); disperse to multiple accessible entrances.",
            "Parking"))


def _loading(p, out):
    ft = _n(p.get("loading_zone_ft"))
    if ft > 0:
        out.append(_cmp(f"Passenger loading zone ({ft} ft)", "209.2.1",
                        _up(ft / 100.0), _have(p, "loading_accessible"),
                        "Site", "One accessible zone per continuous 100 ft "
                        "or fraction (503)."))
    if p.get("use") in ("hospital", "long_term_care"):
        out.append(_cmp("Passenger loading zone at an accessible entrance",
                        "209.3", 1, _have(p, "loading_accessible"), "Site"))


def _entrances(p, out):
    n = _n(p.get("public_entrances"))
    if n > 0:
        out.append(_cmp(f"Public entrances complying with 404 ({n} total)",
                        "206.4.1", _pct(n, 60),
                        _have(p, "accessible_entrances"), "Entrances",
                        "Plus every direct entrance from a parking "
                        "structure (206.4.2) and one per tenancy "
                        "(206.4.5)."))
        if _have(p, "accessible_entrances") is not None and \
                _n(p.get("accessible_entrances")) < n:
            out.append(Finding("Signs at entrances", "216.6",
                               "ISA at accessible entrances; directional "
                               "signs at the others", None, "check", "",
                               "Entrances"))
    tenants = _n(p.get("tenant_spaces"))
    if tenants:
        out.append(Finding(f"Tenant spaces ({tenants})", "206.4.5",
                           "1 accessible entrance to each", None, "check",
                           "", "Entrances"))


def _stories(p, out):
    stories = _n(p.get("stories"), 1)
    if stories <= 1:
        return
    per = _n(p.get("sf_per_story"))
    public = str(p.get("title", "III")).upper() == "II"
    use = p.get("use", "")
    exempt = (not public and use not in NO_ELEVATOR_EXCEPTION and
              (stories < 3 or (per and per < 3000)))
    have = p.get("elevator")
    have = None if have in (None, "") else bool(have)
    if exempt:
        out.append(Finding(
            "Accessible route between stories (elevator)",
            "206.2.3 Exception 1", "Not required", have, "ok",
            "Private building under three stories or under 3,000 sq ft "
            "per story. Toilet rooms must then be on an accessible story "
            "(213.1), and an elevator if provided must comply (206.6).",
            "Accessible route"))
    else:
        why = ("public (Title II) building" if public else
               USES.get(use, "this use") if use in NO_ELEVATOR_EXCEPTION
               else f"{stories} stories of {per or '3,000+'} sq ft")
        out.append(Finding(
            "Accessible route between stories (elevator)", "206.2.3",
            "Required", have,
            "info" if have is None else ("ok" if have else "short"),
            f"Required for a {why}. Public buildings: see Exception 2 for "
            "a small two-story case.", "Accessible route"))


def _toilets(p, out):
    for i, r in enumerate(p.get("toilet_rooms") or [], 1):
        if not isinstance(r, dict):
            continue
        name = r.get("name") or f"Toilet room {i}"
        comps = _n(r.get("compartments"))
        urinals = _n(r.get("urinals"))
        wcs = _n(r.get("water_closets"), comps)
        lavs = _n(r.get("lavatories"))
        g = "Toilet rooms"
        out.append(Finding(f"{name}: room complies with 603", "213.2",
                           "Required", None, "check",
                           "60 in. turning space (603.2.1, 304.3); door "
                           "can't swing into a fixture's clear floor space "
                           "(603.2.3).", g))
        if comps:
            out.append(_cmp(f"{name}: wheelchair accessible compartment",
                            "213.3.1 / 604.8.1", 1,
                            _have(r, "wheelchair_compartments"), g,
                            "60 in. wide; 56 in. deep (wall-hung WC) or "
                            "59 in. (floor-mounted)."))
            if comps >= 6 or urinals + wcs >= 6:
                out.append(_cmp(f"{name}: ambulatory compartment",
                                "213.3.1 / 604.8.2", 1,
                                _have(r, "ambulatory_compartments"), g,
                                "60 in. deep, 35-37 in. wide "
                                "(604.8.2.1)."))
        elif wcs:
            out.append(Finding(f"{name}: accessible water closet",
                               "213.3.2 / 604", 1, None, "check",
                               "Centerline 16-18 in. from the side wall; "
                               "clearance 60 x 56 in. (604.2, 604.3.1).",
                               g))
        if urinals > 1:
            out.append(_cmp(f"{name}: accessible urinal", "213.3.3 / 605",
                            1, _have(r, "accessible_urinals"), g))
        if lavs:
            out.append(_cmp(f"{name}: accessible lavatory (not in a "
                            "compartment)", "213.3.4 / 606", 1,
                            _have(r, "accessible_lavatories"), g))
    single = _n(p.get("single_user_toilets_cluster"))
    if single > 1:
        out.append(Finding(f"Cluster of {single} single-user toilet rooms",
                           "213.2 Exception 4", _up(single / 2.0), None,
                           "check", "At least 50 percent of each use in "
                           "the cluster must comply with 603; mark them "
                           "with the ISA (216.8).", "Toilet rooms"))


def _fountains(p, out):
    n = _n(p.get("drinking_fountains"))
    if n <= 0:
        return
    if n == 1:
        out.append(Finding("Drinking fountain", "211.2", "Two needed "
                           "(one wheelchair, one standing) - or one unit "
                           "that does both", None, "check", "", "Fixtures"))
        return
    half = n // 2
    note = ("50 percent each; with an odd count round either way so the "
            "two kinds add up to all of them (211.3 Exception).")
    out.append(_cmp("Wheelchair-height fountains (602.1-602.6)",
                    "211.2 / 211.3", half, _have(p, "fountains_low"),
                    "Fixtures", note))
    out.append(_cmp("Standing-height fountains (602.7)", "211.2 / 211.3",
                    half, _have(p, "fountains_high"), "Fixtures"))


def _assembly(p, out):
    for i, a in enumerate(p.get("assembly_areas") or [], 1):
        if not isinstance(a, dict):
            continue
        seats = _n(a.get("seats"))
        if seats <= 0:
            continue
        name = a.get("name") or f"Assembly area {i}"
        g = "Assembly"
        ws = wheelchair_spaces(seats)
        out.append(_cmp(f"{name}: wheelchair spaces ({seats} seats)",
                        "221.2.1.1 / Table 221.2.1.1", ws,
                        _have(a, "wheelchair_spaces"), g,
                        "Dispersed, with comparable lines of sight "
                        "(221.2.3, 802.2); 36 in. wide single, 33 in. "
                        "each when paired (802.1.2)."))
        out.append(_cmp(f"{name}: companion seats", "221.3", ws,
                        _have(a, "companion_seats"), g))
        aisle = _n(a.get("aisle_seats"))
        if aisle:
            out.append(_cmp(f"{name}: designated aisle seats "
                            f"({aisle} aisle seats)", "221.4",
                            _pct(aisle, 5), _have(a, "designated_aisle"), g,
                            "Those closest to the accessible route."))
        amplified = a.get("amplified", True)
        if amplified or p.get("use") == "courtroom":
            r, hac = receivers(seats)
            out.append(_cmp(f"{name}: assistive listening receivers",
                            "219.3 / Table 219.3", r,
                            _have(a, "receivers"), g,
                            "Required where audio amplification is "
                            "provided (219.2)."))
            out.append(_cmp(f"{name}: hearing-aid compatible receivers",
                            "219.3", hac, _have(a, "hac_receivers"), g,
                            "Not required where every seat is served by "
                            "an induction loop (219.3 Exception 2)."))


def _dining(p, out):
    seats = _n(p.get("dining_seats"))
    if seats:
        out.append(_cmp(f"Accessible dining seating ({seats} seats)",
                        "226.1 / 902", _pct(seats, 5),
                        _have(p, "dining_accessible"), "Dining & work",
                        "28-34 in. high with knee clearance (902.3), "
                        "dispersed (226.2)."))
    work = _n(p.get("work_surfaces"))
    if work:
        out.append(_cmp(f"Accessible public work surfaces ({work})",
                        "226.1 / 902", _pct(work, 5),
                        _have(p, "work_accessible"), "Dining & work"))
    types = _n(p.get("counter_types"))
    if types:
        out.append(_cmp(f"Accessible sales/service counters ({types} types)",
                        "227.3 / 904.4", types,
                        _have(p, "counters_accessible"), "Dining & work",
                        "One of each type, 36 in. long x 36 in. high max "
                        "(904.4.1); disperse if counters are."))
    lanes = _n(p.get("checkout_aisles"))
    if lanes:
        out.append(Finding(f"Check-out aisles ({lanes})", "227.2 / Table "
                           "227.2", "See Table 227.2", None, "check", "",
                           "Dining & work"))


def _rooms(p, out):
    for key, label, cite in (("dressing_rooms", "dressing / fitting rooms",
                              "222.1 / 803"),
                             ("lockers", "lockers", "225.2.1 / 811")):
        n = _n(p.get(key))
        if n:
            out.append(_cmp(f"Accessible {label} ({n} of a type)", cite,
                            max(1, _pct(n, 5)),
                            _have(p, key + "_accessible"), "Rooms",
                            "5 percent, no fewer than one, of each type "
                            "in each cluster."))


def _lodging(p, out):
    n = _n(p.get("guest_rooms"))
    if not n:
        return
    a, b, t = guest_mobility(n)
    g = "Lodging"
    out.append(_cmp(f"Mobility rooms without roll-in showers ({n} rooms)",
                    "224.2 / Table 224.2", a, _have(p, "mobility_tub"), g))
    out.append(_cmp("Mobility rooms with roll-in showers",
                    "224.2 / Table 224.2", b, _have(p, "mobility_rollin"), g))
    out.append(_cmp("Rooms with communication features",
                    "224.4 / Table 224.4", guest_communication(n),
                    _have(p, "communication_rooms"), g,
                    "Dispersed among room types (224.5); at least one "
                    "mobility room also has communication features."))


def _residential(p, out):
    n = _n(p.get("dwelling_units"))
    if not n:
        return
    g = "Dwelling units"
    out.append(_cmp(f"Units with mobility features ({n} units)",
                    "233.3.1.1 / 809.2-809.4", max(1, _pct(n, 5)),
                    _have(p, "mobility_units"), g,
                    "On an accessible route (206). HUD-funded housing: "
                    "follow HUD's Section 504 rules (233.2)."))
    out.append(_cmp("Units with communication features",
                    "233.3.1.2 / 809.5", max(1, _pct(n, 2)),
                    _have(p, "communication_units"), g))
    if n <= 15:
        out.append(Finding("15 or fewer units", "233.3.1 Exception",
                           "Count all units built under one contract",
                           None, "check", "", g))


def _medical(p, out):
    use = p.get("use")
    beds = _n(p.get("patient_rooms"))
    if not beds:
        return
    if use == "hospital":
        req, cite = max(1, _pct(beds, 10)), "223.2.1"
    elif use == "rehab":
        req, cite = beds, "223.2.2"
    elif use == "long_term_care":
        req, cite = max(1, _pct(beds, 50)), "223.3"
    else:
        return
    out.append(_cmp(f"Patient sleeping rooms with mobility features "
                    f"({beds} rooms)", cite + " / 805", req,
                    _have(p, "patient_rooms_accessible"), "Medical"))


def _always(p, out):
    g = "General"
    out.append(Finding("Accessible route from site arrival points",
                       "206.2.1", "Parking, loading zones, public "
                       "sidewalks and transit stops to an accessible "
                       "entrance", None, "check", "", g))
    out.append(Finding("Accessible route to every accessible space",
                       "206.2.4 / 402", "36 in. clear (403.5.1); passing "
                       "space every 200 ft when under 60 in. (403.5.3)",
                       None, "check", "", g))
    out.append(Finding("Doors on the accessible route", "404.2.3 / "
                       "404.2.4", "32 in. clear; maneuvering clearance "
                       "per Table 404.2.4.1", None, "check", "", g))
    out.append(Finding("Room signs (tactile, braille)", "216.2 / 703",
                       "Each permanent room", None, "check", "", g))
    if p.get("fire_alarm", True):
        out.append(Finding("Visible alarms", "215 / 702", "Where the "
                           "fire alarm is audible", None, "check", "", g))


SECTIONS = (_always, _parking, _loading, _entrances, _stories, _toilets,
            _fountains, _assembly, _dining, _rooms, _lodging, _medical,
            _residential)


def check(project):
    """Findings for one project (a dict - see the module docstring)."""
    p = project if isinstance(project, dict) else {}
    out = []
    for f in SECTIONS:
        f(p, out)
    return out


def summary(findings):
    short = sum(1 for f in findings if f.status == "short")
    ok = sum(1 for f in findings if f.status == "ok")
    todo = sum(1 for f in findings if f.status in ("info", "check"))
    return {"short": short, "ok": ok, "to_check": todo}


def report_text(project, findings):
    lines = ["ADA scoping check - 2010 ADA Standards for Accessible Design",
             f"Use: {USES.get(project.get('use'), project.get('use', ''))}"
             f"   Title {project.get('title', 'III')}", ""]
    group = None
    for f in findings:
        if f.group != group:
            group = f.group
            lines += ["", group.upper()]
        have = "" if f.provided is None else f"  have {f.provided}"
        mark = {"ok": "OK   ", "short": "SHORT", "check": "CHECK",
                "info": "NEED "}[f.status]
        lines.append(f"  {mark} {f.item}: need {f.required}{have}  "
                     f"[{f.cite}]")
        if f.note:
            lines.append(f"        {f.note}")
    s = summary(findings)
    lines += ["", f"{s['short']} short, {s['ok']} OK, {s['to_check']} to "
              "check on the drawings.",
              "Screening aid only: alterations, historic buildings and the "
              "exceptions in the Standards decide the real answer, along "
              "with your jurisdiction's adopted code."]
    return "\n".join(lines)


# ------------------------------------------------- saved with the drawings
FILE = "quantisheet_ada.json"
MAX_BYTES = 1_000_000


def read(doc):
    import json
    try:
        if FILE in doc.embfile_names():
            raw = doc.embfile_get(FILE)
            if len(raw) <= MAX_BYTES:
                data = json.loads(raw.decode("utf-8"))
                if isinstance(data, dict):
                    return data
    except Exception:                                     # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning("ADA data unreadable",
                                            exc_info=True)
    return {"title": "III", "use": "office", "stories": 1}


def write(doc, project):
    import json
    from . import embfiles
    embfiles.put(doc, FILE, json.dumps(project, indent=1).encode("utf-8"),
                 "QuantiSheet ADA check")
