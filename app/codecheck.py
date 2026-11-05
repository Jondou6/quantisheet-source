"""Code check: life-safety and accessibility checks from the takeoff.

What it reads from the drawings (by measurement group name):
* Areas -> spaces. Each space gets a function of space (office, classroom,
  storage...) guessed from its name and changeable; occupant load is the
  area divided by that function's factor (IBC Table 1004.5).
* Length measurements whose group says "door", "corridor" or "stair" ->
  clear widths; "travel", "common path" and "dead end" -> distances.
* Counts whose group says "exit" -> exits on that floor; "water closet" /
  "WC" / "toilet" and "lavatory" / "lav" -> plumbing fixtures.
Each PDF page is treated as one floor.

Checks (IBC 2021, IPC 2021, 2010 ADA Standards):
* occupant load per space and floor; spaces needing two exits (1006.2.1);
  exits per floor (1006.3.3)
* egress capacity (1005.3) against the exit doors and stairs measured
* minimum door, corridor and stair widths (1010.1.1, 1020.3, 1011.2)
* exit access travel distance (1017.2), common path (1006.2.1) and dead
  ends (1020.5)
* accessible and van-accessible parking (1106.1 / ADA 208.2)
* plumbing fixture counts (IPC Table 2902.1)

This is a screening aid. Local amendments, the adopted edition, and the
many exceptions in the code decide the real answer; the report says so.
(Built on the Venice AI draft; tables re-checked and parking corrected.)
"""
import json
import logging
import math
import re

from . import embfiles, settings, units

log = logging.getLogger(__name__)

FILE = "quantisheet_codecheck.json"
EDITION = "IBC 2021 / IPC 2021 / 2010 ADA Standards"

# key: (label, sq ft per occupant, gross|net, occupancy letter)
USES = {
    "business": ("Business areas (offices)", 150, "gross", "B"),
    "business_concentrated": ("Concentrated business (call center, "
                              "trading floor, training)", 50, "gross", "B"),
    "assembly_unconcentrated": ("Assembly, unconcentrated (tables and "
                                "chairs: conference, dining)", 15, "net",
                                "A"),
    "assembly_concentrated": ("Assembly, concentrated (chairs only)", 7,
                              "net", "A"),
    "assembly_standing": ("Assembly, standing space", 5, "net", "A"),
    "classroom": ("Educational classroom", 20, "net", "E"),
    "shop": ("Educational shops and vocational rooms", 50, "net", "E"),
    "day_care": ("Day care", 35, "net", "E"),
    "exercise": ("Exercise room", 50, "gross", "A"),
    "kitchen": ("Kitchen, commercial", 200, "gross", "A"),
    "library_reading": ("Library reading room", 50, "net", "A"),
    "library_stack": ("Library stack area", 100, "gross", "A"),
    "locker": ("Locker room", 50, "gross", "A"),
    "courtroom": ("Courtroom (no fixed seats)", 40, "net", "A"),
    "exhibit": ("Exhibit gallery and museum", 30, "net", "A"),
    "mercantile": ("Mercantile (sales floor)", 60, "gross", "M"),
    "mercantile_storage": ("Mercantile storage, stock, shipping", 300,
                           "gross", "M"),
    "industrial": ("Industrial areas", 100, "gross", "F"),
    "storage_mech": ("Accessory storage / mechanical equipment room", 300,
                     "gross", "S"),
    "warehouse": ("Warehouse", 500, "gross", "S"),
    "parking_garage": ("Parking garage", 200, "gross", "S"),
    "residential": ("Residential", 200, "gross", "R"),
    "dormitory": ("Dormitory", 50, "gross", "R"),
    "inpatient": ("Institutional, inpatient treatment", 240, "gross", "I"),
    "outpatient": ("Institutional, outpatient", 100, "gross", "I"),
    "sleeping": ("Institutional, sleeping areas", 120, "gross", "I"),
    "support": ("Corridor / toilet / stair (counted with the main use when "
                "it's gross, left out when it's net)", 0, "support", ""),
    "none": ("Not counted", 0, "none", ""),
}

# building occupancy groups offered
GROUPS = ["A-1", "A-2", "A-3", "A-4", "A-5", "B", "E", "F-1", "F-2", "H-1",
          "H-2", "H-3", "H-4", "H-5", "I-1", "I-2", "I-3", "I-4", "M", "R-1",
          "R-2", "R-3", "R-4", "S-1", "S-2", "U"]
