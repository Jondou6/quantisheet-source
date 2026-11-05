"""Room finishes: floor, base, ceiling and wall-paint quantities from the
rooms taken off (autotakeoff.all_rooms) and the finish schedule.

    room_finishes(rooms, finish_schedule=None, doors=None)

A pure function - no PDF, no Qt - so the schedule can come from anywhere
(the finish-schedule reader, a spreadsheet, typed in).

Rooms: dicts as all_rooms gives them. Used: "name" (the room number is
read from it, "OFFICE 102A" -> 102A), "number" if present, "sqft" (the
floor area taken off, sq ft - the tag's area when prefer_tags swapped it
in), "net_sf" (the trace), "perimeter_lf" (the traced outline, ft),
"flags", "review", and optionally "doors" (a list of door widths, ft) and
"ceiling_height" / "wall_height" (ft).

Finish schedule: a list of dicts, one per row. Keys are read loosely
(case and spacing don't matter):

    room / number / room_no / no / rm   the room number ("101", "115.1";
                                        several: "101, 102" or a list)
    name / room_name                    used only when a row has no number
    floor / floor_finish / flr          floor finish code   ("CPT-1")
    base / base_finish                  base code           ("RB-1")
    walls / wall / wall_finish          wall finish code ("PT-1"), or
                                        {"north": .., "east": ..} or a list
    ceiling / ceiling_finish / clg      ceiling type        ("ACT-1")
    ceiling_height / clg_ht / height    9, "9'-0\"", "108\"", "9 FT"
    wall_height                         paint height when not to the
                                        ceiling

Doors (optional): a list of dicts from a door schedule: "width" (ft or
"3'-0\"") and the room(s) it opens from - "rooms": [..], or "room" /
"from" / "to", or else the door number ("101A" opens from room 101).
Each opening is taken off the base of every room it serves.

Returns {"rooms": [per room], "floor": {code: SF}, "base": {code: LF},
"ceiling": {code: SF}, "walls": {code: SF}, "flags": [text]}; codes not
known are "(unknown)". Per room: number, name, floor_sf, floor_code,
base_lf, base_code, door_lf, ceiling_sf, ceiling_code, ceiling_height_ft,
wall_sf, wall_code, wall_height_ft, flags, review.

Quantities, never guesses: a room the schedule doesn't list keeps its
floor SF and base LF with its codes unknown and is flagged; wall paint
needs a height, and is left out (flagged) without one; door openings
aren't taken out of the wall paint (they are listed). Without a schedule
only floor SF and base LF come out, codes unknown.
"""
import re

UNKNOWN = "(unknown)"

_ROOM_KEYS = ("room", "number", "room_no", "room_number", "roomno", "no",
              "rm", "room_#", "rm_no")
_NAME_KEYS = ("name", "room_name", "roomname")
_FLOOR_KEYS = ("floor", "floor_finish", "flr", "flooring", "floor_code")
_BASE_KEYS = ("base", "base_finish", "base_code", "wall_base")
_WALL_KEYS = ("walls", "wall", "wall_finish", "wall_finishes", "wall_code")
_CEIL_KEYS = ("ceiling", "ceiling_finish", "clg", "ceiling_type",
              "ceiling_code", "clg_type")
_CEIL_HT_KEYS = ("ceiling_height", "clg_ht", "ceiling_ht", "clg_height",
                 "height", "ceiling_hgt", "ht")
_WALL_HT_KEYS = ("wall_height", "paint_height", "wall_ht")
_NO_CEILING = {"NONE", "OPEN", "EXPOSED", "EXP", "N/A", "NA", "-", "--",
               "OPEN TO STRUCTURE", "OTS"}


def _norm_key(k):
    return re.sub(r"[\s.\-]+", "_", str(k).strip().lower())


def _get(row, keys):
    nk = {_norm_key(k): v for k, v in row.items()}
    for k in keys:
        v = nk.get(k)
        if v not in (None, ""):
            return v
    return None


def _code(v):
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def norm_room(v):
    """'Rm 101' / '101.' / ' 102a ' -> '101' / '101' / '102A'."""
    s = str(v or "").strip().upper()
    s = re.sub(r"^(RM|ROOM)\.?\s*", "", s)
    s = s.rstrip(".").strip()
    return s


def _room_list(v):
    if v is None:
        return []
    if isinstance(v, (list, tuple, set)):
        out = []
        for x in v:
            out += _room_list(x)
        return out
    return [norm_room(x) for x in re.split(r"[,;/&]|\band\b", str(v))
            if norm_room(x)]


