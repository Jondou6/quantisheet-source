"""Bid gate (Nov 3, Jon approved Chief's list): the last checks before a
bid or proposal goes out, run with Estimate Error Check.

  price_old            a unit price not set or confirmed in the last
                       N days (setting "price_max_age_days", 90)
  quote_expired        a sub or supplier quote used in the estimate whose
                       valid-until day has passed
  addendum_unpriced    an addendum not marked priced (blocks the bid form
                       and proposal until it is - Addenda Gate)
  addendum_after_edit  an addendum that arrived after the estimate was
                       last changed
  placeholder          a $/SF placeholder, plug or allowance still in the
                       estimate, not replaced by takeoff or a real quote
  overlap_area         two area takeoffs of the same item overlapping
  repeat_count         a count placed twice on the same spot
  subtotal_twice       a line that repeats the lines just above it (a
                       subtotal added again)

and the Escalation Projector: each cost type's price rise from the bid
day to the day it will be bought. Nothing here changes the estimate; the
findings are dicts like checks.py's.
"""
import datetime
import logging
from decimal import Decimal
from ..dmoney import c2 as _c2

log = logging.getLogger(__name__)

S_MAX_AGE = "price_max_age_days"
S_RATES = "escalation_rates"
MAX_AGE_DAYS = 90
OVERLAP_SHARE = 0.25        # this share of the smaller area overlapping
REPEAT_PT = 6.0             # two counts this close (points) are one spot
RULES = {
    "price_old": "Unit price older than the set number of days",
    "quote_expired": "Quote used past its valid-until day",
    "addendum_unpriced": "Addendum not priced yet",
    "addendum_after_edit": "Addendum arrived after the estimate's last change",
    "placeholder": "Placeholder, plug or allowance not replaced yet",
    "overlap_area": "Area takeoffs of the same item overlap",
    "repeat_count": "Same spot counted twice",
    "subtotal_twice": "Lines repeated as a subtotal",
}
SEVERITY = {"price_old": "warning", "quote_expired": "error",
            "addendum_unpriced": "error", "addendum_after_edit": "warning",
            "placeholder": "warning", "overlap_area": "warning",
            "repeat_count": "warning", "subtotal_twice": "error"}
HOW_TO = {
    "price_old": "The line's price was set more than the set number of days "
                 "ago (Estimate > Bid Gate Settings). Check it with the "
                 "supplier and update it, or right-click > Price Still Good "
                 "to keep it.",
    "quote_expired": "A quote in the estimate is past the day the bidder "
                     "said it holds to. Get it confirmed or re-quoted.",
    "addendum_unpriced": "Every addendum has to be priced (even at $0) "
                         "before the bid form or proposal goes out: Project "
                         "> Addenda > Mark Priced.",
    "addendum_after_edit": "An addendum came in after the estimate was last "
                           "changed. Make sure its changes are in the "
                           "numbers.",
    "placeholder": "A quick $/SF placeholder, a plug or an allowance is "
                   "still in the bid. Replace it with takeoff or a real "
                   "quote, or keep it on purpose.",
    "overlap_area": "Two area takeoffs of the same item cover the same "
                    "floor, so it is counted twice. Trim or delete one.",
    "repeat_count": "Two counts of the same item sit on the same spot - "
                    "probably clicked twice. Delete one.",
    "subtotal_twice": "A line's amount equals the lines right above it "
                      "added up - a subtotal typed in as a line counts "
                      "them twice. Delete it.",
}


def _f(rule, item, message, **extra):
    return dict({"severity": SEVERITY[rule], "rule": rule,
                 "item": str(item), "message": message}, **extra)


def _day(v):
    try:
        return datetime.date.fromisoformat(str(v or "")[:10])
    except ValueError:
        return None


def max_age():
    try:
        from .. import settings
        n = int(settings.get(S_MAX_AGE, MAX_AGE_DAYS))
        return n if n > 0 else MAX_AGE_DAYS
    except Exception:                                     # noqa: BLE001
        return MAX_AGE_DAYS


