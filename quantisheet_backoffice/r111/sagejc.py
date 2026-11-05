"""Job Cost Report PDF import.

Reads the report from the PDF's text words (PyMuPDF get_text('words')).
Printer files (.PRN) are refused and never opened. The layout is a job
header (number, name, address), then each cost code (for example
"01-042 Scheduling Expense"), one line per category (Labor, Material,
Subcontractor, Other, ...), then a "Cost Code Totals" line ending in "*".

Columns, left to right: Original Estimate, Approved Changes, Total
Estimate, Total Committed, Remaining to Commit, JTD Cost, Budget Variance.
A trailing minus is negative (16,121- and 700.00-).

publish() feeds the existing job cost view: budget, committed and actual
on a published code come from this report, and a negative budget variance
(or JTD over the total estimate) sets overrun. Unpublish puts the books
figures back. Snapshot rows already stored are not rewritten.
"""
from __future__ import annotations

import os
import re

from .. import cents, clock, fileguard, jobs, store
from . import pdfutil, schema

_JOB = re.compile(
    r"\bJob(?:\s+(?:Number|No\.?))?\s*[:#]?\s*"
    r"([A-Za-z0-9]+(?:-[A-Za-z0-9]+)*)\b(.*)$", re.I)
_CODE = re.compile(r"^(\d{2}-\d{2,4}(?:-\d{2,4})?)\b\s*(.*)$")
_MONEY = re.compile(
    r"^(?:[\(\-]?\$?\d{1,3}(?:,\d{3})*(?:\.\d+)?\)?\-?"
    r"|[\(\-]?\$?\d+(?:\.\d+)?\)?\-?)$")
_COLS = ("original", "changes_amt", "total_estimate", "committed",
         "remaining", "jtd", "variance")


class SageError(ValueError):
    pass


def parse_money_token(token: str):
    """One report amount -> int cents, or None when `token` is not an
    amount. A trailing '-' or parentheses means negative."""
    s = str(token or "").strip().replace("*", "")   # "1,536*" on totals
    if not s or not _MONEY.fullmatch(s):
        return None
    if s.startswith("-") and s.endswith("-"):
        return None
    neg = False
    if s.endswith("-"):
        neg = True
        s = s[:-1]
    elif s.startswith("(") and s.endswith(")"):
        neg = True
        s = s[1:-1]
    elif s.startswith("-"):
        neg = True
        s = s[1:]
    s = s.replace("$", "").replace(",", "").strip()
    if not s:
        return None
    c = cents.to_cents(s)
    return -c if neg else c


def _glue(tokens: list[str]) -> list[str]:
    """A minus sign that extracted as its own word belongs to the amount
    before it (16,121 and -  ->  16,121-)."""
    out = []
    for t in tokens:
        if t == "-" and out and parse_money_token(out[-1]) is not None \
                and not str(out[-1]).endswith("-"):
            out[-1] = out[-1] + "-"
        else:
            out.append(t)
    return out


def _group(words: list[dict]) -> list[dict]:
    rows = []
    for w in words:
        hit = None
        for row in rows:
            if row["page"] == w["page"] and abs(row["y"] - w["y0"]) <= 3:
                hit = row
                break
        if hit is None:
            hit = {"page": w["page"], "y": w["y0"], "items": []}
            rows.append(hit)
        hit["items"].append(w)
    for row in rows:
        row["items"].sort(key=lambda w: (w["x0"], w["y0"]))
        row["tokens"] = _glue([w["t"] for w in row["items"]])
        row["text"] = " ".join(row["tokens"])
    rows.sort(key=lambda r: (r["page"], r["y"]))
    return rows


def _split_amounts(tokens: list[str]):
    idxs = [i for i, t in enumerate(tokens) if parse_money_token(t) is not None]
    if len(idxs) < 7:
        return [], " ".join(tokens).strip()
    use = idxs[-7:]
    label = " ".join(tokens[:use[0]]).strip()
    return [parse_money_token(tokens[i]) for i in use], label


# Position-aware reading (Nov 4, checked on a real report): a blank cell is
# simply missing from the line, so amounts are placed by where they sit
# under the column headings (right-aligned), not by counting them.
_TOL = 40.0
_HEADS = ("original", "approved", "total", "remaining", "jtd", "budget",
          "estimate", "changes", "committed", "commit", "cost", "variance")


_ENDS = ("estimate", "changes", "estimate", "committed", "commit", "cost",
         "variance")


