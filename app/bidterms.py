"""Find Bid Terms (Nov 19): the terms a bidder screens a job on, read
from the bid documents by pattern - no AI, nothing leaves the PC - each
with the page it was found on so it can be checked:

    bid bond %, how long the bid must hold, prevailing wage, liquidated
    damages, a mandatory pre-bid meeting, DBE/MBE/SBE goals, retainage,
    contract time, alternates.

    find(doc, pages=None) -> [{key, label, value, page, text}]
    hold_days(found) -> int or None   for the Bid Submittal Checklist
"""
import re

# Project Spec Analysis (Nov 20, Jon): his nine questions first, in his
# order, then the other bid terms
ANALYSIS = (("project_name", "1. Project name"),
            ("address", "2. Project address"),
            ("budget", "3. Project value (budget)"),
            ("substantial", "4. Duration - substantial completion"),
            ("final", "4. Duration - final completion"),
            ("ld_value", "5. Liquidated damages"),
            ("summary", "6. Project summary / description"),
            ("bid_date", "7. Bid date"),
            ("prebid", "8. Pre-bid meeting"),
            ("retainage", "9. Retainage"))
NOT_FOUND = {"budget": "not listed", "summary": "not found - see Section "
             "01 10 00 Summary"}
LABELS = (("bid_bond", "Bid bond / bid security"),
          ("hold_days", "Bid must hold (days)"),
          ("prevailing_wage", "Prevailing wage"),
          ("liquidated", "Liquidated damages"),
          ("prebid", "Pre-bid meeting"),
          ("goals", "DBE / MBE / SBE goal"),
          ("retainage", "Retainage"),
          ("contract_time", "Contract time"),
          ("alternates", "Alternates"))
LABEL = dict(LABELS)
LABEL.update(ANALYSIS)
_MONEY = (r"(\$\s?[\d,]+(?:\.\d{1,2})?(?:\s*(?:million|M)\b)?|"
          r"[\d,]+(?:\.\d{1,2})?\s*(?:million\s+)?dollars)")
_NEXT_LABEL = (r"(?=\s+(?:Project\s+\w+|Location|Address|Owner|Architect|"
               r"Engineer|Bid\s+\w+|Date|Contract\s+\w+)\s*:|\s{2,}|\n|$)")
_NAME = re.compile(r"\bProject(?:\s+(?:Name|Title))?\s*:\s*(.{4,120}?)" +
                   _NEXT_LABEL, re.I)
_ADDR = re.compile(r"\b(?:Project\s+(?:Address|Location|Site)|Site\s+"
                   r"Address|Location)\s*:\s*(.{6,140}?)" + _NEXT_LABEL,
                   re.I)
_ADDR2 = re.compile(r"\b(?:located\s+at|at\s+the\s+site\s+of)\s+"
                    r"(\d{1,6}\s+[A-Za-z0-9 .'-]{3,80}?(?:,\s*[A-Za-z .'-]+){1,3}"
                    r"(?:\s+\d{5})?)(?=[.;,\n]|\s{2,}|$)")
_RANGE_WORDS = re.compile(r"\bbetween\s+\$?\s?([\d,.]+)\s*(?:million\s+)?"
                          r"(?:dollars\s+)?and\s+\$?\s?([\d,.]+)\s*(million)?"
                          r"\s*(?:dollars)?", re.I)
_BUDGET = re.compile(r"\b(?:estimated\s+(?:construction\s+|project\s+)?"
                     r"(?:cost|value|budget)|project\s+(?:budget|value)|"
                     r"construction\s+budget|engineer'?s\s+estimate|cost\s+"
                     r"range|budget\s+range|estimated\s+range)\b[^.;]{0,80}?"
                     + _MONEY + r"(?:\s*(?:-|to|and)\s*" + _MONEY + r")?",
                     re.I)
_SUBST = re.compile(r"\bsubstantial(?:ly)?\s+complet\w*\b[^.;]{0,120}?\(?\b"
                    r"(\d{2,4})\)?\s*(?:\(\d+\)\s*)?(?:consecutive\s+)?"
                    r"(calendar|working)\s+days\b", re.I)
_FINAL = re.compile(r"\bfinal(?:ly)?\s+complet\w*\b[^.;]{0,120}?\(?\b"
                    r"(\d{2,4})\)?\s*(?:\(\d+\)\s*)?(?:consecutive\s+)?"
                    r"(calendar|working)\s+days\b", re.I)
_LDV = re.compile(r"\bliquidated\s+damages\b[^.]{0,220}?" + _MONEY +
                  r"[^.]{0,60}?\b(?:per|each|for\s+each|a)\s+(?:calendar\s+|"
                  r"working\s+|consecutive\s+)?(day|week)", re.I)
