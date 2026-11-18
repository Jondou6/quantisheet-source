"""AI Takeoff quantities kept in the PDF, so the Estimate panel follows the
takeoff (Nov 17, live takeoff-to-estimate).

Most of what AI Takeoff finds goes on the drawing as measurements, and the
Estimate panel already totals those live. The rest - steel weight, wall
area from wall length x height, finishes, door-frame lengths, the work
notes' counts - is worked out, not drawn. Those "taken off" quantities are
stored here (embedded file quantisheet_ai_quantities.json) and the
estimate shows them as takeoff lines of type "ai", which an estimate line
can link to like any other. Running AI Takeoff again on the same sheets
replaces their quantities, so a linked line follows; accepting a CHECK
item in review adds it.

    store(doc, res, pages=None) -> n   write the taken-off quantities
    rows(doc) -> [row]                 read them (bad rows skipped)
    clear(doc)

Quantities only - no price is ever stored here.
"""
import json
import logging
import re

from . import embfiles

log = logging.getLogger(__name__)
# review writes who accepted a line ("by Jo in review"); the PDF travels,
# so no name is kept in it
_WHO = re.compile(r"\s+by\s+.{0,80}?\s+in review")

FILE = "quantisheet_ai_quantities.json"
TYPE = "ai"
MAX_ROWS = 2000
# rows put in by Work Notes Takeoff > Add to Estimate (Nov 17): a person
# chose them, so a later AI Takeoff run keeps them and doesn't add its own
# copy of the same note
WINDOW = "work notes window"
WORKNOTES = "work notes"


def _clean(r):
    """One stored row, or None for one no estimate can use."""
    if not isinstance(r, dict):
        return None
    try:
        q = r.get("qty")
        if isinstance(q, bool):
            return None
        q = float(q)
    except (TypeError, ValueError):
        return None
    name, unit = r.get("name"), r.get("unit")
    if not (0 < q < 1e9) or not name or not unit:
        return None
    page = r.get("page")
    if isinstance(page, bool) or not isinstance(page, int) or page < 0:
        page = None
    out = {"engine": str(r.get("engine") or "")[:40],
           "name": str(name)[:200], "qty": q, "unit": str(unit)[:12],
           "page": page, "sheet": str(r.get("sheet") or "")[:120],
           "csi": str(r.get("csi") or "")[:20],
           "basis": _WHO.sub(" in review",
                             str(r.get("basis") or ""))[:400]}
    if r.get("from") == WINDOW:
        out["from"] = WINDOW
    return out


def key(r):
    """What makes two rows the same line in the estimate."""
    return (" ".join(str(r.get("name") or "").split()).upper(),
            str(r.get("unit") or "").upper())


def rows(doc):
    """The stored quantities, [{engine, name, qty, unit, page, sheet, csi,
    basis}]; a page no longer in the file is dropped to the set (None)."""
    try:
        if FILE not in doc.embfile_names():
            return []
        data = json.loads(doc.embfile_get(FILE).decode("utf-8"))
    except Exception:                                     # noqa: BLE001
        log.warning("could not read the AI quantities", exc_info=True)
        return []
    raw = data.get("rows") if isinstance(data, dict) else None
    if not isinstance(raw, list):
        return []
    n = getattr(doc, "page_count", 0) or 0
    out = []
    for r in raw[:MAX_ROWS]:
        c = _clean(r)
        if c is None:
            continue
        if c["page"] is not None and c["page"] >= n:
            c["page"] = None
        out.append(c)
    return out


def taken_off(res):
    """The result's quantities that count (status 'taken off')."""
    out = []
    for q in (res or {}).get("quantities") or ():
        if isinstance(q, dict) and (q.get("status") or "taken off") == \
                "taken off":
            c = _clean(q)
            if c is not None:
                out.append(c)
    return out


def _write(doc, allr):
    allr = allr[:MAX_ROWS]
    if not allr and FILE not in doc.embfile_names():
        return 0
    embfiles.put(doc, FILE, json.dumps({"version": 1, "rows": allr})
                 .encode("utf-8"), "QuantiSheet AI Takeoff quantities")
    return len(allr)


def store(doc, res, pages=None):
    """Write the result's taken-off quantities. With `pages` (the sheets
    this run took off), quantities stored earlier for other sheets stay;
    set-wide ones (no page) and those of `pages` are replaced. Rows Work
    Notes Takeoff added always stay, and the run's own copy of one of
    them is left out. Returns how many are stored."""
    old = rows(doc)
    window = [r for r in old if r.get("from") == WINDOW]
    taken = {key(r) for r in window}
    new = [r for r in taken_off(res)
           if not (r["engine"] == WORKNOTES and key(r) in taken)]
    keep = []
    if pages is not None:
        ps = set(pages)
        keep = [r for r in old if r.get("from") != WINDOW and
                r["page"] is not None and r["page"] not in ps]
    return _write(doc, window + keep + new)


def store_worknotes(doc, totals):
    """Work Notes Takeoff > Add to Estimate: `totals` [{name, qty, unit,
    sheet, basis}] replace the rows it added before; an AI Takeoff
    work-note row for the same note is dropped (one line, not two).
    Returns how many window rows are stored."""
    mine = []
    for t in totals:
        c = _clean(dict(t, engine=WORKNOTES, page=None, **{"from": WINDOW}))
        if c is not None:
            mine.append(c)
    keys = {key(r) for r in mine}
    other = [r for r in rows(doc) if r.get("from") != WINDOW and
             not (r["engine"] == WORKNOTES and key(r) in keys)]
    _write(doc, mine + other)
    return len(mine)


def clear(doc):
    try:
        if FILE in doc.embfile_names():
            doc.embfile_del(FILE)
    except Exception:                                     # noqa: BLE001
        log.warning("could not clear the AI quantities", exc_info=True)
