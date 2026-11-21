"""Project Analysis (Nov 20, Jon, with Chief's list he approved): the
answers a bidder needs from a project manual, read by pattern - nothing
leaves the PC - each with its spec section and page.

    run(doc) -> [row]             every answer, Jon's nine first
        row: {key, label, value, page, section, text, also: [(value,
              page)]}; page None and value "not found" / "not listed"
              when the specs don't say - never a guess
    cached(doc) / save(doc, rows) the answers kept in the PDF; run again
                                  when pages were added (an addendum)
    completion_dates(rows, ntp)   calendar / working days from the notice
                                  to proceed as real dates
    ld_exposure(rows, days_late)  the LD rate x the days late (Decimal)
    export_pdf(rows, path, title) a one-page summary

Where the documents say two things (the bid date moved by an addendum),
the answer from the highest-numbered addendum wins and the others are
kept as "also stated". Without addenda the front end (Division 00, the
first pages) wins over later mentions.
"""
import datetime
import json
import re
from decimal import Decimal, InvalidOperation

from . import bidterms, embfiles

FILE = "quantisheet_project_analysis.json"
VERSION = 1

EXTRA = (("bid_bond", "Bid bond"),
         ("perf_bond", "Performance bond"),
         ("pay_bond", "Payment bond"),
         ("insurance", "Insurance - general liability"),
         ("questions_due", "Last day for questions / RFIs"),
         ("delivery", "Bid delivery"),
         ("prevailing_wage", "Prevailing wage / Davis-Bacon"),
         ("goals", "DBE / MBE / SBE goal"),
         ("alternates", "Bid alternates"),
         ("unit_prices", "Unit prices"),
         ("addenda", "Addenda in this document"),
         ("owner", "Owner"),
         ("architect", "Architect / engineer"),
         ("hold_days", "Bid must hold (days)"),
         ("contract_time", "Contract time"))
ORDER = tuple(bidterms.ANALYSIS) + EXTRA
LABEL = dict(ORDER)
CONFLICT_KEYS = ("bid_date", "prebid", "substantial", "final", "ld_value",
                 "retainage", "questions_due", "bid_bond", "budget")

_ADDENDUM = re.compile(r"\bADDENDUM\s+(?:NO\.?|NUMBER|#)\s*(\d{1,2})\b", re.I)
_PCT = r"(\d{1,3}(?:\.\d{1,2})?)\s*(?:%|percent\b)"
_PERF = re.compile(r"\bperformance\s+bond\b[^.;]{0,120}?" + _PCT, re.I)
_PAYB = re.compile(r"\b(?:payment|labor\s+and\s+material(?:s)?)\s+bond\b"
                   r"[^.;]{0,120}?" + _PCT, re.I)
_BONDS_BOTH = re.compile(r"\bperformance\s+and\s+payment\s+bonds?\b"
                         r"[^.;]{0,120}?" + _PCT, re.I)
_MONEY = r"(\$\s?[\d,]+(?:\.\d{2})?)"
_INSUR = re.compile(r"\b(?:commercial\s+)?general\s+liability\b[^.]{0,160}?"
                    + _MONEY + r"[^.]{0,40}?\b(?:each|per)\s+occurrence", re.I)
_QUESTIONS = re.compile(r"\b(?:questions|inquiries|requests?\s+for\s+"
                        r"(?:information|interpretation)|RFIs?)\b[^.]{0,140}?"
                        r"\b(?:no\s+later\s+than|not\s+later\s+than|until|by|"
                        r"before|prior\s+to)\b", re.I)
_DELIVERY = (("electronic", re.compile(
                r"\b(?:submitted|received|delivered)\s+electronically\b|"
                r"\belectronic\s+(?:bids?|submission|bidding)\b|"
                r"\bonline\s+bid", re.I)),
             ("in person / hand delivered", re.compile(
                r"\bhand[\s-]+deliver\w*|\bin\s+person\b", re.I)),
             ("sealed envelope", re.compile(r"\bsealed\s+(?:envelope|bids?|"
                                            r"proposals?)\b", re.I)),
             ("by mail", re.compile(r"\b(?:mailed|by\s+mail|U\.?S\.?\s+"
                                    r"mail|courier)\b", re.I)))
_UNIT = re.compile(r"\bunit\s+price\s+(?:no\.?|number|#)?\s*(\d{1,3})\b", re.I)
_PERSON = {
    "owner": re.compile(r"\bOwner\s*:\s*(.{3,100}?)" + bidterms._NEXT_LABEL,
                        re.I),
    "architect": re.compile(r"\b(?:Architect(?:\s*/\s*Engineer)?|Engineer|"
                            r"Design\s+Professional)\s*:\s*(.{3,100}?)" +
                            bidterms._NEXT_LABEL, re.I),
}


