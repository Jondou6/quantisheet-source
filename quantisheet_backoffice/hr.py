"""Employee records and onboarding packets (P2-04), and the HR queue for
self-service changes (P2-07).

SSN, date of birth and bank routing/account numbers are stored only as
encrypted fields (crypto.FieldCrypto; key protected by DPAPI on Windows).
Everyone with hr.view sees them masked; only Payroll/HR and Admin can
reveal one, one field at a time, and every reveal is logged (without the
value). Documents (filled W-4, state form, I-9 pages, ID copies) are
encrypted files in the company's documents folder.

Government forms: Back Office ships no copies. HR attaches the current
published edition (W-4, state withholding form, I-9) and records its
edition date; check editions before each use. E-Verify is not integrated
(decision 12 = A): HR uses the government site. Nothing in this module ever
goes to QuantiSheet or its snapshot.
"""
from __future__ import annotations

import json
import os
import secrets

from . import clock, crypto, store

SENSITIVE = ("ssn", "dob", "bank_routing", "bank_account")
PLAIN = ("name", "employee_no", "address", "phone", "email", "hire_date",
         "termination_date", "status", "labor_class", "classification",
         "union_local", "language", "location", "photo_consent_on",
         "apprentice")
CHANGEABLE = ("address", "phone", "email")          # by self-service
DEFAULT_ITEMS = ["W-4 federal withholding", "State withholding form",
                 "I-9 Section 1 (employee)", "I-9 Section 2 (employer review)",
                 "Direct deposit", "Handbook acknowledgement",
                 "Certifications"]
I9_1, I9_2 = DEFAULT_ITEMS[2], DEFAULT_ITEMS[3]


class HRError(ValueError):
    pass


def _add_years(d, n):
    try:
        return d.replace(year=d.year + n)
    except ValueError:                     # 29 February
        return d.replace(year=d.year + n, day=28)


def i9_retention(hire_date, termination_date=None) -> str | None:
    """The later of 3 years after hire and 1 year after termination (have
    counsel confirm); None while the person is still employed."""
    if not termination_date:
        return None
    a = _add_years(clock.d(hire_date), 3)
    b = _add_years(clock.d(termination_date), 1)
    return max(a, b).isoformat()


# ---- employees -------------------------------------------------------------

def add_employee(office, name, employee_no, hire_date, labor_class="",
                 worker_id=None, **fields) -> int:
    office.require("hr.edit", "employee", employee_no)
    bad = [k for k in fields if k not in PLAIN + SENSITIVE]
    if bad:
        raise HRError(f"unknown employee field {bad[0]!r}")
    if office.db.one("SELECT id FROM employees WHERE employee_no = ? AND "
                     "deleted = 0", (employee_no,)):
        raise HRError(f"employee number {employee_no} is already used")
    enc = {k: office.crypto.encrypt(v) for k, v in fields.items()
           if k in SENSITIVE}
    plain = {k: v for k, v in fields.items() if k in PLAIN}
    with office.db.tx():
        if worker_id is None:
            worker_id = office.db.insert("workers", name=name,
                                         employee_no=employee_no,
                                         labor_class=labor_class, active=1)
        eid = office.db.insert("employees", worker_id=worker_id, name=name,
                               employee_no=employee_no,
                               hire_date=str(clock.d(hire_date)),
                               labor_class=labor_class,
                               status=plain.pop("status", "Active"),
                               i9_status="Not started", **plain, **enc)
        office.audit("create", "employee", eid, None,
                     {"name": name, "employee_no": employee_no,
                      "sensitive": sorted(enc)})
    return eid


def _raw(office, eid) -> dict:
    e = office.db.get("employees", eid)
    if e is None or e["deleted"]:
        raise HRError(f"no employee {eid}")
    return e


def _masked(field, value):
    if not value:
        return ""
    if field == "ssn":
        return "***-**-" + "".join(c for c in value if c.isdigit())[-4:]
    if field == "dob":
        return "**/**/****"
    return crypto.mask(value)