MAIN_USE = {"A": "assembly_unconcentrated", "B": "business",
            "E": "classroom", "F": "industrial", "H": "industrial",
            "I": "sleeping", "M": "mercantile", "R": "residential",
            "S": "warehouse", "U": "storage_mech"}

KEYWORDS = [
    (("corridor", "corr", "hall", "toilet", "restroom", "women", "men",
      "wc", "vestibule", "vest", "stair", "shaft", "elev", "chase"),
     "support"),
    (("storage", "stor", "janitor", "jan", "mech", "elec", "idf", "mdf",
      "server", "data", "electrical", "mechanical", "closet"),
     "storage_mech"),
    (("classroom", "class"), "classroom"),
    (("conference", "conf", "meeting", "board", "dining", "cafe",
      "cafeteria", "break", "lounge", "multipurpose"),
     "assembly_unconcentrated"),
    (("training", "call center"), "business_concentrated"),
    (("kitchen",), "kitchen"),
    (("gym", "fitness", "exercise"), "exercise"),
    (("locker",), "locker"),
    (("library", "reading"), "library_reading"),
    (("sales", "retail", "store"), "mercantile"),
    (("warehouse",), "warehouse"),
    (("office", "ofc", "workroom", "work room", "reception", "lobby",
      "open office", "copy", "file"), "business"),
]

# Table 1006.2.1: most occupants a space may have with one exit
ONE_EXIT_MAX = {"A": 49, "B": 49, "E": 49, "F": 49, "M": 49, "U": 49,
                "H-1": 3, "H-2": 3, "H-3": 3, "H-4": 10, "H-5": 10,
                "I-1": 10, "I-2": 10, "I-3": 10, "I-4": 10, "R": 10,
                "S": 29}
# Table 1006.2.1 common path of egress travel (unsprinklered, sprinklered)
COMMON_PATH = {"A": (75, 75), "E": (75, 75), "M": (75, 75),
               "B": (75, 100), "F": (75, 100), "S": (75, 100),
               "U": (75, 100), "R-1": (75, 75), "R-2": (75, 125),
               "R-3": (75, 125), "R-4": (75, 125), "I-1": (75, 75),
               "I-2": (None, 100), "I-3": (100, 100), "I-4": (75, 75),
               "H-1": (None, 25), "H-2": (None, 50), "H-3": (None, 50),
               "H-4": (None, 75), "H-5": (None, 75)}
# Table 1017.2 exit access travel distance (unsprinklered, sprinklered)
TRAVEL = {"A": (200, 250), "E": (200, 250), "F-1": (200, 250),
          "M": (200, 250), "R": (200, 250), "S-1": (200, 250),
          "I-1": (None, 250), "B": (200, 300), "F-2": (300, 400),
          "S-2": (300, 400), "U": (300, 400), "H-1": (None, 75),
          "H-2": (None, 100), "H-3": (None, 150), "H-4": (None, 175),
          "H-5": (None, 200), "I-2": (None, 200), "I-3": (None, 200),
          "I-4": (150, 200)}
# 1020.5: dead ends may be 50 ft in these when sprinklered
DEAD_END_50 = {"B", "E", "F", "I-1", "M", "R-1", "R-2", "R-4", "S", "U"}

# IPC Table 2902.1 (per sex, occupants split 50/50; 2902.1.1)
# (wc steps, lav steps, occupants per drinking fountain)
# steps: [(up to N occupants, 1 per k), ..., (None, 1 per k)]
PLUMBING = {
    "B": ([(50, 25), (None, 50)], [(80, 40), (None, 80)], 100),
    "M": ([(None, 500)], [(None, 750)], 1000),
    "E": ([(None, 50)], [(None, 50)], 100),
    "A-2": ([(None, 75)], [(None, 200)], 500),
    "S": ([(None, 100)], [(None, 100)], 1000),
}


def exits_per_story(load):
    """Exits a story needs for its occupant load (IBC 1006.3.3)."""
    return 2 if load <= 500 else 3 if load <= 1000 else 4


def egress_factors(group, sprinklered=True, voice=False):
    """(inches per occupant at doors and level egress, at stairs) - IBC
    1005.3.1 / 1005.3.2 and their sprinkler + voice alarm exception."""
    group = str(group or "B").upper()
    lvl = 0.15 if (sprinklered and voice and letter(group) not in ("H",)
                   and group != "I-2") else 0.2
    return lvl, (0.2 if lvl == 0.15 else 0.3)


def one_exit_max(group):
    """Most occupants a space may have with one exit (Table 1006.2.1)."""
    return _lookup(ONE_EXIT_MAX, group) or 49


