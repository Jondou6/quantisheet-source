import logging
import re

from . import annotate

log = logging.getLogger(__name__)

DEFAULT_RULES = [
    {"pattern": r"\bshall\b", "mark": "highlight", "color": [1, 1, 0]},
    {"pattern": r"\bfire rating\b", "mark": "underline", "color": [1, 0, 0]},
    {"pattern": r"\bminimum\b", "mark": "underline", "color": [1, 0.5, 0]},
    {"pattern": r"\bmust\b", "mark": "strike", "color": [1, 0, 0]},
]

MARKS = ["highlight", "underline", "strike", "rect", "ellipse", "cloud"]

NL_TOKENS = {
    "highlight": "highlight", "underline": "underline", "strike": "strike",
    "strikeout": "strike", "box": "rect", "rectangle": "rect",
    "circle": "ellipse", "cloud": "cloud",
}
COLOR_WORDS = {
    "red": [1, 0, 0], "yellow": [1, 1, 0], "green": [0, 0.6, 0],
    "blue": [0, 0, 1], "orange": [1, 0.5, 0], "pink": [1, 0.4, 0.7],
    "purple": [0.5, 0, 0.8],
}


def _has_word(word, text):
    return re.search(rf"\b{re.escape(word)}\b", text) is not None


def parse_nl_rule(text):
    """Turn e.g. "underline every fire rating in red" into a rule.

    Words are matched whole, so "required" no longer means red and
    "install" no longer counts as "all". The phrase found is matched
    literally (it is user text, not a regular expression).
    """
    low = " ".join(text.lower().split())
    mark = next((m for w, m in NL_TOKENS.items() if _has_word(w, low)),
                "highlight")
    color = next((c for w, c in COLOR_WORDS.items() if _has_word(w, low)),
                 [1, 1, 0])
    phrase = None
    m = re.search(r"\b(every|all|any|each|the)\b\s+(.+)", low)
    if m:
        phrase = re.split(r"\s+(?:in|with|using)\s+", m.group(2))[0]
    else:
        words = [w for w in low.split()
                 if w not in NL_TOKENS and w not in COLOR_WORDS
                 and w not in ("in", "with", "word", "words")]
        phrase = " ".join(words)
    phrase = phrase.strip(" .,'\"") or low
    return {"pattern": rf"\b{re.escape(phrase)}\b", "mark": mark,
            "color": color}


def _compile(pattern):
    try:
        return re.compile(pattern, re.IGNORECASE)
    except re.error:
        return re.compile(re.escape(pattern), re.IGNORECASE)


def search_regex(page, pattern, keep=None):
    """Rects of regex matches on a page, one per match, within a text line.

    PyMuPDF's search_for() only takes plain strings; the original code
    passed it a compiled regex, which fails, so auto-markup never worked.
    """
    import fitz
    pat = _compile(pattern) if isinstance(pattern, str) else pattern
    out = []
    raw = page.get_text("rawdict")
    for block in raw.get("blocks", []):
        for line in block.get("lines", []):
            chars = [c for s in line.get("spans", []) for c in s.get("chars", [])]
            text = "".join(c["c"] for c in chars)
            for m in pat.finditer(text):
                if keep is not None and not keep(m.group(0)):
                    continue
                hit = chars[m.start():m.end()]
                if not hit:
                    continue
                r = fitz.Rect(hit[0]["bbox"])
                for c in hit[1:]:
                    r |= fitz.Rect(c["bbox"])
                out.append(r)
    return out


def find_marks(doc, rules=None):
    """List the marks the rules would add: (page, kind, payload) tuples.

    Matches already marked the same way are skipped, so running the rules
    twice does not stack duplicate annotations.
    """
    rules = rules or DEFAULT_RULES
    marks = []
    for pno, page in enumerate(doc):
        for r in rules:
            mark = r.get("mark", "highlight")
            if mark not in MARKS:
                continue
            kind = "add_" + mark
            for rect in search_regex(page, r["pattern"]):
                # character boxes are unrotated, which is what ops use
                if annotate.has_similar(page, kind, rect):
                    continue
                marks.append((pno, kind, {"rect": list(rect),
                                          "color": r.get("color", [1, 1, 0])}))
    return marks


def apply_rules(doc, rules=None):
    """Find and apply marks directly (CLI and tests). Returns the count."""
    n = 0
    for pno, kind, payload in find_marks(doc, rules):
        n += annotate.apply_op(doc, annotate.new_op(kind, pno, **payload))
    return n
