"""Sub pay apps feeding the owner pay app (P1: "8 subs submit SOV
progress; GC reviews; totals roll into owner app 4").

A sub pay app (Sub Pay Apps) is a sub's monthly billing against its
subcontract's schedule of values: fill() starts it from the commitment's
lines with what was approved before. The sub submits it (through the
project hub, where only the GC's PM or accountant may approve, reject or
bill it); review() approves or rejects it with a note.

roll_up() totals the APPROVED sub apps of the owner app's period by cost
code; feed_owner() writes those totals into the owner pay app's "this
period" and "stored" on the contract line with the same cost code. A line
the PM already typed is left alone and reported; a cost code with no
contract line stops the roll-up (it would never reach the owner) unless
the PM says to go ahead. The fed sub apps are marked
Billed with the owner app they went into, so the same work is never
billed to the owner twice."""
from .cost import _f, code_key, fill_payapp, payapps_in_order, sov_lines
from ..dmoney import c2 as _c2


class SubPayError(RuntimeError):
    pass


def _approved_before(store, rec):
    """{cost_code: work + stored} approved on this subcontract before
    rec's period."""
    prev = {}
    for a in store.list("subpay"):
        if a["_id"] == rec.get("_id") or \
                a.get("commitment") != rec.get("commitment"):
            continue
        if a.get("status") not in ("Approved", "Billed"):
            continue
        if (a.get("period_to") or "") >= (rec.get("period_to") or ""):
            continue
        for l in a.get("lines") or []:
            k = code_key(l.get("cost_code"))
            prev[k] = prev.get(k, 0.0) + _f(l.get("this_period")) + \
                _f(l.get("stored"))
    return prev


def fill(store, rec):
    """Lines from the subcontract's schedule of values, with what was
    approved before; this period's numbers already typed are kept."""
    c = store.get("commitment", rec.get("commitment") or "")
    if not c:
        raise SubPayError("Pick the subcontract first.")
    have = {code_key(l.get("cost_code")): l for l in rec.get("lines") or []}
    prev = _approved_before(store, rec)
    lines = []
    for l in c.get("lines") or []:
        k = code_key(l.get("cost_code"))
        old = have.get(k, {})
        lines.append({"cost_code": l.get("cost_code") or "",
                      "description": l.get("description") or "",
                      "scheduled": _c2(_f(l.get("amount"))),
                      "previous": _c2(prev.get(k, 0.0)),
                      "this_period": old.get("this_period"),
                      "stored": old.get("stored")})
    if not rec.get("retainage") and c.get("retainage") not in (None, ""):
        rec["retainage"] = c.get("retainage")
    return lines


def problems(rec):
    """Lines billed past their scheduled value (shown at review)."""
    out = []
    for l in rec.get("lines") or []:
        total = _f(l.get("previous")) + _f(l.get("this_period")) + \
            _f(l.get("stored"))
        if _f(l.get("scheduled")) and total > _f(l.get("scheduled")) + 0.005:
            out.append(f"{l.get('cost_code')}: billed {_c2(total):,.2f} of "
                       f"{_c2(_f(l.get('scheduled'))):,.2f}")
    return out


def review(store, rid, approve, by="", note=""):
    rec = store.get("subpay", rid)
    if not rec:
        raise SubPayError("No such sub pay app.")
    if rec.get("status") not in ("Submitted", "Draft"):
        raise SubPayError(f"It's {rec.get('status')} - nothing to review.")
    if approve and problems(rec) and not note:
        raise SubPayError("It bills more than the schedule of values - "
                          "add a review note to approve it anyway:\n" +
                          "\n".join(problems(rec)))
    rec["status"] = "Approved" if approve else "Rejected"
    rec["reviewed_by"] = by or store.me
    rec["review_note"] = note
    return store.save_record("subpay", rec)


def _window(store, payapp):
    """(after, upto): the owner app covers sub periods after the previous
    owner app's period and up to its own."""
    upto = payapp.get("period_to") or ""
    after = ""
    for a in payapps_in_order(store):
        p = a.get("period_to") or ""
        if a["_id"] != payapp.get("_id") and p < upto and p > after:
            after = p
    return after, upto


def roll_up(store, payapp):
    """{"by_code": {code: {"work", "stored"}}, "subs": [ids],
    "work": total, "stored": total} - approved, not yet billed, in the
    owner app's period."""
    after, upto = _window(store, payapp)
    by, ids = {}, []
    for a in store.list("subpay"):
        if a.get("status") != "Approved":
            continue
        p = a.get("period_to") or ""
        if not (after < p <= upto):
            continue
        ids.append(a["_id"])
        for l in a.get("lines") or []:
            k = code_key(l.get("cost_code"))
            t = by.setdefault(k, {"work": 0.0, "stored": 0.0})
            t["work"] += _f(l.get("this_period"))
            t["stored"] += _f(l.get("stored"))
    return {"by_code": by, "subs": ids,
            "work": _c2(sum(t["work"] for t in by.values())),
            "stored": _c2(sum(t["stored"] for t in by.values()))}


def feed_owner(store, payapp, allow_unmatched=False):
    """Put the rolled-up sub billing into the owner pay app (a Draft).
    Returns {"fed": [items], "kept": [items], "unmatched": [codes],
    "work", "stored", "subs"}; the record is saved."""
    if payapp.get("status") not in (None, "", "Draft"):
        raise SubPayError("Only a draft owner pay app can take sub "
                          "billing.")
    r = roll_up(store, payapp)
    if not r["subs"]:
        raise SubPayError("No approved sub pay apps for this period.")
    code_of = {s["item"]: s["csi"] for s in sov_lines(store) if s["csi"]}
    missing = sorted(set(r["by_code"]) - set(code_of.values()))
    if missing and not allow_unmatched:
        raise SubPayError("Sub billing has cost codes with no owner "
                          "contract line, so it would not reach the owner: "
                          + ", ".join(missing) + ". Add contract lines "
                          "with those cost codes (or bill it by hand).")
    if not payapp.get("lines"):
        payapp["lines"] = fill_payapp(store, payapp)
    lines = {str(l.get("item")): l for l in payapp["lines"]}
    fed, kept, used = [], [], set()
    for item, csi in code_of.items():
        t = r["by_code"].get(csi)
        ln = lines.get(item)
        if not t or ln is None:
            continue
        used.add(csi)
        if _f(ln.get("this_period")) or _f(ln.get("stored")):
            kept.append(item)
            continue
        ln["this_period"] = _c2(t["work"])
        ln["stored"] = _c2(t["stored"])
        fed.append(item)
    unmatched = sorted(set(r["by_code"]) - used)
    payapp["sub_billing"] = r["subs"]
    rec = store.save_record("payapp", payapp)
    for sid in r["subs"]:
        s = store.get("subpay", sid)
        s["status"] = "Billed"
        s["billed_in"] = rec["_id"]
        store.save_record("subpay", s)
    return {"fed": fed, "kept": kept, "unmatched": unmatched,
            "work": r["work"], "stored": r["stored"], "subs": r["subs"],
            "payapp": rec}
