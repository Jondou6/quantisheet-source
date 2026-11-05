"""Submittals you send to the architect and engineers (0.12.27).

The submittal log itself is Project Center's Submittals tool (schema.py:
numbered by spec section - 08 71 00-001 - with type, responsible
contractor, needed-on-site / lead / review dates and a review workflow).
This module adds the two things a GC does around it:

* package_pdf(store, rec): the submittal as one PDF to send - a cover
  sheet (project, number and revision, CSI section and division, type,
  from / to, dates, what's included), the contractor's review statement
  and a blank review stamp for each reviewer (architect, each engineer),
  then the attached PDFs and photos. Saved in the project's Submittals
  folder and attached to the record, so Send for Review emails it.
* from_spec_book(pdf): the submittal register read from the project
  manual - each section's SUBMITTALS articles ("A. Product Data: ...",
  "B. Shop Drawings: ...") as proposed submittals, to accept and import.
"""
import datetime as _dt
import logging
import os
import re

from .. import csi
from . import schema
from .store import spec_number

log = logging.getLogger(__name__)

STAMP_RESULTS = ["Approved", "Approved as Noted", "Revise and Resubmit",
                 "Rejected", "For Record Only"]
CONTRACTOR_STATEMENT = (
    "The Contractor has reviewed this submittal and certifies that it has "
    "been checked for field measurements, construction criteria, quantities "
    "and coordination with other work, and that it complies with the "
    "Contract Documents except as noted.")
REVIEW_NOTE = (
    "Review is for general conformance with the design concept and the "
    "information given in the Contract Documents. The Contractor remains "
    "responsible for dimensions, quantities, fabrication, coordination and "
    "safety.")


def number(rec):
    rev = int(rec.get("revision") or 0)
    return f"{rec.get('_no', '')} Rev {rev}".strip()


def section_title(store, spec):
    """'08 71 00 Door Hardware' -> 'Door Hardware'; a bare number looks in
    the titles read from the spec book."""
    spec = spec or ""
    sec = spec_number(spec)
    rest = re.sub(r"^\s*\d{2}\s?\d{2}\s?\d{2}(\.\d+)?", "", spec).strip(
        " -–—:") if sec else ""
    if rest:
        return rest
    titles = (store.setting("spec_titles") or {}) if store else {}
    return titles.get(sec, "")


def division(spec):
    sec = spec_number(spec)
    return (sec[:2], csi.DIVISIONS.get(sec[:2], "")) if sec else ("", "")


def reviewers(store, rec):
    names = [s.get("reviewer") for s in rec.get("workflow") or []
             if s.get("reviewer")]
    if not names and store is not None:
        d = store.setting("default_reviewer")
        if d:
            names = [d]
    return names or ["Architect"]


def safe(text):
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", text or "").strip(" .")[:90]


def default_path(store, rec):
    d = os.path.join(store.folder, "Submittals")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, safe(f"{number(rec)} - {rec.get('title', '')}")
                        + ".pdf")


# ------------------------------------------------------------ the package
def _attachments(store, rec):
    out = []
    for a in rec.get("attachments") or []:
        if (a.get("name") or "").startswith("Submittal package "):
            continue                    # an earlier package, not content
        try:
            out.append((a.get("name") or "file", store.attachment_path(a)))
        except Exception:                                 # noqa: BLE001
            log.info("attachment %s not on this PC", a.get("name"))
    return out


