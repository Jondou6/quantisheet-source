"""Estimate -> budget -> commitments (P1: "Award estimate creates budget
by cost code and draft commitments; totals tie").

award() turns the drawing's priced estimate (estimate_export.collect -
takeoff lines and assemblies, the same lines the estimate exports) into
the Project Center job's budget: one budget line per cost code and cost
category, so the budget total equals the estimate total to the cent. The
subcontract part of each CSI division becomes one DRAFT commitment
(vendor left blank for the PM to pick), with a line per cost code.
Nothing is sent to anyone. A job that already has budget lines is left
alone (nothing merged)."""
from decimal import Decimal

CATEGORY = {"material": "Material", "labor": "Labor",
            "equipment": "Equipment", "subcontract": "Subcontractor",
            "subcontractor": "Subcontractor", "sub": "Subcontractor"}


class AwardError(RuntimeError):
    pass


def _cat(t):
    return CATEGORY.get(str(t or "").strip().lower(), "Other")


def plan(doc):
    """{"budget": [{cost_code, description, category, original}],
    "commitments": [{title, lines}], "total": Decimal} from the estimate,
    without saving anything."""
    from .. import estimate_export as ee
    lines = ee.collect(doc)
    budget = {}
    subs = {}
    total = Decimal("0")
    for ln in lines:
        code = ln["code"] or "00 00 00"
        for t, amt in ln["by_type"].items():
            amt = Decimal(amt)
            if not amt:
                continue
            cat = _cat(t)
            k = (code, cat)
            b = budget.setdefault(k, {"cost_code": code,
                                      "description": ln["title"] or
                                      ln["desc"], "category": cat,
                                      "original": Decimal("0")})
            b["original"] += amt
            total += amt
            if cat == "Subcontractor":
                div = ln["division"] or "00"
                c = subs.setdefault(div, {"title": f"Division {div} "
                                          f"{ln['title'] or ''} (from the "
                                          f"estimate)".replace("  ", " "),
                                          "lines": {}})
                c["lines"][code] = c["lines"].get(code, Decimal("0")) + amt
    return {"budget": [budget[k] for k in sorted(budget)],
            "commitments": [{"title": subs[d]["title"],
                             "lines": [{"cost_code": k, "amount": v}
                                       for k, v in sorted(
                                           subs[d]["lines"].items())]}
                            for d in sorted(subs)],
            "total": total}


def award(doc, store):
    """Save the plan into the job. Returns the plan. Refused when the job
    already has budget lines or the estimate has no priced lines."""
    if store.list("budget"):
        raise AwardError("The job already has budget lines - nothing was "
                         "added (no merging).")
    p = plan(doc)
    if not p["budget"]:
        raise AwardError("The estimate has no priced lines yet (Estimate > "
                         "Price These).")
    for b in p["budget"]:
        store.save_record("budget", dict(b, original=float(b["original"]),
                                         notes="From the awarded "
                                               "estimate."))
    for c in p["commitments"]:
        store.save_record("commitment", {
            "title": c["title"], "type": "Subcontract", "status": "Draft",
            "lines": [{"cost_code": x["cost_code"],
                       "description": "From the estimate",
                       "amount": float(x["amount"])} for x in c["lines"]],
            "notes": "Draft from the awarded estimate - pick the "
                     "subcontractor before sending."})
    store.set_setting("awarded_estimate_total", str(p["total"]))
    return p
