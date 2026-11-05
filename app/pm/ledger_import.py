"""One billing ledger (P1, follows NW-09): bring the Contract & Billing
ledger kept inside a PDF into the Project Center job the drawing belongs
to, once, so the job's pay apps are the only billing from then on.

preview() says what would come in; run() brings it in - only into a job
that has no contract lines and no pay apps yet (nothing is merged or
overwritten). The PDF's own ledger is left as it was (read-only use)."""
from .. import money


class LedgerImportError(RuntimeError):
    pass


def _f(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def preview(doc, store):
    """{"contract": n, "change_orders": n, "pay_apps": n, "certified": n,
    "blocked": reason or ""}."""
    d = money.read(doc)
    sov = [s for s in d["sov"] if not s.get("co")]
    cos = [c for c in d["changes"] if c.get("stage") == "co"]
    apps = d["payapps"]
    blocked = ""
    if store.list("contract") or store.list("payapp"):
        blocked = ("The job already has contract lines or pay apps - "
                   "nothing is merged into them.")
    elif not sov and not apps:
        blocked = "This PDF has no billing to bring in."
    return {"contract": len(sov), "change_orders": len(cos),
            "pay_apps": len(apps),
            "certified": sum(1 for a in apps
                             if a.get("status") == "certified"),
            "blocked": blocked}


def run(doc, store):
    """Bring the PDF's ledger into the job. Returns the preview counts."""
    p = preview(doc, store)
    if p["blocked"]:
        raise LedgerImportError(p["blocked"])
    d = money.read(doc)
    info = d.get("info") or {}
    for k, setting in (("owner", "owner"), ("architect", "architect"),
                       ("contract_for", "contract_for")):
        if info.get(k) and not store.setting(setting):
            store.set_setting(setting, info[k])
    for s in d["sov"]:
        if s.get("co"):
            continue
        store.save_record("contract", {
            "item": str(s.get("item") or ""),
            "description": s.get("desc") or "",
            "scheduled": round(_f(s.get("scheduled")), 2),
            "cost_code": s.get("csi") or ""})
    for c in d["changes"]:
        if c.get("stage") != "co":
            continue
        store.save_record("event", {
            "title": c.get("title") or c.get("co_no") or "Change order",
            "status": "Approved", "co_no": c.get("co_no") or "",
            "approved": c.get("executed") or "",
            "days": int(c.get("approved_days") or 0),
            "lines": [{"description": c.get("title") or "",
                       "price": round(_f(c.get("approved_amount")), 2)}],
            "notes": "Brought in from the drawing's Contract & Billing "
                     "ledger."})
    for a in d["payapps"]:
        lines = [{"item": str(item), "this_period": round(_f(v.get("work")),
                                                          2),
                  "stored": round(_f(v.get("stored")), 2)}
                 for item, v in (a.get("lines") or {}).items()]
        rec = store.save_record("payapp", {
            "period_to": a.get("period_to") or "",
            "date": a.get("date") or a.get("period_to") or "",
            "status": "Draft",
            "retainage_work": _f(a.get("retainage_work")) or 10.0,
            "retainage_stored": _f(a.get("retainage_stored")) or 10.0,
            "lines": lines})
        if a.get("status") == "certified":
            rec["status"] = "Certified"
            store.save_record("payapp", rec)
    store.set_setting("billing_ledger", "project")
    return p