def employee(office, eid) -> dict:
    """The employee file with every sensitive field masked."""
    office.require("hr.view", "employee", eid)
    e = _raw(office, eid)
    for f in SENSITIVE:
        e[f] = _masked(f, office.crypto.decrypt(e[f]) if e[f] else "")
    e.pop("remote_pw", None)
    for k in ("w4", "state_form"):
        e[k] = "on file" if e[k] else ""
    return e


def employees(office) -> list[dict]:
    office.require("hr.view", "employee", "list")
    return [employee(office, r["id"]) for r in office.db.rows(
        "SELECT id FROM employees WHERE deleted = 0 ORDER BY name")]


def by_worker(office, worker_id) -> dict | None:
    return office.db.one("SELECT * FROM employees WHERE worker_id = ? AND "
                         "deleted = 0", (worker_id,))


def by_number(office, employee_no) -> dict | None:
    return office.db.one("SELECT * FROM employees WHERE employee_no = ? AND "
                         "deleted = 0", (employee_no,))


def reveal(office, eid, field) -> str:
    """The full value of one sensitive field, after a logged click."""
    if field not in SENSITIVE:
        raise HRError(f"{field} is not a protected field")
    office.require("hr.reveal", "employee", eid)
    e = _raw(office, eid)
    office.audit("reveal", "employee", eid, None, {"field": field})
    return office.decrypt_field("hr.reveal", e[field], "employee", eid) \
        if e[field] else ""


def update(office, eid, **fields) -> None:
    office.require("hr.edit", "employee", eid)
    bad = [k for k in fields if k not in PLAIN + SENSITIVE + ("w4",
                                                               "state_form")]
    if bad:
        raise HRError(f"unknown employee field {bad[0]!r}")
    e = _raw(office, eid)
    out, log_before, log_after = {}, {}, {}
    for k, v in fields.items():
        if k in SENSITIVE or k in ("w4", "state_form"):
            out[k] = office.crypto.encrypt(json.dumps(v) if isinstance(
                v, dict) else v)
            log_after[k] = "(changed)"
        else:
            out[k] = v
            log_before[k], log_after[k] = e.get(k), v
    with office.db.tx():
        office.db.update("employees", eid, **out)
        if "name" in out or "labor_class" in out:
            office.db.update("workers", e["worker_id"], **{
                k: out[k] for k in ("name", "labor_class") if k in out})
        office.audit("change", "employee", eid, log_before, log_after)


def terminate(office, eid, date) -> None:
    office.require("hr.edit", "employee", eid)
    e = _raw(office, eid)
    keep = i9_retention(e["hire_date"], date)
    with office.db.tx():
        office.db.update("employees", eid, termination_date=str(clock.d(date)),
                         status="Terminated", i9_retain_until=keep)
        office.db.update("workers", e["worker_id"], active=0)
        office.db.conn.execute(
            "UPDATE hr_documents SET retention_until = ? WHERE employee_id = ? "
            "AND type LIKE 'I-9%'", (keep, eid))
        office.audit("terminate", "employee", eid, None,
                     {"date": str(date), "i9_retain_until": keep})


# ---- documents -------------------------------------------------------------

def add_document(office, eid, doc_type, path, expires=None,
                 form_edition="") -> int:
    from . import fileguard
    office.require("hr.edit", "employee", eid)
    fileguard.refuse_company_file(path)
    e = _raw(office, eid)
    with open(path, "rb") as fh:
        data = fh.read()
    folder = os.path.join(office.documents_folder(), "hr")
    os.makedirs(folder, exist_ok=True)
    dest = os.path.join(folder, secrets.token_hex(12) + ".bin")
    token = office.crypto._f.encrypt(data)
    with open(dest, "wb") as fh:
        fh.write(token)
    keep = e["i9_retain_until"] if doc_type.startswith("I-9") else None
    with office.db.tx():
        did = office.db.insert("hr_documents", employee_id=eid, type=doc_type,
                               file_path=dest, file_hash=store.file_hash(dest),
                               uploaded_by=office.who, ts=clock.iso_now(),
                               retention_until=keep, expires=expires,
                               form_edition=form_edition)
        office.audit("attach", "employee", eid, None,
                     {"document": did, "type": doc_type,
                      "form_edition": form_edition})
    return did