def _anchors_by_words(items) -> list:
    """Right edges of the 7 headings' last words, in order (Original
    EstimatE, Approved ChangeS, Total EstimatE, Total CommitteD, Remaining
    to CommiT, JTD CosT, Budget VariancE) - works whether a heading is on
    one line or two, and however close the headings sit."""
    edges, k = [], 0
    for w in items:
        if k < 7 and w["t"].lower().strip("*:") == _ENDS[k]:
            edges.append(w["x1"])
            k += 1
    return edges if k == 7 else []


def _anchors(row) -> list:
    """The 7 columns' right edges from a heading line: by the headings'
    last words when they're all there, else its words grouped by the
    gaps between them."""
    items = sorted(row["items"], key=lambda w: w["x0"])
    got = _anchors_by_words(items)
    if got:
        return got
    groups, cur = [], []
    for w in items:
        if cur and w["x0"] - cur[-1]["x1"] > 12:
            groups.append(cur)
            cur = []
        cur.append(w)
    if cur:
        groups.append(cur)
    edges = [g[-1]["x1"] for g in groups
             if any(x["t"].lower() in _HEADS for x in g)]
    return edges[-7:] if len(edges) >= 7 else []


def _row_amounts(row):
    """[(token, x1 or None)] for a line; a lone '-' or '*' joins the
    amount before it."""
    out = []
    for w in sorted(row["items"], key=lambda w: w["x0"]):
        t = w["t"]
        if t in ("-", "-*", "*-") and out and out[-1][1] is not None and \
                not out[-1][0].endswith("-"):
            out[-1] = (out[-1][0] + "-", w["x1"])
        elif t == "*" and out and out[-1][1] is not None:
            out[-1] = (out[-1][0], w["x1"])
        elif parse_money_token(t) is not None:
            out.append((t, w["x1"]))
        else:
            out.append((t, None))
    return out


def _split_by_columns(row, anchors):
    """(7 amounts in cents, label): each amount under its column (a blank
    cell is 0); ([], text) when the line has no amounts."""
    toks = _row_amounts(row)
    vals = [0] * 7
    found, label_parts = 0, []
    for t, x1 in toks:
        if x1 is None:
            if not found:
                label_parts.append(t)
            continue
        col = min(range(7), key=lambda k: abs(anchors[k] - x1))
        if abs(anchors[col] - x1) > _TOL:
            if not found:
                label_parts.append(t)
            continue
        vals[col] = parse_money_token(t)
        found += 1
    if not found:
        return [], " ".join(t for t, _x in toks).strip()
    return vals, " ".join(label_parts).strip()


_JOBLINE = re.compile(r"^(\d{2,}-[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*)\s+(.+)$")


def _headerish(text: str) -> bool:
    low = text.lower()
    return sum(k in low for k in ("original", "variance", "committed", "jtd")) >= 2


def _is_total(label: str) -> bool:
    low = " ".join(label.lower().split())
    return "*" in label or "cost code total" in low


def _seven(nums: list[int]) -> dict:
    vals = dict(zip(_COLS, nums))
    vals["overrun"] = int(vals["variance"] < 0 or
                          vals["jtd"] > vals["total_estimate"])
    return vals


def _stated(row, anchors) -> dict:
    """{column: cents} for the amounts printed on a totals line."""
    out = {}
    for t, x1 in _row_amounts(row):
        if x1 is None:
            continue
        col = min(range(7), key=lambda k: abs(anchors[k] - x1))
        if abs(anchors[col] - x1) <= _TOL:
            v = parse_money_token(t)
            if v is not None:
                out[_COLS[col]] = v
    return out


_LABELS = {"original": "Original Estimate", "changes_amt": "Approved Changes",
           "total_estimate": "Total Estimate", "committed": "Total Committed",
           "remaining": "Remaining to Commit", "jtd": "JTD Cost",
           "variance": "Budget Variance"}


def parsed_totals(section) -> dict:
    """{column: cents} summed over each cost code's totals line (its
    category lines when it has none)."""
    tot = {c: 0 for c in _COLS}
    for code in section["codes"]:
        lines = [ln for ln in code["lines"] if ln["is_total"]] or \
            code["lines"]
        for ln in lines:
            for c in _COLS:
                tot[c] += ln.get(c) or 0
    return tot


