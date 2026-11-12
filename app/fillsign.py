"""Fill a form from what QuantiSheet already knows, then sign it (Nov 11).

For forms that come back to be filled and signed - a sub bid form, a lien
waiver, a pay application cover, an insurance request, a change order.

  1. propose(): every fillable field with the value it would get and
     WHERE that value comes from (company settings, this job's billing
     info, the Company Directory, today's date) - or why it is left for
     the person. Nothing is written yet.
  2. The person reviews the list and ticks what to fill. Fields the
     program is sure of start ticked; ones it is unsure of don't.
  3. fill() writes the ticked values into a NEW file; the original is
     never changed.
  4. sign() places the saved signature in a signature box - only when it
     is called for that box, which the window does on an explicit Sign
     click - and records who, when and which file (its SHA-256) in the
     file's own audit trail and in "Signed Forms Log.csv" beside it.

What it will not do:
  * guess. A field it can't place is listed as left for you;
  * fill tax IDs, Social Security numbers or bank details (a W-9's TIN,
    an ACH form). Those are never stored by QuantiSheet and never filled;
    the field says "type this yourself";
  * send anything, or sign without being asked for that one box.

The match is by the field's name and, when the name says nothing
("Text12"), by the words printed beside the field. No AI is used here.
"""
import csv
import datetime as _dt
import hashlib
import logging
import os
import re

import fitz

from . import formlib

log = logging.getLogger(__name__)

READY, UNSURE, BLANK, NEVER, HAS, SIGN = \
    "ready", "unsure", "left for you", "type this yourself", \
    "already filled", "signature"
LOG_NAME = "Signed Forms Log.csv"

# never filled, never stored: tax and bank identifiers
_NEVER = re.compile(
    r"(?<![a-z])(tin|ssn|ein|fein|itin|tax\s*(payer)?\s*(id|identification)"
    r"(\s*(no|number|#))?|taxpayer|social\s*security|employer\s*"
    r"identification|routing|aba|account\s*(no|number|#)|bank\s*account|"
    r"iban|swift|card\s*(no|number)|cvv|password|passcode|pin)(?![a-z])",
    re.I)
_SIGN = re.compile(r"\b(signature|signed\s*by|sign\s*here|authorized\s*"
                   r"sign\w*)\b|^sign(ed)?$|^sig\s*\d*$|^by$", re.I)

# (pattern on the field's name or label, meaning, sure?) - first hit wins.
# "sure" patterns say exactly what the field is; the others could mean
# more than one thing on a form ("Name", "Address", "Date") and start
# unticked.
_RULES = [
    (r"^(project|job)\s*(name|title)?$|^name of project$|^re$", "project",
     True),
    (r"^(project|job|site)\s*(location|address)$", "project_address", True),
    (r"^(project|job|contract)\s*(no|number|#)\.?$", "project_number", True),
    (r"^owner(\s*name)?$|^name of owner$", "owner", True),
    (r"^architect(\s*name)?$", "architect", True),
    (r"^contract\s*date$|^date of contract$", "contract_date", True),
    (r"^contract\s*for$", "contract_for", True),
    (r"^(contractor|company|firm|business|bidder|vendor|subcontractor|"
     r"claimant|undersigned)(\s*(name|legal name))?(\.\d+)?$|"
     r"^name of (contractor|company|firm|bidder|claimant)$|^legal name$",
     "contractor", True),
    (r"^(contractor|company|firm|business|bidder|vendor|subcontractor|"
     r"mailing|street)\s*address$", "contractor_address", True),
    (r"^(contractor|company)?\s*city,?\s*state,?\s*(and\s*)?zip(\s*code)?$",
     "contractor_city", True),
    (r"^(contractor|company|business|office)?\s*(phone|telephone|tel)"
     r"(\s*(no|number|#))?\.?$", "contractor_phone", True),
    (r"^(contractor|company|business)?\s*e-?mail(\s*address)?$",
     "contractor_email", True),
    (r"^(contractor'?s?|state)?\s*licen[sc]e(\s*(no|number|#))?\.?$",
     "license", True),
    (r"^(printed|print|typed)\s*name$|^name\s*\(print(ed)?\)$|"
     r"^signer'?s?\s*name$", "signer", True),
    (r"^title$|^signer'?s?\s*title$|^title of signer$", "signer_title",
     True),
    (r"^(contract|subcontract)\s*(sum|amount|price)$|^original contract "
     r"sum$", "contract_sum", True),
    (r"^(through|period\s*to|thru)\s*date$|^period\s*to$", "period_to",
     True),
    (r"^(current|this)\s*payment\s*due$|^amount\s*(of\s*this\s*)?"
     r"(payment|due)$|^payment\s*amount$", "payment_due", True),
    (r"^name$", "contractor", False),
    (r"^address$", "contractor_address", False),
    (r"^date$|^dated$|^date signed$|^today'?s?\s*date$", "date", False),
]
_GENERIC = re.compile(r"^(text|field|undefined|untitled|fill|textbox|"
                      r"text\s*field|form\s*field|f\d+|t\d+)?[\s_.\-#]*"
                      r"\d*(\[\d+\])?$", re.I)