# ---- stale prices and quotes (#2) ----------------------------------------------

def stale(doc, job=None, today=None, days=None):
    from .. import estimate_lines as EL
    from . import bidday
    today = today or datetime.date.today()
    days = days or max_age()
    out = []
    for ln in EL.read(doc) if doc is not None else []:
        d = _day(ln.get("priced_on"))
        if d is None or not any(Decimal(ln[k]) for k in EL.PARTS):
            continue
        age = (today - d).days
        if age > days:
            out.append(_f("price_old", ln["desc"] or ln["code"],
                          f"priced {d.isoformat()}, {age} days ago (over "
                          f"{days})", line_id=ln["id"], age=age))
    try:
        sheets = bidday._all(doc) if doc is not None else []
    except Exception:                                     # noqa: BLE001
        sheets = []
    for sh in sheets:
        ap = sh.get("applied") or {}
        used = ap.get("bidder")
        for b in sh.get("bidders") or []:
            vu = _day(b.get("valid_until"))
            if used and b.get("name") == used and vu and vu < today:
                out.append(_f("quote_expired", f"{sh.get('package')}: "
                              f"{used}", f"{used}'s quote for "
                              f"{sh.get('package')} held until "
                              f"{vu.isoformat()}"))
    for a in (job or {}).get("activities") or []:
        for q in a.get("quotes") or []:
            vu = _day(q.get("valid_until"))
            if q.get("use") and vu and vu < today:
                out.append(_f("quote_expired", f"{a.get('name', '')}: "
                              f"{q.get('vendor', '')}",
                              f"{q.get('vendor', '')}'s {q.get('kind')} "
                              f"quote held until {vu.isoformat()}"))
    return out


# ---- Addenda Gate (#6) -----------------------------------------------------------

def last_estimate_change(doc):
    from .. import estimate_lines as EL
    days = [d for d in (_day(x.get("priced_on")) for x in EL.read(doc)) if d]
    return max(days) if days else None


def addenda(doc):
    from .. import doccontrol
    try:
        adds = doccontrol.addenda(doc)
    except Exception:                                     # noqa: BLE001
        return []
    out = []
    last = last_estimate_change(doc)
    for a in adds:
        name = f"Addendum {a.get('no', '')} {a.get('title', '')}".strip()
        if not a.get("priced"):
            out.append(_f("addendum_unpriced", name, "not marked priced - "
                          "price it (even at $0) before the bid goes out",
                          addendum=a["id"]))
        came = _day(a.get("received") or a.get("issued"))
        if came and last and came > last:
            out.append(_f("addendum_after_edit", name,
                          f"arrived {came.isoformat()}; the estimate was "
                          f"last changed {last.isoformat()}",
                          addendum=a["id"]))
    return out


def blockers(doc):
    """What stops the bid form / proposal going out: unpriced addenda."""
    return [f for f in addenda(doc) if f["rule"] == "addendum_unpriced"]


# ---- placeholders, plugs and allowances (#13) -----------------------------------

def placeholders(doc):
    """Every placeholder still in the estimate: [{"kind": "allowance" |
    "plug" | "placeholder", "item", "amount" (Decimal), "line_id",
    "source"}]. A line taken to $0 (replaced by an award) isn't listed."""
    from .. import estimate_lines as EL
    out = []
    for p in EL.priced(doc) if doc is not None else []:
        if not p["total"]:
            continue
        desc, note = p["desc"].lower(), p.get("note", "").upper()
        if "quick $/sf" in desc or "placeholder" in desc:
            kind = "placeholder"
        elif note.startswith("PLUG") or note.startswith("MISSING") or \
                " plug" in f" {desc}":
            kind = "plug"
        elif p.get("cost_type") == "Allowance" or desc.startswith(
                "allowance"):
            kind = "allowance"
        else:
            continue
        out.append({"kind": kind, "item": p["desc"], "amount": p["total"],
                    "line_id": p["id"], "source": p.get("source", "")})
    return out


