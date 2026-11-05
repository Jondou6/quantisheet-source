"""Spec books (project manuals): find every CSI section, bookmark them by
division, and split the book into one PDF per section.

A section starts at its own heading near the top of a page - "SECTION 03
30 00 - CAST-IN-PLACE CONCRETE", "SECTION 033000", "Section 03300 - Cast
Stone", "DOCUMENT 00 11 13 - INVITATION TO BID" - or right after the
previous section's "END OF SECTION" on the same page, and runs to its own
"END OF SECTION" (or the page before the next section when a book doesn't
print the end markers).

Cross references are not headings (phase 2: Aiken, Colleton): 'Section
031000 "Concrete Forming and Accessories" for ...' quoted near the top of
a page, '31 20 00 "Earth Moving."' inside Site Clearing, a table of
contents page listing many sections. A number already listed isn't listed
again (03 30 00 came twice on Aiken: the real section and a quoted copy
on p544).
"""
import os
import re

from . import csi
from . import safeio

_NUM6 = r"(\d{2})\s?(\d{2})\s?(\d{2})(?:\.(\d{2}))?(?![\d.])"
_START = re.compile(r"^\s*(SECTION|DOCUMENT)\s+" + _NUM6 +
                    r"\s*([-–—:])?\s*(.*)$", re.I)
_START5 = re.compile(r"^\s*(SECTION|DOCUMENT)\s+(\d{2})(\d{3})(?![\d.])"
                     r"\s*([-–—:])?\s*(.*)$", re.I)
# the keyword on a line of its own, its number on the next
_KEY_ONLY = re.compile(r"^\s*(SECTION|DOCUMENT)\s*$")
_NUM_LINE = re.compile(r"^\s*" + _NUM6 + r"\s*([-–—:])?\s*(.*)$")
_END = re.compile(r"^\s*END\s+OF\s+(?:SECTION|DOCUMENT)\b", re.I)
_PART = re.compile(r"^\s*PART\s+(?:[1-3]|I{1,3})\b", re.I)
_QUOTES = '"“”'
TOP_FRAC, TOP_LINES = 0.35, 10


def _number(m, five=False):
    if five:
        a, b = m.group(2), m.group(3)
        return f"{a} {b[:2]} {b[2]}0"
    n = f"{m.group(2)} {m.group(3)} {m.group(4)}"
    return n + (f".{m.group(5)}" if m.group(5) else "")


def _caps(s):
    letters = [c for c in s if c.isalpha()]
    return bool(letters) and \
        sum(c.isupper() for c in letters) >= 0.8 * len(letters)


def _good_title(title, strict):
    """A section title, not the rest of a sentence citing the section."""
    if not title:
        return True                      # title on the next line
    if any(q in title for q in _QUOTES):
        return False                     # Section 031000 "Concrete ..."
    if title.rstrip().endswith((".", ",", ";")) and not _caps(title):
        return False
    if strict:
        return True
    # "Section 26 05 19 - Low-Voltage Conductors" (a title-case heading)
    # vs "Section 079200 - Joint Sealants: Perimeter sealants ..."
    return ":" not in title and len(title.split()) <= 10 and \
        not title.rstrip().endswith((".", ","))


def heading(line, nxt=()):
    """(number, title) when `line` is a section's own heading, else None.
    `nxt`: the lines after it, for a title (or number) on the next line."""
    m = _START.match(line)
    five = False
    if not m:
        m = _START5.match(line)
        five = bool(m)
    if not m:
        if _KEY_ONLY.match(line) and nxt:
            n = _NUM_LINE.match(nxt[0])
            if n:
                title = n.group(6).strip(" -–—:")
                if not _good_title(title, True):
                    return None
                num = f"{n.group(1)} {n.group(2)} {n.group(3)}" + \
                    (f".{n.group(4)}" if n.group(4) else "")
                return num, title or _title_after(nxt[1:])
        return None
    keyword = m.group(1)
    strict = keyword.isupper()
    sep = m.group(6 if not five else 4)
    title = (m.group(5) if five else m.group(7)).strip()
    if not strict and not (sep and title):
        return None                      # "Section 033000 for ..."
    if not strict and not title[:1].isupper():
        return None
    if title and not sep and not _caps(title):
        return None                      # "SECTION 033000 for concrete"
    title = title.strip(" -–—:")
    if not _good_title(title, strict):
        return None
    return _number(m, five), title or _title_after(nxt)


