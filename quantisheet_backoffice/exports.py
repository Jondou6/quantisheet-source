"""Accounting exports (P1-17): CSV and Excel always, QuickBooks Desktop
IIF files, and Sage 300 CRE import files with a saved column map.

Every transaction is written from its balanced journal entry (P1-19), so
an export can never be unbalanced. Each batch is numbered, can be
re-printed, and marks its records exported so they never go twice; a
voided batch (reason required) makes them exportable again. Lines that
can't go are listed with the reason, never exported.

QuickBooks is a trademark of Intuit Inc. QuantiSheet is not affiliated
with or endorsed by Intuit. Back Office writes IIF text files only; it
never opens QuickBooks company files and uses no Intuit API.
"""
from __future__ import annotations

import csv
import json
import os
import re

from . import cents, clock, fileguard, jobs, ledger, store
from .fileguard import TRADEMARK_NOTICE  # noqa: F401  (shown on the screen)

TYPES = {"ap": "AP invoices (bills)", "ar": "AR invoices",
         "payments": "Customer payments", "billpay": "Bill payments",
         "time": "Approved time", "jobcost": "Job cost detail",
         "perdiem": "Approved per diem"}          # r38 G2.2
FORMATS = {"csv": "CSV", "xlsx": "Excel", "iif": "QuickBooks Desktop IIF file",
           "sage": "Sage 300 CRE import file"}
CODE_FORMAT = "{div}-{a}{b}"          # CSI '03 30 00' -> '03-3000'
SAGE_AP_COLUMNS = ["Vendor", "Invoice", "Invoice Date", "Due Date",
                   "Accounting Date", "Amount", "Retainage", "Job", "Extra",
                   "Cost Code", "Category", "GL Account", "Description"]
IIF_TYPE = {"ap": "BILL", "ar": "INVOICE", "payments": "GENERAL JOURNAL",
            "billpay": "GENERAL JOURNAL"}


class ExportError(ValueError):
    pass


def format_code(code, fmt=CODE_FORMAT) -> str:
    """'03 30 00' / '033000' / '03-3000' -> '03-3000' (configurable)."""
    digits = re.sub(r"\D", "", code or "")
    m = re.match(r"^(\d{2})(\d{2})(\d{2})(\d*)$", digits)
    if not m:
        return (code or "").strip()
    return fmt.format(div=m.group(1), a=m.group(2), b=m.group(3),
                      ext=m.group(4))


# ---- column maps ---------------------------------------------------------

def set_column_map(office, target, record_type, columns, code_format=CODE_FORMAT):
    office.require("settings.edit", "column_map", f"{target}/{record_type}")
    with office.db.tx():
        old = column_map(office, target, record_type, default=False)
        if old:
            office.db.update("column_maps", old["id"], columns=columns,
                             code_format=code_format)
        else:
            office.db.insert("column_maps", target=target,
                             record_type=record_type, columns=columns,
                             code_format=code_format)
        office.audit("change", "column_map", f"{target}/{record_type}",
                     old and old["columns"], columns)


def column_map(office, target, record_type, default=True):
    r = office.db.one("SELECT * FROM column_maps WHERE target = ? AND "
                      "record_type = ? AND deleted = 0", (target, record_type))
    if r:
        r = dict(r)
        r["columns"] = json.loads(r["columns"])
        return r
    if default and target == "sage" and record_type == "ap":
        return {"id": None, "columns": SAGE_AP_COLUMNS,
                "code_format": CODE_FORMAT}
    return None


# ---- records -------------------------------------------------------------

def _exported_ids(office, record_type) -> set[int]:
    return {r["record_id"] for r in office.db.rows(
        "SELECT i.record_id FROM export_items i JOIN export_batches b ON "
        "b.id = i.batch_id WHERE i.record_type = ? AND b.status = 'Active'",
        (record_type,))}