def placeholder_findings(doc):
    return [_f("placeholder", x["item"], f"{x['kind']} of "
               f"${_c2(x['amount']):,.2f} still in the estimate",
               line_id=x["line_id"], kind=x["kind"])
            for x in placeholders(doc)]


# ---- double counts (#15) ----------------------------------------------------------

def _poly(doc, it):
    from .. import annotate
    try:
        pg = doc[it["page"]]
        for a in annotate.find_annots(pg, it["ref"])[:1]:
            v = a.vertices or []
            pts = [(float(p[0]), float(p[1])) for p in v]
            if len(pts) >= 3:
                return pts
    except Exception:                                     # noqa: BLE001
        pass
    r = it["rect"]
    return [(r[0], r[1]), (r[2], r[1]), (r[2], r[3]), (r[0], r[3])]


def _overlap_share(a, b):
    """Overlap of two outlines as a share of the smaller one (0..1)."""
    import numpy as np
    import cv2
    xs = [p[0] for p in a + b]
    ys = [p[1] for p in a + b]
    x0, y0 = min(xs), min(ys)
    span = max(max(xs) - x0, max(ys) - y0, 1e-6)
    k = 400.0 / span
    W = int((max(xs) - x0) * k) + 3
    H = int((max(ys) - y0) * k) + 3

    def mask(pts):
        m = np.zeros((H, W), np.uint8)
        q = np.array([[(x - x0) * k + 1, (y - y0) * k + 1] for x, y in pts],
                     np.int32)
        cv2.fillPoly(m, [q], 1)
        return m
    ma, mb = mask(a), mask(b)
    small = min(int(ma.sum()), int(mb.sum()))
    return float((ma & mb).sum()) / small if small else 0.0


def _rects_meet(r, s):
    return r[0] < s[2] and s[0] < r[2] and r[1] < s[3] and s[1] < r[3]


def double_counts(doc, lines=None):
    from .. import annotate
    from .. import estimate_lines as EL
    out = []
    try:
        items = annotate.totals_items(doc) if doc is not None else []
    except Exception:                                     # noqa: BLE001
        items = []
    by = {}
    for it in items:
        by.setdefault((it["page"], it.get("group") or "", it["type"]),
                      []).append(it)
    for (page, group, kind), its in by.items():
        if not group:
            continue
        if kind == "area":
            polys = {}
            for i in range(len(its)):
                for j in range(i + 1, len(its)):
                    a, b = its[i], its[j]
                    if not _rects_meet(a["rect"], b["rect"]):
                        continue
                    pa = polys.setdefault(i, _poly(doc, a))
                    pb = polys.setdefault(j, _poly(doc, b))
                    share = _overlap_share(pa, pb)
                    if share >= OVERLAP_SHARE:
                        out.append(_f("overlap_area", group,
                                      f"two areas on page {page + 1} "
                                      f"overlap ({share:.0%} of the "
                                      "smaller one)", page=page,
                                      refs=[a["ref"], b["ref"]]))
        elif kind == "count":
            seen = []
            for it in its:
                r = it["rect"]
                c = ((r[0] + r[2]) / 2, (r[1] + r[3]) / 2)
                hit = next((s for s in seen if abs(s[0][0] - c[0]) <=
                            REPEAT_PT and abs(s[0][1] - c[1]) <= REPEAT_PT),
                           None)
                if hit is not None:
                    out.append(_f("repeat_count", group,
                                  f"counted twice on the same spot on page "
                                  f"{page + 1}", page=page,
                                  refs=[hit[1], it["ref"]]))
                else:
                    seen.append((c, it["ref"]))
    rows = EL.priced(doc, lines=lines) if doc is not None or lines else []
    totals = [r["total"] for r in rows]
    for i, r in enumerate(rows):
        t = r["total"]
        if t <= 0 or i < 2:
            continue
        run = Decimal("0.00")
        for j in range(i - 1, -1, -1):
            run += totals[j]
            if run > t:
                break
            n = i - j
            said = any(w in (r["desc"] or "").lower()
                       for w in ("total", "sum", "subtot"))
            # two lines adding up to a third happens by chance; three or
            # more, or a line that calls itself a total, is a subtotal
            if run == t and (n >= 3 or (n >= 2 and said)):
                out.append(_f("subtotal_twice", r["desc"] or r["code"],
                              f"${_c2(t):,.2f} = the {n} lines above it "
                              "added up", line_id=r["id"]))
                break
    return out


