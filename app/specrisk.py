"""Spec Book Risk Scanner (Nov 3, Jon approved Chief's list, #9): read a
project manual section by section and pull the costly terms onto one
page - bond percentages, liquidated damages, prevailing wage, insurance
limits, warranties beyond the usual year and testing / inspection the
contractor pays for. Pattern based, no AI; every hit shows its section,
page and the words it was found in. (Retainage and notice terms are kept
in Project > Contract Terms and are not repeated here.)"""
import re

KINDS = {
    "bond": "Bonds",
    "ld": "Liquidated damages",
    "wage": "Prevailing wage",
    "insurance": "Insurance limits",
    "warranty": "Warranties",
    "testing": "Testing and inspection",
}
_MONEY = r"\$\s?[\d,]+(?:\.\d{2})?"
PATTERNS = [
    ("bond", re.compile(r"\b(bid|performance(?:\s+and\s+payment)?|payment|"
                        r"labor and material)\s+"
                        r"bonds?\b[^.]{0,120}?\b(\d{1,3}(?:\.\d+)?)\s*"
                        r"(?:%|percent)", re.I)),
    ("bond", re.compile(r"\b(\d{1,3}(?:\.\d+)?)\s*(?:%|percent)\s+(?:of\s+"
                        r"the\s+)?(?:bid|contract)\s+(?:amount|sum|price)?"
                        r"[^.]{0,40}\b(bid|performance|payment)\s+bond",
                        re.I)),
    ("ld", re.compile(r"liquidated\s+damages[^.]{0,160}?(" + _MONEY +
                      r")\s*(?:per|for each|a|/)\s*(?:calendar\s+|working\s+"
                      r")?day", re.I)),
    ("ld", re.compile(r"(" + _MONEY + r")\s*(?:per|for each)\s*(?:calendar"
                      r"\s+|working\s+)?day[^.]{0,80}liquidated", re.I)),
    ("wage", re.compile(r"\b(prevailing\s+wages?|davis[- ]bacon|"
                        r"wage\s+(?:rate\s+)?determination)\b", re.I)),
    ("insurance", re.compile(r"(" + _MONEY + r")\s*(?:each|per)\s+"
                             r"(occurrence|claim|accident|person)", re.I)),
    ("insurance", re.compile(r"(umbrella|excess)\s+liability[^.]{0,80}?(" +
                             _MONEY + r")", re.I)),
    ("warranty", re.compile(r"\b(\w+|\d{1,2})\s*(?:\(\d{1,2}\)\s*)?[- ]?"
                            r"years?\s+(?:special\s+|extended\s+|"
                            r"manufacturer'?s?\s+)?warrant(?:y|ies)\b",
                            re.I)),
    ("warranty", re.compile(r"(?:special|extended)\s+warrant(?:y|ies)\W"
                            r"[^.]{0,30}?\b(\w+|\d{1,2})\s*(?:\(\d{1,2}\)\s*)?"
                            r"years?", re.I)),
    ("warranty", re.compile(r"warranty\s+period[^.]{0,30}?\b(\w+|\d{1,2})\s*"
                            r"(?:\(\d{1,2}\)\s*)?years?", re.I)),
    ("testing", re.compile(r"\b(contractor\s+shall\s+(?:pay|engage|employ|"
                           r"retain)[^.]{0,60}(?:testing|inspection)|"
                           r"special\s+inspections?|testing\s+agency\s+"
                           r"(?:shall\s+be\s+)?(?:paid|engaged|retained)\s+"
                           r"by\s+the\s+contractor)", re.I)),
]
_NUM_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
              "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
              "fifteen": 15, "twenty": 20}


def _years(w):
    w = str(w).lower()
    if w.isdigit():
        return int(w)
    return _NUM_WORDS.get(w)


def _snippet(text, m, pad=60):
    a, b = max(0, m.start() - pad), min(len(text), m.end() + pad)
    return ("..." if a else "") + " ".join(text[a:b].split()) + \
        ("..." if b < len(text) else "")