def _candidates(office, type_, date_from, date_to) -> list[dict]:
    done = _exported_ids(office, type_)
    db = office.db
    if type_ == "ap":
        rows = db.rows("SELECT i.*, v.name AS party FROM ap_invoices i LEFT JOIN "
                       "vendors v ON v.id = i.vendor_id WHERE i.status IN "
                       "('Approved','Partly paid','Paid') AND i.deleted = 0 "
                       "AND i.gl_date BETWEEN ? AND ? ORDER BY i.number",
                       (date_from, date_to))
    elif type_ == "ar":
        rows = db.rows("SELECT *, customer AS party FROM ar_invoices WHERE "
                       "status NOT IN ('Draft','Void') AND deleted = 0 AND "
                       "gl_date BETWEEN ? AND ? ORDER BY number",
                       (date_from, date_to))
    elif type_ == "payments":
        rows = db.rows("SELECT *, customer AS party, reference AS number FROM "
                       "payments WHERE void = 0 AND deleted = 0 AND date "
                       "BETWEEN ? AND ? ORDER BY id", (date_from, date_to))
    elif type_ == "billpay":
        rows = db.rows("SELECT p.*, v.name AS party, p.reference AS number "
                       "FROM bill_payments p JOIN vendors v ON v.id = "
                       "p.vendor_id WHERE p.void = 0 AND p.deleted = 0 AND "
                       "p.date BETWEEN ? AND ? ORDER BY p.id",
                       (date_from, date_to))
    elif type_ == "time":
        rows = db.rows("SELECT t.*, w.name AS party, w.employee_no, "
                       "w.labor_class, t.id AS number FROM time_lines t JOIN "
                       "workers w ON w.id = t.worker_id WHERE t.status IN "
                       "('Approved','Locked') AND t.deleted = 0 AND t.date "
                       "BETWEEN ? AND ? ORDER BY t.date, t.id",
                       (date_from, date_to))
    elif type_ == "perdiem":                         # r38 G2.2
        rows = db.rows("SELECT p.*, w.name AS party, w.employee_no, "
                       "w.labor_class, p.id AS number FROM per_diem_lines p "
                       "JOIN workers w ON w.id = p.worker_id WHERE p.status "
                       "IN ('Approved','Locked') AND p.deleted = 0 AND p.date "
                       "BETWEEN ? AND ? ORDER BY p.date, p.id",
                       (date_from, date_to))
    else:
        return []
    return [r for r in rows if r["id"] not in done]


def _problems(office, type_, rec, fmt) -> list[str]:
    out = []
    label = rec.get("number") or rec["id"]
    if type_ == "ap":
        if not rec["party"]:
            out.append(f"{label}: no vendor")
        for ln in office.db.rows("SELECT * FROM ap_lines WHERE invoice_id = ? "
                                 "AND deleted = 0 ORDER BY line_no",
                                 (rec["id"],)):
            if ln["job_id"] and not ln["cost_code"]:
                out.append(f"{label} line {ln['line_no']}: no cost code")
    if type_ == "time" and not rec["cost_code"]:
        out.append(f"time line {rec['id']}: no cost code")
    if type_ == "perdiem" and not rec["cost_code"]:
        out.append(f"per diem {rec['id']}: no cost code")
    if type_ in ("ap", "ar", "payments", "billpay"):
        e = _entry(office, type_, rec)
        if e is None:
            out.append(f"{label}: not posted")
            return out
        if sum(l["debit"] for l in e["lines"]) != \
                sum(l["credit"] for l in e["lines"]):
            out.append(f"{label}: unbalanced")
        for ln in e["lines"]:
            a = ledger.account(office, ln["account_id"])
            if fmt == "iif" and not (a["qb_name"] or "").strip():
                out.append(f"account {a['number']} {a['name']}: no "
                           f"QuickBooks name")
            if fmt == "sage" and not (a["sage_gl"] or "").strip():
                out.append(f"account {a['number']} {a['name']}: no Sage GL "
                           f"account")
    return list(dict.fromkeys(out))


def _entry(office, type_, rec):
    st = {"ap": "ap_invoice", "ar": "ar_invoice", "payments": "payment",
          "billpay": "bill_payment"}[type_]
    es = [e for e in ledger.entries_for(office, st, rec["id"])
          if not e["reverses_id"]]
    return es[0] if es else None