def documents(office, eid) -> list[dict]:
    office.require("hr.view", "employee", eid)
    return office.db.rows("SELECT * FROM hr_documents WHERE employee_id = ? "
                          "AND deleted = 0 ORDER BY id", (eid,))


def open_document(office, did) -> bytes:
    office.require("hr.reveal", "hr_document", did)
    d = office.db.get("hr_documents", did)
    if d is None or d["deleted"]:
        raise HRError(f"no HR document {did}")
    office.audit("open document", "hr_document", did, None,
                 {"type": d["type"]})
    with open(d["file_path"], "rb") as fh:
        return office.decrypt_blob("hr.reveal", fh.read(), "hr_document",
                                   did)


# ---- onboarding ------------------------------------------------------------

def add_packet(office, name, role="", language="en", location="",
               items=None) -> int:
    office.require("hr.edit", "onboarding_packet", name)
    with office.db.tx():
        pid = office.db.insert("onboarding_packets", name=name, role=role,
                               language=language, location=location,
                               items=list(items or DEFAULT_ITEMS))
        office.audit("create", "onboarding_packet", pid, None, {"name": name})
    return pid


def packet(office, pid) -> dict:
    p = office.db.get("onboarding_packets", pid)
    p["items"] = json.loads(p["items"])
    return p


def start_onboarding(office, eid, packet_id) -> int:
    office.require("hr.edit", "employee", eid)
    items = {i: {"done": False} for i in packet(office, packet_id)["items"]}
    with office.db.tx():
        oid = office.db.insert("onboardings", employee_id=eid,
                               packet_id=packet_id, items=items,
                               status="In progress")
        office.db.update("employees", eid, status="Onboarding")
        office.audit("start onboarding", "employee", eid, None,
                     {"onboarding": oid})
    return oid


def onboarding(office, oid) -> dict:
    o = office.db.get("onboardings", oid)
    o["items"] = json.loads(o["items"])
    return o


def complete_item(office, oid, item, data=None, document=None,
                  form_edition="") -> None:
    office.require("hr.edit", "onboarding", oid)
    o = onboarding(office, oid)
    if item not in o["items"]:
        raise HRError(f"{item!r} is not in this packet")
    if o["status"] not in ("In progress", "Returned"):
        raise HRError(f"This onboarding is {o['status']}.")
    if item == I9_2:
        office.require("hr.approve", "onboarding", oid)
        if I9_1 in o["items"] and not o["items"][I9_1]["done"]:
            raise HRError("I-9 Section 1 (employee) must be done before the "
                          "employer review in Section 2.")
    did = None
    if document:
        did = add_document(office, o["employee_id"], item, document,
                           form_edition=form_edition)
    fields = {}
    if data and item.startswith("W-4"):
        fields["w4"] = data
    elif data and item.startswith("State"):
        fields["state_form"] = data
    elif data and item == "Direct deposit":
        fields.update({k: data[k] for k in ("bank_routing", "bank_account")
                       if k in data})
    if fields:
        update(office, o["employee_id"], **fields)
    o["items"][item] = {"done": True, "by": office.who, "ts": clock.iso_now(),
                        "document": did, "form_edition": form_edition}
    with office.db.tx():
        office.db.update("onboardings", oid, items=o["items"])
        if item == I9_2:
            office.db.update("employees", o["employee_id"],
                             i9_status="Section 2 done")
        office.audit("onboarding item", "onboarding", oid, None,
                     {"item": item})


