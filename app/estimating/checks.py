"""Estimate Error Check: the mistakes that cost money, found before the
bid goes out.

Looked at:
  * the added estimate lines (estimate_lines.py) and the takeoff groups
    on the drawings (estimate.lines),
  * the civil crew estimate (heavy.py: activities and pay items) when a
    job is given.

Rules (RULES has the plain words shown to the user):
  zero_qty          a priced line or activity with no quantity
  no_cost           a line or activity with a quantity but no price
  unit_mismatch     a linked line priced per a unit its takeoff group
                    can't be turned into; an activity in another unit
                    than its pay item
  duplicate         the same code + description + unit twice
  missing_crew      an activity with a quantity and no crew (or a crew
                    that isn't in the library) and no material, sub or
                    quote either
  unpriced_takeoff  a takeoff group no line, price, assembly, activity
                    or applied bid-day package uses (markups accounted
                    for in the pre-bid checklist - excluded with a
                    reason, RFI, priced - are left out)
  outlier           a unit cost more than outlier_pct % away from the
                    median of your own history for the same code and
                    unit (only when you give a history)
  bid_plug          a bid-day quote in the estimate carries a plug for
                    an item the bidder didn't quote (bidday.apply_quote)
  bid_stale         a bid-day quote changed after it was put in the
                    estimate (a price, the lowest complete bidder), or
                    its lines were removed or edited by hand
  double_priced     a takeoff group with its own unit cost that a linked
                    line, an assembly or a civil activity also prices
  no_cost_type      a takeoff group priced by a unit cost with no cost
                    type: in the total, but not material or any other
                    part (so not on the material order list)
  sched_missing     (v2 step 6, schedcheck.py) a type or room on the
                    plan's own schedule with nothing in the takeoff
  sched_count       a type whose takeoff count differs from its schedule
  sched_extra       a takeoff item that looks scheduled but is on no
                    schedule read
  crew_rate         a production rate far outside the library's and the
                    EXAMPLE crews' rates for the same unit
  crew_hours_day    a crew day over HOURS_DAY_MAX hours
  crew_days         under half a crew-day, or more than a year of them
  unit_cost_far     a $/unit far off the job's other lines in that unit

Schedule findings are advisory and carry a confidence. Every rule can
be switched off on its own (set_rule_on, kept in the settings file);
HOW_TO has each rule's plain-words help.

Nothing is changed; run() only reports. A finding is
{"severity": "error" | "warning", "rule", "item", "message"}.
"""
import logging
import statistics
from decimal import Decimal

from . import _io, safedb

log = logging.getLogger(__name__)

RULES = {
    "zero_qty": "Quantity is zero",
    "no_cost": "Has a quantity but no price",
    "unit_mismatch": "Unit doesn't match its takeoff or pay item",
    "duplicate": "Same item more than once",
    "missing_crew": "Civil activity without a usable crew",
    "unpriced_takeoff": "Takeoff group not priced anywhere",
    "outlier": "Unit cost far from your own history",
    "bid_plug": "Bid-day plug in the estimate (not quoted)",
    "bid_stale": "Bid-day quote changed after it was used",
    "double_priced": "Takeoff group priced twice",
    "no_cost_type": "Priced with no cost type",
    "sched_missing": "On the plan's schedule, not in the takeoff",
    "sched_count": "Takeoff count differs from the schedule",
    "sched_extra": "In the takeoff, not on any schedule",
    "crew_rate": "Production rate far from the library",
    "crew_hours_day": "Crew day too long",
    "crew_days": "Crew-days unrealistic",
    "unit_cost_far": "Unit cost far off the job's other lines",
    "ai_pending": "AI takeoff still waiting for review (not in the totals)",
}
SEVERITY = {"zero_qty": "warning", "no_cost": "error",
            "unit_mismatch": "error", "duplicate": "warning",
            "missing_crew": "error", "unpriced_takeoff": "warning",
            "outlier": "warning", "bid_plug": "warning",
            "bid_stale": "warning", "double_priced": "warning",
            "no_cost_type": "warning", "sched_missing": "warning",
            "sched_count": "warning", "sched_extra": "warning",
            "crew_rate": "warning", "crew_hours_day": "warning",
            "crew_days": "warning", "unit_cost_far": "warning",
            "ai_pending": "error"}