def preview(office, type_, date_from, date_to, fmt="csv") -> dict:
    if type_ not in TYPES:
        raise ExportError(f"type must be one of {', '.join(TYPES)}")
    if fmt not in FORMATS:
        raise ExportError(f"format must be one of {', '.join(FORMATS)}")
    if fmt == "iif" and type_ in ("time", "jobcost", "perdiem"):
        raise ExportError("IIF carries transactions only; use CSV or Excel "
                          "for time, per diem and job cost.")
    ok, problems = [], []
    for r in _candidates(office, type_, str(date_from), str(date_to)):
        p = _problems(office, type_, r, fmt)
        if p:
            problems += p
        else:
            ok.append(r)
    return {"records": ok, "problems": problems,
            "total": sum(r.get("total") or r.get("amount") or 0 for r in ok
                         if type_ != "time")}


# ---- writers -------------------------------------------------------------

def _je_rows(office, type_, rec):
    e = _entry(office, type_, rec)
    rows = []
    for ln in e["lines"]:
        a = ledger.account(office, ln["account_id"])
        j = jobs.job(office, ln["job_id"]) if ln["job_id"] else None
        rows.append({"date": e["date"], "doc": rec.get("number") or rec["id"],
                     "account": a, "debit": ln["debit"], "credit": ln["credit"],
                     "job": j["number"] if j else "",
                     "cost_code": format_code(ln["cost_code"]) if
                     ln["cost_code"] else "", "category": ln["category"] or "",
                     "party": ln["party"] or rec.get("party") or "",
                     "memo": ln["memo"] or e["memo"] or ""})
    return rows


def _iif_date(d):
    y, m, dd = d.split("-")
    return f"{m}/{dd}/{y}"


def _iif_clean(s):
    return str(s or "").replace("\t", " ").replace("\n", " ").replace('"', "'")


def write_iif(office, type_, records, path) -> list[int]:
    """One TRNS/SPL/ENDTRNS block per transaction; returns each block's
    sum (all 0)."""
    hdr = ["TRNSID", "TRNSTYPE", "DATE", "ACCNT", "NAME", "CLASS", "AMOUNT",
           "DOCNUM", "MEMO"]
    lines_ = ["!TRNS\t" + "\t".join(hdr), "!SPL\t" + "\t".join(
        ["SPLID"] + hdr[1:]), "!ENDTRNS"]
    sums = []
    for rec in records:
        rows = _je_rows(office, type_, rec)
        first = {"ap": "ap", "ar": "ar"}.get(type_)
        if first:
            key = ledger.default_account(office, first)
            rows.sort(key=lambda r: r["account"]["id"] != key)
        block = 0
        for i, r in enumerate(rows):
            amt = r["debit"] - r["credit"]
            block += amt
            tag = "TRNS" if i == 0 else "SPL"
            lines_.append("\t".join([
                tag, "", IIF_TYPE[type_], _iif_date(r["date"]),
                _iif_clean(r["account"]["qb_name"]), _iif_clean(r["party"]),
                _iif_clean(r["job"]), cents.text(amt), _iif_clean(r["doc"]),
                _iif_clean((r["cost_code"] + " " + r["memo"]).strip())]))
        lines_.append("ENDTRNS")
        sums.append(block)
    if any(sums):
        raise ExportError("an IIF block does not balance")
    with open(path, "w", encoding="utf-8", newline="\r\n") as fh:
        fh.write("\n".join(lines_) + "\n")
    return sums


GL_HEADERS = ["Batch", "Document", "Date", "Account", "Account name",
              "Debit", "Credit", "Job", "Cost code", "Category", "Name",
              "Memo"]