def _title_after(lines):
    """A title printed on the line(s) under the number: capitals, not
    PART 1 or the next heading."""
    out = []
    for x in list(lines)[:2]:
        if _PART.match(x) or _START.match(x) or _START5.match(x) or \
                _END.match(x) or not _caps(x) or \
                any(q in x for q in _QUOTES) or re.search(r"\d", x):
            break
        out.append(x.strip())
    return " ".join(out).strip(" -–—:")


def _bare(line):
    """'00 11 13 - INVITATION TO BID' with no keyword: front-end documents
    (Divisions 00 and 01) in some manuals. Capitals and a separator only."""
    m = _NUM_LINE.match(line)
    if not m or m.group(1) not in ("00", "01") or not m.group(5):
        return None
    title = m.group(6).strip()
    if len(re.sub(r"[^A-Za-z]", "", title)) < 4 or not _caps(title) or \
            re.search(r"\d", title) or any(q in title for q in _QUOTES):
        return None
    num = f"{m.group(1)} {m.group(2)} {m.group(3)}" + \
        (f".{m.group(4)}" if m.group(4) else "")
    return num, title


_END_NUM = re.compile(r"^\s*END\s+OF\s+(?:SECTION|DOCUMENT)\s+(?:" + _NUM6 +
                      r"|(\d{2})(\d{3})(?![\d.]))", re.I)


def _headless(pages, first, last, end_line, listed):
    """A section whose heading didn't come out in the text (an image, a
    scan) but whose "END OF SECTION 061000" did, after pages no section
    claims: it starts at the first of them its footer ("061000 - 1")
    names, and its title is the footer's."""
    m = _END_NUM.match(end_line)
    if not m:
        return None
    if m.group(5):
        b = m.group(6)
        number, digits = f"{m.group(5)} {b[:2]} {b[2]}0", m.group(5) + b
    else:
        number = f"{m.group(1)} {m.group(2)} {m.group(3)}" + \
            (f".{m.group(4)}" if m.group(4) else "")
        digits = "".join(g for g in m.groups()[:3])
    if number in listed:
        return None
    foot = re.compile(r"^\s*" + r"\s?".join(
        [digits[0:2], digits[2:4], digits[4:]]) +
        (r"(?:\.\d{2})?" if not m.group(5) else "") +
        r"\s*[-–—]\s*\d+\s*$")
    start, title = None, ""
    for p in range(first, last + 1):
        texts = [t for _y, t in pages[p]]
        for k, t in enumerate(texts):
            if foot.match(t):
                start = p if start is None else start
                prev = texts[k - 1] if k else ""
                if not title and _caps(prev) and not _END.match(prev):
                    title = prev
        if start is not None and title:
            break
    if start is None:
        return None
    return {"number": number, "title": _clean_title(title), "start": start,
            "end": last}


def _page_lines(page):
    """[(y as a fraction of the page height, text)] top to bottom."""
    h = page.rect.height or 1
    lines = []
    for b in page.get_text("dict")["blocks"]:
        for ln in b.get("lines", []):
            text = "".join(s["text"] for s in ln["spans"]).strip()
            if text:
                lines.append((ln["bbox"][1] / h, ln["bbox"][0], text))
    lines.sort()
    return [(y, t) for y, _x, t in lines]


def _top_lines(page, frac=TOP_FRAC, max_lines=TOP_LINES):
    return [t for y, t in _page_lines(page) if y <= frac][:max_lines]


def _clean_title(title):
    title = " ".join(title.split())
    return title.title() if title.isupper() else title


