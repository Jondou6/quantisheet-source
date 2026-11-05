"""Remember a vendor's invoice layout and the last job, cost code and
approval path used for them, and hand those back the next time an invoice
from that vendor is captured. Local only: the layout is word positions
from the PDF on this PC. Nothing is sent out.
"""
from __future__ import annotations

import json
import os
from decimal import Decimal

from .. import cents
from . import pdfutil, schema


class MemoryError(ValueError):
    pass


def _loads(raw, default):
    if not raw:
        return default
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return default


def layout_of(path) -> dict:
    """Word positions on the first page, as integer thousandths of the
    page, so the same vendor form can be recognised later."""
    if not path or not os.path.isfile(path):
        return {"words": []}
    found = [w for w in pdfutil.words(path) if w["page"] == 0][:80]
    if not found:
        return {"words": []}
    maxx = max(w["x1"] for w in found) or 1
    maxy = max(w["y1"] for w in found) or 1
    return {"words": [
        {"t": w["t"],
         "x": int(cents.round_half_up(
             Decimal(str(w["x0"])) / Decimal(str(maxx)) * 1000, "1")),
         "y": int(cents.round_half_up(
             Decimal(str(w["y0"])) / Decimal(str(maxy)) * 1000, "1"))}
        for w in found]}


def layout_score(a, b) -> int:
    """0-100, how much of the remembered wording is on the new invoice.
    An int, never a float."""
    sa = {str(w.get("t") or "").lower() for w in (a or {}).get("words") or []
          if w.get("t")}
    sb = {str(w.get("t") or "").lower() for w in (b or {}).get("words") or []
          if w.get("t")}
    sa.discard("")
    sb.discard("")
    if not sa or not sb:
        return 0
    inter = len(sa & sb)
    union = len(sa | sb)
    return int(cents.round_half_up(Decimal(inter) * 100 / Decimal(union), "1"))


def remember(office, vendor_id, path="", job_id=None, cost_code="",
             steps=None) -> int:
    """Store (or replace) what we last used for this vendor. `steps` left
    as None keeps the approval path already remembered."""
    schema.need(office, "ap.edit", "ap.approve", record_type="vendor_memory",
                record_id=vendor_id)
    schema.ensure(office.db)
    layout = layout_of(path) if path else {"words": []}
    row = office.db.one("SELECT * FROM vendor_memory WHERE vendor_id = ? AND "
                        "deleted = 0", (vendor_id,))
    fields = {"layout": layout, "job_id": job_id,
              "cost_code": cost_code or "",
              "sample_path": path or ""}
    if steps is not None:
        fields["approval_steps"] = steps
    with office.db.tx():
        if row:
            office.db.update("vendor_memory", row["id"], **fields)
            mid = row["id"]
        else:
            if "approval_steps" not in fields:
                fields["approval_steps"] = None
            mid = office.db.insert("vendor_memory", vendor_id=vendor_id,
                                   **fields)
        office.audit("change", "vendor_memory", mid, None,
                     {"vendor_id": vendor_id, "job_id": job_id,
                      "cost_code": cost_code or ""})
    return mid


def for_vendor(office, vendor_id) -> dict | None:
    schema.ensure(office.db)
    row = office.db.one("SELECT * FROM vendor_memory WHERE vendor_id = ? AND "
                        "deleted = 0 ORDER BY id DESC LIMIT 1", (vendor_id,))
    if not row:
        return None
    row["layout"] = _loads(row["layout"], {"words": []})
    row["approval_steps"] = _loads(row["approval_steps"], None)
    return row


def suggest(office, capture_result) -> dict | None:
    """Prefill for a capture() result: last job, cost code, approval path,
    and how closely the layout matches. None when this vendor is new."""
    schema.ensure(office.db)
    vid = (capture_result or {}).get("vendor_id")
    if not vid:
        return None
    row = for_vendor(office, vid)
    if not row:
        return None
    fresh = {"words": []}
    path = (capture_result or {}).get("doc_path") or ""
    if path and os.path.isfile(path):
        fresh = layout_of(path)
    return {"vendor_id": vid, "job_id": row["job_id"],
            "cost_code": row["cost_code"] or "",
            "approval_steps": row["approval_steps"],
            "layout_score": layout_score(row["layout"], fresh)}


def learn_invoice(office, iid) -> int:
    """Remember the job, first cost code and approval path of an invoice
    that was just coded."""
    from .. import ap
    inv = ap.invoice(office, iid)
    ls = ap.lines(office, iid)
    code = ls[0]["cost_code"] if ls else ""
    steps = None
    try:
        steps = ap.route(office, iid)["steps"]
    except ap.APError:
        steps = None
    return remember(office, inv["vendor_id"], inv.get("doc_path") or "",
                    inv["job_id"], code, steps)


def apply_rule(office, vendor_id) -> int:
    """Turn the remembered approval path into a vendor routing rule.
    The caller has to be allowed to edit routing; remembering a path
    does not change routing on its own."""
    from .. import ap
    office.require("routing.edit", "vendor_memory", vendor_id)
    row = for_vendor(office, vendor_id)
    if not row or not row["approval_steps"]:
        raise MemoryError("No approval path is remembered for this vendor.")
    return ap.add_rule(office, 50, row["approval_steps"], vendor_id=vendor_id)
