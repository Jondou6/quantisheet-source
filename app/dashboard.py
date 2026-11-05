"""Estimating Dashboard: compare every estimate and bid the company has.

Pure Python (no Qt); the window is dashboard_ui.py. Nothing here keeps a
database of its own - it reads what the app already stores:

* the price database (pricedb.py): Job Cost Feedback jobs and their lines
  (estimate and actual cost by cost code), each job's building SF (kept
  by Quick $/SF in the meta table) and building type (the jobs table's
  "type"), and the bid tab library (bid_projects / bid_rows);
* each project folder's .quantisheet/project.json (pm/store.py), read
  read-only: project settings (building type, SF, bid date, estimator,
  owner, job site, our bid, bid result), Scope Sheets and Bid Packages
  (every sub's bid per trade, the low bid and the award);
* the folders to read: Project Center's recent projects (setting
  "pm_recent"), folders added in the dashboard ("dashboard_folders") and
  any folder a Job Cost Feedback job names.

A project that can't be read (missing, damaged JSON, not a project) is
skipped and listed - it never stops the others, and it is never moved or
changed (Project Center itself renames a damaged file when it opens it).

Bid result (won / lost): nothing recorded the company's own bid result
before, so it is new - the project setting "bid_result" and the price
database jobs table's "result" column (added by pricedb._init). Older
projects and jobs have neither: a job closed in Job Cost Feedback (it was
built) counts as Won, anything else as Pending, until someone sets it.

All money is Decimal, exact to the cent (dmoney.py). Statistics:
  median     the middle value (the mean of the two middle ones)
  range      lowest .. highest
  quartiles  Excel's QUARTILE.INC (linear between ranks)
  outlier    below Q1 - 1.5 x IQR or above Q3 + 1.5 x IQR, judged only
             when a group has at least MIN_OUTLIER_N values
  trend      least-squares slope of $/SF against the bid date, per year
             (at least 3 values on 2 or more dates)
  hit rate   won / (won + lost); pending and no-bid jobs are counted but
             not in the rate
"""
import datetime as _dt
import json
import logging
import os
import re
from decimal import ROUND_HALF_UP, Decimal

from . import csi, safecell
from .dmoney import D, bad, cents

log = logging.getLogger(__name__)

RESULTS = ("Won", "Lost", "Pending", "No bid")
RESULT_SETTING = "bid_result"          # project setting (new)
FOLDERS_SETTING = "dashboard_folders"  # extra folders added in the window
SF_META = "quick_sf_job_sf"            # = quick_sf.META_SF {job id: SF}
PROJECT_FILE = os.path.join(".quantisheet", "project.json")


def project_file(folder):
    """The job's project.json - where a job not opened since the rename
    still keeps it too (oldnames; read only, nothing renamed here)."""
    from . import oldnames
    d = oldnames.job_dir_if_any(folder)
    return os.path.join(d, "project.json") if d else \
        os.path.join(folder, PROJECT_FILE)
# project settings the dashboard reads (Project Center > Project settings)
PROJECT_SETTINGS = ("building_type", "building_sf", "bid_date", "estimator",
                    "bid_amount", RESULT_SETTING, "owner", "location",
                    "number", "low_bid")
LOW_SETTING = "low_bid"                # Nov 3: the low bidder's number
MIN_OUTLIER_N = 4
FENCE = Decimal("1.5")
HIT_BY = ("type", "owner", "month", "estimator", "size", "markup")
BY_LABEL = {"type": "Building type", "owner": "Owner", "month": "Bid month",
            "estimator": "Estimator", "division": "CSI division",
            "size": "Job size (our bid)", "markup": "Markup on cost"}
NO_GROUP = {"type": "(no building type)", "owner": "(no owner)",
            "month": "(no bid date)", "estimator": "(no estimator)",
            "size": "(no bid amount)", "markup": "(no cost to compare)"}
# Nov 3 hit rate by size and markup: (upper limit, label), last open-ended
SIZE_BANDS = ((250_000, "Under $250K"), (1_000_000, "$250K - $1M"),
              (5_000_000, "$1M - $5M"), (None, "$5M and up"))
MARKUP_BANDS = ((5, "Under 5%"), (10, "5% - 10%"), (15, "10% - 15%"),
                (None, "15% and up"))
Z = Decimal("0.00")
TENTH = Decimal("0.1")
US_STATES = frozenset(
    "AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI "
    "MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT "
    "VA WA WV WI WY PR GU VI".split())
EMPTY_HINT = (
    "Nothing to compare yet. The dashboard reads your Job Cost Feedback "
    "jobs (Estimate > Job Cost Feedback; give each a building type and SF "
    "in Quick $/SF) and your Project Center projects (Project settings: "
    "building type, building SF, bid date, estimator, our bid and the bid "
    "result; Scope Sheets and Bid Packages for sub prices). Projects in "
    "other folders: Add Project Folders….")


class DashboardError(RuntimeError):
    pass


class Skip(Exception):
    """A project folder that can't be read (the reason is the message)."""


# ============================================================ small parts
def _s(v):
    return " ".join(str(v or "").split())


def _norm(v):
    return _s(v).lower()


def money(v):
    """Typed/stored money -> Decimal cents, None for blank or bad."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, str) and not v.strip():
        return None
    if bad(v):
        return None
    return cents(D(v))


def quantity(v):
    """A positive quantity (building SF) or None."""
    if v is None or isinstance(v, bool) or bad(v, blank_ok=False):
        return None
    d = D(v)
    return d.quantize(Decimal("0.01")) if d > 0 else None


def parse_date(v, end=False):
    """'2026-03-14', '2026-03' (month: the 1st, or its last day with
    end=True), '3/14/2026' -> date; None when it can't be read."""
    s = str(v or "").strip()
    if not s:
        return None
    if isinstance(v, _dt.datetime):
        return v.date()
    if isinstance(v, _dt.date):
        return v
    m = re.match(r"(\d{4})-(\d{1,2})(?:-(\d{1,2}))?", s)
    month_only = False
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        if m.group(3):
            d = int(m.group(3))
        else:
            d, month_only = 1, True
    else:
        m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{2,4})\b", s)
        if not m:
            return None
        mo, d, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if y < 100:
            y += 2000
    try:
        out = _dt.date(y, mo, d)
    except ValueError:
        return None
    if month_only and end:
        nxt = _dt.date(y + (mo == 12), mo % 12 + 1, 1)
        out = nxt - _dt.timedelta(days=1)
    return out


def state_of(*texts):
    """Two-letter state from 'Town, ST', 'Town, ST 12345' or 'ST ...'."""
    for t in texts:
        s = _s(t).upper()
        if not s:
            continue
        if s in US_STATES:
            return s
        m = re.search(r"(?:^|[\s,])([A-Z]{2})(?:\s+\d{5}(?:-\d{4})?)?\s*$",
                      s)
        if m and m.group(1) in US_STATES:
            return m.group(1)
        m = re.match(r"([A-Z]{2})\b", s)
        if m and m.group(1) in US_STATES:
            return m.group(1)
    return ""


def company_key(name):
    """'Example Drywall, LLC' and 'EXAMPLE DRYWALL' are the same sub."""
    t = re.sub(r"[^a-z0-9& ]", " ", str(name or "").lower())
    words = [w for w in t.split() if w not in
             ("llc", "inc", "co", "corp", "corporation", "company", "ltd",
              "the", "lp", "llp", "pllc")]
    return " ".join(words)


def division_of(code_or_text):
    c = csi.parse_code(code_or_text or "")
    if not c:
        m = re.search(r"\b(\d{2})\s?(\d{2})\s?(\d{2})\b",
                      str(code_or_text or ""))
        c = csi.parse_code(" ".join(m.groups())) if m else ""
    return c[:2] if c and c[:2] in csi.DIVISIONS else ""


def section_of(text):
    """'09 29 00 Gypsum board' -> '09 29 00' ('' when none)."""
    t = str(text or "")
    c = csi.parse_code(t.strip())
    if not c:
        m = re.search(r"\b(\d{2})\s?(\d{2})\s?(\d{2})\b", t)
        c = csi.parse_code(" ".join(m.groups())) if m else ""
    return c[:8] if c and c[:2] in csi.DIVISIONS else ""


def division_label(div):
    return f"{div} {csi.DIVISIONS[div]}" if div in csi.DIVISIONS \
        else "(no division)"


def pct(num, den):
    """num / den as a percent to 0.1, None when den is 0 or missing."""
    if num is None or den is None or D(den) == 0:
        return None
    return (D(num) * 100 / D(den)).quantize(TENTH, rounding=ROUND_HALF_UP)


