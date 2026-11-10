"""Owner report pack drawn from the project data (HELD gaps patch G01-G30
on top of the owner report pack, 0.13.13): the facts as of the report
date - weather days by rule and notices, the allowance, granted time,
earned value and the S-curve, billing, retainage and cash flow, the PCO /
exposure log, RFI and submittal aging, long-lead items, manpower against
plan, safety, quality, site activity, permits, risks, meetings - and the
sections the pack module lays out (owner_report_pack). Offline and
rule-based: the executive summary and the owner actions are drafts from
templates that the PM edits before export (rep["summary_text"],
rep["decisions"]); no network, no outside service.

Settings it reads (project settings, typed by the office): contract_finish
(substantial completion), contract_final_completion, ld_per_day,
owner_pays_days, notice_delay_days, weather_allowance {"YYYY-MM": days},
crew_plan {trade: crew}, owner_contingency (amount) or
owner_contingency_pct, allowances [{name, amount, spent}],
sample_settings [setting names that are
placeholders - printed with a [SAMPLE DATA] tag] and sample_notes [text].
No signature or sign-off block and no AIA wording, by design."""
import copy
import re
from collections import OrderedDict
from datetime import date, timedelta

from . import owner_report as orp
from .owner_report import DAY, _day, _num, mdy
from ..dmoney import c2 as _c2
from ..dmoney import half_up as _hu

THR_DEFAULT = 0.5
STOP = {"and", "the", "for", "of", "to", "a", "an", "data", "product",
        "submittal", "submittals", "submit", "approve", "approval", "rev",
        "package", "at", "in", "on"}
OWNER_ROLES = ("Owner",)
OPEN_DELAY = ("Open", "Notice Given", "Analyzed", "Submitted")


# ------------------------------------------------------------- helpers
def md(d):
    d = _day(d)
    return f"{d.month}/{d.day}" if d else ""


def money(v):
    v = _hu(_num(v), 0)                   # whole dollars, $2.50 -> $3
    return f"(${-v:,.0f})" if v < 0 else f"${v:,.0f}"


def _tokens(s):
    return {w for w in re.findall(r"[a-z0-9]+", str(s or "").lower())
            if len(w) >= 3 and w not in STOP}


def _asof(v, rd):
    d = _day(v)
    return bool(d and d <= rd)


def _wd_between(cal, a, b):
    """Workdays from a to b (b counted, a not); negative when b < a."""
    if not a or not b or a == b:
        return 0
    sg = 1 if b > a else -1
    x, y = sorted((a, b))
    n, d = 0, x
    while d < y:
        d += DAY
        n += 1 if cal.is_work(d) else 0
    return sg * n


def _add_wd(cal, d, n):
    while n > 0:
        d += DAY
        if cal.is_work(d):
            n -= 1
    return d


def _month_end(d):
    nxt = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    return nxt - DAY


def _samples(store):
    return [str(x) for x in (store.setting("sample_settings") or [])]


def _rfi_sent(r):
    return _day(r.get("sent")) or _day(r.get("date")) or \
        _day(r.get("_created"))


def report_date(rep):
    return _day(rep.get("week_ending") or rep.get("date")) or date.today()


def _trade_of(m):
    return (m.get("trade") or "").split(" - ")[0].strip()


def contract_terms(store, ntp):
    sc = _day(store.setting("contract_finish"))
    if not sc and _num(store.setting("contract_days")):
        sc = ntp + timedelta(days=int(_num(store.setting("contract_days")))
                             - 1)
    return {"sc": sc, "fc": _day(store.setting("contract_final_completion")),
            "ld": _num(store.setting("ld_per_day")),
            "owner_pays_days": int(_num(store.setting("owner_pays_days"),
                                        30)),
            "notice_days": int(_num(store.setting("notice_delay_days")))}


def _milestone(rows, word):
    ms = [r for r in rows if r.get("milestone") and not r.get("summary") and
          word in (r.get("name") or "").lower()]
    return ms[-1] if ms else None


# ------------------------------------------------------------- the facts
def facts(store, rep):
    """Everything the pack prints, computed from the project records as of
    the report date (G01): records dated later are left out and listed in
    "left_out"."""
    from . import schedule
    RD = report_date(rep)
    WK0, _we = orp.week_range(rep)
    NTP = orp.project_start(store, rep) or RD
    F = {"rd": RD, "wk0": WK0, "ntp": NTP, "left_out": [],
         "samples": _samples(store)}
    CT = contract_terms(store, NTP)
    F["terms"] = CT
    cpm = schedule.cached(store)
    cal = cpm["cal"]
    F["cal"] = cal
    F["dd"] = schedule.data_date(store)
    rows = [r for r in cpm["rows"] if r.get("_no") and not r.get("summary")]
    ROWS = {r["_no"]: r for r in rows}
    byid = {r["_id"]: r for r in rows}
    succ = {}
    for r in rows:
        for p in r.get("pred_ids") or []:
            succ.setdefault(p, []).append(r)
    F["rows"] = ROWS
    sc_row = _milestone(rows, "substantial")
    fc_row = _milestone(rows, "final completion")
    if sc_row is None and rows:
        sc_row = max(rows, key=lambda r: r["ef"])
    sc_c = CT["sc"] or (sc_row["ef"] if sc_row else RD)
    F["schedule"] = sch = {"sc": sc_row, "fc": fc_row, "sc_contract": sc_c,
                           "fc_contract": CT["fc"]}
    if sc_row:
        sch["var"] = schedule.variance(sc_row, cal) or 0
        sch["margin_wd"] = _wd_between(cal, sc_row["ef"], sc_c)
        sch["margin_cd"] = (sc_c - sc_row["ef"]).days
    if fc_row and CT["fc"]:
        sch["fc_var"] = schedule.variance(fc_row, cal) or 0
        sch["fc_margin_wd"] = _wd_between(cal, fc_row["ef"], CT["fc"])
        sch["fc_margin_cd"] = (CT["fc"] - fc_row["ef"]).days
    sch["contract_cd"] = (sc_c - NTP).days + 1
    sch["used_cd"] = (RD - NTP).days + 1
    sch["elapsed_pct"] = round(100 * sch["used_cd"] / max(1, sch["contract_cd"]), 1)
    sch["critical"] = sorted([r for r in rows if r.get("critical") and
                              r.get("status") != "Complete"],
                             key=lambda r: (r["es"], r["_no"]))
    late = [(schedule.variance(r, cal) or 0, r) for r in sch["critical"]
            if not r.get("milestone")]
    late = [x for x in late if x[0] > 0]
    sch["driver"] = max(late, key=lambda x: (x[0], -x[1]["es"].toordinal()))[1] \
        if late else None
    sch["milestones"] = sorted([r for r in rows if r.get("milestone")],
                               key=lambda r: (r["ef"], r["_no"]))
    # next week (G10) and the 3-week look-ahead
    nw0 = RD + DAY
    while nw0.weekday() != 0:
        nw0 += DAY
    nw1 = nw0 + timedelta(days=4)
    F["next_week_range"] = (nw0, nw1)
    F["next_week"] = sorted([r for r in rows if r.get("status") != "Complete"
                             and r["es"] <= nw1 and r["ef"] >= nw0],
                            key=lambda r: (r["es"], r["_no"]))
    F["holidays_next"] = [h for h in (_day(x) for x in
                                      store.setting("holidays") or [])
                          if h and nw0 <= h <= nw1]

    # ---- cost loading: SOV lines -> activities by the person responsible
    SOV = sorted(store.list("contract"),
                 key=lambda r: (_num(r.get("item"), 1e9), r.get("_no") or ""))
    val = OrderedDict((r.get("description") or "", _num(r.get("scheduled")))
                      for r in SOV)
    CONTRACT = sum(val.values())
    F["contract_sum"] = CONTRACT
    F["sov"] = SOV
    who = {}
    for m in store.list("member"):
        if m.get("trade") in val:
            who[m.get("name")] = m["trade"]
    for c in store.list("commitment"):
        for ln in c.get("lines") or []:
            if ln.get("description") in val and c.get("vendor"):
                who[c["vendor"]] = ln["description"]
                break
    acts = [r for r in rows if who.get(r.get("responsible")) and
            r.get("area") != "Procurement"]
    wsum = {}
    for r in acts:
        t = who[r["responsible"]]
        wsum[t] = wsum.get(t, 0) + max(1, r["dur"])
    linear = [k for k in val if k not in wsum]

    def weight(r):
        t = who[r["responsible"]]
        return val[t] * max(1, r["dur"]) / wsum[t]

    def spread(a, b, amount, upto):
        days = [a + timedelta(days=i) for i in range((b - a).days + 1)]
        days = [d for d in days if cal.is_work(d)] or [a]
        return amount * sum(1 for d in days if d <= upto) / len(days)

    def planned(upto, mode="baseline"):
        v = sum(spread(NTP, sc_c, val[k], upto) for k in linear)
        for r in acts:
            if mode == "baseline":
                a, b = _day(r.get("baseline_start")), \
                    _day(r.get("baseline_finish"))
            else:
                a, b = r["es"], r["ef"]
            if a and b:
                v += spread(a, b, weight(r), upto)
        return v
    earned = sum(weight(r) * (100 if r.get("status") == "Complete" else
                              _num(r.get("percent"))) / 100 for r in acts)
    earned += sum(spread(NTP, sc_c, val[k], RD) for k in linear)
    pv = planned(RD)
    months, m = [], _month_end(NTP)
    while m <= _month_end(sc_c):
        months.append(m)
        m = _month_end(m + DAY)
    C = max(CONTRACT, 1)
    F["earned"] = {"ev": earned, "pv": pv,
                   "pct": round(100 * earned / C, 1),
                   "planned_pct": round(100 * pv / C, 1),
                   "linear": linear, "months": months,
                   "curve": [(mm, planned(mm) / C * 100,
                              planned(mm, "forecast") / C * 100)
                             for mm in months]}

    # ---- billing (G07)
    PAS = sorted(store.list("payapp"), key=lambda p: str(p.get("period_to")))

    def gross(p):
        return sum(_num(ln.get("this_period")) + _num(ln.get("stored"))
                   for ln in p.get("lines") or [])
    certified = [p for p in PAS if p.get("status") in ("Certified", "Paid")
                 and _asof(p.get("period_to"), RD)]
    for p in PAS:
        if p.get("status") in ("Certified", "Paid") and \
                not _asof(p.get("period_to"), RD):
            F["left_out"].append(f"Pay App #{p.get('_no')} certified for "
                                 f"{mdy(p.get('period_to'))}")
    billed = sum(gross(p) for p in certified)
    ret = _num((PAS[0] if PAS else {}).get("retainage_work"), 10) / 100
    nxt = [p for p in PAS if p not in certified][:3]
    cash = []
    for p in nxt:
        g = gross(p)
        co = sum(_num(ln.get("this_period")) for ln in p.get("lines") or []
                 if str(ln.get("item") or "").upper().startswith("CO"))
        per = _day(p.get("period_to"))
        cash.append({"no": p.get("_no"), "period": per, "gross": g,
                     "ret": g * ret, "net": g * (1 - ret), "co": co,
                     "status": p.get("status") or "",
                     "pay": per + timedelta(days=CT["owner_pays_days"])
                     if per else None})
    F["billing"] = {"billed": billed, "retainage_rate": ret,
                    "retainage_held": round(billed * ret), "cash": cash,
                    "next_gross": cash[0]["gross"] if cash else 0,
                    "next": nxt[0] if nxt else None, "payapps": PAS,
                    "gross": gross}
    F["_who"] = who
    F["_succ"] = succ
    F["_byid"] = byid
    _f_changes(store, F)
    _f_dailies(store, rep, F)
    _f_weather(store, rep, F)
    _f_logs(store, F)
    _f_people(store, F)
    _f_risks(store, F)
    _f_rag(store, rep, F)
    return F


# ---- changes (G08)
def ce_amount(e):
    if e.get("price") not in (None, ""):
        return _num(e.get("price"))
    return sum(_num(ln.get("cost")) * (1 + _num(ln.get("markup")) / 100)
               for ln in e.get("lines") or [])