def submit_onboarding(office, oid) -> None:
    office.require("hr.edit", "onboarding", oid)
    o = onboarding(office, oid)
    left = [i for i, v in o["items"].items() if not v["done"]]
    if left:
        raise HRError("Still to do: " + ", ".join(left))
    with office.db.tx():
        office.db.update("onboardings", oid, status="Waiting for HR review",
                         submitted_at=clock.iso_now())
        office.audit("submit", "onboarding", oid)


def review_onboarding(office, oid, decision, note="") -> None:
    """Employer sign-off makes it final; a rejection needs a note."""
    office.require("hr.approve", "onboarding", oid)
    o = onboarding(office, oid)
    if o["status"] != "Waiting for HR review":
        raise HRError(f"This onboarding is {o['status']}.")
    if decision == "reject" and not str(note).strip():
        raise HRError("Add a note saying what needs fixing.")
    if decision not in ("approve", "reject"):
        raise HRError("decision is approve or reject")
    with office.db.tx():
        if decision == "approve":
            office.db.update("onboardings", oid, status="Final",
                             reviewed_by=office.who,
                             reviewed_at=clock.iso_now(), note=note)
            office.db.update("employees", o["employee_id"], status="Active",
                             i9_status="Complete")
        else:
            office.db.update("onboardings", oid, status="Returned",
                             reviewed_by=office.who,
                             reviewed_at=clock.iso_now(), note=note)
        office.audit(decision, "onboarding", oid, None, {"note": note})


# ---- change requests (self-service) ----------------------------------------

def request_change(office, eid, field, value, source="desktop",
                   remote_id=None) -> int:
    if field not in CHANGEABLE:
        raise HRError(f"{field} can't be changed by request")
    _raw(office, eid)
    if remote_id and office.db.one("SELECT id FROM hr_change_requests WHERE "
                                   "remote_id = ?", (remote_id,)):
        return office.db.one("SELECT id FROM hr_change_requests WHERE "
                             "remote_id = ?", (remote_id,))["id"]
    with office.db.tx():
        rid = office.db.insert("hr_change_requests", employee_id=eid,
                               field=field,
                               value=office.crypto.encrypt(value),
                               source=source, remote_id=remote_id,
                               status="Pending")
        office.audit("change request", "employee", eid, None,
                     {"field": field, "source": source, "request": rid})
    return rid


def change_queue(office) -> list[dict]:
    office.require("hr.view", "hr_change_request", "queue")
    rows = office.db.rows("SELECT r.*, e.name FROM hr_change_requests r JOIN "
                          "employees e ON e.id = r.employee_id WHERE "
                          "r.status = 'Pending' AND r.deleted = 0 ORDER BY "
                          "r.id")
    for r in rows:
        r["value"] = office.crypto.decrypt(r["value"])
    return rows


def decide_change(office, rid, decision, note="") -> None:
    office.require("hr.approve", "hr_change_request", rid)
    r = office.db.get("hr_change_requests", rid)
    if r["status"] != "Pending":
        raise HRError(f"This request is {r['status']}.")
    with office.db.tx():
        if decision == "approve":
            e = _raw(office, r["employee_id"])
            new = office.crypto.decrypt(r["value"])
            office.db.update("employees", e["id"], **{r["field"]: new})
            office.audit("change", "employee", e["id"],
                         {r["field"]: e[r["field"]]}, {r["field"]: new,
                                                       "request": rid})
            status = "Approved"
        elif decision == "reject":
            status = "Rejected"
        else:
            raise HRError("decision is approve or reject")
        office.db.update("hr_change_requests", rid, status=status,
                         decided_by=office.who, decided_at=clock.iso_now(),
                         note=note)
        office.audit(decision, "hr_change_request", rid, None, {"note": note})


def queue(office) -> dict:
    """HR review queue: onboarding packets and self-service changes."""
    office.require("hr.view", "hr_queue", "")
    ob = office.db.rows("SELECT o.*, e.name FROM onboardings o JOIN employees "
                        "e ON e.id = o.employee_id WHERE o.status = "
                        "'Waiting for HR review' AND o.deleted = 0")
    return {"onboarding": ob, "changes": change_queue(office)}