def _flat_rows(office, type_, records, batch_no):
    out = []
    if type_ == "time":
        hdr = ["Batch", "Date", "Employee", "Employee no.", "Class", "Job",
               "Cost code", "Pay type", "Hours", "Equipment", "Equipment hours"]
        for t in records:
            j = jobs.job(office, t["job_id"])
            out.append([batch_no, t["date"], t["party"], t["employee_no"] or "",
                        t["labor_class"], j["number"],
                        format_code(t["cost_code"]), t["pay_type"],
                        cents.hours_text(t["hours"]), t["equipment_code"] or "",
                        cents.hours_text(t["equipment_hours"] or 0)])
        return hdr, out
    if type_ == "perdiem":                           # r38 G2.2
        hdr = ["Batch", "Date", "Employee", "Employee no.", "Class", "Job",
               "Cost code", "Kind", "Amount"]
        for p in records:
            j = jobs.job(office, p["job_id"])
            out.append([batch_no, p["date"], p["party"], p["employee_no"] or "",
                        p["labor_class"], j["number"],
                        format_code(p["cost_code"]), p["kind"],
                        cents.text(p["amount"])])
        return hdr, out
    for rec in records:
        for r in _je_rows(office, type_, rec):
            out.append([batch_no, r["doc"], r["date"], r["account"]["number"],
                        r["account"]["name"], cents.text(r["debit"]),
                        cents.text(r["credit"]), r["job"], r["cost_code"],
                        r["category"], r["party"], r["memo"]])
    return GL_HEADERS, out


def _sage_rows(office, records, cmap):
    """Sage 300 CRE AP import rows, columns in the saved map's order."""
    rows = []
    for rec in records:
        inv = office.db.get("ap_invoices", rec["id"])
        for ln in office.db.rows("SELECT * FROM ap_lines WHERE invoice_id = ? "
                                 "AND deleted = 0 ORDER BY line_no",
                                 (rec["id"],)):
            j = jobs.job(office, ln["job_id"]) if ln["job_id"] else None
            acct = ledger.account(office, ln["account_id"] or
                                  ledger.cost_account(office, ln["category"],
                                                      ln["cost_code"],
                                                      inv["vendor_id"],
                                                      ln["job_id"]))
            vals = {"Vendor": rec["party"], "Invoice": inv["invoice_no"],
                    "Invoice Date": inv["invoice_date"],
                    "Due Date": inv["due_date"],
                    "Accounting Date": inv["gl_date"],
                    "Amount": cents.text(ln["amount"]),
                    "Retainage": cents.text(
                        int(cents.round_half_up(cents.D(inv["retainage"] or 0) *
                                                ln["amount"] / inv["total"]))
                        if inv["total"] else 0),
                    "Job": j["number"] if j else "", "Extra": ln["phase"] or "",
                    "Cost Code": format_code(ln["cost_code"],
                                             cmap["code_format"]) if
                    ln["cost_code"] else "",
                    "Category": ln["category"] or "",
                    "GL Account": acct["sage_gl"] or "",
                    "Description": ln["description"] or ""}
            rows.append([vals.get(c, "") for c in cmap["columns"]])
    return cmap["columns"], rows


