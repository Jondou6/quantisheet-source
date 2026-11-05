"""Batch Link: hyperlink every sheet reference in a drawing set.

Reads each sheet's own number from its title block (app/sheets.py), then
finds references to other sheets on every page - "A-501", detail and
section callouts like "3/A-501" or "A5.01", "SEE S-201" - and turns each
into a link to that sheet. Click a link to jump; Alt+Left comes back.

Links made here can be found again (a GoTo link sitting on a sheet
reference) so running Batch Link again only adds what's new, and
"Remove Sheet Links" takes them all out without touching other links.
"""
import re

import fitz

from . import annotate, sheets

# words that can hold a reference: A-501, A5.01, 3/A-501, A-501.
_STRIP = " ,.;:()[]{}<>\"'"


def norm(number):
    """Sheet numbers compare without dashes, spaces or dots in the
    prefix: A-101 == A101 == a101; A5.01 stays distinct from A501."""
    s = (number or "").upper().strip(_STRIP)
    m = re.match(r"^([A-Z]{1,3})[-.\s]?(.*)$", s)
    if not m:
        return s
    return m.group(1) + m.group(2).replace(" ", "")


def sheet_map(doc, numbers=None):
    """{normalized sheet number: page index}; `numbers` can give the
    pages' numbers ({page: number}) when they're already known."""
    out = {}
    for i in range(doc.page_count):
        num = (numbers or {}).get(i)
        if num is None:
            num = sheets.sheet_info(sheets.page_words(doc[i]),
                                    doc[i].rect.width,
                                    doc[i].rect.height)[0]
        if num and norm(num) not in out:
            out[norm(num)] = i
    return out


def _candidates(word):
    """Possible sheet numbers inside one word, with the part of the word
    each one is (for '3/A-501': 'A-501')."""
    w = word.strip(_STRIP)
    parts = [w]
    if "/" in w:
        parts = [p for p in w.split("/") if p]
    out = []
    for p in parts:
        p = p.strip(_STRIP)
        if sheets.SHEET_NO.match(p):
            out.append(p)
    return out


def find_refs(doc, smap=None):
    """[{page, rect (screen coords), target, number, text}] for every
    reference to another sheet in the set."""
    smap = smap if smap is not None else sheet_map(doc)
    refs = []
    for i in range(doc.page_count):
        page = doc[i]
        own = [k for k, v in smap.items() if v == i]
        words = page.get_text("words")
        for w in words:
            for cand in _candidates(w[4]):
                key = norm(cand)
                target = smap.get(key)
                if target is None or key in own:
                    continue
                r = annotate.from_page(page, fitz.Rect(w[:4]))
                refs.append({"page": i, "rect": r, "target": target,
                             "number": cand, "text": w[4]})
        # two-word references: "SHEET A 501" is rare; "A- 501" happens
        for a, b in zip(words, words[1:]):
            if a[4].endswith("-") and re.fullmatch(r"\d{1,3}(\.\d{1,2})?",
                                                   b[4].strip(_STRIP)):
                cand = a[4] + b[4].strip(_STRIP)
                key = norm(cand)
                target = smap.get(key)
                if target is None or key in own or \
                        not sheets.SHEET_NO.match(cand):
                    continue
                r = annotate.from_page(page, fitz.Rect(a[:4]) |
                                       fitz.Rect(b[:4]))
                refs.append({"page": i, "rect": r, "target": target,
                             "number": cand, "text": cand})
    return refs


def _ours(link, ref_rects):
    if link.get("kind") != fitz.LINK_GOTO:
        return False
    r = fitz.Rect(link["from"])
    return any(abs(r.x0 - q.x0) < 1.5 and abs(r.y0 - q.y0) < 1.5 and
               abs(r.x1 - q.x1) < 1.5 and abs(r.y1 - q.y1) < 1.5
               for q in ref_rects)


def link_all(doc, refs=None):
    """Add a link on every reference that doesn't have one. Returns how
    many links were added."""
    refs = refs if refs is not None else find_refs(doc)
    by_page = {}
    for r in refs:
        by_page.setdefault(r["page"], []).append(r)
    added = 0
    for pno, items in by_page.items():
        page = doc[pno]
        have = [fitz.Rect(ln["from"]) for ln in page.get_links()
                if ln.get("kind") == fitz.LINK_GOTO]
        for it in items:
            r = fitz.Rect(it["rect"])
            if any(abs(r.x0 - q.x0) < 1.5 and abs(r.y0 - q.y0) < 1.5
                   for q in have):
                continue
            page.insert_link({"kind": fitz.LINK_GOTO, "from": r,
                              "page": it["target"], "to": fitz.Point(0, 0),
                              "zoom": 0})
            have.append(r)
            added += 1
    return added


def remove_all(doc, refs=None):
    """Take out the links Batch Link made (other links stay)."""
    refs = refs if refs is not None else find_refs(doc)
    by_page = {}
    for r in refs:
        by_page.setdefault(r["page"], []).append(fitz.Rect(r["rect"]))
    n = 0
    for pno, rects in by_page.items():
        page = doc[pno]
        for ln in page.get_links():
            if _ours(ln, rects):
                page.delete_link(ln)
                n += 1
    return n


def link_at(page, pt):
    """The link under a screen point on `page`, or None."""
    for ln in page.get_links():
        r = fitz.Rect(ln["from"]) + (-1, -1, 1, 1)
        if r.contains(pt):
            return ln
    return None
