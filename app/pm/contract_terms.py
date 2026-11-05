"""Contract terms and the owner-vs-sub check (PM review NW-13, NW-14).

The owner (prime) contract's terms are a project setting ("prime_terms");
each subcontract carries the same fields on its Commitment record. The
check compares every subcontract with the owner contract and lists where
the sub's terms leave the GC exposed, each with a severity. No Qt.

Own rules, own wording (not legal advice): a sub notice window as long as
the owner's leaves the GC no time to pass a claim on; liquidated damages
the owner can charge but the sub can't be charged are not flowed down;
less retainage held from the sub than the owner holds from the GC, or a
sub paid sooner than the GC is paid, is cash the GC fronts; a shorter
warranty, a lower umbrella limit or no flow-down clause leave gaps; and
insurance that has expired or expires within 30 days."""
import datetime as _dt

SETTING = "prime_terms"

# (key, label, kind) - kind: days, months, money, pct, yesno
TERMS = (
    ("claim_notice_days", "Claim notice (days)", "days"),
    ("delay_notice_days", "Delay notice (days)", "days"),
    ("ld_per_day", "Liquidated damages ($/day)", "money"),
    ("pay_when_paid", "Pay-when-paid", "yesno"),
    ("pay_days", "Payment due (days after application)", "days"),
    ("retainage_pct", "Retainage %", "pct"),
    ("retainage_reduce_to", "Retainage reduces to %", "pct"),
    ("retainage_reduce_at", "...once the job is this % complete", "pct"),
    ("warranty_months", "Warranty (months)", "months"),
    ("umbrella_limit", "Umbrella / excess limit ($)", "money"),
    ("flow_down", "Flow-down clause", "yesno"),
)
KEYS = tuple(k for k, _l, _t in TERMS)
HIGH, MEDIUM, LOW = "High", "Medium", "Low"


def _num(v):
    try:
        t = str(v if v is not None else "").replace(",", "").replace(
            "$", "").replace("%", "").strip()
        return float(t) if t else None
    except ValueError:
        return None


def _yes(v):
    t = str(v or "").strip().lower()
    return True if t in ("y", "yes", "true", "1") else \
        False if t in ("n", "no", "false", "0") else None


def prime(store):
    """The owner contract's terms {key: text}."""
    cur = store.setting(SETTING) or {}
    return {k: cur.get(k, "") for k in KEYS}


def set_prime(store, values):
    cur = dict(store.setting(SETTING) or {})
    cur.update({k: str(values.get(k, "") or "").strip() for k in KEYS
                if k in values})
    store.set_setting(SETTING, cur)
    return cur


def _sub_retainage(c):
    v = c.get("retainage_pct")
    if v in (None, ""):
        v = c.get("retainage")            # the Commitment's own field
    return _num(v)


def conflicts(store, today=None):
    """[{commitment, no, sub, term, severity, text}] - most severe first,
    then by subcontract."""
    today = today or _dt.date.today().isoformat()
    soon = (_dt.date.fromisoformat(today) +
            _dt.timedelta(days=30)).isoformat()
    p = prime(store)
    out = []
    for c in store.list("commitment"):
        if c.get("status") == "Void" or \
                (c.get("type") or "Subcontract") != "Subcontract":
            continue
        who = c.get("vendor") or c.get("title") or c.get("_no") or "?"

        def add(term, sev, text):
            out.append({"commitment": c.get("_id"), "no": c.get("_no"),
                        "sub": who, "term": term, "severity": sev,
                        "text": text})
        for key, what in (("claim_notice_days", "claim"),
                          ("delay_notice_days", "delay")):
            o, s = _num(p[key]), _num(c.get(key))
            if o is None:
                continue
            if s is None:
                add(key, MEDIUM, f"No {what} notice period in the "
                    f"subcontract (owner requires {o:g} days).")
            elif s >= o:
                add(key, HIGH, f"Sub gives {what} notice in {s:g} days; the "
                    f"owner needs it from you in {o:g} - no time to pass it "
                    "on.")
        o, s = _num(p["ld_per_day"]), _num(c.get("ld_per_day"))
        if o and not s:
            add("ld_per_day", HIGH, f"Owner can charge ${o:,.0f}/day "
                "liquidated damages; none in the subcontract.")
        o, s = _num(p["retainage_pct"]), _sub_retainage(c)
        if o is not None and s is not None and s < o:
            add("retainage_pct", MEDIUM, f"You hold {s:g}% from the sub but "
                f"the owner holds {o:g}% from you.")
        o_pwp, s_pwp = _yes(p["pay_when_paid"]), _yes(c.get("pay_when_paid"))
        o_days, s_days = _num(p["pay_days"]), _num(c.get("pay_days"))
        if s_pwp is not True and o_days is not None and s_days is not None \
                and s_days < o_days:
            add("pay_days", MEDIUM, f"Sub is due payment in {s_days:g} days "
                f"without pay-when-paid; the owner pays you in {o_days:g}.")
        elif o_pwp is True and s_pwp is False:
            add("pay_when_paid", MEDIUM, "Owner contract is pay-when-paid; "
                "the subcontract isn't.")
        o, s = _num(p["warranty_months"]), _num(c.get("warranty_months"))
        if o is not None and (s is None or s < o):
            add("warranty_months", HIGH, f"Sub warranty "
                f"{'not stated' if s is None else f'{s:g} months'}; you owe "
                f"the owner {o:g} months.")
        o, s = _num(p["umbrella_limit"]), _num(c.get("umbrella_limit"))
        if o and (s is None or s < o):
            add("umbrella_limit", MEDIUM, f"Sub umbrella "
                f"{'not stated' if s is None else f'${s:,.0f}'}; the owner "
                f"requires ${o:,.0f}.")
        if _yes(p["flow_down"]) is True and _yes(c.get("flow_down")) is not \
                True:
            add("flow_down", HIGH, "Owner contract terms aren't flowed "
                "down to this subcontract.")
        exp = str(c.get("insurance_expires") or "")[:10]
        if exp and exp < today:
            add("insurance_expires", HIGH, f"Insurance expired {exp}.")
        elif exp and exp <= soon:
            add("insurance_expires", LOW, f"Insurance expires {exp}.")
    rank = {HIGH: 0, MEDIUM: 1, LOW: 2}
    out.sort(key=lambda x: (rank[x["severity"]], str(x["no"] or ""),
                            x["term"]))
    return out