# Nov 3: the bid gate's checks (bidgate.py) are Error Check rules too
from . import bidgate as _bidgate                       # noqa: E402
RULES.update(_bidgate.RULES)
SEVERITY.update(_bidgate.SEVERITY)
OUTLIER_PCT = 50
SCHED_RULES = ("sched_missing", "sched_count", "sched_extra")
CREW_RULES = ("crew_rate", "crew_hours_day", "crew_days", "unit_cost_far")
RATE_FAR = 4            # x outside every other rate for the unit
HOURS_DAY_MAX = 12      # a crew day longer than this is flagged
HOURS_DAY_IMPOSSIBLE = 24
DAYS_MIN = 0.5
DAYS_MAX = 365
COST_FAR = 10           # x the median of the job's other lines
COST_PEERS = 3          # other lines in the unit needed to compare
OFF_KEY = "estimating_check_rules_off"

HOW_TO = {
    "zero_qty": "A line or activity has a price but a quantity of 0. Link "
                "it to its takeoff group or type the quantity, or delete it.",
    "no_cost": "A line or activity has a quantity but no price, so it adds "
               "$0 to the bid. Fill in the unit price, crew or quote.",
    "unit_mismatch": "The line's unit can't be made from its takeoff group "
                     "(for example priced per CY off an area with no depth). "
                     "Fix the unit or add a formula.",
    "duplicate": "The same code, description and unit appear more than "
                 "once. Delete the copy unless both are meant to be there.",
    "missing_crew": "A civil activity has a quantity but no crew from the "
                    "library and no material, sub or quote. Pick a crew.",
    "unpriced_takeoff": "A takeoff group nobody prices. Price it, link it, "
                        "or mark it Excluded or RFI in the pre-bid checklist.",
    "outlier": "A unit cost is more than the set % away from your own past "
               "jobs for the same code and unit (Use History File...).",
    "bid_plug": "A bid-day quote is in the estimate with a plug for an "
                "item the bidder didn't quote. Get the price or keep the plug "
                "on purpose.",
    "bid_stale": "A bid-day quote changed after it was put in the estimate. "
                 "Apply it again or check the lines by hand.",
    "double_priced": "A takeoff group is priced by its own unit cost and "
                     "also by a line, assembly or civil activity. Keep one.",
    "no_cost_type": "Priced with a unit cost but no cost type, so it is not "
                    "on the material order list. Pick a cost type.",
    "sched_missing": "The plan's own door, window, fixture, equipment or "
                     "finish schedule lists a type (or room) that has nothing "
                     "in the takeoff. Count it, or switch this rule off. "
                     "Advisory: read from the PDF's text, with a confidence.",
    "sched_count": "The takeoff count for a type differs from the schedule's "
                   "QTY (or, for doors, its rows). Recount on the plans - the "
                   "schedule can be wrong too. Nothing is changed for you.",
    "sched_extra": "A takeoff item named like a scheduled type (Light X, "
                   "P-9...) that no schedule lists, or a room area not on the "
                   "finish schedule. Check the name or the schedule.",
    "crew_rate": "The activity's production per crew hour is more than 4x "
                 "above or below every other rate for the same unit in your "
                 "library and the EXAMPLE crews. Check the number and whether "
                 "it is per hour or per day.",
    "crew_hours_day": "The job's crew day is over 12 hours (over 24 can't "
                      "happen). Long days cost overtime and lose output. Set "
                      "Hours per day in the civil settings.",
    "crew_days": "An activity takes less than half a crew-day (a crew is "
                 "rarely moved in for less) or more than a year. Check the "
                 "quantity and the production rate.",
    "ai_pending": "AI Takeoff measured these but wasn't sure, so they are "
                  "held out of every total until a person checks them. "
                  "Left as they are, the bid is short by these quantities. "
                  "Accept, fix or delete them in AI Takeoff > Review Queue "
                  "(or Check Takeoff).",
    "unit_cost_far": "A unit cost is more than 10x above or below the "
                     "median of at least 3 other lines in the same unit on "
                     "this job - often a typo or a wrong unit. Different work "
                     "can share a unit, so check before changing it.",
}


