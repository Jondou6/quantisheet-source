"""Takeoff item -> claim line(s) (brief 3.8). Stored per claim.

line qty_q4 = scale_qty(parse_qty(item.qty), factor_bp). Waste is stored
on the line, not applied to the qty. All integer math (finding 27); the
pasted takeoff.ts room math is not ported (finding 20) - QuantiSheet
measures quantities on the drawings and hands them over as text.
"""
from __future__ import annotations

from datetime import datetime

from . import categories
from .cents import scale_qty
from .interface import TakeoffItem
from .model import ClaimRecipe, Line, new_id, unit_from_text


class RecipeError(ValueError):
    pass


def check_recipe(r: ClaimRecipe) -> None:
    """Finding 26: a recipe's category must be a real category."""
    if not categories.is_known(r.category):
        raise RecipeError(f"recipe {r.item_code!r}: unknown category {r.category!r}")
    if unit_from_text(r.unit) is None:
        raise RecipeError(f"recipe {r.item_code!r}: unknown unit {r.unit!r}")
    if r.factor_bp < 0 or r.waste_bp < 0:
        raise RecipeError("factor and waste can't be negative")


def matches(r: ClaimRecipe, item: TakeoffItem) -> bool:
    return (r.name.strip().lower() == item.name.strip().lower()
            and unit_from_text(r.unit) == unit_from_text(item.unit))


def lines_for(item: TakeoffItem, recipes, structure_id: str = "",
              room_id: str = "", group_id: str = "") -> list[Line]:
    """Every matching recipe makes one line. No match -> one 'needs review'
    line at $0 unit cost carrying the takeoff qty, so nothing is dropped."""
    q = item.qty_q4
    now = datetime.now().isoformat(timespec="seconds")
    out = []
    note = f"takeoff: {item.name} p.{item.page_label}"
    for r in recipes:
        if not matches(r, item):
            continue
        check_recipe(r)
        out.append(Line(
            id=new_id(), item_code=r.item_code,
            description=r.description or r.item_code,
            category=r.category.upper(), qty_q4=scale_qty(q, r.factor_bp),
            unit=unit_from_text(r.unit) or "EA", unit_cost=r.unit_cost,
            structure_id=structure_id, room_id=room_id, group_id=group_id,
            waste_bp=r.waste_bp, note=note, origin="takeoff", created_at=now))
    if not out:
        u = unit_from_text(item.unit)
        from .model import UnitCost
        out.append(Line(
            id=new_id(), item_code="REVIEW", description=item.name,
            category="OTHER", qty_q4=q, unit=u or "EA", unit_cost=UnitCost(),
            structure_id=structure_id, room_id=room_id, group_id=group_id,
            note=note + ("" if u else f" (unknown unit {item.unit!r})")
            + " - needs review", origin="takeoff", created_at=now))
    return out