# ---- retainage rule (P1: "10% to 5% at 50%", applied by itself) -----------

def percent_complete(store, before_period=None):
    """Work certified so far / the contract sum (with approved change
    orders), in %. Only Certified / Paid apps before `before_period`."""
    from . import cost
    total = sum(x["scheduled"] for x in cost.sov_lines(store))
    if total <= 0:
        return 0.0
    done = 0.0
    for a in cost.payapps_in_order(store):
        if str(a.get("status") or "").lower() not in ("certified", "paid"):
            continue
        if before_period and (a.get("period_to") or "") >= before_period:
            continue
        for ln in a.get("lines") or []:
            done += _num(ln.get("this_period")) or 0
            done += _num(ln.get("stored")) or 0
    return round(done / total * 100, 2)


def retainage_for(store, rec):
    """(retainage %, note) the owner contract's rule gives the pay app
    `rec`, or (None, "") when the contract has no rule. The rule: hold
    retainage_pct until the job is retainage_reduce_at % complete (work
    certified on EARLIER apps), then retainage_reduce_to."""
    p = prime(store)
    base, to, at = (_num(p.get(k)) for k in ("retainage_pct",
                                             "retainage_reduce_to",
                                             "retainage_reduce_at"))
    if base is None and (to is None or at is None):
        return None, ""
    done = percent_complete(store, rec.get("period_to"))
    if to is not None and at is not None and done >= at:
        return to, (f"Retainage {to:g}%: the job is {done:g}% complete "
                    f"(owner contract: {to:g}% once {at:g}% complete).")
    if base is None:
        return None, ""
    note = ""
    if to is not None and at is not None:
        note = (f"Retainage {base:g}% until the job is {at:g}% complete "
                f"(now {done:g}%), then {to:g}%.")
    return base, note


def apply_retainage_rule(store, rec):
    """Set the draft pay app's retainage on work by the contract's rule.
    A % the PM typed over the rule's (it differs from the last one the
    rule set) is kept, with the note saying so. Returns the note."""
    if str(rec.get("status") or "Draft") not in ("Draft", "Submitted"):
        return ""
    pct, note = retainage_for(store, rec)
    if pct is None:
        return ""
    last = _num(rec.get("retainage_rule_pct"))
    cur = _num(rec.get("retainage_work"))
    if last is not None and cur is not None and cur != last:
        note = (f"Retainage {cur:g}% typed by hand (the contract rule "
                f"gives {pct:g}%).")
    else:
        rec["retainage_work"] = pct
        rec["retainage_rule_pct"] = pct
    rec["retainage_note"] = note
    return note


# ---- notice deadlines (P1 "notice deadline tracker") ----------------------

def notice_due(store, rec):
    """The date written notice of this Delay Log event is due by the owner
    contract's delay notice days (counted in calendar days from the event
    start), or ''."""
    days = _num(prime(store).get("delay_notice_days"))
    start = str(rec.get("event_start") or "")[:10]
    if days is None or not start:
        return ""
    try:
        d = _dt.date.fromisoformat(start)
    except ValueError:
        return ""
    return (d + _dt.timedelta(days=int(days))).isoformat()


def stamp_notice_due(store, rec):
    """Before a Delay Log save: 'due' = the notice deadline while no notice
    has been given (so it shows as due / overdue with everything else);
    'notice_late' when the notice went out after it."""
    due = notice_due(store, rec)
    given = str(rec.get("notice_date") or "")[:10]
    if not due:
        return rec
    rec["notice_due"] = due
    if given:
        rec.pop("due", None)
        rec["notice_late"] = given > due
    else:
        rec["due"] = due
        rec.pop("notice_late", None)
    return rec


def notice_list(store, today=None):
    """[{no, title, due, status}] for every Delay Log event under the
    owner contract's notice rule: 'OVERDUE', 'Due in N days', 'Late
    (given D)' or 'On time'. Most urgent first."""
    today = today or _dt.date.today().isoformat()
    out = []
    for r in store.list("delay"):
        if r.get("status") in ("Withdrawn",):
            continue
        due = notice_due(store, r)
        if not due:
            continue
        given = str(r.get("notice_date") or "")[:10]
        if given:
            st = f"Late (given {given})" if given > due else "On time"
            rank = 2
        elif due < today:
            st, rank = "OVERDUE", 0
        else:
            n = (_dt.date.fromisoformat(due) -
                 _dt.date.fromisoformat(today)).days
            st, rank = f"Due in {n} day{'s' if n != 1 else ''}", 1
        out.append({"id": r.get("_id"), "no": r.get("_no"),
                    "title": r.get("title"), "due": due, "status": st,
                    "_rank": rank})
    out.sort(key=lambda x: (x["_rank"], x["due"]))
    for x in out:
        x.pop("_rank")
    return out
