"""Quick $/SF estimate from your own past jobs.

Pick a building type and a floor area; the price comes from the jobs of
that type in your Job Cost Feedback (bid vs actual) history in the price
database - nothing else. Each past job's cost is what it really cost
when its actual costs are in (the sum of its actual line costs), else
the contract amount, else the bid total, else its estimate lines; divided
by the job's building SF (entered once per job, kept in the price
database) that is its $/SF.

    estimate = median $/SF x SF        range = lowest .. highest $/SF x SF

The result can go into the Estimate panel as one allowance line per CSI
division, split the way those past jobs' own lines split by division
(lines without a code: one "Uncoded" allowance). With no history for the
type it says so and creates nothing. Money is Decimal cents.
"""
import logging
import statistics
from decimal import Decimal

from . import csi, dmoney

log = logging.getLogger(__name__)

META_SF = "quick_sf_job_sf"          # {job id: "building SF"}
Z = Decimal("0.00")


class QuickSFError(ValueError):
    pass


# ---- job SF (kept in the price database's meta table) ---------------------

def _sf_map():
    from . import pricedb
    try:
        m = pricedb.meta(META_SF) or {}
    except Exception:                                     # noqa: BLE001
        log.warning("job SF unavailable", exc_info=True)
        return {}
    return m if isinstance(m, dict) else {}


def job_sf(job_id):
    v = _sf_map().get(str(job_id))
    d = dmoney.D(v) if v not in (None, "") and not dmoney.bad(v) else None
    return d if d is not None and d > 0 else None


def set_job_sf(job_id, sf):
    """Record a past job's building SF (blank or 0 clears it)."""
    from . import pricedb
    m = dict(_sf_map())
    if sf in (None, "") or (not dmoney.bad(sf) and dmoney.D(sf) == 0):
        m.pop(str(job_id), None)
    else:
        if dmoney.bad(sf) or dmoney.D(sf) < 0:
            raise QuickSFError(f"Building SF: can't read {sf!r}")
        m[str(job_id)] = str(dmoney.D(sf).quantize(Decimal("0.01")))
    pricedb.set_meta(META_SF, m)


def set_job_type(job_id, btype):
    """Set a past job's building type (the jobs table's own "type")."""
    from . import pricedb
    with pricedb.connect(write=True) as con:
        con.execute("UPDATE jobs SET type=? WHERE id=?",
                    (" ".join(str(btype or "").split())[:80], job_id))


# ---- history ------------------------------------------------------------

def _norm(t):
    return " ".join(str(t or "").split()).lower()


def _job_cost(job, lines):
    """(Decimal cost, where it came from) of one past job, or (None, "")."""
    acts = [dmoney.D(r["act_cost"]) for r in lines
            if r.get("act_cost") not in (None, "") and
            not dmoney.bad(r["act_cost"])]
    if acts and sum(acts, Z) > 0:
        return dmoney.cents(sum(acts, Z)), "actual cost"
    for key, what in (("contract", "contract"), ("bid_total", "bid")):
        v = job.get(key)
        if v not in (None, "") and not dmoney.bad(v) and dmoney.D(v) > 0:
            return dmoney.cents(v), what
    est = sum((dmoney.D(r.get("est_qty")) * dmoney.D(r.get("est_unit_cost"))
               for r in lines), Z)
    if est > 0:
        return dmoney.cents(est), "estimate lines"
    return None, ""


def _division_amounts(lines, actual):
    """{division or "": Decimal} of a job's lines (actual costs when the
    job's cost is its actuals, else the estimate)."""
    out = {}
    for r in lines:
        if actual:
            if r.get("act_cost") in (None, "") or dmoney.bad(r["act_cost"]):
                continue
            amt = dmoney.D(r["act_cost"])
        else:
            amt = dmoney.D(r.get("est_qty")) * dmoney.D(r.get("est_unit_cost"))
        if amt <= 0:
            continue
        c = csi.parse_code(r.get("code") or "")
        d = c[:2] if c and c[:2] in csi.DIVISIONS else ""
        out[d] = out.get(d, Z) + amt
    return out


def building_types():
    """Generate Set's building types, then the types in your history."""
    names = []
    try:
        from .genset import types as gt
        for k in gt.keys():
            t = gt.get(k)
            names.append(getattr(t, "label", "") or k)
    except Exception:                                     # noqa: BLE001
        log.debug("Generate Set building types unavailable", exc_info=True)
    try:
        from . import pricehistory
        for j in pricehistory.jobs():
            t = " ".join(str(j.get("type") or "").split())
            if t and _norm(t) not in {_norm(n) for n in names}:
                names.append(t)
    except Exception:                                     # noqa: BLE001
        log.debug("job history unavailable", exc_info=True)
    return names