def _f_changes(store, F):
    RD, cal = F["rd"], F["cal"]
    rfis = {r["_id"]: r for r in store.list("rfi")}
    events = sorted(store.list("event"), key=lambda e: e.get("_no") or "")
    approved = [e for e in events if e.get("status") == "Approved" and
                _asof(e.get("approved"), RD)]
    pcos, pending, out = [], [], []
    for e in events:
        if e.get("approved") and not _asof(e.get("approved"), RD):
            F["left_out"].append(f"{e.get('_no')} approval "
                                 f"({mdy(e.get('approved'))})")
        if e in approved or e.get("status") in ("Rejected", "Void"):
            continue
        r = rfis.get(e.get("rfi"))
        sent = _rfi_sent(r) if r else None
        if _asof(e.get("submitted"), RD):
            pending.append(e)
        elif r and sent and sent <= RD:
            pcos.append(e)
        else:
            out.append(e)
            if e.get("submitted"):
                F["left_out"].append(f"{e.get('_no')} sent to the owner "
                                     f"{mdy(e.get('submitted'))}")
    gc_line = next((k for k in (x.get("description") or "" for x in F["sov"])
                    if "general conditions" in k.lower()), None)
    gc_val = sum(_num(x.get("scheduled")) for x in F["sov"]
                 if x.get("description") == gc_line)
    sc_c = F["schedule"]["sc_contract"]
    F["gc_per_wd"] = gc_val / max(1, _wd_between(cal, F["ntp"] - DAY, sc_c))
    P = []
    for i, e in enumerate(pcos, 1):
        r = rfis.get(e.get("rfi")) or {}
        amt = ce_amount(e)
        P.append({"no": f"PCO-{i:03d}", "ce": e.get("_no"),
                  "title": e.get("title") or "", "amount": amt,
                  "days": int(_num(e.get("days"))), "rfi": r.get("_no"),
                  "rfi_open": not _asof(r.get("answered"), RD),
                  "status": "Being priced" if amt else "Not priced yet",
                  "due": _day(e.get("owner_due")) or _add_wd(cal, RD, 2),
                  "reason": e.get("reason") or ""})
    linked = {e.get("rfi") for e in events} | \
        {r["_id"] for r in rfis.values() if r.get("change_event")}
    tbd = []
    for r in sorted(rfis.values(), key=lambda r: r.get("_no") or ""):
        sent = _rfi_sent(r)
        if not sent or sent > RD or _asof(r.get("answered"), RD):
            continue
        if r["_id"] in linked:
            continue
        if (r.get("cost_impact") or "") in ("Yes", "Undetermined"):
            tbd.append({"rfi": r.get("_no"), "title": r.get("subject") or "",
                        "cost": r.get("cost_impact")})
    appr = sum(ce_amount(e) for e in approved)
    F["changes"] = {"approved": appr, "approved_list": approved,
                    "revised": F["contract_sum"] + appr, "pcos": P,
                    "pending": [{"ce": e.get("_no"), "title": e.get("title"),
                                 "amount": ce_amount(e),
                                 "days": int(_num(e.get("days"))),
                                 "sent": _day(e.get("submitted"))}
                                for e in pending],
                    "tbd": tbd, "exposure": sum(p["amount"] for p in P),
                    "pending_amount": sum(ce_amount(e) for e in pending)}
    c = store.setting("owner_contingency")
    amt = _num(c) if c not in (None, "") else \
        F["contract_sum"] * _num(store.setting("owner_contingency_pct")) / 100
    if amt:
        F["contingency"] = {"amount": round(amt), "used": appr,
                            "potential": F["changes"]["exposure"],
                            "remaining": round(amt - appr -
                                               F["changes"]["exposure"])}
    else:
        F["contingency"] = None
    F["allowances"] = []
    for a in store.setting("allowances") or ():
        if not isinstance(a, dict) or not str(a.get("name") or "").strip():
            continue
        amt, spent = (round(_num(str(a.get(k) or 0).replace(",", "")
                                 .replace("$", "").strip()))
                      for k in ("amount", "spent"))
        F["allowances"].append({"name": str(a["name"]).strip(), "amount": amt,
                                "spent": spent, "remaining": amt - spent})


def pco_from_rfi(store, rfi):
    """G08: a change event (a PCO on the owner report) opened from an RFI,
    linked both ways; not priced yet (the PM fills the lines)."""
    ev = store.save_record("event", {
        "title": f"{rfi.get('subject') or 'RFI'} ({rfi.get('_no')})",
        "reason": "Unforeseen Condition", "status": "Open",
        "rfi": rfi["_id"], "lines": [],
        "days": int(_num(rfi.get("days_impact"))),
        "description": f"Opened from {rfi.get('_no')}: "
                       f"{rfi.get('question') or ''}".strip()})
    store.save_record("rfi", dict(store.get("rfi", rfi["_id"]),
                                  change_event=ev["_id"]))
    return ev


# ---- daily logs: manpower, safety, site activity (G12 G13 G14)
def _f_dailies(store, rep, F):
    RD, NTP, cal = F["rd"], F["ntp"], F["cal"]
    a, b = orp.week_range(rep)
    logs = sorted([d for d in store.list("daily")
                   if _day(d.get("date")) and NTP <= _day(d["date"]) <= RD],
                  key=lambda d: d["date"])
    week = [d for d in logs if a <= _day(d["date"]) <= b]
    later = [d for d in store.list("daily") if _day(d.get("date")) and
             _day(d["date"]) > RD]
    if later:
        F["left_out"].append(f"{len(later)} Daily Log(s) dated after "
                             f"{mdy(RD)}")
    F["logs_jtd"], F["logs_week"] = logs, week

    def mh(ds):
        return sum(_num(m.get("workers")) * _num(m.get("hours"))
                   for d in ds for m in d.get("manpower") or [])
    plan = store.setting("crew_plan") or {}
    rows = OrderedDict()
    for d in week:
        for m in d.get("manpower") or []:
            k = (m.get("company") or "", m.get("trade") or "")
            r = rows.setdefault(k, {"company": k[0], "trade": k[1],
                                    "by_day": {}, "worker_days": 0})
            n = int(_num(m.get("workers")))
            r["by_day"][d["date"]] = r["by_day"].get(d["date"], 0) + n
            r["worker_days"] += n
    wdays = sum(1 for i in range((b - a).days + 1)
                if cal.is_work(a + timedelta(days=i))) or 1
    for r in rows.values():
        r["avg"] = r["worker_days"] / wdays
        r["plan"] = plan.get(r["trade"])
    F["manpower"] = {"rows": list(rows.values()), "workdays": wdays,
                     "days_logged": len(week),
                     "worker_days": sum(r["worker_days"]
                                        for r in rows.values()),
                     "manhours_week": mh(week), "manhours_jtd": mh(logs),
                     "plan_total": sum(_num(v) for v in plan.values()),
                     "plan_sample": "crew_plan" in F["samples"]}

    def recordable(d):
        t = (d.get("safety") or "").lower()
        if re.search(r"\bno (recordable|injur|incident)", t):
            return 0
        return 1 if re.search(r"recordable|injur|lost[- ]time", t) else 0
    rec = sum(recordable(d) for d in logs)

    def lost_time(d):
        t = (d.get("safety") or "").lower()
        if re.search(r"\bno (lost[- ]time|injur|incident)", t):
            return 0
        return 1 if re.search(r"lost[- ]time", t) else 0
    obs = []
    for o in store.list("observation"):
        if (o.get("status") or "") == "Closed" or \
                (o.get("type") or "Safety") not in ("Safety", ""):
            continue
        when = _day(o.get("date")) or _day(o.get("due"))
        if when and when > RD:
            continue
        obs.append(o)
    tb = lambda ds: sum(1 for d in ds if "toolbox" in  # noqa: E731
                        (d.get("safety") or "").lower())
    nm = sum(1 for d in logs if "near miss" in (d.get("safety") or "").lower()
             and not re.search(r"no near miss", (d.get("safety") or "").lower()))
    mhj = F["manpower"]["manhours_jtd"]
    F["safety"] = {"recordables": rec, "lost_time": sum(lost_time(d)
                                                       for d in logs),
                   "observations_open": len(obs), "observations": obs,
                   "toolbox_week": tb(week),
                   "toolbox_jtd": tb(logs), "near_misses": nm,
                   "trir": _c2(rec * 200000 / mhj) if mhj else 0.0}
    insp, equip, deliv, vis = [], [], [], []
    for d in week:
        no = orp._log_no(d)
        for ln in (d.get("inspections_note") or "").splitlines():
            if ln.strip():
                insp.append({"date": _day(d["date"]), "note": ln.strip(),
                             "failed": bool(re.search(r"\bfail", ln, re.I)),
                             "src": no, "by": ""})
        for x in d.get("equipment") or []:
            equip.append({"date": _day(d["date"]), "item": x.get("item") or "",
                          "hours": x.get("hours"), "idle": x.get("idle"),
                          "notes": x.get("notes") or "", "src": no})
        for x in d.get("deliveries") or []:
            deliv.append({"date": _day(d["date"]),
                          "what": x.get("contents") or x.get("item") or "",
                          "qty": x.get("qty") or "",
                          "from": x.get("supplier") or x.get("vendor") or "",
                          "src": no})
        for x in d.get("visitors") or []:
            vis.append({"date": _day(d["date"]), "name": x.get("name") or "",
                        "company": x.get("company") or "",
                        "purpose": x.get("purpose") or "", "src": no})
    for x in sorted(store.list("inspection"), key=lambda x: str(x.get("date"))):
        dd = _day(x.get("date"))
        if not dd or not (a <= dd <= b):
            continue
        st = x.get("status") or ""
        insp.append({"date": dd, "note": f"{x.get('title') or ''}"
                     + (f" - {st}" if st else ""),
                     "failed": st == "Failed", "src": x.get("_no") or "",
                     "by": x.get("inspector") or ""})
    insp.sort(key=lambda x: x["date"])
    F["site"] = {"inspections": insp, "equipment": equip,
                 "deliveries": deliv, "visitors": vis}
    F["failed"] = [x for x in insp if x["failed"]]
    pun = []
    for p in store.list("punch"):
        when = _day(p.get("date")) or _day(p.get("opened")) or \
            _day(p.get("due"))
        if p.get("status") in ("Closed", "Complete", "Done"):
            continue
        if when and when <= RD:
            pun.append(p)
        elif when:
            F["left_out"].append(f"punch item {p.get('_no') or ''} dated "
                                 f"{mdy(when)}".replace("  ", " "))
    F["punch_open"] = len(pun)
    F["punch"] = pun


# ---- weather (G02 G03)
def _f_weather(store, rep, F):
    RD, NTP, cal = F["rd"], F["ntp"], F["cal"]
    a, b = orp.week_range(rep)
    w = rep.get("weather") or {}
    thr = _num(w.get("threshold_in"), THR_DEFAULT) or THR_DEFAULT
    typed = {str(d.get("date"))[:10]: d for d in w.get("days") or []}
    logs = {str(d.get("date"))[:10]: d for d in store.list("daily")}
    notices = orp.weather_notices(store, RD)
    by_notice = orp.uses_delay_log(store)
    rows = []
    d = NTP
    while d <= RD:
        iso = d.isoformat()
        dl, td = logs.get(iso), typed.get(iso) or {}
        if dl:
            wx = dl.get("weather") or {}
            rain = _num(wx.get("precip"), None)
            if rain is None:
                rain = _num(td.get("rain_in"))
            lost = sum(_num(x.get("hours")) for x in dl.get("delays") or []
                       if (x.get("cause") or "") == "Weather")
            trades = sorted({_trade_of(m) for m in dl.get("manpower") or []
                             if _trade_of(m) and
                             _trade_of(m) != "Supervision"}) if lost else []
            row = {"high": str(wx.get("high") or ""),
                   "low": str(wx.get("low") or ""),
                   "sky": wx.get("sky") or "", "rain": rain, "lost": lost,
                   "trades": ", ".join(trades), "src": orp._log_no(dl),
                   "typed": False}
        else:
            row = {"high": str(td.get("high") or ""),
                   "low": str(td.get("low") or ""),
                   "sky": td.get("sky") or "",
                   "rain": _num(td.get("rain_in")), "lost": 0.0,
                   "trades": "", "typed": bool(td),
                   "src": "typed in the report" if td else "no log"}
        work = cal.is_work(d)
        adverse = bool(work and (_c2(row["rain"]) >= _c2(thr) or
                                 row["lost"] >= orp.ADVERSE_HOURS))
        if td.get("edited") and "tracked" in td:
            adverse = bool(td["tracked"]) and work
        claimed = iso in notices if by_notice else bool(td.get("claimed"))
        if td.get("claim_edited") and "claimed" in td:
            claimed = bool(td["claimed"])
        row.update(date=d, workday=work, adverse=adverse, claimed=claimed,
                   claim_ref=notices.get(iso, "") if claimed else "",
                   week=a <= d <= b)
        rows.append(row)
        d += DAY
    wk = [r for r in rows if r["week"] and r["workday"]]
    allow = store.setting("weather_allowance") or {}
    al, run = [], 0
    sc_c = F["schedule"]["sc_contract"]
    m = date(NTP.year, NTP.month, 1)
    while m <= sc_c:
        key = f"{m.year:04d}-{m.month:02d}"
        started = m <= RD
        adv = sum(1 for r in rows if r["adverse"] and
                  r["date"].strftime("%Y-%m") == key)
        allowed = allow.get(key)
        exc = max(0, adv - int(_num(allowed))) if started and \
            allowed is not None else 0
        run += exc
        al.append({"month": key, "allowed": allowed, "adverse":
                   adv if started else None, "excess": exc if started
                   else None, "running": run if started else None,
                   "to_date": started and _month_end(m) > RD})
        m = _month_end(m) + DAY
    month_key = RD.strftime("%Y-%m")
    F["weather"] = {
        "threshold": thr, "rows": rows,
        "rain_week": _c2(sum(r["rain"] for r in wk)),
        "rain_jtd": _c2(sum(r["rain"] for r in rows)),
        "lost_week": sum(r["lost"] for r in wk),
        "lost_jtd": sum(r["lost"] for r in rows),
        "adverse_week": sum(1 for r in wk if r["adverse"]),
        "adverse_jtd": sum(1 for r in rows if r["adverse"]),
        "adverse_month": sum(1 for r in rows if r["adverse"] and
                             r["date"].strftime("%Y-%m") == month_key),
        "claimed": sum(1 for r in rows if r["claimed"]),
        "claimed_week": sum(1 for r in rows if r["claimed"] and r["week"]),
        "granted": orp.granted_days(store, RD, "Weather"),
        "allowance": al, "month": month_key,
        "month_allowance": allow.get(month_key),
        "excusable": run,
        "allow_sample": "weather_allowance" in F["samples"],
        "unclaimed_adverse": [r for r in rows if r["adverse"] and
                              not r["claimed"]]}
    F["delays"] = []
    for x in sorted(store.list("delay"), key=lambda x: x.get("_no") or ""):
        nd = _day(x.get("notice_date"))
        if nd and nd > RD:
            F["left_out"].append(f"{x.get('_no')} (notice "
                                 f"{mdy(nd)})")
            continue
        if not nd and not _asof(x.get("event_start"), RD):
            continue
        F["delays"].append(x)


# ---- RFIs, submittals, long-lead (G16 G17)
def _company(store, name):
    m = next((m for m in store.list("member") if m.get("name") == name),
             None)
    return (m or {}).get("company") or name or ""


