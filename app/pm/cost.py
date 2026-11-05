"""Job cost: budget, commitments, change events, direct costs, owner
billing and the forecast - all worked out from Project Center records.

Numbers follow Procore / StratusVue conventions:
  revised budget  = original + approved change-event costs
  committed       = commitment SOVs + approved change-event costs placed
                    with that vendor
  actual          = direct costs and invoices
  cost to complete = your estimate, else what's left of the larger of the
                    revised budget and the commitment
  forecast at completion = actual + cost to complete (+ risk)
  variance        = revised budget - forecast at completion
"""
import logging
from . import schema
from .store import spec_number


def _f(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def code_key(code):
    return spec_number(code) or (code or "").strip() or "(no code)"


def event_cost(e):
    return round(sum(_f(l.get("cost")) for l in e.get("lines") or []), 2)


def event_price(e):
    tot = 0.0
    for l in e.get("lines") or []:
        p = l.get("price")
        if p in (None, ""):
            p = _f(l.get("cost")) * (1 + _f(l.get("markup")) / 100)
        tot += _f(p)
    return round(tot, 2)


_SUFFIX = {"llc", "l l c", "inc", "incorporated", "co", "company", "corp",
           "corporation", "ltd", "lp", "llp", "pllc", "pc"}


def vendor_key(name):
    """'Red Clay Sitework, L.L.C.' and 'red clay sitework llc' -> the same
    key: lower case, punctuation and company suffixes dropped."""
    import re
    t = re.sub(r"[^a-z0-9& ]+", " ", str(name or "").lower())
    t = re.sub(r"\bl\s+l\s+c\b", "llc", t)
    words = t.split()
    while words and words[-1] in _SUFFIX:
        words.pop()
    return " ".join(words)


def vendor_keys(store, c):
    """Every name a change-event line may use for commitment `c`'s vendor:
    the vendor as typed (a person or a company) and, for a Directory
    person, their company (PM review NW-08: lines typed with the company
    'Red Clay Sitework LLC' never matched the vendor person 'Sam Grader')."""
    v = c.get("vendor") or ""
    keys = {vendor_key(v)}
    for m in store.list("member"):
        if vendor_key(m.get("name")) == vendor_key(v) or m.get("_id") == v:
            keys.add(vendor_key(m.get("company")))
    keys.discard("")
    return keys


def unmatched_vendors(store, e):
    """Vendors typed on change event `e` that match no commitment - their
    costs reach no subcontract, so the event says so."""
    known = set()
    for c in store.list("commitment"):
        if c.get("status") != "Void":
            known |= vendor_keys(store, c)
    out = []
    for l in e.get("lines") or []:
        v = (l.get("vendor") or "").strip()
        if v and vendor_key(v) not in known and v not in out:
            out.append(v)
    return out


def commitment_numbers(store, c):
    orig = sum(_f(l.get("amount")) for l in c.get("lines") or [])
    keys = vendor_keys(store, c)
    approved = pending = 0.0
    for e in store.list("event"):
        for l in e.get("lines") or []:
            if not keys or vendor_key(l.get("vendor")) not in keys:
                continue
            if e.get("status") == "Approved" or \
                    e.get("commitments_approved") == "Yes":
                approved += _f(l.get("cost"))
            elif e.get("status") in ("Open", "Pending"):
                pending += _f(l.get("cost"))
    inv = ret = paid = 0.0
    for x in store.list("cost"):
        if x.get("commitment") == c["_id"]:
            inv += _f(x.get("amount"))
            ret += _f(x.get("retainage"))
            if x.get("status") == "Paid" or x.get("paid"):
                paid += _f(x.get("amount")) - _f(x.get("retainage"))
    revised = orig + approved
    return {"original": round(orig, 2), "approved": round(approved, 2),
            "pending": round(pending, 2), "revised": round(revised, 2),
            "invoiced": round(inv, 2), "retained": round(ret, 2),
            "paid": round(paid, 2), "remaining": round(revised - inv, 2)}


def compliance(store, rec, kind="cost", today=None):
    """What stops paying this vendor, Sage 300 / Procore style:
    [text]. For a cost: its commitment's insurance and license must be
    current, a W-9 on file, and a subcontractor invoice needs a lien
    waiver. For a commitment: the same documents."""
    import datetime as _dt
    today = today or _dt.date.today().isoformat()
    soon = (_dt.date.fromisoformat(today) +
            _dt.timedelta(days=30)).isoformat()
    out = []
    c = rec if kind == "commitment" else (
        store.get("commitment", rec.get("commitment"))
        if rec.get("commitment") else None)
    if c:
        for key, label in (("insurance_expires", "Insurance"),
                           ("license_expires", "License")):
            d = c.get(key) or ""
            if d and d < today:
                out.append(f"{label} expired {d}")
            elif d and d <= soon and kind == "commitment":
                out.append(f"{label} expires {d}")
        if c.get("w9") == "No":
            out.append("No W-9 on file")
        if kind == "commitment" and not c.get("insurance_expires") and \
                c.get("type", "Subcontract") == "Subcontract" and \
                c.get("status") in ("Executed", "Out for Signature"):
            out.append("No insurance certificate")
    if kind == "cost":
        sub = (c and c.get("type", "Subcontract") == "Subcontract") or \
            rec.get("category") == "Subcontractor"
        if sub and not rec.get("waiver"):
            out.append("No lien waiver")
    return out


_BY_CODE = {}     # id(store) -> (store, version, rows): one pass per change


def by_code(store):
    """{cost code: numbers} for every code in the budget, commitments,
    change events or costs. Worked out once per store.version, so a grid
    painting hundreds of budget cells doesn't recompute it per cell
    (review 3 #3). Treat the result as read-only."""
    ver = getattr(store, "version", None)
    hit = _BY_CODE.get(id(store))
    if ver is not None and hit and hit[0] is store and hit[1] == ver:
        return hit[2]
    rows = _by_code(store)
    if ver is not None:
        if len(_BY_CODE) > 16:
            _BY_CODE.clear()
        _BY_CODE[id(store)] = (store, ver, rows)
    return rows


def _by_code(store):
    rows = {}

    def row(code, desc="", cat=""):
        k = code_key(code)
        r = rows.setdefault(k, {"code": k, "description": desc,
                                "category": cat, "original": 0.0,
                                "approved": 0.0, "pending": 0.0,
                                "committed": 0.0, "actual": 0.0,
                                "etc": None, "risk": 0.0, "budget_ids": [],
                                "unassigned": 0.0})
        if desc and not r["description"]:
            r["description"] = desc
        if cat and not r["category"]:
            r["category"] = cat
        return r
    for b in store.list("budget"):
        r = row(b.get("cost_code"), b.get("description"), b.get("category"))
        r["original"] += _f(b.get("original"))
        if b.get("etc") not in (None, ""):
            r["etc"] = (r["etc"] or 0.0) + _f(b.get("etc"))
        r["risk"] += _f(b.get("risk"))
        r["budget_ids"].append(b["_id"])
    for e in store.list("event"):
        for l in e.get("lines") or []:
            r = row(l.get("cost_code"), l.get("description"))
            if e.get("status") == "Approved":
                r["approved"] += _f(l.get("cost"))
                if not (l.get("vendor") or "").strip():
                    # no vendor: belongs to no commitment, so it is in
                    # the budget but never in "committed" (review 3 #13)
                    r["unassigned"] += _f(l.get("cost"))
            elif e.get("status") in ("Open", "Pending"):
                r["pending"] += _f(l.get("cost"))
    for c in store.list("commitment"):
        if c.get("status") == "Void":
            continue
        vendor = (c.get("vendor") or "").strip().lower()
        for l in c.get("lines") or []:
            row(l.get("cost_code"), l.get("description"))["committed"] += \
                _f(l.get("amount"))
        for e in store.list("event"):
            if e.get("status") != "Approved" and \
                    e.get("commitments_approved") != "Yes":
                continue
            for l in e.get("lines") or []:
                if vendor and (l.get("vendor") or "").strip().lower() == \
                        vendor:
                    row(l.get("cost_code"))["committed"] += _f(l.get("cost"))
    for x in store.list("cost"):
        row(x.get("cost_code"), x.get("description"),
            x.get("category"))["actual"] += _f(x.get("amount"))
    for r in rows.values():
        r["revised"] = r["original"] + r["approved"]
        r["etc_default"] = r["etc"] is None
        if r["etc"] is None:
            r["etc"] = max(r["revised"], r["committed"]) - r["actual"]
            r["etc"] = max(r["etc"], 0.0)
        # the default "what's left" can't go below zero, so say plainly
        # when a code is over (review 3 #12)
        r["flag"] = ("Over budget" if r["actual"] > r["revised"] + 0.005
                     else "Committed over budget"
                     if r["committed"] > r["revised"] + 0.005 else "")
        r["fac"] = r["actual"] + r["etc"]
        r["fac_risk"] = r["fac"] + r["risk"]
        r["variance"] = r["revised"] - r["fac"]
        r["used_pct"] = (r["actual"] / r["revised"] * 100) if r["revised"] \
            else 0.0
        for k in ("original", "approved", "pending", "committed", "actual",
                  "etc", "risk", "revised", "fac", "fac_risk", "variance",
                  "unassigned"):
            r[k] = round(r[k], 2)
    return dict(sorted(rows.items()))


def contract_numbers(store):
    orig = sum(_f(c.get("scheduled")) for c in store.list("contract"))
    appr = sum(event_price(e) for e in store.list("event")
               if e.get("status") == "Approved")
    pend = sum(event_price(e) for e in store.list("event")
               if e.get("status") in ("Open", "Pending"))
    return {"original": round(orig, 2), "approved": round(appr, 2),
            "pending": round(pend, 2), "revised": round(orig + appr, 2),
            "with_pending": round(orig + appr + pend, 2)}


def summary(store):
    rows = by_code(store)
    cats = {c: {k: 0.0 for k in ("original", "approved", "revised",
                                 "committed", "actual", "etc", "fac")}
            for c in schema.CATEGORIES + ["Other"]}
    for r in rows.values():
        c = r["category"] if r["category"] in cats else "Other"
        for k in cats[c]:
            cats[c][k] += r[k]
    tot = {k: round(sum(c[k] for c in cats.values()), 2)
           for k in ("original", "approved", "revised", "committed",
                     "actual", "etc", "fac")}
    con = contract_numbers(store)
    billed = retained = 0.0
    apps = payapps_in_order(store)
    if apps:
        try:
            v = payapp_values(store, apps[-1])
            billed = v["g702"]["4"]
            retained = v["g702"]["5"]
        except Exception:
            logging.getLogger(__name__).debug("ignored error", exc_info=True)
    received = sum(_f(a.get("received")) for a in apps)
    margin = con["revised"] - tot["revised"]
    proj_margin = con["revised"] - tot["fac"]
    return {
        "contract": con, "categories": cats, "totals": tot,
        "margin": round(margin, 2),
        "margin_pct": margin / con["revised"] * 100 if con["revised"]
        else 0.0,
        "projected_margin": round(proj_margin, 2),
        "projected_margin_pct": proj_margin / con["revised"] * 100
        if con["revised"] else 0.0,
        "billed": round(billed, 2), "retained": round(retained, 2),
        "received": round(received, 2),
        "ar": round(billed - retained - received, 2),
        "pct_complete": tot["actual"] / tot["fac"] * 100 if tot["fac"]
        else 0.0,
        "bought_out": tot["committed"] / tot["revised"] * 100
        if tot["revised"] else 0.0,
        "rows": rows,
    }


# ------------------------------------------------------------ owner billing
def payapps_in_order(store):
    return sorted(store.list("payapp"),
                  key=lambda a: (a.get("period_to") or "", a.get("_n", 0)))


def sov_lines(store):
    """Contract lines plus approved change orders, as G703 rows."""
    out = []
    for c in sorted(store.list("contract"),
                    key=lambda c: _natural(c.get("item"))):
        out.append({"item": str(c.get("item") or ""),
                    "csi": code_key(c.get("cost_code")) if
                    c.get("cost_code") else "",
                    "desc": c.get("description", ""),
                    "scheduled": round(_f(c.get("scheduled")), 2)})
    for e in sorted([e for e in store.list("event")
                     if e.get("status") == "Approved"],
                    key=lambda e: (e.get("approved") or "",
                                   _natural(e.get("co_no") or e.get("_no")))):
        no = e.get("co_no") or e.get("_no")
        out.append({"item": no, "csi": "",
                    "desc": f"{no} {e.get('title', '')}",
                    "scheduled": event_price(e), "co": e["_id"]})
    return out


def _natural(s):
    import re
    return [int(t) if t.isdigit() else t for t in
            re.split(r"(\d+)", str(s or ""))]


def money_data(store):
    """The project's billing in the shape app/money.py works with, so pay
    applications print on the same G702/G703 forms."""
    info = {"project": store.name,
            "owner": store.setting("owner") or "",
            "contractor": store.setting("contractor") or "",
            "architect": store.setting("architect") or "",
            "contract_date": store.setting("contract_date") or "",
            "contract_for": store.setting("contract_for") or "",
            "project_no": store.setting("number") or ""}
    changes = []
    for e in store.list("event"):
        if e.get("status") != "Approved":
            continue
        changes.append({"id": e["_id"], "stage": "co",
                        "executed": e.get("approved") or "0000-00-00",
                        "approved_amount": event_price(e),
                        "co_no": e.get("co_no") or e.get("_no"),
                        "title": e.get("title", "")})
    apps = []
    for i, a in enumerate(payapps_in_order(store), 1):
        lines = {}
        for l in a.get("lines") or []:
            lines[str(l.get("item"))] = {"work": _f(l.get("this_period")),
                                         "stored": _f(l.get("stored"))}
        apps.append({"no": i, "period_to": a.get("period_to") or "",
                     "date": a.get("date") or a.get("period_to") or "",
                     "lines": lines,
                     # only certified/paid apps count as previously
                     # billed (money.COUNTED, review 3 #11)
                     "status": str(a.get("status") or "Draft").lower(),
                     # the numbers it was certified with (NW-07)
                     "certified_values": a.get("certified_values"),
                     "retainage_work": _f(a.get("retainage_work") or 10),
                     "retainage_stored": _f(a.get("retainage_stored")
                                            or 10)})
    return {"info": info, "retainage_work": 10.0, "retainage_stored": 10.0,
            "sov": sov_lines(store), "changes": changes, "payapps": apps,
            "waivers": [], "counter": {}}


def certified_snapshot(store, rid):
    """The G702/G703 numbers of pay app `rid` as they stand now - kept on
    the record when it's certified, so it prints the same ever after."""
    from .. import money
    no = next(i for i, a in enumerate(payapps_in_order(store), 1)
              if a["_id"] == rid)
    data = money_data(store)
    for a in data["payapps"]:            # computed fresh, not from a copy
        if a["no"] == no:
            a.pop("certified_values", None)
            a["status"] = "draft"
    vals = money.compute(None, no, data)
    vals["status"] = "certified"
    return vals


def app_no(store, rec):
    for i, a in enumerate(payapps_in_order(store), 1):
        if a["_id"] == rec["_id"]:
            return i
    return len(payapps_in_order(store)) + 1


def payapp_values(store, rec):
    from .. import money
    data = money_data(store)
    return money.compute(None, app_no(store, rec), data)


def fill_payapp(store, rec):
    """Lines for every contract item and approved change order, with what
    was billed before (the user types this period's work)."""
    have = {str(l.get("item")): l for l in rec.get("lines") or []}
    prev = {}
    for a in payapps_in_order(store):
        if a["_id"] == rec.get("_id") or \
                (a.get("period_to") or "") >= (rec.get("period_to") or ""):
            continue
        if str(a.get("status") or "Draft").lower() not in ("certified",
                                                           "paid"):
            continue                 # not billed until certified (#11)
        for l in a.get("lines") or []:
            k = str(l.get("item"))
            prev[k] = prev.get(k, 0.0) + _f(l.get("this_period"))
    lines = []
    through = rec.get("period_to") or ""
    approved = {e["_id"]: e.get("approved") or "" for e in store.list("event")}
    for s in sov_lines(store):
        # a change order executed after this period isn't billed on it (the
        # G702/G703 leave it out, so a line here would be dropped silently)
        if s.get("co") and through and approved.get(s["co"], "") > through:
            continue
        old = have.get(s["item"], {})
        lines.append({"item": s["item"], "description": s["desc"],
                      "scheduled": s["scheduled"],
                      "previous": round(prev.get(s["item"], 0.0), 2),
                      "this_period": old.get("this_period"),
                      "stored": old.get("stored")})
    # the owner contract's retainage rule (10% -> 5% at 50% ...) - P1
    try:
        from . import contract_terms
        contract_terms.apply_retainage_rule(store, rec)
    except Exception:                                     # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning("retainage rule not applied",
                                            exc_info=True)
    return lines