def _sections(doc):
    """{page: 'xx xx xx Title'} following SECTION headings and footers."""
    from . import specmfrs
    out, cur = {}, ""
    for p in range(doc.page_count):
        t = doc[p].get_text() or ""
        m = specmfrs._SECTION.search(t)
        if m:
            cur = f"{specmfrs._code(m.group(1))} {m.group(2).strip().title()}"
        else:
            f = specmfrs._FOOTER.search(t)
            if f and not cur.startswith(specmfrs._code(f.group(1))):
                cur = specmfrs._code(f.group(1))
        out[p] = cur
    return out


def _addendum_of(text):
    m = _ADDENDUM.search(text[:600])     # the addendum's own heading
    return int(m.group(1)) if m else 0


def _extra_on_page(t, p, raw=None):
    """{key: (value, snippet)} for the extra fields on one page (`raw`:
    the page text with its line breaks, for "Owner:" lines)."""
    out = {}

    def put(key, value, m):
        out.setdefault(key, (value, bidterms._snip(t, m)))
    m = _BONDS_BOTH.search(t)
    if m:
        put("perf_bond", f"{float(m.group(1)):g}% of the contract", m)
        put("pay_bond", f"{float(m.group(1)):g}% of the contract", m)
    m = _PERF.search(t)
    if m:
        put("perf_bond", f"{float(m.group(1)):g}% of the contract", m)
    m = _PAYB.search(t)
    if m:
        put("pay_bond", f"{float(m.group(1)):g}% of the contract", m)
    m = _INSUR.search(t)
    if m:
        put("insurance", f"{m.group(1)} each occurrence", m)
    for m in _QUESTIONS.finditer(t):
        d = bidterms._DATE.search(t, m.end(), m.end() + 80)
        if d:
            tm = bidterms._TIME_OF_DAY.search(t, m.end(), d.end() + 40)
            put("questions_due", d.group() + (f", {bidterms._tod(tm)}" if tm
                                              else ""), m)
            break
    kinds = [(name, rx.search(t)) for name, rx in _DELIVERY]
    kinds = [(n, m) for n, m in kinds if m]
    if kinds:
        put("delivery", ", ".join(n for n, _ in kinds), kinds[0][1])
    for key, rx in _PERSON.items():
        src = raw if raw is not None else t
        m = rx.search(src)
        if m and len(m.group(1).split()) <= 12:
            out.setdefault(key, (m.group(1).strip(" .,;"),
                                 bidterms._snip(src, m).replace("\n", " ")))
    return out


def run(doc):
    secs = _sections(doc)
    cands = {}            # key -> [(value, page, addendum, snippet)]
    units, addenda = set(), set()
    for p in range(doc.page_count):
        t = bidterms._page_text(doc[p])
        if not t.strip():
            continue
        add_no = _addendum_of(t)
        if add_no:
            addenda.add(add_no)
        for m in _UNIT.finditer(t):
            units.add(int(m.group(1)))
        for f in bidterms.find(doc, [p], extra=True):
            if f["key"] == "alternates":
                continue
            cands.setdefault(f["key"], []).append(
                (f["value"], p, add_no, f["text"]))
        raw = doc[p].get_text() or ""
        for key, (val, snip) in _extra_on_page(t, p, raw).items():
            cands.setdefault(key, []).append((val, p, add_no, snip))
    alts = [f for f in bidterms.find(doc) if f["key"] == "alternates"]
    rows = []
    for key, label in ORDER:
        c = cands.get(key) or []
        if key == "alternates" and alts:
            a = alts[0]
            c = [(a["value"], a["page"], 0, a["text"])]
        if key == "unit_prices" and units:
            c = [(f"{len(units)} (No. " + ", ".join(
                str(n) for n in sorted(units)) + ")", None, 0, "")]
        if key == "delivery" and c:
            # every method the documents name, strongest first
            names = [n for n, _rx in _DELIVERY
                     if any(n in v for v, *_x in c)]
            first = next(x for x in c if names[0] in x[0])
            c = [(", ".join(names), first[1], first[2], first[3])]
        if key == "addenda":
            c = [(str(len(addenda)) + (" (No. " + ", ".join(
                str(n) for n in sorted(addenda)) + ")" if addenda else ""),
                  None, 0, "")]
        if not c:
            rows.append({"key": key, "label": label,
                         "value": bidterms.NOT_FOUND.get(key, "not found"),
                         "page": None, "section": "", "text": "",
                         "also": []})
            continue
        # the newest addendum wins; else the front end (first page)
        best = max(c, key=lambda x: (x[2], -(x[1] if x[1] is not None
                                             else 10 ** 6)))
        also = []
        if key in CONFLICT_KEYS:
            seen = {best[0]}
            for v, pg, _a, _s in c:
                if v not in seen:
                    seen.add(v)
                    also.append((v, pg))
        rows.append({"key": key, "label": label, "value": best[0],
                     "page": best[1],
                     "section": secs.get(best[1], "") if best[1] is not None
                     else "", "text": best[3],
                     "addendum": best[2], "also": also})
    return rows