def _role(store, name):
    m = next((m for m in store.list("member") if m.get("name") == name),
             None)
    return (m or {}).get("role") or ""


def _names(v):
    if isinstance(v, (list, tuple)):
        return [str(x) for x in v if x]
    return [x.strip() for x in str(v or "").split(",") if x.strip()]


def _f_logs(store, F):
    RD, cal, ROWS = F["rd"], F["cal"], F["rows"]
    out = []
    for r in sorted(store.list("rfi"), key=lambda r: r.get("_no") or ""):
        sent = _rfi_sent(r)
        if sent and sent > RD:
            F["left_out"].append(f"{r.get('_no')} (sent {mdy(sent)})")
            continue
        ans = _day(r.get("answered"))
        if ans and ans > RD:
            F["left_out"].append(f"{r.get('_no')} answer ({mdy(ans)})")
        op = not (ans and ans <= RD)
        to = _names(r.get("to"))
        bic = ", ".join(f"{n} ({_role(store, n)})" if _role(store, n) else n
                        for n in to) if op else "-"
        due = _day(r.get("due"))
        out.append({"no": r.get("_no"), "subject": r.get("subject") or "",
                    "sent": sent, "due": due, "open": op, "bic": bic,
                    "days_open": (RD - sent).days if sent and op else None,
                    "overdue": bool(op and due and due < RD),
                    "answered": ans if not op else None,
                    "cost": r.get("cost_impact") or "",
                    "sched": r.get("schedule_impact") or "",
                    "status": "Open" if op else "Answered", "_id": r["_id"]})
    F["rfis"] = out
    F["rfis_open"] = sum(1 for r in out if r["open"])
    # submit activities: Procurement work whose name says submit/submittal
    subs = [r for r in ROWS.values() if r.get("area") == "Procurement" and
            re.search(r"submit", r.get("name") or "", re.I)]
    trans = [t for t in store.list("transmittal")]
    S, used = [], set()
    for sb in sorted(store.list("submittal"), key=lambda x: x.get("_no") or ""):
        tk = _tokens(sb.get("title")) | _tokens(sb.get("spec_title"))
        best = max(subs, key=lambda r: (len(tk & _tokens(r.get("name"))),
                                        -int(re.sub(r"\D", "", r["_no"]) or 0)),
                   default=None)
        act = best if best and tk & _tokens(best.get("name")) else None
        if act:
            used.add(act["_no"])
        steps = sb.get("steps") or []
        sent = min([_day(x.get("sent")) for x in steps if
                    _asof(x.get("sent"), RD)] or [None]) or \
            (_day(sb.get("submitted")) if _asof(sb.get("submitted"), RD)
             else None)
        back = _day(sb.get("returned")) if _asof(sb.get("returned"), RD) \
            else None
        tr = next((t for t in sorted(trans, key=lambda t: str(t.get("sent")))
                   if len(tk & (_tokens(t.get("subject")) | _tokens(
                       " ".join(i.get("description") or ""
                                for i in t.get("items") or [])))) >= 2), None)
        if back:
            st, bic = f"Returned {mdy(back)}", "-"
        elif sent:
            st = f"With the reviewer since {mdy(sent)}"
            bic = ", ".join(_names(sb.get("reviewer"))) or "Architect"
        else:
            st = "Not yet submitted"
            if tr and _day(tr.get("sent")) and _day(tr["sent"]) > RD:
                st = (f"In preparation by sub (transmittal {tr.get('_no')} "
                      f"dated {mdy(tr['sent'])})")
            bic = _company(store, act.get("responsible")) if act else \
                (sb.get("sub") or "")
        due = _day(act.get("baseline_finish")) if act else None
        S.append({"no": sb.get("_no"), "title": sb.get("title") or "",
                  "activity": act["_no"] if act else "", "status": st,
                  "bic": bic, "due": due,
                  "late_wd": _wd_between(cal, due, RD) if due and due < RD
                  and not sent else 0,
                  "forecast": act["ef"] if act else None,
                  "float": act["float"] if act else None,
                  "critical": bool(act and act.get("critical")),
                  "need": _day(sb.get("required_on_site")),
                  "lead": sb.get("lead_days"), "sent": sent,
                  "transmittal": tr})
    for r in sorted(subs, key=lambda r: r["_no"]):
        if r["_no"] in used or r.get("status") == "Complete":
            continue
        due = _day(r.get("baseline_finish"))
        S.append({"no": "-", "title": r.get("name"), "activity": r["_no"],
                  "status": "Not in the submittal log",
                  "bic": _company(store, r.get("responsible")), "due": due,
                  "late_wd": _wd_between(cal, due, RD) if due and due < RD
                  else 0, "forecast": r["ef"], "float": r["float"],
                  "critical": bool(r.get("critical")), "need": None,
                  "lead": None, "sent": None, "transmittal": None,
                  "unlogged": True})
    F["submittals"] = S
    F["subs_due_not_sent"] = sum(1 for x in S if not x["sent"] and
                                 x["status"] != "Returned" and x["due"] and
                                 x["due"] <= RD)
    # long lead: a submit step with a fabrication / lead-time step after it
    succ = F["_succ"]
    LL = []
    for sa in sorted(subs, key=lambda r: r["_no"]):
        fab = next((r for r in sorted(succ.get(sa["_id"], []),
                                      key=lambda r: r["_no"])
                    if r.get("area") == "Procurement" and
                    not re.search(r"submit", r.get("name") or "", re.I)),
                   None)
        if fab is None:
            if not re.search(r"\bfab|lead", sa.get("name") or "", re.I):
                continue
            fab = sa
        need = sorted([r for r in succ.get(fab["_id"], [])
                       if r.get("area") != "Procurement"],
                      key=lambda r: (r["es"], r["_no"]))
        if not need:
            continue
        na = need[0]
        # the PM's own name for the item (activity field "long_lead_label"
        # on the submit, fabricate or install step), else the install step
        label = next((str(r.get("long_lead_label")).strip()
                      for r in (sa, fab, na)
                      if str(r.get("long_lead_label") or "").strip()), "")
        LL.append({"item": label or na.get("name") or "",
                   "submit": sa["_no"],
                   "fabricate": fab["_no"], "install": na["_no"],
                   "sub_bl": _day(sa.get("baseline_finish")),
                   "sub_fc": sa["ef"], "ship_fc": fab["ef"],
                   "need": na["es"],
                   "margin": int(_wd_between(F["cal"], fab["ef"], na["es"])),
                   "status": sa.get("status") or "Submittal not started",
                   "critical": bool(fab.get("critical"))})
    F["long_lead"] = LL


# ---- people, meetings, permits, logistics, distribution (G15 G21 G27)
def _f_people(store, F):
    RD = F["rd"]
    ms = sorted([m for m in store.list("meeting") if _day(m.get("date"))],
                key=lambda m: m["date"])
    past = [m for m in ms if _day(m["date"]) <= RD]
    fut = [m for m in ms if _day(m["date"]) > RD]
    last = past[-1] if past else {}
    F["meetings"] = {"present": [
        f"{p.get('name')}" + (f" ({p.get('company')})" if p.get("company")
                              else "")
        for p in last.get("attendees") or []
        if str(p.get("present", "Yes")).lower() in ("yes", "true", "1")],
                     "last": past[-1] if past else None,
                     "next": fut[0] if fut else None,
                     "open_topics": [t for m in past[-1:]
                                     for t in m.get("topics") or []
                                     if (t.get("status") or "Open") != "Closed"]}
    try:
        permits = store.list("permit")
    except Exception:                                   # noqa: BLE001
        permits = []
    F["permits"] = sorted(permits, key=lambda p: p.get("_no") or "")
    F["issues"] = [i for i in store.list("issue")
                   if (i.get("status") or "Open") != "Closed"]
    F["members"] = store.list("member")


def _f_risks(store, F):
    R = []
    ch = F["changes"]
    for p in ch["pcos"]:
        R.append({"risk": f"Potential change {p['no']}: {p['title']}",
                  "impact": (money(p["amount"]) if p["amount"] else
                             "not priced") + f", {p['days']} workday(s)",
                  "likelihood": "High" if p["amount"] else "Medium",
                  "action": "Owner decision" + (f" by {mdy(p['due'])}"
                                                if p["due"] else ""),
                  "due": p["due"]})
    for t in ch["tbd"]:
        R.append({"risk": f"{t['rfi']} {t['title']} - cost impact "
                          f"{t['cost'].lower()}", "impact": "not priced",
                  "likelihood": "Medium", "action": "Price it once the "
                  "answer is in; open a PCO from the RFI", "due": None})
    for x in F["submittals"]:
        if x["critical"] and not x["sent"]:
            R.append({"risk": f"{x['title']} not submitted - on the "
                              "critical path",
                      "impact": "each late day moves the forecast",
                      "likelihood": "High", "action": f"{x['bic']} to "
                      "submit; fast review", "due": x["due"]})
    acts = {}
    for r in F["rows"].values():
        if r.get("status") != "Complete" and r.get("responsible"):
            acts.setdefault(r["responsible"], []).append(r)
    for c in store.list("commitment"):
        exp = _day(c.get("insurance_expires"))
        mine = acts.get(c.get("vendor")) or []
        if exp and mine and exp < max(r["ef"] for r in mine):
            R.append({"risk": f"{_company(store, c.get('vendor'))} insurance "
                              f"certificate expires {mdy(exp)}, before its "
                              "work is done",
                      "impact": "work could stop until renewed",
                      "likelihood": "Medium", "action": "Get the renewed "
                      "certificate 30 days before expiry",
                      "due": exp - timedelta(days=30)})
    for i in F["issues"]:
        R.append({"risk": f"{i.get('_no')} {i.get('title')}",
                  "impact": "open issue", "likelihood": "Medium",
                  "action": f"{i.get('assignee') or 'Team'} to resolve",
                  "due": _day(i.get("due"))})
    w = F["weather"]
    if w["month_allowance"] is not None and \
            w["adverse_month"] >= int(_num(w["month_allowance"])):
        R.append({"risk": "Weather: adverse days at or over the month's "
                          "allowance", "impact": "time extension request "
                  "possible", "likelihood": "Medium", "action":
                  "Keep notices current on the Delay Log", "due": None})
    F["risks"] = R


def _f_rag(store, rep, F):
    sch, ch, w, s = F["schedule"], F["changes"], F["weather"], F["safety"]
    C = max(F["contract_sum"], 1)
    sc = sch.get("sc")
    G = OrderedDict()
    if sc:
        code = "R" if sc["ef"] > sch["sc_contract"] else \
            "Y" if sch.get("var", 0) > 5 else "G"
        G["Schedule"] = (code, f"Forecast substantial completion "
                         f"{mdy(sc['ef'])}: {_ahead(sch.get('var', 0), 'baseline')}, "
                         f"{_ahead(-sch.get('margin_wd', 0), 'the contract date')} "
                         f"{mdy(sch['sc_contract'])}.")
    else:
        G["Schedule"] = ("Y", "No substantial completion milestone in the "
                         "schedule.")
    exp = ch["exposure"]
    G["Cost"] = ("R" if exp > 0.05 * C else "Y" if exp > 0.005 * C else "G",
                 f"Contract {money(ch['revised'])}"
                 f"{' unchanged' if not ch['approved'] else ''}. "
                 f"{len(ch['pcos'])} potential change(s): {money(exp)} "
                 f"({_c2(exp / C * 100):.2f}% of contract).")
    G["Safety"] = ("G" if s["recordables"] == 0 else "R",
                   f"{s['recordables']} recordable(s). "
                   f"{F['manpower']['manhours_jtd']:,.0f} man-hours to date. "
                   f"TRIR {_c2(s['trir']):.2f}.")
    fl = F["failed"]
    G["Quality"] = ("Y" if fl else "G",
                    (f"{fl[0]['note']} ({md(fl[0]['date'])})" if fl else
                     "No failed tests or inspections this week.") +
                    (f" {F['punch_open']} punch item(s) open." if
                     F["punch_open"] else ""))
    al = w["month_allowance"]
    if al is None:
        G["Weather"] = ("G", f"{w['adverse_month']} adverse weather day(s) "
                        "this month; no allowance set. "
                        f"{w['lost_jtd']:g} h lost to date.")
    else:
        G["Weather"] = ("G" if w["adverse_month"] <= int(_num(al)) else "Y",
                        f"{w['adverse_month']} adverse weather day(s) this "
                        f"month vs {al}-day allowance"
                        f"{' (sample)' if w['allow_sample'] else ''}. "
                        f"{w['lost_jtd']:g} h lost to date.")
    F["rag"] = G
    dec = rep.get("decisions") or []
    acts = [d for d in dec if not d.get("done")] or \
        propose_decisions(store, rep, F)
    F["actions"] = sorted(acts, key=lambda d: str(d.get("due") or "9999"))
    soon = [d for d in F["actions"]
            if _day(d.get("due")) and _day(d["due"]) <= F["rd"] +
            timedelta(days=10)]
    F["owner_actions_due_10d"] = len(soon)
    first = min([_day(d["due"]) for d in F["actions"] if _day(d.get("due"))]
                or [None], key=lambda d: d or date.max)
    G["Owner actions"] = ("R" if soon else "G",
                          f"{len(soon)} decision(s) needed within 10 days"
                          + (f"; first one by {mdy(first)}" if first else "")
                          + " (see Owner Action Required).")


def _ahead(n, what):
    """'+8' -> '8 workdays behind baseline'."""
    if n > 0:
        return f"{n} workdays behind {what}"
    if n < 0:
        return f"{-n} workdays ahead of {what}"
    return f"on {what}"


