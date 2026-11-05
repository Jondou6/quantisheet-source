"""Separation of duties (QS-024).

The person who entered an invoice or other approvable item, or who
coded it, is not its approver. Admins can turn on self-approval for a
one-person company. That switch is off until an Admin sets it, and
every self-approval is written to the audit log with who did it.
"""
from __future__ import annotations

from ..security import Denied
from . import schema

_TABLES = {"ap_invoice": "ap_invoices", "time_line": "time_lines",
           "per_diem": "per_diem_lines", "card_charge": "statement_lines"}
KIND_OF_TABLE = {t: k for k, t in _TABLES.items()}


class DutyError(ValueError):
    pass


def self_approval_on(office) -> bool:
    schema.ensure(office.db)
    row = office.db.one("SELECT self_approval FROM duty_settings WHERE "
                        "deleted = 0 ORDER BY id DESC LIMIT 1")
    return bool(row and row["self_approval"])


def set_self_approval(office, enabled, reason) -> None:
    """Admin only. Off unless this is called. The reason is kept."""
    if office.role != "Admin":
        raise Denied("Only an Admin can change self-approval.")
    if not str(reason or "").strip():
        raise DutyError("Say why self-approval is being changed.")
    schema.ensure(office.db)
    before = self_approval_on(office)
    flag = 1 if enabled else 0
    with office.db.tx():
        row = office.db.one("SELECT id FROM duty_settings WHERE deleted = 0 "
                            "ORDER BY id DESC LIMIT 1")
        if row:
            office.db.update("duty_settings", row["id"], self_approval=flag)
        else:
            office.db.insert("duty_settings", self_approval=flag)
        office.audit("self-approval setting", "company", 1,
                     {"on": before},
                     {"on": bool(flag), "who": office.who,
                      "why": str(reason).strip()})


def note(office, record_type, record_id, part) -> None:
    """Remember that the signed-in user entered or coded this record."""
    if not office.user:
        return
    schema.ensure(office.db)
    uid = office.user["id"]
    have = office.db.one(
        "SELECT id FROM approval_parties WHERE record_type = ? AND "
        "record_id = ? AND user_id = ? AND part = ? AND deleted = 0",
        (record_type, record_id, uid, part))
    if have:
        return
    office.db.insert("approval_parties", record_type=record_type,
                     record_id=record_id, user_id=uid, part=part)


def parties(office, record_type, record_id) -> set[int]:
    schema.ensure(office.db)
    return {r["user_id"] for r in office.db.rows(
        "SELECT user_id FROM approval_parties WHERE record_type = ? AND "
        "record_id = ? AND deleted = 0", (record_type, record_id))}


def _created_by(office, record_type, record_id):
    table = _TABLES.get(record_type)
    if not table:
        return None
    row = office.db.get(table, record_id)
    if not row or not row.get("created_by"):
        return set()
    # records from before user ids were kept: everyone with that name
    # (two people with one name are both kept from approving it)
    return {u["id"] for u in office.db.rows(
        "SELECT id FROM users WHERE name = ? AND deleted = 0",
        (row["created_by"],))}


def involved(office, record_type, record_id, owner_id=None) -> set[int]:
    ids = set(parties(office, record_type, record_id))
    if not ids:                 # older records: by the name they carry
        ids |= _created_by(office, record_type, record_id)
    if owner_id:
        ids.add(owner_id)
    return ids


def guard(office, record_type, record_id, decision="approve",
          owner_id=None) -> None:
    """Raise if this user must not approve (or reject their own) record.
    A turned-on self-approval setting lets them approve, and logs it."""
    uid = office.user["id"] if office.user else None
    if uid is None:
        return
    ids = involved(office, record_type, record_id, owner_id)
    if uid not in ids:
        return
    if decision == "approve" and self_approval_on(office):
        # waiting.approve and the approve path both call this
        last = office.db.one(
            "SELECT user, action FROM audit WHERE record_type = ? AND "
            "record_id = ? ORDER BY id DESC LIMIT 1",
            (record_type, str(record_id)))
        if not (last and last["action"] == "self-approval"
                and last["user"] == office.who):
            office.audit("self-approval", record_type, record_id, None,
                         {"who": office.who, "setting": "on"})
        return
    office.audit("denied", record_type, record_id, None,
                 {"reason": "own record", "who": office.who})
    raise Denied("You can't approve your own record.")
