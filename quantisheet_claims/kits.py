"""Line kits: the user's own groups of library items, each with the room
measurement its quantity comes from (ClaimIT 0.2).

Example a user might make: "Water - 2 ft flood cut" = their own drywall
code on 'perimeter' x 2, their own baseboard code on 'perimeter', their
own paint code on 'walls'. Nothing is shipped: kits start empty and only
hold codes from the user's own library. Stored in the module's settings
("kits": name -> [{"code", "measure", "factor"}]).
"""
from __future__ import annotations

import dataclasses
from decimal import Decimal

from . import library, rooms, settings
from . import model as m
from .cents import div_round_half_up

SETTING = "kits"
MAX_ITEMS = 200


# which room measurements can give each unit (Each fits every unit; the
# perimeter gives square feet when "times" is the height, e.g. a 2 ft
# flood cut = perimeter x 2)
FITS = {"SF": ("floor", "ceiling", "walls", "walls_ceiling", "perimeter",
               "baseboard"),
        "SY": ("floor_sy",),
        "LF": ("perimeter", "baseboard")}


class KitError(ValueError):
    pass


def all_kits() -> dict:
    return dict(settings.get(SETTING) or {})


def _factor(v) -> str:
    try:
        d = Decimal(str(v).strip() or "1")
    except Exception as e:
        raise KitError(f"{v!r} is not a number") from e
    if not d.is_finite():
        raise KitError(f"{v!r} is not a number")
    if d <= 0 or d > 1000:
        raise KitError(f"factor {v} must be above 0 and at most 1000")
    return str(d)


def save_kit(name: str, items) -> dict:
    """items: [(code, measure, factor)]. Codes must be in the library."""
    name = (name or "").strip()
    if not name:
        raise KitError("a kit needs a name")
    lib = library.items()
    rows = []
    for code, measure, factor in items:
        c = str(code or "").strip().upper()
        if c not in lib:
            raise KitError(f"{code!r} isn't in your library")
        if measure not in rooms.MEASURES:
            raise KitError(f"unknown measurement {measure!r}")
        unit = lib[c]["unit"]
        if measure != "each" and measure not in FITS.get(unit, ()):
            fits = [rooms.MEASURES[k][0] for k in FITS.get(unit, ())]
            raise KitError(
                f"{c} is priced per {unit}, which "
                f"{rooms.MEASURES[measure][0].lower()} can't give" +
                (f" - use {' or '.join(fits)}" if fits else
                 " - use Each, with how many as the times"))
        rows.append({"code": c, "measure": measure, "factor": _factor(factor)})
    if not rows:
        raise KitError("a kit needs at least one item")
    if len(rows) > MAX_ITEMS:
        raise KitError(f"at most {MAX_ITEMS} items in a kit")
    kits = all_kits()
    kits[name] = rows
    settings.set(SETTING, kits)
    return kits


def remove_kit(name: str) -> None:
    kits = all_kits()
    kits.pop(name, None)
    settings.set(SETTING, kits)


def apply(name: str, room: m.Room, structure_id: str = "",
          first_ordinal: int = 0) -> tuple:
    """Lines for one room: each item's quantity = the room measurement x
    the factor, rounded once."""
    kit = all_kits().get(name)
    if not kit:
        raise KitError(f"no kit named {name!r}")
    out = []
    for i, row in enumerate(kit):
        base = rooms.qty_q4(room, row["measure"])
        f = Decimal(row["factor"])
        num, den = f.as_integer_ratio()
        qty = div_round_half_up(base * num, den)
        try:
            ln = library.line_from(row["code"], qty_q4=qty,
                                   structure_id=structure_id or
                                   room.structure_id,
                                   ordinal=first_ordinal + i)
        except library.LibraryError as e:
            raise KitError(str(e)) from e
        out.append(dataclasses.replace(ln, room_id=room.id,
                                       note=f"kit: {name}",
                                       qty_from=row["measure"],
                                       qty_factor=row["factor"]))
    return tuple(out)
