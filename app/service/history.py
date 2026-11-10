"""Customer history (Nov 5): everything QuantiSheet knows about one
customer or one property in one place - sites and equipment, every work
order and invoice, refrigerant log entries, agreements and their visits,
backflow tests, and callbacks (a return to the same unit within the
callback days, QW6) - with totals. Option quotes join here once they are
kept as records (phase 5).

Matching: by property id when there is one (exact); a customer name is
matched only when it is the same name ignoring case and spacing, never a
"close" name, and the result says it was matched by name.
"""
from decimal import Decimal

from .. import dmoney


def _norm(s):
    return " ".join(str(s or "").lower().split())


def customers(records, orders, agreements):
    """Every customer name seen, sorted, with how many sites each has."""
    seen = {}
    for p in records.get("properties", []):
        n = (p.get("customer") or p.get("name") or "").strip()
        if n:
            seen.setdefault(_norm(n), [n, set()])[1].add(p["id"])
    for o in orders.get("orders", []):
        n = (o.get("customer") or "").strip()
        if n:
            seen.setdefault(_norm(n), [n, set()])
            if o.get("property_id"):
                seen[_norm(n)][1].add(o["property_id"])
    for a in agreements.get("agreements", []):
        n = (a.get("customer") or "").strip()
        if n:
            seen.setdefault(_norm(n), [n, set()])
    return sorted(((v[0], len(v[1])) for v in seen.values()),
                  key=lambda x: x[0].lower())


def history(customer="", property_id="", records=None, orders=None,
            agreements=None, refrigerant=None, backflow=None, today=None,
            quotes=None):
    """One customer's (or one property's) record. Stores default to the
    saved ones."""
    from ..estimating import service as records_api
    from . import agreements as agr_api
    from . import refrigerant as ref_api
    from . import workorder as wo_api
    from . import backflow as bf_api
    records = records if records is not None else records_api.load()
    backflow = backflow if backflow is not None else bf_api.load()
    orders = orders if orders is not None else wo_api.load()
    agreements = agreements if agreements is not None else agr_api.load()
    refrigerant = refrigerant if refrigerant is not None else ref_api.load()
    from . import gbb
    quotes = quotes if quotes is not None else gbb.load()
    want = _norm(customer)

    def prop_ok(p):
        if property_id:
            return p.get("id") == property_id
        return bool(want) and _norm(p.get("customer") or p.get("name")) \
            == want

    props = [p for p in records.get("properties", []) if prop_ok(p)]
    pids = {p["id"] for p in props}
    if property_id and not props:
        pids = {property_id}
    equipment = [e for e in records.get("equipment", [])
                 if e.get("property") in pids]
    eids = {e["id"] for e in equipment}

    def mine(x):
        if x.get("property_id") and x["property_id"] in pids:
            return True
        return not property_id and bool(want) and \
            _norm(x.get("customer")) == want

    wos = [o for o in orders.get("orders", []) if mine(o)]
    wo_ids = {o["id"] for o in wos}
    invoices = [i for i in orders.get("invoices", [])
                if i.get("work_order_id") in wo_ids]
    agrs = [a for a in agreements.get("agreements", []) if mine(a)]
    units = {u["id"]: u for u in refrigerant.get("units", [])
             if u.get("property_id") in pids or u.get("equipment_id") in eids}
    ref = [dict(v, refrigerant=units[v["unit_id"]].get("refrigerant", ""),
                unit=units[v["unit_id"]].get("unit", ""))
           for v in refrigerant.get("visits", []) if v.get("unit_id") in units]
    billed = sum((dmoney.D(i.get("total") or 0) for i in invoices),
                 Decimal(0))
    profit = sum((dmoney.D(i.get("profit") or 0) for i in invoices),
                 Decimal(0))
    open_wo = [o for o in wos if o.get("status") != "closed"]
    bf = [r for r in backflow.get("reports", [])
          if (r.get("property_id") and r["property_id"] in pids) or
          (not property_id and bool(want) and
           _norm(r.get("acct_name")) == want)]
    # agreement visits (done / work order open / due / upcoming), 1.2
    visits = []
    if agrs:
        sub = {"agreements": agrs}
        visits = agr_api.visit_calendar(sub, orders, "0000-01-01",
                                        "9999-12-31", today=today)
    callbacks = [o for o in wos if o.get("callback_of")]
    qs = [q for q in quotes.get("quotes", []) if mine(q)]
    events = []
    for o in wos:
        status = o.get("status", "")
        if o.get("callback_of"):
            status += f" - CALLBACK (after {o['callback_of']})"
        events.append((o.get("opened") or "", "Work order",
                       f"{o['number']} {o.get('complaint', '')}".strip(),
                       status))
    for r in bf:
        events.append((r.get("test_date") or "", "Backflow test",
                       f"{r.get('number', '')} {r.get('dev_name', '')} "
                       f"{r.get('dev_serial', '')}".strip(),
                       f"next due {r.get('next_due', '')}".strip()))
    for v in visits:
        if v["state"] in ("due", "upcoming"):
            events.append((v["date"], "Agreement visit",
                           f"{v['number']} planned visit",
                           agr_api.STATE_TEXT[v["state"]]))
    for q in qs:
        events.append((q.get("date") or "", "Quote", gbb.summary(q),
                       q.get("status", "")))
    for i in invoices:
        events.append((i.get("date") or "", "Invoice",
                       f"{i['number']} {dmoney.fmt(i.get('total') or 0)}",
                       "sent to Sage" if i.get("sage_sent") else ""))
    for v in ref:
        events.append((v.get("date") or "", "Refrigerant",
                       f"{v.get('refrigerant', '')} added "
                       f"{v.get('lbs_added', '0')} lb".strip(),
                       v.get("tech", "")))
    events.sort(key=lambda e: e[0], reverse=True)
    return {
        "customer": customer or (props[0].get("customer") if props else ""),
        "matched_by": "property" if property_id else "name",
        "properties": props, "equipment": equipment, "work_orders": wos,
        "invoices": invoices, "agreements": agrs, "refrigerant": ref,
        "backflow": bf, "visits": visits, "callbacks": callbacks,
        "quotes": qs,
        "events": events,
        "totals": {"work_orders": len(wos), "open": len(open_wo),
                   "invoices": len(invoices),
                   "billed": dmoney.text(dmoney.cents(billed)),
                   "profit": dmoney.text(dmoney.cents(profit)),
                   "units": len(equipment), "callbacks": len(callbacks),
                   "backflow_tests": len(bf),
                   "active_agreements": sum(
                       1 for a in agrs if a.get("status", "active")
                       == "active")},
    }


def summary_lines(h):
    """Plain lines for the top of the history window or a printout."""
    t = h["totals"]
    head = h["customer"] or "This property"
    out = [f"{head}: {len(h['properties'])} site(s), {t['units']} unit(s), "
           f"{t['work_orders']} work order(s) ({t['open']} open), "
           f"{t['invoices']} invoice(s) billed {dmoney.fmt(t['billed'])}, "
           f"profit {dmoney.fmt(t['profit'])}, "
           f"{t['active_agreements']} active agreement(s), "
           f"{t['backflow_tests']} backflow test(s), "
           f"{t['callbacks']} callback(s)."]
    if h["matched_by"] == "name":
        out.append("Matched by the customer's exact name (records not tied "
                   "to a site may belong to another customer with the same "
                   "name).")
    return out