def scan_pages(pages, sections=None):
    """pages: [text per page]; sections: specs.find_sections output.
    Returns [{"kind", "label", "value", "section", "page", "quote"}],
    one per distinct (kind, value, section)."""
    sec_of = {}
    for s in sections or []:
        for p in range(s["start"], s["end"] + 1):
            sec_of.setdefault(p, f"{s['number']} {s['title']}".strip())
    out, seen = [], set()
    for pno, raw in enumerate(pages):
        text = " ".join(str(raw or "").split())
        for kind, rx in PATTERNS:
            for m in rx.finditer(text):
                if kind == "bond":
                    g = m.groups()
                    pct = g[1] if not g[0][0].isdigit() else g[0]
                    what = g[0] if not g[0][0].isdigit() else g[1]
                    value = f"{what[:1].upper()}{what[1:].lower()} bond {pct}%"
                elif kind == "ld":
                    value = f"{m.group(1).replace(' ', '')} per day"
                elif kind == "wage":
                    value = "Prevailing wage / wage determination"
                elif kind == "insurance":
                    g = m.groups()
                    value = (f"{g[0].replace(' ', '')} each {g[1].lower()}"
                             if g[0].startswith("$") else
                             f"{g[0].title()} liability {g[1]}")
                elif kind == "warranty":
                    y = _years(m.group(1))
                    if not y or y <= 1:
                        continue          # the usual one-year is no risk
                    value = f"{y}-year warranty"
                else:
                    value = "Testing / inspection by the contractor"
                sec = sec_of.get(pno, "")
                key = (kind, value, sec)
                if key in seen:
                    continue
                seen.add(key)
                out.append({"kind": kind, "label": KINDS[kind],
                            "value": value, "section": sec, "page": pno,
                            "quote": _snippet(text, m)})
    order = list(KINDS)
    return sorted(out, key=lambda r: (order.index(r["kind"]), r["page"]))


def scan(doc, progress=None):
    from . import specs
    pages = [pg.get_text("text") for pg in doc]
    try:
        secs = specs.find_sections(doc)
    except Exception:                                     # noqa: BLE001
        secs = []
    return scan_pages(pages, secs)


def summary_pdf(found, path, project=""):
    """The one-page (or more) risk summary."""
    import fitz
    out = fitz.open()
    cur = [out.new_page(width=612, height=792)]
    y = [50]

    def line(text, size=9, bold=False, indent=0):
        if y[0] > 750:
            cur[0] = out.new_page(width=612, height=792)
            y[0] = 50
        cur[0].insert_text((36 + indent, y[0]), text[:110],
                                   fontsize=size,
                                   fontname="hebo" if bold else "helv")
        y[0] += size + 5
    line("SPEC BOOK RISK SUMMARY" + (f" - {project}" if project else ""), 14,
         True)
    y[0] += 6
    if not found:
        line("No bonds, liquidated damages, prevailing wage, insurance "
             "limits, long warranties or contractor-paid testing found.")
    for kind, label in KINDS.items():
        rows = [r for r in found if r["kind"] == kind]
        if not rows:
            continue
        y[0] += 4
        line(label, 11, True)
        for r in rows:
            line(f"{r['value']}  -  {r['section'] or 'no section'}, page "
                 f"{r['page'] + 1}", 9, False, 8)
            line(r["quote"][:105], 7, False, 16)
    out.save(path)
    return path


# ---- Bid Form & Insurance Review PDF (Nov 4, Jon) ------------------------------
# The Spec Book Risk Scanner also pulls the insurance requirements and the
# builder's risk requirements out of the book into their own PDF for
# review: the pages themselves, copied whole, behind a cover page saying
# what was found where. The bid form leads (its items feed the Bid Form
# Workbook - bidform_xl.py).

REVIEW_KINDS = {"bid_form": "Bid form",
                "insurance": "Insurance requirements",
                "builders_risk": "Builder's risk requirements"}
_INS_TITLE = re.compile(r"\binsurance\b", re.I)
_CONDITIONS = re.compile(r"general\s+conditions|supplementary\s+conditions|"
                         r"special\s+conditions", re.I)
_INS_HEAD = re.compile(r"^\s*(?:article\s+\d+[\s.:-]*|\d{1,2}\.\d{0,2}\s+)?"
                       r"(?:contractor'?s\s+)?(?:bonds\s+and\s+)?insurance"
                       r"(?:\s+and\s+bonds)?(?:\s+requirements)?\s*$", re.I)
_ARTICLE = re.compile(r"^\s*article\s+\d+\b", re.I)
_BR = re.compile(r"builder'?s'?\s*risk|property\s+insurance|installation\s+"
                 r"floater", re.I)
_DEDUCT = re.compile(r"deductible[^.]{0,80}?(\$\s?[\d,]+(?:\.\d{2})?)", re.I)
MAX_ARTICLE_PAGES = 12


def _runs(pages):
    """[1, 2, 3, 7, 8] -> [(1, 3), (7, 8)]"""
    out = []
    for p in sorted(set(pages)):
        if out and p == out[-1][1] + 1:
            out[-1] = (out[-1][0], p)
        else:
            out.append((p, p))
    return out