# ------------------------------------------------- owner actions (G05)
def propose_decisions(store, rep, F=None):
    """Owner Action Required proposed from the project data: overdue RFIs,
    potential and pending changes, critical submittals to review, open
    weather delay notices and open issues assigned to the owner. Each:
    {text, due (iso), impact (cost / schedule effect of a late answer),
    ref, done False, proposed True}. The PM edits them before export."""
    F = F or facts(store, rep)
    RD, cal = F["rd"], F["cal"]
    gc = F.get("gc_per_wd") or 0
    gc_txt = (f"; owner-caused delay costs about {money(gc)} per workday in "
              "general conditions") if gc else ""
    out = []

    def add(text, due, impact, ref):
        out.append({"text": text, "due": due.isoformat() if due else "",
                    "impact": impact, "ref": ref, "done": False,
                    "proposed": True})
    for r in F["rfis"]:
        if r["overdue"]:
            add(f"Get the answer to {r['no']} ({r['subject']}) - "
                f"{(RD - r['due']).days} days past its due date",
                _add_wd(cal, RD, 2),
                f"Cost impact: {r['cost'] or 'not stated'}; schedule impact: "
                f"{r['sched'] or 'not stated'}. Work tied to it waits"
                + gc_txt + ".", r["no"])
    for p in F["changes"]["pcos"]:
        amt = f", not to exceed {money(p['amount'])}" if p["amount"] else ""
        cond = f", once {p['rfi']} is answered" if p["rfi"] and \
            p["rfi_open"] else ""
        add(f"Approve {p['title']}{amt}{cond}", p["due"],
            f"The work waits ({p['days']} workday(s) priced)"
            + gc_txt + ".",
            " / ".join(x for x in (p["rfi"], p["ce"], p["no"]) if x))
    for e in F["changes"]["pending"]:
        add(f"Approve change {e['ce']} ({e['title']}), {money(e['amount'])}",
            (e["sent"] or RD) + timedelta(days=14),
            f"{e['days']} workday(s) in the change; the work can't start "
            "without the signed change.", e["ce"])
    for x in F["submittals"]:
        if not x["critical"] or x.get("unlogged") or \
                x["status"].startswith("Returned"):
            continue
        tr = x.get("transmittal")
        trd = _day(tr.get("sent")) if tr else None
        due = trd if trd and trd > RD else (x["forecast"] or RD)
        add(f"Have the architect review {x['title']} within 10 workdays of "
            "receipt", due, "On the critical path: each review day beyond 10 "
            "adds a workday to the forecast.",
            " / ".join(v for v in (x["activity"], tr.get("_no") if tr else "")
                       if v))
    for d in F["delays"]:
        if (d.get("cause") or "") != "Weather" or \
                d.get("status") not in OPEN_DELAY or not d.get("notice_date"):
            continue
        st = _day(d.get("event_start"))
        add(f"Acknowledge weather delay notice {d.get('_no')} "
            f"({md(st)}, {int(_num(d.get('days_requested')))} day(s)); we "
            "settle weather time against the allowance at month end",
            _month_end(st or RD), "No cost; keeps the time record open "
            "until it is settled.", d.get("_no"))
    owners = {m.get("name") for m in F["members"]
              if m.get("role") in OWNER_ROLES}
    for i in F["issues"]:
        if i.get("assignee") in owners:
            add(f"{i.get('title')}", _day(i.get("due")) or
                _add_wd(cal, RD, 5), "Open with the owner; the work tied to "
                "it can't be planned until it is settled.", i.get("_no"))
    out.sort(key=lambda d: d["due"] or "9999")
    return out


def merge_decisions(rep, props):
    """Add proposed actions the report doesn't have yet (same ref = the
    PM's row, kept as typed). Returns the number added."""
    dec = rep.setdefault("decisions", [])
    have = {(d.get("ref") or d.get("text") or "").strip() for d in dec}
    n = 0
    for p in props:
        k = (p.get("ref") or p.get("text") or "").strip()
        if k in have:
            continue
        dec.append(dict(p))
        have.add(k)
        n += 1
    return n


# ------------------------------------------- executive summary (G04)
def _progress_bits(F):
    ip = [r for r in F["rows"].values() if r.get("status") == "In Progress"
          and not r.get("milestone")]
    ip.sort(key=lambda r: r["_no"])
    return [f"{r['name']} ({int(_num(r.get('percent')))}%)" for r in ip[:3]]


def draft_summary(store, rep, F=None, short=False):
    """A rule-based draft (templates over the facts, no AI). short: 3-4
    sentences for the weekly page 1; else [(lead, paragraph)]."""
    F = F or facts(store, rep)
    RD, sch, ch, w = F["rd"], F["schedule"], F["changes"], F["weather"]
    mp, s = F["manpower"], F["safety"]
    bits = _progress_bits(F)
    prog = (f"Week ending {mdy(RD)}: {mp['days_logged']} work day(s) logged "
            f"and {mp['worker_days']} worker-days on site"
            + (f"; in progress: {', '.join(bits)}" if bits else "") + ".")
    sc = sch.get("sc")
    if sc:
        sched = (f"We forecast substantial completion on {mdy(sc['ef'])}, "
                 f"{_ahead(sch.get('var', 0), 'our baseline')} and "
                 f"{_ahead(-sch.get('margin_wd', 0), 'the contract date')} "
                 f"of {mdy(sch['sc_contract'])} "
                 f"({abs(sch.get('margin_cd', 0))} calendar days)")
        drv = sch.get("driver")
        sched += (f"; {drv['_no']} {drv['name']} now drives the critical "
                  "path." if drv else ".")
    else:
        sched = "The schedule has no substantial completion milestone yet."
    issue = []
    if F["failed"]:
        f0 = F["failed"][0]
        issue.append(f"{f0['note'].rstrip('.')} ({md(f0['date'])})")
    if ch["pcos"]:
        p = ch["pcos"][0]
        issue.append(f"{p['no']} ({p['title']}) is "
                     + (f"priced at {money(p['amount'])} and {p['days']} "
                        "workday(s)" if p["amount"] else "not priced yet")
                     + (f" and needs your decision by {mdy(p['due'])}"
                        if p["due"] else ""))
    issue = ("; ".join(issue) + ".") if issue else \
        "No failed inspections and no open potential changes this week."
    al = w["month_allowance"]
    wx = (f"Rain cost {w['lost_week']:g} hours this week ({w['adverse_month']}"
          " adverse day(s) this month"
          + (f" against a {al}-day allowance" if al is not None else "")
          + f"); {'no injuries' if not s['recordables'] else str(s['recordables']) + ' recordable injury(ies)'}"
          f", and the contract value is "
          f"{'unchanged at ' if not ch['approved'] else ''}"
          f"{money(ch['revised'])}.")
    if short:
        return [prog, sched, issue, wx]
    b = F["billing"]
    nxt = b["next"]
    cost = (f"Contract value {money(ch['revised'])} "
            f"({money(ch['approved'])} approved changes). Potential changes "
            f"{money(ch['exposure'])}; {len(ch['tbd'])} RFI(s) with a cost "
            f"impact not priced yet. Billed to date {money(b['billed'])}"
            + (f"; next pay application (period to "
               f"{mdy(nxt.get('period_to'))}) {money(b['next_gross'])}"
               if nxt else "") + ".")
    weather = (f"{w['lost_week']:g} hours lost to weather this week, "
               f"{w['lost_jtd']:g} to date. {w['adverse_jtd']} adverse "
               f"weather day(s) to date, {w['claimed']} claimed by notice, "
               f"{w['granted']} granted"
               + (f"; {w['month_allowance']}-day allowance this month"
                  if al is not None else "") + ".")
    safety = (f"{s['recordables']} recordable injury(ies). "
              f"{s['toolbox_week']} toolbox talk(s) this week; "
              f"{mp['manhours_week']:,.0f} man-hours.")
    return [("Progress.", prog), ("Schedule.", sched), ("Issues.", issue),
            ("Weather.", weather), ("Cost.", cost), ("Safety.", safety)]


# ------------------------------------------------ photos (G09 G24 G25)
def default_caption(store, ph):
    """An empty caption / location from the Daily Log the photo came from:
    the first crew's work note and location."""
    src = ph.get("src") or ""
    dl = next((d for d in store.list("daily") if orp._log_no(d) == src),
              None)
    if not dl:
        return ph
    crews = [m for m in dl.get("manpower") or []
             if (m.get("notes") or "").strip() and
             _trade_of(m) != "Supervision"]
    if crews and not (ph.get("caption") or "").strip():
        ph["caption"] = f"{crews[0]['notes'].strip().rstrip('.')} " \
                        f"({md(dl.get('date'))})"
    if crews and not (ph.get("location") or "").strip():
        ph["location"] = crews[0].get("location") or ""
    return ph


GENERIC_PLACES = {"site", "job site", "jobsite", "whole site", "all",
                  "various", "office", "trailer", "site trailer"}


def _match_area(loc, label):
    """Same place: equal, or one names the other (at least 8 letters;
    'Site' and the like match nothing)."""
    a, b = (loc or "").strip().lower(), (label or "").strip().lower()
    if not a or not b or a in GENERIC_PLACES or b in GENERIC_PLACES:
        return False
    if a == b:
        return True
    b0 = b.split(" - ")[0]
    return min(len(a), len(b0)) >= 8 and (a in b or b0 in a)


def auto_pins(rep):
    """A photo with no pin whose location names a work area gets a pin at
    the area's centre (marked auto). Returns the number pinned."""
    n = 0
    for ph in rep.get("photos") or []:
        if ph.get("pin"):
            continue
        wa = next((a for a in rep.get("work_areas") or []
                   if _match_area(ph.get("location"), a.get("label"))
                   and a.get("pts")), None)
        if not wa:
            continue
        xs = [float(p[0]) for p in wa["pts"]]
        ys = [float(p[1]) for p in wa["pts"]]
        ph["pin"] = {"sheet": wa.get("sheet"), "page": wa.get("page", 0),
                     "x": sum(xs) / len(xs), "y": sum(ys) / len(ys),
                     "auto": True}
        n += 1
    return n


def before_from_logs(store, rep):
    """Before photos for before/after: for a report photo with a location
    and no pair, the earliest Daily Log photo whose crew worked at the
    same location (logged before the photo). Returns the number added."""
    cands = rep.setdefault("before_candidates", [])
    have = {orp._photo_key(c.get("ref")) for c in cands}
    logs = sorted(store.list("daily"), key=lambda d: str(d.get("date")))
    n = 0
    for ph in rep.get("photos") or []:
        loc = (ph.get("location") or "").strip()
        if not loc or ph.get("pair_with"):
            continue
        taken = _day(ph.get("taken")) or report_date(rep)
        for dl in logs:
            dd = _day(dl.get("date"))
            if not dd or dd >= taken or not dl.get("photos"):
                continue
            crew = next((m for m in dl.get("manpower") or []
                         if _match_area(loc, m.get("location")) and
                         _trade_of(m) != "Supervision"), None)
            if not crew:
                continue
            ref = dl["photos"][0]
            if not isinstance(ref, dict):
                continue
            if orp._photo_key(ref) not in have:
                c = orp._photo_entry(ref, len(cands) + 1,
                                     taken=dd.isoformat(), src=orp._log_no(dl))
                c["location"] = loc
                c["caption"] = f"Before: {(crew.get('notes') or '').strip()}" \
                    .strip().rstrip(":")
                cands.append(c)
                have.add(orp._photo_key(ref))
                n += 1
            ph["pair_with"] = ref
            break
    return n


# ----------------------------------------- numbers for the comparison
def numbers(F):
    """The figures under the model report's names
    (runs/model_report_numbers.json in the review)."""
    sch, e, b, ch = F["schedule"], F["earned"], F["billing"], F["changes"]
    mp, w = F["manpower"], F["weather"]
    sc = sch.get("sc") or {}
    N = OrderedDict()
    N["forecast_sc"] = str(sc.get("ef"))
    N["baseline_sc"] = sc.get("baseline_finish")
    N["sc_var_vs_baseline_wd"] = sch.get("var")
    N["sc_margin_vs_contract_wd"] = sch.get("margin_wd")
    N["sc_margin_vs_contract_cd"] = sch.get("margin_cd")
    N["fc_margin_vs_contract_cd"] = sch.get("fc_margin_cd")
    N["contract_days"] = sch["contract_cd"]
    N["days_used"] = sch["used_cd"]
    N["time_elapsed_pct"] = sch["elapsed_pct"]
    N["contract_sum"] = F["contract_sum"]
    N["earned_value"] = round(e["ev"])
    N["planned_value_baseline"] = round(e["pv"])
    N["pct_complete_earned"] = e["pct"]
    N["pct_planned"] = e["planned_pct"]
    N["s_curve"] = [[str(m), round(p, 1), round(f, 1)]
                    for m, p, f in e["curve"]]
    N["billed_to_date"] = b["billed"]
    N["retainage_held"] = b["retainage_held"]
    N["pa1_draft_gross"] = b["next_gross"]
    N["cash_flow"] = [{"no": c["no"], "period": str(c["period"]),
                       "gross": round(c["gross"]), "ret": round(c["ret"]),
                       "net": round(c["net"]), "co": round(c["co"]),
                       "pay": str(c["pay"])} for c in b["cash"]]
    N["approved_cos_asof"] = ch["approved"]
    N["revised_contract"] = ch["revised"]
    N["potential_exposure"] = round(ch["exposure"])
    N["gc_cost_per_workday"] = round(F["gc_per_wd"])
    N["manhours_week"] = mp["manhours_week"]
    N["manhours_jtd"] = mp["manhours_jtd"]
    N["recordables"] = F["safety"]["recordables"]
    N["trir_jtd"] = F["safety"]["trir"]
    N["toolbox_talks_week"] = F["safety"]["toolbox_week"]
    N["toolbox_talks_jtd"] = F["safety"]["toolbox_jtd"]
    N["weather_impacted_jtd"] = w["adverse_jtd"]
    N["weather_impacted_week"] = w["adverse_week"]
    N["hours_lost_jtd"] = w["lost_jtd"]
    N["hours_lost_week"] = w["lost_week"]
    N["rain_jtd"] = w["rain_jtd"]
    N["rain_week"] = w["rain_week"]
    N["weather_claimed"] = w["claimed"]
    N["nov_allowance_sample"] = w["month_allowance"]
    N["excusable_weather_days"] = w["excusable"]
    N["subs_due_not_sent"] = F["subs_due_not_sent"]
    N["rfis_open"] = F["rfis_open"]
    N["long_lead"] = [{"item": x["item"], "sub_bl": str(x["sub_bl"]),
                       "sub_fc": str(x["sub_fc"]), "ship_fc": str(x["ship_fc"]),
                       "need": str(x["need"]), "margin": str(x["margin"]),
                       "status": x["status"]} for x in F["long_lead"]]
    N["worker_days_week"] = mp["worker_days"]
    N["owner_actions_due_10d"] = F["owner_actions_due_10d"]
    N["rag"] = {k: v[0] for k, v in F["rag"].items()}
    return N