def parse_feet(v):
    """A length in feet from 9, 9.5, "9'-0\"", "9' 6\"", "108\"", "9 FT",
    "10'-6"; None for "VARIES", "OPEN", blanks."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v) if v > 0 else None
    s = str(v).strip().upper().replace("’", "'").replace("”", '"') \
        .replace("''", '"')
    if not s:
        return None
    m = re.match(r"^(\d+(?:\.\d+)?)\s*'\s*-?\s*(?:(\d+(?:\.\d+)?)"
                 r"(?:\s+(\d+)/(\d+))?\s*\"?)?$", s)
    if m:
        ft = float(m.group(1))
        inch = float(m.group(2) or 0)
        if m.group(3):
            inch += float(m.group(3)) / float(m.group(4))
        return ft + inch / 12
    m = re.match(r"^(\d+(?:\.\d+)?)\s*(\"|IN\.?|INCH(?:ES)?)$", s)
    if m:
        return float(m.group(1)) / 12
    m = re.match(r"^(\d+(?:\.\d+)?)\s*(FT\.?|FEET|')?$", s)
    if m:
        return float(m.group(1))
    return None


def _room_no(room):
    if room.get("number"):
        return norm_room(room["number"])
    try:
        from .autotakeoff import room_number
        return norm_room(room_number(room.get("name")))
    except ImportError:                            # pragma: no cover
        toks = (room.get("name") or "").split()
        return norm_room(toks[-1]) if toks else ""


def _room_words(name):
    return " ".join(t for t in (name or "").upper().split()
                    if not re.search(r"\d", t))


def _wall_codes(v):
    """A row's wall finish: one code, or several (by side) - a list of
    distinct codes in order."""
    if v is None:
        return []
    if isinstance(v, dict):
        vals = list(v.values())
    elif isinstance(v, (list, tuple)):
        vals = list(v)
    else:
        vals = re.split(r"[,;/]", str(v)) if re.search(r"[,;]", str(v)) \
            else [v]
    out = []
    for x in vals:
        c = _code(x)
        if c and c not in out:
            out.append(c)
    return out


def _door_map(doors, numbers):
    """room number -> [door widths, ft] from the door schedule rows."""
    out = {}
    unplaced = []
    for d in doors or ():
        w = parse_feet(d.get("width") if isinstance(d, dict) else d)
        if not w:
            unplaced.append(d)
            continue
        rooms = []
        for k in ("rooms", "room", "from", "to", "from_room", "to_room"):
            rooms += _room_list(_get(d, (k,)))
        if not rooms:
            num = norm_room(_get(d, ("number", "door", "door_no", "mark",
                                     "no")) or "")
            if num in numbers:
                rooms = [num]
            else:
                base = re.sub(r"[A-Z]+$", "", num)       # 101A -> 101
                if base in numbers:
                    rooms = [base]
        rooms = [r for r in dict.fromkeys(rooms) if r in numbers]
        if not rooms:
            unplaced.append(d)
            continue
        for r in rooms:
            out.setdefault(r, []).append(w)
    return out, unplaced


def _add(tot, code, qty):
    if qty is None:
        return
    key = code or UNKNOWN
    tot[key] = tot.get(key, 0.0) + qty


def room_finishes(rooms, finish_schedule=None, doors=None,
                  open_height=None):
    """Floor SF and ceiling SF per code, base LF (perimeter less door
    openings) per code and wall-paint SF (perimeter x height) per code,
    room by room and in total. See the module notes for the inputs."""
    sched = list(finish_schedule or [])
    flags = []
    numbers = [_room_no(r) for r in rooms]
    by_no, by_name = {}, {}
    for row in sched:
        for n in _room_list(_get(row, _ROOM_KEYS)):
            if n in by_no and by_no[n] is not row:
                flags.append(f"room {n} is in the finish schedule twice - "
                             "the first row is used")
                continue
            by_no[n] = row
        if not _get(row, _ROOM_KEYS):
            nm = _room_words(str(_get(row, _NAME_KEYS) or ""))
            if nm:
                by_name.setdefault(nm, []).append(row)
    if not sched:
        flags.append("no finish schedule - floor SF and base LF only; "
                     "finish codes unknown")
    dmap, unplaced = _door_map(doors, set(numbers))
    if doors and unplaced:
        flags.append(f"{len(unplaced)} door(s) could not be matched to a "
                     "room - their openings are not taken off the base")
    # a room whose height reads VARIES / blank / '-': its wall paint is
    # taken at the schedule's most common height, as an ASSUMPTION that is
    # flagged (and the room listed for review); no height anywhere in the
    # schedule, no paint
    hts = []
    for row in sched:
        h = parse_feet(_get(row, _WALL_HT_KEYS)) or \
            parse_feet(_get(row, _CEIL_HT_KEYS))
        if h:
            hts.append(round(h, 2))
    usual = max(set(hts), key=lambda h: (hts.count(h), h)) if hts else None
    out_rooms = []
    tot = {"floor": {}, "base": {}, "ceiling": {}, "walls": {}}
    for room, num in zip(rooms, numbers):
        rf = []
        name = room.get("name") or ""
        if room.get("review"):
            rf.append("room outline needs review (see its takeoff flags)")
        row = by_no.get(num) if num else None
        if row is None and sched:
            cand = by_name.get(_room_words(name), [])
            if len(cand) == 1:
                row = cand[0]
                rf.append("matched to the finish schedule by name, not "
                          "number")
        if sched and row is None:
            rf.append("not in the finish schedule - codes unknown")
        if not sched:
            rf.append("finish codes unknown (no finish schedule)")
        floor_sf = room.get("sqft", room.get("net_sf"))
        perim = room.get("perimeter_lf")
        # door openings come off the base
        widths = list(room.get("doors") or []) + dmap.get(num, [])
        door_lf = sum(widths)
        if perim is None:
            base_lf = None
            rf.append("no perimeter - base and wall paint not measured")
        else:
            base_lf = max(0.0, perim - door_lf)
            if not widths:
                rf.append("door widths unknown - base not reduced for "
                          "openings")
        floor_code = _code(_get(row, _FLOOR_KEYS)) if row else None
        base_code = _code(_get(row, _BASE_KEYS)) if row else None
        ceil_code = _code(_get(row, _CEIL_KEYS)) if row else None
        walls = _wall_codes(_get(row, _WALL_KEYS)) if row else []
        ch = parse_feet(room.get("ceiling_height"))
        if ch is None and row:
            ch = parse_feet(_get(row, _CEIL_HT_KEYS))
        wh = parse_feet(room.get("wall_height"))
        if wh is None and row:
            wh = parse_feet(_get(row, _WALL_HT_KEYS))
        if wh is None:
            wh = ch
        assumed = False
        if wh is None and row is not None and open_height:
            # no height in the schedule ('VARIES', '-'): the walls run up
            # to the structure, so the paint does (open_height = (ft, why))
            wh = open_height[0]
            rf.append(f"wall height {wh:.2f} ft to the structure (this "
                      f"room's reads '{_get(row, _CEIL_HT_KEYS) or 'blank'}'"
                      f") - {open_height[1]}")
        if wh is None and row is not None and usual:
            wh, assumed = usual, True
            rf.append(f"wall height ASSUMED {usual:g} ft (the finish "
                      "schedule's most common height; this room's reads "
                      f"'{_get(row, _CEIL_HT_KEYS) or 'blank'}') - check it")
        rec = {"number": num, "name": name, "floor_sf": floor_sf,
               "floor_code": floor_code, "base_lf": base_lf,
               "base_code": base_code, "door_lf": door_lf,
               "ceiling_sf": None, "ceiling_code": ceil_code,
               "ceiling_height_ft": ch, "wall_sf": None,
               "wall_code": None, "wall_height_ft": wh,
               "wall_height_assumed": assumed}
        _add(tot["floor"], floor_code, floor_sf)
        _add(tot["base"], base_code, base_lf)
        if sched:
            if ceil_code and ceil_code.upper() in _NO_CEILING:
                rf.append(f"ceiling '{ceil_code}' - no ceiling area")
            else:
                rec["ceiling_sf"] = floor_sf
                _add(tot["ceiling"], ceil_code, floor_sf)
                if not ceil_code:
                    rf.append("ceiling type unknown")
            if perim is not None and wh:
                rec["wall_sf"] = perim * wh
                if len(walls) > 1:
                    code = "/".join(walls)
                    rf.append("several wall finishes (" + ", ".join(walls) +
                              ") - all wall SF under the combined code; "
                              "split by wall by hand")
                else:
                    code = walls[0] if walls else None
                    if not walls:
                        rf.append("wall finish unknown")
                rec["wall_code"] = code
                _add(tot["walls"], code, rec["wall_sf"])
                if widths:
                    rf.append(f"door openings ({door_lf:,.1f} LF wide) "
                              "not taken out of the wall paint")
            elif perim is not None:
                rf.append("no ceiling or wall height - wall paint not "
                          "measured")
        rec["flags"] = rf
        rec["review"] = bool(room.get("review")) or row is None or \
            any(f.startswith(("several wall", "no ceiling or wall",
                              "no perimeter", "wall height ASSUMED"))
                for f in rf)
        out_rooms.append(rec)
    unused = [n for n in by_no if n not in set(numbers)]
    if unused:
        flags.append("finish schedule rooms not found on the plan: " +
                     ", ".join(sorted(unused)[:12]))
    return {"rooms": out_rooms, "floor": tot["floor"], "base": tot["base"],
            "ceiling": tot["ceiling"], "walls": tot["walls"],
            "flags": flags}