HOW_TO.update(_bidgate.HOW_TO)


def rules_off():
    """The rules switched off (kept in the settings file)."""
    from .. import settings
    v = settings.get(OFF_KEY) or []
    return {r for r in v if r in RULES} if isinstance(v, list) else set()


def set_rule_on(rule, on=True):
    from .. import settings
    if rule not in RULES:
        raise ValueError(f"no check named {rule!r}")
    off = rules_off()
    (off.discard if on else off.add)(rule)
    settings.set(OFF_KEY, sorted(off))


def _f(rule, item, message, severity=None, **extra):
    return dict({"severity": severity or SEVERITY[rule], "rule": rule,
                 "item": str(item), "message": message}, **extra)


def _line_checks(doc, history, outlier_pct):
    from .. import estimate_lines as EL
    out = []
    try:
        rows = EL.priced(doc)
    except Exception:                                     # noqa: BLE001
        log.warning("estimate lines unreadable", exc_info=True)
        return out, set()
    linked = set()
    seen = {}
    for r in rows:
        name = r["desc"] or r["code"] or "(line)"
        link = r.get("link")
        if link:
            linked.add((link["name"], link["type"], link["unit"]))
        unit_bad = False
        if link and r.get("problem") and "has no markups" not in r["problem"]:
            unit_bad = True
            out.append(_f("unit_mismatch", name, r["problem"]))
        elif link and not link.get("formula"):
            why = EL.link_problem(link, r["unit"] or link["unit"])
            if why:
                unit_bad = True
                out.append(_f("unit_mismatch", name, why))
        has_price = r["unit_cost"] != 0
        if not unit_bad and r["quantity"] == 0 and has_price:
            out.append(_f("zero_qty", name, "Quantity is 0" + (
                f" (takeoff group {link['name']!r} has no markups)"
                if link else "")))
        if r["quantity"] != 0 and not has_price:
            out.append(_f("no_cost", name, f"{r['quantity']} "
                          f"{r['unit_label']} with no unit price"))
        key = (r["code"], _io.norm(r["desc"]), _io.norm(r["unit_label"]))
        seen.setdefault(key, []).append(name)
        if history and has_price and r["code"]:
            past = history.get((r["code"], _io.norm(r["unit_label"])))
            if past:
                med = Decimal(str(statistics.median(
                    [Decimal(str(x)) for x in past])))
                if med:
                    pct = abs(r["unit_cost"] - med) / med * 100
                    if pct > Decimal(outlier_pct):
                        out.append(_f(
                            "outlier", name,
                            f"${r['unit_cost']:.2f} per {r['unit_label']} "
                            f"vs your history median ${med:.2f} "
                            f"({len(past)} past jobs, "
                            f"{pct.quantize(Decimal('1'))}% off)"))
    for key, names in seen.items():
        if len(names) > 1 and (key[0] or key[1]):
            out.append(_f("duplicate", names[0],
                          f"{len(names)} lines with code {key[0] or '-'}, "
                          f"'{names[0]}', unit {key[2] or '-'}"))
    return out, linked


