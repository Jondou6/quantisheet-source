"""Bid vs actual: what jobs really cost, fed back into the cost book.

A job is registered from a locked bid (its estimate, line by line), its
actual costs come from the Project Center (direct costs by cost code, with
the quantity installed) or a job-cost CSV from accounting, and closing the
job records each line's actual unit cost as an observation. For any cost
code, suggest() gives a recency- and quantity-weighted median of those
observations (escalated to today) next to the book's price. Nothing changes
in a cost book until you accept a suggestion with apply(), which goes
through the price database's history (who, when, why).

All money is Decimal and stored as text ("1234.50"); see dmoney.py.
"""
import csv
import datetime as _dt
import logging
from decimal import Decimal

from . import pricedb
from .dmoney import D, cents

log = logging.getLogger(__name__)

FLAG_PCT = Decimal(10)          # variance worth a look
DEFAULT_ESCALATION = Decimal("0.035")
HALF_LIFE_MONTHS = 24


class HistoryError(RuntimeError):
    pass


def _txt(v, places="0.0001"):
    if v is None or v == "":
        return None
    return str(D(v).quantize(Decimal(places)))


def _today():
    return _dt.date.today().isoformat()


# ------------------------------------------------------------- estimate
def estimate_lines(doc):
    """The estimate by cost code, from the assembly rollup: [{"code",
    "desc", "unit", "qty", "unit_cost"}] (unit_cost = material + labor
    per unit, Decimal)."""
    from . import assemblies
    rows, _totals, _err = assemblies.rollup(doc)
    by = {}
    for r in rows:
        for q in r["parts"]:
            code = q.get("code") or f"{r['name']} / {q['name']}"
            e = by.setdefault((code, (q.get("unit") or "").upper()), {
                "code": code, "desc": q["name"], "unit": q.get("unit", ""),
                "qty": Decimal(0), "total": Decimal(0)})
            e["qty"] += D(q["qty"])
            e["total"] += D(q["material"]) + D(q.get("labor_cost", 0))
    out = []
    for e in by.values():
        uc = (e["total"] / e["qty"]) if e["qty"] else Decimal(0)
        out.append({"code": e["code"], "desc": e["desc"], "unit": e["unit"],
                    "qty": e["qty"], "unit_cost": cents(uc)})
    out.sort(key=lambda x: x["code"])
    return out


# ------------------------------------------------------------- jobs
def add_job(number, name="", lines=(), client="", type="", estimator=None,
            book="", region="", bid_date="", bid_total=None, folder="",
            file=""):
    """Register a job and its estimate lines. Returns the job id."""
    number = str(number or "").strip()
    if not number:
        raise HistoryError("Give the job a number.")
    with pricedb.connect(write=True) as con:
        if con.execute("SELECT 1 FROM jobs WHERE number=?",
                       (number,)).fetchone():
            raise HistoryError(f"Job {number} is already in the history.")
        cur = con.execute(
            "INSERT INTO jobs (number, name, client, type, estimator, book, "
            "region, bid_date, status, bid_total, folder, file, added, "
            "added_by) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (number, name, client, type, estimator or pricedb.user(), book,
             region, bid_date or _today(), "Bid",
             _txt(bid_total, "0.01"), folder, file, pricedb.now(),
             pricedb.user()))
        jid = cur.lastrowid
        for ln in lines:
            con.execute(
                "INSERT INTO job_lines (job, code, desc, unit, est_qty, "
                "est_unit_cost, source) VALUES (?,?,?,?,?,?,?)",
                (jid, ln["code"], ln.get("desc", ""), ln.get("unit", ""),
                 _txt(ln.get("qty")), _txt(ln.get("unit_cost"), "0.01"),
                 "estimate"))
    return jid


def job_from_doc(doc, number, name="", **kw):
    """Register the job a PDF's locked bid belongs to (its estimate as it
    was when the bid was locked)."""
    from . import assemblies, prebid
    lk = prebid.lock_state(doc)
    lines = (lk or {}).get("estimate")
    if lines:
        lines = [dict(x, qty=D(x["qty"]), unit_cost=D(x["unit_cost"]))
                 for x in lines]
    else:
        lines = estimate_lines(doc)
    job = assemblies.read_job(doc)
    return add_job(number, name or (doc.name or "").rsplit("\\", 1)[-1]
                   .rsplit("/", 1)[-1], lines,
                   bid_total=(lk or {}).get("total"),
                   book=job.get("costbook") or "",
                   region=job.get("region") or "",
                   file=doc.name or "", **kw)


def jobs():
    with pricedb.connect() as con:
        return [dict(r) for r in con.execute(
            "SELECT * FROM jobs ORDER BY bid_date DESC, id DESC")]


def lines(job_id):
    with pricedb.connect() as con:
        return [dict(r) for r in con.execute(
            "SELECT * FROM job_lines WHERE job=? ORDER BY code", (job_id,))]


