"""Planning Cost Model: a planning-level (conceptual) estimate of a plant
or system - wastewater treatment, for example - from processes you
define with your own sizing parameters and your own cost curves.

    model = {"name", "design": {"Q": "2", ...},        # your design values
             "processes": [{"name", "count": "1",
                            "params": {"X": "Q * 1.5"},  # the size driver
                            "capital": {"a", "b", "c", "min", "max"},
                            "om": {"a", "b", "c"}}],
             "contingency_pct", "engineering_pct",
             "years", "rate_pct"}                      # O&M present worth

Each curve is  cost = a x X^b + c  for one unit, times the count; min /
max are the range your curve is good for (a size outside it is warned,
not refused). Parameters are formulas of the design values (the
assembly formula rules: + - * / ** and ceil, floor, round, min, max,
sqrt...). Capital subtotal + contingency (% of subtotal) + engineering
(% of subtotal + contingency) = capital total; O&M is per year, and its
present worth is O&M x the uniform-series factor when years are given.

QuantiSheet ships NO cost curves or coefficients (none from any public or
commercial cost model): every number is yours. Money is Decimal, rounded
to the cent.
"""
import math
from decimal import Decimal, InvalidOperation

from .. import dmoney
from . import _io

KIND = "planning_cost_model"
VERSION = 1


class ModelError(ValueError):
    pass


def blank(name="New model"):
    return {"kind": KIND, "version": VERSION, "name": str(name),
            "design": {}, "processes": [], "contingency_pct": "0",
            "engineering_pct": "0", "years": "", "rate_pct": "",
            "notes": ""}


def _dec(v, what, blank=None):
    if v is None or str(v).strip() == "":
        if blank is not None:
            return blank
        raise ModelError(f"{what}: type a number.")
    try:
        d = Decimal(str(v).replace(",", "").strip())
    except InvalidOperation:
        raise ModelError(f"{what}: can't read {v!r} as a number.")
    if not d.is_finite():
        raise ModelError(f"{what}: {v!r} isn't a number.")
    return d


def _eval(formula, names, what):
    from .. import assemblies
    try:
        v = assemblies.evaluate(str(formula), names)
        v = float(v)
    except Exception as e:                                # noqa: BLE001
        raise ModelError(f"{what}: {e}") from e
    if math.isnan(v) or math.isinf(v):
        raise ModelError(f"{what}: not a number")
    return v


def validate(model):
    if not isinstance(model, dict):
        raise ModelError("Not a planning cost model.")
    m = blank(model.get("name") or "Model")
    for k in m:
        if k in model and model[k] is not None and k != "kind":
            m[k] = model[k]
    if not isinstance(m["design"], dict) or not isinstance(m["processes"],
                                                           list):
        raise ModelError("A model has design values and a process list.")
    m["design"] = {str(k): str(v) for k, v in m["design"].items()}
    procs = []
    for p in m["processes"]:
        if not isinstance(p, dict):
            raise ModelError("A process must be a table of values.")
        procs.append({"name": str(p.get("name") or "Process"),
                      "count": str(p.get("count") or "1"),
                      "params": {str(k): str(v) for k, v in
                                 dict(p.get("params") or {}).items()},
                      "capital": {str(k): str(v) for k, v in
                                  dict(p.get("capital") or {}).items()},
                      "om": {str(k): str(v) for k, v in
                             dict(p.get("om") or {}).items()},
                      "notes": str(p.get("notes") or "")})
    m["processes"] = procs
    for k in ("contingency_pct", "engineering_pct", "years", "rate_pct",
              "notes", "name"):
        m[k] = str(m[k])
    return m


def _curve(c, x, what):
    a = _dec(c.get("a"), f"{what} a", Decimal(0))
    b = _dec(c.get("b"), f"{what} b", Decimal(1))
    k = _dec(c.get("c"), f"{what} c", Decimal(0))
    if not a and not k:
        return Decimal(0)
    try:
        v = a * Decimal(str(float(x) ** float(b))) + k
    except (OverflowError, ValueError, InvalidOperation) as e:
        raise ModelError(f"{what}: {e}")
    return v


