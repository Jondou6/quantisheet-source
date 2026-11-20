"""Bid-submittal checklist (Nov 19): what has to go in with the bid -
signed bid forms, bid bond, contractor's license, insurance certificate
and the bid reference number - checked off before Export Bid Package.

Each item is ticked when it's ready and can carry a file (the signed bid
form PDF, the bond, the certificate); attached files are copied into the
bid package. The reference number is the one the owner or GC gave the
bid (an invitation or solicitation number). Kept in the PDF as
quantisheet_bid_submittal.json, so it travels with the job. A file is
kept as its path on this PC only - never copied into the drawing PDF.

    read(doc) -> state       write(doc, state)
    missing(state) -> [label]  what isn't ticked yet
    lines(state) -> [text]   for the package's contents list
    hold_until(state) -> date  bid day + the hold days asked for
"""
import json
import logging
import os

from . import embfiles

log = logging.getLogger(__name__)

FILE = "quantisheet_bid_submittal.json"
ITEMS = (("bid_form", "Signed bid form(s)"),
         ("bid_bond", "Bid bond (or bid security)"),
         ("license", "Contractor's license"),
         ("insurance", "Insurance certificate"),
         ("ref_no", "Bid reference number"))
LABEL = dict(ITEMS)
FILE_ITEMS = ("bid_form", "bid_bond", "license", "insurance")


def blank():
    return {"items": {k: {"done": False, "file": "", "note": ""}
                      for k, _ in ITEMS}, "ref_no": "", "bid_date": "",
            "hold_days": 0}


def _iso_day(v):
    import datetime
    try:
        return datetime.date.fromisoformat(str(v or "")[:10]).isoformat()
    except ValueError:
        return ""


def hold_until(state):
    """The last day the bid must hold its price: bid day + the hold days
    the bid documents ask for (Nov 19: public work often 60, 90 or 120)
    - a date, or None when either is not set."""
    import datetime
    st = _clean(state)
    if not st["bid_date"] or not st["hold_days"]:
        return None
    return datetime.date.fromisoformat(st["bid_date"]) + \
        datetime.timedelta(days=st["hold_days"])


def _clean(data):
    st = blank()
    if not isinstance(data, dict):
        return st
    ref = data.get("ref_no")
    st["ref_no"] = str(ref)[:80].strip() if isinstance(ref, str) else ""
    items = data.get("items") if isinstance(data.get("items"), dict) else {}
    for k, _ in ITEMS:
        x = items.get(k) if isinstance(items.get(k), dict) else {}
        st["items"][k] = {
            "done": bool(x.get("done")),
            "file": str(x.get("file") or "")[:500] if k in FILE_ITEMS
            else "",
            "note": str(x.get("note") or "")[:200]}
    st["bid_date"] = _iso_day(data.get("bid_date"))
    try:
        st["hold_days"] = max(0, min(730, int(data.get("hold_days") or 0)))
    except (TypeError, ValueError):
        st["hold_days"] = 0
    # the reference number item is done when there is a number
    st["items"]["ref_no"]["done"] = bool(st["ref_no"])
    return st


def read(doc):
    try:
        if FILE in doc.embfile_names():
            return _clean(json.loads(doc.embfile_get(FILE).decode("utf-8")))
    except Exception:                                     # noqa: BLE001
        log.warning("bid submittal checklist unreadable", exc_info=True)
    return blank()


def write(doc, state):
    st = _clean(state)
    embfiles.put(doc, FILE, json.dumps(st).encode("utf-8"),
                 "QuantiSheet bid-submittal checklist")
    return st


def missing(state):
    st = _clean(state)
    return [LABEL[k] for k, _ in ITEMS if not st["items"][k]["done"]]


def attachments(state):
    """[(item, path)] of attached files that exist on this PC."""
    st = _clean(state)
    out = []
    for k in FILE_ITEMS:
        p = st["items"][k]["file"]
        if p and os.path.isfile(p):
            out.append((k, p))
    return out


def lines(state):
    """The checklist as lines for the package's contents list."""
    st = _clean(state)
    out = []
    for k, label in ITEMS:
        x = st["items"][k]
        mark = "[x]" if x["done"] else "[ ]"
        extra = ""
        if k == "ref_no" and st["ref_no"]:
            extra = f": {st['ref_no']}"
        elif x["file"]:
            extra = f" - {os.path.basename(x['file'])}" + (
                "" if os.path.isfile(x["file"]) else " (file not found)")
        if x["note"]:
            extra += f" ({x['note']})"
        out.append(f"{mark} {label}{extra}")
    if st["bid_date"]:
        out.append(f"Bid day: {st['bid_date']}")
    if st["hold_days"]:
        hu = hold_until(st)
        out.append(f"Bid holds for {st['hold_days']} days" +
                   (f" (to {hu.isoformat()})" if hu else ""))
    return out