def mismatches(section) -> list:
    """[(column label, parsed cents, report's own cents)] where what was
    read doesn't add up to the report's Job Totals line. The report
    rounds each code to whole dollars, so up to 50 cents a code (at least
    $2) is allowed. [] when it adds up or the report has no Job Totals."""
    stated = section.get("stated") or {}
    if not stated:
        return []
    got = parsed_totals(section)
    tol = max(200, 50 * len(section["codes"]))
    return [(_LABELS[c], got[c], v) for c, v in stated.items()
            if abs(got[c] - v) > tol]


def _job_line(ln, text):
    """(number, name) when this line is a job line ("99-T-001  Example
    Hall", or "Job: 4401 Name"), else None."""
    if _CODE.match(text) or _headerish(text):
        return None
    amounts, _label = _split_amounts(ln["tokens"])
    if amounts:
        return None
    jm = _JOBLINE.match(text)
    if jm:
        return jm.group(1), jm.group(2).strip(" -:")
    m = _JOB.search(text)
    if m and re.search(r"\d", m.group(1)):
        return m.group(1), (m.group(2) or "").strip(" -:")
    return None


def parse_words(words: list[dict]) -> dict:
    """Words from pdfutil.words (or the same shape) -> a report dict.
    Money is int cents. overrun is 1 or 0.

    A report can hold several jobs (one after another, each with its own
    header and Job Totals). report["jobs"] lists each as {job_number,
    job_name, address, codes}; the top-level job_number / codes are the
    first job's (Nov 4: three jobs in one file had all gone to the
    first)."""
    jobs_out = []
    cur = None
    anchors = []
    page, in_head = None, True
    page_job_done = False      # this page's header already named its job
    after_job_totals = False   # the next job may start mid-page

    def start(number, name):
        nonlocal cur
        cur = {"job_number": number, "job_name": name, "address": "",
               "codes": [], "_seen_code": False, "_current": None}
        jobs_out.append(cur)

    for ln in _group(words):
        text = ln["text"].strip()
        if not text:
            continue
        if ln["page"] != page:          # every page repeats the job header
            page, in_head = ln["page"], True
            page_job_done = False
        if _headerish(text):
            got = _anchors(ln)
            if got:
                anchors = got
                in_head = False
                continue
        # a job line counts only where a job is named: the first one,
        # the top of a page's header, or right after Job Totals - so an
        # address such as "10-12 Main St" never starts a job
        eligible = cur is None or not cur["job_number"] or \
            (in_head and not page_job_done) or after_job_totals
        job = _job_line(ln, text) if eligible else None
        if job:
            page_job_done = True
            after_job_totals = False
            if cur is not None and not cur["job_number"] and \
                    not cur["_seen_code"]:
                cur["job_number"], cur["job_name"] = job
            elif cur is None or job[0] != cur["job_number"]:
                start(*job)
            continue
        if in_head and anchors:
            if cur is not None and cur["job_number"] and \
                    not cur["address"] and not cur["_seen_code"] and \
                    not _CODE.match(text) and \
                    not _split_by_columns(ln, anchors)[0] and \
                    "job cost report" not in text.lower():
                cur["address"] = text   # a new job's first header page
            continue                    # a later page's header block
        if cur is None:
            start("", "")
        low = " ".join(text.lower().split())
        if "totals" in low and "cost code" not in low:
            cur["_current"] = None      # job / extra / report totals
            if low.startswith("job totals") or \
                    low.startswith("extra totals"):
                after_job_totals = True
            if low.startswith("job totals") and anchors:
                cur["stated"] = _stated(ln, anchors)
            continue
        if anchors:
            amounts, label = _split_by_columns(ln, anchors)
        else:
            amounts, label = _split_amounts(ln["tokens"])
        if cur["job_number"] and not cur["address"] and \
                not cur["_seen_code"] and not amounts and \
                not _CODE.match(text) and not _headerish(text):
            cur["address"] = text
            continue
        cm = _CODE.match(label) or _CODE.match(text)
        current = cur["_current"]
        if cm and len(amounts) < 7:
            current = {"code": cm.group(1),
                       "description": cm.group(2).strip(" -:*"), "lines": []}
            cur["codes"].append(current)
            cur["_current"] = current
            cur["_seen_code"] = True
            continue
        if len(amounts) < 7 or current is None and not cm:
            continue
        if current is None:
            current = {"code": cm.group(1),
                       "description": (cm.group(2) or "").strip(" -:*"),
                       "lines": []}
            cur["codes"].append(current)
            cur["_current"] = current
            cur["_seen_code"] = True
            is_total, category = 1, ""
        else:
            is_total = 1 if _is_total(label) else 0
            category = "" if is_total else label.strip()
        current["lines"].append({"category": category, "is_total": is_total,
                                 **_seven(amounts)})
    jobs_out = [j for j in jobs_out if j["codes"]]
    for j in jobs_out:
        j.pop("_seen_code", None)
        j.pop("_current", None)
        j.setdefault("stated", {})
    if not jobs_out:
        raise SageError("No cost codes were found in this Job Cost Report.")
    first = jobs_out[0]
    report = {"job_number": first["job_number"], "job_name": first["job_name"],
              "address": first["address"], "codes": first["codes"],
              "stated": first["stated"], "jobs": jobs_out}
    return report