def _norm(code):
    return "".join(ch for ch in str(code or "").upper() if ch.isalnum())


def set_actuals(job_id, actuals, source="import"):
    """actuals: [{"code", "cost", "qty"?, "unit"?, "desc"?}] - matched to
    the job's lines by code (spaces and dashes ignored). Codes the estimate
    didn't have are added as actual-only lines. Returns (matched, added)."""
    matched = added = 0
    with pricedb.connect(write=True) as con:
        rows = {_norm(r["code"]): r for r in con.execute(
            "SELECT * FROM job_lines WHERE job=?", (job_id,))}
        for a in actuals:
            key = _norm(a.get("code"))
            if not key:
                continue
            cost = _txt(a.get("cost"), "0.01")
            qty = _txt(a.get("qty")) if a.get("qty") not in (None, "") \
                else None
            r = rows.get(key)
            if r is not None:
                con.execute("UPDATE job_lines SET act_cost=?, act_qty=?, "
                            "source=? WHERE id=?",
                            (cost, qty if qty is not None else r["act_qty"],
                             f"estimate+{source}", r["id"]))
                matched += 1
            else:
                con.execute(
                    "INSERT INTO job_lines (job, code, desc, unit, act_qty, "
                    "act_cost, source) VALUES (?,?,?,?,?,?,?)",
                    (job_id, a.get("code"), a.get("desc", ""),
                     a.get("unit", ""), qty, cost, source))
                added += 1
    return matched, added


def read_actuals_csv(path):
    """A job-cost report (QuickBooks / Sage / Excel saved as CSV): needs a
    cost code column and an amount column; quantity, unit and description
    are used when present."""
    def pick(head, *names):
        for n in names:
            for i, h in enumerate(head):
                if h == n or h.startswith(n):
                    return i
        return None
    from .textio import open_csv              # Excel's Windows-1252 too
    with open_csv(path) as f:
        rows = list(csv.reader(f))
    for hi, head in enumerate(rows[:10]):
        h = [str(x).strip().lower() for x in head]
        c = pick(h, "cost code", "code", "item", "csi")
        a = pick(h, "actual cost", "actual", "amount", "cost", "total")
        if c is not None and a is not None and c != a:
            q = pick(h, "actual qty", "quantity", "qty", "units installed")
            u = pick(h, "unit", "uom")
            d = pick(h, "description", "desc", "name")
            out = []
            for r in rows[hi + 1:]:
                if len(r) <= max(c, a) or not str(r[c]).strip():
                    continue
                cost = D(r[a])
                if cost == 0 and not str(r[a]).strip():
                    continue
                out.append({"code": r[c].strip(), "cost": cost,
                            "qty": D(r[q]) if q is not None and q < len(r)
                            and str(r[q]).strip() else None,
                            "unit": r[u].strip() if u is not None and
                            u < len(r) else "",
                            "desc": r[d].strip() if d is not None and
                            d < len(r) else ""})
            return out
    raise HistoryError("No cost code and amount columns found in that "
                       "file.")


def actuals_from_store(store):
    """Actual costs (and installed quantities) by cost code from a Project
    Center project's direct costs."""
    from .pm import cost
    by = {}
    for x in store.list("cost"):
        k = cost.code_key(x.get("cost_code"))
        e = by.setdefault(k, {"code": k, "cost": Decimal(0), "qty": None,
                              "unit": x.get("unit", ""),
                              "desc": x.get("description", "")})
        e["cost"] += D(x.get("amount"))
        if x.get("quantity") not in (None, ""):
            e["qty"] = (e["qty"] or Decimal(0)) + D(x.get("quantity"))
    return list(by.values())


# ------------------------------------------------------------- variance
def variance(job_id):
    """Each line, estimate vs actual: est and actual $ and unit cost, the
    difference and % (Decimal), and "flag" when it's off by over 10%."""
    out = []
    for r in lines(job_id):
        eq, eu = D(r["est_qty"]), D(r["est_unit_cost"])
        aq = D(r["act_qty"]) if r["act_qty"] not in (None, "") else None
        ac = D(r["act_cost"]) if r["act_cost"] not in (None, "") else None
        est = cents(eq * eu)
        act_unit = cents(ac / aq) if ac is not None and aq else None
        diff = cents(ac - est) if ac is not None else None
        pct = (diff / est * 100).quantize(Decimal("0.1")) \
            if diff is not None and est else None
        out.append({"code": r["code"], "desc": r["desc"], "unit": r["unit"],
                    "est_qty": eq, "est_unit": eu, "est_cost": est,
                    "act_qty": aq, "act_cost": ac, "act_unit": act_unit,
                    "diff": diff, "pct": pct,
                    "flag": pct is not None and abs(pct) > FLAG_PCT,
                    "source": r["source"]})
    return out


