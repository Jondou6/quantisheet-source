"""Manufacturers in the Specs (Nov 20, from the bidding-summit notes:
"pull the approved manufacturers from each spec section into a quote
list"): read a project manual for each section's listed manufacturers
and basis-of-design products, by pattern - no AI, nothing leaves the PC
- each with its page, for a quote-request list by trade.

    find(doc, pages=None) -> [{section, title, manufacturer, kind, page,
                               no_subs}]
        kind "listed" (one of the following...) or "basis" (basis of
        design); no_subs when the section says no substitutions
    to_csv(rows, path)
"""
import csv
import re

_SECTION = re.compile(r"\bSECTION\s+(\d{2}\s?\d{2}\s?\d{2}(?:\.\d{1,2})?)\s*"
                      r"(?:[-–—:]\s*)?\n?\s*([A-Z][A-Z0-9 ,&/'()\-]{2,80})")
_FOOTER = re.compile(r"\b(\d{2} \d{2} \d{2}(?:\.\d{1,2})?)\s*[-–]\s*\d{1,3}\b")
_MFR_HEAD = re.compile(r"\b(?:ACCEPTABLE\s+|APPROVED\s+)?MANUFACTURERS?\b|"
                       r"\bone of the following\b", re.I)
_ITEM = re.compile(r"^\s*(?:\d{1,2}|[a-z])[.)]\s+(.{2,90})$")
_ARTICLE = re.compile(r"^\s*(?:\d\.\d{1,2}\s+[A-Z]|PART\s+\d|END OF SECTION)")
_BASIS = re.compile(r"Basis[- ]of[- ]Design\s+(?:Product|Manufacturer)\s*:\s*"
                    r"(.{3,120}?)(?:\.\s|$)", re.I | re.M)
_NOT_NAME = re.compile(r"^(?:subject to|provide|products?|source|"
                       r"substitution|comply|available|the |a |an |in "
                       r"other|requirements|see |refer|manufacturers?\b)",
                       re.I)
_NO_SUBS = re.compile(r"\bno\s+substitutions?\b", re.I)
_NAME_END = re.compile(r"\s*(?:[;:]|\.\s*$|,\s*or\s+(?:approved\s+)?equal|"
                       r"\s+or\s+(?:approved\s+)?equal).*$", re.I)


def _clean_name(t):
    t = _NAME_END.sub("", t.strip())
    t = re.sub(r"\s{2,}", " ", t).strip(" .,;")
    return t


def _code(c):
    d = re.sub(r"\s", "", c)
    return f"{d[0:2]} {d[2:4]} {d[4:]}"


def find(doc, pages=None):
    rows = []
    cur = ("", "")
    seen = set()
    for p in (range(doc.page_count) if pages is None else pages):
        text = doc[p].get_text() or ""
        m = _SECTION.search(text)
        if m:
            cur = (_code(m.group(1)), m.group(2).strip().title())
        else:
            f = _FOOTER.search(text)
            if f and _code(f.group(1)) != cur[0]:
                cur = (_code(f.group(1)), "")
        no_subs = bool(_NO_SUBS.search(text))
        lines = text.splitlines()
        i = 0
        while i < len(lines):
            if _MFR_HEAD.search(lines[i]):
                j = i + 1
                got = 0
                while j < len(lines) and got < 15:
                    ln = lines[j]
                    if _ARTICLE.match(ln) and j > i + 1:
                        break
                    im = _ITEM.match(ln)
                    if im:
                        name = _clean_name(im.group(1))
                        if name and not _NOT_NAME.match(name) and \
                                len(name.split()) <= 8 and \
                                any(ch.isupper() for ch in name):
                            key = (cur[0], name.lower())
                            if key not in seen:
                                seen.add(key)
                                rows.append({"section": cur[0],
                                             "title": cur[1],
                                             "manufacturer": name,
                                             "kind": "listed", "page": p,
                                             "no_subs": no_subs})
                            got += 1
                    j += 1
                i = j
                continue
            i += 1
        for b in _BASIS.finditer(text):
            name = _clean_name(b.group(1))
            key = (cur[0], name.lower())
            if name and key not in seen:
                seen.add(key)
                rows.append({"section": cur[0], "title": cur[1],
                             "manufacturer": name, "kind": "basis",
                             "page": p, "no_subs": no_subs})
    return rows


def to_csv(rows, path):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Section", "Title", "Manufacturer / product",
                    "Listed as", "Page", "No substitutions"])
        for r in rows:
            w.writerow([r["section"], r["title"], r["manufacturer"],
                        "basis of design" if r["kind"] == "basis" else
                        "listed", r["page"] + 1,
                        "yes" if r["no_subs"] else ""])
    return path