# ------------------------------------------------------- the sections
def C(text, **k):
    d = {"text": text}
    d.update(k)
    return d


def T(cols, rows, title=None, size=7.6):
    return {"t": "table", "cols": cols, "rows": rows, "title": title,
            "size": size}


def P(text, lead=None, **k):
    d = {"t": "text", "text": text, "lead": lead}
    d.update(k)
    return d


def SMP(text):
    return {"t": "sample", "text": text}


def BAR(text):
    return {"t": "bar", "text": text}


def NOTE(text):
    return {"t": "text", "text": text, "size": 6.8, "color": "grey"}


WXC = [["Date", 58], ["High/Low F", 52], ["Rain (in.)", 44, "right"],
       ["Conditions", 62], ["Work impacted", 50, "center"],
       ["Hours lost", 40, "right"], ["Trades affected", 150],
       ["Adverse day", 48, "center"], ["Claimed", 60, "center"],
       ["Source", 86]]

TITLES = OrderedDict([
    ("dashboard", "Dashboard - status, KPIs and S-curve"),
    ("decisions_all", "All open owner decisions"),
    ("schedule", "Schedule status - milestones, critical path, recovery"),
    ("weather", "Inclement weather log - job to date and allowance"),
    ("manpower", "Manpower vs plan"),
    ("site", "Site activity - inspections, equipment, deliveries, visitors"),
    ("budget", "Budget, billing, cash-flow forecast, contingency"),
    ("co_pco", "Change orders and PCO exposure log"),
    ("aging", "RFI and submittal aging"),
    ("long_lead", "Long-lead items"),
    ("permits", "Permits, inspections and testing"),
    ("safety", "Safety statistics"), ("quality", "Quality and punch"),
    ("risks", "Risk register"), ("meetings", "Meeting summary"),
    ("logistics", "Site logistics"), ("key_plan", "Photo key plan"),
    ("work_areas", "Work areas"), ("before_after", "Before / after photos"),
    ("rfi_log", "RFI log (attached)"),
    ("submittal_log", "Submittal log (attached)"),
    ("co_log", "Change order log (attached)"),
    ("weather_log", "Inclement weather log (attached form)"),
    ("forecast", "10-day weather forecast"),
    ("distribution", "Distribution list and data notes")])


def _wx_rows(F, rows):
    out = []
    for w in rows:
        cells = [w["date"].strftime("%a %m/%d"),
                 f"{w['high']}/{w['low']}" if w["high"] else "-",
                 f"{_c2(w['rain']):.2f}", w["sky"] or "-",
                 ("Yes" if w["lost"] else "No") if w["workday"] else "-",
                 f"{w['lost']:g}", w["trades"] or "-",
                 C("YES", bold=True, color="red") if w["adverse"] else "no",
                 C(f"Yes ({w['claim_ref']})" if w["claim_ref"] else "Yes",
                   bold=True) if w["claimed"] else "-",
                 w["src"] + (" *" if w["typed"] else "")]
        if not w["workday"]:
            cells = [C(c, color="grey") if isinstance(c, str) else c
                     for c in cells]
        out.append({"cells": cells, "fill": "amber" if w["adverse"] else
                    ("grey" if not w["workday"] else None)})
    return out


def _sec(key, title, place, blocks, presets, new_page=True):
    return {"key": key, "title": title, "place": place, "blocks": blocks,
            "presets": presets, "new_page": new_page}


def _actions_items(F, n=None):
    acts = F["actions"][:n] if n else F["actions"]
    out = []
    for i, d in enumerate(acts, 1):
        imp = re.sub(r"^\s*if late:\s*", "", d.get("impact") or "",
                     flags=re.I)
        txt = (d.get("text") or "").rstrip(". ")
        out.append([str(i), txt + (f". If late: {imp[:1].lower()}{imp[1:]}"
                                   if imp else ""),
                    mdy(d.get("due")), d.get("ref", "")])
    return out


def _summary_blocks(rep, F, store):
    txt = (rep.get("summary_text") or "").strip()
    if txt:
        return [P(p.strip(), after=4) for p in txt.split("\n\n") if p.strip()]
    return [P(t, lead=l, after=4) for l, t in draft_summary(store, rep, F)]


def pack(store, rep, F=None):
    """rep["pack"] for owner_report_pack: the sections (tagged with the
    presets they print in), the weekly page 1 and the monthly setup."""
    F = F or facts(store, rep)
    RD, sch, ch, w = F["rd"], F["schedule"], F["changes"], F["weather"]
    e, b, mp, s = F["earned"], F["billing"], F["manpower"], F["safety"]
    cal, ROWS = F["cal"], F["rows"]
    CON = max(F["contract_sum"], 1)
    sc, fc = sch.get("sc"), sch.get("fc")
    FULL, WEEK, MON = "full", "weekly", "monthly"
    secs = []
    # -- dashboard
    al = w["month_allowance"]
    first_due = min([_day(d["due"]) for d in F["actions"]
                     if _day(d.get("due"))] or [None],
                    key=lambda d: d or date.max)
    kp = [["Percent complete (earned)", f"{e['pct']:.1f}%",
           f"planned {e['planned_pct']:.1f}% (baseline)"],
          ["Contract time elapsed", f"{sch['elapsed_pct']:.1f}%",
           f"{sch['used_cd']} of {sch['contract_cd']} calendar days"],
          ["Forecast substantial completion", mdy(sc["ef"]) if sc else "-",
           f"baseline {mdy(sc.get('baseline_finish'))}, contract "
           f"{mdy(sch['sc_contract'])}" if sc else "", "amber"
           if sc and sch.get("var", 0) > 0 else None],
          ["Margin to contract date", f"{sch.get('margin_wd', 0)} workdays",
           f"{sch.get('margin_cd', 0)} calendar days"],
          ["Contract value / billed", f"{money(ch['revised'])} / "
           f"{money(b['billed'])}", f"next pay app {money(b['next_gross'])}"
           if b["next"] else ""],
          ["Potential change exposure", money(ch["exposure"]),
           f"{_c2(ch['exposure'] / CON * 100):.2f}% of contract",
           "amber" if ch["exposure"] else None],
          ["Open RFIs / submittals due", f"{F['rfis_open']} / "
           f"{F['subs_due_not_sent']}", "submittals due, not yet submitted"],
          [f"Adverse weather days ({RD:%b})", f"{w['adverse_month']}" +
           (f" of {al}" if al is not None else ""),
           "allowance is SAMPLE DATA" if w["allow_sample"] else
           ("" if al is not None else "no allowance set")],
          ["Man-hours week / to date", f"{mp['manhours_week']:,.0f} / "
           f"{mp['manhours_jtd']:,.0f}", "from the Daily Logs"],
          ["Recordable injuries / TRIR", f"{s['recordables']} / "
           f"{_c2(s['trir']):.2f}", f"{s['toolbox_week']} toolbox talks this week",
           "green" if not s["recordables"] else "red"],
          ["Owner actions due in 10 days", str(F["owner_actions_due_10d"]),
           f"first by {mdy(first_due)}" if first_due else "",
           "red" if F["owner_actions_due_10d"] else None],
          ["Worker-days on site (week)", str(mp["worker_days"]),
           f"{mp['days_logged']} work days logged"]]
    NTP, sc_c = F["ntp"], sch["sc_contract"]
    cum, bill = 0, [[str(NTP), 0]]
    for c in b["cash"]:
        cum += c["gross"]
        bill.append([str(c["period"]), _c2(cum / CON * 100)])
    chart = {"t": "chart", "height": 172, "x0": str(NTP), "x1": str(sc_c),
             "title": "PLANNED VS ACTUAL - cumulative % of contract value "
                      "(S-curve)",
             "ticks": [str(m) for m in e["months"]],
             "series": [
                 {"label": "Planned (baseline)", "color": "blue",
                  "points": [[str(NTP), 0]] + [[str(m), _c2(p)]
                                               for m, p, f in e["curve"]]},
                 {"label": "Forecast (current CPM)", "color": "red",
                  "width": 1.1,
                  "points": [[str(NTP), 0]] + [[str(m), _c2(f)]
                                               for m, p, f in e["curve"]]},
                 {"label": "Projected billing (next pay apps)",
                  "color": "black", "dash": True, "width": 1.2,
                  "points": bill},
                 {"label": f"Earned {md(RD)}: {e['pct']:.1f}%",
                  "color": "green", "points": [],
                  "marks": [[str(RD), e["pct"]]]}]}
    secs.append(_sec("dashboard", "DASHBOARD - STATUS AT A GLANCE", "front", [
        {"t": "rag", "items": [[k, v[0], v[1]] for k, v in F["rag"].items()]},
        NOTE("Rules: Schedule red if the forecast is after the contract "
             "date, yellow if more than 5 workdays behind baseline. Cost "
             "yellow if potential changes exceed 0.5% of contract, red above "
             "5%. Quality yellow if a test or inspection failed this week. "
             "Weather green while adverse days stay within the month's "
             "allowance. Owner actions red when a decision is due within 10 "
             "days."),
        {"t": "space", "h": 4}, {"t": "kpis", "items": kp, "per_row": 4},
        chart], [FULL, MON]))
    acts = _actions_items(F)
    secs.append(_sec("summary", "EXECUTIVE SUMMARY", "front",
                     _summary_blocks(rep, F, store) + [
                         {"t": "space", "h": 4},
                         BAR("OWNER ACTION REQUIRED"),
                         {"t": "actions", "items": acts, "title":
                          "What we need from you (and what happens if it "
                          "is late)"}] if acts else
                     _summary_blocks(rep, F, store), [FULL]))
    if acts:
        secs.append(_sec("decisions_all", "ALL OPEN OWNER DECISIONS", "front",
                         [{"t": "actions", "items": acts, "title":
                           "What we need from you (and what happens if it "
                           "is late)"},
                          NOTE("The first three are also on page 1 of the "
                               "weekly report.")], [MON], new_page=False))
    # -- work done this week (weekly)
    done = []
    for bl in rep.get("progress") or []:
        t = bl.get("text") if isinstance(bl, dict) else str(bl)
        if t:
            tr = (bl.get("trade") if isinstance(bl, dict) else "") or ""
            if tr and t.startswith(tr + " - "):
                t = t[len(tr) + 3:]
            done.append([C(tr, bold=True) if tr else "", t])
    for x in F["failed"]:
        done.append([C("Inspection", bold=True),
                     C(f"{x['date']:%a %m/%d}: {x['note']}", color="red")])
    crews = sorted({r["company"] for r in mp["rows"] if r["company"]})
    if crews:
        done.append([C("Crews on site", bold=True), ", ".join(crews) + "."])
    a0, a1 = orp.week_range(rep)
    secs.append(_sec("work_done", f"WORK COMPLETED THIS WEEK BY TRADE  "
                     f"{mdy(a0)} - {mdy(a1)}", "weekly",
                     [T([["Trade", 120], ["Work completed", 600]], done
                        or [["", "No Daily Logs this week."]])], [WEEK]))
    # -- next week
    nw0, nw1 = F["next_week_range"]
    nrows = [[f"{r['_no']} {r['name']}", _company(store, r.get(
        "responsible")) or r.get("responsible") or "", mdy(r["es"]),
        mdy(r["ef"]), str(r["float"]),
        C("Yes", bold=True, color="red") if r.get("critical") else "No"]
        for r in F["next_week"]]
    hol = F["holidays_next"]
    nwd = sum(1 for i in range(5) if cal.is_work(nw0 + timedelta(days=i)))
    secs.append(_sec("next_week", f"WORK PLANNED NEXT WEEK  {mdy(nw0)} - "
                     f"{mdy(nw1)}", "detail", [
                         T([["Activity", 290], ["Who", 120], ["Start", 70],
                            ["Finish", 70], ["Float (wd)", 60, "center"],
                            ["Critical", 55, "center"]], nrows or
                           [["Nothing scheduled", "", "", "", "", ""]]),
                         P(f"{nwd} work day(s) next week"
                           + (f" (holiday: {', '.join(mdy(h) for h in hol)})"
                              if hol else "") + ".", size=7.6)],
                     [FULL, WEEK]))
    # -- schedule (G06)
    sm = []
    for lab, row, con, v, mwd, mcd in (
            ("Substantial completion", sc, sc_c, sch.get("var"),
             sch.get("margin_wd"), sch.get("margin_cd")),
            ("Final completion", fc, sch.get("fc_contract"),
             sch.get("fc_var"), sch.get("fc_margin_wd"),
             sch.get("fc_margin_cd"))):
        if not row:
            continue
        sm.append([C(lab, bold=True), mdy(con), mdy(row.get("baseline_finish")),
                   C(mdy(row["ef"]), bold=True),
                   C(f"{v:+d} workdays" if v is not None else "-",
                     color="red" if v and v > 0 else "black"),
                   f"{mwd} workdays ({mcd} cal.)" if mwd is not None else "-"])
    from . import schedule as _s
    ms_rows = []
    for r in sch["milestones"]:
        v = _s.variance(r, cal)
        ms_rows.append([f"{r['_no']} {r['name']}",
                        mdy(r.get("baseline_finish")), mdy(r["ef"]),
                        C(f"{v:+d}" if v is not None else "",
                          color="red" if v and v > 0 else "black"),
                        r.get("status") or ("Critical" if r.get("critical")
                                            else "Planned")])
    crit = [r for r in sch["critical"]][:6]
    drv = sch.get("driver")
    cp = " > ".join(f"{r['_no']} {r['name']}" for r in crit)
    cp_txt = (f"The longest path now runs: {cp}"
              + (f" > ... > {sc['_no']} {sc['name']}." if sc else ".")) \
        if crit else "No open critical activities."
    if drv:
        dv = _s.variance(drv, cal) or 0
        cp_txt += (f" {drv['_no']} {drv['name']} was planned to finish "
                   f"{mdy(drv.get('baseline_finish'))}; the CPM now finishes "
                   f"it {mdy(drv['ef'])} (+{dv} workdays), and it drives the "
                   "forecast.")
    var = sch.get("var") or 0
    if var > 0:
        rec = [f"The forecast is {var} workdays behind the baseline."]
        if drv:
            rec.append(f"The most delayed critical work is {drv['_no']} "
                       f"{drv['name']} ({_company(store, drv.get('responsible'))}).")
        rec.append("Proposed for the next update, to be confirmed with the "
                   "trades: resequence or add crews on the critical "
                   "activities starting in the next three weeks, and ask for "
                   "fast reviews of critical submittals (see Owner Action "
                   "Required).")
    else:
        rec = ["None needed: the forecast is on or ahead of the baseline."]
    if (rep.get("recovery_note") or "").strip():
        rec = [rep["recovery_note"].strip()]
    steps = _recovery_steps(store)
    ld = F["terms"]["ld"]
    secs.append(_sec("schedule", "SCHEDULE STATUS - MILESTONES, CRITICAL PATH "
                     "AND RECOVERY", "detail", [
                         T([["", 150], ["Contract", 80], ["Baseline", 80],
                            ["Forecast", 80], ["Variance vs baseline", 110],
                            ["Margin to contract", 150]], sm),
                         NOTE(f"Data date {mdy(F['dd'])}. Forecast by the "
                              f"app's CPM engine from {len(ROWS)} activities."
                              + (f" Liquidated damages: {money(ld)} per day "
                                 f"after {mdy(sc_c)}"
                                 + (" - not at risk on this forecast."
                                    if sc and sc["ef"] <= sc_c else ".")
                                 if ld else "")),
                         T([["Milestone", 300], ["Baseline", 80],
                            ["Forecast / actual", 90],
                            ["Variance (wd)", 80, "center"], ["Status", 110]],
                           ms_rows, title="MILESTONES"),
                         P(cp_txt, lead="Critical path:", size=7.8, after=4),
                         P(" ".join(rec), lead="Recovery:", size=7.8)]
                     + ([T([["Activity", 260], ["Technique", 80],
                            ["Change", 170], ["How", 140],
                            ["Sub agreed", 60, "center"]], steps,
                           title=f"RECOVERY STEPS (RECOVERY PLAN - "
                                 f"{(_recovery_plan(store) or {}).get('status') or 'Draft'})")]
                        if steps else []),
                     [FULL, MON]))
    secs.append(_sec("schedule_week", "SCHEDULE STATUS", "weekly", [
        T([["", 150], ["Contract", 80], ["Baseline", 80], ["Forecast", 80],
           ["Variance vs baseline", 110], ["Margin to contract", 150]], sm),
        P(cp_txt, lead="Critical path:", size=7.8, after=4),
        P(" ".join(rec), lead="Recovery:", size=7.8)], [WEEK],
        new_page=False))
    # -- weather (G02 G03)
    wk_rows = [r for r in w["rows"] if r["week"]]
    sums = T([["", 200], ["This week", 80, "center"],
              ["Job to date", 80, "center"]],
             [["Rain total (in.)", f"{_c2(w['rain_week']):.2f}",
               f"{_c2(w['rain_jtd']):.2f}"],
              ["Adverse weather workdays", str(w["adverse_week"]),
               str(w["adverse_jtd"])],
              ["Hours lost to weather", f"{w['lost_week']:g}",
               f"{w['lost_jtd']:g}"],
              ["Weather days claimed (notice filed)", str(w["claimed_week"]),
               str(w["claimed"])],
              ["Weather days granted (Delay Log)", "", str(w["granted"])]],
             size=7.6)
    alr = []
    for a in w["allowance"]:
        if a["adverse"] is None and a["allowed"] is None:
            continue
        lab = a["month"] + (f" (to {md(RD)})" if a["to_date"] else "")
        alr.append([lab, "-" if a["allowed"] is None else str(a["allowed"]),
                    "-" if a["adverse"] is None else str(a["adverse"]),
                    "-" if a["excess"] is None else str(a["excess"]),
                    "-" if a["running"] is None else str(a["running"])])
    unc = [r for r in w["unclaimed_adverse"]]
    eff = (f"{w['lost_jtd']:g} hours lost to date (about "
           f"{w['lost_jtd'] / 8:.1f} crew-days). {w['adverse_jtd']} adverse "
           f"day(s), {w['claimed']} claimed by a notice on the Delay Log, "
           f"{w['granted']} granted. The contract finish moves only by "
           f"granted days ({mdy(sc_c)} + {w['granted']}). Excusable days "
           f"over the allowance so far: {w['excusable']}.")
    if unc:
        eff += " Adverse with no notice (not claimed): " + ", ".join(
            md(r["date"]) for r in unc) + "."
    blocks = [NOTE(f"Rule: a workday is an adverse weather day when rain is "
                   f"{_c2(w['threshold']):.2f} in. or more, or "
                   f"{orp.ADVERSE_HOURS:g} or more hours are lost to weather "
                   "on the Daily Log. Weekend rain is shown but not counted. "
                   "A day is claimed only when a weather delay notice on the "
                   "Delay Log covers it."),
              T(WXC, _wx_rows(F, wk_rows), title="THIS WEEK", size=7.0),
              sums,
              T(WXC, _wx_rows(F, w["rows"]),
                title=f"JOB TO DATE  {mdy(F['ntp'])} - {mdy(RD)}", size=6.6)]
    if any(r["typed"] for r in w["rows"]):
        blocks.append(NOTE("* = typed in the report (no Daily Log that day)."))
    if alr:
        blocks.append(T([["Month", 150], ["Allowance", 100, "center"],
                         ["Adverse days", 90, "center"],
                         ["Excess (excusable)", 100, "center"],
                         ["Running total of excess", 120, "center"]], alr,
                        title="AGAINST THE CONTRACT WEATHER ALLOWANCE"))
        if w["allow_sample"]:
            blocks.append(SMP("The weather allowance is a placeholder "
                              "setting (weather_allowance)."))
    else:
        blocks.append(NOTE("No weather allowance set (setting "
                           "weather_allowance)."))
    blocks.append(P(eff, lead="Effect on the schedule.", size=7.6, after=4))
    blocks += _outlook(rep, F)
    secs.append(_sec("weather", "INCLEMENT WEATHER LOG - DAILY RECORD, "
                     "ALLOWANCE AND OUTLOOK", "detail", blocks, [FULL, MON]))
    secs.append(_sec("weather_week", "WEATHER THIS WEEK - RAIN DAYS AND HOURS "
                     "LOST", "weekly", [
                         T(WXC, _wx_rows(F, wk_rows), size=7.0),
                         P(f"rain {_c2(w['rain_week']):.2f} in. this week "
                           f"({_c2(w['rain_jtd']):.2f} in. to date); hours lost "
                           f"{w['lost_week']:g} ({w['lost_jtd']:g} to date); "
                           f"adverse workdays {w['adverse_week']} this week, "
                           f"{w['adverse_month']} this month"
                           + (f" against a {al}-day allowance" if al is not
                              None else "") + f"; claimed {w['claimed']}, "
                           f"granted {w['granted']}.", lead="Totals:",
                           size=7.6)]
                     + ([SMP("The weather allowance is a placeholder "
                             "setting.")] if w["allow_sample"] else [])
                     + _outlook(rep, F, short=True), [WEEK]))
    return _pack2(store, rep, F, secs)


