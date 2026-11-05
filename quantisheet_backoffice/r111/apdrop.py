"""A folder of incoming invoice PDFs.

Point it at a local or network folder. scan() calls ap.capture on each
new PDF and, when the text layer already has a vendor, invoice number,
date and total, saves a Draft invoice. Vendor memory, when there is
some, prefills the job and cost code. The same file (same hash) is not
captured twice. .PRN files and anything that is not a PDF are skipped.
Nothing is moved or deleted out of the folder.
"""
from __future__ import annotations

import json
import os

from .. import ap, store
from . import schema, vendmem


class DropError(ValueError):
    pass


def set_folder(office, path) -> int:
    schema.need(office, "ap.edit", record_type="ap_drop", record_id=path)
    if not path or not os.path.isdir(path):
        raise DropError("Choose a folder of invoice PDFs.")
    file_ok(path)
    schema.ensure(office.db)
    with office.db.tx():
        for old in office.db.rows("SELECT id FROM ap_drop_folders WHERE "
                                  "active = 1 AND deleted = 0"):
            office.db.update("ap_drop_folders", old["id"], active=0)
        fid = office.db.insert("ap_drop_folders", path=os.path.abspath(path),
                               active=1)
        office.audit("change", "ap_drop_folder", fid, None, {"path": path})
    return fid


def file_ok(path) -> None:
    from .. import fileguard
    fileguard.refuse_company_file(path)


def folder(office) -> dict | None:
    schema.ensure(office.db)
    return office.db.one("SELECT * FROM ap_drop_folders WHERE active = 1 AND "
                         "deleted = 0 ORDER BY id DESC LIMIT 1")


def seen(office) -> list[dict]:
    schema.ensure(office.db)
    return office.db.rows("SELECT * FROM ap_drop_files WHERE deleted = 0 "
                          "ORDER BY id")


def _record(office, path, digest, status, message="", invoice_id=None,
            captured=None, job_id=None, cost_code="", steps=None) -> dict:
    fid = office.db.insert(
        "ap_drop_files", source_path=path, file_hash=digest, status=status,
        invoice_id=invoice_id, message=message or "",
        captured=captured, job_id=job_id, cost_code=cost_code or "",
        suggested_steps=steps)
    row = office.db.get("ap_drop_files", fid)
    row["captured"] = captured
    return row


def _finish(office, path, digest) -> dict:
    try:
        res = ap.capture(office, path)
    except ap.DuplicateError as e:
        return _record(office, path, digest, "duplicate", str(e),
                       captured=getattr(e, "capture", None))
    except Exception as e:                            # noqa: BLE001
        return _record(office, path, digest, "error", str(e))
    mem = None
    try:
        mem = vendmem.suggest(office, res)
    except Exception:                                 # noqa: BLE001
        mem = None
    fields = res.get("fields") or {}
    low = set(res.get("needs_confirm") or [])
    needed = ("invoice_no", "invoice_date", "total")
    job_id = (mem or {}).get("job_id")
    code = (mem or {}).get("cost_code") or ""
    steps = (mem or {}).get("approval_steps")
    if not res.get("vendor_id") or any(k not in fields or k in low
                                       for k in needed):
        return _record(office, path, digest, "needs_review",
                       "Confirm the invoice fields before saving.",
                       captured=res, job_id=job_id, cost_code=code,
                       steps=steps)
    try:
        iid = ap.create_invoice(
            office, res["vendor_id"], fields["invoice_no"][0],
            fields["invoice_date"][0], fields["total"][0],
            fields.get("tax", ("0",))[0] if "tax" in fields else "0",
            job_id=job_id, capture_result=res,
            lines=[{"cost_code": code, "amount": fields["total"][0],
                    "description": ""}])
    except ap.DuplicateError as e:
        return _record(office, path, digest, "duplicate", str(e),
                       captured=res, job_id=job_id, cost_code=code,
                       steps=steps)
    except ap.APError as e:
        return _record(office, path, digest, "needs_review", str(e),
                       captured=res, job_id=job_id, cost_code=code,
                       steps=steps)
    return _record(office, path, digest, "captured", invoice_id=iid,
                   captured=res, job_id=job_id, cost_code=code, steps=steps)


def scan(office) -> list[dict]:
    """Capture each new PDF in the folder. Safe to call on a timer."""
    schema.need(office, "ap.edit", record_type="ap_drop", record_id="scan")
    fold = folder(office)
    if fold is None:
        raise DropError("Set an invoice folder first.")
    if not os.path.isdir(fold["path"]):
        raise DropError("The invoice folder is not there anymore.")
    out = []
    names = sorted(os.listdir(fold["path"]))
    for name in names:
        if name.startswith("."):
            continue
        path = os.path.join(fold["path"], name)
        if not os.path.isfile(path):
            continue
        ext = os.path.splitext(name)[1].lower()
        if ext == ".prn" or ext != ".pdf":
            continue
        try:
            if os.path.getsize(path) <= 0:
                continue
            file_ok(path)
            digest = store.file_hash(path)
        except Exception as e:                        # noqa: BLE001
            out.append(_record(office, path, "", "error", str(e)))
            continue
        if office.db.one("SELECT id FROM ap_drop_files WHERE file_hash = ? "
                         "AND deleted = 0", (digest,)):
            continue
        out.append(_finish(office, path, digest))
    return out


def accept_duplicate(office, drop_id, reason) -> int:
    """Save a captured file that was blocked as a duplicate. `reason` is
    required; the signed-in user is stored with it."""
    schema.need(office, "ap.edit", record_type="ap_drop", record_id=drop_id)
    if not str(reason or "").strip():
        raise DropError("Say why this duplicate is allowed.")
    row = office.db.get("ap_drop_files", drop_id)
    if not row or row.get("deleted") or row["status"] != "duplicate":
        raise DropError("That file is not waiting as a duplicate.")
    cap = loads_captured(row)
    fields = cap.get("fields") or {}
    if not cap.get("vendor_id") or "total" not in fields:
        raise DropError("The capture does not have enough to save.")
    iid = ap.create_invoice(
        office, cap["vendor_id"], (fields.get("invoice_no") or [""])[0],
        (fields.get("invoice_date") or [""])[0], fields["total"][0],
        fields["tax"][0] if "tax" in fields else "0",
        job_id=row.get("job_id"), capture_result=cap,
        override_reason=str(reason).strip(),
        lines=[{"cost_code": row.get("cost_code") or "",
                "amount": fields["total"][0], "description": ""}])
    office.db.update("ap_drop_files", drop_id, status="overridden",
                     invoice_id=iid, message=str(reason).strip())
    return iid


def loads_captured(row) -> dict:
    raw = row.get("captured")
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return {}