def travel_limit(group, sprinklered=True):
    """Exit access travel distance limit in ft (Table 1017.2), or None
    (the group must be sprinklered / not in the table)."""
    tr = _lookup(TRAVEL, group)
    if not tr:
        return None
    return tr[1] if sprinklered else tr[0]


def letter(group):
    """'B' from 'B', 'S' from 'S-1'."""
    return str(group or "B").split("-")[0].upper()


def _lookup(table, group):
    g = str(group or "B").upper()
    return table.get(g, table.get(letter(g)))


# ---- settings in the PDF ------------------------------------------------------

def defaults():
    return {"group": "B", "sprinklered": True, "voice_alarm": False,
            "uses": {}, "exits": {}, "parking": {"total": None,
                                                 "accessible": None,
                                                 "van": None}}


def read(doc):
    data = defaults()
    try:
        if FILE in doc.embfile_names():
            saved = json.loads(doc.embfile_get(FILE).decode("utf-8"))
            if isinstance(saved, dict):
                for k, v in saved.items():
                    if k == "parking":
                        data["parking"].update(v or {})
                    else:
                        data[k] = v
    except Exception:
        log.warning("could not read code check settings", exc_info=True)
    return data


def write(doc, data):
    embfiles.put(doc, FILE, json.dumps(data, indent=1).encode("utf-8"),
                 "QuantiSheet code check settings")


def update(doc, **kw):
    data = read(doc)
    for k, v in kw.items():
        if k in ("uses", "exits", "parking") and isinstance(v, dict):
            data[k].update(v)
        else:
            data[k] = v
    write(doc, data)
    return data


def guess_use(name, group="B"):
    t = " " + re.sub(r"[^a-z0-9 ]", " ", str(name or "").lower()) + " "
    for words, use in KEYWORDS:
        if any(f" {w} " in t for w in words):
            return use
    return MAIN_USE.get(letter(group), "business")


# ---- reading the drawings ----------------------------------------------------------

def _kind(group):
    g = str(group or "").lower()
    if "common path" in g:
        return "common_path"
    if "dead end" in g or "dead-end" in g:
        return "dead_end"
    if "travel" in g:
        return "travel"
    if "corridor" in g:
        return "corridor"
    if "stair" in g:
        return "stair"
    if "door" in g:
        return "exit_door" if "exit" in g else "door"
    return None


def _fixture(group):
    g = " " + re.sub(r"[^a-z]", " ", str(group or "").lower()) + " "
    if any(f" {w} " in g for w in ("wc", "water closet", "toilet",
                                   "urinal")):
        return "wc"
    if any(f" {w} " in g for w in ("lav", "lavatory", "lavatories",
                                   "sink")) and "service" not in g:
        return "lav"
    if "drinking" in g or "fountain" in g or "bottle filler" in g:
        return "df"
    if "exit" in g:
        return "exit"
    return None


def collect(doc, data=None):
    """Spaces, egress parts and counts from the takeoff, per floor."""
    from . import annotate
    data = data or read(doc)
    out = {"spaces": [], "parts": [], "counts": {}, "problems": []}
    for it in annotate.takeoff_items(doc):
        name = it.get("group") or it.get("label") or "Area"
        try:
            if it["type"] == "area":
                sf = units.measure_to_base(it["value"], it["unit"], "area")
                use = data["uses"].get(name) or guess_use(name,
                                                          data["group"])
                out["spaces"].append({
                    "name": name, "page": it["page"], "ref": it["ref"],
                    "area": sf, "use": use,
                    "exits": data["exits"].get(name)})
            elif it["type"] == "length":
                k = _kind(it.get("group"))
                if k:
                    ft = units.measure_to_base(it["value"], it["unit"],
                                               "length")
                    out["parts"].append({"kind": k, "name": name,
                                         "page": it["page"],
                                         "ref": it["ref"], "ft": ft})
            elif it["type"] == "count":
                k = _fixture(it.get("group"))
                if k:
                    c = out["counts"].setdefault(it["page"], {})
                    c[k] = c.get(k, 0) + float(it["value"])
        except units.UnitError as e:
            out["problems"].append(f"{name}: {e}")
    return out


# ---- the checks ------------------------------------------------------------------

def occupant_load(area_sf, use, main_use="business"):
    label, factor, basis, _ = USES.get(use, USES["business"])
    if basis == "support":
        label, factor, basis, _ = USES[main_use]
        if basis != "gross":
            return 0
    if not factor:
        return 0
    return math.ceil(float(area_sf) / factor - 1e-9)