def evaluate(model):
    m = validate(model)
    names = {}
    for k, v in m["design"].items():
        names[k.lower()] = _eval(v, dict(names), f"design value {k}")
    rows, warnings = [], []
    cap_sub = om = Decimal(0)
    for p in m["processes"]:
        local = dict(names)
        x = None
        for k, v in p["params"].items():
            local[k.lower()] = _eval(v, dict(local), f"{p['name']}: {k}")
            if x is None:
                x = local[k.lower()]
        x = 0.0 if x is None else x
        if x < 0:
            raise ModelError(f"{p['name']}: the size can't be negative.")
        n = _dec(p["count"], f"{p['name']} count")
        cap = _curve(p["capital"], x, f"{p['name']} capital") * n
        o = _curve(p["om"], x, f"{p['name']} O&M") * n
        lo, hi = p["capital"].get("min"), p["capital"].get("max")
        xd = Decimal(str(round(x, 6))).normalize()
        if (lo not in (None, "") and xd < _dec(lo, "min")) or \
                (hi not in (None, "") and xd > _dec(hi, "max")):
            warnings.append(f"{p['name']}: size {xd} is outside your "
                            f"curve's range ({lo or '-'} to {hi or '-'})")
        cap, o = dmoney.cents(cap), dmoney.cents(o)
        cap_sub += cap
        om += o
        rows.append({"name": p["name"], "x": xd, "count": n,
                     "capital": cap, "om": o})
    cont = dmoney.cents(cap_sub * _dec(m["contingency_pct"], "contingency",
                                       Decimal(0)) / 100)
    eng = dmoney.cents((cap_sub + cont) * _dec(m["engineering_pct"],
                                               "engineering",
                                               Decimal(0)) / 100)
    total = cap_sub + cont + eng
    t = {"capital_subtotal": dmoney.cents(cap_sub), "contingency": cont,
         "engineering": eng, "capital_total": dmoney.cents(total),
         "om_annual": dmoney.cents(om), "om_present_worth": None,
         "present_worth": None}
    if str(m["years"]).strip():
        yrs = int(_dec(m["years"], "years"))
        i = _dec(m["rate_pct"], "rate", Decimal(0)) / 100
        f = Decimal(yrs) if not i else \
            (1 - (1 + i) ** -yrs) / i
        t["om_present_worth"] = dmoney.cents(om * f)
        t["present_worth"] = t["capital_total"] + t["om_present_worth"]
    return {"name": m["name"], "processes": rows, "totals": t,
            "warnings": warnings}


def save(model, path):
    return _io.write_json(path, validate(model))


def load(path):
    try:
        data = _io.read_json(path)
    except (OSError, ValueError) as e:
        raise ModelError(f"Can't read the model: {e}")
    if not isinstance(data, dict) or data.get("kind") != KIND:
        raise ModelError("Not a QuantiSheet planning cost model file.")
    return validate(data)


def export(result, path):
    head = ["Process", "Size (X)", "Count", "Capital", "O&M per year"]
    rows = [[r["name"], r["x"], r["count"], r["capital"], r["om"]]
            for r in result["processes"]]
    t = result["totals"]
    for label, k in (("Capital subtotal", "capital_subtotal"),
                     ("Contingency", "contingency"),
                     ("Engineering", "engineering"),
                     ("Capital total", "capital_total"),
                     ("O&M per year", "om_annual"),
                     ("O&M present worth", "om_present_worth"),
                     ("Present worth", "present_worth")):
        rows.append([label, "", "", "" if t[k] is None else t[k], ""])
    for w in result["warnings"]:
        rows.append(["Warning: " + w])
    return _io.write_table(path, head, rows, "Planning model")