def _cover(doc, store, rec, files, today):
    import fitz
    page = doc.new_page(width=612, height=792)          # Letter
    W, x0, x1 = 612, 48, 564
    ink, muted = (0.1, 0.12, 0.15), (0.4, 0.43, 0.47)

    def text(x, y, s, size=10, bold=False, color=ink):
        page.insert_text((x, y), s, fontsize=size, color=color,
                         fontname="hebo" if bold else "helv")

    def box(r, width=0.8):
        page.draw_rect(fitz.Rect(*r), color=ink, width=width)

    def wrap(s, x, y, width, size=9.5, lead=12.5, bold=False):
        words, line = (s or "").split(), ""
        font = fitz.Font("hebo" if bold else "helv")
        for w in words:
            t = (line + " " + w).strip()
            if font.text_length(t, size) > width and line:
                text(x, y, line, size, bold)
                y += lead
                line = w
            else:
                line = t
        if line:
            text(x, y, line, size, bold)
            y += lead
        return y

    text(x0, 60, "SUBMITTAL", 22, True)
    text(x0, 80, store.name, 12, True, muted)
    no = number(rec)
    fw = fitz.Font("hebo").text_length(no, 16)
    text(x1 - fw, 60, no, 16, True)
    sec = spec_number(rec.get("spec"))
    title = section_title(store, rec.get("spec"))
    div, dname = division(rec.get("spec"))
    rows = [
        ("Title", rec.get("title", "")),
        ("Spec section", f"{sec}  {title}".strip()),
        ("CSI division", f"{div}  {dname}".strip()),
        ("Type", rec.get("type", "")),
        ("From (contractor)", rec.get("responsible", "") or
         (store.setting("company") or "")),
        ("To (reviewers)", ", ".join(reviewers(store, rec))),
        ("Date sent", today),
        ("Needed on site", rec.get("required_on_site", "")),
        ("Response needed by", _due(rec, today)),
        ("Copies to", ", ".join(rec.get("cc") or [])),
    ]
    y = 104
    for label, val in rows:
        text(x0, y, label.upper(), 7.5, True, muted)
        y = wrap(str(val or "-"), x0 + 130, y, x1 - x0 - 130, 10) + 3
        page.draw_line((x0, y - 9), (x1, y - 9), color=(0.85, 0.86, 0.88),
                       width=0.4)
    if rec.get("description"):
        text(x0, y + 4, "DESCRIPTION", 7.5, True, muted)
        y = wrap(rec["description"], x0, y + 18, x1 - x0) + 4
    text(x0, y + 6, "INCLUDED", 7.5, True, muted)
    y += 20
    if files:
        for name, pages in files:
            y = wrap(f"•  {name}" + (f"  ({pages} page"
                                     f"{'s' if pages != 1 else ''})"
                                     if pages else ""), x0, y, x1 - x0, 9.5)
    else:
        y = wrap("(nothing attached yet)", x0, y, x1 - x0, 9.5)
    # the contractor's review
    y = max(y + 10, 470)
    box((x0, y, x1, y + 70))
    text(x0 + 8, y + 14, "CONTRACTOR'S REVIEW", 8, True)
    yy = wrap(CONTRACTOR_STATEMENT, x0 + 8, y + 28, x1 - x0 - 16, 8, 10)
    text(x0 + 8, y + 62, "By: ____________________________     "
         "Date: ______________", 8.5)
    # one review stamp per reviewer, two across
    y += 82
    names = reviewers(store, rec)[:4]
    bw = (x1 - x0 - 10) / 2
    for i, who in enumerate(names):
        bx = x0 + (i % 2) * (bw + 10)
        by = y + (i // 2) * 120
        if by + 112 > 760:
            break
        box((bx, by, bx + bw, by + 112))
        text(bx + 8, by + 14, f"REVIEW - {who}".upper()[:42], 8, True)
        for j, res in enumerate(STAMP_RESULTS):
            cy = by + 28 + j * 13
            page.draw_rect(fitz.Rect(bx + 8, cy - 7, bx + 15, cy),
                           color=ink, width=0.6)
            text(bx + 20, cy, res, 8)
        text(bx + 8, by + 104, "By: ______________   Date: ________", 8)
    note_y = min(y + ((len(names) + 1) // 2) * 120 + 4, 772)
    wrap(REVIEW_NOTE, x0, note_y, x1 - x0, 6.5, 8)
    return page


def _due(rec, today):
    days = int(rec.get("review_days") or 10)
    try:
        from .schema import workdays_from
        return workdays_from(_dt.date.fromisoformat(today), days).isoformat()
    except Exception:                                     # noqa: BLE001
        return ""


def package_pdf(store, rec, path=None, today=None):
    """Cover sheet + attachments as one PDF. Returns its path."""
    import fitz
    today = today or _dt.date.today().isoformat()
    path = path or default_path(store, rec)
    parts = []
    for name, src in _attachments(store, rec):
        ext = os.path.splitext(src)[1].lower()
        try:
            if ext == ".pdf":
                d = fitz.open(src)
                parts.append((name, d, d.page_count))
            elif ext in (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"):
                img = fitz.open(src)
                d = fitz.open("pdf", img.convert_to_pdf())
                parts.append((name, d, d.page_count))
            else:
                parts.append((name, None, 0))           # listed, not merged
        except Exception:                                 # noqa: BLE001
            log.warning("couldn't add %s to the package", name,
                        exc_info=True)
            parts.append((name, None, 0))
    out = fitz.open()
    _cover(out, store, rec, [(n, c) for n, _d, c in parts], today)
    toc = [[1, f"Submittal {number(rec)}", 1]]
    for name, d, _c in parts:
        if d is None:
            continue
        toc.append([1, name, out.page_count + 1])
        out.insert_pdf(d)
        d.close()
    out.set_toc(toc)
    out.set_metadata({"title": f"Submittal {number(rec)} - "
                               f"{rec.get('title', '')}",
                      "subject": f"{store.name} - spec section "
                                 f"{spec_number(rec.get('spec'))}",
                      "creator": "QuantiSheet", "producer": "QuantiSheet"})
    tmp = path + ".tmp"
    out.save(tmp, garbage=3, deflate=True)
    out.close()
    os.replace(tmp, path)
    return path


def attach_package(store, rec, path):
    """Keep the package on the record (one per revision) so Send for Review
    mails it. Returns the updated record (not yet saved)."""
    rec = dict(rec)
    name = f"Submittal package {number(rec)}.pdf"
    ref = store.attach(path)
    ref["name"] = name
    atts = [a for a in rec.get("attachments") or []
            if a.get("name") != name]
    rec["attachments"] = atts + [ref]
    return rec


# ------------------------------------------------------- from the specs
# a section's own heading, in capitals: "SECTION 033000 - CAST-IN-PLACE
# CONCRETE". Not the cross references in the text ('Section 031000
# "Concrete Forming and Accessories" for ...'), which would end the
# section being read.
_SECTION = re.compile(
    r"^\s*SECTION\s+(\d{2})\s?(\d{2})\s?(\d{2})(\.\d+)?\s*(?:[-–—:]\s*)?"
    r"([^a-z]*)$")
_ARTICLE = re.compile(r"^\s*(\d{1,2}\.\d{1,2})\s+([A-Z][A-Z0-9 ,&/()\-–—']+)"
                      r"\s*$")
_PART = re.compile(r"^\s*PART\s+([1-3]|I{1,3}|ONE|TWO|THREE)\b", re.I)
_PART_NO = {"I": "1", "II": "2", "III": "3", "ONE": "1", "TWO": "2",
            "THREE": "3"}
_ITEM = re.compile(r"^\s*([A-Z])\.\s+(.+)$")
# a numbered paragraph: "1. Product Data: ..." / "2) Shop Drawings: ..."
# (not an article number, "1.4 SUBMITTALS")
_NUM_ITEM = re.compile(r"^\s*(\d{1,2})[.)]\s+(?!\d)(.+)$")
_NUM_ALONE = re.compile(r"^\s*\d{1,2}[.)]\s*$")
# "Product Data:", "Shop Drawings:", "Samples for Verification:" opening
# a line: a submittal of its own wherever the paragraph numbers ended up
_TYPED_LABEL = re.compile(r"^\s*([A-Z][A-Za-z0-9 ,&/()'\-–—]{2,70}):(?:\s|$)")
# the article's opening paragraph about procedures, not a submittal:
# "Submit under provisions of Section 01300.", "Submit the following:",
# "See Section 01 33 00 for submittal procedures."
_INTRO = re.compile(
    r"^\s*(?:submit\b|submittals?\b|see\b|refer\b|comply\b|conform\b|"
    r"in accordance\b|make submittals|provide submittals|general\b|"
    r"procedures?\b|action submittals|informational submittals|"
    r"the following|section\s+\d)", re.I)
_END = re.compile(r"^\s*END\s+OF\s+SECTION", re.I)
TYPE_WORDS = [
    ("Shop Drawings", ("shop drawing", "coordination drawing")),
    ("Product Data", ("product data", "product schedule")),
    ("Samples", ("sample",)),
    ("Mock-up", ("mockup", "mock-up")),
    ("Calculations", ("delegated-design", "delegated design", "calculation",
                      "structural analysis")),
    ("Test Reports", ("test report", "field quality-control",
                      "source quality-control", "evaluation report",
                      "test and evaluation")),
    ("Certificates", ("certificate", "qualification data", "certification",
                      "installer qualification", "manufacturer qualification")),
    ("O&M Manuals", ("operation and maintenance", "maintenance data",
                     "operation data")),
    ("Warranty", ("warrant",)),
    ("LEED / Sustainability", ("leed", "sustainab", "recycled content",
                               "voc", "environmental product")),
    ("Closeout", ("record drawing", "record documents", "closeout",
                  "maintenance material", "extra stock", "attic stock")),
    ("Design Data", ("design data", "schedule", "submittal schedule",
                     "mixture", "mix design")),
]


def type_of(label):
    low = (label or "").lower()
    for t, words in TYPE_WORDS:
        if any(w in low for w in words):
            return t
    return "Other"


def _label(text):
    """'Product Data: For each type of product.' -> ('Product Data',
    'For each type of product.')"""
    if ":" in text[:80]:
        a, b = text.split(":", 1)
        return a.strip(" ."), b.strip()
    words = text.split(".")[0]
    return words.strip()[:60], text.strip()


_NUM_ONLY = re.compile(r"^\s*(?:\d{1,2}\.\d{1,2}|\d{1,2}\.|[a-z]\.|"
                       r"\d{1,2}\)|[a-z]\))\s*$")
_LETTER_ONLY = re.compile(r"^\s*([A-Z])\.\s*$")
_CAPS_HEAD = re.compile(r"^\s*(?:\d{1,2}\.\d{1,2}\s+)?([A-Z][A-Z0-9 ,&/()\-–—'.]+)"
                        r"\s*$")
_NUM_HEAD = re.compile(r"^\s*\d{1,2}\.\d{1,2}\s+([A-Z][A-Za-z0-9 ,&/()\-–—']+)"
                       r"\s*$")


def _heading(line):
    """The article heading on a line ('ACTION SUBMITTALS', '1.3
    SUBMITTALS', '1.4 Submittals'), or None. Project manuals in the
    usual CSI 3-part format print the article number and its heading in
    separate columns, so text extraction often gives the number on a
    line of its own, sometimes lines away: the heading is recognised by
    being a short line in capitals, with or without its number."""
    m = _NUM_HEAD.match(line)
    if m and len(m.group(1).split()) <= 8 and not m.group(1).endswith("."):
        return m.group(1).strip()
    m = _CAPS_HEAD.match(line)
    if not m:
        return None
    h = m.group(1).strip()
    toks = h.split()
    if not 1 <= len(toks) <= 8 or h.endswith(":"):
        return None
    if sum(ch.isalpha() for ch in h) < 4 or \
            not any(sum(c.isalpha() for c in t) >= 4 for t in toks):
        return None                      # "ACI 117", "ASTM C 94"
    if sum(any(c.isdigit() for c in t) for t in toks) > 1:
        return None
    return h


def _boilerplate(pages):
    """Running headers and footers: lines (numbers ignored) printed at the
    top or bottom of 3 or more pages, and mostly only there - the project
    name, the section title in the footer, '033000 - 4'."""
    edge, every = {}, {}
    for text in pages:
        lines = [ln.strip() for ln in (text or "").splitlines()
                 if ln.strip()]
        seen = set()
        for i, ln in enumerate(lines):
            if _SECTION.match(ln) or _PART.match(ln) or _END.match(ln) or \
                    _LETTER_ONLY.match(ln) or "SUBMITTAL" in ln.upper():
                continue                 # the structure, never boilerplate
            k = re.sub(r"[\d\s\-–—.]+", " ", ln).strip().upper()
            if not k or k in seen:
                continue
            seen.add(k)
            every[k] = every.get(k, 0) + 1
            if i < 6 or i >= len(lines) - 5:
                edge[k] = edge.get(k, 0) + 1
    return {k for k, n in edge.items()
            if n >= 3 and n >= 0.6 * every.get(k, n)}


_PROCEDURAL = re.compile(
    r"\b(?:the following|under (?:the )?provisions|in accordance with|"
    r"as specified in|as required by|requirements? (?:of|in)|per|comply "
    r"with|see|refer to)\s+(?:the\s+)?(?:division|section)|"
    r"\bsection\s+01\s?\d{2}|\bdivision\s+(?:0?1|one)\b|"
    r"for information only|submittal procedures|:\s*$", re.I)


def _is_intro(text):
    """A procedural paragraph ('Submit the following:', 'General: Submit
    in accordance with Section 01 33 00') rather than a submittal ('Submit
    TAB strategies and step-by-step procedures' is one)."""
    label, _d = _label(text)
    if type_of(label) != "Other" or not _INTRO.match(text):
        return False
    return bool(_PROCEDURAL.search(text)) or \
        bool(re.match(r"^\s*(?:see|refer)\b", text, re.I))


def _section_line(line, nxt, at_top):
    """(number, title, lines to skip) when `line` is a section heading.
    In capitals ('SECTION 033000 - CAST-IN-PLACE CONCRETE') anywhere (the
    caller still wants a page top, or the end of the last section); in
    title case ('Section 26 05 19 - Low-Voltage Conductors', 'DOCUMENT
    00 11 13') only at the top of a page, where a cross reference
    ('Section 031000 "Concrete Forming ..." for ...') isn't one."""
    m = _SECTION.match(line)
    if m:
        new = f"{m.group(1)} {m.group(2)} {m.group(3)}" + (m.group(4) or "")
        return new, m.group(5).strip(" -–—"), 0
    if not at_top:
        return None
    from .. import specs
    h = specs.heading(line, nxt)
    if h is None:
        return None
    if specs._KEY_ONLY.match(line):            # SECTION / 03 30 00 / TITLE
        nm = specs._NUM_LINE.match(nxt[0])
        return h[0], nm.group(6).strip(" -–—:"), 1
    raw = specs._START.match(line) or specs._START5.match(line)
    return h[0], raw.groups()[-1].strip(" -–—:"), 0


_FOOT1 = re.compile(r"^\s*(\d{2})\s?(\d{2})\s?(\d{2})(\.\d{2})?\s*[-–—]\s*1\s*$")


def _footer_section(lines):
    """(number, title) from a first page's footer ("ROUGH CARPENTRY" /
    "061000 - 1") when the section's heading isn't in the text."""
    for k, ln in enumerate(lines):
        m = _FOOT1.match(ln)
        if m:
            prev = lines[k - 1] if k else ""
            title = prev.strip().title() if prev.isupper() and \
                not re.search(r"\d", prev) else ""
            return (f"{m.group(1)} {m.group(2)} {m.group(3)}" +
                    (m.group(4) or ""), title)
    return None


def from_spec_text(pages):
    """[page text] -> proposed submittals [{"spec", "section", "type",
    "title", "description", "page"}] from each section's submittal
    articles in PART 1 (SUBMITTALS, ACTION SUBMITTALS, INFORMATIONAL
    SUBMITTALS, CLOSEOUT SUBMITTALS...), each lettered paragraph
    ("A. Product Data: ...") one proposal.

    Phase 2 (Colleton, 0 from 142 sections): article numbers "1.4" or
    "1.04", on the heading's line or the line above; "PART 1 - GENERAL",
    "PART 1  GENERAL", "PART ONE"; a book with no PART headings; title-
    case and DOCUMENT headings; submittals numbered 1./2. instead of
    lettered, or listed under a procedural "A. Submit the following:"."""
    out, sec, stitle, part, in_sub, cur = [], None, "", None, False, None
    want_title = False
    item_next = None                 # a paragraph letter on its own line
    letters = False                  # the article has lettered paragraphs
    intro = False                    # ... and the current one is procedural
    seen_secs = set()
    ended = False                    # past an END OF SECTION
    skip = _boilerplate(pages)

    def flush():
        nonlocal cur
        if cur:
            text = " ".join(cur["lines"])
            if _is_intro(text):
                cur = None               # procedures, not a submittal
                return
            label, desc = _label(text)
            if label and len(label) <= 80:
                out.append({"spec": sec, "section": stitle,
                            "type": type_of(label),
                            "title": f"{stitle} - {label}" if stitle
                            else label,
                            "description": desc[:600], "page": cur["page"]})
        cur = None

    for pno, text in enumerate(pages):
        lines = [ln.strip() for ln in (text or "").splitlines()
                 if ln.strip()]
        drop = 0
        for k, line in enumerate(lines):
            if drop:
                drop -= 1
                continue
            # a title-case heading only above the page's first paragraph
            top = k < 10 and not any(
                _PART.match(x) or _ITEM.match(x) or _NUM_ITEM.match(x) or
                _LETTER_ONLY.match(x) or _NUM_ONLY.match(x)
                for x in lines[:k])
            h = _section_line(line, lines[k + 1:k + 3], top)
            if h:
                new, title, drop = h
                if new == sec:               # the section repeated as a
                    continue                 # page header
                if new in seen_secs:         # a quoted copy, a repeat
                    continue
                if sec is not None and not top:
                    continue                 # "SECTION 312000 - EARTH
                                             # MOVING" in a related list
                flush()
                sec = new
                seen_secs.add(new)
                stitle = title.title() if title.isupper() else title
                want_title = not stitle
                part, in_sub, item_next = None, False, None
                letters = intro = False
                continue
            if re.sub(r"[\d\s\-–—.]+", " ", line).strip().upper() in skip:
                continue
            if want_title and sec:
                if not _PART.match(line):
                    stitle = line.strip(" -–—").title()[:80]
                want_title = False
            if sec is None and ended and _PART.match(line):
                found = _footer_section(lines)
                if found and found[0] not in seen_secs:
                    sec, stitle = found         # its heading didn't come
                    seen_secs.add(sec)          # out in the text
                    want_title, item_next = False, None
                    letters = intro = False
            if sec is None:
                continue
            if _END.match(line):
                flush()                  # what follows (blank pages, a
                sec = None               # utility's standards) is no
                ended = True             # section's
                in_sub, part, item_next = False, None, None
                continue
            m = _PART.match(line)
            if m:
                flush()
                part = _PART_NO.get(m.group(1).upper(), m.group(1))
                in_sub, item_next = False, None
                continue
            if _NUM_ONLY.match(line) or not re.search(r"[A-Za-z]", line):
                continue             # a number alone, a date, a job no.
            m = _LETTER_ONLY.match(line)
            if m:
                if in_sub:
                    flush()
                    item_next = m.group(1)
                    letters, intro = True, False
                continue
            # PART 1, or a book that prints no PART headings
            h = _heading(line) if part in ("1", None) else None
            if h is not None:
                flush()
                in_sub = "SUBMITTAL" in h.upper()
                item_next = None
                letters = intro = False
                continue
            if not in_sub:
                continue
            m = _ITEM.match(line)
            n = _NUM_ITEM.match(line)
            lab = _TYPED_LABEL.match(line)
            if m:
                flush()
                cur = {"lines": [m.group(2)], "page": pno + 1}
                item_next = None
                letters, intro = True, _is_intro(m.group(2))
            elif item_next is not None:
                flush()
                cur = {"lines": [line], "page": pno + 1}
                item_next = None
                letters, intro = True, _is_intro(line)
            elif n and (not letters or intro):
                # numbered submittals: the article's own paragraphs, or the
                # list under "A. Submit the following:"
                flush()
                cur = {"lines": [n.group(2)], "page": pno + 1}
            elif lab and (not letters or intro or cur is None) and \
                    type_of(lab.group(1)) != "Other":
                flush()                  # "Product Data: ..." whose number
                cur = {"lines": [line], "page": pno + 1}   # came apart
            elif cur is not None and not re.match(r"^\s*\d\.\s", line):
                if len(" ".join(cur["lines"])) < 700:
                    cur["lines"].append(line)
    flush()
    # one proposal per section + label
    seen, uniq = set(), []
    for p in out:
        k = (p["spec"], p["title"].lower())
        if k not in seen:
            seen.add(k)
            uniq.append(p)
    return uniq


def from_spec_book(path):
    import fitz
    with fitz.open(path) as d:
        return from_spec_text([pg.get_text() for pg in d])


_STOP = {"and", "for", "the", "with", "of", "to", "in", "on", "a", "an",
         "general", "requirements", "systems", "system", "work", "products",
         "materials", "assemblies", "installation", "miscellaneous"}


def sheet_labels(doc):
    """[(page, sheet number or 'p N')] for a drawing set."""
    try:
        from .. import doccontrol
        reg = {s["page"]: s["number"] for s in doccontrol.register(doc)
               if s.get("page") is not None}
    except Exception:                                     # noqa: BLE001
        reg = {}
    return [(i, reg.get(i) or f"p{i + 1}") for i in range(doc.page_count)]


def link_sheets(proposals, drawings, max_sheets=12):
    """Nov 3 (#14): the drawing sheets each submittal's work is on - the
    sheets whose text cites its spec section (09 21 16 / 092116) or names
    its section's main words ("Gypsum Board"). Sets p["sheets"] in place;
    returns how many got sheets."""
    import re
    if drawings is None:
        return 0
    labels = sheet_labels(drawings)
    texts = []
    for i, lab in labels:
        try:
            t = drawings[i].get_text("text")
        except Exception:                                 # noqa: BLE001
            t = ""
        texts.append((lab, " ".join(t.split()).lower(),
                      re.sub(r"\D", "", t)))
    n = 0
    for p in proposals:
        sec = spec_number(p.get("spec")) or ""
        digits = re.sub(r"\D", "", sec)
        words = [w for w in re.findall(r"[a-z]{4,}",
                                       str(p.get("section") or "").lower())
                 if w not in _STOP][:3]
        phrase = " ".join(words)
        hits = []
        for lab, txt, dig in texts:
            spaced = " ".join([digits[i:i + 2] for i in range(0, 6, 2)])
            if (len(digits) >= 6 and (spaced in txt or digits[:6] in dig)) \
                    or (len(words) >= 2 and phrase in txt):
                hits.append(lab)
        if hits:
            p["sheets"] = ", ".join(hits[:max_sheets]) + (
                " ..." if len(hits) > max_sheets else "")
            n += 1
    return n


def import_register(store, proposals, responsible=""):
    """Save the chosen proposals as submittals (Not Submitted), skipping
    ones already in the log (same spec section and title). Also remembers
    the section titles. Returns the new records."""
    have = {(spec_number(r.get("spec")), (r.get("title") or "").lower())
            for r in store.list("submittal")}
    titles = dict(store.setting("spec_titles") or {})
    made = []
    for p in proposals:
        sec = spec_number(p.get("spec"))
        if not sec:
            continue
        if p.get("section"):
            titles.setdefault(sec, p["section"])
        if (sec, p["title"].lower()) in have:
            continue
        typ = p.get("type") if p.get("type") in schema.SUBMITTAL_TYPES \
            else "Other"
        rec = {"title": p["title"][:120],
               "spec": f"{sec} {p.get('section', '')}".strip(),
               "type": typ, "status": "Not Submitted",
               "responsible": responsible, "revision": 0,
               "review_days": 10, "lead_days": 0,
               "description": p.get("description", ""),
               "sheets": p.get("sheets", "")}
        made.append(store.save_record("submittal", rec))
        have.add((sec, p["title"].lower()))
    store.set_setting("spec_titles", titles)
    return made