# ============================================================ statistics
def median(values):
    s = sorted(D(v) for v in values)
    n = len(s)
    if not n:
        return None
    if n % 2:
        return s[n // 2]
    return (s[n // 2 - 1] + s[n // 2]) / 2


def quartile(values, q):
    """Excel QUARTILE.INC: q in 0..4."""
    s = sorted(D(v) for v in values)
    if not s:
        return None
    pos = Decimal(len(s) - 1) * Decimal(q) / 4
    lo = int(pos)
    frac = pos - lo
    if lo + 1 >= len(s):
        return s[-1]
    return s[lo] + (s[lo + 1] - s[lo]) * frac


def stats(values):
    vals = [D(v) for v in values if v is not None]
    if not vals:
        return {"n": 0, "median": None, "low": None, "high": None,
                "q1": None, "q3": None}
    return {"n": len(vals), "median": median(vals), "low": min(vals),
            "high": max(vals), "q1": quartile(vals, 1),
            "q3": quartile(vals, 3)}


def outlier(value, st):
    """'high', 'low' or '' for a value against its group's stats."""
    if value is None or st["n"] < MIN_OUTLIER_N:
        return ""
    iqr = st["q3"] - st["q1"]
    if D(value) > st["q3"] + FENCE * iqr:
        return "high"
    if D(value) < st["q1"] - FENCE * iqr:
        return "low"
    return ""


def trend_per_year(points):
    """Least-squares slope of value against date, per 365 days (cents),
    or None with fewer than 3 points or a single date."""
    pts = [(d.toordinal(), D(v)) for d, v in points
           if d is not None and v is not None]
    if len(pts) < 3 or len({x for x, _y in pts}) < 2:
        return None
    n = Decimal(len(pts))
    mx = sum(Decimal(x) for x, _y in pts) / n
    my = sum(y for _x, y in pts) / n
    sxx = sum((Decimal(x) - mx) ** 2 for x, _y in pts)
    sxy = sum((Decimal(x) - mx) * (y - my) for x, y in pts)
    if not sxx:
        return None
    return cents(sxy / sxx * 365)


# ============================================================ price db
def read_price_db():
    """{"jobs": [...], "lines": {job id: [...]}, "sf": {job id: str},
    "tabs": [rows], "error": ""} - all of it read in one connection."""
    out = {"jobs": [], "lines": {}, "sf": {}, "tabs": [], "error": ""}
    try:
        from . import pricedb
        with pricedb.connect() as con:
            out["jobs"] = [dict(r) for r in con.execute(
                "SELECT * FROM jobs ORDER BY bid_date, id")]
            for r in con.execute("SELECT * FROM job_lines ORDER BY id"):
                r = dict(r)
                out["lines"].setdefault(r.get("job"), []).append(r)
            row = con.execute("SELECT value FROM meta WHERE key=?",
                              (SF_META,)).fetchone()
            if row and row[0]:
                try:
                    m = json.loads(row[0])
                    out["sf"] = m if isinstance(m, dict) else {}
                except ValueError:
                    log.warning("job SF table unreadable")
            out["tabs"] = [dict(r) for r in con.execute(
                "SELECT r.project, r.bidder, r.trade, r.qty, r.price, "
                "r.note, p.name AS pname, p.owner, p.state, p.location, "
                "p.bid_date FROM bid_rows r JOIN bid_projects p ON "
                "p.id = r.project")]
    except Exception as e:                                # noqa: BLE001
        log.warning("price database unavailable for the dashboard",
                    exc_info=True)
        out["error"] = f"The price database couldn't be read: {e}"
    return out


def _db_job_cost(job, lines):
    """(est cost, actual cost, cost for $/SF, basis) of a price-db job.
    The $/SF cost is what it really cost when actuals are in, else the
    contract, else the bid, else the estimate lines (as Quick $/SF)."""
    est = None
    act = None
    for r in lines:
        if r.get("est_qty") not in (None, "") or \
                r.get("est_unit_cost") not in (None, ""):
            if not bad(r.get("est_qty")) and not bad(r.get("est_unit_cost")):
                est = (est or Z) + D(r.get("est_qty")) * \
                    D(r.get("est_unit_cost"))
        if r.get("act_cost") not in (None, "") and not bad(r["act_cost"]):
            act = (act or Z) + D(r["act_cost"])
    est = cents(est) if est is not None else None
    act = cents(act) if act is not None else None
    if act is not None and act > 0:
        return est, act, act, "actual cost"
    for key, what in (("contract", "contract"), ("bid_total", "bid")):
        v = money(job.get(key))
        if v is not None and v > 0:
            return est, act, v, what
    if est is not None and est > 0:
        return est, act, est, "estimate"
    return est, act, None, ""


def _db_divisions(lines, actual):
    out = {}
    for r in lines:
        if actual:
            if r.get("act_cost") in (None, "") or bad(r["act_cost"]):
                continue
            amt = D(r["act_cost"])
        else:
            if bad(r.get("est_qty")) or bad(r.get("est_unit_cost")):
                continue
            amt = D(r.get("est_qty")) * D(r.get("est_unit_cost"))
        if amt <= 0:
            continue
        d = division_of(r.get("code"))
        out[d] = out.get(d, Z) + amt
    return {k: cents(v) for k, v in out.items()}


# ============================================================ projects
_CACHE = {}                     # project.json path -> (stamp, data)


def _project_data(folder):
    """The project's stored data (read-only), from the store Project
    Center has open when there is one, else from the file (cached by
    modification time and size)."""
    folder = os.path.abspath(folder)
    if not os.path.isdir(folder):
        raise Skip("folder not found")
    try:
        from .pm import store as _store
        live = _store._OPEN.get(folder)
    except Exception:                                     # noqa: BLE001
        live = None
    if live is not None:
        if getattr(live, "damaged", ""):
            raise Skip(f"project file damaged (moved to {live.damaged})")
        return live.data
    path = project_file(folder)
    try:
        st = os.stat(path)
    except FileNotFoundError:
        raise Skip("no QuantiSheet project in this folder")
    except OSError as e:
        raise Skip(f"can't read the project file: {e}")
    stamp = (st.st_mtime_ns, st.st_size)
    hit = _CACHE.get(path)
    if hit and hit[0] == stamp:
        return hit[1]
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (ValueError, UnicodeDecodeError) as e:
        raise Skip(f"project file damaged ({e.__class__.__name__})")
    except OSError as e:
        raise Skip(f"can't read the project file: {e}")
    if not isinstance(data, dict) or not isinstance(
            data.get("records", {}), dict) or not isinstance(
            data.get("settings", {}), dict):
        raise Skip("project file damaged (not a project)")
    _CACHE[path] = (stamp, data)
    return data


def _records(data, coll):
    c = (data.get("records") or {}).get(coll) or {}
    if not isinstance(c, dict):
        return []
    out = [r for r in c.values() if isinstance(r, dict) and
           not r.get("_deleted")]
    out.sort(key=lambda r: (str(r.get("_no") or ""),
                            str(r.get("_created") or "")))
    return out


def _sealed_shut(r):
    return str(r.get("sealed") or "").lower() in ("yes", "true", "1") and \
        not r.get("unsealed")


def _trade_bids(job_key, date, items, low_amt, med, source, trade_key,
                trade_label, division, award_known=True):
    """Sub bid entries of one trade on one job. items: [(company, cents,
    awarded)]."""
    out = []
    for company, amt, awarded in items:
        ck = company_key(company)
        if not ck:
            continue                     # an unnamed bidder can't be traced
        out.append({"job": job_key, "date": date, "trade_key": trade_key,
                    "trade": trade_label, "division": division,
                    "company": _s(company), "company_key": ck,
                    "amount": amt, "median": med,
                    "pct": pct(amt - med, med) if med else None,
                    "low": amt == low_amt,
                    "awarded": bool(awarded) if award_known else None,
                    "source": source})
    return out


def _trade_key(section, text):
    if section:
        return "csi:" + section
    return "name:" + _norm(text) if _norm(text) else ""


def _scope_bids(job_key, date, recs, warnings, name):
    """Sub bids and {division: awarded or low cents} from Scope Sheets."""
    from .pm import scope_sheet as ss
    bids, divs = [], {}
    for rec in recs:
        try:
            sh = ss.from_dict(rec)
        except Exception as e:                            # noqa: BLE001
            warnings.append(f"{name}: a scope sheet was skipped ({e})")
            continue
        totals = {}
        for b in sh["bidders"]:
            if ss.active(sh, b):
                t = ss.bidder_total(sh, b)
                if t is not None:
                    totals[b["id"]] = t
        if not totals:
            continue
        amounts = {k: ss.dollars(v) for k, v in totals.items()}
        med = median(amounts.values())
        low = min(amounts.values())
        aw = (sh.get("award") or {}).get("bidder") or ""
        section = section_of(sh.get("csi"))
        div = division_of(sh.get("csi")) or division_of(sh.get("trade"))
        label = ss.title(sh)
        d = parse_date(sh["header"].get("bid_date")) or date
        items = [(b.get("company"), amounts[b["id"]], b["id"] == aw)
                 for b in sh["bidders"] if b["id"] in amounts]
        bids += _trade_bids(job_key, d, items, low, med, "scope sheet",
                            _trade_key(section, sh.get("trade")), label, div)
        basis = ss.dollars(ss.award_amount(sh)) if aw else low
        if basis is not None:
            divs[div] = divs.get(div, Z) + basis
    return bids, divs


def _package_bids(job_key, date, recs):
    bids, divs = [], {}
    for r in recs:
        if _sealed_shut(r):
            continue
        rows = [b for b in r.get("bidders") or [] if isinstance(b, dict)]
        aw_name = company_key(r.get("awarded_to"))
        items = []
        for b in rows:
            amt = money(b.get("amount"))
            if amt is None or amt <= 0:
                continue
            awarded = b.get("status") == "Awarded" or (
                aw_name and company_key(b.get("company")) == aw_name)
            items.append((b.get("company"), amt, awarded))
        if not items:
            continue
        vals = [a for _c, a, _w in items]
        med, low = median(vals), min(vals)
        trades = r.get("trades") or ""
        section = section_of(trades)
        div = division_of(trades) or division_of(r.get("title"))
        label = _s(trades) or _s(r.get("title")) or "Bid package"
        d = parse_date(r.get("due")) or date
        bids += _trade_bids(job_key, d, items, low, med, "bid package",
                            _trade_key(section, trades or r.get("title")),
                            label, div)
        award = money(r.get("award_amount"))
        if award is None and any(w for _c, _a, w in items):
            award = next(a for _c, a, w in items if w)
        if award is not None:
            divs[div] = divs.get(div, Z) + award
    return bids, divs


def _dedupe(bids):
    """The same bid in a scope sheet and a bid package of one job counts
    once (same job, division, company and amount)."""
    seen, out = {}, []
    for b in bids:
        k = (b["job"], b["division"], b["company_key"], b["amount"])
        if k in seen:
            o = seen[k]
            if b["awarded"]:
                o["awarded"] = True
            continue
        seen[k] = b
        out.append(b)
    return out


def _new_job(key, **kw):
    j = {"key": key, "name": "", "number": "", "folder": "", "file": "",
         "sources": [], "db_id": None, "type": "", "owner": "", "state": "",
         "estimator": "", "bid_date": None, "sf": None, "bid": None,
         "est_cost": None, "actual_cost": None, "cost": None,
         "cost_basis": "", "result": "Pending", "result_source": "",
         "closed": False, "divisions": {}, "div_basis": "",
         "can_set_result": False}
    j.update(kw)
    return j


def _result(value):
    v = _norm(value)
    for r in RESULTS:
        if v == r.lower():
            return r
    if v in ("awarded", "win"):
        return "Won"
    if v in ("not awarded", "loss"):
        return "Lost"
    if v in ("no-bid", "nobid", "declined", "passed"):
        return "No bid"
    return ""


def _from_db(job, lines, sf_map):
    est, act, cost, basis = _db_job_cost(job, lines)
    res = _result(job.get("result"))
    closed = job.get("status") == "Closed"
    src = "price database" if res else ""
    if not res:
        res, src = ("Won", "closed in Job Cost Feedback") if closed \
            else ("Pending", "")
    return _new_job(
        f"db:{job['id']}", name=_s(job.get("name")) or _s(job.get("number")),
        number=_s(job.get("number")), folder=job.get("folder") or "",
        file=job.get("file") or "", sources=["Job Cost Feedback"],
        db_id=job["id"], type=_s(job.get("type")),
        owner=_s(job.get("client")),
        state=state_of(job.get("region")),
        estimator=_s(job.get("estimator")),
        bid_date=parse_date(job.get("bid_date")),
        sf=quantity(sf_map.get(str(job["id"]))),
        bid=money(job.get("bid_total")), est_cost=est, actual_cost=act,
        cost=cost, cost_basis=basis, result=res, result_source=src,
        closed=closed, can_set_result=True,
        divisions=_db_divisions(lines, basis == "actual cost"),
        div_basis=("job lines (actual)" if basis == "actual cost" else
                   "job lines (estimate)"))


def _apply_project(job, folder, data, warnings):
    """Fill/override a job from a project's settings and records; returns
    the project's sub bids."""
    st = data.get("settings") or {}
    name = _s(data.get("name")) or os.path.basename(folder)
    job["folder"] = folder
    job["sources"] = job["sources"] + ["Project Center"]
    job["can_set_result"] = True
    if not job["name"] or not job["db_id"]:
        job["name"] = name
    for key, field in (("number", "number"), ("building_type", "type"),
                       ("owner", "owner"), ("estimator", "estimator")):
        if _s(st.get(key)):
            job[field] = _s(st.get(key))
    s = state_of(st.get("state"), st.get("location"))
    if s:
        job["state"] = s
    d = parse_date(st.get("bid_date"))
    if d:
        job["bid_date"] = d
    elif st.get("bid_date"):
        warnings.append(f"{name}: bid date {st.get('bid_date')!r} can't be "
                        "read (yyyy-mm-dd)")
    sf = quantity(st.get("building_sf"))
    if sf:
        job["sf"] = sf
    elif _s(st.get("building_sf")):
        warnings.append(f"{name}: building SF {st.get('building_sf')!r} "
                        "can't be read")
    bid = money(st.get("bid_amount"))
    if bid is not None:
        job["bid"] = bid
        if job["cost_basis"] in ("", "bid", "estimate") and \
                job["actual_cost"] is None:
            job["cost"], job["cost_basis"] = bid, "bid"
    elif _s(st.get("bid_amount")):
        warnings.append(f"{name}: our bid {st.get('bid_amount')!r} can't be "
                        "read")
    low = money(st.get(LOW_SETTING))
    if low is not None:
        job["low_bid"] = low
    res = _result(st.get(RESULT_SETTING))
    if res:
        job["result"], job["result_source"] = res, "project settings"
    if job["bid_date"] is None:
        for r in _records(data, "scopesheet"):
            d = parse_date((r.get("header") or {}).get("bid_date"))
            if d:
                job["bid_date"] = d
                break
    sb, sdiv = _scope_bids(job["key"], job["bid_date"],
                           _records(data, "scopesheet"), warnings, name)
    pb, pdiv = _package_bids(job["key"], job["bid_date"],
                             _records(data, "bidpkg"))
    if not job["divisions"]:
        divs = dict(pdiv)
        divs.update(sdiv)             # scope sheets win for a division
        if divs:
            job["divisions"] = {k: cents(v) for k, v in divs.items()}
            job["div_basis"] = "scope sheets / bid packages (award or low)"
    return _dedupe(sb + pb)


def _tab_jobs(rows):
    """Bid tab projects as jobs (for sub/bidder prices only) and the
    bidders' totals per trade."""
    projects, groups = {}, {}
    for r in rows:
        if str(r.get("note") or ""):
            continue                     # INCL lines aren't priced here
        pid = r.get("project")
        if pid not in projects:
            projects[pid] = _new_job(
                f"tab:{pid}", name=_s(r.get("pname")) or f"Bid tab {pid}",
                sources=["Bid tab"], owner=_s(r.get("owner")),
                state=state_of(r.get("state"), r.get("location")),
                bid_date=parse_date(r.get("bid_date")), result="")
        trade = _s(r.get("trade")) or "(no trade)"
        price = D(r.get("price")) if r.get("price") is not None else None
        if price is None:
            continue
        qty = D(r.get("qty")) if r.get("qty") not in (None, "") else \
            Decimal(1)
        g = groups.setdefault((pid, trade), {})
        g[r.get("bidder") or ""] = g.get(r.get("bidder") or "", Z) + \
            qty * price
    bids = []
    for (pid, trade), by in groups.items():
        items = [(b, cents(v), False) for b, v in by.items() if v > 0]
        if not items:
            continue
        vals = [a for _b, a, _w in items]
        bids += _trade_bids(f"tab:{pid}", projects[pid]["bid_date"], items,
                            min(vals), median(vals), "bid tab",
                            "tab:" + _norm(trade), trade, "",
                            award_known=False)
    return list(projects.values()), bids


def project_folders(extra=()):
    """Folders to read: given ones, the dashboard's own list, Project
    Center's recent projects."""
    from . import settings
    out = []
    for f in list(extra or []) + list(settings.get(FOLDERS_SETTING, []) or
                                      []) + list(settings.get("pm_recent",
                                                              []) or []):
        if isinstance(f, str) and f.strip():
            out.append(f)
    return out


def _fkey(f):
    return os.path.normcase(os.path.abspath(f))


def load(folders=None, price_db=True, progress=None):
    """Everything the dashboard shows, unfiltered:
    {"jobs", "tab_jobs", "bids", "index", "skipped": [{folder, reason}],
    "warnings": [...], "projects_read", "loaded"}."""
    warnings, skipped = [], []
    db = read_price_db() if price_db else {"jobs": [], "lines": {},
                                           "sf": {}, "tabs": [], "error": ""}
    if db["error"]:
        warnings.append(db["error"])
    jobs = []
    for j in db["jobs"]:
        try:
            jobs.append(_from_db(j, db["lines"].get(j.get("id"), []),
                                 db["sf"]))
        except Exception as e:                            # noqa: BLE001
            warnings.append(f"Job {j.get('number')!r} skipped ({e})")
    by_folder = {_fkey(j["folder"]): j for j in jobs if j["folder"]}
    by_number = {_norm(j["number"]): j for j in jobs if j["number"]}
    files = [(j, os.path.normcase(os.path.abspath(j["file"])))
             for j in jobs if j["file"]]
    names = list(folders) if folders is not None else project_folders()
    names += [j["folder"] for j in jobs if j["folder"]]
    seen, bids, n_read = set(), [], 0
    for i, f in enumerate(names):
        k = _fkey(f)
        if k in seen:
            continue
        seen.add(k)
        if progress:
            try:
                progress(i, len(names), f)
            except Exception:                             # noqa: BLE001
                pass
        try:
            data = _project_data(f)
        except Skip as e:
            skipped.append({"folder": f, "reason": str(e)})
            continue
        except Exception as e:                            # noqa: BLE001
            skipped.append({"folder": f, "reason": f"unreadable ({e})"})
            continue
        try:
            st = data.get("settings") or {}
            job = by_folder.get(k)
            if job is None and _norm(st.get("number")):
                job = by_number.get(_norm(st.get("number")))
                if job is not None and job["folder"] and \
                        _fkey(job["folder"]) != k:
                    job = None           # that job belongs to another folder
            if job is None:
                prefix = k.rstrip(os.sep) + os.sep
                job = next((j for j, p in files if p.startswith(prefix) and
                            not j["folder"]), None)
            if job is None:
                job = _new_job("pf:" + k)
                jobs.append(job)
            elif "Project Center" in job["sources"]:
                job = _new_job("pf:" + k)     # one job, two folders
                jobs.append(job)
            bids += _apply_project(job, os.path.abspath(f), data, warnings)
            n_read += 1
        except Exception as e:                            # noqa: BLE001
            log.warning("dashboard: project %s skipped", f, exc_info=True)
            skipped.append({"folder": f, "reason": f"unreadable ({e})"})
    try:                     # Nov 4: estimating time from the Time Log
        attach_time(jobs)
    except Exception:                                     # noqa: BLE001
        log.debug("time log not added", exc_info=True)
    tab_jobs, tab_bids = _tab_jobs(db["tabs"])
    index = {j["key"]: j for j in jobs + tab_jobs}
    return {"jobs": jobs, "tab_jobs": tab_jobs, "bids": bids + tab_bids,
            "index": index, "skipped": skipped, "warnings": warnings,
            "projects_read": n_read,
            "loaded": _dt.datetime.now().isoformat(timespec="seconds")}


def attach_time(jobs, data=None):
    """Each job's time from the Time Log (timelog.py): the drawings it
    was logged on that are the job's file or inside its folder. Sets
    j["hours"] = {"takeoff", "review", "total"} (None when none logged).
    Returns how many jobs got time."""
    from . import timelog
    data = timelog.load() if data is None else data
    per = {}
    for r in timelog.rows(data):
        k = os.path.normcase(os.path.abspath(r["job"]))
        t = per.setdefault(k, [0.0, 0.0])
        t[0] += r["takeoff_min"]
        t[1] += r["review_min"]
    n = 0
    for j in jobs:
        take = rev = 0.0
        hit = False
        f = os.path.normcase(os.path.abspath(j["file"])) if j.get("file") \
            else ""
        d = os.path.normcase(os.path.abspath(j["folder"])).rstrip(os.sep) + \
            os.sep if j.get("folder") else ""
        for k, (a, b) in per.items():
            if (f and k == f) or (d and k.startswith(d)):
                take, rev, hit = take + a, rev + b, True
        j["hours"] = {"takeoff": round(take / 60, 2),
                      "review": round(rev / 60, 2),
                      "total": round((take + rev) / 60, 2)} if hit else None
        n += hit
    return n


def bid_cost_per_hour(j):
    """Our bid per estimating hour (how much bid an hour of estimating
    produced), or None."""
    h = (j.get("hours") or {}).get("total")
    if not h or j.get("bid") is None:
        return None
    return cents(D(j["bid"]) / D(h))


# ============================================================ filters
def filter_options(data):
    def opts(field, rows):
        seen = {}
        for j in rows:
            v = j.get(field) or ""
            if v and _norm(v) not in seen:
                seen[_norm(v)] = v
        return sorted(seen.values(), key=str.lower)
    js = data["jobs"]
    return {"type": opts("type", js),
            "state": opts("state", js + data["tab_jobs"]),
            "estimator": opts("estimator", js)}


def _match(job, f):
    if not f:
        return True
    lo = parse_date(f.get("date_from"))
    hi = parse_date(f.get("date_to"), end=True)
    if lo or hi:
        d = job.get("bid_date")
        if d is None or (lo and d < lo) or (hi and d > hi):
            return False
    for field in ("type", "state", "estimator"):
        want = _norm(f.get(field))
        if want and _norm(job.get(field)) != want:
            return False
    return True


def filter_jobs(jobs, filters=None):
    return [j for j in jobs if _match(j, filters)]


# ============================================================ cost per SF
def _band(v, bands):
    for i, (top, label) in enumerate(bands):
        if top is None or v < top:
            return f"{i}", label
    return f"{len(bands)}", bands[-1][1]


def _gkey(job, by):
    if by == "size":
        b = job.get("bid")
        return _band(float(b), SIZE_BANDS) if b is not None else \
            ("", NO_GROUP[by])
    if by == "markup":
        b, e = job.get("bid"), job.get("est_cost")
        if b is None or not e:
            return "", NO_GROUP[by]
        return _band(float((b - e) / e * 100), MARKUP_BANDS)
    if by == "month":
        d = job.get("bid_date")
        return (f"{d:%Y-%m}", f"{d:%Y-%m}") if d else ("", NO_GROUP[by])
    v = _s(job.get(by))
    return (_norm(v), v) if v else ("", NO_GROUP.get(by, "(none)"))


def per_sf(amount, sf):
    if amount is None or not sf:
        return None
    return cents(D(amount) / D(sf))


def _sf_group(key, label, items):
    """items: [(job, $/SF)] -> a cost-per-SF row with flags per job."""
    st = stats([v for _j, v in items])
    detail = []
    for j, v in sorted(items, key=lambda x: (x[0]["bid_date"] or
                                             _dt.date.min, x[0]["name"])):
        detail.append({"job": j["key"], "name": j["name"],
                       "date": j["bid_date"], "value": v,
                       "flag": outlier(v, st),
                       "vs_median": pct(v - st["median"], st["median"])})
    return {"group": key, "label": label, "n": st["n"],
            "median": cents(st["median"]) if st["median"] is not None
            else None,
            "low": st["low"], "high": st["high"],
            "q1": cents(st["q1"]) if st["q1"] is not None else None,
            "q3": cents(st["q3"]) if st["q3"] is not None else None,
            "trend": trend_per_year([(d["date"], d["value"])
                                     for d in detail]),
            "outliers": sum(1 for d in detail if d["flag"]),
            "jobs": [d["job"] for d in detail], "detail": detail}


def cost_per_sf(jobs, by="type", total=True):
    """$/SF of each job (its cost / building SF) grouped by building type
    (or owner, estimator, month); the first row is all jobs together."""
    groups = {}
    for j in jobs:
        v = per_sf(j.get("cost"), j.get("sf"))
        if v is None:
            continue
        k, label = _gkey(j, by)
        g = groups.setdefault(k, [label, []])
        g[1].append((j, v))
    rows = [_sf_group(k, g[0], g[1]) for k, g in groups.items()]
    rows.sort(key=lambda r: (r["group"] == "", r["label"].lower()))
    if total and rows:
        allv = [x for g in groups.values() for x in g[1]]
        rows.insert(0, _sf_group("*", "All jobs", allv))
    return rows


def cost_per_sf_division(jobs):
    """$/SF by CSI division: each job's division amount / its SF."""
    groups = {}
    for j in jobs:
        if not j.get("sf"):
            continue
        for div, amt in (j.get("divisions") or {}).items():
            v = per_sf(amt, j["sf"])
            if v is None:
                continue
            groups.setdefault(div, []).append((j, v))
    rows = [dict(_sf_group(d, division_label(d), items), division=d)
            for d, items in groups.items()]
    rows.sort(key=lambda r: (r["group"] == "", r["group"]))
    return rows


# ============================================================ hit rate
def _hit_row(key, label, js):
    c = {r: 0 for r in RESULTS}
    amt = {r: Z for r in RESULTS}
    for j in js:
        r = j.get("result") or "Pending"
        c[r] = c.get(r, 0) + 1
        if j.get("bid") is not None:
            amt[r] = amt.get(r, Z) + j["bid"]
    decided = c["Won"] + c["Lost"]
    dec_amt = amt["Won"] + amt["Lost"]
    return {"group": key, "label": label, "won": c["Won"],
            "lost": c["Lost"], "pending": c["Pending"],
            "no_bid": c["No bid"], "decided": decided,
            "rate": pct(c["Won"], decided),
            "won_amount": amt["Won"], "decided_amount": dec_amt,
            "dollar_rate": pct(amt["Won"], dec_amt),
            "jobs": [j["key"] for j in js]}


def hit_rate(jobs, by="type", total=True):
    groups = {}
    for j in jobs:
        k, label = _gkey(j, by)
        groups.setdefault(k, [label, []])[1].append(j)
    rows = [_hit_row(k, g[0], g[1]) for k, g in groups.items()]
    if by in ("month", "size", "markup"):
        rows.sort(key=lambda r: (r["group"] == "", r["group"]))
    else:
        rows.sort(key=lambda r: (r["group"] == "", r["label"].lower()))
    if total and rows:
        rows.append(_hit_row("*", "All jobs", list(jobs)))
    return rows


# ============================================================ bid results
def bid_results(jobs):
    """Nov 3 bid results: per job our number, the low number and the gap
    ($ and % over the low)."""
    out = []
    for j in jobs:
        bid, low = j.get("bid"), j.get("low_bid")
        gap = bid - low if bid is not None and low is not None else None
        out.append({"job": j["key"], "name": j["name"],
                    "date": j.get("bid_date"), "owner": j.get("owner", ""),
                    "result": j.get("result") or "", "bid": bid,
                    "low": low, "gap": gap,
                    "gap_pct": pct(gap, low) if gap is not None and low
                    else None,
                    "hours": (j.get("hours") or {}).get("total"),
                    "bid_per_hour": bid_cost_per_hour(j)})
    return out


def set_low_bid(job, amount):
    """Save the low bidder's number with the job's project settings."""
    folder = job.get("folder") or ""
    if not folder or "Project Center" not in job.get("sources", ()):
        raise DashboardError("This job has no project to save the low bid "
                             "in.")
    v = money(amount)
    if v is None:
        raise DashboardError(f"{amount!r} isn't an amount.")
    from .pm.store import open_store
    st = open_store(folder)
    if getattr(st, "damaged", ""):
        raise DashboardError(f"The project in {folder} is damaged.")
    st.set_setting(LOW_SETTING, str(v))
    st.flush(force=True)
    job["low_bid"] = v
    return v


# ============================================================ margin
def job_margin(j):
    bid, est, act = j.get("bid"), j.get("est_cost"), j.get("actual_cost")
    markup = bid - est if bid is not None and est is not None else None
    return {"job": j["key"], "name": j["name"], "date": j["bid_date"],
            "result": j.get("result") or "", "bid": bid, "est_cost": est,
            "markup": markup, "margin_pct": pct(markup, bid)
            if bid else None,
            "actual_cost": act,
            "actual_vs_est": act - est if act is not None and
            est is not None else None,
            "actual_vs_est_pct": pct(act - est, est)
            if act is not None and est else None,
            "actual_margin_pct": pct(bid - act, bid)
            if act is not None and bid else None,
            "partial": act is not None and not j.get("closed")}


def margin(jobs, by="type", total=True):
    """Bid vs estimate cost (markup and margin % of the bid) over jobs
    with both; actual vs estimate over jobs with actual costs."""
    groups = {}
    for j in jobs:
        k, label = _gkey(j, by)
        groups.setdefault(k, [label, []])[1].append(j)

    def row(key, label, js):
        both = [j for j in js if j.get("bid") is not None and
                j.get("est_cost") is not None]
        acts = [j for j in js if j.get("actual_cost") is not None and
                j.get("est_cost") is not None]
        bid = sum((j["bid"] for j in both), Z)
        est = sum((j["est_cost"] for j in both), Z)
        a_est = sum((j["est_cost"] for j in acts), Z)
        a_act = sum((j["actual_cost"] for j in acts), Z)
        return {"group": key, "label": label, "n": len(both),
                "bid": bid, "est_cost": est, "markup": bid - est,
                "margin_pct": pct(bid - est, bid) if both else None,
                "n_actual": len(acts), "act_est": a_est, "actual": a_act,
                "actual_vs_est": a_act - a_est,
                "actual_vs_est_pct": pct(a_act - a_est, a_est)
                if acts else None,
                "jobs": [j["key"] for j in js if any(
                    j is x for x in both) or any(j is x for x in acts)]}
    rows = [row(k, g[0], g[1]) for k, g in groups.items()]
    rows = [r for r in rows if r["n"] or r["n_actual"]]
    rows.sort(key=lambda r: (r["group"] == "", r["label"].lower()))
    if total and rows:
        rows.append(row("*", "All jobs", list(jobs)))
    return rows


# ============================================================ subs
def trades(bids):
    """[(trade key, label, bids)] sorted by label."""
    out = {}
    for b in bids:
        if not b["trade_key"]:
            continue
        e = out.setdefault(b["trade_key"], [b["trade"], 0])
        e[1] += 1
    return sorted(((k, v[0], v[1]) for k, v in out.items()),
                  key=lambda x: x[1].lower())


def sub_summary(bids, trade_key=None):
    """Per trade and sub: bids, how often low, how often awarded, the
    median of their bids' % against each job's median, latest amount and
    their bids over time."""
    groups = {}
    for b in bids:
        if not b["trade_key"] or (trade_key and b["trade_key"] != trade_key):
            continue
        groups.setdefault((b["trade_key"], b["company_key"]), []).append(b)
    rows = []
    for (tk, _ck), bs in groups.items():
        bs.sort(key=lambda b: (b["date"] or _dt.date.min, b["job"]))
        known = [b for b in bs if b["awarded"] is not None]
        pcts = [b["pct"] for b in bs if b["pct"] is not None]
        md = median(pcts)
        rows.append({"trade_key": tk, "trade": bs[0]["trade"],
                     "company": bs[-1]["company"],
                     "company_key": bs[0]["company_key"],
                     "bids": len(bs), "low": sum(1 for b in bs if b["low"]),
                     "awarded": sum(1 for b in known if b["awarded"]),
                     "award_known": len(known),
                     "median_pct": md.quantize(TENTH, rounding=ROUND_HALF_UP)
                     if md is not None else None,
                     "latest": bs[-1]["amount"],
                     "first": bs[0]["date"], "last": bs[-1]["date"],
                     "sources": sorted({b["source"] for b in bs}),
                     "history": bs, "jobs": sorted({b["job"] for b in bs})})
    rows.sort(key=lambda r: (r["trade"].lower(),
                             r["median_pct"] if r["median_pct"] is not None
                             else Decimal(10 ** 9), r["company"].lower()))
    return rows


# ============================================================ report
def build(data, filters=None):
    """The filtered dashboard: every table, ready for the window and the
    exports."""
    jobs = filter_jobs(data["jobs"], filters)
    tabs = filter_jobs(data["tab_jobs"], filters)
    keys = {j["key"] for j in jobs} | {j["key"] for j in tabs}
    bids = [b for b in data["bids"] if b["job"] in keys]
    return {"filters": dict(filters or {}), "jobs": jobs,
            "index": data["index"],
            "by_type": cost_per_sf(jobs, "type"),
            "by_division": cost_per_sf_division(jobs),
            "hit": {by: hit_rate(jobs, by) for by in HIT_BY},
            "margin": margin(jobs, "type"),
            "job_margins": [job_margin(j) for j in jobs],
            "bids": bids, "subs": sub_summary(bids),
            "trades": trades(bids),
            "skipped": list(data["skipped"]),
            "warnings": list(data["warnings"]),
            "loaded": data.get("loaded", ""),
            "empty": not data["jobs"] and not data["bids"]}


def jobs_for(report, keys):
    """The jobs behind a number, in bid-date order."""
    idx = report["index"]
    js = [idx[k] for k in dict.fromkeys(keys) if k in idx]
    js.sort(key=lambda j: (j["bid_date"] or _dt.date.min, j["name"]))
    return js


def filters_text(f):
    f = f or {}
    parts = []
    if f.get("date_from") or f.get("date_to"):
        parts.append(f"bid date {f.get('date_from') or 'any'} to "
                     f"{f.get('date_to') or 'any'}")
    for k, label in (("type", "building type"), ("state", "state"),
                     ("estimator", "estimator")):
        if _s(f.get(k)):
            parts.append(f"{label} {_s(f.get(k))}")
    return "; ".join(parts) or "all jobs"


# ============================================================ bid result
def set_result(job, result):
    """Record our bid result for a job: in the project's settings (when
    it has a project folder) and the price database job (when it has
    one). Returns where it was saved."""
    result = _result(result) if result else ""
    if result == "" and job.get("result_source") not in (
            "project settings", "price database"):
        return []
    saved = []
    # the project store first (review N9): a damaged project stops here,
    # before the price database is changed, so the two never disagree
    folder = job.get("folder") or ""
    st = None
    if folder and "Project Center" in job.get("sources", ()):
        from .pm.store import open_store
        st = open_store(folder)
        if getattr(st, "damaged", ""):
            raise DashboardError(f"The project in {folder} is damaged; its "
                                 "result can't be saved there.")
        before = st.setting(RESULT_SETTING)
        st.set_setting(RESULT_SETTING, result)
        st.flush(force=True)
    if job.get("db_id") is not None:
        from . import pricedb
        try:
            with pricedb.connect(write=True) as con:
                con.execute("UPDATE jobs SET result=? WHERE id=?",
                            (result, job["db_id"]))
        except Exception:
            if st is not None:          # put the project back as it was
                try:
                    st.set_setting(RESULT_SETTING, before)
                    st.flush(force=True)
                except Exception:
                    log.warning("could not undo the project result",
                                exc_info=True)
            raise
        saved.append("price database")
    if st is not None:
        saved.append("project settings")
    if not saved:
        raise DashboardError("This job has no project or Job Cost Feedback "
                             "record to save a result in.")
    job["result"] = result or ("Won" if job.get("closed") else "Pending")
    job["result_source"] = saved[-1] if result else ""
    return saved


def add_folders(folders):
    from . import settings
    have = list(settings.get(FOLDERS_SETTING, []) or [])
    keys = {_fkey(f) for f in have}
    for f in folders:
        if f and _fkey(f) not in keys:
            have.append(os.path.abspath(f))
            keys.add(_fkey(f))
    settings.set(FOLDERS_SETTING, have)
    return have


# ============================================================ Excel
def _fmt_date(d):
    return d.isoformat() if d else ""


def _refs(sheet, col, rows):
    """'Jobs'!L2:L4,'Jobs'!L7 for a set of rows (runs merged)."""
    rows = sorted(set(rows))
    runs, start, prev = [], None, None
    for r in rows:
        if start is None:
            start = prev = r
        elif r == prev + 1:
            prev = r
        else:
            runs.append((start, prev))
            start = prev = r
    if start is not None:
        runs.append((start, prev))
    q = f"'{sheet}'!"
    return [f"{q}{col}{a}" if a == b else f"{q}{col}{a}:{col}{b}"
            for a, b in runs]


def _fn(name, refs, fallback, wrap=None):
    """=NAME(refs) when it fits Excel's 255 arguments, else the value."""
    if not refs or len(refs) > 250:
        return fallback
    inner = f"{name}({','.join(refs)})"
    return "=" + (wrap.format(inner) if wrap else inner)


def export_xlsx(report, path, title="Estimating Dashboard"):
    """The dashboard as a workbook: data sheets (Jobs, Division Lines, Sub
    Bids) and summary sheets whose medians, ranges, totals and rates are
    Excel formulas over the data rows. Returns the path."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    MONEY = '"$"#,##0.00_);("$"#,##0.00)'
    PCT1 = '0.0"%"'
    bold = Font(bold=True)
    head_fill = PatternFill("solid", fgColor="FFDCE6F2")
    flag_fill = PatternFill("solid", fgColor="FFFFE0B2")
    wb = Workbook()

    def put(ws, row, live=()):
        """Append a row. Only the positions in `live` hold the program's
        own formulas; any other text that starts like a formula (a
        project's owner, a sub's company from a proposal...) is stored as
        text, never run (0.13.5 security fix)."""
        live = set(live)
        return safecell.append_row(ws, [
            safecell.Formula(v) if i in live and isinstance(v, str) and
            v.startswith("=") else v for i, v in enumerate(row)])

    def sheet(name, heads, widths=None, first=False):
        ws = wb.active if first else wb.create_sheet()
        ws.title = name
        if heads:
            put(ws, heads)
            for c in ws[1]:
                c.font = bold
                c.fill = head_fill
                c.alignment = Alignment(wrap_text=True, vertical="top")
            ws.freeze_panes = "A2"
        for i, w in enumerate(widths or [], 1):
            ws.column_dimensions[get_column_letter(i)].width = w
        return ws

    def fmt(ws, row, cols, number_format):
        for c in cols:
            ws[f"{c}{row}"].number_format = number_format

    # ---- summary
    ws = sheet("Summary", None, [34, 70], first=True)
    put(ws, [title])
    ws["A1"].font = Font(bold=True, size=14)
    put(ws, ["Filters", filters_text(report["filters"])])
    put(ws, ["Read", report.get("loaded", "")])
    put(ws, ["Jobs", len(report["jobs"])])
    put(ws, ["Sub bids", len(report["bids"])])
    put(ws, [])
    put(ws, ["How it's figured"])
    ws[f"A{ws.max_row}"].font = bold
    for k, v in (
            ("$/SF", "a job's cost / its building SF; cost is the actual "
             "cost when Job Cost Feedback has it, else the contract, else "
             "our bid, else the estimate lines"),
            ("Outlier", f"below Q1 - 1.5 IQR or above Q3 + 1.5 IQR "
             f"(groups of {MIN_OUTLIER_N} or more)"),
            ("Trend", "least-squares slope of $/SF against bid date, per "
             "year"),
            ("Hit rate", "won / (won + lost); pending and no-bid jobs are "
             "not in the rate"),
            ("Margin %", "(our bid - estimate cost) / our bid"),
            ("Sub % vs median", "a sub's bid against the median of all "
             "bids for that trade on that job")):
        put(ws, [k, v])
    if report["skipped"]:
        put(ws, [])
        put(ws, ["Projects skipped"])
        ws[f"A{ws.max_row}"].font = bold
        for s in report["skipped"]:
            put(ws, [s["folder"], s["reason"]])
    if report["warnings"]:
        put(ws, [])
        put(ws, ["Notes"])
        ws[f"A{ws.max_row}"].font = bold
        for w in report["warnings"]:
            put(ws, ["", w])

    # ---- jobs (data)
    jobs = sorted(report["jobs"], key=lambda j: (_norm(j["type"]) or "~",
                                                 j["bid_date"] or
                                                 _dt.date.min, j["name"]))
    js = sheet("Jobs", ["Job", "Number", "Building type", "Owner", "State",
                        "Estimator", "Bid date", "Result", "Building SF",
                        "Cost", "Cost basis", "$/SF", "Our bid",
                        "Estimate cost", "Markup", "Margin %",
                        "Actual cost", "Actual - estimate", "Source"],
               [30, 12, 18, 20, 7, 16, 11, 9, 12, 15, 13, 10, 15, 15, 14,
                10, 15, 15, 26])
    row_of = {}
    for j in jobs:
        r = js.max_row + 1
        row_of[j["key"]] = r
        put(js, [j["name"], j["number"], j["type"], j["owner"],
                   j["state"], j["estimator"], _fmt_date(j["bid_date"]),
                   j["result"], j["sf"], j["cost"], j["cost_basis"],
                   f'=IF(AND(ISNUMBER(I{r}),ISNUMBER(J{r})),'
                   f'IF(I{r}>0,ROUND(J{r}/I{r},2),""),"")',
                   j["bid"], j["est_cost"],
                   f'=IF(AND(ISNUMBER(M{r}),ISNUMBER(N{r})),M{r}-N{r},"")',
                   f'=IF(AND(ISNUMBER(O{r}),ISNUMBER(M{r})),'
                   f'IF(M{r}<>0,ROUND(O{r}/M{r}*100,1),""),"")',
                   j["actual_cost"],
                   f'=IF(AND(ISNUMBER(Q{r}),ISNUMBER(N{r})),Q{r}-N{r},"")',
                   ", ".join(j["sources"])], live=(11, 14, 15, 17))
        fmt(js, r, "JLMNOQR", MONEY)
        js[f"P{r}"].number_format = PCT1
        js[f"I{r}"].number_format = "#,##0.00"
    if jobs:
        last = js.max_row
        put(js, ["Total"] + [""] * 8 + [f"=SUM(J2:J{last})", "", ""] +
            [f"=SUM({c}2:{c}{last})" for c in "MN"] +
            [f"=SUM(O2:O{last})", "", f"=SUM(Q2:Q{last})",
             f"=SUM(R2:R{last})"], live=range(1, 19))
        t = js.max_row
        js[f"A{t}"].font = bold
        fmt(js, t, "JMNOQR", MONEY)

    # ---- cost per SF by type (formulas over Jobs!L)
    cs = sheet("Cost per SF", ["Building type", "Jobs", "Median $/SF",
                               "Low $/SF", "High $/SF", "Q1", "Q3",
                               "Trend $/SF per year", "Outliers"],
               [26, 8, 13, 12, 12, 11, 11, 15, 30])
    for g in report["by_type"]:
        rows = [row_of[k] for k in g["jobs"] if k in row_of]
        refs = _refs("Jobs", "L", rows)
        flags = ", ".join(f"{d['name']} ({d['flag']})" for d in g["detail"]
                          if d["flag"])
        put(cs, [g["label"], _fn("COUNT", refs, g["n"]),
                 _fn("MEDIAN", refs, g["median"], "ROUND({},2)"),
                 _fn("MIN", refs, g["low"]), _fn("MAX", refs, g["high"]),
                 g["q1"], g["q3"], g["trend"], flags], live=(1, 2, 3, 4))
        r = cs.max_row
        fmt(cs, r, "CDEFGH", MONEY)
        if flags:
            cs[f"I{r}"].fill = flag_fill
        if g["group"] == "*":
            cs[f"A{r}"].font = bold

    # ---- divisions
    dl = sheet("Division Lines", ["Division", "Job", "Bid date",
                                  "Division cost", "Building SF", "$/SF",
                                  "Basis", "Flag"],
               [30, 30, 11, 15, 12, 10, 34, 8])
    div_rows = {}
    for g in report["by_division"]:
        for d in g["detail"]:
            j = report["index"][d["job"]]
            r = dl.max_row + 1
            div_rows.setdefault(g["group"], []).append(r)
            put(dl, [g["label"], j["name"], _fmt_date(j["bid_date"]),
                     j["divisions"].get(g["group"]), j["sf"],
                     f'=IF(E{r}>0,ROUND(D{r}/E{r},2),"")', j["div_basis"],
                     d["flag"]], live=(5,))
            fmt(dl, r, "DF", MONEY)
            dl[f"E{r}"].number_format = "#,##0.00"
    dv = sheet("By Division", ["CSI division", "Jobs", "Median $/SF",
                               "Low $/SF", "High $/SF", "Q1", "Q3",
                               "Trend $/SF per year", "Outliers"],
               [34, 8, 13, 12, 12, 11, 11, 15, 30])
    for g in report["by_division"]:
        refs = _refs("Division Lines", "F", div_rows.get(g["group"], []))
        flags = ", ".join(f"{d['name']} ({d['flag']})" for d in g["detail"]
                          if d["flag"])
        put(dv, [g["label"], _fn("COUNT", refs, g["n"]),
                 _fn("MEDIAN", refs, g["median"], "ROUND({},2)"),
                 _fn("MIN", refs, g["low"]), _fn("MAX", refs, g["high"]),
                 g["q1"], g["q3"], g["trend"], flags], live=(1, 2, 3, 4))
        r = dv.max_row
        fmt(dv, r, "CDEFGH", MONEY)
        if flags:
            dv[f"I{r}"].fill = flag_fill

    # ---- hit rate
    hs = sheet("Hit Rate", None, [26, 8, 8, 9, 8, 10, 15, 15, 12])
    for by in HIT_BY:
        put(hs, [BY_LABEL[by], "Won", "Lost", "Pending", "No bid",
                 "Hit rate", "Won $", "Decided $", "$ hit rate"])
        for c in hs[hs.max_row]:
            c.font = bold
            c.fill = head_fill
        first = hs.max_row + 1
        for g in report["hit"][by]:
            if g["group"] == "*":
                continue
            r = hs.max_row + 1
            put(hs, [g["label"], g["won"], g["lost"], g["pending"],
                     g["no_bid"],
                     f'=IF(B{r}+C{r}>0,ROUND(B{r}/(B{r}+C{r})*100,1),"")',
                     g["won_amount"], g["decided_amount"],
                     f'=IF(H{r}>0,ROUND(G{r}/H{r}*100,1),"")'], live=(5, 8))
            fmt(hs, r, "GH", MONEY)
            fmt(hs, r, "FI", PCT1)
        last = hs.max_row
        if last >= first:
            r = last + 1
            put(hs, ["All jobs"] + [f"=SUM({c}{first}:{c}{last})"
                                    for c in "BCDE"] +
                [f'=IF(B{r}+C{r}>0,ROUND(B{r}/(B{r}+C{r})*100,1),"")',
                 f"=SUM(G{first}:G{last})", f"=SUM(H{first}:H{last})",
                 f'=IF(H{r}>0,ROUND(G{r}/H{r}*100,1),"")'],
                live=range(1, 9))
            hs[f"A{r}"].font = bold
            fmt(hs, r, "GH", MONEY)
            fmt(hs, r, "FI", PCT1)
        put(hs, [])

    # ---- margin (formulas over Jobs!M/N/Q)
    ms = sheet("Margin", ["Building type", "Jobs (bid + estimate)",
                          "Our bids", "Estimate cost", "Markup",
                          "Margin %", "Jobs with actuals",
                          "Estimate (those jobs)", "Actual cost",
                          "Actual - estimate", "Actual vs estimate %"],
               [26, 10, 15, 15, 14, 10, 10, 15, 15, 15, 12])
    idx = report["index"]
    for g in report["margin"]:
        js_ = [idx[k] for k in g["jobs"] if k in idx]
        both = [row_of[j["key"]] for j in js_ if j["bid"] is not None and
                j["est_cost"] is not None and j["key"] in row_of]
        acts = [row_of[j["key"]] for j in js_ if j["actual_cost"] is not
                None and j["est_cost"] is not None and j["key"] in row_of]
        r = ms.max_row + 1
        put(ms, [g["label"], g["n"],
                   _fn("SUM", _refs("Jobs", "M", both), g["bid"]),
                   _fn("SUM", _refs("Jobs", "N", both), g["est_cost"]),
                   f"=C{r}-D{r}",
                   f'=IF(C{r}<>0,ROUND((C{r}-D{r})/C{r}*100,1),"")',
                   g["n_actual"],
                   _fn("SUM", _refs("Jobs", "N", acts), g["act_est"]),
                   _fn("SUM", _refs("Jobs", "Q", acts), g["actual"]),
                   f"=I{r}-H{r}",
                   f'=IF(H{r}<>0,ROUND((I{r}-H{r})/H{r}*100,1),"")'],
            live=(2, 3, 4, 5, 7, 8, 9, 10))
        fmt(ms, r, "CDEHIJ", MONEY)
        fmt(ms, r, "FK", PCT1)
        if g["group"] == "*":
            ms[f"A{r}"].font = bold

    # ---- subs
    sb = sheet("Sub Bids", ["Trade", "Company", "Job", "Bid date",
                            "Bid", "Job median", "% vs median", "Low",
                            "Awarded", "Source"],
               [30, 28, 28, 11, 15, 15, 11, 6, 9, 13])
    bid_rows = {}
    for s in report["subs"]:
        for b in s["history"]:
            r = sb.max_row + 1
            bid_rows.setdefault((s["trade_key"], s["company_key"]),
                                []).append(r)
            put(sb, [s["trade"], b["company"],
                       idx[b["job"]]["name"] if b["job"] in idx else "",
                       _fmt_date(b["date"]), b["amount"], b["median"],
                       f'=IF(F{r}<>0,ROUND((E{r}-F{r})/F{r}*100,1),"")',
                       "yes" if b["low"] else "",
                       "" if b["awarded"] is None else
                       ("yes" if b["awarded"] else "no"), b["source"]],
                live=(6,))
            fmt(sb, r, "EF", MONEY)
            sb[f"G{r}"].number_format = PCT1
    ss_ = sheet("Sub Summary", ["Trade", "Company", "Bids", "Times low",
                                "Times awarded", "Median % vs job median",
                                "Latest bid", "First", "Last"],
                [30, 28, 7, 9, 10, 12, 15, 11, 11])
    for s in report["subs"]:
        rows = bid_rows.get((s["trade_key"], s["company_key"]), [])
        h_refs = _refs("Sub Bids", "H", rows)
        i_refs = _refs("Sub Bids", "I", rows)
        # COUNTIF takes one range: the sub's rows are written together
        put(ss_, [s["trade"], s["company"],
                    _fn("COUNT", _refs("Sub Bids", "E", rows), s["bids"]),
                    f'=COUNTIF({h_refs[0]},"yes")' if len(h_refs) == 1
                    else s["low"],
                    (f'=COUNTIF({i_refs[0]},"yes")' if len(i_refs) == 1
                     else s["awarded"]) if s["award_known"] else "",
                    _fn("MEDIAN", _refs("Sub Bids", "G", rows),
                        s["median_pct"], "ROUND({},1)"),
                    s["latest"], _fmt_date(s["first"]),
                    _fmt_date(s["last"])], live=(2, 3, 4, 5))
        r = ss_.max_row
        ss_[f"G{r}"].number_format = MONEY
        ss_[f"F{r}"].number_format = PCT1
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".",
                exist_ok=True)
    wb.save(path)
    return path


# ============================================================ PDF
def _m(v):
    if v is None:
        return ""
    c = cents(v)
    return f"-${abs(c):,.2f}" if c < 0 else f"${c:,.2f}"


def _p(v):
    return "" if v is None else f"{v}%"


def pdf_tables(report):
    """[(title, heads, rows, widths)] - the tables the PDF prints."""
    t = []
    t.append(("Cost per SF by building type",
              ["Building type", "Jobs", "Median", "Low", "High",
               "Trend / yr", "Outliers"],
              [[g["label"], g["n"], _m(g["median"]), _m(g["low"]),
                _m(g["high"]), _m(g["trend"]),
                ", ".join(f"{d['name']} ({d['flag']})" for d in g["detail"]
                          if d["flag"])] for g in report["by_type"]],
              [150, 40, 70, 70, 70, 70, 250]))
    t.append(("Cost per SF by CSI division",
              ["Division", "Jobs", "Median", "Low", "High", "Trend / yr",
               "Outliers"],
              [[g["label"], g["n"], _m(g["median"]), _m(g["low"]),
                _m(g["high"]), _m(g["trend"]),
                ", ".join(f"{d['name']} ({d['flag']})" for d in g["detail"]
                          if d["flag"])] for g in report["by_division"]],
              [150, 40, 70, 70, 70, 70, 250]))
    for by in HIT_BY:
        t.append((f"Hit rate by {BY_LABEL[by].lower()}",
                  [BY_LABEL[by], "Won", "Lost", "Pending", "No bid",
                   "Hit rate", "Won $", "Decided $", "$ hit rate"],
                  [[g["label"], g["won"], g["lost"], g["pending"],
                    g["no_bid"], _p(g["rate"]), _m(g["won_amount"]),
                    _m(g["decided_amount"]), _p(g["dollar_rate"])]
                   for g in report["hit"][by]],
                  [170, 40, 40, 50, 45, 60, 100, 100, 70]))
    t.append(("Margin by building type",
              ["Building type", "Jobs", "Our bids", "Estimate", "Markup",
               "Margin %", "w/ actuals", "Actual", "Actual - est."],
              [[g["label"], g["n"], _m(g["bid"]), _m(g["est_cost"]),
                _m(g["markup"]), _p(g["margin_pct"]), g["n_actual"],
                _m(g["actual"]), _m(g["actual_vs_est"])]
               for g in report["margin"]],
              [150, 40, 95, 95, 90, 60, 60, 95, 90]))
    t.append(("Subcontractor prices",
              ["Trade", "Company", "Bids", "Low", "Awarded",
               "Median vs job", "Latest bid", "Last"],
              [[s["trade"], s["company"], s["bids"], s["low"],
                s["awarded"] if s["award_known"] else "",
                _p(s["median_pct"]), _m(s["latest"]),
                _fmt_date(s["last"])] for s in report["subs"]],
              [190, 180, 40, 40, 50, 80, 90, 70]))
    return t


def export_pdf(report, path, title="Estimating Dashboard"):
    """Landscape letter pages: the summary, a bar chart of median $/SF by
    building type (low-high range), then every table. Returns the path."""
    import fitz
    W, H, M = 792, 612, 36
    out = fitz.open()
    state = {"page": None, "y": 0}

    def new_page():
        pg = out.new_page(width=W, height=H)
        pg.insert_text((M, M + 4), title, fontsize=14, fontname="hebo")
        pg.insert_text((M, M + 20), filters_text(report["filters"]) +
                       (f"  -  read {report.get('loaded', '')}"
                        if report.get("loaded") else ""),
                       fontsize=8, fontname="helv")
        state["page"], state["y"] = pg, M + 44
        return pg

    def need(h):
        if state["page"] is None or state["y"] + h > H - M:
            new_page()
        return state["page"]

    def fit(s, width, size, font="helv"):
        s = str(s if s is not None else "")
        while s and fitz.get_text_length(s, fontname=font,
                                         fontsize=size) > width - 4:
            s = s[:-2] + "..." if len(s) > 2 else ""
        return s

    new_page()
    pg = state["page"]
    y = state["y"]
    pg.insert_text((M, y), f"{len(report['jobs'])} job(s), "
                   f"{len(report['bids'])} sub bid(s)", fontsize=9)
    y += 14
    if report.get("empty"):
        for line in _wrap(EMPTY_HINT.replace("…", "..."), 130):
            pg.insert_text((M, y), line, fontsize=9)
            y += 12
    rows = [g for g in report["by_type"] if g["median"] is not None]
    if rows:
        y += 6
        pg.insert_text((M, y), "Median $/SF by building type (line = low "
                       "to high)", fontsize=10, fontname="hebo")
        y += 8
        top = max(D(g["high"]) for g in rows) or Decimal(1)
        bh = 14
        for g in rows[:14]:
            pg.insert_text((M, y + 10), fit(g["label"], 150, 8), fontsize=8)
            x0, span = M + 155, W - 2 * M - 260
            w = float(D(g["median"]) / top) * span
            pg.draw_rect(fitz.Rect(x0, y + 2, x0 + max(w, 1), y + bh - 2),
                         color=None, fill=(0.15, 0.39, 0.92))
            lo = x0 + float(D(g["low"]) / top) * span
            hi = x0 + float(D(g["high"]) / top) * span
            mid = y + bh / 2
            pg.draw_line(fitz.Point(lo, mid), fitz.Point(hi, mid),
                         color=(0.1, 0.1, 0.1), width=1)
            pg.insert_text((x0 + span + 8, y + 10),
                           f"{_m(g['median'])}  ({_m(g['low'])} - "
                           f"{_m(g['high'])}, {g['n']} job(s))", fontsize=8)
            y += bh
    if report["skipped"]:
        y += 10
        pg.insert_text((M, y), "Projects skipped", fontsize=10,
                       fontname="hebo")
        y += 12
        for s in report["skipped"][:20]:
            pg.insert_text((M, y), fit(f"{s['folder']}: {s['reason']}",
                                       W - 2 * M, 8), fontsize=8)
            y += 11
    state["y"] = y + 14
    for name, heads, rows, widths in pdf_tables(report):
        if not rows:
            continue
        pg = need(40)
        pg.insert_text((M, state["y"]), name, fontsize=11, fontname="hebo")
        state["y"] += 14

        def head_row():
            p = state["page"]
            x = M
            for h, w in zip(heads, widths):
                p.insert_text((x, state["y"]), fit(h, w, 8, "hebo"),
                              fontsize=8, fontname="hebo")
                x += w
            state["y"] += 12
        head_row()
        for r in rows:
            if state["y"] + 11 > H - M:
                new_page()
                head_row()
            p = state["page"]
            x = M
            for v, w in zip(r, widths):
                p.insert_text((x, state["y"]), fit(v, w, 8), fontsize=8)
                x += w
            state["y"] += 11
        state["y"] += 14
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".",
                exist_ok=True)
    out.save(path)
    out.close()
    return path


def _wrap(text, n):
    words, lines, cur = str(text).split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > n and cur:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    return lines