def _refuse_prn(path) -> None:
    if str(path).lower().endswith(".prn"):
        raise SageError("Printer files (.PRN) can't be read yet. In Sage, "
                        "print the Job Cost Report again and choose "
                        "Microsoft Print to PDF (or Save as PDF) as the "
                        "printer, then import that PDF.")
    if not str(path).lower().endswith(".pdf"):
        raise SageError("Choose the Job Cost Report PDF.")


def read_pdf(path) -> dict:
    """Parse a Job Cost Report PDF. Does not open .PRN files."""
    _refuse_prn(path)
    fileguard.refuse_company_file(path)
    if not os.path.isfile(path):
        raise SageError("That file was not found.")
    found = pdfutil.words(path)
    report = parse_words(found)
    report["page_count"] = (max(w["page"] for w in found) + 1) if found else 0
    return report


def _job_for(office, report, job_id):
    if job_id:
        j = office.db.get("jobs", job_id)
        if not j or j.get("deleted"):
            raise SageError("That job was not found.")
        return job_id
    number = report["job_number"]
    if not number:
        raise SageError("The report has no job number. Choose the job to "
                        "attach it to.")
    found = jobs.job_by_number(office, number)
    if found:
        return found["id"]
    return office.db.insert(
        "jobs", number=number, name=report["job_name"] or number,
        project={"name": report["job_name"], "number": number,
                 "address": report["address"]},
        retainage_work="0", retainage_stored="0", state="",
        last_snapshot_at="", source={"kind": "job cost report"})


def _pick_sections(office, report, job_id):
    """[(section, job_id or None)] to import. One job in the file: that
    one, onto job_id if given. Several: with job_id, only the section
    whose number is that job's; without, every section (each matched or
    added by its number)."""
    secs = report.get("jobs") or [report]
    if len(secs) == 1:
        return [(secs[0], job_id)]
    if job_id:
        j = office.db.get("jobs", job_id)
        if not j or j.get("deleted"):
            raise SageError("That job was not found.")
        want = str(j.get("number") or "").strip()
        hit = [s_ for s_ in secs if s_["job_number"] == want]
        if not hit:
            raise SageError(
                "This report has %d jobs (%s), and none is job %s. Choose "
                "'Each job in the report' to import each one under its "
                "own job number." % (
                    len(secs), ", ".join(s_["job_number"] for s_ in secs),
                    want or "(no number)"))
        return [(hit[0], job_id)]
    return [(s_, None) for s_ in secs]


def previous_imports(office, path) -> list:
    """Imports already made from this very file (same contents)."""
    schema.ensure(office.db)
    h = store.file_hash(path)
    return office.db.rows(
        "SELECT id, job_number, created_at, status FROM sage_imports WHERE "
        "source_hash = ? AND deleted = 0 ORDER BY id", (h,))


def preview(office, path, job_id=None) -> dict:
    """What an import would store, before anything is stored (reviews 1 +
    2, Nov 4): each job (existing or new), its codes, lines and totals,
    whether it adds up to the report's own Job Totals, and whether this
    file was imported before."""
    full = read_pdf(path)
    schema.ensure(office.db)
    picks = _pick_sections(office, full, job_id)
    jobs_ = []
    for section, jid in picks:
        if jid:
            j = office.db.get("jobs", jid)
            existing = j
        else:
            existing = jobs.job_by_number(office, section["job_number"]) \
                if section["job_number"] else None
        tot = parsed_totals(section)
        jobs_.append({
            "job_number": section["job_number"],
            "job_name": section["job_name"],
            "job_id": existing["id"] if existing else None,
            "new": existing is None,
            "codes": len(section["codes"]),
            "lines": sum(len(c["lines"]) for c in section["codes"]),
            "total_estimate": tot["total_estimate"], "jtd": tot["jtd"],
            "committed": tot["committed"],
            "mismatches": mismatches(section)})
    return {"file": os.path.basename(str(path)), "jobs": jobs_,
            "new_jobs": sum(1 for j in jobs_ if j["new"]),
            "duplicate_of": [r["id"] for r in previous_imports(office, path)],
            "adds_up": not any(j["mismatches"] for j in jobs_),
            "page_count": full.get("page_count") or 0}


