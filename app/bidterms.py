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


def find(doc, pages=None):
    """The terms found, first place each is stated (alternates: all of
    them, counted). Every value is as printed, to be checked."""
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
            put("prebid", kind + (f", {d.group()}" if d else ""), m)
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
    return [found[k] for k, _ in LABELS if k in found]


def hold_days(found):
    for f in found:
        if f["key"] == "hold_days":
            return int(f["value"].split()[0])
    return None
