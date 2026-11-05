"""A schedule printed to PDF -> neutral rows (Jon's examples: Primavera P6
layouts and MS Project Gantt printouts).

Subs often send their update as a PDF printout only. Read-only, our own
code: the activity table is read from the page's words by its column
headings, never from the Gantt bars.

P6 layout   Activity ID | Activity Name | Original Duration | Remaining
            Duration | Start | Finish  ("16-Jun-25 A" = actual, "*" =
            constraint; "Data Date: 09-Dec-25" in the footer)
MSP layout  ID | Task Name | Duration ("10 days") | Start | Finish
            ("Mon 6/2/25"); no actual dates or status date in a printout

Rows without an activity ID (P6 WBS bands) and MS Project summary tasks
(the next row is indented further) are skipped. Percent complete isn't
printed: it is worked out from the original and remaining durations and
said so in a warning. Matching: the activity ID as a task code / activity
number; unmatched rows map once ("p6:<ID>" / "msp:id<ID>")."""
import datetime as _dt
import os
import re

from . import common

_MONTHS = {m: i for i, m in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct",
     "nov", "dec"), 1)}
_P6_DATE = re.compile(r"^(\d{1,2})-([A-Za-z]{3})-(\d{2,4})(\*)?$")
_MSP_DATE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{2,4})$")
_DAYNAME = re.compile(r"^(Mon|Tue|Wed|Thu|Fri|Sat|Sun)$", re.I)
_DATA_DATE = re.compile(r"Data\s+Date:?\s*(\d{1,2}-[A-Za-z]{3}-\d{2,4})",
                        re.I)
_TITLE_DATE = re.compile(r"\b(\d{1,2})([A-Za-z]{3})(\d{2})\s+Update\b")
_ID = re.compile(r"^[A-Za-z]{0,4}\d{1,6}[A-Za-z]{0,2}$")


def _year(y):
    y = int(y)
    return y + 2000 if y < 100 else y


def p6_date(text):
    m = _P6_DATE.match(text or "")
    if not m or m.group(2).lower() not in _MONTHS:
        return None
    try:
        return _dt.date(_year(m.group(3)), _MONTHS[m.group(2).lower()],
                        int(m.group(1)))
    except ValueError:
        return None


def msp_date(text):
    m = _MSP_DATE.match(text or "")
    if not m:
        return None
    try:
        return _dt.date(_year(m.group(3)), int(m.group(1)), int(m.group(2)))
    except ValueError:
        return None


def _num(text):
    t = str(text or "").replace(",", "").strip()
    t = re.sub(r"\s*(days?|d|wks?|w)\??$", "", t, flags=re.I)  # "1 day?"
    t = t.rstrip("?")
    try:
        return float(t)
    except ValueError:
        return None


def _lines(words):
    """Words grouped into printed lines (same baseline within 2.5 pt),
    each sorted left to right: [(y, [word])]."""
    rows = []
    for w in sorted(words, key=lambda w: ((w[1] + w[3]) / 2, w[0])):
        y = (w[1] + w[3]) / 2
        if rows and abs(rows[-1][0] - y) <= 2.5:
            rows[-1][1].append(w)
        else:
            rows.append([y, [w]])
    return [(y, sorted(ws, key=lambda w: w[0])) for y, ws in rows]


def _header(lines):
    """(layout, {column: x0}) from the heading line, or (None, {})."""
    for _y, ws in lines:
        txt = [str(w[4]) for w in ws]
        low = [t.lower() for t in txt]
        x = {}
        for i, t in enumerate(low):
            nxt = low[i + 1] if i + 1 < len(low) else ""
            if t == "activity" and nxt == "id":
                x["id"] = ws[i][0]
            elif t == "activity" and nxt == "name":
                x["name"] = ws[i][0]
            elif t == "task" and nxt == "name":
                x["name"] = ws[i][0]
            elif t == "id" and "id" not in x and (i == 0 or
                                                  low[i - 1] != "activity"):
                x["id"] = ws[i][0]
            elif t == "original":
                x["orig"] = ws[i][0]
            elif t == "remaining":
                x["rem"] = ws[i][0]
            elif t == "duration" and "orig" not in x and \
                    (i == 0 or low[i - 1] not in ("original", "remaining")):
                x["orig"] = ws[i][0]
            elif t == "start" and "start" not in x:
                x["start"] = ws[i][0]
            elif t == "finish" and "finish" not in x:
                x["finish"] = ws[i][0]
        if {"id", "name", "orig", "start", "finish"} <= set(x):
            return ("p6" if "rem" in x else "msp"), x, _y
    return None, {}, None


