"""Invoice PDFs, backup bundles, statements and email-ready output (P1-16).

Our own layout and wording; the pay application pages use the standard
construction math with our own headings and never a trade association's
form names, numbers or text. 'Email' builds a message for the user to review: through
Outlook on the PC when it is there, else an .eml file opened in the mail
program. Back Office never sends on its own; the user marks it Sent.
"""
from __future__ import annotations

import os
import subprocess
import sys
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

from . import billing, cents, clock, fileguard, jobs, store

SUMMARY_LINES = [
    ("1", "Original contract amount"),
    ("2", "Net change from executed change orders"),
    ("3", "Contract amount to date (1 + 2)"),
    ("4", "Work completed and materials stored to date"),
    ("5a", "Retainage on completed work"),
    ("5b", "Retainage on stored materials"),
    ("5", "Total retainage"),
    ("6", "Earned to date less retainage (4 - 5)"),
    ("7", "Less amounts certified on earlier applications"),
    ("8", "Amount due this application"),
    ("9", "Balance to finish including retainage (3 - 6)"),
]
SUMMARY_TITLE = "Progress Billing Summary"
DETAIL_TITLE = "Progress Billing Detail by Line"


class _Pg:
    def __init__(self, doc):
        import fitz
        self.fitz = fitz
        self.p = doc.new_page(width=612, height=792)

    def t(self, x, y, s, size=9, bold=False, right=None):
        font = "hebo" if bold else "helv"
        s = str(s)
        if right is not None:
            w = self.fitz.get_text_length(s, fontname=font, fontsize=size)
            x = right - w
        self.p.insert_text((x, y), s, fontsize=size, fontname=font)

    def line(self, y, x0=54, x1=558):
        self.p.draw_line((x0, y), (x1, y), width=0.5)


MSGID_DOMAIN = "quantisheet-backoffice.invalid"


def _out(office, name) -> str:
    """A file in the output folder named from user data, kept inside it."""
    folder = office.output_folder()
    os.makedirs(folder, exist_ok=True)
    return fileguard.safe_path(folder, name)


def _header(office, pg, title):
    c = office.company()
    y = 54
    if c.get("logo") and os.path.isfile(c["logo"]):
        import fitz
        try:
            pg.p.insert_image(fitz.Rect(458, 36, 558, 86), filename=c["logo"],
                              keep_proportion=True)
        except Exception:                                 # noqa: BLE001
            pass
    pg.t(54, y, c.get("name") or "", 13, True)
    for i, ln in enumerate((c.get("address") or "").splitlines()[:3]):
        pg.t(54, y + 14 + 11 * i, ln, 8.5)
    pg.t(54, 110, title, 15, True)
    pg.line(118)


def _job_name(office, job_id):
    j = jobs.job(office, job_id) if job_id else None
    return j["name"] if j else ""


def invoice_title(office, iid) -> str:
    inv = billing.invoice(office, iid)
    return f"Invoice {inv['number']} - {_job_name(office, inv['job_id'])}"


