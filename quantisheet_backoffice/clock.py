"""Today's date and time, overridable in tests (no hidden wall-clock reads)."""
from __future__ import annotations

from datetime import date, datetime

_fixed: datetime | None = None


def set_now(dt: datetime | None) -> None:
    global _fixed
    _fixed = dt


def now() -> datetime:
    return _fixed if _fixed is not None else datetime.now()


def today() -> date:
    return now().date()


def iso_now() -> str:
    return now().isoformat(timespec="seconds")


def d(v) -> date:
    """'2026-10-22' / date -> date."""
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return date.fromisoformat(str(v)[:10])