def history(btype):
    """[{id, number, name, type, sf, cost, basis, per_sf, divisions}] for
    your past jobs of this building type that have an SF and a cost."""
    from . import pricehistory
    want = _norm(btype)
    if not want:
        return []
    sfs = _sf_map()
    out = []
    for j in pricehistory.jobs():
        if _norm(j.get("type")) != want:
            continue
        v = sfs.get(str(j["id"]))
        if v in (None, "") or dmoney.bad(v) or dmoney.D(v) <= 0:
            continue
        sf = dmoney.D(v)
        lines = pricehistory.lines(j["id"])
        cost, basis = _job_cost(j, lines)
        if cost is None:
            continue
        out.append({"id": j["id"], "number": j.get("number", ""),
                    "name": j.get("name", ""), "type": j.get("type", ""),
                    "sf": sf, "cost": cost, "basis": basis,
                    "per_sf": cost / sf,
                    "divisions": _division_amounts(
                        lines, basis == "actual cost")})
    return out


def estimate(btype, sf, jobs=None):
    """{"type", "sf", "jobs", "count", "per_sf": median, "low_per_sf",
    "high_per_sf", "median", "low", "high", "lines"} or None when there
    is no history for the type. "lines" are [{division, title, amount}]
    adding up to the median exactly."""
    if dmoney.bad(sf, blank_ok=False) or dmoney.D(sf) <= 0:
        raise QuickSFError("Enter the building's square feet.")
    sf = dmoney.D(sf)
    jobs = history(btype) if jobs is None else jobs
    if not jobs:
        return None
    rates = [j["per_sf"] for j in jobs]
    med = statistics.median(rates)
    lo, hi = min(rates), max(rates)
    median = dmoney.cents(med * sf)
    res = {"type": jobs[0].get("type") or btype, "sf": sf, "jobs": jobs,
           "count": len(jobs),
           "per_sf": dmoney.cents(med), "low_per_sf": dmoney.cents(lo),
           "high_per_sf": dmoney.cents(hi), "median": median,
           "low": dmoney.cents(lo * sf), "high": dmoney.cents(hi * sf)}
    res["lines"] = split(median, jobs)
    return res


def split(amount, jobs):
    """The amount by CSI division in the average share of the past jobs'
    lines (jobs without lines don't vote); one Uncoded line when none has
    lines. The last line takes the rounding, so they add up exactly."""
    shares, n = {}, 0
    for j in jobs:
        divs = j.get("divisions") or {}
        tot = sum(divs.values(), Z)
        if tot <= 0:
            continue
        n += 1
        for d, v in divs.items():
            shares[d] = shares.get(d, Decimal(0)) + v / tot
    if not n:
        return [{"division": "", "title": "Uncoded", "amount": amount}]
    keys = sorted(shares, key=lambda d: (d == "", d))
    out, used = [], Z
    for i, d in enumerate(keys):
        if i == len(keys) - 1:
            amt = amount - used
        else:
            amt = dmoney.cents(amount * shares[d] / n)
            used += amt
        title = csi.DIVISIONS.get(d, "Uncoded") if d else "Uncoded"
        out.append({"division": d,
                    "title": title[:1].upper() + title[1:], "amount": amt})
    return [x for x in out if x["amount"]]


def to_lines(res):
    """Allowance lines (estimate_lines.new_line) for a quick estimate."""
    from . import estimate_lines
    out = []
    for x in res["lines"]:
        what = (f"Division {x['division']} {x['title']}" if x["division"]
                else "Uncoded")
        out.append(estimate_lines.new_line(
            desc=f"Allowance - {what} (quick $/SF, {res['type']}, "
                 f"{float(res['sf']):,.0f} SF)",
            qty=1, unit="ls",
            code=f"{x['division']} 00 00" if x["division"] else "",
            cost_type="Allowance", sub=x["amount"],
            source=f"Quick $/SF from {res['count']} past job(s)",
            note=f"median {dmoney.fmt(res['per_sf'])}/SF, range "
                 f"{dmoney.fmt(res['low_per_sf'])}-"
                 f"{dmoney.fmt(res['high_per_sf'])}/SF"))
    return out


def describe(res, btype=""):
    """One paragraph for the dialog."""
    if res is None:
        return (f"No past jobs of type {btype!r} with a building SF in your "
                "Job Cost Feedback history - nothing to price from. Add the "
                "jobs' building SF below (or register jobs in Job Cost "
                "Feedback) and try again.")
    return (f"{res['count']} past {res['type']} job(s): median "
            f"{dmoney.fmt(res['per_sf'])}/SF (range "
            f"{dmoney.fmt(res['low_per_sf'])} - "
            f"{dmoney.fmt(res['high_per_sf'])}/SF). For "
            f"{float(res['sf']):,.0f} SF: {dmoney.fmt(res['median'])} "
            f"(range {dmoney.fmt(res['low'])} - {dmoney.fmt(res['high'])}).")