def sections_in(pages, page_count=None):
    """The section list from page lines: pages = [[(y fraction, text)]]
    (top to bottom). Pure logic, shared by find_sections and the tests."""
    page_count = len(pages) if page_count is None else page_count
    out, listed, cur, gap_from = [], set(), None, None
    for i, lines in enumerate(pages):
        texts = [t for _y, t in lines]
        top_n = sum(1 for y, _t in lines[:TOP_LINES] if y <= TOP_FRAC)
        # a table of contents or a list of sections: many headings at the
        # top of one page - none of them starts a section here
        # (a section's first page listing its related sections in
        # capitals still has its PART 1 heading)
        first = texts[:max(top_n, 1) + 12]
        heads = [heading(t, texts[k + 1:k + 3]) for k, t in enumerate(first)]
        toc = len({h[0] for h in heads if h}) >= 3 and \
            not any(_PART.match(t) for t in texts[:30])
        after_end, top_taken = -99, False
        for k, t in enumerate(texts):
            if _END.match(t):
                if cur is not None and cur["end"] is None:
                    cur["end"] = i
                elif gap_from is not None:
                    lost = _headless(pages, gap_from, i, t, listed)
                    if lost:
                        listed.add(lost["number"])
                        out.append(lost)
                        cur = lost
                gap_from = i + 1
                after_end = k
                continue
            after = k - after_end <= 4
            at_top = k < top_n and not top_taken
            if toc or not (at_top or after):
                continue
            h = heading(t, texts[k + 1:k + 3])
            if h is None and k < min(top_n, 4):
                h = _bare(t)
            if h is None:
                continue
            number, title = h
            if not after:
                top_taken = True         # one heading per page top: the
                                         # rest are its related sections
            if cur is not None and cur["number"] == number:
                continue                 # its running header
            if number in listed:
                continue                 # a quoted copy / a repeat
            if cur is not None and cur["end"] is None:
                cur["end"] = i if after else i - 1
            cur = {"number": number, "title": _clean_title(title),
                   "start": i, "end": None}
            listed.add(number)
            out.append(cur)
    res = []
    for k, s in enumerate(out):
        end = s["end"]
        if end is None:
            end = (out[k + 1]["start"] - 1) if k + 1 < len(out) \
                else page_count - 1
        end = max(end, s["start"])
        div = s["number"][:2]
        res.append(dict(s, end=end, division=div,
                        division_title=csi.division_title(s["number"])
                        or f"Division {div}"))
    return res


def find_sections(doc, progress=None):
    """[{number, title, division, division_title, start, end}] (0-based
    pages, end inclusive), in book order."""
    pages = []
    for i, page in enumerate(doc):
        if progress and progress(i, doc.page_count) is False:
            break
        pages.append(_page_lines(page))
    return sections_in(pages, doc.page_count)


def bookmark(doc, sections, replace=False):
    """Bookmarks: Division NN - Title > NN NN NN - Section title (added
    after the existing ones, or replacing them)."""
    new, last_div = [], None
    for s in sections:
        if s["division"] != last_div:
            new.append([1, f"Division {s['division']} - "
                           f"{s['division_title']}", s["start"] + 1])
            last_div = s["division"]
        new.append([2, f"{s['number']} - {s['title']}", s["start"] + 1])
    doc.set_toc(new if replace else doc.get_toc() + new)
    return len(new)


def split(doc, sections, folder, name_fmt="{number} {title}.pdf"):
    """One PDF per section in `folder`. Returns the file paths."""
    import fitz
    os.makedirs(folder, exist_ok=True)
    paths = []
    for s in sections:
        name = name_fmt.format(number=s["number"], title=s["title"])
        name = re.sub(r'[\\/:*?"<>|]+', "", name)[:120]
        out = fitz.open()
        out.insert_pdf(doc, from_page=s["start"], to_page=s["end"])
        out.set_metadata({"title": f"{s['number']} - {s['title']}"})
        p = os.path.join(folder, name)
        out.save(p, garbage=safeio.gc_level(out), deflate=True)
        out.close()
        paths.append(p)
    return paths