# ------------------------------------------------------------ what we know
def known(job_doc=None, contact=None, signer=None, extra=None):
    """{meaning: {"value", "source"}}: what QuantiSheet already has.
    `job_doc`: the job's drawing (its billing info); `contact`: a Company
    Directory entry when the form is about a sub; `signer`: {"name",
    "title"}; `extra`: more {meaning: (value, source)}."""
    out = {}
    company_keys = ("contractor", "contractor_address", "contractor_city",
                    "contractor_phone", "contractor_email", "license")
    base = formlib.job_values(None)
    for k, v in base.items():
        out[k] = {"value": v, "source": "today's date" if k == "date" else
                  "your company settings (Estimate > Company)"}
    if job_doc is not None:
        both = formlib.job_values(job_doc)
        for k, v in both.items():
            if base.get(k) != v or k not in out:
                out[k] = {"value": v,
                          "source": "this job's billing info (Billing > "
                                    "Contract Info)"}
        try:
            from . import money
            from .dmoney import c2 as _c2
            data = money.read(job_doc)
            total = sum((_c2(r.get("scheduled") or 0)
                         for r in data.get("sov") or []), _c2(0))
            if total:
                out["contract_sum"] = {
                    "value": f"{_c2(total):,.2f}",
                    "source": "this job's schedule of values (the sum of "
                              "its lines)"}
        except Exception:                                 # noqa: BLE001
            log.debug("no schedule of values for the form", exc_info=True)
    if contact:
        src = f"Company Directory: {contact.get('company') or ''}".strip()
        city = ", ".join(x for x in (contact.get("city"), " ".join(
            y for y in (contact.get("state"), contact.get("zip")) if y))
            if x)
        for k, v in (("contractor", contact.get("company")),
                     ("contractor_address", contact.get("address")),
                     ("contractor_city", city),
                     ("contractor_phone", contact.get("phone")),
                     ("contractor_email", contact.get("email")),
                     ("license", contact.get("license"))):
            if k in company_keys:
                if v:
                    out[k] = {"value": str(v), "source": src}
                else:
                    out.pop(k, None)    # never our own in a sub's field
    if signer:
        for k, key in (("signer", "name"), ("signer_title", "title")):
            if signer.get(key):
                out[k] = {"value": str(signer[key]),
                          "source": "the signer you entered"}
    for k, (v, src) in (extra or {}).items():
        if v not in (None, ""):
            out[k] = {"value": str(v), "source": src}
    return out


# ---------------------------------------------------------------- matching
def _clean(name):
    t = re.sub(r"[_\[\]().:]+", " ", str(name or ""))
    t = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", t)         # ProjectName
    return re.sub(r"\s+", " ", t).strip().lower()


def label_near(page, rect, words=None):
    """The words printed beside a field: on its line to the left, else
    the line just above it (or just below, for a signature rule)."""
    words = page.get_text("words") if words is None else words
    r = fitz.Rect(rect)
    left = [w for w in words if w[2] <= r.x0 + 2 and w[3] > r.y0 - 2 and
            w[1] < r.y1 + 2 and r.x0 - w[2] < 220]
    if left:
        left.sort(key=lambda w: w[0])
        return " ".join(w[4] for w in left[-6:]).strip(" :_")
    for dy0, dy1 in ((-16, 0), (0, 14)):
        band = [w for w in words if w[0] < r.x1 and w[2] > r.x0 - 4 and
                (r.y0 + dy0 - 2 <= w[1] and w[3] <= r.y0 + 2 if dy0 < 0
                 else r.y1 - 2 <= w[1] and w[3] <= r.y1 + dy1 + 2)]
        if band:
            band.sort(key=lambda w: (round(w[1]), w[0]))
            return " ".join(w[4] for w in band[:6]).strip(" :_")
    return ""


