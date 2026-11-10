"""Count by Label with a hit list (Nov 1).

search(doc, text) finds every word (or run of words) on the sheets that
matches `text`, with wildcards for tag families:

    *   any letters        "WH-*"  finds WH-1, WH-2A, WH-10
    ?   one letter         "D?"    finds D1, D2, DA - not D10
    #   a number           "P-#"   finds P-1 ... P-12, not P-1A

Without a wildcard a label is matched whole-word as before ("D1" finds
D1, not D10). Each hit says whether it is on the plan or in the title
block, a schedule, a legend or a notes block (those are listed but not
ticked), so the person sees what will be counted before anything is.
Scanned pages are read with OCR when it is installed.
"""
import re

import fitz

from . import autocount
from . import ocr as ocr_mod
from .dmoney import c2 as _c2

WILD = set("*?#")


def has_wildcard(text):
    return any(ch in WILD for ch in text or "")


def _strip(w):
    return (w or "").strip(".,;:()[]{}\"'").upper()


def word_regex(word):
    """A wildcard word -> compiled regex over the word (upper case, edge
    punctuation removed)."""
    out = []
    for ch in _strip(word):
        if ch == "*":
            out.append(r".*")
        elif ch == "?":
            out.append(r".")
        elif ch == "#":
            out.append(r"\d+")
        else:
            out.append(re.escape(ch))
    return re.compile("^" + "".join(out) + "$")


def matcher(text):
    """A function(list of words) -> bool for `text` (several words: each
    in turn). None when `text` has no letters or digits."""
    parts = [p for p in (text or "").split() if p.strip()]
    if not parts or not any(ch.isalnum() for ch in text):
        return None, 0
    if not has_wildcard(text):
        target = [autocount._norm(p) for p in parts]
        target = [t for t in target if t]
        return (lambda ws: [autocount._norm(w) for w in ws] == target), \
            len(target)
    rx = [word_regex(p) for p in parts]
    return (lambda ws: all(r.match(_strip(w)) for r, w in zip(rx, ws))), \
        len(rx)


def _words_text(page):
    """[(text, rect, line key)] from the page's text layer."""
    return [(w[4], fitz.Rect(w[:4]), (w[5], w[6]))
            for w in page.get_text("words")]


def _words_ocr(page):
    return [(w["text"], fitz.Rect(w["rect"]), None)
            for w in ocr_mod.ocr_words(page)]


def search(doc, text, pages=None, plan_area_only=True, use_ocr=True,
           info=None):
    """[{page, rect, text, in_plan}] for `text`. in_plan False: in the
    title block, a schedule, a legend or notes (plan_area_only), or a
    second view of the same plan. `info` gets "ocr_error" when a scanned
    page couldn't be read."""
    match, n = matcher(text)
    if match is None:
        return []
    out = []
    for pno, page in enumerate(doc):
        if pages is not None and pno not in pages:
            continue
        try:
            if page.get_text().strip():
                words = _words_text(page)
            elif use_ocr:
                words = _words_ocr(page)
            else:
                words = []
        except ocr_mod.OCRUnavailable as e:
            if info is not None:
                info["ocr_error"] = str(e)
            words = []
        found = []
        for i in range(len(words) - n + 1):
            group = words[i:i + n]
            if n > 1 and group[0][2] is not None and \
                    len({g[2] for g in group}) > 1:
                continue                         # not on one line
            if match([g[0] for g in group]):
                r = fitz.Rect(group[0][1])
                for g in group[1:]:
                    r |= g[1]
                found.append((" ".join(_strip(g[0]) for g in group), r))
        if not found:
            continue
        keep = None
        if plan_area_only:
            try:
                kept = autocount._in_plan_area(page, [r for _t, r in found])
                keep = {tuple(_c2(v) for v in r) for r in kept}
            except Exception:                             # noqa: BLE001
                keep = None
        for t, r in found:
            inp = keep is None or tuple(_c2(v) for v in r) in keep
            out.append({"page": pno, "rect": list(r), "text": t,
                        "in_plan": inp})
    return out


def by_text(hits):
    """{matched text: [hits]} in tag order (P-2 before P-10)."""
    def nat(s):
        return [int(x) if x.isdigit() else x for x in re.split(r"(\d+)", s)]
    groups = {}
    for h in hits:
        groups.setdefault(h["text"], []).append(h)
    return {k: groups[k] for k in sorted(groups, key=nat)}


def count_marks(groups, doc, one_item=None):
    """Count marks for the ticked hits: groups {text: [hits]}. one_item: a
    name to count them all under; None: one item per matched text."""
    from . import count_several
    marks = []
    if one_item:
        every = [h for hs in groups.values() for h in hs]
        for h in every:
            h.setdefault("method", "count by label")
        return autocount.count_marks(every, one_item, doc,
                                     count_several.CLASS_COLORS[0])
    for i, (t, hits) in enumerate(groups.items()):
        if not hits:
            continue
        name = t
        col = count_several.CLASS_COLORS[i % len(count_several.CLASS_COLORS)]
        for h in hits:
            h.setdefault("method", "count by label")
        marks += autocount.count_marks(hits, name, doc, col)
    return marks
