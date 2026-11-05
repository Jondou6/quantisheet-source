"""The Excel update template (design 3.1): generate one per sub per
cycle, and read a returned one into neutral rows.

Sheets: "Update" (the sub's activities, editable columns unlocked, then
shaded read-only context rows from other trades), "New activities" (the
sub's own internal work, rolled up under one of their activities) and a
very hidden "_qs" sheet holding the issue data and an HMAC over it with
the project's template key. Sheet protection is not security; the HMAC
is what catches an edited id, base value, company or project."""
import datetime as _dt
import hashlib
import hmac
import json
import os
import zipfile

from ... import schedule
from .. import model
from ..values import Bad, base_of, date, num, text

UPDATE_COLS = ("No.", "Activity", "Owner", "Area", "Baseline start",
               "Baseline finish", "Planned start", "Planned finish",
               "Duration (workdays)", "Expected finish", "% complete",
               "Actual start", "Actual finish", "Note")
EDITABLE = ("Duration (workdays)", "Expected finish", "% complete",
            "Actual start", "Actual finish", "Note")
FIELD = {"Duration (workdays)": "duration",
         "Expected finish": "expected_finish", "% complete": "percent",
         "Actual start": "actual_start", "Actual finish": "actual_finish",
         "Note": "note"}
DATES = ("expected_finish", "actual_start", "actual_finish")
NEW_COLS = ("Activity name", "Duration (workdays)",
            "Inside master activity no.", "Note")
MAX_BYTES = 5 * 1024 * 1024
MAX_ROWS = 2000
KIND = "quantisheet-master-update"
CHUNK = 30000


def _col(name):
    return "ABCDEFGHIJKLMNOPQRSTUVWXYZ"[UPDATE_COLS.index(name)]


def _mac(key, body):
    return hmac.new(key, body.encode("utf-8"), hashlib.sha256).hexdigest()


def _dd(store, cycle):
    if cycle:
        return _dt.date.fromisoformat(str(cycle)[:10])
    return schedule.data_date(store)


