"""The audit trail for AI and similarity suggestions (P3-05) - one ai_log
row per suggestion and one audit row for the suggestion and for whatever
the user then did with it (accepted, corrected, rejected, undone)."""
from __future__ import annotations

import json

from . import clock

STATUSES = ("suggested", "accepted", "corrected", "rejected", "undone",
            "discarded")


def log(office, kind, layer, record_type, record_id, proposal,
        confidence="", reason="", model="", input_hash="",
        model_version="",
        status="suggested") -> int:
    with office.db.tx():
        lid = office.db.insert(
            "ai_log", kind=kind, layer=layer, model=model,
            model_version=model_version, input_hash=input_hash,
            record_type=record_type, record_id=record_id,
            proposal=json.dumps(proposal, default=str),
            confidence=str(confidence), reason=reason, status=status)
        office.audit("ai " + status, record_type, record_id, None,
                     {"ai_log": lid, "kind": kind, "layer": layer,
                      "model": model, "model_version": model_version,
                      "proposal": proposal,
                      "confidence": str(confidence), "reason": reason})
    return lid


def get(office, log_id) -> dict:
    r = office.db.get("ai_log", log_id)
    if r is None:
        raise KeyError(log_id)
    r["proposal"] = json.loads(r["proposal"] or "null")
    r["undo"] = json.loads(r["undo"] or "null")
    return r


def decide(office, log_id, status, entry_id=None, undo=None,
           detail=None) -> None:
    if status not in STATUSES:
        raise ValueError(status)
    r = get(office, log_id)
    with office.db.tx():
        office.db.update("ai_log", log_id, status=status,
                         decided_by=office.who, decided_at=clock.iso_now(),
                         entry_id=entry_id if entry_id is not None else
                         r["entry_id"],
                         undo=json.dumps(undo) if undo is not None else
                         (json.dumps(r["undo"]) if r["undo"] else None))
        office.audit("ai " + status, r["record_type"], r["record_id"],
                     {"status": r["status"]},
                     dict({"ai_log": log_id, "entry": entry_id},
                          **(detail or {})))


def history(office, record_type=None, record_id=None) -> list[dict]:
    q, p = "SELECT * FROM ai_log WHERE deleted = 0", []
    if record_type:
        q += " AND record_type = ?"
        p.append(record_type)
    if record_id is not None:
        q += " AND record_id = ?"
        p.append(record_id)
    out = office.db.rows(q + " ORDER BY id", p)
    for r in out:
        r["proposal"] = json.loads(r["proposal"] or "null")
    return out