def _recovery_plan(store):
    try:
        from . import recovery
        return store.setting(recovery.SETTING)
    except Exception:                                   # noqa: BLE001
        return None


def _recovery_steps(store):
    """The saved recovery plan's steps (Schedule > Recovery), as rows."""
    plan = _recovery_plan(store)
    if not plan:
        return []
    from . import recovery
    acts = store.list("activity")
    by = {a["_id"]: a for a in acts}
    rows = []
    for s in plan.get("steps") or []:
        a = by.get(s.get("id"))
        if not a:
            continue
        try:
            what = recovery.describe(store, s, acts)
        except Exception:                               # noqa: BLE001
            what = ""
        rows.append([f"{a.get('_no') or ''} {a.get('name') or ''}",
                     recovery.TECHNIQUES.get(s.get("technique"), ""), what,
                     s.get("how") or "", "Yes" if s.get("agreed") else "No"])
    return rows


def _outlook(rep, F, short=False):
    """Next week's forecast from the report's forecast rows (downloaded or
    typed); offline with none: says so (G22)."""
    nw0, nw1 = F["next_week_range"]
    f = rep.get("forecast") or {}
    rows = [r for r in f.get("rows") or []
            if _day(r.get("date")) and nw0 <= _day(r["date"]) <= nw1]
    hol = set(F["holidays_next"])
    if not rows:
        return [P("not available offline - no forecast downloaded or "
                  "attached.", lead="Outlook:", size=7.6)]
    thr = F["weather"]["threshold"]
    if short:
        bits = []
        for r in rows:
            d = _day(r["date"])
            if d in hol:
                bits.append(f"{d:%a} {md(d)} holiday")
            elif _num(r.get("rain_in")) >= thr or \
                    _num(r.get("rain_chance")) >= 50:
                bits.append(f"{d:%a} {md(d)} {r.get('sky') or 'rain'} "
                            f"{_c2(_num(r.get('rain_in'))):.2f} in.")
        txt = "; ".join(bits) or "no rain days forecast"
        out = [P(txt + ".", lead="Outlook:", size=7.6)]
    else:
        cols = [["Day", 70]] + [[f"{_day(r['date']):%a %m/%d}", 110]
                                for r in rows]
        fc = [C("Forecast", bold=True)] + [
            f"{r.get('sky') or ''} {r.get('high', '')}/{r.get('low', '')}"
            + (f", {_c2(_num(r.get('rain_in'))):.2f} in." if _num(r.get("rain_in"))
               else "") for r in rows]
        plan = [C("Work plan", bold=True)]
        for r in rows:
            d = _day(r["date"])
            if d in hol or not F["cal"].is_work(d):
                plan.append("No work (holiday / weekend)")
            elif _num(r.get("rain_in")) >= thr:
                plan.append(C("Possible lost day", color="red"))
            else:
                plan.append("Normal")
        out = [T(cols, [fc, plan], title="WEATHER OUTLOOK NEXT WEEK")]
    if "forecast" in F["samples"] or "SAMPLE" in str(f.get("source") or ""):
        out.append(SMP("The forecast rows are typed placeholders (no "
                       "forecast service used)."))
    return out