def _priced_by(doc, groups, linked, job):
    """{(name, type, unit): [what else prices it]} - linked lines, an
    applied bid-day package, a civil activity, an assembly (a group's own
    unit cost is not in the list)."""
    from .. import assemblies
    try:
        ajob, alib = assemblies.read_job(doc), assemblies.library()
    except Exception:                                     # noqa: BLE001
        ajob, alib = None, None
    used_by_civil = {a.get("group") for a in (job or {}).get(
        "activities") or [] if a.get("group")}
    try:
        from . import bidday
        by_bid = bidday.applied_groups(doc)
    except Exception:                                     # noqa: BLE001
        log.warning("bid-day sheets unreadable", exc_info=True)
        by_bid = {}
    out = {}
    for g in groups:
        k = (g["name"], g["type"], g["unit"])
        also = []
        if k in linked:
            also.append("a linked estimate line")
        if k in by_bid:
            also.append(f"bid-day package {by_bid[k]!r}")
        if g["name"] in used_by_civil:
            also.append("a civil activity")
        try:
            if ajob is not None and assemblies.find(doc, g["name"], ajob,
                                                    alib):
                also.append("an assembly")
        except Exception:                                 # noqa: BLE001
            pass
        out[k] = also
    return out


@safedb.read_only
def priced_groups(doc, job=None):
    """The takeoff groups (name, type, unit) something already prices:
    their own unit cost, a linked line, an applied bid-day package, a
    civil activity or an assembly (read only)."""
    from .. import annotate, estimate, estimate_lines as EL
    if doc is None:
        return set()
    with annotate.scan_cache():
        groups = estimate.lines(doc)
        linked = {(ln["link"]["name"], ln["link"]["type"], ln["link"]["unit"])
                  for ln in EL.read(doc) if ln.get("link")}
        by = _priced_by(doc, groups, linked, job)
    return {k for k, also in by.items() if also} | {
        (g["name"], g["type"], g["unit"]) for g in groups
        if g.get("unit_cost")}


def _group_checks(doc, linked, job):
    from .. import estimate
    out = []
    try:
        groups = estimate.lines(doc)
    except Exception:                                     # noqa: BLE001
        log.warning("takeoff groups unreadable", exc_info=True)
        return out
    by = _priced_by(doc, groups, linked, job)
    accounted = _prebid_accounted(doc)
    for g in groups:
        k = (g["name"], g["type"], g["unit"])
        also = by[k]
        if g.get("unit_cost") and also:
            out.append(_f("double_priced", g["name"],
                          f"has its own unit cost ${g['unit_cost']:,.2f} per "
                          f"{g['unit']} and is also priced by "
                          + " and ".join(also)))
        if also or g.get("unit_cost") or accounted.get(k):
            continue
        out.append(_f("unpriced_takeoff", g["name"],
                      f"{g['quantity']:,.2f} {g['unit']} on page(s) "
                      f"{g.get('pages', '')} has no price, line, assembly "
                      "or activity"))
    return out


def _prebid_accounted(doc):
    """{(name, type, unit): True} for takeoff groups whose every markup
    is accounted for in the pre-bid checklist (prebid.py: priced, RFI, or
    excluded with a reason) - "not priced here" is then on purpose."""
    from .. import annotate, prebid
    acc = {}
    try:
        for page in doc:
            for a in annotate.iter_annots(page):
                subj = (a.info or {}).get("subject", "")
                if not subj.startswith(annotate.TAKEOFF + ":"):
                    continue
                parts = (subj.split(":", 5) + [""] * 6)[:6]
                _t, mtype, _v, unit, group, _p = parts
                if mtype == annotate.CUTOUT:
                    continue
                k = (group or mtype.title(), mtype, unit)
                sc = prebid.scope_of(doc, a)
                ok = sc.get("status") in ("priced", "rfi") or (
                    sc.get("status") == "excluded" and bool(sc.get("reason")))
                acc[k] = acc.get(k, True) and ok
    except Exception:                                     # noqa: BLE001
        log.warning("pre-bid scope unreadable", exc_info=True)
        return {}
    return acc