def accessible_parking(total):
    """Accessible spaces required (IBC 1106.1 / ADA Table 208.2)."""
    t = int(total)
    if t <= 0:
        return 0
    for top, need in ((25, 1), (50, 2), (75, 3), (100, 4), (150, 5),
                      (200, 6), (300, 7), (400, 8), (500, 9)):
        if t <= top:
            return need
    if t <= 1000:
        return math.ceil(t * 0.02)
    return 20 + math.ceil((t - 1000) / 100)


def van_parking(accessible):
    """One van space for every six accessible spaces (ADA 208.2.4)."""
    return math.ceil(int(accessible) / 6) if accessible else 0


def _steps(n, steps):
    out, done = 0, 0
    for top, per in steps:
        part = (min(n, top) if top else n) - done
        if part > 0:
            out += math.ceil(part / per)
            done += part
        if top and n <= top:
            break
    return out


def fixtures(occupants, group):
    """Required fixtures by IPC Table 2902.1, or None if the occupancy
    isn't in the short table here."""
    g = str(group).upper()
    row = PLUMBING.get(g) or PLUMBING.get(letter(g)) \
        if g != "A-2" else PLUMBING["A-2"]
    if not row:
        return None
    wc_s, lav_s, df_per = row
    half = math.ceil(occupants / 2)
    wc = _steps(half, wc_s)
    lav = _steps(half, lav_s)
    return {"wc_each": wc, "lav_each": lav, "wc": wc * 2, "lav": lav * 2,
            "df": max(1, math.ceil(occupants / df_per)) if occupants else 0,
            "service_sink": 1}


def _f(sev, rule, section, where, message, actual=None, required=None,
       unit="", page=None, ref=None):
    return {"severity": sev, "rule": rule, "section": section,
            "where": where, "message": message, "actual": actual,
            "required": required, "unit": unit, "page": page, "ref": ref}