def invoice_pdf(office, iid, path=None) -> str:
    """Cover invoice page (+ summary and detail pages for a progress
    invoice). Saves the path and hash on the invoice."""
    import fitz
    inv = billing.invoice(office, iid)
    path = fileguard.write_target(path) if path else \
        _out(office, f"{inv['number']}.pdf")
    doc = fitz.open()
    pg = _Pg(doc)
    _header(office, pg, "INVOICE")
    j = jobs.job(office, inv["job_id"]) if inv["job_id"] else None
    con = billing.contract_for(office, inv["job_id"]) if inv["job_id"] else None
    y = 140
    for k, v in (("Invoice number", inv["number"]),
                 ("Invoice date", inv["invoice_date"]),
                 ("Due date", inv["due_date"]),
                 ("Bill to", inv["customer"]),
                 ("Job", f"{j['number']} {j['name']}" if j else ""),
                 ("Period to", inv["period_to"] or ""),
                 ("Pay application", inv["payapp_no"] or ""),
                 ("Change reference", inv["change_ref"] or "")):
        if v in ("", None):
            continue
        pg.t(54, y, k, 9, True)
        pg.t(170, y, v, 9)
        y += 14
    if con and con["bill_to"]:
        pg.t(340, 140, "Address", 9, True)
        for i, ln in enumerate(con["bill_to"].splitlines()[:4]):
            pg.t(340, 154 + 12 * i, ln, 9)
    y += 16
    pg.t(54, y, "Description", 9, True)
    pg.t(0, y, "Amount", 9, True, right=558)
    pg.line(y + 4)
    y += 18
    for ln in billing.lines(office, iid):
        if y > 700:
            pg = _Pg(doc)
            y = 60
        pg.t(54, y, ln["description"][:95], 8.5)
        pg.t(0, y, cents.fmt(ln["amount"]), 8.5, right=558)
        y += 13
    pg.line(y)
    y += 14
    if inv["tax"]:
        pg.t(380, y, "Sales tax", 9)
        pg.t(0, y, cents.fmt(inv["tax"]), 9, right=558)
        y += 14
    if inv["type"] == "Progress":
        pg.t(380, y, "Retainage held this invoice", 9)
        pg.t(0, y, cents.fmt(inv["retainage"]), 9, right=558)
        y += 14
    pg.t(380, y, "AMOUNT DUE", 10, True)
    pg.t(0, y, cents.fmt(inv["total"]), 10, True, right=558)
    tpl = office.db.one("SELECT * FROM templates WHERE deleted = 0 "
                        "ORDER BY id LIMIT 1")
    if tpl:
        if tpl["remit_to"]:
            pg.t(54, 720, "Remit to: " + tpl["remit_to"], 8.5)
        if tpl["footer"]:
            pg.t(54, 734, tpl["footer"][:110], 8)
    if inv["type"] == "Progress":
        _summary_page(office, doc, inv)
        _detail_page(office, doc, inv)
    doc.set_metadata({"title": invoice_title(office, iid),
                      "author": office.company()["name"] or "",
                      "producer": "QuantiSheet Back Office",
                      "creator": "QuantiSheet Back Office"})
    doc.save(path)
    doc.close()
    h = store.file_hash(path)
    with office.db.tx():
        office.db.update("ar_invoices", iid, pdf_path=path, pdf_hash=h)
        office.audit("print", "ar_invoice", iid, None, {"file": path,
                                                         "hash": h})
    return path


def _summary_page(office, doc, inv):
    v = billing.payapp_numbers(office, inv["id"])
    a = billing.payapp(office, inv["job_id"], inv["payapp_no"])
    pg = _Pg(doc)
    _header(office, pg, SUMMARY_TITLE)
    j = jobs.job(office, inv["job_id"])
    pg.t(54, 140, f"Job {j['number']} {j['name']}", 10, True)
    pg.t(54, 154, f"Application {a['number']}   Period to {a['period_to']}   "
                  f"Invoice {inv['number']}", 9)
    y = 184
    for k, label in SUMMARY_LINES:
        if k not in v:
            continue
        bold = k in ("3", "6", "8", "9")
        pg.t(54, y, f"{k}.", 9, bold)
        pg.t(80, y, label, 9, bold)
        pg.t(0, y, cents.fmt(v[k]), 9, bold, right=558)
        y += 16
    pg.t(54, y + 20, "Figures as certified in QuantiSheet; Back Office does not "
                     "recompute a certified application.", 7.5)


def _detail_page(office, doc, inv):
    a = billing.payapp(office, inv["job_id"], inv["payapp_no"])
    sov = {s["item"]: s for s in jobs.section(office, inv["job_id"], "sov")}
    chg = {(c["co"] or c["id"]): c for c in
           jobs.section(office, inv["job_id"], "changes")}
    pg = _Pg(doc)
    _header(office, pg, DETAIL_TITLE)
    cols = [(54, "Item"), (100, "Description"), (300, "Previous"),
            (370, "This period"), (440, "Stored"), (510, "To date")]
    y = 140
    for x, h in cols:
        pg.t(x, y, h, 8, True)
    pg.line(y + 4)
    y += 16
    tot = [0, 0, 0, 0]
    for ln in a["lines"]:
        vals = [cents.to_cents(ln[k]) for k in ("previous", "this_period",
                                                "stored")]
        vals.append(sum(vals))
        desc = (sov.get(ln["item"]) or {}).get("description") or \
            (chg.get(ln["item"]) or {}).get("title", "")
        pg.t(54, y, ln["item"], 8)
        pg.t(100, y, desc[:36], 8)
        for i, x in enumerate((360, 430, 500, 558)):
            pg.t(0, y, cents.fmt(vals[i]), 8, right=x)
            tot[i] += vals[i]
        y += 13
    pg.line(y)
    y += 12
    pg.t(100, y, "Totals", 8, True)
    for i, x in enumerate((360, 430, 500, 558)):
        pg.t(0, y, cents.fmt(tot[i]), 8, True, right=x)