def _civil_checks(job, lib):
    from .. import heavy
    out = []
    items = {p.get("no"): p for p in job.get("pay_items") or []}
    seen = {}
    for a in job.get("activities") or []:
        name = a.get("name") or "(activity)"
        try:
            c = heavy.activity_cost(a, lib, job)
        except Exception as e:                            # noqa: BLE001
            out.append(_f("no_cost", name, f"can't price it: {e}"))
            continue
        qty = heavy.D(a.get("qty"))
        has_other = bool(a.get("materials") or heavy.D(a.get("sub")) or
                         a.get("quotes"))
        crew_ok = bool(a.get("crew")) and a["crew"] in (lib.get("crews")
                                                         or {})
        if qty and not crew_ok and not has_other:
            out.append(_f("missing_crew", name,
                          f"crew {a['crew']!r} isn't in the library"
                          if a.get("crew") else
                          "no crew, material, sub or quote"))
        elif qty and crew_ok and "no production rate" in (c.get("problem")
                                                          or ""):
            out.append(_f("no_cost", name, "no production rate"))
        if not qty and (a.get("crew") or has_other):
            out.append(_f("zero_qty", name, "Quantity is 0"))
        p = items.get(a.get("pay_item"))
        if p and p.get("unit") and a.get("unit") and \
                _io.norm(p["unit"]) != _io.norm(a["unit"]):
            out.append(_f("unit_mismatch", name,
                          f"in {a['unit']}; pay item {p['no']} is in "
                          f"{p['unit']}"))
        key = (_io.norm(name), a.get("pay_item") or "")
        seen.setdefault(key, []).append(name)
    for p in items.values():
        if not heavy.D(p.get("owner_qty")):
            out.append(_f("zero_qty", f"Pay item {p.get('no')}",
                          "Owner's quantity is 0"))
    for key, names in seen.items():
        if len(names) > 1:
            out.append(_f("duplicate", names[0],
                          f"{len(names)} activities named '{names[0]}' on "
                          f"pay item {key[1] or '-'}"))
    return out


def _bid_checks(doc):
    from . import bidday
    try:
        found = bidday.applied_problems(doc)
    except Exception:                                     # noqa: BLE001
        log.warning("bid-day sheets unreadable", exc_info=True)
        return []
    return [_f("bid_plug" if kind == "plug" else "bid_stale", item, msg)
            for _pkg, item, kind, msg in found]


@safedb.read_only
def run(doc, job=None, lib=None, history=None, outlier_pct=OUTLIER_PCT,
        off=None):
    """Every finding for the document's estimate and (optional) civil job.
    `history` = {(code, unit lower-case): [past unit costs]}. `off`: rules
    to leave out (None = the ones switched off in the settings)."""
    from .. import annotate
    off = rules_off() if off is None else set(off)
    with annotate.scan_cache():
        found = _run(doc, job, lib, history, outlier_pct, off)
    return [f for f in found if f["rule"] not in off]


def _pending_checks(doc):
    """Nov 1: AI items still in review are kept out of the totals, so a bid
    could go out short with no warning. One finding per takeoff group."""
    from .. import annotate
    try:
        items = annotate.takeoff_items(doc)
    except Exception:                                     # noqa: BLE001
        log.warning("pending AI items not checked", exc_info=True)
        return []
    by = {}
    for it in items:
        if not it.get("pending"):
            continue
        k = (it.get("group") or "(no group)", it.get("unit") or "")
        n, v = by.get(k, (0, 0.0))
        by[k] = (n + 1, v + float(it.get("value") or 0) *
                 float(it.get("multiplier") or 1))
    return [_f("ai_pending", g,
               f"{n} AI measurement(s) still in review, "
               f"{v:,.0f} {u} not in the totals - accept or fix them in "
               "AI Takeoff > Review Queue", count=n, quantity=round(v, 2),
               unit=u)
            for (g, u), (n, v) in sorted(by.items())]


def _cost_type_checks(doc):
    from .. import estimate
    try:
        groups = estimate.lines(doc)
    except Exception:                                     # noqa: BLE001
        return []
    return [_f("no_cost_type", g["name"],
               "Priced by a unit cost with no cost type - it is in the "
               "total but not counted as material (not on the material "
               "order list); pick a cost type in the Estimate panel")
            for g in groups if g.get("unit_cost") and g.get("total")
            and not str(g.get("cost_type") or "").strip()]


