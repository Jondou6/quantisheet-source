"""The bid set: base scope, drawings, addenda and Q&A, applied in order.

A renovation bid often has no spec divisions worth the name: the work is
a numbered scope list in the bid form, notes on the plans, and a stack of
addenda and bidder questions that add and remove items. This module turns
that stack into live scope lines, each with the document it came from,
and keeps the removed lines (and what removed them) on the record.

Documents are applied in the order given - the order they were issued -
and a later document wins: an item deleted by Addendum 1 and added back
by Addendum 3 is live again.

Each document is {"kind", "id", "text"}; kind is one of
  bid       - the bid form / scope of work (numbered items)
  drawing   - one sheet; "id" is the sheet number, numbered notes count
  addendum  - "Item 3 is deleted", "ADD: ...", "Delete item 4"
  qa        - "Q: ... A: ..." pairs; an answer that removes or adds scope
  spec      - read by the spec path; ignored here

Then activities() maps each live line to a trade class with a duration
from quantity x a production rate when the line states a quantity, and
says so when it doesn't. Rates are starting values (RATES), editable.
Nothing here calls a model or the network.
"""
import re

KINDS = ("bid", "drawing", "addendum", "qa", "spec")

CAVEAT = ("For reference only. Dates are confirmed after Notice to Proceed "
          "and once material lead times are confirmed.")

_STOP = set("""a an and are as at be by for from in into is it its of on or
the this that to with all any each per new existing install installed
furnish provide replace replaced remove removed repair repairs work scope
item items bid building buildings shall will be been has have not no yes
there their they which what should still required still please confirm
contractor owner""".split())

_NUMBERED = re.compile(r"^\s*(?:item\s+)?(\d{1,3})\s*[.)]\s+(.{4,})$", re.I)
_NOTE = re.compile(r"^\s*(?:(?:key)?note\s*)?(\d{1,3}|[A-Z])\s*[.):]\s+(.{4,})$",
                   re.I)
_ITEM_REF = r"(?:bid\s+|scope\s+)?item\s*(?:no\.?\s*|#\s*)?(\d{1,3})"
_DEL_WORDS = (r"deleted|removed|omitted|struck|eliminated|not\s+(?:be\s+)?"
              r"(?:required|included)|no\s+longer\s+(?:required|included|"
              r"part\s+of)|not\s+(?:in|part\s+of)\s+(?:the\s+)?(?:scope|"
              r"contract|work)|by\s+(?:the\s+)?owner|by\s+others")
_DEL_ITEM = (
    re.compile(r"\b(?:delete|remove|omit|strike)\s+" + _ITEM_REF, re.I),
    re.compile(_ITEM_REF + r"\b[^.\n]{0,160}?\b(?:is|are|has\s+been|shall\s+be|"
               r"will\s+be)\s+(?:hereby\s+)?(?:" + _DEL_WORDS + r")", re.I),
    re.compile(_ITEM_REF + r"\b[^.\n]{0,160}?[-:]\s*(?:" + _DEL_WORDS + r")\b",
               re.I),
)
_DEL_TEXT = re.compile(r"\b(?:" + _DEL_WORDS + r"|delete|deleted|omit)\b", re.I)
_ADD = re.compile(r"^\s*(?:\d{1,3}\s*[.)]\s*)?(?:add|added|addition)\s*[:\-]\s*"
                  r"(.{4,})$", re.I)
_ADD_TEXT = re.compile(r"\b(?:is|are)\s+(?:hereby\s+)?added\s+to\s+the\s+"
                       r"(?:scope|work|contract)\b", re.I)
_QA = re.compile(r"(?:^|\n)\s*Q(?:uestion)?\s*\d*\s*[:.)]\s*(.+?)\n\s*"
                 r"A(?:nswer)?\s*\d*\s*[:.)]\s*(.+?)(?=\n\s*Q(?:uestion)?\s*\d*"
                 r"\s*[:.)]|\Z)", re.I | re.S)