def meaning_of(text):
    """(meaning, sure) for a field name or label, or (None, False)."""
    t = _clean(text)
    if not t:
        return None, False
    for pat, key, sure in _RULES:
        if re.search(pat, t, re.I):
            return key, sure
    return None, False


def _is_sig(w, name, label):
    try:
        if w.field_type == fitz.PDF_WIDGET_TYPE_SIGNATURE:
            return True
    except Exception:                                     # noqa: BLE001
        pass
    if _SIGN.search(_clean(name)):
        return True
    # a name that says nothing else, beside the word "Signature"
    return meaning_of(name)[0] is None and \
        bool(_SIGN.search(_clean(label)))


def propose(doc, data):
    """One row per fillable field: {"id", "page", "xref", "rect", "name",
    "label", "meaning", "value", "source", "status", "why", "tick"}.
    Nothing in `doc` changes."""
    rows = []
    for pno, page in enumerate(doc):
        words = page.get_text("words")
        for w in formlib._widgets(page):
            name = re.sub(r"\s+", " ", str(w.field_name or "")).strip()
            rect = [round(v, 3) for v in w.rect]
            label = label_near(page, w.rect, words)
            row = {"id": f"{pno}:{w.xref}", "page": pno, "xref": w.xref,
                   "rect": rect, "name": name, "label": label,
                   "meaning": None, "value": "", "source": "",
                   "status": BLANK, "why": "", "tick": False}
            rows.append(row)
            both = f"{name} {label}"
            if _NEVER.search(_clean(name)) or (
                    _NEVER.search(_clean(label)) and
                    _GENERIC.match(_clean(name))):
                row.update(status=NEVER, why="Tax and bank identifiers are "
                           "never kept or filled by QuantiSheet.")
                continue
            if _is_sig(w, name, label):
                row.update(status=SIGN, meaning="signature",
                           why="Signed only when you press Sign for this "
                               "box.")
                continue
            if not formlib._is_textlike(w):
                row["why"] = "Not a text field (a box to tick or choose)."
                continue
            if w.field_value not in (None, ""):
                row.update(status=HAS, value=str(w.field_value),
                           why="Left as it is.")
                continue
            key, sure = meaning_of(name)
            by_label = False
            if key is None and _GENERIC.match(_clean(name)):
                key, sure = meaning_of(label)
                by_label = key is not None
            if key is None:
                row["why"] = "Nothing here says what this field is." if \
                    not both.strip() else "Not a field QuantiSheet knows."
                continue
            row["meaning"] = key
            got = data.get(key)
            if not got:
                row["why"] = f"QuantiSheet has no {key.replace('_', ' ')} " \
                             "for this form."
                continue
            row.update(value=got["value"], source=got["source"])
            if sure and not by_label:
                row.update(status=READY, tick=True)
            else:
                row.update(status=UNSURE, why=(
                    "Matched by the words beside the field, not its name."
                    if by_label else "This name could mean more than one "
                    "thing on a form.") + " Check it.")
    return rows


def summary(rows):
    n = {s: sum(1 for r in rows if r["status"] == s)
         for s in (READY, UNSURE, BLANK, NEVER, HAS, SIGN)}
    return (f"{n[READY]} ready, {n[UNSURE]} to check, {n[BLANK]} left for "
            f"you, {n[NEVER]} you must type yourself, {n[HAS]} already "
            f"filled, {n[SIGN]} signature box(es).")


# ------------------------------------------------------------------ filling
def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def out_path(src, tag):
    base, ext = os.path.splitext(src)
    base = re.sub(r" - (filled|signed)( \d+)?$", "", base)
    p = f"{base} - {tag}{ext or '.pdf'}"
    n = 2
    while os.path.exists(p):
        p = f"{base} - {tag} {n}{ext or '.pdf'}"
        n += 1
    return p