def close_job(job_id, region="", record=True):
    """Close a job: every line with an actual cost and quantity becomes a
    unit-cost observation. Returns how many were recorded."""
    n = 0
    with pricedb.connect(write=True) as con:
        job = con.execute("SELECT * FROM jobs WHERE id=?",
                          (job_id,)).fetchone()
        if job is None:
            raise HistoryError("No such job.")
        if job["status"] == "Closed":
            raise HistoryError(f"Job {job['number']} is already closed.")
        if record:
            for r in con.execute("SELECT * FROM job_lines WHERE job=?",
                                 (job_id,)).fetchall():
                if r["act_cost"] in (None, "") or r["act_qty"] in (None, ""):
                    continue
                q = D(r["act_qty"])
                if q <= 0:
                    continue
                con.execute(
                    "INSERT INTO unit_cost_obs (code, unit, unit_cost, qty, "
                    "job, date, region, kind, source, added_by) VALUES "
                    "(?,?,?,?,?,?,?,?,?,?)",
                    (r["code"], r["unit"], _txt(D(r["act_cost"]) / q,
                                                "0.0001"),
                     _txt(q), job_id, _today(), region or job["region"],
                     "actual", f"job {job['number']}", pricedb.user()))
                n += 1
        con.execute("UPDATE jobs SET status='Closed', closed=? WHERE id=?",
                    (_today(), job_id))
    return n


def add_observation(code, unit_cost, qty=1, unit="", kind="quote",
                    date=None, region="", source="", job=None):
    with pricedb.connect(write=True) as con:
        con.execute(
            "INSERT INTO unit_cost_obs (code, unit, unit_cost, qty, job, "
            "date, region, kind, source, added_by) VALUES "
            "(?,?,?,?,?,?,?,?,?,?)",
            (code, unit, _txt(unit_cost), _txt(qty), job, date or _today(),
             region, kind, source, pricedb.user()))


def observations(code, limit=None):
    with pricedb.connect() as con:
        rows = [dict(r) for r in con.execute(
            "SELECT * FROM unit_cost_obs WHERE code=? ORDER BY date DESC, "
            "id DESC", (code,))]
    return rows[:limit] if limit else rows


# ------------------------------------------------------------- suggest
def weighted_median(values, weights):
    """The value where the running weight reaches half the total
    (Decimals)."""
    pairs = sorted(zip(values, weights))
    total = sum(w for _v, w in pairs)
    if not pairs or total <= 0:
        return None
    half, run = total / 2, Decimal(0)
    for v, w in pairs:
        run += w
        if run >= half:
            return v
    return pairs[-1][0]


def _months(date, today):
    try:
        d = _dt.date.fromisoformat(str(date)[:10])
    except ValueError:
        return 0
    return max(0, (today.year - d.year) * 12 + today.month - d.month)


def suggest(code, book=None, n=8, today=None, escalation=None):
    """{"price", "min", "max", "count", "book", "obs"} for a code - the
    weighted median of its last n observations, each escalated to today
    (book's yearly escalation, else 3.5%). Weights: newer and bigger jobs
    count more. None when there are no observations."""
    today = today or _dt.date.today()
    obs = observations(code, n)
    if not obs:
        return None
    rate = D(escalation if escalation is not None else
             (getattr(book, "escalation", None) or DEFAULT_ESCALATION))
    vals, wts = [], []
    for o in obs:
        m = _months(o["date"], today)
        esc = Decimal(str((1 + float(rate)) ** (m / 12)))
        vals.append(D(o["unit_cost"]) * esc)
        q = max(D(o["qty"]), Decimal(1))
        wts.append(q.sqrt() * Decimal(str(0.5 ** (m / HALF_LIFE_MONTHS))))
    price = weighted_median(vals, wts)
    item = book.get(code) if book is not None else None
    cur = None
    if item:
        cur = cents(D(item.get("material")) + D(item.get("sub")))
    return {"code": code, "price": cents(price), "min": cents(min(vals)),
            "max": cents(max(vals)), "count": len(obs), "book": cur,
            "obs": obs}


def apply(book_name, picks, note=""):
    """Accept suggestions: picks {code: price}. The price goes into the
    item's material (or sub, when the item is priced as a sub). Codes the
    book doesn't have are reported, not created. Returns (changed,
    skipped)."""
    from . import costbook
    book = costbook.load(costbook.DB + book_name)
    changes, skipped = {}, []
    for code, price in picks.items():
        it = book.get(code)
        if not it:
            skipped.append(code)
            continue
        field = "sub" if D(it.get("sub")) and not D(it.get("material")) \
            else "material"
        changes[code] = {field: str(cents(price))}
    if changes:
        pricedb.update_items(book_name, changes,
                             note=f"history: {note}".strip())
    return sorted(changes), skipped