def payapp_pdf(store, rec, path):
    import fitz
    from .. import money
    v = payapp_values(store, rec)
    out = fitz.open()
    money._g702(out, v)
    money._g703(out, v)
    out.set_metadata({"title": f"Pay Application {v['no']} - "
                      f"{store.name}", "creator": "QuantiSheet"})
    out.save(path)
    out.close()
    return path


def money_fmt(v):
    v = _f(v)
    return f"(${-v:,.0f})" if v < 0 else f"${v:,.0f}"


def cell(store, key, rec, c):
    """List columns that are worked out, not stored."""
    if c == "_compliance":
        if key == "cost" and rec.get("status") == "Paid":
            return ""
        issues = compliance(store, rec, key)
        return "; ".join(issues) if issues else "OK"
    if key == "commitment":
        n = commitment_numbers(store, rec)
        return money_fmt(n[c[1:]]) if c[1:] in n else ""
    if key == "budget":
        r = by_code(store).get(code_key(rec.get("cost_code")), {})
        k = {"_approved": "approved", "_revised": "revised",
             "_committed": "committed", "_actual": "actual",
             "_fac": "fac", "_variance": "variance"}.get(c)
        if c == "_flag":
            return r.get("flag", "")
        return money_fmt(r.get(k)) if k else ""
    if key == "event":
        return money_fmt(event_cost(rec) if c == "_cost" else
                         event_price(rec))
    if key == "contract":
        billed = 0.0
        for a in store.list("payapp"):
            for l in a.get("lines") or []:
                if str(l.get("item")) == str(rec.get("item")):
                    billed += _f(l.get("this_period")) + _f(l.get("stored"))
        if c == "_billed":
            return money_fmt(billed)
        sch = _f(rec.get("scheduled"))
        return f"{billed / sch * 100:.0f}%" if sch else ""
    if key == "subpay" and c == "_this_period":
        return money_fmt(sum(_f(l.get("this_period")) + _f(l.get("stored"))
                             for l in rec.get("lines") or []))
    if key == "payapp":
        if c == "_this_period":
            return money_fmt(sum(_f(l.get("this_period")) +
                                 _f(l.get("stored"))
                                 for l in rec.get("lines") or []))
        if c == "_due":
            try:
                return money_fmt(payapp_values(store, rec)["g702"]["8"])
            except Exception:
                return ""
    return ""


def sage_csv(store, path):
    """Budget and commitments as CSV for Sage 300 CRE's import (job,
    cost code, category, amount) - map the columns once in Sage's import
    wizard."""
    from .. import safecell
    job = store.setting("number") or store.name
    cat_code = {"Labor": "L", "Subcontractor": "S", "Material": "M",
                "Equipment": "E", "Other": "O", "Overhead": "O"}
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = safecell.writer(f)
        w.writerow(["Record", "Job", "Cost Code", "Category", "Description",
                    "Amount", "Vendor", "Commitment"])
        for r in by_code(store).values():
            w.writerow(["Budget", job, r["code"],
                        cat_code.get(r["category"], "O"), r["description"],
                        f"{r['revised']:.2f}", "", ""])
        for c in store.list("commitment"):
            for l in c.get("lines") or []:
                w.writerow(["Commitment", job, code_key(l.get("cost_code")),
                            "S" if c.get("type") == "Subcontract" else "M",
                            l.get("description", ""),
                            f"{_f(l.get('amount')):.2f}",
                            c.get("vendor", ""), c.get("_no", "")])
    return path