_SUMMARY = re.compile(r"\b(?:SUMMARY\s+OF\s+(?:THE\s+)?WORK|PROJECT\s+"
                      r"DESCRIPTION|WORK\s+COVERED\s+BY\s+CONTRACT\s+"
                      r"DOCUMENTS|DESCRIPTION\s+OF\s+(?:THE\s+)?WORK|"
                      r"SCOPE\s+OF\s+(?:THE\s+)?WORK)\b\s*[:.]?\s*(?:A\.\s*)?"
                      r"(.{30,600}?[.])(?=\s|$)", re.I | re.S)
_BIDDATE = re.compile(r"\b(?:(?:sealed\s+)?(?:bids|proposals)\s+(?:will|shall)"
                      r"\s+be\s+received|bid\s+(?:date|opening|due(?:\s+date)?|"
                      r"deadline)|(?:bids|proposals)\s+(?:are\s+)?due|until)\b"
                      r"[^.]{0,160}?", re.I)
def _tod(m):
    """'5:00 PM.' (end of a sentence) -> '5:00 PM'; 'p.m.' kept."""
    t = m.group()
    return t[:-1] if t.endswith(".") and t.count(".") == 1 else t


_TIME_OF_DAY = re.compile(r"\b\d{1,2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?)",
                          re.I)
_PCT = r"(\d{1,2}(?:\.\d{1,2})?)\s*(?:%|percent\b)"
_BOND = [re.compile(r"\bbid\s+(?:bond|security|guarant(?:y|ee))\b[^.;]{0,140}?"
                    + _PCT, re.I),
         re.compile(_PCT + r"\s+of\s+the\s+(?:total\s+)?(?:amount\s+of\s+"
                    r"the\s+)?(?:base\s+)?bid\b", re.I)]
_HOLD = [re.compile(r"\b(?:withdraw\w*|remain\s+(?:open|valid|in\s+effect|"
                    r"firm)|irrevocable|binding|held\s+open|subject\s+to\s+"
                    r"acceptance)\b[^.;]{0,100}?\(?\b(\d{2,3})\)?\s*"
                    r"(?:\(\d+\)\s*)?(?:calendar\s+|consecutive\s+)?days\b",
                    re.I)]
_WAGE = re.compile(r"\b(prevailing\s+wage\w*|davis[\s-]+bacon|wage\s+"
                   r"determination)\b", re.I)
_LD = re.compile(r"\bliquidated\s+damages\b", re.I)
_PREBID = re.compile(r"\b(mandatory|non[\s-]*mandatory|optional)\b[^.;]{0,30}?"
                     r"\bpre[\s-]*(?:bid|proposal)\b", re.I)
_GOAL = re.compile(r"\b(DBE|MBE|WBE|SBE|SLBE|M/WBE|MWBE|DBE/MBE|HUB)\b"
                   r"[^.;]{0,100}?" + _PCT, re.I)
_RET = re.compile(r"\bretain(?:age|ed|ing)?\b[^.;]{0,100}?" + _PCT, re.I)
_TIME = re.compile(r"\b(?:substantial(?:ly)?\s+complet\w*|final(?:ly)?\s+"
                   r"complet\w*|complete[ds]?|contract\s+time)\b[^.;]{0,100}?\(?\b(\d{2,4})\)?\s*(?:\(\d+\)\s*)?"
                   r"(?:consecutive\s+)?(?:calendar|working)\s+days\b", re.I)
_ALT = re.compile(r"\b(?:add(?:itive)?\s+|deduct(?:ive)?\s+)?alternate\s+"
                  r"(?:no\.?\s*|number\s+|#\s*)?(\d{1,2})\b", re.I)
_DATE = re.compile(r"\b(?:\d{1,2}/\d{1,2}/\d{2,4}|(?:jan|feb|mar|apr|may|jun|"
                   r"jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4})",
                   re.I)


def _snip(t, m, pad=70):
    a, b = max(0, m.start() - pad), min(len(t), m.end() + pad)
    return ("..." if a else "") + t[a:b].strip() + ("..." if b < len(t)
                                                    else "")


def _page_text(page):
    return re.sub(r"\s+", " ", page.get_text() or "")


