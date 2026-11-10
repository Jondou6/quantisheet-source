"""Phone work ticket (QuantiSheet 1.2, #4): a fillable PDF a tech fills
in a phone PDF app with no signal, read back into the work order.

- Each ticket carries its own id (QS-xxxxxxxx) printed on the page, in a
  read-only field and in the PDF's keywords, so a ticket is matched to
  its work order even when the phone app drops the fields.
- Read back from the fields when they are there (Adobe Acrobat Reader
  keeps them). A built-in viewer may flatten the form on save: then each
  value is read from the page text inside that field's own box, and
  every box that can't be read (check boxes, empty boxes) is listed for
  the office to type in. Nothing is guessed.
- The same ticket returned twice: the same values add nothing; different
  values are a conflict the office decides (keep the first, or replace
  it - the first return's time and parts come out, the new ones go in).
- Hours and parts go in as they would from the office; parts from a
  ticket have no price and are marked for the office to price.
"""
import datetime as dt
import os
import re
import secrets

from . import files, workorder

KEY = "qs-ticket"
ROWS_TIME = 3
ROWS_PARTS = 6
TOKEN_RE = re.compile(r"QS-([A-Z0-9]{8})")


class TicketError(ValueError):
    pass


class TicketConflict(TicketError):
    def __init__(self, diff):
        self.diff = diff
        super().__init__("This ticket came back before with different "
                         "entries: " + "; ".join(
                             f"{k}: {a!r} then {b!r}" for k, (a, b) in
                             sorted(diff.items())))


def _layout():
    """(name, label, rect, kind) in page points - the same every time."""
    out = [("t_date", "Date of visit", (36, 150, 180, 166), "text")]
    y = 186
    for i in range(1, ROWS_TIME + 1):
        out += [(f"t_tech{i}", f"Technician {i}", (36, y, 300, y + 16),
                 "text"),
                (f"t_hours{i}", "Hours", (320, y, 400, y + 16), "text")]
        y += 26
    y += 18
    for i in range(1, ROWS_PARTS + 1):
        out += [(f"t_qty{i}", f"Qty {i}", (36, y, 90, y + 16), "text"),
                (f"t_part{i}", f"Part {i}", (100, y, 560, y + 16), "text")]
        y += 24
    out += [("t_noparts", "No parts used", (36, y + 4, 48, y + 16), "check")]
    y += 34
    out += [("t_work", "Work done", (36, y, 560, y + 90), "multi")]
    y += 110
    out += [("t_signed", "Customer name (signed)", (36, y, 300, y + 16),
             "text"),
            ("t_complete", "Work complete", (320, y + 2, 332, y + 14),
             "check")]
    return out


def make(store, wo_id, path, comp=None, now=None):
    """Write the ticket PDF for one open work order; remember it."""
    from .pdfdoc import Sheet
    wo = workorder.get(store, wo_id)
    if wo["status"] != "open":
        raise TicketError("Only an open work order gets a phone ticket.")
    token = "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789")
                    for _ in range(8))
    sheet = Sheet("Work Ticket", comp, subtitle=wo["number"])
    pg = sheet.page
    sheet.text(36, 92, f"Ticket QS-{token}   {wo['number']}   "
                       f"{wo['customer']}   {wo['site']}", 9, True)
    sheet.text(36, 106, f"Unit: {wo.get('unit') or '-'}    Complaint: "
                        f"{wo['complaint'][:90]}", 8)
    sheet.text(36, 120, "Fill in on the phone, save, and send the file back "
                        "to the office. Hours as numbers (1.5).", 7.5)
    sheet.text_field("t_ticket", (440, 80, 576, 94), f"QS-{token}",
                     readonly=True)
    rects = {}
    for name, label, rect, kind in _layout():
        sheet.label(rect[0], rect[1] - 2, label)
        if kind == "check":
            sheet.checkbox(name, rect)
        else:
            value = dt.date.today().isoformat() if name == "t_date" else ""
            if name == "t_tech1":
                value = wo.get("tech") or ""
            sheet.text_field(name, rect, value, multiline=kind == "multi")
        rects[name] = list(rect)
    sheet.doc.set_metadata({"title": f"Work ticket {wo['number']}",
                            "keywords": f"{KEY}:{wo_id}:{token}"})
    out = sheet.save(path)
    wo.setdefault("tickets", []).append({
        "token": token, "issued": (now or dt.datetime.now()).isoformat(
            timespec="seconds"), "file": os.path.basename(path),
        "rects": rects, "returns": []})
    return {"token": token, "path": out}


def _find(store, token):
    for wo in store.get("orders", []):
        for t in wo.get("tickets", []):
            if t["token"] == token:
                return wo, t
    return None, None