_QTY = re.compile(
    r"\b(?:approx(?:imately|\.)?\s*|about\s*|\(\s*)?([\d,]+(?:\.\d+)?)\s*"
    r"(SF|LF|SY|EA|flights?|doors?|windows?|fixtures?|devices?|fans?|units?|"
    r"hoods?)\b", re.I)
_LEAD = re.compile(r"lead\s+time\s+(?:is\s+|of\s+)?(?:about\s+)?(\d{1,3})\s*"
                   r"(weeks?|wks?|days?|calendar\s+days)", re.I)
_OFOI = re.compile(r"\bOFOI\b|owner[- ]furnished,?\s+owner[- ]installed", re.I)
_OFCI = re.compile(r"\bOFCI\b|owner[- ]furnished,?\s+contractor[- ]installed",
                   re.I)

# unit spellings -> the rate table's unit
_UNIT = {"sf": "SF", "lf": "LF", "sy": "SY", "ea": "EA", "flight": "EA",
         "flights": "EA", "door": "EA", "doors": "EA", "window": "EA",
         "windows": "EA", "fixture": "EA", "fixtures": "EA", "device": "EA",
         "devices": "EA", "fan": "EA", "fans": "EA", "unit": "EA",
         "units": "EA", "hood": "EA", "hoods": "EA"}

# class -> (pattern, wbs, division, role, calendar, default workdays)
# First match wins, so the narrow patterns come first.
TRADES = (
    ("site_misc", r"\b(?:generator|enclosure)\b", "1.3", "06", "Carpenter",
     "5day", 10),
    ("hood_install", r"\bhood\b|\bkitchen\b.*suppression|suppression system",
     "1.7", "23", "HVAC technician", "5day", 5),
    ("casework", r"\bcasework\b|\bcabinet", "1.6", "12", "Carpenter",
     "5day", 5),
    ("coating", r"\bcorrosion\b|\brust\b|\bcoating\b", "1.5", "09",
     "Painter", "weather", 10),
    ("ext_paint", r"exterior\s+paint|paint\b.*\bwindow\s+frames?|window\s+"
     r"frames?\b.*\bpaint", "1.5", "09", "Painter", "weather", 10),
    ("sealants", r"\bcaulk|\bsealant", "1.5", "07", "Caulker", "weather", 6),
    ("stucco", r"\bstucco\b", "1.5", "09", "Plasterer", "weather", 4),
    ("demolition", r"\bdemo(?:lition|lish)?\b", "1.3", "02", "Laborer",
     "5day", 7),
    ("framing", r"\bframing\b|\bstud\s+walls?\b|\bnew\s+partitions?\b", "1.6",
     "09", "Carpenter", "5day", 5),
    ("mep_rough", r"\brough[- ]?in\b", "1.7", "22", "MEP crew", "5day", 20),
    ("cover", r"\bdrywall\b|\bgypsum\b|\bnail\s+pops?\b|\bceiling\s+crack",
     "1.6", "09", "Drywall crew", "5day", 10),
    ("doors_reinstall", r"re-?install\b.*\b(?:doors?|frames?)\b|\b(?:doors?|"
     r"frames?)\b.*\bre-?install", "1.6", "08", "Carpenter", "5day", 2),
    ("int_doors", r"\binterior\s+doors?\b", "1.6", "09", "Painter", "5day", 6),
    ("finishes", r"\binterior\s+paint|\bpaint\b", "1.6", "09", "Painter",
     "5day", 10),
    ("flooring", r"\bfloor(?:ing)?\b|\bbase\b|\bvct\b|\blvt\b|\bcarpet",
     "1.6", "09", "Flooring crew", "5day", 5),
    ("trim", r"\bexhaust\s+fans?\b|\bfixtures?\b|\bdevices?\b|\btrim\b",
     "1.7", "26", "MEP crew", "5day", 7),
    ("clean", r"\bclean(?:ing)?\b", "1.8", "01", "Laborer", "5day", 2),
)