def _col(x0, cols):
    """The column a word starting at x0 falls in (the last heading at or
    left of it, 6 pt slack)."""
    best = None
    for name, cx in sorted(cols.items(), key=lambda kv: kv[1]):
        if x0 >= cx - 6:
            best = name
    return best


def read_pages(pages_words):
    """[[word]] per page -> {"layout", "rows": [{"id", "name", "orig",
    "rem", "start", "start_a", "finish", "finish_a", "indent", "page"}],
    "data_date", "title"}. Pure (tests feed it words)."""
    out = {"layout": None, "rows": [], "data_date": None, "title": ""}
    for pno, words in enumerate(pages_words, 1):
        lines = _lines(words)
        for _y, ws in lines:
            m = _DATA_DATE.search(" ".join(str(w[4]) for w in ws))
            if m and out["data_date"] is None:
                out["data_date"] = p6_date(m.group(1))
        layout, cols, hy = _header(lines)
        if layout is None:
            continue
        out["layout"] = out["layout"] or layout
        # the table ends at the Finish column (a date is ~60 pt wide);
        # to the right are the Gantt bars and their labels
        right = cols["finish"] + 70
        last = None
        for y, ws in lines:
            if y <= hy + 4:
                continue
            ws = [w for w in ws if w[0] < right]
            if not ws:
                continue
            cells = {}
            for w in ws:
                cells.setdefault(_col(w[0], cols), []).append(w)
            ids = [str(w[4]) for w in cells.get("id", [])]
            name_ws = cells.get("name", [])
            name = " ".join(str(w[4]) for w in name_ws).strip()
            dates = {}
            for c in ("start", "finish"):
                toks = [str(w[4]) for w in cells.get(c, [])]
                d, act = None, False
                for t in toks:
                    d = d or (p6_date(t) if layout == "p6" else msp_date(t))
                    if t == "A":
                        act = True
                dates[c] = (d, act)
            if not ids and not dates["start"][0] and name and last and \
                    not cells.get("orig"):
                last["name"] = (last["name"] + " " + name).strip()
                continue                         # a wrapped activity name
            if not dates["start"][0] or not dates["finish"][0]:
                last = None
                continue                         # a band, legend or footer
            if not out["title"] and not ids:
                out["title"] = name
            orig = " ".join(str(w[4]) for w in cells.get("orig", []))
            rem = " ".join(str(w[4]) for w in cells.get("rem", []))
            # an activity has its ID alone in the ID column; a P6 WBS
            # band ("00100 - Owner Supplied Materials") fills it with text
            rid = ids[0] if len(ids) == 1 and _ID.match(ids[0]) else None
            row = {"id": rid, "name": name, "orig": _num(orig),
                   "rem": _num(rem),
                   "start": dates["start"][0], "start_a": dates["start"][1],
                   "finish": dates["finish"][0],
                   "finish_a": dates["finish"][1],
                   "indent": name_ws[0][0] if name_ws else None,
                   "page": pno}
            out["rows"].append(row)
            last = row
    if out["data_date"] is None:
        m = _TITLE_DATE.search(" ".join(r["name"] for r in out["rows"][:3]))
        if m and m.group(2).lower() in _MONTHS:
            try:
                out["data_date"] = _dt.date(2000 + int(m.group(3)),
                                            _MONTHS[m.group(2).lower()],
                                            int(m.group(1)))
            except ValueError:
                pass
    return out


