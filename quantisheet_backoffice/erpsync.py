"""File sync with an accounting system (P3-02; decision 15 = A: files only).

Import: the master-data export from the accounting system (vendors, jobs,
cost codes, employees, open commitments) as CSV/Excel is read and compared
with Back Office. A Sync run lists what is new, what matches, what is a
likely match for a person to confirm, what changed and what is only here.
Nothing is renamed or overwritten automatically: a likely match only becomes
a link when someone confirms it, and new vendors are only added for the rows
the user ticks. Jobs and cost codes come from QuantiSheet; differences there
are reported for the user to fix at the source.

Export: approved batches go back through the existing export files
(exports.py: CSV/Excel, Sage 300 CRE AP import, IIF); record_export() logs
the round so the Sync Center shows the last import and export per system.

Limits (M4 review): a file over MAX_BYTES or with more than MAX_ROWS rows
is refused before anything is compared; a row whose key or name is empty,
too long, holds control characters or starts like a spreadsheet formula
(= + @ or -digit) is not imported and is listed under 'rejected' with the
row number and reason.

Columns that hold personal or bank data (SSN, tax ID, bank, routing,
account number, date of birth) are never read or stored; their headers are
listed on the run as ignored. Default column names are common header words;
every system's map can be set per file.

QuickBooks is a trademark of Intuit Inc. QuantiSheet is not affiliated with
or endorsed by Intuit. Back Office never opens QuickBooks company files and
uses no Intuit API: for QuickBooks it reads list exports (CSV/Excel/IIF
lists the user saves) and writes IIF files.
"""
from __future__ import annotations

import csv
import difflib
import hashlib
import io
import json
import os
import re

from . import ap, clock, fileguard, jobs, settings

SYSTEMS = ("Sage 300 CRE", "Vista", "Spectrum", "QuickBooks", "Other")
RECORD_TYPES = ("vendors", "jobs", "cost_codes", "employees", "commitments")
SENSITIVE = re.compile(r"ssn|social|tax ?id|\btin\b|\bein\b|federal id|"
                       r"bank|routing|acct|account ?(no|num|#)|\bdob\b|"
                       r"birth|pay ?rate|salary|wage", re.I)
FIELDS = {
    "vendors": {"key": ["vendor id", "vendor code", "vendor number",
                        "vendor no", "vendor #", "id", "code", "number"],
                "name": ["vendor name", "name", "company", "vendor"],
                "email": ["email", "e-mail"], "phone": ["phone", "telephone"],
                "address": ["address", "address 1", "street"]},
    "jobs": {"key": ["job number", "job no", "job #", "job id", "job",
                     "number"],
             "name": ["job name", "description", "name"]},
    "cost_codes": {"job": ["job number", "job no", "job", "job id"],
                   "key": ["cost code", "phase code", "phase", "code"],
                   "name": ["description", "cost code description",
                            "phase description", "name"]},
    "employees": {"key": ["employee number", "employee no", "employee id",
                          "emp no", "employee #", "employee"],
                  "name": ["employee name", "name"]},
    "commitments": {"key": ["commitment", "commitment no", "po number",
                            "po", "subcontract", "contract", "number"],
                    "vendor": ["vendor name", "vendor"],
                    "job": ["job number", "job no", "job"],
                    "amount": ["amount", "revised amount", "total",
                               "contract amount"]},
}
SUFFIXES = {"LLC", "L L C", "INC", "INCORPORATED", "CO", "CORP",
            "CORPORATION", "COMPANY", "LTD", "LP", "LLP", "PLLC", "PC",
            "THE"}
LIKELY_MIN = 0.88
MAX_BYTES = 5 * 1024 * 1024
MAX_ROWS = 20000
MAX_NAME = 120
MAX_KEY = 60
CONTROL = re.compile(r"[\x00-\x1f\x7f]")
FORMULA = re.compile(r"^(?:[=+@]|-[\d=(])")


class SyncError(RuntimeError):
    pass


def norm_name(name: str) -> str:
    t = (name or "").upper().replace("&", " AND ")
    t = re.sub(r"[^A-Z0-9 ]", " ", t)
    return " ".join(w for w in t.split() if w not in SUFFIXES)