def generate(store, company, path, cycle=None, now=None):
    """Write the template for `company` and record the issue. Returns
    the path."""
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Protection
    from openpyxl.worksheet.datavalidation import DataValidation
    dd = _dd(store, cycle)
    acts = store.list("activity")
    own_ids = set(model.slice_ids(store, company))
    if not own_ids:
        raise ValueError(f"No activities are owned by {company} (set "
                         "'Owning subcontractor' first).")
    by = {a["_id"]: a for a in acts}
    find = schedule.resolver(acts)
    ctx = set()
    for a in acts:
        ps = {find(ref) for ref, _t, _l in schedule.parse_preds(a)}
        ps.discard(None)
        if a["_id"] in own_ids:
            ctx |= ps - own_ids
        elif ps & own_ids:
            ctx.add(a["_id"])
    cpm = schedule.compute(store, dd)
    rows = {r["_id"]: r for r in cpm["rows"]}
    order = [a["_id"] for a in acts if a["_id"] in own_ids] + \
        [a["_id"] for a in acts if a["_id"] in ctx]
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Update"
    ws.append(list(UPDATE_COLS))
    for c in ws[1]:
        c.font = Font(bold=True)
    grey = PatternFill("solid", fgColor="DDDDDD")
    payload_rows = []
    for rid in order:
        a, r = by[rid], rows.get(rid, {})
        b = base_of(a)
        own = rid in own_ids
        vals = [a.get("_no"), a.get("name"), model.owner_of(a) or "GC",
                a.get("area") or "", date(a.get("baseline_start")) and
                _dt.date.fromisoformat(date(a.get("baseline_start"))),
                date(a.get("baseline_finish")) and
                _dt.date.fromisoformat(date(a.get("baseline_finish"))),
                r.get("es"), r.get("ef"), b["duration"], None,
                b["percent"],
                b["actual_start"] and
                _dt.date.fromisoformat(b["actual_start"]),
                b["actual_finish"] and
                _dt.date.fromisoformat(b["actual_finish"]), None]
        ws.append(vals)
        i = ws.max_row
        for k, c in enumerate(ws[i]):
            name = UPDATE_COLS[k]
            if isinstance(c.value, _dt.date):
                c.number_format = "yyyy-mm-dd"
            if name in ("Expected finish", "Actual start", "Actual finish"):
                c.number_format = "yyyy-mm-dd"
            if own and name in EDITABLE:
                c.protection = Protection(locked=False)
            elif not own:
                c.fill = grey
        payload_rows.append({"id": rid, "no": a.get("_no"),
                             "name": a.get("name"), "own": own, "base": b})
    ws.protection.sheet = True
    ws.freeze_panes = "C2"
    for k, w in enumerate((8, 34, 18, 14, 12, 12, 12, 12, 10, 12, 10, 12,
                           12, 30)):
        ws.column_dimensions["ABCDEFGHIJKLMN"[k]].width = w
    wn = wb.create_sheet("New activities")
    wn.append(list(NEW_COLS))
    for c in wn[1]:
        c.font = Font(bold=True)
    nos = [by[i].get("_no") for i in order if i in own_ids]
    dv = DataValidation(type="list", formula1='"' + ",".join(nos) + '"',
                        allow_blank=True)
    wn.add_data_validation(dv)
    dv.add("C2:C500")
    for k, w in enumerate((34, 12, 14, 30)):
        wn.column_dimensions["ABCD"[k]].width = w
    now = (now or _dt.datetime.now()).replace(microsecond=0).isoformat()
    cfg = model.config(store)
    payload = {"v": 1, "kind": KIND, "project": model.project_id(store),
               "project_name": store.name, "company": company,
               "cycle": dd.isoformat(), "rev": cfg["rev"],
               "issued_at": now, "rows": payload_rows}
    body = json.dumps(payload, sort_keys=True)
    q = wb.create_sheet("_qs")
    q["A1"] = "mac:" + _mac(model.template_key(store), body)
    for k in range(0, len(body), CHUNK):
        q.cell(row=2 + k // CHUNK, column=1, value=body[k:k + CHUNK])
    q.sheet_state = "veryHidden"
    q.protection.sheet = True
    tmp = path + ".tmp.xlsx"
    wb.save(tmp)
    os.replace(tmp, path)
    issued = list(cfg.get("issued") or [])
    issued.append({"company": company, "cycle": dd.isoformat(),
                   "rev": cfg["rev"], "at": now,
                   "file": os.path.basename(path)})
    model.set_config(store, issued=issued[-200:])
    return path


def _err(where, msg):
    return {"where": where, "text": msg}


def read(store, path):
    """{"format", "meta", "rows", "new", "errors", "warnings"}. Every
    problem is collected; nothing is written anywhere."""
    out = {"format": "xlsx", "meta": {}, "rows": [], "new": [],
           "errors": [], "warnings": []}
    E = out["errors"]
    name = os.path.basename(path)
    if os.path.splitext(path)[1].lower() != ".xlsx":
        E.append(_err(name, "Only .xlsx workbooks are read (no .xlsm "
                      "macros or old .xls files)."))
        return out
    try:
        size = os.path.getsize(path)
    except OSError as ex:
        E.append(_err(name, f"Can't read the file: {ex}"))
        return out
    if size > MAX_BYTES:
        E.append(_err(name, f"The file is too big ({size:,} bytes; the "
                      f"limit is {MAX_BYTES:,})."))
        return out
    if not zipfile.is_zipfile(path):
        E.append(_err(name, "This isn't a readable Excel workbook."))
        return out
    import openpyxl
    try:
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    except Exception as ex:                          # noqa: BLE001
        E.append(_err(name, f"Excel couldn't open it: {ex}"))
        return out
    try:
        _read(store, wb, out, name)
    finally:
        wb.close()
    return out


def _read(store, wb, out, name):
    E = out["errors"]
    for sh in ("Update", "New activities", "_qs"):
        if sh not in wb.sheetnames:
            E.append(_err(name, f"The '{sh}' sheet is missing - this isn't "
                          "a QuantiSheet update template (or it was "
                          "changed)."))
    if E:
        return
    q = [r[0] for r in wb["_qs"].iter_rows(min_col=1, max_col=1,
                                           values_only=True)]
    mac = str(q[0] or "")[4:] if q else ""
    body = "".join(str(x or "") for x in q[1:])
    good = hmac.compare_digest(_mac(model.template_key(store), body), mac)
    try:
        payload = json.loads(body) if good else None
    except ValueError:
        payload = None
    if not good or not isinstance(payload, dict) or \
            payload.get("kind") != KIND:
        E.append(_err("_qs", "The template's hidden data was changed, or "
                      "the template is from another project - send the "
                      "sub a fresh template."))
        return
    if payload.get("project") != model.project_id(store):
        E.append(_err("_qs", "This template belongs to another project."))
        return
    out["meta"] = {k: payload.get(k) for k in ("project", "project_name",
                                               "company", "cycle", "rev",
                                               "issued_at")}
    issued = {r["no"]: r for r in payload.get("rows") or []}
    ws = wb["Update"]
    it = ws.iter_rows(values_only=True)
    head = tuple(next(it, ()) or ())
    if tuple(str(h or "") for h in head[:len(UPDATE_COLS)]) != UPDATE_COLS:
        E.append(_err("Update!1", "The Update sheet's columns were "
                      "changed - use the template as sent."))
        return
    seen = set()
    for i, vals in enumerate(it, start=2):
        if i > MAX_ROWS:
            E.append(_err("Update", f"More than {MAX_ROWS} rows."))
            break
        vals = list(vals) + [None] * len(UPDATE_COLS)
        if all(v is None or str(v).strip() == "" for v in
               vals[:len(UPDATE_COLS)]):
            continue
        no = text(vals[0])
        if no not in issued:
            E.append(_err(f"Update!A{i}", f"Activity no. '{no}' isn't in "
                          "this template - put new work on the New "
                          "activities sheet."))
            continue
        if no in seen:
            E.append(_err(f"Update!A{i}", f"Activity no. {no} is listed "
                          "twice."))
            continue
        seen.add(no)
        iss = issued[no]
        values, where = {}, {}
        for col in EDITABLE:
            f = FIELD[col]
            raw = vals[UPDATE_COLS.index(col)]
            where[f] = f"Update!{_col(col)}{i}"
            try:
                if f in DATES:
                    values[f] = date(raw)
                elif f == "note":
                    values[f] = text(raw)
                else:
                    values[f] = num(raw)
            except Bad as ex:
                values[f] = None
                E.append(_err(where[f], f"{no} {col}: {ex}."))
        out["rows"].append({"key": iss["id"], "no": no,
                            "name": iss.get("name"), "ctx": not iss["own"],
                            "values": values, "base": dict(iss["base"]),
                            "where": where, "row": i})
    wn = wb["New activities"]
    it = wn.iter_rows(values_only=True)
    head = tuple(next(it, ()) or ())
    if tuple(str(h or "") for h in head[:len(NEW_COLS)]) != NEW_COLS:
        E.append(_err("New activities!1", "The New activities sheet's "
                      "columns were changed."))
        return
    for i, vals in enumerate(it, start=2):
        if i > MAX_ROWS:
            E.append(_err("New activities", f"More than {MAX_ROWS} rows."))
            break
        vals = list(vals) + [None] * 4
        if all(v is None or str(v).strip() == "" for v in vals[:4]):
            continue
        item = {"name": text(vals[0], 200), "duration": None,
                "parent_no": text(vals[2]), "note": text(vals[3]),
                "where": f"New activities!A{i}", "row": i}
        try:
            item["duration"] = num(vals[1])
        except Bad as ex:
            E.append(_err(f"New activities!B{i}", f"{ex}."))
        out["new"].append(item)
