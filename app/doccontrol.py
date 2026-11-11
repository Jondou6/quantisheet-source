"""Document control: drawing register, transmittals and addenda, saved
inside the job PDF.

* Drawing register: every sheet (read from the title blocks), its
  discipline, page and revision history (rev, date, description).
* Transmittals (TR-001...): what was sent, to whom, why and how, with
  acknowledgement of receipt.
* Addenda (ADD-001...): issued to bidders, with the sheets they change
  and who has acknowledged them (a bid without an acknowledged addendum
  can be thrown out).

(Built on the Venice AI draft.)
"""
import datetime as _dt
import json
import logging
import re

from . import forms, settings
from . import embfiles
from .dmoney import c2 as _c2

log = logging.getLogger(__name__)

FILE = "quantisheet_doccontrol.json"
PURPOSES = ("For review", "For approval", "For record", "For construction",
            "For pricing", "For permit", "As built", "As requested")
METHODS = ("Email", "Project portal", "Hand delivery", "Courier", "Mail",
           "FTP / file share")
# US National CAD Standard discipline letters, in set order
DISCIPLINES = [("G", "General"), ("H", "Hazardous Materials"),
               ("V", "Survey / Mapping"), ("B", "Geotechnical"),
               ("C", "Civil"), ("L", "Landscape"), ("S", "Structural"),
               ("A", "Architectural"), ("I", "Interiors"),
               ("Q", "Equipment"), ("F", "Fire Protection"),
               ("P", "Plumbing"), ("D", "Process"), ("M", "Mechanical"),
               ("E", "Electrical"), ("W", "Distributed Energy"),
               ("T", "Telecommunications"), ("R", "Resource"),
               ("X", "Other Disciplines"), ("Z", "Contractor / Shop "
                                                 "Drawings"),
               ("O", "Operations")]
_DISC = dict(DISCIPLINES)
_ORDER = {k: i for i, (k, _) in enumerate(DISCIPLINES)}


class DocControlError(ValueError):
    pass


def _today():
    return _dt.date.today().isoformat()


def _who():
    try:
        return settings.author() or ""
    except Exception:
        return ""


def blank():
    return {"sheets": {}, "transmittals": [], "addenda": [],
            "counter": {"TR": 0, "ADD": 0}}


def read(doc):
    data = blank()
    try:
        if FILE in doc.embfile_names():
            saved = json.loads(doc.embfile_get(FILE).decode("utf-8"))
            if isinstance(saved, dict):
                for k, v in saved.items():
                    if k == "counter":
                        data["counter"].update(v or {})
                    else:
                        data[k] = v
    except Exception:
        log.warning("could not read document control data", exc_info=True)
    return data


def write(doc, data):
    raw = json.dumps(data).encode("utf-8")
    embfiles.put(doc, FILE, raw, "QuantiSheet document control")


def _next(data, prefix):
    data["counter"][prefix] = int(data["counter"].get(prefix, 0)) + 1
    return f"{prefix}-{data['counter'][prefix]:03d}"


# ---- drawing register --------------------------------------------------------

def discipline_of(number):
    """'Architectural' for 'A-101', 'Fire Protection' for 'FP-1'."""
    m = re.match(r"^([A-Z]+)", str(number or "").upper())
    if not m:
        return ""
    letters = m.group(1)
    if letters in ("FP", "FA"):
        return "Fire Protection"
    return _DISC.get(letters[0], "")


def _key(number):
    n = str(number).upper()
    m = re.match(r"^([A-Z]+)", n)
    first = m.group(1)[0] if m else "~"
    parts = [int(x) if x.isdigit() else x for x in re.findall(r"\d+|\D+",
                                                             n)]
    return (_ORDER.get(first, 99), [(0, p) if isinstance(p, int) else
                                    (1, p) for p in parts])


def scan_register(doc):
    """Read each page's sheet number and title into the register. Titles
    you've typed are kept. Returns (found, pages without a number)."""
    from . import sheets
    data = read(doc)
    reg = data["sheets"]
    for s in reg.values():
        s["page"] = None
    found, missing = 0, []
    for info in sheets.scan(doc):
        num = (info["number"] or "").upper()
        if not num:
            missing.append(info["page"])
            continue
        found += 1
        s = reg.setdefault(num, {"title": "", "discipline": "",
                                 "revs": [], "manual_title": False})
        s["page"] = info["page"]
        if not s.get("manual_title"):
            s["title"] = info["title"] or s.get("title", "")
        if not s.get("discipline"):
            s["discipline"] = discipline_of(num)
    write(doc, data)
    return found, missing