def fill(src, rows, out=None, values=None):
    """Write the ticked rows (status ready or unsure) into a copy of
    `src`. `values`: {row id: text} typed over the proposed value.
    Returns (out path, {field name: value}). `src` is not changed."""
    out = out or out_path(src, "filled")
    want = {}
    for r in rows:
        if r.get("tick") and r["status"] in (READY, UNSURE):
            v = (values or {}).get(r["id"], r["value"])
            if str(v).strip():
                want[(r["page"], r["xref"])] = (r["name"], str(v))
    doc = fitz.open(src)
    done = {}
    try:
        for pno, page in enumerate(doc):
            for w in formlib._widgets(page):
                hit = want.get((pno, w.xref))
                if hit and formlib._is_textlike(w):
                    formlib.set_text(doc, w, hit[1])
                    done[hit[0] or f"field {w.xref}"] = hit[1]
        doc.save(out, garbage=1, deflate=True)
    finally:
        doc.close()
    return out, done


# ------------------------------------------------------------------ signing
def _log_line(folder, row):
    p = os.path.join(folder, LOG_NAME)
    new = not os.path.exists(p)
    with open(p, "a", encoding="utf-8", newline="") as f:
        wr = csv.writer(f)
        if new:
            wr.writerow(["When", "Signed by", "File", "Field",
                         "SHA-256 of the file before signing",
                         "SHA-256 of the signed file"])
        wr.writerow(row)
    return p


def sign(src, row, strokes, who, out=None, date_rows=(), when=None):
    """Put the drawn signature (`strokes` from signature.saved) in the
    signature box `row`, in a copy of `src`, and record it. `date_rows`:
    Date fields to fill with today's date at the same time. Returns
    {"path", "log", "before", "after", "when", "by"}. Called only for a
    box the person pressed Sign on."""
    from . import signature
    from .sign.audit import AuditLog
    from .sign import embed
    if row.get("status") != SIGN:
        raise ValueError("That isn't a signature box.")
    if not (isinstance(strokes, dict) and strokes.get("strokes")):
        raise ValueError("There is no saved signature. Draw one first "
                         "(Fill & Sign > Signature).")
    who = str(who or "").strip()
    if not who:
        raise ValueError("Say who is signing (your name is kept with the "
                         "signature).")
    when = when or _dt.datetime.now()
    before = sha256(src)
    out = out or out_path(src, "signed")
    doc = fitz.open(src)
    try:
        page = doc[row["page"]]
        r = fitz.Rect(row["rect"])
        box = fitz.Rect(r.x0 + 2, r.y0 + 1, r.x1 - 2, r.y1 - 1)
        if box.height < 14:                 # a thin line: sign above it
            box = fitz.Rect(r.x0 + 2, r.y1 - 26, r.x1 - 2, r.y1 - 1)
        sh = page.new_shape()
        for st in signature.strokes_in(strokes, box):
            pts = [fitz.Point(x, y) * page.derotation_matrix for x, y in st]
            if len(pts) == 1:
                sh.draw_circle(pts[0], 0.6)
            else:
                sh.draw_polyline(pts)
            sh.finish(color=(0.05, 0.12, 0.47), width=1.3, closePath=False)
        sh.commit()
        today = when.strftime("%m/%d/%Y")
        for d in date_rows:
            for w in formlib._widgets(doc[d["page"]]):
                if w.xref == d["xref"] and formlib._is_textlike(w) and \
                        w.field_value in (None, ""):
                    formlib.set_text(doc, w, today)
        doc.save(out, garbage=1, deflate=True)
    finally:
        doc.close()
    try:
        trail = embed.read_audit(out) or AuditLog()
    except Exception:                                     # noqa: BLE001
        trail = AuditLog()
    trail.add("signed", who, {
        "field": row.get("name") or row.get("label") or "signature",
        "page": row["page"] + 1, "file": os.path.basename(src),
        "sha256_before": before, "kind": "drawn signature (not a "
        "certificate signature)"})
    embed.embed_audit(out, out, trail)
    after = sha256(out)
    stamp = when.isoformat(timespec="seconds")
    logp = _log_line(os.path.dirname(os.path.abspath(out)), [
        stamp, who, os.path.basename(out),
        row.get("name") or row.get("label") or "signature", before, after])
    return {"path": out, "log": logp, "before": before, "after": after,
            "when": stamp, "by": who}


def date_rows_for(rows, sig_row):
    """Empty Date fields that belong to a signature box: on its page, on
    its line or the line under it."""
    r = fitz.Rect(sig_row["rect"])
    out = []
    for x in rows:
        if x is sig_row or x["page"] != sig_row["page"] or \
                x["meaning"] != "date" or x["status"] not in (READY, UNSURE):
            continue
        y = (x["rect"][1] + x["rect"][3]) / 2
        if r.y0 - 30 <= y <= r.y1 + 40:
            out.append(x)
    return out