# Production rates per crew-day (one crew), starting values - change them
# in the company's rate table. Units must match the quantity on the line.
RATES = {
    ("coating", "SF"): 100, ("coating", "LF"): 60, ("coating", "EA"): 1,
    ("sealants", "LF"): 400, ("stucco", "SF"): 50,
    ("ext_paint", "SF"): 1200, ("ext_paint", "EA"): 6,
    ("demolition", "SF"): 600, ("framing", "LF"): 120,
    ("mep_rough", "SF"): 400, ("cover", "SF"): 1000, ("cover", "EA"): 40,
    ("doors_reinstall", "EA"): 12, ("int_doors", "EA"): 8,
    ("finishes", "SF"): 2500, ("flooring", "SF"): 800,
    ("trim", "EA"): 15, ("clean", "SF"): 6000, ("casework", "LF"): 30,
    ("hood_install", "EA"): 0.2,
}

# Trade logic for these classes (added to the rule table for a bid set).
RULES = (
    ("mobilization", "demolition"), ("mobilization", "coating"),
    ("mobilization", "sealants"), ("mobilization", "stucco"),
    ("mobilization", "site_misc"), ("demolition", "framing"),
    ("framing", "mep_rough"), ("mep_rough", "rough_in_inspection"),
    ("rough_in_inspection", "cover"), ("framing", "cover"),
    ("cover", "doors_reinstall"), ("doors_reinstall", "finishes"),
    ("doors_reinstall", "int_doors"), ("finishes", "casework"),
    ("finishes", "hood_install"), ("finishes", "trim"),
    ("int_doors", "flooring"), ("casework", "flooring"),
    ("hood_install", "flooring"), ("trim", "flooring"),
    ("finishes", "flooring"), ("flooring", "clean"),
    ("clean", "punch"), ("clean", "final_inspection"),
    ("sealants", "ext_paint"),
    ("ext_paint", "final_inspection"), ("stucco", "final_inspection"),
    ("coating", "final_inspection"), ("site_misc", "final_inspection"),
    ("scope_item", "final_inspection"), ("final_inspection", "substantial"),
)
FIELD = {t[0] for t in TRADES} | {"scope_item"}
ROUGH = {"mep_rough", "plumb_rough", "hvac_rough", "elec_rough", "fire_rough"}


def _words(text):
    return {w for w in re.findall(r"[a-z]{3,}", (text or "").lower())
            if w not in _STOP}


def _clean(text):
    t = " ".join(str(text or "").split()).strip(" .;")
    return t[:1].upper() + t[1:] if t else t


def _line(key, text, source, document, kind):
    return {"key": key, "text": _clean(text), "source": source,
            "document": document, "kind": kind, "history": []}


def _numbered(text):
    out = []
    for raw in (text or "").splitlines():
        m = _NUMBERED.match(raw)
        if m:
            out.append((m.group(1), m.group(2)))
    return out


def _find(lines, number=None, text=None):
    """The live line an addendum or answer means: by bid item number, or
    by the words it shares with one line (one clear best match)."""
    if number is not None:
        return next((x for x in lines if x["kind"] == "bid" and
                     x["key"] == f"B{int(number)}"), None)
    want = _words(text)
    best, best_score, tie = None, 0.0, False
    for x in lines:
        have = _words(x["text"])
        if not have:
            continue
        shared = len(have & want)
        score = shared / len(have)
        if shared < 2 and not (shared == 1 and len(have) <= 2):
            continue
        if score > best_score + 1e-9:
            best, best_score, tie = x, score, False
        elif abs(score - best_score) < 1e-9:
            tie = True
    if best is None or tie or best_score < 0.34:
        return None
    return best