def tm_backup(office, iid) -> dict:
    """Every time line and receipt behind a T&M invoice; the backup total
    equals the invoice total (lines plus tax)."""
    inv = billing.invoice(office, iid)
    time_rows, receipts, line_rows = [], [], []
    for ln in billing.lines(office, iid):
        line_rows.append({"description": ln["description"],
                          "amount": ln["amount"], "kind": ln["kind"]})
        for b in office.db.rows("SELECT * FROM billed_links WHERE ar_line_id = ? "
                                "AND active = 1", (ln["id"],)):
            if b["source_type"] == "time_line":
                t = office.db.one("SELECT t.*, w.name AS worker, w.labor_class "
                                  "FROM time_lines t JOIN workers w ON "
                                  "w.id = t.worker_id WHERE t.id = ?",
                                  (b["source_id"],))
                if ln["kind"] == "labor":
                    time_rows.append({"date": t["date"], "worker": t["worker"],
                                      "class": t["labor_class"],
                                      "pay_type": t["pay_type"],
                                      "hours": t["hours"],
                                      "cost_code": t["cost_code"],
                                      "equipment": t["equipment_code"],
                                      "equipment_hours": t["equipment_hours"]})
            elif b["source_type"] == "ap_line":
                a = office.db.one("SELECT l.*, i.number, i.doc_path, v.name AS "
                                  "vendor FROM ap_lines l JOIN ap_invoices i ON "
                                  "i.id = l.invoice_id JOIN vendors v ON "
                                  "v.id = i.vendor_id WHERE l.id = ?",
                                  (b["source_id"],))
                receipts.append({"ap": a["number"], "vendor": a["vendor"],
                                 "amount": a["amount"],
                                 "file": a["doc_path"] or ""})
    total = sum(r["amount"] for r in line_rows) + (inv["tax"] or 0)
    return {"invoice": inv["number"], "lines": line_rows,
            "time_lines": time_rows, "receipts": receipts,
            "tax": inv["tax"] or 0, "total": total}


def tm_backup_pdf(office, iid, path=None) -> str:
    import fitz
    b = tm_backup(office, iid)
    inv = billing.invoice(office, iid)
    path = fileguard.write_target(path) if path else \
        _out(office, f"{inv['number']}-backup.pdf")
    doc = fitz.open()
    pg = _Pg(doc)
    _header(office, pg, f"T&M backup for {inv['number']}")
    y = 140
    pg.t(54, y, "Time", 10, True)
    y += 14
    for t in b["time_lines"]:
        if y > 740:
            pg, y = _Pg(doc), 60
        pg.t(54, y, f"{t['date']}  {t['worker']}  {t['class']} {t['pay_type']}"
                    f"  {cents.hours_text(t['hours'])} h  {t['cost_code']}"
                    + (f"  {t['equipment']} {cents.hours_text(t['equipment_hours'])} h"
                       if t["equipment"] else ""), 8.5)
        y += 12
    y += 8
    pg.t(54, y, "Receipts", 10, True)
    y += 14
    for r in b["receipts"]:
        pg.t(54, y, f"{r['ap']}  {r['vendor']}  {cents.fmt(r['amount'])}", 8.5)
        y += 12
    y += 8
    for ln in b["lines"]:
        pg.t(54, y, ln["description"][:90], 8.5)
        pg.t(0, y, cents.fmt(ln["amount"]), 8.5, right=558)
        y += 12
    if b["tax"]:
        pg.t(54, y, "Sales tax", 8.5)
        pg.t(0, y, cents.fmt(b["tax"]), 8.5, right=558)
        y += 12
    pg.t(54, y + 4, "Backup total", 9, True)
    pg.t(0, y + 4, cents.fmt(b["total"]), 9, True, right=558)
    for r in b["receipts"]:
        f = r["file"]
        if f and os.path.isfile(f):
            try:
                if f.lower().endswith(".pdf"):
                    with fitz.open(f) as src:
                        doc.insert_pdf(src)
                else:
                    p = doc.new_page(width=612, height=792)
                    p.insert_image(fitz.Rect(36, 36, 576, 756), filename=f,
                                   keep_proportion=True)
            except Exception:                             # noqa: BLE001
                pass
    doc.set_metadata({"title": f"T&M backup {inv['number']}",
                      "producer": "QuantiSheet Back Office"})
    doc.save(path)
    doc.close()
    return path


