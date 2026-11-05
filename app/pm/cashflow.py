"""Cash flow: a cost-loaded schedule.

Each cost code's budget is spread over the schedule activities that carry
that cost code, workday by workday; codes no activity carries are spread
evenly over the whole job. That gives the planned cost curve (the
S-curve). Against it:

  actual cost     direct costs and invoices by date
  forecast        actual so far + what's left (forecast at completion -
                  actual) spread over the remaining work in the schedule
  billed          owner pay apps: amount due on each (G702 line 8) in its
                  period
  received        payments recorded on pay apps
  paid out        costs marked paid, by their paid date
  net cash        received - paid out, running

All by calendar month. months(store) -> [row]; a row is
{month "2026-11", planned, actual, forecast, billed, received, paid, and
cum_* running totals}.
"""
import datetime as _dt

from . import cost, schedule


def _m(d):
    return f"{d.year:04d}-{d.month:02d}"


def _f(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _spread(amount, days, into):
    """Add `amount` spread evenly over the dates `days` into {month: x}."""
    if not days or not amount:
        return
    per = amount / len(days)
    for d in days:
        k = _m(d)
        into[k] = into.get(k, 0.0) + per


def _workdays(cal, a, b, memo=None):
    if memo is not None:              # many activities share date ranges
        k = (a, b)
        if k not in memo:
            memo[k] = _workdays(cal, a, b)
        return memo[k]
    out = []
    d = a
    while d <= b:
        if cal.is_work(d):
            out.append(d)
        d += _dt.timedelta(days=1)
    return out or [a]


def months(store, today=None):
    today = today or _dt.date.today()
    cpm = schedule.compute(store)
    cal = cpm["cal"]
    memo = {}                         # (start, end) -> workdays (#18)
    codes = cost.by_code(store)
    rows = cpm["rows"]
    # activities by cost code, with their workdays
    by_code = {}
    for r in rows:
        k = cost.code_key(r.get("cost_code")) if r.get("cost_code") else None
        if k:
            by_code.setdefault(k, []).append(r)
    if rows:
        job = _workdays(cal, cpm["start"], cpm["finish"], memo)
    else:
        job = []
    planned, forecast = {}, {}
    unscheduled = 0.0
    for k, c in codes.items():
        acts = by_code.get(k)
        plan_amt = c["revised"]
        if acts:
            days = [d for r in acts for d in
                    (_workdays(cal, r["es"], r["ef"], memo)
                     if not r["milestone"]
                     else [r["es"]])]
            left = [d for d in days if d >= today]
        elif job:
            days = job
            left = [d for d in job if d >= today]
        else:
            unscheduled += plan_amt
            continue
        _spread(plan_amt, days, planned)
        remaining = max(0.0, c["fac"] - c["actual"])
        if not left:
            # the work was due to finish already: spread what is left over
            # the next month's workdays, not all on one day (#15)
            start = max(today, days[-1])
            left = _workdays(cal, start, start + _dt.timedelta(days=30),
                             memo)
        _spread(remaining, left, forecast)
    actual, paid, billed, received = {}, {}, {}, {}
    for x in store.list("cost"):
        d = schedule._d(x.get("date"))
        if d:
            actual[_m(d)] = actual.get(_m(d), 0.0) + _f(x.get("amount"))
        pd = schedule._d(x.get("paid"))
        if pd:
            net = _f(x.get("amount")) - _f(x.get("retainage"))
            paid[_m(pd)] = paid.get(_m(pd), 0.0) + net
    for a in store.list("payapp"):
        d = schedule._d(a.get("period_to"))
        if d:
            try:
                due = cost.payapp_values(store, a)["g702"]["8"]
            except Exception:
                due = sum(_f(ln.get("this_period")) + _f(ln.get("stored"))
                          for ln in a.get("lines") or [])
            billed[_m(d)] = billed.get(_m(d), 0.0) + due
        rd = schedule._d(a.get("received_on"))
        if rd and a.get("received"):
            received[_m(rd)] = received.get(_m(rd), 0.0) + \
                _f(a.get("received"))
    # forecast = actual for past months, actual so far + spread remaining
    # for this month on
    keys = set(planned) | set(actual) | set(forecast) | set(billed) | \
        set(received) | set(paid)
    if not keys:
        return {"rows": [], "unscheduled": unscheduled}
    first, last = min(keys), max(keys)
    out = []
    y, mo = int(first[:4]), int(first[5:])
    cum = {k: 0.0 for k in ("planned", "actual", "forecast", "billed",
                            "received", "paid")}
    now = _m(today)
    while True:
        k = f"{y:04d}-{mo:02d}"
        row = {"month": k,
               "planned": planned.get(k, 0.0),
               "actual": actual.get(k, 0.0) if k <= now else 0.0,
               "billed": billed.get(k, 0.0),
               "received": received.get(k, 0.0),
               "paid": paid.get(k, 0.0)}
        row["forecast"] = row["actual"] + (forecast.get(k, 0.0)
                                           if k >= now else 0.0)
        for f in cum:
            cum[f] += row[f]
            row["cum_" + f] = round(cum[f], 2)
        row["net_cash"] = round(cum["received"] - cum["paid"], 2)
        for f in ("planned", "actual", "forecast", "billed", "received",
                  "paid"):
            row[f] = round(row[f], 2)
        out.append(row)
        if k >= last:
            break
        mo += 1
        if mo > 12:
            y, mo = y + 1, 1
    return {"rows": out, "unscheduled": round(unscheduled, 2)}


def label(month):
    d = _dt.date(int(month[:4]), int(month[5:]), 1)
    return f"{d:%b %Y}"


COLS = [("month", "Month"), ("planned", "Planned cost"),
        ("cum_planned", "Planned to date"), ("actual", "Actual cost"),
        ("cum_forecast", "Forecast to date"), ("billed", "Billed"),
        ("received", "Received"), ("paid", "Paid out"),
        ("net_cash", "Net cash")]


def table(store, today=None):
    data = months(store, today)
    rows = [[label(r["month"]) if k == "month" else cost.money_fmt(r[k])
             for k, _l in COLS] for r in data["rows"]]
    return [l for _k, l in COLS], rows, data


def xlsx(store, path, today=None):
    from ..acrobat import write_xlsx
    data = months(store, today)
    rows = [[lbl for _k, lbl in COLS]]
    for r in data["rows"]:
        rows.append([label(r["month"]) if k == "month" else r[k]
                     for k, _l in COLS])
    write_xlsx(path, [("Cash Flow", rows)])
    return path


def pdf(store, path, today=None):
    """S-curve chart and the monthly table on 11x17 landscape."""
    import fitz
    data = months(store, today)
    rows = data["rows"]
    W, H, M = 1224, 792, 36
    doc = fitz.open()
    pg = doc.new_page(width=W, height=H)
    pg.insert_text((M, 46), "Cash Flow & Cost Curve", fontsize=18,
                   fontname="hebo")
    pg.insert_text((M, 64), f"{store.name}   ·   printed "
                   f"{_dt.date.today():%b %d, %Y}", fontsize=9,
                   color=(0.45, 0.45, 0.45))
    # chart
    cx0, cy0, cx1, cy1 = M + 50, 90, W - M - 10, 430
    pg.draw_rect(fitz.Rect(cx0, cy0, cx1, cy1), color=(0.8, 0.8, 0.8),
                 width=0.5)
    top = max([1.0] + [max(r["cum_planned"], r["cum_forecast"],
                           r["cum_billed"]) for r in rows])
    n = max(1, len(rows))

    def X(i):
        return cx0 + (cx1 - cx0) * (i + 1) / n

    def Y(v):
        return cy1 - (cy1 - cy0) * v / top
    for k in range(5):
        v = top * k / 4
        pg.draw_line((cx0, Y(v)), (cx1, Y(v)), color=(0.92, 0.92, 0.92),
                     width=0.4)
        pg.insert_text((M - 4, Y(v) + 3), cost.money_fmt(v).split(".")[0],
                       fontsize=7, color=(0.45, 0.45, 0.45))
    series = [("cum_planned", "Planned (cost-loaded schedule)",
               (0.15, 0.4, 0.8), None),
              ("cum_forecast", "Actual + forecast", (0.85, 0.2, 0.2),
               None),
              ("cum_billed", "Billed to owner", (0.1, 0.6, 0.3), [4, 2])]
    for key, name, col, dash in series:
        pts = [fitz.Point(cx0, cy1)] + [fitz.Point(X(i), Y(r[key]))
                                         for i, r in enumerate(rows)]
        if len(pts) > 1:
            pg.draw_polyline(pts, color=col, width=1.6,
                             dashes=f"[{dash[0]} {dash[1]}] 0" if dash
                             else None)
    for i, r in enumerate(rows):
        if n <= 24 or i % 2 == 0:
            pg.insert_text((X(i) - 16, cy1 + 12), label(r["month"])[:3] +
                           " " + r["month"][2:4], fontsize=7)
    lx = cx0
    for key, name, col, _d in series:
        pg.draw_line((lx, cy0 - 8), (lx + 18, cy0 - 8), color=col, width=2)
        pg.insert_text((lx + 22, cy0 - 5), name, fontsize=8)
        lx += 190
    # table
    headers = [lbl for _k, lbl in COLS]
    y = 470
    widths = [90] + [(W - 2 * M - 90) / (len(COLS) - 1)] * (len(COLS) - 1)
    x = M
    for hname, w in zip(headers, widths):
        pg.insert_text((x + 2, y), hname, fontsize=8, fontname="hebo")
        x += w
    pg.draw_line((M, y + 4), (W - M, y + 4), width=0.6)
    y += 16
    for r in rows:
        if y > H - 30:
            pg = doc.new_page(width=W, height=H)
            y = 50
        x = M
        for (k, _l), w in zip(COLS, widths):
            v = label(r["month"]) if k == "month" else cost.money_fmt(r[k])
            if k != "month":
                tw = fitz.get_text_length(v, fontsize=8)
                pg.insert_text((x + w - tw - 6, y), v, fontsize=8,
                               color=(0.8, 0.1, 0.1) if k == "net_cash"
                               and r[k] < 0 else (0, 0, 0))
            else:
                pg.insert_text((x + 2, y), v, fontsize=8)
            x += w
        y += 13
    if data["unscheduled"]:
        pg.insert_text((M, y + 10), "Not on the schedule (no activities "
                       "yet): " + cost.money_fmt(data["unscheduled"]),
                       fontsize=8, color=(0.45, 0.45, 0.45))
    doc.save(path, garbage=3, deflate=True)
    return path