def resolve(documents):
    """{"lines", "removed", "log"}: the live scope after every document,
    in order; removed lines say what removed them."""
    live, removed, log, skipped = [], [], [], []
    n_add = 0

    def remove(x, by, why):
        if x in live:
            live.remove(x)
            x = dict(x, removed_by=by, removed_why=_clean(why)[:200])
            removed.append(x)
            log.append(("removed", x["key"], by, x["text"]))

    def add(text, by, document):
        nonlocal n_add
        text = _clean(text)
        back = next((r for r in removed if _words(r["text"]) == _words(text)),
                    None)
        if back is not None:                       # later wins: restored
            removed.remove(back)
            back = dict(back, restored_by=by)
            back.pop("removed_by", None)
            live.append(back)
            log.append(("restored", back["key"], by, back["text"]))
            return
        n_add += 1
        x = _line(f"X{n_add}", text, by, document, "added")
        live.append(x)
        log.append(("added", x["key"], by, x["text"]))

    for doc in documents or ():
        kind = (doc.get("kind") or "").lower()
        did = doc.get("id") or kind.title()
        text = doc.get("text") or ""
        if kind == "bid":
            for num, body in _numbered(_scope_block(text)):
                live.append(_line(f"B{int(num)}", body,
                                  f"{did} item {int(num)}", did, "bid"))
        elif kind == "drawing":
            for raw in text.splitlines():
                m = _NOTE.match(raw)
                if not m:
                    continue
                x = _line(f"{did}-{m.group(1)}", m.group(2),
                          f"Sheet {did} note {m.group(1)}", did, "drawing")
                if _trade(x["text"]) is None:
                    # general notes ("all dimensions to face of stud") are
                    # not work; listed for review, not scheduled
                    skipped.append(x)
                    log.append(("skipped", x["key"], x["source"], x["text"]))
                    continue
                live.append(x)
        elif kind == "addendum":
            for i, raw in enumerate(text.splitlines(), 1):
                if not raw.strip():
                    continue
                num = re.match(r"\s*(\d{1,3})\s*[.)]\s", raw)
                at = (f"{did} item {num.group(1)}" if num
                      else f"{did}, line {i}")
                hit = False
                for pat in _DEL_ITEM:
                    for m in pat.finditer(raw):
                        x = _find(live, number=m.group(1))
                        if x is not None:
                            remove(x, at, raw)
                            hit = True
                if hit:
                    continue
                m = _ADD.match(raw)
                if m:
                    add(m.group(1), at, did)
                    continue
                if _ADD_TEXT.search(raw):
                    add(_ADD_TEXT.sub("", raw), at, did)
                    continue
                if _DEL_TEXT.search(raw):
                    x = _find(live, text=raw)
                    if x is not None:
                        remove(x, at, raw)
        elif kind == "qa":
            for j, m in enumerate(_QA.finditer(text), 1):
                q, a = m.group(1).strip(), m.group(2).strip()
                tag = f"{did} Q{j}"
                if _DEL_TEXT.search(a) and not re.match(r"\s*yes\b", a, re.I):
                    x = None
                    ref = re.search(_ITEM_REF, q + " " + a, re.I)
                    if ref:
                        x = _find(live, number=ref.group(1))
                    if x is None:
                        x = _find(live, text=q + " " + a)
                    if x is not None:
                        remove(x, tag, a)
                    else:
                        log.append(("unmatched", "", tag, a[:120]))
                elif _ADD_TEXT.search(a) or _ADD.match(a):
                    add(_ADD.match(a).group(1) if _ADD.match(a) else q, tag,
                        did)
    return {"lines": live, "removed": removed, "log": log,
            "skipped": skipped}


def _scope_block(text):
    """The numbered list under a SCOPE OF WORK heading, when there is one
    (a bid package has many other numbered lines)."""
    m = re.search(r"scope\s+of\s+(?:the\s+)?work", text or "", re.I)
    if not m:
        return text or ""
    out, seen = [], False
    for raw in text[m.end():].splitlines():
        st = raw.strip()
        if _NUMBERED.match(raw):
            seen = True
            out.append(raw)
        elif seen and st and st.upper() == st and len(st) > 8 and \
                re.search(r"[A-Z]{4}", st):
            break                                  # next heading
        elif seen and out and st and not re.match(r"\d", st):
            out[-1] += " " + st                    # wrapped item
    return "\n".join(out)