def _pack2(store, rep, F, secs):
    ch, b, mp = F["changes"], F["billing"], F["manpower"]
    FULL, WEEK, MON = "full", "weekly", "monthly"
    CON = max(F["contract_sum"], 1)
    # -- manpower (G12)
    mrows = []
    for r in mp["rows"]:
        pl = r["plan"]
        mrows.append([r["company"], r["trade"], str(r["worker_days"]),
                      f"{r['avg']:.1f}", str(pl) if pl is not None else "-",
                      C(f"{r['avg'] - _num(pl):+.1f}", color="red"
                        if r["avg"] - _num(pl) < -0.5 else "black")
                      if pl is not None else "-"])
    tot = mp["worker_days"] / mp["workdays"]
    mrows.append([C("Total on site", bold=True), "",
                  C(str(mp["worker_days"]), bold=True),
                  C(f"{tot:.1f}", bold=True),
                  C(f"{mp['plan_total']:g}", bold=True) if mp["plan_total"]
                  else "-",
                  C(f"{tot - mp['plan_total']:+.1f}", bold=True)
                  if mp["plan_total"] else "-"])
    mb = [T([["Company", 200], ["Trade", 150],
             ["Worker-days (week)", 90, "center"],
             ["Average / day", 80, "center"], ["Plan / day", 80, "center"],
             ["Average vs plan", 90, "center"]], mrows)]
    if mp["plan_sample"]:
        mb.append(SMP("'Plan / day' crew sizes are placeholders (setting "
                      "crew_plan); actual counts are from the Daily Logs."))
    elif not mp["plan_total"]:
        mb.append(NOTE("No crew plan set (setting crew_plan)."))
    mb.append(P(f"Man-hours this week: {mp['manhours_week']:,.0f}. Job to "
                f"date: {mp['manhours_jtd']:,.0f} (workers x hours on each "
                "Daily Log).", size=7.6))
    secs.append(_sec("manpower", "MANPOWER VS PLAN", "detail", mb,
                     [FULL, MON]))
    # -- site activity (G14)
    st = F["site"]
    sb = []
    sb.append(T([["Date", 70], ["Inspection / test", 430], ["By", 90],
                 ["Result", 60, "center"], ["Source", 70]],
                [[mdy(x["date"]), x["note"], x["by"],
                  C("FAILED", bold=True, color="red") if x["failed"]
                  else "Noted", x["src"]] for x in st["inspections"]]
                or [["", "No inspections logged this week.", "", "", ""]],
                title="INSPECTIONS AND TESTS"))
    if st["equipment"]:
        sb.append(T([["Date", 70], ["Equipment", 300], ["Hours", 60, "right"],
                     ["Idle", 60, "right"], ["Notes", 230]],
                    [[mdy(x["date"]), x["item"], f"{_num(x['hours']):g}",
                      f"{_num(x['idle']):g}", x["notes"]]
                     for x in st["equipment"]], title="EQUIPMENT ON SITE"))
    if st["deliveries"]:
        sb.append(T([["Date", 70], ["Delivered", 330], ["Qty", 90],
                     ["From", 230]],
                    [[mdy(x["date"]), x["what"], str(x["qty"]), x["from"]]
                     for x in st["deliveries"]], title="DELIVERIES"))
    if st["visitors"]:
        sb.append(T([["Date", 70], ["Visitor", 180], ["Company", 220],
                     ["Purpose", 250]],
                    [[mdy(x["date"]), x["name"], x["company"], x["purpose"]]
                     for x in st["visitors"]], title="VISITORS"))
    secs.append(_sec("site", "SITE ACTIVITY - INSPECTIONS, EQUIPMENT, "
                     "DELIVERIES AND VISITORS", "detail", sb,
                     [FULL, WEEK, MON], new_page=False))
    secs.append(_sec("manpower_week", "MANPOWER", "weekly", [
        P(f"{mp['worker_days']} worker-days over {mp['days_logged']} work "
          f"day(s) (average {mp['worker_days'] / max(1, mp['days_logged']):.1f}"
          " a day" + (f" against a plan of {mp['plan_total']:g} a day"
                      + (" [SAMPLE DATA plan]" if mp["plan_sample"] else "")
                      if mp["plan_total"] else "") +
          f"); {mp['manhours_week']:,.0f} man-hours this week, "
          f"{mp['manhours_jtd']:,.0f} to date.", size=7.8)], [WEEK],
        new_page=False))
    # -- budget (G07 G20)
    ret = b["retainage_rate"]
    bb = [["Original contract sum", money(F["contract_sum"])],
          ["Approved change orders (to date)", money(ch["approved"])],
          [C("Revised contract sum", bold=True),
           C(money(ch["revised"]), bold=True)],
          ["Pending change orders (sent, not approved)",
           money(ch["pending_amount"])],
          ["Potential change orders", money(ch["exposure"])],
          ["Billed to date (certified)", money(b["billed"])],
          [f"Retainage held ({ret * 100:g}%)", money(b["retainage_held"])],
          ["Balance to finish", money(ch["revised"] - b["billed"])],
          ["Percent complete - billed / earned (schedule)",
           f"{b['billed'] / max(ch['revised'], 1) * 100:.1f}% / "
           f"{F['earned']['pct']:.1f}%"]]
    blocks = [T([["", 400], ["Amount", 150, "right"]], bb)]
    nxt = b["next"]
    if nxt:
        lines = {str(ln.get("item")): ln for ln in nxt.get("lines") or []}
        sov = []
        for r in F["sov"]:
            ln = lines.get(str(r.get("item"))) or {}
            th = _num(ln.get("this_period")) + _num(ln.get("stored"))
            sch_v = _num(r.get("scheduled"))
            sov.append([str(r.get("item") or ""), r.get("description") or "",
                        money(sch_v), money(th),
                        f"{th / sch_v * 100:.1f}%" if sch_v else "-",
                        money(sch_v - th)])
        blocks.append(T([["Item", 40], ["Description", 230],
                         ["Scheduled value", 100, "right"],
                         [f"Pay App #{nxt.get('_no')} ({nxt.get('status')})",
                          110, "right"], ["%", 60, "right"],
                         ["Balance", 100, "right"]], sov,
                        title=f"SCHEDULE OF VALUES - NEXT PAY APPLICATION "
                              f"(PERIOD TO {mdy(nxt.get('period_to'))})"))
    if b["cash"]:
        cash = [[f"#{c['no']}", mdy(c["period"]), c["status"],
                 money(c["gross"]), money(c["ret"]), money(c["net"]),
                 mdy(c["pay"]), money(c["co"])] for c in b["cash"]]
        cash.append([C("", bold=True), C("Total", bold=True), "",
                     C(money(sum(c["gross"] for c in b["cash"])), bold=True),
                     C(money(sum(c["ret"] for c in b["cash"])), bold=True),
                     C(money(sum(c["net"] for c in b["cash"])), bold=True),
                     "", ""])
        blocks.append(T([["Pay app", 50], ["Period to", 70], ["Status", 70],
                         ["Gross", 90, "right"],
                         [f"Retainage ({ret * 100:g}%)", 90, "right"],
                         ["Net due", 90, "right"],
                         [f"Owner pays (+{F['terms']['owner_pays_days']} d)",
                          90], ["Incl. change orders", 90, "right"]], cash,
                        title="CASH-FLOW FORECAST (THE NEXT PAY APPLICATIONS)"))
    cg = F["contingency"]
    if cg:
        blocks.append(T([["Owner contingency", 400], ["Amount", 150, "right"]],
                        [["Contingency", money(cg["amount"])],
                         ["Used by approved changes", money(cg["used"])],
                         ["Potential changes (if all approved)",
                          money(cg["potential"])],
                         [C("Remaining", bold=True),
                          C(money(cg["remaining"]), bold=True)]],
                        title="CONTINGENCY"))
        if {"owner_contingency", "owner_contingency_pct"} & set(F["samples"]):
            blocks.append(SMP("The owner contingency is a placeholder "
                              "setting."))
    al = F["allowances"]
    if al:
        rows = [[r["name"], money(r["amount"]), money(r["spent"]),
                 C(money(r["remaining"]), color="red" if r["remaining"] < 0
                   else "black")] for r in al]
        tot = [sum(r[k] for r in al) for k in ("amount", "spent", "remaining")]
        rows.append([C("Total", bold=True)] + [C(money(v), bold=True)
                                               for v in tot])
        blocks.append(T([["Allowance", 250], ["Amount", 100, "right"],
                         ["Spent", 100, "right"], ["Remaining", 100, "right"]],
                        rows, title="ALLOWANCES"))
        if "allowances" in set(F["samples"]):
            blocks.append(SMP("The allowances are a placeholder setting."))
    secs.append(_sec("budget", "BUDGET, BILLING AND CASH FLOW", "detail",
                     blocks, [FULL, MON]))
    # -- changes (G08)
    prow = [[p["no"], p["ce"], p["title"], p["rfi"] or "-",
             money(p["amount"]) if p["amount"] else "TBD", str(p["days"]),
             p["status"], mdy(p["due"])] for p in ch["pcos"]]
    prow += [["-", "-", f"{t['title']} (cost impact {t['cost'].lower()})",
              t["rfi"], "TBD", "-", "No PCO yet", ""] for t in ch["tbd"]]
    totals = T([["", 330], ["Count", 70, "center"], ["Amount", 120, "right"],
                ["Days", 60, "center"]],
               [["Original contract sum", "", money(F["contract_sum"]), ""],
                ["Approved change orders", str(len(ch["approved_list"])),
                 money(ch["approved"]), ""],
                [C("Revised contract sum", bold=True), "",
                 C(money(ch["revised"]), bold=True), ""],
                ["Pending change orders (sent, not approved)",
                 str(len(ch["pending"])), money(ch["pending_amount"]),
                 str(sum(x["days"] for x in ch["pending"]))],
                ["Potential change orders", str(len(ch["pcos"])),
                 money(ch["exposure"]), str(sum(p["days"]
                                                for p in ch["pcos"]))],
                ["RFIs with a cost impact, no PCO yet", str(len(ch["tbd"])),
                 "TBD", ""]])
    secs.append(_sec("co_pco", "CHANGE ORDERS AND PCO EXPOSURE LOG", "detail",
                     [totals, T([["PCO", 50], ["Change", 50], ["Title", 230],
                                 ["RFI", 55], ["Amount", 75, "right"],
                                 ["Days", 35, "center"], ["Status", 90],
                                 ["Owner decision by", 80]],
                                prow or [["", "", "None", "", "", "", "", ""]],
                                title="POTENTIAL CHANGE ORDERS (EXPOSURE)"),
                      NOTE(f"Exposure {money(ch['exposure'])} = "
                           f"{_c2(ch['exposure'] / CON * 100):.2f}% of the "
                           "contract. A PCO is a change event tied to an RFI "
                           "sent by the report date and not yet approved.")],
                     [FULL, MON]))
    secs.append(_sec("co_totals", "CHANGE ORDERS AND POTENTIAL CHANGE ORDERS "
                     "- TOTALS", "weekly", [totals],
                     [WEEK], new_page=False))
    return _pack3(store, rep, F, secs)


