"""Jobs and their read-only copies of QuantiSheet data (P1-02).

import_snapshot() copies a checked snapshot into the job record. Earlier
imported data stays: records are matched by their key, a certified pay
application is frozen the first time it is imported (never re-valued
afterwards), and nothing Back Office created (invoices, time, AP) is
touched.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from . import cents, clock, interface


@dataclass
class ImportResult:
    job_id: int
    counts: dict
    rejected: list
    changes: list = field(default_factory=list)
    contract_sum_to_date: int = 0
    certified_apps: int = 0
    taken_at: str = ""


def job_by_number(office, number: str) -> dict | None:
    return office.db.one("SELECT * FROM jobs WHERE number = ?", (number,))


def job(office, job_id: int) -> dict:
    return office.db.get("jobs", job_id)


def jobs(office) -> list[dict]:
    return office.db.rows("SELECT * FROM jobs WHERE deleted = 0 ORDER BY number")


def section(office, job_id: int, name: str) -> list[dict]:
    rows = office.db.rows(
        "SELECT data FROM snap_records WHERE job_id = ? AND section = ? "
        "AND deleted = 0 ORDER BY id", (job_id, name))
    return [json.loads(r["data"]) for r in rows]


def record(office, job_id, name, key) -> dict | None:
    r = office.db.one("SELECT data FROM snap_records WHERE job_id = ? AND "
                      "section = ? AND key = ? AND deleted = 0",
                      (job_id, name, key))
    return json.loads(r["data"]) if r else None


def cost_codes(office, job_id) -> set[str]:
    """Every code the job knows: cost codes, budget, estimate, activities,
    SOV and commitments."""
    out = set()
    for name, k in (("cost_codes", "code"), ("budget", "code"),
                    ("estimate", "code"), ("activities", "cost_code"),
                    ("sov", "cost_code")):
        out |= {r[k] for r in section(office, job_id, name) if r.get(k)}
    for c in section(office, job_id, "commitments"):
        out |= {ln["cost_code"] for ln in c["lines"] if ln.get("cost_code")}
    return out


def code_category(office, job_id, code) -> str:
    for name in ("cost_codes", "budget", "estimate"):
        for r in section(office, job_id, name):
            if r.get("code") == code and r.get("category"):
                return r["category"]
    return ""


def _what_changed(old: dict, new: dict, first: bool) -> list[str]:
    if first:
        return []
    out = []
    for k, it in new.get("cost_codes", {}).items():
        if k not in old.get("cost_codes", {}):
            out.append(f"New cost code {k} {it['description']}".rstrip())
    for k, it in new.get("changes", {}).items():
        o = old.get("changes", {}).get(k)
        label = it["co"] or it["cor"] or it["pco"] or k
        if o is None:
            out.append(f"New change {label} ({it['stage'].upper()}) "
                       f"{cents.fmt(cents.to_cents(it['amount']))}")
        elif o["stage"] != "co" and it["stage"] == "co":
            out.append(f"Change {label} executed "
                       f"{cents.fmt(cents.to_cents(it['approved_amount']))}")
    for k, it in new.get("payapps", {}).items():
        o = old.get("payapps", {}).get(k)
        if it["status"] in interface.COUNTED and \
                (o is None or o["status"] not in interface.COUNTED):
            out.append(f"Newly certified pay application {it['number']} "
                       f"(period to {it['period_to']})")
    for k, it in new.get("budget", {}).items():
        o = old.get("budget", {}).get(k)
        if o is None:
            out.append(f"New budget line {k}")
        elif (o["original"], o["revised"]) != (it["original"], it["revised"]):
            out.append(f"Budget line {k} changed: revised "
                       f"{cents.fmt(cents.to_cents(o['revised']))} -> "
                       f"{cents.fmt(cents.to_cents(it['revised']))}")
    return out


def import_snapshot(office, snap: interface.Snapshot) -> ImportResult:
    office.require("snapshot.import", "job", snap.project["number"])
    db = office.db
    with db.tx():
        j = job_by_number(office, snap.project["number"])
        first = j is None
        if first:
            jid = db.insert("jobs", number=snap.project["number"],
                            name=snap.project["name"],
                            project=snap.project,
                            retainage_work=snap.contract["retainage_work"],
                            retainage_stored=snap.contract["retainage_stored"],
                            state=snap.project.get("state", ""),
                            last_snapshot_at=snap.source.get("taken_at"),
                            source=snap.source)
        else:
            jid = j["id"]
            db.update("jobs", jid, name=snap.project["name"],
                      project=snap.project,
                      retainage_work=snap.contract["retainage_work"],
                      retainage_stored=snap.contract["retainage_stored"],
                      last_snapshot_at=snap.source.get("taken_at"),
                      source=snap.source)
            if snap.project.get("state"):
                db.update("jobs", jid, state=snap.project["state"])
        old = {}
        for r in db.rows("SELECT section, key, data FROM snap_records WHERE "
                         "job_id = ? AND deleted = 0", (jid,)):
            old.setdefault(r["section"], {})[r["key"]] = json.loads(r["data"])
        changes = _what_changed(old, snap.sections, first)
        imp = db.insert("snapshot_imports", job_id=jid,
                        taken_at=snap.source.get("taken_at"),
                        source=snap.source, file_hash=snap.file_hash,
                        counts=snap.counts(),
                        rejected=[list(r) for r in snap.rejected],
                        changes=changes)
        for name, items in snap.sections.items():
            for key, it in items.items():
                row = db.one("SELECT * FROM snap_records WHERE job_id = ? AND "
                             "section = ? AND key = ?", (jid, name, key))
                frozen = int(name == "payapps" and
                             it["status"] in interface.COUNTED)
                if row is None:
                    db.insert("snap_records", job_id=jid, section=name,
                              key=key, data=json.dumps(it, sort_keys=True),
                              first_import=imp, last_import=imp,
                              frozen=frozen)
                elif row["frozen"]:
                    if json.dumps(it, sort_keys=True) != row["data"] and \
                            name == "payapps":
                        # certified numbers never change once imported
                        prev = json.loads(row["data"])
                        new_status = it["status"]
                        if prev["status"] != new_status:
                            prev["status"] = new_status
                            prev["received"] = it.get("received")
                            prev["received_on"] = it.get("received_on")
                            db.update("snap_records", row["id"],
                                      data=json.dumps(prev, sort_keys=True),
                                      last_import=imp)
                    db.update("snap_records", row["id"], last_import=imp)
                else:
                    db.update("snap_records", row["id"],
                              data=json.dumps(it, sort_keys=True),
                              last_import=imp, frozen=frozen)
        office.audit("import", "job", jid, None,
                     {"taken_at": snap.source.get("taken_at"),
                      "counts": snap.counts(),
                      "rejected": len(snap.rejected), "changes": changes})
    sov = section(office, jid, "sov")
    chg = section(office, jid, "changes")
    apps = section(office, jid, "payapps")
    return ImportResult(
        job_id=jid, counts=snap.counts(), rejected=list(snap.rejected),
        changes=changes,
        contract_sum_to_date=interface.original_contract(sov) +
        interface.executed_changes(chg),
        certified_apps=sum(1 for a in apps
                           if a["status"] in interface.COUNTED),
        taken_at=snap.source.get("taken_at", ""))


def import_file(office, path) -> ImportResult:
    return import_snapshot(office, interface.load_snapshot(path))


def set_team(office, job_id, title, user_id):
    office.require("settings.edit", "job", job_id)
    with office.db.tx():
        office.db.insert("job_team", job_id=job_id, title=title,
                         user_id=user_id)
        office.audit("change", "job_team", job_id, None,
                     {"title": title, "user_id": user_id})


def team(office, job_id, title) -> list[int]:
    return [r["user_id"] for r in office.db.rows(
        "SELECT user_id FROM job_team WHERE job_id = ? AND title = ? AND "
        "deleted = 0", (job_id, title))]


def last_snapshot_date(office) -> str:
    r = office.db.one("SELECT MAX(taken_at) AS t FROM snapshot_imports")
    return (r or {}).get("t") or ""


def week_ending(d) -> str:
    """Saturday that ends the week (Sunday..Saturday) holding date d."""
    from datetime import timedelta
    d = clock.d(d)
    return (d + timedelta(days=(5 - d.weekday()) % 7)).isoformat()