# ------------------------------------------------------------------ cache
def save(doc, rows):
    data = {"version": VERSION, "pages": doc.page_count, "rows": rows,
            "made": datetime.date.today().isoformat()}
    embfiles.put(doc, FILE, json.dumps(data).encode("utf-8"),
                 "QuantiSheet project analysis")


def cached(doc):
    """The kept answers, or None when there are none or the document has
    gained or lost pages since (an addendum was added)."""
    try:
        if FILE not in embfiles.names(doc):
            return None
        data = json.loads(embfiles.get(doc, FILE).decode("utf-8"))
    except Exception:                                     # noqa: BLE001
        return None
    if data.get("version") != VERSION or data.get("pages") != doc.page_count:
        return None
    return data.get("rows")


# ---------------------------------------------------------------- outputs
def _days(value):
    m = re.match(r"\s*(\d{1,4})\s+(calendar|working)", value or "")
    return (int(m.group(1)), m.group(2)) if m else None


def add_days(start, n, kind="calendar"):
    """`n` calendar days, or working days (Monday to Friday), after
    `start`."""
    if kind == "calendar":
        return start + datetime.timedelta(days=n)
    d, left = start, n
    while left > 0:
        d += datetime.timedelta(days=1)
        if d.weekday() < 5:
            left -= 1
    return d


def completion_dates(rows, ntp):
    """{substantial, final: date} from the notice to proceed."""
    out = {}
    for r in rows:
        if r["key"] in ("substantial", "final") and r["page"] is not None:
            d = _days(r["value"])
            if d:
                out[r["key"]] = add_days(ntp, d[0], d[1])
    return out


def ld_rate(rows):
    """(amount per day as Decimal, 'day') from the LD answer, or None."""
    for r in rows:
        if r["key"] != "ld_value" or r["page"] is None:
            continue
        m = re.search(r"([\d,]+(?:\.\d{1,2})?)", r["value"])
        if not m:
            return None
        try:
            amt = Decimal(m.group(1).replace(",", ""))
        except InvalidOperation:
            return None
        if "million" in r["value"].lower():
            amt *= Decimal(1000000)
        if r["value"].rstrip().endswith("week"):
            amt = amt / Decimal(7)
        return amt
    return None


def ld_exposure(rows, days_late):
    rate = ld_rate(rows)
    if rate is None:
        return None
    return (rate * Decimal(int(days_late))).quantize(Decimal("0.01"))


def export_pdf(rows, path, title="Project Analysis", ntp=None,
               days_late=None):
    import fitz
    d = fitz.open()
    pg = d.new_page(width=612, height=792)
    y = 54
    pg.insert_text((54, y), title, fontsize=15)
    y += 22
    lines = []
    for r in rows:
        where = "" if r["page"] is None else (
            f"  [p. {r['page'] + 1}" + (f", {r['section']}" if r["section"]
                                       else "") + "]")
        lines.append(f"{r['label']}: {r['value']}{where}")
        for v, pgno in r.get("also") or []:
            lines.append(f"      also stated: {v}" +
                         (f" (p. {pgno + 1})" if pgno is not None else ""))
    if ntp:
        for k, dt in completion_dates(rows, ntp).items():
            lines.append(f"{LABEL[k]} from NTP {ntp.isoformat()}: "
                         f"{dt.isoformat()}")
    if days_late:
        ex = ld_exposure(rows, days_late)
        if ex is not None:
            lines.append(f"LD exposure for {days_late} days late: "
                         f"{ex:,}")
    text = "\n".join(lines)
    size = 9.0
    while size > 5.5 and pg.insert_textbox(
            fitz.Rect(54, y, 558, 760), text, fontsize=size) < 0:
        size -= 0.5
    if size <= 5.5:
        pg.insert_textbox(fitz.Rect(54, y, 558, 760), text, fontsize=5.5)
    pg.insert_text((54, 778), "Read from the documents by pattern - check "
                   "each answer on its page.", fontsize=7)
    d.save(path)
    d.close()
    return path