# ---- everything, for Error Check ------------------------------------------------

def run(doc, job=None, today=None):
    out = []
    for fn in (lambda: stale(doc, job, today), lambda: addenda(doc),
               lambda: placeholder_findings(doc),
               lambda: double_counts(doc)):
        try:
            out += fn()
        except Exception:                                 # noqa: BLE001
            log.warning("a bid gate check failed", exc_info=True)
    return out


# ---- Escalation Projector (#16) --------------------------------------------------

DEFAULT_RATES = {"Material": 4.0, "Labor": 3.5, "Equipment": 2.5,
                 "Subcontract": 3.5}


def rates():
    """% a year per cost type (settings, else DEFAULT_RATES)."""
    out = dict(DEFAULT_RATES)
    try:
        from .. import settings
        saved = settings.get(S_RATES) or {}
        for k, v in saved.items():
            if k in out:
                out[k] = float(v)
    except Exception:                                     # noqa: BLE001
        pass
    return out


def save_rates(r):
    from .. import settings
    settings.set(S_RATES, {k: float(v) for k, v in r.items()
                           if k in DEFAULT_RATES})


def project(doc, buy_date, bid_date=None, pct=None, buy_dates=None):
    """The rise in each cost type's cost from `bid_date` (default today)
    to the day it is bought (`buy_dates` {cost type: date} or `buy_date`).
    Returns {"rows": [{"type", "amount", "pct_year", "months", "rise"}],
    "total" (Decimal)}. Allowances are left as they are."""
    from .. import estimate_lines as EL
    pct = pct or rates()
    start = _day(bid_date) or datetime.date.today()
    amounts = {k: Decimal("0.00") for k in DEFAULT_RATES}
    part_type = {"mat": "Material", "lab": "Labor", "eqp": "Equipment",
                 "sub": "Subcontract"}
    for p in EL.priced(doc) if doc is not None else []:
        if p.get("cost_type") == "Allowance":
            continue
        for k, t in part_type.items():
            amounts[t] += p["ext"][k]
    rows, total = [], Decimal("0.00")
    for t, amt in amounts.items():
        end = _day((buy_dates or {}).get(t)) or _day(buy_date) or start
        days = max(0, (end - start).days)
        f = (1 + pct.get(t, 0) / 100.0) ** (days / 365.25) - 1
        rise = (amt * Decimal(str(round(f, 6)))).quantize(Decimal("0.01"))
        rows.append({"type": t, "amount": amt, "pct_year": pct.get(t, 0),
                     "months": round(days / 30.44, 1), "rise": rise,
                     "buy": end.isoformat()})
        total += rise
    return {"rows": rows, "total": total, "from": start.isoformat()}


def escalation_line(result, buy_date):
    """An estimate line carrying the projected rise (estimate_lines)."""
    from .. import estimate_lines as EL
    return EL.new_line(f"Escalation to buy date ({buy_date})", 1, "ls",
                       cost_type="Other", sub=result["total"],
                       source="Escalation Projector",
                       note="; ".join(f"{r['type']} {r['pct_year']:g}%/yr x "
                                      f"{r['months']} mo = ${_c2(r['rise']):,.2f}"
                                      for r in result["rows"] if r["rise"]))
