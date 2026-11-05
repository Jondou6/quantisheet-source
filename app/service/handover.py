"""Build-to-service handover.

At closeout, equipment named in approved submittals and in O&M documents
(model, serial, warranty) becomes Equipment & Service Records. The
warranty start is the closeout date. A preventive-maintenance agreement
is offered; it is saved only when the office accepts it.

No network calls.
"""
import datetime as dt
import os
import re

from ..estimating import service as records_api
from . import files

APPROVED = {"Approved", "Approved as Noted"}

# Labeled lines in a submittal description or an O&M document.
_FIELD = re.compile(
    r"^(?P<k>make|manufacturer|"
    r"model(?:\s+(?:no\.?|number|#))?|"
    r"serial(?:\s+(?:no\.?|number|#))?|"
    r"warranty|equipment|unit|type)\s*[:#]\s*(?P<v>.+?)\s*$",
    re.I)
_MONTHS = re.compile(r"(\d+)\s*months?\b", re.I)
_YEARS = re.compile(r"(\d+)\s*years?\b", re.I)


class HandoverError(ValueError):
    pass


def _canon(key):
    k = key.lower()
    if k.startswith("make") or k.startswith("manufacturer"):
        return "make"
    if k.startswith("model"):
        return "model"
    if k.startswith("serial"):
        return "serial"
    if k.startswith("warranty"):
        return "warranty"
    return "kind"


def _months(text):
    m = _MONTHS.search(text or "")
    if m:
        return int(m.group(1))
    y = _YEARS.search(text or "")
    if y:
        return int(y.group(1)) * 12
    return None


def _blank_eq():
    return {"kind": "", "make": "", "model": "", "serial": "",
            "warranty_months": None}


def parse_text(text):
    """Equipment blocks from labeled lines (Make, Model, Serial, Warranty)."""
    lines = [ln.strip() for ln in str(text or "").splitlines()]
    blocks, cur = [], []
    for ln in lines:
        if not ln:
            if cur:
                blocks.append(cur)
                cur = []
            continue
        cur.append(ln)
    if cur:
        blocks.append(cur)
    found = []
    for block in blocks:
        found.extend(_one_block(block))
    return found


def _one_block(lines):
    items, cur = [], None

    def finish():
        nonlocal cur
        if cur and (cur.get("model") or cur.get("serial")):
            if not cur.get("kind"):
                cur["kind"] = "Equipment"
            items.append(cur)
        cur = None

    for ln in lines:
        m = _FIELD.match(ln)
        if not m:
            if cur is None:
                cur = _blank_eq()
                cur["kind"] = files.txt(ln, 80)
            elif not cur.get("kind"):
                cur["kind"] = files.txt(ln, 80)
            continue
        key = _canon(m.group("k"))
        val = files.txt(m.group("v"), 120)
        if cur and cur.get(key) and key in ("model", "serial", "kind"):
            finish()
        if cur is None:
            cur = _blank_eq()
        if key == "warranty":
            months = _months(val)
            if months is not None:
                cur["warranty_months"] = months
        elif val:
            cur[key] = val
    finish()
    return items


def text_of_pdf(path):
    import fitz
    with fitz.open(path) as doc:
        return "\n".join(page.get_text() for page in doc)


def _attachment_text(pm_store, rec):
    if pm_store is None:
        return ""
    chunks = []
    for a in rec.get("attachments") or []:
        name = (a.get("name") or "")
        if not name.lower().endswith(".pdf"):
            continue
        try:
            path = pm_store.attachment_path(a)
        except Exception:                                 # noqa: BLE001
            continue
        if path and os.path.isfile(path):
            try:
                chunks.append(text_of_pdf(path))
            except Exception:                             # noqa: BLE001
                continue
    return "\n".join(chunks)


