"""Jon's own plain-English categories (brief 3.6, finding 21).

No vendor category code table is copied here. Every category belongs to
exactly one trade group (finding 19: the pasted list left 6 codes,
including water mitigation, in no group). Labels and groups can be
edited in the module's settings under "categories" (code -> [label, group]).
"""
from __future__ import annotations

# code: (label, trade group)
DEFAULT_CATEGORIES: dict[str, tuple[str, str]] = {
    "DEMOLITION": ("Demolition", "Site & general"),
    "GENERAL": ("General", "Site & general"),
    "CLEANING": ("Cleaning", "Site & general"),
    "WATER": ("Water mitigation", "Mitigation"),
    "FRAMING": ("Framing", "Structure"),
    "INSULATION": ("Insulation", "Structure"),
    "ROOFING": ("Roofing", "Exterior"),
    "SIDING": ("Siding", "Exterior"),
    "DRYWALL": ("Drywall", "Interior finishes"),
    "PAINTING": ("Painting", "Interior finishes"),
    "FLOORING": ("Flooring", "Interior finishes"),
    "CABINETS": ("Cabinets", "Interior finishes"),
    "PLUMBING": ("Plumbing", "Mechanical, electrical & plumbing"),
    "ELECTRICAL": ("Electrical", "Mechanical, electrical & plumbing"),
    "HVAC": ("HVAC", "Mechanical, electrical & plumbing"),
    "TAX": ("Sales tax", "Other"),
    "OTHER": ("Other", "Other"),
}


def categories() -> dict[str, tuple[str, str]]:
    from . import settings
    out = dict(DEFAULT_CATEGORIES)
    extra = settings.get("categories") or {}
    if isinstance(extra, dict):
        for code, v in extra.items():
            if isinstance(v, (list, tuple)) and len(v) == 2 and all(
                    isinstance(x, str) and x.strip() for x in v):
                out[str(code).upper()] = (v[0], v[1])
    return out


def label(code: str) -> str:
    return categories().get((code or "").upper(), (code, ""))[0]


def group_for(code: str) -> str:
    return categories().get((code or "").upper(), ("", "Other"))[1]


def is_known(code: str) -> bool:
    return (code or "").upper() in categories()


def trade_groups() -> list[str]:
    seen: list[str] = []
    for _, g in categories().values():
        if g not in seen:
            seen.append(g)
    return seen