def set_sheet(doc, number, title=None, discipline=None, page=None):
    data = read(doc)
    num = str(number).strip().upper()
    if not num:
        raise DocControlError("A sheet needs a number.")
    s = data["sheets"].setdefault(num, {"title": "", "discipline":
                                        discipline_of(num), "revs": [],
                                        "page": None, "manual_title": False})
    if title is not None:
        s["title"] = str(title)
        s["manual_title"] = True
    if discipline is not None:
        s["discipline"] = str(discipline)
    if page is not None:
        s["page"] = int(page)
    write(doc, data)
    return s


def remove_sheet(doc, number):
    data = read(doc)
    data["sheets"].pop(str(number).upper(), None)
    write(doc, data)


def add_revision(doc, numbers, rev, date=None, desc=""):
    """Record revision `rev` on one sheet or a list of sheets."""
    if isinstance(numbers, str):
        numbers = [numbers]
    if not str(rev).strip():
        raise DocControlError("Give the revision a number or letter.")
    data = read(doc)
    for n in numbers:
        num = str(n).strip().upper()
        if num not in data["sheets"]:
            raise DocControlError(f"{num} isn't in the register.")
        data["sheets"][num]["revs"].append(
            {"rev": str(rev).strip(), "date": date or _today(),
             "desc": desc})
    write(doc, data)


def register(doc, data=None):
    """Sheets in set order: [{number, title, discipline, page, rev,
    rev_date, rev_desc, revs}]."""
    data = data or read(doc)
    rows = []
    for num in sorted(data["sheets"], key=_key):
        s = data["sheets"][num]
        last = s["revs"][-1] if s.get("revs") else {}
        rows.append({"number": num, "title": s.get("title", ""),
                     "discipline": s.get("discipline", ""),
                     "page": s.get("page"), "rev": last.get("rev", ""),
                     "rev_date": last.get("date", ""),
                     "rev_desc": last.get("desc", ""),
                     "revs": list(s.get("revs") or [])})
    return rows


def register_pdf(doc, path, project=""):
    rows = register(doc)
    f = forms.Form("Drawing Register", f"{project}   {len(rows)} sheets"
                   .strip(), landscape=True)
    disc = None
    table = []
    for r in rows:
        if r["discipline"] != disc:
            disc = r["discipline"]
        table.append([r["number"], r["title"], r["discipline"],
                      "" if r["page"] is None else r["page"] + 1, r["rev"],
                      r["rev_date"], r["rev_desc"]])
    f.table(["Sheet", "Title", "Discipline", "Page", "Rev", "Rev date",
             "Description"], table, [1, 4, 1.6, 0.6, 0.6, 1, 3])
    return f.save(path)


def register_xlsx(doc, path):
    from . import acrobat
    rows = [["Sheet", "Title", "Discipline", "Page", "Current rev",
             "Rev date", "Description", "All revisions"]]
    for r in register(doc):
        rows.append([r["number"], r["title"], r["discipline"],
                     "" if r["page"] is None else r["page"] + 1, r["rev"],
                     r["rev_date"], r["rev_desc"],
                     "; ".join(f"{x['rev']} {x['date']}" for x in r["revs"])])
    acrobat.write_xlsx(path, [("Drawing Register", rows)])
    return path


# ---- transmittals -------------------------------------------------------------

def items_for_sheets(doc, numbers):
    """Transmittal lines for sheets in the register, at their current rev."""
    reg = {r["number"]: r for r in register(doc)}
    out = []
    for n in numbers:
        r = reg.get(str(n).upper())
        if r:
            out.append({"doc": r["number"], "desc": r["title"],
                        "rev": r["rev"], "date": r["rev_date"],
                        "copies": 1})
    return out


def new_transmittal(doc, to, items, purpose="For review", method="Email",
                    due="", cc="", notes="", sender="", date=None):
    if not str(to).strip():
        raise DocControlError("Who is the transmittal to?")
    items = [dict(i) for i in items if str(i.get("doc") or
                                             i.get("desc") or "").strip()]
    if not items:
        raise DocControlError("List at least one item being sent.")
    data = read(doc)
    tid = _next(data, "TR")
    data["transmittals"].append({
        "id": tid, "to": str(to).strip(), "cc": cc, "purpose": purpose,
        "method": method, "due": due or "", "notes": notes,
        "from": sender or _who(), "date": date or _today(),
        "items": items, "acks": []})
    write(doc, data)
    return tid


def transmittals(doc):
    return read(doc)["transmittals"]


def _tr(data, tid):
    for t in data["transmittals"]:
        if t["id"] == tid:
            return t
    raise KeyError(tid)


def acknowledge(doc, tid, who, date=None, note=""):
    data = read(doc)
    t = _tr(data, tid)
    t["acks"].append({"who": str(who).strip() or t["to"],
                      "date": date or _today(), "note": note})
    write(doc, data)
    return t


def awaiting(doc, today=None):
    """Transmittals not yet acknowledged (oldest first), and whether each
    is past its response date."""
    today = today or _today()
    return [(t, bool(t.get("due")) and t["due"] < today)
            for t in transmittals(doc) if not t["acks"]]