def check(doc, data=None, collected=None):
    """Findings, worst first, and a summary."""
    data = data or read(doc)
    col = collected or collect(doc, data)
    group = str(data.get("group") or "B").upper()
    spr = bool(data.get("sprinklered"))
    voice = bool(data.get("voice_alarm"))
    main = MAIN_USE.get(letter(group), "business")
    out = []
    for p in col["problems"]:
        out.append(_f("warn", "units", "-", "takeoff", p))

    # occupant load per space and floor
    floors = {}
    for s in col["spaces"]:
        s["load"] = occupant_load(s["area"], s["use"], main)
        floors.setdefault(s["page"], 0)
        floors[s["page"]] += s["load"]
        u = USES.get(s["use"], USES["business"])
        occ = u[3] or letter(group)
        g_for = group if letter(group) == occ else occ
        one = one_exit_max(g_for)
        if s["load"] > one:
            ex = s.get("exits")
            if ex is None:
                out.append(_f("warn", "two-exits", "1006.2.1", s["name"],
                              f"Occupant load {s['load']} is over {one}: "
                              "the space needs two exits or exit access "
                              "doorways. Confirm and enter its exits.",
                              s["load"], one, "occupants", s["page"],
                              s["ref"]))
            elif int(ex) < 2:
                out.append(_f("error", "two-exits", "1006.2.1", s["name"],
                              f"Occupant load {s['load']} needs two exits; "
                              f"{ex} shown.", int(ex), 2, "exits",
                              s["page"], s["ref"]))
    total = sum(floors.values())

    # exits and egress capacity per floor
    lvl, stair_f = egress_factors(group, spr, voice)
    for page, load in sorted(floors.items()):
        where = f"Floor on page {page + 1}"
        need = exits_per_story(load)
        have = col["counts"].get(page, {}).get("exit")
        if have is not None:
            if have < need:
                sev = "warn" if have == 1 and need == 2 else "error"
                msg = (f"Occupant load {load} needs {need} exits; "
                       f"{have:g} counted.")
                if sev == "warn":
                    msg += " One exit is allowed only where Table 1006.3.4 "
                    msg += "permits it."
                out.append(_f(sev, "exits-per-story", "1006.3.3", where,
                              msg, have, need, "exits", page))
        doors = [x for x in col["parts"] if x["page"] == page and
                 x["kind"] == "exit_door"]
        if doors and load:
            got = sum(x["ft"] * 12 for x in doors)
            req = load * lvl
            if got + 1e-6 < req:
                out.append(_f("error", "egress-capacity", "1005.3.2",
                              where, f"Exit doors give {got:.0f} in; "
                              f"{load} occupants x {lvl} in need "
                              f"{req:.0f} in.", round(got, 1),
                              round(req, 1), "in", page))
        stairs = [x for x in col["parts"] if x["page"] == page and
                  x["kind"] == "stair"]
        if stairs and load:
            got = sum(x["ft"] * 12 for x in stairs)
            req = load * stair_f
            if got + 1e-6 < req:
                out.append(_f("error", "stair-capacity", "1005.3.1", where,
                              f"Stairs give {got:.0f} in; {load} occupants "
                              f"x {stair_f} in need {req:.0f} in.",
                              round(got, 1), round(req, 1), "in", page))

    # component widths and distances
    tr = _lookup(TRAVEL, group)
    cp = _lookup(COMMON_PATH, group)
    for x in col["parts"]:
        load = floors.get(x["page"], 0)
        inches = x["ft"] * 12
        k = x["kind"]
        args = dict(page=x["page"], ref=x["ref"])
        if k in ("door", "exit_door") and inches < 32 - 1e-6:
            out.append(_f("error", "door-width", "1010.1.1", x["name"],
                          "Door clear width under 32 in.", round(inches, 1),
                          32, "in", **args))
        elif k == "corridor":
            req = 44 if load >= 50 else 36
            if inches < req - 1e-6:
                out.append(_f("error", "corridor-width", "1020.3", x["name"],
                              f"Corridor under {req} in.", round(inches, 1),
                              req, "in", **args))
        elif k == "stair":
            req = 44 if load >= 50 else 36
            if inches < req - 1e-6:
                out.append(_f("error", "stair-width", "1011.2", x["name"],
                              f"Stair under {req} in.", round(inches, 1),
                              req, "in", **args))
        elif k == "travel" and tr:
            lim = tr[1] if spr else tr[0]
            if lim is None:
                out.append(_f("error", "sprinklers", "1017.2", x["name"],
                              f"{group} must be sprinklered.", **args))
            elif x["ft"] > lim + 1e-6:
                out.append(_f("error", "travel-distance", "1017.2",
                              x["name"], "Exit access travel distance over "
                              "the limit.", round(x["ft"], 1), lim, "ft",
                              **args))
        elif k == "common_path" and cp:
            lim = cp[1] if spr else cp[0]
            if not spr and letter(group) in ("B", "F", "S", "U") and \
                    load <= (29 if letter(group) == "S" else 30):
                lim = 100
            if lim is not None and x["ft"] > lim + 1e-6:
                out.append(_f("error", "common-path", "1006.2.1",
                              x["name"], "Common path of egress travel over "
                              "the limit.", round(x["ft"], 1), lim, "ft",
                              **args))
        elif k == "dead_end":
            ok50 = spr and (group in DEAD_END_50 or letter(group) in
                            DEAD_END_50)
            lim = 50 if ok50 else 20
            if x["ft"] > lim + 1e-6:
                out.append(_f("error", "dead-end", "1020.5", x["name"],
                              "Dead-end corridor over the limit (no limit "
                              "if it is under 2.5 times its least width).",
                              round(x["ft"], 1), lim, "ft", **args))

    # parking
    pk = data.get("parking") or {}
    if pk.get("total"):
        need = accessible_parking(pk["total"])
        acc = pk.get("accessible")
        if acc is not None and int(acc) < need:
            out.append(_f("error", "accessible-parking", "1106.1",
                          "Parking", f"{pk['total']} spaces need {need} "
                          "accessible.", int(acc), need, "spaces"))
        van_need = van_parking(max(need, int(acc or 0)))
        van = pk.get("van")
        if van is not None and int(van) < van_need:
            out.append(_f("error", "van-parking", "1106.1 / ADA 208.2.4",
                          "Parking", "Van-accessible spaces short.",
                          int(van), van_need, "spaces"))

    # plumbing fixtures
    fx = fixtures(total, group)
    have = {"wc": 0.0, "lav": 0.0, "df": 0.0}
    counted = False
    for c in col["counts"].values():
        for k in have:
            if k in c:
                have[k] += c[k]
                counted = True
    if fx:
        out.append(_f("info", "plumbing", "IPC 2902.1", "Building",
                      f"{total} occupants need {fx['wc']} water closets "
                      f"({fx['wc_each']} per sex), {fx['lav']} lavatories "
                      f"({fx['lav_each']} per sex), {fx['df']} drinking "
                      "fountain(s) and 1 service sink."))
        if counted:
            for k, label in (("wc", "water closets"), ("lav", "lavatories"),
                             ("df", "drinking fountains")):
                if have[k] < fx[k]:
                    out.append(_f("error", "plumbing-" + k, "IPC 2902.1",
                                  "Building", f"Not enough {label}.",
                                  int(have[k]), fx[k], "fixtures"))
    elif total:
        out.append(_f("info", "plumbing", "IPC 2902.1", "Building",
                      f"Check plumbing fixtures for {group} in IPC Table "
                      "2902.1 (not in this tool's short table)."))
    order = {"error": 0, "warn": 1, "info": 2}
    out.sort(key=lambda f: (order[f["severity"]], f["section"], f["where"]))
    summary = {"occupants": total, "floors": floors,
               "errors": sum(1 for f in out if f["severity"] == "error"),
               "warnings": sum(1 for f in out if f["severity"] == "warn"),
               "spaces": col["spaces"], "group": group,
               "sprinklered": spr, "fixtures": fx}
    return out, summary