def read(store, path):
    """What a returned ticket says. {"token", "wo_id", "values", "how":
    "fields" | "flattened", "unread": [field labels], "note"}."""
    import fitz
    try:
        doc = fitz.open(path)
    except Exception as e:                                # noqa: BLE001
        raise TicketError(f"Can't open {os.path.basename(path)}: {e}") \
            from e
    with doc:
        token = None
        kw = (doc.metadata or {}).get("keywords") or ""
        if kw.startswith(KEY + ":"):
            token = kw.split(":")[-1]
        page = doc[0]
        widgets = {w.field_name: w for w in page.widgets() or []}
        if not token and "t_ticket" in widgets:
            m = TOKEN_RE.search(widgets["t_ticket"].field_value or "")
            token = m.group(1) if m else None
        if not token:
            m = TOKEN_RE.search(page.get_text())
            token = m.group(1) if m else None
        if not token:
            raise TicketError("This isn't a QuantiSheet work ticket (no "
                              "ticket id on it).")
        wo, t = _find(store, token)
        if wo is None:
            raise TicketError(f"Ticket QS-{token} isn't from this office's "
                              "work orders.")
        labels = {n: lab for n, lab, _r, _k in _layout()}
        kinds = {n: k for n, _l, _r, k in _layout()}
        values, unread = {}, []
        how = "fields" if any(n in widgets for n in t["rects"]) else \
            "flattened"
        words = page.get_text("words") if how == "flattened" else []
        for name, rect in t["rects"].items():
            if how == "fields":
                w = widgets.get(name)
                if w is None:
                    unread.append(labels[name])
                    continue
                v = w.field_value
                if kinds[name] == "check":
                    v = v not in (None, "", "Off", False)
                values[name] = v if isinstance(v, bool) else \
                    str(v or "").strip()
            else:
                if kinds[name] == "check":
                    unread.append(labels[name])        # not readable as text
                    continue
                r = fitz.Rect(rect)
                # words whose middle is inside the box (a label just above
                # a box can touch it), in reading order
                ws = [w for w in words
                      if r.contains(fitz.Point((w[0] + w[2]) / 2,
                                               (w[1] + w[3]) / 2))]
                ws.sort(key=lambda w: (w[5], w[6], w[7]))
                v = " ".join(w[4] for w in ws).strip()
                if v:
                    values[name] = v
                elif name not in ("t_tech2", "t_tech3", "t_hours2",
                                  "t_hours3") and not name.startswith(
                                      ("t_qty", "t_part")):
                    unread.append(labels[name])
        # widget and page objects must go before the document closes
        # (PyMuPDF crashes cleaning up a widget of a closed document)
        w = None
        widgets.clear()
        del page
    note = ("Read from the fields." if how == "fields" else
            "The phone app flattened the form: values were read from the "
            "page inside each box - check them, and fill in: " +
            (", ".join(unread) or "nothing"))
    return {"token": token, "wo_id": wo["id"], "number": wo["number"],
            "values": values, "how": how, "unread": unread, "note": note}


def _entries(values):
    """(time rows, part rows) from the values, checked."""
    times, parts = [], []
    for i in range(1, ROWS_TIME + 1):
        tech = (values.get(f"t_tech{i}") or "").strip()
        hrs = (values.get(f"t_hours{i}") or "").strip()
        if not tech and not hrs:
            continue
        if not tech or not hrs:
            raise TicketError(f"Time row {i}: a technician and hours are "
                              "both needed.")
        times.append((tech, hrs))
    for i in range(1, ROWS_PARTS + 1):
        q = (values.get(f"t_qty{i}") or "").strip()
        d = (values.get(f"t_part{i}") or "").strip()
        if not q and not d:
            continue
        if not d:
            raise TicketError(f"Part row {i}: name the part.")
        parts.append((q or "1", d))
    return times, parts


def apply(store, ret, replace=False, now=None):
    """Put a read ticket into its work order. Returns what was added."""
    wo = workorder.get(store, ret["wo_id"])
    t = next(x for x in wo.get("tickets", []) if x["token"] == ret["token"])
    vals = ret["values"]
    done = [r for r in t["returns"] if r.get("applied")]
    if done:
        prev = done[-1]
        diff = {k: (prev["values"].get(k), vals.get(k))
                for k in set(prev["values"]) | set(vals)
                if prev["values"].get(k) != vals.get(k)}
        if not diff:
            return {"added_time": [], "added_parts": [], "same": True}
        if not replace:
            raise TicketConflict(diff)
    if wo["status"] != "open":
        raise TicketError(f"{wo['number']} is closed - reopen it to take "
                          "the ticket.")
    times, parts = _entries(vals)
    when = vals.get("t_date") or dt.date.today().isoformat()
    if done and replace:                       # the first return comes out
        prev = done[-1]
        wo["time"] = [x for x in wo["time"]
                      if x["id"] not in prev["time_ids"]]
        wo["parts"] = [x for x in wo["parts"]
                       if x["id"] not in prev["part_ids"]]
        prev["applied"] = False
        prev["replaced_at"] = (now or dt.datetime.now()).isoformat(
            timespec="seconds")
    tids, pids = [], []
    try:
        for tech, hrs in times:
            tids.append(workorder.add_time(store, wo["id"], tech, hrs,
                                           when=when, note="from ticket")
                        ["id"])
        for q, d in parts:
            line = workorder.add_part(store, wo["id"], d, q)
            line["from_ticket"] = True
            line["price_needed"] = True
            pids.append(line["id"])
    except workorder.WorkOrderError as e:
        wo["time"] = [x for x in wo["time"] if x["id"] not in tids]
        wo["parts"] = [x for x in wo["parts"] if x["id"] not in pids]
        raise TicketError(str(e)) from e
    if vals.get("t_noparts") is True and not wo["parts"]:
        wo["parts_recorded"] = True
    work = (vals.get("t_work") or "").strip()
    if work:
        wo["notes"] = (wo.get("notes", "") + "\n" + work).strip() \
            if work not in (wo.get("notes") or "") else wo["notes"]
    if vals.get("t_signed"):
        wo["signed_by"] = files.txt(vals["t_signed"], 120)
    t["returns"].append({"at": (now or dt.datetime.now()).isoformat(
        timespec="seconds"), "how": ret["how"], "values": vals,
        "unread": ret["unread"], "applied": True, "time_ids": tids,
        "part_ids": pids})
    return {"added_time": tids, "added_parts": pids, "same": False}