def _run(doc, job, lib, history, outlier_pct, off=()):
    out, linked = [], set()
    lib = lib or {"crews": {}, "labor": {}, "equipment": {}, "settings": {}}
    if doc is not None:
        found, linked = _line_checks(doc, history, outlier_pct)
        out += found
        out += _group_checks(doc, linked, job)
        out += _bid_checks(doc)
        out += _cost_type_checks(doc)
        out += _pending_checks(doc)
        if not set(SCHED_RULES) <= set(off):
            out += _schedule_checks(doc)
    if doc is not None or job is not None:
        out += _bidgate.run(doc, job)
    if job is not None:
        out += _civil_checks(job, lib)
        out += _crew_checks(job, lib)
    if "unit_cost_far" not in off:
        out += _unit_cost_checks(doc, job, lib)
    order = {"error": 0, "warning": 1}
    return sorted(out, key=lambda f: (order[f["severity"]], f["rule"]))


def _schedule_checks(doc):
    from . import schedcheck
    try:
        res = schedcheck.check(doc)
    except Exception:                                     # noqa: BLE001
        log.warning("schedules not checked", exc_info=True)
        return []
    rule = {"missing": "sched_missing", "count": "sched_count",
            "extra": "sched_extra"}
    return [_f(rule[x["check"]], x["group"] or f"{x['kind']} {x['key']}",
               x["message"], confidence=x["confidence"])
            for x in res["findings"]]


def _n(v):
    from .. import heavy
    return float(heavy.D(v))


def _peer_rates(lib, job):
    """{unit: [production per crew hour]} from the library crews' and the
    EXAMPLE crews' production lines (never prices)."""
    from . import starters
    hpd = _n((job.get("settings") or {}).get("hours_per_day") or 10) or 10
    out = {}
    crews = list((lib.get("crews") or {}).values())
    try:
        crews += starters.crew_pack()["crews"]
    except Exception:                                     # noqa: BLE001
        pass
    for c in crews:
        for p in (c or {}).get("production") or []:
            try:
                r = _n(p.get("rate"))
            except Exception:                             # noqa: BLE001
                continue
            if r <= 0:
                continue
            r = r / hpd if p.get("per") == "day" else r
            out.setdefault(_io.norm(p.get("unit") or ""), []).append(r)
    return out


def _g(x):
    return f"{x:,.2f}".rstrip("0").rstrip(".")


