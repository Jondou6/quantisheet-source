"""The ONLY link between QuantiSheet and the claims module (brief 3.8).

QuantiSheet -> module, one way, as a JSON file:

{"interface_version": 1,
 "source": {"file": "Smith Residence.pdf", "taken_at": "2026-10-20T11:40"},
 "items": [{"name": "Interior Wall", "qty": "1234.5000", "unit": "sf",
            "page_label": "A-101", "color": "#ff0000"}]}

- qty is a decimal STRING (no floats cross the line).
- One item per (name, unit, page_label, color), summed by QuantiSheet.
- load_snapshot() checks: interface_version == 1, at most 20,000 items,
  every field a string, name <= 120 chars, qty >= 0 and readable, color
  "" or "#rrggbb". A bad item is listed as rejected, never set to 0.
- The module copies items into a claim; it never re-reads the PDF, never
  writes to it, and never touches ~/.quantisheet.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from .cents import MoneyError, parse_qty

INTERFACE_VERSION = 1
MAX_ITEMS = 20_000
MAX_NAME = 120
MAX_BYTES = 50 * 1024 * 1024
_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
FIELDS = ("name", "qty", "unit", "page_label", "color")


class SnapshotError(ValueError):
    """The whole snapshot can't be used (bad version, too big, not JSON)."""


@dataclass(frozen=True)
class TakeoffItem:
    name: str
    qty: str
    unit: str
    page_label: str
    color: str

    @property
    def qty_q4(self) -> int:
        return parse_qty(self.qty)


@dataclass(frozen=True)
class Rejected:
    index: int
    reason: str
    raw: str


@dataclass(frozen=True)
class TakeoffSnapshot:
    source_file: str
    taken_at: str
    items: tuple[TakeoffItem, ...]
    rejected: tuple[Rejected, ...] = ()


def check_item(raw) -> TakeoffItem:
    if not isinstance(raw, dict):
        raise ValueError("item is not an object")
    vals = {}
    for f in FIELDS:
        v = raw.get(f, "" if f in ("color", "page_label") else None)
        if not isinstance(v, str):
            raise ValueError(f"{f} must be text")
        vals[f] = v
    if not vals["name"].strip():
        raise ValueError("name is blank")
    if len(vals["name"]) > MAX_NAME:
        raise ValueError(f"name longer than {MAX_NAME} characters")
    try:
        q = parse_qty(vals["qty"])
    except MoneyError as e:
        raise ValueError(f"qty: {e}") from None
    if q < 0:
        raise ValueError("qty is negative")
    if vals["color"] and not _COLOR.match(vals["color"]):
        raise ValueError("color must be #rrggbb or blank")
    return TakeoffItem(**vals)


def parse_snapshot(data) -> TakeoffSnapshot:
    if not isinstance(data, dict):
        raise SnapshotError("snapshot is not a JSON object")
    if data.get("interface_version") != INTERFACE_VERSION:
        raise SnapshotError(
            f"interface_version {data.get('interface_version')!r} is not "
            f"supported (this module reads version {INTERFACE_VERSION})")
    items = data.get("items")
    if not isinstance(items, list):
        raise SnapshotError("items must be a list")
    if len(items) > MAX_ITEMS:
        raise SnapshotError(f"{len(items):,} items; the limit is {MAX_ITEMS:,}")
    src = data.get("source") if isinstance(data.get("source"), dict) else {}
    ok, bad = [], []
    for i, raw in enumerate(items):
        try:
            ok.append(check_item(raw))
        except ValueError as e:
            bad.append(Rejected(i, str(e), json.dumps(raw)[:200]))
    return TakeoffSnapshot(str(src.get("file", "")), str(src.get("taken_at", "")),
                           tuple(ok), tuple(bad))


def load_snapshot(path: str) -> TakeoffSnapshot:
    import os
    if os.path.getsize(path) > MAX_BYTES:
        raise SnapshotError("snapshot file is too large")
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except ValueError as e:
        raise SnapshotError(f"not valid JSON: {e}") from None
    return parse_snapshot(data)