def preview_text(pv) -> str:
    """The preview in plain words for the confirm box."""
    out = [f"{pv['file']}: {len(pv['jobs'])} job(s)"]
    for j in pv["jobs"]:
        tag = "NEW job" if j["new"] else "existing job"
        out.append(f"  {j['job_number']} {j['job_name']} ({tag}): "
                   f"{j['codes']} codes, {j['lines']} lines, total estimate "
                   f"{cents.fmt(j['total_estimate'])}, JTD "
                   f"{cents.fmt(j['jtd'])}")
        for lab, got, want in j["mismatches"]:
            out.append(f"    Doesn't add up: {lab} read as {cents.fmt(got)}, "
                       f"the report says {cents.fmt(want)}")
    if pv["new_jobs"]:
        out.append(f"{pv['new_jobs']} new job(s) will be added.")
    if pv["duplicate_of"]:
        out.append("This file was already imported.")
    return "\n".join(out)


def import_pdf(office, path, job_id=None, note="",
               allow_duplicate=False) -> int:
    """Store the report. Status stays 'stored' until publish(). A report
    with several jobs is stored as one import per job (see
    _pick_sections); the first import's id is returned.""" 
    schema.need(office, "snapshot.import", record_type="sage_import",
                record_id=os.path.basename(str(path)))
    full = read_pdf(path)
    schema.ensure(office.db)
    picks = _pick_sections(office, full, job_id)
    if not allow_duplicate and previous_imports(office, path):
        raise SageError("This job cost report was already imported. "
                        "Publish the earlier import instead, or import it "
                        "again on purpose.")
    kept = store.copy_into(office.documents_folder(), path)
    ids = []
    with office.db.tx():
        for section, jid_in in picks:
            report = dict(section, page_count=full.get("page_count"))
            ids.append(_store_one(office, report, jid_in, path, kept, note))
    return ids[0]


def _store_one(office, report, job_id, path, kept, note):
    if True:                    # (kept indented as it was inside the tx)
        jid = _job_for(office, report, job_id)
        iid = office.db.insert(
            "sage_imports", job_id=jid, job_number=report["job_number"],
            job_name=report["job_name"], address=report["address"],
            source_name=os.path.basename(str(path)), source_path=kept,
            source_hash=store.file_hash(kept), status="stored",
            page_count=report.get("page_count") or 0, note=note or "")
        n = 0
        for code in report["codes"]:
            for ln in code["lines"]:
                n += 1
                office.db.insert(
                    "sage_lines", import_id=iid, line_no=n,
                    cost_code=code["code"], description=code["description"],
                    category=ln["category"], is_total=ln["is_total"],
                    original=ln["original"], changes_amt=ln["changes_amt"],
                    total_estimate=ln["total_estimate"],
                    committed=ln["committed"], remaining=ln["remaining"],
                    jtd=ln["jtd"], variance=ln["variance"],
                    overrun=ln["overrun"])
        office.audit("import", "sage_import", iid, None,
                     {"job_id": jid, "job_number": report["job_number"],
                      "codes": len(report["codes"]), "lines": n,
                      "file": os.path.basename(str(path))})
    return iid


def get_import(office, import_id) -> dict:
    schema.ensure(office.db)
    row = office.db.get("sage_imports", import_id)
    if not row or row.get("deleted"):
        raise SageError("That job cost report is not on file.")
    return row


def lines(office, import_id) -> list[dict]:
    get_import(office, import_id)
    return office.db.rows("SELECT * FROM sage_lines WHERE import_id = ? AND "
                          "deleted = 0 ORDER BY line_no", (import_id,))


