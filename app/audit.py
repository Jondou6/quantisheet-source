"""Measurement audit trail and the takeoff mirror.

Every measurement carries who took it off, when, how (by hand, auto area,
trace, auto count, carried from an older set), the scale it was measured
at and, for automatic counts, how confident the match was (annotate.py
writes it as PSAudit). This module:

* trail(doc): one row per measurement with all of that plus its sheet
  number, the revision it was taken in, and its review status;
* mirror(doc, job, file): copies the takeoff into the shared price
  database (table takeoff_items) so it can be searched across files and
  jobs - "every 6\\" storm pipe we've measured this year";
* search(text, ...): that search.
"""
import datetime
import logging
import os

from . import annotate

log = logging.getLogger(__name__)

DDL = """
CREATE TABLE IF NOT EXISTS takeoff_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT, job TEXT, file TEXT, page INTEGER,
    sheet TEXT, grp TEXT, type TEXT, value REAL, unit TEXT, author TEXT,
    taken TEXT, method TEXT, confidence REAL, scale TEXT, status TEXT,
    revision TEXT, synced TEXT, synced_by TEXT);
CREATE INDEX IF NOT EXISTS takeoff_items_file ON takeoff_items (file);
CREATE INDEX IF NOT EXISTS takeoff_items_grp ON takeoff_items (grp);
"""

METHODS = {"manual": "By hand", "auto area": "Auto area",
           "auto rooms": "Auto rooms", "trace length": "Trace",
           "auto count": "Auto count", "count by label": "Count by label",
           "carried": "Carried from older set"}


def _sheet_numbers(doc):
    from . import sheets
    out = {}
    try:
        for info in sheets.scan(doc):
            out[info["page"]] = info["number"] or ""
    except Exception:
        log.debug("sheet numbers", exc_info=True)
    return out


def _revision_at(revs, when):
    """The revision in force when a measurement was taken: the latest one
    recorded before it, else 'Original'."""
    label = "Original"
    for r in revs:
        if when and r.get("date", "") <= when:
            label = r["label"]
    return label


def trail(doc):
    """[{page, sheet, group, type, value, unit, author, taken, method,
    confidence, scale, status, revision, ref}]."""
    from . import revisions
    revs = revisions.read(doc)["revisions"]
    nums = _sheet_numbers(doc)
    rows = []
    for pno, page in enumerate(doc):
        for a in annotate.iter_annots(page) or []:
            subj = (a.info or {}).get("subject", "")
            if not subj.startswith(annotate.TAKEOFF + ":"):
                continue
            parts = (subj.split(":", 5) + [""] * 6)[:6]
            if parts[1] == annotate.CUTOUT:
                continue
            try:
                value = float(parts[2])
            except ValueError:
                continue
            au = annotate.audit_of(doc, a)
            info = a.info or {}
            taken = au.get("at") or _pdf_date(info.get("creationDate")) or ""
            rows.append({
                "page": pno, "sheet": nums.get(pno, ""), "group": parts[4],
                "type": parts[1], "value": value, "unit": parts[3],
                "author": au.get("by") or info.get("title", ""),
                "taken": taken, "method": au.get("method") or "unknown",
                "confidence": au.get("conf"),
                "scale": au.get("scale") or "",
                "status": annotate.status_of(doc, a),
                "revision": au.get("rev") or _revision_at(revs, taken),
                "ref": annotate.ref(a)})
    return rows


def _pdf_date(s):
    """D:20261014213000-04'00' -> 2026-10-14T21:30:00"""
    if not s or not s.startswith("D:") or len(s) < 16:
        return ""
    d = s[2:]
    try:
        return datetime.datetime.strptime(d[:14], "%Y%m%d%H%M%S").isoformat()
    except ValueError:
        return ""