def transmittal_pdf(doc, tid, path, project="", company=""):
    t = _tr(read(doc), tid)
    f = forms.Form(f"Transmittal {t['id']}", project, company=company)
    f.fields([("To", t["to"]), ("Date", t["date"]), ("From", t["from"]),
              ("Sent by", t["method"]), ("CC", t.get("cc", "")),
              ("Response due", t.get("due", "")), ("Purpose", t["purpose"]),
              ("Items", len(t["items"]))])
    f.table(["#", "Document / sheet", "Description", "Rev", "Date",
             "Copies"],
            [[i + 1, x.get("doc", ""), x.get("desc", ""), x.get("rev", ""),
              x.get("date", ""), x.get("copies", 1)]
             for i, x in enumerate(t["items"])],
            [0.4, 1.4, 4, 0.6, 1, 0.6], ["l", "l", "l", "c", "l", "c"])
    if t.get("notes"):
        f.heading("Remarks")
        f.para(t["notes"])
    if t["acks"]:
        f.heading("Received")
        f.table(["By", "Date", "Note"], [[a["who"], a["date"],
                                          a.get("note", "")]
                                         for a in t["acks"]], [2, 1, 4])
    f.para("If the enclosures are not as listed, please notify us at "
           "once. Sign and return one copy to acknowledge receipt.", 8.5)
    f.signatures(["Received by", "Company", "Date"])
    return f.save(path)


# ---- addenda --------------------------------------------------------------------

def add_addendum(doc, title, issued=None, desc="", sheets=(), bidders=()):
    if not str(title).strip():
        raise DocControlError("Give the addendum a title.")
    data = read(doc)
    aid = _next(data, "ADD")
    data["addenda"].append({
        "id": aid, "no": int(data["counter"]["ADD"]), "title": title,
        "issued": issued or _today(), "desc": desc,
        "sheets": [str(s).upper() for s in sheets],
        "bidders": [b for b in (str(x).strip() for x in bidders) if b],
        "acks": [], "by": _who()})
    write(doc, data)
    return aid


def addenda(doc):
    return read(doc)["addenda"]


def price_addendum(doc, aid, priced=True, cost="", line_id="", note="",
                   received=None):
    """Addenda Gate (Nov 3): mark an addendum priced - its cost impact
    (money, "0" when it changes nothing), the estimate line it went into
    and the day. `received`: the day it reached us, when not its issue
    day."""
    from decimal import Decimal, InvalidOperation
    data = read(doc)
    for a in data["addenda"]:
        if a["id"] == aid:
            if cost not in ("", None):
                try:
                    c = Decimal(str(cost).replace("$", "").replace(",", ""))
                except InvalidOperation:
                    raise DocControlError(f"Cost impact {cost!r} isn't a "
                                          "number.")
                a["cost"] = f"{_c2(c):.2f}"
            a["priced"] = bool(priced)
            a["priced_on"] = _today() if priced else ""
            if line_id is not None:
                a["line_id"] = str(line_id or "")
            if note:
                a["price_note"] = str(note)
            if received:
                a["received"] = str(received)[:10]
            write(doc, data)
            return a
    raise KeyError(aid)


def unpriced_addenda(doc):
    return [a for a in read(doc)["addenda"] if not a.get("priced")]


def ack_addendum(doc, aid, bidder, date=None):
    data = read(doc)
    for a in data["addenda"]:
        if a["id"] == aid:
            b = str(bidder).strip()
            if b not in a["bidders"]:
                a["bidders"].append(b)
            if b not in [x["who"] for x in a["acks"]]:
                a["acks"].append({"who": b, "date": date or _today()})
            write(doc, data)
            return a
    raise KeyError(aid)


def unacknowledged(doc):
    """{addendum id: [bidders who haven't acknowledged it]}"""
    out = {}
    for a in addenda(doc):
        done = {x["who"] for x in a["acks"]}
        out[a["id"]] = [b for b in a["bidders"] if b not in done]
    return out


def addenda_pdf(doc, path, project=""):
    f = forms.Form("Addenda Log", project)
    adds = addenda(doc)
    if not adds:
        f.para("No addenda issued.")
    for a in adds:
        f.heading(f"Addendum No. {a['no']} - {a['title']}")
        f.fields([("Issued", a["issued"]), ("Sheets", ", ".join(a["sheets"])
                                            or "-")])
        f.para(a.get("desc", ""))
        acks = {x["who"]: x["date"] for x in a["acks"]}
        f.table(["Bidder", "Acknowledged"],
                [[b, acks.get(b, "NOT ACKNOWLEDGED")] for b in a["bidders"]]
                or [["-", "-"]], [3, 2],
                fills=[None if b in acks else (1, 0.9, 0.9)
                       for b in a["bidders"]] or None)
    return f.save(path)
