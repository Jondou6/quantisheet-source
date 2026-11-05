"""Sheet coverage map and second-person check (upgrade spec 1b and 1g).

Coverage: how much of each sheet's drawing area the takeoff touches
(union of the takeoff marks' boxes / the drawing area, leaving out the
title block - the right 20% by default). Status per sheet:
    green  reviewed (and, when a second check is required, checked)
    amber  has takeoff but isn't reviewed (or is waiting for its check)
    red    nothing taken off and not reviewed

Second check: a different estimator checks each reviewed sheet. The
checker can't be the person who reviewed it. With "second check
required" on (optionally only for bids over an amount), the bid can't
lock until every sheet is checked.
"""
import fitz

from . import annotate, prebid, settings
from .dmoney import D

TITLE_BLOCK = 0.20
GRID = 120                      # cells across the drawing area


class CheckError(prebid.PrebidError):
    pass


def drawing_area(page, title_frac=None):
    """The page minus the title block strip on the right."""
    f = TITLE_BLOCK if title_frac is None else float(title_frac)
    r = page.rect
    return fitz.Rect(r.x0, r.y0, r.x1 - r.width * f, r.y1)


def takeoff_rects(doc, pno):
    """Boxes of the takeoff marks on a page (lengths, areas, counts)."""
    return [fitz.Rect(it["rect"]) for it in annotate.takeoff_items(doc)
            if it["page"] == pno]


def coverage(doc, pno, title_frac=None, rects=None):
    """Fraction 0..1 of the drawing area under takeoff marks (their union,
    so overlaps count once). Thin marks (a pipe run) get a little width so
    a line shows as covering the strip it runs through."""
    page = doc[pno]
    area = drawing_area(page, title_frac)
    rects = takeoff_rects(doc, pno) if rects is None else rects
    if area.is_empty or not rects:
        return 0.0
    n = GRID
    cw = area.width / n
    rows = max(1, int(round(area.height / cw)))
    ch = area.height / rows
    pad = cw / 2
    cells = set()
    for r in rects:
        # only a thin mark (a pipe run) is widened, and only across itself
        px = pad if r.width < cw else 0
        py = pad if r.height < ch else 0
        r = fitz.Rect(r.x0 - px, r.y0 - py, r.x1 + px, r.y1 + py) & area
        if r.is_empty:
            continue
        c0 = max(0, int((r.x0 - area.x0) / cw))
        c1 = min(n - 1, int((r.x1 - area.x0 - 1e-9) / cw))
        r0 = max(0, int((r.y0 - area.y0) / ch))
        r1 = min(rows - 1, int((r.y1 - area.y0 - 1e-9) / ch))
        for i in range(r0, r1 + 1):
            for j in range(c0, c1 + 1):
                cells.add((i, j))
    return len(cells) / float(n * rows)


def second_check_required(total=None):
    """The setting, and its threshold: required for every bid, or only
    bids over settings 'second_check_over' (0 = all)."""
    if not settings.get("second_check_required", False):
        return False
    over = D(settings.get("second_check_over", 0) or 0)
    return total is None or over <= 0 or D(total) > over


def status(doc, title_frac=None, total=None):
    """[{page, sheet, coverage, takeoff, reviewed, by, checked, checked_by,
    color}] for every page."""
    data = prebid.read(doc)
    keys = prebid._sheet_keys(doc)
    need = second_check_required(total)
    per_page = {}
    for it in annotate.takeoff_items(doc):
        per_page.setdefault(it["page"], []).append(fitz.Rect(it["rect"]))
    out = []
    for pno in range(doc.page_count):
        st = data["sheets"].get(keys[pno]) or {}
        rects = per_page.get(pno, [])
        chk = st.get("checked") or {}
        reviewed = bool(st.get("reviewed"))
        checked = bool(chk)
        if reviewed and (checked or not need):
            color = "green"
        elif rects or reviewed:
            color = "amber"
        else:
            color = "red"
        out.append({"page": pno, "sheet": keys[pno],
                    "coverage": coverage(doc, pno, title_frac, rects),
                    "takeoff": len(rects), "reviewed": reviewed,
                    "by": st.get("by", ""), "checked": checked,
                    "checked_by": chk.get("by", ""),
                    "checked_at": chk.get("at", ""), "color": color})
    return out


def set_checked(doc, pno, checked=True, by=None):
    """Second-person check of a reviewed sheet."""
    data = prebid.read(doc)
    key = prebid._sheet_keys(doc)[pno]
    st = data["sheets"].get(key)
    if not checked:
        if st:
            st.pop("checked", None)
            prebid.write(doc, data)
        return key
    if not st or not st.get("reviewed"):
        raise CheckError(f"{key} hasn't been reviewed yet - it needs a "
                         "review before the second check.")
    who = prebid._who(by)
    if who.strip().lower() == str(st.get("by", "")).strip().lower():
        raise CheckError(f"{key} was reviewed by {who}. The second check "
                         "has to be someone else.")
    st["checked"] = {"by": who, "at": prebid._now()}
    data["log"].append({"action": "checked", "sheet": key, "by": who,
                        "at": st["checked"]["at"]})
    prebid.write(doc, data)
    return key


def unchecked(doc, total=None):
    """Sheets still waiting for the second check, when it's required."""
    if not second_check_required(total):
        return []
    return [s for s in status(doc, total=total) if not s["checked"]]


def lock_blockers(doc, total):
    """Plain-English reasons the second check blocks the lock (empty when
    it doesn't)."""
    left = unchecked(doc, total)
    if not left:
        return []
    names = ", ".join(s["sheet"] for s in left[:8])
    more = f" and {len(left) - 8} more" if len(left) > 8 else ""
    return [f"{len(left)} sheet(s) not second-checked: {names}{more}"]