def _rollup(rows: list[dict]) -> list[dict]:
    """One row per cost code: the Cost Code Totals line when the report
    has one, otherwise the sum of the category lines."""
    order = []
    bucket = {}
    for ln in rows:
        slot = bucket.get(ln["cost_code"])
        if slot is None:
            slot = {"code": ln["cost_code"], "description": "",
                    "categories": [], "total": None}
            bucket[ln["cost_code"]] = slot
            order.append(ln["cost_code"])
        if ln.get("description") and not slot["description"]:
            slot["description"] = ln["description"]
        if ln["is_total"]:
            slot["total"] = ln
        else:
            slot["categories"].append(ln)
    out = []
    for code in order:
        slot = bucket[code]
        if slot["total"] is not None:
            src = slot["total"]
            nums = {k: src[k] for k in _COLS}
            overrun = int(src["overrun"])
        elif slot["categories"]:
            nums = {k: sum(c[k] for c in slot["categories"]) for k in _COLS}
            overrun = int(nums["variance"] < 0 or
                          nums["jtd"] > nums["total_estimate"])
        else:
            continue
        cats = []
        for c in slot["categories"]:
            cats.append({"category": c["category"],
                         **{k: c[k] for k in _COLS},
                         "overrun": bool(c["overrun"])})
        out.append({"code": code, "description": slot["description"],
                    **nums, "overrun": bool(overrun), "categories": cats})
    return out


def comparison(office, job_id=None, import_id=None) -> list[dict]:
    """Budget vs committed vs actual (JTD) per cost code, overruns flagged.
    Uses `import_id`, else the published report for the job, else the
    latest stored report for the job."""
    schema.ensure(office.db)
    if import_id is None:
        if job_id is None:
            return []
        row = office.db.one(
            "SELECT id FROM sage_imports WHERE job_id = ? AND deleted = 0 "
            "AND status = 'published' ORDER BY id DESC LIMIT 1", (job_id,))
        if row is None:
            row = office.db.one(
                "SELECT id FROM sage_imports WHERE job_id = ? AND deleted = 0 "
                "ORDER BY id DESC LIMIT 1", (job_id,))
        if row is None:
            return []
        import_id = row["id"]
    return _rollup(lines(office, import_id))


def latest_import(office, job_id):
    """The job's report to act on: the published one, else the newest
    stored one; None when the job has none."""
    schema.ensure(office.db)
    for where in ("AND status = 'published' ", ""):
        row = office.db.one(
            "SELECT id FROM sage_imports WHERE job_id = ? AND deleted = 0 "
            + where + "ORDER BY id DESC LIMIT 1", (job_id,))
        if row is not None:
            return row["id"]
    return None


def publish(office, import_id) -> None:
    """The job cost view uses this report for the codes it contains."""
    schema.need(office, "snapshot.import", record_type="sage_import",
                record_id=import_id)
    imp = get_import(office, import_id)
    if not imp["job_id"]:
        raise SageError("Attach the report to a job before publishing it.")
    with office.db.tx():
        for old in office.db.rows(
                "SELECT id FROM sage_imports WHERE job_id = ? AND "
                "status = 'published' AND deleted = 0", (imp["job_id"],)):
            if old["id"] != import_id:
                office.db.update("sage_imports", old["id"], status="stored")
        office.db.update("sage_imports", import_id, status="published")
        office.audit("publish", "sage_import", import_id,
                     {"status": imp["status"]},
                     {"job_id": imp["job_id"], "on": clock.today().isoformat()})


def unpublish(office, import_id) -> None:
    """Job cost goes back to the books figures. The report stays stored."""
    schema.need(office, "snapshot.import", record_type="sage_import",
                record_id=import_id)
    imp = get_import(office, import_id)
    with office.db.tx():
        office.db.update("sage_imports", import_id, status="stored")
        office.audit("unpublish", "sage_import", import_id,
                     {"status": imp["status"]}, {"status": "stored"})


def published_map(office, job_id) -> dict:
    """What jobcost.job_cost reads. Empty when nothing is published
    (and when these tables are not in the file yet)."""
    if not schema.has_table(office.db, "sage_imports"):
        return {}
    row = office.db.one(
        "SELECT * FROM sage_imports WHERE job_id = ? AND status = "
        "'published' AND deleted = 0 ORDER BY id DESC LIMIT 1", (job_id,))
    if not row:
        return {}
    out = {}
    for code in _rollup(office.db.rows(
            "SELECT * FROM sage_lines WHERE import_id = ? AND deleted = 0 "
            "ORDER BY line_no", (row["id"],))):
        code["import_id"] = row["id"]
        code["source_name"] = row["source_name"] or ""
        code["imported_on"] = (row["created_at"] or "")[:10]
        out[code["code"]] = code
    return out