def _already(records, property_id, item):
    serial = (item.get("serial") or "").lower()
    model = (item.get("model") or "").lower()
    kind = (item.get("kind") or "").lower()
    for eq in records.get("equipment") or []:
        if eq.get("property") != property_id:
            continue
        if serial and (eq.get("serial") or "").lower() == serial:
            return True
        if not serial and model and (eq.get("model") or "").lower() == model \
                and (eq.get("kind") or "").lower() == kind:
            return True
    return False


def _offer(records, property_id, warranty_start):
    prop = records_api.find(records, property_id)
    start = dt.date.fromisoformat(warranty_start)
    renewal = records_api.add_interval(start, 1, "years").isoformat()
    return {"property_id": property_id,
            "customer": (prop.get("customer") or prop.get("name") or ""),
            "site": prop.get("name") or "",
            "price": "", "visits_per_year": 2, "start": warranty_start,
            "renewal": renewal,
            "notes": "Offered at closeout from approved submittals and "
                     "O&M documents."}


def import_closeout(records, property_id, warranty_start, submittals=None,
                    documents=(), pm_store=None):
    """Create service-record equipment and offer a PM agreement.

    Approved submittals are read from `submittals` or, when that is None,
    from `pm_store`. `documents` are O&M PDF paths the office already chose.
    The agreement is not saved; pass the offer to accept_offer.
    """
    prop = records_api.find(records, property_id) if records else None
    if not prop or "customer" not in prop:
        raise HandoverError("That site isn't in the service records.")
    try:
        warranty_start = files.iso_date(warranty_start, "Warranty start",
                                        blank_ok=False)
    except files.FileError as e:
        raise HandoverError(str(e)) from e
    if submittals is None and pm_store is not None:
        recs = pm_store.list("submittal")
    else:
        recs = list(submittals or [])
    created, skipped, seen = [], [], []
    blobs = []
    for rec in recs:
        if rec.get("status") not in APPROVED:
            continue
        text = "\n".join([rec.get("title") or "", rec.get("description") or "",
                          _attachment_text(pm_store, rec)])
        source = " ".join(p for p in (rec.get("_no"), rec.get("title")) if p)
        blobs.append((text, source or "Submittal"))
    for path in documents or []:
        if not path or not os.path.isfile(path):
            skipped.append({"title": os.path.basename(str(path)),
                            "why": "file not found"})
            continue
        try:
            blobs.append((text_of_pdf(path), os.path.basename(path)))
        except Exception as e:                            # noqa: BLE001
            skipped.append({"title": os.path.basename(path),
                            "why": f"could not read the PDF ({e})"})
    for text, source in blobs:
        for item in parse_text(text):
            key = ((item.get("serial") or "").lower(),
                   (item.get("model") or "").lower(),
                   (item.get("kind") or "").lower())
            if key in seen:
                continue
            seen.append(key)
            if _already(records, property_id, item):
                skipped.append({"title": item.get("model") or item.get("kind"),
                                "why": "already on the service record"})
                continue
            eid = records_api.add_equipment(
                records, property_id, item["kind"], make=item.get("make") or "",
                model=item.get("model") or "", serial=item.get("serial") or "",
                installed=warranty_start,
                warranty_months=item.get("warranty_months"),
                notes=f"Closeout: {source}")
            item = dict(item, id=eid, source=source)
            created.append(item)
    offer = _offer(records, property_id, warranty_start) \
        if created or any(s["why"].startswith("already") for s in skipped) \
        else None
    return {"equipment_ids": [c["id"] for c in created], "created": created,
            "skipped": skipped, "offer": offer}


def accept_offer(offer, agreements, price, visits_per_year=None,
                 records=None):
    """Save the offered preventive-maintenance agreement."""
    from . import agreements as agr
    if not offer:
        raise HandoverError("There is no agreement to offer.")
    return agr.add(agreements, customer=offer.get("customer") or "",
                   price=price,
                   visits_per_year=visits_per_year or offer.get(
                       "visits_per_year") or 2,
                   renewal=offer["renewal"], start=offer.get("start") or "",
                   property_id=offer.get("property_id") or "",
                   site=offer.get("site") or "",
                   notes=offer.get("notes") or "", records=records)
