"""Escalation from real BLS Producer Price Index series (bls_core).

Fetch the series (public BLS API, no key needed; a free key allows more),
keep them in the price database so every estimator uses the same numbers,
and turn them into yearly escalation rates by trade:

* Bid Tabs: each bid is escalated at its trade's PPI rate.
* Cost books: each item escalates at its CSI division's PPI rate (from the
  book's date to the job's pricing date); the book's own rate still
  applies to everything else and to labor.
"""
import datetime as _dt
import re

from . import bls_core as core
from . import pricedb, settings

CACHE_KEY = "ppi_cache"
FETCHED_KEY = "ppi_fetched"


def series():
    """{id: (title, trades)} - the built-in list plus yours (settings
    "ppi_series": {id: [title, trade]})."""
    out = {k: (v[0], core.trades_of(v)) for k, v in core.DEFAULT_SERIES.items()}
    for sid, v in (settings.get("ppi_series") or {}).items():
        if isinstance(v, (list, tuple)) and len(v) >= 2:
            out[str(sid)] = (str(v[0]), core.trades_of(v))
    return out


def cache():
    try:
        data = pricedb.meta(CACHE_KEY) or {}
    except Exception:
        data = {}
    return data if isinstance(data, dict) else {}


def fetched():
    try:
        return pricedb.meta(FETCHED_KEY) or ""
    except Exception:
        return ""


def fetch(start=None, end=None, key=None, ids=None, fetcher=None):
    """Pull the series from BLS into the price database. Returns
    {id: points} of what came back (missing ids aren't BLS series)."""
    end = end or _dt.date.today().year
    start = start or end - 3
    key = key if key is not None else settings.get("bls_key") or None
    ids = list(ids or series())
    fetcher = fetcher or core.fetch_series
    data = cache()
    got = {}
    per = 50 if key else 25
    for i in range(0, len(ids), per):
        got.update(fetcher(ids[i:i + per], int(start), int(end), key))
    for sid, pts in got.items():
        if pts:
            merged = dict(data.get(sid) or {})
            merged.update(pts)
            data[sid] = dict(sorted(merged.items()))
    pricedb.set_meta(CACHE_KEY, data)
    pricedb.set_meta(FETCHED_KEY, _dt.datetime.now().isoformat(
        timespec="minutes"))
    return got


def table(start_ym, end_ym):
    """[{id, title, trades, last, last_month, factor, annual_pct,
    extrapolated}] for the cached series."""
    data = cache()
    out = []
    for sid, (title, trades) in series().items():
        pts = data.get(sid) or {}
        row = {"id": sid, "title": title, "trades": trades, "last": None,
               "last_month": "", "factor": None, "annual_pct": None,
               "extrapolated": 0, "warnings": []}
        if pts:
            last = sorted(pts)[-1]
            r = core.escalation(pts, start_ym, end_ym)
            row.update(last=pts[last], last_month=last, factor=r["factor"],
                       annual_pct=r["annual_pct"],
                       extrapolated=r["extrapolated"],
                       warnings=r.get("warnings", []))
        out.append(row)
    return out


def trade_rates(start_ym, end_ym):
    """{bid tab trade: yearly %} averaged over each trade's series."""
    got = {}
    for row in table(start_ym, end_ym):
        if row["annual_pct"] is None:
            continue
        for t in row["trades"]:
            got.setdefault(t, []).append(row["annual_pct"])
    return {t: round(sum(v) / len(v), 2) for t, v in got.items()}


def divisions_of(trade):
    """CSI divisions a bid tab trade name covers: "03 Concrete" -> ["03"],
    "27-28 Comm & Security" -> ["27", "28"], "40-46 Process" -> 40..46."""
    m = re.match(r"(\d{2})(?:-(\d{2}))?", trade or "")
    if not m:
        return []
    a = int(m.group(1))
    b = int(m.group(2) or a)
    return [f"{d:02d}" for d in range(a, b + 1)]


def division_rates(start_ym, end_ym):
    """{"03": yearly fraction, ...} for cost books."""
    out = {}
    for trade, pct in trade_rates(start_ym, end_ym).items():
        for d in divisions_of(trade):
            out.setdefault(d, []).append(pct)
    return {d: round(sum(v) / len(v) / 100.0, 4) for d, v in out.items()}


def apply_to_bidtabs(start_ym, end_ym):
    from . import bidtab
    cur = bidtab.rates()
    new = trade_rates(start_ym, end_ym)
    cur.update(new)
    bidtab.set_rates(cur)
    return new


def apply_to_book(name, start_ym, end_ym, overall=True):
    """Give cost book `name` PPI escalation by CSI division (and, with
    `overall`, its general rate from new nonresidential construction).
    Returns the division rates."""
    from . import costbook
    book = costbook.find(name)
    if book is None:
        raise ValueError(f"No cost book named {name}")
    divs = division_rates(start_ym, end_ym)
    book.escalation_by_div = divs
    gen = trade_rates(start_ym, end_ym).get("Unclassified")
    if overall and gen is not None:
        book.escalation = round(gen / 100.0, 4)
    book.escalation_source = (f"BLS PPI, {start_ym} to {end_ym} "
                              f"(fetched {fetched()[:10]})")
    costbook.save(book, note="PPI escalation")
    return divs
