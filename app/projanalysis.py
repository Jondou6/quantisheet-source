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
# a limits table: "... Each Occurrence $1,000,000.00" after the heading
_INSUR2 = re.compile(r"\bgeneral\s+liability\b.{0,1500}?\beach\s+occurrence\s*"
                     + _MONEY, re.I | re.S)
_QUESTIONS = re.compile(r"\b(?:questions|inquiries|requests?\s+for\s+"
                        r"(?:information|interpretation)|RFIs?)\b[^.]{0,140}?"
                        r"\b(?:no\s+later\s+than|not\s+later\s+than|until|by|"
                        r"before|prior\s+to)\b", re.I)
# "at least ten days prior": the number written out
_WORDS = {w: n for n, w in enumerate(
    "one two three four five six seven eight nine ten eleven twelve "
    "thirteen fourteen fifteen sixteen seventeen eighteen nineteen "
    "twenty".split(), 1)}
_WORDS.update({"twenty-one": 21, "twenty-five": 25, "thirty": 30})
# "... must be received at least seven (7) days prior to the date fixed
# for the opening of bids" - a deadline counted back from bid day
_QUESTIONS_REL = re.compile(
    r"\b(?:requests?|questions|inquiries|interpretations?)\b[^.]{0,300}?"
    r"\bat\s+least\s+(?:[a-z-]+\s+\((\d{1,2})\)|\(?(\d{1,2})\)?|"
    r"(" + "|".join(sorted(_WORDS, key=len, reverse=True)) + r"))"
    r"\s+(calendar\s+|working\s+|"
    r"business\s+)?days\s+(?:prior\s+to|before)\s+(?:the\s+)?(?:date\s+"
    r"(?:fixed\s+|set\s+|scheduled\s+)?for\s+(?:the\s+)?)?(?:bid\s+opening|"
    r"opening\s+of\s+(?:the\s+)?bids|bid\s+date|receipt\s+of\s+bids)", re.I)
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
    m = _INSUR2.search(t) or _INSUR.search(t)
    if m:
        put("insurance", f"{m.group(1)} each occurrence", m)
    for m in _QUESTIONS.finditer(t):
        d = bidterms._DATE.search(t, m.end(), m.end() + 80)
        if d:
            tm = bidterms._TIME_OF_DAY.search(t, m.end(), d.end() + 40)
            put("questions_due", d.group() + (f", {bidterms._tod(tm)}" if tm
                                              else ""), m)
            break
    m = _QUESTIONS_REL.search(t)
    if m:
        n = int(m.group(1) or m.group(2) or _WORDS[m.group(3).lower()])
        kind = (m.group(4) or "").strip()
        put("questions_due", f"{n} {kind + ' ' if kind else ''}"
            "days before bid opening", m)
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


def parse_day(text):
    """'December 17th, 2026, 2:00 P.M.' / '12/17/2026' -> date, or None."""
    m = re.search(r"([A-Za-z]+)\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})",
                  text or "")
    if m:
        for fmt in ("%B %d %Y", "%b %d %Y"):
            try:
                return datetime.datetime.strptime(
                    f"{m.group(1)[:3] if fmt == '%b %d %Y' else m.group(1)} "
                    f"{m.group(2)} {m.group(3)}", fmt).date()
            except ValueError:
                pass
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b", text or "")
    if m:
        y = int(m.group(3))
        y += 2000 if y < 100 else 0
        try:
            return datetime.date(y, int(m.group(1)), int(m.group(2)))
        except ValueError:
            return None
    return None


def _date_questions(cands):
    """'7 days before bid opening' + the bid date -> the actual last day
    (working / business days skip weekends)."""
    bids = cands.get("bid_date") or []
    if not bids:
        return
    best = max(bids, key=lambda x: (x[2], -(x[1] if x[1] is not None
                                            else 10 ** 6)))
    day = parse_day(best[0])
    if day is None:
        return
    out = []
    for v, pg, a, sn in cands.get("questions_due") or []:
        m = re.match(r"(\d+) (?:(calendar|working|business) )?days before "
                     r"bid opening$", v)
        if m:
            n = int(m.group(1))
            if m.group(2) in ("working", "business"):
                d, left = day, n
                while left:
                    d -= datetime.timedelta(days=1)
                    if d.weekday() < 5:
                        left -= 1
            else:
                d = day - datetime.timedelta(days=n)
            v = f"{d.strftime('%B')} {d.day}, {d.year} ({v})"
        out.append((v, pg, a, sn))
    if out:
        cands["questions_due"] = out


def _same(v):
    """'$500.00 per day' and '$500 per day' are one answer."""
    v = str(v).lower().replace(",", "")
    v = re.sub(r"(\d)\.00\b", r"\1", v)
    return re.sub(r"\s+", " ", v).strip()


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
    _date_questions(cands)
    if not cands.get("final") and cands.get("contract_time"):
        cands["final"] = [(f"{v} (contract time - final completion not "
                           "stated separately)", pg, a, sn)
                          for v, pg, a, sn in cands["contract_time"]]
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
            seen = {_same(best[0])}
            for v, pg, _a, _s in c:
                if _same(v) not in seen:
                    seen.add(_same(v))
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
    m = re.match(r"\s*(\d{1,4})\s+(?:(calendar|working)\s+)?days", value or "")
    return (int(m.group(1)), m.group(2) or "calendar") if m else None


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