def statement_pdf(office, customer, as_of, path=None) -> str:
    import fitz
    from . import payments
    path = fileguard.write_target(path) if path else \
        _out(office, f"Statement {customer} {as_of}.pdf")
    ag = payments.aging(office, as_of)
    doc = fitz.open()
    pg = _Pg(doc)
    _header(office, pg, "STATEMENT")
    pg.t(54, 140, f"{customer}   as of {as_of}", 10, True)
    y = 166
    tot = 0
    for r in ag["rows"]:
        if r["customer"] != customer:
            continue
        pg.t(54, y, f"{r['number']}  due {r['due_date']}  {r['bucket']}", 9)
        pg.t(0, y, cents.fmt(r["open"]), 9, right=558)
        tot += r["open"]
        y += 13
    pg.t(54, y + 8, "Total open", 10, True)
    pg.t(0, y + 8, cents.fmt(tot), 10, True, right=558)
    doc.set_metadata({"title": f"Statement - {customer} - {as_of}",
                      "producer": "QuantiSheet Back Office"})
    doc.save(path)
    doc.close()
    return path


# ---- email-ready (never sent by Back Office) -----------------------------

def outlook_available() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import win32com.client                           # noqa: F401
        return True
    except ImportError:
        return False


def _open_file(path):
    if sys.platform == "win32":
        os.startfile(path)                               # noqa: S606
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def email_subject(office, iid) -> str:
    inv = billing.invoice(office, iid)
    s = invoice_title(office, iid)
    if inv["period_to"]:
        s += f" - Period to {inv['period_to']}"
    return s


def email_invoice(office, iid, cc="", body=None, opener=None,
                  outlook=None) -> dict:
    """Builds the message for review. Outlook present: opens it in Outlook
    (Display, not Send). Else writes an .eml and opens it. Nothing is sent
    and the invoice status does not change."""
    inv = billing.invoice(office, iid)
    con = billing.contract_for(office, inv["job_id"]) if inv["job_id"] else None
    to = (con or {}).get("contact_email") or ""
    pdf = inv["pdf_path"] if inv["pdf_path"] and os.path.isfile(
        inv["pdf_path"]) else invoice_pdf(office, iid)
    subject = email_subject(office, iid)
    body = body or (f"Please find attached invoice {inv['number']} for "
                    f"{cents.fmt(inv['total'])}, due {inv['due_date']}.\n\n"
                    f"{office.company()['name'] or ''}")
    use_outlook = outlook_available() if outlook is None else outlook
    msg = {"to": to, "cc": cc, "subject": subject, "body": body,
           "attachments": [pdf], "via": "outlook" if use_outlook else "eml",
           "path": ""}
    if use_outlook:
        import win32com.client
        ol = win32com.client.Dispatch("Outlook.Application")
        m = ol.CreateItem(0)
        m.To, m.CC, m.Subject, m.Body = to, cc, subject, body
        m.Attachments.Add(os.path.abspath(pdf))
        m.Display(False)                 # the user reviews and sends
    else:
        em = EmailMessage()
        em["To"] = to
        if cc:
            em["Cc"] = cc
        em["Subject"] = subject
        em["Date"] = formatdate(localtime=True)
        em["Message-ID"] = make_msgid(domain=MSGID_DOMAIN)   # no DNS lookup
        em["X-Unsent"] = "1"
        em.set_content(body)
        with open(pdf, "rb") as fh:
            em.add_attachment(fh.read(), maintype="application",
                              subtype="pdf", filename=os.path.basename(pdf))
        path = _out(office, f"{inv['number']}.eml")
        with open(path, "wb") as fh:
            fh.write(bytes(em))
        msg["path"] = path
        (opener or _open_file)(path)
    office.audit("email prepared", "ar_invoice", iid, None,
                 {"to": to, "via": msg["via"], "sent": False})
    return msg
