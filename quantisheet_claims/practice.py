"""A made-up practice claim to try every tab on (ClaimIT 0.2), like
QuantiSheet's practice drawings. Everything in it is invented: the
insured is "Example Owner", the address is example.invalid, and every
price is a round practice number - not a price to bid with. It is never
saved unless the user saves it.
"""
from __future__ import annotations

import datetime as _dt

from . import model as m
from . import rooms

NUMBER = "PRACTICE-0001"


def _line(code, desc, cat, qty, unit, cents, room, ordinal, dep_bp=0):
    from .cents import parse_qty
    return m.Line(id=m.new_id(), item_code=code,
                  description=f"{desc} (practice price)", category=cat,
                  qty_q4=parse_qty(qty), unit=unit,
                  unit_cost=m.UnitCost(other=cents), room_id=room.id,
                  structure_id=room.structure_id, ordinal=ordinal,
                  dep_bp=dep_bp)


def claim() -> m.Claim:
    sid = m.new_id()
    kitchen = rooms.new_room("Kitchen", "14", "12", "8", doors=1, windows=1,
                             structure_id=sid)
    hall = rooms.new_room("Hall", "12", "4", "8", doors=2, structure_id=sid)
    ms = rooms.measure(kitchen)
    lines = (
        _line("EX-DEMO", "Remove wet drywall, 2 ft up", "DEMOLITION",
              str(ms.perimeter * 2), "SF", 100, kitchen, 0),
        _line("EX-DRY", "New drywall, 2 ft up", "DRYWALL",
              str(ms.perimeter * 2), "SF", 300, kitchen, 1, dep_bp=1000),
        _line("EX-PAINT", "Paint walls", "PAINTING", str(ms.walls), "SF",
              100, kitchen, 2, dep_bp=2000),
        _line("EX-FLOOR", "Replace vinyl floor", "FLOORING",
              str(rooms.measure(hall).floor), "SF", 500, hall, 3,
              dep_bp=3000),
        _line("EX-DRYOUT", "Drying equipment, 3 days", "WATER", "3", "EA",
              10000, hall, 4),
    )
    loss = (_dt.date.today() - _dt.timedelta(days=10)).isoformat()
    return m.Claim(
        id=m.new_id(), claim_number=NUMBER, claim_type="residential",
        insured="Example Owner", carrier="Example Insurance",
        loss_address="1 Example Street, example.invalid",
        loss_date=loss, peril="Water",
        deductible=m.DeductibleSpec(amount_cents=100_000),
        structures=(m.Structure(id=sid, name="Dwelling", kind="dwelling",
                                limit_cents=30_000_000),),
        rooms=(kitchen, hall), lines=lines,
        diary=(m.DiaryEntry(id=m.new_id(), on=loss, kind="call",
                            text="Practice: owner reported water under "
                                 "the kitchen sink."),))
