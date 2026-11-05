"""Copies of a counted symbol that aren't counted yet (Nov 1).

- Every Count Symbol keeps its sample picture in the PDF (one per count
  name), so the program can look for the same symbol again later.
- uncounted(): the copies of a count's symbol on the given pages that
  have no count mark of that name on or next to them - "show what's not
  counted yet", so missed counts stand out.
- from_example(): a person boxes one copy the takeoff missed; that becomes
  the sample and the program looks for more like it that aren't counted.

The matching is autocount.find_symbols as it is (whole-symbol matching,
the patent design rules unchanged); the 'picture_count' switch is
honoured. Nothing here adds a count: the caller turns hits into count
marks (count_marks), and copies the program found itself stay in review
until a person accepts them.
"""
import base64
import json
import logging

import fitz

from . import annotate, autocount

log = logging.getLogger(__name__)

FILE = "quantisheet_count_samples.json"
REVIEW_METHOD = "AI takeoff: count, found from a missed example" + \
    annotate.REVIEW_SUFFIX


def _read(doc):
    try:
        from . import embfiles
        raw = embfiles.get(doc, FILE)
        if raw:
            d = json.loads(raw.decode("utf-8"))
            return d if isinstance(d, dict) else {}
    except Exception:                                     # noqa: BLE001
        log.debug("count samples not read", exc_info=True)
    return {}


def save_sample(doc, group, png):
    """Keep `png` (autocount.symbol_template) as count `group`'s sample."""
    group = (group or "").strip()
    if not group or not png:
        return False
    from . import embfiles
    d = _read(doc)
    d[group[:80]] = base64.b64encode(png).decode("ascii")
    embfiles.put(doc, FILE, json.dumps(d).encode("utf-8"),
                 "QuantiSheet count symbol samples")
    return True


def sample(doc, group):
    """Count `group`'s saved sample (PNG bytes), or None."""
    v = _read(doc).get((group or "").strip()[:80])
    try:
        return base64.b64decode(v) if v else None
    except ValueError:
        return None


def groups_with_samples(doc):
    return sorted(_read(doc))


def count_rects(doc, page, group):
    """Rects (unrotated page points) of the count marks named `group` on
    page `page`."""
    return [fitz.Rect(it["rect"]) for it in annotate.takeoff_items(doc)
            if it["type"] == "count" and it["group"] == group
            and it["page"] == page]


def is_counted(hit_rect, marks):
    """A copy counts as counted when a count mark of its name sits on it or
    right next to it: count_marks puts the number just above the
    symbol's top-left corner, a hand count is clicked on the symbol."""
    r = fitz.Rect(hit_rect)
    pad = max(r.width, r.height) * 0.6
    near = r + (-pad, -pad, pad, pad)
    for m in marks:
        m = fitz.Rect(m)
        corner = fitz.Point(m.x0, m.y1)
        centre = fitz.Point((m.x0 + m.x1) / 2, (m.y0 + m.y1) / 2)
        if near.contains(corner) or near.contains(centre) or \
                near.intersects(m) and r.intersects(m):
            return True
    return False


def _picture_on():
    try:
        from .aitakeoff import picture_count_on
        return picture_count_on()
    except Exception:                                     # noqa: BLE001
        return True


def uncounted(doc, group, pages, template=None, threshold=0.8):
    """[{page, rect, score}] copies of `group`'s symbol on `pages` with no
    count mark of that name near them. template None = the saved sample.
    Raises LookupError when there is no sample, RuntimeError when picture
    counting is switched off."""
    if not _picture_on():
        raise RuntimeError("Counting by picture is turned off (setting "
                           "'picture_count').")
    tpl = template or sample(doc, group)
    if not tpl:
        raise LookupError(f"No sample saved for '{group}' - count it once "
                          "with Count Symbol and its sample is kept.")
    hits = autocount.find_symbols(doc, tpl, threshold, set(pages))
    out = []
    marks = {}
    for h in hits:
        p = h["page"]
        if p not in marks:
            marks[p] = count_rects(doc, p, group)
        if not is_counted(h["rect"], marks[p]):
            out.append(h)
    return out


def from_example(doc, page, screen_rect, group, pages=None, save=True):
    """A copy the takeoff missed, boxed by a person (screen rect on
    `page`): it becomes `group`'s sample (save=True) and the copies like it
    that aren't counted are returned (it included)."""
    pg = doc[page]
    png = autocount.symbol_template(pg, fitz.Rect(screen_rect))
    if save:
        save_sample(doc, group, png)
    return uncounted(doc, group, pages if pages is not None else [page],
                     template=png)


def count_marks(hits, group, doc, color=(1, 0, 0), review=False):
    """Count marks for `hits`; review=True: marked as found by the program
    and kept out of the totals until accepted (REVIEW_METHOD)."""
    for h in hits:
        if review:
            h["method"] = REVIEW_METHOD
        else:
            h.setdefault("method", "count: uncounted copies")
    marks = autocount.count_marks(hits, group, doc, color)
    if review:
        for _p, _k, payload in marks:
            payload["badge"] = True
            payload["dashes"] = [3, 2]
    return marks
