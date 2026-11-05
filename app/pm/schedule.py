"""Project schedule: critical path, Gantt and lookahead PDFs, and
MS Project / Primavera P6 exchange.

Activities are records of the "activity" tool. Durations are in workdays
(Monday to Friday, less the project's holidays: setting "holidays", a
list of ISO dates). Predecessor links are finish-to-start unless typed SS,
FF or SF, with an optional lag in workdays.

compute(store) runs the critical path method:
  early start/finish forward from the data date and each activity's
  "start no earlier than", late start/finish backward from the project
  finish, total float = late start - early start; zero float is critical.
Actual dates, when entered, pin an activity where it really happened.
"""
import bisect
import json
import datetime as _dt
import math
import re
import xml.etree.ElementTree as ET

from . import schema

DAY = _dt.timedelta(days=1)
TYPES = ("FS", "SS", "FF", "SF")


# ------------------------------------------------------------- calendar
def _holiday(h):
    """A holiday as typed: 2026-07-03, 7/3/2026 or 07/03/26 (US order).
    Anything else was dropped without a word; now it is logged."""
    t = str(h or "").strip()
    try:
        return _dt.date.fromisoformat(t[:10])
    except ValueError:
        pass
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y"):
        try:
            return _dt.datetime.strptime(t, fmt).date()
        except ValueError:
            continue
    if t:
        import logging
        logging.getLogger(__name__).warning("holiday %r not understood", t)
    return None


class Calendar:
    """Workday arithmetic in index space: workday 0 is `base` (or the
    first workday after it)."""

    def __init__(self, base, holidays=()):
        self.hol = set()
        for h in holidays or ():
            d = _holiday(h)
            if d:
                self.hol.add(d)
        d = base
        while not self.is_work(d):
            d += DAY
        self.base = d
        self._days = [d]

    def is_work(self, d):
        return d.weekday() < 5 and d not in self.hol

    def _extend(self, n):
        while len(self._days) <= n:
            d = self._days[-1] + DAY
            while not self.is_work(d):
                d += DAY
            self._days.append(d)

    def date(self, i):
        """Workday index -> date (negative indexes count backwards)."""
        if i >= 0:
            self._extend(i)
            return self._days[i]
        d, n = self.base, -i
        while n:
            d -= DAY
            if self.is_work(d):
                n -= 1
        return d

    def index(self, d):
        """Date -> index of that workday, or of the next one."""
        if d < self.base:
            n, x = 0, d
            while x < self.base:
                if self.is_work(x):
                    n += 1
                x += DAY
            return -n
        while not self.is_work(d):
            d += DAY
        self._extend(int((d - self.base).days * 5 / 7) + 2)
        while self._days[-1] < d:
            self._extend(len(self._days) + 64)
        return bisect.bisect_left(self._days, d)


def _d(s):
    try:
        return _dt.date.fromisoformat(str(s)[:10]) if s else None
    except ValueError:
        return None


