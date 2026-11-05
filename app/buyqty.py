"""Buy quantities (Nov 4, takeoff list #10): what to order for a takeoff
item - sheets of drywall, boxes of tile, rolls of underlayment - from its
total, the size of one (32 sf a sheet, 10 sf a box...) and a waste
allowance, always rounded UP to whole ones.

The rules are kept with the job (quantisheet_buy.json, by item name), so
the Quantities panel and the totals show "buy 47 sheets" next to the
measured total.
"""
import json
import math
from decimal import ROUND_CEILING, Decimal

from . import embfiles

FILE = "quantisheet_buy.json"


def rules(doc):
    try:
        if FILE in doc.embfile_names():
            d = json.loads(doc.embfile_get(FILE).decode("utf-8"))
            return d if isinstance(d, dict) else {}
    except Exception:                                     # noqa: BLE001
        pass
    return {}


def set_rule(doc, group, per, unit="each", waste=0.0):
    """Set (per > 0) or clear (per falsy) the rule for an item."""
    d = rules(doc)
    if not per:
        d.pop(group, None)
    else:
        per = float(per)
        if per <= 0 or not math.isfinite(per):
            raise ValueError("the size of one must be more than 0")
        waste = float(waste or 0)
        if waste < 0 or waste > 500:
            raise ValueError("waste must be 0-500 %")
        d[group] = {"per": per, "unit": str(unit or "each").strip() or
                    "each", "waste": waste}
    embfiles.put(doc, FILE, json.dumps(d).encode("utf-8"),
                 "QuantiSheet job data")
    return d


def buy(total, rule):
    """Whole units to order: total x (1 + waste) / per, rounded up."""
    if not rule or not rule.get("per"):
        return None
    t = Decimal(str(total)) * (1 + Decimal(str(rule.get("waste") or 0)) /
                               100) / Decimal(str(rule["per"]))
    # a hair over a whole number from float takeoff (12.0000001) is 12
    t = t.quantize(Decimal("0.0001"))
    return int(t.to_integral_value(rounding=ROUND_CEILING))


def summary(doc, totals):
    """{group: (buy, unit)} for {(group, type, unit): total} totals."""
    rs = rules(doc)
    out = {}
    for (group, _t, _u), total in totals.items():
        r = rs.get(group or "")
        if r:
            n = buy(total, r)
            if n is not None:
                out[group] = (n, r["unit"])
    return out
