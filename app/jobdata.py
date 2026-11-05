"""QuantiSheet's job data inside a PDF, kept safe through page operations.

Scales, assemblies, prices, custom columns and proposals are embedded files
named "quantisheet_*". Two things used to lose them:

* Scales are stored per page index, and inserting, deleting, moving or
  replacing pages shifted the pages under them. keep_scales() ties each
  scale to the page itself (its PDF object) across a page operation, and
  puts it back on the page's new index.
* Combine, split, extract, insert-from-PDF and Remove Hidden Information
  made or scrubbed documents without them. copy_job() / snapshot() /
  restore() carry them across.
"""
import json
import logging
from contextlib import contextmanager
from . import embfiles

log = logging.getLogger(__name__)

PREFIX = "quantisheet_"
SCALE_FILE = "quantisheet_scale.json"


def names(doc):
    try:
        return [n for n in doc.embfile_names() if n.startswith(PREFIX)]
    except Exception:
        return []


# What each job file holds, for the "this PDF carries job data" indicator.
LABELS = {
    "quantisheet_scale.json": "scales",
    "quantisheet_assemblies.json": "assemblies",
    "quantisheet_estimate.json": "estimate and prices",
    "quantisheet_money.json": "margins and markups",
    "quantisheet_proposal.json": "proposal",
    "quantisheet_heavy.json": "civil estimate",
    "quantisheet_columns.json": "custom columns",
    "quantisheet_buy.json": "buy quantities",
    "quantisheet_scale_src.json": "where each scale came from",
    "quantisheet_audit.json": "audit trail",
    "quantisheet_log.json": "change log",
}
# Files that reveal money (prices, margins, bids).
PRICING_HINTS = ("estimate", "money", "margin", "price", "cost", "bid", "proposal",
                 "audit", "assembl", "heavy", "column")


def describe(doc):
    """[(file name, plain label)] of the job data this PDF carries."""
    out = []
    for n in names(doc):
        if n == "quantisheet_meta.json":   # the version stamp (jobsafe.py)
            continue
        label = LABELS.get(n) or n[len(PREFIX):].rsplit(".", 1)[0] \
            .replace("_", " ")
        out.append((n, label))
    return out


def has_pricing(doc):
    return any(h in n.lower() for n in names(doc) for h in PRICING_HINTS)


def strip(doc):
    """Remove every quantisheet_* job file. Returns the names removed."""
    gone = []
    for n in names(doc):
        try:
            if embfiles.delete(doc, n):
                gone.append(n)
        except Exception:
            log.warning("could not remove %s", n, exc_info=True)
    return gone


def snapshot(doc):
    """{embedded file name: bytes} of QuantiSheet's job data."""
    out = {}
    for n in names(doc):
        try:
            out[n] = doc.embfile_get(n)
        except Exception:
            log.warning("could not read %s", n, exc_info=True)
    return out


def _put(doc, name, data):
    embfiles.put(doc, name, data, "QuantiSheet job data")


def restore(doc, data, overwrite=True):
    have = set(doc.embfile_names())
    for n, raw in data.items():
        if overwrite or n not in have:
            _put(doc, n, raw)


def _scales(doc):
    try:
        if SCALE_FILE in doc.embfile_names():
            d = json.loads(doc.embfile_get(SCALE_FILE).decode("utf-8"))
            return {int(k): v for k, v in d.items() if isinstance(v, dict)}
    except Exception:
        log.warning("could not read scales", exc_info=True)
    return {}


def _write_scales(doc, scales):
    if not scales:
        embfiles.delete(doc, SCALE_FILE)
        return
    _put(doc, SCALE_FILE, json.dumps(
        {str(k): v for k, v in sorted(scales.items())}).encode())


@contextmanager
def keep_scales(doc):
    """Keep each page's scale (and viewports) with that page through
    whatever the block does to the page order. A page that is replaced in
    place (OCR, Replace Pages) keeps the scale of the page it replaced."""
    before = _scales(doc)
    if not before:
        yield
        return
    old = [doc.page_xref(i) for i in range(doc.page_count)]
    by_xref = {old[i]: v for i, v in before.items() if 0 <= i < len(old)}
    yield
    new = [doc.page_xref(i) for i in range(doc.page_count)]
    alive, was = set(new), set(old)
    out = {}
    for i, x in enumerate(new):
        if x in by_xref:
            out[i] = by_xref[x]
        elif x not in was and i < len(old) and old[i] not in alive \
                and i in before:
            out[i] = before[i]                  # same slot, page replaced
    if out != before:
        _write_scales(doc, out)


def copy_job(src, dst, page_map, scales_only=False):
    """Copy job data from `src` into `dst`. `page_map` is {src page: dst
    page} for the pages that were copied; their scales come along. Other
    job files are copied only if `dst` has none of its own."""
    s = _scales(src)
    if s:
        d = _scales(dst)
        changed = False
        for si, di in page_map.items():
            if si in s and di not in d:
                d[di] = s[si]
                changed = True
        if changed:
            _write_scales(dst, d)
    if scales_only:
        return
    have = set(dst.embfile_names())
    for n in names(src):
        if n != SCALE_FILE and n not in have:
            try:
                _put(dst, n, src.embfile_get(n))
            except Exception:
                log.warning("could not copy %s", n, exc_info=True)
