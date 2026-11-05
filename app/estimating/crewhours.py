"""Crew Hours by Pay Item: how many crew hours (and crew days) each pay
item of the civil estimate needs, which crews do the work, and its direct
cost per unit - from your own crews, rates and production rates.

The pricing is heavy.py's (crew hours = quantity / production rate per
hour; a crew's hour costs its burdened labor plus its equipment). This
module only adds it up by pay item and by crew, and lists the activities
that couldn't be priced instead of hiding them.
"""
from decimal import Decimal

from . import _io, safedb

Q2 = Decimal("0.01")


def _blank(no="", desc="", unit="", qty=Decimal(0)):
    return {"no": no, "desc": desc, "unit": unit, "owner_qty": qty,
            "hours": Decimal(0), "crew_days": Decimal(0),
            "labor": Decimal(0), "equipment": Decimal(0),
            "material": Decimal(0), "sub": Decimal(0), "direct": Decimal(0),
            "unit_cost": Decimal(0), "crews": {}, "activities": 0}


def _add(row, a, c):
    row["activities"] += 1
    for k in ("hours", "labor", "equipment", "material", "sub"):
        row[k] += c[k]
    row["crew_days"] += c["days"]
    row["direct"] += c["total"]
    if a.get("crew") and c["hours"]:
        row["crews"][a["crew"]] = row["crews"].get(a["crew"], Decimal(0)) \
            + c["hours"]


def _done(row):
    for k in ("hours", "crew_days"):
        row[k] = row[k].quantize(Q2)
    row["crews"] = {k: v.quantize(Q2) for k, v in sorted(row["crews"].items())}
    q = row["owner_qty"]
    row["unit_cost"] = (row["direct"] / q).quantize(Q2) if q else Decimal(0)
    return row


@safedb.read_only
def by_pay_item(job, lib):
    """{"items": [row per pay item], "unassigned": row, "total_hours",
    "problems": [text]}. A row: no, desc, unit, owner_qty, hours,
    crew_days, labor, equipment, material, sub, direct, unit_cost and
    crews {crew: hours}."""
    from .. import heavy
    t = heavy.totals(job, lib)
    items = {}
    for p in job.get("pay_items") or []:
        items[p["no"]] = _blank(p["no"], p.get("desc", ""), p.get("unit", ""),
                                heavy.D(p.get("owner_qty")))
    loose = _blank(desc="(not on a pay item)")
    for a, c in t["activities"]:
        _add(items.get(a.get("pay_item")) or loose, a, c)
    rows = [_done(r) for r in items.values()]
    loose = _done(loose)
    return {"items": rows, "unassigned": loose,
            "total_hours": sum((r["hours"] for r in rows), loose["hours"]),
            "problems": list(t["problems"])}


def by_crew(job, lib):
    """{crew: {"hours", "days", "cost"}} across the estimate."""
    from .. import heavy
    out = {}
    for a, c in heavy.totals(job, lib)["activities"]:
        if not a.get("crew"):
            continue
        r = out.setdefault(a["crew"], {"hours": Decimal(0),
                                       "days": Decimal(0),
                                       "cost": Decimal(0)})
        r["hours"] += c["hours"]
        r["days"] += c["days"]
        r["cost"] += c["labor"] + c["equipment"]
    return {k: {kk: vv.quantize(Q2) for kk, vv in v.items()}
            for k, v in sorted(out.items())}


def export(result, path):
    head = ["Pay item", "Description", "Unit", "Quantity", "Crew hours",
            "Crew days", "Crews", "Labor", "Equipment", "Material", "Sub",
            "Direct cost", "Direct cost per unit"]
    rows = []
    for r in result["items"] + [result["unassigned"]]:
        rows.append([r["no"], r["desc"], r["unit"], r["owner_qty"],
                     r["hours"], r["crew_days"],
                     "; ".join(f"{k} {v} h" for k, v in r["crews"].items()),
                     r["labor"], r["equipment"], r["material"], r["sub"],
                     r["direct"], r["unit_cost"]])
    return _io.write_table(path, head, rows, "Crew hours")