def _num(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def calendar(store, base=None):
    acts = store.list("activity")
    dates = [d for a in acts for d in (_d(a.get("start")),
                                       _d(a.get("actual_start"))) if d]
    ps = _d(store.setting("project_start"))
    if ps:
        dates.append(ps)
    base = base or (min(dates) if dates else _dt.date.today())
    return Calendar(base, store.setting("holidays") or ())


# ------------------------------------------------------------- links
def parse_preds(rec):
    """[(ref text, type, lag)] from the predecessors lines."""
    out = []
    for ln in rec.get("preds") or []:
        ref = str(ln.get("id") or "").strip()
        if not ref:
            continue
        t = str(ln.get("type") or "FS").strip().upper()[:2]
        out.append((ref, t if t in TYPES else "FS", _num(ln.get("lag"))))
    return out


def resolver(acts):
    """ref text -> activity id: matches the number (A0010, a10, 10) or the
    exact name."""
    by = {}
    for a in acts:
        no = str(a.get("_no") or "")
        by.setdefault(no.upper(), a["_id"])
        m = re.search(r"(\d+)$", no)
        if m:
            by.setdefault(str(int(m.group(1))), a["_id"])
        if a.get("name"):
            by.setdefault(str(a["name"]).strip().upper(), a["_id"])
        if a.get("_ext"):
            by.setdefault(str(a["_ext"]).upper(), a["_id"])

    def find(ref):
        r = ref.strip().upper()
        if r in by:
            return by[r]
        m = re.search(r"(\d+)$", r)
        return by.get(str(int(m.group(1)))) if m else None
    return find


# ------------------------------------------------------------- outline
def _seq(a):
    return (_num(a.get("seq"), _num(a.get("_n"), 0)), a.get("_n") or 0)


def outline(acts):
    """Activities in outline order (the order they were typed, children
    under their summary): [(record, level, is_summary)]. "parent" is the
    summary row's id, "seq" the position among its siblings."""
    by = {a["_id"]: a for a in acts}
    kids = {}
    for a in acts:
        p = a.get("parent")
        if p not in by or p == a["_id"]:
            p = None
        kids.setdefault(p, []).append(a)
    out, seen = [], set()

    def walk(p, lvl):
        for a in sorted(kids.get(p, []), key=_seq):
            if a["_id"] in seen:
                continue
            seen.add(a["_id"])
            out.append((a, lvl, bool(kids.get(a["_id"]))))
            walk(a["_id"], lvl + 1)
    walk(None, 0)
    for a in sorted(acts, key=_seq):            # a parent loop: flatten
        if a["_id"] not in seen:
            out.append((a, 0, False))
    return out


def summaries(acts):
    """{summary id: [all descendant ids]}."""
    by = {a["_id"]: a for a in acts}
    kids = {}
    for a in acts:
        p = a.get("parent")
        if p in by and p != a["_id"]:
            kids.setdefault(p, []).append(a["_id"])
    out = {}
    for sid in kids:
        seen, stack = [], list(kids[sid])
        while stack:
            k = stack.pop()
            if k in seen or k == sid:
                continue
            seen.append(k)
            stack += kids.get(k, [])
        out[sid] = seen
    return out


# ------------------------------------------------------------- CPM
def compute(store, data_date=None):
    """{"rows": [row...], "finish": date, "critical": [ids], "problems":
    [text], "cal": Calendar}. A row is the activity plus es, ef (dates),
    ls, lf, float (workdays), critical (bool), dur."""
    acts = store.list("activity")
    cal = calendar(store)
    find = resolver(acts)
    by = {a["_id"]: a for a in acts}
    problems = []
    summ = summaries(acts)
    ps = _d(store.setting("project_start"))
    dur, preds, succs = {}, {}, {}
    for a in acts:
        dur[a["_id"]] = 0 if a["_id"] in summ else \
            max(0, int(round(_num(a.get("duration"), 0))))
        preds[a["_id"]] = []
        succs.setdefault(a["_id"], [])
    for a in acts:
        for ref, t, lag in parse_preds(a):
            p = find(ref)
            if p is None:
                problems.append(f"{a.get('_no')} {a.get('name')}: no "
                                f"activity '{ref}'")
                continue
            if p == a["_id"]:
                continue
            if p in summ or a["_id"] in summ:
                problems.append(f"{a.get('_no')} {a.get('name')}: links to "
                                "or from a summary row aren't used - link "
                                "the activities under it")
                continue
            preds[a["_id"]].append((p, t, int(round(lag))))
            succs.setdefault(p, []).append((a["_id"], t, int(round(lag))))
    # topological order (Kahn); links in a loop are dropped and reported
    def topo():
        indeg = {i: len(preds[i]) for i in by}
        order = [i for i in by if indeg[i] == 0]
        k = 0
        while k < len(order):
            for sx, _t, _l in succs.get(order[k], []):
                indeg[sx] -= 1
                if indeg[sx] == 0:
                    order.append(sx)
            k += 1
        return order
    order = topo()
    if len(order) < len(by):
        left = set(by) - set(order)

        def reaches(src):
            seen, stack = set(), [src]
            while stack:
                n = stack.pop()
                for sx, _t, _l in succs.get(n, []):
                    if sx == src:
                        return True
                    if sx in left and sx not in seen:
                        seen.add(sx)
                        stack.append(sx)
            return False
        loop = [i for i in left if reaches(i)]
        loopset = set(loop)
        problems.append("These activities depend on each other in a loop "
                        "and were scheduled without those links: " +
                        ", ".join(sorted(str(by[i].get("_no"))
                                         for i in loop)))
        for i in loop:
            preds[i] = [x for x in preds[i] if x[0] not in loopset]
        for p in loop:
            succs[p] = [x for x in succs.get(p, []) if x[0] not in loopset]
        order = topo()
    dd = cal.index(data_date) if data_date else None
    es, efx = {}, {}
    for i in order:
        a = by[i]
        n = dur[i]
        cand = [0]
        if ps:
            cand.append(cal.index(ps))
        snet = _d(a.get("start"))
        if snet:
            cand.append(cal.index(snet))
        for p, t, lag in preds[i]:
            if t == "FS":
                cand.append(efx[p] + lag)
            elif t == "SS":
                cand.append(es[p] + lag)
            elif t == "FF":
                cand.append(efx[p] + lag - n)
            else:                                    # SF
                cand.append(es[p] + lag - n)
        start = max(cand)
        started = bool(a.get("actual_start")) or \
            a.get("status") in ("In Progress", "Complete") or \
            _num(a.get("percent")) > 0
        if dd is not None and not started:
            start = max(start, dd)       # unstarted work can't be in the past
        if a.get("actual_start"):
            start = cal.index(_d(a["actual_start"]))
        es[i] = start
        efx[i] = start + n
        if a.get("actual_finish"):
            efx[i] = max(start, cal.index(_d(a["actual_finish"])) +
                         (1 if n else 0))
        elif started and dd is not None and a.get("status") != "Complete" \
                and _num(a.get("percent")) < 100:
            # in progress: what's left runs from the data date on
            pc = _num(a.get("percent"), -1)
            if pc >= 0:
                left = int(math.ceil(n * max(0.0, 100 - pc) / 100))
                # the part done sits from the start; what's left runs on
                # from the data date - or right after the done part when
                # the activity is planned to start after the data date
                efx[i] = max(start + (1 if n else 0),
                             max(dd, start + n - left) + left)
            else:
                left = max(1, start + n - dd)
                efx[i] = max(start + (1 if n else 0), dd + left)
    finish = max(efx.values()) if efx else 0
    lfx, ls = {}, {}
    for i in reversed(order):
        n = dur[i]
        cand = [finish]
        for s, t, lag in succs.get(i, []):
            if t == "FS":
                cand.append(ls[s] - lag)
            elif t == "SS":
                cand.append(ls[s] - lag + n)
            elif t == "FF":
                cand.append(lfx[s] - lag)
            else:
                cand.append(lfx[s] - lag + n)
        lfx[i] = min(cand)
        ls[i] = lfx[i] - n
    rows = []
    for a in acts:
        i = a["_id"]
        n = dur[i]
        fl = ls[i] - es[i]
        row = dict(a)
        if n == 0 and es[i] > 0 and preds[i]:
            # a milestone after its predecessors falls on the day they
            # finish (as in Project and P6), not the next morning
            es_d = ef_d = cal.date(es[i] - 1)
        else:
            es_d, ef_d = cal.date(es[i]), cal.date(max(es[i], efx[i] - 1))
        row.update(
            dur=n, es_i=es[i], ef_i=efx[i], float=fl,
            critical=fl <= 0 and a.get("status") != "Complete",
            es=es_d, ef=ef_d,
            ls=cal.date(ls[i]), lf=cal.date(max(ls[i], lfx[i] - 1)),
            milestone=n == 0,
            pred_ids=[p for p, _t, _l in preds[i]],
            links=[(p, t, lag) for p, t, lag in preds[i]])
        rows.append(row)
    # summary rows span their activities
    byrow = {r["_id"]: r for r in rows}
    for sid, kids in summ.items():
        ch = [byrow[k] for k in kids if k in byrow and k not in summ]
        r = byrow.get(sid)
        if r is None:
            continue
        r["summary"] = True
        r["milestone"] = False
        r["links"], r["pred_ids"] = [], []
        if not ch:
            continue
        r["es_i"] = min(c["es_i"] for c in ch)
        r["ef_i"] = max(c["ef_i"] for c in ch)
        r["es"] = min(c["es"] for c in ch)
        r["ef"] = max(c["ef"] for c in ch)
        r["ls"] = min(c["ls"] for c in ch)
        r["lf"] = max(c["lf"] for c in ch)
        r["dur"] = max(0, cal.index(r["ef"]) - cal.index(r["es"]) + 1)
        r["float"] = min(c["float"] for c in ch)
        r["critical"] = any(c["critical"] for c in ch)
        tot = sum(max(1, c["dur"]) for c in ch)
        r["percent"] = round(sum(max(1, c["dur"]) *
                                 _num(c.get("percent")) for c in ch) /
                             tot) if tot else 0
    rows.sort(key=lambda r: (r["es_i"], r.get("_n") or 0))
    return {"rows": rows, "cal": cal, "problems": problems,
            "finish": max(r["ef"] for r in rows) if rows else None,
            "start": min(r["es"] for r in rows) if rows else None,
            "critical": [r["_id"] for r in rows if r["critical"] and
                         not r.get("summary")]}


_CACHE = {}


def data_date(store):
    """The status date: unstarted work can't be scheduled before it and
    unfinished work runs on from it (setting "data_date", else today)."""
    return _d(store.setting("data_date")) or _dt.date.today()


# The settings compute() reads. Only these go into cached()'s signature:
# the project settings also hold the schedule update log and its anchor
# (a full copy of every activity per saved update), and serialising those
# on every Start/Finish/Float cell made the Activity list crawl. The extra
# calendar-ish names are signed in case a work-week setting is added.
CPM_SETTINGS = ("project_start", "holidays", "data_date",
                "work_days", "workweek", "calendar")


def _sig(store):
    st = store.setting
    return (getattr(store, "version", None),
            tuple((k, r.get("_updated"), r.get("_rev"), r.get("_deleted"))
                  for k, r in store.coll("activity").items()),
            data_date(store),
            json.dumps([st(k) for k in CPM_SETTINGS], sort_keys=True,
                       default=str))


def cached(store):
    """compute(store), reused until an activity or a setting the CPM
    reads (project start, holidays, data date) changes."""
    sig = _sig(store)
    hit = _CACHE.get(id(store))
    if hit and hit[0] == sig:
        return hit[1]
    cpm = compute(store, data_date(store))
    _CACHE[id(store)] = (sig, cpm)
    return cpm


def cell(store, rec, c, cpm=None):
    cpm = cpm or cached(store)
    row = next((r for r in cpm["rows"] if r["_id"] == rec.get("_id")), None)
    if row is None:
        return ""
    if c == "_start":
        return row["es"].isoformat()
    if c == "_finish":
        return row["ef"].isoformat()
    if c == "_float":
        if row.get("status") == "Complete":
            return "Done"
        return "Critical" if row["critical"] else f"{row['float']}d"
    return ""


def update_dates(store, cpm=None):
    """Nothing is stored for computed dates; this sets status from actual
    dates and % complete (handy after an import)."""
    n = 0
    for a in store.list("activity"):
        st = a.get("status") or "Not Started"
        want = st
        pc = _num(a.get("percent"))
        if a.get("actual_finish") or pc >= 100:
            want = "Complete"
        elif a.get("actual_start") or pc > 0:
            want = "In Progress"
        if want != st:
            a["status"] = want
            store.save_record("activity", a)
            n += 1
    return n


class BaselineLocked(RuntimeError):
    """Set Baseline while the Master Schedule baseline lock is on."""


def set_baseline(store):
    """Copy today's computed dates into the baseline fields."""
    lk = store.setting("master_baseline")
    if isinstance(lk, dict) and lk.get("locked"):
        raise BaselineLocked("The baseline is locked (Master Schedule). "
                             "Use Master Schedule > Re-baseline… for a new "
                             "one; the locked baseline is kept.")
    cpm = cached(store)
    n = 0
    for r in cpm["rows"]:
        a = store.get("activity", r["_id"])
        bs, bf = r["es"].isoformat(), r["ef"].isoformat()
        if a.get("baseline_start") != bs or a.get("baseline_finish") != bf:
            a["baseline_start"], a["baseline_finish"] = bs, bf
            store.save_record("activity", a)
            n += 1
    return n


def lookahead(store, weeks=3, start=None, cpm=None):
    """Rows of work happening in the next `weeks` (not complete)."""
    cpm = cpm or cached(store)
    start = start or _dt.date.today()
    end = start + _dt.timedelta(days=7 * weeks - 1)
    return [r for r in cpm["rows"] if r.get("status") != "Complete" and
            r["es"] <= end and r["ef"] >= start], start, end


def variance(row, cal=None):
    """Workdays late against the baseline finish (+ late, - early).
    With the project calendar, holidays don't count (review 3 #19)."""
    bf = _d(row.get("baseline_finish"))
    if not bf:
        return None
    sign = 1 if row["ef"] >= bf else -1
    a, b = sorted((bf, row["ef"]))
    n, d = 0, a
    while d < b:
        d += DAY
        if (cal.is_work(d) if cal is not None else d.weekday() < 5):
            n += 1
    return sign * n


# ------------------------------------------------------------- PDF
def gantt_pdf(store, path, rows=None, title="Schedule", start=None,
              end=None, cpm=None):
    """A Gantt chart on 11x17 landscape pages: the activity table on the
    left, bars on a weekly time scale, critical work in red, progress
    filled in, baselines as thin grey bars, today as a dashed line."""
    import fitz
    cpm = cpm or cached(store)
    levels = {}
    if rows is None:
        # outline order (as typed / in the Scheduler), summaries over
        # their activities
        by = {r["_id"]: r for r in cpm["rows"]}
        ol = outline([r for r in cpm["rows"]])
        rows = [by[a["_id"]] for a, _l, _s in ol if a["_id"] in by]
        levels = {a["_id"]: lvl for a, lvl, _s in ol}
    W, H = 1224, 792
    M = 30
    cols = [("ID", 52), ("Activity", 230), ("Dur", 34), ("Start", 62),
            ("Finish", 62), ("Float", 44)]
    tw = sum(w for _n, w in cols)
    gx0, gx1 = M + tw + 6, W - M
    top, rh = 112, 16
    per = int((H - top - 40) // rh)
    s = start or (min((r["es"] for r in rows), default=_dt.date.today()))
    e = end or (max((r["ef"] for r in rows), default=s))
    s = s - _dt.timedelta(days=s.weekday())          # Monday
    e = e + _dt.timedelta(days=6 - e.weekday())
    days = max(7, (e - s).days + 1)
    px = (gx1 - gx0) / days

    def x(d):
        return gx0 + (d - s).days * px
    red, blue = (0.82, 0.16, 0.16), (0.16, 0.38, 0.78)
    grey, dark = (0.6, 0.6, 0.6), (0.15, 0.15, 0.15)
    doc = fitz.open()
    today = _dt.date.today()
    pages = max(1, -(-len(rows) // per))
    for pn in range(pages):
        pg = doc.new_page(width=W, height=H)
        pg.insert_text((M, 44), title, fontsize=18, fontname="hebo")
        sub = f"{store.name}   ·   {sum(1 for r in rows if not r.get('summary'))} activities   ·   finish " \
              f"{cpm['finish'] or ''}   ·   printed {today:%b %d, %Y}"
        pg.insert_text((M, 62), sub, fontsize=9, color=grey)
        if pages > 1:
            pg.insert_text((W - M - 70, 44), f"Page {pn + 1} of {pages}",
                           fontsize=9, color=grey)
        # header
        y = top - 26
        cx = M
        for name, w in cols:
            pg.insert_text((cx + 2, top - 6), name, fontsize=8,
                           fontname="hebo")
            cx += w
        # time scale: months above weeks
        d = s
        last_m = None
        while d <= e:
            xx = x(d)
            if d.weekday() == 0:
                pg.draw_line((xx, top - 14), (xx, H - 40),
                             color=(0.9, 0.9, 0.9), width=0.4)
                if px * 7 > 26:
                    pg.insert_text((xx + 2, top - 6), f"{d:%d}", fontsize=7,
                                   color=grey)
            if d.month != last_m:
                pg.insert_text((xx + 2, y + 2), f"{d:%b %Y}", fontsize=8,
                               fontname="hebo")
                pg.draw_line((xx, y - 8), (xx, top - 14), color=grey,
                             width=0.6)
                last_m = d.month
            d += DAY
        pg.draw_line((M, top - 2), (W - M, top - 2), color=dark, width=0.8)
        if s <= today <= e:
            pg.draw_line((x(today), top - 14), (x(today), H - 40),
                         color=(0.9, 0.5, 0), width=0.8, dashes="[3 2] 0")
        chunk = rows[pn * per:(pn + 1) * per]
        for k, r in enumerate(chunk):
            yy = top + k * rh
            if k % 2:
                pg.draw_rect(fitz.Rect(M, yy, W - M, yy + rh),
                             color=None, fill=(0.97, 0.97, 0.97))
            vals = [str(r.get("_no") or ""),
                    "   " * levels.get(r["_id"], 0) + str(r.get("name") or ""),
                    f"{r['dur']}d", f"{r['es']:%m/%d/%y}",
                    f"{r['ef']:%m/%d/%y}",
                    "done" if r.get("status") == "Complete" else
                    "crit" if r["critical"] else f"{r['float']}d"]
            cx = M
            for (name, w), val in zip(cols, vals):
                while val and fitz.get_text_length(val, fontsize=8) > w - 4:
                    val = val[:-2] + "…" if len(val) > 2 else ""
                pg.insert_text((cx + 2, yy + 11), val, fontsize=8,
                               color=red if r["critical"] and
                               name == "Float" else dark)
                cx += w
            col = red if r["critical"] else blue
            bs, bf = _d(r.get("baseline_start")), _d(r.get("baseline_finish"))
            if bs and bf and bf >= s and bs <= e:
                pg.draw_rect(fitz.Rect(max(gx0, x(bs)), yy + 11,
                                       min(gx1, x(bf) + px), yy + 13.5),
                             color=None, fill=grey)
            if r.get("summary"):
                x0 = max(gx0, x(r["es"]))
                x1 = min(gx1, x(r["ef"]) + px)
                if x1 > x0:
                    pg.draw_rect(fitz.Rect(x0, yy + 4, x1, yy + 7.5),
                                 color=None, fill=dark)
                    for xe in (x0, x1):
                        pg.draw_polyline([(xe - 3, yy + 7.5),
                                          (xe + 3, yy + 7.5),
                                          (xe, yy + 11.5)],
                                         color=dark, fill=dark, width=0.3)
                continue
            if r["milestone"]:
                cxm, cym = x(r["es"]), yy + rh / 2
                q = fitz.Quad((cxm, cym - 5), (cxm + 5, cym),
                              (cxm - 5, cym), (cxm, cym + 5))
                pg.draw_quad(q, color=dark, fill=col)
                pg.insert_text((cxm + 8, cym + 3), f"{r['es']:%b %d}",
                               fontsize=7, color=dark)
                continue
            x0 = max(gx0, x(r["es"]))
            x1 = min(gx1, x(r["ef"]) + px)
            if x1 <= x0:
                continue
            pg.draw_rect(fitz.Rect(x0, yy + 3, x1, yy + 10.5), color=col,
                         fill=tuple(c * 0.35 + 0.65 for c in col),
                         width=0.6)
            pc = max(0.0, min(100.0, _num(r.get("percent"))))
            if pc:
                pg.draw_rect(fitz.Rect(x0, yy + 3, x0 + (x1 - x0) * pc / 100,
                                       yy + 10.5), color=None, fill=col)
            if r.get("responsible") and x1 + 60 < gx1:
                pg.insert_text((x1 + 3, yy + 10), str(r["responsible"])[:28],
                               fontsize=6.5, color=grey)
        # legend
        ly = H - 22
        lx = M
        for label, c in (("Critical", red), ("Has float", blue),
                         ("Baseline", grey)):
            pg.draw_rect(fitz.Rect(lx, ly - 6, lx + 16, ly), color=None,
                         fill=c)
            pg.insert_text((lx + 20, ly), label, fontsize=8)
            lx += 90
        pg.insert_text((lx, ly), "Diamond = milestone   ·   dashed line "
                       "= today   ·   filled part = % complete", fontsize=8,
                       color=grey)
    doc.save(path, garbage=3, deflate=True)
    return path


def lookahead_pdf(store, path, weeks=3, start=None):
    rows, s, e = lookahead(store, weeks, start)
    return gantt_pdf(store, path, rows,
                     title=f"{weeks}-Week Lookahead  {s:%b %d} - {e:%b %d, %Y}",
                     start=s, end=e)


# ------------------------------------------------------------- exchange
_MSP_TYPE = {"0": "FF", "1": "FS", "2": "SF", "3": "SS"}
_MSP_CODE = {v: k for k, v in _MSP_TYPE.items()}


def _hours(iso_dur):
    """'PT40H0M0S' -> 40.0"""
    m = re.match(r"P(?:(\d+)D)?T?(?:(\d+(?:\.\d+)?)H)?(?:(\d+)M)?",
                 iso_dur or "")
    if not m:
        return 0.0
    d, h, mi = m.groups()
    return float(d or 0) * 8 + float(h or 0) + float(mi or 0) / 60


def msproject_holidays(root, ns=""):
    """The non-working days of a Project XML file's project calendar: its
    Exceptions (Project 2007 and later) or WeekDay entries with DayType 0
    (older files), as ISO dates. Ranges of more than 31 days are skipped
    (a shutdown that long is no list of holidays)."""
    def t(el, name):
        x = el.find(ns + name)
        return x.text if x is not None and x.text is not None else ""
    want = t(root, "CalendarUID")
    cals = root.find(ns + "Calendars")
    if cals is None:
        return []
    cal = None
    for c in cals.findall(ns + "Calendar"):
        if t(c, "UID") == want or (cal is None and t(c, "IsBaseCalendar")
                                   == "1"):
            cal = c
            if t(c, "UID") == want:
                break
    if cal is None:
        return []
    periods = []
    exs = cal.find(ns + "Exceptions")
    for ex in exs.findall(ns + "Exception") if exs is not None else ():
        if t(ex, "DayWorking") == "1":
            continue
        tp = ex.find(ns + "TimePeriod")
        if tp is not None:
            periods.append((t(tp, "FromDate"), t(tp, "ToDate")))
    wds = cal.find(ns + "WeekDays")
    for wd in wds.findall(ns + "WeekDay") if wds is not None else ():
        tp = wd.find(ns + "TimePeriod")
        if t(wd, "DayType") == "0" and t(wd, "DayWorking") != "1" and \
                tp is not None:
            periods.append((t(tp, "FromDate"), t(tp, "ToDate")))
    out = set()
    for a, b in periods:
        a, b = _d(a), _d(b) or _d(a)
        if not a or not b or b < a or (b - a).days > 31:
            continue
        while a <= b:
            out.add(a.isoformat())
            a += DAY
    return sorted(out)


def import_msproject(store, path):
    """Read a Microsoft Project XML file (File > Save As > XML in
    Project). Summary tasks become the area of the tasks under them;
    Notes and Baseline 0 start / finish are kept when present. Returns the number of activities added or updated."""
    from .. import safexml                  # threat model T-007
    tree = safexml.parse(path)
    root = tree.getroot()
    ns = ""
    if root.tag.startswith("{"):
        ns = root.tag.split("}")[0] + "}"

    def t(el, name):
        x = el.find(ns + name)
        return x.text if x is not None and x.text is not None else ""
    tasks = root.find(ns + "Tasks")
    if tasks is None:
        raise ValueError("This isn't a Microsoft Project XML file.")
    if not store.setting("holidays"):       # the calendar's days off
        hols = msproject_holidays(root, ns)
        if hols:
            store.set_setting("holidays", hols)
    outline = {}
    items = []
    for task in tasks.findall(ns + "Task"):
        uid = t(task, "UID")
        name = t(task, "Name")
        if not name or uid == "0":
            continue
        lvl = int(t(task, "OutlineLevel") or 1)
        if t(task, "Summary") == "1":
            for k in [k for k in outline if k >= lvl]:
                del outline[k]
            outline[lvl] = name
            continue
        area = " / ".join(outline[k] for k in sorted(outline) if k < lvl)
        links = []
        for pl in task.findall(ns + "PredecessorLink"):
            lag = float(t(pl, "LinkLag") or 0) / 4800.0  # tenths of minutes
            links.append({"uid": t(pl, "PredecessorUID"),
                          "type": _MSP_TYPE.get(t(pl, "Type"), "FS"),
                          "lag": round(lag, 1) or ""})
        base = next((b for b in task.findall(ns + "Baseline")
                     if (t(b, "Number") or "0") == "0"), None)
        items.append({
            "uid": uid, "name": name, "area": area,
            "notes": t(task, "Notes"),
            "baseline_start": t(base, "Start")[:10] if base is not None
            else "",
            "baseline_finish": t(base, "Finish")[:10] if base is not None
            else "",
            "duration": round(_hours(t(task, "Duration")) / 8, 1),
            "start": t(task, "Start")[:10],
            "percent": t(task, "PercentComplete"),
            "actual_start": t(task, "ActualStart")[:10],
            "actual_finish": t(task, "ActualFinish")[:10],
            "milestone": t(task, "Milestone") == "1",
            "links": links})
    return _merge(store, items, "msp")


def import_xer(store, path):
    """Read a Primavera P6 .xer export (TASK and TASKPRED tables)."""
    with open(path, encoding="cp1252", errors="replace") as f:
        lines = f.read().splitlines()
    tables, cur, fields = {}, None, []
    for ln in lines:
        parts = ln.split("\t")
        if parts[0] == "%T":
            cur = parts[1]
            tables[cur] = []
        elif parts[0] == "%F":
            fields = parts[1:]
        elif parts[0] == "%R" and cur:
            tables[cur].append(dict(zip(fields, parts[1:])))
    if "TASK" not in tables:
        raise ValueError("No activities (TASK table) in this XER file.")
    wbs = {w.get("wbs_id"): w.get("wbs_name", "")
           for w in tables.get("PROJWBS", [])}
    preds = {}
    for p in tables.get("TASKPRED", []):
        preds.setdefault(p.get("task_id"), []).append({
            "uid": p.get("pred_task_id"),
            "type": (p.get("pred_type") or "PR_FS")[-2:],
            "lag": round(_num(p.get("lag_hr_cnt")) / 8, 1) or ""})
    items = []
    for tk in tables["TASK"]:
        hrs = _num(tk.get("target_drtn_hr_cnt"))
        start = (tk.get("act_start_date") or tk.get("restart_date") or
                 tk.get("target_start_date") or "")[:10]
        items.append({
            "uid": tk.get("task_id"), "code": tk.get("task_code"),
            "name": tk.get("task_name") or tk.get("task_code"),
            "area": wbs.get(tk.get("wbs_id"), ""),
            "duration": round(hrs / 8, 1),
            "start": start,
            "percent": str(round(_num(tk.get("phys_complete_pct")))),
            "actual_start": (tk.get("act_start_date") or "")[:10],
            "actual_finish": (tk.get("act_end_date") or "")[:10],
            "milestone": (tk.get("task_type") or "").endswith("Mile"),
            "links": preds.get(tk.get("task_id"), [])})
    return _merge(store, items, "p6")


def _merge(store, items, src):
    """Add or update activities from an import, keyed by the source's id
    (so importing an updated schedule again updates in place)."""
    existing = {a.get("_ext"): a for a in store.list("activity")
                if a.get("_ext")}
    ids = {}
    n = 0
    for it in items:
        ext = f"{src}:{it['uid']}"
        a = existing.get(ext) or {"_ext": ext}
        a.update({"name": it["name"], "area": it.get("area", ""),
                  "duration": 0 if it.get("milestone") else
                  it.get("duration", 0),
                  "start": it.get("start") or "",
                  "percent": it.get("percent") or "",
                  "actual_start": it.get("actual_start") or "",
                  "actual_finish": it.get("actual_finish") or ""})
        if it.get("code"):
            a["source_id"] = it["code"]
        # notes / baselines only when the file has them (an import never
        # wipes ones typed here)
        for k in ("notes", "baseline_start", "baseline_finish"):
            if it.get(k):
                a[k] = it[k]
        a.setdefault("status", "Not Started")
        a = store.save_record("activity", a)
        ids[it["uid"]] = a
        n += 1
    # links once every activity has its number; imported starts are kept
    # only for activities with no predecessors (else the logic drives)
    for it in items:
        a = store.get("activity", ids[it["uid"]]["_id"])
        lines = []
        for ln in it["links"]:
            p = ids.get(ln["uid"])
            if p:
                lines.append({"id": p["_no"], "type": ln["type"],
                              "lag": ln["lag"]})
        a["preds"] = lines
        if lines and not a.get("actual_start"):
            a["start"] = ""
        store.save_record("activity", a)
    update_dates(store)
    return n


def export_msproject(store, path):
    """Microsoft Project XML (opens in Project; P6 imports it too). Tasks
    in outline order with OutlineLevel / OutlineNumber (the summary rows
    as summary tasks), Notes, Baseline 0 for baselined activities, and
    one project calendar - Monday to Friday, 8-12
    and 13-17 - with the project's holidays as its Exceptions."""
    cpm = cached(store)
    byrow = {r["_id"]: r for r in cpm["rows"]}
    order = [(a, lvl, summ) for a, lvl, summ in
             outline(store.list("activity")) if a["_id"] in byrow]
    uid = {a["_id"]: i + 1 for i, (a, _l, _s) in enumerate(order)}
    NS = "http://schemas.microsoft.com/project"
    ET.register_namespace("", NS)
    P = ET.Element(f"{{{NS}}}Project")

    def sub(el, name, text=None):
        x = ET.SubElement(el, f"{{{NS}}}{name}")
        if text is not None:
            x.text = str(text)
        return x
    sub(P, "Name", store.name)
    sub(P, "ScheduleFromStart", 1)
    if cpm["start"]:
        sub(P, "StartDate", f"{cpm['start']}T08:00:00")
    # The MSPDI schema's Project element is an xs:sequence: CalendarUID
    # comes before DefaultStartTime / MinutesPerDay, and Calendars, Tasks
    # come last. Project's XML import checks that order. Task children
    # below follow the schema's Task sequence too.
    sub(P, "CalendarUID", 1)
    sub(P, "MinutesPerDay", 480)
    sub(P, "MinutesPerWeek", 2400)
    sub(P, "DaysPerMonth", 20)
    cals = sub(P, "Calendars")
    cal = sub(cals, "Calendar")
    sub(cal, "UID", 1)
    sub(cal, "Name", "Standard")
    sub(cal, "IsBaseCalendar", 1)
    sub(cal, "BaseCalendarUID", -1)
    wds = sub(cal, "WeekDays")
    for day in range(1, 8):                 # 1 = Sunday ... 7 = Saturday
        wd = sub(wds, "WeekDay")
        sub(wd, "DayType", day)
        work = 2 <= day <= 6
        sub(wd, "DayWorking", 1 if work else 0)
        if work:
            wt = sub(wd, "WorkingTimes")
            for a, b in (("08:00:00", "12:00:00"), ("13:00:00", "17:00:00")):
                t = sub(wt, "WorkingTime")
                sub(t, "FromTime", a)
                sub(t, "ToTime", b)
    hols = sorted({d for d in (_holiday(h) for h in
                               store.setting("holidays") or ()) if d})
    if hols:
        exs = sub(cal, "Exceptions")
        for d in hols:
            ex = sub(exs, "Exception")
            sub(ex, "EnteredByOccurrences", 0)
            tp = sub(ex, "TimePeriod")
            sub(tp, "FromDate", f"{d}T00:00:00")
            sub(tp, "ToDate", f"{d}T23:59:00")
            sub(ex, "Occurrences", 1)
            sub(ex, "Name", f"Holiday {d:%b %d, %Y}")
            sub(ex, "Type", 1)                  # daily
            sub(ex, "DayWorking", 0)
    tasks = sub(P, "Tasks")
    bcal = Calendar(_dt.date.today(), store.setting("holidays") or ())
    counters = []
    for a, lvl, summ in order:
        r = byrow[a["_id"]]
        del counters[lvl + 1:]
        while len(counters) <= lvl:
            counters.append(0)
        counters[lvl] += 1
        t = sub(tasks, "Task")
        sub(t, "UID", uid[a["_id"]])
        sub(t, "ID", uid[a["_id"]])
        sub(t, "Name", r.get("name") or "")
        sub(t, "Type", 0)
        sub(t, "OutlineNumber", ".".join(map(str, counters)))
        sub(t, "OutlineLevel", lvl + 1)
        sub(t, "Start", f"{r['es']}T08:00:00")
        sub(t, "Finish", f"{r['ef']}T17:00:00")
        sub(t, "Duration", f"PT{r['dur'] * 8}H0M0S")
        sub(t, "DurationFormat", 7)
        sub(t, "Milestone", 1 if r["milestone"] and not summ else 0)
        sub(t, "Summary", 1 if summ else 0)
        sub(t, "PercentComplete", int(_num(r.get("percent"))))
        if r.get("actual_start"):
            sub(t, "ActualStart", f"{r['actual_start']}T08:00:00")
        if r.get("actual_finish"):
            sub(t, "ActualFinish", f"{r['actual_finish']}T17:00:00")
        if r.get("start") and not r["links"] and not summ:
            sub(t, "ConstraintType", 4)              # start no earlier than
            sub(t, "ConstraintDate", f"{r['start']}T08:00:00")
        if r.get("notes"):
            sub(t, "Notes", r["notes"])
        seen = set()
        for p, typ, lag in r["links"]:
            if p not in uid or p in seen:   # one link per predecessor
                continue
            seen.add(p)
            pl = sub(t, "PredecessorLink")
            sub(pl, "PredecessorUID", uid[p])
            sub(pl, "Type", _MSP_CODE.get(typ, "1"))
            sub(pl, "LinkLag", int(lag * 4800))
            sub(pl, "LagFormat", 7)
        # Baseline 0 (Project's "Baseline"): after PredecessorLink /
        # ExtendedAttribute in the Task sequence; inside it Number comes
        # first, then Interim, Start, Finish, Duration, DurationFormat (the
        # order as remembered from mspdi_pj12.xsd, not checked against it).
        bs, bf = _d(r.get("baseline_start")), _d(r.get("baseline_finish"))
        if bs and bf and bf >= bs:
            days = 0 if r["milestone"] and not summ else \
                sum(1 for i in range((bf - bs).days + 1)
                    if bcal.is_work(bs + DAY * i))
            b = sub(t, "Baseline")
            sub(b, "Number", 0)
            sub(b, "Start", f"{bs}T08:00:00")
            sub(b, "Finish", f"{bf}T17:00:00")
            sub(b, "Duration", f"PT{days * 8}H0M0S")
            sub(b, "DurationFormat", 7)
    ET.ElementTree(P).write(path, encoding="utf-8", xml_declaration=True)
    return path