_SHEET_NO = re.compile(r"\b(?:SHEET\s+)?([A-Z]{1,3}\s?-?\d{1,3}(?:\.\d{1,2})?"
                       r"[A-Z]?)\b")


def _pdf_pages(path):
    """Plain text of each page; nothing from the document outlives it."""
    if str(path).lower().endswith(".txt"):
        with open(path, encoding="utf-8", errors="replace") as fh:
            return [fh.read()]
    import fitz
    with fitz.open(path) as doc:
        return [pg.get_text() or "" for pg in doc]


def kind_of(text):
    """addendum or qa, from the text."""
    qs = len(re.findall(r"(?:^|\n)\s*Q(?:uestion)?\s*\d*\s*[:.)]", text or ""))
    return "qa" if qs >= 1 and re.search(r"(?:^|\n)\s*A(?:nswer)?\s*\d*\s*"
                                         r"[:.)]", text or "") else "addendum"


def from_files(bid=None, drawings=None, addenda=()):
    """A bid set from the files a person picked: the bid documents, the
    plan set (one document per sheet) and the addenda / Q&A in the order
    issued."""
    import os
    docs = []
    if bid:
        docs.append({"kind": "bid", "id": "Bid documents",
                     "text": "\n".join(_pdf_pages(bid))})
    if drawings:
        for i, text in enumerate(_pdf_pages(drawings), 1):
            m = _SHEET_NO.search(text or "")
            docs.append({"kind": "drawing",
                         "id": m.group(1).replace(" ", "") if m else
                         f"page {i}", "text": text})
    for path in addenda or ():
        text = "\n".join(_pdf_pages(path))
        name = os.path.splitext(os.path.basename(path))[0]
        docs.append({"kind": kind_of(text), "id": name, "text": text})
    return docs


def _trade(text):
    low = (text or "").lower()
    for row in TRADES:
        if re.search(row[1], low):
            return row
    return None


def quantity(text):
    m = _QTY.search(text or "")
    if not m:
        return None, ""
    try:
        q = float(m.group(1).replace(",", ""))
    except ValueError:
        return None, ""
    return q, _UNIT.get(m.group(2).lower(), m.group(2).upper())


def lead_days(text):
    """Stated lead time in workdays (weeks x 5), or None."""
    m = _LEAD.search(text or "")
    if not m:
        return None
    n = int(m.group(1))
    unit = m.group(2).lower()
    if unit.startswith("w"):
        return n * 5
    if "calendar" in unit:
        return max(1, round(n * 5 / 7))
    return n


def plan_line(line, rates=None):
    """What activity a live line becomes: class, duration and why."""
    rates = rates or RATES
    row = _trade(line["text"])
    if row is None:
        cls, wbs, div, role, cal, days = ("scope_item", "1.6", "", "Crew",
                                          "5day", 5)
        matched = False
    else:
        cls, _pat, wbs, div, role, cal, days = row
        matched = True
    qty, unit = quantity(line["text"])
    rate = rates.get((cls, unit)) if qty else None
    if qty and rate:
        d = max(1, round(qty / float(rate)))
        basis = (f"{qty:g} {unit} / {rate:g} {unit} per crew-day (starting "
                 f"rate) = {d} workdays")
        kind, missing = "computed", False
    else:
        d = days
        basis = (f"no quantity on {line['source']}; {d} workdays estimated"
                 if not qty else f"no rate for {unit} on {cls}; {d} workdays "
                 "estimated")
        kind, missing = "estimated", True
    owner = bool(_OFOI.search(line["text"]))
    return {"cls": cls, "wbs": wbs, "division": div, "role": role,
            "calendar": cal, "days": d, "basis": basis,
            "duration_kind": kind, "quantity_missing": missing,
            "quantity": qty, "unit": unit, "matched": matched,
            "owner_installed": owner,
            "owner_furnished": owner or bool(_OFCI.search(line["text"])),
            "lead_days": lead_days(line["text"])}


def cite(line):
    return [{"document": line["document"], "source": line["source"],
             "spec_section": "", "page": None, "text": line["text"][:160]}]