def summary(rows):
    """{by method: count, by author: count, low confidence: count,
    to check: count}."""
    out = {"methods": {}, "authors": {}, "low_confidence": 0,
           "to_check": 0, "no_scale": 0}
    for r in rows:
        out["methods"][r["method"]] = out["methods"].get(r["method"], 0) + 1
        out["authors"][r["author"] or "?"] = \
            out["authors"].get(r["author"] or "?", 0) + 1
        if r["confidence"] is not None and r["confidence"] < 0.85:
            out["low_confidence"] += 1
        if r["status"] == annotate.REVISED:
            out["to_check"] += 1
        if r["method"] != "unknown" and not r["scale"] and \
                r["type"] != "count":
            out["no_scale"] += 1
    return out


def export_xlsx(rows, path):
    from . import acrobat
    data = [["Sheet", "Page", "Group", "Type", "Quantity", "Unit", "Taken by",
             "Taken", "How", "Confidence", "Scale", "Revision", "Status"]]
    for r in rows:
        data.append([r["sheet"], r["page"] + 1, r["group"], r["type"],
                     round(r["value"], 4), r["unit"], r["author"],
                     r["taken"].replace("T", " "),
                     METHODS.get(r["method"], r["method"]),
                     "" if r["confidence"] is None else r["confidence"],
                     r["scale"], r["revision"], r["status"]])
    acrobat.write_xlsx(path, [("Measurement audit", data)])
    return path


# ---- mirror in the shared database --------------------------------------------------

def _con(write=False):
    from . import pricedb
    return pricedb.connect(write=write)


def mirror(doc, job="", file=""):
    """Replace this file's rows in the shared takeoff table. Returns the
    number of measurements written."""
    from . import pricedb
    rows = trail(doc)
    file = os.path.abspath(file or doc.name or "")
    job = job or os.path.splitext(os.path.basename(file))[0]
    stamp = pricedb.now()
    who = pricedb.user()
    with _con(write=True) as con:
        con.executescript(DDL)
        con.execute("DELETE FROM takeoff_items WHERE file = ?", (file,))
        con.executemany(
            "INSERT INTO takeoff_items (job, file, page, sheet, grp, type, "
            "value, unit, author, taken, method, confidence, scale, status, "
            "revision, synced, synced_by) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,"
            "?,?,?,?)",
            [(job, file, r["page"], r["sheet"], r["group"], r["type"],
              r["value"], r["unit"], r["author"], r["taken"], r["method"],
              r["confidence"], r["scale"], r["status"], r["revision"], stamp,
              who) for r in rows])
    return len(rows)


def search(text="", job=None, unit=None, since=None, limit=2000):
    """Takeoff across every mirrored file: [{job, file, sheet, group, type,
    value, unit, author, taken, method, revision}]. `text` matches the
    group name (all words)."""
    sql = ("SELECT job, file, page, sheet, grp, type, value, unit, author, "
           "taken, method, revision, status FROM takeoff_items")
    where, args = [], []
    for w in (text or "").split():
        where.append("grp LIKE ?")
        args.append(f"%{w}%")
    if job:
        where.append("job = ?")
        args.append(job)
    if unit:
        where.append("unit = ?")
        args.append(unit)
    if since:
        where.append("taken >= ?")
        args.append(since)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY job, grp LIMIT ?"
    args.append(limit)
    with _con() as con:
        try:
            con.executescript(DDL)
        except Exception:
            pass                       # read-only copy
        try:
            cur = con.execute(sql, args)
        except Exception:
            return []
        cols = ["job", "file", "page", "sheet", "group", "type", "value",
                "unit", "author", "taken", "method", "revision", "status"]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def totals(rows):
    """{(group, unit): (quantity, files)} for search results."""
    out = {}
    for r in rows:
        k = (r["group"], r["unit"])
        q, f = out.get(k, (0.0, set()))
        f.add(r["file"])
        out[k] = (q + float(r["value"] or 0), f)
    return {k: (q, len(f)) for k, (q, f) in out.items()}
