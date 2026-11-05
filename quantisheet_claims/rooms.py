"""Room measurements from length, width, height and openings (ClaimIT
0.2, Jon Oct 31: "make it better and easier to use").

All Decimal math, rounded once to 0.01 for display and once to qty_q4
when a measurement becomes a line quantity. A room with no dimensions
measures 0 everywhere (it can still hold lines).
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass
import re
from decimal import ROUND_HALF_UP, Decimal

from . import model as m
from .cents import parse_qty

# common openings, so a door or window is one click (feet)
DOOR = ("door", Decimal("3"), Decimal("6.67"))
WINDOW = ("window", Decimal("3"), Decimal("4"))

# measurement key -> (label, unit)
MEASURES = {
    "floor": ("Floor area", "SF"),
    "ceiling": ("Ceiling area", "SF"),
    "walls": ("Walls, less doors and windows", "SF"),
    "walls_ceiling": ("Walls and ceiling", "SF"),
    "perimeter": ("Floor perimeter", "LF"),
    "baseboard": ("Floor perimeter, less door openings", "LF"),
    "floor_sy": ("Floor area in square yards", "SY"),
    "each": ("Each (1)", "EA"),
}

_CENT = Decimal("0.01")


class RoomError(ValueError):
    pass


_FT_IN = re.compile(r"""^\s*(\d+(?:\.\d+)?)\s*(?:'|ft|feet)\s*-?\s*"""
                    r"""(?:(\d+(?:\.\d+)?)\s*(?:"|in|inches)?)?\s*$""", re.I)
_IN = re.compile(r"""^\s*(\d+(?:\.\d+)?)\s*(?:"|in|inches)\s*$""", re.I)


def _feet_text(v) -> str:
    """12'6", 12' 6, 12 ft 6 in, 6" -> decimal feet as text (r47 #9).
    Plain numbers pass through."""
    t = str(v).strip()
    m_ = _FT_IN.match(t)
    if m_:
        ft = Decimal(m_.group(1))
        inch = Decimal(m_.group(2) or "0")
        if inch >= 12:
            raise RoomError(f"{v!r}: inches must be under 12")
        return str(ft + inch / 12)
    m_ = _IN.match(t)
    if m_:
        return str(Decimal(m_.group(1)) / 12)
    return t


def _d(v) -> Decimal:
    try:
        d = Decimal(_feet_text(v) or "0")
    except Exception as e:                       # decimal.InvalidOperation
        raise RoomError(f"{v!r} is not a number") from e
    if not d.is_finite():
        raise RoomError(f"{v!r} is not a number")
    if d < 0 or d > 10_000:
        raise RoomError(f"{v} ft is out of range (0 to 10,000)")
    return d


@dataclass(frozen=True)
class Measures:
    floor: Decimal
    ceiling: Decimal
    walls_gross: Decimal
    openings: Decimal
    walls: Decimal
    walls_ceiling: Decimal
    perimeter: Decimal
    floor_sy: Decimal
    baseboard: Decimal = Decimal(0)

    def get(self, key: str) -> Decimal:
        if key == "each":
            return Decimal(1)
        if key not in MEASURES:
            raise RoomError(f"unknown measurement {key!r}")
        return getattr(self, key)


PART_KINDS = {"bump": "Alcove / extra leg (adds floor)",
              "cut": "Corner cut out (L-shape)"}


def _parts(room: m.Room, L: Decimal, W: Decimal):
    """(floor change, perimeter change) from the room's odd-shape parts.
    A piece built out from a wall adds its area and two side walls
    (2 x depth); a corner taken out removes its area and leaves the
    perimeter as it was (the two new walls replace the two cut away)."""
    add = Decimal(0)
    per = Decimal(0)
    big = max(L, W)
    for p in getattr(room, "parts", ()) or ():
        a, d = _d(p.along_ft), _d(p.depth_ft)
        if not (a and d):
            continue
        if p.kind == "bump":
            add += a * d
            per += 2 * d
        elif p.kind == "cut":
            if not (L and W):
                raise RoomError("a corner cut needs the room's length and "
                                "width first")
            if a >= big or d >= big or (a >= L and d >= L) or \
                    (a >= W and d >= W) or a * d >= L * W:
                raise RoomError(f"the corner cut ({a} x {d} ft) is as big "
                                "as the room")
            add -= a * d
        else:
            raise RoomError(f"unknown room part {p.kind!r}")
    return add, per