def export(office, type_, date_from, date_to, fmt, folder=None) -> dict:
    office.require("export.run", "export", type_)
    pv = preview(office, type_, date_from, date_to, fmt)
    if not pv["records"]:
        return {"batch_id": None, "count": 0, "problems": pv["problems"],
                "path": "", "total": 0}
    folder = folder or os.path.join(office.output_folder(), "exports")
    os.makedirs(folder, exist_ok=True)
    # Safety backup before the export, only for people who may make backups
    # anyway: export.run alone must never produce a full-database dump
    # (0.13.5 security fix; backup.make checks backup.run itself too).
    if office.can("backup.run"):
        try:
            from . import backup
            backup.make(office)
        except Exception:                                 # noqa: BLE001
            pass
    number = office.db.next_number("EXP", "EXP-{n:04d}")
    ext = {"csv": "csv", "xlsx": "xlsx", "iif": "iif", "sage": "csv"}[fmt]
    path = fileguard.safe_path(folder, f"{number} {type_}.{ext}")
    if fmt == "iif":
        write_iif(office, type_, pv["records"], path)
    else:
        if fmt == "sage":
            if type_ != "ap":
                raise ExportError("Sage import files are set up for AP "
                                  "invoices; use CSV for the others.")
            hdr, rows = _sage_rows(office, pv["records"],
                                   column_map(office, "sage", "ap"))
        else:
            hdr, rows = _flat_rows(office, type_, pv["records"], number)
        if fmt == "xlsx":
            from openpyxl import Workbook
            wb = Workbook()
            ws = wb.active
            ws.title = TYPES[type_][:30]
            ws.append(fileguard.safe_row(hdr))
            for r in rows:
                ws.append(fileguard.safe_row(r))
            wb.save(path)
        else:
            with open(path, "w", encoding="utf-8", newline="") as fh:
                w = csv.writer(fh)
                w.writerow(fileguard.safe_row(hdr))
                w.writerows(fileguard.safe_row(r) for r in rows)
    total = pv["total"]
    with office.db.tx():
        bid = office.db.insert("export_batches", number=number, type=type_,
                               format=fmt, ts=clock.iso_now(),
                               record_count=len(pv["records"]), total=total,
                               file_path=path, file_hash=store.file_hash(path),
                               status="Active", date_from=str(date_from),
                               date_to=str(date_to))
        for r in pv["records"]:
            office.db.insert("export_items", batch_id=bid, record_type=type_,
                             record_id=r["id"])
            if type_ == "ap":
                inv = office.db.get("ap_invoices", r["id"])
                office.db.update("ap_invoices", r["id"], exported_batch=bid,
                                 pre_export_status=inv["status"],
                                 status="Exported" if inv["status"] ==
                                 "Approved" else inv["status"])
            elif type_ == "ar":
                office.db.update("ar_invoices", r["id"], exported_batch=bid)
        office.audit("export", "export_batch", bid, None,
                     {"number": number, "type": type_, "format": fmt,
                      "count": len(pv["records"]), "total": total,
                      "problems": pv["problems"]})
    return {"batch_id": bid, "number": number, "count": len(pv["records"]),
            "problems": pv["problems"], "path": path, "total": total}


def void_batch(office, batch_id, reason) -> None:
    office.require("export.void", "export_batch", batch_id)
    if not (reason or "").strip():
        raise ExportError("A reason is required to void a batch.")
    b = office.db.get("export_batches", batch_id)
    with office.db.tx():
        office.db.update("export_batches", batch_id, status="Void",
                         void_reason=reason)
        for it in office.db.rows("SELECT * FROM export_items WHERE batch_id = ?",
                                 (batch_id,)):
            if it["record_type"] == "ap":
                inv = office.db.get("ap_invoices", it["record_id"])
                office.db.update("ap_invoices", it["record_id"],
                                 exported_batch=None,
                                 status=inv["pre_export_status"] if
                                 inv["status"] == "Exported" else inv["status"])
            elif it["record_type"] == "ar":
                office.db.update("ar_invoices", it["record_id"],
                                 exported_batch=None)
        office.audit("void", "export_batch", batch_id,
                     {"status": b["status"]}, {"reason": reason})


def batches(office) -> list[dict]:
    return office.db.rows("SELECT * FROM export_batches ORDER BY id DESC")


def job_cost_csv(office, job_id, path) -> str:
    from . import jobcost
    fileguard.refuse_company_file(path)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(fileguard.safe_row(["Cost code", "Description", "Category", "Original",
                    "Revised", "Committed", "Actual", "Remaining",
                    "% spent", "Variance", "Per diem", "Regular labor",
                    "Overtime labor", "Regular hours",
                    "Overtime hours"]))       # r38 G2.2 / G2.5: added last
        for r in jobcost.job_cost(office, job_id):
            w.writerow(fileguard.safe_row([format_code(r["code"]), r["description"],
                        r["category"], cents.text(r["original"]),
                        cents.text(r["revised"]), cents.text(r["committed"]),
                        cents.text(r["actual"]), cents.text(r["remaining"]),
                        r["pct_spent"], cents.text(r["variance"]),
                        cents.text(r["per_diem"]),
                        cents.text(r["labor_regular"]),
                        cents.text(r["labor_overtime"]),
                        cents.hours_text(r["hours_regular"]),
                        cents.hours_text(r["hours_overtime"])]))
    return path