def review_items(pages, sections=None):
    """What goes in the review PDF: [{"kind", "label", "pages": [..],
    "where": "00 73 16 Insurance Requirements", "terms": [..]}], plus a
    {"kind", "label", "missing": True} entry for anything not found.
    `pages` is the text of each page; `sections` from specs."""
    sections = sections or []
    sec_of = {}
    for s in sections:
        for p in range(s["start"], s["end"] + 1):
            sec_of.setdefault(p, f"{s['number']} {s['title']}".strip())
    ins = set()
    # 1. whole insurance sections (00 73 16 Insurance Requirements ...)
    for s in sections:
        if _INS_TITLE.search(s.get("title", "")):
            ins.update(range(s["start"], s["end"] + 1))
    # 2. the insurance article of the General / Supplementary Conditions
    for s in sections:
        if not _CONDITIONS.search(s.get("title", "")):
            continue
        p = s["start"]
        while p <= s["end"]:
            lines = str(pages[p] or "").splitlines()
            if any(_INS_HEAD.match(ln.strip()) for ln in lines):
                q = p
                while q < min(s["end"], p + MAX_ARTICLE_PAGES - 1):
                    nxt = str(pages[q + 1] or "").splitlines()
                    heads = [ln for ln in nxt if _ARTICLE.match(ln)]
                    if heads and not any(_INS_TITLE.search(h) or
                                         _BR.search(h) for h in heads):
                        break
                    q += 1
                ins.update(range(p, q + 1))
                p = q + 1
            else:
                p += 1
    if not sections:              # no sections read: pages that say so
        for i, t in enumerate(pages):
            if any(_INS_HEAD.match(ln.strip()) for ln in
                   str(t or "").splitlines()):
                ins.add(i)
    br = {i for i, t in enumerate(pages) if _BR.search(str(t or ""))}
    from . import bidform_xl
    bf = set()
    for s in sections:
        if bidform_xl.HEAD.search(s.get("title", "")) or \
                str(s.get("number", "")).startswith("00 41"):
            bf.update(range(s["start"], s["end"] + 1))
    if not bf:
        bf = {i for i, t in enumerate(pages) if bidform_xl.HEAD.search(
            "\n".join(str(t or "").splitlines()[:12]))}
    out = []
    for kind, pgs in (("bid_form", bf), ("insurance", ins),
                      ("builders_risk", br)):
        label = REVIEW_KINDS[kind]
        if not pgs:
            out.append({"kind": kind, "label": label, "missing": True})
            continue
        for a, b in _runs(pgs):
            txt = " ".join(str(pages[i] or "") for i in range(a, b + 1))
            terms = [r["value"] for r in scan_pages([txt])
                     if r["kind"] in ("insurance", "bond")]
            if kind == "bid_form":
                f = bidform_xl.parse([pages[i] for i in range(a, b + 1)])
                terms = [f"{len(f['items'])} bid item(s)",
                         f"{len(f['alternates'])} alternate(s)"]
            if kind == "builders_risk":
                terms += [f"Deductible {m.group(1).replace(' ', '')}"
                          for m in _DEDUCT.finditer(" ".join(txt.split()))]
            out.append({"kind": kind, "label": label,
                        "pages": list(range(a, b + 1)),
                        "where": sec_of.get(a, ""),
                        "terms": list(dict.fromkeys(terms))[:8]})
    return out


def review_pdf(doc, items, path, project=""):
    """The review PDF: a cover page saying what was found where, then the
    pages themselves, copied whole, bookmarked by item. Returns path."""
    import fitz
    out = fitz.open()
    cover = out.new_page(width=612, height=792)
    y = [50]

    def line(text, size=9, bold=False, indent=0, color=(0, 0, 0)):
        cover.insert_text((36 + indent, y[0]), text[:105], fontsize=size,
                          fontname="hebo" if bold else "helv", color=color)
        y[0] += size + 5
    line("BID FORM & INSURANCE REVIEW" + (f" - {project}" if project
                                          else ""), 14, True)
    line("Pages copied whole from the spec book for review. Check every "
         "requirement against the book.", 8)
    y[0] += 6
    toc, start = [], 2
    for it in items:
        if y[0] > 740:
            break
        if it.get("missing"):
            line(f"{it['label']}: NOT FOUND in this spec book - ask for it "
                 "or check the bid documents.", 9, True, 0, (0.75, 0.1, 0.1))
            continue
        pg = it["pages"]
        rng = f"page {pg[0] + 1}" if len(pg) == 1 else \
            f"pages {pg[0] + 1}-{pg[-1] + 1}"
        line(f"{it['label']}: {it['where'] or 'spec book'}, {rng} (review "
             f"page {start})", 10, True)
        for t in it["terms"]:
            line("- " + t, 9, False, 14)
        toc.append([1, f"{it['label']} - {it['where'] or rng}", start])
        start += len(pg)
    for it in items:
        if it.get("missing"):
            continue
        out.insert_pdf(doc, from_page=it["pages"][0],
                       to_page=it["pages"][-1], annots=False)
    if toc:
        out.set_toc([[1, "What was found", 1]] + toc)
    out.save(path, garbage=3, deflate=True)
    out.close()
    return path


def review_for(doc, path, project=""):
    """Find the items in `doc` and write the review PDF to `path`.
    Returns the items."""
    from . import specs
    pages = [pg.get_text("text") for pg in doc]
    try:
        secs = specs.find_sections(doc)
    except Exception:                                     # noqa: BLE001
        secs = []
    items = review_items(pages, secs)
    review_pdf(doc, items, path, project)
    return items