# ------------------------------------------------- local-AI summary (Nov 21)
AI_CHARS = 6000


def ai_source(doc, rows):
    """The text the local AI is asked to summarize: the page the summary
    answer came from, then the first pages (the invitation and
    instructions), up to AI_CHARS."""
    pages = []
    for r in rows:
        if r["key"] == "summary" and r["page"] is not None:
            pages.append(r["page"])
    pages += [p for p in range(min(12, doc.page_count)) if p not in pages]
    out, n = [], 0
    for p in pages:
        t = re.sub(r"\s+", " ", doc[p].get_text() or "").strip()
        if not t:
            continue
        out.append(f"[page {p + 1}] {t}")
        n += len(t)
        if n >= AI_CHARS:
            break
    return "\n".join(out)[:AI_CHARS]


def ai_prompt(source):
    return ("You are helping a construction estimator. From the bid "
            "documents text below, write a plain summary of the project's "
            "scope of work in 3 to 5 sentences: what is being built or "
            "replaced, where, and the main trades or systems. Use only what "
            "the text says. Do not give any dollar amounts, dates or "
            "numbers that are not in the text, and do not guess. If the "
            "text does not describe the work, say so.\n\nTEXT:\n" + source)


def ai_summary(doc, rows, ask=None):
    """A short scope summary from the local AI (Ollama on this PC -
    nothing leaves the PC). `ask(prompt) -> text` for tests."""
    from .ai import review
    prompt = ai_prompt(ai_source(doc, rows))
    if ask is None:
        def ask(pr):
            return review.stream(pr, num_ctx=4096, num_predict=260)
    return re.sub(r"\s+", " ", ask(prompt) or "").strip()


def with_ai_summary(rows, text):
    """The rows with the AI summary added (or replaced) after the
    pattern-read summary."""
    rows = [r for r in rows if r["key"] != "ai_summary"]
    row = {"key": "ai_summary", "label": "6. Summary (local AI)",
           "value": text, "page": None, "section": "",
           "text": "written by the AI on this PC from the first pages - "
                   "check it against the specs", "also": []}
    i = next((n + 1 for n, r in enumerate(rows) if r["key"] == "summary"),
             len(rows))
    return rows[:i] + [row] + rows[i:]


# ------------------------------------------------------- to the Bid Board
# Nov 23 (Jon: both places - "Send to Bid Board" in Project Analysis and
# "Fill From Specs" in the Bid Board's edit window)
_CITY_ST = re.compile(r"([A-Z][A-Za-z.' -]{1,40}),\s*([A-Z]{2})\b(?:\s+\d{5})?")


def _found(rows):
    """key -> row, for the answers that were read from the documents."""
    return {r["key"]: r for r in rows or []
            if r.get("page") is not None and str(r.get("value") or "")}


def _mandatory(text):
    t = (text or "").lower()
    if re.search(r"\b(?:non[\s-]*mandatory|optional|not\s+mandatory|"
                 r"not\s+required)\b", t):
        return "No"
    if re.search(r"\b(?:mandatory|required)\b", t):
        return "Yes"
    return ""


def bidboard_fields(rows, source=""):
    """The Bid Board fields these answers fill: project, address, city
    and state, bid due date and time, job walk, pre-bid mandatory,
    questions due, the specs' own scope summary, and the file name.
    Only what was found; dates as YYYY-MM-DD."""
    got = _found(rows)
    out = {}

    def val(key):
        return str(got[key]["value"]).strip() if key in got else ""

    if val("project_name"):
        out["project"] = val("project_name")
    if val("address"):
        out["address"] = val("address")
        m = None
        for m in _CITY_ST.finditer(val("address")):
            pass
        if m:
            city = m.group(1).split(",")[-1].strip()
            # "123 Main Street Springfield" -> the words after the street
            city = re.sub(r"^.*\b(?:street|st|avenue|ave|road|rd|drive|dr|"
                          r"boulevard|blvd|lane|ln|way|highway|hwy|parkway|"
                          r"pkwy|court|ct)\.?\s+", "", city, flags=re.I)
            if city and not re.search(r"\d", city):
                out["location"] = f"{city}, {m.group(2)}"
    if val("bid_date"):
        d = parse_day(val("bid_date"))
        if d:
            out["due"] = d.isoformat()
        tm = bidterms._TIME_OF_DAY.search(val("bid_date"))
        if tm:
            out["due_time"] = bidterms._tod(tm)
    if val("prebid"):
        v = val("prebid")
        d = parse_day(v)
        tm = bidterms._TIME_OF_DAY.search(v)
        if d:
            out["job_walk"] = d.isoformat() + (
                " " + bidterms._tod(tm) if tm else "")
        pm = _mandatory(v) or _mandatory(got["prebid"].get("text"))
        if pm:
            out["prebid_mandatory"] = pm
    if val("questions_due"):
        d = parse_day(val("questions_due"))
        if d:
            out["rfi_due"] = d.isoformat()
    if val("summary"):
        out["notes"] = "From the specs: " + val("summary")
    if source:
        out["source"] = str(source)
    return out


def fill_empty(opp, fields):
    """`opp` with `fields` put only where it is empty; and the keys that
    were filled. Nothing typed is replaced."""
    o = dict(opp or {})
    filled = []
    for k, v in (fields or {}).items():
        if v and not str(o.get(k) or "").strip():
            o[k] = v
            filled.append(k)
    return o, filled