def activities(parsed):
    """The rows that are activities: an ID, and (MS Project) not a summary
    task - the row after it is indented further."""
    rows = parsed["rows"]
    keep = []
    for i, r in enumerate(rows):
        if not r["id"]:
            continue                             # P6 WBS band
        if parsed["layout"] == "msp" and i + 1 < len(rows):
            nx = rows[i + 1]
            if r["indent"] is not None and nx["indent"] is not None and \
                    nx["indent"] > r["indent"] + 3 and nx["page"] == r["page"]:
                continue                         # a summary task
        keep.append(r)
    return keep


def _words(path):
    import fitz
    doc = fitz.open(path)
    try:
        if doc.page_count > 200:
            raise ValueError("more than 200 pages")
        out = []
        for p in doc:
            m = p.rotation_matrix          # landscape sheets stored turned
            ws = []
            for w in p.get_text("words"):
                r = fitz.Rect(w[:4]) * m
                ws.append((r.x0, r.y0, r.x1, r.y1) + tuple(w[4:]))
            out.append(ws)
        return out
    finally:
        doc.close()


def read(store, path, company, now=None):
    out = common.new_out("pdf")
    name = os.path.basename(path)
    data = common.load(path, out)
    if data is None:
        return out
    if not data[:5] == b"%PDF-":
        out["errors"].append(common.err(name, "This isn't a PDF file."))
        return out
    try:
        parsed = read_pages(_words(path))
    except Exception as ex:                               # noqa: BLE001
        out["errors"].append(common.err(name, f"The PDF can't be read: "
                                        f"{ex}"))
        return out
    if parsed["layout"] is None:
        out["errors"].append(common.err(name, "No schedule table was found "
                                        "in this PDF (no Activity ID / Task "
                                        "Name, Start and Finish headings). "
                                        "A scanned printout can't be read - "
                                        "ask for an MS Project XML, P6 XER or "
                                        "the update template."))
        return out
    acts = activities(parsed)
    if not acts:
        out["errors"].append(common.err(name, "The schedule table has no "
                                        "activity rows with an ID."))
        return out
    if len(acts) > common.MAX_ROWS:
        out["errors"].append(common.err(name, f"More than {common.MAX_ROWS} "
                                        "activities."))
        return out
    status = parsed["data_date"].isoformat() if parsed["data_date"] else ""
    dd = common.data_date(store, status, out, now)
    pre = "p6:" if parsed["layout"] == "p6" else "msp:id"
    est = 0
    items = []
    for k, r in enumerate(acts, 1):
        where = f"page {r['page']}, activity {r['id']} '{r['name'][:50]}'"
        v = {"duration": r["orig"], "percent": None,
             "actual_start": r["start"].isoformat() if r["start_a"] else None,
             "actual_finish": (r["finish"].isoformat() if r["finish_a"]
                               else None)}
        if v["actual_finish"]:
            v["percent"] = 100
        elif v["actual_start"] and r["orig"] and r["rem"] is not None:
            v["percent"] = max(0, min(99, round(
                (r["orig"] - r["rem"]) / r["orig"] * 100)))
            est += 1
        elif parsed["layout"] == "p6" and r["orig"] is not None:
            v["percent"] = 0
        items.append({"ref": f"{pre}{r['id']}",
                      "ids": [("task code", r["id"])], "ext": None,
                      "name": r["name"], "where": where, "values": v,
                      "row": k, "links": []})
    if est:
        out["warnings"].append(common.err(
            "file", f"A PDF printout has no % complete: for {est} started "
            "activit(y/ies) it is worked out from the original and "
            "remaining durations - check it."))
    if parsed["layout"] == "msp":
        out["warnings"].append(common.err(
            "file", "An MS Project printout shows no actual dates or % "
            "complete; only durations and dates were read."))
    out["warnings"].append(common.err(
        "file", "Read from a PDF printout: logic links aren't printed, so "
        "they aren't checked."))
    out["meta"] = {"company": company, "cycle": dd.isoformat(),
                   "rev": "unknown", "layout": parsed["layout"],
                   "pages": max(r["page"] for r in acts)}
    return common.build(store, company, items, out, "pdf")
