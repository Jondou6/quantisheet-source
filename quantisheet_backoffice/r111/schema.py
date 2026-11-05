"""Tables for release 1.1.1.

New tables only. An existing company file gains them on first use
(CREATE TABLE IF NOT EXISTS) and any column added after a table first
shipped is ALTER TABLE ... ADD COLUMN, so rows already stored stay.
Nothing in an older table is rebuilt or dropped.
"""
from __future__ import annotations

from .. import store

# (column, sql type) in the order a new database creates them.
# A column listed here that an older file lacks is added in place.
TABLES = {
    "sage_imports": (
        ("job_id", "INTEGER"), ("job_number", "TEXT"), ("job_name", "TEXT"),
        ("address", "TEXT"), ("source_name", "TEXT"), ("source_path", "TEXT"),
        ("source_hash", "TEXT"), ("status", "TEXT"), ("page_count", "INTEGER"),
        ("note", "TEXT")),
    "sage_lines": (
        ("import_id", "INTEGER"), ("line_no", "INTEGER"),
        ("cost_code", "TEXT"), ("description", "TEXT"), ("category", "TEXT"),
        ("is_total", "INTEGER"), ("original", "INTEGER"),
        ("changes_amt", "INTEGER"), ("total_estimate", "INTEGER"),
        ("committed", "INTEGER"), ("remaining", "INTEGER"), ("jtd", "INTEGER"),
        ("variance", "INTEGER"), ("overrun", "INTEGER")),
    "ap_drop_folders": (("path", "TEXT"), ("active", "INTEGER")),
    # a vendor whose bills are often the same amount (rent, fuel cards):
    # same vendor + amount within 7 days isn't a duplicate (review, Nov 4)
    "vendor_flags": (("vendor_id", "INTEGER"), ("recurring", "INTEGER")),
    "ap_drop_files": (
        ("source_path", "TEXT"), ("file_hash", "TEXT"), ("status", "TEXT"),
        ("invoice_id", "INTEGER"), ("message", "TEXT"), ("captured", "TEXT"),
        ("job_id", "INTEGER"), ("cost_code", "TEXT"),
        ("suggested_steps", "TEXT")),
    "ap_stamps": (
        ("invoice_id", "INTEGER"), ("original_path", "TEXT"),
        ("original_hash", "TEXT"), ("stamped_path", "TEXT"),
        ("stamped_hash", "TEXT"), ("job_text", "TEXT"), ("cost_code", "TEXT"),
        ("amount", "INTEGER"), ("approver", "TEXT"), ("stamped_on", "TEXT")),
    "vendor_memory": (
        ("vendor_id", "INTEGER"), ("layout", "TEXT"), ("job_id", "INTEGER"),
        ("cost_code", "TEXT"), ("approval_steps", "TEXT"),
        ("sample_path", "TEXT")),
    "safety_topics": (("title", "TEXT"), ("body", "TEXT"), ("active", "INTEGER")),
    "safety_meetings": (
        ("number", "TEXT"), ("meeting_date", "TEXT"), ("job_id", "INTEGER"),
        ("topic_id", "INTEGER"), ("title", "TEXT"), ("notes", "TEXT"),
        ("presenter", "TEXT")),
    "safety_attendees": (
        ("meeting_id", "INTEGER"), ("name", "TEXT"), ("company", "TEXT"),
        ("signed", "INTEGER"), ("signature", "TEXT"), ("signed_at", "TEXT")),
    "incidents": (
        ("number", "TEXT"), ("job_id", "INTEGER"), ("kind", "TEXT"),
        ("occurred_on", "TEXT"), ("occurred_time", "TEXT"), ("weather", "TEXT"),
        ("location", "TEXT"), ("description", "TEXT"), ("status", "TEXT"),
        ("supervisor", "TEXT"), ("reviewed_at", "TEXT"), ("review_note", "TEXT")),
    "incident_people": (
        ("incident_id", "INTEGER"), ("role", "TEXT"), ("name", "TEXT"),
        ("company", "TEXT"), ("job_title", "TEXT"), ("statement", "TEXT"),
        ("recordable", "INTEGER"), ("classification", "TEXT"),
        ("days_away", "INTEGER"), ("days_restricted", "INTEGER"),
        ("privacy", "INTEGER")),
    "incident_photos": (
        ("incident_id", "INTEGER"), ("file_path", "TEXT"), ("caption", "TEXT")),
    "jha_plans": (
        ("plan_date", "TEXT"), ("job_id", "INTEGER"), ("task", "TEXT"),
        ("hazards", "TEXT"), ("controls", "TEXT"), ("copied_from", "INTEGER")),
    "jha_signatures": (
        ("plan_id", "INTEGER"), ("name", "TEXT"), ("signature", "TEXT"),
        ("signed_at", "TEXT")),
    "equipment": (
        ("code", "TEXT"), ("kind", "TEXT"), ("name", "TEXT"), ("plate", "TEXT"),
        ("serial_no", "TEXT"), ("meter", "INTEGER"),
        ("next_service_hours", "INTEGER"), ("next_service_on", "TEXT"),
        ("next_inspection_on", "TEXT"), ("active", "INTEGER")),
    "equipment_logs": (
        ("equipment_id", "INTEGER"), ("log_date", "TEXT"), ("hours", "INTEGER"),
        ("note", "TEXT"), ("source", "TEXT"), ("source_key", "TEXT")),
    "crew_assignments": (
        ("work_date", "TEXT"), ("crew_id", "INTEGER"), ("job_id", "INTEGER"),
        ("cost_code", "TEXT"), ("hours", "INTEGER"), ("note", "TEXT")),
    "job_closeouts": (
        ("job_id", "INTEGER"), ("closed_on", "TEXT"), ("note", "TEXT")),
    "warranty_calls": (
        ("number", "TEXT"), ("job_id", "INTEGER"), ("caller", "TEXT"),
        ("phone", "TEXT"), ("issue", "TEXT"), ("assigned", "TEXT"),
        ("status", "TEXT"), ("opened_on", "TEXT"), ("closed_on", "TEXT"),
        ("note", "TEXT")),
    "warranty_photos": (
        ("call_id", "INTEGER"), ("file_path", "TEXT"), ("caption", "TEXT")),
    "qa_templates": (("name", "TEXT"), ("items", "TEXT"), ("active", "INTEGER")),
    # QS-020: who allowed a duplicate, and why
    "dup_overrides": (
        ("invoice_id", "INTEGER"), ("doc_hash", "TEXT"), ("who", "TEXT"),
        ("user_id", "INTEGER"), ("why", "TEXT"), ("matches", "TEXT")),
    # QS-024: who entered or coded an approvable record; self-approval switch
    "approval_parties": (
        ("record_type", "TEXT"), ("record_id", "INTEGER"),
        ("user_id", "INTEGER"), ("part", "TEXT")),
    "duty_settings": (("self_approval", "INTEGER"),),
}


def has_table(db, name: str) -> bool:
    return db.one("SELECT name FROM sqlite_master WHERE type = 'table' AND "
                  "name = ?", (name,)) is not None


def ensure(db) -> None:
    """Create any missing 1.1.1 table and add any missing column."""
    for name, cols in TABLES.items():
        body = ", ".join(f"{col} {typ}" for col, typ in cols)
        db.conn.execute(
            f"CREATE TABLE IF NOT EXISTS {name} ({store.STD}, {body})")
        have = {r[1] for r in db.conn.execute(f"PRAGMA table_info({name})")}
        for col, typ in cols:
            if col not in have:
                db.conn.execute(
                    f"ALTER TABLE {name} ADD COLUMN {col} {typ}")


def need(office, *perms, record_type="", record_id="") -> None:
    """Pass when the signed-in user holds any of `perms`."""
    if office.user and any(office.can(p) for p in perms):
        return
    office.require(perms[0], record_type, record_id)