def likeness(a: str, b: str) -> float:
    na, nb = norm_name(a), norm_name(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    return round(difflib.SequenceMatcher(None, na, nb).ratio(), 2)


# ---- reading ------------------------------------------------------------

def check_name(value: str, limit: int = MAX_NAME, what="name") -> str:
    """'' when the value is fine to import, else the reason it is not."""
    v = value or ""
    if not v.strip():
        return f"empty {what}"
    if len(v) > limit:
        return f"{what} longer than {limit} characters"
    if CONTROL.search(v):
        return f"{what} holds control characters"
    if FORMULA.match(v.strip()):
        return f"{what} starts like a spreadsheet formula"
    return ""


def _rows_from(path=None, text=None) -> list[list[str]]:
    if path:
        fileguard.refuse_company_file(path)
        path = settings.check_safe(path)
        if os.path.getsize(path) > MAX_BYTES:
            raise SyncError(f"The file is larger than "
                            f"{MAX_BYTES // (1024 * 1024)} MB; split it or "
                            f"export fewer records.")
        if path.lower().endswith(".xlsx"):
            from openpyxl import load_workbook
            ws = load_workbook(path, read_only=True, data_only=True).active
            out = []
            for r in ws.iter_rows(values_only=True):
                if len(out) > MAX_ROWS:
                    raise SyncError(f"The file has more than {MAX_ROWS} "
                                    f"rows.")
                out.append(["" if c is None else str(c) for c in r])
            return out
        with open(path, encoding="utf-8-sig", errors="replace") as fh:
            text = fh.read()
    if text and len(text.encode("utf-8", "replace")) > MAX_BYTES:
        raise SyncError(f"The text is larger than "
                        f"{MAX_BYTES // (1024 * 1024)} MB.")
    sample = (text or "")[:2048]
    delim = "\t" if sample.count("\t") > sample.count(",") else ","
    out = [r for r in csv.reader(io.StringIO(text or ""), delimiter=delim)
           if any(c.strip() for c in r)]
    if len(out) > MAX_ROWS + 1:
        raise SyncError(f"The file has more than {MAX_ROWS} rows.")
    return out


def detect_map(headers, record_type) -> dict:
    low = [h.strip().lower() for h in headers]
    out = {}
    for field, names in FIELDS[record_type].items():
        for n in names:
            if n in low and low.index(n) not in out.values() and \
                    not SENSITIVE.search(n):
                out[field] = low.index(n)
                break
    return out


def parse(record_type, path=None, text=None, column_map=None) -> dict:
    if record_type not in RECORD_TYPES:
        raise SyncError(f"record type is one of {', '.join(RECORD_TYPES)}")
    rows = _rows_from(path, text)
    if not rows:
        raise SyncError("The file is empty.")
    headers = [h.strip() for h in rows[0]]
    ignored = [h for h in headers if SENSITIVE.search(h)]
    if column_map:
        low = [h.lower() for h in headers]
        cmap = {f: low.index(str(h).lower()) for f, h in column_map.items()
                if str(h).lower() in low}
    else:
        cmap = detect_map(headers, record_type)
    if "key" not in cmap and "name" in cmap:
        cmap["key"] = cmap["name"]
    if "key" not in cmap:
        raise SyncError("No key column found; set the column map.")
    if any(SENSITIVE.search(headers[i]) for i in cmap.values()):
        raise SyncError("A personal or bank data column can't be mapped.")
    recs, rejected = [], []
    for n, r in enumerate(rows[1:], start=2):
        rec = {f: (r[i].strip() if i < len(r) else "")
               for f, i in cmap.items()}
        if not rec.get("key") and not rec.get("name"):
            continue
        rec.setdefault("name", rec["key"])
        if not rec.get("name"):
            rec["name"] = rec["key"]
        why = check_name(rec.get("key", ""), MAX_KEY, "key") or \
            check_name(rec["name"]) or next(
                (f"{f} starts like a spreadsheet formula"
                 for f, v in rec.items() if f not in ("key", "name") and
                 v and FORMULA.match(v) and f != "amount"), "")
        if why:
            rejected.append({"row": n, "key": CONTROL.sub("?", rec.get(
                "key", ""))[:MAX_KEY], "reason": why})
            continue
        recs.append(rec)
    return {"records": recs, "rejected": rejected, "ignored": ignored,
            "map": {
        f: headers[i] for f, i in cmap.items()}}


# ---- comparing ----------------------------------------------------------

def _links(office, system, record_type) -> dict:
    return {r["erp_key"]: r for r in office.db.rows(
        "SELECT * FROM erp_links WHERE system = ? AND record_type = ? AND "
        "deleted = 0", (system, record_type))}


def _compare_vendors(office, system, recs) -> dict:
    local = office.db.rows("SELECT id, name, email, phone FROM vendors WHERE "
                           "deleted = 0 ORDER BY name")
    links = _links(office, system, "vendors")
    out = {"new": [], "matched": [], "likely": [], "changed": [],
           "only_here": []}
    seen = set()
    for r in recs:
        if r["key"] in links:
            lv = next((v for v in local if v["id"] ==
                       links[r["key"]]["local_id"]), None)
            if lv:
                seen.add(lv["id"])
                diffs = {f: {"erp": r.get(f, ""), "here": lv[f] or ""}
                         for f in ("name", "email", "phone")
                         if r.get(f) and r.get(f) != (lv[f] or "")}
                (out["changed"] if diffs else out["matched"]).append(
                    {"erp_key": r["key"], "erp_name": r["name"],
                     "local_id": lv["id"], "local_name": lv["name"],
                     "differences": diffs})
                continue
        exact = next((v for v in local if v["name"].lower() ==
                      r["name"].lower()), None)
        if exact:
            seen.add(exact["id"])
            out["matched"].append({"erp_key": r["key"], "erp_name": r["name"],
                                   "local_id": exact["id"],
                                   "local_name": exact["name"]})
            continue
        best = max(((likeness(r["name"], v["name"]), v) for v in local),
                   key=lambda x: x[0], default=(0.0, None))
        if best[1] is not None and best[0] >= LIKELY_MIN:
            seen.add(best[1]["id"])
            out["likely"].append({
                "erp_key": r["key"], "erp_name": r["name"],
                "local_id": best[1]["id"], "local_name": best[1]["name"],
                "score": f"{best[0]:.2f}",
                "reason": "same name apart from LLC/Inc/punctuation"
                if best[0] == 1.0 else "similar name"})
        else:
            out["new"].append({"erp_key": r["key"], "erp_name": r["name"],
                               "email": r.get("email", ""),
                               "phone": r.get("phone", ""),
                               "address": r.get("address", "")})
    out["only_here"] = [{"local_id": v["id"], "local_name": v["name"]}
                        for v in local if v["id"] not in seen]
    return out


def _compare_jobs(office, recs) -> dict:
    local = {j["number"]: j for j in jobs.jobs(office)}
    out = {"new": [], "matched": [], "likely": [], "changed": [],
           "only_here": []}
    for r in recs:
        j = local.pop(r["key"], None)
        if j is None:
            out["new"].append({"erp_key": r["key"], "erp_name": r["name"],
                               "note": "not in Back Office; jobs come from "
                                       "QuantiSheet"})
        elif r["name"] and r["name"] != j["name"]:
            out["changed"].append({"erp_key": r["key"], "local_id": j["id"],
                                   "differences": {"name": {
                                       "erp": r["name"], "here": j["name"]}}})
        else:
            out["matched"].append({"erp_key": r["key"], "local_id": j["id"]})
    out["only_here"] = [{"local_id": j["id"], "local_name": j["number"]}
                        for j in local.values()]
    return out


def _compare_codes(office, recs) -> dict:
    out = {"new": [], "matched": [], "likely": [], "changed": [],
           "only_here": []}
    js = {j["number"]: j for j in jobs.jobs(office)}
    seen = set()
    for r in recs:
        j = js.get(r.get("job", ""))
        if j is None:
            out["new"].append({"erp_key": r["key"], "job": r.get("job", ""),
                               "note": "job not in Back Office"})
            continue
        codes = {c["code"]: c for c in jobs.section(office, j["id"],
                                                    "cost_codes")}
        c = codes.get(r["key"])
        seen.add((j["id"], r["key"]))
        if c is None:
            out["new"].append({"erp_key": r["key"], "job": j["number"],
                               "erp_name": r["name"],
                               "note": "not in the QuantiSheet snapshot"})
        elif r["name"] and r["name"] != r["key"] and \
                r["name"].lower() != (c["description"] or "").lower():
            out["changed"].append({"erp_key": r["key"], "job": j["number"],
                                   "differences": {"description": {
                                       "erp": r["name"],
                                       "here": c["description"]}}})
        else:
            out["matched"].append({"erp_key": r["key"], "job": j["number"]})
    jobs_in_file = {r.get("job") for r in recs}
    for num, j in js.items():
        if num not in jobs_in_file:
            continue
        for c in jobs.section(office, j["id"], "cost_codes"):
            if (j["id"], c["code"]) not in seen:
                out["only_here"].append({"job": num, "local_name": c["code"]})
    return out


def _compare_employees(office, recs) -> dict:
    local = office.db.rows("SELECT id, name, employee_no FROM employees "
                           "WHERE deleted = 0")
    by_no = {e["employee_no"]: e for e in local}
    out = {"new": [], "matched": [], "likely": [], "changed": [],
           "only_here": []}
    seen = set()
    for r in recs:
        e = by_no.get(r["key"])
        if e is None:
            out["new"].append({"erp_key": r["key"], "erp_name": r["name"]})
            continue
        seen.add(e["id"])
        if r["name"] and r["name"].lower() != e["name"].lower():
            out["changed"].append({"erp_key": r["key"], "local_id": e["id"],
                                   "differences": {"name": {
                                       "erp": r["name"], "here": e["name"]}}})
        else:
            out["matched"].append({"erp_key": r["key"], "local_id": e["id"]})
    out["only_here"] = [{"local_id": e["id"], "local_name": e["name"]}
                        for e in local if e["id"] not in seen]
    return out


def _compare_commitments(office, recs) -> dict:
    from . import cents
    out = {"new": [], "matched": [], "likely": [], "changed": [],
           "only_here": []}
    snap = {}
    for j in jobs.jobs(office):
        for c in jobs.section(office, j["id"], "commitments"):
            snap[c["number"]] = (j, c)
    for r in recs:
        hit = snap.pop(r["key"], None)
        if hit is None:
            out["new"].append({"erp_key": r["key"], "erp_name": r.get(
                "vendor", "")})
            continue
        j, c = hit
        here = sum(cents.to_cents(ln["amount"]) for ln in c["lines"])
        try:
            erp_amt = cents.parse_amount(r.get("amount") or "0")
        except Exception:                                 # noqa: BLE001
            erp_amt = None
        if erp_amt is not None and erp_amt != here:
            out["changed"].append({"erp_key": r["key"], "job": j["number"],
                                   "differences": {"amount": {
                                       "erp": cents.text(erp_amt),
                                       "here": cents.text(here)}}})
        else:
            out["matched"].append({"erp_key": r["key"], "job": j["number"]})
    out["only_here"] = [{"local_name": k, "job": j["number"]}
                        for k, (j, _) in snap.items()]
    return out


# ---- runs -----------------------------------------------------------------

def import_file(office, system, record_type, path=None, text=None,
                column_map=None) -> dict:
    """Read one export and record a Sync run for review. Changes nothing."""
    office.require("sync.run", "erp_run", system)
    if system not in SYSTEMS:
        raise SyncError(f"system is one of {', '.join(SYSTEMS)}")
    p = parse(record_type, path, text, column_map)
    recs = p["records"]
    cmp_ = {"vendors": lambda: _compare_vendors(office, system, recs),
            "jobs": lambda: _compare_jobs(office, recs),
            "cost_codes": lambda: _compare_codes(office, recs),
            "employees": lambda: _compare_employees(office, recs),
            "commitments": lambda: _compare_commitments(office, recs)}[
        record_type]()
    cmp_["rejected"] = p["rejected"]
    raw = json.dumps(recs, sort_keys=True).encode()
    counts = {k: len(v) for k, v in cmp_.items()}
    counts["rows"] = len(recs)
    with office.db.tx():
        rid = office.db.insert(
            "erp_runs", system=system, direction="import",
            record_type=record_type,
            file_name=os.path.basename(path) if path else "(pasted)",
            file_hash=hashlib.sha256(raw).hexdigest()[:16],
            counts=json.dumps(counts), differences=json.dumps(cmp_),
            status="Review", ignored=json.dumps(p["ignored"]))
        for r in recs:
            office.db.insert("erp_records", system=system,
                             record_type=record_type, erp_key=r["key"],
                             data=json.dumps(r), run_id=rid)
        office.audit("sync import", "erp_run", rid, None,
                     {"system": system, "type": record_type,
                      "counts": counts, "ignored_columns": p["ignored"]})
    return run(office, rid)


def run(office, rid) -> dict:
    r = office.db.get("erp_runs", rid)
    if r is None:
        raise SyncError(f"no sync run {rid}")
    for k in ("counts", "differences", "ignored"):
        r[k] = json.loads(r[k] or "null")
    return r


def runs(office, system=None) -> list[dict]:
    q, p = "SELECT id FROM erp_runs WHERE deleted = 0", []
    if system:
        q += " AND system = ?"
        p.append(system)
    return [run(office, x["id"]) for x in office.db.rows(q + " ORDER BY id "
                                                          "DESC", p)]


def last_runs(office) -> dict:
    """{system: {'import': run or None, 'export': run or None}}."""
    out = {}
    for s in SYSTEMS:
        d = {}
        for direction in ("import", "export"):
            x = office.db.one("SELECT id FROM erp_runs WHERE system = ? AND "
                              "direction = ? AND deleted = 0 ORDER BY id "
                              "DESC LIMIT 1", (s, direction))
            d[direction] = run(office, x["id"]) if x else None
        out[s] = d
    return out


def confirm_match(office, rid, erp_key, local_id) -> int:
    """A person confirms a likely match: the two are linked. Neither name
    is changed."""
    office.require("sync.run", "erp_run", rid)
    r = run(office, rid)
    item = next((x for x in r["differences"]["likely"] +
                 r["differences"]["matched"] if x["erp_key"] == erp_key),
                None)
    if item is None or item.get("local_id") != local_id:
        raise SyncError("That pair is not a match in this run.")
    with office.db.tx():
        cur = _links(office, r["system"], r["record_type"]).get(erp_key)
        if cur:
            office.db.update("erp_links", cur["id"], local_id=local_id)
            lid = cur["id"]
        else:
            lid = office.db.insert(
                "erp_links", system=r["system"],
                record_type=r["record_type"], erp_key=erp_key,
                erp_name=item.get("erp_name", ""),
                local_type=r["record_type"], local_id=local_id)
        office.audit("sync link", "erp_link", lid, None,
                     {"run": rid, "erp_key": erp_key, "local_id": local_id})
    return lid


def apply(office, rid, create_keys=()) -> dict:
    """Apply after review: add the NEW vendors the user ticked (and link
    them). Matches stay links only; nothing is renamed or overwritten."""
    office.require("sync.run", "erp_run", rid)
    r = run(office, rid)
    if r["status"] != "Review":
        raise SyncError(f"This run is {r['status']}.")
    if create_keys and r["record_type"] != "vendors":
        raise SyncError("Only new vendors are added from a sync; jobs and "
                        "cost codes come from QuantiSheet.")
    new = {x["erp_key"]: x for x in r["differences"]["new"]}
    made = []
    with office.db.tx():
        for k in create_keys:
            if k not in new:
                raise SyncError(f"{k} is not a new record in this run.")
            x = new[k]
            why = check_name(x["erp_name"])
            if why:
                raise SyncError(f"{k}: {why}; not added.")
            vid = ap.add_vendor(office, x["erp_name"], email=x.get("email",
                                                                    ""),
                                phone=x.get("phone", ""),
                                address=x.get("address", ""))
            office.db.insert("erp_links", system=r["system"],
                             record_type="vendors", erp_key=k,
                             erp_name=x["erp_name"], local_type="vendors",
                             local_id=vid)
            made.append(vid)
        office.db.update("erp_runs", rid, status="Applied",
                         applied_by=office.who, applied_at=clock.iso_now())
        office.audit("sync apply", "erp_run", rid, None,
                     {"created": made})
    return {"created": made, "report": report(office, rid)}


def record_export(office, system, batch_id) -> int:
    """Log an export round (the files come from exports.export)."""
    office.require("sync.run", "erp_run", system)
    b = office.db.get("export_batches", batch_id) if batch_id else None
    if b is None:
        raise SyncError("Export a batch first (Exports page).")
    with office.db.tx():
        rid = office.db.insert(
            "erp_runs", system=system, direction="export",
            record_type=b["type"] or "",
            file_name=os.path.basename(b["file_path"] or ""),
            file_hash=b["file_hash"] or "",
            counts=json.dumps({"records": b["record_count"] or 0}),
            differences="{}", status="Exported", batch_id=batch_id,
            applied_by=office.who, applied_at=clock.iso_now(), ignored="[]")
        office.audit("sync export", "erp_run", rid, None,
                     {"system": system, "batch": batch_id})
    return rid


def report(office, rid) -> list[str]:
    """The reconciliation report after a round, in plain lines."""
    r = run(office, rid)
    c = r["counts"] or {}
    out = [f"{r['system']} {r['record_type']} {r['direction']} "
           f"({r['file_name']}), status {r['status']}"]
    if r["direction"] == "import":
        out.append(f"{c.get('rows', 0)} rows: {c.get('matched', 0)} match, "
                   f"{c.get('likely', 0)} likely match (confirm), "
                   f"{c.get('changed', 0)} changed, {c.get('new', 0)} new, "
                   f"{c.get('only_here', 0)} only in Back Office")
        for x in r["differences"].get("likely", []):
            out.append(f"Likely: '{x['erp_name']}' = '{x['local_name']}'? "
                       f"({x['reason']})")
        for x in r["differences"].get("changed", []):
            for f, v in x["differences"].items():
                out.append(f"Changed {x['erp_key']} {f}: accounting system "
                           f"'{v['erp']}', Back Office '{v['here']}'")
        if r["ignored"]:
            out.append("Ignored (personal/bank data, not read): " +
                       ", ".join(r["ignored"]))
    else:
        out.append(f"{c.get('records', 0)} records in batch "
                   f"{r['batch_id']}")
    return out
