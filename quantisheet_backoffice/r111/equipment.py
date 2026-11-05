"""Equipment and vehicle register.

Hours come from time cards (time_lines.equipment_hours) and from logs
typed here. Service-due and inspection reminders are returned to the
screen only. Nothing is sent.
"""
from __future__ import annotations

from .. import cents, clock
from . import schema

KINDS = ("equipment", "vehicle")


class EquipmentError(ValueError):
    pass


def add_unit(office, code, name, kind="equipment", plate="", serial_no="",
             meter="0", next_service_hours=None, next_service_on="",
             next_inspection_on="") -> int:
    schema.need(office, "time.edit", record_type="equipment", record_id=code)
    if kind not in KINDS:
        raise EquipmentError(f"Kind must be one of: {', '.join(KINDS)}.")
    if not str(code).strip() or not str(name).strip():
        raise EquipmentError("A unit needs a code and a name.")
    schema.ensure(office.db)
    service_h = None
    if next_service_hours not in (None, ""):
        service_h = cents.hours(next_service_hours)
    with office.db.tx():
        uid = office.db.insert(
            "equipment", code=str(code).strip(), kind=kind,
            name=str(name).strip(), plate=plate or "",
            serial_no=serial_no or "", meter=cents.hours(meter),
            next_service_hours=service_h,
            next_service_on=str(next_service_on or ""),
            next_inspection_on=str(next_inspection_on or ""), active=1)
        office.audit("create", "equipment", uid, None,
                     {"code": code, "kind": kind})
    return uid


def units(office, include_inactive=False) -> list[dict]:
    schema.ensure(office.db)
    if include_inactive:
        return office.db.rows("SELECT * FROM equipment WHERE deleted = 0 "
                              "ORDER BY code")
    return office.db.rows("SELECT * FROM equipment WHERE deleted = 0 AND "
                          "active = 1 ORDER BY code")


def by_code(office, code) -> dict | None:
    schema.ensure(office.db)
    return office.db.one("SELECT * FROM equipment WHERE code = ? AND "
                         "deleted = 0", (code,))


def log_hours(office, unit_id, log_date, hours, note="", source="manual",
              source_key=None) -> int:
    schema.need(office, "time.edit", record_type="equipment",
                record_id=unit_id)
    schema.ensure(office.db)
    unit = office.db.get("equipment", unit_id)
    if not unit or unit.get("deleted"):
        raise EquipmentError("That unit is not on the register.")
    if source_key and office.db.one(
            "SELECT id FROM equipment_logs WHERE source_key = ? AND "
            "deleted = 0", (source_key,)):
        return office.db.one(
            "SELECT id FROM equipment_logs WHERE source_key = ? AND "
            "deleted = 0", (source_key,))["id"]
    h = cents.hours(hours)
    with office.db.tx():
        lid = office.db.insert(
            "equipment_logs", equipment_id=unit_id, log_date=str(log_date),
            hours=h, note=note or "", source=source, source_key=source_key)
        office.db.update("equipment", unit_id,
                         meter=(unit["meter"] or 0) + h)
        office.audit("create", "equipment_log", lid, None,
                     {"code": unit["code"], "hours": h, "source": source})
    return lid


def sync_time(office) -> dict:
    """Pull equipment hours off time cards. A card already pulled is
    skipped. Unknown equipment codes are listed, not invented."""
    schema.need(office, "time.edit", record_type="equipment",
                record_id="sync")
    schema.ensure(office.db)
    added, unmatched = [], []
    rows = office.db.rows(
        "SELECT id, date, equipment_code, equipment_hours FROM time_lines "
        "WHERE deleted = 0 AND equipment_code != '' AND "
        "IFNULL(equipment_hours, 0) > 0")
    for ln in rows:
        key = f"time:{ln['id']}"
        if office.db.one("SELECT id FROM equipment_logs WHERE source_key = ? "
                         "AND deleted = 0", (key,)):
            continue
        unit = by_code(office, ln["equipment_code"])
        if unit is None:
            unmatched.append(ln["equipment_code"])
            continue
        added.append(log_hours(
            office, unit["id"], ln["date"],
            cents.hours_text(ln["equipment_hours"]),
            note="Time card", source="timecard", source_key=key))
    return {"added": added, "unmatched": sorted(set(unmatched))}


def reminders(office, as_of=None) -> list[dict]:
    """Service and inspection items that are due. For the screen only."""
    schema.ensure(office.db)
    day = clock.d(as_of).isoformat() if as_of else clock.today().isoformat()
    out = []
    for u in units(office):
        if u["next_service_hours"] and (u["meter"] or 0) >= u["next_service_hours"]:
            out.append({"id": u["id"], "code": u["code"], "name": u["name"],
                        "kind": u["kind"], "why": "service",
                        "detail": "Hour meter is at "
                        f"{cents.hours_text(u['meter'])}; service was due at "
                        f"{cents.hours_text(u['next_service_hours'])}."})
        if u["next_service_on"] and u["next_service_on"] <= day:
            out.append({"id": u["id"], "code": u["code"], "name": u["name"],
                        "kind": u["kind"], "why": "service",
                        "detail": f"Service date {u['next_service_on']}."})
        if u["next_inspection_on"] and u["next_inspection_on"] <= day:
            out.append({"id": u["id"], "code": u["code"], "name": u["name"],
                        "kind": u["kind"], "why": "inspection",
                        "detail": f"Inspection date {u['next_inspection_on']}."})
    return out