def find(doc, pages=None, extra=False):
    """The terms found, first place each is stated (alternates: all of
    them, counted). Every value is as printed, to be checked. `extra`
    adds the Project Spec Analysis items (name, address, budget,
    completion times, LD amount, summary, bid date)."""
    found = {}
    alts = {}
    for p in (range(doc.page_count) if pages is None else pages):
        t = _page_text(doc[p])
        if not t.strip():
            continue

        def put(key, value, m):
            if key not in found:
                found[key] = {"key": key, "label": LABEL[key],
                              "value": value, "page": p,
                              "text": _snip(t, m)}
        for rx in _BOND:
            m = rx.search(t)
            if m:
                put("bid_bond", f"{float(m.group(1)):g}% of the bid", m)
                break
        for rx in _HOLD:
            for m in rx.finditer(t):
                n = int(m.group(1))
                if 30 <= n <= 365:
                    put("hold_days", f"{n} days", m)
                    break
        m = _WAGE.search(t)
        if m:
            put("prevailing_wage", "required (" + m.group(1).strip() + ")",
                m)
        m = _LD.search(t)
        if m:
            put("liquidated", "stated - read the terms", m)
        m = _PREBID.search(t)
        if m:
            kind = re.sub(r"[\s-]+", "-", m.group(1).lower())
            d = _DATE.search(t, m.end(), m.end() + 160)
            tm = _TIME_OF_DAY.search(t, m.end(), m.end() + 200)
            put("prebid", kind + (f", {d.group()}" if d else "") +
                (f" at {_tod(tm)}" if tm and d else ""), m)
        if "project_name" not in found:
            m = _NAME.search(t)
            if m and not re.match(r"(?:manual|no\.?|number|#)", m.group(1),
                                  re.I):
                put("project_name", m.group(1).strip(" .,;"), m)
        if "address" not in found:
            m = _ADDR.search(t) or _ADDR2.search(t)
            if m:
                put("address", m.group(1).strip(" .,;"), m)
        m = _BUDGET.search(t)
        if m:
            rw = _RANGE_WORDS.search(t, m.start(), m.end() + 5)
            if rw:
                unit = " million" if rw.group(3) else ""
                put("budget", f"{rw.group(1)}{unit} to {rw.group(2)}{unit} "
                    "dollars", m)
            else:
                put("budget", m.group(1) + (f" to {m.group(2)}" if
                                            m.group(2) else ""), m)
        m = _SUBST.search(t)
        if m:
            put("substantial", f"{int(m.group(1))} {m.group(2).lower()} "
                "days", m)
        m = _FINAL.search(t)
        if m:
            put("final", f"{int(m.group(1))} {m.group(2).lower()} days", m)
        m = _LDV.search(t)
        if m:
            put("ld_value", f"{m.group(1)} per {m.group(2).lower()}", m)
        if "summary" not in found:
            m = _SUMMARY.search(t)
            if m:
                txt = re.sub(r"\s+", " ", m.group(1)).strip()
                found["summary"] = {"key": "summary",
                                    "label": LABEL["summary"],
                                    "value": txt[:400], "page": p,
                                    "text": txt[:400]}
        if "bid_date" not in found:
            for m in _BIDDATE.finditer(t):
                d = _DATE.search(t, m.start(), m.end() + 120)
                if d:
                    tm = _TIME_OF_DAY.search(t, m.start(), d.end() + 60)
                    put("bid_date", d.group() + (f", {_tod(tm)}" if tm
                                                 else ""), m)
                    break
        m = _GOAL.search(t)
        if m:
            put("goals", f"{m.group(1).upper()} {float(m.group(2)):g}%", m)
        m = _RET.search(t)
        if m:
            put("retainage", f"{float(m.group(1)):g}%", m)
        m = _TIME.search(t)
        if m:
            put("contract_time", f"{int(m.group(1))} days", m)
        for m in _ALT.finditer(t):
            alts.setdefault(int(m.group(1)), (p, _snip(t, m)))
    if alts:
        first = min(alts)
        found["alternates"] = {
            "key": "alternates", "label": LABEL["alternates"],
            "value": f"{len(alts)} (No. " + ", ".join(
                str(n) for n in sorted(alts)) + ")",
            "page": alts[first][0], "text": alts[first][1]}
    keys = [k for k, _ in LABELS] + ([k for k, _ in ANALYSIS if k not in
                                      LABEL_KEYS] if extra else [])
    return [found[k] for k in keys if k in found]


LABEL_KEYS = {k for k, _ in LABELS}


def analysis(doc, pages=None, found=None):
    """Project Spec Analysis: Jon's nine questions in order (a row for
    each, "not found" when the specs don't say), then the other bid
    terms found. Each row {key, label, value, page (None when not
    found), text}."""
    found = find(doc, pages, extra=True) if found is None else found
    by = {f["key"]: f for f in found}
    rows = []
    for key, label in ANALYSIS:
        if key in by:
            rows.append(dict(by[key], label=label))
        else:
            rows.append({"key": key, "label": label,
                         "value": NOT_FOUND.get(key, "not found"),
                         "page": None, "text": ""})
    done = {k for k, _ in ANALYSIS}
    rows += [f for f in found if f["key"] not in done]
    return rows


def looks_like_specs(doc, pages=12):
    """A project manual: its first pages name spec sections or call
    themselves specifications / a project manual."""
    hits = 0
    for p in range(min(pages, doc.page_count)):
        t = doc[p].get_text() or ""
        if re.search(r"\bPROJECT\s+MANUAL\b|\bSPECIFICATIONS\b|"
                     r"\bINVITATION\s+(?:TO|FOR)\s+BID|\bINSTRUCTIONS\s+TO"
                     r"\s+BIDDERS\b", t, re.I):
            hits += 1
        hits += len(re.findall(r"\bSECTION\s+\d{2}\s?\d{2}\s?\d{2}\b", t))
        if hits >= 3:
            return True
    return False


def hold_days(found):
    for f in found:
        if f["key"] == "hold_days":
            return int(f["value"].split()[0])
    return None
