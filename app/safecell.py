"""Spreadsheet formula-injection guard for CSV and Excel exports (0.13.5
security fix).

Text that came from a drawing, a project record or a sub's proposal can
start with "=", "+", "-" or "@" (or a tab / carriage return). Excel,
LibreOffice and Google Sheets run such a cell as a formula when the export
is opened - "=HYPERLINK(...)" or a DDE call - so every user-text cell goes
through here:

* CSV: ``writer(f)`` (a drop-in csv.writer), ``safe_cell(v)`` and
  ``safe_row(row)`` put a leading apostrophe on such text (the spreadsheet
  then shows it as text);
* Excel (openpyxl): ``append_row(ws, row)`` / ``set_text(cell, v)`` store
  the text as a text cell (data type "s", quote prefix) instead, so no
  apostrophe shows. The program's own formulas are wrapped in
  ``Formula("=SUM(...)")`` and left alone.

Numbers and plain numeric text ("-312.47", "+5") are never changed. The
same rules as quantisheet_backoffice.fileguard.safe_cell (Back Office keeps
its own copy: it never imports the app package).
"""
from __future__ import annotations

import csv
import re

FORMULA_START = ("=", "+", "-", "@", "\t", "\r")
_PLAIN_NUMBER = re.compile(r"^[+-]?(\d[\d,]*)?(\.\d+)?%?$")


class Formula(str):
    """A formula the program itself builds (=SUM, =IF ...): kept live."""
    __slots__ = ()


def risky(v) -> bool:
    """True for text a spreadsheet would run as a formula."""
    return isinstance(v, str) and not isinstance(v, Formula) and \
        len(v) > 1 and v.startswith(FORMULA_START) and v.strip() != "-" and \
        not (_PLAIN_NUMBER.match(v) and any(c.isdigit() for c in v))


def safe_cell(v):
    """CSV cell: risky text gets a leading apostrophe; anything else
    (numbers, None, plain text, the program's Formula) is returned as is."""
    if isinstance(v, Formula):
        return str(v)
    return "'" + v if risky(v) else v


def safe_row(row):
    return [safe_cell(v) for v in row]


def unquote(v):
    """Reading back a CSV the program wrote: the apostrophe safe_cell put
    in front of risky text comes off ("'=1+1" -> "=1+1"), so an export /
    import round trip keeps the text as it was. Anything else unchanged."""
    if isinstance(v, str) and v.startswith("'") and risky(v[1:]):
        return v[1:]
    return v


class _SafeWriter:
    """csv.writer whose rows go through safe_row."""

    def __init__(self, w):
        self._w = w

    @property
    def dialect(self):
        return self._w.dialect

    def writerow(self, row):
        return self._w.writerow(safe_row(row))

    def writerows(self, rows):
        for r in rows:
            self.writerow(r)


def writer(f, *args, **kw):
    """Drop-in for csv.writer(f, ...) that neutralises risky text."""
    return _SafeWriter(csv.writer(f, *args, **kw))


_KEEP = object()


def set_text(cell, v=_KEEP):
    """Excel cell: write `v` (or keep the cell's value) so that risky text
    is stored as text, not as a formula. No visible apostrophe. A Formula
    is written as a live formula."""
    if v is not _KEEP:
        cell.value = str(v) if isinstance(v, Formula) else v
        if isinstance(v, Formula):
            return cell
    v = cell.value
    if risky(v):
        cell.value = v
        cell.data_type = "s"
        try:
            cell.quotePrefix = True
        except Exception:                   # older openpyxl: text is enough
            pass
    return cell


def append_row(ws, row):
    """ws.append(row), with every risky text cell stored as text. Values
    wrapped in Formula stay formulas."""
    row = list(row)
    ws.append([str(v) if isinstance(v, Formula) else v for v in row])
    r = getattr(ws, "_current_row", None) or ws.max_row
    for i, v in enumerate(row):
        if risky(v):
            set_text(ws.cell(row=r, column=i + 1), v)
    return r


def protect_sheet(ws, keep=()):
    """After a sheet is filled: turn every formula cell that is not one of
    the program's own back into text. `keep(cell)` -> True for a formula the
    program wrote (or pass a set of coordinates like {"D7"})."""
    if callable(keep):
        own = keep
    else:
        keep = set(keep)
        own = lambda c: c.coordinate in keep     # noqa: E731
    for row in ws.iter_rows():
        for c in row:
            if c.data_type == "f" and isinstance(c.value, str) and \
                    not own(c):
                set_text(c, c.value)