# ---- outputs -------------------------------------------------------------------

def markup(doc, findings, author=""):
    """A red cloud with the finding as its note around each finding that
    points at a measurement. Returns how many were added."""
    from . import annotate
    import fitz
    n = 0
    for f in findings:
        if f["severity"] == "info" or f.get("page") is None or \
                not f.get("ref"):
            continue
        page = doc[f["page"]]
        found = annotate.find_annots(page, f["ref"])
        if not found:
            continue
        a = found[0]
        pts = [fitz.Point(v) for v in (a.vertices or [])]
        if pts:
            r = fitz.Rect(pts[0], pts[0])
            for p in pts[1:]:
                r |= p
        else:
            r = fitz.Rect(a.rect)           # unrotated, like vertices
        r = fitz.Rect(r.x0 - 14, r.y0 - 14, r.x1 + 14, r.y1 + 14)
        note = f"Code check ({f['section']}): {f['message']}"
        if f.get("required") is not None:
            note += f" Shown {f['actual']} {f['unit']}, needs " \
                    f"{f['required']} {f['unit']}."
        op = annotate.new_op("add_cloud", f["page"],
                             rect=[r.x0, r.y0, r.x1, r.y1],
                             color=[0.9, 0.1, 0.1], note=note,
                             subject="Code Check", author=author)
        if annotate.apply_op(doc, op):
            n += 1
    return n


def report_pdf(doc, path, project=""):
    from . import forms
    data = read(doc)
    findings, s = check(doc, data)
    f = forms.Form("Code Check", f"{project}   {EDITION}".strip(),
                   landscape=True)
    f.fields([("Occupancy", s["group"]),
              ("Sprinklered", "Yes" if s["sprinklered"] else "No"),
              ("Occupant load", s["occupants"]),
              ("Errors / warnings", f"{s['errors']} / {s['warnings']}")],
             cols=4)
    f.para("Screening only: verify against the code edition and local "
           "amendments adopted where the project is, and the exceptions "
           "that apply. Occupant loads use IBC Table 1004.5.", 8)
    sev = {"error": "Error", "warn": "Check", "info": "Note"}
    f.heading("Findings")
    f.table(["", "Section", "Where", "Finding", "Shown", "Required"],
            [[sev[x["severity"]], x["section"], x["where"], x["message"],
              "" if x["actual"] is None else f"{x['actual']} {x['unit']}",
              "" if x["required"] is None else f"{x['required']} {x['unit']}"]
             for x in findings] or [["", "", "", "No findings.", "", ""]],
            [0.7, 1.2, 1.8, 6, 1.1, 1.1],
            fills=[(1, 0.9, 0.9) if x["severity"] == "error" else
                   (1, 0.97, 0.85) if x["severity"] == "warn" else None
                   for x in findings] or None)
    f.heading("Occupant load")
    rows = []
    for sp in s["spaces"]:
        u = USES.get(sp["use"], USES["business"])
        rows.append([f"p.{sp['page'] + 1}", sp["name"], u[0],
                     f"{sp['area']:,.0f}",
                     f"{u[1]} {u[2]}" if u[1] else u[2], sp["load"]])
    rows.append(["", "Total", "", "", "", s["occupants"]])
    f.table(["Page", "Space", "Function of space", "Area (sf)",
             "Factor (sf/occ)", "Occupants"], rows,
            [0.6, 2.4, 4.4, 1, 1.2, 0.9], ["l", "l", "l", "r", "l", "r"])
    return f.save(path)