def measure(room: m.Room) -> Measures:
    L, W, H = (_d(room.length_ft), _d(room.width_ft), _d(room.height_ft))
    extra, extra_per = _parts(room, L, W)
    floor = L * W + extra if (L and W) else Decimal(0)
    perim = 2 * (L + W) + extra_per if (L and W) else Decimal(0)
    gross = perim * H
    opening = sum((_d(o.width_ft) * _d(o.height_ft) for o in room.openings),
                  Decimal(0))
    walls = max(Decimal(0), gross - opening)
    doors = sum((_d(o.width_ft) for o in room.openings if o.kind == "door"),
                Decimal(0))
    base = max(Decimal(0), perim - doors)
    q = lambda d: d.quantize(_CENT, rounding=ROUND_HALF_UP)   # noqa: E731
    return Measures(floor=q(floor), ceiling=q(floor), walls_gross=q(gross),
                    openings=q(opening), walls=q(walls),
                    walls_ceiling=q(walls + floor), perimeter=q(perim),
                    floor_sy=q(floor / 9), baseboard=q(base))


def qty_q4(room: m.Room, key: str) -> int:
    """A measurement as a line quantity (ten-thousandths)."""
    return parse_qty(str(measure(room).get(key)))


def requantify(line, room):
    """A line's quantity again from `room`, when it came from a room
    measurement (line.qty_from); None when it was typed by hand."""
    if not getattr(line, "qty_from", "") or line.qty_from not in MEASURES:
        return None
    from .cents import div_round_half_up
    f = Decimal(line.qty_factor or "1")
    num, den = f.as_integer_ratio()
    return div_round_half_up(qty_q4(room, line.qty_from) * num, den)


def unit_for(key: str) -> str:
    return MEASURES[key][1]


def new_room(name: str, length="0", width="0", height="8", doors=0,
             windows=0, structure_id="") -> m.Room:
    name = (name or "").strip()
    if not name:
        raise RoomError("a room needs a name")
    ops = tuple(m.Opening(kind=k, width_ft=w, height_ft=h)
                for k, w, h, n in ((*DOOR, doors), (*WINDOW, windows))
                for _ in range(int(n)))
    room = m.Room(id=m.new_id(), name=name, structure_id=structure_id,
                  length_ft=_d(length), width_ft=_d(width),
                  height_ft=_d(height), openings=ops)
    measure(room)                                 # checks the numbers
    return room


def count(room: m.Room, kind: str) -> int:
    return sum(1 for o in room.openings if o.kind == kind)


def set_openings(room: m.Room, doors: int, windows: int) -> m.Room:
    """Keep any other openings; set the number of standard doors and
    windows."""
    other = tuple(o for o in room.openings if o.kind not in ("door", "window"))
    ops = other + tuple(m.Opening(kind=k, width_ft=w, height_ft=h)
                        for k, w, h, n in ((*DOOR, doors), (*WINDOW, windows))
                        for _ in range(int(n)))
    return dataclasses.replace(room, openings=ops)


def set_part(room: m.Room, kind: str, along="0", depth="0") -> m.Room:
    """The room with its (first) part of `kind` set to along x depth;
    0 or blank removes it. Other parts are kept."""
    if kind not in PART_KINDS:
        raise RoomError(f"unknown room part {kind!r}")
    a, d = _d(along or "0"), _d(depth or "0")
    rest = tuple(p for p in room.parts if p.kind != kind)
    same = [p for p in room.parts if p.kind == kind]
    new = (m.RoomPart(kind=kind, along_ft=a, depth_ft=d),) if (a and d) \
        else ()
    out = dataclasses.replace(room, parts=rest + new + tuple(same[1:]))
    measure(out)                                  # checks it
    return out


def part(room: m.Room, kind: str):
    for p in room.parts:
        if p.kind == kind:
            return p
    return None


def size_text(room: m.Room) -> str:
    """'12 x 10 x 8 ft', plus the odd-shape parts (PDF / CSV / Excel)."""
    t = f"{room.length_ft} x {room.width_ft} x {room.height_ft} ft"
    for p in room.parts:
        if p.along_ft and p.depth_ft:
            t += (" + " if p.kind == "bump" else " - ") + \
                f"{p.along_ft} x {p.depth_ft}"
    return t


def summary(room: m.Room) -> str:
    ms = measure(room)
    if not ms.floor:
        return f"{room.name}: no dimensions yet"
    if room.parts:
        return (f"{room.name}: {size_text(room)} - floor {ms.floor} SF, "
                f"walls {ms.walls} SF, perimeter {ms.perimeter} LF")
    return (f"{room.name}: {room.length_ft} x {room.width_ft} ft, "
            f"{room.height_ft} ft high - floor {ms.floor} SF, walls "
            f"{ms.walls} SF, perimeter {ms.perimeter} LF")