def _pack3(store, rep, F, secs):
    RD = F["rd"]
    FULL, WEEK, MON = "full", "weekly", "monthly"
    # -- aging (G16 G17)
    rr = [[r["no"], r["subject"], mdy(r["sent"]), mdy(r["due"]), r["bic"],
           str(r["days_open"]) if r["days_open"] is not None else "-",
           C("OVERDUE", bold=True, color="red") if r["overdue"] else
           r["status"], r["cost"], r["sched"]] for r in F["rfis"]]
    sr = [[x["no"], x["title"], x["status"], x["bic"], mdy(x["due"]),
           C(str(x["late_wd"]), color="red") if x["late_wd"] else "0",
           mdy(x["forecast"]), str(x["float"]) if x["float"] is not None
           else "-", mdy(x["need"]) or "-", x["activity"]]
          for x in F["submittals"]]
    rcols = [["RFI", 50], ["Subject", 170], ["Sent", 60], ["Due", 60],
             ["Ball in court", 120], ["Days open", 50, "center"],
             ["Status", 60], ["Cost", 60], ["Schedule", 60]]
    scols = [["No.", 62], ["Submittal", 140], ["Status", 140],
             ["Ball in court", 100], ["Due (baseline)", 58],
             ["Late (wd)", 38, "center"], ["Approval forecast", 58],
             ["Float", 32, "center"], ["Needed on site", 58],
             ["Activity", 44]]
    secs.append(_sec("aging", "RFI AND SUBMITTAL AGING", "detail", [
        T(rcols, rr or [["", "No RFIs sent by the report date"] + [""] * 7],
          title=f"RFIs (AS OF {mdy(RD)})"),
        NOTE("Days open count from the RFI's sent date to the report date."),
        T(scols, sr or [["", "No submittals"] + [""] * 8],
          title="SUBMITTALS")], [FULL, MON]))
    orr = [r for r in rr if r[6] != "Answered"]
    osr = [x for x, raw in zip(sr, F["submittals"])
           if not raw["sent"] and raw["due"] and raw["due"] <= RD + timedelta(
               days=14)]
    secs.append(_sec("open_items", "OPEN RFIs AND SUBMITTALS DUE", "weekly", [
        T(rcols, orr or [["", "No open RFIs"] + [""] * 7], size=7.2),
        T(scols, osr or [["", "No submittals due in the next two weeks"]
                         + [""] * 8], size=7.2)], [WEEK], new_page=False))
    # -- long lead
    ll = [[f"{x['item']} ({x['submit']} > {x['fabricate']} > {x['install']})",
           mdy(x["sub_bl"]), mdy(x["sub_fc"]), mdy(x["ship_fc"]),
           mdy(x["need"]), C(str(x["margin"]), bold=True,
                             color="red" if x["margin"] <= 2 else "black"),
           x["status"]] for x in F["long_lead"]]
    secs.append(_sec("long_lead", "LONG-LEAD ITEMS", "detail", [
        T([["Item (submit > fabricate > install)", 250],
           ["Submittal baseline", 65], ["Submittal forecast", 65],
           ["On site (forecast)", 65], ["Needed (install start)", 65],
           ["Margin (wd)", 50, "center"], ["Status", 120]],
          ll or [["No long-lead items in the schedule"] + [""] * 6]),
        NOTE("Long-lead = a Procurement submit activity followed by a "
             "fabrication / lead-time activity; margin = workdays from "
             "delivery to the install start (CPM).")], [FULL, MON]))
    # -- permits (G15)
    pr = [[p.get("_no") or "", p.get("title") or "", p.get("agency") or "",
           p.get("permit_no") or "", p.get("status") or "",
           mdy(p.get("issued")), mdy(p.get("expires")),
           p.get("next_inspection") or ""] for p in F["permits"]]
    pb = [T([["No.", 50], ["Permit / inspection", 170], ["Agency", 120],
             ["Permit no.", 70], ["Status", 60], ["Issued", 60],
             ["Expires", 60], ["Next inspection", 130]],
            pr or [["", "No permits on the Permits log", "", "", "", "", "",
                    ""]], title="PERMITS")]
    if "permit" in F["samples"] or "permits" in F["samples"]:
        pb.append(SMP("The permit records are placeholders."))
    pb.append(T([["Date", 70], ["Inspection / test", 430], ["By", 90],
                 ["Result", 60, "center"], ["Source", 70]],
                [[mdy(x["date"]), x["note"], x["by"],
                  C("FAILED", bold=True, color="red") if x["failed"]
                  else "Noted", x["src"]] for x in F["site"]["inspections"]]
                or [["", "No inspections logged this week.", "", "", ""]],
                title="INSPECTIONS AND TESTS THIS WEEK"))
    secs.append(_sec("permits", "PERMITS, INSPECTIONS AND TESTING", "detail",
                     pb, [FULL, MON]))
    # -- safety (G13), quality
    s, mp = F["safety"], F["manpower"]
    secs.append(_sec("safety", "SAFETY STATISTICS", "detail", [
        T([["", 300], ["This week", 100, "center"],
           ["Job to date", 100, "center"]],
          [["Man-hours", f"{mp['manhours_week']:,.0f}",
            f"{mp['manhours_jtd']:,.0f}"],
           ["Recordable injuries", "", str(s["recordables"])],
           ["Lost-time injuries", "", str(s["lost_time"])],
           ["Open safety observations (as of the report date)", "",
            str(s["observations_open"])],
           ["TRIR (recordables x 200,000 / man-hours)", "",
            f"{_c2(s['trir']):.2f}"],
           ["Toolbox talks", str(s["toolbox_week"]), str(s["toolbox_jtd"])],
           ["Near misses logged", "", str(s["near_misses"])]]),
        NOTE("From the Daily Logs' safety notes.")], [FULL, MON],
        new_page=False))
    q = [[mdy(x["date"]), x["note"], C("FAILED", bold=True, color="red")]
         for x in F["failed"]]
    secs.append(_sec("quality", "QUALITY AND PUNCH", "detail", [
        T([["Date", 70], ["Failed test / inspection", 560],
           ["Result", 90, "center"]],
          q or [["", "No failed tests or inspections this week.", ""]]),
        P(f"Punch items open as of {mdy(RD)}: {F['punch_open']}.", size=7.6)],
        [FULL, MON], new_page=False))
    # -- risks (G18)
    rk = [[str(i), r["risk"], r["impact"], r["likelihood"], r["action"],
           mdy(r["due"])] for i, r in enumerate(F["risks"], 1)]
    secs.append(_sec("risks", "RISK REGISTER", "detail", [
        T([["#", 20, "center"], ["Risk", 260], ["Impact", 130],
           ["Likelihood", 60], ["Action", 170], ["By", 60]],
          rk or [["", "No open risks", "", "", "", ""]]),
        NOTE("From open potential changes, unpriced RFIs, critical "
             "submittals, insurance expiry against the work, open issues "
             "and weather against the allowance.")], [FULL, MON]))
    # -- meetings (G21)
    m = F["meetings"]
    mb = []
    if m["last"]:
        L = m["last"]
        mb.append(P(f"{L.get('title')} on {mdy(L.get('date'))}"
                    + (f" at {L.get('location')}" if L.get("location") else "")
                    + ".", lead="Last meeting:", size=7.8))
        if m["present"]:
            mb.append(P(", ".join(m["present"]) + ".", lead="Present:",
                        size=7.6))
        if m["open_topics"]:
            mb.append(T([["Item", 40], ["Topic", 200], ["Discussion", 300],
                         ["By", 100], ["Status", 80]],
                        [[t.get("no") or "", t.get("topic") or "",
                          t.get("discussion") or "", t.get("owner") or "",
                          t.get("status") or "Open"]
                         for t in m["open_topics"]], title="OPEN ITEMS"))
    if m["next"]:
        N = m["next"]
        mb.append(P(f"{N.get('title')} on {mdy(N.get('date'))}"
                    + (f" {N.get('time')}" if N.get("time") else "")
                    + (f" at {N.get('location')}" if N.get("location") else "")
                    + ".", lead="Next meeting:", size=7.8))
    secs.append(_sec("meetings", "MEETING SUMMARY", "detail",
                     mb or [P("No meetings on the Meetings log.", size=7.8)],
                     [FULL, MON], new_page=False))
    # -- logistics (G26)
    lg = (rep.get("logistics") or "").strip()
    if lg:
        lb = [{"t": "bullets", "size": 7.8,
               "items": [x.strip(" -") for x in lg.splitlines() if x.strip()]}]
        if "logistics" in F["samples"]:
            lb.append(SMP("The site logistics text is a placeholder."))
        secs.append(_sec("logistics", "SITE LOGISTICS", "detail", lb,
                         [FULL, MON], new_page=False))
    # -- distribution and data notes (G27 G28)
    roles = ("Owner", "Architect", "General Contractor", "Engineer",
             "Owner's Representative")
    dist = [[x.get("name") or "", x.get("company") or "", x.get("role") or "",
             "Email (PDF)"] for x in F["members"]
            if x.get("role") in roles]
    notes = [f"As of {mdy(RD)} (the report date): records dated later are "
             "left out of every figure and log"
             + (": " + "; ".join(F["left_out"]) if F["left_out"] else "")
             + ".",
             f"Schedule: the app's CPM at the data date {mdy(F['dd'])} "
             f"({len(F['rows'])} activities); contract dates from the project "
             "settings.",
             "Percent complete (earned): each schedule-of-values line spread "
             "over its trade's activities by duration (activities matched by "
             "the person responsible on the commitments); lines with no "
             "activities (" + (", ".join(F["earned"]["linear"]) or "none")
             + ") spread evenly from NTP to the contract date. Procurement "
             "activities carry no value.",
             f"Weather: adverse day = a workday with rain of "
             f"{_c2(F['weather']['threshold']):.2f} in. or more or "
             f"{orp.ADVERSE_HOURS:g} or more hours lost on the Daily Log; "
             "claimed = covered by a weather delay notice given by the "
             "report date; the contract finish moves only by granted days.",
             "Billing: certified pay applications with a period ending by "
             "the report date; the cash-flow forecast is the next pay "
             "applications' gross, paid "
             f"{F['terms']['owner_pays_days']} days after the period.",
             "The executive summary and the owner actions are drafted by "
             "rules from these records (no AI, no network); the PM edits "
             "them before export."]
    if F["samples"]:
        notes.append("[SAMPLE DATA] placeholder settings in this report: "
                     + ", ".join(F["samples"]) + ".")
    for x in store.setting("sample_notes") or []:
        notes.append(f"[SAMPLE DATA] {x}")
    secs.append(_sec("distribution", "DISTRIBUTION LIST", "end", [
        T([["Name", 130], ["Company", 230], ["Role", 150], ["Copy", 120]],
          dist or [["", "No owner / architect / contractor members", "", ""]]),
        BAR("DATA SOURCES AND NOTES"),
        {"t": "bullets", "size": 7.4, "items": notes}], [FULL, MON]))
    # -- footers by preset
    preset = str(orp.options(rep).get("report_preset") or "").lower()
    for sct in secs:
        if preset == "monthly":
            sct["footer"] = "Monthly Appendix"
        elif "weekly" in sct["presets"] and sct["place"] == "weekly":
            sct["footer"] = "Weekly Detail"
        else:
            sct["footer"] = {"front": "Owner Summary", "detail":
                             "Project Detail", "end": "Distribution",
                             "weekly": "Weekly Detail"}[sct["place"]]
    # the weekly preset's pages, in this order; a section that also prints
    # in the full report goes in as a copy placed "weekly"
    order = ["work_done", "next_week", "schedule_week", "weather_week",
             "site", "manpower_week", "co_totals", "open_items"]
    by = {x["key"]: x for x in secs}
    weekly = []
    for k in order:
        x = by.get(k)
        if not x:
            continue
        if x["place"] != "weekly":
            y = copy.deepcopy(x)
            y.update(key="w_" + k, place="weekly", presets=[WEEK],
                     footer="Weekly Detail", new_page=False)
            x["presets"] = [p for p in x["presets"] if p != WEEK]
            x = y
        weekly.append(x)
    secs = [x for x in secs if x["place"] != "weekly"] + weekly
    for i, x in enumerate(weekly):      # the weekly pages run on
        x["new_page"] = i == 0
    contents = _sec("contents", "PROJECT", "front",
                    _contents_blocks(rep, F, []), [MON], new_page=True)
    contents["footer"] = "Monthly Appendix"
    contents["cover"] = _cover_blocks(rep, F)
    secs.insert(0, contents)
    wkp = {"status": [[k, v[0], v[1]] for k, v in F["rag"].items()
                      if k in ("Schedule", "Cost", "Safety")],
           "summary": [(rep.get("summary_text") or "").strip()]
           if (rep.get("summary_text") or "").strip()
           else draft_summary(store, rep, F, short=True),
           "actions": _actions_items(F, 3),
           "allowance": {"label": f"{RD:%b} allowance",
                         "days": F["weather"]["month_allowance"],
                         "sample": F["weather"]["allow_sample"]},
           "weather_note": _weather_note(F)}
    mo = dict(((rep.get("pack") or {}).get("monthly") or {}))
    mo.setdefault("title", "Project Progress Report - Monthly Appendix")
    return {"sections": secs, "percent_complete": F["earned"]["pct"],
            "weekly": wkp, "monthly": mo, "auto": True}


def _weather_note(F):
    w = F["weather"]
    al = w["month_allowance"]
    txt = (f"{F['rd']:%B}: {w['adverse_month']} adverse day(s)"
           + (f" of the {al}-day allowance" if al is not None else "")
           + f"; {w['claimed']} claimed by notice, {w['granted']} granted.")
    unc = w["unclaimed_adverse"]
    if unc:
        txt += " " + ", ".join(md(r["date"]) for r in unc) + \
            " adverse, no notice, not claimed."
    txt += f" Hours lost {w['lost_week']:g} this week, {w['lost_jtd']:g} to date."
    return txt


def _cover_blocks(rep, F):
    """G23: the project facts at the top of the appendix's first page (from
    the project members, the contract settings and the report)."""
    def firm(*roles):
        return ", ".join(dict.fromkeys(
            x.get("company") or x.get("name") or "" for x in F["members"]
            if x.get("role") in roles and (x.get("company") or x.get("name"))
        )) or "-"
    hdr = rep.get("header") or {}
    T_ = F["terms"]
    rows = [["Project", f"{hdr.get('job_no', '')} {hdr.get('job_name', '')}"
             .strip() or "-"],
            ["Owner", firm("Owner", "Owner's Representative")],
            ["Architect", firm("Architect")],
            ["General contractor", firm("General Contractor")],
            ["Contract sum", money(F["contract_sum"])],
            ["Notice to proceed", mdy(F["ntp"])],
            ["Substantial completion (contract)", mdy(T_["sc"]) or "-"],
            ["Final completion (contract)", mdy(T_["fc"]) or "-"],
            ["Report no.", f"{rep.get('report_no') or '-'} (goes with the "
             "weekly owner report of the same number)"],
            ["Week", f"{mdy(F['wk0'])} - {mdy(F['rd'])}"]]
    return [T([["Item", 200], ["", 520]],
              [[C(a, bold=True), b] for a, b in rows], size=7.8)]


def _contents_blocks(rep, F, pm, cover=None):
    rows = []
    for m in pm:
        k = m[0].replace("pack_", "")
        if k in TITLES:
            rows.append([TITLES[k], str(m[1]) + (f"-{m[2]}" if len(m) > 2 and
                                                 m[2] != m[1] else "")])
    if not pm:                       # first pass: same rows, pages to come
        rows = [[t, "-"] for k, t in TITLES.items()]
    if cover is None:
        cover = _cover_blocks(rep, F)
    return cover + [BAR("CONTENTS"),
            T([["Section", 560], ["Page", 160, "center"]], rows, size=7.8),
            NOTE("Photo numbers on the key plan and before/after pages refer "
                 "to the weekly report ('W5' = weekly report page 5). This "
                 "appendix is optional and monthly; the weekly report stands "
                 "on its own.")]


# --------------------------------------------- build hooks (build_pdf)
def with_pack(store, rep):
    """A copy of the report with the pack drawn from the project data
    (option auto_pack): weather days by the rules, photos in date order
    with default captions and auto pins, the PM's decisions (else the
    proposed ones), progress by trade, and rep["pack"]. For the monthly
    appendix, the weekly report's photo pages (built first) for the key
    plan / before-after references. The stored record isn't changed."""
    r = copy.deepcopy(rep)
    o = r.setdefault("options", {})
    o["owner_pack"] = True
    o["auto_pack"] = True
    if o.get("progress_by_trade") is None:
        o["progress_by_trade"] = True
    orp.apply_weather_rules(store, r, (r.get("weather") or {}).get("days")
                            or [], report_date(r))
    w = r.setdefault("weather", {})
    from . import owner_report_logs as orl
    if w.get("days"):
        w["impacted"], w["claimed"] = orl.weather_counts(w)
    if not r.get("progress"):
        orp.draft_from_daily_logs(store, r)
    orp.sort_photos(r)
    for ph in r.get("photos") or []:
        default_caption(store, ph)
    auto_pins(r)
    if o.get("before_after") and not r.get("before_candidates"):
        before_from_logs(store, r)
    F = facts(store, r)
    if not r.get("decisions"):
        r["decisions"] = [d for d in F["actions"]]
    preset = str(o.get("report_preset") or "").lower()
    if preset == "monthly" and not ((r.get("pack") or {}).get("monthly")
                                    or {}).get("photo_pages") and \
            orp.printed_photos(r):
        wk = copy.deepcopy(r)
        wk["options"]["report_preset"] = "weekly"
        wk["pack"] = pack(store, wk, F)
        t = orp.template_for(wk, None)
        doc, pm, ctx = orp._build_doc(store, wk, t)
        doc.close()
        ph = next((m for m in pm if m[0] == "photos"), None)
        if ph:
            per = int(orp.options(wk).get("photos_per_page") or 4)
            r.setdefault("pack", {}).setdefault("monthly", {})
            r["pack"]["monthly"]["photo_pages"] = {
                (p.get("ref") or {}).get("name"): f"W{ph[1] + i // per}"
                for i, p in enumerate(orp.printed_photos(wk))}
            r["pack"]["monthly"]["photo_report"] = "weekly"
    r["pack"] = pack(store, r, F)
    return r


def wants_contents(rep):
    return str(orp.options(rep).get("report_preset") or "").lower() == \
        "monthly" and any(s.get("key") == "contents" for s in
                          (rep.get("pack") or {}).get("sections") or [])


def set_contents(rep, page_map, store=None):
    secs = (rep.get("pack") or {}).get("sections") or []
    sct = next((s for s in secs if s.get("key") == "contents"), None)
    if sct is None:
        return
    F = {"rd": report_date(rep)}
    sct["blocks"] = _contents_blocks(rep, F, page_map, sct.get("cover"))