def _crew_checks(job, lib):
    from .. import heavy
    out = []
    st = job.get("settings") or {}
    hpd = _n(st.get("hours_per_day") or 10)
    acts = [a for a in job.get("activities") or [] if a.get("crew")]
    if acts and hpd > HOURS_DAY_IMPOSSIBLE:
        out.append(_f("crew_hours_day", "Hours per day",
                      f"The job is set to {_g(hpd)} crew hours a day - more "
                      f"than the {HOURS_DAY_IMPOSSIBLE} hours in a day, so "
                      "every crew-day and duration is wrong",
                      severity="error"))
    elif acts and hpd > HOURS_DAY_MAX:
        out.append(_f("crew_hours_day", "Hours per day",
                      f"The job is set to {_g(hpd)} crew hours a day; over "
                      f"{HOURS_DAY_MAX} is rarely kept up - overtime and "
                      "tired crews cost more and produce less than the rates "
                      "assume"))
    peers = _peer_rates(lib, job)
    for a in acts:
        name = a.get("name") or "(activity)"
        try:
            rate = _n(a.get("rate"))
            qty = _n(a.get("qty"))
        except Exception:                                 # noqa: BLE001
            continue
        if rate <= 0 or qty <= 0:
            continue
        ph = rate / hpd if a.get("per") == "day" and hpd else rate
        unit = a.get("unit") or ""
        others = list(peers.get(_io.norm(unit), []))
        for b in acts:
            if b is a or _io.norm(b.get("unit") or "") != _io.norm(unit):
                continue
            try:
                r = _n(b.get("rate"))
            except Exception:                             # noqa: BLE001
                continue
            if r > 0:
                others.append(r / hpd if b.get("per") == "day" and hpd
                              else r)
        lib_rates = peers.get(_io.norm(unit), [])
        if lib_rates:
            lo, hi = min(lib_rates), max(lib_rates)
            if ph > hi * RATE_FAR or ph < lo / RATE_FAR:
                out.append(_f(
                    "crew_rate", name,
                    f"Produces {_g(ph)} {unit} per crew hour; the library "
                    f"and EXAMPLE crews run {_g(lo)}-{_g(hi)} {unit} per "
                    f"hour - more than {RATE_FAR}x "
                    f"{'faster' if ph > hi else 'slower'}. Check the number "
                    "and whether it is per hour or per day"))
        try:
            c = heavy.activity_cost(a, lib, job)
        except Exception:                                 # noqa: BLE001
            continue
        days = float(c.get("days") or 0)
        if c.get("hours") and 0 < days < DAYS_MIN:
            out.append(_f("crew_days", name,
                          f"Only {_g(days)} crew-days ({_g(float(c['hours']))}"
                          " h): less than half a day - a crew is rarely "
                          "moved in for less; check the quantity or rate, "
                          "or allow a minimum"))
        elif days > DAYS_MAX:
            out.append(_f("crew_days", name,
                          f"{_g(days)} crew-days - more than a year of work "
                          f"for one crew at {_g(hpd)} h a day; check the "
                          "quantity, the rate and its unit"))
    return out


def _unit_cost_checks(doc, job, lib):
    """Every priced line, takeoff group and civil activity by unit; one far
    from the median of the others in its unit is flagged."""
    from .. import heavy
    pool = []
    if doc is not None:
        from .. import estimate_lines as EL
        try:
            for r in EL.priced(doc):
                if r["unit_cost"] and r["quantity"]:
                    pool.append((r["desc"] or r["code"] or "(line)",
                                 r["unit_label"], float(r["unit_cost"])))
        except Exception:                                 # noqa: BLE001
            pass
        try:
            from .. import estimate
            for g in estimate.lines(doc):
                if g.get("unit_cost") and g.get("quantity"):
                    pool.append((g["name"], g.get("unit") or "",
                                 float(g["unit_cost"])))
        except Exception:                                 # noqa: BLE001
            pass
    if job is not None:
        for a in job.get("activities") or []:
            try:
                c = heavy.activity_cost(a, lib, job)
            except Exception:                             # noqa: BLE001
                continue
            if c.get("unit_cost"):
                pool.append((a.get("name") or "(activity)",
                             a.get("unit") or "", float(c["unit_cost"])))
    by = {}
    for i, (name, unit, cost) in enumerate(pool):
        if cost > 0 and unit:
            by.setdefault(_io.norm(unit), []).append((i, name, unit, cost))
    out = []
    for rows in by.values():
        if len(rows) < COST_PEERS + 1:
            continue
        for i, name, unit, cost in rows:
            med = statistics.median(c for j, _n2, _u, c in rows if j != i)
            if med > 0 and (cost > med * COST_FAR or cost < med / COST_FAR):
                out.append(_f(
                    "unit_cost_far", name,
                    f"${_g(cost)} per {unit} - the median of the job's "
                    f"{len(rows) - 1} other lines per {unit} is "
                    f"${_g(med)}, more than {COST_FAR}x "
                    f"{'higher' if cost > med else 'lower'}; check for a "
                    "typo or a wrong unit"))
    return out


def summary(found):
    return {"errors": sum(1 for f in found if f["severity"] == "error"),
            "warnings": sum(1 for f in found if f["severity"] == "warning")}


def export_csv(found, path):
    return _io.write_table(path, ["Severity", "Rule", "Check", "Item",
                                  "Message"],
                           [[f["severity"], f["rule"], RULES[f["rule"]],
                             f["item"], f["message"]] for f in found])
